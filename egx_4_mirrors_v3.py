from __future__ import annotations
from egx_lists import filter_universe, annotate, SECTOR_MAP as UNIVERSE_SECTORS
from fees_config import FeesConfig, THNDR_FEES, order_fees, round_trip_fees

import argparse
from dataclasses import dataclass
from math import floor, sqrt
from pathlib import Path
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


CAIRO_TZ = ZoneInfo("Africa/Cairo")
UTC_TZ = ZoneInfo("UTC")
REQUIRED_COLUMNS = ("Open", "High", "Low", "Close", "Volume")

SECTOR_MAP: Mapping[str, str] = {
    "COMI.CA": "Banks",
    "ADIB.CA": "Banks",
    "QNBE.CA": "Banks",
    "CIEB.CA": "Banks",
    "SAUD.CA": "Banks",
    "HRHO.CA": "Financials",
    "EFIH.CA": "Financials",
    "BTEX.CA": "Financials",
    "BTFH.CA": "Financials",
    "TMGH.CA": "RealEstate",
    "MNHD.CA": "RealEstate",
    "MASR.CA": "RealEstate",
    "OCDI.CA": "RealEstate",
    "PHDC.CA": "RealEstate",
    "SWDY.CA": "Industrial",
    "EAST.CA": "Industrial",
    "IRON.CA": "Industrial",
    "ABUK.CA": "Industrial",
    "ORAS.CA": "Industrial",
    "ETEL.CA": "Telecom",
    "ORWE.CA": "Telecom",
    "TAQA.CA": "Energy",
    "EKHO.CA": "Energy",
    "JUFO.CA": "Consumer",
    "CCAP.CA": "Consumer",
    "DOMT.CA": "Consumer",
    "FWRY.CA": "Technology",
    "RAYA.CA": "Technology",
    "ISPH.CA": "Healthcare",
    "PHAR.CA": "Healthcare",
    "NIPH.CA": "Healthcare",
    "SKPC.CA": "Chemicals",
    "MFPC.CA": "Chemicals",
    "EFIC.CA": "Chemicals",
    "SCTS.CA": "Transport",
    "ALCN.CA": "Transport",
    "GBCO.CA": "Automotive",
    "AMOC.CA": "Energy",
    "CIRA.CA": "Education",
    "MTIE.CA": "Distribution",
    "ACAMD.CA": "RealEstate",
}


SECTOR_MAP = {**SECTOR_MAP, **UNIVERSE_SECTORS}


@dataclass(frozen=True)
class ScreenConfig:
    min_rows: int = 60
    min_close: float = 1.0
    min_volume_sma20: float = 50_000
    min_value_sma20: float = 1_000_000
    min_active_days_20: int = 16


@dataclass(frozen=True)
class SignalConfig:
    max_gap_pct: float = 4.0
    min_adx: float = 20.0
    rsi_min: float = 50.0
    rsi_max: float = 70.0
    volume_multiplier: float = 1.2
    min_atr_pct: float = 1.5
    min_bb_width: float = 0.035


@dataclass(frozen=True)
class RiskConfig:
    capital: float = 100_000
    risk_pct: float = 0.01
    atr_sl_mult: float = 1.5
    reward_risk: float = 2.0
    # Explicit legacy per-side override, for controlled comparisons only.
    round_trip_fee_pct: float | None = None
    fees: FeesConfig = THNDR_FEES
    capital_gains_tax_pct: float = 0.10
    dividend_tax_pct: float = 0.10  # withheld at source on cash dividends, separate from capital gains tax
    max_position_pct: float = 0.20
    max_avg_volume_pct: float = 0.01


@dataclass(frozen=True)
class SystemConfig:
    screen: ScreenConfig = ScreenConfig()
    signal: SignalConfig = SignalConfig()
    risk: RiskConfig = RiskConfig()


@dataclass(frozen=True)
class TradePlan:
    ticker: str
    entry: float
    stop_loss: float
    take_profit: float
    atr: float
    shares: int
    risk_egp: float
    reward_egp: float
    rr_net: float
    position_value: float
    notes: str


def _require_ohlcv(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df index must be a DatetimeIndex")


def _clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    _require_ohlcv(df)
    data = df.copy().sort_index()
    for col in REQUIRED_COLUMNS:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data.dropna(subset=list(REQUIRED_COLUMNS))


def _wilder(series: pd.Series, period: int = 14) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False).mean()


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = _clean_ohlcv(df)
    close = data["Close"]
    high = data["High"]
    low = data["Low"]
    volume = data["Volume"]
    prev_close = close.shift(1)

    data["EMA_20"] = close.ewm(span=20, adjust=False).mean()
    data["EMA_50"] = close.ewm(span=50, adjust=False).mean()
    data["EMA_200"] = close.ewm(span=200, adjust=False).mean()
    data["EMA50_slope"] = data["EMA_50"].diff(5)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder(gain, 14)
    avg_loss = _wilder(loss, 14)
    rs = avg_gain / (avg_loss + 1e-9)
    data["RSI"] = 100 - (100 / (1 + rs))

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    data["MACD_line"] = ema12 - ema26
    data["MACD_Signal"] = data["MACD_line"].ewm(span=9, adjust=False).mean()
    data["MACD_Hist"] = data["MACD_line"] - data["MACD_Signal"]

    data["Volume_SMA20"] = volume.rolling(20).mean()
    data["Value_Traded"] = close * volume
    data["Value_SMA20"] = data["Value_Traded"].rolling(20).mean()

    data["OBV"] = (np.sign(close.diff()).fillna(0) * volume).cumsum()
    data["OBV_SMA20"] = data["OBV"].rolling(20).mean()

    data["BB_Mid"] = close.rolling(20).mean()
    data["BB_Std"] = close.rolling(20).std(ddof=0)
    data["BB_Upper"] = data["BB_Mid"] + 2 * data["BB_Std"]
    data["BB_Lower"] = data["BB_Mid"] - 2 * data["BB_Std"]
    data["BB_Width"] = (data["BB_Upper"] - data["BB_Lower"]) / data["BB_Mid"]
    data["BBW_SMA20"] = data["BB_Width"].rolling(20).mean()

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_wilder = _wilder(tr, 14)
    data["ATR"] = atr_wilder
    data["ATR_Pct"] = atr_wilder / close * 100

    high_diff = high.diff()
    low_diff = -low.diff()
    plus_dm = high_diff.where(high_diff > low_diff, 0).clip(lower=0)
    minus_dm = low_diff.where(low_diff > high_diff, 0).clip(lower=0)
    plus_di = 100 * (_wilder(plus_dm, 14) / (atr_wilder + 1e-9))
    minus_di = 100 * (_wilder(minus_dm, 14) / (atr_wilder + 1e-9))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    data["DI_Plus"] = plus_di
    data["DI_Minus"] = minus_di
    data["DX"] = dx
    data["ADX"] = _wilder(dx, 14)

    cairo_days = (
        pd.Index(data.index.tz_convert(CAIRO_TZ).date)
        if data.index.tz is not None
        else pd.Index(data.index.date)
    )
    # v3: VWAP يومي حقيقي — تجميع حسب تاريخ القاهرة، ويبدأ من جديد كل يوم: cumsum(Close×Volume)/cumsum(Volume) لكل يوم.
    # (v2 كان على البيانات اليومية بيحسب VWAP تراكمي من أول شمعة في الملف، فنتيجته بتتغير حسب طول البيانات المحمّلة.)
    day_key = np.asarray(cairo_days)
    price_volume = close * volume
    cum_pv = price_volume.groupby(day_key).cumsum()
    cum_v = volume.groupby(day_key).cumsum().replace(0, np.nan)
    data["VWAP_day"] = (cum_pv / cum_v).reindex(data.index)   # نفس الفهرس الأصلي (مكافئ لـ reset بعد التجميع)
    # على بيانات يومية (شمعة واحدة لكل يوم) الـVWAP اليومي = سعر الإغلاق بالظبط، فشرط "Close > VWAP_day" يبقى مستحيل.
    # بديل للمرآة على البيانات اليومية: VWAP متحرك لآخر 20 جلسة (مستقل عن طول الملف).
    data["VWAP_20"] = price_volume.rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
    data.attrs["intraday"] = bool(cairo_days.duplicated().any())
    data["VWAP_ref"] = data["VWAP_day"] if data.attrs["intraday"] else data["VWAP_20"]

    data["Gap_Pct"] = (data["Open"] - prev_close) / prev_close * 100
    return data


def passes_screener(df: pd.DataFrame, cfg: ScreenConfig) -> tuple[bool, dict[str, Any]]:
    data = df if "Volume_SMA20" in df.columns else calculate_indicators(df)
    checks: dict[str, Any] = {
        "min_rows": len(data) >= cfg.min_rows,
        "close_min": False,
        "volume_sma20_min": False,
        "value_sma20_min": False,
        "active_days_20_min": False,
    }
    if len(data) == 0:
        return False, checks

    last = data.iloc[-1]
    active_days_20 = int((data["Volume"].tail(20) > 0).sum())
    checks.update(
        {
            "close_min": bool(last["Close"] >= cfg.min_close),
            "volume_sma20_min": bool(last["Volume_SMA20"] >= cfg.min_volume_sma20),
            "value_sma20_min": bool(last["Value_SMA20"] >= cfg.min_value_sma20),
            "active_days_20_min": bool(active_days_20 >= cfg.min_active_days_20),
            "active_days_20": active_days_20,
        }
    )
    return all(bool(checks[k]) for k in ("min_rows", "close_min", "volume_sma20_min", "value_sma20_min", "active_days_20_min")), checks


def evaluate_4_mirrors(df: pd.DataFrame, signal_cfg: SignalConfig) -> dict[str, Any]:
    data = df if "ADX" in df.columns else calculate_indicators(df)
    if len(data) == 0:
        return {"signal": "WAIT", "mirrors": {}, "row": None}

    last = data.iloc[-1]
    mirrors: dict[str, bool] = {
        "Trend": False,
        "Momentum": False,
        "Volume": False,
        "Volatility": False,
    }

    if abs(float(last.get("Gap_Pct", 0) or 0)) > signal_cfg.max_gap_pct:
        return {"signal": "SKIP_GAP", "mirrors": mirrors, "row": last}
    if float(last["ADX"]) < signal_cfg.min_adx:
        return {"signal": "NO_TREND", "mirrors": mirrors, "row": last}

    mirrors["Trend"] = bool(
        last["Close"] > last["EMA_50"]
        and last["EMA_20"] > last["EMA_50"]
        and last["EMA50_slope"] > 0
    )
    mirrors["Momentum"] = bool(
        signal_cfg.rsi_min < last["RSI"] < signal_cfg.rsi_max
        and last["MACD_Hist"] > 0
    )
    mirrors["Volume"] = bool(
        last["Volume"] > signal_cfg.volume_multiplier * last["Volume_SMA20"]
        and last["OBV"] > last["OBV_SMA20"]
        and last["Close"] > last["VWAP_ref"]   # v3: VWAP يومي حقيقي للبيانات اللحظية، و VWAP_20 للبيانات اليومية
    )
    mirrors["Volatility"] = bool(
        last["Close"] > last["BB_Mid"]
        and last["ATR_Pct"] >= signal_cfg.min_atr_pct
        and last["BB_Width"] >= signal_cfg.min_bb_width
    )
    return {"signal": "BUY" if all(mirrors.values()) else "WAIT", "mirrors": mirrors, "row": last}


def _net_reward_risk(
    entry: float,
    stop_loss: float,
    take_profit: float,
    shares: int,
    risk_cfg: RiskConfig,
) -> tuple[float, float, float]:
    gross_loss = (entry - stop_loss) * shares
    gross_profit = (take_profit - entry) * shares
    loss_fees = trade_fees(entry, stop_loss, shares, risk_cfg)
    profit_fees = trade_fees(entry, take_profit, shares, risk_cfg)
    net_loss = gross_loss + loss_fees
    pre_tax_profit = gross_profit - profit_fees
    tax = max(pre_tax_profit, 0) * risk_cfg.capital_gains_tax_pct
    net_profit = pre_tax_profit - tax
    rr_net = net_profit / net_loss if net_loss > 0 else 0.0
    return net_loss, net_profit, rr_net


def build_trade_plan(
    ticker: str,
    df: pd.DataFrame,
    signal_cfg: SignalConfig,
    risk_cfg: RiskConfig,
) -> Optional[TradePlan]:
    data = df if "ADX" in df.columns else calculate_indicators(df)
    evaluation = evaluate_4_mirrors(data, signal_cfg)
    if evaluation["signal"] != "BUY":
        return None

    last = data.iloc[-1]
    entry = float(last["Close"])
    atr = float(last["ATR"])
    stop_loss = entry - risk_cfg.atr_sl_mult * atr
    take_profit = entry + (risk_cfg.reward_risk * risk_cfg.atr_sl_mult * atr)
    risk_per_share = entry - stop_loss
    if not np.isfinite(risk_per_share) or risk_per_share <= 0:
        return None

    shares_by_risk = floor((risk_cfg.capital * risk_cfg.risk_pct) / risk_per_share)
    shares_by_cap = floor((risk_cfg.capital * risk_cfg.max_position_pct) / entry)
    shares_by_liq = floor(risk_cfg.max_avg_volume_pct * float(last["Volume_SMA20"]))
    shares = int(min(shares_by_risk, shares_by_cap, shares_by_liq))
    if shares <= 0:
        return None

    risk_egp, reward_egp, rr_net = _net_reward_risk(entry, stop_loss, take_profit, shares, risk_cfg)
    if rr_net < risk_cfg.reward_risk:
        after_tax = 1 - risk_cfg.capital_gains_tax_pct
        if after_tax <= 0:
            raise ValueError('Capital gains tax must be below 100%')
        required_gross = risk_cfg.reward_risk * risk_egp / after_tax
        low, high = take_profit, max(take_profit, entry * 2)
        for _ in range(128):
            if (high - entry) * shares - trade_fees(entry, high, shares, risk_cfg) >= required_gross:
                break
            high *= 2
        else:
            raise ValueError('Fee configuration cannot produce the requested net reward')
        for _ in range(64):
            middle = (low + high) / 2
            if (middle - entry) * shares - trade_fees(entry, middle, shares, risk_cfg) < required_gross:
                low = middle
            else:
                high = middle
        take_profit = high
        risk_egp, reward_egp, rr_net = _net_reward_risk(
            entry, stop_loss, take_profit, shares, risk_cfg
        )

    return TradePlan(
        ticker=ticker,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        atr=atr,
        shares=shares,
        risk_egp=risk_egp,
        reward_egp=reward_egp,
        rr_net=rr_net,
        position_value=shares * entry,
        notes=f"fees={'Thndr current-tariff scenario' if risk_cfg.round_trip_fee_pct is None else 'legacy per-side override'}, tax assumption={risk_cfg.capital_gains_tax_pct:.0%}",
    )


def sector_for(ticker: str, sector_map: Mapping[str, str]) -> str:
    return sector_map.get(ticker.upper(), "Other")


def limit_sector_exposure(
    signals: list[dict[str, Any]],
    sector_map: Mapping[str, str],
    max_per_sector: int = 2,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for signal in sorted(signals, key=lambda x: float(x.get("RR_Net", 0)), reverse=True):
        sector = sector_for(str(signal["Ticker"]), sector_map)
        if counts.get(sector, 0) >= max_per_sector:
            continue
        counts[sector] = counts.get(sector, 0) + 1
        signal["Sector"] = sector
        kept.append(signal)
    return kept


ACTIONS_CSV = Path(__file__).with_name("docs") / "corporate_actions.csv"
# فولدرات أسعارها معدّلة بالتوزيعات أصلًا (auto_adjust=True) — إضافة التوزيعات عليها = حسابها مرتين.
# كل واحد اتفحص بمقارنة COMI/EAST مع data_2019_2026_wf أو Yahoo مباشرة (KNOWN_ISSUES.md). أي فولدر معدّل جديد يتضاف هنا.
KNOWN_ADJUSTED_FOLDERS = frozenset({"data_2019_2026_wf", "data_2022_2023", "data_2020_2021", "data_dividend_adjusted",
                                    "data_momentum_2019", "data_h3_live"})
KNOWN_UNADJUSTED_FOLDERS = frozenset({"data"})  # data_downloader.py: auto_adjust=False


# يحدد هل نضيف التوزيعات للـbacktest. فولدر معروف بمود مخالف أو فولدر مش معروف من غير مود → خطأ صريح.
def resolve_dividend_mode(folder: str | Path, mode: Optional[str] = None) -> tuple[str, str]:
    name = Path(folder).name
    if mode not in (None, "add", "none"):
        raise ValueError(f"dividend mode must be 'add' or 'none', got {mode!r}")
    expected = "none" if name in KNOWN_ADJUSTED_FOLDERS else "add" if name in KNOWN_UNADJUSTED_FOLDERS else None
    if expected is None:
        if mode is None:
            raise ValueError(f"unknown data folder {name!r}: pass dividend mode 'add' (dividend-unadjusted prices) or 'none' (adjusted)")
        return mode, f"Data folder: {name}/    Dividend mode: {mode}    (user-set, unverified)"
    if mode not in (None, expected):
        kind = "dividend-adjusted" if expected == "none" else "dividend-unadjusted"
        raise ValueError(f"data folder {name!r} is {kind}; dividend mode must be {expected!r}, got {mode!r}")
    state = "adjusted" if expected == "none" else "unadjusted"
    return expected, f"Data folder: {name}/    Dividend mode: {expected}    ({state}, verified)"


# يضيف عمود Dividends (توزيع/سهم، قبل الضريبة) على تاريخ الاستحقاق — للـbacktest فقط، الإنتاج مش محتاجه.
def with_dividends(ticker: str, df: pd.DataFrame, actions_csv: Path = ACTIONS_CSV) -> pd.DataFrame:
    data = df.copy()
    data["Dividends"] = 0.0
    if not actions_csv.exists() or data.empty:
        return data
    acts = pd.read_csv(actions_csv)
    acts = acts[(acts["ticker"].str.upper() == ticker.upper()) & (acts["dividend"] != 0)]
    days = data.index.tz_convert(CAIRO_TZ).tz_localize(None).normalize() if data.index.tz else data.index.normalize()
    for ex_date, amount in zip(pd.to_datetime(acts["ex_date"]), acts["dividend"]):
        pos = days.searchsorted(ex_date)  # ex-date missing from the data (Yahoo gap) → next available bar
        if 0 < pos < len(data):
            data.iloc[pos, data.columns.get_loc("Dividends")] += float(amount)
    return data


# توزيعات/سهم بتاريخ استحقاق في الشموع (i, j]: ماسك السهم في إغلاق i ولسه ماسكه قبل افتتاح يوم الاستحقاق.
def dividends_between(data: pd.DataFrame, i: int, j: int) -> float:
    return float(data["Dividends"].iloc[i + 1 : j + 1].sum()) if "Dividends" in data.columns else 0.0


# صافي ربح صفقة: فرق السعر − العمولة − ضريبة الأرباح الرأسمالية + صافي التوزيعات بعد الاستقطاع.
# مشتركة بين المحرك و backtest_optimizer عشان الاتنين يفضلوا متطابقين.
def trade_fees(entry, exit_price, shares, risk, *, same_session=False, entry_fills=None, exit_fills=None):
    if risk.round_trip_fee_pct is not None:
        return risk.round_trip_fee_pct * shares * (entry + exit_price)
    return round_trip_fees(entry * shares, exit_price * shares, same_session=same_session,
                           entry_fills=entry_fills, exit_fills=exit_fills, config=risk.fees)


def entry_order_fee(value, risk):
    if risk.round_trip_fee_pct is not None:
        return value * risk.round_trip_fee_pct
    return sum(order_fees(value, config=risk.fees).values())


def same_session(entry_date, exit_date):
    def cairo_day(value):
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError('Missing execution timestamp')
        return (stamp.tz_localize('Africa/Cairo') if stamp.tzinfo is None else stamp.tz_convert('Africa/Cairo')).date()
    return cairo_day(entry_date) == cairo_day(exit_date)


def net_trade_pnl(entry: float, exit_price: float, shares: int, risk: RiskConfig, dividends_per_share: float = 0.0,
                  *, same_session=False, entry_fills=None, exit_fills=None) -> float:
    pre_tax = (exit_price - entry) * shares - trade_fees(entry, exit_price, shares, risk, same_session=same_session,
                                                       entry_fills=entry_fills, exit_fills=exit_fills)
    return pre_tax - max(pre_tax, 0) * risk.capital_gains_tax_pct + dividends_per_share * (1 - risk.dividend_tax_pct) * shares


# منحنى Buy & Hold بالتوزيعات الصافية (من غير إعادة استثمار) — نفس معاملة الاستراتيجية.
def buy_hold_curve(data: pd.DataFrame, start: int, capital: float, risk: RiskConfig) -> pd.Series:
    close = data["Close"].iloc[start:]
    divs = data["Dividends"].iloc[start:].copy() if "Dividends" in data.columns else pd.Series(0.0, index=close.index)
    divs.iloc[0] = 0.0
    return capital * (close + divs.cumsum() * (1 - risk.dividend_tax_pct)) / float(close.iloc[0])


def _trade_return(entry: float, exit_price: float, risk_per_share: float) -> float:
    return (exit_price - entry) / risk_per_share if risk_per_share > 0 else 0.0


def backtest(df: pd.DataFrame, cfg: SystemConfig) -> dict[str, Any]:
    data = calculate_indicators(df)
    equity = cfg.risk.capital
    r_values: list[float] = []
    trades: list[dict[str, Any]] = []
    equity_events: list[tuple[pd.Timestamp, float]] = []
    wins = 0
    losses = 0
    gross_win = 0.0
    gross_loss = 0.0
    start_index = 60
    i = start_index

    if len(data) <= i:
        empty = pd.DataFrame()
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_R": 0.0,
            "max_drawdown": 0.0,
            "final_equity": equity,
            "sharpe": 0.0,
            "buy_hold_return": 0.0,
            "buy_hold_final_equity": equity,
            "trades": empty,
            "equity_curve": empty,
        }

    equity_events.append((data.index[start_index], equity))

    while i < len(data) - 1:
        window = data.iloc[: i + 1]
        screen_ok, _ = passes_screener(window, cfg.screen)
        evaluation = evaluate_4_mirrors(window, cfg.signal)
        plan = build_trade_plan("BACKTEST", window, cfg.signal, cfg.risk) if screen_ok and evaluation["signal"] == "BUY" else None
        if plan is None:
            i += 1
            continue

        entry = plan.entry
        atr = plan.atr
        stop_loss = plan.stop_loss
        take_profit = plan.take_profit
        exit_price = data.iloc[-1]["Close"]
        exit_index = len(data) - 1
        exit_reason = "END"

        for j in range(i + 1, len(data)):
            row = data.iloc[j]
            if row["Low"] <= stop_loss:
                exit_price = stop_loss
                exit_index = j
                exit_reason = "TRAIL_SL" if stop_loss > plan.stop_loss else "SL"
                break
            if row["High"] >= take_profit:
                exit_price = take_profit
                exit_index = j
                exit_reason = "TP"
                break
            if row["Close"] >= entry + 2 * atr:
                stop_loss = max(stop_loss, entry + atr)
            elif row["Close"] >= entry + atr:
                stop_loss = max(stop_loss, entry)

        risk_per_share = entry - plan.stop_loss
        div_ps = dividends_between(data, i, exit_index)
        pnl = net_trade_pnl(entry, float(exit_price), plan.shares, cfg.risk, div_ps,
                            same_session=same_session(data.index[i], data.index[exit_index]))
        r_multiple = pnl / plan.risk_egp if plan.risk_egp > 0 else _trade_return(entry, float(exit_price), risk_per_share)
        equity += pnl
        r_values.append(r_multiple)
        equity_events.append((data.index[exit_index], equity))
        trades.append(
            {
                "Ticker": "BACKTEST",
                "Entry_Date": data.index[i],
                "Exit_Date": data.index[exit_index],
                "Entry": entry,
                "Exit": float(exit_price),
                "Shares": plan.shares,
                "Position_Value": plan.position_value,
                "Div_PS": div_ps,
                "PnL_EGP": pnl,
                "PnL_%": pnl / plan.position_value * 100,
                "R": r_multiple,
                "Exit_Reason": exit_reason,
            }
        )
        if pnl > 0:
            wins += 1
            gross_win += pnl
        else:
            losses += 1
            gross_loss += abs(pnl)
        i = max(exit_index + 1, i + 1)

    total_trades = len(r_values)
    equity_series = pd.Series(dict(equity_events), dtype=float).reindex(data.index[start_index:]).ffill()
    buy_hold_series = buy_hold_curve(data, start_index, cfg.risk.capital, cfg.risk)
    peak_series = equity_series.cummax()
    drawdown_series = equity_series / peak_series - 1
    returns = equity_series.pct_change().dropna().to_numpy(dtype=float)
    sharpe = 0.0
    if len(returns) > 1 and returns.std(ddof=1) > 0:
        sharpe = float(returns.mean() / returns.std(ddof=1) * sqrt(252))

    buy_hold_return = float(buy_hold_series.iloc[-1]) / cfg.risk.capital - 1
    equity_curve = pd.DataFrame(
        {
            "Strategy_Equity": equity_series,
            "Buy_Hold_Equity": buy_hold_series,
            "Drawdown": drawdown_series,
        }
    )

    return {
        "total_trades": total_trades,
        "win_rate": wins / total_trades if total_trades else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else np.inf if gross_win > 0 else 0.0,
        "avg_R": float(np.mean(r_values)) if r_values else 0.0,
        "max_drawdown": float(drawdown_series.min()),
        "final_equity": equity,
        "sharpe": sharpe,
        "buy_hold_return": buy_hold_return,
        "buy_hold_final_equity": cfg.risk.capital * (1 + buy_hold_return),
        "trades": pd.DataFrame(trades),
        "equity_curve": equity_curve,
    }


def _checks_text(checks: Mapping[str, Any]) -> str:
    return "; ".join(f"{k}={v}" for k, v in checks.items())


def scan_universe(
    data_map: Mapping[str, pd.DataFrame],
    screen_cfg: ScreenConfig,
    signal_cfg: SignalConfig,
    risk_cfg: RiskConfig,
    sector_limit: int = 2,
    *,
    demo_mode: bool = False,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    passed_signals: list[dict[str, Any]] = []

    for ticker, raw_df in filter_universe(data_map, demo_mode=demo_mode).items():
        data = calculate_indicators(raw_df)
        screen_ok, screen_checks = passes_screener(data, screen_cfg)
        if not screen_ok:
            rows.append({"Ticker": ticker, "Status": "SCREEN_FAIL", "Checks": _checks_text(screen_checks)})
            continue

        evaluation = evaluate_4_mirrors(data, signal_cfg)
        plan = build_trade_plan(ticker, data, signal_cfg, risk_cfg)
        if plan is None:
            rows.append(
                {
                    "Ticker": ticker,
                    "Status": evaluation["signal"],
                    "Sector": sector_for(ticker, SECTOR_MAP),
                    "Checks": _checks_text(evaluation["mirrors"]),
                }
            )
            continue

        row = {
            "Ticker": ticker,
            "Status": "BUY",
            "Entry": round(plan.entry, 3),
            "SL": round(plan.stop_loss, 3),
            "TP": round(plan.take_profit, 3),
            "ATR": round(plan.atr, 3),
            "Shares": plan.shares,
            "RR_Net": round(plan.rr_net, 3),
            "Sector": sector_for(ticker, SECTOR_MAP),
            "Checks": _checks_text(evaluation["mirrors"]),
        }
        passed_signals.append(row)

    limited = limit_sector_exposure(passed_signals, SECTOR_MAP, sector_limit)
    return annotate(pd.DataFrame(limited + rows, columns=["Ticker", "Status", "Entry", "SL", "TP", "ATR", "Shares", "RR_Net", "Sector", "Checks"]))


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for col in df.columns:
        key = col.strip().lower().replace(" ", "_")
        if key in {"date", "datetime", "time"}:
            rename[col] = "Date"
        elif key in {"open", "o"}:
            rename[col] = "Open"
        elif key in {"high", "h"}:
            rename[col] = "High"
        elif key in {"low", "l"}:
            rename[col] = "Low"
        elif key in {"close", "c", "last"}:
            rename[col] = "Close"
        elif key in {"volume", "vol", "v"}:
            rename[col] = "Volume"
        elif key in {"ticker", "symbol"}:
            rename[col] = "Ticker"
    return df.rename(columns=rename)


def _with_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    data = _standardize_columns(df)
    if "Date" in data.columns:
        index = pd.to_datetime(data.pop("Date"), errors="coerce")
        data = data.loc[index.notna()].copy()
        index = index[index.notna()]
        if index.dt.tz is None:
            data.index = index.dt.tz_localize(CAIRO_TZ, nonexistent="shift_forward", ambiguous="NaT").dt.tz_convert(UTC_TZ)
        else:
            data.index = index.dt.tz_convert(UTC_TZ)
    elif not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("CSV must include Date/Datetime column or a DatetimeIndex")
    elif data.index.tz is None:
        data.index = data.index.tz_localize(CAIRO_TZ, nonexistent="shift_forward", ambiguous="NaT").tz_convert(UTC_TZ)
    else:
        data.index = data.index.tz_convert(UTC_TZ)
    return data.sort_index()


def load_data_map(path_or_folder: Path) -> dict[str, pd.DataFrame]:
    if path_or_folder.is_dir():
        return {file.stem.upper(): _with_utc_index(pd.read_csv(file)) for file in sorted(path_or_folder.glob("*.csv"))}

    df = _standardize_columns(pd.read_csv(path_or_folder))
    if "Ticker" in df.columns:
        return {str(ticker).upper(): _with_utc_index(part.drop(columns=["Ticker"])) for ticker, part in df.groupby("Ticker")}
    return {path_or_folder.stem.upper(): _with_utc_index(df)}


def _demo_data(periods: int = 160) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = np.cumprod(1 + rng.normal(0.0025, 0.017, periods)) * 55
    end_utc = pd.Timestamp.now(tz=UTC_TZ).normalize() + pd.Timedelta(hours=12)
    index = pd.DatetimeIndex([end_utc - pd.Timedelta(days=periods - i - 1) for i in range(periods)])
    data = pd.DataFrame(
        {
            "Open": np.r_[close[0], close[:-1]] * rng.uniform(0.995, 1.01, periods),
            "High": close * rng.uniform(1.005, 1.035, periods),
            "Low": close * rng.uniform(0.965, 0.995, periods),
            "Close": close,
            "Volume": rng.integers(80_000, 650_000, periods),
        },
        index=index,
    )
    return data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EGX Trading System v2: 4 Mirrors + ATR Risk")
    parser.add_argument("path_or_folder", nargs="?", help="CSV file, combined CSV with Ticker, or folder of CSVs")
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--risk", type=float, default=0.01)
    parser.add_argument("--out", default="")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--dividend-mode", choices=["add", "none"], help="required for data folders not in KNOWN_*_FOLDERS")
    parser.add_argument("--sector-limit", type=int, default=2)
    parser.add_argument("--min-adx", type=float, default=20.0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    screen_cfg = ScreenConfig()
    signal_cfg = SignalConfig(min_adx=args.min_adx)
    risk_cfg = RiskConfig(capital=args.capital, risk_pct=args.risk)
    system_cfg = SystemConfig(screen=screen_cfg, signal=signal_cfg, risk=risk_cfg)

    data_map = load_data_map(Path(args.path_or_folder)) if args.path_or_folder else {"DEMO.CA": _demo_data()}
    if args.backtest:
        source = Path(args.path_or_folder) if args.path_or_folder else Path("demo")
        dividend_mode, dividend_line = resolve_dividend_mode(source if source.is_dir() else source.parent, args.dividend_mode)
        print(dividend_line)
    signals = scan_universe(data_map, screen_cfg, signal_cfg, risk_cfg, args.sector_limit)
    generated_utc = pd.Timestamp.now(tz=UTC_TZ)
    generated_cairo = generated_utc.tz_convert(CAIRO_TZ)

    print(f"Generated UTC: {generated_utc.isoformat()}")
    print(f"Displayed Cairo: {generated_cairo.isoformat()}")
    print(signals.to_string(index=False))

    if args.out:
        signals.to_csv(args.out, index=False, encoding="utf-8-sig")

    if args.backtest:
        for ticker, data in data_map.items():
            stats = backtest(with_dividends(ticker, data) if dividend_mode == "add" else data, system_cfg)
            print(f"\nBacktest {ticker}")
            for key, value in stats.items():
                print(f"{key}: {value}")

    assert not signals.empty


if __name__ == "__main__":
    main()
