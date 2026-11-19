#!/usr/bin/env sh
# Lanzador para Linux y macOS.
set -eu

AQUI=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PY=python3
if ! command -v python3 >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        PY=python
    else
        echo "No encuentro python3. Instalalo con el gestor de paquetes de tu distribucion." >&2
        exit 1
    fi
fi

exec "$PY" "$AQUI/steam_families.py" --datos "${1:-$AQUI}"
