"""Synthetic checks for C; never opens production data or databases."""
import hashlib

import numpy as np
import pandas as pd
import pytest

import egx_4_mirrors_v3 as eng
from strategies.base import BaseStrategy, BUY, WAIT, ExitPolicy
from strategies import TrendMirrors
from test_strategies import _fixture
from validation.runner import ContractError, run, TRADE_COLUMNS


def bars():
    d = pd.DataFrame({"Open": 100., "High": 101., "Low": 99.,
                      "Close": 100., "Volume": 100_000.},
                     index=pd.date_range("2026-01-01", periods=26))
    # Signal 20, entry 21; entry-bar touches must not close the trade.
    d.iloc[21, d.columns.get_loc("High")] = 120
    d.iloc[21, d.columns.get_loc("Low")] = 80
    d.iloc[22, d.columns.get_loc("High")] = 110
    return d


class Probe(BaseStrategy):
    def __init__(self, policy=ExitPolicy()):
        self.policy = policy
        self.calls = []
        self.prefixes = []

    def name(self):
        return "probe"

    def get_params(self):
        return {}

    def generate_signals(self, data):
        self.prefixes.append(data.index.copy())
        signals = pd.Series(WAIT, index=data.index, dtype=int)
        if len(data) > 20:
            signals.iloc[20] = BUY
        return signals

    def exit_policy(self, data, i):
        self.calls.append((i, data.copy()))
        return self.policy


def execute(strategy, data, **kwargs):
    return run(strategy, {"SYNTH": data}, eng.SystemConfig(),
               dataset_path="synthetic", dividend_mode="none", **kwargs)


def test_causal_prefix_timing_and_policy_once(monkeypatch):
    d, s = bars(), Probe()
    seen = []
    original = eng.simulate_trade

    def trace(data, i, stop, target, atr, breaks=None, **kw):
        seen.append((i, kw, atr, stop, target))
        return original(data, i, stop, target, atr, breaks, **kw)

    monkeypatch.setattr(eng, "simulate_trade", trace)
    result = execute(s, d)
    assert len(result.trades) == 1
    t = result.trades.iloc[0]
    assert (t.Signal_Index, t.Entry_Index, t.Exit_Index, t.Exit_Scan_Start) == (20, 21, 22, 22)
    assert t.Entry == d.Close.iloc[21]
    assert t.Exit_Reason == "TP"
    assert len(s.calls) == 1
    i, prefix = s.calls[0]
    assert i == len(prefix) - 1
    pd.testing.assert_series_equal(prefix.iloc[i], eng.calculate_indicators(d).iloc[20])
    pd.testing.assert_frame_equal(prefix, eng.calculate_indicators(d).iloc[:i + 1])
    for prefix_index in s.prefixes:
        assert prefix_index.equals(d.index[:len(prefix_index)])
    assert seen[0][1] == {"allow_trailing": False}
    assert seen[0][2] == eng.calculate_indicators(d).ATR.iloc[20]
    assert t.Stop == t.Entry - 1.5 * seen[0][2]
    assert t.Target == t.Entry + 3 * seen[0][2]


def test_future_mutation_does_not_change_signal_or_policy():
    d = bars()
    changed = d.copy()
    changed.iloc[21:, changed.columns.get_indexer(["Open", "High", "Low", "Close"])] *= 1.05
    a, b = Probe(), Probe()
    execute(a, d)
    execute(b, changed)
    pd.testing.assert_frame_equal(a.calls[0][1], b.calls[0][1])
    full = Probe().generate_signals(d)
    for i in range(len(d)):
        assert full.iloc[i] == Probe().generate_signals(d.iloc[:i + 1]).iloc[-1]


def test_future_indicator_metadata_is_not_exposed():
    class MetadataProbe(Probe):
        def generate_signals(self, data):
            if len(data) <= 21:
                assert "intraday" not in data.attrs
                assert not data["Intraday_So_Far"].dropna().any()
                assert "future_info" not in data.attrs
                assert "Future_Close" not in data
            return super().generate_signals(data)
    d = bars().assign(Future_Close=9000., ATR=9000.)
    d.attrs["future_info"] = "leaked"
    idx = d.index.to_list()
    idx[-1] = idx[-2] + pd.Timedelta(hours=1)
    d.index = pd.DatetimeIndex(idx)
    execute(MetadataProbe(), d)


def test_early_buy_does_not_call_policy_before_indicator_readiness():
    class EarlyBuy(Probe):
        def generate_signals(self, data):
            signals = super().generate_signals(data)
            if len(data) > 1:
                signals.iloc[1] = BUY
            return signals

        def exit_policy(self, data, i):
            assert np.isfinite(data.ATR.iloc[-1]) and data.ATR.iloc[-1] > 0
            assert np.isfinite(data.Volume_SMA20.iloc[-1]) and data.Volume_SMA20.iloc[-1] > 0
            return super().exit_policy(data, i)
    strategy = EarlyBuy()
    assert execute(strategy, bars().iloc[:3]).trades.empty
    assert len(strategy.calls) == 0
    result = execute(strategy, bars())
    assert result.trades.Signal_Index.tolist() == [20]
    assert len(strategy.calls) == 1
    assert [i for i, _ in strategy.calls] == [20]


@pytest.mark.parametrize("kind", ["filler", "terminal", "invalid_entry"])
def test_ineligible_signal_does_not_call_policy(kind):
    d = bars()
    if kind == "filler":
        d.iloc[20, d.columns.get_loc("Volume")] = 0.
    elif kind == "terminal":
        d = d.iloc[:22].copy()
    else:
        d.iloc[21, d.columns.get_loc("Close")] = 0.
    strategy = Probe()
    if kind == "invalid_entry":
        # Input validation fails before any strategy policy is evaluated.
        with pytest.raises(ValueError, match="invalid numeric OHLCV"):
            execute(strategy, d)
    else:
        assert execute(strategy, d).trades.empty
    assert strategy.calls == []


def test_dividend_none_ignores_supplied_amounts_without_mutating_input(monkeypatch):
    d = bars()
    d["Dividends"] = 50.
    before = d.copy(deep=True)
    monkeypatch.setattr(eng, "with_dividends", lambda *a: pytest.fail("Adjusted prices must not load dividends"))
    monkeypatch.setattr(eng, "dividends_between", lambda *a: pytest.fail("none must bypass dividend calculation"))
    result = execute(Probe(), d)
    assert result.trades.Div_PS.tolist() == [0.]
    without_dividends = execute(Probe(), d.drop(columns="Dividends"))
    pd.testing.assert_frame_equal(result.trades, without_dividends.trades)
    assert "Dividends" in d and (d.Dividends == 50.).all()
    pd.testing.assert_frame_equal(d, before)
    legacy = run(TrendMirrors(), {"SYNTH": _fixture(1).assign(Dividends=50.)},
                 eng.SystemConfig(), dataset_path="data_2019_2026_wf")
    assert len(legacy.trades) > 0
    assert (legacy.trades.Div_PS == 0).all()


def test_no_dividend_column_is_added_to_raw_input():
    raw = bars()
    before = raw.copy(deep=True)
    execute(Probe(), raw)
    assert "Dividends" not in raw.columns
    pd.testing.assert_frame_equal(raw, before)


@pytest.mark.parametrize("multiple", [50., 100.])
def test_nonpositive_stop_aborts_run(multiple):
    with pytest.raises(ContractError, match="resolved stop/target"):
        execute(Probe(ExitPolicy(stop_atr_mult=multiple)), bars())


def test_large_atr_default_stop_aborts_without_partial_result(monkeypatch, tmp_path):
    import validation.runner as runner
    good = bars()
    bad = bars().assign(High=140., Low=60.)
    atr = eng.calculate_indicators(bad).ATR.iloc[20]
    assert bad.Close.iloc[21] - 1.5 * atr < 0
    completed = []
    original = eng.simulate_trade

    def trace(*args, **kwargs):
        outcome = original(*args, **kwargs)
        if outcome["status"] == "closed":
            completed.append(outcome)
        return outcome

    monkeypatch.setattr(eng, "simulate_trade", trace)
    monkeypatch.setattr(runner, "RunResult", lambda *a, **k: pytest.fail("Partial result returned"))
    monkeypatch.chdir(tmp_path)
    result = None
    with pytest.raises(ContractError, match="B_BAD: resolved stop/target"):
        result = runner.run(Probe(), {"A_OK": good, "B_BAD": bad}, eng.SystemConfig(),
                            dataset_path="synthetic", dividend_mode="none")
    assert len(completed) == 1
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_add_counts_ex_date_only_while_held():
    d = bars().assign(Dividends=0.)
    d.iloc[21, d.columns.get_loc("Dividends")] = 10.
    d.iloc[22, d.columns.get_loc("Dividends")] = 2.
    r = run(Probe(), {"SYNTH": d}, eng.SystemConfig(), dataset_path="synthetic", dividend_mode="add")
    assert r.trades.Div_PS.tolist() == [2.]


@pytest.mark.parametrize("policy,error", [(None, ContractError),
    (ExitPolicy(exit_on_signal=True), NotImplementedError),
    (ExitPolicy(max_hold_bars=2), NotImplementedError)])
def test_contract_fail_fast_no_result(policy, error):
    with pytest.raises(error):
        execute(Probe(policy), bars())


def test_fail_fast_even_after_an_earlier_trade_completed():
    class LateUnsupported(Probe):
        def generate_signals(self, data):
            signals = super().generate_signals(data)
            if len(data) > 23:
                signals.iloc[23] = BUY
            return signals

        def exit_policy(self, data, i):
            self.calls.append(i)
            return ExitPolicy() if i == 20 else ExitPolicy(max_hold_bars=2)
    strategy = LateUnsupported()
    with pytest.raises(NotImplementedError):
        execute(strategy, bars())
    assert strategy.calls == [20, 23]


def test_runner_uses_shared_sizing_helper(monkeypatch):
    calls = []
    def size(entry, risk_per_share, avg_volume, risk_cfg):
        calls.append((entry, risk_per_share, avg_volume, risk_cfg))
        return 3
    monkeypatch.setattr(eng, "position_size", size)
    r = execute(Probe(), bars())
    assert len(calls) == 1 and r.trades.Shares.tolist() == [3]
    assert calls[0][0:3] == (100., 3., 100_000.)


def test_determinism_open_independence_and_fixed_empty_schema():
    d = bars()
    a, b = execute(Probe(), d), execute(Probe(), d)
    assert a.trades.to_json(date_format="iso", double_precision=15) == b.trades.to_json(date_format="iso", double_precision=15)
    assert a.metadata == b.metadata
    pd.testing.assert_frame_equal(a.cancelled_trades, b.cancelled_trades)
    pd.testing.assert_frame_equal(a.equity_curve["SYNTH"], b.equity_curve["SYNTH"])
    changed = d.assign(Open=np.arange(len(d)) * 1000.)
    pd.testing.assert_frame_equal(a.trades, execute(Probe(), changed).trades)
    empty = execute(Probe(), d.iloc[:10])
    assert empty.trades.empty and list(empty.trades) == TRADE_COLUMNS


@pytest.mark.parametrize("kind", ["touch", "gap", "filler", "cancel"])
def test_trailing_isolation_when_no_trailing_trigger(kind):
    d = bars().iloc[20:24].copy()
    d.iloc[1, d.columns.get_loc("High")] = 101.
    d.iloc[1, d.columns.get_loc("Low")] = 99.
    d.iloc[2, d.columns.get_loc("High")] = 101.
    if kind == "touch":
        d.iloc[2, d.columns.get_loc("Low")] = 94.
    elif kind == "gap":
        d.iloc[2, d.columns.get_indexer(["High", "Low", "Close"])] = [92., 89., 90.]
    elif kind == "filler":
        d.iloc[2, d.columns.get_loc("Volume")] = 0.
    else:
        d.iloc[2, d.columns.get_indexer(["High", "Low", "Close"])] = [71., 69., 70.]
    default = eng.simulate_trade(d, 0, 95., 120., 2.)
    assert default == eng.simulate_trade(d, 0, 95., 120., 2., allow_trailing=True)
    assert default == eng.simulate_trade(d, 0, 95., 120., 2., allow_trailing=False)


def test_trailing_flag_disables_stop_movement_only():
    d = bars().iloc[:4].copy()
    d.iloc[2, d.columns.get_indexer(["High", "Low", "Close"])] = [105., 101., 104.]
    d.iloc[3, d.columns.get_indexer(["High", "Low", "Close"])] = [103., 101., 102.]
    enabled = eng.simulate_trade(d, 0, 95., 120., 2.)
    disabled = eng.simulate_trade(d, 0, 95., 120., 2., allow_trailing=False)
    assert enabled["reason"] == "TRAIL_SL" and enabled["stop"] == 102.
    assert disabled["reason"] == "END" and disabled["stop"] == 95.


def test_cancelled_trades_separate_and_no_last_bar_entry():
    d = bars()
    d.iloc[22, d.columns.get_indexer(["High", "Low", "Close"])] = [71., 69., 70.]
    r = execute(Probe(), d)
    assert r.trades.empty and len(r.cancelled_trades) == 1
    assert execute(Probe(), bars().iloc[:22]).trades.empty


def assert_legacy_trade_regression(monkeypatch):
    d, cfg = _fixture(1), eng.SystemConfig()
    baseline = eng.backtest(d, cfg)
    assert len(baseline["trades"]) == 3
    # Frozen before C (HEAD e7ec64b), not computed from the runner.
    assert hashlib.sha256(baseline["trades"].to_json(date_format="iso", double_precision=15).encode()).hexdigest() == "35a9a938dd7b3fe0e67e1b53944b3755a61d1b5a9891f133636f659b7827259e"
    monkeypatch.setattr(TrendMirrors, "exit_policy", lambda *a: pytest.fail("Legacy must bypass exit_policy"))
    r = run(TrendMirrors(), {"BACKTEST": d}, cfg, dataset_path="synthetic", dividend_mode="none")
    pd.testing.assert_frame_equal(r.trades[list(baseline["trades"])].reset_index(drop=True), baseline["trades"].reset_index(drop=True))
    for _, t in r.trades.iterrows():
        plan = eng.build_trade_plan("BACKTEST", eng.calculate_indicators(d).iloc[:int(t.Signal_Index) + 1], cfg.signal, cfg.risk)
        assert (t.Stop, t.Target, t.Shares, t.Position_Value) == (plan.stop_loss, plan.take_profit, plan.shares, plan.position_value)
    broken = d.copy()
    broken.iloc[114, broken.columns.get_indexer(["Open", "High", "Low", "Close"])] *= 1.6
    baseline_cancel = eng.backtest(broken, cfg)["data_break_trades"]
    assert len(baseline_cancel) == 1
    assert baseline_cancel.Break_Date.iloc[0] == broken.index[114]
    cancelled = run(TrendMirrors(), {"BACKTEST": broken}, cfg,
                    dataset_path="synthetic", dividend_mode="none").cancelled_trades
    pd.testing.assert_frame_equal(cancelled[list(baseline_cancel)].reset_index(drop=True),
                                  baseline_cancel.reset_index(drop=True))


def test_unknown_folder_requires_mode_and_bad_signal_contract():
    with pytest.raises(ValueError, match="unknown data folder"):
        run(Probe(), {"SYNTH": bars()}, eng.SystemConfig(), dataset_path="synthetic")
    class Invalid(Probe):
        def generate_signals(self, data):
            return pd.Series([7] * len(data), index=data.index)
    with pytest.raises(ContractError):
        execute(Invalid(), bars())
