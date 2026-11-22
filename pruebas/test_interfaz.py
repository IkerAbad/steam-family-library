"""Pruebas de la interfaz en un navegador real.

Se saltan si Playwright no está instalado:

    pip install playwright
    playwright install chromium
    python -m unittest discover -s pruebas -p "test_interfaz.py" -v
"""

import csv
import json
import pathlib
import sys
import tempfile
import threading
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import steam_families as sfl  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def escribe_datos(d):
    filas = [
        {"appid": "10", "name": "Alfa", "source": "own", "playable": "True",
         "exclude_reason": "", "playtime_minutes": "60", "acquired": "2026-01-01",
         "last_played": "2026-03-01", "store_url": "u"},
        {"appid": "20", "name": "Beta", "source": "family", "playable": "True",
         "exclude_reason": "", "playtime_minutes": "120", "acquired": "2026-02-01",
         "last_played": "2026-01-01", "store_url": "u"},
        {"appid": "30", "name": "Gamma", "source": "family", "playable": "False",
         "exclude_reason": "excluido por el dueño", "playtime_minutes": "0",
         "acquired": "2026-03-01", "last_played": "", "store_url": "u"},
    ]
    with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=sfl.COLUMNAS)
        w.writeheader()
        w.writerows(filas)

    snap = {"yo": sfl.etiqueta("111"), "fecha": "2026-11-22T09:00:00+00:00",
            "nombres": {sfl.etiqueta("111"): "tú", sfl.etiqueta("222"): "Ana"},
            "juegos": {"10": {"o": [sfl.etiqueta("111")], "p": True},
                       "20": {"o": [sfl.etiqueta("222")], "p": True},
                       "30": {"o": [sfl.etiqueta("222")], "p": False}}}
    (d / "snapshot.json").write_text(json.dumps(snap), encoding="utf-8")


@unittest.skipUnless(sync_playwright, "Playwright no está instalado")
class PruebaInterfaz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.datos = pathlib.Path(cls.tmp.name)
        escribe_datos(cls.datos)
        sfl.generar_panel(cls.datos)

        try:
            cls.pw = sync_playwright().start()
            cls.navegador = cls.pw.chromium.launch()
        except Exception:
            try:
                cls.pw.stop()
            except Exception:
                pass
            cls.tmp.cleanup()
            raise unittest.SkipTest("Chromium no está instalado: playwright install chromium")

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
        cls.navegador.close()
        cls.pw.stop()
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.hilo.join(timeout=5)
        sfl.Handler.datos = pathlib.Path(".")
        sfl.ruta_token = cls.ruta_original
        cls.tmp.cleanup()

    def pagina(self, ruta="/"):
        contexto = self.navegador.new_context(locale="es-ES")
        self.addCleanup(contexto.close)
        pagina = contexto.new_page()
        pagina.set_default_timeout(5000)
        pagina.goto(self.base + ruta)
        return pagina

    def test_cambia_de_idioma(self):
        pagina = self.pagina()
        self.assertIn("paso 1", pagina.locator("h2").first.inner_text().lower())
        pagina.click('[data-idioma="en"]')
        self.assertIn("step 1", pagina.locator("h2").first.inner_text().lower())
        self.assertIn("Export your family library", pagina.inner_text(".sub"))

    def test_panel_ordena_por_horas(self):
        pagina = self.pagina("/panel.html")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 3)

        pagina.click('th[data-campo="m"]')
        primera = pagina.inner_text("#cuerpo tr:first-child td:nth-child(5)").strip()
        self.assertEqual(primera, "2,0 h")

        pagina.click('th[data-campo="m"]')
        primera = pagina.inner_text("#cuerpo tr:first-child td:nth-child(5)").strip()
        self.assertEqual(primera, "")

    def test_panel_recuerda_filtros(self):
        pagina = self.pagina("/panel.html")
        pagina.select_option("#origen", "own")
        pagina.reload()
        self.assertEqual(pagina.input_value("#origen"), "own")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 1)

    def test_limpiar_filtros(self):
        pagina = self.pagina("/panel.html")
        pagina.fill("#q", "Alfa")
        pagina.wait_for_selector("#limpiar:not([hidden])")
        pagina.click("#limpiar")
        self.assertEqual(pagina.input_value("#q"), "")
        self.assertEqual(pagina.input_value("#origen"), "todo")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 3)

    def test_orden_con_teclado(self):
        pagina = self.pagina("/panel.html")
        cabecera = pagina.locator('th[data-campo="m"]')
        cabecera.focus()
        pagina.keyboard.press("Enter")
        self.assertEqual(cabecera.get_attribute("aria-sort"), "descending")
        pagina.keyboard.press("Enter")
        self.assertEqual(cabecera.get_attribute("aria-sort"), "ascending")


if __name__ == "__main__":
    unittest.main()
