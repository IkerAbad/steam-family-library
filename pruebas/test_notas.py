"""Pruebas de las notas de release."""

import pathlib
import sys
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import notas_release  # noqa: E402


class PruebaNotas(unittest.TestCase):
    def test_seccion_del_changelog(self):
        texto = notas_release.seccion("2.1.0")
        self.assertIn("historial de novedades", texto)
        self.assertNotIn("El servidor lee", texto)

    def test_version_inexistente(self):
        self.assertEqual(notas_release.seccion("9.9.9"), "")


if __name__ == "__main__":
    unittest.main()
