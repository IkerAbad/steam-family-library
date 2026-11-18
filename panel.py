"""Construye panel.html, prestados.csv y prestados.txt a partir de los datos.

Uso:
    python panel.py --datos <carpeta>

Lee library.csv, snapshot.json (para los nombres de los duenos) y
novedades.json (para marcar lo que ha entrado o salido). Escribe panel.html en
la misma carpeta: un fichero unico, sin dependencias ni conexion.
"""

import argparse
import csv
import json
from pathlib import Path


def leer_json(ruta, defecto):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return defecto


def main():
    p = argparse.ArgumentParser(description="Genera el panel HTML.")
    p.add_argument("--datos", default=".", help="carpeta con library.csv y snapshot.json")
    args = p.parse_args()

    datos = Path(args.datos).resolve()
    csv_path = datos / "library.csv"
    if not csv_path.exists():
        raise SystemExit(f"no encuentro {csv_path}. Ejecuta antes steam_family_library.py")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))

    snap = leer_json(datos / "snapshot.json", {})
    alias = snap.get("nombres") or {}
    yo = snap.get("yo", "")
    por_appid = {str(k): v for k, v in (snap.get("juegos") or {}).items()}

    nov = leer_json(datos / "novedades.json", {})
    marca = {str(e["appid"]): e for e in nov.get("eventos", [])}

    def dueno(fila):
        j = por_appid.get(str(fila["appid"]))
        if not j:
            return ""
        otros = [alias.get(o, "") for o in j.get("o", []) if o != yo]
        otros = [o for o in otros if o]
        if not otros:
            return "tú" if yo in j.get("o", []) else ""
        return ", ".join(sorted(otros))

    juegos = []
    for r in filas:
        appid = str(r["appid"])
        e = marca.get(appid)
        juegos.append({
            "n": r["name"],
            "a": appid,
            "s": r["source"],
            "p": r["playable"] == "True",
            "e": r["exclude_reason"],
            "m": int(r["playtime_minutes"] or 0),
            "u": r["last_played"],
            "d": dueno(r),
            "w": e["evento"] if e else "",
            "wf": nov.get("fecha", ""),
        })

    prestados = [j for j in juegos if j["s"] == "family"]
    prestados.sort(key=lambda j: j["n"].lower())
    if prestados:
        with (datos / "prestados.csv").open("w", encoding="utf-8-sig", newline="") as f:
            campos = [k for k in filas[0].keys()]
            w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            w.writeheader()
            por_id = {str(r["appid"]): r for r in filas}
            w.writerows(por_id[j["a"]] for j in prestados)

    jugables = sorted((j["n"] for j in prestados if j["p"]), key=str.lower)
    (datos / "prestados.txt").write_text("\n".join(jugables) + "\n", encoding="utf-8")

    blob = json.dumps(juegos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    fecha_nov = nov.get("fecha", "")
    hay_nov = bool(marca)

    html = PLANTILLA
    html = html.replace("__DATOS__", blob)
    html = html.replace("__FECHA_NOV__", json.dumps(fecha_nov, ensure_ascii=False))
    html = html.replace("__HAY_NOV__", "true" if hay_nov else "false")

    salida = datos / "panel.html"
    salida.write_text(html, encoding="utf-8")
    print(f"escrito {salida} ({salida.stat().st_size // 1024} KB, {len(juegos)} juegos, {len(prestados)} prestados)")
    return 0


PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Biblioteca familiar de Steam</title>
<style>
:root { --fondo:#12151a; --panel:#1a1f26; --borde:#2a313b; --texto:#dfe6ee; --suave:#8b98a8; --acento:#66c0f4; --verde:#7bd88f; --ambar:#e0b341; --rojo:#e06c6c; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fondo); color:var(--texto); font-family:"Segoe UI",system-ui,-apple-system,sans-serif; font-size:14px; }
header { padding:22px 24px 6px; }
h1 { font-size:20px; margin:0 0 6px; font-weight:600; }
#stats { margin:0; color:var(--suave); font-size:13px; }
#stats b { color:var(--texto); font-weight:600; }
.aviso { margin:10px 24px 0; padding:9px 12px; border-radius:8px; background:#16241a; border:1px solid #2f5c3b; color:var(--verde); font-size:13px; }
.aviso button { float:right; background:none; border:none; color:var(--verde); cursor:pointer; font:inherit; text-decoration:underline; }
.controles { display:flex; flex-wrap:wrap; gap:8px; padding:14px 24px 8px; align-items:center; }
input[type=search], select { background:var(--panel); color:var(--texto); border:1px solid var(--borde); border-radius:6px; padding:7px 10px; font:inherit; }
input[type=search] { flex:1 1 280px; min-width:220px; }
input[type=search]:focus, select:focus { outline:none; border-color:var(--acento); }
label.check { display:flex; align-items:center; gap:6px; color:var(--suave); font-size:13px; padding:0 4px; cursor:pointer; }
label.check input { accent-color:var(--acento); }
#resumen { padding:2px 24px 10px; color:var(--suave); font-size:13px; }
table { width:100%; border-collapse:collapse; table-layout:fixed; }
thead th { position:sticky; top:0; background:var(--panel); text-align:left; padding:9px 12px; font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--suave); border-bottom:1px solid var(--borde); user-select:none; }
thead th:nth-child(2) { width:170px; }
thead th:nth-child(3) { width:110px; }
thead th:nth-child(4) { width:180px; }
thead th:nth-child(5) { width:100px; }
thead th:nth-child(6) { width:120px; }
thead th.der { text-align:right; }
tbody td { padding:8px 12px; border-bottom:1px solid #1e242c; vertical-align:middle; }
tbody td:first-child { overflow:hidden; }
tbody tr:hover { background:#171c23; }
td.der { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.nombre { display:flex; align-items:center; gap:8px; min-width:0; }
.nombre a { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--acento); text-decoration:none; }
.nombre a:hover { text-decoration:underline; }
.marca { font-size:11px; padding:1px 7px; border-radius:10px; border:1px solid; white-space:nowrap; }
.prestado { color:var(--verde); border-color:#2f5c3b; background:#16241a; }
.propio { color:var(--suave); border-color:#333b45; background:#1b2027; }
.bloqueado { color:var(--ambar); border-color:#5a4a22; background:#241f11; }
.nuevo { color:var(--acento); border-color:#2b5878; background:#14222c; }
.fuera { color:var(--rojo); border-color:#5c2f2f; background:#241717; }
.dim { color:var(--suave); }
#vacio { padding:30px 24px; color:var(--suave); }
</style>
</head>
<body>
<header>
  <h1>Biblioteca familiar de Steam</h1>
  <p id="stats"></p>
</header>
<div class="aviso" id="aviso" hidden>
  <span id="avisoTexto"></span>
  <button id="verNuevos" type="button">Ver solo novedades</button>
</div>
<div class="controles">
  <input id="q" type="search" placeholder="Buscar por nombre... (los acentos dan igual)" autocomplete="off">
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
    <option value="dueno">Dueno A-Z</option>
  </select>
  <label class="check"><input type="checkbox" id="soloNuevos"> Solo novedades</label>
</div>
<div id="resumen"></div>
<table>
  <thead>
    <tr>
      <th>Juego</th>
      <th>Dueno</th>
      <th>Origen</th>
      <th>Estado</th>
      <th class="der">Tus horas</th>
      <th class="der">Ultima sesion</th>
    </tr>
  </thead>
  <tbody id="cuerpo"></tbody>
</table>
<div id="vacio" hidden>Ningun juego cumple esos filtros.</div>

<script>
const DATOS = __DATOS__;
const FECHA_NOV = __FECHA_NOV__;
const HAY_NOV = __HAY_NOV__;

const plano = s => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
DATOS.forEach(d => { d.b = plano(d.n); });

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
  "<b>" + totales.juegos + "</b> juegos &middot; <b>" + totales.prestados + "</b> prestados &middot; " +
  "<b>" + totales.jugables + "</b> jugables ahora &middot; <b>" + totales.jugados + "</b> ya jugados de ellos &middot; " +
  "<b>" + (totales.horas / 60).toFixed(1).replace(".", ",") + "</b> h acumuladas en prestados";

if (HAY_NOV) {
  const nuevos = DATOS.filter(d => d.w === "nuevo").length;
  const fuera = DATOS.filter(d => d.w === "fuera").length;
  $("aviso").hidden = false;
  $("avisoTexto").textContent = "Novedades desde la ultima vez (" + FECHA_NOV + "): " +
    nuevos + " juegos nuevos, " + fuera + " que ya no estan.";
}

const horas = m => (m / 60).toFixed(1).replace(".", ",");
const fecha = u => u ? u.split("-").reverse().join("/") : "";

function pinta() {
  const q = plano($("q").value.trim());
  const origen = $("origen").value;
  const estado = $("estado").value;
  const orden = $("orden").value;
  const soloNuevos = $("soloNuevos").checked;

  let lista = DATOS.filter(d => {
    if (q && !d.b.includes(q)) return false;
    if (origen !== "todo" && d.s !== origen) return false;
    if (soloNuevos && d.w !== "nuevo") return false;
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
  else if (orden === "dueno") lista.sort((a, b) => (a.d || "zz").localeCompare(b.d || "zz", "es") || a.n.localeCompare(b.n, "es"));
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
    if (d.w === "nuevo") {
      const b = document.createElement("span");
      b.className = "marca nuevo";
      b.textContent = "nuevo";
      b.title = "Entro despues del " + d.wf;
      cont.appendChild(b);
    } else if (d.w === "fuera") {
      const b = document.createElement("span");
      b.className = "marca fuera";
      b.textContent = "fuera";
      cont.appendChild(b);
    } else if (d.w === "nuevo_dueno") {
      const b = document.createElement("span");
      b.className = "marca nuevo";
      b.textContent = "+ dueno";
      cont.appendChild(b);
    }
    td1.appendChild(cont);

    const td2 = document.createElement("td");
    td2.className = "dim";
    td2.textContent = d.d || "";
    td2.title = d.d || "";

    const td3 = document.createElement("td");
    const m3 = document.createElement("span");
    m3.className = "marca " + (d.s === "family" ? "prestado" : "propio");
    m3.textContent = d.s === "family" ? "prestado" : "tuyo";
    td3.appendChild(m3);

    const td4 = document.createElement("td");
    if (!d.p) {
      const m4 = document.createElement("span");
      m4.className = "marca bloqueado";
      m4.textContent = d.e || "bloqueado";
      m4.title = d.e;
      td4.appendChild(m4);
    } else {
      const sp = document.createElement("span");
      sp.className = "dim";
      sp.textContent = "jugable";
      td4.appendChild(sp);
    }

    const td5 = document.createElement("td");
    td5.className = "der" + (d.m === 0 ? " dim" : "");
    td5.textContent = d.m > 0 ? horas(d.m) + " h" : "";

    const td6 = document.createElement("td");
    td6.className = "der dim";
    td6.textContent = fecha(d.u);

    tr.append(td1, td2, td3, td4, td5, td6);
    frag.appendChild(tr);
  }
  cuerpo.replaceChildren(frag);
}

["q", "origen", "estado", "orden", "soloNuevos"].forEach(id => $(id).addEventListener("input", pinta));
$("verNuevos").addEventListener("click", () => {
  $("soloNuevos").checked = !$("soloNuevos").checked;
  pinta();
});
pinta();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
