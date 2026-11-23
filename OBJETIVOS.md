# Objetivos

> Estado: los ocho primeros y las tandas segunda a décima están implementados.

## Décima tanda (3.0.0)

- Renovación guiada del token, con aviso en la interfaz local y en el panel.
- Cero pruebas saltadas por defecto: suites separadas por plataforma y navegador.
- Cobertura publicada y umbral del 90 %.
- ZIP de Windows sin Python en la release.

## Novena tanda (2.10.0)

- Operadores `fecha:`, `favorito:` y `oculto:`.
- Historial ordenable, con botón para limpiar sus filtros.
- Historial adaptado a móvil.
- Favorito y oculto en el JSON exportado.

## Octava tanda (2.9.0)

- Buscador por palabras en cualquier orden.
- Filtros del historial recordados.
- Cabeceras ordenables en las estadísticas por miembro.
- Fecha relativa, enlace de salto y botón para detener la app.

## Séptima tanda (2.8.0)

- Alias locales de los miembros, aplicados en toda la interfaz.
- Sección «Ya no están» con las bajas de la última actualización.
- Vista móvil con columnas secundarias ocultas.
- Rango `horas:1-2`, copiar nombres y horas propias en la cabecera.

## Sexta tanda (2.7.0)

- Notas por juego, con búsqueda y filtros `nota:si` y `nota:no`.
- Notas en la copia de ajustes y en el JSON exportado.
- Descargar todo en ZIP desde la interfaz.
- Recarga automática del panel tras una actualización.
- Impresión limpia y ayuda de atajos con `?`.

## Quinta tanda (2.6.0)

- Historial recordado entre visitas.
- Exportar historial en JSON y miembros en CSV.
- Operadores `appid:`, `mes:` y `ultima:`.
- Meses clicables y enlace de la vista con los filtros.

## Cuarta tanda (2.5.0)

- Intervalo de actualización desde el panel, con `ajustes.json`.
- Exportar la vista filtrada en JSON.
- Vista compacta recordada y copia del resumen.
- Top 10 de los más jugados y filtro al pulsar un miembro.
- Contador de novedades en el título.
- Botón «Sorpréndeme» y limpieza completa de filtros.

## Tercera tanda (2.4.0)

- Operadores `origen:`, `estado:` y `dueno:` en el buscador.
- El orden por cabecera se guarda entre visitas.
- Tema reactivo también en la interfaz local.
- Etiquetas accesibles y prueba automática.
- Fila de totales por miembro.

## Segunda tanda (2.3.0)

- Historial paginado con «Mostrar más».
- Barra de horas por miembro.
- Tema que sigue al sistema si no hay elección manual.
- Atajos `/` y `Escape`.
- Búsqueda avanzada `horas:>10`, `horas:<2`, `anio:2026`.

## Primera tanda (2.2.0)

Ordenados por valor para quien usa el programa. Cada uno con su criterio de
aceptación para saber cuándo está terminado.

## 1. Historial con búsqueda y filtros

El historial ya existe, pero solo se puede mirar. Añadir búsqueda por juego o
miembro, filtro por tipo (nuevo, fuera, otro dueño) y por fecha, reutilizando
los controles del panel.

- Aceptación: la tabla del historial responde a los filtros y a los dos idiomas,
  y hay prueba de navegador.

## 2. Actualización automática mientras la app está abierta

Hoy se actualiza al abrir. Con el token guardado, repetir cada 6 horas
(configurable) y refrescar el panel sin recargar la pestaña.

- Aceptación: con un Steam falso, dos ciclos seguidos actualizan sin pulsar
  nada; si el token caduca, se avisa y se deja de intentar.

## 3. Estadísticas por miembro

Sección con juegos prestados, horas y jugables por cada miembro del grupo.

- Aceptación: los totales cuadran con la tabla; funciona en ES/EN y con nombres
  sin resolver.

## 4. Favoritos y ocultos

Marcar juegos con estrella y ocultar los que no interesan, guardado en el
navegador. Filtros «favoritos» y «ocultos», y que la vista filtrada se pueda
exportar.

- Aceptación: sobrevive a la recarga, se puede quitar la marca y no rompe el
  orden ni la búsqueda.

## 5. Altas por mes

Gráfico de barras de los juegos añadidos en los últimos 12 meses, sin librerías.

- Aceptación: las barras cuadran con las fechas de `library.csv` y se leen con
  el ratón y con el teclado.

## 6. Exportar la vista filtrada

Botón que descarga un CSV con las filas que se están viendo ahora mismo,
incluidos los filtros y el orden.

- Aceptación: el CSV abre en Excel, tiene las mismas columnas que
  `library.csv` y el nombre lleva la fecha.

## 7. Tema claro

Alternar claro/oscuro, recordar la elección y respetar `prefers-color-scheme`
la primera vez.

- Aceptación: contraste suficiente en las dos lenguas y en los avisos de color.

## 8. Cobertura por encima del 85 %

Medir con `coverage`, cubrir las ramas que faltan del servidor y de los
mensajes de error, y publicar el informe en el CI.

- Aceptación: el job de pruebas imprime la cobertura y falla por debajo del
  umbral acordado.

## Descartado por ahora

- **Precios e historial de precios**: la API de la tienda no da histórico y
  pedir precios de 1386 juegos multiplica las peticiones.
- **Cookies de sesión** para renovar el token: rompe la promesa de no guardar
  cookies.
