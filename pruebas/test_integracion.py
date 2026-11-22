"""Flujo completo contra un Steam falso: sin red y sin tocar la API real.

    python -m unittest discover -s pruebas -v
"""

import csv
import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import steam_families as sfl  # noqa: E402
from falso import SteamFalso, arranca, para, token as token_falso  # noqa: E402

class PruebaIntegracion(unittest.TestCase):
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

    def setUp(self):
        SteamFalso.fallos = {}
        SteamFalso.caida = 0
        SteamFalso.sin_grupo = False
        SteamFalso.sin_apps = False
        SteamFalso.llamadas = []
        self.dormir = sfl.time.sleep
        sfl.time.sleep = lambda segundos: None

    def tearDown(self):
        sfl.time.sleep = self.dormir

    def token(self):
        return token_falso()

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
            self.assertIn("const SIN_NOMBRE = 2", html)

    def test_token_rechazado(self):
        with tempfile.TemporaryDirectory() as tmp:
            SteamFalso.caida = 401
            with self.assertRaises(SystemExit) as error:
                sfl.exportar(pathlib.Path(tmp), self.token(), con_precios=False)
            self.assertIn("rechazado", str(error.exception))

    def test_cuenta_sin_grupo(self):
        SteamFalso.sin_grupo = True
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as error:
                sfl.exportar(pathlib.Path(tmp), self.token(), con_precios=False)
            self.assertIn("grupo familiar", str(error.exception))

    def test_sin_apps(self):
        SteamFalso.sin_apps = True
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as error:
                sfl.exportar(pathlib.Path(tmp), self.token(), con_precios=False)
            self.assertIn("ninguna app", str(error.exception))

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

    def test_sin_nombres_no_deja_hashes_en_las_novedades(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text(json.dumps({
                "nombres": {sfl.etiqueta("111"): "tú", sfl.etiqueta("222"): "Ana"},
                "nombres_fecha": datetime.now().strftime("%Y-%m-%d"),
                "juegos": {},
            }), encoding="utf-8")
            sfl.exportar(d, self.token(), con_nombres=False, con_precios=False)
            self.assertEqual(self.nombres_pedidos(), [])
            nov = json.loads((d / "novedades.json").read_text(encoding="utf-8"))
            quienes = [e["quien"] for e in nov["eventos"]]
            self.assertIn("Ana", quienes)
            self.assertFalse(any(len(q) == 10 for q in quienes))

    def test_nombres_de_juegos_en_el_idioma_de_la_interfaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfl.idioma("en")
            try:
                sfl.exportar(pathlib.Path(tmp), self.token(), con_precios=False)
            finally:
                sfl.idioma("es")
            consultas = [c for r, c in SteamFalso.llamadas if "GetSharedLibraryApps" in r]
            self.assertEqual(consultas[0]["language"], ["english"])

    def test_no_pierde_los_nombres_si_falla_el_refresco(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text(json.dumps({
                "nombres": {sfl.etiqueta("222"): "Ana"},
                "nombres_fecha": "2020-01-01",
                "juegos": {},
            }), encoding="utf-8")
            SteamFalso.fallos = {"222": 99}
            sfl.exportar(d, self.token(), con_precios=False)
            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snap["nombres"].get(sfl.etiqueta("222")), "Ana")

    def test_numera_los_duenos_que_no_son_miembros(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            SteamFalso.fallos = {"333": 99}
            sfl.exportar(d, self.token(), con_precios=False)
            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("Miembro 1", snap["nombres"].values())

    def test_con_api_key_resuelve_en_una_llamada(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            sfl.exportar(d, self.token(), api_key="0" * 32, con_precios=False)
            self.assertEqual(self.nombres_pedidos(), [])
            resumen = [r for r, c in SteamFalso.llamadas if "GetPlayerSummaries" in r]
            self.assertEqual(len(resumen), 1)
            snap = json.loads((d / "snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("Ana", snap["nombres"].values())

    def test_pasa_los_filtros_a_steam(self):
        with tempfile.TemporaryDirectory() as tmp:
            sfl.exportar(pathlib.Path(tmp), self.token(), include_free=True,
                         include_non_games=True, con_precios=False)
            consulta = [c for r, c in SteamFalso.llamadas if "GetSharedLibraryApps" in r][0]
            self.assertEqual(consulta["include_free"], ["true"])
            self.assertEqual(consulta["include_non_games"], ["true"])

    def test_sin_precios_no_consulta_la_tienda(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text(json.dumps({
                "nombres": {}, "nombres_fecha": datetime.now().strftime("%Y-%m-%d"),
                "juegos": {},
            }), encoding="utf-8")
            sfl.exportar(d, self.token(), con_precios=False)
            self.assertFalse(any("appdetails" in r for r, c in SteamFalso.llamadas))

    def test_sin_historial_no_escribe_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            sfl.exportar(d, self.token(), con_historial=False, con_precios=False)
            self.assertFalse((d / "snapshot.json").exists())
            self.assertTrue((d / "library.csv").exists())

    def test_ejecutar_completo(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            ok, texto = sfl.ejecutar(d, self.token())
            self.assertTrue(ok, texto)
            self.assertIn("panel", texto)
            self.assertTrue((d / "panel.html").exists())
            self.assertTrue((d / "library.csv").exists())

    def test_es_gratis(self):
        self.assertFalse(sfl.es_gratis(10))

    def test_snapshot_corrupto_se_aparta(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text("{roto", encoding="utf-8")
            sfl.exportar(d, self.token(), con_precios=False)
            self.assertTrue((d / "snapshot.corrupto.json").exists())
            self.assertTrue((d / "snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()
