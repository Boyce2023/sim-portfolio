#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Enrich factor_30_marginal_table.csv with exact raw trigger frequencies, ss/deq WR & MDD across all 4 pools."""
import os, sys, pickle
import numpy as np
import pandas as pd

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
S3_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
for d in (S3_DIR, F3_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

import run_exit_scan as base
import backtest_30_factors as bt
from run_f3_audit_part1 import make_xf30_spec

cache = pickle.load(open(f"{F3_DIR}/_cache_feats_830.pkl", "rb"))
sub, feats = cache["sub"], cache["feats"]
cb = pickle.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb"))["code_bars"]

# Exact trigger predicates for XF01..XF30
pred_map = {
    "XF01_d0_lhasa_trap": lambda ft, r: any(ft["steps"][k].get("lhasa_cnt", 0) >= 1 for k in ft["steps"] if k >= 1),
    "XF02_d0_daysurf_in": lambda ft, r: any(ft["steps"][k].get("daysurf", False) for k in ft["steps"] if k >= 1),
    "XF03_d0_inst_net_buy_vs_sell": lambda ft, r: any(ft["steps"][k].get("inst_net", 0.0) != 0.0 for k in ft["steps"] if k >= 1),
    "XF04_d0_top_youzi_in": lambda ft, r: any(ft["steps"][k].get("yz_buy", False) or ft["steps"][k].get("yz_sell", False) for k in ft["steps"] if k >= 1),
    "XF05_lhb_quant_churn": lambda ft, r: any(ft["steps"][k].get("quant_cnt", 0) >= 1 for k in ft["steps"] if k >= 1),
    "XF06_north_or_big_net_sell": lambda ft, r: any(ft["steps"][k].get("big_net_sell", False) for k in ft["steps"] if k >= 1),
    "XF07_hold_bad_notice": lambda ft, r: any(ft["steps"][k].get("bad_notice", False) for k in ft["steps"] if k >= 1),
    "XF08_ex_reg5_ge2": lambda ft, r: any(ft["steps"][k].get("ex_reg5", 0) >= 2 for k in ft["steps"] if k >= 1),
    "XF09_xq_spike_hold": lambda ft, r: any(ft["steps"][k].get("xq_cnt", 0) >= 1 for k in ft["steps"] if k >= 1),
    "XF10_guba_panic_spike": lambda ft, r: any(ft["steps"][k].get("gb_ratio", 0.0) >= 3.0 and ft["steps"][k].get("gb_overnight", 0) >= 5 for k in ft["steps"] if k >= 1),
    "XF11_good_buyback_win_notice": lambda ft, r: any(ft["steps"][k].get("good_notice", False) for k in ft["steps"] if k >= 1),
    "XF12_ir_pit_hold": lambda ft, r: any(ft["steps"][k].get("ir_active", False) for k in ft["steps"] if k >= 1),
    "XF13_t1_mkt_open_zt_ice": lambda ft, r: any(ft["steps"][k].get("mkt_open_zt", 10) < 5 for k in ft["steps"] if k >= 1),
    "XF14_mkt_fb_open_neg": lambda ft, r: any(ft["steps"][k].get("fb_open_avg", 0.0) < 0.0 for k in ft["steps"] if k >= 1),
    "XF15_csi300_panic_drop": lambda ft, r: any(ft["steps"][k].get("prev_csi_pct", 0.0) < -0.015 for k in ft["steps"] if k >= 1),
    "XF16_mkt_dt_surge": lambda ft, r: any(ft["steps"][k].get("prev_n_dt", 99) < 10 for k in ft["steps"] if k >= 1),
    "XF17_rebound_rate10_hot": lambda ft, r: any(ft["steps"][k].get("hd_reb_zt_r10", 0.0) >= 0.20 for k in ft["steps"] if k >= 1),
    "XF18_mkt_zt_surge": lambda ft, r: any(ft["steps"][k].get("prev_n_zt", 0) >= 60 for k in ft["steps"] if k >= 1),
    "XF19_plate_has_zt_mates": lambda ft, r: any(ft["steps"][k].get("csrc_mates", 0) >= 2 for k in ft["steps"] if k >= 1),
    "XF20_promo_1to2_warm": lambda ft, r: any(ft["steps"][k].get("prev_promo", 0.0) >= 0.20 for k in ft["steps"] if k >= 1),
    "XF21_d0_candle_clv": lambda ft, r: bool(ft.get("d0_strong_yang", False)),
    "XF22_d0_real_to_death": lambda ft, r: ft.get("d0_real_to", 0.0) > 20.0,
    "XF23_t1_open_gap_down": lambda ft, r: ft["steps"].get(1, {}).get("o_gap", 0.0) < -0.020,
    "XF24_t1_open_strong_gap": lambda ft, r: ft["steps"].get(1, {}).get("o_gap", 0.0) >= 0.020,
    "XF25_vol_shrink_stall": lambda ft, r: any(ft["steps"][k].get("to_vr", 1.0) < 0.70 for k in (1, 2) if k in ft["steps"]),
    "XF26_touch_ma5_ma10_resist": lambda ft, r: True,
    "XF27_1to2_tightness_after_zt": lambda ft, r: any(ft["steps"][k].get("tight_good_zt", False) or ft["steps"][k].get("loose_bad_zt", False) for k in ft["steps"]),
    "XF28_DecD_4d_step": lambda ft, r: True,
    "XF29_RD_t1_gap2_2d": lambda ft, r: True,
    "XF30_V21_Dynamic_Factor_Step": lambda ft, r: True,
}

# Reconstruct specs for the 30 canonical rows from sweep_27_factors + XF30
import sweep_27_factors as sw
spec_dict = {nm: sp for nm, _, _, sp in sw.specs}
spec_dict["XF30_C4_13_21_16"] = make_xf30_spec(5, 0.70, 10, 0.03, True)

tdf = pd.read_csv(f"{F3_DIR}/factor_30_marginal_table.csv")
is_m = sub["buy_date"].values <= "2023-12-31"
p165_m = sub["score"].values >= 165

extra_cols = []
for row in tdf.itertuples(index=False):
    fid = row.factor_id
    rk = row.raw_variant
    fn_p = pred_map[fid]
    m_hit = np.array([bool(fn_p(feats[i], sub.iloc[i])) for i in range(len(sub))])
    sp = spec_dict[rk]
    rets, edts, hlds, _, _ = bt.run_spec(sub, cb, feats, sp)
    ev150 = base.eval_variant(sub, rets, edts, hlds, 150)
    ev140 = base.eval_variant(sub, rets, edts, hlds, 140)
    ev000 = base.eval_variant(sub, rets, edts, hlds, 0)
    extra_cols.append({
        "raw_hits_P000": int(m_hit.sum()),
        "raw_hit_pct_P000": round(float(m_hit.mean() * 100.0), 1),
        "raw_hits_IS": int((m_hit & is_m).sum()),
        "raw_hits_OOS": int((m_hit & ~is_m).sum()),
        "raw_hits_P165": int((m_hit & p165_m).sum()),
        "P150_IS_ss": ev150["IS"]["ss"]["nav"],
        "P150_OOS_ss": ev150["OOS"]["ss"]["nav"],
        "P150_ALL_deq_wr": ev150["ALL"]["deq"]["wr"],
        "P150_ALL_deq_mdd": ev150["ALL"]["deq"]["mdd"],
        "P140_ALL_deq_wr": ev140["ALL"]["deq"]["wr"],
        "P140_ALL_deq_mdd": ev140["ALL"]["deq"]["mdd"],
        "P000_ALL_deq_wr": ev000["ALL"]["deq"]["wr"],
        "P000_ALL_deq_mdd": ev000["ALL"]["deq"]["mdd"],
    })

edf = pd.DataFrame(extra_cols)
out = pd.concat([tdf[["factor_id", "raw_variant", "group", "rule_desc"]], edf, tdf.drop(columns=["factor_id", "raw_variant", "group", "rule_desc"])], axis=1)
out.to_csv(f"{F3_DIR}/factor_30_marginal_table.csv", index=False, encoding="utf-8-sig")
print("Enriched factor_30_marginal_table.csv:", out.shape)
print(out[["factor_id", "raw_hits_P000", "raw_hits_IS", "raw_hits_OOS", "changed_trades_vs_DecD4", "P165_ss_nav", "P165_ss_wr", "P150_IS_deq", "P150_OOS_deq", "P000_ALL_deq", "verdict"]].to_string(index=False))
