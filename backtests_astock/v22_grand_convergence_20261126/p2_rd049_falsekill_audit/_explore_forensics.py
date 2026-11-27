#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, sys, pickle
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
for p in (RD038, RD049):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd038_engine as eng
import _rd049_common as cm

with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
    cache = pickle.load(f)
reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
reg2 = cm.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0)
reg_idx = reg2.set_index("trade_date")

SPECS = [
    ("S1_SkipYellow34", dict(mode="skip_yellow", pry_cold=True)),
    ("S3_RD049_Tier_Full", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=True)),
    ("S4_RD049_R2D_Full", dict(mode="runion", r0=38, rk=12, raf=45, af03_weak=True, pry_cold=True)),
    ("S5_RD049_Tier_NoPry", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=False)),
    ("M3_OnlyAf03_Weak", dict(mode="base", af03_weak=True, pry_cold=False)),
]

# --- VIEW A: 3to4 Full Pool & Standalone Slot ---
d34 = cache["pools_ext"]["3to4"].copy()
d34["light_5"] = d34["buy_date"].map(reg_idx["light_5"].to_dict())
d34["X_score"] = d34["buy_date"].map(reg_idx["X_score"].to_dict())
d34["Y_score"] = d34["buy_date"].map(reg_idx["Y_score"].to_dict())
d34["R_union"] = d34["buy_date"].map(reg_idx["R_union"].to_dict())
d34["is_red_floor"] = d34["buy_date"].map(reg_idx["is_red_floor"].to_dict())
m4_mask = cache["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"]
d34["v21_m4_pass"] = m4_mask

base_34 = d34[d34["can_buy_hygiene"] & (d34["orig_score"] >= 90.0) & d34["buy_date"].between("2021-11-16", "2026-11-16")].copy()
print(f"=== VIEW A: 3to4 Full Pool (V20 base eligible n={len(base_34)}, V21 m4 pass n={(base_34['v21_m4_pass']).sum()}) ===")
for nm, kw in SPECS:
    cf = cm.apply_rd049_filter(cache, reg_idx, **kw)
    k34 = cf["pools_ext"]["3to4"]["can_buy_hygiene"].to_numpy(bool)
    base_34[f"keep_{nm}"] = k34[base_34.index]
    blk = base_34[~base_34[f"keep_{nm}"]]
    kp = base_34[base_34[f"keep_{nm}"]]
    losers = blk[blk["net_ret_030"] <= 0]
    winners = blk[blk["net_ret_030"] > 0]
    print(f"  {nm:20s}: blocked={len(blk):2d}/{len(base_34)} | losers={len(losers):2d} (avg={losers['net_ret_030'].mean()*100 if len(losers) else 0:+.2f}%) | winners={len(winners):2d} (avg={winners['net_ret_030'].mean()*100 if len(winners) else 0:+.2f}%) | kept wr={(kp['net_ret_030']>0).mean()*100:.1f}% mean={kp['net_ret_030'].mean()*100:+.2f}%")

print("\n--- All 3to4 candidates blocked by ANY of S1/S3/S4/S5/M3 ---")
any_blk = np.zeros(len(base_34), dtype=bool)
for nm, _ in SPECS:
    any_blk |= ~base_34[f"keep_{nm}"].to_numpy(bool)
blk_all = base_34[any_blk].sort_values("buy_date")
for r in blk_all.itertuples():
    flags = "".join(["1" if not getattr(r, f"keep_{nm}") else "." for nm, _ in SPECS])
    print(f"  {r.buy_date} {r.code} {r.name:6s} sc={r.orig_score:5.1f} af03={int(r.s34_af_03)} hh={int(r.buy_hhmm)} v21m4={int(r.v21_m4_pass)} | {r.light_5} R={r.R_union:4.1f} | ret={r.net_ret_030*100:+6.2f}% | blk[S1,S3,S4,S5,M3]={flags}")

# Also check pry candidates blocked by pry_cold
dp = cache["pools_ext"]["pry"].copy()
dp_base = dp[dp["can_buy_hygiene"] & (dp["orig_score"] >= 165.0) & dp["buy_date"].between("2021-11-16", "2026-11-16")].copy()
dp_blk = dp_base[dp_base["mkt10_zt_est_t1"] < 50.0]
print(f"\n=== PRY candidates blocked by pry_cold (mkt10_zt_est_t1 < 50): {len(dp_blk)} / {len(dp_base)} ===")
for r in dp_blk.itertuples():
    l5 = reg_idx.loc[r.buy_date, "light_5"] if r.buy_date in reg_idx.index else "?"
    print(f"  {r.buy_date} {r.code} {r.name:6s} sc={r.orig_score:5.1f} mkt10zt={r.mkt10_zt_est_t1:4.0f} | {l5} | ret={r.net_ret_030*100:+6.2f}%")

# --- VIEW B: Portfolio Level Episode Decomposition ---
def decompose_episodes(tr_b: pd.DataFrame, tr_v: pd.DataFrame):
    """Split divergence between baseline and variant ledgers into exact disjoint episodes."""
    b_list = tr_b.sort_values("buy_date").to_dict("records")
    v_list = tr_v.sort_values("buy_date").to_dict("records")
    ib, iv = 0, 0
    episodes = []
    while ib < len(b_list) or iv < len(v_list):
        if ib < len(b_list) and iv < len(v_list):
            rb, rv = b_list[ib], v_list[iv]
            if (rb["buy_date"], rb["code"], rb["strategy"], rb["exit_date"], rb["exit_hhmm"]) == (rv["buy_date"], rv["code"], rv["strategy"], rv["exit_date"], rv["exit_hhmm"]):
                ib += 1
                iv += 1
                continue
        # Start of divergence episode
        b_ep, v_ep = [], []
        # Advance the one with earlier entry, until both reach same next synchronized trade or empty
        while True:
            if ib < len(b_list) and iv < len(v_list):
                rb, rv = b_list[ib], v_list[iv]
                if len(b_ep) > 0 or len(v_ep) > 0:
                    # Check if synchronized at same trade AND previous exits both <= this buy_date/hhmm
                    if (rb["buy_date"], rb["code"], rb["strategy"], rb["exit_date"], rb["exit_hhmm"]) == (rv["buy_date"], rv["code"], rv["strategy"], rv["exit_date"], rv["exit_hhmm"]):
                        break
            if ib >= len(b_list) and iv >= len(v_list):
                break
            # Determine which pointer to advance
            if ib < len(b_list) and (iv >= len(v_list) or (b_list[ib]["buy_date"], int(b_list[ib]["buy_hhmm"])) <= (v_list[iv]["buy_date"], int(v_list[iv]["buy_hhmm"]))):
                b_ep.append(b_list[ib])
                ib += 1
            else:
                v_ep.append(v_list[iv])
                iv += 1
        episodes.append((b_ep, v_ep))
    return episodes

for bname, cfg in [("V21", cm.CFG_V21), ("V20", cm.CFG_V20)]:
    cf_b = cm.apply_rd049_filter(cache, reg_idx, mode="base")
    sim_b = eng.run_bundle_sim(cf_b, cfg, fee_mode="030")
    tr_b = sim_b["trades_df"]
    print(f"\n================ {bname} PORTFOLIO EPISODES ================")
    for nm, kw in SPECS:
        cf_v = cm.apply_rd049_filter(cache, reg_idx, **kw)
        sim_v = eng.run_bundle_sim(cf_v, cfg, fee_mode="030")
        tr_v = sim_v["trades_df"]
        eps = decompose_episodes(tr_b, tr_v)
        tot_mult = 1.0
        print(f"\n--- {bname} :: {nm} (episodes={len(eps)}) ---")
        for ei, (b_ep, v_ep) in enumerate(eps, 1):
            pb = float(np.prod([1.0 + x["net_ret"] for x in b_ep]))
            pv = float(np.prod([1.0 + x["net_ret"] for x in v_ep]))
            ratio = pv / pb
            tot_mult *= ratio
            b_str = "; ".join([f"{x['buy_date']}->{x['exit_date']} {x['strategy']}:{x['code']}{x['name']}(sc={x['score']:.0f},{reg_idx.loc[x['buy_date'],'light_5'][:2]},{x['net_ret']*100:+.2f}%)" for x in b_ep]) or "EMPTY"
            v_str = "; ".join([f"{x['buy_date']}->{x['exit_date']} {x['strategy']}:{x['code']}{x['name']}(sc={x['score']:.0f},{reg_idx.loc[x['buy_date'],'light_5'][:2]},{x['net_ret']*100:+.2f}%)" for x in v_ep]) or "EMPTY"
            print(f"  Ep{ei:02d} ratio={ratio:.4f} (log={np.log(ratio):+.4f}) | BASE=[{b_str}]  ==>  VAR=[{v_str}]")
        nav_b = float(np.prod(1.0 + tr_b["net_ret"].to_numpy(float)))
        nav_v = float(np.prod(1.0 + tr_v["net_ret"].to_numpy(float)))
        print(f"  Check exact NAV ratio: prod(ep)={tot_mult:.6f} vs actual={nav_v/nav_b:.6f}")
