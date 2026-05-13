"""
Directorios del proyecto, comprobación de ffmpeg y limpieza de temporales.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def project_root() -> Path:
    """Directorio raíz del proyecto (donde está transcribe.py)."""
    return Path(__file__).resolve().parent.parent


def ensure_project_dirs(
    logs_dir: Path | None = None,
    temp_dir: Path | None = None,
    outputs_dir: Path | None = None,
) -> tuple[Path, Path, Path]:
    """
    Crea logs/, temp/, outputs/ si no existen.

    Returns:
        Tupla (logs_dir, temp_dir, outputs_dir).
    """
    root = project_root()
    logs = logs_dir or root / "logs"
    temp_base = temp_dir or root / "temp"
    outputs = outputs_dir or root / "outputs"

    for d in (logs, temp_base, outputs):
        d.mkdir(parents=True, exist_ok=True)

    return logs, temp_base, outputs


def check_ffmpeg_installed() -> bool:
    """True si el binario ffmpeg está en PATH."""
    return shutil.which("ffmpeg") is not None


def make_job_temp_dir(temp_base: Path, video_id: str) -> Path:
    """
    Crea un subdirectorio único bajo temp/ para un trabajo.

    Args:
        temp_base: Carpeta temp del proyecto.
        video_id: ID del video (para nombre legible).

    Returns:
        Path del directorio temporal del trabajo.
    """
    temp_base.mkdir(parents=True, exist_ok=True)
    unique = tempfile.mkdtemp(prefix=f"{video_id}_", dir=temp_base)
    return Path(unique)


def cleanup_dir(path: Path) -> None:
    """
    Elimina recursivamente un directorio si existe.

    Args:
        path: Directorio a borrar.
    """
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
