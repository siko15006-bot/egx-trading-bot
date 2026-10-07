from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Iterable, Mapping, Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CAIRO = ZoneInfo("Africa/Cairo")
FIELDS = ("Open", "High", "Low", "Close", "Volume")


class DataHealthError(RuntimeError):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        super().__init__(health_message(report))


def expected_session(now: datetime | None = None, *, holidays: Iterable[date] | None = None) -> date:
    # تقويم أسبوعي فقط؛ الإجازات يجب توثيقها في الإعدادات، لا تخمينها.
    pinned = os.getenv("EGX_EXPECTED_SESSION")  # tests only: pin the session instead of reading the wall clock
    if now is None and pinned:
        return date.fromisoformat(pinned)
    clock = now or datetime.now(CAIRO)
    clock = clock.replace(tzinfo=CAIRO) if clock.tzinfo is None else clock.astimezone(CAIRO)
    cutoff = time.fromisoformat(os.getenv("EGX_DATA_CUTOFF", "14:30"))
    closed = set(holidays) if holidays is not None else {
        date.fromisoformat(value.strip()) for value in os.getenv("EGX_MARKET_HOLIDAYS", "").split(",") if value.strip()
    }
    session = clock.date() if clock.time().replace(tzinfo=None) >= cutoff else clock.date() - timedelta(days=1)
    while session.weekday() in (4, 5) or session in closed:
        session -= timedelta(days=1)
    return session


def assess_daily_data(
    data_map: Mapping[str, pd.DataFrame], *, expected: date | None = None,
    expected_tickers: Iterable[str] | None = None, min_rows: int = 60,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    target = expected or expected_session()
    required = set(expected_tickers) if expected_tickers is not None else set(data_map)
    problems: dict[str, str] = {ticker: "missing CSV" for ticker in sorted(required - set(data_map))}
    valid: dict[str, pd.DataFrame] = {}
    latest: list[str] = []
    fresh = 0
    for ticker, raw in data_map.items():
        if raw.empty or not isinstance(raw.index, pd.DatetimeIndex) or raw.index.hasnans:
            problems[ticker] = "empty or invalid dates"
            continue
        index = raw.index.tz_localize(CAIRO) if raw.index.tz is None else raw.index.tz_convert(CAIRO)
        # لا نحسب إشارات إغلاق يومي على شمعة الجلسة الحالية غير المكتملة.
        frame = raw.loc[index.date <= target].copy()
        if frame.empty:
            problems[ticker] = "no completed daily candles"
            continue
        last_date = index[index.date <= target][-1].date()
        latest.append(last_date.isoformat())
        if last_date != target:
            problems[ticker] = f"last candle {last_date}; expected {target}"
        elif len(frame) < min_rows:
            problems[ticker] = f"insufficient history: {len(frame)} < {min_rows}"
        elif frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
            problems[ticker] = "duplicate or unordered dates"
        elif any(name not in frame for name in FIELDS):
            problems[ticker] = "missing OHLCV columns"
        else:
            values = frame[list(FIELDS)].apply(pd.to_numeric, errors="coerce")
            tolerance = values.Close.abs() * 1e-7
            malformed = ((values.High + tolerance < values[["Close", "Low"]].max(axis=1))
                         | (values.Low - tolerance > values[["Close", "High"]].min(axis=1)))
            if (not np.isfinite(values.to_numpy()).all() or (values[list(FIELDS[:4])] <= 0).any().any()
                    or (values.Volume < 0).any() or malformed.any()):
                problems[ticker] = "invalid OHLCV values"
            else:
                valid[ticker] = frame
                fresh += 1
    report = {
        "status": "DATA_OK" if required and not problems and fresh == len(data_map) else "DATA_UNAVAILABLE",
        "expected_session": target.isoformat(), "latest_session": max(latest, default=None),
        "oldest_session": min(latest, default=None), "loaded": len(data_map),
        "required": len(required), "fresh": fresh, "problems": problems,
        "calendar_policy": "Sun-Thu plus configured EGX_MARKET_HOLIDAYS; official holidays not guessed",
    }
    return valid, report


def require_daily_data(data_map: Mapping[str, pd.DataFrame], **kwargs: Any) -> dict[str, pd.DataFrame]:
    valid, report = assess_daily_data(data_map, **kwargs)
    if report["status"] != "DATA_OK":
        raise DataHealthError(report)
    return valid


def health_message(report: Mapping[str, Any]) -> str:
    return (
        f"DATA_UNAVAILABLE: لم يتم حساب BUY/WATCH بسبب خلل البيانات.\n"
        f"الجلسة المتوقعة: {report['expected_session']}\n"
        f"آخر شمعة متاحة: {report.get('latest_session') or 'لا توجد'}\n"
        f"ملفات سليمة وحديثة: {report['fresh']}/{report['required']}\n"
        f"ملفات تحتاج مراجعة: {len(report['problems'])}"
    )
