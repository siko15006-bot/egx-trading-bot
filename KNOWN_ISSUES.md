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
