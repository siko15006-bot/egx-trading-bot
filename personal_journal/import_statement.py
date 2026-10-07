"""Thndr statement import (docs/personal_ledger_design.md, "Parser").

Real format (E-STATEMENT_<Mon>_<YYYY>_<NN>.pdf): a PDF "كشف حساب عميل" with columns التاريخ (d/m/yyyy, no time) |
الوصف | القيمة (net cash, fees merged) | رصيد (running balance), plus opening/closing balance and period in the header.
_01 = main (stock) account, _02 = fund sub-account ("حساب الوثائق"). Row types (description, after RTL repair):
  بيع|شراء <company> (qty@price)        → fill (ticker from company_names.json; fees = gross − net)
  رد العمولة بيع|شراء <company> (q@p)    → cash commission_refund (subscription from 2026-09-24: brokerage refunded)
  ايداع / بنك …                          → cash deposit
  <date> TRADER رسوم اشتراك             → cash subscription_fee
  تحويل … حساب الوثائق | الحساب الرئيسي  → main account: cash transfer_to_fund / transfer_from_fund (by sign);
                                            fund account: mirror of that transfer, kept in raw_rows only
  بيع|شراء <fund code> (جنيه (units@price → fund_holdings (units, not shares; no fees, no FIFO)
Every row must reconcile with the running and closing balance. Anything unknown (row type, company, fund) is an
error, never a guess. CSV/XLSX: no real Thndr export seen yet (Codex's CSV fixtures stay skipped).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

Format = Literal["csv", "xlsx", "pdf"]

HERE = Path(__file__).resolve().parent
NAMES_FILE = HERE / "company_names.json"
LOG_DIR = HERE.parent / "logs"
CENT = Decimal("0.01")
FEE_TOLERANCE = Decimal("0.02")  # Ahmed 2026-10-07: a 0.02 gap (HEBCO 27/9) is rounding, not a finding

_ARABIC = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")
_MIRROR = str.maketrans("()", ")(")
_ROW = re.compile(r"^(?P<date>\d{1,2}/\d{1,2}/\d{4}) (?P<desc>.+) (?P<amt>-?[\d,]+(?:\.\d+)?) (?P<bal>-?[\d,]+(?:\.\d+)?)$")
_QP = re.compile(r"([\d.]+)@([\d.]+)")
_SIDE = {"بيع": "SELL", "شراء": "BUY"}


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


def _names_file() -> dict[str, Any]:
    return json.loads(NAMES_FILE.read_text(encoding="utf-8"))


def _names() -> dict[str, str]:
    return {_key(k): v for k, v in _names_file()["companies"].items()}


def _money(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _iso(d: str) -> str:
    return datetime.strptime(d, "%d/%m/%Y").date().isoformat()


def _stock(prefix: str, a: str, b: str, path: Path) -> tuple[str, str, int, Decimal]:
    side_word, _, company = prefix.partition(" ")
    if side_word not in _SIDE:
        raise ValueError(f"{path.name}: unknown operation {side_word!r} in {prefix!r}")
    if ("." in a) == ("." in b):
        raise ValueError(f"{path.name}: cannot tell qty from price in {a}@{b}")
    price_s, qty_s = (a, b) if "." in a else (b, a)   # price is printed with 4 decimals, qty is an integer
    return _SIDE[side_word], company.strip(" ()"), int(qty_s), Decimal(price_s)


def parse_pdf(path: Path) -> dict[str, Any]:
    """{'header': {...}, 'account': 'main'|'fund', 'rows': [...]} — every row reconciles or ValueError."""
    import pdfplumber  # requirements_analytics.txt

    path = Path(path)
    with pdfplumber.open(path) as pdf:
        visual = [ln for page in pdf.pages for table in page.extract_tables()
                  for cells in table for c in cells if c for ln in c.splitlines()]
        first_text = _logical((pdf.pages[0].extract_text() or "").splitlines()[0]) if pdf.pages else ""
    if "فاتورة" in first_text:
        raise ValueError(f"{path.name}: an invoice (contract note), not an account statement — separate parser, later")
    return parse_lines(visual, path)


def parse_lines(visual: list[str], path: Path) -> dict[str, Any]:
    """Classify and reconcile the statement's table lines (pdfplumber visual order); see the module docstring."""
    path = Path(path)
    names_raw = _names_file()
    companies, funds = _names(), names_raw.get("funds", {})
    unresolved = {_key(k): v for k, v in names_raw.get("_unresolved", {}).items()}
    header: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    unknown: list[str] = []
    for line in visual:
        logical = _logical(line)
        if m := re.search(r"رصيد أول المدة (-?[\d,.]+)", logical):
            header["opening_balance"] = _money(m[1])
        if m := re.search(r"رصيد آخر المدة (-?[\d,.]+)", logical):
            header["closing_balance"] = _money(m[1])
        if m := re.search(r"من (\d+/\d+/\d{4}) إلى (\d+/\d+/\d{4})", logical):
            header["period_from"], header["period_to"] = _iso(m[1]), _iso(m[2])
        m = _ROW.match(logical)
        if not m:
            continue
        desc, amount = m["desc"], _money(m["amt"])
        row: dict[str, Any] = {"row_no": len(rows) + 1, "trade_date": _iso(m["date"]), "ts_cairo": None,
                               "amount": amount, "balance": _money(m["bal"]), "description": desc, "raw": line}
        qp = _QP.search(desc)
        prefix = desc[:qp.start()].strip(" (") if qp else desc
        if qp and (fm := re.match(r"^(بيع|شراء) (\S+) \(جنيه", prefix)):
            code = fm[2]
            if code not in funds:
                unknown.append(f"fund {code!r}")
                continue
            units, unit_price = Decimal(qp[1]), Decimal(qp[2])
            if abs(abs(amount) - units * unit_price) > CENT:
                raise ValueError(f"{path.name}: fund row {desc!r}: units×price {units * unit_price} ≠ {abs(amount)}")
            row.update(event_type="fund", fund_code=code, fund_name=funds[code], operation=_SIDE[fm[1]],
                       units=units, unit_price=unit_price, value=abs(amount))
        elif qp:
            refund = prefix.startswith("رد العمولة ")
            side, company, qty, price = _stock(prefix.removeprefix("رد العمولة ").strip(), qp[1], qp[2], path)
            ticker = companies.get(_key(company))
            if ticker is None:
                note = unresolved.get(_key(company), "add it after checking the price")
                unknown.append(f"{company!r} ({note})")
                continue
            gross = (qty * price).quantize(CENT)
            row.update(ticker=ticker, company_ar=company, side=side, qty=qty, price=price, gross_value=gross)
            if refund:
                row.update(event_type="cash", kind="commission_refund")
            else:
                row.update(event_type="fill", total_fees=gross - amount if side == "SELL" else -amount - gross,
                           fees_source="derived: gross - net")
        elif desc.startswith("ايداع"):
            row.update(event_type="cash", kind="deposit")
        elif "رسوم اشتراك" in desc:
            row.update(event_type="cash", kind="subscription_fee")
        elif desc.startswith("تحويل") and ("حساب الوثائق" in desc or "الحساب الرئيسي" in desc):
            row.update(event_type="cash", kind="transfer_to_fund" if amount < 0 else "transfer_from_fund")
        else:
            unknown.append(f"row type {desc!r}")
            continue
        rows.append(row)
    if unknown:
        raise ValueError(f"{path.name}: not mapped — " + "; ".join(dict.fromkeys(unknown)))
    if "opening_balance" not in header or "closing_balance" not in header:
        raise ValueError(f"{path.name}: opening/closing balance not found — unknown layout")
    account = "fund" if any(r["event_type"] == "fund" for r in rows) else "main"
    for r in rows:  # the fund account's transfer rows mirror the main account's: audit trail only
        if account == "fund" and r.get("kind", "").startswith("transfer_"):
            r["event_type"] = "fund_transfer"
    running = header["opening_balance"]
    for r in rows:
        running += r["amount"]
        if running != r["balance"]:
            raise ValueError(f"{path.name}: row {r['row_no']} does not reconcile: {running} != {r['balance']}")
        if r["event_type"] == "fill" and r["total_fees"] < 0:
            raise ValueError(f"{path.name}: row {r['row_no']} negative derived fees {r['total_fees']}")
    if running != header["closing_balance"]:
        raise ValueError(f"{path.name}: rows sum to {running}, closing balance is {header['closing_balance']}")
    for r in rows:  # link each commission refund to its fill (same day, ticker, side, qty, price)
        if r.get("kind") == "commission_refund":
            fill = next((f for f in rows if f["event_type"] == "fill" and all(
                f[k] == r[k] for k in ("trade_date", "ticker", "side", "qty", "price"))), None)
            if fill is None:
                raise ValueError(f"{path.name}: refund row {r['row_no']} has no matching fill")
            fill["refund"], r["for_row"] = r["amount"], fill["row_no"]
    return {"header": header, "account": account, "rows": rows}


def parse_rows(path: Path, fmt: Format) -> list[dict[str, Any]]:
    """Statement rows → normalised dicts. Unknown column/row → error."""
    if fmt == "pdf":
        return parse_pdf(Path(path))["rows"]
    raise NotImplementedError(f"{fmt}: no real Thndr {fmt.upper()} export seen yet (the statement is a PDF)")


def expected_fees(value: Decimal) -> dict[str, Decimal]:
    """fees_config components, each rounded half-up to the piaster (matches Thndr's invoice line by line):
    'full' (with stamp), 'no_stamp' (July 2026 only, KNOWN_ISSUES) and 'brokerage' (refunded after 2026-09-24)."""
    from fees_config import order_fees

    parts = {k: Decimal(str(v)).quantize(CENT, ROUND_HALF_UP) for k, v in order_fees(float(value)).items()}
    full = sum(parts.values())
    return {"full": full, "no_stamp": full - parts["stamp"], "brokerage": parts["brokerage"]}


def fee_report(rows: list[dict[str, Any]], source: str) -> list[str]:
    """One line per fill: statement fee, refund, net, fees_config; appended to logs/ledger_import_*.log."""
    lines = []
    for r in rows:
        if r.get("event_type") != "fill":
            continue
        exp = expected_fees(r["gross_value"])
        refund = r.get("refund", Decimal(0))
        lines.append(f"{source} row {r['row_no']} {r['trade_date']} {r['ticker']} {r['side']} {r['qty']}@{r['price']} "
                     f"gross={r['gross_value']} fee={r['total_fees']} refund={refund} net={r['total_fees'] - refund} | "
                     f"fees_config={exp['full']} net_expected={exp['full'] - (exp['brokerage'] if refund else 0)}")
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / f"ledger_import_{datetime.now():%Y%m%d}.log").open("a", encoding="utf-8") as f:
        f.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} fee check {source}\n" + "\n".join(lines) + "\n")
    return lines


BLOCKING = ("OVERSELL", "GROSS_MISMATCH", "HOLDINGS_MISMATCH", "CHAIN_BREAK")
# warnings: FEE_DIFF, FEE_NO_STAMP (the July 2026 exception), FUND_DOCUMENT_FEE, REFUND_DIFF, PERIOD_OVERLAP


def validate_balance(rows: list[dict[str, Any]], holdings: dict[str, int] | None = None,
                     *, earlier_periods: list[tuple[int, str, str]] | None = None,
                     period: tuple[str, str] | None = None,
                     opening_positions: dict[str, int] | None = None) -> list[str]:
    """Problems/warnings found before writing, each prefixed with a stable tag:
    OVERSELL (always checked on the rows alone, independent of `holdings`; `opening_positions` = shares already in the
    ledger from earlier imports), GROSS_MISMATCH (qty×price vs gross > 0.01 EGP), FEE_DIFF (vs fees_config, beyond
    0.02 — or FEE_NO_STAMP when it equals fees_config without stamp, FUND_DOCUMENT_FEE for fund certificates),
    REFUND_DIFF (commission refund ≠ brokerage), HOLDINGS_MISMATCH (only when `holdings` is given) and
    PERIOD_OVERLAP (a warning: earlier import ids whose (from, to) overlaps → rows get review_flag
    POSSIBLE_DUPLICATE and Ahmed confirms; overlapping imports are allowed so older statements can be added).
    Position rows (transfer/bonus/IPO/split) change share counts for OVERSELL but are never BUY lots."""
    problems: list[str] = []
    held: dict[str, int] = dict(opening_positions or {})
    for r in rows:
        t = r.get("ticker")
        if r.get("event_type") == "position":
            held[t] = held.get(t, 0) + (-1 if r.get("kind") == "transfer_out" else 1) * int(r.get("qty") or 0)
            continue
        if r.get("event_type") not in (None, "fill") or r.get("side") not in ("BUY", "SELL"):
            continue
        qty, price, gross = int(r["qty"]), Decimal(str(r["price"])), Decimal(str(r["gross_value"]))
        if abs(qty * price - gross) > CENT:
            problems.append(f"GROSS_MISMATCH row {r.get('row_no')} {t}: {qty}×{price} = {qty * price} vs gross {gross}")
        held[t] = held.get(t, 0) + (qty if r["side"] == "BUY" else -qty)
        if held[t] < 0:
            problems.append(f"OVERSELL row {r.get('row_no')} {t}: sells {qty}, open position {held[t] + qty}")
            held[t] = 0
        if r.get("total_fees") not in (None, ""):
            exp, fee = expected_fees(gross), Decimal(str(r["total_fees"]))
            if abs(fee - exp["full"]) > FEE_TOLERANCE:
                tag = ("FEE_NO_STAMP" if abs(fee - exp["no_stamp"]) <= CENT else
                       "FUND_DOCUMENT_FEE" if "وثائق صندوق" in str(r.get("company_ar", "")) else "FEE_DIFF")
                problems.append(f"{tag} row {r.get('row_no')} {t}: statement {fee} vs fees_config {exp['full']} "
                                f"({fee - exp['full']:+})")
            if "refund" in r and Decimal(str(r["refund"])) != exp["brokerage"]:
                problems.append(f"REFUND_DIFF row {r.get('row_no')} {t}: refund {r['refund']} vs brokerage {exp['brokerage']}")
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
    # ponytail: schema frozen with REAL money columns; values are ≤3-decimal Decimals, exact after rounding on read.
    # Upgrade path (design note "Money storage"): integer piasters through an explicit migration.
    return float(x) if isinstance(x, Decimal) else x


def import_file(path: Path, db_path: Path | None = None, *, accept: tuple[str, ...] = ()) -> int:
    """detect → parse → validate → write imports/raw_rows/fills/cash_events/fund_holdings in one transaction; returns
    import id. Blocking problems (OVERSELL, GROSS_MISMATCH, HOLDINGS_MISMATCH, CHAIN_BREAK) stop the import unless
    Ahmed accepts the tag via `accept` (e.g. the first statement sells shares bought before its period)."""
    from contextlib import closing

    from personal_journal import db as ledger_db

    path = Path(path)
    fmt = detect_format(path)
    parsed = parse_pdf(path) if fmt == "pdf" else {"header": {}, "account": None, "rows": parse_rows(path, fmt)}
    rows, header, account = parsed["rows"], parsed["header"], parsed["account"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    db_path = ledger_db.init_db(db_path or ledger_db.DB_PATH)
    with closing(sqlite3.connect(db_path)) as con:
        if con.execute("SELECT id FROM imports WHERE sha256 = ?", (digest,)).fetchone():
            raise ValueError(f"{path.name}: already imported (sha256)")
        earlier = con.execute("SELECT id, period_from, period_to FROM imports WHERE period_from IS NOT NULL "
                              "AND COALESCE(account, 'main') = ?", (account,)).fetchall()
        period = (header["period_from"], header["period_to"]) if "period_from" in header else None
        # shares already in the ledger; a negative net = sold out of a pre-ledger holding, so it counts as 0
        opening = {t: max(int(q), 0) for t, q in con.execute(
            "SELECT ticker, SUM(CASE side WHEN 'BUY' THEN qty ELSE -qty END) FROM fills GROUP BY ticker")}
        problems = validate_balance(rows, earlier_periods=earlier, period=period, opening_positions=opening)
        prev = con.execute("SELECT id, closing_balance FROM imports WHERE account = ? AND period_to < ? "
                           "ORDER BY period_to DESC LIMIT 1", (account, header.get("period_from", ""))).fetchone()
        if prev and prev[1] is not None and Decimal(str(prev[1])) != header["opening_balance"]:
            problems.append(f"CHAIN_BREAK opening {header['opening_balance']} ≠ closing {prev[1]} of import {prev[0]}")
        blocking = [p for p in problems if p.split()[0] in BLOCKING and p.split()[0] not in accept]
        if blocking:
            raise ValueError(f"{path.name}: not imported —\n" + "\n".join(blocking))
        overlap = next((p for p in problems if p.startswith("PERIOD_OVERLAP")), None)
        flag = "POSSIBLE_DUPLICATE" if overlap else None
        with con:  # one transaction: all rows or nothing
            iid = con.execute("INSERT INTO imports (file_name, sha256, imported_at, period_from, period_to, row_count, "
                              "overlaps_imports, account, opening_balance, closing_balance) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (path.name, digest, datetime.now().astimezone().isoformat(timespec="seconds"),
                               header.get("period_from"), header.get("period_to"), len(rows),
                               overlap.split("imports ", 1)[1] if overlap else None, account,
                               _db_float(header.get("opening_balance")), _db_float(header.get("closing_balance")))).lastrowid
            for r in rows:
                con.execute("INSERT INTO raw_rows VALUES (?, ?, ?)", (iid, r["row_no"], json.dumps(
                    {k: str(v) if isinstance(v, Decimal) else v for k, v in r.items()}, ensure_ascii=False)))
                day = r["ts_cairo"] or r["trade_date"]  # date only on the statement: no invented time
                if r["event_type"] == "fill":   # fee components unknown → NULL; refund is its own cash event
                    con.execute("INSERT INTO fills (import_id, row_no, ts_cairo, ticker, side, qty, price, gross_value, "
                                "total_fees, review_flag) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (iid, r["row_no"], day, r["ticker"], r["side"], r["qty"], _db_float(r["price"]),
                                 _db_float(r["gross_value"]), _db_float(r["total_fees"]), flag))
                elif r["event_type"] == "cash":
                    con.execute("INSERT INTO cash_events (import_id, row_no, ts_cairo, kind, ticker, amount, review_flag) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (iid, r["row_no"], day, r["kind"], r.get("ticker"), _db_float(r["amount"]), flag))
                elif r["event_type"] == "fund":
                    con.execute("INSERT INTO fund_holdings (import_id, row_no, date, fund_code, fund_name, operation, "
                                "units, unit_price, value, balance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (iid, r["row_no"], day, r["fund_code"], r["fund_name"], r["operation"],
                                 _db_float(r["units"]), _db_float(r["unit_price"]), _db_float(r["value"]),
                                 _db_float(r["balance"])))
                elif r["event_type"] != "fund_transfer":
                    raise ValueError(f"row {r['row_no']}: event type {r['event_type']} not mapped")
    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / f"ledger_import_{datetime.now():%Y%m%d}.log").open("a", encoding="utf-8") as f:
        f.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S} import {path.name} ({account}) -> id {iid}, {len(rows)} "
                f"rows, accepted={list(accept)}\n" + "\n".join(problems) + "\n")
    fee_report(rows, path.name)
    return iid


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(HERE.parent))
    p = Path(sys.argv[1])
    parsed = parse_pdf(p)
    print(f"account={parsed['account']} header={ {k: str(v) for k, v in parsed['header'].items()} }")
    print("\n".join(fee_report(parsed["rows"], p.name)))
    print("\n".join(validate_balance(parsed["rows"])) or "validate_balance: no problems")
