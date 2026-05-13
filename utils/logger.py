"""
Configuración básica de logging para archivo y consola.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logger(log_dir: Path, name: str = "transcribe") -> logging.Logger:
    """
    Configura un logger que escribe en logs/<name>.log y en stderr.

    Args:
        log_dir: Carpeta donde guardar el archivo de log.
        name: Nombre base del archivo de log (sin extensión).

    Returns:
        Logger configurado.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{name}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Evitar handlers duplicados si se llama dos veces
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
