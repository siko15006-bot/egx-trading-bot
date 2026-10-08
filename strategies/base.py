"""Strategy interface for the strategy factory (Phase 1a: interface only — no walk-forward, OOS or Monte Carlo yet)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real
from typing import Any

import pandas as pd

BUY, WAIT, EXIT = 1, 0, -1


@dataclass(frozen=True)
class ExitPolicy:
    """Exit intent only; the future runner resolves None multipliers to 1.5/3.0."""

    stop_atr_mult: float | None = None
    target_atr_mult: float | None = None
    exit_on_signal: bool = False
    max_hold_bars: int | None = None

    def __post_init__(self) -> None:
        for name in ("stop_atr_mult", "target_atr_mult"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, Real)
                or not isfinite(value) or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive, or None")
        if not isinstance(self.exit_on_signal, bool):
            raise ValueError("exit_on_signal must be a boolean")
        if self.max_hold_bars is not None and (
            isinstance(self.max_hold_bars, bool)
            or not isinstance(self.max_hold_bars, Integral) or self.max_hold_bars <= 0
        ):
            raise ValueError("max_hold_bars must be a positive integer, or None")


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

    def exit_policy(self, data: pd.DataFrame, i: int) -> ExitPolicy | None:
        """Future runner hook on the signal prefix; None preserves the legacy path.

        Non-TrendMirrors strategies must override this before generic execution.
        This hook is not wired into the current engine.
        """
        return None
