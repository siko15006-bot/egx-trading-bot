from __future__ import annotations

import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_trading import (
    PAPER_TARGET_DAYS,
    PAPER_TARGET_TRADES,
    PaperTradeInput,
    add_paper_trade,
    campaign_progress,
    close_paper_trade,
    format_close_message,
    format_open_message,
    format_weekly_message,
    load_paper_trades,
    weekly_performance,
)


class PaperTradingTest(unittest.TestCase):
    def test_weekly_boundary_is_cairo_sunday(self) -> None:
        # Cairo is UTC+3: Sat 21:30 UTC is already Sunday 00:30 in Cairo, so it starts the next EGX week.
        import pandas as pd
        trades = pd.DataFrame({"exit_time": pd.to_datetime([
            "2026-10-10T20:59:00Z",   # Sat 23:59 Cairo -> week of Sun 2026-10-04
            "2026-10-10T21:30:00Z",   # Sun 00:30 Cairo -> week of Sun 2026-10-11
        ], utc=True), "status": ["CLOSED", "CLOSED"], "pnl_egp": [1.0, 2.0], "pnl_pct": [0.1, 0.2],
            "outcome": ["WIN", "WIN"], "r_multiple": [1.0, 1.0]})
        old, _, old_start, _ = weekly_performance(trades, datetime(2026, 10, 10).date())
        new, _, new_start, _ = weekly_performance(trades, datetime(2026, 10, 11).date())
        self.assertEqual((str(old_start), list(old["pnl_egp"])), ("2026-10-04", [1.0]))
        self.assertEqual((str(new_start), list(new["pnl_egp"])), ("2026-10-11", [2.0]))

    def test_trade_lifecycle_and_weekly_summary(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "paper.db"
            # Fixed Wednesday noon Cairo: the week is Cairo-based (Sun..Sat), so a wall-clock UTC date
            # failed every Saturday 21:00-24:00 UTC (already Sunday in Cairo).
            now = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
            trade_id = add_paper_trade(
                PaperTradeInput(
                    ticker="COMI",
                    entry_time=now - timedelta(days=1),
                    entry=100.0,
                    shares=10,
                    stop_loss=90.0,
                    take_profit=120.0,
                    mirrors=4,
                    setup="4 Mirrors",
                ),
                db_path,
            )
            open_trades = load_paper_trades(db_path)
            open_week, open_summary, _, _ = weekly_performance(open_trades, now.date())
            self.assertTrue(open_week.empty)
            self.assertEqual(open_summary["trades"], 0)
            result = close_paper_trade(trade_id, now, 110.0, db_path)
            trades = load_paper_trades(db_path)
            weekly, summary, _, _ = weekly_performance(trades, now.date())

            self.assertEqual(trade_id, 1)
            self.assertEqual(result["outcome"], "WIN")
            self.assertEqual(trades.iloc[0]["status"], "CLOSED")
            self.assertEqual(len(weekly), 1)
            self.assertEqual(summary["trades"], 1)
            self.assertTrue(math.isclose(float(result["pnl_egp"]), 81.2925, abs_tol=1e-6))
            campaign = campaign_progress(db_path)
            day_ten = campaign_progress(db_path, campaign["start_date"] + timedelta(days=9))
            self.assertEqual(day_ten["elapsed_days"], 10)
            self.assertEqual(day_ten["remaining_days"], PAPER_TARGET_DAYS - 10)
            self.assertEqual(day_ten["target_trades"], PAPER_TARGET_TRADES)
            self.assertEqual(day_ten["closed_trades"], 1)
            trade = trades.iloc[0]
            self.assertIn("Paper Trade Opened", format_open_message(trade))
            self.assertIn("Paper Trade Closed", format_close_message(trade, result))
            self.assertIn("Weekly Review", format_weekly_message(summary, now.date(), now.date()))


if __name__ == "__main__":
    unittest.main()
