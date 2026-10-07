"""اختبار الإغلاق: Daily Runner (--dry-run) + TV Validator (صيغ التيكر، 5 سيناريوهات، DB) + Webhook كامل.
التشغيل: python test_closure.py
- egx_signals.db الحقيقي: بيتحسب sha256 + عدد صفوف كل جدول قبل/بعد تشغيلات الـdry-run ولازم يفضل زي ما هو.
- سيناريوهات التحقق والـWebhook بتكتب في DB مؤقت (مش الحقيقي)، وتيليجرام بدون توكن → DRY-RUN، والسيرفر على 127.0.0.1 بس.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import warnings
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pandas as pd  # noqa: E402
import egx_4_mirrors_v3 as eng  # noqa: E402
import validate_tv_signals as tv  # noqa: E402

LOG = HERE / "logs" / f"closure_test_{datetime.now():%Y%m%d}.log"
REAL_DB = HERE / "egx_signals.db"
results: list[tuple[str, bool, str]] = []
CLEAN_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [TEST] {'PASS' if ok else 'FAIL'} {name} {detail}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def db_snapshot(path: Path) -> tuple[str, dict[str, int]]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return digest, {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def daily_runner_tests() -> None:
    today = datetime.now(ZoneInfo("Africa/Cairo")).strftime("%Y%m%d")
    report, log_file = HERE / "reports" / f"daily_{today}.xlsx", HERE / "logs" / f"daily_{today}.log"
    before = db_snapshot(REAL_DB)
    with tempfile.TemporaryDirectory() as empty:
        # The session is pinned to the folder's own last candle (EGX_EXPECTED_SESSION), so the result does not depend on
        # the wall clock or on Yahoo having published today's bar. data/ must complete; the other two must be blocked by
        # the data-health gate (exit 2): data_2022_2023 holds 9 of the 90 required tickers, the empty folder none.
        for label, folder, expect_exit in (("data", "./data", 0), ("data_2022_2023", "./data_2022_2023", 2), ("empty folder", empty, 2)):
            csvs = sorted((HERE / folder if not Path(folder).is_absolute() else Path(folder)).glob("*.csv"))
            last = max((pd.read_csv(f, usecols=["Date"])["Date"].iloc[-1][:10] for f in csvs), default="2026-10-01")
            start = time.time()
            log_size = log_file.stat().st_size if log_file.exists() else 0
            proc = subprocess.run([sys.executable, "-W", "ignore", "daily_runner.py", "--data-folder", folder, "--capital", "100000",
                                   "--no-telegram", "--dry-run"], cwd=HERE, env={**CLEAN_ENV, "EGX_EXPECTED_SESSION": last},
                                  capture_output=True, text=True, encoding="utf-8", timeout=900)
            # slice bytes, not text: read_text turns CRLF into LF, so a byte offset would skip the new lines on Windows
            new_log = log_file.read_bytes()[log_size:].decode("utf-8", errors="replace") if log_file.exists() else ""
            done = next((ln for ln in new_log.splitlines() if "EGX daily run completed" in ln), "")
            stocks = int(done.split("stocks=")[1].split()[0]) if done else -1
            if expect_exit == 0:
                ok = (proc.returncode == 0 and stocks == len(csvs) and report.exists() and report.stat().st_mtime >= start
                      and "Telegram send skipped" in new_log and "outcome evaluation skipped" in new_log)
            else:
                ok = proc.returncode == 2 and "Analysis blocked by data health" in new_log + proc.stderr
            check(f"daily_runner --dry-run [{label}] (session pinned to {last})", ok,
                  f"exit={proc.returncode} stocks={stocks} completed='{done[-90:]}' stderr_tail={proc.stderr[-160:]!r}")
    after = db_snapshot(REAL_DB)
    check("egx_signals.db unchanged by dry-runs (sha256 + row counts)", before == after, f"rows={after[1]}")


def tv_validator_tests(work: Path) -> Path:
    # صيغ التيكر
    forms = ["COMI", "COMI.CA", "EGX:COMI", "EGX:COMI.CA", "comi.ca"]
    norm = {f: tv.normalize_ticker(f) for f in forms}
    resolved = {}
    for f in forms:   # load_ohlcv لازم يلاقي نفس الملف COMI.CA.csv لكل الصيغ
        names = tv._ticker_candidates(tv.normalize_ticker(f))
        resolved[f] = next((n for n in names if (HERE / "data" / f"{n}.csv").is_file()), None)
    check("ticker formats -> COMI.CA", set(norm.values()) == {"COMI.CA"} and set(resolved.values()) == {"COMI.CA"}, json.dumps(norm))

    # COMI بيانات لحد يوم كان المحرك فيه BUY (4/4) → مجلد مؤقت للسيناريو CONFIRMED
    full = eng.load_data_map(HERE / "data")["COMI.CA"]
    buy_end = next(i for i in range(len(full) - 1, 60, -1)
                   if eng.evaluate_4_mirrors(eng.calculate_indicators(full.iloc[: i + 1].tail(250)), eng.SignalConfig())["signal"] == "BUY")   # نفس tail(250) اللي في load_ohlcv
    buy_dir = work / "data_buy"
    buy_dir.mkdir()
    raw = full.iloc[: buy_end + 1].copy()
    raw.index = raw.index.tz_convert("Africa/Cairo").strftime("%Y-%m-%d")
    raw.index.name = "Date"
    raw.to_csv(buy_dir / "COMI.CA.csv")
    buy_day = raw.index[-1]
    empty_dir = work / "data_empty"
    empty_dir.mkdir()

    db = work / "validator.db"
    scenarios = [
        ("COMI + BUY + 4/4 true", buy_dir, {"ticker": "EGX:COMI", "action": "BUY", "price": 1}, "CONFIRMED", 100.0),
        ("COMI + BUY + 4/4 false", HERE / "data", {"ticker": "COMI", "action": "BUY", "price": 1}, "MISMATCH", None),
        ("COMI + BUY + file missing", empty_dir, {"ticker": "COMI", "action": "BUY"}, "REJECT", 0.0),
        ("INVALID + BUY", HERE / "data", {"ticker": "INVALID", "action": "BUY"}, "REJECT", 0.0),
        ("COMI + SELL", HERE / "data", {"ticker": "COMI", "action": "SELL"}, "REJECT", 0.0),
    ]
    for name, folder, alert, want, want_conf in scenarios:
        os.environ["DATA_FOLDER"] = str(folder)
        res = tv.validate_signal(alert)
        row_id = tv.log_alert(db, alert, res)
        with closing(sqlite3.connect(db)) as c:
            row = c.execute("SELECT ticker, status, confidence, py_mirrors_json, notes FROM tv_alerts WHERE id=?", (row_id,)).fetchone()
        mirrors = json.loads(row[3])
        conf_ok = (row[2] == want_conf) if want_conf is not None else (0 <= row[2] < 100 and row[2] == sum(mirrors.values()) * 25)
        mirrors_ok = (len(mirrors) == 4 and all(mirrors.values())) if want == "CONFIRMED" else (len(mirrors) == 4 if want == "MISMATCH" else mirrors == {})
        check(f"validator: {name} -> {want}", res["status"] == want and row[1] == want and conf_ok and mirrors_ok and row[0] in ("COMI.CA", "INVALID.CA"),
              f"db_row=(id={row_id}, ticker={row[0]}, status={row[1]}, confidence={row[2]}, mirrors={row[3]}, notes={row[4][:60]!r})"
              + (f" [4/4 day used: {buy_day}]" if want == "CONFIRMED" else ""))
    os.environ.pop("DATA_FOLDER", None)
    with closing(sqlite3.connect(db)) as c:
        check("validator: one new tv_alerts row per scenario", c.execute("SELECT COUNT(*) FROM tv_alerts").fetchone()[0] == len(scenarios))
    return buy_dir


def webhook_test(work: Path, buy_dir: Path) -> None:
    db, server_log = work / "webhook.db", work / "server.log"
    env = {**CLEAN_ENV, "HOST": "127.0.0.1", "PORT": "5057", "WEBHOOK_SECRET": "test_secret_123", "DB_PATH": str(db), "DATA_FOLDER": str(buy_dir)}
    with server_log.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen([sys.executable, "-W", "ignore", "tv_webhook_server.py"], cwd=HERE, env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:5057/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)

        def post(body: dict, secret: str) -> tuple[int, dict]:
            req = urllib.request.Request("http://127.0.0.1:5057/tv-webhook", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "X-Webhook-Secret": secret})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        code, body = post({"ticker": "EGX:COMI", "action": "BUY", "price": 85.5, "entry": 85.5, "sl": 82.3, "tp": 91.9}, "test_secret_123")
        bad_code, _ = post({"ticker": "COMI", "action": "BUY"}, "wrong")
        with closing(sqlite3.connect(db)) as c:
            rows = c.execute("SELECT ticker, status, confidence, entry, sl, tp FROM tv_alerts").fetchall()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    log_text = server_log.read_text(encoding="utf-8", errors="replace")
    check("webhook: POST -> 200 CONFIRMED + telegram dry_run", code == 200 and body.get("validated") == "CONFIRMED" and body.get("telegram") == "dry_run", f"{code} {body}")
    check("webhook: wrong secret -> 401, not stored", bad_code == 401 and len(rows) == 1, f"code={bad_code} rows={len(rows)}")
    check("webhook: DB row correct", rows == [("COMI.CA", "CONFIRMED", 100.0, 85.5, 82.3, 91.9)], f"{rows}")
    check("webhook: server log has validation + dry-run + processed lines",
          "Validated COMI.CA: CONFIRMED" in log_text and "TELEGRAM DRY-RUN" in log_text and "Webhook processed for EGX:COMI: CONFIRMED (telegram=dry_run)" in log_text
          and "Rejected webhook with invalid secret" in log_text)
    try:
        urllib.request.urlopen("http://127.0.0.1:5057/health", timeout=1)
        check("webhook: server stopped after test", False)
    except OSError:
        check("webhook: server stopped after test", True)


def main() -> int:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"===== test_closure run {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
    daily_runner_tests()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        buy_dir = tv_validator_tests(work)
        webhook_test(work, buy_dir)
    passed = sum(ok for _, ok, _ in results)
    print(f"\nRESULT {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


def test_script_suite() -> None:  # pytest entry point: every check above must pass
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
