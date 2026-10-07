"""Acceptance tests against the existing isolated personal_journal placeholders.

No production imports/data/DB. Default exit=2 means parser NOT IMPLEMENTED,
not a passing parser. --fixtures-only runs fixture/schema checks separately.
"""
import csv
import hashlib
import importlib
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "sample_statements"
CASES = json.loads((SAMPLES / "cases.json").read_text(encoding="utf-8"))
# Adapted from Codex's outputs/ledger_test_design (2026-10-07): runs against the repo's personal_journal package
# instead of Codex's isolated reference copy. Test logic unchanged except the fill-identity case below.
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))
parser = importlib.import_module("personal_journal.import_statement")
portfolio = importlib.import_module("personal_journal.portfolio")
schema = importlib.import_module("personal_journal.db")
assert Path(parser.__file__).resolve().is_relative_to(REPO / "personal_journal")
assert Path(schema.__file__).resolve().is_relative_to(REPO / "personal_journal")


# Explicitly deferred work (Codex W8, 2026-10-08): only these may raise NotImplementedError and be SKIPPED.
# Any other NotImplementedError is a FAIL, so a function that silently stops working can never hide as a skip.
DEFERRED = {
    ("parse_rows", "csv"): "Thndr statements are PDF; no real CSV export seen yet — these fixtures are hypothetical",
    ("parse_rows", "xlsx"): "no real Thndr XLSX export seen yet",
    ("fifo_round_trips", None): "FIFO round trips: next step after the statements are complete",
    ("average_cost", None): "average cost: built with FIFO",
}


def deferred_reason(name, args):
    fmt = args[1] if name == "parse_rows" and len(args) > 1 else None
    return DEFERRED.get((name, fmt))


def invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except NotImplementedError as exc:
        reason = deferred_reason(function.__name__, args)
        if reason is None:
            raise AssertionError(f"unexpected NotImplementedError from {function.__name__}: {exc}") from exc
        raise unittest.SkipTest(f"DEFERRED: {function.__name__}: {reason}")


def dec(value):
    if isinstance(value, bool) or value is None:
        raise AssertionError("Missing/boolean money value")
    result = Decimal(str(value))
    if not result.is_finite():
        raise AssertionError("Non-finite money value")
    return result


class ParserAcceptance(unittest.TestCase):
    def assert_normalized(self, actual, expected):
        self.assertIsInstance(actual, list)
        self.assertEqual(len(actual), len(expected), "Do not drop, merge or invent statement rows")
        for row, target in zip(actual, expected):
            self.assertIsInstance(row, dict)
            for key, value in target.items():
                self.assertIn(key, row)
                if key in ("price", "gross_value", "total_fees", "amount"):
                    self.assertEqual(dec(row[key]), Decimal(value), f"{key}: preserve reported amounts")
                elif key == "ts_cairo":
                    stamp = datetime.fromisoformat(str(row[key]))
                    self.assertIsNotNone(stamp.tzinfo, "Timezone must be explicit")
                    self.assertEqual(stamp.isoformat(), value)
                    self.assertEqual(stamp.utcoffset(), stamp.astimezone(ZoneInfo("Africa/Cairo")).utcoffset())
                elif key in ("qty", "ratio_num", "ratio_den"):
                    self.assertIsInstance(row[key], int)
                    self.assertNotIsInstance(row[key], bool)
                    self.assertEqual(row[key], value)
                else:
                    self.assertEqual(row[key], value)
            if target.get("event_type") in ("cash", "position"):
                self.assertNotIn(row.get("side"), ("BUY", "SELL"), "Cash/corporate actions are not fictitious fills")
            if target.get("event_type") == "cash":
                self.assertIsNone(row.get("qty"), "Cash event must not invent a share quantity")
            if target.get("kind") in ("transfer_in", "transfer_out"):
                self.assertIsNone(row.get("cost_basis"), "Unknown transferred cost basis is not zero")
            if "ticker" in target and target["ticker"] is not None:
                self.assertEqual(row["ticker"].count(".CA"), 1)

    def run_case(self, case):
        path = SAMPLES / case["file"]
        before = path.read_bytes()
        if case["error"]:
            with self.assertRaisesRegex(ValueError, case["error"]):
                invoke(parser.parse_rows, path, "csv")
        else:
            result = invoke(parser.parse_rows, path, "csv")
            self.assert_normalized(result, case["expected"])
            if case["name"] == "partial_fills_three":
                self.assertEqual(sum(r["qty"] for r in result), 100)
                self.assertEqual(sum(dec(r["total_fees"]) for r in result), Decimal("9.06"))
                self.assertEqual(len({r["order_ref"] for r in result}), 1)
        self.assertEqual(path.read_bytes(), before, "Parsing must not edit statements")

    def test_detect_csv_by_content_not_extension(self):
        run_dir = ROOT / "test_runs"
        run_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=run_dir) as tmp:
            disguised = Path(tmp) / "statement.pdf"
            disguised.write_bytes((SAMPLES / "english_only.csv").read_bytes())
            self.assertEqual(invoke(parser.detect_format, disguised), "csv")

    def test_oversell_validation_requires_specific_problem(self):
        case = next(c for c in CASES if c["name"] == "oversell")
        rows = invoke(parser.parse_rows, SAMPLES / case["file"], "csv")
        self.assert_normalized(rows, case["expected"])
        problems = invoke(parser.validate_balance, rows)
        self.assertTrue(any("OVERSELL" in str(p) for p in problems),
                        "Proposed stable issue tag OVERSELL: a fee warning alone must not satisfy this test")

    def test_gross_mismatch_greater_than_one_piaster_reported(self):
        case = next(c for c in CASES if c["name"] == "gross_mismatch")
        rows = invoke(parser.parse_rows, SAMPLES / case["file"], "csv")
        problems = invoke(parser.validate_balance, rows)
        self.assertTrue(any("GROSS_MISMATCH" in str(p) for p in problems), "Proposed stable issue tag")

    def test_gross_exact_tolerance_not_rejected(self):
        case = next(c for c in CASES if c["name"] == "gross_tolerance_boundary")
        rows = invoke(parser.parse_rows, SAMPLES / case["file"], "csv")
        problems = invoke(parser.validate_balance, rows)
        self.assertFalse(any("GROSS_MISMATCH" in str(p) for p in problems),
                         "Other fee problems are allowed: this checks only the 0.01 gross boundary")

    def test_fifo_partial_sell_preserves_fees_and_open_cost(self):
        fills = [dict(ts_cairo="2026-10-05T12:00:00+03:00", ticker="ABUK.CA", side="BUY", qty=10,
                      price=Decimal("10.00"), gross_value=Decimal("100.00"), total_fees=Decimal("2.00")),
                 dict(ts_cairo="2026-10-06T12:00:00+03:00", ticker="ABUK.CA", side="BUY", qty=10,
                      price=Decimal("20.00"), gross_value=Decimal("200.00"), total_fees=Decimal("4.00")),
                 dict(ts_cairo="2026-10-07T12:00:00+03:00", ticker="ABUK.CA", side="SELL", qty=15,
                      price=Decimal("30.00"), gross_value=Decimal("450.00"), total_fees=Decimal("3.00"))]
        trips = invoke(portfolio.fifo_round_trips, fills)
        self.assertEqual(sum(t["qty"] for t in trips), 15)
        self.assertEqual(sum(dec(t["qty"]) * dec(t["avg_buy"]) for t in trips), Decimal("200.00"))
        self.assertEqual(sum(dec(t["qty"]) * dec(t["avg_sell"]) for t in trips), Decimal("450.00"))
        self.assertEqual(sum(dec(t["fees"]) for t in trips), Decimal("7.00"))
        self.assertEqual(dec(invoke(portfolio.average_cost, fills, "ABUK.CA")), Decimal("20.40"))


def attach_case(case):
    def test(self):
        self.run_case(case)
    test.__name__ = "test_" + case["name"]
    test.__doc__ = case["status"] + ": " + case["notes"]
    setattr(ParserAcceptance, test.__name__, test)


for scenario in CASES:
    attach_case(scenario)


class FixtureAndSchemaChecks(unittest.TestCase):
    def test_fixture_files_and_reference_are_isolated(self):
        names = [c["name"] for c in CASES]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 15)
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertFalse(manifest["real_statement_used"])
        self.assertFalse(manifest["personal_database_read_or_copied"])
        for case in CASES:
            path = SAMPLES / case["file"]
            self.assertTrue(path.resolve().is_relative_to(ROOT))
            content = path.read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), manifest["fixture_sha256"][case["file"]])
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader)
                rows = list(reader)
            self.assertEqual(len(rows), case["rows"])
            self.assertTrue(all(len(row) == len(header) for row in rows))
            if case["expected"] is not None:
                self.assertEqual(len(case["expected"]), len(rows))
        self.assertFalse(list(ROOT.rglob("*.db")), "No real or test ledger DB belongs next to the fixtures")

    def test_synthetic_expected_math_independent_of_parser(self):
        partial = next(c for c in CASES if c["name"] == "partial_fills_three")["expected"]
        self.assertEqual(sum(r["qty"] for r in partial), 100)
        self.assertEqual(sum(Decimal(r["total_fees"]) for r in partial), Decimal("9.06"))
        self.assertEqual(sum(Decimal(r["gross_value"]) for r in partial), Decimal("1010.00"))
        for case in CASES:
            for row in case["expected"] or []:
                if "side" in row and case["name"] not in ("gross_mismatch", "gross_tolerance_boundary"):
                    self.assertEqual(Decimal(row["qty"]) * Decimal(row["price"]), Decimal(row["gross_value"]))
        self.assertEqual(Decimal("100.01") - Decimal("100.00"), Decimal("0.01"))
        self.assertEqual(Decimal("100.02") - Decimal("100.00"), Decimal("0.02"))

    def test_schema_duplicate_file_sha256_is_rejected(self):
        with sqlite3.connect(":memory:") as con:
            con.executescript(schema.SCHEMA)
            query = "INSERT INTO imports(file_name,sha256,imported_at,row_count) VALUES(?,?,?,1)"
            con.execute(query, ("synthetic.csv", "SYNTHETIC-HASH", "2026-10-07"))
            with self.assertRaisesRegex(sqlite3.IntegrityError, r"UNIQUE constraint failed: imports.sha256"):
                con.execute(query, ("renamed.csv", "SYNTHETIC-HASH", "2026-10-07"))
            self.assertEqual(con.execute("SELECT count(*) FROM imports").fetchone()[0], 1)

    def test_schema_transaction_rollback_not_partial_import(self):
        con = sqlite3.connect(":memory:")
        try:
            con.executescript(schema.SCHEMA)
            con.execute("PRAGMA foreign_keys=ON")
            with self.assertRaisesRegex(sqlite3.IntegrityError, r"CHECK constraint failed: qty > 0"):
                with con:
                    con.execute("INSERT INTO imports(id,file_name,sha256,imported_at,row_count) VALUES(1,'synthetic.csv','SYN-HASH','2026-10-07',2)")
                    con.execute("INSERT INTO raw_rows VALUES(1,1,'{\"synthetic\":true}')")
                    con.execute("INSERT INTO fills(import_id,row_no,ts_cairo,ticker,side,qty,price,gross_value,total_fees) VALUES(1,2,'2026-10-05','ABUK.CA','BUY',-1,10,10,0)")
            self.assertEqual(con.execute("SELECT count(*) FROM imports").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT count(*) FROM raw_rows").fetchone()[0], 0)
        finally:
            con.close()

    def test_schema_identical_executions_are_both_kept(self):
        # Fill identity is (import_id, row_no): two genuine executions with the same day/ticker/qty/price are both
        # stored; only the same statement row twice is rejected (docs/personal_ledger_design.md, "Fill identity").
        with sqlite3.connect(":memory:") as con:
            con.executescript(schema.SCHEMA)
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("INSERT INTO imports(id,file_name,sha256,imported_at,row_count) VALUES(1,'synthetic.csv','SYN-IDENTITY','2026-10-07',2)")
            query = "INSERT INTO fills(import_id,row_no,ts_cairo,ticker,side,qty,price,gross_value,total_fees,order_ref) VALUES(1,?,'2026-10-05T12:00:00+03:00','ABUK.CA','BUY',10,10,100,3,'SYN-SAME')"
            con.execute(query, (1,))
            con.execute(query, (2,))
            self.assertEqual(con.execute("SELECT count(*) FROM fills").fetchone()[0], 2)
            with self.assertRaisesRegex(sqlite3.IntegrityError, r"UNIQUE constraint failed: fills.import_id, fills.row_no"):
                con.execute(query, (2,))


if __name__ == "__main__":
    fixtures_only = "--fixtures-only" in sys.argv
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FixtureAndSchemaChecks)
    if not fixtures_only:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ParserAcceptance))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
    if result.skipped:
        print("NOT IMPLEMENTED: parser/portfolio cases were skipped; this is NOT a parser pass.")
        sys.exit(2)
    if fixtures_only:
        print("Fixture/schema checks only. Actual parser and import_file were NOT validated.")
