"""
Pruebas de tools_core sobre una base pequena y controlada (5 cuentas),
elegida para poder afirmar valores exactos de aging, mora ponderada,
recuperacion y ranking de gestores.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

import tools
import tools_core
from seed import SCHEMA

HOY = tools_core.HOY  # 2026-09-01


def _dias(n: int) -> str:
    return (HOY - dt.timedelta(days=n)).isoformat()


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)

    con.executemany(
        "INSERT INTO gestores VALUES (?,?,?)",
        [(1, "Ana", "Temprana"), (2, "Beto", "Tardia")],
    )
    con.executemany(
        "INSERT INTO deudores VALUES (?,?,?,?,?,?)",
        [
            (1, "Deudor Uno", "consumo", "Monterrey", "81-000", 650),
            (2, "Deudor Dos", "pyme", "CDMX", "55-000", 500),
        ],
    )
    # id, deudor, gestor, producto, s_orig, s_actual, f_orig, f_venc, dias_mora, estatus
    con.executemany(
        "INSERT INTO cuentas VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (1, 1, 1, "Tarjeta de credito", 10000, 10000, "2025-01-01", "2026-09-15", 0, "al_corriente"),
            (2, 1, 1, "Prestamo personal", 20000, 20000, "2025-01-01", "2026-08-17", 15, "en_mora"),
            (3, 2, 2, "Credito PyME", 100000, 50000, "2024-01-01", "2026-06-03", 90, "en_mora"),
            (4, 2, 2, "Credito automotriz", 200000, 100000, "2023-01-01", "2026-01-01", 240, "castigada"),
            (5, 1, 1, "Tarjeta de credito", 5000, 0, "2024-01-01", "2024-06-01", 0, "liquidada"),
        ],
    )
    con.executemany(
        "INSERT INTO pagos VALUES (?,?,?,?,?)",
        [
            (1, 3, _dias(10), 5000, "parcial"),
            (2, 4, _dias(20), 3000, "parcial"),
            (3, 5, "2024-05-01", 5000, "total"),
            (4, 2, _dias(200), 1000, "parcial"),
        ],
    )
    con.executemany(
        "INSERT INTO promesas VALUES (?,?,?,?,?,?)",
        [
            (1, 3, _dias(15), _dias(5), 5000, 1),
            (2, 4, _dias(30), _dias(20), 2000, 0),
            (3, 4, _dias(10), _dias(2), 1000, 0),
        ],
    )
    con.commit()
    con.close()

    monkeypatch.setattr(tools_core, "DB_PATH", path)
    monkeypatch.setattr(tools.database, "DB_PATH", path)
    monkeypatch.setattr(tools, "DB_PATH", path)
    return path


# --------------------------------------------------------------------------- #
def test_portfolio_summary(db):
    s = tools_core.portfolio_summary()
    assert s["saldo_total_vivo"] == 180000
    assert s["saldo_vencido"] == 170000
    assert s["pct_cartera_vencida"] == pytest.approx(94.4, abs=0.1)
    # (20000*15 + 50000*90 + 100000*240) / 180000 = 160.0
    assert s["dias_mora_promedio_ponderado"] == pytest.approx(160.0, abs=0.1)
    assert s["recuperado_ult_30d"] == 8000  # 5000 + 3000; el pago de -200d queda fuera
    assert s["promesas_totales"] == 3
    assert s["promesas_cumplidas_pct"] == pytest.approx(33.3, abs=0.1)
    assert s["cuentas_por_estatus"]["en_mora"]["cuentas"] == 2


def test_aging_buckets(db):
    res = tools_core.aging()
    by = {b["bucket"]: b for b in res["buckets"]}
    assert (by["al_corriente"]["cuentas"], by["al_corriente"]["saldo"]) == (1, 10000)
    assert by["1-30"]["saldo"] == 20000
    assert by["31-60"]["cuentas"] == 0
    assert by["61-90"]["saldo"] == 50000       # dias_mora == 90 cae en 61-90
    assert by["90+"]["saldo"] == 100000
    assert res["saldo_total"] == 180000        # la liquidada no cuenta
    assert by["90+"]["pct_saldo"] == pytest.approx(100 * 100000 / 180000, abs=0.1)


def test_list_accounts_filtra_y_ordena(db):
    r = tools_core.list_accounts(bucket="90+")
    assert r["resultados"] == 1
    assert r["cuentas"][0]["id"] == 4

    r = tools_core.list_accounts(orden="saldo_desc", limite=3)
    saldos = [c["saldo_actual"] for c in r["cuentas"]]
    assert saldos == sorted(saldos, reverse=True)
    assert r["cuentas"][0]["id"] == 4

    r = tools_core.list_accounts(gestor_id=1)
    assert {c["id"] for c in r["cuentas"]} == {1, 2, 5}


def test_list_accounts_valida_parametros(db):
    with pytest.raises(ValueError):
        tools_core.list_accounts(bucket="inexistente")
    with pytest.raises(ValueError):
        tools_core.list_accounts(orden="raro")


def test_get_account_incluye_pagos_y_promesas(db):
    a = tools_core.get_account(4)
    assert a["cuenta"]["estatus"] == "castigada"
    assert a["deudor"]["nombre"] == "Deudor Dos"
    assert a["total_pagado"] == 3000
    assert len(a["promesas"]) == 2
    assert all(p["cumplida"] is False for p in a["promesas"])


def test_get_account_inexistente(db):
    with pytest.raises(ValueError):
        tools_core.get_account(999)


def test_get_debtor(db):
    d = tools_core.get_debtor(1)
    assert d["num_cuentas"] == 3          # cuentas 1, 2, 5
    assert d["saldo_total"] == 30000      # 10000 + 20000 + 0
    assert d["saldo_en_mora"] == 20000    # solo la cuenta 2


def test_cashflow_agrupa_por_mes(db):
    r = tools_core.cashflow(desde="2026-01-01", hasta="2026-09-01", granularidad="mes")
    per = {s["periodo"]: s["cobrado"] for s in r["serie"]}
    assert per.get("2026-08") == 8000    # pagos de -10d y -20d
    assert r["total_cobrado"] == 9000    # + 1000 del pago de -200d (febrero)


def test_cashflow_rango_invalido(db):
    with pytest.raises(ValueError):
        tools_core.cashflow(desde="2026-09-01", hasta="2026-01-01")
    with pytest.raises(ValueError):
        tools_core.cashflow(granularidad="trimestre")


def test_collector_stats_ranking(db):
    r = tools_core.collector_stats(desde="2026-07-01", hasta="2026-09-01")
    top = r["gestores"][0]
    assert top["gestor"] == "Beto"           # recupero 5000 + 3000 en el periodo
    assert top["recuperado_periodo"] == 8000
    ana = next(g for g in r["gestores"] if g["gestor"] == "Ana")
    assert ana["recuperado_periodo"] == 0


def test_modular_package_consistency(db):
    assert len(tools.TOOLS) == 9
    assert tools.portfolio_summary() == tools_core.portfolio_summary()
    assert tools.aging() == tools_core.aging()
    assert tools.list_accounts(limite=2) == tools_core.list_accounts(limite=2)


def test_register_and_list_payment_promises(db):
    r1 = tools.register_payment_promise(cuenta_id=1, monto_prometido=5000.0, fecha_promesa="2026-09-10")
    assert r1["cuenta_id"] == 1
    assert r1["fecha_promesa"] == "2026-09-10"
    assert r1["monto_prometido"] == 5000.0
    assert r1["cumplida"] is False

    r2 = tools.register_payment_promise(cuenta_id=1, monto_prometido=2000.0, dias_plazo=5)
    assert r2["fecha_promesa"] == (HOY + dt.timedelta(days=5)).isoformat()

    # Probar que list_payment_promises encuentra las promesas recién registradas
    lista = tools.list_payment_promises(cuenta_id=1)
    assert lista["total_encontradas"] >= 2
    assert any(p["monto_prometido"] == 5000.0 for p in lista["promesas"])

    with pytest.raises(ValueError, match="No existe la cuenta"):
        tools.register_payment_promise(cuenta_id=9999, monto_prometido=100.0, dias_plazo=1)

    with pytest.raises(ValueError):
        tools.register_payment_promise(cuenta_id=1, monto_prometido=100.0)
