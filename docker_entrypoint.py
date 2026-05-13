#!/usr/bin/env python3
"""
Punto de entrada del contenedor sin script shell (evita CRLF de Windows en .sh).
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    os.chdir("/app")
    exe = sys.executable
    args = sys.argv[1:]

    if len(args) == 0:
        os.execv(
            exe,
            [
                exe,
                "-m",
                "uvicorn",
                "web_server:app",
                "--host",
                "0.0.0.0",
                "--port",
                "15000",
            ],
        )
    if args[0] == "launcher":
        os.execv(exe, [exe, "/app/launcher.py", *args[1:]])
    os.execv(exe, [exe, "/app/transcribe.py", *args])


if __name__ == "__main__":
    main()
