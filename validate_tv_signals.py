from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from egx_4_mirrors_v3 import (
    RiskConfig,
    ScreenConfig,
    SECTOR_MAP,
    SignalConfig,
    build_trade_plan,
    calculate_indicators,
    evaluate_4_mirrors,
)


LOGGER = logging.getLogger(__name__)
CAIRO_TZ = ZoneInfo("Africa/Cairo")
UTC_TZ = ZoneInfo("UTC")
OHLCV = ("Open", "High", "Low", "Close", "Volume")


# ينشئ جدول تنبيهات TradingView عند أول تشغيل.
def init_db(db_path: str | os.PathLike[str]) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tv_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                ticker TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL,
                entry REAL,
                sl REAL,
                tp REAL,
                atr_pct REAL,
                adx REAL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                py_mirrors_json TEXT NOT NULL,
                notes TEXT
            )
            """
        )
        connection.commit()
    LOGGER.info("SQLite database ready: %s", path)


# يحول القيم النصية الرقمية القادمة من TradingView بأمان.
def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if np.isfinite(number) else None
    except (TypeError, ValueError):
        return None


# يوحد أعمدة CSV والفهرس الزمني إلى UTC.
def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for column in frame.columns:
        key = str(column).strip().lower().replace(" ", "_")
        if key in {"date", "datetime", "time", "timestamp"}:
            rename[column] = "Date"
        elif key in {"open", "high", "low", "close", "volume"}:
            rename[column] = key.title()
    data = frame.rename(columns=rename)
    missing = [column for column in OHLCV if column not in data.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")
    if "Date" not in data.columns:
        raise ValueError("CSV requires Date/Datetime/Time/Timestamp column")

    timestamps = pd.to_datetime(data.pop("Date"), errors="coerce")
    valid = timestamps.notna()
    data = data.loc[valid, list(OHLCV)].copy()
    timestamps = timestamps.loc[valid]
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(CAIRO_TZ, nonexistent="shift_forward", ambiguous=False)
    data.index = pd.DatetimeIndex(timestamps.dt.tz_convert(UTC_TZ))
    for column in OHLCV:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.dropna().sort_index()


# أسماء الملفات المحتملة للسهم: TradingView يرسل {{ticker}} بدون لاحقة (COMI) أو مع البورصة (EGX:COMI)،
# بينما ملفات البيانات و SECTOR_MAP بصيغة COMI.CA.
def _ticker_candidates(ticker: str) -> list[str]:
    symbol = ticker.strip().split(":")[-1]
    base = symbol.split(".")[0]
    return list(dict.fromkeys(name for name in (symbol, f"{base}.CA", base) if name))


# الصيغة الموحّدة للسهم: COMI / comi.ca / EGX:COMI / EGX:COMI.CA → COMI.CA (نفس أسماء ملفات data/ و SECTOR_MAP).
def normalize_ticker(ticker: str) -> str:
    base = str(ticker).strip().split(":")[-1].split(".")[0].upper()
    return f"{base}.CA" if base else ""


# يقرأ آخر 250 شمعة للسهم من مجلد البيانات.
def load_ohlcv(ticker: str, data_folder: str | os.PathLike[str]) -> pd.DataFrame:
    folder = Path(data_folder)
    names = _ticker_candidates(ticker)
    candidates = [folder / f"{variant}.csv" for name in names for variant in (name, name.upper(), name.lower())]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        wanted = {name.casefold() for name in names}
        path = next((item for item in folder.glob("*.csv") if item.stem.casefold() in wanted), None)
    if path is None:
        raise FileNotFoundError(f"No CSV found for ticker {ticker} in {folder}")
    data = _normalize_ohlcv(pd.read_csv(path)).tail(250)
    if len(data) < 60:
        raise ValueError(f"Ticker {ticker} requires at least 60 valid candles")
    LOGGER.info("Loaded %d candles for %s", len(data), ticker)
    return data


# يقارن إشارة TradingView بنتيجة محرك Python.
def validate_signal(tv_alert: dict[str, Any]) -> dict[str, Any]:
    load_dotenv()
    ticker = normalize_ticker(tv_alert.get("ticker", ""))
    action = str(tv_alert.get("action", "")).strip().upper()
    base_result: dict[str, Any] = {
        "status": "REJECT",
        "confidence": 0.0,
        "py_mirrors": {},
        "tv": tv_alert,
        "notes": "",
    }
    if not ticker or action not in {"BUY", "SL_HIT", "TP_HIT"}:
        base_result["notes"] = "Invalid ticker or action"
        return base_result
    if action != "BUY":
        base_result["notes"] = f"Lifecycle event {action}; no new entry validation"
        return base_result

    try:
        data = load_ohlcv(ticker, os.getenv("DATA_FOLDER", "./data"))
        calculated = calculate_indicators(data)
        signal_cfg = SignalConfig()
        evaluation = evaluate_4_mirrors(calculated, signal_cfg)
        mirrors = {key: bool(value) for key, value in evaluation["mirrors"].items()}
        score = sum(mirrors.values())
        row = evaluation["row"]
        python_buy = evaluation["signal"] == "BUY"
        base_result.update(
            {
                "status": "CONFIRMED" if python_buy else "MISMATCH",
                "confidence": round(score / 4 * 100, 2),
                "py_mirrors": mirrors,
                "notes": f"Python signal: {evaluation['signal']}",
                "adx": float(row["ADX"]) if row is not None else None,
                "atr_pct": float(row["ATR_Pct"]) if row is not None else None,
            }
        )
        if python_buy:
            plan = build_trade_plan(ticker, calculated, signal_cfg, RiskConfig())
            if plan is not None:
                base_result["trade_plan"] = {
                    "entry": plan.entry,
                    "sl": plan.stop_loss,
                    "tp": plan.take_profit,
                    "rr": plan.rr_net,
                    "shares": plan.shares,
                }
        LOGGER.info("Validated %s: %s", ticker, base_result["status"])
        return base_result
    except (FileNotFoundError, ValueError, TypeError, KeyError) as exc:
        LOGGER.warning("Rejected %s: %s", ticker, exc)
        base_result["notes"] = str(exc)
        return base_result


# يخزن التنبيه ونتيجة التحقق في SQLite.
def log_alert(
    db_path: str | os.PathLike[str],
    alert: dict[str, Any],
    validation_result: dict[str, Any],
) -> int:
    init_db(db_path)
    timestamp = str(alert.get("timestamp") or datetime.now(timezone.utc).isoformat())
    with closing(sqlite3.connect(db_path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO tv_alerts (
                timestamp, ticker, action, price, entry, sl, tp,
                atr_pct, adx, status, confidence, py_mirrors_json, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                normalize_ticker(alert.get("ticker", "")),
                str(alert.get("action", "")).upper(),
                _as_float(alert.get("price")),
                _as_float(alert.get("entry")),
                _as_float(alert.get("sl")),
                _as_float(alert.get("tp")),
                _as_float(validation_result.get("atr_pct", alert.get("atr_pct"))),
                _as_float(validation_result.get("adx", alert.get("adx"))),
                str(validation_result.get("status", "REJECT")),
                float(validation_result.get("confidence", 0)),
                json.dumps(validation_result.get("py_mirrors", {}), ensure_ascii=False),
                str(validation_result.get("notes", "")),
            ),
        )
        connection.commit()
        row_id = int(cursor.lastrowid)
    LOGGER.info("Stored alert %d for %s", row_id, alert.get("ticker"))
    return row_id


# يجري اختباراً محلياً سريعاً لقاعدة البيانات.
def _smoke_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "smoke.db"
        init_db(path)
        row_id = log_alert(path, {"ticker": "TEST.CA", "action": "BUY"}, {"status": "REJECT", "confidence": 0, "py_mirrors": {}})
        assert row_id == 1
    LOGGER.info("validate_tv_signals smoke test passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _smoke_test()
