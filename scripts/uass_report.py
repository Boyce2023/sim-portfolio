#!/usr/bin/env python3
"""UASS v6.2 — 报告生成: 双漏斗终端摘要 + JSON输出"""

from __future__ import annotations
from datetime import datetime

from uass_types import mainline_sort_key, STAGE_PRIORITY


# ── 内部常量 ─────────────────────────────────────────────────────────────────

_MULTI_FRAME_ALERT_FLAGS = {
    "EXTREME_RUN", "HEAVY_RUN", "60D_EXTREME_RUN", "60D_HEAVY_RUN",
    "60D_TOP_RANGE", "MA60_OVEREXTEND", "250D_TOP_RANGE",
    "MA250_OVEREXTEND", "52W_HIGH_BREAKOUT",
}

_OVERHEAT_FLAGS = {
    "EXTREME_RUN", "HEAVY_RUN", "60D_EXTREME_RUN", "60D_HEAVY_RUN",
    "MA250_OVEREXTEND",
}


# ── print_summary ─────────────────────────────────────────────────────────────

def print_summary(
    data: dict,
    scored: list[dict],
    chains: list[dict],
    top_n: int,
    streaks: dict | None = None,
    ta_universe: list[dict] | None = None,
) -> None:
    """打印UASS完整终端摘要报告 (双漏斗架构)。

    Sections:
        A  一行摘要
        B  板块资金流向 TOP10
        C  概念板块涨幅 TOP10
        D  涨停集中行业 TOP10
        E  主线演进追踪 (按可操作性排序)
        F  强势非涨停 TOP15 (含D5弹性列)
        G  Funnel 1 — Track B评分 TOP N (含TA双轨评级)
        GA Funnel 2 — Track A基本面排名 (独立发现)
        H  多时间框架D6位置 (异常标记)
        I  B→A 产业链发散候选
        J  Claude TODO
        K  统计汇总 (含双漏斗)
    """
    zt_count = len(data["zt_pool"])
    lhb_count = len(data["lhb"])
    nb = data.get("northbound", {})
    strong_count = len(data.get("strong_movers", []))

    # ── Section A: 一行摘要 ───────────────────────────────────────────────────
    print()
    nb_val = nb.get("净买额_亿", "?")
    print(
        f"UASS 自动扫描 | {data['date']} | "
        f"涨停{zt_count}只 | 强势非涨停{strong_count}只 | "
        f"龙虎榜{lhb_count}条 | 北向净买{nb_val}亿"
    )

    # ── Section B: 板块资金流向 TOP10 ─────────────────────────────────────────
    if data.get("sector_flow"):
        print()
        print("板块资金流向 TOP10")
        print(f"{'#':>3} {'板块':<12} {'涨跌幅':>7} {'主力净流入亿':>10} {'领涨股':<10}")
        for i, sf in enumerate(data["sector_flow"][:10], 1):
            net_b = sf["主力净流入"] / 1e8
            print(
                f"{i:>3} {sf['名称']:<12} {sf['涨跌幅']:>+6.2f}%"
                f" {net_b:>+9.1f} {sf['领涨股']:<10}"
            )

    # ── Section C: 概念板块涨幅 TOP10 ─────────────────────────────────────────
    if data.get("concept_flow"):
        print()
        print("概念板块涨幅 TOP10")
        for i, cf in enumerate(data["concept_flow"][:10], 1):
            print(f"{i:>3} {cf['名称']:<16} {cf['涨跌幅']:>+6.2f}%")

    # ── Section D: 涨停集中行业 TOP10 ─────────────────────────────────────────
    sector_zt_count: dict[str, int] = {}
    for s in scored:
        if s.get("涨停"):
            sec = s.get("行业", "")
            sector_zt_count[sec] = sector_zt_count.get(sec, 0) + 1
    hot_sectors = sorted(sector_zt_count.items(), key=lambda x: x[1], reverse=True)[:10]
    print()
    print("涨停集中行业 TOP10")
    for sec, cnt in hot_sectors:
        names = [s["名称"] for s in scored if s.get("行业") == sec and s.get("涨停")][:3]
        print(f"  {sec}: {cnt}只涨停 ({', '.join(names)})")

    # ── Section E: 主线演进追踪 ───────────────────────────────────────────────
    if streaks:
        print()
        print("主线演进追踪 (按可操作性排序: 启动/主升早 → 主升中 → 高潮)")
        print(f"{'':>5} {'行业':<12} {'天数':>4} {'涨停':>4} {'阶段':<12} {'趋势':<4} {'判断'}")
        for sec, info in sorted(streaks.items(), key=mainline_sort_key):
            stage = info.get("stage_auto", "")
            trend = info.get("trend", "")
            is_actionable = stage in ("启动(首日)", "主升早")
            is_danger = stage == "高潮/退潮风险"
            prefix = ">>>" if is_actionable else ("  x" if is_danger else "   ")
            verdict = "可操作" if is_actionable else ("不碰" if is_danger else "观察")
            print(
                f"  {prefix} {sec:<12} {info['streak_days']:>3}d"
                f" {info['today_count']:>3}只 {stage:<12} {trend:<4} {verdict}"
            )

    # ── Section E2: 大票·基本面关注 (Track A候选, 独立于主线) ────────────────
    mainline_sectors = set(streaks.keys()) if streaks else set()
    bigcap_watch = []
    seen_codes = set()
    for s in scored:
        code = s.get("代码", "")
        if code in seen_codes:
            continue
        raw = s.get("TB总分_raw", s.get("TB总分", 0))
        penalty = s.get("D6_penalty", 0)
        mkt = s.get("总市值_亿") or 0.0
        sec = s.get("行业", "")
        in_ml = any(ml in sec or sec in ml for ml in mainline_sectors)
        # Criteria: large-cap penalized OR high raw TB (independent or penalized)
        if mkt >= 500 and penalty <= -15:
            bigcap_watch.append(s)
            seen_codes.add(code)
        elif raw >= 80 and sec not in mainline_sectors and not s.get("veto"):
            bigcap_watch.append(s)
            seen_codes.add(code)
    bigcap_watch.sort(key=lambda x: x.get("总市值_亿") or 0, reverse=True)

    if bigcap_watch:
        print()
        print("大票·基本面关注 (与主线独立, 大beta跟踪)")
        print(
            f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10}"
            f" {'市值亿':>6} {'raw':>4}→{'最终':>4} {'D6惩罚':>6} {'D6状态':<20} {'判断'}"
        )
        for i, s in enumerate(bigcap_watch[:15], 1):
            raw = s.get("TB总分_raw", s.get("TB总分", 0))
            final = s.get("TB总分", 0)
            penalty = s.get("D6_penalty", 0)
            mkt = s.get("总市值_亿") or 0.0
            flags = s.get("D6_flags", [])
            flag_str = ",".join(f for f in flags if f not in ("HEALTHY", "DATA_ERROR"))[:20]
            if not flag_str:
                flag_str = "HEALTHY" if "HEALTHY" in flags else "N/A"
            if "HEALTHY" in flags and not s.get("veto"):
                verdict = "可操作"
            elif s.get("veto"):
                verdict = "等回调"
            elif penalty <= -15:
                verdict = "等回调"
            else:
                verdict = "谨慎"
            print(
                f"{i:>3} {s['代码']:<8} {s['名称']:<8} {s.get('行业', ''):<10}"
                f" {mkt:>5.0f} {raw:>4}→{final:>4} {penalty:>+5}"
                f" {flag_str:<20} {verdict}"
            )

    # ── Section F: 强势非涨停 TOP15 (含D5弹性) ───────────────────────────────
    strong_scored = [s for s in scored if s.get("数据源") == "push2delay"]
    if strong_scored:
        print()
        print("★ 强势非涨停 TOP15 (全市场扫描, 覆盖创业板/科创板10-19%盲区)")
        print(
            f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10}"
            f" {'涨幅':>6} {'市值亿':>6} {'TB分':>5} {'级':>3} {'D5弹':>5}"
        )
        for i, s in enumerate(strong_scored[:15], 1):
            d5_elas = s.get("D5分", s.get("D5_弹性", 0))
            if isinstance(d5_elas, str):
                try:
                    d5_elas = int(d5_elas)
                except (ValueError, TypeError):
                    d5_elas = 0
            mkt = s.get("总市值_亿") or 0.0
            change = s.get("涨跌幅") or 0.0
            tb_score = s.get("TB总分") or 0
            grade = s.get("TB评级") or "-"
            print(
                f"{i:>3} {s['代码']:<8} {s['名称']:<8} {s.get('行业', ''):<10}"
                f" {change:>+5.2f}% {mkt:>5.0f} {tb_score:>5} {grade:>3} {d5_elas:>5}"
            )

    # ── Build TA lookup for cross-referencing ──────────────────────────────────
    ta_map: dict[str, dict] = {}
    if ta_universe:
        for t in ta_universe:
            ta_map[t["代码"]] = t

    # ── Section G: Funnel 1 — Track B评分 TOP N (含TA双轨评级) ────────────────
    print()
    print(f"═══ Funnel 1: Track B动量评分 TOP{top_n} (含Track A双轨评级) ═══")
    print(
        f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10}"
        f" {'市值亿':>6} {'TB分':>7} {'TB':>3} {'TA':>3}"
        f" {'D1':>2} {'D2':>2} {'D3':<4} {'D4':<6}"
        f" {'D5弹':>5} {'20d%':>5} {'量比':>4} {'D6筹码'} {'veto':>5}"
    )
    for i, s in enumerate(scored[:top_n], 1):
        g20 = s.get("D6_20d涨幅")
        g20_str = f"{g20:>+4.0f}%" if g20 is not None else "  N/A"
        vr = s.get("D6_量比")
        vr_str = f"{vr:>3.1f}x" if vr is not None else " N/A"
        flags = s.get("D6_flags", [])
        flag_str = ",".join(f for f in flags if f not in ("HEALTHY", "DATA_ERROR"))
        if not flag_str:
            flag_str = "✓" if "HEALTHY" in flags else "N/A"
        penalty = s.get("D6_penalty", 0)
        raw = s.get("TB总分_raw", s.get("TB总分", 0))
        tb_total = s.get("TB总分", 0)
        score_str = f"{tb_total:>4}" if penalty == 0 else f"{raw}→{tb_total}"
        d5_val = s.get("D5分", 0) or 0
        veto_str = "❌" if s.get("veto") else ""
        mkt = s.get("总市值_亿") or 0.0
        ta_info = ta_map.get(s.get("代码", ""), {})
        ta_grade = ta_info.get("TA评级", "-")
        print(
            f"{i:>3} {s['代码']:<8} {s['名称']:<8} {s.get('行业', ''):<10}"
            f" {mkt:>5.0f} {score_str:>7} {s.get('TB评级', '-'):>3} {ta_grade:>3}"
            f" {s.get('D1', '-'):>2} {s.get('D2', '-'):>2}"
            f" {s.get('D3', '-'):<4} {s.get('D4', '-'):<6}"
            f" {d5_val:>5} {g20_str} {vr_str} {flag_str} {veto_str}"
        )

    # ── Section GA: Funnel 2 — Track A基本面排名 (独立发现) ───────────────────
    if ta_universe:
        ta_show = min(top_n, len(ta_universe))
        print()
        print(f"═══ Funnel 2: Track A基本面排名 TOP{ta_show} (独立发现, 不受TB筛选) ═══")
        print(
            f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10}"
            f" {'市值亿':>6} {'TA分':>5} {'TA':>3} {'TB':>3}"
            f" {'TA1跟踪':<8} {'TA2行业':<8} {'TA3规模':<6}"
            f" {'TA4健康':<8} {'TA5催化':<6} {'来源'}"
        )
        for i, t in enumerate(ta_universe[:ta_show], 1):
            mkt = t.get("总市值_亿", 0)
            tb_g = t.get("tb_grade", "") or "-"
            if t["in_tb"]:
                src = "TB+WL" if t.get("TA1_label", "无") != "无" else "TB"
            else:
                src = "WL/持仓"
            print(
                f"{i:>3} {t['代码']:<8} {t['名称']:<8} {t.get('行业', ''):<10}"
                f" {mkt:>5.0f} {t['TA总分']:>5} {t['TA评级']:>3} {tb_g:>3}"
                f" {t['TA1_label']:<8} {t['TA2_label']:<8} {t['TA3_label']:<6}"
                f" {t['TA4_label']:<8} {t['TA5_label']:<6} {src}"
            )

    # ── Section H: 多时间框架D6位置 ──────────────────────────────────────────
    multi_frame_stocks: list[tuple[dict, list[str]]] = []
    for s in scored[:top_n]:
        flags = s.get("D6_flags", [])
        mf = [f for f in flags if f in _MULTI_FRAME_ALERT_FLAGS]
        if mf or s.get("veto"):
            multi_frame_stocks.append((s, mf))

    if multi_frame_stocks:
        print()
        print("多时间框架D6位置 (异常标记)")
        print(
            f"{'#':>3} {'代码':<8} {'名称':<8}"
            f" {'20d%':>6} {'60d%':>6} {'250d%':>7} {'综合位':>6}  核心flags"
        )
        for i, (s, mf) in enumerate(multi_frame_stocks, 1):
            g20 = s.get("D6_20d涨幅")
            g60 = s.get("D6_60d涨幅")
            g250 = s.get("D6_250d涨幅")
            comp = s.get("D6_综合位置")
            g20_s = f"{g20:>+5.0f}%" if g20 is not None else "   N/A"
            g60_s = f"{g60:>+5.0f}%" if g60 is not None else "   N/A"
            g250_s = f"{g250:>+6.0f}%" if g250 is not None else "    N/A"
            comp_s = f"{comp:>5.1f}" if comp is not None else "  N/A"
            flag_detail = ",".join(mf) if mf else ""
            if s.get("veto"):
                veto_reasons = ",".join(s.get("veto_reasons", []))
                flag_detail = (
                    f"VETO({veto_reasons})" + (f",{flag_detail}" if flag_detail else "")
                )
            print(
                f"{i:>3} {s['代码']:<8} {s['名称']:<8}"
                f" {g20_s} {g60_s} {g250_s} {comp_s}  {flag_detail}"
            )

    # ── Section I: B→A 产业链发散候选 ────────────────────────────────────────
    if chains:
        print()
        print(f"B→A 产业链发散候选 — {len(chains)}条链")
        for c in chains:
            signals = ", ".join(
                f"{s['名称']}({s['TB评级']})" for s in c["信号股"]
            )
            print(f"  [{c['产业链']}] {signals}")
            print(f"    → {c['建议发散方向']}")

    # ── Section J: Claude TODO ────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("Claude TODO (脚本无法自动完成的部分)")
    print("=" * 60)
    print("1. 深度Track A: 对Funnel 1 TB≥B+且TA≥B+的标的做深度基本面研究")
    print("2. Track A独立发现: 对Funnel 2中TA高分但不在TB中的标的评估")
    print("3. 先手票识别: 对每个热门行业,搜同板块+3~9%未涨停的股")
    print("4. B→A产业链发散: 从涨停信号出发,找上下游滞涨标的")
    print("5. 催化剂匹配: 查未来1-2周催化事件,与标的匹配")

    # ── Section K: 统计汇总 (双漏斗) ─────────────────────────────────────────
    print()
    s_count = sum(1 for s in scored if s.get("TB评级") == "S")
    a_plus = sum(1 for s in scored if s.get("TB评级") == "A+")
    a_count = sum(1 for s in scored if s.get("TB评级") == "A")
    a_minus = sum(1 for s in scored if s.get("TB评级") == "A-")
    veto_count = sum(1 for s in scored if s.get("veto"))
    overheat_count = sum(
        1 for s in scored
        if any(f in s.get("D6_flags", []) for f in _OVERHEAT_FLAGS)
    )
    print(
        f"TB评级分布: S={s_count} A+={a_plus} A={a_count} A-={a_minus}"
        f" | 涨停{zt_count}只 | 强势非涨停{strong_count}只 | TB合计{len(scored)}只"
    )
    if ta_universe:
        ta_high = sum(1 for t in ta_universe if t["TA评级"] in ("S", "A+", "A", "A-"))
        ta_bp = sum(1 for t in ta_universe if t["TA评级"] in ("S", "A+", "A", "A-", "B+"))
        dual_high = sum(
            1 for s in scored
            if not s.get("veto")
            and s.get("TB评级", "") in ("S", "A+", "A", "A-", "B+")
            and ta_map.get(s.get("代码", ""), {}).get("TA评级", "") in ("S", "A+", "A", "A-", "B+")
        )
        print(
            f"TA评级分布: A-以上{ta_high}只 | B+以上{ta_bp}只 | TA宇宙{len(ta_universe)}只"
        )
        print(f"双轨高分(TB≥B+ & TA≥B+ & 无VETO): {dual_high}只")
    print(f"D6统计: 多时间框架过热{overheat_count}只 | veto{veto_count}只")
    if data.get("errors"):
        print(f"数据源问题: {len(data['errors'])}个 (详见JSON)")


# ── build_json_output ─────────────────────────────────────────────────────────

def build_json_output(
    data: dict,
    scored: list[dict],
    chains: list[dict],
    d7_result: dict,
    streaks: dict | None,
    date_str: str,
    ta_universe: list[dict] | None = None,
) -> dict:
    """构建JSON输出字典 (双漏斗架构)。

    Args:
        data:         原始扫描数据 (zt_pool, lhb, sector_flow, concept_flow, …)
        scored:       Track B评分列表
        chains:       产业链发散候选列表
        d7_result:    D7趋势检测结果 (含trend_alerts / sector_alerts)
        streaks:      D8主线连板追踪字典 (可为None)
        date_str:     扫描日期字符串 (YYYYMMDD 或 YYYY-MM-DD)
        ta_universe:  Track A评分列表 (可为None)

    Returns:
        JSON-serializable dict，可直接 json.dump 写文件。
    """
    safe_streaks: dict = streaks if streaks is not None else {}

    d8_mainline_sorted = [
        {
            "sector": sec,
            **info,
            "actionability_rank": STAGE_PRIORITY.get(info.get("stage_auto", ""), 99),
        }
        for sec, info in sorted(safe_streaks.items(), key=mainline_sort_key)
    ]

    mainline_sectors = set(safe_streaks.keys())
    seen_codes = set()
    bigcap_watch = []
    for s in scored:
        code = s.get("代码", "")
        if code in seen_codes:
            continue
        raw = s.get("TB总分_raw", s.get("TB总分", 0))
        penalty = s.get("D6_penalty", 0)
        mkt = s.get("总市值_亿") or 0.0
        sec = s.get("行业", "")
        if mkt >= 500 and penalty <= -15:
            bigcap_watch.append(s)
            seen_codes.add(code)
        elif raw >= 80 and sec not in mainline_sectors and not s.get("veto"):
            bigcap_watch.append(s)
            seen_codes.add(code)
    bigcap_watch.sort(key=lambda x: x.get("总市值_亿") or 0, reverse=True)

    output = {
        "scan_date": date_str,
        "scan_time": datetime.now().isoformat(),
        "scan_version": "v6.2-dual-funnel",
        "market_summary": {
            "涨停数": len(data.get("zt_pool", [])),
            "强势非涨停数": len(data.get("strong_movers", [])),
            "龙虎榜数": len(data.get("lhb", [])),
            "北向净买_亿": data.get("northbound", {}).get("净买额_亿", None),
        },
        "sector_flow_top10": data.get("sector_flow", [])[:10],
        "concept_flow_top10": data.get("concept_flow", [])[:10],
        "trackb_scored": scored,
        "tracka_universe": ta_universe or [],
        "bigcap_watch": bigcap_watch[:15],
        "supply_chain_candidates": chains,
        "d7_trend_alerts": d7_result.get("trend_alerts", []),
        "d7_sector_alerts": d7_result.get("sector_alerts", []),
        "d8_mainline_streaks": streaks,
        "d8_mainline_sorted": d8_mainline_sorted,
        "errors": data.get("errors", []),
    }
    return output
