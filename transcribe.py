#!/usr/bin/env python3
"""
Punto de entrada: descarga audio de YouTube/Twitch, transcribe con faster-whisper,
genera outputs/<VIDEO_ID>.txt
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from rich.panel import Panel
from rich.table import Table
from rich_argparse import RichHelpFormatter

from utils.downloader import DownloadError, download_audio_to_wav
from utils.helpers import (
    check_ffmpeg_installed,
    cleanup_dir,
    ensure_project_dirs,
    make_job_temp_dir,
)
from utils.logger import setup_logger
from utils.platform_handler import PlatformError, build_url, normalize_platform
from utils.transcriber import TranscriptionError, transcribe_audio
from utils.ui import build_ytdlp_rich_hook, create_console, create_progress
from utils.whisper_models import ALLOWED_MODELS, validate_model


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transcriptor local: YouTube / Twitch VOD -> WAV -> faster-whisper -> "
            "archivo TXT en outputs/"
        ),
        formatter_class=RichHelpFormatter,
        epilog=(
            "Ejemplos:\n  %(prog)s youtube dQw4w9WgXcQ\n"
            "  %(prog)s twitch 1234567890 --model base --lang es\n"
            "  %(prog)s youtube dQw4w9WgXcQ --cpu\n"
            "  docker compose up -d transcribe\n"
            "  Abrir http://127.0.0.1:15000\n"
            "  docker compose run --rm transcribe youtube dQw4w9WgXcQ --cpu"
        ),
    )
    parser.add_argument(
        "platform",
        choices=["youtube", "twitch"],
        help="Origen del vídeo: youtube o twitch",
    )
    parser.add_argument(
        "video_id",
        help="ID del vídeo (YouTube ~11 caracteres; Twitch VOD numérico)",
    )
    parser.add_argument(
        "--model",
        default="tiny",
        metavar="NAME",
        help="Modelo faster-whisper (por defecto: tiny). VRAM baja: tiny/base.",
    )
    parser.add_argument(
        "--lang",
        default=None,
        metavar="LANG",
        help="Idioma fijo (p. ej. es). Si se omite: autodetección.",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Forzar solo CPU (no usar CUDA aunque exista GPU).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Salida sin colores ANSI (útil en logs en crudo).",
    )
    return parser.parse_args(argv)


def write_output_txt(
    path: Path,
    *,
    platform: str,
    title: str,
    url: str,
    when: datetime,
    model: str,
    language: str,
    lang_probability: float,
    body: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"Plataforma: {platform}\n"
        f"Título: {title}\n"
        f"URL: {url}\n"
        f"Fecha y hora: {when.isoformat(timespec='seconds')}\n"
        f"Modelo usado: {model}\n"
        f"Idioma detectado: {language} (probabilidad estimada: {lang_probability:.4f})\n"
        f"---\n"
        f"Transcripción:\n\n"
        f"{body}\n"
    )
    path.write_text(header, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logs_dir, temp_base, outputs_dir = ensure_project_dirs()
    logger = setup_logger(logs_dir, name="transcribe")

    console = create_console(no_color=args.no_color)

    console.print(
        Panel.fit(
            "[bold accent]piña-transcribe[/] - YouTube / Twitch -> texto (faster-whisper)",
            border_style="cyan",
        )
    )

    if not check_ffmpeg_installed():
        console.print(
            "[err]ffmpeg no está instalado o no está en PATH.[/]\n"
            "[muted]Ubuntu:[/] sudo apt update && sudo apt install -y ffmpeg\n"
            "[muted]Docker:[/] usa la imagen incluida (ya trae ffmpeg)."
        )
        logger.error("ffmpeg no encontrado en PATH")
        return 2

    job_dir: Path | None = None

    try:
        try:
            platform = normalize_platform(args.platform)
            model_name = validate_model(args.model)
        except (PlatformError, ValueError) as e:
            console.print(f"[err]{e}[/]")
            logger.error("%s", e)
            return 2

        video_id = args.video_id.strip()
        try:
            url = build_url(platform, video_id)
        except PlatformError as e:
            console.print(f"[err]{e}[/]")
            logger.error("%s", e)
            return 2

        mode_lbl = "[warn]CPU forzada (--cpu)[/]" if args.cpu else "[info]GPU si disponible[/]"
        summary = Table(title="Parámetros del trabajo", show_header=False, border_style="dim")
        summary.add_column("Campo", style="muted")
        summary.add_column("Valor")
        summary.add_row("Plataforma", platform)
        summary.add_row("ID", video_id)
        summary.add_row("URL", url)
        summary.add_row("Modelo", model_name)
        summary.add_row("Idioma", args.lang or "(autodetectar)")
        summary.add_row("Dispositivo", mode_lbl)
        console.print(summary)
        console.print()

        logger.info(
            "Inicio | platform=%s id=%s url=%s model=%s cpu=%s",
            platform,
            video_id,
            url,
            model_name,
            args.cpu,
        )

        job_dir = make_job_temp_dir(temp_base, video_id)

        wav_path: Path
        meta: dict

        with create_progress(console) as progress:
            dl_task = progress.add_task("Descargando y extrayendo audio...", total=None)
            rich_hook = build_ytdlp_rich_hook(progress, dl_task)
            try:
                wav_path, meta = download_audio_to_wav(
                    url,
                    video_id,
                    job_dir,
                    quiet_ytdlp=True,
                    extra_progress_hooks=[rich_hook],
                )
            except DownloadError as e:
                console.print(f"[err]Descarga fallida:[/] {e}")
                logger.error("Descarga fallida: %s", e)
                return 3
            progress.update(dl_task, description="[ok]Audio listo (WAV)[/]")

            tr_task = progress.add_task("Transcribiendo...", total=None)
            title = str(meta.get("title") or "(sin título)")
            page_url = str(meta.get("webpage_url") or url)

            try:
                result = transcribe_audio(
                    str(wav_path),
                    model_name,
                    args.lang,
                    force_cpu=args.cpu,
                    rich_progress=(progress, tr_task),
                )
            except TranscriptionError as e:
                console.print(f"[err]Transcripción fallida:[/] {e}")
                logger.error("Transcripción fallida: %s", e)
                return 4
            progress.update(tr_task, description="[ok]Transcripción terminada[/]")

        out_path = outputs_dir / f"{video_id}.txt"
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

        logger.info("Guardado en %s", out_path.resolve())

        done = Table(show_header=False, border_style="green")
        done.add_column("clave", style="muted")
        done.add_column("valor")
        done.add_row("Salida", str(out_path.resolve()))
        done.add_row("Título", title[:120] + ("..." if len(title) > 120 else ""))
        done.add_row("Idioma", f"{result.language} (p≈{result.language_probability:.2f})")

        console.print()
        console.print(Panel(done, title="[ok]Listo[/]", border_style="green"))
        return 0

    except KeyboardInterrupt:
        logging.getLogger("transcribe").warning("Interrumpido por el usuario.")
        console.print("\n[warn]Interrumpido por el usuario.[/]")
        return 130
    except Exception as e:
        logging.getLogger("transcribe").exception("Error no controlado: %s", e)
        console.print(f"[err]Error no controlado:[/] {e}")
        return 1
    finally:
        if job_dir is not None:
            cleanup_dir(job_dir)
            logging.getLogger("transcribe").debug("Temporal eliminado: %s", job_dir)


if __name__ == "__main__":
    raise SystemExit(main())
