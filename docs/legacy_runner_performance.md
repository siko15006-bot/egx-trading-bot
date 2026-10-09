# Legacy runner algorithmic optimization

## Frozen scope and criterion

Optimize only concrete TrendMirrors legacy execution. Not new-path parity.
Classification: algorithmic optimization, outputs verified byte-identical
on the 9-stock regression. This is not universal equivalence on all inputs.
Reference: outputs/phase1b_baseline_legacy/trades.csv, 243 trades on 9 stocks.
Criterion frozen before edits: >=5x faster on the first 250 COMI rows compared
with the original 7aacc48 runner/strategy; unchanged subset results and full
243-trade CSV plus cancellation CSV byte identity. No new strategy or gate.

## Implementation

- TrendMirrors.evaluate_bar reads the current closed decision bar from a
  prepared causal prefix, using existing passes_screener/evaluate_4_mirrors.
- generate_signals keeps its full-Series API and delegates each bar to the
  same helper. No duplicated indicator or signal mathematics.
- The concrete TrendMirrors runner reuses indicators computed once per stock
  and passes only data.iloc[:i+1], with defensive copies.
- Subclasses and all generic strategies keep their prior prefix/history path.
- build_trade_plan, position_size, simulate_trade and net_trade_pnl are
  untouched. Engine bytes still match the pre-performance SHA-256:
  ff4f30c4c072ad2a191e2268cac38b8987fc3dc20e4aea123dd0f98460095516.
- No global or persistent cache, no future bars exposed to strategy code.

Repeated historical signal evaluation and repeated prefix indicator calculation
are removed for the concrete legacy strategy. Increasing speedup with larger
inputs is consistent with that change, not a constant-factor-only optimization.
However, defensive prefix copies still incur superlinear total copying work;
this document does not claim the entire runner is asymptotically linear.
Historical full-run timing and sample timing use different conditions
and do not by themselves establish an asymptotic complexity class.
Untested mirror branches, rare cancellations and other inputs are not covered
by the 9-stock byte-identity claim; synthetic checks supplement, not generalize it.

## Measured result

Paired timing on the same loaded first 250 COMI rows, excluding imports,
data loading, CSV exports and frozen-code extraction:

| Measure | Result |
|---|---:|
| Frozen 7aacc48 legacy implementation | about 30 s |
| Optimized legacy implementation | about 0.4-0.5 s |
| Sample completed trades | 2 |
| Optimized full 9-stock run | about 40 s (initial run) |
| Full completed/cancelled | 243 / 0 |

Subset trade/cancellation CSV bytes, exact equity curve and metadata match.
Full CSV matches the ORIGINAL reference including header, row order, numeric
text and CRLF. No float rounding or reference reserialization is used for
the full comparison. The entire COMI 22-trade subset is therefore preserved
as part of the identical 243-row full file.

Expected and actual full CSV SHA-256:
e3ca4a4830b5c5f98012e75e478b988b3152265201c6c7d922c8eae30eaeab9b

Input fingerprints and all protected-file checks match. The benchmark captures
raw-file hashes before simulation and records them in the final report. Original inputs, baseline
artifacts, engine, parity-skip file and old VWAP README were not changed.

This is one paired wall-clock measurement, not a timing-distribution study
or a performance guarantee across machines. The original 200-minute run is
historical evidence, not a contemporaneous full-run timing comparison.

## Reproduce

The harness loads ONLY the original runner function and strategy class from
git revision 7aacc48 in memory. Shared engine mathematics are pinned to the
unchanged working-file bytes. It does not check out/reset files or change
the working engine. It compares legacy with legacy, never with generic.

```powershell
Set-Location C:\Projects\EGX
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' `
  scripts\benchmark_legacy_runner.py --output outputs\legacy_performance_rerun
```

Use a fresh output directory. Artifacts for the recorded run:
outputs/legacy_performance_20261009/trades.csv, cancelled_trades.csv,
performance.json. Outputs are ignored in Git; this document preserves hashes.

performance.json SHA-256:
30c9547f2ae031dc49c063fe50815a50bc754c9dfa40f5316167213c83de3695
Executed harness SHA-256:
ad4d9bce5e997609594afb7df7985a8748151b94a1b2d4f33d30e2cefe4089c3
Executed runner SHA-256:
adc5bbf9f77352d14dff8939e469de620512c778d504c3f5e2c4527351270bcd
Executed TrendMirrors adapter SHA-256:
1cce1dae07add2ed7c92eac14ed951573e2b7af4849d51985039106e6c75bbbe

## Fresh-process repetitions

The sample-only mode runs each implementation in its own interpreter, once,
without a warm-up call. Imports/loading remain excluded from runner timing.
Bytecode reads are redirected to a verified absent, unique pycache_prefix;
-B and PYTHONDONTWRITEBYTECODE prevent creating it. Each invocation checks
that this directory is absent both before and after execution. Existing repo
__pycache__, .pytest_cache and unrelated temporary files were not deleted:
they are not used by this isolated timing command. The benchmark does not
invoke pytest or read a previous output/cache artifact as computed results.
Per-run indicator precomputation is intentional, not a persisted result cache.
Windows filesystem/page cache is NOT flushed: these are fresh-process runs,
not a claim of cold-disk IO. The original paired timing was same-process;
these independent-process repetitions address that limitation.

Exact command for the recorded clean repetitions (pairs 2 and 3):

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
foreach ($pair in 2,3) {
  foreach ($variant in 'frozen','optimized') {
    $cache = "C:\Users\ahmed\Documents\Codex\2026-10-05\a\isolated_bytecode_${pair}_${variant}_20261009"
    if (Test-Path -LiteralPath $cache) { throw "Cache path must not exist: $cache" }
    & 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' -B -X "pycache_prefix=$cache" scripts/benchmark_legacy_runner.py --sample-variant $variant --output "outputs\legacy_fresh_${pair}_${variant}_20261009"
    if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed' }
    if (Test-Path -LiteralPath $cache) { throw 'Bytecode cache unexpectedly created' }
  }
}
```

Reproduction requires fresh names: existing output directories are refused.
The executions were serial. Pair 1 is excluded because the harness import
statement was cleaned up while that pair was underway; pairs 2 and 3 use
the final identical harness bytes. There was no trading-code edit during them.
Each sample.json records PID, bytecode settings, CSV hashes, script hash and
protected-file verification. Final harness SHA-256:
69ab194e3a553ee78b165bf740c8c8d55b9b4ae230b28eec9845f12e1abf0189.

| Clean pair | Frozen seconds | Optimized seconds | Separate PIDs |
|---|---:|---:|---|
| 2 | about 30 | about 0.42 | 17572 / 16272 |
| 3 | about 30 | about 0.38 | 19948 / 21208 |

Trading code did not change between the initial and these measurements:
runner and adapter hashes above are still current. Only the harness gained
sample-only timing and an import cleanup. Timing variation reflects measurement
conditions, not nondeterministic trade decisions. Exact ratios are not presented
as a reliable speedup estimate; raw timing observations remain in their JSON
artifacts for audit, rather than a precision claim in this summary.

All four executions produced 2 completed sample trades, identical trade hash
d4c4825ab13018944440ffaad33a5a46bc66740abef703392ae864132012eb7e
and cancellation CSV hash
d6d8b416caf83fa46b3a9cc49f592f2666dc41c658602a591104739b6d1b8257.
All protected-file checks passed. These repetitions verify sample timing and
identity; the full 243-trade identity remains the previously recorded full run,
not an invented additional full regression. Runtime/precomputation scope did
not change when the sample-only harness option was added.

## Known limitations

1. Current code SHA-256: runner adc5bbf9f77352d14dff8939e469de620512c778d504c3f5e2c4527351270bcd; adapter 1cce1dae07add2ed7c92eac14ed951573e2b7af4849d51985039106e6c75bbbe. Observed sample range: old about 30 s, optimized about 0.36-0.5 s; not a precise speedup guarantee.
2. Minimal zero-volume, single-bar and session-boundary differential checks are included; exhaustive edge branches and seeded fuzzing remain OPEN as P1B-DIFF-TEST (P2).
3. Dynamic dispatch substitutions remain OPEN as P1B-DYNAMIC-DISPATCH (P3), also recorded in KNOWN_ISSUES.md; no new dispatch framework or guard is added.
4. Real-data byte identity is verified on 9 stocks only, not guaranteed for every input or evidence of legacy/new-path equivalence.

## Final-code full rerun

After verifying the unchanged runner/adapter hashes, the final harness was
rerun with `python -B scripts/benchmark_legacy_runner.py --output outputs/legacy_final_regression_20261009`
in a fresh process with PYTHONDONTWRITEBYTECODE=1. Sample old/new runner
times were about 31 s / 0.36 s. Full optimized run was about 28 s, yielding
243 completed trades and zero cancellations. Both full CSVs matched their
original baseline bytes; input fingerprints and every protected-file check
also matched. Full measured optimized range is therefore about 28-40 s.
The historical original run took about 12,000 s; that comparison is not a
contemporaneous controlled ratio and is not advertised as one.

Final performance.json SHA-256:
c9b81fbffd38511888772bbcde773e7034035e52a8d1d75a845bcc15026adf95.
Full trade hash remains e3ca4a4830b5c5f98012e75e478b988b3152265201c6c7d922c8eae30eaeab9b.
The recorded changed-code hashes match the current working code exactly.

## Verification and scope

Final broader verification: 123 passed, 1 unchanged skip in 128.15 s.
The increase from 120 is exactly the three parametrized minimal differential
cases added this round, not a change to old test outcomes. Literal command:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' -m pytest -q -rs -p no:cacheprovider --basetemp 'C:\Users\ahmed\Documents\Codex\2026-10-05\a\pytest_perf_final_20261009' test_runner_performance.py test_indicator_causality.py test_validation_runner.py test_plan_sizing.py test_exit_policy.py test_execution.py test_strategies.py
```

Minimal differential runs compare complete trade/cancellation DataFrames,
exact equity curves and metadata. They are deliberately small input checks;
they do not establish coverage of every possible execution branch.

test_runner_performance.py: four checks passed (12.94 s): frozen signal
parity including mixed/filler input; one indicator calculation plus causal
prefix checks; complete synthetic legacy run identity; subclass compatibility.
Broader focused suite (not the whole repository): 120 passed, 1 skipped in 133.80 seconds; the only skip
is the unchanged legacy-versus-generic trade-match debt.

### Why 7 became 120

These are different selections, not 113 added tests or repaired failures.
The narrow command selected seven indicator checks and one explicitly skipped
debt test. The broader command selected seven test files (121 collected).
Only four optimization checks were added in test_runner_performance.py;
two numeric VWAP oracle checks belong to the earlier prerequisite scope B.
The other 114 passing checks existed before this optimization. No failed test
or skipped debt test was converted to passing.

Literal narrow command (7 passed, 1 skipped):

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' -m pytest -q -rs -p no:cacheprovider test_indicator_causality.py test_plan_sizing.py::test_legacy_vs_new_path_trade_match
```

Literal broader command (120 passed, 1 skipped):

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' -m pytest -q -rs -p no:cacheprovider --basetemp 'C:\Users\ahmed\Documents\Codex\2026-10-05\a\pytest_perf_20261009_a' test_runner_performance.py test_indicator_causality.py test_validation_runner.py test_plan_sizing.py test_exit_policy.py test_execution.py test_strategies.py
```

### New-path boundary, traced manually

Entry point is validation.runner.run(strategy, data_map, cfg, ...).
isinstance(strategy, TrendMirrors) selects execution semantics, while
type(strategy) is TrendMirrors selects the optimization. A non-TrendMirrors
instance takes the unchanged else branch: prefix calculation, generate_signals,
readiness checks, exit_policy, position_size, then shared simulate_trade and
net_trade_pnl. It never takes the optimized evaluate_bar branch or legacy
build_trade_plan branch. Subclasses retain generate_signals as tested.

This is a trace of the current ordinary call path, not proof about arbitrary
runtime monkeypatches, importlib replacements or registry/decorator mutations.
Those dynamic substitutions remain outside the regression claim. The four
shared engine functions are unchanged; three are legitimately called by the
new path, rather than absent from it.

Scope A (algorithmic optimization): validation/runner.py,
strategies/trend_following_mirrors.py, scripts/benchmark_legacy_runner.py,
test_runner_performance.py, this performance record.

Separate documentation scope: KNOWN_ISSUES.md (sticky VWAP behavior, path
debt, P1B-DIFF-TEST and P1B-DYNAMIC-DISPATCH). The prior evidence files
test_indicator_causality.py, docs/vwap_regression_evidence.md and
docs/vwap_regression_evidence.review.md remain outside the optimization commit.
Exclude unchanged untracked docs/atr_filter_negative_result.md,
docs/entry_candle_exits_investigation.md, docs/mirrors_failure_analysis.md,
docs/trade_predictors.md from both scopes. No data, engine math or gate change;
no push. Scope is enforced with explicit paths and cached diff checks.

MC remains DISABLED, results sanity-only, not eligible for pass/fail.
After adding the sample-only benchmark option, the targeted command
`python -m pytest -q -rs -p no:cacheprovider test_runner_performance.py test_indicator_causality.py test_plan_sizing.py::test_legacy_vs_new_path_trade_match`
passed 11 checks with 1 unchanged skip in 19.40 seconds. The 120-pass result
above is the earlier broader run, not a claim that it was rerun this round.
P1B-STOP-ANCHOR remains OPEN. test_legacy_vs_new_path_trade_match stays
SKIPPED. Claude's earlier VWAP review is not a review of this performance diff.
