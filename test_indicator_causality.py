"""VWAP mode is chosen from history available at each real bar."""
import numpy as np
import pandas as pd

import egx_4_mirrors_v3 as eng


def bars(index):
    close = np.arange(len(index), dtype=float) + 100
    return pd.DataFrame({"Open": close, "High": close + 1,
                         "Low": close - 1, "Close": close, "Volume": 1000.0},
                        index=pd.DatetimeIndex(list(index)))


def assert_prefix_identity(raw):
    full = eng.calculate_indicators(raw)
    for length in range(1, len(raw) + 1):
        prefix = eng.calculate_indicators(raw.iloc[:length])
        pd.testing.assert_frame_equal(full.iloc[:length], prefix, check_exact=True)
        assert full.attrs == prefix.attrs
    return full


def test_intraday_first_bar_daily_then_second_bar_intraday():
    raw = bars(pd.date_range("2026-01-01 10:00", periods=4, freq="h", tz="UTC"))
    actual = assert_prefix_identity(raw)
    assert pd.isna(actual.VWAP_ref.iloc[0])
    pd.testing.assert_series_equal(actual.VWAP_ref.iloc[:1], actual.VWAP_20.iloc[:1], check_names=False)
    pd.testing.assert_series_equal(actual.VWAP_ref.iloc[1:], actual.VWAP_day.iloc[1:], check_names=False)
    assert actual.Intraday_So_Far.tolist() == [False, True, True, True]


def test_future_intraday_bar_does_not_change_historical_110_5():
    raw = bars(pd.date_range("2026-01-01 12:00", periods=30, tz="UTC"))
    future = bars([raw.index[-1] + pd.Timedelta(hours=1)])
    extended = pd.concat([raw, future])
    actual = assert_prefix_identity(extended)
    before = eng.calculate_indicators(raw)
    pd.testing.assert_frame_equal(actual.iloc[:len(raw)], before, check_exact=True)
    assert actual.VWAP_ref.iloc[20] == before.VWAP_ref.iloc[20] == 110.5


def test_mixed_daily_intraday_daily_mode_stays_intraday():
    daily = pd.date_range("2026-01-01 12:00", periods=30, tz="UTC")
    index = daily.tolist() + [daily[-1] + pd.Timedelta(hours=1)]
    index += pd.date_range("2026-01-31 12:00", periods=3, tz="UTC").tolist()
    actual = assert_prefix_identity(bars(index))
    assert not actual.Intraday_So_Far.iloc[:30].any()
    assert actual.Intraday_So_Far.iloc[30:].all()
    pd.testing.assert_series_equal(actual.VWAP_ref.iloc[31:], actual.VWAP_day.iloc[31:], check_names=False)


def test_future_filler_does_not_change_prefix_dtypes_or_activate_intraday():
    daily = pd.date_range("2026-01-01 12:00", periods=25, tz="UTC")
    raw = bars(daily.tolist() + [daily[-1] + pd.Timedelta(hours=1)])
    raw.iloc[-1, raw.columns.get_loc("Volume")] = 0
    raw.attrs["intraday"] = True
    actual = assert_prefix_identity(raw)
    assert not actual.Intraday_So_Far.dropna().any()
    assert pd.isna(actual.Intraday_So_Far.iloc[-1])
    assert "intraday" not in actual.attrs


def test_cairo_day_not_utc_day_controls_mode():
    raw = bars(pd.DatetimeIndex(["2026-01-01 23:00Z", "2026-01-02 00:00Z"]))
    actual = assert_prefix_identity(raw)
    assert actual.Intraday_So_Far.tolist() == [False, True]
    assert actual.VWAP_ref.iloc[1] == actual.VWAP_day.iloc[1]
