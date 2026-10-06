"""فحص تناسق الإشارات بين تبويبات الداشبورد (كلها لازم تكون على egx_4_mirrors_v3).

1) ثابت: مفيش ملف في سلسلة الداشبورد بيستورد egx_4_mirrors_v2، وبعد تشغيل الداشبورد v2 مش في sys.modules.
2) حيّ (AppTest على data/): Tab 2 (Run Scanner) و Tab 3 (لكل سهم) و Tab 9 — نفس الإشارة لكل سهم.
3) تاريخي (COMI/SWDY/ETEL، كل يوم من الشمعة 60 لآخر يوم): نفس الدوال اللي التبويبات بتناديها على البيانات لحد اليوم ده:
     Tab 2 scan_universe · Tab 3 evaluate_4_mirrors · Tab 8 build_setup · Tab 9 signal_engine.classify
   قواعد التناقض (أي واحدة = FAIL):
     a) Tab 2 = BUY  ⇔  Tab 3 = BUY
     b) سهم في Tab 9 (اشتري الآن / انتظر الاختراق) ⇒ Tab 2 = BUY  (Tab 9 مايعرضش سهم الماسح شايفه WAIT)
     c) Tab 9 «اشتري الآن» ⇒ نفس Entry/SL/TP/Shares اللي في Tab 2
     d) بطاقة Tab 8 ⇒ عدد المرايا فيها = Tab 3، وبطاقة ACTIVE ⇒ Tab 2 = BUY
     e) Tab 2 = BUY ⇒ Tab 9 يا إما «اشتري الآن» أو «انتظر الاختراق» أو الاختراق فات (فوق التنشيط من قبل) — عمره ما يكون غايب بسبب WAIT
التشغيل: python consistency_check.py   (exit 1 لو فيه أي تناقض)
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import egx_4_mirrors_v3 as eng  # noqa: E402
import signal_engine as se  # noqa: E402
from setup_builder import build_setup  # noqa: E402

TICKERS = ["COMI.CA", "SWDY.CA", "ETEL.CA"]
DASHBOARD_CHAIN = ["egx_dashboard.py", "setup_builder.py", "pattern_detector.py", "signal_engine.py", "analytics_engine.py"]
LOG = HERE / "logs" / f"consistency_{datetime.now():%Y%m%d}.log"
problems: list[str] = []


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def fail(msg: str) -> None:
    problems.append(msg)
    log(f"[CONTRADICTION] {msg}")


def static_check() -> None:
    for name in DASHBOARD_CHAIN:
        if re.search(r"^\s*(from|import)\s+egx_4_mirrors_v2\b", (HERE / name).read_text(encoding="utf-8"), re.M):
            fail(f"{name} imports egx_4_mirrors_v2")
    log(f"[STATIC] dashboard import chain checked: {DASHBOARD_CHAIN}")


def live_check() -> dict[str, dict[str, str]]:
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(HERE / "egx_dashboard.py"), default_timeout=300)
    at.run()
    at.sidebar.radio[0].set_value("CSV Folder").run()
    at.sidebar.text_input[0].set_value(str(HERE / "data")).run()
    [b for b in at.sidebar.button if b.label == "Load"][0].click().run()
    [b for b in at.button if b.label == "Run Scanner"][0].click().run()
    if at.exception:
        fail(f"dashboard exceptions: {[str(e.value)[:200] for e in at.exception]}")
    if "egx_4_mirrors_v2" in sys.modules:
        fail("egx_4_mirrors_v2 was imported while running the dashboard")
    frames = [d.value for d in at.dataframe]
    frames = [f.data if hasattr(f, "data") else f for f in frames]   # Styler → DataFrame
    scanner = next((f for f in frames if "Mirrors Score" in f.columns), None)
    if scanner is None:
        fail("Tab 2 scanner table not rendered")
        return {}
    tab9_rows = {r["Ticker"]: kind for f in frames for kind, col in (("BUY_NOW", "Entry"), ("WATCH", "مستوى التنشيط"))
                 if col in f.columns and "السبب" in f.columns for _, r in f.iterrows()}
    out: dict[str, dict[str, str]] = {}
    tab3_box = next(s for s in at.selectbox if s.label == "Ticker")
    for t in TICKERS:
        tab2 = str(scanner.set_index("Ticker").loc[t, "Status"])
        tab3_box.set_value(t).run()
        info = " ".join(str(i.value) for i in at.info) + " " + " ".join(str(w.value) for w in at.warning)
        has_plan = any(m.label == "Entry" for m in at.metric)
        tab3 = "BUY" if has_plan or "الإشارة مكتملة" in info else (re.search(r"Current signal: (\w+)", info) or [None, "?"])[1]
        tab9 = tab9_rows.get(t, "—")
        out[t] = {"Tab2": tab2, "Tab3": tab3, "Tab9": tab9}
        if (tab2 == "BUY") != (tab3 == "BUY") and tab2 != "SCREEN_FAIL":
            fail(f"live {t}: Tab2={tab2} Tab3={tab3}")
        if tab9 != "—" and tab2 != "BUY":
            fail(f"live {t}: Tab9={tab9} but Tab2={tab2}")
    log(f"[LIVE] last bar of data/: {json.dumps(out)}")
    return out


def historical_check() -> dict[str, dict[str, int]]:
    data_map = eng.load_data_map(HERE / "data")
    sig, risk, screen = eng.SignalConfig(), eng.RiskConfig(), eng.ScreenConfig()
    stats: dict[str, dict[str, int]] = {}
    for t in TICKERS:
        full = data_map[t]
        c = {"days": 0, "tab2_buy": 0, "tab9_buy_now": 0, "tab9_watch": 0, "tab9_breakout_passed": 0, "cards": 0, "cards_best_while_tab2_not_buy": 0}
        for i in range(60, len(full)):
            raw = full.iloc[: i + 1]
            data = eng.calculate_indicators(raw)
            day = se._day(data.index[-1])
            tab2_row = eng.scan_universe({t: raw}, screen, sig, risk, 2).iloc[0]
            tab2 = tab2_row["Status"]
            ev = eng.evaluate_4_mirrors(data, sig)                  # Tab 3
            screen_ok, _ = eng.passes_screener(data, screen)
            tab9 = se.classify(t, data, ev, screen_ok, sig, risk)   # Tab 9
            card = build_setup(t, raw, sig, risk)                   # Tab 8
            c["days"] += 1
            c["tab2_buy"] += tab2 == "BUY"
            if (tab2 == "BUY") != (ev["signal"] == "BUY") and tab2 != "SCREEN_FAIL":
                fail(f"a) {t} {day}: Tab2={tab2} Tab3={ev['signal']}")
            if tab9 is not None:
                c["tab9_buy_now" if tab9[0] == "BUY" else "tab9_watch"] += 1
                if tab2 != "BUY":
                    fail(f"b) {t} {day}: Tab9={tab9[0]} but Tab2={tab2}")
                if tab9[0] == "BUY" and not all(np.isclose(tab9[1][k], tab2_row[k2]) for k, k2 in (("Entry", "Entry"), ("SL", "SL"), ("TP", "TP"), ("Shares", "Shares"))):
                    fail(f"c) {t} {day}: Tab9 plan {[tab9[1][k] for k in ('Entry', 'SL', 'TP', 'Shares')]} != Tab2 {[tab2_row[k] for k in ('Entry', 'SL', 'TP', 'Shares')]}")
            elif tab2 == "BUY":
                c["tab9_breakout_passed"] += 1   # e) BUY بس الإغلاق فوق التنشيط من قبل النهارده → مش WAIT
                activation = float(data["High"].iloc[-11:-1].max())
                if not float(data["Close"].iloc[-1]) > activation:
                    fail(f"e) {t} {day}: Tab2=BUY but Tab9 shows nothing and close is not above activation")
            if card is not None:
                c["cards"] += 1
                if card.mirrors_count != sum(ev["mirrors"].values()):
                    fail(f"d) {t} {day}: Tab8 mirrors {card.mirrors_count} != Tab3 {sum(ev['mirrors'].values())}")
                if card.quality == "ACTIVE" and tab2 != "BUY":
                    fail(f"d) {t} {day}: Tab8 ACTIVE card but Tab2={tab2}")
                if card.quality == "BEST" and tab2 != "BUY":
                    c["cards_best_while_tab2_not_buy"] += 1
        stats[t] = c
        log(f"[HISTORY] {t} {json.dumps(c)}")
    return stats


def main() -> int:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"===== consistency_check run {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    static_check()
    live_check()
    historical_check()
    log(f"[RESULT] {'PASS' if not problems else 'FAIL'} contradictions={len(problems)}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
