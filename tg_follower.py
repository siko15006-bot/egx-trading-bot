"""Follow EGX signal groups on Telegram (as Ahmed, via tg_egx.session) and forward each signal to Ahmed's chat.

Ahmed executes on Thndr himself (no API). Every forwarded signal is also stored in `tg_signals` so each group can
be scored later. Not investment advice; groups are judged on their recorded results only.
Run: python tg_follower.py         (long-running; scheduled task EGX_TG_Follower)
     python tg_follower.py --test  (parser self-check, no network)
"""
from __future__ import annotations

import html
import logging
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from paper_trading import _db_path
from telegram_notifier import send_telegram

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")
LOGGER = logging.getLogger("tg_follower")

# group id → name. Only بورصجى posts structured signals (scan 2026-10-07: 35 in 14 months, 1 author).
GROUPS = {-1002839995727: "بورصجى"}
# Historical check 2026-10-07 (entry in buy zone ≤3 sessions, exit T1 / close below stop / 30 sessions, 0.3% fees).
HISTORY = "سجل الجروب (اتقاس 10-07): 21 صفقة مقفولة، 11 ربح، متوسط +0.3% للصفقة — يعني تقريبًا تعادل"

_AR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_NUM = r"(\d+(?:\.\d+)?)"


def parse(text: str) -> Optional[dict]:
    """Structured signal → dict, or None. Format: name CODE / شراء a___b / مستهدف t1_t2_t3 / وقف الخساره ... x."""
    t = text.translate(_AR)
    if not (re.search("شراء", t) and re.search("مستهدف", t) and re.search("وقف", t)):
        return None
    code = re.search(r"\b([A-Z]{3,5})\b", t)
    buy = re.search(r"شراء\s*" + _NUM + r"[\s_\-–]*" + _NUM + "?", t)
    tg = re.search(r"مستهدف[^\d]*([\d.\s_\-–]+)", t)
    sl = re.search(r"وقف[^\d]*" + _NUM, t)
    if not (code and buy and tg and sl):
        return {"ticker": None}  # signal-like but unparsed → forward raw
    lo, hi = float(buy.group(1)), float(buy.group(2) or buy.group(1))
    targets = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", tg.group(1))]
    return {"ticker": code.group(1), "lo": min(lo, hi), "hi": max(lo, hi), "targets": targets, "sl": float(sl.group(1))}


def message_for(group: str, sig: dict, raw: str) -> str:
    if not sig.get("ticker"):
        return f"📣 <b>رسالة شبه إشارة من {html.escape(group)}</b> (ما اتقرتش أوتوماتيك)\n\n{html.escape(raw[:1500])}"
    hi, sl, t = sig["hi"], sig["sl"], sig["targets"]
    risk = (hi - sl) / hi * 100
    reward = (t[0] - hi) / hi * 100 if t else 0.0
    return (f"📣 <b>إشارة من {html.escape(group)}</b>\n"
            f"السهم: <b>{sig['ticker']}</b>\n"
            f"شراء: {sig['lo']:g} – {hi:g}\n"
            f"الأهداف: {' / '.join(f'{x:g}' for x in t)}\n"
            f"وقف: إغلاق أسفل {sl:g}\n"
            f"من أعلى سعر شراء: مخاطرة {risk:.1f}% | للهدف الأول {reward:+.1f}%\n\n"
            f"ℹ️ {HISTORY}\n⚠️ مش نصيحة استثمار — القرار والتنفيذ على Thndr ليك.")


def store(group: str, msg_id: int, date: str, sig: dict, raw: str) -> bool:
    with closing(sqlite3.connect(_db_path())) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS tg_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, grp TEXT, msg_id INTEGER,
            date TEXT, ticker TEXT, lo REAL, hi REAL, targets TEXT, sl REAL, raw TEXT, UNIQUE (grp, msg_id))""")
        cur = con.execute("INSERT OR IGNORE INTO tg_signals (grp, msg_id, date, ticker, lo, hi, targets, sl, raw) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (group, msg_id, date, sig.get("ticker"), sig.get("lo"), sig.get("hi"),
                           "_".join(f"{x:g}" for x in sig.get("targets", [])), sig.get("sl"), raw))
        con.commit()
        return bool(cur.rowcount)


def main() -> int:
    from telethon import TelegramClient, events

    logging.basicConfig(filename=HERE / "logs" / "tg_follower.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    client = TelegramClient(str(HERE / "tg_egx"), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])

    @client.on(events.NewMessage(chats=list(GROUPS)))
    async def on_message(event) -> None:
        raw = event.message.message or ""
        sig = parse(raw)
        if sig is None:
            return
        group = GROUPS.get(event.chat_id, str(event.chat_id))
        if store(group, event.message.id, event.message.date.isoformat(), sig, raw):  # once per message
            send_telegram(message_for(group, sig, raw))
            LOGGER.info("forwarded %s %s", group, sig.get("ticker"))

    client.start()  # uses the saved session; never prompts when tg_egx.session is valid
    LOGGER.info("following %s", list(GROUPS.values()))
    client.run_until_disconnected()
    return 0


def _selftest() -> None:
    s = parse("الماليه الصناعيه EFIC\n\n8سبتمبر 2026\n\nشراء 200___208\n\nمستهدف220__240_260\n\nوقف الخساره إغلاق اسفل 191")
    assert s == {"ticker": "EFIC", "lo": 200.0, "hi": 208.0, "targets": [220.0, 240.0, 260.0], "sl": 191.0}, s
    assert parse("صباح الخير يا جماعة") is None
    assert parse("شراء ومستهدف ووقف من غير أرقام") == {"ticker": None}
    assert "EFIC" in message_for("بورصجى", s, "") and "مش نصيحة" in message_for("بورصجى", s, "")
    print("tg_follower self-test OK")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _selftest()
        raise SystemExit(0)
    raise SystemExit(main())
