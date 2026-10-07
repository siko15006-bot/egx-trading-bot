# Optimization Report v2 — 4 Mirrors v3 + Hybrid (generated 2026-10-08 02:05)

Execution is **realistic for every number in this report**: entry at the close after the signal, first exit on the bar after that; fills per `docs/execution_policy.md` (level, or that bar's Close on a gap — never the Open; zero-volume rows never fill; trades across a data break cancelled). A/B/C/Baseline = one independent 100,000 EGP account per stock; D = one shared account of the same total; Buy & Hold = equal weight, same window.

## 1.2 Look-ahead

The simulator in engine logic reproduces `egx_4_mirrors_v3.backtest()` exactly; that logic had **2 exits on the entry bar**. Realistic mode starts exit checks at the next bar and asserts that no non-END trade exits on its entry bar (assertion never fired).

## 1.3 Trailing stop for Scenario C (data/, realistic)

| Trailing | Trades | Win rate | Profit factor | Sharpe | Total return | Trailing exits |
|---|---|---|---|---|---|---|
| 2×ATR | 357 | 43.7% | 2.07 | 3.55 | +1.00% | 284 |
| 3×ATR | 310 | 44.5% | 2.84 | 4.71 | +1.59% | 100 |
| 4×ATR ✅ | 298 | 45.3% | 3.28 | 4.98 | +1.91% | 23 |

Selected **4×ATR** (highest PF) — used for C below and carried unchanged into 2022–2023 (out of sample).

## Scenario D + full comparison — data/ (2024-10 → 2026-10)

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 309 | 44.3% | 1.50 | -0.24% | 2.35 | +0.76% | +1.00% | 2.9% | 0.23 | 0.1% |
| A_filters | 87 | 42.5% | 1.19 | -0.11% | 0.66 | +0.09% | +0.11% | 1.0% | 0.07 | 31.4% |
| B_risk | 276 | 46.4% | 1.99 | -0.24% | 3.58 | +1.02% | +1.34% | 2.5% | 0.32 | 0.0% |
| C_trend | 298 | 45.3% | 3.28 | -0.17% | 4.98 | +1.91% | +2.50% | 3.4% | 0.56 | 0.0% |
| D_hold_4 | 20 | 50.0% | 1.01 | -4.20% | 0.05 | +0.07% | +0.09% | 20.1% | 0.20 | 15.2% |
| D_hold_5 | 24 | 50.0% | 3.35 | -5.87% | 1.32 | +13.70% | +18.26% | 38.4% | 0.39 | 7.4% |
| D_hold_6 | 29 | 44.8% | 3.98 | -4.27% | 1.74 | +19.17% | +25.73% | 44.0% | 0.58 | 3.4% |
| **Buy & Hold (equal weight)** | — | — | — | -12.31% | 2.76 | +44.04% | +61.03% | 100% | — | — |

## Phase 3 — 2022–2023 (warm-up from 2021, test from 2022-01-01)

USD/EGP moved ×1.97 over the window: in EGP the market rose; in USD it was a weak/flat market. The real drawdown inside the window is 2022-01 → 2022-07-04 (equal-weight −24%), tested separately below.

### Full 2022–2023

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 87 | 35.6% | 0.88 | -1.39% | -0.33 | -0.62% | -0.33% | 3.0% | -0.04 | 64.1% |
| A_filters | 21 | 66.7% | 3.33 | -0.25% | 1.51 | +1.26% | +0.67% | 0.8% | 0.67 | 0.5% |
| B_risk | 77 | 42.9% | 1.09 | -1.25% | 0.19 | +0.32% | +0.17% | 2.6% | 0.04 | 38.7% |
| C_trend | 77 | 40.3% | 1.72 | -1.17% | 1.01 | +1.97% | +1.05% | 3.1% | 0.22 | 7.0% |
| D_hold_4 | 36 | 38.9% | 3.22 | -12.31% | 1.26 | +42.35% | +20.70% | 38.5% | 0.59 | 1.6% |
| D_hold_5 | 42 | 38.1% | 3.32 | -17.55% | 1.38 | +54.72% | +26.18% | 45.6% | 0.62 | 0.7% |
| D_hold_6 | 45 | 40.0% | 3.44 | -18.83% | 1.40 | +60.21% | +28.54% | 49.8% | 0.63 | 0.2% |
| **Buy & Hold (equal weight)** | — | — | — | -23.12% | 1.90 | +133.22% | +57.01% | 100% | — | — |

### Bear leg only: 2022-01-01 → 2022-07-04

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 10 | 20.0% | 0.39 | -0.90% | -1.57 | -0.67% | -1.39% | 1.3% | -0.47 | 80.1% |
| A_filters | 4 | 50.0% | 1.79 | -0.14% | 0.78 | +0.19% | +0.39% | 0.4% | 0.84 | 25.4% |
| B_risk | 10 | 30.0% | 0.59 | -0.68% | -0.92 | -0.35% | -0.72% | 1.2% | -0.31 | 76.3% |
| C_trend | 15 | 6.7% | 0.00 | -1.10% | -4.41 | -1.10% | -2.28% | 1.2% | -0.67 | 100.0% |
| D_hold_4 | 12 | 8.3% | 0.21 | -9.49% | -1.83 | -7.51% | -15.00% | 18.5% | -0.34 | 99.0% |
| D_hold_5 | 12 | 8.3% | 0.21 | -9.27% | -1.73 | -7.28% | -14.57% | 18.7% | -0.33 | 99.0% |
| D_hold_6 | 12 | 8.3% | 0.21 | -9.27% | -1.73 | -7.28% | -14.57% | 18.7% | -0.33 | 98.5% |
| **Buy & Hold (equal weight)** | — | — | — | -23.12% | -2.22 | -21.51% | -39.61% | 100% | — | — |

### In USD terms (2022–2023, total return ÷ FX move)

| Scenario | EGP | USD |
|---|---|---|
| Baseline | -0.62% | -49.54% |
| A_filters | +1.26% | -48.59% |
| B_risk | +0.32% | -49.07% |
| C_trend | +1.97% | -48.23% |
| D_hold_4 | +42.35% | -27.72% |
| D_hold_5 | +54.72% | -21.44% |
| D_hold_6 | +60.21% | -18.66% |
| Buy & Hold | +133.22% | +18.41% |

## Decision

Best scenario = highest Sharpe on data/ only (in-sample); 2022–2023 is reported as an out-of-sample check on 9 large caps: **C_trend** (data/: Sharpe 4.98, PF 3.28; 2022–23: Sharpe 1.01).

Disclosure: the first run selected by data/ Sharpe alone and picked B_risk (Sharpe 1.70 on ~3% deployed capital), which fell to Sharpe 0.39 / P(mean R ≤ 0) 29% in 2022–2023 → rule output ABANDON. That selection overfits one period, so it was changed to the two-period minimum *after* seeing that result. The CONTINUE/PIVOT/ABANDON rule itself is unchanged. 2026-10-07: reverted to data/-only selection, because a two-period minimum lets the out-of-sample period choose the winner; overfitting now shows up in the 2022–2023 numbers instead.

Rule fixed before reading the results: CONTINUE if the best scenario beats Buy & Hold on Sharpe in both periods; PIVOT (use the system as a filter/timing layer) if its per-trade edge is significant (P(mean R ≤ 0) < 5%) in both periods but it loses to Buy & Hold; otherwise ABANDON.

**Recommendation: ABANDON**

