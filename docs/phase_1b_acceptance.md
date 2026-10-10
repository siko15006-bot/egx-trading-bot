<!-- Source: Ahmed's message 2026-10-08 19:02 UTC, Claude session 11c7970e (extracted verbatim 2026-10-10). Never committed to EGX repo. -->
# Phase 1b Spec (addendum to docs/PHASE_1B_PLAN.md @ b321f7a)

This does not replace PHASE_1B_PLAN.md. It resolves the three open decisions
in that plan and fixes the interfaces it left implicit. Where this spec and
the plan differ, this spec wins; amend the plan to point here.

---

## Decision 1 — Exit interface

Settled: extend the existing BaseStrategy (merged in Phase 1a) with one
optional method. Do not introduce a second, parallel strategy Protocol.

    class BaseStrategy:
        # existing: generate_signals, get_params, name
        def exit_policy(self, data, i) -> "ExitPolicy | None":
            return None

    @dataclass(frozen=True)
    class ExitPolicy:
        stop: float | None = None
        target: float | None = None
        exit_on_signal: bool = False
        max_hold_bars: int | None = None

Default-stop rule:
- None is NOT a free pass. Returning None means "use the engine's default",
  but the engine's default stop/target are specific to the 4 Mirrors
  strategies, defined inside build_trade_plan. They are not a general
  default.
- Therefore: any strategy that is not a TrendMirrors strategy MUST return a
  non-None ExitPolicy with `stop` set. Two acceptable ways:
    (a) set stop/target explicitly, or
    (b) request a documented generic default, e.g. k * ATR, by returning
        ExitPolicy(stop=GENERIC_DEFAULT) where GENERIC_DEFAULT is resolved by
        the runner against the engine's ATR.
- TrendMirrors strategies may continue returning None to get the current
  behavior. This preserves all existing results.

Exit-timing rule (must be tested):
- A signal-based exit or max_hold is recognized at the close of bar i.
- Execution is on the NEXT bar, at the same price convention the engine uses
  for entry (open of next bar, or close of next bar — pick one and use it for
  both entry and exit). Do not execute on bar i's close.
- This closes the look-ahead hole: the signal is not known until bar i closes,
  so acting on bar i's close is not allowed.

Priority on the same bar:
    stop > target > exit_signal > max_hold_bars
This matches the engine's existing behavior (stop beats target).

Exit-condition evaluation happens on every bar while a position is open.
First trigger wins.

Non-goal: per-strategy position sizing. That stays a runner-level input.

---

## Decision 2 — Monte Carlo drawdown gate, and buy & hold

Settled:
- The MC DD gate is computed on a SINGLE shared account, not on the sum of
  90 independent 100k accounts.
- Gate: 95th-percentile max DD on the shared account <= 15% (absolute).
- The 15% is provisional and revisited only if the shared-account baseline
  max DD is itself near 15%.

Why this changed:
- The 0.24% previously reported was measured on the sum of 90 independent
  100k accounts while the strategy used ~3% of capital. That number is
  diluted and not decision-useful.
- Worst single stock DD was -5.71%.
- A 15% gate on the 9M aggregate would never fail. It belongs on a shared
  account, as used by `simulate_d` in the optimizer, or on capital actually
  deployed.

Procedure:
- N = 1000 bootstrap resamples of the trade sequence (i.i.d., with
  replacement).
- Recompute the shared-account equity curve under the net cost model
  (fees + slippage + tax).
- Report: median, 95th percentile, ratio to baseline shared-account DD.
- Gate: 95th percentile <= 15%.
- Also reported, not gated: worst single-stock DD (informational).

Buy & hold:
- Reported as a criterion, NOT an acceptance gate for Phase 1b.
- Reason: one year of rising-only data makes buy & hold a beta test, not an
  edge test. Report per window and overall. Do not reject a configuration
  solely on buy & hold underperformance.

This removes the MC DD question from the blockers list.

---

## Decision 3 — Data source

Settled: primary = download a longer history into `data_extended/`, leaving
`data/` untouched. Fallback = the 2019–2026 long series on 10 stocks, clearly
labelled. The current one-year `data/` is smoke-test only.

Mandatory registration:
- Any new data folder MUST be registered in `resolve_dividend_mode`,
  otherwise the backtest refuses to run on it. This is intentional and must
  not be bypassed.
- The registration MUST declare whether the data is dividend-adjusted or not.
  Getting this wrong causes double-counted dividends.
- Until registration is done, `data_extended/` is not usable.

Rules:
- `data_extended/` must include at least one falling and one choppy regime.
- Every Phase 1b result file must state the dataset path and the regime
  labels present in it.
- If only `data/` is available, results are labelled `rising-market-only`,
  are not eligible to pass acceptance criteria, and may only be reported as
  a smoke test.

---

## Updated acceptance criteria
(supersedes PHASE_1B_PLAN.md where they differ)

To pass Phase 1b on a dataset with at least one falling regime:

1. Out-of-sample expectancy per trade, net of fees/slippage/tax, > 0 in a
   majority of walk-forward windows.
2. Minimum OOS trade count per window: >= 30. Windows with < 30 trades are
   marked "insufficient" and excluded from pass/fail, not counted as passes.
3. Window-stability, defined operationally:
   - Let W = set of eligible windows.
   - Let T = total net expectancy across W.
   - Let T_best = total after removing the single best window.
   - Require T_best > 0. ("No single window drives the total.")
4. 95th-percentile Monte Carlo max DD on the shared account <= 15%
   (absolute).
5. No look-ahead: signals computed on data up to and including the signal bar
   only; entry and exit both execute on the next bar.
6. All results reported both net (fees/tax) and gross.

Reported but not gated:
- Count of stocks beating buy & hold, per window and overall.
- Ratio of MC 95th-percentile DD to baseline shared-account DD.
- Worst single-stock DD.
- Regime split (rising / falling / choppy).

Explicitly rejected as acceptance criteria:
- Arithmetic aggregation on deleted trades.
- Net-only or gross-only reporting.
- Benchmarks not present in the inputs (EGX30 unless added).

---

## Deliverables

- docs/phase_1b_results.md — per-window results, regime labels, pass/fail.
- outputs/phase_1b/ — raw trades, per-ticker results, MC resample summary,
  both cost models.
- Amend docs/PHASE_1B_PLAN.md to point here.

---

## Status

- Decisions 1–3: settled (above).
- Implementation: not started.
- Blocked on: `data_extended/` registration in resolve_dividend_mode
  (or the 10-stock fallback, also registered), and confirmation of the
  generic default stop for non-TrendMirrors strategies.
- data/ and engine defaults unchanged.
