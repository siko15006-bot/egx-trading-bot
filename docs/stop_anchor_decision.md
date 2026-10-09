# P1B-STOP-ANCHOR: decision brief

Status: OPEN. Decision owner: Ahmed. Technical recommendation: Codex.
Prepared 2026-10-09 against HEAD 08e167b. No model change or new backtest.

## Verified current behavior

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
This recommendation has not been accepted; current code remains unchanged.

## Decision and verification boundary

Ahmed can accept two distinct versioned models, or request a unified model
and its impact study. Neither choice alone proves full-trade parity. Target
fee adjustment, trailing, terminal entry handling and risk denominators also
differ today. The skipped debt-retirement test must not be unskipped merely
because the stop anchor is chosen; replace/revise its purpose only with an
explicit reviewed contract and genuinely implemented verification.

No MC gate change, no push, no D strategy and no new optimization are included.
