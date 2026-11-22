# Steam Families

[![Linux](https://github.com/IkerAbad/steam-family-library/actions/workflows/linux.yml/badge.svg)](https://github.com/IkerAbad/steam-family-library/actions/workflows/linux.yml)
[![Windows](https://github.com/IkerAbad/steam-family-library/actions/workflows/windows.yml/badge.svg)](https://github.com/IkerAbad/steam-family-library/actions/workflows/windows.yml)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)
[![Interfaz](https://github.com/IkerAbad/steam-family-library/actions/workflows/interfaz.yml/badge.svg)](https://github.com/IkerAbad/steam-family-library/actions/workflows/interfaz.yml)

Ve qué juegos te presta tu familia en Steam, cuáles son tuyos y qué ha entrado nuevo desde la última vez. Un solo archivo de Python, sin dependencias, con interfaz en el navegador.

![Panel](docs/panel.png)

Steam fusiona todas las bibliotecas del grupo y no tiene ningún filtro para separarlas. Esto sí.

## Empezar

1. Instala [Python 3.8 o superior](https://www.python.org/downloads/). En Windows, marca «Add python.exe to PATH».
2. Windows: doble clic en `iniciar.cmd`. Linux o macOS: `chmod +x iniciar.sh && ./iniciar.sh`. Los datos se guardan en la subcarpeta `datos/`.
3. Se abre una página en `127.0.0.1`. Pega el token la primera vez; a partir de ahí se guarda cifrado y la app se actualiza sola hasta que caduque.

Solo puede haber una ventana usando la misma carpeta de datos. Si abres otra, avisa y se cierra.

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
| `historial.csv` | Una fila por novedad y día, sin repetir el mismo evento si actualizas dos veces |
| `snapshot.json` | Retrato de la biblioteca para poder comparar |

Todos se escriben en la subcarpeta `datos/`, que el lanzador pasa con `--datos`.

El panel trae buscador sin acentos, filtros por origen, estado y antigüedad, columna **Añadido** con la fecha de adquisición, marca **nuevo**, marca **gratis** y el atajo **Añadidos (90 días)**. La interfaz y el panel están en español y en inglés: el botón **ES / EN** de la esquina cambia el idioma y la elección se recuerda. `novedades.txt` se escribe en el idioma de la interfaz; `historial.csv` mantiene las columnas en español.

Debajo del título, el panel muestra la fecha de la última actualización y la pone en ámbar si tiene más de un día. También avisa si algún miembro sigue como «Miembro N», con enlace a la API key. Recuerda los filtros y el orden, y ordena al pulsar una cabecera.

Los CSV van en UTF-8 con BOM para que Excel respete los acentos.

## Seguridad

- **Ninguna cookie.** No lee, no pide y no guarda cookies de Steam.
- El token se guarda cifrado con DPAPI en `%LOCALAPPDATA%\SteamFamilies\token.bin`. Solo tu usuario de Windows puede descifrarlo y caduca solo en 24 h. Hay un enlace **olvidar**.
- La API key, si la pegas, se guarda igual en `apikey.bin`, en la misma carpeta. **olvidar** borra los dos.
- El token y la API key **no se envían a la página**: el servidor los usa y la interfaz solo sabe si están guardados.
- Nada sale de tu equipo: las únicas conexiones son a `api.steampowered.com` y `steamcommunity.com`.
- El servidor local escucha solo en `127.0.0.1`, comprueba el `Host` y rechaza peticiones de otras webs por `Origin`.
- Los SteamID se guardan como un hash de 10 caracteres, nunca en claro. Los ficheros de datos están en `.gitignore`.

## Terminal

```
python steam_families.py --datos datos              # interfaz en el navegador
python steam_families.py --exportar --token X --datos datos # exporta sin interfaz
python steam_families.py --panel --datos datos      # solo regenera el panel
```

Opciones: `--datos`, `--api-key`, `--include-free`, `--include-non-games`, `--sin-nombres`, `--sin-historial`, `--sin-precios`, `--puerto`, `--sin-navegador`.

## Cómo funciona

1. El token es un JWT firmado por Steam; su campo `sub` es tu SteamID64 y `exp` la caducidad.
2. `IFamilyGroupsService/GetFamilyGroupForUser` devuelve el grupo y sus miembros.
3. `IFamilyGroupsService/GetSharedLibraryApps` con `include_own=true` devuelve todas las apps con `owner_steamids`, `exclude_reason` y `rt_playtime`.
4. Si tu SteamID está entre los dueños, el juego es `own`; si no, `family`.
5. Las novedades son la diferencia entre el `snapshot.json` anterior y el actual.
6. Los nombres son el alias público de cada miembro. Se guardan en el snapshot y se refrescan cada 7 días; con API key, en cada ejecución.
7. Los nombres de los juegos se piden en el idioma de la interfaz: español o inglés.

Los tres endpoints de familia están sin documentar: funcionan hoy y pueden cambiar mañana.

## Límites

- El token caduca cada 24 horas. Sin guardar una cookie de sesión no hay forma de renovarlo solo, y guardar cookies queda descartado.
- Los free-to-play cuentan como biblioteca: un juego gratis reclamado también sale como novedad.
- «Comprado», «key» y «regalo» no se distinguen: el endpoint solo dice que alguien lo tiene.
- `rt_time_acquired` se usa como fecha de adquisición porque cuadra con compras reales, pero Valve no documenta su significado exacto.
- Sin API key, los nombres se piden de uno en uno al endpoint público de Steam. Si responde 429, espera 20 s y reintenta, con tres esperas como máximo por ejecución; si sigue frenando, esos miembros quedan como «Miembro 1», «Miembro 2»… hasta la siguiente.
- Los nombres guardados se refrescan a los 7 días para que un cambio de alias no se quede pegado. Con API key se refrescan en cada ejecución.

## Desarrollo

```
python -m unittest discover -s pruebas -v
```

89 pruebas sin red, más 5 de interfaz con Playwright (se saltan si no está instalado; hacen falta `pip install -r requirements-dev.txt` y `playwright install chromium`). Tres de las unitarias son solo de Windows y se saltan en otros sistemas. GitHub Actions ejecuta además la interfaz completa en Ubuntu 22.04 con Python 3.8, Ubuntu latest con 3.12 y Windows con 3.9 y 3.12, incluido el lanzador `.cmd`, y las pruebas de navegador en Chromium.

## Créditos

Basado en [salah153/steam-family-library](https://github.com/salah153/steam-family-library). MIT, ver `LICENSE`.

---

# Steam Families (English)

See which games your family lends you on Steam, which ones are yours, and what is new since last time. A single Python file, no dependencies, with a browser interface.

Steam merges all the libraries of the group and has no filter to tell them apart. This does.

## Getting started

1. Install [Python 3.8 or higher](https://www.python.org/downloads/). On Windows, tick "Add python.exe to PATH".
2. Windows: double-click `iniciar.cmd`. Linux or macOS: `chmod +x iniciar.sh && ./iniciar.sh`. Data is stored in the `datos/` subfolder.
3. A page opens on `127.0.0.1`. Paste the token the first time; from then on it is stored encrypted and the app updates itself until it expires.

Only one window can use the same data folder. If you open another one, it warns and closes.

### The token

1. Open `https://store.steampowered.com/pointssummary/ajaxgetasyncconfig` while signed in to Steam.
2. Copy the value of `webapi_token`. Either the bare token or the whole JSON works.
3. Paste it in the interface.

The page itself has a **Copiar token** bookmarklet that puts the token on the clipboard in one click, and a **Pegar** (paste) button.

## What it generates

| File | Content |
|---|---|
| `panel.html` | The full dashboard in a single offline file |
| `library.csv` | The whole library with a `source` column (`own` / `family`) |
| `prestados.csv`, `prestados.txt` | Only what is lent to you |
| `novedades.txt`, `novedades.json` | What changed in the last run |
| `historial.csv` | One row per change and day, without repeating the same event if you update twice |
| `snapshot.json` | A snapshot of the library to compare against |

All of them go into the `datos/` subfolder, which the launcher passes with `--datos`.

The dashboard has accent-insensitive search, filters by origin, status and age, an **Añadido** (added) column with the acquisition date, a **nuevo** (new) tag, a **gratis** (free) tag and the **Añadidos (90 días)** shortcut (added in the last 90 days). The interface and the dashboard come in Spanish and English: the **ES / EN** button in the corner switches the language and the choice is remembered. `novedades.txt` is written in the interface language; `historial.csv` keeps Spanish column names.

Under the title, the dashboard shows the last update time and turns it amber when the data is over a day old. It also warns when a member is still "Miembro N", with a link to the API key. It remembers your filters and sort order, and sorts when you click a column header.

CSVs are UTF-8 with BOM so Excel respects accents.

## Security

- **No cookies.** It does not read, ask for or store Steam cookies.
- The token is stored encrypted with DPAPI in `%LOCALAPPDATA%\SteamFamilies\token.bin`. Only your Windows user can decrypt it, and it expires on its own after 24 h. There is a **olvidar** (forget) link.
- The API key, if you paste one, is stored the same way in `apikey.bin`, in the same folder. **olvidar** deletes both.
- The token and the API key are **never sent to the page**: the server uses them and the interface only knows whether they are stored.
- Nothing leaves your machine: the only connections are to `api.steampowered.com` and `steamcommunity.com`.
- The local server listens only on `127.0.0.1`, checks the `Host` header and rejects requests from other websites by `Origin`.
- SteamIDs are stored as a 10-character hash, never in the clear. The data files are in `.gitignore`.

## Terminal

```
python steam_families.py --datos datos              # browser interface
python steam_families.py --exportar --token X --datos datos # export without the interface
python steam_families.py --panel --datos datos      # only regenerate the dashboard
```

Options: `--datos`, `--api-key`, `--include-free`, `--include-non-games`, `--sin-nombres`, `--sin-historial`, `--sin-precios`, `--puerto`, `--sin-navegador`.

## How it works

1. The token is a JWT signed by Steam; its `sub` field is your SteamID64 and `exp` the expiry.
2. `IFamilyGroupsService/GetFamilyGroupForUser` returns the group and its members.
3. `IFamilyGroupsService/GetSharedLibraryApps` with `include_own=true` returns all apps with `owner_steamids`, `exclude_reason` and `rt_playtime`.
4. If your SteamID is among the owners, the game is `own`; otherwise `family`.
5. What is new is the difference between the previous `snapshot.json` and the current one.
6. Names are each member's public alias. They are stored in the snapshot and refreshed every 7 days; with an API key, on every run.
7. Game names are requested in the interface language: Spanish or English.

The three family endpoints are undocumented: they work today and may change tomorrow.

## Limits

- The token expires every 24 hours. Without storing a session cookie there is no way to renew it automatically, and storing cookies is ruled out.
- Free-to-play games count as library: a free game that was claimed also shows up as new.
- "Bought", "key" and "gift" cannot be told apart: the endpoint only says that someone has it.
- `rt_time_acquired` is used as the acquisition date because it matches real purchases, but Valve does not document what it exactly means.
- Without an API key, names are requested one by one from Steam's public endpoint. If it answers 429, it waits 20 s and retries, with at most three waits per run; if it keeps throttling, those members stay as "Miembro 1", "Miembro 2"... until the next run.
- Stored names are refreshed after 7 days so an alias change does not stay stuck. With an API key they are refreshed on every run.

## Development

```
python -m unittest discover -s pruebas -v
```

89 tests with no network, plus 5 browser tests with Playwright (skipped if it is not installed; they need `pip install -r requirements-dev.txt` and `playwright install chromium`). Three of the unit tests are Windows-only and are skipped elsewhere. GitHub Actions also runs the full interface on Ubuntu 22.04 with Python 3.8, Ubuntu latest with 3.12, and Windows with 3.9 and 3.12, including the `.cmd` launcher, and the browser tests on Chromium.

## Credits

Based on [salah153/steam-family-library](https://github.com/salah153/steam-family-library). MIT, see `LICENSE`.
