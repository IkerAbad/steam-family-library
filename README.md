# Steam Families

[![Linux](https://github.com/IkerAbad/steam-family-library/actions/workflows/linux.yml/badge.svg)](https://github.com/IkerAbad/steam-family-library/actions/workflows/linux.yml)
[![Windows](https://github.com/IkerAbad/steam-family-library/actions/workflows/windows.yml/badge.svg)](https://github.com/IkerAbad/steam-family-library/actions/workflows/windows.yml)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)

Ve qué juegos te presta tu familia en Steam, cuáles son tuyos y qué ha entrado nuevo desde la última vez. Un solo archivo de Python, sin dependencias, con interfaz en el navegador.

Steam fusiona todas las bibliotecas del grupo y no tiene ningún filtro para separarlas. Esto sí.

## Empezar

1. Instala [Python 3.8 o superior](https://www.python.org/downloads/). En Windows, marca «Add python.exe to PATH».
2. Windows: doble clic en `iniciar.cmd`. Linux o macOS: `chmod +x iniciar.sh && ./iniciar.sh`.
3. Se abre una página en `127.0.0.1`. Pega el token la primera vez; a partir de ahí se guarda cifrado y la app se actualiza sola hasta que caduque.

### El token

1. Abre `https://store.steampowered.com/pointssummary/ajaxgetasyncconfig` con la sesión de Steam iniciada.
2. Copia el valor de `webapi_token`. Vale el token suelto o el JSON entero.
3. Pégalo en la interfaz.

En la propia página hay un marcador **Copiar token** que lo deja en el portapapeles de un clic, y un botón **Pegar**.

## Qué genera

| Fichero | Contenido |
|---|---|
| `panel.html` | Panel completo en un solo fichero, sin conexión |
| `library.csv` | Biblioteca entera con la columna `source` (`own` / `family`) |
| `prestados.csv`, `prestados.txt` | Solo lo que te prestan |
| `novedades.txt`, `novedades.json` | Lo que cambió en la última ejecución |
| `historial.csv` | Una fila por novedad, con fecha |
| `snapshot.json` | Retrato de la biblioteca para poder comparar |

El panel trae buscador sin acentos, filtros por origen, estado y antigüedad, columna **Añadido** con la fecha de adquisición, marca **nuevo**, marca **gratis** y el atajo **Compras de la familia (90 días)**. La interfaz y el panel están en español y en inglés: el botón **ES / EN** de la esquina cambia el idioma y la elección se recuerda. Los ficheros de datos (`novedades.txt`, `prestados.txt`) siguen en español.

Los CSV van en UTF-8 con BOM para que Excel respete los acentos.

## Seguridad

- **Ninguna cookie.** No lee, no pide y no guarda cookies de Steam.
- El token se guarda cifrado con DPAPI en `%LOCALAPPDATA%\SteamFamilies\token.bin`. Solo tu usuario de Windows puede descifrarlo y caduca solo en 24 h. Hay un enlace **olvidar**.
- Nada sale de tu equipo: las únicas conexiones son a `api.steampowered.com` y `steamcommunity.com`.
- El servidor local escucha solo en `127.0.0.1` y rechaza peticiones de otras webs por `Origin`.
- Los SteamID se guardan como un hash de 10 caracteres, nunca en claro. Los ficheros de datos están en `.gitignore`.

## Terminal

```
python steam_families.py                      # interfaz en el navegador
python steam_families.py --exportar --token X # exporta sin interfaz
python steam_families.py --panel              # solo regenera el panel
```

Opciones: `--datos`, `--api-key`, `--include-free`, `--include-non-games`, `--sin-nombres`, `--sin-historial`, `--sin-precios`, `--puerto`, `--sin-navegador`.

## Cómo funciona

1. El token es un JWT firmado por Steam; su campo `sub` es tu SteamID64 y `exp` la caducidad.
2. `IFamilyGroupsService/GetFamilyGroupForUser` devuelve el grupo y sus miembros.
3. `IFamilyGroupsService/GetSharedLibraryApps` con `include_own=true` devuelve todas las apps con `owner_steamids`, `exclude_reason` y `rt_playtime`.
4. Si tu SteamID está entre los dueños, el juego es `own`; si no, `family`.
5. Las novedades son la diferencia entre el `snapshot.json` anterior y el actual.

Los tres endpoints de familia están sin documentar: funcionan hoy y pueden cambiar mañana.

## Límites

- El token caduca cada 24 horas. Sin guardar una cookie de sesión no hay forma de renovarlo solo, y guardar cookies queda descartado.
- Los free-to-play cuentan como biblioteca: un juego gratis reclamado también sale como novedad.
- «Comprado», «key» y «regalo» no se distinguen: el endpoint solo dice que alguien lo tiene.
- `rt_time_acquired` se usa como fecha de adquisición porque cuadra con compras reales, pero Valve no documenta su significado exacto.

## Desarrollo

```
python -m unittest discover -s pruebas -v
```

23 pruebas sin red. GitHub Actions ejecuta además la interfaz completa en Ubuntu 22.04 con Python 3.8, Ubuntu latest con 3.12 y Windows con 3.9 y 3.12, incluido el lanzador `.cmd`.

## Créditos

Basado en [salah153/steam-family-library](https://github.com/salah153/steam-family-library). MIT, ver `LICENSE`.
