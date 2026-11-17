#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
s1_intraday_sweep.py - 盘中撬板全谱系因子扫描 (Task 1)
4买 (E1..E4) x 10卖 (X1..X10) x 全子池 x 300+ 因子切片全矩阵大扫除
"""
import os, time, pickle
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
PARQUET_FILE = f"{BASE_DIR}/full_pry_master_enriched.parquet"
RETURN_MATRIX_FILE = f"{BASE_DIR}/return_matrix_8x10.pkl"
OUT_CSV = f"{BASE_DIR}/s1_factor_catalog.csv"

def main():
    t0 = time.time()
    print("Loading enriched master parquet and return matrix...")
    df = pd.read_parquet(PARQUET_FILE)
    with open(RETURN_MATRIX_FILE, "rb") as f:
        rm = pickle.load(f)

    n = len(df)
    is_mask = (df["dt_str"] < "2025-01-01").values
    oos_mask = (df["dt_str"] >= "2025-01-01").values
    base_clean = ((~df["is_st_or_delist"].values) & (df["pre_c"].values >= 2.0))

    # Pre-extract all candidate factor masks (strictly zero-lookahead!)
    # Sub-pools
    dt_streak = df["prev_dt_streak"].fillna(0).values
    yz_streak = df["prev_yizi_dt_streak"].fillna(0).values

    # 1. Panic sensors (09:25)
    mkt_open_dt = df["mkt_open_dt_0925"].fillna(0).values
    mkt_open_lt5 = df["mkt_open_lt5_0925"].fillna(0).values
    mkt_open_avg = df["mkt_open_avg_0925"].fillna(0).values
    mkt_open_zt = df["mkt_open_zt_0925"].fillna(0).values

    # 2. Chip lock & float
    lock10 = df["lock_top10"].fillna(0).values
    lock5 = df["lock_big5"].fillna(0).values
    rf_mcap = df["real_free_mcap"].fillna(9999).values

    # 3. Trend vs Oversold
    ret60 = df["prev_ret60"].fillna(0).values
    ma20_up = df["prev_ma20_up"].fillna(False).values.astype(bool)
    zt5 = df["prev_zt5"].fillna(0).values
    ret10 = df["prev_ret10"].fillna(0).values
    dd20 = df["prev_dd20"].fillna(1.0).values
    dd60 = df["prev_dd60"].fillna(1.0).values
    pos20 = df["prev_pos20"].fillna(0.5).values

    # 4. Volume & Yizi
    vr_prev = df["prev_vr"].fillna(1.0).values

    # 5. Dragon Tiger & seats
    inst_sell = df["inst_sell_prev"].fillna(0).values
    inst_buy = df["inst_buy_prev"].fillna(0).values
    north_net = df["north_net_prev"].fillna(0).values
    youzi_cnt = df["youzi_cnt_prev"].fillna(0).values
    quant_cnt = df["quant_cnt_prev"].fillna(0).values
    lhasa_cnt = df["lhasa_cnt_prev"].fillna(0).values

    # 6. Announcements & Survey & Community
    n_poison = df["n_poison90"].fillna(False).values.astype(bool)
    n_buyback = df["n_buyback90"].fillna(False).values.astype(bool)
    n_win = df["n_win90"].fillna(False).values.astype(bool)
    ir8 = df["ir8"].fillna(False).values.astype(bool)
    ir30 = df["ir30_cnt"].fillna(0).values
    comm24 = df["comm24"].fillna(0).values

    # Define Factor Dictionary
    factor_dict = {
        # Baseline
        "All_baseline": np.ones(n, dtype=bool),
        
        # Sub-pool splits
        "Sub_prev_dt_streak_0": (dt_streak == 0),
        "Sub_prev_dt_streak_1": (dt_streak == 1),
        "Sub_prev_dt_streak_ge2": (dt_streak >= 2),
        "Sub_prev_dt_streak_ge3": (dt_streak >= 3),
        "Sub_prev_yizi_dt_streak_ge1": (yz_streak >= 1),
        "Sub_prev_yizi_dt_streak_ge2": (yz_streak >= 2),
        "Sub_prev_dt_streak_ge2_no_yizi": (dt_streak >= 2) & (yz_streak == 0),

        # 09:25 Panic Sensor
        "Panic_mkt_open_dt_ge10": (mkt_open_dt >= 10),
        "Panic_mkt_open_dt_ge20": (mkt_open_dt >= 20),
        "Panic_mkt_open_dt_ge35": (mkt_open_dt >= 35),
        "Panic_mkt_open_dt_ge50": (mkt_open_dt >= 50),
        "Panic_mkt_open_dt_lt10": (mkt_open_dt < 10),
        "Panic_mkt_open_lt5_ge50": (mkt_open_lt5 >= 50),
        "Panic_mkt_open_lt5_ge100": (mkt_open_lt5 >= 100),
        "Panic_mkt_open_lt5_ge200": (mkt_open_lt5 >= 200),
        "Panic_mkt_open_avg_le_-1.5pct": (mkt_open_avg <= -0.015),
        "Panic_mkt_open_avg_le_-2.5pct": (mkt_open_avg <= -0.025),
        "Calm_mkt_open_zt_ge20": (mkt_open_zt >= 20),
        "Calm_mkt_open_zt_ge50": (mkt_open_zt >= 50),

        # Chip Lock & Float
        "Lock_top10_ge50": (lock10 >= 50.0),
        "Lock_top10_ge60": (lock10 >= 60.0),
        "Lock_top10_lt40": (lock10 < 40.0),
        "Lock_big5_ge40": (lock5 >= 40.0),
        "Lock_big5_ge50": (lock5 >= 50.0),
        "Float_real_free_lt10y": (rf_mcap < 10.0),
        "Float_real_free_10_to_25y": (rf_mcap >= 10.0) & (rf_mcap < 25.0),
        "Float_real_free_25_to_50y": (rf_mcap >= 25.0) & (rf_mcap < 50.0),
        "Float_real_free_ge50y": (rf_mcap >= 50.0),

        # Trend Plunge vs Oversold
        "Trend_bull_plunge_ret60_ge20_ma20up": (ret60 > 0.20) & ma20_up & (zt5 == 0),
        "Trend_bull_plunge_ret60_ge40_ma20up": (ret60 > 0.40) & ma20_up & (zt5 == 0),
        "Oversold_ret10_le_-25pct": (ret10 < -0.25),
        "Oversold_ret10_le_-15pct": (ret10 < -0.15),
        "Oversold_dd20_le_0.72": (dd20 < 0.72),
        "Oversold_dd60_le_0.60": (dd60 < 0.60),
        "Oversold_pos20_le_0.05": (pos20 < 0.05),
        "Oversold_combo_ret10_and_dd20": (ret10 < -0.20) & (dd20 < 0.75),

        # Volume ratio & Yizi contract
        "Vol_prev_vr_le_0.4": (vr_prev < 0.4),
        "Vol_prev_vr_0.4_to_1.0": (vr_prev >= 0.4) & (vr_prev < 1.0),
        "Vol_prev_vr_ge_2.0": (vr_prev >= 2.0),
        "Vol_prev_vr_ge_3.0": (vr_prev >= 3.0),

        # Dragon Tiger Seats
        "Seat_inst_sell_prev_gt0": (inst_sell > 0),
        "Seat_inst_buy_prev_gt0": (inst_buy > 0),
        "Seat_north_net_gt0": (north_net > 0),
        "Seat_north_net_lt0": (north_net < 0),
        "Seat_youzi_cnt_gt0": (youzi_cnt > 0),
        "Seat_quant_cnt_gt0": (quant_cnt > 0),
        "Seat_lhasa_cnt_ge2": (lhasa_cnt >= 2),

        # Announcements & Survey & Community
        "News_n_poison90": n_poison,
        "News_n_buyback90": n_buyback,
        "News_n_win90": n_win,
        "Survey_ir8": ir8,
        "Survey_ir30_gt0": (ir30 > 0),
        "Comm_cold_comm24_eq0": (comm24 == 0),
        "Comm_hot_comm24_ge5": (comm24 >= 5),

        # Synergy Combos
        "Combo_2dt_and_panic_open_dt_ge20": (dt_streak >= 2) & (mkt_open_dt >= 20),
        "Combo_2dt_and_lock10_ge50": (dt_streak >= 2) & (lock10 >= 50.0),
        "Combo_2dt_and_float_lt25y": (dt_streak >= 2) & (rf_mcap < 25.0),
        "Combo_2dt_and_oversold_ret10_le_-25pct": (dt_streak >= 2) & (ret10 < -0.25),
        "Combo_2dt_and_inst_sell_gt0": (dt_streak >= 2) & (inst_sell > 0),
        "Combo_2dt_and_buyback": (dt_streak >= 2) & n_buyback,
        "Combo_2dt_and_comm_cold": (dt_streak >= 2) & (comm24 == 0),
        "Combo_1dt_and_panic_open_dt_ge35": (dt_streak == 1) & (mkt_open_dt >= 35),
        "Combo_1dt_and_oversold_ret10_le_-20pct": (dt_streak == 1) & (ret10 < -0.20),
        "Combo_1dt_and_lock10_ge50": (dt_streak == 1) & (lock10 >= 50.0),
        "Combo_yizi_and_inst_sell_gt0": (yz_streak >= 1) & (inst_sell > 0),
        "Combo_yizi_and_float_lt25y": (yz_streak >= 1) & (rf_mcap < 25.0),
    }

    print(f"Total factor definitions: {len(factor_dict)}")

    # We will sweep:
    # Entries: E1_opendt_lift15, E2_opendt_lift35, E4_intradive_dt (and E3_opendt_red0 for baseline/key factors)
    # Exits: X1, X2, X4, X6, X7, X9, X10
    entries = ["E1_opendt_lift15", "E2_opendt_lift35", "E4_intradive_dt"]
    exits = ["X1", "X2", "X4", "X6", "X7", "X9", "X10"]

    records = []
    total_slices = 0

    for fname, fmask in factor_dict.items():
        for ename in entries:
            # Also test across exits
            for xname in exits:
                r_arr = rm["ret"][ename][xname]
                valid = (~np.isnan(r_arr)) & base_clean & fmask
                n_all = int(valid.sum())
                if n_all < 5:
                    continue

                r_all = r_arr[valid]
                w_all = float((r_all > 0).mean())
                m_all = float(r_all.mean())
                std_all = float(r_all.std()) if n_all > 1 else 0.0
                sharpe_proxy = float(m_all / std_all * np.sqrt(250)) if std_all > 1e-6 else 0.0
                g_all = r_all[r_all > 0]
                l_all = r_all[r_all < 0]
                gain_all = float(g_all.mean()) if len(g_all) > 0 else 0.0
                loss_all = float(abs(l_all.mean())) if len(l_all) > 0 else 1.0
                plr_all = float(gain_all / loss_all) if loss_all > 1e-6 else 0.0

                # IS stats (2022-2024)
                v_is = valid & is_mask
                n_is = int(v_is.sum())
                if n_is > 0:
                    r_is = r_arr[v_is]
                    w_is = float((r_is > 0).mean())
                    m_is = float(r_is.mean())
                else:
                    w_is, m_is = 0.0, 0.0

                # OOS stats (2025-2026)
                v_oos = valid & oos_mask
                n_oos = int(v_oos.sum())
                if n_oos > 0:
                    r_oos = r_arr[v_oos]
                    w_oos = float((r_oos > 0).mean())
                    m_oos = float(r_oos.mean())
                else:
                    w_oos, m_oos = 0.0, 0.0

                # Equal-weighted cumulative product
                cum_eq = float(np.prod(1.0 + r_all) - 1.0) if n_all <= 2000 else float(np.sum(r_all))

                records.append({
                    "factor_name": fname,
                    "entry": ename,
                    "exit": xname,
                    "n_all": n_all,
                    "win_all": round(w_all, 4),
                    "plr_all": round(plr_all, 2),
                    "mean_all_pct": round(m_all * 100, 2),
                    "sharpe_proxy": round(sharpe_proxy, 2),
                    "n_is": n_is,
                    "win_is": round(w_is, 4),
                    "mean_is_pct": round(m_is * 100, 2),
                    "n_oos": n_oos,
                    "win_oos": round(w_oos, 4),
                    "mean_oos_pct": round(m_oos * 100, 2),
                })
                total_slices += 1

    # Also add E3 for key factors
    for fname in ["All_baseline", "Sub_prev_dt_streak_ge2", "Sub_prev_yizi_dt_streak_ge1", "Panic_mkt_open_dt_ge20", "Combo_2dt_and_panic_open_dt_ge20"]:
        fmask = factor_dict[fname]
        for xname in ["X1", "X4", "X7", "X9", "X10"]:
            r_arr = rm["ret"]["E3_opendt_red0"][xname]
            valid = (~np.isnan(r_arr)) & base_clean & fmask
            n_all = int(valid.sum())
            if n_all < 5:
                continue
            r_all = r_arr[valid]
            w_all = float((r_all > 0).mean())
            m_all = float(r_all.mean())
            std_all = float(r_all.std()) if n_all > 1 else 0.0
            sharpe_proxy = float(m_all / std_all * np.sqrt(250)) if std_all > 1e-6 else 0.0
            g_all = r_all[r_all > 0]; l_all = r_all[r_all < 0]
            gain_all = float(g_all.mean()) if len(g_all) > 0 else 0.0
            loss_all = float(abs(l_all.mean())) if len(l_all) > 0 else 1.0
            plr_all = float(gain_all / loss_all) if loss_all > 1e-6 else 0.0
            v_is = valid & is_mask; n_is = int(v_is.sum())
            w_is = float((r_arr[v_is] > 0).mean()) if n_is > 0 else 0.0
            m_is = float(r_arr[v_is].mean()) if n_is > 0 else 0.0
            v_oos = valid & oos_mask; n_oos = int(v_oos.sum())
            w_oos = float((r_arr[v_oos] > 0).mean()) if n_oos > 0 else 0.0
            m_oos = float(r_arr[v_oos].mean()) if n_oos > 0 else 0.0
            records.append({
                "factor_name": fname,
                "entry": "E3_opendt_red0",
                "exit": xname,
                "n_all": n_all,
                "win_all": round(w_all, 4),
                "plr_all": round(plr_all, 2),
                "mean_all_pct": round(m_all * 100, 2),
                "sharpe_proxy": round(sharpe_proxy, 2),
                "n_is": n_is,
                "win_is": round(w_is, 4),
                "mean_is_pct": round(m_is * 100, 2),
                "n_oos": n_oos,
                "win_oos": round(w_oos, 4),
                "mean_oos_pct": round(m_oos * 100, 2),
            })
            total_slices += 1

    res_df = pd.DataFrame(records)
    res_df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"Generated {len(res_df)} factor slices! Saved to {OUT_CSV}. Elapsed: {time.time()-t0:.2f}s")

if __name__ == "__main__":
    main()
