"""Legacy-only timing and exact regression. No network or original-file writes."""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import pandas as pd
import egx_4_mirrors_v3 as eng
import strategies.trend_following_mirrors as mirrors
import validation.runner as runner

FROZEN_REV = "7aacc48"


def frozen_symbol(path, name, namespace):
    source = subprocess.check_output(["git", "show", f"{FROZEN_REV}:{path}"], cwd=REPO, encoding="utf-8")
    node = next(n for n in ast.parse(source).body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    scope = namespace.copy()
    exec(compile(ast.Module(body=[node], type_ignores=[]), f"{FROZEN_REV}:{path}", "exec"), scope)
    return scope[name]


def frozen_legacy():
    strategy = frozen_symbol("strategies/trend_following_mirrors.py", "TrendMirrors", vars(mirrors))
    run = frozen_symbol("validation/runner.py", "run", {**vars(runner), "TrendMirrors": strategy})
    return strategy, run


def csv_bytes(frame):
    return frame.to_csv(index=False, lineterminator="\r\n").encode("utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-variant", choices=("frozen", "optimized"))
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = REPO / "data_2019_2026_wf"
    baseline = REPO / "outputs/phase1b_baseline_legacy"
    metadata = json.loads((baseline / "metadata.json").read_text())
    reference = (baseline / "trades.csv").read_bytes()
    cancelled_reference = (baseline / "cancelled_trades.csv").read_bytes()
    protected = list(source.glob("*.csv")) + list(baseline.glob("*"))
    protected += [REPO / "egx_4_mirrors_v3.py", REPO / "test_plan_sizing.py",
                  REPO / "outputs/vwap_causality_fix/README.md"]
    before = {str(p): sha(p) for p in protected if p.is_file()}
    if before[str(REPO / "egx_4_mirrors_v3.py")] != "ff4f30c4c072ad2a191e2268cac38b8987fc3dc20e4aea123dd0f98460095516":
        raise RuntimeError("Engine bytes changed; algorithmic optimization benchmark invalid")
    cfg = eng.SystemConfig()
    if asdict(cfg.risk) != metadata["risk"]:
        raise RuntimeError("Risk configuration differs from frozen baseline")
    data = eng.load_data_map(source)
    old_strategy, old_run = frozen_legacy()
    sample = {"COMI.CA": data["COMI.CA"].iloc[:250].copy()}
    def timed(call, strategy, inputs):
        start = time.perf_counter()
        result = call(strategy, inputs, cfg, dataset_path=source, dividend_mode="none")
        return result, time.perf_counter() - start
    if args.sample_variant:
        call, strategy = ((old_run, old_strategy) if args.sample_variant == "frozen"
                          else (runner.run, mirrors.TrendMirrors))
        result, seconds = timed(call, strategy(), sample)
        payload = csv_bytes(result.trades)
        report = dict(variant=args.sample_variant, seconds=seconds,
                      rows=250, trades=len(result.trades),
                      trades_sha256=hashlib.sha256(payload).hexdigest(),
                      cancelled_sha256=hashlib.sha256(csv_bytes(result.cancelled_trades)).hexdigest(),
                      pid=os.getpid(), pycache_prefix=sys.pycache_prefix,
                      dont_write_bytecode=sys.dont_write_bytecode,
                      script_sha256=sha(Path(__file__)),
                      protected_files_unchanged=all(sha(Path(p)) == h for p, h in before.items()))
        (out / "sample.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report), flush=True)
        if not report["protected_files_unchanged"]:
            raise AssertionError("Protected files changed")
        return
    print("START 250-row COMI benchmark: frozen legacy then optimized legacy", flush=True)
    old, old_seconds = timed(old_run, old_strategy(), sample)
    new, new_seconds = timed(runner.run, mirrors.TrendMirrors(), sample)
    for field in ("trades", "cancelled_trades"):
        if csv_bytes(getattr(old, field)) != csv_bytes(getattr(new, field)):
            raise AssertionError(f"Subset {field} changed")
    pd.testing.assert_frame_equal(old.equity_curve["COMI.CA"], new.equity_curve["COMI.CA"], check_exact=True)
    if old.metadata != new.metadata:
        raise AssertionError("Subset metadata changed")
    print(f"Subset unchanged: {old_seconds:.3f}s -> {new_seconds:.3f}s", flush=True)
    print("START full optimized legacy regression", flush=True)
    full, full_seconds = timed(runner.run, mirrors.TrendMirrors(), data)
    (out / "trades.csv").write_bytes(csv_bytes(full.trades))
    (out / "cancelled_trades.csv").write_bytes(csv_bytes(full.cancelled_trades))
    byte_equal = (out / "trades.csv").read_bytes() == reference
    cancelled_equal = (out / "cancelled_trades.csv").read_bytes() == cancelled_reference
    unchanged = {p: sha(Path(p)) == digest for p, digest in before.items()}
    report = dict(scope="legacy TrendMirrors only", frozen_revision=FROZEN_REV,
        working_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        sample_rows=250, sample_trades=len(old.trades), sample_old_seconds=old_seconds,
        sample_new_seconds=new_seconds, speedup=old_seconds/new_seconds,
        full_seconds=full_seconds, trades=len(full.trades), cancelled=len(full.cancelled_trades),
        full_byte_identical=byte_equal, cancelled_byte_identical=cancelled_equal,
        baseline_sha256=hashlib.sha256(reference).hexdigest(),
        actual_sha256=sha(out / "trades.csv"),
        input_fingerprints_match=full.metadata["input_fingerprints"] == metadata["input_fingerprints"],
        protected_before_sha256=before, protected_files_unchanged=unchanged,
        script_sha256=sha(Path(__file__)),
        changed_code_sha256={p: sha(REPO/p) for p in ("validation/runner.py", "strategies/trend_following_mirrors.py")},
        sanity_only=True, mc_gate="DISABLED", eligible_for_pass_fail=False)
    (out / "performance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("protected_before_sha256", "protected_files_unchanged")}), flush=True)
    if not (byte_equal and cancelled_equal and len(full.trades)==243 and len(full.cancelled_trades)==0
            and report["input_fingerprints_match"] and all(unchanged.values()) and report["speedup"]>=5):
        raise AssertionError("Frozen performance/regression criteria failed; see performance.json")


if __name__ == "__main__":
    main()
