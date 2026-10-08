# Strategy status

## 4 Mirrors (trend following) — ABANDONED, decided 2026-10-08 (Ahmed)

**Strategy:** `egx_4_mirrors_v3` — screener + ADX gate + 4 mirrors (Trend, Momentum, Volume, Volatility) all true →
BUY; entry at the next session's Close; ATR stop/target with a trailing stop. Interface: `strategies.TrendMirrors`
(`STRATEGIES["trend_mirrors"]`). The code stays: the live scanner, dashboard, bot and the strategy factory's identity
tests still use it. It is no longer a candidate for real money.

### Final numbers (counterfactual run 2026-10-08, data/ through 2026-10-07, 90 stocks × 100,000 EGP, dividends added)

| Metric | A: all 4 mirrors | B: Volume mirror removed | Buy & hold |
|---|---|---|---|
| Total trades | 288 | 516 | — |
| Winners / losers | 44.4% / 55.6% | 42.1% / 57.9% | — |
| Avg win / avg loss (EGP) | 1,475 / −782 | 1,523 / −769 | — |
| Expectancy per trade (EGP) | +221.4 | +194.9 | — |
| Net profit (EGP) | +63,772 | +100,552 | +3,978,765 |
| Return on 9,000,000 | **+0.71%** | **+1.12%** | **+44.21%** |
| Max drawdown (combined equity) | −0.24% | −0.33% | — |
| Stocks beating buy & hold | 12/90 | 13/90 | — |
| Median holding period (sessions) | 6 | 7 | — |

Raw results: `outputs/counterfactual_volume/` (gitignored: A/B trades, per ticker, comparison). B was a one-off run
with the Volume mirror forced to pass outside the repo; no default changed.

Supporting evidence: `mirrors_failure_analysis.md` (Codex, 2026-10-08), `decision_report.md` (first ABANDON verdict),
`KNOWN_ISSUES.md` → "Strategy vs Buy & Hold". Mirror rejection rates (`--backtest` table): of 10,570 bars that reach
the mirrors, Volume is the sole blocker on 1,865 (17.6%), Momentum 1,012, Trend 225, Volatility 1.

### Root cause (assessment)

Not a single mirror: removing the strongest blocker (Volume) adds trades with *lower* expectancy and the result stays
far below buy & hold (+1.12% vs +44.21%). The strategy keeps only a few percent of capital deployed (≈3% average
exposure in the optimizer report) in a market that rose ~44% in the same year, and its trend entries on EGX's thin,
noisy daily bars mostly end in stop-outs (55–58% losers). The assessment is a category problem — trend following on
this market and data — not a tuning problem. This is a judgement from one year of data on 90 stocks, not a proof for
every regime.

### Decision

Move to the strategy factory with **non-trend strategies**, each validated by the Phase 1b layer
(`PHASE_1B_PLAN.md`) before any result is trusted. No further tuning of 4 Mirrors.

### Open items carried forward (from `KNOWN_ISSUES.md`)

- **Entry-price mismatch:** the live scanner shows Close[i] (the signal candle) as the entry and sizes SL/TP/shares
  from it; the backtest fills at Close[i+1]. Documented, not fixed.
- **pattern_detector reads raw High/Low including Volume 0 rows** (the indicators and signals no longer do).
- **DST midnight trap in synthetic test fixtures** (2026-04-24): needs one shared noon-timestamp fixture helper.
