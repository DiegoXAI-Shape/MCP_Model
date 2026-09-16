"""
probe_mcp.py -- Cliente MCP minimo para verificar server.py de punta a punta.

Levanta server.py por stdio, lista las herramientas y llama algunas.
Sirve como prueba de humo y como ejemplo de uso del servidor.

    python scripts/probe_mcp.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RAIZ = Path(__file__).resolve().parent.parent


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(RAIZ / "src" / "backend" / "server.py")],
        cwd=str(RAIZ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = (await session.list_tools()).tools
            print(f"Herramientas expuestas ({len(tools)}):")
            for t in tools:
                params_names = ", ".join((t.input_schema or {}).get("properties", {}))
                print(f"  - {t.name}({params_names})")
            print()

            demos = [
                ("portfolio_summary", {}),
                ("aging", {}),
                ("list_accounts", {"bucket": "90+", "limite": 2}),
                ("collector_stats", {}),
                ("get_account", {"cuenta_id": 999999}),  # error controlado
                ("register_payment_promise", {"cuenta_id": 1, "monto_prometido": 2500.0, "dias_plazo": 3}),
            ]
            for nombre, args in demos:
                res = await session.call_tool(nombre, args)
                dato = res.structured_content or (
                    res.content[0].text if res.content else None
                )
                print(f"# {nombre}({json.dumps(args, ensure_ascii=False)})")
                print(json.dumps(dato, ensure_ascii=False)[:500])
                print()


if __name__ == "__main__":
    asyncio.run(main())
