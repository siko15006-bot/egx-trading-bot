# H2 — ML filter for 4 Mirrors signals — **NOT RUN, superseded by H3**

> 2026-10-07: dropped before any data/model. A filter can only pick the better part of a ~breakeven, ABANDONed
> strategy; H3 (AI Score) tests an independent ranking instead. Kept for the record.

Written 2026-10-07, **before** any training data was built or any model was fit.
Changing anything below after seeing validation results = H2 failed. Edits before the first run go in the edit log.

## Question

Given a 4 Mirrors BUY signal (entry, SL, TP from `build_trade_plan`), can a model estimate the probability that it
reaches TP before SL well enough that **taking only the high-probability signals makes money after fees**?
This does not rescue the strategy (ABANDON, `decision_report.md`); it only asks whether a filter adds an edge.

## Target

- Trade simulated exactly as `auto_sim.replay`: entry at the signal-day close; exits checked from the **next** bar;
  SL before TP on the same bar; gap through a level fills at the Open; engine trailing rule; **max 30 sessions**.
- `y = 1` if the exit is TP; `y = 0` for SL, TRAIL_SL or the 30-session time exit.
- Also stored per trade: net return after 0.15% per side (used for the money criteria, not for training).

## Data

- Prices: `data_momentum_2019/` (403 tickers, 2019-01 → 2026-10, fully adjusted). Adjusted prices keep relative
  distances (ATR, SL/TP as % of entry) correct; dividends are inside the returns. Raw levels differ — fine for a filter.
- Universe each day: the H1 point-in-time eligibility (≥147 real bars, ≥15 real of last 21, top 60 by 63-day median
  traded value). Filler rows excluded (`KNOWN_ISSUES.md`).
- Signals: `passes_screener` + `evaluate_4_mirrors` + `build_trade_plan` on each eligible stock-day, default configs.
  One open trade per stock at a time (same as the engine). Expected: a few thousand trades.
- Split by signal date: **train 2019-07 → 2022-12**, **embargo** of the first 30 sessions of 2023 (no trade whose
  window crosses the split), **validation 2023 → end**. No validation data is used for any choice.

## Features (all known at the signal-day close)

ADX, ATR % of price, RSI14, MACD histogram / price, distance of close from EMA50 and from 20-day high (in ATR),
position in the 252-day range, volume / 20-day average, RR_Net, 20-day return of the stock, 20-day return of the
equal-weight eligible universe (market regime), stock's 63-day median traded value rank. No sector feature
(sector map is unverified).

## Models (fixed in advance)

1. Logistic regression (standardised features, C = 1.0). **This one decides.**
2. LightGBM with fixed parameters (200 trees, depth 3, learning rate 0.05) — reported for information only.
No hyper-parameter search. Threshold fixed in advance: take a trade when predicted p ≥ the **70th percentile of the
train predictions** (i.e. keep the top 30% by score).

## Success (validation, logistic regression, all must hold)

1. AUC ≥ 0.58.
2. Lift: TP rate of kept trades ≥ base TP rate of all validation trades + 5 percentage points.
3. Money: mean net return per kept trade > 0 **and** above the mean of all validation trades; 95% bootstrap CI of the
   kept mean excludes 0.
4. At least 100 kept trades in validation.

## Failure

Anything else. No retry with other features, models, thresholds or periods. If H2 fails, the next idea needs its
own document.

## Known limits (accepted up front)

- Survivorship: today's 403 names only.
- Trades overlap in time (many signals on the same days) → effective sample is smaller than the count; the bootstrap
  resamples by **signal day**, not by trade.
- Base strategy is ~breakeven; a filter can at most pick its better part.

## Outputs

Research only: no production, Telegram, auto-sim or paper-trading change unless all criteria pass **and** Ahmed approves.

## Edit log

- 2026-10-07: draft created (changes vs the proposed draft: target uses the auto-sim exit rules with a 30-session cap
  instead of the engine's same-bar exit; data from `data_momentum_2019` because `data/` has only 1 year; Precision and
  "Sharpe +20%" replaced by lift over base rate and per-trade money criteria, since the base strategy's Sharpe is ~0;
  embargo and day-level bootstrap added; threshold and model settings fixed in advance).
