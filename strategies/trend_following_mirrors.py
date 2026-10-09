"""4 Mirrors (trend following) behind the BaseStrategy interface.

ponytail: thin adapter — the rules stay in egx_4_mirrors_v3 (passes_screener + evaluate_4_mirrors), which the scanner,
dashboard, signal_engine, setup_builder, bot and optimizer also call; moving them here would touch every caller for no
behaviour change. Move them only when the engine itself runs strategies through the registry.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

import egx_4_mirrors_v3 as eng
from strategies.base import BUY, WAIT, BaseStrategy

WARMUP = 60   # first bar the engine's backtest evaluates (start_index), = ScreenConfig.min_rows


class TrendMirrors(BaseStrategy):
    """BUY on a bar when the screener passes and all 4 mirrors agree — exactly the engine backtest's entry condition
    (before risk sizing in build_trade_plan). It has no exit signal: exits are the engine's stop/target/trailing rules,
    so it never emits EXIT."""

    def __init__(self, screen: eng.ScreenConfig | None = None, signal: eng.SignalConfig | None = None):
        self.screen = screen or eng.ScreenConfig()
        self.signal = signal or eng.SignalConfig()

    def name(self) -> str:
        return "trend_mirrors"

    def get_params(self) -> dict[str, Any]:
        return {"screen": asdict(self.screen), "signal": asdict(self.signal), "warmup": WARMUP}

    def evaluate_bar(self, data: pd.DataFrame) -> int:
        """Current signal only, on a causal prefix with engine indicators.

        The caller owns indicator computation; rows begin at the original
        first bar and end at the closed decision bar. No execution or sizing.
        """
        if len(data) <= WARMUP:
            return WAIT
        return BUY if (eng.passes_screener(data, self.screen)[0]
                       and eng.evaluate_4_mirrors(data, self.signal)["signal"] == "BUY") else WAIT

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        # Indicators are causal (EMA/Wilder/rolling/cumsum over past bars only), so computing them once and slicing
        # equals the engine's per-window recompute; test_strategies.py checks this against the engine.
        ind = eng.calculate_indicators(data)
        out = pd.Series(WAIT, index=ind.index, dtype=int)
        for i in range(WARMUP, len(ind)):
            out.iloc[i] = self.evaluate_bar(ind.iloc[: i + 1])
        return out
