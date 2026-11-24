#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 2 (IS-ONLY <= 2024-08-31):
1. Verify incremental value of pit_top10_20cm_summary.json (lock_top10, real_free_mcap, real_to),
   KPL historical 180d + Dynamic Elo, CNINFO notices/IR, LHB, and zero-leak Community.
2. Build 15-item pure-integer orthogonal candidate scorecard -> run Leave-One-Out Ablation on IS.
3. Prune any redundant/hurtful items -> verify 5-bucket score monotonicity -> select A-tier & S-tier thresholds.
ZERO OOS DATA IS TOUCHED IN THIS SCRIPT!
"""
import os, pickle, time
import numpy as np
import pandas as pd
from v1_exit_engine import simulate_exit_v1, calc_window_d15

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_beta_scorecard_exit"
P1_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves"
IS_END = "2024-08-31"


def compute_score_components(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Return dictionary of 15 pure-integer orthogonal scoring components (all strictly <= T+1 09:25 PIT)."""
    c = df
    comps = {}

    # 1. T+1 open sweet spot [-1.2%, +1.8%] (+6), deep gap-down <-2.5% (-12), chase >+4.0% (-6)
    og1 = c["t1_open_gap"].fillna(0.0).to_numpy()
    comps["F01_T1Open"] = np.where(
        og1 < -0.025, -12,
        np.where(og1 > 0.040, -6,
                 np.where((og1 >= -0.012) & (og1 <= 0.018), 6, 0))
    )

    # 2. Short-term low box position pos20_pre
    p20 = c["pos20_pre"].fillna(0.5).to_numpy()
    comps["F02_Pos20"] = np.where(p20 <= 0.25, 10, np.where(p20 <= 0.42, 5, np.where(p20 > 0.65, -8, 0)))

    # 3. Medium-term below MA60 dist_ma60_pre
    dm60 = c["dist_ma60_pre"].fillna(0.0).to_numpy()
    comps["F03_DistMA60"] = np.where(dm60 <= -0.15, 12, np.where(dm60 <= 0.0, 6, np.where(dm60 > 0.10, -8, 0)))

    # 4. Real free-float mcap (using pit_top10_20cm_summary.json!) & big army penalty (>=150亿 circ_mcap or >=80亿 real_free_mcap)
    rfm = c["real_free_mcap"].fillna(c["circ_mcap"] * 0.6).to_numpy()
    cm = c["circ_mcap"].fillna(50.0).to_numpy()
    comps["F04_RealFreeMcap"] = np.where((cm >= 150.0) | (rfm >= 80.0), -10, np.where(rfm <= 25.0, 10, np.where(rfm <= 45.0, 4, 0)))

    # 5. Top-10 freeholder lockup direct check (<= 25% lighter lockup vs >= 55% high concentration)
    lt10 = c["lock_top10"].to_numpy()
    comps["F05_LockTop10"] = np.where(np.isnan(lt10), 0, np.where(lt10 <= 25.0, 4, np.where(lt10 >= 55.0, -4, 0)))

    # 6. Real free-float turnover sweet spot [6%, 22%] vs dead (<3.5%) / blowout (>30%)
    rto = c["real_to"].fillna(c["turn_pct"] / 0.6).to_numpy()
    comps["F06_RealTurnover"] = np.where(rto > 30.0, -8, np.where(rto < 3.5, -6, np.where((rto >= 6.0) & (rto <= 22.0), 8, 0)))

    # 7. T0 intraday close strength CLV
    clv = c["clv"].fillna(0.5).to_numpy()
    comps["F07_CLV"] = np.where(clv >= 0.80, 6, np.where(clv < 0.55, -8, 0))

    # 8. Freshness / Anti-Old-Dragon (big7_cnt_20d_pre == 0 vs >= 2)
    b7 = c["big7_cnt_20d_pre"].fillna(0.0).to_numpy()
    comps["F08_AntiOldDragon"] = np.where(b7 == 0, 8, np.where(b7 >= 2, -8, 0))

    # 9. Board elasticity (ChiNext 300/301 vs STAR 688) & low unit price
    chinext = c["is_chinext"].fillna(0).to_numpy()
    px = c["close"].fillna(20.0).to_numpy()
    comps["F09_BoardPrice"] = np.where(chinext == 1, 6, 0) + np.where(px <= 15.0, 4, np.where(px > 45.0, -4, 0))

    # 10. Deviation headroom (head_3d30, head_10d100)
    h3 = c["head_3d30"].fillna(0.20).to_numpy()
    h10 = c["head_10d100"].fillna(0.80).to_numpy()
    comps["F10_Headroom"] = np.where(h3 < 0.05, -12, np.where((h3 >= 0.15) & (h10 >= 0.70), 4, 0))

    # 11. KPL Historical Theme (T-180..T-1) + Dynamic Elo resonance (1..14 ZT or Elo>25, avoid >=18 climax)
    kzt = c["kpl_hist180_allzt_max"].fillna(0).to_numpy()
    kelo = c["kpl_hist180_elo_max"].fillna(0).to_numpy()
    comps["F11_KPL_ThemeElo"] = np.where(kzt >= 18, -4, np.where(((kzt >= 1) & (kzt <= 14)) | (kelo > 25.0), 5, 0))

    # 12. CNINFO Notices & IR QA: T0 post-close earn_pos sell-the-news penalty (-20!), prior earn_pos/IR mild boost
    ep_post = c["earn_pos_t0_post_B"].fillna(0).to_numpy()
    ep30 = c["earn_pos_30d_B"].fillna(0).to_numpy()
    ir30 = c["ir_qa_30d_B"].fillna(0).to_numpy()
    comps["F12_Notices_IR"] = np.where(ep_post == 1, -20, np.where(ep30 == 1, 4, 0) + np.where(ir30 == 1, 2, 0))

    # 13. LHB Institutional Net Buy (+8) vs Lhasa / Toxic Surf Seat (-18)
    onet = c["lhb_t0_org_net_yi"].fillna(0.0).to_numpy()
    lh = c["lhb_t0_lhasa_cnt"].fillna(0.0).to_numpy()
    surf = c["lhb_t0_surf_bad"].fillna(0.0).to_numpy()
    comps["F13_LHB_Seats"] = np.where((lh >= 1) | (surf == 1), -18, np.where(onet > 0.02, 8, 0))

    # 14. Zero-Leak Community Overheat Penalty (Xueqiu + Guba posts >= 4 in 3d)
    comm = c["comm_posts_3d_pit"].fillna(0).to_numpy()
    comps["F14_CommOverheat"] = np.where(comm >= 4, -5, 0)

    # 15. Market 5d Regime & Monday Penalty
    m5 = c["mkt_prev5d_ew"].fillna(0.0).to_numpy()
    mon = c["is_monday"].fillna(0).to_numpy()
    comps["F15_MarketRegime"] = np.where(m5 >= -0.02, 6, np.where(m5 >= -0.05, -8, 2)) + np.where(mon == 1, -6, 0)

    return comps


def eval_is_selection(is_df: pd.DataFrame, scores: np.ndarray, paths: dict, mkt_ew: dict,
                      dt_to_gidx: dict, mkt: pd.DataFrame, th: float, top_n: int = 3,
                      exit_rule: str = "GRID_TP12_SL07_T5") -> dict:
    sub = is_df.copy()
    sub["score"] = scores
    sub = sub[sub["score"] >= th].sort_values(["dt", "score", "circ_mcap", "c6"], ascending=[True, False, True, True])
    sub = sub.groupby("dt", sort=False).head(top_n).reset_index(drop=True)
    trades = []
    for r in sub.itertuples(index=False):
        res = simulate_exit_v1(paths, mkt_ew, r.c6, dt_to_gidx[r.dt], exit_rule, float(r.mkt_prev5d_ew))
        if res is None:
            continue
        bdt, bpx, sdt, spx, nret, why, hbars = res
        trades.append({
            "signal_dt": r.dt, "buy_dt": bdt, "sell_dt": sdt, "c6": r.c6,
            "circ_mcap": float(r.circ_mcap), "score": float(r.score),
            "net_ret": nret, "exit_reason": why, "is_delisted": int(r.is_delisted),
        })
    tdf = pd.DataFrame(trades)
    return calc_window_d15(tdf, mkt, "2021-01-04", IS_END)


def main():
    t0 = time.time()
    base = pd.read_parquet(f"{OUT_DIR}/v1_beta_base_pool.parquet")
    mkt = pd.read_parquet(f"{P1_DIR}/market_daily.parquet")
    mkt_ew = dict(zip(mkt["dt"], mkt["ew_ret_all"]))
    pk = pickle.load(open(f"{OUT_DIR}/v1_stock_paths.pkl", "rb"))
    paths, dt_to_gidx = pk["paths"], pk["dt_to_gidx"]

    is_df = base[(base["dt"] <= IS_END) & (base["buyable_B"])].copy().reset_index(drop=True)
    comps = compute_score_components(is_df)
    comp_names = list(comps.keys())
    full_score = np.full(len(is_df), 70, dtype=int)
    for k in comp_names:
        full_score += comps[k]

    # 1. Check baseline & full 15-item IS performance
    base_m = eval_is_selection(is_df, np.full(len(is_df), 70.0), paths, mkt_ew, dt_to_gidx, mkt, th=70.0, top_n=3)
    full_m = eval_is_selection(is_df, full_score.astype(float), paths, mkt_ew, dt_to_gidx, mkt, th=80.0, top_n=3)
    print(f"[IS Baseline (top3 by small cap, th=70)]: days={base_m['n_days']}, 1s={base_m['nav_1s']}x(WR={base_m['wr_1s']}%), 3s={base_m['nav_3s']}x(ex5={base_m['ex5_3s']}x,MDD={base_m['mdd_3s_pct']}%), dew={base_m['dew_nav']}x")
    print(f"[IS Full 15-item (th>=80, top3)]: days={full_m['n_days']}, 1s={full_m['nav_1s']}x(WR={full_m['wr_1s']}%), 3s={full_m['nav_3s']}x(ex5={full_m['ex5_3s']}x,MDD={full_m['mdd_3s_pct']}%), dew={full_m['dew_nav']}x")

    # 2. Leave-One-Out Ablation on IS (evaluated at th>=80 top3 and across all signals IC!)
    # Also compute within-day rank IC of full_score vs each leave-one-out score on TP12_SL07_T5!
    r_tp12 = [simulate_exit_v1(paths, mkt_ew, r.c6, dt_to_gidx[r.dt], "GRID_TP12_SL07_T5", float(r.mkt_prev5d_ew)) for r in is_df.itertuples(index=False)]
    is_df["y_tp12"] = [x[4] if x else np.nan for x in r_tp12]

    def mean_cs_ic(sc_vec):
        tmp = pd.DataFrame({"dt": is_df["dt"].values, "sc": sc_vec, "y": is_df["y_tp12"].values}).dropna()
        ics = [g["sc"].corr(g["y"], method="spearman") for _, g in tmp.groupby("dt") if len(g) >= 10 and g["sc"].nunique() > 1]
        return float(np.nanmean(ics)) if ics else 0.0

    base_ic = mean_cs_ic(full_score)
    ab_rows = [{
        "dropped_item": "NONE (Full_15)", "is_cs_ic": round(base_ic, 4),
        "ic_delta": 0.0, "is_n_3s": full_m["n_3s"], "is_nav_1s": full_m["nav_1s"],
        "is_nav_3s": full_m["nav_3s"], "is_ex5_3s": full_m["ex5_3s"],
        "is_mdd_3s_pct": full_m["mdd_3s_pct"], "is_dew_nav": full_m["dew_nav"],
        "verdict": "BASELINE"
    }]
    for k in comp_names:
        sc_loo = full_score - comps[k]
        ic_loo = mean_cs_ic(sc_loo)
        m_loo = eval_is_selection(is_df, sc_loo.astype(float), paths, mkt_ew, dt_to_gidx, mkt, th=80.0, top_n=3)
        ic_gain = base_ic - ic_loo  # positive means keeping k improves IC
        nav3_gain = full_m["nav_3s"] - m_loo["nav_3s"]
        ex5_gain = full_m["ex5_3s"] - m_loo["ex5_3s"]
        dew_gain = full_m["dew_nav"] - m_loo["dew_nav"]
        keep = (ic_gain > 0.0005) or (nav3_gain > 0.02) or (ex5_gain > 0.02) or (dew_gain > 0.02)
        ab_rows.append({
            "dropped_item": k, "is_cs_ic": round(ic_loo, 4), "ic_delta": round(-ic_gain, 4),
            "is_n_3s": m_loo["n_3s"], "is_nav_1s": m_loo["nav_1s"],
            "is_nav_3s": m_loo["nav_3s"], "is_ex5_3s": m_loo["ex5_3s"],
            "is_mdd_3s_pct": m_loo["mdd_3s_pct"], "is_dew_nav": m_loo["dew_nav"],
            "verdict": "KEEP" if keep else "PRUNE_CANDIDATE",
        })
    ab_df = pd.DataFrame(ab_rows)
    ab_df.to_csv(f"{OUT_DIR}/ablation_is_probe.csv", index=False)
    print("\n=== IS LEAVE-ONE-OUT ABLATION (negative ic_delta or lower nav_3s/ex5_3s means dropping HURT => item is valuable) ===")
    print(ab_df.to_string(index=False))

    # 3. 5-Bucket Monotonicity on IS (using Full_15 first, then compare after pruning!)
    is_df["full_score"] = full_score
    bins = [-999, 65, 79, 89, 99, 999]
    labels = ["Q1(<65)", "Q2(65-79)", "Q3(80-89)", "Q4(90-99)", "Q5(>=100)"]
    is_df["bucket"] = pd.cut(is_df["full_score"], bins=bins, labels=labels)
    b_tbl = is_df.groupby("bucket", observed=False).agg(
        n=("y_tp12", "count"),
        mean_pct=("y_tp12", lambda s: round(s.mean() * 100, 2)),
        wr_pct=("y_tp12", lambda s: round((s > 0).mean() * 100, 1)),
    )
    print("\n=== IS 5-BUCKET MONOTONICITY (Full_15) ===")
    print(b_tbl.to_string())

    # 4. Threshold sweep on IS for Top-3 (th = 75, 80, 85, 90, 95, 100)
    print("\n=== IS THRESHOLD SWEEP (Top 3 per Beta Day) ===")
    for th in [70, 75, 80, 85, 90, 95, 100]:
        mt = eval_is_selection(is_df, full_score.astype(float), paths, mkt_ew, dt_to_gidx, mkt, th=float(th), top_n=3)
        print(f"  th>={th:3d} | days={mt['n_days']:2d} n={mt['n_trades']:3d} | 1s={mt['nav_1s']:5.2f}x(N={mt['n_1s']:2d},WR={mt['wr_1s']:4.1f}%,MDD={mt['mdd_1s_pct']:5.1f}%) | "
              f"3s={mt['nav_3s']:5.2f}x(N={mt['n_3s']:2d},ex5={mt['ex5_3s']:5.2f}x,MDD={mt['mdd_3s_pct']:5.1f}%) | dew={mt['dew_nav']:5.2f}x(ex5={mt['dew_ex5_nav']:5.2f}x)")
    print(f"[Done Step 2 IS probe in {time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()
