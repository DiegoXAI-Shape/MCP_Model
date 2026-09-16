"""
tools/information_in.py -- Herramientas para registrar nueva información (promesas de pago).
"""

from __future__ import annotations

import datetime as dt

from .database import HOY, _conn


def register_payment_promise(
    cuenta_id: int,
    monto_prometido: float,
    fecha_promesa: str | None = None,
    dias_plazo: int | None = None,
) -> dict:
    """Registra una promesa de pago para una cuenta.
    Acepta 'fecha_promesa' (ej: '2026-09-05') O 'dias_plazo' (ej: 3)."""
    fecha_registro = HOY.isoformat()

    if dias_plazo is not None:
        fecha_final = (HOY + dt.timedelta(days=dias_plazo)).isoformat()
    elif fecha_promesa is not None:
        fecha_final = str(fecha_promesa)
    else:
        raise ValueError("Debes proporcionar 'fecha_promesa' o 'dias_plazo'")

    cid = int(cuenta_id)
    monto = round(float(monto_prometido), 2)

    with _conn() as conn:
        c = conn.execute("SELECT id FROM cuentas WHERE id = ?", (cid,)).fetchone()
        if c is None:
            raise ValueError(f"No existe la cuenta {cid}")

        cursor = conn.execute(
            """
            INSERT INTO promesas (cuenta_id, fecha_registro, fecha_promesa, monto_prometido, cumplida)
            VALUES (?, ?, ?, ?, 0)
            """,
            (cid, fecha_registro, fecha_final, monto),
        )
        conn.commit()
        promesa_id = cursor.lastrowid

    return {
        "id": promesa_id,
        "cuenta_id": cid,
        "fecha_registro": fecha_registro,
        "fecha_promesa": fecha_final,
        "monto_prometido": monto,
        "cumplida": False,
        "estatus": "registrada",
    }


def list_payment_promises(
    cuenta_id: int | None = None,
    cumplida: bool | None = None,
    limite: int = 20,
) -> dict:
    """Lista las promesas de pago registradas, con nombre del deudor, gestor y montos.
    Permite filtrar por cuenta_id o por estatus de cumplimiento (cumplida=True/False).
    Ordenadas de las más recientes a las más antiguas.
    """
    limite = max(1, min(int(limite), 50))
    where = ["1=1"]
    params: list = []

    if cuenta_id is not None:
        try:
            where.append("p.cuenta_id = ?")
            params.append(int(str(cuenta_id).strip("\"' ")))
        except (ValueError, TypeError):
            pass

    if cumplida is not None:
        where.append("p.cumplida = ?")
        params.append(1 if cumplida else 0)

    sql = f"""
        SELECT p.id, p.cuenta_id, d.nombre AS deudor, g.nombre AS gestor,
               c.producto, c.saldo_actual, p.fecha_registro, p.fecha_promesa,
               p.monto_prometido, p.cumplida
        FROM promesas p
        JOIN cuentas c ON c.id = p.cuenta_id
        JOIN deudores d ON d.id = c.deudor_id
        JOIN gestores g ON g.id = c.gestor_id
        WHERE {' AND '.join(where)}
        ORDER BY p.id DESC
        LIMIT {limite}
    """
    with _conn() as conn:
        filas = [dict(r) for r in conn.execute(sql, params)]

    for r in filas:
        r["cumplida"] = bool(r["cumplida"])
        r["estatus"] = "Cumplida" if r["cumplida"] else "Pendiente"
        r["monto_prometido"] = round(float(r["monto_prometido"]), 2)
        r["saldo_actual"] = round(float(r["saldo_actual"]), 2)

    return {
        "total_encontradas": len(filas),
        "promesas": filas,
    }
