import sys, json, pickle, pandas as pd, numpy as np

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
OPT = f"{SIM}/backtests_astock/exit_opt_20261118"
CLEAN16 = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
UPG17 = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
for p in (f"{OPT}/s3_pry_exit", f"{OPT}/s2_2to3_exit", UPG17, CLEAN16):
    if p not in sys.path:
        sys.path.insert(0, p)

import synthesize_master_clean_20261116 as syn16
import run_exit_scan as base_pry
import generate_final_report_and_audit as gen_pry
import exit_engine as ee23

# Load V19.0 Priority: 1=三进四V4.0, 2=高标首阴V5.1, 3=超跌撬板, 4=二进三, 5=一进二V19
d_34 = syn16.standardize_ledger(f"{UPG17}/ledger_upg_3to4_std.csv", "三进四V4.0", 1)
d_hd = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴V5.1", 2)
d_12 = syn16.standardize_ledger(f"{UPG17}/ledger_upg_1to2.csv", "一进二V19", 5)

# 2to3 daily unmasked top-1 (>=90)
c23 = pickle.load(open(f"{OPT}/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
supp5m = pickle.load(open(f"{OPT}/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "rb"))
b5m1 = c23["b5m_need"]
b5m2 = {**b5m1, **supp5m["supp_5m"]}
da = c23["da_need"]
all_dts = c23["all_dts"]
dt_idx = {x: i for i, x in enumerate(all_dts)}
idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
idx_sh, idx_sz = idx_cache["sh000002"], idx_cache["sz399107"]

gated23 = c23["gated_all"]
sub90 = gated23[(gated23["score_v2"] >= 90) & (gated23["buy_date"] >= "2021-11-15")].copy()
sub90["c6_str"] = sub90["code"].astype(str).str.zfill(6)
plook, stk_hist = ee23.build_lookups(da[da["c6"].isin(set(sub90["c6_str"]))].copy())

def make_2to3_top1(bmap, drop_th):
    cfg = ee23.ExitConfig("cfg", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=drop_th)
    r, ed, eh, _ = ee23.sim_exit_all(sub90, plook, stk_hist, bmap, all_dts, dt_idx, idx_sh, idx_sz, cfg)
    tmp = sub90.copy()
    tmp["net_ret"] = r; tmp["exit_date"] = ed; tmp["exit_hhmm"] = eh
    top1 = tmp.sort_values(["buy_date", "score_v2", "open_pct", "plate_sz", "c6_str"], ascending=[True, False, True, True, True]).groupby("buy_date", as_index=False).first()
    return pd.DataFrame({
        "buy_date": top1["buy_date"], "exit_date": top1["exit_date"],
        "code": top1["c6_str"], "name": top1["name"], "net_ret": top1["net_ret"],
        "score": top1["score_v2"], "buy_hhmm": 925, "exit_hhmm": top1["exit_hhmm"],
        "strategy": "二进三", "priority": 4
    })

d23_t1_base = make_2to3_top1(b5m1, 0.050)
d23_t1_opt  = make_2to3_top1(b5m1, 0.065)
d23_t2_base = make_2to3_top1(b5m2, 0.050)
d23_t2_opt  = make_2to3_top1(b5m2, 0.065)

# Pry daily unmasked top-1 (>=165)
df_pry, cb_pry, _, _, _, _, _ = base_pry.load_all_data()
sub_pry = base_pry.build_base_candidates(df_pry, cb_pry)

def make_pry_top1(fn):
    rows = []
    for r in sub_pry[sub_pry["score"] >= 165].itertuples(index=False):
        rv, ed, hd, eh, _ = fn(cb_pry[r.c6], r.p0, r.buy_px, r)
        rows.append({"buy_date": r.dt_str, "exit_date": ed, "code": r.c6, "name": r.name,
                     "net_ret": rv, "score": r.score, "bias10": r.bias10, "buy_hhmm": 925, "exit_hhmm": eh})
    pdf = pd.DataFrame(rows)
    top1 = pdf.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    top1["strategy"] = "超跌撬板"
    top1["priority"] = 3
    return top1[["buy_date", "exit_date", "code", "name", "net_ret", "score", "buy_hhmm", "exit_hhmm", "strategy", "priority"]]

pry_old = make_pry_top1(gen_pry.make_v1_strict())
pry_new = make_pry_top1(gen_pry.make_dec_985(4, 0.985, 0.985, True))
pry_2d  = make_pry_top1(gen_pry.make_dec_985(2, None, None, True))

def eval_5(label, d_pry, d_23):
    pool = pd.concat([d_34, d_hd, d_pry, d_23, d_12], ignore_index=True)
    slot = syn16.run_1slot(pool)
    slot5y = slot[slot["buy_date"] >= "2021-11-15"].copy()
    out_str = [f"=== {label} ==="]
    for name_w, dt0 in [("5Y", "2021-11-15"), ("Near3Y", "2023-11-16"), ("OOS24_26", "2024-01-01"), ("2026", "2026-01-01")]:
        s = slot[slot["buy_date"] >= dt0]
        r = s["net_ret"].to_numpy()
        wr = float((r > 0).mean() * 100)
        pos, neg = r[r > 0], r[r <= 0]
        plr = float(pos.mean() / abs(neg.mean())) if len(neg) and neg.mean() != 0 else 99.0
        nav = float(np.prod(1.0 + r))
        cum = np.cumprod(1.0 + r)
        mdd = float(np.max(1.0 - cum / np.maximum.accumulate(cum)) * 100)
        out_str.append(f"  {name_w:8s}: n={len(s):3d}, WR={wr:5.2f}%, PLR={plr:4.2f}, MDD={mdd:5.2f}%, NAV={nav:,.2f}x")
    bd = slot5y.groupby("strategy").agg(n=("net_ret","count"), wr=("net_ret", lambda x: round((x>0).mean()*100,2)), mean_pct=("net_ret", lambda x: round(x.mean()*100,2))).to_dict("index")
    out_str.append(f"  5Y Per-Strat: {bd}")
    print("\n".join(out_str))

eval_5("1_Base_T1 (现役官库5m)", pry_old, d23_t1_base)
eval_5("2_Opt_T1  (撬V2+二三6.5)", pry_new, d23_t1_opt)
eval_5("3_Base_T2 (现役100%5m)", pry_old, d23_t2_base)
eval_5("4_Opt_T2  (撬V2+二三6.5)", pry_new, d23_t2_opt)
eval_5("5_Opt2d_T2(撬2日+二三6.5)", pry_2d, d23_t2_opt)
