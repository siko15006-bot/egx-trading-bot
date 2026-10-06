"""كاشف النماذج الفنية لطبقة Setup Cards (Breakout Swing).

كل دالة تستقبل DataFrame فيه أعمدة High/Low/Close/Volume مرتبة زمنياً، وترجع None لو النموذج غير موجود، أو:
    {"pattern": str, "confidence": "HIGH"|"MED"|"LOW", "key_levels": {...}, "arabic_note": str}

مبادئ: نستخدم قمم/قيعان محلية حقيقية (swing points) وليس شموع منفردة، ولا نقدّر أي قيمة غير موجودة في البيانات.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

CONFIDENCE_RANK: dict[str, int] = {"HIGH": 3, "MED": 2, "LOW": 1}
NO_PATTERN: dict[str, Any] = {
    "pattern": "NONE",
    "confidence": "LOW",
    "key_levels": {},
    "levels": {},
    "arabic_note": "لا يوجد نموذج فني واضح في الفترة الأخيرة",
}


# يتحقق من وجود الأعمدة المطلوبة وعدد كافٍ من الشموع.
def _ready(df: pd.DataFrame, window: int) -> bool:
    needed = {"High", "Low", "Close"}
    return isinstance(df, pd.DataFrame) and needed.issubset(df.columns) and len(df.dropna(subset=list(needed))) >= window


# يرجع مواضع القمم/القيعان المحلية: نقطة أعلى (أو أقل) من order شمعة على كل جانب.
def _swing_points(values: np.ndarray, order: int, kind: str) -> list[int]:
    points: list[int] = []
    for i in range(order, len(values) - order):
        segment = values[i - order: i + order + 1]
        if kind == "high" and values[i] == segment.max() and values[i] > values[i - 1]:
            points.append(i)
        elif kind == "low" and values[i] == segment.min() and values[i] < values[i - 1]:
            points.append(i)
    return points


# انحدار خطي بسيط: يرجع (الميل، الثابت، معامل التحديد R²).
def _linear_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
    return float(slope), float(intercept), max(0.0, 1.0 - ss_res / ss_tot)


# مثلث متماثل: قمم هابطة + قيعان صاعدة تتقارب، والاختراق فوق الضلع العلوي.
def detect_symmetrical_triangle(df: pd.DataFrame, window: int = 30) -> Optional[dict[str, Any]]:
    if not _ready(df, window):
        return None
    data = df.tail(window)
    highs, lows = data["High"].to_numpy(float), data["Low"].to_numpy(float)
    hi_idx, lo_idx = _swing_points(highs, 2, "high"), _swing_points(lows, 2, "low")
    if len(hi_idx) < 2 or len(lo_idx) < 2:
        return None
    hs, hb, hr2 = _linear_fit(np.array(hi_idx, float), highs[hi_idx])
    ls, lb, lr2 = _linear_fit(np.array(lo_idx, float), lows[lo_idx])
    price = float(data["Close"].iloc[-1])
    # الضلع العلوي لازم يهبط والسفلي يصعد بشكل ملحوظ (أكثر من 0.05% من السعر لكل شمعة)
    if not (hs < -0.0005 * price and ls > 0.0005 * price):
        return None
    last = window - 1
    upper, lower = hs * last + hb, ls * last + lb
    first_width = (hb) - (lb)
    if upper <= lower or first_width <= 0 or (upper - lower) > 0.75 * first_width:
        return None   # لازم يكون فيه تقارب حقيقي (العرض الحالي أقل من 75% من البداية)
    touches = len(hi_idx) + len(lo_idx)
    fit = min(hr2, lr2)
    confidence = "HIGH" if touches >= 6 and fit >= 0.8 else "MED" if touches >= 5 and fit >= 0.6 else "LOW"
    height = first_width
    return {
        "pattern": "SYMMETRICAL_TRIANGLE",
        "confidence": confidence,
        "key_levels": {"breakout": round(upper, 4), "support": round(lower, 4), "pattern_height": round(height, 4),
                       "measured_target": round(upper + height, 4), "touches": touches},
        "arabic_note": f"مثلث متماثل: قمم هابطة وقيعان صاعدة ({touches} لمسات)، الاختراق فوق {upper:,.2f}",
    }


# كوب وعروة: قاع مستدير بين حافتين متقاربتين، ثم تصحيح صغير (العروة) في النصف العلوي للكوب.
def detect_cup_and_handle(df: pd.DataFrame, window: int = 60) -> Optional[dict[str, Any]]:
    if not _ready(df, window):
        return None
    data = df.tail(window)
    highs, lows, closes = data["High"].to_numpy(float), data["Low"].to_numpy(float), data["Close"].to_numpy(float)
    third = window // 3
    left_i = int(np.argmax(highs[:third]))
    bottom_i = third + int(np.argmin(lows[third: 2 * third]))
    handle_len = max(5, window // 8)
    right_zone = slice(2 * third, window - handle_len + 2)
    right_i = 2 * third + int(np.argmax(highs[right_zone]))
    left_rim, right_rim, bottom = highs[left_i], highs[right_i], lows[bottom_i]
    depth = (min(left_rim, right_rim) - bottom) / max(left_rim, right_rim)
    if not (0.10 <= depth <= 0.40):
        return None   # عمق الكوب المعتاد 10–40%
    if abs(left_rim - right_rim) / left_rim > 0.06:
        return None   # الحافتان متقاربتان (فرق ≤ 6%)
    handle = data.iloc[right_i + 1:]
    if len(handle) < 3:
        return None
    handle_low = float(handle["Low"].min())
    rim = float(max(left_rim, right_rim))
    midpoint = bottom + (rim - bottom) / 2
    handle_drop = (rim - handle_low) / (rim - bottom)
    if not (0.05 <= handle_drop <= 0.5) or handle_low < midpoint or closes[-1] > rim * 1.02:
        return None   # العروة تصحيح صغير فوق منتصف الكوب، ولسه ما اخترقش بقوة
    # استدارة القاع: النصف الأوسط من الكوب يقضي وقتاً قرب القاع (مش شكل V حاد)
    middle = lows[left_i: right_i + 1]
    roundness = float(np.mean(middle <= bottom + 0.35 * (rim - bottom))) if len(middle) else 0.0
    vol_ok = "Volume" in data and float(handle["Volume"].mean()) < float(data["Volume"].iloc[left_i:right_i + 1].mean())
    confidence = "HIGH" if roundness >= 0.25 and vol_ok and handle_drop <= 0.33 else "MED" if roundness >= 0.15 else "LOW"
    return {
        "pattern": "CUP_AND_HANDLE",
        "confidence": confidence,
        "key_levels": {"breakout": round(rim, 4), "cup_bottom": round(float(bottom), 4), "handle_low": round(handle_low, 4),
                       "cup_depth_pct": round(float(depth) * 100, 2), "measured_target": round(float(rim + (rim - bottom)), 4)},
        "arabic_note": f"كوب وعروة: عمق {depth * 100:.0f}%، العروة فوق منتصف الكوب، الاختراق فوق الحافة {rim:,.2f}",
    }


# قيعان صاعدة: 3 قيعان محلية متتالية كل واحد أعلى من اللي قبله، والمقاومة أعلى قمة في الفترة.
def detect_higher_lows(df: pd.DataFrame, window: int = 30) -> Optional[dict[str, Any]]:
    if not _ready(df, window):
        return None
    data = df.tail(window)
    lows = data["Low"].to_numpy(float)
    lo_idx = _swing_points(lows, 2, "low")
    if len(lo_idx) < 3:
        return None
    seq = lows[lo_idx]
    run = 1
    for a, b in zip(seq[:-1], seq[1:]):
        run = run + 1 if b > a else 1
    if run < 3:
        return None   # آخر 3 قيعان على الأقل لازم تكون صاعدة
    resistance = float(data["High"].max())
    rise = (seq[-1] - seq[-run]) / seq[-run]
    confidence = "HIGH" if run >= 4 and rise >= 0.03 else "MED" if rise >= 0.015 else "LOW"
    return {
        "pattern": "HIGHER_LOWS",
        "confidence": confidence,
        "key_levels": {"breakout": round(resistance, 4), "last_higher_low": round(float(seq[-1]), 4),
                       "prior_low": round(float(seq[-2]), 4), "consecutive_higher_lows": run},
        "arabic_note": f"قيعان صاعدة ({run} قيعان متتالية) تحت مقاومة {resistance:,.2f} — ضغط شرائي متزايد",
    }


# علم صاعد: صعود قوي سريع (السارية) ثم تماسك ضيق مائل للهبوط أو عرضي مع هدوء في الحجم.
def detect_bull_flag(df: pd.DataFrame, window: int = 20) -> Optional[dict[str, Any]]:
    if not _ready(df, window):
        return None
    data = df.tail(window)
    closes, highs, lows = data["Close"].to_numpy(float), data["High"].to_numpy(float), data["Low"].to_numpy(float)
    best: Optional[dict[str, Any]] = None
    for flag_len in range(3, 11):
        pole_end = window - flag_len - 1
        if pole_end < 4:
            break
        pole_start = max(0, pole_end - 10)
        pole_low = float(lows[pole_start: pole_end + 1].min())
        pole_top = float(highs[pole_end - 1: pole_end + 1].max())
        pole_gain = (pole_top - pole_low) / pole_low
        if pole_gain < 0.08:
            continue   # السارية: صعود ≥ 8% خلال ≤ 10 شموع
        flag = data.iloc[pole_end + 1:]
        flag_high, flag_low = float(flag["High"].max()), float(flag["Low"].min())
        if (flag_high - flag_low) > 0.5 * (pole_top - pole_low) or flag_high > pole_top * 1.01:
            continue   # العلم أضيق من نصف السارية ولسه ما اخترقش قمتها
        drift = (float(flag["Close"].iloc[-1]) - float(flag["Close"].iloc[0])) / float(flag["Close"].iloc[0])
        if drift > 0.02:
            continue   # التماسك عرضي أو هابط قليلاً، مش امتداد للصعود
        vol_fade = "Volume" in data and float(flag["Volume"].mean()) < float(data["Volume"].iloc[pole_start: pole_end + 1].mean())
        confidence = "HIGH" if vol_fade and pole_gain >= 0.12 else "MED" if vol_fade or pole_gain >= 0.12 else "LOW"
        candidate = {
            "pattern": "BULL_FLAG",
            "confidence": confidence,
            "key_levels": {"breakout": round(flag_high, 4), "flag_low": round(flag_low, 4),
                           "pole_gain_pct": round(pole_gain * 100, 2), "measured_target": round(flag_high + (pole_top - pole_low), 4)},
            "arabic_note": f"علم صاعد: سارية +{pole_gain * 100:.0f}% ثم تماسك {flag_len} جلسات، الاختراق فوق {flag_high:,.2f}",
        }
        if best is None or CONFIDENCE_RANK[confidence] > CONFIDENCE_RANK[best["confidence"]]:
            best = candidate
    return best


# يشغّل كل الكواشف ويرجع الأقوى ثقةً (عند التساوي: الترتيب = الأولوية).
def detect_breakout_pattern(df: pd.DataFrame) -> dict[str, Any]:
    found = [
        result
        for result in (
            detect_cup_and_handle(df),
            detect_symmetrical_triangle(df),
            detect_bull_flag(df),
            detect_higher_lows(df),
        )
        if result is not None
    ]
    if not found:
        return dict(NO_PATTERN)
    best = max(found, key=lambda r: CONFIDENCE_RANK[r["confidence"]])   # max يحتفظ بأول عنصر عند التساوي
    return {**best, "levels": best["key_levels"]}
