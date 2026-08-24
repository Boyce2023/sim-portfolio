#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证假设: 扣非净利同比增速"由正转负"是有效的卖出信号

口径说明(必读):
- 股票池: 沪深300 + 中证500 成分股(当前成分, ak.index_stock_cons), 去重后作为universe。
- 财务数据: ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期"), 直接读取
  该接口给出的"扣非净利润同比增长率"列(THS已算好的YoY, 不再自算)。
- "上期"/"本期": 该股票财务序列里按报告期排序后相邻的两期(几乎全部是 2026-03-31 vs 2026-06-30,
  因为回测窗口2026-06-24~2026-08-24内, 唯一大批量落在窗口内的实际披露是2026年中报;
  2026年报/2025年报/2026一季报的实际披露日都早于窗口起点, 已提前验证, 详见脚本末尾"窗口口径验证"注释)。
- 信号日: 用 ak.stock_report_disclosure(market="沪深京", period="2026半年报") 的"实际披露"列
  (巨潮资讯实际披露日, 不是预约披露日, 也不是period_end+60天近似 —— 经验证后者会把信号日
  推到2026-08-29, 晚于今天(数据cutoff 2026-08-24), 导致全员没有前向收益, 弃用该近似)。
- 只保留 实际披露 落在 [2026-06-24, 2026-08-24] 窗口内的股票 —— 这是任务给定的回测窗口,
  也是本脚本能拿到价格前向数据的硬约束(今天=2026-08-24, 更晚的信号没有前向收益可算)。
- 价格数据: 腾讯 web.ifzq.gtimg.cn/appstock/app/fqkline/get, qfq前复权, 索引 收=r[2] 高=r[3] 低=r[4] 量=r[5]。
- T0 = 信号日(或信号日之后第一个交易日, 因为披露多在盘后/开盘前, 用披露当日或次日收盘价都不精确,
  这里用"信号日当天若是交易日则当天收盘, 否则信号日之后第一个交易日收盘"作为T0, 并在结果表里
  单独给出 t0_date 供复核)。
- 前向收益 = P(T0+N个交易日收盘) / P(T0收盘) - 1, N=5/20/40。
- 分组: treatment = 上期扣非净利同比>0 且 本期<0 (由正转负); control = 上期>0 且 本期仍>0。
  两组要求"上期"口径一致(都是上期为正), 只有本期正负不同, 这样对照才干净。
- 数据源全部用 akshare / 腾讯行情, 不用 yfinance(D12铁律, A股禁yfinance)。
- 不派生子agent, 全部在本进程内用 ThreadPoolExecutor 做I/O并发(不是多agent)。

运行:
    python3 backtest_kfjlr_flip.py
输出:
    - kfjlr_flip_signals.csv        : 逐票信号明细(报告期/披露日/prev growth/curr growth/分组)
    - kfjlr_flip_returns.csv        : 逐票前向收益明细(5/20/40交易日)
    - kfjlr_flip_summary.json       : 分组统计汇总(n/mean/median/winrate/p5/p95)
    - 终端打印: 一句话结论 + 数据表 + 反例
"""

import json
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import akshare as ak
import numpy as np
import pandas as pd
import requests

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
WIN_START = "2026-06-24"
WIN_END = "2026-08-24"
TODAY = "2026-08-24"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pct_to_float(x):
    """把 '213.36%' / '-77.07%' / '--' / '不适用' / NaN 统一转成float或np.nan"""
    if x is None:
        return np.nan
    if isinstance(x, (int, float)):
        return float(x) if not pd.isna(x) else np.nan
    s = str(x).strip()
    if s in ("", "--", "nan", "None", "不适用", "NaN"):
        return np.nan
    s = s.replace("%", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return np.nan


def get_universe(mode="hs300_zz500"):
    """
    mode="hs300_zz500": 沪深300+中证500成分股(原始口径)
    mode="full_a_disclosed": 全A中"2026半年报实际披露落在窗口内"的股票(备用口径)
        —— 之所以启用备用口径: 本想用"全A按总市值筛前800只"(ak.stock_zh_a_spot_em,
        东财push2 spot接口), 但该接口在本机被代理挡死(ProxyError, 与D12记录的
        eastmoney push2his被挡是同一根因), 按铁律#4"失败立即换源不要重试"操作,
        换成"全A中实际已披露"作为更宽口径, 而不是死磕市值排序接口。
        这不是"全A", 是"全A的实际披露子集"(1710只), 口径已在结果里写明。
    """
    if mode == "hs300_zz500":
        hs300 = ak.index_stock_cons(symbol="000300")
        zz500 = ak.index_stock_cons(symbol="000905")
        codes = pd.concat([hs300["品种代码"], zz500["品种代码"]]).drop_duplicates().tolist()
        log(f"universe(hs300_zz500): hs300={len(hs300)} zz500={len(zz500)} dedup_total={len(codes)}")
        return codes
    elif mode == "full_a_disclosed":
        disc_map = get_disclosure_window()
        codes = list(disc_map.keys())
        log(f"universe(full_a_disclosed): {len(codes)} (全A中2026半年报实际披露落在窗口内的股票)")
        return codes
    else:
        raise ValueError(mode)


def get_disclosure_window():
    """2026半年报 实际披露 落在窗口内的股票代码->披露日"""
    disc = ak.stock_report_disclosure(market="沪深京", period="2026半年报")
    disc["实际披露"] = pd.to_datetime(disc["实际披露"], errors="coerce")
    disc_win = disc[
        (disc["实际披露"] >= WIN_START) & (disc["实际披露"] <= WIN_END)
    ].copy()
    return dict(zip(disc_win["股票代码"], disc_win["实际披露"]))


def fetch_financial(code):
    """返回 dict: prev_period, prev_growth, curr_period, curr_growth, ok/err"""
    try:
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按报告期")
        if df is None or df.empty:
            return {"code": code, "ok": False, "err": "empty_df"}
        df = df.sort_values("报告期").reset_index(drop=True)
        curr_rows = df[df["报告期"].astype(str) == "2026-06-30"]
        if curr_rows.empty:
            return {"code": code, "ok": False, "err": "no_2026-06-30_row"}
        curr_idx = curr_rows.index[-1]
        if curr_idx == 0:
            return {"code": code, "ok": False, "err": "no_prev_row"}
        prev_row = df.iloc[curr_idx - 1]
        curr_row = df.iloc[curr_idx]
        prev_growth = pct_to_float(prev_row.get("扣非净利润同比增长率"))
        curr_growth = pct_to_float(curr_row.get("扣非净利润同比增长率"))
        return {
            "code": code,
            "ok": True,
            "prev_period": str(prev_row.get("报告期")),
            "prev_growth": prev_growth,
            "curr_period": str(curr_row.get("报告期")),
            "curr_growth": curr_growth,
        }
    except Exception as e:
        return {"code": code, "ok": False, "err": f"{type(e).__name__}:{e}"}


def tencent_prefix(code):
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return "sh" + code
    else:
        return "sz" + code


def fetch_price(code, start="2026-06-15", end="2026-08-24"):
    """
    返回 DataFrame[date, close], qfq前复权日线。
    ⛔源切换记录: 最初用腾讯 web.ifzq.gtimg.cn/appstock/app/fqkline/get(任务里给的源),
    在跑 full_a_disclosed(715只并发)那一轮把腾讯WAF打了(501 waf.tencent.com/501page.html,
    连单发串行请求都被拦), 按铁律#4"失败立即换源不要重试", 改用 ak.stock_zh_a_daily
    (新浪源, 任务里列的备选源之一)。hs300_zz500那一轮(166只)是在腾讯被封之前跑的,
    用的还是腾讯源, 数据本身没问题, 不受此次切源影响。
    """
    sym = tencent_prefix(code)  # sina用同样的 sh600519/sz000001 格式
    try:
        df = ak.stock_zh_a_daily(
            symbol=sym,
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="qfq",
        )
        if df is None or df.empty:
            return None
        pdf = df[["date", "close"]].copy()
        pdf["date"] = pd.to_datetime(pdf["date"])
        pdf = pdf.sort_values("date").reset_index(drop=True)
        return pdf
    except Exception:
        return None


def forward_returns(price_df, signal_date, horizons=(5, 20, 40)):
    """T0 = signal_date当天(若是交易日)否则之后第一个交易日; 返回dict + t0_date"""
    if price_df is None or price_df.empty:
        return None
    sig = pd.Timestamp(signal_date)
    idx_ge = price_df.index[price_df["date"] >= sig]
    if len(idx_ge) == 0:
        return None
    t0_idx = idx_ge[0]
    t0_date = price_df.loc[t0_idx, "date"]
    t0_close = price_df.loc[t0_idx, "close"]
    out = {"t0_date": t0_date.strftime("%Y-%m-%d"), "t0_close": t0_close}
    n_rows = len(price_df)
    for h in horizons:
        tgt_idx = t0_idx + h
        if tgt_idx < n_rows:
            out[f"ret_{h}d"] = price_df.loc[tgt_idx, "close"] / t0_close - 1.0
            out[f"n_avail_{h}d"] = n_rows - 1 - t0_idx  # 实际可用的交易日数(用于诊断)
        else:
            out[f"ret_{h}d"] = np.nan
            out[f"n_avail_{h}d"] = n_rows - 1 - t0_idx
    return out


def main():
    import sys
    t_start = time.time()
    mode = sys.argv[1] if len(sys.argv) > 1 else "hs300_zz500"
    universe = get_universe(mode=mode)
    disc_map = get_disclosure_window()
    log(f"2026半年报 实际披露落在窗口内(全市场): {len(disc_map)}")

    eligible = [c for c in universe if c in disc_map]
    log(f"universe∩窗口内已披露 = {len(eligible)}")

    # ---- 1. 拉财务数据(并发) ----
    fin_results = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(fetch_financial, c): c for c in eligible}
        for i, fut in enumerate(as_completed(futs)):
            fin_results.append(fut.result())
            if (i + 1) % 50 == 0:
                log(f"  financial fetched {i+1}/{len(eligible)}")
    fin_df = pd.DataFrame(fin_results)
    log(f"financial fetch done: ok={fin_df['ok'].sum()} fail={(~fin_df['ok']).sum()} "
        f"elapsed={time.time()-t_start:.1f}s")

    ok_df = fin_df[fin_df["ok"]].copy()
    ok_df["signal_date"] = ok_df["code"].map(disc_map)

    treat = ok_df[(ok_df["prev_growth"] > 0) & (ok_df["curr_growth"] < 0)].copy()
    ctrl = ok_df[(ok_df["prev_growth"] > 0) & (ok_df["curr_growth"] > 0)].copy()
    log(f"treatment(由正转负) n={len(treat)}  control(仍为正) n={len(ctrl)}  "
        f"(其余{len(ok_df)-len(treat)-len(ctrl)}只: 上期非正或本期恰为0/缺失, 不进任一组)")

    treat["group"] = "treatment_turn_negative"
    ctrl["group"] = "control_stay_positive"
    sig_df = pd.concat([treat, ctrl], ignore_index=True)
    sig_df.to_csv(f"{OUTDIR}/kfjlr_flip_signals_{mode}.csv", index=False, encoding="utf-8-sig")
    log(f"signals saved -> kfjlr_flip_signals_{mode}.csv ({len(sig_df)} rows)")

    # ---- 2. 拉价格数据 + 算前向收益(并发) ----
    def process_one(row):
        code = row["code"]
        pdf = fetch_price(code)
        fr = forward_returns(pdf, row["signal_date"])
        rec = dict(row)
        if fr is None:
            rec["price_ok"] = False
            return rec
        rec["price_ok"] = True
        rec.update(fr)
        return rec

    ret_results = []
    rows = sig_df.to_dict("records")
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(process_one, r): r["code"] for r in rows}
        for i, fut in enumerate(as_completed(futs)):
            ret_results.append(fut.result())
            if (i + 1) % 50 == 0:
                log(f"  price/return fetched {i+1}/{len(rows)}")
    ret_df = pd.DataFrame(ret_results)
    ret_df.to_csv(f"{OUTDIR}/kfjlr_flip_returns_{mode}.csv", index=False, encoding="utf-8-sig")
    log(f"returns saved -> kfjlr_flip_returns_{mode}.csv ({len(ret_df)} rows) "
        f"price_ok={ret_df['price_ok'].sum()}/{len(ret_df)} elapsed={time.time()-t_start:.1f}s")

    # ---- 3. 汇总统计 ----
    def group_stats(df, horizon):
        col = f"ret_{horizon}d"
        s = df[col].dropna()
        n = len(s)
        if n == 0:
            return {"n": 0, "mean": None, "median": None, "winrate": None,
                    "p5": None, "p95": None}
        return {
            "n": int(n),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "winrate": float((s > 0).mean()),
            "p5": float(np.percentile(s, 5)),
            "p95": float(np.percentile(s, 95)),
        }

    summary = {}
    for h in (5, 20, 40):
        summary[f"{h}d"] = {
            "treatment": group_stats(ret_df[ret_df["group"] == "treatment_turn_negative"], h),
            "control": group_stats(ret_df[ret_df["group"] == "control_stay_positive"], h),
        }

    with open(f"{OUTDIR}/kfjlr_flip_summary_{mode}.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ---- 4. 打印 ----
    print("\n" + "=" * 78)
    print("汇总统计 (信号日=2026半年报实际披露日, 窗口2026-06-24~2026-08-24, T0=披露后首个交易日收盘)")
    print("=" * 78)
    for h in (5, 20, 40):
        t = summary[f"{h}d"]["treatment"]
        c = summary[f"{h}d"]["control"]
        print(f"\n--- {h}个交易日前向收益 ---")
        print(f"  treatment(转负): n={t['n']:>4}  mean={fmtpct(t['mean'])}  median={fmtpct(t['median'])}  "
              f"winrate={fmtpct(t['winrate'])}  p5~p95=[{fmtpct(t['p5'])}, {fmtpct(t['p95'])}]")
        print(f"  control  (仍正): n={c['n']:>4}  mean={fmtpct(c['mean'])}  median={fmtpct(c['median'])}  "
              f"winrate={fmtpct(c['winrate'])}  p5~p95=[{fmtpct(c['p5'])}, {fmtpct(c['p95'])}]")
        if t["n"] > 0 and c["n"] > 0:
            print(f"  mean差(treat-ctrl)  = {fmtpct(t['mean']-c['mean'])}")
            print(f"  median差(treat-ctrl)= {fmtpct(t['median']-c['median'])}")
            overlap = not (t["p95"] < c["p5"] or c["p95"] < t["p5"])
            print(f"  p5-p95区间是否重叠: {'是(离散度盖过均值差, 不显著)' if overlap else '否(两组分离)'}")

    # ---- 5. 反例(主动找,不只报支持假设的) ----
    print("\n" + "=" * 78)
    print("反例检查(treatment组里20日收益仍为正的, 即'转负'没跌反涨)")
    print("=" * 78)
    t20 = ret_df[(ret_df["group"] == "treatment_turn_negative") & ret_df["ret_20d"].notna()]
    counter = t20[t20["ret_20d"] > 0].sort_values("ret_20d", ascending=False)
    if len(counter) == 0:
        print("  (无: 该horizon样本量可能为0, 见上方n)")
    else:
        print(counter[["code", "curr_growth", "signal_date", "ret_20d"]].head(15).to_string(index=False))

    log(f"total elapsed={time.time()-t_start:.1f}s")
    return summary, ret_df


def fmtpct(x):
    if x is None:
        return "N/A"
    return f"{x*100:+.2f}%"


if __name__ == "__main__":
    main()
