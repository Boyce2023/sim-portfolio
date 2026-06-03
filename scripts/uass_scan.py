#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.14", "yfinance>=0.2", "requests>=2.28", "baostock>=0.8"]
# ///
"""
UASS 自动扫描引擎 v6.1 — 金字塔四层筛选架构 + 回测驱动优化

Layer 1: 全量扫描 (数据拉取 + D1-D4评分 + D5弹性 + D6筹码体检)
Layer 2: 主线定位 (D8主线追踪 + 阶段判定 + 可操作性排序)
Layer 3: 产业链展开 (B→A供应链发散 + Signal A入口)
Layer 4: 催化剂确认 (D7缓涨检测 + 催化剂匹配 → 🟢标记)

v6.1: 回测驱动优化(675信号/67天): Streak≥6 VETO(p=0.002), D5≥12追高惩罚(p=0.027), 医药降权(p=0.027)
v6.0: 金字塔架构重写, D5弹性(K线3维替代市值代理), 合并D5+D6共享K线IO, Signal A入口
v5.1: 主线按可操作性排序
v5.0: D7缓涨检测 + 滚动状态持久化

用法:
  uv run --script scripts/uass_scan.py                    # 默认扫描(今日)
  uv run --script scripts/uass_scan.py --date 20260528    # 指定日期
  uv run --script scripts/uass_scan.py --json             # JSON输出
  uv run --script scripts/uass_scan.py --top 30           # TOP N
  uv run --script scripts/uass_scan.py --signal-a 002028,300502  # Signal A入口
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

from uass_types import (
    D1_SCORES, D2_SCORES, D3_SCORES, D4_SCORES,
    SCAN_OUTPUT, mainline_sort_key, score_to_grade,
)
from uass_scoring import (
    score_d1, auto_score_d2, auto_score_d3_batch, auto_score_d4,
    batch_chip_and_elasticity, apply_veto_filter,
)
from uass_pipeline import fetch_all, find_supply_chain_candidates, signal_a_entry
from uass_mainline import (
    load_mainline_history, compute_mainline_streaks,
    update_mainline_history,
)
from uass_report import print_summary, build_json_output


# ── Layer 1 评分函数 ─────────────────────────────────────────────────────────

def score_strong_movers(
    movers: list[dict],
    lhb_map: dict,
    zt_sectors: dict[str, list],
    sector_zt_counts: dict[str, int] | None = None,
    prior_streaks: dict | None = None,
) -> list[dict]:
    """Score non-limit-up strong movers (涨幅>5%) with adapted Track B.

    v6.0变更:
    - D5评分不在此处计算 (旧: classify_d5基于市值代理)
    - 改为 D5分=0 占位, 待 batch_chip_and_elasticity 运行后统一补充
    - 初始总分 = D1+D2+D3+D4 (不含D5)
    """
    if sector_zt_counts is None:
        sector_zt_counts = {}
    if prior_streaks is None:
        prior_streaks = {}

    sector_groups: dict[str, list] = {}
    for s in movers:
        sec = s.get("所属行业", "未知")
        sector_groups.setdefault(sec, []).append(s)

    for sec, members in sector_groups.items():
        members.sort(key=lambda x: x.get("涨跌幅", 0), reverse=True)
        # 掉队判断: 涨幅 < 板块平均涨幅的一半
        avg_chg = sum(s.get("涨跌幅", 0) for s in members) / len(members) if members else 0
        half_avg = avg_chg / 2.0

        for i, s in enumerate(members):
            chg = s.get("涨跌幅", 0)
            # 掉队优先判断（无论排名）
            if chg < half_avg:
                s["_d3"] = "掉队"
            elif sec in zt_sectors:
                # 板块有涨停时，强势非涨停最多是先手/跟涨/补涨
                if i == 0:
                    s["_d3"] = "先手"
                elif i <= 5:
                    s["_d3"] = "跟涨"
                else:
                    s["_d3"] = "补涨"
            else:
                if i == 0:
                    s["_d3"] = "龙头"
                elif i <= 2:
                    s["_d3"] = "先手"
                elif i <= 5:
                    s["_d3"] = "跟涨"
                else:
                    s["_d3"] = "补涨"
            s["_d3_score"] = D3_SCORES[s["_d3"]]

    scored = []
    for s in movers:
        code = s["代码"]
        change_pct = s.get("涨跌幅", 0)
        d1, d1s = score_d1(code, lhb_map, change_pct, is_limit_up=False)

        # Simplified D2 for strong movers (no 连板数/封板资金, use change_pct only)
        is_gem_star = code.startswith("3") or code.startswith("68")
        if is_gem_star and change_pct >= 15:
            d2, d2s = "A", D2_SCORES["A"]
        elif change_pct >= 10:
            d2, d2s = "B", D2_SCORES["B"]
        else:
            d2, d2s = "C", D2_SCORES["C"]

        d3 = s.get("_d3", "跟涨")
        d3s = s.get("_d3_score", D3_SCORES["跟涨"])
        sec = s.get("所属行业", "未知")

        # D4: use sector context + D8 history streak
        zt_in_sec = sector_zt_counts.get(sec, 0)
        _ps_info = prior_streaks.get(sec, {})
        _prior_stk = _ps_info.get("streak_days", 0)
        _prior_zt = _ps_info.get("today_count", 0)
        # strong mover row has no 连板数/炸板次数; pass zeros so streak logic dominates
        _sm_row = {"连板数": 0, "炸板次数": 0}
        if sec not in zt_sectors:
            d4, d4s = auto_score_d4(_sm_row, sector_zt_count=zt_in_sec,
                                     prior_streak=_prior_stk, prior_zt_count=_prior_zt)
        elif zt_in_sec >= 6:
            d4, d4s = auto_score_d4(_sm_row, sector_zt_count=zt_in_sec,
                                     prior_streak=_prior_stk, prior_zt_count=_prior_zt)
        elif zt_in_sec >= 3:
            d4, d4s = auto_score_d4(_sm_row, sector_zt_count=zt_in_sec,
                                     prior_streak=_prior_stk, prior_zt_count=_prior_zt)
        else:
            d4, d4s = "主升早", D4_SCORES["主升早"]

        # D5 deferred — set placeholder (will be computed in batch_chip_and_elasticity)
        d5s = 0
        d5_label = ""

        # Initial total without D5 (updated after batch_chip_and_elasticity)
        total = d1s + d2s + d3s + d4s
        grade = score_to_grade(total)
        lhb = lhb_map.get(code, {})
        net_buy = lhb.get("龙虎榜净买额", 0)

        scored.append({
            "代码": code,
            "名称": s["名称"],
            "行业": s.get("所属行业", ""),
            "总市值_亿": round(s.get("总市值", 0) / 1e8, 1),
            "流通市值_亿": round(s.get("流通市值", 0) / 1e8, 1),
            "涨跌幅": round(change_pct, 2),
            "成交额_亿": round(s.get("成交额", 0) / 1e8, 1),
            "封板资金_亿": 0,
            "换手率": round(s.get("换手率", 0), 1),
            "连板数": 0,
            "炸板次数": 0,
            "首次封板时间": "",
            "龙虎榜净买_亿": round(net_buy / 1e8, 2) if net_buy else 0,
            "龙虎榜解读": lhb.get("解读", ""),
            "D1": d1, "D1分": d1s,
            "D2": d2, "D2分": d2s,
            "D3": d3, "D3分": d3s,
            "D4": d4, "D4分": d4s,
            "D5_弹性": d5_label, "D5分": d5s,
            "D5_振幅分": 0, "D5_爆发力分": 0, "D5_涨停频率分": 0,
            "TB总分": total,
            "TB评级": grade,
            "涨停": False,
            "可操作性": "可买",
            "数据源": "push2delay",
        })

    return scored


def auto_score_trackb(data: dict) -> list[dict]:
    """Layer 1 主评分函数: 涨停池 + 强势非涨停股 → Track B初始评分 (D1-D4).

    v6.0变更:
    - D5评分延迟到 batch_chip_and_elasticity (共享K线IO)
    - 初始总分 = D1+D2+D3+D4
    - D5分=0 占位, 待后续步骤补充
    """
    zt_pool = data["zt_pool"]
    strong_movers = data.get("strong_movers", [])

    lhb_map = {}
    for item in data["lhb"]:
        code = item["代码"]
        if code not in lhb_map or item["龙虎榜净买额"] > lhb_map[code]["龙虎榜净买额"]:
            lhb_map[code] = item

    sector_groups: dict[str, list] = {}
    for s in zt_pool:
        sec = s.get("所属行业", "未知")
        sector_groups.setdefault(sec, []).append(s)

    auto_score_d3_batch(zt_pool, sector_groups)

    # Build sector涨停计数 for D4
    sector_zt_counts = {sec: len(members) for sec, members in sector_groups.items()}

    # D8历史streak (由 main() 在调用前注入 data["prior_streaks"])
    prior_streaks: dict[str, dict] = data.get("prior_streaks", {})

    def _prior_info(sector: str) -> tuple[int, int]:
        """返回 (prior_streak, prior_zt_count) for a sector."""
        info = prior_streaks.get(sector, {})
        return info.get("streak_days", 0), info.get("today_count", 0)

    scored = []
    for s in zt_pool:
        code = s["代码"]
        lhb = lhb_map.get(code, {})
        net_buy = lhb.get("龙虎榜净买额", 0)
        change_pct = s.get("涨跌幅", 0)
        is_lu = (
            change_pct >= 9.8
            or (code.startswith("3") and change_pct >= 19.5)
            or (code.startswith("68") and change_pct >= 19.5)
        )

        d1, d1s = score_d1(code, lhb_map, change_pct, is_limit_up=is_lu)
        d2, d2s = auto_score_d2(s)
        d3 = s.get("_d3", "跟涨")
        d3s = s.get("_d3_score", D3_SCORES["跟涨"])
        sec = s.get("所属行业", "未知")
        _prior_stk, _prior_zt = _prior_info(sec)
        d4, d4s = auto_score_d4(s, sector_zt_count=sector_zt_counts.get(sec, 0),
                                 prior_streak=_prior_stk, prior_zt_count=_prior_zt)

        # D5 deferred — set placeholder (will be computed in batch_chip_and_elasticity)
        d5s = 0
        d5_label = ""

        # Initial total without D5
        total = d1s + d2s + d3s + d4s
        grade = score_to_grade(total)

        is_limit_up = is_lu or (
            (code.startswith("8") or code.startswith("4")) and change_pct >= 29
        )

        scored.append({
            "代码": code,
            "名称": s["名称"],
            "行业": s.get("所属行业", ""),
            "总市值_亿": round(s.get("总市值", 0) / 1e8, 1),
            "流通市值_亿": round(s.get("流通市值", 0) / 1e8, 1),
            "涨跌幅": round(change_pct, 2),
            "成交额_亿": round(s.get("成交额", 0) / 1e8, 1),
            "封板资金_亿": round(s.get("封板资金", 0) / 1e8, 1),
            "换手率": round(s.get("换手率", 0), 1),
            "连板数": s.get("连板数", 1),
            "炸板次数": s.get("炸板次数", 0),
            "首次封板时间": s.get("首次封板时间", ""),
            "龙虎榜净买_亿": round(net_buy / 1e8, 2) if net_buy else 0,
            "龙虎榜解读": lhb.get("解读", ""),
            "D1": d1, "D1分": d1s,
            "D2": d2, "D2分": d2s,
            "D3": d3, "D3分": d3s,
            "D4": d4, "D4分": d4s,
            "D5_弹性": d5_label, "D5分": d5s,
            "D5_振幅分": 0, "D5_爆发力分": 0, "D5_涨停频率分": 0,
            "TB总分": total,
            "TB评级": grade,
            "涨停": is_limit_up,
            "可操作性": "涨停" if is_limit_up else "可买",
            "数据源": "涨停池",
        })

    # 合并强势非涨停股(push2delay)
    if strong_movers:
        scored_strong = score_strong_movers(
            strong_movers, lhb_map, sector_groups,
            sector_zt_counts, prior_streaks=prior_streaks,
        )
        scored.extend(scored_strong)

    scored.sort(key=lambda x: x["TB总分"], reverse=True)
    return scored


# ── Signal A 评分 ─────────────────────────────────────────────────────────────

def _score_signal_a_stocks(
    stocks: list[dict],
    lhb_map: dict,
    prior_streaks: dict,
) -> list[dict]:
    """Score Signal A stocks (基本面催化剂直接入场).

    Signal A 特殊评分规则:
    - D1: 基于LHB + 涨幅 (同标准路径)
    - D2: 基于涨跌幅 (同 strong_movers 简化路径)
    - D3: 默认"先手"/20分 — 由论文驱动，跳过普通D3排名逻辑
    - D4: 基于 prior_streak (mainline history)
    - D5: 占位=0 (后续 batch_chip_and_elasticity 补充)
    """
    scored = []
    for s in stocks:
        code = s["代码"]
        change_pct = s.get("涨跌幅", 0)
        is_lu = (
            change_pct >= 9.8
            or (code.startswith("3") and change_pct >= 19.5)
            or (code.startswith("68") and change_pct >= 19.5)
        )

        d1, d1s = score_d1(code, lhb_map, change_pct, is_limit_up=is_lu)

        # Simplified D2 (same as strong_movers path)
        is_gem_star = code.startswith("3") or code.startswith("68")
        if is_gem_star and change_pct >= 15:
            d2, d2s = "A", D2_SCORES["A"]
        elif change_pct >= 10:
            d2, d2s = "B", D2_SCORES["B"]
        elif change_pct >= 5:
            d2, d2s = "C", D2_SCORES["C"]
        else:
            d2, d2s = "C", D2_SCORES["C"]

        # D3: 先手/20 — thesis-driven signal, skip normal ranking
        d3, d3s = "先手", D3_SCORES["先手"]

        # D4: use prior streak if available
        sec = s.get("所属行业", "未知")
        _ps_info = prior_streaks.get(sec, {})
        _prior_stk = _ps_info.get("streak_days", 0)
        _prior_zt = _ps_info.get("today_count", 0)
        _sa_row = {"连板数": s.get("连板数", 1), "炸板次数": s.get("炸板次数", 0)}
        d4, d4s = auto_score_d4(_sa_row, sector_zt_count=0,
                                 prior_streak=_prior_stk, prior_zt_count=_prior_zt)

        # D5 deferred
        d5s = 0
        d5_label = ""

        total = d1s + d2s + d3s + d4s
        grade = score_to_grade(total)
        lhb = lhb_map.get(code, {})
        net_buy = lhb.get("龙虎榜净买额", 0)

        scored.append({
            "代码": code,
            "名称": s.get("名称", ""),
            "行业": s.get("所属行业", ""),
            "总市值_亿": round(s.get("总市值", 0) / 1e8, 1),
            "流通市值_亿": round(s.get("流通市值", 0) / 1e8, 1),
            "涨跌幅": round(change_pct, 2),
            "成交额_亿": round(s.get("成交额", 0) / 1e8, 1),
            "封板资金_亿": round(s.get("封板资金", 0) / 1e8, 1),
            "换手率": round(s.get("换手率", 0), 1),
            "连板数": s.get("连板数", 0),
            "炸板次数": s.get("炸板次数", 0),
            "首次封板时间": s.get("首次封板时间", ""),
            "龙虎榜净买_亿": round(net_buy / 1e8, 2) if net_buy else 0,
            "龙虎榜解读": lhb.get("解读", ""),
            "D1": d1, "D1分": d1s,
            "D2": d2, "D2分": d2s,
            "D3": d3, "D3分": d3s,
            "D4": d4, "D4分": d4s,
            "D5_弹性": d5_label, "D5分": d5s,
            "D5_振幅分": 0, "D5_爆发力分": 0, "D5_涨停频率分": 0,
            "TB总分": total,
            "TB评级": grade,
            "涨停": is_lu,
            "可操作性": "涨停" if is_lu else "可买",
            "数据源": "signal_a",
            "signal_a": True,
        })

    return scored


# ── main() ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="UASS自动扫描引擎 v6.0")
    parser.add_argument("--date", type=str, help="扫描日期 YYYYMMDD")
    parser.add_argument("--json", action="store_true", help="输出JSON")
    parser.add_argument("--top", type=int, default=25, help="显示TOP N")
    parser.add_argument(
        "--signal-a", type=str, dest="signal_a", default=None,
        help="Signal A入口: 逗号分隔的股票代码 (e.g. 002028,300502)",
    )
    args = parser.parse_args()

    # ── 日期确定 ──────────────────────────────────────────────────────────────
    if args.date:
        date_str = args.date
    else:
        now = datetime.now()
        if now.hour < 9 or (now.hour == 9 and now.minute < 40):
            # 盘前(09:40前): 涨停池API无今日数据，用昨天
            date_str = (now - timedelta(days=1)).strftime("%Y%m%d")
            print("[WARN] 盘前扫描: 涨停池数据为昨日，push2delay为实时。建议09:45后扫描。")
        elif now.hour >= 15:
            # 收盘后: 用今天
            date_str = now.strftime("%Y%m%d")
        else:
            # 盘中(09:40-15:00): 用今天，API应已有数据
            date_str = now.strftime("%Y%m%d")

    print(f"UASS扫描启动 v6.1 | 日期: {date_str}")
    print("-" * 40)

    # ══════════════════════════════════════════════════════════════════════════
    # Layer 1: 全量扫描
    # ══════════════════════════════════════════════════════════════════════════

    data = fetch_all(date_str)

    # ── 加载D8历史(一次), 算prior_streaks, 注入data让D4可以感知退潮 ──────────
    history = load_mainline_history()
    if history.get("days"):
        last_day = history["days"][-1]
        prior_sector_counts = last_day.get("sectors", {})
        prior_streaks_data = compute_mainline_streaks(history, prior_sector_counts)
        data["prior_streaks"] = prior_streaks_data
    else:
        data["prior_streaks"] = {}

    # ── 主评分 (涨停池 + 强势非涨停) ─────────────────────────────────────────
    scored = auto_score_trackb(data)

    # ── Signal A 处理 (若指定 --signal-a) ────────────────────────────────────
    signal_a_tickers: list[str] = []
    if args.signal_a:
        signal_a_tickers = [t.strip() for t in args.signal_a.split(",") if t.strip()]

    if signal_a_tickers:
        print(f"Signal A入口: {len(signal_a_tickers)}只标的 ({', '.join(signal_a_tickers)})")
        sa_stocks = signal_a_entry(signal_a_tickers)
        if sa_stocks:
            # Build lhb_map for Signal A scoring
            lhb_map_sa = {}
            for item in data["lhb"]:
                code = item["代码"]
                if code not in lhb_map_sa or item["龙虎榜净买额"] > lhb_map_sa[code]["龙虎榜净买额"]:
                    lhb_map_sa[code] = item
            sa_scored = _score_signal_a_stocks(sa_stocks, lhb_map_sa, data["prior_streaks"])
            # Deduplicate: skip Signal A stocks already in scored (by 代码)
            existing_codes = {s["代码"] for s in scored}
            for s in sa_scored:
                if s["代码"] not in existing_codes:
                    scored.append(s)
                    existing_codes.add(s["代码"])
                else:
                    # Mark existing entry with signal_a=True
                    for ex in scored:
                        if ex["代码"] == s["代码"]:
                            ex["signal_a"] = True
                            break
            print(f"Signal A: 合并{len(sa_scored)}只 (去重后)")

    # ── D5 + D6 合并: batch_chip_and_elasticity (K线共享IO) ──────────────────
    d56_top = len(scored)
    print(f"D5弹性 + D6筹码体检中 (全部{d56_top}只, K线共享IO)...")
    batch_chip_and_elasticity(scored, top_n=d56_top)

    # Re-sort by TB总分 after D5+D6 updates scores
    scored.sort(key=lambda x: x["TB总分"], reverse=True)

    d6_flagged = [
        f"{s['名称']}({','.join(s.get('D6_flags', []))})"
        for s in scored[:30]
        if s.get("D6_flags") and "HEALTHY" not in s.get("D6_flags", [])
    ]
    if d6_flagged:
        print(f"D5+D6 完成 | 异常标记: " + ", ".join(d6_flagged))
    else:
        print("D5+D6 完成 | 全部健康")

    # ══════════════════════════════════════════════════════════════════════════
    # Layer 2: 主线定位 (D8主线演进) — 移到VETO前，让Streak≥6 VETO生效
    # ══════════════════════════════════════════════════════════════════════════

    streaks = update_mainline_history(history, date_str, scored)

    # ── 一票否决过滤 (v6.1: 含Streak≥6 VETO + D5≥12 CAUTION) ─────────────
    scored = apply_veto_filter(scored, streaks=streaks)
    veto_count = sum(1 for s in scored if s.get("veto"))
    if veto_count:
        veto_stocks = [s for s in scored if s.get("veto")]
        veto_names = ", ".join(s["名称"] for s in veto_stocks[:5])
        suffix = "..." if veto_count > 5 else ""
        streak_vetos = sum(1 for s in veto_stocks if s.get("_streak_veto"))
        d5_cautions = sum(1 for s in scored if s.get("可操作性") == "CAUTION:D5追高")
        extra = ""
        if streak_vetos:
            extra += f" | Streak≥6: {streak_vetos}只"
        if d5_cautions:
            extra += f" | D5追高: {d5_cautions}只"
        print(f"一票否决: {veto_count}只 ({veto_names}{suffix}){extra}")
    if streaks:
        print()
        print("D8 主线演进 (按可操作性排序: 启动/主升早优先)")
        for sec, info in sorted(streaks.items(), key=mainline_sort_key):
            trend_str = info.get("trend", "")
            stage = info.get("stage_auto", "")
            is_actionable = stage in ("启动(首日)", "主升早")
            is_danger = stage == "高潮/退潮风险"
            prefix = ">>>" if is_actionable else ("  x" if is_danger else "   ")
            suffix = " [可操作]" if is_actionable else (" [不碰]" if is_danger else "")
            print(f"  {prefix} {sec}: 连续{info['streak_days']}天 | {info['today_count']}只涨停 | {stage} | {trend_str}{suffix}")

    # ══════════════════════════════════════════════════════════════════════════
    # Layer 3: 产业链展开 (B→A供应链发散)
    # ══════════════════════════════════════════════════════════════════════════

    chains = find_supply_chain_candidates(scored, data["sector_flow"])

    # ══════════════════════════════════════════════════════════════════════════
    # Layer 4: 催化剂确认 (D7缓涨检测)
    # ══════════════════════════════════════════════════════════════════════════

    print("D7 缓涨检测中 (7日滚动宇宙+板块关联)...")
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trend_detector import run_d7_scan, print_d7_report

    # Build all_active_codes: zt_pool + strong_movers with >3% gains
    all_active = []
    for s in data["zt_pool"]:
        all_active.append({
            "代码": s["代码"],
            "名称": s["名称"],
            "行业": s.get("所属行业", ""),
        })
    for s in data.get("strong_movers", []):
        if s.get("涨跌幅", 0) >= 3.0:
            all_active.append({
                "代码": s["代码"],
                "名称": s["名称"],
                "行业": s.get("所属行业", ""),
            })

    d7_result = run_d7_scan(scored, data["sector_flow"], date_str, all_active_codes=all_active)
    d7_trend_count = len(d7_result.get("trend_alerts", []))
    d7_sector_count = len(d7_result.get("sector_alerts", []))
    print(f"D7 完成 | 缓涨预警{d7_trend_count}只 | 板块关联{d7_sector_count}条")

    # ── 输出 ──────────────────────────────────────────────────────────────────

    output = build_json_output(data, scored, chains, d7_result, streaks, date_str)
    if signal_a_tickers:
        output["market_summary"]["signal_a_count"] = len(signal_a_tickers)

    with open(SCAN_OUTPUT, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print_summary(data, scored, chains, args.top, streaks=streaks)
        print_d7_report(d7_result)
        print()
        print(f"完整数据已存: {SCAN_OUTPUT}")


if __name__ == "__main__":
    main()
