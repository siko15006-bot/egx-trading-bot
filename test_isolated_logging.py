import argparse
import json
import logging
from types import SimpleNamespace

import pandas as pd
import pytest

import daily_runner as dr
import data_downloader as dd
from run_evidence import SafeFormatter, capture_download


def frame():
    return pd.DataFrame({"Open": 100., "High": 102., "Low": 99., "Close": 101., "Volume": 1000},
                        index=pd.date_range("2026-10-01", periods=8))


def args(root=None, dry=True, **kwargs):
    values = dict(data_folder="data", db_path="egx_signals.db", capital=100000, notify=True,
                  no_telegram=False, download=False, dry_run=dry, health_only=False,
                  health_file="logs/bot_health_latest.json", alert_after=None, output_root=root)
    return argparse.Namespace(**(values | kwargs))


@pytest.fixture
def runner(tmp_path, monkeypatch):
    prod = tmp_path / "production"
    prod.mkdir()
    (prod / "egx_signals.db").write_bytes(b"untouched production marker")
    monkeypatch.setattr(dr, "BASE_DIR", prod)
    monkeypatch.setenv("DB_PATH", str(prod / "egx_signals.db"))
    monkeypatch.setenv("DATA_FOLDER", str(prod / "data"))
    monkeypatch.setattr(dr, "_load_universe", lambda folder: {})
    monkeypatch.setattr(dr, "assess_daily_data", lambda *a, **k: ({}, dict(status="DATA_OK", expected_session="2026-10-07",
                         latest_session="2026-10-07", fresh=90, required=90)))
    monkeypatch.setattr(dr, "scan_universe", lambda *a: pd.DataFrame())
    monkeypatch.setattr(dr, "build_signals", lambda *a: SimpleNamespace(buy=[], watch=[], sell=[], as_of="2026-10-07"))
    monkeypatch.setattr(dr, "send_telegram", lambda *a: pytest.fail("Isolated runs must never send Telegram"))
    return prod


def test_dry_run_separates_all_outputs_and_inherited_db(runner, tmp_path):
    out = tmp_path / "isolated"
    assert dr.run_daily(args(str(out))) == 0
    assert (runner / "egx_signals.db").read_bytes() == b"untouched production marker"
    assert not (runner / "logs").exists() and not (runner / "reports").exists()
    assert list((out / "reports").glob("*.xlsx"))
    health = json.loads((out / "logs/bot_health_latest.json").read_text(encoding="utf-8"))
    assert health["analysis_completed"] and health["report_created"]
    assert not health.get("report_stored") and not health.get("telegram_delivery")
    assert health["observed_at_utc"].endswith("+00:00") and health["observed_at_cairo"]
    text = next((out / "logs").glob("daily_*.log")).read_text(encoding="utf-8")
    assert f"[run_id={health['run_id']}]" in text


def test_default_dry_run_uses_temporary_root(runner):
    assert dr.run_daily(args()) == 0
    assert sorted(p.name for p in runner.iterdir()) == ["egx_signals.db"]


def test_missing_input_is_not_created(tmp_path):
    missing = tmp_path / "missing-input"
    assert dr._load_universe(missing) == {}
    assert not missing.exists()


def test_two_runs_same_day_have_distinct_snapshots(runner, tmp_path):
    out = tmp_path / "isolated"
    for _ in range(2):
        assert dr.run_daily(args(str(out))) == 0
    snapshots = list((out / "logs/runs").glob("*/health_*.json"))
    assert len(snapshots) == 2
    assert len({json.loads(p.read_text(encoding="utf-8"))["run_id"] for p in snapshots}) == 2


def test_failed_health_has_snapshot_and_no_delivery(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "assess_daily_data", lambda *a, **k: ({}, dict(status="DATA_UNAVAILABLE",
                         expected_session="2026-10-07", latest_session=None, fresh=0, required=90, problems={})))
    out = tmp_path / "isolated"
    assert dr.run_daily(args(str(out))) == 2
    health = json.loads(next((out / "logs/runs").glob("*/health_*.json")).read_text(encoding="utf-8"))
    assert health["status"] == "DATA_UNAVAILABLE" and not health.get("telegram_delivery")


def test_isolated_non_dry_run_cannot_send_telegram(runner, tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "assess_daily_data", lambda *a, **k: ({}, dict(status="DATA_UNAVAILABLE",
                         expected_session="2026-10-07", latest_session=None, fresh=0, required=90, problems={})))
    out = tmp_path / "isolated"
    assert dr.run_daily(args(str(out), dry=False)) == 2
    assert (runner / "egx_signals.db").read_bytes() == b"untouched production marker"
    assert not list(out.rglob("daily_delivery*"))


def test_isolated_download_cannot_overwrite_input(runner, tmp_path):
    with pytest.raises(ValueError, match="separate --output-root"):
        dr.run_daily(args(str(tmp_path / "isolated"), data_folder=str(runner / "data"), download=True))
    assert not (runner / "data").exists()


@pytest.mark.parametrize("bad", ["../escape.json", "production", "parent"])
def test_isolated_output_escape_rejected(runner, tmp_path, bad):
    root = runner if bad == "production" else tmp_path if bad == "parent" else tmp_path / "isolated"
    options = args(str(root), health_file=bad)
    with pytest.raises(ValueError, match="separate --output-root"):
        dr.run_daily(options)
    assert not (runner / "logs").exists()


def test_raw_tail_preserved_before_normalization(tmp_path, monkeypatch):
    raw = frame()
    raw.iloc[-1, raw.columns.get_loc("High")] = 1  # rejected by normalization, but retained in evidence
    monkeypatch.setattr(dd.yf, "download", lambda *a, **k: raw.copy())
    evidence = tmp_path / "run1/downloads"
    with pytest.raises(ValueError, match="malformed"):
        dd.download_ticker("COMI.CA", tmp_path / "data", evidence_dir=evidence)
    files = sorted(evidence.glob("*.json"))
    assert len(files) == 2  # period and fallback attempts both retained
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert body["run_id"] == "run1" and body["raw_rows"] == 8
    assert len(body["last_five_rows"]["data"]) == 5
    assert body["last_five_rows"]["data"][-1][1] == 1
    assert body["http_status"] is None and body["http_headers"] == {}
    assert not (tmp_path / "data/COMI.CA.csv").exists()


def test_network_exception_evidence_has_no_secret(tmp_path, monkeypatch):
    def fail(*a, **k):
        raise ConnectionError("Authorization: Bearer pretend-secret")
    monkeypatch.setattr(dd.yf, "download", fail)
    evidence = tmp_path / "run1/downloads"
    with pytest.raises(ConnectionError):
        dd.download_ticker("COMI.CA", tmp_path / "data", evidence_dir=evidence)
    text = next(evidence.glob("*.json")).read_text()
    assert "pretend-secret" not in text and json.loads(text)["error_type"] == "ConnectionError"


def test_evidence_drops_non_market_fields(tmp_path):
    raw = frame()
    raw["Cookie"] = "pretend-secret"
    capture_download(tmp_path / "run/downloads", "COMI.CA", 1, raw)
    assert "pretend-secret" not in next(tmp_path.rglob("*.json")).read_text()


def test_evidence_sanitizes_multiindex_labels(tmp_path):
    raw = frame()
    raw.columns = pd.MultiIndex.from_product([raw.columns, ["pretend-secret"]])
    capture_download(tmp_path / "run/downloads", "COMI.CA", 1, raw)
    text = next(tmp_path.rglob("*.json")).read_text()
    assert "pretend-secret" not in text and "Close" in text


def test_formatter_redacts_traceback_and_url_query():
    try:
        raise ValueError("Cookie: pretend-secret")
    except ValueError:
        import sys
        record = logging.LogRecord("x", logging.ERROR, "", 0, "https://example.test/?crumb=hidden", (), sys.exc_info())
    text = SafeFormatter("%(message)s").format(record)
    assert "hidden" not in text and "pretend-secret" not in text and "[REDACTED]" in text
