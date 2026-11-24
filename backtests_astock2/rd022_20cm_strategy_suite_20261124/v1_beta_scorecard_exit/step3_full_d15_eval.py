#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 3: Lock IS-calibrated Beta-Resonance V1.0 (15-item Pure Integer Scorecard + DYN_YANG_TP15_T5),
run blind validation on OOS, OOS_ex924, 2026 YTD, FULL, plus full D15, HLZ t, DSR, Monkey-p,
Param Plateau (+-20%), and export all required CSV/JSON artifacts.
"""
import json, os, pickle, time
import numpy as np
import pandas as pd
from v1_exit_engine import simulate_exit_v1, calc_window_d15, _sim_k_slots_v1

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_beta_scorecard_exit"
P1_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part1_beta_waves"

SCORECARD_SPEC = [
    ("I01_T1Open", "T+1开盘甜区与跳空惩罚", "t1_open_gap in [-1.2%,+1.8%] +5; <-2.5% -14; >+4.0% -6", "T+1_0925"),
    ("I02_Pos20", "20日区间低位", "pos20_pre <= 0.25 +8; <= 0.42 +4; > 0.65 -8", "T0_pre"),
    ("I03_DistMA60", "60日均线乖离低位", "dist_ma60_pre <= -15% +10; <= 0% +5; > +10% -8", "T0_pre"),
    ("I04_RealFreeMcap", "真实自由流通市值(十大锁仓扣减)", "real_free_mcap <= 25亿 +8; <= 45亿 +3; >= 80亿或circ >= 150亿 -10", "PIT_Top10"),
    ("I05_LockTop10", "十大自由流通股东锁仓比例", "lock_top10 <= 25% +4; >= 55% -4", "PIT_Top10"),
    ("I06_RealTO_Climax", "真实自由流通换手甜区与爆量惩罚", "real_to in [6%,22%] +3; > 28% -8", "PIT_Top10"),
    ("I07_CLV", "T0日内收盘强度(CLV)", "clv >= 0.80 +5; < 0.55 -8", "T0_1500"),
    ("I08_AntiOldDragon", "前20日零暴涨老妖避坑", "big7_cnt_20d_pre == 0 +6; >= 2 -8", "T0_pre"),
    ("I09_BoardPrice", "板块弹性(创业板)与低股价弹性", "创业板300/301 +5; 股价 <= 15元 +4; > 45元 -4", "T0_1500"),
    ("I10_BarrierVeto", "3日30%严重异动防撞线", "head_3d30 < 5% -12", "T0_1500"),
    ("I11_KPL_ThemeElo", "开盘啦历史题材(180d)与动态Elo共振", "kpl_hist180_allzt in [1,14] 或 elo>25 +5; >=18防高潮 -4", "KPL_PIT"),
    ("I12_EarnPostKill", "T0盘后业绩预增见光死拆雷", "earn_pos_t0_post_B == 1 -20", "CNINFO_B"),
    ("I13_LHB_Seats", "T0盘后龙虎榜机构净买与拉萨/坑人席位", "org_net > 200万 +8; 拉萨或坑人游资 >= 1 -18", "LHB_T0"),
    ("I14_MarketRegime", "大盘5日环境与周一效应", "mkt_prev5d >= -2% +5; [-5%,-2%) -8; <-5% +2; 周一 -6", "Macro_T0"),
    ("I15_CommOverheat", "雪球股吧零前视3日散户过热避坑", "comm_posts_3d_pit >= 4 -5", "Comm_PIT"),
]


def compute_score_beta_v1(df: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    og1 = df["t1_open_gap"].fillna(0.0).to_numpy()
    p20 = df["pos20_pre"].fillna(0.5).to_numpy()
    dm60 = df["dist_ma60_pre"].fillna(0.0).to_numpy()
    rfm = df["real_free_mcap"].fillna(df["circ_mcap"] * 0.6).to_numpy()
    cm = df["circ_mcap"].fillna(50.0).to_numpy()
    lt10 = df["lock_top10"].to_numpy()
    rto = df["real_to"].fillna(df["turn_pct"] / 0.6).to_numpy()
    clv = df["clv"].fillna(0.5).to_numpy()
    b7 = df["big7_cnt_20d_pre"].fillna(0.0).to_numpy()
    chin = df["is_chinext"].fillna(0).to_numpy()
    px = df["close"].fillna(20.0).to_numpy()
    h3 = df["head_3d30"].fillna(0.20).to_numpy()
    kzt = df["kpl_hist180_allzt_max"].fillna(0).to_numpy()
    kelo = df["kpl_hist180_elo_max"].fillna(0).to_numpy()
    ep_post = df["earn_pos_t0_post_B"].fillna(0).to_numpy()
    onet = df["lhb_t0_org_net_yi"].fillna(0.0).to_numpy()
    lh = df["lhb_t0_lhasa_cnt"].fillna(0.0).to_numpy()
    surf = df["lhb_t0_surf_bad"].fillna(0.0).to_numpy()
    m5 = df["mkt_prev5d_ew"].fillna(0.0).to_numpy()
    mon = df["is_monday"].fillna(0).to_numpy()
    comm = df["comm_posts_3d_pit"].fillna(0).to_numpy()

    comps = pd.DataFrame({
        "I01_T1Open": np.where(og1 < -0.025, -14, np.where(og1 > 0.040, -6, np.where((og1 >= -0.012) & (og1 <= 0.018), 5, 0))),
        "I02_Pos20": np.where(p20 <= 0.25, 8, np.where(p20 <= 0.42, 4, np.where(p20 > 0.65, -8, 0))),
        "I03_DistMA60": np.where(dm60 <= -0.15, 10, np.where(dm60 <= 0.0, 5, np.where(dm60 > 0.10, -8, 0))),
        "I04_RealFreeMcap": np.where((cm >= 150.0) | (rfm >= 80.0), -10, np.where(rfm <= 25.0, 8, np.where(rfm <= 45.0, 3, 0))),
        "I05_LockTop10": np.where(np.isnan(lt10), 0, np.where(lt10 <= 25.0, 4, np.where(lt10 >= 55.0, -4, 0))),
        "I06_RealTO_Climax": np.where(rto > 28.0, -8, np.where((rto >= 6.0) & (rto <= 22.0), 3, 0)),
        "I07_CLV": np.where(clv >= 0.80, 5, np.where(clv < 0.55, -8, 0)),
        "I08_AntiOldDragon": np.where(b7 == 0, 6, np.where(b7 >= 2, -8, 0)),
        "I09_BoardPrice": np.where(chin == 1, 5, 0) + np.where(px <= 15.0, 4, np.where(px > 45.0, -4, 0)),
        "I10_BarrierVeto": np.where(h3 < 0.05, -12, 0),
        "I11_KPL_ThemeElo": np.where(kzt >= 18, -4, np.where(((kzt >= 1) & (kzt <= 14)) | (kelo > 25.0), 5, 0)),
        "I12_EarnPostKill": np.where(ep_post == 1, -20, 0),
        "I13_LHB_Seats": np.where((lh >= 1) | (surf == 1), -18, np.where(onet > 0.02, 8, 0)),
        "I14_MarketRegime": np.where(m5 >= -0.02, 5, np.where(m5 >= -0.05, -8, 2)) + np.where(mon == 1, -6, 0),
        "I15_CommOverheat": np.where(comm >= 4, -5, 0),
    }, index=df.index)
    total = 50 + comps.sum(axis=1)
    return total.astype(int), comps


def build_trades(df_sub: pd.DataFrame, paths: dict, mkt_ew: dict, dt_to_gidx: dict, exit_rule: str) -> pd.DataFrame:
    rows = []
    for r in df_sub.itertuples(index=False):
        res = simulate_exit_v1(paths, mkt_ew, r.c6, dt_to_gidx[r.dt], exit_rule, float(r.mkt_prev5d_ew))
        if res is None:
            continue
        bdt, bpx, sdt, spx, nret, why, hbars = res
        rows.append({
            "signal_dt": r.dt, "buy_dt": bdt, "sell_dt": sdt,
            "c6": r.c6, "sec_name_pit": r.sec_name_pit, "is_delisted": int(r.is_delisted),
            "score": int(r.score_v1), "rank_in_day": int(r.rank_in_day),
            "circ_mcap": round(float(r.circ_mcap), 2),
            "real_free_mcap": round(float(r.real_free_mcap), 2),
            "lock_top10": round(float(r.lock_top10), 2) if pd.notna(r.lock_top10) else np.nan,
            "t1_open_gap_pct": round(float(r.t1_open_gap) * 100, 2),
            "buy_px": round(bpx, 4), "sell_px": round(spx, 4),
            "net_ret": nret, "net_ret_pct": round(nret * 100, 2),
            "hold_bars": int(hbars), "exit_reason": why,
        })
    return pd.DataFrame(rows)


def eval_all_windows(tdf: pd.DataFrame, mkt: pd.DataFrame, m_trials: int = 150) -> dict:
    wins = [
        ("FULL", "2021-01-04", "2026-11-23", False),
        ("IS", "2021-01-04", "2024-08-31", False),
        ("OOS", "2024-09-01", "2026-11-23", False),
        ("OOS_ex924", "2024-09-01", "2026-11-23", True),
        ("Y2026", "2026-01-01", "2026-11-23", False),
    ]
    out = {}
    for wnm, sdt, edt, ex9 in wins:
        out[wnm] = calc_window_d15(tdf, mkt, sdt, edt, exclude_924=ex9, m_trials=m_trials)
    return out


def monkey_pvalue(tdf: pd.DataFrame, bg_rets: np.ndarray, n_sim: int = 5000) -> float:
    _, nav_obs, _, _ = _sim_k_slots_v1(tdf, 1)
    t1, _, _, _ = _sim_k_slots_v1(tdf, 1)
    n_pick = len(t1)
    if n_pick <= 0 or len(bg_rets) == 0:
        return 1.0
    rng = np.random.default_rng(42)
    draws = rng.choice(bg_rets, size=(n_sim, n_pick), replace=True)
    navs = np.prod(1.0 + draws, axis=1)
    return round(float((navs >= nav_obs).mean()), 4)


def main():
    t0 = time.time()
    base = pd.read_parquet(f"{OUT_DIR}/v1_beta_base_pool.parquet")
    mkt = pd.read_parquet(f"{P1_DIR}/market_daily.parquet")
    mkt_ew = dict(zip(mkt["dt"], mkt["ew_ret_all"]))
    pk = pickle.load(open(f"{OUT_DIR}/v1_stock_paths.pkl", "rb"))
    paths, dt_to_gidx = pk["paths"], pk["dt_to_gidx"]

    # Historical buyable universe (exclude 2026-11-23 which has no T+1 in parquet yet; handled in Step 4 live)
    hist = base[(base["dt"] <= "2026-11-20") & (base["buyable_B"])].copy().reset_index(drop=True)
    sc, comps = compute_score_beta_v1(hist)
    hist["score_v1"] = sc
    for col in comps.columns:
        hist[f"pt_{col}"] = comps[col].values
    hist = hist.sort_values(["dt", "score_v1", "circ_mcap", "c6"], ascending=[True, False, True, True]).reset_index(drop=True)
    hist["rank_in_day"] = hist.groupby("dt").cumcount() + 1
    hist["pass_A"] = (hist["score_v1"] >= 85) & (hist["rank_in_day"] <= 3)
    hist["pass_S"] = (hist["score_v1"] >= 94) & (hist["rank_in_day"] <= 3)

    # 1. Save scorecard_beta_v1.csv
    sc_rows = [{"item": k, "name_cn": nm, "rule": rl, "timing": tm} for k, nm, rl, tm in SCORECARD_SPEC]
    sc_rows.append({"item": "BASE_AND_TIERS", "name_cn": "基础分与分级门槛", "rule": "Base=50; A档>=85(每日Top3); S档>=94(每日Top3)", "timing": "T+1_0925"})
    pd.DataFrame(sc_rows).to_csv(f"{OUT_DIR}/scorecard_beta_v1.csv", index=False, encoding="utf-8-sig")

    # 2. Save all_scored_signals_beta_v1.csv (ALL 13,539 hist + attach 4 exit returns!)
    for ex_lbl, ex_rule in [("ret_dyn_yang_tp15", "DYN_YANG_TP15_T5"), ("ret_tp12_sl07_t5", "GRID_TP12_SL07_T5"), ("ret_fix_t2", "FIX_T2"), ("ret_fix_t5", "FIX_T5")]:
        vals = []
        for r in hist.itertuples(index=False):
            res = simulate_exit_v1(paths, mkt_ew, r.c6, dt_to_gidx[r.dt], ex_rule, float(r.mkt_prev5d_ew))
            vals.append(round(res[4] * 100, 3) if res else np.nan)
        hist[f"{ex_lbl}_pct"] = vals

    export_cols = [
        "dt", "t1_dt", "c6", "sec_name_pit", "is_delisted", "score_v1", "rank_in_day", "pass_A", "pass_S",
        "ret", "t1_open_gap", "pos20_pre", "dist_ma60_pre", "circ_mcap", "lock_top10", "real_free_mcap", "real_to",
        "clv", "big7_cnt_20d_pre", "is_chinext", "close", "head_3d30", "kpl_hist180_allzt_max", "kpl_hist180_elo_max",
        "earn_pos_t0_post_B", "lhb_t0_org_net_yi", "lhb_t0_lhasa_cnt", "lhb_t0_surf_bad", "comm_posts_3d_pit",
        "ew_ret_all", "up_ratio_all", "mkt_prev5d_ew", "is_monday",
        "ret_dyn_yang_tp15_pct", "ret_tp12_sl07_t5_pct", "ret_fix_t2_pct", "ret_fix_t5_pct",
    ] + [f"pt_{c}" for c in comps.columns]
    hist[export_cols].to_csv(f"{OUT_DIR}/all_scored_signals_beta_v1.csv", index=False, encoding="utf-8-sig")

    # 3. 5-Bucket Monotonicity across IS, OOS, OOS_ex924, FULL
    b_bins = [-999, 50, 65, 75, 85, 999]
    b_lbls = ["Q1(<50)", "Q2[50,65)", "Q3[65,75)", "Q4[75,85)", "Q5(>=85)"]
    hist["score_bucket"] = pd.cut(hist["score_v1"], bins=b_bins, labels=b_lbls, right=False)
    bk_rows = []
    for wnm, mask in [
        ("IS", hist["dt"] <= "2024-08-31"),
        ("OOS", hist["dt"] >= "2024-09-01"),
        ("OOS_ex924", (hist["dt"] >= "2024-09-01") & (~hist["dt"].between("2024-09-24", "2024-10-08"))),
        ("FULL", hist["dt"] >= "2021-01-04"),
    ]:
        sub_w = hist[mask]
        for b in b_lbls:
            sb = sub_w[sub_w["score_bucket"] == b]
            y = sb["ret_dyn_yang_tp15_pct"].dropna()
            bk_rows.append({
                "window": wnm, "bucket": b, "n": int(len(y)),
                "mean_pct": round(float(y.mean()), 2) if len(y) else np.nan,
                "wr_pct": round(float((y > 0).mean() * 100), 1) if len(y) else np.nan,
                "dew_mean_pct": round(float(sb.groupby("dt")["ret_dyn_yang_tp15_pct"].mean().mean()), 2) if len(sb) else np.nan,
            })
    pd.DataFrame(bk_rows).to_csv(f"{OUT_DIR}/score_buckets_beta_v1.csv", index=False)

    # 4. Complete Leave-One-Out Ablation on IS & OOS_ex924 (at A>=85 Top3, using DYN_YANG_TP15_T5)
    def run_score_eval(sc_series, th, w_sdt, w_edt, ex9=False):
        tmp = hist.copy()
        tmp["score_v1"] = sc_series
        sel = tmp[tmp["score_v1"] >= th].sort_values(["dt", "score_v1", "circ_mcap", "c6"], ascending=[True, False, True, True]).groupby("dt", sort=False).head(3)
        sel["rank_in_day"] = sel.groupby("dt").cumcount() + 1
        tdf = build_trades(sel, paths, mkt_ew, dt_to_gidx, "DYN_YANG_TP15_T5")
        return calc_window_d15(tdf, mkt, w_sdt, w_edt, exclude_924=ex9)

    ab_rows = []
    b_is = run_score_eval(hist["score_v1"], 85, "2021-01-04", "2024-08-31")
    b_ox = run_score_eval(hist["score_v1"], 85, "2024-09-01", "2026-11-23", ex9=True)
    ab_rows.append({
        "dropped_item": "NONE (V1_15)", "is_1s": b_is["nav_1s"], "is_3s": b_is["nav_3s"], "is_ex5_3s": b_is["ex5_3s"], "is_mdd3": b_is["mdd_3s_pct"],
        "oos_ex924_1s": b_ox["nav_1s"], "oos_ex924_3s": b_ox["nav_3s"], "oos_ex924_ex5_3s": b_ox["ex5_3s"],
    })
    for col in comps.columns:
        sc_l = hist["score_v1"] - hist[f"pt_{col}"]
        m_is = run_score_eval(sc_l, 85, "2021-01-04", "2024-08-31")
        m_ox = run_score_eval(sc_l, 85, "2024-09-01", "2026-11-23", ex9=True)
        ab_rows.append({
            "dropped_item": col, "is_1s": m_is["nav_1s"], "is_3s": m_is["nav_3s"], "is_ex5_3s": m_is["ex5_3s"], "is_mdd3": m_is["mdd_3s_pct"],
            "oos_ex924_1s": m_ox["nav_1s"], "oos_ex924_3s": m_ox["nav_3s"], "oos_ex924_ex5_3s": m_ox["ex5_3s"],
        })
    pd.DataFrame(ab_rows).to_csv(f"{OUT_DIR}/ablation_beta_v1.csv", index=False)

    # 5. Full 39-Exit-Tree Comparison across IS, OOS, OOS_ex924, FULL for A & S
    EXITS = ["FIX_T2", "FIX_T3", "FIX_T4", "FIX_T5"]
    for tp in ["08", "10", "12", "15"]:
        for sl in ["NO", "05", "07", "10"]:
            EXITS.append(f"GRID_TP{tp}_SL{sl}_T5")
    EXITS += ["GRID_TP10_SLNO_T3", "GRID_TP10_SL06_T3", "GRID_TP12_SL07_T3", "GRID_TP08_SL05_T3"]
    EXITS += [
        "DYN_ZT_RIDE_T3", "DYN_YANG_TP15_T5", "DYN_TRAIL5_T5", "DYN_YANG_TRAIL5_T5",
        "DYN_WEAK_OPEN_CUT", "DYN_WEAK_CLOSE_CUT", "DYN_WEAK_GAP_CUT",
        "DYN_STAG2_T2_T5", "DYN_STAG2_T3_T5", "DYN_MKT_CRASH_T5",
        "DYN_TREE_FULL_OPEN", "DYN_TREE_FULL_CLOSE", "DYN_TREE_FULL_MKT", "DYN_TREE_LIGHT", "DYN_TREE_ICE_FAST",
    ]
    exit_rows = []
    sel_A = hist[hist["pass_A"]].copy()
    sel_S = hist[hist["pass_S"]].copy()
    for t_nm, df_s in [("A_ge85", sel_A), ("S_ge94", sel_S)]:
        for ex in EXITS:
            tdf = build_trades(df_s, paths, mkt_ew, dt_to_gidx, ex)
            w = eval_all_windows(tdf, mkt)
            exit_rows.append({
                "tier": t_nm, "exit_rule": ex,
                "IS_1s": w["IS"]["nav_1s"], "IS_3s": w["IS"]["nav_3s"], "IS_ex5_3s": w["IS"]["ex5_3s"], "IS_mdd3": w["IS"]["mdd_3s_pct"],
                "OOS_1s": w["OOS"]["nav_1s"], "OOS_3s": w["OOS"]["nav_3s"], "OOS_ex5_3s": w["OOS"]["ex5_3s"], "OOS_mdd3": w["OOS"]["mdd_3s_pct"],
                "OOSx924_1s": w["OOS_ex924"]["nav_1s"], "OOSx924_3s": w["OOS_ex924"]["nav_3s"], "OOSx924_ex5_3s": w["OOS_ex924"]["ex5_3s"],
                "FULL_1s": w["FULL"]["nav_1s"], "FULL_3s": w["FULL"]["nav_3s"], "FULL_ex5_3s": w["FULL"]["ex5_3s"], "FULL_mdd3": w["FULL"]["mdd_3s_pct"],
                "Y2026_1s": w["Y2026"]["nav_1s"], "Y2026_3s": w["Y2026"]["nav_3s"],
            })
    pd.DataFrame(exit_rows).to_csv(f"{OUT_DIR}/exit_opt_beta_v1.csv", index=False)

    # 6. Export Final Ledgers & Complete D15/Yearly/Plateau Summary for A & S under DYN_YANG_TP15_T5
    led_A = build_trades(sel_A, paths, mkt_ew, dt_to_gidx, "DYN_YANG_TP15_T5")
    led_S = build_trades(sel_S, paths, mkt_ew, dt_to_gidx, "DYN_YANG_TP15_T5")
    led_A.to_csv(f"{OUT_DIR}/ledger_beta_v1_A.csv", index=False, encoding="utf-8-sig")
    led_S.to_csv(f"{OUT_DIR}/ledger_beta_v1_S.csv", index=False, encoding="utf-8-sig")

    bg_rets = hist["ret_dyn_yang_tp15_pct"].dropna().to_numpy() / 100.0
    sum_A = eval_all_windows(led_A, mkt)
    sum_S = eval_all_windows(led_S, mkt)
    monkey_A = monkey_pvalue(led_A, bg_rets)
    monkey_S = monkey_pvalue(led_S, bg_rets)

    # Yearly breakdown
    yearly = {}
    for yr in ["2021", "2022", "2023", "2024", "2025", "2026"]:
        s_dt, e_dt = f"{yr}-01-01", f"{yr}-12-31" if yr != "2026" else "2026-11-23"
        yearly[yr] = {
            "A": calc_window_d15(led_A, mkt, s_dt, e_dt),
            "S": calc_window_d15(led_S, mkt, s_dt, e_dt),
        }

    # +-20% Parameter Plateau (Score thresholds & Exit TP/SL perturbations)
    plateau = {"A_th_sweep": {}, "S_th_sweep": {}, "exit_param_sweep_A": {}}
    for th in [80, 82, 85, 88, 90]:
        sub_p = hist[hist["score_v1"] >= th].sort_values(["dt", "score_v1", "circ_mcap", "c6"], ascending=[True, False, True, True]).groupby("dt", sort=False).head(3)
        sub_p["rank_in_day"] = sub_p.groupby("dt").cumcount() + 1
        tp_df = build_trades(sub_p, paths, mkt_ew, dt_to_gidx, "DYN_YANG_TP15_T5")
        w = eval_all_windows(tp_df, mkt)
        plateau["A_th_sweep"][str(th)] = {k: {"1s": w[k]["nav_1s"], "3s": w[k]["nav_3s"], "ex5_3s": w[k]["ex5_3s"]} for k in ["IS", "OOS_ex924", "FULL"]}
    for th in [90, 92, 94, 96, 98]:
        sub_p = hist[hist["score_v1"] >= th].sort_values(["dt", "score_v1", "circ_mcap", "c6"], ascending=[True, False, True, True]).groupby("dt", sort=False).head(3)
        sub_p["rank_in_day"] = sub_p.groupby("dt").cumcount() + 1
        tp_df = build_trades(sub_p, paths, mkt_ew, dt_to_gidx, "DYN_YANG_TP15_T5")
        w = eval_all_windows(tp_df, mkt)
        plateau["S_th_sweep"][str(th)] = {k: {"1s": w[k]["nav_1s"], "3s": w[k]["nav_3s"], "ex5_3s": w[k]["ex5_3s"]} for k in ["IS", "OOS_ex924", "FULL"]}
    for ex_r in ["GRID_TP10_SL07_T5", "GRID_TP12_SL07_T5", "GRID_TP15_SL07_T5", "GRID_TP10_SL10_T5", "DYN_YANG_TP15_T5", "DYN_YANG_TRAIL5_T5"]:
        tp_df = build_trades(sel_A, paths, mkt_ew, dt_to_gidx, ex_r)
        w = eval_all_windows(tp_df, mkt)
        plateau["exit_param_sweep_A"][ex_r] = {k: {"1s": w[k]["nav_1s"], "3s": w[k]["nav_3s"], "ex5_3s": w[k]["ex5_3s"]} for k in ["IS", "OOS_ex924", "FULL"]}

    # Delisted 20cm stats
    dl_stats = {
        "base_pool_delisted_rows": int(base[base["dt"] <= "2026-11-20"]["is_delisted"].sum()),
        "base_pool_delisted_tickers": int(base[(base["dt"] <= "2026-11-20") & (base["is_delisted"] == 1)]["c6"].nunique()),
        "A_raw_delisted_trades": int(led_A["is_delisted"].sum()),
        "A_3slot_delisted_trades": int(_sim_k_slots_v1(led_A, 3)[0]["is_delisted"].sum()),
        "S_raw_delisted_trades": int(led_S["is_delisted"].sum()),
        "S_3slot_delisted_trades": int(_sim_k_slots_v1(led_S, 3)[0]["is_delisted"].sum()),
    }

    summary = {
        "A_ge85": sum_A, "S_ge94": sum_S,
        "monkey_p_A": monkey_A, "monkey_p_S": monkey_S,
        "yearly": yearly, "plateau": plateau, "delisted_audit": dl_stats,
    }
    with open(f"{OUT_DIR}/beta_v1_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[DONE Step 3 in {time.time()-t0:.1f}s] Monkey p(A)={monkey_A}, p(S)={monkey_S}")
    print("Delisted audit:", dl_stats)
    for nm, sm in [("A_ge85", sum_A), ("S_ge94", sum_S)]:
        print(f"\n=== {nm} + DYN_YANG_TP15_T5 ===")
        for wk in ["FULL", "IS", "OOS", "OOS_ex924", "Y2026"]:
            mw = sm[wk]
            print(f"  {wk:9s} | d={mw['n_days']:2d} n={mw['n_trades']:3d} | 1s={mw['nav_1s']:6.3f}x(N={mw['n_1s']:2d},WR={mw['wr_1s']:4.1f}%,MDD={mw['mdd_1s_pct']:5.1f}%,ex5={mw['ex5_1s']:5.2f}x,cap10m={mw['cap1m_10m_1s']:5.2f}x,t={mw['hlz_t_1s_ex']:4.2f},DSR={mw['dsr_1s']:.3f}) | "
                  f"3s={mw['nav_3s']:6.3f}x(N={mw['n_3s']:3d},WR={mw['wr_3s']:4.1f}%,MDD={mw['mdd_3s_pct']:5.1f}%,ex5={mw['ex5_3s']:5.2f}x,f50={mw['fee50_3s']:5.2f}x,cap10m={mw['cap1m_10m_3s']:5.2f}x,t={mw['hlz_t_3s_ex']:4.2f},DSR={mw['dsr_3s']:.3f}) | "
                  f"dew={mw['dew_nav']:6.3f}x | exHS300_3s={mw['ex_3s_hs300_pp']:+6.1f}pp exEW20_3s={mw['ex_3s_ew20_pp']:+6.1f}pp")


if __name__ == "__main__":
    main()
