"""Local-only rolling development checks; no fitting, acceptance gate or downloads."""
from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import hashlib
import json
from math import isfinite
from pathlib import Path
import subprocess

import pandas as pd

import egx_4_mirrors_v3 as eng
from fees_config import FeesConfig
from strategies.base import WAIT
from strategies.trend_following_mirrors import TrendMirrors
from validation.runner import run


LIMITS = """هذا العمل تطويري فقط على 9 أسهم محلية.
- لا يثبت ترخيص البيانات ولا جودتها.
- لا يثبت امتثال سقف القيمة عند التنفيذ الفعلي؛ legacy غير ممتثل، وP1B-STOP-ANCHOR مغلق كقرار مرجعي فقط.
- لا يثبت إمكانية التنفيذ (لا سبريد، لا أمر محدد، لا مزاد).
- أي رقم صافٍ هو بافتراض تنفيذ كامل، وليس دليلاً على ميزة قابلة للتداول.
"""


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_settings(path):
    settings = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("dataset", "dividend_mode", "source_note", "windows", "risk", "scenarios"):
        if key not in settings:
            raise ValueError(f"Missing setting: {key}")
    windows = settings["windows"]
    for key in ("train_months", "test_months", "count", "min_trades"):
        if type(windows[key]) is not int or windows[key] <= 0:
            raise ValueError(f"{key} must be a positive integer")
    pd.Timestamp(windows["first_test_start"])
    if not settings["scenarios"]:
        raise ValueError("At least one explicit cost scenario is required")
    return settings


def cost_config(settings, name):
    scenario = settings["scenarios"][name]
    fee_names = {f.name for f in fields(FeesConfig)}
    if set(scenario["fees"]) != fee_names:
        raise ValueError("Every FeesConfig field must be supplied explicitly")
    risk = {**settings["risk"], **{k: v for k, v in scenario.items() if k != "fees"}}
    if set(risk) != {f.name for f in fields(eng.RiskConfig)} - {"fees"}:
        raise ValueError("Every RiskConfig field must be supplied explicitly")
    for key, value in risk.items():
        if key == "round_trip_fee_pct" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise ValueError(f"Invalid risk/cost value: {key}")
    if risk["capital"] <= 0 or risk["atr_sl_mult"] <= 0 or risk["reward_risk"] <= 0:
        raise ValueError("Capital and risk multipliers must be positive")
    for key in ("risk_pct", "max_position_pct", "max_avg_volume_pct", "capital_gains_tax_pct", "dividend_tax_pct"):
        if risk[key] > 1:
            raise ValueError(f"{key} must be a fraction, not a percentage number")
    return eng.SystemConfig(risk=eng.RiskConfig(**risk, fees=FeesConfig(**scenario["fees"])))


def load_local(dataset, settings):
    dataset = Path(dataset).resolve()
    if not dataset.is_dir():
        raise ValueError("Dataset must be an existing local folder")
    files = sorted(dataset.glob("*.csv"))
    tickers = settings.get("tickers")
    if tickers is not None:
        if (not isinstance(tickers, list) or not tickers
                or not all(isinstance(t, str) and t for t in tickers)
                or len(set(tickers)) != len(tickers)):
            raise ValueError("Tickers must be a nonempty unique list")
        if {p.stem for p in files} != set(tickers):
            raise ValueError("Dataset must match the explicit ticker list exactly")
    elif len(files) != 9:
        raise ValueError("Approved scope requires exactly 9 local ticker CSVs")
    before = {str(p): sha(p) for p in files}
    data = eng.load_data_map(dataset)
    records = []
    for ticker, frame in sorted(data.items()):
        if frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:
            raise ValueError(f"{ticker}: empty or invalid date index")
        records.append(dict(ticker=ticker, rows=len(frame), first=str(frame.index[0]),
                            last=str(frame.index[-1]), sha256=before[str(dataset / f"{ticker}.csv")]))
    return data, dict(folder=str(dataset), source_note=settings["source_note"],
                     source_verified=False, licence_verified=False, quality_verified=False,
                     dividend_mode=settings["dividend_mode"],
                     split_adjustment_verified=False, files=records), before


def windows(settings):
    spec = settings["windows"]
    start = pd.Timestamp(spec["first_test_start"], tz="Africa/Cairo")
    for number in range(spec["count"]):
        train_start = start - pd.DateOffset(months=spec["train_months"])
        end = start + pd.DateOffset(months=spec["test_months"])
        yield number + 1, train_start.tz_convert("UTC"), start.tz_convert("UTC"), end.tz_convert("UTC")
        start = end


class WindowMirrors(TrendMirrors):
    """Legacy execution, with a signal-date gate; no entries during warmup.

    The existing runner supplies a causal indicator prefix. Evaluate its last
    bar only; do not refit or replace mirror math. Subclass dispatch deliberately
    retains the legacy execution branch. Indicator state restarts per window.
    """

    def __init__(self, test_start, cfg):
        super().__init__(cfg.screen, cfg.signal)
        self.test_start = test_start

    def generate_signals(self, data):
        signals = pd.Series(WAIT, index=data.index, dtype=int)
        if not data.empty and data.index[-1] >= self.test_start:
            signals.iloc[-1] = self.evaluate_bar(data)
        return signals


def run_window(data, cfg, dataset, mode, train_start, test_start, end):
    subset = {ticker: frame.loc[(frame.index >= train_start) & (frame.index < end)].copy()
              for ticker, frame in data.items()}
    subset = {ticker: frame for ticker, frame in subset.items()
              if not frame.empty and (frame.index >= test_start).any()}
    if not subset:
        raise ValueError("No observed test bars in requested window")
    result = run(WindowMirrors(test_start, cfg), subset, cfg,
                 dataset_path=dataset, dividend_mode=mode)
    # These checks catch orchestration mistakes, not generic/legacy parity.
    for frame in (result.trades, result.cancelled_trades):
        if not frame.empty and (frame.Signal_Date < test_start).any():
            raise AssertionError("Warmup generated a trade")
    if not result.trades.empty and (result.trades.Exit_Date >= end).any():
        raise AssertionError("Trade read beyond test boundary")
    return result


def execute(config_path, output):
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    settings = load_settings(config_path)
    limits = settings.get("limits", LIMITS)
    repo = Path(__file__).resolve().parents[1]
    dataset = (repo / settings["dataset"]).resolve()
    if not output.is_relative_to(repo / "outputs"):
        raise ValueError("Development artifacts must stay under repository outputs/")
    if output.exists():
        raise FileExistsError("Output folder already exists; never overwrite an experiment")
    # Validate all scenarios before simulation or output creation.
    configs = {name: cost_config(settings, name) for name in settings["scenarios"]}
    data, provenance, protected = load_local(dataset, settings)
    for pattern in ("*.py", "validation/*.py", "strategies/*.py"):
        for path in repo.glob(pattern):
            protected[str(path)] = sha(path)
    protected[str(config_path)] = sha(config_path)
    for path in (repo / "outputs/phase1b_baseline_legacy").glob("*"):
        if path.is_file():
            protected[str(path)] = sha(path)
    summaries, trade_frames, cancel_frames, curves, runs = [], [], [], [], []
    for number, train_start, test_start, end in windows(settings):
        for name, cfg in configs.items():
            print(f"Window {number}: {name}", flush=True)
            result = run_window(data, cfg, dataset, settings["dividend_mode"], train_start, test_start, end)
            trades = result.trades
            actual_values = trades.Entry * trades.Shares
            cap = cfg.risk.capital * cfg.risk.max_position_pct
            breaches = actual_values > cap + 1e-8
            total = float(trades.PnL_EGP.sum())
            summaries.append(dict(window=number, scenario=name, train_start=str(train_start),
                test_start=str(test_start), test_end_exclusive=str(end),
                tickers_with_test_bars=len(result.equity_curve), trades=len(trades),
                cancelled=len(result.cancelled_trades), pnl_egp=total,
                mean_pnl_egp=total / len(trades) if len(trades) else None,
                win_rate=float((trades.PnL_EGP > 0).mean()) if len(trades) else None,
                sample_status="SUFFICIENT_COUNT_ONLY" if len(trades) >= settings["windows"]["min_trades"] else "INSUFFICIENT",
                end_liquidations=int((trades.Exit_Reason == "END").sum()),
                completed_raw_value_cap_breaches=int(breaches.sum()),
                completed_cap_breach_egp=float((actual_values - cap).clip(lower=0).sum())))
            trade_frames.append(trades.assign(Window=number, Scenario=name))
            cancel_frames.append(result.cancelled_trades.assign(Window=number, Scenario=name))
            for ticker, curve in result.equity_curve.items():
                test_curve = curve.loc[(curve.index >= test_start) & (curve.index < end)]
                curves.append(test_curve.rename_axis("Date").reset_index().assign(
                    Ticker=ticker, Window=number, Scenario=name))
            runs.append(dict(window=number, scenario=name, effective_config=asdict(cfg), metadata=result.metadata))
    if any(sha(path) != digest for path, digest in protected.items()):
        raise AssertionError("Protected local input/code/config changed")
    # All runs complete before publishing any output. Never overwrite a run.
    output.mkdir(parents=True, exist_ok=False)
    summary = pd.DataFrame(summaries)
    summary.to_csv(output / "windows.csv", index=False)
    pd.concat(trade_frames, ignore_index=True).to_csv(output / "trades.csv", index=False)
    pd.concat(cancel_frames, ignore_index=True).to_csv(output / "cancelled_trades.csv", index=False)
    pd.concat(curves, ignore_index=True).to_csv(output / "equity_curves.csv", index=False)
    metadata = dict(development_only=True, eligible_for_pass_fail=False, mc_gate="DISABLED",
        limits=limits, source_registry=provenance, settings=settings,
        code_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        fingerprints=protected, runs=runs, fitting="NONE; fixed engine defaults",
        boundary_policy="reset indicators at train start; warmup signals gated; END liquidation at last test bar; flat restart",
        dataset_warnings=["Unresolved breaks: ADIB/2025-05-26, EAST/2024-06-02, EFIH/2025-05-25",
                          "Known risk: split provenance and regime coverage unverified",
                          "Cap breach counts cover completed trades only; cancelled shares not exported by legacy runner"])
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    (output / "source_registry.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    lines = [limits, "\n## Development settings\n",
             "Fixed parameters; no fitting, held-out validation, MC or acceptance gate.\n",
             f"Rolling {settings['windows']['train_months']}-month history / {settings['windows']['test_months']}-month test; indicators reset at training start.\n",
             "No warmup entries. Existing END liquidation at last observed test bar; positions never carry across windows.\n",
             "Stop/sizing: signal-Close legacy model, unchanged. Fees/tax scenario is not a historical tariff claim.\n",
             "Cap counts use completed raw executed notionals, exclude fees and cancelled exposure.\n",
             "\n| Window | Scenario | Trades | Cancelled | P/L EGP | Count status | END exits | Cap breaches |\n",
             "|---|---|---:|---:|---:|---|---:|---:|\n"]
    for row in summaries:
        lines.append(f"| {row['window']} | {row['scenario']} | {row['trades']} | {row['cancelled']} | {row['pnl_egp']:.2f} | {row['sample_status']} | {row['end_liquidations']} | {row['completed_raw_value_cap_breaches']} |\n")
    lines.append("\nNet and gross are separate engine runs, not deleted trades or repriced logs. "
                 "No comparison with the frozen 243-trade baseline is claimed. "
                 "Input/code/config hashes and source limitations are recorded in metadata.json.\n")
    (output / "report.md").write_text("".join(lines), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    execute(args.config, args.output)
