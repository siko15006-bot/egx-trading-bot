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


def report(trips: list[dict[str, Any]], fills: list[dict[str, Any]], cash: list[dict[str, Any]]) -> dict[str, Any]:
    """All metrics for the first report."""
    raise NotImplementedError
