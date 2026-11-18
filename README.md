# steam-family-library

Exporta tu biblioteca familiar de Steam, separa lo que te prestan de lo que es tuyo y detecta qué ha entrado nuevo desde la última vez. Sin instalar nada más que Python, con una interfaz local en el navegador.

Steam fusiona todas las bibliotecas del grupo y no ofrece ningún filtro para ver solo lo prestado. Este programa sí.

## Lo que hace

- **Biblioteca completa**: todos los juegos que el grupo puede jugar, con la etiqueta `own` (tuyo) o `family` (de otro).
- **Filtro de prestados**: qué no es tuyo, si se puede jugar ahora y por qué no.
- **Novedades**: compara con la ejecución anterior y avisa de juegos nuevos, juegos que desaparecen y juegos que pasa a tener otro miembro.
- **Nombres**: resuelve el alias de cada miembro, sin API key.
- **Panel**: buscador sin acentos, filtros por origen y estado, orden por horas o última sesión, enlaces a la tienda.

## Empezar

1. Instala [Python 3.8 o superior](https://www.python.org/downloads/). En Windows, marca «Add python.exe to PATH».
2. Doble clic en `iniciar.cmd`. Se abre una página en `127.0.0.1`.
3. Pega el token (abajo se explica cómo) y pulsa **Actualizar**.

Todo queda en tu ordenador. No hay servidor, no hay cuenta, no hay telemetría.

### El token

1. Con la sesión de Steam abierta en el navegador, entra en `https://store.steampowered.com/pointssummary/ajaxgetasyncconfig`.
2. Copia el valor de `webapi_token` (dentro de `data`).
3. Pégalo en la interfaz.

Es un JWT que caduca a las 24 horas. No se guarda en ningún fichero: vive en memoria mientras dura la consulta.

## Qué genera

| Fichero | Contenido |
|---|---|
| `panel.html` | Panel completo, un solo fichero, sin conexión |
| `library.csv` | Biblioteca entera con la columna `source` |
| `prestados.csv` / `prestados.txt` | Solo lo que te prestan |
| `novedades.txt` / `novedades.json` | Lo que cambió en la última ejecución |
| `historial.csv` | Una fila por novedad, con fecha |
| `snapshot.json` | Retrato de la biblioteca para poder comparar |

Los CSV van en UTF-8 con BOM para que Excel respete los acentos.

## Uso desde la terminal

```
$env:STEAM_WEBAPI_TOKEN = "eyJ0eXAi..."
python steam_family_library.py --datos .
python panel.py --datos .
```

Opciones de `steam_family_library.py`:

| Opción | Para qué |
|---|---|
| `--datos RUTA` | Carpeta de salida (por defecto, la actual) |
| `--token TOKEN` | Token en línea, sin variable de entorno |
| `--api-key CLAVE` | API key opcional de Steam, resuelve nombres sin límites |
| `--include-free` | Incluye free-to-play |
| `--include-non-games` | Incluye herramientas, bandas sonoras y demos |
| `--sin-nombres` | No consulta alias (más rápido) |
| `--sin-historial` | No toca snapshot, novedades ni historial |

La API key es opcional y se saca gratis en `https://steamcommunity.com/dev/apikey`. Sin ella, los nombres salen del endpoint de la comunidad de Steam, que a veces responde 429 y deja «Miembro 1», «Miembro 2» hasta la siguiente ejecución.

## Cómo funciona

1. El token es un JWT firmado por Steam; su campo `sub` es tu SteamID64 y `exp` la caducidad.
2. `IFamilyGroupsService/GetFamilyGroupForUser` devuelve el id del grupo y sus miembros.
3. `IFamilyGroupsService/GetSharedLibraryApps` con `include_own=true` devuelve todas las apps del grupo con `owner_steamids`, `exclude_reason` y `rt_playtime`.
4. Si tu SteamID está entre los dueños, el juego es `own`; si no, `family`.
5. `panel.py` incrusta los datos en un HTML y filtra en JavaScript.
6. Las novedades son una comparación entre el `snapshot.json` anterior y el actual.

Los tres endpoints de familia están sin documentar. Funcionan hoy y pueden cambiar mañana.

## Privacidad

- No se sube nada a ningún sitio.
- El token no se escribe en disco.
- `snapshot.json`, `historial.csv` y `novedades.*` guardan los SteamID convertidos en un hash de 10 caracteres, no los IDs reales. Los ficheros de datos están en `.gitignore`, igual que `library.csv`, `panel.html` y `prestados.*`.
- Si compartes el panel, compartes la lista de juegos y tus horas jugadas. No lleva identificadores de nadie.

## Límites

- Hay que repetir el token cada 24 horas.
- Los free-to-play cuentan como biblioteca: un juego gratis reclamado también sale como novedad.
- «Comprado», «key» y «regalo» no se distinguen: el endpoint solo dice que alguien lo tiene.
- `rt_time_acquired` no se usa para fechar compras porque su significado no está documentado.
- Los juegos excluidos del préstamo por su dueño aparecen como bloqueados, no desaparecen.

## Créditos

Basado en [salah153/steam-family-library](https://github.com/salah153/steam-family-library). MIT, ver `LICENSE`.
