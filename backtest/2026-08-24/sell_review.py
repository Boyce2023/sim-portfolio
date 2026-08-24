#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复盘: 2026-06-24 以后所有 a_share 卖出记录的事后正确性
数据源: akshare stock_zh_a_daily (新浪源, qfq复权) + stock_zh_index_daily (沪深300对照组)
禁yfinance (D12铁律)
输出: sells_with_forward.json (逐笔明细) + category_stats.json (分类统计)
"""
import json
import time
import sys
import akshare as ak
import pandas as pd

TODAY = "2026-08-24"
OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
PORTFOLIO_STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"

def to_sina_symbol(ticker):
    if ticker.startswith("6"):
        return "sh" + ticker
    else:
        return "sz" + ticker

def fetch_stock(ticker, retries=3):
    sym = to_sina_symbol(ticker)
    for i in range(retries):
        try:
            df = ak.stock_zh_a_daily(symbol=sym, start_date="20260101", end_date="20260824", adjust="qfq")
            df["date"] = df["date"].astype(str)
            return df[["date", "close"]].reset_index(drop=True)
        except Exception as e:
            print(f"  [WARN] {ticker} attempt {i+1} failed: {e}", file=sys.stderr)
            time.sleep(1)
    return None

def fetch_index():
    for i in range(3):
        try:
            df = ak.stock_zh_index_daily(symbol="sh000300")
            df["date"] = df["date"].astype(str)
            return df[["date", "close"]].reset_index(drop=True)
        except Exception as e:
            print(f"  [WARN] index attempt {i+1} failed: {e}", file=sys.stderr)
            time.sleep(1)
    return None

def fwd_close(df, sell_date, n):
    """找到sell_date在df中的位置(或其后第一个交易日), 取其后第n个交易日的close. 找不到返回None."""
    if df is None or df.empty:
        return None, None
    dates = df["date"].tolist()
    # 找到 >= sell_date 的第一个交易日索引(卖出当天或之后最近交易日)
    idx0 = None
    for i, d in enumerate(dates):
        if d >= sell_date:
            idx0 = i
            break
    if idx0 is None:
        return None, None
    idx_n = idx0 + n
    if idx_n >= len(dates):
        return None, None
    return dates[idx_n], float(df.loc[idx_n, "close"])

import re

def classify(reason):
    r = reason
    # 去否定化: "非thesis证伪"/"非个股thesis证伪"/"去重非证伪"/"非机会成本门触发"等负向表述
    # 会被子串匹配误判为命中该关键词, 必须先剥离否定从句再匹配"证伪"/"机会成本"
    r_neg_stripped = re.sub(r"非[^，。、]{0,15}证伪", "", r)
    r_neg_stripped = re.sub(r"不是[^，。、]{0,15}证伪", "", r_neg_stripped)
    r_neg_stripped = re.sub(r"非[^，。、]{0,15}机会成本", "", r_neg_stripped)

    # 优先级顺序: "用户直接指令"是最不含糊的程序性标记(整批清仓重来,非个股判断),
    # 排在最前面, 防止其冗长说明文字里后段出现的其他关键词(如"第6道机会成本门已加"这类
    # 描述系统新规则的文字, 而非本笔卖出的驱动原因)抢先命中导致误判。
    if ("用户令清仓重置" in r) or ("组合级重置" in r) or ("归零重来" in r) or ("用户直接指令" in r) or ("Buwen直接指令" in r):
        return "用户指令-组合重置"
    if "灾难线" in r:
        return "灾难线(T18第②门/硬止损)"
    if ("破前10日低" in r) or ("T18第①门" in r) or ("破位" in r) or ("破X1" in r) or ("破自主扳机线" in r):
        return "破位(T18第①门/X1趋势线)"
    if "证伪" in r_neg_stripped:
        return "thesis证伪"
    if ("T11止盈" in r) or ("兑现" in r) or ("止盈" in r):
        return "催化兑现/止盈"
    if ("集中度" in r) or ("超限" in r):
        return "集中度超限"
    if ("主beta" in r) or ("大beta" in r):
        return "主beta缺失/重构"
    if "机会成本" in r_neg_stripped:
        return "机会成本/换仓"
    if "全面重建" in r:
        return "全面重建清仓"
    if ("感受仓纠错" in r) or ("防守收敛" in r):
        return "感受仓纠错/防守收敛"
    if "残仓" in r:
        return "残仓清理"
    if ("预设扳机" in r) or ("预设止损" in r) or ("预设线" in r) or ("硬止损" in r):
        return "预设扳机止损"
    if "个股利空" in r:
        return "个股利空"
    if "清仓重置" in r:
        return "清仓重置(扫描迭代)"
    return "其他/未分类"

def main():
    d = json.load(open(PORTFOLIO_STATE))
    tl = d["trade_log"]
    sells = [t for t in tl if t.get("account") == "a_share" and t.get("action") in ("sell", "reduce") and t.get("date", "") >= "2026-06-24"]
    print(f"总计卖出记录: {len(sells)}")

    tickers = sorted(set(t["ticker"] for t in sells))
    print(f"涉及标的: {len(tickers)}")

    print("拉取个股日K...")
    stock_data = {}
    for i, tk in enumerate(tickers):
        df = fetch_stock(tk)
        if df is None:
            print(f"  [FAIL] {tk} 数据拉取失败,跳过")
        else:
            print(f"  [{i+1}/{len(tickers)}] {tk}: {len(df)}行 {df['date'].iloc[0]}~{df['date'].iloc[-1]}")
        stock_data[tk] = df
        time.sleep(0.3)

    print("拉取沪深300指数(对照组)...")
    idx_df = fetch_index()
    if idx_df is not None:
        print(f"  沪深300: {len(idx_df)}行 {idx_df['date'].iloc[0]}~{idx_df['date'].iloc[-1]}")

    results = []
    for t in sells:
        tk = t["ticker"]
        sell_date = t["date"]
        sell_price = t["price"]
        df = stock_data.get(tk)

        rec = {
            "id": t["id"], "date": sell_date, "ticker": tk, "name": t.get("name", ""),
            "sell_price": sell_price, "reason": t.get("reason", ""),
            "category": classify(t.get("reason", "")),
        }

        for n in (5, 10, 20):
            fd, fc = fwd_close(df, sell_date, n)
            if fc is not None:
                ret = (fc - sell_price) / sell_price * 100
                rec[f"fwd{n}_date"] = fd
                rec[f"fwd{n}_close"] = round(fc, 3)
                rec[f"fwd{n}_ret_pct"] = round(ret, 2)
            else:
                rec[f"fwd{n}_date"] = None
                rec[f"fwd{n}_close"] = None
                rec[f"fwd{n}_ret_pct"] = None

            # 对照组: 沪深300同期
            ifd, ifc = fwd_close(idx_df, sell_date, n)
            # 需要卖出日当天/后第一个交易日指数收盘作为基准
            base_fd, base_fc = fwd_close(idx_df, sell_date, 0)
            if ifc is not None and base_fc is not None:
                idx_ret = (ifc - base_fc) / base_fc * 100
                rec[f"idx_fwd{n}_ret_pct"] = round(idx_ret, 2)
                if rec[f"fwd{n}_ret_pct"] is not None:
                    rec[f"excess_fwd{n}_ret_pct"] = round(rec[f"fwd{n}_ret_pct"] - idx_ret, 2)
                else:
                    rec[f"excess_fwd{n}_ret_pct"] = None
            else:
                rec[f"idx_fwd{n}_ret_pct"] = None
                rec[f"excess_fwd{n}_ret_pct"] = None

        results.append(rec)

    json.dump(results, open(f"{OUTDIR}/sells_with_forward.json", "w"), ensure_ascii=False, indent=2)
    print(f"\n已写入 {OUTDIR}/sells_with_forward.json ({len(results)}条)")

    # ---- 分类统计 ----
    import statistics as stats
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    cat_stats = {}
    for cat, items in by_cat.items():
        cat_stats[cat] = {"n_total": len(items)}
        for n in (5, 10, 20):
            vals = [r[f"fwd{n}_ret_pct"] for r in items if r[f"fwd{n}_ret_pct"] is not None]
            excess_vals = [r[f"excess_fwd{n}_ret_pct"] for r in items if r.get(f"excess_fwd{n}_ret_pct") is not None]
            n_missing = len(items) - len(vals)
            entry = {"n": len(vals), "n_missing_insufficient_time": n_missing}
            if vals:
                sv = sorted(vals)
                def pct(p):
                    if len(sv) == 1:
                        return sv[0]
                    k = (len(sv) - 1) * p
                    f = int(k)
                    c = min(f + 1, len(sv) - 1)
                    if f == c:
                        return sv[f]
                    return sv[f] + (sv[c] - sv[f]) * (k - f)
                entry["mean_ret_pct"] = round(stats.mean(vals), 2)
                entry["median_ret_pct"] = round(stats.median(vals), 2)
                entry["win_rate_pct"] = round(100 * sum(1 for v in vals if v < 0) / len(vals), 1)
                entry["p5"] = round(pct(0.05), 2)
                entry["p95"] = round(pct(0.95), 2)
                entry["stdev"] = round(stats.pstdev(vals), 2) if len(vals) > 1 else None
            if excess_vals:
                entry["mean_excess_vs_hs300_pct"] = round(stats.mean(excess_vals), 2)
                entry["win_rate_excess_pct"] = round(100 * sum(1 for v in excess_vals if v < 0) / len(excess_vals), 1)
            cat_stats[cat][f"horizon_{n}d"] = entry

    json.dump(cat_stats, open(f"{OUTDIR}/category_stats.json", "w"), ensure_ascii=False, indent=2)
    print(f"已写入 {OUTDIR}/category_stats.json")

    # ---- 打印摘要 ----
    print("\n=== 分类统计摘要 (win_rate = 卖后N日价格低于卖出价的比例, 即'卖对'比例) ===")
    for cat, cs in sorted(cat_stats.items(), key=lambda x: -x[1]["n_total"]):
        print(f"\n[{cat}] n_total={cs['n_total']}")
        for n in (5, 10, 20):
            e = cs[f"horizon_{n}d"]
            if e["n"] == 0:
                print(f"  {n}日: n=0 (全部数据不足,missing={e['n_missing_insufficient_time']})")
                continue
            print(f"  {n}日: n={e['n']}(缺{e['n_missing_insufficient_time']}) 均值={e.get('mean_ret_pct')}% 中位={e.get('median_ret_pct')}% 胜率={e.get('win_rate_pct')}% p5={e.get('p5')}% p95={e.get('p95')}% | 超额vs沪深300均值={e.get('mean_excess_vs_hs300_pct')}%")

if __name__ == "__main__":
    main()
