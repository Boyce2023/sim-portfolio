#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股15年知名投资理论实证大回测（2011-01-01 至 2026-11-18）
阵营B：技术形态、波浪、缠论与日历魔咒 4 大理论引擎（5条策略）
严格 PIT 零未来函数因果实现 + shift(1) 次日生效 + 单边 0.15% 换手成本
"""
import json
import os
import sys
import numpy as np
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data_cache")
sys.path.insert(0, BASE_DIR)
import tei_metrics  # noqa: E402

COST_ONE_WAY = 0.0015
START_DATE = "2011-01-01"
END_DATE = "2026-11-18"

STRATEGY_NAMES = [
    "艾略特波浪_因果数浪",
    "缠论_分型笔与MACD背驰",
    "经典均线趋势_MA20与MA60",
    "传统超买超卖_RSI逆势",
    "A股日历魔咒_春季躁动避五穷六绝",
]


def to_builtin(obj):
    if isinstance(obj, dict):
        return {str(k): to_builtin(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_builtin(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return str(obj)[:10]
    return obj


def causal_zigzag(df: pd.DataFrame, pct_thresh: float = 0.06):
    """Strict PIT causal ZigZag confirmed on close reversal >= pct_thresh."""
    has_hl = {"high", "low"}.issubset(df.columns)
    closes = df["close"].values
    highs = df["high"].values if has_hl else closes
    lows = df["low"].values if has_hl else closes
    dates = df.index
    n = len(df)
    pivots = []
    if n == 0:
        return pivots

    ext_high, ext_high_idx = float(highs[0]), 0
    ext_low, ext_low_idx = float(lows[0]), 0
    direction = 0

    for t in range(1, n):
        c, h, l = float(closes[t]), float(highs[t]), float(lows[t])
        if direction == 0:
            if h > ext_high:
                ext_high, ext_high_idx = h, t
            if l < ext_low:
                ext_low, ext_low_idx = l, t
            if c <= ext_high * (1.0 - pct_thresh) and ext_high_idx < t:
                pivots.append({"idx": ext_high_idx, "date": dates[ext_high_idx], "price": ext_high, "type": "H", "confirm_idx": t, "confirm_date": dates[t]})
                direction = -1
                ext_low_idx = ext_high_idx + 1 + int(np.argmin(lows[ext_high_idx + 1 : t + 1]))
                ext_low = float(lows[ext_low_idx])
            elif c >= ext_low * (1.0 + pct_thresh) and ext_low_idx < t:
                pivots.append({"idx": ext_low_idx, "date": dates[ext_low_idx], "price": ext_low, "type": "L", "confirm_idx": t, "confirm_date": dates[t]})
                direction = 1
                ext_high_idx = ext_low_idx + 1 + int(np.argmax(highs[ext_low_idx + 1 : t + 1]))
                ext_high = float(highs[ext_high_idx])
            continue

        if direction == 1:
            if h > ext_high:
                ext_high, ext_high_idx = h, t
            if c <= ext_high * (1.0 - pct_thresh):
                pivots.append({"idx": ext_high_idx, "date": dates[ext_high_idx], "price": ext_high, "type": "H", "confirm_idx": t, "confirm_date": dates[t]})
                direction = -1
                if ext_high_idx < t:
                    ext_low_idx = ext_high_idx + 1 + int(np.argmin(lows[ext_high_idx + 1 : t + 1]))
                    ext_low = float(lows[ext_low_idx])
                else:
                    ext_low_idx, ext_low = t, c
        elif direction == -1:
            if l < ext_low:
                ext_low, ext_low_idx = l, t
            if c >= ext_low * (1.0 + pct_thresh):
                pivots.append({"idx": ext_low_idx, "date": dates[ext_low_idx], "price": ext_low, "type": "L", "confirm_idx": t, "confirm_date": dates[t]})
                direction = 1
                if ext_low_idx < t:
                    ext_high_idx = ext_low_idx + 1 + int(np.argmax(highs[ext_low_idx + 1 : t + 1]))
                    ext_high = float(highs[ext_high_idx])
                else:
                    ext_high_idx, ext_high = t, c
    return pivots


def run_elliott_wave(df: pd.DataFrame, pct_thresh: float = 0.06) -> pd.Series:
    """Strategy 1: Strict PIT Causal Elliott Wave (6% ZigZag ABC + 5-wave counting)."""
    has_hl = {"high", "low"}.issubset(df.columns)
    has_vol = "volume" in df.columns
    closes = df["close"].values
    highs = df["high"].values if has_hl else closes
    lows = df["low"].values if has_hl else closes
    opens = df["open"].values if "open" in df.columns else closes
    vols = df["volume"].values if has_vol else None
    vol_ma20 = pd.Series(vols).rolling(20).mean().values if vols is not None else None
    n = len(df)

    pivots = []
    ext_high, ext_high_idx = float(highs[0]), 0
    ext_low, ext_low_idx = float(lows[0]), 0
    direction = 0

    pos_raw = np.zeros(n, dtype=float)
    state = "WAIT_ABC"
    impulse_wave = 0
    stop_low = 0.0
    min_abc_start_pivot = 0
    shrink_tried_leg = -1
    entered_by_shrink = False

    for t in range(1, n):
        c, h, l = float(closes[t]), float(highs[t]), float(lows[t])
        if direction == 0:
            if h > ext_high:
                ext_high, ext_high_idx = h, t
            if l < ext_low:
                ext_low, ext_low_idx = l, t
            if c <= ext_high * (1.0 - pct_thresh) and ext_high_idx < t:
                pivots.append({"idx": ext_high_idx, "price": ext_high, "type": "H", "confirm_idx": t})
                direction = -1
                ext_low_idx = ext_high_idx + 1 + int(np.argmin(lows[ext_high_idx + 1 : t + 1]))
                ext_low = float(lows[ext_low_idx])
            elif c >= ext_low * (1.0 + pct_thresh) and ext_low_idx < t:
                pivots.append({"idx": ext_low_idx, "price": ext_low, "type": "L", "confirm_idx": t})
                direction = 1
                ext_high_idx = ext_low_idx + 1 + int(np.argmax(highs[ext_low_idx + 1 : t + 1]))
                ext_high = float(highs[ext_high_idx])
            continue

        new_pivot = None
        if direction == 1:
            if h > ext_high:
                ext_high, ext_high_idx = h, t
            if c <= ext_high * (1.0 - pct_thresh):
                new_pivot = {"idx": ext_high_idx, "price": ext_high, "type": "H", "confirm_idx": t}
                pivots.append(new_pivot)
                direction = -1
                if ext_high_idx < t:
                    ext_low_idx = ext_high_idx + 1 + int(np.argmin(lows[ext_high_idx + 1 : t + 1]))
                    ext_low = float(lows[ext_low_idx])
                else:
                    ext_low_idx, ext_low = t, c
        elif direction == -1:
            if l < ext_low:
                ext_low, ext_low_idx = l, t
            if c >= ext_low * (1.0 + pct_thresh):
                new_pivot = {"idx": ext_low_idx, "price": ext_low, "type": "L", "confirm_idx": t}
                pivots.append(new_pivot)
                direction = 1
                if ext_low_idx < t:
                    ext_high_idx = ext_low_idx + 1 + int(np.argmax(highs[ext_low_idx + 1 : t + 1]))
                    ext_high = float(highs[ext_high_idx])
                else:
                    ext_high_idx, ext_high = t, c

        cur_pos = pos_raw[t - 1]
        if state == "LONG_IMPULSE":
            if c < stop_low:
                cur_pos = 0.0
                state = "WAIT_ABC"
                impulse_wave = 0
                entered_by_shrink = False
            elif new_pivot is not None:
                if new_pivot["type"] == "L":
                    if entered_by_shrink and impulse_wave == 1:
                        stop_low = new_pivot["price"]
                        entered_by_shrink = False
                    elif impulse_wave in (2, 4):
                        impulse_wave += 1
                        stop_low = new_pivot["price"]
                elif new_pivot["type"] == "H":
                    if impulse_wave in (1, 3):
                        impulse_wave += 1
                    elif impulse_wave == 5:
                        cur_pos = 0.0
                        state = "WAIT_ABC"
                        impulse_wave = 0
                        entered_by_shrink = False
                        min_abc_start_pivot = len(pivots) - 1

        if state == "WAIT_ABC":
            if new_pivot is not None and new_pivot["type"] == "L" and len(pivots) - min_abc_start_pivot >= 4:
                p0, p1, p2, p3 = pivots[-4], pivots[-3], pivots[-2], pivots[-1]
                if p0["type"] == "H" and p2["price"] < p0["price"] and p3["price"] < p1["price"]:
                    cur_pos = 1.0
                    state = "LONG_IMPULSE"
                    impulse_wave = 1
                    stop_low = p3["price"]
                    entered_by_shrink = False
            elif direction == -1 and vols is not None and len(pivots) - min_abc_start_pivot >= 3:
                p0, p1, p2 = pivots[-3], pivots[-2], pivots[-1]
                cur_leg = len(pivots) - 1
                if p0["type"] == "H" and p2["price"] < p0["price"] and ext_low < p1["price"]:
                    if shrink_tried_leg != cur_leg:
                        made_recent_low = (t - ext_low_idx) <= 2
                        bull_candle = (c > float(opens[t])) and (c > float(closes[t - 1]))
                        shrink_vol = (vol_ma20[t] > 0) and (float(vols[t]) < 0.75 * float(vol_ma20[t]))
                        if made_recent_low and bull_candle and shrink_vol:
                            cur_pos = 1.0
                            state = "LONG_IMPULSE"
                            impulse_wave = 1
                            stop_low = ext_low * 0.99
                            shrink_tried_leg = cur_leg
                            entered_by_shrink = True
        pos_raw[t] = cur_pos
    return pd.Series(pos_raw, index=df.index)


def run_chanlun(df: pd.DataFrame) -> pd.Series:
    """Strategy 2: Strict PIT Chanlun (containment -> 3rd-bar fractal -> >=5 stroke -> MACD area div)."""
    has_hl = {"high", "low"}.issubset(df.columns)
    closes = df["close"].values
    highs = df["high"].values if has_hl else closes
    lows = df["low"].values if has_hl else closes
    n = len(df)

    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = (2.0 * (dif - dea)).values

    def green_area(r0, r1):
        seg = hist[max(0, r0) : min(n, r1 + 1)]
        return float(np.sum(np.abs(seg[seg < 0])))

    def red_area(r0, r1):
        seg = hist[max(0, r0) : min(n, r1 + 1)]
        return float(np.sum(seg[seg > 0]))

    mk = []
    stroke_pts = []
    strokes = []
    pos_raw = np.zeros(n, dtype=float)
    state = "FLAT"
    stop_low = 0.0

    for t in range(n):
        h_t, l_t, c_t = float(highs[t]), float(lows[t]), float(closes[t])
        added_new = False
        if len(mk) == 0:
            mk.append({"h": h_t, "l": l_t, "hi_raw": t, "lo_raw": t})
            added_new = True
        else:
            last = mk[-1]
            contains = (last["h"] >= h_t and last["l"] <= l_t) or (h_t >= last["h"] and l_t <= last["l"])
            if contains:
                up_dir = True if len(mk) == 1 else (mk[-1]["h"] > mk[-2]["h"])
                if up_dir:
                    if h_t >= last["h"]:
                        last["h"] = h_t
                        last["hi_raw"] = t
                    if l_t >= last["l"]:
                        last["l"] = l_t
                        last["lo_raw"] = t
                else:
                    if l_t <= last["l"]:
                        last["l"] = l_t
                        last["lo_raw"] = t
                    if h_t <= last["h"]:
                        last["h"] = h_t
                        last["hi_raw"] = t
            else:
                mk.append({"h": h_t, "l": l_t, "hi_raw": t, "lo_raw": t})
                added_new = True

        new_frac = None
        if added_new and len(mk) >= 3:
            k0, k1, k2 = mk[-3], mk[-2], mk[-1]
            c_idx = len(mk) - 2
            if k1["h"] > k0["h"] and k1["h"] > k2["h"] and k1["l"] > k0["l"] and k1["l"] > k2["l"]:
                new_frac = {"type": "TOP", "mk_idx": c_idx, "raw_idx": k1["hi_raw"], "h": k1["h"], "l": k1["l"]}
            elif k1["l"] < k0["l"] and k1["l"] < k2["l"] and k1["h"] < k0["h"] and k1["h"] < k2["h"]:
                new_frac = {"type": "BOT", "mk_idx": c_idx, "raw_idx": k1["lo_raw"], "h": k1["h"], "l": k1["l"]}

        cur_pos = pos_raw[t - 1] if t > 0 else 0.0
        if state == "LONG" and c_t < stop_low:
            cur_pos = 0.0
            state = "FLAT"

        if new_frac is not None:
            if len(stroke_pts) == 0:
                stroke_pts.append(new_frac)
            else:
                last_pt = stroke_pts[-1]
                if new_frac["type"] == last_pt["type"]:
                    if new_frac["type"] == "TOP" and new_frac["h"] > last_pt["h"]:
                        stroke_pts[-1] = new_frac
                        if len(strokes) >= 1 and strokes[-1]["dir"] == "UP":
                            s_curr = strokes[-1]
                            s_curr["end_pt"] = new_frac
                            s_curr["area"] = red_area(s_curr["start_pt"]["raw_idx"], new_frac["raw_idx"])
                            prev_ups = [s for s in strokes[:-1] if s["dir"] == "UP"]
                            if prev_ups and new_frac["h"] > prev_ups[-1]["end_pt"]["h"] and s_curr["area"] < prev_ups[-1]["area"]:
                                if state == "LONG":
                                    cur_pos = 0.0
                                    state = "FLAT"
                    elif new_frac["type"] == "BOT" and new_frac["l"] < last_pt["l"]:
                        stroke_pts[-1] = new_frac
                        if len(strokes) >= 1 and strokes[-1]["dir"] == "DOWN":
                            s_curr = strokes[-1]
                            s_curr["end_pt"] = new_frac
                            s_curr["area"] = green_area(s_curr["start_pt"]["raw_idx"], new_frac["raw_idx"])
                            prev_downs = [s for s in strokes[:-1] if s["dir"] == "DOWN"]
                            if prev_downs and new_frac["l"] < prev_downs[-1]["end_pt"]["l"] and s_curr["area"] < prev_downs[-1]["area"]:
                                s_curr["is_1buy"] = True
                                if state == "FLAT":
                                    cur_pos = 1.0
                                    state = "LONG"
                                    stop_low = new_frac["l"]
                elif new_frac["mk_idx"] - last_pt["mk_idx"] >= 4:
                    if last_pt["type"] == "BOT" and new_frac["type"] == "TOP" and new_frac["h"] > last_pt["h"] and new_frac["l"] > last_pt["l"]:
                        stroke_pts.append(new_frac)
                        u_area = red_area(last_pt["raw_idx"], new_frac["raw_idx"])
                        prev_ups = [s for s in strokes if s["dir"] == "UP"]
                        if prev_ups and new_frac["h"] > prev_ups[-1]["end_pt"]["h"] and u_area < prev_ups[-1]["area"]:
                            if state == "LONG":
                                cur_pos = 0.0
                                state = "FLAT"
                        strokes.append({"dir": "UP", "start_pt": last_pt, "end_pt": new_frac, "area": u_area, "is_1buy": False})
                    elif last_pt["type"] == "TOP" and new_frac["type"] == "BOT" and new_frac["l"] < last_pt["l"] and new_frac["h"] < last_pt["h"]:
                        stroke_pts.append(new_frac)
                        d_area = green_area(last_pt["raw_idx"], new_frac["raw_idx"])
                        prev_downs = [s for s in strokes if s["dir"] == "DOWN"]
                        is_1b = False
                        if prev_downs:
                            prev_d = prev_downs[-1]
                            if new_frac["l"] < prev_d["end_pt"]["l"] and d_area < prev_d["area"]:
                                is_1b = True
                                if state == "FLAT":
                                    cur_pos = 1.0
                                    state = "LONG"
                                    stop_low = new_frac["l"]
                                elif new_frac["l"] > stop_low:
                                    stop_low = new_frac["l"]
                            elif new_frac["l"] > prev_d["end_pt"]["l"] and prev_d["is_1buy"]:
                                if state == "FLAT":
                                    cur_pos = 1.0
                                    state = "LONG"
                                    stop_low = new_frac["l"]
                                elif new_frac["l"] > stop_low:
                                    stop_low = new_frac["l"]
                        strokes.append({"dir": "DOWN", "start_pt": last_pt, "end_pt": new_frac, "area": d_area, "is_1buy": is_1b})
        pos_raw[t] = cur_pos
    return pd.Series(pos_raw, index=df.index)


def run_ma_trend(df: pd.DataFrame) -> pd.Series:
    """Strategy 3: MA20 & MA60 classic trend benchmark."""
    c = df["close"].values
    ma20 = df["close"].rolling(20).mean().values
    ma60 = df["close"].rolling(60).mean().values
    pos = np.zeros(len(df), dtype=float)
    cur = 0.0
    for t in range(len(df)):
        if np.isnan(ma60[t]):
            pos[t] = 0.0
            continue
        if cur == 0.0 and c[t] > ma60[t] and ma20[t] > ma60[t]:
            cur = 1.0
        elif cur == 1.0 and c[t] < ma60[t]:
            cur = 0.0
        pos[t] = cur
    return pd.Series(pos, index=df.index)


def run_rsi_contrarian(df: pd.DataFrame) -> pd.Series:
    """Strategy 4: RSI(14) < 30 buy, RSI(14) > 70 sell."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_g = gain.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean()
    avg_l = loss.ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean()
    rs = avg_g / avg_l.replace(0.0, np.nan)
    rsi = (100.0 - 100.0 / (1.0 + rs)).fillna(50.0).values
    # Handle zero loss edge case
    zero_loss_mask = (avg_l == 0.0) & (avg_g > 0.0)
    rsi = np.where(zero_loss_mask.values, 100.0, rsi)

    pos = np.zeros(len(df), dtype=float)
    cur = 0.0
    for t in range(len(df)):
        if rsi[t] < 30.0:
            cur = 1.0
        elif rsi[t] > 70.0:
            cur = 0.0
        pos[t] = cur
    return pd.Series(pos, index=df.index)


def run_calendar_effect(df: pd.DataFrame) -> pd.Series:
    """Strategy 5: Spring Rally + Avoid May/Jun + Jul/Nov/Dec 100%, Apr/Aug-Oct/Jan1-14 50%."""
    dates = df.index
    w_target = np.zeros(len(dates), dtype=float)
    for i, d in enumerate(dates):
        m, day = d.month, d.day
        if (m == 1 and day >= 15) or m in (2, 3, 7, 11, 12):
            w_target[i] = 1.0
        elif m in (5, 6):
            w_target[i] = 0.0
        else:
            w_target[i] = 0.5
    s_target = pd.Series(w_target, index=dates)
    return s_target.shift(-1).fillna(w_target[-1])


STRATEGY_FUNCS = {
    "艾略特波浪_因果数浪": run_elliott_wave,
    "缠论_分型笔与MACD背驰": run_chanlun,
    "经典均线趋势_MA20与MA60": run_ma_trend,
    "传统超买超卖_RSI逆势": run_rsi_contrarian,
    "A股日历魔咒_春季躁动避五穷六绝": run_calendar_effect,
}


def backtest_single(df: pd.DataFrame, bench_ret: pd.Series, strat_fn) -> tuple:
    pos_raw = strat_fn(df)
    w = pos_raw.shift(1).fillna(0.0)
    turnover = w.diff().abs().fillna(0.0)
    strat_ret = w * bench_ret - turnover * COST_ONE_WAY
    return strat_ret, w


def analyze_wave_c4(broad_df: pd.DataFrame) -> dict:
    """Empirical C-wave 4 statistics across major indices (2011-01-01 ~ 2026-11-18)."""
    out = {}
    for sym, label in [("sh000300", "沪深300"), ("sh000905", "中证500"), ("sz399006", "创业板指"), ("sh000001", "上证综指")]:
        df = broad_df[broad_df["symbol"] == sym].sort_values("date").set_index("date")
        highs, lows, closes = df["high"].values, df["low"].values, df["close"].values
        n = len(df)

        # Perspective 1: 6% causal ZigZag C-wave trigger perspective (exact strategy signal perspective)
        piv6 = causal_zigzag(df, 0.06)
        ev6 = []
        for i in range(3, len(piv6)):
            p0, p1, p2, p3 = piv6[i - 3], piv6[i - 2], piv6[i - 1], piv6[i]
            if p0["type"] == "H" and p1["type"] == "L" and p2["type"] == "H" and p3["type"] == "L":
                if p2["price"] < p0["price"] and p3["price"] < p1["price"]:
                    if pd.Timestamp("2011-01-01") <= p3["date"] <= pd.Timestamp("2026-06-01"):
                        l3 = p3["price"]
                        end_idx = min(n, p3["confirm_idx"] + 200)
                        outcome = "DIRECT_BOTTOM"
                        max_b = (closes[p3["confirm_idx"]] / l3 - 1.0) * 100.0
                        extra_drop = 0.0
                        for k in range(p3["confirm_idx"], end_idx):
                            max_b = max(max_b, (highs[k] / l3 - 1.0) * 100.0)
                            if highs[k] >= l3 * 1.15 or highs[k] >= p2["price"]:
                                outcome = "DIRECT_BOTTOM"
                                break
                            if lows[k] < l3:
                                outcome = "C4_THEN_C5_NEW_LOW"
                                sub_min = lows[k]
                                for m in range(k, min(n, k + 200)):
                                    if lows[m] < sub_min:
                                        sub_min = lows[m]
                                    if highs[m] >= sub_min * 1.15:
                                        break
                                extra_drop = (sub_min / l3 - 1.0) * 100.0
                                break
                        ev6.append({
                            "b_top_date": str(p2["date"])[:10],
                            "c_low_date": str(p3["date"])[:10],
                            "confirm_date": str(p3["confirm_date"])[:10],
                            "c_drop_pct": round((l3 / p2["price"] - 1.0) * 100.0, 2),
                            "outcome": outcome,
                            "bounce_pct": round(max_b, 2),
                            "c5_extra_drop_pct": round(extra_drop, 2),
                        })

        c4_list = [e for e in ev6 if e["outcome"] == "C4_THEN_C5_NEW_LOW"]
        dir_list = [e for e in ev6 if e["outcome"] == "DIRECT_BOTTOM"]

        # Perspective 2: Macro 10% ZigZag major C-waves with >=5% internal C4 bounce
        piv10 = causal_zigzag(df, 0.10)
        ev10 = []
        for i in range(3, len(piv10)):
            p0, p1, p2, p3 = piv10[i - 3], piv10[i - 2], piv10[i - 1], piv10[i]
            if p0["type"] == "H" and p1["type"] == "L" and p2["type"] == "H" and p3["type"] == "L":
                if p2["price"] < p0["price"] and p3["price"] < p1["price"] and p3["date"] >= pd.Timestamp("2011-01-01"):
                    brk = next((k for k in range(p2["idx"] + 1, p3["idx"] + 1) if lows[k] < p1["price"]), None)
                    if brk is None:
                        continue
                    run_min = lows[brk]
                    bounces = []
                    in_b, b_start, b_peak = False, run_min, highs[brk]
                    for k in range(brk + 1, p3["idx"]):
                        if lows[k] < run_min:
                            if in_b:
                                bounces.append((b_peak / b_start - 1.0) * 100.0)
                                in_b = False
                            run_min = lows[k]
                            b_start, b_peak = run_min, highs[k]
                        else:
                            if highs[k] > b_peak:
                                b_peak = highs[k]
                            if (b_peak / b_start - 1.0) >= 0.05:
                                in_b = True
                    if in_b and lows[p3["idx"]] < b_start:
                        bounces.append((b_peak / b_start - 1.0) * 100.0)
                    ev10.append({
                        "a_low_date": str(p1["date"])[:10],
                        "b_top_date": str(p2["date"])[:10],
                        "c_end_date": str(p3["date"])[:10],
                        "c_total_drop_pct": round((p3["price"] / p2["price"] - 1.0) * 100.0, 2),
                        "has_c4_bounce": len(bounces) > 0,
                        "c4_count": len(bounces),
                        "max_c4_bounce_pct": round(max(bounces), 2) if bounces else 0.0,
                    })
        m_c4 = sum(1 for e in ev10 if e["has_c4_bounce"])

        out[sym] = {
            "name": label,
            "tactical_6pct_perspective": {
                "total_c_rebound_events": len(ev6),
                "c4_trap_then_c5_count": len(c4_list),
                "c4_trap_prob_pct": round(len(c4_list) / len(ev6) * 100.0, 1) if ev6 else 0.0,
                "direct_bottom_count": len(dir_list),
                "direct_bottom_prob_pct": round(len(dir_list) / len(ev6) * 100.0, 1) if ev6 else 0.0,
                "avg_c4_bounce_pct": round(float(np.mean([e["bounce_pct"] for e in c4_list])), 2) if c4_list else 0.0,
                "avg_c5_extra_drop_pct": round(float(np.mean([e["c5_extra_drop_pct"] for e in c4_list])), 2) if c4_list else 0.0,
                "events": ev6 if sym == "sh000300" else ev6[-8:],
            },
            "macro_10pct_c_wave_perspective": {
                "total_major_c_waves": len(ev10),
                "with_c4_bounce_gt5pct_count": m_c4,
                "with_c4_bounce_prob_pct": round(m_c4 / len(ev10) * 100.0, 1) if ev10 else 0.0,
                "straight_crash_bottom_count": len(ev10) - m_c4,
                "straight_crash_prob_pct": round((len(ev10) - m_c4) / len(ev10) * 100.0, 1) if ev10 else 0.0,
                "avg_max_c4_bounce_pct": round(float(np.mean([e["max_c4_bounce_pct"] for e in ev10 if e["has_c4_bounce"]])), 2) if m_c4 else 0.0,
                "events": ev10,
            },
        }
    return out


def build_calendar_monthly_matrix(broad_df: pd.DataFrame) -> dict:
    """1..12 monthly win-rate & mean return matrix: HS300 vs CSI500 vs ChiNext, 2011-2018 vs 2019-2026."""
    symbols = [("sh000300", "沪深300"), ("sh000905", "中证500"), ("sz399006", "创业板指")]
    periods = [
        ("full_15y", "2011-01-01", "2026-11-18"),
        ("first_8y_2011_2018", "2011-01-01", "2018-12-31"),
        ("last_8y_2019_2026", "2019-01-01", "2026-11-18"),
    ]
    matrix = {}
    for sym, label in symbols:
        df = broad_df[broad_df["symbol"] == sym].sort_values("date").set_index("date")
        daily_ret = df["close"].pct_change().dropna()
        daily_ret = daily_ret[(daily_ret.index >= START_DATE) & (daily_ret.index <= END_DATE)]
        monthly_ret = (1.0 + daily_ret).resample("ME").prod() - 1.0
        matrix[sym] = {"name": label}
        for p_key, p0, p1 in periods:
            sub = monthly_ret[(monthly_ret.index >= p0) & (monthly_ret.index <= p1)]
            m_dict = {}
            for m in range(1, 13):
                vals = sub[sub.index.month == m]
                m_dict[str(m)] = {
                    "n_months": int(len(vals)),
                    "win_rate_pct": round(float((vals > 0).mean() * 100.0), 1) if len(vals) else None,
                    "mean_ret_pct": round(float(vals.mean() * 100.0), 2) if len(vals) else None,
                    "median_ret_pct": round(float(vals.median() * 100.0), 2) if len(vals) else None,
                }
            matrix[sym][p_key] = m_dict
    return matrix


def main():
    broad = pd.read_parquet(os.path.join(DATA_DIR, "broad_indices_15y.parquet"))
    sector_ret = pd.read_parquet(os.path.join(DATA_DIR, "sector_ret_cw_15y.parquet"))
    regime = pd.read_parquet(os.path.join(DATA_DIR, "regime_daily_15y.parquet"))

    # 1. Primary benchmark: sh000300 + comparison indices (sh000001, sz399006)
    idx_dfs = {}
    for sym in ["sh000300", "sh000001", "sz399006"]:
        sub = broad[broad["symbol"] == sym].sort_values("date").set_index("date")
        idx_dfs[sym] = sub

    results = {
        "meta": {
            "camp": "阵营B：技术形态、波浪、缠论与日历魔咒",
            "backtest_window": f"{START_DATE} ~ {END_DATE}",
            "primary_benchmark": "sh000300",
            "one_way_cost": COST_ONE_WAY,
            "pit_lag": "shift(1)",
        },
        "strategies": {},
        "index_comparison": {},
        "industry_tei": {},
        "wave_c4_empirical_stats": {},
        "calendar_monthly_matrix": {},
    }

    daily_ret_hs300 = {}

    for s_name in STRATEGY_NAMES:
        fn = STRATEGY_FUNCS[s_name]
        # Primary HS300 full profile
        df300 = idx_dfs["sh000300"]
        bench300 = df300["close"].pct_change().fillna(0.0)
        s_ret300, w300 = backtest_single(df300, bench300, fn)
        prof300 = tei_metrics.evaluate_full_profile(s_name, s_ret300, bench300, regime, w300)
        # Add annual turnover metric
        s_sub = s_ret300[(s_ret300.index >= START_DATE) & (s_ret300.index <= END_DATE)]
        w_sub = w300.reindex(s_sub.index).fillna(0.0)
        ann_oneway_to = float(w_sub.diff().abs().fillna(0.0).sum() / (len(s_sub) / 242.0))
        prof300["ann_oneway_turnover_x"] = round(ann_oneway_to, 2)
        results["strategies"][s_name] = prof300
        daily_ret_hs300[s_name] = s_sub

        # Index comparison across sh000300, sh000001, sz399006
        idx_comp = {}
        for sym, sym_label in [("sh000300", "沪深300"), ("sh000001", "上证综指"), ("sz399006", "创业板指")]:
            df_i = idx_dfs[sym]
            b_i = df_i["close"].pct_change().fillna(0.0)
            sr_i, wi = backtest_single(df_i, b_i, fn)
            p_i = tei_metrics.evaluate_full_profile(f"{s_name}_{sym}", sr_i, b_i, regime, wi)
            idx_comp[sym] = {
                "name": sym_label,
                "overall_15y": p_i["overall_15y"],
                "last_10y": p_i["last_10y"],
                "last_3y": p_i["last_3y"],
                "tei_decay_per_decade": p_i["tei_decay_per_decade"],
            }
        results["index_comparison"][s_name] = idx_comp

        # 10-Sector TEI matrix
        ind_dict = {}
        for sec_col in sector_ret.columns:
            r_sec = sector_ret[sec_col].fillna(0.0)
            nav_sec = (1.0 + r_sec).cumprod()
            df_sec = pd.DataFrame({"close": nav_sec, "open": nav_sec, "high": nav_sec, "low": nav_sec}, index=sector_ret.index)
            sr_sec, w_sec = backtest_single(df_sec, r_sec, fn)
            p_sec = tei_metrics.evaluate_full_profile(f"{s_name}_{sec_col}", sr_sec, r_sec, regime, w_sec)
            ind_dict[sec_col] = {
                "overall_15y": {k: p_sec["overall_15y"][k] for k in ["tei", "ann_ret", "bench_ann_ret", "excess_ann", "mdd", "bench_mdd", "ir", "sharpe", "exposure_pct", "q_win_rate"]},
                "last_10y": {k: p_sec["last_10y"][k] for k in ["tei", "ann_ret", "bench_ann_ret", "excess_ann", "ir", "exposure_pct"]},
                "last_3y": {k: p_sec["last_3y"][k] for k in ["tei", "ann_ret", "bench_ann_ret", "excess_ann", "ir", "exposure_pct"]},
                "tei_decay_per_decade": p_sec["tei_decay_per_decade"],
            }
        results["industry_tei"][s_name] = ind_dict

    # 2. Empirical C-wave 4 statistics
    results["wave_c4_empirical_stats"] = analyze_wave_c4(broad)

    # 3. Calendar monthly matrix
    results["calendar_monthly_matrix"] = build_calendar_monthly_matrix(broad)

    # Save outputs
    json_path = os.path.join(BASE_DIR, "res_tech_4theories.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(to_builtin(results), f, ensure_ascii=False, indent=2)

    daily_df = pd.DataFrame(daily_ret_hs300)
    daily_df.index.name = "date"
    parquet_path = os.path.join(BASE_DIR, "daily_ret_tech.parquet")
    daily_df.to_parquet(parquet_path)

    print("Saved:", json_path, parquet_path)
    print("daily_ret_tech shape:", daily_df.shape, "date range:", daily_df.index.min(), daily_df.index.max())


if __name__ == "__main__":
    main()
