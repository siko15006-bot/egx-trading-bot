from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from egx_4_mirrors_v3 import SECTOR_MAP
from validate_tv_signals import init_db, load_ohlcv


LOGGER = logging.getLogger(__name__)
WEEKDAY_ORDER = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]
STAT_KEYS = (
    "total_alerts",
    "confirmed_signals",
    "win_rate",
    "avg_win_pct",
    "avg_loss_pct",
    "profit_factor",
    "expectancy",
    "avg_holding_days",
    "best_sector",
    "worst_sector",
    "best_weekday",
    "worst_weekday",
    "best_hour",
    "consecutive_wins",
    "consecutive_losses",
    "avg_time_to_tp",
    "avg_time_to_sl",
    "win_rate_by_sector",
    "win_rate_by_weekday",
    "win_rate_by_adx_bucket",
    "win_rate_by_atr_bucket",
)


# يعيد مسار قاعدة البيانات من البيئة.
def _db_path() -> Path:
    load_dotenv()
    return Path(os.getenv("DB_PATH", "egx_signals.db"))


# ينشئ جدول نتائج الإشارات عند الحاجة.
def _init_analytics_db(path: Path | None = None) -> Path:
    db_path = path or _db_path()
    init_db(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_outcomes (
                alert_id INTEGER PRIMARY KEY,
                resolved_date TEXT,
                outcome TEXT NOT NULL CHECK(outcome IN ('WIN', 'LOSS', 'OPEN')),
                exit_price REAL,
                pnl_pct REAL,
                days_held INTEGER NOT NULL,
                max_favorable REAL,
                max_adverse REAL,
                FOREIGN KEY(alert_id) REFERENCES tv_alerts(id)
            )
            """
        )
        connection.commit()
    return db_path


# يضيف أبعاد الوقت والقطاع إلى سجل الإشارات.
def _enrich_alerts(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if data.empty:
        for column in ("hour", "weekday", "sector"):
            data[column] = pd.Series(dtype="object")
        return data
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
    cairo_time = data["timestamp"].dt.tz_convert("Africa/Cairo")
    data["hour"] = cairo_time.dt.hour
    data["weekday"] = cairo_time.dt.day_name()
    data["sector"] = data["ticker"].str.upper().map(SECTOR_MAP).fillna("Other")
    return data


# يقرأ إشارات الفترة المطلوبة من SQLite.
def load_alerts(days: int = 90) -> pd.DataFrame:
    db_path = _init_analytics_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 0))
    with closing(sqlite3.connect(db_path)) as connection:
        alerts = pd.read_sql_query("SELECT * FROM tv_alerts ORDER BY timestamp", connection)
    alerts = _enrich_alerts(alerts)
    if alerts.empty:
        return alerts
    result = alerts[alerts["timestamp"] >= cutoff].reset_index(drop=True)
    LOGGER.info("Loaded %d alerts from the last %d days", len(result), days)
    return result


# يقرأ النتائج مع بيانات الإشارة اللازمة للتحليل.
def load_outcomes(days: int = 90) -> pd.DataFrame:
    db_path = _init_analytics_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(days, 0))).isoformat()
    query = """
        SELECT o.*, a.timestamp, a.ticker, a.action, a.entry, a.sl, a.tp,
               a.atr_pct, a.adx, a.status
        FROM alert_outcomes o
        JOIN tv_alerts a ON a.id = o.alert_id
        WHERE a.timestamp >= ?
        ORDER BY a.timestamp
    """
    with closing(sqlite3.connect(db_path)) as connection:
        outcomes = pd.read_sql_query(query, connection, params=(cutoff,))
    return _enrich_alerts(outcomes)


# يحول قيمة قاعدة البيانات إلى رقم صالح.
def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


# يقيّم إشارة واحدة على عشر جلسات لاحقة.
def _evaluate_alert(alert: pd.Series, prices: pd.DataFrame) -> dict[str, Any]:
    entry = _number(alert.get("entry")) or _number(alert.get("price"))
    stop = _number(alert.get("sl"))
    target = _number(alert.get("tp"))
    if entry is None or stop is None or target is None or entry <= 0:
        raise ValueError("Alert requires valid entry, sl, and tp")

    alert_time = pd.Timestamp(alert["timestamp"])
    if alert_time.tzinfo is None:
        alert_time = alert_time.tz_localize("UTC")
    else:
        alert_time = alert_time.tz_convert("UTC")
    window = prices.loc[prices.index > alert_time].head(10)
    if window.empty:
        return {
            "alert_id": int(alert["id"]),
            "resolved_date": None,
            "outcome": "OPEN",
            "exit_price": entry,
            "pnl_pct": 0.0,
            "days_held": 0,
            "max_favorable": 0.0,
            "max_adverse": 0.0,
        }

    outcome = "OPEN"
    exit_price = float(window["Close"].iloc[-1])
    resolved_date = window.index[-1]
    days_held = len(window)
    for position, (timestamp, row) in enumerate(window.iterrows(), start=1):
        if float(row["Low"]) <= stop:
            outcome, exit_price, resolved_date, days_held = "LOSS", stop, timestamp, position
            break
        if float(row["High"]) >= target:
            outcome, exit_price, resolved_date, days_held = "WIN", target, timestamp, position
            break

    observed = window.iloc[:days_held]
    return {
        "alert_id": int(alert["id"]),
        "resolved_date": pd.Timestamp(resolved_date).isoformat(),
        "outcome": outcome,
        "exit_price": exit_price,
        "pnl_pct": (exit_price / entry - 1) * 100,
        "days_held": days_held,
        "max_favorable": (float(observed["High"].max()) / entry - 1) * 100,
        "max_adverse": (float(observed["Low"].min()) / entry - 1) * 100,
    }


# يقيّم إشارات BUY الجديدة أو المفتوحة ويحدّث نتائجها.
def evaluate_pending_alerts(
    data_folder: str | os.PathLike[str],
    lookback_days: int = 30,
) -> pd.DataFrame:
    db_path = _init_analytics_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(lookback_days, 0))).isoformat()
    query = """
        SELECT a.*
        FROM tv_alerts a
        LEFT JOIN alert_outcomes o ON o.alert_id = a.id
        WHERE a.action = 'BUY' AND a.timestamp >= ?
          AND (o.alert_id IS NULL OR o.outcome = 'OPEN')
        ORDER BY a.timestamp
    """
    with closing(sqlite3.connect(db_path)) as connection:
        pending = pd.read_sql_query(query, connection, params=(cutoff,))

    rows: list[dict[str, Any]] = []
    for _, alert in pending.iterrows():
        try:
            outcome = _evaluate_alert(alert, load_ohlcv(str(alert["ticker"]), data_folder))
            rows.append(outcome)
        except (FileNotFoundError, ValueError, TypeError, KeyError) as exc:
            LOGGER.warning("Could not evaluate alert %s: %s", alert.get("id"), exc)

    if rows:
        statement = """
            INSERT INTO alert_outcomes (
                alert_id, resolved_date, outcome, exit_price, pnl_pct,
                days_held, max_favorable, max_adverse
            ) VALUES (:alert_id, :resolved_date, :outcome, :exit_price, :pnl_pct,
                      :days_held, :max_favorable, :max_adverse)
            ON CONFLICT(alert_id) DO UPDATE SET
                resolved_date=excluded.resolved_date,
                outcome=excluded.outcome,
                exit_price=excluded.exit_price,
                pnl_pct=excluded.pnl_pct,
                days_held=excluded.days_held,
                max_favorable=excluded.max_favorable,
                max_adverse=excluded.max_adverse
        """
        with closing(sqlite3.connect(db_path)) as connection:
            connection.executemany(statement, rows)
            connection.commit()
        LOGGER.info("Evaluated %d pending alerts", len(rows))
    return load_outcomes(lookback_days)


# يحسب أطول سلسلة متتابعة من نتيجة محددة.
def _max_streak(values: pd.Series, target: str) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if value == target else 0
        best = max(best, current)
    return best


# يحسب معدل الفوز حسب بُعد تحليلي.
def _win_rates(frame: pd.DataFrame, column: str) -> dict[str, float]:
    if frame.empty or column not in frame:
        return {}
    return (
        frame.groupby(column, observed=True)["outcome"]
        .apply(lambda values: round(float((values == "WIN").mean() * 100), 2))
        .to_dict()
    )


# يعيد اسماً آمناً لأفضل أو أسوأ مجموعة.
def _group_extreme(rates: dict[str, float], best: bool) -> str:
    if not rates:
        return "N/A"
    return str((max if best else min)(rates, key=rates.get))


# يحسب مؤشرات الأداء الكاملة للإشارات المغلقة.
def compute_stats(df_alerts: pd.DataFrame, df_outcomes: pd.DataFrame | None) -> dict[str, Any]:
    alerts = _enrich_alerts(df_alerts) if not {"sector", "weekday", "hour"}.issubset(df_alerts.columns) else df_alerts.copy()
    # None = لسه مفيش نتائج مغلقة (الحالة الطبيعية قبل أول TP/SL)
    outcomes = pd.DataFrame() if df_outcomes is None else df_outcomes.copy()
    if not outcomes.empty and "sector" not in outcomes and "alert_id" in outcomes and "id" in alerts:
        outcomes = outcomes.merge(
            alerts[["id", "ticker", "timestamp", "sector", "weekday", "hour", "adx", "atr_pct"]],
            left_on="alert_id",
            right_on="id",
            how="left",
        )
    closed = outcomes[outcomes.get("outcome", pd.Series(dtype=str)).isin(["WIN", "LOSS"])].copy()
    wins = closed[closed["outcome"] == "WIN"] if not closed.empty else closed
    losses = closed[closed["outcome"] == "LOSS"] if not closed.empty else closed
    win_rate = float(len(wins) / len(closed) * 100) if len(closed) else 0.0
    avg_win = float(wins["pnl_pct"].mean()) if len(wins) else 0.0
    avg_loss = float(losses["pnl_pct"].mean()) if len(losses) else 0.0
    win_sum = float(wins["pnl_pct"].sum()) if len(wins) else 0.0
    loss_sum = abs(float(losses["pnl_pct"].sum())) if len(losses) else 0.0
    profit_factor = win_sum / loss_sum if loss_sum else (float("inf") if win_sum else 0.0)

    if not closed.empty:
        closed["adx_bucket"] = pd.cut(closed["adx"], [-np.inf, 20, 30, np.inf], labels=["<20", "20-30", ">30"], right=False)
        closed["atr_bucket"] = pd.cut(closed["atr_pct"], [-np.inf, 2, 4, np.inf], labels=["<2", "2-4", ">4"], right=False)
        closed = closed.sort_values("timestamp")
    sector_rates = _win_rates(closed, "sector")
    weekday_rates = _win_rates(closed, "weekday")
    hour_rates = _win_rates(closed, "hour")
    loss_rate = 100 - win_rate
    result: dict[str, Any] = {
        "total_alerts": int(len(alerts)),
        "confirmed_signals": int((alerts.get("status", pd.Series(dtype=str)) == "CONFIRMED").sum()),
        "win_rate": win_rate,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": (win_rate / 100 * avg_win) - (loss_rate / 100 * abs(avg_loss)),
        "avg_holding_days": float(closed["days_held"].mean()) if len(closed) else 0.0,
        "best_sector": _group_extreme(sector_rates, True),
        "worst_sector": _group_extreme(sector_rates, False),
        "best_weekday": _group_extreme(weekday_rates, True),
        "worst_weekday": _group_extreme(weekday_rates, False),
        "best_hour": _group_extreme({str(k): v for k, v in hour_rates.items()}, True),
        "consecutive_wins": _max_streak(closed.get("outcome", pd.Series(dtype=str)), "WIN"),
        "consecutive_losses": _max_streak(closed.get("outcome", pd.Series(dtype=str)), "LOSS"),
        "avg_time_to_tp": float(wins["days_held"].mean()) if len(wins) else 0.0,
        "avg_time_to_sl": float(losses["days_held"].mean()) if len(losses) else 0.0,
        "win_rate_by_sector": sector_rates,
        "win_rate_by_weekday": weekday_rates,
        "win_rate_by_adx_bucket": _win_rates(closed, "adx_bucket"),
        "win_rate_by_atr_bucket": _win_rates(closed, "atr_bucket"),
    }
    return {key: result[key] for key in STAT_KEYS}


# يصنف ثقة النمط بناءً على حجم العينة.
def _confidence(sample_size: int) -> str:
    return "HIGH" if sample_size >= 30 else "MED" if sample_size >= 10 else "LOW"


# يكتشف الأنماط العملية في النتائج المغلقة.
def detect_patterns(df_outcomes: pd.DataFrame) -> list[dict[str, Any]]:
    if df_outcomes.empty or "outcome" not in df_outcomes:
        return []
    closed = df_outcomes[df_outcomes["outcome"].isin(["WIN", "LOSS"])].copy()
    if closed.empty:
        return []
    patterns: list[dict[str, Any]] = []
    overall = float((closed["outcome"] == "WIN").mean() * 100)

    for column, label in (("weekday", "اليوم"), ("sector", "القطاع")):
        if column not in closed:
            continue
        grouped = closed.groupby(column)["outcome"].agg(sample_size="size", win_rate=lambda values: (values == "WIN").mean() * 100)
        if grouped.empty:
            continue
        name = grouped["win_rate"].idxmax()
        row = grouped.loc[name]
        wording = f"{label} {name} هو الأفضل بمعدل فوز {row['win_rate']:.1f}%"
        patterns.append({"pattern": wording, "impact": round(float(row["win_rate"] - overall), 2), "sample_size": int(row["sample_size"]), "confidence": _confidence(int(row["sample_size"]))})

    if "adx" in closed:
        strong = closed[closed["adx"] > 30]
        if not strong.empty:
            rate = float((strong["outcome"] == "WIN").mean() * 100)
            patterns.append({"pattern": f"ADX > 30 يرفع Win Rate إلى {rate:.1f}%", "impact": round(rate - overall, 2), "sample_size": len(strong), "confidence": _confidence(len(strong))})

    if "hour" in closed:
        early = closed[closed["hour"].between(10, 11)]
        noon = closed[closed["hour"].between(12, 13)]
        if not early.empty and not noon.empty:
            early_rate = float((early["outcome"] == "WIN").mean() * 100)
            noon_rate = float((noon["outcome"] == "WIN").mean() * 100)
            patterns.append({"pattern": f"12:00-13:00 أقل من 10:00-11:00 بفارق {early_rate - noon_rate:.1f} نقطة", "impact": round(noon_rate - early_rate, 2), "sample_size": len(early) + len(noon), "confidence": _confidence(len(early) + len(noon))})
    return patterns


# يحول معدلات الفوز إلى جدول تقرير.
def _rates_table(rates: dict[str, float], dimension: str) -> pd.DataFrame:
    return pd.DataFrame([{dimension: key, "Win Rate %": value} for key, value in rates.items()])


# يزيل معلومات المنطقة الزمنية من نسخة Excel فقط.
def _excel_safe(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    for column in data.columns:
        if isinstance(data[column].dtype, pd.DatetimeTZDtype):
            data[column] = data[column].dt.tz_convert("Africa/Cairo").dt.tz_localize(None)
    return data


# يصدر تقرير Excel بخمس أوراق تحليلية.
def export_analytics_report(output_path: str | os.PathLike[str] = "analytics_report.xlsx") -> Path:
    alerts = load_alerts(90)
    outcomes = load_outcomes(90)
    stats = compute_stats(alerts, outcomes)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(
        {"Metric": list(stats), "Value": [json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value for value in stats.values()]}
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        _rates_table(stats["win_rate_by_sector"], "Sector").to_excel(writer, sheet_name="By_Sector", index=False)
        _rates_table(stats["win_rate_by_weekday"], "Weekday").to_excel(writer, sheet_name="By_Weekday", index=False)
        _rates_table(_win_rates(outcomes[outcomes.get("outcome", pd.Series(dtype=str)).isin(["WIN", "LOSS"])], "hour"), "Hour").to_excel(writer, sheet_name="By_Hour", index=False)
        _excel_safe(outcomes).to_excel(writer, sheet_name="Outcomes", index=False)
    LOGGER.info("Analytics report exported: %s", path)
    return path


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    df = load_alerts(days=30)
    print(f"✅ Loaded {len(df)} alerts")
    stats = compute_stats(df, pd.DataFrame())
    print(f"✅ Stats keys: {list(stats.keys())}")
    patterns = detect_patterns(pd.DataFrame())
    print(f"✅ Found {len(patterns)} patterns")
    # running the module must produce the report (it previously only printed and never wrote the xlsx)
    report = export_analytics_report("analytics_report.xlsx")
    print(f"✅ Report: {report}")
