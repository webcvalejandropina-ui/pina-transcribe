#!/usr/bin/env bash
# Arranca Docker en modo interactivo; menus y transcripcion van DENTRO del contenedor.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if command -v python3 >/dev/null 2>&1; then
  exec python3 launch_docker.py "$@"
elif command -v python >/dev/null 2>&1; then
  exec python launch_docker.py "$@"
else
  # Sin Python: invoca docker compose directamente
  exec docker compose run --rm -it transcribe
fi
