"""
tools/database.py -- Configuración, conexión y utilidades de base de datos.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path

# Raíz del repositorio (4 niveles arriba desde src/backend/tools/database.py)
REPO_ROOT = Path(__file__).resolve().parents[3]

HOY = dt.date(2026, 9, 1)

DB_PATH = Path(os.environ.get("COBRANZA_DB", REPO_ROOT / "cobranza.db"))

BUCKETS = ("al_corriente", "1-30", "31-60", "61-90", "90+")

# Expresión SQL que clasifica una cuenta en su bucket de aging.
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


def _conn() -> sqlite3.Connection:
    tc = sys.modules.get("tools_core") or sys.modules.get("backend.tools_core")
    db_path = getattr(tc, "DB_PATH", DB_PATH) if tc else DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(
            f"No existe la base {db_path}. Corre primero:  python src/backend/seed.py"
        )
    con = sqlite3.connect(db_path)
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
