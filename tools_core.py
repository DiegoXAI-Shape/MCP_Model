"""
tools_core.py -- Logica de negocio de la cartera de cobranza.

Funciones puras que consultan la base SQLite y devuelven estructuras
JSON-serializables (dict / list). Es la unica fuente de verdad: el servidor
MCP (server.py) y el host de interfaces (host.py) la reutilizan tal cual.

La fecha de referencia ("hoy") esta fija en HOY, igual que en seed.py, para
que los resultados sean reproducibles.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

HOY = dt.date(2026, 9, 1)

DB_PATH = Path(os.environ.get("COBRANZA_DB", "cobranza.db"))

BUCKETS = ("al_corriente", "1-30", "31-60", "61-90", "90+")

# Expresion SQL que clasifica una cuenta en su bucket de aging.
_BUCKET_SQL = """
CASE
    WHEN dias_mora = 0  THEN 'al_corriente'
    WHEN dias_mora <= 30 THEN '1-30'
    WHEN dias_mora <= 60 THEN '31-60'
    WHEN dias_mora <= 90 THEN '61-90'
    ELSE '90+'
END
"""

_ORDENES = {
    "saldo_desc": "c.saldo_actual DESC",
    "saldo_asc": "c.saldo_actual ASC",
    "mora_desc": "c.dias_mora DESC",
    "mora_asc": "c.dias_mora ASC",
}

_GRANULARIDADES = {"dia": "%Y-%m-%d", "semana": "%Y-S%W", "mes": "%Y-%m"}


# --------------------------------------------------------------------------- #
# Ayudantes internos
# --------------------------------------------------------------------------- #
def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"No existe la base {DB_PATH}. Corre primero:  python seed.py"
        )
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _f(x: float | None, nd: int = 2) -> float:
    """Redondea y trata None como 0."""
    return round(x or 0.0, nd)


def _fecha_iso(s: str, campo: str) -> str:
    try:
        return dt.date.fromisoformat(s).isoformat()
    except (TypeError, ValueError):
        raise ValueError(
            f"'{campo}' debe ser una fecha ISO (YYYY-MM-DD); recibi: {s!r}"
        )


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
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


def list_accounts(
    bucket: str | None = None,
    gestor_id: int | None = None,
    estatus: str | None = None,
    orden: str = "saldo_desc",
    limite: int = 20,
) -> dict:
    """Lista de cuentas filtrable por bucket, gestor y estatus."""
    if orden not in _ORDENES:
        raise ValueError(f"'orden' invalido: {orden!r}. Opciones: {sorted(_ORDENES)}")
    if bucket is not None and bucket not in BUCKETS:
        raise ValueError(f"'bucket' invalido: {bucket!r}. Opciones: {list(BUCKETS)}")
    limite = max(1, min(int(limite), 100))

    where = ["1=1"]
    params: list = []
    rangos = {
        "al_corriente": "c.dias_mora = 0",
        "1-30": "c.dias_mora BETWEEN 1 AND 30",
        "31-60": "c.dias_mora BETWEEN 31 AND 60",
        "61-90": "c.dias_mora BETWEEN 61 AND 90",
        "90+": "c.dias_mora > 90",
    }
    if bucket:
        where.append(rangos[bucket])
    if gestor_id is not None:
        where.append("c.gestor_id = ?")
        params.append(int(gestor_id))
    if estatus is not None:
        where.append("c.estatus = ?")
        params.append(estatus)

    sql = f"""
        SELECT c.id, c.producto, c.saldo_actual, c.dias_mora, c.estatus,
               c.fecha_vencimiento, d.nombre AS deudor, d.segmento, d.ciudad,
               g.nombre AS gestor
        FROM cuentas c
        JOIN deudores d ON d.id = c.deudor_id
        JOIN gestores g ON g.id = c.gestor_id
        WHERE {' AND '.join(where)}
        ORDER BY {_ORDENES[orden]}
        LIMIT {limite}
    """
    with closing(_conn()) as con:
        filas = [dict(r) for r in con.execute(sql, params)]
    for r in filas:
        r["saldo_actual"] = _f(r["saldo_actual"])

    return {
        "filtros": {
            "bucket": bucket,
            "gestor_id": gestor_id,
            "estatus": estatus,
            "orden": orden,
            "limite": limite,
        },
        "resultados": len(filas),
        "cuentas": filas,
    }


def get_account(cuenta_id: int) -> dict:
    """Detalle de una cuenta con su deudor, historial de pagos y promesas."""
    cid = int(cuenta_id)
    with closing(_conn()) as con:
        c = con.execute(
            """
            SELECT c.*, d.nombre AS deudor, d.segmento, d.ciudad, d.telefono,
                   d.score_buro, g.nombre AS gestor, g.equipo
            FROM cuentas c
            JOIN deudores d ON d.id = c.deudor_id
            JOIN gestores g ON g.id = c.gestor_id
            WHERE c.id = ?
            """,
            (cid,),
        ).fetchone()
        if c is None:
            raise ValueError(f"No existe la cuenta {cid}")
        pagos = [
            dict(r)
            for r in con.execute(
                "SELECT fecha, monto, tipo FROM pagos WHERE cuenta_id = ? ORDER BY fecha",
                (cid,),
            )
        ]
        promesas = [
            dict(r)
            for r in con.execute(
                "SELECT fecha_registro, fecha_promesa, monto_prometido, cumplida "
                "FROM promesas WHERE cuenta_id = ? ORDER BY fecha_registro",
                (cid,),
            )
        ]

    d = dict(c)
    for p in pagos:
        p["monto"] = _f(p["monto"])
    for p in promesas:
        p["monto_prometido"] = _f(p["monto_prometido"])
        p["cumplida"] = bool(p["cumplida"])

    return {
        "cuenta": {
            "id": d["id"],
            "producto": d["producto"],
            "saldo_original": _f(d["saldo_original"]),
            "saldo_actual": _f(d["saldo_actual"]),
            "dias_mora": d["dias_mora"],
            "estatus": d["estatus"],
            "fecha_originacion": d["fecha_originacion"],
            "fecha_vencimiento": d["fecha_vencimiento"],
        },
        "deudor": {
            "nombre": d["deudor"],
            "segmento": d["segmento"],
            "ciudad": d["ciudad"],
            "telefono": d["telefono"],
            "score_buro": d["score_buro"],
        },
        "gestor": {"nombre": d["gestor"], "equipo": d["equipo"]},
        "pagos": pagos,
        "promesas": promesas,
        "total_pagado": _f(sum(p["monto"] for p in pagos)),
    }


def get_debtor(deudor_id: int) -> dict:
    """Perfil de un deudor con todas sus cuentas y totales."""
    did = int(deudor_id)
    with closing(_conn()) as con:
        d = con.execute("SELECT * FROM deudores WHERE id = ?", (did,)).fetchone()
        if d is None:
            raise ValueError(f"No existe el deudor {did}")
        cuentas = [
            dict(r)
            for r in con.execute(
                """
                SELECT c.id, c.producto, c.saldo_actual, c.dias_mora, c.estatus,
                       g.nombre AS gestor
                FROM cuentas c
                JOIN gestores g ON g.id = c.gestor_id
                WHERE c.deudor_id = ?
                ORDER BY c.saldo_actual DESC
                """,
                (did,),
            )
        ]

    for c in cuentas:
        c["saldo_actual"] = _f(c["saldo_actual"])

    return {
        "deudor": {
            "id": d["id"],
            "nombre": d["nombre"],
            "segmento": d["segmento"],
            "ciudad": d["ciudad"],
            "telefono": d["telefono"],
            "score_buro": d["score_buro"],
        },
        "num_cuentas": len(cuentas),
        "saldo_total": _f(sum(c["saldo_actual"] for c in cuentas)),
        "saldo_en_mora": _f(
            sum(c["saldo_actual"] for c in cuentas if c["estatus"] in ("en_mora", "castigada"))
        ),
        "cuentas": cuentas,
    }


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


TOOLS = {
    "portfolio_summary": portfolio_summary,
    "aging": aging,
    "list_accounts": list_accounts,
    "get_account": get_account,
    "get_debtor": get_debtor,
    "cashflow": cashflow,
    "collector_stats": collector_stats,
}


if __name__ == "__main__":  # vistazo rapido: python tools_core.py
    print(json.dumps(portfolio_summary(), indent=2, ensure_ascii=False))
