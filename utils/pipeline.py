"""
Ejecuta descarga + transcripción con callbacks de progreso (CLI Rich / API web).

Los mensajes de progreso son claves estables (p. ej. ``download.audio``) para que
la interfaz los muestre en el idioma del usuario.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from transcribe import write_output_srt, write_output_txt

from utils.downloader import download_audio_to_wav
from utils.helpers import check_ffmpeg_installed, cleanup_dir, ensure_project_dirs, make_job_temp_dir
from utils.platform_handler import build_url, normalize_platform
from utils.transcriber import TranscriptionError, transcribe_audio
from utils.whisper_models import validate_model

logger = logging.getLogger("transcribe")

ProgressCb = Callable[[str, float, str], None]


def _emit(cb: ProgressCb | None, phase: str, pct: float, msg_key: str) -> None:
    p = max(0.0, min(100.0, pct))
    if cb:
        cb(phase, p, msg_key)
    logger.info("[%s] %.1f%% %s", phase, p, msg_key)


def _range_suffix(start: float | None, end: float | None) -> str:
    if start is None and end is None:
        return ""
    a = int(start or 0)
    b = "end" if end is None else str(int(end))
    return f"_{a}-{b}"


def run_transcription_job(
    *,
    platform_raw: str,
    video_id: str,
    model: str,
    lang: str | None,
    force_cpu: bool,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """
    Ejecuta el pipeline completo.

    Returns:
        dict con title, text, language, lang_probability, output_path, srt_path,
        url, video_id, platform, model, device, start_seconds, end_seconds.
    """
    if not check_ffmpeg_installed():
        raise TranscriptionError("ffmpeg no esta instalado o no esta en PATH", "ffmpeg_missing")

    _, temp_base, outputs_dir = ensure_project_dirs()

    platform = normalize_platform(platform_raw)
    model_name = validate_model(model)
    vid = video_id.strip().replace(" ", "")
    url = build_url(platform, vid)

    _emit(on_progress, "init", 2, "init.validated")

    job_dir: Path | None = None
    try:
        job_dir = make_job_temp_dir(temp_base, vid)

        def dl_hook(d: dict[str, Any]) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                pct = 5.0 + (float(got) / float(total)) * 30.0 if total else 12.0
                _emit(on_progress, "download", pct, "download.audio")
            elif d.get("status") == "finished":
                _emit(on_progress, "download", 36.0, "download.convert")

        _emit(on_progress, "download", 4, "download.start")
        wav_path, meta = download_audio_to_wav(
            url,
            vid,
            job_dir,
            quiet_ytdlp=True,
            extra_progress_hooks=[dl_hook],
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )

        title = str(meta.get("title") or "(sin titulo)")
        page_url = str(meta.get("webpage_url") or url)

        _emit(on_progress, "transcribe", 38.0, "transcribe.load")

        def frac_cb(f: float) -> None:
            pct = 40.0 + max(0.0, min(1.0, f)) * 52.0
            _emit(on_progress, "transcribe", pct, "transcribe.decode")

        result = transcribe_audio(
            str(wav_path),
            model_name,
            lang if lang else None,
            force_cpu=force_cpu,
            fraction_callback=frac_cb,
        )

        _emit(on_progress, "save", 95.0, "save.files")
        stem = f"{vid}{_range_suffix(start_seconds, end_seconds)}"
        out_path = outputs_dir / f"{stem}.txt"
        srt_path = outputs_dir / f"{stem}.srt"
        offset = float(start_seconds or 0.0)
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
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
        write_output_srt(srt_path, result.segments, offset=offset)

        _emit(on_progress, "done", 100.0, "done")

        return {
            "video_id": vid,
            "platform": platform,
            "title": title,
            "url": page_url,
            "text": result.text,
            "language": result.language,
            "lang_probability": result.language_probability,
            "output_path": str(out_path.resolve()),
            "srt_path": str(srt_path.resolve()),
            "model": model_name,
            "device": result.device,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "segments": len(result.segments),
        }
    finally:
        if job_dir is not None:
            cleanup_dir(job_dir)
