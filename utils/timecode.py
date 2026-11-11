"""Conversión entre marcas de tiempo legibles (hh:mm:ss) y segundos."""

from __future__ import annotations


def parse_timecode(value: str | float | int | None) -> float | None:
    """
    Acepta ``90``, ``"90"``, ``"1:30"``, ``"01:01:30"`` o ``"1:30.5"``.

    Devuelve segundos (float) o None si el valor está vacío.
    Lanza ValueError si el formato no es válido o es negativo.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError("El tiempo no puede ser negativo.")
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.replace(",", ".").split(":")
    if len(parts) > 3 or not all(parts):
        raise ValueError(f"Tiempo no válido: {value!r}. Usa segundos, mm:ss o hh:mm:ss.")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(
            f"Tiempo no válido: {value!r}. Usa segundos, mm:ss o hh:mm:ss."
        ) from None
    if any(n < 0 for n in nums):
        raise ValueError("El tiempo no puede ser negativo.")
    if len(nums) > 1 and any(n >= 60 for n in nums[1:]):
        raise ValueError(f"Tiempo no válido: {value!r} (minutos/segundos deben ser < 60).")
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def format_timecode(seconds: float | None) -> str:
    """Formatea segundos como ``h:mm:ss`` o ``m:ss``."""
    if seconds is None:
        return ""
    s = int(round(max(0.0, float(seconds))))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
