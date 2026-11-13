#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part 2B: Materialize Daily Env, Price Trajectory Store, and All 5 Strategy Candidate Tables with All 32 1-to-2 Factors."""
import os, sys, json, time, bisect, pickle, datetime
from collections import defaultdict
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from part2a_daily_and_env import build_daily_panel_and_env, SANDBOX, OUT_DIR
from pit_aux_loaders import load_aux_pit_sources, CSRC_PURE_OUTSIDER, HARD_TECH_RE


def pit_lock_lookup(holders_idx, c6, dt_str):
    valid = [r for r in holders_idx.get(c6, []) if r[0] < dt_str]
    if not valid:
        return 38.0, 25.0
    b = max(valid, key=lambda x: x[1])
    return float(b[2]), float(b[3])


def main():
    t0 = time.time()
    df, all_dts, dt_to_idx = build_daily_panel_and_env()
    holders_idx = json.load(open(f"{OUT_DIR}/pit_top10_all_codes.json", "r", encoding="utf-8"))
    idx_klines = json.load(open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8"))

    sub21 = df[df["dt_str"] >= "2021-10-01"].copy()
    target_codes = set(sub21["c6"].unique())
    ind_map, name_map, tape_map, lhasa_map, notice_by_c6, ir_grp, comm_grp, build_8y_theme = load_aux_pit_sources(target_codes)
    stock_theme_5y, _ = build_8y_theme(df)

    # Build daily market environment table (2021-10-01 to 2026-11-10)
    sub21["csrc_ind"] = sub21["c6"].map(ind_map).fillna("")
    sub21["prev_streak"] = sub21.groupby("c6")["streak"].shift(1).fillna(0).astype(int)
    sub21["prev_dt_streak"] = sub21.groupby("c6")["dt_streak"].shift(1).fillna(0).astype(int)
    sub21["prev_is_yizi"] = sub21.groupby("c6")["is_yizi"].shift(1).fillna(False)
    sub21["buyable_open"] = (sub21["open"] < sub21["zt_price"] - 0.011) & (sub21["open"] > sub21["dt_price"] + 0.011) & (sub21["pre_c"] > 0)

    env_rows = []
    csi_map = idx_klines["sh000300"]
    csrc_zt_day_map = {}
    for dt, grp in sub21.groupby("dt_str", sort=True):
        zt_g = grp[grp["is_zt"]]
        csrc_zt_day_map[dt] = zt_g[zt_g["csrc_ind"] != ""].groupby("csrc_ind")["c6"].count().to_dict()
        n_zt = int(len(zt_g))
        n_touch = int(grp["touch_zt"].sum())
        seal_r = n_zt / max(1, n_touch)
        max_b = int(zt_g["streak"].max()) if n_zt > 0 else 0
        top_cnt = int((zt_g["streak"] == max_b).sum()) if max_b > 0 else 0

        fb_today = grp[grp["prev_streak"] == 1]
        fb_buy = fb_today[~fb_today["prev_is_yizi"]]
        promo_1to2 = float(fb_buy["is_zt"].mean()) if len(fb_buy) > 0 else 0.20
        fb_open_avg = float(fb_buy["o_pct"].mean()) if len(fb_buy) > 0 else 0.0
        ho_fb = fb_buy[fb_buy["buyable_open"] & (fb_buy["o_pct"] >= 0.055)]
        ho_zt_r = float(ho_fb["is_zt"].mean()) if len(ho_fb) > 0 else np.nan

        b3_today = grp[grp["prev_streak"] >= 3]
        b3_dt_cnt = int(b3_today["is_dt"].sum())
        b3_brk = b3_today[~b3_today["is_zt"]]
        brk_dt_r = float(b3_brk["is_dt"].mean()) if len(b3_brk) > 0 else np.nan

        c34 = grp[(grp["prev_streak"] == 3) & grp["buyable_open"] & (grp["o_pct"] >= 0.03)]
        nuke_34 = float((c34["pct"] <= -0.05).mean()) if len(c34) > 0 else np.nan
        mkt_yz_open = int((grp["open"] >= grp["zt_price"] - 0.011).sum())

        env_rows.append({
            "dt_str": dt, "n_zt": n_zt, "n_dt": int(grp["is_dt"].sum()), "seal_rate": seal_r,
            "max_board": max_b, "top_cnt": top_cnt, "promo_1to2": promo_1to2,
            "fb_open_avg": fb_open_avg, "ho_zt_r": ho_zt_r, "b3_dt_cnt": b3_dt_cnt,
            "brk_dt_r": brk_dt_r, "nuke_34": nuke_34, "mkt_yizi_cnt": mkt_yz_open,
            "csi300": float(csi_map.get(dt, np.nan))
        })

    env_df = pd.DataFrame(env_rows).sort_values("dt_str").reset_index(drop=True)
    env_df["csi300"] = env_df["csi300"].ffill().bfill()
    env_df["mkt_zt_prev"] = env_df["n_zt"].shift(1).fillna(50)
    env_df["mkt_dt_prev"] = env_df["n_dt"].shift(1).fillna(5)
    env_df["mkt_seal_rate_prev"] = env_df["seal_rate"].shift(1).fillna(0.60)
    env_df["mkt_max_board_prev"] = env_df["max_board"].shift(1).fillna(4).astype(int)
    env_df["mkt_top_cnt_prev"] = env_df["top_cnt"].shift(1).fillna(1).astype(int)
    env_df["mkt_promo_1to2_5d"] = env_df["promo_1to2"].shift(1).rolling(5, min_periods=2).mean().fillna(0.20)
    env_df["roll20_ho_zt"] = env_df["ho_zt_r"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    env_df["prev_3b_dt_cnt"] = env_df["b3_dt_cnt"].shift(1).fillna(0).astype(int)
    env_df["prev_break_dt_rate_10d"] = env_df["brk_dt_r"].shift(1).rolling(10, min_periods=3).mean().fillna(0.20)
    env_df["prev_3to4_nuke_rate_20d"] = env_df["nuke_34"].shift(1).rolling(20, min_periods=3).mean().fillna(0.15)
    env_df["csi300_ret5"] = env_df["csi300"].shift(1) / env_df["csi300"].shift(6) - 1.0
    env_df["csi300_ret20"] = env_df["csi300"].shift(1) / env_df["csi300"].shift(21) - 1.0
    c_max20 = env_df["csi300"].shift(1).rolling(20, min_periods=10).max()
    c_min20 = env_df["csi300"].shift(1).rolling(20, min_periods=10).min()
    env_df["csi300_amp20"] = (c_max20 - c_min20) / (c_min20 + 1e-6)
    env_df.to_parquet(f"{OUT_DIR}/daily_env_5y.parquet", index=False)

    # Save fast forward bar lookup for 2021-11-01..2026-11-11
    sub_bars = sub21[sub21["dt_str"] >= "2021-11-01"][
        ["c6", "dt_str", "open", "high", "low", "close", "adjf", "pre_c", "zt_price", "dt_price", "is_zt", "is_dt", "is_yizi", "is_yizi_dt", "to", "streak", "dt_streak"]
    ].copy()
    code_bars = {}
    for c6, g_c in sub_bars.groupby("c6", sort=False):
        code_bars[c6] = {
            "dts": g_c["dt_str"].values,
            "date_to_pos": {d: idx for idx, d in enumerate(g_c["dt_str"].values)},
            "open": g_c["open"].values.astype(float),
            "high": g_c["high"].values.astype(float),
            "low": g_c["low"].values.astype(float),
            "close": g_c["close"].values.astype(float),
            "adjf": g_c["adjf"].values.astype(float),
            "pre_c": g_c["pre_c"].values.astype(float),
            "zt_px": g_c["zt_price"].values.astype(float),
            "dt_px": g_c["dt_price"].values.astype(float),
            "is_zt": g_c["is_zt"].values.astype(bool),
            "is_dt": g_c["is_dt"].values.astype(bool),
            "is_yizi": g_c["is_yizi"].values.astype(bool),
            "is_yizi_dt": g_c["is_yizi_dt"].values.astype(bool),
            "to": g_c["to"].values.astype(float),
        }
    with open(f"{OUT_DIR}/code_bars_5y.pkl", "wb") as f:
        pickle.dump({"code_bars": code_bars, "idx_klines": idx_klines, "all_dts": [d for d in all_dts if d >= "2021-11-01"]}, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[+] Saved daily_env_5y.parquet & code_bars_5y.pkl ({len(code_bars)} codes) in {time.time()-t0:.1f}s")

    # Save intermediate state for Part 2C feature enrichment
    with open("/tmp/grand_matrix_stage2b.pkl", "wb") as f:
        pickle.dump((sub21, env_df, holders_idx, ind_map, name_map, tape_map, lhasa_map, notice_by_c6, ir_grp, comm_grp, stock_theme_5y, csrc_zt_day_map), f, protocol=pickle.HIGHEST_PROTOCOL)


if __name__ == "__main__":
    main()
