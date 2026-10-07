"""Thndr statement import (docs/personal_ledger_design.md, "Parser"). Placeholders until a real statement arrives:
the column mapping depends on its actual format, so nothing here guesses it."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

Format = Literal["csv", "xlsx", "pdf"]


def detect_format(path: Path) -> Format:
    """CSV / XLSX / PDF from content, not only the extension."""
    raise NotImplementedError("waiting for a real Thndr statement")


def parse_rows(path: Path, fmt: Format) -> list[dict[str, Any]]:
    """Statement rows → normalised dicts (Cairo time, TICKER.CA, side, qty, price, fees). Unknown column → error."""
    raise NotImplementedError("waiting for a real Thndr statement")


def validate_balance(rows: list[dict[str, Any]], holdings: dict[str, int] | None = None,
                     *, earlier_periods: list[tuple[int, str, str]] | None = None) -> list[str]:
    """Problems/warnings found before writing, each prefixed with a stable tag:
    OVERSELL (always checked on the rows alone, independent of `holdings`), GROSS_MISMATCH (qty×price vs gross
    > 0.01 EGP), FEE_DIFF (vs fees_config), HOLDINGS_MISMATCH (only when `holdings` is given) and
    PERIOD_OVERLAP (a warning: earlier import ids whose (from, to) overlaps → rows get review_flag
    POSSIBLE_DUPLICATE and Ahmed confirms; overlapping imports are allowed so older statements can be added).
    Position rows (transfer/bonus/IPO/split) change share counts for OVERSELL but are never BUY lots."""
    raise NotImplementedError("waiting for a real Thndr statement")


def import_file(path: Path) -> int:
    """detect → parse → validate → write imports/raw_rows/fills/cash_events in one transaction; returns import id."""
    raise NotImplementedError("waiting for a real Thndr statement")
