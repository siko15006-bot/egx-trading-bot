هذا العمل تطويري فقط على 18 سهمًا مختارًا، وليس تحققًا مستقلًا من الجودة.
- لا يثبت ترخيص البيانات ولا جودتها أو تغطية كون تاريخي point-in-time.
- legacy مرجع بحثي غير ممتثل لسقف التنفيذ الفعلي؛ قرار المرجع أُغلق دون إصلاحه.
- لا يثبت إمكانية التنفيذ (لا سبريد، لا أمر محدد، لا مزاد).
- أي رقم صافٍ يفترض التنفيذ الكامل، وليس دليلًا على ميزة قابلة للتداول.

# Legacy signal pipeline diagnostic

Recorded 2026-10-09, against code HEAD c49160c and the existing 18-stock
development experiment. No filter, execution, cost or position rule was changed.
The observed test period is 2025-07-01 through 2026-09-30: 15 months, not
the seven-year download range. Five three-month windows use six-month
initialization, no fitting, flat restarts and existing END liquidation.

## Definitions

- BUY before screener already satisfies all four mirrors and their volume/ADX
  gates. It is NOT an unconditional signal before every filter.
- Screener checks price, history, mean volume, traded value and recent active
  days. Volatility is one mirror, not an independent prefilter.
- Counts cover decision bars only: no initialization entries or last-bar signal.
- All-bar BUY counts ignore positions. Occupied-loop candidates fall after an
  accepted signal through its exit; cancelled intervals end before the break.
  These are unvisited decision bars, not queued orders or measured lost profits.
- Mirror failure counts overlap. Sole-blocker counts indicate extra potential
  signals if one condition were removed, not extra completed trades.

## Net funnel

| Window | BUY before screener | After screener | Occupied loop | Entry rejected | Completed |
|---|---:|---:|---:|---:|---:|
| 1 | 18 | 13 | 5 | 0 | 8 |
| 2 | 53 | 53 | 29 | 0 | 24 |
| 3 | 65 | 65 | 34 | 0 | 31 |
| 4 | 40 | 40 | 24 | 1 | 15 |
| 5 | 62 | 62 | 42 | 0 | 20 |
| Total | 238 | 233 | 134 | 1 | 98 |

Conservation: 238 - 5 = 233; 233 - 134 - 1 = 98. No plan rejection or
cancellation occurred among eligible candidates. Gross has the same 233 BUY
bars, 129 occupied-loop candidates, two entry rejections and 102 completions.

Screener removed 5/238 BUY candidates (2.1%). This conditional statistic does
not imply the screener does nothing: 469/5,400 decision bars failed it overall.
After screener and ADX gates, 3,259 bars reached mirror evaluation.
There were 199 zero-volume decision bars; they failed screening before the
mirror helper's zero-volume branch. Its zero counter is not evidence of absence.

## Mirror barriers

| Mirror | Fails / 3,259 bars | Failure rate | Sole blocker |
|---|---:|---:|---:|
| Trend | 1,021 | 31.3% | 79 |
| Momentum | 2,199 | 67.5% | 297 |
| Volume | 2,615 | 80.2% | 590 |
| Volatility | 1,149 | 35.3% | 2 |

All four must pass simultaneously. The 238 pre-screener BUY already include
that intersection; they cannot subsequently be attributed to mirror rejection.
This is an operational diagnosis, not evidence that any mirror lacks value.

## Entry timing and holding duration

| Entry month | Net | Gross |
|---|---:|---:|
| 2025-07 | 5 | 5 |
| 2025-08 | 0 | 0 |
| 2025-09 | 3 | 3 |
| 2025-10 | 9 | 9 |
| 2025-11 | 7 | 9 |
| 2025-12 | 8 | 8 |
| 2026-01 | 16 | 16 |
| 2026-02 | 10 | 10 |
| 2026-03 | 5 | 5 |
| 2026-04 | 7 | 7 |
| 2026-05 | 7 | 8 |
| 2026-06 | 1 | 1 |
| 2026-07 | 10 | 10 |
| 2026-08 | 8 | 8 |
| 2026-09 | 2 | 3 |

Net holding duration: mean 10.673469, median 9, maximum 38 Cairo calendar
days. Elapsed observed-bar transitions (exit_index - entry_index): mean
7.204082, median 6, maximum 27. Gross calendar durations: mean 9.186275,
median 7, maximum 36. One month has no entries, not a prolonged global absence.

## Single-position rule

This behavior exists in the engine's current legacy backtest, not just the
new validation wrapper: egx_4_mirrors_v3.py::backtest runs one position to
completion and advances i = max(exit_index + 1, i + 1). validation.runner
preserves it. Signals on those skipped bars are not replayed after exit.
This establishes implementation lineage, not author intent in an independent
original strategy specification. It is a model rule, not a discovered bug.

Allowing simultaneous lots would require a different exposure, sizing and
execution model. The 134 skipped BUY bars are not a guarantee of 134 extra
trades, better performance or statistical independence.

## Evidence and limits

The diagnostic reused mirror_rejections, passes_screener, evaluate_4_mirrors,
build_trade_plan, simulate_trade and net_trade_pnl. Assertions matched existing
completed-trade entry, exit, stop, target, shares, exit date/reason and PnL
exactly. Funnel counts conserved; 60 protected artifact/reference files were
unchanged. This is legacy self-consistency, not generic-path parity or an
independent price-quality oracle. Cancellation coverage remains open.

Prior focused suite: 111 passed, one unchanged skip. This means 110 plus one
explicit-universe/zero-volume-preservation test, not unexplained test recovery.
Diagnostic assertions are separate from that pytest result.

Local artifacts (not committed, not guaranteed available in a clean clone):
outputs/yahoo_expansion_18_20261009/ contains the experiment config, raw and
adjusted files, download manifest, walk_forward/ and pipeline_diagnostic/.
The external one-off diagnostic harness also remains local, not shipped here.
SHA-256 anchors for actual files, not empty manifests:

```text
experiment.json
8670d087b8bf2fea300540272e1ceab639a5fc43e9e49f902134e8f910919d30
walk_forward/trades.csv
094bc05c8b8d6627a0c6eebd4f6ed8f400f6d88ae415a2704622dfa87da57dea
pipeline_diagnostic/funnel.csv
60db8c38a25122831459dd6ec9119dc58b4904a7eb10e34aaeb23c4c031bb6f0
```

No acceptance gate, concurrency variant or longer-history run is authorized
by this record. A proposed 2019-2024 inclusive period spans six calendar years,
not five. Trade counts cannot be linearly guaranteed from 15 months, and
reviewed historical data are not a pristine untouched holdout. A larger
sample alone cannot make the noncompliant legacy model an acceptance oracle.
