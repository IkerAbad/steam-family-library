"""Genera panel.html a partir de library.csv.

Uso: python panel.py <library.csv> <panel.html>

Un solo fichero HTML, sin dependencias ni conexion: los datos van dentro.
"""

import csv
import json
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])

with src.open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

datos = []
for r in rows:
    datos.append({
        "n": r["name"],
        "a": r["appid"],
        "s": r["source"],
        "p": r["playable"] == "True",
        "e": r["exclude_reason"],
        "m": int(r["playtime_minutes"] or 0),
        "u": r["last_played"],
    })

blob = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

html = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Biblioteca familiar de Steam</title>
<style>
:root {
  --fondo: #12151a; --panel: #1a1f26; --borde: #2a313b;
  --texto: #dfe6ee; --suave: #8b98a8; --acento: #66c0f4; --verde: #7bd88f; --ambar: #e0b341;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--fondo); color: var(--texto);
  font-family: "Segoe UI", system-ui, -apple-system, sans-serif; font-size: 14px; }
header { padding: 20px 24px 8px; }
h1 { font-size: 20px; margin: 0 0 4px; font-weight: 600; }
#stats { margin: 0; color: var(--suave); font-size: 13px; }
#stats b { color: var(--texto); font-weight: 600; }
.controles { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 24px 8px; }
input[type=search], select { background: var(--panel); color: var(--texto);
  border: 1px solid var(--borde); border-radius: 6px; padding: 7px 10px; font: inherit; }
input[type=search] { flex: 1 1 260px; min-width: 200px; }
input[type=search]:focus, select:focus { outline: none; border-color: var(--acento); }
#resumen { padding: 0 24px 10px; color: var(--suave); font-size: 13px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
thead th { position: sticky; top: 0; background: var(--panel); text-align: left;
  padding: 9px 12px; font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--suave); border-bottom: 1px solid var(--borde); cursor: pointer; user-select: none; }
thead th:nth-child(2) { width: 110px; }
thead th:nth-child(3) { width: 210px; }
thead th:nth-child(4) { width: 110px; }
thead th:nth-child(5) { width: 140px; }
thead th.der { text-align: right; }
tbody td { padding: 8px 12px; border-bottom: 1px solid #1e242c; vertical-align: middle; }
tbody td:first-child { overflow: hidden; }
tbody tr:hover { background: #171c23; }
td.der { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.nombre { display: flex; align-items: center; gap: 8px; min-width: 0; }
.nombre a { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
a { color: var(--acento); text-decoration: none; }
a:hover { text-decoration: underline; }
.marca { font-size: 11px; padding: 1px 7px; border-radius: 10px; border: 1px solid; white-space: nowrap; }
.prestado { color: var(--verde); border-color: #2f5c3b; background: #16241a; }
.propio { color: var(--suave); border-color: #333b45; background: #1b2027; }
.bloqueado { color: var(--ambar); border-color: #5a4a22; background: #241f11; }
.dim { color: var(--suave); }
#vacio { padding: 30px 24px; color: var(--suave); }
</style>
</head>
<body>
<header>
  <h1>Biblioteca familiar de Steam</h1>
  <p id="stats"></p>
</header>

<div class="controles">
  <input id="q" type="search" placeholder="Buscar por nombre... (sin acentos tambien vale)" autocomplete="off">
  <select id="origen">
    <option value="todo">Todo</option>
    <option value="family">Solo prestados</option>
    <option value="own">Solo mios</option>
  </select>
  <select id="estado">
    <option value="todo">Cualquier estado</option>
    <option value="jugable">Jugables ahora</option>
    <option value="bloqueado">Bloqueados</option>
    <option value="jugados">Ya jugados</option>
    <option value="sinestrenar">Sin estrenar</option>
  </select>
  <select id="orden">
    <option value="nombre">Nombre A-Z</option>
    <option value="horas">Mas horas jugadas</option>
    <option value="reciente">Ultima sesion</option>
  </select>
</div>

<div id="resumen"></div>

<table>
  <thead>
    <tr>
      <th data-campo="n">Juego</th>
      <th>Origen</th>
      <th>Estado</th>
      <th class="der" data-campo="m">Tus horas</th>
      <th class="der" data-campo="u">Ultima sesion</th>
    </tr>
  </thead>
  <tbody id="cuerpo"></tbody>
</table>
<div id="vacio" hidden>Ningun juego cumple esos filtros.</div>

<script>
const DATOS = __DATOS__;

const plano = s => s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
DATOS.forEach(d => d.b = plano(d.n));

const $ = id => document.getElementById(id);
const cuerpo = $("cuerpo");

const totales = {
  juegos: DATOS.length,
  prestados: DATOS.filter(d => d.s === "family").length,
  jugables: DATOS.filter(d => d.s === "family" && d.p).length,
  horas: DATOS.filter(d => d.s === "family").reduce((a, d) => a + d.m, 0),
  jugados: DATOS.filter(d => d.s === "family" && d.m > 0).length
};
$("stats").innerHTML =
  "<b>" + totales.juegos + "</b> juegos en la biblioteca &middot; " +
  "<b>" + totales.prestados + "</b> prestados &middot; " +
  "<b>" + totales.jugables + "</b> jugables ahora &middot; " +
  "<b>" + totales.jugados + "</b> de ellos ya jugados &middot; " +
  "<b>" + (totales.horas / 60).toFixed(1) + "</b> h acumuladas en prestados";

const horas = m => (m / 60).toFixed(1).replace(".", ",");
const fecha = u => u ? u.split("-").reverse().join("/") : "";

function pinta() {
  const q = plano($("q").value.trim());
  const origen = $("origen").value;
  const estado = $("estado").value;
  const orden = $("orden").value;

  let lista = DATOS.filter(d => {
    if (q && !d.b.includes(q)) return false;
    if (origen !== "todo" && d.s !== origen) return false;
    switch (estado) {
      case "jugable": if (!d.p) return false; break;
      case "bloqueado": if (d.p) return false; break;
      case "jugados": if (d.m === 0) return false; break;
      case "sinestrenar": if (d.m > 0) return false; break;
    }
    return true;
  });

  if (orden === "horas") lista.sort((a, b) => b.m - a.m || a.n.localeCompare(b.n, "es"));
  else if (orden === "reciente") lista.sort((a, b) => (b.u || "").localeCompare(a.u || "") || a.n.localeCompare(b.n, "es"));
  else lista.sort((a, b) => a.n.localeCompare(b.n, "es"));

  $("resumen").textContent = lista.length + " de " + DATOS.length + " juegos";
  $("vacio").hidden = lista.length > 0;

  const frag = document.createDocumentFragment();
  for (const d of lista) {
    const tr = document.createElement("tr");

    const td1 = document.createElement("td");
    const cont = document.createElement("div");
    cont.className = "nombre";
    const a = document.createElement("a");
    a.href = "https://store.steampowered.com/app/" + d.a;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = d.n;
    a.title = d.n;
    cont.appendChild(a);
    td1.appendChild(cont);

    const td2 = document.createElement("td");
    const m2 = document.createElement("span");
    m2.className = "marca " + (d.s === "family" ? "prestado" : "propio");
    m2.textContent = d.s === "family" ? "prestado" : "tuyo";
    td2.appendChild(m2);

    const td3 = document.createElement("td");
    if (!d.p) {
      const m3 = document.createElement("span");
      m3.className = "marca bloqueado";
      m3.textContent = d.e || "bloqueado";
      m3.title = d.e;
      td3.appendChild(m3);
    } else {
      const sp = document.createElement("span");
      sp.className = "dim";
      sp.textContent = "jugable";
      td3.appendChild(sp);
    }

    const td4 = document.createElement("td");
    td4.className = "der";
    td4.textContent = d.m > 0 ? horas(d.m) + " h" : "";
    if (d.m === 0) td4.classList.add("dim");

    const td5 = document.createElement("td");
    td5.className = "der dim";
    td5.textContent = fecha(d.u);

    tr.append(td1, td2, td3, td4, td5);
    frag.appendChild(tr);
  }
  cuerpo.replaceChildren(frag);
}

["q", "origen", "estado", "orden"].forEach(id => $(id).addEventListener("input", pinta));
pinta();
</script>
</body>
</html>
"""

html = html.replace("__DATOS__", blob)
out.write_text(html, encoding="utf-8")
print(f"escrito {out} ({out.stat().st_size // 1024} KB, {len(datos)} juegos)")
