# Optimization Report v2 — 4 Mirrors v3 + Hybrid (generated 2026-10-08 03:12)

Execution is **realistic for every number in this report**: entry at the close after the signal, first exit on the bar after that; fills per `docs/execution_policy.md` (level, or that bar's Close on a gap — never the Open; zero-volume rows never fill; trades across a data break cancelled). A/B/C/Baseline = one independent 100,000 EGP account per stock; D = one shared account of the same total; Buy & Hold = equal weight, same window.

## 1.2 Look-ahead

The simulator in engine logic reproduces `egx_4_mirrors_v3.backtest()` exactly; that logic had **2 exits on the entry bar**. Realistic mode starts exit checks at the next bar and asserts that no non-END trade exits on its entry bar (assertion never fired).

## 1.3 Trailing stop for Scenario C (data/, realistic)

| Trailing | Trades | Win rate | Profit factor | Sharpe | Total return | Trailing exits |
|---|---|---|---|---|---|---|
| 2×ATR | 342 | 43.3% | 2.20 | 3.64 | +1.10% | 264 |
| 3×ATR | 307 | 43.3% | 2.73 | 4.37 | +1.56% | 92 |
| 4×ATR ✅ | 296 | 44.3% | 3.16 | 4.67 | +1.86% | 20 |

Selected **4×ATR** (highest PF) — used for C below and carried unchanged into 2022–2023 (out of sample).

## Scenario D + full comparison — data/ (2024-10 → 2026-10)

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 287 | 44.9% | 1.56 | -0.25% | 2.60 | +0.77% | +1.00% | 2.8% | 0.24 | 0.1% |
| A_filters | 84 | 47.6% | 1.48 | -0.10% | 1.62 | +0.21% | +0.27% | 0.9% | 0.21 | 6.5% |
| B_risk | 265 | 48.3% | 2.05 | -0.24% | 3.43 | +0.98% | +1.28% | 2.4% | 0.32 | 0.0% |
| C_trend | 296 | 44.3% | 3.16 | -0.17% | 4.67 | +1.86% | +2.44% | 3.5% | 0.55 | 0.0% |
| D_hold_4 | 20 | 55.0% | 1.21 | -4.20% | 0.22 | +0.97% | +1.26% | 20.2% | 0.22 | 11.0% |
| D_hold_5 | 24 | 50.0% | 3.56 | -5.64% | 1.33 | +13.93% | +18.56% | 38.5% | 0.39 | 6.2% |
| D_hold_6 | 29 | 44.8% | 4.17 | -4.27% | 1.75 | +19.34% | +25.97% | 44.3% | 0.58 | 3.3% |
| **Buy & Hold (equal weight)** | — | — | — | -12.31% | 2.76 | +44.04% | +61.03% | 100% | — | — |

## Phase 3 — 2022–2023 (warm-up from 2021, test from 2022-01-01)

USD/EGP moved ×1.97 over the window: in EGP the market rose; in USD it was a weak/flat market. The real drawdown inside the window is 2022-01 → 2022-07-04 (equal-weight −24%), tested separately below.

### Full 2022–2023

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 87 | 35.6% | 0.88 | -1.39% | -0.33 | -0.61% | -0.32% | 3.0% | -0.04 | 64.0% |
| A_filters | 20 | 65.0% | 2.98 | -0.25% | 1.35 | +1.07% | +0.57% | 0.7% | 0.60 | 1.2% |
| B_risk | 77 | 42.9% | 1.09 | -1.25% | 0.19 | +0.32% | +0.17% | 2.6% | 0.04 | 38.8% |
| C_trend | 77 | 40.3% | 1.72 | -1.17% | 1.01 | +1.97% | +1.05% | 3.1% | 0.22 | 7.1% |
| D_hold_4 | 36 | 38.9% | 3.22 | -12.31% | 1.26 | +42.35% | +20.70% | 38.5% | 0.59 | 1.4% |
| D_hold_5 | 42 | 38.1% | 3.32 | -17.55% | 1.38 | +54.72% | +26.18% | 45.6% | 0.62 | 0.6% |
| D_hold_6 | 45 | 40.0% | 3.44 | -18.83% | 1.40 | +60.21% | +28.54% | 49.8% | 0.63 | 0.4% |
| **Buy & Hold (equal weight)** | — | — | — | -23.12% | 1.90 | +133.22% | +57.01% | 100% | — | — |

### Bear leg only: 2022-01-01 → 2022-07-04

| Scenario | Trades | Win rate | Profit factor | Max DD | Sharpe | Total return | CAGR | Avg capital deployed | Mean R | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|---|
| Baseline | 10 | 20.0% | 0.39 | -0.90% | -1.57 | -0.67% | -1.39% | 1.3% | -0.47 | 80.1% |
| A_filters | 4 | 50.0% | 1.79 | -0.14% | 0.78 | +0.19% | +0.39% | 0.4% | 0.84 | 25.4% |
| B_risk | 10 | 30.0% | 0.59 | -0.68% | -0.92 | -0.35% | -0.72% | 1.2% | -0.31 | 76.3% |
| C_trend | 15 | 6.7% | 0.00 | -1.10% | -4.41 | -1.10% | -2.29% | 1.2% | -0.67 | 100.0% |
| D_hold_4 | 12 | 8.3% | 0.21 | -9.49% | -1.83 | -7.51% | -15.00% | 18.5% | -0.34 | 99.0% |
| D_hold_5 | 12 | 8.3% | 0.21 | -9.27% | -1.73 | -7.28% | -14.57% | 18.7% | -0.33 | 99.0% |
| D_hold_6 | 12 | 8.3% | 0.21 | -9.27% | -1.73 | -7.28% | -14.57% | 18.7% | -0.33 | 98.5% |
| **Buy & Hold (equal weight)** | — | — | — | -23.12% | -2.22 | -21.51% | -39.61% | 100% | — | — |

### In USD terms (2022–2023, total return ÷ FX move)

| Scenario | EGP | USD |
|---|---|---|
| Baseline | -0.61% | -49.54% |
| A_filters | +1.07% | -48.68% |
| B_risk | +0.32% | -49.07% |
| C_trend | +1.97% | -48.23% |
| D_hold_4 | +42.35% | -27.72% |
| D_hold_5 | +54.72% | -21.44% |
| D_hold_6 | +60.21% | -18.66% |
| Buy & Hold | +133.22% | +18.41% |

## Decision

Best scenario = highest Sharpe on data/ only (in-sample); 2022–2023 is reported as an out-of-sample check on 9 large caps: **C_trend** (data/: Sharpe 4.67, PF 3.16; 2022–23: Sharpe 1.01).

Disclosure: the first run selected by data/ Sharpe alone and picked B_risk (Sharpe 1.70 on ~3% deployed capital), which fell to Sharpe 0.39 / P(mean R ≤ 0) 29% in 2022–2023 → rule output ABANDON. That selection overfits one period, so it was changed to the two-period minimum *after* seeing that result. The CONTINUE/PIVOT/ABANDON rule itself is unchanged. 2026-10-07: reverted to data/-only selection, because a two-period minimum lets the out-of-sample period choose the winner; overfitting now shows up in the 2022–2023 numbers instead.

Rule fixed before reading the results: CONTINUE if the best scenario beats Buy & Hold on Sharpe in both periods; PIVOT (use the system as a filter/timing layer) if its per-trade edge is significant (P(mean R ≤ 0) < 5%) in both periods but it loses to Buy & Hold; otherwise ABANDON.

**Recommendation: ABANDON**

