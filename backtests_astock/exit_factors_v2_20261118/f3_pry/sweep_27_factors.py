#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
sweep_27_factors.py
Run all 27 marginal holding-period exit factors (plus variants) and synthesis baselines
against _cache_feats_830.pkl, reporting pure IS vs OOS performance across P165, P150, P140, P000.
"""
import os, sys, json, pickle, time
import numpy as np
import pandas as pd

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
sys.path.insert(0, F3_DIR)
import backtest_30_factors as bt

t0 = time.time()
cache = pickle.load(open(f"{F3_DIR}/_cache_feats_830.pkl", "rb"))
sub, feats, cb = cache["sub"], cache["feats"], pickle.load(
    open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb")
)["code_bars"]


def dyn_tp_fn(r):
    return float(np.clip(0.45 * abs(r.prev_ret10), 0.06, 0.16))


# Register baselines + all 27 factors + variants
specs = []

# Baselines
specs.append(("B1_X10_v1_strict", "Baseline", "现役X10死限价", {"base_mode": "X10_v1"}))
specs.append(("XF28_DecD_4d", "Synth", "上轮DecD_4d_t1_985_t2_985", {"base_mode": "DecD_4d"}))
specs.append(("XF29a_RD_2d", "Synth", "RD推荐:T+1低开<-2%斩+涨停骑+T+2收盘", {
    "base_mode": "DecD_4d", "max_h": 2, "t1_ratio": None, "t2_ratio": None,
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and st.get("o_gap", 0.0) < -0.02,
    "tp_sched_fn": lambda off, st, ft, r, btp: None,
}))
specs.append(("XF29b_RD_3d", "Synth", "RD推荐:T+1低开<-2%斩+涨停骑+T+3收盘", {
    "base_mode": "DecD_4d", "max_h": 3, "t1_ratio": None, "t2_ratio": None,
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and st.get("o_gap", 0.0) < -0.02,
    "tp_sched_fn": lambda off, st, ft, r, btp: None,
}))

# --- Group 1: LHB (XF01..XF06) ---
specs.append(("XF01_lhasa_cnt1_0925", "G1_LHB", "LHB拉萨>=1家次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("lhasa_cnt", 0) >= 1,
}))
specs.append(("XF01b_lhasa_cnt2_0925", "G1_LHB", "LHB拉萨>=2家次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("lhasa_cnt", 0) >= 2,
}))
specs.append(("XF02_daysurf_0925", "G1_LHB", "LHB一日游买方次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: bool(st.get("daysurf", False)),
}))
specs.append(("XF03a_inst_net_buy_boost", "G1_LHB", "LHB机构净买>0抬高止盈+3%且放飞", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("inst_net", 0.0) > 0) else btp,
    "disable_default_eod_cut_fn": lambda off, st, ft, r: st.get("inst_net", 0.0) > 0 and off == 1,
}))
specs.append(("XF03b_inst_net_sell_0925", "G1_LHB", "LHB机构净卖<0次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("inst_net", 0.0) < 0,
}))
specs.append(("XF03c_inst_bidir", "G1_LHB", "LHB机构净买格局+净卖早盘砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("inst_net", 0.0) < 0,
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("inst_net", 0.0) > 0) else btp,
}))
specs.append(("XF04_top_youzi_boost", "G1_LHB", "LHB顶级游资买入格局+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("yz_buy", False)) else btp,
    "preopen_cut_fn": lambda off, st, ft, r: bool(st.get("yz_sell", False)) and not bool(st.get("yz_buy", False)),
}))
specs.append(("XF05_quant_churn_0925", "G1_LHB", "LHB量化席位上榜次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("quant_cnt", 0) >= 1,
}))
specs.append(("XF06_big_net_sell_0925", "G1_LHB", "LHB总卖>1.2*总买次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: bool(st.get("big_net_sell", False)),
}))

# --- Group 2: Notices, Reg & Community (XF07..XF12) ---
specs.append(("XF07_bad_notice_0925", "G2_Notice", "持仓突发坏公告/澄清<09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: bool(st.get("bad_notice", False)),
}))
specs.append(("XF08_ex_reg5_ge2_0925", "G2_Notice", "交易所近5日监管>=2封09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("ex_reg5", 0) >= 2,
}))
specs.append(("XF08b_ex_reg5_ge2_tighttp", "G2_Notice", "交易所监管>=2封止盈降3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: max(0.02, btp - 0.03) if (btp is not None and st.get("ex_reg5", 0) >= 2) else btp,
}))
specs.append(("XF09a_xq_spike_cut", "G2_Comm", "持仓雪球>=1帖次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("xq_cnt", 0) >= 1,
}))
specs.append(("XF09b_xq_zero_boost", "G2_Comm", "雪球零帖暗牌抬高止盈+2%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.02) if (btp is not None and st.get("xq_cnt", 0) == 0) else btp,
}))
specs.append(("XF10_guba_spike3x_0925", "G2_Comm", "股吧发帖>=3x基线(且>=5帖)09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("gb_ratio", 0.0) >= 3.0 and st.get("gb_overnight", 0) >= 5,
}))
specs.append(("XF10b_guba_spike3x_boost", "G2_Comm", "股吧暴增>=3x高关注抬止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("gb_ratio", 0.0) >= 3.0 and st.get("gb_overnight", 0) >= 5) else btp,
}))
specs.append(("XF11_good_notice_boost", "G2_Notice", "回购/增持/中标利好护体抬止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("good_notice", False)) else btp,
}))
specs.append(("XF12_ir_active_boost", "G2_Notice", "近30日/持仓机构调研抬止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("ir_active", False)) else btp,
}))

# --- Group 3: 09:25 Auction & Market Ecosystem (XF13..XF20) ---
specs.append(("XF13a_mkt_open_zt_lt5_0925", "G3_Mkt0925", "T+k 09:25竞价涨停<5家直接砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("mkt_open_zt", 10) < 5,
}))
specs.append(("XF13b_mkt_open_zt_lt8_0925", "G3_Mkt0925", "T+k 09:25竞价涨停<8家直接砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("mkt_open_zt", 10) < 8,
}))
specs.append(("XF13c_mkt_open_dt_ge20_0925", "G3_Mkt0925", "T+k 09:25竞价跌停>=20家直接砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("mkt_open_dt", 0) >= 20,
}))
specs.append(("XF13d_zt_lt5_and_dt_ge10", "G3_Mkt0925", "T+k 09:25涨停<5且跌停>=10砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("mkt_open_zt", 10) < 5 and st.get("mkt_open_dt", 0) >= 10,
}))
specs.append(("XF14a_fb_open_neg_0925", "G3_Mkt0925", "T+k 09:25首板竞价均值<0%直接砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("fb_open_avg", 0.0) < 0.0,
}))
specs.append(("XF14b_fb_open_lt_neg1_0925", "G3_Mkt0925", "T+k 09:25首板竞价<-1%直接砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("fb_open_avg", 0.0) < -0.01,
}))
specs.append(("XF14c_nuke_or_brk_dt_0925", "G3_Mkt0925", "前日三进四核>=25%或高标断跌>=30%砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("prev_nuke_34", 0.0) >= 0.25 or st.get("prev_brk_dt_r", 0.0) >= 0.30,
}))
specs.append(("XF15a_csi_drop15_0925", "G3_MktEnv", "前日沪深300跌>1.5%次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("prev_csi_pct", 0.0) < -0.015,
}))
specs.append(("XF15b_csi_drop20_0925", "G3_MktEnv", "前日沪深300跌>2.0%次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("prev_csi_pct", 0.0) < -0.020,
}))
specs.append(("XF16a_mkt_ndt_ge30_0925", "G3_MktEnv", "前日全场跌停>=30家次日09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("prev_n_dt", 0) >= 30,
}))
specs.append(("XF16b_mkt_ndt_lt10_boost", "G3_MktEnv", "前日跌停<10家止血抬高止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("prev_n_dt", 99) < 10) else btp,
}))
specs.append(("XF17a_hd_brk_r10_hot", "G3_MktEnv", "高标10日断板跌停率>=20%调高止盈+2%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.02) if (btp is not None and st.get("hd_brk_r10", 0.0) >= 0.20) else btp,
}))
specs.append(("XF17b_hd_reb_zt_r10_hot", "G3_MktEnv", "真高标10日反包率>=20%调高止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("hd_reb_zt_r10", 0.0) >= 0.20) else btp,
}))
specs.append(("XF18a_mkt_zt_ge60_boost", "G3_MktEnv", "前日涨停>=60家抬高止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("prev_n_zt", 0) >= 60) else btp,
}))
specs.append(("XF18b_mkt_zt_lt40_cut", "G3_MktEnv", "前日涨停<40家(冰冷)09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("prev_n_zt", 99) < 40,
}))
specs.append(("XF19a_kpl_mates_ge1_boost", "G3_Sector", "开盘啦题材有>=1涨停先锋抬止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("kpl_mates", 0) >= 1) else btp,
}))
specs.append(("XF19b_csrc_mates_ge2_boost", "G3_Sector", "证监会行业有>=2涨停队友抬止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("csrc_mates", 0) >= 2) else btp,
}))
specs.append(("XF20a_promo1to2_ge20_boost", "G3_MktEnv", "一进二晋级率>=20%抬高止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and st.get("prev_promo", 0.0) >= 0.20) else btp,
}))
specs.append(("XF20b_promo1to2_lt13_cut", "G3_MktEnv", "一进二晋级率<13%冰点09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("prev_promo", 1.0) < 0.13,
}))

# --- Group 4: D0 Candle & T+1 Micro Quality (XF21..XF27) ---
specs.append(("XF21a_d0_ugly_fade_0925", "G4_Micro", "D0假阴/冲高回落(CLV<=0.3)T+1 09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and bool(ft.get("d0_ugly_fade", False)),
}))
specs.append(("XF21b_d0_ugly_fade_tp2", "G4_Micro", "D0假阴/冲高回落T+1挂+2%快跑", {
    "tp_sched_fn": lambda off, st, ft, r, btp: 0.02 if (off >= 1 and bool(ft.get("d0_ugly_fade", False))) else btp,
}))
specs.append(("XF21c_d0_strong_yang_boost", "G4_Micro", "D0光头真阳(CLV>=0.7)抬止盈+3%且免T1弱斩", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and bool(ft.get("d0_strong_yang", False))) else btp,
    "disable_default_eod_cut_fn": lambda off, st, ft, r: off == 1 and bool(ft.get("d0_strong_yang", False)),
}))
specs.append(("XF22a_d0_real_to_gt45_0925", "G4_Micro", "D0真实换手>45%天量对倒T+1 09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and ft.get("d0_real_to", 0.0) > 45.0,
}))
specs.append(("XF22b_d0_real_to_gt20_0925", "G4_Micro", "D0真实换手>20%高换手T+1 09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and ft.get("d0_real_to", 0.0) > 20.0,
}))
specs.append(("XF22c_d0_real_to_lt6_boost", "G4_Micro", "D0真实换手<6%缩量锁仓抬止盈+3%", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and ft.get("d0_real_to", 99.0) < 6.0) else btp,
}))
specs.append(("XF23a_t1_gap_lt_neg20_0925", "G4_Micro", "T+1竞价低开<-2.0%于09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and st.get("o_gap", 0.0) < -0.020,
}))
specs.append(("XF23b_t1_gap_lt_neg15_0925", "G4_Micro", "T+1竞价低开<-1.5%于09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and st.get("o_gap", 0.0) < -0.015,
}))
specs.append(("XF23c_t1_gap_lt_neg30_0925", "G4_Micro", "T+1竞价低开<-3.0%于09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: off == 1 and st.get("o_gap", 0.0) < -0.030,
}))
specs.append(("XF23d_tk_gap_lt_neg20_0925", "G4_Micro", "任一持仓日09:25低开<-2.0%于09:25砍", {
    "preopen_cut_fn": lambda off, st, ft, r: st.get("o_gap", 0.0) < -0.020,
}))
specs.append(("XF24a_t1_gap_ge20_release", "G4_Micro", "T+1高开>=+2.0%放飞T+2不设低盖(仅涨停/14:55)", {
    "tp_sched_fn": lambda off, st, ft, r, btp: None if (off == 2 and ft["steps"].get(1, {}).get("o_gap", 0.0) >= 0.020) else btp,
}))
specs.append(("XF24b_t1_gap_ge30_release", "G4_Micro", "T+1高开>=+3.0%全周期不设盖子(仅涨停/弱斩)", {
    "tp_sched_fn": lambda off, st, ft, r, btp: None if ft["steps"].get(1, {}).get("o_gap", 0.0) >= 0.030 else btp,
}))
specs.append(("XF25_vol_shrink_stall_eod", "G4_Micro", "T+1/T+2缩量滞涨(量比<0.7且涨幅<1%)尾盘清", {
    "eod_cut_fn": lambda off, k, st, ft, d, p0, bpx, end_p: (
        off in (1, 2) and (not d["is_zt"][k]) and st.get("to_vr", 1.0) < 0.70 and (d["close"][k] / d["pre_c"][k] - 1.0) < 0.010
    ),
}))
specs.append(("XF26a_ma5_resist_tp", "G4_Micro", "挂单上限叠加昨日MA5阻力(保底+2%)", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (
        min(btp, max(0.02, st["ma5_px"] / (r.buy_px * (cb[r.c6]["adjf"][r.p0] / cb[r.c6]["adjf"][r.p0 + off])) - 1.0))
        if (btp is not None and "ma5_px" in st) else btp
    ),
}))
specs.append(("XF26b_ma10_resist_tp", "G4_Micro", "挂单上限叠加昨日MA10阻力(保底+2%)", {
    "tp_sched_fn": lambda off, st, ft, r, btp: (
        min(btp, max(0.02, st["ma10_px"] / (r.buy_px * (cb[r.c6]["adjf"][r.p0] / cb[r.c6]["adjf"][r.p0 + off])) - 1.0))
        if (btp is not None and "ma10_px" in st) else btp
    ),
}))
specs.append(("XF27a_1to2_tight_judge", "G4_Cross", "涨停后用一进二紧密度>=37+非假题材裁判(紧板连板/烂板次日开出)", {
    "zt_judge_fn": lambda off, st, ft, r: "relay" if st.get("tight_good_zt", False) else "next_open",
}))
specs.append(("XF27b_1to2_tight_on_x10", "G4_Cross", "基于X10:仅紧封好板(>=37/非事件/0拉萨)破限价转连板", {
    "base_mode": "X10_v1",
    "zt_judge_fn": lambda off, st, ft, r: "relay" if st.get("tight_good_zt", False) else "next_open",
}))

# Run all!
ref_rets, ref_edts, ref_hlds, _, _ = bt.run_spec(sub, cb, feats, {"base_mode": "DecD_4d"})
x10_rets, _, _, _, _ = bt.run_spec(sub, cb, feats, {"base_mode": "X10_v1"})

all_rows = []
for nm, grp, desc, sp in specs:
    rets, edts, hlds, ehms, rsns = bt.run_spec(sub, cb, feats, sp)
    qm = bt.quick_metrics(sub, rets, edts, hlds, ref_rets=ref_rets)
    row = {
        "factor": nm, "group": grp, "desc": desc, "changed_vs_DecD4": qm["changed_all"],
        "P165_ss": qm["P165"]["ALL_ss_nav"], "P165_wr": qm["P165"]["ALL_ss_wr"],
        "P165_mdd": qm["P165"]["ALL_ss_mdd"], "P165_h": qm["P165"]["ALL_ss_h"],
        "P165_IS_s": qm["P165"]["IS_ss_nav"], "P165_OOS_s": qm["P165"]["OOS_ss_nav"],
        "P165_IS_d": qm["P165"]["IS_deq_nav"], "P165_OOS_d": qm["P165"]["OOS_deq_nav"],
        "P150_IS_s": qm["P150"]["IS_ss_nav"], "P150_OOS_s": qm["P150"]["OOS_ss_nav"],
        "P150_IS_d": qm["P150"]["IS_deq_nav"], "P150_OOS_d": qm["P150"]["OOS_deq_nav"],
        "P140_IS_d": qm["P140"]["IS_deq_nav"], "P140_OOS_d": qm["P140"]["OOS_deq_nav"],
        "P000_IS_d": qm["P000"]["IS_deq_nav"], "P000_OOS_d": qm["P000"]["OOS_deq_nav"],
        "P000_ALL_d": qm["P000"]["ALL_deq_nav"],
    }
    all_rows.append(row)

res_df = pd.DataFrame(all_rows)
res_df.to_csv(f"{F3_DIR}/_raw_27_factors_scan.csv", index=False, encoding="utf-8-sig")

ref_row = res_df[res_df["factor"] == "XF28_DecD_4d"].iloc[0]
print("=== [BASELINE] XF28_DecD_4d vs B1_X10 vs XF29_RD ===")
cols_show = ["factor", "changed_vs_DecD4", "P165_ss", "P165_IS_d", "P165_OOS_d", "P150_IS_d", "P150_OOS_d", "P140_IS_d", "P140_OOS_d", "P000_IS_d", "P000_OOS_d"]
print(res_df[res_df["factor"].isin(["B1_X10_v1_strict", "XF28_DecD_4d", "XF29a_RD_2d", "XF29b_RD_3d"])][cols_show].to_string(index=False))

# Check which factors improve IS across >= 3 pools over DecD_4d!
res_df["is_beat_cnt"] = (
    (res_df["P165_IS_d"] > ref_row["P165_IS_d"] + 1e-4).astype(int)
    + (res_df["P150_IS_d"] > ref_row["P150_IS_d"] + 1e-4).astype(int)
    + (res_df["P140_IS_d"] > ref_row["P140_IS_d"] + 1e-4).astype(int)
    + (res_df["P000_IS_d"] > ref_row["P000_IS_d"] + 1e-4).astype(int)
)
res_df["oos_beat_cnt"] = (
    (res_df["P165_OOS_d"] > ref_row["P165_OOS_d"] + 1e-4).astype(int)
    + (res_df["P150_OOS_d"] > ref_row["P150_OOS_d"] + 1e-4).astype(int)
    + (res_df["P140_OOS_d"] > ref_row["P140_OOS_d"] + 1e-4).astype(int)
    + (res_df["P000_OOS_d"] > ref_row["P000_OOS_d"] + 1e-4).astype(int)
)
res_df["is_gm"] = (res_df["P165_IS_d"] * res_df["P150_IS_d"] * res_df["P140_IS_d"] * res_df["P000_IS_d"]) ** 0.25
res_df["oos_gm"] = (res_df["P165_OOS_d"] * res_df["P150_OOS_d"] * res_df["P140_OOS_d"] * res_df["P000_OOS_d"]) ** 0.25

print("\n=== ALL FACTORS RANKED BY PURE IS GEOMETRIC MEAN (vs DecD_4d) ===")
print(res_df.sort_values("is_gm", ascending=False)[cols_show + ["is_beat_cnt", "oos_beat_cnt", "is_gm", "oos_gm"]].to_string(index=False))
print(f"\nDone in {time.time()-t0:.1f}s")
