# H3 — AI Score: cross-sectional ranking by logistic regression (pre-registration)

Written 2026-10-07, **before** any feature, label or model was computed. Changing anything below after seeing
validation results = H3 failed. Edits before the first run go in the edit log.

## Question

Does a simple model, trained only on 2019–2022, rank EGX stocks so that the ranking carries information about the
next month's relative return? Two levels, decided separately:

- **Level 1 — trading signal:** the top 10 by score beat the equal-weight eligible universe (same test as H1).
- **Level 2 — screening tool only:** the score is positively rank-correlated with next-month excess return, even if
  the top 10 do not beat equal weight.

## Data and universe (same as H1)

`data_momentum_2019/` (403 tickers, fully adjusted, 2019-01 → 2026-10), filler rows excluded. Each rebalance day
(every 21 sessions, the H1 grid): eligible = ≥147 real bars, ≥15 real of last 21, real bar today, top 60 by 63-day
median traded value.

## Features (known at the rebalance close; each converted to its percentile rank among that day's eligible stocks)

1. return t−21→t  2. return t−63→t  3. return t−126→t−21  4. return t−252→t (NaN if <252 bars → rank 0.5)
5. 63-day daily-return volatility  6. RSI14 (close)  7. (close − EMA50) / (63-day vol × close)
8. position of close in its 252-day high–low range  9. 5-day / 63-day median traded value
10. 63-day median traded value (liquidity)

## Label and model

- Forward excess return = stock's return t→t+21 minus the mean of that day's eligible stocks. `y = 1` if > 0.
- Logistic regression, standardised features, C = 1.0, fit **once** on all train rebalance days whose t+21 is before
  2023-01-01. No refit, no tuning, no other model.
- Score on every validation rebalance day (2023-01-01 → last day with t+21 available for Level 2; to the last
  available day for Level 1).

## Level 1 (all must hold, USD, same harness and costs as H1)

Portfolio = top 10 eligible by score, equal weight, rebalanced every 21 sessions, 0.15% per side; benchmark = equal
weight of the same eligible 60. Criteria identical to H1:
1. validation Sharpe(H3) − Sharpe(EW) ≥ 0.30  2. validation CAGR(H3) > CAGR(EW)
3. validation max DD not worse than EW by > 10 pp  4. train-period Sharpe(H3) > Sharpe(EW) (in-sample, sanity only)

## Level 2

Per validation rebalance day: Spearman correlation between score and forward 21-session excess return across the
eligible stocks. Windows do not overlap (21-session forward = rebalance spacing), so the daily values are treated as
independent. **Pass if the mean is > 0 with a one-sided t-test p < 0.05.**

## Decision table

| Level 1 | Level 2 | Meaning |
|---|---|---|
| pass | pass | trading-signal candidate (still needs Ahmed's approval; forward-tracked before any money) |
| fail | pass | screening tool only: may be shown in the dashboard labelled "أداة فرز، مش إشارة" |
| pass | fail | suspect (likely sample noise): not used until confirmed on a second validation window |
| fail | fail | H3 closed, nothing displayed |

No retry with other features, models, horizons or thresholds.

## Known limits

Survivorship (today's 403 names); EGP inflation (handled by cross-sectional ranks + USD for Level 1);
~45 validation rebalance days only — a small sample for Level 2.

## Result (single run, 2026-10-07) — **Level 1 PASS, Level 2 PASS → trading-signal candidate**

Full output: `H3_result.txt`, code: `research_h3_ai_score.py`. Train 2,274 stock-days on 38 rebalance days.

| USD | H3 Sharpe | H3 CAGR | H3 max DD | EW Sharpe | EW CAGR | EW max DD |
|---|---|---|---|---|---|---|
| Train (in-sample) | 1.37 | +38.2% | −36.8% | 0.14 | −0.3% | −52.2% |
| **Validation 2023→** | **1.31** | **+47.2%** | −54.3% | 0.83 | +23.7% | −53.3% |

Level 2: 41 validation days, mean Spearman IC +0.063, positive on 71% of days, one-sided p = 0.009.
Largest weights: near the 252-day high (+), last-month return (−, short-term reversal), 6-1 momentum (−),
liquidity (−), volatility (−).

**Post-hoc checks (information only — they do not change the pre-registered verdict):**
- Executing one session later (features one day stale, which is what Ahmed can actually do after the close):
  validation USD Sharpe 1.04 vs 0.83, CAGR +33.6% vs +23.7%. Still ahead of EW, but the Sharpe gap (0.21) would
  **not** clear the 0.30 bar — part of the edge comes from trading at the same close (short-term reversal).
- Without the last-month-return feature: validation USD Sharpe 1.13, CAGR +38.4% — the result does not rest on
  that single feature.

**What this does and does not mean:** one 3.8-year validation window, survivorship-biased universe, no taxes or
slippage. It is a candidate, not a proven strategy. Next step (needs Ahmed's approval): forward-track the daily
top 10 with no money for at least 3 months, then judge on those results only.

## Classification after review (2026-10-07)

Level 1 is judged on **realistic execution** (Ahmed sees the score after the close and buys at the next open).
Under that standard the Sharpe gap is 0.21 < 0.30, so: **Level 1 = PENDING, Level 2 = PASS.** No real money.

## Forward test protocol (fixed before it starts)

- **Model frozen:** coefficients and scaler from the 2019–2022 fit saved in `docs/research/H3_model.json`. Never refit.
- **Schedule:** a rebalance every 21 EGX sessions, counted on the production calendar (`data/`); the first one is the
  first session processed after this commit. Run daily by the scheduled task `EGX_H3_Forward`.
- **Universe / top 10:** same 403 candidates, freshly downloaded fully adjusted (`data_h3_live/`), H1 eligibility
  (≥147 real bars, ≥15 real of last 21, real bar on the day, top 60 by 63-day median traded value), no price filter.
  Top 10 = highest score; ties broken by ticker A→Z. Benchmark = equal weight of the same 60.
- **Two executions recorded:** ideal (close of the rebalance day → close of the next) and realistic (close of the
  next session → close of the session after the next rebalance; see edit log). Both net of 0.3% per period for the top 10
  (full turnover assumed) and 0 for the benchmark. Realistic periods complete one session later.
- **Kill switch (realistic):** stop if cumulative top-10 return minus cumulative EW return ≤ −10 percentage points at
  any completed period.
- **After 3 periods:** judge operation only (runs on time, no errors, messages arrive). No performance verdict.
- **After 12 periods (~1 year), realistic execution decides:**
  1. cumulative top-10 return > cumulative EW return, **and**
  2. mean per-period Spearman IC > 0 (one-sided t-test p < 0.10 — n = 12 is small).
  Both → "confirmed candidate": Ahmed may decide on small real money; the forward test continues.
  Either fails → H3 closed for trading; the score may stay as a screening tool only if (2) holds.
  No changes to features, model or schedule during the 12 periods; any change restarts the count as a new hypothesis.
- **Separate from auto-sim:** own table `h3_forward`, own dashboard section, own Telegram message.

## Edit log

- 2026-10-07: created (replaces the H2 filter idea; two-level decision agreed in review).
- 2026-10-07 (after the run): classification on realistic execution and forward-test protocol added; no change to the run.
- 2026-10-07 (before any completed period): realistic leg changed from next Open to next close (Yahoo's EGX Open is not a real
  opening price, KNOWN_ISSUES.md), and stocks with a >25% data break inside a period are left out of both averages.
  Model, features, universe and schedule unchanged, so the 12-period count is not restarted.
