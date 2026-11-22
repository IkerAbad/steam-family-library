"""Steam falso para las pruebas: sin red y sin tocar la API real."""

import base64
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOMBRES = {"111": "Yo", "222": "Ana", "333": "Luis"}

APPS = [
    {"appid": 10, "name": "Mio", "owner_steamids": ["111"], "exclude_reason": 0,
     "rt_playtime": 60, "rt_time_acquired": 1700000000, "rt_last_played": 1700000000},
    {"appid": 20, "name": "Prestado", "owner_steamids": ["222"], "exclude_reason": 1,
     "rt_playtime": 30, "rt_time_acquired": 1700000000, "rt_last_played": 0},
    {"appid": 30, "name": "De otro", "owner_steamids": ["333"], "exclude_reason": 0,
     "rt_playtime": 0, "rt_time_acquired": 0, "rt_last_played": 0},
]


class SteamFalso(BaseHTTPRequestHandler):
    fallos = {}
    caida = 0
    sin_grupo = False
    sin_apps = False
    llamadas = []

    def log_message(self, *args):
        pass

    def _enviar(self, cuerpo, codigo=200, tipo="application/json"):
        datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo + "; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _json(self, datos, codigo=200):
        self._enviar(json.dumps(datos), codigo)

    def do_GET(self):
        partes = urllib.parse.urlparse(self.path)
        ruta = partes.path
        consulta = urllib.parse.parse_qs(partes.query)
        tipo = type(self)
        tipo.llamadas.append((ruta, consulta))

        if "GetFamilyGroupForUser" in ruta:
            if tipo.caida:
                self._enviar("<html><body>Unauthorized</body></html>", tipo.caida, "text/html")
                return
            if tipo.sin_grupo:
                self._json({"response": {"is_not_member_of_any_group": True}})
                return
            self._json({"response": {
                "family_groupid": "grupo1",
                "family_group": {"name": "Basados",
                                 "members": [{"steamid": "111"}, {"steamid": "222"}]},
            }})
            return

        if "GetSharedLibraryApps" in ruta:
            self._json({"response": {"apps": [] if tipo.sin_apps else APPS}})
            return

        if "GetPlayerSummaries" in ruta:
            ids = (consulta.get("steamids") or [""])[0].split(",")
            self._json({"response": {"players": [
                {"steamid": sid, "personaname": NOMBRES.get(sid, "?")} for sid in ids]}})
            return

        if "ajaxresolveusers" in ruta:
            sid = (consulta.get("steamids") or [""])[0]
            if tipo.fallos.get(sid, 0) > 0:
                tipo.fallos[sid] -= 1
                self._enviar("Too Many Requests", 429, "text/plain")
                return
            self._json([{"steamid": sid, "persona_name": NOMBRES.get(sid, "?")}])
            return

        if "appdetails" in ruta:
            appid = (consulta.get("appids") or [""])[0]
            self._json({appid: {"data": {"is_free": False}}})
            return

        self._enviar("no existe", 404, "text/plain")


def arranca():
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), SteamFalso)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    return servidor, hilo, f"http://127.0.0.1:{servidor.server_address[1]}"


def para(servidor, hilo):
    servidor.shutdown()
    servidor.server_close()
    hilo.join(timeout=5)


def token(sub="111", exp=2000000000):
    cabecera = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
    carga = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "sub": sub}).encode()).decode().rstrip("=")
    return cabecera + "." + carga + "." + "a" * 43
