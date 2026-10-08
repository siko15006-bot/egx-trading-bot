"""Byte-stable plan snapshots captured before the sizing extraction."""
import hashlib
import json
from dataclasses import asdict, replace

import pandas as pd
import pytest

import egx_4_mirrors_v3 as eng


CASES = {
    "default": {},
    "risk_bound": {"risk_pct": 0.0001},
    "capital_bound": {"max_position_pct": 0.001},
    "liquidity_bound": {"max_avg_volume_pct": 0.0001},
    "zero_shares": {"max_avg_volume_pct": 0.000001},
    "legacy_fee": {"round_trip_fee_pct": 0.003},
    "invalid_risk": {"atr_sl_mult": 0.0},
}


def _signal_row():
    # Precomputed synthetic indicators isolate plan construction from indicator math.
    return pd.DataFrame([{
        "Close": 10.0, "ATR": 1.0, "ADX": 30.0, "Volume": 200000,
        "EMA_50": 8.0, "EMA_20": 9.0, "EMA50_slope": 1.0,
        "RSI": 60.0, "MACD_Hist": 1.0, "Volume_SMA20": 100000.0,
        "OBV": 2.0, "OBV_SMA20": 1.0, "VWAP_ref": 9.0,
        "BB_Mid": 9.0, "ATR_Pct": 10.0, "BB_Width": 0.1,
    }])


def _plan_bytes(overrides):
    plan = eng.build_trade_plan("SYNTH", _signal_row(), eng.SignalConfig(),
                                replace(eng.RiskConfig(), **overrides))
    return json.dumps(asdict(plan) if plan is not None else None,
                      sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


# Filled from the unmodified engine before extraction, never regenerated in tests.
BEFORE_HASHES = {
    "default": "8099371c2f18a00e6068826e067d07133d2d3ea2143d9742c3031856e6be5396",
    "risk_bound": "b90d053d0e145303ccbbf271e350f47bb12a355f581dd7aaa6046c5b54f90c7d",
    "capital_bound": "94e1ea66c47eb93b0ed650293504cf699c3d67e448b8c334e0d6d00ec132615f",
    "liquidity_bound": "94e1ea66c47eb93b0ed650293504cf699c3d67e448b8c334e0d6d00ec132615f",
    "zero_shares": "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
    "legacy_fee": "a915ba238018b0c6c732dc9576767edbfdae576a651dcd9b1557647a993837ca",
    "invalid_risk": "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
}


@pytest.mark.parametrize("case", CASES)
def test_complete_plan_bytes_match_before_extraction(case):
    assert hashlib.sha256(_plan_bytes(CASES[case])).hexdigest() == BEFORE_HASHES[case]


@pytest.mark.parametrize("overrides,expected", [
    ({}, 666), ({"risk_pct": 0.0001}, 6),
    ({"max_position_pct": 0.001}, 10),
    ({"max_avg_volume_pct": 0.0001}, 10),
    ({"max_avg_volume_pct": 0.000001}, 0),
])
def test_shared_sizing_limits(overrides, expected):
    assert eng.position_size(10.0, 1.5, 100000.0,
                             replace(eng.RiskConfig(), **overrides)) == expected


@pytest.mark.parametrize("entry,risk_per_share,avg_volume,expected", [
    (5000.0, 1.5, 100000.0, 4),  # high price: position-value cap
    (10.0, 200.0, 100000.0, 5),  # large per-share risk: risk cap
    (10.0, 1.5, 150.0, 1),      # small volume: liquidity cap + floor
    (10.0, 1.5, 0.0, 0),
    (10.0, 1.5, 100.0, 1),
    (10.0, 1.5, 99.0, 0),
])
def test_price_risk_volume_boundaries(entry, risk_per_share, avg_volume, expected):
    assert eng.position_size(entry, risk_per_share, avg_volume, eng.RiskConfig()) == expected


def test_single_share_plan_is_not_skipped():
    risk = replace(eng.RiskConfig(), max_avg_volume_pct=0.00001)
    plan = eng.build_trade_plan("SYNTH", _signal_row(), eng.SignalConfig(), risk)
    assert plan is not None and plan.shares == 1


def test_zero_average_volume_returns_no_plan():
    data = _signal_row()
    data["Volume_SMA20"] = 0.0
    assert eng.evaluate_4_mirrors(data, eng.SignalConfig())["signal"] == "BUY"
    assert eng.build_trade_plan("SYNTH", data, eng.SignalConfig(), eng.RiskConfig()) is None


@pytest.mark.parametrize("atr_sl_mult", [0.0, -1.0])
def test_invalid_risk_is_rejected_before_sizing(monkeypatch, atr_sl_mult):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid risk must not reach division in position_size")

    monkeypatch.setattr(eng, "position_size", forbidden)
    risk = replace(eng.RiskConfig(), atr_sl_mult=atr_sl_mult)
    assert eng.build_trade_plan("SYNTH", _signal_row(), eng.SignalConfig(), risk) is None


@pytest.mark.parametrize("overrides,expected_limits", [
    ({"risk_pct": 0.0001}, [6, 2000, 1000]),
    ({"max_position_pct": 0.001}, [666, 10, 1000]),
    ({"max_avg_volume_pct": 0.0001}, [666, 2000, 10]),
])
def test_all_three_constraints_are_evaluated(monkeypatch, overrides, expected_limits):
    real_floor = eng.floor
    observed = []

    def record_floor(value):
        result = real_floor(value)
        observed.append(result)
        return result

    monkeypatch.setattr(eng, "floor", record_floor)
    size = eng.position_size(10.0, 1.5, 100000.0,
                             replace(eng.RiskConfig(), **overrides))
    assert observed == expected_limits
    assert size == min(expected_limits)


def test_legacy_runner_trade_match(monkeypatch):
    # C preserves the legacy branch; generic-vs-legacy parity is debt retirement,
    # not a claim that entry-relative and signal-relative stops are equivalent.
    from test_validation_runner import assert_legacy_trade_regression
    assert_legacy_trade_regression(monkeypatch)


@pytest.mark.skip(reason="Debt retirement: full trade identity between legacy and generic paths is not implemented; their stop anchors differ.")
def test_legacy_vs_new_path_trade_match():
    raise AssertionError("Must compare complete trades between both paths before retiring the two-path debt")
