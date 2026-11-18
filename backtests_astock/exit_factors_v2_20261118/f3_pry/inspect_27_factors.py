#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Quickly inspect hit rates & conditional returns of all 27 holding factors across P165/P150/P140/P000."""
import os, sys, pickle, time
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
S3_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
for d in (S3_DIR, F3_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

import run_exit_scan as base
import generate_final_report_and_audit as gen_pry
import pit_data_loaders as pdl
import pit_env_comm_loaders as pec
import factor_signals as fs

t0 = time.time()
df = pd.read_parquet(f"{SIM}/backtests_astock2/p5_full_pry_universe/full_pry_master_enriched.parquet")
with open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb") as f:
    cb = pickle.load(f)["code_bars"]
sub = base.build_base_candidates(df, cb)
codes = set(sub["code"])

lhb_map = pdl.load_lhb_pit(codes)
stock_notices, ex_reg = pdl.load_notices_and_reg_pit(codes)
xq_map, gb_map, ir_map = pec.load_community_and_ir_pit(codes)
kpl_ds, kpl_dp, kpl_hist, tape_map = pec.load_kpl_and_zt_tape(codes)
env_map, rt_map, hd_rate_map, csrc_zt_map, csrc_ind_map = pec.load_market_env_maps(cb)

ctx = {
    "lhb_map": lhb_map, "stock_notices": stock_notices, "ex_reg": ex_reg,
    "xq_map": xq_map, "gb_map": gb_map, "ir_map": ir_map,
    "kpl_ds": kpl_ds, "kpl_dp": kpl_dp, "kpl_hist": kpl_hist, "tape_map": tape_map,
    "env_map": env_map, "rt_map": rt_map, "hd_rate_map": hd_rate_map,
    "csrc_zt_map": csrc_zt_map, "csrc_ind_map": csrc_ind_map,
}
feats = fs.compute_all_holding_factors(sub, cb, ctx)

# Baseline DecD_4d returns
fn_dec = gen_pry.make_dec_985(4, 0.985, 0.985, True)
dec_rets = np.array([fn_dec(cb[r.c6], r.p0, r.buy_px, r)[0] for r in sub.itertuples(index=False)], dtype=float)

# Save precomputed feats + sub + dec_rets cache in F3_DIR for ultra-fast iteration!
with open(f"{F3_DIR}/_cache_feats_830.pkl", "wb") as f:
    pickle.dump({"sub": sub, "feats": feats, "dec_rets": dec_rets, "ctx": ctx}, f)

# Inspect hit counts for key flags at T+1 (steps[1])
def chk(name, fn_cond):
    m = np.array([bool(fn_cond(feats[i], sub.iloc[i])) for i in range(len(sub))])
    p165 = sub["score"].values >= 165
    p150 = sub["score"].values >= 150
    is_m = sub["buy_date"].values <= "2023-12-31"
    h_mean = dec_rets[m].mean() * 100 if m.sum() else np.nan
    nh_mean = dec_rets[~m].mean() * 100 if (~m).sum() else np.nan
    print(f"{name:<28} | P000:{m.sum():3d}(IS:{(m&is_m).sum():2d},OOS:{(m&~is_m).sum():3d}) | P150:{(m&p150).sum():3d} | P165:{(m&p165).sum():3d} | DecD mean hit/no: {h_mean:+.2f}% / {nh_mean:+.2f}%")

chk("XF01_lhasa_cnt>=1_D0", lambda ft, r: ft["steps"][1]["lhasa_d0"] >= 1)
chk("XF01_lhasa_cnt>=2_D0", lambda ft, r: ft["steps"][1]["lhasa_d0"] >= 2)
chk("XF01_lhasa_any_hold>=1", lambda ft, r: any(ft["steps"][k]["lhasa_cnt"] >= 1 for k in ft["steps"] if k >= 1))
chk("XF02_daysurf_T1", lambda ft, r: ft["steps"][1]["daysurf"])
chk("XF03_inst_net>0_T1", lambda ft, r: ft["steps"][1]["inst_net"] > 0)
chk("XF03_inst_buy>0_T1", lambda ft, r: ft["steps"][1]["inst_buy"] > 0)
chk("XF03_inst_net<0_T1", lambda ft, r: ft["steps"][1]["inst_net"] < 0)
chk("XF04_yz_buy_T1", lambda ft, r: ft["steps"][1]["yz_buy"])
chk("XF05_quant>=1_T1", lambda ft, r: ft["steps"][1]["quant_cnt"] >= 1)
chk("XF06_big_net_sell_T1", lambda ft, r: ft["steps"][1]["big_net_sell"])
chk("XF07_bad_notice_T1", lambda ft, r: ft["steps"][1]["bad_notice"])
chk("XF07_bad_notice_any", lambda ft, r: any(ft["steps"][k]["bad_notice"] for k in ft["steps"] if k >= 1))
chk("XF08_ex_reg5>=2_T1", lambda ft, r: ft["steps"][1]["ex_reg5"] >= 2)
chk("XF09_xq_cnt>=1_T1", lambda ft, r: ft["steps"][1]["xq_cnt"] >= 1)
chk("XF10_gb_ratio>=3_T1", lambda ft, r: ft["steps"][1]["gb_ratio"] >= 3.0 and ft["steps"][1]["gb_overnight"] >= 5)
chk("XF11_good_notice_T1", lambda ft, r: ft["steps"][1]["good_notice"])
chk("XF12_ir_active_T1", lambda ft, r: ft["steps"][1]["ir_active"])
chk("XF13_mkt_open_zt<5_T1", lambda ft, r: ft["steps"][1]["mkt_open_zt"] < 5)
chk("XF13_mkt_open_zt<8_T1", lambda ft, r: ft["steps"][1]["mkt_open_zt"] < 8)
chk("XF13_mkt_open_dt>=10_T1", lambda ft, r: ft["steps"][1]["mkt_open_dt"] >= 10)
chk("XF13_mkt_open_dt>=20_T1", lambda ft, r: ft["steps"][1]["mkt_open_dt"] >= 20)
chk("XF14_fb_open_avg<0_T1", lambda ft, r: ft["steps"][1]["fb_open_avg"] < 0.0)
chk("XF14_prev_brk_dt>=0.3", lambda ft, r: ft["steps"][1]["prev_brk_dt_r"] >= 0.30)
chk("XF15_csi_drop<-1.5%_T1", lambda ft, r: ft["steps"][1]["prev_csi_pct"] < -0.015)
chk("XF16_prev_n_dt>=30_T1", lambda ft, r: ft["steps"][1]["prev_n_dt"] >= 30)
chk("XF16_prev_n_dt<10_T1", lambda ft, r: ft["steps"][1]["prev_n_dt"] < 10)
chk("XF17_hd_brk_r10>=20%", lambda ft, r: ft["steps"][1]["hd_brk_r10"] >= 0.20)
chk("XF17_hd_reb_zt>=20%", lambda ft, r: ft["steps"][1]["hd_reb_zt_r10"] >= 0.20)
chk("XF18_prev_n_zt>=60_T1", lambda ft, r: ft["steps"][1]["prev_n_zt"] >= 60)
chk("XF19_kpl_mates>=1_T1", lambda ft, r: ft["steps"][1]["kpl_mates"] >= 1)
chk("XF19_csrc_mates>=2_T1", lambda ft, r: ft["steps"][1]["csrc_mates"] >= 2)
chk("XF20_promo_1to2>=20%", lambda ft, r: ft["steps"][1]["prev_promo"] >= 0.20)
chk("XF21_d0_strong_yang", lambda ft, r: ft["d0_strong_yang"])
chk("XF21_d0_ugly_fade", lambda ft, r: ft["d0_ugly_fade"])
chk("XF22_d0_real_to>20%", lambda ft, r: ft["d0_real_to"] > 20.0)
chk("XF22_d0_real_to>45%", lambda ft, r: ft["d0_real_to"] > 45.0)
chk("XF22_d0_real_to<6%", lambda ft, r: ft["d0_real_to"] < 6.0)
chk("XF23_t1_gap<-2.0%", lambda ft, r: ft["steps"][1]["o_gap"] < -0.020)
chk("XF23_t1_gap<-1.5%", lambda ft, r: ft["steps"][1]["o_gap"] < -0.015)
chk("XF24_t1_gap>=+2.0%", lambda ft, r: ft["steps"][1]["o_gap"] >= 0.020)
chk("XF27_d0_tight_zt", lambda ft, r: ft["steps"][0]["tight_good_zt"])
chk("XF27_d0_loose_zt", lambda ft, r: ft["steps"][0]["loose_bad_zt"])
chk("XF27_t1_tight_zt", lambda ft, r: ft["steps"][1]["tight_good_zt"])
chk("XF27_t1_loose_zt", lambda ft, r: ft["steps"][1]["loose_bad_zt"])
print(f"Done in {time.time()-t0:.1f}s")
