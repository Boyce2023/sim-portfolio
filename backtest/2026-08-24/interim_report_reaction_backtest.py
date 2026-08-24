"""
中报披露后股价反应回测 (2026-08-24)
====================================
问题: 业绩好是否一定涨? "利好兑现"效应有多强? 持仓中报前后该怎么处理?

方法:
1. ak.stock_report_disclosure(period="2026半年报") 拿全A股实际披露日期 (实际披露不为空的记录)
2. ak.stock_yjbb_em / 本地缓存 yjbb_20260630.csv 拿净利润同比增长率 (注: 非严格"扣非", 见脚本内 LIMITATIONS)
3. 用同比增速在全样本内的百分位分三档(Miss/In-line/Beat)近似"预期" (用户任务书明确认可此近似)
4. ak.stock_zh_a_daily(新浪源, qfq前复权) 拉每只股票日线, 定位披露日前一交易日收盘为基准T-1
   计算 T-1→T+1 / T-1→T+5 / T-1→T+20 累计收益 (披露后1/5/20个交易日收益, 含公告日当天反应)
5. 同法拉 sh000001 上证指数同期收益做对照组(市场基准), 算超额收益
6. 输出: n / 均值 / 中位数 / 胜率 / 离散度(p5-p95), 分档 + 对照组同口径

窗口: 2026-06-24 ~ 2026-08-24 (今日), 仅单一regime, 结论不外推
数据源: akshare (禁yfinance, D12铁律)
"""
import akshare as ak
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import time
import sys

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/"
WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"
TODAY = "2026-08-24"

t_start = time.time()

def log(*a):
    print(f"[{time.time()-t_start:6.1f}s]", *a, file=sys.stderr, flush=True)

# ---------- Step 1: 披露日期 (已缓存) ----------
disc = pd.read_csv(OUTDIR + "report_disclosure_actual_h1_2026.csv", dtype={"股票代码": str})
disc["股票代码"] = disc["股票代码"].str.zfill(6)
disc["实际披露"] = pd.to_datetime(disc["实际披露"])
disc = disc[disc["实际披露"].notna()].copy()
disc = disc[(disc["实际披露"] >= WINDOW_START) & (disc["实际披露"] <= WINDOW_END)]
log("披露记录(窗口内):", len(disc))

# ---------- Step 2: 净利润同比增长(proxy, 非严格扣非) ----------
yjbb = pd.read_csv(OUTDIR + "yjbb_20260630.csv", dtype={"股票代码": str})
yjbb["股票代码"] = yjbb["股票代码"].str.zfill(6)
yjbb = yjbb[["股票代码", "净利润-同比增长", "营业总收入-同比增长"]].rename(
    columns={"净利润-同比增长": "np_yoy_pct", "营业总收入-同比增长": "rev_yoy_pct"}
)

merged = disc.merge(yjbb, on="股票代码", how="inner")
merged = merged[merged["np_yoy_pct"].notna()]
merged = merged.drop_duplicates(subset="股票代码")
log("披露+净利润增长率均有效:", len(merged))
FULL_POPULATION_N = len(merged)

# 用百分位排名分三档 (对极端值/inf稳健)
merged["np_rank_pct"] = merged["np_yoy_pct"].rank(pct=True)
def tier(p):
    if p <= 1/3:
        return "Miss(后1/3)"
    elif p <= 2/3:
        return "InLine(中1/3)"
    else:
        return "Beat(前1/3)"
merged["tier"] = merged["np_rank_pct"].apply(tier)
log("分档结果:", merged["tier"].value_counts().to_dict())

merged.to_csv(OUTDIR + "step2_merged_universe.csv", index=False)

# ---------- Step 2b: 分层随机抽样 (akshare底层mini_racer非线程安全, 多线程会FATAL crash;
#            改单线程顺序拉取, 需控制样本量在25分钟预算内完成. 抽样前已完成全population分档,
#            抽样按tier分层等比随机抽取, 非挑选支持结论的样本) ----------
SAMPLE_PER_TIER = 260
sampled = (
    merged.groupby("tier", group_keys=False)
    .apply(lambda g: g.sample(n=min(SAMPLE_PER_TIER, len(g)), random_state=42))
    .reset_index(drop=True)
)
log("分层抽样后样本量:", len(sampled), sampled["tier"].value_counts().to_dict())

# ---------- Step 3: 价格数据 (新浪源, 单线程顺序 -- akshare mini_racer多线程不安全) ----------
def code_to_symbol(code):
    if code.startswith(("60", "68", "9")):
        return "sh" + code
    elif code.startswith(("00", "30", "20")):
        return "sz" + code
    elif code.startswith(("8", "4")):
        return "bj" + code
    return None

def fetch_one(code):
    sym = code_to_symbol(code)
    if sym is None:
        return None
    try:
        df = ak.stock_zh_a_daily(symbol=sym, start_date="20260501", end_date="20260824", adjust="qfq")
        if df is None or len(df) == 0:
            return None
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "close"]].reset_index(drop=True)
    except Exception:
        return None

codes = sampled["股票代码"].unique().tolist()
INDEX_CODE = "sh000001"

import pickle
CACHE_PATH = OUTDIR + "price_map_cache.pkl"
price_map = {}
failed = []
if __import__("os").path.exists(CACHE_PATH):
    with open(CACHE_PATH, "rb") as f:
        cached = pickle.load(f)
    if set(codes).issubset(set(cached.keys())) or len(cached) >= len(codes) * 0.9:
        price_map = {c: cached[c] for c in codes if c in cached}
        log("命中价格缓存, 复用之前拉取结果, 跳过网络请求. 缓存命中:", len(price_map))
    else:
        log("缓存存在但不匹配当前样本, 重新拉取")

if not price_map:
    log("开始拉取价格(单线程顺序), 股票数:", len(codes))
    for i, c in enumerate(codes):
        df = fetch_one(c)
        if df is not None:
            price_map[c] = df
        else:
            failed.append(c)
        if (i + 1) % 100 == 0:
            log(f"  进度 {i+1}/{len(codes)}  elapsed={time.time()-t_start:.0f}s")
        if time.time() - t_start > 18 * 60:
            log("  接近时间预算上限(18min), 停止继续拉取, 已拉:", len(price_map))
            break
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(price_map, f)
    log("价格已缓存到磁盘:", CACHE_PATH)

log("价格拉取完成. 成功:", len(price_map), "失败:", len(failed))
merged = sampled  # 后续统计基于抽样样本

# 指数
idx_df = ak.stock_zh_index_daily(symbol=INDEX_CODE)
idx_df["date"] = pd.to_datetime(idx_df["date"])
idx_df = idx_df[(idx_df["date"] >= "2026-05-01") & (idx_df["date"] <= WINDOW_END)][["date", "close"]].reset_index(drop=True)
log("指数数据:", len(idx_df))

with open(OUTDIR + "step3_fetch_status.json", "w") as f:
    json.dump({"success": len(price_map), "failed": failed}, f, ensure_ascii=False, indent=2)

# ---------- Step 4: 计算 T-1 -> T+1/T+5/T+20 收益 ----------
def compute_returns(df, event_date):
    """df: date,close sorted; event_date: pd.Timestamp (实际披露日)
    T-1 = 披露日前最后一个交易日, 基准收盘价
    返回 dict: ret_1d/5d/20d (从T-1到T-1+1/5/20个交易日的累计收益), 以及可用天数标记
    """
    d = df.sort_values("date").reset_index(drop=True)
    before = d[d["date"] < event_date]
    if len(before) == 0:
        return None
    t_minus_1_idx = before.index[-1]
    base_price = d.loc[t_minus_1_idx, "close"]
    if base_price is None or base_price <= 0:
        return None
    out = {}
    for h, label in [(1, "ret_1d"), (5, "ret_5d"), (20, "ret_20d")]:
        target_idx = t_minus_1_idx + h
        if target_idx < len(d):
            out[label] = d.loc[target_idx, "close"] / base_price - 1
        else:
            out[label] = np.nan
    return out

records = []
for _, row in merged.iterrows():
    code = row["股票代码"]
    if code not in price_map:
        continue
    r = compute_returns(price_map[code], row["实际披露"])
    if r is None:
        continue
    idx_r = compute_returns(idx_df, row["实际披露"])
    rec = {
        "code": code, "name": row["股票简称"], "disclosure_date": str(row["实际披露"].date()),
        "np_yoy_pct": row["np_yoy_pct"], "rev_yoy_pct": row["rev_yoy_pct"], "tier": row["tier"],
        "np_rank_pct": row["np_rank_pct"],
        "ret_1d": r["ret_1d"], "ret_5d": r["ret_5d"], "ret_20d": r["ret_20d"],
    }
    if idx_r is not None:
        for h in ["ret_1d", "ret_5d", "ret_20d"]:
            rec[f"idx_{h}"] = idx_r[h]
            rec[f"excess_{h}"] = (rec[h] - idx_r[h]) if (rec[h] is not None and not pd.isna(rec[h]) and idx_r[h] is not None and not pd.isna(idx_r[h])) else np.nan
    records.append(rec)

res = pd.DataFrame(records)
res.to_csv(OUTDIR + "step4_event_returns_full.csv", index=False)
log("最终样本(有价格+收益数据):", len(res))

# ---------- Step 5: 分档统计 ----------
def stats_block(s):
    s = s.dropna()
    n = len(s)
    if n == 0:
        return dict(n=0, mean=np.nan, median=np.nan, win_rate=np.nan, p5=np.nan, p95=np.nan)
    return dict(
        n=n,
        mean=round(s.mean() * 100, 2),
        median=round(s.median() * 100, 2),
        win_rate=round((s > 0).mean() * 100, 1),
        p5=round(s.quantile(0.05) * 100, 2),
        p95=round(s.quantile(0.95) * 100, 2),
    )

summary = {}
horizons = ["ret_1d", "ret_5d", "ret_20d"]
excess_horizons = ["excess_ret_1d", "excess_ret_5d", "excess_ret_20d"]

for h in horizons:
    summary[h] = {}
    summary[h]["ALL(对照-全样本)"] = stats_block(res[h])
    for t in ["Beat(前1/3)", "InLine(中1/3)", "Miss(后1/3)"]:
        summary[h][t] = stats_block(res[res["tier"] == t][h])

for h in excess_horizons:
    if h in res.columns:
        summary[h] = {}
        summary[h]["ALL(对照-全样本)"] = stats_block(res[h])
        for t in ["Beat(前1/3)", "InLine(中1/3)", "Miss(后1/3)"]:
            summary[h][t] = stats_block(res[res["tier"] == t][h])

# 相关性 (业绩增速排名 vs 各期收益) - Spearman
from scipy.stats import spearmanr
corr = {}
for h in horizons + excess_horizons:
    if h in res.columns:
        sub = res[["np_rank_pct", h]].dropna()
        if len(sub) >= 10:
            rho, p = spearmanr(sub["np_rank_pct"], sub[h])
            corr[h] = dict(n=len(sub), spearman_rho=round(rho, 3), p_value=round(p, 4))

# 反例: Beat组里跌得最惨的, Miss组里涨得最好的 (T+5)
beat_worst = res[res["tier"] == "Beat(前1/3)"].dropna(subset=["ret_5d"]).nsmallest(8, "ret_5d")[
    ["code", "name", "np_yoy_pct", "ret_1d", "ret_5d", "ret_20d"]]
miss_best = res[res["tier"] == "Miss(后1/3)"].dropna(subset=["ret_5d"]).nlargest(8, "ret_5d")[
    ["code", "name", "np_yoy_pct", "ret_1d", "ret_5d", "ret_20d"]]

# 持仓个股 case study
PORTFOLIO_TICKERS = {
    "600549": "厦门钨业(A,深研埋伏)", "600111": "北方稀土(A-,深研埋伏)",
    "603259": "药明康德(A,深研埋伏)", "600312": "平高电气(A,深研埋伏)",
}
portfolio_cases = res[res["code"].isin(PORTFOLIO_TICKERS.keys())][
    ["code", "name", "disclosure_date", "np_yoy_pct", "tier", "ret_1d", "ret_5d", "ret_20d",
     "excess_ret_1d", "excess_ret_5d", "excess_ret_20d"]]

final_out = {
    "meta": {
        "window": f"{WINDOW_START} ~ {WINDOW_END}",
        "n_disclosed_in_window": len(disc),
        "n_with_growth_data_full_population": FULL_POPULATION_N,
        "n_sampled_for_price_fetch": len(sampled),
        "sampling_method": "分层随机抽样(random_state=42), 每档目标260只(全population不足则取全部), 抽样前已完成全population的tier分档",
        "n_with_price_data_final": len(res),
        "price_fetch_failed": len(failed),
        "run_time_sec": round(time.time() - t_start, 1),
        "LIMITATION": "净利润同比增长率(净利润-净利润, akshare stock_yjbb_em)非严格扣非归母净利润同比增速。"
                       "实测恒瑞医药(600276): 净利润同比+0.34% vs 用户报告扣非-12.71%, 符号方向相反(一次性损益拉高净利润)。"
                       "厦门钨业(600549): 净利润同比+127.04% vs 用户报告扣非+122.81%, 较接近。"
                       "结论: 净利润YoY可作粗略近似但对有大额非经常性损益的公司(如恒瑞)会产生方向性误判, akshare免费接口未找到全市场扣非增速字段(已测stock_lrb_em/stock_yjkb_em均无此字段, stock_financial_abstract_ths需逐票调用, 1700+票在25分钟预算内不可行)。此为已知数据局限, 非结论支持性证据被选择性隐藏。",
    },
    "summary_by_tier": summary,
    "spearman_correlation": corr,
    "counter_examples": {
        "beat_but_fell_5d": beat_worst.to_dict("records"),
        "miss_but_rose_5d": miss_best.to_dict("records"),
    },
    "portfolio_case_study": portfolio_cases.to_dict("records"),
}

with open(OUTDIR + "step5_final_summary.json", "w") as f:
    json.dump(final_out, f, ensure_ascii=False, indent=2, default=str)

log("DONE. 总耗时:", round(time.time() - t_start, 1), "秒")
print(json.dumps(final_out, ensure_ascii=False, indent=2, default=str))
