"""بناء "بطاقة الإعداد" (Setup Card) لكل سهم: مستوى تفعيل (اختراق)، مستوى إبطال، هدف، وقف خسارة، وجودة الإعداد.

القواعد (حسب المواصفات):
    activation   = أعلى قمة في آخر 10 جلسات
    invalidation = أدنى قاع في آخر 10 جلسات (EMA50 كبديل فقط لو القاع مش تحت التفعيل)
    target       = activation + 2.5 × (activation − invalidation)، أو قمة سابقة لو فيه مقاومة حقيقية قبلها (اختيار متحفظ)
    stop_loss    = invalidation
    rr           = (target − activation) / (activation − stop_loss)  ← لو أقل من 2.0 مفيش بطاقة
الجودة: BEST ثم ACTIVE ثم WATCH (لو مفيش ولا واحدة تنطبق → مفيش بطاقة).
لا يعدّل egx_4_mirrors_v3.py: بيستخدم المؤشرات وتقييم المرايا الأربع كما هي.
"""
from __future__ import annotations
from egx_lists import DEMO_TICKERS, filter_universe, recommendation_warning

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import pandas as pd

from egx_4_mirrors_v3 import SECTOR_MAP, RiskConfig, SignalConfig, calculate_indicators, evaluate_4_mirrors
from pattern_detector import detect_breakout_pattern

PATTERN_AR: dict[str, str] = {
    "SYMMETRICAL_TRIANGLE": "مثلث متماثل",
    "CUP_AND_HANDLE": "كوب وعروة",
    "HIGHER_LOWS": "قيعان صاعدة",
    "BULL_FLAG": "علم صاعد",
    "NONE": "بدون نموذج واضح",
}
QUALITY_AR: dict[str, str] = {"BEST": "أفضل إعداد", "ACTIVE": "إعداد نشط", "WATCH": "تحت المراقبة"}
MIN_RR = 2.0
ACTIVATION_LOOKBACK = 10
PRIOR_PEAK_LOOKBACK = 120


@dataclass(frozen=True)
class TradeSetup:
    """بطاقة إعداد واحدة لسهم واحد (كل الأسعار بالجنيه)."""
    ticker: str
    sector: str
    quality: str
    pattern: str
    pattern_confidence: str
    activation: float
    invalidation: float
    target: float
    stop_loss: float
    rr: float
    current_close: float
    distance_to_activation_pct: float
    mirrors_count: int
    rsi: float
    adx: float
    volume_confirmed: bool
    shares: int
    target_source: str
    note: str
    as_of: str
    mirrors: dict[str, bool] = field(default_factory=dict)
    key_levels: dict[str, Any] = field(default_factory=dict)

    # يحوّل البطاقة لقاموس (للجداول والتصدير).
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# قيمة رقمية صالحة (مش NaN ولا لانهائية).
def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


# وسم عدد المرايا (يُضاف لملاحظة بطاقات BEST لأن BEST مش شرطها 4/4).
def mirrors_label(count: int) -> str:
    if count >= 4:
        return "📊 Mirrors: 4/4 — إشارة كاملة ✅"
    if count == 3:
        return "📊 Mirrors: 3/4 — Setup فقط (ينتظر التأكيد) ⚠️"
    return f"📊 Mirrors: {count}/4 — Pattern فقط (خطر عالي) 🔴"


# يحدد جودة الإعداد بالترتيب: BEST ← ACTIVE ← WATCH.
def _quality(rsi: float, adx: float, pattern: dict[str, Any], volume_ok: bool, mirrors_count: int, rr: float) -> Optional[str]:
    has_pattern = pattern["pattern"] != "NONE"
    if 55 <= rsi <= 65 and adx > 25 and pattern["confidence"] == "HIGH" and has_pattern and volume_ok:
        return "BEST"
    if mirrors_count == 4 and rr >= 2.5:
        return "ACTIVE"
    if mirrors_count == 3 and has_pattern:
        return "WATCH"
    return None


# يبني الجملة العربية من النمط + الحالة.
def _arabic_note(quality: str, pattern: dict[str, Any], close: float, activation: float, invalidation: float,
                 mirrors_count: int, target_source: str) -> str:
    distance = (activation - close) / close * 100
    where = "عند مستوى التفعيل" if distance <= 0.25 else f"على بُعد {distance:.1f}% من التفعيل"
    pattern_part = pattern["arabic_note"] if pattern["pattern"] != "NONE" else "بدون نموذج فني واضح"
    target_part = "الهدف عند قمة سابقة" if target_source == "PRIOR_PEAK" else "الهدف 2.5 ضعف المخاطرة"
    return (f"{QUALITY_AR[quality]}: {pattern_part}. السعر {where}، والإعداد يُبطَل بإغلاق يومي تحت {invalidation:,.2f}. "
            f"{mirrors_count}/4 مرايا متحققة، و{target_part}. للمراجعة اليدوية فقط — ليست أمر تنفيذ.")


# يبني بطاقة إعداد للسهم أو يرجع None لو مفيش إعداد صالح (R:R < 2 أو جودة غير مطابقة أو بيانات ناقصة).
def build_setup(ticker: str, df: pd.DataFrame, signal_cfg: SignalConfig, risk_cfg: RiskConfig) -> Optional[TradeSetup]:
    if df is None or len(df) < 60:
        return None
    data = df if "ADX" in df.columns else calculate_indicators(df)
    data = data.dropna(subset=["High", "Low", "Close"])
    if len(data) < 60:
        return None
    last = data.iloc[-1]
    if not all(_finite(last.get(col)) for col in ("Close", "RSI", "ADX", "EMA_50", "Volume", "Volume_SMA20")):
        return None

    recent = data.tail(ACTIVATION_LOOKBACK)
    activation = float(recent["High"].max())
    invalidation = float(recent["Low"].min())
    if not invalidation < activation:
        invalidation = float(last["EMA_50"])   # بديل فقط لو القاع مش تحت التفعيل
    if not (0 < invalidation < activation):
        return None
    risk_per_share = activation - invalidation
    stop_loss = invalidation

    measured = activation + 2.5 * risk_per_share
    prior = data.iloc[-PRIOR_PEAK_LOOKBACK:-ACTIVATION_LOOKBACK]
    prior_peak = float(prior["High"].max()) if len(prior) else float("nan")
    if _finite(prior_peak) and activation < prior_peak < measured:
        target, target_source = prior_peak, "PRIOR_PEAK"   # مقاومة حقيقية قبل الهدف المقاس → نلتزم بيها
    else:
        target, target_source = measured, "MEASURED_2_5R"
    rr = (target - activation) / (activation - stop_loss)
    if rr < MIN_RR:
        return None

    evaluation = evaluate_4_mirrors(data, signal_cfg)
    mirrors = {key: bool(value) for key, value in evaluation["mirrors"].items()}
    mirrors_count = sum(mirrors.values())
    rsi, adx = float(last["RSI"]), float(last["ADX"])
    volume_ok = bool(float(last["Volume"]) > signal_cfg.volume_multiplier * float(last["Volume_SMA20"]))
    pattern = detect_breakout_pattern(data)
    quality = _quality(rsi, adx, pattern, volume_ok, mirrors_count, rr)
    if quality is None:
        return None

    close = float(last["Close"])
    budget = risk_cfg.capital * risk_cfg.risk_pct
    shares = int(budget // risk_per_share) if risk_per_share > 0 else 0
    shares = min(shares, int(risk_cfg.capital * risk_cfg.max_position_pct // activation))
    as_of = data.index[-1]
    as_of_text = as_of.tz_convert("Africa/Cairo").strftime("%Y-%m-%d") if getattr(as_of, "tzinfo", None) else str(as_of)[:10]
    return TradeSetup(
        ticker=ticker.upper(),
        sector=SECTOR_MAP.get(ticker.upper(), "Other"),
        quality=quality,
        pattern=pattern["pattern"],
        pattern_confidence=pattern["confidence"],
        activation=round(activation, 3),
        invalidation=round(invalidation, 3),
        target=round(target, 3),
        stop_loss=round(stop_loss, 3),
        rr=round(rr, 2),
        current_close=round(close, 3),
        distance_to_activation_pct=round((activation - close) / close * 100, 2),
        mirrors_count=mirrors_count,
        rsi=round(rsi, 1),
        adx=round(adx, 1),
        volume_confirmed=volume_ok,
        shares=max(shares, 0),
        target_source=target_source,
        note=(mirrors_label(mirrors_count) + " — " if quality == "BEST" else "")
        + _arabic_note(quality, pattern, close, activation, invalidation, mirrors_count, target_source)
        + " | " + recommendation_warning(ticker),
        as_of=as_of_text,
        mirrors=mirrors,
        key_levels=dict(pattern.get("key_levels", {})),
    )


# يبني بطاقات لكل الأسهم المحمّلة ويرتبها: الجودة ثم R:R.
def build_setups(data_map: dict[str, pd.DataFrame], signal_cfg: SignalConfig, risk_cfg: RiskConfig, *, demo_mode: bool | None = None) -> list[TradeSetup]:
    order = {"BEST": 0, "ACTIVE": 1, "WATCH": 2}
    if demo_mode is None:
        demo_mode = bool(data_map) and set(data_map).issubset(DEMO_TICKERS)
    setups = [s for s in (build_setup(t, d, signal_cfg, risk_cfg) for t, d in filter_universe(data_map, demo_mode=demo_mode).items()) if s is not None]
    return sorted(setups, key=lambda s: (order[s.quality], -s.rr))
