"""Yahoo EGX partial split back-adjust (egx_reports/FALSE_DROPS_AUDIT_2026-10-11.md): fix, raw archive, guard."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import data_downloader as dd

HERE = Path(__file__).parent
SNAPSHOT = HERE / "backups" / "pre_backadjust_fix_20261011"


def _yahoo(prices, split_at: int, adjusted_from: int, factor: float) -> pd.DataFrame:
    """Exchange prices (old share basis before split_at); Yahoo divided only sessions adjusted_from..split_at-1 by the
    factor and put the split on split_at: a false drop on adjusted_from."""
    idx = pd.bdate_range(end="2026-10-08", periods=len(prices), freq="C", weekmask="Sun Mon Tue Wed Thu")
    px = pd.Series(prices, index=idx, dtype=float)
    px.iloc[adjusted_from:split_at] /= factor
    df = pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99, "Close": px, "Adj Close": px, "Volume": 1000})
    df["Volume"] = df["Volume"].where(np.arange(len(px)) >= adjusted_from, 800)  # old basis volume too
    df["Dividends"], df["Stock Splits"] = 0.0, 0.0
    df.iloc[split_at, df.columns.get_loc("Stock Splits")] = factor
    return df


def _simple():  # 1.25 on round prices: Yahoo's divided closes stay on the tick grid -> price-only path
    return _yahoo([100.0] * 30 + [80.0] * 10, split_at=30, adjusted_from=23, factor=1.25)


def _splits(df):
    return df["Stock Splits"][df["Stock Splits"] > 0]


def test_fix_removes_false_drop_and_is_idempotent():
    raw = _simple()
    assert dd.false_split_drops(raw, _splits(raw))  # the guard sees the problem
    fixed, notes = dd.fix_partial_backadjust(raw, _splits(raw))
    assert np.allclose(fixed["Close"], 80.0) and np.allclose(fixed["Adj Close"], 80.0)
    assert (fixed["Volume"] == 1000).all() and fixed["Volume"].dtype == raw["Volume"].dtype
    assert notes[0]["method"] == "price-only" and notes[0]["false_drop"] == str(raw.index[23].date())
    assert dd.false_split_drops(fixed, _splits(raw)) == []
    again, notes2 = dd.fix_partial_backadjust(fixed, _splits(raw))
    assert again.equals(fixed) and notes2[0]["method"].startswith("none")


def test_fingerprint_beats_a_real_move_next_to_the_false_drop():
    # NCCW 2024: real -5.5% the day before Yahoo's block; that day is closer to the factor than the false drop itself
    f = 1.0759
    raw = _yahoo([4.69] * 22 + [4.43] + [4.14] * 7 + [3.85] * 10, split_at=30, adjusted_from=23, factor=f)
    assert dd._closest(raw, raw.index[30], f)[0] == raw.index[22]  # price alone would pick the wrong day
    fixed, notes = dd.fix_partial_backadjust(raw, _splits(raw))
    assert notes[0]["method"] == "fingerprint" and notes[0]["false_drop"] == str(raw.index[23].date())
    assert np.allclose(fixed["Close"].iloc[:22], 4.69 / f) and fixed["Close"].iloc[22] == pytest.approx(4.43 / f)
    # the real -5.5% stays; the fix is trusted, so the download is not rejected
    assert dd.false_split_drops(fixed, _splits(raw), skip=frozenset({raw.index[30]})) == []


def test_fully_adjusted_and_small_factor_are_left_alone():
    f = 1.1  # old event Yahoo adjusted completely: every close before the split is divided (off the grid)
    prices = [5.37, 5.41, 5.29, 5.33, 5.47, 5.52, 5.03, 5.11, 5.18, 5.21, 5.24, 5.26] + [4.9] * 5  # -8.9% real day
    full = _yahoo(prices, split_at=12, adjusted_from=0, factor=f)
    fixed, notes = dd.fix_partial_backadjust(full, _splits(full))
    assert fixed.equals(full) and notes[0]["method"].startswith("none: window already")
    small = _yahoo([5.55] * 30 + [5.33] * 10, split_at=30, adjusted_from=22, factor=1.041667)
    small.iloc[22:30, :5] = small.iloc[22:30, :5].round(2)  # MASR 2026: Yahoo's divided closes came rounded, on the grid
    fixed, notes = dd.fix_partial_backadjust(small, _splits(small))
    assert fixed.equals(small) and "too small" in notes[0]["method"]
    manual = {small.index[30]: small.index[22]}  # approved day: applied while it still drops by the factor
    fixed, notes = dd.fix_partial_backadjust(small, _splits(small), manual)
    assert notes[0]["method"] == "manual (approved)" and np.allclose(fixed["Close"], 5.33, atol=0.01)
    assert dd.fix_partial_backadjust(fixed, _splits(small), manual)[0].equals(fixed)  # Yahoo fixed it -> not doubled
    plain = _simple().assign(**{"Stock Splits": 0.0})
    assert dd.apply_backadjust_fix(plain, "X.CA", "t").equals(plain)


def test_to_adjusted_is_yfinance_rule():
    raw = _simple().assign(**{"Adj Close": lambda d: d["Close"] * 0.9})
    adj = dd.to_adjusted(raw)
    assert "Adj Close" not in adj and np.allclose(adj["Close"], raw["Close"] * 0.9)
    assert np.allclose(adj["High"], raw["High"] * 0.9) and adj["Volume"].equals(raw["Volume"])


def test_download_ticker_saves_fixed_prices_and_archives_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "RAW_ARCHIVE", tmp_path / "raw")
    monkeypatch.setattr(dd, "FIX_LOG", tmp_path / "fix.jsonl")
    monkeypatch.setattr(dd.yf, "download", lambda *a, **k: _simple())
    dd.download_ticker("SKPC.CA", tmp_path / "data")
    saved = pd.read_csv(tmp_path / "data" / "SKPC.CA.csv")
    assert np.allclose(saved["Close"], 80.0) and (saved["Volume"] == 1000).all()
    raw_files = list((tmp_path / "raw" / "data").rglob("SKPC.CA.csv"))
    assert len(raw_files) == 1 and pd.read_csv(raw_files[0])["Close"].iloc[0] == 100.0  # Yahoo's response as received
    log = [json.loads(line) for line in (tmp_path / "fix.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log[0]["ticker"] == "SKPC.CA" and log[0]["false_drop"] and log[0]["raw"] == str(raw_files[0])
    assert log[0]["fix_type"] == "inferred" and log[0]["verified_by"] is None  # price-only, no external source


def test_guard_failure_keeps_the_old_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "RAW_ARCHIVE", tmp_path / "raw")
    monkeypatch.setattr(dd, "FIX_LOG", tmp_path / "fix.jsonl")
    raw = _simple()
    raw.iloc[26:, :5] = raw.iloc[26:, :5] / 1.25  # a second factor-sized drop, no fingerprint: ambiguous
    monkeypatch.setattr(dd.yf, "download", lambda *a, **k: raw.copy())
    (tmp_path / "data").mkdir()
    with pytest.raises(ValueError, match="false split drop left after fix"):
        dd.download_ticker("SKPC.CA", tmp_path / "data")
    assert not (tmp_path / "data" / "SKPC.CA.csv").exists()
    rejected = [json.loads(line) for line in (tmp_path / "fix.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r.get("reason") == "suspected_false_drop" and r["ticker"] == "SKPC.CA" for r in rejected)


def _flagged(folder: Path, tol: float, trusted=frozenset()) -> set[tuple[str, str]]:
    """(ticker, split date) the guard flags in a stored folder, from docs/corporate_actions.csv."""
    acts = pd.read_csv(HERE / "docs" / "corporate_actions.csv")
    found = set()
    for ticker, rows in acts[acts["split"] > 0].groupby("ticker"):
        path = folder / f"{ticker}.csv"
        if path.exists():
            df = pd.read_csv(path, index_col=0)
            df.index = pd.to_datetime(df.index.str[:10])
            splits = pd.Series(rows["split"].to_numpy(), index=pd.to_datetime(rows["ex_date"]))
            skip = frozenset(pd.Timestamp(d) for t, d in trusted if t == ticker)
            found |= {(ticker, s) for s, _, _, _ in dd.false_split_drops(df, splits, tol, skip)}
    return found


# The silent (<25%) false drops of the audit, by split event. ISPH 2022-06-01 (the 19th) is not one: the raw Yahoo
# series is off the tick grid across the whole window, i.e. fully adjusted; its -7% was a real move.
SILENT_18 = {("INFI.CA", "2024-02-08"), ("CANA.CA", "2024-02-14"), ("EXPA.CA", "2024-02-29"), ("AMIA.CA", "2024-05-30"),
             ("NCCW.CA", "2024-08-14"), ("SKPC.CA", "2024-10-10"), ("INFI.CA", "2025-02-20"), ("SPIN.CA", "2025-07-31"),
             ("NCCW.CA", "2025-08-21"), ("MTIE.CA", "2025-09-18"), ("JUFO.CA", "2025-11-06"), ("RMDA.CA", "2025-12-03"),
             ("COMI.CA", "2025-12-17"), ("SKPC.CA", "2026-01-12"), ("JUFO.CA", "2026-08-06"), ("NCCW.CA", "2026-08-06"),
             ("MTIE.CA", "2026-08-13"), ("ACGC.CA", "2026-08-20")}


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="pre-fix snapshot not on this machine")
def test_guard_covers_the_silent_events():
    assert SILENT_18 <= _flagged(SNAPSHOT / "data_h3_live", dd.FIX_TOL)


@pytest.mark.parametrize("name", ["data", "data_h3_live"])
def test_live_folders_have_no_false_split_drop(name):
    """Data guard on the stored live files (2% as in the audit). Events the download fixed by fingerprint are trusted:
    a factor-sized move left next to them is real. Skipped (not failed) until the folder has had at least one download
    with the fix, i.e. until the deploy's re-download step; from then on it must pass."""
    if not (HERE / name).exists():
        pytest.skip(f"{name}/ not on this machine")
    notes = [json.loads(line) for line in dd.FIX_LOG.read_text(encoding="utf-8").splitlines()] if dd.FIX_LOG.exists() else []
    notes = [n for n in notes if n.get("source") == name]
    if not notes:
        pytest.skip(f"{name}/ not yet re-downloaded with the split fix (deploy step); no entry in {dd.FIX_LOG.name}")
    trusted = {(n["ticker"], n["split_date"]) for n in notes if n.get("method") in dd.TRUSTED}
    assert _flagged(HERE / name, 0.02, trusted) == set()


def test_rejected_ticker_blocks_the_daily_scan():
    """A guard rejection keeps the previous CSV, whose last candle is then older than the expected session. The
    freshness gate drops that ticker and marks the whole run DATA_UNAVAILABLE, so daily_runner raises before
    scan_universe: no signal can come from a file that may still hold a false drop."""
    from data_health import assess_daily_data
    days = pd.bdate_range("2026-06-01", "2026-10-08", tz="Africa/Cairo")
    fresh = pd.DataFrame({"Open": 10.0, "High": 10.5, "Low": 9.5, "Close": 10.0, "Volume": 1000.0}, index=days)
    stale = fresh.iloc[:-1]   # the rejected ticker kept yesterday's file
    valid, report = assess_daily_data({"OK.CA": fresh, "REJ.CA": stale}, expected=days[-1].date(),
                                      expected_tickers=["OK.CA", "REJ.CA"])
    assert "REJ.CA" not in valid and "REJ.CA" in report["problems"]
    assert report["status"] == "DATA_UNAVAILABLE"
