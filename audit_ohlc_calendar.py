"""Observed date gaps are NOT proof of missing exchange sessions."""
import csv
import hashlib
from collections import Counter
from datetime import date

from audit_ohlc import DATA_DIR, OUT_DIR, parse_row

FOCUS_DATES = ("2026-06-21", "2026-06-23", "2026-08-11", "2026-08-17")
SAMPLE_TICKERS = ("ABUK.CA", "COMI.CA", "EFID.CA", "SWDY.CA", "TMGH.CA")


def days_between(previous, current):
    return (date.fromisoformat(current) - date.fromisoformat(previous)).days


def main():
    assert days_between("2026-06-18", "2026-06-21") == 3
    assert days_between("2026-08-16", "2026-08-17") == 1
    files = sorted(DATA_DIR.glob("*.csv"))
    if not files:
        raise ValueError("No price files")
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    data, indexes = {}, {}
    for path in files:
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = [parse_row(raw) for raw in csv.DictReader(file)]
        rows.sort(key=lambda row: row["date"])
        index = {row["date"]: i for i, row in enumerate(rows)}
        if len(index) != len(rows):
            raise ValueError(f"Duplicate dates: {path.name}")
        data[path.stem], indexes[path.stem] = rows, index
    out = ["Observed CSV dates only; official EGX calendar NOT checked.",
           "Calendar-day gaps do not establish missing trading sessions.",
           "=== Context rows around focus dates ==="]
    for ticker in SAMPLE_TICKERS:
        if ticker not in data:
            out.append(f"{ticker}: FILE NOT PRESENT")
            continue
        rows = data[ticker]
        for fd in FOCUS_DATES:
            i = indexes[ticker].get(fd)
            if i is None:
                out.append(f"{ticker} {fd}: NOT PRESENT")
                continue
            out.append(f"--- {ticker} around {fd} ---")
            for row in rows[max(0, i - 3):i + 4]:
                out.append(f"  {row['date']} open={row['open']:.4f} high={row['high']:.4f} "
                           f"low={row['low']:.4f} close={row['close']:.4f} vol={row['vol']}"
                           + (" <== FOCUS" if row["date"] == fd else ""))
    dates = Counter(row["date"] for rows in data.values() for row in rows)
    ordered = sorted(dates)
    out.extend(["=== Observed union of dates across tickers ===",
                f"unique dates: {len(ordered)}; first: {ordered[0]}; last: {ordered[-1]}"])
    for fd in FOCUS_DATES:
        if fd not in dates:
            out.append(f"{fd}: absent from all CSVs")
            continue
        i = ordered.index(fd)
        out.extend([f"{fd}: tickers_count={dates[fd]}",
                    f"  before: {ordered[max(0, i - 5):i]}", f"  after: {ordered[i + 1:i + 6]}"])
    gaps = [(a, b, days_between(a, b)) for a, b in zip(ordered, ordered[1:]) if days_between(a, b) > 4]
    out.append(f"=== Observed date gaps >4 calendar days: {len(gaps)} ===")
    out.extend(f"  {a} -> {b}: {n} days" for a, b, n in gaps)
    out.append("=== Focus dates: strict equality and volume ===")
    for fd in FOCUS_DATES:
        groups = {"exact": [], "non-exact": []}
        predecessors = Counter()
        absent, no_prev = [], []
        for ticker, rows in data.items():
            i = indexes[ticker].get(fd)
            if i is None:
                absent.append(ticker)
                continue
            if i == 0:
                no_prev.append(ticker)
                continue
            current, previous = rows[i], rows[i - 1]
            predecessors[previous["date"]] += 1
            key = "exact" if current["open"] == previous["close"] else "non-exact"
            groups[key].append((ticker, current))
        out.append(f"{fd}: exact={len(groups['exact'])}; non-exact={len(groups['non-exact'])}; absent={len(absent)}; no_prev={len(no_prev)}")
        out.append(f"  predecessor dates: {dict(predecessors)}")
        for key, group in groups.items():
            out.append(f"  {key}: volume=0: {sum(row['vol'] == 0 for _, row in group)}; volume>0: {sum(row['vol'] > 0 for _, row in group)}")
            if len(group) <= 15:
                out.append(f"  {key} ticker volumes: {[(t, row['vol']) for t, row in group]}")
    if files != sorted(DATA_DIR.glob("*.csv")) or any(hashlib.sha256(p.read_bytes()).hexdigest() != hashes[p] for p in files):
        raise RuntimeError("Input files changed during audit")
    out.append(f"Input SHA-256 unchanged: {len(files)}/{len(files)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out)
    (OUT_DIR / "audit_ohlc_calendar.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
