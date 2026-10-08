# Known issues

## Status index (2026-10-07) — sections below are unchanged; this table only classifies them

| Status | Item | Section |
|---|---|---|
| 🔴 Open | Entry price mismatch: live scanner shows Close[i] (unattainable), backtest assumes Close[i+1] — documented, not fixed (strategy on hold) | Execution conventions |
| 🔴 Open | Test fixtures: daily `pd.date_range(..., tz=Africa/Cairo)` at midnight crashes on 2026-04-24 (nonexistent time) — fixtures use noon or start after April | Data health fails on Cairo DST… |
| 🔴 Open | Data health crashes on the Cairo DST spring-forward midnight (only matters for a Friday session / intraday data) | Data health fails on Cairo DST… |
| 🔴 Open | Yahoo misses whole EGX sessions for stocks (e.g. 2026-06-22, 08-10, 10-06); ~2–4.5%/yr lower bound | Missing EGX sessions in Yahoo |
| 🔴 Open | Yahoo misdates/omits split adjustments in `data/` (HDBK, EFID, INFI, …) — guarded by `DATA_BREAK`, not corrected | Execution conventions |
| 🔴 Open | Universe excludes high-priced and single-bad-row stocks (SCTS, CPCI, MIPH, 13 others); widening deferred | Universe gaps |
| ❓ Unknown | الدمغة مش محصلة في يوليو 2026، السبب غير معروف. fees_config سليم (Ahmed 2026-10-07). July only — stamp is charged from August on, so `fees_config` is the real tariff | Execution conventions → Fees |
| ✅ Closed | `fees_config` (with stamp) verified on 13/15 Aug–Sep fills + a Thndr invoice line by line; subscription (2026-09-24) = brokerage charged then refunded same day ("رد العمولة", 6/6 = 2 + 0.1%) | Execution conventions → Fees |
| ❓ Unknown | FUND_DOCUMENT_FEE: exchange-traded fund certificate (وثائق صندوق المصريين, 2026-09-07) charged +1.01 EGP above `fees_config`; cause unknown — ask Thndr support. Not corrected | Execution conventions → Fees |
| ❓ Unknown | Slippage size on EGX (10 bps default is an assumption); trading halts / limit-locked days; official holiday calendar | Execution conventions; Missing EGX sessions |
| ❓ Unknown | Effect of misdated splits on the H3 research result | Execution conventions |
| ✅ Closed (rule in place) | Volume 0 rows = missing data: no indicators (computed on real rows only), signal → SKIPPED_ZERO_VOLUME, no fills, data_health warns (2026-10-08) | Yahoo filler rows |
| ✅ Closed (rule in place) | `data/` vs fully adjusted series never mixed; dividends only on `data/`, enforced by `resolve_dividend_mode` | Price series; Dividends in backtests |
| ✅ Closed | No Open-based fills; entry at next close; in-range fills; optimizer selects on main window only (OOS = 9 large caps) | Execution conventions |
| ✅ Closed (verdict) | 4 Mirrors strategy ABANDON vs Buy & Hold | Strategy vs Buy & Hold |

## Data health fails on Cairo DST forward-transition midnight (2026-04-24 only)

Daily (midnight) rows: only the April spring-forward breaks. Hourly data: exposed to both transitions
(April nonexistent hour, October ambiguous 23:00 hour).

- `assess_daily_data` calls `raw.index.tz_localize(CAIRO)` on naive dates.
- 2026-04-24 00:00 does not exist in Africa/Cairo (spring-forward) -> `ValueError`, whole assessment crashes.
- Checked every 2026 midnight: only 2026-04-24 (a Friday) fails. October fall-back (2026-10-29/30) repeats
  23:00 Thursday, so midnight-stamped daily rows are fine; intraday rows in that hour would be ambiguous.
- Production impact today: none (EGX is closed on Fridays, daily rows are midnight). Would bite on an
  exceptional Friday session or intraday data.
- Fix when needed: `tz_localize(CAIRO, nonexistent="shift_forward", ambiguous="NaT")` or localize dates
  as plain `date` objects instead of midnight timestamps.
- Found 2026-10-05 while writing `test_download_freshness.py` (fixture now uses the Sun-Thu EGX week).
- **Test infrastructure (separate issue, 2026-10-08):** any synthetic fixture built with a daily
  `pd.date_range(start, periods=n, tz="Africa/Cairo")` at midnight that spans 2026-04-24 raises
  `ValueError: 2026-04-24 00:00:00 is a nonexistent time` — before the code under test even runs, so the failure
  looks unrelated to the change being tested. Hit twice on 2026-10-08 (`test_execution.py`, Volume 0 and Open tests),
  worked around with a noon start (`"2026-01-04 12:00"`). `test_execution._flat()` and `_bars()` start in January /
  September with ≤ 70 bars, so they do not reach April today; a longer `_flat(n)` would. Fix when convenient: one
  shared fixture helper that always builds noon timestamps (or naive dates + `tz_localize(..., nonexistent=
  "shift_forward")`).

## Yahoo filler rows (zero-volume flat bars) — provider gap, not market behaviour

Rule adopted 2026-10-06. Raw CSVs stay untouched; this applies at analysis/backtest time only.

- **filler** = `Volume == 0 and Open == High == Low == Close`. **real** = Volume > 0.
  **ambiguous** = Volume 0 but OHLC not flat (handle case by case).
- Measured on `data/` (90 files, 22,500 rows, 2025-10-05 → 2026-10-05): 1,000 filler, 0 ambiguous.
- Fillers cover holidays (06-17/18) **and real sessions**: 06-22 (90/90), 08-09/10 (89, 88), 08-16 (89).
  08-10 was a confirmed session (EGX30 traded, EGP 14.9bn). So filler = Yahoo calendar gap, not "no trading".
- The 4 "Open != prev Close" days (06-21, 06-23, 08-11, 08-17 — 353 of 379 mismatches) are the first
  real day after a filler run: prev Close is a filler value, not real.
- Handling (corrected 2026-10-08 to match the code — the earlier list claimed exclusion from indicators that did not
  exist; 137 of 309 backtest signals had a Volume 0 row inside their 20-bar window). Code rule: **Volume 0 = missing
  data** (`is_filler`, Volume <= 0; on `data/` every such row is also flat):
  1. **Indicators** (`calculate_indicators`): computed on the Volume > 0 rows only and joined back — the row keeps
     its place and raw OHLCV, its indicators are NaN, and every other row equals the series without it (windows
     slide one bar further back). NaN-masking the prices instead was measured and rejected: `_clean_ohlcv` drops NaN
     rows, NaN + `rolling(min_periods=1)` differs from that reference on 81/220 COMI rows, EMA with NaN on 125.
  2. **Signals** (`evaluate_4_mirrors`): a Volume 0 latest candle → `SKIPPED_ZERO_VOLUME` (rejected, logged by the
     daily scan and `signal_engine`).
  3. **Execution**: never an entry, exit or trailing-stop update (`docs/execution_policy.md`); counts as an elapsed
     session for data breaks. Open is not used anywhere in execution.
  4. **data_health**: `suspect_volume` (rows per ticker), `suspect_volume_latest`, `suspect_volume_distribution`
     (tickers per share: 0-5 / 5-15 / 15-30 / >30%) — a warning in the report and log, never a block; no threshold yet.
  5. Every performance report should state the Volume 0 count (verifiable rows only).
- Deferred: re-checking prices via Investing.com (doesn't change handling); alternative provider
  (decide once filler share over 2019-2026 is measured).

## Price series: `data/` and `data_2019_2026_wf/` are different series — never mix them

Found 2026-10-06 on COMI, checked against Yahoo directly.

| Folder | Download | Meaning | Used by |
|---|---|---|---|
| `data/` | `data_downloader.py`: `auto_adjust=False, actions=False` | split-adjusted, **dividend-unadjusted** | production: daily_runner, signal_engine, dashboard |
| `data_2019_2026_wf/` | script not in repo; matches Yahoo `auto_adjust=True` | fully adjusted (splits + dividends) | analysis only: decision_analysis / decision_report |
| `data_dividend_adjusted/` | `fetch_adjusted.py`: `auto_adjust=True, actions=True`, 2y, yfinance 1.2.0 | fully adjusted + `Dividends`/`Stock Splits` columns; companion to `data/`, **not a replacement** | returns/PnL (from 2026-10-06) |

- COMI ex-dividend 2026-04-07 (EGP 6.00): before it `data/` = 1.049 × `wf` (127.76 / 121.76), after it equal.
- `auto_adjust=False` is not "as traded": Yahoo still back-adjusts splits (COMI: 2021-08, 2022-09, 2025-12).
- Rules: execution levels (Entry/SL/TP) from `data/`; returns/PnL from fully adjusted prices (or `data/` + dividends);
  never combine both folders in one calculation; any new download must state `auto_adjust`/`actions` here.
- Verified 2026-10-06 on all 90 stocks: `data/` / adjusted Close ratio steps **only** on ex-dividend dates from
  `docs/corporate_actions.csv` (103 dividends, 29 splits, 61 tickers), ratio = 1 after the last one, volumes equal.
  Splits are already inside `data/` (no step at split dates). COMI adjusted = `wf` to 0.0001 on 472 shared days.
- Run log: `docs/adjusted_download_log.json`. Re-run `python fetch_adjusted.py` after any new dividend.

## Missing EGX sessions in Yahoo — `docs/egx_missing_days.csv`

Upper bound of Yahoo gaps, **preliminary sample** (9 stocks in `wf` + 90 in `data/`). A Sun–Thu day counts as
missing when < 50% of a folder's stocks have a real (non-filler) row. Classified with python-holidays 0.106 (Egypt):
`holiday` = exact match; `uncertain_near_holiday` = within 3 days (EGX often extends/shifts holidays);
`unexplained` = no holiday nearby (likely provider gap). Not verified date by date against EGX announcements.
The ±3-day window is a choice, not a fact: the split between `uncertain` and `unexplained` moves with it.
If precision is ever needed, verify the worst upper-bound years first (2021, 2023), not all ~95 days.

| Year | holiday | uncertain | unexplained | unexplained / ~245 sessions |
|---|---|---|---|---|
| 2020 | 11 | 7 | 9 | 3.7% |
| 2021 | 13 | 7 | 11 | 4.5% |
| 2022 | 14 | 3 | 5 | 2.0% |
| 2023 | 13 | 9 | 8 | 3.3% |
| 2024 | 15 | 6 | 4 | 1.6% |
| 2025 | 12 | 6 | 7 | 2.9% |
| 2026 (to 10-01) | 9 | 7 | 6 | ~3% |

Known real sessions among `unexplained`: 2026-06-22, 2026-08-10. Whole week 2025-08-03..07 missing in `wf`.

## Dividends in backtests (from 2026-10-06)

- `backtest()` and `backtest_optimizer` add net cash dividends (`dividend_tax_pct` 10%, withheld at source) for
  ex-dates in (entry bar, exit bar], and to Buy & Hold (no reinvestment). Source: `docs/corporate_actions.csv`
  (Yahoo `Ticker.actions`, full history, gross per share, split-adjusted like `data/`).
- **Only for dividend-unadjusted prices (`data/`).** `data_2019_2026_wf/`, `data_2022_2023/` (verified = `wf`)
  and `data_dividend_adjusted/` already contain dividends — calling `with_dividends` on them counts them twice.
  Enforced since `fix/data-folder-safety`: `KNOWN_ADJUSTED_FOLDERS` / `KNOWN_UNADJUSTED_FOLDERS` in
  `egx_4_mirrors_v3.py` + `resolve_dividend_mode()`. Known folder with the wrong mode → error; unknown folder
  (other paths, uploads, demo) → `--dividend-mode add|none` (CLI) or the dashboard radio is required.
  Every backtest prints `Data folder: ... Dividend mode: ...`. `data_2020_2021` verified = `wf` (COMI/EAST).
- SL/TP are computed from `data/` prices (not dividend-adjusted). This matches most brokers, but a trade that exits
  on an ex-date exits at the lower unadjusted price and then receives the dividend in PnL. In the 2026-10-06 sample,
  5 of 346 trades exited by SL/TRAIL_SL on the ex-date itself (ARCC, BINV, EFID, ETRS, SAUD). The final PnL is right;
  a broker that auto-adjusts stop levels on ex-dates would give different results.

## Strategy vs Buy & Hold — read with decision_report.md

The dividend change did not move this. 4 Mirrors (Baseline) loses to B&H in every window tested:
`data/` 2026 sample: beats B&H in 12/90 stocks. 2022-23: Baseline ret -0.05% at 3.3% exposure vs B&H +133% (EGP).
Raw return vs B&H is not like-for-like (3% vs 100% invested; EGP returns inflated by devaluation — 2022-23 B&H is
+26.6% in USD). The fair comparison, D_hold_6 in EGP and USD over 3 periods, is in `decision_report.md`:
rule output **ABANDON (confidence MED)** — D beats B&H on USD Sharpe in 1 of 3 periods. One window ≠ another regime.

## Execution conventions (red-team review 2026-10-07) — one rule set for every simulated path

Applies to `backtest`, `backtest_optimizer` (all modes, `simulate_d`), `auto_sim` and the H3 forward test, via
`egx_4_mirrors_v3.simulate_trade` / `stop_fill` / `target_fill` / `data_breaks`.

- **Yahoo's EGX Open is not an opening price.** On `data/` real bars it equals the previous Close 98.2% of the time
  and lies outside [Low, High] 18.2% of the time. No fill uses the Open (2026-10-08): a gap fills at that bar's
  Close — repro of the old bug: ABUK 2026-03-08, Open 77.93 below
  Low 83.0, filled at a price the stock never traded.
  **Gap_Pct removed 2026-10-08 (dead code):** the `max_gap_pct` signal filter measured the signal bar's Open vs the
  previous Close; with Yahoo's Open ≈ previous Close on 98% of bars it blocked ~3 BUY signals a year (72 of 22,500
  bars fired). No look-ahead was involved (signal on a closed bar, entry at Close[i+1]). Worth revisiting only with
  a data source whose Open is a real opening price; a Close-to-Close version is a different filter (would block 161).
  Backtest after removal: 289 trades (was 287), +67,324 EGP (was +69,041): 3 signals returned (ATLC 08-10, FERC
  08-10 and 09-01; FERC 08-11 shifted out), all losers; still 12/90 above B&H → ABANDON stands.
  No signal, indicator or fill reads Open any more; it is only drawn on the dashboard candlestick and validated by
  data_health. The unused legacy `egx_4_mirrors_v2.py` (nothing imports it) still has the old filter.
- **Entry = close of the session after the signal.** Signals are computed after the close (daily runner 14:45, data
  cutoff 14:30), so the signal-day close is not executable. Exits are checked from the bar after the entry bar.
- **Entry price mismatch (live vs backtest), found 2026-10-08:** the live scanner (`build_trade_plan`:
  `entry = float(last["Close"])`, shown as "Entry" in the daily report, Telegram, dashboard tabs 2/9) displays
  **Close[i]** — the close of the signal candle — and sizes SL, TP and shares from it. The backtest, the optimizer and
  auto_sim fill at **Close[i+1]**. Close[i] is unattainable: the signal needs that close to exist, and a market-on-close
  order would have to be placed before the signal is known; in practice the entry is the next session. So the
  backtest is the realistic one and the live display is optimistic by one session (and SL/TP/shares are computed from
  a price you will not get). Not fixed — the strategy is on hold. Fix when it returns: show Close[i] as "signal price"
  and label the entry as "next session (expected ≈ Close[i+1])", or accept the display as approximate with a UI note.
  Independent of Gap_Pct: removing that filter does not change this.
- **Fills, filler rows, data breaks (superseded 2026-10-07 by `docs/execution_policy.md`):** stop/target fill at
  the level, or on a gap at that bar's Close (never the Open); zero-volume rows never fill; a move beyond ±25% per
  elapsed session either way is a data break and a trade across it is **cancelled** (excluded and counted), not
  closed retroactively. The scanner reports `DATA_BREAK` instead of a signal for 60 bars.
  Found on `data/` (2025-10 → 2026-10), symmetric ±25% threshold, 7 break bars in 7 stocks: AMES 04-19 (−48.7%),
  CANA 04-06 (−36.4%), EFID 09-20 (−32.7%, Yahoo dates the split 09-29), EXPA 09-28 (−25.8%), HDBK 06-29 (−49.6%,
  Yahoo dates the 2:1 split 07-08), INFI 02-09 (−29.2%), ORHD 09-28 (−69.7%). (AFMC, JUFO, RMDA, SKPC were flagged
  by the old asymmetric threshold only — moves inside the ±20% daily limit band, not breaks.)
  Backtest on `data/` (2026-10-07, 90 stocks × 100k, dividends added): 309 trades, net +68,411 EGP, 2 trades
  cancelled (EXPA, INFI → `outputs/data_breaks_log.csv`); before this policy 315 trades, +66,910.
  2026-10-08, gaps at Close (never Open): 309 trades, **+68,746 EGP**, 2 cancelled, 7 gap exits (1 changed: MPCI
  2026-08-10 target gap, Open 393.72 → Close 402.00, +335). Still beats B&H in 12/90 stocks → ABANDON stands.
  2026-10-08, indicators from Volume > 0 rows only: **287 trades, +69,041 EGP**, 1 cancelled; only 89 trades
  identical (83 removed — 20 by the volume mirror, 21 ADX, 14 trend/momentum, 28 sequence shift; 61 added; 137 with
  a different size or exit through ATR). Still 12/90 above B&H → ABANDON stands.
  Correction: the 2026-10-06 note that EFID's split is "already inside data/" was wrong — the comparison used two
  Yahoo series with the same misdating.
- **Slippage:** `RiskConfig.slippage_bps` (default 10, an assumption — no fill data yet), applied per side in
  `net_trade_pnl`; `--slippage-bps` on the engine CLI and `backtest_optimizer.py`. Paper trading (real fills) uses 0.
  Sensitivity on `data/` (330 trades, before these changes): each 10 bps ≈ −11.4k EGP. Proposed next step once fills
  exist: fixed + k·√(order value / 20-day traded value).
- **Optimizer selection:** best scenario chosen on the main (`data/`) window only; 2022-23 stays out-of-sample.
  Main-window metrics, and the trailing multiplier chosen on them, are in-sample. Scope of that out-of-sample test:
  **9 large caps only (ADIB, COMI, EAST, EFIH, ETEL, HRHO, MNHD, SWDY, TMGH), chosen in 2026 → survivorship bias and
  limited representativeness** of the 90-stock universe. (`data_health` rejects ADIB and TMGH there — 5 of 6,105 rows
  have Close up to 0.8% above High, an artefact of Yahoo's per-field adjustment — but the optimizer never calls
  `data_health`, so all 9 are used.)
- **Fees:** Thndr tariff from `fees_config.py` (live page read 2026-10-07). Open question: Thndr's fee page says
  "2 EGP + 0.1%", its Trader page says "0.1% with EGP 2 minimum"; the fee page (with a worked 5,000 EGP = 7 EGP
  example) is used until a real contract note settles it.
  **Settled by real statements (Jul–Sep 2026, 20 fills) and a Thndr invoice (2026-10-07):** the invoice itemises
  EGX 0.01%, MCDR 0.01%, FRA 1.00 minimum, insurance 0.005%, **stamp duty 0.05%**, brokerage 0.1% and an order fee of
  2 EGP — exactly `fees_config`, each component rounded half-up to the piaster. Statements: August and September match
  full `fees_config` on 13/15 fills; HEBCO 27/9 is −0.02 (rounding, ignored — FEE_TOLERANCE 0.02); the fund
  certificate below is the other.
  **Decision (Ahmed, 2026-10-07): الدمغة مش محصلة في يوليو 2026، السبب غير معروف. fees_config سليم.** July's 5 fills
  equal `fees_config` minus stamp exactly (= 3 EGP + 0.125% below 20k); that is the only month without stamp.
  `validate_balance` tags such a fill FEE_NO_STAMP (warning). An earlier note here read July as the general rule — wrong.
  **FUND_DOCUMENT_FEE:** buying 23 certificates of صندوق المصريين للاستثمار العقاري (exchange-traded, 2026-09-07) cost
  +1.01 EGP above `fees_config`. Cause unknown (issue fee? different tariff?) — ask Thndr support; not corrected.
  **Thndr subscription from 2026-09-24** (annual, 2,646 EGP debited 2026-09-25, 50 trades/month, not carried over):
  brokerage is still **charged** on each fill, then refunded the same day as a separate row "رد العمولة" equal to
  2 + 0.1% (6/6 fills). Net fee after the subscription = `fees_config` − brokerage. The ledger keeps the charged fee on
  the fill and the refund as `cash_events.commission_refund`. Statements before 24-09 carry full fees. A backtest of
  Ahmed's real cost needs fixed 2,646/yr + the non-brokerage components, not `fees_config` alone.

## Universe gaps — what `egx_universe.json` (v90-20261005) leaves out

Built by Codex's `universe_discovery.py` (`score()`, lines 83–101; top 90 by liquidity at line 216; script is not in
this repo). `egx_lists.filter_universe` applies it everywhere: dashboard, scanner, auto-sim, optimizer.
- **Price cap 5..500 EGP** drops liquid high-priced names: SCTS (545 EGP, 10.8M/day — price is its only failure),
  CPCI (596 EGP, 7.0M/day — price only), MIPH (812 EGP), AXPH (1,507 EGP), WCDF (654 EGP).
- **"Invalid High/Low/Close/Volume" anywhere in 2 years** drops the whole stock for a single bad row: 13 stocks with
  enough history (BIDI, MIPH, AXPH, NEDA, FNAR, WCDF, SEIG, SAIB, FAITA, MOIN, NINH, UNIT, EGREF).
- **MIPH (Mina Pharm)** specifically: price 812 EGP, 6-month mean turnover 4.79M EGP/day (threshold 5M), and 65 of 492
  Yahoo rows where Close is stuck at 156.92 while High/Low move (Yahoo did not update Close in late 2024).
- Decision 2026-10-07: universe unchanged for now; widening is deferred until the personal ledger
  (`docs/personal_ledger_design.md`) shows which stocks Ahmed actually trades.

## Phase 1b planned two-path debt (not wired yet)

The proposed runner dispatches TrendMirrors by strategy type to build_trade_plan
(legacy-path), and other strategies to generate_signals + exit_policy (new-path).
Both must use the engine's signal-bar ATR column and label results by path.
See docs/phase_1b_spec.md, "Temporary two-path debt", for the full contract.

Before wiring, freeze a full-trade legacy regression covering dates, prices,
initial stop/target, shares, reason, costs/P&L and cancellations. Plan snapshots
are not sufficient. test_plan_sizing.py contains an explicitly SKIPPED precondition;
that skip must be replaced by substantive assertions before C is accepted.
The debt is retired only when full-trade identity between both paths is proved
on agreed fixtures. Model changes require a separate reviewed impact analysis.
The shared position_size contract reads only RiskConfig.capital, risk_pct,
max_position_pct and max_avg_volume_pct. Any future change to that dependency
set must update its docstring and contract tests in the same change.
