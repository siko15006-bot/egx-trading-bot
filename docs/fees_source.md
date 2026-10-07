# Fee Scenario Provenance

Source: Thndr Help Center - Thndr Order Fees
URL: https://support.thndr.app/en/articles/638558-thndr-order-fees
User-provided URL: https://support.thndr.app/ar/articles/638558
Accessed: 2026-10-07
Published: 2026-08-18

Standard stocks/ETFs tariff only, no Trader subscription waiver.
FRA is per transaction, with a 1 EGP minimum and 250 EGP maximum.
An order of 5,000 EGP executed once costs 11.75 EGP overnight, not 11.
Buy stamp duty starts at 0.05%; same-session disposal reduces the final
rate to 0.025% by refund. The article states applicability since 2026-06-29.

The code calculates final round-trip cost, not refund timing or wallet cash
flows for partial same-session disposal. It assumes one transaction per
order unless actual fill notionals are supplied. TODO: execution-generated
partial fills are not implemented; supplied fills only affect fee accounting.
Historical fee schedules before that date remain UNKNOWN. Applying this
tariff to earlier bars is a current-tariff scenario, not historical truth.
Invoice component rounding rules are UNKNOWN; no per-component rounding.
Annual custody fees and subscriptions are excluded. Existing capital-gains
and dividend tax assumptions are NOT verified by this tariff article.

Execution (entry, stop/target fills, filler rows, data breaks) is now one shared policy
for core, optimizer and auto_sim: see docs/execution_policy.md (2026-10-07). The note
that originally stood here (close-of-signal entry, Open-based gap fills) is superseded.
No production source, prices, CSVs or databases were modified.
