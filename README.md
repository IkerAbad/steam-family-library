# steam-family-library

Script de un solo archivo que exporta la biblioteca de Steam completa: los juegos que has comprado y los que te comparte tu familia con Steam Families. Genera un JSON y un CSV con el dueño de cada título.

## Por qué existe

El endpoint público `IPlayerService/GetOwnedGames` solo devuelve los juegos que has comprado. No hay ningún parámetro que cambie eso: los juegos compartidos le son invisibles.

Los juegos que puedes jugar de verdad están detrás de otro endpoint, no documentado:

```
IFamilyGroupsService/GetSharedLibraryApps/v1
```

Con `include_own=true` devuelve la biblioteca familiar fusionada en una sola llamada y dice qué miembro es dueño de cada título.

El cliente de Steam no tiene un filtro para ver solo lo prestado, así que la alternativa práctica es exportar y filtrar la columna `source` (`own` / `family`).

## Requisitos

Python 3.8 o superior. Sin dependencias externas.

## Conseguir el token

`GetSharedLibraryApps` no acepta una API key normal de desarrollador. Necesita el `webapi_token` de una sesión web ya iniciada.

1. Inicia sesión en Steam en el navegador.
2. Abre `https://store.steampowered.com/pointssummary/ajaxgetasyncconfig`.
3. Copia el valor de `webapi_token` (dentro de `data`).

Es un JWT válido unas 24 horas y lleva tu SteamID64 dentro, así que no hay que buscar nada más.

## Uso

PowerShell:

```
$env:STEAM_WEBAPI_TOKEN='eyJ0eXAi...'
python steam_family_library.py --include-free
```

Bash:

```
export STEAM_WEBAPI_TOKEN='eyJ0eXAi...'
python3 steam_family_library.py --include-free
```

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--json PATH` | `library.json` | Ruta del JSON |
| `--csv PATH` | `library.csv` | Ruta del CSV |
| `--include-free` | desactivado | Incluye juegos free-to-play |
| `--include-non-games` | desactivado | Incluye herramientas, bandas sonoras y demos |
| `--token TOKEN` | `$STEAM_WEBAPI_TOKEN` | Token en línea |

## Salida

`library.csv` se escribe en UTF-8 con BOM para que Excel respete los acentos, con una fila por juego ordenado por nombre:

```csv
appid,name,source,playable,exclude_reason,playtime_minutes,acquired,last_played,store_url
242820,140,family,True,,0,2021-06-04,,https://store.steampowered.com/app/242820
```

Campos que conviene entender:

- `source`: `own` si lo has comprado tú, `family` si viene de otro miembro. Un juego que tenéis dos se marca `own`.
- `playable` y `exclude_reason`: los compartidos pueden estar bloqueados (excluido por el dueño, no elegible para compartir, restricción regional o de DRM).
- `playtime_minutes` y `last_played` son tus horas, no las del dueño.

`library.json` lleva lo mismo más `owner_steamids`, la lista de miembros que poseen cada juego.

Filtrar solo lo prestado es una línea:

```python
import csv
rows = list(csv.DictReader(open("library.csv", encoding="utf-8")))
prestados = [r for r in rows if r["source"] == "family"]
```

## Privacidad

`library.json` contiene tu SteamID64 y los de todos los miembros de tu grupo familiar. Trátalo como dato personal: el `.gitignore` de este repo ya lo excluye, junto con los CSV generados y cualquier fichero de token.

## Limitaciones

- El endpoint no está documentado. Valve puede cambiarlo sin avisar.
- No devuelve géneros, etiquetas, notas ni fechas de lanzamiento. Para eso hace falta una segunda pasada sobre `store.steampowered.com/api/appdetails`, limitada a unas 200 peticiones cada 5 minutos.
- Solo funciona con Steam Families. Si tu cuenta sigue en el sistema antiguo de préstamo familiar, no hay nada que leer.

## Créditos

Basado en [salah153/steam-family-library](https://github.com/salah153/steam-family-library), bajo licencia MIT. Ver `LICENSE`.
