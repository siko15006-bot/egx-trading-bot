from __future__ import annotations
from egx_lists import UNIVERSE, filter_universe, recommendation_warning
from data_health import DataHealthError, require_daily_data

import asyncio
import difflib
import html
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import egx_4_mirrors_v3 as engine
from paper_trading import campaign_progress, load_paper_trades, performance_summary
from signal_engine import build_signals
from validate_tv_signals import normalize_ticker


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
LOGGER = logging.getLogger(__name__)
DISCLAIMER = "⚠️ تحليل فني تعليمي فقط، وليس توصية استثمارية. القرار النهائي مسؤوليتك."
MIRROR_NAMES = {
    "Trend": "الاتجاه",
    "Momentum": "الزخم",
    "Volume": "الحجم",
    "Volatility": "التذبذب",
}


# يقرأ مسارات المشروع ورأس المال من البيئة المحلية.
def _settings() -> tuple[str, str, Path, float]:
    load_dotenv(ENV_PATH, override=True)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    folder = Path(os.getenv("DATA_FOLDER", "./data"))
    data_folder = folder if folder.is_absolute() else BASE_DIR / folder
    capital = float(os.getenv("ACCOUNT_CAPITAL", "100000"))
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    return token, chat_id, data_folder, capital


# يمنع كشف بيانات المشروع لأي محادثة غير المسجلة في .env.
def _authorized(update: Update) -> bool:
    chat = update.effective_chat
    if chat is None:
        return False
    try:
        _, allowed_chat, _, _ = _settings()
    except RuntimeError:
        return False
    return str(chat.id) == allowed_chat


# يرسل رداً موحداً مع التنبيه الإلزامي.
async def _reply(update: Update, text: str) -> None:
    if update.effective_message is not None:
        await update.effective_message.reply_text(
            f"{text}\n\n{DISCLAIMER}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


# يتحقق من صلاحية المحادثة قبل تنفيذ أي تحليل.
async def _allow(update: Update) -> bool:
    if _authorized(update):
        return True
    await _reply(update, "⛔ هذه المحادثة غير مصرح لها باستخدام بيانات النظام.")
    return False


# يحمل ملفات OHLCV الحالية من المصدر نفسه المستخدم في Dashboard.
def _load_data() -> dict[str, pd.DataFrame]:
    _, _, data_folder, _ = _settings()
    if not data_folder.exists():
        raise FileNotFoundError(f"Data folder not found: {data_folder}")
    return require_daily_data(filter_universe(engine.load_data_map(data_folder)), expected_tickers=UNIVERSE)


# يعرض تاريخ آخر شمعة بتوقيت القاهرة.
def _as_of(frame: pd.DataFrame) -> str:
    stamp = frame.index[-1]
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Africa/Cairo")
    return stamp.strftime("%Y-%m-%d")


# يحسب ملخص حالة السوق من المرايا الفعلية لكل سهم.
def _status_message() -> str:
    data_map = _load_data()
    complete: list[str] = []
    scores: dict[int, int] = {score: 0 for score in range(5)}
    dates: list[str] = []
    for ticker, frame in data_map.items():
        calculated = engine.calculate_indicators(frame)
        result = engine.evaluate_4_mirrors(calculated, engine.SignalConfig())
        score = sum(bool(value) for value in result["mirrors"].values())
        scores[score] += 1
        if score == 4:
            complete.append(ticker)
        dates.append(_as_of(calculated))
    latest = max(dates, default="—")
    names = ", ".join(complete) if complete else "لا يوجد"
    distribution = " | ".join(f"{score}/4: {scores[score]}" for score in range(4, -1, -1))
    return (
        "📊 <b>حالة EGX الفنية</b>\n"
        f"آخر شمعة: {latest}\n"
        f"الأسهم المحللة: {len(data_map)}\n"
        f"إشارات 4/4: <b>{len(complete)}</b>\n"
        f"القائمة: {html.escape(names)}\n"
        f"التوزيع: {distribution}"
    )


# يبني تحليلاً فنياً لسهم واحد من آخر شمعة متاحة.
def _stock_message(raw_ticker: str) -> str:
    ticker = normalize_ticker(raw_ticker)
    data_map = _load_data()
    if ticker not in data_map:
        match = difflib.get_close_matches(ticker, data_map.keys(), n=1, cutoff=0.55)
        hint = f" هل تقصد {match[0]}؟" if match else ""
        return f"❌ لا توجد بيانات للسهم {html.escape(ticker or raw_ticker)}.{html.escape(hint)}"

    calculated = engine.calculate_indicators(data_map[ticker])
    screen_ok, _ = engine.passes_screener(calculated, engine.ScreenConfig())
    evaluation = engine.evaluate_4_mirrors(calculated, engine.SignalConfig())
    row = evaluation["row"]
    mirrors = evaluation["mirrors"]
    score = sum(bool(value) for value in mirrors.values())
    checks = "\n".join(
        f"{'✅' if value else '❌'} {MIRROR_NAMES.get(name, name)}"
        for name, value in mirrors.items()
    )
    lines = [
        f"📈 <b>{html.escape(ticker)}</b> — {_as_of(calculated)}",
        f"الحالة الفنية: <b>{html.escape(str(evaluation['signal']))}</b>",
        f"Screener: {'✅' if screen_ok else '❌'} | Mirrors: <b>{score}/4</b>",
        f"الإغلاق: {float(row['Close']):,.2f} EGP",
        f"RSI: {float(row['RSI']):.1f} | ADX: {float(row['ADX']):.1f}",
        f"ATR: {float(row['ATR']):,.2f} | ATR%: {float(row['ATR_Pct']):.2f}%",
        checks,
        html.escape(recommendation_warning(ticker)),
    ]
    _, _, _, capital = _settings()
    plan = engine.build_trade_plan(
        ticker,
        calculated,
        engine.SignalConfig(),
        engine.RiskConfig(capital=capital),
    )
    if plan is not None:
        lines.extend(
            [
                "<b>مستويات النموذج الفنية:</b>",
                f"Entry {plan.entry:,.2f} | SL {plan.stop_loss:,.2f} | TP {plan.take_profit:,.2f}",
                f"Shares {plan.shares:,} | Net R:R 1:{plan.rr_net:.2f}",
            ]
        )
    return "\n".join(lines)


# يبني قائمة إشارات اليوم من signal_engine الموحد.
def _signals_message() -> str:
    data_map = _load_data()
    _, _, _, capital = _settings()
    result = build_signals(
        data_map,
        engine.SignalConfig(),
        engine.RiskConfig(capital=capital),
    )
    lines = [f"🎯 <b>إشارات اليوم — {html.escape(result.as_of)}</b>"]
    if result.buy.empty:
        lines.append("🟢 BUY: لا يوجد")
    else:
        for row in result.buy.itertuples(index=False):
            lines.append(
                f"🟢 {html.escape(str(row.Ticker))}: Entry {row.Entry:,.2f} | "
                f"SL {row.SL:,.2f} | TP {row.TP:,.2f}\n"
                f"{html.escape(recommendation_warning(str(row.Ticker)))}"
            )
    if result.watch.empty:
        lines.append("⏸️ WATCH: لا يوجد")
    else:
        lines.append(f"⏸️ WATCH: {len(result.watch)}")
        for _, row in result.watch.head(10).iterrows():
            lines.append(
                f"• {html.escape(str(row['Ticker']))}: تفعيل {float(row['مستوى التنشيط']):,.2f} "
                f"(المسافة {float(row['المسافة %']):.2f}%)\n"
                f"{html.escape(recommendation_warning(str(row['Ticker'])))}"
            )
    return "\n".join(lines)


# يلخص الصفقات الورقية المفتوحة والأداء المغلق.
def _portfolio_message() -> str:
    trades = load_paper_trades()
    summary = performance_summary(trades)
    campaign = campaign_progress()
    opened = trades[trades["status"] == "OPEN"] if not trades.empty else pd.DataFrame()
    lines = [
        "📝 <b>Paper Trading Portfolio</b>",
        f"مفتوحة: {len(opened)} | مغلقة: {summary['trades']}",
        f"Win Rate: {summary['win_rate']:.1f}% | Net PnL: {summary['net_pnl']:+,.2f} EGP",
        "⚠️ PnL لا يشمل التوزيعات (أقل من الفعلي لو الصفقة عدّت تاريخ الاستحقاق).",
        f"تقدم الحملة: {campaign['closed_trades']}/{campaign['target_trades']} صفقة مغلقة",
    ]
    for row in opened.head(10).itertuples():
        lines.append(
            f"• {html.escape(str(row.ticker))}: Entry {row.entry:,.2f} | "
            f"SL {row.stop_loss:,.2f} | TP {row.take_profit:,.2f} | {int(row.shares):,} سهم"
        )
    if opened.empty:
        lines.append("لا توجد صفقات ورقية مفتوحة.")
    return "\n".join(lines)


# رسالة الترحيب.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allow(update):
        return
    await _reply(
        update,
        "👋 <b>EGX Technical Advisor</b>\n"
        "أحلل بيانات النظام الحالية وأعرض حالة المرايا والمستويات الفنية.\n"
        "استخدم /help لعرض الأوامر.",
    )


# قائمة الأوامر.
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allow(update):
        return
    await _reply(
        update,
        "<b>الأوامر المتاحة</b>\n"
        "/status — حالة السوق وعدد إشارات 4/4\n"
        "/check COMI — تحليل فني لسهم\n"
        "/signals — إشارات اليوم\n"
        "/portfolio — سجل الصفقات الورقية\n"
        "/help — هذه القائمة",
    )


# حالة السوق وعدد الأسهم المكتملة.
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allow(update):
        return
    await _run_and_reply(update, _status_message)


# تحليل سهم محدد بصيغة /check COMI.
async def check_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allow(update):
        return
    if not context.args:
        await _reply(update, "اكتب رمز السهم بعد الأمر، مثال: <code>/check COMI</code>")
        return
    await _run_and_reply(update, _stock_message, context.args[0])


# إشارات اليوم من المحرك الموحد.
async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allow(update):
        return
    await _run_and_reply(update, _signals_message)


# الصفقات الورقية الحالية.
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allow(update):
        return
    await _run_and_reply(update, _portfolio_message)


# ينفذ القراءة والحساب في thread مع رسالة خطأ آمنة.
async def _run_and_reply(update: Update, func: Callable[..., str], *args: Any) -> None:
    try:
        message = await asyncio.to_thread(func, *args)
    except DataHealthError as exc:
        LOGGER.warning("Data health blocked analysis: %s", exc.report)
        await _reply(update, html.escape(str(exc)))
        return
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        LOGGER.exception("Bot analysis failed")
        await _reply(update, f"❌ تعذر إكمال التحليل: {html.escape(str(exc))}")
        return
    await _reply(update, message)


# يحدد أقرب أمر أو رمز سهم من الرسالة الحرة.
def _text_intent(text: str, tickers: list[str]) -> tuple[str, str | None]:
    lowered = text.strip().lower()
    for token in re.findall(r"[A-Za-z]{2,8}(?:\.CA)?", text):
        ticker = normalize_ticker(token)
        if ticker in tickers:
            return "check", ticker
    keywords = {
        "status": ("حالة السوق", "السوق", "status", "مرايا"),
        "signals": ("اشارات", "إشارات", "فرص", "signals", "اليوم"),
        "portfolio": ("محفظة", "صفقات", "portfolio", "paper"),
        "help": ("مساعدة", "اوامر", "أوامر", "help"),
    }
    for intent, words in keywords.items():
        if any(word.lower() in lowered for word in words):
            return intent, None
    choices = [word for words in keywords.values() for word in words]
    match = difflib.get_close_matches(lowered, [word.lower() for word in choices], n=1, cutoff=0.55)
    if match:
        for intent, words in keywords.items():
            if match[0] in [word.lower() for word in words]:
                return intent, None
    return "help", None


# يرد على النص الحر باستخدام مطابقة بسيطة بلا نموذج يولد أرقاماً.
async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _allow(update):
        return
    text = update.effective_message.text if update.effective_message else ""
    tickers = list(UNIVERSE)
    intent, ticker = _text_intent(text, tickers)
    if intent == "check" and ticker:
        await _run_and_reply(update, _stock_message, ticker)
    elif intent == "status":
        await status(update, context)
    elif intent == "signals":
        await signals(update, context)
    elif intent == "portfolio":
        await portfolio(update, context)
    else:
        await help_command(update, context)


# يسجل الاستثناءات غير المتوقعة دون كشف تفاصيل حساسة للمستخدم.
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.exception("Unhandled Telegram bot error", exc_info=context.error)
    if isinstance(update, Update):
        await _reply(update, "❌ حدث خطأ غير متوقع. راجع سجل التشغيل.")


# يبني التطبيق ويسجل كل المعالجات.
def build_application(token: str) -> Application:
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("check", check_stock))
    application.add_handler(CommandHandler("signals", signals))
    application.add_handler(CommandHandler("portfolio", portfolio))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, free_text))
    application.add_error_handler(error_handler)
    return application


# فحص محلي لا يرسل رسائل ولا يبدأ polling.
def _smoke_test() -> None:
    try:
        data = _load_data()
    except DataHealthError as exc:
        assert exc.report["status"] == "DATA_UNAVAILABLE"
        print("BOT HANDLERS SMOKE TEST PASSED: stale data correctly blocked")
        return
    assert len(data) == len(UNIVERSE)
    assert _text_intent("حلل COMI", list(data)) == ("check", "COMI.CA")
    assert DISCLAIMER in f"x\n{DISCLAIMER}"
    stock = _stock_message("COMI")
    assert "COMI.CA" in stock and "Mirrors:" in stock and "ATR%:" in stock
    assert "إشارات 4/4" in _status_message()
    assert "Paper Trading" in _portfolio_message()
    print("BOT HANDLERS SMOKE TEST PASSED")


def main() -> int:
    log_path = BASE_DIR / "logs" / "telegram_advisor.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if "--smoke-test" in sys.argv:
        _smoke_test()
        return 0
    token, _, _, _ = _settings()
    LOGGER.info("Starting EGX Telegram advisor polling")
    build_application(token).run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
