# H1 — Cross-sectional momentum rotation (pre-registration)

Written 2026-10-06, **before** any momentum data was downloaded or any return was computed.
Changing anything below after seeing results = H1 failed. Edits before the first run are logged at the bottom.

## Why this hypothesis

4 Mirrors lost because it times entries and sits in cash (~3% to ~50% exposure) in a market whose EGP return is
mostly inflation/devaluation carry (`decision_report.md`). H1 is always invested and only chooses *which* stocks to hold.

## Hypothesis (one sentence)

EGX stocks with the highest 6-month return (skipping the last month) outperform an equal-weight portfolio of the
same universe over the following month, in USD, after fees.

## Decision rule (no free parameters)

- **Universe:** every ticker in `egx_universe.json` v90-20261005 `records` (401 candidates, passed or not) plus TALM
  and KZPC (large caps on Yahoo, missing from the manifest). Not limited to today's 90 "passed" names, because that
  filter uses today's liquidity and price (look-ahead). Large caps absent from Yahoo (Ezz Steel, QNB, EKHO, Valu,
  Madinet Nasr) cannot be included.
- **Eligibility (point-in-time, each rebalance day):** ≥ 147 real (non-filler, per `KNOWN_ISSUES.md`) bars,
  ≥ 15 real bars in the last 21, then the **top 60 by median daily traded value (Close × Volume, EGP) over the last
  63 bars**. Liquidity is ranked, not thresholded, so EGP inflation does not move the bar.
- **Prices:** fully adjusted Yahoo closes (`auto_adjust=True`, total return). Downloaded into `data_momentum_2019/`,
  which is added to `KNOWN_ADJUSTED_FOLDERS`.
- **Signal:** return from t−126 to t−21 trading days (close to close).
- **Portfolio:** top 10 eligible stocks by signal, equal weight. Fewer than 10 eligible → hold all eligible.
- **Rebalance:** every 21 trading days, at the close (signal and trade at the same close; no look-ahead beyond it).
- **Costs:** `RiskConfig.round_trip_fee_pct` (0.3%) on turnover. Taxes ignored for both sides.
- **Benchmark:** equal-weight, same eligible (top-60) universe, same rebalance dates and costs. Same survivorship bias on
  both sides, so the comparison is fair even though absolute returns are not.
- **Currency:** USD via `data_2019_2026_wf/fx/EGP_USD.csv` (primary). EGP reported alongside.

## Sample split (fixed)

- **Train:** first eligible rebalance → 2022-12-31. Used only to confirm the code runs and the direction. No tuning.
- **Validation:** 2023-01-01 → last available day. This decides.

## Success (all must hold, in USD)

1. Validation: Sharpe(H1) − Sharpe(benchmark) ≥ 0.30.
2. Validation: CAGR(H1) > CAGR(benchmark).
3. Validation: max drawdown(H1) not worse than benchmark by more than 10 percentage points.
4. Train: Sharpe(H1) > Sharpe(benchmark) (same direction).

## Failure

Anything else. No retry with other lookbacks, N, or rebalance frequency. Reported for information only, never for
choosing: lookback 63/252 days, N = 5/15. If H1 fails, the next hypothesis needs its own document.

## Known biases (accepted up front)

- **Survivorship:** the universe is today's 90 survivors; delisted/collapsed names are missing. Inflates both H1 and
  the benchmark; may favour momentum (losers that died are absent). Treat a marginal pass as a fail.
- **Yahoo gaps:** ~2–4.5% missing sessions/year (`docs/egx_missing_days.csv`); filler rows excluded from eligibility.
- **Liquidity:** no volume cap on position size; small EGX names may not absorb real orders.

## Outputs

Nothing goes to production, Telegram, or paper trading unless all success criteria pass **and** Ahmed approves.

## Edit log

- 2026-10-06: created.
- 2026-10-06 (before any download/run): universe widened from the 90 passed names to all 401 manifest candidates
  + TALM, KZPC, with a point-in-time top-60 liquidity rank. Reason: Ahmed asked for more large caps; the 90-name
  filter used today's liquidity/price (look-ahead) and dropped large low-priced names such as BTFH.
