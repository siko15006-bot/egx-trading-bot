from __future__ import annotations

import hmac
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from typing import Any

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request

from telegram_notifier import send_signal_alert
from validate_tv_signals import init_db, log_alert, validate_signal


load_dotenv()
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)
APP_STARTED = time.monotonic()
app = Flask(__name__)


# يعيد مسار قاعدة البيانات الحالي من البيئة.
def _db_path() -> str:
    return os.getenv("DB_PATH", "egx_signals.db")


# ينشئ اتصال SQLite يعيد الصفوف كقواميس.
def _connect() -> sqlite3.Connection:
    init_db(_db_path())
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    return connection


# يدمج خطة Python وبيانات المؤشرات في تنبيه تيليجرام.
def _telegram_payload(alert: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    payload = dict(alert)
    payload.update(validation.get("trade_plan", {}))
    payload["adx"] = validation.get("adx", alert.get("adx", 0))
    payload["atr_pct"] = validation.get("atr_pct", alert.get("atr_pct", 0))
    return payload


# يستقبل Webhook TradingView ويتحقق منه ويسجله.
@app.post("/tv-webhook")
def tv_webhook() -> tuple[Response, int] | Response:
    expected_secret = os.getenv("WEBHOOK_SECRET", "")
    if not expected_secret:
        LOGGER.error("WEBHOOK_SECRET is not configured")
        return jsonify({"status": "error", "message": "server secret is not configured"}), 500
    supplied_secret = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(supplied_secret, expected_secret):
        LOGGER.warning("Rejected webhook with invalid secret")
        return jsonify({"status": "error", "message": "unauthorized"}), 401

    alert = request.get_json(silent=True)
    if not isinstance(alert, dict) or not alert.get("ticker") or not alert.get("action"):
        return jsonify({"status": "error", "message": "valid JSON with ticker and action is required"}), 400

    try:
        validation = validate_signal(alert)
        log_alert(_db_path(), alert, validation)
        telegram = "not_sent"
        if validation["status"] == "CONFIRMED":
            # the alert is already stored: a notifier failure must not turn the webhook into a 500
            try:
                result = send_signal_alert(_telegram_payload(alert, validation))
                telegram = "dry_run" if result.get("dry_run") else "sent"
            except Exception:
                LOGGER.exception("Telegram notification failed for %s (alert stored)", alert["ticker"])
                telegram = "failed"
        LOGGER.info("Webhook processed for %s: %s (telegram=%s)", alert["ticker"], validation["status"], telegram)
        return jsonify({"status": "ok", "validated": validation["status"], "telegram": telegram})
    except Exception:
        LOGGER.exception("Webhook processing failed")
        return jsonify({"status": "error", "message": "internal server error"}), 500


# يعرض صحة الخدمة وعدد السجلات ومدة التشغيل.
@app.get("/health")
def health() -> Response:
    with closing(_connect()) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM tv_alerts").fetchone()[0])
    return jsonify({"status": "ok", "db_count": count, "uptime": round(time.monotonic() - APP_STARTED, 2)})


# يعرض آخر عشرين تنبيهاً بترتيب الأحدث.
@app.get("/recent")
def recent() -> Response:
    with closing(_connect()) as connection:
        rows = connection.execute("SELECT * FROM tv_alerts ORDER BY id DESC LIMIT 20").fetchall()
    return jsonify([dict(row) for row in rows])


# يعرض إحصاءات حالات التحقق المسجلة.
@app.get("/stats")
def stats() -> Response:
    with closing(_connect()) as connection:
        total = int(connection.execute("SELECT COUNT(*) FROM tv_alerts").fetchone()[0])
        counts = {
            row["status"].lower(): int(row["count"])
            for row in connection.execute("SELECT status, COUNT(*) AS count FROM tv_alerts GROUP BY status")
        }
    return jsonify(
        {
            "total": total,
            "confirmed": counts.get("confirmed", 0),
            "mismatch": counts.get("mismatch", 0),
            "reject": counts.get("reject", 0),
            "win_rate_placeholder": None,
        }
    )


# يشغل اختبار تحميل بسيط قبل بدء الخادم.
def _smoke_test() -> None:
    assert callable(validate_signal)
    assert callable(send_signal_alert)
    LOGGER.info("Webhook modules loaded successfully")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    init_db(os.getenv("DB_PATH", "egx_signals.db"))
    from telegram_notifier import send_telegram
    from validate_tv_signals import init_db as v_init

    _smoke_test()
    print("✅ ALL MODULES LOADED")
    print("📡 Server: http://localhost:5000")
    print("🔍 Health: http://localhost:5000/health")
    print("📊 Stats:  http://localhost:5000/stats")
    # HOST=127.0.0.1 for local testing (not reachable from the LAN); default unchanged for Railway/Docker
    app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "5000")))
