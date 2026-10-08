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
- Preserve legacy end-of-window liquidation and cost conventions.
- New-path terminal entry rule: after BUY and before policy evaluation, skip a
  signal whose next-bar entry would be the final available bar (i+2 >= n).
  Do not fail the run for this condition. The last-bar signal is not evaluated
  because it has no next-bar entry. This requires at least one post-entry bar.
  Legacy remains unchanged and may record END on its entry bar. This is an
  explicit path divergence, not a claim of generic-vs-legacy identity.

These are simulation assumptions, not proof of executable real-world fills.
There is no universal next-bar Close rule for stop/target exits.
TrendMirrors retains its existing trailing behavior and trade identity.

Proposed signal-driven exits for new strategies are not existing engine
behavior: an EXIT learned at bar k's close schedules execution at the next
bar's Close, not Close[k]. Freeze filler, pending-exit and end-of-window
handling before implementing this extension. Max-hold exits follow the same
causal scheduling rule; the bar-count convention must also be frozen.

## Decision 1: extend BaseStrategy, no parallel Protocol

Exit interface: FROZEN as a design decision; not implemented.
The strategy owns exit intent; the runner owns actual entry and execution.
The strategy does not receive entry_price or entry_index. Contract:

```python
def exit_policy(self, data, i) -> ExitPolicy | None:
    return None

@dataclass(frozen=True)
class ExitPolicy:
    stop_atr_mult: float | None = None
    target_atr_mult: float | None = None
    exit_on_signal: bool = False
    max_hold_bars: int | None = None
```

- Field-level None means the generic default multiplier, not no stop/target.
  ExitPolicy() therefore requests both generic defaults; no flag or sentinel.
- Returning None for the whole policy is distinct: it requests the legacy
  TrendMirrors plan only. Non-TrendMirrors strategies must return ExitPolicy.
- Validate supplied multipliers as finite and strictly positive; reject zero,
  negatives, NaN, infinity and booleans. max_hold_bars, when supplied, must be
  a positive integer, not a boolean. Validate flags as booleans.
- Call exit_policy once on the signal-bar prefix with i equal to the signal
  index. Freeze the returned intent before entry; provide no future rows.
  Generic execution starts at row 0; strategies must return WAIT until their
  own history/indicators are ready. Before calling exit_policy, the runner
  requires a post-entry bar, a non-filler signal, finite positive signal ATR
  and Volume_SMA20, and a finite positive next-bar Close. Ineligible BUYs are
  skipped without policy evaluation; these checks cannot affect prior signals.
  i is a zero-based iloc position, not an index label. The prefix starts at
  original row 0, so i == len(data)-1 is also its relative position. Do not
  pass rolling/shifted windows under this contract.
- After the actual entry is known, the runner resolves levels using ATR at
  the SIGNAL bar, not the entry bar:
  stop_mult = 1.5 if policy.stop_atr_mult is None else policy.stop_atr_mult;
  target_mult = 3.0 if policy.target_atr_mult is None else policy.target_atr_mult;
  stop = entry_price - stop_mult * ATR(signal_bar);
  target = entry_price + target_mult * ATR(signal_bar).
  Use explicit None checks, not `value or default`. Refuse invalid signal ATR
  or nonpositive resolved stop; do not silently clip levels.
- Frozen runner constants: GENERIC_DEFAULT_STOP_ATR_MULT=1.5 and
  GENERIC_DEFAULT_TARGET_ATR_MULT=3.0. Strategies need no custom sentinel.
- Entry-based level resolution must not affect the earlier BUY decision or
  use entry-bar High/Low to trigger an exit. Absolute/non-ATR stops and a
  no-stop mode are outside Phase 1b; extend the contract only when needed.
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

### Temporary two-path debt (runner wiring not implemented)

- Planned dispatch is explicit by strategy type: TrendMirrors uses
  build_trade_plan (legacy-path); other BaseStrategy implementations use
  generate_signals plus exit_policy (new-path). The runner retains the strategy
  instance. None from an unrelated strategy must not trigger the legacy path.
- Tag every result and trade with legacy-path or new-path; never silently mix
  execution paths in reported results.
- Both paths use the engine's ATR column at the signal bar: Wilder 14 True
  Range on Volume > 0 rows, not an alternative ATR implementation.
- Extract sizing before wiring, as a separate pre-Phase-1b refactor. Preserve
  the legacy entry reference, arithmetic, rounding and fee-adjusted target.
- Before wiring, add a frozen full-trade regression for legacy TrendMirrors:
  entry/exit dates and prices, initial stop/target, shares, exit reason,
  costs/P&L and cancellations. Existing signal-identity tests alone do not
  satisfy this requirement. Plan snapshots are not completed-trade regression.
- Retire this debt only after both paths pass full-trade identity tests on
  the agreed fixtures. Any deliberate model change requires separate review
  and impact analysis, not updated expected values presented as identity.

## Decision 2: Monte Carlo denominator FROZEN, gate DISABLED

Frozen before any run:

    N_SLOTS = 10
    PER_TRADE_CAPITAL = 100,000 EGP
    NOTIONAL_DENOMINATOR = N_SLOTS * PER_TRADE_CAPITAL = 1,000,000 EGP

This is a notional risk yardstick, not capital actually deployed or a portfolio
simulation. Observed max concurrency is not the denominator: a larger
denominator would shrink DD% for the same EGP loss. No post-hoc change to the
denominator or switch between max and p95 is permitted.

- N=1000 i.i.d. bootstrap resamples of eligible OOS trades, with replacement.
- Freeze and record the seed before running; never select it from results.
- Accumulate fixed net trade P/L into an approximate closed-trade equity curve,
  not mark-to-market. Include the initial point before the first trade.
- Define max DD in EGP as the largest running-peak minus subsequent cumulative
  P/L. Report DD_fraction = max_DD_EGP / NOTIONAL_DENOMINATOR. This is fixed-
  denominator drawdown, not conventional percentage drawdown from a varying peak.
- This ignores capital constraints, position overlap, changing sizing,
  intratrade mark-to-market and dependence. It is NOT shared-account simulation.
- Report median and p95 max DD, baseline non-resampled DD on the same denominator,
  p95/baseline ratio (NOT_AVAILABLE if baseline DD is zero), and worst-stock DD.
- Report the baseline concurrency histogram and median/p95/max open positions;
  freeze observation-grid and same-day overlap conventions before measurement.
  Concurrency is informational, not resampled and not used in the denominator.

Gate: p95 max DD <= 15% of NOTIONAL_DENOMINATOR. Status: DISABLED until this
data-source decision is committed, a baseline on data_2019_2026_wf/ is produced
for a sanity check, and a separate explicit gate-enablement decision is recorded.
Do not enable the gate from this spec alone. A non-binding baseline gate is
reported as such, not repaired by tuning the denominator after results.

Capacity Violation is a separate boolean: did baseline concurrency exceed
N_SLOTS? It neither implies nor is implied by a DD breach. No capacity ranking,
re-entry or rejection rule is defined here. Realistically enforcing capacity
requires a runner change, outside this Phase 1b approximation.

Buy & hold is reported, not an acceptance gate. Use only benchmarks actually
present in the inputs; name the dataset and dividend/cost conventions.

## Decision 3: data source FROZEN

- Dataset: data_2019_2026_wf/, 9 stocks. Eight begin 2019-07-02;
  EFIH begins 2021-10-20. All end 2026-10-01.
- Regime verification is DEFERRED. No falling/choppy classifier is applied
  or frozen for Phase 1b. Individual-stock drawdowns do not prove regime coverage.
- Every result carries: small-universe, partial-history, regimes-unverified.
- Acceptance is explicitly RELAXED from regime-diverse validation to validation
  on a small, partially-covered, regime-unverified dataset. Every results file
  states this relaxation; a pass does NOT establish multi-regime robustness.
- data/ remains rising-market-only smoke testing, ineligible for acceptance.
- data_extended/ is unavailable and not planned for this Phase 1b scope.
- EFIH enters no earlier than 2021-10-20. Cross-sectional counts use stocks
  with available eligible history at the evaluation date/window; report the
  actual denominator, including exclusions for insufficient warm-up/history.
  Never synthesize pre-listing history to make the universe constant.
- Dividend semantics verified against resolve_dividend_mode and its caller:
  add -> dividend-unadjusted prices; with_dividends is applied.
  none -> dividend-adjusted prices; no dividends added.
- Known folders have checked dividend modes. An unknown folder with an explicit
  mode is accepted and tagged user-set, unverified. Without an explicit mode,
  the unknown-folder run is refused.
- Registration is recommended, not mandatory. Verify adjustment status from
  provenance before choosing a mode; never infer it from a folder name.
- Declare the chosen folder's dividend mode explicitly and record it per run.
- Fingerprint the actual data, code and configuration inputs per run, with
  paths and counts. The old report's 96-input count is not a fixed requirement
  for this different dataset.

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
4. The approximate MC gate remains DISABLED pending baseline sanity review
   and explicit enablement. Report it as not evaluated, not a pass. No complete
   acceptance pass can be declared while a required gate is disabled.
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
- Exit signature and multiplier payload: frozen in this design, not implemented.
- Dataset choice and notional denominator: frozen; MC gate remains DISABLED.
- Implementation and baseline execution are not authorized by this documentation
  commit. Record an explicit verified dividend mode; registry membership is optional.
- Before implementation: freeze scheduled-exit edge cases and generic sizing.
- Before baseline/acceptance runs: verify dividend mode, freeze windows,
  bootstrap seed and concurrency measurement conventions. Regime verification
  is deferred with the explicit acceptance relaxation above.
