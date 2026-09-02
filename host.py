"""
host.py -- Genera interfaces minimas de cobranza bajo demanda.

Dada una pregunta en lenguaje natural, Claude consulta la cartera a traves de
las herramientas del servidor MCP (los esquemas se toman de server.py, la
ejecucion la hace tools_core) y devuelve una pagina HTML autonoma y minimalista
que se guarda en out/ junto con una galeria (out/index.html).

    python host.py "Dame un resumen ejecutivo de la cartera"
    python host.py --demo                 # genera 4 interfaces de ejemplo
    python host.py --model claude-opus-5 "..."

Requiere ANTHROPIC_API_KEY en el archivo .env.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

import tools_core
from server import server as mcp_server

RAIZ = Path(__file__).resolve().parent
OUT = RAIZ / "out"
MANIFEST = OUT / "manifest.json"

# Sonnet por defecto: el host se corre muchas veces al iterar y las interfaces
# que pide son sencillas. Con --model claude-opus-5 sube el acabado visual.
MODELO_POR_DEFECTO = "claude-sonnet-5"

SYSTEM_PROMPT = """\
Eres un generador de interfaces para un panel de cobranza. Tienes herramientas
para consultar una cartera sintetica (deudores, cuentas en mora, pagos y
promesas de pago). Los montos estan en pesos mexicanos.

Flujo:
1. Llama las herramientas que necesites para responder la pregunta.
2. Cuando tengas los datos, responde UNICAMENTE con una pagina HTML completa
   dentro de un bloque ```html ... ```. Sin texto antes ni despues.

Reglas de la interfaz:
- Documento HTML completo y autonomo: <!DOCTYPE html>, con <style> embebido.
- Sin dependencias externas, salvo (opcional) una fuente de Google Fonts.
- Estetica minimalista: fondo claro, 2 o 3 colores como maximo, mucho espacio
  en blanco, tipografia grande para las cifras clave.
- Para barras, lineas o sparklines usa <svg> hecho a mano. Nada de librerias.
- Nada de <script> salvo que sea imprescindible para una interaccion trivial.
- Formatea el dinero como "$1,234,567 MXN". Muestra la fecha de corte.
- Debe caber en una pantalla y no provocar scroll horizontal.
- Todo el texto en espanol de Mexico.
"""

DEMO = [
    "Dame un resumen ejecutivo de la cartera de cobranza.",
    "Muestrame la distribucion de la cartera por antiguedad de mora (aging).",
    "Quienes son los gestores con mejor recuperacion este trimestre?",
    "Ensename las 8 cuentas con mayor saldo vencido a mas de 90 dias.",
]


# --------------------------------------------------------------------------- #
# Herramientas: esquema desde el servidor MCP, ejecucion desde tools_core
# --------------------------------------------------------------------------- #
def cargar_tools() -> list[dict]:
    tools = asyncio.run(mcp_server.list_tools())
    return [
        {
            "name": t.name,
            "description": (t.description or "").strip(),
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def ejecutar_tool(nombre: str, args: dict) -> dict:
    fn = tools_core.TOOLS.get(nombre)
    if fn is None:
        return {"error": f"herramienta desconocida: {nombre}"}
    try:
        return fn(**args)
    except (ValueError, FileNotFoundError, TypeError) as exc:
        return {"error": str(exc)}


# --------------------------------------------------------------------------- #
# Generacion
# --------------------------------------------------------------------------- #
def generar(pregunta: str, modelo: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic()
    tools = cargar_tools()
    messages: list[dict] = [{"role": "user", "content": pregunta}]
    tools_usadas: list[str] = []
    tok_in = tok_out = 0

    for _ in range(8):  # tope de vueltas del loop de tool-use
        resp = client.messages.create(
            model=modelo,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        tok_in += resp.usage.input_tokens
        tok_out += resp.usage.output_tokens
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            break

        resultados = []
        for bloque in resp.content:
            if bloque.type != "tool_use":
                continue
            tools_usadas.append(bloque.name)
            salida = ejecutar_tool(bloque.name, dict(bloque.input))
            resultados.append(
                {
                    "type": "tool_result",
                    "tool_use_id": bloque.id,
                    "content": json.dumps(salida, ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": resultados})

    texto = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    html = _extraer_html(texto)
    return {
        "html": html,
        "tools": sorted(set(tools_usadas)),
        "modelo": modelo,
        "tokens": {"in": tok_in, "out": tok_out},
    }


def _extraer_html(texto: str) -> str:
    m = re.search(r"```html\s*(.*?)```", texto, re.S | re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"(<!DOCTYPE html.*?</html>)", texto, re.S | re.I)
    if m:
        return m.group(1).strip()
    raise ValueError("El modelo no devolvio un bloque HTML reconocible.")


# --------------------------------------------------------------------------- #
# Guardado y galeria
# --------------------------------------------------------------------------- #
def _slug(texto: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return t[:40] or "interfaz"


def _cargar_manifest() -> list[dict]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return []


def guardar(pregunta: str, resultado: dict) -> Path:
    OUT.mkdir(exist_ok=True)
    manifest = _cargar_manifest()
    n = len(manifest) + 1
    archivo = f"{n:02d}-{_slug(pregunta)}.html"
    (OUT / archivo).write_text(resultado["html"], encoding="utf-8")

    manifest.append(
        {
            "archivo": archivo,
            "pregunta": pregunta,
            "creado": dt.datetime.now().isoformat(timespec="seconds"),
            "tools": resultado["tools"],
            "modelo": resultado["modelo"],
            "tokens": resultado["tokens"],
        }
    )
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _construir_indice(manifest)
    return OUT / archivo


def _construir_indice(manifest: list[dict]) -> None:
    filas = "\n".join(
        f"""    <li>
      <a href="{m['archivo']}">{_esc(m['pregunta'])}</a>
      <div class="meta">{m['creado']} &middot; {m['modelo']}
        &middot; {' '.join(f'<code>{_esc(t)}</code>' for t in m['tools'])}</div>
    </li>"""
        for m in reversed(manifest)
    )
    html = f"""<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de Cartera Generativo &mdash; interfaces</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font: 16px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif;
         max-width: 760px; margin: 3rem auto; padding: 0 1.25rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; margin-bottom: .25rem; }}
  p.sub {{ color: #666; margin-top: 0; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 1rem 0; border-top: 1px solid #e6e6e6; }}
  li a {{ font-size: 1.05rem; color: #1552d6; text-decoration: none; }}
  li a:hover {{ text-decoration: underline; }}
  .meta {{ color: #888; font-size: .82rem; margin-top: .3rem; }}
  .meta code {{ background: #f2f2f2; padding: .05rem .35rem; border-radius: 4px; }}
</style>
</head>
<body>
  <h1>Panel de Cartera Generativo</h1>
  <p class="sub">Interfaces generadas bajo demanda sobre la cartera de cobranza sintetica.</p>
  <ul>
{filas}
  </ul>
</body>
</html>
"""
    (OUT / "index.html").write_text(html, encoding="utf-8")


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


# --------------------------------------------------------------------------- #
def _procesar(pregunta: str, modelo: str) -> None:
    print(f"> {pregunta}")
    resultado = generar(pregunta, modelo)
    ruta = guardar(pregunta, resultado)
    tk = resultado["tokens"]
    print(
        f"  {ruta.relative_to(RAIZ)}  "
        f"[tools: {', '.join(resultado['tools']) or 'ninguna'}]  "
        f"[tokens {tk['in']}+{tk['out']}]\n"
    )


def main() -> None:
    load_dotenv(RAIZ / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pregunta", nargs="?", help="pregunta en lenguaje natural")
    ap.add_argument("--demo", action="store_true", help="genera las 4 interfaces de ejemplo")
    ap.add_argument("--model", default=MODELO_POR_DEFECTO, help=f"modelo (por defecto {MODELO_POR_DEFECTO})")
    args = ap.parse_args()

    import os

    if not os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant"):
        sys.exit("Falta ANTHROPIC_API_KEY valida en .env (debe empezar con 'sk-ant').")

    if args.demo:
        for q in DEMO:
            _procesar(q, args.model)
    elif args.pregunta:
        _procesar(args.pregunta, args.model)
    else:
        ap.error("da una pregunta o usa --demo")


if __name__ == "__main__":
    main()
