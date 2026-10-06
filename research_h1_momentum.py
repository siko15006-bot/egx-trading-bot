"""H1 momentum rotation — runs exactly the rule in docs/research/H1_momentum_rotation.md.

python research_h1_momentum.py --download   # once: fully adjusted prices → data_momentum_2019/
python research_h1_momentum.py              # the single pre-registered run (+ info-only variants)
Research only: nothing here is imported by production code.
"""
from __future__ import annotations

import json
import sys
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "data_momentum_2019"
FX = HERE / "data_2019_2026_wf" / "fx" / "EGP_USD.csv"
EXTRA = ["TALM.CA", "KZPC.CA"]
FEE_PER_SIDE = 0.003 / 2  # RiskConfig.round_trip_fee_pct, charged per unit traded on each side
SPLIT = "2023-01-01"


def download() -> None:
    import yfinance as yf

    manifest = json.loads((HERE / "egx_universe.json").read_text(encoding="utf-8"))
    tickers = sorted({r["ticker"] for r in manifest["records"]} | set(EXTRA))
    OUT.mkdir(exist_ok=True)
    raw = yf.download(tickers, start="2019-01-01", auto_adjust=True, actions=False, group_by="ticker",
                      threads=True, progress=False, timeout=30)
    saved = 0
    for t in tickers:
        frame = raw[t].dropna(how="all") if t in raw.columns.get_level_values(0) else pd.DataFrame()
        if len(frame):
            frame.index = pd.to_datetime(frame.index).strftime("%Y-%m-%d")
            frame.index.name = "Date"
            frame[["Open", "High", "Low", "Close", "Volume"]].to_csv(OUT / f"{t}.csv")
            saved += 1
    print(f"requested {len(tickers)}, saved {saved}, yfinance {yf.__version__}")


def load_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    closes, values, real = {}, {}, {}
    for f in sorted(OUT.glob("*.csv")):
        d = pd.read_csv(f, index_col="Date")
        filler = (d["Volume"] == 0) & (d["Open"] == d["High"]) & (d["High"] == d["Low"]) & (d["Low"] == d["Close"])
        d = d[~filler & d["Close"].gt(0)]
        closes[f.stem], values[f.stem] = d["Close"], d["Close"] * d["Volume"]
        real[f.stem] = pd.Series(True, index=d.index)
    close = pd.DataFrame(closes).sort_index()
    close.index = pd.to_datetime(close.index)
    # Calendar = days when at least a quarter of the listed names traded (drops Yahoo stray dates).
    listed = close.notna().cumsum().gt(0).sum(axis=1)
    close = close[close.notna().sum(axis=1) >= 0.25 * listed]
    value = pd.DataFrame(values).set_axis(pd.to_datetime(pd.DataFrame(values).index)).reindex(close.index)
    is_real = close.notna()
    return close, value, is_real


def run(close: pd.DataFrame, value: pd.DataFrame, is_real: pd.DataFrame,
        lookback: int = 126, skip: int = 21, top_n: int = 10, top_liq: int = 60) -> tuple[pd.Series, pd.Series]:
    """Daily EGP returns of (H1, equal-weight benchmark). Weights drift between rebalances."""
    px = close.ffill()
    rets = px.pct_change().fillna(0.0)
    real_count, recent = is_real.cumsum(), is_real.rolling(21).sum()
    liq = value.where(is_real).rolling(63, min_periods=1).median()
    start = max(147, lookback)
    rebal = set(range(start, len(px), 21))
    w_h, w_b = pd.Series(dtype=float), pd.Series(dtype=float)
    out_h, out_b = [], []
    for p in range(len(px)):
        day_r = rets.iloc[p]
        r_h = float((w_h * day_r.reindex(w_h.index)).sum()) if len(w_h) else 0.0
        r_b = float((w_b * day_r.reindex(w_b.index)).sum()) if len(w_b) else 0.0
        if len(w_h):
            w_h = w_h * (1 + day_r.reindex(w_h.index)) / (1 + r_h)
        if len(w_b):
            w_b = w_b * (1 + day_r.reindex(w_b.index)) / (1 + r_b)
        if p in rebal:  # signal and trade at this close; returns from p+1 on
            ok = (real_count.iloc[p] >= 147) & (recent.iloc[p] >= 15) & is_real.iloc[p]
            pool = liq.iloc[p][ok].dropna().nlargest(top_liq).index
            signal = (px.iloc[p - skip] / px.iloc[p - lookback] - 1)[pool].dropna()
            assert p - skip < p and p - lookback >= 0  # signal uses only past closes
            new_h = pd.Series(1 / min(top_n, len(signal)), index=signal.nlargest(top_n).index) if len(signal) else w_h
            new_b = pd.Series(1 / len(pool), index=pool) if len(pool) else w_b
            r_h -= FEE_PER_SIDE * new_h.sub(w_h, fill_value=0).abs().sum()
            r_b -= FEE_PER_SIDE * new_b.sub(w_b, fill_value=0).abs().sum()
            w_h, w_b = new_h, new_b
        out_h.append(r_h)
        out_b.append(r_b)
    first = min(rebal)
    idx = px.index[first + 1:]
    return pd.Series(out_h[first + 1:], idx), pd.Series(out_b[first + 1:], idx)


def to_usd(r: pd.Series, usdegp: pd.Series) -> pd.Series:
    fx = usdegp.reindex(r.index).ffill()
    usd = (1 + r) * fx.shift(1) / fx - 1
    return usd.dropna()


def metrics(r: pd.Series) -> dict[str, float]:
    eq = (1 + r).cumprod()
    years = len(r) / 252
    return {"sharpe": float(r.mean() / r.std(ddof=1) * sqrt(252)) if r.std(ddof=1) > 0 else 0.0,
            "cagr": float(eq.iloc[-1] ** (1 / years) - 1), "max_dd": float((eq / eq.cummax() - 1).min()),
            "days": len(r)}


def report(h: pd.Series, b: pd.Series, usdegp: pd.Series, label: str) -> dict:
    res = {}
    for ccy, (hh, bb) in {"USD": (to_usd(h, usdegp), to_usd(b, usdegp)), "EGP": (h, b)}.items():
        end = min(hh.index[-1], usdegp.index[-1]) if ccy == "USD" else hh.index[-1]
        for name, lo, hi in [("train", hh.index[0], pd.Timestamp(SPLIT) - pd.Timedelta(days=1)),
                             ("validation", pd.Timestamp(SPLIT), end)]:
            mh, mb = metrics(hh[lo:hi]), metrics(bb[lo:hi])
            res[(ccy, name)] = (mh, mb)
            print(f"{label:22s} {ccy} {name:10s} H1 Sharpe {mh['sharpe']:5.2f} CAGR {mh['cagr']:+7.1%} DD {mh['max_dd']:6.1%} | "
                  f"EW Sharpe {mb['sharpe']:5.2f} CAGR {mb['cagr']:+7.1%} DD {mb['max_dd']:6.1%} | days {mh['days']}")
    return res


def main() -> int:
    if "--download" in sys.argv:
        download()
        return 0
    close, value, is_real = load_panels()
    fx = pd.read_csv(FX, index_col="Date", parse_dates=True)["USDEGP"]
    print(f"panel: {close.shape[1]} tickers, {close.index[0].date()} -> {close.index[-1].date()}, FX to {fx.index[-1].date()}")
    h, b = run(close, value, is_real)
    res = report(h, b, fx, "PRE-REGISTERED")
    (vh, vb), (th, tb) = res[("USD", "validation")], res[("USD", "train")]
    checks = {
        "1 val Sharpe diff >= 0.30": vh["sharpe"] - vb["sharpe"] >= 0.30,
        "2 val CAGR > benchmark": vh["cagr"] > vb["cagr"],
        "3 val DD not worse by >10pp": vh["max_dd"] >= vb["max_dd"] - 0.10,
        "4 train Sharpe > benchmark": th["sharpe"] > tb["sharpe"],
    }
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print("H1 VERDICT:", "PASS" if all(checks.values()) else "FAIL")
    print("\n-- info only, never used to choose --")
    for lb, n in [(63, 10), (252, 10), (126, 5), (126, 15)]:
        report(*run(close, value, is_real, lookback=lb, top_n=n), fx, f"lookback {lb} N {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
