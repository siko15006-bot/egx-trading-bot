"""Schema guards only; parser/FIFO behaviour is covered by Codex's acceptance tests (test_ledger_parser.py)."""
from __future__ import annotations

import sqlite3

import pytest

from personal_journal.db import init_db

FILL = ("INSERT INTO fills (import_id, row_no, ts_cairo, ticker, side, qty, price, gross_value, total_fees) "
        "VALUES (1, ?, '2026-10-05T12:00:00+03:00', 'ABUK.CA', ?, 100, 50, 5000, 11.75)")


@pytest.fixture()
def con(tmp_path):
    c = sqlite3.connect(init_db(tmp_path / "l.db"))
    c.execute("INSERT INTO imports (id, file_name, sha256, imported_at, row_count) VALUES (1, 'a.csv', 'h', 'now', 3)")
    yield c
    c.close()


def test_schema_guards(con) -> None:
    with pytest.raises(sqlite3.IntegrityError):  # same statement twice
        con.execute("INSERT INTO imports (file_name, sha256, imported_at, row_count) VALUES ('b.csv', 'h', 'now', 0)")
    with pytest.raises(sqlite3.IntegrityError):  # side must be BUY or SELL
        con.execute(FILL, (1, "HOLD"))


def test_position_event_is_stored_and_never_a_buy_lot(con) -> None:
    con.execute(FILL, (1, "BUY"))
    con.execute("INSERT INTO position_events (import_id, row_no, ts_cairo, ticker, kind, qty) "
                "VALUES (1, 2, '2026-10-06T12:00:00+03:00', 'ABUK.CA', 'bonus_shares', 20)")
    con.execute("INSERT INTO position_events (import_id, row_no, ts_cairo, ticker, kind, qty) "
                "VALUES (1, 3, '2026-10-06T12:00:00+03:00', 'ABUK.CA', 'transfer_in', 30)")
    rows = con.execute("SELECT kind, qty, cost_basis FROM position_events ORDER BY row_no").fetchall()
    assert rows == [("bonus_shares", 20, None), ("transfer_in", 30, None)]   # unknown transfer cost stays NULL, not 0
    # Cost basis comes only from BUY fills: the bonus and the transfer add shares but no purchase price.
    buys = con.execute("SELECT SUM(qty), SUM(gross_value + total_fees) FROM fills WHERE side = 'BUY'").fetchone()
    assert buys == (100, 5011.75)
    with pytest.raises(sqlite3.IntegrityError):  # a position can never be written as a fill
        con.execute(FILL, (4, "POSITION"))
    with pytest.raises(sqlite3.IntegrityError):  # unknown kind rejected
        con.execute("INSERT INTO position_events (import_id, row_no, ts_cairo, ticker, kind, qty) "
                    "VALUES (1, 5, 't', 'ABUK.CA', 'gift', 1)")
    with pytest.raises(sqlite3.IntegrityError):  # needs a quantity or a ratio
        con.execute("INSERT INTO position_events (import_id, row_no, ts_cairo, ticker, kind) "
                    "VALUES (1, 6, 't', 'ABUK.CA', 'split')")
    con.execute("INSERT INTO position_events (import_id, row_no, ts_cairo, ticker, kind, ratio_num, ratio_den) "
                "VALUES (1, 7, 't', 'ABUK.CA', 'split', 3, 2)")


def test_overlap_is_a_flag_not_a_block(con) -> None:
    con.execute("UPDATE imports SET overlaps_imports = '1' WHERE id = 1")
    con.execute("INSERT INTO fills (import_id, row_no, ts_cairo, ticker, side, qty, price, gross_value, total_fees, "
                "review_flag) VALUES (1, 1, 't', 'ABUK.CA', 'BUY', 1, 1, 1, 0, 'POSSIBLE_DUPLICATE')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO fills (import_id, row_no, ts_cairo, ticker, side, qty, price, gross_value, total_fees, "
                    "review_flag) VALUES (1, 2, 't', 'ABUK.CA', 'BUY', 1, 1, 1, 0, 'MAYBE')")
