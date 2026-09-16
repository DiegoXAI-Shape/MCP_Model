"""
providers/base.py -- Utilidades y contrato comun de los proveedores de modelo.

Un proveedor es cualquier objeto con un metodo async `stream(prompt) ->
AsyncIterator[dict]` que emite eventos de este vocabulario:

    {"type": "thinking_delta", "text": str}
    {"type": "thinking_done", "ms": int}
    {"type": "tool_call", "id": str, "name": str, "args": dict}
    {"type": "tool_result", "id": str, "name": str, "result": Any, "ms": int, "error": bool}
    {"type": "usage", "turn": int, "input_tokens": int, "output_tokens": int}
    {"type": "html", "html": str}
    {"type": "done", "total_ms": int, "thinking_ms": int,
     "tokens": {"in": int, "out": int}, "tools": list[str]}
    {"type": "error", "message": str}

El endpoint de FastAPI (web.py) solo reenvia estos eventos como Server-Sent
Events; no conoce los detalles de cada backend de modelo.
"""

from __future__ import annotations

import re
import time
from typing import Any

try:
    from .. import tools
except ImportError:  # ejecucion directa (python providers/base.py)
    import tools

MAX_TURNOS = 8  # tope de vueltas del loop de tool-use, por seguridad

SYSTEM_PROMPT = """\
Eres un generador de interfaces para un panel de cobranza. Tienes herramientas
para consultar y gestionar una cartera sintetica (deudores, cuentas en mora,
pagos y promesas de pago). Los montos estan en pesos mexicanos.

Flujo:
1. Llama las herramientas que necesites para responder la pregunta.
2. Cuando tengas los datos, responde UNICAMENTE con una pagina HTML completa
   dentro de un bloque ```html ... ```. Sin texto antes ni despues.

Reglas criticas de la interfaz:
- NUNCA respondas con texto plano ni tablas en Markdown (| col1 | col2 |). Tu salida DEBE ser SIEMPRE codigo HTML dentro de ```html ... ```.
- Documento HTML completo y conciso: <!DOCTYPE html>, con <style> breve (maximo 30-35 lineas).
- Tablas bien estructuradas: Toda tabla <table> DEBE tener encabezados <thead><tr><th>Columna</th>...</tr></thead> bien definidos. Cada valor va en su propia columna <td> separada (ej. Gestor | Equipo | Cuentas | Saldo | Recuperado | Eficacia). NUNCA amontones dos numeros en la misma celda ni dejes textos flotando sin columna.
- Si hay mas de 15 cuentas o promesas, muestra en la tabla un TOP 10-15 de las principales para no agotar el limite de tokens.
- Para barras de progreso usa divs simples (ej. <div style="background:#e2e8f0;border-radius:4px;height:8px;"><div style="width:65%;background:#2563eb;height:8px;border-radius:4px;"></div></div>).
- Sin dependencias externas, sin <script>, sin emojis.
- Formatea el dinero como "$1,234,567 MXN". Muestra la fecha de corte.
- Todo el texto en espanol de Mexico.
- En tu razonamiento interno (<think>), se muy breve (maximo 2 lineas de planeacion). NUNCA escribas el codigo HTML dentro del pensamiento. Pasa directo a redactar el bloque ```html ... ```.
- IMPORTANTE: Ve directo al grano en el HTML y asegurate de cerrar siempre con </body></html>.
"""


def now_ms() -> int:
    return int(time.monotonic() * 1000)


def ejecutar_tool(nombre: str, args: dict) -> dict:
    fn = tools.TOOLS.get(nombre)
    if fn is None:
        return {"error": f"herramienta desconocida: {nombre}"}
    try:
        clean_args = {}
        for k, v in (args or {}).items():
            if isinstance(v, str):
                v = v.strip("\"' ")
            clean_args[k] = v
        return fn(**clean_args)
    except (ValueError, FileNotFoundError, TypeError) as exc:
        return {"error": str(exc)}


def _markdown_to_html_page(texto: str) -> str:
    """Convierte texto o tablas Markdown a una pagina HTML limpia si el modelo se equivoca de formato."""
    lineas = [l.strip() for l in texto.strip().splitlines() if l.strip()]
    filas_tabla = [l for l in lineas if l.startswith("|") and ("|" in l[1:])]

    if len(filas_tabla) >= 2:
        partes_tabla = []
        es_encabezado = True
        for f in filas_tabla:
            # Separador |---|---|
            if set(f.replace("|", "").strip()) <= {"-", ":", " "}:
                es_encabezado = False
                continue
            celdas = [c.strip() for c in f.split("|")[1:-1]]
            if es_encabezado:
                th_tags = "".join(f"<th>{c}</th>" for c in celdas)
                partes_tabla.append(f"<thead><tr>{th_tags}</tr></thead><tbody>")
                es_encabezado = False
            else:
                td_tags = "".join(f"<td>{c}</td>" for c in celdas)
                partes_tabla.append(f"<tr>{td_tags}</tr>")
        if partes_tabla:
            partes_tabla.append("</tbody>")
            cuerpo_html = f"<table>{''.join(partes_tabla)}</table>"
        else:
            cuerpo_html = f"<pre>{texto}</pre>"
    else:
        parrafos = "".join(f"<p>{l}</p>" for l in lineas)
        cuerpo_html = f"<div class='content'>{parrafos}</div>"

    return f"""<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="UTF-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 24px; background: #f8fafc; color: #1e293b; margin: 0; }}
.card {{ background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); max-width: 1200px; margin: 0 auto; }}
h2 {{ font-size: 1.25rem; margin-top: 0; color: #0f172a; margin-bottom: 16px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
th {{ background: #f1f5f9; font-weight: 600; color: #475569; }}
tr:hover {{ background: #f8fafc; }}
.content p {{ margin: 6px 0; line-height: 1.5; }}
</style>
</head>
<body>
<div class="card">
    <h2>Reporte de Cartera</h2>
    {cuerpo_html}
</div>
</body>
</html>"""


def _asegurar_cierre_html(cuerpo: str) -> str:
    if "<style" in cuerpo.lower() and "</style>" not in cuerpo.lower():
        cuerpo += "\n</style>\n</head>\n<body>\n"
    if "<body" in cuerpo.lower() and "</body>" not in cuerpo.lower():
        cuerpo += "\n</body>"
    if "</html>" not in cuerpo.lower():
        cuerpo += "\n</html>"
    return cuerpo


def _envolver_en_documento_html(contenido: str) -> str:
    if "<!doctype" in contenido.lower() or "<html" in contenido.lower():
        return _asegurar_cierre_html(contenido)

    if "<style" in contenido.lower() and "</style>" not in contenido.lower():
        contenido += "\n</style>"

    return f"""<!DOCTYPE html>
<html lang="es-MX">
<head>
<meta charset="UTF-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 24px; background: #f8fafc; color: #1e293b; margin: 0; }}
.card {{ background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); max-width: 1200px; margin: 0 auto; }}
h1, h2, h3 {{ color: #0f172a; margin-top: 0; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 0.88rem; }}
th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
th {{ background: #f1f5f9; font-weight: 600; color: #475569; }}
tr:hover {{ background: #f8fafc; }}
.progress-container {{ width: 100%; background-color: #e2e8f0; border-radius: 4px; height: 8px; overflow: hidden; }}
.progress-bar {{ height: 100%; background-color: #2563eb; }}
</style>
</head>
<body>
<div class="card">
{contenido}
</div>
</body>
</html>"""


def extraer_html(texto: str) -> str:
    texto = (texto or "").strip()
    if not texto:
        return _envolver_en_documento_html("<p>No se recibió respuesta del modelo para esta consulta.</p>")

    # 1. Bloque markdown ```html ... ``` (cerrado o sin cerrar)
    m = re.search(r"```html\s*(.*?)(?:```|$)", texto, re.S | re.I)
    if m:
        cuerpo = m.group(1).strip()
        return _envolver_en_documento_html(cuerpo)

    # 2. Bloque markdown genérico ``` ... ``` si contiene HTML
    m = re.search(r"```(?:xml)?\s*(.*?)(?:```|$)", texto, re.S | re.I)
    if m:
        cuerpo = m.group(1).strip()
        if any(tag in cuerpo.lower() for tag in ["<!doctype", "<html", "<table", "<div", "<style", "<section", "<h1", "<h2", "<p"]):
            return _envolver_en_documento_html(cuerpo)

    # 3. Documento HTML completo <!DOCTYPE ... o <html ...
    m = re.search(r"(<!DOCTYPE html.*)", texto, re.S | re.I)
    if m:
        return _asegurar_cierre_html(m.group(1).strip())
    m = re.search(r"(<html.*)", texto, re.S | re.I)
    if m:
        return _asegurar_cierre_html(m.group(1).strip())

    # 4. Cualquier fragmento con etiquetas HTML comunes
    if any(tag in texto.lower() for tag in ["<table", "<div", "<style", "<section", "<main", "<header", "<h1", "<h2", "<ul", "<p"]):
        return _envolver_en_documento_html(texto)

    # 5. Tabla en Markdown (| col1 | col2 |)
    if "|" in texto and ("\n|" in texto or texto.count("|") >= 4):
        return _markdown_to_html_page(texto)

    # 6. Texto plano: envolverlo en una tarjeta limpia
    parrafos = "".join(f"<p>{l.strip()}</p>" for l in texto.splitlines() if l.strip())
    return _envolver_en_documento_html(f"<h2>Resumen</h2>{parrafos}")


async def anthropic_tool_schema() -> list[dict[str, Any]]:
    """Schema de las tools MCP en formato Anthropic (name/description/input_schema).

    Debe ejecutarse dentro de un event loop ya corriendo (el de FastAPI/uvicorn),
    por eso se hace `await` directo en vez de `asyncio.run(...)`.
    """
    try:
        from ..server import server as mcp_server
    except ImportError:
        from server import server as mcp_server

    tools_list = await mcp_server.list_tools()
    return [
        {
            "name": t.name,
            "description": (t.description or "").strip(),
            "input_schema": t.input_schema,
        }
        for t in tools_list
    ]


async def openai_tool_schema() -> list[dict[str, Any]]:
    """Las mismas tools, en formato OpenAI (usado por llama.cpp)."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in await anthropic_tool_schema()
    ]
