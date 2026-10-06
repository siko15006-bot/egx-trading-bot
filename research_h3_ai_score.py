"""H3 AI Score — runs exactly the rule in docs/research/H3_ai_score.md (single pre-registered run).

python research_h3_ai_score.py      (needs data_momentum_2019/ from research_h1_momentum.py --download)
Research only: nothing here is imported by production code.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, ttest_1samp
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import research_h1_momentum as h1

SPLIT = pd.Timestamp(h1.SPLIT)
H, TOP_LIQ = 21, 60
FEATURES = ["r21", "r63", "mom", "r252", "vol63", "rsi14", "ema50_dist", "range252", "liq_trend", "liq"]


def feature_panels(close: pd.DataFrame, value: pd.DataFrame, is_real: pd.DataFrame) -> dict[str, pd.DataFrame]:
    px = close.ffill()
    r = px.pct_change(fill_method=None)
    vol63 = r.rolling(63).std()
    gain, loss = r.clip(lower=0), (-r).clip(lower=0)
    rs = gain.ewm(alpha=1 / 14, adjust=False).mean() / loss.ewm(alpha=1 / 14, adjust=False).mean()
    lo, hi = px.rolling(252, min_periods=147).min(), px.rolling(252, min_periods=147).max()
    v = value.where(is_real)
    return {
        "r21": px / px.shift(21) - 1, "r63": px / px.shift(63) - 1, "mom": px.shift(21) / px.shift(126) - 1,
        "r252": px / px.shift(252) - 1, "vol63": vol63, "rsi14": 100 - 100 / (1 + rs),
        "ema50_dist": (px - px.ewm(span=50, adjust=False).mean()) / (vol63 * px),
        "range252": (px - lo) / (hi - lo), "liq_trend": v.rolling(5, min_periods=1).median() / v.rolling(63, min_periods=1).median(),
        "liq": v.rolling(63, min_periods=1).median(),
    }


def pools(close: pd.DataFrame, value: pd.DataFrame, is_real: pd.DataFrame) -> dict[int, pd.Index]:
    """Same eligibility as research_h1_momentum.run, on the same rebalance grid."""
    real_count, recent = is_real.cumsum(), is_real.rolling(21).sum()
    liq = value.where(is_real).rolling(63, min_periods=1).median()
    out = {}
    for p in range(147, len(close), 21):
        ok = (real_count.iloc[p] >= 147) & (recent.iloc[p] >= 15) & is_real.iloc[p]
        out[p] = liq.iloc[p][ok].dropna().nlargest(TOP_LIQ).index
    return out


def dataset(close, value, is_real) -> pd.DataFrame:
    px = close.ffill()
    feats = feature_panels(close, value, is_real)
    rows = []
    for p, pool in pools(close, value, is_real).items():
        if len(pool) < 10:
            continue
        x = pd.DataFrame({k: f.iloc[p][pool] for k, f in feats.items()})
        x = x.rank(pct=True).fillna(0.5)  # cross-sectional percentile; missing (e.g. <252 bars) → middle
        x["p"], x["date"] = p, px.index[p]
        if p + H < len(px):
            fwd = px.iloc[p + H][pool] / px.iloc[p][pool] - 1
            x["excess"] = fwd - fwd.mean()
            x["label_end"] = px.index[p + H]
        rows.append(x)
    return pd.concat(rows)


def main() -> int:
    close, value, is_real = h1.load_panels()
    fx = pd.read_csv(h1.FX, index_col="Date", parse_dates=True)["USDEGP"]
    d = dataset(close, value, is_real)
    train = d[d["label_end"].notna() & (d["label_end"] < SPLIT)]
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=1000))
    model.fit(train[FEATURES], (train["excess"] > 0).astype(int))
    d["score"] = model.predict_proba(d[FEATURES])[:, 1]
    print(f"train rows {len(train)} on {train['date'].nunique()} days | coefficients:",
          dict(zip(FEATURES, np.round(model[-1].coef_[0], 3))))

    # Level 1: H1 harness with the score as the signal
    score = d.reset_index().pivot_table(index="p", columns="index", values="score")
    score = score.reindex(range(len(close))).set_axis(close.index)
    res = h1.report(*h1.run(close, value, is_real, score=score), fx, "H3 AI SCORE")
    (vh, vb), (th, tb) = res[("USD", "validation")], res[("USD", "train")]
    l1 = {"1 val Sharpe diff >= 0.30": vh["sharpe"] - vb["sharpe"] >= 0.30, "2 val CAGR > EW": vh["cagr"] > vb["cagr"],
          "3 val DD not worse by >10pp": vh["max_dd"] >= vb["max_dd"] - 0.10, "4 train Sharpe > EW": th["sharpe"] > tb["sharpe"]}
    for k, v in l1.items():
        print(f"  {'PASS' if v else 'FAIL'}  L1 {k}")
    level1 = all(l1.values())

    # Level 2: Spearman IC on non-overlapping validation windows
    val = d[(d["date"] >= SPLIT) & d["excess"].notna()]
    ics = val.groupby("date").apply(lambda g: spearmanr(g["score"], g["excess"]).statistic)
    t = ttest_1samp(ics, 0.0, alternative="greater")
    level2 = bool(ics.mean() > 0 and t.pvalue < 0.05)
    print(f"L2 IC: {len(ics)} days, mean {ics.mean():+.4f}, positive days {(ics > 0).mean():.0%}, "
          f"one-sided p = {t.pvalue:.4f} → {'PASS' if level2 else 'FAIL'}")

    verdict = {(True, True): "TRADING-SIGNAL CANDIDATE", (False, True): "SCREENING TOOL ONLY",
               (True, False): "SUSPECT (L1 without L2)", (False, False): "FAIL — H3 closed"}[(level1, level2)]
    print("H3 VERDICT:", verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
