"""Pruebas que solo tienen sentido en Linux y macOS.

Se ejecutan en el workflow de Linux:

    python -m unittest discover -s pruebas_plataforma -p "test_posix.py" -v
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


class PruebaPosix(unittest.TestCase):
    def test_guardar_en_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = sfl.ruta_token
            sfl.ruta_token = lambda: pathlib.Path(tmp) / "token.bin"
            try:
                tok = jwt(2000000000)
                self.assertTrue(sfl.guardar_token(tok))
                self.assertEqual(sfl.leer_token(), tok)
                modo = pathlib.Path(tmp).joinpath("token.bin").stat().st_mode & 0o777
                self.assertEqual(modo, 0o600)
                estado = sfl.estado_token()
                self.assertTrue(estado["guardado"])
                self.assertFalse(estado["caducado"])
                sfl.olvidar_token()
                self.assertIsNone(sfl.leer_token())
            finally:
                sfl.ruta_token = original


if __name__ == "__main__":
    unittest.main()
