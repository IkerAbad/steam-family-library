#!/usr/bin/env python3
"""
Interfaz local para steam-family-library.

Levanta un servidor en 127.0.0.1, abre el navegador y permite pegar el token,
actualizar la biblioteca y ver el panel, todo desde una pagina. Nada sale de tu
ordenador: el unico trafico externo es a la API de Steam.

    python app.py            (desde cualquier carpeta)
    python app.py --datos C:\\ruta\\donde\\guardar
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PROHIBIDOS = set('"<>|*?')
CANDADO = threading.Lock()
FICHEROS = {
    "/panel.html": ("panel.html", "text/html; charset=utf-8"),
    "/library.csv": ("library.csv", "text/csv; charset=utf-8"),
    "/prestados.csv": ("prestados.csv", "text/csv; charset=utf-8"),
    "/prestados.txt": ("prestados.txt", "text/plain; charset=utf-8"),
    "/novedades.txt": ("novedades.txt", "text/plain; charset=utf-8"),
    "/historial.csv": ("historial.csv", "text/csv; charset=utf-8"),
}


def leer_json(ruta):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except Exception:
        return {}


def carpeta_de_datos(texto):
    """Comprueba la ruta antes de tocar nada y explica el problema en castellano."""
    texto = (texto or "").strip()
    if not texto:
        raise SystemExit("la carpeta de datos esta vacia. Pasa --datos <ruta>.")
    raros = sorted({c for c in texto if c in PROHIBIDOS}) if os.name == "nt" else []
    if raros:
        raise SystemExit(
            f"la ruta de datos lleva caracteres no validos: {texto}\n"
            f"sobran {', '.join(raros)}. Suele pasar cuando el .cmd pasa \"%~dp0\" "
            "y la barra final se come la comilla: usa \"%~dp0.\"."
        )
    ruta = Path(texto).expanduser()
    try:
        ruta = ruta.resolve()
    except OSError as e:
        raise SystemExit(f"no puedo resolver la ruta {texto}: {e}")
    if ruta.exists() and not ruta.is_dir():
        raise SystemExit(f"{ruta} existe y no es una carpeta.")
    try:
        ruta.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SystemExit(f"no puedo crear o abrir la carpeta {ruta}: {e}")
    if not ruta.is_dir():
        raise SystemExit(f"{ruta} no es una carpeta.")
    try:
        prueba = ruta / ".escritura.tmp"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
    except OSError as e:
        raise SystemExit(f"la carpeta {ruta} no admite escritura: {e}")
    return ruta


def estado(datos: Path):
    snap = leer_json(datos / "snapshot.json")
    nov = leer_json(datos / "novedades.json")
    juegos = snap.get("juegos") or {}
    yo = snap.get("yo", "")
    prestados = sum(1 for j in juegos.values() if yo not in j.get("o", []))
    jugables = sum(1 for j in juegos.values() if yo not in j.get("o", []) and j.get("p"))
    horas = 0
    csv_path = datos / "library.csv"
    if csv_path.exists():
        import csv as _csv
        try:
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                for r in _csv.DictReader(f):
                    if (r.get("source") or "") != "family":
                        continue
                    try:
                        horas += int(float(r.get("playtime_minutes") or 0))
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass
    return {
        "ok": True,
        "primera": not bool(juegos),
        "grupo": snap.get("grupo", ""),
        "juegos": len(juegos),
        "prestados": prestados,
        "jugables": jugables,
        "horas": round(horas / 60, 1),
        "nombres": snap.get("nombres", {}),
        "yo": yo,
        "novedades": nov.get("eventos", []),
        "fecha_novedades": nov.get("fecha", ""),
        "ficheros": {k: (datos / v[0]).exists() for k, v in FICHEROS.items()},
    }


def ejecutar(datos: Path, token: str, api_key: str = ""):
    entorno = dict(os.environ, STEAM_WEBAPI_TOKEN=token, PYTHONIOENCODING="utf-8")
    if api_key:
        entorno["STEAM_API_KEY"] = api_key
    pasos = [
        [sys.executable, str(AQUI / "steam_family_library.py"), "--datos", str(datos)],
        [sys.executable, str(AQUI / "panel.py"), "--datos", str(datos)],
    ]
    salida = []
    for cmd in pasos:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env=entorno, timeout=300)
        except subprocess.TimeoutExpired:
            return False, ("La consulta ha tardado mas de 5 minutos y la he cortado. "
                           "Suele ser la conexion con Steam; prueba otra vez.")
        except FileNotFoundError:
            return False, ("No encuentro python. Comprueba que esta instalado y en el PATH.")
        except OSError as e:
            return False, f"No pude lanzar el proceso: {e}"
        salida.append((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            return False, (salida[-1].strip() or f"fallo el paso {cmd[1]}")
    return True, "\n".join(salida).strip()


class Servidor(ThreadingHTTPServer):
    # En Windows, SO_REUSEADDR deja que dos procesos escuchen el mismo puerto:
    # mejor que falle y que la app busque el siguiente libre.
    allow_reuse_address = False
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    datos = Path(".")
    servidor = None


    def log_message(self, formato, *args):
        pass

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8", extra=None):
        if isinstance(cuerpo, (dict, list)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False)
        datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._fallo(e)

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self._fallo(e)

    def _fallo(self, e):
        try:
            self._enviar(500, {"ok": False, "error": f"Fallo interno: {type(e).__name__}: {e}"})
        except Exception:
            pass

    def _origen_ok(self):
        """Solo acepta POST de la propia pagina: evita que otra web toque los datos."""
        origen = self.headers.get("Origin")
        if not origen:
            return True
        puerto = self.servidor.server_address[1]
        return origen in (f"http://127.0.0.1:{puerto}", f"http://localhost:{puerto}")

    def _get(self):
        if self.path in ("/", "/index.html"):
            self._enviar(200, PAGINA, "text/html; charset=utf-8")
            return
        if self.path == "/api/estado":
            self._enviar(200, estado(self.datos))
            return
        if self.path in FICHEROS:
            nombre, tipo = FICHEROS[self.path]
            ruta = self.datos / nombre
            if not ruta.exists():
                self._enviar(404, {"ok": False, "error": f"todavia no existe {nombre}"})
                return
            try:
                contenido = ruta.read_bytes()
            except OSError as e:
                self._enviar(500, {"ok": False, "error": f"no puedo leer {nombre}: {e}"})
                return
            self._enviar(200, contenido, tipo,
                         {"Content-Disposition": f'inline; filename="{nombre}"'})
            return
        self._enviar(404, {"ok": False, "error": "no existe"})

    def _post(self):
        if not self._origen_ok():
            self._enviar(403, {"ok": False, "error": "peticion de otro sitio: solo vale desde esta pagina"})
            return
        try:
            largo = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            largo = 0
        if largo > 100_000:
            self._enviar(413, {"ok": False, "error": "cuerpo demasiado grande"})
            return
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except Exception:
            self._enviar(400, {"ok": False, "error": "JSON invalido"})
            return
        if not isinstance(cuerpo, dict):
            self._enviar(400, {"ok": False, "error": "esperaba un objeto JSON"})
            return

        if self.path == "/api/actualizar":
            token = str(cuerpo.get("token") or "").strip().strip("\"'")
            if not token:
                self._enviar(400, {"ok": False, "error": "falta el token"})
                return
            if len(token) > 4000:
                self._enviar(400, {"ok": False, "error": "eso no es un token"})
                return
            api_key = str(cuerpo.get("api_key") or "").strip()
            if api_key and (len(api_key) > 64 or not all(c.isalnum() for c in api_key)):
                self._enviar(400, {"ok": False, "error": "la API key no tiene buena pinta: son 32 caracteres en hexadecimal"})
                return
            if not CANDADO.acquire(blocking=False):
                self._enviar(409, {"ok": False, "error": "Ya hay una actualizacion en curso. Espera a que termine."})
                return
            try:
                ok, mensaje = ejecutar(self.datos, token, api_key)
            finally:
                CANDADO.release()
            if not ok:
                self._enviar(500, {"ok": False, "error": mensaje})
                return
            datos = estado(self.datos)
            datos["log"] = mensaje
            self._enviar(200, datos)
            return

        if self.path == "/api/detener":
            self._enviar(200, {"ok": True})
            threading.Thread(target=self.servidor.shutdown, daemon=True).start()
            return

        self._enviar(404, {"ok": False, "error": "no existe"})


def main():
    p = argparse.ArgumentParser(description="Interfaz local de steam-family-library")
    p.add_argument("--datos", default=str(AQUI), help="carpeta con los datos (por defecto, la del programa)")
    p.add_argument("--puerto", type=int, default=8087)
    p.add_argument("--sin-navegador", action="store_true")
    args = p.parse_args()

    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    datos = carpeta_de_datos(args.datos)

    Handler.datos = datos
    servidor = None
    for puerto in range(args.puerto, args.puerto + 12):
        try:
            servidor = Servidor(("127.0.0.1", puerto), Handler)
            break
        except OSError:
            continue
    if servidor is None:
        print("No he encontrado un puerto libre entre "
              f"{args.puerto} y {args.puerto + 11}. Cierra la otra ventana de Steam Families.", file=sys.stderr)
        return 1

    Handler.servidor = servidor
    url = f"http://127.0.0.1:{servidor.server_address[1]}/"
    print(f"Datos: {datos}")
    print(f"Interfaz: {url}")
    print("Cierra esta ventana (o pulsa Detener en la pagina) para terminar.")
    if not args.sin_navegador:
        def abrir():
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Timer(0.6, abrir).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as e:
        print(f"El servidor se ha parado: {e}", file=sys.stderr)
        return 1
    finally:
        servidor.server_close()
    return 0


PAGINA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Steam Families</title>
<style>
:root { --fondo:#12151a; --panel:#1a1f26; --borde:#2a313b; --texto:#dfe6ee; --suave:#8b98a8; --acento:#66c0f4; --verde:#7bd88f; --rojo:#e06c6c; }
* { box-sizing:border-box; }
body { margin:0; background:var(--fondo); color:var(--texto); font-family:"Segoe UI",system-ui,-apple-system,sans-serif; font-size:14px; line-height:1.5; }
main { max-width:880px; margin:0 auto; padding:32px 22px 60px; }
h1 { font-size:24px; margin:0 0 4px; }
.sub { color:var(--suave); margin:0 0 26px; }
.paso { background:var(--panel); border:1px solid var(--borde); border-radius:10px; padding:18px 20px; margin-bottom:14px; }
.paso h2 { font-size:14px; margin:0 0 10px; text-transform:uppercase; letter-spacing:.05em; color:var(--suave); }
a { color:var(--acento); }
code { background:#0e1116; border:1px solid var(--borde); border-radius:4px; padding:1px 5px; font-size:12px; }
.fila { display:flex; gap:8px; flex-wrap:wrap; }
input[type=password], input[type=text] { flex:1 1 320px; min-width:220px; background:#0e1116; color:var(--texto); border:1px solid var(--borde); border-radius:6px; padding:9px 11px; font:inherit; }
input:focus { outline:none; border-color:var(--acento); }
button { background:#2a6f97; color:#fff; border:none; border-radius:6px; padding:9px 16px; font:inherit; cursor:pointer; }
button:hover { background:#3583b0; }
button:disabled { opacity:.55; cursor:default; }
button.sec { background:#232a33; color:var(--texto); border:1px solid var(--borde); }
button.sec:hover { background:#2b333d; }
#estado { margin-top:10px; min-height:22px; font-size:13px; color:var(--suave); }
.error { color:var(--rojo); white-space:pre-wrap; }
.tarjetas { display:flex; gap:10px; flex-wrap:wrap; margin:6px 0 4px; }
.tarjeta { flex:1 1 130px; background:#0e1116; border:1px solid var(--borde); border-radius:8px; padding:12px 14px; }
.tarjeta b { display:block; font-size:22px; font-weight:600; }
.tarjeta span { color:var(--suave); font-size:12px; }
table { width:100%; border-collapse:collapse; margin-top:8px; }
th, td { text-align:left; padding:7px 8px; border-bottom:1px solid #1e242c; font-size:13px; }
th { color:var(--suave); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
td.quien { color:var(--suave); }
.si { color:var(--verde); }
.no { color:var(--rojo); }
details summary { cursor:pointer; color:var(--suave); font-size:13px; }
details ol { margin:8px 0 0 18px; padding:0; color:var(--suave); font-size:13px; }
.pie { margin-top:26px; color:var(--suave); font-size:12px; }
</style>
</head>
<body>
<main>
  <h1>Steam Families</h1>
  <p class="sub">Exporta tu biblioteca familiar, separa lo que te prestan y detecta qué ha entrado nuevo.</p>

  <section class="paso">
    <h2>Paso 1 · El token</h2>
    <p style="margin:0 0 10px">
      Abre <a href="https://store.steampowered.com/pointssummary/ajaxgetasyncconfig" target="_blank" rel="noopener">esta página</a>
      con la sesión de Steam iniciada y copia el valor de <code>webapi_token</code>.
    </p>
    <details>
      <summary>¿Por qué hace falta y qué es?</summary>
      <ol>
        <li>Es un JWT de Steam que caduca en unas 24 horas.</li>
        <li>Solo sirve para leer tu biblioteca familiar. No se guarda en disco.</li>
        <li>La página que abres es la oficial de Steam: devuelve un JSON y dentro está el token.</li>
      </ol>
    </details>
  </section>

  <section class="paso">
    <h2>Paso 2 · Pégalo aquí</h2>
    <div class="fila">
      <input id="token" type="password" placeholder="eyJ0eXAiOiJKV1Qi..." autocomplete="off" spellcheck="false">
      <button id="ver" type="button" class="sec">Mostrar</button>
      <button id="lanzar" type="button">Actualizar</button>
    </div>
    <details style="margin-top:12px">
      <summary>¿Los dueños salen como «Miembro 1»?</summary>
      <p style="color:var(--suave);font-size:13px;margin:8px 0">
        Steam limita las consultas de nombres cuando se piden muchas seguidas. Con una
        <a href="https://steamcommunity.com/dev/apikey" target="_blank" rel="noopener">API key gratuita</a>
        salen siempre. Solo se usa durante esta consulta y no se guarda.
      </p>
      <input id="apikey" type="text" placeholder="API key de Steam (opcional)" autocomplete="off" spellcheck="false" style="width:100%">
    </details>
    <div id="estado"></div>
  </section>

  <section class="paso" id="resultado" hidden>
    <h2>Resultado</h2>
    <div class="tarjetas" id="tarjetas"></div>
    <div id="novedades"></div>
    <div class="fila" style="margin-top:14px">
      <button class="sec" onclick="window.open('/panel.html','_blank')">Abrir panel</button>
      <button class="sec" onclick="window.open('/prestados.csv','_blank')">Abrir CSV de prestados</button>
      <button class="sec" onclick="window.open('/novedades.txt','_blank')">Abrir novedades</button>
      <button class="sec" onclick="window.open('/historial.csv','_blank')">Historial</button>
    </div>
  </section>

  <p class="pie">
    Todo se ejecuta en tu ordenador. El token vive en memoria mientras dura la consulta y no se escribe en ningún fichero.
    <a href="#" id="detener">Detener la interfaz</a>
  </p>
</main>

<script>
const $ = id => document.getElementById(id);
const fmt = n => new Intl.NumberFormat("es-ES").format(n);

$("ver").addEventListener("click", () => {
  const t = $("token");
  t.type = t.type === "password" ? "text" : "password";
  $("ver").textContent = t.type === "password" ? "Mostrar" : "Ocultar";
});

function pintar(d) {
  $("resultado").hidden = false;
  $("tarjetas").innerHTML = `
    <div class="tarjeta"><b>${fmt(d.juegos)}</b><span>juegos</span></div>
    <div class="tarjeta"><b>${fmt(d.prestados)}</b><span>prestados</span></div>
    <div class="tarjeta"><b>${fmt(d.jugables)}</b><span>jugables ahora</span></div>
    <div class="tarjeta"><b>${String(d.horas).replace(".", ",")}</b><span>horas en prestados</span></div>`;

  const ev = d.novedades || [];
  if (!d.primera && ev.length) {
    const filas = ev.slice(0, 40).map(e => {
      const etiqueta = e.evento === "nuevo" ? "nuevo" : (e.evento === "fuera" ? "fuera" : "otro dueño");
      const clase = e.evento === "nuevo" ? "si" : "no";
      return `<tr><td>${e.nombre}</td><td class="${clase}">${etiqueta}</td><td class="quien">${e.quien || "tú"}</td></tr>`;
    }).join("");
    $("novedades").innerHTML = `
      <p style="margin:14px 0 0;color:var(--suave);font-size:13px">Novedades del ${d.fecha_novedades}</p>
      <table><thead><tr><th>Juego</th><th>Qué</th><th>Quién</th></tr></thead><tbody>${filas}</tbody></table>`;
  } else if (d.primera) {
    $("novedades").innerHTML = `<p style="margin:14px 0 0;color:var(--suave)">Primera ejecución: guardado el retrato inicial. A partir de la próxima sabrás qué entra y qué sale.</p>`;
  } else {
    $("novedades").innerHTML = `<p style="margin:14px 0 0;color:var(--suave)">Sin cambios desde la última vez.</p>`;
  }
}

async function cargar() {
  try {
    const r = await fetch("/api/estado");
    const d = await r.json();
    if (d && d.juegos) pintar(d);
  } catch (e) {}
}

$("lanzar").addEventListener("click", async () => {
  const token = $("token").value.trim();
  if (!token) { $("estado").textContent = "Pega antes el token."; return; }
  $("lanzar").disabled = true;
  $("estado").className = "";
  $("estado").textContent = "Consultando Steam. La primera vez tarda unos segundos más porque busca los nombres de los miembros...";
  try {
    const r = await fetch("/api/actualizar", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token, api_key: $("apikey").value.trim()})
    });
    const d = await r.json();
    if (!d.ok) {
      $("estado").className = "error";
      $("estado").textContent = d.error || "No se pudo actualizar.";
      return;
    }
    $("token").value = "";
    $("estado").textContent = "Listo.";
    pintar(d);
  } catch (e) {
    $("estado").className = "error";
    $("estado").textContent = "No se pudo hablar con el servidor local: " + e.message;
  } finally {
    $("lanzar").disabled = false;
  }
});

$("detener").addEventListener("click", async e => {
  e.preventDefault();
  try { await fetch("/api/detener", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"}); } catch (x) {}
  document.body.innerHTML = '<main><h1>Interfaz detenida</h1><p class="sub">Puedes cerrar esta pestaña. Para volver a abrirla, doble clic en iniciar.cmd.</p></main>';
});

cargar();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
