"""Small per-attempt evidence files; no HTTP interception or credentials."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
from curl_cffi import requests, CurlInfo

CAIRO_TZ = ZoneInfo("Africa/Cairo")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex


def timestamps() -> dict[str, str]:
    now = datetime.now(timezone.utc)
    return {"observed_at_utc": now.isoformat(), "observed_at_cairo": now.astimezone(CAIRO_TZ).isoformat()}


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        text = re.sub(r"https?://[^\s?]+\?[^\s]+", "[URL query redacted]", text)
        return re.sub(r"(?im)\b(authorization|set-cookie|cookie|crumb|token|api[_-]?key|password)['\"]?\s*[:=]\s*[^\r\n]+",
                      r"\1=[REDACTED]", text)


class EvidenceSession(requests.Session):
    """Observe chart transfers only; never record URLs, cookies or request headers."""

    def __init__(self):
        super().__init__(impersonate="chrome", curl_infos=[CurlInfo.STARTTRANSFER_TIME])
        self.chart_requests = []

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if parsed.hostname not in {"query1.finance.yahoo.com", "query2.finance.yahoo.com"} or not parsed.path.startswith("/v8/finance/chart/"):
            return super().request(method, url, **kwargs)
        started = datetime.now(timezone.utc)
        event = {"started_at_utc": started.isoformat(), "started_at_cairo": started.astimezone(CAIRO_TZ).isoformat(),
                 "http_status": None, "http_headers": {}, "first_byte_seconds": None,
                 "first_byte_at_utc": None, "first_byte_at_cairo": None, "error_type": None}
        params = kwargs.get("params") or {}
        event["query"] = {k: v for k, v in params.items() if k in {"range", "interval", "period1", "period2"}
                          and (type(v) is int or isinstance(v, str) and re.fullmatch(r"[0-9a-z]+", v))}
        try:
            response = super().request(method, url, **kwargs)
        except Exception as exc:
            event["error_type"] = type(exc).__name__
            raise
        else:
            event["http_status"] = response.status_code
            for header in ("Content-Length", "Age"):
                value = response.headers.get(header)
                if value is not None and str(value).isdigit():
                    event["http_headers"][header] = int(value)
            seconds = response.infos.get(CurlInfo.STARTTRANSFER_TIME)
            if isinstance(seconds, (int, float)) and seconds > 0:
                first_byte = started + timedelta(seconds=seconds)
                event.update(first_byte_seconds=seconds, first_byte_at_utc=first_byte.isoformat(),
                             first_byte_at_cairo=first_byte.astimezone(CAIRO_TZ).isoformat())
            return response
        finally:
            event.update(timestamps())
            self.chart_requests.append(event)


def capture_download(directory: Path, symbol: str, request_number: int, raw: pd.DataFrame | None,
                     error: Exception | None = None, transport: list | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    content = {"run_id": directory.parent.name, "ticker": symbol, "request_number": request_number,
               **timestamps(), "source": "yfinance_dataframe", "http_status": None, "http_headers": {},
               "transport_metadata": "not exposed by yf.download",
               "error_type": type(error).__name__ if error is not None else None,
               "raw_rows": 0 if raw is None else len(raw), "latest_timestamp": None, "last_five_rows": None}
    if transport is not None:
        content.update(chart_http_requests=transport, transport_metadata="curl_cffi_chart_requests" if transport else "no_chart_http_observed")
        if transport:
            content.update(http_status=transport[-1]["http_status"], http_headers=transport[-1]["http_headers"])
    if raw is not None and not raw.empty:
        # Keep only market fields, never arbitrary provider strings, request headers or session objects.
        allowed = {"Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"}
        columns = [c for c in raw.columns if any(str(v) in allowed for v in (c if isinstance(c, tuple) else (c,)))]
        sample = raw.loc[:, columns].tail(5).apply(pd.to_numeric, errors="coerce")
        sample.columns = [next(str(v) for v in (c if isinstance(c, tuple) else (c,)) if str(v) in allowed) for c in columns]
        sample.index = pd.to_datetime(sample.index, errors="coerce")
        content["latest_timestamp"] = str(pd.to_datetime(raw.index, errors="coerce").max())
        content["last_five_rows"] = json.loads(sample.to_json(orient="split", date_format="iso", double_precision=15))
    path = directory / f"{symbol}_{request_number}.json"
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
