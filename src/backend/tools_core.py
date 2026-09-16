"""
backend.tools_core -- Fachada de retrocompatibilidad dentro de backend.
"""

from __future__ import annotations

import json

try:
    from . import tools
    from .tools import (
        BUCKETS,
        DB_PATH,
        HOY,
        TOOLS,
        aging,
        cashflow,
        collector_stats,
        get_account,
        get_debtor,
        list_accounts,
        portfolio_summary,
        register_payment_promise,
        list_payment_promises,
    )
    from .tools.database import (
        _BUCKET_SQL,
        _GRANULARIDADES,
        _ORDENES,
        _conn,
        _f,
        _fecha_iso,
    )
except ImportError:
    import tools
    from tools import (
        BUCKETS,
        DB_PATH,
        HOY,
        TOOLS,
        aging,
        cashflow,
        collector_stats,
        get_account,
        get_debtor,
        list_accounts,
        portfolio_summary,
        register_payment_promise,
        list_payment_promises,
    )
    from tools.database import (
        _BUCKET_SQL,
        _GRANULARIDADES,
        _ORDENES,
        _conn,
        _f,
        _fecha_iso,
    )

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
]

if __name__ == "__main__":
    print(json.dumps(portfolio_summary(), indent=2, ensure_ascii=False))
