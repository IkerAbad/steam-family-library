"""Caminos de error que no dependen del navegador.

Se ejecutan en Linux y Windows; los de plataforma viven en `pruebas_plataforma`.
"""

import base64
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import steam_families as sfl  # noqa: E402


def jwt(exp, sub="1"):
    datos = {"exp": exp}
    if sub:
        datos["sub"] = sub
    carga = base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")
    return "x." + carga + "." + "a" * 43


def escribe_library(d, filas=None):
    filas = filas or [{
        "appid": "10", "name": "Juego", "source": "family", "playable": "True",
        "exclude_reason": "", "playtime_minutes": "60", "acquired": "2026-01-01",
        "last_played": "", "store_url": "u",
    }]
    with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
        import csv
        w = csv.DictWriter(f, fieldnames=sfl.COLUMNAS)
        w.writeheader()
        w.writerows(filas)
    (d / "snapshot.json").write_text(json.dumps({
        "yo": "1", "fecha": "2026-01-01T00:00:00+00:00",
        "nombres": {"1": "tú"},
        "juegos": {"10": {"o": ["1"], "p": True}},
    }), encoding="utf-8")


class PruebaErroresComunes(unittest.TestCase):
    def test_carpeta_no_puede_crear(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("pathlib.Path.mkdir", side_effect=OSError("boom")):
                with self.assertRaises(SystemExit):
                    sfl.carpeta(str(pathlib.Path(tmp) / "x"))

    def test_steamid_no_es_jwt(self):
        with self.assertRaises(SystemExit):
            sfl.steamid_del_token("x")

    def test_steamid_payload_roto(self):
        with self.assertRaises(SystemExit):
            sfl.steamid_del_token("x.@@@." + "a" * 43)

    def test_steamid_caducado(self):
        with self.assertRaises(SystemExit):
            sfl.steamid_del_token(jwt(1000000000))

    def test_steamid_sin_sub(self):
        with self.assertRaises(SystemExit):
            sfl.steamid_del_token(jwt(2000000000, sub=""))

    def test_steamid_valido(self):
        self.assertEqual(sfl.steamid_del_token(jwt(2000000000)), "1")

    def test_nombres_api_falla(self):
        with mock.patch("steam_families.urllib.request.urlopen",
                        side_effect=Exception("sin red")), \
             mock.patch("steam_families.time.sleep"):
            self.assertEqual(sfl.nombres(["111"], api_key="0" * 32), {})

    def test_nombres_sid_vacio(self):
        with mock.patch("steam_families.urllib.request.urlopen",
                        side_effect=Exception("sin red")):
            self.assertEqual(sfl.nombres(["", "111"]), {})

    def test_historial_corrupto_y_sin_renombrar(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "historial.csv").write_bytes(b"\xff\xfe\x00mal")
            with mock.patch("pathlib.Path.replace", side_effect=OSError("boom")):
                self.assertEqual(sfl.leer_historial(d), [])

    def test_chivato_otro_dueno(self):
        texto = sfl.chivato([{
            "evento": "nuevo_dueno", "nombre": "Juego", "quien": "Ana", "propio": False,
        }], "2026-01-01 10:00")
        self.assertIn("= Juego", texto)
        self.assertIn("Ana", texto)

    def test_exportar_snapshot_corrupto(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text("[]", encoding="utf-8")
            with mock.patch("steam_families.descargar", side_effect=RuntimeError("fin")), \
                 mock.patch("pathlib.Path.replace", side_effect=OSError("boom")):
                with self.assertRaises(RuntimeError):
                    sfl.exportar(d, "token", con_historial=False)

    def test_exportar_library_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            datos = {"juegos": [], "csv": [], "yo": "1", "snapshot": {}, "alias": {}, "grupo": "G"}
            with mock.patch("steam_families.descargar", return_value=datos), \
                 mock.patch("steam_families.escribir_csv", side_effect=OSError("boom")):
                with self.assertRaises(SystemExit):
                    sfl.exportar(d, "token", con_historial=False)

    def test_exportar_historial_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text(json.dumps({"juegos": {}}), encoding="utf-8")
            datos = {"juegos": [], "csv": [], "yo": "1", "snapshot": {}, "alias": {}, "grupo": "G"}
            evento = [{"evento": "nuevo", "appid": 1, "nombre": "X",
                       "quien": "Ana", "propio": False}]
            with mock.patch("steam_families.descargar", return_value=datos), \
                 mock.patch("steam_families.comparar", return_value=evento), \
                 mock.patch("steam_families.escribir_csv"), \
                 mock.patch("steam_families.escribir_atomico", side_effect=OSError("boom")):
                with self.assertRaises(SystemExit):
                    sfl.exportar(d, "token", con_precios=False)

    def test_exportar_precios(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "snapshot.json").write_text(json.dumps({"juegos": {}}), encoding="utf-8")
            datos = {"juegos": [], "csv": [], "yo": "1", "snapshot": {}, "alias": {}, "grupo": "G"}
            evento = [{"evento": "nuevo", "appid": 1, "nombre": "X",
                       "quien": "Ana", "propio": False}]
            with mock.patch("steam_families.descargar", return_value=datos), \
                 mock.patch("steam_families.comparar", return_value=evento), \
                 mock.patch("steam_families.es_gratis", return_value=True), \
                 mock.patch("steam_families.escribir_csv"), \
                 mock.patch("steam_families.escribir_atomico"), \
                 mock.patch("steam_families.anotar_historial"), \
                 mock.patch("steam_families.time.sleep"):
                sfl.exportar(d, "token", con_precios=True)
            self.assertTrue(evento[0]["gratis"])

    def test_leer_historial_directorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "historial.csv").mkdir()
            self.assertEqual(sfl.leer_historial(d), [])

    def test_generar_panel_csv_directorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "library.csv").mkdir()
            with self.assertRaises(SystemExit):
                sfl.generar_panel(d)

    def test_generar_panel_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "library.csv").write_bytes(b"\xff\xfe\x00mal")
            with self.assertRaises(SystemExit):
                sfl.generar_panel(d)

    def test_generar_panel_prestados_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            escribe_library(d)
            with mock.patch("steam_families.escribir_csv", side_effect=OSError("boom")):
                with self.assertRaises(SystemExit):
                    sfl.generar_panel(d)

    def test_generar_panel_error_al_escribir(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            escribe_library(d)
            original = sfl.escribir_atomico

            def falla(ruta, texto):
                if pathlib.Path(ruta).name == "panel.html":
                    raise OSError("boom")
                return original(ruta, texto)

            with mock.patch("steam_families.escribir_atomico", side_effect=falla):
                with self.assertRaises(SystemExit):
                    sfl.generar_panel(d)

    def test_ejecutar_errores(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("steam_families.exportar", side_effect=SystemExit("boom")):
                self.assertEqual(sfl.ejecutar(tmp, "token"), (False, "boom"))
            with mock.patch("steam_families.exportar", side_effect=RuntimeError("x")):
                ok, texto = sfl.ejecutar(tmp, "token")
                self.assertFalse(ok)
                self.assertIn("RuntimeError", texto)

    def test_leer_ajustes_directorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "ajustes.json").mkdir()
            self.assertIsNone(sfl.leer_ajustes(d))

    def test_guardar_ajustes_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("steam_families.escribir_atomico", side_effect=OSError("boom")):
                self.assertFalse(sfl.guardar_ajustes(tmp, 3))

    def test_actualizacion_con_cerrojo_ocupado(self):
        with tempfile.TemporaryDirectory() as tmp:
            veces = []

            def dormir(segundos):
                veces.append(segundos)
                if len(veces) >= 2:
                    raise RuntimeError("fin")

            sfl.CANDADO.acquire()
            try:
                with mock.patch("steam_families.leer_token", return_value="token"):
                    with self.assertRaises(RuntimeError):
                        sfl.actualizacion_periodica(
                            tmp, 1, dormir=dormir,
                            ejecutar_fn=lambda *a, **k: self.fail("no debe ejecutar"))
            finally:
                sfl.CANDADO.release()

    def test_estado_token_invalido(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                sfl.guardar_token("no.es.un.jwt")
                estado = sfl.estado_token()
                self.assertTrue(estado["guardado"])
                self.assertTrue(estado["caducado"])
                self.assertEqual(estado["motivo"], "invalido")
                self.assertIsNone(sfl.leer_token())
            finally:
                sfl.ruta_token = original

    def test_estado_token_ilegible(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            ruta = pathlib.Path(tmp) / "token.bin"
            ruta.write_bytes(b"\xff\xfe\x00")
            sfl.ruta_token = lambda: ruta
            try:
                estado = sfl.estado_token()
                self.assertTrue(estado["guardado"])
                self.assertTrue(estado["caducado"])
                self.assertEqual(estado["motivo"], "invalido")
                self.assertIsNone(sfl.leer_token())
            finally:
                sfl.ruta_token = original

    def test_guardar_clave_sin_ruta(self):
        with mock.patch("steam_families.ruta_clave", return_value=None):
            self.assertFalse(sfl.guardar_clave("0" * 32))

    def test_estado_csv_con_horas_mal(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            escribe_library(d)
            with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
                import csv
                w = csv.DictWriter(f, fieldnames=sfl.COLUMNAS)
                w.writeheader()
                w.writerow({"appid": "10", "name": "Juego", "source": "family",
                            "playable": "True", "exclude_reason": "",
                            "playtime_minutes": "no-numero", "acquired": "2026-01-01",
                            "last_played": "", "store_url": "u"})
            self.assertEqual(sfl.estado(d)["horas"], 0)

    def test_estado_csv_directorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            escribe_library(d)
            (d / "library.csv").unlink()
            (d / "library.csv").mkdir()
            self.assertEqual(sfl.estado(d)["horas"], 0)


if __name__ == "__main__":
    unittest.main()
