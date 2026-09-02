"""
server.py -- Servidor MCP de la cartera de cobranza.

Expone la logica de tools_core como herramientas MCP para que cualquier
cliente compatible (Claude Desktop, MCP Inspector, el host de este repo)
pueda consultarla. Todas las herramientas son de solo lectura.

Ejecutar en modo stdio:
    python server.py

Probar con el Inspector (requiere Node):
    mcp dev server.py
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

import tools_core

server = MCPServer(
    name="cartera-cobranza",
    instructions=(
        "Herramientas de solo lectura sobre una cartera de cobranza sintetica "
        "(deudores, cuentas en mora, pagos y promesas de pago). Los montos estan "
        "en pesos mexicanos (MXN). La fecha de corte de los datos es 2026-09-01."
    ),
    version="0.1.0",
)

Bucket = Literal["al_corriente", "1-30", "31-60", "61-90", "90+"]
Estatus = Literal["al_corriente", "en_mora", "castigada", "liquidada"]
Orden = Literal["saldo_desc", "saldo_asc", "mora_desc", "mora_asc"]
Granularidad = Literal["dia", "semana", "mes"]


def _safe(fn, *args, **kwargs) -> Any:
    """Convierte los errores de entrada en un resultado estructurado en vez de
    dejar que se propaguen como excepcion de transporte."""
    try:
        return fn(*args, **kwargs)
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}


@server.tool()
def portfolio_summary() -> dict:
    """Foto general de la cartera: saldo vivo, saldo vencido, porcentaje de
    cartera vencida, dias de mora promedio ponderados por saldo, monto
    recuperado en los ultimos 30 dias y porcentaje de promesas cumplidas."""
    return _safe(tools_core.portfolio_summary)


@server.tool()
def aging() -> dict:
    """Distribucion de la cartera viva por bucket de dias de mora
    (al_corriente, 1-30, 31-60, 61-90, 90+): saldo, numero de cuentas y
    porcentaje del saldo total en cada bucket."""
    return _safe(tools_core.aging)


@server.tool()
def list_accounts(
    bucket: Bucket | None = None,
    gestor_id: int | None = None,
    estatus: Estatus | None = None,
    orden: Orden = "saldo_desc",
    limite: int = 20,
) -> dict:
    """Lista cuentas de la cartera con datos del deudor y del gestor asignado.
    Permite filtrar por bucket de aging, por gestor y por estatus; ordenar por
    saldo o por dias de mora; y limitar el numero de resultados (maximo 100)."""
    return _safe(
        tools_core.list_accounts,
        bucket=bucket,
        gestor_id=gestor_id,
        estatus=estatus,
        orden=orden,
        limite=limite,
    )


@server.tool()
def get_account(cuenta_id: int) -> dict:
    """Detalle de una cuenta: datos del credito, del deudor y del gestor, mas
    el historial completo de pagos y de promesas de pago."""
    return _safe(tools_core.get_account, cuenta_id)


@server.tool()
def get_debtor(deudor_id: int) -> dict:
    """Perfil de un deudor con todas sus cuentas, su saldo total y su saldo en
    mora."""
    return _safe(tools_core.get_debtor, deudor_id)


@server.tool()
def cashflow(
    desde: str | None = None,
    hasta: str | None = None,
    granularidad: Granularidad = "mes",
) -> dict:
    """Monto cobrado agrupado por periodo. 'desde' y 'hasta' son fechas ISO
    (YYYY-MM-DD); si se omiten, se usan los ultimos 180 dias hasta la fecha de
    corte."""
    return _safe(tools_core.cashflow, desde=desde, hasta=hasta, granularidad=granularidad)


@server.tool()
def collector_stats(desde: str | None = None, hasta: str | None = None) -> dict:
    """Desempeno por gestor en un periodo: numero de cuentas y saldo gestionado,
    monto recuperado, numero de pagos y porcentaje de promesas cumplidas.
    Ordenado de mayor a menor monto recuperado. Periodo por defecto: ultimos
    90 dias."""
    return _safe(tools_core.collector_stats, desde=desde, hasta=hasta)


if __name__ == "__main__":
    server.run("stdio")
