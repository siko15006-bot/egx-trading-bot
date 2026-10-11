# N1 — Independent test of Nabil et al. (2024) RP/Momentum and MA portfolio strategies (pre-registration)

Written 2026-10-11, **before** any price for this study was downloaded or any return computed. Research only: no
production code, data folder or strategy is touched; isolated branch `research/nabil2024-momentum-ma`.
Changing a rule below after seeing results = N1 failed. Edits before the first run are logged at the bottom.

## Source (Phase 1)

Mohamed Nabil Mohamed El Saiid, Doaa Salman Abdou, Ashraf Saleh, "Analyzing Momentum-Based and Moving Average-Based
Portfolio Strategies: A Case Study of the Egyptian Stock Market", *The Scientific Journal for Economics & Commerce*
(Ain Shams University), pp. 235–274, accepted 2023-11-05, published July 2024. Full text read (MSA repository,
handle 123456789/6097, PDF 846 KB, 43 pages; ResearchGate 382083252).

### Documented rules (from the paper)

| Item | Paper |
|---|---|
| Data | daily closes of the EGX30 index and its constituents, 1H-2000 → 2H-2020 (42 half-years, 136 securities) |
| Universe | the 30 EGX30 constituents of each semi-annual review, fixed for that half-year |
| RP | `RP_i = C_i / I_i` (stock close / EGX30 close) |
| Strategy A (RPA, after Jegadeesh-Titman) | `APP = C_t / C_n`, `RPP = RP_t / RP_n`, n = end of the preceding 6-month interval. Positive APP and RPP → bought "on the following trading day"; negative APP and RPP → sold the following trading day; re-evaluated every day inside the half-year |
| Strategy B (MACO, after Masry 2017) | close vs one SMA of "medium-term" length, on the price (AP-MACO) and on RP (RP-MACO). Both above → buy next day; both below → sell next day |
| Benchmark | equal-weighted EGX30 constituents, buy & hold per half-year (tables label it "EGX30") |
| Returns | daily log returns; statistics on 42 semi-annual returns (paired t-test, ANOVA, Scheffé) |
| Costs / slippage | **none** ("no transaction costs", "no slippage", fills at the signal-day close — limitations) |
| Reported | mean semi-annual return A 12.10%, B 11.24%, EGX30 7.99% (A vs EGX30 p = 0.034; B p = 0.134; ANOVA on returns p = 0.80) |

### Not specified in the paper (gaps)

1. **SMA length of strategy B** — only "medium-term". Not invented: B is tested only as a declared grid (below).
2. What happens when APP and RPP (or the two MACO signals) disagree.
3. Weighting inside the portfolio, and the return on uninvested capital.
4. Whether positions are closed at the end of each half-year.
5. Dates of the EGX30 semi-annual reviews (the paper labels intervals 1H/2H, i.e. calendar halves).
6. Whether dividends are included (prices described as "closing prices").
7. "Following trading day" vs "closing value exactly upon a given signal" — the text says both.

## Data available (verified 2026-10-11)

- Stock prices: Yahoo via yfinance 1.2.0, EGX tickers back to 2000, but 2000–2008 has ~30% filler (zero-volume) rows;
  usable from 2009. Downloaded with the split back-adjust fix of `data_downloader.apply_backadjust_fix` (KNOWN_ISSUES.md).
- **EGX30 index history: not available.** Yahoo `^CASE30` returns only the current day; stooq requires a browser
  challenge (not bypassed); EODHD free plan = 20 requests/day, 1 year.
- **EGX30 point-in-time constituents: not available** in the project or found sources.
- FX: Yahoo `EGP=X` from 2001.

Because the two core inputs are missing, **a faithful replication is INSUFFICIENT_DATA by construction.** What follows is a
**proxy test**, every substitution declared.

## Proxy test (Phase 2) — fixed rules

- **Universe candidates:** the 401 tickers of `egx_universe.json` (today's list → survivorship bias, same on both sides).
- **Proxy EGX30 (assumption P1):** at the last session of each half-year, the 30 tickers with the highest median daily
  traded value (Close × Volume, EGP) over the last 126 sessions, among tickers with ≥ 100 real (Volume > 0) bars in those
  126. Fixed for the next half-year. (EGX30 selection is liquidity/activity + market cap; market cap is unavailable.)
- **Proxy index (P2):** equal-weight index of the 30 proxy constituents (mean daily return, chained).
- **Prices (P3):** fully adjusted closes (splits + cash dividends, yfinance's own rule after the split fix). Same basis for
  strategies and benchmark.
- **Half-years:** calendar halves (Jan–Jun, Jul–Dec). Anchor n = last session of the previous half.
- **Strategy A:** each session t of the half, APP = C_t/C_n, RPP = RP_t/RP_n with RP = C/index. Both > 1 → state IN;
  both < 1 → OUT; mixed → keep the previous state (assumption M1). Every half starts OUT.
- **Strategy B:** AP signal C_t > SMA_N(C)_t, RP signal RP_t > SMA_N(RP)_t (SMA over past closes, may start before the half);
  same IN/OUT/M1 logic. **N ∈ {20, 50, 100, 150, 200}**, each reported; the B result that decides is **walk-forward**:
  for each half, the N with the best net Sharpe over the previous 4 halves (ties → larger N); first 4 halves use N = 100.
- **Execution:** state decided at close t, traded at close t+1 (documented "following trading day"). A filler bar (Volume 0)
  never fills: the trade waits for the next real bar.
- **Portfolio (assumption W1):** 30 equal slots per half (1/30 of the value at the half start each). A slot is in the
  stock when IN, in cash at 0% when OUT. All slots are closed at the last close of the half and the new half starts
  from the portfolio value (a stock kept across halves is not traded twice: no cost if it stays IN through the boundary).
- **Benchmark (paper's):** the same 30 slots always IN for the half (EW buy & hold per half-year).
- **Costs (base):** 0.30% per side = Thndr fees ~0.18% (`fees_config.py`: 0.1% brokerage + EGX/MCDR/FRA/insurance + 0.05%
  stamp; the 2 EGP fixed fee ignored) + 0.12% slippage, rounded. Same cost on benchmark trades (half-start rebalance).
- **Currency:** EGP primary; USD via `EGP=X` reported alongside.

## Samples

- **In-sample (overlaps the paper):** 2010-H1 → 2020-H2 (22 halves; 2009 only feeds the first anchors/SMAs).
- **Out-of-sample (after the paper's data):** 2021-H1 → 2026-H1 (11 halves). 2026-H2 (to date) shown, not judged.

## Metrics (Phase 3)

Total return, CAGR, max drawdown, Sharpe (daily, annualised ×√248, risk-free 0 — EGP rates were 8–27%, so this flatters
everything equally), win rate and profit factor per round trip (slot IN → OUT), number of trades, total costs (EGP per
100 EGP of starting capital), and versus the benchmark. EGX30 index itself: not available (see above). The paper's own test
is also reproduced: paired t-test on the semi-annual returns, strategy vs benchmark.

## Sensitivity (one change at a time from the base, A and B-walk-forward)

Costs 0 / 0.15% / 0.30% / 0.50% per side; execution at the signal close (paper's optimistic reading) vs next close;
mixed rule M1 vs "IN only when both positive" (M2); proxy index over the top 60 instead of the 30; 3-month instead of
6-month intervals.

## Verdict rules (fixed now)

For each strategy (A, and B walk-forward), net of base costs, versus the EW benchmark:
- **PASS:** OOS CAGR and OOS Sharpe both above the benchmark in EGP **and** USD; IS also above in both; paired t-test of
  semi-annual excess returns over IS+OOS one-sided p < 0.05; and ≥ 80% of the sensitivity variants keep OOS CAGR above
  the benchmark.
- **WEAK:** OOS CAGR above the benchmark in EGP, but any other PASS condition fails.
- **REJECT:** OOS CAGR not above the benchmark in EGP.
- **INSUFFICIENT_DATA:** applies to the faithful replication (EGX30 index and constituents missing), whatever the proxy says.

Final report = replication verdict + proxy verdict per strategy. Prior related result: H1 momentum rotation FAILED
(`H1_momentum_rotation.md`); N1 is the same causal family (momentum / trend), so a pass would need the full criteria.

## Edit log

- 2026-10-11: created before any download or return computation.
