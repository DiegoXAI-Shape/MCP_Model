"""
tools/analytics.py -- Métricas de flujo de cobranza (cashflow) y desempeño de gestores.
"""

from __future__ import annotations

import datetime as dt
from contextlib import closing

from .database import HOY, _GRANULARIDADES, _conn, _f, _fecha_iso


def cashflow(
    desde: str | None = None,
    hasta: str | None = None,
    granularidad: str = "mes",
) -> dict:
    """Monto cobrado agrupado por periodo (dia / semana / mes)."""
    if granularidad not in _GRANULARIDADES:
        raise ValueError(
            f"'granularidad' invalida: {granularidad!r}. Opciones: {list(_GRANULARIDADES)}"
        )
    hasta = _fecha_iso(hasta, "hasta") if hasta else HOY.isoformat()
    desde = (
        _fecha_iso(desde, "desde")
        if desde
        else (HOY - dt.timedelta(days=180)).isoformat()
    )
    if desde > hasta:
        raise ValueError(f"'desde' ({desde}) es posterior a 'hasta' ({hasta})")

    fmt = _GRANULARIDADES[granularidad]
    with closing(_conn()) as con:
        filas = con.execute(
            f"""
            SELECT strftime('{fmt}', fecha) AS periodo,
                   COUNT(*) AS num_pagos,
                   SUM(monto) AS cobrado
            FROM pagos
            WHERE fecha BETWEEN ? AND ?
            GROUP BY periodo
            ORDER BY periodo
            """,
            (desde, hasta),
        ).fetchall()

    serie = [
        {"periodo": r["periodo"], "num_pagos": r["num_pagos"], "cobrado": _f(r["cobrado"])}
        for r in filas
    ]
    return {
        "desde": desde,
        "hasta": hasta,
        "granularidad": granularidad,
        "total_cobrado": _f(sum(s["cobrado"] for s in serie)),
        "serie": serie,
    }


def collector_stats(desde: str | None = None, hasta: str | None = None) -> dict:
    """Desempeno por gestor: saldo gestionado, recuperado y promesas."""
    hasta = _fecha_iso(hasta, "hasta") if hasta else HOY.isoformat()
    desde = (
        _fecha_iso(desde, "desde")
        if desde
        else (HOY - dt.timedelta(days=90)).isoformat()
    )
    if desde > hasta:
        raise ValueError(f"'desde' ({desde}) es posterior a 'hasta' ({hasta})")

    with closing(_conn()) as con:
        base: dict[int, dict] = {
            r["id"]: {
                "gestor_id": r["id"],
                "gestor": r["nombre"],
                "equipo": r["equipo"],
                "cuentas": 0,
                "saldo_gestionado": 0.0,
                "recuperado_periodo": 0.0,
                "num_pagos_periodo": 0,
                "promesas": 0,
                "promesas_cumplidas_pct": 0.0,
            }
            for r in con.execute("SELECT * FROM gestores")
        }
        for r in con.execute(
            "SELECT gestor_id, COUNT(*) n, SUM(saldo_actual) saldo "
            "FROM cuentas WHERE estatus != 'liquidada' GROUP BY gestor_id"
        ):
            base[r["gestor_id"]]["cuentas"] = r["n"]
            base[r["gestor_id"]]["saldo_gestionado"] = _f(r["saldo"])
        for r in con.execute(
            """
            SELECT c.gestor_id, SUM(p.monto) recuperado, COUNT(*) num_pagos
            FROM pagos p JOIN cuentas c ON c.id = p.cuenta_id
            WHERE p.fecha BETWEEN ? AND ?
            GROUP BY c.gestor_id
            """,
            (desde, hasta),
        ):
            base[r["gestor_id"]]["recuperado_periodo"] = _f(r["recuperado"])
            base[r["gestor_id"]]["num_pagos_periodo"] = r["num_pagos"]
        for r in con.execute(
            """
            SELECT c.gestor_id, COUNT(*) n, AVG(pr.cumplida) tasa
            FROM promesas pr JOIN cuentas c ON c.id = pr.cuenta_id
            GROUP BY c.gestor_id
            """
        ):
            base[r["gestor_id"]]["promesas"] = r["n"]
            base[r["gestor_id"]]["promesas_cumplidas_pct"] = _f(100 * (r["tasa"] or 0), 1)

    ranking = sorted(base.values(), key=lambda x: x["recuperado_periodo"], reverse=True)
    return {"desde": desde, "hasta": hasta, "gestores": ranking}
