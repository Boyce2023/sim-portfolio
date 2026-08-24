#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
复盘v2(修正版): 2026-06-24以后所有a_share卖出记录的事后正确性
修正原因: v1(sell_review.py)用 adjust="qfq" 拉远期收盘价, 但qfq(前复权)以"今天"(08-24)为基准
向前调整历史价格以消除除权除息造成的跳空。多只标的(如紫金矿业601899, 06-26和08-13两次除权除息)
在卖出日到今天之间发生分红,导致qfq序列的t0收盘价与trade_log里记录的真实成交价sell_price存在
系统性缺口(实测紫金矿业缺口约2.7%, 由两次分红共计约0.8元/股造成)。脚本却拿"未调整的真实成交价
sell_price"去除以"调整过的qfq远期收盘价", 两个口径不一致, 引入方向不定但量级可达1-5pp的偏差。
修正: 改用 adjust=""(不复权, 原始成交价)全程一致, t0直接用trade_log里真实成交价sell_price做基准,
远期收盘价也用不复权序列——两端口径统一,不存在缺口问题。价格返回的是"纯价格变动"不含分红再投资,
和v1一样都不含分红收益, 但至少内部口径自洽。
数据源: akshare stock_zh_a_daily(新浪源, adjust="") + stock_zh_index_daily(沪深300对照组, 原始点位)
禁yfinance(D12铁律)
"""
import json
import time
import sys
import re
import statistics as stats
import akshare as ak

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
PORTFOLIO_STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"

def to_sina_symbol(ticker):
    return ("sh" + ticker) if ticker.startswith("6") else ("sz" + ticker)

def fetch_stock(ticker, retries=3):
    sym = to_sina_symbol(ticker)
    for i in range(retries):
        try:
            df = ak.stock_zh_a_daily(symbol=sym, start_date="20260101", end_date="20260824", adjust="")
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
    if df is None or df.empty:
        return None, None
    dates = df["date"].tolist()
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

def classify(reason):
    r = reason
    r_neg_stripped = re.sub(r"非[^，。、]{0,15}证伪", "", r)
    r_neg_stripped = re.sub(r"不是[^，。、]{0,15}证伪", "", r_neg_stripped)
    r_neg_stripped = re.sub(r"非[^，。、]{0,15}机会成本", "", r_neg_stripped)
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

    print("拉取个股日K(不复权/原始成交价)...")
    stock_data = {}
    fail = []
    for i, tk in enumerate(tickers):
        df = fetch_stock(tk)
        if df is None:
            print(f"  [FAIL] {tk} 数据拉取失败")
            fail.append(tk)
        else:
            print(f"  [{i+1}/{len(tickers)}] {tk}: {len(df)}行 {df['date'].iloc[0]}~{df['date'].iloc[-1]}")
        stock_data[tk] = df
        time.sleep(0.25)

    if fail:
        print(f"\n⛔ 拉取失败标的: {fail} -- 按铁律#1(完整数据), 这些标的的卖出记录将标记为数据不足,不纳入分类统计的完整性声明")

    print("拉取沪深300指数(对照组,原始点位)...")
    idx_df = fetch_index()

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
            "data_fetch_ok": df is not None,
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
            base_fd, base_fc = fwd_close(idx_df, sell_date, 0)
            ifd, ifc = fwd_close(idx_df, sell_date, n)
            if ifc is not None and base_fc is not None:
                idx_ret = (ifc - base_fc) / base_fc * 100
                rec[f"idx_fwd{n}_ret_pct"] = round(idx_ret, 2)
                rec[f"excess_fwd{n}_ret_pct"] = round(rec[f"fwd{n}_ret_pct"] - idx_ret, 2) if rec[f"fwd{n}_ret_pct"] is not None else None
            else:
                rec[f"idx_fwd{n}_ret_pct"] = None
                rec[f"excess_fwd{n}_ret_pct"] = None
        results.append(rec)

    json.dump(results, open(f"{OUTDIR}/sells_with_forward_v2_raw.json", "w"), ensure_ascii=False, indent=2)
    print(f"\n已写入 {OUTDIR}/sells_with_forward_v2_raw.json ({len(results)}条)")

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
                def pct(p, sv=sv):
                    if len(sv) == 1:
                        return sv[0]
                    k = (len(sv) - 1) * p
                    f = int(k); c = min(f + 1, len(sv) - 1)
                    return sv[f] if f == c else sv[f] + (sv[c] - sv[f]) * (k - f)
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

    json.dump(cat_stats, open(f"{OUTDIR}/category_stats_v2_raw.json", "w"), ensure_ascii=False, indent=2)
    print(f"已写入 {OUTDIR}/category_stats_v2_raw.json")

    print("\n=== 分类统计摘要(v2/不复权修正版) ===")
    for cat, cs in sorted(cat_stats.items(), key=lambda x: -x[1]["n_total"]):
        print(f"\n[{cat}] n_total={cs['n_total']}")
        for n in (5, 10, 20):
            e = cs[f"horizon_{n}d"]
            if e["n"] == 0:
                print(f"  {n}日: n=0(缺{e['n_missing_insufficient_time']})")
                continue
            print(f"  {n}日: n={e['n']}(缺{e['n_missing_insufficient_time']}) 均值={e.get('mean_ret_pct')}% 中位={e.get('median_ret_pct')}% 胜率={e.get('win_rate_pct')}% p5={e.get('p5')}% p95={e.get('p95')}% stdev={e.get('stdev')} | 超额vs沪深300均值={e.get('mean_excess_vs_hs300_pct')}%")

if __name__ == "__main__":
    main()
