"""download_ticker: save valid newer data, never downgrade, still reject bad/empty data."""
import logging

import pandas as pd
import pytest

import data_downloader as dd

SYM = "COMI.CA"


def _yahoo(last_day: str, days: int = 5, **override) -> pd.DataFrame:
    # EGX week (Sun-Thu): plain calendar days would include Fridays, e.g. 2026-04-24 00:00 which does not
    # exist in Africa/Cairo (DST jump) and crashes tz_localize in data_health.
    idx = pd.bdate_range(end=last_day, periods=days, freq="C", weekmask="Sun Mon Tue Wed Thu")
    df = pd.DataFrame({"Open": 100.0, "High": 102.0, "Low": 99.0, "Close": 101.0, "Adj Close": 101.0, "Volume": 1000},
                      index=idx)
    for col, val in override.items():
        df[col] = val
    return df


def _cache(folder, last_day: str, days: int = 5) -> str:
    path = folder / f"{SYM}.csv"
    _yahoo(last_day, days).drop(columns="Adj Close").rename_axis("Date").reset_index().assign(
        Date=lambda d: d["Date"].dt.strftime("%Y-%m-%d")).to_csv(path, index=False)
    return path.read_text()


def _disk(folder) -> pd.DataFrame:
    """What download_ticker actually left on disk — the returned DownloadResult alone can be stale (Codex audit)."""
    return pd.read_csv(folder / f"{SYM}.csv")


def _fake(monkeypatch, frame):
    monkeypatch.setattr(dd.yf, "download", lambda *a, **k: frame.copy())


def test_newer_valid_data_is_saved_even_if_not_today(tmp_path, monkeypatch):
    _cache(tmp_path, "2026-10-01")
    _fake(monkeypatch, _yahoo("2026-10-04"))
    result = dd.download_ticker(SYM, tmp_path)
    assert result.last_date == "2026-10-04"
    saved = _disk(tmp_path)
    assert saved["Date"].iloc[-1] == "2026-10-04" and len(saved) == 5
    assert list(saved.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]


def test_older_data_never_overwrites_newer_cache(tmp_path, monkeypatch):
    before = _cache(tmp_path, "2026-10-04")
    _fake(monkeypatch, _yahoo("2026-10-01"))
    with pytest.raises(ValueError, match="refusing downgrade"):
        dd.download_ticker(SYM, tmp_path)
    assert (tmp_path / f"{SYM}.csv").read_text() == before


def test_same_day_refresh_is_allowed(tmp_path, monkeypatch):
    _cache(tmp_path, "2026-10-04")
    _fake(monkeypatch, _yahoo("2026-10-04", Close=101.5, High=102.0))
    assert dd.download_ticker(SYM, tmp_path).last_date == "2026-10-04"
    saved = _disk(tmp_path)
    assert (saved["Close"] == 101.5).all() and saved["Date"].iloc[-1] == "2026-10-04"


@pytest.mark.parametrize("bad", [
    _yahoo("2026-10-04").drop(columns="Volume"),  # missing OHLCV column
    _yahoo("2026-10-04", High=50.0),               # High below Close/Low
])
def test_bad_ohlcv_rejected_and_cache_untouched(tmp_path, monkeypatch, bad):
    before = _cache(tmp_path, "2026-10-01")
    _fake(monkeypatch, bad)
    with pytest.raises(ValueError):
        dd.download_ticker(SYM, tmp_path)
    assert (tmp_path / f"{SYM}.csv").read_text() == before


@pytest.mark.parametrize("yahoo_rows, cached_rows, accepted", [
    (1, 200, False),     # glitch: one row (floor and shrinkage)
    (199, 200, False),   # same last date, one row lost -> shrinkage
    (200, 200, True),
    (201, 200, True),
    (5, None, True),     # new ticker at the floor
    (4, None, False),    # new ticker below the floor
])
def test_row_count_guards(tmp_path, monkeypatch, yahoo_rows, cached_rows, accepted):
    before = _cache(tmp_path, "2026-10-04", cached_rows) if cached_rows else None
    _fake(monkeypatch, _yahoo("2026-10-04", yahoo_rows))
    if accepted:
        assert dd.download_ticker(SYM, tmp_path).rows == yahoo_rows
        assert len(_disk(tmp_path)) == yahoo_rows
    else:
        with pytest.raises(Exception) as err:
            dd.download_ticker(SYM, tmp_path)
        detail = str(err.value) + str(getattr(err.value, "report", {}).get("problems", ""))
        assert "shrinkage" in detail or "insufficient history" in detail
        if before is not None:
            assert (tmp_path / f"{SYM}.csv").read_text() == before
        else:
            assert not (tmp_path / f"{SYM}.csv").exists()


def test_lowering_limit_shrinks_cache_instead_of_deadlocking(tmp_path, monkeypatch):
    _cache(tmp_path, "2026-10-04", 250)
    _fake(monkeypatch, _yahoo("2026-10-04", 250))
    assert dd.download_ticker(SYM, tmp_path, limit=100).rows == 100
    saved = _disk(tmp_path)
    expected = _yahoo("2026-10-04", 250).index[-100:].strftime("%Y-%m-%d").tolist()
    assert saved["Date"].tolist() == expected   # the newest 100 sessions, not any 100
    assert saved["Volume"].dtype.kind in "iuf" and (saved["Close"] == 101.0).all()


def test_corrupt_cache_replaced_with_warning(tmp_path, monkeypatch, caplog):
    (tmp_path / f"{SYM}.csv").write_text("not,a,date,column\n1,2,3,4\n")  # no Date column
    _fake(monkeypatch, _yahoo("2026-10-04"))
    with caplog.at_level(logging.WARNING):
        assert dd.download_ticker(SYM, tmp_path).last_date == "2026-10-04"
    assert "cached CSV unreadable" in caplog.text
    saved = _disk(tmp_path)   # the unreadable file was really replaced by a readable one
    assert saved["Date"].iloc[-1] == "2026-10-04" and {"Open", "High", "Low", "Close", "Volume"} <= set(saved.columns)


def test_atomic_write_failure_preserves_old_cache(tmp_path, monkeypatch):
    before = _cache(tmp_path, "2026-10-01")
    _fake(monkeypatch, _yahoo("2026-10-04"))

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(dd.os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        dd.download_ticker(SYM, tmp_path)
    assert (tmp_path / f"{SYM}.csv").read_text() == before
    assert not list(tmp_path.glob(".*.tmp"))   # no temporary file left behind
    monkeypatch.undo()                         # retry after the failure succeeds
    _fake(monkeypatch, _yahoo("2026-10-04"))
    dd.download_ticker(SYM, tmp_path)
    assert _disk(tmp_path)["Date"].iloc[-1] == "2026-10-04"


@pytest.mark.parametrize("override, reason", [
    ({"High": 50.0}, "invalid OHLCV values"),     # High below Close
    ({"Close": float("nan")}, "invalid OHLCV values"),
    ({"Open": -1.0}, "invalid OHLCV values"),
])
def test_expected_equal_to_last_date_keeps_ohlcv_checks_active(override, reason):
    """expected=last date only satisfies the freshness branch; the later elif checks still run."""
    from data_health import DataHealthError, require_daily_data
    frame = _yahoo("2026-10-04", **override).drop(columns="Adj Close")
    with pytest.raises(DataHealthError) as err:
        require_daily_data({SYM: frame}, min_rows=1, expected=frame.index.max().date())
    assert err.value.report["problems"][SYM] == reason


def test_empty_yahoo_rejected_logged_and_cache_untouched(tmp_path, monkeypatch, caplog):
    before = _cache(tmp_path, "2026-10-01")
    _fake(monkeypatch, pd.DataFrame())
    monkeypatch.setattr(dd.time, "sleep", lambda s: None)
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="All downloads failed"):
        dd.download_universe(tmp_path, tickers=(SYM,))
    assert "keeping old CSV=True" in caplog.text
    assert (tmp_path / f"{SYM}.csv").read_text() == before
