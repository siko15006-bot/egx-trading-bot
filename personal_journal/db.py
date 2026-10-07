"""SQLite schema for the personal ledger (docs/personal_ledger_design.md, "Schema"). Schema only, no data."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).with_name("personal_ledger.db")  # gitignored (*.db); personal financial data

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,              -- the same statement file can never be imported twice
    imported_at TEXT NOT NULL,
    period_from TEXT,
    period_to TEXT,
    row_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS raw_rows (           -- untouched copy of every statement row (audit trail)
    import_id INTEGER NOT NULL REFERENCES imports(id),
    row_no INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (import_id, row_no)
);
CREATE TABLE IF NOT EXISTS fills (               -- one row per executed transaction
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    row_no INTEGER NOT NULL,
    ts_cairo TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    qty INTEGER NOT NULL CHECK (qty > 0),
    price REAL NOT NULL CHECK (price > 0),
    gross_value REAL NOT NULL,
    brokerage REAL, egx REAL, mcdr REAL, fra REAL, insurance REAL, stamp REAL, other_fees REAL,
    total_fees REAL NOT NULL,
    order_ref TEXT,
    -- identity = "row X of statement Y": two real executions can share day, ticker, qty and price, so the
    -- trade's own fields must never be a unique key. Re-importing a file is blocked by imports.sha256 instead.
    UNIQUE (import_id, row_no)
);
CREATE TABLE IF NOT EXISTS cash_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    ts_cairo TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('dividend', 'stamp_refund', 'commission_kickback', 'custody_fee',
                                       'subscription', 'deposit', 'withdrawal', 'other')),
    ticker TEXT,
    amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS round_trips (         -- derived by FIFO matching; rebuilt, never edited
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    open_ts TEXT NOT NULL,
    close_ts TEXT,
    qty INTEGER NOT NULL,
    avg_buy REAL NOT NULL,
    avg_sell REAL,
    fees REAL NOT NULL,
    dividends REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0,
    net_pnl REAL,
    net_pct REAL,
    holding_sessions INTEGER,
    same_session INTEGER
);
CREATE TABLE IF NOT EXISTS trip_sources (        -- derived: which signal a BUY followed, if any
    trip_id INTEGER NOT NULL REFERENCES round_trips(id),
    source TEXT NOT NULL,
    ref TEXT,
    lag_minutes INTEGER
);
"""


def init_db(path: Path = DB_PATH) -> Path:
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
    return path
