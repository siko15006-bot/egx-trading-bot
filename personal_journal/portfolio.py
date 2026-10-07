"""Positions and P&L from fills (docs/personal_ledger_design.md). Placeholders: logic is written together with the
parser and Codex's tests, against real statement rows."""
from __future__ import annotations

from typing import Any


def fifo_round_trips(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Match SELLs to the oldest open BUYs per ticker; partial sells split a lot. Fees allocated pro rata by qty."""
    raise NotImplementedError


def average_cost(fills: list[dict[str, Any]], ticker: str) -> float:
    """Average cost of the currently open quantity, fees included."""
    raise NotImplementedError


def realized_pnl(trip: dict[str, Any], dividends: float = 0.0) -> float:
    """Net P&L of one round trip: sell − buy − fees + net dividends − tax."""
    raise NotImplementedError
