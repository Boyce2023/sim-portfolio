#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.14"]
# ///
"""
UASS 自动扫描引擎 v1.0 — 全自动数据拉取 + Track B评分 + 产业链发散

替代人工搜索，30秒内完成数据收集+初步评分。
Claude只需补Track A评级(thesis/催化剂) + 交叉发散判断 + 出表。

用法:
  uv run --script scripts/uass_scan.py                    # 默认扫描(今日)
  uv run --script scripts/uass_scan.py --date 20260528    # 指定日期
  uv run --script scripts/uass_scan.py --json             # JSON输出(供agent读取)
  uv run --script scripts/uass_scan.py --top 30           # 涨停板TOP N

数据源: AKShare (涨停板池/龙虎榜/板块资金流向/北向汇总)
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent
SCAN_OUTPUT = REPO / "uass_scan_output.json"

# ── Track B 评分常量 (与 tb_engine.py v2.0 一致) ─────────────────────────────

D1_SCORES = {"S": 45, "A": 35, "B": 25, "C": 12, "X": 0}
D2_SCORES = {"S": 30, "A": 24, "B": 18, "C": 10, "D": 0}
D3_SCORES = {"龙头": 25, "先手": 20, "跟涨": 12, "补涨": 6, "掉队": 0}
D4_SCORES = {"启动": 20, "主升早": 16, "主升中晚": 8, "高潮分歧": 3, "退潮": 0}
D5_SCORES = {"科创创业小盘": 15, "主板小盘": 13, "主板中盘": 10, "大盘蓝筹": 8, "北交A": 10, "北交B": 6, "北交超小": 0}

GRADE_THRESHOLDS = [
    (120, "S"), (108, "A+"), (95, "A"), (85, "A-"),
    (75, "B+"), (65, "B"), (55, "B-"), (40, "C"), (0, "D"),
]

# ── 板块→产业链映射 (B→A发散用) ──────────────────────────────────────────────

SUPPLY_CHAIN_MAP = {
    "MLCC": ["被动元件", "电子元件", "MLCC概念"],
    "MLCC上游": ["覆铜板", "PCB", "离型膜", "载带"],
    "PCB": ["印制电路板", "覆铜板", "电子元件"],
    "光通信": ["CPO概念", "光模块", "光芯片", "5G概念"],
    "半导体": ["芯片概念", "半导体", "光刻机", "EDA概念"],
    "CVD金刚石": ["超硬材料", "金刚石", "人造钻石"],
    "稀有金属": ["小金属", "稀土永磁", "锗", "钼"],
    "电力设备": ["特高压", "电网设备", "智能电网"],
    "创新药": ["创新药", "CRO概念", "ADC概念", "生物医药"],
    "智能驾驶": ["无人驾驶", "智能座舱", "车联网", "汽车电子"],
    "AI算力": ["算力概念", "AI概念", "服务器", "液冷概念"],
    "军工": ["国防军工", "航天航空", "军工电子"],
}


def score_to_grade(total: int) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if total >= threshold:
            return grade
    return "D"


def classify_d5(code: str, market_cap: float) -> tuple[str, int]:
    cap_b = market_cap / 1e8
    if code.startswith("8") or code.startswith("4"):
        if cap_b < 10:
            return "北交超小", D5_SCORES["北交超小"]
        elif cap_b < 100:
            return "北交A", D5_SCORES["北交A"]
        else:
            return "北交B", D5_SCORES["北交B"]
    elif code.startswith("68") or code.startswith("3"):
        if cap_b < 200:
            return "科创创业小盘", D5_SCORES["科创创业小盘"]
        elif cap_b < 1000:
            return "主板中盘", D5_SCORES["主板中盘"]
        else:
            return "大盘蓝筹", D5_SCORES["大盘蓝筹"]
    else:
        if cap_b < 300:
            return "主板小盘", D5_SCORES["主板小盘"]
        elif cap_b < 1000:
            return "主板中盘", D5_SCORES["主板中盘"]
        else:
            return "大盘蓝筹", D5_SCORES["大盘蓝筹"]


def auto_score_d2(row: dict) -> tuple[str, int]:
    lianban = row.get("连板数", 1)
    seal_money = row.get("封板资金", 0)
    turnover_rate = row.get("换手率", 0)
    zb_count = row.get("炸板次数", 0)

    if lianban >= 3 and turnover_rate < 10:
        return "S", D2_SCORES["S"]
    if lianban >= 2 or (seal_money > 1e8 and zb_count == 0):
        return "A", D2_SCORES["A"]
    if seal_money > 0:
        return "B", D2_SCORES["B"]
    return "C", D2_SCORES["C"]


def auto_score_d3_batch(stocks: list[dict], sector_map: dict[str, list]) -> None:
    for sector, members in sector_map.items():
        if not members:
            continue
        sorted_m = sorted(members, key=lambda x: x.get("首次封板时间", "999999"))
        for i, s in enumerate(sorted_m):
            if i == 0:
                s["_d3"] = "龙头"
                s["_d3_score"] = D3_SCORES["龙头"]
            elif i <= 2:
                s["_d3"] = "先手"
                s["_d3_score"] = D3_SCORES["先手"]
            else:
                s["_d3"] = "跟涨"
                s["_d3_score"] = D3_SCORES["跟涨"]


def auto_score_d4(row: dict) -> tuple[str, int]:
    lianban = row.get("连板数", 1)
    zb = row.get("炸板次数", 0)
    if lianban == 1 and zb == 0:
        return "启动", D4_SCORES["启动"]
    if lianban <= 3 and zb <= 1:
        return "主升早", D4_SCORES["主升早"]
    if lianban <= 6:
        return "主升中晚", D4_SCORES["主升中晚"]
    if zb >= 3 or lianban > 6:
        return "高潮分歧", D4_SCORES["高潮分歧"]
    return "主升中晚", D4_SCORES["主升中晚"]


# ── 数据拉取 ─────────────────────────────────────────────────────────────────

def _retry(fn, retries=2, delay=1):
    import time
    for i in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            if i == retries:
                raise e
            time.sleep(delay)


def fetch_all(date_str: str) -> dict:
    import akshare as ak

    result = {
        "date": date_str,
        "fetch_time": datetime.now().strftime("%H:%M:%S"),
        "zt_pool": [],
        "lhb": [],
        "sector_flow": [],
        "concept_flow": [],
        "northbound": {},
        "errors": [],
    }

    # 1. 涨停板池
    try:
        df = ak.stock_zt_pool_em(date=date_str)
        for _, r in df.iterrows():
            result["zt_pool"].append({
                "代码": str(r.get("代码", "")),
                "名称": str(r.get("名称", "")),
                "涨跌幅": float(r.get("涨跌幅", 0)),
                "最新价": float(r.get("最新价", 0)),
                "成交额": float(r.get("成交额", 0)),
                "流通市值": float(r.get("流通市值", 0)),
                "总市值": float(r.get("总市值", 0)),
                "换手率": float(r.get("换手率", 0)),
                "封板资金": float(r.get("封板资金", 0)),
                "首次封板时间": str(r.get("首次封板时间", "")),
                "炸板次数": int(r.get("炸板次数", 0)),
                "连板数": int(r.get("连板数", 1)),
                "所属行业": str(r.get("所属行业", "")),
            })
        print(f"  涨停板池: {len(result['zt_pool'])}只")
    except Exception as e:
        result["errors"].append(f"涨停板: {e}")
        print(f"  涨停板池: 失败 ({e})")

    # 2. 龙虎榜
    try:
        df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)
        for _, r in df.iterrows():
            result["lhb"].append({
                "代码": str(r.get("代码", "")),
                "名称": str(r.get("名称", "")),
                "涨跌幅": float(r.get("涨跌幅", 0)),
                "龙虎榜净买额": float(r.get("龙虎榜净买额", 0)),
                "龙虎榜买入额": float(r.get("龙虎榜买入额", 0)),
                "龙虎榜卖出额": float(r.get("龙虎榜卖出额", 0)),
                "换手率": float(r.get("换手率", 0)),
                "流通市值": float(r.get("流通市值", 0)),
                "解读": str(r.get("解读", "")),
                "上榜原因": str(r.get("上榜原因", "")),
            })
        print(f"  龙虎榜: {len(result['lhb'])}条")
    except Exception as e:
        result["errors"].append(f"龙虎榜: {e}")
        print(f"  龙虎榜: 失败 ({e})")

    # 3. 板块资金流向 (带重试)
    try:
        df = _retry(lambda: ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流"))
        for _, r in df.iterrows():
            result["sector_flow"].append({
                "名称": str(r.get("名称", "")),
                "涨跌幅": float(r.get("今日涨跌幅", 0)),
                "主力净流入": float(r.get("今日主力净流入-净额", 0)),
                "主力净占比": float(r.get("今日主力净流入-净占比", 0)),
                "领涨股": str(r.get("今日主力净流入最大股", "")),
            })
        result["sector_flow"].sort(key=lambda x: x["主力净流入"], reverse=True)
        print(f"  板块资金: {len(result['sector_flow'])}个行业")
    except Exception as e:
        result["errors"].append(f"板块资金: {e}")
        print(f"  板块资金: 失败 ({e})")

    # 3b. 概念板块涨幅 (补充)
    try:
        df = _retry(lambda: ak.stock_board_concept_name_em())
        df = df.sort_values("涨跌幅", ascending=False)
        for _, r in df.head(20).iterrows():
            result["concept_flow"].append({
                "名称": str(r.get("板块名称", r.get("名称", ""))),
                "涨跌幅": float(r.get("涨跌幅", 0)),
                "领涨股": str(r.get("领涨股票", r.get("最新价", ""))),
            })
        print(f"  概念板块: TOP20已获取")
    except Exception as e:
        result["errors"].append(f"概念板块: {e}")
        print(f"  概念板块: 失败")

    # 4. 北向资金汇总
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        north = df[df["资金方向"] == "北向"]
        total_net = north["成交净买额"].sum()
        result["northbound"] = {
            "净买额_亿": round(total_net, 2),
            "沪股通_上涨": int(north[north["板块"] == "沪股通"]["上涨数"].sum()),
            "沪股通_下跌": int(north[north["板块"] == "沪股通"]["下跌数"].sum()),
            "深股通_上涨": int(north[north["板块"] == "深股通"]["上涨数"].sum()),
            "深股通_下跌": int(north[north["板块"] == "深股通"]["下跌数"].sum()),
        }
        print(f"  北向资金: 净买{result['northbound']['净买额_亿']}亿")
    except Exception as e:
        result["errors"].append(f"北向资金: {e}")
        print(f"  北向资金: 失败 ({e})")

    return result


# ── Track B 自动评分 ─────────────────────────────────────────────────────────

def auto_score_trackb(data: dict) -> list[dict]:
    zt_pool = data["zt_pool"]
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

    scored = []
    for s in zt_pool:
        code = s["代码"]
        lhb = lhb_map.get(code, {})

        net_buy = lhb.get("龙虎榜净买额", 0)
        jigou = "机构" in lhb.get("解读", "")
        has_lhb = code in lhb_map

        if net_buy >= 5e8 and jigou:
            d1, d1s = "S", D1_SCORES["S"]
        elif net_buy >= 2e8 or (has_lhb and jigou):
            d1, d1s = "A", D1_SCORES["A"]
        elif has_lhb:
            d1, d1s = "B", D1_SCORES["B"]
        else:
            d1, d1s = "C", D1_SCORES["C"]

        d2, d2s = auto_score_d2(s)
        d3 = s.get("_d3", "跟涨")
        d3s = s.get("_d3_score", D3_SCORES["跟涨"])
        d4, d4s = auto_score_d4(s)
        d5_label, d5s = classify_d5(code, s.get("总市值", 0))

        total = d1s + d2s + d3s + d4s + d5s
        grade = score_to_grade(total)

        change_pct = s.get("涨跌幅", 0)
        is_limit_up = change_pct >= 9.8 or (code.startswith("3") and change_pct >= 19.5) or (code.startswith("68") and change_pct >= 19.5) or ((code.startswith("8") or code.startswith("4")) and change_pct >= 29)

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
            "D5": d5_label, "D5分": d5s,
            "TB总分": total,
            "TB评级": grade,
            "涨停": is_limit_up,
            "可操作性": "涨停" if is_limit_up else "可买",
        })

    scored.sort(key=lambda x: x["TB总分"], reverse=True)
    return scored


# ── 产业链发散候选 ───────────────────────────────────────────────────────────

def find_supply_chain_candidates(scored: list[dict], sector_flow: list[dict]) -> list[dict]:
    hot_sectors = set()
    for s in scored:
        if s["TB评级"] in ("S", "A+", "A"):
            hot_sectors.add(s["行业"])

    top_flow_sectors = [sf["名称"] for sf in sector_flow[:15]]

    candidates = []
    for chain_name, related in SUPPLY_CHAIN_MAP.items():
        chain_hot = False
        signal_stocks = []
        for s in scored:
            if s["行业"] in related or any(r in s.get("行业", "") for r in related):
                chain_hot = True
                if s["TB评级"] in ("S", "A+", "A"):
                    signal_stocks.append(s)
        if chain_hot and signal_stocks:
            candidates.append({
                "产业链": chain_name,
                "信号股": [{"代码": s["代码"], "名称": s["名称"], "TB评级": s["TB评级"], "涨停": s["涨停"]} for s in signal_stocks[:3]],
                "关联板块": related,
                "建议发散方向": f"从{signal_stocks[0]['名称']}等涨停信号出发,找同链未涨停的先手票",
            })

    return candidates


# ── 输出 ─────────────────────────────────────────────────────────────────────

def print_summary(data: dict, scored: list[dict], chains: list[dict], top_n: int):
    zt_count = len(data["zt_pool"])
    lhb_count = len(data["lhb"])
    nb = data.get("northbound", {})

    print()
    print(f"UASS 自动扫描 | {data['date']} | 涨停{zt_count}只 | 龙虎榜{lhb_count}条 | 北向净买{nb.get('净买额_亿', '?')}亿")

    # 板块资金TOP10
    if data["sector_flow"]:
        print()
        print("板块资金流向 TOP10")
        print(f"{'#':>3} {'板块':<12} {'涨跌幅':>7} {'主力净流入亿':>10} {'领涨股':<10}")
        for i, sf in enumerate(data["sector_flow"][:10], 1):
            net_b = sf["主力净流入"] / 1e8
            print(f"{i:>3} {sf['名称']:<12} {sf['涨跌幅']:>+6.2f}% {net_b:>+9.1f} {sf['领涨股']:<10}")

    # 概念板块TOP10
    if data.get("concept_flow"):
        print()
        print("概念板块涨幅 TOP10")
        for i, cf in enumerate(data["concept_flow"][:10], 1):
            print(f"{i:>3} {cf['名称']:<16} {cf['涨跌幅']:>+6.2f}%")

    # 热门行业统计(从涨停板归纳)
    sector_zt_count: dict[str, int] = {}
    for s in scored:
        sec = s["行业"]
        sector_zt_count[sec] = sector_zt_count.get(sec, 0) + 1
    hot_sectors = sorted(sector_zt_count.items(), key=lambda x: x[1], reverse=True)[:10]
    print()
    print("涨停集中行业 TOP10")
    for sec, cnt in hot_sectors:
        names = [s["名称"] for s in scored if s["行业"] == sec][:3]
        print(f"  {sec}: {cnt}只涨停 ({', '.join(names)})")

    # Track B 评分 TOP N
    print()
    print(f"Track B 自动评分 TOP{top_n}")
    print(f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10} {'市值亿':>6} {'TB分':>4} {'级':>3} {'D1':>2} {'D2':>2} {'D3':<4} {'D4':<6} {'连板':>2} {'龙虎榜净买亿':>8}")
    for i, s in enumerate(scored[:top_n], 1):
        print(f"{i:>3} {s['代码']:<8} {s['名称']:<8} {s['行业']:<10} {s['总市值_亿']:>5.0f} {s['TB总分']:>4} {s['TB评级']:>3} {s['D1']:>2} {s['D2']:>2} {s['D3']:<4} {s['D4']:<6} {s['连板数']:>2} {s['龙虎榜净买_亿']:>+7.1f}")

    # 产业链发散
    if chains:
        print()
        print(f"B→A 产业链发散候选 — {len(chains)}条链")
        for c in chains:
            signals = ", ".join(f"{s['名称']}({s['TB评级']})" for s in c["信号股"])
            print(f"  [{c['产业链']}] {signals}")
            print(f"    → {c['建议发散方向']}")

    # Claude TODO
    print()
    print("=" * 60)
    print("Claude TODO (脚本无法自动完成的部分)")
    print("=" * 60)
    print("1. Track A评级: 对TOP30逐只补thesis/催化剂/供需判断")
    print("2. 先手票识别: 对每个热门行业,搜同板块+3~9%未涨停的股")
    print("3. B→A产业链发散: 从涨停信号出发,找上下游滞涨标的")
    print("4. 主线演进: 判断各主线阶段(启动/主升/高潮/退潮)和方向")
    print("5. 催化剂匹配: 查未来1-2周催化事件,与标的匹配")

    # 统计
    print()
    s_count = sum(1 for s in scored if s["TB评级"] == "S")
    a_plus = sum(1 for s in scored if s["TB评级"] == "A+")
    a_count = sum(1 for s in scored if s["TB评级"] == "A")
    a_minus = sum(1 for s in scored if s["TB评级"] == "A-")
    print(f"评级分布: S={s_count} A+={a_plus} A={a_count} A-={a_minus} | 涨停{zt_count}只")
    if data["errors"]:
        print(f"数据源问题: {len(data['errors'])}个 (详见JSON)")


def main():
    parser = argparse.ArgumentParser(description="UASS自动扫描引擎")
    parser.add_argument("--date", type=str, help="扫描日期 YYYYMMDD")
    parser.add_argument("--json", action="store_true", help="输出JSON")
    parser.add_argument("--top", type=int, default=25, help="显示TOP N")
    args = parser.parse_args()

    if args.date:
        date_str = args.date
    else:
        now = datetime.now()
        if now.hour < 15:
            date_str = (now - timedelta(days=1)).strftime("%Y%m%d")
        else:
            date_str = now.strftime("%Y%m%d")

    print(f"UASS扫描启动 | 日期: {date_str}")
    print("-" * 40)

    data = fetch_all(date_str)
    scored = auto_score_trackb(data)
    chains = find_supply_chain_candidates(scored, data["sector_flow"])

    output = {
        "scan_date": date_str,
        "scan_time": datetime.now().isoformat(),
        "market_summary": {
            "涨停数": len(data["zt_pool"]),
            "龙虎榜数": len(data["lhb"]),
            "北向净买_亿": data.get("northbound", {}).get("净买额_亿", None),
        },
        "sector_flow_top10": data["sector_flow"][:10],
        "concept_flow_top10": data.get("concept_flow", [])[:10],
        "trackb_scored": scored,
        "supply_chain_candidates": chains,
        "errors": data["errors"],
    }

    with open(SCAN_OUTPUT, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print_summary(data, scored, chains, args.top)
        print()
        print(f"完整数据已存: {SCAN_OUTPUT}")


if __name__ == "__main__":
    main()
