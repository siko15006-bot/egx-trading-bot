"""Schema guards only; parser/FIFO tests come from Codex's ledger test design."""
from __future__ import annotations

import sqlite3

import pytest

from personal_journal.db import init_db


def test_schema_guards(tmp_path) -> None:
    con = sqlite3.connect(init_db(tmp_path / "l.db"))
    con.execute("INSERT INTO imports (file_name, sha256, imported_at, row_count) VALUES ('a.csv', 'h', 'now', 0)")
    with pytest.raises(sqlite3.IntegrityError):  # same statement twice
        con.execute("INSERT INTO imports (file_name, sha256, imported_at, row_count) VALUES ('b.csv', 'h', 'now', 0)")
    with pytest.raises(sqlite3.IntegrityError):  # side must be BUY or SELL
        con.execute("INSERT INTO fills (import_id, row_no, ts_cairo, ticker, side, qty, price, gross_value, total_fees) "
                    "VALUES (1, 1, 't', 'X.CA', 'HOLD', 1, 1, 1, 0)")
