# Phase 1b Acceptance Discrepancies

Recorded: 2026-10-10. Documentation only; no implementation or acceptance run
is authorized by this record.

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
- References to development-spec line numbers describe snapshot `3b9f43b`.
  Code references describe the unchanged implementation reviewed with it.

## P1B-ACC-MC: shared-account Monte Carlo

- Status: **open**.
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
- Decision owner: **Ahmed**. Choose authorized shared-account implementation
  and verification, or an explicit deferral. Do not enable it automatically.
- Implementation/verification owner after authorization: **Codex**.
- Acceptance consequence: MC remains DISABLED. No acceptance pass may be
  declared while this required gate is missing, disabled or deferred.

## P1B-ACC-STOP: price fields versus ATR multipliers

- Status: **open**.
- Draft reference: `docs/phase_1b_acceptance.md:22`, Decision 1: `stop` and
  `target` price fields, with a proposed generic-default sentinel at line 36.
- Code reference: `strategies/base.py:19` and `strategies/base.py:20` expose
  `stop_atr_mult` and `target_atr_mult`, not absolute-price fields.
  `validation/runner.py:136` resolves defaults to 1.5 and 3.0; line 138 uses
  `stop = entry_price - stop_mult * ATR(signal_bar)` and
  `target = entry_price + target_mult * ATR(signal_bar)`.
- The conversion explains current behavior; it does not establish that the
  multiplier-only interface satisfies the draft's absolute-price contract.
- Decision owner: **Ahmed**. His preference for documenting the conversion
  is not yet a final interface decision. Preserve the draft and current code
  until an explicit decision authorizes an addendum or implementation change.
- Implementation/verification owner after authorization: **Codex**.
- Acceptance consequence: interface compliance remains unverified.

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

## P1B-ACC-EXPECTANCY: window stability metric

- Status: **open**.
- Draft reference: `docs/phase_1b_acceptance.md:132`, acceptance criterion 3:
  `total net expectancy across W`, then removal of the single best window.
- Development-spec reference: `docs/phase_1b_spec.md@3b9f43b:257` instead uses
  total net PnL and removes the window with the greatest total net PnL.
- Code reference: `validation/development.py:201` explicitly disables
  pass/fail eligibility; line 204 identifies fixed defaults rather than
  fitting. No acceptance stability decision is implemented in this path.
- Total PnL, pooled per-trade expectancy, and an unweighted sum/mean of
  window expectancies are different quantities. Different window trade
  counts can also change which window ranks as best.
- Decision owner: **Ahmed**. Define aggregation, weighting, best-window
  ranking and the post-removal calculation before an acceptance run. Do not
  silently select the development-spec PnL rule to match current behavior.
- Implementation/verification owner after authorization: **Codex**.
- Acceptance consequence: the stability criterion cannot be evaluated as
  a pass until its meaning is fixed and its implementation is verified.

## Unchanged boundaries

MC stays disabled; all existing walk-forward/screen results are development
only. Multi-regime acceptance requirements remain intact. `data_extended/`
is not available; no data download or new data directory is authorized.
ADIB/EAST/EFIH discontinuities remain unresolved pending independent source
verification. The six local evidence files remain untracked and untouched.
TrendMirrors remains closed. No code, configuration or market data changes
were made to resolve these discrepancies.
