# L1 — Low-volatility anomaly on EGX (pre-registration)

Written 2026-10-11, **before** any low-volatility signal or return was computed. Research only, isolated branch
`research/l1-low-volatility`; no production code, data or strategy touched. Changing a rule below after seeing results =
L1 failed. Edits are logged at the bottom.

## Why

Momentum/trend failed three times on EGX (H1 2026-10-06; N1 strategies A and B 2026-10-11 — not independent: same family,
same data). The low-volatility anomaly is a different family (risk, not trend): stocks with low past volatility have
earned similar or higher returns with less risk than high-volatility stocks in many markets (Blitz & van Vliet 2007;
Baker, Bradley & Wurgler 2011). EGX is retail-heavy with speculative high-volatility names, the setting where the anomaly
is usually explained (lottery demand). No EGX-specific study is relied on.

## Hypothesis (one sentence)

Among the 60 most liquid EGX stocks, the 10 with the lowest past volatility deliver a higher risk-adjusted return (Sharpe)
than an equal-weight portfolio of the same 60, after costs, in EGP and in USD.

## Decision rule (no free parameters)

- **Harness:** `research_h1_momentum.run` unchanged (the H1/H3 one): eligibility ≥ 147 real bars, ≥ 15 real of the last
  21, real bar on the day, top 60 by 63-session median traded value; rebalance every 21 sessions; signal and trade at
  the same close (H1 convention; a 1-session lag is a sensitivity); weights drift between rebalances.
- **Signal:** minus the standard deviation of daily returns over the last 252 sessions, using only returns that end on a
  real bar (Volume > 0); at least 200 such returns, else not eligible. Hold the 10 highest scores (lowest volatility),
  equal weight. Benchmark: equal weight of the same 60, same dates and costs.
- **Prices:** `data_l1/` = byte copy of N1's download (Yahoo 2009+, fully adjusted, split back-adjust fix; 401 tickers;
  combined sha256 in `data_l1/_copied_from.json`). These prices were used for N1 (momentum); no volatility sort was run.
- **Costs:** 0.30% per side on turnover (N1 base: Thndr fees ~0.18% + slippage).
- **Currency:** EGP and USD (`EGP=X`, in `data_l1/_EGPUSD.csv`).

## Samples (fixed)

- **In-sample:** first rebalance (2010, after 252 sessions of history) → 2020-12-31.
- **Out-of-sample:** 2021-01-01 → 2026-06-30. Later days shown, not judged.

## Metrics

Total return, CAGR, max drawdown, Sharpe (daily ×√252, risk-free 0), win rate and profit factor over the 21-session
holding periods, number of trades (names entering or leaving the 10), transaction costs (annual cost drag = gross minus
net CAGR), versus the EW benchmark. EGX30 itself: not available (N1).

## Success (fixed now)

- **PASS:** OOS Sharpe ≥ EW Sharpe + 0.20 in EGP **and** USD; OOS max drawdown no deeper than EW's; IS Sharpe above EW in
  EGP and USD; and in ≥ 80% of the sensitivity variants OOS Sharpe (EGP) above EW.
- **WEAK:** OOS Sharpe (EGP) above EW, but any PASS condition fails.
- **REJECT:** OOS Sharpe (EGP) not above EW.

## Sensitivity (one change at a time, OOS judged)

Volatility window 63 / 126; hold 5 / 15; pool top 30 / 100; costs 0.15% / 0.50% per side; signal lagged by 1 session.

## Edit log

- 2026-10-11: created before any low-volatility computation.
