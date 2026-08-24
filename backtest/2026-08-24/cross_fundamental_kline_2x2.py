#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证假设: 基本面拐点 + K线拐点 同时出现时,信号最强(2x2交叉)

设计说明(必读, 决定了本脚本为什么这样设计, 而不是直接复用同批H1财报flip信号):
  同目录下已有的H1财报flip/decel-accel信号(backtest_kfjlr_deceleration.py ->
  signal_results_full.csv)信号日期(ann_date)全部落在2026-07-16~08-24, 高度右偏
  (中报法定披露截止8月31日, 多数公司集中在8月最后两周披露)。用它做2x2交叉的锚点会导致
  20/40交易日前瞻收益因"今天=2026-08-24"右截断而几乎全部缺失(实测: ret_20d非空仅6条,
  ret_40d非空0条) —— 样本量不足以支撑本任务要求的20/40日结论。

  改为以"K线拐点信号日"作为交叉锚点(K线拐点在窗口内均匀分布, 06-24起就有信号), 在每个
  K线信号日, 用"point-in-time"规则查该股当时已知的最近两期已披露财报的同比增速方向,
  作为当天的基本面状态(基本面向上/向下)。这样能大幅缓解右截断问题, 同时两个信号的定义
  与同批sibling脚本(backtest_kfjlr_deceleration.py 的"连续期扣非/净利润增速方向"、
  trend_seq_vs_cost_stop.py 的"高点/低点序列降降=K线向下, 抬抬=K线向上")保持方法论一致。

  ⚠️本session未收到"A1/A2/A3/A4"信号的直接交接文档(与同目录下ma_vs_drawdown_backtest.py /
  trend_seq_vs_cost_stop.py两个sibling脚本遇到的情况相同, 均在脚本头部声明"未能定位A1具体
  产出文件/交接说明")。本脚本按任务原文语义操作化: A1=基本面向下, A2=基本面向上,
  A3=K线向下, A4=K线向上, 定义如下, 供复核者判断是否与原始意图一致。

基本面信号(point-in-time, 每只股票每个交易日t):
  用本地已有的4期 akshare yjbb_em 批量净利润数据(yjbb_20250930/20251231/20260331/20260630.csv,
  字段: 净利润-同比增长 + 最新公告日期), 对每只股票按"最新公告日期<=t"筛出t时刻已知的报告,
  取已知报告里报告期最新的两期(curr, prev), 比较同比增速:
    curr同比 > prev同比 -> 基本面向上(A2)
    curr同比 < prev同比 -> 基本面向下(A1)
    相等或已知报告<2期 -> 跳过(不计入,不猜)
  已知局限: "净利润-同比增长"是净利润口径,非扣非口径,含非经常性损益(与同批
  backtest_kfjlr_deceleration.py注释一致的已知局限, 非结论支持性证据被隐藏)。

K线信号(point-in-time, 每只股票每个交易日t, 复用trend_seq_vs_cost_stop.py同款算法):
  取t及之前最近30个交易日, 切3个连续10日子窗口(W1最早/W2中/W3最近含t)。
  W1/W2/W3各自max(high)序列 -> 高点序列(降/抬/混合); min(low)序列 -> 低点序列。
  高点序列=降 且 低点序列=降 -> K线向下(A3, "降降")
  高点序列=抬 且 低点序列=抬 -> K线向上(A4, "抬抬")
  其余 -> 混合(不进4格主表, 仅作对照)
  状态机去重: 只在"新进入"该状态的当天记一次信号,避免同一趋势里逐日重复计入。

universe: 沪深300+中证500成分股(当前成分, ak.index_stock_cons), 与同批kfjlr_flip.py/
  trend_seq_vs_cost_stop.py口径一致。
价格源: 腾讯 web.ifzq.gtimg.cn/appstock/app/fqkline/get (qfq前复权) 直连, 失败换本地akshare-china
  CLI(新浪源, 不复权)兜底(同trend_seq_vs_cost_stop.py, 该脚本实测本机环境tencent 0/717成功,
  ak兜底717/717成功, 故本脚本ThreadPoolExecutor用CLI子进程兜底为主, tencent仅作首选尝试)。
窗口: 信号日限定在 2026-06-24~2026-08-24(2个月), 前瞻收益按信号日收盘价起算5/20/40交易日,
  数据不足右截断记为缺失, 不外推。
落盘: 本文件路径 + cross_signals_log.csv(逐信号明细) + cross_summary.json(分组统计)。
"""

import json
import math
import statistics
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd


def _is_missing(r):
    """None 或 NaN(pandas把dict里的None写进DataFrame数值列后会变float('nan'),
    不再是None, 必须同时判两种)"""
    return r is None or (isinstance(r, float) and math.isnan(r))

WORKDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
AK_CLI = "/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"
FETCH_START = "2026-04-01"
FETCH_END = "2026-08-24"
WIN_START = "2026-06-24"
WIN_END = "2026-08-24"
HORIZONS = [5, 20, 40]
TIMEOUT = 8

YJBB_FILES = [
    ("2025-09-30", 0, "yjbb_20250930.csv"),
    ("2025-12-31", 1, "yjbb_20251231.csv"),
    ("2026-03-31", 2, "yjbb_20260331.csv"),
    ("2026-06-30", 3, "yjbb_20260630.csv"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- 基本面 point-in-time timeline ----------
def build_fundamental_timeline():
    """返回 dict: code(6位str) -> sorted list of (period_order, disclosure_date, yoy_growth)"""
    per_code = {}
    for period, order, fname in YJBB_FILES:
        df = pd.read_csv(f"{WORKDIR}/{fname}", dtype={"股票代码": str})
        df["股票代码"] = df["股票代码"].str.zfill(6)
        df = df[["股票代码", "净利润-同比增长", "最新公告日期"]].dropna()
        for _, r in df.iterrows():
            code = r["股票代码"]
            try:
                yoy = float(r["净利润-同比增长"])
            except (ValueError, TypeError):
                continue
            ddate = str(r["最新公告日期"])
            if not (len(ddate) == 10 and ddate[4] == "-"):
                continue
            per_code.setdefault(code, []).append((order, ddate, yoy))
    for code in per_code:
        per_code[code].sort(key=lambda x: x[0])
    return per_code


def fundamental_state_at(timeline, date_str):
    """timeline: list of (order, ddate, yoy) sorted by order. 返回 'up'/'down'/None"""
    known = [t for t in timeline if t[1] <= date_str]
    if len(known) < 2:
        return None
    known.sort(key=lambda x: x[0])
    curr = known[-1]
    prev = known[-2]
    if curr[2] > prev[2]:
        return "up"
    if curr[2] < prev[2]:
        return "down"
    return None


# ---------- universe ----------
def load_universe():
    import akshare as ak
    hs300 = ak.index_stock_cons(symbol="000300")
    zz500 = ak.index_stock_cons(symbol="000905")
    codes = pd.concat([hs300["品种代码"], zz500["品种代码"]]).drop_duplicates().tolist()
    return sorted(codes)


# ---------- 价格抓取 ----------
def tencent_prefix(code):
    return "sh" if code.startswith("6") else "sz"


def fetch_tencent(code):
    pref = tencent_prefix(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
           f"{pref}{code},day,{FETCH_START},{FETCH_END},320,qfq")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8")
    d = json.loads(raw)
    if d.get("code") != 0:
        raise RuntimeError(f"tencent code={d.get('code')}")
    key = pref + code
    node = d["data"][key]
    rows = node.get("qfqday") or node.get("day")
    if not rows:
        raise RuntimeError("empty rows")
    bars = [{"d": r[0], "o": float(r[1]), "c": float(r[2]), "h": float(r[3]),
              "l": float(r[4]), "v": float(r[5])} for r in rows]
    bars.sort(key=lambda x: x["d"])
    return bars


def fetch_ak_fallback(code):
    out = subprocess.run([AK_CLI, "kline", code, "140", "--json"],
                          capture_output=True, text=True, timeout=TIMEOUT).stdout
    data = json.loads(out)
    bars = []
    for r in data:
        try:
            bars.append({"d": r["day"], "o": float(r["open"]), "c": float(r["close"]),
                         "h": float(r["high"]), "l": float(r["low"]), "v": float(r["volume"])})
        except Exception:
            continue
    bars.sort(key=lambda x: x["d"])
    return [b for b in bars if FETCH_START <= b["d"] <= FETCH_END]


def fetch_one(code):
    try:
        bars = fetch_tencent(code)
        if len(bars) >= 40:
            return code, bars, "tencent_qfq", None
        raise RuntimeError(f"tencent too short n={len(bars)}")
    except Exception as e1:
        try:
            bars = fetch_ak_fallback(code)
            if len(bars) < 40:
                raise RuntimeError(f"fallback too short n={len(bars)}")
            return code, bars, "ak_sina_noqfq_fallback", None
        except Exception as e2:
            return code, None, None, f"tencent_fail={e1} | ak_fallback_fail={e2}"


# ---------- K线状态分类(复用trend_seq_vs_cost_stop.py同款算法) ----------
def classify_seq(vals):
    if vals[0] > vals[1] > vals[2]:
        return "降"
    if vals[0] < vals[1] < vals[2]:
        return "抬"
    return "混合"


def kline_label_for(hi_seq, lo_seq):
    if hi_seq == "降" and lo_seq == "降":
        return "down"
    if hi_seq == "抬" and lo_seq == "抬":
        return "up"
    return "mixed"


def detect_kline_signals(bars):
    sigs = []
    prev_label = None
    n = len(bars)
    for i in range(29, n):
        window = bars[i - 29: i + 1]
        w1, w2, w3 = window[0:10], window[10:20], window[20:30]
        hi_seq = classify_seq([max(b["h"] for b in w) for w in (w1, w2, w3)])
        lo_seq = classify_seq([min(b["l"] for b in w) for w in (w1, w2, w3)])
        label = kline_label_for(hi_seq, lo_seq)
        d = bars[i]["d"]
        if WIN_START <= d <= WIN_END and label != prev_label:
            sigs.append({"idx": i, "date": d, "kline": label, "close": bars[i]["c"]})
        prev_label = label
    return sigs


def fwd_returns(bars, sig_idx, sig_close):
    out = {}
    n = len(bars)
    for h in HORIZONS:
        j = sig_idx + h
        out[h] = (bars[j]["c"] / sig_close - 1.0) if j < n else None
    return out


def pctl(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def stats_block(returns):
    vals = sorted(r for r in returns if not _is_missing(r))
    n = len(vals)
    if n == 0:
        return dict(n=0, mean=None, median=None, win_rate=None, p5=None, p95=None)
    return dict(
        n=n,
        mean=round(statistics.mean(vals) * 100, 2),
        median=round(statistics.median(vals) * 100, 2),
        win_rate=round(sum(1 for v in vals if v > 0) / n * 100, 1),
        p5=round(pctl(vals, 0.05) * 100, 2),
        p95=round(pctl(vals, 0.95) * 100, 2),
    )


def main():
    t0 = time.time()
    log("Step1: 构建基本面point-in-time timeline(本地yjbb文件,无需网络)")
    fund_timeline = build_fundamental_timeline()
    log(f"  覆盖股票数: {len(fund_timeline)}")

    log("Step2: 拉universe(沪深300+中证500)")
    universe = load_universe()
    log(f"  universe n={len(universe)}")

    log("Step3: 并发拉价格(tencent优先, ak CLI兜底)")
    price_data = {}
    failed = []
    src_count = {}
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(fetch_one, c): c for c in universe}
        done = 0
        for fut in as_completed(futs):
            code, bars, src, err = fut.result()
            done += 1
            if bars is None:
                failed.append((code, err))
            else:
                price_data[code] = bars
                src_count[src] = src_count.get(src, 0) + 1
            if done % 150 == 0:
                log(f"  ...价格拉取进度 {done}/{len(universe)} 耗时{time.time()-t0:.0f}s")
    log(f"  价格拉取完成: ok={len(price_data)} failed={len(failed)} 来源={src_count} 耗时{time.time()-t0:.0f}s")
    if failed:
        log(f"  失败样例(前10): {failed[:10]}")

    log("Step4: 逐票检测K线信号 + 匹配point-in-time基本面状态 + 算前瞻收益")
    events = []
    n_no_fund = 0
    n_no_price_at_all = 0
    for code, bars in price_data.items():
        if len(bars) < 31:
            n_no_price_at_all += 1
            continue
        sigs = detect_kline_signals(bars)
        tl = fund_timeline.get(code)
        for s in sigs:
            fstate = fundamental_state_at(tl, s["date"]) if tl else None
            if fstate is None:
                n_no_fund += 1
                continue
            fr = fwd_returns(bars, s["idx"], s["close"])
            events.append({
                "code": code, "date": s["date"], "kline": s["kline"],
                "fundamental": fstate, "close": s["close"],
                "ret_5": fr[5], "ret_20": fr[20], "ret_40": fr[40],
            })
    log(f"  信号事件总数(有基本面+K线双状态)={len(events)}, "
        f"因无基本面数据被跳过={n_no_fund}, 价格序列过短被跳过={n_no_price_at_all}")

    ev_df = pd.DataFrame(events)
    ev_df.to_csv(f"{WORKDIR}/cross_signals_log.csv", index=False)
    log(f"  已落盘逐信号明细: {WORKDIR}/cross_signals_log.csv (n={len(ev_df)})")

    # ---------- 分组统计 ----------
    def sub(fund, kline):
        return ev_df[(ev_df.fundamental == fund) & (ev_df.kline == kline)]

    cells = {
        "基本面向下+K线向下(A1+A3)": sub("down", "down"),
        "基本面向下+K线向上(A1+A4)": sub("down", "up"),
        "基本面向上+K线向下(A2+A3)": sub("up", "down"),
        "基本面向上+K线向上(A2+A4)": sub("up", "up"),
    }
    controls = {
        "对照_K线混合(不管基本面)": ev_df[ev_df.kline == "mixed"],
        "边际_全部K线向下(不管基本面)": ev_df[ev_df.kline == "down"],
        "边际_全部K线向上(不管基本面)": ev_df[ev_df.kline == "up"],
        "边际_全部基本面向下(不管K线)": ev_df[ev_df.fundamental == "down"],
        "边际_全部基本面向上(不管K线)": ev_df[ev_df.fundamental == "up"],
        "对照_全样本(不做任何筛选)": ev_df,
    }

    summary = {"meta": {
        "window": f"{WIN_START}~{WIN_END}",
        "universe_n": len(universe),
        "price_ok_n": len(price_data),
        "events_total": len(ev_df),
    }}
    print("\n" + "=" * 90)
    print("2x2交叉主表: (基本面方向, K线方向) -> horizon -> n/mean%/median%/win_rate%/p5%/p95%")
    print("=" * 90)
    for name, df in {**cells, **controls}.items():
        summary[name] = {}
        for h in HORIZONS:
            sb = stats_block(df[f"ret_{h}"].tolist())
            summary[name][f"{h}d"] = sb
            flag = " <-- n<30仅方向性提示" if (sb["n"] and sb["n"] < 30) else (" <-- n=0" if sb["n"] == 0 else "")
            if sb["n"]:
                print(f"{name:32s} | {h:2d}日 | n={sb['n']:4d} mean={sb['mean']:+7.2f}% "
                      f"median={sb['median']:+7.2f}% win={sb['win_rate']:5.1f}% "
                      f"p5={sb['p5']:+7.2f}% p95={sb['p95']:+7.2f}%{flag}")
            else:
                print(f"{name:32s} | {h:2d}日 | n=0 (无数据)")

    with open(f"{WORKDIR}/cross_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    log(f"已落盘汇总: {WORKDIR}/cross_summary.json")
    log(f"总耗时 {time.time()-t0:.1f}s")
    return summary, ev_df


if __name__ == "__main__":
    main()
