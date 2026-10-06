"""Read-only analysis of the existing per-row audit snapshot."""
import csv
import hashlib
import math
from collections import Counter
from fractions import Fraction

from audit_ohlc import OUT_DIR, write_csv
from audit_ohlc_classify import categorize
from audit_ohlc_relations import rel_diff

FRACTION_TOL = 0.005
CANDIDATE_FRACTIONS = tuple(Fraction(s) for s in (
    "1/2", "1/3", "2/3", "1/4", "3/4", "1/5", "2/5", "3/5", "4/5",
    "1/6", "5/6", "1/7", "2/7", "3/7", "4/7", "5/7", "6/7",
    "1/8", "3/8", "5/8", "7/8", "1/10", "3/10", "7/10", "9/10"))


def nearest(ratio):
    best = min(CANDIDATE_FRACTIONS, key=lambda f: abs(ratio - float(f)))
    error = abs(ratio - float(best))
    return str(best), error, error <= FRACTION_TOL


def main():
    assert len(CANDIDATE_FRACTIONS) == 25
    assert nearest(2 / 3) == ("2/3", 0.0, True)
    assert nearest(1.2)[2] is False
    source = OUT_DIR / "audit_ohlc_relations_per_row.csv"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with source.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    seen = set()
    for row in rows:
        key = (row["ticker"], row["date"])
        if key in seen:
            raise ValueError(f"Duplicate snapshot row: {key}")
        seen.add(key)
        for field in ("open", "prev_close", "vol", "stock_med_vol", "vol_ratio"):
            row[field] = float(row[field]) if row[field] else None
            if row[field] is not None and not math.isfinite(row[field]):
                raise ValueError(f"Nonfinite {field}: {key}")
        if row["vol"] is None or row["vol"] < 0:
            raise ValueError(f"Invalid volume: {key}")
        prev = row["prev_close"]
        row["rel_diff"] = rel_diff(row["open"], prev) if prev is not None else None
        row["category"] = categorize(row["rel_diff"]) if prev is not None else "no_prev"
        row["open_over_prev"] = row["open"] / prev if prev not in (None, 0) else None
    if hashlib.sha256(source.read_bytes()).hexdigest() != before:
        raise RuntimeError("Input snapshot changed during analysis")
    out = [f"Source snapshot: {source}", f"Source SHA-256: {before}", f"Total rows: {len(rows)}",
           f"Candidate fractions ({len(CANDIDATE_FRACTIONS)}): " + ", ".join(map(str, CANDIDATE_FRACTIONS)),
           f"Fraction tolerance: absolute ratio distance <= {FRACTION_TOL}; NOT relative percent error",
           "rel_diff denominator: max(|open|, |prev_close|); zero/zero = 0"]
    zero = [r for r in rows if r["kind"].startswith("zero_range")]
    pos = [r for r in zero if r["vol"] > 0]
    out.extend([f"Zero-range rows: {len(zero)}; volume>0: {len(pos)}; volume=0: {len(zero) - len(pos)}"])
    vr = sorted(r["vol_ratio"] for r in pos if r["vol_ratio"] is not None)
    if vr:
        out.append("Zero-range positive volume / own median: " + " ".join(
            f"p{int(q * 100)}={vr[min(int(len(vr) * q), len(vr) - 1)]:.3f}" for q in (0.1, 0.5, 0.9)) + f" max={vr[-1]:.3f}")
    non_exact = [r for r in rows if r["category"] in ("near", "medium", "large")]
    for name, key_fn, limit in (("By month", lambda r: r["date"][:7], None),
                                ("By specific day (top 20)", lambda r: r["date"], 20)):
        totals = Counter(key_fn(r) for r in rows)
        counts = Counter(key_fn(r) for r in non_exact)
        by_cat = Counter((key_fn(r), r["category"]) for r in non_exact)
        keys = sorted(totals) if limit is None else sorted(totals, key=lambda k: (-counts[k], k))[:limit]
        out.append(f"--- {name}; denominator ALL snapshot rows ---")
        for key in keys:
            out.append(f"  {key}: {counts[key]}/{totals[key]} ({counts[key] / totals[key] * 100:.2f}%) "
                       f"near={by_cat[key, 'near']} medium={by_cat[key, 'medium']} large={by_cat[key, 'large']}")
    for cat in ("near", "medium", "large"):
        group = [r for r in non_exact if r["category"] == cat]
        tickers = Counter(r["ticker"] for r in group)
        top = tickers.most_common(10)
        share = sum(n for _, n in top)
        out.append(f"{cat}: {len(group)} rows; {len(tickers)} tickers; top10 share={share}/{len(group)} "
                   + (f"({share / len(group) * 100:.1f}%)" if group else "(N/A)"))
        out.append("  " + ", ".join(f"{ticker}:{n}" for ticker, n in top))
    matches = []
    for row in non_exact:
        ratio = row["open_over_prev"]
        if ratio is None:
            continue
        fraction, error, matched = nearest(ratio)
        matches.append({key: row[key] for key in ("ticker", "date", "kind", "category", "open", "prev_close", "open_over_prev", "rel_diff")}
                       | {"nearest_fraction": fraction, "matched_fraction": fraction if matched else "",
                          "match_err": error, "matched": matched})
    out.append(f"Fraction evaluation: {len(matches)}/{len(non_exact)} non-exact rows have defined ratio")
    out.append(f"Ratios >=1 (outside candidate direction): {sum(r['open_over_prev'] >= 1 for r in matches)}")
    for cat in ("near", "medium", "large"):
        group = [r for r in matches if r["category"] == cat]
        count = sum(r["matched"] for r in group)
        out.append(f"  {cat}: {count}/{len(group)} matched " + (f"({count / len(group) * 100:.1f}%)" if group else "(N/A)"))
    out.append("Matched fraction frequency:")
    out.extend(f"  {f}: {n}" for f, n in Counter(r["matched_fraction"] for r in matches if r["matched"]).most_common())
    unmatched = [r for r in matches if r["category"] == "large" and not r["matched"]]
    out.append(f"Unmatched large: {len(unmatched)}; non-match does NOT establish data error")
    out.append("Matching does NOT establish a corporate action; candidate set only covers ratios below 1.")
    out.append("Input snapshot hash unchanged; raw data not reloaded or modified in this run.")
    columns = ["ticker", "date", "kind", "category", "open", "prev_close", "open_over_prev", "rel_diff",
               "nearest_fraction", "matched_fraction", "match_err", "matched"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "audit_ohlc_fraction_matches.csv", matches, columns)
    write_csv(OUT_DIR / "audit_ohlc_unmatched_large.csv", unmatched, columns)
    text = "\n".join(out)
    (OUT_DIR / "audit_ohlc_fractions_summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
