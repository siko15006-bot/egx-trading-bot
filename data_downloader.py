from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from egx_lists import UNIVERSE
from data_health import require_daily_data


BASE_DIR = Path(__file__).resolve().parent
CAIRO_TZ = ZoneInfo("Africa/Cairo")
LOGGER = logging.getLogger(__name__)
OHLCV = ("Open", "High", "Low", "Close", "Volume")
MIN_ROWS = 5  # fewer rows from Yahoo is almost certainly a glitch, not real history


@dataclass(frozen=True)
class DownloadResult:
    ticker: str
    path: Path
    rows: int
    first_date: str
    last_date: str
    size_bytes: int


# يحل المسار النسبي من مجلد المشروع ليتوافق مع Task Scheduler.
def _resolve(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else BASE_DIR / candidate


# يجهز Log مستقل لتشغيل أداة التحميل يدويًا.
def _configure_logging() -> Path:
    log_path = BASE_DIR / "logs" / f"data_downloader_{datetime.now(CAIRO_TZ):%Y%m%d}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    return log_path


def _existing_stats(path: Path):
    """(last Date, row count) of the cached CSV, or (None, 0) if missing/unreadable (then the validated new file may replace it)."""
    try:
        dates = pd.to_datetime(pd.read_csv(path, usecols=["Date"])["Date"])
        return dates.max().date(), len(dates)
    except (OSError, ValueError, KeyError, pd.errors.ParserError, pd.errors.EmptyDataError):
        return None, 0


# يحتفظ بجلسات الحجم الصفري حتى لا يضخم مقياس النشاط.
def _normalize_download(raw: pd.DataFrame, ticker: str, limit: int) -> pd.DataFrame:
    data = raw.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if ticker in data.columns.get_level_values(-1):
            data = data.xs(ticker, axis=1, level=-1)
        else:
            data.columns = data.columns.get_level_values(0)
    missing = [column for column in OHLCV if column not in data.columns]
    if missing:
        raise ValueError(f"{ticker}: missing columns {missing}")
    data = data.loc[:, OHLCV].copy()
    for column in OHLCV:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[data.index.notna()].dropna(subset=list(OHLCV))
    data = data[~data.index.duplicated(keep="last")].sort_index().tail(limit)
    if ((data[list(OHLCV[:4])] <= 0).any(axis=1) | (data["Volume"] < 0)
            | (data["High"] + data["Close"].abs() * 1e-7 < data[["Low", "Close"]].max(axis=1))
            | (data["Low"] - data["Close"].abs() * 1e-7 > data[["High", "Close"]].min(axis=1))).any():
        raise ValueError(f"{ticker}: malformed OHLCV")
    if data.empty:
        raise ValueError(f"{ticker}: Yahoo returned no active sessions")
    dates = data.index
    if dates.tz is not None:
        dates = dates.tz_convert(CAIRO_TZ).tz_localize(None)
    result = data.reset_index(drop=True)
    result.insert(0, "Date", dates.strftime("%Y-%m-%d"))
    result["Volume"] = result["Volume"].round().astype("int64")
    return result[["Date", *OHLCV]]


# يحمل سهمًا واحدًا ويستبدل CSV فقط بعد اكتمال ملف مؤقت صالح.
def download_ticker(
    ticker: str,
    data_folder: str | os.PathLike[str],
    limit: int = 250,
    period: str = "2y",
) -> DownloadResult:
    folder = _resolve(data_folder)
    folder.mkdir(parents=True, exist_ok=True)
    symbol = ticker.strip().upper()
    raw = yf.download(
        symbol,
        period=period,
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=False,
        timeout=30,
    )
    try:
        frame = _normalize_download(raw, symbol, limit)
    except ValueError:
        if period != "2y":
            raise
        today = datetime.now(CAIRO_TZ).date()
        raw = yf.download(
            symbol,
            start=today - timedelta(days=740),
            end=today + timedelta(days=1),
            interval="1d",
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=False,
            timeout=30,
        )
        frame = _normalize_download(raw, symbol, limit)
    indexed = frame.set_index(pd.to_datetime(frame["Date"])).drop(columns="Date")
    new_last = indexed.index.max().date()  # not [-1]: if unsorted, [-1] < max would silently drop newer rows
    # Structure/OHLCV checks in require_daily_data are unchanged; only freshness moves out:
    # expected=new_last means "is this file valid", while daily_runner's assess_daily_data still
    # decides "is it today's session". Before, a valid 10-04 file was thrown away for not being 10-05.
    # Guard 3 (absolute floor) reuses require_daily_data's own min_rows check ("insufficient history").
    checked = require_daily_data({symbol: indexed}, min_rows=MIN_ROWS, expected=new_last)[symbol]
    frame = checked.reset_index()
    frame.columns = ["Date", *OHLCV]
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
    destination = folder / f"{symbol}.csv"
    existing_last, existing_count = _existing_stats(destination)
    if existing_last is not None and new_last < existing_last:
        raise ValueError(f"{symbol}: refusing downgrade, Yahoo last={new_last} < cached last={existing_last}")
    # Floor capped at `limit` so lowering limit (e.g. 250 -> 100) shrinks caches instead of refusing every ticker.
    floor = min(existing_count, limit)
    if existing_last is not None and len(frame) < floor:
        raise ValueError(f"{symbol}: refusing shrinkage, Yahoo rows={len(frame)} < floor={floor} (cached={existing_count}, limit={limit})")
    if existing_last is None and destination.exists():
        LOGGER.warning("%s: cached CSV unreadable, replacing with validated new file", symbol)
    temporary = folder / f".{symbol}.csv.tmp"
    try:
        frame.to_csv(temporary, index=False, encoding="utf-8", lineterminator="\n")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    result = DownloadResult(
        ticker=symbol,
        path=destination,
        rows=len(frame),
        first_date=str(frame["Date"].iloc[0]),
        last_date=str(frame["Date"].iloc[-1]),
        size_bytes=destination.stat().st_size,
    )
    LOGGER.info(
        "Downloaded %s: rows=%d range=%s..%s bytes=%d",
        result.ticker,
        result.rows,
        result.first_date,
        result.last_date,
        result.size_bytes,
    )
    return result


# يحدث الكون كاملًا ويُبقي الملف القديم لأي سهم يفشل.
def download_universe(
    data_folder: str | os.PathLike[str],
    tickers: tuple[str, ...] = UNIVERSE,
    limit: int = 250,
    period: str = "2y",
) -> list[DownloadResult]:
    folder = _resolve(data_folder)
    results: list[DownloadResult] = []
    failures: list[str] = []
    for number, ticker in enumerate(tickers, 1):
        try:
            results.append(download_ticker(ticker, folder, limit=limit, period=period))
        except Exception as exc:
            fallback = folder / f"{ticker}.csv"
            failures.append(ticker)
            LOGGER.error(
                "Download failed for %s; keeping old CSV=%s: %s",
                ticker,
                fallback.exists(),
                exc,
            )
        if number % 20 == 0:
            LOGGER.info("Progress: %d/%d stocks", number, len(tickers))
        time.sleep(0.3)
    if not results:
        raise RuntimeError(f"All downloads failed: {', '.join(failures)}")
    LOGGER.info("Download complete: success=%d failed=%d", len(results), len(failures))
    return results


# يقرأ معاملات التشغيل اليدوي.
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download EGX daily OHLCV data from Yahoo Finance")
    parser.add_argument("--data-folder", default="./data")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--period", default="2y")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    log_path = _configure_logging()
    LOGGER.info("EGX data download started")
    try:
        results = download_universe(args.data_folder, limit=max(args.limit, 1), period=args.period)
    except Exception:
        LOGGER.exception("EGX data download failed")
        return 1
    latest = max(result.last_date for result in results)
    print(f"Downloaded {len(results)} files; latest candle: {latest}; log: {log_path}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
