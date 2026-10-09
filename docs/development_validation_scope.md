# Approved local development scope

هذا العمل تطويري فقط على 9 أسهم محلية.
- لا يثبت ترخيص البيانات ولا جودتها.
- لا يثبت امتثال سقف القيمة عند التنفيذ الفعلي (P1B-STOP-ANCHOR مفتوح).
- لا يثبت إمكانية التنفيذ (لا سبريد، لا أمر محدد، لا مزاد).
- أي رقم صافٍ هو بافتراض تنفيذ كامل، وليس دليلاً على ميزة قابلة للتداول.

legacy يُعتمد مرجعًا بحثيًا للتطابق البايتي فقط، غير ممتثل لسقف التنفيذ الفعلي (19 من 50 صفقة net، 38%). لا يُستخدم معيار قبول، ولا يُحسم P1B-STOP-ANCHOR بموجبه.

## Frozen before the first development run

- Local data_2019_2026_wf/ only; no downloads or source/licence assertion.
- Five adjacent half-open test windows, starting 2025-07-01, each three months.
  First ends 2025-10-01; final ends 2026-10-01 (that end date is excluded).
- Each window uses the preceding six months for indicator initialization only.
  No fitting/search occurs. This is fixed-parameter rolling development,
  not optimized OOS validation or a previously untouched holdout.
- Engine indicators restart at each training start. No positions/signals from
  the training interval are carried into testing. Partial history remains partial.
- The existing legacy runner scans all window bars with a subclass signal-date
  gate; entry/exit/sizing/fees/trailing math is not changed. A signal on the
  last possible bar retains legacy entry and END liquidation conventions.
- Every window is truncated at its end; remaining positions use the existing
  END liquidation on the final observed bar. Windows restart flat. END counts
  are reported rather than disguised as natural exits.
- min_trades=30 is a descriptive count flag only, not an acceptance criterion.
  Empty results remain empty; insufficient windows are not excluded from CSVs.
- Cost scenarios are explicitly loaded from config/development_validation.json.
  net_assumption copies existing fee assumptions; gross_zero_cost is a separate
  engine run with zero costs. These are not verified historical tariff series.
  No spread or probability-of-fill model is included; no net/gross log deletion.
- All effective configs, input/code hashes, raw source records, cancellations,
  closed-trade curves and raw execution-value cap breaches are exported.
- No shared account, benchmark superiority claim, MC, acceptance gate or paper.
- Output folders must be new and under outputs/; inputs and the frozen baseline
  are hash-checked before publication. No DB access by the development wrapper.

## Run

```powershell
Set-Location C:\Projects\EGX
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' -B -m validation.development --config config/development_validation.json --output outputs/development_walk_forward_20261009
```

No engine, existing runner or existing strategy edits are required. Every
generated report begins with the same approved limitations. New choices made
after viewing results require another explicit config and a new output folder.

## Verification record

Synthetic wrapper checks: 6 passed. Broader focused selection: 110 passed,
1 unchanged legacy/generic debt skip. The first test invocation reached all
6 successful assertions but failed on Windows cleanup of an old global pytest
temporary link; reruns use isolated --basetemp and completed successfully.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' -B -m pytest -q -rs -p no:cacheprovider --basetemp 'C:\Users\ahmed\Documents\Codex\2026-10-05\a\pytest_development_regression_20261009' test_development_validation.py test_plan_sizing.py test_exit_policy.py test_execution.py test_validation_runner.py
```

CSV content SHA-256 serves as the local file version; provider version is
unknown, not inferred. Loader/engine/config content hashes are in metadata.
These checks verify technical orchestration, not source quality or an edge.

## First development artifact

outputs/development_walk_forward_20261009/ contains report.md, windows.csv,
trades.csv, cancelled_trades.csv, equity_curves.csv, metadata.json and
source_registry.json. Five windows / two independent cost runs completed.
There are 50 completed net-assumption trades and 53 zero-cost trades;
all windows are below the descriptive 30-trade count, with no cancellations.
Each scenario has 19 completed-trade raw-notional cap breaches. The approved
classification is research-only, noncompliant with the actual-execution value
cap; this is not a profitability conclusion. Two END liquidations occur in
each scenario.
All 74 recorded input/code/config/baseline fingerprints remain unchanged.
The report's opening limitations match metadata (after Windows newline
normalization). MC is DISABLED and eligible_for_pass_fail is false.

Tracked summaries: [report](development_walk_forward_report.md) and
[verification](development_validation_checks.md). Raw outputs and the new
development implementation/config remain local and outside this docs commit.
