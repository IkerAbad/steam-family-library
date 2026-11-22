# Cambios

## 2.2.5 — 2026-11-22

- Guardar y cargar los ajustes del panel: favoritos, ocultos, tema, idioma y filtros.

## 2.2.4 — 2026-11-22

- Binario de macOS Intel (`steam-families-macos-intel`), además del de Apple Silicon.

## 2.2.3 — 2026-11-22

- Tema claro y oscuro también en la interfaz local.

## 2.2.2 — 2026-11-22

- Filtro por dueño en el panel.

## 2.2.1 — 2026-11-22

- La búsqueda del panel mira también el dueño.
- El historial filtrado se puede descargar en CSV.

## 2.2.0 — 2026-11-22

- Historial con búsqueda, tipo y rango de fechas.
- Actualización automática cada 6 horas mientras la app está abierta (`--cada`).
- Estadísticas por miembro: juegos, jugables y horas.
- Favoritos y juegos ocultos, con sus filtros.
- Gráfico de altas de los últimos 12 meses.
- Exportar la vista filtrada a CSV.
- Tema claro y oscuro, con `prefers-color-scheme`.
- Cobertura del 86 % medida en el CI.

## 2.1.1 — 2026-11-22

- Los binarios de Linux y macOS ya no se pisan al publicar la release.
- Las notas de la release salen del changelog y de la guía de instalación.

## 2.1.0 — 2026-11-22

- El panel incluye el historial de novedades (últimas 500), con fecha, juego, qué y quién.

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
