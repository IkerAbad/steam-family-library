"""Pruebas de la línea de comandos, sin red."""

import contextlib
import csv
import io
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import steam_families as sfl  # noqa: E402
from falso import SteamFalso, arranca, para, token as token_falso  # noqa: E402


def escribe_datos(d):
    with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=sfl.COLUMNAS)
        w.writeheader()
        w.writerow({"appid": "10", "name": "Mio", "source": "own", "playable": "True",
                    "exclude_reason": "", "playtime_minutes": "60",
                    "acquired": "2026-01-01", "last_played": "", "store_url": "u"})
    snap = {"yo": sfl.etiqueta("111"), "fecha": "2026-11-22T09:00:00+00:00",
            "nombres": {sfl.etiqueta("111"): "tú"},
            "juegos": {"10": {"o": [sfl.etiqueta("111")], "p": True}}}
    (d / "snapshot.json").write_text(json.dumps(snap), encoding="utf-8")


class PruebaCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor, cls.hilo, base = arranca()
        cls.originales = (sfl.API, sfl.COMUNIDAD, sfl.TIENDA)
        sfl.API = base
        sfl.COMUNIDAD = base
        sfl.TIENDA = base

    @classmethod
    def tearDownClass(cls):
        para(cls.servidor, cls.hilo)
        sfl.API, sfl.COMUNIDAD, sfl.TIENDA = cls.originales

    def ejecuta(self, args):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = sfl.main(args)
        return codigo, salida.getvalue()

    def setUp(self):
        SteamFalso.caida = 0
        SteamFalso.fallos = {}

    def test_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            escribe_datos(d)
            codigo, texto = self.ejecuta(["--panel", "--datos", str(d)])
            self.assertEqual(codigo, 0)
            self.assertTrue((d / "panel.html").exists())
            self.assertIn("panel con 1 juegos", texto)

    def test_segunda_instancia(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            escribe_datos(d)
            candado = sfl.bloquear_datos(d)
            try:
                codigo, texto = self.ejecuta(["--panel", "--datos", str(d)])
            finally:
                sfl.liberar_datos(candado)
            self.assertEqual(codigo, 1)
            self.assertTrue("otra ventana" in texto or "another Steam Families window" in texto)
            codigo, _ = self.ejecuta(["--panel", "--datos", str(d)])
            self.assertEqual(codigo, 0)

    def test_exportar_sin_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            codigo, texto = self.ejecuta(["--exportar", "--datos", tmp])
            self.assertEqual(codigo, 1)
            self.assertIn("falta el token", texto)

    def test_exportar(self):
        with tempfile.TemporaryDirectory() as tmp:
            codigo, texto = self.ejecuta(["--exportar", "--token", token_falso(),
                                          "--datos", tmp, "--sin-precios"])
            self.assertEqual(codigo, 0)
            self.assertIn("3 juegos", texto)
            self.assertTrue((pathlib.Path(tmp) / "library.csv").exists())
            self.assertTrue((pathlib.Path(tmp) / "snapshot.json").exists())

    def test_version(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            with self.assertRaises(SystemExit) as error:
                sfl.main(["--version"])
        self.assertEqual(error.exception.code, 0)
        self.assertIn(sfl.VERSION, salida.getvalue())

    def test_exportar_con_token_rechazado(self):
        SteamFalso.caida = 401
        with tempfile.TemporaryDirectory() as tmp:
            codigo, texto = self.ejecuta(["--exportar", "--token", token_falso(),
                                          "--datos", tmp, "--sin-precios"])
            self.assertEqual(codigo, 1)
            self.assertTrue("rechazado" in texto or "rejected" in texto)

    def test_interfaz_arranca_y_se_para(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            escribe_datos(d)
            sfl.Handler.servidor = None
            hilo = threading.Thread(
                target=self.ejecuta,
                args=(["--datos", str(d), "--puerto", "0", "--sin-navegador", "--cada", "0"],),
                daemon=True)
            hilo.start()

            puerto = None
            for _ in range(60):
                servidor = getattr(sfl.Handler, "servidor", None)
                if servidor is not None:
                    puerto = servidor.server_address[1]
                    break
                time.sleep(0.1)
            self.assertIsNotNone(puerto, "la interfaz no arrancó")

            with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/estado", timeout=5) as r:
                self.assertEqual(r.status, 200)
            peticion = urllib.request.Request(
                f"http://127.0.0.1:{puerto}/api/detener", data=b"{}",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(peticion, timeout=5) as r:
                self.assertEqual(r.status, 200)

            hilo.join(timeout=10)
            self.assertFalse(hilo.is_alive(), "la interfaz no se paró")


if __name__ == "__main__":
    unittest.main()
