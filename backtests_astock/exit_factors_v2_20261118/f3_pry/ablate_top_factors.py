#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
ablate_top_factors.py
Deep ablation & +/-20% plateau check on all top IS winners before locking XF30 (V2.1).
Also checks XF09 xueqiu crawl-coverage bias and tests XF27 1to2 tightness variants.
"""
import os, sys, pickle, time
import numpy as np
import pandas as pd

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
sys.path.insert(0, F3_DIR)
import backtest_30_factors as bt

cache = pickle.load(open(f"{F3_DIR}/_cache_feats_830.pkl", "rb"))
sub, feats = cache["sub"], cache["feats"]
cb = pickle.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb"))["code_bars"]

ref_rets, _, _, _, _ = bt.run_spec(sub, cb, feats, {"base_mode": "DecD_4d"})


def test_list(title, item_list):
    print(f"\n=== {title} ===")
    rows = []
    for nm, sp in item_list:
        rets, edts, hlds, _, _ = bt.run_spec(sub, cb, feats, sp)
        qm = bt.quick_metrics(sub, rets, edts, hlds, ref_rets=ref_rets)
        rows.append({
            "name": nm, "ch": qm["changed_all"],
            "P165_ss": qm["P165"]["ALL_ss_nav"], "P165_wr": qm["P165"]["ALL_ss_wr"], "P165_h": qm["P165"]["ALL_ss_h"],
            "65_IS_d": qm["P165"]["IS_deq_nav"], "65_OO_d": qm["P165"]["OOS_deq_nav"],
            "50_IS_d": qm["P150"]["IS_deq_nav"], "50_OO_d": qm["P150"]["OOS_deq_nav"],
            "40_IS_d": qm["P140"]["IS_deq_nav"], "40_OO_d": qm["P140"]["OOS_deq_nav"],
            "00_IS_d": qm["P000"]["IS_deq_nav"], "00_OO_d": qm["P000"]["OOS_deq_nav"],
            "00_ALL_d": qm["P000"]["ALL_deq_nav"],
        })
    print(pd.DataFrame(rows).to_string(index=False))


# 1. Ablate XF13 plateau: mkt_open_zt < {4,5,6,7} x {T1 only vs T1..T4} x {dt_ge in [0, 5, 10]}
xf13_items = [("DecD_4d_BASE", {"base_mode": "DecD_4d"})]
for zt_th in [4, 5, 6, 7]:
    for dt_th in [0, 10]:
        for t1_only in [True, False]:
            lbl = f"XF13_zt<{zt_th}_dt>={dt_th}_{'T1' if t1_only else 'all'}"
            xf13_items.append((lbl, {
                "preopen_cut_fn": (lambda zt0, dt0, t1: lambda off, st, ft, r: (
                    (not t1 or off == 1) and st.get("mkt_open_zt", 10) < zt0 and st.get("mkt_open_dt", 0) >= dt0
                ))(zt_th, dt_th, t1_only)
            }))
test_list("XF13 Plateau (mkt_open_zt x mkt_open_dt x T1/all)", xf13_items)

# 2. Ablate XF21c (d0_strong_yang): boost only vs exempt T1 weak cut only vs both, across CLV {0.6, 0.7, 0.8}
xf21_items = [("DecD_4d_BASE", {"base_mode": "DecD_4d"})]
for clv_th in [0.60, 0.70, 0.80]:
    for boost in [0.0, 0.02, 0.03, 0.04]:
        for ex_t1 in [False, True]:
            if boost == 0.0 and not ex_t1:
                continue
            lbl = f"XF21_clv{int(clv_th*100)}_b{int(boost*100)}_{'exT1' if ex_t1 else 'noEx'}"
            xf21_items.append((lbl, {
                "tp_sched_fn": (lambda c0, b0: lambda off, st, ft, r, btp: (
                    (btp + b0) if (btp is not None and ft["d0_true_yang"] and ft["d0_clv"] >= c0) else btp
                ))(clv_th, boost),
                "disable_default_eod_cut_fn": (lambda c0, ex: lambda off, st, ft, r: (
                    ex and off == 1 and ft["d0_true_yang"] and ft["d0_clv"] >= c0
                ))(clv_th, ex_t1),
            }))
test_list("XF21c Strong Yang Plateau (CLV x TP boost x T1 exempt)", xf21_items)

# 3. Ablate XF16b (prev_n_dt < {8,10,12}), XF19b (csrc_mates >= {1,2,3}), XF24 (t1_gap >= {1.5,2.0,2.5}), XF27
bull_items = [("DecD_4d_BASE", {"base_mode": "DecD_4d"})]
for ndt in [8, 10, 12]:
    for b in [0.02, 0.03, 0.04]:
        bull_items.append((f"XF16b_ndt<{ndt}_b{int(b*100)}", {
            "tp_sched_fn": (lambda n0, b0: lambda off, st, ft, r, btp: (btp + b0) if (btp is not None and st.get("prev_n_dt", 99) < n0) else btp)(ndt, b)
        }))
for cm in [1, 2, 3]:
    for b in [0.02, 0.03]:
        bull_items.append((f"XF19b_csrc>={cm}_b{int(b*100)}", {
            "tp_sched_fn": (lambda c0, b0: lambda off, st, ft, r, btp: (btp + b0) if (btp is not None and st.get("csrc_mates", 0) >= c0) else btp)(cm, b)
        }))
for gap in [0.015, 0.020, 0.025]:
    bull_items.append((f"XF24_t1gap>={gap*100:.1f}_relT2", {
        "tp_sched_fn": (lambda g0: lambda off, st, ft, r, btp: None if (off == 2 and ft["steps"].get(1, {}).get("o_gap", 0.0) >= g0) else btp)(gap)
    }))
    bull_items.append((f"XF24_t1gap>={gap*100:.1f}_b3", {
        "tp_sched_fn": (lambda g0: lambda off, st, ft, r, btp: (btp + 0.03) if (btp is not None and ft["steps"].get(1, {}).get("o_gap", 0.0) >= g0) else btp)(gap)
    }))
bull_items.append(("XF27_loose_t1_only_next_open", {
    "zt_judge_fn": lambda off, st, ft, r: "relay" if (off == 0 or st.get("tight_good_zt", False)) else "next_open"
}))
bull_items.append(("XF27_loose_all_eod_sell", {
    "zt_judge_fn": lambda off, st, ft, r: "relay" if st.get("tight_good_zt", False) else "next_open"
}))
test_list("XF16b / XF19b / XF24 / XF27 Plateau", bull_items)

# 4. Orthogonal combinations of top IS+OOS robust factors!
comb_items = [("DecD_4d_BASE", {"base_mode": "DecD_4d"})]

# Test combinations of:
#   A: XF13 (mkt_open_zt < 5 [or <5 & dt>=10] at 09:25)
#   B: XF21c (d0_strong_yang CLV>=0.7 -> +3% TP & exempt T1 weak cut)
#   C: XF16b (prev_n_dt < 10 -> +3% TP)
#   D: XF19b (csrc_mates >= 2 -> +3% TP)
#   E: XF24a (T+1 o_gap >= +2% -> release T+2 cap)
def make_combo(use_13=False, x13_dt=0, x13_t1=False, use_21=False, use_16=False, use_19=False, use_24=False, use_27=False):
    def preopen_cut(off, st, ft, r):
        if use_13:
            if (not x13_t1 or off == 1) and st.get("mkt_open_zt", 10) < 5 and st.get("mkt_open_dt", 0) >= x13_dt:
                return True
        return False

    def tp_sched(off, st, ft, r, btp):
        if btp is None:
            return None
        if use_24 and off == 2 and ft["steps"].get(1, {}).get("o_gap", 0.0) >= 0.020:
            return None
        boost = 0.0
        if use_21 and ft["d0_true_yang"] and ft["d0_clv"] >= 0.70:
            boost += 0.03
        if use_16 and st.get("prev_n_dt", 99) < 10:
            boost += 0.03
        if use_19 and st.get("csrc_mates", 0) >= 2:
            boost += 0.02
        return min(0.18, btp + boost) if boost > 0 else btp

    def dis_eod(off, st, ft, r):
        return bool(use_21 and off == 1 and ft["d0_true_yang"] and ft["d0_clv"] >= 0.70)

    sp = {"preopen_cut_fn": preopen_cut, "tp_sched_fn": tp_sched, "disable_default_eod_cut_fn": dis_eod}
    if use_27:
        sp["zt_judge_fn"] = lambda off, st, ft, r: "relay" if st.get("tight_good_zt", False) else "next_open"
    return sp


comb_items.extend([
    ("C1_13all_21", make_combo(use_13=True, x13_dt=0, use_21=True)),
    ("C2_13dt10_21", make_combo(use_13=True, x13_dt=10, use_21=True)),
    ("C3_13T1_21", make_combo(use_13=True, x13_dt=0, x13_t1=True, use_21=True)),
    ("C4_13all_21_16", make_combo(use_13=True, x13_dt=0, use_21=True, use_16=True)),
    ("C5_13dt10_21_16", make_combo(use_13=True, x13_dt=10, use_21=True, use_16=True)),
    ("C6_13all_21_16_24", make_combo(use_13=True, x13_dt=0, use_21=True, use_16=True, use_24=True)),
    ("C7_13dt10_21_16_24", make_combo(use_13=True, x13_dt=10, use_21=True, use_16=True, use_24=True)),
    ("C8_13all_21_16_19_24", make_combo(use_13=True, x13_dt=0, use_21=True, use_16=True, use_19=True, use_24=True)),
    ("C9_21_16", make_combo(use_21=True, use_16=True)),
    ("C10_21_16_24", make_combo(use_21=True, use_16=True, use_24=True)),
])
test_list("Orthogonal Combinations of Multi-Pool IS Winners", comb_items)
