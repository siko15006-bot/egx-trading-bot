"""Retry mode of daily_runner: defer the data-health alert until --alert-after, stop once today succeeded."""
import argparse
import json
import sqlite3
from datetime import datetime, time

import pytest

import daily_runner as dr

STALE = {"status": "DATA_UNAVAILABLE", "expected_session": "2030-01-02", "latest_session": "2030-01-01",
         "oldest_session": "2030-01-01", "loaded": 1, "required": 1, "fresh": 0, "problems": {"X.CA": "stale"}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "BASE_DIR", tmp_path)  # logs, delivery markers, health file all go to tmp
    monkeypatch.setattr(dr, "_load_universe", lambda folder: {})
    calls = {"telegram": [], "assess": 0}

    def assess(data_map, **kw):
        calls["assess"] += 1
        return {}, dict(STALE)

    monkeypatch.setattr(dr, "assess_daily_data", assess)
    monkeypatch.setattr(dr, "send_telegram", lambda msg: calls["telegram"].append(msg) or {"ok": True})

    def run(clock: str, alert_after: str | None):
        monkeypatch.setattr(dr, "_now", lambda: datetime.fromisoformat(f"2030-01-02T{clock}").replace(tzinfo=dr.CAIRO_TZ))
        args = argparse.Namespace(
            data_folder=str(tmp_path / "data"), db_path=str(tmp_path / "s.db"), capital=100_000,
            notify=True, no_telegram=False, download=False, dry_run=False, health_only=False,
            health_file="logs/health.json",
            alert_after=time.fromisoformat(alert_after) if alert_after else None,
        )
        rc = dr.run_daily(args)
        hp = tmp_path / "logs" / "health.json"  # not written on an early skip: last SUCCESS status is kept
        health = json.loads(hp.read_text(encoding="utf-8")) if hp.exists() else None
        return rc, health

    return run, calls, tmp_path


def test_early_retry_defers_alert(env):
    run, calls, _ = env
    rc, health = run("14:45", "19:30")
    assert rc == 2 and calls["telegram"] == [] and health["retry_exhausted"] is False


def test_final_retry_sends_one_alert_and_flags_exhausted(env):
    run, calls, tmp = env
    rc, health = run("19:45", "19:30")
    assert rc == 2 and len(calls["telegram"]) == 1 and health["retry_exhausted"] is True
    # runner replaces root log handlers (basicConfig force=True), so check the real log file
    assert "retry_exhausted=True" in (tmp / "logs" / "daily_20300102.log").read_text(encoding="utf-8")


def test_retry_stops_once_today_succeeded(env):
    run, calls, tmp = env
    with sqlite3.connect(tmp / "s.db") as c:
        c.execute("CREATE TABLE daily_reports (report_date TEXT PRIMARY KEY)")
        c.execute("INSERT INTO daily_reports VALUES ('20300102')")
    rc, _ = run("15:45", "19:30")
    assert rc == 0 and calls["assess"] == 0 and calls["telegram"] == []


def test_yesterdays_report_does_not_stop_today(env):
    run, calls, tmp = env
    with sqlite3.connect(tmp / "s.db") as c:
        c.execute("CREATE TABLE daily_reports (report_date TEXT PRIMARY KEY)")
        c.execute("INSERT INTO daily_reports VALUES ('20300101')")
    run("15:45", "19:30")
    assert calls["assess"] == 1


def test_without_alert_after_behaviour_is_unchanged(env):
    run, calls, _ = env
    rc, health = run("14:45", None)
    assert rc == 2 and len(calls["telegram"]) == 1 and "retry_exhausted" not in health


def test_two_final_retries_send_one_alert(env):  # Codex missing test 18: the scheduler may fire 19:45 twice
    run, calls, _ = env
    run("19:45", "19:30")
    rc, health = run("19:50", "19:30")
    assert rc == 2 and len(calls["telegram"]) == 1 and health["retry_exhausted"] is True
