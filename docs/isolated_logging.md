# Isolated daily evidence (MVP)

No calendar, expected-session, retry-deadline, strategy or price-adjustment changes.
No new dependencies. This branch does not merge `fix/yahoo-partial-backadjust`.

Production keeps its existing logs, DB, reports and latest health path. Each invocation
also writes `logs/runs/<run_id>/health_YYYYMMDD.json`. Multiple attempts on one day
have distinct IDs. A skipped retry records its own snapshot without replacing latest.
Health records distinguish analysis, report creation/storage and report vs failure-alert delivery.

Every Yahoo request in `data_downloader` records its returned DataFrame's last five
rows before normalization (including period fallback, empty results and exceptions),
raw row count, latest timestamp and both UTC/Cairo observation times.
This is SDK-level evidence, NOT the original HTTP body. `yf.download` does not expose
HTTP status/headers: status is null and headers empty, explicitly marked unavailable.
No HTTP interception, cookie/token storage or additional logging framework is added.
Only numeric market fields are retained; runtime log formatting redacts sensitive fields
and URL query strings. Standalone downloads save evidence inside the requested folder's
`.evidence/<run_id>/downloads`; daily downloads use their run's evidence directory.

`--dry-run` defaults to a newly allocated system temporary output root. An explicit
`--output-root` contains logs, evidence, reports and a separate DB, ignoring inherited
production DB_PATH. Isolated runs never send Telegram. Absolute input paths remain
read-only unless `--download` is supplied; isolated downloads reject destinations
outside their output root. Dry-run alone does not authorize modifying live data.

Example (isolated outputs, read-only existing input):

```powershell
python daily_runner.py --data-folder C:\Projects\EGX\data --dry-run --no-telegram --output-root C:\Temp\egx-check
```

The closure, signal-engine and setup-card script suites write their logs and reports
to temporary directories, not production logs/reports. Existing fixtures retain their
own temporary DB/data paths. Evidence retention/rotation is not implemented in this MVP.

## Predefined operational criteria

- Monitoring: five consecutive trading sessions with correct, documented status;
  no false success or holiday alert, and no test evidence in production.
- Readiness: five consecutive trading sessions with new data within the agreed
  deadline AND completed/stored report AND confirmed report delivery.
  Correctly detecting stale data satisfies monitoring, not readiness.

Milestones D2/D7/D14/D21 start only after deployment and verified evidence capture.
D2: capture/isolation proven; D7: first evidence review; D14: pattern review;
D21: explicit operational decision, not automatic acceptance or strategy deployment.
October 13-14 is a target, not an unattended deployment promise. The adjustment branch
requires its own isolated review before any combined release.
