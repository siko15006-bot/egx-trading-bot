# Phase 1b Acceptance Discrepancies

Recorded: 2026-10-10. Documentation only; no implementation or acceptance run
is authorized by this record.
Owner-approved follow-up decisions: 2026-10-10, recorded below. The preserved
draft is unchanged; these decisions are an explicit addendum, not edits
silently attributed to its original text.

## Authority and status meanings

- Acceptance reference: [Ahmed's preserved draft](phase_1b_acceptance.md),
  committed verbatim in `0a23afa`. Its header records extraction on 2026-10-10
  from a message dated 2026-10-08; the original message was not independently
  verified in this review. Ahmed authorized preserving this supplied text.
- The source file's SHA256 is
  `0CA05D0C7F2D728DF093D14CACBD9519675A08CB9EFA9915BEAF15CA6206A764`.
- [The current spec](phase_1b_spec.md) remains DEVELOPMENT / EXPERIMENTAL.
  It does not override the acceptance draft.
- `open`: an owner decision is pending. `deferred`: explicitly postponed by
  the owner. No item is silently deferred by this record.
- `resolved` below means the policy, interpretation or metric is settled, not that
  code enforcement or verification has been completed. Both are stated
  separately; a resolved policy alone cannot establish acceptance.
- References to development-spec line numbers describe snapshot `3b9f43b`.
  Code references describe the unchanged implementation reviewed with it.

## P1B-ACC-MC: shared-account Monte Carlo

- Status: **deferred**; gate remains DISABLED.
- Draft reference: `docs/phase_1b_acceptance.md:63`, Decision 2, and acceptance
  criterion 4 at line 135: p95 maximum drawdown <= 15% on one shared account.
- Current implementation: `validation/runner.py:179` identifies equity as
  per-stock closed-trade diagnostics, not shared-account equity.
  `validation/development.py:201` records `mc_gate="DISABLED"` and
  `eligible_for_pass_fail=False`. No shared-account MC gate is implemented
  in this validation path. `backtest_optimizer.py:194` contains `simulate_d`,
  a separate shared-portfolio scenario, not a wired Phase 1b MC gate.
- Development-spec reference: `docs/phase_1b_spec.md@3b9f43b:127` uses a fixed
  1M EGP notional yardstick. This is not the draft's shared-account model;
  it is also not evidence of a live gate using the wrong denominator.
- Decision owner: **Ahmed**, approved 2026-10-10. Defer because no
  acceptance-eligible dataset is currently available.
- Reopening condition: review when acceptance-eligible data is registered
  (`data_extended/` or an equivalent approved dataset) and before any
  acceptance run. Registration alone does not establish data eligibility.
  Shared-account implementation, verification
  and explicit gate-enablement authorization are required before evaluating
  the draft's p95 DD <= 15% criterion. The 1M yardstick is not a substitute.
- Implementation/verification owner after authorization: **Codex**.
- Acceptance consequence: MC remains DISABLED. No acceptance pass may be
  declared while this required gate is missing, disabled or deferred.

## P1B-ACC-STOP: price fields versus ATR multipliers

- Status: **resolved (interface decision)**; verification pending.
- Draft reference: `docs/phase_1b_acceptance.md:22`, Decision 1: `stop` and
  `target` price fields, with a proposed generic-default sentinel at line 36.
- Code reference: `strategies/base.py:19` and `strategies/base.py:20` expose
  `stop_atr_mult` and `target_atr_mult`, not absolute-price fields.
  `validation/runner.py:136` resolves defaults to 1.5 and 3.0; line 138 uses
  `stop = entry_price - stop_mult * ATR(signal_bar)` and
  `target = entry_price + target_mult * ATR(signal_bar)`.
- Decision owner: **Ahmed**, approved 2026-10-10. Keep the ATR-multiplier
  interface and the conversion addendum below, with no code change. This
  resolves the interface choice explicitly rather than asserting that the
  original draft and implementation always had identical field meanings.
- Verification owner: **Codex**, after separate authorization. Documenting
  the conversion does not demonstrate full execution or acceptance compliance.
- Acceptance consequence: the interface decision is settled; required
  implementation/acceptance verification remains pending.

### Approved ATR-to-price conversion addendum

Basis: `entry_price` is the actual modeled entry at the next session's Close;
`atr` is the engine ATR at the signal bar, not the entry bar. The runner
resolves prices after the entry price is known, without changing the earlier
BUY decision or using entry-bar High/Low to fill an exit.

```text
stop_mult   = 1.5 if stop_atr_mult is None else stop_atr_mult
target_mult = 3.0 if target_atr_mult is None else target_atr_mult
stop_price   = entry_price - stop_mult * atr
target_price = entry_price + target_mult * atr

For compatible price levels and atr > 0:
stop_mult   = (entry_price - stop_price) / atr
target_mult = (target_price - entry_price) / atr
```

Current generic multiplier resolution (not an inventory of past runs):

| Level | Policy field | Default k when None | Explicit override |
| --- | --- | --- | --- |
| Stop | `stop_atr_mult` | 1.5 | Supplied finite positive multiplier |
| Target | `target_atr_mult` | 3.0 | Supplied finite positive multiplier |

An acceptance report must identify the resolved k values actually used;
the default table does not imply every strategy or past run used them.

The inverse is a mathematical conversion, not a new absolute-price API.
It requires finite positive ATR and positive multipliers; the resolved stop
must remain finite and positive. Field-level `None` selects defaults; a
whole-policy `None` retains its separate legacy-only meaning. This addendum
does not add a no-stop mode, change legacy sizing, or permit future-bar ATR.

## P1B-ACC-DATA: mandatory data registration

- Status: **resolved (policy)**.
- Draft reference: `docs/phase_1b_acceptance.md:103`, Decision 3: registration
  in `resolve_dividend_mode` and a declared adjustment policy are mandatory.
- Code reference: `egx_4_mirrors_v3.py:446`; its unknown-folder branch at
  line 451 accepts an explicit `add`/`none` mode and returns the provenance
  label `user-set, unverified` at line 454. The caller is
  `validation/runner.py:52`.
- Development-spec reference: `docs/phase_1b_spec.md@3b9f43b:223` recommends
  registration rather than requiring it.
- Resolved decision owner: **Ahmed**. Registration is mandatory for every
  acceptance run. Explicit-mode bypass is development-only and must never
  establish acceptance eligibility.
- Enforcement/verification owner: **Codex**, under separate implementation
  authorization. Acceptance-specific enforcement is **not implemented or
  verified by this documentation change**; the current bypass still exists.
- Acceptance consequence: refuse acceptance eligibility until registration,
  adjustment provenance and enforcement are verified. `data_2019_2026_wf/`
  remains development/fallback only, not acceptance-eligible.

## P1B-ACC-EXIT: signal exits versus stop/target fills

- Status: **resolved (Ahmed accepted Codex's interpretation on 2026-10-10)**;
  implementation/verification pending.
- Draft reference: `docs/phase_1b_acceptance.md:41`, the signal/max-hold timing
  rule, and the broader wording in acceptance criterion 5 at line 138.
- Code reference: `egx_4_mirrors_v3.py:509` (`stop_fill`) and line 514
  (`target_fill`) implement level-touch fills and gap-bar Close fills.
  `validation/runner.py:134` rejects signal/max-hold policies with
  `NotImplementedError`; line 146 calls the existing trade simulator.
- Audit trail: **Ahmed accepted Codex's interpretation on 2026-10-10**.
  This clarification is not quoted original wording from the preserved draft.
- Resolved decision owner: **Ahmed**. Next-bar timing applies to an exit
  decision recognized at the signal bar's close, including max-hold intent.
  It does not move a touched stop or target to the following candle.
  Under the current execution policy, scheduled exits use next-bar Close,
  while stops/targets retain touch/gap handling. This is not permission to
  introduce Open fills or change the legacy execution model.
- Implementation/verification owner: **Codex**, after authorization.
  Generic signal/max-hold execution is still **not implemented**; the
  interpretation alone is not a passing timing test.
- Acceptance consequence: timing compliance requires implementation and
  tests of the required exit modes before any acceptance claim.

## P1B-ACC-EXPECTANCY: pooled net expectancy

- Status: **resolved (metric definition)**; implementation/verification pending.
- Draft reference: `docs/phase_1b_acceptance.md:132`, acceptance criterion 3:
  `total net expectancy across W`, then removal of the single best window.
- Development-spec reference: `docs/phase_1b_spec.md@3b9f43b:257` instead uses
  total net PnL and removes the window with the greatest total net PnL.
- Code reference: `validation/development.py:201` explicitly disables
  pass/fail eligibility; line 204 identifies fixed defaults rather than
  fitting. No acceptance stability decision is implemented in this path.
- Definition owner: **Ahmed**, approved 2026-10-10. For all completed net
  trades in the eligible windows combined:

```text
pooled_net_expectancy = sum(net_PnL across eligible windows)
                       / count(completed net trades across those windows)
```

- This is trade-weighted mean net PnL per trade, in EGP/trade. It is not
  total PnL, an unweighted sum/mean of window expectancies, or a percentage
  return. An empty pooled sample is NOT_AVAILABLE, not zero or a pass.
- The definition does not replace the draft's majority-of-eligible-windows
  expectancy requirement. Per-window results must still be reported.
- Window-removal robustness is tracked separately in P1B-ACC-ROBUST below;
  it is not silently fixed by defining pooled expectancy.
- Implementation/verification owner after authorization: **Codex**.
- Acceptance consequence: the metric meaning is fixed, but no acceptance
  pass follows from this definition or current development reports.

## P1B-ACC-ROBUST: leave-one-window-out robustness

- Status: **resolved (LOO decision, N_min, minimum window count)**;
  implementation/verification pending.
- Audit trail: **Ahmed's addition on 2026-10-10**, not Codex's interpretation
  or original wording from the preserved draft.
- Draft reference: `docs/phase_1b_acceptance.md:130`, acceptance criterion 3,
  removes the single best window and requires the remaining result positive.
- Development-spec reference: `docs/phase_1b_spec.md@3b9f43b:257` instead
  ranks/removes a window by total net PnL. This is not the adopted robustness
  definition. P1B-ACC-EXPECTANCY above settles only pooled expectancy.
- Code reference: `validation/development.py:201` disables acceptance
  pass/fail eligibility; no acceptance robustness decision is implemented
  in this path.
- Decision owner: **Ahmed**, approved 2026-10-10. For the eligible
  walk-forward OOS windows `W`, remove each window once and recompute the
  pooled net expectancy over all remaining completed net trades:

```text
For every window w in W:
    remaining = completed net trades from W excluding w
    remaining_count = count(remaining)
    remaining_mean = sum(net_PnL in remaining) / remaining_count
    Require remaining_mean > 0 for every leave-one-out version.
```

- Window lengths, step and eligibility must be frozen in the validation
  configuration before any acceptance run; this addition does not invent
  a calendar-year regrouping or set those configuration values.
- This is stronger than removing only the best window: every omission
  includes omission of that window, without needing to rank windows.
  The LOO rule is kept separate from the pooled expectancy definition.
- Sub-condition N_min (trades): **closed by Ahmed on 2026-10-10**, set
  before any acceptance run. Draft criterion 2 already requires >= 30 OOS
  trades in every eligible window, so with at least two eligible windows
  every leave-one-out remainder has >= 30 trades. No separate N_min value
  is added; the example value 20 is withdrawn.
- Minimum eligible windows: **|W| >= 3, Ahmed on 2026-10-10**, set before
  any acceptance run. With fewer than 3 eligible windows the robustness
  criterion FAILS (it is not skipped or marked not-applicable). LOO always
  runs over every eligible window, whatever their number.
- A zero-count remainder has undefined mean and cannot pass.
- Implementation/verification owner after authorization: **Codex**.
- Acceptance consequence: the robustness definition is fixed, but it cannot
  be declared passed until window configuration and implementation are
  fixed and verified.

## P1B-ACC-FX: currency of acceptance

- Status: **resolved (Ahmed, 2026-10-11)**, recorded before any acceptance run.
- Ahmed works and accounts in EGP, so every acceptance criterion above stays
  measured in EGP (primary gate).
- Additional required check: the same pooled net expectancy, with each trade's
  entry and exit converted to USD at the official rate of its own date, must
  also be > 0. Purpose: reject a strategy whose EGP edge is only exposure to
  EGP devaluation. Both numbers are reported with every result.
- Conversion details (fixed now, before any run): source = Yahoo `EGP=X`
  daily close (official rate), raw copy `outputs/fx_raw_20261010/EGP=X.csv`;
  each fill converted at the rate of its own fill date (entry fill and exit
  fill separately; fees in EGP converted at the fill date too); a date with no
  FX quote uses the last earlier quote. The official rate is used for the
  whole history, including 2023 when the parallel market diverged; results
  covering 2023 state that caveat.
- Not adopted: a USD benchmark (e.g. S&P 500) or a separate USD drawdown gate.
  A hard "beat buy & hold" gate is also not adopted (the preserved draft
  reports buy & hold, it does not gate on it) -- see P1B-ACC-FX-2.

## P1B-ACC-FX-2: buy & hold disclosure and justification threshold

- Status: **resolved (Ahmed, 2026-10-11)**, before any acceptance run.
- Every acceptance report shows buy & hold for the SAME basket (equal weight
  of the strategy's eligible stocks), the SAME windows, the SAME starting
  capital and the SAME fee model, in EGP and in USD (P1B-ACC-FX conversion).
- Compared quantity: total net return of the strategy's capital over the
  window vs total return of the buy & hold basket over the same window (not a
  per-trade mean vs a window return, which are different units).
- Basket membership is point-in-time by validity: on each date only stocks
  that have valid data on that date (after the candidate's valid_from cuts,
  e.g. CIEB from 2021-03-01, BTFH from 2023-06-04, EFIH from 2021-10-20) are
  in the equal-weight basket; an excluded stock is not replaced and its
  weight is shared by the others. The strategy uses the same availability.
  Both sides use the same price-return series (e.g. BTFH rights value is
  absent for both), so the comparison stays like for like.
- Trigger, exactly: `BH_USD_return - Strategy_USD_return >= 20 percentage
  points` requires a written justification before any paper/shadow stage.
  Outperformance never triggers it. This is a mandatory stop for review,
  not an automatic rejection.
- Minimum contents of that justification: sample size N, per-trade sigma and
  the smallest edge detectable at that N; decomposition of the gap (timing,
  stock selection, currency exposure); what result would change the
  conclusion and the date of the next review.
- Small samples cut both ways: with too few trades a strategy below buy & hold
  is "not proven worse" and one above it is "not proven better". Either way
  the decision is to stay in paper/shadow, never promotion to real money.
  A minimum trade count for promotion (N_min_promotion from the measured
  per-trade sigma and a stated minimum edge) is fixed in the strategy's own
  pre-registration, before its results.
- Revisit as a hard gate once a strategy has passed the other criteria with a
  larger sample; "the market" stays defined as above unless Ahmed changes it
  before results.
- Implementation/verification owner after authorization: **Codex/Claude**;
  FX source and caveats as in the data candidate manifest.

## Unchanged boundaries

MC stays disabled; all existing walk-forward/screen results are development
only. Multi-regime acceptance requirements remain intact. `data_extended/`
is not available. Candidate dataset (2026-10-10, Ahmed-approved build, local
and gitignored): `outputs/yahoo_expansion_18_fixed_20261010/` with its own
`manifest.json`. ADIB/EFIH/EAST/MFPC(2025-07-14)/SKPC(2024-10, 2026-01)/
COMI(2025-12) breaks were Yahoo splits recorded 4-15 days late and never
applied; fixed there by the Yahoo factor. MFPC 2024-01-02 is the ENPC merger
share distribution (8.07476 new per old share, ex 2023-12-28), fixed by
factor 9.07476. MASR 2026-02-22 is a treasury-share distribution (AGM
2026-02-15), fixed by the Yahoo factor 1.0417. Residuals UNRESOLVED: EAST -5.8%
(2024-06-02, low impact), MFPC +11.9% (2024-01-02, first valid session after
the merger suspension; kept as a real repricing).
CIEB rows through 2021-02-28 and BTFH before 2023-06-04 (cash rights issue,
factor unverified) were removed.
Regimes are measured in EGP and USD (Yahoo EGP=X, official rate). The
candidate is NOT registered in `resolve_dividend_mode` and NOT
acceptance-eligible until Ahmed reviews it. The six local evidence files remain untracked and untouched.
TrendMirrors remains closed. No code, configuration or market data changes
were made to resolve these discrepancies.
