"""
Descarga de audio con yt-dlp y extracción a WAV mediante FFmpeg.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

import yt_dlp
from yt_dlp.utils import download_range_func

logger = logging.getLogger("transcribe")

YtdlpProgressCallback = Callable[[dict[str, Any]], None]


def _ensure_ca_bundle() -> None:
    """
    ffmpeg descarga los tramos HLS por su cuenta. Algunas compilaciones (p. ej.
    Homebrew en macOS) no encuentran los certificados raíz del sistema; si nadie
    ha configurado SSL_CERT_FILE, usamos el bundle de certifi que trae yt-dlp.
    """
    if os.getenv("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except ImportError:  # pragma: no cover
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


class DownloadError(RuntimeError):
    """Fallo de descarga o extracción de audio."""

    def __init__(self, message: str, code: str = "download_failed") -> None:
        super().__init__(message)
        self.code = code


def _build_ydl_opts(
    out_template: str,
    hooks: list[YtdlpProgressCallback],
    quiet_ytdlp: bool,
    *,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> dict[str, Any]:
    """Construye opciones reproducibles y compatibles con YouTube moderno."""
    opts: dict[str, Any] = {
        # HLS evita algunos 403 de URLs directas; mantenemos fallback de audio.
        "format": "bestaudio[protocol*=m3u8]/bestaudio/best",
        "outtmpl": out_template,
        "quiet": quiet_ytdlp,
        "no_warnings": quiet_ytdlp,
        "noplaylist": True,
        "progress_hooks": hooks,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }
        ],
        # Whisper trabaja a 16 kHz mono: convertir aquí reduce el WAV ~6x
        # (menos disco, menos RAM y decodificación más rápida).
        "postprocessor_args": {"extractaudio": ["-ar", "16000", "-ac", "1"]},
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": 1,
    }

    if start_seconds is not None or end_seconds is not None:
        # Descarga solo el tramo pedido (no el VOD entero de varias horas).
        start = float(start_seconds or 0.0)
        end = float(end_seconds) if end_seconds is not None else float("inf")
        opts["download_ranges"] = download_range_func(None, [(start, end)])
        opts["force_keyframes_at_cuts"] = True

    proxy = os.getenv("YTDLP_PROXY", "").strip()
    if proxy:
        opts["proxy"] = proxy

    cookies_file = os.getenv("YTDLP_COOKIES_FILE", "").strip()
    if cookies_file:
        cookie_path = Path(cookies_file)
        if not cookie_path.is_file():
            raise DownloadError(
                "YTDLP_COOKIES_FILE está configurado, pero el archivo no existe.",
                "cookies_missing",
            )
        opts["cookiefile"] = str(cookie_path)

    return opts


def _default_logger_hook(d: dict[str, Any]) -> None:
    """Hook de progreso para yt-dlp vía logging (archivo / stderr)."""
    status = d.get("status")
    if status == "downloading":
        pct = d.get("_percent_str", "").strip()
        spd = d.get("_speed_str", "").strip()
        eta = d.get("_eta_str", "").strip()
        msg = f"Descarga: {pct}"
        if spd:
            msg += f" | Velocidad: {spd}"
        if eta:
            msg += f" | ETA: {eta}"
        logger.info(msg)
    elif status == "finished":
        logger.info("Descarga finalizada; procesando audio con FFmpeg…")


def download_audio_to_wav(
    url: str,
    video_id: str,
    job_dir: Path,
    *,
    quiet_ytdlp: bool = False,
    extra_progress_hooks: list[YtdlpProgressCallback] | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> tuple[Path, dict[str, Any]]:
    """
    Descarga el mejor audio disponible y lo convierte a WAV.

    Args:
        url: URL completa del video (YouTube o Twitch VOD).
        video_id: ID corto usado en nombres de salida.
        job_dir: Directorio temporal exclusivo de este trabajo.
        quiet_ytdlp: Si True, silencia la salida estándar de yt-dlp (útil con UI Rich).
        extra_progress_hooks: Hooks adicionales (p. ej. Rich Progress).
        start_seconds / end_seconds: Tramo opcional a descargar (segundos).

    Returns:
        Tupla (ruta_archivo_wav, metadatos_info).

    Raises:
        DownloadError: Si yt-dlp/ffmpeg fallan o no hay archivo de salida.
    """
    _ensure_ca_bundle()
    job_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(job_dir / f"{video_id}.%(ext)s")

    hooks: list[YtdlpProgressCallback] = [_default_logger_hook]
    if extra_progress_hooks:
        hooks.extend(extra_progress_hooks)

    ydl_opts = _build_ydl_opts(
        out_template,
        hooks,
        quiet_ytdlp,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
    )

    info: dict[str, Any] = {}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e).lower()
        if "private" in err_msg:
            raise DownloadError(
                "El video parece ser privado o no tienes permiso para verlo.", "private"
            ) from e
        if "unavailable" in err_msg or "deleted" in err_msg:
            raise DownloadError(
                "El video no está disponible (eliminado o restricción).", "unavailable"
            ) from e
        if "403" in err_msg or "forbidden" in err_msg or "sign in" in err_msg:
            raise DownloadError(
                "YouTube rechazó la descarga (HTTP 403). La imagen incluye Deno/EJS; "
                "si persiste, configura YTDLP_COOKIES_FILE o YTDLP_PROXY.",
                "forbidden",
            ) from e
        raise DownloadError(f"Error de red o descarga con yt-dlp: {e}") from e
    except Exception as e:
        raise DownloadError(f"Fallo inesperado durante la descarga: {e}") from e

    if not isinstance(info, dict):
        raise DownloadError("No se pudieron obtener metadatos del video.", "no_metadata")

    title = info.get("title") or "(sin título)"
    ext = info.get("ext")
    wav_path = job_dir / f"{video_id}.wav"

    if not wav_path.is_file():
        wav_files = sorted(job_dir.glob("*.wav"))
        if len(wav_files) == 1:
            wav_path = wav_files[0]
        else:
            raise DownloadError(
                "No se encontró el archivo WAV esperado tras la conversión con FFmpeg.",
                "no_audio",
            )

    if wav_path.stat().st_size < 1024:
        raise DownloadError(
            "El archivo de audio es demasiado pequeño o está vacío tras la descarga.",
            "no_audio",
        )

    logger.debug("Audio WAV listo: %s (ext original hint=%s)", wav_path, ext)
    meta = {
        "title": title,
        "id": info.get("id", video_id),
        "webpage_url": info.get("webpage_url") or url,
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
    }
    return wav_path, meta
