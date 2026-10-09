# Data Quality Findings: ADIB, EAST, EFIH

Recorded: 2026-10-09. All three cases remain UNRESOLVED.

This report distinguishes observations in saved local series from facts about
historical market trading. A confirmed discontinuity in a file is not a
confirmed market price movement or evidence of a provider error.

## Confirmed Local Observations

| Stock | Previous saved session | Discontinuity date | Saved values |
| --- | --- | --- | --- |
| ADIB | 2025-05-25 | 2025-05-26 | Close: 41.45 -> 20.945 |
| EAST | 2024-05-30 | 2024-06-02 | Adj Close: approximately 22.5779 -> 15.8100; destination Close: 19.3267 |
| EFIH | 2025-05-22 | 2025-05-25 | Adj Close: approximately 18.6627 -> 12.8446; destination Close: 13.1800 |

Evidence was read from data_2019_2026_wf/ and the saved Yahoo download under
outputs/yahoo_expansion_18_20261009/raw/. These local paths are not a promise
of artifacts available in a fresh clone. The downloads are not independent
market sources.

For EAST, Close and Adj Close on the same date are different fields, not
different sessions. Their adjustment policies and the corporate actions
reflected in these values have not been established.

For EFIH, the reported transition is Adj Close to Adj Close across consecutive
saved sessions. Comparing it with an external quoted price requires matching
adjustment policies first.

## Unresolved Interpretation

- The saved discontinuities precede the associated corporate-action dates
  discussed in the investigation by 4-15 calendar days. Record dates,
  entitlement cutoffs, distribution dates and first ex-entitlement trading
  sessions are not interchangeable.
- The cause of each discontinuity and the adjustment policy of Close and
  Adj Close in each source and saved file remain undetermined.
- The field name Close does not establish an unadjusted historical trade price.
- Neither Yahoo error nor source price accuracy is established.
- No conclusion is drawn that these discontinuities were real market moves.

## Evidence Needed to Resolve Each Case

1. Independent historical closing prices for the trading session immediately
   before the saved discontinuity and for the discontinuity session itself.
2. The last session carrying entitlement and the first session without it,
   confirmed as actual trading sessions, with independent closing prices.
3. Documented adjustment policies for each price field in every compared
   source; numbers must be compared on a consistent basis.
4. Corporate-action disclosures sufficient to distinguish entitlement,
   distribution and trading-effective dates and identify other relevant
   actions. For EFIH, a distribution date alone is not a reference-price date.

## Scope

Documentation only. No data or engine changes, no new backtest, no acceptance
decision, and no conclusions about source accuracy. Resolving these cases
requires independent source verification. TrendMirrors remains closed; these
findings do not reopen the strategy investigation.
