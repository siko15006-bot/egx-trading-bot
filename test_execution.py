"""Execution policy (docs/execution_policy.md) — engine, optimizer and portfolio simulator.
Each test pins one rule or one finding of Codex's adversarial audit (2026-10-07).
Run: python -m pytest test_execution.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backtest_optimizer as bo
import egx_4_mirrors_v3 as eng


def _bars(rows, volume=1000.0):
    idx = pd.date_range("2026-09-01", periods=len(rows), freq="D", tz=eng.CAIRO_TZ).tz_convert("UTC")
    frame = pd.DataFrame([r[:4] for r in rows], columns=["Open", "High", "Low", "Close"], index=idx)
    frame["Volume"] = [r[4] if len(r) > 4 else volume for r in rows]
    return frame


SIG = (100, 101, 99, 100)   # signal bar
FILL = (100, 102, 99, 101)  # entry bar: entry = 101


def test_entry_is_next_close() -> None:
    t = eng.simulate_trade(_bars([SIG, FILL]), 0, 95.0, 110.0, 2.0)
    assert (t["status"], t["entry_index"], t["entry"]) == ("open", 1, 101)


def test_stop_touched_inside_bar_fills_at_stop() -> None:
    t = eng.simulate_trade(_bars([SIG, FILL, (100, 100, 94, 96)]), 0, 95.0, 110.0, 2.0)
    assert (t["exit"], t["reason"]) == (95, "SL")


def test_gap_down_real_open_fills_at_open() -> None:
    t = eng.simulate_trade(_bars([SIG, FILL, (88, 92, 87, 90)]), 0, 95.0, 110.0, 2.0)
    assert (t["exit"], t["reason"]) == (88, "SL")


def test_gap_down_fake_open_fills_at_close() -> None:
    # Open equals the previous close (Yahoo's usual value) and sits outside the bar → not a price; use the bar's close.
    t = eng.simulate_trade(_bars([SIG, FILL, (101, 92, 87, 90)]), 0, 95.0, 110.0, 2.0)
    assert (t["exit"], t["reason"]) == (90, "SL")


def test_gap_up_target_real_and_fake_open() -> None:
    assert eng.simulate_trade(_bars([SIG, FILL, (115, 118, 113, 116)]), 0, 95.0, 110.0, 2.0)["exit"] == 115
    assert eng.simulate_trade(_bars([SIG, FILL, (101, 118, 113, 116)]), 0, 95.0, 110.0, 2.0)["exit"] == 116


def test_zero_volume_bar_never_fills() -> None:  # Codex finding A
    assert eng.simulate_trade(_bars([SIG, (100, 100, 100, 100, 0)]), 0, 90.0, 120.0, 2.0)["status"] == "skipped"
    t = eng.simulate_trade(_bars([SIG, FILL, (85, 85, 85, 85, 0)]), 0, 90.0, 120.0, 2.0)
    assert t["status"] == "open"   # the filler row below the stop is not a trade


def test_data_break_cancels_instead_of_closing_retroactively() -> None:  # Codex finding 2
    before = eng.simulate_trade(_bars([SIG, FILL]), 0, 95.0, 110.0, 2.0)
    after = eng.simulate_trade(_bars([SIG, FILL, (50, 51, 49, 50)]), 0, 95.0, 110.0, 2.0)
    assert before["status"] == "open"
    assert (after["status"], after["reason"], after["break_index"]) == ("cancelled", "DATA_BREAK", 2)
    assert "exit" not in after   # no retroactive fill


def test_break_threshold_is_symmetric() -> None:  # asymmetry finding: a −20% limit-down day is not a break
    def brk(ret):
        return bool(eng.data_breaks(pd.DataFrame({"Close": [100, 100 * (1 + ret)], "Volume": [1, 1]}))[1])
    assert not brk(-0.20) and not brk(-0.2001) and not brk(-0.25) and not brk(0.25)
    assert brk(-0.2501) and brk(0.2501)


def test_slippage_validation() -> None:  # Codex finding 4
    for bad in (-10, np.nan, np.inf, 1001):
        with pytest.raises(ValueError):
            eng.RiskConfig(slippage_bps=bad)
    assert eng.RiskConfig(slippage_bps=0).slippage_bps == 0


def test_slippage_costs_both_sides() -> None:
    no_slip, slip = eng.RiskConfig(slippage_bps=0.0), eng.RiskConfig(slippage_bps=10.0)
    assert eng.net_trade_pnl(100, 110, 100, slip) < eng.net_trade_pnl(100, 110, 100, no_slip)
    assert abs(eng.net_trade_pnl(100, 110, 100, slip) - eng.net_trade_pnl(100.1, 109.89, 100, no_slip)) < 1e-9


def _flat(n=70):
    idx = pd.date_range("2026-01-04", periods=n, freq="D", tz=eng.CAIRO_TZ).tz_convert("UTC")
    c = np.full(n, 100.0)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)


def test_portfolio_break_no_crash_and_cancelled(monkeypatch) -> None:  # Codex finding 1
    d = _flat()
    d.iloc[66:, :4] = d.iloc[66:, :4] * 0.5   # entry bar 65, break on the next bar
    monkeypatch.setattr(bo, "_trend_entry", lambda data, i, sc: {"x": 1} if i == 64 else None)
    r = bo.simulate_d({"T.CA": d}, 4, 100000.0)
    assert r["trades"].empty and len(r["cancelled"]) == 1


def test_portfolio_final_equity_includes_end_costs(monkeypatch) -> None:  # Codex finding 3
    monkeypatch.setattr(bo, "_trend_entry", lambda data, i, sc: {"x": 1} if i == 64 else None)
    r = bo.simulate_d({"T.CA": _flat()}, 4, 100000.0)
    assert abs(float(r["equity"].iloc[-1]) - (100000 + float(r["trades"]["pnl"].sum()))) < 1e-6


def test_empty_window_does_not_crash() -> None:  # Codex finding 5
    r = bo.simulate(_flat(65), bo.SCENARIOS["Baseline"], "realistic", "2030-01-01")
    assert r["trades"].empty and r["bh"].empty


def test_filler_row_never_moves_the_trailing_stop() -> None:  # missing test 4
    # filler Close 106 ≥ entry+2·ATR would lift the stop to 103 and the next bar (Low 100) would stop out
    t = eng.simulate_trade(_bars([SIG, FILL, (106, 106, 106, 106, 0), (101, 102, 100, 101)]), 0, 95.0, 120.0, 2.0)
    assert (t["status"], t["stop"]) == ("open", 95.0)
    flat_real = eng.simulate_trade(_bars([SIG, FILL, (101, 101, 101, 101, 500)]), 0, 95.0, 120.0, 2.0)
    assert flat_real["status"] == "open"   # positive control: a flat bar with volume is a real bar


def test_break_threshold_counts_elapsed_filler_sessions() -> None:  # missing tests 12–13
    def flags(closes, vols):
        return eng.data_breaks(pd.DataFrame({"Close": closes, "Volume": vols})).tolist()
    assert flags([100, 70], [1, 1]) == [False, True]                    # −30% next session: break
    assert flags([100, 100, 70], [1, 0, 1]) == [False, False, False]   # same move over 2 sessions: 0.75² allowed
    # ponytail: known ceiling (docs/execution_policy.md) — after two filler rows a −40% split goes undetected,
    # −60% is still caught. A corporate-action feed is the upgrade path, not a tighter heuristic.
    assert flags([100, 100, 100, 60], [1, 0, 0, 1])[-1] is False
    assert flags([100, 100, 100, 40], [1, 0, 0, 1])[-1] is True


def test_net_pnl_matches_independent_examples() -> None:  # missing test 15: oracle is the tariff, not net_trade_pnl
    from fees_config import round_trip_fees
    risk = eng.RiskConfig(capital_gains_tax_pct=0, slippage_bps=10.0)
    for buy, sell in ((100, 110), (100, 90), (100, 100)):          # gain, loss, flat
        b, s = buy * 100 * 1.001, sell * 100 * 0.999                # 100 shares, 10 bps each side
        expected = s - b - round_trip_fees(b, s, same_session=False)
        assert eng.net_trade_pnl(buy, sell, 100, risk) == pytest.approx(expected)
    assert eng.net_trade_pnl(100, 100, 100, risk) < 0               # a flat trade always costs money


def test_optimizer_edge_windows_return_empty() -> None:  # missing test 16
    d = _flat(65)
    last = d.index[-1].tz_convert(eng.CAIRO_TZ).strftime("%Y-%m-%d")
    assert bo.simulate(d, bo.SCENARIOS["Baseline"], "realistic", last)["trades"].empty   # starts on the last row
    assert bo.simulate(_flat(30), bo.SCENARIOS["Baseline"], "realistic")["trades"].empty  # below warm-up
    r = bo.simulate_d({}, 4, 100000.0)
    assert r["trades"].empty and len(r["cancelled"]) == 0


def test_optimizer_cli_rejects_bad_slippage() -> None:  # missing tests 9–10: clean usage errors, no IndexError
    import subprocess, sys
    from pathlib import Path
    here = Path(__file__).parent
    for argv, code, text in ((["--slippage-bps"], 2, "expected one argument"), (["--slippage-bps", "-5"], 1, "slippage_bps"),
                             (["--slippage-bps", "nan"], 1, "slippage_bps"), (["--bogus"], 2, "unrecognized")):
        p = subprocess.run([sys.executable, "backtest_optimizer.py", *argv], cwd=here, capture_output=True, text=True, timeout=120)
        assert p.returncode == code and text in p.stderr and "IndexError" not in p.stderr, (argv, p.returncode, p.stderr[-300:])
