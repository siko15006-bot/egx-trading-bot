"""Small per-attempt evidence files; no HTTP interception or credentials."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

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


def capture_download(directory: Path, symbol: str, request_number: int, raw: pd.DataFrame | None,
                     error: Exception | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    content = {"run_id": directory.parent.name, "ticker": symbol, "request_number": request_number,
               **timestamps(), "source": "yfinance_dataframe", "http_status": None, "http_headers": {},
               "transport_metadata": "not exposed by yf.download",
               "error_type": type(error).__name__ if error is not None else None,
               "raw_rows": 0 if raw is None else len(raw), "latest_timestamp": None, "last_five_rows": None}
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
