"""Read prices without modifying them; write audit reports outside data/."""
import csv
import hashlib
import math
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median

DATA_DIR = Path(r"C:\Projects\EGX\data")
OUT_DIR = Path(r"C:\Users\ahmed\Documents\Codex\2026-10-05\a\outputs")


def parse_row(raw):
    date.fromisoformat(raw["Date"])
    row = {"date": raw["Date"], **{key.lower(): float(raw[key])
           for key in ("Open", "High", "Low", "Close")}, "vol": int(raw["Volume"])}
    if not all(math.isfinite(row[key]) for key in ("open", "high", "low", "close")):
        raise ValueError(f"Nonfinite OHLC on {row['date']}")
    if row["high"] < row["low"]:
        raise ValueError(f"High below Low on {row['date']}")
    return row


def classify(row):
    if row["open"] > row["high"]:
        return "open>high", row["open"] - row["high"]
    if row["open"] < row["low"]:
        return "open<low", row["low"] - row["open"]
    return "ok", 0.0


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in columns} for row in rows)


def main():
    assert classify({"open": 12, "high": 11, "low": 9}) == ("open>high", 1)
    assert classify({"open": 8, "high": 11, "low": 9}) == ("open<low", 1)
    assert classify({"open": 9, "high": 11, "low": 9}) == ("ok", 0.0)
    files = sorted(DATA_DIR.glob("*.csv"))
    if not files:
        raise ValueError(f"No CSV files in {DATA_DIR}")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    anomalies = []
    by_ticker, by_month, by_direction, by_position = (Counter() for _ in range(4))
    magnitudes_pct, magnitudes_abs = [], []
    total_rows = 0
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = [parse_row(raw) for raw in csv.DictReader(file)]
        total_rows += len(rows)
        for i, row in enumerate(rows):
            kind, delta = classify(row)
            if kind == "ok":
                continue
            daily_range = row["high"] - row["low"]
            pct = delta / daily_range * 100 if daily_range > 0 else float("nan")
            position = "first" if i == 0 else "last" if i == len(rows) - 1 else "middle"
            anomalies.append({"ticker": path.stem, "date": row["date"], "position": position,
                              "kind": kind, **{key: row[key] for key in ("open", "high", "low", "close")},
                              "delta_abs": delta, "delta_pct_of_range": pct})
            by_ticker[path.stem] += 1
            by_month[row["date"][:7]] += 1
            by_direction[kind] += 1
            by_position[position] += 1
            if math.isfinite(pct):
                magnitudes_pct.append(pct)
            magnitudes_abs.append(delta)
    if not total_rows:
        raise ValueError("No price rows")
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    if before != after or files != sorted(DATA_DIR.glob("*.csv")):
        raise RuntimeError("Input files changed during audit; retry on a stable snapshot")
    summary = [f"Total CSV files: {len(files)}", f"Total rows: {total_rows}",
               f"Anomalous rows: {len(anomalies)} ({len(anomalies) / total_rows * 100:.2f}%)",
               f"By direction: {dict(by_direction)}", f"By file position: {dict(by_position)}",
               "", "Top 15 tickers by anomaly count:"]
    summary.extend(f"  {ticker}: {count}" for ticker, count in by_ticker.most_common(15))
    summary.extend(["", "Top 10 months by anomaly count:"])
    summary.extend(f"  {month}: {count}" for month, count in by_month.most_common(10))
    if magnitudes_abs:
        summary.extend(["", "Anomaly magnitude (absolute price units):",
                        f"  min={min(magnitudes_abs):.6f} median={median(magnitudes_abs):.6f} "
                        f"max={max(magnitudes_abs):.6f} mean={mean(magnitudes_abs):.6f}"])
    if magnitudes_pct:
        ordered = sorted(magnitudes_pct)
        summary.extend(["Anomaly magnitude (as % of High-Low range):",
                        "  " + " ".join(f"p{int(p * 100)}={ordered[int(len(ordered) * p)]:.2f}%"
                                         for p in (0.10, 0.50, 0.90, 0.99))])
    summary.append(f"Range <= 0 excluded from range percentiles: {len(anomalies) - len(magnitudes_pct)}")
    summary.append(f"Input SHA-256 unchanged: {len(files)}/{len(files)}")
    columns = ["ticker", "date", "position", "kind", "open", "high", "low", "close",
               "delta_abs", "delta_pct_of_range"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(summary)
    (OUT_DIR / "audit_ohlc_summary.txt").write_text(text, encoding="utf-8")
    write_csv(OUT_DIR / "audit_ohlc_top100_magnitude.csv",
              sorted(anomalies, key=lambda row: row["delta_abs"], reverse=True)[:100], columns)
    write_csv(OUT_DIR / "audit_ohlc_random100.csv",
              random.Random(42).sample(anomalies, min(100, len(anomalies))), columns)
    grouped = defaultdict(list)
    for row in anomalies:
        grouped[row["ticker"]].append(row)
    write_csv(OUT_DIR / "audit_ohlc_per_ticker_first5.csv",
              [row for group in grouped.values() for row in group[:5]], columns)
    print(text)
    print(f"\nOutputs written to {OUT_DIR}")


if __name__ == "__main__":
    main()
