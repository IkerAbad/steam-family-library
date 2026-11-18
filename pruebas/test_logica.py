"""Pruebas de la logica, sin red.

    python -m unittest discover -s pruebas -v
"""

import csv
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import app  # noqa: E402
import panel  # noqa: E402
import steam_family_library as sfl  # noqa: E402


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


class PruebaNombres(unittest.TestCase):
    def test_rellena_huecos_sin_tocar_el_tuyo(self):
        alias = sfl.rellenar_huecos({"bbb": "V"}, ["bbb", "ccc", "ddd"], "aaa")
        self.assertEqual(alias["bbb"], "V")
        self.assertEqual(alias["ccc"], "Miembro 1")
        self.assertEqual(alias["ddd"], "Miembro 2")
        self.assertNotIn("aaa", alias)


class PruebaChivato(unittest.TestCase):
    def test_texto_legible(self):
        eventos = [
            {"evento": "nuevo", "nombre": "Juego", "quien": "V", "propio": False, "gratis": True},
            {"evento": "fuera", "nombre": "Otro", "quien": "M", "propio": False},
            {"evento": "nuevo", "nombre": "Mio", "quien": "", "propio": True},
        ]
        texto = sfl.chivato(eventos, "2026-01-01 10:00")
        self.assertIn("+ Juego  (de V)  [gratis]", texto)
        self.assertIn("- Otro  (ya no esta; era de M)", texto)
        self.assertIn("+ Mio  (de ti)", texto)

    def test_sin_eventos(self):
        self.assertIn("Sin cambios", sfl.chivato([], "2026-01-01"))


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
            ]
            with (d / "library.csv").open("w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=columnas)
                w.writeheader()
                w.writerows(filas)

            snap = {"yo": "aaa", "nombres": {"bbb": "V"},
                    "juegos": {"10": {"n": "Mio", "o": ["aaa"], "p": True, "v": "2026-01-01"},
                               "20": {"n": "Prestado", "o": ["bbb"], "p": True, "v": "2026-02-01"},
                               "30": {"n": "Bloqueado", "o": ["bbb"], "p": False, "v": "2026-02-01"}}}
            (d / "snapshot.json").write_text(json.dumps(snap), encoding="utf-8")

            r = subprocess.run([sys.executable, str(RAIZ / "panel.py"), "--datos", str(d)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

            html = (d / "panel.html").read_text(encoding="utf-8")
            self.assertIn("Prestado", html)
            self.assertIn("V", html)
            self.assertIn('"v":"2026-02-01"', html)
            self.assertIn('"q":"2026-03-04"', html)
            self.assertIn("Anadido", html)

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

            e = app.estado(d)
            self.assertEqual(e["juegos"], 2)
            self.assertEqual(e["prestados"], 1)
            self.assertEqual(e["jugables"], 1)
            self.assertEqual(e["horas"], 0.5)


if __name__ == "__main__":
    unittest.main()
