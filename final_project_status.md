# EGX Trading System — Final Project Status (2026-10-04 20:15)

**Bottom line:**
- **Technically:** works and is consistent.
- **As an edge:** not proven. `decision_report.md` = **ABANDON (MED confidence)**.
- **Use:** manual review + paper trading only. No real money.

## 1. Tests

| Suite | Result | What it covers |
|---|---|---|
| `test_setup_cards.py` | **29/29 ✅** | Patterns, card rules, Mirrors label on BEST cards, Tab 8 (Mirrors column + "4/4 only" filter), CSV/PDF export, HTML escaping |
| `test_signal_engine.py` | **23/23 ✅** | Tab 9: buy now / wait for breakout / sell, portfolio, Telegram (stub), the dashboard on real + demo + empty data |
| `test_closure.py` | **16/16 ✅** | Daily runner `--dry-run` on 3 folders + the real DB unchanged (sha256), the TV validator (5 ticker formats + 5 scenarios + DB rows), a full webhook (200/401, DB, log, server shutdown) |
| **Total** | **68/68 = 100%** | |
| `consistency_check.py` | **PASS — 0 contradictions** | Static (nothing imports v2) + live (the dashboard itself) + historical 1,235 stock-days (COMI/SWDY/ETEL) across tabs 2/3/8/9 |

Logs:
- `logs/closure_test_20261004.log`
- `logs/signals_test_20261004.log`
- `logs/setup_cards_20261004.log`
- `logs/consistency_20261004.log`
- `logs/final_closure_20261004.log`

## 2. Files

| File | Purpose | Status | Last modified |
|---|---|---|---|
| `egx_4_mirrors_v3.py` | Engine: indicators, 4 Mirrors, trade plan, scanner (true daily VWAP; VWAP_20 on daily data) | ✅ The only engine | 10-04 18:49 |
| `egx_4_mirrors_v2.py` | Old engine (cumulative VWAP — bug) | 🗄️ DEPRECATED, reference only, nothing imports it | 10-04 19:50 (comment only) |
| `egx_4_mirrors_system.py` | First version (before v2) | 🗄️ Historical, unused | 10-04 17:28 |
| `egx_dashboard.py` | Streamlit, 9 tabs, all on v3 | ✅ | 10-04 20:03 |
| `setup_builder.py` | Setup Cards (Tab 8) + Mirrors label for BEST | ✅ v3 | 10-04 20:03 |
| `pattern_detector.py` | Pattern detection (triangle/cup/flag/higher lows) — doesn't use the engine | ✅ | 10-04 18:32 |
| `signal_engine.py` | Tab 9 + CLI `--notify`: buy / wait / sell + portfolio + Telegram | ✅ v3 | 10-04 19:44 |
| `portfolio.csv` | Manual portfolio (edited from Tab 9) | ⚪ Empty — enter your holdings | 10-04 19:44 |
| `daily_runner.py` | Daily scan + analytics + Excel report + Telegram | ✅ `--dry-run` fixed (see §5) | 10-04 20:05 |
| `validate_tv_signals.py` | Validates TradingView alerts with the Python engine + SQLite | ✅ v3 + `normalize_ticker` | 10-04 20:05 |
| `tv_webhook_server.py` | Flask `/tv-webhook` `/health` `/recent` `/stats` | ✅ | 10-04 18:22 |
| `telegram_notifier.py` | Telegram send with DRY-RUN when there is no token | ✅ ⚠️ last edit isn't mine (§6) | 10-04 20:10 |
| `setup_telegram.py` | Telegram setup helper (getMe/getUpdates + test message) | ⚠️ Not mine (§6) — reviewed, not run | 10-04 20:10 |
| `analytics_engine.py` | Alert analytics (win rate, sectors, Excel) | ✅ v3 (SECTOR_MAP only) | 10-04 19:50 |
| `pine_egx_v2.pine` | TradingView indicator (title "v3") | ✅ VWAP fixed; ⚠️ not compiled inside TradingView | 10-04 20:00 |
| `backtest_optimizer.py` | Scenarios A/B/C/D, realistic execution | ✅ | 10-04 18:57 |
| `decision_analysis.py` | 2020–21, USD, walk-forward, market filter | ✅ | 10-04 19:17 |
| `consistency_check.py` | Signal consistency across tabs | ✅ PASS | 10-04 19:51 |
| `test_setup_cards.py` · `test_signal_engine.py` · `test_closure.py` | Tests | ✅ 68/68 | 10-04 20:03–20:06 |
| `egx_signals.db` | SQLite: tv_alerts 14 · alert_outcomes 0 · daily_reports 1 | ✅ Not touched by any test | 10-04 18:23 |
| `.env` | Settings (Telegram empty, WEBHOOK_SECRET set) | ⚠️ Not mine (§6) | 10-04 20:10 |
| `Dockerfile` · `railway.json` · `requirements_*.txt` · `setup_scheduler.ps1` | Deployment / scheduling | ⚪ Not used in testing | 10-04 17:57–18:06 |
| Reports | `optimization_report.md` · `optimization_report_v2.md` · `decision_report.md` · `signals_report.md` · `test_setup_cards.md` · `final_test_report.md` | 📄 | — |
| Data | `data/` (9 stocks 2024-10→2026-10) · `data_2022_2023/` · `data_2020_2021/` · `data_2019_2026_wf/` (+ `fx/EGP_USD.csv` from Yahoo `EGP=X`) | ✅ Real data, Yahoo | — |

Backups: `outputs_backup_20261004_1815` … `outputs_backup_20261004_2003_before_final_closure` (7 in total).

## 3. Ready vs Pending

**Ready (technically):**
- Dashboard 9 tabs on one engine.
- Setup Cards + Mirrors labels.
- Tab 9 signals + portfolio.
- Daily runner (normal and `--dry-run`).
- TV validator + webhook (authentication, normalization, storage).
- DRY-RUN Telegram.
- Consistency check.

**Pending:**

| Item | Why |
|---|---|
| A real Telegram token | `.env` has empty values → everything is DRY-RUN |
| Pine in TradingView | Paste it into the Pine Editor, check it compiles, recreate the alerts (the old alerts are tied to the old version) |
| Deploy the webhook (Railway/Docker) | Not tested; it ran locally on 127.0.0.1 only |
| Task Scheduler for the daily runner | `setup_scheduler.ps1` not run |
| A proven edge | ABANDON (MED) — see the warnings |
| Portfolio | `portfolio.csv` is empty |

## 4. Important warnings
1. **No proven edge.**
   - In USD, Scenario D beat Buy & Hold on Sharpe in only 1 of 3 periods.
   - Walk-forward: positive in only 2 of 4 test years.
   - Its value is lower drawdown, not higher return.
   - 4/4 signals are rare: today all 9 stocks are 0–2/4.
2. **Manual review only.** Every card, signal and message says "not a trade order".
3. **Paper trading is required.** The current decision gate is 15 closed trades over 6 months before any money.
4. **Data:**
   - Yahoo (auto-adjusted).
   - Daily candles only, so the true daily VWAP has no meaning without intraday data.
   - The EGX30 comparison used an equal-weight proxy.
5. **Costs:** 0.3% per side + 10% tax on gains. The Tab 9 PnL excludes them.

## 5. What changed in this closure
1. **BEST Cards:**
   - The note now starts with `📊 Mirrors: N/4 — …` (4/4 ✅, 3/4 ⚠️, ≤2/4 🔴); BEST still does not require 4/4.
   - Tab 8: a colored Mirrors badge on each card + a summary table with a colored Mirrors column + an "اعرض فقط 4/4" filter.
   - In ETEL's history, the 4 BEST cards came out with 2/4 and 3/4 and the correct labels.
2. **Tab 9:** title verified: "⏸️ انتظر الاختراق (BUY 4/4 في الماسح — لسه تحت التنشيط)". Logic unchanged.
3. **Daily runner `--dry-run`:** it was writing to the DB despite the flag:
   - `evaluate_pending_alerts` writes `alert_outcomes`;
   - `_reported_tickers` creates a table and commits;
   - and it wasn't generating the Excel file.

   Now it skips both DB writes and generates `reports/daily_YYYYMMDD.xlsx` (a local file).

   | Folder | Exit | Stocks | Buys |
   |---|---|---|---|
   | `data` | 0 | 9 | 0 |
   | `data_2022_2023` | 0 | 9 | 1 |
   | empty | 0 | 0 | 0 |

   The DB is identical before and after (sha256 + row counts).
4. **TV Validator:**
   - New `normalize_ticker`: COMI / COMI.CA / EGX:COMI / EGX:COMI.CA / comi.ca → `COMI.CA`, in validation and in DB storage. Previously the raw ticker was stored as-is (`EGX:COMI`), which breaks the sector analysis.
   - The 5 scenarios gave CONFIRMED / MISMATCH / REJECT ×3 with correct status/confidence/py_mirrors_json. For 4/4 = true I used COMI data truncated at 2026-08-05, a real BUY day.
   - The full webhook gave 200 CONFIRMED + `telegram=dry_run`, and the wrong secret gave 401 with no storage.
5. **The test server I ran earlier was stopped** on your request (port 5000 closed).

## 6. ⚠️ Changes not made by me (noticed at 20:10)
These appeared during the work and **I didn't write them**:
- **`.env`:** Telegram empty; `WEBHOOK_SECRET` set (length 28); `DB_PATH`, `DATA_FOLDER`, `LOG_LEVEL`, `PORT`.
- **`telegram_notifier.py`:** reads `.env` from the project folder instead of the current directory, and its smoke test checks DRY-RUN.
- **`setup_telegram.py`:** new; validates the token, finds the Chat ID, sends a test message.

I reviewed them and they look correct and harmless. I re-ran `test_closure` after they appeared: 16/16. I **did not** run `setup_telegram.py`, because it sends a real message once there is a token. Please confirm they are yours (or Codex's).

## 7. Your next steps
1. **Telegram:**
   - Create a bot via @BotFather.
   - Put `TELEGRAM_BOT_TOKEN` in `.env`.
   - Send /start to the bot.
   - Run `python setup_telegram.py` → it shows you the Chat ID → put it in `.env` → run it again for a test message.
2. **TradingView:** paste `pine_egx_v2.pine` into the Pine Editor → Save → create the "EGX BUY" alert with the webhook URL + the `X-Webhook-Secret` header (not available in all TradingView plans — check), or put the secret in a different way.
3. **Paper trading:**
   - Enter positions in `portfolio.csv` (from Tab 9) without real money.
   - Run `python signal_engine.py --notify` daily after the market closes.
   - Log every signal and its outcome for 6 months, targeting at least 15 closed trades.
   - Then compare against EGX30.
4. **Before any real money:** re-run `decision_analysis.py` on the paper-trading results. The decision needs data the backtest couldn't provide (real EGX30, return on cash, real execution).
