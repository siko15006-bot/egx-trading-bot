# Known issues

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

## Yahoo filler rows (zero-volume flat bars) — provider gap, not market behaviour

Rule adopted 2026-10-06. Raw CSVs stay untouched; this applies at analysis/backtest time only.

- **filler** = `Volume == 0 and Open == High == Low == Close`. **real** = Volume > 0.
  **ambiguous** = Volume 0 but OHLC not flat (handle case by case).
- Measured on `data/` (90 files, 22,500 rows, 2025-10-05 → 2026-10-05): 1,000 filler, 0 ambiguous.
- Fillers cover holidays (06-17/18) **and real sessions**: 06-22 (90/90), 08-09/10 (89, 88), 08-16 (89).
  08-10 was a confirmed session (EGX30 traded, EGP 14.9bn). So filler = Yahoo calendar gap, not "no trading".
- The 4 "Open != prev Close" days (06-21, 06-23, 08-11, 08-17 — 353 of 379 mismatches) are the first
  real day after a filler run: prev Close is a filler value, not real.
- Handling:
  1. Filler rows are flagged and excluded from any OHLC-based calc; their return/PnL = NA, never 0.
  2. The first real row after a filler gets `open_reference_unverified`: its `prev_close` = NA,
     but its own Open stays usable.
  3. No entries at a filler Open; no SL/TP or gap logic built on a filler prev_close.
  4. Every performance report states the filler count and that metrics cover verifiable rows only.
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
