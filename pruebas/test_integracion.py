"""Flujo completo contra un Steam falso: sin red y sin tocar la API real.

    python -m unittest discover -s pruebas -v
"""

import base64
import csv
import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import steam_families as sfl  # noqa: E402

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
            self._json({"response": {
                "family_groupid": "grupo1",
                "family_group": {"name": "Basados",
                                 "members": [{"steamid": "111"}, {"steamid": "222"}]},
            }})
            return

        if "GetSharedLibraryApps" in ruta:
            self._json({"response": {"apps": APPS}})
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


class PruebaIntegracion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), SteamFalso)
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()
        base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        cls.originales = (sfl.API, sfl.COMUNIDAD, sfl.TIENDA)
        sfl.API = base
        sfl.COMUNIDAD = base
        sfl.TIENDA = base

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.hilo.join(timeout=5)
        sfl.API, sfl.COMUNIDAD, sfl.TIENDA = cls.originales

    def setUp(self):
        SteamFalso.fallos = {}
        SteamFalso.caida = 0
        SteamFalso.llamadas = []
        self.dormir = sfl.time.sleep
        sfl.time.sleep = lambda segundos: None

    def tearDown(self):
        sfl.time.sleep = self.dormir

    def token(self):
        cabecera = base64.urlsafe_b64encode(b'{"alg":"HS256"}').decode().rstrip("=")
        carga = base64.urlsafe_b64encode(
            json.dumps({"exp": 2000000000, "sub": "111"}).encode()).decode().rstrip("=")
        return cabecera + "." + carga + "." + "a" * 43

    def nombres_pedidos(self):
        return [c.get("steamids", [""])[0] for r, c in SteamFalso.llamadas
                if "ajaxresolveusers" in r]

    def test_flujo_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            resumen = sfl.exportar(d, self.token(), con_precios=False)
            self.assertEqual(resumen["juegos"], 3)
            self.assertEqual(resumen["prestados"], 2)
            self.assertTrue(resumen["primera"])

            filas = list(csv.DictReader((d / "library.csv").open(encoding="utf-8-sig")))
            self.assertEqual(len(filas), 3)
            self.assertEqual({f["source"] for f in filas}, {"own", "family"})

            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(snap["nombres"].values()), ["Ana", "Luis", "tú"])
            self.assertEqual(snap["nombres_fecha"], datetime.now().strftime("%Y-%m-%d"))

            sfl.generar_panel(d)
            html = (d / "panel.html").read_text(encoding="utf-8")
            self.assertIn("Ana", html)
            self.assertIn("const SIN_NOMBRE = 0", html)
            self.assertIn("const ACTUALIZADO = ", html)

            e = sfl.estado(d)
            self.assertTrue(e["actualizado"])
            self.assertEqual(e["sin_nombre"], 0)

    def test_no_pide_nombres_si_son_recientes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            previo = {
                "nombres": {sfl.etiqueta("111"): "Yo", sfl.etiqueta("222"): "Ana",
                            sfl.etiqueta("333"): "Luis"},
                "nombres_fecha": datetime.now().strftime("%Y-%m-%d"),
                "juegos": {},
            }
            (d / "snapshot.json").write_text(json.dumps(previo), encoding="utf-8")
            sfl.exportar(d, self.token(), con_precios=False)
            self.assertEqual(self.nombres_pedidos(), [])

    def test_refresca_nombres_viejos(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            previo = {
                "nombres": {sfl.etiqueta("222"): "Nombre viejo"},
                "nombres_fecha": "2020-01-01",
                "juegos": {},
            }
            (d / "snapshot.json").write_text(json.dumps(previo), encoding="utf-8")
            sfl.exportar(d, self.token(), con_precios=False)
            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("Ana", snap["nombres"].values())
            self.assertNotIn("Nombre viejo", snap["nombres"].values())
            self.assertIn("222", self.nombres_pedidos())

    def test_reintenta_cuando_steam_frena(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            SteamFalso.fallos = {"222": 1}
            sfl.exportar(d, self.token(), con_precios=False)
            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("Ana", snap["nombres"].values())
            self.assertEqual(self.nombres_pedidos().count("222"), 2)

    def test_se_rinde_tras_tres_esperas(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            SteamFalso.fallos = {"222": 99}
            sfl.exportar(d, self.token(), con_precios=False)
            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("Miembro 1", snap["nombres"].values())
            self.assertEqual(self.nombres_pedidos().count("222"), 4)

            sfl.generar_panel(d)
            html = (d / "panel.html").read_text(encoding="utf-8")
            self.assertIn("const SIN_NOMBRE = 1", html)

    def test_token_rechazado(self):
        with tempfile.TemporaryDirectory() as tmp:
            SteamFalso.caida = 401
            with self.assertRaises(SystemExit) as error:
                sfl.exportar(pathlib.Path(tmp), self.token(), con_precios=False)
            self.assertIn("rechazado", str(error.exception))

    def test_sin_nombres_conserva_los_guardados(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text(json.dumps({
                "nombres": {sfl.etiqueta("222"): "Ana"},
                "nombres_fecha": "2026-01-01",
                "juegos": {},
            }), encoding="utf-8")
            sfl.exportar(d, self.token(), con_nombres=False, con_precios=False)
            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snap["nombres"].get(sfl.etiqueta("222")), "Ana")
            self.assertEqual(snap["nombres_fecha"], "2026-01-01")


if __name__ == "__main__":
    unittest.main()
