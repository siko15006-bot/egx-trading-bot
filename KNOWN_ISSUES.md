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
