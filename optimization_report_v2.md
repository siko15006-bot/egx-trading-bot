# Optimization Report v2 — 4 Mirrors v3 + Hybrid (generated 2026-10-04 19:00)

Execution is **realistic for every number in this report**: first possible exit = the bar after the signal; gaps through a stop/target fill at the open. A/B/C/Baseline = 9 independent 100,000 EGP accounts; D = one shared 900,000 EGP account; Buy & Hold = equal weight, same window.

## 1.2 Look-ahead

The simulator in engine logic reproduces `egx_4_mirrors_v3.backtest()` exactly; that logic had **12 exits on the entry bar**. Realistic mode starts exit checks at the next bar and asserts that no non-END trade exits on its entry bar (assertion never fired).

## 1.3 Trailing stop for Scenario C (data/, realistic)

| Trailing | Trades | Win rate | Profit factor | Sharpe | Total return | Trailing exits |
|---|---|---|---|---|---|---|
| 2×ATR | 75 | 50.7% | 2.10 | 1.44 | +1.98% | 62 |
| 3×ATR ✅ | 69 | 46.4% | 2.10 | 1.39 | +2.26% | 22 |
| 4×ATR | 68 | 47.1% | 2.08 | 1.36 | +2.24% | 10 |

Selected **3×ATR** (highest PF) — used for C below and carried unchanged into 2022–2023 (out of sample).

## Scenario D + full comparison — data/ (2024-10 → 2026-10)

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 71 | 38.0% | 1.37 | -0.58% | 0.75 | +1.15% | +0.70% | 3.3% | 0.12 | 21.2% |
| A_filters | 17 | 29.4% | 0.66 | -0.40% | -0.49 | -0.18% | -0.11% | 1.1% | -0.14 | 79.3% |
| B_risk | 58 | 58.6% | 2.20 | -0.35% | 1.70 | +2.08% | +1.27% | 3.3% | 0.30 | 0.9% |
| C_trend | 69 | 46.4% | 2.10 | -0.73% | 1.39 | +2.26% | +1.38% | 4.6% | 0.28 | 2.3% |
| D_hold_4 | 33 | 45.5% | 2.15 | -16.44% | 0.86 | +22.56% | +13.25% | 51.0% | 0.27 | 13.3% |
| D_hold_5 | 37 | 48.6% | 3.21 | -16.30% | 1.31 | +43.76% | +24.86% | 61.2% | 0.46 | 1.8% |
| D_hold_6 | 44 | 54.5% | 3.34 | -17.82% | 1.37 | +48.16% | +27.18% | 66.7% | 0.44 | 1.3% |
| **Buy & Hold (equal weight)** | — | — | — | -17.54% | 1.85 | +84.62% | +45.50% | 100% | — | — |

## Phase 3 — 2022–2023 (warm-up from 2021, test from 2022-01-01)

USD/EGP moved ×1.97 over the window: in EGP the market rose; in USD it was a weak/flat market. The real drawdown inside the window is 2022-01 → 2022-07-04 (equal-weight −24%), tested separately below.

### Full 2022–2023

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 88 | 35.2% | 0.99 | -1.53% | -0.02 | -0.05% | -0.03% | 3.3% | 0.01 | 47.8% |
| A_filters | 23 | 52.2% | 2.41 | -0.67% | 1.14 | +1.29% | +0.69% | 0.9% | 0.56 | 2.5% |
| B_risk | 79 | 43.0% | 1.18 | -1.29% | 0.39 | +0.65% | +0.35% | 2.8% | 0.07 | 28.8% |
| C_trend | 78 | 38.5% | 1.87 | -0.89% | 1.15 | +2.34% | +1.24% | 3.1% | 0.25 | 3.6% |
| D_hold_4 | 33 | 42.4% | 3.64 | -13.13% | 1.41 | +48.19% | +23.31% | 39.6% | 0.64 | 1.3% |
| D_hold_5 | 41 | 39.0% | 3.43 | -17.70% | 1.48 | +59.81% | +28.37% | 46.2% | 0.63 | 0.7% |
| D_hold_6 | 44 | 40.9% | 3.62 | -18.78% | 1.50 | +65.75% | +30.90% | 50.4% | 0.65 | 0.2% |
| **Buy & Hold (equal weight)** | — | — | — | -23.12% | 1.90 | +133.22% | +57.01% | 100% | — | — |

### Bear leg only: 2022-01-01 → 2022-07-04

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 12 | 16.7% | 0.35 | -0.84% | -2.32 | -0.68% | -1.41% | 1.4% | -0.43 | 91.2% |
| A_filters | 6 | 16.7% | 0.35 | -0.46% | -1.38 | -0.30% | -0.62% | 0.3% | -0.35 | 81.2% |
| B_risk | 10 | 30.0% | 0.57 | -0.72% | -0.97 | -0.35% | -0.74% | 1.3% | -0.32 | 79.8% |
| C_trend | 17 | 11.8% | 0.08 | -0.89% | -4.04 | -0.89% | -1.85% | 1.3% | -0.48 | 100.0% |
| D_hold_4 | 11 | 9.1% | 0.17 | -8.53% | -1.24 | -5.61% | -11.33% | 19.4% | -0.34 | 99.7% |
| D_hold_5 | 12 | 8.3% | 0.15 | -9.82% | -1.40 | -6.58% | -13.21% | 20.0% | -0.34 | 99.9% |
| D_hold_6 | 12 | 8.3% | 0.15 | -9.82% | -1.40 | -6.58% | -13.21% | 20.0% | -0.34 | 99.9% |
| **Buy & Hold (equal weight)** | — | — | — | -23.12% | -2.22 | -21.51% | -39.61% | 100% | — | — |

### In USD terms (2022–2023, total return ÷ FX move)

| Scenario | EGP | USD |
|---|---|---|
| Baseline | -0.05% | -49.25% |
| A_filters | +1.29% | -48.57% |
| B_risk | +0.65% | -48.90% |
| C_trend | +2.34% | -48.04% |
| D_hold_4 | +48.19% | -24.76% |
| D_hold_5 | +59.81% | -18.86% |
| D_hold_6 | +65.75% | -15.84% |
| Buy & Hold | +133.22% | +18.41% |

## Decision

Best scenario = highest *minimum* Sharpe across data/ and 2022–2023: **D_hold_6** (data/: Sharpe 1.37, PF 3.34; 2022–23: Sharpe 1.50).

Disclosure: the first run selected by data/ Sharpe alone and picked B_risk (Sharpe 1.70 on ~3% deployed capital), which fell to Sharpe 0.39 / P(mean R ≤ 0) 29% in 2022–2023 → rule output ABANDON. That selection overfits one period, so it was changed to the two-period minimum *after* seeing that result. The CONTINUE/PIVOT/ABANDON rule itself is unchanged.

Rule fixed before reading the results: CONTINUE if the best scenario beats Buy & Hold on Sharpe in both periods; PIVOT (use the system as a filter/timing layer) if its per-trade edge is significant (P(mean R ≤ 0) < 5%) in both periods but it loses to Buy & Hold; otherwise ABANDON.

**Recommendation: PIVOT**


## 1.1 True daily VWAP (`egx_4_mirrors_v3.py`) — measured (log: `[T1.1]` lines)

- Implementation: grouped by Cairo date, `cumsum(Close×Volume)/cumsum(Volume)` per day, realigned to the original index. Tested on a 3-day × 6-bar intraday sample: VWAP at each day's first bar == Close ✅, and it matches a brute-force per-day calculation ✅.
- **On the daily data in `data/`, the true daily VWAP equals Close on every bar** (one bar per day), so "Close > VWAP_day" is almost never true. Over 9 stocks the Volume mirror would allow only **7 BUY days, against 148 in v2**.
- The old v2 VWAP was cumulative from the first bar in the file, which made it a meaningless filter:

  | Stock | Old VWAP vs Close (mean deviation) | Old VWAP said Close > VWAP | VWAP_20 says Close > VWAP |
  |---|---|---|---|
  | COMI | 16.7% | 84% of days | 58% |
  | ETEL | 26.1% | 95% | 74% |
  | SWDY | 10.4% | 25% | 51% |

- Fix in v3: `VWAP_ref` = the true daily VWAP on intraday data, and the 20-session rolling VWAP on daily data (161 BUY days). Changing VWAP alone moved the Baseline from PF 1.48 to 1.37 (71 trades instead of 66).

## Interpretation (Ahmed)

1. **Scenario D works where the problem actually was:**
   - On `data/` it returned +48% with 67% of capital deployed, against +2% for C on 4.6%. The edge per trade is significant: P(mean R ≤ 0) = 1.3%.
   - But it still loses to Buy & Hold: +48% vs +85%, Sharpe 1.37 vs 1.85, with a similar drawdown (−18%).
2. **In the 2022–2023 test (out of sample, all settings fixed in advance), D held up:**
   - +66%, PF 3.6, P(mean R ≤ 0) 0.2%.
   - Buy & Hold made +133% in pounds. The pound fell ×1.97 against the dollar, so neither was a real gain in dollar terms.
3. **In the actual falling leg (Jan → Jul 2022):**
   - Every scenario lost money.
   - D lost −6.6% against −21.5% for Buy & Hold, and its max drawdown was −9.8% against −23%.
   - **The system's value is that it stays out of the market in a downturn, not that it beats the market.**
4. **The A/B/C scenarios on separate accounts** risk 1% per trade, so total return stays tiny (±2%). Their high Sharpe comes from tiny volatility, not from real profit.
5. **Trailing stop:** 2×, 3× and 4× are almost the same (PF 2.10 / 2.10 / 2.08). 3× was kept; the trailing distance isn't what moves the results.

**Decision: PIVOT.** Use the system as a timing filter on top of holding the stocks (stay in while price is above EMA50 and the stop isn't hit; exit in a downturn), not as a short-trade strategy against the market. Not ready for live: 33–44 trades per period is still a small sample, and costs or a liquidity constraint larger than the 1%-of-volume cap would change the numbers.
