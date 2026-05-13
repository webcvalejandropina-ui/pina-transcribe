"""Modelos Whisper permitidos (compartido por CLI, launcher y API web)."""

from __future__ import annotations

ALLOWED_MODELS = frozenset(
    {
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "medium",
        "medium.en",
        "large-v1",
        "large-v2",
        "large-v3",
        "large",
    }
)


def validate_model(name: str) -> str:
    m = name.strip().lower()
    if m not in ALLOWED_MODELS:
        allowed = ", ".join(sorted(ALLOWED_MODELS))
        raise ValueError(f"Modelo no permitido: {name!r}. Opciones: {allowed}")
    return m
