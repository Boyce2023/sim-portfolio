#!/usr/bin/env python3
"""
验证假设: 股价相对MA20/MA60的位置, 比"距60日高点回撤幅度"(等价于"距成本-12%"这类
锚定成本价的指标, 在universe层面用"距60日高点回撤"代替, 因为universe本身没有个体成本价)
对后续收益的预测力更强。

universe口径(A1)说明:
  本次任务提示词写"universe同A1", 但本session/本次调用未直接收到A1的定义文件。
  本目录(backtest/2026-08-24/)同批次落盘的另外两个脚本
  (backtest_kfjlr_flip.py 文件头 + trend_seq_vs_cost_stop.py 文件头) 都独立得出同一结论:
  universe = 沪深300+中证500成分股(当前成分, ak.index_stock_cons), 去重, n≈717,
  backtest_kfjlr_flip.py 的表述最直接("股票池: 沪深300+中证500成分股, 去重后作为universe"),
  两个sibling脚本互相印证, 本脚本采用同一定义以保证同批结果口径一致、可互相比对。
  ⚠️这是基于同批产出的推断, 非收到确认的A1原始定义, 已明确标注。

数据源: akshare(ak.index_stock_cons 取成分股) + 腾讯 web.ifzq.gtimg.cn/appstock/app/fqkline/get
  (qfq前复权日线), 失败重试1次后换本地 ak CLI(新浪源, 不复权)兜底。全部请求 timeout=8s。
  不用yfinance(D12铁律, A股禁yfinance)。

窗口: t∈[2026-06-24, 2026-08-24]。今天=2026-08-24(数据cutoff), 更晚没有前向收益可算。
  h=40的前向收益只有窗口最前若干个交易日才有完整40个交易日之后的真实数据, 窗口越靠后的
  t, h=40可用样本越少 —— 这是"今天就是2026-08-24"的硬约束, 不是数据缺失, 报告里会显式
  给出每个(metric,horizon)组合的 n_dates(覆盖的不同交易日数), h=40覆盖薄的分析降级为
  方向性提示。

方法:
  每只股票每个交易日t(该股自身交易日序列, 不跨股票对齐日历):
    - pos_ma20 = Close[t]/MA20[t] - 1   (MA20/MA60用rolling mean, min_periods=满窗口)
    - pos_ma60 = Close[t]/MA60[t] - 1
    - dd60     = Close[t]/Rolling60Max(High)[t] - 1  (恒<=0, "距60日高点回撤幅度")
    - fwd_h    = Close[t+h]/Close[t] - 1, h=5/20/40 (t+h按该股自身序列位移, 非自然日;
                 数据不足右截断为NaN, 不外推不填补)
  分桶: MA位置(<-10% / -10~0% / 0~10% / >10%); dd60(<-30% / -30~-20% / -20~-10% /
       -10~-5% / -5~0%)。每桶算 n / n_dates / mean / median / win_rate / p5 / p95。
  信息量对比两把尺子:
    (a) 分桶间收益的单调性与极差(spread)
    (b) 连续值与前瞻收益的Spearman秩相关(IC), 全panel算, n<30标注不显著/不给结论
  主动找反例: 三个指标(pos_ma20/pos_ma60/dd60)本身的相关性矩阵(高共线=测的是同一件事,
  不是"谁更强"而是"两把尺子量同一根木头"); h=40覆盖天数; 反直觉的桶(如极端回撤桶反而
  正收益)一律列出不隐藏。

落盘: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/ma_vs_drawdown_hs300zz500.py
"""
import json
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
AK_CLI = "/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"
FETCH_START = "2026-03-01"   # 早于窗口起点2026-06-24约80个交易日, 给MA60留足回看
FETCH_END   = "2026-08-24"
WIN_START   = "2026-06-24"
WIN_END     = "2026-08-24"
HORIZONS    = (5, 20, 40)
TIMEOUT     = 8

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 200)


def load_universe():
    import akshare as ak
    hs300 = ak.index_stock_cons(symbol="000300")
    zz500 = ak.index_stock_cons(symbol="000905")
    codes = pd.concat([hs300["品种代码"], zz500["品种代码"]]).astype(str).str.zfill(6)
    codes = sorted(codes.drop_duplicates().tolist())
    return codes


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
        bars.append({"date": r[0], "close": float(r[2]), "high": float(r[3]),
                      "low": float(r[4]), "volume": float(r[5])})
    bars.sort(key=lambda x: x["date"])
    return bars


def fetch_ak_fallback(code):
    out = subprocess.run([AK_CLI, "kline", code, "140", "--json"],
                          capture_output=True, text=True, timeout=TIMEOUT).stdout
    data = json.loads(out)
    bars = []
    for r in data:
        try:
            bars.append({"date": r["day"], "close": float(r["close"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "volume": float(r["volume"])})
        except Exception:
            continue
    bars.sort(key=lambda x: x["date"])
    return [b for b in bars if FETCH_START <= b["date"] <= FETCH_END]


def fetch_one(code):
    try:
        return code, fetch_tencent(code), "tencent_qfq", None
    except Exception as e1:
        try:
            bars = fetch_ak_fallback(code)
            if len(bars) < 60:
                raise RuntimeError(f"fallback too short n={len(bars)}")
            return code, bars, "ak_sina_noqfq_fallback", None
        except Exception as e2:
            return code, None, None, f"tencent_fail={e1} | ak_fallback_fail={e2}"


def bucket_ma_pos(x):
    if pd.isna(x):
        return np.nan
    if x < -0.10:
        return "1:<-10%"
    if x < 0:
        return "2:-10~0%"
    if x < 0.10:
        return "3:0~10%"
    return "4:>10%"


def bucket_dd60(x):
    if pd.isna(x):
        return np.nan
    if x < -0.30:
        return "1:<-30%"
    if x < -0.20:
        return "2:-30~-20%"
    if x < -0.10:
        return "3:-20~-10%"
    if x < -0.05:
        return "4:-10~-5%"
    return "5:-5~0%"


def summarize_bucket(sub, fwd_col):
    v = sub[fwd_col].dropna()
    n = len(v)
    if n == 0:
        return pd.Series({"n": 0, "n_dates": 0, "mean": np.nan, "median": np.nan,
                           "win_rate": np.nan, "p5": np.nan, "p95": np.nan})
    n_dates = sub.loc[v.index, "date"].nunique()
    return pd.Series({"n": n, "n_dates": n_dates, "mean": v.mean(), "median": v.median(),
                       "win_rate": (v > 0).mean(), "p5": v.quantile(0.05), "p95": v.quantile(0.95)})


def bucket_table(df, bucket_col, fwd_col):
    rows = []
    for b, sub in df.groupby(bucket_col, observed=True):
        s = summarize_bucket(sub, fwd_col)
        s["bucket"] = b
        rows.append(s)
    out = pd.DataFrame(rows).set_index("bucket").sort_index()
    return out[["n", "n_dates", "mean", "median", "win_rate", "p5", "p95"]]


def spearman_ic(df, metric_col, fwd_col):
    sub = df[[metric_col, fwd_col, "date"]].dropna()
    n = len(sub)
    if n < 30:
        return {"n": n, "n_dates": sub["date"].nunique(), "ic": np.nan}
    ic = sub[metric_col].corr(sub[fwd_col], method="spearman")
    return {"n": n, "n_dates": sub["date"].nunique(), "ic": ic}


def main():
    t0 = time.time()
    print("[step1] loading universe (hs300+zz500 via akshare) ...")
    universe = load_universe()
    print(f"[step1] universe n={len(universe)}")

    print("[step2] fetching daily qfq bars via tencent (24 threads, ak fallback) ...")
    data, failed, source_count = {}, [], {"tencent_qfq": 0, "ak_sina_noqfq_fallback": 0}
    with ThreadPoolExecutor(max_workers=24) as ex:
        futs = {ex.submit(fetch_one, c): c for c in universe}
        done = 0
        for fut in as_completed(futs):
            code, bars, src, err = fut.result()
            done += 1
            if bars is None:
                failed.append((code, err))
            else:
                data[code] = bars
                source_count[src] = source_count.get(src, 0) + 1
            if done % 150 == 0:
                print(f"[step2]   fetched {done}/{len(universe)}")
    print(f"[step2] done: ok={len(data)} failed={len(failed)} elapsed={time.time()-t0:.1f}s")
    print(f"[step2] source breakdown: {source_count}")
    if failed:
        print(f"[step2] failed sample (first 15): {failed[:15]}")

    print("[step3] computing indicators (MA20/MA60/dd60/fwd returns) ...")
    rows = []
    for code, bars in data.items():
        if len(bars) < 61:
            continue
        d = pd.DataFrame(bars)
        d["close"] = d["close"].astype(float)
        d["high"] = d["high"].astype(float)
        d["volume"] = d["volume"].astype(float)
        d = d[d["volume"] > 0].reset_index(drop=True)
        if len(d) < 61:
            continue
        d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
        d["ma60"] = d["close"].rolling(60, min_periods=60).mean()
        d["hh60"] = d["high"].rolling(60, min_periods=60).max()
        d["pos_ma20"] = d["close"] / d["ma20"] - 1
        d["pos_ma60"] = d["close"] / d["ma60"] - 1
        d["dd60"] = d["close"] / d["hh60"] - 1
        for h in HORIZONS:
            d[f"fwd_{h}"] = d["close"].shift(-h) / d["close"] - 1
        d["code"] = code
        rows.append(d)

    panel = pd.concat(rows, ignore_index=True)
    win = panel[(panel["date"] >= WIN_START) & (panel["date"] <= WIN_END)].copy()
    print(f"[step3] window rows(t in [{WIN_START},{WIN_END}]) = {len(win)}, "
          f"codes={win['code'].nunique()}, dates={win['date'].nunique()}")

    win["bkt_ma20"] = win["pos_ma20"].apply(bucket_ma_pos)
    win["bkt_ma60"] = win["pos_ma60"].apply(bucket_ma_pos)
    win["bkt_dd60"] = win["dd60"].apply(bucket_dd60)

    results, ic_rows = {}, []
    for h in HORIZONS:
        fwd_col = f"fwd_{h}"
        for metric_name, bkt_col, pos_col in (
            ("MA20位置", "bkt_ma20", "pos_ma20"),
            ("MA60位置", "bkt_ma60", "pos_ma60"),
            ("60日高点回撤", "bkt_dd60", "dd60"),
        ):
            tbl = bucket_table(win, bkt_col, fwd_col)
            results[(metric_name, h)] = tbl
            ic = spearman_ic(win, pos_col, fwd_col)
            ic_rows.append({"metric": metric_name, "horizon": h, **ic})
    ic_df = pd.DataFrame(ic_rows)

    corr_cols = ["pos_ma20", "pos_ma60", "dd60"]
    corr_mat = win[corr_cols].corr(method="spearman")

    print("\n" + "=" * 90)
    print("BUCKET TABLES (universe=hs300+zz500 n=%d)" % win["code"].nunique())
    print("=" * 90)
    for (metric_name, h), tbl in results.items():
        print(f"\n--- {metric_name} | forward {h}d return ---")
        print(tbl.round(4).to_string())

    print("\n" + "=" * 90)
    print("SPEARMAN IC (continuous metric vs forward return, pooled panel)")
    print("=" * 90)
    print(ic_df.round(4).to_string(index=False))

    print("\n" + "=" * 90)
    print("CROSS-CORRELATION AMONG THE THREE RAW METRICS (collinearity check)")
    print("=" * 90)
    print(corr_mat.round(3).to_string())

    # counter-evidence scan
    print("\n" + "=" * 90)
    print("反例扫描(主动找不支持假设的证据)")
    print("=" * 90)
    counter = []
    for (metric_name, h), tbl in results.items():
        means = tbl["mean"].dropna()
        if len(means) >= 2:
            # monotonicity check across sorted bucket index (bucket labels already sorted asc)
            vals = means.values
            is_mono_inc = all(vals[i] <= vals[i+1] for i in range(len(vals)-1))
            is_mono_dec = all(vals[i] >= vals[i+1] for i in range(len(vals)-1))
            if not (is_mono_inc or is_mono_dec):
                counter.append(f"{metric_name} h={h}: 分桶mean非单调({[round(v,4) for v in vals]})")
    for h in HORIZONS:
        n_dates_40 = ic_df[(ic_df["horizon"] == h)]["n_dates"].tolist()
    for c in counter:
        print(f"⚠️ {c}")
    if not counter:
        print("未发现分桶非单调的反例(所有metric×horizon分桶mean均单调)")
    if abs(corr_mat.loc["pos_ma60", "dd60"]) > 0.7:
        print(f"⚠️ pos_ma60 与 dd60 的Spearman相关系数={corr_mat.loc['pos_ma60','dd60']:.3f}, "
              f"高度共线 —— 二者很可能在量同一件事(距近期高点的距离), 不能简单说'谁的信息量更大'")

    win.to_csv(f"{OUT_DIR}/panel_raw_hs300zz500.csv.gz", index=False, compression="gzip")
    ic_df.to_csv(f"{OUT_DIR}/ic_summary_hs300zz500.csv", index=False)
    corr_mat.to_csv(f"{OUT_DIR}/metric_crosscorr_hs300zz500.csv")
    with pd.ExcelWriter(f"{OUT_DIR}/bucket_tables_hs300zz500.xlsx") as xw:
        for (metric_name, h), tbl in results.items():
            sheet = f"{metric_name}_{h}d"[:31]
            tbl.to_excel(xw, sheet_name=sheet)
    with open(f"{OUT_DIR}/failed_fetch_hs300zz500.json", "w") as f:
        json.dump([{"code": c, "err": e} for c, e in failed], f, ensure_ascii=False, indent=2)

    print(f"\n[done] elapsed={time.time()-t0:.1f}s")
    print(f"Saved: {OUT_DIR}/panel_raw_hs300zz500.csv.gz")
    print(f"Saved: {OUT_DIR}/ic_summary_hs300zz500.csv")
    print(f"Saved: {OUT_DIR}/metric_crosscorr_hs300zz500.csv")
    print(f"Saved: {OUT_DIR}/bucket_tables_hs300zz500.xlsx")
    print(f"Saved: {OUT_DIR}/failed_fetch_hs300zz500.json")


if __name__ == "__main__":
    main()
