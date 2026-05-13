"""
Transcripción local con faster-whisper, detección de CUDA y fallback a CPU.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from faster_whisper import WhisperModel

logger = logging.getLogger("transcribe")

if TYPE_CHECKING:
    from rich.progress import Progress, TaskID

ComputeType = Literal["default", "int8", "int8_float16", "int16", "float16", "float32"]


@dataclass(frozen=True)
class TranscriptionResult:
    """Resultado agregado de la transcripción."""

    text: str
    language: str
    language_probability: float


class TranscriptionError(RuntimeError):
    """Errores durante la carga del modelo o la transcripción."""

    pass


def detect_device_and_compute_type(
    *,
    prefer_gpu: bool = True,
    force_cpu: bool = False,
) -> tuple[str, ComputeType]:
    """
    Elige dispositivo (cuda/cpu) y tipo de cómputo adecuado para poca VRAM.

    Para GPUs con poca memoria se usa int8_float16 en CUDA si está disponible;
    en CPU se usa int8 por rendimiento/memoria.

    Args:
        prefer_gpu: Si False, no intenta CUDA.
        force_cpu: Si True, fuerza CPU sin consultar CUDA.

    Returns:
        Tupla (device, compute_type).
    """
    if force_cpu or not prefer_gpu:
        logger.info("Modo CPU activo (compute_type=int8).")
        return "cpu", "int8"

    try:
        import ctranslate2 as ct2

        n = ct2.get_cuda_device_count()
        if n and n > 0:
            logger.info(
                "CUDA detectada (%s dispositivo(s)); usando GPU con compute_type=int8_float16.",
                n,
            )
            return "cuda", "int8_float16"
    except Exception as e:
        logger.debug("No se pudo consultar CUDA via ctranslate2: %s", e)

    logger.info("CUDA no disponible o no usable; usando CPU (compute_type=int8).")
    return "cpu", "int8"


def transcribe_audio(
    audio_path: str,
    model_size: str,
    language: str | None,
    *,
    beam_size: int = 5,
    vad_filter: bool = True,
    force_cpu: bool = False,
    rich_progress: tuple["Progress", "TaskID"] | None = None,
    fraction_callback: Callable[[float], None] | None = None,
) -> TranscriptionResult:
    """
    Transcribe un archivo de audio con faster-whisper.

    Args:
        audio_path: Ruta al WAV (u otro formato soportado por ffmpeg del modelo).
        model_size: Nombre del modelo (tiny, base, small, …).
        language: Código ISO-639-1 (p. ej. 'es') o None para autodetección.
        beam_size: Tamaño de haz para decodificación.
        vad_filter: Activa filtro VAD para grabaciones largas con silencios.
        force_cpu: Si True, no usa GPU ni reintenta en GPU tras fallos.
        rich_progress: Par opcional (Progress, task_id) para barra Rich.
        fraction_callback: Opcional; llamado con progreso 0.0-1.0 durante la decodificacion.

    Returns:
        TranscriptionResult con texto e idioma.

    Raises:
        TranscriptionError: Si el modelo falla o el texto resultante está vacío.
    """
    device, compute_type = detect_device_and_compute_type(
        prefer_gpu=not force_cpu,
        force_cpu=force_cpu,
    )

    try:
        logger.info(
            "Cargando modelo faster-whisper '%s' en %s (%s)…",
            model_size,
            device,
            compute_type,
        )
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
    except Exception as e:
        if device == "cuda" and not force_cpu:
            logger.warning(
                "Fallo al cargar el modelo en GPU (%s). Reintentando en CPU…",
                e,
            )
            device, compute_type = "cpu", "int8"
            try:
                model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type=compute_type,
                )
            except Exception as e2:
                raise TranscriptionError(
                    f"No se pudo cargar el modelo ni en GPU ni en CPU: {e2}"
                ) from e2
        else:
            raise TranscriptionError(f"No se pudo cargar el modelo: {e}") from e

    try:
        segments_iter, info = model.transcribe(
            audio_path,
            language=language if language else None,
            beam_size=beam_size,
            vad_filter=vad_filter,
            condition_on_previous_text=True,
        )
    except Exception as e:
        raise TranscriptionError(f"Fallo durante transcribe(): {e}") from e

    detected_lang = info.language or (language or "unknown")
    lang_prob = float(info.language_probability or 0.0)

    raw_duration = getattr(info, "duration", None)
    duration_seconds: float | None = (
        float(raw_duration) if raw_duration is not None and raw_duration > 0 else None
    )

    parts: list[str] = []
    last_end = 0.0

    if rich_progress is not None:
        prog, tid = rich_progress
        if duration_seconds is not None:
            prog.update(tid, total=duration_seconds, completed=0)
        else:
            prog.update(tid, total=None)

        for seg in segments_iter:
            parts.append(seg.text.strip())
            if duration_seconds is not None:
                end = seg.end if seg.end is not None else last_end
                prog.advance(tid, max(0.0, end - last_end))
                last_end = end
            else:
                prog.advance(tid, 1.0)

        if duration_seconds is not None:
            prog.update(tid, completed=duration_seconds)
    elif fraction_callback is not None:
        est_segments = 0
        for seg in segments_iter:
            parts.append(seg.text.strip())
            est_segments += 1
            if duration_seconds is not None and duration_seconds > 0:
                end = seg.end if seg.end is not None else last_end
                last_end = max(last_end, end)
                fraction_callback(min(1.0, last_end / duration_seconds))
            else:
                fraction_callback(min(1.0, 1.0 - pow(0.92, est_segments)))
        fraction_callback(1.0)
    else:
        try:
            from tqdm import tqdm
        except ImportError:
            tqdm = None  # type: ignore[assignment,misc]

        if tqdm is not None and duration_seconds is not None:
            pbar = tqdm(
                total=int(duration_seconds),
                unit="s",
                desc="Transcripción",
                ascii=True,
            )
            try:
                for seg in segments_iter:
                    parts.append(seg.text.strip())
                    end = seg.end if seg.end is not None else last_end
                    delta = max(0.0, end - last_end)
                    pbar.update(min(int(delta), max(0, pbar.total - pbar.n)))
                    last_end = end
                if pbar.total is not None and pbar.n < pbar.total:
                    pbar.update(pbar.total - pbar.n)
            finally:
                pbar.close()
        elif tqdm is not None:
            for seg in tqdm(
                segments_iter,
                desc="Segmentos",
                unit="seg",
                ascii=True,
            ):
                parts.append(seg.text.strip())
        else:
            for seg in segments_iter:
                parts.append(seg.text.strip())

    full_text = " ".join(p for p in parts if p).strip()
    if not full_text:
        raise TranscriptionError(
            "La transcripción está vacía (audio sin voz detectable o problema del modelo)."
        )

    return TranscriptionResult(
        text=full_text,
        language=str(detected_lang),
        language_probability=lang_prob,
    )
