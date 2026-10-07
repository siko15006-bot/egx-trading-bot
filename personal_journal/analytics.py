"""Behavioural analysis (docs/personal_ledger_design.md, "Behavioural analysis"). Placeholders."""
from __future__ import annotations

from typing import Any


def results_summary(trips: list[dict[str, Any]]) -> dict[str, float]:
    """Net PnL, expectancy per trip, win rate, average win / loss, fee drag."""
    raise NotImplementedError


def disposition_effect(trips: list[dict[str, Any]], daily_prices: Any) -> float:
    """Odean PGR − PLR: proportion of gains realised minus proportion of losses realised."""
    raise NotImplementedError


def attribute_sources(trips: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """BUY ↔ signal for the same ticker in the preceding 2 trading sessions; nearest wins; else 'own idea'."""
    raise NotImplementedError


def fund_summary(db_path: Any = None) -> list[dict[str, Any]]:
    """Fund sub-account, kept apart from the stock P&L (no FIFO, no fees): per fund the net units bought − sold in the
    imported statements, the cash in/out and the last unit price seen. Negative net units = sold out of a holding
    that predates the first imported statement (its cost is unknown)."""
    import sqlite3
    from contextlib import closing

    from personal_journal.db import DB_PATH

    with closing(sqlite3.connect(db_path or DB_PATH)) as con:
        rows = con.execute(
            "SELECT fund_code, MAX(fund_name), "
            "SUM(CASE operation WHEN 'BUY' THEN units ELSE -units END), "
            "SUM(CASE operation WHEN 'BUY' THEN -value ELSE value END), "
            "(SELECT unit_price FROM fund_holdings f2 WHERE f2.fund_code = f.fund_code ORDER BY date DESC, id DESC LIMIT 1), "
            "MAX(date) FROM fund_holdings f GROUP BY fund_code ORDER BY fund_code").fetchall()
    return [{"fund_code": c, "fund_name": n, "net_units": u, "net_cash": round(v, 3), "last_unit_price": p,
             "last_date": d} for c, n, u, v, p, d in rows]


def report(trips: list[dict[str, Any]], fills: list[dict[str, Any]], cash: list[dict[str, Any]]) -> dict[str, Any]:
    """All metrics for the first report."""
    raise NotImplementedError
