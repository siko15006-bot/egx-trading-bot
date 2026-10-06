# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

EGX (Egyptian Exchange) technical-analysis + paper-trading system: Yahoo Finance daily data → "4 Mirrors" v3 engine → signals/setups → SQLite + Telegram + Streamlit dashboard. Paper trading only, no brokerage execution. Paper campaign runs 2026-10-04 → 2027-04-04.

## Commands (PowerShell, from this folder)

```powershell
python -m pytest -q -p no:cacheprovider --basetemp="$env:TEMP\egx_pytest"   # full suite; default pytest tmp dir hits WinError 5 on this machine
python -m pytest test_daily_retry.py::<test_name> -q --basetemp="$env:TEMP\egx_pytest"
python test_closure.py          # end-to-end: daily_runner --dry-run + TV validator + local webhook; asserts real egx_signals.db is unchanged (sha256 + row counts)
python daily_runner.py --data-folder ./data --capital 100000 --dry-run      # safe local run, no DB/Telegram writes
python daily_runner.py --data-folder ./data --health-only                   # data freshness check only
python data_downloader.py --data-folder ./data --limit 520 --period 2y
streamlit run egx_dashboard.py  # http://127.0.0.1:8501 ; start_mobile_dashboard.ps1 binds 0.0.0.0 (trusted LAN only, no auth)
python bot_handlers.py          # Telegram advisor bot
```

No linter/build step. Deps: `requirements_analytics.txt` (local) and `requirements_webhook.txt` (Railway/Docker image for `tv_webhook_server.py`).

## Architecture

- `egx_lists.py` — the universe (`UNIVERSE`, `SECTOR_MAP`, filters, warnings). Everything imports tickers from here.
- `egx_4_mirrors_v3.py` — **the live engine** (`ScreenConfig`/`SignalConfig`/`RiskConfig`, `calculate_indicators`, `evaluate_4_mirrors`, `scan_universe`, `load_data_map`). `egx_4_mirrors_system.py` and `_v2.py` are older versions; don't edit them for live behaviour.
- `data_health.py` — freshness gate. `expected_session()` uses a Sun–Thu week, `EGX_DATA_CUTOFF` (default 14:30 Cairo) and `EGX_MARKET_HOLIDAYS` (comma-separated ISO dates in `.env`; holidays are never guessed). `require_daily_data` raises `DataHealthError` when data is stale.
- `data_downloader.py` — yfinance download with row-count guards against the cached CSVs in `data/`.
- `signal_engine.py` (`build_signals`) and `setup_builder.py` + `pattern_detector.py` (setup cards) sit on top of the engine.
- `daily_runner.py` — scheduled orchestration: download → health check → scan → `daily_reports` table → analytics → Telegram heartbeat/alert. With `--alert-after HH:MM` it is a retry loop: stale-data alerts are deferred until that time, and once today's report exists later runs exit early.
- `validate_tv_signals.py` + `tv_webhook_server.py` — TradingView alerts (`tv_alerts` table); `analytics_engine.py` (`alert_outcomes`); `paper_trading.py` (`paper_trades`, `paper_campaign`).
- All modules share one SQLite DB via `DB_PATH` (default `egx_signals.db`) and read `.env` with python-dotenv.

## Scheduled tasks (Windows Task Scheduler, all point at `C:\Projects\EGX`)

- `EGX_Daily_Runner` — 14:45 Cairo, `--notify --download --alert-after 19:30`. The retry design expects an hourly repeat (PT1H for PT5H5M) on the trigger; check it with `(Get-ScheduledTask EGX_Daily_Runner).Triggers.Repetition`.
- `EGX_Telegram_Bot` (`bot_handlers.py`, at sign-in), `EGX_Streamlit_Dashboard` (binds 0.0.0.0:8501).
- `setup_scheduler.ps1` (re)creates `EGX_Daily_Runner` with the hourly repeat and `--alert-after 19:30`.
- The old `Documents\Codex\2026-10-04\...\outputs` folder is a stale copy. Edit only this repo.

## Rules

- Tests must never touch the real `egx_signals.db`, `data/`, or `logs/`: monkeypatch `BASE_DIR`/DB path to `tmp_path` (see `test_daily_retry.py`) and stub `send_telegram`.
- Don't write into `egx_research_assistant`'s `state/` folder; any new state (e.g. `signals_today.json`) lives inside this project.
- `backups/`, `data_rejected/`, `data_20*` folders and `*.db.bak*` files are snapshots, not live code/data.
- Known issue (DST): see `KNOWN_ISSUES.md` — `assess_daily_data` breaks on the nonexistent Cairo midnight 2026-04-24.
