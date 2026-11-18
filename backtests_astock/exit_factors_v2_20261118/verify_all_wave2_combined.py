import sys, json, pickle, pandas as pd, numpy as np

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
W2 = f"{SIM}/backtests_astock/exit_factors_v2_20261118"
W1 = f"{SIM}/backtests_astock/exit_opt_20261118"
CLEAN16 = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
UPG17 = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
for p in (f"{W2}/f3_pry", f"{W2}/f2_2to3", f"{W2}/f1_3to4", f"{W1}/s3_pry_exit", f"{W1}/s2_2to3_exit", CLEAN16):
    if p not in sys.path:
        sys.path.insert(0, p)

import synthesize_master_clean_20261116 as syn16
import run_exit_scan as base_pry
import generate_final_report_and_audit as gen_pry
import backtest_30_factors as bt3_pry

# 1. 3to4 Base vs XF30_7f_ge1 (note: ledger_upg_3to4_std vs ledger_3to4_xf30_std; also check unmasked 115 signals!)
d_34_base = syn16.standardize_ledger(f"{UPG17}/ledger_upg_3to4_std.csv", "三进四", 1)
d_34_w2   = syn16.standardize_ledger(f"{W2}/f1_3to4/ledger_3to4_xf30_std.csv", "三进四", 1)
d_hd      = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴", 2)
d_12      = syn16.standardize_ledger(f"{UPG17}/ledger_upg_1to2.csv", "一进二", 5)

# 2. Pry Base vs Wave1 DecD4 vs Wave2 XF30_V21
s3_w2 = json.load(open(f"{W2}/f3_pry/summary_pry_exit_factors.json"))
print("S3 W2 5strat Base X10:", s3_w2["models"]["B1_X10_v1_strict"]["portfolio_5strat_5y"]["win_rate"], s3_w2["models"]["B1_X10_v1_strict"]["portfolio_5strat_oos"]["max_dd_pct"])
print("S3 W2 5strat XF30_V21:", s3_w2["models"]["XF30_V21"]["portfolio_5strat_5y"]["win_rate"], s3_w2["models"]["XF30_V21"]["portfolio_5strat_oos"]["max_dd_pct"])

# Get exact unmasked top25 for XF30_V21 from f3_pry cache
pk_pry = pickle.load(open(f"{W2}/f3_pry/_cache_feats_830.pkl", "rb"))
sub_p = pk_pry["sub"]
feats_p = pk_pry["feats"]
ctx_p = pk_pry["ctx"]
import run_f3_audit_part1 as f3p1
ldf_b1  = f3p1.eval_model_ledger(sub_p, feats_p, ctx_p, "B1_X10_v1_strict")
ldf_v21 = f3p1.eval_model_ledger(sub_p, feats_p, ctx_p, "XF30_V21")

def top25_pry(ldf):
    t = ldf[ldf["score"] >= 165].sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    return t[["buy_date", "exit_date", "code", "name", "net_ret", "score", "buy_hhmm", "exit_hhmm"]].assign(strategy="超跌撬板", priority=3)

d_pry_b1  = top25_pry(ldf_b1)
d_pry_v21 = top25_pry(ldf_v21)

# 3. 2to3 Track2 Base (5.0%) vs Opt_V21 (6.5%) vs Opt_V21 + XF03
c23_h = pickle.load(open(f"{W2}/f2_2to3/_cache_holding_factors_full.pkl", "rb"))
import exit_factor_engine as efe23
c23 = pickle.load(open(f"{W1}/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
supp5m = pickle.load(open(f"{W1}/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "rb"))
import exit_engine as ee23
b5m2 = {**c23["b5m_need"], **supp5m["supp_5m"]}
da = c23["da_need"]; all_dts = c23["all_dts"]; dt_idx = {x: i for i, x in enumerate(all_dts)}
idx_c = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
gated23 = c23["gated_all"]
sub90 = gated23[(gated23["score_v2"] >= 90) & (gated23["buy_date"] >= "2021-11-15")].copy()
sub90["c6_str"] = sub90["code"].astype(str).str.zfill(6)
plook, stk_hist = ee23.build_lookups(da[da["c6"].isin(set(sub90["c6_str"]))].copy())

def make_23(drop_th):
    cfg = ee23.ExitConfig("cfg", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=drop_th)
    r, ed, eh, _ = ee23.sim_exit_all(sub90, plook, stk_hist, b5m2, all_dts, dt_idx, idx_c["sh000002"], idx_c["sz399107"], cfg)
    tmp = pd.concat([sub90.reset_index(drop=True), pd.DataFrame({"net_ret": r, "exit_date": ed, "exit_hhmm": eh})], axis=1)
    top1 = tmp.sort_values(["buy_date", "score_v2", "open_pct", "plate_sz", "c6_str"], ascending=[True, False, True, True, True]).groupby("buy_date", as_index=False).first()
    return pd.DataFrame({"buy_date": top1["buy_date"], "exit_date": top1["exit_date"], "code": top1["c6_str"], "name": top1["name"], "net_ret": top1["net_ret"], "score": top1["score_v2"], "buy_hhmm": 925, "exit_hhmm": top1["exit_hhmm"], "strategy": "二进三", "priority": 4})

d_23_b0  = make_23(0.050)
d_23_v21 = make_23(0.065)
# Also check XF03 ledger_xf30 or scan_29factors_raw for XF03!
raw29 = pickle.load(open(f"{W2}/f2_2to3/_scan_29factors_raw.pkl", "rb"))
print("raw29 type/keys:", type(raw29), list(raw29.keys())[:5] if isinstance(raw29, dict) else len(raw29))

for lbl, s34, spry, s23 in [
    ("Base_All_Original (100% 5m)", d_34_base, d_pry_b1, d_23_b0),
    ("Wave2_Upgraded    (100% 5m)", d_34_w2,   d_pry_v21, d_23_v21),
]:
    pool = pd.concat([s34, d_hd, spry, s23, d_12], ignore_index=True)
    slot = syn16.run_1slot(pool)
    for w, d0 in [("5Y", "2021-11-15"), ("Near3Y", "2023-11-16"), ("OOS24_26", "2024-01-01"), ("2026", "2026-01-01")]:
        s = slot[slot["buy_date"] >= d0]
        r = s["net_ret"].to_numpy()
        wr = float((r > 0).mean() * 100)
        plr = float(r[r > 0].mean() / abs(r[r <= 0].mean()))
        cum = np.cumprod(1.0 + r)
        mdd = float(np.max(1.0 - cum / np.maximum.accumulate(cum)) * 100)
        print(f"  {lbl} | {w:8s} | n={len(s):3d} | WR={wr:5.2f}% | PLR={plr:4.2f} | MDD={mdd:5.2f}% | NAV={cum[-1]:,.2f}x")
    bd = slot[slot["buy_date"] >= "2021-11-15"].groupby("strategy").agg(n=("net_ret","count"), wr=("net_ret", lambda x: round((x>0).mean()*100,2)), mean=("net_ret", lambda x: round(x.mean()*100,2))).to_dict("index")
    print("   Breakdown:", bd)
