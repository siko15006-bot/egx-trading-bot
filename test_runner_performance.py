"""Performance invariants, without timing assertions or production data."""
import pandas as pd
import pytest

import egx_4_mirrors_v3 as eng
from strategies import TrendMirrors
from scripts.benchmark_legacy_runner import frozen_legacy
from test_strategies import _fixture
from validation.runner import run


def execute(strategy, raw, call=run):
    return call(strategy, {"SYNTH": raw}, eng.SystemConfig(),
                dataset_path="synthetic", dividend_mode="none")


def test_evaluate_bar_matches_frozen_signal_path():
    old_class, _ = frozen_legacy()
    raw = _fixture(1, n=130)
    raw.iloc[110, raw.columns.get_loc("Volume")] = 0
    index = raw.index.tolist()
    index[-1] = index[-2] + pd.Timedelta(hours=1)
    raw.index = pd.DatetimeIndex(index)
    want = old_class().generate_signals(raw)
    strategy = TrendMirrors()
    ind = eng.calculate_indicators(raw)
    got = pd.Series([strategy.evaluate_bar(ind.iloc[:i+1]) for i in range(len(ind))],
                    index=ind.index, dtype=int)
    pd.testing.assert_series_equal(got, want)


def test_one_indicator_calculation_and_one_current_bar_evaluation(monkeypatch):
    raw = _fixture(1, n=100)
    raw.iloc[-1, raw.columns.get_loc("Volume")] = 0
    raw["Future_Close"] = 9999.
    raw.attrs["future_info"] = "not for strategy"
    count, visited = [], []
    calculate = eng.calculate_indicators
    evaluate = TrendMirrors.evaluate_bar
    def counted(data):
        count.append(len(data))
        return calculate(data)
    def current(self, window):
        i = len(window)-1
        assert window.index.equals(raw.index[:i+1])
        assert "Future_Close" not in window and "future_info" not in window.attrs
        expected = calculate(raw[list(eng.REQUIRED_COLUMNS)].iloc[:i+1])
        pd.testing.assert_frame_equal(window, expected, check_exact=True)
        visited.append(i)
        return evaluate(self, window)
    monkeypatch.setattr(eng, "calculate_indicators", counted)
    monkeypatch.setattr(TrendMirrors, "evaluate_bar", current)
    monkeypatch.setattr(TrendMirrors, "generate_signals", lambda *a: pytest.fail("History must not be replayed"))
    execute(TrendMirrors(), raw)
    assert count == [len(raw)]
    assert visited and len(visited) == len(set(visited))


def test_full_synthetic_run_matches_frozen_legacy():
    old_class, old_run = frozen_legacy()
    raw = _fixture(1, n=130)
    want = execute(old_class(), raw, old_run)
    got = execute(TrendMirrors(), raw)
    pd.testing.assert_frame_equal(got.trades, want.trades, check_exact=True)
    pd.testing.assert_frame_equal(got.cancelled_trades, want.cancelled_trades, check_exact=True)
    pd.testing.assert_frame_equal(got.equity_curve["SYNTH"], want.equity_curve["SYNTH"], check_exact=True)
    assert got.metadata == want.metadata


def test_subclass_keeps_generate_signals_contract():
    class Custom(TrendMirrors):
        def generate_signals(self, data):
            self.called = True
            return pd.Series(0, index=data.index, dtype=int)
        def evaluate_bar(self, data):
            pytest.fail("Subclass must not be silently opted into the fast path")
    strategy = Custom()
    assert execute(strategy, _fixture(1, n=65)).trades.empty
    assert strategy.called


@pytest.mark.parametrize("case", ["zero_volume", "single_bar", "session_boundary"])
def test_minimal_edge_run_matches_frozen_legacy(case):
    raw = _fixture(1, n=65)
    if case == "zero_volume":
        raw.iloc[61, raw.columns.get_loc("Volume")] = 0
    elif case == "single_bar":
        raw = raw.iloc[:1].copy()
    else:
        index = pd.date_range("2026-01-01 12:00", periods=len(raw), tz="UTC").tolist()
        index[-2] = index[-3] + pd.Timedelta(hours=1)
        raw.index = pd.DatetimeIndex(index)
    old_class, old_run = frozen_legacy()
    want = execute(old_class(), raw, old_run)
    got = execute(TrendMirrors(), raw)
    pd.testing.assert_frame_equal(got.trades, want.trades, check_exact=True)
    pd.testing.assert_frame_equal(got.cancelled_trades, want.cancelled_trades, check_exact=True)
    pd.testing.assert_frame_equal(got.equity_curve["SYNTH"], want.equity_curve["SYNTH"], check_exact=True)
    assert got.metadata == want.metadata
