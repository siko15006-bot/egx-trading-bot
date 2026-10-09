هذا العمل تطويري فقط على 9 أسهم محلية.
- لا يثبت ترخيص البيانات ولا جودتها.
- لا يثبت امتثال سقف القيمة عند التنفيذ الفعلي (P1B-STOP-ANCHOR مفتوح).
- لا يثبت إمكانية التنفيذ (لا سبريد، لا أمر محدد، لا مزاد).
- أي رقم صافٍ هو بافتراض تنفيذ كامل، وليس دليلاً على ميزة قابلة للتداول.

## Recorded checks

Development wrapper: 6 passed. Focused regression: 110 passed, 1 skipped.
These are completed test executions, not just collection counts.

The earlier 123 passed / 1 skipped and current 110 passed / 1 skipped are
different selections: 123 - 7 performance - 7 causality - 5 strategies
+ 6 development = 110. No failure or disappearance is implied.

Earlier selection:

```text
test_runner_performance.py test_indicator_causality.py test_validation_runner.py test_plan_sizing.py test_exit_policy.py test_execution.py test_strategies.py
```

Completed focused command:

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& 'C:\Users\ahmed\AppData\Local\Programs\Python\Python314\python.exe' -B -m pytest -q -rs -p no:cacheprovider --basetemp 'C:\Users\ahmed\Documents\Codex\2026-10-05\a\pytest_development_regression_20261009' test_development_validation.py test_plan_sizing.py test_exit_policy.py test_execution.py test_validation_runner.py
```

The initial six-test invocation passed assertions but exited unsuccessfully
on Windows cleanup of an old global pytest temporary link. An isolated
--basetemp rerun passed; this infrastructure failure is not omitted.

The unchanged skip is test_legacy_vs_new_path_trade_match in
test_plan_sizing.py. Legacy/new-path trade parity remains unimplemented;
stop anchors differ. P1B-STOP-ANCHOR remains open for Ahmed and is not
resolved by retaining legacy as a noncompliant research reference.

All 74 recorded input/code/config/reference hashes remained unchanged after
the development run. Report opening limits match metadata after Windows
newline normalization. No acceptance gate, source-quality validation or
tradable-edge conclusion follows from these checks.

This commit records results only. The development wrapper, configuration,
new tests and raw outputs remain outside this docs-only commit; the run
command in the scope document is not a clean-clone reproducibility claim.
