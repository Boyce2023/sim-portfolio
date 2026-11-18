import json, pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118"
SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
s2 = json.load(open(f"{ROOT}/s2_2to3_exit/summary_2to3_exit_opt.json"))
s3 = json.load(open(f"{ROOT}/s3_pry_exit/summary_pry_exit_opt.json"))

print("=== 1. S2 Track1(23.8% 5m) vs Track2(100% 5m) Stage D Reconciliation ===")
t1_list = {x["name"]: x for x in s2["all_263_variants_track1"]}
t2_list = {x["name"]: x for x in s2["all_263_variants_track2"]}
for k in t2_list:
    if any(w in k.lower() for w in ["base", "forgive", "imm", "d_", "zero", "6.5", "65"]):
        a = t1_list.get(k, {})
        b = t2_list.get(k, {})
        if str(k).startswith(("BASE", "D", "C_1345_p8.5_d6.5", "J_")):
            print(f"  {k:28s} | T1_5Y={a.get('s90_5y_nav')} (IS={a.get('s90_is_nav')}, OOS={a.get('s90_oos_nav')}) | T2_5Y={b.get('s90_5y_nav')} (IS={b.get('s90_is_nav')}, OOS={b.get('s90_oos_nav')}, 96_IS={b.get('s96_is_nav')}, 96_OOS={b.get('s96_oos_nav')})")

# Print sample keys if none matched prefix
sample_d = [k for k in t2_list if "forgive" in k.lower() or "d_" in k.lower() or "zero" in k.lower() or "imm" in k.lower() or "base" in k.lower()][:12]
for k in sample_d:
    a, b = t1_list[k], t2_list[k]
    print(f"  * {k:28s} | T1: { {kk:a[kk] for kk in list(a.keys())[1:6]} } | T2: { {kk:b[kk] for kk in list(b.keys())[1:6]} }")
