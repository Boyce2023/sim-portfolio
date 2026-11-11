import json
from pathlib import Path
import numpy as np
import pandas as pd

# 1. Load kpl_plates_v2.jsonl
kpl_path = Path("/Users/huaichuaibeimeng/claude-projects/news-dashboard/output/kpl_plates_v2.jsonl")
kpl_data = {}
code_to_meta = {}  # code -> (name, main_theme, sub_concept)

with open(kpl_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        dt = item.get("date")
        plates = item.get("plates", [])
        kpl_data[dt] = plates
        for p in plates:
            pname = p.get("plate", "")
            for s in p.get("stocks", []):
                # s is [code, name, sub_concept, full_concept]
                code = s[0]
                name = s[1]
                sub = s[2] if len(s) > 2 else ""
                full = s[3] if len(s) > 3 else ""
                if code not in code_to_meta:
                    code_to_meta[code] = (name, pname, full)
                else:
                    # update if theme is not '其他' or 'ST板块'
                    if pname not in ["其他", "ST板块"]:
                        code_to_meta[code] = (name, pname, full)

# 2. Load a_daily.parquet
pq_path = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet")
df = pd.read_parquet(
    pq_path,
    columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "oshare", "turn"],
)
df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
# Keep from 2026-09-01 onwards to calculate rolling features
df = df[df["date"] >= "2026-09-01"].sort_values(["ticker", "date"]).reset_index(drop=True)
df["code6"] = df["ticker"].astype(str).str.extract(r"(\d{6})")[0].fillna("")

# Main board check
df["is_main"] = df["code6"].str.startswith(("00", "60"))
df["is_gem"] = df["code6"].str.startswith(("30", "68"))
df["is_bse"] = df["code6"].str.startswith(("8", "4", "92"))

# Groupby ticker to get prev_close and ret
g = df.groupby("ticker", sort=False)
df["prev_c"] = g["close"].shift(1)
df["ret"] = df["close"] / df["prev_c"] - 1.0

# Calculate limit up/down prices
# Main board
main_zt = np.floor(df["prev_c"] * 1.10 * 100 + 0.5) / 100.0
main_dt = np.floor(df["prev_c"] * 0.90 * 100 + 0.5) / 100.0
# GEM/STAR
gem_zt = np.floor(df["prev_c"] * 1.20 * 100 + 0.5) / 100.0
gem_dt = np.floor(df["prev_c"] * 0.80 * 100 + 0.5) / 100.0
# BSE
bse_zt = np.floor(df["prev_c"] * 1.30 * 100 + 0.5) / 100.0
bse_dt = np.floor(df["prev_c"] * 0.70 * 100 + 0.5) / 100.0

is_zt = np.zeros(len(df), dtype=bool)
is_dt = np.zeros(len(df), dtype=bool)

# Mask for main board
m_main = df["is_main"].to_numpy()
c = df["close"].to_numpy()
r = df["ret"].to_numpy()

is_zt[m_main] = (c[m_main] >= main_zt[m_main] - 0.005) & (r[m_main] > 0.085)
is_dt[m_main] = (c[m_main] <= main_dt[m_main] + 0.005) & (r[m_main] < -0.085)

m_gem = df["is_gem"].to_numpy()
is_zt[m_gem] = (c[m_gem] >= gem_zt[m_gem] - 0.005) & (r[m_gem] > 0.18)
is_dt[m_gem] = (c[m_gem] <= gem_dt[m_gem] + 0.005) & (r[m_gem] < -0.18)

m_bse = df["is_bse"].to_numpy()
is_zt[m_bse] = (c[m_bse] >= bse_zt[m_bse] - 0.005) & (r[m_bse] > 0.27)
is_dt[m_bse] = (c[m_bse] <= bse_dt[m_bse] + 0.005) & (r[m_bse] < -0.27)

df["is_zt"] = is_zt
df["is_dt"] = is_dt

# Vectorized streak calculation
zt_arr = df["is_zt"].to_numpy()
tk_arr = df["ticker"].to_numpy()
streak = np.zeros(len(df), dtype=np.int32)
cur = 0
prev_tk = None
for i in range(len(df)):
    if tk_arr[i] != prev_tk:
        cur = 1 if zt_arr[i] else 0
        prev_tk = tk_arr[i]
    else:
        cur = (cur + 1) if zt_arr[i] else 0
    streak[i] = cur
df["streak"] = streak

g = df.groupby("ticker", sort=False)
df["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)

# Target dates: 2026-10-26 to 2026-11-10
target_dates = [
    "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30",
    "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06",
    "2026-11-09", "2026-11-10"
]

print("=== PART 1: 逐日市场全景表 (2026-10-26 至 2026-11-10) ===")
summary_rows = []

for dt in target_dates:
    sub = df[df["date"] == dt]
    if len(sub) == 0:
        continue
    
    # 全A平均涨跌
    all_avg_ret = sub["ret"].mean() * 100.0
    
    # 主板统计
    main_sub = sub[sub["is_main"]]
    main_zt_cnt = main_sub["is_zt"].sum()
    main_dt_cnt = main_sub["is_dt"].sum()
    all_zt_cnt = sub["is_zt"].sum()
    all_dt_cnt = sub["is_dt"].sum()
    
    # 连板梯队 (主板 + 创业板)
    # Filter stocks with streak >= 1
    zt_stocks = sub[sub["is_zt"]].copy()
    max_streak = zt_stocks["streak"].max() if len(zt_stocks) > 0 else 0
    
    # Highest streak stock(s)
    highest_stocks = []
    if max_streak > 0:
        top_s = zt_stocks[zt_stocks["streak"] == max_streak]
        for _, r_s in top_s.iterrows():
            c6 = r_s["code6"]
            nm = code_to_meta.get(c6, (c6, ""))[0]
            highest_stocks.append(f"{nm}({c6})")
    highest_str = f"{max_streak}板: " + ",".join(highest_stocks) if max_streak > 0 else "无"
    
    # 3板及以上梯队明细
    tiers = {}
    for st_val in range(max_streak, 2, -1):
        tier_s = zt_stocks[zt_stocks["streak"] == st_val]
        if len(tier_s) > 0:
            names = [f"{code_to_meta.get(x, (x,))[0]}({x})" for x in tier_s["code6"]]
            tiers[st_val] = names
    
    tier_str_list = []
    for st_val, names in tiers.items():
        tier_str_list.append(f"{st_val}板({len(names)}家): {','.join(names)}")
    tier_summary = " | ".join(tier_str_list) if tier_str_list else "3板及以上无"
    
    # 当日断板大面股: 前一日 prev_streak >= 4, 当日 streak == 0, 且当日大跌 (ret < -0.04) 或跌停
    broken_s = sub[(sub["prev_streak"] >= 4) & (~sub["is_zt"])].copy()
    broken_list = []
    for _, r_b in broken_s.iterrows():
        c6 = r_b["code6"]
        nm = code_to_meta.get(c6, (c6, ""))[0]
        p_st = r_b["prev_streak"]
        ret_b = r_b["ret"] * 100.0
        dt_tag = " [跌停]" if r_b["is_dt"] else ""
        broken_list.append(f"{nm}({c6},昨日{p_st}板,今日{ret_b:+.1f}%{dt_tag})")
    broken_summary = " | ".join(broken_list) if broken_list else "无"
    
    print(f"[{dt}] 全A均涨:{all_avg_ret:+.2f}% | 主板涨停:{main_zt_cnt}家/跌停:{main_dt_cnt}家 (全A涨停:{all_zt_cnt}/跌停:{all_dt_cnt})")
    print(f"  最高标: {highest_str}")
    print(f"  3板及以上梯队: {tier_summary}")
    print(f"  当日>=4板断板个股: {broken_summary}")
    print()

print("\n=== PART 2: 10月底至11月初冲到 >=4 连板的高标股票完整名单与退潮走势 ===")
# Find all tickers that had streak >= 4 on any date between 2026-10-26 and 2026-11-10
target_df = df[(df["date"] >= "2026-10-26") & (df["date"] <= "2026-11-10")]
high_streak_tickers = target_df[target_df["streak"] >= 4]["ticker"].unique()

high_spec_rows = []

for tk in high_streak_tickers:
    tk_sub = df[df["ticker"] == tk].sort_values("date").reset_index(drop=True)
    c6 = tk_sub["code6"].iloc[0]
    meta = code_to_meta.get(c6, (c6, "未知", "未知"))
    name = meta[0]
    theme = meta[1]
    full_theme = meta[2]
    
    # Filter to period around target
    # Find max streak in target period
    sub_period = tk_sub[(tk_sub["date"] >= "2026-10-20") & (tk_sub["date"] <= "2026-11-10")]
    max_st = sub_period["streak"].max()
    
    # Find peak date (last date of max streak)
    peak_rows = sub_period[sub_period["streak"] == max_st]
    peak_date = peak_rows["date"].iloc[-1]
    peak_idx = tk_sub[tk_sub["date"] == peak_date].index[0]
    peak_close = tk_sub.loc[peak_idx, "close"]
    
    # Day after peak (break date)
    if peak_idx + 1 < len(tk_sub):
        break_date = tk_sub.loc[peak_idx + 1, "date"]
        break_ret = tk_sub.loc[peak_idx + 1, "ret"] * 100.0
        break_is_dt = tk_sub.loc[peak_idx + 1, "is_dt"]
    else:
        break_date = "未断板"
        break_ret = 0.0
        break_is_dt = False
        
    # Latest close at 2026-11-10
    latest_sub = tk_sub[tk_sub["date"] == "2026-11-10"]
    if len(latest_sub) > 0:
        latest_close = latest_sub["close"].iloc[0]
        latest_drawdown = (latest_close / peak_close - 1.0) * 100.0
    else:
        latest_close = np.nan
        latest_drawdown = np.nan
        
    # Subsequent returns after peak
    post_peak = tk_sub.loc[peak_idx+1 : ]
    post_period = post_peak[(post_peak["date"] <= "2026-11-10")]
    dt_count = post_period["is_dt"].sum()
    min_close = post_period["close"].min() if len(post_period) > 0 else peak_close
    max_dd = (min_close / peak_close - 1.0) * 100.0
    
    post_ret_sequence = []
    for _, r_p in post_period.iterrows():
        d_str = r_p["date"][5:]
        r_val = r_p["ret"] * 100.0
        dt_flag = "(跌停)" if r_p["is_dt"] else ""
        zt_flag = "(涨停)" if r_p["is_zt"] else ""
        post_ret_sequence.append(f"{d_str}:{r_val:+.1f}%{dt_flag}{zt_flag}")
        
    high_spec_rows.append({
        "ticker": tk,
        "code6": c6,
        "name": name,
        "theme": theme,
        "full_theme": full_theme,
        "max_streak": max_st,
        "peak_date": peak_date,
        "break_date": break_date,
        "break_ret": break_ret,
        "break_is_dt": break_is_dt,
        "latest_dd": latest_drawdown,
        "max_dd": max_dd,
        "dt_count": dt_count,
        "post_seq": " -> ".join(post_ret_sequence) if post_ret_sequence else "无后续"
    })

high_spec_df = pd.DataFrame(high_spec_rows).sort_values("break_date")

for _, r_h in high_spec_df.iterrows():
    print(f"【{r_h['name']} ({r_h['code6']})】 题材:{r_h['theme']} ({r_h['full_theme']})")
    print(f"  最高连板: {r_h['max_streak']}板 | 见顶日: {r_h['peak_date']} | 断板日: {r_h['break_date']} (断板当日:{r_h['break_ret']:+.1f}%)")
    print(f"  到11-10累计回撤: {r_h['latest_dd']:.1f}% | 期间最大回撤: {r_h['max_dd']:.1f}% | 断板后跌停次数: {r_h['dt_count']}次")
    print(f"  断板后每日轨迹: {r_h['post_seq']}")
    print("-" * 60)

print("\n=== PART 3: 上周主线题材演变 (开盘啦每日涨停前3名题材) ===")
for dt in target_dates:
    plates = kpl_data.get(dt, [])
    # filter out ST板块 and 其他
    valid_plates = [p for p in plates if p.get("plate") not in ["ST板块", "其他"]]
    # sort by stock count
    valid_plates.sort(key=lambda x: len(x.get("stocks", [])), reverse=True)
    top3 = valid_plates[:3]
    top3_str = ", ".join([f"{p.get('plate')}({len(p.get('stocks', []))}家)" for p in top3])
    print(f"[{dt}] 前3题材: {top3_str}")
