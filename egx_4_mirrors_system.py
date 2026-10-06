from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


@dataclass(frozen=True)
class StrategyConfig:
    min_rows: int = 80
    min_price: float = 1.0
    min_avg_volume_20: float = 50_000
    min_avg_turnover_20: float = 1_000_000
    min_active_days_20: float = 0.80
    rsi_min: float = 50.0
    rsi_max: float = 70.0
    min_atr_pct: float = 0.015
    min_bb_width_pct: float = 0.035
    atr_stop_multiple: float = 1.5
    reward_risk: float = 2.0
    account_capital: float = 100_000
    risk_per_trade_pct: float = 0.01


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    rename = {c: c.strip().title() for c in df.columns}
    data = df.rename(columns=rename).copy()
    missing = REQUIRED_COLUMNS - set(data.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if "Date" in data.columns:
        data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
        data = data.sort_values("Date")
    for col in REQUIRED_COLUMNS:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data.dropna(subset=list(REQUIRED_COLUMNS)).reset_index(drop=True)


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = normalize_ohlcv(df)
    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"]

    data["EMA20"] = close.ewm(span=20, adjust=False).mean()
    data["EMA50"] = close.ewm(span=50, adjust=False).mean()
    data["EMA200"] = close.ewm(span=200, adjust=False).mean()
    data["RSI14"] = rsi(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    data["MACD"] = ema12 - ema26
    data["MACD_SIGNAL"] = data["MACD"].ewm(span=9, adjust=False).mean()
    data["MACD_HIST"] = data["MACD"] - data["MACD_SIGNAL"]

    data["VOLUME_SMA20"] = volume.rolling(20).mean()
    data["TURNOVER"] = close * volume
    data["TURNOVER_SMA20"] = data["TURNOVER"].rolling(20).mean()
    data["ACTIVE_DAYS_20"] = (volume > 0).rolling(20).mean()
    data["OBV"] = (np.sign(close.diff()).fillna(0) * volume).cumsum()
    data["OBV_SLOPE_5"] = data["OBV"].diff(5)

    data["BB_MID"] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    data["BB_UPPER"] = data["BB_MID"] + 2 * bb_std
    data["BB_LOWER"] = data["BB_MID"] - 2 * bb_std
    data["BB_WIDTH_PCT"] = (data["BB_UPPER"] - data["BB_LOWER"]) / close

    true_range = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["ATR14"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    data["ATR_PCT"] = data["ATR14"] / close
    return data


def evaluate_stock(df: pd.DataFrame, ticker: str, cfg: StrategyConfig = StrategyConfig()) -> dict:
    data = add_indicators(df)
    if len(data) < cfg.min_rows:
        return {"Ticker": ticker, "Signal": "SKIP", "Reason": "not_enough_history", "Rows": len(data)}

    last = data.iloc[-1]
    liquidity = (
        last["Close"] >= cfg.min_price
        and last["VOLUME_SMA20"] >= cfg.min_avg_volume_20
        and last["TURNOVER_SMA20"] >= cfg.min_avg_turnover_20
        and last["ACTIVE_DAYS_20"] >= cfg.min_active_days_20
    )
    trend = last["Close"] > last["EMA50"] and last["EMA20"] > last["EMA50"]
    momentum = cfg.rsi_min < last["RSI14"] < cfg.rsi_max and last["MACD_HIST"] > 0
    volume_ok = last["Volume"] > last["VOLUME_SMA20"] and last["OBV_SLOPE_5"] > 0
    volatility = (
        last["Close"] > last["BB_MID"]
        and last["ATR_PCT"] >= cfg.min_atr_pct
        and last["BB_WIDTH_PCT"] >= cfg.min_bb_width_pct
    )

    buy = liquidity and trend and momentum and volume_ok and volatility
    entry = float(last["Close"])
    atr = float(last["ATR14"])
    stop = entry - cfg.atr_stop_multiple * atr
    risk_per_share = entry - stop
    target = entry + cfg.reward_risk * risk_per_share
    max_risk_cash = cfg.account_capital * cfg.risk_per_trade_pct
    quantity = int(max_risk_cash // risk_per_share) if risk_per_share > 0 else 0

    return {
        "Ticker": ticker,
        "Signal": "BUY" if buy else "WAIT",
        "Close": round(entry, 3),
        "Checks": {
            "MarketScreener_Liquidity": bool(liquidity),
            "Mirror1_Trend": bool(trend),
            "Mirror2_Momentum": bool(momentum),
            "Mirror3_Volume": bool(volume_ok),
            "Mirror4_Volatility": bool(volatility),
        },
        "Metrics": {
            "RSI14": round(float(last["RSI14"]), 2),
            "ATR14": round(atr, 3),
            "ATR_PCT": round(float(last["ATR_PCT"]), 4),
            "AvgVolume20": round(float(last["VOLUME_SMA20"]), 0),
            "AvgTurnover20": round(float(last["TURNOVER_SMA20"]), 0),
            "BBWidthPct": round(float(last["BB_WIDTH_PCT"]), 4),
        },
        "RiskPlan": {
            "Entry": round(entry, 3),
            "StopLoss": round(stop, 3),
            "TakeProfit": round(target, 3),
            "RiskPerShare": round(risk_per_share, 3),
            "RewardRisk": f"1:{cfg.reward_risk:g}",
            "MaxRiskCash": round(max_risk_cash, 2),
            "PositionSizeShares": quantity,
            "PositionValue": round(quantity * entry, 2),
        },
    }


def load_universe(path: Path) -> dict[str, pd.DataFrame]:
    if path.is_dir():
        return {csv.stem: pd.read_csv(csv) for csv in sorted(path.glob("*.csv"))}
    df = pd.read_csv(path)
    ticker_col = next((c for c in df.columns if c.lower() in {"ticker", "symbol"}), None)
    if ticker_col:
        return {str(ticker): part.drop(columns=[ticker_col]) for ticker, part in df.groupby(ticker_col)}
    return {path.stem: df}


def scan_universe(universe: dict[str, pd.DataFrame], cfg: StrategyConfig = StrategyConfig()) -> pd.DataFrame:
    rows = [evaluate_stock(df, ticker, cfg) for ticker, df in universe.items()]
    flat_rows = []
    for row in rows:
        flat = {k: v for k, v in row.items() if not isinstance(v, dict)}
        for group in ("Checks", "Metrics", "RiskPlan"):
            for k, v in row.get(group, {}).items():
                flat[f"{group}.{k}"] = v
        flat_rows.append(flat)
    return pd.DataFrame(flat_rows).sort_values(["Signal", "Metrics.ATR_PCT"], ascending=[True, False])


def demo_data(periods: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = np.cumprod(1 + rng.normal(0.002, 0.018, periods)) * 50
    return pd.DataFrame(
        {
            "Date": pd.date_range(end=pd.Timestamp.today(), periods=periods),
            "Open": close * rng.uniform(0.99, 1.01, periods),
            "High": close * rng.uniform(1.005, 1.035, periods),
            "Low": close * rng.uniform(0.965, 0.995, periods),
            "Close": close,
            "Volume": rng.integers(60_000, 400_000, periods),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="EGX 4 Mirrors technical screener")
    parser.add_argument("path", nargs="?", help="CSV file or folder of CSV files")
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--risk", type=float, default=0.01, help="Risk per trade, e.g. 0.01 = 1%%")
    parser.add_argument("--out", default="", help="Optional output CSV path")
    args = parser.parse_args()

    cfg = StrategyConfig(account_capital=args.capital, risk_per_trade_pct=args.risk)
    universe = load_universe(Path(args.path)) if args.path else {"DEMO.CA": demo_data()}
    result = scan_universe(universe, cfg)
    pd.set_option("display.max_columns", 80)
    print(result.to_string(index=False))
    if args.out:
        result.to_csv(args.out, index=False, encoding="utf-8-sig")

    assert {"BUY", "WAIT", "SKIP"} & set(result["Signal"])


if __name__ == "__main__":
    main()
