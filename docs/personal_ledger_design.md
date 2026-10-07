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
| `fills` | id, import_id, row_no, ts_cairo, ticker, side (BUY/SELL), qty, price, gross_value, brokerage, egx, mcdr, fra, insurance, stamp, other_fees, total_fees, order_ref | One row per executed transaction; UNIQUE(order_ref, ts, qty, price) |
| `cash_events` | id, import_id, ts_cairo, kind, ticker, amount | dividend, stamp T0 refund, commission kickback (Trader), custody fee, subscription, deposit, withdrawal |
| `round_trips` | id, ticker, open_ts, close_ts, qty, avg_buy, avg_sell, fees, dividends, tax, net_pnl, net_pct, holding_sessions, same_session | Derived (rebuilt, never edited): FIFO matching of fills per ticker |
| `trip_sources` | trip_id, source, ref, lag_minutes | Derived: matched signal, if any (see below) |

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
