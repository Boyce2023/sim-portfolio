#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part 2D: Generate all 5 strategy PIT candidate Parquet tables (2022-01-04..2026-11-10)."""
import os, sys, time, pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from part2b_build_env_and_bars import OUT_DIR
from part2c_enrich_helper import enrich_candidates


def main():
    t0 = time.time()
    with open("/tmp/grand_matrix_stage2b.pkl", "rb") as f:
        sub21, env_df, holders_idx, ind_map, name_map, tape_map, lhasa_map, notice_by_c6, ir_grp, comm_grp, stock_theme_5y, csrc_zt_day_map = pickle.load(f)

    # Compute lagged signal-day features strictly on T-1
    sub21.sort_values(["c6", "dt_str"], inplace=True)
    g = sub21.groupby("c6")
    sub21["sig_date"] = g["dt_str"].shift(1)
    sub21["buy_date"] = sub21["dt_str"]
    sub21["gap_days"] = (pd.to_datetime(sub21["buy_date"]) - pd.to_datetime(sub21["sig_date"])).dt.days.fillna(1).astype(int)
    sub21["prev_mcap"] = g["mcap"].shift(1)
    sub21["prev_to"] = g["to"].shift(1)
    sub21["prev_amt"] = g["amount"].shift(1).fillna(0.0)
    sub21["prev_vr"] = (g["amount"].shift(1) / (g["vol_ma5"].shift(1) + 1e-6)).fillna(1.5)
    sub21["prev_dd20"] = (g["close"].shift(1) / (g["max20"].shift(1) + 1e-6)).fillna(0.90)
    sub21["prev_dd60"] = (g["close"].shift(1) / (g["max60"].shift(1) + 1e-6)).fillna(0.85)
    sub21["prev_pos20"] = ((g["close"].shift(1) - g["min20"].shift(1)) / (g["max20"].shift(1) - g["min20"].shift(1) + 1e-6)).fillna(0.50)
    sub21["prev_brk60"] = (g["close"].shift(1) >= g["max60"].shift(2) - 0.01).fillna(False)
    sub21["prev_ret10"] = g["ret10"].shift(1).fillna(0.0)
    sub21["prev_zt20"] = g["zt_cnt20"].shift(1).fillna(0).astype(int)
    sub21["prev_mb_gap"] = g["prior_mb_gap"].shift(1).fillna(9999).astype(int)
    sub21["prev_tight"] = g["seal_tightness"].shift(1).fillna(20.0)

    w5y = sub21[(sub21["buy_date"] >= "2022-01-04") & (sub21["buy_date"] <= "2026-11-10") & sub21["sig_date"].notna()].copy()
    env_map = env_df.set_index("dt_str").to_dict(orient="index")

    # Daily theme dominance & melee flags on sig_date, plus plate open peers on buy_date
    theme_by_day = {}
    for (dt_s, _c), ti in stock_theme_5y.items():
        p = ti["plate"]
        if p != "其他" and (not ti["is_event_basket"]) and ti["p_sz"] >= 2:
            cur = theme_by_day.setdefault(dt_s, {})
            if p not in cur or ti["t_score_c"] > cur[p][0]:
                cur[p] = (ti["t_score_c"], ti["p_sz"])
    theme_day_meta = {}
    for dt_s, pm in theme_by_day.items():
        srt = sorted(pm.values(), key=lambda x: x[0], reverse=True)
        t1 = srt[0] if len(srt) >= 1 else (100.0, 1)
        t2 = srt[1] if len(srt) >= 2 else (95.0, 1)
        t3 = srt[2] if len(srt) >= 3 else (90.0, 1)
        gap12 = t1[0] - t2[0]
        is_dom = (gap12 >= 20.0) or (t1[1] >= 6 and t1[1] >= 2 * max(1, t2[1]))
        is_melee = (len(srt) >= 3) and ((t1[0] - t3[0]) <= 15.0) and all(2 <= x[1] <= 5 for x in srt[:3])
        theme_day_meta[dt_s] = (round(gap12, 2), bool(is_dom), bool(is_melee))

    # Plate peers open avg & plate yizi open count on buy_date (computed on T-1 ZT stocks opening on T)
    zt_prev_rows = w5y[w5y["prev_streak"] >= 1][["c6", "sig_date", "buy_date", "o_pct", "open", "zt_price"]].copy()
    zt_prev_rows["plate"] = [stock_theme_5y.get((s, c), {}).get("plate", "其他") for s, c in zip(zt_prev_rows["sig_date"], zt_prev_rows["c6"])]
    zt_prev_rows["yz_o"] = (zt_prev_rows["open"] >= zt_prev_rows["zt_price"] - 0.011).astype(int)
    p_grp = zt_prev_rows[zt_prev_rows["plate"] != "其他"].groupby(["buy_date", "plate"], as_index=False).agg(o_avg=("o_pct", "mean"), yz_cnt=("yz_o", "sum"))
    plate_open_peers_map = {(r.buy_date, r.plate): (round(float(r.o_avg), 4), int(r.yz_cnt)) for r in p_grp.itertuples(index=False)}

    common_args = (env_map, holders_idx, name_map, tape_map, lhasa_map, notice_by_c6, ir_grp, comm_grp, stock_theme_5y, csrc_zt_day_map, theme_day_meta, plate_open_peers_map)

    specs = [
        ("cand_high_dragon.parquet", w5y[w5y["prev_streak"] >= 3]),
        ("cand_3to4.parquet", w5y[w5y["prev_streak"] == 3]),
        ("cand_2to3.parquet", w5y[w5y["prev_streak"] == 2]),
        ("cand_pry_limitdown.parquet", w5y[(w5y["prev_dt_streak"] >= 2) | ((w5y["prev_dt_streak"] >= 1) & w5y["touch_dt"])]),
        ("cand_0to1_firstboard.parquet", w5y[(w5y["prev_streak"] == 0) & (w5y["open"] < w5y["zt_price"] - 0.011) & (w5y["touch_zt"] | (w5y["h_pct"] >= 0.065))]),
    ]
    for fname, sub_c in specs:
        t1 = time.time()
        out_df = enrich_candidates(sub_c, *common_args)
        out_df.to_parquet(f"{OUT_DIR}/{fname}", index=False)
        print(f"[+] {fname}: {len(out_df):,} rows saved in {time.time()-t1:.1f}s")

    print(f"[DONE] All 5 strategy PIT candidate tables ready in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
