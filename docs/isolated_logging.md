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
The five rows are SDK-level evidence, NOT the original HTTP body. A small custom
`curl_cffi` Session, passed via `yf.download(session=...)`, observes only Yahoo chart
requests. Each request records status, numeric Content-Length/Age when supplied,
safe range/interval/period parameters, exception type and UTC/Cairo times. First-byte
time comes from libcurl STARTTRANSFER_TIME (transfer start to first response byte,
including redirects), not a timestamp guessed from download completion.
UTC/Cairo first-byte timestamps are derived from request start plus that duration;
they are not an independent wall-clock callback measurement. The last
chart event supplies the top-level HTTP fields; inspect the list for retries and
preliminary timezone requests. Missing Content-Length is not replaced by an estimate.
Tested locally with yfinance 1.2.0 and curl_cffi 0.13.0; no dependency upgrade.
No DEBUG dump, HTTP body, cookies/session credentials or extra logging framework.
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

## Diagnostic limits

A captured 200 confirms an observed HTTP response; it does not prove fresh market
data or identify Yahoo/CDN caching. Age, when present, is only supporting evidence.
Age estimates time since origin generation/validation across caches and transit; it
does not identify a CDN specifically, prove local SDK caching, or establish stale
market rows. TTFB includes connection/network/server time, not the lag in publishing
a trading session. Content-Length counts representation bytes, not rows; a smaller
value alone does not prove missing data, and encoding/request differences matter.
References: [HTTP Age](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.1),
[Content-Length](https://www.rfc-editor.org/rfc/rfc9110.html#section-8.6),
[libcurl TTFB](https://curl.se/libcurl/c/CURLINFO_STARTTRANSFER_TIME.html).
No chart event is explicitly marked `no_chart_http_observed`, NOT automatically
classified as a cache hit. An exception or rejected download can still keep the
previous local CSV by the existing guard policy. Historical incidents with no saved
transport evidence cannot be reconstructed from this change. Cookie/token values
are intentionally never retained. Changes to yfinance's HTTP backend need review.

## Skipped-test register

Verified with `python -m pytest -q -rs` in the isolated checkout. The 39 skipped
cases are not network/live-data skips and are not counted as passing coverage:

| Cases | Location | Reason |
| --- | --- | --- |
| 33 | personal_journal/tests/test_ledger_parser.py | CSV parser fixtures explicitly deferred; no real CSV statement export validated |
| 1 | personal_journal/tests/test_ledger_parser.py | FIFO round-trip implementation deferred |
| 4 | test_statement_parser.py | Private, gitignored July/August statement PDFs absent from this checkout |
| 1 | test_plan_sizing.py | Legacy/generic trade identity not implemented; stop anchors differ |

All isolation/HTTP-evidence tests execute; none are deliberately skipped.

Verification on October 11: full suite 226 passed / 39 skipped; focused evidence,
freshness and retry suite 44 passed. A real, isolated COMI.CA download observed 200
for both timezone/history chart requests and first-byte durations; the 2y request
did not supply Content-Length. It returned 487 rows before the existing 250-row limit.
A later Ticker retained a usable session. These checks prove capture/compatibility,
not production readiness or the cause of October 5-7 incidents. No deployment performed.

## Predefined operational criteria

- Monitoring: five consecutive trading sessions with correct, documented status;
  no false success or holiday alert, and no test evidence in production.
- Readiness: five consecutive trading sessions with new data within the agreed
  deadline AND completed/stored report AND confirmed report delivery.
  Correctly detecting stale data satisfies monitoring, not readiness.

Five sessions are not five calendar days. October 14-18 contains only three regular
Sunday-Thursday dates (14, 15, 18); 16-17 are Friday/Saturday. If deployment and the
first verified session are October 14, the earliest five-session sequence is
14, 15, 18, 19, 20, subject to the approved calendar and actual successful evidence.

Milestones D2/D7/D14/D21 start only after deployment and verified evidence capture.
D2: capture/isolation proven; D7: first evidence review; D14: pattern review;
D21: explicit operational decision, not automatic acceptance or strategy deployment.
October 12: transport check target (implemented/tested earlier on October 11).
October 13: final review of BOTH branches, including isolated adjustment comparisons.
October 14: conditional combined deployment, only if both reviews pass. Waiting until
October 18-19 to review the adjustment branch is incompatible with a combined release
on October 14; if that review remains deferred, combined deployment is deferred too.
No automatic deployment is configured. If verified deployment happens October 14,
the 21-day maximum decision deadline is November 4; any later start shifts milestones.
A rebalance before that decision is not automatically authorized by publishing a fix;
source-readiness evidence and a separate operational decision remain necessary.
If a separately authorized rebalance precedes a later decision that the live path
is not ready, keep that rebalance under review with its original as-of data/evidence.
Do not treat its completion as readiness, erase/reprice its historical record, or
retroactively declare it accepted. The suspension applies from the recorded decision;
any retrospective audit remains distinct. The November 3-4 date alone grants no execution.
