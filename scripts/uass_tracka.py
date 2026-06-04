#!/usr/bin/env python3
"""UASS v6.2 — Track A 基本面评分: 独立发现引擎

Track A与Track B完全独立运行:
- Track B: 动量/市场信号 (涨停板+龙虎榜+板块资金→TB评分)
- Track A: 基本面质量 (已知研究+行业质量+规模+筹码健康+催化剂→TA评分)

Track A扫描宇宙 = Track B全量 + 持仓 + 观察池 (去重)
Track A只提供评分和排名, 不做任何筛选淘汰

5维评分 (100分满分):
  TA1 已知跟踪 (0-30): 持仓/观察池匹配度
  TA2 行业质量 (0-25): 主线热度+板块资金流向
  TA3 规模稳定性 (0-20): 市值分层
  TA4 筹码健康 (0-15): D6健康度正向映射
  TA5 催化剂 (0-10): 已知催化剂接近度
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from uass_types import REPO

TA_GRADE_THRESHOLDS = [
    (90, "S"), (80, "A+"), (70, "A"), (60, "A-"),
    (50, "B+"), (40, "B"), (30, "B-"), (20, "C"), (0, "D"),
]

TA1_SCORES = {
    "in_portfolio": 25,
    "S": 22, "A": 18, "B": 12, "C": 8, "D": 4,
    "none": 0,
}
TA1_SIGNAL_A_BONUS = 5

TA3_TIERS = [
    (500, 20), (200, 16), (100, 12), (50, 8), (0, 4),
]

_D6_SEVERE = {
    "EXTREME_RUN", "VOLUME_CLIMAX", "MA_OVEREXTEND", "MACD_TOP_DIV",
    "STAGNANT_VOL", "60D_EXTREME_RUN", "MA60_OVEREXTEND", "MA250_OVEREXTEND",
}
_D6_MODERATE = {
    "HEAVY_RUN", "VOL_SHRINK", "VOL_PRICE_DIV", "PROFIT_TRAPPED",
    "RSI_EXTREME", "HIGH_SHADOW", "60D_HEAVY_RUN", "60D_TOP_RANGE",
    "250D_TOP_RANGE", "MA250_DEEP_BELOW",
}


def ta_score_to_grade(total: int) -> str:
    for threshold, grade in TA_GRADE_THRESHOLDS:
        if total >= threshold:
            return grade
    return "D"


# ── 数据加载 ─────────────────────────────────────────────────────────────────

def _load_portfolio_cn() -> dict[str, dict]:
    ps_path = REPO / "portfolio_state.json"
    if not ps_path.exists():
        return {}
    try:
        ps = json.loads(ps_path.read_text())
        return {
            p["ticker"]: {"name": p.get("name", ""), "shares": p.get("shares", 0)}
            for p in ps.get("positions", [])
            if p.get("account") == "cn"
        }
    except Exception:
        return {}


def _load_watchlist_cn() -> dict[str, dict]:
    wl_path = REPO / "watchlist_config.json"
    if not wl_path.exists():
        return {}
    try:
        wl = json.loads(wl_path.read_text())
        result = {}
        for w in wl.get("cn_watchlist", []):
            ticker = w.get("ticker", "")
            if not ticker:
                continue
            cat = w.get("next_catalyst", {})
            result[ticker] = {
                "name": w.get("name", ""),
                "grade": w.get("watchlist_grade", w.get("confidence", "C")),
                "status": w.get("status", ""),
                "sector": w.get("sector", ""),
                "thesis": w.get("thesis_summary", w.get("thesis", "")),
                "catalyst_date": w.get("next_catalyst_date", cat.get("date", "") if isinstance(cat, dict) else ""),
                "catalyst_event": cat.get("event", "") if isinstance(cat, dict) else "",
            }
        return result
    except Exception:
        return {}


def _fetch_extra_stocks(codes: list[str]) -> dict[str, dict]:
    """Fetch basic market data for portfolio/watchlist stocks not in today's scan."""
    if not codes:
        return {}
    try:
        from uass_pipeline import signal_a_entry
        stocks = signal_a_entry(codes)
        return {
            s["代码"]: {
                "名称": s.get("名称", ""),
                "行业": s.get("所属行业", ""),
                "总市值_亿": round(s.get("总市值", 0) / 1e8, 1),
                "涨跌幅": s.get("涨跌幅", 0),
            }
            for s in stocks
        }
    except Exception:
        return {}


# ── TA1-TA5 评分 ─────────────────────────────────────────────────────────────

def _score_ta1(code: str, portfolio: dict, watchlist: dict, is_signal_a: bool = False) -> tuple[int, str]:
    """TA1 已知跟踪 (0-30)."""
    score = 0
    label = "无"

    if code in portfolio:
        score = TA1_SCORES["in_portfolio"]
        label = "持仓"
    elif code in watchlist:
        wl = watchlist[code]
        grade = wl.get("grade", "C")
        score = TA1_SCORES.get(grade, TA1_SCORES["C"])
        if wl.get("status") == "in_portfolio":
            score = max(score, TA1_SCORES["in_portfolio"])
            label = "持仓"
        else:
            label = f"WL-{grade}"

    if is_signal_a:
        score = min(score + TA1_SIGNAL_A_BONUS, 30)
        label += "+SA"

    return score, label


def _sector_matches(stock_sector: str, ref_sector: str) -> bool:
    if not stock_sector or not ref_sector:
        return False
    if stock_sector == ref_sector:
        return True
    if ref_sector in stock_sector or stock_sector in ref_sector:
        return True
    for part in stock_sector.split("/"):
        if part and (part in ref_sector or ref_sector in part):
            return True
    return False


def _score_ta2(sector: str, streaks: dict, sector_flow: list[dict]) -> tuple[int, str]:
    """TA2 行业质量 (0-25)."""
    best_score = 5
    best_label = "中性"

    for ml_sector, info in streaks.items():
        if _sector_matches(sector, ml_sector):
            stage = info.get("stage_auto", "")
            if stage in ("启动(首日)", "主升早"):
                return 25, f"主线启动"
            elif stage == "主升中":
                if best_score < 18:
                    best_score, best_label = 18, "主升中"
            elif stage == "高潮/退潮风险":
                pass
            else:
                if best_score < 12:
                    best_score, best_label = 12, "主线内"

    for i, sf in enumerate(sector_flow):
        if _sector_matches(sector, sf.get("名称", "")):
            if i < 3 and best_score < 20:
                best_score, best_label = 20, f"资金TOP{i+1}"
            elif i < 5 and best_score < 15:
                best_score, best_label = 15, f"资金TOP{i+1}"
            elif i < 10 and best_score < 10:
                best_score, best_label = 10, f"资金TOP{i+1}"
            break

    return best_score, best_label


def _score_ta3(mkt_cap_yi: float) -> tuple[int, str]:
    """TA3 规模稳定性 (0-20)."""
    labels = {500: "超大盘", 200: "大盘", 100: "中盘", 50: "中小盘", 0: "小盘"}
    for threshold, score in TA3_TIERS:
        if mkt_cap_yi >= threshold:
            return score, labels[threshold]
    return 4, "小盘"


def _score_ta4(d6_flags: list[str], d6_penalty: int, has_d6_data: bool = True) -> tuple[int, str]:
    """TA4 筹码健康 (0-15)."""
    if not has_d6_data:
        return 8, "未知"

    if not d6_flags or "HEALTHY" in d6_flags:
        return 15, "健康"

    severe = [f for f in d6_flags if f in _D6_SEVERE]
    moderate = [f for f in d6_flags if f in _D6_MODERATE]

    if severe:
        return 0, f"严重({len(severe)})"
    elif len(moderate) >= 3:
        return 3, f"较差({len(moderate)})"
    elif moderate:
        return 8, f"一般({len(moderate)})"
    return 12, "轻微"


def _score_ta5(code: str, watchlist: dict) -> tuple[int, str]:
    """TA5 催化剂接近度 (0-10)."""
    if code not in watchlist:
        return 0, "无"

    cat_date = watchlist[code].get("catalyst_date", "")
    if not cat_date:
        return 0, "无"

    try:
        cat_dt = datetime.strptime(cat_date, "%Y-%m-%d")
        days_until = (cat_dt - datetime.now()).days
        if days_until <= 0:
            return 3, "已过"
        elif days_until <= 14:
            return 10, f"{days_until}d内"
        elif days_until <= 30:
            return 7, "30d内"
        elif days_until <= 60:
            return 4, "60d内"
        return 2, "远期"
    except (ValueError, TypeError):
        return 0, "无"


# ── 主函数 ───────────────────────────────────────────────────────────────────

def score_track_a(
    scored: list[dict],
    data: dict,
    streaks: dict | None = None,
) -> list[dict]:
    """Track A全量评分.

    扫描宇宙 = Track B全量 + 持仓 + 观察池 (去重).
    对每只股票算TA1-TA5, 返回按TA总分降序的列表.
    不做任何筛选淘汰.
    """
    portfolio = _load_portfolio_cn()
    watchlist = _load_watchlist_cn()
    if streaks is None:
        streaks = {}
    sector_flow = data.get("sector_flow", [])

    universe: dict[str, dict] = {}

    for s in scored:
        code = s.get("代码", "")
        if not code:
            continue
        universe[code] = {
            "代码": code,
            "名称": s.get("名称", ""),
            "行业": s.get("行业", ""),
            "总市值_亿": s.get("总市值_亿", 0),
            "涨跌幅": s.get("涨跌幅", 0),
            "D6_flags": s.get("D6_flags", []),
            "D6_penalty": s.get("D6_penalty", 0),
            "has_d6": True,
            "in_tb": True,
            "tb_score": s.get("TB总分", 0),
            "tb_grade": s.get("TB评级", ""),
            "veto": s.get("veto", False),
            "signal_a": s.get("signal_a", False),
        }

    extra_codes = []
    for code in list(portfolio.keys()) + list(watchlist.keys()):
        if code not in universe:
            extra_codes.append(code)

    if extra_codes:
        extra_data = _fetch_extra_stocks(list(set(extra_codes)))
        for code in set(extra_codes):
            if code in universe:
                continue
            ed = extra_data.get(code, {})
            wl = watchlist.get(code, {})
            universe[code] = {
                "代码": code,
                "名称": ed.get("名称", "") or wl.get("name", "") or portfolio.get(code, {}).get("name", ""),
                "行业": ed.get("行业", "") or wl.get("sector", ""),
                "总市值_亿": ed.get("总市值_亿", 0),
                "涨跌幅": ed.get("涨跌幅", 0),
                "D6_flags": [],
                "D6_penalty": 0,
                "has_d6": False,
                "in_tb": False,
                "tb_score": 0,
                "tb_grade": "",
                "veto": False,
                "signal_a": False,
            }

    ta_results = []
    for code, stock in universe.items():
        ta1, ta1_l = _score_ta1(code, portfolio, watchlist, stock.get("signal_a", False))
        ta2, ta2_l = _score_ta2(stock.get("行业", ""), streaks, sector_flow)
        ta3, ta3_l = _score_ta3(stock.get("总市值_亿", 0))
        ta4, ta4_l = _score_ta4(
            stock.get("D6_flags", []),
            stock.get("D6_penalty", 0),
            has_d6_data=stock.get("has_d6", False),
        )
        ta5, ta5_l = _score_ta5(code, watchlist)

        ta_total = ta1 + ta2 + ta3 + ta4 + ta5
        ta_grade = ta_score_to_grade(ta_total)

        ta_results.append({
            "代码": code,
            "名称": stock.get("名称", ""),
            "行业": stock.get("行业", ""),
            "总市值_亿": stock.get("总市值_亿", 0),
            "涨跌幅": stock.get("涨跌幅", 0),
            "TA1分": ta1, "TA1_label": ta1_l,
            "TA2分": ta2, "TA2_label": ta2_l,
            "TA3分": ta3, "TA3_label": ta3_l,
            "TA4分": ta4, "TA4_label": ta4_l,
            "TA5分": ta5, "TA5_label": ta5_l,
            "TA总分": ta_total,
            "TA评级": ta_grade,
            "in_tb": stock.get("in_tb", False),
            "tb_score": stock.get("tb_score", 0),
            "tb_grade": stock.get("tb_grade", ""),
            "veto": stock.get("veto", False),
        })

    ta_results.sort(key=lambda x: x["TA总分"], reverse=True)
    return ta_results
