from __future__ import annotations

import html
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


LOGGER = logging.getLogger(__name__)
CAIRO_TZ = ZoneInfo("Africa/Cairo")
ENV_PATH = Path(__file__).with_name(".env")


# يقرأ إعدادات تيليجرام من البيئة دون تضمين أسرار في الكود.
def read_env() -> tuple[str, str]:
    load_dotenv(ENV_PATH)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    return token, chat_id


_PLACEHOLDERS = {"", "your_token", "your_chat_id"}   # values shipped in .env.example


# هل تيليجرام مُعدّ فعلاً؟ (توكن ومعرّف محادثة حقيقيين، مش القيم الافتراضية من .env.example)
def is_configured() -> bool:
    load_dotenv(ENV_PATH)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return token not in _PLACEHOLDERS and chat_id not in _PLACEHOLDERS


# يرسل رسالة مع ثلاث محاولات إعادة بعد المحاولة الأولى.
# Mock Mode: بدون توكن حقيقي تُسجَّل الرسالة كـ TELEGRAM DRY-RUN بدل الإرسال (لا crash للـwebhook أو daily runner).
def send_telegram(message: str, parse_mode: str = "HTML") -> dict[str, Any]:
    if not is_configured():
        LOGGER.warning("TELEGRAM DRY-RUN (no TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID configured): %s", message.replace("\n", " | "))
        return {"ok": True, "dry_run": True}
    token, chat_id = read_env()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": parse_mode}
    last_error: Exception | None = None

    for attempt in range(4):
        try:
            LOGGER.info("Sending Telegram message, attempt %d", attempt + 1)
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            result = response.json()
            if not result.get("ok", False):
                raise RuntimeError(f"Telegram rejected request: {result.get('description', 'unknown error')}")
            LOGGER.info("Telegram message sent successfully")
            return result
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            LOGGER.warning("Telegram send failed on attempt %d: error=%s http_status=%s",
                           attempt + 1, type(exc).__name__,
                           getattr(getattr(exc, "response", None), "status_code", None))
            if attempt < 3:
                time.sleep(2**attempt)

    # استثناء requests قد يحتوي رابطاً بالتوكن؛ لا نضعه في السجل أو traceback.
    raise RuntimeError("Telegram delivery failed after retries; see sanitized HTTP status") from None


# يحول الوقت الوارد إلى توقيت القاهرة للعرض.
def _cairo_timestamp(value: Any) -> str:
    if value is None or value == "":
        return datetime.now(CAIRO_TZ).strftime("%Y-%m-%d %H:%M:%S")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CAIRO_TZ)
        return parsed.astimezone(CAIRO_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return html.escape(str(value))


# يبني تنبيه شراء منسقاً ويرسله إلى تيليجرام.
def send_signal_alert(alert: dict[str, Any]) -> dict[str, Any]:
    ticker = html.escape(str(alert.get("ticker", "UNKNOWN")))
    message = (
        "🚀 <b>إشارة شراء جديدة</b>\n"
        f"📊 السهم: <b>{ticker}</b>\n"
        f"💰 الدخول: {float(alert.get('entry', alert.get('price', 0))):,.3f} EGP\n"
        f"🛑 وقف الخسارة: {float(alert.get('sl', 0)):,.3f} EGP\n"
        f"🎯 الهدف: {float(alert.get('tp', 0)):,.3f} EGP\n"
        f"📈 R:R = 1:{float(alert.get('rr', 0)):.2f}\n"
        f"📊 ADX: {float(alert.get('adx', 0)):.2f} | ATR%: {float(alert.get('atr_pct', 0)):.2f}\n"
        f"⏰ {_cairo_timestamp(alert.get('timestamp'))} (Cairo)"
    )
    return send_telegram(message)


# يفحص تحميل الوحدة دون إجراء إرسال حقيقي.
def _smoke_test() -> None:
    assert _cairo_timestamp("2026-10-04T12:00:00+00:00").startswith("2026-10-04")
    if not is_configured():
        assert send_telegram("Telegram mock smoke test").get("dry_run") is True
    LOGGER.info("telegram_notifier smoke test passed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _smoke_test()
