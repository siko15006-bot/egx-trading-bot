from __future__ import annotations

import os
import sqlite3
import html
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from egx_4_mirrors_v3 import SECTOR_MAP, RiskConfig, trade_fees, net_trade_pnl, same_session


CAIRO_TZ = ZoneInfo("Africa/Cairo")
CAPITAL_GAINS_TAX = 0.10
PAPER_TARGET_DAYS = 183
PAPER_TARGET_TRADES = 15


@dataclass(frozen=True)
class PaperTradeInput:
    ticker: str
    entry_time: datetime
    entry: float
    shares: int
    stop_loss: float
    take_profit: float
    mirrors: int = 0
    setup: str = "Manual"
    notes: str = ""


# يعيد مسار قاعدة البيانات مع تثبيت المسارات النسبية بجوار المشروع.
def _db_path(db_path: str | os.PathLike[str] | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    env_path = Path(__file__).with_name(".env")
    load_dotenv(env_path)
    configured = Path(os.getenv("DB_PATH", "egx_signals.db"))
    return configured if configured.is_absolute() else Path(__file__).with_name(configured.name)


# يحول توقيت القاهرة إلى ISO UTC للتخزين.
def _utc_iso(value: datetime | pd.Timestamp) -> str:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(CAIRO_TZ)
    return stamp.tz_convert("UTC").isoformat()


# ينشئ جدول الصفقات الورقية عند أول استخدام.
def init_paper_db(db_path: str | os.PathLike[str] | None = None) -> Path:
    path = _db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                sector TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('OPEN', 'CLOSED')),
                entry_time TEXT NOT NULL,
                entry REAL NOT NULL,
                shares INTEGER NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                mirrors INTEGER NOT NULL CHECK(mirrors BETWEEN 0 AND 4),
                setup TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                exit_time TEXT,
                exit_price REAL,
                commission_egp REAL,
                tax_egp REAL,
                pnl_egp REAL,
                pnl_pct REAL,
                r_multiple REAL,
                outcome TEXT CHECK(outcome IN ('WIN', 'LOSS', 'BREAKEVEN')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_campaign (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                start_date TEXT NOT NULL,
                target_days INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT OR IGNORE INTO paper_campaign (id, start_date, target_days) VALUES (1, ?, ?)",
            (datetime.now(CAIRO_TZ).date().isoformat(), PAPER_TARGET_DAYS),
        )
        connection.execute(
            "UPDATE paper_campaign SET target_days = ? WHERE id = 1",
            (PAPER_TARGET_DAYS,),
        )
        connection.commit()
    return path


# يتحقق من مستويات الصفقة قبل كتابتها.
def _validate_trade(trade: PaperTradeInput) -> None:
    if not trade.ticker.strip():
        raise ValueError("Ticker is required")
    if trade.entry <= 0 or trade.shares <= 0:
        raise ValueError("Entry and shares must be positive")
    if not 0 <= trade.mirrors <= 4:
        raise ValueError("Mirrors must be between 0 and 4")
    if trade.stop_loss <= 0 or trade.stop_loss >= trade.entry:
        raise ValueError("Stop loss must be positive and below entry")
    if trade.take_profit <= trade.entry:
        raise ValueError("Take profit must be above entry")


# يضيف صفقة ورقية مفتوحة ويعيد رقمها.
def add_paper_trade(
    trade: PaperTradeInput,
    db_path: str | os.PathLike[str] | None = None,
) -> int:
    _validate_trade(trade)
    path = init_paper_db(db_path)
    ticker = trade.ticker.strip().upper()
    if not ticker.endswith(".CA"):
        ticker += ".CA"
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO paper_trades (
                ticker, sector, status, entry_time, entry, shares, stop_loss,
                take_profit, mirrors, setup, notes, created_at, updated_at
            ) VALUES (?, ?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                SECTOR_MAP.get(ticker, "Other"),
                _utc_iso(trade.entry_time),
                float(trade.entry),
                int(trade.shares),
                float(trade.stop_loss),
                float(trade.take_profit),
                int(trade.mirrors),
                trade.setup.strip() or "Manual",
                trade.notes.strip(),
                now,
                now,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


# يغلق صفقة ويحسب العمولة والضريبة وصافي PnL وR.
def close_paper_trade(
    trade_id: int,
    exit_time: datetime,
    exit_price: float,
    db_path: str | os.PathLike[str] | None = None,
    *, risk: RiskConfig | None = None, entry_fills=None, exit_fills=None,
) -> dict[str, float | str]:
    if exit_price <= 0:
        raise ValueError("Exit price must be positive")
    path = init_paper_db(db_path)
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM paper_trades WHERE id = ? AND status = 'OPEN'", (int(trade_id),)
        ).fetchone()
        if row is None:
            raise ValueError("Open paper trade not found")
        if pd.Timestamp(_utc_iso(exit_time)) < pd.Timestamp(row["entry_time"]):
            raise ValueError("Exit time cannot be before entry time")

        entry_value = float(row["entry"]) * int(row["shares"])
        exit_value = float(exit_price) * int(row["shares"])
        risk = risk or RiskConfig(capital_gains_tax_pct=CAPITAL_GAINS_TAX)
        t0 = same_session(row['entry_time'], exit_time)
        commission = trade_fees(float(row['entry']), float(exit_price), int(row['shares']), risk,
                                same_session=t0, entry_fills=entry_fills, exit_fills=exit_fills)
        gross = exit_value - entry_value
        taxable_profit = max(gross - commission, 0.0)
        tax = taxable_profit * risk.capital_gains_tax_pct
        pnl = net_trade_pnl(float(row['entry']), float(exit_price), int(row['shares']), risk,
                            same_session=t0, entry_fills=entry_fills, exit_fills=exit_fills)
        pnl_pct = pnl / entry_value * 100
        initial_risk = (float(row["entry"]) - float(row["stop_loss"])) * int(row["shares"])
        r_multiple = pnl / initial_risk if initial_risk > 0 else np.nan
        outcome = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"
        now = datetime.now(timezone.utc).isoformat()

        connection.execute(
            """
            UPDATE paper_trades
            SET status='CLOSED', exit_time=?, exit_price=?, commission_egp=?, tax_egp=?,
                pnl_egp=?, pnl_pct=?, r_multiple=?, outcome=?, updated_at=?
            WHERE id=?
            """,
            (
                _utc_iso(exit_time),
                float(exit_price),
                commission,
                tax,
                pnl,
                pnl_pct,
                r_multiple,
                outcome,
                now,
                int(trade_id),
            ),
        )
        connection.commit()
    return {
        "outcome": outcome,
        "pnl_egp": pnl,
        "pnl_pct": pnl_pct,
        "r_multiple": r_multiple,
    }


# يقرأ السجل كاملًا مع تحويل التواريخ إلى UTC.
def load_paper_trades(db_path: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    path = init_paper_db(db_path)
    with closing(sqlite3.connect(path)) as connection:
        frame = pd.read_sql_query("SELECT * FROM paper_trades ORDER BY entry_time DESC", connection)
    for column in ("entry_time", "exit_time", "created_at", "updated_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    return frame


# يلخص أداء DataFrame من الصفقات المغلقة فقط.
def performance_summary(trades: pd.DataFrame) -> dict[str, Any]:
    closed = trades[trades["status"] == "CLOSED"].copy() if not trades.empty else pd.DataFrame()
    if closed.empty:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "avg_r": 0.0,
            "avg_pnl_pct": 0.0,
            "grade": "NO DATA",
            "message": "لا توجد صفقات مغلقة في الفترة.",
        }
    wins = closed.loc[closed["pnl_egp"] > 0, "pnl_egp"]
    losses = closed.loc[closed["pnl_egp"] < 0, "pnl_egp"]
    profit_factor = float(wins.sum() / abs(losses.sum())) if not losses.empty else float("inf")
    win_rate = float((closed["pnl_egp"] > 0).mean() * 100)
    net_pnl = float(closed["pnl_egp"].sum())
    avg_r = float(closed["r_multiple"].mean())
    if len(closed) >= 5 and profit_factor >= 1.5 and win_rate >= 45 and avg_r >= 0.2:
        grade, message = "A", "أداء قوي ومنضبط؛ حافظ على نفس المخاطرة."
    elif profit_factor >= 1 and net_pnl > 0:
        grade, message = "B", "أسبوع إيجابي؛ راجع الصفقات الأقل من 1R."
    elif net_pnl >= 0:
        grade, message = "C", "النتيجة محايدة؛ حسّن الانتقائية قبل زيادة الحجم."
    else:
        grade, message = "D", "أسبوع سلبي؛ خفّض المخاطرة وراجع قواعد الدخول."
    return {
        "trades": int(len(closed)),
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "profit_factor": profit_factor,
        "avg_r": avg_r,
        "avg_pnl_pct": float(closed["pnl_pct"].mean()),
        "grade": grade,
        "message": message,
    }


# يعيد صفقات أسبوع يبدأ الأحد وملخصها.
def weekly_performance(trades: pd.DataFrame, selected_date: date) -> tuple[pd.DataFrame, dict[str, Any], date, date]:
    week_start = selected_date - timedelta(days=(selected_date.weekday() + 1) % 7)
    week_end = week_start + timedelta(days=6)
    if trades.empty:
        weekly = trades.copy()
    else:
        exit_cairo = trades["exit_time"].dt.tz_convert(CAIRO_TZ)
        start_stamp = pd.Timestamp(week_start, tz=CAIRO_TZ)
        end_stamp = pd.Timestamp(week_end + timedelta(days=1), tz=CAIRO_TZ)
        mask = exit_cairo.ge(start_stamp) & exit_cairo.lt(end_stamp)
        weekly = trades.loc[mask].copy()
    return weekly, performance_summary(weekly), week_start, week_end


# يعيد تقدم تجربة Paper Trading ذات الستة أشهر وهدف الصفقات المغلقة.
def campaign_progress(
    db_path: str | os.PathLike[str] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    path = init_paper_db(db_path)
    with closing(sqlite3.connect(path)) as connection:
        start_raw, target_days = connection.execute(
            "SELECT start_date, target_days FROM paper_campaign WHERE id = 1"
        ).fetchone()
        closed_trades = int(
            connection.execute("SELECT COUNT(*) FROM paper_trades WHERE status = 'CLOSED'").fetchone()[0]
        )
    start = date.fromisoformat(start_raw)
    target = int(target_days)
    today = as_of or datetime.now(CAIRO_TZ).date()
    elapsed = min(max((today - start).days + 1, 0), target)
    return {
        "start_date": start,
        "end_date": start + timedelta(days=target - 1),
        "elapsed_days": elapsed,
        "remaining_days": target - elapsed,
        "target_days": target,
        "progress": elapsed / target,
        "closed_trades": closed_trades,
        "target_trades": PAPER_TARGET_TRADES,
        "trades_progress": min(closed_trades / PAPER_TARGET_TRADES, 1.0),
    }


# يبني رسالة Telegram عند فتح صفقة ورقية.
def format_open_message(trade: Mapping[str, Any]) -> str:
    entry = float(trade["entry"])
    stop = float(trade["stop_loss"])
    target = float(trade["take_profit"])
    rr = (target - entry) / (entry - stop)
    ticker = html.escape(str(trade["ticker"]))
    setup = html.escape(str(trade.get("setup", "Manual")))
    return (
        "📝 <b>Paper Trade Opened</b>\n"
        f"📊 #{int(trade['id'])} · <b>{ticker}</b> · {setup}\n"
        f"💰 Entry: {entry:,.2f} EGP · Shares: {int(trade['shares']):,}\n"
        f"🛑 SL: {stop:,.2f} · 🎯 TP: {target:,.2f}\n"
        f"📈 Planned R:R = 1:{rr:.2f} · Mirrors {int(trade['mirrors'])}/4\n"
        "🧪 Paper Trading only"
    )


# يبني رسالة Telegram عند إغلاق صفقة ورقية.
def format_close_message(trade: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    ticker = html.escape(str(trade["ticker"]))
    outcome = html.escape(str(result["outcome"]))
    return (
        "✅ <b>Paper Trade Closed</b>\n"
        f"📊 #{int(trade['id'])} · <b>{ticker}</b> · {outcome}\n"
        f"💰 Exit: {float(trade['exit_price']):,.2f} EGP\n"
        f"📌 Net PnL: {float(result['pnl_egp']):+,.2f} EGP "
        f"({float(result['pnl_pct']):+.2f}%)\n"
        f"📐 Result: {float(result['r_multiple']):+.2f}R\n"
        "🧪 Paper Trading only"
    )


# يبني رسالة Telegram لملخص الأداء الأسبوعي.
def format_weekly_message(stats: Mapping[str, Any], week_start: date, week_end: date) -> str:
    profit_factor = stats["profit_factor"]
    pf_text = "∞" if profit_factor == float("inf") else f"{float(profit_factor):.2f}"
    return (
        "📊 <b>Paper Trading Weekly Review</b>\n"
        f"📅 {week_start} → {week_end}\n"
        f"🧾 Closed trades: {int(stats['trades'])}\n"
        f"✅ Win Rate: {float(stats['win_rate']):.1f}%\n"
        f"⚖️ Profit Factor: {pf_text} · Avg R: {float(stats['avg_r']):+.2f}R\n"
        f"💰 Net PnL: {float(stats['net_pnl']):+,.2f} EGP\n"
        f"🏅 Grade: {html.escape(str(stats['grade']))}\n"
        f"{html.escape(str(stats['message']))}"
    )
