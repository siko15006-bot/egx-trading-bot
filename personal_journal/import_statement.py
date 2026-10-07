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


def validate_balance(fills: list[dict[str, Any]], holdings: dict[str, int] | None = None) -> list[str]:
    """Problems found before writing: qty×price vs gross, fee recomputation vs fees_config (> 0.01 EGP),
    final holdings vs the app, sells larger than the open position. Empty list = OK."""
    raise NotImplementedError("waiting for a real Thndr statement")


def import_file(path: Path) -> int:
    """detect → parse → validate → write imports/raw_rows/fills/cash_events in one transaction; returns import id."""
    raise NotImplementedError("waiting for a real Thndr statement")
