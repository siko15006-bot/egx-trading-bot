from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
from egx_lists import UNIVERSE
from data_health import require_daily_data


BASE_DIR = Path(__file__).resolve().parent
CAIRO_TZ = ZoneInfo("Africa/Cairo")
LOGGER = logging.getLogger(__name__)
OHLCV = ("Open", "High", "Low", "Close", "Volume")
MIN_ROWS = 5  # fewer rows from Yahoo is almost certainly a glitch, not real history
# Yahoo EGX bonus shares (egx_reports/FALSE_DROPS_AUDIT_2026-10-11.md): the split is dated on the ex-date E but only the
# ~4-8 sessions before E are split-adjusted, so the series shows a false drop days early and older history on the old
# share basis. Every download is corrected; Yahoo's raw response is archived first and the guard must pass after.
FIX_WINDOW, FIX_TOL, GUARD_MIN_FACTOR = 10, 0.08, 1.07  # below 7% a false drop is indistinguishable from a normal day
PRICE_COLS = ("Open", "High", "Low", "Close", "Adj Close")
RAW_ARCHIVE = BASE_DIR / "backups" / "yahoo_raw"
# Approved false drops the detector cannot see (factor < 7%, divided closes on the grid): (ticker, Yahoo split date) ->
# false-drop day. Applied only while that day still drops by about the factor, so a later full Yahoo fix is not doubled.
MANUAL_FALSE_DROPS = {("MASR.CA", "2026-03-04"): "2026-02-22"}  # treasury-share distribution, Ahmed 2026-10-11
TRUSTED = ("fingerprint", "none: window already on the new basis (fully adjusted)")  # tick-grid verdicts
FIX_LOG = BASE_DIR / "logs" / "backadjust_fixes.jsonl"


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


def _off_grid(close: pd.Series) -> pd.Series:
    """True where a raw (auto_adjust=False) close is off the 0.001 EGP tick grid, i.e. Yahoo divided it by a split
    factor. Tolerance covers Yahoo's float32 storage (~1e-7 relative)."""
    x = close.to_numpy(float) * 1000
    return pd.Series(np.abs(x - np.round(x)) > np.maximum(0.01, np.abs(x) * 1e-7), index=close.index)


def _ratios(df: pd.DataFrame, split_date) -> pd.Series:
    """prev/close of the last FIX_WINDOW traded sessions before split_date (>1 = drop)."""
    close = df.loc[(df.index < split_date) & (df["Volume"] > 0), "Close"]
    return (close.shift(1) / close).iloc[-FIX_WINDOW:].dropna()


def _fits(ratio: float, factor: float, tol: float = FIX_TOL) -> bool:
    return abs(ratio / factor - 1) <= tol and ratio > 1 + (factor - 1) / 2


def _closest(df: pd.DataFrame, split_date, factor: float, tol: float = FIX_TOL):
    """(day, ratio) of the drop closest to the factor in the window; day None if it does not fit."""
    ratio = _ratios(df, split_date)
    if ratio.empty:
        return None, None
    day = (np.log(ratio) - np.log(factor)).abs().idxmin()
    return (day if _fits(ratio[day], factor, tol) else None), float(ratio[day])


def _false_drop(raw: pd.DataFrame, split_date, factor: float):
    """(day, ratio, method) of Yahoo's false drop before split_date, or (None, ratio, reason).
    fingerprint: the closes Yahoo divided are off the tick grid and form a block ending just before the split; the
    block start (on-grid before it, at most one coincidence allowed) whose drop fits the factor is the false drop.
    Without a block: a window mostly off the grid is already fully adjusted; otherwise the closest drop to the factor
    (price-only), only for factors >= 7%. Price alone can pick a real move next to the false drop (NCCW/CANA 2024)."""
    ratio = _ratios(raw, split_date)
    if ratio.empty:
        return None, None, "none: no sessions before split"
    off = _off_grid(raw.loc[ratio.index, "Close"]).to_numpy()
    n = len(off)
    pre_on = np.concatenate([[0], np.cumsum(~off)])                 # on-grid closes in [0, j)
    post_off = np.concatenate([np.cumsum(off[::-1])[::-1], [0]])     # off-grid closes in [j, n)
    blocks = [j for j in range(1, n) if pre_on[j] + post_off[j] >= n - 1 and post_off[j] >= max(2, 0.75 * (n - j))
              and _fits(ratio.iloc[j], factor)]
    if blocks:
        j = min(blocks, key=lambda k: (-(pre_on[k] + post_off[k]), abs(np.log(ratio.iloc[k] / factor))))  # cleanest block
        return ratio.index[j], float(ratio.iloc[j]), "fingerprint"
    if off.mean() >= 0.8:
        return None, None, "none: window already on the new basis (fully adjusted)"
    if factor < GUARD_MIN_FACTOR:
        return None, None, "none: no divided block and factor too small for a price-only match"
    day, best = _closest(raw, split_date, factor)
    return (day, best, "price-only") if day is not None else (None, best, "none: no false drop")


def fix_partial_backadjust(df: pd.DataFrame, splits: pd.Series, manual: dict | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """Divide prices before each split's false drop by the factor (Volume multiplied). Same method as
    outputs/yahoo_expansion_18_fixed_20261010/build_fixed.py. Detection runs on the frame as received (raw closes, so
    the tick-grid fingerprint is intact); a fixed frame shows no divided block and no drop, so a second run is a no-op.
    Reverse splits and events outside the data are left alone."""
    out, notes = df.copy(), []
    for split_date, factor in sorted(splits.items()):
        if not (factor > 1 and df.index[0] < split_date <= df.index[-1]):
            continue
        day, ratio, method = _false_drop(df, split_date, factor)
        known = pd.Timestamp((manual or {}).get(pd.Timestamp(split_date), pd.NaT))
        if day is None and pd.notna(known):
            r = _ratios(df, split_date)
            if known in r.index and _fits(r[known], factor):
                day, ratio, method = known, float(r[known]), "manual (approved)"
        note = dict(split_date=str(pd.Timestamp(split_date).date()), factor=float(factor), ratio=ratio, method=method)
        if day is None:
            notes.append(note)
            continue
        before = out.index < day
        cols = [c for c in PRICE_COLS if c in out]
        out.loc[before, cols] = out.loc[before, cols] / factor
        out["Volume"] = out["Volume"].where(~before, (out["Volume"] * factor).round()).astype(out["Volume"].dtype)
        notes.append(note | dict(false_drop=str(pd.Timestamp(day).date()), rows_adjusted=int(before.sum())))
    return out, notes


def false_split_drops(df: pd.DataFrame, splits: pd.Series, tol: float = FIX_TOL,
                      skip: frozenset = frozenset()) -> list[tuple[str, float, str, float]]:
    """Guard: splits >= GUARD_MIN_FACTOR (not in skip) whose window before still holds a drop within tol of the factor."""
    found = []
    for split_date, factor in splits.items():
        if factor >= GUARD_MIN_FACTOR and df.index[0] < split_date <= df.index[-1] and split_date not in skip:
            day, ratio = _closest(df, split_date, factor, tol)
            if day is not None:
                found.append((str(pd.Timestamp(split_date).date()), float(factor), str(pd.Timestamp(day).date()), ratio))
    return found


def apply_backadjust_fix(raw: pd.DataFrame, ticker: str, source: str) -> pd.DataFrame:
    """Download hook (raw = auto_adjust=False frame with Stock Splits): archive Yahoo's response when it has a split,
    fix, log, then the guard. Tick-grid verdicts are trusted (a factor-sized drop left beside them is a real move);
    anything else left factor-sized is ambiguous and raises, so the caller keeps the previous file."""
    if "Stock Splits" not in raw or raw.empty:
        return raw
    splits = raw["Stock Splits"][pd.to_numeric(raw["Stock Splits"], errors="coerce").fillna(0) > 0]
    manual = {pd.Timestamp(e): d for (t, e), d in MANUAL_FALSE_DROPS.items() if t == ticker}
    fixed, notes = fix_partial_backadjust(raw, splits, manual)
    if notes:
        now = datetime.now(CAIRO_TZ)
        path = RAW_ARCHIVE / source / f"{now:%Y%m%d_%H%M%S}" / f"{ticker}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        FIX_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FIX_LOG.open("a", encoding="utf-8") as log:
            for note in notes:
                log.write(json.dumps(dict(at=now.isoformat(timespec="seconds"), source=source, ticker=ticker,
                                          raw=str(path), raw_sha256=digest, **note), ensure_ascii=False) + "\n")
        LOGGER.info("%s back-adjust: %s", ticker, notes)
    trusted = frozenset(pd.Timestamp(n["split_date"]) for n in notes if n["method"] in TRUSTED)
    bad = false_split_drops(fixed, splits.rename(index=pd.Timestamp), skip=trusted)
    if bad:
        raise ValueError(f"{ticker}: false split drop left after fix (split, factor, day, ratio): {bad}")
    return fixed


def to_adjusted(frame: pd.DataFrame) -> pd.DataFrame:
    """auto_adjust=True from a (fixed) auto_adjust=False frame: yfinance's own rule, OHLC * Adj Close / Close."""
    out = frame.copy()
    ratio = out["Adj Close"] / out["Close"]
    for col in ("Open", "High", "Low"):
        out[col] = out[col] * ratio
    out["Close"] = out["Adj Close"]
    return out.drop(columns="Adj Close")


# يحتفظ بجلسات الحجم الصفري حتى لا يضخم مقياس النشاط.
def _normalize_download(raw: pd.DataFrame, ticker: str, limit: int, source: str = "data") -> pd.DataFrame:
    data = raw.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if ticker in data.columns.get_level_values(-1):
            data = data.xs(ticker, axis=1, level=-1)
        else:
            data.columns = data.columns.get_level_values(0)
    data = apply_backadjust_fix(data, ticker, source)  # before tail(limit): the split may sit just outside the kept rows
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
        actions=True,  # Stock Splits for apply_backadjust_fix
        progress=False,
        threads=False,
        timeout=30,
    )
    try:
        frame = _normalize_download(raw, symbol, limit, folder.name)
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
            actions=True,
            progress=False,
            threads=False,
            timeout=30,
        )
        frame = _normalize_download(raw, symbol, limit, folder.name)
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
