# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas>=2.0"]
# ///
"""
D7 缓涨检测模块 — 多日趋势扫描 + 板块关联追踪

解决的核心问题：UASS单日快照无法识别"缓涨走势"(V底→缩量回调→放量突破)
典型案例：2026-06-01 煤炭爆发前5天已有明确缓涨信号，但系统未捕捉

检测模式：
  1. WASHOUT_CONFIRMED — 放量阳线后缩量回调(经典洗盘确认)
  2. GRADUAL_CLIMB — 3+天小阳(0.5-5%)且量温和放大
  3. V_BOTTOM_REVERSAL — 深跌后反弹过半程
  4. VOLUME_BUILDUP — 价格横盘但量连续3天放大(资金暗中吸货)
  5. BREAKOUT_COMPRESS — 5日振幅收窄至<5%且量升(即将突破)

板块关联：
  当上游板块连续2日走强时，自动预警下游板块
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "kline_cache.db"
SCAN_HISTORY_PATH = REPO / "data" / "scan_history.json"

# 板块关联方向图：key板块变强时 → 预警value板块
SECTOR_CORRELATION = {
    "电力": ["煤炭开采", "煤炭", "天然气"],
    "煤炭开采": ["电力", "煤化工"],
    "半导体": ["电子元件", "被动元件", "PCB", "光刻胶"],
    "光模块": ["PCB", "连接器", "光芯片"],
    "消费电子": ["被动元件", "PCB", "面板"],
    "汽车零部": ["智能座舱", "汽车电子", "轮胎"],
    "AI算力": ["光模块", "液冷", "服务器", "IDC"],
    "光伏": ["逆变器", "硅料", "银浆"],
    "锂电池": ["正极材料", "负极材料", "电解液", "隔膜"],
    "军工": ["碳纤维", "钛合金", "航空装备"],
    "房地产": ["家电", "装修建材", "家居"],
    "有色金属": ["小金属", "稀土永磁", "铜"],
    "医药": ["CRO", "创新药", "医疗器械"],
    "IT服务": ["信创", "国产软件", "云计算"],
}


def _get_klines_batch(codes: list[str], days: int = 20) -> dict[str, pd.DataFrame]:
    """Batch read from SQLite cache."""
    if not DB_PATH.exists():
        return {}

    conn = sqlite3.connect(str(DB_PATH))
    results = {}
    for code in codes:
        try:
            df = pd.read_sql_query(
                "SELECT date, open AS Open, high AS High, low AS Low, "
                "close AS Close, volume AS Volume "
                "FROM daily_kline WHERE code = ? ORDER BY date DESC LIMIT ?",
                conn, params=(code, days),
            )
            if df.empty or len(df) < 5:
                continue
            df = df.sort_values("date").reset_index(drop=True)
            for col in ("Open", "High", "Low", "Close", "Volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            results[code] = df
        except Exception:
            pass
    conn.close()
    return results


def detect_patterns(code: str, df: pd.DataFrame) -> list[dict]:
    """Detect multi-day accumulation patterns on a single stock."""
    if df is None or len(df) < 5:
        return []

    alerts = []
    closes = df["Close"].values
    volumes = df["Volume"].values
    highs = df["High"].values
    lows = df["Low"].values

    n = len(closes)
    if n < 5:
        return []

    avg_vol = volumes[-10:].mean() if n >= 10 else volumes.mean()

    # Pattern 1: WASHOUT_CONFIRMED
    # 条件：某天涨>3% + 次日跌(缩量<0.7x) + 之后又涨
    for i in range(max(0, n - 6), n - 2):
        day_chg = (closes[i] - closes[i - 1]) / closes[i - 1] * 100 if i > 0 else 0
        next_chg = (closes[i + 1] - closes[i]) / closes[i] * 100
        next_vol_ratio = volumes[i + 1] / avg_vol if avg_vol > 0 else 1

        if day_chg >= 3.0 and next_chg < 0 and next_vol_ratio < 0.7:
            # 确认洗盘后有反弹
            if i + 2 < n:
                after_chg = (closes[i + 2] - closes[i + 1]) / closes[i + 1] * 100
                if after_chg > 0:
                    alerts.append({
                        "pattern": "WASHOUT_CONFIRMED",
                        "description": "放量阳线→缩量回调→反弹确认",
                        "signal_day": df["date"].iloc[i + 1],
                        "strength": min(100, int(day_chg * 10 + (1 - next_vol_ratio) * 50)),
                    })
                    break

    # Pattern 2: GRADUAL_CLIMB (缓涨走势)
    # 条件：最近5天中有3+天小阳(0.5-5%)，量不萎缩
    if n >= 5:
        last5_chg = [(closes[i] - closes[i - 1]) / closes[i - 1] * 100
                     for i in range(n - 5, n) if i > 0]
        up_days = sum(1 for c in last5_chg if 0.3 <= c <= 5.0)
        vol_trend = volumes[-1] / volumes[-5] if volumes[-5] > 0 else 1

        if up_days >= 3 and vol_trend >= 0.8:
            total_gain = (closes[-1] - closes[-5]) / closes[-5] * 100
            alerts.append({
                "pattern": "GRADUAL_CLIMB",
                "description": f"5日{up_days}阳缓涨(累计+{total_gain:.1f}%)",
                "signal_day": df["date"].iloc[-1],
                "strength": min(100, int(up_days * 15 + total_gain * 3)),
            })

    # Pattern 3: V_BOTTOM_REVERSAL
    # 条件：10日内先跌>10%再反弹超过跌幅50%
    if n >= 10:
        min_idx = np.argmin(closes[-10:])
        if min_idx > 0 and min_idx < 8:  # 底部不在首尾
            peak_before = max(closes[-10:-10 + min_idx]) if min_idx > 0 else closes[-10]
            bottom = closes[-10 + min_idx]
            current = closes[-1]
            drop_pct = (bottom - peak_before) / peak_before * 100
            recovery_pct = (current - bottom) / (peak_before - bottom) * 100 if peak_before > bottom else 0

            if drop_pct < -8 and recovery_pct > 50:
                # 强度按恢复程度和跌幅深度加权，cap at 100
                raw_strength = int(abs(drop_pct) * 1.5 + min(recovery_pct, 120) * 0.3)
                alerts.append({
                    "pattern": "V_BOTTOM_REVERSAL",
                    "description": f"V底反转(跌{drop_pct:.0f}%→反弹{recovery_pct:.0f}%)",
                    "signal_day": df["date"].iloc[-10 + min_idx],
                    "strength": min(100, raw_strength),
                })

    # Pattern 4: VOLUME_BUILDUP (量升价平=暗中吸货)
    if n >= 5:
        price_range = (max(closes[-5:]) - min(closes[-5:])) / closes[-5] * 100
        vol_growth = [volumes[i] / volumes[i - 1] for i in range(n - 4, n) if volumes[i - 1] > 0]
        vol_expanding = sum(1 for v in vol_growth if v > 1.1) >= 2

        if price_range < 5 and vol_expanding and volumes[-1] > avg_vol * 1.3:
            alerts.append({
                "pattern": "VOLUME_BUILDUP",
                "description": f"价格横盘({price_range:.1f}%)但量连续放大",
                "signal_day": df["date"].iloc[-1],
                "strength": min(100, int(volumes[-1] / avg_vol * 30)),
            })

    # Pattern 5: BREAKOUT_COMPRESS (窄幅整��即将突破)
    if n >= 7:
        last5_range = (max(highs[-5:]) - min(lows[-5:])) / closes[-5] * 100
        prev5_range = (max(highs[-10:-5]) - min(lows[-10:-5])) / closes[-10] * 100 if n >= 10 else last5_range * 2

        if last5_range < 5 and prev5_range > last5_range * 1.5:
            vol_rising = volumes[-1] > volumes[-3] if n >= 3 else False
            if vol_rising:
                alerts.append({
                    "pattern": "BREAKOUT_COMPRESS",
                    "description": f"振幅收窄至{last5_range:.1f}%(前5日{prev5_range:.1f}%)且量升",
                    "signal_day": df["date"].iloc[-1],
                    "strength": min(100, int((prev5_range / last5_range) * 20)),
                })

    # Pattern 6: ACCUMULATION_PHASE (当前正在积累，尚未突破)
    # 核心：最近一天是缩量小跌/平盘，且前1-2天有放量阳线
    # 这是05-26昊华能源被错过的模式 — 当天的特征
    if n >= 3:
        today_chg = (closes[-1] - closes[-2]) / closes[-2] * 100
        today_vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
        prev_chg = (closes[-2] - closes[-3]) / closes[-3] * 100 if n >= 3 else 0
        prev_vol_ratio = volumes[-2] / avg_vol if avg_vol > 0 else 1

        # 今天缩量(-3%~+1%) + 昨天放量阳线(>2%, vol>1.2x)
        is_today_quiet = -3.0 <= today_chg <= 1.5 and today_vol_ratio < 0.8
        was_prev_strong = prev_chg >= 2.0 and prev_vol_ratio >= 1.0

        if is_today_quiet and was_prev_strong:
            # 额外确认：过去5天整体向上
            if n >= 5:
                five_day_chg = (closes[-1] - closes[-5]) / closes[-5] * 100
                if five_day_chg > 0:
                    alerts.append({
                        "pattern": "ACCUMULATION_PHASE",
                        "description": f"放量阳线(+{prev_chg:.1f}%)后缩量整理(vol={today_vol_ratio:.1f}x)，积累中",
                        "signal_day": df["date"].iloc[-1],
                        "strength": min(100, int(prev_chg * 12 + (1 - today_vol_ratio) * 40)),
                    })

    return alerts


def detect_sector_correlation(sector_history: dict[str, list[float]]) -> list[dict]:
    """
    Check if upstream sectors have been strengthening → alert downstream.
    sector_history: {sector_name: [day1_chg, day2_chg, ...]} (recent 5 days)
    """
    alerts = []

    for upstream, downstreams in SECTOR_CORRELATION.items():
        history = sector_history.get(upstream, [])
        if len(history) < 2:
            continue

        # 连续2日走强(涨幅>0.5%)
        recent = history[-3:] if len(history) >= 3 else history[-2:]
        consecutive_up = sum(1 for h in recent if h > 0.5)

        if consecutive_up >= 2:
            avg_gain = sum(recent) / len(recent)
            for ds in downstreams:
                ds_history = sector_history.get(ds, [])
                ds_recent = ds_history[-1] if ds_history else 0
                # 下游还没明显启动(涨幅<上游一半)
                if ds_recent < avg_gain * 0.5:
                    alerts.append({
                        "upstream": upstream,
                        "downstream": ds,
                        "upstream_days": consecutive_up,
                        "upstream_avg_gain": round(avg_gain, 2),
                        "downstream_current": round(ds_recent, 2),
                        "description": f"{upstream}连续{consecutive_up}日走强(均+{avg_gain:.1f}%)→{ds}可能跟随",
                    })

    return alerts


def load_scan_history() -> dict:
    """Load rolling scan history (last 5 days)."""
    if SCAN_HISTORY_PATH.exists():
        try:
            with open(SCAN_HISTORY_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"days": [], "sector_daily": {}}


def save_scan_history(history: dict):
    """Save rolling scan history, keep last 5 days."""
    history["days"] = history.get("days", [])[-5:]
    # Keep only last 5 days of sector data
    for sector in list(history.get("sector_daily", {}).keys()):
        history["sector_daily"][sector] = history["sector_daily"][sector][-5:]
    SCAN_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCAN_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def update_scan_history(date_str: str, scored_top: list[dict], sector_flow: list[dict]) -> dict:
    """Add today's scan to rolling history."""
    history = load_scan_history()

    # Don't duplicate
    if date_str in history.get("days", []):
        return history

    history.setdefault("days", []).append(date_str)

    # Track sector daily changes
    history.setdefault("sector_daily", {})
    for sf in sector_flow:
        name = sf.get("名称", "")
        if name:
            history["sector_daily"].setdefault(name, []).append(sf.get("涨跌幅", 0))

    # Track top scored stocks per day
    history.setdefault("daily_top_codes", {})
    history["daily_top_codes"][date_str] = [
        {"代码": s["代码"], "名称": s["名称"], "TB总分": s["TB总分"], "行业": s.get("行业", "")}
        for s in scored_top[:60]
    ]

    save_scan_history(history)
    return history


def _seed_sector_history_from_scored(scored: list[dict], history: dict) -> dict:
    """
    When sector_daily is empty (first run), seed from scored stocks' industries.
    Groups scored stocks by industry and estimates sector trend from their avg change.
    """
    if history.get("sector_daily"):
        return history

    sector_changes: dict[str, list[float]] = {}
    for s in scored:
        industry = s.get("行业", "")
        if industry and s.get("涨跌幅") is not None:
            sector_changes.setdefault(industry, []).append(s["涨跌幅"])

    history.setdefault("sector_daily", {})
    for sector, changes in sector_changes.items():
        avg_chg = sum(changes) / len(changes) if changes else 0
        history["sector_daily"][sector] = [avg_chg]

    return history


def run_d7_scan(scored: list[dict], sector_flow: list[dict], date_str: str) -> dict:
    """
    Main entry: run D7 trend detection on top scored stocks + sector correlation.
    Returns {trend_alerts: [...], sector_alerts: [...], watchlist_codes: [...]}
    """
    # 1. Load history and update
    history = update_scan_history(date_str, scored, sector_flow)
    # Seed sector data from scored if first run
    history = _seed_sector_history_from_scored(scored, history)

    # 2. Determine scan universe: all codes that appeared in last 5 days of scans
    scan_universe = set()
    for day, tops in history.get("daily_top_codes", {}).items():
        for t in tops:
            scan_universe.add(t["代码"])
    # Also include current top 60
    for s in scored[:60]:
        scan_universe.add(s["代码"])

    # Filter: only codes that kline_cache can handle
    scan_codes = [c for c in scan_universe if not c.startswith(("8", "4")) and not c.startswith("92")]

    # 3. Batch read klines
    klines = _get_klines_batch(scan_codes, days=15)

    # 4. Detect patterns on each stock
    trend_alerts = []
    for code, df in klines.items():
        patterns = detect_patterns(code, df)
        if patterns:
            # Find name from scored or history
            name = ""
            industry = ""
            for s in scored:
                if s["代码"] == code:
                    name = s["名称"]
                    industry = s.get("行业", "")
                    break
            if not name:
                for tops in history.get("daily_top_codes", {}).values():
                    for t in tops:
                        if t["代码"] == code:
                            name = t["名称"]
                            industry = t.get("行业", "")
                            break
                    if name:
                        break

            for p in patterns:
                trend_alerts.append({
                    "代码": code,
                    "名称": name,
                    "行业": industry,
                    **p,
                })

    # Sort by strength
    trend_alerts.sort(key=lambda x: x.get("strength", 0), reverse=True)

    # 5. Sector correlation
    sector_history = history.get("sector_daily", {})
    sector_alerts = detect_sector_correlation(sector_history)

    # 6. Build watchlist: codes with strong patterns
    watchlist = [a["代码"] for a in trend_alerts if a.get("strength", 0) >= 60]

    return {
        "trend_alerts": trend_alerts,
        "sector_alerts": sector_alerts,
        "watchlist_codes": list(set(watchlist)),
        "scan_universe_size": len(scan_codes),
        "kline_hit": len(klines),
    }


def print_d7_report(d7_result: dict):
    """Print D7 results to console."""
    trend_alerts = d7_result.get("trend_alerts", [])
    sector_alerts = d7_result.get("sector_alerts", [])

    if trend_alerts:
        print()
        print(f"🔥 D7 缓涨预警 ({len(trend_alerts)}只检出, 扫描范围{d7_result['scan_universe_size']}只)")
        print(f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10} {'模式':<20} {'信号日':>10} {'强度':>4}")
        for i, a in enumerate(trend_alerts[:15], 1):
            print(f"{i:>3} {a['代码']:<8} {a['名称']:<8} {a['行业']:<10} "
                  f"{a['pattern']:<20} {a.get('signal_day','')[-5:]:>10} {a.get('strength',0):>4}")
            if a.get("description"):
                print(f"      └─ {a['description']}")

    if sector_alerts:
        print()
        print(f"⚡ 板块关联预警 ({len(sector_alerts)}条)")
        for a in sector_alerts[:8]:
            print(f"  {a['upstream']} → {a['downstream']}: {a['description']}")

    if not trend_alerts and not sector_alerts:
        print()
        print("D7 缓涨检测: 未发现明显积累信号")


if __name__ == "__main__":
    # Standalone test
    history = load_scan_history()
    print(f"Scan history: {len(history.get('days', []))} days")
    print(f"Sector tracking: {len(history.get('sector_daily', {}))} sectors")
