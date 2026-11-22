# Objetivos

> Estado: los ocho están implementados en `main`, pendientes de etiquetar.

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
