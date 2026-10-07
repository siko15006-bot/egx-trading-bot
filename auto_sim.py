"""Auto-simulation: forward test of the technical path (signal → SL/TP → close → PnL → Telegram/dashboard).

NOT paper trading (that table is for Ahmed's own decisions) and NOT a strategy evaluation: the 4 Mirrors strategy
is ruled ABANDON in decision_report.md. Separate table `auto_sim_trades`.

Rules (fixed, same as egx_4_mirrors_v3.backtest except where noted):
- Each daily run opens the top 2 BUY rows of scan_universe, ranked by RR_Net desc, then ticker A→Z.
  Skipped if that ticker already has an OPEN auto-sim trade. Entry = signal-day close (= plan.entry).
- Exits are replayed from the bars after the signal day (not the signal bar itself — the engine checks it,
  which is a known look-ahead), SL checked before TP on each bar; a gap through the stop/target fills at the Open.
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


def replay(data: pd.DataFrame, signal_date: str, entry: float, stop0: float, tp: float, atr: float
           ) -> tuple[float, Optional[tuple[str, float, str, int]]]:
    """Returns (current stop, exit) where exit = (date, price, reason, bar index) or None while still open."""
    days = [_day(ts) for ts in data.index]
    if signal_date not in days:
        return stop0, None
    i = days.index(signal_date)
    stop = stop0
    for j in range(i + 1, len(data)):
        row = data.iloc[j]
        reason = "TRAIL_SL" if stop > stop0 else "SL"
        if row["Open"] <= stop:
            return stop, (days[j], float(row["Open"]), reason, j)
        if row["Low"] <= stop:
            return stop, (days[j], stop, reason, j)
        if row["Open"] >= tp:
            return stop, (days[j], float(row["Open"]), "TP", j)
        if row["High"] >= tp:
            return stop, (days[j], tp, "TP", j)
        if row["Close"] >= entry + 2 * atr:
            stop = max(stop, entry + atr)
        elif row["Close"] >= entry + atr:
            stop = max(stop, entry)
    return stop, None


def update_open(data_map: Mapping[str, pd.DataFrame], risk: eng.RiskConfig, db_path=None) -> int:
    closed = 0
    with closing(_connect(db_path)) as con:
        rows = con.execute("SELECT id, ticker, signal_date, entry, stop0, tp, atr, shares FROM auto_sim_trades "
                           "WHERE status = 'OPEN'").fetchall()
        for tid, ticker, sdate, entry, stop0, tp, atr, shares in rows:
            if ticker not in data_map:
                continue
            data = eng.with_dividends(ticker, data_map[ticker])
            stop, exit_ = replay(data, sdate, entry, stop0, tp, atr)
            if exit_ is None:
                con.execute("UPDATE auto_sim_trades SET stop = ? WHERE id = ?", (stop, tid))
                continue
            date, price, reason, j = exit_
            i = [_day(ts) for ts in data.index].index(sdate)
            div_ps = eng.dividends_between(data, i, j)
            pnl = eng.net_trade_pnl(entry, price, shares, risk, div_ps,
                                    same_session=eng.same_session(sdate, date))
            con.execute("UPDATE auto_sim_trades SET status='CLOSED', stop=?, exit_date=?, exit_price=?, exit_reason=?, "
                        "div_ps=?, pnl_egp=?, pnl_pct=? WHERE id=?",
                        (stop, date, price, reason, div_ps, pnl, pnl / (entry * shares) * 100, tid))
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
