#!/usr/bin/env python3
"""UASS v6.0 — 评分模块: D1-D6 + D6筹码体检 + D5弹性(K线版) + 一票否决"""

from __future__ import annotations

import sys
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from uass_types import (
    D1_SCORES, D2_SCORES, D3_SCORES, D4_SCORES,
    D5_AMPLITUDE_THRESHOLDS, D5_EXPLOSION_THRESHOLDS, D5_ZT_FREQ_THRESHOLDS,
    D6_FLAGS, GRADE_THRESHOLDS, score_to_grade,
)


# ── D1 资金信号 ───────────────────────────────────────────────────────────────

def score_d1(code: str, lhb_map: dict, change_pct: float = 0, is_limit_up: bool = False) -> tuple[str, int]:
    """D1资金信号: LHB优先，无LHB时用涨停/涨幅作为proxy."""
    lhb = lhb_map.get(code, {})
    net_buy = lhb.get("龙虎榜净买额", 0)
    jigou = "机构" in lhb.get("解读", "")
    has_lhb = code in lhb_map
    # S: 净买≥5亿+机构
    if net_buy >= 5e8 and jigou:
        return "S", D1_SCORES["S"]
    # A: 净买≥2亿 或 (有LHB+机构)
    if net_buy >= 2e8 or (has_lhb and jigou):
        return "A", D1_SCORES["A"]
    # B: 有LHB且净买≥5000万（修复：原来是>0就给A）
    if has_lhb and net_buy >= 5e7:
        return "B", D1_SCORES["B"]
    # B: 涨停但无LHB（降级：原来给A）
    if is_limit_up:
        return "B", D1_SCORES["B"]
    # C: 有LHB但净买<5000万，或涨幅≥7%，或涨幅≥3%
    if has_lhb and net_buy > 0:
        return "C", D1_SCORES["C"]
    if change_pct >= 7:
        return "C", D1_SCORES["C"]
    if change_pct >= 3:
        return "C", D1_SCORES["C"]
    return "X", D1_SCORES["X"]


# ── D2 封板强度 ───────────────────────────────────────────────────────────────

def auto_score_d2(row: dict, vol_ratio: float = 0) -> tuple[str, int]:
    """D2封板强度评分.

    BUG FIX: vol_ratio 默认值改为 0（zt_pool股票数据源不提供该字段时），
    调用方可从K线缓存中注入实际 vol_ratio 覆盖默认值。
    """
    lianban = row.get("连板数", 1)
    seal_money = row.get("封板资金", 0)
    turnover_rate = row.get("换手率", 0)
    zb_count = row.get("炸板次数", 0)
    # row-level vol_ratio takes precedence if provided; caller-injected vol_ratio is fallback
    _row_vr = row.get("vol_ratio")
    if _row_vr is not None and _row_vr > 0:
        vol_ratio = float(_row_vr)

    # -- D=0 一票否决：派发出货信号 ----------------------------------
    # 条件1: 炸板>=3次（多次冲高回落，主力出货特征）
    # 条件2: 换手率>20% 且 非首板（高换手非启动=游资发货）
    if zb_count >= 3:
        return "D", D2_SCORES["D"]
    if turnover_rate > 20 and lianban > 1:
        return "D", D2_SCORES["D"]

    # -- 正常评分路径 ------------------------------------------------
    # S: 连板>=3 + 低换手（筹码锁定扎实）
    if lianban >= 3 and turnover_rate < 10:
        return "S", D2_SCORES["S"]
    # A: 连板>=2 或 大封单无炸板
    if lianban >= 2 or (seal_money > 1e8 and zb_count == 0):
        return "A", D2_SCORES["A"]
    if seal_money > 0:
        # 量比>3 升级到A（量能强劲弥补封单不足，tb_engine标准）
        if vol_ratio > 3:
            return "A", D2_SCORES["A"]
        # 量比>2 维持B
        return "B", D2_SCORES["B"]
    return "C", D2_SCORES["C"]


# ── D3 板块地位 ───────────────────────────────────────────────────────────────

def auto_score_d3_batch(stocks: list[dict], sector_map: dict[str, list]) -> None:
    """D3板块地位批量评分 (in-place)."""
    for sector, members in sector_map.items():
        if not members:
            continue
        # 掉队判断: 涨幅 < 板块平均涨幅的一半
        avg_chg = sum(s.get("涨跌幅", 0) for s in members) / len(members) if members else 0
        half_avg = avg_chg / 2.0

        sorted_m = sorted(members, key=lambda x: x.get("首次封板时间", "999999"))
        for i, s in enumerate(sorted_m):
            chg = s.get("涨跌幅", 0)
            # 掉队优先判断（无论排名）
            if chg < half_avg:
                s["_d3"] = "掉队"
                s["_d3_score"] = D3_SCORES["掉队"]
            elif i == 0:
                s["_d3"] = "龙头"
                s["_d3_score"] = D3_SCORES["龙头"]
            elif i <= 2:
                s["_d3"] = "先手"
                s["_d3_score"] = D3_SCORES["先手"]
            elif i <= 5:
                s["_d3"] = "跟涨"
                s["_d3_score"] = D3_SCORES["跟涨"]
            else:
                s["_d3"] = "补涨"
                s["_d3_score"] = D3_SCORES["补涨"]


# ── D4 板块周期 ───────────────────────────────────────────────────────────────

def auto_score_d4(row: dict, sector_zt_count: int = 0, prior_streak: int = 0, prior_zt_count: int = 0) -> tuple[str, int]:
    """D4板块周期: 连板数 + 板块涨停家数 + D8历史streak 综合判断.

    prior_streak: 昨天为止该板块连续热门天数 (来自 mainline_history)
    prior_zt_count: 昨天该板块涨停家数 (用于检测退潮: 今日<昨日)
    """
    lianban = row.get("连板数", 1)
    zb = row.get("炸板次数", 0)

    # ── 优先用D8历史streak判断板块宏观阶段 ──────────────────────────
    # streak≥6天: 板块已进入高潮分歧区
    if prior_streak >= 6:
        return "高潮分歧", D4_SCORES["高潮分歧"]

    # streak≥4天 且今日涨停数 < 昨日涨停数: 退潮信号
    if prior_streak >= 4 and prior_zt_count > 0 and sector_zt_count < prior_zt_count:
        return "退潮", D4_SCORES["退潮"]

    # ── 个股连板判断 ─────────────────────────────────────────────────
    # 高连板 or 多次炸板 = 高潮/分歧
    if zb >= 3 or lianban > 6:
        return "高潮分歧", D4_SCORES["高潮分歧"]
    # 连板≥5(与tb_engine.py"龙头5板+"一致) = 主升中晚
    if lianban >= 5:
        return "主升中晚", D4_SCORES["主升中晚"]
    if lianban >= 2:
        return "主升早", D4_SCORES["主升早"]

    # 连板=1(首板): 用板块涨停家数判断板块热度
    if sector_zt_count >= 6:
        return "主升中晚", D4_SCORES["主升中晚"]
    if sector_zt_count >= 3:
        return "主升早", D4_SCORES["主升早"]
    return "启动", D4_SCORES["启动"]


# ── D5 弹性评分 (K线版，替代旧市值代理) ──────────────────────────────────────

def score_d5_elasticity(
    closes: "np.ndarray",
    highs: "np.ndarray",
    lows: "np.ndarray",
    code: str,
) -> dict:
    """D5弹性评分 — 基于K线实际波动性，三维度15分满分.

    Dimension 1: 振幅 (0-6pts)
      均值(High-Low)/Close * 100 over last 20 trading days
    Dimension 2: 爆发力 (0-5pts)
      最大5日滚动涨幅 over last 20 days
    Dimension 3: 涨停频率 (0-4pts)
      过去20日涨幅≥xt%的天数 (主板9.5%, 创业板/科创板19.5%, 北交所29%)
    """
    closes = np.asarray(closes, dtype=float)
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)

    n = len(closes)

    # ── Dimension 1: 振幅 ─────────────────────────────────────────────
    amplitude_pts = 0
    if n >= 1:
        valid = (closes > 0)
        if valid.sum() > 0:
            amp_arr = (highs[valid] - lows[valid]) / closes[valid] * 100
            mean_amp = float(np.nanmean(amp_arr))
            for threshold, pts in D5_AMPLITUDE_THRESHOLDS:
                if mean_amp >= threshold:
                    amplitude_pts = pts
                    break

    # ── Dimension 2: 爆发力 (最大5日滚动涨幅) ────────────────────────
    explosion_pts = 0
    if n >= 6:
        max_5d_return = 0.0
        for i in range(n - 5, -1, -1):
            if i >= 0 and closes[i] > 0:
                ret = (closes[min(i + 5, n - 1)] - closes[i]) / closes[i] * 100
                if ret > max_5d_return:
                    max_5d_return = ret
        for threshold, pts in D5_EXPLOSION_THRESHOLDS:
            if max_5d_return >= threshold:
                explosion_pts = pts
                break

    # ── Dimension 3: 涨停频率 ────────────────────────────────────────
    zt_freq_pts = 0
    if n >= 2:
        # 确定涨停阈值
        if code.startswith("8") or code.startswith("4"):
            zt_threshold = 29.0   # 北交所
        elif code.startswith("3") or code.startswith("68"):
            zt_threshold = 19.5   # 创业板/科创板
        else:
            zt_threshold = 9.5    # 主板

        zt_days = 0
        for i in range(1, n):
            if closes[i - 1] > 0:
                daily_chg = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
                if daily_chg >= zt_threshold:
                    zt_days += 1

        for threshold, pts in D5_ZT_FREQ_THRESHOLDS:
            if zt_days >= threshold:
                zt_freq_pts = pts
                break

    total = amplitude_pts + explosion_pts + zt_freq_pts

    if total >= 12:
        label = "极高弹性"
    elif total >= 8:
        label = "高弹性"
    elif total >= 4:
        label = "中弹性"
    else:
        label = "低弹性"

    return {
        "amplitude_pts": amplitude_pts,
        "explosion_pts": explosion_pts,
        "zt_freq_pts": zt_freq_pts,
        "total": total,
        "label": label,
    }


# ── 历史数据获取 Helper 函数 ──────────────────────────────────────────────────

def _yf_code(code: str) -> str:
    if code.startswith(("6", "9")):
        return f"{code}.SS"
    return f"{code}.SZ"


def _baostock_code(code: str) -> str:
    if code.startswith("6") or code.startswith("9"):
        return f"sh.{code}"
    return f"sz.{code}"


def _fetch_hist_baostock(code: str, days: int = 65):
    """baostock历史行情 — TCP协议, 不受VPN影响. 不覆盖北交所."""
    if code.startswith(("8", "4")) or code.startswith("92"):
        return None
    import baostock as bs
    import pandas as pd
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=int(days * 1.5) + 30)).strftime("%Y-%m-%d")
    lg = bs.login()
    try:
        rs = bs.query_history_k_data_plus(
            _baostock_code(code),
            "date,open,high,low,close,volume",
            start_date=start, end_date=end,
            frequency="d", adjustflag="2",
        )
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=rs.fields)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
        df = df.dropna(subset=["Close"])
        return df.tail(days) if len(df) >= 20 else None
    finally:
        bs.logout()


def _fetch_hist_akshare(code: str, days: int = 65):
    """akshare历史行情(东方财富源) — VPN下可能被阻断."""
    import akshare as ak
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=int(days * 1.5) + 10)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
    if df is None or df.empty:
        return None
    df = df.rename(columns={"日期": "Date", "开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"})
    return df.tail(days)


def _fetch_hist_yf(code: str, days: int = 65):
    """yfinance兜底 — 使用start/end而非period参数."""
    import yfinance as yf
    from datetime import date
    end_date = date.today()
    start_date = end_date - timedelta(days=int(days * 1.5) + 10)
    hist = yf.Ticker(_yf_code(code)).history(start=start_date.isoformat(), end=end_date.isoformat())
    if hist is not None and len(hist) > 0:
        return hist.tail(days)
    return None


def _fetch_hist(code: str, days: int = 65):
    """A股历史行情: baostock优先(TCP,VPN安全), akshare次之, yfinance兜底."""
    try:
        df = _fetch_hist_baostock(code, days)
        if df is not None and len(df) >= 20:
            return df
    except Exception:
        pass
    try:
        df = _fetch_hist_akshare(code, days)
        if df is not None and len(df) >= 20:
            return df
    except Exception:
        pass
    return _fetch_hist_yf(code, days)


def _fetch_hist_cached(code: str, days: int = 270):
    """SQLite cache first, then full fallback chain."""
    from kline_cache import get_klines

    df = get_klines(code, days)
    if df is not None and len(df) >= 20:
        return df
    return _fetch_hist(code, days)


def _calc_ema(data, period: int):
    """Exponential moving average."""
    ema = np.zeros_like(data, dtype=float)
    k = 2.0 / (period + 1)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = data[i] * k + ema[i - 1] * (1 - k)
    return ema


def _calc_rsi(closes, period: int = 14) -> float:
    """RSI(period) of last value."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


# ── D5+D6 合并体检函数 ────────────────────────────────────────────────────────

def chip_and_elasticity_check(
    code: str,
    current_price: float = 0,
    use_cache: bool = False,
    days: int = 270,
) -> dict:
    """一次拉取K线，同时运行D6筹码体检 + D5弹性评分.

    v2: 三时间框架 (20d/60d/250d) 筹码体检 + D5弹性(K线实际波动版)。
    向后兼容：30d_gain保留为20d_gain别名。
    返回字典包含所有原D6字段 + d5_* 字段。
    """
    result = {
        # D6 字段
        "flags": [],
        "30d_gain": None, "20d_gain": None,
        "vol_ratio": None, "avg_cost_20d": None,
        "ma20_dev": None, "rsi14": None,
        "60d_gain": None, "60d_pos": None, "ma60_dev": None,
        "250d_gain": None, "250d_pos": None, "ma250_dev": None, "52w_high_dist": None,
        "composite_pos": None,
        # D5 字段
        "d5_amplitude_pts": 0,
        "d5_explosion_pts": 0,
        "d5_zt_freq_pts": 0,
        "d5_total": 0,
        "d5_label": "低弹性",
    }
    try:
        hist = _fetch_hist_cached(code, days) if use_cache else _fetch_hist(code, days)
        if hist is None or len(hist) < 20:
            return result

        closes = np.array(hist["Close"].values, dtype=float)
        volumes = np.array(hist["Volume"].values, dtype=float)
        highs = np.array(hist["High"].values, dtype=float)
        lows = np.array(hist["Low"].values, dtype=float)
        opens = np.array(hist["Open"].values, dtype=float) if "Open" in hist.columns else closes.copy()

        valid = (~np.isnan(closes) & ~np.isnan(volumes) & ~np.isnan(highs)
                 & ~np.isnan(lows) & ~np.isnan(opens))
        closes, volumes, highs, lows, opens = (closes[valid], volumes[valid],
                                                highs[valid], lows[valid], opens[valid])
        if len(closes) < 20:
            return result

        n = len(closes)
        curr = closes[-1] if current_price <= 0 else current_price

        # ══ BLOCK A — 20日检查 (原有逻辑保留) ══════════════════════════

        if n >= 15:
            base = closes[-15]
            gain_20d = (curr - base) / base * 100
            result["20d_gain"] = round(gain_20d, 1)
            result["30d_gain"] = result["20d_gain"]
            if gain_20d > 60:
                result["flags"].append("EXTREME_RUN")
            elif gain_20d > 40:
                result["flags"].append("HEAVY_RUN")

        if n >= 20:
            recent_vol = volumes[-20:]
            avg_vol_prior = recent_vol[:-5].mean() if len(recent_vol) > 5 else recent_vol.mean()
            last5_vol = volumes[-5:]
            max_5d_vol = max(last5_vol)
            vol_ratio = max_5d_vol / avg_vol_prior if avg_vol_prior > 0 else 0
            result["vol_ratio"] = round(vol_ratio, 1)
            if max_5d_vol >= recent_vol.max() * 0.90 and vol_ratio > 2:
                result["flags"].append("VOLUME_CLIMAX")
            today_vol = volumes[-1]
            avg_5d_vol = last5_vol.mean()
            if avg_5d_vol > 0 and today_vol < avg_5d_vol * 0.5:
                result["flags"].append("VOL_SHRINK")

        if n >= 5:
            last5_close = closes[-5:]
            last5_vol_arr = volumes[-5:]
            if last5_close[-1] >= max(last5_close) * 0.99:
                vol_trend = (last5_vol_arr[-1] - last5_vol_arr[0]) / last5_vol_arr[0] if last5_vol_arr[0] > 0 else 0
                if vol_trend < -0.3:
                    result["flags"].append("VOL_PRICE_DIV")

        if n >= 20:
            avg_20 = closes[-20:].mean()
            result["avg_cost_20d"] = round(float(avg_20), 2)
            profit_gap = (curr - avg_20) / avg_20 * 100
            if profit_gap > 25:
                result["flags"].append("PROFIT_TRAPPED")

        if n >= 20:
            ma20 = closes[-20:].mean()
            ma_dev = (curr - ma20) / ma20 * 100
            result["ma20_dev"] = round(ma_dev, 1)
            if ma_dev > 25:
                result["flags"].append("MA_OVEREXTEND")

        if n >= 20:
            ma5 = closes[-5:].mean()
            ma10 = closes[-10:].mean()
            ma20_val = closes[-20:].mean()
            if ma5 < ma10 < ma20_val:
                result["flags"].append("MA_BEARISH")

        if n >= 30:
            ema12 = _calc_ema(closes, 12)
            ema26 = _calc_ema(closes, 26)
            dif = ema12 - ema26
            dea = _calc_ema(dif, 9)
            macd_bar = (dif - dea) * 2
            price_near_high = curr >= max(closes[-20:]) * 0.98
            if price_near_high and len(macd_bar) >= 5:
                bar_5d = macd_bar[-5:]
                if bar_5d[-1] < bar_5d[0] and bar_5d[-1] < max(bar_5d) * 0.7:
                    result["flags"].append("MACD_TOP_DIV")

        rsi = _calc_rsi(closes.tolist())
        result["rsi14"] = round(rsi, 1)
        if rsi > 85:
            result["flags"].append("RSI_EXTREME")

        if n >= 20:
            avg_vol_20 = volumes[-20:].mean()
            today_vol_a9 = volumes[-1]
            today_chg = abs(closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] > 0 else 0
            price_at_high = curr >= max(closes[-20:]) * 0.95
            if price_at_high and today_vol_a9 > avg_vol_20 * 2 and today_chg < 2:
                result["flags"].append("STAGNANT_VOL")

        if n >= 20:
            price_at_high = curr >= max(closes[-20:]) * 0.95
            if price_at_high:
                for i in range(-3, 0):
                    if abs(i) <= n:
                        body = abs(closes[i] - opens[i])
                        upper_shadow = highs[i] - max(closes[i], opens[i])
                        if body > 0 and upper_shadow > body * 2:
                            result["flags"].append("HIGH_SHADOW")
                            break

        # ══ BLOCK B — 60日检查 (新增) ══════════════════════════════════
        if n >= 60:
            try:
                c60, h60, l60 = closes[-60:], highs[-60:], lows[-60:]
                base_60 = c60[0]
                if base_60 > 0:
                    gain_60d = (curr - base_60) / base_60 * 100
                    result["60d_gain"] = round(gain_60d, 1)
                    if gain_60d > 80:
                        result["flags"].append("60D_EXTREME_RUN")
                    elif gain_60d > 50:
                        result["flags"].append("60D_HEAVY_RUN")
                hi60, lo60 = float(h60.max()), float(l60.min())
                if hi60 > lo60:
                    pos_60 = (curr - lo60) / (hi60 - lo60) * 100
                    result["60d_pos"] = round(pos_60, 1)
                    if pos_60 >= 90:
                        result["flags"].append("60D_TOP_RANGE")
                ma60 = c60.mean()
                if ma60 > 0:
                    dev_60 = (curr - ma60) / ma60 * 100
                    result["ma60_dev"] = round(dev_60, 1)
                    if dev_60 > 30:
                        result["flags"].append("MA60_OVEREXTEND")
            except Exception:
                pass

        # ══ BLOCK C — 250日检查 (新增) ═════════════════════════════════
        if n >= 200:
            try:
                n250 = min(250, n)
                c250, h250, l250 = closes[-n250:], highs[-n250:], lows[-n250:]
                base_250 = c250[0]
                if base_250 > 0:
                    gain_250d = (curr - base_250) / base_250 * 100
                    result["250d_gain"] = round(gain_250d, 1)
                hi250, lo250 = float(h250.max()), float(l250.min())
                if hi250 > lo250:
                    pos_250 = (curr - lo250) / (hi250 - lo250) * 100
                    result["250d_pos"] = round(pos_250, 1)
                    if pos_250 >= 95:
                        result["flags"].append("250D_TOP_RANGE")
                ma250 = c250.mean()
                if ma250 > 0:
                    dev_250 = (curr - ma250) / ma250 * 100
                    result["ma250_dev"] = round(dev_250, 1)
                    if dev_250 > 40:
                        result["flags"].append("MA250_OVEREXTEND")
                    if dev_250 < -20:
                        result["flags"].append("MA250_DEEP_BELOW")
                n52 = min(252, n)
                hi52 = float(highs[-n52:].max())
                if hi52 > 0:
                    dist_52w = (curr - hi52) / hi52 * 100
                    result["52w_high_dist"] = round(dist_52w, 1)
                    if dist_52w >= -2:
                        result["flags"].append("52W_HIGH_BREAKOUT")
                    elif dist_52w <= -40:
                        result["flags"].append("52W_DEEP_DRAWDOWN")
            except Exception:
                pass

        # ══ BLOCK D — 综合位置评分 ═════════════════════════════════════
        pos_weights = []
        if result.get("ma20_dev") is not None:
            pos_20 = max(0.0, min(100.0, 50.0 + result["ma20_dev"]))
            pos_weights.append((20, pos_20))
        if result.get("60d_pos") is not None:
            pos_weights.append((30, result["60d_pos"]))
        if result.get("250d_pos") is not None:
            pos_weights.append((50, result["250d_pos"]))
        if pos_weights:
            total_w = sum(w for w, _ in pos_weights)
            result["composite_pos"] = round(sum(pos * w / total_w for w, pos in pos_weights), 1)

        if not result["flags"]:
            result["flags"].append("HEALTHY")

        # ══ D5 弹性评分 — 用同一批K线数据的最近20日 ══════════════════
        d5_closes = closes[-20:] if n >= 20 else closes
        d5_highs = highs[-20:] if n >= 20 else highs
        d5_lows = lows[-20:] if n >= 20 else lows
        d5_result = score_d5_elasticity(d5_closes, d5_highs, d5_lows, code)
        result["d5_amplitude_pts"] = d5_result["amplitude_pts"]
        result["d5_explosion_pts"] = d5_result["explosion_pts"]
        result["d5_zt_freq_pts"] = d5_result["zt_freq_pts"]
        result["d5_total"] = d5_result["total"]
        result["d5_label"] = d5_result["label"]

    except Exception:
        result["flags"].append("DATA_ERROR")

    return result


# ── 批量D5+D6 体检 ────────────────────────────────────────────────────────────

def batch_chip_and_elasticity(scored: list[dict], top_n: int = 30) -> None:
    """Run chip+elasticity check on top N scored stocks, enrich in-place.

    Runs D6 chip health AND D5 elasticity from a single K-line fetch per stock.
    After enrichment, recalculates TB总分 (D1+D2+D3+D4+D5) then applies D6 penalty.
    """
    import concurrent.futures
    import time as _t
    from kline_cache import update_cache

    targets = scored[:top_n]
    codes = [s["代码"] for s in targets]

    t0 = _t.time()
    cache_stats = update_cache(codes, days=270)
    cache_elapsed = _t.time() - t0
    new_codes = len(cache_stats)
    new_rows = sum(cache_stats.values())
    if new_rows:
        print(f"  K线缓存: {new_codes}只更新{new_rows}条 ({cache_elapsed:.1f}s)")
    else:
        print(f"  K线缓存: 全部命中 ({cache_elapsed:.1f}s)")

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(chip_and_elasticity_check, code, 0, True, 270): code
            for code in codes
        }
        for f in concurrent.futures.as_completed(futures):
            code = futures[f]
            try:
                results[code] = f.result()
            except Exception:
                results[code] = {
                    "flags": ["DATA_ERROR"],
                    "30d_gain": None,
                    "d5_total": 0,
                    "d5_label": "低弹性",
                    "d5_amplitude_pts": 0,
                    "d5_explosion_pts": 0,
                    "d5_zt_freq_pts": 0,
                }

    for s in targets:
        chk = results.get(s["代码"], {})

        # ── D6 字段赋值 ──────────────────────────────────────────────
        s["D6_flags"] = chk.get("flags", [])
        s["D6_20d涨幅"] = chk.get("20d_gain")
        s["D6_30d涨幅"] = chk.get("30d_gain")
        s["D6_量比"] = chk.get("vol_ratio")
        s["D6_20日均价"] = chk.get("avg_cost_20d")
        s["D6_MA偏离"] = chk.get("ma20_dev")
        s["D6_RSI"] = chk.get("rsi14")
        s["D6_60d涨幅"] = chk.get("60d_gain")
        s["D6_60d位置"] = chk.get("60d_pos")
        s["D6_MA60偏离"] = chk.get("ma60_dev")
        s["D6_250d涨幅"] = chk.get("250d_gain")
        s["D6_250d位置"] = chk.get("250d_pos")
        s["D6_52w距高"] = chk.get("52w_high_dist")
        s["D6_综合位置"] = chk.get("composite_pos")

        # ── D5 字段赋值 ──────────────────────────────────────────────
        s["D5_弹性"] = chk.get("d5_label", "低弹性")
        s["D5分"] = chk.get("d5_total", 0)
        s["D5_振幅分"] = chk.get("d5_amplitude_pts", 0)
        s["D5_爆发力分"] = chk.get("d5_explosion_pts", 0)
        s["D5_涨停频率分"] = chk.get("d5_zt_freq_pts", 0)

        # ── 重新计算TB总分 (D1+D2+D3+D4+D5, 未扣D6) ─────────────────
        s["TB总分"] = (
            s.get("D1分", 0) + s.get("D2分", 0) + s.get("D3分", 0)
            + s.get("D4分", 0) + s.get("D5分", 0)
        )

        # ══ D6 v2 penalty: 三时间框架 + bonus ═══════════════════════
        flags = s["D6_flags"]

        # ── 20日涨幅类 (互斥取最严重) ──
        run_20d = 0
        if "EXTREME_RUN" in flags:
            run_20d = -35
        elif "HEAVY_RUN" in flags:
            run_20d = -20

        # ── 60日涨幅类 (互斥取最严重) ──
        run_60d = 0
        if "60D_EXTREME_RUN" in flags:
            run_60d = -25
        elif "60D_HEAVY_RUN" in flags:
            run_60d = -12

        # ── 250日位置类 ──
        run_250d = 0
        if "MA250_OVEREXTEND" in flags:
            run_250d = -20
        if "250D_TOP_RANGE" in flags:
            run_250d += -5

        # 涨幅类跨时间框架累加，cap=-50
        run_penalty = max(-50, run_20d + run_60d + run_250d)

        # ── 位置类 ──
        pos_penalty = 0
        if "60D_TOP_RANGE" in flags:
            pos_penalty += -8
        if "MA60_OVEREXTEND" in flags:
            pos_penalty += -10

        # ── 量价/技术类 (原有逻辑保留) ──
        tech_penalty = 0
        if "VOLUME_CLIMAX" in flags:
            tech_penalty += -15
        if "PROFIT_TRAPPED" in flags:
            tech_penalty += -10
        if "STAGNANT_VOL" in flags:
            tech_penalty += -15
        if "MA_OVEREXTEND" in flags:
            tech_penalty += -15
        if "MACD_TOP_DIV" in flags:
            tech_penalty += -10
        if "MA_BEARISH" in flags:
            tech_penalty += -10

        # ── 辅助flag: 有核心flag时才加重 ──
        has_core = any(f in flags for f in (
            "EXTREME_RUN", "HEAVY_RUN", "VOLUME_CLIMAX", "PROFIT_TRAPPED",
            "MA_OVEREXTEND", "MACD_TOP_DIV", "STAGNANT_VOL",
            "60D_EXTREME_RUN", "60D_HEAVY_RUN", "MA60_OVEREXTEND", "MA250_OVEREXTEND"))
        if has_core:
            if "VOL_SHRINK" in flags:
                tech_penalty += -5
            if "VOL_PRICE_DIV" in flags:
                tech_penalty += -5
            if "RSI_EXTREME" in flags:
                tech_penalty += -5
            if "HIGH_SHADOW" in flags:
                tech_penalty += -5

        # ── Bonus (正面信号) ──
        bonus = 0
        if "MA250_DEEP_BELOW" in flags and chk.get("20d_gain") and chk["20d_gain"] > 10:
            bonus += 3
        if "52W_DEEP_DRAWDOWN" in flags:
            bonus += 3
        bonus = min(bonus, 10)

        penalty = run_penalty + pos_penalty + tech_penalty + bonus
        s["D6_penalty"] = penalty
        s["TB总分_raw"] = s["TB总分"]
        s["TB总分"] = max(0, s["TB总分"] + penalty)
        s["TB评级"] = score_to_grade(s["TB总分"])


# ── 一票否决过滤器 ────────────────────────────────────────────────────────────

def apply_veto_filter(scored: list[dict]) -> list[dict]:
    """一票否决过滤：标记应排除的股票。不删除，只标记veto=True+降级到D。"""
    for s in scored:
        veto_reasons = []
        # D1=X: 无任何资金信号
        if s.get("D1") == "X":
            veto_reasons.append("D1=X:无资金信号")
        # D2=D: 派发出货
        if s.get("D2") == "D":
            veto_reasons.append("D2=D:派发出货")
        # D3=掉队
        if s.get("D3") == "掉队":
            veto_reasons.append("D3=掉队")
        # D4=退潮
        if s.get("D4") == "退潮":
            veto_reasons.append("D4=退潮")
        # D6多时间框架严重过热
        d6_critical = [f for f in s.get("D6_flags", []) if f in (
            "EXTREME_RUN", "60D_EXTREME_RUN", "MA250_OVEREXTEND")]
        if len(d6_critical) >= 2:
            veto_reasons.append(f"D6多重过热:{','.join(d6_critical)}")

        if veto_reasons:
            s["veto"] = True
            s["veto_reasons"] = veto_reasons
            s["TB评级"] = "D"
        else:
            s["veto"] = False
    return scored
