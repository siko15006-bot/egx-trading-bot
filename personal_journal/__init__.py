"""Personal trading ledger (Ahmed's real Thndr trades). Design: docs/personal_ledger_design.md.

Isolated from the trading system: own SQLite file (personal_ledger.db, gitignored), no imports from production
modules except fees_config (to recompute Thndr fees). Parser logic waits for a real statement.
"""
