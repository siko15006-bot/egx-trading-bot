"""L1 — low-volatility anomaly on EGX. Rules: docs/research/L1_low_volatility.md. Harness: research_h1_momentum.run.

python research_l1_lowvol.py   # the pre-registered run + sensitivity -> docs/research/L1_result.txt
Research only: nothing here is imported by production code; no order execution.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import research_h1_momentum as h1

HERE = Path(__file__).parent
DATA = HERE / "data_l1"
IS, OOS = ("2010-01-01", "2020-12-31"), ("2021-01-01", "2026-06-30")
BASE = dict(window=252, top_n=10, top_liq=60, fee=0.003, lag=0)


def lowvol_score(close: pd.DataFrame, is_real: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """Minus the std of daily returns ending on a real bar over the last `window` sessions (>= 200/252 of them)."""
    r = close.ffill().pct_change(fill_method=None).where(is_real)
    return -r.rolling(window, min_periods=round(window * 200 / 252)).std()


def holdings(close, value, is_real, score, top_n, top_liq) -> list[set]:
    """The names h1.run holds after each rebalance (same eligibility and ranking), for trade counts."""
    real_count, recent = is_real.cumsum(), is_real.rolling(21).sum()
    liq = value.where(is_real).rolling(63, min_periods=1).median()
    out, held = [], set()
    for p in range(147, len(close), 21):
        ok = (real_count.iloc[p] >= 147) & (recent.iloc[p] >= 15) & is_real.iloc[p]
        pool = liq.iloc[p][ok].dropna().nlargest(top_liq).index
        sig = score.iloc[p][pool].dropna()
        held = set(sig.nlargest(top_n).index) if len(sig) else held
        out.append((close.index[p], held))
    return out


def simulate(close, value, is_real, window, top_n, top_liq, fee, lag):
    h1.FEE_PER_SIDE = fee
    score = lowvol_score(close, is_real, window).shift(lag)
    return h1.run(close, value, is_real, top_n=top_n, top_liq=top_liq, score=score), score


def period_stats(r: pd.Series, dates: list, lo: str, hi: str) -> dict:
    eq = (1 + r).cumprod()
    d = [x for x in dates if lo <= str(x.date()) <= hi]
    p = eq.reindex(d, method="ffill").pct_change().dropna()
    loss = -p[p < 0].sum()
    return dict(win=float((p > 0).mean()), pf=float(p[p > 0].sum() / loss) if loss > 0 else np.nan)


def main() -> int:
    close, value, real = h1.load_panels(DATA)
    fx = pd.read_csv(DATA / "_meta" / "_EGPUSD.csv", index_col="Date", parse_dates=True).iloc[:, 0]
    (h, b), score = simulate(close, value, real, **BASE)
    (hg, _), _ = simulate(close, value, real, **(BASE | dict(fee=0.0)))
    hold = holdings(close, value, real, score, BASE["top_n"], BASE["top_liq"])
    dates = [d for d, _ in hold]
    lines = [f"panel: {close.shape[1]} tickers, {close.index[0].date()} -> {close.index[-1].date()}; base {BASE}"]
    res = {}
    for tag, (lo, hi) in {"IS": IS, "OOS": OOS}.items():
        for cur in ("EGP", "USD"):
            hh, bb = (h, b) if cur == "EGP" else (h1.to_usd(h, fx), h1.to_usd(b, fx))
            mh, mb = h1.metrics(hh[lo:hi]), h1.metrics(bb[lo:hi])
            res[(tag, cur)] = (mh, mb)
            lines.append(f"{tag:3s} {cur} L1 total {(1 + hh[lo:hi]).prod() - 1:+8.1%} CAGR {mh['cagr']:+6.1%} DD {mh['max_dd']:+6.1%} "
                         f"Sharpe {mh['sharpe']:5.2f} | EW total {(1 + bb[lo:hi]).prod() - 1:+8.1%} CAGR {mb['cagr']:+6.1%} "
                         f"DD {mb['max_dd']:+6.1%} Sharpe {mb['sharpe']:5.2f}")
        trades = sum(len(a ^ c) for (da, a), (_, c) in zip(hold, hold[1:]) if lo <= str(da.date()) <= hi)
        ps = period_stats(h, dates, lo, hi)
        drag = h1.metrics(hg[lo:hi])["cagr"] - res[(tag, "EGP")][0]["cagr"]
        lines.append(f"{tag:3s}     21-session periods: win {ps['win']:.1%} PF {ps['pf']:.2f} | trades (names in/out) {trades} "
                     f"| cost drag {drag:.2%}/yr")
    later = (1 + h["2026-07-01":]).prod() - 1, (1 + b["2026-07-01":]).prod() - 1
    lines.append(f"2026-07 to date (not judged): L1 {later[0]:+.1%} vs EW {later[1]:+.1%}")

    variants = {"window 63": dict(window=63), "window 126": dict(window=126), "hold 5": dict(top_n=5),
                "hold 15": dict(top_n=15), "pool top30": dict(top_liq=30), "pool top100": dict(top_liq=100),
                "cost 0.15%": dict(fee=0.0015), "cost 0.50%": dict(fee=0.005), "signal lag 1": dict(lag=1)}
    lines.append("\n-- sensitivity (OOS, EGP) --")
    wins = 0
    for name, kw in variants.items():
        (vh, vb), _ = simulate(close, value, real, **(BASE | kw))
        mh, mb = h1.metrics(vh[OOS[0]:OOS[1]]), h1.metrics(vb[OOS[0]:OOS[1]])
        wins += mh["sharpe"] > mb["sharpe"]
        lines.append(f"{name:12s} L1 Sharpe {mh['sharpe']:5.2f} CAGR {mh['cagr']:+6.1%} DD {mh['max_dd']:+6.1%} | "
                     f"EW Sharpe {mb['sharpe']:5.2f} CAGR {mb['cagr']:+6.1%} DD {mb['max_dd']:+6.1%}")
    robust = wins / len(variants)

    (oe, oeb), (ou, oub) = res[("OOS", "EGP")], res[("OOS", "USD")]
    (ie, ieb), (iu, iub) = res[("IS", "EGP")], res[("IS", "USD")]
    if oe["sharpe"] <= oeb["sharpe"]:
        word = "REJECT"
    elif (oe["sharpe"] >= oeb["sharpe"] + 0.20 and ou["sharpe"] >= oub["sharpe"] + 0.20 and oe["max_dd"] >= oeb["max_dd"]
          and ie["sharpe"] > ieb["sharpe"] and iu["sharpe"] > iub["sharpe"] and robust >= 0.8):
        word = "PASS"
    else:
        word = "WEAK"
    lines.append(f"\n== VERDICT (pre-registered) == L1: {word}  (OOS Sharpe EGP {oe['sharpe']:.2f} vs {oeb['sharpe']:.2f}, "
                 f"USD {ou['sharpe']:.2f} vs {oub['sharpe']:.2f}; IS EGP {ie['sharpe']:.2f} vs {ieb['sharpe']:.2f}, "
                 f"USD {iu['sharpe']:.2f} vs {iub['sharpe']:.2f}; variants above EW {robust:.0%})")
    text = "\n".join(lines)
    print(text)
    (HERE / "docs" / "research" / "L1_result.txt").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
