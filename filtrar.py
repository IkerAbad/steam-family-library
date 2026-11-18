"""Saca de library.csv solo los juegos que te presta la familia.

Uso: python filtrar.py <library.csv> <carpeta_de_salida>

Escribe prestados.csv (con todas las columnas) y prestados.txt (solo nombres
de los jugables, uno por linea).
"""

import csv
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

with src.open(encoding="utf-8-sig", newline="") as f:
    rows = [r for r in csv.DictReader(f) if r["source"] == "family"]

if not rows:
    print("No hay filas con source=family en", src)
    sys.exit(1)

rows.sort(key=lambda r: r["name"].lower())

with (out / "prestados.csv").open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

jugables = sorted((r["name"] for r in rows if r["playable"] == "True"), key=str.lower)
(out / "prestados.txt").write_text("\n".join(jugables) + "\n", encoding="utf-8")

print(f"{len(rows)} prestados, {len(jugables)} jugables")
print("escritos prestados.csv y prestados.txt en", out)
