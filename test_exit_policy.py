"""Phase 1b exit intent contract; no runner or execution changes."""
from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from strategies import BaseStrategy, TrendMirrors
from strategies.base import ExitPolicy


def test_defaults_and_immutability():
    policy = ExitPolicy()
    assert policy.stop_atr_mult is None and policy.target_atr_mult is None
    assert policy.exit_on_signal is False and policy.max_hold_bars is None
    with pytest.raises(FrozenInstanceError):
        policy.stop_atr_mult = 2.0


def test_explicit_valid_policy():
    policy = ExitPolicy(1.5, 3.0, True, 10)
    assert (policy.stop_atr_mult, policy.target_atr_mult,
            policy.exit_on_signal, policy.max_hold_bars) == (1.5, 3.0, True, 10)


@pytest.mark.parametrize("field", ["stop_atr_mult", "target_atr_mult"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"),
                                  float("-inf"), True, False, "1.5"])
def test_invalid_multiplier(field, value):
    with pytest.raises(ValueError, match=field):
        ExitPolicy(**{field: value})


@pytest.mark.parametrize("value", [0, -1, 1.5, True, False, "10", float("nan")])
def test_invalid_hold_count(value):
    with pytest.raises(ValueError, match="max_hold_bars"):
        ExitPolicy(max_hold_bars=value)


@pytest.mark.parametrize("value", [0, 1, None, "true"])
def test_invalid_signal_flag(value):
    with pytest.raises(ValueError, match="exit_on_signal"):
        ExitPolicy(exit_on_signal=value)


def test_existing_strategy_inherits_noop_without_mutating_input():
    data = pd.DataFrame({"Close": [10.0]})
    before = data.copy(deep=True)
    strategy = TrendMirrors()
    assert "exit_policy" not in BaseStrategy.__abstractmethods__
    assert strategy.exit_policy(data, 0) is None
    pd.testing.assert_frame_equal(data, before)
