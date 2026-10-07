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
| `position_events` | id, import_id, row_no, ts_cairo, ticker, kind, qty, ratio_num, ratio_den, cost_basis, review_flag | transfer in/out, bonus shares, IPO allocation, split — see "Event types" |
| `cash_events` | id, import_id, row_no, ts_cairo, kind, ticker, amount, review_flag | dividend, stamp T0 refund, commission kickback (Trader), custody fee, subscription, deposit, withdrawal |
| `round_trips` | id, ticker, open_ts, close_ts, qty, avg_buy, avg_sell, fees, dividends, tax, net_pnl, net_pct, holding_sessions, same_session | Derived (rebuilt, never edited): FIFO matching of fills per ticker |
| `trip_sources` | trip_id, source, ref, lag_minutes | Derived: matched signal, if any (see below) |

## Fill identity (changed 2026-10-07, found by Codex's ledger tests)

The first schema made `(order_ref, ts_cairo, qty, price)` unique. Two genuine executions can share all four (same day,
stock, quantity and price — e.g. two fills of one order), so the second would have been rejected and the trade lost.
A fill is now identified by **where it came from: row `row_no` of import `import_id`**, `UNIQUE(import_id, row_no)`.
- Importing the same file twice is still blocked by `imports.sha256`.
- New risk this opens: two *different* files covering the same days (e.g. a monthly and a yearly export) would load
  the same trades twice. Decision (Ahmed, 2026-10-07): **warn and flag, never block** — older statements must stay
  addable. `validate_balance` returns `PERIOD_OVERLAP` with the earlier import ids; they are stored in
  `imports.overlaps_imports`, every row of the new import gets `review_flag = 'POSSIBLE_DUPLICATE'`, and Ahmed confirms
  or removes them by hand. Reconciliation with the app's holdings is the backstop.

## Event types (decided 2026-10-07)

| Type | Table | Examples | Effect on cost basis |
|---|---|---|---|
| BUY / SELL | `fills` | executed orders, partial fills | BUY lots are the only purchase cost; SELL closes lots FIFO |
| POSITION | `position_events` | `transfer_in`, `transfer_out`, `bonus_shares`, `subscription_allocation` (IPO), `split` | change share count without a purchase: bonus/split spread the existing cost over more shares; a transfer's cost is `NULL` (unknown, not zero) and its shares stay out of P&L until the cost is known; IPO allocation carries its subscription cost from the matching cash row |
| CASH | `cash_events` | dividend, stamp refund, Trader kickback, custody fee, subscription, deposit, withdrawal | dividends/refunds enter trip P&L; deposits/withdrawals do not |

Kinds match Codex's acceptance fixtures. A position can never be written as a fill (`side` CHECK), so it can never
become a BUY lot.

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

## Implemented (2026-10-07, first statement E-STATEMENT_Jul_2026_01.pdf)

- Real format is a PDF (no Thndr CSV/XLSX export seen); `parse_pdf` reads it with pdfplumber, every row must
  reconcile with the running and closing balance. Company names → tickers via `personal_journal/company_names.json`.
- The statement has **no time of day**: `fills.ts_cairo` holds the date (`YYYY-MM-DD`), no invented time.
- The statement gives **total fees only** (gross − net): the component columns stay NULL.
- Money is still written to the frozen `REAL` columns (2-decimal values); piasters need an explicit migration.
- `validate_balance`: OVERSELL / GROSS_MISMATCH / HOLDINGS_MISMATCH block the import; FEE_DIFF / PERIOD_OVERLAP warn.
  A blocking tag is overridden only by `import_file(..., accept=(tag,))` on Ahmed's decision — used once for July:
  4 sells close shares bought before 2026-07-01 (OVERSELL on the rows alone), so their round trips lack a buy cost
  until an earlier statement is imported.

## Migration 1 + Aug–Sep statements (2026-10-07)

- `db.MIGRATIONS[0]` (explicit, `PRAGMA user_version` = 1): table `fund_holdings` (fund sub-account `*_02`
  statements: units REAL, value, balance; no fees, no FIFO, never in stock P&L); `cash_events.kind` adds
  `subscription_fee`, `commission_refund`, `transfer_to_fund`, `transfer_from_fund`; `imports` adds `account`
  (main/fund), `opening_balance`, `closing_balance`. Import id 1 (July) backfilled from its own file (sha256 checked).
- Chain check: an import's opening balance must equal the closing balance of the previous import of the same account
  (CHAIN_BREAK blocks). OVERSELL now counts shares already in the ledger (pre-ledger holdings count as 0).
- Fees: the fill keeps the fee as charged; a subscription refund ("رد العمولة") is its own cash event linked to the
  fill; net fee = charged − refund. Tags: FEE_NO_STAMP (July), FUND_DOCUMENT_FEE, REFUND_DIFF, FEE_DIFF (> 0.02).
- The fund account's transfer rows mirror the main account's transfers: raw_rows only, so cash is counted once.
- `company_names.json`: sections `companies`, `funds`, `_unresolved` (names whose ticker could not be verified — the
  parser stops on them and quotes the note). `analytics.fund_summary()` reports funds apart from stocks.
- E-INVOICE (per-trade contract note, itemised fees) is recognised and refused: separate parser later.

## Goal change (Ahmed, 2026-10-07)

The ledger judges **the project's signals**, not Ahmed: he trades only on system signals (Telegram channels, EGXBot,
H3, scanner). `analytics.attribute_sources` is therefore the core of the ledger, not a side metric — per source:
signal count, share followed, net result of followed trips, and "followed every signal" vs "what was actually done".
Prerequisites, not started (no new modules yet): every signal stored with source, time, ticker, direction and price
(today only `tg_signals` for one channel and `h3_forward` exist; `tg_raw` holds EGXBot text, not parsed signals);
a signal parser for Telegram text; a signal↔trip link table. Matching rule unchanged (same ticker, preceding 2
sessions). Note: statements have no time of day, so "preceding 2 sessions" is counted in whole sessions.
