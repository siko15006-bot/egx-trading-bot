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
    def test_trade_lifecycle_and_weekly_summary(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "paper.db"
            now = datetime.now(timezone.utc)
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
