#!/usr/bin/env python3
"""Notas de una release: guía de instalación + sección del changelog.

    python notas_release.py 2.1.0

Lo usa el workflow Release para rellenar la release con texto útil.
"""

import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent


def seccion(version):
    """Texto de la sección `## version` del CHANGELOG, sin las siguientes."""
    texto = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    encontrado = re.search(rf"^## {re.escape(version)}(?:\s|$).*$", texto, re.M)
    if not encontrado:
        return ""
    resto = texto[encontrado.end():]
    siguiente = re.search(r"^## ", resto, re.M)
    return resto[:siguiente.start() if siguiente else None].strip()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("uso: notas_release.py X.Y.Z", file=sys.stderr)
        return 2
    guia = (RAIZ / "docs" / "instalacion-release.md").read_text(encoding="utf-8").strip()
    cambios = seccion(argv[0].lstrip("v"))
    print(guia)
    if cambios:
        print()
        print(cambios)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
