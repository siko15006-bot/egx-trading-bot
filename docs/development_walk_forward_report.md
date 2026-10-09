هذا العمل تطويري فقط على 9 أسهم محلية.
- لا يثبت ترخيص البيانات ولا جودتها.
- لا يثبت امتثال سقف القيمة عند التنفيذ الفعلي (P1B-STOP-ANCHOR مفتوح).
- لا يثبت إمكانية التنفيذ (لا سبريد، لا أمر محدد، لا مزاد).
- أي رقم صافٍ هو بافتراض تنفيذ كامل، وليس دليلاً على ميزة قابلة للتداول.

legacy يُعتمد مرجعًا بحثيًا للتطابق البايتي فقط، غير ممتثل لسقف التنفيذ الفعلي (19 من 50 صفقة net، 38%). لا يُستخدم معيار قبول، ولا يُحسم P1B-STOP-ANCHOR بموجبه.

## Development results

Local artifact: outputs/development_walk_forward_20261009/ (not committed).
Nine stocks, fixed parameters, six-month initialization and three-month test
windows. No fitting, holdout claim, MC or acceptance decision.

| Window | Scenario | Trades | Cancelled | P/L EGP | Count status | END exits | Cap breaches |
|---|---|---:|---:|---:|---|---:|---:|
| 1 | net_assumption | 5 | 0 | 4090.66 | INSUFFICIENT | 1 | 1 |
| 1 | gross_zero_cost | 5 | 0 | 4797.20 | INSUFFICIENT | 1 | 1 |
| 2 | net_assumption | 13 | 0 | -1056.84 | INSUFFICIENT | 1 | 8 |
| 2 | gross_zero_cost | 15 | 0 | 322.27 | INSUFFICIENT | 1 | 8 |
| 3 | net_assumption | 13 | 0 | 2698.32 | INSUFFICIENT | 0 | 5 |
| 3 | gross_zero_cost | 13 | 0 | 3629.42 | INSUFFICIENT | 0 | 5 |
| 4 | net_assumption | 8 | 0 | 4051.95 | INSUFFICIENT | 0 | 2 |
| 4 | gross_zero_cost | 9 | 0 | 3556.20 | INSUFFICIENT | 0 | 2 |
| 5 | net_assumption | 11 | 0 | 429.40 | INSUFFICIENT | 0 | 3 |
| 5 | gross_zero_cost | 11 | 0 | 1985.58 | INSUFFICIENT | 0 | 3 |

Totals: 50 net-assumption / 53 gross-zero-cost trades; all windows below 30.
The 19 breaches per scenario mean 38% net and approximately 35.8% gross.
Counts use completed raw executed notionals, excluding fees and cancelled
exposure. Zero cancellations do not verify the cancellation branch.

Net/gross are separate full engine runs; costs can change targets and later
trade availability. These results do not claim byte identity with the frozen
243-trade reference or legacy/new-path equivalence. MC remains DISABLED;
eligible_for_pass_fail is false. Legacy code and data are unchanged.

See [scope](development_validation_scope.md) and
[verification record](development_validation_checks.md).
