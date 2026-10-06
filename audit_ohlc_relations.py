"""Read-only price relationship audit; output reports outside data/."""
import csv
import hashlib
import math
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import median

from audit_ohlc import DATA_DIR, OUT_DIR, write_csv
from egx_4_mirrors_v3 import SECTOR_MAP

EXACT_REL_TOL = 1e-9
NEAR_REL_TOL = 1e-3


def classify(row):
    rng = row["high"] - row["low"]
    if rng < 0:
        return "invalid_range(high<low)", None
    if rng == 0:
        return "zero_range(high==low)", None
    if row["open"] > row["high"]:
        return "open>high", rng
    if row["open"] < row["low"]:
        return "open<low", rng
    return "ok", rng


def rel_diff(a, b):
    scale = max(abs(a), abs(b))
    return abs(a - b) / scale if scale else 0.0


def percentiles(values):
    values = sorted(values)
    return " ".join(f"p{int(p * 100)}={values[min(int(len(values) * p), len(values) - 1)]:.4f}"
                    for p in (0.10, 0.50, 0.90, 0.99))


def stats_block(rows, name):
    comp = [row for row in rows if row["prev_close"] is not None]
    out = [f"--- {name} ---", f"count: {len(rows)}; comparable: {len(comp)}"]
    if comp:
        for field, label in (("exact_match_prev_close", "strict equality"),
                             ("tight_match_prev_close", f"tight relative <= {EXACT_REL_TOL}"),
                             ("near_match_prev_close", f"near relative <= {NEAR_REL_TOL}")):
            count = sum(row[field] for row in comp)
            out.append(f"  {label}: {count}/{len(comp)} = {count / len(comp) * 100:.3f}%")
    for field, label in (("d_pct_close", "SIGNED (open-prev_close)/prev_close %"),
                         ("abs_d_pct_close", "ABS |open-prev_close|/|prev_close| %"),
                         ("abs_d_pct_range", "ABS |open-prev_close|/(high-low) %"),
                         ("vol_ratio", "volume / own stock median")):
        values = [row[field] for row in rows if row[field] is not None]
        if values:
            out.append(f"  {label}: {percentiles(values)}")
    return out


def main():
    assert classify({"open": 8, "high": 10, "low": 9}) == ("open<low", 1)
    assert classify({"open": 8, "high": 9, "low": 9})[0].startswith("zero_range")
    assert classify({"open": 8, "high": 8, "low": 9})[0].startswith("invalid_range")
    assert rel_diff(0.5, 0.5001) > NEAR_REL_TOL / 10
    assert percentiles([1]) == "p10=1.0000 p50=1.0000 p90=1.0000 p99=1.0000"
    files = sorted(DATA_DIR.glob("*.csv"))
    if not files:
        raise ValueError("No price CSVs")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    rows_by_ticker = {}
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = []
            for raw in csv.DictReader(file):
                dt = date.fromisoformat(raw["Date"].strip()).isoformat()
                row = {"date": dt, **{key.lower(): float(raw[key]) for key in ("Open", "High", "Low", "Close")},
                       "vol": int(raw["Volume"])}
                if not all(math.isfinite(row[key]) for key in ("open", "high", "low", "close")) or row["vol"] < 0:
                    raise ValueError(f"Invalid numeric data: {path.name} {dt}")
                rows.append(row)
        rows.sort(key=lambda row: row["date"])
        if len({row["date"] for row in rows}) != len(rows):
            raise ValueError(f"Duplicate dates: {path.name}; previous close ambiguous")
        rows_by_ticker[path.stem] = rows
    per_row = []
    for ticker, rows in rows_by_ticker.items():
        med_vol = median(row["vol"] for row in rows) if rows else 0
        for i, row in enumerate(rows):
            kind, rng = classify(row)
            prev = rows[i - 1]["close"] if i else None
            delta = row["open"] - prev if prev is not None else None
            dpc = delta / prev * 100 if prev not in (None, 0) else None
            dpr = delta / rng * 100 if delta is not None and rng else None
            per_row.append({"ticker": ticker, **row, "kind": kind,
                            "is_anomaly": kind in ("open>high", "open<low"), "prev_close": prev,
                            "d_abs": delta, "d_pct_close": dpc, "abs_d_pct_close": abs(dpc) if dpc is not None else None,
                            "d_pct_range": dpr, "abs_d_pct_range": abs(dpr) if dpr is not None else None,
                            "exact_match_prev_close": row["open"] == prev if prev is not None else None,
                            "tight_match_prev_close": rel_diff(row["open"], prev) <= EXACT_REL_TOL if prev is not None else None,
                            "near_match_prev_close": rel_diff(row["open"], prev) <= NEAR_REL_TOL if prev is not None else None,
                            "stock_med_vol": med_vol, "vol_ratio": row["vol"] / med_vol if med_vol > 0 else None,
                            "sector": SECTOR_MAP.get(ticker, "Unknown")})
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    if before != after or files != sorted(DATA_DIR.glob("*.csv")):
        raise RuntimeError("Input files changed during audit")
    kinds = Counter(row["kind"] for row in per_row)
    summary = [f"Total files: {len(files)}; total rows: {len(per_row)}", "Duplicate dates per ticker: none",
               f"Tolerances: strict equality separate; tight_rel={EXACT_REL_TOL}, near_rel={NEAR_REL_TOL}",
               "Relative difference denominator: max(|open|, |prev_close|); zero/zero = 0",
               f"Kind breakdown: {dict(kinds)}"]
    for name, rows in (("ANOMALIES", [r for r in per_row if r["is_anomaly"]]),
                       ("NORMALS", [r for r in per_row if r["kind"] == "ok"]),
                       ("open>high", [r for r in per_row if r["kind"] == "open>high"]),
                       ("open<low", [r for r in per_row if r["kind"] == "open<low"])):
        summary.extend(stats_block(rows, name))
    first = [r for r in per_row if r["prev_close"] is None]
    summary.append(f"First rows: {len(first)}; anomalous: {sum(r['is_anomaly'] for r in first)}; zero/invalid: {sum(r['kind'].startswith(('zero_range', 'invalid_range')) for r in first)}")
    summary.append("Monthly anomaly rate (positive-range anomalies / ALL bars, zero/invalid included in denominator):")
    totals = Counter(r["date"][:7] for r in per_row)
    anoms = Counter(r["date"][:7] for r in per_row if r["is_anomaly"])
    for month in sorted(totals):
        summary.append(f"  {month}: {anoms[month]}/{totals[month]} = {anoms[month] / totals[month] * 100:.2f}%")
    matched = sum(t in SECTOR_MAP for t in rows_by_ticker)
    summary.append(f"Sector coverage: {matched}/{len(files)} tickers ({matched / len(files) * 100:.1f}%); map entries: {len(SECTOR_MAP)}")
    summary.append("Sector labels copied from project map; not independently verified:")
    totals = Counter(r["sector"] for r in per_row)
    anoms = Counter(r["sector"] for r in per_row if r["is_anomaly"])
    for sector, count in totals.most_common():
        summary.append(f"  {sector}: {anoms[sector]}/{count} = {anoms[sector] / count * 100:.2f}%")
    summary.append("Volume median uses the full observed history per ticker; descriptive only, not a causal test.")
    summary.append(f"Input SHA-256 unchanged: {len(files)}/{len(files)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(summary)
    (OUT_DIR / "audit_ohlc_relations_summary.txt").write_text(text, encoding="utf-8")
    columns = ["ticker", "date", "kind", "is_anomaly", "open", "high", "low", "close", "prev_close",
               "d_abs", "d_pct_close", "abs_d_pct_close", "d_pct_range", "abs_d_pct_range",
               "exact_match_prev_close", "tight_match_prev_close", "near_match_prev_close",
               "vol", "stock_med_vol", "vol_ratio", "sector"]
    write_csv(OUT_DIR / "audit_ohlc_relations_per_row.csv",
              [{key: "" if value is None else value for key, value in row.items()} for row in per_row], columns)
    print(text)


if __name__ == "__main__":
    main()
