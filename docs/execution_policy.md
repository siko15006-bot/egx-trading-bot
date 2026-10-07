# Execution policy — every simulated path

Applies to `egx_4_mirrors_v3.backtest`, `backtest_optimizer` (`simulate` in both modes, `simulate_d`), `auto_sim`, and
the H3 forward test. Implemented once in `egx_4_mirrors_v3` (`simulate_trade`, `stop_fill`, `target_fill`,
`is_filler`, `data_breaks`); the optimizer reuses the same helpers. Tests: `test_execution.py`, `test_auto_sim.py`.
Decided 2026-10-07 after Codex's adversarial audit and Thndr's confirmation of how its stop orders work.

## 1. Stop and target fills (Thndr stop order = market order once the level trades)

| Bar after entry | Stop (sell) | Target (sell) |
|---|---|---|
| Level touched inside the bar | fill **at the stop** | fill **at the target** |
| Bar opened beyond the level (gap) | fill **at the open**, if it is a real open | same |
| …but the open is not a real price | fill **at that bar's close** | same |

- "Real open" = within [Low, High] and different from the previous close. Yahoo's EGX Open equals the previous close
  on ~98% of traded bars and lies outside [Low, High] on ~18% (`KNOWN_ISSUES.md`), so most gaps fall back to the close.
  The close is a price that actually traded that day and assumes no intraday detail we don't have.
- The same bar touching both levels → stop first (conservative).
- Entry is always the **close of the session after the signal** (signals are computed after the close; the
  signal-day close is not executable). Exits are checked from the bar after the entry bar.
- Costs on every fill: Thndr fees (`fees_config.py`) + `RiskConfig.slippage_bps` per side (default 10, an
  assumption; validated 0..1000, a negative value would turn a flat trade into a profit).

## 2. Zero-volume rows (Yahoo filler)

A row with Volume 0 is a Yahoo gap, not a trading day: it is **never an entry, never an exit, and never moves the
trailing stop**. A trade whose entry bar is a filler row is skipped. (A positive-volume flat bar is a real bar.)

## 3. Data breaks (unadjusted or misdated corporate actions)

- A traded bar whose close moved beyond **±25% per elapsed session** from the previous traded close (×1.25^k up,
  ×0.75^k down; filler rows count as sessions) is a data break. EGX daily limits are ±20%, so a limit move is never
  a break; the threshold is symmetric in percentage terms.
- A trade open across a break is **cancelled**: outcome unknown (it may be a split with no real loss), so it is
  excluded from P&L, win rate and every statistic, and counted. It is never "closed" at an earlier price — that would
  be a sale dated before the evidence existed.
  - backtest: `result["data_break_trades"]`; the engine CLI (`--backtest`) writes `outputs/data_breaks_log.csv`.
  - optimizer `simulate`: `result["cancelled"]`; `simulate_d`: the position is undone (cash back to its cost);
    earlier equity-curve points still include its mark-to-market — a known limitation.
  - auto_sim: status `CANCELLED`, exit_reason `DATA_BREAK`, no P&L.
- The daily scanner reports `DATA_BREAK` instead of a signal for 60 bars after a break.
- Limits: the threshold is a price heuristic, not a corporate-action feed; two filler rows before a 40% drop dilute
  it enough to miss it.

## Other conventions

- End of window: backtests liquidate at the last close (`END`) and the final equity point includes those costs;
  auto_sim keeps the trade open (forward simulation). Compare their prices, not their statuses.
- A start date beyond the data returns empty results instead of crashing.
- The optimizer chooses its best scenario on `data/` only; 2022–2023 is an out-of-sample check on 9 large caps.
