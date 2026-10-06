from __future__ import annotations
from egx_lists import UNIVERSE, filter_universe, recommendation_warning

import argparse
import json
import hashlib
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from analytics_engine import (
    compute_stats,
    detect_patterns,
    evaluate_pending_alerts,
    export_analytics_report,
    load_alerts,
    load_outcomes,
)
from data_downloader import download_universe
from egx_4_mirrors_v3 import RiskConfig, ScreenConfig, SignalConfig, load_data_map, scan_universe
from telegram_notifier import send_telegram
from data_health import DataHealthError, assess_daily_data, health_message
from signal_engine import build_signals
from validate_tv_signals import init_db
import auto_sim


BASE_DIR = Path(__file__).resolve().parent
CAIRO_TZ = ZoneInfo("Africa/Cairo")
LOGGER = logging.getLogger(__name__)


# يحل المسارات النسبية من مجلد السكربت لتوافق Task Scheduler.
def _resolve(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else BASE_DIR / candidate


# يجهز تسجيل التشغيل اليومي إلى ملف والشاشة.
def _configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )


# ينشئ جدول التقارير اليومية ويعيد رموز اليوم المسجلة سابقاً.
def _reported_tickers(db_path: Path, report_date: str) -> set[str]:
    init_db(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_reports (
                report_date TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                report_path TEXT NOT NULL,
                buy_count INTEGER NOT NULL,
                tickers_json TEXT NOT NULL,
                stats_json TEXT NOT NULL,
                patterns_json TEXT NOT NULL
            )
            """
        )
        row = connection.execute(
            "SELECT tickers_json FROM daily_reports WHERE report_date = ?", (report_date,)
        ).fetchone()
        connection.commit()
    return set(json.loads(row[0])) if row else set()


# يخزن ملخص التقرير اليومي في قاعدة البيانات.
def _store_report(
    db_path: Path,
    report_date: str,
    report_path: Path,
    tickers: list[str],
    stats: dict[str, Any],
    patterns: list[dict[str, Any]],
) -> None:
    serializable_stats = {
        key: None if isinstance(value, float) and not pd.notna(value) else value
        for key, value in stats.items()
    }
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            INSERT INTO daily_reports (
                report_date, generated_at, report_path, buy_count,
                tickers_json, stats_json, patterns_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_date) DO UPDATE SET
                generated_at=excluded.generated_at,
                report_path=excluded.report_path,
                buy_count=excluded.buy_count,
                tickers_json=excluded.tickers_json,
                stats_json=excluded.stats_json,
                patterns_json=excluded.patterns_json
            """,
            (
                report_date,
                datetime.now(CAIRO_TZ).isoformat(),
                str(report_path),
                len(tickers),
                json.dumps(tickers, ensure_ascii=False),
                json.dumps(serializable_stats, ensure_ascii=False, default=str),
                json.dumps(patterns, ensure_ascii=False, default=str),
            ),
        )
        connection.commit()
    LOGGER.info("Daily report stored in SQLite")


# يبني رسالة ملخص التقرير اليومي.
def _daily_message(report_date: str, tickers: list[str], stats: dict[str, Any], *, as_of: str = "", buy_count: int = 0, watch_count: int = 0) -> str:
    symbols = ", ".join(ticker.replace(".CA", "") for ticker in tickers) or "لا توجد"
    profit_factor = stats["profit_factor"]
    pf_text = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    return (
        f"📊 <b>تقرير EGX اليومي - {report_date}</b>\n"
        f"آخر شمعة مكتملة: {as_of}\n"
        f"BUY (محرك إشارات اليوم): {buy_count} | WATCH: {watch_count}\n"
        f"✅ إشارات جديدة: {len(tickers)}\n"
        f"🎯 قائمة: {symbols}\n"
        f"📈 Win Rate (30 يوم): {stats['win_rate']:.1f}%\n"
        f"💰 Profit Factor: {pf_text}\n"
        + "\n".join(f"{ticker}: {recommendation_warning(ticker)}" for ticker in tickers)
    )


def _write_health(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {**report, "checked_at": datetime.now(CAIRO_TZ).isoformat()}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _notify_once(report_date: str, message: str) -> str:
    # سجل الإرسال منفصل عن التقرير؛ الإرسال الفاشل لا يستهلك محاولة اليوم.
    path = BASE_DIR / "logs" / f"daily_delivery_{report_date}.json"
    sent = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    key = hashlib.sha256(message.encode("utf-8")).hexdigest()
    if key in sent:
        LOGGER.info("Daily Telegram delivery already confirmed for this payload")
        return "already_sent"
    result = send_telegram(message)
    if result.get("dry_run") or not result.get("ok"):
        raise RuntimeError("Telegram delivery not confirmed; success marker not written")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(sent + [key]), encoding="utf-8")
    os.replace(temporary, path)
    return "sent"


def _now() -> datetime:
    return datetime.now(CAIRO_TZ)


# Retry mode: Task Scheduler re-runs hourly; a later run exits early once today's report is stored.
def _already_succeeded(db_path: Path, report_date: str) -> bool:
    if not db_path.exists():
        return False
    with closing(sqlite3.connect(db_path)) as connection:
        try:
            return connection.execute(
                "SELECT 1 FROM daily_reports WHERE report_date = ?", (report_date,)
            ).fetchone() is not None
        except sqlite3.OperationalError:  # table not created yet
            return False


# يقرأ كل ملفات CSV المتاحة دون فشل عند المجلد الفارغ.
def _load_universe(data_folder: Path) -> dict[str, pd.DataFrame]:
    data_folder.mkdir(parents=True, exist_ok=True)
    if not any(data_folder.glob("*.csv")):
        LOGGER.warning("No CSV files found in %s", data_folder)
        return {}
    return filter_universe(load_data_map(data_folder))


# ينفذ دورة EGX اليومية كاملة ويعيد كود الخروج.
def run_daily(args: argparse.Namespace) -> int:
    started = time.monotonic()
    now = _now()
    report_date = now.strftime("%Y%m%d")
    data_folder = _resolve(args.data_folder)
    db_path = _resolve(args.db_path)
    os.environ["DB_PATH"] = str(db_path)
    os.environ["DATA_FOLDER"] = str(data_folder)
    _configure_logging(BASE_DIR / "logs" / f"daily_{report_date}.log")
    LOGGER.info("EGX daily run started")
    alert_after = getattr(args, "alert_after", None)  # None = old behaviour: alert on every failed run
    if alert_after is not None and not args.dry_run and _already_succeeded(db_path, report_date):
        LOGGER.info("Retry skipped: daily report for %s already stored", report_date)
        return 0
    health_path = _resolve(getattr(args, "health_file", "logs/bot_health_latest.json"))
    health: dict[str, Any] = {"status": "RUNNING"}
    _write_health(health_path, health)

    try:
        if args.download:
            try:
                downloads = download_universe(data_folder)
                LOGGER.info("Download responses accepted for %d tickers; validating complete universe", len(downloads))
            except Exception:
                LOGGER.exception("Market data download failed; cached files must pass freshness validation")
        data_map = _load_universe(data_folder)
        data_map, health = assess_daily_data(data_map, expected_tickers=UNIVERSE)
        _write_health(health_path, health)
        LOGGER.info("Data health: status=%s expected=%s latest=%s fresh=%s/%s",
                    health["status"], health["expected_session"], health["latest_session"], health["fresh"], health["required"])
        if health["status"] != "DATA_OK":
            raise DataHealthError(health)
        if getattr(args, "health_only", False):
            return 0
        signals = scan_universe(
            data_map,
            ScreenConfig(),
            SignalConfig(),
            RiskConfig(capital=args.capital),
        )
        unified = build_signals(data_map, SignalConfig(), RiskConfig(capital=args.capital))
        health["scanner_status_counts"] = signals["Status"].value_counts().to_dict() if not signals.empty else {}
        LOGGER.info("Unified signals: BUY=%d WATCH=%d SELL=%d; as_of=%s",
                    len(unified.buy), len(unified.watch), len(unified.sell), unified.as_of)
        if args.dry_run:   # بيكتب في alert_outcomes → ممنوع في dry-run
            LOGGER.info("Dry run: pending-alert outcome evaluation skipped (it writes alert_outcomes)")
        else:
            evaluate_pending_alerts(data_folder, lookback_days=30)
        alerts = load_alerts(30)
        outcomes = load_outcomes(30)
        stats = compute_stats(alerts, outcomes)
        patterns = detect_patterns(outcomes)

        auto_line = ""
        if not args.dry_run:   # auto-sim writes auto_sim_trades; a failure here must not block the daily report
            try:
                sim = auto_sim.run(data_map, signals, RiskConfig(capital=args.capital), db_path)
                LOGGER.info("Auto-sim: closed=%d opened=%s as_of=%s", sim["closed"], sim["opened"], sim["as_of"])
                auto_line = "\n\n" + auto_sim.summary_line(db_path)
            except Exception:
                LOGGER.exception("Auto-sim step failed")
        buy_tickers = sorted(signals.loc[signals["Status"] == "BUY", "Ticker"].astype(str).tolist()) if not signals.empty else []
        previous = set() if args.dry_run else _reported_tickers(db_path, report_date)   # _reported_tickers بيعمل CREATE + commit
        new_tickers = sorted(set(buy_tickers) - previous)
        report_path = BASE_DIR / "reports" / f"daily_{report_date}.xlsx"
        export_analytics_report(report_path)   # ملف Excel محلي (قراءة من DB بس) — بيتولد في dry-run كمان
        if not args.dry_run:
            if args.notify and not args.no_telegram:
                health["telegram_delivery"] = _notify_once(
                    report_date, _daily_message(now.strftime("%Y-%m-%d"), new_tickers, stats,
                                                as_of=unified.as_of, buy_count=len(unified.buy), watch_count=len(unified.watch)) + auto_line,
                )
            _store_report(db_path, report_date, report_path, buy_tickers, stats, patterns)
        else:
            LOGGER.info("Dry run: database summary and Telegram send skipped (report written: %s)", report_path)

        LOGGER.info(
            "EGX daily run completed: stocks=%d buys=%d new=%d elapsed=%.2fs",
            len(data_map),
            len(buy_tickers),
            len(new_tickers),
            time.monotonic() - started,
        )
        health.update(status="SUCCESS", buy=len(unified.buy), watch=len(unified.watch))
        _write_health(health_path, health)
        return 0
    except DataHealthError as exc:
        LOGGER.error("Analysis blocked by data health: %s", exc.report)
        final_attempt = alert_after is None or now.time() >= alert_after
        if alert_after is not None:
            health["retry_exhausted"] = final_attempt
            if final_attempt:
                LOGGER.error("retry_exhausted=True: data still not fresh at %s; sending one alert", now.strftime("%H:%M"))
            else:
                LOGGER.warning("Data not fresh yet; Telegram alert deferred until the %s retry", alert_after.strftime("%H:%M"))
        try:
            if final_attempt and args.notify and not args.no_telegram and not args.dry_run:
                health["telegram_delivery"] = _notify_once(
                    report_date, f"EGX bot health - {now:%Y-%m-%d}\n{health_message(exc.report)}",
                )
        except Exception:
            LOGGER.exception("Data-health Telegram alert delivery failed")
            health["telegram_delivery"] = "failed"
        _write_health(health_path, health)
        return 2
    except Exception:
        LOGGER.exception("EGX daily run failed after %.2fs", time.monotonic() - started)
        health["status"] = "RUN_ERROR"
        _write_health(health_path, health)
        return 1


# يقرأ معاملات سطر الأوامر.
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the EGX daily scan and analytics workflow")
    parser.add_argument("--data-folder", default="./data")
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--db-path", default=os.getenv("DB_PATH", "egx_signals.db"))
    telegram = parser.add_mutually_exclusive_group()
    telegram.add_argument("--notify", action="store_true", help="Send daily heartbeat or a data-health failure alert")
    telegram.add_argument("--no-telegram", action="store_true", help="Disable Telegram delivery")
    parser.add_argument("--download", action="store_true", help="Refresh Yahoo Finance CSV files before scanning")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--health-only", action="store_true", help="Validate completed daily data without DB/report writes")
    parser.add_argument("--health-file", default="logs/bot_health_latest.json")
    parser.add_argument("--alert-after", type=lambda s: datetime.strptime(s, "%H:%M").time(), default=None,
                        help="Retry mode (HH:MM, Cairo): skip if today's report exists; send the data-health alert only from this time")
    return parser.parse_args()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(BASE_DIR / ".env")
    print("✅ Daily runner ready")
    raise SystemExit(run_daily(_parse_args()))
