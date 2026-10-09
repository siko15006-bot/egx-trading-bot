"""Two explicitly labelled execution paths, sharing existing engine mathematics.

Gross results require a separate run with zero fees, slippage and taxes.
Equity curves are per-stock closed-trade diagnostics, not a shared account.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from math import isfinite
from pathlib import Path

import pandas as pd

import egx_4_mirrors_v3 as eng
from strategies.base import BUY, WAIT, EXIT, BaseStrategy, ExitPolicy
from strategies.trend_following_mirrors import TrendMirrors, WARMUP


class ContractError(ValueError):
    """Strategy output violates the runner contract."""


TRADE_COLUMNS = [
    "Ticker", "Signal_Date", "Entry_Date", "Exit_Date", "Signal_Index",
    "Entry_Index", "Exit_Index", "Exit_Scan_Start", "Entry", "Exit",
    "Stop", "Target", "Final_Stop", "ATR", "Shares", "Position_Value",
    "Div_PS", "PnL_EGP", "PnL_%", "R", "Exit_Reason", "Status", "Path",
]
CANCEL_COLUMNS = ["Ticker", "Signal_Date", "Entry_Date", "Break_Date",
                  "Entry", "Close_Before", "Close_At_Break", "Path"]


@dataclass
class RunResult:
    trades: pd.DataFrame
    cancelled_trades: pd.DataFrame
    equity_curve: dict[str, pd.DataFrame]
    metadata: dict


def run(strategy: BaseStrategy, data_map: dict[str, pd.DataFrame], cfg: eng.SystemConfig,
        *, dataset_path: str | Path, dividend_mode: str | None = None) -> RunResult:
    """Run only; no file writes. Errors abort without returning partial results.

    Folder provenance is required for resolve_dividend_mode protection. In add
    mode a supplied Dividends column is authoritative; otherwise with_dividends
    supplies it. In none mode even a supplied column is ignored on a copy.
    """
    if not isinstance(strategy, BaseStrategy):
        raise TypeError("strategy must be a BaseStrategy instance")
    mode, provenance = eng.resolve_dividend_mode(dataset_path, dividend_mode)
    # Mirrors plans are mirror-specific: None is NOT a dispatch sentinel.
    is_legacy = isinstance(strategy, TrendMirrors)
    # Subclasses may override generate_signals; preserve their existing path.
    fast_legacy = type(strategy) is TrendMirrors
    path = "legacy-path" if is_legacy else "new-path"
    risk = cfg.risk
    rows, cancellations, curves, fingerprints = [], [], {}, {}
    for ticker in sorted(data_map):
        raw = data_map[ticker]
        eng._require_ohlcv(raw)
        if not raw.index.is_unique or not raw.index.is_monotonic_increasing:
            raise ValueError(f"{ticker}: dates must be unique and increasing")
        # Rebuild engine indicators; caller-supplied derived columns/attrs may
        # have been calculated using future rows.
        source = raw.loc[:, list(eng.REQUIRED_COLUMNS) + (["Dividends"] if "Dividends" in raw else [])].copy()
        source.attrs.clear()
        schema = repr((list(source.columns), [str(t) for t in source.dtypes], str(source.index.dtype)))
        fingerprints[ticker] = hashlib.sha256(schema.encode() + pd.util.hash_pandas_object(source, index=True).values.tobytes()).hexdigest()
        data = eng.calculate_indicators(source)
        if not data.index.equals(raw.index):
            raise ValueError(f"{ticker}: invalid OHLCV rows would change bar indices")
        if (not data[list(eng.REQUIRED_COLUMNS)].map(isfinite).all().all()
                or (data.Close <= 0).any() or (data.Volume < 0).any()
                or (data.High < data.Low).any()):
            raise ValueError(f"{ticker}: invalid numeric OHLCV")
        if mode == "none":
            data = data.drop(columns="Dividends", errors="ignore")
        elif "Dividends" not in data:
            data = eng.with_dividends(ticker, data)
        if "Dividends" in data:
            amounts = pd.to_numeric(data["Dividends"], errors="coerce")
            if not amounts.map(lambda x: isfinite(x) and x >= 0).all():
                raise ValueError(f"{ticker}: dividends must be finite and non-negative")
            data["Dividends"] = amounts
        breaks = eng.data_breaks(data)
        start = WARMUP if is_legacy else 0
        i, equity = start, risk.capital
        events = {data.index[start]: equity} if len(data) > start else {}
        while i < len(data) - 1:
            if fast_legacy:
                # Indicators are prefix-invariant; only the current closed bar
                # is evaluated. Defensive copies prevent strategy mutation.
                window = data.iloc[:i + 1].copy()
                signal = strategy.evaluate_bar(window.copy())
                if signal not in (BUY, WAIT, EXIT):
                    raise ContractError(f"{ticker}: evaluate_bar must return BUY/WAIT/EXIT")
            else:
                # ponytail: generic/subclass history evaluation stays O(n^2);
                # optimize separately against its own pre-change baseline.
                prefix = data.loc[:, list(eng.REQUIRED_COLUMNS) + (["Dividends"] if "Dividends" in data else [])].iloc[:i + 1].copy()
                prefix.attrs.clear()
                window = eng.calculate_indicators(prefix)
                signals = strategy.generate_signals(window.copy())
                if (not isinstance(signals, pd.Series) or not signals.index.equals(window.index)
                        or not signals.isin([BUY, WAIT, EXIT]).all()):
                    raise ContractError(f"{ticker}: signals must align with the prefix and contain BUY/WAIT/EXIT")
                signal = signals.iloc[-1]
            if signal != BUY:
                i += 1
                continue
            if is_legacy:
                plan = eng.build_trade_plan(ticker, window, strategy.signal, risk)
                if plan is None:
                    i += 1
                    continue
                stop, target, atr, shares = plan.stop_loss, plan.take_profit, plan.atr, plan.shares
                position_value, risk_amount = plan.position_value, plan.risk_egp
            else:
                # No final-bar entry: it would force END liquidation on entry.
                if i + 2 >= len(data):
                    i += 1
                    continue
                atr = float(window.ATR.iloc[-1])
                avg_volume = float(window.Volume_SMA20.iloc[-1])
                entry = float(data.Close.iloc[i + 1])
                if not all(isfinite(x) and x > 0 for x in (atr, avg_volume, entry)) or eng.is_filler(window.iloc[-1]):
                    i += 1
                    continue
                policy = strategy.exit_policy(window.copy(), i)
                if not isinstance(policy, ExitPolicy):
                    raise ContractError(f"{ticker}: non-TrendMirrors exit_policy must return ExitPolicy, not None")
                if policy.exit_on_signal or policy.max_hold_bars is not None:
                    raise NotImplementedError("exit_on_signal/max_hold_bars are not implemented in C")
                stop_mult = 1.5 if policy.stop_atr_mult is None else policy.stop_atr_mult
                target_mult = 3.0 if policy.target_atr_mult is None else policy.target_atr_mult
                stop, target = entry - stop_mult * atr, entry + target_mult * atr
                if stop <= 0 or not all(isfinite(x) for x in (stop, target)):
                    raise ContractError(f"{ticker}: resolved stop/target must be finite positive prices")
                shares = eng.position_size(entry, entry - stop, avg_volume, risk)
                if shares <= 0:
                    i += 1
                    continue
                position_value, risk_amount = entry * shares, (entry - stop) * shares
            outcome = eng.simulate_trade(data, i, stop, target, atr, breaks, allow_trailing=is_legacy)
            if outcome["status"] in ("pending", "skipped"):
                i += 1
                continue
            e = outcome["entry_index"]
            if outcome["status"] == "cancelled":
                j = outcome["break_index"]
                cancellations.append(dict(Ticker=ticker, Signal_Date=data.index[i], Entry_Date=data.index[e],
                    Break_Date=data.index[j], Entry=outcome["entry"], Close_Before=float(data.Close.iloc[j - 1]),
                    Close_At_Break=float(data.Close.iloc[j]), Path=path))
                i = j
                continue
            j, entry, exit_price = outcome["exit_index"], outcome["entry"], float(outcome["exit"])
            div_ps = eng.dividends_between(data, e, j) if mode == "add" else 0.0
            pnl = eng.net_trade_pnl(entry, exit_price, shares, risk, div_ps,
                                    same_session=eng.same_session(data.index[e], data.index[j]))
            equity += pnl
            events[data.index[j]] = equity
            rows.append(dict(Ticker=ticker, Signal_Date=data.index[i], Entry_Date=data.index[e],
                Exit_Date=data.index[j], Signal_Index=i, Entry_Index=e, Exit_Index=j, Exit_Scan_Start=e + 1,
                Entry=entry, Exit=exit_price, Stop=stop, Target=target, Final_Stop=outcome["stop"], ATR=atr,
                Shares=shares, Position_Value=position_value, Div_PS=div_ps, PnL_EGP=pnl,
                **{"PnL_%": pnl / position_value * 100}, R=pnl / risk_amount,
                Exit_Reason=outcome["reason"],
                Status="liquidated" if outcome["status"] == "open" else "closed", Path=path))
            i = max(j + 1, i + 1)
        curve = pd.Series(events, dtype=float).reindex(data.index[start:]).ffill()
        curves[ticker] = pd.DataFrame({"Closed_Trade_Equity": curve,
                                     "Drawdown": curve / curve.cummax() - 1})
    return RunResult(pd.DataFrame(rows, columns=TRADE_COLUMNS),
                     pd.DataFrame(cancellations, columns=CANCEL_COLUMNS), curves,
                     dict(strategy=strategy.name(), strategy_params=strategy.get_params(), path=path,
                          dataset_path=str(dataset_path), dividend_mode=mode, dividend_provenance=provenance,
                          risk=asdict(risk), equity_basis="per-stock closed-trade diagnostic; not shared-account",
                          input_fingerprints=fingerprints,
                          terminal_entry_policy="legacy unchanged; new path requires a post-entry bar"))
