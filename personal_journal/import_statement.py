"""Thndr statement import (docs/personal_ledger_design.md, "Parser").

Real format (first seen: E-STATEMENT_Jul_2026_01.pdf, 2026-10-07): a PDF "كشف حساب عميل" with columns
التاريخ (d/m/yyyy, no time) | الوصف ("بيع|شراء <Arabic company name> (qty@price)") | القيمة (net cash, fees merged)
| رصيد (running balance), plus opening/closing balance and period in the header. No ticker, time or fee column:
the ticker comes from company_names.json, the fees are derived (gross − net) and every row must reconcile with the
running balance. Anything else (a row without qty@price, an unknown company) is an error, never a guess.
CSV/XLSX: no real Thndr export seen yet, so their mapping is not implemented (Codex's CSV fixtures stay skipped).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

Format = Literal["csv", "xlsx", "pdf"]

HERE = Path(__file__).resolve().parent
NAMES_FILE = HERE / "company_names.json"
LOG_DIR = HERE.parent / "logs"
SUBSCRIPTION_START = date(2026, 9, 24)  # Thndr annual plan (2,646 EGP/yr, 50 trades/month): brokerage 0 from here
CENT = Decimal("0.01")

_ARABIC = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")
_MIRROR = str.maketrans("()", ")(")


def detect_format(path: Path) -> Format:
    """CSV / XLSX / PDF from content, not only the extension."""
    head = Path(path).read_bytes()[:8]
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    try:
        Path(path).read_text(encoding="utf-8-sig")[:4096].splitlines()[0].index(",")
        return "csv"
    except (UnicodeDecodeError, IndexError, ValueError):
        raise ValueError(f"{path}: unknown statement format") from None


def _logical(visual: str) -> str:
    """pdfplumber returns RTL lines in visual order with Arabic presentation forms: reverse the words, and the letters
    of each Arabic word (before NFKC, so lam-alef ligatures expand in the right order); mirror its brackets."""
    words = []
    for w in reversed(visual.split()):
        words.append(unicodedata.normalize("NFKC", w[::-1]).translate(_MIRROR) if _ARABIC.search(w) else w)
    return " ".join(words)


def _key(name: str) -> str:
    """Letters only, common spelling variants folded — statement and JSON names match despite spacing/brackets."""
    name = unicodedata.normalize("NFKC", name).translate(str.maketrans("أإآىة", "ااايه"))
    return "".join(ch for ch in name if ch.isalpha())


def _names() -> dict[str, str]:
    raw = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    return {_key(k): v for k, v in raw.items() if not k.startswith("_")}


def _money(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


_ROW = re.compile(r"^(?P<bal>-?[\d,]+\.?\d*) (?P<amt>-?[\d,]+\.?\d*) \(\s*(?P<a>[\d.]+)@(?P<b>[\d.]+)\s*\) "
                  r"(?P<desc>.+) (?P<date>\d{1,2}/\d{1,2}/\d{4})$")


def parse_pdf(path: Path) -> dict[str, Any]:
    """{'header': {...}, 'rows': [...]} — header: period, opening/closing balance; rows reconcile or ValueError."""
    import pdfplumber  # requirements_analytics.txt

    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for cells in table:
                    lines += [ln for c in cells if c for ln in c.splitlines()]
    header: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    names = _names()
    for visual in lines:
        logical = _logical(visual)
        if m := re.search(r"رصيد أول المدة ([\d,.]+)", logical):
            header["opening_balance"] = _money(m[1])
        if m := re.search(r"رصيد آخر المدة ([\d,.]+)", logical):
            header["closing_balance"] = _money(m[1])
        if m := re.search(r"من (\d+/\d+/\d{4}) إلى (\d+/\d+/\d{4})", logical):
            header["period_from"], header["period_to"] = (datetime.strptime(d, "%d/%m/%Y").date().isoformat() for d in m.groups())
        m = _ROW.match(visual)
        if not m:
            if re.match(r"^\s*-?[\d,]+\.\d+ -?[\d,]+\.?\d* ", visual) and "@" not in visual:
                raise ValueError(f"{path.name}: row without qty@price (dividend/transfer/fee?) — not mapped yet: {logical}")
            continue
        desc = _logical(m["desc"])
        side_word, _, company = desc.partition(" ")
        side = {"بيع": "SELL", "شراء": "BUY"}.get(side_word)
        if side is None:
            raise ValueError(f"{path.name}: unknown operation {side_word!r} in {desc!r}")
        ticker = names.get(_key(company))
        if ticker is None:
            raise ValueError(f"{path.name}: company not in company_names.json: {company!r} (add it after checking the "
                             f"price against data/)")
        a, b = m["a"], m["b"]
        price_s, qty_s = (a, b) if "." in a else (b, a)   # price is printed with 4 decimals, qty is an integer
        qty, price = int(qty_s), Decimal(price_s)
        amount = _money(m["amt"])
        gross = (qty * price).quantize(CENT)
        fees = gross - amount if side == "SELL" else -amount - gross
        rows.append({"row_no": len(rows) + 1, "event_type": "fill",
                     "trade_date": datetime.strptime(m["date"], "%d/%m/%Y").date().isoformat(),
                     "ts_cairo": None,  # the statement has no time of day
                     "ticker": ticker, "company_ar": company, "side": side, "qty": qty, "price": price,
                     "gross_value": gross, "amount": amount, "total_fees": fees, "fees_source": "derived: gross - net",
                     "balance": _money(m["bal"]), "description": desc, "raw": visual})
    if "opening_balance" not in header or "closing_balance" not in header:
        raise ValueError(f"{path.name}: opening/closing balance not found — unknown layout")
    running = header["opening_balance"]
    for r in rows:
        running += r["amount"]
        if running != r["balance"]:
            raise ValueError(f"{path.name}: row {r['row_no']} does not reconcile: {running} != {r['balance']}")
        if r["total_fees"] < 0:
            raise ValueError(f"{path.name}: row {r['row_no']} negative derived fees {r['total_fees']}")
    if running != header["closing_balance"]:
        raise ValueError(f"{path.name}: rows sum to {running}, closing balance is {header['closing_balance']}")
    return {"header": header, "rows": rows}


def parse_rows(path: Path, fmt: Format) -> list[dict[str, Any]]:
    """Statement rows → normalised dicts (TICKER.CA, side, qty, price, fees). Unknown column/row → error."""
    if fmt == "pdf":
        return parse_pdf(Path(path))["rows"]
    raise NotImplementedError(f"{fmt}: no real Thndr {fmt.upper()} export seen yet (the statement is a PDF)")


def expected_fees(value: Decimal, trade_date: str) -> dict[str, Decimal]:
    """Fee formulas compared on every fill. 'observed' = fees_config without stamp duty, each component rounded to the
    piaster — matches all 5 July 2026 fills exactly (= 3 EGP + 0.125% below 20,000: brokerage 2 + 0.1%, FRA minimum 1,
    EGX 0.01%, MCDR 0.01%, insurance 0.005%). 'fees_config' = the module as is (includes 0.05% stamp)."""
    from fees_config import order_fees

    parts = order_fees(float(value))
    rounded = {k: Decimal(str(v)).quantize(CENT, ROUND_HALF_UP) for k, v in parts.items()}
    observed = sum(v for k, v in rounded.items() if k != "stamp")
    out = {"fees_config": Decimal(str(sum(parts.values()))).quantize(CENT, ROUND_HALF_UP), "observed": observed}
    if date.fromisoformat(trade_date) >= SUBSCRIPTION_START:  # ponytail: unverified until a post-24-09 statement
        out["observed"] = observed - rounded["brokerage"]
    return out


def fee_report(rows: list[dict[str, Any]], source: str) -> list[str]:
    """One line per fill (statement fee vs both formulas) + FEE_DIFF tags; appended to logs/ledger_import_*.log."""
    lines = []
    for r in rows:
        exp = expected_fees(r["gross_value"], r["trade_date"])
        tag = "" if r["total_fees"] == exp["observed"] else "  FEE_DIFF"
        lines.append(f"{source} row {r['row_no']} {r['trade_date']} {r['ticker']} {r['side']} {r['qty']}@{r['price']} "
                     f"gross={r['gross_value']} fees: statement={r['total_fees']} observed_formula={exp['observed']} "
                     f"fees_config={exp['fees_config']}{tag}")
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / f"ledger_import_{datetime.now():%Y%m%d}.log").open("a", encoding="utf-8") as f:
        f.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} fee check {source}\n" + "\n".join(lines) + "\n")
    return lines


BLOCKING = ("OVERSELL", "GROSS_MISMATCH", "HOLDINGS_MISMATCH")   # FEE_DIFF and PERIOD_OVERLAP are warnings


def validate_balance(rows: list[dict[str, Any]], holdings: dict[str, int] | None = None,
                     *, earlier_periods: list[tuple[int, str, str]] | None = None,
                     period: tuple[str, str] | None = None) -> list[str]:
    """Problems/warnings found before writing, each prefixed with a stable tag:
    OVERSELL (always checked on the rows alone, independent of `holdings`), GROSS_MISMATCH (qty×price vs gross
    > 0.01 EGP), FEE_DIFF (vs fees_config), HOLDINGS_MISMATCH (only when `holdings` is given) and
    PERIOD_OVERLAP (a warning: earlier import ids whose (from, to) overlaps → rows get review_flag
    POSSIBLE_DUPLICATE and Ahmed confirms; overlapping imports are allowed so older statements can be added).
    Position rows (transfer/bonus/IPO/split) change share counts for OVERSELL but are never BUY lots."""
    from fees_config import order_fees

    problems: list[str] = []
    held: dict[str, int] = {}
    for r in rows:
        t = r.get("ticker")
        if r.get("event_type") == "position":
            held[t] = held.get(t, 0) + (-1 if r.get("kind") == "transfer_out" else 1) * int(r.get("qty") or 0)
            continue
        if r.get("side") not in ("BUY", "SELL"):
            continue
        qty, price, gross = int(r["qty"]), Decimal(str(r["price"])), Decimal(str(r["gross_value"]))
        if abs(qty * price - gross) > CENT:
            problems.append(f"GROSS_MISMATCH row {r.get('row_no')} {t}: {qty}×{price} = {qty * price} vs gross {gross}")
        held[t] = held.get(t, 0) + (qty if r["side"] == "BUY" else -qty)
        if held[t] < 0:
            problems.append(f"OVERSELL row {r.get('row_no')} {t}: sells {qty}, open position in these rows {held[t] + qty}")
            held[t] = 0
        if r.get("total_fees") not in (None, ""):
            cfg = Decimal(str(sum(order_fees(float(gross)).values()))).quantize(CENT, ROUND_HALF_UP)
            fee = Decimal(str(r["total_fees"]))
            if abs(fee - cfg) > CENT:
                problems.append(f"FEE_DIFF row {r.get('row_no')} {t}: statement {fee} vs fees_config {cfg} ({fee - cfg:+})")
    if holdings is not None:
        for t in sorted(set(held) | set(holdings)):
            if held.get(t, 0) != holdings.get(t, 0):
                problems.append(f"HOLDINGS_MISMATCH {t}: rows {held.get(t, 0)} vs holdings {holdings.get(t, 0)}")
    if earlier_periods and period:
        hits = [i for i, f, to in earlier_periods if f <= period[1] and period[0] <= to]
        if hits:
            problems.append(f"PERIOD_OVERLAP with imports {hits}")
    return problems


def _db_float(x: Any) -> Any:
    # ponytail: schema frozen with REAL money columns; values are 2-decimal Decimals, exact after round(x, 2) on read.
    # Upgrade path (design note "Money storage"): integer piasters through an explicit migration.
    return float(x) if isinstance(x, Decimal) else x


def import_file(path: Path, db_path: Path | None = None, *, accept: tuple[str, ...] = ()) -> int:
    """detect → parse → validate → write imports/raw_rows/fills/cash_events in one transaction; returns import id.
    A blocking problem (OVERSELL, GROSS_MISMATCH, HOLDINGS_MISMATCH) stops the import unless Ahmed accepts its tag via
    `accept` (e.g. the first statement sells shares bought before its period)."""
    from contextlib import closing

    from personal_journal import db as ledger_db

    path = Path(path)
    fmt = detect_format(path)
    parsed = parse_pdf(path) if fmt == "pdf" else {"header": {}, "rows": parse_rows(path, fmt)}
    rows, header = parsed["rows"], parsed["header"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    db_path = ledger_db.init_db(db_path or ledger_db.DB_PATH)
    with closing(sqlite3.connect(db_path)) as con:
        if con.execute("SELECT id FROM imports WHERE sha256 = ?", (digest,)).fetchone():
            raise ValueError(f"{path.name}: already imported (sha256)")
        earlier = con.execute("SELECT id, period_from, period_to FROM imports WHERE period_from IS NOT NULL").fetchall()
        period = (header["period_from"], header["period_to"]) if "period_from" in header else None
        problems = validate_balance(rows, earlier_periods=earlier, period=period)
        blocking = [p for p in problems if p.split()[0] in BLOCKING and p.split()[0] not in accept]
        if blocking:
            raise ValueError(f"{path.name}: not imported —\n" + "\n".join(blocking))
        overlap = next((p for p in problems if p.startswith("PERIOD_OVERLAP")), None)
        flag = "POSSIBLE_DUPLICATE" if overlap else None
        with con:  # one transaction: all rows or nothing
            iid = con.execute("INSERT INTO imports (file_name, sha256, imported_at, period_from, period_to, row_count, "
                              "overlaps_imports) VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (path.name, digest, datetime.now().astimezone().isoformat(timespec="seconds"),
                               header.get("period_from"), header.get("period_to"), len(rows),
                               overlap.split("imports ", 1)[1] if overlap else None)).lastrowid
            for r in rows:
                if r["event_type"] != "fill":
                    raise ValueError(f"row {r['row_no']}: event type {r['event_type']} not mapped yet")
                con.execute("INSERT INTO raw_rows VALUES (?, ?, ?)", (iid, r["row_no"], json.dumps(
                    {k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()}, ensure_ascii=False)))
                # the statement gives a date only: ts_cairo = that date, no invented time; fee components unknown → NULL
                con.execute("INSERT INTO fills (import_id, row_no, ts_cairo, ticker, side, qty, price, gross_value, "
                            "total_fees, review_flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (iid, r["row_no"], r["ts_cairo"] or r["trade_date"], r["ticker"], r["side"], r["qty"],
                             _db_float(r["price"]), _db_float(r["gross_value"]), _db_float(r["total_fees"]), flag))
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / f"ledger_import_{datetime.now():%Y%m%d}.log").open("a", encoding="utf-8") as f:
        f.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} import {path.name} -> id {iid}, {len(rows)} rows, "
                f"accepted={list(accept)}\n" + "\n".join(problems) + "\n")
    fee_report(rows, path.name)
    return iid


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(HERE.parent))
    p = Path(sys.argv[1])
    fmt = detect_format(p)
    parsed = parse_pdf(p) if fmt == "pdf" else {"header": {}, "rows": parse_rows(p, fmt)}
    print(f"format={fmt} header={ {k: str(v) for k, v in parsed['header'].items()} }")
    print("\n".join(fee_report(parsed["rows"], p.name)))
    print("\n".join(validate_balance(parsed["rows"])) or "validate_balance: no problems")
