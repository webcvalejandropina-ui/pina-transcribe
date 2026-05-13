"""
Componentes de interfaz Rich (progreso, tema, hooks de yt-dlp).
"""

from __future__ import annotations

from typing import Any, Callable

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.theme import Theme

CUSTOM_THEME = Theme(
    {
        "info": "cyan",
        "warn": "yellow",
        "err": "bold red",
        "ok": "bold green",
        "accent": "bold magenta",
        "muted": "dim",
    }
)


def create_console(
    *,
    no_color: bool = False,
    force_terminal: bool | None = None,
) -> Console:
    """Consola Rich con tema consistente."""
    kwargs: dict[str, Any] = {"theme": CUSTOM_THEME, "no_color": no_color}
    if force_terminal is not None:
        kwargs["force_terminal"] = force_terminal
    return Console(**kwargs)


def create_progress(console: Console) -> Progress:
    """Barra de progreso estándar (compatible con TTY y redirecciones)."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold accent]{task.description}"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def build_ytdlp_rich_hook(progress: Progress, task_id: TaskID) -> Callable[[dict[str, Any]], None]:
    """
    Hook compatible con yt-dlp que actualiza una tarea Rich.

    Args:
        progress: Instancia Rich Progress (activa; dentro de `with`).
        task_id: ID devuelto por progress.add_task.

    Returns:
        Callable usable en yt-dlp progress_hooks.
    """

    state: dict[str, float | None] = {"total": None}

    def hook(d: dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total and state["total"] != total:
                state["total"] = float(total)
                progress.update(task_id, total=float(total))
            downloaded = float(d.get("downloaded_bytes") or 0)
            if state["total"]:
                progress.update(task_id, completed=min(downloaded, float(state["total"])))
            else:
                progress.update(task_id, completed=downloaded)
        elif status == "finished":
            tot = state["total"]
            if tot:
                progress.update(task_id, completed=tot)

    return hook
