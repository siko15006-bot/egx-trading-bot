"""Strategy interface for the strategy factory (Phase 1a: interface only — no walk-forward, OOS or Monte Carlo yet)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

BUY, WAIT, EXIT = 1, 0, -1


class BaseStrategy(ABC):
    """A strategy turns daily OHLCV into one signal per bar, computed only from bars up to and including that bar
    (the bar must be closed). Execution — entry at the next session's Close, stops, targets, fees, data breaks — stays
    in the engine (docs/execution_policy.md) and is the same for every strategy."""

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Series on data's index with BUY (1), WAIT (0) or EXIT (-1) per bar."""

    @abstractmethod
    def get_params(self) -> dict[str, Any]:
        """Every parameter that changes the signals, so a run can be reproduced."""

    @abstractmethod
    def name(self) -> str:
        """Registry key."""
