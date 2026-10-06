"""Download fully adjusted (splits + dividends) daily prices into data_dividend_adjusted/.

Companion to data/ (split-adjusted, dividend-unadjusted), never a replacement: returns come
from here, execution levels stay on data/. See KNOWN_ISSUES.md "Price series".
Usage: python fetch_adjusted.py [TICKER ...]   (default: every CSV name in data/)
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).parent
OUT = HERE / "data_dividend_adjusted"
ACTIONS_CSV = HERE / "docs" / "corporate_actions.csv"
LOG = HERE / "docs" / "adjusted_download_log.json"
SETTINGS = {"period": "2y", "interval": "1d", "auto_adjust": True, "actions": True}


def fetch(ticker: str) -> pd.DataFrame:
    raw = yf.download(ticker, progress=False, threads=False, timeout=30, **SETTINGS)
    if raw.empty:
        raise ValueError("empty download")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.index = pd.to_datetime(raw.index).strftime("%Y-%m-%d")
    raw.index.name = "Date"
    return raw[["Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]]


def main() -> int:
    tickers = sys.argv[1:] or sorted(p.stem for p in (HERE / "data").glob("*.csv"))
    OUT.mkdir(exist_ok=True)
    log = {"run_at": datetime.now().isoformat(timespec="seconds"), "yfinance": yf.__version__,
           "settings": SETTINGS, "files": {}}
    for t in tickers:
        try:
            frame = fetch(t)
        except Exception as exc:  # ponytail: one bad ticker must not stop the batch; it is logged
            log["files"][t] = {"error": str(exc)}
            continue
        frame.to_csv(OUT / f"{t}.csv")
        log["files"][t] = {"rows": len(frame), "first": frame.index[0], "last": frame.index[-1],
                           "dividends": int((frame["Dividends"] != 0).sum()),
                           "splits": int((frame["Stock Splits"] != 0).sum())}
    # Rebuild the tracked actions list from every file on disk (cheap, always consistent).
    rows = []
    for f in sorted(OUT.glob("*.csv")):
        d = pd.read_csv(f)
        hit = d[(d["Dividends"] != 0) | (d["Stock Splits"] != 0)]
        rows += [(f.stem, *r) for r in hit[["Date", "Dividends", "Stock Splits"]].itertuples(index=False)]
    ACTIONS_CSV.parent.mkdir(exist_ok=True)
    pd.DataFrame(rows, columns=["ticker", "ex_date", "dividend", "split"]).to_csv(ACTIONS_CSV, index=False)
    LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(log["files"], indent=1))
    return 0 if all("error" not in v for v in log["files"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
