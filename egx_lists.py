from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, TypeVar

import pandas as pd

MANIFEST = json.loads(Path(__file__).with_name("egx_universe.json").read_text(encoding="utf-8"))
UNIVERSE: tuple[str, ...] = tuple(MANIFEST["universe"])
RECORDS: dict[str, dict[str, Any]] = {row["ticker"]: row for row in MANIFEST["records"]}
SECTOR_MAP: dict[str, str] = {ticker: RECORDS[ticker]["sector"] for ticker in UNIVERSE}
T = TypeVar("T")
DEMO_TICKERS = frozenset({"BULL.CA", "BEAR.CA", "SIDEWAYS.CA", "VOLATILE.CA", "QUIET.CA"})


def liquidity_list(turnover: float | None) -> str:
    """تصنيف بديل بالسيولة؛ لا يثبت أهلية الهامش أو التداول اللحظي."""
    if turnover is None or pd.isna(turnover) or turnover < 0:
        return "Unknown"
    return "A" if turnover > 10_000_000 else "B" if turnover >= 3_000_000 else "C"


def classification(ticker: str) -> str:
    return str(RECORDS.get(ticker.upper(), {}).get("list", "Unknown"))


def recommendation_warning(ticker: str) -> str:
    group = classification(ticker)
    if group == "A":
        return "A بديل سيولة؛ T+0 والهامش غير موثقين، تحقق مع الوسيط"
    if group == "B":
        return "B بديل سيولة؛ Swing فقط كسياسة للنظام، لا كحظر رسمي"
    if group == "C":
        return "C بديل سيولة؛ غير مناسب للتداول وفق فلاتر النظام"
    return "تصنيف غير معروف؛ مستبعد من الدخول الجديد"


def filter_universe(data: Mapping[str, T], *, demo_mode: bool = False) -> dict[str, T]:
    # لا تتغير سجلات المراكز التاريخية؛ الفلتر للدخول الجديد فقط.
    allowed = set(UNIVERSE) | (DEMO_TICKERS if demo_mode else set())
    return {ticker: value for ticker, value in data.items() if ticker in allowed}


def annotate(frame: pd.DataFrame, ticker_column: str = "Ticker") -> pd.DataFrame:
    result = frame.copy()
    tickers = result[ticker_column] if ticker_column in result else pd.Series(index=result.index, dtype=str)
    result["List"] = tickers.map(classification)
    result["List Source"] = "Liquidity proxy (not official)"
    result["Eligibility Warning"] = tickers.map(recommendation_warning)
    return result


def universe_table() -> pd.DataFrame:
    return annotate(pd.DataFrame([{
        "Ticker": ticker, "Company": RECORDS[ticker]["name"], "Sector": SECTOR_MAP[ticker],
        "Liquidity M EGP/day": RECORDS[ticker]["avg_turnover"] / 1_000_000,
        "Activity %": RECORDS[ticker]["activity_pct"],
        "Sector Source": RECORDS[ticker]["sector_source"],
    } for ticker in UNIVERSE]))
