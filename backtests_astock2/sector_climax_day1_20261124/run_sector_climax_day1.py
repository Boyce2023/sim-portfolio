#!/opt/homebrew/bin/python3.13
"""8Y (2018~2026.11.23) PIT Backtest: Industry Climax Day-1 Gap-Up (First in 40 trading days).
Measures T0 intraday, T+1, T+2, T+3, T+5 returns & win rates for:
- Independent industry climax gap-up (market median gap < +0.8%) vs Whole-market gap-up
- Gap tiers: [+1.5%, +2.5%), [+2.5%, +4.0%), >= +4.0%
- With US overnight resonance (QQQ/SOXX/XLE/GDX/FCX >= +2%) vs Pure A-share catalyst
- Entry at T0 Open vs T0 Close (and T0 Open -> T0 Close intraday fade!)
- Basket: Equal-Weight Industry vs Large-Cap Zhongjun (Top5 amount) vs Top3 Gap Leaders
- Also checks 2024-2026 recent 2Y subsample!
Strictly NO yfinance. Reads local parquets + csrc_industry_l2.csv.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

SIM = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
OUT = SIM / "backtests_astock2/sector_climax_day1_20261124"
OUT.mkdir(parents=True, exist_ok=True)

# 1. Load industry map (CSRC L2)
ind = pd.read_csv(SIM / "data/csrc_industry_l2.csv")
ind = ind[ind["industry"].notna() & (ind["industry"].astype(str).str.len() > 2)].copy()
ind["ticker"] = ind["code"].apply(lambda x: f"{x.split('.')[1]}.{x.split('.')[0].upper()}" if "." in str(x) else str(x))
ind_map = dict(zip(ind["ticker"], ind["industry"]))

# 2. Load A-share daily 2018-01-01 ~ 2026-11-23
df = pd.read_parquet(
    SIM / "data/cn_hk_price_db/a_daily.parquet",
    columns=["date", "ticker", "open", "close", "adj_close", "amount"],
    filters=[("date", ">=", pd.Timestamp("2018-01-01"))],
)
df["ind"] = df["ticker"].map(ind_map)
df = df[df["ind"].notna()].copy()
df = df.sort_values(["ticker", "date"])
# Compute split-adjusted open and forward returns strictly per stock
ratio = df["adj_close"] / df["close"].replace(0, np.nan)
df["adj_open"] = df["open"] * ratio
g = df.groupby("ticker", sort=False)
df["prev_c"] = g["adj_close"].shift(1)
df["prev_amt"] = g["amount"].shift(1)
df["gap"] = df["adj_open"] / df["prev_c"] - 1.0
df["o2c"] = df["adj_close"] / df["adj_open"] - 1.0
df["c2c"] = df["adj_close"] / df["prev_c"] - 1.0
for h in (1, 2, 3, 5):
    c_h = g["adj_close"].shift(-h)
    df[f"o2c_{h}"] = c_h / df["adj_open"] - 1.0
    df[f"c2c_{h}"] = c_h / df["adj_close"] - 1.0
df["o2o_1"] = g["adj_open"].shift(-1) / df["adj_open"] - 1.0

# Filter valid bars (exclude IPO/relisting extreme >25% gap artifacts)
df = df[df["gap"].between(-0.22, 0.22) & df["o2c"].between(-0.35, 0.35)].copy()

# Market daily median gap & HS300 proxy (all-market equal-weight)
mkt = df.groupby("date").agg(
    mkt_med_gap=("gap", "median"),
    mkt_o2c=("o2c", "mean"),
    mkt_o2c_1=("o2c_1", "mean"),
    mkt_o2c_3=("o2c_3", "mean"),
    mkt_o2c_5=("o2c_5", "mean"),
)

# Industry daily aggregation (keep industries with >= 15 active stocks on that day)
ind_day = df.groupby(["date", "ind"]).agg(
    n=("ticker", "size"),
    gap_mean=("gap", "mean"),
    gap_med=("gap", "median"),
    pct_gap2=("gap", lambda s: (s >= 0.02).mean()),
    pct_gap5=("gap", lambda s: (s >= 0.05).mean()),
    o2c=("o2c", "mean"),
    o2o_1=("o2o_1", "mean"),
    o2c_1=("o2c_1", "mean"),
    o2c_2=("o2c_2", "mean"),
    o2c_3=("o2c_3", "mean"),
    o2c_5=("o2c_5", "mean"),
    c2c_1=("c2c_1", "mean"),
    c2c_3=("c2c_3", "mean"),
    c2c_5=("c2c_5", "mean"),
).reset_index()
ind_day = ind_day[ind_day["n"] >= 15].merge(mkt, on="date", how="left").sort_values(["ind", "date"])

# Also compute Large-cap Zhongjun (top 5 by prev_amt) and Top 3 gap leaders per (date, ind)
df_sorted_amt = df.sort_values(["date", "ind", "prev_amt"], ascending=[True, True, False])
top5_amt = df_sorted_amt.groupby(["date", "ind"]).head(5).groupby(["date", "ind"])[["o2c", "o2c_1", "o2c_3", "o2c_5", "c2c_3", "c2c_5"]].mean().add_prefix("zj_")
df_sorted_gap = df.sort_values(["date", "ind", "gap"], ascending=[True, True, False])
top3_gap = df_sorted_gap.groupby(["date", "ind"]).head(3).groupby(["date", "ind"])[["o2c", "o2c_1", "o2c_3", "o2c_5", "c2c_3", "c2c_5"]].mean().add_prefix("ld_")
ind_day = ind_day.merge(top5_amt, on=["date", "ind"], how="left").merge(top3_gap, on=["date", "ind"], how="left")

# Load US overnight returns (NQ_F, ES_F + NVDA/TSLA/FCX/XOM/NEM/ALB) aligned strictly PIT (US date < A-share date)
us = pd.read_parquet(
    SIM / "data/us_price_db/all_daily.parquet",
    columns=["date", "ticker", "adj_close"],
    filters=[("ticker", "in", ["NVDA", "TSLA", "FCX", "XOM", "NEM", "ALB"])],
)
us["date"] = pd.to_datetime(us["date"])
us_p = us.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index().pct_change()
for nm, fn in [("NQ", "NQ_F.parquet"), ("ES", "ES_F.parquet")]:
    fp = SIM / "data/us_price_db/commodities" / fn
    d_f = pd.read_parquet(fp)
    idx = d_f.index if isinstance(d_f.index, pd.DatetimeIndex) else pd.to_datetime(d_f["date"])
    us_p[nm] = pd.Series(d_f["close"].values, index=idx).groupby(level=0).last().pct_change().reindex(us_p.index)
a_dates = pd.DataFrame({"date": sorted(ind_day["date"].unique())})
us_p_reset = us_p.reset_index().rename(columns={"date": "us_date"})
aligned_us = pd.merge_asof(a_dates, us_p_reset, left_on="date", right_on="us_date", direction="backward", allow_exact_matches=False)
aligned_us["us_big_up"] = (aligned_us["NQ"] >= 0.015) | (aligned_us["ES"] >= 0.015) | (aligned_us["NVDA"] >= 0.04) | (aligned_us["TSLA"] >= 0.05) | (aligned_us["FCX"] >= 0.04) | (aligned_us["ALB"] >= 0.05) | (aligned_us["NEM"] >= 0.04)
ind_day = ind_day.merge(aligned_us[["date", "NQ", "NVDA", "us_big_up"]], on="date", how="left")

# Mark "First Day in 40 trading days" per industry for climax threshold >= +1.5%
def mark_first_day(sub_df, gap_thr=0.015, cool=40):
    sub_df = sub_df.sort_values("date").copy()
    is_evt = (sub_df["gap_mean"] >= gap_thr).values
    first = np.zeros(len(sub_df), dtype=bool)
    last_i = -9999
    for i, flag in enumerate(is_evt):
        if flag and (i - last_i > cool):
            first[i] = True
            last_i = i
        elif flag:
            last_i = i  # extend climax cluster
    sub_df["is_day1"] = first
    return sub_df

ind_day = ind_day.groupby("ind", group_keys=False).apply(mark_first_day, gap_thr=0.015, cool=40)
ev = ind_day[ind_day["is_day1"]].copy()
ev["indep"] = ev["mkt_med_gap"] < 0.008  # Independent sector catalyst (not whole-market surge)

def stats(d, label):
    if len(d) == 0:
        return f"{label:32s} | n=  0"
    def f(col):
        s = d[col].dropna()
        return f"{s.mean()*100:+5.2f}%({(s>0).mean()*100:4.0f}%)"
    ex3 = (d["o2c_3"] - d["mkt_o2c_3"]).dropna().mean() * 100
    ex5 = (d["o2c_5"] - d["mkt_o2c_5"]).dropna().mean() * 100
    return f"{label:32s} | n={len(d):4d} | gap={d['gap_mean'].mean()*100:+4.2f}% | T0日内:{f('o2c')} | T+1收:{f('o2c_1')} | T+3收:{f('o2c_3')}(超{ex3:+4.2f}%) | T+5收:{f('o2c_5')}(超{ex5:+4.2f}%) | 收买T+3:{f('c2c_3')} | 收买T+5:{f('c2c_5')}"

print("=== 8年(2018-2026) 行业明牌大高潮高开（近40日首日）全谱系实证 ===")
print(stats(ev, "全量首日高开(>=+1.5%)"))
print(stats(ev[ev["indep"]], "独立行业催化(大盘<+0.8%)"))
print(stats(ev[~ev["indep"]], "大盘普涨共振(大盘>=+0.8%)"))
print("--- 独立行业催化按高开幅度拆档 ---")
ie = ev[ev["indep"]]
print(stats(ie[ie["gap_mean"].between(0.015, 0.025)], "  独立 温和高开[+1.5%,+2.5%)"))
print(stats(ie[ie["gap_mean"].between(0.025, 0.040)], "  独立 大高潮[+2.5%,+4.0%)"))
print(stats(ie[ie["gap_mean"] >= 0.040],             "  独立 极端爆高开(>=+4.0%)"))
print("--- 独立行业催化：叠加隔夜美股共振 vs 纯A股独立消息 ---")
print(stats(ie[ie["us_big_up"] == True],  "  独立 + 隔夜美股大涨共振"))
print(stats(ie[ie["us_big_up"] == False], "  独立 + 无美股共振(纯A消息)"))
print("--- 独立行业催化(>=+2.0%)：买中军Top5 vs 行业全员 vs 高开前3领涨股 ---")
ie2 = ie[ie["gap_mean"] >= 0.020]
for pfx, nm in [("", "行业全员等权"), ("zj_", "大市值中军Top5"), ("ld_", "高开最猛前3领涨")]:
    s0 = ie2[f"{pfx}o2c"].dropna(); s1 = ie2[f"{pfx}o2c_1"].dropna(); s3 = ie2[f"{pfx}o2c_3"].dropna(); s5 = ie2[f"{pfx}o2c_5"].dropna(); c3 = ie2[f"{pfx}c2c_3"].dropna()
    print(f"  {nm:16s} (n={len(ie2):3d}) | T0日内:{s0.mean()*100:+5.2f}%({(s0>0).mean()*100:4.0f}%) | T+1收:{s1.mean()*100:+5.2f}%({(s1>0).mean()*100:4.0f}%) | T+3收:{s3.mean()*100:+5.2f}%({(s3>0).mean()*100:4.0f}%) | T+5收:{s5.mean()*100:+5.2f}%({(s5>0).mean()*100:4.0f}%) | 收买T+3:{c3.mean()*100:+5.2f}%")
print("--- 近两年(2025-2026) 独立行业首日高开是否变味？ ---")
ie25 = ie[ie["date"] >= "2025-01-01"]
print(stats(ie25, "2025-2026 独立首日(>=+1.5%)"))
print(stats(ie25[ie25["gap_mean"] >= 0.025], "2025-2026 独立大高潮(>=+2.5%)"))
print(stats(ie25[ie25["us_big_up"] == True], "2025-2026 独立+美股共振"))
print(stats(ie25[ie25["us_big_up"] == False], "2025-2026 独立+纯A消息"))
print("--- 2025-2026 独立大高潮最近10个真实案例 ---")
for _, r in ie25[ie25["gap_mean"] >= 0.025].tail(10).iterrows():
    print(f"  {str(r['date'])[:10]} | {r['ind'][:12]:12s} | gap={r['gap_mean']*100:+5.2f}% | us={bool(r['us_big_up'])} | T0日内={r['o2c']*100:+5.2f}% | T+3={r['o2c_3']*100:+5.2f}% | T+5={r['o2c_5']*100:+5.2f}%")
