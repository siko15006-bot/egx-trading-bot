"""Strategy factory, Phase 1a: the interface and the 4 Mirrors adapter must reproduce the engine exactly."""
import numpy as np
import pandas as pd

import egx_4_mirrors_v3 as eng
from strategies import BUY, EXIT, STRATEGIES, WAIT, BaseStrategy, TrendMirrors


def _fixture(seed: int, n: int = 220) -> pd.DataFrame:
    """Synthetic daily bars with trends, pullbacks and volume bursts, so all 4 mirrors line up on some bars."""
    rng = np.random.default_rng(seed)
    drift = np.where((np.arange(n) // 40) % 2 == 0, 0.004, -0.002)
    close = 20 * np.exp(np.cumsum(drift + rng.normal(0, 0.015, n)))
    vol = rng.integers(400_000, 900_000, n).astype(float)
    vol[rng.random(n) < 0.15] *= 3
    idx = pd.date_range("2026-01-04 12:00", periods=n, freq="D", tz=eng.CAIRO_TZ).tz_convert("UTC")  # noon: no DST gap
    return pd.DataFrame({"Open": close, "High": close * 1.012, "Low": close * 0.988, "Close": close, "Volume": vol},
                        index=idx)


def _engine_signals(data: pd.DataFrame) -> pd.Series:
    """The engine backtest's own entry test, bar by bar on the raw window (egx_4_mirrors_v3.backtest)."""
    cfg = eng.SystemConfig()
    out = pd.Series(WAIT, index=data.index, dtype=int)
    for i in range(60, len(data)):
        w = data.iloc[: i + 1]
        if eng.passes_screener(w, cfg.screen)[0] and eng.evaluate_4_mirrors(w, cfg.signal)["signal"] == "BUY":
            out.iloc[i] = BUY
    return out


def test_registry_and_interface() -> None:
    assert STRATEGIES == {"trend_mirrors": TrendMirrors}
    s = STRATEGIES["trend_mirrors"]()
    assert isinstance(s, BaseStrategy) and s.name() == "trend_mirrors"
    p = s.get_params()
    assert p["signal"]["min_adx"] == eng.SignalConfig().min_adx and p["screen"]["min_rows"] == 60 and p["warmup"] == 60


def test_trend_mirrors_signals_equal_engine() -> None:
    buys = 0
    for seed in (1, 2, 3, 4):
        d = _fixture(seed)
        got, want = TrendMirrors().generate_signals(d), _engine_signals(d)
        pd.testing.assert_series_equal(got, want)
        assert set(got.unique()) <= {BUY, WAIT} and EXIT not in got.values   # no exit signal: exits are the engine's
        buys += int((got == BUY).sum())
    assert buys > 0   # the fixture really produces BUY bars (not a vacuous comparison)


def test_every_backtest_trade_starts_on_a_buy_signal() -> None:
    for seed in (1, 2, 3, 4):
        d = _fixture(seed)
        sig = TrendMirrors().generate_signals(d)
        trades = eng.backtest(d, eng.SystemConfig())["trades"]
        assert all(sig.loc[t] == BUY for t in (trades["Signal_Date"] if len(trades) else []))
