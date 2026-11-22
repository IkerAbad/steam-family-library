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
from datetime import date

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import steam_families as sfl  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


def mes(offset):
    y, m = date.today().year, date.today().month - offset
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}-01"


def escribe_datos(d):
    filas = [
        {"appid": "10", "name": "Alfa", "source": "own", "playable": "True",
         "exclude_reason": "", "playtime_minutes": "60", "acquired": mes(2),
         "last_played": "2026-03-01", "store_url": "u"},
        {"appid": "20", "name": "Beta", "source": "family", "playable": "True",
         "exclude_reason": "", "playtime_minutes": "120", "acquired": mes(1),
         "last_played": "2026-01-01", "store_url": "u"},
        {"appid": "30", "name": "Gamma", "source": "family", "playable": "False",
         "exclude_reason": "excluido por el dueño", "playtime_minutes": "0",
         "acquired": mes(0), "last_played": "", "store_url": "u"},
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
    (d / "historial.csv").write_text(
        "fecha,evento,appid,nombre,quien,propio\n" +
        "".join(f"2026-01-01 00:00,nuevo,{1000 + i},Relleno {i},Ana,no\n" for i in range(120)) +
        "2026-11-20 10:00,nuevo,20,Paseo,Ana,no\n"
        "2026-11-21 09:00,fuera,99,Viejo,Luis,no\n",
        encoding="utf-8-sig")


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
        pagina.reload()
        self.assertIn("step 1", pagina.locator("h2").first.inner_text().lower())

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

    def test_historial(self):
        pagina = self.pagina("/panel.html")
        pagina.click("#verHistorial")
        texto = pagina.inner_text("#historialCaja")
        self.assertIn("Paseo", texto)
        self.assertIn("20/11/2026", texto)

    def test_historial_filtros(self):
        pagina = self.pagina("/panel.html")
        pagina.click("#verHistorial")
        filas = "#historialTabla tbody tr"
        self.assertEqual(pagina.locator(filas).count(), 100)

        pagina.fill("#hq", "Paseo")
        self.assertEqual(pagina.locator(filas).count(), 1)
        self.assertIn("Paseo", pagina.inner_text("#historialTabla"))

        pagina.fill("#hq", "")
        pagina.select_option("#hecho", "fuera")
        self.assertIn("Viejo", pagina.inner_text("#historialTabla"))
        self.assertNotIn("Paseo", pagina.inner_text("#historialTabla"))

        pagina.select_option("#hecho", "todo")
        pagina.fill("#hdesde", "2026-11-21")
        self.assertEqual(pagina.locator(filas).count(), 1)
        self.assertIn("Viejo", pagina.inner_text("#historialTabla"))

    def test_historial_mas(self):
        pagina = self.pagina("/panel.html")
        pagina.click("#verHistorial")
        filas = pagina.locator("#historialTabla tbody tr")
        self.assertEqual(filas.count(), 100)
        self.assertTrue(pagina.is_visible("#historialMas"))
        pagina.click("#historialMas")
        self.assertEqual(filas.count(), 122)

    def test_miembros(self):
        pagina = self.pagina("/panel.html")
        filas = pagina.locator("#miembrosTabla tbody tr").all_inner_texts()
        self.assertEqual(len(filas), 2)
        ana = [f for f in filas if "Ana" in f][0]
        yo = [f for f in filas if "tú" in f][0]
        self.assertIn("2", ana)
        self.assertIn("2,0 h", ana)
        self.assertIn("1,0 h", yo)

        anchos = pagina.eval_on_selector_all(
            "#miembrosTabla .mini", "barras => barras.map(b => b.style.width)")
        self.assertIn("100%", anchos)
        self.assertIn("50%", anchos)

    def test_favoritos_y_ocultos(self):
        pagina = self.pagina("/panel.html")
        filas = pagina.locator("#cuerpo tr")
        self.assertEqual(filas.count(), 3)

        pagina.click('[data-fav="10"]')
        self.assertEqual(pagina.get_attribute('[data-fav="10"]', "aria-pressed"), "true")
        pagina.check("#soloFav")
        self.assertEqual(filas.count(), 1)
        pagina.uncheck("#soloFav")

        pagina.click('[data-ocultar="10"]')
        self.assertEqual(filas.count(), 2)
        pagina.check("#verOcultos")
        self.assertEqual(filas.count(), 3)

        pagina.reload()
        self.assertEqual(pagina.get_attribute('[data-fav="10"]', "aria-pressed"), "true")
        self.assertEqual(filas.count(), 3)

    def test_altas_por_mes(self):
        pagina = self.pagina("/panel.html")
        self.assertEqual(pagina.locator("#mesesCaja .mes").count(), 12)
        total = sum(int(t) for t in pagina.locator("#mesesCaja .num").all_inner_texts())
        self.assertEqual(total, 3)

    def test_exportar_csv(self):
        pagina = self.pagina("/panel.html")
        with pagina.expect_download() as descarga:
            pagina.click("#exportar")
        texto = pathlib.Path(descarga.value.path()).read_text(encoding="utf-8-sig")
        lineas = texto.strip().splitlines()
        self.assertEqual(len(lineas), 4)
        self.assertIn("appid,name,source", lineas[0])
        self.assertIn("Alfa", texto)

        pagina.fill("#q", "Alfa")
        pagina.wait_for_timeout(250)
        with pagina.expect_download() as descarga:
            pagina.click("#exportar")
        texto = pathlib.Path(descarga.value.path()).read_text(encoding="utf-8-sig")
        self.assertEqual(len(texto.strip().splitlines()), 2)

    def test_tema(self):
        pagina = self.pagina("/panel.html")
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "claro")
        pagina.click("#tema")
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "oscuro")
        pagina.reload()
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "oscuro")

    def test_tema_local(self):
        pagina = self.pagina("/")
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "claro")
        pagina.click("#tema")
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "oscuro")
        pagina.reload()
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "oscuro")

    def test_tema_sigue_al_sistema(self):
        pagina = self.pagina("/panel.html")
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "claro")
        pagina.emulate_media(color_scheme="dark")
        pagina.wait_for_timeout(200)
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "oscuro")
        pagina.emulate_media(color_scheme="light")
        pagina.wait_for_timeout(200)
        self.assertEqual(pagina.get_attribute("html", "data-tema"), "claro")

    def test_busqueda_por_dueno(self):
        pagina = self.pagina("/panel.html")
        filas = pagina.locator("#cuerpo tr")
        pagina.fill("#q", "Ana")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 2)
        pagina.fill("#q", "tú")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Alfa", pagina.inner_text("#cuerpo"))

    def test_exportar_historial(self):
        pagina = self.pagina("/panel.html")
        pagina.click("#verHistorial")
        pagina.select_option("#hecho", "fuera")
        with pagina.expect_download() as descarga:
            pagina.click("#exportarHistorial")
        texto = pathlib.Path(descarga.value.path()).read_text(encoding="utf-8-sig")
        lineas = texto.strip().splitlines()
        self.assertEqual(lineas[0], "fecha,evento,appid,nombre,quien,propio")
        self.assertEqual(len(lineas), 2)
        self.assertIn("Viejo", texto)
        self.assertIn("99", texto)

    def test_filtro_por_dueno(self):
        pagina = self.pagina("/panel.html")
        filas = pagina.locator("#cuerpo tr")
        anna = sfl.etiqueta("222")
        yo = sfl.etiqueta("111")

        pagina.select_option("#duenoFiltro", anna)
        self.assertEqual(filas.count(), 2)
        pagina.select_option("#duenoFiltro", yo)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Alfa", pagina.inner_text("#cuerpo"))

        pagina.reload()
        self.assertEqual(pagina.input_value("#duenoFiltro"), yo)
        self.assertEqual(filas.count(), 1)

    def test_ajustes(self):
        pagina = self.pagina("/panel.html")
        with pagina.expect_download() as descarga:
            pagina.click("#guardarAjustes")
        datos = json.loads(pathlib.Path(descarga.value.path()).read_text(encoding="utf-8"))
        self.assertEqual(datos["version"], 1)
        self.assertEqual(datos["tema"], "claro")
        self.assertEqual(datos["idioma"], "es")

        fichero = pathlib.Path(self.tmp.name) / "ajustes-prueba.json"
        fichero.write_text(json.dumps({
            "version": 1, "tema": "oscuro", "idioma": "en",
            "favoritos": ["20"], "ocultos": ["10"], "filtros": {},
        }), encoding="utf-8")
        pagina.set_input_files("#ficheroAjustes", str(fichero))
        pagina.wait_for_timeout(300)

        self.assertEqual(pagina.get_attribute("html", "data-tema"), "oscuro")
        self.assertIn("Steam family library", pagina.inner_text("h1"))
        self.assertEqual(pagina.get_attribute('[data-fav="20"]', "aria-pressed"), "true")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 2)

    def test_atajos(self):
        pagina = self.pagina("/panel.html")
        pagina.keyboard.press("/")
        self.assertEqual(pagina.evaluate("document.activeElement.id"), "q")
        pagina.keyboard.type("Ana")
        pagina.keyboard.press("Escape")
        self.assertEqual(pagina.input_value("#q"), "")

    def test_busqueda_avanzada(self):
        pagina = self.pagina("/panel.html")
        filas = pagina.locator("#cuerpo tr")

        pagina.fill("#q", "horas:>1")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Beta", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "horas:<1")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Gamma", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "anio:2025")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 0)


if __name__ == "__main__":
    unittest.main()
