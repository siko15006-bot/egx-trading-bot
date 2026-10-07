"""Shared execution conventions (egx_4_mirrors_v3.simulate_trade), red-team review 2026-10-07.
Run: python -m pytest test_execution.py
"""
from __future__ import annotations

import pandas as pd

import egx_4_mirrors_v3 as eng


def _bars(rows):
    idx = pd.date_range("2026-09-01", periods=len(rows), freq="D", tz=eng.CAIRO_TZ).tz_convert("UTC")
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close"], index=idx).assign(Volume=1000)


def test_entry_is_next_close_and_fills_stay_in_range() -> None:
    d = _bars([(100, 101, 99, 100), (100, 102, 99, 101), (60, 99, 97, 98), (98, 99, 90, 91)])
    t = eng.simulate_trade(d, 0, 95.0, 110.0, 2.0)
    assert t["entry_index"] == 1 and t["entry"] == 101          # signal bar 0 → entry at bar 1 close
    assert t["exit_index"] == 3 and t["exit"] == 95.0           # bar 2 Open 60 ignored (not a real open)
    assert all(d["Low"].iloc[t["exit_index"]] <= t["exit"] <= d["High"].iloc[t["exit_index"]] for _ in [0])


def test_gap_below_stop_fills_at_bar_high_not_open() -> None:
    d = _bars([(100, 101, 99, 100), (100, 101, 99, 100), (88, 92, 87, 90)])
    assert eng.simulate_trade(d, 0, 95.0, 110.0, 2.0)["exit"] == 92


def test_data_break_closes_at_last_valid_close() -> None:
    d = _bars([(100, 101, 99, 100), (100, 101, 99, 100), (50, 51, 49, 50)])   # −50%: unadjusted split
    t = eng.simulate_trade(d, 0, 95.0, 110.0, 2.0)
    assert (t["reason"], t["exit"], t["exit_index"]) == ("DATA_BREAK", 100.0, 1)


def test_pending_and_skipped() -> None:
    assert eng.simulate_trade(_bars([(100, 101, 99, 100)]), 0, 95.0, 110.0, 2.0)["status"] == "pending"
    assert eng.simulate_trade(_bars([(100, 101, 99, 100), (100, 100, 93, 94)]), 0, 95.0, 110.0, 2.0)["status"] == "skipped"


def test_slippage_costs_both_sides() -> None:
    no_slip = eng.RiskConfig(slippage_bps=0.0)
    slip = eng.RiskConfig(slippage_bps=10.0)
    base = eng.net_trade_pnl(100, 110, 100, no_slip)
    assert eng.net_trade_pnl(100, 110, 100, slip) < base
    assert abs(eng.net_trade_pnl(100, 110, 100, slip) - eng.net_trade_pnl(100.1, 109.89, 100, no_slip)) < 1e-9
