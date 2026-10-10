"""Development orchestration checks on synthetic inputs only."""
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

import egx_4_mirrors_v3 as eng
from strategies.base import BUY, WAIT
from validation.development import (
    LIMITS, WindowMirrors, cost_config, execute, load_local, load_settings,
    run_window, sha, windows,
)


CONFIG = Path(__file__).parent / "config/development_validation.json"


def bars():
    return pd.DataFrame(dict(Open=100., High=101., Low=99., Close=100., Volume=100000.),
                        index=pd.date_range("2025-01-01", periods=120, tz="UTC"))


def test_external_costs_reuse_config_and_reject_missing_fields():
    settings = load_settings(CONFIG)
    assert cost_config(settings, "net_assumption").risk.fees.brokerage_fixed_egp == 2
    assert cost_config(settings, "gross_zero_cost").risk.slippage_bps == 0
    changed = deepcopy(settings)
    changed["scenarios"]["net_assumption"]["fees"]["brokerage_fixed_egp"] = 7
    assert cost_config(changed, "net_assumption").risk.fees.brokerage_fixed_egp == 7
    del changed["scenarios"]["net_assumption"]["fees"]["fra_pct"]
    with pytest.raises(ValueError, match="Every FeesConfig"):
        cost_config(changed, "net_assumption")


def test_local_registry_has_raw_hashes_without_mutation(tmp_path):
    for number in range(9):
        bars().rename_axis("Date").to_csv(tmp_path / f"S{number}.csv")
    settings = load_settings(CONFIG)
    before = {str(p): sha(p) for p in tmp_path.glob("*.csv")}
    data, registry, protected = load_local(tmp_path, settings)
    assert len(data) == len(registry["files"]) == 9
    assert not registry["source_verified"] and not registry["licence_verified"]
    assert before == protected == {str(p): sha(p) for p in tmp_path.glob("*.csv")}


def test_explicit_universe_is_exact_and_preserves_zero_volume(tmp_path):
    settings = load_settings(CONFIG)
    settings["tickers"] = ["A", "B"]
    raw = bars()
    raw.iloc[3, raw.columns.get_loc("Volume")] = 0
    for ticker in settings["tickers"]:
        raw.rename_axis("Date").to_csv(tmp_path / f"{ticker}.csv")
    data, registry, _ = load_local(tmp_path, settings)
    assert set(data) == {"A", "B"}
    assert all(len(frame) == len(raw) and frame.Volume.iloc[3] == 0 for frame in data.values())
    assert len(registry["files"]) == 2
    settings["tickers"] = ["A", "C"]
    with pytest.raises(ValueError, match="exactly"):
        load_local(tmp_path, settings)
    settings["tickers"] = ["A", "A"]
    with pytest.raises(ValueError, match="unique"):
        load_local(tmp_path, settings)


def test_window_dates_are_nonoverlapping_half_open():
    configured = list(windows(load_settings(CONFIG)))
    assert len(configured) == 5
    assert all(left[3] == right[2] for left, right in zip(configured, configured[1:]))
    assert all(train < start < end for _, train, start, end in configured)


def test_future_changes_do_not_change_past_current_signals():
    raw = bars()
    changed = raw.copy()
    changed.loc[changed.index[90]:, ["Open", "High", "Low", "Close"]] *= 2
    cfg = eng.SystemConfig()
    start = raw.index[65]
    for end in (65, 70, 80):
        left = WindowMirrors(start, cfg).generate_signals(eng.calculate_indicators(raw.iloc[:end+1]))
        right = WindowMirrors(start, cfg).generate_signals(eng.calculate_indicators(changed.iloc[:end+1]))
        pd.testing.assert_series_equal(left, right)
    assert WindowMirrors(start, cfg).generate_signals(eng.calculate_indicators(raw.iloc[:65])).eq(WAIT).all()


def test_real_runner_respects_warmup_and_test_boundary(monkeypatch):
    raw = bars()
    start, end = raw.index[65], raw.index[90]
    monkeypatch.setattr(WindowMirrors, "evaluate_bar", lambda self, data: BUY)
    monkeypatch.setattr(eng, "evaluate_4_mirrors", lambda *a: {"signal": "BUY"})
    cfg = cost_config(load_settings(CONFIG), "gross_zero_cost")
    before = raw.copy()
    result = run_window({"S": raw}, cfg, "synthetic", "none", raw.index[0], start, end)
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade.Signal_Date == start and trade.Entry_Date == raw.index[66]
    assert trade.Exit_Date == raw.index[89] and trade.Exit_Reason == "END"
    changed = raw.copy()
    changed.loc[end:, ["Open", "High", "Low", "Close"]] *= 2
    again = run_window({"S": changed}, cfg, "synthetic", "none", raw.index[0], start, end)
    pd.testing.assert_frame_equal(result.trades, again.trades, check_exact=True)
    pd.testing.assert_frame_equal(raw, before)


def test_limits_and_output_guard(tmp_path):
    assert LIMITS.startswith("هذا العمل تطويري فقط على 9 أسهم محلية.")
    assert "P1B-STOP-ANCHOR" in LIMITS and "تنفيذ كامل" in LIMITS
    assert "مغلق كقرار مرجعي فقط" in LIMITS and "غير ممتثل" in LIMITS
    with pytest.raises(ValueError, match="outputs/"):
        execute(CONFIG, tmp_path / "not_allowed")
