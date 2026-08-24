#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审判 T18 五道门中的 ①破前10日低 和 ③round-trip(峰值回撤)。

样本: sim-portfolio a_share account, 2026-06-24起平仓的全部交易, n=60 (FIFO聚合,
      与同批次B1审判-12%灾难线/破20日均线/破前10日低/不设止损时用的是同一frozen快照,
      agg_closed_trades_frozen.json, exit_date in [2026-06-24, 2026-08-24])
数据源(D12合规,禁yfinance):
  - 逐日OHLCV(原始未复权,用于门槛触发判定和PnL计算,与实际成交价同口径):
    price_data_raw_0401_0821.json, akshare stock_zh_a_daily(sina), 2026-04-01~08-21
    + today_quotes.json 2026-08-24盘中快照(腾讯qt.gtimg批量行情,13:14刷新)
  - qfq前复权收盘(仅用于"卖对率"远期收益核对,与sell_review.py/C2同口径以便直接
    对比36%/87%基准): qfq_close_series.json, akshare stock_zh_a_daily(sina,49/49成功)

规则定义(4条独立重放,互不依赖实际卖出原因/日期,与B1方法论一致):

  R3_10dlow (T18第①门,复用B1定义,本脚本重新独立跑一遍以便自证可复现):
    触发日 = 当日LOW首次 < 过去10个交易日(不含当日,对齐序列绝对index非仓位相对index,
    与B1一致)的最低LOW。按当日收盘价成交。

  RT_cost15 (T18第③门原始口径,"峰值+15%吐回成本" — 本次审判的靶子):
    stop = peak(持仓后最高HIGH,前一日为止,不含当日lookahead) - entry_price * 0.15
    即回撤的"金额"锚定在成本的15%,不是峰值的15% —— 涨得越多,以峰值计的实际
    容忍回撤比例越松;几乎没涨的票,容忍回撤比例反而逼近15%。这正是用户质疑的缺陷。

  RT_pct{10,15,20} (③门修正口径,与成本无关):
    stop = peak * (1 - X/100)。X∈{10,15,20}三档独立回测。

  R0_no_stop (不设止损基线,=B1的R4): 一路持有到序列最后一根bar(08-24盘中快照或
    08-21收盘),不构成"卖出",无误杀/卖对概念。

触发后取消: 若同一交易在多条规则下都未触发,以序列最后一根bar计价("held to today")。
本回测所有规则均独立于实际卖出日/原因重放,不是"实际卖出+规则复核"。

产出两套对比,回答③个核心问题:
  (a) 规则触发的PnL/PnL% vs 实际卖出的PnL/PnL% (delta = rule - actual, delta>0代表
      机械规则本可比当时判断卖得更好)
  (b) 规则触发后的"卖对率" (qfq口径, 卖出价为rule触发价, 远期N=5/10/20交易日收盘价
      对比: ret<0 记"卖对"), 与C2已知的 机械型20日36.4% / 判断型20日86.7% 基准对齐比较

⛔样本量n=60,单一regime(2026-06-24~08-24两个月),结论仅对该窗口负责,外推需谨慎。
"""
import json
import statistics as st
from collections import defaultdict

HERE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/gate13_roundtrip_10dlow"
REBOUND_N = 5  # 误杀检查窗口,与B1一致

agg = json.load(open(f"{HERE}/agg_closed_trades_frozen.json"))
price_data = json.load(open(f"{HERE}/price_data_raw_0401_0821.json"))
today_quotes = json.load(open(f"{HERE}/today_quotes.json"))
qfq_raw = json.load(open(f"{HERE}/qfq_close_series.json"))

qfq_close = {tk: v["rows"] for tk, v in qfq_raw.items()}  # {ticker: [[date, close], ...]}


def build_series(ticker):
    rows = price_data.get(ticker, [])
    series = [{"date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in rows]
    tq = today_quotes.get(ticker)
    if tq:
        date, open_, current, high, low, _ = tq
        series.append({"date": date, "open": open_, "high": high, "low": low, "close": current, "volume": None,
                        "note": "08-24盘中快照(13:14刷新),非官方收盘价"})
    series.sort(key=lambda x: x["date"])
    return series


def idx_after_entry(series, entry_date):
    for i, bar in enumerate(series):
        if bar["date"] > entry_date:
            return i
    return None


def sim_no_stop(series, i0, entry_price, shares):
    last = series[-1]
    exit_price = last["close"]
    return {"rule": "R0_no_stop", "triggered": False, "exit_date": last["date"], "exit_price": exit_price,
            "pnl": (exit_price - entry_price) * shares,
            "pnl_pct": (exit_price - entry_price) / entry_price * 100, "note": "held_to_today"}


def sim_10dlow(series, i0, entry_price, shares):
    for i in range(i0, len(series)):
        if i < 10:
            continue
        prior10_low = min(series[j]["low"] for j in range(i - 10, i))
        bar = series[i]
        if bar["low"] < prior10_low:
            exit_price = bar["close"]
            return {"rule": "R3_10dlow", "triggered": True, "exit_date": bar["date"], "exit_idx": i,
                    "exit_price": exit_price, "pnl": (exit_price - entry_price) * shares,
                    "pnl_pct": (exit_price - entry_price) / entry_price * 100, "prior10_low": prior10_low}
    last = series[-1]
    exit_price = last["close"]
    return {"rule": "R3_10dlow", "triggered": False, "exit_date": last["date"], "exit_price": exit_price,
            "pnl": (exit_price - entry_price) * shares,
            "pnl_pct": (exit_price - entry_price) / entry_price * 100, "note": "never_triggered_marked_today"}


def sim_roundtrip(series, i0, entry_price, shares, retrace_pct, cost_based, rule_name):
    """No-lookahead: stop for day i is computed from peak as of end of day i-1.
    peak updates AFTER the trigger check using day i's high."""
    peak = entry_price
    for i in range(i0, len(series)):
        bar = series[i]
        if cost_based:
            stop = peak - entry_price * (retrace_pct / 100.0)
        else:
            stop = peak * (1 - retrace_pct / 100.0)
        if bar["low"] <= stop:
            exit_price = stop
            peak_gain_pct = (peak - entry_price) / entry_price * 100
            return {"rule": rule_name, "triggered": True, "exit_date": bar["date"], "exit_idx": i,
                    "exit_price": exit_price, "pnl": (exit_price - entry_price) * shares,
                    "pnl_pct": (exit_price - entry_price) / entry_price * 100,
                    "peak_at_trigger": round(peak, 4), "peak_gain_pct": round(peak_gain_pct, 2),
                    "genuine_giveback": peak_gain_pct >= 5.0}
        peak = max(peak, bar["high"])
    last = series[-1]
    exit_price = last["close"]
    peak_gain_pct = (peak - entry_price) / entry_price * 100
    return {"rule": rule_name, "triggered": False, "exit_date": last["date"], "exit_price": exit_price,
            "pnl": (exit_price - entry_price) * shares,
            "pnl_pct": (exit_price - entry_price) / entry_price * 100, "note": "never_triggered_marked_today",
            "peak_at_end": round(peak, 4), "peak_gain_pct": round(peak_gain_pct, 2)}


def check_false_positive(series, result, sell_price):
    if not result.get("triggered"):
        return False, False, 0
    exit_idx = result["exit_idx"]
    forward = series[exit_idx + 1: exit_idx + 1 + REBOUND_N]
    days_available = len(forward)
    if days_available < REBOUND_N:
        return False, False, days_available
    fp = any(bar["high"] > sell_price for bar in forward)
    return True, fp, days_available


def fwd_qfq_close(ticker, exit_date, n):
    """Mirror sell_review.py fwd_close(): first date >= exit_date, then +n trading days."""
    rows = qfq_close.get(ticker)
    if not rows:
        return None, None
    dates = [r[0] for r in rows]
    idx0 = None
    for i, d in enumerate(dates):
        if d >= exit_date:
            idx0 = i
            break
    if idx0 is None:
        return None, None
    idx_n = idx0 + n
    if idx_n >= len(dates):
        return None, None
    return rows[idx_n][0], rows[idx_n][1]


RULES = [
    ("R0_no_stop", lambda s, i, e, sh: sim_no_stop(s, i, e, sh)),
    ("R3_10dlow", lambda s, i, e, sh: sim_10dlow(s, i, e, sh)),
    ("RT_cost15", lambda s, i, e, sh: sim_roundtrip(s, i, e, sh, 15, True, "RT_cost15")),
    ("RT_pct10", lambda s, i, e, sh: sim_roundtrip(s, i, e, sh, 10, False, "RT_pct10")),
    ("RT_pct15", lambda s, i, e, sh: sim_roundtrip(s, i, e, sh, 15, False, "RT_pct15")),
    ("RT_pct20", lambda s, i, e, sh: sim_roundtrip(s, i, e, sh, 20, False, "RT_pct20")),
]

results = defaultdict(list)
missing_data_tickers = set()

for trade in agg:
    ticker = trade["ticker"]
    series = build_series(ticker)
    if not series:
        missing_data_tickers.add(ticker)
        continue
    entry_date = trade["entry_date_anchor"]
    entry_price = trade["avg_entry_price"]
    shares = trade["shares"]
    i0 = idx_after_entry(series, entry_date)
    if i0 is None:
        missing_data_tickers.add(ticker)
        continue

    for rule_name, fn in RULES:
        r = fn(series, i0, entry_price, shares)
        r["ticker"] = ticker
        r["name"] = trade["name"]
        r["entry_date"] = entry_date
        r["entry_price"] = entry_price
        r["shares"] = shares
        r["actual_exit_date"] = trade["exit_date"]
        r["actual_exit_price"] = trade["exit_price"]
        r["actual_pnl"] = trade["actual_pnl"]
        r["actual_pnl_pct"] = trade["actual_pnl_pct"]
        r["delta_pnl_vs_actual"] = round(r["pnl"] - trade["actual_pnl"], 2)
        r["delta_pnl_pct_vs_actual"] = round(r["pnl_pct"] - trade["actual_pnl_pct"], 3)
        r["rule_beats_actual"] = r["pnl"] > trade["actual_pnl"]

        if rule_name != "R0_no_stop":
            elig, fp, days_avail = check_false_positive(series, r, r["exit_price"])
            r["fp_eligible"] = elig
            r["fp_false_positive"] = fp
            r["fp_days_available"] = days_avail

        if r.get("triggered"):
            for n in (5, 10, 20):
                fd, fc = fwd_qfq_close(ticker, r["exit_date"], n)
                if fc is not None:
                    ret = (fc - r["exit_price"]) / r["exit_price"] * 100
                    r[f"fwd{n}_date"] = fd
                    r[f"fwd{n}_close_qfq"] = round(fc, 3)
                    r[f"fwd{n}_ret_pct"] = round(ret, 2)
                else:
                    r[f"fwd{n}_date"] = None
                    r[f"fwd{n}_close_qfq"] = None
                    r[f"fwd{n}_ret_pct"] = None

        results[rule_name].append(r)

print("missing_data_tickers:", missing_data_tickers)


def pctile(sorted_data, p):
    if not sorted_data:
        return None
    if len(sorted_data) == 1:
        return sorted_data[0]
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def summarize_pnl(rule_results):
    pnls = [r["pnl"] for r in rule_results]
    n = len(pnls)
    sp = sorted(pnls)
    triggered = [r for r in rule_results if r.get("triggered")]
    eligible = [r for r in triggered if r.get("fp_eligible")]
    fp_count = sum(1 for r in eligible if r["fp_false_positive"])
    deltas = [r["delta_pnl_vs_actual"] for r in rule_results]
    sd = sorted(deltas)
    beat_actual = sum(1 for r in rule_results if r["rule_beats_actual"])
    genuine = [r for r in triggered if r.get("genuine_giveback") is True]
    return {
        "n": n,
        "total_pnl": round(sum(pnls), 2), "mean_pnl": round(st.mean(pnls), 2),
        "median_pnl": round(st.median(pnls), 2),
        "pnl_p5": round(pctile(sp, 0.05), 2), "pnl_p95": round(pctile(sp, 0.95), 2),
        "win_rate_pct": round(100 * sum(1 for p in pnls if p > 0) / n, 1),
        "trigger_count": len(triggered), "trigger_rate_pct": round(100 * len(triggered) / n, 1),
        "fp_eligible_n": len(eligible), "fp_count": fp_count,
        "fp_rate_pct": round(100 * fp_count / len(eligible), 1) if eligible else None,
        "vs_actual_mean_delta": round(st.mean(deltas), 2), "vs_actual_median_delta": round(st.median(deltas), 2),
        "vs_actual_delta_p5": round(pctile(sd, 0.05), 2), "vs_actual_delta_p95": round(pctile(sd, 0.95), 2),
        "vs_actual_rule_beats_actual_rate_pct": round(100 * beat_actual / n, 1),
        "genuine_giveback_n_of_triggered": len(genuine), "genuine_giveback_pct_of_triggered":
            round(100 * len(genuine) / len(triggered), 1) if triggered else None,
    }


def summarize_sellright(rule_results):
    """卖对率, mirrors sell_review.py / C2 methodology exactly (qfq fwd close, win = ret<0)."""
    triggered = [r for r in rule_results if r.get("triggered")]
    out = {"n_triggered": len(triggered)}
    for n in (5, 10, 20):
        vals = [r[f"fwd{n}_ret_pct"] for r in triggered if r.get(f"fwd{n}_ret_pct") is not None]
        n_missing = len(triggered) - len(vals)
        entry = {"n": len(vals), "n_missing_insufficient_time": n_missing}
        if vals:
            sv = sorted(vals)
            entry["mean_ret_pct"] = round(st.mean(vals), 2)
            entry["median_ret_pct"] = round(st.median(vals), 2)
            entry["sell_right_rate_pct"] = round(100 * sum(1 for v in vals if v < 0) / len(vals), 1)
            entry["p5"] = round(pctile(sv, 0.05), 2)
            entry["p95"] = round(pctile(sv, 0.95), 2)
        out[f"horizon_{n}d"] = entry
    return out


summary_pnl = {rule: summarize_pnl(results[rule]) for rule, _ in RULES}
summary_sellright = {rule: summarize_sellright(results[rule]) for rule, _ in RULES if rule != "R0_no_stop"}

print("\n=== PnL / vs-actual summary ===")
print(json.dumps(summary_pnl, ensure_ascii=False, indent=2))
print("\n=== 卖对率 summary (qfq, win=ret<0) ===")
print(json.dumps(summary_sellright, ensure_ascii=False, indent=2))

json.dump({k: v for k, v in results.items()}, open(f"{HERE}/gate13_full_results.json", "w"),
           ensure_ascii=False, indent=2, default=str)
json.dump(summary_pnl, open(f"{HERE}/gate13_summary_pnl.json", "w"), ensure_ascii=False, indent=2)
json.dump(summary_sellright, open(f"{HERE}/gate13_summary_sellright.json", "w"), ensure_ascii=False, indent=2)
print("\nsaved: gate13_full_results.json, gate13_summary_pnl.json, gate13_summary_sellright.json")
