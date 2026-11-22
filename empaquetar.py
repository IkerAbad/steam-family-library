#!/usr/bin/env python3
"""Crea un ejecutable de un solo fichero con PyInstaller.

    pip install -r requirements-dev.txt
    python empaquetar.py

En Windows deja dist/steam-families.exe. Hay que ejecutarlo en el sistema
destino: PyInstaller no compila para otra plataforma.
"""

import pathlib
import shutil
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parent


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Falta PyInstaller: pip install -r requirements-dev.txt", file=sys.stderr)
        return 1

    orden = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--noconfirm",
        "--name", "steam-families",
        "--distpath", str(RAIZ / "dist"),
        "--workpath", str(RAIZ / "build"),
        "--specpath", str(RAIZ / "build"),
        str(RAIZ / "steam_families.py"),
    ]
    codigo = subprocess.call(orden)
    if codigo == 0:
        shutil.rmtree(RAIZ / "build", ignore_errors=True)
        nombre = "steam-families.exe" if sys.platform.startswith("win") else "steam-families"
        print(f"hecho: {RAIZ / 'dist' / nombre}")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
