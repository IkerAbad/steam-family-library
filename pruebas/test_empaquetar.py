"""Pruebas del empaquetador, sin llamar de verdad a PyInstaller."""

import pathlib
import sys
import unittest
from unittest import mock

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import empaquetar  # noqa: E402


class PruebaEmpaquetar(unittest.TestCase):
    def test_falta_pyinstaller(self):
        with mock.patch.dict(sys.modules, {"PyInstaller": None}), \
             mock.patch("sys.argv", ["empaquetar.py"]):
            self.assertEqual(empaquetar.main(), 1)

    def test_empaqueta(self):
        with mock.patch.dict(sys.modules, {"PyInstaller": mock.Mock()}), \
             mock.patch("empaquetar.subprocess.call", return_value=0) as llamada, \
             mock.patch("empaquetar.shutil.rmtree") as limpiar, \
             mock.patch("sys.argv", ["empaquetar.py", "--nombre", "prueba"]):
            self.assertEqual(empaquetar.main(), 0)
            argumentos = llamada.call_args[0][0]
            self.assertIn("--onefile", argumentos)
            self.assertIn("--name", argumentos)
            self.assertIn("prueba", argumentos)
            limpiar.assert_called_once()

    def test_pyinstaller_falla(self):
        with mock.patch.dict(sys.modules, {"PyInstaller": mock.Mock()}), \
             mock.patch("empaquetar.subprocess.call", return_value=1), \
             mock.patch("empaquetar.shutil.rmtree") as limpiar, \
             mock.patch("sys.argv", ["empaquetar.py"]):
            self.assertEqual(empaquetar.main(), 1)
            limpiar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
