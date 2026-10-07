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

# group (id or @username) → (name, measured history). Scan + history check 2026-10-07: entry in the buy zone within
# 3 sessions, exit at target 1 / stop / 30 sessions, 0.3% fees, Yahoo prices.
GROUPS = {
    -1002839995727: ("بورصجى", "21 صفقة مقفولة، 52% ربح، متوسط +0.3% للصفقة"),
    "mostafamagdy15": ("الأسهم النارية", "91 صفقة مقفولة، 47% ربح، متوسط +0.17% (2026 لوحدها −0.27%)"),
    "egystocksalerts": ("منبه أسهم البورصة", "60 صفقة مقفولة، 53% ربح، متوسط +0.33%"),
    "mohamed27927": ("صقر التوصيات", "5 صفقات بس، 60% ربح، متوسط +3.2% — عينة صغيرة جدًا"),
}
# الأسهم النارية writes Arabic short names, not codes. Verified against prices on the signal day (2026-10-07).
NAMES = {"اعمار": "EMFD", "ايجيترانس": "ETRS", "اسيك": "ASCM", "اسيك للتعدين": "ASCM", "قاهرة زيوت": "COSG",
         "الصعيد": "UEGC", "بنيان": "BONY", "اليكو": "LCSW", "ليسيكو": "LCSW", "راميدا": "RMDA", "الكابلات": "ELEC",
         "ابن سينا": "ISPH", "المنتجعات": "EGTS", "ام ام": "MTIE", "دايس": "DSCW", "الجيزة": "GGCC", "يونيفرسال": "UNIP",
         "اوراسكوم استثمار": "OIH", "لوتس": "LUTS", "السويدى": "SWDY", "اسباير": "ASPI", "شارم دريمز": "SDTI",
         "مدينة مصر": "MASR", "هيرميس": "HRHO", "بلتون": "BTFH", "راية خدمات": "RACC", "راية": "RAYA",
         "العبور استثمار": "OBRI", "مصر لصناعة الكيماويات": "EGCH", "مينا للاستثمار": "MENA", "سوديك": "OCDI",
         "جي بي اى": "GBCO", "جهينة": "JUFO", "عبور لاند": "OLFI", "كيما": "KIMA", "كونتكت": "CNFN", "مصر الجديدة": "HELI",
         "المتحدة إسكان": "UNIT", "ايبيكو": "PHAR", "برايم": "PRMH", "طلعت": "TMGH", "دلتا سكر": "SUGR",
         "الدلتا للسكر": "SUGR", "اموك": "AMOC", "ايه تي ليس": "ATLC", "ايه تى ليس": "ATLC", "أي تي ليس": "ATLC",
         "فورى": "FWRY", "ماكرو": "MCRO", "حاويات": "ALCN", "المصرف المتحد": "UBEE", "اودن": "ODIN",
         "كفر الزيات": "KZPC", "اى فينانس": "EFIH", "زهراء": "ZMID", "منصورة دواجن": "MPCO", "الشمس للاسكان": "ELSH"}

_AR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_N = r"(\d+(?:\.\d+)?)"
_LINE = re.compile(r"^(.*?)\s*شراء\s*(?:من)?\s*" + _N + r"\s*[–\-_]+\s*" + _N + r"\s*هدف\s*" + _N
                   + r"(?:\s*[–\-_]+\s*" + _N + r")?\s*استوب\s*" + _N)
_BUY, _TGT, _STOP = r"منطقة الشراء|شراء|شرا", r"مستهدف|الأهداف|أهداف|اهداف|الهدف|هدف", r"وقف|استوب|ستوب"


def _after(t: str, kw: str) -> Optional[re.Match]:
    return re.search("(?:" + kw + r")[^\d]{0,40}?" + _N + r"(?:[\s_\-–]*" + _N + ")?", t)


def parse(text: str) -> list[dict]:
    """Signals in one message ([] if none). ticker None = signal-like but not readable → forward raw."""
    t = text.translate(_AR)
    # one-line format, possibly several per message: "NAME شراء من a – b هدف c – d استوب e"
    lines = [m for m in (_LINE.search(x.strip()) for x in t.splitlines()) if m]
    if lines:
        return [{"ticker": NAMES.get(m.group(1).strip()), "name": m.group(1).strip(),
                 "lo": min(float(m.group(2)), float(m.group(3))), "hi": max(float(m.group(2)), float(m.group(3))),
                 "targets": [float(x) for x in (m.group(4), m.group(5)) if x], "sl": float(m.group(6))} for m in lines]
    if not (re.search(_BUY, t) and re.search(_TGT, t) and re.search(_STOP, t)):
        return []
    code, buy, sl = re.search(r"\b([A-Z]{3,5})\b", t), _after(t, _BUY), _after(t, _STOP)
    tgt = re.search("(?:" + _TGT + ")(.*?)(?:" + _STOP + ")", t, re.S)
    targets = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", tgt.group(1))] if tgt else []
    if not (code and buy and sl and targets):
        return [{"ticker": None}]
    lo, hi = float(buy.group(1)), float(buy.group(2) or buy.group(1))
    return [{"ticker": code.group(1), "name": "", "lo": min(lo, hi), "hi": max(lo, hi), "targets": targets,
             "sl": float(sl.group(1))}]


def message_for(group: str, history: str, sig: dict, raw: str) -> str:
    if not sig.get("lo"):
        return f"📣 <b>رسالة شبه إشارة من {html.escape(group)}</b> (ما اتقرتش أوتوماتيك)\n\n{html.escape(raw[:1500])}"
    hi, sl, t = sig["hi"], sig["sl"], sig["targets"]
    label = sig["ticker"] or "؟"
    if sig.get("name"):
        label = f"{html.escape(sig['name'])} ({label})"
    return (f"📣 <b>إشارة من {html.escape(group)}</b>\n"
            f"السهم: <b>{label}</b>\n"
            f"شراء: {sig['lo']:g} – {hi:g}\n"
            f"الأهداف: {' / '.join(f'{x:g}' for x in t)}\n"
            f"وقف: {sl:g}\n"
            f"من أعلى سعر شراء: مخاطرة {(hi - sl) / hi * 100:.1f}% | للهدف الأول {(t[0] - hi) / hi * 100:+.1f}%\n\n"
            f"ℹ️ سجل القناة: {history}\n⚠️ مش نصيحة استثمار — القرار والتنفيذ على Thndr ليك.")


# Record only, never forwarded: Ahmed already gets these directly. Scored later on the full record (signals + stops),
# not on the "target hit" messages alone.
RECORD_ONLY = {"egx_stock_analyzer_bot": "EGXBot"}


def store_raw(source: str, msg_id: int, date: str, raw: str) -> bool:
    with closing(sqlite3.connect(_db_path())) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS tg_raw (src TEXT, msg_id INTEGER, date TEXT, raw TEXT,
            PRIMARY KEY (src, msg_id))""")
        cur = con.execute("INSERT OR IGNORE INTO tg_raw VALUES (?, ?, ?, ?)", (source, msg_id, date, raw))
        con.commit()
        return bool(cur.rowcount)


def store(group: str, msg_id: int, idx: int, date: str, sig: dict, raw: str) -> bool:
    with closing(sqlite3.connect(_db_path())) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS tg_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, grp TEXT, msg_id INTEGER,
            idx INTEGER, date TEXT, ticker TEXT, name TEXT, lo REAL, hi REAL, targets TEXT, sl REAL, raw TEXT,
            UNIQUE (grp, msg_id, idx))""")
        cur = con.execute("INSERT OR IGNORE INTO tg_signals (grp, msg_id, idx, date, ticker, name, lo, hi, targets, sl, raw) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (group, msg_id, idx, date, sig.get("ticker"), sig.get("name"), sig.get("lo"), sig.get("hi"),
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
        signals = parse(raw)
        if not signals:
            return
        chat = await event.get_chat()
        key = event.chat_id if event.chat_id in GROUPS else getattr(chat, "username", None)
        group, history = GROUPS.get(key, (str(event.chat_id), "غير مقاس"))
        for idx, sig in enumerate(signals):
            if store(group, event.message.id, idx, event.message.date.isoformat(), sig, raw):  # once per signal
                send_telegram(message_for(group, history, sig, raw))
                LOGGER.info("forwarded %s %s", group, sig.get("ticker"))

    @client.on(events.NewMessage(chats=list(RECORD_ONLY), incoming=True))
    async def on_record(event) -> None:
        source = RECORD_ONLY[(await event.get_chat()).username]
        if store_raw(source, event.message.id, event.message.date.isoformat(), event.message.message or ""):
            LOGGER.info("recorded %s %s", source, event.message.id)

    client.start()  # uses the saved session; never prompts when tg_egx.session is valid
    async def backfill() -> None:  # anything received while the follower was down
        for username, source in RECORD_ONLY.items():
            async for m in client.iter_messages(username, limit=500):
                if m.message and not m.out:
                    store_raw(source, m.id, m.date.isoformat(), m.message)

    client.loop.run_until_complete(backfill())
    LOGGER.info("following %s", [g for g, _ in GROUPS.values()])
    client.run_until_disconnected()
    return 0


def _selftest() -> None:
    s = parse("الماليه الصناعيه EFIC\n\n8سبتمبر 2026\n\nشراء 200___208\n\nمستهدف220__240_260\n\nوقف الخساره إغلاق اسفل 191")
    assert s == [{"ticker": "EFIC", "name": "", "lo": 200.0, "hi": 208.0, "targets": [220.0, 240.0, 260.0], "sl": 191.0}], s
    m = parse("راميدا شراء من 5.40 – 5.48 هدف 5.70 – 5.80 استوب 5.28\nالكابلات شراء من 1.90 – 1.92 هدف 1.98 – 2.02 استوب 1.86")
    assert [x["ticker"] for x in m] == ["RMDA", "ELEC"] and m[0]["targets"] == [5.7, 5.8] and m[1]["sl"] == 1.86, m
    e = parse("ETEL المصرية للإتصالات\nشرا\n32.75-34.5\nأهداف\n37\n40\n43\nوقف الخسارة\n32")
    assert e == [{"ticker": "ETEL", "name": "", "lo": 32.75, "hi": 34.5, "targets": [37.0, 40.0, 43.0], "sl": 32.0}], e
    q = parse("📊COSG\nالقاهرة للزيوت والصابون\n📍 منطقة الشراء:\n1.70\n🎯 الأهداف:\n· هدف أول:1.90\n· هدف ثاني: 2.23\n🛑 وقف الخسارة :\nكسر 1.61")
    assert q[0]["ticker"] == "COSG" and q[0]["hi"] == 1.7 and q[0]["sl"] == 1.61 and q[0]["targets"][0] == 1.9, q
    assert parse("صباح الخير يا جماعة") == []
    assert parse("شراء ومستهدف ووقف من غير أرقام") == [{"ticker": None}]
    msg = message_for("الأسهم النارية", "x", m[0], "")
    assert "RMDA" in msg and "راميدا" in msg and "مش نصيحة" in msg
    print("tg_follower self-test OK")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _selftest()
        raise SystemExit(0)
    raise SystemExit(main())
