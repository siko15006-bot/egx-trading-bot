from __future__ import annotations
from egx_lists import UNIVERSE, MANIFEST, DEMO_TICKERS, annotate, filter_universe, universe_table, recommendation_warning

import os
import sqlite3
from dataclasses import replace
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from analytics_engine import *
import html as html_lib

from setup_builder import PATTERN_AR, QUALITY_AR, TradeSetup, build_setups
import signal_engine as sigeng
from dataclasses import asdict
from paper_trading import (
    PaperTradeInput,
    add_paper_trade,
    campaign_progress,
    close_paper_trade,
    format_close_message,
    format_open_message,
    format_weekly_message,
    init_paper_db,
    load_paper_trades,
    performance_summary,
    weekly_performance,
)
from telegram_notifier import is_configured as telegram_is_configured, send_telegram

from egx_4_mirrors_v3 import (
    RiskConfig,
    ScreenConfig,
    SECTOR_MAP,
    SignalConfig,
    SystemConfig,
    KNOWN_ADJUSTED_FOLDERS,
    KNOWN_UNADJUSTED_FOLDERS,
    backtest,
    resolve_dividend_mode,
    with_dividends,
    build_trade_plan,
    calculate_indicators,
    evaluate_4_mirrors,
    passes_screener,
    scan_universe,
)


CAIRO_TZ = ZoneInfo("Africa/Cairo")
UTC_TZ = ZoneInfo("UTC")
OHLCV = ("Open", "High", "Low", "Close", "Volume")
STATUS_COLORS = {
    "BUY": "#16794b",
    "WAIT": "#b7791f",
    "SKIP_GAP": "#6b7280",
    "NO_TREND": "#c05621",
    "SCREEN_FAIL": "#9ca3af",
}


st.set_page_config(page_title="EGX Trading System v3", layout="wide")

if os.getenv("EGX_MOBILE_MODE") == "1":
    st.warning("وضع الموبايل يعمل على الشبكة المحلية فقط. لا تنشر الرابط على الإنترنت.")


def rtl_title(text: str, level: int = 2) -> None:
    st.markdown(f'<h{level} dir="rtl">{text}</h{level}>', unsafe_allow_html=True)


def _normalize_csv(raw: pd.DataFrame) -> pd.DataFrame:
    rename = {str(col): str(col).strip().title() for col in raw.columns}
    data = raw.rename(columns=rename)
    date_col = next((col for col in data.columns if col.lower() in {"date", "datetime", "time"}), None)
    if date_col is None:
        raise ValueError("CSV must include Date, Datetime, or Time column")
    missing = [col for col in OHLCV if col not in data.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")
    index = pd.to_datetime(data.pop(date_col), errors="coerce")
    data = data.loc[index.notna(), list(OHLCV)].copy()
    index = index[index.notna()]
    if index.dt.tz is None:
        index = index.dt.tz_localize(CAIRO_TZ, nonexistent="shift_forward", ambiguous=False)
    data.index = index.dt.tz_convert(UTC_TZ)
    for col in OHLCV:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna().sort_index()
    if data.empty:
        raise ValueError("CSV contains no valid OHLCV rows")
    return data


@st.cache_data(show_spinner=False)
def load_folder(folder: str) -> dict[str, pd.DataFrame]:
    path = Path(folder).expanduser()
    if not path.is_dir():
        raise ValueError("Folder does not exist")
    files = sorted(path.glob("*.csv"))
    if not files:
        raise ValueError("No CSV files found in folder")
    return filter_universe({file.stem.upper(): _normalize_csv(pd.read_csv(file)) for file in files})


@st.cache_data(show_spinner=False)
def load_uploads(files: tuple[tuple[str, bytes], ...]) -> dict[str, pd.DataFrame]:
    return {
        Path(name).stem.upper(): _normalize_csv(pd.read_csv(BytesIO(content)))
        for name, content in files
    }


@st.cache_data(show_spinner=False)
def generate_demo_data(periods: int = 360) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    calendar = pd.date_range(end=pd.Timestamp.now(tz=UTC_TZ).normalize(), periods=periods * 2, freq="D")
    index = calendar[calendar.dayofweek < 5][-periods:]
    specs = {
        "BULL.CA": (0.0018, 0.012, 420_000),
        "BEAR.CA": (-0.0010, 0.014, 360_000),
        "SIDEWAYS.CA": (0.0, 0.008, 280_000),
        "VOLATILE.CA": (0.0004, 0.032, 520_000),
        "QUIET.CA": (0.0002, 0.003, 90_000),
    }
    result: dict[str, pd.DataFrame] = {}
    for ticker, (drift, volatility, base_volume) in specs.items():
        returns = rng.normal(drift, volatility, periods)
        if ticker == "SIDEWAYS.CA":
            close = 45 + np.sin(np.linspace(0, 10 * np.pi, periods)) * 2 + rng.normal(0, 0.35, periods)
        else:
            close = 45 * np.cumprod(1 + returns)
        previous = np.r_[close[0], close[:-1]]
        spread = np.maximum(np.abs(rng.normal(volatility, volatility / 3, periods)), 0.003)
        volume = np.maximum(rng.normal(base_volume, base_volume * 0.22, periods), 10_000).astype(int)
        result[ticker] = pd.DataFrame(
            {
                "Open": previous * (1 + rng.normal(0, volatility / 4, periods)),
                "High": close * (1 + spread),
                "Low": close * (1 - spread),
                "Close": close,
                "Volume": volume,
            },
            index=index,
        )
    return result


def _sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker.upper(), "Other")


def _display_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.tz_convert(CAIRO_TZ) if index.tz is not None else index.tz_localize(CAIRO_TZ)


def _money(value: float) -> str:
    return f"{value:,.0f} EGP"


def _init_state() -> None:
    defaults: dict[str, Any] = {
        "data_map": {},
        "scanner_results": pd.DataFrame(),
        "backtest_result": None,
        "sector_results": None,
        "analytics_report": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.get("universe_version") != MANIFEST["version"]:
        folder = Path(__file__).parent / "data"
        if folder.is_dir() and any(folder.glob("*.csv")):
            st.session_state.data_map = load_folder(str(folder))
            st.session_state.data_folder = str(folder)
        st.session_state.universe_version = MANIFEST["version"]
        st.session_state.scanner_results = pd.DataFrame()


def _apply_theme(dark: bool) -> None:
    background = "#0f172a" if dark else "#f7f8fa"
    panel = "#172033" if dark else "#ffffff"
    text = "#edf2f7" if dark else "#1f2937"
    border = "#334155" if dark else "#d8dee8"
    st.markdown(
        """
        <style>
        [data-testid="stMetric"] {
            background: var(--secondary-background-color);
            border: 1px solid rgba(128,128,128,0.25);
            padding: 12px;
            border-radius: 6px;
        }
        .mirror {
            border: 1px solid rgba(128,128,128,0.3);
            border-left: 5px solid var(--mirror-color);
            background: var(--secondary-background-color);
            padding: 12px;
            border-radius: 6px;
            min-height: 78px;
        }
        .insight {
            border: 1px solid rgba(128,128,128,0.3);
            background: var(--secondary-background-color);
            padding: 16px;
            border-radius: 6px;
        }
        div[dir="rtl"] { text-align: right; }
        [data-testid="stAlert"] [data-testid="stMarkdownContainer"] {
            direction: rtl;
            text-align: right;
            unicode-bidi: plaintext;
        }
        [data-testid="stAlert"] code,
        [data-testid="stAlert"] pre {
            direction: ltr;
            text-align: left;
            unicode-bidi: embed;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _sidebar() -> tuple[ScreenConfig, SignalConfig, RiskConfig, int]:
    st.sidebar.markdown('<h2 dir="rtl">إعدادات الحساب</h2>', unsafe_allow_html=True)
    capital = st.sidebar.number_input("Account Capital (EGP)", 10_000.0, 100_000_000.0, 100_000.0, 10_000.0)
    risk_percent = st.sidebar.slider("Risk per trade %", 0.1, 2.0, 1.0, 0.1)
    sector_limit = st.sidebar.number_input("Sector limit", 1, 10, 2)
    dark = st.sidebar.toggle("Dark Mode", value=False)
    _apply_theme(dark)

    st.sidebar.divider()
    source = st.sidebar.radio("مصدر البيانات", ["CSV Folder", "Upload Files", "Demo Data"])
    try:
        if source == "CSV Folder":
            folder = st.sidebar.text_input("CSV folder path", value=str(Path(__file__).parent / "data"))
            if st.sidebar.button("Load", width="stretch"):
                with st.spinner("Loading CSV files..."):
                    st.session_state.data_map = load_folder(folder)
                    st.session_state.data_folder = folder
        elif source == "Upload Files":
            uploads = st.sidebar.file_uploader("Upload CSV files", type=["csv"], accept_multiple_files=True)
            if uploads and st.sidebar.button("Load uploads", width="stretch"):
                payload = tuple((file.name, file.getvalue()) for file in uploads)
                with st.spinner("Validating uploads..."):
                    st.session_state.data_map = load_uploads(payload)
                    st.session_state.data_folder = "uploads"
        elif st.sidebar.button("Generate 5 demo stocks", width="stretch"):
            st.session_state.data_map = generate_demo_data()
            st.session_state.data_folder = "demo"
    except (ValueError, OSError, pd.errors.ParserError) as exc:
        st.sidebar.error(str(exc))

    st.sidebar.divider()
    st.sidebar.markdown('<h3 dir="rtl">فلاتر الماسح</h3>', unsafe_allow_html=True)
    min_price = st.sidebar.slider("Min price", 0.1, 50.0, 1.0, 0.1)
    min_volume = st.sidebar.number_input("Min Volume SMA20", 0, 10_000_000, 50_000, 10_000)
    min_value = st.sidebar.number_input("Min value traded (EGP)", 0, 1_000_000_000, 1_000_000, 100_000)
    min_days = st.sidebar.slider("Min days traded / 20", 1, 20, 16)
    sectors = sorted(set(SECTOR_MAP.values()) | {"Other"})
    st.session_state.selected_sectors = st.sidebar.multiselect("Sectors", sectors, default=sectors)
    st.session_state.only_buy = st.sidebar.checkbox("أظهر فقط 4 Mirrors", value=False)
    min_adx = st.sidebar.number_input("Min ADX", 0.0, 100.0, 20.0, 1.0)
    min_atr = st.sidebar.number_input("Min ATR %", 0.0, 20.0, 1.5, 0.1)

    if st.sidebar.button("🔄 Reset All", width="stretch"):
        st.cache_data.clear()
        st.session_state.clear()
        st.rerun()

    return (
        ScreenConfig(
            min_close=min_price,
            min_volume_sma20=float(min_volume),
            min_value_sma20=float(min_value),
            min_active_days_20=min_days,
        ),
        SignalConfig(min_adx=min_adx, min_atr_pct=min_atr),
        RiskConfig(capital=capital, risk_pct=risk_percent / 100),
        int(sector_limit),
    )


# يعرض حالة البيانات المحملة وملخص جودتها.
def render_tab1() -> None:
    rtl_title("تحميل البيانات وملخص السوق")
    data_map: Mapping[str, pd.DataFrame] = st.session_state.data_map
    if not data_map:
        st.info("اختر مصدر البيانات من الشريط الجانبي ثم حمّل الملفات.")
        return

    starts = [df.index.min() for df in data_map.values()]
    ends = [df.index.max() for df in data_map.values()]
    liquidity = [float((df["Close"] * df["Volume"]).tail(20).mean()) for df in data_map.values()]
    row1 = st.columns(2)
    row2 = st.columns(2)
    row1[0].metric("Stocks", f"{len(data_map):,}")
    row1[1].metric("Period", f"{min(starts).date()} → {max(ends).date()}")
    row2[0].metric("Latest (Cairo)", _display_index(pd.DatetimeIndex([max(ends)]))[0].strftime("%Y-%m-%d"))
    row2[1].metric("Avg daily liquidity", _money(float(np.mean(liquidity))))

    summary = pd.DataFrame(
        {
            "Ticker": data_map.keys(),
            "Rows": [len(df) for df in data_map.values()],
            "From": [_display_index(df.index)[0].date() for df in data_map.values()],
            "To": [_display_index(df.index)[-1].date() for df in data_map.values()],
            "Avg Value 20": liquidity,
        }
    )
    st.dataframe(
        summary,
        width="stretch",
        hide_index=True,
        column_config={"Avg Value 20": st.column_config.NumberColumn(format="%.0f EGP")},
    )


def _scanner_enrichment(
    data_map: Mapping[str, pd.DataFrame],
    base: pd.DataFrame,
    signal_cfg: SignalConfig,
) -> pd.DataFrame:
    details: list[dict[str, Any]] = []
    for ticker, raw in data_map.items():
        data = calculate_indicators(raw)
        evaluation = evaluate_4_mirrors(data, signal_cfg)
        row = evaluation["row"]
        details.append(
            {
                "Ticker": ticker,
                "Mirrors Score": sum(evaluation["mirrors"].values()),
                "ADX": float(row["ADX"]) if row is not None else np.nan,
                "ATR%": float(row["ATR_Pct"]) if row is not None else np.nan,
                "Signal": evaluation["signal"],
            }
        )
    enriched = base.merge(pd.DataFrame(details), on="Ticker", how="left")
    enriched["Status"] = enriched["Status"].fillna(enriched["Signal"])
    return enriched.drop(columns=["Signal"]).sort_values(["Mirrors Score", "ATR%"], ascending=False)


def _status_style(value: Any) -> str:
    color = STATUS_COLORS.get(str(value), "#6b7280")
    return f"background-color: {color}; color: white"


# يشغّل ماسح السوق ويعرض ترتيب الإشارات وخطة الصفقة.
def render_tab2(screen_cfg: ScreenConfig, signal_cfg: SignalConfig, risk_cfg: RiskConfig, sector_limit: int) -> None:
    rtl_title("Market Scanner")
    data_map: Mapping[str, pd.DataFrame] = st.session_state.data_map
    if not data_map:
        st.info("حمّل البيانات أولاً من تبويب تحميل البيانات.")
        return

    if st.button("Run Scanner", type="primary"):
        with st.spinner("Scanning EGX universe..."):
            base = scan_universe(data_map, screen_cfg, signal_cfg, risk_cfg, sector_limit, demo_mode=set(data_map).issubset(DEMO_TICKERS))
            result = _scanner_enrichment(data_map, base, signal_cfg)
            result = result[result["Sector"].fillna("Other").isin(st.session_state.selected_sectors)]
            if st.session_state.only_buy:
                result = result[result["Mirrors Score"] == 4]
            st.session_state.scanner_results = result

    result = st.session_state.scanner_results
    if result.empty:
        st.info("اضغط Run Scanner لبدء الفحص.")
        return

    metrics = st.columns(4)
    metrics[0].metric("BUY", int((result["Status"] == "BUY").sum()))
    metrics[1].metric("WAIT", int((result["Status"] == "WAIT").sum()))
    metrics[2].metric("Avg RR", f"{result['RR_Net'].dropna().mean():.2f}" if result["RR_Net"].notna().any() else "—")
    metrics[3].metric("Avg ADX", f"{result['ADX'].mean():.1f}")

    st.download_button(
        "Export to CSV",
        result.to_csv(index=False).encode("utf-8-sig"),
        "egx_signals.csv",
        "text/csv",
    )
    styled = result.style.map(_status_style, subset=["Status"])
    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        column_config={
            "Mirrors Score": st.column_config.ProgressColumn(min_value=0, max_value=4, format="%d / 4"),
            "Entry": st.column_config.NumberColumn(format="%.3f EGP"),
            "SL": st.column_config.NumberColumn(format="%.3f EGP"),
            "TP": st.column_config.NumberColumn(format="%.3f EGP"),
            "ATR%": st.column_config.NumberColumn(format="%.2f%%"),
        },
    )


def _price_chart(data: pd.DataFrame, plan: Any | None) -> go.Figure:
    x = _display_index(data.index)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=x, open=data["Open"], high=data["High"], low=data["Low"], close=data["Close"], name="Price", increasing_line_color="#16a34a", decreasing_line_color="#dc2626"))
    for col, color in (("EMA_20", "#2563eb"), ("EMA_50", "#f59e0b"), ("EMA_200", "#dc2626")):
        fig.add_trace(go.Scatter(x=x, y=data[col], name=col, line=dict(color=color, width=1.4)))
    fig.add_trace(go.Scatter(x=x, y=data["BB_Upper"], name="BB Upper", line=dict(color="#64748b", width=1), opacity=0.5))
    fig.add_trace(go.Scatter(x=x, y=data["BB_Lower"], name="BB Lower", line=dict(color="#64748b", width=1), fill="tonexty", fillcolor="rgba(100,116,139,0.12)", opacity=0.5))
    fig.add_trace(go.Scatter(x=x, y=data["VWAP_day"], name="VWAP", line=dict(color="#6b7280", width=1.2, dash="dash")))
    if plan:
        for value, label, color in ((plan.entry, "Entry", "#16a34a"), (plan.stop_loss, "SL", "#dc2626"), (plan.take_profit, "TP", "#2563eb")):
            fig.add_hline(y=value, line_color=color, line_dash="dot", annotation_text=label)
    fig.update_layout(height=560, xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=45, b=20), legend_orientation="h")
    return fig


def _volume_obv_chart(data: pd.DataFrame) -> go.Figure:
    x = _display_index(data.index)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = np.where(data["Close"].diff().fillna(0) >= 0, "#16a34a", "#dc2626")
    fig.add_trace(go.Bar(x=x, y=data["Volume"], name="Volume", marker_color=colors, opacity=0.55), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=data["Volume_SMA20"], name="Volume SMA20", line=dict(color="#f59e0b")), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=data["OBV"], name="OBV", line=dict(color="#2563eb")), secondary_y=True)
    fig.update_layout(height=330, margin=dict(l=20, r=20, t=40, b=20), legend_orientation="h")
    return fig


def _momentum_chart(data: pd.DataFrame) -> go.Figure:
    x = _display_index(data.index)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35], specs=[[{"secondary_y": True}], [{}]])
    fig.add_trace(go.Scatter(x=x, y=data["RSI"], name="RSI", line=dict(color="#2563eb")), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=data["ADX"], name="ADX", line=dict(color="#f59e0b")), row=1, col=1, secondary_y=True)
    for value, color in ((30, "#6b7280"), (50, "#16a34a"), (70, "#dc2626")):
        fig.add_hline(y=value, line_dash="dot", line_color=color, row=1, col=1)
    fig.add_hline(y=20, line_dash="dash", line_color="#f59e0b", row=1, col=1, secondary_y=True)
    macd_colors = np.where(data["MACD_Hist"] >= 0, "#16a34a", "#dc2626")
    fig.add_trace(go.Bar(x=x, y=data["MACD_Hist"], name="MACD Hist", marker_color=macd_colors), row=2, col=1)
    fig.update_layout(height=460, margin=dict(l=20, r=20, t=40, b=20), legend_orientation="h")
    return fig


def _volatility_chart(data: pd.DataFrame) -> go.Figure:
    x = _display_index(data.index)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=x, y=data["ATR_Pct"], name="ATR %", line=dict(color="#dc2626")), secondary_y=False)
    fig.add_trace(go.Scatter(x=x, y=data["BB_Width"] * 100, name="BB Width %", line=dict(color="#2563eb")), secondary_y=True)
    fig.add_hline(y=1.5, line_dash="dot", line_color="#dc2626", secondary_y=False)
    fig.add_hline(y=3.5, line_dash="dot", line_color="#2563eb", secondary_y=True)
    fig.update_layout(height=330, margin=dict(l=20, r=20, t=40, b=20), legend_orientation="h")
    return fig


# يعرض الرسوم الفنية التفصيلية وخطة الصفقة للسهم المختار.
def render_tab3(signal_cfg: SignalConfig, risk_cfg: RiskConfig) -> None:
    rtl_title("تحليل سهم واحد")
    data_map: Mapping[str, pd.DataFrame] = st.session_state.data_map
    if not data_map:
        st.info("حمّل البيانات أولاً.")
        return
    ticker = st.selectbox("Ticker", sorted(data_map))
    data = calculate_indicators(data_map[ticker])
    evaluation = evaluate_4_mirrors(data, signal_cfg)
    plan = build_trade_plan(ticker, data, signal_cfg, risk_cfg)

    main, side = st.columns([3, 1])
    with main:
        st.plotly_chart(_price_chart(data, plan), width="stretch")
    with side:
        rtl_title("Trade Plan", 3)
        if plan:
            st.metric("Entry", f"{plan.entry:,.3f} EGP")
            st.metric("Stop Loss", f"{plan.stop_loss:,.3f} EGP")
            st.metric("Take Profit", f"{plan.take_profit:,.3f} EGP")
            st.metric("Shares", f"{plan.shares:,}")
            st.metric("RR Net", f"{plan.rr_net:.2f}")
            st.progress(min(plan.rr_net / max(risk_cfg.reward_risk, 0.01), 1.0))
        elif evaluation["signal"] == "BUY":
            st.warning("الإشارة مكتملة، لكن الخطة رُفضت بسبب صافي R:R أو حجم المركز.")
        else:
            st.info(f"Current signal: {evaluation['signal']}")

        rtl_title("Mirrors Checklist", 3)
        labels = {"Trend": "الاتجاه", "Momentum": "الزخم", "Volume": "السيولة", "Volatility": "التذبذب"}
        for key, label in labels.items():
            passed = evaluation["mirrors"].get(key, False)
            color = "#16a34a" if passed else "#dc2626"
            icon = "✅" if passed else "❌"
            st.markdown(f'<div class="mirror" style="--mirror-color:{color}" dir="rtl"><b>{icon} {label}</b><br>{key}</div>', unsafe_allow_html=True)
            st.write("")

    chart_cols = st.columns(2)
    with chart_cols[0]:
        st.plotly_chart(_volume_obv_chart(data), width="stretch")
    with chart_cols[1]:
        st.plotly_chart(_volatility_chart(data), width="stretch")
    st.plotly_chart(_momentum_chart(data), width="stretch")


def _smart_alerts(stats: Mapping[str, Any]) -> None:
    if stats["win_rate"] > 0.75:
        st.warning("⚠️ Win rate مرتفع بشكل غير طبيعي — تحقق من Overfitting")
    if stats["total_trades"] < 30:
        st.warning("⚠️ حجم العينة صغير، النتائج غير موثوقة إحصائياً")
    if abs(stats["max_drawdown"]) > 0.25:
        st.error("🚨 المخاطرة عالية، قلّل risk_pct")
    if stats["sharpe"] < 0.5:
        st.warning("⚠️ العائد المعدّل للمخاطرة ضعيف")
    if stats["sharpe"] > 3:
        st.warning("🤔 Sharpe غير واقعي، راجع البيانات")


def _equity_chart(equity: pd.DataFrame, benchmark: pd.Series | None = None) -> go.Figure:
    x = _display_index(equity.index)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28])
    fig.add_trace(go.Scatter(x=x, y=equity["Strategy_Equity"], name="Strategy", line=dict(color="#16a34a", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=equity["Buy_Hold_Equity"], name="Buy & Hold", line=dict(color="#6b7280")), row=1, col=1)
    if benchmark is not None:
        fig.add_trace(go.Scatter(x=_display_index(benchmark.index), y=benchmark, name="EGX30", line=dict(color="#2563eb")), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=equity["Drawdown"] * 100, name="Drawdown %", fill="tozeroy", line=dict(color="#dc2626")), row=2, col=1)
    fig.update_layout(height=560, margin=dict(l=20, r=20, t=40, b=20), legend_orientation="h")
    return fig


def _trade_distribution(trades: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=1, cols=3, specs=[[{}, {}, {"type": "domain"}]], subplot_titles=["PnL %", "Entry vs PnL", "Wins / Losses"])
    fig.add_trace(go.Histogram(x=trades["PnL_%"], marker_color="#2563eb", name="PnL %"), row=1, col=1)
    sizes = np.clip(trades["Position_Value"] / max(trades["Position_Value"].max(), 1) * 32, 8, 32)
    colors = np.where(trades["PnL_EGP"] >= 0, "#16a34a", "#dc2626")
    fig.add_trace(go.Scatter(x=trades["Entry_Date"], y=trades["PnL_%"], mode="markers", marker=dict(size=sizes, color=colors), name="Trades"), row=1, col=2)
    counts = trades["PnL_EGP"].ge(0).map({True: "Win", False: "Loss"}).value_counts()
    fig.add_trace(go.Pie(labels=counts.index, values=counts.values, marker_colors=["#16a34a", "#dc2626"], name="Outcome"), row=1, col=3)
    fig.update_layout(height=390, showlegend=False, margin=dict(l=20, r=20, t=55, b=20))
    return fig


def _monthly_heatmap(equity: pd.DataFrame) -> go.Figure:
    returns = equity["Strategy_Equity"].resample("ME").last().pct_change() * 100
    frame = returns.to_frame("Return")
    frame["Year"] = frame.index.year
    frame["Month"] = frame.index.month
    pivot = frame.pivot(index="Year", columns="Month", values="Return").reindex(columns=range(1, 13))
    fig = go.Figure(go.Heatmap(z=pivot.values, x=["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], y=pivot.index, colorscale="RdYlGn", zmid=0, text=np.round(pivot.values, 2), texttemplate="%{text}%", colorbar_title="%"))
    fig.update_layout(height=max(260, 70 + 42 * len(pivot)), margin=dict(l=20, r=20, t=35, b=20))
    return fig


# يشغّل الاختبار التاريخي ويعرض الأداء وسجل الصفقات.
def render_tab4(screen_cfg: ScreenConfig, signal_cfg: SignalConfig, risk_cfg: RiskConfig) -> None:
    rtl_title("Backtest Results")
    data_map: Mapping[str, pd.DataFrame] = st.session_state.data_map
    if not data_map:
        st.info("حمّل البيانات أولاً.")
        return
    ticker = st.selectbox("Backtest ticker", sorted(data_map), key="bt_ticker")
    raw = data_map[ticker]
    dates = st.date_input("Date range", value=(raw.index.min().date(), raw.index.max().date()), min_value=raw.index.min().date(), max_value=raw.index.max().date())
    controls = st.columns(5)
    capital = controls[0].number_input("Capital", 10_000.0, 100_000_000.0, risk_cfg.capital, 10_000.0)
    risk_pct = controls[1].slider("Risk %", 0.1, 2.0, risk_cfg.risk_pct * 100, 0.1)
    atr_mult = controls[2].slider("ATR SL", 0.5, 4.0, risk_cfg.atr_sl_mult, 0.1)
    rr_ratio = controls[3].slider("R:R", 1.0, 5.0, risk_cfg.reward_risk, 0.1)
    min_adx = controls[4].slider("Min ADX", 0.0, 50.0, signal_cfg.min_adx, 1.0)

    data_folder = st.session_state.get("data_folder", "data")
    known = Path(data_folder).name in KNOWN_ADJUSTED_FOLDERS | KNOWN_UNADJUSTED_FOLDERS
    chosen_mode = None if known else st.radio(
        "Dividend mode — مصدر بيانات غير معروف: add = أسعار غير معدّلة بالتوزيعات، none = معدّلة",
        ["add", "none"], index=None, horizontal=True, key="bt_dividend_mode")
    if st.button("Run Backtest", type="primary"):
        start, end = dates if isinstance(dates, tuple) and len(dates) == 2 else (raw.index.min().date(), raw.index.max().date())
        mask = (raw.index.date >= start) & (raw.index.date <= end)
        selected = raw.loc[mask]
        try:
            dividend_mode, dividend_line = resolve_dividend_mode(data_folder, chosen_mode)
        except ValueError as exc:
            dividend_mode = None
            st.error(str(exc))
        if dividend_mode is None:
            pass
        elif len(selected) < 61:
            st.error("الفترة المختارة تحتاج إلى 61 جلسة على الأقل.")
        else:
            cfg = SystemConfig(
                screen=screen_cfg,
                signal=replace(signal_cfg, min_adx=min_adx),
                risk=replace(risk_cfg, capital=capital, risk_pct=risk_pct / 100, atr_sl_mult=atr_mult, reward_risk=rr_ratio),
            )
            with st.spinner("Running event-driven backtest..."):
                stats = backtest(with_dividends(ticker, selected) if dividend_mode == "add" else selected, cfg)
                if not stats["trades"].empty:
                    stats["trades"]["Ticker"] = ticker
                st.session_state.backtest_result = {"ticker": ticker, "stats": stats, "config": cfg, "data_line": dividend_line}

    stored = st.session_state.backtest_result
    if not stored:
        st.info("اضغط Run Backtest لعرض النتائج.")
        return
    stats = stored["stats"]
    st.caption(stored.get("data_line", ""))
    metric_values = [
        ("Total Trades", f"{stats['total_trades']:,}"),
        ("Win Rate", f"{stats['win_rate']:.1%}"),
        ("Profit Factor", f"{stats['profit_factor']:.2f}"),
        ("Avg R", f"{stats['avg_R']:.2f}"),
        ("Max Drawdown", f"{stats['max_drawdown']:.1%}"),
        ("Sharpe", f"{stats['sharpe']:.2f}"),
        ("Final Equity", _money(stats["final_equity"])),
        ("Buy & Hold", f"{stats['buy_hold_return']:.1%}"),
    ]
    for column, (label, value) in zip(st.columns(8), metric_values):
        column.metric(label, value)
    _smart_alerts(stats)

    equity = stats["equity_curve"]
    benchmark = None
    if "EGX30" in data_map and stored["ticker"] != "EGX30" and not equity.empty:
        bench = data_map["EGX30"]["Close"].reindex(equity.index).ffill().dropna()
        benchmark = stored["config"].risk.capital * bench / bench.iloc[0] if not bench.empty else None
    st.plotly_chart(_equity_chart(equity, benchmark), width="stretch")

    trades = stats["trades"]
    if trades.empty:
        st.info("لا توجد صفقات وفق الشروط الحالية. جرّب فترة أطول أو راجع شروط الإشارة.")
    else:
        st.plotly_chart(_trade_distribution(trades), width="stretch")
        st.plotly_chart(_monthly_heatmap(equity), width="stretch")
        display = trades.copy()
        display["Entry_Date"] = pd.to_datetime(display["Entry_Date"]).dt.tz_convert(CAIRO_TZ)
        display["Exit_Date"] = pd.to_datetime(display["Exit_Date"]).dt.tz_convert(CAIRO_TZ)
        styled = display.style.map(lambda value: "color: #16a34a" if value >= 0 else "color: #dc2626", subset=["PnL_EGP", "PnL_%"])
        st.dataframe(styled, width="stretch", hide_index=True)
        st.download_button("Download Trades CSV", display.to_csv(index=False).encode("utf-8-sig"), "egx_trades.csv", "text/csv")
    st.download_button("Download Equity CSV", equity.to_csv().encode("utf-8-sig"), "egx_equity.csv", "text/csv")


def _sector_analysis(data_map: Mapping[str, pd.DataFrame], cfg: SystemConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    trade_frames: list[pd.DataFrame] = []
    signal_rows: list[dict[str, Any]] = []
    for ticker, raw in data_map.items():
        stats = backtest(raw, cfg)
        trades = stats["trades"].copy()
        if not trades.empty:
            trades["Ticker"] = ticker
            trades["Sector"] = _sector(ticker)
            trade_frames.append(trades)
        evaluation = evaluate_4_mirrors(calculate_indicators(raw), cfg.signal)
        signal_rows.append({"Ticker": ticker, "Sector": _sector(ticker), "Signal": evaluation["signal"]})
    trades_all = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    signals = pd.DataFrame(signal_rows)
    rows: list[dict[str, Any]] = []
    for sector in sorted(signals["Sector"].unique()):
        part = trades_all[trades_all["Sector"] == sector] if not trades_all.empty else pd.DataFrame()
        rows.append(
            {
                "Sector": sector,
                "Trades": len(part),
                "Signals": int((signals.loc[signals["Sector"] == sector, "Signal"] == "BUY").sum()),
                "Win Rate": float((part["PnL_EGP"] > 0).mean() * 100) if not part.empty else 0.0,
                "Avg R": float(part["R"].mean()) if not part.empty else 0.0,
                "Avg Return %": float(part["PnL_%"].mean()) if not part.empty else 0.0,
                "Total PnL": float(part["PnL_EGP"].sum()) if not part.empty else 0.0,
            }
        )
    return pd.DataFrame(rows), trades_all


# يقارن نتائج القطاعات ويبرز مخاطر التمركز.
def render_tab5(screen_cfg: ScreenConfig, signal_cfg: SignalConfig, risk_cfg: RiskConfig) -> None:
    rtl_title("مقارنة القطاعات")
    data_map: Mapping[str, pd.DataFrame] = st.session_state.data_map
    if not data_map:
        st.info("حمّل البيانات أولاً.")
        return
    if st.button("Run Sector Analysis", type="primary"):
        with st.spinner("Backtesting sectors..."):
            cfg = SystemConfig(screen=screen_cfg, signal=signal_cfg, risk=risk_cfg)
            st.session_state.sector_results = _sector_analysis(data_map, cfg)
    stored = st.session_state.sector_results
    if stored is None:
        st.info("اضغط Run Sector Analysis لحساب المقارنة.")
        return
    summary, _ = stored
    if summary.empty:
        st.info("لا توجد نتائج قطاعية.")
        return

    cols = st.columns(2)
    fig_return = go.Figure(go.Bar(x=summary["Sector"], y=summary["Avg Return %"], marker_color=np.where(summary["Avg Return %"] >= 0, "#16a34a", "#dc2626")))
    fig_return.update_layout(title="Average Return by Sector", height=360, margin=dict(l=20, r=20, t=55, b=20))
    cols[0].plotly_chart(fig_return, width="stretch")
    fig_signals = go.Figure(go.Bar(x=summary["Sector"], y=summary["Signals"], marker_color="#2563eb"))
    fig_signals.update_layout(title="Current BUY Signals", height=360, margin=dict(l=20, r=20, t=55, b=20))
    cols[1].plotly_chart(fig_signals, width="stretch")

    bubble_size = np.maximum(summary["Trades"].to_numpy(), 1) * 10
    bubble = go.Figure(go.Scatter(x=summary["Sector"], y=summary["Win Rate"], mode="markers+text", text=summary["Trades"], textposition="middle center", marker=dict(size=bubble_size, color=summary["Avg R"], colorscale="RdYlGn", showscale=True, colorbar_title="Avg R")))
    bubble.update_layout(title="Sector Win Rate and Trade Count", yaxis_title="Win Rate %", height=400, margin=dict(l=20, r=20, t=55, b=20))
    st.plotly_chart(bubble, width="stretch")
    st.dataframe(summary, width="stretch", hide_index=True, column_config={"Win Rate": st.column_config.NumberColumn(format="%.1f%%"), "Total PnL": st.column_config.NumberColumn(format="%.0f EGP")})

    best = summary.loc[summary["Avg R"].idxmax()]
    worst = summary.loc[summary["Avg R"].idxmin()]
    st.markdown(
        f'<div class="insight" dir="rtl"><b>أفضل قطاع حالياً:</b> {best["Sector"]} (Avg R {best["Avg R"]:.2f})<br>'
        f'<b>أضعف قطاع:</b> {worst["Sector"]} (Avg R {worst["Avg R"]:.2f})<br>'
        "حافظ على حد أقصى لصفقتين في القطاع الواحد لتقليل مخاطر التمركز.</div>",
        unsafe_allow_html=True,
    )


# يبني بيانات عرض تحليلية من أسهم Demo دون الكتابة في SQLite.
# ponytail: cached — uncached it cost ~32s per page load with 90 tickers.
@st.cache_data(show_spinner=False)
def _demo_analytics_frames(data_map: Mapping[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    alerts: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    alert_id = 1
    for ticker, raw in data_map.items():
        for position in (-35, -18):
            index_position = len(raw) + position
            if index_position < 60 or index_position + 10 >= len(raw):
                continue
            calculated = calculate_indicators(raw.iloc[: index_position + 1])
            evaluation = evaluate_4_mirrors(calculated, SignalConfig())
            row = calculated.iloc[-1]
            entry = float(row["Close"])
            atr = float(row["ATR"])
            timestamp = calculated.index[-1]
            future = raw.iloc[index_position + 1 : index_position + 11]
            exit_price = float(future["Close"].iloc[-1])
            pnl_pct = (exit_price / entry - 1) * 100
            cairo_time = timestamp.tz_convert(CAIRO_TZ)
            sector = _sector(ticker)
            alerts.append(
                {
                    "id": alert_id,
                    "timestamp": timestamp,
                    "ticker": ticker,
                    "action": "BUY",
                    "price": entry,
                    "entry": entry,
                    "sl": entry - 1.5 * atr,
                    "tp": entry + 3 * atr,
                    "atr_pct": float(row["ATR_Pct"]),
                    "adx": float(row["ADX"]),
                    "status": "CONFIRMED" if sum(evaluation["mirrors"].values()) >= 3 else "MISMATCH",
                    "confidence": sum(evaluation["mirrors"].values()) * 25,
                    "hour": cairo_time.hour,
                    "weekday": cairo_time.day_name(),
                    "sector": sector,
                }
            )
            outcomes.append(
                {
                    "alert_id": alert_id,
                    "resolved_date": future.index[-1],
                    "outcome": "WIN" if pnl_pct >= 0 else "LOSS",
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "days_held": len(future),
                    "max_favorable": (float(future["High"].max()) / entry - 1) * 100,
                    "max_adverse": (float(future["Low"].min()) / entry - 1) * 100,
                    "timestamp": timestamp,
                    "ticker": ticker,
                    "adx": float(row["ADX"]),
                    "atr_pct": float(row["ATR_Pct"]),
                    "status": "CONFIRMED",
                    "hour": cairo_time.hour,
                    "weekday": cairo_time.day_name(),
                    "sector": sector,
                }
            )
            alert_id += 1
    return pd.DataFrame(alerts), pd.DataFrame(outcomes)


# يقرأ بيانات التحليلات الحقيقية فقط؛ أخطاء القراءة يعالجها التاب.
def _analytics_frames(days: int) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    alerts = load_alerts(days)
    outcomes = load_outcomes(days)
    return alerts, outcomes, False


# يطبق نطاق التاريخ على الإشارات والنتائج المرتبطة بها.
def _filter_analytics_dates(
    alerts: pd.DataFrame,
    outcomes: pd.DataFrame,
    date_range: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not isinstance(date_range, tuple) or len(date_range) != 2 or alerts.empty:
        return alerts, outcomes
    start, end = date_range
    timestamps = pd.to_datetime(alerts["timestamp"], utc=True)
    mask = (timestamps.dt.date >= start) & (timestamps.dt.date <= end)
    filtered_alerts = alerts.loc[mask].copy()
    if outcomes.empty or "alert_id" not in outcomes:
        return filtered_alerts, outcomes
    ids = set(filtered_alerts["id"])
    return filtered_alerts, outcomes[outcomes["alert_id"].isin(ids)].copy()


# يعرض إشارات TradingView الحية ونتائج تقييمها.
def render_tab6() -> None:
    rtl_title("إشارات TradingView الحيّة")
    try:
        alerts, outcomes, _ = _analytics_frames(30)
    except (sqlite3.Error, pd.errors.DatabaseError, OSError, ValueError) as exc:
        st.error(f"Analytics database error: {exc}")
        return
    if not alerts.empty and not {"id", "timestamp", "ticker", "entry", "sl", "tp", "adx", "atr_pct", "status", "sector"}.issubset(alerts.columns):
        st.error("Analytics data structure error: missing required signal columns")
        return
    if not outcomes.empty and not {"alert_id", "outcome", "pnl_pct"}.issubset(outcomes.columns):
        st.error("Analytics data structure error: missing alert_id, outcome or pnl_pct")
        return

    today = pd.Timestamp.now(tz=CAIRO_TZ).date()
    filter_cols = st.columns([2, 2, 2, 1, 1])
    date_range = filter_cols[0].date_input("Date range", (today - pd.Timedelta(days=30), today), key="live_dates")
    statuses = filter_cols[1].multiselect("Status", ["CONFIRMED", "MISMATCH", "REJECT"], default=["CONFIRMED", "MISMATCH", "REJECT"], key="live_status")
    sectors = sorted(alerts["sector"].dropna().unique()) if not alerts.empty else []
    selected_sectors = filter_cols[2].multiselect("Sector", sectors, default=sectors, key="live_sectors")
    adx_min = filter_cols[3].slider("ADX Min", 0.0, 60.0, 0.0, 1.0, key="live_adx")
    atr_min = filter_cols[4].slider("ATR% Min", 0.0, 10.0, 0.0, 0.1, key="live_atr")
    alerts, outcomes = _filter_analytics_dates(alerts, outcomes, date_range)
    if not alerts.empty:
        alerts = alerts[
            alerts["status"].isin(statuses)
            & alerts["sector"].isin(selected_sectors)
            & (alerts["adx"].fillna(0) >= adx_min)
            & (alerts["atr_pct"].fillna(0) >= atr_min)
        ]
        if not outcomes.empty:
            outcomes = outcomes[outcomes["alert_id"].isin(alerts["id"])]

    if alerts.empty:
        st.info("لا توجد إشارات تطابق الفلاتر الحالية.")
        return
    closed = outcomes[outcomes["outcome"].isin(["WIN", "LOSS"])].copy() if not outcomes.empty else pd.DataFrame()
    if closed.empty:
        st.warning("الإشارات معروضة، ولكن لا توجد نتائج مغلقة (WIN/LOSS) بعد لحساب الأداء.")
    else:
        stats = compute_stats(alerts, closed)
        metric_cols = st.columns(4)
        metric_cols[0].metric("إجمالي الإشارات", stats["total_alerts"])
        metric_cols[1].metric("Win Rate", f"{stats['win_rate']:.1f}%")
        metric_cols[2].metric("Profit Factor", "∞" if stats["profit_factor"] == float("inf") else f"{stats['profit_factor']:.2f}")
        metric_cols[3].metric("Expectancy", f"{stats['expectancy']:.2f}%")

    actions = st.columns(3)
    if actions[0].button("🔄 تحديث", key="refresh_live"):
        st.rerun()
    if actions[1].button("🧮 تقييم الإشارات المعلقة", key="evaluate_live"):
        with st.spinner("Evaluating pending alerts..."):
            folder = os.getenv("DATA_FOLDER", str(Path(__file__).with_name("data")))
            evaluate_pending_alerts(folder, lookback_days=30)
        st.rerun()

    merged = alerts.merge(
        closed[["alert_id", "pnl_pct"]] if not closed.empty else pd.DataFrame(columns=["alert_id", "pnl_pct"]),
        left_on="id",
        right_on="alert_id",
        how="left",
    )
    if merged.empty:
        st.info("لا توجد إشارات تطابق الفلاتر الحالية.")
        return
    display = merged[["timestamp", "ticker", "entry", "sl", "tp", "adx", "atr_pct", "status", "sector", "pnl_pct"]].copy()
    display.columns = ["Timestamp", "Ticker", "Entry", "SL", "TP", "ADX", "ATR%", "Status", "Sector", "PnL%"]
    display["Timestamp"] = pd.to_datetime(display["Timestamp"], utc=True).dt.tz_convert(CAIRO_TZ)
    # نسخة للجدول فقط؛ القيم الأصلية محفوظة للتصدير والرسم.
    table_display = display.copy()
    table_display["PnL%"] = table_display["PnL%"].apply(lambda value: "" if pd.isna(value) else f"{value:+.2f}")
    status_colors = {"CONFIRMED": "#16794b", "MISMATCH": "#b7791f", "REJECT": "#6b7280"}
    styled = table_display.style.map(lambda value: f"background-color:{status_colors.get(value, '#6b7280')};color:white", subset=["Status"])
    styled = styled.map(lambda value: "" if value == "" or pd.isna(value) else ("color:#16a34a" if float(value) >= 0 else "color:#dc2626"), subset=["PnL%"])
    st.dataframe(styled, width="stretch", hide_index=True)
    actions[2].download_button("📥 تصدير CSV", display.to_csv(index=False).encode("utf-8-sig"), "tv_live_signals.csv", "text/csv")

    evaluated = display.dropna(subset=["PnL%"])
    if not evaluated.empty:
        chart = px.scatter(evaluated, x="Timestamp", y="PnL%", color="Sector", size=evaluated["ATR%"].clip(lower=0.1), hover_name="Ticker", title="Signal PnL over time")
        chart.add_hline(y=0, line_dash="dot", line_color="#6b7280")
        st.plotly_chart(chart, width="stretch")


# يحول قاموس معدلات الفوز إلى DataFrame مرتب.
def _rates_frame(values: Mapping[str, float], label: str) -> pd.DataFrame:
    return pd.DataFrame([{label: key, "Win Rate %": value} for key, value in values.items()]).sort_values("Win Rate %", ascending=False) if values else pd.DataFrame(columns=[label, "Win Rate %"])


# يعرض لوحة التحليلات التاريخية والأنماط المكتشفة.
def render_tab7() -> None:
    rtl_title("تحليلات الأداء (Analytics)")
    try:
        alerts, outcomes, _ = _analytics_frames(90)
    except (sqlite3.Error, pd.errors.DatabaseError, OSError, ValueError) as exc:
        st.error(f"Analytics database error: {exc}")
        return
    if not alerts.empty and not {"id", "timestamp", "ticker", "adx", "atr_pct", "status", "sector", "weekday", "hour"}.issubset(alerts.columns):
        st.error("Analytics data structure error: missing required signal columns")
        return
    if not outcomes.empty and not {"alert_id", "outcome", "pnl_pct"}.issubset(outcomes.columns):
        st.error("Analytics data structure error: missing alert_id, outcome or pnl_pct")
        return
    today = pd.Timestamp.now(tz=CAIRO_TZ).date()
    date_range = st.date_input("Date range", (today - pd.Timedelta(days=90), today), key="analytics_dates")
    alerts, outcomes = _filter_analytics_dates(alerts, outcomes, date_range)
    if alerts.empty:
        st.info("لا توجد إشارات تطابق الفلاتر الحالية.")
        return
    if outcomes.empty:
        st.info("لا توجد نتائج كافية لحساب إحصائيات الأداء. يرجى تشغيل الإشارات وانتظار إغلاق الصفقات.")
        return
    closed = outcomes[outcomes["outcome"].isin(["WIN", "LOSS"])].copy()
    closed = closed[closed["alert_id"].isin(alerts["id"])]
    if closed.empty:
        st.info("لا توجد نتائج مغلقة (WIN/LOSS) تطابق الإشارات بعد الفلاتر الحالية. الأداء غير متاح.")
        return
    stats = compute_stats(alerts, closed)

    rtl_title("الأداء الإجمالي", 3)
    values = [
        ("Win Rate", f"{stats['win_rate']:.1f}%"),
        ("Profit Factor", "∞" if stats["profit_factor"] == float("inf") else f"{stats['profit_factor']:.2f}"),
        ("Expectancy", f"{stats['expectancy']:.2f}%"),
        ("Avg Win", f"{stats['avg_win_pct']:.2f}%"),
        ("Avg Loss", f"{stats['avg_loss_pct']:.2f}%"),
        ("Avg Holding", f"{stats['avg_holding_days']:.1f} days"),
        ("Max Wins", stats["consecutive_wins"]),
        ("Max Losses", stats["consecutive_losses"]),
    ]
    row1 = st.columns(4)
    row2 = st.columns(4)
    for column, (label, value) in zip(row1 + row2, values):
        column.metric(label, value)

    sector_table = _rates_frame(stats["win_rate_by_sector"], "Sector")
    weekday_table = _rates_frame(stats["win_rate_by_weekday"], "Weekday")
    hour_rates = {}
    if not closed.empty and "hour" in closed:
        hour_rates = (closed.groupby("hour")["outcome"].apply(lambda values: float((values == "WIN").mean() * 100))).to_dict()
    hour_table = _rates_frame(hour_rates, "Hour")

    rtl_title("Win Rate حسب القطاع", 3)
    if not sector_table.empty:
        st.plotly_chart(px.bar(sector_table, x="Sector", y="Win Rate %", color="Win Rate %", color_continuous_scale="RdYlGn"), width="stretch")

    rtl_title("Win Rate حسب يوم الأسبوع", 3)
    if not weekday_table.empty:
        order = [day for day in WEEKDAY_ORDER if day in set(weekday_table["Weekday"])]
        weekday_table = weekday_table[weekday_table["Weekday"].isin(order)].copy()
        weekday_table["Weekday"] = pd.Categorical(weekday_table["Weekday"], order, ordered=True)
        weekday_table = weekday_table.sort_values("Weekday")
        best = stats["best_weekday"]
        colors = ["#16a34a" if str(day) == best else "#64748b" for day in weekday_table["Weekday"]]
        st.plotly_chart(go.Figure(go.Bar(x=weekday_table["Weekday"].astype(str), y=weekday_table["Win Rate %"], marker_color=colors)), width="stretch")

    rtl_title("Win Rate حسب الساعة", 3)
    if not closed.empty and {"weekday", "hour"}.issubset(closed.columns) and len(closed) >= 10:
        heat = closed.assign(win=(closed["outcome"] == "WIN").astype(float)).pivot_table(index="weekday", columns="hour", values="win", aggfunc="mean") * 100
        st.plotly_chart(px.imshow(heat, text_auto=".0f", color_continuous_scale="RdYlGn", aspect="auto"), width="stretch")
    elif not hour_table.empty:
        st.plotly_chart(px.bar(hour_table.sort_values("Hour"), x="Hour", y="Win Rate %", color="Win Rate %", color_continuous_scale="RdYlGn"), width="stretch")

    rtl_title("Win Rate حسب ADX / ATR", 3)
    indicator_cols = st.columns(2)
    adx_table = _rates_frame(stats["win_rate_by_adx_bucket"], "ADX Bucket")
    atr_table = _rates_frame(stats["win_rate_by_atr_bucket"], "ATR Bucket")
    if not adx_table.empty:
        indicator_cols[0].plotly_chart(px.bar(adx_table, x="ADX Bucket", y="Win Rate %", color="Win Rate %", color_continuous_scale="RdYlGn"), width="stretch")
    if not atr_table.empty:
        indicator_cols[1].plotly_chart(px.bar(atr_table, x="ATR Bucket", y="Win Rate %", color="Win Rate %", color_continuous_scale="RdYlGn"), width="stretch")

    rtl_title("الأنماط المكتشفة", 3)
    icons = {"HIGH": "💡", "MED": "⚠️", "LOW": "ℹ️"}
    patterns = detect_patterns(closed)
    if not patterns:
        st.info("لا توجد عينة كافية لاكتشاف أنماط.")
    for pattern in patterns:
        st.markdown(f'<div class="insight" dir="rtl"><b>{icons[pattern["confidence"]]} {pattern["pattern"]}</b><br>Impact: {pattern["impact"]:+.1f}% | Sample: {pattern["sample_size"]} | Confidence: {pattern["confidence"]}</div><br>', unsafe_allow_html=True)

    export_cols = st.columns(5)
    report_path = Path(__file__).with_name("analytics_report.xlsx")
    if export_cols[0].button("📊 تصدير تقرير Excel", key="export_analytics_excel"):
        with st.spinner("Building Excel report..."):
            export_analytics_report(report_path)
            st.session_state.analytics_report = report_path.read_bytes()
    if st.session_state.analytics_report:
        export_cols[1].download_button("Download Excel", st.session_state.analytics_report, "analytics_report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    export_cols[2].download_button("Sector CSV", sector_table.to_csv(index=False).encode("utf-8-sig"), "analytics_by_sector.csv", "text/csv")
    export_cols[3].download_button("Weekday CSV", weekday_table.to_csv(index=False).encode("utf-8-sig"), "analytics_by_weekday.csv", "text/csv")
    export_cols[4].download_button("Outcomes CSV", outcomes.to_csv(index=False).encode("utf-8-sig"), "analytics_outcomes.csv", "text/csv")


# --------------------------------------------------------------------------------------------------
# Tab 8 — بطاقات الإعداد (Setup Cards). عرض فقط: للمراجعة اليدوية، لا يرسل أوامر ولا يغيّر أي بيانات.
# --------------------------------------------------------------------------------------------------
QUALITY_BADGE: dict[str, tuple[str, str]] = {   # (emoji, لون الشارة)
    "BEST": ("🟠", "#ea580c"),
    "ACTIVE": ("🟢", "#16a34a"),
    "WATCH": ("⚪", "#6b7280"),
}
SECTOR_EMOJI: dict[str, str] = {
    "Banks": "🏦", "Financials": "💼", "RealEstate": "🏗️", "Industrial": "🏭",
    "Telecom": "📡", "Energy": "⚡", "Consumer": "🛒", "Other": "📈",
}


# يبني HTML بطاقة واحدة؛ كل النصوص escaped لأن اسم السهم والملاحظة جايين من بيانات/ملفات المستخدم.
def _setup_card_html(setup: TradeSetup) -> str:
    e = html_lib.escape
    emoji, color = QUALITY_BADGE[setup.quality]
    rr_width = max(8.0, min(setup.rr / 5.0, 1.0) * 100)
    rows = [   # من أعلى سعر لأقل سعر
        ("🎯 الهدف", setup.target, "#16a34a"),
        ("⚡ التفعيل (اختراق)", setup.activation, "#2563eb"),
        ("⛔ الإبطال (إغلاق يومي تحت)", setup.invalidation, "#b45309"),
        ("🛑 وقف الخسارة", setup.stop_loss, "#dc2626"),
    ]
    m_color = MIRRORS_COLOR(setup.mirrors_count)
    price_rows = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #e5e7eb">'
        f'<span>{e(label)}</span><b style="color:{c};direction:ltr;unicode-bidi:isolate">{value:,.2f}</b></div>'
        for label, value, c in rows
    )
    return f'''
<div dir="rtl" style="border:1px solid #d1d5db;border-radius:14px;padding:14px;margin-bottom:14px;background:#ffffff;color:#111827">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div style="font-size:18px;font-weight:700">{SECTOR_EMOJI.get(setup.sector, "📈")} {e(setup.ticker)}
      <span style="font-size:12px;color:#6b7280;font-weight:400">· {e(setup.sector)}</span></div>
    <span><span style="background:{m_color};color:#fff;border-radius:999px;padding:2px 8px;font-size:12px;margin-left:4px">Mirrors {setup.mirrors_count}/4</span>
    <span style="background:{color};color:#fff;border-radius:999px;padding:2px 10px;font-size:12px">{emoji} {e(setup.quality)}</span></span>
  </div>
  <div style="font-size:12px;color:#4b5563;margin:4px 0 8px">{e(PATTERN_AR.get(setup.pattern, setup.pattern))} · ثقة {e(setup.pattern_confidence)}
    · الإغلاق <span style="direction:ltr;unicode-bidi:isolate">{setup.current_close:,.2f}</span> · {e(setup.as_of)}</div>
  {price_rows}
  <div style="margin-top:8px;font-size:12px">R:R = 1:{setup.rr:.2f}
    <div style="background:#e5e7eb;border-radius:6px;height:8px;margin-top:3px">
      <div style="width:{rr_width:.0f}%;background:{color};height:8px;border-radius:6px"></div></div></div>
  <div style="font-size:12px;color:#374151;margin-top:8px;line-height:1.6">{e(setup.note)}</div>
</div>'''


# لون عدد المرايا: 4 أخضر، 3 أصفر، ≤2 أحمر (نفس دلالة mirrors_label في setup_builder).
def MIRRORS_COLOR(count: int) -> str:
    return "#16a34a" if count >= 4 else "#d97706" if count == 3 else "#dc2626"


# جدول البطاقات للتصدير (CSV/PDF).
def _setups_frame(setups: list[TradeSetup]) -> pd.DataFrame:
    columns = ["ticker", "sector", "quality", "pattern", "pattern_confidence", "current_close", "activation",
               "invalidation", "target", "stop_loss", "rr", "mirrors_count", "rsi", "adx", "shares", "target_source", "as_of", "note"]
    return pd.DataFrame([s.to_dict() for s in setups], columns=columns)


# يصدر PDF: fpdf2 + تشكيل عربي لو متاحين، وإلا matplotlib بعناوين إنجليزية (matplotlib لا يشكّل الحروف العربية).
@st.cache_data(show_spinner=False)
def _setups_pdf(frame: pd.DataFrame) -> tuple[bytes | None, str]:
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        from fpdf import FPDF

        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "tahoma.ttf"
        ar = lambda text: get_display(arabic_reshaper.reshape(str(text)))
        pdf = FPDF(orientation="L")
        pdf.add_page()
        pdf.add_font("Tahoma", fname=str(font))
        pdf.set_font("Tahoma", size=14)
        pdf.cell(0, 10, ar("بطاقات الإعداد — EGX"), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Tahoma", size=9)
        for _, row in frame.iterrows():
            line = (f"{row.ticker} | {row.quality} | {row.pattern} | Act {row.activation:,.2f} | Inv {row.invalidation:,.2f} | "
                    f"TP {row.target:,.2f} | SL {row.stop_loss:,.2f} | R:R {row.rr:.2f}")
            pdf.cell(0, 7, line, new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(0, 6, ar(row.note), align="R")
        return bytes(pdf.output()), "fpdf2 (Arabic)"
    except ImportError:
        pass
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages

        cols = ["ticker", "sector", "quality", "pattern", "activation", "invalidation", "target", "stop_loss", "rr", "as_of"]
        table = frame[cols].copy()
        buffer = BytesIO()
        with PdfPages(buffer) as pdf:
            for start in range(0, max(len(table), 1), 20):
                fig, ax = plt.subplots(figsize=(11.7, 8.3))
                ax.axis("off")
                ax.set_title("EGX Setup Cards (manual review only)", fontsize=14)
                part = table.iloc[start:start + 20]
                if len(part):
                    t = ax.table(cellText=part.round(2).astype(str).values, colLabels=cols, loc="center")
                    t.auto_set_font_size(False)
                    t.set_fontsize(8)
                pdf.savefig(fig)
                plt.close(fig)
        return buffer.getvalue(), "matplotlib (English labels; install fpdf2 arabic-reshaper python-bidi for Arabic)"
    except ImportError:
        return None, "PDF unavailable: install fpdf2 (pip install fpdf2 arabic-reshaper python-bidi)"


@st.cache_data(show_spinner=False)
def _cached_setups(data_map: dict[str, pd.DataFrame], signal_cfg: SignalConfig, risk_cfg: RiskConfig) -> list[TradeSetup]:
    return build_setups(data_map, signal_cfg, risk_cfg, demo_mode=set(data_map).issubset(DEMO_TICKERS))


def render_tab8(signal_cfg: SignalConfig, risk_cfg: RiskConfig) -> None:
    rtl_title("🎴 بطاقات الإعداد (Setup Cards)")
    st.markdown('<p dir="rtl">تفعيل عند اختراق أعلى قمة 10 جلسات، إبطال بإغلاق يومي تحت أدنى قاع 10 جلسات، والبطاقة تظهر فقط لو R:R ≥ 2. '
                'للمراجعة اليدوية فقط — ليست توصية تنفيذ.</p>', unsafe_allow_html=True)
    data_map = st.session_state.get("data_map") or {}
    if not data_map:
        st.info("حمّل البيانات من تبويب التحميل (مجلد CSV أو Demo) لعرض البطاقات.")
        return
    setups = _cached_setups(data_map, signal_cfg, risk_cfg)
    st.caption(f"أسهم محمّلة: {len(data_map)} · بطاقات صالحة: {len(setups)}")
    if not setups:
        st.info("لا توجد إعدادات مطابقة للشروط حالياً (R:R ≥ 2 + جودة BEST/ACTIVE/WATCH).")
        return

    f1, f2, f3, f4 = st.columns(4)
    qualities = f1.multiselect("Quality", ["BEST", "ACTIVE", "WATCH"], default=["BEST", "ACTIVE", "WATCH"])
    patterns_all = sorted({s.pattern for s in setups})
    patterns = f2.multiselect("Pattern", patterns_all, default=patterns_all, format_func=lambda p: PATTERN_AR.get(p, p))
    sectors_all = sorted({s.sector for s in setups})
    sectors = f3.multiselect("Sector", sectors_all, default=sectors_all)
    min_rr = f4.slider("Min R:R", 2.0, 6.0, 2.0, 0.1)
    only_full = st.checkbox("اعرض فقط 4/4", value=False, key="cards_only_4of4")
    shown = [s for s in setups if s.quality in qualities and s.pattern in patterns and s.sector in sectors and s.rr >= min_rr
             and (not only_full or s.mirrors_count == 4)]

    if not shown:
        st.info("لا توجد بطاقات بعد تطبيق الفلاتر.")
    else:
        grid = st.columns(3)
        for i, setup in enumerate(shown):
            with grid[i % 3]:
                st.markdown(_setup_card_html(setup), unsafe_allow_html=True)

    frame = _setups_frame(shown)
    if not frame.empty:
        summary = frame[["ticker", "quality", "pattern", "rr", "mirrors_count"]].rename(columns={"mirrors_count": "Mirrors"})
        st.dataframe(summary.style.map(lambda v: f"background-color:{MIRRORS_COLOR(int(v))};color:white", subset=["Mirrors"]),
                     hide_index=True, width="stretch", column_config={"Mirrors": st.column_config.NumberColumn(format="%d / 4")})
    e1, e2 = st.columns(2)
    e1.download_button("⬇️ تصدير CSV", frame.to_csv(index=False).encode("utf-8-sig"), "setup_cards.csv", "text/csv",
                       disabled=frame.empty)
    pdf_bytes, engine = _setups_pdf(frame)
    if pdf_bytes:
        e2.download_button("⬇️ تصدير PDF", pdf_bytes, "setup_cards.pdf", "application/pdf", disabled=frame.empty)
        e2.caption(f"PDF: {engine}")
    else:
        e2.info(engine)


# تبويب 9: إشارات اليوم — اشتري / انتظر / بيع + ملخص المحفظة (المنطق كله في signal_engine.py على محرك v3).
@st.cache_data(show_spinner=False)
def _cached_signals(data_map: dict[str, pd.DataFrame], signal_cfg: SignalConfig, risk_cfg: RiskConfig, portfolio: Any, screen_cfg: ScreenConfig) -> Any:
    result = sigeng.build_signals(data_map, signal_cfg, risk_cfg, portfolio, screen_cfg)
    for frame in (result.buy, result.watch, result.sell):
        if not frame.empty and "السبب" in frame:
            frame["السبب"] = frame["السبب"] + " | " + frame["Ticker"].map(recommendation_warning)
    return result


def render_tab9(screen_cfg: ScreenConfig, signal_cfg: SignalConfig, risk_cfg: RiskConfig) -> None:
    rtl_title("🎯 إشارات اليوم")
    st.markdown('<p dir="rtl">كل إشارة محسوبة من آخر شمعة في البيانات المحمّلة (محرك v3) ومعاها سببها. '
                '<b>اختبارات decision_report.md انتهت بـ ABANDON (ثقة متوسطة)</b> — للمراجعة اليدوية فقط، مش أوامر تنفيذ.</p>',
                unsafe_allow_html=True)
    data_map = st.session_state.get("data_map") or {}
    if not data_map:
        st.info("حمّل البيانات من تبويب التحميل (مجلد CSV أو Demo) لعرض الإشارات.")
        return
    v3 = sigeng.eng
    sig = _cached_signals(data_map, v3.SignalConfig(**asdict(signal_cfg)), v3.RiskConfig(**asdict(risk_cfg)),
                               sigeng.load_portfolio(), v3.ScreenConfig(**asdict(screen_cfg)))
    st.caption(f"آخر شمعة: {sig.as_of} · أسهم: {len(data_map)}")

    def section(title: str, color: str, frame: pd.DataFrame, empty: str) -> None:
        frame = annotate(frame)
        st.markdown(f'<h3 dir="rtl" style="color:{color};border-right:6px solid {color};padding-right:8px">{title} ({len(frame)})</h3>',
                    unsafe_allow_html=True)
        if frame.empty:
            st.caption(empty)
        else:
            st.dataframe(frame.style.set_properties(**{"background-color": f"{color}22"}), hide_index=True, width="stretch")

    section("🟢 اشتري الآن", "#0b7a3e", sig.buy, "لا يوجد سهم اخترق مستوى التنشيط اليوم مع 4/4 مرايا.")
    section("⏸️ انتظر الاختراق (BUY 4/4 في الماسح — لسه تحت التنشيط)", "#b7791f", sig.watch, "لا يوجد سهم بـ4/4 مرايا تحت مستوى التنشيط.")
    section("🔴 بيع", "#c53030", sig.sell, "لا توجد إشارة بيع لمراكز المحفظة.")

    rtl_title("📊 Portfolio Snapshot", 3)
    h = sig.holdings
    c1, c2, c3 = st.columns(3)
    c1.metric("أسهم في المحفظة", len(h))
    cost = float((h["Entry"] * h["Shares"]).sum()) if not h.empty else 0.0
    pnl = float(h["PnL"].sum()) if not h.empty else 0.0
    c2.metric("PnL إجمالي (قبل العمولة والضريبة)", _money(pnl), f"{pnl / cost:+.2%}" if cost else None)
    c3.metric("تنبيهات", len(sig.alerts))
    if not h.empty:
        st.dataframe(h, hide_index=True, width="stretch")
    for alert in sig.alerts:
        st.warning(alert)

    with st.expander("✏️ تعديل المحفظة (portfolio.csv)"):
        st.caption("الوقف فاضي → −15% من سعر الدخول افتراضياً. الهدف اختياري. الحفظ يكتب portfolio.csv.")
        edited = st.data_editor(sigeng.load_portfolio(), num_rows="dynamic", hide_index=True, width="stretch", key="portfolio_editor")
        if st.button("💾 حفظ المحفظة"):
            sigeng.save_portfolio(edited)
            st.success("اتحفظت.")
            st.rerun()

    message = sigeng.telegram_message(sig)
    if st.button("📨 إرسال التنبيهات على Telegram", disabled=message is None):
        result = sigeng.notify(sig)
        st.info(f"Telegram: {result}" + (" — DRY-RUN (مفيش توكن في .env)" if result.get("dry_run") else ""))


# تبويب 10: سجل Paper Trading وإدخال الصفقات والتقييم الأسبوعي.
def render_tab10() -> None:
    rtl_title("📝 Paper Trading Journal")
    st.caption("سجل تجريبي فقط. الأسعار والنتائج لا تُرسل إلى وسيط ولا تنفذ أوامر حقيقية.")
    try:
        init_paper_db()
        trades = load_paper_trades()
        campaign = campaign_progress()
    except (sqlite3.Error, OSError, ValueError) as exc:
        st.error(f"تعذر فتح سجل Paper Trading: {exc}")
        return

    flash = st.session_state.pop("paper_flash", None)
    if flash:
        st.success(flash)
    telegram_ready = telegram_is_configured()
    notify_telegram = st.toggle(
        "إرسال تحديثات الصفقات إلى Telegram",
        value=telegram_ready,
        disabled=not telegram_ready,
        key="paper_telegram_notify",
    )
    if not telegram_ready:
        st.warning("Telegram غير مضبوط؛ الصفقات ستُسجل محليًا فقط.")
    st.progress(
        float(campaign["progress"]),
        text=(
            f"تجربة 6 شهور: اليوم {campaign['elapsed_days']} من {campaign['target_days']} · "
            f"متبقي {campaign['remaining_days']} يوم · {campaign['start_date']} → {campaign['end_date']} · "
            f"الهدف {campaign['closed_trades']} من {campaign['target_trades']} صفقة مغلقة"
        ),
    )

    closed_stats = performance_summary(trades)
    open_count = int((trades["status"] == "OPEN").sum()) if not trades.empty else 0
    metric_cols = st.columns(4)
    metric_cols[0].metric("صفقات مفتوحة", open_count)
    metric_cols[1].metric("صفقات مغلقة", closed_stats["trades"])
    metric_cols[2].metric("صافي PnL", _money(closed_stats["net_pnl"]))
    metric_cols[3].metric("Win Rate", f"{closed_stats['win_rate']:.1f}%")

    with st.expander("Universe v90"):
        st.dataframe(universe_table(), hide_index=True, width="stretch")
    rtl_title("إدخال صفقة ورقية", 3)
    now_cairo = pd.Timestamp.now(tz=CAIRO_TZ)
    with st.form("paper_trade_entry", clear_on_submit=True):
        row1 = st.columns([1.2, 1, 1, 1])
        ticker = row1[0].selectbox("Ticker", UNIVERSE)
        entry_date = row1[1].date_input("Entry date", now_cairo.date())
        entry_time = row1[2].time_input("Entry time (Cairo)", now_cairo.time().replace(second=0, microsecond=0))
        mirrors = row1[3].select_slider("Mirrors", options=[0, 1, 2, 3, 4], value=4)
        row2 = st.columns(4)
        entry = row2[0].number_input("Entry (EGP)", min_value=0.01, value=50.0, step=0.05)
        shares = row2[1].number_input("Shares", min_value=1, value=100, step=1)
        stop_loss = row2[2].number_input("Stop Loss", min_value=0.01, value=47.5, step=0.05)
        take_profit = row2[3].number_input("Take Profit", min_value=0.01, value=55.0, step=0.05)
        setup = st.selectbox("Setup", ["4 Mirrors", "Breakout", "Pullback", "Reversal", "Manual"])
        notes = st.text_area("ملاحظات وخطة الصفقة", placeholder="سبب الدخول، حالة السوق، وما الذي يبطل الفكرة")
        risk_egp = max((entry - stop_loss) * shares, 0.0)
        planned_rr = (take_profit - entry) / (entry - stop_loss) if entry > stop_loss else 0.0
        st.caption(f"المخاطرة المخططة: {_money(risk_egp)} · R:R مخطط = 1:{planned_rr:.2f}")
        submitted = st.form_submit_button("➕ إضافة الصفقة", type="primary")
    if submitted:
        try:
            trade_id = add_paper_trade(
                PaperTradeInput(
                    ticker=ticker,
                    entry_time=datetime.combine(entry_date, entry_time, tzinfo=CAIRO_TZ),
                    entry=float(entry),
                    shares=int(shares),
                    stop_loss=float(stop_loss),
                    take_profit=float(take_profit),
                    mirrors=int(mirrors),
                    setup=setup,
                    notes=notes,
                )
            )
            delivery = ""
            if notify_telegram:
                try:
                    stored = load_paper_trades().loc[lambda frame: frame["id"] == trade_id].iloc[0]
                    send_telegram(format_open_message(stored))
                    delivery = " وتم إرسال Telegram"
                except RuntimeError as exc:
                    st.warning(f"تم حفظ الصفقة لكن فشل Telegram: {exc}")
            st.session_state.paper_flash = f"تم تسجيل الصفقة الورقية #{trade_id}{delivery}."
            st.rerun()
        except (sqlite3.Error, OSError, ValueError) as exc:
            st.error(str(exc))

    open_trades = trades[trades["status"] == "OPEN"].copy() if not trades.empty else pd.DataFrame()
    rtl_title("إغلاق صفقة", 3)
    if open_trades.empty:
        st.info("لا توجد صفقات ورقية مفتوحة.")
    else:
        labels = {
            int(row.id): f"#{int(row.id)} · {row.ticker} · {row.entry:,.2f} EGP · {int(row.shares)} سهم"
            for row in open_trades.itertuples()
        }
        with st.form("paper_trade_close"):
            close_cols = st.columns(4)
            trade_id = close_cols[0].selectbox("Open trade", list(labels), format_func=labels.get)
            exit_date = close_cols[1].date_input("Exit date", now_cairo.date())
            exit_time = close_cols[2].time_input("Exit time (Cairo)", now_cairo.time().replace(second=0, microsecond=0), key="paper_exit_time")
            selected_entry = float(open_trades.loc[open_trades["id"] == trade_id, "entry"].iloc[0])
            exit_price = close_cols[3].number_input("Exit price", min_value=0.01, value=selected_entry, step=0.05)
            close_submitted = st.form_submit_button("✅ إغلاق وحساب النتيجة")
        if close_submitted:
            try:
                result = close_paper_trade(
                    int(trade_id),
                    datetime.combine(exit_date, exit_time, tzinfo=CAIRO_TZ),
                    float(exit_price),
                )
                delivery = ""
                if notify_telegram:
                    try:
                        stored = load_paper_trades().loc[lambda frame: frame["id"] == trade_id].iloc[0]
                        send_telegram(format_close_message(stored, result))
                        delivery = " · Telegram sent"
                    except RuntimeError as exc:
                        st.warning(f"تم إغلاق الصفقة لكن فشل Telegram: {exc}")
                st.session_state.paper_flash = (
                    f"{result['outcome']} · PnL {_money(float(result['pnl_egp']))} · "
                    f"{float(result['pnl_pct']):+.2f}% · {float(result['r_multiple']):+.2f}R{delivery}"
                )
                st.rerun()
            except (sqlite3.Error, OSError, ValueError) as exc:
                st.error(str(exc))

    rtl_title("سجل الصفقات", 3)
    if trades.empty:
        st.info("السجل فارغ. أضف أول صفقة ورقية من النموذج أعلاه.")
    else:
        filter_cols = st.columns(3)
        statuses = filter_cols[0].multiselect("Status", ["OPEN", "CLOSED"], default=["OPEN", "CLOSED"], key="paper_status")
        tickers = sorted(trades["ticker"].unique())
        selected_tickers = filter_cols[1].multiselect("Tickers", tickers, default=tickers, key="paper_tickers")
        sectors = sorted(trades["sector"].unique())
        selected_sectors = filter_cols[2].multiselect("Sectors", sectors, default=sectors, key="paper_sectors")
        shown = trades[
            trades["status"].isin(statuses)
            & trades["ticker"].isin(selected_tickers)
            & trades["sector"].isin(selected_sectors)
        ].copy()
        shown["Entry Time"] = shown["entry_time"].dt.tz_convert(CAIRO_TZ)
        shown["Exit Time"] = shown["exit_time"].dt.tz_convert(CAIRO_TZ)
        display_cols = [
            "id", "ticker", "sector", "status", "Entry Time", "entry", "shares",
            "stop_loss", "take_profit", "mirrors", "Exit Time", "exit_price",
            "pnl_egp", "pnl_pct", "r_multiple", "outcome", "setup", "notes",
        ]
        display = shown[display_cols].rename(
            columns={
                "id": "ID", "ticker": "Ticker", "sector": "Sector", "status": "Status",
                "entry": "Entry", "shares": "Shares", "stop_loss": "SL", "take_profit": "TP",
                "mirrors": "Mirrors", "exit_price": "Exit", "pnl_egp": "PnL EGP",
                "pnl_pct": "PnL %", "r_multiple": "R", "outcome": "Outcome",
                "setup": "Setup", "notes": "Notes",
            }
        )
        display = annotate(display)
        styled = display.style.map(
            lambda value: "" if pd.isna(value) else ("color:#16a34a" if value >= 0 else "color:#dc2626"),
            subset=["PnL EGP", "PnL %", "R"],
        )
        st.dataframe(styled, hide_index=True, width="stretch")
        st.download_button(
            "📥 تصدير Journal CSV",
            display.to_csv(index=False).encode("utf-8-sig"),
            "paper_trading_journal.csv",
            "text/csv",
        )

    rtl_title("التقييم الأسبوعي", 3)
    selected_week = st.date_input("اختر أي يوم داخل الأسبوع", now_cairo.date(), key="paper_week")
    weekly, stats, week_start, week_end = weekly_performance(trades, selected_week)
    st.caption(f"أسبوع EGX: الأحد {week_start} إلى السبت {week_end} · التقييم على الصفقات المغلقة")
    week_cols = st.columns(6)
    week_cols[0].metric("الصفقات", stats["trades"])
    week_cols[1].metric("Win Rate", f"{stats['win_rate']:.1f}%")
    week_cols[2].metric("Profit Factor", "∞" if stats["profit_factor"] == float("inf") else f"{stats['profit_factor']:.2f}")
    week_cols[3].metric("Avg R", f"{stats['avg_r']:+.2f}R")
    week_cols[4].metric("Net PnL", _money(stats["net_pnl"]))
    week_cols[5].metric("Grade", stats["grade"])
    st.markdown(f'<div class="insight" dir="rtl"><b>التقييم: {stats["grade"]}</b><br>{stats["message"]}</div>', unsafe_allow_html=True)
    if st.button("📨 إرسال الملخص الأسبوعي إلى Telegram", disabled=not telegram_ready, key="paper_weekly_telegram"):
        try:
            send_telegram(format_weekly_message(stats, week_start, week_end))
            st.success("تم إرسال الملخص الأسبوعي إلى Telegram.")
        except RuntimeError as exc:
            st.error(f"فشل إرسال الملخص: {exc}")
    if 0 < stats["trades"] < 5:
        st.warning("حجم العينة الأسبوعية أقل من 5 صفقات؛ لا تعتمد على الدرجة وحدها.")
    closed_week = weekly[weekly["status"] == "CLOSED"].copy() if not weekly.empty else pd.DataFrame()
    if not closed_week.empty:
        closed_week["Exit"] = closed_week["exit_time"].dt.tz_convert(CAIRO_TZ)
        chart_cols = st.columns(2)
        chart_cols[0].plotly_chart(
            px.bar(closed_week.sort_values("Exit"), x="Exit", y="pnl_egp", color="outcome", hover_name="ticker", title="Weekly PnL by trade", color_discrete_map={"WIN": "#16a34a", "LOSS": "#dc2626", "BREAKEVEN": "#6b7280"}),
            width="stretch",
        )
        by_sector = closed_week.groupby("sector", as_index=False).agg(PnL=("pnl_egp", "sum"), Trades=("id", "count"))
        chart_cols[1].plotly_chart(
            px.bar(by_sector.sort_values("PnL", ascending=False), x="sector", y="PnL", color="PnL", color_continuous_scale="RdYlGn", title="Weekly PnL by sector"),
            width="stretch",
        )


def main() -> None:
    _init_state()
    screen_cfg, signal_cfg, risk_cfg, sector_limit = _sidebar()
    rtl_title("EGX Trading System v3", 1)
    tabs = st.tabs(["📥 تحميل البيانات", "🔍 ماسح السوق", "📈 تحليل سهم", "🧪 اختبار خلفي", "📊 القطاعات", "📡 إشارات TradingView", "📊 تحليلات الأداء", "🎴 بطاقات الإعداد", "🎯 إشارات اليوم", "📝 تداول ورقي"])
    with st.expander("⚠️ ملاحظة عن Universe v90"):
        st.warning("Universe v90 بحثي وورقي فقط: A/B بديل سيولة غير رسمي؛ نوع الأداة على Yahoo متعارض وOpen غالباً سعر مرجعي. لا توجد أهلية T+0 أو هامش موثقة.")
    with tabs[0]:
        render_tab1()
    with tabs[1]:
        render_tab2(screen_cfg, signal_cfg, risk_cfg, sector_limit)
    with tabs[2]:
        render_tab3(signal_cfg, risk_cfg)
    with tabs[3]:
        render_tab4(screen_cfg, signal_cfg, risk_cfg)
    with tabs[4]:
        render_tab5(screen_cfg, signal_cfg, risk_cfg)
    with tabs[5]:
        render_tab6()
    with tabs[6]:
        render_tab7()
    with tabs[7]:
        render_tab8(signal_cfg, risk_cfg)
    with tabs[8]:
        render_tab9(screen_cfg, signal_cfg, risk_cfg)
    with tabs[9]:
        render_tab10()


if __name__ == "__main__":
    main()
