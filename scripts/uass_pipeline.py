#!/usr/bin/env python3
"""UASS v6.0 — 数据管道: 并发拉取 + 产业链发散 + Signal A入口"""

from __future__ import annotations
import os as _np_os  # ⛔代理劫持eastmoney防护(07-23 M5迁移):设NO_PROXY绕代理直连东财
_np_os.environ.setdefault('NO_PROXY', '*')
_np_os.environ.setdefault('no_proxy', '*')
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

from uass_types import SUPPLY_CHAIN_MAP, safe_float

warnings.filterwarnings("ignore")


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _retry(fn, retries=2, delay=1):
    import time
    for i in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            if i == retries:
                raise e
            time.sleep(delay)


# ── 数据拉取 ─────────────────────────────────────────────────────────────────

def fetch_strong_movers(min_change_pct: float = 5.0, max_pages: int = 8) -> list[dict]:
    """
    全市场强势股扫描 via push2delay.eastmoney.com HTTPS.
    VPN下依然可用(HTTPS域名解析不受Shadowrocket TUN劫持).
    按涨跌幅降序翻页, 遇到<min_change_pct停止.
    增强: 增加 f10 (量比/vol_ratio) 字段.
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
            "fields": "f2,f3,f6,f8,f10,f12,f14,f20,f21,f100",
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
                    "最新价": safe_float(item.get("f2")),
                    "成交额": safe_float(item.get("f6")),
                    "流通市值": safe_float(item.get("f21")),
                    "总市值": safe_float(item.get("f20")),
                    "换手率": safe_float(item.get("f8")),
                    "vol_ratio": safe_float(item.get("f10")),
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
        net_flow = safe_float(item.get("f62"))
        results.append({
            "名称": str(item.get("f14", "")),
            "涨跌幅": safe_float(item.get("f3")),
            "主力净流入": net_flow,
            "主力净占比": safe_float(item.get("f184")),
            "领涨股": "",
        })
    results.sort(key=lambda x: x["主力净流入"], reverse=True)
    return results


def fetch_all(date_str: str) -> dict:
    """Concurrent data fetch — 6 API calls in parallel (~3s vs ~15s serial)."""
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


# ── 产业链发散候选 ───────────────────────────────────────────────────────────

def find_supply_chain_candidates(scored: list[dict], sector_flow: list[dict]) -> list[dict]:
    """B→A发散: 从涨停信号股出发，找同产业链未涨停的先手票。

    增强: 当产业链有信号股但无非涨停候选时(全部涨停)，
    扩大搜索范围至相关行业名称模糊匹配、涨幅>3%的股票。
    """
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

            # 增强: 无候选时(全部涨停)，扩大到相关行业模糊匹配
            if not top_non_zt:
                # 提取 related 中的关键词片段用于模糊匹配
                related_keywords = set()
                for r in related:
                    # 拆分复合词，取有意义的片段（≥2字）
                    for keyword in [r] + [r[:len(r)//2], r[len(r)//2:]]:
                        if len(keyword) >= 2:
                            related_keywords.add(keyword)

                broadened = []
                for s in scored:
                    if s.get("涨停"):
                        continue
                    if s.get("涨跌幅", 0) <= 3:
                        continue
                    # 已经在精确匹配中检查过的跳过
                    in_chain_exact = s["行业"] in related or any(r in s.get("行业", "") for r in related)
                    if in_chain_exact:
                        continue
                    # 模糊匹配：行业名称包含任意关键词
                    stock_industry = s.get("行业", "")
                    if any(kw in stock_industry for kw in related_keywords):
                        broadened.append(s)

                broadened.sort(key=lambda x: x.get("涨跌幅", 0), reverse=True)
                top_non_zt = broadened[:3]

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


# ── Signal A: 基本面催化剂直接入场 ───────────────────────────────────────────

def signal_a_entry(tickers: list[str], fetch_date: str | None = None) -> list[dict]:
    """Signal A: 基本面催化剂驱动的直接入场。

    跳过Layer 1全量扫描，直接获取指定标的数据供Layer 2+评分。
    用于Claude识别出的基本面催化剂标的。
    """
    import requests

    if not tickers:
        return []

    results = []
    # Use push2delay to get current data for each ticker
    # Build the code list for batch fetch
    code_list = ",".join(f"1.{t}" if t.startswith("6") else f"0.{t}" for t in tickers)
    url = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2", "invt": "2",
        "fields": "f2,f3,f6,f8,f10,f12,f14,f20,f21,f100",
        "secids": code_list,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        items = data.get("data", {}).get("diff", [])
        for item in items:
            code = str(item.get("f12", ""))
            if not code:
                continue
            results.append({
                "代码": code,
                "名称": str(item.get("f14", "")),
                "涨跌幅": safe_float(item.get("f3")),
                "最新价": safe_float(item.get("f2")),
                "成交额": safe_float(item.get("f6")),
                "流通市值": safe_float(item.get("f21")),
                "总市值": safe_float(item.get("f20")),
                "换手率": safe_float(item.get("f8")),
                "vol_ratio": safe_float(item.get("f10")),
                "所属行业": str(item.get("f100", "") or ""),
                "signal_a": True,
            })
    except Exception as e:
        print(f"  Signal A fetch failed: {e}")

    return results
