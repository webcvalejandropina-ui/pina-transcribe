#!/usr/bin/env python3
"""Arranca el stack Docker en segundo plano (servidor web en puerto 15000)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    use_gpu = "--gpu" in sys.argv

    if not shutil.which("docker"):
        print("docker no esta en PATH.", file=sys.stderr)
        return 1

    compose = ["docker", "compose"]
    env_file = root / "pina.env"
    if env_file.is_file():
        compose.extend(["--env-file", str(env_file)])
        print("Usando configuración de", env_file.name)
    service = "transcribe-gpu" if use_gpu else "transcribe"
    if use_gpu:
        compose.extend(["--profile", "gpu"])

    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")

    print("Levantando servicio:", service, "(detached)...")
    up = subprocess.run(
        compose + ["up", "-d", "--build", service],
        cwd=root,
        env=env,
    )
    if up.returncode != 0:
        return up.returncode

    print()
    port = os.environ.get("PINA_PORT", "15000")
    print(f"Interfaz web / Web UI: http://127.0.0.1:{port}")
    print("Logs: docker compose logs -f", service)
    print("Parar: docker compose stop", service)
    print()
    print("Launcher consola (TTY): docker compose run --rm -it", service, "launcher")
    print("CLI: docker compose run --rm", service, "youtube VIDEO_ID --start 0:30 --end 2:00")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
