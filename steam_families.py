#!/usr/bin/env python3
"""
Steam Families: exporta tu biblioteca familiar y detecta lo que ha entrado.

Un solo archivo, sin dependencias. Hace tres cosas:

  python steam_families.py            abre la interfaz en el navegador
  python steam_families.py --exportar exporta sin interfaz (necesita token)
  python steam_families.py --panel    regenera el panel a partir del CSV

El token se pide una vez y se guarda cifrado con DPAPI; a partir de ahi la
interfaz se actualiza sola hasta que caduque (24 h). No se guarda ninguna
cookie de Steam.
"""

import argparse
import base64
import csv
import ctypes
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


# =====================  exportador  =====================

API = "https://api.steampowered.com"
UA = "steam-family-library/2.0"
EXCLUDE_REASONS = {
    0: "",
    1: "excluido por el dueno",
    2: "no se puede compartir",
    3: "restringido por region o DRM",
}
COLUMNAS = [
    "appid", "name", "source", "playable", "exclude_reason",
    "playtime_minutes", "acquired", "last_played", "store_url",
]


def die(msg):
    raise SystemExit(msg)


def carpeta(texto):
    """Valida y prepara la carpeta de datos. Falla con un mensaje util, no con un traceback."""
    raros = sorted({c for c in texto if c in '"<>|*?'}) if os.name == "nt" else []
    if raros:
        die(f"la ruta {texto} lleva caracteres no validos ({', '.join(raros)}). "
            "Suele ser una comilla colada por la barra final de la ruta.")
    try:
        p = Path(texto).expanduser().resolve()
        if p.exists() and not p.is_dir():
            die(f"{p} existe y no es una carpeta")
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        die(f"no puedo usar la carpeta {texto}: {e}")
    return p


def api_get(metodo, params):
    url = f"{API}/{metodo}/?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp).get("response", {})
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:400]
        pista = "\nEl token caduca a las 24 h: saca uno nuevo." if e.code in (401, 403) else ""
        die(f"{metodo} devolvio HTTP {e.code}\n{cuerpo}{pista}")
    except urllib.error.URLError as e:
        die(f"no se pudo conectar con la API de Steam: {e.reason}")


def normaliza_token(texto):
    """Acepta el token suelto, entre comillas o el JSON entero del endpoint."""
    t = (texto or "").strip().strip("\"'")
    if t.startswith("{"):
        try:
            datos = json.loads(t)
            interno = (datos.get("data") or {}).get("webapi_token") or datos.get("webapi_token")
            if interno:
                t = str(interno).strip().strip("\"'")
        except Exception:
            pass
    return t


def steamid_del_token(token):
    partes = token.split(".")
    if len(partes) != 3:
        die("el token no parece un JWT. Copia solo el valor de webapi_token, sin comillas")
    try:
        relleno = partes[1] + "=" * (-len(partes[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(relleno))
    except Exception:
        die("no se pudo leer el contenido del token")
    exp = claims.get("exp")
    if exp and datetime.now(tz=timezone.utc).timestamp() > exp:
        die("ese token ya ha caducado. Recarga la pagina del token para tener uno nuevo")
    sid = claims.get("sub")
    if not sid:
        die("el token no lleva SteamID")
    return str(sid)


def etiqueta(steamid):
    """Identificador estable sin exponer el SteamID: mismo numero siempre, sin nombre."""
    return hashlib.sha256(steamid.encode()).hexdigest()[:10]


def nombres(steamids, previos=None, api_key=""):
    """Alias publico de cada miembro. Sin API key: endpoint de la comunidad.

    `previos` va por etiqueta (hash), no por SteamID, para no guardar los IDs.
    429 significa que Steam ha frenado las peticiones: se devuelve lo que haya y
    se reintenta en la siguiente ejecucion.
    """
    previos = dict(previos or {})
    out = {}
    faltan = []
    for sid in steamids:
        h = etiqueta(sid)
        previo_nombre = previos.get(h, "")
        if previo_nombre and not previo_nombre.startswith("Miembro "):
            out[sid] = previo_nombre
        else:
            faltan.append(sid)
    if not faltan:
        return out

    if api_key:
        try:
            params = urllib.parse.urlencode({"key": api_key, "steamids": ",".join(faltan)})
            url = f"{API}/ISteamUser/GetPlayerSummaries/v2/?{params}"
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20) as r:
                for p in json.load(r).get("response", {}).get("players", []):
                    sid = str(p.get("steamid", ""))
                    if sid in faltan and p.get("personaname"):
                        out[sid] = p["personaname"].strip()
        except Exception:
            pass

    pendientes = [s for s in faltan if s not in out]
    for espera in (0, 2, 6):
        if not pendientes:
            break
        if espera:
            time.sleep(espera)
        try:
            url = "https://steamcommunity.com/actions/ajaxresolveusers?steamids=" + ",".join(pendientes)
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                for u in json.load(r):
                    sid = str(u.get("steamid", ""))
                    if sid in pendientes and u.get("persona_name"):
                        out[sid] = u["persona_name"].strip()
        except Exception:
            pass
        pendientes = [s for s in pendientes if s not in out]

    return out


def rellenar_huecos(alias, miembros, yo):
    """Quien no se haya podido resolver sale como Miembro 1, 2... siempre el mismo."""
    n = 0
    for sid in miembros:
        if sid == yo or sid in alias:
            continue
        n += 1
        alias[sid] = f"Miembro {n}"
    return alias


def dia(epoch):
    if not epoch:
        return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")


def descargar(token, con_free, con_no_juegos, con_nombres=True, previo=None, api_key=""):
    yo = steamid_del_token(token)

    fam = api_get("IFamilyGroupsService/GetFamilyGroupForUser/v1", {
        "access_token": token,
        "steamid": yo,
        "include_family_group_response": "true",
    })
    grupo_id = fam.get("family_groupid")
    if not grupo_id or fam.get("is_not_member_of_any_group"):
        die("esta cuenta no esta en ningun grupo familiar de Steam, asi que no hay biblioteca compartida")

    grupo = fam.get("family_group", {})
    miembros = [str(m.get("steamid")) for m in grupo.get("members", [])]

    lib = api_get("IFamilyGroupsService/GetSharedLibraryApps/v1", {
        "access_token": token,
        "family_groupid": grupo_id,
        "include_own": "true",
        "include_excluded": "true",
        "include_free": str(bool(con_free)).lower(),
        "include_non_games": str(bool(con_no_juegos)).lower(),
        "language": "spanish",
    })
    apps = lib.get("apps", [])
    if not apps:
        die("la API no devolvio ninguna app. Puede que el token sea de otra cuenta")

    alias = {}
    if con_nombres:
        todos = set(miembros)
        for a in apps:
            todos.update(str(o) for o in a.get("owner_steamids", []))
        alias = nombres(sorted(todos), (previo or {}).get("nombres"), api_key)
        alias = rellenar_huecos(alias, miembros, yo)
    alias.setdefault(yo, "tú")

    juegos, csv_filas, snapshot = [], [], {}
    previos_juegos = (previo or {}).get("juegos") or {}
    hoy = datetime.now().strftime("%Y-%m-%d")
    for a in apps:
        appid = a.get("appid")
        duenos = [str(o) for o in a.get("owner_steamids", [])]
        motivo = a.get("exclude_reason", 0)
        nombre = a.get("name", "")
        propio = yo in duenos
        antes = previos_juegos.get(str(appid)) or {}
        juego = {
            "appid": appid,
            "name": nombre,
            "source": "own" if propio else "family",
            "playable": motivo == 0,
            "exclude_reason": EXCLUDE_REASONS.get(motivo, f"desconocido ({motivo})"),
            "playtime_minutes": a.get("rt_playtime", 0),
            "acquired": dia(a.get("rt_time_acquired")),
            "last_played": dia(a.get("rt_last_played")),
            "store_url": f"https://store.steampowered.com/app/{appid}",
            "owners": [etiqueta(o) for o in duenos],
        }
        juegos.append(juego)
        csv_filas.append({k: v for k, v in juego.items() if k in COLUMNAS})
        snapshot[str(appid)] = {
            "n": nombre,
            "o": sorted(juego["owners"]),
            "p": juego["playable"],
            # se conserva la fecha en la que lo vimos por primera vez
            "v": antes.get("v") or hoy,
        }

    juegos.sort(key=lambda g: g["name"].lower())
    csv_filas.sort(key=lambda g: g["name"].lower())

    return {
        "yo": etiqueta(yo),
        "grupo": {"id": grupo_id, "nombre": grupo.get("name", ""), "miembros": len(miembros)},
        "alias": {etiqueta(k): v for k, v in alias.items()},
        "juegos": juegos,
        "csv": csv_filas,
        "snapshot": {
            "fecha": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "yo": etiqueta(yo),
            "grupo": grupo.get("name", ""),
            "nombres": {etiqueta(k): v for k, v in alias.items()},
            "juegos": snapshot,
        },
    }


def es_gratis(appid):
    """True/False si la ficha de la tienda lo dice; None si no se puede saber."""
    try:
        url = (f"https://store.steampowered.com/api/appdetails?appids={appid}"
               "&filters=basic&l=spanish")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            datos = json.load(r)
        info = (datos.get(str(appid)) or {}).get("data") or {}
        if "is_free" in info:
            return bool(info["is_free"])
    except Exception:
        pass
    return None


def comparar(antes, despues, yo, alias):
    """Novedades entre dos retratos de la biblioteca."""
    previos = (antes or {}).get("juegos", {})
    actuales = despues.get("juegos", {})
    eventos = []

    def quien(ids):
        otros = [i for i in ids if i != yo]
        nombres = [alias.get(i, i) for i in otros]
        return ", ".join(sorted(nombres)) if nombres else ""

    for appid, j in actuales.items():
        if appid not in previos:
            eventos.append({
                "evento": "nuevo",
                "appid": int(appid),
                "nombre": j["n"],
                "quien": quien(j["o"]),
                "propio": yo in j["o"],
            })
        else:
            nuevos = set(j["o"]) - set(previos[appid]["o"])
            if nuevos:
                eventos.append({
                    "evento": "nuevo_dueno",
                    "appid": int(appid),
                    "nombre": j["n"],
                    "quien": quien(nuevos),
                    "propio": yo in nuevos,
                })

    for appid, j in previos.items():
        if appid not in actuales:
            eventos.append({
                "evento": "fuera",
                "appid": int(appid),
                "nombre": j["n"],
                "quien": quien(j["o"]),
                "propio": yo in j["o"],
            })

    eventos.sort(key=lambda e: (e["evento"], e["nombre"].lower()))
    return eventos


def escribir_csv(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def anotar_historial(ruta, eventos, ahora):
    nuevo = not Path(ruta).exists()
    with open(ruta, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["fecha", "evento", "appid", "nombre", "quien", "propio"])
        for e in eventos:
            w.writerow([ahora, e["evento"], e["appid"], e["nombre"], e["quien"], "si" if e["propio"] else "no"])


def chivato(eventos, ahora):
    def de(e):
        return e["quien"] or ("ti" if e["propio"] else "otro miembro")

    lineas = [f"Novedades del {ahora}", ""]
    if not eventos:
        lineas.append("Sin cambios desde la ultima vez.")
    for e in eventos:
        extra = "  [gratis]" if e.get("gratis") else ""
        if e["evento"] == "nuevo":
            lineas.append(f"+ {e['nombre']}  (de {de(e)}){extra}")
        elif e["evento"] == "nuevo_dueno":
            lineas.append(f"= {e['nombre']}  (ahora tambien de {de(e)})")
        else:
            lineas.append(f"- {e['nombre']}  (ya no esta; era de {de(e)})")
    return "\n".join(lineas) + "\n"




# =====================  panel  =====================

def leer_json(ruta, defecto=None):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return {} if defecto is None else defecto




PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3' fill='%2366c0f4'/><text x='8' y='12' font-size='10' font-family='sans-serif' text-anchor='middle' fill='%2312151a'>S</text></svg>">
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
thead th:nth-child(2) { width:150px; }
thead th:nth-child(3) { width:100px; }
thead th:nth-child(4) { width:180px; }
thead th:nth-child(5) { width:100px; }
thead th:nth-child(6) { width:120px; }
thead th:nth-child(7) { width:100px; }
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
.atajo { background:#22303c; color:var(--acento); border:1px solid #2b5878; border-radius:6px; padding:7px 12px; font:inherit; cursor:pointer; }
.atajo:hover { background:#2a3d4d; }
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
    <option value="anadido">Anadido (mas reciente)</option>
    <option value="nombre">Nombre A-Z</option>
    <option value="horas">Mas horas jugadas</option>
    <option value="reciente">Ultima sesion</option>
    <option value="dueno">Dueno A-Z</option>
  </select>
  <select id="antiguedad">
    <option value="todo">Cualquier fecha</option>
    <option value="30">Anadidos en 30 dias</option>
    <option value="90">Anadidos en 90 dias</option>
    <option value="anio">Anadidos este anio</option>
  </select>
  <label class="check"><input type="checkbox" id="soloNuevos"> Solo novedades</label>
  <button type="button" id="presetCompras" class="atajo">Compras de la familia (90 dias)</button>
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
      <th class="der">Anadido</th>
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
const hoyISO = new Date().toISOString().slice(0, 10);
const isoDias = n => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
const recientesAnio = DATOS.filter(d => d.q && d.q >= hoyISO.slice(0, 4) + "-01-01").length;
$("stats").innerHTML =
  "<b>" + totales.juegos + "</b> juegos &middot; <b>" + totales.prestados + "</b> prestados &middot; " +
  "<b>" + totales.jugables + "</b> jugables ahora &middot; <b>" + totales.jugados + "</b> ya jugados de ellos &middot; " +
  "<b>" + (totales.horas / 60).toFixed(1).replace(".", ",") + "</b> h acumuladas en prestados &middot; " +
  "<b>" + recientesAnio + "</b> anadidos este anio";

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
  const antiguedad = $("antiguedad").value;
  const soloNuevos = $("soloNuevos").checked;

  let corte = "";
  if (antiguedad === "30") corte = isoDias(30);
  else if (antiguedad === "90") corte = isoDias(90);
  else if (antiguedad === "anio") corte = hoyISO.slice(0, 4) + "-01-01";

  let lista = DATOS.filter(d => {
    if (q && !d.b.includes(q)) return false;
    if (origen !== "todo" && d.s !== origen) return false;
    if (soloNuevos && d.w !== "nuevo") return false;
    if (corte && !(d.q && d.q >= corte)) return false;
    switch (estado) {
      case "jugable": if (!d.p) return false; break;
      case "bloqueado": if (d.p) return false; break;
      case "jugados": if (d.m === 0) return false; break;
      case "sinestrenar": if (d.m > 0) return false; break;
    }
    return true;
  });

  if (orden === "anadido") lista.sort((a, b) => (b.q || "").localeCompare(a.q || "") || a.n.localeCompare(b.n, "es"));
  else if (orden === "horas") lista.sort((a, b) => b.m - a.m || a.n.localeCompare(b.n, "es"));
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
      if (d.g) {
        const g = document.createElement("span");
        g.className = "marca dim";
        g.textContent = "gratis";
        g.title = "La ficha de Steam lo marca como free-to-play";
        cont.appendChild(g);
      }
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

    const td7 = document.createElement("td");
    td7.className = "der dim";
    td7.textContent = fecha(d.q);
    td7.title = "Fecha en la que Steam dice que se adquirio";

    tr.append(td1, td2, td3, td4, td5, td6, td7);
    frag.appendChild(tr);
  }
  cuerpo.replaceChildren(frag);
}

["q", "origen", "estado", "orden", "antiguedad", "soloNuevos"].forEach(id => $(id).addEventListener("input", pinta));
$("verNuevos").addEventListener("click", () => {
  $("soloNuevos").checked = !$("soloNuevos").checked;
  pinta();
});
$("presetCompras").addEventListener("click", () => {
  $("q").value = "";
  $("origen").value = "family";
  $("estado").value = "todo";
  $("antiguedad").value = "90";
  $("orden").value = "anadido";
  $("soloNuevos").checked = false;
  pinta();
});
pinta();
</script>
</body>
</html>
"""




# =====================  interfaz local  =====================


def exportar(datos, token, api_key="", include_free=False, include_non_games=False,
             con_nombres=True, con_historial=True, con_precios=True):
    """Descarga la biblioteca, escribe el CSV y calcula las novedades."""
    ruta_snap = Path(datos) / "snapshot.json"

    previo = {}
    if Path(ruta_snap).exists():
        try:
            previo = json.loads(Path(ruta_snap).read_text(encoding="utf-8"))
            if not isinstance(previo, dict) or "juegos" not in previo:
                raise ValueError("formato inesperado")
        except Exception:
            previo = {}
            try:
                Path(ruta_snap).replace(Path(datos) / "snapshot.corrupto.json")
            except Exception:
                pass

    datos_nuevos = descargar(token, include_free, include_non_games, con_nombres, previo, api_key)
    try:
        escribir_csv(Path(datos) / "library.csv", datos_nuevos["csv"])
    except OSError as e:
        die(f"no puedo escribir library.csv en {datos}: {e}")

    juegos = datos_nuevos["juegos"]
    prestados = sum(1 for g in juegos if datos_nuevos["yo"] not in g["owners"])
    eventos, ahora = [], datetime.now().strftime("%Y-%m-%d %H:%M")

    if con_historial:
        if previo:
            eventos = comparar(previo, datos_nuevos["snapshot"], datos_nuevos["yo"], datos_nuevos["alias"])
            if eventos and con_precios:
                for e in [x for x in eventos if x["evento"] == "nuevo"][:25]:
                    gratis = es_gratis(e["appid"])
                    if gratis is not None:
                        e["gratis"] = gratis
                    time.sleep(1.1)
        try:
            Path(ruta_snap).write_text(json.dumps(datos_nuevos["snapshot"], ensure_ascii=False, indent=1),
                                       encoding="utf-8")
            (Path(datos) / "novedades.json").write_text(json.dumps({
                "fecha": ahora, "eventos": eventos}, ensure_ascii=False, indent=1), encoding="utf-8")
            (Path(datos) / "novedades.txt").write_text(chivato(eventos, ahora), encoding="utf-8")
            anotar_historial(Path(datos) / "historial.csv", eventos, ahora)
        except OSError as e:
            die(f"no puedo escribir el historial en {datos}: {e}")

    return {
        "juegos": len(juegos),
        "prestados": prestados,
        "eventos": eventos,
        "grupo": datos_nuevos["grupo"],
        "primera": not previo,
    }


def generar_panel(datos):
    """Escribe panel.html, prestados.csv y prestados.txt. Devuelve el resumen."""
    datos = Path(datos)
    csv_path = datos / "library.csv"
    if not csv_path.exists():
        die(f"no encuentro {csv_path}. Ejecuta antes la exportacion")

    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f))
    except OSError as e:
        die(f"no puedo leer {csv_path}: {e}")
    except UnicodeDecodeError:
        die(f"{csv_path} no parece un CSV en UTF-8. Borralo y vuelve a exportar.")
    if not filas:
        die(f"{csv_path} esta vacio. Vuelve a exportar.")
    for obligatoria in ("appid", "name", "source"):
        if obligatoria not in filas[0]:
            die(f"{csv_path} no tiene la columna {obligatoria}. Vuelve a exportar.")

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
            return "tu" if yo in j.get("o", []) else ""
        return ", ".join(sorted(otros))

    juegos = []
    for r in filas:
        appid = str(r["appid"])
        e = marca.get(appid)
        try:
            minutos = int(float(r.get("playtime_minutes") or 0))
        except (TypeError, ValueError):
            minutos = 0
        juegos.append({
            "n": r["name"],
            "a": appid,
            "s": r["source"],
            "p": r["playable"] == "True",
            "e": r["exclude_reason"],
            "m": minutos,
            "u": r["last_played"],
            "d": dueno(r),
            "w": e["evento"] if e else "",
            "wf": nov.get("fecha", ""),
            "g": bool(e.get("gratis")) if e else False,
            "v": (por_appid.get(appid) or {}).get("v", ""),
            "q": r["acquired"],
        })

    prestados = [j for j in juegos if j["s"] == "family"]
    prestados.sort(key=lambda j: j["n"].lower())
    try:
        if prestados:
            with (datos / "prestados.csv").open("w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(filas[0].keys()), extrasaction="ignore")
                w.writeheader()
                por_id = {str(r["appid"]): r for r in filas}
                w.writerows(por_id[j["a"]] for j in prestados)
        jugables = sorted((j["n"] for j in prestados if j["p"]), key=str.lower)
        (datos / "prestados.txt").write_text("\n".join(jugables) + "\n", encoding="utf-8")
    except OSError as e:
        die(f"no puedo escribir los ficheros de prestados en {datos}: {e}")

    blob = json.dumps(juegos, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = PLANTILLA.replace("__DATOS__", blob)
    html = html.replace("__FECHA_NOV__", json.dumps(nov.get("fecha", ""), ensure_ascii=False))
    html = html.replace("__HAY_NOV__", "true" if marca else "false")

    salida = datos / "panel.html"
    try:
        salida.write_text(html, encoding="utf-8")
    except OSError as e:
        die(f"no puedo escribir {salida}: {e}")

    return {"juegos": len(juegos), "prestados": len(prestados)}


def ejecutar(datos, token, api_key=""):
    """Lo que hace el boton Actualizar: todo en el mismo proceso."""
    try:
        resumen = exportar(datos, token, api_key)
        panel = generar_panel(datos)
    except SystemExit as e:
        return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    texto = (f"{resumen['juegos']} juegos, {resumen['prestados']} prestados, "
             f"{len(resumen['eventos'])} novedades\n"
             f"panel con {panel['juegos']} juegos")
    return True, texto


AQUI = Path(__file__).resolve().parent
PROHIBIDOS = set('"<>|*?')
CANDADO = threading.Lock()
FICHEROS = {
    "/panel.html": ("panel.html", "text/html; charset=utf-8"),
    "/library.csv": ("library.csv", "text/csv; charset=utf-8"),
    "/prestados.csv": ("prestados.csv", "text/csv; charset=utf-8"),
    "/prestados.txt": ("prestados.txt", "text/plain; charset=utf-8"),
    "/novedades.txt": ("novedades.txt", "text/plain; charset=utf-8"),
    "/historial.csv": ("historial.csv", "text/csv; charset=utf-8"),
}


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(datos):
    buf = ctypes.create_string_buffer(datos, len(datos))
    return _BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _proteger(datos):
    entrada = _blob(datos)
    salida = _BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(entrada), "steam-families", None, None, None, 0, ctypes.byref(salida))
    if not ok:
        raise OSError("CryptProtectData ha fallado")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def _desproteger(datos):
    entrada = _blob(datos)
    salida = _BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida))
    if not ok:
        raise OSError("CryptUnprotectData ha fallado")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def ruta_token():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            return None
        return Path(base) / "SteamFamilies" / "token.bin"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "steam-families" / "token.bin"


def caduca_token(token):
    """Fecha de caducidad legible del JWT, o cadena vacia si no se puede leer."""
    try:
        parte = token.split(".")[1]
        parte += "=" * (-len(parte) % 4)
        datos = json.loads(base64.urlsafe_b64decode(parte))
        exp = datos.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass
    return ""


def token_caducado(token):
    try:
        parte = token.split(".")[1]
        parte += "=" * (-len(parte) % 4)
        datos = json.loads(base64.urlsafe_b64decode(parte))
        exp = datos.get("exp")
        return bool(exp) and datetime.now(tz=timezone.utc).timestamp() > exp
    except Exception:
        return True


def guardar_token(token):
    """Windows: cifrado con DPAPI. Linux y macOS: fichero con permisos 600."""
    ruta = ruta_token()
    if ruta is None:
        return False
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            ruta.write_bytes(_proteger(token.encode("utf-8")))
        else:
            ruta.write_text(token, encoding="utf-8")
            os.chmod(ruta, 0o600)
        return True
    except Exception:
        return False


def leer_token():
    ruta = ruta_token()
    if ruta is None or not ruta.exists():
        return None
    try:
        if os.name == "nt":
            token = _desproteger(ruta.read_bytes()).decode("utf-8").strip()
        else:
            token = ruta.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not token or token_caducado(token):
        olvidar_token()
        return None
    return token


def olvidar_token():
    ruta = ruta_token()
    try:
        if ruta and ruta.exists():
            ruta.unlink()
    except OSError:
        pass


def carpeta_de_datos(texto):
    """Comprueba la ruta antes de tocar nada y explica el problema en castellano."""
    texto = (texto or "").strip()
    if not texto:
        raise SystemExit("la carpeta de datos esta vacia. Pasa --datos <ruta>.")
    raros = sorted({c for c in texto if c in PROHIBIDOS}) if os.name == "nt" else []
    if raros:
        raise SystemExit(
            f"la ruta de datos lleva caracteres no validos: {texto}\n"
            f"sobran {', '.join(raros)}. Suele pasar cuando el .cmd pasa \"%~dp0\" "
            "y la barra final se come la comilla: usa \"%~dp0.\"."
        )
    ruta = Path(texto).expanduser()
    try:
        ruta = ruta.resolve()
    except OSError as e:
        raise SystemExit(f"no puedo resolver la ruta {texto}: {e}")
    if ruta.exists() and not ruta.is_dir():
        raise SystemExit(f"{ruta} existe y no es una carpeta.")
    try:
        ruta.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SystemExit(f"no puedo crear o abrir la carpeta {ruta}: {e}")
    if not ruta.is_dir():
        raise SystemExit(f"{ruta} no es una carpeta.")
    try:
        prueba = ruta / ".escritura.tmp"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
    except OSError as e:
        raise SystemExit(f"la carpeta {ruta} no admite escritura: {e}")
    return ruta


def estado(datos: Path):
    snap = leer_json(datos / "snapshot.json")
    nov = leer_json(datos / "novedades.json")
    juegos = snap.get("juegos") or {}
    yo = snap.get("yo", "")
    prestados = sum(1 for j in juegos.values() if yo not in j.get("o", []))
    jugables = sum(1 for j in juegos.values() if yo not in j.get("o", []) and j.get("p"))
    horas = 0
    csv_path = datos / "library.csv"
    if csv_path.exists():
        import csv as _csv
        try:
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                for r in _csv.DictReader(f):
                    if (r.get("source") or "") != "family":
                        continue
                    try:
                        horas += int(float(r.get("playtime_minutes") or 0))
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass
    return {
        "ok": True,
        "primera": not bool(juegos),
        "grupo": snap.get("grupo", ""),
        "juegos": len(juegos),
        "prestados": prestados,
        "jugables": jugables,
        "horas": round(horas / 60, 1),
        "nombres": snap.get("nombres", {}),
        "yo": yo,
        "novedades": nov.get("eventos", []),
        "fecha_novedades": nov.get("fecha", ""),
        "ficheros": {k: (datos / v[0]).exists() for k, v in FICHEROS.items()},
    }


class Servidor(ThreadingHTTPServer):
    # En Windows, SO_REUSEADDR deja que dos procesos escuchen el mismo puerto:
    # mejor que falle y que la app busque el siguiente libre.
    allow_reuse_address = False
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    datos = Path(".")
    servidor = None


    def log_message(self, formato, *args):
        pass

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8", extra=None):
        if isinstance(cuerpo, (dict, list)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False)
        datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._fallo(e)

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._fallo(e)

    def _fallo(self, e):
        try:
            self._enviar(500, {"ok": False, "error": f"Fallo interno: {type(e).__name__}: {e}"})
        except Exception:
            pass

    def _origen_ok(self):
        """Solo acepta POST de la propia pagina: evita que otra web toque los datos."""
        origen = self.headers.get("Origin")
        if not origen:
            return True
        puerto = self.servidor.server_address[1]
        return origen in (f"http://127.0.0.1:{puerto}", f"http://localhost:{puerto}")

    def _get(self):
        if self.path in ("/", "/index.html"):
            self._enviar(200, PAGINA, "text/html; charset=utf-8")
            return
        if self.path == "/api/estado":
            self._enviar(200, estado(self.datos))
            return
        if self.path == "/api/token":
            guardado = leer_token()
            self._enviar(200, {"ok": True, "token": guardado, "guardado": bool(guardado),
                               "caduca": caduca_token(guardado) if guardado else ""})
            return
        if self.path in FICHEROS:
            nombre, tipo = FICHEROS[self.path]
            ruta = self.datos / nombre
            if not ruta.exists():
                self._enviar(404, {"ok": False, "error": f"todavia no existe {nombre}"})
                return
            try:
                contenido = ruta.read_bytes()
            except OSError as e:
                self._enviar(500, {"ok": False, "error": f"no puedo leer {nombre}: {e}"})
                return
            self._enviar(200, contenido, tipo,
                         {"Content-Disposition": f'inline; filename="{nombre}"'})
            return
        self._enviar(404, {"ok": False, "error": "no existe"})

    def _post(self):
        if not self._origen_ok():
            self._enviar(403, {"ok": False, "error": "peticion de otro sitio: solo vale desde esta pagina"})
            return
        try:
            largo = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            largo = 0
        if largo > 100_000:
            self._enviar(413, {"ok": False, "error": "cuerpo demasiado grande"})
            return
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except Exception:
            self._enviar(400, {"ok": False, "error": "JSON invalido"})
            return
        if not isinstance(cuerpo, dict):
            self._enviar(400, {"ok": False, "error": "esperaba un objeto JSON"})
            return

        if self.path == "/api/actualizar":
            token = str(cuerpo.get("token") or "").strip().strip("\"'")
            if not token:
                self._enviar(400, {"ok": False, "error": "falta el token"})
                return
            if len(token) > 4000:
                self._enviar(400, {"ok": False, "error": "eso no es un token"})
                return
            api_key = str(cuerpo.get("api_key") or "").strip()
            if api_key and (len(api_key) > 64 or not all(c.isalnum() for c in api_key)):
                self._enviar(400, {"ok": False, "error": "la API key no tiene buena pinta: son 32 caracteres en hexadecimal"})
                return
            if not CANDADO.acquire(blocking=False):
                self._enviar(409, {"ok": False, "error": "Ya hay una actualizacion en curso. Espera a que termine."})
                return
            try:
                ok, mensaje = ejecutar(self.datos, token, api_key)
            finally:
                CANDADO.release()
            if not ok:
                self._enviar(500, {"ok": False, "error": mensaje})
                return
            if cuerpo.get("guardar", True):
                guardar_token(token)
            else:
                olvidar_token()
            datos = estado(self.datos)
            datos["log"] = mensaje
            datos["caduca"] = caduca_token(token)
            self._enviar(200, datos)
            return

        if self.path == "/api/detener":
            self._enviar(200, {"ok": True})
            threading.Thread(target=self.servidor.shutdown, daemon=True).start()
            return

        if self.path == "/api/olvidar":
            olvidar_token()
            self._enviar(200, {"ok": True})
            return

        self._enviar(404, {"ok": False, "error": "no existe"})


PAGINA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3' fill='%2366c0f4'/><text x='8' y='12' font-size='10' font-family='sans-serif' text-anchor='middle' fill='%2312151a'>S</text></svg>">
<title>Steam Families</title>
<style>
:root { --fondo:#12151a; --panel:#1a1f26; --borde:#2a313b; --texto:#dfe6ee; --suave:#8b98a8; --acento:#66c0f4; --verde:#7bd88f; --rojo:#e06c6c; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fondo); color:var(--texto); font-family:"Segoe UI",system-ui,-apple-system,sans-serif; font-size:14px; line-height:1.5; }
main { max-width:880px; margin:0 auto; padding:32px 22px 60px; }
h1 { font-size:24px; margin:0 0 4px; }
.sub { color:var(--suave); margin:0 0 26px; }
.paso { background:var(--panel); border:1px solid var(--borde); border-radius:10px; padding:18px 20px; margin-bottom:14px; }
.paso h2 { font-size:14px; margin:0 0 10px; text-transform:uppercase; letter-spacing:.05em; color:var(--suave); }
a { color:var(--acento); }
code { background:#0e1116; border:1px solid var(--borde); border-radius:4px; padding:1px 5px; font-size:12px; }
.fila { display:flex; gap:8px; flex-wrap:wrap; }
input[type=password], input[type=text] { flex:1 1 320px; min-width:220px; background:#0e1116; color:var(--texto); border:1px solid var(--borde); border-radius:6px; padding:9px 11px; font:inherit; }
input:focus { outline:none; border-color:var(--acento); }
button { background:#2a6f97; color:#fff; border:none; border-radius:6px; padding:9px 16px; font:inherit; cursor:pointer; }
button:hover { background:#3583b0; }
button:disabled { opacity:.55; cursor:default; }
button.sec { background:#232a33; color:var(--texto); border:1px solid var(--borde); }
button.sec:hover { background:#2b333d; }
#estado { margin-top:10px; min-height:22px; font-size:13px; color:var(--suave); }
.error { color:var(--rojo); white-space:pre-wrap; }
.tarjetas { display:flex; gap:10px; flex-wrap:wrap; margin:6px 0 4px; }
.tarjeta { flex:1 1 130px; background:#0e1116; border:1px solid var(--borde); border-radius:8px; padding:12px 14px; }
.tarjeta b { display:block; font-size:22px; font-weight:600; }
.tarjeta span { color:var(--suave); font-size:12px; }
table { width:100%; border-collapse:collapse; margin-top:8px; }
th, td { text-align:left; padding:7px 8px; border-bottom:1px solid #1e242c; font-size:13px; }
th { color:var(--suave); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
td.quien { color:var(--suave); }
.si { color:var(--verde); }
.no { color:var(--rojo); }
details summary { cursor:pointer; color:var(--suave); font-size:13px; }
details ol { margin:8px 0 0 18px; padding:0; color:var(--suave); font-size:13px; }
.pie { margin-top:26px; color:var(--suave); font-size:12px; }
label.check { display:flex; align-items:center; gap:8px; color:var(--suave); font-size:13px; }
label.check input { accent-color:var(--acento); }
.seguridad { margin:8px 0 0 18px; padding:0; color:var(--suave); font-size:13px; }
.seguridad li { margin-bottom:6px; }
</style>
</head>
<body>
<main>
  <h1>Steam Families</h1>
  <p class="sub">Exporta tu biblioteca familiar, separa lo que te prestan y detecta qué ha entrado nuevo.</p>

  <section class="paso">
    <h2>Paso 1 · El token</h2>
    <p style="margin:0 0 10px">
      Abre <a href="https://store.steampowered.com/pointssummary/ajaxgetasyncconfig" target="_blank" rel="noopener">esta página</a>
      con la sesión de Steam iniciada y copia el valor de <code>webapi_token</code>.
      Vale el token suelto o el JSON entero: el programa saca el token de donde esté.
    </p>
    <details>
      <summary>¿Por qué hace falta y qué es?</summary>
      <ol>
        <li>Es un JWT de Steam que caduca en unas 24 horas.</li>
        <li>Solo sirve para leer tu biblioteca familiar. No se guarda en disco.</li>
        <li>La página que abres es la oficial de Steam: devuelve un JSON y dentro está el token.</li>
      </ol>
    </details>
  </section>

  <section class="paso">
    <h2>Paso 2 · Pégalo aquí</h2>
    <div class="fila">
      <input id="token" type="password" placeholder="Token, o el JSON entero de esa pagina" autocomplete="off" spellcheck="false">
      <button id="pegar" type="button" class="sec">Pegar</button>
      <button id="ver" type="button" class="sec">Mostrar</button>
      <button id="lanzar" type="button">Actualizar</button>
    </div>
    <details style="margin-top:12px">
      <summary>Copiar el token en un solo clic</summary>
      <p style="color:var(--suave);font-size:13px;margin:8px 0">
        Arrastra este botón a la barra de marcadores:
        <a id="marcador" href="#" style="display:inline-block;padding:5px 10px;border:1px solid #2b5878;border-radius:6px;background:#22303c;text-decoration:none">Copiar token</a>
      </p>
      <p style="color:var(--suave);font-size:13px;margin:8px 0">
        Después, en la página del token de Steam, pulsa ese marcador: copia el token al portapapeles y te avisa.
        Vuelve aquí y pulsa <b>Pegar</b>.
      </p>
    </details>
    <details style="margin-top:8px">
      <summary>Que guarda y que no</summary>
      <ul class="seguridad">
        <li><b>Ninguna cookie.</b> El programa no lee, no pide y no guarda cookies de Steam.</li>
        <li>El token caduca en 24 h. En Windows se guarda cifrado con DPAPI en <code>%LOCALAPPDATA%\SteamFamilies\token.bin</code>; en Linux y macOS, con permisos 600 en <code>~/.local/share/steam-families/</code>.</li>
        <li>No se envia nada a ningun servidor propio: las unicas conexiones son a la API de Steam.</li>
        <li>Puedes borrarlo cuando quieras con <b>olvidar</b>.</li>
      </ul>
    </details>
    <details style="margin-top:8px">
      <summary>¿Los dueños salen como «Miembro 1»?</summary>
      <p style="color:var(--suave);font-size:13px;margin:8px 0">
        Steam limita las consultas de nombres cuando se piden muchas seguidas. Con una
        <a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener">API key gratuita</a>
        salen siempre. Solo se usa durante esta consulta y no se guarda.
      </p>
      <input id="apikey" type="text" placeholder="API key de Steam (opcional)" autocomplete="off" spellcheck="false" style="width:100%">
    </details>
    <div id="estado"></div>
    <label class="check" style="margin-top:10px">
      <input type="checkbox" id="recordar" checked>
      Recordar el token en este equipo, cifrado
      <a href="#" id="olvidar" style="margin-left:10px">olvidar</a>
    </label>
  </section>

  <section class="paso" id="resultado" hidden>
    <h2>Resultado</h2>
    <div class="tarjetas" id="tarjetas"></div>
    <div id="novedades"></div>
    <div class="fila" style="margin-top:14px">
      <button class="sec" onclick="window.open('/panel.html','_blank')">Abrir panel</button>
      <button class="sec" onclick="window.open('/prestados.csv','_blank')">Abrir CSV de prestados</button>
      <button class="sec" onclick="window.open('/novedades.txt','_blank')">Abrir novedades</button>
      <button class="sec" onclick="window.open('/historial.csv','_blank')">Historial</button>
    </div>
  </section>

  <p class="pie">
    Todo se ejecuta en tu ordenador y no se guarda ninguna cookie de Steam. Si marcas «recordar», el token queda guardado solo para tu usuario: cifrado con DPAPI en Windows, permisos 600 en Linux y macOS.
    <a href="#" id="detener">Detener la interfaz</a>
  </p>
</main>

<script>
const $ = id => document.getElementById(id);
const fmt = n => new Intl.NumberFormat("es-ES").format(n);

$("ver").addEventListener("click", () => {
  const t = $("token");
  t.type = t.type === "password" ? "text" : "password";
  $("ver").textContent = t.type === "password" ? "Mostrar" : "Ocultar";
});

const CODIGO = 'javascript:(async()=>{const r=await fetch("https://store.steampowered.com/pointssummary/ajaxgetasyncconfig",{credentials:"include"});const j=await r.json();let t=(j.data&&j.data.webapi_token)||j.webapi_token||"";t=t.replace(/^"|"$/g,"");if(!t){alert("Primero inicia sesion en Steam.");return;}try{await navigator.clipboard.writeText(t);alert("Token copiado. Vuelve a Steam Families y pulsa Pegar.");}catch(e){prompt("Copia el token:",t);}})();';
$("marcador").setAttribute("href", CODIGO);
$("marcador").addEventListener("click", e => {
  e.preventDefault();
  alert("No lo pulses aqui: arrastralo a la barra de marcadores y usalo en la pagina del token de Steam.");
});

$("pegar").addEventListener("click", async () => {
  $("estado").className = "";
  $("estado").textContent = "Leyendo el portapapeles...";
  let t = "";
  try {
    t = await Promise.race([
      navigator.clipboard.readText(),
      new Promise((_, rej) => setTimeout(() => rej(new Error("tarda demasiado")), 3000))
    ]);
  } catch (e) {
    $("estado").className = "error";
    $("estado").textContent = "El navegador no deja leer el portapapeles. Pega con Ctrl+V.";
    return;
  }
  if (!t || !t.trim()) { $("estado").textContent = "El portapapeles esta vacio."; return; }
  $("token").value = t.trim();
  $("token").type = "password";
  $("ver").textContent = "Mostrar";
  $("estado").className = "";
  $("estado").textContent = "Token pegado. Pulsa Actualizar.";
});

function pintar(d) {
  $("resultado").hidden = false;
  $("tarjetas").innerHTML = `
    <div class="tarjeta"><b>${fmt(d.juegos)}</b><span>juegos</span></div>
    <div class="tarjeta"><b>${fmt(d.prestados)}</b><span>prestados</span></div>
    <div class="tarjeta"><b>${fmt(d.jugables)}</b><span>jugables ahora</span></div>
    <div class="tarjeta"><b>${String(d.horas).replace(".", ",")}</b><span>horas en prestados</span></div>`;

  const ev = d.novedades || [];
  if (!d.primera && ev.length) {
    const filas = ev.slice(0, 40).map(e => {
      const etiqueta = e.evento === "nuevo" ? "nuevo" : (e.evento === "fuera" ? "fuera" : "otro dueño");
      const clase = e.evento === "nuevo" ? "si" : "no";
      return `<tr><td>${e.nombre}</td><td class="${clase}">${etiqueta}</td><td class="quien">${e.quien || "tú"}</td></tr>`;
    }).join("");
    $("novedades").innerHTML = `
      <p style="margin:14px 0 0;color:var(--suave);font-size:13px">Novedades del ${d.fecha_novedades}</p>
      <table><thead><tr><th>Juego</th><th>Qué</th><th>Quién</th></tr></thead><tbody>${filas}</tbody></table>`;
  } else if (d.primera) {
    $("novedades").innerHTML = `<p style="margin:14px 0 0;color:var(--suave)">Primera ejecución: guardado el retrato inicial. A partir de la próxima sabrás qué entra y qué sale.</p>`;
  } else {
    $("novedades").innerHTML = `<p style="margin:14px 0 0;color:var(--suave)">Sin cambios desde la última vez.</p>`;
  }
}

async function cargar() {
  try {
    const r = await fetch("/api/estado");
    const d = await r.json();
    if (d && d.juegos) pintar(d);
  } catch (e) {}
}

async function lanzar(auto) {
  const token = $("token").value.trim();
  if (!token) { $("estado").textContent = "Pega antes el token."; return; }
  $("lanzar").disabled = true;
  $("estado").className = "";
  $("estado").textContent = auto
    ? "Token guardado en este equipo. Actualizando..."
    : "Consultando Steam. La primera vez tarda unos segundos mas porque busca los nombres de los miembros...";
  try {
    const r = await fetch("/api/actualizar", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token, api_key: $("apikey").value.trim(), guardar: $("recordar").checked})
    });
    const d = await r.json();
    if (!d.ok) {
      $("estado").className = "error";
      $("estado").textContent = d.error || "No se pudo actualizar.";
      return;
    }
    if (!$("recordar").checked) $("token").value = "";
    $("estado").textContent = d.caduca
      ? "Listo. Token " + ($("recordar").checked ? "guardado, caduca el " : "válido hasta el ") + d.caduca + "."
      : "Listo.";
    pintar(d);
  } catch (e) {
    $("estado").className = "error";
    $("estado").textContent = "No hay conexion con la ventana de Steam Families. Suele pasar si esa ventana se ha cerrado: " +
      "cierra esta pestana, haz doble clic en actualizar.cmd y vuelve a pegar el token. (" + e.message + ")";
  } finally {
    $("lanzar").disabled = false;
  }
}
$("lanzar").addEventListener("click", () => lanzar(false));

$("olvidar").addEventListener("click", async e => {
  e.preventDefault();
  try { await fetch("/api/olvidar", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"}); } catch (x) {}
  $("token").value = "";
  $("estado").className = "";
  $("estado").textContent = "Token olvidado. En la proxima ejecucion tendras que pegarlo.";
});

async function arranque() {
  try {
    const r = await fetch("/api/token");
    const d = await r.json();
    if (d && d.token) {
      $("token").value = d.token;
      $("recordar").checked = true;
      await lanzar(true);
    }
  } catch (e) {}
  await cargar();
}
arranque();

$("detener").addEventListener("click", async e => {
  e.preventDefault();
  try { await fetch("/api/detener", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"}); } catch (x) {}
  document.body.innerHTML = '<main><h1>Interfaz detenida</h1><p class="sub">Puedes cerrar esta pestaña. Para volver a abrirla, doble clic en iniciar.cmd.</p></main>';
});
</script>
</body>
</html>
"""




def main(argv=None):
    p = argparse.ArgumentParser(
        description="Exporta la biblioteca familiar de Steam y detecta novedades.")
    p.add_argument("--datos", default=".", help="carpeta de datos (por defecto, la actual)")
    p.add_argument("--token", default="", help="webapi_token; si no, variable STEAM_WEBAPI_TOKEN")
    p.add_argument("--api-key", default="", help="API key opcional de Steam para los nombres")
    p.add_argument("--exportar", action="store_true", help="exporta sin abrir la interfaz")
    p.add_argument("--panel", action="store_true", help="solo regenera el panel")
    p.add_argument("--include-free", action="store_true", help="incluye free-to-play")
    p.add_argument("--include-non-games", action="store_true", help="incluye herramientas y demos")
    p.add_argument("--sin-nombres", action="store_true", help="no consulta los alias")
    p.add_argument("--sin-historial", action="store_true", help="no toca snapshot ni novedades")
    p.add_argument("--sin-precios", action="store_true", help="no consulta la tienda")
    p.add_argument("--puerto", type=int, default=8087, help="puerto de la interfaz")
    p.add_argument("--sin-navegador", action="store_true", help="no abre el navegador")
    args = p.parse_args(argv)

    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if args.panel:
        try:
            datos = carpeta(args.datos)
            resumen = generar_panel(datos)
        except SystemExit as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"panel con {resumen['juegos']} juegos y {resumen['prestados']} prestados")
        return 0

    token = normaliza_token(args.token or os.environ.get("STEAM_WEBAPI_TOKEN", ""))
    if args.exportar or token:
        if not token:
            print("error: falta el token para exportar. Usa --token o STEAM_WEBAPI_TOKEN.",
                  file=sys.stderr)
            return 1
        try:
            datos = carpeta(args.datos)
            resumen = exportar(datos, token, args.api_key, args.include_free,
                               args.include_non_games, not args.sin_nombres,
                               not args.sin_historial, not args.sin_precios)
            panel = generar_panel(datos)
        except SystemExit as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except OSError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"grupo {resumen['grupo']['nombre']} ({resumen['grupo']['miembros']} miembros)")
        print(f"{resumen['juegos']} juegos | {resumen['juegos'] - resumen['prestados']} tuyos | "
              f"{resumen['prestados']} prestados")
        if resumen["primera"]:
            print("primera ejecucion: guardado el retrato inicial, sin novedades")
        else:
            nuevos = sum(1 for e in resumen["eventos"] if e["evento"] == "nuevo")
            fuera = sum(1 for e in resumen["eventos"] if e["evento"] == "fuera")
            print(f"novedades: {nuevos} nuevos, {fuera} fuera")
        print(f"panel con {panel['juegos']} juegos")
        return 0

    return interfaz(args)


def interfaz(args):
    datos = carpeta_de_datos(args.datos)

    Handler.datos = datos
    servidor = None
    for puerto in range(args.puerto, args.puerto + 12):
        try:
            servidor = Servidor(("127.0.0.1", puerto), Handler)
            break
        except OSError:
            continue
    if servidor is None:
        print(f"No he encontrado un puerto libre entre {args.puerto} y {args.puerto + 11}. "
              "Cierra la otra ventana de Steam Families.", file=sys.stderr)
        return 1

    Handler.servidor = servidor
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Datos: {datos}")
    print(f"Interfaz: {url}")
    print("Cierra esta ventana (o pulsa Detener en la pagina) para terminar.")
    if not args.sin_navegador:
        def abrir():
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Timer(0.6, abrir).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"El servidor se ha parado: {e}", file=sys.stderr)
        return 1
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
