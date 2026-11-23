"""Pruebas que solo tienen sentido en Windows.

Se ejecutan en el workflow de Windows:

    python -m unittest discover -s pruebas_plataforma -p "test_windows.py" -v
"""

import base64
import json
import pathlib
import sys
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import steam_families as sfl  # noqa: E402


def jwt(exp):
    carga = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return "x." + carga + ".y"


class PruebaWindows(unittest.TestCase):
    def test_rechaza_comilla_colada(self):
        with self.assertRaises(SystemExit):
            sfl.carpeta('C:\\una\\ruta"')

    def test_guardar_leer_y_olvidar(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                tok = jwt(2000000000)
                self.assertTrue(sfl.guardar_token(tok))
                self.assertEqual(sfl.leer_token(), tok)
                estado = sfl.estado_token()
                self.assertTrue(estado["guardado"])
                self.assertFalse(estado["caducado"])
                sfl.olvidar_token()
                self.assertIsNone(sfl.leer_token())
            finally:
                sfl.ruta_token = original

    def test_no_carga_un_token_caducado(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                sfl.guardar_token(jwt(1000000000))
                self.assertIsNone(sfl.leer_token())
                estado = sfl.estado_token()
                self.assertTrue(estado["guardado"])
                self.assertTrue(estado["caducado"])
            finally:
                sfl.ruta_token = original


if __name__ == "__main__":
    unittest.main()
