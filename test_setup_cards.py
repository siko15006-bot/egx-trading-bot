"""اختبار طبقة Setup Cards: كل نمط على بيانات مناسبة، تحكم سلبي، قواعد البطاقة، Demo + بيانات حقيقية، وتبويب 8 في الداشبورد.
التشغيل: python test_setup_cards.py   (لا يعدّل أي بيانات؛ الأسهم المُصنّعة هنا للاختبار فقط ولا تُكتب في data/)"""
from __future__ import annotations

import importlib.util
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import egx_4_mirrors_v3 as eng  # noqa: E402
import pattern_detector as pdx  # noqa: E402
from setup_builder import build_setup, build_setups  # noqa: E402

LOG = HERE / "logs" / f"setup_cards_{datetime.now():%Y%m%d}.log"
results: list[tuple[str, bool, str]] = []


# يسجل نتيجة اختبار في القائمة والسجل.
def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [TEST] {'PASS' if ok else 'FAIL'} {name} {detail}"
    print(line)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# يبني DataFrame OHLCV بفهرس UTC من مسار إغلاق (بيانات مُصنّعة للاختبار).
def frame(close: np.ndarray, volume: np.ndarray | None = None, spread: float = 0.006, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(close)
    idx = pd.bdate_range(end="2026-10-01", periods=n).tz_localize("UTC")
    vol = volume if volume is not None else rng.integers(400_000, 700_000, n).astype(float)
    return pd.DataFrame({"Open": np.r_[close[0], close[:-1]], "High": close * (1 + spread), "Low": close * (1 - spread),
                         "Close": close, "Volume": vol}, index=idx)


# سعر صاعد هادئ يسبق النموذج (عشان المؤشرات تتحسب).
def lead_in(n: int, start: float, end: float) -> np.ndarray:
    return np.linspace(start, end, n)


def triangle() -> pd.DataFrame:
    t = np.arange(30)
    amp = np.linspace(0.06, 0.012, 30)
    body = 100 * (1 + amp * np.sin(2 * np.pi * t / 7.5))
    return frame(np.r_[lead_in(110, 70, 100), body])


def cup_handle() -> pd.DataFrame:
    x = np.linspace(-1, 1, 50)
    cup = 100 - 22 * (1 - x ** 2) ** 0.6          # قاع مستدير بعمق ~22%
    cup[-1] = 99.5
    handle = np.linspace(99.0, 94.0, 6).tolist() + [94.5, 95.5, 96.0, 96.5]
    close = np.r_[lead_in(100, 60, 100), cup, handle]
    vol = np.r_[np.full(100, 600_000.0), np.full(50, 650_000.0), np.full(10, 300_000.0)]
    return frame(close, vol, spread=0.004)


def higher_lows() -> pd.DataFrame:
    lows = [90, 92, 94.5, 97]
    path: list[float] = []
    for lo in lows:   # موجة: قاع صاعد ثم رجوع لنفس المقاومة ~100
        path += list(np.linspace(100, lo, 4)) + list(np.linspace(lo, 100, 4))[1:]
    body = np.array(path)[-30:]
    return frame(np.r_[lead_in(110, 70, 100), body])


def bull_flag() -> pd.DataFrame:
    base = np.full(7, 100.0)
    pole = np.linspace(100, 116, 7)[1:]
    flag = np.linspace(115.5, 112.5, 7)
    close = np.r_[lead_in(100, 80, 100), base, pole, flag]
    vol = np.r_[np.full(107, 450_000.0), np.full(6, 1_200_000.0), np.full(7, 300_000.0)]
    return frame(close, vol, spread=0.004)


FIXTURES = {"SYMMETRICAL_TRIANGLE": (triangle, pdx.detect_symmetrical_triangle),
            "CUP_AND_HANDLE": (cup_handle, pdx.detect_cup_and_handle),
            "HIGHER_LOWS": (higher_lows, pdx.detect_higher_lows),
            "BULL_FLAG": (bull_flag, pdx.detect_bull_flag)}


def main() -> int:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"===== test_setup_cards run {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")

    # 1) كل نمط على بيانات مناسبة
    for name, (make, detector) in FIXTURES.items():
        df = make()
        hit = detector(df)
        check(f"pattern {name} detected on its fixture", hit is not None and hit["pattern"] == name,
              f"-> {None if hit is None else (hit['confidence'], hit['key_levels'])}")
        if hit:
            check(f"pattern {name} output schema", set(hit) >= {"pattern", "confidence", "key_levels", "arabic_note"}
                  and hit["confidence"] in pdx.CONFIDENCE_RANK and isinstance(hit["arabic_note"], str))
        others = [n for n, (_, d) in FIXTURES.items() if n != name and d(df) is not None]
        combined = pdx.detect_breakout_pattern(df)
        check(f"detect_breakout_pattern on {name} fixture", combined["pattern"] == name and "levels" in combined,  # the fixture's own pattern, not any detector
              f"-> {combined['pattern']}/{combined['confidence']} (other detectors also firing: {others})")

    # 2) تحكم سلبي: مسارات عشوائية بدون نموذج مقصود
    fp: dict[str, int] = {n: 0 for n in FIXTURES}
    trials = 200
    for seed in range(trials):
        rng = np.random.default_rng(1000 + seed)
        df = frame(100 * np.cumprod(1 + rng.normal(0, 0.012, 160)), seed=seed)
        for n, (_, d) in FIXTURES.items():
            fp[n] += d(df) is not None
    check("negative control (random walks) false-positive rates", all(v / trials < 0.35 for v in fp.values()),
          json.dumps({k: f"{v / trials:.0%}" for k, v in fp.items()}))
    check("too-short / missing-column input returns None",
          all(d(frame(np.linspace(1, 2, 10))) is None for _, d in FIXTURES.values()) and
          pdx.detect_symmetrical_triangle(pd.DataFrame({"Close": [1.0] * 50})) is None)

    # 3) قواعد البطاقة على كل الإعدادات اللي اتبنت
    sig, risk = eng.SignalConfig(), eng.RiskConfig()
    pool = {f"{n}.TEST": make() for n, (make, _) in FIXTURES.items()}
    real = eng.load_data_map(HERE / "data") if (HERE / "data").is_dir() else {}
    spec = importlib.util.spec_from_file_location("dash_for_demo", HERE / "egx_dashboard.py")
    dash = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dash)
    demo = dash.generate_demo_data()
    built = [(t, d, build_setup(t, d, sig, risk)) for t, d in {**pool, **demo, **real}.items()]
    produced = [(t, d, s) for t, d, s in built if s is not None]
    rule_ok = True
    for t, d, s in produced:
        ind = eng.calculate_indicators(d)
        act, low10 = float(ind["High"].tail(10).max()), float(ind["Low"].tail(10).min())
        rr = (s.target - s.activation) / (s.activation - s.stop_loss)
        rule_ok &= abs(s.activation - act) < 1e-3 and abs(s.stop_loss - s.invalidation) < 1e-9 and s.rr >= 2.0 \
            and abs(rr - s.rr) < 0.02 and (abs(s.invalidation - low10) < 1e-3 or s.invalidation == round(float(ind["EMA_50"].iloc[-1]), 3)) \
            and s.quality in {"BEST", "ACTIVE", "WATCH"} and bool(s.note)
    check("card rules (activation=10d high, stop=invalidation=10d low, rr formula, rr>=2, quality, note)",
          rule_ok and len(produced) > 0, f"cards checked: {len(produced)}")

    # 4) R:R < 2 → None: نفس السهم بس مع قمة سابقة فوق التفعيل مباشرة (مقاومة قريبة)
    base_t, base_d, base_s = produced[0]
    capped = base_d.copy()
    pos = capped.index[-30]
    capped.loc[pos, "High"] = base_s.activation * 1.02
    check("prior peak just above activation caps target -> rr<2 -> None",
          build_setup(base_t, capped, sig, risk) is None, f"base {base_t} rr={base_s.rr}")

    # 5) Demo + حقيقي: بطاقات لأسهم مختلفة
    demo_cards = [s for s in build_setups(demo, sig, risk)]
    all_cards = [s for _, _, s in produced]
    check("demo 5 stocks analysed", len(demo) == 5 and len(demo_cards) > 0, f"cards: {[(s.ticker, s.quality, s.pattern, s.rr) for s in demo_cards]}")
    check("cards appear for different stocks", len({s.ticker for s in all_cards}) >= 2,
          f"{[(s.ticker, s.quality, s.pattern, s.rr) for s in all_cards]}")
    real_cards = build_setups(real, sig, risk)
    check("real EGX data analysed: every card keeps rr>=2 and stop below activation", len(real) > 0 and all(
          s.rr >= 2 and s.stop_loss < s.activation for s in real_cards),
          f"{len(real)} tickers, cards: {[(s.ticker, s.quality, s.rr) for s in real_cards]}")

    # 6) تبويب 8 في الداشبورد (AppTest): Demo، بيانات حقيقية، وبدون بيانات + التصدير
    from streamlit.testing.v1 import AppTest
    for label, source in (("demo", "Demo Data"), ("real", "CSV Folder"), ("empty", None)):
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
        cards_html = sum("R:R = 1:" in str(m.value) for m in at.markdown)
        check(f"dashboard tab 8 [{label}]", len(at.exception) == 0 and len(labels) >= 8 and labels[7].startswith("🎴"),
              f"tabs={len(labels)} exceptions={[str(e.value)[:120] for e in at.exception]} cards_rendered={cards_html}")

    frame_ = dash._setups_frame(all_cards)
    pdf, engine = dash._setups_pdf(frame_)
    check("export CSV", frame_.to_csv(index=False).count("\n") == len(all_cards) + 1)
    check("export PDF", pdf is not None and pdf[:4] == b"%PDF", f"engine={engine} bytes={0 if pdf is None else len(pdf)}")
    check("card HTML escapes ticker text", "&lt;script&gt;" in dash._setup_card_html(
        all_cards[0].__class__(**{**all_cards[0].to_dict(), "ticker": "<script>x</script>"})))

    # 7) وسم Mirrors على بطاقات BEST + عمود/فلتر 4/4 في تبويب 8
    from setup_builder import mirrors_label
    check("mirrors_label texts", mirrors_label(4).startswith("📊 Mirrors: 4/4") and "3/4" in mirrors_label(3) and "خطر عالي" in mirrors_label(2)
          and mirrors_label(0).startswith("📊 Mirrors: 0/4"))
    etel = real.get("ETEL.CA")
    best = [c for c in (build_setup("ETEL.CA", etel.iloc[: i + 1], sig, risk) for i in range(60, len(etel))) if c and c.quality == "BEST"] if etel is not None else []
    check("BEST notes carry the matching mirrors label (ETEL history)", len(best) > 0 and all(c.note.startswith(mirrors_label(c.mirrors_count)) for c in best),
          f"BEST cards={len(best)} counts={sorted({c.mirrors_count for c in best})}")
    non_best = [s for s in all_cards if s.quality != "BEST"]
    check("non-BEST notes unchanged (no label)", len(non_best) > 0 and all(not s.note.startswith("📊") for s in all_cards if s.quality != "BEST"))
    at = AppTest.from_file(str(HERE / "egx_dashboard.py"), default_timeout=300)
    at.run()
    at.sidebar.radio[0].set_value("Demo Data").run()
    [b for b in at.sidebar.button if b.label.startswith("Generate")][0].click().run()
    before = sum("R:R = 1:" in str(m.value) for m in at.markdown)
    has_col = any("Mirrors" in getattr(d.value, "data", d.value).columns for d in at.dataframe)
    at.checkbox(key="cards_only_4of4").check().run()
    after = sum("R:R = 1:" in str(m.value) for m in at.markdown)
    full = sum(1 for c in demo_cards if c.mirrors_count == 4)
    check("tab 8 Mirrors column + 'only 4/4' filter", len(at.exception) == 0 and has_col and after == full and before >= after,
          f"cards before={before} after={after} expected 4/4={full}")

    passed = sum(ok for _, ok, _ in results)
    print(f"\nRESULT {passed}/{len(results)} passed")
    (HERE / "logs" / "setup_cards_test_results.json").write_text(
        json.dumps([{"test": n, "pass": ok, "detail": d} for n, ok, d in results], ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if passed == len(results) else 1


def test_script_suite() -> None:  # pytest entry point: every check above must pass
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
