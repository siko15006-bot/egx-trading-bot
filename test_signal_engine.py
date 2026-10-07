"""اختبار نظام الإشارات الموحّد (signal_engine.py) + تبويب 9 في الداشبورد.
التشغيل: python test_signal_engine.py   (بيانات مُصنّعة في الذاكرة فقط؛ تيليجرام مستبدل بـstub فمفيش إرسال حقيقي)"""
from __future__ import annotations

import json
import sys
import tempfile
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import signal_engine as se  # noqa: E402
import telegram_notifier  # noqa: E402
from data_health import expected_session

eng = se.eng
LOG = HERE / "logs" / f"signals_test_{datetime.now():%Y%m%d}.log"
results: list[tuple[str, bool, str]] = []
SIG, RISK = eng.SignalConfig(), eng.RiskConfig()
ALL_MIRRORS = {"signal": "BUY", "mirrors": {"Trend": True, "Momentum": True, "Volume": True, "Volatility": True}}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [TEST] {'PASS' if ok else 'FAIL'} {name} {detail}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def frame(close: np.ndarray, last_volume: float = 1_500_000.0) -> pd.DataFrame:
    n = len(close)
    idx = pd.bdate_range(end=pd.offsets.BDay().rollback(pd.Timestamp.now().normalize()), periods=n).tz_localize("UTC")
    vol = np.full(n, 600_000.0)
    vol[-1] = last_volume
    return pd.DataFrame({"Open": np.r_[close[0], close[:-1]], "High": close * 1.005, "Low": close * 0.995, "Close": close, "Volume": vol}, index=idx)


def main() -> int:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"===== test_signal_engine run {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    real_eval = eng.evaluate_4_mirrors
    eng.evaluate_4_mirrors = lambda df, cfg: ALL_MIRRORS   # build_trade_plan بيعيد التقييم داخلياً → نثبّته على 4/4
    try:
        base = np.r_[np.linspace(50, 60, 100), np.full(20, 60.0)]
        # 1) اختراق اليوم لأول مرة → BUY
        breakout = eng.calculate_indicators(frame(np.r_[base, 62.0]))
        kind, row = se.classify("BRK.CA", breakout, ALL_MIRRORS, True, SIG, RISK)
        last = breakout.iloc[-1]
        check("breakout today -> BUY", kind == "BUY", json.dumps(row, ensure_ascii=False, default=str)[:220])
        check("BUY numbers come from the frame (Entry=Close, SL=Close-1.5*ATR)",
              abs(row["Entry"] - round(last["Close"], 3)) < 1e-9 and abs(row["SL"] - round(last["Close"] - 1.5 * last["ATR"], 3)) < 1e-6
              and row["TP"] > row["Entry"] > row["SL"] and row["Shares"] > 0)
        check("BUY reason cites activation level and volume", "اخترق" in row["السبب"] and "60.30" in row["السبب"]
              and f"{last['Volume'] / last['Volume_SMA20']:.1f}×" in row["السبب"])
        # 2) 4/4 تحت التنشيط → WATCH، والمسافة = (التنشيط − الإغلاق)/الإغلاق
        below = eng.calculate_indicators(frame(np.r_[base, 59.0]))
        kind, row = se.classify("WAIT.CA", below, ALL_MIRRORS, True, SIG, RISK)
        check("4/4 below activation -> WATCH", kind == "WATCH" and abs(row["المسافة %"] - round((60.3 - 59) / 59 * 100, 2)) < 1e-6, str(row))
        # 3) اخترق أمس (مش النهارده) → مفيش إشارة جديدة
        late = eng.calculate_indicators(frame(np.r_[base, 62.0, 63.0]))
        check("breakout was yesterday -> None", se.classify("LATE.CA", late, ALL_MIRRORS, True, SIG, RISK) is None)
        # 4) مرايا ناقصة أو screener فاشل → None
        check("mirrors not 4/4 -> None", se.classify("X", breakout, {"signal": "WAIT", "mirrors": {}}, True, SIG, RISK) is None)
        check("screener fail -> None", se.classify("X", breakout, ALL_MIRRORS, False, SIG, RISK) is None)
    finally:
        eng.evaluate_4_mirrors = real_eval

    # 5) المحفظة: وقف / هدف / EMA50 / احتفظ مع تنبيهات / وقف افتراضي / سهم بدون بيانات
    up = eng.calculate_indicators(frame(np.linspace(40, 60, 120)))   # ترند صاعد: Close فوق EMA50
    c = float(up["Close"].iloc[-1]); atr = float(up["ATR"].iloc[-1])
    down = eng.calculate_indicators(frame(np.r_[np.linspace(40, 60, 100), np.linspace(60, 45, 20)]))
    ind = {"SL.CA": up, "TP.CA": up, "EMA.CA": down, "NEAR.CA": up, "DEF.CA": up}
    pf = pd.DataFrame([
        {"ticker": "SL.CA", "shares": 100, "entry_price": c * 1.1, "entry_date": "", "stop_loss": c + 0.01, "target": np.nan, "notes": ""},
        {"ticker": "TP.CA", "shares": 100, "entry_price": 50, "entry_date": "", "stop_loss": 40, "target": c, "notes": ""},
        {"ticker": "EMA.CA", "shares": 100, "entry_price": 50, "entry_date": "", "stop_loss": 30, "target": np.nan, "notes": ""},
        {"ticker": "NEAR.CA", "shares": 10, "entry_price": 55, "entry_date": "", "stop_loss": c - atr / 2, "target": np.nan, "notes": ""},
        {"ticker": "DEF.CA", "shares": 10, "entry_price": c, "entry_date": "", "stop_loss": np.nan, "target": np.nan, "notes": ""},
        {"ticker": "MISSING.CA", "shares": 10, "entry_price": 10, "entry_date": "", "stop_loss": 9, "target": np.nan, "notes": ""},
    ])
    sell, holdings, alerts = se.review_portfolio(pf, ind)
    reasons = dict(zip(sell["Ticker"], sell["التوصية"]))
    check("portfolio: SL hit -> sell", "الوقف" in reasons.get("SL.CA", ""), str(reasons))
    check("portfolio: target hit -> take profit", "الهدف" in reasons.get("TP.CA", ""))
    check("portfolio: close < EMA50 -> sell", "EMA" in sell.set_index("Ticker").loc["EMA.CA", "السبب"] if "EMA.CA" in reasons else False)
    check("portfolio: near SL -> alert, not sell", "NEAR.CA" not in reasons and any("NEAR.CA" in a and "قريب من الوقف" in a for a in alerts))
    check("portfolio: blank stop -> default -15%", abs(holdings.set_index("Ticker").loc["DEF.CA", "SL"] - round(c * 0.85, 3)) < 1e-6 and "DEF.CA" not in reasons)
    check("portfolio: ticker without data -> alert", any("MISSING.CA" in a for a in alerts))
    h = holdings.set_index("Ticker")
    check("portfolio: PnL = (Close-Entry)*Shares", abs(h.loc["TP.CA", "PnL"] - round((c - 50) * 100, 2)) < 1e-6, f"{h.loc['TP.CA', 'PnL']}")

    # 6) حفظ/تحميل المحفظة (كتابة ذرّية)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "portfolio.csv"
        se.save_portfolio(pf, path)
        back = se.load_portfolio(path)
        check("portfolio save/load roundtrip", len(back) == len(pf) and list(back.columns) == se.PORTFOLIO_COLUMNS and not path.with_suffix(".tmp").exists())
        check("missing portfolio file -> empty frame", se.load_portfolio(Path(tmp) / "nope.csv").empty)

        # 7) تيليجرام: رسالة فاضية → None، escaping، ومنع التكرار في نفس اليوم (stub بدل الإرسال الحقيقي)
        empty = se.Signals(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), [], "2026-10-01")
        check("telegram: nothing to say -> None", se.telegram_message(empty) is None)
        sig = se.Signals(pd.DataFrame(), pd.DataFrame(), sell, holdings, alerts + ["<b>x</b>"], expected_session().isoformat())
        msg = se.telegram_message(sig)
        check("telegram: message has sells + alerts, escaped", "SL.CA" in msg and "&lt;b&gt;x&lt;/b&gt;" in msg and "ليست أمر تنفيذ" in msg)
        calls: list[str] = []
        real_send = telegram_notifier.send_telegram
        telegram_notifier.send_telegram = lambda m: calls.append(m) or {"ok": True}
        try:
            log_path = Path(tmp) / "sent.json"
            first, second = se.notify(sig, log_path), se.notify(sig, log_path)
        finally:
            telegram_notifier.send_telegram = real_send
        check("telegram: sent once, duplicate skipped", first["sent"] and not second["sent"] and len(calls) == 1, f"{first} {second}")

    # 8) البيانات الحقيقية: الماسح بيشتغل، وحالة المرايا لكل سهم (للتقرير)
    real = eng.load_data_map(HERE / "data")
    s = se.build_signals(real, SIG, RISK, pd.DataFrame(columns=se.PORTFOLIO_COLUMNS))
    status = {}
    for t, d in real.items():
        data = eng.calculate_indicators(d)
        ev = eng.evaluate_4_mirrors(data, SIG)
        status[t] = f"{ev['signal']} {sum(ev['mirrors'].values())}/4"
    check("real data scan (informational)", True, f"as_of={s.as_of} buy={len(s.buy)} watch={len(s.watch)} mirrors={status}")

    # 9) تبويب 9 في الداشبورد (AppTest): حقيقي + Demo + بدون بيانات
    from streamlit.testing.v1 import AppTest
    for label, source in (("real", "CSV Folder"), ("demo", "Demo Data"), ("empty", None)):
        at = AppTest.from_file(str(HERE / "egx_dashboard.py"), default_timeout=300)
        at.run()
        if source == "Demo Data":
            at.sidebar.radio[0].set_value("Demo Data").run()
            [b for b in at.sidebar.button if b.label.startswith("Generate")][0].click().run()
        elif source == "CSV Folder":
            at.sidebar.radio[0].set_value("CSV Folder").run()
            at.sidebar.text_input[0].set_value(str(HERE / "data")).run()
            [b for b in at.sidebar.button if b.label == "Load"][0].click().run()
        labels = [t.label for t in at.tabs]
        text = " ".join(str(m.value) for m in at.markdown)
        sections = all(k in text for k in ("اشتري الآن", "انتظر", "بيع")) if source else True
        check(f"dashboard tab 9 [{label}]", len(at.exception) == 0 and len(labels) == 10
              and labels[8] == "🎯 إشارات اليوم" and labels[9] == "📝 تداول ورقي" and sections,
              f"tabs={len(labels)} exceptions={[str(e.value)[:150] for e in at.exception]}")

    passed = sum(ok for _, ok, _ in results)
    print(f"\nRESULT {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def test_script_suite() -> None:  # pytest entry point: every check above must pass
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
