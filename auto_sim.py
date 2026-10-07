"""Auto-simulation: forward test of the technical path (signal → SL/TP → close → PnL → Telegram/dashboard).

NOT paper trading (that table is for Ahmed's own decisions) and NOT a strategy evaluation: the 4 Mirrors strategy
is ruled ABANDON in decision_report.md. Separate table `auto_sim_trades`.

Rules (fixed, same as egx_4_mirrors_v3.backtest except where noted):
- Each daily run opens the top 2 BUY rows of scan_universe, ranked by RR_Net desc, then ticker A→Z.
  Skipped if that ticker already has an OPEN auto-sim trade. Stored entry starts as the signal close and is replaced
  by the real fill (next session close) once that bar exists.
- Same execution policy as the engine (egx_4_mirrors_v3.simulate_trade, docs/execution_policy.md): entry at the close
  of the session after the signal, exits from the bar after that, SL before TP, stop/target at the level, or at that bar's
  Close on a gap (Open is never used), no fills on zero-volume rows, and a >25% data break cancels the trade
  (status CANCELLED, no P&L).
- Trailing stop exactly as the engine: Close ≥ entry+2·ATR → stop ≥ entry+ATR; Close ≥ entry+ATR → stop ≥ entry.
- PnL via egx_4_mirrors_v3.net_trade_pnl, including net dividends (data/ is dividend-unadjusted).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Mapping, Optional

import pandas as pd

import egx_4_mirrors_v3 as eng
from paper_trading import _db_path

PER_DAY = 2
LABEL = "🧪 Auto-sim (اختبار مسار تقني — مش تقييم استراتيجية، الاستراتيجية حكمها ABANDON)"


def _day(ts: pd.Timestamp) -> str:
    return ts.tz_convert(eng.CAIRO_TZ).strftime("%Y-%m-%d") if ts.tzinfo else ts.strftime("%Y-%m-%d")


def _connect(db_path=None) -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(db_path))
    con.execute("""CREATE TABLE IF NOT EXISTS auto_sim_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, signal_date TEXT NOT NULL,
        entry REAL NOT NULL, stop0 REAL NOT NULL, tp REAL NOT NULL, atr REAL NOT NULL, shares INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN', stop REAL, exit_date TEXT, exit_price REAL, exit_reason TEXT,
        div_ps REAL, pnl_egp REAL, pnl_pct REAL, UNIQUE (ticker, signal_date))""")
    return con


def replay(data: pd.DataFrame, signal_date: str, stop0: float, tp: float, atr: float) -> dict:
    """egx_4_mirrors_v3.simulate_trade for the bar dated signal_date (entry at the next close, in-range fills only)."""
    days = [_day(ts) for ts in data.index]
    if signal_date not in days:
        return {"status": "pending"}
    t = eng.simulate_trade(data, days.index(signal_date), stop0, tp, atr)
    if "exit_index" in t:
        t["exit_date"] = days[t["exit_index"]]
    return t


def update_open(data_map: Mapping[str, pd.DataFrame], risk: eng.RiskConfig, db_path=None) -> int:
    closed = 0
    with closing(_connect(db_path)) as con:
        rows = con.execute("SELECT id, ticker, signal_date, stop0, tp, atr, shares FROM auto_sim_trades "
                           "WHERE status = 'OPEN'").fetchall()
        for tid, ticker, sdate, stop0, tp, atr, shares in rows:
            if ticker not in data_map:
                continue
            data = eng.with_dividends(ticker, data_map[ticker])
            t = replay(data, sdate, stop0, tp, atr)
            if t["status"] == "pending":
                continue
            if t["status"] == "skipped":  # next close already beyond the stop/target, a filler bar, or a data break
                con.execute("UPDATE auto_sim_trades SET status='SKIPPED', exit_reason='ENTRY_INVALID' WHERE id=?", (tid,))
                continue
            if t["status"] == "cancelled":  # data break while open: outcome unknown, no P&L (docs/execution_policy.md)
                con.execute("UPDATE auto_sim_trades SET status='CANCELLED', entry=?, exit_reason='DATA_BREAK' WHERE id=?",
                            (t["entry"], tid))
                continue
            entry = t["entry"]
            if t["status"] == "open":
                con.execute("UPDATE auto_sim_trades SET entry = ?, stop = ? WHERE id = ?", (entry, t["stop"], tid))
                continue
            div_ps = eng.dividends_between(data, t["entry_index"], t["exit_index"])
            pnl = eng.net_trade_pnl(entry, t["exit"], shares, risk, div_ps,
                                    same_session=eng.same_session(data.index[t["entry_index"]], data.index[t["exit_index"]]))
            con.execute("UPDATE auto_sim_trades SET status='CLOSED', entry=?, stop=?, exit_date=?, exit_price=?, "
                        "exit_reason=?, div_ps=?, pnl_egp=?, pnl_pct=? WHERE id=?",
                        (entry, t["stop"], t["exit_date"], t["exit"], t["reason"], div_ps, pnl,
                         pnl / (entry * shares) * 100, tid))
            closed += 1
        con.commit()
    return closed


def open_new(signals: pd.DataFrame, as_of: str, db_path=None) -> list[str]:
    if signals.empty:
        return []
    buys = signals[signals["Status"] == "BUY"].sort_values(["RR_Net", "Ticker"], ascending=[False, True])
    opened: list[str] = []
    with closing(_connect(db_path)) as con:
        held = {r[0] for r in con.execute("SELECT ticker FROM auto_sim_trades WHERE status = 'OPEN'")}
        quota = PER_DAY - con.execute("SELECT COUNT(*) FROM auto_sim_trades WHERE signal_date = ?", (as_of,)).fetchone()[0]
        for r in buys.itertuples():
            if len(opened) >= quota:  # retries on the same day never open more than PER_DAY
                break
            if r.Ticker in held:
                continue
            atr = float(r.ATR)
            cur = con.execute("INSERT OR IGNORE INTO auto_sim_trades (ticker, signal_date, entry, stop0, tp, atr, shares, stop) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (r.Ticker, as_of, r.Entry, r.SL, r.TP, atr, int(r.Shares), r.SL))
            if cur.rowcount:
                opened.append(r.Ticker)
        con.commit()
    return opened


def load(db_path=None) -> pd.DataFrame:
    with closing(_connect(db_path)) as con:
        return pd.read_sql_query("SELECT * FROM auto_sim_trades ORDER BY signal_date DESC, id DESC", con)


def summary_line(db_path=None) -> str:
    t = load(db_path)
    closed = t[t["status"] == "CLOSED"]
    wins = int((closed["pnl_egp"] > 0).sum())
    wr = f"{wins / len(closed) * 100:.0f}%" if len(closed) else "—"
    return (f"{LABEL}\nمفتوحة: {int((t['status'] == 'OPEN').sum())} | مغلقة: {len(closed)} | "
            f"Win Rate: {wr} | صافي: {closed['pnl_egp'].sum():+,.0f} EGP")


def run(data_map: Mapping[str, pd.DataFrame], signals: pd.DataFrame, risk: eng.RiskConfig, db_path=None) -> dict:
    """Daily step: close what hit SL/TP, then open today's top picks (as_of = latest bar date)."""
    closed = update_open(data_map, risk, db_path)
    as_of = max((_day(d.index[-1]) for d in data_map.values()), default="")
    opened = open_new(signals, as_of, db_path) if as_of else []
    return {"closed": closed, "opened": opened, "as_of": as_of}
