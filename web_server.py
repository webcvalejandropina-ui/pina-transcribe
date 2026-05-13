"""
Servidor web (FastAPI) en puerto 15000.

Interfaz editorial inspirada en el sistema de diseno descrito en DESIGN.md
(negro/blanco/soft-cloud, pills, tipografia editorial). Soporta URLs completas
de YouTube/Twitch ademas de IDs, historial reciente y reanudacion por hash.
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

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from utils.helpers import project_root
from utils.pipeline import run_transcription_job
from utils.whisper_models import ALLOWED_MODELS, validate_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_server")

app = FastAPI(title="piña-transcribe", version="2.0")

_MAX_HISTORY = 24

_jobs_lock = threading.Lock()
_jobs: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_busy = threading.Lock()


_YT_URL_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|"
    r"youtube\.com/embed/|youtube\.com/live/)([A-Za-z0-9_-]{11})"
)
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_TWITCH_VOD_RE = re.compile(r"twitch\.tv/videos/(\d+)")
_TWITCH_ID_RE = re.compile(r"^\d+$")


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
    video_id: str = Field(..., min_length=1)
    model: str = "tiny"
    lang: str | None = ""
    force_cpu: bool = True


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
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
        "platform": job.get("platform"),
        "video_id": job.get("video_id"),
        "model": job.get("model"),
        "title": res.get("title"),
        "language": res.get("language"),
        "url": res.get("url"),
    }


def _trim_history() -> None:
    while len(_jobs) > _MAX_HISTORY:
        for jid, j in list(_jobs.items()):
            if j.get("status") in ("done", "error"):
                _jobs.pop(jid, None)
                break
        else:
            break


def _worker(job_id: str, payload: JobCreate, video_id: str) -> None:
    lang = (payload.lang or "").strip() or None

    def on_progress(phase: str, pct: float, msg: str) -> None:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["phase"] = phase
                _jobs[job_id]["progress"] = round(pct, 1)
                _jobs[job_id]["message"] = msg

    try:
        with _jobs_lock:
            _jobs[job_id]["status"] = "running"
            _jobs[job_id]["progress"] = 0
            _jobs[job_id]["message"] = "Iniciando..."

        result = run_transcription_job(
            platform_raw=payload.platform,
            video_id=video_id,
            model=payload.model,
            lang=lang,
            force_cpu=payload.force_cpu,
            on_progress=on_progress,
        )

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["progress"] = 100
            _jobs[job_id]["message"] = "Listo"
            _jobs[job_id]["finished_at"] = time.time()
            _jobs[job_id]["result"] = result
    except Exception as e:
        logger.exception("Job fallido")
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["finished_at"] = time.time()
            _jobs[job_id]["message"] = str(e)
            _jobs[job_id]["error"] = str(e)
    finally:
        _busy.release()


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    models_opts = "".join(
        f'<button type="button" class="chip" data-value="{m}" '
        f'role="radio" aria-checked="false">{m}</button>'
        for m in _ordered_models()
    )
    return _render_page(models_opts)


def _ordered_models() -> list[str]:
    order = [
        "tiny", "tiny.en", "base", "base.en",
        "small", "small.en", "medium", "medium.en",
        "large-v1", "large-v2", "large-v3", "large",
    ]
    return [m for m in order if m in ALLOWED_MODELS]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
async def api_models() -> dict[str, list[str]]:
    return {"models": _ordered_models()}


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
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        clean_id = _parse_source(payload.platform, payload.video_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not _busy.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="Ya hay una transcripcion en curso. Espera a que termine.",
        )

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "phase": "queued",
            "message": "En cola",
            "result": None,
            "error": None,
            "created_at": time.time(),
            "finished_at": None,
            "platform": payload.platform,
            "video_id": clean_id,
            "model": payload.model,
        }
        _trim_history()

    t = threading.Thread(target=_worker, args=(job_id, payload, clean_id), daemon=True)
    t.start()
    return JSONResponse({"job_id": job_id, "video_id": clean_id})


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"job_id": job_id, **job}


@app.get("/api/jobs/{job_id}/download")
async def download_txt(job_id: str) -> FileResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job or job["status"] != "done" or not job.get("result"):
        raise HTTPException(status_code=404, detail="No disponible")
    path = Path(job["result"]["output_path"]).resolve()
    root = _outputs_root().resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ruta invalida") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path, filename=path.name, media_type="text/plain; charset=utf-8")


def create_app() -> FastAPI:
    return app


# ---------------------------------------------------------------------------
# UI (HTML/CSS/JS embebido)
# ---------------------------------------------------------------------------


def _render_page(models_opts: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>PIÑA-TRANSCRIBE / Transcripcion local</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
  --ink:#111111;
  --on-primary:#ffffff;
  --canvas:#ffffff;
  --soft-cloud:#f5f5f5;
  --charcoal:#39393b;
  --mute:#707072;
  --stone:#9e9ea0;
  --hairline:#cacacb;
  --hairline-soft:#e5e5e5;
  --sale:#d30005;
  --success:#007d48;
  --sans:'Inter','Helvetica Neue',Helvetica,Arial,sans-serif;
  --display:'Bebas Neue','Inter','Helvetica Neue',sans-serif;
}}
* {{ box-sizing:border-box; }}
html,body {{ margin:0; padding:0; background:var(--canvas); color:var(--ink); font-family:var(--sans); }}
body {{ min-height:100vh; -webkit-font-smoothing:antialiased; }}

/* utility-bar */
.utility-bar {{
  background:var(--soft-cloud);
  height:36px;
  display:flex; align-items:center; justify-content:space-between;
  padding:0 32px;
  font-size:12px; font-weight:500;
}}
.utility-bar .group {{ display:flex; gap:24px; }}
.utility-bar a {{ color:var(--ink); text-decoration:none; }}
.utility-bar .meta {{ color:var(--mute); }}

/* primary-nav */
.primary-nav {{
  background:var(--canvas);
  height:64px;
  display:flex; align-items:center; justify-content:space-between;
  padding:0 32px;
  box-shadow:inset 0 -1px 0 var(--hairline-soft);
  position:sticky; top:0; z-index:50;
}}
.brand {{
  font-family:var(--display); font-size:32px; letter-spacing:0;
  line-height:1; color:var(--ink);
}}
.brand span {{ color:var(--mute); margin-left:8px; font-size:14px; font-family:var(--sans); font-weight:500; letter-spacing:0.04em; }}
.nav-right {{ display:flex; align-items:center; gap:12px; }}
.nav-link {{ font-weight:500; font-size:16px; color:var(--ink); text-decoration:none; }}
.status-dot {{
  display:inline-flex; align-items:center; gap:8px;
  font-size:12px; font-weight:500; color:var(--mute);
}}
.status-dot .pulse {{
  width:8px; height:8px; border-radius:9999px; background:var(--success);
  box-shadow:0 0 0 0 rgba(0,125,72,0.5);
  animation:pulse 2s infinite;
}}
@keyframes pulse {{
  0%   {{ box-shadow:0 0 0 0 rgba(0,125,72,0.5); }}
  70%  {{ box-shadow:0 0 0 8px rgba(0,125,72,0); }}
  100% {{ box-shadow:0 0 0 0 rgba(0,125,72,0); }}
}}

/* hero editorial */
.hero {{
  padding:80px 32px 48px;
  border-bottom:1px solid var(--hairline-soft);
  background:var(--canvas);
}}
.hero .eyebrow {{
  font-size:12px; font-weight:600; letter-spacing:0.16em; text-transform:uppercase;
  color:var(--mute); margin:0 0 16px;
}}
.hero h1 {{
  font-family:var(--display);
  font-size:clamp(64px,12vw,156px);
  line-height:0.88;
  letter-spacing:-0.01em;
  margin:0;
  text-transform:uppercase;
  color:var(--ink);
}}
.hero h1 em {{ font-style:normal; color:var(--stone); }}
.hero .sub {{
  margin-top:24px; max-width:680px;
  font-size:16px; line-height:1.5; color:var(--charcoal);
}}

/* layout main */
main {{
  display:grid;
  grid-template-columns:minmax(0,1fr) 360px;
  gap:48px;
  padding:48px 32px 64px;
  max-width:1440px; margin:0 auto;
}}
@media (max-width:1023px) {{
  main {{ grid-template-columns:minmax(0,1fr); gap:32px; padding:32px 20px 48px; }}
  .hero {{ padding:48px 20px 32px; }}
  .utility-bar {{ padding:0 20px; font-size:11px; }}
  .primary-nav {{ padding:0 20px; }}
}}

/* card (flat, sin sombras) */
.card {{
  background:var(--canvas);
  border:1px solid var(--hairline-soft);
  padding:32px;
}}
.card h2 {{
  font-family:var(--display); font-size:32px; letter-spacing:0;
  text-transform:uppercase; line-height:1; margin:0 0 24px;
}}
.card h3 {{
  font-size:14px; font-weight:600; letter-spacing:0.08em;
  text-transform:uppercase; color:var(--mute); margin:32px 0 12px;
}}
.card h3:first-child {{ margin-top:0; }}

/* segmented (filter-chip pattern) */
.segmented {{ display:flex; gap:8px; flex-wrap:wrap; }}
.chip {{
  font-family:var(--sans);
  font-size:14px; font-weight:500;
  background:var(--canvas); color:var(--ink);
  border:1px solid var(--hairline);
  border-radius:9999px;
  padding:10px 18px; height:40px;
  cursor:pointer; transition:none;
  line-height:1;
}}
.chip[aria-checked="true"],
.chip.active {{
  background:var(--ink); color:var(--on-primary); border-color:var(--ink);
}}
.chip:focus-visible {{ outline:2px solid var(--ink); outline-offset:2px; }}

/* input pill */
.input-pill {{
  display:flex; align-items:center; gap:12px;
  background:var(--soft-cloud);
  border-radius:24px; padding:8px 16px; height:56px;
  border:1px solid transparent;
}}
.input-pill.focused {{
  background:var(--canvas);
  border-color:var(--ink);
  box-shadow:0 0 0 4px var(--soft-cloud);
}}
.input-pill svg {{ flex-shrink:0; }}
.input-pill input {{
  flex:1; background:transparent; border:none; outline:none;
  font-family:var(--sans); font-size:16px; color:var(--ink);
  min-width:0;
}}
.input-pill input::placeholder {{ color:var(--mute); }}
.input-pill .meta {{ font-size:12px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--mute); }}

.field-row {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
@media (max-width:599px) {{ .field-row {{ grid-template-columns:1fr; }} }}

.lang-pill {{
  background:var(--soft-cloud);
  border-radius:24px; padding:8px 16px; height:56px;
  display:flex; align-items:center;
}}
.lang-pill input {{
  width:100%; background:transparent; border:none; outline:none;
  font-family:var(--sans); font-size:16px;
}}
.field-label {{
  font-size:12px; font-weight:600; letter-spacing:0.08em;
  text-transform:uppercase; color:var(--mute); margin-bottom:8px;
}}

/* buttons */
.btn {{
  display:inline-flex; align-items:center; justify-content:center; gap:8px;
  height:48px; padding:0 32px;
  border-radius:9999px; border:none; cursor:pointer;
  font-family:var(--sans); font-size:16px; font-weight:500;
  line-height:1;
}}
.btn-primary {{ background:var(--ink); color:var(--on-primary); }}
.btn-primary:active {{ transform:scale(0.96); opacity:0.85; }}
.btn-primary:disabled {{ opacity:0.4; cursor:not-allowed; }}
.btn-secondary {{ background:var(--soft-cloud); color:var(--ink); }}
.btn-secondary:active {{ transform:scale(0.96); opacity:0.85; }}
.btn-ghost {{
  background:transparent; color:var(--ink);
  border:1px solid var(--hairline);
}}
.btn-icon {{
  width:40px; height:40px; padding:0;
  background:var(--soft-cloud); color:var(--ink);
  border-radius:9999px; border:none; cursor:pointer;
  display:inline-flex; align-items:center; justify-content:center;
}}
.btn-icon:hover {{ background:var(--hairline-soft); }}

.cta-row {{ display:flex; gap:12px; align-items:center; margin-top:32px; flex-wrap:wrap; }}
.cta-row .spacer {{ flex:1; }}
.kbd {{
  font-family:'SF Mono',Menlo,Consolas,monospace; font-size:11px;
  background:var(--soft-cloud); padding:4px 8px; border-radius:6px;
  color:var(--mute);
}}

/* progress / phases */
.progress-section {{ margin-top:32px; display:none; }}
.progress-section.active {{ display:block; }}

.phases {{
  display:grid; grid-template-columns:repeat(5,1fr); gap:0;
  border-top:1px solid var(--hairline);
  border-bottom:1px solid var(--hairline);
}}
.phase {{
  padding:16px 12px;
  border-left:1px solid var(--hairline);
  font-size:11px; font-weight:600;
  letter-spacing:0.08em; text-transform:uppercase;
  color:var(--mute);
  display:flex; flex-direction:column; gap:4px;
  position:relative;
}}
.phase:first-child {{ border-left:none; }}
.phase .label {{ color:inherit; }}
.phase .pct {{ font-family:var(--display); font-size:24px; color:var(--mute); letter-spacing:0; line-height:1; }}
.phase.active {{ color:var(--ink); background:var(--soft-cloud); }}
.phase.active .pct {{ color:var(--ink); }}
.phase.done {{ color:var(--ink); }}
.phase.done .pct::after {{ content:" ok"; font-size:10px; color:var(--success); letter-spacing:0.08em; }}

.bar {{
  margin-top:16px;
  height:4px; background:var(--soft-cloud); position:relative; overflow:hidden;
}}
.bar > span {{
  display:block; height:100%; background:var(--ink); width:0;
  transition:width 200ms linear;
}}
.bar-meta {{
  display:flex; justify-content:space-between; margin-top:8px;
  font-size:12px; color:var(--mute); font-weight:500;
}}
.bar-meta strong {{ color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums; }}

.error-box {{
  margin-top:24px; padding:16px 20px;
  border:1px solid var(--sale);
  background:var(--canvas);
  color:var(--ink);
  font-size:14px; line-height:1.5;
  display:none;
}}
.error-box.active {{ display:block; }}
.error-box .tag {{
  color:var(--sale); font-weight:600;
  font-size:11px; letter-spacing:0.12em; text-transform:uppercase;
  display:block; margin-bottom:6px;
}}

/* result */
.result {{ margin-top:48px; display:none; }}
.result.active {{ display:block; }}
.result-header {{
  display:flex; align-items:flex-start; justify-content:space-between; gap:24px;
  padding-bottom:24px; border-bottom:1px solid var(--hairline);
  margin-bottom:24px; flex-wrap:wrap;
}}
.result-header .title {{
  font-family:var(--display);
  font-size:clamp(36px,6vw,72px); line-height:0.9;
  text-transform:uppercase; letter-spacing:0;
  margin:0; max-width:760px; word-break:break-word;
}}
.result-meta {{
  display:flex; gap:24px; flex-wrap:wrap;
  margin-top:16px;
  font-size:12px; font-weight:500;
  letter-spacing:0.08em; text-transform:uppercase;
  color:var(--mute);
}}
.result-meta b {{ color:var(--ink); font-weight:600; }}

.toolbar {{
  display:flex; gap:8px; align-items:center; flex-wrap:wrap;
  margin-bottom:16px;
}}
.toolbar .input-pill {{ height:40px; flex:1; min-width:200px; }}
.toolbar .input-pill input {{ font-size:14px; }}

.transcript {{
  background:var(--soft-cloud);
  padding:32px;
  font-size:15px; line-height:1.7;
  max-height:560px; overflow:auto;
  white-space:pre-wrap; word-break:break-word;
  font-family:var(--sans);
  color:var(--ink);
}}
.transcript mark {{
  background:var(--ink); color:var(--on-primary);
  padding:0 2px; border-radius:2px;
}}

/* side panel (history) */
.aside {{
  display:flex; flex-direction:column; gap:24px;
}}
.history h3 {{
  font-family:var(--display); font-size:24px; text-transform:uppercase;
  margin:0 0 16px; letter-spacing:0;
}}
.history-empty {{
  padding:24px 0; color:var(--mute);
  font-size:14px; line-height:1.5;
  border-top:1px solid var(--hairline);
}}
.history-item {{
  border-top:1px solid var(--hairline);
  padding:18px 0;
  display:flex; flex-direction:column; gap:6px;
  cursor:pointer;
}}
.history-item:hover {{ background:var(--soft-cloud); margin:0 -12px; padding:18px 12px; }}
.history-item:last-child {{ border-bottom:1px solid var(--hairline); }}
.history-item .h-title {{
  font-size:14px; font-weight:600; color:var(--ink);
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
  overflow:hidden;
}}
.history-item .h-meta {{
  font-size:11px; font-weight:500; letter-spacing:0.06em;
  text-transform:uppercase; color:var(--mute);
  display:flex; gap:8px; align-items:center;
}}
.h-status {{
  display:inline-block; width:6px; height:6px; border-radius:9999px;
  background:var(--mute);
}}
.h-status.done {{ background:var(--success); }}
.h-status.error {{ background:var(--sale); }}
.h-status.running {{ background:var(--ink); animation:pulse 1.4s infinite; }}

.tip-block {{
  background:var(--ink); color:var(--on-primary);
  padding:32px;
}}
.tip-block h3 {{
  font-family:var(--display); font-size:32px; text-transform:uppercase;
  margin:0 0 12px; line-height:0.95; letter-spacing:0;
}}
.tip-block p {{ margin:0 0 8px; font-size:13px; line-height:1.5; color:var(--stone); }}
.tip-block kbd {{
  font-family:'SF Mono',Menlo,Consolas,monospace; font-size:11px;
  background:#222; padding:2px 6px; border-radius:4px; color:#fff;
}}

/* footer */
footer {{
  border-top:1px solid var(--hairline);
  padding:32px;
  display:flex; justify-content:space-between; align-items:center;
  font-size:12px; color:var(--mute); flex-wrap:wrap; gap:16px;
}}
footer .legal {{ font-size:9px; line-height:1.75; letter-spacing:0.04em; }}
footer a {{ color:var(--mute); text-decoration:none; margin-left:16px; }}
</style>
</head>
<body>

<div class="utility-bar">
  <div class="meta">PUERTO 15000 / WHISPER LOCAL / FFMPEG + YT-DLP</div>
  <div class="group">
    <a href="https://github.com/openai/whisper" target="_blank" rel="noopener">Whisper</a>
    <a href="https://github.com/yt-dlp/yt-dlp" target="_blank" rel="noopener">yt-dlp</a>
    <span class="meta" id="clock"></span>
  </div>
</div>

<nav class="primary-nav">
  <div class="brand">PIÑA<span>/ TRANSCRIBE</span></div>
  <div class="nav-right">
    <span class="status-dot"><span class="pulse"></span> SERVIDOR ACTIVO</span>
  </div>
</nav>

<section class="hero">
  <p class="eyebrow">Transcripcion local · YouTube · Twitch VOD</p>
  <h1>De video<br/>a <em>texto.</em></h1>
  <p class="sub">Descarga el audio con yt-dlp, lo convierte con ffmpeg y lo transcribe en tu maquina con faster-whisper. Sin servicios externos, sin subir nada. Pega una URL y dale a transcribir.</p>
</section>

<main>
  <div>
    <div class="card" id="form-card">
      <form id="f" autocomplete="off">

        <h3>01 / Fuente</h3>
        <div class="segmented" id="platform-group" role="radiogroup" aria-label="Plataforma">
          <button type="button" class="chip active" data-platform="youtube" aria-checked="true">YouTube</button>
          <button type="button" class="chip" data-platform="twitch" aria-checked="false">Twitch VOD</button>
        </div>

        <h3>02 / URL o ID del video</h3>
        <div class="input-pill" id="url-pill">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1 1"/><path d="M14 11a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1-1"/></svg>
          <input type="text" id="video_id" name="video_id"
                 placeholder="https://www.youtube.com/watch?v=... o ID de 11 caracteres" required/>
          <span class="meta" id="url-meta"></span>
        </div>

        <h3>03 / Modelo Whisper</h3>
        <div class="segmented" id="model-group" role="radiogroup" aria-label="Modelo">
          {models_opts}
        </div>

        <h3>04 / Idioma y dispositivo</h3>
        <div class="field-row">
          <div>
            <div class="field-label">Idioma (opcional)</div>
            <div class="lang-pill">
              <input type="text" id="lang" placeholder="auto · es · en · pt · fr..."/>
            </div>
          </div>
          <div>
            <div class="field-label">Dispositivo</div>
            <div class="segmented" id="device-group" role="radiogroup" aria-label="Dispositivo">
              <button type="button" class="chip active" data-device="cpu" aria-checked="true">CPU</button>
              <button type="button" class="chip" data-device="gpu" aria-checked="false">GPU si hay</button>
            </div>
          </div>
        </div>

        <div class="cta-row">
          <button type="submit" class="btn btn-primary" id="btn">Transcribir</button>
          <button type="button" class="btn btn-secondary" id="reset-btn">Limpiar</button>
          <div class="spacer"></div>
          <span class="kbd">CTRL + ENTER</span>
        </div>
      </form>

      <div class="progress-section" id="pw">
        <h3 style="margin-top:32px">Progreso</h3>
        <div class="phases" id="phases">
          <div class="phase" data-phase="init"><span class="label">Init</span><span class="pct">--</span></div>
          <div class="phase" data-phase="download"><span class="label">Descarga</span><span class="pct">--</span></div>
          <div class="phase" data-phase="transcribe"><span class="label">Transcribe</span><span class="pct">--</span></div>
          <div class="phase" data-phase="save"><span class="label">Guarda</span><span class="pct">--</span></div>
          <div class="phase" data-phase="done"><span class="label">Listo</span><span class="pct">--</span></div>
        </div>
        <div class="bar"><span id="bar-fill"></span></div>
        <div class="bar-meta">
          <span id="bar-msg">Esperando...</span>
          <span><strong id="bar-pct">0%</strong> · <span id="bar-elapsed">00:00</span></span>
        </div>
      </div>

      <div class="error-box" id="er">
        <span class="tag">Error</span>
        <div id="er-msg"></div>
      </div>
    </div>

    <section class="result" id="result">
      <div class="result-header">
        <div style="flex:1; min-width:0;">
          <h2 class="title" id="r-title">Transcripcion</h2>
          <div class="result-meta" id="r-meta"></div>
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
          <button class="btn btn-secondary" id="copy-btn">Copiar texto</button>
          <a class="btn btn-primary" id="dl" href="#" download>Descargar .txt</a>
        </div>
      </div>
      <div class="toolbar">
        <div class="input-pill" style="flex:1; min-width:200px;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input type="text" id="search" placeholder="Buscar dentro de la transcripcion..."/>
        </div>
        <button class="btn-icon" id="clear-search" title="Limpiar busqueda">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="transcript" id="r-text"></div>
    </section>
  </div>

  <aside class="aside">
    <div class="tip-block">
      <h3>Atajos.</h3>
      <p><kbd>Ctrl</kbd> + <kbd>Enter</kbd> &nbsp; lanzar transcripcion</p>
      <p><kbd>Esc</kbd> &nbsp; limpiar busqueda en transcripcion</p>
      <p style="margin-top:16px">Pega cualquier URL: la plataforma y el ID se detectan automaticamente.</p>
    </div>

    <div class="history">
      <h3>Recientes.</h3>
      <div id="history-list"></div>
    </div>
  </aside>
</main>

<footer>
  <div>PIÑA-TRANSCRIBE / Pipeline local, sin telemetria</div>
  <div class="legal">Respeta los terminos de YouTube y Twitch y las licencias de los modelos Whisper.</div>
</footer>

<script>
(() => {{
  const $ = (id) => document.getElementById(id);
  const state = {{
    platform: 'youtube',
    model: 'tiny',
    device: 'cpu',
    pollId: null,
    startedAt: 0,
    lastTranscript: '',
    activeJob: null,
  }};

  // ---------- segmented controls ----------
  const setupSegmented = (groupId, key, onChange) => {{
    const root = $(groupId);
    if (!root) return;
    root.querySelectorAll('.chip').forEach(chip => {{
      chip.addEventListener('click', () => {{
        root.querySelectorAll('.chip').forEach(c => {{
          c.classList.remove('active');
          c.setAttribute('aria-checked','false');
        }});
        chip.classList.add('active');
        chip.setAttribute('aria-checked','true');
        const val = chip.dataset[key];
        if (onChange) onChange(val);
      }});
    }});
  }};

  setupSegmented('platform-group','platform', v => {{ state.platform = v; updateUrlMeta(); }});
  setupSegmented('model-group','value', v => {{ state.model = v; }});
  setupSegmented('device-group','device', v => {{ state.device = v; }});

  // mark default model 'tiny' as active
  document.querySelector('#model-group .chip[data-value="tiny"]')?.click();

  // ---------- URL detection ----------
  const YT_URL = /(?:youtube\\.com\\/watch\\?v=|youtu\\.be\\/|youtube\\.com\\/shorts\\/|youtube\\.com\\/live\\/|youtube\\.com\\/embed\\/)([A-Za-z0-9_-]{{11}})/;
  const YT_ID = /^[A-Za-z0-9_-]{{11}}$/;
  const TWITCH_URL = /twitch\\.tv\\/videos\\/(\\d+)/;
  const TWITCH_ID = /^\\d+$/;

  const detect = (raw) => {{
    const v = raw.trim();
    if (!v) return {{platform:null, id:null}};
    let m = v.match(YT_URL); if (m) return {{platform:'youtube', id:m[1]}};
    m = v.match(TWITCH_URL); if (m) return {{platform:'twitch', id:m[1]}};
    if (YT_ID.test(v)) return {{platform:'youtube', id:v}};
    if (TWITCH_ID.test(v)) return {{platform:'twitch', id:v}};
    return {{platform:null, id:null}};
  }};

  const selectPlatform = (p) => {{
    document.querySelectorAll('#platform-group .chip').forEach(c => {{
      const active = c.dataset.platform === p;
      c.classList.toggle('active', active);
      c.setAttribute('aria-checked', active ? 'true' : 'false');
    }});
    state.platform = p;
  }};

  const updateUrlMeta = () => {{
    const raw = $('video_id').value;
    const d = detect(raw);
    const meta = $('url-meta');
    if (d.id) {{
      meta.textContent = d.platform.toUpperCase() + ' / ' + d.id;
      if (d.platform !== state.platform) selectPlatform(d.platform);
    }} else {{
      meta.textContent = '';
    }}
  }};

  $('video_id').addEventListener('input', updateUrlMeta);
  $('video_id').addEventListener('paste', () => setTimeout(updateUrlMeta, 0));

  // ---------- focus styling for pill ----------
  const urlInput = $('video_id');
  const urlPill = $('url-pill');
  urlInput.addEventListener('focus', () => urlPill.classList.add('focused'));
  urlInput.addEventListener('blur', () => urlPill.classList.remove('focused'));

  // ---------- clock ----------
  const tickClock = () => {{
    const d = new Date();
    const hh = String(d.getHours()).padStart(2,'0');
    const mm = String(d.getMinutes()).padStart(2,'0');
    $('clock').textContent = hh + ':' + mm;
  }};
  setInterval(tickClock, 30000); tickClock();

  // ---------- elapsed counter ----------
  let elapsedTimer = null;
  const startElapsed = () => {{
    state.startedAt = Date.now();
    clearInterval(elapsedTimer);
    elapsedTimer = setInterval(() => {{
      const s = Math.floor((Date.now() - state.startedAt) / 1000);
      const mm = String(Math.floor(s/60)).padStart(2,'0');
      const ss = String(s%60).padStart(2,'0');
      $('bar-elapsed').textContent = mm + ':' + ss;
    }}, 500);
  }};
  const stopElapsed = () => {{ clearInterval(elapsedTimer); }};

  // ---------- phases ----------
  const PHASES = ['init','download','transcribe','save','done'];
  const phaseEls = {{}};
  document.querySelectorAll('.phase').forEach(p => {{ phaseEls[p.dataset.phase] = p; }});

  const setPhase = (phase, pct, msg) => {{
    let idx = PHASES.indexOf(phase);
    if (idx < 0) idx = 0;
    PHASES.forEach((name, i) => {{
      const el = phaseEls[name];
      el.classList.remove('active','done');
      if (i < idx) el.classList.add('done');
      if (i === idx) el.classList.add('active');
    }});
    if (phase === 'done') {{
      Object.values(phaseEls).forEach(el => {{ el.classList.remove('active'); el.classList.add('done'); }});
    }}
    PHASES.forEach((name, i) => {{
      const el = phaseEls[name];
      const pctEl = el.querySelector('.pct');
      if (i < idx) pctEl.textContent = '100';
      else if (i === idx) pctEl.textContent = Math.round(pct || 0);
      else pctEl.textContent = '--';
    }});
    $('bar-fill').style.width = (pct || 0) + '%';
    $('bar-pct').textContent = Math.round(pct || 0) + '%';
    $('bar-msg').textContent = msg || phase;
  }};

  const resetPhases = () => {{
    Object.values(phaseEls).forEach(el => {{
      el.classList.remove('active','done');
      el.querySelector('.pct').textContent = '--';
    }});
    $('bar-fill').style.width = '0';
    $('bar-pct').textContent = '0%';
    $('bar-msg').textContent = 'Esperando...';
    $('bar-elapsed').textContent = '00:00';
  }};

  // ---------- form submit ----------
  $('f').addEventListener('submit', async (e) => {{
    e.preventDefault();
    await startJob();
  }});

  $('reset-btn').addEventListener('click', () => {{
    $('video_id').value = '';
    $('lang').value = '';
    updateUrlMeta();
    $('er').classList.remove('active');
    $('result').classList.remove('active');
    $('pw').classList.remove('active');
    resetPhases();
    history.replaceState(null,'',window.location.pathname);
  }});

  const startJob = async () => {{
    const raw = $('video_id').value.trim();
    if (!raw) {{ urlInput.focus(); return; }}
    const detected = detect(raw);
    if (detected.platform) selectPlatform(detected.platform);

    $('er').classList.remove('active');
    $('result').classList.remove('active');
    $('pw').classList.add('active');
    $('btn').disabled = true;
    resetPhases();
    startElapsed();

    const body = {{
      platform: state.platform,
      video_id: raw,
      model: state.model,
      lang: $('lang').value.trim(),
      force_cpu: state.device === 'cpu',
    }};
    let res, data;
    try {{
      res = await fetch('/api/jobs', {{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify(body),
      }});
      data = await res.json();
    }} catch (err) {{
      showError('No se pudo conectar con el servidor: ' + err.message);
      $('btn').disabled = false;
      stopElapsed();
      return;
    }}
    if (!res.ok) {{
      showError(data.detail || JSON.stringify(data));
      $('btn').disabled = false;
      stopElapsed();
      $('pw').classList.remove('active');
      return;
    }}
    state.activeJob = data.job_id;
    history.replaceState(null,'','#' + data.job_id);
    pollJob(data.job_id);
  }};

  const pollJob = (jobId) => {{
    if (state.pollId) clearInterval(state.pollId);
    state.pollId = setInterval(async () => {{
      let j;
      try {{
        const r = await fetch('/api/jobs/' + jobId);
        if (!r.ok) {{
          clearInterval(state.pollId);
          showError('Job no disponible (' + r.status + ')');
          $('btn').disabled = false; stopElapsed();
          return;
        }}
        j = await r.json();
      }} catch (err) {{
        return;
      }}
      setPhase(j.phase || 'init', j.progress || 0, j.message || '');

      if (j.status === 'done') {{
        clearInterval(state.pollId); state.pollId = null;
        stopElapsed();
        $('btn').disabled = false;
        renderResult(jobId, j);
        refreshHistory();
      }} else if (j.status === 'error') {{
        clearInterval(state.pollId); state.pollId = null;
        stopElapsed();
        $('btn').disabled = false;
        showError(j.error || j.message || 'Error desconocido');
        refreshHistory();
      }}
    }}, 400);
  }};

  const showError = (msg) => {{
    $('er-msg').textContent = msg;
    $('er').classList.add('active');
  }};

  // ---------- result ----------
  const renderResult = (jobId, j) => {{
    const r = j.result || {{}};
    $('r-title').textContent = r.title || 'Transcripcion';
    const metaParts = [];
    if (r.platform) metaParts.push('<b>' + r.platform.toUpperCase() + '</b>');
    if (r.language) metaParts.push('Idioma <b>' + r.language + '</b>');
    if (r.model) metaParts.push('Modelo <b>' + r.model + '</b>');
    if (r.url) metaParts.push('<a href="' + r.url + '" target="_blank" rel="noopener" style="color:var(--ink)">Origen</a>');
    $('r-meta').innerHTML = metaParts.join(' · ');
    state.lastTranscript = r.text || '';
    $('r-text').textContent = state.lastTranscript;
    $('dl').href = '/api/jobs/' + jobId + '/download';
    $('result').classList.add('active');
    setPhase('done', 100, 'Completado');
  }};

  $('copy-btn').addEventListener('click', async () => {{
    if (!state.lastTranscript) return;
    try {{
      await navigator.clipboard.writeText(state.lastTranscript);
      const orig = $('copy-btn').textContent;
      $('copy-btn').textContent = 'Copiado!';
      setTimeout(() => {{ $('copy-btn').textContent = orig; }}, 1400);
    }} catch (err) {{
      showError('No se pudo copiar: ' + err.message);
    }}
  }});

  // ---------- search inside transcript ----------
  const escapeHtml = (s) => s.replace(/[&<>]/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[ch]));
  const renderHighlight = (q) => {{
    const text = state.lastTranscript || '';
    if (!q) {{ $('r-text').textContent = text; return; }}
    const escaped = escapeHtml(text);
    const safeQ = q.replace(/[.*+?^${{}}()|[\\]\\\\]/g,'\\\\$&');
    const re = new RegExp(safeQ, 'gi');
    $('r-text').innerHTML = escaped.replace(re, m => '<mark>' + m + '</mark>');
  }};
  $('search').addEventListener('input', e => renderHighlight(e.target.value));
  $('clear-search').addEventListener('click', () => {{ $('search').value=''; renderHighlight(''); }});

  // ---------- history ----------
  const fmtAgo = (ts) => {{
    if (!ts) return '';
    const s = Math.floor(Date.now()/1000 - ts);
    if (s < 60) return 'hace ' + s + 's';
    if (s < 3600) return 'hace ' + Math.floor(s/60) + 'min';
    if (s < 86400) return 'hace ' + Math.floor(s/3600) + 'h';
    return 'hace ' + Math.floor(s/86400) + 'd';
  }};

  const refreshHistory = async () => {{
    try {{
      const r = await fetch('/api/jobs');
      const data = await r.json();
      const list = data.jobs || [];
      const root = $('history-list');
      if (!list.length) {{
        root.innerHTML = '<div class="history-empty">No hay trabajos recientes todavia. Pega una URL arriba para empezar.</div>';
        return;
      }}
      root.innerHTML = list.map(j => {{
        const t = (j.title || j.video_id || 'Sin titulo');
        const cls = j.status === 'done' ? 'done' : j.status === 'error' ? 'error' : 'running';
        const right = j.status === 'done' ? (j.language || 'OK')
                    : j.status === 'error' ? 'ERROR'
                    : Math.round(j.progress || 0) + '%';
        return `<div class="history-item" data-id="${{j.job_id}}">
          <div class="h-title">${{escapeHtml(t)}}</div>
          <div class="h-meta">
            <span class="h-status ${{cls}}"></span>
            <span>${{(j.platform||'').toUpperCase()}}</span>
            <span>·</span>
            <span>${{(j.model||'').toUpperCase()}}</span>
            <span>·</span>
            <span>${{right.toUpperCase()}}</span>
            <span>·</span>
            <span>${{fmtAgo(j.finished_at || j.created_at)}}</span>
          </div>
        </div>`;
      }}).join('');
      root.querySelectorAll('.history-item').forEach(el => {{
        el.addEventListener('click', async () => {{
          const id = el.dataset.id;
          const r2 = await fetch('/api/jobs/' + id);
          if (!r2.ok) return;
          const j2 = await r2.json();
          if (j2.status === 'done') {{
            renderResult(id, j2);
            history.replaceState(null,'','#' + id);
            $('result').scrollIntoView({{behavior:'smooth', block:'start'}});
          }} else if (j2.status === 'running' || j2.status === 'queued') {{
            $('pw').classList.add('active');
            startElapsed();
            pollJob(id);
            history.replaceState(null,'','#' + id);
          }} else if (j2.status === 'error') {{
            showError(j2.error || j2.message || 'Error');
          }}
        }});
      }});
    }} catch (err) {{ /* silent */ }}
  }};

  refreshHistory();
  setInterval(refreshHistory, 5000);

  // ---------- resume on reload via hash ----------
  if (window.location.hash && window.location.hash.length > 1) {{
    const id = window.location.hash.slice(1);
    fetch('/api/jobs/' + id).then(r => r.ok ? r.json() : null).then(j => {{
      if (!j) return;
      if (j.status === 'done') {{
        renderResult(id, j);
      }} else if (j.status === 'running' || j.status === 'queued') {{
        $('pw').classList.add('active');
        $('btn').disabled = true;
        startElapsed();
        pollJob(id);
      }} else if (j.status === 'error') {{
        showError(j.error || j.message || 'Error');
      }}
    }}).catch(() => {{}});
  }}

  // ---------- keyboard shortcuts ----------
  document.addEventListener('keydown', e => {{
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {{
      e.preventDefault();
      if (!$('btn').disabled) $('f').requestSubmit();
    }}
    if (e.key === 'Escape' && document.activeElement === $('search')) {{
      $('search').value=''; renderHighlight('');
    }}
  }});
}})();
</script>
</body>
</html>"""
