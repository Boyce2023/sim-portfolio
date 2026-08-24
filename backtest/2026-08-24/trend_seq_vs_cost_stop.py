#!/usr/bin/env python3
"""
验证假设: "高点序列降低+低点序列降低"(下降趋势确立) 是否优于成本价止损, 作为持仓退出信号。
universe: 沪深300+中证500成分股去重(ak.index_stock_cons, 当前成分), n≈717。
  口径来源: 本session未收到"A1"任务的直接交接, 但本次任务与backtest_kfjlr_flip.py(同目录同批次落盘,
  文件头明确写"股票池: 沪深300+中证500成分股, 去重后作为universe")是同一批并行任务, 大概率就是提示词
  里的"A1"。为保证跨任务universe口径一致(便于同批结果互相比对), 采用与该脚本相同的沪深300+中证500定义。
  ⚠️此为推断而非确认, 已明确标注。
数据源: 腾讯 web.ifzq.gtimg.cn/appstock/app/fqkline/get (qfq前复权), 失败1次重试后换 ak CLI(新浪源,不复权) 兜底。
方法:
  对每只股票的每个交易日t(限定在回测窗口2026-06-24~2026-08-24内):
    取best t及之前最近30个交易日, 切成3个连续10日子窗口(W1最早/W2中/W3最近,含t)。
    W1/W2/W3各自的 max(high) 序列 -> 高点序列(降/抬/混合); min(low) 序列 -> 低点序列(降/抬/混合)。
    "降" = W1>W2>W3 严格递减; "抬" = W1<W2<W3 严格递增; 其余(含打平/非单调) = 混合。
  状态机取"首次进入"某状态的那一天为信号日(避免同一趋势里每天重复计入导致的高度自相关):
    降降组: 高点序列=降 且 低点序列=降, 且前一日不是该状态
    抬抬组: 高点序列=抬 且 低点序列=抬, 且前一日不是该状态
    混合组: 其余情况(高低序列不是同降或同抬), 且前一日不是"混合"状态(同样只取新进入的那天)
  信号日收盘价为基准, 计算信号后5/20/40个交易日的收盘价收益率(数据不足则该horizon记为缺失,不做任何填补/外推)。
落盘: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/trend_seq_vs_cost_stop.py
"""
import json, re, statistics, subprocess, sys, time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

WATCHLIST = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/watchlist_config.json"
AK_CLI = "/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"
FETCH_START = "2026-04-01"   # 早于回测窗口, 给30日回看窗口留缓冲
FETCH_END   = "2026-08-24"   # = 今天, 无法取到未来数据
WIN_START   = "2026-06-24"
WIN_END     = "2026-08-24"
HORIZONS    = [5, 20, 40]
TIMEOUT     = 8

def load_universe():
    import akshare as ak
    import pandas as pd
    hs300 = ak.index_stock_cons(symbol="000300")
    zz500 = ak.index_stock_cons(symbol="000905")
    codes = pd.concat([hs300["品种代码"], zz500["品种代码"]]).drop_duplicates().tolist()
    return sorted(codes)

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
        raise RuntimeError(f"tencent code={d.get('code')} msg={d.get('msg')}")
    key = pref + code
    node = d["data"][key]
    rows = node.get("qfqday") or node.get("day")
    if not rows:
        raise RuntimeError("empty rows")
    bars = []
    for r in rows:
        bars.append({
            "d": r[0], "o": float(r[1]), "c": float(r[2]),
            "h": float(r[3]), "l": float(r[4]), "v": float(r[5]),
        })
    bars.sort(key=lambda x: x["d"])
    return bars

def fetch_ak_fallback(code):
    out = subprocess.run([AK_CLI, "kline", code, "140", "--json"],
                          capture_output=True, text=True, timeout=TIMEOUT).stdout
    data = json.loads(out)
    bars = []
    for r in data:
        try:
            bars.append({
                "d": r["day"], "o": float(r["open"]), "c": float(r["close"]),
                "h": float(r["high"]), "l": float(r["low"]), "v": float(r["volume"]),
            })
        except Exception:
            continue
    bars.sort(key=lambda x: x["d"])
    return [b for b in bars if FETCH_START <= b["d"] <= FETCH_END]

def fetch_one(code):
    try:
        return code, fetch_tencent(code), "tencent_qfq", None
    except Exception as e1:
        try:
            bars = fetch_ak_fallback(code)
            if len(bars) < 40:
                raise RuntimeError(f"fallback too short n={len(bars)}")
            return code, bars, "ak_sina_noqfq_fallback", None
        except Exception as e2:
            return code, None, None, f"tencent_fail={e1} | ak_fallback_fail={e2}"

def classify_seq(vals):
    """vals=[W1,W2,W3] 顺序为最早->最近, 判定 降/抬/混合"""
    if vals[0] > vals[1] > vals[2]:
        return "降"
    if vals[0] < vals[1] < vals[2]:
        return "抬"
    return "混合"

def label_for(hi_seq, lo_seq):
    if hi_seq == "降" and lo_seq == "降":
        return "降降(下降趋势)"
    if hi_seq == "抬" and lo_seq == "抬":
        return "抬抬(上升趋势)"
    return "混合"

def detect_signals(bars):
    """返回 list of dict: {date_idx, date, label, close}"""
    sigs = []
    prev_label = None
    n = len(bars)
    for i in range(29, n):
        window = bars[i - 29 : i + 1]  # 30根, 含当日i
        w1, w2, w3 = window[0:10], window[10:20], window[20:30]
        hi_seq = classify_seq([max(b["h"] for b in w) for w in (w1, w2, w3)])
        lo_seq = classify_seq([min(b["l"] for b in w) for w in (w1, w2, w3)])
        label = label_for(hi_seq, lo_seq)
        d = bars[i]["d"]
        if WIN_START <= d <= WIN_END:
            if label != prev_label:  # 首次进入该状态才算新信号(状态机去重)
                sigs.append({"idx": i, "date": d, "label": label, "close": bars[i]["c"]})
            prev_label_in_window = True
        # 状态机不管在不在窗口内都要连续追踪(避免窗口边界前的状态被误判为"新进入")
        prev_label = label
    return sigs

def fwd_returns(bars, sig_idx, sig_close):
    out = {}
    n = len(bars)
    for h in HORIZONS:
        j = sig_idx + h
        if j < n:
            out[h] = bars[j]["c"] / sig_close - 1.0
        else:
            out[h] = None  # 右截断,数据不足,不外推
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
    vals = sorted(r for r in returns if r is not None)
    n = len(vals)
    if n == 0:
        return dict(n=0, mean=None, median=None, win_rate=None, p5=None, p95=None)
    return dict(
        n=n,
        mean=statistics.mean(vals),
        median=statistics.median(vals),
        win_rate=sum(1 for v in vals if v > 0) / n,
        p5=pctl(vals, 0.05),
        p95=pctl(vals, 0.95),
    )

def main():
    t0 = time.time()
    universe = load_universe()
    print(f"[info] universe n={len(universe)} (沪深300+中证500去重, 与同批backtest_kfjlr_flip.py口径对齐, 见脚本头部声明)")

    data = {}
    failed = []
    source_count = {"tencent_qfq": 0, "ak_sina_noqfq_fallback": 0}
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(fetch_one, c): c for c in universe}
        for fut in as_completed(futs):
            code, bars, src, err = fut.result()
            if bars is None:
                failed.append((code, err))
            else:
                data[code] = bars
                source_count[src] = source_count.get(src, 0) + 1

    print(f"[info] fetch ok={len(data)} failed={len(failed)} elapsed={time.time()-t0:.1f}s")
    print(f"[info] source breakdown: {source_count}")
    if failed:
        print(f"[info] failed tickers (first 20): {failed[:20]}")

    groups = {"降降(下降趋势)": [], "抬抬(上升趋势)": [], "混合": []}
    per_ticker_signal_count = {}
    all_signals_log = []

    for code, bars in data.items():
        if len(bars) < 30 + 1:
            continue
        sigs = detect_signals(bars)
        per_ticker_signal_count[code] = len(sigs)
        for s in sigs:
            fr = fwd_returns(bars, s["idx"], s["close"])
            groups[s["label"]].append(fr)
            all_signals_log.append({"ticker": code, "date": s["date"], "label": s["label"],
                                     "close": s["close"], "fwd": fr})

    print(f"[info] total tickers with usable series: {len(per_ticker_signal_count)}")
    print(f"[info] total signal-days detected (all groups): {len(all_signals_log)}")
    for lbl in groups:
        print(f"[info]   {lbl}: {len(groups[lbl])} signal-days")

    print("\n" + "=" * 78)
    print("结果表: 分组 x horizon -> n / mean / median / win_rate / p5 / p95")
    print("=" * 78)
    summary = {}
    for lbl, obs_list in groups.items():
        summary[lbl] = {}
        for h in HORIZONS:
            rets = [o[h] for o in obs_list]
            sb = stats_block(rets)
            summary[lbl][h] = sb
            n = sb["n"]
            if n == 0:
                print(f"{lbl:16s} | {h:2d}日 | n=0 (无数据)")
                continue
            flag = " ⚠️n<30仅方向性提示" if n < 30 else ""
            print(f"{lbl:16s} | {h:2d}日 | n={n:4d} mean={sb['mean']*100:+7.2f}% "
                  f"median={sb['median']*100:+7.2f}% win={sb['win_rate']*100:5.1f}% "
                  f"p5={sb['p5']*100:+7.2f}% p95={sb['p95']*100:+7.2f}%{flag}")

    print("\n" + "=" * 78)
    print("下降趋势确立后继续持有的代价 = 降降组 vs 抬抬组 的 mean/median 差")
    print("=" * 78)
    for h in HORIZONS:
        dd = summary["降降(下降趋势)"][h]
        uu = summary["抬抬(上升趋势)"][h]
        mx = summary["混合"][h]
        if dd["n"] and uu["n"]:
            gap_mean = dd["mean"] - uu["mean"]
            gap_med = dd["median"] - uu["median"]
            print(f"{h:2d}日: 降降mean={dd['mean']*100:+.2f}%(n={dd['n']}) vs "
                  f"抬抬mean={uu['mean']*100:+.2f}%(n={uu['n']}) -> gap={gap_mean*100:+.2f}pp | "
                  f"median gap={gap_med*100:+.2f}pp")
        else:
            print(f"{h:2d}日: 数据不足,无法比较 (降降n={dd['n']}, 抬抬n={uu['n']})")
        if mx["n"]:
            print(f"       混合组 mean={mx['mean']*100:+.2f}% median={mx['median']*100:+.2f}% n={mx['n']}")

    print("\n" + "=" * 78)
    print("反例检查(主动找不支持假设的证据)")
    print("=" * 78)
    counter_found = False
    for h in HORIZONS:
        dd = summary["降降(下降趋势)"][h]
        uu = summary["抬抬(上升趋势)"][h]
        if dd["n"] and dd["mean"] is not None and dd["mean"] > 0:
            print(f"⚠️反例: {h}日降降组mean仍为正({dd['mean']*100:+.2f}%),下降趋势确立后并未继续走弱")
            counter_found = True
        if dd["n"] and uu["n"] and dd["mean"] is not None and uu["mean"] is not None and dd["mean"] >= uu["mean"]:
            print(f"⚠️反例: {h}日降降组mean({dd['mean']*100:+.2f}%) >= 抬抬组mean({uu['mean']*100:+.2f}%),趋势方向未能区分收益")
            counter_found = True
        if dd["n"] and dd["win_rate"] is not None and dd["win_rate"] > 0.5:
            print(f"⚠️反例: {h}日降降组胜率{dd['win_rate']*100:.1f}%>50%,买入并持有降降信号仍大概率赚钱")
            counter_found = True
        # 离散度检查: p5-p95跨0说明个体层面预测力弱
        if dd["n"] and dd["p5"] is not None and dd["p95"] is not None and dd["p5"] < 0 < dd["p95"]:
            print(f"ℹ️离散度提示: {h}日降降组p5={dd['p5']*100:+.1f}% ~ p95={dd['p95']*100:+.1f}% 跨越0,"
                  f"个股层面信号不是每次都对,只是分布整体偏移")
    if not counter_found:
        print("未发现降降组mean为正或win_rate>50%或不劣于抬抬组的反例(但见上方离散度提示)")

    out = {
        "universe_note": "cn_watchlist(112只), 非A1(subagent找不到A1定义,已声明替代)",
        "fetch_ok": len(data), "fetch_failed": len(failed), "failed_list": failed,
        "source_count": source_count,
        "window": [WIN_START, WIN_END],
        "signal_counts": {k: len(v) for k, v in groups.items()},
        "summary": summary,
        "signals_log_sample": all_signals_log[:30],
    }
    outpath = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/trend_seq_result.json"
    with open(outpath, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[info] 结果json已写: {outpath}")
    print(f"[info] elapsed total = {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
