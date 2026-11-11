"""
Transcripción local con faster-whisper.

- Detecta CUDA y cae a CPU si no hay GPU usable.
- Mantiene en memoria el último modelo cargado: el segundo trabajo con el mismo
  modelo arranca al instante en vez de volver a cargar pesos desde disco.
- Ajusta los hilos de CPU a la máquina (o a PINA_CPU_THREADS).
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from faster_whisper import WhisperModel

logger = logging.getLogger("transcribe")

if TYPE_CHECKING:
    from rich.progress import Progress, TaskID

ComputeType = Literal["default", "int8", "int8_float16", "int16", "float16", "float32"]
DeviceChoice = Literal["auto", "cpu", "gpu"]


@dataclass(frozen=True)
class Segment:
    """Fragmento con marcas de tiempo (segundos)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    """Resultado agregado de la transcripción."""

    text: str
    language: str
    language_probability: float
    device: str = "cpu"
    segments: tuple[Segment, ...] = field(default_factory=tuple)


class TranscriptionError(RuntimeError):
    """Errores durante la carga del modelo o la transcripción."""

    def __init__(self, message: str, code: str = "transcribe_failed") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------


def cuda_device_count() -> int:
    """Número de GPUs CUDA visibles para CTranslate2 (0 si no hay)."""
    try:
        import ctranslate2 as ct2

        return int(ct2.get_cuda_device_count() or 0)
    except Exception as e:  # pragma: no cover - depende del hardware
        logger.debug("No se pudo consultar CUDA via ctranslate2: %s", e)
        return 0


def cpu_threads() -> int:
    """Hilos de CPU a usar: PINA_CPU_THREADS o los núcleos disponibles."""
    raw = os.getenv("PINA_CPU_THREADS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    try:
        return max(1, len(os.sched_getaffinity(0)))  # respeta límites de cgroup/cpuset
    except AttributeError:  # macOS / Windows
        return max(1, os.cpu_count() or 1)


def detect_device_and_compute_type(
    *,
    prefer_gpu: bool = True,
    force_cpu: bool = False,
) -> tuple[str, ComputeType]:
    """
    Elige dispositivo (cuda/cpu) y tipo de cómputo.

    En CUDA se usa int8_float16 (poca VRAM); en CPU int8 (rápido y ligero,
    funciona tanto en x86_64 como en ARM64).
    """
    if force_cpu or not prefer_gpu:
        return "cpu", "int8"
    n = cuda_device_count()
    if n > 0:
        logger.info("CUDA detectada (%s GPU); compute_type=int8_float16.", n)
        return "cuda", "int8_float16"
    logger.info("CUDA no disponible; usando CPU (compute_type=int8).")
    return "cpu", "int8"


# ---------------------------------------------------------------------------
# Caché de modelo
# ---------------------------------------------------------------------------

_model_lock = threading.Lock()
_cached_key: tuple[str, str, str] | None = None
_cached_model: WhisperModel | None = None


def _keep_model_loaded() -> bool:
    return os.getenv("PINA_KEEP_MODEL", "1").strip().lower() not in ("0", "false", "no")


def _load_model(model_size: str, device: str, compute_type: str) -> WhisperModel:
    global _cached_key, _cached_model
    key = (model_size, device, compute_type)
    with _model_lock:
        if _cached_model is not None and _cached_key == key:
            logger.info("Reutilizando modelo '%s' ya cargado en %s.", model_size, device)
            return _cached_model
        # Libera el anterior antes de cargar otro: en máquinas pequeñas no caben dos.
        _cached_model = None
        _cached_key = None
        logger.info("Cargando modelo '%s' en %s (%s)…", model_size, device, compute_type)
        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads() if device == "cpu" else 0,
        )
        if _keep_model_loaded():
            _cached_model = model
            _cached_key = key
        return model


def release_model() -> None:
    """Libera el modelo en memoria (útil en tests o para recuperar RAM)."""
    global _cached_key, _cached_model
    with _model_lock:
        _cached_model = None
        _cached_key = None


# ---------------------------------------------------------------------------
# Transcripción
# ---------------------------------------------------------------------------


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
        audio_path: Ruta al audio (WAV mono 16 kHz o cualquier formato que lea PyAV).
        model_size: Nombre del modelo (tiny, base, small, …).
        language: Código ISO-639-1 (p. ej. 'es') o None para autodetección.
        beam_size: Tamaño de haz para decodificación.
        vad_filter: Activa filtro VAD (salta silencios: más rápido en directos largos).
        force_cpu: Si True, no usa GPU.
        rich_progress: Par opcional (Progress, task_id) para barra Rich.
        fraction_callback: Opcional; recibe progreso 0.0-1.0 durante la decodificación.
    """
    device, compute_type = detect_device_and_compute_type(
        prefer_gpu=not force_cpu,
        force_cpu=force_cpu,
    )

    try:
        model = _load_model(model_size, device, compute_type)
    except Exception as e:
        if device != "cuda":
            raise TranscriptionError(f"No se pudo cargar el modelo: {e}", "model_load") from e
        logger.warning("Fallo al cargar el modelo en GPU (%s). Reintentando en CPU…", e)
        device, compute_type = "cpu", "int8"
        try:
            model = _load_model(model_size, device, compute_type)
        except Exception as e2:
            raise TranscriptionError(
                f"No se pudo cargar el modelo ni en GPU ni en CPU: {e2}", "model_load"
            ) from e2

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
    duration: float | None = float(raw_duration) if raw_duration and raw_duration > 0 else None

    segments: list[Segment] = []

    def on_segment(seg) -> None:  # noqa: ANN001 - tipo interno de faster-whisper
        text = (seg.text or "").strip()
        if text:
            segments.append(Segment(float(seg.start or 0.0), float(seg.end or 0.0), text))

    if rich_progress is not None:
        prog, tid = rich_progress
        prog.update(tid, total=duration, completed=0)
        last_end = 0.0
        for seg in segments_iter:
            on_segment(seg)
            if duration is not None:
                end = float(seg.end or last_end)
                prog.advance(tid, max(0.0, end - last_end))
                last_end = end
            else:
                prog.advance(tid, 1.0)
        if duration is not None:
            prog.update(tid, completed=duration)
    else:
        count = 0
        for seg in segments_iter:
            on_segment(seg)
            count += 1
            if fraction_callback is None:
                continue
            if duration:
                fraction_callback(min(1.0, float(seg.end or 0.0) / duration))
            else:
                fraction_callback(min(1.0, 1.0 - pow(0.92, count)))
        if fraction_callback is not None:
            fraction_callback(1.0)

    full_text = " ".join(s.text for s in segments).strip()
    if not full_text:
        raise TranscriptionError(
            "La transcripción está vacía (audio sin voz detectable o problema del modelo).",
            "empty_transcript",
        )

    return TranscriptionResult(
        text=full_text,
        language=str(detected_lang),
        language_probability=lang_prob,
        device=device,
        segments=tuple(segments),
    )
