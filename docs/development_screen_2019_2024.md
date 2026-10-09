# Development Screen: 2019-2024

Development screening only -- 2019-2024.
Legacy is non-compliant with position-cap rules.
Results do NOT establish baseline acceptance.
These are research-continuation criteria, not acceptance gates.

## Frozen Procedure

- One continuous legacy run, 2019-01-01 inclusive to 2025-01-01 exclusive,
  using the existing 18-stock development universe and net_assumption costs.
- No fitting, variants, filter changes, new downloads or walk-forward resets.
- Engine warmup and one-position-per-stock behavior retained; terminal END
  liquidation retained. EFIH has partial history from 2021-10-20.
- Contribution: absolute per-stock total net P/L divided by the sum of
  absolute per-stock total net P/L; not a count-normalized concentration metric.
- Monthly cluster bootstrap: Cairo exit month, all stocks jointly, including
  empty months; 72 clusters sampled with replacement per draw, 10,000 draws,
  NumPy default_rng seed 42. Each mean is resampled total P/L divided by
  resampled trade count. CI uses the 2.5th and 97.5th percentiles.
- Protocol written and fingerprinted before execution. There were no
  zero-trade bootstrap draws and no alternative bootstrap after inspection.
- Frozen rule: no failed conditions means research continuation only; one
  means inconclusive/investigate; two or more means stop. Acceptance disabled.

## Screen Results

| Research-continuation condition | Observed | Condition met |
| --- | --- | --- |
| Completed net trades >= 300 | 315 | Yes |
| Mean net P/L > 0 | 2.598637 EGP/trade | Yes |
| 95% CI lower bound > 0 | [-188.818840, 190.226675] EGP/trade | No |
| Maximum stock contribution <= 30% | MASR.CA, 16.050130% | Yes |

Frozen-rule outcome: INCONCLUSIVE (one failed condition). No positive mean
has been established statistically under this bootstrap. This does not prove
absence of an edge. No new strategy experiment was run after this result.

- Total net P/L: 818.570723 EGP; cancelled trades: 0; terminal END trades: 1.
- Empty months: 14; median holding period: 9 calendar days.
- One stock has contribution above 15%.
- Actual-entry model notional exceeded the position-value cap on 68/315
  trades (21.59%). Legacy remains a non-compliant research reference.
- 137 protected code/input/previous-artifact files were unchanged. All 28
  screen artifact hashes verified after publication.

## Existing-Trade Distribution Inspection

This inspection reads the existing 315 trades only. It does not rerun signals,
execution, bootstrap, or any strategy variant.

| Statistic | EGP unless stated otherwise |
| --- | --- |
| Sample standard deviation (ddof=1) | 1190.403567 |
| Median net P/L | -118.676292 |
| 5th / 95th percentiles | -1460.320870 / 2107.159267 |
| Minimum / maximum | -3933.024096 / 2581.030582 |
| Winners / losers / flat trades | 116 / 199 / 0 |
| Sum of positive trade P/L | 155920.905054 |
| Sum of negative trade P/L | -155102.334331 |
| Profit factor | 1.005278 |
| Top five net P/L sum | 12292.506673 |
| Top five share of positive trade P/L | 7.883809% |
| Bottom five net P/L sum | -11804.209338 |

The top-five-outlier hypothesis (90% of positive trade profits) is not
supported by these numbers. Dividing top-five profits by the tiny overall net
balance would instead produce an unstable and misleading concentration ratio.
Removing the top five gives -11473.935949 EGP, a descriptive calculation only,
not a new exclusion rule or robustness gate.

| Top five ticker | Net P/L | Reason |
| --- | --- | --- |
| TMGH.CA | 2581.030582 | TP |
| AMOC.CA | 2554.722225 | TP |
| SWDY.CA | 2399.016681 | TP |
| EAST.CA | 2386.132347 | TP |
| CIEB.CA | 2371.604838 | TP |

| Bottom five ticker | Net P/L | Reason |
| --- | --- | --- |
| HRHO.CA | -3933.024096 | SL |
| HRHO.CA | -2053.150715 | SL |
| PHDC.CA | -1977.946920 | SL |
| TMGH.CA | -1935.401842 | SL |
| AMOC.CA | -1904.685766 | SL |

## Cost Reconciliation

The +2.60 EGP mean is NET under the frozen cost assumptions. For those exact
entries, exits and shares, sum((exit-entry)*shares) is 49888.631990 EGP.
Modeled fees/tax/slippage reduce it by 49070.061267 EGP to 818.570723 EGP.
This same-fill price-only arithmetic is NOT a separate gross strategy run:
legacy targets can depend on costs, so a zero-cost run could change trades.

Recomputing every net P/L with the existing net_trade_pnl and frozen settings
matched with maximum absolute difference 0.0. This verifies internal
consistency, not independent correctness or historical tariff validity.
Position-cap breaches are separately documented, not diagnosed as a P/L bug
by this reconciliation.

## Interpretation Limits

- A CI spanning zero is lack of positive-mean evidence, not proof of no edge.
  No defensible required-trade-count estimate is derived from this CI alone.
- Independent months are assumed, not guaranteed by having 72 clusters;
  dependence and overlapping positions across month boundaries are not kept.
- Data quality, licensing, corporate adjustments, historical cost validity,
  execution feasibility and point-in-time universe membership are unverified.
- Historical provider-adjusted OHLC and unchanged volume use synthetic units.
- The selected data are development data, not a sealed independent holdout.
- Zero cancellations do not exercise or validate the cancellation branch.
- Existing single-position behavior is not independent evidence of original
  strategy intent. Generic/legacy parity and deferred verification remain open.
- No acceptance gate enabled; no profitability or tradability claim; no
  automatic variant testing or additional data expansion follows this report.

## Reproducibility References

Full artifacts and external harnesses are LOCAL, not tracked in Git. This
tracked summary retains the findings and hashes without claiming the local
artifact paths will exist in a fresh clone.

Screen artifacts: outputs/development_screen_2019_2024_20261009/.
Inspection artifacts: outputs/development_screen_2019_2024_pnl_inspection_20261009/.

| Local evidence | SHA-256 |
| --- | --- |
| Screen protocol.json | 76f8b85e1844870ca146796805fa529fecc6fa0e8c8d68327119920dd8fab6bb |
| Screen trades.csv | c90556d5c4a5e42ed99a7eabdb82c19984cf57a957dcbff63274477e9afd26ee |
| Screen summary.json | 276c754e6cfcf36ff8e39daace3248b6379dfec89605eb73f202fa09f23514ed |
| Inspection harness | 88665af7ec1d2bd27ba51cd1ab2ae85daeb0b13e20a7230dc09f54aaaf15208f |

Screen ran from HEAD 6624d1f with existing working-tree development helpers.
Protocol records actual code fingerprints, settings, sliced coverage and
screen harness hash; HEAD alone does not identify every local helper.
