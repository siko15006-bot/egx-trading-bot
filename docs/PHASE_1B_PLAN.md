# Phase 1b — validation layer (plan only, not implemented)

Status: planned 2026-10-08. Nothing here is built yet. Phase 1a is done (`strategies.BaseStrategy`,
`TrendMirrors`, `STRATEGIES`, mirror-rejection instrumentation). 4 Mirrors is abandoned (`STRATEGY_STATUS.md`).

## Goal

Any new (non-trend) strategy must pass the same validation before a result is believed: out-of-sample, walk-forward,
Monte Carlo and parameter stability, all on the engine's one execution policy (`execution_policy.md`: entry at the
next session's Close, level fills or that bar's Close on a gap, Volume 0 rows skipped, data breaks cancel, Thndr fees
from `fees_config.py` + 10 bps slippage per side, dividends added on `data/`).

## 0. Prerequisite — generic runner (found while planning)

`egx_4_mirrors_v3.backtest()` is 4-Mirrors-specific: it calls `passes_screener`, `evaluate_4_mirrors` and
`build_trade_plan` (ATR stop/target, sizing). `BaseStrategy.generate_signals` returns only BUY/WAIT/EXIT, so a new
strategy cannot be executed yet. Needed before modules 1–4:

- **Interface addition** (decision for Ahmed): either `BaseStrategy.trade_plan(data, i) -> (stop, target) | None`
  (stop/target exits, as today), or signal-driven exits (EXIT = sell at the next session's Close), or both.
- **`validation/runner.py`**: `run(strategy, data_map, cfg, start=None, end=None) -> RunResult` — signals →
  `egx_4_mirrors_v3.simulate_trade` (no second execution engine), sizing by `RiskConfig`, one independent account per
  stock as today. `RunResult`: trades frame (ticker, signal/entry/exit dates, prices, shares, P/L, reason, held
  sessions), per-ticker equity, cancelled trades, buy & hold over the same window.
- **`validation/metrics.py`**: `summarize(run) -> dict` — the counterfactual table's metrics: trades, % winners /
  losers, avg win / loss, expectancy, net profit, return on capital, max drawdown (combined and worst stock),
  stocks beating buy & hold, median holding period, average exposure, cancelled count.
- **Acceptance:** `run(TrendMirrors(), …)` reproduces `backtest()` trade for trade on all 90 stocks (same check as
  Phase 1a's signal identity).

## Modules

All under `validation/`, pure functions on `RunResult`/trades, seeded where random, no writes outside `outputs/`.

### 1. `walk_forward.py` — rolling train/test

```python
walk_forward(strategy_cls, data_map, *, train_bars, test_bars, step=None, grid=None, cfg=None) -> WFResult
```
- Folds by **date** (one calendar for all stocks): train `[t, t+train)`, test `[t+train, t+train+test)`, advance by
  `step` (default `test_bars`). Test windows never overlap; earlier bars feed indicator warm-up only.
- With `grid`: parameters chosen on each train window only (via `param_sweep`), frozen, then run on its test window.
- `WFResult`: per-fold params + train/test metrics, stitched OOS trades, share of folds with OOS expectancy > 0.

### 2. `out_of_sample.py` — 70/30, no leakage

```python
split_dates(data_map, train_frac=0.7) -> (cut_date, end_date)
out_of_sample(strategy_cls, data_map, *, params, train_frac=0.7, cfg=None) -> OOSResult
```
- One cut date for all stocks (no shuffling, no per-stock cuts). Parameters are fixed **before** the test window is
  read. A trade counts as OOS only if its signal bar is after the cut; a train trade still open at the cut is
  reported separately, never mixed in.
- `OOSResult`: train metrics, test metrics, degradation (test vs train expectancy).

### 3. `monte_carlo.py` — 1,000 runs on the trade list

```python
monte_carlo(trades, *, capital, n=1000, method="shuffle" | "bootstrap", seed=0) -> MCResult
```
- `shuffle`: permutes trade order — same total P/L, path-dependent risk (drawdown, losing streaks).
  `bootstrap`: resamples trades with replacement — uncertainty of the total.
- `MCResult`: percentiles (5/50/95/99) of max drawdown, final equity and longest losing streak; probability of
  ending below the starting capital. Input is OOS trades only.

### 4. `param_sweep.py` — grid + OOS check

```python
param_sweep(strategy_cls, grid, data_map, *, train_frac=0.7, cfg=None) -> SweepResult
```
- Every combination run on the train window; the best is chosen on train only, then run once on test.
- Stability: each combination's immediate neighbours in the grid (one step in one parameter). A **cliff edge** =
  a neighbour whose expectancy changes sign or drops by more than half.
- `SweepResult`: full grid table (train), chosen params + their OOS metrics, neighbour table, cliff flags, and the
  number of combinations tried (multiple-testing disclosure, printed with every result).

## Success criteria for a strategy (all required)

1. **OOS expectancy > 0 after fees and slippage**, on at least 30 OOS trades (fewer = "insufficient", not a pass).
2. **Monte Carlo worst-case drawdown under a threshold:** 95th-percentile max drawdown of the shuffled OOS trades
   ≤ **X% of allocated capital** — X to be set by Ahmed before the first run (proposal: 15%).
3. **Parameter stability:** the chosen parameters and all immediate neighbours have OOS expectancy > 0; no cliff edge.
4. **Walk-forward consistency:** OOS expectancy > 0 in a majority of folds (not only on aggregate).
5. *Proposed addition (Ahmed to confirm):* report OOS return against buy & hold over the same window and exposure.
   4 Mirrors had positive expectancy (+221 EGP/trade) and still lost to buy & hold by 43 points, so criterion 1 alone
   would have passed it.

Every criterion is fixed before a strategy is run; a strategy is not re-run with changed thresholds after seeing
its result.

## Data constraint (decision needed, data/ untouched)

`data/` holds 250 daily rows (one year) per stock: a 70/30 split is ~175/75 sessions and walk-forward allows only
2–3 short folds. `data_2019_2026_wf/` has 2019–2026 but only 10 large caps (fully adjusted: no dividend add, never
mixed with `data/` — `KNOWN_ISSUES.md`). Options: validate on `data/` and accept short windows; validate on the
long series and accept the small universe; or download a longer history for the 90 stocks into a new folder
(`data/` itself stays on hold).

## Test plan for the validation layer

Synthetic fixtures only (noon timestamps — the 2026-04-24 DST trap), plus the 90-stock identity check once.

- **Runner:** `run(TrendMirrors)` = `backtest()` trade for trade; an always-BUY toy strategy's trades and P/L
  equal a hand computation; execution policy cases (gap at Close, Volume 0 skipped, data break cancelled) go through.
- **Causality guard (all modules):** a deliberately peeking strategy (uses `shift(-1)`) must be caught — signals on
  a prefix of the data must equal the full-data signals on that prefix; the runner checks this before trusting any
  strategy.
- **Out-of-sample:** one cut date for all stocks; no OOS trade with a signal before the cut; changing only post-cut
  data never changes the train metrics or the chosen parameters.
- **Walk-forward:** folds contiguous and non-overlapping, covering the range; per-fold choices use only that fold's
  train window (same perturbation test).
- **Monte Carlo:** same seed → same result; `shuffle` preserves total P/L exactly; max drawdown of a short known
  sequence equals a hand calculation; n = 1000 by default.
- **Param sweep:** combination count reported; cliff detection flags a synthetic metric surface with a known cliff
  and passes a smooth one; the chosen parameters do not depend on test data.

## Build order

runner + metrics (with the identity check) → out_of_sample → walk_forward → monte_carlo → param_sweep. Each step
its own commit with its tests; no strategy is evaluated until all four exist.
