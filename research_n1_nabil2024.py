"""N1 — proxy test of Nabil et al. (2024) strategies A (RP/momentum) and B (MACO). Rules: docs/research/N1_nabil2024_replication.md.

python research_n1_nabil2024.py --download   # once: Yahoo 2009+ with the split fix -> data_n1/ (gitignored)
python research_n1_nabil2024.py              # the pre-registered run + sensitivity -> docs/research/N1_result.txt
Research only: nothing here is imported by production code; no order execution.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
DATA = HERE / "data_n1"
START = "2009-01-01"
IS = ("2010-01-01", "2020-12-31")
OOS = ("2021-01-01", "2026-06-30")
SLOTS, RANK_WINDOW, MIN_REAL = 30, 126, 100
GRID = (20, 50, 100, 150, 200)
ANNUAL = 248


@dataclass(frozen=True)
class Cfg:
    strategy: str = "A"            # "A" (APP/RPP), "B" (MACO), "EW" (benchmark)
    n: int = 100                   # SMA length for B
    cost: float = 0.003            # per side
    lag: int = 1                   # 1 = trade at the next close; 0 = at the signal close (paper's optimistic reading)
    mixed_keep: bool = True        # M1: disagreeing signals keep the state; False = M2 (IN only if both positive)
    index_top: int = SLOTS         # names in the proxy index
    months: int = 6                # interval length


# ---------------------------------------------------------------- data
def download() -> None:
    import yfinance as yf
    from data_downloader import apply_backadjust_fix, to_adjusted
    import data_downloader as dd

    DATA.mkdir(exist_ok=True)
    dd.FIX_LOG, dd.RAW_ARCHIVE = DATA / "_backadjust_fixes.jsonl", DATA / "_yahoo_raw"
    tickers = sorted({r["ticker"] for r in json.loads((HERE / "egx_universe.json").read_text(encoding="utf-8"))["records"]})
    raw = yf.download(tickers, start=START, auto_adjust=False, actions=True, group_by="ticker", threads=True,
                      progress=False, timeout=30)
    saved, failed = 0, []
    for t in tickers:
        frame = raw[t].dropna(how="all", subset=["Close"]) if t in raw.columns.get_level_values(0) else pd.DataFrame()
        if not len(frame):
            continue
        try:
            frame = to_adjusted(apply_backadjust_fix(frame, t, DATA.name))
        except ValueError as exc:
            failed.append(str(exc))
            continue
        frame.index = pd.to_datetime(frame.index).strftime("%Y-%m-%d")
        frame.index.name = "Date"
        frame[["Open", "High", "Low", "Close", "Volume"]].to_csv(DATA / f"{t}.csv")
        saved += 1
    fx = yf.download("EGP=X", start=START, auto_adjust=False, progress=False, timeout=30)["Close"].squeeze()
    fx.rename("EGP_per_USD").rename_axis("Date").to_csv(DATA / "_EGPUSD.csv")
    (DATA / "_manifest.json").write_text(json.dumps(dict(
        fetched_at=pd.Timestamp.now(tz="Africa/Cairo").isoformat(), yfinance=yf.__version__, start=START,
        requested=len(tickers), saved=saved, rejected=failed,
        prices="fully adjusted: auto_adjust=False + data_downloader.apply_backadjust_fix + to_adjusted"), indent=1),
        encoding="utf-8")
    print(f"requested {len(tickers)}, saved {saved}, rejected {len(failed)}")


def load(folder: Path = DATA):
    """Close (fully adjusted), traded value and real-bar mask on one calendar (sessions where >= 25% of listed names trade)."""
    closes, values = {}, {}
    for f in sorted(folder.glob("*.CA.csv")):
        d = pd.read_csv(f, index_col="Date")
        d = d[d["Close"].gt(0)]
        closes[f.stem], values[f.stem] = d["Close"], (d["Close"] * d["Volume"]).where(d["Volume"] > 0)
    close = pd.DataFrame(closes).sort_index()
    close.index = pd.to_datetime(close.index)
    listed = close.notna().cumsum().gt(0).sum(axis=1)
    value = pd.DataFrame(values).set_axis(pd.to_datetime(pd.DataFrame(values).index)).reindex(close.index)
    real = value.notna()
    keep = real.sum(axis=1) >= 0.25 * listed
    return close[keep], value[keep], real[keep]


# ---------------------------------------------------------------- rules
def periods(index: pd.DatetimeIndex, months: int) -> list[tuple[int, int]]:
    """(anchor, end) positions: anchor = last session of the previous interval, end = last session of this one."""
    key = index.year * 12 + (index.month - 1) // months
    ends = np.flatnonzero(np.r_[key[1:] != key[:-1], True])
    return [(int(a), int(e)) for a, e in zip(ends[:-1], ends[1:])]


def universe(value: pd.DataFrame, real: pd.DataFrame, anchor: int, top: int) -> list[str]:
    """Proxy EGX30 (P1): top names by median traded value over the last RANK_WINDOW sessions up to the anchor."""
    w = slice(max(0, anchor - RANK_WINDOW + 1), anchor + 1)
    ok = real.iloc[w].sum() >= MIN_REAL
    return list(value.iloc[w].median()[ok].dropna().nlargest(top).index)


def states(px: pd.DataFrame, idx: pd.Series, anchor_pos: int, cfg: Cfg) -> pd.DataFrame:
    """IN (1) / OUT (0) decided at each close of the interval rows (positions > anchor_pos in px)."""
    rp = px.div(idx, axis=0)
    if cfg.strategy == "A":
        up = (px / px.iloc[anchor_pos] > 1) & (rp / rp.iloc[anchor_pos] > 1)
        down = (px / px.iloc[anchor_pos] < 1) & (rp / rp.iloc[anchor_pos] < 1)
    else:
        ap_sma, rp_sma = px.rolling(cfg.n).mean(), rp.rolling(cfg.n).mean()
        up, down = (px > ap_sma) & (rp > rp_sma), (px < ap_sma) & (rp < rp_sma)
    up, down = up.iloc[anchor_pos + 1:], down.iloc[anchor_pos + 1:]
    if not cfg.mixed_keep:
        return up.astype(float)
    st = pd.DataFrame(np.where(up, 1.0, np.where(down, 0.0, np.nan)), index=up.index, columns=up.columns)
    st.iloc[0] = st.iloc[0].fillna(0.0)  # every interval starts OUT
    return st.ffill()


@dataclass
class Result:
    value: pd.Series          # portfolio value at each close (starts at 1)
    halves: pd.DataFrame      # per interval: start, end, ret, cost (fraction of the interval's starting value), n
    trades: pd.DataFrame      # round trips: ticker, start (entry date), entry, exit, ret (net of both sides)
    exposure: pd.Series | None = None  # share of the interval's slots IN at each close (info only)


def run(close: pd.DataFrame, value: pd.DataFrame, real: pd.DataFrame, cfg: Cfg) -> Result:
    px = close.ffill()
    ret = px.pct_change(fill_method=None).fillna(0.0)
    hist = max(GRID) + 5
    v_total, out_v, out_d, out_x, halves, trades = 1.0, [], [], [], [], []
    for anchor, end in periods(close.index, cfg.months):
        if anchor < RANK_WINDOW or close.index[end] < pd.Timestamp(IS[0]):
            continue
        names = universe(value, real, anchor, SLOTS)
        idx_names = names if cfg.index_top == SLOTS else universe(value, real, anchor, cfg.index_top)
        lo = max(0, anchor - hist)
        idx = (1 + ret.iloc[lo:end + 1][idx_names].mean(axis=1)).cumprod()  # P2: EW proxy index
        if cfg.strategy != "EW":
            want = states(px.iloc[lo:end + 1][names], idx, anchor - lo, cfg)
        slot = np.full(len(names), v_total / len(names))
        held = np.zeros(len(names), bool)
        entry, entry_d = np.zeros(len(names)), [None] * len(names)
        start_v, cost = v_total, 0.0
        for k, d in enumerate(range(anchor + 1, end + 1)):
            slot = np.where(held, slot * (1 + ret.iloc[d][names].to_numpy()), slot)
            if cfg.strategy == "EW":
                target = np.ones(len(names), bool)
            else:
                j = k - cfg.lag                                   # decision row traded at this close
                target = want.iloc[j].to_numpy() > 0.5 if j >= 0 else np.zeros(len(names), bool)
            if d == end:
                target = np.zeros(len(names), bool)               # every slot closed at the interval's last close
            can = real.iloc[d][names].to_numpy() | (d == end)     # a filler bar never fills (except the forced close)
            change = (target != held) & can
            fee = np.where(change, slot * cfg.cost, 0.0)
            cost += fee.sum()
            for i in np.flatnonzero(change & ~held):
                entry[i], entry_d[i] = slot[i], close.index[d]    # capital committed, before the buy cost
            slot = slot - fee
            for i in np.flatnonzero(change & held):
                trades.append((names[i], entry_d[i], entry[i], slot[i]))
            held = np.where(change, target, held)
            out_v.append(slot.sum())
            out_x.append(held.mean())
            out_d.append(close.index[d])
        v_total = slot.sum()
        halves.append((close.index[anchor + 1], close.index[end], v_total / start_v - 1, cost / start_v, cfg.n))
    t = pd.DataFrame(trades, columns=["ticker", "start", "entry", "exit"])
    t["ret"] = t["exit"] / t["entry"] - 1
    return Result(pd.Series(out_v, index=pd.DatetimeIndex(out_d)),
                  pd.DataFrame(halves, columns=["start", "end", "ret", "cost", "n"]), t,
                  pd.Series(out_x, index=pd.DatetimeIndex(out_d)))


def walk_forward_b(close, value, real, base: Cfg) -> Result:
    """B with N chosen per interval by the best net Sharpe over the previous 4 intervals (ties -> larger N; first 4: N=100).
    Intervals are independent (each restarts from the portfolio value), so the chosen N's interval returns splice exactly."""
    runs = {n: run(close, value, real, replace(base, strategy="B", n=n)) for n in GRID}
    h = runs[GRID[0]].halves
    rets, rows, trades = [], [], []
    for k in range(len(h)):
        if k < 4:
            n = 100
        else:
            lo, hi = h["start"].iloc[k - 4], h["end"].iloc[k - 1]
            score = {m: _sharpe(runs[m].value.loc[lo:hi].pct_change().dropna()) for m in GRID}
            n = max(GRID, key=lambda m: (round(score[m], 12), m))
        r = runs[n]
        s, e = h["start"].iloc[k], h["end"].iloc[k]
        v = r.value
        prev = v.loc[:s].iloc[:-1]
        seg = v.loc[s:e] / (prev.iloc[-1] if len(prev) else 1.0)
        rets.append(seg.pct_change().fillna(seg.iloc[0] - 1))
        rows.append(r.halves.iloc[k])
        trades.append(r.trades[(r.trades["start"] >= s) & (r.trades["start"] <= e)])
    return Result((1 + pd.concat(rets)).cumprod(), pd.DataFrame(rows).reset_index(drop=True),
                  pd.concat(trades, ignore_index=True))


# ---------------------------------------------------------------- metrics
def _sharpe(r: pd.Series) -> float:
    return float(r.mean() / r.std() * np.sqrt(ANNUAL)) if len(r) > 2 and r.std() > 0 else float("nan")


def metrics(v: pd.Series, lo: str, hi: str, fx: pd.Series | None = None) -> dict:
    s = v.loc[lo:hi]
    prev = v.loc[:lo].iloc[:-1]
    s = pd.concat([prev.iloc[-1:], s]) if len(prev) else s
    if fx is not None:
        s = s / fx.reindex(s.index).ffill()
    r = s.pct_change().dropna()
    years = (s.index[-1] - s.index[0]).days / 365.25
    total = s.iloc[-1] / s.iloc[0] - 1
    return dict(total=total, cagr=(1 + total) ** (1 / years) - 1 if years > 0 else np.nan,
                maxdd=float((s / s.cummax() - 1).min()), sharpe=_sharpe(r))


def trade_stats(t: pd.DataFrame, lo: str, hi: str) -> dict:
    t = t[(t["start"] >= lo) & (t["start"] <= hi)]
    pnl = t["exit"] - t["entry"]
    loss = -pnl[pnl < 0].sum()
    return dict(trades=len(t), win=float((t["ret"] > 0).mean()) if len(t) else np.nan,
                pf=float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan)


def cost_drag(h: pd.DataFrame, lo: str, hi: str) -> float:
    """Average annual cost, % of the portfolio value."""
    h = h[(h["start"] >= lo) & (h["end"] <= hi)]
    years = len(h) * 0.5
    return float(h["cost"].sum() / years) if years else np.nan


def evaluate(close, value, real, fx, cfg: Cfg) -> dict:
    """Strategy (A, or B walk-forward when cfg.strategy == 'B') and its EW benchmark under the same costs/intervals."""
    strat = walk_forward_b(close, value, real, cfg) if cfg.strategy == "B" else run(close, value, real, cfg)
    bench = run(close, value, real, replace(cfg, strategy="EW"))
    out = {"strat": strat, "bench": bench}
    for tag, (lo, hi) in {"IS": IS, "OOS": OOS}.items():
        for cur, f in (("EGP", None), ("USD", fx)):
            out[(tag, cur)] = metrics(strat.value, lo, hi, f), metrics(bench.value, lo, hi, f)
    return out


def paired_t(strat: Result, bench: Result, lo: str, hi: str):
    from scipy.stats import ttest_rel
    a = strat.halves[(strat.halves["start"] >= lo) & (strat.halves["end"] <= hi)]["ret"].to_numpy()
    b = bench.halves[(bench.halves["start"] >= lo) & (bench.halves["end"] <= hi)]["ret"].to_numpy()
    t = ttest_rel(a, b, alternative="greater")
    return a.mean(), b.mean(), float(t.statistic), float(t.pvalue), len(a)


def _fmt(m: dict) -> str:
    return f"total {m['total']:+8.1%} CAGR {m['cagr']:+6.1%} DD {m['maxdd']:+6.1%} Sharpe {m['sharpe']:5.2f}"


def main() -> int:
    close, value, real = load()
    fx = pd.read_csv(DATA / "_EGPUSD.csv", index_col="Date", parse_dates=True).iloc[:, 0]
    lines = [f"panel: {close.shape[1]} tickers, {close.index[0].date()} -> {close.index[-1].date()}; "
             f"IS {IS[0]}..{IS[1]}, OOS {OOS[0]}..{OOS[1]}; base cost {Cfg().cost:.2%}/side, next-close execution"]
    verdict, base = {}, {}
    for name, cfg in (("A", Cfg("A")), ("B-WF", Cfg("B"))):
        ev = evaluate(close, value, real, fx, cfg)
        base[name] = ev
        s, b = ev["strat"], ev["bench"]
        lines.append(f"\n=== Strategy {name} vs EW benchmark (same proxy universe, same costs)")
        for tag in ("IS", "OOS"):
            for cur in ("EGP", "USD"):
                ms, mb = ev[(tag, cur)]
                lines.append(f"{tag:3s} {cur}  {name:4s} {_fmt(ms)} | EW {_fmt(mb)}")
            lo, hi = IS if tag == "IS" else OOS
            ts, tb = trade_stats(s.trades, lo, hi), trade_stats(b.trades, lo, hi)
            lines.append(f"{tag:3s}      trades {ts['trades']} win {ts['win']:.1%} PF {ts['pf']:.2f} | cost drag "
                         f"{cost_drag(s.halves, lo, hi):.2%}/yr (EW {cost_drag(b.halves, lo, hi):.2%}/yr, {tb['trades']} trades)")
        ma, mb_, t, p, n = paired_t(s, b, IS[0], OOS[1])
        lines.append(f"paired t (semi-annual, IS+OOS, n={n}): mean {name} {ma:+.2%} vs EW {mb_:+.2%}, t {t:.2f}, one-sided p {p:.3f}")
        part = (s.value.loc["2026-07-01":].iloc[-1] / s.value.loc[:"2026-06-30"].iloc[-1] - 1,
                b.value.loc["2026-07-01":].iloc[-1] / b.value.loc[:"2026-06-30"].iloc[-1] - 1)
        lines.append(f"2026-H2 to date (not judged): {name} {part[0]:+.1%} vs EW {part[1]:+.1%}")
        if name == "B-WF":
            lines.append("N chosen per interval: " + " ".join(str(int(x)) for x in s.halves["n"]))
        verdict[name] = {"oos_egp": ev[("OOS", "EGP")], "oos_usd": ev[("OOS", "USD")], "is_egp": ev[("IS", "EGP")],
                         "is_usd": ev[("IS", "USD")], "p": p}

    lines.append("\n-- B per fixed N (info only, never used to choose) --")
    for n in GRID:
        r, b = run(close, value, real, Cfg("B", n=n)), base["A"]["bench"]
        for tag, (lo, hi) in {"IS": IS, "OOS": OOS}.items():
            lines.append(f"B N={n:3d} {tag:3s} EGP {_fmt(metrics(r.value, lo, hi))} | EW CAGR {metrics(b.value, lo, hi)['cagr']:+6.1%}")

    variants = {"cost 0": dict(cost=0.0), "cost 0.15%": dict(cost=0.0015), "cost 0.50%": dict(cost=0.005),
                "same-close exec": dict(lag=0), "mixed M2": dict(mixed_keep=False), "index top60": dict(index_top=60),
                "3-month intervals": dict(months=3)}
    lines.append("\n-- sensitivity (OOS, EGP; strategy minus its own EW benchmark) --")
    for name, cfg in (("A", Cfg("A")), ("B-WF", Cfg("B"))):
        wins = 0
        for vname, kw in variants.items():
            ev = evaluate(close, value, real, fx, replace(cfg, **kw))
            (ms, mb), (is_s, is_b) = ev[("OOS", "EGP")], ev[("IS", "EGP")]
            wins += ms["cagr"] > mb["cagr"]
            lines.append(f"{name:4s} {vname:18s} OOS CAGR {ms['cagr']:+6.1%} vs EW {mb['cagr']:+6.1%} "
                         f"(diff {ms['cagr'] - mb['cagr']:+6.1%}) Sharpe {ms['sharpe']:.2f} vs {mb['sharpe']:.2f} | "
                         f"IS CAGR {is_s['cagr']:+6.1%} vs {is_b['cagr']:+6.1%}")
        verdict[name]["robust"] = wins / len(variants)

    lines.append("\n-- diagnostics (info only, not part of the verdict) --")
    ra, re_ = base["A"]["strat"], base["A"]["bench"]
    for tag, (lo, hi) in {"IS": IS, "OOS": OOS}.items():
        lines.append(f"A average exposure {tag}: {ra.exposure.loc[lo:hi].mean():.0%} of the 30 slots (rest in cash at 0%)")
    yr = lambda v: (v.groupby(v.index.year).last() / v.groupby(v.index.year).last().shift(1) - 1).dropna()
    ya, ye = yr(ra.value), yr(re_.value)
    lines.append("calendar-year EGP returns, A / EW: " + "  ".join(f"{y}: {ya[y]:+.0%}/{ye[y]:+.0%}" for y in ya.index))
    lines.append("\n== VERDICT (pre-registered rules) ==")
    lines.append("Faithful replication: INSUFFICIENT_DATA (no EGX30 index history, no point-in-time constituents)")
    for name, v in verdict.items():
        (os_, ob), (ou, oub) = v["oos_egp"], v["oos_usd"]
        (is_, ib), (iu, iub) = v["is_egp"], v["is_usd"]
        if os_["cagr"] <= ob["cagr"]:
            word = "REJECT"
        elif (os_["sharpe"] > ob["sharpe"] and ou["cagr"] > oub["cagr"] and ou["sharpe"] > oub["sharpe"]
              and is_["cagr"] > ib["cagr"] and is_["sharpe"] > ib["sharpe"] and iu["cagr"] > iub["cagr"]
              and iu["sharpe"] > iub["sharpe"] and v["p"] < 0.05 and v["robust"] >= 0.8):
            word = "PASS"
        else:
            word = "WEAK"
        lines.append(f"Proxy {name}: {word}  (OOS CAGR {os_['cagr']:+.1%} vs EW {ob['cagr']:+.1%}; p {v['p']:.3f}; "
                     f"variants beating EW OOS {v['robust']:.0%})")
    text = "\n".join(lines)
    print(text)
    (HERE / "docs" / "research" / "N1_result.txt").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(download() or 0 if "--download" in sys.argv else main())
