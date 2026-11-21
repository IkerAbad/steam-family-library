#!/usr/bin/env python3
"""
Steam Families: exporta tu biblioteca familiar y detecta lo que ha entrado.

Un solo archivo, sin dependencias. Hace tres cosas:

  python steam_families.py            abre la interfaz en el navegador
  python steam_families.py --exportar exporta sin interfaz (necesita token)
  python steam_families.py --panel    regenera el panel a partir del CSV

El token se pide una vez y se guarda cifrado con DPAPI; a partir de ahí la
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
    1: "excluido por el dueño",
    2: "no se puede compartir",
    3: "restringido por región o DRM",
}
COLUMNAS = [
    "appid", "name", "source", "playable", "exclude_reason",
    "playtime_minutes", "acquired", "last_played", "store_url",
]


_IDIOMA = threading.local()


def idioma(valor=None):
    """Idioma de la petición en curso: «es» por defecto, «en» si la interfaz está en inglés."""
    if valor is not None:
        _IDIOMA.valor = "en" if str(valor).lower().startswith("en") else "es"
    return getattr(_IDIOMA, "valor", "es")


def tr(es, en):
    """Devuelve el texto en el idioma de la petición en curso."""
    return en if idioma() == "en" else es


def die(msg):
    raise SystemExit(msg)


def carpeta(texto):
    """Valida y prepara la carpeta de datos. Falla con un mensaje útil, no con un traceback."""
    raros = sorted({c for c in texto if c in '"<>|*?'}) if os.name == "nt" else []
    if raros:
        die(tr(f"la ruta {texto} lleva caracteres no válidos ({', '.join(raros)}). "
               "Suele ser una comilla colada por la barra final de la ruta.",
               f"the path {texto} has invalid characters ({', '.join(raros)}). "
               "It is usually a quote swallowed by the trailing slash of the path."))
    try:
        p = Path(texto).expanduser().resolve()
        if p.exists() and not p.is_dir():
            die(tr(f"{p} existe y no es una carpeta", f"{p} exists and it is not a folder"))
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        die(tr(f"no puedo usar la carpeta {texto}: {e}", f"cannot use the folder {texto}: {e}"))
    return p


def api_get(metodo, params):
    url = f"{API}/{metodo}/?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp).get("response", {})
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode("utf-8", "replace")[:400]
        pista = tr("\nEl token caduca a las 24 h: saca uno nuevo.",
                   "\nThe token expires after 24 h: get a new one.") if e.code in (401, 403) else ""
        die(tr(f"{metodo} devolvió HTTP {e.code}\n{cuerpo}{pista}",
               f"{metodo} returned HTTP {e.code}\n{cuerpo}{pista}"))
    except urllib.error.URLError as e:
        die(tr(f"no se pudo conectar con la API de Steam: {e.reason}",
               f"could not connect to the Steam API: {e.reason}"))


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
        die(tr("el token no parece un JWT. Copia solo el valor de webapi_token, sin comillas",
               "that does not look like a JWT. Copy only the webapi_token value, without quotes"))
    try:
        relleno = partes[1] + "=" * (-len(partes[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(relleno))
    except Exception:
        die(tr("no se pudo leer el contenido del token", "could not read the token contents"))
    exp = claims.get("exp")
    if exp and datetime.now(tz=timezone.utc).timestamp() > exp:
        die(tr("ese token ya ha caducado. Recarga la página del token para tener uno nuevo",
               "that token has already expired. Reload the token page to get a new one"))
    sid = claims.get("sub")
    if not sid:
        die(tr("el token no lleva SteamID", "the token has no SteamID"))
    return str(sid)


def etiqueta(steamid):
    """Identificador estable sin exponer el SteamID: mismo número siempre, sin nombre."""
    return hashlib.sha256(steamid.encode()).hexdigest()[:10]


def nombres(steamids, previos=None, api_key=""):
    """Alias público de cada miembro. Sin API key: endpoint de la comunidad.

    `previos` va por etiqueta (hash), no por SteamID, para no guardar los IDs.
    429 significa que Steam ha frenado las peticiones: se devuelve lo que haya y
    se reintenta en la siguiente ejecución.
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
    # Uno por uno: Steam devuelve 429 si se piden varios SteamID en la misma llamada.
    for i, sid in enumerate(pendientes):
        if not sid:
            continue
        if i:
            time.sleep(1.1)
        try:
            url = "https://steamcommunity.com/actions/ajaxresolveusers?steamids=" + sid
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                for u in json.load(r):
                    if str(u.get("steamid", "")) == sid and u.get("persona_name"):
                        out[sid] = u["persona_name"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                break
        except Exception:
            continue

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
        die(tr("esta cuenta no está en ningún grupo familiar de Steam, así que no hay biblioteca compartida",
               "this account is not in a Steam family group, so there is no shared library"))

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
        die(tr("la API no devolvió ninguna app. Puede que el token sea de otra cuenta",
               "the API returned no apps. The token may belong to another account"))

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
        lineas.append("Sin cambios desde la última vez.")
    for e in eventos:
        extra = "  [gratis]" if e.get("gratis") else ""
        if e["evento"] == "nuevo":
            lineas.append(f"+ {e['nombre']}  (de {de(e)}){extra}")
        elif e["evento"] == "nuevo_dueno":
            lineas.append(f"= {e['nombre']}  (ahora también de {de(e)})")
        else:
            lineas.append(f"- {e['nombre']}  (ya no está; era de {de(e)})")
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
header { padding:22px 24px 6px; display:flex; align-items:flex-start; gap:14px; }
header .titulo { flex:1 1 auto; min-width:0; }
h1 { font-size:20px; margin:0 0 6px; font-weight:600; }
#stats { margin:0; color:var(--suave); font-size:13px; }
#stats b { color:var(--texto); font-weight:600; }
.idiomas { display:flex; border:1px solid var(--borde); border-radius:6px; overflow:hidden; flex:0 0 auto; }
.idiomas button { background:var(--panel); color:var(--suave); border:0; padding:5px 9px; font:inherit; font-size:12px; line-height:1; cursor:pointer; }
.idiomas button:hover { color:var(--texto); }
.idiomas button[aria-pressed="true"] { background:#22303c; color:var(--acento); }
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
  <div class="titulo">
    <h1 data-t="titulo">Biblioteca familiar de Steam</h1>
    <p id="stats"></p>
  </div>
  <div class="idiomas" role="group" aria-label="Idioma" data-ta="idioma">
    <button type="button" data-idioma="es" aria-pressed="true" title="Español">ES</button>
    <button type="button" data-idioma="en" aria-pressed="false" title="English">EN</button>
  </div>
</header>
<div class="aviso" id="aviso" hidden>
  <span id="avisoTexto"></span>
  <button id="verNuevos" type="button" data-t="verNuevos">Ver solo novedades</button>
</div>
<div class="controles">
  <input id="q" type="search" data-tp="buscar" placeholder="Buscar por nombre… (los acentos dan igual)" autocomplete="off">
  <select id="origen" aria-label="Origen" data-ta="origen">
    <option value="todo" data-t="todo">Todo</option>
    <option value="family" data-t="soloPrestados">Solo prestados</option>
    <option value="own" data-t="soloMios">Solo míos</option>
  </select>
  <select id="estado" aria-label="Estado" data-ta="estado">
    <option value="todo" data-t="cualquierEstado">Cualquier estado</option>
    <option value="jugable" data-t="jugables">Jugables ahora</option>
    <option value="bloqueado" data-t="bloqueados">Bloqueados</option>
    <option value="jugados" data-t="jugados">Ya jugados</option>
    <option value="sinestrenar" data-t="sinEstrenar">Sin estrenar</option>
  </select>
  <select id="orden" aria-label="Orden" data-ta="orden">
    <option value="anadido" data-t="ordenAnadido">Añadido (más reciente)</option>
    <option value="nombre" data-t="ordenNombre">Nombre A-Z</option>
    <option value="horas" data-t="ordenHoras">Más horas jugadas</option>
    <option value="reciente" data-t="ordenReciente">Última sesión</option>
    <option value="dueno" data-t="ordenDueno">Dueño A-Z</option>
  </select>
  <select id="antiguedad" aria-label="Fecha" data-ta="fecha">
    <option value="todo" data-t="cualquierFecha">Cualquier fecha</option>
    <option value="30" data-t="dias30">Añadidos en 30 días</option>
    <option value="90" data-t="dias90">Añadidos en 90 días</option>
    <option value="anio" data-t="esteAnio">Añadidos este año</option>
  </select>
  <label class="check"><input type="checkbox" id="soloNuevos"> <span data-t="soloNuevos">Solo novedades</span></label>
  <button type="button" id="presetCompras" class="atajo" data-t="preset">Compras de la familia (90 días)</button>
</div>
<div id="resumen"></div>
<table>
  <thead>
    <tr>
      <th data-t="juego">Juego</th>
      <th data-t="dueno">Dueño</th>
      <th data-t="origen">Origen</th>
      <th data-t="estado">Estado</th>
      <th class="der" data-t="tusHoras">Tus horas</th>
      <th class="der" data-t="ultimaSesion">Última sesión</th>
      <th class="der" data-t="anadido">Añadido</th>
    </tr>
  </thead>
  <tbody id="cuerpo"></tbody>
</table>
<div id="vacio" hidden data-t="vacio">Ningún juego cumple esos filtros.</div>

<script>
const DATOS = __DATOS__;
const FECHA_NOV = __FECHA_NOV__;
const HAY_NOV = __HAY_NOV__;

const TEXTOS = {
  es: {
    titulo: "Biblioteca familiar de Steam",
    buscar: "Buscar por nombre… (los acentos dan igual)",
    todo: "Todo",
    soloPrestados: "Solo prestados",
    soloMios: "Solo míos",
    cualquierEstado: "Cualquier estado",
    jugables: "Jugables ahora",
    bloqueados: "Bloqueados",
    jugados: "Ya jugados",
    sinEstrenar: "Sin estrenar",
    ordenAnadido: "Añadido (más reciente)",
    ordenNombre: "Nombre A-Z",
    ordenHoras: "Más horas jugadas",
    ordenReciente: "Última sesión",
    ordenDueno: "Dueño A-Z",
    cualquierFecha: "Cualquier fecha",
    dias30: "Añadidos en 30 días",
    dias90: "Añadidos en 90 días",
    esteAnio: "Añadidos este año",
    soloNuevos: "Solo novedades",
    verNuevos: "Ver solo novedades",
    preset: "Compras de la familia (90 días)",
    juego: "Juego",
    dueno: "Dueño",
    origen: "Origen",
    estado: "Estado",
    tusHoras: "Tus horas",
    ultimaSesion: "Última sesión",
    anadido: "Añadido",
    vacio: "Ningún juego cumple esos filtros.",
    juegos: "juegos",
    prestados: "prestados",
    jugablesAhora: "jugables ahora",
    yaJugados: "ya jugados de ellos",
    horasPrestados: "h acumuladas en prestados",
    anadidosAnio: "añadidos este año",
    resumenNovedades: "Novedades desde la última vez",
    juegosNuevos: "juegos nuevos",
    yaNoEstan: "que ya no están",
    marcaPrestado: "prestado",
    marcaTuyo: "tuyo",
    nuevo: "nuevo",
    gratis: "gratis",
    fuera: "fuera",
    masDueno: "+ dueño",
    jugable: "jugable",
    bloqueado: "bloqueado",
    tu: "tú",
    de: "de",
    tipEntro: "Entró después del ",
    tipGratis: "La ficha de Steam lo marca como free-to-play",
    tipAdquirido: "Fecha en la que Steam dice que se adquirió",
    idioma: "Idioma",
    orden: "Orden",
    fecha: "Fecha"
  },
  en: {
    titulo: "Steam family library",
    buscar: "Search by name… (accents don't matter)",
    todo: "All",
    soloPrestados: "Shared with me",
    soloMios: "Only mine",
    cualquierEstado: "Any status",
    jugables: "Playable now",
    bloqueados: "Locked",
    jugados: "Already played",
    sinEstrenar: "Never played",
    ordenAnadido: "Recently added",
    ordenNombre: "Name A-Z",
    ordenHoras: "Most hours played",
    ordenReciente: "Last session",
    ordenDueno: "Owner A-Z",
    cualquierFecha: "Any date",
    dias30: "Added in 30 days",
    dias90: "Added in 90 days",
    esteAnio: "Added this year",
    soloNuevos: "Only new",
    verNuevos: "Show only new",
    preset: "Family purchases (90 days)",
    juego: "Game",
    dueno: "Owner",
    origen: "Source",
    estado: "Status",
    tusHoras: "Your hours",
    ultimaSesion: "Last session",
    anadido: "Added",
    vacio: "No game matches those filters.",
    juegos: "games",
    prestados: "shared with you",
    jugablesAhora: "playable now",
    yaJugados: "of them played",
    horasPrestados: "h played in shared games",
    anadidosAnio: "added this year",
    resumenNovedades: "Changes since last run",
    juegosNuevos: "new games",
    yaNoEstan: "gone",
    marcaPrestado: "shared",
    marcaTuyo: "yours",
    nuevo: "new",
    gratis: "free",
    fuera: "gone",
    masDueno: "+ owner",
    jugable: "playable",
    bloqueado: "locked",
    tu: "you",
    de: "of",
    tipEntro: "Added after ",
    tipGratis: "Steam lists it as free-to-play",
    tipAdquirido: "Date Steam reports it was acquired",
    idioma: "Language",
    orden: "Sort by",
    fecha: "Date"
  }
};

function idiomaInicial() {
  try {
    const guardado = localStorage.getItem("sf-idioma");
    if (guardado === "es" || guardado === "en") return guardado;
  } catch (e) {}
  const navegador = (navigator.language || "es").toLowerCase();
  return navegador.startsWith("es") ? "es" : "en";
}
let IDIOMA = idiomaInicial();
const T = clave => (TEXTOS[IDIOMA] && TEXTOS[IDIOMA][clave]) || TEXTOS.es[clave] || clave;
const LOCALE = () => IDIOMA === "es" ? "es-ES" : "en-GB";
const num = opciones => new Intl.NumberFormat(LOCALE(), opciones || {});
const numero = n => num().format(n);
const horas = m => num({minimumFractionDigits: 1, maximumFractionDigits: 1}).format(m / 60);
const fecha = u => u ? u.split("-").reverse().join("/") : "";

const plano = s => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
DATOS.forEach(d => { d.b = plano(d.n); });

const MOTIVOS = {
  "excluido por el dueno": {es: "excluido por el dueño", en: "excluded by the owner"},
  "no se puede compartir": {es: "no se puede compartir", en: "can't be shared"},
  "restringido por region o drm": {es: "restringido por región o DRM", en: "region or DRM restricted"}
};
function motivo(texto) {
  const clave = plano(texto || "");
  if (MOTIVOS[clave]) return MOTIVOS[clave][IDIOMA];
  const desconocido = /^desconocido \((\d+)\)$/.exec(clave);
  if (desconocido) return IDIOMA === "es" ? "desconocido (" + desconocido[1] + ")" : "unknown (" + desconocido[1] + ")";
  return texto || T("bloqueado");
}

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

function pintaStats() {
  $("stats").innerHTML = [
    "<b>" + numero(totales.juegos) + "</b> " + T("juegos"),
    "<b>" + numero(totales.prestados) + "</b> " + T("prestados"),
    "<b>" + numero(totales.jugables) + "</b> " + T("jugablesAhora"),
    "<b>" + numero(totales.jugados) + "</b> " + T("yaJugados"),
    "<b>" + horas(totales.horas) + "</b> " + T("horasPrestados"),
    "<b>" + numero(recientesAnio) + "</b> " + T("anadidosAnio")
  ].join(" &middot; ");
}

function pintaAviso() {
  if (!HAY_NOV) { $("aviso").hidden = true; return; }
  const nuevos = DATOS.filter(d => d.w === "nuevo").length;
  const fuera = DATOS.filter(d => d.w === "fuera").length;
  $("aviso").hidden = false;
  $("avisoTexto").textContent = T("resumenNovedades") + " (" + FECHA_NOV + "): " +
    nuevos + " " + T("juegosNuevos") + ", " + fuera + " " + T("yaNoEstan") + ".";
}

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

  const compara = (a, b) => a.localeCompare(b, IDIOMA);
  if (orden === "anadido") lista.sort((a, b) => (b.q || "").localeCompare(a.q || "") || compara(a.n, b.n));
  else if (orden === "horas") lista.sort((a, b) => b.m - a.m || compara(a.n, b.n));
  else if (orden === "reciente") lista.sort((a, b) => (b.u || "").localeCompare(a.u || "") || compara(a.n, b.n));
  else if (orden === "dueno") lista.sort((a, b) => compara(a.d || "zz", b.d || "zz") || compara(a.n, b.n));
  else lista.sort((a, b) => compara(a.n, b.n));

  $("resumen").textContent = numero(lista.length) + " " + T("de") + " " + numero(DATOS.length) + " " + T("juegos");
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
      b.textContent = T("nuevo");
      b.title = T("tipEntro") + d.wf;
      cont.appendChild(b);
      if (d.g) {
        const g = document.createElement("span");
        g.className = "marca dim";
        g.textContent = T("gratis");
        g.title = T("tipGratis");
        cont.appendChild(g);
      }
    } else if (d.w === "fuera") {
      const b = document.createElement("span");
      b.className = "marca fuera";
      b.textContent = T("fuera");
      cont.appendChild(b);
    } else if (d.w === "nuevo_dueno") {
      const b = document.createElement("span");
      b.className = "marca nuevo";
      b.textContent = T("masDueno");
      cont.appendChild(b);
    }
    td1.appendChild(cont);

    const td2 = document.createElement("td");
    td2.className = "dim";
    const miembro = /^Miembro (\d+)$/.exec(d.d || "");
    const quien = (d.d === "tú" || d.d === "tu") ? T("tu")
      : (miembro && IDIOMA === "en") ? "Member " + miembro[1] : d.d;
    td2.textContent = quien || "";
    td2.title = quien || "";

    const td3 = document.createElement("td");
    const m3 = document.createElement("span");
    m3.className = "marca " + (d.s === "family" ? "prestado" : "propio");
    m3.textContent = d.s === "family" ? T("marcaPrestado") : T("marcaTuyo");
    td3.appendChild(m3);

    const td4 = document.createElement("td");
    if (!d.p) {
      const m4 = document.createElement("span");
      m4.className = "marca bloqueado";
      m4.textContent = motivo(d.e);
      m4.title = m4.textContent;
      td4.appendChild(m4);
    } else {
      const sp = document.createElement("span");
      sp.className = "dim";
      sp.textContent = T("jugable");
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
    td7.title = T("tipAdquirido");

    tr.append(td1, td2, td3, td4, td5, td6, td7);
    frag.appendChild(tr);
  }
  cuerpo.replaceChildren(frag);
}

function aplicaIdioma() {
  document.documentElement.lang = IDIOMA;
  document.title = T("titulo");
  document.querySelectorAll("[data-t]").forEach(el => { el.textContent = T(el.dataset.t); });
  document.querySelectorAll("[data-tp]").forEach(el => { el.placeholder = T(el.dataset.tp); });
  document.querySelectorAll("[data-ta]").forEach(el => { el.setAttribute("aria-label", T(el.dataset.ta)); });
  document.querySelectorAll("[data-idioma]").forEach(b => {
    b.setAttribute("aria-pressed", String(b.dataset.idioma === IDIOMA));
  });
  pintaStats();
  pintaAviso();
  pinta();
}

document.querySelectorAll("[data-idioma]").forEach(b => b.addEventListener("click", () => {
  IDIOMA = b.dataset.idioma;
  try { localStorage.setItem("sf-idioma", IDIOMA); } catch (e) {}
  aplicaIdioma();
}));

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
aplicaIdioma();
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
        die(tr(f"no puedo escribir library.csv en {datos}: {e}",
               f"cannot write library.csv in {datos}: {e}"))

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
            die(tr(f"no puedo escribir el historial en {datos}: {e}",
                   f"cannot write the history in {datos}: {e}"))

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
        die(tr(f"no encuentro {csv_path}. Ejecuta antes la exportación",
               f"cannot find {csv_path}. Run the export first"))

    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f))
    except OSError as e:
        die(tr(f"no puedo leer {csv_path}: {e}", f"cannot read {csv_path}: {e}"))
    except UnicodeDecodeError:
        die(tr(f"{csv_path} no parece un CSV en UTF-8. Bórralo y vuelve a exportar.",
               f"{csv_path} does not look like a UTF-8 CSV. Delete it and export again."))
    if not filas:
        die(tr(f"{csv_path} está vacío. Vuelve a exportar.",
               f"{csv_path} is empty. Export again."))
    for obligatoria in ("appid", "name", "source"):
        if obligatoria not in filas[0]:
            die(tr(f"{csv_path} no tiene la columna {obligatoria}. Vuelve a exportar.",
                   f"{csv_path} has no {obligatoria} column. Export again."))

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
        die(tr(f"no puedo escribir los ficheros de prestados en {datos}: {e}",
               f"cannot write the shared files in {datos}: {e}"))

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
    """Lo que hace el botón Actualizar: todo en el mismo proceso."""
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


def _guardar_secreto(ruta, texto):
    """Windows: cifrado con DPAPI. Linux y macOS: fichero con permisos 600."""
    if ruta is None:
        return False
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            ruta.write_bytes(_proteger(texto.encode("utf-8")))
        else:
            ruta.write_text(texto, encoding="utf-8")
            os.chmod(ruta, 0o600)
        return True
    except Exception:
        return False


def _leer_secreto(ruta):
    if ruta is None or not ruta.exists():
        return None
    try:
        if os.name == "nt":
            return _desproteger(ruta.read_bytes()).decode("utf-8").strip()
        return ruta.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _olvidar_secreto(ruta):
    try:
        if ruta and ruta.exists():
            ruta.unlink()
    except OSError:
        pass


def guardar_token(token):
    """Windows: cifrado con DPAPI. Linux y macOS: fichero con permisos 600."""
    return _guardar_secreto(ruta_token(), token)


def leer_token():
    token = _leer_secreto(ruta_token())
    if not token or token_caducado(token):
        olvidar_token()
        return None
    return token


def olvidar_token():
    _olvidar_secreto(ruta_token())


def ruta_clave():
    """Misma carpeta que el token, fichero aparte."""
    ruta = ruta_token()
    return None if ruta is None else ruta.with_name("apikey.bin")


def guardar_clave(clave):
    return _guardar_secreto(ruta_clave(), clave)


def leer_clave():
    return _leer_secreto(ruta_clave())


def olvidar_clave():
    _olvidar_secreto(ruta_clave())


def carpeta_de_datos(texto):
    """Comprueba la ruta antes de tocar nada y explica el problema en castellano."""
    texto = (texto or "").strip()
    if not texto:
        raise SystemExit("la carpeta de datos está vacía. Pasa --datos <ruta>.")
    raros = sorted({c for c in texto if c in PROHIBIDOS}) if os.name == "nt" else []
    if raros:
        raise SystemExit(
            f"la ruta de datos lleva caracteres no válidos: {texto}\n"
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
    nombres = snap.get("nombres", {}) or {}
    return {
        "ok": True,
        "primera": not bool(juegos),
        "grupo": snap.get("grupo", ""),
        "juegos": len(juegos),
        "prestados": prestados,
        "jugables": jugables,
        "horas": round(horas / 60, 1),
        "nombres": nombres,
        "sin_nombre": sum(1 for v in nombres.values() if str(v).startswith("Miembro ")),
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
            self._enviar(500, {"ok": False,
                               "error": tr(f"Fallo interno: {type(e).__name__}: {e}",
                                          f"Internal error: {type(e).__name__}: {e}")})
        except Exception:
            pass

    def _origen_ok(self):
        """Solo acepta POST de la propia página: evita que otra web toque los datos."""
        origen = self.headers.get("Origin")
        if not origen:
            return True
        puerto = self.servidor.server_address[1]
        return origen in (f"http://127.0.0.1:{puerto}", f"http://localhost:{puerto}")

    def _get(self):
        consulta = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        idioma((consulta.get("lang") or [""])[0])
        pedida = urllib.parse.urlparse(self.path).path
        if pedida in ("/", "/index.html"):
            self._enviar(200, PAGINA, "text/html; charset=utf-8")
            return
        if pedida == "/api/estado":
            self._enviar(200, estado(self.datos))
            return
        if pedida == "/api/token":
            guardado = leer_token()
            self._enviar(200, {"ok": True, "token": guardado, "guardado": bool(guardado),
                               "caduca": caduca_token(guardado) if guardado else ""})
            return
        if pedida == "/api/clave":
            clave = leer_clave()
            self._enviar(200, {"ok": True, "clave": clave or "", "guardada": bool(clave)})
            return
        if pedida in FICHEROS:
            nombre, tipo = FICHEROS[pedida]
            ruta = self.datos / nombre
            if not ruta.exists():
                self._enviar(404, {"ok": False, "error": tr(f"todavía no existe {nombre}",
                                                            f"{nombre} does not exist yet")})
                return
            try:
                contenido = ruta.read_bytes()
            except OSError as e:
                self._enviar(500, {"ok": False, "error": tr(f"no puedo leer {nombre}: {e}",
                                                            f"cannot read {nombre}: {e}")})
                return
            self._enviar(200, contenido, tipo,
                         {"Content-Disposition": f'inline; filename="{nombre}"'})
            return
        self._enviar(404, {"ok": False, "error": tr("no existe", "not found")})

    def _post(self):
        if not self._origen_ok():
            self._enviar(403, {"ok": False, "error": tr("petición de otro sitio: solo vale desde esta página",
                                                        "request from another site: only this page is allowed")})
            return
        try:
            largo = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            largo = 0
        if largo > 100_000:
            self._enviar(413, {"ok": False, "error": tr("cuerpo demasiado grande", "body too large")})
            return
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except Exception:
            self._enviar(400, {"ok": False, "error": tr("JSON inválido", "invalid JSON")})
            return
        if not isinstance(cuerpo, dict):
            self._enviar(400, {"ok": False, "error": tr("esperaba un objeto JSON", "expected a JSON object")})
            return
        idioma(cuerpo.get("idioma"))

        if self.path == "/api/actualizar":
            token = str(cuerpo.get("token") or "").strip().strip("\"'")
            if not token:
                self._enviar(400, {"ok": False, "error": tr("falta el token", "the token is missing")})
                return
            if len(token) > 4000:
                self._enviar(400, {"ok": False, "error": tr("eso no es un token", "that is not a token")})
                return
            api_key = str(cuerpo.get("api_key") or "").strip()
            if api_key and (len(api_key) > 64 or not all(c.isalnum() for c in api_key)):
                self._enviar(400, {"ok": False, "error": tr(
                    "la API key no tiene buena pinta: son 32 caracteres en hexadecimal",
                    "the API key does not look right: it is 32 hexadecimal characters")})
                return
            if not api_key:
                api_key = leer_clave() or ""
            if not CANDADO.acquire(blocking=False):
                self._enviar(409, {"ok": False, "error": tr(
                    "Ya hay una actualización en curso. Espera a que termine.",
                    "An update is already running. Wait until it finishes.")})
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
                if api_key:
                    guardar_clave(api_key)
            else:
                olvidar_token()
                olvidar_clave()
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
            olvidar_clave()
            self._enviar(200, {"ok": True})
            return

        self._enviar(404, {"ok": False, "error": tr("no existe", "not found")})


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
.cabecera { display:flex; align-items:flex-start; gap:12px; }
.cabecera .texto { flex:1 1 auto; min-width:0; }
h1 { font-size:24px; margin:0 0 4px; }
.sub { color:var(--suave); margin:0 0 26px; }
.idiomas { display:flex; border:1px solid var(--borde); border-radius:6px; overflow:hidden; margin-top:4px; flex:0 0 auto; }
.idiomas button { background:#232a33; color:var(--suave); border:0; border-radius:0; padding:5px 9px; font-size:12px; line-height:1; font-family:inherit; cursor:pointer; }
.idiomas button:hover { background:#2b333d; color:var(--texto); }
.idiomas button[aria-pressed="true"] { background:#22303c; color:var(--acento); }
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
.nota { margin:10px 0 0; padding:9px 12px; border-radius:8px; background:#241f11; border:1px solid #5a4a22; color:#e0b341; font-size:13px; }
.nota a { color:#e0b341; }
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
  <div class="cabecera">
    <div class="texto">
      <h1>Steam Families</h1>
      <p class="sub" data-t="sub">Exporta tu biblioteca familiar, separa lo que te prestan y detecta qué ha entrado nuevo.</p>
    </div>
    <div class="idiomas" role="group" aria-label="Idioma" data-ta="idioma">
      <button type="button" data-idioma="es" aria-pressed="true" title="Español">ES</button>
      <button type="button" data-idioma="en" aria-pressed="false" title="English">EN</button>
    </div>
  </div>

  <section class="paso">
    <h2 data-t="paso1">Paso 1 · El token</h2>
    <p style="margin:0 0 10px" data-th="paso1Texto">
      Abre <a href="https://store.steampowered.com/pointssummary/ajaxgetasyncconfig" target="_blank" rel="noopener">esta página</a>
      con la sesión de Steam iniciada y copia el valor de <code>webapi_token</code>.
      Vale el token suelto o el JSON entero: el programa saca el token de donde esté.
    </p>
    <details>
      <summary data-t="porQue">¿Por qué hace falta y qué es?</summary>
      <ol>
        <li data-t="porQue1">Es un JWT de Steam que caduca en unas 24 horas.</li>
        <li data-t="porQue2">Solo sirve para leer tu biblioteca familiar.</li>
        <li data-t="porQue3">La página que abres es la oficial de Steam: devuelve un JSON y dentro está el token.</li>
      </ol>
    </details>
  </section>

  <section class="paso">
    <h2 data-t="paso2">Paso 2 · Pégalo aquí</h2>
    <div class="fila">
      <input id="token" type="password" data-tp="tokenPlaceholder" placeholder="Token, o el JSON entero de esa página" autocomplete="off" spellcheck="false">
      <button id="pegar" type="button" class="sec" data-t="pegar">Pegar</button>
      <button id="ver" type="button" class="sec" data-t="mostrar">Mostrar</button>
      <button id="lanzar" type="button" data-t="lanzar">Actualizar</button>
    </div>
    <details style="margin-top:12px">
      <summary data-t="copiarTitulo">Copiar el token en un solo clic</summary>
      <p style="color:var(--suave);font-size:13px;margin:8px 0">
        <span data-th="copiarTexto">Arrastra este botón a la barra de marcadores:</span>
        <a id="marcador" href="#" style="display:inline-block;padding:5px 10px;border:1px solid #2b5878;border-radius:6px;background:#22303c;text-decoration:none" data-t="copiarEnlace">Copiar token</a>
      </p>
      <p style="color:var(--suave);font-size:13px;margin:8px 0" data-th="copiarPasos">
        Después, en la página del token de Steam, pulsa ese marcador: copia el token al portapapeles y te avisa.
        Vuelve aquí y pulsa <b>Pegar</b>.
      </p>
    </details>
    <details style="margin-top:8px">
      <summary data-t="guardaTitulo">Qué guarda y qué no</summary>
      <ul class="seguridad">
        <li data-th="guarda1"><b>Ninguna cookie.</b> El programa no lee, no pide y no guarda cookies de Steam.</li>
        <li data-th="guarda2">El token caduca en 24 h. En Windows se guarda cifrado con DPAPI en <code>%LOCALAPPDATA%\SteamFamilies\token.bin</code>; en Linux y macOS, con permisos 600 en <code>~/.local/share/steam-families/</code>.</li>
        <li data-t="guarda3">No se envía nada a ningún servidor propio: las únicas conexiones son a la API de Steam.</li>
        <li data-th="guarda4">Puedes borrarlo cuando quieras con <b>olvidar</b>.</li>
      </ul>
    </details>
    <details style="margin-top:8px">
      <summary data-t="duenosTitulo">¿Los dueños salen como «Miembro 1»?</summary>
      <p style="color:var(--suave);font-size:13px;margin:8px 0" data-th="duenosTexto">
        Steam limita las consultas de nombres cuando se piden muchas seguidas. Con una
        <a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener">API key gratuita</a>
        salen siempre. Solo se usa durante esta consulta y no se guarda.
      </p>
      <input id="apikey" type="text" data-tp="apiKeyPlaceholder" placeholder="API key de Steam (opcional)" autocomplete="off" spellcheck="false" style="width:100%">
    </details>
    <div id="estado"></div>
    <label class="check" style="margin-top:10px">
      <input type="checkbox" id="recordar" checked>
      <span data-t="recordar">Recordar el token y la API key en este equipo, cifrados</span>
      <a href="#" id="olvidar" style="margin-left:10px" data-t="olvidar">olvidar</a>
    </label>
  </section>

  <section class="paso" id="resultado" hidden>
    <h2 data-t="resultado">Resultado</h2>
    <div class="tarjetas" id="tarjetas"></div>
    <div id="avisoNombres"></div>
    <div id="novedades"></div>
    <div class="fila" style="margin-top:14px">
      <button class="sec" onclick="window.open('/panel.html','_blank')" data-t="abrirPanel">Abrir panel</button>
      <button class="sec" onclick="window.open('/prestados.csv','_blank')" data-t="abrirCsv">Abrir CSV de prestados</button>
      <button class="sec" onclick="window.open('/novedades.txt','_blank')" data-t="abrirNovedades">Abrir novedades</button>
      <button class="sec" onclick="window.open('/historial.csv','_blank')" data-t="historial">Historial</button>
    </div>
  </section>

  <p class="pie">
    <span data-th="pie">Todo se ejecuta en tu ordenador y no se guarda ninguna cookie de Steam. Si marcas «recordar», el token queda guardado solo para tu usuario: cifrado con DPAPI en Windows, permisos 600 en Linux y macOS.</span>
    <a href="#" id="detener" data-t="detener">Detener la interfaz</a>
  </p>
</main>

<script>
const TEXTOS = {
  es: {
    sub: "Exporta tu biblioteca familiar, separa lo que te prestan y detecta qué ha entrado nuevo.",
    paso1: "Paso 1 · El token",
    paso1Texto: 'Abre <a href="https://store.steampowered.com/pointssummary/ajaxgetasyncconfig" target="_blank" rel="noopener">esta página</a> con la sesión de Steam iniciada y copia el valor de <code>webapi_token</code>. Vale el token suelto o el JSON entero: el programa saca el token de donde esté.',
    porQue: "¿Por qué hace falta y qué es?",
    porQue1: "Es un JWT de Steam que caduca en unas 24 horas.",
    porQue2: "Solo sirve para leer tu biblioteca familiar.",
    porQue3: "La página que abres es la oficial de Steam: devuelve un JSON y dentro está el token.",
    paso2: "Paso 2 · Pégalo aquí",
    tokenPlaceholder: "Token, o el JSON entero de esa página",
    pegar: "Pegar",
    mostrar: "Mostrar",
    ocultar: "Ocultar",
    lanzar: "Actualizar",
    copiarTitulo: "Copiar el token en un solo clic",
    copiarTexto: "Arrastra este botón a la barra de marcadores:",
    copiarEnlace: "Copiar token",
    copiarPasos: 'Después, en la página del token de Steam, pulsa ese marcador: copia el token al portapapeles y te avisa. Vuelve aquí y pulsa <b>Pegar</b>.',
    guardaTitulo: "Qué guarda y qué no",
    guarda1: "<b>Ninguna cookie.</b> El programa no lee, no pide y no guarda cookies de Steam.",
    guarda2: 'El token caduca en 24 h. En Windows se guarda cifrado con DPAPI en <code>%LOCALAPPDATA%\\SteamFamilies\\token.bin</code>; en Linux y macOS, con permisos 600 en <code>~/.local/share/steam-families/</code>.',
    guarda3: "No se envía nada a ningún servidor propio: las únicas conexiones son a la API de Steam.",
    guarda4: "Puedes borrarlo cuando quieras con <b>olvidar</b>.",
    duenosTitulo: "¿Los dueños salen como «Miembro 1»?",
    duenosTexto: 'Steam limita las consultas de nombres cuando se piden muchas seguidas. Con una <a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener">API key gratuita</a> salen siempre. Solo se usa durante esta consulta y no se guarda.',
    apiKeyPlaceholder: "API key de Steam (opcional)",
    recordar: "Recordar el token y la API key en este equipo, cifrados",
    olvidar: "olvidar",
    sinNombreAviso: "Hay %n% miembros sin nombre. Pega una API key gratuita y vuelve a actualizar:",
    sinNombreUno: "Hay 1 miembro sin nombre. Pega una API key gratuita y vuelve a actualizar:",
    pedirClave: "consíguela aquí",
    resultado: "Resultado",
    abrirPanel: "Abrir panel",
    abrirCsv: "Abrir CSV de prestados",
    abrirNovedades: "Abrir novedades",
    historial: "Historial",
    pie: 'Todo se ejecuta en tu ordenador y no se guarda ninguna cookie de Steam. Si marcas «recordar», el token queda guardado solo para tu usuario: cifrado con DPAPI en Windows, permisos 600 en Linux y macOS.',
    detener: "Detener la interfaz",
    juegos: "juegos",
    prestados: "prestados",
    jugablesAhora: "jugables ahora",
    horasPrestados: "horas en prestados",
    nuevo: "nuevo",
    fuera: "fuera",
    otroDueno: "otro dueño",
    tu: "tú",
    que: "Qué",
    quien: "Quién",
    juego: "Juego",
    novedadesDel: "Novedades del",
    primera: "Primera ejecución: guardado el retrato inicial. A partir de la próxima sabrás qué entra y qué sale.",
    sinCambios: "Sin cambios desde la última vez.",
    leyendo: "Leyendo el portapapeles…",
    portapapelesNo: "El navegador no deja leer el portapapeles. Pega con Ctrl+V.",
    portapapelesVacio: "El portapapeles está vacío.",
    pegado: "Token pegado. Pulsa Actualizar.",
    faltaToken: "Pega antes el token.",
    guardadoActualizando: "Token guardado en este equipo. Actualizando…",
    consultando: "Consultando Steam. La primera vez tarda unos segundos más porque busca los nombres de los miembros…",
    listoGuardado: "Listo. Token guardado, caduca el",
    listoValido: "Listo. Token válido hasta el",
    listo: "Listo.",
    actualizarFallo: "No se pudo actualizar.",
    sinConexion: "No hay conexión con la ventana de Steam Families. Suele pasar si esa ventana se ha cerrado: cierra esta pestaña, haz doble clic en iniciar.cmd (o ejecuta iniciar.sh) y vuelve a pegar el token.",
    olvidado: "Token olvidado. En la próxima ejecución tendrás que pegarlo.",
    detenida: "Interfaz detenida",
    detenidaTexto: "Puedes cerrar esta pestaña. Para volver a abrirla, doble clic en iniciar.cmd.",
    sinSesion: "Primero inicia sesión en Steam.",
    copiado: "Token copiado. Vuelve a Steam Families y pulsa Pegar.",
    copiaManual: "Copia el token:",
    marcadorAviso: "No lo pulses aquí: arrástralo a la barra de marcadores y úsalo en la página del token de Steam.",
    idioma: "Idioma"
  },
  en: {
    sub: "Export your family library, split what is shared with you and spot what is new.",
    paso1: "Step 1 · The token",
    paso1Texto: 'Open <a href="https://store.steampowered.com/pointssummary/ajaxgetasyncconfig" target="_blank" rel="noopener">this page</a> with your Steam session signed in and copy the <code>webapi_token</code> value. The bare token or the whole JSON both work: the program finds the token either way.',
    porQue: "Why is it needed, and what is it?",
    porQue1: "It is a Steam JWT that expires after about 24 hours.",
    porQue2: "It is only used to read your family library.",
    porQue3: "The page you open is Steam's own: it returns a JSON document with the token inside.",
    paso2: "Step 2 · Paste it here",
    tokenPlaceholder: "Token, or the whole JSON from that page",
    pegar: "Paste",
    mostrar: "Show",
    ocultar: "Hide",
    lanzar: "Update",
    copiarTitulo: "Copy the token in one click",
    copiarTexto: "Drag this button to the bookmarks bar:",
    copiarEnlace: "Copy token",
    copiarPasos: 'Then, on Steam\'s token page, click that bookmark: it copies the token to the clipboard and tells you. Come back here and press <b>Paste</b>.',
    guardaTitulo: "What is stored and what is not",
    guarda1: "<b>No cookies.</b> The program does not read, ask for or store Steam cookies.",
    guarda2: 'The token expires in 24 h. On Windows it is stored encrypted with DPAPI in <code>%LOCALAPPDATA%\\SteamFamilies\\token.bin</code>; on Linux and macOS, with 600 permissions in <code>~/.local/share/steam-families/</code>.',
    guarda3: "Nothing is sent to any server of ours: the only connections are to Steam's API.",
    guarda4: "You can delete it whenever you want with <b>forget</b>.",
    duenosTitulo: "Owners show up as “Member 1”?",
    duenosTexto: 'Steam rate-limits name lookups when too many are requested in a row. With a <a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener">free API key</a> they always resolve. It is only used for this request and is not stored.',
    apiKeyPlaceholder: "Steam API key (optional)",
    recordar: "Remember the token and the API key on this computer, encrypted",
    olvidar: "forget",
    sinNombreAviso: "%n% members have no name yet. Paste a free API key and update again:",
    sinNombreUno: "1 member has no name yet. Paste a free API key and update again:",
    pedirClave: "get one here",
    resultado: "Result",
    abrirPanel: "Open panel",
    abrirCsv: "Open shared CSV",
    abrirNovedades: "Open changes",
    historial: "History",
    pie: 'Everything runs on your computer and no Steam cookie is stored. If you tick “remember”, the token is stored for your user only: encrypted with DPAPI on Windows, 600 permissions on Linux and macOS.',
    detener: "Stop the interface",
    juegos: "games",
    prestados: "shared with you",
    jugablesAhora: "playable now",
    horasPrestados: "hours in shared games",
    nuevo: "new",
    fuera: "gone",
    otroDueno: "new owner",
    tu: "you",
    que: "What",
    quien: "Who",
    juego: "Game",
    novedadesDel: "Changes from",
    primera: "First run: initial snapshot saved. From the next run you will see what comes in and what goes out.",
    sinCambios: "No changes since the last run.",
    leyendo: "Reading the clipboard…",
    portapapelesNo: "The browser will not let us read the clipboard. Paste with Ctrl+V.",
    portapapelesVacio: "The clipboard is empty.",
    pegado: "Token pasted. Press Update.",
    faltaToken: "Paste the token first.",
    guardadoActualizando: "Token loaded from this computer. Updating…",
    consultando: "Asking Steam. The first time takes a few seconds longer while it looks up member names…",
    listoGuardado: "Done. Token stored, expires on",
    listoValido: "Done. Token valid until",
    listo: "Done.",
    actualizarFallo: "Could not update.",
    sinConexion: "No connection to the Steam Families window. This usually means that window was closed: close this tab, double-click iniciar.cmd (or run iniciar.sh) and paste the token again.",
    olvidado: "Token forgotten. You will have to paste it again next time.",
    detenida: "Interface stopped",
    detenidaTexto: "You can close this tab. To open it again, double-click iniciar.cmd.",
    sinSesion: "Sign in to Steam first.",
    copiado: "Token copied. Go back to Steam Families and press Paste.",
    copiaManual: "Copy the token:",
    marcadorAviso: "Don't click it here: drag it to the bookmarks bar and use it on Steam's token page.",
    idioma: "Language"
  }
};

function idiomaInicial() {
  try {
    const guardado = localStorage.getItem("sf-idioma");
    if (guardado === "es" || guardado === "en") return guardado;
  } catch (e) {}
  const navegador = (navigator.language || "es").toLowerCase();
  return navegador.startsWith("es") ? "es" : "en";
}
let IDIOMA = idiomaInicial();
const T = clave => (TEXTOS[IDIOMA] && TEXTOS[IDIOMA][clave]) || TEXTOS.es[clave] || clave;
const LOCALE = () => IDIOMA === "es" ? "es-ES" : "en-GB";
const num = opciones => new Intl.NumberFormat(LOCALE(), opciones || {});
const fmt = n => num().format(n);
const fmtHoras = n => num({minimumFractionDigits: 1, maximumFractionDigits: 1}).format(n);

const $ = id => document.getElementById(id);
let ULTIMO = null;
let VISIBLE = false;
let ESTADO = {clave: "", extra: "", texto: "", error: false};

function pintaEstado() {
  const el = $("estado");
  el.className = ESTADO.error ? "error" : "";
  el.textContent = ESTADO.clave ? T(ESTADO.clave) + (ESTADO.extra ? " " + ESTADO.extra : "") : ESTADO.texto;
}
function ponEstado(clave, extra) {
  ESTADO = {clave, extra: extra || "", texto: "", error: false};
  pintaEstado();
}
function ponError(texto) {
  ESTADO = {clave: "", extra: "", texto, error: true};
  pintaEstado();
}

function escapa(texto) {
  return texto.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, " ");
}

function construyeMarcador() {
  const codigo = 'javascript:(async()=>{' +
    'const r=await fetch("https://store.steampowered.com/pointssummary/ajaxgetasyncconfig",{credentials:"include"});' +
    'const j=await r.json();' +
    'let t=(j.data&&j.data.webapi_token)||j.webapi_token||"";' +
    't=t.replace(/^"|"$/g,"");' +
    'if(!t){alert("' + escapa(T("sinSesion")) + '");return;}' +
    'try{await navigator.clipboard.writeText(t);alert("' + escapa(T("copiado")) + '");}' +
    'catch(e){prompt("' + escapa(T("copiaManual")) + '",t);}' +
    '})();';
  $("marcador").setAttribute("href", codigo);
}

function aplicaIdioma() {
  document.documentElement.lang = IDIOMA;
  document.querySelectorAll("[data-t]").forEach(el => { el.textContent = T(el.dataset.t); });
  document.querySelectorAll("[data-th]").forEach(el => { el.innerHTML = T(el.dataset.th); });
  document.querySelectorAll("[data-tp]").forEach(el => { el.placeholder = T(el.dataset.tp); });
  document.querySelectorAll("[data-ta]").forEach(el => { el.setAttribute("aria-label", T(el.dataset.ta)); });
  document.querySelectorAll("[data-idioma]").forEach(b => {
    b.setAttribute("aria-pressed", String(b.dataset.idioma === IDIOMA));
  });
  $("ver").textContent = VISIBLE ? T("ocultar") : T("mostrar");
  construyeMarcador();
  pintaEstado();
  if (ULTIMO) pintar(ULTIMO);
}

document.querySelectorAll("[data-idioma]").forEach(b => b.addEventListener("click", () => {
  IDIOMA = b.dataset.idioma;
  try { localStorage.setItem("sf-idioma", IDIOMA); } catch (e) {}
  aplicaIdioma();
}));

$("ver").addEventListener("click", () => {
  const t = $("token");
  VISIBLE = !VISIBLE;
  t.type = VISIBLE ? "text" : "password";
  $("ver").textContent = VISIBLE ? T("ocultar") : T("mostrar");
});

$("marcador").addEventListener("click", e => {
  e.preventDefault();
  alert(T("marcadorAviso"));
});

$("pegar").addEventListener("click", async () => {
  ponEstado("leyendo");
  let t = "";
  try {
    t = await Promise.race([
      navigator.clipboard.readText(),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 3000))
    ]);
  } catch (e) {
    ponError(T("portapapelesNo"));
    return;
  }
  if (!t || !t.trim()) { ponEstado("portapapelesVacio"); return; }
  $("token").value = t.trim();
  $("token").type = "password";
  VISIBLE = false;
  $("ver").textContent = T("mostrar");
  ponEstado("pegado");
});

function pintar(d) {
  ULTIMO = d;
  $("resultado").hidden = false;
  $("tarjetas").innerHTML =
    '<div class="tarjeta"><b>' + fmt(d.juegos) + '</b><span>' + T("juegos") + '</span></div>' +
    '<div class="tarjeta"><b>' + fmt(d.prestados) + '</b><span>' + T("prestados") + '</span></div>' +
    '<div class="tarjeta"><b>' + fmt(d.jugables) + '</b><span>' + T("jugablesAhora") + '</span></div>' +
    '<div class="tarjeta"><b>' + fmtHoras(d.horas) + '</b><span>' + T("horasPrestados") + '</span></div>';

  const aviso = $("avisoNombres");
  if (d.sin_nombre) {
    const texto = d.sin_nombre === 1 ? T("sinNombreUno") : T("sinNombreAviso").replace("%n%", d.sin_nombre);
    aviso.innerHTML = '<p class="nota">' + texto + ' ' +
      '<a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener">' +
      T("pedirClave") + '</a></p>';
  } else {
    aviso.innerHTML = "";
  }

  const ev = d.novedades || [];
  if (!d.primera && ev.length) {
    const filas = ev.slice(0, 40).map(e => {
      const etiqueta = e.evento === "nuevo" ? T("nuevo") : (e.evento === "fuera" ? T("fuera") : T("otroDueno"));
      const clase = e.evento === "nuevo" ? "si" : "no";
      let quien = e.quien || T("tu");
      const miembro = /^Miembro (\d+)$/.exec(quien);
      if (miembro && IDIOMA === "en") quien = "Member " + miembro[1];
      return '<tr><td>' + e.nombre + '</td><td class="' + clase + '">' + etiqueta +
        '</td><td class="quien">' + quien + '</td></tr>';
    }).join("");
    $("novedades").innerHTML =
      '<p style="margin:14px 0 0;color:var(--suave);font-size:13px">' + T("novedadesDel") + " " + d.fecha_novedades + '</p>' +
      '<table><thead><tr><th>' + T("juego") + '</th><th>' + T("que") + '</th><th>' + T("quien") + '</th></tr></thead><tbody>' + filas + '</tbody></table>';
  } else if (d.primera) {
    $("novedades").innerHTML = '<p style="margin:14px 0 0;color:var(--suave)">' + T("primera") + '</p>';
  } else {
    $("novedades").innerHTML = '<p style="margin:14px 0 0;color:var(--suave)">' + T("sinCambios") + '</p>';
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
  if (!token) { ponEstado("faltaToken"); return; }
  $("lanzar").disabled = true;
  ponEstado(auto ? "guardadoActualizando" : "consultando");
  try {
    const r = await fetch("/api/actualizar", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token, api_key: $("apikey").value.trim(), guardar: $("recordar").checked, idioma: IDIOMA})
    });
    const d = await r.json();
    if (!d.ok) {
      ponError(d.error || T("actualizarFallo"));
      return;
    }
    if (!$("recordar").checked) $("token").value = "";
    if (d.caduca) {
      ponEstado($("recordar").checked ? "listoGuardado" : "listoValido", d.caduca + ".");
    } else {
      ponEstado("listo");
    }
    pintar(d);
  } catch (e) {
    ponError(T("sinConexion") + " (" + e.message + ")");
  } finally {
    $("lanzar").disabled = false;
  }
}
$("lanzar").addEventListener("click", () => lanzar(false));

$("olvidar").addEventListener("click", async e => {
  e.preventDefault();
  try { await fetch("/api/olvidar", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"}); } catch (x) {}
  $("token").value = "";
  ponEstado("olvidado");
});

async function cargaClave() {
  try {
    const r = await fetch("/api/clave");
    const d = await r.json();
    if (d && d.clave) $("apikey").value = d.clave;
  } catch (e) {}
}

async function arranque() {
  await cargaClave();
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

$("detener").addEventListener("click", async e => {
  e.preventDefault();
  try { await fetch("/api/detener", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({idioma: IDIOMA})}); } catch (x) {}
  document.body.innerHTML = '<main><h1>' + T("detenida") + '</h1><p class="sub">' + T("detenidaTexto") + '</p></main>';
});

aplicaIdioma();
arranque();
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
            print("primera ejecución: guardado el retrato inicial, sin novedades")
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
    print("Cierra esta ventana (o pulsa Detener en la página) para terminar.")
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
