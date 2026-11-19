#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import json, sys
import pandas as pd

ABL_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/ablation_1to2_price60_20261119"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, ABL_DIR)
sys.path.insert(0, UPG_DIR)

import upgrade_1to2_pit as u
from pit_signal_base import build_base_ctx_pit, apply_variant_v19
from run_ablation_price60 import inspect_forensics_nonfatal

# 1. Assert all 6 variants pass 1S forensics (T+0=0, overlap=0, yizi=0, 5m=100%)
with open(f"{ABL_DIR}/ablation_summary.json", encoding="utf-8") as f:
    summ = json.load(f)
for fk in ["fee_30bps", "fee_20bps"]:
    for vn, obj in summ[fk].items():
        f1 = obj["forensics_1s"]
        assert f1["t0_violations"] == 0, f"{fk} {vn} T+0!=0"
        assert f1["overlap_violations"] == 0, f"{fk} {vn} overlap!=0"
        assert f1["yizi_buy_violations"] == 0, f"{fk} {vn} yizi!=0"
        assert f1["five_min_coverage_pct"] == 100.0 and len(f1["five_min_missing_days"]) == 0, f"{fk} {vn} 5m<100%"

# 2. Assert NoCap 2024-12-31 physical truncation zero lookahead leak
u.FEE_RATE = 0.0030
df_full_nc = pd.read_csv(f"{ABL_DIR}/NoCap_1s_30bps.csv", dtype={"code": str})
pre25_full = df_full_nc[(df_full_nc["buy_date"] <= "2024-12-31") & (df_full_nc["exit_date"] <= "2024-12-31")].reset_index(drop=True)

base_trunc = build_base_ctx_pit("2024-12-31")
ctx_trunc = apply_variant_v19(base_trunc, price_cap=None, soft_pen_gt60=0.0)
sim_trunc = u.make_trade_sim(ctx_trunc, use_m1_d3_exempt=True)
tr_trunc, _, _ = u.run_slot_and_eq(ctx_trunc, ctx_trunc["mask_v19"], "_sv_v19", sim_trunc, u.CANON_5Y_START, "2024-12-31")
f_tr = inspect_forensics_nonfatal(tr_trunc, ctx_trunc)
assert f_tr["five_min_coverage_pct"] == 100.0
tr_trunc_cmp = [t for t in tr_trunc if t["exit_date"] <= "2024-12-31"]
assert len(pre25_full) == len(tr_trunc_cmp), f"Trunc len mismatch: {len(pre25_full)} vs {len(tr_trunc_cmp)}"

max_diff_ret = 0.0
max_diff_sc = 0.0
for a, b in zip(pre25_full.itertuples(index=False), tr_trunc_cmp):
    assert str(a.buy_date) == str(b["buy_date"]) and str(a.code).zfill(6) == str(b["code"]).zfill(6)
    max_diff_ret = max(max_diff_ret, abs(float(a.net_ret) - float(b["net_ret"])))
    max_diff_sc = max(max_diff_sc, abs(float(a.score) - float(b["score"])))

assert max_diff_ret == 0.0 and max_diff_sc == 0.0, f"Leak detected: ret={max_diff_ret}, sc={max_diff_sc}"
print(f"[ALL ASSERTS PASSED] 6 variants x 2 fees 5m=100%, NoCap 2024-12-31 truncation checked={len(tr_trunc_cmp)}, max_diff=0.0")
