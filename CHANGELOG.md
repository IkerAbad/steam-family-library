# Cambios

## 2.0.1 — 2026-11-22

- El servidor lee y descarta el cuerpo antes de responder 413: en Windows ya no corta la conexión.
- README con badge de release y la vía sin Python.

## 2.0.0 — 2026-11-22

- Interfaz y panel en español e inglés, con la elección recordada.
- Nombres de los miembros: API key opcional, resolución uno a uno con reintentos, refresco semanal y conservación del último nombre bueno.
- Datos en `datos/`, escrituras atómicas y una sola instancia por carpeta.
- Historial sin eventos repetidos del mismo día.
- Panel: fecha de actualización con aviso de datos viejos, aviso de miembros sin nombre, filtros y orden recordados, cabeceras ordenables con ratón y teclado.
- Seguridad: token y API key cifrados y nunca enviados a la página; comprobación de `Host` y `Origin`; CSP.
- Empaquetado con PyInstaller para Windows y Linux.
- 99 pruebas, con integración contra un Steam falso y pruebas de navegador con Playwright.

Versiones anteriores: ver los tags `v1.0.0` y `v1.0.1`.
