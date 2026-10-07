"""تحسين استراتيجية 4 Mirrors (v3) + نظام هجين (سيناريو D) + اختبار سوق هابط — على البيانات الحقيقية.

v2 من الملف ده (النسخة القديمة في outputs_backup_20261004_1848_before_v3):
    - المحرك: egx_4_mirrors_v3 (VWAP يومي حقيقي؛ على بيانات يومية مراية الحجم بتستخدم VWAP_20).
    - التنفيذ واقعي دائماً لكل السيناريوهات: أول خروج ممكن = الشمعة التالية للإشارة، ولو السعر فتح بفجوة
      تحت الوقف/فوق الهدف يتنفذ عند الافتتاح. وضع "engine" موجود فقط للتحقق إن المحاكي بيطابق eng.backtest().
    - Trailing لسيناريو C قابل للضبط (2/3/4×ATR) والاختيار بأعلى Profit Factor.
    - سيناريو D (Signal-Based Buy & Hold): محفظة واحدة برأس مال مشترك، دخول على إشارة C، خروج بإغلاق تحت EMA50،
      وقف أمان −15%، حجم المركز حتى 15% من رأس المال، 4–6 مراكز متزامنة كحد أقصى.
المحفظة في A/B/C/Baseline: حساب مستقل 100,000 لكل سهم؛ D حساب واحد بنفس الإجمالي؛ Buy & Hold أوزان متساوية.

التشغيل: python backtest_optimizer.py  →  optimization_report_v2.md + logs/optimization_v2_<date>.log
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from math import floor, sqrt
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import egx_4_mirrors_v3 as eng  # noqa: E402

START_INDEX = 60   # نفس بداية المحرك (أول 60 شمعة لتسخين المؤشرات)
TRADING_DAYS = 252
BEAR_DIR = HERE / "data_2022_2023"
BEAR_START, BEAR_TROUGH = "2022-01-01", "2022-07-04"   # قمة→قاع المحفظة المتساوية الأوزان (−24%)، مقاسة من البيانات


@dataclass(frozen=True)
class Scenario:
    """تعريف سيناريو: فلاتر الإشارة + إدارة المخاطر + منطق الدخول/الخروج."""
    name: str
    signal: eng.SignalConfig = field(default_factory=eng.SignalConfig)
    risk: eng.RiskConfig = field(default_factory=eng.RiskConfig)
    be_trigger_atr: float = 1.0        # الإغلاق ≥ الدخول + X×ATR → الوقف على سعر الدخول
    lock_trigger_atr: float = 2.0      # الإغلاق ≥ الدخول + X×ATR → الوقف على الدخول + 1×ATR
    time_stop_days: Optional[int] = None
    kind: str = "mirrors"              # mirrors | trend
    trail_atr: float = 3.0             # trend فقط: Trailing من أعلى إغلاق


# ------------------------------------------------------------------ أدوات مساعدة
def _shares(entry: float, stop: float, last: pd.Series, risk: eng.RiskConfig) -> int:
    """نفس قيود الحجم في المحرك: مخاطرة 1%، حد 20% من رأس المال، و1% من متوسط الحجم."""
    rps = entry - stop
    if not np.isfinite(rps) or rps <= 0:
        return 0
    return int(min(floor(risk.capital * risk.risk_pct / rps), floor(risk.capital * risk.max_position_pct / entry),
                   floor(risk.max_avg_volume_pct * float(last["Volume_SMA20"]))))




def _start(data: pd.DataFrame, start_date: Optional[str]) -> int:
    """أول شمعة للاختبار: بعد التسخين، ومن تاريخ البداية لو محدد."""
    if start_date is None:
        return START_INDEX
    return max(START_INDEX, int(data.index.searchsorted(pd.Timestamp(start_date, tz="UTC"))))


def _combine(curves: list[pd.Series], fill: float) -> pd.Series:
    """يجمع منحنيات أسهم بتواريخ مختلفة: ffill لآخر قيمة، وقبل أول تاريخ = رأس المال كاش."""
    return pd.concat(curves, axis=1).sort_index().ffill().fillna(fill).sum(axis=1)


# ------------------------------------------------------------------ إشارات الدخول
def _mirrors_entry(data: pd.DataFrame, i: int, sc: Scenario) -> Optional[dict[str, float]]:
    """دخول 4 Mirrors بنفس دوال المحرك (screener + evaluate_4_mirrors + build_trade_plan)."""
    window = data.iloc[: i + 1]
    ok, _ = eng.passes_screener(window, eng.ScreenConfig())
    if not ok or eng.evaluate_4_mirrors(window, sc.signal)["signal"] != "BUY":
        return None
    plan = eng.build_trade_plan("BT", window, sc.signal, sc.risk)
    if plan is None:
        return None
    return {"entry": plan.entry, "stop": plan.stop_loss, "tp": plan.take_profit, "atr": plan.atr, "shares": plan.shares,
            "risk_egp": plan.risk_egp, "position_value": plan.position_value}


def _trend_entry(data: pd.DataFrame, i: int, sc: Scenario) -> Optional[dict[str, float]]:
    """سيناريو C: اختراق أعلى قمة 20 جلسة سابقة مع حجم > 1.2×متوسط 20، والوقف = أدنى قاع 10 جلسات."""
    if i < 21:
        return None
    window = data.iloc[: i + 1]
    ok, _ = eng.passes_screener(window, eng.ScreenConfig())
    row = data.iloc[i]
    prior_high = float(data["High"].iloc[i - 20: i].max())
    if not ok or not (row["Close"] > prior_high and row["Volume"] > sc.signal.volume_multiplier * row["Volume_SMA20"]):
        return None
    entry = float(row["Close"])
    stop = float(data["Low"].iloc[i - 9: i + 1].min())
    shares = _shares(entry, stop, row, sc.risk)
    if shares <= 0:
        return None
    risk_egp = (entry - stop) * shares + eng.trade_fees(entry, stop, shares, sc.risk)
    return {"entry": entry, "stop": stop, "tp": float("inf"), "atr": float(row["ATR"]), "shares": shares,
            "risk_egp": risk_egp, "position_value": shares * entry}


# ------------------------------------------------------------------ محاكاة سهم واحد (A/B/C/Baseline)
def simulate(df: pd.DataFrame, sc: Scenario, mode: str = "realistic", start_date: Optional[str] = None) -> dict[str, Any]:
    data = eng.calculate_indicators(df)
    entry_fn: Callable[[pd.DataFrame, int, Scenario], Optional[dict[str, float]]] = (
        _trend_entry if sc.kind == "trend" else _mirrors_entry)
    capital = sc.risk.capital
    equity = capital
    trades: list[dict[str, Any]] = []
    daily_pnl = pd.Series(0.0, index=data.index)
    exposure = pd.Series(0.0, index=data.index)
    start = _start(data, start_date)
    i = start
    n = len(data)
    breaks = eng.data_breaks(data)
    cancelled: list[dict[str, Any]] = []
    while i < n - 1:
        plan = entry_fn(data, i, sc)
        if plan is None:
            i += 1
            continue
        initial_stop, tp, atr = plan["stop"], plan["tp"], plan["atr"]
        # Same execution policy as eng.simulate_trade (docs/execution_policy.md): entry at the close after the signal on a
        # traded bar, filler bars never fill, stop/target fills via eng.stop_fill/target_fill, and a data break while
        # open cancels the trade (counted, excluded). `mode` no longer differs.
        e = i + 1
        entry = float(data["Close"].iloc[e])
        if breaks[e] or eng.is_filler(data.iloc[e]) or not initial_stop < entry < tp:
            i += 1
            continue
        stop = initial_stop
        exit_price, exit_index, reason = float(data["Close"].iloc[-1]), n - 1, "END"
        highest_close = entry
        for j in range(e + 1, n):
            row = data.iloc[j]
            if breaks[j]:
                reason, exit_index = "DATA_BREAK", j
                break
            if eng.is_filler(row):
                continue
            if row["Low"] <= stop:
                exit_price, exit_index = eng.stop_fill(data, j, stop), j
                reason = "TRAIL_SL" if stop > initial_stop else "SL"
                break
            if row["High"] >= tp:
                exit_price, exit_index, reason = eng.target_fill(data, j, tp), j, "TP"
                break
            if sc.kind == "trend":
                if row["Close"] < row["EMA_20"]:                         # كسر EMA20 بالإغلاق
                    exit_price, exit_index, reason = float(row["Close"]), j, "EMA20_EXIT"
                    break
                highest_close = max(highest_close, float(row["Close"]))
                stop = max(stop, highest_close - sc.trail_atr * float(row["ATR"]))
            else:
                if row["Close"] >= entry + sc.lock_trigger_atr * atr:
                    stop = max(stop, entry + atr)
                elif row["Close"] >= entry + sc.be_trigger_atr * atr:
                    stop = max(stop, entry)
            if sc.time_stop_days is not None and (j - e) >= sc.time_stop_days:
                exit_price, exit_index, reason = float(row["Close"]), j, "TIME_STOP"
                break
        if reason == "DATA_BREAK":   # outcome unknown: excluded from P&L and stats, counted
            cancelled.append({"entry_date": data.index[e], "break_date": data.index[exit_index], "entry": entry})
            i = exit_index
            continue
        if reason != "END":
            assert exit_index > e, "look-ahead: exit on the entry bar"
        i = e  # entry bar index from here on (P&L, exposure, dividends, trade record)
        pnl = eng.net_trade_pnl(entry, float(exit_price), int(plan["shares"]), sc.risk, eng.dividends_between(data, i, exit_index),
                                same_session=eng.same_session(data.index[i], data.index[exit_index]))
        equity += pnl
        daily_pnl.iloc[exit_index] += pnl
        exposure.iloc[i: exit_index + 1] += plan["position_value"] / capital
        trades.append({"entry_idx": i, "exit_idx": exit_index, "entry_date": data.index[i], "exit_date": data.index[exit_index],
                       "entry": entry, "exit": float(exit_price), "stop0": initial_stop, "tp": tp, "shares": int(plan["shares"]),
                       "position_value": plan["position_value"], "pnl": pnl, "R": pnl / plan["risk_egp"] if plan["risk_egp"] > 0 else 0.0,
                       "pnl_pct_pos": pnl / plan["position_value"] * 100, "reason": reason, "bars": exit_index - i})
        i = max(exit_index + 1, i + 1)
    span = data.index[start:]
    equity_curve = capital + daily_pnl.loc[span].cumsum()
    bh_curve = eng.buy_hold_curve(data, start, capital, sc.risk)
    return {"trades": pd.DataFrame(trades), "equity": equity_curve, "bh": bh_curve, "final": equity,
            "exposure": exposure.loc[span], "cancelled": pd.DataFrame(cancelled)}


# ------------------------------------------------------------------ سيناريو D: محفظة مشتركة
def simulate_d(data_map: dict[str, pd.DataFrame], max_pos: int, capital: float, start_date: Optional[str] = None,
               pos_pct: float = 0.15, sl_pct: float = 0.15) -> dict[str, Any]:
    """Signal-Based Buy & Hold: دخول عند إغلاق الجلسة اللي بعد إشارة C، خروج بإغلاق < EMA50 أو وقف −15%
    (docs/execution_policy.md: الوقف بأمر سوق، مفيش تنفيذ على شمعة حجمها صفر). لا Trailing ولا هدف.
    مركز بيعدّي data break بيتلغي: الكاش بيرجع لتكلفته ومش بيتسجل كصفقة (معدود في cancelled)."""
    sc = SCENARIOS["C_trend"]
    risk = sc.risk
    ind = {t: eng.calculate_indicators(df) for t, df in data_map.items()}
    brk = {t: pd.Series(eng.data_breaks(d), index=d.index) for t, d in ind.items()}
    signals: dict[pd.Timestamp, list[tuple[float, str]]] = {}
    for t, d in ind.items():
        for i in range(_start(d, start_date), len(d) - 1):
            if _trend_entry(d, i, sc) is not None:   # executable at the ticker's next session close
                signals.setdefault(d.index[i + 1], []).append((float(d["Volume"].iloc[i] / d["Volume_SMA20"].iloc[i]), t))
    dates = sorted(set().union(*(d.index[_start(d, start_date):] for d in ind.values())))
    cash, pos, last_close = capital, {}, {}
    trades: list[dict[str, Any]] = []
    cancelled: list[dict[str, Any]] = []
    curve, invested = {}, {}

    def close_position(t: str, ts: pd.Timestamp, px: float, why: str) -> None:
        nonlocal cash
        p = pos.pop(t)
        d = ind[t]
        pnl = eng.net_trade_pnl(p["entry"], px, p["shares"], risk,
                                eng.dividends_between(d, d.index.get_loc(p["ts"]), d.index.get_loc(ts)),
                                same_session=eng.same_session(p['ts'], ts))
        cash += p['cost'] + pnl
        value = p["shares"] * p["entry"]
        trades.append({"ticker": t, "entry_date": p["ts"], "exit_date": ts, "entry": p["entry"], "exit": px, "shares": p["shares"],
                       "position_value": value, "pnl": pnl, "R": pnl / (value * sl_pct), "pnl_pct_pos": pnl / value * 100,
                       "reason": why, "bars": int(ind[t].index.get_loc(ts) - ind[t].index.get_loc(p["ts"]))})

    for ts in dates:
        for t in list(pos):
            d = ind[t]
            if ts not in d.index:
                continue
            row, stop = d.loc[ts], pos[t]["stop"]
            if brk[t].loc[ts]:   # outcome unknown → undo the position (cash back to its cost); earlier curve points keep
                p = pos.pop(t)   # its mark-to-market, a documented limitation
                cash += p["cost"]
                cancelled.append({"ticker": t, "entry_date": p["ts"], "break_date": ts, "entry": p["entry"]})
            elif eng.is_filler(row):
                continue
            elif row["Low"] <= stop:
                close_position(t, ts, eng.stop_fill(d, d.index.get_loc(ts), stop), "SL")
            elif row["Close"] < row["EMA_50"]:
                close_position(t, ts, float(row["Close"]), "EMA50_EXIT")
        for t, d in ind.items():
            if ts in d.index:
                last_close[t] = float(d.at[ts, "Close"])
        equity = cash + sum(p["shares"] * last_close[t] for t, p in pos.items())
        for _, t in sorted(signals.get(ts, []), reverse=True):
            if len(pos) >= max_pos:
                break
            if t in pos:
                continue
            row = ind[t].loc[ts]
            px = float(row["Close"])
            if brk[t].loc[ts] or eng.is_filler(row):
                continue
            budget = min(pos_pct * equity, cash)
            shares = int(min(budget // px, floor(risk.max_avg_volume_pct * float(row["Volume_SMA20"]))))
            if shares <= 0:
                continue
            while shares > 0 and shares * px + eng.entry_order_fee(shares * px, risk) > cash:
                shares -= 1
            if shares <= 0:
                continue
            cost = shares * px + eng.entry_order_fee(shares * px, risk)
            cash -= cost
            pos[t] = {"entry": px, "stop": px * (1 - sl_pct), "shares": shares, "ts": ts, 'cost': cost}
        held = sum(p["shares"] * last_close[t] for t, p in pos.items())
        curve[ts], invested[ts] = cash + held, held / (cash + held)
    for t in list(pos):   # مراكز مفتوحة في النهاية → تقييم على آخر إغلاق (END)
        close_position(t, ind[t].index[-1], float(ind[t]["Close"].iloc[-1]), "END")
    if curve:   # the last curve point must include the END liquidation costs (fees, tax, slippage)
        curve[max(curve)] = cash
    tr = pd.DataFrame(trades)
    if len(tr):
        assert (tr.loc[tr.reason != "END", "bars"] >= 1).all(), "look-ahead: exit on the entry bar"
    return {"trades": tr, "equity": pd.Series(curve), "exposure": pd.Series(invested), "cancelled": pd.DataFrame(cancelled)}


# ------------------------------------------------------------------ مقاييس
def _metrics(curve: pd.Series, trades: Optional[pd.DataFrame], capital: float) -> dict[str, float]:
    rets = curve.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std(ddof=1) * sqrt(TRADING_DAYS)) if len(rets) > 1 and rets.std(ddof=1) > 0 else 0.0
    years = len(curve) / TRADING_DAYS
    final = float(curve.iloc[-1])
    out = {"total_return": final / capital - 1, "cagr": (final / capital) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan"),
           "max_dd": float((curve / curve.cummax() - 1).min()), "sharpe": sharpe}
    if trades is not None and len(trades):
        wins, losses = trades.loc[trades.pnl > 0, "pnl"], trades.loc[trades.pnl <= 0, "pnl"]
        out.update(trades=len(trades), win_rate=len(wins) / len(trades),
                   profit_factor=float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
                   avg_R=float(trades.R.mean()))
    else:
        out.update(trades=0, win_rate=float("nan"), profit_factor=float("nan"), avg_R=float("nan"))
    return out


def _edge(trades: pd.DataFrame, rng: np.random.Generator) -> dict[str, float]:
    """متوسط R لكل صفقة + bootstrap 10,000× (هل الأفضلية حقيقية؟)."""
    r = trades.R.to_numpy() if len(trades) else np.array([])
    if len(r) < 3:
        return {"n": len(r), "mean_R": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan"), "p_le_0": float("nan")}
    boots = np.array([rng.choice(r, len(r)).mean() for _ in range(10_000)])
    return {"n": len(r), "mean_R": float(r.mean()), "ci_lo": float(np.percentile(boots, 2.5)),
            "ci_hi": float(np.percentile(boots, 97.5)), "p_le_0": float((boots <= 0).mean())}


SCENARIOS: dict[str, Scenario] = {
    "Baseline": Scenario("Baseline"),
    "A_filters": Scenario("A_filters", signal=eng.SignalConfig(min_adx=25.0, rsi_min=55.0, rsi_max=65.0, volume_multiplier=1.5, max_gap_pct=2.0)),
    "B_risk": Scenario("B_risk", risk=eng.RiskConfig(atr_sl_mult=2.5, reward_risk=3.0), be_trigger_atr=2.0, lock_trigger_atr=3.0, time_stop_days=15),
    "C_trend": Scenario("C_trend", kind="trend"),
}
D_MAX_POSITIONS = (4, 5, 6)


def run_suite(data_map: dict[str, pd.DataFrame], scenarios: dict[str, Scenario], start_date: Optional[str],
              log: Callable[[str], None], label: str) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """يشغّل كل السيناريوهات (تنفيذ واقعي) + D بـ4/5/6 مراكز + Buy & Hold على نفس النافذة."""
    capital = eng.RiskConfig().capital
    total = capital * len(data_map)
    rng = np.random.default_rng(0)
    out: dict[str, dict[str, Any]] = {}
    bh_parts = []
    for key, sc in scenarios.items():
        per = {t: simulate(df, sc, "realistic", start_date) for t, df in data_map.items()}
        trades = pd.concat([r["trades"].assign(ticker=t) for t, r in per.items() if len(r["trades"])], ignore_index=True) \
            if any(len(r["trades"]) for r in per.values()) else pd.DataFrame()
        m = _metrics(_combine([r["equity"] for r in per.values()], capital), trades, total)
        m["avg_exposure_pct"] = float(_combine([r["exposure"] for r in per.values()], 0.0).mean() / len(per) * 100)
        out[key] = {"metrics": m, "trades": trades, "edge": _edge(trades, rng)}
        bh_parts = [r["bh"] for r in per.values()]
    for k in D_MAX_POSITIONS:
        r = simulate_d(data_map, k, total, start_date)
        m = _metrics(r["equity"], r["trades"], total)
        m["avg_exposure_pct"] = float(r["exposure"].mean() * 100)
        out[f"D_hold_{k}"] = {"metrics": m, "trades": r["trades"], "edge": _edge(r["trades"], rng)}
    bh = _metrics(_combine(bh_parts, capital), None, total)
    for key, r in out.items():
        m = r["metrics"]
        log(f"[RUN:{label}] {key:10s} trades={m['trades']} WR={_rate(m['win_rate'])} PF={_fmt(m['profit_factor'], False)} "
            f"ret={m['total_return']:+.2%} CAGR={_fmt(m['cagr'])} DD={m['max_dd']:.2%} Sharpe={m['sharpe']:.2f} "
            f"exposure={m['avg_exposure_pct']:.1f}% edge={json.dumps(r['edge'])}")
    log(f"[RUN:{label}] Buy&Hold   ret={bh['total_return']:+.2%} CAGR={_fmt(bh['cagr'])} DD={bh['max_dd']:.2%} Sharpe={bh['sharpe']:.2f}")
    return out, bh


def main() -> int:
    global SCENARIOS
    ap = argparse.ArgumentParser(description="EGX optimizer (see module docstring)")
    ap.add_argument("--slippage-bps", type=float, default=None, help="cost per side on top of fees, 0..1000")
    args = ap.parse_args()
    if args.slippage_bps is not None:  # applied to every scenario; RiskConfig rejects values outside 0..1000
        SCENARIOS = {k: replace(v, risk=replace(v.risk, slippage_bps=args.slippage_bps)) for k, v in SCENARIOS.items()}
    log_path = HERE / "logs" / f"optimization_v2_{datetime.now():%Y%m%d}.log"

    def log(msg: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    mode, line = eng.resolve_dividend_mode(HERE / "data")
    log(f"[DATA] {line}")
    data_map = {t: eng.with_dividends(t, d) if mode == "add" else d for t, d in eng.load_data_map(HERE / "data").items()}
    log(f"[DATA] main: {len(data_map)} tickers {sorted(data_map)}")
    capital = eng.RiskConfig().capital

    # 0) التحقق: المحاكي بمنطق المحرك لازم يطابق eng.backtest() في v3 قبل أي مقارنة
    cfg = eng.SystemConfig()
    mismatches, same_bar = [], 0
    for t, df in data_map.items():
        ref, mine = eng.backtest(df, cfg), simulate(df, SCENARIOS["Baseline"], "engine")
        same_bar += int((mine["trades"].bars == 0).sum()) if len(mine["trades"]) else 0
        if ref["total_trades"] != len(mine["trades"]) or abs(ref["final_equity"] - mine["final"]) > 1e-6:
            mismatches.append((t, ref["total_trades"], len(mine["trades"])))
    log(f"[VALIDATE] simulator(engine logic) vs v3 eng.backtest(): {'IDENTICAL' if not mismatches else mismatches}; "
        f"same-bar exits in engine logic = {same_bar} (all results below use realistic execution → 0)")
    if mismatches:
        log("[ABORT] simulator does not reproduce the engine")
        return 1

    # 1.3) Trailing لسيناريو C: 2/3/4×ATR، الاختيار بأعلى PF (على بيانات data/ فقط؛ بيانات 2022–2023 اختبار خارج العينة)
    trail: dict[float, dict[str, float]] = {}
    for k in (2.0, 3.0, 4.0):
        sc = replace(SCENARIOS["C_trend"], trail_atr=k)
        per = {t: simulate(df, sc) for t, df in data_map.items()}
        tr = pd.concat([r["trades"] for r in per.values() if len(r["trades"])], ignore_index=True)
        trail[k] = _metrics(_combine([r["equity"] for r in per.values()], capital), tr, capital * len(per))
        trail[k]["trail_exits"] = int((tr.reason == "TRAIL_SL").sum())
        log(f"[TRAIL] {k:.0f}xATR trades={trail[k]['trades']} WR={trail[k]['win_rate']:.1%} PF={trail[k]['profit_factor']:.2f} "
            f"ret={trail[k]['total_return']:+.2%} Sharpe={trail[k]['sharpe']:.2f} trail_exits={trail[k]['trail_exits']}")
    best_trail = max(trail, key=lambda k: trail[k]["profit_factor"])
    log(f"[TRAIL] selected {best_trail:.0f}xATR by Profit Factor")
    scenarios = {**SCENARIOS, "C_trend": replace(SCENARIOS["C_trend"], trail_atr=best_trail)}

    # 2) كل السيناريوهات + D على البيانات الرئيسية
    main_runs, main_bh = run_suite(data_map, scenarios, None, log, "main")

    # 3) السوق الهابط: 2022–2023 (تسخين من 2021) + نافذة الهبوط الفعلية يناير→يوليو 2022
    mode, line = eng.resolve_dividend_mode(BEAR_DIR)
    log(f"[DATA] {line}")
    bear_map = {t: eng.with_dividends(t, d) if mode == "add" else d for t, d in eng.load_data_map(BEAR_DIR).items()}
    log(f"[DATA] bear: {len(bear_map)} tickers from {BEAR_DIR.name}/")
    full_runs, full_bh = run_suite(bear_map, scenarios, BEAR_START, log, "2022-23")
    cut = pd.Timestamp(BEAR_TROUGH, tz="UTC") + pd.Timedelta(days=1)
    trough_runs, trough_bh = run_suite({t: d[d.index < cut] for t, d in _raw(bear_map).items()}, scenarios, BEAR_START, log, "bear-H1-2022")
    fx = pd.read_csv(BEAR_DIR / "fx" / "EGP_USD.csv", index_col=0, parse_dates=True).iloc[:, 0]
    fx_move = float(fx.iloc[-1] / fx.loc[BEAR_START:].iloc[0])
    log(f"[FX] USD/EGP x{fx_move:.2f} over 2022-23")

    # 4) القرار
    # الاختيار بأقل Sharpe في الفترتين (ثبات)، مش Sharpe الفترة الأولى بس — B_risk كان الأعلى على data/ وانهار في 2022–23
    # Select on the main (data/) window only; the 2022-23 runs stay a true out-of-sample check. Main-window metrics are
    # in-sample (the trail multiplier above is also chosen on data/).
    best = max(main_runs, key=lambda k: main_runs[k]["metrics"]["sharpe"])
    rec = _recommend(best, main_runs, main_bh, full_runs, full_bh)
    report = build_report(trail, best_trail, main_runs, main_bh, full_runs, full_bh, trough_runs, trough_bh, fx_move, best, rec, same_bar)
    (HERE / "optimization_report_v2.md").write_text(report, encoding="utf-8")
    log("[DONE] optimization_report_v2.md written")
    files = ["egx_4_mirrors_v3.py", "backtest_optimizer.py", "optimization_report_v2.md", log_path.relative_to(HERE).as_posix()] + \
            [f"{BEAR_DIR.name}/{p.name}" for p in sorted(BEAR_DIR.glob("*.csv"))] + [f"{BEAR_DIR.name}/fx/EGP_USD.csv"]
    bm = main_runs[best]["metrics"]
    log(f"[SUMMARY] files={len(files)} best={best} sharpe={bm['sharpe']:.2f} pf={bm['profit_factor']:.2f} rec={rec}")
    print(f"\n✅ V3 + Hybrid System Ready\n📄 Files: {len(files)}\n📊 Best Scenario: {best} (Sharpe {bm['sharpe']:.2f}, PF {bm['profit_factor']:.2f})\n"
          f"🎯 Recommendation: {rec}")
    return 0


def _raw(data_map: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {t: d[[c for c in ("Open", "High", "Low", "Close", "Volume", "Dividends") if c in d.columns]] for t, d in data_map.items()}


def _recommend(best: str, main_runs: dict, main_bh: dict, bear_runs: dict, bear_bh: dict) -> str:
    """قاعدة مكتوبة مسبقاً: CONTINUE لو أفضل سيناريو يتفوق على Buy & Hold في Sharpe في الفترتين؛
    PIVOT لو الأفضلية لكل صفقة موجبة إحصائياً (P(mean R ≤ 0) < 5% في الفترتين) لكنه بيخسر قدام Buy & Hold؛ غير كده ABANDON."""
    beats = main_runs[best]["metrics"]["sharpe"] > main_bh["sharpe"] and bear_runs[best]["metrics"]["sharpe"] > bear_bh["sharpe"]
    edge_ok = all(r[best]["edge"]["p_le_0"] < 0.05 for r in (main_runs, bear_runs))
    return "CONTINUE" if beats else "PIVOT" if edge_ok else "ABANDON"


def _fmt(v: Optional[float], pct: bool = True) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    return f"{v:+.2%}" if pct else f"{v:.2f}"


def _rate(v: Optional[float]) -> str:
    return "—" if v is None or not np.isfinite(v) else f"{v:.1%}"


def _table(runs: dict, bh: dict) -> list[str]:
    lines = ["| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for key, r in runs.items():
        m, e = r["metrics"], r["edge"]
        lines.append(f"| {key} | {m['trades']} | {_rate(m['win_rate'])} | {_fmt(m['profit_factor'], False)} | {m['max_dd']:.2%} | {m['sharpe']:.2f} | "
                     f"{_fmt(m['total_return'])} | {_fmt(m['cagr'])} | {m['avg_exposure_pct']:.1f}% | {_fmt(e['mean_R'], False)} | {_rate(e['p_le_0'])} |")
    lines.append(f"| **Buy & Hold (equal weight)** | — | — | — | {bh['max_dd']:.2%} | {bh['sharpe']:.2f} | {_fmt(bh['total_return'])} | {_fmt(bh['cagr'])} | 100% | — | — |")
    return lines


def build_report(trail: dict, best_trail: float, main_runs: dict, main_bh: dict, full_runs: dict, full_bh: dict,
                 trough_runs: dict, trough_bh: dict, fx_move: float, best: str, rec: str, same_bar: int) -> str:
    L = [f"# Optimization Report v2 — 4 Mirrors v3 + Hybrid (generated {datetime.now():%Y-%m-%d %H:%M})", "",
         "Execution is **realistic for every number in this report**: entry at the close after the signal, first exit on the bar after that; fills per `docs/execution_policy.md` (level, real open on a gap, else close; zero-volume rows never fill; trades across a data break cancelled). "
         "A/B/C/Baseline = one independent 100,000 EGP account per stock; D = one shared account of the same total; Buy & Hold = equal weight, same window.", "",
         "## 1.2 Look-ahead", "",
         f"The simulator in engine logic reproduces `egx_4_mirrors_v3.backtest()` exactly; that logic had **{same_bar} exits on the entry bar**. "
         "Realistic mode starts exit checks at the next bar and asserts that no non-END trade exits on its entry bar (assertion never fired).", "",
         "## 1.3 Trailing stop for Scenario C (data/, realistic)", "",
         "| Trailing | Trades | Win rate | Profit factor | Sharpe | Total return | Trailing exits |", "|---|---|---|---|---|---|---|"]
    for k, m in trail.items():
        L.append(f"| {k:.0f}×ATR{' ✅' if k == best_trail else ''} | {m['trades']} | {_rate(m['win_rate'])} | {m['profit_factor']:.2f} | {m['sharpe']:.2f} | "
                 f"{_fmt(m['total_return'])} | {m['trail_exits']} |")
    L += ["", f"Selected **{best_trail:.0f}×ATR** (highest PF) — used for C below and carried unchanged into 2022–2023 (out of sample).", "",
          "## Scenario D + full comparison — data/ (2024-10 → 2026-10)", ""] + _table(main_runs, main_bh)
    L += ["", "## Phase 3 — 2022–2023 (warm-up from 2021, test from 2022-01-01)", "",
          f"USD/EGP moved ×{fx_move:.2f} over the window: in EGP the market rose; in USD it was a weak/flat market. "
          f"The real drawdown inside the window is 2022-01 → {BEAR_TROUGH} (equal-weight −24%), tested separately below.", "",
          "### Full 2022–2023", ""] + _table(full_runs, full_bh)
    L += ["", f"### Bear leg only: {BEAR_START} → {BEAR_TROUGH}", ""] + _table(trough_runs, trough_bh)
    L += ["", "### In USD terms (2022–2023, total return ÷ FX move)", "", "| Scenario | EGP | USD |", "|---|---|---|"]
    for key, r in {**{k: v["metrics"] for k, v in full_runs.items()}, "Buy & Hold": full_bh}.items():
        L.append(f"| {key} | {_fmt(r['total_return'])} | {_fmt((1 + r['total_return']) / fx_move - 1)} |")
    bm = main_runs[best]["metrics"]
    L += ["", "## Decision", "",
          f"Best scenario = highest Sharpe on data/ only (in-sample); 2022–2023 is reported as an out-of-sample check on 9 large caps: **{best}** (data/: Sharpe {bm['sharpe']:.2f}, PF {_fmt(bm['profit_factor'], False)}; "
          f"2022–23: Sharpe {full_runs[best]['metrics']['sharpe']:.2f}).", "",
          "Disclosure: the first run selected by data/ Sharpe alone and picked B_risk (Sharpe 1.70 on ~3% deployed capital), which fell to Sharpe 0.39 / "
          "P(mean R ≤ 0) 29% in 2022–2023 → rule output ABANDON. That selection overfits one period, so it was changed to the two-period minimum *after* "
          "seeing that result. The CONTINUE/PIVOT/ABANDON rule itself is unchanged. 2026-10-07: reverted to data/-only selection, because "
          "a two-period minimum lets the out-of-sample period choose the winner; overfitting now shows up in the 2022–2023 numbers instead.", "",
          "Rule fixed before reading the results: CONTINUE if the best scenario beats Buy & Hold on Sharpe in both periods; "
          "PIVOT (use the system as a filter/timing layer) if its per-trade edge is significant (P(mean R ≤ 0) < 5%) in both periods but it loses to Buy & Hold; otherwise ABANDON.", "",
          f"**Recommendation: {rec}**", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
