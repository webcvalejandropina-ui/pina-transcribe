#!/usr/bin/env python3
"""
Asistente interactivo DENTRO del contenedor (flechas en todas las opciones salvo el ID).
Sin argumentos: docker_entrypoint.py arranca la web; con argumento launcher se ejecuta este script.
"""

from __future__ import annotations

import sys

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

import transcribe as transcribe_mod
from utils.whisper_models import ALLOWED_MODELS

try:
    import questionary
    from questionary import Choice, Separator, Style as QStyle
except ImportError:
    questionary = None  # type: ignore[misc, assignment]
    Choice = None  # type: ignore[misc, assignment]
    Separator = None  # type: ignore[misc, assignment]
    QStyle = None  # type: ignore[misc, assignment]


def _q_style() -> "QStyle":
    return QStyle(
        [
            ("qmark", "fg:#89b4fa bold"),
            ("question", "bold fg:#cdd6f4"),
            ("answer", "fg:#a6e3a1 bold"),
            ("pointer", "fg:#cba6f7 bold"),
            ("highlighted", "fg:#cba6f7 bold"),
            ("selected", "fg:#94e2d5"),
            ("instruction", "fg:#6c7086"),
            ("separator", "fg:#45475a"),
        ]
    )


_MODEL_ORDER = (
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
)


def _lang_choices() -> list:
    lines: tuple[tuple[str, str] | str, ...] = (
        ("Autodetectar (recomendado)", "__auto__"),
        "sep",
        ("Español (es)", "es"),
        ("English (en)", "en"),
        ("Português (pt)", "pt"),
        ("Français (fr)", "fr"),
        ("Deutsch (de)", "de"),
        ("Italiano (it)", "it"),
        ("日本語 (ja)", "ja"),
        ("한국어 (ko)", "ko"),
        ("中文 (zh)", "zh"),
        ("Русский (ru)", "ru"),
    )
    out: list = []
    for item in lines:
        if item == "sep":
            out.append(Separator(" ─────────────── "))
        else:
            title, val = item  # type: ignore[misc]
            out.append(Choice(title, value=val))
    return out


def _fallback_menu(console: Console) -> int:
    console.print("[yellow]questionary no disponible; modo numerico de respaldo.[/]\n")
    print("Dispositivo: 1=Solo CPU  2=CUDA si existe")
    d = input("> ").strip()
    force_cpu = d != "2"
    print("Plataforma: 1=youtube  2=twitch")
    p = input("> ").strip()
    platform = "youtube" if p == "1" else "twitch" if p == "2" else ""
    vid = input("ID video: ").strip()
    models = [m for m in _MODEL_ORDER if m in ALLOWED_MODELS]
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")
    mi = input(f"Modelo 1-{len(models)} [1]: ").strip() or "1"
    try:
        model = models[int(mi) - 1]
    except (ValueError, IndexError):
        model = "tiny"
    print("Idioma: 0=auto  1=es  2=en  3=pt (Enter=0)")
    li = input("> ").strip() or "0"
    lang_map = {"0": "", "1": "es", "2": "en", "3": "pt"}
    lang = lang_map.get(li, "")
    if platform not in ("youtube", "twitch") or not vid:
        return 2
    argv = [platform, vid, "--model", model]
    if lang:
        argv.extend(["--lang", lang])
    if force_cpu:
        argv.append("--cpu")
    return transcribe_mod.main(argv)


def main() -> int:
    console = Console(highlight=False)

    header = Panel.fit(
        Group(
            Align.center(Text("piña-transcribe", style="bold #cba6f7")),
            Align.center(Text("Asistente (dentro del contenedor)", style="bold #cdd6f4")),
            Align.center(
                Text(
                    "↑↓ elige opcion   Enter confirma   Solo el ID se escribe a mano",
                    style="dim italic #89dceb",
                )
            ),
        ),
        border_style="bright_blue",
        box=box.DOUBLE,
        padding=(1, 3),
    )
    console.print()
    console.print(header)
    console.print(Rule(style="#45475a"))

    if questionary is None:
        return _fallback_menu(console)

    if not sys.stdin.isatty():
        console.print(
            "[red]Sin TTY interactivo.[/] Ejemplo:\n"
            "[dim]python transcribe.py youtube ID --model tiny --cpu[/]"
        )
        return 1

    style = _q_style()

    compute = questionary.select(
        "Como transcribir (en este contenedor)?",
        choices=[
            Choice(
                "Solo CPU (forzar --cpu; recomendado si no hay GPU)",
                value="cpu",
            ),
            Choice(
                "GPU/CUDA si existe (sin --cpu; requiere drivers NVIDIA en el host)",
                value="cuda",
            ),
        ],
        style=style,
        qmark=">",
        pointer=">",
        use_indicator=True,
        instruction=" flechas + Enter",
    ).ask()

    if compute is None:
        console.print("[dim]Cancelado.[/]")
        return 0

    platform = questionary.select(
        "Plataforma del video?",
        choices=[
            Choice("YouTube   youtube.com/watch?v=...", "youtube"),
            Choice("Twitch VOD   twitch.tv/videos/...", "twitch"),
        ],
        style=style,
        qmark=">",
        pointer=">",
        use_indicator=True,
        instruction=" flechas + Enter",
    ).ask()

    if platform is None:
        console.print("[dim]Cancelado.[/]")
        return 0

    video_id = questionary.text(
        "ID del video (pegar el ID y Enter)",
        style=style,
        qmark=":",
        validate=lambda t: len((t or "").strip()) > 0 or "El ID no puede estar vacio",
        instruction=" unico campo de texto libre",
    ).ask()

    if video_id is None:
        console.print("[dim]Cancelado.[/]")
        return 0

    video_id = video_id.strip().replace(" ", "")

    model_choices: list = [
        Separator(" --- Modelos Whisper --- "),
        *[
            Choice(m, value=m)
            for m in _MODEL_ORDER
            if m in ALLOWED_MODELS
        ],
    ]

    model = questionary.select(
        "Modelo Whisper",
        choices=model_choices,
        style=style,
        qmark=">",
        pointer=">",
        use_indicator=True,
        instruction=" flechas + Enter",
    ).ask()

    if model is None:
        console.print("[dim]Cancelado.[/]")
        return 0

    lang_sel = questionary.select(
        "Idioma del audio",
        choices=_lang_choices(),
        style=style,
        qmark=">",
        pointer=">",
        use_indicator=True,
        instruction=" flechas + Enter",
    ).ask()

    if lang_sel is None:
        console.print("[dim]Cancelado.[/]")
        return 0

    argv = [platform, video_id, "--model", model]
    if lang_sel and lang_sel != "__auto__":
        argv.extend(["--lang", lang_sel])
    if compute == "cpu":
        argv.append("--cpu")

    tbl = Table(box=box.ROUNDED, title="Resumen", border_style="cyan", expand=True)
    tbl.add_column("Opcion", style="dim")
    tbl.add_column("Valor")
    tbl.add_row("Dispositivo", "CPU forzada" if compute == "cpu" else "CUDA si hay GPU")
    tbl.add_row("Plataforma", platform)
    tbl.add_row("ID", video_id)
    tbl.add_row("Modelo", model)
    tbl.add_row("Idioma", lang_sel if lang_sel and lang_sel != "__auto__" else "(autodetectar)")
    console.print()
    console.print(tbl)
    console.print(Rule("[bold green]Iniciando transcripcion[/]", style="green"))
    console.print()

    try:
        return transcribe_mod.main(argv)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido.[/]")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
