"""
Servidor web (FastAPI) de Piña Transcribe.

- API JSON en /api/* (trabajos, modelos, información del equipo).
- Interfaz estática en web/ (HTML + CSS + JS sin dependencias externas),
  con modo claro/oscuro e idiomas español/inglés resueltos en el navegador.
- Los errores llevan un ``code`` estable para que la interfaz los traduzca.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app_metadata import APP_CHANGES, APP_NAME, APP_REPO, APP_VERSION, UPDATED_AT
from utils.downloader import DownloadError
from utils.helpers import project_root
from utils.pipeline import run_transcription_job
from utils.platform_handler import PlatformError
from utils.system_info import system_summary
from utils.timecode import parse_timecode
from utils.transcriber import TranscriptionError
from utils.whisper_models import ALLOWED_MODELS, validate_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_server")

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; connect-src 'self'; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


_MAX_HISTORY = 24

_jobs_lock = threading.Lock()
_jobs: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_busy = threading.Lock()


_YT_URL_RE = re.compile(
    r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/|youtube\.com/shorts/|"
    r"youtube\.com/embed/|youtube\.com/live/)([A-Za-z0-9_-]{11})"
)
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TWITCH_VOD_RE = re.compile(r"twitch\.tv/(?:[^/]+/)?videos?/(\d+)")
_TWITCH_ID_RE = re.compile(r"^\d+$")


def _api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _parse_source(platform: str, raw: str) -> str:
    """
    Acepta un ID puro o una URL y devuelve el ID limpio.
    Lanza ValueError con mensaje legible si no encaja.
    """
    v = raw.strip().replace(" ", "")
    if not v:
        raise ValueError("El campo de video esta vacio.")
    if platform == "youtube":
        if _YT_ID_RE.match(v):
            return v
        m = _YT_URL_RE.search(v)
        if m:
            return m.group(1)
        raise ValueError(
            "ID/URL de YouTube no reconocido. Pega una URL de youtube.com / "
            "youtu.be o un ID de 11 caracteres."
        )
    if platform == "twitch":
        if _TWITCH_ID_RE.match(v):
            return v
        m = _TWITCH_VOD_RE.search(v)
        if m:
            return m.group(1)
        raise ValueError(
            "ID/URL de Twitch VOD no reconocido. Pega una URL "
            "twitch.tv/videos/NUMERO o un ID numerico."
        )
    raise ValueError(f"Plataforma desconocida: {platform!r}")


class JobCreate(BaseModel):
    platform: Literal["youtube", "twitch"]
    video_id: str = Field(..., min_length=1, max_length=500)
    model: str = "tiny"
    lang: str | None = Field(default="", max_length=8)
    device: Literal["auto", "cpu", "gpu"] = "auto"
    # Compatibilidad con clientes 2.x: si llega, manda sobre ``device``.
    force_cpu: bool | None = None
    start: str | float | None = None
    end: str | float | None = None


def _outputs_root() -> Path:
    return project_root() / "outputs"


def _job_summary(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    res = job.get("result") or {}
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "phase": job.get("phase", ""),
        "message": job.get("message", ""),
        "error_code": job.get("error_code"),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
        "platform": job.get("platform"),
        "video_id": job.get("video_id"),
        "model": job.get("model"),
        "start_seconds": job.get("start_seconds"),
        "end_seconds": job.get("end_seconds"),
        "title": res.get("title"),
        "language": res.get("language"),
        "url": res.get("url"),
    }


def _public_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resultado sin rutas internas del servidor."""
    if not result:
        return None
    hidden = {"output_path", "srt_path"}
    return {k: v for k, v in result.items() if k not in hidden}


def _trim_history() -> None:
    while len(_jobs) > _MAX_HISTORY:
        for jid, j in list(_jobs.items()):
            if j.get("status") in ("done", "error"):
                _jobs.pop(jid, None)
                break
        else:
            break


def _error_code(exc: Exception) -> str:
    if isinstance(exc, (DownloadError, TranscriptionError)):
        return exc.code
    if isinstance(exc, PlatformError):
        return "invalid_source"
    if isinstance(exc, ValueError):
        return "invalid_request"
    return "unexpected"


def _worker(job_id: str, payload: JobCreate, video_id: str, force_cpu: bool) -> None:
    lang = (payload.lang or "").strip().lower() or None

    def on_progress(phase: str, pct: float, msg_key: str) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["phase"] = phase
                _jobs[job_id]["progress"] = round(pct, 1)
                _jobs[job_id]["message"] = msg_key

    try:
        with _jobs_lock:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["message"] = "init.start"

        result = run_transcription_job(
            platform_raw=payload.platform,
            video_id=video_id,
            model=payload.model,
            lang=lang,
            force_cpu=force_cpu,
            start_seconds=_jobs[job_id]["start_seconds"],
            end_seconds=_jobs[job_id]["end_seconds"],
            on_progress=on_progress,
        )

        with _jobs_lock:
            _jobs[job_id].update(
                status="done",
                progress=100,
                phase="done",
                message="done",
                finished_at=time.time(),
                result=result,
            )
    except Exception as e:
        logger.exception("Job fallido")
        with _jobs_lock:
            _jobs[job_id].update(
                status="error",
                finished_at=time.time(),
                message=str(e),
                error=str(e),
                error_code=_error_code(e),
            )
    finally:
        _busy.release()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _ordered_models() -> list[str]:
    order = [
        "tiny", "tiny.en", "base", "base.en",
        "small", "small.en", "medium", "medium.en",
        "large-v1", "large-v2", "large-v3", "large",
    ]
    return [m for m in order if m in ALLOWED_MODELS]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION, "updated_at": UPDATED_AT}


@app.get("/api/about")
async def api_about() -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "updated_at": UPDATED_AT,
        "repo": APP_REPO,
        "changes": {lang: list(items) for lang, items in APP_CHANGES.items()},
    }


@app.get("/api/models")
async def api_models() -> dict[str, list[str]]:
    return {"models": _ordered_models()}


@app.get("/api/system")
async def api_system() -> dict[str, Any]:
    return system_summary()


@app.get("/api/jobs")
async def list_jobs() -> dict[str, list[dict[str, Any]]]:
    with _jobs_lock:
        items = [_job_summary(jid, j) for jid, j in reversed(_jobs.items())]
    return {"jobs": items}


@app.post("/api/jobs")
async def create_job(payload: JobCreate) -> JSONResponse:
    try:
        validate_model(payload.model)
    except ValueError as e:
        raise _api_error(400, "invalid_model", str(e)) from e

    try:
        clean_id = _parse_source(payload.platform, payload.video_id)
    except ValueError as e:
        raise _api_error(400, "invalid_source", str(e)) from e

    try:
        start_s = parse_timecode(payload.start)
        end_s = parse_timecode(payload.end)
    except ValueError as e:
        raise _api_error(400, "invalid_time", str(e)) from e
    if start_s == 0:
        start_s = None if end_s is None else 0.0
    if start_s is not None and end_s is not None and end_s <= start_s:
        raise _api_error(400, "invalid_range", "El fin debe ser posterior al inicio.")

    if payload.force_cpu is not None:
        force_cpu = payload.force_cpu
    else:
        force_cpu = payload.device == "cpu"

    if not _busy.acquire(blocking=False):
        raise _api_error(429, "busy", "Ya hay una transcripcion en curso. Espera a que termine.")

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "phase": "init",
            "message": "init.queued",
            "result": None,
            "error": None,
            "error_code": None,
            "created_at": time.time(),
            "finished_at": None,
            "platform": payload.platform,
            "video_id": clean_id,
            "model": payload.model.strip().lower(),
            "start_seconds": start_s,
            "end_seconds": end_s,
        }
        _trim_history()

    t = threading.Thread(
        target=_worker, args=(job_id, payload, clean_id, force_cpu), daemon=True
    )
    t.start()
    return JSONResponse({"job_id": job_id, "video_id": clean_id})


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise _api_error(404, "job_not_found", "Job no encontrado")
        data = {**job, "result": _public_result(job.get("result"))}
    return {"job_id": job_id, **data}


@app.get("/api/jobs/{job_id}/download")
async def download_file(job_id: str, format: Literal["txt", "srt"] = "txt") -> FileResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["status"] != "done" or not job.get("result"):
        raise _api_error(404, "not_available", "No disponible")
    key = "srt_path" if format == "srt" else "output_path"
    raw_path = job["result"].get(key)
    if not raw_path:
        raise _api_error(404, "not_available", "No disponible")
    path = Path(raw_path).resolve()
    root = _outputs_root().resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise _api_error(400, "invalid_path", "Ruta invalida") from None
    if not path.is_file():
        raise _api_error(404, "file_missing", "Archivo no encontrado")
    media = "application/x-subrip" if format == "srt" else "text/plain"
    return FileResponse(path, filename=path.name, media_type=f"{media}; charset=utf-8")


# ---------------------------------------------------------------------------
# Interfaz
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(
        WEB_DIR / "favicon.svg",
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def create_app() -> FastAPI:
    return app
