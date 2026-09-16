"""
tools -- Paquete modular de herramientas de análisis y gestión de cartera de cobranza.
"""

from __future__ import annotations

from .accounts import get_account, get_debtor, list_accounts
from .analytics import cashflow, collector_stats
from .database import BUCKETS, DB_PATH, HOY
from .information_in import list_payment_promises, register_payment_promise
from .portfolio import aging, portfolio_summary

TOOLS = {
    "portfolio_summary": portfolio_summary,
    "aging": aging,
    "list_accounts": list_accounts,
    "get_account": get_account,
    "get_debtor": get_debtor,
    "cashflow": cashflow,
    "collector_stats": collector_stats,
    "register_payment_promise": register_payment_promise,
    "list_payment_promises": list_payment_promises,
}

__all__ = [
    "HOY",
    "DB_PATH",
    "BUCKETS",
    "TOOLS",
    "portfolio_summary",
    "aging",
    "list_accounts",
    "get_account",
    "get_debtor",
    "cashflow",
    "collector_stats",
    "register_payment_promise",
    "list_payment_promises",
]
