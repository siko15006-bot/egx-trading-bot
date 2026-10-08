# Phase 1b Spec (addendum to docs/PHASE_1B_PLAN.md @ b321f7a)

Status: design only; implementation and validation have not started.
This supplements PHASE_1B_PLAN.md. It supersedes conflicting design decisions
in that plan, but does not change code or docs/execution_policy.md.

## Execution policy: preserve the existing model

Source of truth: docs/execution_policy.md.

- Entry: Close of the session after the signal bar.
- Check exits starting with the bar after the entry bar, never the entry bar.
- Stop touched within the bar: fill at the stop price.
- Target touched within the bar: fill at the target price.
- Whole bar below stop (High < stop): fill at that bar's Close.
- Whole bar above target (Low > target): fill at that bar's Close.
- Both levels touched: stop wins; daily OHLC does not establish intrabar order.
- Open is forbidden for every fill, regardless of whether it lies in range.
- Volume 0 rows never enter, exit, or update a trailing stop. A filler entry
  bar skips the trade, rather than deferring it silently.
- Data breaks cancel affected trades under the existing policy.
- Preserve existing end-of-window liquidation and cost conventions.

These are simulation assumptions, not proof of executable real-world fills.
There is no universal next-bar Close rule for stop/target exits.
TrendMirrors retains its existing trailing behavior and trade identity.

Proposed signal-driven exits for new strategies are not existing engine
behavior: an EXIT learned at bar k's close schedules execution at the next
bar's Close, not Close[k]. Freeze filler, pending-exit and end-of-window
handling before implementing this extension. Max-hold exits follow the same
causal scheduling rule; the bar-count convention must also be frozen.

## Decision 1: extend BaseStrategy, no parallel Protocol

Optional exit_policy method: signature NOT FINALIZED and not implemented.
The open choice is whether the strategy receives entry_price/entry_index as
arguments or the runner resolves entry context from its execution record.
Neither interface is frozen by this spec. Proposed policy payload:

```python
@dataclass(frozen=True)
class ExitPolicy:
    use_generic_defaults: bool = False
    stop: float | None = None
    target: float | None = None
    exit_on_signal: bool = False
    max_hold_bars: int | None = None
```

- `stop` and `target` are absolute prices, not overloaded multipliers.
- `use_generic_defaults=True` rejects any explicit stop or target in
  `__post_init__`; do not silently choose one interpretation.
- Require finite positive explicit levels and a positive integer max_hold_bars
  when supplied. Reject contradictory long-position levels.
- None requests the legacy TrendMirrors plan only. Non-TrendMirrors strategies
  must return a policy with an explicit stop or use_generic_defaults=True.
- The runner resolves generic defaults using the realized entry price and
  ATR at the SIGNAL bar, not the entry bar:
  stop = entry_price - 1.5 * ATR(signal_bar);
  target = entry_price + 3.0 * ATR(signal_bar).
- Frozen runner constants: GENERIC_DEFAULT_STOP_ATR_MULT=1.5 and
  GENERIC_DEFAULT_TARGET_ATR_MULT=3.0. Strategies need no custom sentinel.
- The eventual interface must allow policy resolution after the entry Close
  is known. Resolution must not affect
  the earlier BUY decision or use entry-bar High/Low to trigger an exit.
  Pass only a prefix ending at the evaluation bar; no future rows.
- Resolve fixed levels once at entry; evaluate later exit signals separately.
  `exit_on_signal` enables use of the existing EXIT signal stream, it is not
  itself an immediate exit instruction.
- Priority for simultaneous triggers: stop > target > exit_signal > max_hold.
  Pending scheduled exits need an explicit precedence rule before implementation.
- New generic policies use fixed levels only; generic trailing stops are out
  of scope. Legacy TrendMirrors trailing stops remain unchanged.
- Position sizing stays runner-level. Validate sizing from actual entry and
  resolved stop without altering the legacy TrendMirrors path.

Acceptance test for compatibility: run(TrendMirrors) must reproduce backtest()
trade for trade, including prices, timing, cancellation and costs.

## Decision 2: approximate Monte Carlo, not portfolio simulation

- N=1000 i.i.d. bootstrap resamples of eligible OOS trades, with replacement.
- Seed and initial capital denominator must be fixed and recorded before a run.
- Accumulate fixed net trade P/L to produce an approximate closed-trade
  equity curve; not mark-to-market.
- This ignores capital constraints, overlapping positions, changing sizing,
  intratrade mark-to-market and dependence across trades. It is NOT shared-account
  or portfolio-level drawdown, and does not establish live account risk.
- Report median and 95th-percentile maximum drawdown, baseline approximate DD,
  their ratio, initial capital denominator and worst single-stock DD separately.
  Ratio is NOT_AVAILABLE if baseline DD is zero.
- Provisional approximate gate: 95th-percentile DD <= 15%. Gate status:
  DISABLED until the capital denominator is decided and frozen. Do not choose the
  denominator or revise the threshold after seeing results.
- Proper shared-account MC requires re-simulating capital-constrained execution
  and position overlap; it is outside this approximation's scope.
- An approximate pass is not evidence that account drawdown is below 15%.

Buy & hold is reported, not an acceptance gate. Use only benchmarks actually
present in the inputs; name the dataset and dividend/cost conventions.

## Decision 3: longer data, explicit dividend mode

- Preferred candidate: longer history in data_extended/, leaving data/ untouched.
- Fallback candidate: data_2019_2026_wf/ on 10 stocks, explicitly labelled
  small-universe. Dataset selection is NOT FINALIZED; data_extended/ is not
  declared ready or usable by this spec.
- Verify at least one falling and one choppy regime before robustness claims.
- Dividend semantics verified against resolve_dividend_mode and its caller:
  add -> dividend-unadjusted prices; with_dividends is applied.
  none -> dividend-adjusted prices; no dividends added.
- Known folders have checked dividend modes. An unknown folder with an explicit
  mode is accepted and tagged user-set, unverified. Without an explicit mode,
  the unknown-folder run is refused.
- Registration is recommended, not mandatory. Verify adjustment status from
  provenance before choosing a mode; never infer it from a folder name.
- Every result records dataset path, fingerprints, adjustment mode and regime
  labels. One-year data/ is rising-market-only smoke testing and cannot pass
  regime-diverse acceptance.

## Actual engine interface and net/gross runs

- build_trade_plan(ticker, df, signal_cfg, risk_cfg) returns a plan, not a trade.
- df ends at the signal bar. The execution runner, not build_trade_plan itself,
  handles next-session entry and subsequent exit simulation.
- Plans have no net_pnl or exit_index. Use completed execution records.
- build_trade_plan is 4-Mirrors-specific; do not require other strategies to
  pass its mirror gates. The generic runner resolves their own exit policies
  while reusing execution helpers rather than creating a second fill model.
- Net and gross require two independent end-to-end runs: fee/tax assumptions
  affect target construction, and slippage affects modeled returns.
- Net uses recorded fee, slippage and tax assumptions. Gross disables all
  three, including fixed fees/minima; simply changing a variable rate is insufficient.
- Engine RSI uses Close, period 14, over Volume > 0 rows. Use its RSI column;
  never recompute an alternative or use entry-bar RSI for an earlier decision.
- The RSI smoke-test comparison is A baseline vs D RSI(signal)>=60 only,
  inside the existing 50<RSI<70 condition. Freeze its temporal split separately
  before running. It is not Phase 1b acceptance.

## Acceptance criteria and definitions

Freeze walk-forward lengths, step, regime labels and fitting procedure before
running. OOS windows do not overlap; training parameters never see test data.

1. Net OOS expectancy > 0 in a majority of eligible windows.
2. Each eligible window has >=30 net OOS trades. Smaller windows are
   insufficient, not passes. No eligible windows means NOT_AVAILABLE.
3. Stability uses total net P/L, not a sum of window expectancies:
   T=sum(net PnL across eligible windows); remove the window with the largest
   total net P/L and require T_best>0. Fewer than two eligible windows is
   insufficient. Report all excluded windows and their results as well.
4. Apply the provisional approximate MC gate only with a pre-frozen capital
   denominator, and retain its limitations in every pass/fail statement.
5. No look-ahead; apply the existing touch/gap policy above, not universal
   next-bar Close exits. Changing only Open must not change fills.
6. Report independent net and gross results, per window and overall.
7. Retain the plan's parameter-neighbour stability requirement; this addendum
   does not remove it.

Expectancy = total P/L / trade count, equivalent to win probability times
average win minus loss probability times absolute average loss. Report pooled
trade-weighted expectancy separately from the total-P/L stability test; empty
samples are undefined, not zero.

Report buy-and-hold beating counts, regime splits, worst-stock DD and MC ratios.
No deleted-trade arithmetic may be presented as a backtest counterfactual.

## Deliverables and status

- docs/phase_1b_results.md: per-window results, regime labels and limitations.
- outputs/phase_1b/: raw trades, per-ticker results and MC summaries for both
  cost models, with code/config/data provenance.
- Amend PHASE_1B_PLAN.md with a pointer in a later approved documentation edit.
- Implementation: not started. No code, defaults, data or execution policy changed.
- Implementation is BLOCKED until the MC capital denominator, exit_policy
  signature and actual dataset choice are settled. Record an explicit verified
  dividend mode for the chosen dataset; registry membership is not mandatory.
- Before implementation: freeze scheduled-exit edge cases and generic sizing.
- Before acceptance runs: verify longer data and dividend mode, freeze windows,
  regime definitions, bootstrap seed and capital denominator.
