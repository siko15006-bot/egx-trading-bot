# Personal trading ledger — design (no code until the Thndr statement arrives)

Status 2026-10-07: design only. Paper trading stays paused. Code starts after Ahmed sends his Thndr statement, because
the parser depends on its real format.

## Purpose

Turn Ahmed's **real** Thndr trades into one ledger that answers three questions with numbers:
1. What did each trade really earn after every fee, tax and dividend?
2. How does he trade (holding time, sizing, cutting losers vs. winners, overtrading)?
3. Which source did a trade follow (a Telegram channel, EGXBot, H3, the scanner, his own idea), and how did each
   source do **on his actual fills**?

It also settles two open questions from `KNOWN_ISSUES.md`: the real Thndr brokerage formula ("2 EGP + 0.1%" vs.
"0.1% with EGP 2 minimum") and which stocks outside the 90-stock universe he trades (e.g. MIPH).

## Privacy

Personal financial data: separate SQLite file `personal_ledger.db` (gitignored, like `*.db`), never sent to Telegram
or shown on a shared page, raw statement files kept outside the repo. Nothing from it goes into research datasets.

## Schema (SQLite, append-only imports)

| Table | Columns | Notes |
|---|---|---|
| `imports` | id, file_name, sha256, imported_at, period_from, period_to, row_count | Same file twice → rejected by sha256 |
| `raw_rows` | import_id, row_no, raw_json | Untouched copy of every statement row (audit trail) |
| `fills` | id, import_id, row_no, ts_cairo, ticker, side (BUY/SELL), qty, price, gross_value, brokerage, egx, mcdr, fra, insurance, stamp, other_fees, total_fees, order_ref | One row per executed transaction; UNIQUE(import_id, row_no) — see "Fill identity" |
| `cash_events` | id, import_id, ts_cairo, kind, ticker, amount | dividend, stamp T0 refund, commission kickback (Trader), custody fee, subscription, deposit, withdrawal |
| `round_trips` | id, ticker, open_ts, close_ts, qty, avg_buy, avg_sell, fees, dividends, tax, net_pnl, net_pct, holding_sessions, same_session | Derived (rebuilt, never edited): FIFO matching of fills per ticker |
| `trip_sources` | trip_id, source, ref, lag_minutes | Derived: matched signal, if any (see below) |

## Fill identity (changed 2026-10-07, found by Codex's ledger tests)

The first schema made `(order_ref, ts_cairo, qty, price)` unique. Two genuine executions can share all four (same day,
stock, quantity and price — e.g. two fills of one order), so the second would have been rejected and the trade lost.
A fill is now identified by **where it came from: row `row_no` of import `import_id`**, `UNIQUE(import_id, row_no)`.
- Importing the same file twice is still blocked by `imports.sha256`.
- New risk this opens: two *different* files covering the same days (e.g. a monthly and a yearly export) would load
  the same trades twice. `validate_balance` must therefore reject a new import whose period overlaps an earlier one
  unless the overlap is explicitly resolved; reconciliation with the app's holdings is the backstop.

## Parser

1. **Detect format**: CSV / XLSX / PDF. PDF only if no export exists (PDF table extraction is the fragile path).
2. **Map columns** from a small header dictionary (Arabic and English headers, Eastern-Arabic digits → ASCII,
   thousands separators, "ج.م"). Unknown column → stop with a clear error, never guess.
3. **Normalise**: Cairo timestamps, `TICKER.CA`, side, quantities as integers, money to 2 decimals.
4. **Validate before writing**:
   - qty × price ≈ gross value (tolerance 0.01 EGP);
   - recompute fees with `fees_config.order_fees` and report every difference > 0.01 EGP (this tells us the real
     brokerage formula);
   - final holdings per ticker reconcile with the app's current portfolio (last memory snapshot: 16,042.32 EGP on
     2026-09-29) — a mismatch means missing rows;
   - no sell larger than the open position (otherwise a transfer or corporate action is missing).
5. Write `imports` + `raw_rows` + `fills` + `cash_events` in one transaction; derived tables rebuilt afterwards.

## Behavioural analysis (first report)

| Area | Metric |
|---|---|
| Results | net PnL, expectancy per trip (EGP and %), win rate, average win / average loss, fee drag (% of gross PnL) |
| Benchmark | each trip vs. equal-weight universe and vs. the same stock bought and held, over the same dates |
| Holding | distribution of holding sessions; same-session (T0) share |
| Disposition effect | proportion of gains realised vs. proportion of losses realised (Odean PGR − PLR) |
| Sizing | position size vs. account value; averaging down count; max concentration in one stock |
| Activity | trips per week; clustering after losses (revenge trading); trades in the first/last 30 minutes |
| Sources | per source (Telegram channel, EGXBot, H3 top 10, scanner BUY, none): trip count, net expectancy |
| Universe | tickers traded that are outside `egx_universe.json` |

Source matching rule (fixed in advance): a BUY is attributed to a signal for the same ticker received in the
preceding 2 trading sessions (`tg_signals`, `tg_raw`, `h3_forward`, scanner BUY list); nearest one wins; otherwise
"own idea". Matching never changes the PnL, only the grouping.

## What I need from the statement (questions for Ahmed)

1. Format: CSV / Excel / PDF, and the date range it covers.
2. Does it show fees per order (broken down or total)? Partial fills as separate rows?
3. Are dividends, T0 stamp refunds and Trader commission kickbacks listed?
4. Any transfers in/out of shares, IPO allocations or bonus shares in the period?

## Tests (written with the parser)

One small fixture built from 3–4 real rows (anonymised amounts) covering: buy, partial sell, full sell, dividend,
T0 refund; asserts on parsed fills, FIFO round trips, fee recomputation and the duplicate-import guard.

## Open design notes (from the Gemini test review of f4739c5, 2026-10-07 — decided, not yet implemented)

- **Money storage:** `REAL` columns (price, gross_value, fees, amounts) are binary floats. Before real data is
  written, switch money to integer piasters (EGP × 100; prices at the exchange's tick size if finer) or SQLite
  `NUMERIC` with values passed as `Decimal`, and do the arithmetic in `Decimal` (Codex's tests already compare
  with `Decimal`). Not urgent while the tables are empty; must be settled together with the parser.
- **`validate_balance`:** the oversell check ("no SELL larger than the open position") must run on the fills alone,
  always — it must not depend on the optional `holdings` argument, which only adds the reconciliation with the app.
