"""research_h1_momentum.download (data_h3_live): a truncated Yahoo response never replaces cached history."""
import json

import pandas as pd
import pytest

import research_h1_momentum as h1

FIELDS = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]


def _frame(days: int) -> pd.DataFrame:
    idx = pd.bdate_range(end="2026-10-08", periods=days, freq="C", weekmask="Sun Mon Tue Wed Thu")
    return pd.DataFrame({"Open": 10.0, "High": 10.5, "Low": 9.5, "Close": 10.0, "Adj Close": 10.0, "Volume": 1000.0,
                         "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)[FIELDS]


def _setup(tmp_path, monkeypatch, responses: dict[str, int]):
    """responses: ticker -> rows Yahoo returns. Every ticker has a cached 300-row file."""
    (tmp_path / "egx_universe.json").write_text(json.dumps({"records": [{"ticker": t} for t in responses]}))
    out = tmp_path / "data_h3_live"
    out.mkdir()
    for t in responses:
        _frame(300)[["Open", "High", "Low", "Close", "Volume"]].rename_axis("Date").to_csv(out / f"{t}.csv")
    monkeypatch.setattr(h1, "HERE", tmp_path)
    monkeypatch.setattr(h1, "OUT", out)
    monkeypatch.setattr(h1, "EXTRA", [])
    raw = pd.concat({t: _frame(n) for t, n in responses.items()}, axis=1)
    monkeypatch.setattr("yfinance.download", lambda *a, **k: raw)
    return out


def test_one_row_response_keeps_the_cached_file(tmp_path, monkeypatch):
    tickers = {f"T{k:02d}.CA": 310 for k in range(30)} | {"ONE.CA": 1}  # 1/31 rejected: under the 5% limit
    out = _setup(tmp_path, monkeypatch, tickers)
    h1.download()
    assert len(pd.read_csv(out / "ONE.CA.csv")) == 300          # history kept
    assert len(pd.read_csv(out / "T00.CA.csv")) == 310          # normal tickers updated


def test_broken_response_fails_the_download(tmp_path, monkeypatch):
    tickers = {f"T{k:02d}.CA": 310 for k in range(10)} | {f"ONE{k}.CA": 1 for k in range(3)}  # 3/13 rejected
    out = _setup(tmp_path, monkeypatch, tickers)
    with pytest.raises(RuntimeError, match="Yahoo response looks broken"):
        h1.download()
    assert all(len(pd.read_csv(out / f"ONE{k}.CA.csv")) == 300 for k in range(3))
