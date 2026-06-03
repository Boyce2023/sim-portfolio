#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.14", "yfinance>=0.2", "requests>=2.28", "baostock>=0.8"]
# ///
"""
UASS 自动扫描引擎 v5.0 — 并发数据拉取 + SQLite K线缓存 + Track B评分 + D6筹码体检 + D7缓涨检测

v5.0: D7缓涨检测(多日趋势+板块关联) + 滚动状态持久化
v4.0: 并发API(~3s) + SQLite K线缓存(D6 <1s) + Pipeline统一入口
v3.1: push2delay双轨 + baostock批量预取
v3.0: 全自动数据拉取 + Track B评分 + D6筹码体检

用法:
  uv run --script scripts/uass_scan.py                    # 默认扫描(今日)
  uv run --script scripts/uass_scan.py --date 20260528    # 指定日期
  uv run --script scripts/uass_scan.py --json             # JSON输出(供agent读取)
  uv run --script scripts/uass_scan.py --top 30           # 涨停板TOP N
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
MAINLINE_HISTORY = REPO / "data" / "mainline_history.json"

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
    # ── 原有14条 ──────────────────────────────────────────────────────────────
    "MLCC": ["被动元件", "电子元件", "MLCC概念", "元件"],
    "MLCC上游": ["覆铜板", "PCB", "离型膜", "载带", "元件"],
    "PCB": ["印制电路板", "覆铜板", "电子元件", "元件"],
    "光通信": ["CPO概念", "光模块", "光芯片", "5G概念", "通信设备"],
    "半导体": ["芯片概念", "半导体", "光刻机", "EDA概念", "半导体及元件"],
    "CVD金刚石": ["超硬材料", "金刚石", "人造钻石"],
    "稀有金属": ["小金属", "稀土永磁", "锗", "钼", "有色金属"],
    "电力设备": ["特高压", "电网设备", "智能电网"],
    "创新药": ["创新药", "CRO概念", "ADC概念", "生物医药", "医药商业", "化学制药", "生物制品"],
    "智能驾驶": ["无人驾驶", "智能座舱", "车联网", "汽车电子", "汽车零部件", "汽车整车"],
    "AI算力": ["算力概念", "AI概念", "服务器", "液冷概念", "通信设备", "计算机设备"],
    "军工": ["国防军工", "航天航空", "军工电子", "航天装备", "军工电子Ⅱ"],
    "电力": ["煤炭开采", "电力设备", "天然气"],
    "煤炭": ["煤化工", "电力"],
    # ── 新增14条 ──────────────────────────────────────────────────────────────
    "机器人": ["人形机器人", "机器人概念", "工业机器人", "减速器", "丝杠", "自动化设备", "通用设备"],
    "光伏": ["光伏设备", "太阳能", "光伏组件", "HJT电池", "钙钛矿", "电源设备"],
    "储能": ["储能概念", "液流电池", "钠离子电池", "储能电站"],
    "新能源车": ["新能源汽车", "动力电池", "锂电池", "电动汽车", "充电桩", "汽车零部件", "汽车整车"],
    "医疗器械": ["医疗器械", "体外诊断", "骨科器械", "手术机器人", "高值耗材", "专用设备"],
    "消费电子": ["消费电子", "苹果概念", "折叠屏", "智能穿戴", "TWS耳机", "光学光电子"],
    "低空经济": ["低空经济", "无人机", "eVTOL", "航空发动机", "飞行汽车"],
    "CDMO": ["CDMO概念", "CXO概念", "医药外包", "原料药", "创新药研发", "医药商业", "化学制药", "生物制品"],
    "氟化工": ["氟化工", "含氟材料", "制冷剂", "锂电材料", "氟聚合物"],
    "核能": ["核电", "核能概念", "核废料处理", "小堆核能", "铀矿开采", "电力"],
    "卫星互联网": ["卫星互联网", "卫星导航", "低轨卫星", "北斗导航", "太空经济"],
    "数据要素": ["数据要素", "数字经济", "数据中心", "大数据", "数据安全"],
    "信创": ["信创概念", "国产替代", "国产操作系统", "国产芯片", "鸿蒙概念", "计算机设备", "软件开发"],
    "固态电池": ["固态电池", "全固态电池", "钠电池", "电解质", "新型储能"],
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
    vol_ratio = row.get("vol_ratio") or 0  # None -> 0

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


def auto_score_d3_batch(stocks: list[dict], sector_map: dict[str, list]) -> None:
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


def _safe_float(val, default=0.0) -> float:
    if val is None or val == "-" or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def fetch_strong_movers(min_change_pct: float = 5.0, max_pages: int = 8) -> list[dict]:
    """
    全市场强势股扫描 via push2delay.eastmoney.com HTTPS.
    VPN下依然可用(HTTPS域名解析不受Shadowrocket TUN劫持).
    按涨跌幅降序翻页, 遇到<min_change_pct停止.
    """
    import requests
    import time

    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    all_stocks = []

    for page in range(1, max_pages + 1):
        params = {
            "pn": str(page), "pz": "100", "po": "1",
            "fid": "f3", "np": "1",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fltt": "2", "invt": "2",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f2,f3,f6,f8,f12,f14,f20,f21,f100",
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            data = resp.json()
            items = data.get("data", {}).get("diff", [])
            if not items:
                break

            stop = False
            for item in items:
                chg = item.get("f3")
                if chg is None or not isinstance(chg, (int, float)) or chg < min_change_pct:
                    stop = True
                    break
                code = str(item.get("f12", ""))
                if not code:
                    continue
                all_stocks.append({
                    "代码": code,
                    "名称": str(item.get("f14", "")),
                    "涨跌幅": float(chg),
                    "最新价": _safe_float(item.get("f2")),
                    "成交额": _safe_float(item.get("f6")),
                    "流通市值": _safe_float(item.get("f21")),
                    "总市值": _safe_float(item.get("f20")),
                    "换手率": _safe_float(item.get("f8")),
                    "所属行业": str(item.get("f100", "") or ""),
                })

            if stop:
                break
            if page < max_pages:
                time.sleep(0.2)
        except Exception as e:
            print(f"  push2delay第{page}页: 失败 ({e})")
            break

    return all_stocks


def _fetch_board_push2delay(fs: str, top_n: int = 30) -> list[dict]:
    """Fetch board/sector data from push2delay when akshare is blocked."""
    import requests
    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": str(top_n), "po": "1",
        "np": "1", "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": "2", "invt": "2", "fid0": "f62",
        "fs": fs, "stat": "1",
        "fields": "f12,f14,f2,f3,f62,f184,f66,f69,f124",
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()
    items = data.get("data", {}).get("diff", [])
    results = []
    for item in items:
        net_flow = _safe_float(item.get("f62"))
        results.append({
            "名称": str(item.get("f14", "")),
            "涨跌幅": _safe_float(item.get("f3")),
            "主力净流入": net_flow,
            "主力净占比": _safe_float(item.get("f184")),
            "领涨股": "",
        })
    results.sort(key=lambda x: x["主力净流入"], reverse=True)
    return results


def fetch_all(date_str: str) -> dict:
    """Concurrent data fetch — 6 API calls in parallel (~3s vs ~15s serial)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import akshare as ak
    import time as _t

    result = {
        "date": date_str,
        "fetch_time": datetime.now().strftime("%H:%M:%S"),
        "zt_pool": [],
        "strong_movers": [],
        "lhb": [],
        "sector_flow": [],
        "concept_flow": [],
        "northbound": {},
        "errors": [],
    }

    t0 = _t.time()

    def _task_zt():
        df = ak.stock_zt_pool_em(date=date_str)
        rows = []
        for _, r in df.iterrows():
            rows.append({
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
        return "zt", rows

    def _task_strong():
        return "strong", fetch_strong_movers(min_change_pct=5.0)

    def _task_lhb():
        df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)
        rows = []
        for _, r in df.iterrows():
            rows.append({
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
        return "lhb", rows

    def _task_sector():
        # push2delay first (VPN-safe, 0.2s), akshare fallback
        try:
            rows = _fetch_board_push2delay("m:90+t:2", top_n=30)
            if rows:
                return "sector", rows
        except Exception:
            pass
        try:
            df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
            rows = []
            for _, r in df.iterrows():
                rows.append({
                    "名称": str(r.get("名称", "")),
                    "涨跌幅": float(r.get("今日涨跌幅", 0)),
                    "主力净流入": float(r.get("今日主力净流入-净额", 0)),
                    "主力净占比": float(r.get("今日主力净流入-净占比", 0)),
                    "领涨股": str(r.get("今日主力净流入最大股", "")),
                })
            rows.sort(key=lambda x: x["主力净流入"], reverse=True)
            return "sector", rows
        except Exception:
            return "sector", []

    def _task_concept():
        # push2delay first (VPN-safe, 0.2s), akshare fallback
        try:
            rows = _fetch_board_push2delay("m:90+t:3", top_n=20)
            if rows:
                return "concept", rows
        except Exception:
            pass
        try:
            df = ak.stock_board_concept_name_em()
            df = df.sort_values("涨跌幅", ascending=False)
            rows = []
            for _, r in df.head(20).iterrows():
                rows.append({
                    "名称": str(r.get("板块名称", r.get("名称", ""))),
                    "涨跌幅": float(r.get("涨跌幅", 0)),
                    "领涨股": str(r.get("领涨股票", r.get("最新价", ""))),
                })
            return "concept", rows
        except Exception:
            return "concept", []

    def _task_north():
        df = ak.stock_hsgt_fund_flow_summary_em()
        north = df[df["资金方向"] == "北向"]
        total_net = north["成交净买额"].sum()
        return "north", {
            "净买额_亿": round(total_net, 2),
            "沪股通_上涨": int(north[north["板块"] == "沪股通"]["上涨数"].sum()),
            "沪股通_下跌": int(north[north["板块"] == "沪股通"]["下跌数"].sum()),
            "深股通_上涨": int(north[north["板块"] == "深股通"]["上涨数"].sum()),
            "深股通_下跌": int(north[north["板块"] == "深股通"]["下跌数"].sum()),
        }

    tasks = [_task_zt, _task_strong, _task_lhb, _task_sector, _task_concept, _task_north]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fn): fn.__name__ for fn in tasks}
        for f in as_completed(futures):
            name = futures[f]
            try:
                key, data = f.result()
                if key == "zt":
                    result["zt_pool"] = data
                    print(f"  涨停板池: {len(data)}只")
                elif key == "strong":
                    result["_strong_raw"] = data
                elif key == "lhb":
                    result["lhb"] = data
                    print(f"  龙虎榜: {len(data)}条")
                elif key == "sector":
                    result["sector_flow"] = data
                    print(f"  板块资金: {len(data)}个行业")
                elif key == "concept":
                    result["concept_flow"] = data
                    print(f"  概念板块: TOP{len(data)}已获取")
                elif key == "north":
                    result["northbound"] = data
                    print(f"  北向资金: 净买{data.get('净买额_亿', '?')}亿")
            except Exception as e:
                result["errors"].append(f"{name}: {e}")
                print(f"  {name}: 失败 ({e})")

    # Post-process: filter strong movers to exclude limit-up stocks
    raw_strong = result.pop("_strong_raw", [])
    zt_codes = {s["代码"] for s in result["zt_pool"]}
    result["strong_movers"] = [s for s in raw_strong if s["代码"] not in zt_codes]
    print(f"  强势非涨停: {len(result['strong_movers'])}只 (涨幅>5%, 排除已涨停)")

    elapsed = _t.time() - t0
    print(f"  数据拉取: {elapsed:.1f}s (6路并发)")

    return result


# ── Track B 自动评分 ─────────────────────────────────────────────────────────

# ── D6 筹码体检（历史维度）— 过去N天涨了多少？量价结构健不健康？───────────

D6_FLAGS = {
    # ── 20日维度 (涨幅+量价) ──
    "EXTREME_RUN":    "⛔ 20日涨幅>60%，翻倍行情末段",
    "HEAVY_RUN":      "⚠️ 20日涨幅>40%，获利盘沉重",
    "VOLUME_CLIMAX":  "⛔ 近5日出现过最大量日+放量>均量2x，冲顶放量",
    "VOL_SHRINK":     "⚠️ 今日成交量<近5日均量50%，买盘衰竭",
    "VOL_PRICE_DIV":  "⚠️ 近5日价格新高但成交量递减30%+，量价背离",
    "PROFIT_TRAPPED": "⚠️ 20日均价远低于现价(>25%)，获利盘悬顶",
    # ── 20日维度: 技术面 ──
    "MA_OVEREXTEND":  "⛔ 价格远超MA20(>25%)，严重偏离均线",
    "MA_BEARISH":     "⚠️ MA5<MA10<MA20空头排列，趋势向下",
    "MACD_TOP_DIV":   "⛔ 价格新高但MACD柱缩短，顶背离",
    "RSI_EXTREME":    "⚠️ RSI(14)>85，极度超买",
    "STAGNANT_VOL":   "⛔ 高位放量(>2x)但涨幅<2%，放量滞涨=出货",
    "HIGH_SHADOW":    "⚠️ 近3日高位长上影线(>实体2x)，上方抛压重",
    # ── 60日维度 (3个月) ──
    "60D_EXTREME_RUN":"⛔ 3月涨幅>80%，中期严重过热",
    "60D_HEAVY_RUN":  "⚠️ 3月涨幅>50%，中期涨幅偏高",
    "60D_TOP_RANGE":  "⚠️ 处于60日高低区间顶部(>90%)",
    "MA60_OVEREXTEND":"⛔ 价格远超MA60(>30%)，中期严重偏离",
    # ── 250日维度 (1年) ──
    "250D_TOP_RANGE":  "⚠️ 处于年线高低区间顶部(>95%)",
    "MA250_OVEREXTEND":"⛔ 价格远超MA250(>40%)，年线严重偏离",
    "MA250_DEEP_BELOW":"⚠️ 价格深度跌破MA250(>20%)，长期弱势",
    "52W_HIGH_BREAKOUT":"ℹ️ 接近或突破52周高点(距高点<2%)",
    "52W_DEEP_DRAWDOWN":"ℹ️ 距52周高点回撤>40%，深度调整",
    # ── 健康 ──
    "HEALTHY":        "✓ 全时间框架筹码+技术面健康",
}


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


def _calc_ema(data, period: int):
    """Exponential moving average."""
    import numpy as np
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


def chip_health_check(code: str, current_price: float = 0, use_cache: bool = False, days: int = 270) -> dict:
    """Pull up to `days`-day price history, return multi-frame chip+technical health.

    v2: 三时间框架 (20d/60d/250d) 筹码体检。向后兼容：30d_gain保留为20d_gain别名。
    """
    import numpy as np
    result = {
        "flags": [],
        "30d_gain": None, "20d_gain": None,
        "vol_ratio": None, "avg_cost_20d": None,
        "ma20_dev": None, "rsi14": None,
        "60d_gain": None, "60d_pos": None, "ma60_dev": None,
        "250d_gain": None, "250d_pos": None, "ma250_dev": None, "52w_high_dist": None,
        "composite_pos": None,
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

        valid = ~np.isnan(closes) & ~np.isnan(volumes) & ~np.isnan(highs) & ~np.isnan(lows) & ~np.isnan(opens)
        closes, volumes, highs, lows, opens = closes[valid], volumes[valid], highs[valid], lows[valid], opens[valid]
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

    except Exception:
        result["flags"].append("DATA_ERROR")

    return result


def _fetch_hist_cached(code: str, days: int = 270):
    """SQLite cache first, then full fallback chain."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from kline_cache import get_klines

    df = get_klines(code, days)
    if df is not None and len(df) >= 20:
        return df
    return _fetch_hist(code, days)


def batch_chip_health(scored: list[dict], top_n: int = 30) -> None:
    """Run chip health check on top N scored stocks, enrich in-place."""
    import concurrent.futures
    import time as _t
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
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
        futures = {pool.submit(chip_health_check, code, 0, True, 270): code for code in codes}
        for f in concurrent.futures.as_completed(futures):
            code = futures[f]
            try:
                results[code] = f.result()
            except Exception:
                results[code] = {"flags": ["DATA_ERROR"], "30d_gain": None}

    for s in targets:
        chk = results.get(s["代码"], {})
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


def _score_d1(code: str, lhb_map: dict, change_pct: float = 0, is_limit_up: bool = False) -> tuple[str, int]:
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


def score_strong_movers(movers: list[dict], lhb_map: dict, zt_sectors: dict[str, list], sector_zt_counts: dict[str, int] = None, prior_streaks: dict = None) -> list[dict]:
    """Score non-limit-up strong movers (涨幅>5%) with adapted Track B."""
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
        d1, d1s = _score_d1(code, lhb_map, change_pct, is_limit_up=False)

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
            # sector has no zt today — still allow streak-based退潮/高潮 detection
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
        d5_label, d5s = classify_d5(code, s.get("总市值", 0))

        total = d1s + d2s + d3s + d4s + d5s
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
            "D5": d5_label, "D5分": d5s,
            "TB总分": total,
            "TB评级": grade,
            "涨停": False,
            "可操作性": "可买",
            "数据源": "push2delay",
        })

    return scored


def auto_score_trackb(data: dict) -> list[dict]:
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
        is_lu = change_pct >= 9.8 or (code.startswith("3") and change_pct >= 19.5) or (code.startswith("68") and change_pct >= 19.5)

        d1, d1s = _score_d1(code, lhb_map, change_pct, is_limit_up=is_lu)
        d2, d2s = auto_score_d2(s)
        d3 = s.get("_d3", "跟涨")
        d3s = s.get("_d3_score", D3_SCORES["跟涨"])
        sec = s.get("所属行业", "未知")
        _prior_stk, _prior_zt = _prior_info(sec)
        d4, d4s = auto_score_d4(s, sector_zt_count=sector_zt_counts.get(sec, 0),
                                 prior_streak=_prior_stk, prior_zt_count=_prior_zt)
        d5_label, d5s = classify_d5(code, s.get("总市值", 0))

        total = d1s + d2s + d3s + d4s + d5s
        grade = score_to_grade(total)

        is_limit_up = is_lu or ((code.startswith("8") or code.startswith("4")) and change_pct >= 29)

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
            "数据源": "涨停池",
        })

    # 合并强势非涨停股(push2delay)
    if strong_movers:
        scored_strong = score_strong_movers(strong_movers, lhb_map, sector_groups, sector_zt_counts, prior_streaks=prior_streaks)
        scored.extend(scored_strong)

    scored.sort(key=lambda x: x["TB总分"], reverse=True)
    return scored


# ── 一票否决过滤器 ───────────────────────────────────────────────────────────

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


# ── 产业链发散候选 ───────────────────────────────────────────────────────────

def find_supply_chain_candidates(scored: list[dict], sector_flow: list[dict]) -> list[dict]:
    hot_sectors = set()
    for s in scored:
        if s["TB评级"] in ("S", "A+", "A"):
            hot_sectors.add(s["行业"])

    # 板块资金流排名索引：名称 -> 排名(1-based)
    flow_rank: dict[str, int] = {sf["名称"]: i + 1 for i, sf in enumerate(sector_flow)}

    candidates = []
    for chain_name, related in SUPPLY_CHAIN_MAP.items():
        chain_hot = False
        signal_stocks = []
        non_zt_candidates = []
        for s in scored:
            in_chain = s["行业"] in related or any(r in s.get("行业", "") for r in related)
            if in_chain:
                chain_hot = True
                if s["TB评级"] in ("S", "A+", "A"):
                    signal_stocks.append(s)
                # 强势非涨停：涨幅>3% 且未涨停
                if not s.get("涨停") and s.get("涨跌幅", 0) > 3:
                    non_zt_candidates.append(s)

        if chain_hot and signal_stocks:
            # 非涨停候选按涨幅降序，取前3
            non_zt_candidates.sort(key=lambda x: x.get("涨跌幅", 0), reverse=True)
            top_non_zt = non_zt_candidates[:3]

            if top_non_zt:
                candidates_info = [
                    f"{s['代码']} {s['名称']}(+{s['涨跌幅']:.1f}%)" for s in top_non_zt
                ]
                diverge_hint = (
                    f"从{signal_stocks[0]['名称']}等涨停信号出发,同链强势未涨停候选: "
                    + " / ".join(candidates_info)
                )
            else:
                # 无候选时，补充板块资金流向排名
                flow_info_parts = []
                for r in related:
                    rank = flow_rank.get(r)
                    if rank:
                        flow_info_parts.append(f"{r}(资金流第{rank})")
                if flow_info_parts:
                    diverge_hint = (
                        f"从{signal_stocks[0]['名称']}等涨停信号出发,找同链未涨停的先手票"
                        f"(板块资金参考: {', '.join(flow_info_parts[:2])})"
                    )
                else:
                    diverge_hint = f"从{signal_stocks[0]['名称']}等涨停信号出发,找同链未涨停的先手票"

            candidates.append({
                "产业链": chain_name,
                "信号股": [{"代码": s["代码"], "名称": s["名称"], "TB评级": s["TB评级"], "涨停": s["涨停"]} for s in signal_stocks[:3]],
                "候选股": [{"代码": s["代码"], "名称": s["名称"], "涨跌幅": round(s.get("涨跌幅", 0), 2)} for s in top_non_zt],
                "关联板块": related,
                "建议发散方向": diverge_hint,
            })

    return candidates


# ── 输出 ─────────────────────────────────────────────────────────────────────

def print_summary(data: dict, scored: list[dict], chains: list[dict], top_n: int):
    zt_count = len(data["zt_pool"])
    lhb_count = len(data["lhb"])
    nb = data.get("northbound", {})

    strong_count = len(data.get("strong_movers", []))

    print()
    print(f"UASS 自动扫描 | {data['date']} | 涨停{zt_count}只 | 强势非涨停{strong_count}只 | 龙虎榜{lhb_count}条 | 北向净买{nb.get('净买额_亿', '?')}亿")

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

    # 热门行业统计(涨停板)
    sector_zt_count: dict[str, int] = {}
    for s in scored:
        if s.get("涨停"):
            sec = s["行业"]
            sector_zt_count[sec] = sector_zt_count.get(sec, 0) + 1
    hot_sectors = sorted(sector_zt_count.items(), key=lambda x: x[1], reverse=True)[:10]
    print()
    print("涨停集中行业 TOP10")
    for sec, cnt in hot_sectors:
        names = [s["名称"] for s in scored if s["行业"] == sec and s.get("涨停")][:3]
        print(f"  {sec}: {cnt}只涨停 ({', '.join(names)})")

    # 强势非涨停 TOP15 (push2delay全市场扫描, 修复创业板/科创板10-19%盲区)
    strong_scored = [s for s in scored if s.get("数据源") == "push2delay"]
    if strong_scored:
        print()
        print(f"★ 强势非涨停 TOP15 (全市场扫描, 覆盖创业板/科创板10-19%盲区)")
        print(f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10} {'涨幅':>6} {'市值亿':>6} {'TB分':>5} {'级':>3}")
        for i, s in enumerate(strong_scored[:15], 1):
            print(f"{i:>3} {s['代码']:<8} {s['名称']:<8} {s['行业']:<10} {s['涨跌幅']:>+5.2f}% {s['总市值_亿']:>5.0f} {s['TB总分']:>5} {s['TB评级']:>3}")

    # Track B 评分 TOP N (含D6筹码体检)
    print()
    print(f"Track B 自动评分 TOP{top_n} (含D6筹码体检)")
    print(f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10} {'市值亿':>6} {'TB分':>7} {'级':>3} {'D1':>2} {'D2':>2} {'D3':<4} {'D4':<6} {'20d%':>5} {'量比':>4} {'D6筹码'} {'veto':>5}")
    for i, s in enumerate(scored[:top_n], 1):
        g20 = s.get("D6_20d涨幅")
        g20_str = f"{g20:>+4.0f}%" if g20 is not None else "  N/A"
        vr = s.get("D6_量比")
        vr_str = f"{vr:>3.1f}x" if vr is not None else " N/A"
        flags = s.get("D6_flags", [])
        flag_str = ",".join(f for f in flags if f != "HEALTHY" and f != "DATA_ERROR")
        if not flag_str:
            flag_str = "✓" if "HEALTHY" in flags else "N/A"
        penalty = s.get("D6_penalty", 0)
        raw = s.get("TB总分_raw", s["TB总分"])
        score_str = f"{s['TB总分']:>4}" if penalty == 0 else f"{raw}→{s['TB总分']}"
        veto_str = "❌" if s.get("veto") else ""
        print(f"{i:>3} {s['代码']:<8} {s['名称']:<8} {s['行业']:<10} {s['总市值_亿']:>5.0f} {score_str:>7} {s['TB评级']:>3} {s['D1']:>2} {s['D2']:>2} {s['D3']:<4} {s['D4']:<6} {g20_str} {vr_str} {flag_str} {veto_str}")

    # 多时间框架D6位置 (只显示有异常的股票)
    _MULTI_FRAME_ALERT_FLAGS = {
        "EXTREME_RUN", "HEAVY_RUN", "60D_EXTREME_RUN", "60D_HEAVY_RUN",
        "60D_TOP_RANGE", "MA60_OVEREXTEND", "250D_TOP_RANGE",
        "MA250_OVEREXTEND", "52W_HIGH_BREAKOUT",
    }
    multi_frame_stocks = []
    for s in scored[:top_n]:
        flags = s.get("D6_flags", [])
        mf = [f for f in flags if f in _MULTI_FRAME_ALERT_FLAGS]
        if mf or s.get("veto"):
            multi_frame_stocks.append((s, mf))

    if multi_frame_stocks:
        print()
        print("多时间框架D6位置 (异常标记)")
        print(f"{'#':>3} {'代码':<8} {'名称':<8} {'20d%':>6} {'60d%':>6} {'250d%':>7} {'综合位':>6}  核心flags")
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
                flag_detail = f"VETO({veto_reasons})" + (f",{flag_detail}" if flag_detail else "")
            print(f"{i:>3} {s['代码']:<8} {s['名称']:<8} {g20_s} {g60_s} {g250_s} {comp_s}  {flag_detail}")

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
    veto_count = sum(1 for s in scored if s.get("veto"))
    _OVERHEAT_FLAGS = {"EXTREME_RUN", "HEAVY_RUN", "60D_EXTREME_RUN", "60D_HEAVY_RUN", "MA250_OVEREXTEND"}
    overheat_count = sum(1 for s in scored if any(f in s.get("D6_flags", []) for f in _OVERHEAT_FLAGS))
    print(f"评级分布: S={s_count} A+={a_plus} A={a_count} A-={a_minus} | 涨停{zt_count}只 | 强势非涨停{strong_count}只 | 合计{len(scored)}只")
    print(f"D6统计: 多时间框架过热{overheat_count}只 | veto{veto_count}只")
    if data["errors"]:
        print(f"数据源问题: {len(data['errors'])}个 (详见JSON)")


# ── D8 主线持续天数追踪 ─────────────────────────────────────────────────────

def load_mainline_history() -> dict:
    """Load historical sector limit-up data (past 20 trading days)."""
    if MAINLINE_HISTORY.exists():
        with open(MAINLINE_HISTORY) as f:
            return json.load(f)
    return {"days": []}


def save_mainline_history(history: dict):
    """Persist mainline history, keep last 20 days."""
    history["days"] = history["days"][-20:]
    MAINLINE_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(MAINLINE_HISTORY, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def compute_mainline_streaks(history: dict, today_sectors: dict) -> dict[str, dict]:
    """
    Given sector data for today and historical days, compute hot streak
    (consecutive days with ≥2 limit-ups) and auto-stage.

    today_sectors values may be:
      - int: legacy format (just zt_count)
      - dict: new format with keys zt_count, avg_gain, leader, leader_gain

    Stage logic:
      Day 1: 启动
      Day 2-3: 主升早
      Day 4-5: 主升中
      Day 6+: 高潮/退潮风险

    Trend logic (today vs yesterday, for sectors with ≥2 days of history):
      今日涨停数 > 昨日 → "加速"
      今日涨停数 == 昨日 → "持平"
      今日涨停数 < 昨日 → "减速" (退潮信号)
    """
    def _get_zt_count(val) -> int:
        """Extract zt_count whether val is int or new-format dict."""
        if isinstance(val, dict):
            return val.get("zt_count", 0)
        return int(val) if val else 0

    results = {}
    past_days = history.get("days", [])

    for sector, today_val in today_sectors.items():
        today_count = _get_zt_count(today_val)
        if today_count < 2:
            continue

        streak = 1
        for day in reversed(past_days):
            day_sectors = day.get("sectors", {})
            past_val = day_sectors.get(sector, 0)
            if _get_zt_count(past_val) >= 2:
                streak += 1
            else:
                break

        if streak == 1:
            stage = "启动(首日)"
        elif streak <= 3:
            stage = "主升早"
        elif streak <= 5:
            stage = "主升中"
        else:
            stage = "高潮/退潮风险"

        # Trend: compare today vs yesterday
        trend = "持平"
        if past_days:
            yesterday_val = past_days[-1].get("sectors", {}).get(sector, 0)
            yesterday_count = _get_zt_count(yesterday_val)
            if today_count > yesterday_count:
                trend = "加速"
            elif today_count < yesterday_count:
                trend = "减速"

        results[sector] = {
            "streak_days": streak,
            "today_count": today_count,
            "stage_auto": stage,
            "trend": trend,
        }
    return results


def update_mainline_history(history: dict, date_str: str, scored: list) -> dict[str, dict]:
    """
    Count limit-ups per sector for today, enrich with avg_gain and leader info,
    append to history, compute streaks. Returns streak info per sector.

    Stored sector format (new):
      {"光通信": {"zt_count": 5, "avg_gain": 8.3, "leader": "002281", "leader_gain": 12.5}}
    """
    # Collect per-sector data from limit-up stocks
    sector_data: dict[str, dict] = {}
    for s in scored:
        if not s.get("涨停"):
            continue
        sec = s["行业"]
        if sec not in sector_data:
            sector_data[sec] = {"zt_count": 0, "gains": [], "leader": "", "leader_gain": -999.0}
        sector_data[sec]["zt_count"] += 1
        chg = s.get("涨跌幅", 0.0)
        sector_data[sec]["gains"].append(chg)
        if chg > sector_data[sec]["leader_gain"]:
            sector_data[sec]["leader_gain"] = chg
            sector_data[sec]["leader"] = s.get("代码", "")

    # Build final sector dict with avg_gain, drop internal gains list
    sector_counts: dict[str, dict] = {}
    for sec, info in sector_data.items():
        gains = info["gains"]
        avg_gain = round(sum(gains) / len(gains), 1) if gains else 0.0
        sector_counts[sec] = {
            "zt_count": info["zt_count"],
            "avg_gain": avg_gain,
            "leader": info["leader"],
            "leader_gain": round(info["leader_gain"], 1) if info["leader_gain"] != -999.0 else 0.0,
        }

    if not history["days"] or history["days"][-1].get("date") != date_str:
        history["days"].append({"date": date_str, "sectors": sector_counts})
    else:
        history["days"][-1]["sectors"] = sector_counts

    streaks = compute_mainline_streaks(history, sector_counts)
    save_mainline_history(history)
    return streaks


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

    print(f"UASS扫描启动 | 日期: {date_str}")
    print("-" * 40)

    data = fetch_all(date_str)

    # ── 先加载D8历史, 算prior_streaks, 注入data让D4可以感知退潮 ──
    history_pre = load_mainline_history()
    if history_pre.get("days"):
        # 用history中最后一天(即昨天)的数据算prior streak
        last_day = history_pre["days"][-1]
        prior_sector_counts = last_day.get("sectors", {})
        prior_streaks_data = compute_mainline_streaks(history_pre, prior_sector_counts)
        # today_count字段此时存的是昨天的数量, 用于退潮对比
        data["prior_streaks"] = prior_streaks_data
    else:
        data["prior_streaks"] = {}

    scored = auto_score_trackb(data)

    # D6 筹码体检: 拉历史行情, 检查涨幅/量价/筹码结构 (全量覆盖)
    d6_top = len(scored)
    print(f"D6 筹码体检中 (全部{d6_top}只历史行情)...")
    batch_chip_health(scored, top_n=d6_top)
    scored.sort(key=lambda x: x["TB总分"], reverse=True)
    scored = apply_veto_filter(scored)
    veto_count = sum(1 for s in scored if s.get("veto"))
    if veto_count:
        veto_stocks = [s for s in scored if s.get("veto")]
        veto_names = ", ".join(s["名称"] for s in veto_stocks[:5])
        suffix = "..." if veto_count > 5 else ""
        print(f"一票否决: {veto_count}只 ({veto_names}{suffix})")
    print(f"D6 完成 | 标记: " + ", ".join(
        f"{s['名称']}({','.join(s.get('D6_flags',[]))})"
        for s in scored[:30] if s.get('D6_flags') and 'HEALTHY' not in s.get('D6_flags',[])
    ) or "全部健康")

    chains = find_supply_chain_candidates(scored, data["sector_flow"])

    # ── D8 主线持续天数 ──────────────────────────────────────────────────
    history = load_mainline_history()
    streaks = update_mainline_history(history, date_str, scored)
    if streaks:
        print()
        print("D8 主线持续天数 (≥2只涨停的行业)")
        for sec, info in sorted(streaks.items(), key=lambda x: -x[1]["streak_days"]):
            trend_str = info.get('trend', '')
        trend_icon = {"加速": "🔥", "减速": "⚠️", "持平": "→"}.get(trend_str, "")
        print(f"  {sec}: 连续{info['streak_days']}天热门 | 今日{info['today_count']}只涨停 | 阶段={info['stage_auto']} | {trend_icon}{trend_str}")

    # ── D7 缓涨检测 ──────────────────────────────────────────────────────
    print("D7 缓涨检测中 (7日滚动宇宙+板块关联)...")
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trend_detector import run_d7_scan, print_d7_report

    # Build all_active_codes: zt_pool + strong_movers with >3% gains
    all_active = []
    for s in data["zt_pool"]:
        all_active.append({"代码": s["代码"], "名称": s["名称"], "行业": s.get("所属行业", "")})
    for s in data.get("strong_movers", []):
        if s.get("涨跌幅", 0) >= 3.0:
            all_active.append({"代码": s["代码"], "名称": s["名称"], "行业": s.get("所属行业", "")})

    d7_result = run_d7_scan(scored, data["sector_flow"], date_str, all_active_codes=all_active)
    d7_trend_count = len(d7_result.get("trend_alerts", []))
    d7_sector_count = len(d7_result.get("sector_alerts", []))
    print(f"D7 完成 | 缓涨预警{d7_trend_count}只 | 板块关联{d7_sector_count}条")

    output = {
        "scan_date": date_str,
        "scan_time": datetime.now().isoformat(),
        "market_summary": {
            "涨停数": len(data["zt_pool"]),
            "强势非涨停数": len(data.get("strong_movers", [])),
            "龙虎榜数": len(data["lhb"]),
            "北向净买_亿": data.get("northbound", {}).get("净买额_亿", None),
        },
        "sector_flow_top10": data["sector_flow"][:10],
        "concept_flow_top10": data.get("concept_flow", [])[:10],
        "trackb_scored": scored,
        "supply_chain_candidates": chains,
        "d7_trend_alerts": d7_result.get("trend_alerts", []),
        "d7_sector_alerts": d7_result.get("sector_alerts", []),
        "d8_mainline_streaks": streaks,
        "errors": data["errors"],
    }

    with open(SCAN_OUTPUT, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print_summary(data, scored, chains, args.top)
        print_d7_report(d7_result)
        print()
        print(f"完整数据已存: {SCAN_OUTPUT}")


if __name__ == "__main__":
    main()
