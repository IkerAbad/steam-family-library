"""Pruebas de las notas de release."""

import contextlib
import io
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

    def test_publica_la_guia_y_los_cambios(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            self.assertEqual(notas_release.main(["2.1.0"]), 0)
        texto = salida.getvalue()
        self.assertIn("steam-families", texto)
        self.assertIn("historial de novedades", texto)

    def test_version_sin_seccion(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            self.assertEqual(notas_release.main(["9.9.9"]), 0)
        self.assertIn("steam-families", salida.getvalue())
        self.assertNotIn("## 9.9.9", salida.getvalue())

    def test_uso(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(notas_release.main([]), 2)
        self.assertIn("uso:", error.getvalue())


if __name__ == "__main__":
    unittest.main()
