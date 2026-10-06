"""اختبار حاسم قبل القرار: 2020–2021 (COVID)، قياس بالدولار، Walk-Forward لـD_hold_6، والنظام كـ Market Filter.

لا يعدّل egx_4_mirrors_v3.py ولا backtest_optimizer.py — بيستوردهم كما هم.
البيانات: data_2019_2026_wf/ (تحميل واحد متصل 2019-07 → 2026-10 من Yahoo) + نسخة 2020–2021 في data_2020_2021/.
الدولار: كل الأسعار × (USDEGP يوم بداية الفترة ÷ USDEGP اليوم) = مسار الدولار بوحدات جنيه بداية الفترة
(ثابت ضرب واحد، فالعوائد والإشارات = الدولار بالظبط، وحدود الـscreener ورأس المال بتفضل بنفس حجمها في أول يوم).
EGX30 غير متاح على Yahoo → البديل: سلة متساوية الأوزان من الـ9 أسهم (مذكور كقيد في التقرير).

التشغيل: python decision_analysis.py  →  decision_report.md + logs/decision_<date>.log
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backtest_optimizer as bo  # noqa: E402

eng = bo.eng
WF_DIR = HERE / "data_2019_2026_wf"
PERIODS = {"P1 2020-21": ("2020-01-01", "2021-12-31"), "P2 2022-23": ("2022-01-01", "2023-12-31"),
           "P3 2024-26": ("2024-01-01", "2026-10-01")}
WINDOWS = {"W1": ("2020-01-01", "2021-12-31", "2022"), "W2": ("2021-01-01", "2022-12-31", "2023"),
           "W3": ("2022-01-01", "2023-12-31", "2024"), "W4": ("2023-01-01", "2024-12-31", "2025")}
COVID_PHASES = {"Pre-COVID": ("2020-01-01", "2020-02-29"), "Crash": ("2020-03-01", "2020-05-31"), "Recovery": ("2020-06-01", "2020-12-31")}
SHOW = ["Baseline", "A_filters", "B_risk", "C_trend", "D_hold_6"]
TOTAL = eng.RiskConfig().capital * 9
FEE_SIDE = eng.RiskConfig().round_trip_fee_pct


def _ts(day: str, end: bool = False) -> pd.Timestamp:
    return pd.Timestamp(day, tz="UTC") + (pd.Timedelta(days=1) if end else pd.Timedelta(0))


def _cairo_days(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index.tz_convert("Africa/Cairo").strftime("%Y-%m-%d"))


def cut(data_map: dict[str, pd.DataFrame], start: str, end: str) -> dict[str, pd.DataFrame]:
    """بيانات لحد آخر الفترة (التسخين من قبلها مسموح)؛ يستبعد سهم ملوش 60 شمعة قبل البداية + بيانات في الفترة."""
    out = {}
    for t, d in data_map.items():
        d = d[d.index < _ts(end, True)][["Open", "High", "Low", "Close", "Volume"]]
        if (d.index < _ts(start)).sum() >= bo.START_INDEX and (d.index >= _ts(start)).sum() > 20:
            out[t] = d
    return out


def to_usd(data_map: dict[str, pd.DataFrame], fx: pd.Series, start: str) -> dict[str, pd.DataFrame]:
    """سعر بالدولار مقاس بوحدات جنيه يوم البداية: price × fx0 / fx_t (آخر سعر صرف معروف لكل يوم)."""
    fx0 = float(fx.asof(pd.Timestamp(start)))
    out = {}
    for t, d in data_map.items():
        days = _cairo_days(d.index)
        rate = fx.reindex(fx.index.union(days)).ffill().loc[days].to_numpy()
        conv = d.copy()
        conv[["Open", "High", "Low", "Close"]] = d[["Open", "High", "Low", "Close"]].to_numpy() * (fx0 / rate)[:, None]
        out[t] = conv
    return out


def bh_curve(data_map: dict[str, pd.DataFrame], start: str) -> pd.Series:
    """Buy & Hold متساوي الأوزان (نفس طريقة backtest_optimizer: 100,000 لكل سهم من أول يوم اختبار)."""
    parts = []
    for d in data_map.values():
        s = bo._start(d, start)
        parts.append(100_000 * d["Close"].iloc[s:] / float(d["Close"].iloc[s]))
    return bo._combine(parts, 100_000) * 9 / len(parts)


def curve_stats(curve: pd.Series) -> dict[str, float]:
    rets = curve.pct_change().dropna()
    sd = rets.std(ddof=1)
    years = len(curve) / bo.TRADING_DAYS
    tot = float(curve.iloc[-1] / curve.iloc[0] - 1)
    return {"ret": tot, "cagr": (1 + tot) ** (1 / years) - 1 if years > 0 else float("nan"),
            "sharpe": float(rets.mean() / sd * sqrt(bo.TRADING_DAYS)) if sd > 0 else 0.0,
            "dd": float((curve / curve.cummax() - 1).min())}


def d6(data_map: dict[str, pd.DataFrame], start: str) -> dict[str, Any]:
    return bo.simulate_d(data_map, 6, TOTAL, start)


# ------------------------------------------------------------------ اختبار 4: Market Filter
def weekly_buy_counts(data_map: dict[str, pd.DataFrame], start: str) -> pd.Series:
    """آخر يوم تداول في كل أسبوع: عدد الأسهم اللي إشارتها BUY (كل المرايا الأربعة + فلتر الفجوة) في شمعة الأسبوع ده."""
    ind = {t: eng.calculate_indicators(d) for t, d in data_map.items()}
    days = sorted(set().union(*(d.index for d in ind.values())))
    cal = pd.Series(days, index=pd.DatetimeIndex(days))
    cal = cal[cal.index >= _ts(start) - pd.Timedelta(days=7)]
    week_ends = cal.groupby(_cairo_days(cal.index).to_period("W-SAT")).max()
    counts = {}
    sig = eng.SignalConfig()
    for we in week_ends:
        n = 0
        for d in ind.values():
            i = int(d.index.searchsorted(we, side="right")) - 1
            if i >= bo.START_INDEX and (we - d.index[i]) <= pd.Timedelta(days=6):
                n += eng.evaluate_4_mirrors(d.iloc[: i + 1], sig)["signal"] == "BUY"
        counts[we] = n
    return pd.Series(counts)


def filter_backtest(index_ret: pd.Series, counts: pd.Series) -> tuple[pd.Series, pd.Series]:
    """الوزن يتحدد على إغلاق آخر يوم في الأسبوع ويتطبق من اليوم التالي؛ عمولة 0.3% على الجزء المتداول."""
    w = counts.map(lambda c: 1.0 if c >= 5 else 0.5 if c >= 2 else 0.0)
    weight = w.reindex(index_ret.index.union(w.index)).ffill().reindex(index_ret.index).shift(1).fillna(0.0)
    cost = weight.diff().abs().fillna(weight.iloc[0]) * FEE_SIDE
    return (1 + weight * index_ret - cost).cumprod(), weight


def main() -> int:
    log_path = HERE / "logs" / f"decision_{datetime.now():%Y%m%d}.log"

    def log(msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    full = eng.load_data_map(WF_DIR)
    fx = pd.read_csv(WF_DIR / "fx" / "EGP_USD.csv", index_col=0, parse_dates=True).iloc[:, 0].dropna()
    scen = bo.SCENARIOS   # C بـ3×ATR (المختار في optimization_report_v2)
    res: dict[str, Any] = {"periods": {}, "covid": {}, "wf": {}, "filter": {}}
    jumps = fx.pct_change().abs().nlargest(3)
    res["fx"] = {"rows": len(fx), "first": f"{fx.index[0]:%Y-%m-%d}", "last": f"{fx.index[-1]:%Y-%m-%d}",
                 "at": {d: round(float(fx.asof(pd.Timestamp(d))), 2) for d in ("2020-01-01", "2022-01-01", "2024-01-01", "2026-10-01")},
                 "jumps": {f"{k:%Y-%m-%d}": f"{v:+.1%}" for k, v in jumps.items()}}
    log(f"[FX] source=Yahoo EGP=X daily close {json.dumps(res['fx'])}")

    # اختبار 1 + 2: كل السيناريوهات على 3 فترات، بالجنيه وبالدولار
    for name, (start, end) in PERIODS.items():
        base = cut(full, start, end)
        log(f"[PERIOD] {name} tickers={sorted(base)}")
        for cur, dm in (("EGP", base), ("USD", to_usd(base, fx, start))):
            runs, bh = bo.run_suite(dm, scen, start, log, f"{name} {cur}")
            res["periods"][(name, cur)] = {"runs": {k: {"metrics": runs[k]["metrics"], "edge": runs[k]["edge"]} for k in SHOW}, "bh": bh}

    # COVID: منحنى D_hold_6 مقابل B&H جوه فبراير→يونيو 2020
    start, end = PERIODS["P1 2020-21"]
    for cur in ("EGP", "USD"):
        dm = cut(full, start, end)
        dm = dm if cur == "EGP" else to_usd(dm, fx, start)
        d = d6(dm, start)
        bh = bh_curve(dm, start)
        tr = d["trades"]
        for phase, (a, b) in COVID_PHASES.items():
            lo, hi = _ts(a), _ts(b, True)
            # منحنى المرحلة يبدأ من آخر إغلاق قبلها، عشان عائد المرحلة يشمل أول يوم فيها
            dw = d["equity"][d["equity"].index < hi].loc[lambda c: c.index >= c.index[max(0, c.index.searchsorted(lo) - 1)]]
            bw = bh[bh.index < hi].loc[lambda c: c.index >= c.index[max(0, c.index.searchsorted(lo) - 1)]]
            expo = d["exposure"][(d["exposure"].index >= lo) & (d["exposure"].index < hi)]
            opened = tr[(tr.entry_date >= lo) & (tr.entry_date < hi)] if len(tr) else tr
            closed = tr[(tr.exit_date >= lo) & (tr.exit_date < hi)] if len(tr) else tr
            res["covid"][(cur, phase)] = {"D": curve_stats(dw), "BH": curve_stats(bw), "invested": float(expo.mean()),
                                          "opened": len(opened), "closed": len(closed),
                                          "closed_reasons": closed.reason.value_counts().to_dict() if len(closed) else {},
                                          "trades": closed[["ticker", "entry_date", "exit_date", "pnl_pct_pos", "reason"]].astype(str).to_dict("records") if len(closed) else []}
            log(f"[COVID {cur} {phase}] {json.dumps({k: v for k, v in res['covid'][(cur, phase)].items() if k != 'trades'})} closed_trades={res['covid'][(cur, phase)]['trades']}")

    # اختبار 3: Walk-Forward لـD_hold_6 (بدون أي معامل يتضبط في التدريب — بيقيس ثبات الأداء)
    for w, (tr_start, tr_end, year) in WINDOWS.items():
        for cur in ("EGP", "USD"):
            tr_map = cut(full, tr_start, tr_end)
            te_map = cut(full, f"{year}-01-01", f"{year}-12-31")
            if cur == "USD":
                tr_map, te_map = to_usd(tr_map, fx, tr_start), to_usd(te_map, fx, f"{year}-01-01")
            trn, tst = d6(tr_map, tr_start), d6(te_map, f"{year}-01-01")
            row = {"train": curve_stats(trn["equity"]), "test": curve_stats(tst["equity"]),
                   "bh_test": curve_stats(bh_curve(te_map, f"{year}-01-01")),
                   "train_trades": len(trn["trades"]), "test_trades": len(tst["trades"])}
            res["wf"][(w, cur)] = row
            log(f"[WF {w} {cur}] train {tr_start}..{tr_end} sharpe={row['train']['sharpe']:.2f} ret={row['train']['ret']:+.1%} n={row['train_trades']} | "
                f"test {year} sharpe={row['test']['sharpe']:.2f} ret={row['test']['ret']:+.1%} n={row['test_trades']} | B&H test sharpe={row['bh_test']['sharpe']:.2f} ret={row['bh_test']['ret']:+.1%}")

    # اختبار 4: Smart Timing على مؤشر بديل (سلة متساوية الأوزان من الـ9)
    fstart, fend = "2020-01-01", "2026-10-01"
    fmap = cut(full, fstart, fend)
    closes = pd.concat({t: d["Close"] for t, d in fmap.items()}, axis=1).sort_index()
    idx_ret = closes.pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
    idx_ret = idx_ret[idx_ret.index >= _ts(fstart)]
    days = _cairo_days(idx_ret.index)
    rate = fx.reindex(fx.index.union(days)).ffill().loc[days].to_numpy()
    idx_ret_usd = pd.Series((1 + idx_ret.to_numpy()) * np.r_[rate[0], rate[:-1]] / rate - 1, index=idx_ret.index)
    counts = weekly_buy_counts(fmap, fstart)
    dist = counts[counts.index >= _ts(fstart)].value_counts().sort_index().to_dict()
    log(f"[FILTER] weekly BUY-count distribution (weeks): {dist}")
    for cur, r in (("EGP", idx_ret), ("USD", idx_ret_usd)):
        strat, weight = filter_backtest(r, counts)
        bh = (1 + r).cumprod()
        res["filter"][cur] = {"timing": curve_stats(strat), "bh": curve_stats(bh), "avg_weight": float(weight.mean()),
                              "full_weeks_pct": float((counts >= 5).mean()), "half_weeks_pct": float(((counts >= 2) & (counts < 5)).mean())}
        log(f"[FILTER {cur}] {json.dumps(res['filter'][cur])}")
    res["filter"]["dist"] = {int(k): int(v) for k, v in dist.items()}

    rec, conf = decide(res)
    (HERE / "decision_report.md").write_text(build_report(res, rec, conf), encoding="utf-8")
    log(f"[DONE] decision_report.md written rec={rec} conf={conf}")
    return 0


def decide(res: dict) -> tuple[str, str]:
    """قاعدة مكتوبة قبل قراءة النتائج:
    CONTINUE = D_hold_6 يتفوق على B&H بالدولار في Sharpe في ≥2 من 3 فترات.
    PIVOT_TO_FILTER = مش متفوق، لكن (أ) أقل تراجع من B&H بالدولار في ≥2 من 3 فترات، و(ب) Walk-Forward بالدولار: Sharpe الاختبار > 0 في ≥3 من 4 نوافذ.
    ABANDON = غير كده.
    الثقة: HIGH لو ≥100 صفقة وكل الشروط اتحققت في كل الفترات؛ MED لو الشروط اتحققت بالأغلبية؛ LOW لو أي حالة حدّية أو عدد صفقات D < 100."""
    per = [res["periods"][(p, "USD")] for p in PERIODS]
    beats = sum(p["runs"]["D_hold_6"]["metrics"]["sharpe"] > p["bh"]["sharpe"] for p in per)
    shallower = sum(p["runs"]["D_hold_6"]["metrics"]["max_dd"] > p["bh"]["max_dd"] for p in per)
    wf_pos = sum(res["wf"][(w, "USD")]["test"]["sharpe"] > 0 for w in WINDOWS)
    n = sum(p["runs"]["D_hold_6"]["metrics"]["trades"] for p in per)
    rec = "CONTINUE" if beats >= 2 else "PIVOT_TO_FILTER" if shallower >= 2 and wf_pos >= 3 else "ABANDON"
    unanimous = (beats == 3) if rec == "CONTINUE" else (shallower == 3 and wf_pos == 4) if rec == "PIVOT_TO_FILTER" else (beats == 0 and wf_pos <= 1)
    conf = "HIGH" if unanimous and n >= 100 else "MED" if unanimous or n >= 100 else "LOW"
    return rec, conf


def _p(v: float) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v:+.1%}"


def build_report(res: dict, rec: str, conf: str) -> str:
    L = [f"# Decision Report — 4 Mirrors v3 / Scenario D (generated {datetime.now():%Y-%m-%d %H:%M})", "",
         "Every number below uses realistic execution, real Yahoo data (`data_2019_2026_wf/`, one continuous download), and the same engine (`egx_4_mirrors_v3.py`, unmodified). "
         "**USD** = prices converted day by day with Yahoo `EGP=X`. ", "",
         "## Tests 1 + 2 — All scenarios, three periods, EGP and USD", "",
         "| Period | Ccy | Scenario | Trades | PF | Sharpe | Max DD | Total return | Deployed | P(mean R ≤ 0) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for (p, cur), v in res["periods"].items():
        for k, r in v["runs"].items():
            m, e = r["metrics"], r["edge"]
            L.append(f"| {p} | {cur} | {k} | {m['trades']} | {bo._fmt(m['profit_factor'], False)} | {m['sharpe']:.2f} | {m['max_dd']:.1%} | {_p(m['total_return'])} | "
                     f"{m['avg_exposure_pct']:.0f}% | {bo._rate(e['p_le_0'])} |")
        b = v["bh"]
        L.append(f"| {p} | {cur} | **Buy & Hold** | — | — | {b['sharpe']:.2f} | {b['max_dd']:.1%} | {_p(b['total_return'])} | 100% | — |")
    L += ["", "### D_hold_6 vs Buy & Hold — summary", "", "| Period | Ccy | D Sharpe | B&H Sharpe | D DD | B&H DD | D return | B&H return |", "|---|---|---|---|---|---|---|---|"]
    for (p, cur), v in res["periods"].items():
        m, b = v["runs"]["D_hold_6"]["metrics"], v["bh"]
        L.append(f"| {p} | {cur} | {m['sharpe']:.2f} | {b['sharpe']:.2f} | {m['max_dd']:.1%} | {b['max_dd']:.1%} | {_p(m['total_return'])} | {_p(b['total_return'])} |")
    L += ["", "## COVID — three phases, D_hold_6 vs equal-weight Buy & Hold (P1 run, started 2020-01-01)", "",
          "| Phase | Dates | Ccy | D return | D max DD | B&H return | B&H max DD | D avg invested | Opened / closed | Exit reasons |", "|---|---|---|---|---|---|---|---|---|---|"]
    for (cur, phase), c in res["covid"].items():
        a, b = COVID_PHASES[phase]
        L.append(f"| {phase} | {a} → {b} | {cur} | {_p(c['D']['ret'])} | {c['D']['dd']:.1%} | {_p(c['BH']['ret'])} | {c['BH']['dd']:.1%} | {c['invested']:.0%} | "
                 f"{c['opened']} / {c['closed']} | {c['closed_reasons'] or '—'} |")
    L += ["", f"Trades closed in the crash phase (EGP): `{res['covid'][('EGP', 'Crash')]['trades']}`", "",
          "## Test 3 — Walk-forward, D_hold_6 (2-year train → next-year test)", "",
          "D has no fitted parameter, so 'train' here just runs the same fixed rules on the earlier window; the comparison measures stability, not overfitting of a tuned value.", "",
          "| Window | Ccy | Train Sharpe | Test Sharpe | Degradation | Test return | B&H test Sharpe | B&H test return | Test trades |", "|---|---|---|---|---|---|---|---|---|"]
    for cur in ("EGP", "USD"):
        degr = []
        for w in WINDOWS:
            r = res["wf"][(w, cur)]
            degr.append(r["test"]["sharpe"] - r["train"]["sharpe"])
            L.append(f"| {w} → {WINDOWS[w][2]} | {cur} | {r['train']['sharpe']:.2f} | {r['test']['sharpe']:.2f} | {degr[-1]:+.2f} | {_p(r['test']['ret'])} | "
                     f"{r['bh_test']['sharpe']:.2f} | {_p(r['bh_test']['ret'])} | {r['test_trades']} |")
        L.append(f"| **mean {cur}** | | | | **{np.mean(degr):+.2f}** | | | | |")
    f = res["filter"]
    L += ["", "## Test 4 — System as a market filter (Smart Timing), 2020-01 → 2026-10", "",
          "EGX30 is not on Yahoo (`^CASE30`, `^EGX30`, `EGX30.CA`, `^CASE`, `EGPT` all returned nothing), so the index is a **proxy: equal-weight basket of the same 9 stocks** "
          "(daily rebalanced). Weekly: count of stocks with a 4/4 BUY → ≥5: 100%, 2–4: 50%, <2: cash (0% return — EGP T-bill yield not modelled). "
          "Weight is set at the week's last close and applied from the next day; 0.3% per traded side.", "",
          f"Weekly count distribution (count: weeks): `{f['dist']}`", "",
          "| Ccy | Timing return | Timing Sharpe | Timing max DD | B&H return | B&H Sharpe | B&H max DD | Avg weight | Weeks 100% / 50% |", "|---|---|---|---|---|---|---|---|---|"]
    for cur in ("EGP", "USD"):
        x = f[cur]
        L.append(f"| {cur} | {_p(x['timing']['ret'])} | {x['timing']['sharpe']:.2f} | {x['timing']['dd']:.1%} | {_p(x['bh']['ret'])} | {x['bh']['sharpe']:.2f} | "
                 f"{x['bh']['dd']:.1%} | {x['avg_weight']:.0%} | {x['full_weeks_pct']:.0%} / {x['half_weeks_pct']:.0%} |")
    x = res["fx"]
    L += ["", "## Limitations (read before the decision)", "",
          "1. **The index in test 4 is NOT EGX30.** It is an *equal-weight* basket of 9 stocks, rebalanced daily. EGX30 is *cap-weighted* (free-float, capped) over 30 stocks "
          "and dominated by a few names (e.g. COMI alone is a large share of it). Equal weight gives small/mid names far more influence and rebalances in a way no "
          "real index fund does, so the proxy's return, volatility and drawdown can differ materially from EGX30. It is also built from the same 9 stocks the filter "
          "reads, which flatters the filter (signal and market are the same basket). **Test 4 is an idea check, not an EGX30 result.**",
          f"2. **USD conversion** uses the *historical daily* USD/EGP close from **Yahoo Finance `EGP=X`** ({x['rows']} rows, {x['first']} → {x['last']}), "
          f"forward-filled to each EGX trading day — not a constant. Spot checks: {x['at']}. Largest daily moves (devaluations): {x['jumps']}. "
          "Yahoo's EGP=X is the official/bank rate; during 2022–2023 the parallel-market rate was materially weaker, so USD results for those years are, if anything, optimistic. "
          "Stooq was not used (blocked by a bot-check, which was not bypassed).",
          "3. **Small samples.** D_hold_6 trades per period are a few dozen; walk-forward test years have even fewer. Any Sharpe difference below ~0.5 between D and B&H is within noise.",
          "4. **Cash earns 0%.** EGP deposits/T-bills paid ~8–27% over 2020–2026. Every strategy that holds cash (all of them, D ~50–65%, timing filter) is understated in EGP; "
          "in USD the gap is smaller but still non-zero.",
          "5. **Survivorship / universe:** the 9 stocks were chosen in 2026 (today's large caps). EFIH has no data before 2021-10 and is absent from P1 and W1. "
          "MNHD = Yahoo `MASR.CA` (renamed). Yahoo prices are auto-adjusted; frozen/no-trade bars removed.",
          "6. **Costs:** 0.3% per side + 10% tax on gains, no slippage beyond open-gap fills, liquidity capped at 1% of 20-day average volume.", "",
          "## Decision rule (fixed before the run)", "",
          "- CONTINUE: D_hold_6 beats Buy & Hold on USD Sharpe in ≥2 of 3 periods.",
          "- PIVOT_TO_FILTER: it doesn't, but its USD max DD is shallower than B&H in ≥2 of 3 periods AND walk-forward USD test Sharpe > 0 in ≥3 of 4 windows.",
          "- ABANDON: otherwise. Confidence: HIGH only if unanimous and ≥100 D trades; MED if unanimous or ≥100 trades; LOW otherwise.", "",
          f"**Rule output: {rec} — confidence {conf}**", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
