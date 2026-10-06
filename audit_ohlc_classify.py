"""Read-only classification; tight tolerance is not strict equality."""
import csv
import hashlib
import math
import random
from collections import Counter
from datetime import date

from audit_ohlc import DATA_DIR, OUT_DIR, write_csv
from audit_ohlc_relations import classify, rel_diff

KINDS = ("ok", "open>high", "open<low", "zero_range", "invalid_range")
CATS = ("within_1e-9", "near", "medium", "large", "no_prev")


def categorize(value):
    for limit, name in zip((1e-9, 1e-3, 1e-2), CATS):
        if value <= limit:
            return name
    return "large"


def main():
    assert [categorize(v) for v in (0, 1e-9, 1e-3, 1e-2, 0.02)] == [
        "within_1e-9", "within_1e-9", "near", "medium", "large"]
    assert rel_diff(0.5, 0.6) > 0.16
    files = sorted(DATA_DIR.glob("*.csv"))
    if not files:
        raise ValueError("No input CSV files")
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    per_row = []
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = []
            for raw in csv.DictReader(file):
                row = {"date": date.fromisoformat(raw["Date"].strip()).isoformat(),
                       **{k.lower(): float(raw[k]) for k in ("Open", "High", "Low", "Close")}}
                if not all(math.isfinite(row[k]) for k in ("open", "high", "low", "close")):
                    raise ValueError(f"Nonfinite OHLC: {path.name} {row['date']}")
                rows.append(row)
        rows.sort(key=lambda row: row["date"])
        if len({row["date"] for row in rows}) != len(rows):
            raise ValueError(f"Duplicate dates: {path.name}")
        for i, row in enumerate(rows):
            kind = classify(row)[0].split("(")[0]
            prev = rows[i - 1]["close"] if i else None
            rel = rel_diff(row["open"], prev) if prev is not None else None
            delta = row["open"] - prev if prev is not None else None
            per_row.append({"ticker": path.stem, **row, "kind": kind,
                            "prev_close": prev, "rel_diff": rel,
                            "category": categorize(rel) if rel is not None else "no_prev",
                            "strict_equal": row["open"] == prev if prev is not None else None,
                            "d_abs": delta, "d_pct_close": delta / prev * 100 if prev not in (None, 0) else None})
    if files != sorted(DATA_DIR.glob("*.csv")) or any(hashlib.sha256(p.read_bytes()).hexdigest() != before[p] for p in files):
        raise RuntimeError("Input files changed during audit")
    table = Counter((r["kind"], r["category"]) for r in per_row)
    out = [f"Files: {len(files)}; rows: {len(per_row)}; duplicate dates: none",
           "rel_diff = |open-prev_close| / max(|open|,|prev_close|); zero/zero = 0",
           "Upper-inclusive limits: within_1e-9 <= 1e-9; near <= 0.001; medium <= 0.01; large > 0.01",
           "within_1e-9 is a tolerance bin, NOT strict equality.",
           "kind             within_1e-9 near medium large no_prev total"]
    for kind in KINDS:
        counts = [table[kind, cat] for cat in CATS]
        out.append(f"{kind:<16} " + " ".join(map(str, counts + [sum(counts)])))
    comp = [r for r in per_row if r["prev_close"] is not None]
    positive = [r for r in comp if r["kind"] in KINDS[:3]]
    zero = [r for r in comp if r["kind"] == "zero_range"]
    for name, rows in (("ALL COMPARABLE", comp), ("POSITIVE RANGE", positive), ("ZERO RANGE", zero)):
        out.append(f"--- {name}: {len(rows)} ---")
        for cat in CATS[:-1]:
            count = sum(r["category"] == cat for r in rows)
            out.append(f"  {cat}: {count} ({count / len(rows) * 100:.4f}%)" if rows else f"  {cat}: 0 (N/A)")
        out.append(f"  strict unequal: {sum(not r['strict_equal'] for r in rows)}")
        out.append(f"  outside 1e-9: {sum(r['category'] != CATS[0] for r in rows)}")
    first = Counter(r["kind"] for r in per_row if r["prev_close"] is None)
    out.append(f"First rows: {sum(first.values())}; {dict(first)}")
    population = [r for r in positive if r["strict_equal"]]
    sample = random.Random(42).sample(population, min(50, len(population)))
    out.append(f"Strict-equal POSITIVE-range sample: seed=42; n={len(sample)}; population={len(population)}")
    for kind in KINDS[:3]:
        s = sum(r["kind"] == kind for r in sample)
        p = sum(r["kind"] == kind for r in population)
        out.append(f"  {kind}: sample={s}/{len(sample)} ({s / len(sample) * 100:.3f}%); population={p}/{len(population)} ({p / len(population) * 100:.3f}%)" if sample else f"  {kind}: sample/population empty")
    out.append(f"Input SHA-256 unchanged: {len(files)}/{len(files)}")
    columns = ["ticker", "date", "kind", "category", "strict_equal", "open", "prev_close", "rel_diff",
               "d_abs", "d_pct_close", "high", "low", "close"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in (("non_exact_positive", [r for r in positive if not r["strict_equal"]]),
                       ("non_exact_zero", [r for r in zero if not r["strict_equal"]])):
        write_csv(OUT_DIR / f"audit_ohlc_{name}.csv",
                  [{k: "" if v is None else v for k, v in r.items()} for r in sorted(rows, key=lambda r: r["rel_diff"], reverse=True)], columns)
    write_csv(OUT_DIR / "audit_ohlc_exact_sample.csv", sample, columns)
    text = "\n".join(out)
    (OUT_DIR / "audit_ohlc_classify_summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
