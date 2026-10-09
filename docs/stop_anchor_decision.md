# P1B-STOP-ANCHOR: decision brief

Status: CLOSED by Ahmed on 2026-10-09 (reference decision only).
Technical recommendation: Codex. Verification debt remains open.

## Approved decision (2026-10-09)

1. The project adopts actual execution price as the stop/sizing reference.
2. Legacy is noncompliant with the actual-execution position-value cap:
   19 of 50 net-assumption completed trades (38%) exceeded it.
3. Legacy is frozen as a research reference only, not an acceptance criterion.
   Any future production path must use actual execution price.
4. No legacy correction is made in this phase. Any correction is separate work.

Legacy results remain restricted by this classification. Closing this decision
does not prove legacy/new-path parity. test_legacy_vs_new_path_trade_match
remains SKIPPED until full-trade verification is implemented. No code, data
or acceptance-gate change follows from this documentation.

The technical analysis below was prepared before approval and is retained
as historical rationale; its previously pending contract question is resolved
by the decision above, not by a code migration.

## Historical decision brief
Prepared 2026-10-09 against HEAD 08e167b. No model change or new backtest.
Consistency check 2026-10-09: git grep confirms build_trade_plan entry at
signal Close (engine line 365), cap sizing at line 348, planned value at
line 411, and simulate_trade actual entry at next-bar Close (line 528).
Observed execution is actual next-bar Close, not the plan reference.
Historical question, now resolved: must the cap constrain actual execution
value, or only planned value? A planned 200 shares at 100 becomes 20,400 at entry 102, exceeding a
20,000 actual-value cap. If the contract requires that cap at execution,
this is a legacy enforcement defect, not an acceptable anchor difference.
The final allowed-difference catalogue must follow Ahmed's specification
decision, not be inferred from the current behavior inventory below.

## Verified current behavior

Production-code entry points use v3 build_trade_plan: signal_engine.build_signals,
bot_handlers and egx_dashboard; validation.runner is the separate Phase 1b
validation path. This identifies repository wiring, not a verified live deployment.
Stop consumers: v3 plan construction/_net_reward_risk, backtest/simulate_trade,
validation.runner, backtest_optimizer, signal_engine, bot_handlers,
egx_dashboard, auto_sim.replay (stored stop0), and paper_trading (explicit
trade.stop_loss, not a direct plan call). Located by git grep on
plan.stop_loss, atr_sl_mult, stop0 and stop_given; arbitrary dynamic calls are excluded.

- egx_4_mirrors_v3.py::build_trade_plan uses the signal candle's Close for
  plan.entry, initial stop, sizing reference and position value. Initial
  target is signal Close + reward_risk * atr_sl_mult * ATR(signal), then
  may be increased to meet the cost-adjusted net reward/risk requirement.
- egx_4_mirrors_v3.py::simulate_trade actually enters at Close[i+1]. It
  skips entry unless stop < actual entry < target, and scans exits from i+2.
- validation/runner.py::run keeps those plan levels, shares, position value
  and risk_egp for TrendMirrors, but uses the simulator's actual entry for P/L.
- The generic path computes fixed stop/target and position sizing from
  actual Close[i+1], using the same signal-bar ATR. No entry-bar indicator
  influences the signal. Generic default multiples are 1.5 / 3.0.
- Slippage affects net_trade_pnl, not the raw entry or stop anchors.

The difference is a model choice, not evidence of look-ahead by itself.
Signal-anchored levels can be intentional pre-entry technical levels;
entry-relative multiples can be an intentional distance-based risk policy.
However, planned risk/value in legacy are not generally actual-entry risk/value.

## When the difference appears

The 243-byte-identical-trade evidence is legacy BEFORE versus legacy AFTER
optimization, never legacy versus generic. It supports neither explanation
that sizing ignores stop distance nor that the anchor difference was dormant
on these 9 stocks; that cross-path experiment has not been performed.

position_size explicitly uses floor(risk_budget / risk_per_share). For equal
ATR and stop multiples, both CURRENT paths pass k*ATR as that distance:
signal_close - (signal_close-k*ATR) = entry - (entry-k*ATR) = k*ATR.
Thus moving both entry and stop anchors together does not alone change the
risk-cap share count. Actual-entry loss distance in legacy DOES change by
entry-signal_close. Recomputing legacy sizing against its fixed signal stop
would instead pass entry-signal_stop; that is a proposed change, not current code.

Current sizing can still differ through the position-value cap: it divides
by signal Close in legacy and actual entry in generic. With a position cap
of 20,000 EGP and the other limits above 200 shares, Close=100 vs entry=102
gives floor(20000/100)=200 vs floor(20000/102)=196. The trigger is a binding
value cap and different floored limits. It is entirely possible on other data.
Different multiples also change the risk cap if that cap governs the minimum.
Exit differences occur when a later bar touches one stop but not the other;
entry eligibility differs when entry crosses the legacy stop or target.
These effects already have explicit examples below. Their possibility does
not establish which model satisfies an as-yet undecided strategy contract.

## Documented path differences

| Surface | Legacy TrendMirrors | Generic validation path |
|---|---|---|
| Signal source | Four-mirror adapter plus mirror-specific plan checks | Strategy generate_signals |
| Initial stop anchor | Signal Close | Actual next-bar Close |
| Target | Signal-relative, adjusted for required net reward/risk | Entry-relative ATR multiple, no equivalent target expansion |
| Sizing/value | Signal Close and planned risk distance | Actual entry and resolved stop distance |
| Reported R denominator | Planned risk_egp, including stop costs | Raw actual-entry distance times shares |
| Trailing | Enabled | Disabled |
| Final-bar entry | Existing END behavior retained | Requires a post-entry bar |
| Nonpositive stop | No equivalent explicit plan guard | ContractError aborts run |
| VWAP definition | Shared causal engine VWAP_ref | Same shared causal engine VWAP_ref |

VWAP's intraday/mixed fix is not new-path-only. The engine definition is
shared, and tested causal prefixes match precomputed indicator slices.
This table inventories inspected differences; it is not proof that no
unlisted difference exists under every input or dynamic substitution.

## Hand-derived discriminating scenarios

Assumptions: long position, signal Close=100, ATR(signal)=2, stop multiple=1.5,
target multiple=3, zero fees/tax/slippage. Default legacy reward_risk=2.
No trailing, filler, break, sizing cap or terminal liquidation complication.
These are formula examples, not backtest results or performance estimates.

| Actual entry | Legacy stop / target | Generic stop / target | Difference |
|---:|---:|---:|---|
| 100 | 97 / 106 | 97 / 106 | Anchors agree only in this flat-entry example |
| 102 | 97 / 106 | 99 / 108 | Legacy raw distance to stop is 5, generic is 3 |
| 98 | 97 / 106 | 95 / 104 | Legacy raw distance to stop is 1, generic is 3 |
| 110 | 97 / 106 | 107 / 116 | Legacy skips entry above target; generic levels permit it |
| 96 | 97 / 106 | 93 / 102 | Legacy skips entry below stop; generic levels permit it |

For entry=102, a later candle Low=98, High=103, Close=102 touches the generic
stop 99, not legacy stop 97. With trailing disabled, generic closes at 99;
legacy does not exit on that candle. This discriminates behavior, not just fields.

For a hypothetical risk budget of 600 EGP with other caps nonbinding, both
paths size 200 shares from a 3 EGP planned distance. At entry=102 the legacy
raw stop-distance exposure is nevertheless 1,000 EGP; generic is 600 EGP.
This excludes fees and gaps beyond the stop: neither figure is a guaranteed
maximum loss. Legacy risk_egp additionally includes modeled stop costs.

## Recommendation for Ahmed

Preserve TrendMirrors as a versioned legacy model, and explicitly retain
actual-entry anchoring for generic ATR-distance policies. Do not silently
re-anchor TrendMirrors to retire the debt or force a passing parity test.
If one unified model is required, prefer actual-entry anchoring for that NEW
model, including recalculated sizing/value/risk and an explicit target-cost
policy. Treat migration as a separate reviewed impact analysis, not a refactor.
Ahmed has now adopted actual-execution anchoring for future production and
retained legacy as a noncompliant research reference. Current code is unchanged.

## Decision and verification boundary

Ahmed can accept two distinct versioned models, or request a unified model
and its impact study. Neither choice alone proves full-trade parity. Target
fee adjustment, trailing, terminal entry handling and risk denominators also
differ today. The skipped debt-retirement test must not be unskipped merely
because the stop anchor is chosen; replace/revise its purpose only with an
explicit reviewed contract and genuinely implemented verification.

No MC gate change, no push, no D strategy and no new optimization are included.

## Remaining open items

- P1B-DIFF-TEST: cancellation path and broader differential edge coverage.
- Dynamic dispatch: documented limitation; runtime verification deferred.
- test_legacy_vs_new_path_trade_match: SKIPPED.
- New-path versus legacy parity: unverified.
- VWAP definition against an external specification: unverified.
- Human approval of the evidence file: pending; this decision is not that approval.
- Expansion to 20 stocks: outside the current scope.

See KNOWN_ISSUES.md for verification debt. This closes the reference decision,
not those items; no further implementation is authorized by this closure.
