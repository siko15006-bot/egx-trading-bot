"""نظام إشارات موحّد: اشتري الآن / انتظر / بيع + ملخص المحفظة + تنبيهات تيليجرام.

كل إشارة مبنية على أعمدة DataFrame من egx_4_mirrors_v3 (بدون تعديله) ومعاها سبب مكتوب:
    اشتري الآن : screener ناجح + evaluate_4_mirrors = BUY (4/4) + إغلاق اليوم فوق أعلى High في الـ10 جلسات السابقة
                 (ولم يكن فوقه أمس) → الدخول/الوقف/الهدف/الأسهم من build_trade_plan.
    انتظر      : 4/4 مرايا لكن الإغلاق لسه تحت مستوى التنشيط (أعلى High في الـ10 جلسات السابقة).
    بيع        : لكل سهم في portfolio.csv — Close ≤ الوقف، أو High ≥ الهدف، أو Close < EMA_50.
    تنبيهات    : قرب الوقف (≤ 1×ATR)، قرب الهدف (≤ 1×ATR)، إغلاق تحت EMA_20، وبيانات قديمة.
تنبيه: اختبارات decision_report.md انتهت بـ ABANDON (ثقة MED) — الإشارات للمراجعة اليدوية فقط، مش أوامر تنفيذ.

CLI:  python signal_engine.py [data_folder] [--portfolio portfolio.csv] [--notify]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

import egx_4_mirrors_v3 as eng
from data_health import DataHealthError, require_daily_data, assess_daily_data, health_message, expected_session, CAIRO
from egx_lists import UNIVERSE, filter_universe

HERE = Path(__file__).resolve().parent
PORTFOLIO_PATH = HERE / "portfolio.csv"
PORTFOLIO_COLUMNS = ["ticker", "shares", "entry_price", "entry_date", "stop_loss", "target", "notes"]
ACTIVATION_LOOKBACK = 10
DEFAULT_STOP_PCT = 0.15     # لو الوقف فاضي في المحفظة: −15% من الدخول (قاعدة سيناريو D)
STALE_DAYS = 4              # آخر شمعة أقدم من كده (أيام تقويمية) → تنبيه بيانات قديمة
MIRRORS_AR = {"Trend": "الاتجاه", "Momentum": "الزخم", "Volume": "الحجم", "Volatility": "التذبذب"}


@dataclass(frozen=True)
class Signals:
    buy: pd.DataFrame
    watch: pd.DataFrame
    sell: pd.DataFrame
    holdings: pd.DataFrame
    alerts: list[str]
    as_of: str
    data_health: dict[str, Any] = field(default_factory=dict)


def _day(ts: pd.Timestamp) -> str:
    return ts.tz_convert("Africa/Cairo").strftime("%Y-%m-%d") if ts.tzinfo else ts.strftime("%Y-%m-%d")


def classify(ticker: str, data: pd.DataFrame, evaluation: dict[str, Any], screen_ok: bool,
             signal_cfg: eng.SignalConfig, risk_cfg: eng.RiskConfig) -> Optional[tuple[str, dict[str, Any]]]:
    """يرجع ("BUY"|"WATCH", صف) أو None. data = مخرجات calculate_indicators، evaluation = evaluate_4_mirrors على نفس data."""
    if not screen_ok or evaluation.get("signal") != "BUY" or len(data) < ACTIVATION_LOOKBACK + 2:
        return None
    last, prev = data.iloc[-1], data.iloc[-2]
    activation = float(data["High"].iloc[-ACTIVATION_LOOKBACK - 1:-1].max())        # أعلى High في الـ10 جلسات قبل اليوم
    activation_prev = float(data["High"].iloc[-ACTIVATION_LOOKBACK - 2:-2].max())   # نفس المستوى كما كان أمس
    close = float(last["Close"])
    vol_ratio = float(last["Volume"] / last["Volume_SMA20"])
    mirrors = "، ".join(MIRRORS_AR[k] for k, v in evaluation["mirrors"].items() if v)
    if close > activation and float(prev["Close"]) <= activation_prev:
        plan = eng.build_trade_plan(ticker, data, signal_cfg, risk_cfg)
        if plan is None:
            return None
        return "BUY", {
            "Ticker": ticker, "Entry": round(plan.entry, 3), "SL": round(plan.stop_loss, 3), "TP": round(plan.take_profit, 3),
            "Shares": plan.shares, "R:R (صافي)": round(plan.rr_net, 2),
            "السبب": (f"إغلاق {close:,.2f} اخترق أعلى قمة 10 جلسات ({activation:,.2f}) اليوم لأول مرة؛ 4/4 مرايا ({mirrors})؛ "
                      f"الحجم {vol_ratio:.1f}× متوسط 20؛ الوقف = الدخول − {risk_cfg.atr_sl_mult}×ATR ({plan.atr:,.2f})"),
        }
    if close <= activation:
        return "WATCH", {
            "Ticker": ticker, "مستوى التنشيط": round(activation, 3), "الإغلاق": round(close, 3),
            "المسافة %": round((activation - close) / close * 100, 2),
            "السبب": f"4/4 مرايا ({mirrors}) لكن الإغلاق لسه تحت أعلى قمة 10 جلسات — الشراء عند إغلاق فوق {activation:,.2f}",
        }
    return None   # فوق التنشيط من قبل النهارده: الاختراق فات، مش إشارة جديدة


def scan(data_map: dict[str, pd.DataFrame], signal_cfg: eng.SignalConfig, risk_cfg: eng.RiskConfig,
         screen_cfg: Optional[eng.ScreenConfig] = None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    screen_cfg = screen_cfg or eng.ScreenConfig()
    buy, watch, indicators = [], [], {}
    for ticker, df in sorted(data_map.items()):
        data = eng.calculate_indicators(df)
        indicators[ticker] = data
        ok, _ = eng.passes_screener(data, screen_cfg)
        result = classify(ticker, data, eng.evaluate_4_mirrors(data, signal_cfg), ok, signal_cfg, risk_cfg)
        if result:
            (buy if result[0] == "BUY" else watch).append(result[1])
    return pd.DataFrame(buy), pd.DataFrame(watch).sort_values("المسافة %") if watch else pd.DataFrame(), indicators


def load_portfolio(path: Path = PORTFOLIO_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    frame = pd.read_csv(path, dtype={"ticker": str, "notes": str, "entry_date": str})
    frame["ticker"] = frame["ticker"].str.strip().str.upper()
    for col in ("shares", "entry_price", "stop_loss", "target"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna(subset=["ticker", "shares", "entry_price"])[PORTFOLIO_COLUMNS]


def save_portfolio(frame: pd.DataFrame, path: Path = PORTFOLIO_PATH) -> None:
    tmp = path.with_suffix(".tmp")
    frame.reindex(columns=PORTFOLIO_COLUMNS).to_csv(tmp, index=False, encoding="utf-8")
    tmp.replace(path)   # كتابة ذرّية: الملف القديم ما يتمسحش لو الكتابة فشلت


def review_portfolio(portfolio: pd.DataFrame, indicators: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """بيع/احتفظ لكل مركز + تنبيهات. الأسعار من آخر شمعة في البيانات المحمّلة."""
    sell, rows, alerts = [], [], []
    now = pd.Timestamp.now(tz="UTC")
    for _, pos in portfolio.iterrows():
        t = pos["ticker"]
        data = indicators.get(t)
        if data is None or data.empty:
            alerts.append(f"⚠️ {t}: مفيش بيانات محمّلة للسهم ده — مش قادر أقيّم المركز")
            continue
        last = data.iloc[-1]
        close, high, atr = float(last["Close"]), float(last["High"]), float(last["ATR"])
        entry, shares = float(pos["entry_price"]), float(pos["shares"])
        stop_given = pd.notna(pos["stop_loss"])
        stop = float(pos["stop_loss"]) if stop_given else entry * (1 - DEFAULT_STOP_PCT)
        target = float(pos["target"]) if pd.notna(pos["target"]) else float("nan")
        pnl = (close - entry) * shares
        rows.append({"Ticker": t, "Shares": int(shares), "Entry": entry, "Close": close, "SL": round(stop, 3),
                     "TP": target, "PnL": round(pnl, 2), "PnL %": round((close / entry - 1) * 100, 2), "As of": _day(data.index[-1])})
        stop_note = "" if stop_given else f" (وقف افتراضي −{DEFAULT_STOP_PCT:.0%} من الدخول)"
        if close <= stop:
            sell.append({"Ticker": t, "السبب": f"الإغلاق {close:,.2f} ≤ وقف الخسارة {stop:,.2f}{stop_note}", "السعر الحالي": close,
                         "التوصية": "بيع — الوقف اتكسر"})
        elif target == target and high >= target:
            sell.append({"Ticker": t, "السبب": f"أعلى سعر اليوم {high:,.2f} ≥ الهدف {target:,.2f}", "السعر الحالي": close,
                         "التوصية": "بيع / جني ربح — الهدف اتحقق"})
        elif close < float(last["EMA_50"]):
            sell.append({"Ticker": t, "السبب": f"الإغلاق {close:,.2f} تحت EMA50 ({float(last['EMA_50']):,.2f}) — قاعدة خروج سيناريو D",
                         "السعر الحالي": close, "التوصية": "بيع — الاتجاه المتوسط انكسر"})
        else:
            if close - stop <= atr:
                alerts.append(f"🟠 {t}: قريب من الوقف — الإغلاق {close:,.2f} على بُعد {close - stop:,.2f} (≤ 1×ATR {atr:,.2f}) من {stop:,.2f}{stop_note}")
            if target == target and target - close <= atr:
                alerts.append(f"🎯 {t}: قريب من الهدف — {target - close:,.2f} (≤ 1×ATR) من {target:,.2f}")
            if close < float(last["EMA_20"]):
                alerts.append(f"🟡 {t}: إغلاق تحت EMA20 ({float(last['EMA_20']):,.2f}) — ضعف قصير المدى، راقب")
        if (now - data.index[-1]).days > STALE_DAYS:
            alerts.append(f"⏳ {t}: آخر شمعة {_day(data.index[-1])} — البيانات قديمة، حدّثها قبل أي قرار")
    return pd.DataFrame(sell), pd.DataFrame(rows), alerts


def build_signals(data_map: dict[str, pd.DataFrame], signal_cfg: eng.SignalConfig, risk_cfg: eng.RiskConfig,
                  portfolio: Optional[pd.DataFrame] = None, screen_cfg: Optional[eng.ScreenConfig] = None) -> Signals:
    buy, watch, indicators = scan(data_map, signal_cfg, risk_cfg, screen_cfg)
    sell, holdings, alerts = review_portfolio(load_portfolio() if portfolio is None else portfolio, indicators)
    as_of = max((_day(d.index[-1]) for d in indicators.values()), default="—")
    _, health = assess_daily_data(data_map)
    return Signals(buy, watch, sell, holdings, alerts, as_of, health)


def telegram_message(sig: Signals) -> Optional[str]:
    """رسالة HTML واحدة بكل الإشارات؛ None لو مفيش حاجة تستاهل تنبيه (مفيش شراء ولا بيع ولا تنبيهات)."""
    if sig.data_health and sig.data_health.get("status") != "DATA_OK":
        return f"EGX bot health - {datetime.now(CAIRO):%Y-%m-%d}\n{health_message(sig.data_health)}"
    if sig.buy.empty and sig.watch.empty and sig.sell.empty and not sig.alerts:
        return None
    e = lambda v: html.escape(str(v))  # noqa: E731
    lines = [f"🎯 <b>إشارات EGX — {e(sig.as_of)}</b>"]
    for _, r in sig.buy.iterrows():
        lines.append(f"🟢 <b>اشتري {e(r['Ticker'])}</b> دخول {r['Entry']:,.2f} | SL {r['SL']:,.2f} | TP {r['TP']:,.2f} | {r['Shares']} سهم | R:R {r['R:R (صافي)']}\n   {e(r['السبب'])}")
    for _, r in sig.sell.iterrows():
        lines.append(f"🔴 <b>{e(r['التوصية'])}: {e(r['Ticker'])}</b> @ {r['السعر الحالي']:,.2f}\n   {e(r['السبب'])}")
    for _, r in sig.watch.head(10).iterrows():
        lines.append(f"WATCH {e(r['Ticker'])}: {e(r['السبب'])}")
    lines += [e(a) for a in sig.alerts]
    lines.append("⚠️ للمراجعة اليدوية فقط — ليست أمر تنفيذ")
    return "\n".join(lines)


def notify(sig: Signals, sent_log: Optional[Path] = None) -> dict[str, Any]:
    """يرسل مرة واحدة لكل محتوى في اليوم (تكرار نفس الرسالة يتخطّى). بدون توكن → DRY-RUN من telegram_notifier."""
    from telegram_notifier import send_telegram
    message = telegram_message(sig)
    if message is None:
        return {"sent": False, "reason": "no signals"}
    if not sig.data_health and sig.as_of != expected_session().isoformat():
        return {"sent": False, "reason": "stale or unverified session", "as_of": sig.as_of}
    sent_log = sent_log or HERE / "logs" / f"signals_sent_{datetime.now(CAIRO):%Y%m%d}.json"
    sent = json.loads(sent_log.read_text(encoding="utf-8")) if sent_log.exists() else []
    key = hashlib.sha256(message.encode("utf-8")).hexdigest()   # hash() بيتغير بين العمليات
    if key in sent:
        return {"sent": False, "reason": "already sent today"}
    result = send_telegram(message)
    if result.get("dry_run") or not result.get("ok"):
        return {"sent": False, "dry_run": bool(result.get("dry_run")), "reason": "delivery not confirmed"}
    sent_log.parent.mkdir(parents=True, exist_ok=True)
    sent_log.write_text(json.dumps(sent + [key]), encoding="utf-8")
    return {"sent": True, "dry_run": bool(result.get("dry_run")), "chars": len(message)}


def main() -> int:
    parser = argparse.ArgumentParser(description="EGX unified signals (buy / watch / sell)")
    parser.add_argument("data", nargs="?", default=str(HERE / "data"))
    parser.add_argument("--portfolio", default=str(PORTFOLIO_PATH))
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    try:
        data = require_daily_data(filter_universe(eng.load_data_map(Path(args.data))), expected_tickers=UNIVERSE)
    except DataHealthError as exc:
        print(str(exc))
        return 2
    sig = build_signals(data, eng.SignalConfig(), eng.RiskConfig(), load_portfolio(Path(args.portfolio)))
    print(f"As of {sig.as_of}")
    for title, frame in (("🟢 اشتري الآن", sig.buy), ("⏸️ انتظر", sig.watch), ("🔴 بيع", sig.sell), ("📊 المحفظة", sig.holdings)):
        print(f"\n{title}: {len(frame)}")
        if not frame.empty:
            print(frame.to_string(index=False))
    print("\nتنبيهات:", *(sig.alerts or ["لا يوجد"]), sep="\n  ")
    if args.notify:
        print("\nTelegram:", notify(sig))
    return 0


if __name__ == "__main__":
    sys.exit(main())
