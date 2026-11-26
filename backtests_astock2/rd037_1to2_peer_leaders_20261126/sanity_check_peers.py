#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD037 Sanity Check: Verify PIT Peer1..Peer4 selections on Anchor_Live92 sample & measure Peak RSS."""
import gc
import json
import os
import resource
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
RD016_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd016_famous_youzi_seats_20261117"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
CORE_PQ = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
OH_PQ = f"{RD028_DIR}/old_hot_6dim_stock_day_pit.parquet"

t0 = time.time()

# 1. Load anchor Live92
p1 = pd.read_parquet(
    f"{BASE_DIR}/pool_1to2_master_pit.parquet",
    columns=["buy_date", "code", "name", "plate", "L2_kpl_plate_t1", "L2_ind_name_t1",
             "sd_csrc_ind_id", "is_standalone_slot1", "orig_pass", "v20_score", "buy_hhmm", "net_ret"]
)
s92 = p1[p1["is_standalone_slot1"] == 1].sort_values("buy_date").reset_index(drop=True)

# 2. Load calendar
raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
all_cal = sorted(raw_idx["sh000300"].keys())
cal_5y = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
cal_idx = {d: i for i, d in enumerate(cal_5y)}
prev_td = {cal_5y[i]: cal_5y[i - 1] for i in range(1, len(cal_5y))}

# 3. Stock names from csrc_industry_pit_clean.csv
csrc = pd.read_csv(f"{DATA_DIR}/csrc_industry_pit_clean.csv", usecols=["code", "code_name", "industry", "start_date"])
csrc["c6"] = csrc["code"].astype(str).str[-6:]
name_map = dict(zip(csrc["c6"], csrc["code_name"].astype(str)))
audit2 = json.load(open(f"{BASE_DIR}/_audit_step2_stockday.json"))
id_to_ind = {v: k for k, v in audit2["csrc_ind_id_map"].items()}

# 4. Build KPL plate -> [(cal_i, c6)] strictly from kpl_plates_5y_2021_2026_complete.jsonl
# Note: also check pre-2021 from merged? Let's test kpl_plates_5y_2021_2026_complete.jsonl first
kpl_plate_recs = defaultdict(list)  # base_plate -> list of (d_i, c6)
with open(f"{DATA_DIR}/kpl_plates_5y_2021_2026_complete.jsonl", encoding="utf-8") as f:
    for line in f:
        o = json.loads(line)
        d = str(o["date"])[:10]
        di = cal_idx.get(d, -1)
        if di < 0:
            continue
        for pl in o.get("plates", []):
            pn = str(pl.get("plate", ""))
            base = pn.split("(")[0].strip()
            for s in pl.get("stocks", []):
                c6 = str(s[0]).strip()[:6].zfill(6)
                kpl_plate_recs[pn].append((di, c6))
                if base != pn:
                    kpl_plate_recs[base].append((di, c6))

# 5. Load famous youzi codes from rd016 & bayes_seat_scores_d1_5y.parquet
sys.path.insert(0, RD016_DIR)
import step2_module2_leaderboard as rd16_m2
famous_yz_codes = set()
for k, v in rd16_m2.SEAT_GROUPS.items():
    if "拉萨" in k or "外资" in k or "机构" in k or "山南" in k or "昌都" in k:
        continue
    if "瑞银" in k or "高盛" in k or "摩根" in k or "量化" in k or "国信浙江" in k:
        continue
    famous_yz_codes |= set(v)

bs = pd.read_parquet(f"{RD016_DIR}/bayes_seat_scores_d1_5y.parquet")
bs["c6"] = bs["stock_code"].astype(str).str.zfill(6)
bs["di"] = bs["date"].astype(str).str[:10].map(cal_idx).fillna(-1).astype(np.int32)
bs["is_fam_yz"] = bs["dept_code"].astype(str).isin(famous_yz_codes).astype(np.int8)
bs = bs[bs["di"] >= 0].copy()
# Aggregate per (c6, di): n_fam_yz, sum_pos_bt2
bs_day = bs.groupby(["c6", "di"], as_index=False).agg(
    n_fam=("is_fam_yz", "sum"),
    n_seats=("dept_code", "count"),
)
yz_by_c6 = {}
for c6, g in bs_day.sort_values("di").groupby("c6", sort=False):
    yz_by_c6[c6] = (g["di"].to_numpy(np.int32), g["n_fam"].to_numpy(np.int32), g["n_seats"].to_numpy(np.int32))
del bs, bs_day
gc.collect()

# 6. Load minimal columns from stock_day_core_features_pit + old_hot (only needed dates or all with compact arrays!)
sd_cols = ["dt", "c6", "open", "close", "adj_factor", "ret_1d", "open_pct", "is_zt", "is_yizi_zt",
           "is_st_pit", "is_20cm", "mcap_yi_t1", "free_mcap_yi_t1", "amount_yi_t1", "amount_yi",
           "turn_pct", "ret_20d_t1", "csrc_ind_id", "zt_cnt_1y_t1", "waves_3y_g15_t1"]
sd = pd.read_parquet(CORE_PQ, columns=sd_cols)
pa.default_memory_pool().release_unused()
print(f"Loaded sd {sd.shape} | RAM={sd.memory_usage(deep=True).sum()/1e9:.3f}GB | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")

# Compute trailing 20d / 60d zt_cnt, amt_ma20, turn_ma20 strictly <= T-1 per stock!
# Since sd is sorted by (c6, dt)? Let's verify!
sd["di"] = sd["dt"].astype(str).map(cal_idx).fillna(-1).astype(np.int16)
sd = sd.sort_values(["c6", "di"]).reset_index(drop=True)
c6_s = sd["c6"].astype(str).values
brk = np.flatnonzero(c6_s[1:] != c6_s[:-1]) + 1
starts = np.concatenate(([0], brk))
ends = np.concatenate((brk, [len(sd)]))

n = len(sd)
zt20_t1 = np.zeros(n, dtype=np.int16)
zt60_t1 = np.zeros(n, dtype=np.int16)
amt20_t1 = np.full(n, np.nan, dtype=np.float32)
trn20_t1 = np.full(n, np.nan, dtype=np.float32)
yz3y_t1 = np.zeros(n, dtype=np.int16)

iz = sd["is_zt"].to_numpy(np.int32)
am = np.nan_to_num(sd["amount_yi"].to_numpy(np.float64), nan=0.0)
tr = np.nan_to_num(sd["turn_pct"].to_numpy(np.float64), nan=0.0)
di_arr = sd["di"].to_numpy(np.int32)

for s, e in zip(starts, ends):
    m = e - s
    cs_z = np.concatenate(([0], np.cumsum(iz[s:e])))
    cs_a = np.concatenate(([0.0], np.cumsum(am[s:e])))
    cs_t = np.concatenate(([0.0], np.cumsum(tr[s:e])))
    # strictly < i: [max(0, i-W), i)
    idx_i = np.arange(m)
    lo20 = np.maximum(0, idx_i - 20)
    lo60 = np.maximum(0, idx_i - 60)
    cnt20 = np.maximum(1, idx_i - lo20)
    zt20_t1[s:e] = cs_z[idx_i] - cs_z[lo20]
    zt60_t1[s:e] = cs_z[idx_i] - cs_z[lo60]
    amt20_t1[s + 1 : e] = (cs_a[idx_i[1:]] - cs_a[lo20[1:]]) / cnt20[1:]
    trn20_t1[s + 1 : e] = (cs_t[idx_i[1:]] - cs_t[lo20[1:]]) / cnt20[1:]
    tup = yz_by_c6.get(str(c6_s[s]))
    if tup is not None:
        yd, yf, _ = tup
        p_arr = di_arr[s:e] - 1  # strictly <= T-1
        cs_yf = np.concatenate(([0], np.cumsum(yf)))
        rp = np.searchsorted(yd, p_arr, side="right")
        lp = np.searchsorted(yd, p_arr - 750, side="left")
        yz3y_t1[s:e] = cs_yf[rp] - cs_yf[lp]

sd["zt20_t1"] = zt20_t1
sd["zt60_t1"] = zt60_t1
sd["amt20_t1"] = amt20_t1
sd["trn20_t1"] = trn20_t1
sd["yz3y_t1"] = yz3y_t1

# Also attach zt_cnt_3y_t1 from old_hot
oh = pd.read_parquet(OH_PQ, columns=["c6", "dt", "zt_cnt_3y_t1"])
sd["c6_str"] = sd["c6"].astype(str)
sd["dt_str"] = sd["dt"].astype(str)
oh["c6_str"] = oh["c6"].astype(str)
oh["dt_str"] = oh["dt"].astype(str)
sd = sd.merge(oh[["c6_str", "dt_str", "zt_cnt_3y_t1"]], on=["c6_str", "dt_str"], how="left")
sd["zt_cnt_3y_t1"] = sd["zt_cnt_3y_t1"].fillna(0).astype(np.int16)
del oh
gc.collect()

# Slice only the 92 anchor dates for inspection!
anchor_dts = set(s92["buy_date"].tolist())
sd_sub = sd[sd["dt_str"].isin(anchor_dts)].copy()
by_dt = {d: g.reset_index(drop=True) for d, g in sd_sub.groupby("dt_str")}
del sd, sd_sub
gc.collect()

print(f"Prep done in {time.time()-t0:.1f}s | Peak RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f} GB\n")

# Print 12 sample Live92 anchor dates & their Peer1..Peer4 top picks
sample_idx = [0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 86, 91]
for idx in sample_idx:
    r = s92.iloc[idx]
    dt = r["buy_date"]
    di = cal_idx[dt]
    pl = r["plate"]
    base = pl.split("(")[0].strip()
    recs = kpl_plate_recs.get(pl, []) or kpl_plate_recs.get(base, [])
    # counts in trailing 250d / 750d / 60d strictly < di (i.e. <= di-1)
    c_3y = defaultdict(int)
    c_1y = defaultdict(int)
    c_60 = defaultdict(int)
    for d_i, c6 in recs:
        if d_i < di:
            if d_i >= di - 750: c_3y[c6] += 1
            if d_i >= di - 250: c_1y[c6] += 1
            if d_i >= di - 60: c_60[c6] += 1

    day_df = by_dt[dt].copy()
    day_df = day_df[(day_df["c6_str"] != r["code"]) & (day_df["is_st_pit"] == 0)].copy()
    day_df["kpl_3y"] = day_df["c6_str"].map(c_3y).fillna(0).astype(int)
    day_df["kpl_1y"] = day_df["c6_str"].map(c_1y).fillna(0).astype(int)
    day_df["kpl_60"] = day_df["c6_str"].map(c_60).fillna(0).astype(int)

    # Theme pool (KPL >= 2 in 3y, fallback >=1)
    tp3 = day_df[day_df["kpl_3y"] >= 2]
    if len(tp3) < 3:
        tp3 = day_df[day_df["kpl_3y"] >= 1]
    tp60 = day_df[day_df["kpl_60"] >= 1]
    if len(tp60) < 3:
        tp60 = tp3

    # Peer1: Old Youzi Dragon (waves_3y_g15_t1 + zt_cnt_3y_t1 + yz3y_t1 + kpl_3y)
    p1_df = tp3.copy()
    p1_df["sc1"] = (p1_df["waves_3y_g15_t1"].rank(pct=True) * 0.35 +
                    p1_df["zt_cnt_3y_t1"].rank(pct=True) * 0.30 +
                    p1_df["yz3y_t1"].rank(pct=True) * 0.20 +
                    p1_df["kpl_3y"].rank(pct=True) * 0.15)
    p1_top = p1_df.sort_values(["sc1", "zt_cnt_3y_t1"], ascending=False).head(3)

    # Peer2: Recent Active Dragon (zt20_t1, zt60_t1, trn20_t1, ret_20d_t1)
    p2_df = tp60.copy()
    p2_df["sc2"] = (p2_df["zt60_t1"].rank(pct=True) * 0.35 +
                    p2_df["zt20_t1"].rank(pct=True) * 0.30 +
                    p2_df["trn20_t1"].rank(pct=True) * 0.20 +
                    p2_df["ret_20d_t1"].fillna(0).rank(pct=True) * 0.15)
    p2_top = p2_df.sort_values(["sc2", "zt60_t1"], ascending=False).head(3)

    # Peer3: Inst Big Cap (same KPL 1y/3y, free_mcap >= 100 & top 20%, top amt20_t1)
    tp1y = day_df[day_df["kpl_1y"] >= 1]
    if len(tp1y[tp1y["free_mcap_yi_t1"] >= 100.0]) == 0:
        tp1y = tp3
    q80_mc = tp1y["free_mcap_yi_t1"].quantile(0.80) if len(tp1y) else 100.0
    p3_df = tp1y[(tp1y["free_mcap_yi_t1"] >= max(100.0, q80_mc))].copy()
    if p3_df.empty:
        p3_df = tp1y[tp1y["free_mcap_yi_t1"] >= 100.0].copy()
    p3_top = p3_df.sort_values("amt20_t1", ascending=False).head(3)

    # Peer4: CSRC Industry Leader 1 (free_mcap_yi_t1 pct + amt20_t1 pct in same csrc_ind_id)
    cid = int(r["sd_csrc_ind_id"])
    p4_df = day_df[day_df["csrc_ind_id"] == cid].copy()
    p4_df["sc4"] = p4_df["free_mcap_yi_t1"].rank(pct=True) * 0.5 + p4_df["amt20_t1"].rank(pct=True) * 0.5
    p4_top = p4_df.sort_values("sc4", ascending=False).head(3)

    def _fmt(df_t):
        return ", ".join(f"{x.c6_str}({name_map.get(x.c6_str,'?')},mc={x.free_mcap_yi_t1:.0f},zt3y={x.zt_cnt_3y_t1},zt60={x.zt60_t1})" for x in df_t.itertuples())

    print(f"[{dt}] Anchor: {r['code']}({r['name']}) | Plate={pl} | CSRC={id_to_ind.get(cid,'?')}")
    print(f"   P1 OldYouzi : {_fmt(p1_top)}")
    print(f"   P2 RecActive: {_fmt(p2_top)}")
    print(f"   P3 InstBig  : {_fmt(p3_top)}")
    print(f"   P4 IndLead1 : {_fmt(p4_top)}")
