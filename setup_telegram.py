from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv, set_key

from telegram_notifier import is_configured, send_telegram


ENV_PATH = Path(__file__).with_name(".env")
LOGGER = logging.getLogger(__name__)
PLACEHOLDERS = {"", "your_token", "your_chat_id"}


# يقرأ ملف البيئة المحلي دون عرض القيم السرية.
def _settings() -> tuple[str, str]:
    load_dotenv(ENV_PATH)
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


# يطبع خطوات إنشاء وضبط البوت عند غياب التوكن.
def _print_token_steps() -> None:
    print("لم يتم ضبط TELEGRAM_BOT_TOKEN بعد.")
    print("1. افتح @BotFather في Telegram.")
    print("2. استخدم /mybots واختر البوت، أو /newbot لإنشاء بوت جديد.")
    print("3. انسخ API Token وضعه في ملف .env:")
    print("   TELEGRAM_BOT_TOKEN=ضع_التوكن_هنا")
    print("4. افتح البوت واضغط Start أو أرسل /start.")
    print("5. شغّل هذا السكربت مرة أخرى لاكتشاف Chat ID واختبار الإرسال.")


# يتحقق من صلاحية التوكن عبر Telegram getMe API.
def verify_token(token: str) -> dict[str, Any]:
    response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Telegram rejected the token"))
    return dict(payload["result"])


# يعرض المحادثات الحديثة لمساعدة المستخدم في اختيار Chat ID.
def discover_chats(token: str) -> list[dict[str, Any]]:
    response = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
    response.raise_for_status()
    payload = response.json()
    chats: dict[str, dict[str, Any]] = {}
    for update in payload.get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        if "id" in chat:
            chats[str(chat["id"])] = chat
    return list(chats.values())


# يحفظ Chat ID المكتشف في .env ويحدّث البيئة الحالية.
def save_chat_id(chat_id: int | str) -> None:
    value = str(chat_id)
    set_key(ENV_PATH, "TELEGRAM_CHAT_ID", value, quote_mode="never")
    os.environ["TELEGRAM_CHAT_ID"] = value


# ينفذ التحقق الكامل ويرسل رسالة اختبار عند اكتمال الإعداد.
def main() -> int:
    if not ENV_PATH.exists():
        print(f"ملف البيئة غير موجود: {ENV_PATH}")
        return 1

    token, chat_id = _settings()
    if token in PLACEHOLDERS:
        _print_token_steps()
        return 1

    try:
        bot = verify_token(token)
        print(f"✅ التوكن صالح. البوت: @{bot.get('username', 'unknown')}")
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        LOGGER.error("فشل التحقق من التوكن: %s", exc)
        print("❌ التوكن غير صالح أو تعذر الاتصال بـ Telegram. راجع TELEGRAM_BOT_TOKEN.")
        return 1

    if chat_id in PLACEHOLDERS:
        print("TELEGRAM_CHAT_ID غير مضبوط.")
        try:
            chats = discover_chats(token)
        except (requests.RequestException, ValueError) as exc:
            LOGGER.error("تعذر قراءة getUpdates: %s", exc)
            chats = []
        if chats:
            print("المحادثات التي وجدها البوت:")
            for chat in chats:
                name = chat.get("title") or chat.get("username") or chat.get("first_name") or "Unknown"
                print(f"- {name}: {chat['id']}")
            private_chats = [chat for chat in chats if chat.get("type") == "private"]
            selected = (private_chats or chats)[-1]
            save_chat_id(selected["id"])
            chat_id = str(selected["id"])
            print(f"✅ تم حفظ TELEGRAM_CHAT_ID تلقائياً للمحادثة: {selected.get('first_name') or selected.get('username') or selected.get('title') or 'Unknown'}")
        else:
            print("أرسل /start إلى البوت أولاً، ثم شغّل السكربت مرة أخرى.")
            return 1

    if not is_configured():
        print("❌ إعدادات Telegram غير مكتملة.")
        return 1

    try:
        result = send_telegram("✅ EGX Trading System متصل بنجاح مع Telegram.")
    except (requests.RequestException, RuntimeError) as exc:
        LOGGER.error("فشل إرسال رسالة الاختبار: %s", exc)
        print("❌ التوكن صالح لكن إرسال الرسالة فشل. راجع TELEGRAM_CHAT_ID وصلاحية البوت.")
        return 1

    if result.get("dry_run"):
        print("⚠️ Mock Mode ما زال فعالاً؛ راجع قيم .env.")
        return 1
    print("✅ تم إرسال رسالة الاختبار. إعداد Telegram مكتمل.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
