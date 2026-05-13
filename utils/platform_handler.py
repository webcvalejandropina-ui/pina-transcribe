"""
Construcción de URLs y validación de plataforma (YouTube / Twitch VOD).
"""

from __future__ import annotations

import re
from typing import Literal

PlatformName = Literal["youtube", "twitch"]

_YOUTUBE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")
# Twitch VOD IDs son numéricos (cadena de dígitos)
_TWITCH_VOD_ID_RE = re.compile(r"^\d+$")


class PlatformError(ValueError):
    """Plataforma no soportada o ID con formato inválido."""

    pass


def normalize_platform(name: str) -> PlatformName:
    """
    Normaliza el nombre de plataforma recibido por CLI.

    Args:
        name: Cadena en minúsculas esperada ('youtube' | 'twitch').

    Raises:
        PlatformError: Si la plataforma no es reconocida.
    """
    lowered = name.strip().lower()
    if lowered not in ("youtube", "twitch"):
        raise PlatformError(
            f"Plataforma inválida: {name!r}. Use 'youtube' o 'twitch'."
        )
    return lowered  # type: ignore[return-value]


def build_url(platform: PlatformName, video_id: str) -> str:
    """
    Construye la URL completa del recurso según la plataforma.

    Args:
        platform: youtube | twitch
        video_id: Identificador del video.

    Raises:
        PlatformError: Si el ID no cumple un formato mínimo esperado.

    Returns:
        URL lista para yt-dlp.
    """
    vid = video_id.strip()
    if not vid:
        raise PlatformError("El ID del video está vacío.")

    if platform == "youtube":
        if not _YOUTUBE_ID_RE.match(vid):
            raise PlatformError(
                "ID de YouTube inválido: debe tener 11 caracteres "
                "(letras, números, guion o guion bajo)."
            )
        return f"https://www.youtube.com/watch?v={vid}"

    # twitch VOD
    if not _TWITCH_VOD_ID_RE.match(vid):
        raise PlatformError(
            "ID de VOD de Twitch inválido: debe ser una cadena numérica."
        )
    return f"https://www.twitch.tv/videos/{vid}"
