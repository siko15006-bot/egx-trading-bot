from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import math

import pandas as pd
import pytest

import egx_4_mirrors_v3 as eng
import paper_trading as paper
import auto_sim
import backtest_optimizer as optimizer
from fees_config import order_fees, round_trip_fees


@pytest.mark.parametrize('value, expected', [(1000, 4.75), (5000, 11.75), (50000, 92), (500000, 902)])
def test_order_fee_tariff(value, expected):
    assert sum(order_fees(value).values()) == pytest.approx(expected)


@pytest.mark.parametrize('value', [1000, 5000, 50000, 500000])
@pytest.mark.parametrize('t0', [False, True])
def test_fee_consistency_across_paths(tmp_path, value, t0):
    risk = eng.RiskConfig(capital_gains_tax_pct=0)
    entered = datetime(2026, 7, 1, 12, tzinfo=ZoneInfo('Africa/Cairo'))
    exited = entered + timedelta(hours=1) if t0 else entered + timedelta(days=1)
    # Ten shares; buy and sell notionals match the stated test value.
    price = value / 10
    tid = paper.add_paper_trade(paper.PaperTradeInput('COMI', entered, price, 10, price * .9, price * 1.2), tmp_path / 'paper.db')
    result = paper.close_paper_trade(tid, exited, price, tmp_path / 'paper.db', risk=risk)
    expected_fees = round_trip_fees(value, value, same_session=t0)
    assert result['pnl_egp'] == pytest.approx(-expected_fees)
    assert eng.net_trade_pnl(price, price, 10, risk, same_session=t0) == pytest.approx(result['pnl_egp'])
    stored = paper.load_paper_trades(tmp_path / 'paper.db').iloc[0]
    assert stored['commission_egp'] == pytest.approx(expected_fees)


@pytest.mark.parametrize('value', [1000, 5000, 50000, 500000])
def test_optimizer_and_auto_sim_use_shared_fees(tmp_path, monkeypatch, value):
    risk = eng.RiskConfig(capital_gains_tax_pct=0)
    price = value / 10
    idx = pd.date_range('2026-07-01', periods=63, tz='Africa/Cairo')
    frame = pd.DataFrame({'Open':price, 'High':price, 'Low':price, 'Close':price, 'Volume':10000.}, index=idx)
    signals = pd.DataFrame([{'Ticker':'ZZZ.CA','Status':'BUY','Entry':price,'SL':price*.9,'TP':price*1.2,
                             'ATR':price*.05,'Shares':10,'RR_Net':2}])
    db = tmp_path / 'auto.db'
    auto_sim.open_new(signals, idx[60].date().isoformat(), db)
    auto_data = frame.iloc[60:].copy()
    auto_data.iloc[1, auto_data.columns.get_loc('High')] = price * 1.2
    monkeypatch.setattr(eng, 'with_dividends', lambda ticker, df: df)
    assert auto_sim.update_open({'ZZZ.CA':auto_data}, risk, db) == 1
    expected = eng.net_trade_pnl(price, price*1.2, 10, risk)
    assert auto_sim.load(db).iloc[0]['pnl_egp'] == pytest.approx(expected)
    monkeypatch.setattr(eng, 'calculate_indicators', lambda df: df)
    plan = {'entry':price,'stop':price*.9,'tp':price*1.2,'atr':price*.05,'shares':10,
            'position_value':value,'risk_egp':value*.1}
    monkeypatch.setattr(optimizer, '_mirrors_entry', lambda data, i, sc: plan if i == 60 else None)
    frame.loc[idx[61], 'High'] = price * 1.2
    for mode in ('engine', 'realistic'):
        result = optimizer.simulate(frame, optimizer.Scenario('fee-test', risk=risk), mode=mode)
        assert result['trades'].iloc[0]['pnl'] == pytest.approx(expected)
    monkeypatch.setattr(eng, 'passes_screener', lambda *args: (True, []))
    monkeypatch.setattr(eng, 'evaluate_4_mirrors', lambda *args: {'signal':'BUY'})
    monkeypatch.setattr(eng, 'build_trade_plan', lambda ticker, data, *args: eng.TradePlan(
        ticker, price, price*.9, price*1.2, price*.05, 10, value*.1, value*.2, 2, value, '') if len(data)==61 else None)
    assert eng.backtest(frame, eng.SystemConfig(risk=risk))['trades'].iloc[0]['PnL_EGP'] == pytest.approx(expected)


def test_fills_caps_and_validation():
    assert order_fees(5000, fills=[1000, 2000, 2000])['fra'] == 3
    assert order_fees(5000)['fra'] == 1
    capped = order_fees(100_000_000)
    assert (capped['egx'], capped['mcdr'], capped['insurance'], capped['fra']) == (5000, 5000, 5000, 250)
    for bad in (0, -1, math.nan, math.inf):
        with pytest.raises(ValueError):
            order_fees(bad)
    with pytest.raises(ValueError):
        order_fees(5000, fills=[1000])


def test_cairo_session_not_utc_day():
    assert not eng.same_session('2026-07-01T20:59:00Z', '2026-07-01T21:01:00Z')
    assert eng.same_session('2026-07-01T22:00:00Z', '2026-07-02T10:00:00+03:00')


def test_signal_bar_exit_is_not_scanned(monkeypatch):
    idx = pd.date_range('2026-07-01', periods=63, tz='Africa/Cairo')
    frame = pd.DataFrame({'Open':100., 'High':101., 'Low':99., 'Close':100., 'Volume':10000.}, index=idx)
    frame.loc[idx[60], ['High', 'Low']] = [120, 80]
    frame.loc[idx[61], 'High'] = 111
    monkeypatch.setattr(eng, 'calculate_indicators', lambda df: df)
    monkeypatch.setattr(eng, 'passes_screener', lambda *args: (True, []))
    monkeypatch.setattr(eng, 'evaluate_4_mirrors', lambda *args: {'signal':'BUY'})
    monkeypatch.setattr(eng, 'build_trade_plan', lambda ticker, df, *args: eng.TradePlan(
        ticker, 100, 90, 110, 5, 10, 100, 100, 1, 1000, '') if len(df)==61 else None)
    result = eng.backtest(frame, eng.SystemConfig())
    trade = result['trades'].iloc[0]
    assert trade['Exit_Date'] == idx[61]
    assert trade['Exit_Reason'] == 'TP'
