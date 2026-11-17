#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
from master_5y_zero_lookahead_walkforward import (
    load_all_data, create_master_trade_engine, evaluate_strategy_master, FEE_RATE, FEE_RATE_DISCOUNT
)

hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()
hist_fb = hist_fb.reset_index(drop=True)

dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1
is_granularity = hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0))

common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_l1 = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
pass_l2 = (~hist_fb["is_dying_pulse"])
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_nd = (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

q_pen15 = - np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)

hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
hist_fb["sq_91"] = hist_fb["s_quant_dual"] + q_pen15 + d_ov
hist_fb["sc_91"] = hist_fb["s_prior_wk"] + hist_fb["sq_91"]
hist_fb["score_active"] = hist_fb["sc_91"]

m_t2 = common_ok & (hist_fb["p_sz"] == 1) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"]) & hist_fb["d2_o_pct"].between(0.035, 0.078) & (hist_fb["buyable_mkt_open_rk"] <= 3) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
mt1_91 = common_ok & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (hist_fb["s_prior_wk"] >= 45.0) & (hist_fb["sq_91"] >= 150.0) & (hist_fb["sc_91"] >= thr_vec)
mm_91 = (mt1_91 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)
mmon_91 = common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (hist_fb["s_prior_wk"] >= 38.0) & (hist_fb["sq_91"] >= 145.0) & (hist_fb["sc_91"] >= thr_vec) & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
hist_fb["msk_91"] = mm_91 | (mmon_91 & (~mm_91))
hist_fb["pass_all_gates"] = common_ok & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & hist_fb["d2_o_pct"].between(0.020, 0.088)

# Compute exact daily Plate Theme Score & Rank (rk_theme = 1, 2, 3...) and Gap of Theme #1 over Theme #2!
valid_plate = hist_fb[(hist_fb["plate"] != "其他") & (~hist_fb["is_event_basket"])].copy()
pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(
    p_sz_max=("p_sz", "max"),
    p_theme_sc=("s_prior_wk", "max"),
    p_theme_med=("s_prior_dual", "median"),
    p_open_avg=("d2_o_pct", "mean"),
    p_yizi_cnt=("d2_is_yizi", "sum"),
)
pg_m = pg[pg["p_sz_max"] >= 2].copy()
pg_m["rk_theme"] = pg_m.groupby("d2_dt")["p_theme_med"].rank(ascending=False, method="min")
p2_th = pg_m.groupby("d2_dt")["p_theme_med"].transform(lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else 0.0)
pg_m["theme1_gap"] = np.where(pg_m["rk_theme"] == 1, pg_m["p_theme_med"] - p2_th, 0.0)
day_gap_map = pg_m[pg_m["rk_theme"] == 1].groupby("d2_dt")["theme1_gap"].max().to_dict()

hist_m = hist_fb.merge(pg_m[["d2_dt", "plate", "rk_theme", "p_theme_med", "p_open_avg", "p_yizi_cnt"]], on=["d2_dt", "plate"], how="left")
hist_m["day_theme1_gap"] = [day_gap_map.get(d, 0.0) for d in hist_m["d2_dt"]]

fn20 = create_master_trade_engine(price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE)

# Inspect across TWO scopes in 2022-2026:
# Scope A: Broad qualified candidates (pass_all_gates & sc_91 >= 275) where:
#   - Overall #1 stock (Stock_1st) is from Theme #2 or #3 (rk_theme in [2, 3, 4])
#   - Overall #2 (or #3) stock (Stock_Dom2nd) is the #1 stock of Dominant Theme #1 (rk_theme == 1 & day_theme1_gap >= 10)!
# Scope B: Strictly inside our 90.98x passed pool (msk_91)!

for scope_name, base_cond, gap_thr in [
    ("SCOPE_1_Broad_Qualified(sc>=275, gap>=10)", hist_m["pass_all_gates"] & (hist_m["sc_91"] >= 275.0), 10.0),
    ("SCOPE_2_Broad_StrictDom(sc>=285, gap>=15)", hist_m["pass_all_gates"] & (hist_m["sc_91"] >= 285.0), 15.0),
    ("SCOPE_3_Inside_90.98x_PassedPool(gap>=8)", hist_m["msk_91"], 8.0),
    ("SCOPE_4_Inside_90.98x_AnyTheme1(gap>=0)", hist_m["msk_91"], 0.0),
]:
    sub_oos = hist_m[(hist_m["d2_dt"] >= "2022-01-01") & (hist_m["d2_dt"] <= "2026-11-09") & base_cond].copy()
    cases = []
    for dt, grp in sub_oos.groupby("d2_dt"):
        if day_gap_map.get(dt, 0.0) < gap_thr:
            continue
        grp_s = grp.sort_values("sc_91", ascending=False).reset_index(drop=True)
        if len(grp_s) < 2:
            continue
        top1 = grp_s.iloc[0]
        # Check if Overall #1 is from Theme #2/#3/#4 (not Theme #1!), while Theme #1's best stock is Overall #2 (or #3)!
        if pd.isna(top1["rk_theme"]) or top1["rk_theme"] == 1:
            continue
        dom_rows = grp_s[grp_s["rk_theme"] == 1]
        if len(dom_rows) == 0:
            continue
        dom_best = dom_rows.iloc[0]
        dom_overall_rk = int(dom_rows.index[0]) + 1
        if dom_overall_rk > 3:
            continue
        t1 = fn20(top1.to_dict())
        td = fn20(dom_best.to_dict())
        if t1 is None and td is None:
            continue
        b1 = price_lookup.get((top1["c6"], dt))
        bd = price_lookup.get((dom_best["c6"], dt))
        r1 = t1["net_ret"] if t1 is not None else ((b1[3]/b1[0]-1.0) if b1 else 0.0)
        rd = td["net_ret"] if td is not None else ((bd[3]/bd[0]-1.0) if bd else 0.0)
        cases.append({
            "dt": dt, "gap": day_gap_map.get(dt, 0.0),
            "t23_name": top1["name"], "t23_plate": top1["plate"], "t23_rk_th": top1["rk_theme"],
            "t23_sc": top1["sc_91"], "t23_sp": top1["s_prior_wk"], "t23_sq": top1["sq_91"],
            "t23_o": top1["d2_o_pct"], "t23_dd20": top1["f_dd20_d0"], "t23_p_o": top1["p_open_avg"],
            "t23_psz": top1["p_sz"], "t23_ret": r1, "t23_trig": int(t1 is not None), "t23_zt2": int(top1["d2_is_zt"]),
            "dom_name": dom_best["name"], "dom_plate": dom_best["plate"], "dom_ov_rk": dom_overall_rk,
            "dom_sc": dom_best["sc_91"], "dom_sp": dom_best["s_prior_wk"], "dom_sq": dom_best["sq_91"],
            "dom_o": dom_best["d2_o_pct"], "dom_dd20": dom_best["f_dd20_d0"], "dom_p_o": dom_best["p_open_avg"],
            "dom_yizi": dom_best["p_yizi_cnt"], "dom_psz": dom_best["p_sz"], "dom_pl_rk": dom_best["buyable_plate_rk"],
            "dom_ret": rd, "dom_trig": int(td is not None), "dom_zt2": int(dom_best["d2_is_zt"]),
        })
    cdf = pd.DataFrame(cases)
    print(f"\n==================== {scope_name}: N={len(cdf)} days ====================")
    if len(cdf) == 0:
        continue
    print(f"  Theme2/3 Overall-#1 Stock : WR={(cdf['t23_ret']>0).mean()*100:4.1f}% | 2B={cdf['t23_zt2'].mean()*100:4.1f}% | Avg={cdf['t23_ret'].mean()*100:+5.2f}% | Triggered={cdf['t23_trig'].sum()}/{len(cdf)}")
    print(f"  DomTheme1 Overall-#2 Stock: WR={(cdf['dom_ret']>0).mean()*100:4.1f}% | 2B={cdf['dom_zt2'].mean()*100:4.1f}% | Avg={cdf['dom_ret'].mean()*100:+5.2f}% | Triggered={cdf['dom_trig'].sum()}/{len(cdf)}")
    print(f"  Mean Features -> T23_#1: sp={cdf['t23_sp'].mean():.1f}, sq={cdf['t23_sq'].mean():.1f}, open={cdf['t23_o'].mean()*100:.2f}%, dd20={cdf['t23_dd20'].mean():.3f}, p_open_avg={cdf['t23_p_o'].mean()*100:.2f}%, p_sz={cdf['t23_psz'].mean():.1f}")
    print(f"  Mean Features -> Dom_#2: sp={cdf['dom_sp'].mean():.1f}, sq={cdf['dom_sq'].mean():.1f}, open={cdf['dom_o'].mean()*100:.2f}%, dd20={cdf['dom_dd20'].mean():.3f}, p_open_avg={cdf['dom_p_o'].mean()*100:.2f}%, p_sz={cdf['dom_psz'].mean():.1f}, yizi={cdf['dom_yizi'].mean():.2f}")

    if len(cdf) >= 15:
        # Split by WHY Theme 2/3 beat Dom Theme 1 in total score:
        # Subcase A: Theme 2/3 actually opened MUCH stronger in auction (t23_o > dom_o + 1.0% & t23_p_o > dom_p_o) -> True "卡位切换/新支线抢筹"!
        # Subcase B: Dom Theme 1 opened >= Theme 2/3 (dom_o >= t23_o - 0.5%), Theme 2/3 ONLY won because of static oversold dd20!
        m_auc_beat = (cdf["t23_o"] > cdf["dom_o"] + 0.010)
        m_stat_beat = ~m_auc_beat
        for sub_nm, sm in [("SubA: Theme2/3 beat via STRONGER AUCTION OPEN (t23_o > dom_o + 1%)", m_auc_beat),
                           ("SubB: DomTheme1 opened >= Theme2/3, T23 only won via STATIC OVERSOLD", m_stat_beat),
                           ("SubC: DomTheme1 crowded (dom_psz>=10) vs fresh Theme2/3", cdf["dom_psz"] >= 10),
                           ("SubD: DomTheme1 NOT crowded (dom_psz<10) & dom_o>=4%", (cdf["dom_psz"] < 10) & (cdf["dom_o"] >= 0.040))]:
            s = cdf[sm]
            if len(s) >= 3:
                print(f"    {sub_nm:68s} (N={len(s):2d}): T23_Avg={s['t23_ret'].mean()*100:+5.2f}% (WR={(s['t23_ret']>0).mean()*100:4.1f}%) vs Dom_Avg={s['dom_ret'].mean()*100:+5.2f}% (WR={(s['dom_ret']>0).mean()*100:4.1f}%)")

    if "Inside_90.98x" in scope_name and len(cdf) <= 25:
        for _, r in cdf.iterrows():
            print(f"    [{r['dt']}] T23#1 {r['t23_name']}({r['t23_plate']},rk{int(r['t23_rk_th'])},o={r['t23_o']*100:.1f}%,ret={r['t23_ret']*100:+.1f}%) vs Dom#2 {r['dom_name']}({r['dom_plate']},o={r['dom_o']*100:.1f}%,psz={int(r['dom_psz'])},ret={r['dom_ret']*100:+.1f}%)")
