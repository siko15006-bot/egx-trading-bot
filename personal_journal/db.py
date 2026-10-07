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
    row_count INTEGER NOT NULL,
    overlaps_imports TEXT          -- ids of earlier imports whose period overlaps (warning, Ahmed confirms; not a block)
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
    review_flag TEXT CHECK (review_flag IN ('POSSIBLE_DUPLICATE')),  -- set when the statement period overlaps an earlier import
    -- identity = "row X of statement Y": two real executions can share day, ticker, qty and price, so the
    -- trade's own fields must never be a unique key. Re-importing a file is blocked by imports.sha256 instead.
    UNIQUE (import_id, row_no)
);
-- Event types: BUY/SELL → fills; POSITION → position_events; CASH → cash_events. A position event changes the share
-- count without a trade at a price, so it is never a BUY lot (a bonus lowers the average cost, it is not a purchase).
CREATE TABLE IF NOT EXISTS position_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    row_no INTEGER NOT NULL,
    ts_cairo TEXT NOT NULL,
    ticker TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('transfer_in', 'transfer_out', 'bonus_shares', 'subscription_allocation', 'split')),
    qty INTEGER CHECK (qty IS NULL OR qty > 0),          -- shares in/out; NULL for a pure ratio event (split)
    ratio_num INTEGER, ratio_den INTEGER,                 -- split / bonus ratio when the statement gives one
    cost_basis REAL,                                      -- NULL = unknown (a transfer's cost is NOT zero)
    review_flag TEXT CHECK (review_flag IN ('POSSIBLE_DUPLICATE')),
    UNIQUE (import_id, row_no),
    -- COALESCE: in SQL a NULL comparison is NULL and a NULL CHECK passes, so a row with neither field would slip in
    CHECK (qty IS NOT NULL OR (COALESCE(ratio_num, 0) > 0 AND COALESCE(ratio_den, 0) > 0))
);
CREATE TABLE IF NOT EXISTS cash_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES imports(id),
    row_no INTEGER NOT NULL,
    ts_cairo TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('dividend', 'stamp_refund', 'commission_kickback', 'custody_fee',
                                       'subscription', 'deposit', 'withdrawal', 'other')),
    ticker TEXT,
    amount REAL NOT NULL,
    review_flag TEXT CHECK (review_flag IN ('POSSIBLE_DUPLICATE')),
    UNIQUE (import_id, row_no)
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


# Explicit migrations on top of the frozen SCHEMA (PRAGMA user_version = number applied). Never edit one once applied.
MIGRATIONS = [
    # 1 (2026-10-07, Ahmed): fund sub-account + new cash kinds + per-account balances for the import chain check.
    """
    CREATE TABLE fund_holdings (     -- Thndr fund sub-account (*_02 statements): units, not shares; no fees, no FIFO
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id INTEGER NOT NULL REFERENCES imports(id),
        row_no INTEGER NOT NULL,
        date TEXT NOT NULL,
        fund_code TEXT NOT NULL,
        fund_name TEXT,
        operation TEXT NOT NULL CHECK (operation IN ('BUY', 'SELL')),
        units REAL NOT NULL CHECK (units > 0),
        unit_price REAL,
        value REAL NOT NULL,
        balance REAL,
        UNIQUE (import_id, row_no)
    );
    CREATE TABLE cash_events_v1 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id INTEGER NOT NULL REFERENCES imports(id),
        row_no INTEGER NOT NULL,
        ts_cairo TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('dividend', 'stamp_refund', 'commission_kickback', 'custody_fee',
                                           'subscription', 'deposit', 'withdrawal', 'other',
                                           'subscription_fee', 'commission_refund', 'transfer_to_fund',
                                           'transfer_from_fund')),
        ticker TEXT,
        amount REAL NOT NULL,
        review_flag TEXT CHECK (review_flag IN ('POSSIBLE_DUPLICATE')),
        UNIQUE (import_id, row_no)
    );
    INSERT INTO cash_events_v1 SELECT * FROM cash_events;
    DROP TABLE cash_events;
    ALTER TABLE cash_events_v1 RENAME TO cash_events;
    ALTER TABLE imports ADD COLUMN account TEXT;            -- 'main' | 'fund'
    ALTER TABLE imports ADD COLUMN opening_balance REAL;
    ALTER TABLE imports ADD COLUMN closing_balance REAL;
    """,
]


def init_db(path: Path = DB_PATH) -> Path:
    with sqlite3.connect(path) as con:
        con.executescript(SCHEMA)
        done = con.execute("PRAGMA user_version").fetchone()[0]
        for n, sql in enumerate(MIGRATIONS[done:], start=done + 1):
            con.executescript(f"BEGIN; {sql} PRAGMA user_version = {n}; COMMIT;")
    return path
