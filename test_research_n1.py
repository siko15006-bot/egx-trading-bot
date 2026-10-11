"""N1 engine: no look-ahead, benchmark = plain buy & hold, filler bars never fill."""
import numpy as np
import pandas as pd

import research_n1_nabil2024 as n1


def _panel(jump_day: str | None = None, after: str | None = None):
    idx = pd.bdate_range("2009-01-01", "2010-12-31")
    names = [f"T{k:02d}.CA" for k in range(35)]
    close = pd.DataFrame(100.0, index=idx, columns=names)
    if jump_day:
        close.loc[jump_day:, "T00.CA"] = 110.0          # the only move: T00 +10% on jump_day
    if after:
        close.loc[after:, "T00.CA"] = 121.0             # a later +10%, after the strategy could have bought
    value = pd.DataFrame(1e6, index=idx, columns=names)
    value["T00.CA"] = 1e9                               # most liquid: always in the proxy universe
    return close, value, value.notna()


def test_benchmark_is_buy_and_hold():
    close, value, real = _panel()
    close.loc["2010-03-01":, :] = 120.0                 # every stock +20% inside 2010-H1
    r = n1.run(close, value, real, n1.Cfg("EW", cost=0.0))
    h1 = r.halves.iloc[0]
    assert abs(h1["ret"] - 0.20) < 1e-12 and (r.trades["start"] < "2010-07-01").sum() == 30


def test_signal_day_move_is_not_captured():
    close, value, real = _panel(jump_day="2010-02-01")
    r = n1.run(close, value, real, n1.Cfg("A", cost=0.0))   # decides at the 02-01 close, buys at the 02-02 close
    assert abs(r.halves.iloc[0]["ret"]) < 1e-12
    close, value, real = _panel(jump_day="2010-02-01", after="2010-03-01")
    r = n1.run(close, value, real, n1.Cfg("A", cost=0.0))
    assert abs(r.halves.iloc[0]["ret"] - 0.10 / 30) < 1e-12   # only the later move, on one of 30 slots


def test_filler_bar_never_fills():
    close, value, real = _panel(jump_day="2010-02-01", after="2010-03-01")
    real.loc["2010-02-02":"2010-03-01", "T00.CA"] = False  # no real bar until after the second move
    r = n1.run(close, value, real, n1.Cfg("A", cost=0.0))
    assert abs(r.halves.iloc[0]["ret"]) < 1e-12
