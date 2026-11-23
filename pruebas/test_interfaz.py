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
        cls.cada_original = sfl.Handler.cada
        sfl.Handler.cada = 6.0
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
        sfl.Handler.cada = cls.cada_original
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

    def test_recuerda_orden_cabecera(self):
        pagina = self.pagina("/panel.html")
        pagina.click('th[data-campo="m"]')
        self.assertEqual(
            pagina.get_attribute('th[data-campo="m"]', "aria-sort"), "descending")
        pagina.reload()
        self.assertEqual(
            pagina.get_attribute('th[data-campo="m"]', "aria-sort"), "descending")

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

    def test_miembros_orden(self):
        pagina = self.pagina("/panel.html")
        horas = pagina.locator('#miembrosTabla th[data-campo-miembro="m"]')
        horas.click()
        self.assertEqual(horas.get_attribute("aria-sort"), "descending")
        filas = pagina.locator("#miembrosTabla tbody tr").all_inner_texts()
        self.assertIn("Ana", filas[0])

        horas.click()
        self.assertEqual(horas.get_attribute("aria-sort"), "ascending")
        filas = pagina.locator("#miembrosTabla tbody tr").all_inner_texts()
        self.assertIn("Ana", filas[-1])
        self.assertIn("tú", filas[-2])

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

        total = pagina.inner_text("#miembrosTabla tfoot")
        self.assertIn("Total", total)
        self.assertIn("3", total)
        self.assertIn("2", total)
        self.assertIn("3,0 h", total)
        self.assertIn("2,0 h acumuladas en prestados", pagina.inner_text("#stats"))
        self.assertIn("1,0 h tuyas", pagina.inner_text("#stats"))

    def test_alias_miembros(self):
        pagina = self.pagina("/panel.html")
        hash_ana = sfl.etiqueta("222")
        pagina.once("dialog", lambda dialogo: dialogo.accept("Mamá"))
        pagina.click(f'[data-alias="{hash_ana}"]')

        self.assertIn("Mamá", pagina.inner_text("#miembrosTabla"))
        self.assertIn("Mamá", pagina.inner_text("#cuerpo tr[data-appid='20']"))
        opciones = pagina.eval_on_selector(
            "#duenoFiltro", "s => [...s.options].map(o => o.textContent).join('|')")
        self.assertIn("Mamá", opciones)

        pagina.fill("#q", "dueno:mama")
        pagina.wait_for_timeout(250)
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 2)
        pagina.fill("#q", "")
        pagina.wait_for_timeout(250)

        with pagina.expect_download() as descarga:
            pagina.click("#guardarAjustes")
        datos = json.loads(pathlib.Path(descarga.value.path()).read_text(encoding="utf-8"))
        self.assertEqual(datos["alias"][hash_ana], "Mamá")

        pagina.reload()
        self.assertIn("Mamá", pagina.inner_text("#miembrosTabla"))
        pagina.once("dialog", lambda dialogo: dialogo.accept(""))
        pagina.click(f'[data-alias="{hash_ana}"]')
        self.assertIn("Ana", pagina.inner_text("#miembrosTabla"))

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

    def test_tema_local_sigue_al_sistema(self):
        pagina = self.pagina("/")
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
            "notas": {"20": "desde la copia"},
        }), encoding="utf-8")
        pagina.set_input_files("#ficheroAjustes", str(fichero))
        pagina.wait_for_timeout(300)

        self.assertEqual(pagina.get_attribute("html", "data-tema"), "oscuro")
        self.assertIn("Steam family library", pagina.inner_text("h1"))
        self.assertEqual(pagina.get_attribute('[data-fav="20"]', "aria-pressed"), "true")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 2)
        self.assertEqual(pagina.get_attribute('[data-nota="20"]', "title"), "Edit note")
        self.assertEqual(
            pagina.get_attribute("#cuerpo tr[data-appid='20'] .marca.nota", "title"),
            "desde la copia")

    def test_cada_desde_el_panel(self):
        pagina = self.pagina("/panel.html")
        pagina.wait_for_selector("#cadaCaja", state="visible")
        self.assertEqual(pagina.input_value("#cada"), "6")
        pagina.select_option("#cada", "12")
        for _ in range(60):
            if pagina.inner_text("#cadaEstado") == "Guardado":
                break
            pagina.wait_for_timeout(50)
        self.assertEqual(pagina.inner_text("#cadaEstado"), "Guardado")
        self.assertEqual(sfl.Handler.cada, 12)
        pagina.reload()
        pagina.wait_for_selector("#cadaCaja", state="visible")
        self.assertEqual(pagina.input_value("#cada"), "12")
        pagina.select_option("#cada", "6")
        pagina.wait_for_timeout(300)

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

        pagina.fill("#q", "origen:own")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Alfa", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "estado:jugable")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 2)
        self.assertNotIn("Gamma", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "dueno:ana")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 2)
        self.assertNotIn("Alfa", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "ana beta")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Beta", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "beta ana")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Beta", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "origen:family estado:jugable")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Beta", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "horas:1-2")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 2)
        self.assertIn("Alfa", pagina.inner_text("#cuerpo"))
        self.assertIn("Beta", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "horas:0-1")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 2)
        self.assertIn("Gamma", pagina.inner_text("#cuerpo"))
        self.assertNotIn("Beta", pagina.inner_text("#cuerpo"))

    def test_exportar_json(self):
        pagina = self.pagina("/panel.html")
        pagina.fill("#q", "Beta")
        pagina.wait_for_timeout(250)
        with pagina.expect_download() as descarga:
            pagina.click("#exportarJson")
        fichero = pathlib.Path(descarga.value.path())
        self.assertTrue(descarga.value.suggested_filename.endswith(".json"))
        datos = json.loads(fichero.read_text(encoding="utf-8"))
        self.assertEqual(len(datos), 1)
        self.assertEqual(datos[0]["name"], "Beta")
        self.assertEqual(datos[0]["appid"], 20)
        self.assertTrue(datos[0]["playable"])
        self.assertEqual(datos[0]["playtime_minutes"], 120)
        self.assertEqual(datos[0]["store_url"],
                         "https://store.steampowered.com/app/20")

    def test_vista_compacta(self):
        pagina = self.pagina("/panel.html")
        self.assertFalse(pagina.evaluate("document.body.classList.contains('compacto')"))
        pagina.check("#compacto")
        self.assertTrue(pagina.evaluate("document.body.classList.contains('compacto')"))
        pagina.reload()
        self.assertTrue(pagina.evaluate("document.body.classList.contains('compacto')"))
        with pagina.expect_download() as descarga:
            pagina.click("#guardarAjustes")
        datos = json.loads(pathlib.Path(descarga.value.path()).read_text(encoding="utf-8"))
        self.assertTrue(datos["compacto"])
        pagina.uncheck("#compacto")

    def test_top_jugados(self):
        pagina = self.pagina("/panel.html")
        filas = pagina.locator("#topTabla tbody tr").all_inner_texts()
        self.assertEqual(len(filas), 2)
        self.assertIn("Beta", filas[0])
        self.assertIn("2,0 h", filas[0])
        self.assertIn("Alfa", filas[1])
        anchos = pagina.eval_on_selector_all(
            "#topTabla .mini", "barras => barras.map(b => b.style.width)")
        self.assertEqual(anchos, ["100%", "50%"])

    def test_miembro_filtra(self):
        pagina = self.pagina("/panel.html")
        pagina.click("#miembrosTabla button.enlace:has-text('Ana')")
        self.assertNotEqual(pagina.input_value("#duenoFiltro"), "todo")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 2)
        self.assertNotIn("Alfa", pagina.inner_text("#cuerpo"))
        pagina.click("#limpiar")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 3)

    def test_copiar_resumen(self):
        pagina = self.pagina("/panel.html")
        pagina.context.grant_permissions(["clipboard-read", "clipboard-write"])
        pagina.click("#copiarResumen")
        for _ in range(60):
            if pagina.inner_text("#copiarResumen") == "Copiado":
                break
            pagina.wait_for_timeout(50)
        self.assertEqual(pagina.inner_text("#copiarResumen"), "Copiado")
        texto = pagina.evaluate("navigator.clipboard.readText()")
        self.assertIn("3 de 3 juegos", texto)

    def test_sorprende(self):
        pagina = self.pagina("/panel.html")
        pagina.fill("#q", "Beta")
        pagina.wait_for_timeout(250)
        pagina.click("#sorprende")
        self.assertIn("Beta", pagina.inner_text("#elegido"))
        self.assertTrue(pagina.evaluate(
            "document.querySelector('#cuerpo tr.elegido').dataset.appid === '20'"))

    def test_titulo_cuenta_novedades(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            for nombre in ("library.csv", "snapshot.json"):
                (d / nombre).write_bytes((self.datos / nombre).read_bytes())
            (d / "novedades.json").write_text(json.dumps({
                "fecha": "2026-11-21T10:00:00+00:00",
                "eventos": [
                    {"appid": "20", "evento": "nuevo", "nombre": "Beta"},
                    {"appid": "99", "evento": "fuera", "nombre": "Viejo", "quien": "Ana"},
                ]}), encoding="utf-8")
            sfl.generar_panel(d)
            contexto = self.navegador.new_context(locale="es-ES")
            self.addCleanup(contexto.close)
            pagina = contexto.new_page()
            pagina.goto((d / "panel.html").as_uri())
            self.assertTrue(pagina.title().startswith("(1) "))
            self.assertIn("Biblioteca familiar", pagina.title())
            self.assertTrue(pagina.is_visible("#fueraCaja"))
            self.assertFalse(pagina.is_visible("#detenerPanel"))
            self.assertIn("Viejo", pagina.inner_text("#fueraLista"))
            self.assertIn("Ana", pagina.inner_text("#fueraLista"))
            self.assertIn("1 juegos nuevos", pagina.inner_text("#avisoTexto"))
            self.assertIn("que ya no están", pagina.inner_text("#avisoTexto"))

    def test_titulo_cambia_de_idioma(self):
        pagina = self.pagina("/panel.html")
        self.assertEqual(pagina.title(), "Biblioteca familiar de Steam")
        pagina.click('[data-idioma="en"]')
        self.assertEqual(pagina.title(), "Steam family library")

    def test_historial_se_recuerda(self):
        pagina = self.pagina("/panel.html")
        pagina.click("#verHistorial")
        pagina.fill("#hq", "Paseo")
        pagina.select_option("#hecho", "nuevo")
        pagina.fill("#hdesde", "2026-11-20")
        pagina.reload()
        self.assertTrue(pagina.is_visible("#historialCaja"))
        self.assertEqual(pagina.input_value("#hq"), "Paseo")
        self.assertEqual(pagina.input_value("#hecho"), "nuevo")
        self.assertEqual(pagina.input_value("#hdesde"), "2026-11-20")
        self.assertEqual(pagina.locator("#historialTabla tbody tr").count(), 1)
        pagina.click("#verHistorial")
        pagina.reload()
        self.assertFalse(pagina.is_visible("#historialCaja"))

    def test_exportar_historial_json(self):
        pagina = self.pagina("/panel.html")
        pagina.click("#verHistorial")
        pagina.fill("#hq", "Paseo")
        with pagina.expect_download() as descarga:
            pagina.click("#exportarHistorialJson")
        self.assertTrue(descarga.value.suggested_filename.endswith(".json"))
        datos = json.loads(pathlib.Path(descarga.value.path()).read_text(encoding="utf-8"))
        self.assertEqual(len(datos), 1)
        self.assertEqual(datos[0]["nombre"], "Paseo")
        self.assertEqual(datos[0]["evento"], "nuevo")
        self.assertEqual(datos[0]["appid"], 20)
        self.assertFalse(datos[0]["propio"])

    def test_exportar_miembros(self):
        pagina = self.pagina("/panel.html")
        with pagina.expect_download() as descarga:
            pagina.click("#exportarMiembros")
        self.assertTrue(descarga.value.suggested_filename.startswith("miembros-"))
        lineas = pathlib.Path(descarga.value.path()).read_text(
            encoding="utf-8-sig").splitlines()
        self.assertEqual(lineas[0], "miembro,juegos,jugables,horas")
        self.assertTrue(any(l.startswith("Ana,2,1,2.0") for l in lineas))
        self.assertTrue(any(l.startswith("tú,1,1,1.0") for l in lineas))

    def test_operadores_appid_mes_ultima(self):
        pagina = self.pagina("/panel.html")
        filas = pagina.locator("#cuerpo tr")

        pagina.fill("#q", "appid:20")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Beta", pagina.inner_text("#cuerpo"))

        clave = date.today().strftime("%Y-%m")
        pagina.fill("#q", "mes:" + clave)
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Gamma", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "ultima:never")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 1)
        self.assertIn("Gamma", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "ultima:>30")
        pagina.wait_for_timeout(250)
        self.assertEqual(filas.count(), 2)
        self.assertNotIn("Gamma", pagina.inner_text("#cuerpo"))

    def test_enlace_comparte_filtros(self):
        pagina = self.pagina("/panel.html#q=Beta")
        self.assertEqual(pagina.input_value("#q"), "Beta")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 1)
        self.assertIn("q=Beta", pagina.evaluate("location.hash"))

        pagina.context.grant_permissions(["clipboard-read", "clipboard-write"])
        pagina.click("#copiarEnlace")
        for _ in range(60):
            if pagina.inner_text("#copiarEnlace") == "Copiado":
                break
            pagina.wait_for_timeout(50)
        enlace = pagina.evaluate("navigator.clipboard.readText()")
        self.assertIn("#q=Beta", enlace)

    def test_mes_filtra(self):
        pagina = self.pagina("/panel.html")
        clave = date.today().strftime("%Y-%m")
        pagina.click('.mes[data-clave="%s"]' % clave)
        self.assertEqual(pagina.input_value("#q"), "mes:" + clave)
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 1)
        self.assertIn("Gamma", pagina.inner_text("#cuerpo"))

    def test_hash_tambien_en_panel_suelto(self):
        contexto = self.navegador.new_context(locale="es-ES")
        self.addCleanup(contexto.close)
        pagina = contexto.new_page()
        pagina.goto((self.datos / "panel.html").as_uri())
        pagina.fill("#q", "Beta")
        pagina.wait_for_timeout(250)
        self.assertIn("q=Beta", pagina.evaluate("location.hash"))
        pagina.goto((self.datos / "panel.html").as_uri() + "#q=Beta")
        self.assertEqual(pagina.input_value("#q"), "Beta")
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 1)

    def test_notas(self):
        pagina = self.pagina("/panel.html")
        pagina.once("dialog", lambda dialogo: dialogo.accept("para el finde"))
        pagina.click('[data-nota="20"]')

        fila = pagina.locator("#cuerpo tr[data-appid='20']")
        self.assertEqual(fila.locator(".marca.nota").count(), 1)
        self.assertEqual(pagina.get_attribute('[data-nota="20"]', "title"), "Editar nota")
        self.assertIn("con nota", pagina.inner_text("#stats"))

        pagina.reload()
        self.assertEqual(
            pagina.locator("#cuerpo tr[data-appid='20'] .marca.nota").count(), 1)
        self.assertEqual(pagina.get_attribute('[data-nota="20"]', "title"), "Editar nota")

        pagina.fill("#q", "finde")
        pagina.wait_for_timeout(250)
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 1)
        self.assertIn("Beta", pagina.inner_text("#cuerpo"))

        pagina.fill("#q", "nota:si")
        pagina.wait_for_timeout(250)
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 1)

        pagina.fill("#q", "nota:no")
        pagina.wait_for_timeout(250)
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 2)

        pagina.fill("#q", "")
        pagina.wait_for_timeout(250)
        with pagina.expect_download() as descarga:
            pagina.click("#guardarAjustes")
        datos = json.loads(pathlib.Path(descarga.value.path()).read_text(encoding="utf-8"))
        self.assertEqual(datos["notas"]["20"], "para el finde")

        pagina.once("dialog", lambda dialogo: dialogo.accept(""))
        pagina.click('[data-nota="20"]')
        self.assertEqual(
            pagina.locator("#cuerpo tr[data-appid='20'] .marca.nota").count(), 0)
        self.assertNotIn("con nota", pagina.inner_text("#stats"))

    def test_panel_detecta_actualizacion(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            for nombre in ("library.csv", "snapshot.json"):
                (d / nombre).write_bytes((self.datos / nombre).read_bytes())
            sfl.generar_panel(d)
            original = sfl.Handler.datos
            original_servidor = sfl.Handler.servidor
            sfl.Handler.datos = d
            servidor = sfl.Servidor(("127.0.0.1", 0), sfl.Handler)
            sfl.Handler.servidor = servidor
            hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
            hilo.start()
            try:
                contexto = self.navegador.new_context(locale="es-ES")
                self.addCleanup(contexto.close)
                pagina = contexto.new_page()
                pagina.goto(f"http://127.0.0.1:{servidor.server_address[1]}/panel.html")
                self.assertFalse(pagina.evaluate("hayPanelNuevo()"))
                snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
                snap["fecha"] = "2027-01-01T00:00:00+00:00"
                (d / "snapshot.json").write_text(json.dumps(snap), encoding="utf-8")
                sfl.generar_panel(d)
                self.assertTrue(pagina.evaluate("hayPanelNuevo()"))
            finally:
                servidor.shutdown()
                servidor.server_close()
                hilo.join(timeout=5)
                sfl.Handler.datos = original
                sfl.Handler.servidor = original_servidor

    def test_detener_desde_el_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            for nombre in ("library.csv", "snapshot.json"):
                (d / nombre).write_bytes((self.datos / nombre).read_bytes())
            sfl.generar_panel(d)
            original = sfl.Handler.datos
            original_servidor = sfl.Handler.servidor
            sfl.Handler.datos = d
            servidor = sfl.Servidor(("127.0.0.1", 0), sfl.Handler)
            sfl.Handler.servidor = servidor
            hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
            hilo.start()
            try:
                contexto = self.navegador.new_context(locale="es-ES")
                self.addCleanup(contexto.close)
                pagina = contexto.new_page()
                pagina.goto(f"http://127.0.0.1:{servidor.server_address[1]}/panel.html")
                self.assertTrue(pagina.is_visible("#detenerPanel"))
                pagina.click("#detenerPanel")
                for _ in range(40):
                    if "detenida" in pagina.inner_text("h1").lower():
                        break
                    pagina.wait_for_timeout(50)
                self.assertIn("detenida", pagina.inner_text("h1").lower())
            finally:
                servidor.shutdown()
                servidor.server_close()
                hilo.join(timeout=5)
                sfl.Handler.datos = original
                sfl.Handler.servidor = original_servidor

    def test_imprimir(self):
        pagina = self.pagina("/panel.html")
        pagina.evaluate("window.print = () => { window.__impreso = true; }")
        pagina.click("#imprimir")
        self.assertTrue(pagina.evaluate("window.__impreso"))
        pagina.emulate_media(media="print")
        self.assertFalse(pagina.is_visible("#ajustes"))
        self.assertFalse(pagina.is_visible(".controles"))
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 3)
        pagina.emulate_media(media="screen")
        self.assertTrue(pagina.is_visible("#ajustes"))

    def test_ayuda(self):
        pagina = self.pagina("/panel.html")
        self.assertFalse(pagina.evaluate("document.getElementById('ayuda').open"))
        pagina.keyboard.press("Shift+Slash")
        self.assertTrue(pagina.evaluate("document.getElementById('ayuda').open"))
        pagina.keyboard.press("Shift+Slash")
        self.assertFalse(pagina.evaluate("document.getElementById('ayuda').open"))

    def test_copiar_nombres(self):
        pagina = self.pagina("/panel.html")
        pagina.context.grant_permissions(["clipboard-read", "clipboard-write"])
        pagina.fill("#q", "Beta")
        pagina.wait_for_timeout(250)
        pagina.click("#copiarNombres")
        for _ in range(60):
            if pagina.inner_text("#copiarNombres") == "Copiado":
                break
            pagina.wait_for_timeout(50)
        self.assertEqual(pagina.evaluate("navigator.clipboard.readText()"), "Beta")

    def test_vista_movil(self):
        contexto = self.navegador.new_context(
            locale="es-ES", viewport={"width": 390, "height": 844})
        self.addCleanup(contexto.close)
        pagina = contexto.new_page()
        pagina.goto(self.base + "/panel.html")
        self.assertTrue(pagina.is_visible('th[data-campo="n"]'))
        self.assertFalse(pagina.is_visible('th[data-campo="s"]'))
        self.assertFalse(pagina.is_visible('th[data-campo="u"]'))
        self.assertFalse(pagina.is_visible('th[data-campo="q"]'))
        self.assertTrue(pagina.is_visible('th[data-campo="m"]'))
        self.assertEqual(pagina.locator("#cuerpo tr").count(), 3)

    def test_actualizado_relativo(self):
        pagina = self.pagina("/panel.html")
        texto = pagina.inner_text("#actualizado")
        self.assertIn("Actualizado el", texto)
        self.assertIn("hace", texto)

    def test_saltar_a_la_tabla(self):
        pagina = self.pagina("/panel.html")
        pagina.keyboard.press("Tab")
        self.assertEqual(pagina.evaluate("document.activeElement.id"), "saltar")
        self.assertTrue(pagina.is_visible("#saltar"))
        pagina.keyboard.press("Enter")
        self.assertEqual(pagina.evaluate("location.hash"), "#tablaJuegos")

    def test_accesibilidad_basica(self):
        script = """() => {
          const fallos = [];
          document.querySelectorAll("button").forEach(b => {
            const nombre = (b.textContent || "").trim() ||
              b.getAttribute("aria-label") || b.getAttribute("title");
            if (!nombre) fallos.push("boton sin nombre");
          });
          document.querySelectorAll(
            "input:not([type=hidden]):not([hidden]), select:not([hidden])"
          ).forEach(i => {
            const id = i.id;
            const label = id ? document.querySelector(`label[for="${id}"]`) : null;
            const aria = i.getAttribute("aria-label");
            const dentro = i.closest("label");
            if (!label && !aria && !dentro) {
              fallos.push("control sin etiqueta: " + (id || i.tagName));
            }
          });
          return fallos;
        }"""
        for ruta in ("/", "/panel.html"):
            pagina = self.pagina(ruta)
            self.assertEqual(pagina.evaluate(script), [], ruta)


if __name__ == "__main__":
    unittest.main()
