# EGX Trading System v3

EGX technical-analysis, paper-trading, TradingView, Telegram, and analytics system. The project uses the v3 engine and a 90-stock Yahoo Finance universe (`egx_universe.json` v90-20261005).

> **Status (2026-10-06): monitoring and alerting tool, not a trading strategy.** The 4 Mirrors strategy was tested and ruled
> **ABANDON (confidence MED)** in `decision_report.md`. Do not use its signals as the sole basis for trading.
> Data caveats: `KNOWN_ISSUES.md`. Strategy research, if any, follows `docs/research/` pre-registration only.

## Main commands

```powershell
cd C:\Projects\EGX
streamlit run egx_dashboard.py
python data_downloader.py --data-folder ./data --limit 520 --period 2y
python daily_runner.py --data-folder ./data --capital 100000 --notify --download
python bot_handlers.py
```

Desktop dashboard: http://127.0.0.1:8501

## Mobile dashboard on the local network

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_mobile_dashboard.ps1
```

The script prints the laptop's current local IPv4 address and a URL such as `http://192.168.1.4:8501`. Open that URL from a phone connected to the same Wi-Fi or Ethernet network.

Security warning: mobile mode binds Streamlit to `0.0.0.0`, so other devices on the same local network may reach it. Use it only on a trusted private LAN. Do not expose, forward, or publish port 8501 on the Internet. The app does not add authentication.

Windows Task Scheduler: `EGX_Daily_Runner` at 14:45 Cairo, retried hourly until 19:45 (`--alert-after 19:30`). Recreate it with `powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1`.

Telegram Advisor Task Scheduler: `EGX_Telegram_Bot` starts at Windows sign-in. Recreate it with `powershell -ExecutionPolicy Bypass -File .\setup_telegram_bot_scheduler.ps1`.

Paper Trading campaign: 2026-10-04 through 2027-04-04, targeting at least 15 closed trades over six months.

This project provides technical analysis for paper trading only, not brokerage execution or final investment advice.
