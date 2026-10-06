# Decision Report — 4 Mirrors v3 / Scenario D (generated 2026-10-04 19:25)

Every number below uses realistic execution, real Yahoo data (`data_2019_2026_wf/`, one continuous download), and the same engine (`egx_4_mirrors_v3.py`, unmodified). **USD** = prices converted day by day with Yahoo `EGP=X`. 

## Tests 1 + 2 — All scenarios, three periods, EGP and USD

| Period | Ccy | Scenario | Trades | PF | Sharpe | Max DD | Total return | Deployed | P(mean R ≤ 0) |
|---|---|---|---|---|---|---|---|---|---|
| P1 2020-21 | EGP | Baseline | 50 | 1.00 | 0.00 | -1.1% | -0.0% | 3% | 53.6% |
| P1 2020-21 | EGP | A_filters | 7 | 0.33 | -0.86 | -0.6% | -0.6% | 0% | 93.5% |
| P1 2020-21 | EGP | B_risk | 46 | 1.59 | 0.79 | -0.5% | +1.1% | 2% | 13.5% |
| P1 2020-21 | EGP | C_trend | 51 | 0.96 | -0.07 | -1.1% | -0.1% | 2% | 56.2% |
| P1 2020-21 | EGP | D_hold_6 | 45 | 1.35 | 0.41 | -10.4% | +6.6% | 33% | 32.6% |
| P1 2020-21 | EGP | **Buy & Hold** | — | — | 0.33 | -42.3% | +10.5% | 100% | — |
| P1 2020-21 | USD | Baseline | 52 | 1.06 | 0.12 | -0.8% | +0.2% | 3% | 47.1% |
| P1 2020-21 | USD | A_filters | 9 | 0.26 | -1.13 | -0.8% | -0.8% | 0% | 98.9% |
| P1 2020-21 | USD | B_risk | 49 | 1.57 | 0.81 | -0.5% | +1.2% | 2% | 12.6% |
| P1 2020-21 | USD | C_trend | 56 | 1.10 | 0.17 | -1.1% | +0.2% | 3% | 42.8% |
| P1 2020-21 | USD | D_hold_6 | 50 | 1.47 | 0.48 | -11.7% | +8.3% | 35% | 25.4% |
| P1 2020-21 | USD | **Buy & Hold** | — | — | 0.38 | -42.2% | +12.9% | 100% | — |
| P2 2022-23 | EGP | Baseline | 76 | 1.12 | 0.30 | -1.5% | +0.6% | 3% | 29.8% |
| P2 2022-23 | EGP | A_filters | 21 | 2.16 | 0.98 | -0.7% | +1.2% | 1% | 4.2% |
| P2 2022-23 | EGP | B_risk | 71 | 1.42 | 0.76 | -1.3% | +1.4% | 3% | 13.6% |
| P2 2022-23 | EGP | C_trend | 68 | 2.23 | 1.33 | -1.0% | +3.0% | 3% | 1.2% |
| P2 2022-23 | EGP | D_hold_6 | 40 | 4.81 | 1.72 | -17.7% | +83.7% | 52% | 0.1% |
| P2 2022-23 | EGP | **Buy & Hold** | — | — | 2.00 | -22.5% | +149.4% | 100% | — |
| P2 2022-23 | USD | Baseline | 59 | 0.66 | -0.92 | -2.6% | -1.5% | 3% | 88.0% |
| P2 2022-23 | USD | A_filters | 14 | 0.93 | -0.07 | -0.6% | -0.0% | 1% | 49.6% |
| P2 2022-23 | USD | B_risk | 54 | 0.72 | -0.64 | -1.7% | -1.0% | 2% | 83.3% |
| P2 2022-23 | USD | C_trend | 65 | 1.12 | 0.18 | -1.7% | +0.3% | 3% | 39.7% |
| P2 2022-23 | USD | D_hold_6 | 49 | 1.36 | 0.44 | -21.7% | +12.7% | 38% | 19.8% |
| P2 2022-23 | USD | **Buy & Hold** | — | — | 0.56 | -36.5% | +26.6% | 100% | — |
| P3 2024-26 | EGP | Baseline | 105 | 1.48 | 0.96 | -0.6% | +2.3% | 3% | 7.7% |
| P3 2024-26 | EGP | A_filters | 28 | 0.79 | -0.30 | -0.5% | -0.3% | 1% | 71.6% |
| P3 2024-26 | EGP | B_risk | 89 | 1.66 | 1.14 | -0.6% | +2.0% | 3% | 2.8% |
| P3 2024-26 | EGP | C_trend | 108 | 1.58 | 0.88 | -1.3% | +2.0% | 4% | 6.3% |
| P3 2024-26 | EGP | D_hold_6 | 69 | 2.61 | 1.04 | -24.4% | +68.3% | 64% | 1.1% |
| P3 2024-26 | EGP | **Buy & Hold** | — | — | 1.41 | -30.5% | +140.5% | 100% | — |
| P3 2024-26 | USD | Baseline | 105 | 1.22 | 0.42 | -1.3% | +1.2% | 4% | 29.1% |
| P3 2024-26 | USD | A_filters | 34 | 1.10 | 0.14 | -0.7% | +0.2% | 1% | 47.7% |
| P3 2024-26 | USD | B_risk | 98 | 1.56 | 0.90 | -1.1% | +2.3% | 3% | 6.3% |
| P3 2024-26 | USD | C_trend | 109 | 0.97 | -0.05 | -3.0% | -0.2% | 3% | 54.9% |
| P3 2024-26 | USD | D_hold_6 | 74 | 1.26 | 0.36 | -45.7% | +15.9% | 60% | 21.8% |
| P3 2024-26 | USD | **Buy & Hold** | — | — | 0.60 | -52.8% | +43.7% | 100% | — |

### D_hold_6 vs Buy & Hold — summary

| Period | Ccy | D Sharpe | B&H Sharpe | D DD | B&H DD | D return | B&H return |
|---|---|---|---|---|---|---|---|
| P1 2020-21 | EGP | 0.41 | 0.33 | -10.4% | -42.3% | +6.6% | +10.5% |
| P1 2020-21 | USD | 0.48 | 0.38 | -11.7% | -42.2% | +8.3% | +12.9% |
| P2 2022-23 | EGP | 1.72 | 2.00 | -17.7% | -22.5% | +83.7% | +149.4% |
| P2 2022-23 | USD | 0.44 | 0.56 | -21.7% | -36.5% | +12.7% | +26.6% |
| P3 2024-26 | EGP | 1.04 | 1.41 | -24.4% | -30.5% | +68.3% | +140.5% |
| P3 2024-26 | USD | 0.36 | 0.60 | -45.7% | -52.8% | +15.9% | +43.7% |

## COVID — three phases, D_hold_6 vs equal-weight Buy & Hold (P1 run, started 2020-01-01)

| Phase | Dates | Ccy | D return | D max DD | B&H return | B&H max DD | D avg invested | Opened / closed | Exit reasons |
|---|---|---|---|---|---|---|---|---|---|
| Pre-COVID | 2020-01-01 → 2020-02-29 | EGP | -2.5% | -2.5% | -10.3% | -14.9% | 6% | 2 / 2 | {'EMA50_EXIT': 1, 'SL': 1} |
| Crash | 2020-03-01 → 2020-05-31 | EGP | +0.8% | -2.4% | -14.5% | -33.3% | 7% | 5 / 4 | {'EMA50_EXIT': 4} |
| Recovery | 2020-06-01 → 2020-12-31 | EGP | -1.1% | -10.1% | +20.3% | -10.0% | 40% | 18 / 16 | {'EMA50_EXIT': 16} |
| Pre-COVID | 2020-01-01 → 2020-02-29 | USD | +0.9% | -3.7% | -8.0% | -14.2% | 22% | 3 / 2 | {'EMA50_EXIT': 2} |
| Crash | 2020-03-01 → 2020-05-31 | USD | -0.5% | -2.4% | -15.4% | -33.7% | 8% | 6 / 6 | {'EMA50_EXIT': 6} |
| Recovery | 2020-06-01 → 2020-12-31 | USD | -2.3% | -11.3% | +20.9% | -9.2% | 43% | 21 / 19 | {'EMA50_EXIT': 19} |

Trades closed in the crash phase (EGP): `[{'ticker': 'TMGH.CA', 'entry_date': '2020-04-25 22:00:00+00:00', 'exit_date': '2020-04-26 22:00:00+00:00', 'pnl_pct_pos': '1.4173809337148673', 'reason': 'EMA50_EXIT'}, {'ticker': 'TMGH.CA', 'entry_date': '2020-04-26 22:00:00+00:00', 'exit_date': '2020-04-27 22:00:00+00:00', 'pnl_pct_pos': '1.6957201496115877', 'reason': 'EMA50_EXIT'}, {'ticker': 'MNHD.CA', 'entry_date': '2020-04-26 22:00:00+00:00', 'exit_date': '2020-04-29 22:00:00+00:00', 'pnl_pct_pos': '0.04994775462282888', 'reason': 'EMA50_EXIT'}, {'ticker': 'SWDY.CA', 'entry_date': '2020-04-25 22:00:00+00:00', 'exit_date': '2020-05-03 22:00:00+00:00', 'pnl_pct_pos': '-6.753495926575226', 'reason': 'EMA50_EXIT'}]`

## Test 3 — Walk-forward, D_hold_6 (2-year train → next-year test)

D has no fitted parameter, so 'train' here just runs the same fixed rules on the earlier window; the comparison measures stability, not overfitting of a tuned value.

| Window | Ccy | Train Sharpe | Test Sharpe | Degradation | Test return | B&H test Sharpe | B&H test return | Test trades |
|---|---|---|---|---|---|---|---|---|
| W1 → 2022 | EGP | 0.39 | 1.78 | +1.39 | +29.9% | 1.40 | +34.4% | 23 |
| W2 → 2023 | EGP | 1.42 | 1.19 | -0.23 | +24.0% | 2.40 | +76.3% | 26 |
| W3 → 2024 | EGP | 1.70 | 0.72 | -0.98 | +15.6% | 1.22 | +40.0% | 25 |
| W4 → 2025 | EGP | 1.11 | 1.33 | +0.23 | +19.4% | 1.32 | +24.8% | 28 |
| **mean EGP** | | | | **+0.10** | | | | |
| W1 → 2022 | USD | 0.46 | -0.33 | -0.79 | -7.1% | -0.34 | -14.8% | 30 |
| W2 → 2023 | USD | 0.10 | 1.83 | +1.74 | +35.4% | 1.44 | +41.2% | 21 |
| W3 → 2024 | USD | 0.39 | -0.14 | -0.52 | -13.4% | -0.05 | -14.6% | 28 |
| W4 → 2025 | USD | 0.53 | 0.88 | +0.35 | +14.4% | 1.60 | +32.9% | 28 |
| **mean USD** | | | | **+0.19** | | | | |

## Test 4 — System as a market filter (Smart Timing), 2020-01 → 2026-10

EGX30 is not on Yahoo (`^CASE30`, `^EGX30`, `EGX30.CA`, `^CASE`, `EGPT` all returned nothing), so the index is a **proxy: equal-weight basket of the same 9 stocks** (daily rebalanced). Weekly: count of stocks with a 4/4 BUY → ≥5: 100%, 2–4: 50%, <2: cash (0% return — EGP T-bill yield not modelled). Weight is set at the week's last close and applied from the next day; 0.3% per traded side.

Weekly count distribution (count: weeks): `{0: 242, 1: 84, 2: 18, 3: 4}`

| Ccy | Timing return | Timing Sharpe | Timing max DD | B&H return | B&H Sharpe | B&H max DD | Avg weight | Weeks 100% / 50% |
|---|---|---|---|---|---|---|---|---|
| EGP | +14.2% | 0.70 | -6.8% | +681.0% | 1.36 | -44.4% | 3% | 0% / 6% |
| USD | +9.3% | 0.41 | -12.2% | +140.9% | 0.61 | -55.1% | 3% | 0% / 6% |

## Limitations (read before the decision)

1. **The index in test 4 is NOT EGX30.** It is an *equal-weight* basket of 9 stocks, rebalanced daily. EGX30 is *cap-weighted* (free-float, capped) over 30 stocks and dominated by a few names (e.g. COMI alone is a large share of it). Equal weight gives small/mid names far more influence and rebalances in a way no real index fund does, so the proxy's return, volatility and drawdown can differ materially from EGX30. It is also built from the same 9 stocks the filter reads, which flatters the filter (signal and market are the same basket). **Test 4 is an idea check, not an EGX30 result.**
2. **USD conversion** uses the *historical daily* USD/EGP close from **Yahoo Finance `EGP=X`** (1890 rows, 2019-07-01 → 2026-10-02), forward-filled to each EGX trading day — not a constant. Spot checks: {'2020-01-01': 16.01, '2022-01-01': 15.68, '2024-01-01': 30.89, '2026-10-01': 51.91}. Largest daily moves (devaluations): {'2024-03-07': '+60.4%', '2022-10-28': '+17.6%', '2022-03-22': '+15.8%'}. Yahoo's EGP=X is the official/bank rate; during 2022–2023 the parallel-market rate was materially weaker, so USD results for those years are, if anything, optimistic. Stooq was not used (blocked by a bot-check, which was not bypassed).
3. **Small samples.** D_hold_6 trades per period are a few dozen; walk-forward test years have even fewer. Any Sharpe difference below ~0.5 between D and B&H is within noise.
4. **Cash earns 0%.** EGP deposits/T-bills paid ~8–27% over 2020–2026. Every strategy that holds cash (all of them, D ~50–65%, timing filter) is understated in EGP; in USD the gap is smaller but still non-zero.
5. **Survivorship / universe:** the 9 stocks were chosen in 2026 (today's large caps). EFIH has no data before 2021-10 and is absent from P1 and W1. MNHD = Yahoo `MASR.CA` (renamed). Yahoo prices are auto-adjusted; frozen/no-trade bars removed.
6. **Costs:** 0.3% per side + 10% tax on gains, no slippage beyond open-gap fills, liquidity capped at 1% of 20-day average volume.

## Decision rule (fixed before the run)

- CONTINUE: D_hold_6 beats Buy & Hold on USD Sharpe in ≥2 of 3 periods.
- PIVOT_TO_FILTER: it doesn't, but its USD max DD is shallower than B&H in ≥2 of 3 periods AND walk-forward USD test Sharpe > 0 in ≥3 of 4 windows.
- ABANDON: otherwise. Confidence: HIGH only if unanimous and ≥100 D trades; MED if unanimous or ≥100 trades; LOW otherwise.

**Rule output: ABANDON — confidence MED**


## Summary table (USD = reference)

| Test | Result | Statistically certain? |
|---|---|---|
| 1. 2020–21 (8 stocks, EFIH has no data) | D +8.3% vs B&H +12.9%; Sharpe 0.48 vs 0.38; DD −11.7% vs −42.2% | No: the Sharpe difference (0.10) is within noise, 50 trades |
| COVID — Crash phase (Mar–May 2020) | D −0.5% (USD) / +0.8% (EGP), DD −2.4%, vs B&H −15.4% / −14.5%. D was mostly in cash | Yes for direction (B&H loss is large); one event |
| COVID — Recovery phase (Jun–Dec 2020) | D −2.3% vs B&H +20.9% (USD): **missed the whole rebound** | One event |
| 2. USD, 3 periods | D beats B&H on Sharpe in **1 of 3** (2020–21 only); shallower DD in **3 of 3** | DD yes; Sharpe no |
| 2. USD, 2024–26 | D DD −45.7% (B&H −52.8%): the 2024-03-07 devaluation (+60% in one day) hit open positions. The −15% stop does not protect against a currency gap | Yes, an event that actually happened |
| 3. Walk-forward USD | Test Sharpe > 0 in **2 of 4** (2023, 2025). Mean degradation +0.19 (no degradation on average, but very wide spread: −0.79 to +1.74) | No: 21–30 trades per test year |
| 3. Walk-forward USD, losing years | 2022: D −7.1% vs B&H −14.8%; 2024: D −13.4% vs B&H −14.6%. It lost less, but it still lost | — |
| 4. Smart Timing (filter) | The count was never ≥5 (0 weeks); 2–4 in only 6% of weeks; average invested 3%. Return +9.3% vs B&H +141% (USD) | **The idea as defined failed**: 4/4 signals are too rare to be a market filter |

## Final decision

**Rule output (fixed before the run): ABANDON — confidence MED.**
- CONTINUE fails: D beats B&H in only 1 of 3 periods in USD.
- PIVOT_TO_FILTER fails: the drawdown condition passed (3 of 3), but walk-forward needed test Sharpe > 0 in ≥3 of 4 windows and got 2 of 4.
- Confidence is MED, not HIGH: the result isn't unanimous, though it rests on 173 D trades across 3 periods.

**Is the system worth turning into a filter? No — not in either tested form:**
- The weekly 4/4 filter (test 4) is effectively always out of the market.
- D cuts drawdown consistently, but gives up most of the upside: it missed the COVID recovery and returned about a third to a half of B&H in every period.
- In USD terms, a drawdown reducer that underperforms on Sharpe isn't worth its costs and taxes.

**Uncertainty, stated plainly:**
- The two walk-forward failures (2022 and 2024) were years when B&H itself was negative in USD, and D lost less. A rule that judges a filter against the market rather than in absolute terms might have given PIVOT. I did not change the rule after seeing the results, since I already changed the selection criterion once in the previous report.
- Every Sharpe difference here (≤0.25 in 2 of 3 periods) is within noise for a few dozen trades.

**What could change the decision:** see "What's Missing" below. The most important items are real EGX30 data and modelling the return on cash (T-bills were 8–27%). Including cash yield would raise D, since it is ~40–65% in cash.

## What's Missing
1. Real EGX30 data (cap-weighted). It isn't on Yahoo, and stooq/investing are blocked by bot-checks.
2. Return on cash (EGP T-bill/deposit rates by period).
3. The parallel-market FX rate for 2022–2023.
4. A wider universe (EGX30/EGX70 constituents at the time) to remove survivorship bias in the 9 stocks.
5. More trades. A real paper-trading test from 2026-10 onward would be true out-of-sample data.
6. Intraday data, so that the true daily VWAP has a meaning.
