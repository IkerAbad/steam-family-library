"""Pruebas de los endpoints de la interfaz, en local y sin red externa."""

import base64
import csv
import http.client
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import steam_families as sfl  # noqa: E402

COLUMNAS = ["appid", "name", "source", "playable", "exclude_reason",
            "playtime_minutes", "acquired", "last_played", "store_url"]


def escribe_datos(d):
    filas = [
        {"appid": "10", "name": "Mio", "source": "own", "playable": "True",
         "exclude_reason": "", "playtime_minutes": "60", "acquired": "2026-01-01",
         "last_played": "", "store_url": "u"},
        {"appid": "20", "name": "Prestado", "source": "family", "playable": "True",
         "exclude_reason": "", "playtime_minutes": "30", "acquired": "2026-02-02",
         "last_played": "", "store_url": "u"},
    ]
    with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(filas)

    snap = {"yo": "aaa", "juegos": {"10": {"o": ["aaa"], "p": True},
                                    "20": {"o": ["bbb"], "p": True}}}
    (d / "snapshot.json").write_text(json.dumps(snap), encoding="utf-8")


class PruebaHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.datos = pathlib.Path(cls.tmp.name)
        escribe_datos(cls.datos)

        # ruta de token aislada: no toca la del usuario
        cls.ruta_original = sfl.ruta_token
        sfl.ruta_token = lambda: cls.datos / "token.bin"

        sfl.Handler.datos = cls.datos
        cls.servidor = sfl.Servidor(("127.0.0.1", 0), sfl.Handler)
        sfl.Handler.servidor = cls.servidor
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.hilo.join(timeout=5)
        sfl.Handler.datos = pathlib.Path(".")
        sfl.ruta_token = cls.ruta_original
        cls.tmp.cleanup()

    def get(self, ruta):
        try:
            with urllib.request.urlopen(self.base + ruta, timeout=5) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def post(self, ruta, cuerpo, origin=None):
        req = urllib.request.Request(
            self.base + ruta, data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"})
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def test_pagina(self):
        codigo, cuerpo = self.get("/")
        self.assertEqual(codigo, 200)
        self.assertIn("Steam Families", cuerpo)
        self.assertIn("v" + sfl.VERSION, cuerpo)

    def test_estado(self):
        codigo, cuerpo = self.get("/api/estado")
        self.assertEqual(codigo, 200)
        datos = json.loads(cuerpo)
        self.assertEqual(datos["juegos"], 2)
        self.assertEqual(datos["prestados"], 1)

    def test_token_sin_guardar(self):
        codigo, cuerpo = self.get("/api/token")
        self.assertEqual(codigo, 200)
        datos = json.loads(cuerpo)
        self.assertFalse(datos["guardado"])
        self.assertNotIn("token", datos)

    def test_token_guardado_no_se_devuelve(self):
        carga = base64.urlsafe_b64encode(
            json.dumps({"exp": 2000000000, "sub": "1"}).encode()).decode().rstrip("=")
        tok = "x." + carga + "." + "a" * 43
        sfl.guardar_token(tok)
        try:
            datos = json.loads(self.get("/api/token")[1])
            self.assertTrue(datos["guardado"])
            self.assertNotIn("token", datos)
        finally:
            sfl.olvidar_token()

    def test_clave_guardada_no_se_devuelve(self):
        sfl.guardar_clave("0123456789abcdef")
        try:
            datos = json.loads(self.get("/api/clave")[1])
            self.assertTrue(datos["guardada"])
            self.assertNotIn("clave", datos)
        finally:
            sfl.olvidar_clave()

    def test_clave_vacia(self):
        codigo, cuerpo = self.get("/api/clave")
        self.assertEqual(codigo, 200)
        self.assertFalse(json.loads(cuerpo)["guardada"])

    def test_library_csv(self):
        codigo, cuerpo = self.get("/library.csv")
        self.assertEqual(codigo, 200)
        self.assertIn("appid", cuerpo)

    def test_usa_el_token_guardado_si_no_se_pega(self):
        carga = base64.urlsafe_b64encode(
            json.dumps({"exp": 2000000000, "sub": "1"}).encode()).decode().rstrip("=")
        tok = "x." + carga + "." + "a" * 43
        sfl.guardar_token(tok)
        vistos = []
        original = sfl.ejecutar
        sfl.ejecutar = lambda datos, token, api_key="", **k: (vistos.append(token) or (True, "ok"))
        try:
            codigo, _ = self.post("/api/actualizar", {"guardar": False})
        finally:
            sfl.ejecutar = original
            sfl.olvidar_token()
        self.assertEqual(codigo, 200)
        self.assertEqual(vistos, [tok])

    def test_panel_inexistente(self):
        self.assertEqual(self.get("/panel.html")[0], 404)

    def test_fichero_que_no_existe(self):
        self.assertEqual(self.get("/prestados.csv")[0], 404)

    def test_cuerpo_demasiado_grande(self):
        req = urllib.request.Request(
            self.base + "/api/actualizar", data=b"{}" * 60_000,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                codigo = r.status
        except urllib.error.HTTPError as e:
            codigo = e.code
        self.assertEqual(codigo, 413)

    def test_ruta_desconocida(self):
        self.assertEqual(self.get("/loquesea")[0], 404)

    def test_host_ajeno(self):
        puerto = self.servidor.server_address[1]
        conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=5)
        try:
            conexion.putrequest("GET", "/api/estado", skip_host=True)
            conexion.putheader("Host", "malo.example")
            conexion.endheaders()
            respuesta = conexion.getresponse()
            respuesta.read()
            self.assertEqual(respuesta.status, 403)
        finally:
            conexion.close()

    def test_json_roto(self):
        req = urllib.request.Request(
            self.base + "/api/actualizar", data=b"{roto",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                codigo = r.status
        except urllib.error.HTTPError as e:
            codigo = e.code
        self.assertEqual(codigo, 400)

    def test_sin_token(self):
        self.assertEqual(self.post("/api/actualizar", {})[0], 400)

    def test_api_key_invalida(self):
        codigo, cuerpo = self.post("/api/actualizar", {"token": "x", "api_key": "no-es-hex"})
        self.assertEqual(codigo, 400)
        self.assertIn("32", json.loads(cuerpo)["error"])

    def test_api_key_valida(self):
        vistos = []
        original = sfl.ejecutar
        sfl.ejecutar = lambda datos, token, api_key="", **k: (vistos.append(api_key) or (True, "ok"))
        try:
            codigo, _ = self.post("/api/actualizar", {
                "token": "x",
                "api_key": "0123456789abcdef0123456789abcdef",
                "guardar": False,
            })
        finally:
            sfl.ejecutar = original
        self.assertEqual(codigo, 200)
        self.assertEqual(vistos, ["0123456789abcdef0123456789abcdef"])

    def test_acepta_el_json_entero(self):
        vistos = []
        original = sfl.ejecutar
        sfl.ejecutar = lambda datos, token, api_key="", **k: (vistos.append((token, api_key)) or (True, "ok"))
        try:
            codigo, _ = self.post("/api/actualizar", {
                "token": '{"success":1,"data":{"webapi_token":"aaa.bbb.ccc"}}',
                "guardar": False,
            })
        finally:
            sfl.ejecutar = original
        self.assertEqual(codigo, 200)
        self.assertEqual(vistos, [("aaa.bbb.ccc", "")])

    def test_token_larguisimo(self):
        self.assertEqual(self.post("/api/actualizar", {"token": "x" * 5000})[0], 400)

    def test_origen_ajeno(self):
        self.assertEqual(self.post("/api/actualizar", {"token": "x"},
                                   origin="http://malo.example")[0], 403)

    def test_olvidar(self):
        self.assertEqual(self.post("/api/olvidar", {})[0], 200)

    def test_progreso(self):
        sfl.progreso("probando")
        try:
            codigo, cuerpo = self.get("/api/progreso")
        finally:
            sfl.parar_progreso()
        self.assertEqual(codigo, 200)
        self.assertTrue(json.loads(cuerpo)["activo"])
        self.assertFalse(json.loads(self.get("/api/progreso")[1])["activo"])

    def test_doble_actualizacion(self):
        original = sfl.ejecutar
        sfl.ejecutar = lambda *a, **k: (time.sleep(0.6) or (True, "ok"))
        codigos = []

        def golpe():
            codigos.append(self.post("/api/actualizar", {"token": "x"})[0])

        try:
            h1 = threading.Thread(target=golpe)
            h1.start()
            time.sleep(0.15)
            h2 = threading.Thread(target=golpe)
            h2.start()
            h1.join(timeout=10)
            h2.join(timeout=10)
        finally:
            sfl.ejecutar = original

        self.assertEqual(sorted(codigos), [200, 409])


if __name__ == "__main__":
    unittest.main()
