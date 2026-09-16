"""
tools/portfolio.py -- Consultas de salud macro y distribución de la cartera.
"""

from __future__ import annotations

import datetime as dt
from contextlib import closing

from .database import BUCKETS, HOY, _BUCKET_SQL, _conn, _f


def portfolio_summary() -> dict:
    """Foto general de la cartera: saldos, mora y recuperacion reciente."""
    hoy = HOY.isoformat()
    hace_30 = (HOY - dt.timedelta(days=30)).isoformat()

    with closing(_conn()) as con:
        cuentas_por_estatus = {
            r["estatus"]: {"cuentas": r["n"], "saldo": _f(r["saldo"])}
            for r in con.execute(
                "SELECT estatus, COUNT(*) n, SUM(saldo_actual) saldo "
                "FROM cuentas GROUP BY estatus"
            )
        }
        row = con.execute(
            """
            SELECT
              SUM(CASE WHEN estatus != 'liquidada' THEN saldo_actual ELSE 0 END)      AS saldo_vivo,
              SUM(CASE WHEN estatus IN ('en_mora','castigada') THEN saldo_actual ELSE 0 END) AS saldo_vencido,
              SUM(saldo_actual * dias_mora)                                           AS num_mora_pond,
              SUM(CASE WHEN saldo_actual > 0 THEN saldo_actual ELSE 0 END)            AS den_mora_pond
            FROM cuentas
            """
        ).fetchone()
        recuperado_30d = (
            con.execute(
                "SELECT SUM(monto) FROM pagos WHERE fecha BETWEEN ? AND ?",
                (hace_30, hoy),
            ).fetchone()[0]
            or 0.0
        )
        prom = con.execute(
            "SELECT AVG(cumplida) tasa, COUNT(*) n FROM promesas"
        ).fetchone()

    saldo_vivo = row["saldo_vivo"] or 0.0
    saldo_vencido = row["saldo_vencido"] or 0.0
    mora_pond = (row["num_mora_pond"] or 0.0) / (row["den_mora_pond"] or 1.0)
    base_rr = saldo_vencido + recuperado_30d

    return {
        "fecha_corte": hoy,
        "saldo_total_vivo": _f(saldo_vivo),
        "saldo_vencido": _f(saldo_vencido),
        "pct_cartera_vencida": _f(100 * saldo_vencido / saldo_vivo if saldo_vivo else 0, 1),
        "dias_mora_promedio_ponderado": _f(mora_pond, 1),
        "recuperado_ult_30d": _f(recuperado_30d),
        "recovery_rate_30d_pct": _f(100 * recuperado_30d / base_rr if base_rr else 0, 1),
        "promesas_totales": prom["n"],
        "promesas_cumplidas_pct": _f(100 * (prom["tasa"] or 0), 1),
        "cuentas_por_estatus": cuentas_por_estatus,
    }


def aging() -> dict:
    """Distribucion de la cartera viva por bucket de dias de mora."""
    with closing(_conn()) as con:
        filas = con.execute(
            f"""
            SELECT {_BUCKET_SQL} AS bucket,
                   COUNT(*)      AS cuentas,
                   SUM(saldo_actual) AS saldo
            FROM cuentas
            WHERE estatus != 'liquidada' AND saldo_actual > 0
            GROUP BY bucket
            """
        ).fetchall()

    por_bucket = {r["bucket"]: r for r in filas}
    total = sum((r["saldo"] or 0.0) for r in filas)
    denom = total or 1.0

    salida = []
    for b in BUCKETS:
        r = por_bucket.get(b)
        saldo = _f(r["saldo"]) if r else 0.0
        salida.append(
            {
                "bucket": b,
                "cuentas": r["cuentas"] if r else 0,
                "saldo": saldo,
                "pct_saldo": _f(100 * saldo / denom, 1),
            }
        )
    return {"fecha_corte": HOY.isoformat(), "saldo_total": _f(total), "buckets": salida}
