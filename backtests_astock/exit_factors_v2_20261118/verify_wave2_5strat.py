import sys, json, pickle, pandas as pd, numpy as np

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
W2 = f"{SIM}/backtests_astock/exit_factors_v2_20261118"
W1 = f"{SIM}/backtests_astock/exit_opt_20261118"
CLEAN16 = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
UPG17 = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
for p in (f"{W2}/f3_pry", f"{W2}/f2_2to3", f"{W1}/s3_pry_exit", f"{W1}/s2_2to3_exit", CLEAN16):
    if p not in sys.path:
        sys.path.insert(0, p)

import synthesize_master_clean_20261116 as syn16

# 1. Load 3to4 Base vs XF30_7f_ge1
d_34_base = syn16.standardize_ledger(f"{UPG17}/ledger_upg_3to4_std.csv", "三进四", 1)
d_34_w2   = syn16.standardize_ledger(f"{W2}/f1_3to4/ledger_3to4_xf30_std.csv", "三进四", 1)
d_hd      = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴", 2)
d_12      = syn16.standardize_ledger(f"{UPG17}/ledger_upg_1to2.csv", "一进二", 5)

# 2. Load Pry Base vs Wave1 DecD4 vs Wave2 XF30_V21 (from f3_pry)
s3_w2 = json.load(open(f"{W2}/f3_pry/summary_pry_exit_factors.json"))
print("000011 V2.1 plan:", json.dumps(s3_w2["live_000011_20261118"], ensure_ascii=False)[:900])

# Load unmasked daily top1 for pry XF30_V21 & 2to3 XF03
import backtest_30_factors as bt3_pry
feats = pickle.load(open(f"{W2}/f3_pry/_cache_feats_830.pkl", "rb"))
print("feats keys:", list(feats.keys()) if isinstance(feats, dict) else type(feats))
