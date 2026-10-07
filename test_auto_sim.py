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
    sig = (100, 120, 90, 100)   # signal bar: never used for entry or exits
    fill = (100, 101, 99, 100)  # next session: entry at its close (100)
    r = lambda *bars: auto_sim.replay(_bars([sig, *bars]), "2026-09-01", 95, 110, 3)
    assert auto_sim.replay(_bars([sig]), "2026-09-01", 95, 110, 3)["status"] == "pending"
    assert r(fill)["status"] == "open" and r(fill)["entry"] == 100
    assert r((100, 100, 94, 94))["status"] == "skipped"          # next close already below the stop
    t = r(fill, (100, 111, 94, 100))                              # same bar hits SL and TP → SL first
    assert (t["exit"], t["reason"]) == (95, "SL")
    for open_ in (90, 100):                                       # gap below the stop → that bar's Close, never its
        t = r(fill, (open_, 92, 88, 91))                          # Open (in-range or not; Ahmed 2026-10-08)
        assert (t["exit"], t["reason"]) == (91, "SL")
    # real ABUK 2026-03-08 bar: Open 77.93 below Low 83.0; stop 80 was never touched → no exit
    abuk = auto_sim.replay(_bars([(86, 87, 85, 86), (86, 87, 85, 86), (77.93, 91.5, 83.0, 87.0)]), "2026-09-01", 80, 95, 2)
    assert abuk["status"] == "open"
    t = r(fill, (101, 104, 100.5, 103.5), (102, 102, 99, 99.5))   # close ≥ entry+ATR → stop to entry, then hit
    assert t["stop"] == 100 and (t["exit"], t["reason"]) == (100, "TRAIL_SL")
    t = r(fill, (101, 111, 100, 109))
    assert (t["exit"], t["reason"]) == (110, "TP")
    t = r(fill, (60, 62, 58, 60))                                 # −40% close-to-close = data break → cancelled
    assert (t["status"], t["reason"]) == ("cancelled", "DATA_BREAK")


def test_update_closes_with_engine_pnl() -> None:
    db = Path(tempfile.mkdtemp()) / "t.db"
    auto_sim.open_new(_signals(("ZZZ.CA", 2.0)), "2026-09-01", db)
    data = {"ZZZ.CA": _bars([(100, 100, 100, 100), (101, 101.5, 100.5, 101), (101, 111, 100, 109)])}
    assert auto_sim.update_open(data, RISK, db) == 1
    row = auto_sim.load(db).iloc[0]
    assert row.status == "CLOSED" and row.exit_reason == "TP" and row.exit_date == "2026-09-03" and row.entry == 101
    assert abs(row.pnl_egp - eng.net_trade_pnl(101, 110, 10, RISK)) < 1e-9
    assert "ABANDON" in auto_sim.summary_line(db) and "مغلقة: 1" in auto_sim.summary_line(db)


def test_closed_trade_pnl_matches_hand_computation(monkeypatch) -> None:
    """Independent oracle (Codex W2): every number below is computed by hand from the tariff in fees_config.py, not by
    eng.net_trade_pnl. 100 shares, entry = next close 10, exit = TP 12 touched inside the bar, overnight, tax 10%.
    Fees per order = brokerage 2 + 0.1% + EGX 0.01% + MCDR 0.01% + FRA max(1, 0.005%) + insurance 0.005% + stamp 0.05%.
      0 bps:  buy 1,000.00 → 3.00+0.10+0.10+1.00+0.05+0.50 = 4.75; sell 1,200.00 → 3.20+0.12+0.12+1.00+0.06+0.60 = 5.10
              pre-tax 1,200 − 1,000 − 4.75 − 5.10 = 190.15; tax 19.015 → 171.135
      10 bps: buy 10.01 → 1,001.00, fees 3.001+0.1001+0.1001+1.00+0.05005+0.5005 = 4.75175;
              sell 11.988 → 1,198.80, fees 3.1988+0.11988+0.11988+1.00+0.05994+0.5994 = 5.0979
              pre-tax 1,198.80 − 1,001.00 − 4.75175 − 5.0979 = 187.95035; tax 18.795035 → 169.155315"""
    monkeypatch.setattr(eng, "with_dividends", lambda ticker, df: df)   # no dividends in this example
    signal = pd.DataFrame([{"Ticker": "HND.CA", "Status": "BUY", "Entry": 10.0, "SL": 9.0, "TP": 12.0, "ATR": 0.5,
                            "Shares": 100, "RR_Net": 2.0}])
    bars = _bars([(10, 10, 10, 10), (10, 10.1, 9.9, 10), (10.5, 12.5, 10.4, 12.2)])
    for bps, expected in ((0.0, 171.135), (10.0, 169.155315)):
        db = Path(tempfile.mkdtemp()) / "t.db"
        auto_sim.open_new(signal, "2026-09-01", db)
        risk = eng.RiskConfig(slippage_bps=bps, capital_gains_tax_pct=0.10)
        assert auto_sim.update_open({"HND.CA": bars}, risk, db) == 1
        row = auto_sim.load(db).iloc[0]
        assert (row.entry, row.exit_price, row.exit_reason) == (10, 12, "TP")
        assert abs(row.pnl_egp - expected) < 1e-6, (bps, row.pnl_egp, expected)


def test_data_break_cancels_without_pnl() -> None:
    db = Path(tempfile.mkdtemp()) / "t.db"
    auto_sim.open_new(_signals(("ZZZ.CA", 2.0)), "2026-09-01", db)
    data = {"ZZZ.CA": _bars([(100, 100, 100, 100), (101, 101.5, 100.5, 101), (50, 51, 49, 50)])}
    assert auto_sim.update_open(data, RISK, db) == 0
    row = auto_sim.load(db).iloc[0]
    assert row.status == "CANCELLED" and row.exit_reason == "DATA_BREAK" and pd.isna(row.pnl_egp)
    assert "مغلقة: 0" in auto_sim.summary_line(db)


if __name__ == "__main__":
    for fn in [f for n, f in dict(globals()).items() if n.startswith("test_")]:
        fn()
        print("PASS", fn.__name__)
