#!/usr/bin/env python3
"""
Exporta tu biblioteca familiar de Steam y detecta novedades entre ejecuciones.

Steam fusiona tus juegos con los de tu familia y no ofrece ningún filtro para
separarlos. El endpoint publico IPlayerService/GetOwnedGames solo devuelve los
juegos que has comprado. Los compartidos viven en
IFamilyGroupsService/GetSharedLibraryApps, sin documentar, y necesita el
webapi_token de una sesion web.

Ademas de exportar, guarda un retrato de la biblioteca (snapshot.json) y lo
compara con el anterior: juegos nuevos, juegos que desaparecen y juegos que
pasa a tener otro miembro.

Requiere Python 3.8+. Sin dependencias.

    python steam_family_library.py --datos .
"""

import argparse
import base64
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

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
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


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


def main():
    p = argparse.ArgumentParser(description="Exporta la biblioteca familiar de Steam y detecta novedades.")
    p.add_argument("--datos", default=".", help="carpeta donde guardar los ficheros (por defecto, la actual)")
    p.add_argument("--token", default="", help="webapi_token (si no, variable STEAM_WEBAPI_TOKEN)")
    p.add_argument("--include-free", action="store_true", help="incluye free-to-play")
    p.add_argument("--include-non-games", action="store_true", help="incluye herramientas, bandas sonoras y demos")
    p.add_argument("--sin-nombres", action="store_true", help="no consulta los alias de los miembros")
    p.add_argument("--api-key", default="", help="opcional, API key de Steam (ver README): resuelve nombres sin limites")
    p.add_argument("--sin-historial", action="store_true", help="no toca historial.csv ni novedades")
    p.add_argument("--sin-precios", action="store_true", help="no consulta la tienda para marcar los juegos gratis")
    args = p.parse_args()

    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    token = (args.token or os.environ.get("STEAM_WEBAPI_TOKEN", "")).strip().strip("\"'")
    if not token:
        die("falta el token. Pasalo con --token o en la variable STEAM_WEBAPI_TOKEN")
    api_key = (args.api_key or os.environ.get("STEAM_API_KEY", "")).strip()

    datos = carpeta(args.datos)
    ruta_snap = datos / "snapshot.json"

    previo = {}
    if ruta_snap.exists():
        try:
            previo = json.loads(ruta_snap.read_text(encoding="utf-8"))
            if not isinstance(previo, dict) or "juegos" not in previo:
                raise ValueError("formato inesperado")
        except Exception:
            previo = {}
            try:
                ruta_snap.replace(datos / "snapshot.corrupto.json")
                print("aviso: el retrato anterior estaba roto; lo he guardado como snapshot.corrupto.json")
            except Exception:
                pass

    datos_nuevos = descargar(token, args.include_free, args.include_non_games, not args.sin_nombres, previo, api_key)
    try:
        escribir_csv(datos / "library.csv", datos_nuevos["csv"])
    except OSError as e:
        die(f"no puedo escribir library.csv en {datos}: {e}")

    juegos = datos_nuevos["juegos"]
    prestados = [g for g in juegos if not g["owners"] or datos_nuevos["yo"] not in g["owners"]]
    print(f"Grupo: {datos_nuevos['grupo']['nombre']} ({datos_nuevos['grupo']['miembros']} miembros)")
    print(f"{len(juegos)} juegos | {len(juegos) - len(prestados)} tuyos | {len(prestados)} prestados")

    eventos, ahora = [], datetime.now().strftime("%Y-%m-%d %H:%M")
    if not args.sin_historial:
        if previo:
            eventos = comparar(previo, datos_nuevos["snapshot"], datos_nuevos["yo"], datos_nuevos["alias"])
            if eventos and not args.sin_precios:
                for e in [x for x in eventos if x["evento"] == "nuevo"][:25]:
                    gratis = es_gratis(e["appid"])
                    if gratis is not None:
                        e["gratis"] = gratis
                    time.sleep(1.1)
        try:
            ruta_snap.write_text(json.dumps(datos_nuevos["snapshot"], ensure_ascii=False, indent=1), encoding="utf-8")
            (datos / "novedades.json").write_text(json.dumps({
                "fecha": ahora,
                "eventos": eventos,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            (datos / "novedades.txt").write_text(chivato(eventos, ahora), encoding="utf-8")
            anotar_historial(datos / "historial.csv", eventos, ahora)
        except OSError as e:
            die(f"no puedo escribir el historial en {datos}: {e}")

        if not previo:
            print("primera ejecucion: guardado el retrato inicial, sin novedades")
        else:
            print(f"novedades: {len([e for e in eventos if e['evento'] == 'nuevo'])} nuevos, "
                  f"{len([e for e in eventos if e['evento'] == 'fuera'])} fuera")

    print(f"escrito {datos / 'library.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
