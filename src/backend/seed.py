"""
seed.py -- Genera una cartera de cobranza sintetica y reproducible en SQLite.

Uso:
    python src/backend/seed.py                     # crea cobranza.db en la raíz del repo
    python src/backend/seed.py --db otra.db --seed 7

El objetivo es tener datos realistas del dominio de cobranza: deudores,
cuentas con distintos niveles de mora, pagos (totales y parciales) y
promesas de pago cumplidas/incumplidas.

Todas las cantidades estan en pesos mexicanos (MXN). La fecha de referencia
("hoy") esta fija en HOY para que los numeros del README sean reproducibles.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sqlite3
from pathlib import Path

from faker import Faker

REPO_ROOT = Path(__file__).resolve().parents[2]

HOY = dt.date(2026, 9, 1)

N_DEUDORES = 150
N_GESTORES = 6
N_CUENTAS = 400

SEGMENTOS = ["consumo", "pyme", "nomina"]
EQUIPOS = ["Temprana", "Media", "Tardia"]

# producto: (saldo_min, saldo_max) en MXN
PRODUCTOS = {
    "Tarjeta de credito": (5_000, 80_000),
    "Prestamo personal": (10_000, 250_000),
    "Credito PyME": (50_000, 800_000),
    "Credito automotriz": (80_000, 450_000),
}

# (etiqueta, dias_min, dias_max, peso) -- la distribucion de mora de la cartera
BUCKETS = [
    ("al_corriente", 0, 0, 0.42),
    ("1-30", 1, 30, 0.22),
    ("31-60", 31, 60, 0.16),
    ("61-90", 61, 90, 0.09),
    ("90+", 91, 320, 0.11),
]

SCHEMA = """
CREATE TABLE gestores (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL,
    equipo  TEXT NOT NULL
);
CREATE TABLE deudores (
    id         INTEGER PRIMARY KEY,
    nombre     TEXT NOT NULL,
    segmento   TEXT NOT NULL,
    ciudad     TEXT NOT NULL,
    telefono   TEXT NOT NULL,
    score_buro INTEGER NOT NULL
);
CREATE TABLE cuentas (
    id                INTEGER PRIMARY KEY,
    deudor_id         INTEGER NOT NULL REFERENCES deudores(id),
    gestor_id         INTEGER NOT NULL REFERENCES gestores(id),
    producto          TEXT NOT NULL,
    saldo_original    REAL NOT NULL,
    saldo_actual      REAL NOT NULL,
    fecha_originacion TEXT NOT NULL,
    fecha_vencimiento TEXT NOT NULL,
    dias_mora         INTEGER NOT NULL,
    estatus           TEXT NOT NULL
);
CREATE TABLE pagos (
    id        INTEGER PRIMARY KEY,
    cuenta_id INTEGER NOT NULL REFERENCES cuentas(id),
    fecha     TEXT NOT NULL,
    monto     REAL NOT NULL,
    tipo      TEXT NOT NULL
);
CREATE TABLE promesas (
    id              INTEGER PRIMARY KEY,
    cuenta_id       INTEGER NOT NULL REFERENCES cuentas(id),
    fecha_registro  TEXT NOT NULL,
    fecha_promesa   TEXT NOT NULL,
    monto_prometido REAL NOT NULL,
    cumplida        INTEGER NOT NULL
);
CREATE INDEX ix_cuentas_gestor  ON cuentas(gestor_id);
CREATE INDEX ix_cuentas_estatus ON cuentas(estatus);
CREATE INDEX ix_pagos_cuenta    ON pagos(cuenta_id);
CREATE INDEX ix_promesas_cuenta ON promesas(cuenta_id);
"""


def iso(d: dt.date) -> str:
    return d.isoformat()


def elegir_bucket(rng: random.Random) -> tuple[str, int]:
    etiquetas = [b[0] for b in BUCKETS]
    pesos = [b[3] for b in BUCKETS]
    etiqueta = rng.choices(etiquetas, weights=pesos, k=1)[0]
    _, dmin, dmax, _ = next(b for b in BUCKETS if b[0] == etiqueta)
    dias = 0 if dmax == 0 else rng.randint(dmin, dmax)
    return etiqueta, dias


def gen_gestores(fake: Faker) -> list[tuple]:
    return [
        (i, fake.name(), EQUIPOS[(i - 1) % len(EQUIPOS)])
        for i in range(1, N_GESTORES + 1)
    ]


def gen_deudores(rng: random.Random, fake: Faker) -> list[tuple]:
    filas = []
    for i in range(1, N_DEUDORES + 1):
        filas.append(
            (
                i,
                fake.name(),
                rng.choice(SEGMENTOS),
                fake.city(),
                fake.phone_number(),
                rng.randint(320, 830),
            )
        )
    return filas


def gen_cuentas(rng: random.Random) -> list[tuple]:
    filas = []
    for i in range(1, N_CUENTAS + 1):
        producto = rng.choice(list(PRODUCTOS))
        s_min, s_max = PRODUCTOS[producto]
        saldo_original = round(rng.uniform(s_min, s_max), 2)
        originacion = HOY - dt.timedelta(days=rng.randint(60, 900))

        if rng.random() < 0.12:
            estatus = "liquidada"
            dias_mora = 0
            saldo_actual = 0.0
            vencimiento = originacion + dt.timedelta(days=rng.randint(30, 400))
        else:
            etiqueta, dias_mora = elegir_bucket(rng)
            if etiqueta == "al_corriente":
                estatus = "al_corriente"
                saldo_actual = round(saldo_original * rng.uniform(0.2, 0.95), 2)
                vencimiento = HOY + dt.timedelta(days=rng.randint(1, 25))
            else:
                estatus = "castigada" if dias_mora > 180 else "en_mora"
                saldo_actual = round(saldo_original * rng.uniform(0.55, 1.08), 2)
                vencimiento = HOY - dt.timedelta(days=dias_mora)

        filas.append(
            (
                i,
                rng.randint(1, N_DEUDORES),
                rng.randint(1, N_GESTORES),
                producto,
                saldo_original,
                saldo_actual,
                iso(originacion),
                iso(vencimiento),
                dias_mora,
                estatus,
            )
        )
    return filas


def _fecha_pago(rng: random.Random, originacion: dt.date) -> dt.date:
    # ~35% de los pagos caen en los ultimos 45 dias para que
    # "recuperado del mes" tenga senal.
    if rng.random() < 0.35:
        return HOY - dt.timedelta(days=rng.randint(0, 45))
    span = max((HOY - originacion).days, 1)
    return originacion + dt.timedelta(days=rng.randint(0, span))


def gen_pagos(rng: random.Random, cuentas: list[tuple]) -> list[tuple]:
    filas = []
    pid = 1
    for cid, *_, saldo_original, _saldo_actual, f_orig, _f_venc, _dias, estatus in cuentas:
        originacion = dt.date.fromisoformat(f_orig)
        if estatus == "liquidada":
            for _ in range(rng.randint(0, 3)):
                filas.append(
                    (pid, cid, iso(_fecha_pago(rng, originacion)),
                     round(saldo_original * rng.uniform(0.03, 0.20), 2), "parcial")
                )
                pid += 1
            filas.append(
                (pid, cid, iso(HOY - dt.timedelta(days=rng.randint(0, 90))),
                 round(saldo_original * rng.uniform(0.85, 1.0), 2), "total")
            )
            pid += 1
        else:
            for _ in range(rng.randint(0, 4)):
                filas.append(
                    (pid, cid, iso(_fecha_pago(rng, originacion)),
                     round(saldo_original * rng.uniform(0.02, 0.18), 2), "parcial")
                )
                pid += 1
    return filas


def gen_promesas(rng: random.Random, cuentas: list[tuple]) -> list[tuple]:
    filas = []
    prid = 1
    for cid, *_, _saldo_original, saldo_actual, _f_orig, _f_venc, dias_mora, estatus in cuentas:
        if estatus not in ("en_mora", "castigada"):
            continue
        for _ in range(rng.randint(0, 3)):
            registro = HOY - dt.timedelta(days=rng.randint(1, 60))
            promesa = registro + dt.timedelta(days=rng.randint(1, 15))
            p_cumplida = min(max(0.75 - dias_mora / 500, 0.15), 0.80)
            cumplida = 1 if rng.random() < p_cumplida else 0
            filas.append(
                (prid, cid, iso(registro), iso(promesa),
                 round(saldo_actual * rng.uniform(0.10, 0.60), 2), cumplida)
            )
            prid += 1
    return filas


def construir(db_path: Path, seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    Faker.seed(seed)
    fake = Faker("es_MX")

    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        gestores = gen_gestores(fake)
        deudores = gen_deudores(rng, fake)
        cuentas = gen_cuentas(rng)
        pagos = gen_pagos(rng, cuentas)
        promesas = gen_promesas(rng, cuentas)

        con.executemany("INSERT INTO gestores VALUES (?,?,?)", gestores)
        con.executemany("INSERT INTO deudores VALUES (?,?,?,?,?,?)", deudores)
        con.executemany("INSERT INTO cuentas VALUES (?,?,?,?,?,?,?,?,?,?)", cuentas)
        con.executemany("INSERT INTO pagos VALUES (?,?,?,?,?)", pagos)
        con.executemany("INSERT INTO promesas VALUES (?,?,?,?,?,?)", promesas)
        con.commit()
    finally:
        con.close()

    return {
        "gestores": len(gestores),
        "deudores": len(deudores),
        "cuentas": len(cuentas),
        "pagos": len(pagos),
        "promesas": len(promesas),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera la cartera de cobranza sintetica.")
    ap.add_argument("--db", default=REPO_ROOT / "cobranza.db", type=Path)
    ap.add_argument("--seed", default=42, type=int)
    args = ap.parse_args()

    resumen = construir(args.db, args.seed)
    print(f"Base creada en {args.db} (semilla {args.seed}, hoy = {HOY})")
    for k, v in resumen.items():
        print(f"  {k:10} {v}")


if __name__ == "__main__":
    main()
