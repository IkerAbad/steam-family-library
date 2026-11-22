"""Pruebas de la logica, sin red.

    python -m unittest discover -s pruebas -v
"""

import csv
import base64
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta
from unittest import mock

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import steam_families as sfl  # noqa: E402


def juego(nombre, duenos, playable=True):
    return {"n": nombre, "o": sorted(duenos), "p": playable}


class PruebaComparar(unittest.TestCase):
    def base(self, juegos):
        return {"yo": "aaa", "juegos": juegos}

    def test_detecta_nuevo_y_fuera(self):
        antes = self.base({"1": juego("Viejo", ["bbb"]), "2": juego("Se va", ["bbb"])})
        despues = self.base({"1": juego("Viejo", ["bbb"]), "3": juego("Nuevo", ["bbb"])})
        eventos = sfl.comparar(antes, despues, "aaa", {"bbb": "V"})

        tipos = sorted(e["evento"] for e in eventos)
        self.assertEqual(tipos, ["fuera", "nuevo"])

        nuevo = [e for e in eventos if e["evento"] == "nuevo"][0]
        self.assertEqual(nuevo["nombre"], "Nuevo")
        self.assertEqual(nuevo["quien"], "V")

    def test_detecta_segundo_dueno(self):
        antes = self.base({"1": juego("Compartido", ["bbb"])})
        despues = self.base({"1": juego("Compartido", ["bbb", "ccc"])})
        eventos = sfl.comparar(antes, despues, "aaa", {"bbb": "V", "ccc": "M"})
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["evento"], "nuevo_dueno")
        self.assertEqual(eventos[0]["quien"], "M")

    def test_sin_cambios(self):
        igual = self.base({"1": juego("Igual", ["bbb"])})
        self.assertEqual(sfl.comparar(igual, igual, "aaa", {"bbb": "V"}), [])

    def test_tus_propios_juegos_no_salen_como_de_otro(self):
        antes = self.base({})
        despues = self.base({"1": juego("Mio", ["aaa"])})
        eventos = sfl.comparar(antes, despues, "aaa", {"aaa": "tu"})
        self.assertEqual(eventos[0]["quien"], "")
        self.assertTrue(eventos[0]["propio"])


class PruebaEtiqueta(unittest.TestCase):
    def test_estable_y_sin_id(self):
        sid = "76561198000000000"
        self.assertEqual(sfl.etiqueta(sid), sfl.etiqueta(sid))
        self.assertEqual(len(sfl.etiqueta(sid)), 10)
        self.assertNotIn(sid, sfl.etiqueta(sid))


class PruebaToken(unittest.TestCase):
    def test_suelto(self):
        self.assertEqual(sfl.normaliza_token("  abc.def.ghi  "), "abc.def.ghi")

    def test_entre_comillas(self):
        self.assertEqual(sfl.normaliza_token('"abc.def.ghi"'), "abc.def.ghi")

    def test_json_entero(self):
        crudo = '{"success":1,"data":{"webapi_token":"abc.def.ghi"}}'
        self.assertEqual(sfl.normaliza_token(crudo), "abc.def.ghi")

    def test_json_roto_no_revienta(self):
        self.assertEqual(sfl.normaliza_token('{"roto":'), '{"roto":')

    def test_firma_cortada(self):
        with self.assertRaises(SystemExit):
            sfl.steamid_del_token("x.eyJleHAiOjIwMDAwMDAwMDB9.abc")


class PruebaNombres(unittest.TestCase):
    def test_rellena_huecos_sin_tocar_el_tuyo(self):
        alias = sfl.rellenar_huecos({"bbb": "V"}, ["bbb", "ccc", "ddd"], "aaa")
        self.assertEqual(alias["bbb"], "V")
        self.assertEqual(alias["ccc"], "Miembro 1")
        self.assertEqual(alias["ddd"], "Miembro 2")
        self.assertNotIn("aaa", alias)

    def test_rellena_tambien_otros_duenos(self):
        alias = sfl.rellenar_huecos({}, ["bbb"], "aaa", ["ccc", "ddd"])
        self.assertEqual(alias["bbb"], "Miembro 1")
        self.assertEqual(alias["ccc"], "Miembro 2")
        self.assertEqual(alias["ddd"], "Miembro 3")


class PruebaNombresRed(unittest.TestCase):
    """Sin red: se sustituye urlopen y la pausa entre peticiones."""

    def setUp(self):
        self.urlopen = sfl.urllib.request.urlopen
        self.sleep = sfl.time.sleep
        sfl.time.sleep = lambda s: None

    def tearDown(self):
        sfl.urllib.request.urlopen = self.urlopen
        sfl.time.sleep = self.sleep

    def test_pide_uno_a_uno(self):
        llamadas = []

        class Respuesta:
            def __init__(self, sid):
                self.sid = sid

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps([{"steamid": self.sid,
                                    "persona_name": "Nombre " + self.sid}]).encode()

        def falso(req, timeout=0):
            sid = req.full_url.rsplit("=", 1)[1]
            llamadas.append(sid)
            return Respuesta(sid)

        sfl.urllib.request.urlopen = falso
        alias = sfl.nombres(["111", "222"], {}, "")
        self.assertEqual(alias, {"111": "Nombre 111", "222": "Nombre 222"})
        self.assertEqual(llamadas, ["111", "222"])

    def test_para_cuando_steam_frena(self):
        llamadas = []

        def falso(req, timeout=0):
            llamadas.append(req.full_url.rsplit("=", 1)[1])
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

        sfl.urllib.request.urlopen = falso
        alias = sfl.nombres(["111", "222"], {}, "")
        self.assertEqual(alias, {})
        self.assertEqual(llamadas, ["111", "111", "111", "111"])

    def test_reintenta_tras_el_429(self):
        llamadas = []

        class Respuesta:
            def __init__(self, sid):
                self.sid = sid

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps([{"steamid": self.sid,
                                    "persona_name": "Nombre"}]).encode()

        def falso(req, timeout=0):
            sid = req.full_url.rsplit("=", 1)[1]
            llamadas.append(sid)
            if len(llamadas) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
            return Respuesta(sid)

        sfl.urllib.request.urlopen = falso
        alias = sfl.nombres(["111"], {}, "")
        self.assertEqual(alias, {"111": "Nombre"})
        self.assertEqual(llamadas, ["111", "111"])


class PruebaNombresCaducados(unittest.TestCase):
    def test_hoy_no_caduca(self):
        self.assertFalse(sfl.nombres_caducados(datetime.now().strftime("%Y-%m-%d")))

    def test_ocho_dias_caduca(self):
        viejo = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
        self.assertTrue(sfl.nombres_caducados(viejo))

    def test_vacio_caduca(self):
        self.assertTrue(sfl.nombres_caducados(""))
        self.assertTrue(sfl.nombres_caducados(None))


class PruebaChivato(unittest.TestCase):
    def test_texto_legible(self):
        eventos = [
            {"evento": "nuevo", "nombre": "Juego", "quien": "V", "propio": False, "gratis": True},
            {"evento": "fuera", "nombre": "Otro", "quien": "M", "propio": False},
            {"evento": "nuevo", "nombre": "Mio", "quien": "", "propio": True},
        ]
        texto = sfl.chivato(eventos, "2026-01-01 10:00")
        self.assertIn("+ Juego  (de V)  [gratis]", texto)
        self.assertIn("- Otro  (ya no está; era de M)", texto)
        self.assertIn("+ Mio  (de ti)", texto)

    def test_sin_eventos(self):
        self.assertIn("Sin cambios", sfl.chivato([], "2026-01-01"))

    def test_fecha_legible(self):
        self.assertEqual(sfl.fecha_legible("2026-11-22 10:00"), "22/11/2026 10:00")
        self.assertEqual(sfl.fecha_legible("2026-11-22"), "2026-11-22")
        self.assertEqual(sfl.fecha_legible(""), "")

    def test_en_ingles(self):
        eventos = [{"evento": "nuevo", "nombre": "X", "quien": "V", "propio": False}]
        sfl.idioma("en")
        try:
            texto = sfl.chivato(eventos, "2026-01-01")
        finally:
            sfl.idioma("es")
        self.assertIn("Changes from 2026-01-01", texto)
        self.assertIn("+ X  (from V)", texto)


class PruebaCarpeta(unittest.TestCase):
    def test_crea_carpetas_anidadas(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = pathlib.Path(tmp) / "a" / "b" / "c"
            self.assertEqual(sfl.carpeta(str(destino)), destino.resolve())
            self.assertTrue(destino.is_dir())

    def test_rechaza_fichero(self):
        with tempfile.TemporaryDirectory() as tmp:
            fichero = pathlib.Path(tmp) / "fichero.txt"
            fichero.write_text("hola", encoding="utf-8")
            with self.assertRaises(SystemExit):
                sfl.carpeta(str(fichero))

    @unittest.skipUnless(os.name == "nt", "solo Windows")
    def test_rechaza_comilla_colada(self):
        with self.assertRaises(SystemExit):
            sfl.carpeta('C:\\una\\ruta"')


class PruebaEscrituraAtomica(unittest.TestCase):
    def test_deja_el_viejo_si_falla(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = pathlib.Path(tmp) / "x.json"
            ruta.write_text("viejo", encoding="utf-8")
            with mock.patch("steam_families.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    sfl.escribir_atomico(ruta, "nuevo")
            self.assertEqual(ruta.read_text(encoding="utf-8"), "viejo")
            self.assertFalse((pathlib.Path(tmp) / "x.json.tmp").exists())


class PruebaApiReintentos(unittest.TestCase):
    def setUp(self):
        self.urlopen = sfl.urllib.request.urlopen
        self.dormir = sfl.time.sleep
        sfl.time.sleep = lambda segundos: None

    def tearDown(self):
        sfl.urllib.request.urlopen = self.urlopen
        sfl.time.sleep = self.dormir

    def test_reintenta_un_500(self):
        llamadas = []

        class Respuesta:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"response": {"ok": 1}}'

        def falso(req, timeout=0):
            llamadas.append(1)
            if len(llamadas) == 1:
                raise urllib.error.HTTPError(req.full_url, 500, "boom", {},
                                             io.BytesIO(b"error"))
            return Respuesta()

        sfl.urllib.request.urlopen = falso
        self.assertEqual(sfl.api_get("X", {}), {"ok": 1})
        self.assertEqual(len(llamadas), 2)

    def test_no_reintenta_un_403(self):
        llamadas = []

        def falso(req, timeout=0):
            llamadas.append(1)
            raise urllib.error.HTTPError(req.full_url, 403, "no", {},
                                         io.BytesIO(b"no"))

        sfl.urllib.request.urlopen = falso
        with self.assertRaises(SystemExit):
            sfl.api_get("X", {})
        self.assertEqual(len(llamadas), 1)


class PruebaTokenRechazado(unittest.TestCase):
    def test_borra_el_guardado_si_steam_lo_rechaza(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = sfl.ruta_token
            urlopen = sfl.urllib.request.urlopen
            dormir = sfl.time.sleep
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            sfl.time.sleep = lambda segundos: None

            carga = base64.urlsafe_b64encode(
                json.dumps({"exp": 2000000000}).encode()).decode().rstrip("=")
            tok = "x." + carga + "." + "a" * 43
            sfl.guardar_token(tok)

            def falso(req, timeout=0):
                raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b"no"))

            sfl.urllib.request.urlopen = falso
            try:
                with self.assertRaises(SystemExit):
                    sfl.api_get("X", {"access_token": tok})
                self.assertFalse((pathlib.Path(tmp) / "token.bin").exists())
            finally:
                sfl.urllib.request.urlopen = urlopen
                sfl.time.sleep = dormir
                sfl.ruta_token = ruta


class PruebaCarpetaDatos(unittest.TestCase):
    def test_vacia(self):
        with self.assertRaises(SystemExit) as error:
            sfl.carpeta_de_datos("")
        self.assertIn("vacía", str(error.exception))

    def test_fichero_en_vez_de_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = pathlib.Path(tmp) / "fichero.txt"
            ruta.write_text("hola", encoding="utf-8")
            with self.assertRaises(SystemExit):
                sfl.carpeta_de_datos(str(ruta))


class PruebaErroresPanel(unittest.TestCase):
    def test_sin_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as error:
                sfl.generar_panel(pathlib.Path(tmp))
            self.assertIn("no encuentro", str(error.exception))

    def test_csv_vacio(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "library.csv").write_text("appid,name,source\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                sfl.generar_panel(d)
            self.assertIn("vacío", str(error.exception))

    def test_csv_sin_columna(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "library.csv").write_text("appid,name\n10,Juego\n", encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                sfl.generar_panel(d)
            self.assertIn("source", str(error.exception))


class PruebaHistorial(unittest.TestCase):
    def test_cabecera_en_fichero_vacio(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = pathlib.Path(tmp) / "historial.csv"
            ruta.write_text("", encoding="utf-8")
            sfl.anotar_historial(ruta, [{
                "evento": "nuevo", "appid": 1, "nombre": "X", "quien": "V", "propio": False,
            }], "2026-01-01 10:00")
            lineas = ruta.read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(lineas[0], "fecha,evento,appid,nombre,quien,propio")
            self.assertEqual(len(lineas), 2)

    def test_no_repite_el_mismo_evento_del_dia(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = pathlib.Path(tmp) / "historial.csv"
            eventos = [{"evento": "nuevo", "appid": 1, "nombre": "X", "quien": "V", "propio": False}]
            self.assertEqual(sfl.anotar_historial(ruta, eventos, "2026-01-01 10:00"), 1)
            self.assertEqual(sfl.anotar_historial(ruta, eventos, "2026-01-01 18:00"), 0)
            lineas = ruta.read_text(encoding="utf-8-sig").splitlines()
            self.assertEqual(len(lineas), 2)


class PruebaCandado(unittest.TestCase):
    def test_una_instancia_por_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            primero = sfl.bloquear_datos(tmp)
            try:
                with self.assertRaises(SystemExit):
                    sfl.bloquear_datos(tmp)
            finally:
                sfl.liberar_datos(primero)
            segundo = sfl.bloquear_datos(tmp)
            sfl.liberar_datos(segundo)


class PruebaPanel(unittest.TestCase):
    def test_genera_todo(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            columnas = ["appid", "name", "source", "playable", "exclude_reason",
                        "playtime_minutes", "acquired", "last_played", "store_url"]
            filas = [
                {"appid": "10", "name": "Mio", "source": "own", "playable": "True",
                 "exclude_reason": "", "playtime_minutes": "60", "acquired": "",
                 "last_played": "2026-01-01", "store_url": "u"},
                {"appid": "20", "name": "Prestado", "source": "family", "playable": "True",
                 "exclude_reason": "", "playtime_minutes": "0", "acquired": "2026-03-04",
                 "last_played": "", "store_url": "u"},
                {"appid": "30", "name": "Bloqueado", "source": "family", "playable": "False",
                 "exclude_reason": "excluido", "playtime_minutes": "0", "acquired": "",
                 "last_played": "", "store_url": "u"},
                {"appid": "40", "name": "__FECHA_NOV__", "source": "own", "playable": "True",
                 "exclude_reason": "", "playtime_minutes": "0", "acquired": "",
                 "last_played": "", "store_url": "u"},
            ]
            with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=columnas)
                w.writeheader()
                w.writerows(filas)

            snap = {"yo": "aaa", "fecha": "2026-11-21T10:00:00+00:00", "nombres": {"bbb": "V"},
                    "juegos": {"10": {"n": "Mio", "o": ["aaa"], "p": True, "v": "2026-01-01"},
                               "20": {"n": "Prestado", "o": ["bbb"], "p": True, "v": "2026-02-01"},
                               "30": {"n": "Bloqueado", "o": ["bbb"], "p": False, "v": "2026-02-01"}}}
            (d / "snapshot.json").write_text(json.dumps(snap), encoding="utf-8")

            resumen = sfl.generar_panel(d)
            self.assertEqual(resumen["prestados"], 2)

            html = (d / "panel.html").read_text(encoding="utf-8")
            self.assertIn("Prestado", html)
            self.assertIn("V", html)
            self.assertIn('"v":"2026-02-01"', html)
            self.assertIn('"q":"2026-03-04"', html)
            self.assertIn("Añadido", html)
            self.assertIn("const ACTUALIZADO = \"2026-11-21T10:00:00+00:00\"", html)
            self.assertIn("const SIN_NOMBRE = 0", html)
            self.assertIn('"n":"__FECHA_NOV__"', html)

            prestados = list(csv.DictReader((d / "prestados.csv").open(encoding="utf-8-sig")))
            self.assertEqual(len(prestados), 2)

            corta = (d / "prestados.txt").read_text(encoding="utf-8").split()
            self.assertEqual(corta, ["Prestado"])


class PruebaEstado(unittest.TestCase):
    def test_cuenta_bien(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            columnas = ["appid", "name", "source", "playable", "exclude_reason",
                        "playtime_minutes", "acquired", "last_played", "store_url"]
            filas = [
                {"appid": "10", "name": "Mio", "source": "own", "playable": "True",
                 "exclude_reason": "", "playtime_minutes": "60", "acquired": "",
                 "last_played": "", "store_url": "u"},
                {"appid": "20", "name": "Prestado", "source": "family", "playable": "True",
                 "exclude_reason": "", "playtime_minutes": "30", "acquired": "",
                 "last_played": "", "store_url": "u"},
            ]
            with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=columnas)
                w.writeheader()
                w.writerows(filas)

            snap = {"yo": "aaa", "juegos": {"10": {"o": ["aaa"], "p": True},
                                            "20": {"o": ["bbb"], "p": True}}}
            (d / "snapshot.json").write_text(json.dumps(snap), encoding="utf-8")

            e = sfl.estado(d)
            self.assertEqual(e["juegos"], 2)
            self.assertEqual(e["prestados"], 1)
            self.assertEqual(e["jugables"], 1)
            self.assertEqual(e["horas"], 0.5)
            self.assertEqual(e["sin_nombre"], 0)


class PruebaTokenGuardado(unittest.TestCase):
    def jwt(self, exp):
        carga = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
        return "x." + carga + ".y"

    def test_caduca_legible(self):
        self.assertTrue(sfl.caduca_token(self.jwt(1893456000)))

    def test_caducado_pasado(self):
        self.assertTrue(sfl.token_caducado(self.jwt(1000000000)))

    def test_no_caducado_futuro(self):
        self.assertFalse(sfl.token_caducado(self.jwt(2000000000)))

    def test_basura_se_trata_como_caducado(self):
        self.assertTrue(sfl.token_caducado("no.es.un.jwt"))

    @unittest.skipUnless(os.name == "nt", "DPAPI solo existe en Windows")
    def test_guardar_leer_y_olvidar(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                tok = self.jwt(2000000000)
                self.assertTrue(sfl.guardar_token(tok))
                self.assertEqual(sfl.leer_token(), tok)
                sfl.olvidar_token()
                self.assertIsNone(sfl.leer_token())
            finally:
                sfl.ruta_token = original

    @unittest.skipIf(os.name == "nt", "en Windows se usa DPAPI")
    def test_guardar_en_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                tok = self.jwt(2000000000)
                self.assertTrue(sfl.guardar_token(tok))
                self.assertEqual(sfl.leer_token(), tok)
                modo = pathlib.Path(tmp).joinpath("token.bin").stat().st_mode & 0o777
                self.assertEqual(modo, 0o600)
                sfl.olvidar_token()
                self.assertIsNone(sfl.leer_token())
            finally:
                sfl.ruta_token = original

    @unittest.skipUnless(os.name == "nt", "DPAPI solo existe en Windows")
    def test_no_guarda_un_token_caducado(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                sfl.guardar_token(self.jwt(1000000000))
                self.assertIsNone(sfl.leer_token())
            finally:
                sfl.ruta_token = original


class PruebaClaveGuardada(unittest.TestCase):
    def test_guardar_leer_y_olvidar(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                self.assertIsNone(sfl.leer_clave())
                self.assertTrue(sfl.guardar_clave("0123456789abcdef"))
                self.assertEqual(sfl.leer_clave(), "0123456789abcdef")
                self.assertTrue((pathlib.Path(tmp) / "apikey.bin").exists())
                sfl.olvidar_clave()
                self.assertIsNone(sfl.leer_clave())
            finally:
                sfl.ruta_token = original


if __name__ == "__main__":
    unittest.main()
