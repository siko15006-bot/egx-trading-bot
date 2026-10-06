# Unified Signals — Tab 9 "🎯 إشارات اليوم" (2026-10-04)

**Tests: 23/23 ✅** (`python test_signal_engine.py`, log `logs/signals_test_20261004.log`) and Setup Cards is still **25/25 ✅**.
Backup before the change: `outputs_backup_20261004_1943_before_tab9`. `egx_4_mirrors_v3.py` was not modified.

> ⚠️ `decision_report.md` ended with **ABANDON (MED confidence)**. These signals are for manual review only, not trade orders. Every signal in the tab and every Telegram message says so.

## Files
| File | Status | Contents |
|---|---|---|
| `signal_engine.py` | New | All the logic: `classify` / `scan` / `review_portfolio` / `telegram_message` / `notify` + CLI |
| `egx_dashboard.py` | Modified | Tab 9 added (the existing 8 tabs are unchanged) |
| `portfolio.csv` | New (empty) | The manual portfolio: `ticker, shares, entry_price, entry_date, stop_loss, target, notes` |
| `test_signal_engine.py` | New | The tests below |
| `test_setup_cards.py` | One-line change | Its tab-count check was `== 8`; it is now `>= 8` because Tab 9 was added |

## Rules — every number is tied to a column
| Section | Condition | Numbers |
|---|---|---|
| 🟢 Buy now | `passes_screener` + `evaluate_4_mirrors` = BUY (4/4) + **today's** `Close` > the highest `High` over the previous 10 sessions, and yesterday's close was not above it | Entry/SL/TP/Shares/net R:R straight from `build_trade_plan` (Entry = `Close`, SL = `Close − 1.5×ATR`, TP adjusted for net R:R 2 after fees and tax) |
| ⏸️ Wait | 4/4 mirrors but `Close` ≤ activation level | Activation = `High.iloc[-11:-1].max()`, distance = (activation − Close)/Close |
| 🔴 Sell | For each `portfolio.csv` position: `Close` ≤ SL → sell; `High` ≥ target → take profit; `Close` < `EMA_50` → sell (Scenario D's exit rule) | Prices from the last bar; blank SL = −15% of entry (and labelled as such) |
| 📊 Snapshot | Number of holdings, total PnL = Σ(Close − Entry) × Shares, **before fees and tax** | Alerts: near SL (≤ 1×`ATR`), near target (≤ 1×`ATR`), close below `EMA_20`, stale data (> 4 days), ticker with no data |

Each row carries its reason as text, built from the same numbers (for example: "close 62.00 broke the 10-session high (60.30) for the first time today; 4/4 mirrors; volume 2.3× the 20-day average").

## Telegram
- **📨 button** in Tab 9, or `python signal_engine.py --notify` (for the daily runner or Task Scheduler).
- **One message** containing the buys, sells and alerts.
- **Text is HTML-escaped.**
- **Same message is never sent twice in a day** (`logs/signals_sent_YYYYMMDD.json`, sha256).
- **Without a token in `.env`** it sends nothing and logs a DRY-RUN.
- **The tests replaced `send_telegram` with a stub**, so no real message was sent.

## Today's state (real data, last bar 2026-10-01)
**Buy 0 · Wait 0 · Sell 0** (portfolio empty). None of the 9 stocks is anywhere near 4/4:

| Stock | ADIB | COMI | EAST | EFIH | ETEL | HRHO | MNHD | SWDY | TMGH |
|---|---|---|---|---|---|---|---|---|---|
| Mirrors | 0/4 | 0/4 | 0/4 | 1/4 | 2/4 | 0/4 | NO_TREND | 0/4 | 0/4 |

That's consistent with decision_report (the number of 4/4 stocks was 0 in 70% of weeks). **Expect the Buy and Wait sections to be empty most days.**

## Things to know
1. **There is no "Tab 11 Portfolio Tracker"** in the dashboard (it had 8 tabs). I put a minimal editor inside Tab 9 (the "✏️ Edit portfolio" expander), which writes `portfolio.csv` atomically. A future Tab 11 can use the same `load_portfolio`/`save_portfolio`.
2. **Setup Cards (Tab 8) are not wired into the signals.** `setup_builder` runs on the v2 engine (the old cumulative VWAP), so mixing the two would give inconsistent signals. Tab 9 uses the same activation idea (10-session high) on v3.
3. **Tab 9 uses v3, while the rest of the dashboard (tabs 2–8) still uses v2.** A stock can show BUY in the Scanner and not in Tab 9. Moving the dashboard to v3 is a separate decision.
4. **PnL excludes fees (0.3% per side) and the 10% tax on gains.**
