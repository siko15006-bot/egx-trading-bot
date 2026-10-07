"""Thndr PDF statement parser + ledger import (personal_journal/). personal_journal/tests/ is Codex's frozen suite, so
the parser's own checks live here. Real statements are private (gitignored): those cases skip when absent, and only
synthetic numbers appear in this file."""
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from personal_journal import db as ledger_db
from personal_journal import import_statement as st

STATEMENTS = Path(__file__).parent / "personal_journal" / "statements"
REAL = STATEMENTS / "E-STATEMENT_Jul_2026_01.pdf"
REAL_AUG = STATEMENTS / "E-STATEMENT_Aug_2026_01.pdf"
_M = str.maketrans("()", ")(")


def _visual(logical: str) -> str:
    """Inverse of st._logical for plain (non-presentation-form) Arabic: what pdfplumber would hand the parser."""
    return " ".join(w[::-1].translate(_M) if st._ARABIC.search(w) else w for w in reversed(logical.split()))


def _parse(*lines: str, opening="100", closing):
    head = [f"إسم العميل س رصيد أول المدة {opening}", f"من 1/10/2026 إلى 31/10/2026 رصيد آخر المدة {closing}"]
    return st.parse_lines([_visual(x) for x in head + list(lines)], Path("synthetic.pdf"))


def test_visual_rtl_line_becomes_logical_text() -> None:
    # pdfplumber output for a description: words in visual order, letters reversed, presentation forms + lam-alef ligature
    assert st._logical("تﻻﺎﺼﺗﻼﻟ ﺔﻳﺮﺼﻤﻟا ﺔﻛﺮﺸﻟا ﻊﻴﺑ") == "بيع الشركة المصرية للاتصالات"
    assert st._logical("(ﺮﺼﻣ) ﻲﻟوﺪﻟا") == "الدولي (مصر)"
    assert st._logical(_visual("5/10/2026 شراء مصر للالومنيوم 10.0000@5) ( -50.5 49.5")) == \
        "5/10/2026 شراء مصر للالومنيوم 10.0000@5) ( -50.5 49.5"


def test_company_key_ignores_spacing_brackets_and_variants() -> None:
    assert st._key("البنك التجاري الدولي (مصر)") == st._key("البنك  التجارى الدولى مصر")
    assert st._names()[st._key("الشركة المصرية للاتصالات")] == "ETEL.CA"


def test_detect_format_by_content(tmp_path) -> None:
    (tmp_path / "a.pdf").write_text("Date,Close\n2026-01-01,1\n")
    (tmp_path / "b.csv").write_bytes(b"%PDF-1.4 ...")
    assert st.detect_format(tmp_path / "a.pdf") == "csv" and st.detect_format(tmp_path / "b.csv") == "pdf"
    (tmp_path / "c.bin").write_bytes(b"\x00\x01binary")
    with pytest.raises(ValueError):
        st.detect_format(tmp_path / "c.bin")


def test_expected_fees_match_fees_config_components() -> None:
    # hand-computed for 1,000 EGP: brokerage 2 + 1.00, EGX 0.10, MCDR 0.10, FRA min 1.00, insurance 0.05, stamp 0.50
    e = st.expected_fees(Decimal("1000"))
    assert (e["full"], e["no_stamp"], e["brokerage"]) == (Decimal("4.75"), Decimal("4.25"), Decimal("3.00"))


def test_main_account_row_types_and_refund_link() -> None:
    p = _parse("1/10/2026 ايداع / بنك بنك مصر - المعادى 1,000 1,100",
               "2/10/2026 شراء مصر للالومنيوم 100.0000@10) ( -1,004.75 95.25",
               "2/10/2026 رد العمولة شراء مصر للالومنيوم 100.0000@10) ( 3 98.25",
               "3/10/2026 2026-10-03 TRADER رسوم اشتراك -50 48.25",
               "4/10/2026 تحويل إلى حساب الوثائق -40 8.25",
               "5/10/2026 تحويل من حساب الوثائق 1.75 10", closing="10")
    rows = p["rows"]
    assert p["account"] == "main"
    assert [r.get("kind", r["event_type"]) for r in rows] == [
        "deposit", "fill", "commission_refund", "subscription_fee", "transfer_to_fund", "transfer_from_fund"]
    fill = rows[1]
    assert (fill["ticker"], fill["qty"], fill["price"], fill["total_fees"], fill["refund"]) == \
        ("EGAL.CA", 10, Decimal("100.0000"), Decimal("4.75"), Decimal("3"))
    assert rows[2]["for_row"] == 2
    assert not st.validate_balance(rows)   # fee = fees_config, refund = brokerage (3.00 on 1,000)


def test_fund_account_rows_go_to_funds_and_transfers_are_mirrors() -> None:
    p = _parse("9/10/2026 بيع thndrsavings (جنيه (10@1.5 15 15",
               "9/10/2026 تحويل من حساب الوثائق -15 0", opening="0", closing="0")
    assert p["account"] == "fund"
    fund, mirror = p["rows"]
    assert (fund["event_type"], fund["fund_code"], fund["operation"], fund["units"], fund["value"]) == \
        ("fund", "thndrsavings", "SELL", Decimal("10"), Decimal("15"))
    assert mirror["event_type"] == "fund_transfer"   # the main account records the cash; this is audit only


def test_unknown_rows_stop_the_parser() -> None:
    with pytest.raises(ValueError, match="row type"):
        _parse("1/10/2026 توزيعات كوبون 5 105", closing="105")
    with pytest.raises(ValueError, match="fund 'xyz'"):
        _parse("1/10/2026 بيع xyz (جنيه (1@5 5 105", closing="105")
    with pytest.raises(ValueError, match="هيبكو"):   # listed as unresolved: stop and ask, never guess
        _parse("1/10/2026 شراء هيبكو للاستثمارات التجارية والتنمية العقارية 10.0000@1) ( -13.01 86.99", closing="86.99")
    with pytest.raises(ValueError, match="does not reconcile"):
        _parse("1/10/2026 ايداع / بنك بنك مصر 10 111", closing="111")


def _fill(row_no, ticker, side, qty, price, fees="3.00", gross=None, **extra):
    price = Decimal(price)
    return {"row_no": row_no, "event_type": "fill", "ticker": ticker, "side": side, "qty": qty, "price": price,
            "gross_value": Decimal(gross) if gross else qty * price, "total_fees": Decimal(fees), **extra}


def test_validate_balance_tags() -> None:
    rows = [_fill(1, "AAA.CA", "BUY", 10, "10"), _fill(2, "AAA.CA", "SELL", 15, "11"),       # oversell by 5
            _fill(3, "BBB.CA", "BUY", 10, "10", gross="100.02")]                              # gross off by 0.02
    tags = [p.split()[0] for p in st.validate_balance(rows)]
    assert "OVERSELL" in tags and "GROSS_MISMATCH" in tags
    assert not any(p.startswith("OVERSELL")                                                   # shares from earlier imports
                   for p in st.validate_balance(rows[1:2], opening_positions={"AAA.CA": 15}))
    ok = [_fill(1, "AAA.CA", "BUY", 100, "10", fees="4.75")]
    assert not st.validate_balance(ok)
    assert not st.validate_balance([_fill(1, "AAA.CA", "BUY", 100, "10", fees="4.73")])      # 0.02 = rounding (Ahmed)

    def tag(**kw):
        return st.validate_balance([_fill(1, "AAA.CA", "BUY", 100, "10", **kw)])[0].split()[0]
    assert tag(fees="4.25") == "FEE_NO_STAMP"                                                 # the July 2026 exception
    assert tag(fees="5.76", company_ar="وثائق صندوق المصريين") == "FUND_DOCUMENT_FEE"
    assert tag(fees="9.00") == "FEE_DIFF"
    assert tag(fees="4.75", refund=Decimal("2.50")) == "REFUND_DIFF"                          # brokerage is 3.00
    assert any(p.startswith("HOLDINGS_MISMATCH") for p in st.validate_balance(ok, holdings={"AAA.CA": 9}))
    assert st.validate_balance(ok, earlier_periods=[(7, "2026-07-01", "2026-07-31")],
                               period=("2026-07-15", "2026-08-15"))[-1] == "PERIOD_OVERLAP with imports [7]"


def test_migration_keeps_rows_and_adds_funds(tmp_path) -> None:
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as con:   # a v0 ledger with one cash row
        con.executescript(ledger_db.SCHEMA)
        con.execute("INSERT INTO imports (file_name, sha256, imported_at, row_count) VALUES ('x', 'h', 't', 1)")
        con.execute("INSERT INTO cash_events (import_id, row_no, ts_cairo, kind, amount) VALUES (1, 1, 'd', 'deposit', 5)")
    ledger_db.init_db(db)
    ledger_db.init_db(db)   # idempotent
    with sqlite3.connect(db) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == len(ledger_db.MIGRATIONS)
        assert con.execute("SELECT kind, amount FROM cash_events").fetchall() == [("deposit", 5.0)]
        con.execute("INSERT INTO cash_events (import_id, row_no, ts_cairo, kind, amount) VALUES (1, 2, 'd', 'commission_refund', 1)")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO cash_events (import_id, row_no, ts_cairo, kind, amount) VALUES (1, 3, 'd', 'bogus', 1)")
        con.execute("INSERT INTO fund_holdings (import_id, row_no, date, fund_code, operation, units, value) "
                    "VALUES (1, 1, 'd', 'thndrgold', 'BUY', 0.5, 1)")   # fractional units allowed


@pytest.mark.skipif(not REAL.exists(), reason="real statement is private (gitignored)")
def test_july_statement_parses_and_reconciles() -> None:
    parsed = st.parse_pdf(REAL)   # private numbers stay out of git: check properties, not values
    rows = parsed["rows"]
    assert rows and all(r["ticker"].endswith(".CA") and r["side"] in ("BUY", "SELL") and r["qty"] > 0 for r in rows)
    assert all(r["total_fees"] == st.expected_fees(r["gross_value"])["no_stamp"] for r in rows)   # July: no stamp
    assert parsed["header"]["opening_balance"] + sum(r["amount"] for r in rows) == parsed["header"]["closing_balance"]
    assert st.parse_rows(REAL, "pdf") == rows


def test_unknown_company_is_an_error_not_a_guess(monkeypatch, tmp_path) -> None:
    if not REAL.exists():
        pytest.skip("real statement is private (gitignored)")
    names = tmp_path / "names.json"
    names.write_text('{"companies": {"البنك التجاري الدولي (مصر)": "COMI.CA"}}', encoding="utf-8")
    monkeypatch.setattr(st, "NAMES_FILE", names)
    with pytest.raises(ValueError, match="not mapped"):
        st.parse_pdf(REAL)


@pytest.mark.skipif(not (REAL.exists() and REAL_AUG.exists()), reason="real statements are private (gitignored)")
def test_import_chain_positions_and_duplicates(tmp_path) -> None:
    db = tmp_path / "ledger.db"
    with pytest.raises(ValueError, match="OVERSELL"):           # sells of shares bought before the period
        st.import_file(REAL, db)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0   # nothing half-written
    st.import_file(REAL, db, accept=("OVERSELL",))
    st.import_file(REAL_AUG, db)   # its sell of a July buy is covered by the ledger's positions; chain must hold
    with sqlite3.connect(db) as con:
        (a, b), = [con.execute("SELECT (SELECT closing_balance FROM imports WHERE id=1), "
                               "(SELECT opening_balance FROM imports WHERE id=2)").fetchone()]
        n_raw = con.execute("SELECT COUNT(*) FROM raw_rows WHERE import_id=2").fetchone()[0]
        n_typed = con.execute("SELECT (SELECT COUNT(*) FROM fills WHERE import_id=2) + "
                              "(SELECT COUNT(*) FROM cash_events WHERE import_id=2)").fetchone()[0]
    assert a == b and n_raw == n_typed == len(st.parse_pdf(REAL_AUG)["rows"])
    with pytest.raises(ValueError, match="already imported"):
        st.import_file(REAL_AUG, db)


@pytest.mark.skipif(not REAL_AUG.exists(), reason="real statement is private (gitignored)")
def test_chain_break_blocks(tmp_path) -> None:
    db = ledger_db.init_db(tmp_path / "ledger.db")
    with sqlite3.connect(db) as con:   # a fake July import whose closing balance differs from August's opening
        con.execute("INSERT INTO imports (file_name, sha256, imported_at, period_from, period_to, row_count, account, "
                    "opening_balance, closing_balance) VALUES ('fake', 'h', 't', '2026-07-01', '2026-07-31', 0, 'main', 0, 1)")
    with pytest.raises(ValueError, match="CHAIN_BREAK"):
        st.import_file(REAL_AUG, db, accept=("OVERSELL",))
