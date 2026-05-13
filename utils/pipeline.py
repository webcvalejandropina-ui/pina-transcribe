"""
Ejecuta descarga + transcripcion con callbacks de progreso (CLI Rich / API web).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from transcribe import write_output_txt

from utils.downloader import download_audio_to_wav
from utils.helpers import check_ffmpeg_installed, cleanup_dir, ensure_project_dirs, make_job_temp_dir
from utils.platform_handler import build_url, normalize_platform
from utils.transcriber import transcribe_audio
from utils.whisper_models import validate_model

logger = logging.getLogger("transcribe")

ProgressCb = Callable[[str, float, str], None]


def _emit(cb: ProgressCb | None, phase: str, pct: float, msg: str) -> None:
    p = max(0.0, min(100.0, pct))
    if cb:
        cb(phase, p, msg)
    logger.info("[%s] %.1f%% %s", phase, p, msg)


def run_transcription_job(
    *,
    platform_raw: str,
    video_id: str,
    model: str,
    lang: str | None,
    force_cpu: bool,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """
    Ejecuta el pipeline completo.

    Returns:
        dict con title, text, language, lang_probability, output_path (str), url, video_id, platform
    """
    if not check_ffmpeg_installed():
        raise RuntimeError("ffmpeg no esta instalado o no esta en PATH")

    _, temp_base, outputs_dir = ensure_project_dirs()

    platform = normalize_platform(platform_raw)
    model_name = validate_model(model)
    vid = video_id.strip().replace(" ", "")
    url = build_url(platform, vid)

    _emit(on_progress, "init", 2, "Parametros validados")

    job_dir: Path | None = None

    try:
        job_dir = make_job_temp_dir(temp_base, vid)

        def dl_hook(d: dict[str, Any]) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                if total:
                    sub = float(got) / float(total)
                    pct = 5.0 + sub * 30.0
                else:
                    pct = 12.0
                _emit(on_progress, "download", pct, "Descargando audio...")
            elif d.get("status") == "finished":
                _emit(on_progress, "download", 36.0, "Extrayendo WAV...")

        wav_path, meta = download_audio_to_wav(
            url,
            vid,
            job_dir,
            quiet_ytdlp=True,
            extra_progress_hooks=[dl_hook],
        )

        title = str(meta.get("title") or "(sin titulo)")
        page_url = str(meta.get("webpage_url") or url)

        _emit(on_progress, "transcribe", 38.0, "Transcribiendo con Whisper...")

        def frac_cb(f: float) -> None:
            pct = 38.0 + max(0.0, min(1.0, f)) * 54.0
            _emit(on_progress, "transcribe", pct, "Decodificando segmentos...")

        result = transcribe_audio(
            str(wav_path),
            model_name,
            lang if lang else None,
            force_cpu=force_cpu,
            fraction_callback=frac_cb,
        )

        _emit(on_progress, "save", 95.0, "Guardando TXT...")
        out_path = outputs_dir / f"{vid}.txt"
        write_output_txt(
            out_path,
            platform=platform,
            title=title,
            url=page_url,
            when=datetime.now().astimezone(),
            model=model_name,
            language=result.language,
            lang_probability=result.language_probability,
            body=result.text,
        )

        _emit(on_progress, "done", 100.0, "Completado")

        return {
            "video_id": vid,
            "platform": platform,
            "title": title,
            "url": page_url,
            "text": result.text,
            "language": result.language,
            "lang_probability": result.language_probability,
            "output_path": str(out_path.resolve()),
            "model": model_name,
        }
    finally:
        if job_dir is not None:
            cleanup_dir(job_dir)
