#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.14", "pandas>=2.0", "requests>=2.31", "baostock>=0.8"]
# ///
"""
mainline_scan.py — A股主线识别引擎（重建任务C1，2026-08-14）

把"顺势而为"的势的四层框架中第3层(主线板块)+第4层(个股趋势进场判据)落地成可执行代码。
诊断7的判据原文见文件头注释末尾，脚本严格对应实现，不擅自加新判据。

⛔ 数据源纪律（宪法D12 + 本文件新增发现）:
  - A股行情/涨停/资金流全部走 eastmoney push2delay（VPN代理不劫持），
    禁止用 yfinance，禁止裸调 akshare 的 push2.eastmoney/push2his 接口
    （本次实测：push2.eastmoney.com 在本机环境下对
      stock_sector_fund_flow_rank(今日/5日) 和 stock_sector_fund_flow_hist
      两个akshare封装函数持续 ConnectionError/RemoteDisconnected，
      push2delay.eastmoney.com 用完全相同的字段结构可稳定拿到数据 → 本文件
      自建 fetch_sector_money_flow() 绕开这两个坏掉的akshare封装，不是重复造轮子）。
  - ak.stock_zt_pool_em / stock_zt_pool_previous_em / stock_zt_pool_zbgc_em
    这三个是date-parameterized的官方接口，历史/当日都稳定，直接用。
  - ⛔ 板块资金流(push2delay clist)只有"当前快照"，没有历史查询能力
    （push2his.eastmoney.com在本机环境同样连不上，且akshare官方hist封装
    也依赖push2.eastmoney先拿板块代码表，同样连不上）。
    → 回测历史日期时，条件②(板块资金流居前排)诚实返回 not_available，
      不伪造历史资金流数字。这是宪法第1条"没有就说没有"的直接体现。

═══════════════════════════════════════════════════════════════════════════
诊断7判据原文(本脚本的实现依据，不是脚本自己发明的规则):

【进场四条件】(涨跌幅本身被物理删除出判断链):
  ① 龙头20日均线未破
  ② 板块资金流3日以上仍居前排
  ③ 距最近25日高≤8%（防接最后一棒，不是防涨得多）
  ④ 基本面轴独立过关

【主线识别方法排名】(预测力 / 难度):
  1. 连板高度+晋级率                  高预测力 / 低难度
  2. 板块资金连续N日居前              高预测力 / 低难度
  3. 龙头股高度                       高预测力 / 中难度
  4. 产业链轮动扩散节奏                高预测力 / 中高难度
     实证: 05-22 PCB龙头全涨停 → 05-26 上游覆铜板/封装精确跟涨，1-3日时差
  5. 龙虎榜                           中预测力 —— 是"确认"不是"发现"

【生命周期四阶段】:
  启动期        — 硬催化 + 龙头先动 + 多股涨停
  主升发酵中段  — 最该重仓、也正是系统性拒绝的阶段
  高潮期        — 涨停>50家 + 最弱票补涨 + 利好钝化
  退潮期        — （本脚本用 炸板率↑/晋级率↓/连续天数减速 三线共振判定）

⛔ 北向资金2024-08-19起停止逐日披露，本脚本不使用北向数据（同astock_regime.py信号3处理）。
═══════════════════════════════════════════════════════════════════════════

用法:
  uv run --script scripts/mainline_scan.py                              # 今日实跑
  uv run --script scripts/mainline_scan.py --date 20260731              # 回测某历史交易日
  uv run --script scripts/mainline_scan.py --top 10                     # 显示前10主线
  uv run --script scripts/mainline_scan.py --trees "AI算力,半导体设备"   # 指定产业链做扩散分析(不指定则自动探测)
  uv run --script scripts/mainline_scan.py --check 600487,603186,688627 # 四条件进场检查(逗号分隔代码)
  uv run --script scripts/mainline_scan.py --json                       # 额外打印完整JSON
"""

from __future__ import annotations

# ⛔ 必须在 import requests/akshare 之前设，绕过代理软件对eastmoney的劫持(同astock_data_layer.py)
import os as _os
_os.environ.setdefault("NO_PROXY", "*")
_os.environ.setdefault("no_proxy", "*")

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import akshare as ak
import requests

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
PRODUCT_TREE_MAP_PATH = DATA_DIR / "product_tree_map.json"
CACHE_DIR = DATA_DIR / "mainline_scan_cache"
SNAPSHOT_DIR = DATA_DIR / "mainline_scan"
FLOW_RANK_HISTORY_PATH = DATA_DIR / "mainline_flow_rank_history.json"

TZ_BJ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ_BJ)
TODAY_STR = NOW.strftime("%Y%m%d")


# ─────────────────────────────────────────────────────────────────────────
# §0 通用小工具
# ─────────────────────────────────────────────────────────────────────────

def safe_float(v, default=None):
    try:
        f = float(v)
        return f if f == f else default  # NaN check
    except (TypeError, ValueError):
        return None if default is None else default


def safe_str(v):
    return "" if v is None else str(v)


def clean_name(v):
    """东财原始数据里部分3字股票名会被空格填充成'金 螳 螂'这种展示宽度对齐格式(源数据现象，非本脚本产生)。
    中文公司名不含空格，统一去空格不算篡改数据，只是清理源头的展示级padding。"""
    return safe_str(v).replace(" ", "").replace("　", "")


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


# ─────────────────────────────────────────────────────────────────────────
# §1 交易日历
# ─────────────────────────────────────────────────────────────────────────

_TRADE_DATES_CACHE: list[str] | None = None


def get_trading_dates() -> list[str]:
    """全量交易日列表(YYYYMMDD, 升序)，本进程内只拉一次。"""
    global _TRADE_DATES_CACHE
    if _TRADE_DATES_CACHE is not None:
        return _TRADE_DATES_CACHE
    df = ak.tool_trade_date_hist_sina()
    dates = sorted(df["trade_date"].astype(str).str.replace("-", "").tolist())
    _TRADE_DATES_CACHE = dates
    return dates


def trading_days_ending_at(date_str: str, n: int) -> list[str]:
    """返回以 date_str 结尾(含)的最近 n 个交易日(升序)。date_str 非交易日时回退到其前最近交易日。"""
    dates = get_trading_dates()
    le = [d for d in dates if d <= date_str]
    if not le:
        raise ValueError(f"找不到 {date_str} 及之前的任何交易日")
    anchor_idx = dates.index(le[-1])
    start = max(0, anchor_idx - n + 1)
    return dates[start:anchor_idx + 1]


def is_settled_date(date_str: str) -> bool:
    """是否是"已收盘定型"的历史交易日(可以磁盘缓存)。今天(未必收盘)不缓存。"""
    return date_str < TODAY_STR


# ─────────────────────────────────────────────────────────────────────────
# §2 涨停池 / 昨日涨停今日表现 / 炸板池 — date-parameterized官方接口
# ─────────────────────────────────────────────────────────────────────────

def _cache_path(kind: str, date_str: str) -> Path:
    return CACHE_DIR / f"{kind}_{date_str}.json"


def _load_or_fetch(kind: str, date_str: str, fetch_fn) -> list[dict]:
    if is_settled_date(date_str):
        p = _cache_path(kind, date_str)
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
    data = fetch_fn(date_str)
    if is_settled_date(date_str):
        atomic_write_json(_cache_path(kind, date_str), data)
    return data


def fetch_zt_pool(date_str: str) -> list[dict]:
    """当日涨停池: 代码/名称/涨跌幅/连板数/炸板次数/涨停统计/所属行业等。"""
    def _fetch(d):
        df = ak.stock_zt_pool_em(date=d)
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "代码": safe_str(r.get("代码")),
                "名称": clean_name(r.get("名称")),
                "涨跌幅": safe_float(r.get("涨跌幅"), 0.0),
                "最新价": safe_float(r.get("最新价")),
                "成交额": safe_float(r.get("成交额"), 0.0),
                "换手率": safe_float(r.get("换手率"), 0.0),
                "封板资金": safe_float(r.get("封板资金"), 0.0),
                "首次封板时间": safe_str(r.get("首次封板时间")),
                "炸板次数": int(safe_float(r.get("炸板次数"), 0)),
                "涨停统计": safe_str(r.get("涨停统计")),
                "连板数": int(safe_float(r.get("连板数"), 1)),
                "所属行业": safe_str(r.get("所属行业")),
            })
        return rows
    return _load_or_fetch("zt", date_str, _fetch)


def fetch_zt_previous(date_str: str) -> list[dict]:
    """昨日涨停股今日表现: 用于计算晋级率。"""
    def _fetch(d):
        df = ak.stock_zt_pool_previous_em(date=d)
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "代码": safe_str(r.get("代码")),
                "名称": clean_name(r.get("名称")),
                "涨跌幅": safe_float(r.get("涨跌幅"), 0.0),
                "最新价": safe_float(r.get("最新价")),
                "涨停价": safe_float(r.get("涨停价")),
                "昨日连板数": int(safe_float(r.get("昨日连板数"), 1)),
                "所属行业": safe_str(r.get("所属行业")),
            })
        return rows
    return _load_or_fetch("zt_prev", date_str, _fetch)


def fetch_zbgc(date_str: str) -> list[dict]:
    """炸板池(今日封过板但未能守住/未封住的股票): 用于计算炸板率。"""
    def _fetch(d):
        df = ak.stock_zt_pool_zbgc_em(date=d)
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "代码": safe_str(r.get("代码")),
                "名称": clean_name(r.get("名称")),
                "涨跌幅": safe_float(r.get("涨跌幅"), 0.0),
                "炸板次数": int(safe_float(r.get("炸板次数"), 0)),
                "所属行业": safe_str(r.get("所属行业")),
            })
        return rows
    return _load_or_fetch("zbgc", date_str, _fetch)


def fetch_zt_pool_multiday(trading_days: list[str]) -> dict[str, list[dict]]:
    """
    多日涨停池，用于计算板块连续天数(streak)。单日调用一次akshare，磁盘缓存历史日。

    ⛔ 实测发现的数据源硬限制(2026-08-14): ak.stock_zt_pool_em(date=...) 只服务"当前运行时刻"
    往前约14-15个交易日的滚动窗口，更早的日期(哪怕是真实交易日)一律返回空表——不是那天真的0涨停，
    是东财这个数据中心接口本身不存(可能对应网页版"最近N日"的UI限制)。
    → 对超出窗口的日期，本函数检测"合法交易日但返回空"并打印警告，不静默当成"真实0涨停"喂给streak计算，
      避免streak被系统性低估(诚实体现，不是逻辑漏洞：streak只会偏保守，不会凭空产生假信号)。
    """
    out = {}
    trading_dates_set = set(get_trading_dates())
    for d in trading_days:
        rows = fetch_zt_pool(d)
        if not rows and d in trading_dates_set:
            print(f"  ⚠️ [数据窗口限制] {d}是合法交易日但stock_zt_pool_em返回空——超出东财该接口的"
                  f"回溯窗口(实测约14-15个交易日)，非真实0涨停。该日streak计算按0处理(偏保守，不影响"
                  f"结论方向，只可能低估连续天数)。", file=sys.stderr)
        out[d] = rows
        if not is_settled_date(d):
            continue
        time.sleep(0.15)  # 轻微限速，避免连续多请求触发东财风控
    return out


def fetch_lhb(date_str: str) -> list[dict]:
    """龙虎榜(确认层，权重最低)。"""
    def _fetch(d):
        try:
            df = ak.stock_lhb_detail_em(start_date=d, end_date=d)
        except Exception as e:
            print(f"  [警告] 龙虎榜获取失败({d}): {e}", file=sys.stderr)
            return []
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "代码": safe_str(r.get("代码")),
                "名称": clean_name(r.get("名称")),
                "涨跌幅": safe_float(r.get("涨跌幅"), 0.0),
                "龙虎榜净买额": safe_float(r.get("龙虎榜净买额"), 0.0),
            })
        return rows
    return _load_or_fetch("lhb", date_str, _fetch)


# ─────────────────────────────────────────────────────────────────────────
# §3 板块资金流 — 自建push2delay直连(绕开akshare封装在本机环境下坏掉的push2.eastmoney)
#     ⛔ 只有"当前快照"，无历史查询能力 —— 只在 date_str == 今天 时调用
# ─────────────────────────────────────────────────────────────────────────

_FLOW_WINDOW_FIELDS = {
    "今日": {"pct": "f3", "net": "f62", "net_pct": "f184", "stat": "1"},
    "5日": {"pct": "f109", "net": "f164", "net_pct": "f165", "stat": "5"},
    "10日": {"pct": "f160", "net": "f174", "net_pct": "f175", "stat": "10"},
}

_PUSH2DELAY_CLIST = "https://push2delay.eastmoney.com/api/qt/clist/get"
_EM_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def fetch_sector_money_flow(window: str = "今日", sector_type: str = "行业资金流",
                              max_pages: int = 6, page_size: int = 100) -> list[dict]:
    """
    板块(细分行业, ~496个)资金流排名快照 — push2delay clist直连。
    仅代表"调用时刻"的数据，没有date参数，不可用于历史回测。
    返回: [{"名称","代码"(BK code),"涨跌幅","净流入","净占比","排名","领涨股"}], 按净流入降序。
    """
    if window not in _FLOW_WINDOW_FIELDS:
        raise ValueError(f"window必须是{list(_FLOW_WINDOW_FIELDS)}之一")
    spec = _FLOW_WINDOW_FIELDS[window]
    sector_type_map = {"行业资金流": "2", "概念资金流": "3", "地域资金流": "1"}
    fields = f"f12,f14,{spec['pct']},{spec['net']},{spec['net_pct']}"

    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        params = {
            "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
            "fltt": "2", "invt": "2",
            "fid0": spec["net"],
            "fs": f"m:90 t:{sector_type_map[sector_type]}",
            "stat": spec["stat"],
            "fields": fields,
        }
        try:
            r = requests.get(_PUSH2DELAY_CLIST, params=params, headers=_EM_UA, timeout=15)
            d = r.json()
            diff = (d.get("data") or {}).get("diff") or []
        except Exception as e:
            print(f"  [警告] 板块资金流({window})第{page}页失败: {e}", file=sys.stderr)
            break
        if not diff:
            break
        for item in diff:
            rows.append({
                "名称": safe_str(item.get("f14")),
                "代码": safe_str(item.get("f12")),
                "涨跌幅": safe_float(item.get(spec["pct"])),
                "净流入": safe_float(item.get(spec["net"])),
                "净占比": safe_float(item.get(spec["net_pct"])),
            })
        if len(diff) < page_size:
            break
        time.sleep(0.15)

    rows.sort(key=lambda x: (x["净流入"] if x["净流入"] is not None else -1e18), reverse=True)
    for i, row in enumerate(rows, 1):
        row["排名"] = i
    return rows


def match_flow_rank(industry_name: str, flow_list: list[dict]) -> tuple[int | None, dict | None]:
    """
    zt_pool的所属行业字段可能被截断(如'家电零部'截断自'家电零部件')，
    与板块资金流(细分行业全名)做精确匹配优先，退化到前缀/包含匹配。
    """
    if not industry_name or not flow_list:
        return None, None
    for row in flow_list:
        if row["名称"] == industry_name:
            return row["排名"], row
    for row in flow_list:
        name = row["名称"]
        if name.startswith(industry_name) or industry_name in name:
            return row["排名"], row
    return None, None


# ─────────────────────────────────────────────────────────────────────────
# §4 资金流居前排"3日以上"持续性 — 自建滚动历史(实盘每日跑一次自动积累)
# ─────────────────────────────────────────────────────────────────────────

def load_flow_rank_history() -> dict:
    if FLOW_RANK_HISTORY_PATH.exists():
        try:
            return json.loads(FLOW_RANK_HISTORY_PATH.read_text())
        except Exception:
            pass
    return {"days": []}


def append_flow_rank_history(date_str: str, today_flow: list[dict]) -> None:
    """把今日(今日窗口)每个板块的排名记一笔，供未来判断'连续N日居前'用。只在实盘日(=今天)调用。"""
    hist = load_flow_rank_history()
    ranks = {row["名称"]: row["排名"] for row in today_flow}
    days = hist.get("days", [])
    if days and days[-1].get("date") == date_str:
        days[-1]["ranks"] = ranks
    else:
        days.append({"date": date_str, "ranks": ranks})
    hist["days"] = days[-30:]
    atomic_write_json(FLOW_RANK_HISTORY_PATH, hist)


def check_flow_persistence(sector_name: str, flow_today: list[dict], flow_5d: list[dict],
                             threshold_rank: int = 30, min_days: int = 3) -> dict:
    """
    条件②的核心判定: 板块资金流是否'3日以上仍居前排'。
    优先用自建滚动历史(真实逐日排名)；历史积累不足3天时退化到官方5日窗口快照做代理，
    并在method字段里诚实标注用的是哪种方法。
    """
    hist = load_flow_rank_history()
    days = hist.get("days", [])
    hit_days = []
    for day in reversed(days):
        rank = day.get("ranks", {}).get(sector_name)
        if rank is not None and rank <= threshold_rank:
            hit_days.append(day["date"])
        else:
            break  # 要求连续，断了就停

    today_rank, _ = match_flow_rank(sector_name, flow_today)
    if today_rank is not None and today_rank <= threshold_rank:
        hit_days_today = [TODAY_STR] + hit_days if (not hit_days or hit_days[0] != TODAY_STR) else hit_days
    else:
        hit_days_today = []

    if len(hit_days_today) >= min_days:
        return {
            "pass": True,
            "method": "own_history_daily_rank",
            "consecutive_days": len(hit_days_today),
            "detail": f"自建逐日历史显示连续{len(hit_days_today)}日排名≤{threshold_rank} (真实3日+持续性)",
        }

    # 退化到5日窗口快照代理(方向正确但不是真正"连续N日居前"的逐日验证)
    rank5d, _ = match_flow_rank(sector_name, flow_5d)
    if rank5d is not None:
        ok = rank5d <= threshold_rank
        return {
            "pass": ok,
            "method": "proxy_5day_window_snapshot",
            "rank_5d": rank5d,
            "detail": (
                f"自建逐日历史不足{min_days}天(仅{len(hit_days_today)}天有效样本)，"
                f"退化用官方5日累计资金流排名{rank5d}(阈值≤{threshold_rank})做代理，"
                f"不是逐日验证的真'3日+持续居前'，需继续积累每日快照后自动切换为精确判定"
            ),
        }

    return {"pass": None, "method": "no_data", "detail": "5日窗口板块资金流未匹配到该板块名"}


# ─────────────────────────────────────────────────────────────────────────
# §5 产业链地图(product_tree_map.json) — 龙头/跟随/未启动 + 层级扩散
# ─────────────────────────────────────────────────────────────────────────

_TREE_STRUCTURE_CACHE: list[dict] | None = None


def load_tree_structure() -> list[dict]:
    global _TREE_STRUCTURE_CACHE
    if _TREE_STRUCTURE_CACHE is not None:
        return _TREE_STRUCTURE_CACHE
    d = json.loads(PRODUCT_TREE_MAP_PATH.read_text())
    _TREE_STRUCTURE_CACHE = d["tree_structure"]
    return _TREE_STRUCTURE_CACHE


def build_ticker_tree_index(tree_structure: list[dict]) -> dict[str, list[dict]]:
    """code -> [{"tree","node","layer","role"}, ...] (一只票可能属于多条链/多个节点)"""
    idx: dict[str, list[dict]] = {}
    for tree in tree_structure:
        tree_name = tree["tree"]
        for node in tree["nodes"]:
            for tk in node["tickers"]:
                idx.setdefault(tk["code"], []).append({
                    "tree": tree_name,
                    "node": node["node"],
                    "layer": node["layer"],
                    "role": tk["role"],
                    "name": tk["name"],
                })
    return idx


def find_trees_by_name(tree_structure: list[dict], name_fragments: list[str]) -> list[dict]:
    frags = [f.strip() for f in name_fragments if f.strip()]
    if not frags:
        return []
    return [t for t in tree_structure if any(f in t["tree"] for f in frags)]


def tree_tickers(tree: dict) -> list[str]:
    codes = []
    for node in tree["nodes"]:
        for tk in node["tickers"]:
            codes.append(tk["code"])
    return sorted(set(codes))


def rank_trees_by_price_action(tree_structure: list[dict], price_map: dict[str, dict],
                                 min_tickers: int = 5) -> list[dict]:
    """
    产业链广度雷达 — 独立于涨停池的第二探测通道。

    ⛔ 为什么需要这个通道(07-31回测撞见的真实缺口，不是理论假设):
      涨停池方法(§6-§8的主排名)只认"封死在涨停价"的票。回测07-31("科技修复启动日")发现：
      AI算力链73只票当日97%上涨、平均+4.38%，但因为链内以688/300(20cm封板制)大票为主，
      强势日体现为+4%~+13%的普涨而非物理封死10%涨停，涨停池排名完全没看到这条主线。
      半导体设备国产化链同日54只票85%上涨、平均+2.82%，同样的问题。
      → 涨停/连板法对"游资题材连板式"主线(方法#1，中小盘10cm封板)预测力最高，
        但对"机构修复式"主线(大盘/科创板20cm封板，强势但未必封板)是系统性盲区。
      本函数直接按链内成分股当日涨跌幅排名33条产业链，补上这个盲区，
      对应诊断7方法排名#3(龙头股高度)+#4(产业链轮动扩散节奏)在"链"这一层的独立实现。

    排序: 按平均涨幅降序。
    """
    results = []
    for tree in tree_structure:
        codes = tree_tickers(tree)
        pcts = [price_map[c]["change_pct"] for c in codes
                if price_map.get(c, {}).get("change_pct") is not None]
        if len(pcts) < min_tickers:
            continue
        avg_pct = sum(pcts) / len(pcts)
        up_ratio = sum(1 for p in pcts if p > 0) / len(pcts)
        strong_ratio = sum(1 for p in pcts if p >= 3) / len(pcts)
        zt_ratio = sum(1 for p in pcts if p >= 9.8) / len(pcts)
        results.append({
            "tree": tree["tree"], "n_tickers_priced": len(pcts), "n_tickers_total": len(codes),
            "avg_change_pct": round(avg_pct, 2), "up_ratio": round(up_ratio, 3),
            "strong_ratio_ge3pct": round(strong_ratio, 3), "zt_ratio": round(zt_ratio, 3),
        })
    results.sort(key=lambda x: -x["avg_change_pct"])
    for i, r in enumerate(results, 1):
        r["排名"] = i
    return results


def chain_breadth_stage(tree: dict, date_str: str, lookback: int = 5, min_tickers: int = 5) -> dict:
    """
    广度雷达探测到的链，给一个轻量阶段读数(不复用涨停streak逻辑，因为这类链常年没有涨停样本)。
    复用kline_cache里已经拉好的日线(build_price_map_historical同一份缓存)，零额外网络请求，
    只是多算trailing几天的平均涨幅序列。

    stage粗分:
      streak<=1天(仅今天广度转强) → "启动期(广度首日转强)"
      2-4天且今日强度未明显衰减 → "主升发酵中段(广度延续)"
      强度较峰值明显衰减(今日avg<峰值*0.4)或上涨占比跌破50% → "高潮/钝化迹象"
      其余 → "延续中/待确认"
    """
    import kline_cache as kc
    codes = tree_tickers(tree)
    kc.update_cache(codes)
    target = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    daily_series: list[dict] = []  # [{"date":..., "avg_pct":..., "up_ratio":...}, ...] 升序
    per_code_pcts: dict[str, list[tuple[str, float]]] = {}
    for code in codes:
        df = kc.get_klines(code, days=280)
        if df is None:
            continue
        sub = df[df["date"] <= target].tail(lookback + 1)
        if len(sub) < 2:
            continue
        dates = sub["date"].tolist()
        closes = sub["Close"].tolist()
        pairs = []
        for i in range(1, len(closes)):
            pct = (closes[i] / closes[i - 1] - 1) * 100 if closes[i - 1] else None
            pairs.append((dates[i], pct))
        per_code_pcts[code] = pairs

    all_dates = sorted({d for pairs in per_code_pcts.values() for d, _ in pairs})
    for d in all_dates:
        pcts = [p for pairs in per_code_pcts.values() for dd, p in pairs if dd == d and p is not None]
        if len(pcts) < min_tickers:
            continue
        avg = sum(pcts) / len(pcts)
        up_ratio = sum(1 for p in pcts if p > 0) / len(pcts)
        daily_series.append({"date": d, "avg_pct": round(avg, 2), "up_ratio": round(up_ratio, 3), "n": len(pcts)})

    if not daily_series:
        return {"stage": "数据不足", "daily_series": [], "note": "缓存的历史K线不足以计算广度序列"}

    streak = 0
    for day in reversed(daily_series):
        if day["avg_pct"] > 1.5:
            streak += 1
        else:
            break

    today_avg = daily_series[-1]["avg_pct"]
    peak_avg = max(d["avg_pct"] for d in daily_series)
    today_up = daily_series[-1]["up_ratio"]

    if streak <= 1:
        stage = "启动期(广度首日转强)"
        reason = f"trailing{lookback}日中仅今日平均涨幅>1.5%(今日{today_avg:+.2f}%)"
    elif today_avg < peak_avg * 0.4 or today_up < 0.5:
        stage = "高潮/钝化迹象"
        reason = f"今日平均涨幅{today_avg:+.2f}%较区间峰值{peak_avg:+.2f}%明显衰减，或上涨占比{today_up:.0%}<50%"
    elif 2 <= streak <= 4:
        stage = "主升发酵中段(广度延续)"
        reason = f"连续{streak}日平均涨幅>1.5%，今日{today_avg:+.2f}%仍健康"
    else:
        stage = "延续中/待确认"
        reason = f"连续{streak}日走强，样本较长需结合涨停池数据交叉确认"

    return {"stage": stage, "reason": reason, "breadth_streak_days": streak,
            "daily_series": daily_series, "today_avg_pct": today_avg, "peak_avg_pct": peak_avg}


def build_price_map_all_trees(tree_structure: list[dict], date_str: str, is_today: bool) -> dict[str, dict]:
    """一次性为全部33条链的并集ticker(847只)建价格map，避免按链重复拉取。"""
    all_codes = sorted({c for t in tree_structure for c in tree_tickers(t)})
    if is_today:
        return build_price_map_live(all_codes)
    return build_price_map_historical(all_codes, date_str)


def build_price_map_live(codes: list[str]) -> dict[str, dict]:
    """实时价格/涨跌幅(今天) — 走astock_data_layer的批量接口，分批避免URL过长。"""
    import astock_data_layer as adl  # 复用唯一合法A股数据入口
    out: dict[str, dict] = {}
    chunk = 80
    for i in range(0, len(codes), chunk):
        batch = codes[i:i + chunk]
        res = adl.get_batch_prices(batch)
        for code, info in res.items():
            out[code] = {"change_pct": info.get("change_pct"), "price": info.get("price")}
        time.sleep(0.1)
    return out


def build_price_map_historical(codes: list[str], date_str: str) -> dict[str, dict]:
    """历史某日的涨跌幅 — 走本地kline_cache(baostock前复权日线)，day-over-day算涨跌幅。
    仅对本次分析涉及的产业链票(几十只)拉取，不对全市场847只票跑，控制运行时间。"""
    import kline_cache as kc
    yyyy, mm, dd = date_str[:4], date_str[4:6], date_str[6:8]
    target = f"{yyyy}-{mm}-{dd}"
    kc.update_cache(codes)
    out: dict[str, dict] = {}
    for code in codes:
        df = kc.get_klines(code, days=280)
        if df is None:
            out[code] = {"change_pct": None, "price": None}
            continue
        sub = df[df["date"] <= target]
        if len(sub) < 2:
            out[code] = {"change_pct": None, "price": None}
            continue
        last_row = sub.iloc[-1]
        if str(last_row["date"]) != target:
            # 该日无成交记录(停牌/未上市)
            out[code] = {"change_pct": None, "price": None}
            continue
        prev_close = float(sub.iloc[-2]["Close"])
        close = float(last_row["Close"])
        pct = (close / prev_close - 1) * 100 if prev_close else None
        out[code] = {"change_pct": pct, "price": close}
    return out


def analyze_chain_diffusion(tree: dict, zt_code_set: set[str], price_map: dict[str, dict]) -> dict:
    """
    单条产业链的扩散快照: 按layer分组，把每个ticker归入 龙头/跟随/尚未启动。
    龙头 = role含"龙头" 且 今日涨停或涨幅>=7% ；跟随 = 非龙头但今日涨停或涨幅>0；
    尚未启动 = 涨幅<=0或无数据。
    """
    leaders, followers, not_started = [], [], []
    layer_summary: dict[str, dict] = {}

    for node in tree["nodes"]:
        layer = node["layer"]
        layer_summary.setdefault(layer, {"总数": 0, "涨停": 0, "上涨未涨停": 0, "未启动": 0})
        for tk in node["tickers"]:
            code = tk["code"]
            info = price_map.get(code, {})
            pct = info.get("change_pct")
            is_zt = code in zt_code_set or (pct is not None and pct >= 9.8)
            entry = {
                "代码": code, "名称": tk["name"], "角色": tk["role"],
                "节点": node["node"], "层级": layer, "涨跌幅": pct, "涨停": is_zt,
            }
            layer_summary[layer]["总数"] += 1
            if is_zt:
                layer_summary[layer]["涨停"] += 1
                (leaders if "龙头" in tk["role"] else followers).append(entry)
            elif pct is not None and pct > 0:
                layer_summary[layer]["上涨未涨停"] += 1
                followers.append(entry)
            else:
                layer_summary[layer]["未启动"] += 1
                not_started.append(entry)

    return {
        "tree": tree["tree"],
        "龙头": leaders,
        "跟随": followers,
        "尚未启动": not_started,
        "层级汇总": layer_summary,
    }


# ─────────────────────────────────────────────────────────────────────────
# §6 板块聚合统计
# ─────────────────────────────────────────────────────────────────────────

def build_sector_stats(zt_pool: list[dict], zt_prev: list[dict], zbgc: list[dict]) -> dict[str, dict]:
    """按所属行业聚合: zt_count/max连板/龙头/晋级率/炸板率。"""
    sectors: dict[str, dict] = {}

    for row in zt_pool:
        sec = row["所属行业"] or "(未分类)"
        s = sectors.setdefault(sec, {
            "zt_count": 0, "max_lianban": 0, "leader": None,
            "zt_codes": [], "gains": [],
        })
        s["zt_count"] += 1
        s["zt_codes"].append(row["代码"])
        s["gains"].append(row["涨跌幅"])
        if row["连板数"] > s["max_lianban"]:
            s["max_lianban"] = row["连板数"]
            s["leader"] = {"代码": row["代码"], "名称": row["名称"], "连板数": row["连板数"],
                            "涨跌幅": row["涨跌幅"]}

    # 晋级率: 昨日涨停股，今日是否再次封板(最新价>=涨停价)，按所属行业分组
    promo_by_sector: dict[str, list[bool]] = {}
    for row in zt_prev:
        sec = row["所属行业"] or "(未分类)"
        zt_price = row["涨停价"]
        cur_price = row["最新价"]
        promoted = (zt_price is not None and cur_price is not None and cur_price >= zt_price * 0.998)
        promo_by_sector.setdefault(sec, []).append(promoted)

    # 炸板率: 该板块 zbgc数 / (zbgc数 + zt数)
    zbgc_by_sector: dict[str, int] = {}
    for row in zbgc:
        sec = row["所属行业"] or "(未分类)"
        zbgc_by_sector[sec] = zbgc_by_sector.get(sec, 0) + 1

    all_sectors = set(sectors) | set(promo_by_sector) | set(zbgc_by_sector)
    for sec in all_sectors:
        s = sectors.setdefault(sec, {
            "zt_count": 0, "max_lianban": 0, "leader": None, "zt_codes": [], "gains": [],
        })
        promos = promo_by_sector.get(sec, [])
        s["promotion_rate"] = (sum(promos) / len(promos)) if promos else None
        s["promotion_sample"] = len(promos)
        zbgc_n = zbgc_by_sector.get(sec, 0)
        denom = zbgc_n + s["zt_count"]
        s["board_break_rate"] = (zbgc_n / denom) if denom > 0 else None
        s["zbgc_count"] = zbgc_n
        s["avg_gain"] = (sum(s["gains"]) / len(s["gains"])) if s["gains"] else None

    return sectors


def compute_streaks(sector_names: set[str], zt_multiday: dict[str, list[dict]],
                      trading_days: list[str], min_zt: int = 2) -> dict[str, dict]:
    """连续天数(streak) + 趋势(加速/持平/减速)。trading_days为升序，最后一个是当前分析日。"""
    per_day_counts: dict[str, dict[str, int]] = {}
    for d in trading_days:
        counts: dict[str, int] = {}
        for row in zt_multiday.get(d, []):
            sec = row["所属行业"] or "(未分类)"
            counts[sec] = counts.get(sec, 0) + 1
        per_day_counts[d] = counts

    out = {}
    for sec in sector_names:
        streak = 0
        for d in reversed(trading_days):
            if per_day_counts.get(d, {}).get(sec, 0) >= min_zt:
                streak += 1
            else:
                break
        today_d = trading_days[-1]
        yday_d = trading_days[-2] if len(trading_days) >= 2 else None
        today_count = per_day_counts.get(today_d, {}).get(sec, 0)
        yday_count = per_day_counts.get(yday_d, {}).get(sec, 0) if yday_d else 0
        if today_count > yday_count:
            trend = "加速"
        elif today_count < yday_count:
            trend = "减速"
        else:
            trend = "持平"
        out[sec] = {"streak_days": streak, "trend": trend, "zt_count_today": today_count,
                     "zt_count_yday": yday_count}
    return out


# ─────────────────────────────────────────────────────────────────────────
# §7 生命周期阶段判定
# ─────────────────────────────────────────────────────────────────────────

def classify_stage(streak: dict, promotion_rate: float | None, board_break_rate: float | None,
                     market_total_zt: int) -> tuple[str, list[str]]:
    """
    四阶段规则(严格对应诊断7原文，阈值为本脚本落地时选定，见每条注释):
      退潮期: 炸板率高 或 晋级率低 且 已有过热(streak>=2) 且 趋势减速 —— 三线至少两线确认
      启动期: streak<=2 (刚冒头，样本太少不足以判断中段/高潮)
      高潮期: 全市场涨停>50家(诊断7原文阈值) 且 本板块晋级率开始走弱(<30%)但涨停数仍不低 —— 补涨+利好钝化的量化替身
      主升发酵中段: 其余情况，streak在2~8之间且晋级率尚可(>=25%)
      主升早期/待确认: 兜底
    """
    reasons = []
    streak_days = streak["streak_days"]
    trend = streak["trend"]
    pr = promotion_rate if promotion_rate is not None else 0.0
    bbr = board_break_rate if board_break_rate is not None else 0.0

    retreat_signals = 0
    if bbr >= 0.45:
        retreat_signals += 1
        reasons.append(f"炸板率{bbr:.0%}≥45%")
    if promotion_rate is not None and pr < 0.15 and streak_days >= 2:
        retreat_signals += 1
        reasons.append(f"晋级率{pr:.0%}<15%(已有连续{streak_days}日热度基础)")
    if trend == "减速" and streak_days >= 2:
        retreat_signals += 1
        reasons.append(f"连续{streak_days}日后today涨停数较昨日{trend}")

    if retreat_signals >= 2:
        return "退潮期", reasons

    if streak_days <= 1:
        reasons = [f"streak={streak_days}日(刚出现/首日)，涨停{streak['zt_count_today']}家"]
        return "启动期", reasons

    if market_total_zt > 50:
        if promotion_rate is not None and pr < 0.30 and streak['zt_count_today'] >= streak['zt_count_yday']:
            reasons = [
                f"全市场涨停{market_total_zt}家>50家(诊断7高潮期阈值)",
                f"本板块晋级率走弱至{pr:.0%}但涨停数未退({streak['zt_count_today']}家,昨{streak['zt_count_yday']}家)"
                "——补涨+利好钝化的量化替身信号",
            ]
            return "高潮期", reasons
        else:
            reasons = [f"全市场涨停{market_total_zt}家>50家，但本板块晋级率{pr:.0%}仍健康，未现钝化"]

    if 2 <= streak_days <= 8 and pr >= 0.25:
        reasons = [f"streak={streak_days}日，晋级率{pr:.0%}≥25%，扩散尚在持续"]
        return "主升发酵中段", reasons

    reasons = reasons or [f"streak={streak_days}日，晋级率{pr:.0%}，指标混合，未达任一明确阶段阈值"]
    return "主升早期/待确认", reasons


# ─────────────────────────────────────────────────────────────────────────
# §8 综合打分排序 — 权重对应诊断7的"预测力排名"
# ─────────────────────────────────────────────────────────────────────────

WEIGHTS = {
    "lianban": 35,      # 连板高度+晋级率 — 排名#1，高预测力/低难度
    "promotion": 25,    # (与lianban同属#1，拆开算避免单一维度支配)
    "flow_rank": 20,    # 板块资金连续N日居前 — 排名#2，高预测力/低难度
    "chain": 15,        # 产业链轮动扩散 — 排名#4，高预测力/中高难度(能匹配上product_tree才加分)
    "lhb": 5,           # 龙虎榜 — 排名#5，"确认不是发现"，权重最低
}


def score_sector(sec_stats: dict, flow_rank_today: int | None, flow_rank_5d: int | None,
                   n_sectors_flow: int, has_chain_match: bool, lhb_hit: bool) -> float:
    lianban_score = min(sec_stats["max_lianban"] / 6.0, 1.0) * WEIGHTS["lianban"]
    pr = sec_stats.get("promotion_rate")
    promo_score = (pr if pr is not None else 0.0) * WEIGHTS["promotion"]

    flow_score = 0.0
    if n_sectors_flow > 0:
        best_rank = None
        if flow_rank_today is not None:
            best_rank = flow_rank_today
        if flow_rank_5d is not None:
            best_rank = flow_rank_5d if best_rank is None else min(best_rank, flow_rank_5d)
        if best_rank is not None:
            flow_score = max(0.0, 1.0 - (best_rank - 1) / n_sectors_flow) * WEIGHTS["flow_rank"]

    chain_score = WEIGHTS["chain"] if has_chain_match else 0.0
    lhb_score = WEIGHTS["lhb"] if lhb_hit else 0.0

    bbr = sec_stats.get("board_break_rate")
    penalty = (bbr * 15) if bbr is not None else 0.0  # 炸板率惩罚，最多扣15分

    return round(lianban_score + promo_score + flow_score + chain_score + lhb_score - penalty, 2)


# ─────────────────────────────────────────────────────────────────────────
# §9 四条件进场检查(条件① ② ③ ④)
# ─────────────────────────────────────────────────────────────────────────

def _get_price_series(code: str, days: int = 60):
    import kline_cache as kc
    kc.update_cache([code])
    return kc.get_klines(code, days=days)


def check_leader_ma20(code: str, tree_structure: list[dict],
                        ticker_tree_index: dict[str, list[dict]]) -> dict:
    """条件① 龙头20日均线未破。若ticker自己就是龙头则查自己；否则查同node/同tree的龙头。"""
    memberships = ticker_tree_index.get(code, [])
    if not memberships:
        return _ma20_status(code, note="未在product_tree_map中找到该ticker，退化为检查自身20日均线")

    leader_codes: set[str] = set()
    self_is_leader = any("龙头" in m["role"] for m in memberships)
    if self_is_leader:
        leader_codes.add(code)
    else:
        by_tree: dict[str, list[dict]] = {}
        for m in memberships:
            by_tree.setdefault(m["tree"], []).append(m)
        for tree_name, ms in by_tree.items():
            tree = next((t for t in tree_structure if t["tree"] == tree_name), None)
            if not tree:
                continue
            node_names = {m["node"] for m in ms}
            for node in tree["nodes"]:
                if node["node"] not in node_names:
                    continue
                for tk in node["tickers"]:
                    if "龙头" in tk["role"]:
                        leader_codes.add(tk["code"])

    if not leader_codes:
        return _ma20_status(code, note="所在产业链节点无明确'龙头'标注，退化为检查自身20日均线")

    results = [_ma20_status(c) for c in sorted(leader_codes)]
    all_pass = all(r["pass"] is True for r in results if r["pass"] is not None)
    any_unknown = any(r["pass"] is None for r in results)
    broken = [r for r in results if r["pass"] is False]

    return {
        "pass": None if (any_unknown and not broken) else (False if broken else all_pass),
        "leaders_checked": results,
        "note": (f"检查了{len(leader_codes)}个龙头: " +
                 ", ".join(f"{r['code']}({'未破' if r['pass'] else '已破' if r['pass'] is False else '无数据'})"
                           for r in results)),
    }


def _ma20_status(code: str, note: str = "") -> dict:
    df = _get_price_series(code, days=40)
    if df is None or len(df) < 20:
        return {"code": code, "pass": None, "detail": f"K线数据不足(<20日) {note}".strip()}
    closes = df["Close"].tolist()
    ma20 = sum(closes[-20:]) / 20
    last_close = closes[-1]
    dist_pct = (last_close / ma20 - 1) * 100 if ma20 else None
    return {
        "code": code, "pass": last_close >= ma20,
        "ma20": round(ma20, 3), "last_close": round(last_close, 3),
        "distance_pct": round(dist_pct, 2) if dist_pct is not None else None,
        "detail": f"收盘{last_close:.2f} vs MA20={ma20:.2f} ({dist_pct:+.1f}%) {note}".strip(),
    }


def check_flow_condition(code: str, sector_name: str | None, flow_today: list[dict],
                           flow_5d: list[dict], threshold_rank: int = 30) -> dict:
    """条件② 板块资金流3日以上仍居前排。"""
    if not sector_name:
        return {"pass": None, "detail": "未提供该ticker的所属行业，无法定位板块资金流"}
    result = check_flow_persistence(sector_name, flow_today, flow_5d, threshold_rank=threshold_rank)
    result["sector"] = sector_name
    return result


def check_25d_high(code: str) -> dict:
    """条件③ 距最近25日高≤8%。"""
    df = _get_price_series(code, days=40)
    if df is None or len(df) < 25:
        return {"pass": None, "detail": "K线数据不足(<25日)"}
    highs = df["High"].tolist()
    closes = df["Close"].tolist()
    high25 = max(highs[-25:])
    last_close = closes[-1]
    dist_pct = (high25 - last_close) / high25 * 100 if high25 else None
    ok = dist_pct is not None and dist_pct <= 8.0
    return {
        "pass": ok, "high_25d": round(high25, 3), "last_close": round(last_close, 3),
        "distance_pct": round(dist_pct, 2) if dist_pct is not None else None,
        "detail": f"25日高={high25:.2f}，现价{last_close:.2f}，回落{dist_pct:.1f}% (阈值≤8%)" if dist_pct is not None else "无法计算",
    }


def check_entry_conditions(code: str, sector_name: str | None, tree_structure: list[dict],
                             ticker_tree_index: dict[str, list[dict]],
                             flow_today: list[dict], flow_5d: list[dict],
                             fundamental_pass: bool | None = None) -> dict:
    """
    四条件综合检查入口。
    fundamental_pass: 条件④需人工判断，脚本不自动计算；调用方可传入人工结论(True/False)，
                       默认None表示"未提供，本脚本不臆断"。
    """
    c1 = check_leader_ma20(code, tree_structure, ticker_tree_index)
    c2 = check_flow_condition(code, sector_name, flow_today, flow_5d)
    c3 = check_25d_high(code)
    c4 = {"pass": fundamental_pass,
          "detail": "④基本面轴独立过关: 需人工判断(供给约束/主beta/催化剂时间线三问)，本脚本不自动计算"
                     if fundamental_pass is None else "外部传入的人工基本面判断结论"}

    conditions = {
        "①龙头20日均线未破": c1,
        "②板块资金流3日以上仍居前排": c2,
        "③距最近25日高≤8%": c3,
        "④基本面轴独立过关": c4,
    }

    failed = [k for k, v in conditions.items() if v.get("pass") is False]
    unknown = [k for k, v in conditions.items() if v.get("pass") is None]

    if failed:
        verdict = f"不可进 — {'; '.join(failed)} 不满足"
    elif "④基本面轴独立过关" in unknown and len(unknown) == 1:
        verdict = "技术面①②③已过，待人工确认④基本面后可进"
    elif unknown:
        verdict = f"数据不足，无法判定: {'; '.join(unknown)}"
    else:
        verdict = "可进 — 四条件全部满足"

    return {"code": code, "sector": sector_name, "conditions": conditions,
            "failed": failed, "unknown": unknown, "verdict": verdict}


# ─────────────────────────────────────────────────────────────────────────
# §10 主扫描流程
# ─────────────────────────────────────────────────────────────────────────

def run_scan(date_str: str, top_n: int = 15, streak_lookback: int = 10,
              tree_name_filter: list[str] | None = None, live_flow: bool | None = None,
              chain_rank: bool = False) -> dict:
    is_today = (date_str == TODAY_STR)
    if live_flow is None:
        live_flow = is_today

    print(f"{'='*70}\n主线扫描 — {date_str} {'(实盘/今日)' if is_today else '(历史回测)'}\n{'='*70}")

    zt_pool = fetch_zt_pool(date_str)
    zt_prev = fetch_zt_previous(date_str)
    zbgc = fetch_zbgc(date_str)
    market_total_zt = len(zt_pool)
    print(f"当日涨停{market_total_zt}家 | 昨日涨停今日回看{len(zt_prev)}只 | 炸板{len(zbgc)}只")

    sec_stats = build_sector_stats(zt_pool, zt_prev, zbgc)

    trading_days = trading_days_ending_at(date_str, streak_lookback)
    zt_multiday = fetch_zt_pool_multiday(trading_days)
    streaks = compute_streaks(set(sec_stats), zt_multiday, trading_days, min_zt=2)

    if live_flow:
        print("拉取板块资金流(今日/5日/10日, push2delay直连)...")
        flow_today = fetch_sector_money_flow("今日")
        flow_5d = fetch_sector_money_flow("5日")
        flow_10d = fetch_sector_money_flow("10日")
        append_flow_rank_history(date_str, flow_today)
        n_sectors_flow = len(flow_today)
    else:
        flow_today, flow_5d, flow_10d = [], [], []
        n_sectors_flow = 0
        print("⛔ 历史日期: 板块资金流无历史查询能力(push2delay/push2his均为快照，无date参数)，"
              "条件②/资金流分项本次回测标记为 not_available，不伪造数字。")

    lhb = fetch_lhb(date_str)
    lhb_names = set()
    lhb_code_to_sector = {r["代码"]: None for r in lhb}
    zt_code_to_sector = {r["代码"]: r["所属行业"] for r in zt_pool}
    for code in lhb_code_to_sector:
        if code in zt_code_to_sector:
            lhb_names.add(zt_code_to_sector[code])

    tree_structure = load_tree_structure()
    ticker_tree_index = build_ticker_tree_index(tree_structure)

    ranked = []
    for sec, stats in sec_stats.items():
        if stats["zt_count"] == 0 and stats.get("zbgc_count", 0) == 0:
            continue
        streak = streaks.get(sec, {"streak_days": 0, "trend": "持平", "zt_count_today": stats["zt_count"],
                                     "zt_count_yday": 0})
        frank_today, _ = match_flow_rank(sec, flow_today) if live_flow else (None, None)
        frank_5d, _ = match_flow_rank(sec, flow_5d) if live_flow else (None, None)

        sector_codes = set(stats.get("zt_codes", []))
        has_chain_match = any(ticker_tree_index.get(c) for c in sector_codes)

        stage, stage_reasons = classify_stage(streak, stats.get("promotion_rate"),
                                                stats.get("board_break_rate"), market_total_zt)
        score = score_sector(stats, frank_today, frank_5d, n_sectors_flow, has_chain_match, sec in lhb_names)

        ranked.append({
            "板块": sec, "综合分": score, "连续天数": streak["streak_days"], "趋势": streak["trend"],
            "今日涨停家数": stats["zt_count"], "最高连板": stats["max_lianban"], "龙头": stats["leader"],
            "晋级率": stats.get("promotion_rate"), "晋级率样本数": stats.get("promotion_sample", 0),
            "炸板率": stats.get("board_break_rate"), "炸板数": stats.get("zbgc_count", 0),
            "资金流排名_今日": frank_today, "资金流排名_5日": frank_5d,
            "产业链匹配": has_chain_match, "龙虎榜确认": sec in lhb_names,
            "阶段": stage, "阶段依据": stage_reasons,
        })

    ranked.sort(key=lambda x: -x["综合分"])
    top = ranked[:top_n]

    # 产业链广度雷达(可选，--chain-rank): 独立于涨停池的第二探测通道，见rank_trees_by_price_action文档字符串
    breadth_ranking: list[dict] = []
    price_map_all: dict[str, dict] = {}
    if chain_rank:
        print("产业链广度雷达: 为全部33条链的847只票并集拉价格(涨停池之外的第二探测通道)...")
        price_map_all = build_price_map_all_trees(tree_structure, date_str, is_today)
        breadth_ranking = rank_trees_by_price_action(tree_structure, price_map_all)

    # 产业链扩散分析: 用户指定--trees时按用户指定；否则自动探测——
    # 探测信号取两路并集: ①top板块涨停龙头命中的链 ②(若开了--chain-rank)广度雷达头部的链，
    # 避免"07-31型"广度普涨但零涨停的主线被漏判(实测发现的真实盲区，见rank_trees_by_price_action注释)。
    if tree_name_filter:
        selected_trees = find_trees_by_name(tree_structure, tree_name_filter)
    else:
        hit_counter: dict[str, int] = {}
        for sec_row in top[:5]:
            leader = sec_row["龙头"]
            if leader:
                for m in ticker_tree_index.get(leader["代码"], []):
                    hit_counter[m["tree"]] = hit_counter.get(m["tree"], 0) + 1
        auto_names = list(dict.fromkeys(sorted(hit_counter, key=lambda k: -hit_counter[k])[:3]))
        if chain_rank:
            for r in breadth_ranking[:3]:
                if r["tree"] not in auto_names:
                    auto_names.append(r["tree"])
        selected_trees = [t for t in tree_structure if t["tree"] in auto_names]

    diffusion = []
    if selected_trees:
        if price_map_all:
            price_map = price_map_all
        else:
            all_codes = sorted({c for t in selected_trees for c in tree_tickers(t)})
            print(f"产业链扩散分析: {len(selected_trees)}条链, {len(all_codes)}只票...")
            price_map = build_price_map_live(all_codes) if is_today else build_price_map_historical(all_codes, date_str)
        zt_code_set = {r["代码"] for r in zt_pool}
        for tree in selected_trees:
            d = analyze_chain_diffusion(tree, zt_code_set, price_map)
            if not is_today:
                d["breadth_stage"] = chain_breadth_stage(tree, date_str)
            diffusion.append(d)

    result = {
        "date": date_str, "is_live": is_today, "market_total_zt": market_total_zt,
        "n_sectors_scanned": len(ranked), "flow_data_available": live_flow,
        "mainline_ranking": top,
        "chain_breadth_ranking": breadth_ranking,
        "chain_diffusion": diffusion,
        "generated_at": NOW.isoformat(),
    }

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(SNAPSHOT_DIR / f"{date_str}.json", result)

    return result


# ─────────────────────────────────────────────────────────────────────────
# §11 输出格式化
# ─────────────────────────────────────────────────────────────────────────

def print_ranking_table(result: dict) -> None:
    print(f"\n{'─'*100}")
    print(f"主线板块排名 — {result['date']} | 全市场涨停{result['market_total_zt']}家 "
          f"| 扫描到{result['n_sectors_scanned']}个有涨停/炸板活动的板块"
          f"{'' if result['flow_data_available'] else ' | ⚠️资金流数据不可得(历史回测限制)'}")
    print(f"{'─'*100}")
    hdr = f"{'#':<3}{'板块':<12}{'分':<7}{'连续天':<6}{'趋势':<5}{'今日涨停':<8}{'最高连板':<8}{'晋级率':<8}{'炸板率':<8}{'资金流排名':<12}{'阶段'}"
    print(hdr)
    print("-" * len(hdr))
    for i, row in enumerate(result["mainline_ranking"], 1):
        pr = f"{row['晋级率']*100:.0f}%" if row["晋级率"] is not None else "N/A"
        bbr = f"{row['炸板率']*100:.0f}%" if row["炸板率"] is not None else "N/A"
        frank = row["资金流排名_今日"]
        f5 = row["资金流排名_5日"]
        frank_str = f"{frank}/{f5}" if (frank is not None or f5 is not None) else "N/A"
        leader = row["龙头"]
        leader_str = f"{leader['名称']}{leader['连板数']}板" if leader else "-"
        print(f"{i:<3}{row['板块']:<12}{row['综合分']:<7}{row['连续天数']:<6}{row['趋势']:<5}"
              f"{row['今日涨停家数']:<8}{leader_str:<8}{pr:<8}{bbr:<8}{frank_str:<12}{row['阶段']}")
        for reason in row["阶段依据"]:
            print(f"      └ {reason}")

    if result.get("chain_breadth_ranking"):
        print(f"\n{'─'*100}")
        print("产业链广度雷达(独立于涨停池的第二探测通道 — 见rank_trees_by_price_action文档，"
              "捕捉'机构修复式'普涨主线) — TOP15")
        print(f"{'─'*100}")
        hdr2 = f"{'#':<3}{'产业链':<58}{'平均涨幅':<10}{'上涨占比':<10}{'强势(≥3%)占比':<14}{'涨停占比'}"
        print(hdr2)
        for r in result["chain_breadth_ranking"][:15]:
            print(f"{r['排名']:<3}{r['tree'][:56]:<58}{r['avg_change_pct']:+.2f}%    "
                  f"{r['up_ratio']*100:.0f}%       {r['strong_ratio_ge3pct']*100:.0f}%            "
                  f"{r['zt_ratio']*100:.0f}%  ({r['n_tickers_priced']}/{r['n_tickers_total']}只有数据)")

    if result["chain_diffusion"]:
        print(f"\n{'─'*100}\n产业链扩散进度\n{'─'*100}")
        for d in result["chain_diffusion"]:
            print(f"\n【{d['tree']}】")
            print(f"  龙头({len(d['龙头'])}): " + ", ".join(f"{e['名称']}({e['层级']})" for e in d["龙头"][:10]))
            print(f"  跟随({len(d['跟随'])}): " + ", ".join(f"{e['名称']}({e['层级']})" for e in d["跟随"][:15]))
            print(f"  尚未启动({len(d['尚未启动'])}): " +
                  ", ".join(f"{e['名称']}" for e in d["尚未启动"][:10]) +
                  (" ..." if len(d["尚未启动"]) > 10 else ""))
            print("  层级汇总: " + " | ".join(
                f"{layer}: 涨停{s['涨停']}/上涨{s['上涨未涨停']}/未启动{s['未启动']}(共{s['总数']})"
                for layer, s in d["层级汇总"].items()))
            if "breadth_stage" in d:
                bs = d["breadth_stage"]
                print(f"  广度阶段: {bs['stage']}" + (f" — {bs['reason']}" if "reason" in bs else ""))
                if bs.get("daily_series"):
                    print("    近日广度序列: " + " | ".join(
                        f"{s['date'][5:]}:{s['avg_pct']:+.1f}%({s['up_ratio']*100:.0f}%涨)"
                        for s in bs["daily_series"]))


def print_entry_check(result: dict) -> None:
    print(f"\n{'='*70}\n四条件进场检查 — {result['code']} (所属行业: {result['sector'] or '未知'})\n{'='*70}")
    print(f"综合结论: {result['verdict']}\n")
    for name, c in result["conditions"].items():
        status = "✅通过" if c.get("pass") is True else ("❌不满足" if c.get("pass") is False else "❓未知/待人工")
        print(f"[{status}] {name}")
        print(f"      {c.get('detail') or c.get('note', '')}")
        if "leaders_checked" in c:
            for r in c["leaders_checked"]:
                print(f"        - {r['code']}: {r['detail']}")


# ─────────────────────────────────────────────────────────────────────────
# §12 CLI
# ─────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="A股主线识别引擎(重建任务C1)")
    parser.add_argument("--date", default=TODAY_STR, help="YYYYMMDD，默认今天")
    parser.add_argument("--top", type=int, default=15, help="显示前N主线板块")
    parser.add_argument("--lookback", type=int, default=10, help="streak计算回溯交易日数")
    parser.add_argument("--trees", default=None, help="逗号分隔的产业链名称片段，指定则不自动探测")
    parser.add_argument("--check", default=None, help="逗号分隔股票代码，跑四条件进场检查")
    parser.add_argument("--flow-threshold", type=int, default=30, help="条件②资金流'居前排'的排名阈值")
    parser.add_argument("--chain-rank", action="store_true",
                         help="开启产业链广度雷达(全33链847只票按当日涨跌幅排名，"
                              "捕捉涨停池测不到的机构修复式主线；较慢，默认关闭)")
    parser.add_argument("--json", action="store_true", help="额外打印完整JSON")
    args = parser.parse_args()

    date_str = args.date
    tree_filter = [s for s in args.trees.split(",")] if args.trees else None

    result = run_scan(date_str, top_n=args.top, streak_lookback=args.lookback,
                       tree_name_filter=tree_filter, chain_rank=args.chain_rank)
    print_ranking_table(result)

    if args.check:
        tree_structure = load_tree_structure()
        ticker_tree_index = build_ticker_tree_index(tree_structure)
        is_today = (date_str == TODAY_STR)
        if is_today:
            flow_today = fetch_sector_money_flow("今日")
            flow_5d = fetch_sector_money_flow("5日")
        else:
            flow_today, flow_5d = [], []

        zt_pool = fetch_zt_pool(date_str)
        code_to_sector = {r["代码"]: r["所属行业"] for r in zt_pool}
        # 若不在涨停池(常见:非涨停的观察票)，用产业链地图里的行业信息兜底(取树名近似)
        for code in [c.strip() for c in args.check.split(",")]:
            sector = code_to_sector.get(code)
            if sector is None:
                memberships = ticker_tree_index.get(code, [])
                sector = None  # zt_pool的"所属行业"字段和产业链tree名不是同一命名体系，不强行伪造对应

            entry_result = check_entry_conditions(
                code, sector, tree_structure, ticker_tree_index,
                flow_today, flow_5d,
            )
            print_entry_check(entry_result)
            if args.json:
                print(json.dumps(entry_result, ensure_ascii=False, indent=2))

    if args.json:
        print(f"\n{'='*70}\n完整JSON\n{'='*70}")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
