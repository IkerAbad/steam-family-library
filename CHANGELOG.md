# Cambios

## 3.1.2 — 2026-11-25

- La interfaz y los mensajes salen en inglés por defecto. El español sigue
  disponible desde el selector de idioma.
- El atributo `lang` del documento y el título de la página siguen al idioma
  elegido.

## 3.1.1 — 2026-11-25

- Corregido un fallo que rompía la actualización automática al arrancar: el
  intervalo se leía de `type(Handler).cada` en lugar de `Handler.cada`, así que
  el hilo periódico lanzaba `AttributeError` y se cerraba.
- Sin cambios de comportamiento en el resto.

## 3.1.0 — 2026-11-23

- El proyecto incluye `pyproject.toml`: se puede instalar con `pip install .` y
  ejecutar con el comando `steam-families`, con las mismas opciones que el
  script.
- La distribución se llama `steam-families-library` y está publicada en PyPI.
- Sin cambios de comportamiento.

## 3.0.1 — 2026-11-23

- Pruebas de los endpoints HTTP y de los caminos de error de la app.
- Cobertura al 93 % en `steam_families.py` (96 % en `empaquetar.py` y `notas_release.py`).
- Sin cambios visibles: la renovación guiada sigue igual que en 3.0.0.

## 3.0.0 — 2026-11-23

- Renovación guiada del token: se detecta la caducidad al arrancar y cada minuto, se explica el motivo y se enlaza la página oficial. El token caducado ya no se borra en silencio.
- El panel también avisa cuando el token ha caducado o caduca pronto.
- La suite deja de saltarse pruebas: 151 comunes, 58 de navegador y 4 de plataforma, cada una en su workflow.
- Cobertura publicada como `htmlcov` y `coverage.xml`: 91 % de `steam_families.py`, 96 % de `empaquetar.py` y 96 % de `notas_release.py`.
- La release incluye `steam-families.zip` para Windows sin Python.

## 2.10.0 — 2026-11-23

- Operador `fecha:` con `>`, `<` y rangos `2026-01-01..2026-06-30` sobre la fecha de alta.
- Operadores `favorito:si|no` y `oculto:si|no`; `oculto:si` enseña los ocultos aunque la casilla esté apagada.
- Historial ordenable por fecha, juego, tipo o quién, con flecha y `aria-sort`.
- Botón «Limpiar filtros» en el historial.
- Historial adaptado a móvil: se oculta la columna de quién y la fecha no se solapa.
- El JSON exportado incluye `favorite` y `hidden`.

## 2.9.0 — 2026-11-23

- Buscador por palabras en cualquier orden: «ana beta» y «beta ana» encuentran lo mismo.
- El historial recuerda sus filtros entre visitas.
- Las estadísticas por miembro se ordenan pulsando sus cabeceras.
- «Actualizado» muestra el tiempo relativo («hace 2 h»).
- Enlace «Saltar a la tabla» para navegar con teclado.
- «Detener la app» desde el panel cuando se sirve desde la propia app.

## 2.8.0 — 2026-11-23

- Nombres locales para los miembros: se editan desde «Por miembro» y valen en la tabla, los filtros y las estadísticas.
- Sección «Ya no están» con los juegos que salieron en la última actualización.
- Vista móvil: columnas secundarias ocultas y controles apilados en pantallas estrechas.
- Rango de horas en el buscador: `horas:1-2`.
- Botón «Copiar nombres» con la lista de la vista filtrada.
- Las horas de tus propios juegos aparecen en la cabecera cuando hay alguna.

## 2.7.0 — 2026-11-23

- Notas por juego: se crean, se editan, se borran, se buscan y se filtran con `nota:si` y `nota:no`.
- Las notas van en la copia de ajustes y en el JSON exportado.
- Descargar todo en un ZIP desde la interfaz local.
- El panel se recarga solo cuando la app termina una actualización.
- Botón e hoja de estilo para imprimir o guardar en PDF.
- Ayuda de atajos y operadores con `?`.

## 2.6.0 — 2026-11-23

- El historial recuerda si lo dejaste abierto.
- Exportar el historial en JSON, con los filtros aplicados.
- Exportar la tabla por miembro en CSV.
- Operadores `appid:`, `mes:` y `ultima:` (`<30`, `>365`, `never`).
- Las barras de altas por mes filtran ese mes al pulsarlas.
- Los filtros se guardan en la dirección y «Copiar enlace» comparte la vista exacta.

## 2.5.0 — 2026-11-22

- Intervalo de actualización automática configurable desde el panel, guardado en `ajustes.json`.
- La copia de ajustes incluye la vista compacta y el intervalo.
- Exportar la vista filtrada en JSON.
- Vista compacta, recordada entre visitas.
- Top 10 de los juegos más jugados.
- Pulsar un miembro en las estadísticas filtra la tabla por él.
- Copiar el resumen al portapapeles.
- Contador de novedades en el título de la pestaña, con título traducido.
- Botón «Sorpréndeme»: elige un juego al azar de la vista filtrada.
- «Limpiar filtros» ahora también resetea dueño, favoritos y ocultos.

## 2.4.0 — 2026-11-22

- Búsqueda por operadores: `origen:`, `estado:` y `dueno:`.
- El orden por cabecera se recuerda entre visitas.
- El tema de la interfaz local también sigue al sistema.
- Etiquetas accesibles en buscadores y campos del token, con prueba automática.
- Fila de totales en las estadísticas por miembro.

## 2.3.0 — 2026-11-22

- Historial paginado: 100 novedades y botón «Mostrar más».
- Barra de horas por miembro en las estadísticas.
- El tema sigue al sistema si no has elegido uno a mano.
- Atajos: `/` enfoca el buscador y `Escape` lo limpia.
- Búsqueda avanzada: `horas:>10`, `horas:<2` y `anio:2026`.

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
