#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.14", "yfinance>=0.2", "requests>=2.28", "baostock>=0.8"]
# ///
"""
UASS 自动扫描引擎 v3.0 — 全自动数据拉取 + Track B评分 + D6筹码+技术常识体检 + 产业链发散

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
    import akshare as ak

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

    # 1b. 全市场强势股(push2delay HTTPS, VPN下可用)
    try:
        strong = fetch_strong_movers(min_change_pct=5.0)
        zt_codes = {s["代码"] for s in result["zt_pool"]}
        result["strong_movers"] = [s for s in strong if s["代码"] not in zt_codes]
        print(f"  强势非涨停: {len(result['strong_movers'])}只 (涨幅>5%, 排除已涨停)")
    except Exception as e:
        result["errors"].append(f"强势股扫描: {e}")
        print(f"  强势非涨停: 失败 ({e})")

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

    # 3. 板块资金流向 (akshare → push2delay fallback)
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
    except Exception:
        try:
            result["sector_flow"] = _fetch_board_push2delay("m:90+t:2", top_n=30)
            print(f"  板块资金: {len(result['sector_flow'])}个行业 (push2delay)")
        except Exception as e2:
            result["errors"].append(f"板块资金: {e2}")
            print(f"  板块资金: 失败 ({e2})")

    # 3b. 概念板块涨幅 (akshare → push2delay fallback)
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
    except Exception:
        try:
            result["concept_flow"] = _fetch_board_push2delay("m:90+t:3", top_n=20)
            print(f"  概念板块: TOP{len(result['concept_flow'])}已获取 (push2delay)")
        except Exception as e2:
            result["errors"].append(f"概念板块: {e2}")
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

# ── D6 筹码体检（历史维度）— 过去N天涨了多少？量价结构健不健康？───────────

D6_FLAGS = {
    # ── 原有flags (涨幅+量价) ──
    "EXTREME_RUN":    "⛔ 20日涨幅>60%，翻倍行情末段",
    "HEAVY_RUN":      "⚠️ 20日涨幅>40%，获利盘沉重",
    "VOLUME_CLIMAX":  "⛔ 近5日出现过最大量日+放量>均量2x，冲顶放量",
    "VOL_SHRINK":     "⚠️ 今日成交量<近5日均量50%，买盘衰竭",
    "VOL_PRICE_DIV":  "⚠️ 近5日价格新高但成交量递减30%+，量价背离",
    "PROFIT_TRAPPED": "⚠️ 20日均价远低于现价(>25%)，获利盘悬顶",
    # ── 新增: 技术常识flags ──
    "MA_OVEREXTEND":  "⛔ 价格远超MA20(>25%)，严重偏离均线",
    "MA_BEARISH":     "⚠️ MA5<MA10<MA20空头排列，趋势向下",
    "MACD_TOP_DIV":   "⛔ 价格新高但MACD柱缩短，顶背离",
    "RSI_EXTREME":    "⚠️ RSI(14)>85，极度超买",
    "STAGNANT_VOL":   "⛔ 高位放量(>2x)但涨幅<2%，放量滞涨=出货",
    "HIGH_SHADOW":    "⚠️ 近3日高位长上影线(>实体2x)，上方抛压重",
    # ── 健康 ──
    "HEALTHY":        "✓ 筹码+技术面健康",
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
    if code.startswith("8") or code.startswith("4"):
        return None
    import baostock as bs
    import pandas as pd
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 20)).strftime("%Y-%m-%d")
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
    start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
    df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
    if df is None or df.empty:
        return None
    df = df.rename(columns={"日期": "Date", "开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"})
    return df.tail(days)


def _fetch_hist_yf(code: str, days: int = 65):
    """yfinance兜底."""
    import yfinance as yf
    hist = yf.Ticker(_yf_code(code)).history(period=f"{days}d")
    return hist if hist is not None and len(hist) > 0 else None


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


def chip_health_check(code: str, current_price: float = 0, use_cache: bool = False) -> dict:
    """Pull 60-day price history, return chip+technical health flags."""
    import numpy as np
    result = {"flags": [], "30d_gain": None, "vol_ratio": None, "avg_cost_20d": None,
              "ma20_dev": None, "rsi14": None}
    try:
        hist = _fetch_hist_cached(code) if use_cache else _fetch_hist(code)
        if hist is None or len(hist) < 20:
            return result

        closes = np.array(hist["Close"].values, dtype=float)
        volumes = np.array(hist["Volume"].values, dtype=float)
        highs = np.array(hist["High"].values, dtype=float)
        lows = np.array(hist["Low"].values, dtype=float)
        opens = np.array(hist["Open"].values, dtype=float) if "Open" in hist.columns else closes.copy()

        if np.any(np.isnan(closes)) or len(closes) < 20:
            valid = ~np.isnan(closes)
            closes = closes[valid]
            volumes = volumes[valid]
            highs = highs[valid]
            lows = lows[valid]
            opens = opens[valid]
            if len(closes) < 20:
                return result

        curr = closes[-1] if current_price <= 0 else current_price

        # ── 原有检查 ──────────────────────────────────────────────

        # 20-day gain
        if len(closes) >= 15:
            base = closes[-15]
            gain_20d = (curr - base) / base * 100
            result["30d_gain"] = round(gain_20d, 1)
            if gain_20d > 60:
                result["flags"].append("EXTREME_RUN")
            elif gain_20d > 40:
                result["flags"].append("HEAVY_RUN")

        # Volume climax: 近5日内出现过最大量日
        if len(volumes) >= 20:
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

        # Volume-price divergence
        if len(closes) >= 5:
            last5_close = closes[-5:]
            last5_vol_arr = volumes[-5:]
            if last5_close[-1] >= max(last5_close) * 0.99:
                vol_trend = (last5_vol_arr[-1] - last5_vol_arr[0]) / last5_vol_arr[0] if last5_vol_arr[0] > 0 else 0
                if vol_trend < -0.3:
                    result["flags"].append("VOL_PRICE_DIV")

        # Profit-trapped
        if len(closes) >= 20:
            avg_20 = closes[-20:].mean()
            result["avg_cost_20d"] = round(float(avg_20), 2)
            profit_gap = (curr - avg_20) / avg_20 * 100
            if profit_gap > 25:
                result["flags"].append("PROFIT_TRAPPED")

        # ── 新增: 技术常识检查 ─────────────────────────────────────

        # 1. 均线偏离: 价格远超MA20 → 追高危险
        if len(closes) >= 20:
            ma20 = closes[-20:].mean()
            ma_dev = (curr - ma20) / ma20 * 100
            result["ma20_dev"] = round(ma_dev, 1)
            if ma_dev > 25:
                result["flags"].append("MA_OVEREXTEND")

        # 2. 均线空头排列: MA5 < MA10 < MA20 → 趋势向下不该买
        if len(closes) >= 20:
            ma5 = closes[-5:].mean()
            ma10 = closes[-10:].mean()
            ma20_val = closes[-20:].mean()
            if ma5 < ma10 < ma20_val:
                result["flags"].append("MA_BEARISH")

        # 3. MACD顶背离: 价格近5日新高但MACD柱在缩短
        if len(closes) >= 30:
            ema12 = _calc_ema(closes, 12)
            ema26 = _calc_ema(closes, 26)
            dif = ema12 - ema26
            dea = _calc_ema(dif, 9)
            macd_bar = (dif - dea) * 2
            # 价格在近20日高点附近(>98%)，但MACD柱近5日在缩短
            price_near_high = curr >= max(closes[-20:]) * 0.98
            if price_near_high and len(macd_bar) >= 5:
                bar_5d = macd_bar[-5:]
                if bar_5d[-1] < bar_5d[0] and bar_5d[-1] < max(bar_5d) * 0.7:
                    result["flags"].append("MACD_TOP_DIV")

        # 4. RSI极度超买
        rsi = _calc_rsi(closes.tolist())
        result["rsi14"] = round(rsi, 1)
        if rsi > 85:
            result["flags"].append("RSI_EXTREME")

        # 5. 放量滞涨: 高位放量(>2x均量)但涨幅<2% = 出货
        if len(volumes) >= 20 and len(closes) >= 20:
            avg_vol_20 = volumes[-20:].mean()
            today_vol = volumes[-1]
            today_chg = abs(closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] > 0 else 0
            price_at_high = curr >= max(closes[-20:]) * 0.95
            if price_at_high and today_vol > avg_vol_20 * 2 and today_chg < 2:
                result["flags"].append("STAGNANT_VOL")

        # 6. 高位长上影线: 近3日有长上影线(>实体2x) = 上方抛压
        if len(closes) >= 20:
            price_at_high = curr >= max(closes[-20:]) * 0.95
            if price_at_high:
                for i in range(-3, 0):
                    if abs(i) <= len(closes):
                        body = abs(closes[i] - opens[i])
                        upper_shadow = highs[i] - max(closes[i], opens[i])
                        if body > 0 and upper_shadow > body * 2:
                            result["flags"].append("HIGH_SHADOW")
                            break

        if not result["flags"]:
            result["flags"].append("HEALTHY")

    except Exception:
        result["flags"].append("DATA_ERROR")

    return result


_hist_cache: dict[str, object] = {}


def _prefetch_baostock_batch(codes: list[str], days: int = 65) -> None:
    """Batch-prefetch historical data via single baostock session (non-threaded)."""
    global _hist_cache
    bs_codes = [c for c in codes if not c.startswith("8") and not c.startswith("4")]
    if not bs_codes:
        return
    try:
        import baostock as bs
        import pandas as pd
        bs.login()
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days + 20)).strftime("%Y-%m-%d")
        for code in bs_codes:
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
                if rows:
                    df = pd.DataFrame(rows, columns=rs.fields)
                    for col in ("open", "high", "low", "close", "volume"):
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})
                    df = df.dropna(subset=["Close"])
                    if len(df) >= 20:
                        _hist_cache[code] = df.tail(days)
            except Exception:
                pass
        bs.logout()
    except Exception:
        pass


def _fetch_hist_cached(code: str, days: int = 65):
    """Use prefetched cache, then yfinance fallback."""
    if code in _hist_cache:
        return _hist_cache[code]
    return _fetch_hist_yf(code, days)


def batch_chip_health(scored: list[dict], top_n: int = 30) -> None:
    """Run chip health check on top N scored stocks, enrich in-place."""
    import concurrent.futures

    targets = scored[:top_n]
    codes = [s["代码"] for s in targets]

    _prefetch_baostock_batch(codes)

    import time as _time
    results = {}
    batch_size = 4
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as pool:
            futures = {pool.submit(chip_health_check, code, 0, True): code for code in batch}
            for f in concurrent.futures.as_completed(futures):
                code = futures[f]
                try:
                    results[code] = f.result()
                except Exception:
                    results[code] = {"flags": ["DATA_ERROR"], "30d_gain": None}
        if i + batch_size < len(codes):
            _time.sleep(0.3)

    for s in targets:
        chk = results.get(s["代码"], {})
        s["D6_flags"] = chk.get("flags", [])
        s["D6_30d涨幅"] = chk.get("30d_gain")
        s["D6_量比"] = chk.get("vol_ratio")
        s["D6_20日均价"] = chk.get("avg_cost_20d")
        s["D6_MA偏离"] = chk.get("ma20_dev")
        s["D6_RSI"] = chk.get("rsi14")

        # D6 penalty: 核心flag扣分, 辅助flag仅叠加时加重
        penalty = 0
        flags = s["D6_flags"]
        # ── 涨幅类 (互斥取最严重) ──
        if "EXTREME_RUN" in flags:
            penalty = -35
        elif "HEAVY_RUN" in flags:
            penalty = -20
        # ── 量价类 (累加) ──
        if "VOLUME_CLIMAX" in flags:
            penalty += -15
        if "PROFIT_TRAPPED" in flags:
            penalty += -10
        if "STAGNANT_VOL" in flags:
            penalty += -15
        # ── 技术面类 (累加) ──
        if "MA_OVEREXTEND" in flags:
            penalty += -15
        if "MACD_TOP_DIV" in flags:
            penalty += -10
        if "MA_BEARISH" in flags:
            penalty += -10
        # ── 辅助flag: 单独不扣分, 有核心flag时才加重 ──
        has_core_flag = any(f in flags for f in (
            "EXTREME_RUN", "HEAVY_RUN", "VOLUME_CLIMAX", "PROFIT_TRAPPED",
            "MA_OVEREXTEND", "MACD_TOP_DIV", "STAGNANT_VOL"))
        if has_core_flag:
            if "VOL_SHRINK" in flags:
                penalty += -5
            if "VOL_PRICE_DIV" in flags:
                penalty += -5
            if "RSI_EXTREME" in flags:
                penalty += -5
            if "HIGH_SHADOW" in flags:
                penalty += -5

        s["D6_penalty"] = penalty
        s["TB总分_raw"] = s["TB总分"]
        s["TB总分"] = max(0, s["TB总分"] + penalty)
        s["TB评级"] = score_to_grade(s["TB总分"])


def _score_d1_from_lhb(code: str, lhb_map: dict) -> tuple[str, int]:
    lhb = lhb_map.get(code, {})
    net_buy = lhb.get("龙虎榜净买额", 0)
    jigou = "机构" in lhb.get("解读", "")
    has_lhb = code in lhb_map
    if net_buy >= 5e8 and jigou:
        return "S", D1_SCORES["S"]
    if net_buy >= 2e8 or (has_lhb and jigou):
        return "A", D1_SCORES["A"]
    if has_lhb:
        return "B", D1_SCORES["B"]
    return "C", D1_SCORES["C"]


def score_strong_movers(movers: list[dict], lhb_map: dict, zt_sectors: dict[str, list]) -> list[dict]:
    """Score non-limit-up strong movers (涨幅>5%) with adapted Track B."""
    sector_groups: dict[str, list] = {}
    for s in movers:
        sec = s.get("所属行业", "未知")
        sector_groups.setdefault(sec, []).append(s)

    for sec, members in sector_groups.items():
        members.sort(key=lambda x: x.get("涨跌幅", 0), reverse=True)
        for i, s in enumerate(members):
            if sec in zt_sectors:
                s["_d3"] = "先手" if i == 0 else "跟涨"
            else:
                s["_d3"] = "龙头" if i == 0 else ("先手" if i <= 2 else "跟涨")
            s["_d3_score"] = D3_SCORES[s["_d3"]]

    scored = []
    for s in movers:
        code = s["代码"]
        d1, d1s = _score_d1_from_lhb(code, lhb_map)

        change_pct = s.get("涨跌幅", 0)
        is_gem_star = code.startswith("3") or code.startswith("68")
        if is_gem_star and change_pct >= 15:
            d2, d2s = "A", D2_SCORES["A"]
        elif change_pct >= 10:
            d2, d2s = "B", D2_SCORES["B"]
        else:
            d2, d2s = "C", D2_SCORES["C"]

        d3 = s.get("_d3", "跟涨")
        d3s = s.get("_d3_score", D3_SCORES["跟涨"])
        d4, d4s = "启动", D4_SCORES["启动"]
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

    scored = []
    for s in zt_pool:
        code = s["代码"]
        lhb = lhb_map.get(code, {})
        net_buy = lhb.get("龙虎榜净买额", 0)

        d1, d1s = _score_d1_from_lhb(code, lhb_map)
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
            "数据源": "涨停池",
        })

    # 合并强势非涨停股(push2delay)
    if strong_movers:
        scored_strong = score_strong_movers(strong_movers, lhb_map, sector_groups)
        scored.extend(scored_strong)

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
    print(f"{'#':>3} {'代码':<8} {'名称':<8} {'行业':<10} {'市值亿':>6} {'TB分':>7} {'级':>3} {'D1':>2} {'D2':>2} {'D3':<4} {'D4':<6} {'30d%':>5} {'量比':>4} {'D6筹码'}")
    for i, s in enumerate(scored[:top_n], 1):
        g30 = s.get("D6_30d涨幅")
        g30_str = f"{g30:>+4.0f}%" if g30 is not None else "  N/A"
        vr = s.get("D6_量比")
        vr_str = f"{vr:>3.1f}x" if vr is not None else " N/A"
        flags = s.get("D6_flags", [])
        flag_str = ",".join(f for f in flags if f != "HEALTHY" and f != "DATA_ERROR")
        if not flag_str:
            flag_str = "✓" if "HEALTHY" in flags else "N/A"
        penalty = s.get("D6_penalty", 0)
        raw = s.get("TB总分_raw", s["TB总分"])
        score_str = f"{s['TB总分']:>4}" if penalty == 0 else f"{raw}→{s['TB总分']}"
        print(f"{i:>3} {s['代码']:<8} {s['名称']:<8} {s['行业']:<10} {s['总市值_亿']:>5.0f} {score_str:>7} {s['TB评级']:>3} {s['D1']:>2} {s['D2']:>2} {s['D3']:<4} {s['D4']:<6} {g30_str} {vr_str} {flag_str}")

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
    print(f"评级分布: S={s_count} A+={a_plus} A={a_count} A-={a_minus} | 涨停{zt_count}只 | 强势非涨停{strong_count}只 | 合计{len(scored)}只")
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

    # D6 筹码体检: 拉历史行情, 检查涨幅/量价/筹码结构 (涨停+强势合并后的TOP40)
    d6_top = min(40, len(scored))
    print(f"D6 筹码体检中 (TOP{d6_top}历史行情)...")
    batch_chip_health(scored, top_n=d6_top)
    scored.sort(key=lambda x: x["TB总分"], reverse=True)
    print(f"D6 完成 | 标记: " + ", ".join(
        f"{s['名称']}({','.join(s.get('D6_flags',[]))})"
        for s in scored[:30] if s.get('D6_flags') and 'HEALTHY' not in s.get('D6_flags',[])
    ) or "全部健康")

    chains = find_supply_chain_candidates(scored, data["sector_flow"])

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
