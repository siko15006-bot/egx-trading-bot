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
- `resolved` below means the policy or interpretation is settled, not that
  code enforcement or verification has been completed. Both are stated
  separately; a resolved policy alone cannot establish acceptance.
- `defined` means the owner has fixed a metric's mathematical meaning;
  implementation and acceptance eligibility still require verification.
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
- Reopening condition: review when acceptance-eligible data becomes available
  and before any acceptance run. Shared-account implementation, verification
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

- Status: **resolved (interpretation)**.
- Draft reference: `docs/phase_1b_acceptance.md:41`, the signal/max-hold timing
  rule, and the broader wording in acceptance criterion 5 at line 138.
- Code reference: `egx_4_mirrors_v3.py:509` (`stop_fill`) and line 514
  (`target_fill`) implement level-touch fills and gap-bar Close fills.
  `validation/runner.py:134` rejects signal/max-hold policies with
  `NotImplementedError`; line 146 calls the existing trade simulator.
- Audit trail: **Codex's interpretation, accepted by Ahmed on 2026-10-10**.
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

- Status: **defined (owner-approved)**; implementation/verification pending.
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

- Status: **open**.
- Draft reference: `docs/phase_1b_acceptance.md:130`, acceptance criterion 3,
  removes the single best window and requires the remaining result positive.
- Development-spec reference: `docs/phase_1b_spec.md@3b9f43b:257` instead
  ranks/removes a window by total net PnL. This is not the adopted robustness
  definition. P1B-ACC-EXPECTANCY above settles only pooled expectancy.
- Code reference: `validation/development.py:201` disables acceptance
  pass/fail eligibility; no acceptance robustness decision is implemented
  in this path.
- Decision owner: **Ahmed**. Define what a window means for this test:
  a walk-forward OOS window, a calendar year, or another frozen time unit.
  Define eligible units, best-window ranking, and whether to remove only
  the best unit or require every leave-one-out result to pass.
- Remaining criterion questions: must every remaining pooled mean be > 0?
  Is a minimum remaining trade count `N` required, and if so what is `N`?
  These are open questions, not adopted rules or permission to pick values
  after observing results.
- Implementation/verification owner after authorization: **Codex**.
- Acceptance consequence: robustness cannot be declared passed until the
  definition, thresholds and implementation are fixed and verified.

## Unchanged boundaries

MC stays disabled; all existing walk-forward/screen results are development
only. Multi-regime acceptance requirements remain intact. `data_extended/`
is not available; no data download or new data directory is authorized.
ADIB/EAST/EFIH discontinuities remain unresolved pending independent source
verification. The six local evidence files remain untracked and untouched.
TrendMirrors remains closed. No code, configuration or market data changes
were made to resolve these discrepancies.
