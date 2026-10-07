"""Thndr PDF statement parser (personal_journal/import_statement.py). personal_journal/tests/ is Codex's frozen suite,
so the parser's own checks live here. The real statement is gitignored: that case skips when it is absent."""
from decimal import Decimal
from pathlib import Path

import pytest

from personal_journal import import_statement as st

REAL = Path(__file__).parent / "personal_journal" / "statements" / "E-STATEMENT_Jul_2026_01.pdf"


def test_visual_rtl_line_becomes_logical_text() -> None:
    # pdfplumber output for a description: words in visual order, letters reversed, presentation forms + lam-alef ligature
    assert st._logical("تﻻﺎﺼﺗﻼﻟ ﺔﻳﺮﺼﻤﻟا ﺔﻛﺮﺸﻟا ﻊﻴﺑ") == "بيع الشركة المصرية للاتصالات"
    assert st._logical("(ﺮﺼﻣ) ﻲﻟوﺪﻟا") == "الدولي (مصر)"


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


def test_observed_fee_formula() -> None:
    # 3 EGP + 0.125%, per piaster-rounded component, no stamp. Hand-computed (brokerage, EGX, MCDR, FRA min, insurance):
    # 400 → 2.40+0.04+0.04+1.00+0.02 = 3.50; 1000 → 3.00+0.10+0.10+1.00+0.05 = 4.25
    assert st.expected_fees(Decimal("400"), "2026-07-08")["observed"] == Decimal("3.50")
    assert st.expected_fees(Decimal("1000"), "2026-07-08")["observed"] == Decimal("4.25")
    assert st.expected_fees(Decimal("1000"), "2026-07-08")["fees_config"] == Decimal("4.75")   # + 0.05% stamp
    assert st.expected_fees(Decimal("1000"), "2026-09-24")["observed"] == Decimal("1.25")       # subscription: no brokerage


@pytest.mark.skipif(not REAL.exists(), reason="real statement is private (gitignored)")
def test_july_statement_parses_and_reconciles() -> None:
    parsed = st.parse_pdf(REAL)   # private numbers stay out of git: check properties, not values
    rows = parsed["rows"]
    assert rows and all(r["ticker"].endswith(".CA") and r["side"] in ("BUY", "SELL") and r["qty"] > 0 for r in rows)
    assert all(r["total_fees"] == st.expected_fees(r["gross_value"], r["trade_date"])["observed"] for r in rows)
    assert parsed["header"]["opening_balance"] + sum(r["amount"] for r in rows) == parsed["header"]["closing_balance"]
    assert st.parse_rows(REAL, "pdf") == rows


def test_unknown_company_is_an_error_not_a_guess(monkeypatch, tmp_path) -> None:
    if not REAL.exists():
        pytest.skip("real statement is private (gitignored)")
    names = tmp_path / "names.json"
    names.write_text('{"البنك التجاري الدولي (مصر)": "COMI.CA"}', encoding="utf-8")
    monkeypatch.setattr(st, "NAMES_FILE", names)
    with pytest.raises(ValueError, match="company not in company_names.json"):
        st.parse_pdf(REAL)
