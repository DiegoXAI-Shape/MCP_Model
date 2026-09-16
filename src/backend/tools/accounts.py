"""
tools/accounts.py -- Consultas de cuentas de crédito, deudores y detalle 360°.
"""

from __future__ import annotations

from contextlib import closing

from .database import BUCKETS, _ORDENES, _conn, _f


def list_accounts(
    bucket: str | None = None,
    gestor_id: int | None = None,
    estatus: str | None = None,
    orden: str = "saldo_desc",
    limite: int = 20,
) -> dict:
    if isinstance(orden, str):
        orden = orden.strip("\"' ")
    if isinstance(bucket, str):
        bucket = bucket.strip("\"' ")
    if isinstance(estatus, str):
        estatus = estatus.strip("\"' ")
    if gestor_id is not None:
        try:
            gestor_id = int(str(gestor_id).strip("\"' "))
        except (ValueError, TypeError):
            pass

    if orden not in _ORDENES:
        raise ValueError(f"'orden' invalido: {orden!r}. Opciones: {sorted(_ORDENES)}")
    if bucket is not None and bucket not in BUCKETS:
        raise ValueError(f"'bucket' invalido: {bucket!r}. Opciones: {list(BUCKETS)}")
    limite = max(1, min(int(limite), 25))

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
