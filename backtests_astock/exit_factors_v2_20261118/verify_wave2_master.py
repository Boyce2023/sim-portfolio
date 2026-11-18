import sys, json, pickle, pandas as pd, numpy as np

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
W2 = f"{SIM}/backtests_astock/exit_factors_v2_20261118"
W1 = f"{SIM}/backtests_astock/exit_opt_20261118"
CLEAN16 = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
UPG17 = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, CLEAN16)
import synthesize_master_clean_20261116 as syn16

s3 = json.load(open(f"{W2}/f3_pry/summary_pry_exit_factors.json"))
print("=== 1. F3_PRY XF30_V21 Key Windows & Live 000011 ===")
m21 = s3["models"]["XF30_V21"]["P165"]
for w, v in m21.items():
    print(f"  {w:28s} | SS: n={v['ss']['n']} WR={v['ss']['wr']}% PLR={v['ss']['plr']} NAV={v['ss']['nav']}x MDD={v['ss']['mdd']}% Hold={v['ss']['avg_hold']}d | DEQ={v['deq']['nav']}x")
print("  S3 top-level keys:", [k for k in s3.keys() if k not in ("models", "csi300_benchmarks")])
for k in ("overfitting_8tests", "plateau_summary", "portfolio_synergy", "live_000011_20261118"):
    if k in s3:
        print(f"  [{k}]:", str(s3[k])[:500])
