"""
Información del equipo que ejecuta la app y modelo Whisper recomendado.

Funciona en Linux (incluido Docker, respetando los límites de cgroup), macOS y
Windows sin dependencias extra.
"""

from __future__ import annotations

import os
import platform
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.transcriber import cpu_threads, cuda_device_count


def _cgroup_limit_bytes() -> int | None:
    """Límite de memoria del contenedor (cgroup v2 o v1), si existe."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(path).read_text().strip()
        except OSError:
            continue
        if raw.isdigit():
            value = int(raw)
            if 0 < value < (1 << 60):  # valores enormes = "sin límite"
                return value
    return None


def _physical_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        pass
    if platform.system() == "Windows":  # pragma: no cover
        try:
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemStatus()
            stat.dwLength = ctypes.sizeof(_MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return int(stat.ullTotalPhys)
        except Exception:
            return None
    return None


def memory_gb() -> float | None:
    """Memoria utilizable en GiB (el menor entre la física y el límite del contenedor)."""
    candidates = [v for v in (_physical_memory_bytes(), _cgroup_limit_bytes()) if v]
    if not candidates:
        return None
    return round(min(candidates) / (1024**3), 1)


def recommend_model(cores: int, mem_gb: float | None, gpus: int) -> str:
    """Modelo con el mejor equilibrio calidad/velocidad para este equipo."""
    mem = mem_gb if mem_gb is not None else 4.0
    if gpus > 0:
        return "large-v3" if mem >= 8 else "small"
    if mem < 2.5 or cores <= 2:
        return "tiny"
    if mem < 5 or cores < 6:
        return "base"
    return "small"


@lru_cache(maxsize=1)
def system_summary() -> dict[str, Any]:
    cores = cpu_threads()
    mem = memory_gb()
    gpus = cuda_device_count()
    return {
        "os": platform.system(),
        "arch": platform.machine(),
        "cpu_threads": cores,
        "memory_gb": mem,
        "gpu_count": gpus,
        "recommended_model": recommend_model(cores, mem, gpus),
    }
