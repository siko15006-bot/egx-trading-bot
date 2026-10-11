"""L1 signal: past data only, filler bars ignored."""
import numpy as np
import pandas as pd

import research_l1_lowvol as l1


def test_score_uses_only_the_past_and_real_bars():
    idx = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, (400, 2)), axis=0)), index=idx, columns=["A", "B"])
    real = pd.DataFrame(True, index=idx, columns=close.columns)
    s = l1.lowvol_score(close, real)
    future = close.copy()
    future.iloc[301:] *= 3                          # change only the future
    assert s.iloc[:301].equals(l1.lowvol_score(future, real).iloc[:301])
    assert s.iloc[199].isna().all() and s.iloc[200].notna().all()   # >= 200 real returns in the 252 window
    filler = close.copy()
    filler.iloc[100:300:2, 0] = np.nan             # half the bars are fillers (no trade): fewer than 200 real returns
    real2 = real.copy()
    real2.iloc[100:300:2, 0] = False
    assert l1.lowvol_score(filler, real2).iloc[300, 0] != l1.lowvol_score(close, real).iloc[300, 0]
