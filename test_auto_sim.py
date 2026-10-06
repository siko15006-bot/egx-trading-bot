"""اختبار auto_sim على DB مؤقت وبيانات صناعية (مش الحقيقية).
التشغيل: python test_auto_sim.py   (أو pytest)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

import auto_sim
import egx_4_mirrors_v3 as eng

RISK = eng.RiskConfig()


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2026-09-01", periods=len(rows), freq="D", tz=eng.CAIRO_TZ).tz_convert("UTC")
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx).assign(Volume=1000)


def _signals(*rows: tuple[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{"Ticker": t, "Status": "BUY", "Entry": 100.0, "SL": 95.0, "TP": 110.0, "ATR": 3.0,
                          "Shares": 10, "RR_Net": rr} for t, rr in rows])


def test_rank_quota_and_no_duplicates() -> None:
    db = Path(tempfile.mkdtemp()) / "t.db"
    sig = _signals(("BBB.CA", 2.0), ("AAA.CA", 2.0), ("CCC.CA", 3.0))
    assert auto_sim.open_new(sig, "2026-09-01", db) == ["CCC.CA", "AAA.CA"]  # RR desc, then A→Z
    assert auto_sim.open_new(sig, "2026-09-01", db) == []                     # same-day retry opens nothing
    assert auto_sim.open_new(sig, "2026-09-02", db) == ["BBB.CA"]             # open tickers are skipped


def test_replay_rules() -> None:
    # signal bar itself touches both levels: must be ignored (no look-ahead)
    sig_bar = (100, 120, 90, 100)
    assert auto_sim.replay(_bars([sig_bar, (100, 101, 99, 100)]), "2026-09-01", 100, 95, 110, 3)[1] is None
    # same bar hits SL and TP → SL first
    _, ex = auto_sim.replay(_bars([sig_bar, (100, 111, 94, 100)]), "2026-09-01", 100, 95, 110, 3)
    assert ex[1:3] == (95, "SL")
    # gap below stop fills at the open
    _, ex = auto_sim.replay(_bars([sig_bar, (90, 92, 88, 91)]), "2026-09-01", 100, 95, 110, 3)
    assert ex[1:3] == (90, "SL")
    # close ≥ entry+ATR moves stop to breakeven, then a dip exits as TRAIL_SL at entry
    stop, ex = auto_sim.replay(_bars([sig_bar, (101, 104, 100.5, 103.5), (102, 102, 99, 99.5)]), "2026-09-01", 100, 95, 110, 3)
    assert stop == 100 and ex[1:3] == (100, "TRAIL_SL")
    # TP
    _, ex = auto_sim.replay(_bars([sig_bar, (101, 111, 100, 109)]), "2026-09-01", 100, 95, 110, 3)
    assert ex[1:3] == (110, "TP")


def test_update_closes_with_engine_pnl() -> None:
    db = Path(tempfile.mkdtemp()) / "t.db"
    auto_sim.open_new(_signals(("ZZZ.CA", 2.0)), "2026-09-01", db)
    data = {"ZZZ.CA": _bars([(100, 100, 100, 100), (101, 111, 100, 109)])}
    assert auto_sim.update_open(data, RISK, db) == 1
    row = auto_sim.load(db).iloc[0]
    assert row.status == "CLOSED" and row.exit_reason == "TP" and row.exit_date == "2026-09-02"
    assert abs(row.pnl_egp - eng.net_trade_pnl(100, 110, 10, RISK)) < 1e-9
    assert "ABANDON" in auto_sim.summary_line(db) and "مغلقة: 1" in auto_sim.summary_line(db)


if __name__ == "__main__":
    for fn in [f for n, f in dict(globals()).items() if n.startswith("test_")]:
        fn()
        print("PASS", fn.__name__)
