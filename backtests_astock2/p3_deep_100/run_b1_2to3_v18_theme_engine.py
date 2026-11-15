#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_b1_2to3_v18_theme_engine.py
================================================================================
二进三策略首席一进二题材龙王迁移回测器 (B1)
1. 完整迁移《一进二 V18》8年动态题材引擎与三层假题材净化器 (100% 09:25 PIT)
2. 逐个回测全部 38+ 题材与龙头因子在 Traj 1 (右侧点火 touch65_1130 + 13:45 护利 + 真阳免死)
   与 Traj 2 (09:25 竞价直买) 上的全套高颗粒度指标
3. 严格遵守 D12 (零 yfinance)、D15 (单仓时序+按日等权+三期+去Top3+沪深300净超额)、SQLite mode=ro
================================================================================
"""
import os
import sys
import re
import json
import time
import pickle
import sqlite3
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
sys.path.insert(0, f"{SIM_DIR}/backtest/2026-11-11-1to2-clean")
sys.path.insert(0, f"{SIM_DIR}/backtests_astock2")

from clean_wf_1to2_v14_ironclad_master import load_full_prices
from exp1_fake_theme_purifier import build_8y_purified_theme_metadata
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m
from p2_2to3.rd_true5m_2to3_audit import load_all_local_5m
from p3_deep_100.common_eval_harness import eval_factor_slice, CSI_BENCH

OUT_DIR = f"{SIM_DIR}/backtests_astock2/p3_deep_100"
CAND_PATH = f"{SIM_DIR}/backtests_astock2/p2_2to3/cand_2to3_enriched.parquet"
CODE_BARS_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"

FEE = 0.0020
OUT_MASTER_PARQUET = f"{OUT_DIR}/2to3_v18_theme_master.parquet"
OUT_CORE_CSV = f"{OUT_DIR}/b1_2to3_v18_theme_core_factors.csv"
OUT_SUMMARY_JSON = f"{OUT_DIR}/b1_summary.json"


def load_kpl_calendar_and_plates():
    t0 = time.time()
    kpl_days_map = {}
    for pth in [KPL_MERGED_PATH, KPL_5Y_PATH]:
        if os.path.exists(pth):
            for ln in open(pth, encoding="utf-8"):
                if ln.strip():
                    try:
                        d = json.loads(ln)
                        dt = d.get("date", "")
                        if pth == KPL_MERGED_PATH and dt < "2021-01-01":
                            kpl_days_map[dt] = d
                        elif pth == KPL_5Y_PATH and dt >= "2021-01-01":
                            kpl_days_map[dt] = d
                    except Exception:
                        pass
    all_kpl_dts = sorted(kpl_days_map.keys())
    dt_idx = {d: i for i, d in enumerate(all_kpl_dts)}
    plate_day_indices = defaultdict(list)
    plate_stocks_by_dt = defaultdict(lambda: defaultdict(list))
    for dt in all_kpl_dts:
        d = kpl_days_map[dt]
        idx = dt_idx[dt]
        for p in d.get("plates", []):
            pname = p.get("plate", "")
            stocks = p.get("stocks", [])
            if stocks and pname != "其他":
                plate_day_indices[pname].append(idx)
                for s in stocks:
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    plate_stocks_by_dt[dt][pname].append(c6)
    print(f"[*] Loaded KPL days ({len(all_kpl_dts)}) & {len(plate_day_indices)} plates in {time.time()-t0:.2f}s")
    return all_kpl_dts, dt_idx, plate_day_indices, plate_stocks_by_dt


def precompute_stock_streaks(cb_map):
    t0 = time.time()
    streak_map = {}
    for c6, cb in cb_map.items():
        dts = cb["dts"]
        is_zt = cb["is_zt"]
        cur_stk = 0
        for dt, zt in zip(dts, is_zt):
            if zt:
                cur_stk += 1
                streak_map[(dt, c6)] = cur_stk
            else:
                cur_stk = 0
    print(f"[*] Precomputed streak_map ({len(streak_map):,} items) in {time.time()-t0:.2f}s")
    return streak_map


def simulate_trajectories(cands, cb_map, bars_5m):
    t0 = time.time()
    n = len(cands)
    t1_ret, t1_exit, t1_bpx, t1_hb, t1_zt = [np.nan] * n, [""] * n, [np.nan] * n, [0] * n, [False] * n
    t2_ret, t2_exit, t2_bpx, t2_hb, t2_zt = [np.nan] * n, [""] * n, [np.nan] * n, [0] * n, [False] * n

    for i, r in enumerate(cands.itertuples(index=False)):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if not cb:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1:
            continue

        # Traj 1: Right-side ignition touch65_1130
        if (c6, bd) in bars_5m:
            bpx1, bhh1 = sim_buy_5m(c6, bd, cb, pos, bars_5m, "touch65_1130")
        else:
            op, pc, hi, zt = float(cb["open"][pos]), float(cb["pre_c"][pos]), float(cb["high"][pos]), float(cb["zt_px"][pos])
            trig = max(pc * 1.065, op)
            if op < zt - 0.005 and trig < zt - 0.005 and hi >= trig:
                bpx1, bhh1 = max(op, trig), 1000
            else:
                bpx1, bhh1 = None, -1

        if bpx1 is not None:
            ex_dt1, spx1, adjs1, hb1, shh1 = sim_exit_5m(c6, cb, pos, bars_5m, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)
            t1_ret[i] = float((spx1 * adjs1) / (bpx1 * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0)
            t1_exit[i] = ex_dt1
            t1_bpx[i] = bpx1
            t1_hb[i] = hb1
            t1_zt[i] = bool(cb["is_zt"][pos])

        # Traj 2: 09:25 open direct buy
        op, zt = float(cb["open"][pos]), float(cb["zt_px"][pos])
        if op < zt - 0.005 and op > 0:
            ex_dt2, spx2, adjs2, hb2, shh2 = sim_exit_5m(c6, cb, pos, bars_5m, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)
            t2_ret[i] = float((spx2 * adjs2) / (op * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0)
            t2_exit[i] = ex_dt2
            t2_bpx[i] = op
            t2_hb[i] = hb2
            t2_zt[i] = bool(cb["is_zt"][pos])

    cands["traj1_net_ret"] = t1_ret
    cands["traj1_exit_date"] = t1_exit
    cands["traj1_buy_px"] = t1_bpx
    cands["traj1_hold_bars"] = t1_hb
    cands["traj1_is_zt_buy"] = t1_zt

    cands["traj2_net_ret"] = t2_ret
    cands["traj2_exit_date"] = t2_exit
    cands["traj2_buy_px"] = t2_bpx
    cands["traj2_hold_bars"] = t2_hb
    cands["traj2_is_zt_buy"] = t2_zt
    print(f"[*] Simulated Trajectories 1 & 2 for {n} cands in {time.time()-t0:.2f}s")
    return cands


def main():
    print("=" * 80)
    print(">>> [B1: 2-to-3 V18 Theme Engine & Dragon Factor Migrator] Starting...")
    print("=" * 80)

    # 1. Load basic datasets
    df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
    stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)
    all_kpl_dts, dt_idx, plate_day_indices, plate_stocks_by_dt = load_kpl_calendar_and_plates()

    with open(CODE_BARS_PATH, "rb") as f:
        cb_map = pickle.load(f)["code_bars"]
    streak_map = precompute_stock_streaks(cb_map)

    cands = pd.read_parquet(CAND_PATH)
    codes = set(cands["code"].astype(str).str.zfill(6))
    bars_5m = load_all_local_5m(codes)

    # 2. Simulate Trajectory 1 & 2
    cands = simulate_trajectories(cands, cb_map, bars_5m)

    # 3. Mount Theme Metadata on Day 1 (1-board day) and Day 2 (sig_date 2-board day)
    print("[*] Mounting Day 1 & Day 2 purified theme metadata & dragon space factors...")
    d1_plates, d2_plates = [], []
    d1_rk_c, d2_rk_c = [], []
    d1_t_score_c, d2_t_score_c = [], []
    d1_p_sz, d2_p_sz = [], []
    d1_p_elo, d2_p_elo = [], []
    d1_s_elo, d2_s_elo = [], []
    d2_gap_c = []
    d2_has_new = []
    d2_own_new = []
    d2_is_pioneer = []
    d2_spark = []
    d2_sub_cnt = []
    d2_is_gran = []
    d2_is_tech = []
    d2_is_ma = []
    d2_is_earn = []
    d1_is_dying, d2_is_dying = [], []
    d2_s_prior = []

    # Dragon space features
    plate_max_streak_d2 = []
    plate_2b_cnt_d2 = []
    plate_3b_plus_cnt_d2 = []
    is_plate_space_dragon = []
    has_plate_3b_plus_bro = []
    has_plate_4b_plus_bro = []
    is_sole_plate_space_dragon = []
    same_plate_d1_d2 = []
    dying_pulse_no_4b_escort = []
    theme_age_vals = []

    for r in cands.itertuples(index=False):
        c6, bd, sd = str(r.code).zfill(6), str(r.buy_date), str(r.sig_date)
        cb = cb_map.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        d2 = sd
        d1 = cb["dts"][pos - 2] if (cb and pos >= 2) else sd

        t1 = stock_theme_5y.get((d1, c6), {})
        t2 = stock_theme_5y.get((d2, c6), {})

        p1_name = t1.get("plate", str(r.plate) if hasattr(r, "plate") and pd.notna(r.plate) else "其他")
        p2_name = t2.get("plate", str(r.plate) if hasattr(r, "plate") and pd.notna(r.plate) else "其他")
        d1_plates.append(p1_name)
        d2_plates.append(p2_name)

        d1_rk_c.append(t1.get("rk_c", 99))
        d2_rk_c.append(t2.get("rk_c", 99))
        d1_t_score_c.append(t1.get("t_score_c", 95.0))
        d2_t_score_c.append(t2.get("t_score_c", 95.0))
        d1_p_sz.append(t1.get("p_sz", 1))
        d2_p_sz.append(t2.get("p_sz", int(r.p_sz) if hasattr(r, "p_sz") and pd.notna(r.p_sz) else 1))
        d1_p_elo.append(t1.get("p_elo", 100.0))
        d2_p_elo.append(t2.get("p_elo", float(r.p_elo) if hasattr(r, "p_elo") and pd.notna(r.p_elo) else 100.0))
        d1_s_elo.append(t1.get("s_elo", 100.0))
        d2_s_elo.append(t2.get("s_elo", float(r.s_elo) if hasattr(r, "s_elo") and pd.notna(r.s_elo) else 100.0))

        d2_gap_c.append(t2.get("gap_c", 0.0))
        d2_has_new.append(t2.get("has_new", False))
        d2_own_new.append(t2.get("own_new", False))
        d2_spark.append(t2.get("spark", 0.0))
        d2_sub_cnt.append(t2.get("sub_cluster_cnt", int(r.sub_cluster_cnt) if hasattr(r, "sub_cluster_cnt") and pd.notna(r.sub_cluster_cnt) else 1))
        d2_is_tech.append(t2.get("is_tech_c", False))
        d2_is_ma.append(t2.get("is_ma", bool(r.notice_ma) if hasattr(r, "notice_ma") else False))
        d2_is_earn.append(t2.get("is_earn", False))

        d1_is_dying.append(t1.get("is_dying_pulse", False))
        d2_is_dying.append(t2.get("is_dying_pulse", False))

        # Pioneer word check
        r_txt = str(t2.get("r_short", "")) + " " + str(t2.get("name", r.name))
        is_pw = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = m.group(0).strip().upper()
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= d2]
                if 1 <= len(prior) <= 3:
                    is_pw = True
                    break
        d2_is_pioneer.append(is_pw)
        is_gr = is_pw or t2.get("has_new", False) or t2.get("own_new", False) or (t2.get("sub_cluster_cnt", 1) >= 2)
        d2_is_gran.append(is_gr)

        # s_prior_dual
        rk_val, psz_val = t2.get("rk_c", 99), t2.get("p_sz", 1)
        sp = (
            (28 if rk_val == 1 else (16 if rk_val == 2 else (8 if rk_val == 3 else 0)))
            + (18 if psz_val >= 4 else (10 if psz_val >= 2 else -15))
            + (12 if t2.get("has_new", False) else 0)
            + (8 if t2.get("own_new", False) else 0)
            + (10 if t2.get("spark", 0.0) > 0 else 0)
            + (18 if getattr(r, "notice_hard", False) else 0)
            + (18 if (t2.get("is_ma", False) or getattr(r, "notice_ma", False)) else 0)
            + (12 if t2.get("is_tech_c", False) else 0)
            + (12 if t2.get("gap_c", 0.0) >= 20.0 else 0)
            + float(np.clip((t2.get("t_score_c", 95.0) - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((t2.get("s_elo", 100.0) - 100.0) * 0.35, -10.0, 18.0))
        )
        d2_s_prior.append(round(sp, 2))

        # Dragon space height
        stks = plate_stocks_by_dt[d2].get(p2_name, [c6])
        streaks = [streak_map.get((d2, c), 1) for c in stks]
        if not streaks:
            streaks = [2]
        max_s = max(streaks)
        cnt_2b = sum(1 for s in streaks if s == 2)
        cnt_3b_p = sum(1 for s in streaks if s >= 3)

        plate_max_streak_d2.append(max_s)
        plate_2b_cnt_d2.append(cnt_2b)
        plate_3b_plus_cnt_d2.append(cnt_3b_p)
        is_plate_space_dragon.append(max_s == 2)
        has_plate_3b_plus_bro.append(max_s >= 3)
        has_plate_4b_plus_bro.append(max_s >= 4)
        is_sole_plate_space_dragon.append(bool(max_s == 2 and cnt_2b == 1 and getattr(r, "is_plate_top1_2b", False)))
        same_plate_d1_d2.append(bool(p1_name == p2_name and p1_name not in ("其他", "")))
        dying_pulse_no_4b_escort.append(bool(t1.get("is_dying_pulse", False) and max_s < 4))

        # Theme cycle age in past 8 trading days
        if p2_name in plate_day_indices and d2 in dt_idx:
            c_i = dt_idx[d2]
            past = [idx for idx in plate_day_indices[p2_name] if c_i - 8 <= idx <= c_i]
            age = (c_i - past[0] + 1) if past else 1
        else:
            age = 1
        theme_age_vals.append(age)

    cands["d1_plate"] = d1_plates
    cands["d2_plate"] = d2_plates
    cands["d1_rk_c"] = d1_rk_c
    cands["d2_rk_c"] = d2_rk_c
    cands["d1_t_score_c"] = d1_t_score_c
    cands["d2_t_score_c"] = d2_t_score_c
    cands["d1_p_sz"] = d1_p_sz
    cands["d2_p_sz"] = d2_p_sz
    cands["d1_p_elo"] = d1_p_elo
    cands["d2_p_elo"] = d2_p_elo
    cands["d1_s_elo"] = d1_s_elo
    cands["d2_s_elo"] = d2_s_elo
    cands["d2_gap_c"] = d2_gap_c
    cands["d2_has_new_term"] = d2_has_new
    cands["d2_own_new_term"] = d2_own_new
    cands["d2_is_pioneer_word"] = d2_is_pioneer
    cands["d2_spark_bonus"] = d2_spark
    cands["d2_sub_cluster_cnt"] = d2_sub_cnt
    cands["d2_is_granularity"] = d2_is_gran
    cands["d2_is_tech_c"] = d2_is_tech
    cands["d2_is_ma"] = d2_is_ma
    cands["d2_is_earn"] = d2_is_earn
    cands["d1_is_dying_pulse"] = d1_is_dying
    cands["d2_is_dying_pulse"] = d2_is_dying
    cands["d2_s_prior_dual"] = d2_s_prior

    cands["plate_max_streak_d2"] = plate_max_streak_d2
    cands["plate_2b_cnt_d2"] = plate_2b_cnt_d2
    cands["plate_3b_plus_cnt_d2"] = plate_3b_plus_cnt_d2
    cands["is_plate_space_dragon"] = is_plate_space_dragon
    cands["has_plate_3b_plus_bro"] = has_plate_3b_plus_bro
    cands["has_plate_4b_plus_bro"] = has_plate_4b_plus_bro
    cands["is_sole_plate_space_dragon"] = is_sole_plate_space_dragon
    cands["same_plate_d1_d2"] = same_plate_d1_d2
    cands["dying_pulse_no_4b_escort"] = dying_pulse_no_4b_escort
    cands["theme_age"] = theme_age_vals
    cands["theme_age_1_2d"] = [a in (1, 2) for a in theme_age_vals]
    cands["theme_age_3_4d"] = [a in (3, 4) for a in theme_age_vals]
    cands["theme_age_5_8d"] = [a in (5, 6, 7, 8) for a in theme_age_vals]

    # Cross-theme rules (Rule Alpha, Beta, V18 Rule 3, Gamma, M_T2)
    cands["Rule_alpha_blocked"] = cands["is_dominant_day"] & (cands["rk_theme"] >= 3)
    cands["Rule_beta_blocked"] = cands["is_melee_day"] & (~(cands["mkt_open_rk"].between(1, 2) | cands["notice_hard"] | cands["d2_is_ma"]))
    # One-super two-weak day
    valid_pg = cands[(cands["plate"] != "其他") & (~cands["is_event_basket"])].groupby(["buy_date", "plate"], as_index=False).agg(sp_med=("d2_s_prior_dual", "median"), p_sz_max=("d2_p_sz", "max"))
    valid_pg = valid_pg[valid_pg["p_sz_max"] >= 2].copy()
    valid_pg["rk"] = valid_pg.groupby("buy_date")["sp_med"].rank(ascending=False, method="min")
    d_t1 = valid_pg[valid_pg["rk"] == 1].sort_values(["buy_date", "sp_med"], ascending=[True, False]).drop_duplicates("buy_date").set_index("buy_date")["sp_med"].to_dict()
    d_t3 = valid_pg[valid_pg["rk"] == 3].sort_values(["buy_date", "sp_med"], ascending=[True, False]).drop_duplicates("buy_date").set_index("buy_date")["sp_med"].to_dict()
    t1_s = cands["buy_date"].map(d_t1).fillna(0.0)
    t3_s = cands["buy_date"].map(d_t3).fillna(0.0)
    is_ostw = (t1_s >= 65.0) & (t1_s - t3_s >= 35.0) & (t3_s < 42.0)
    cands["is_one_super_two_weak"] = is_ostw
    cands["V18_Rule_3_penalized"] = is_ostw & (cands["rk_theme"] >= 3)
    cands["Rule_gamma_cold"] = cands["roll20_ho_zt"] < 0.40
    cands["m_t2_channel"] = (cands["d2_p_sz"] == 1) & (cands["d2_is_pioneer_word"] | cands["notice_hard"] | cands["d2_is_ma"] | cands["d2_has_new_term"] | cands["d2_own_new_term"]) & (cands["mkt_open_rk"] <= 3)

    # Save enriched master table
    cands.to_parquet(OUT_MASTER_PARQUET, index=False)
    print(f"[+] Master parquet saved: {cands.shape} -> {OUT_MASTER_PARQUET}")

    # 4. Construct complete list of 38+ factors
    factors = [
        # --- Group 1: 龙头身位纯度 ---
        ("G1_01_is_plate_space_dragon", cands["is_plate_space_dragon"]),
        ("G1_02_has_plate_3b_plus_bro", cands["has_plate_3b_plus_bro"]),
        ("G1_03_has_plate_4b_plus_bro", cands["has_plate_4b_plus_bro"]),
        ("G1_04_is_sole_plate_space_dragon", cands["is_sole_plate_space_dragon"]),
        ("G1_05_is_mkt_highest_2b", cands["is_mkt_highest_2b"]),
        # --- Group 2: V18 原子题材因子拆解 (Day 2) ---
        ("G2_06_d2_rk_c_eq1", cands["d2_rk_c"] == 1),
        ("G2_07_d2_rk_c_eq2", cands["d2_rk_c"] == 2),
        ("G2_08_d2_rk_c_eq3", cands["d2_rk_c"] == 3),
        ("G2_09_d2_rk_c_ge4_cold", cands["d2_rk_c"] >= 4),
        ("G2_10_d2_gap_c_ge20", cands["d2_gap_c"] >= 20.0),
        ("G2_11_d2_p_sz_eq1_lone", cands["d2_p_sz"] == 1),
        ("G2_12_d2_p_sz_2_to_3", cands["d2_p_sz"].between(2, 3)),
        ("G2_13_d2_p_sz_4_to_7", cands["d2_p_sz"].between(4, 7)),
        ("G2_14_d2_p_sz_8_to_15_wave", cands["d2_p_sz"].between(8, 15)),
        ("G2_15_d2_p_sz_gt15", cands["d2_p_sz"] > 15),
        ("G2_16_d2_p_sz_gt35_chaotic", cands["d2_p_sz"] > 35),
        ("G2_17_d2_p_elo_ge105", cands["d2_p_elo"] >= 105.0),
        ("G2_18_d2_p_elo_ge110", cands["d2_p_elo"] >= 110.0),
        ("G2_19_d2_p_elo_ge115", cands["d2_p_elo"] >= 115.0),
        ("G2_20_d2_p_elo_le95_weak", cands["d2_p_elo"] <= 95.0),
        ("G2_21_d2_s_elo_ge105", cands["d2_s_elo"] >= 105.0),
        ("G2_22_d2_s_elo_le95_weak", cands["d2_s_elo"] <= 95.0),
        ("G2_23_d2_has_new_term", cands["d2_has_new_term"]),
        ("G2_24_d2_own_new_term", cands["d2_own_new_term"]),
        ("G2_25_d2_is_pioneer_word", cands["d2_is_pioneer_word"]),
        ("G2_26_d2_spark_bonus", cands["d2_spark_bonus"] > 0),
        ("G2_27_d2_sub_cluster_ge2", cands["d2_sub_cluster_cnt"] >= 2),
        ("G2_28_d2_is_granularity", cands["d2_is_granularity"]),
        ("G2_29_d2_is_tech_c", cands["d2_is_tech_c"]),
        ("G2_30_d2_is_ma", cands["d2_is_ma"]),
        ("G2_31_d2_is_earn", cands["d2_is_earn"]),
        ("G2_32_notice_hard", cands["notice_hard"]),
        ("G2_33_notice_ma", cands["notice_ma"]),
        ("G2_34_notice_bad", cands["notice_bad"]),
        ("G2_35_has_ir_8d", cands["has_ir_8d"]),
        ("G2_36_same_plate_d1_d2", cands["same_plate_d1_d2"]),
        ("G2_37_diff_plate_d1_d2_switch", ~cands["same_plate_d1_d2"]),
        # --- Group 3: 三层假题材净化器全因子 ---
        ("G3_38_is_event_basket", cands["is_event_basket"]),
        ("G3_39_is_broad_ind", cands["is_broad_ind"]),
        ("G3_40_is_pure_outsider", cands["is_pure_outsider"]),
        ("G3_41_is_dying_pulse_d1", cands["d1_is_dying_pulse"]),
        ("G3_42_is_dying_pulse_d2", cands["d2_is_dying_pulse"]),
        ("G3_43_dying_pulse_no_4b_escort", cands["dying_pulse_no_4b_escort"]),
        ("G3_44_theme_age_1_2d_start", cands["theme_age_1_2d"]),
        ("G3_45_theme_age_3_4d_mid", cands["theme_age_3_4d"]),
        ("G3_46_theme_age_5_8d_exhaust", cands["theme_age_5_8d"]),
        # --- Group 4: 四大跨题材全局规则 ---
        ("G4_47_rk_theme_le2_main", cands["rk_theme"] <= 2),
        ("G4_48_rk_theme_ge4_cold", cands["rk_theme"] >= 4),
        ("G4_49_Rule_alpha_blocked", cands["Rule_alpha_blocked"]),
        ("G4_50_Rule_beta_blocked", cands["Rule_beta_blocked"]),
        ("G4_51_V18_Rule_3_penalized", cands["V18_Rule_3_penalized"]),
        ("G4_52_Rule_gamma_cold", cands["Rule_gamma_cold"]),
        ("G4_53_m_t2_channel", cands["m_t2_channel"]),
    ]

    # Baseline skeleton: non-yizi, is_plate_top1_2b, 2% <= open_pct <= 7.8%
    base_mask = (~cands["prev_is_yizi"]) & cands["is_plate_top1_2b"] & cands["open_pct"].between(0.02, 0.078)
    base_df = cands[base_mask].copy()

    # Pre-evaluate base benchmarks
    base_t1_m = float(base_df["traj1_net_ret"].dropna().mean()) if len(base_df["traj1_net_ret"].dropna()) else 0.0
    base_t2_m = float(base_df["traj2_net_ret"].dropna().mean()) if len(base_df["traj2_net_ret"].dropna()) else 0.0

    raw_t1_m = float(cands["traj1_net_ret"].dropna().mean()) if len(cands["traj1_net_ret"].dropna()) else 0.0
    raw_t2_m = float(cands["traj2_net_ret"].dropna().mean()) if len(cands["traj2_net_ret"].dropna()) else 0.0

    print(f"[*] Base skeleton size: {len(base_df)}, Traj1 avg: {base_t1_m*100:+.2f}%, Traj2 avg: {base_t2_m*100:+.2f}%")
    print(f"[*] Raw pool size: {len(cands)}, Traj1 avg: {raw_t1_m*100:+.2f}%, Traj2 avg: {raw_t2_m*100:+.2f}%")

    # Evaluate all factors across 4 dimensions
    records = []
    summary_dict = {
        "meta": {
            "strategy": "2to3",
            "eval_date": "2026-11-14",
            "total_candidates": len(cands),
            "skeleton_candidates": len(base_df),
            "base_t1_mean_pct": round(base_t1_m * 100, 2),
            "base_t2_mean_pct": round(base_t2_m * 100, 2),
            "csi300_5y_pct": round(CSI_BENCH["5y"] * 100, 2),
        },
        "factors": {},
    }

    print("\n" + "=" * 115)
    print(f"{'Factor Name':<34} | {'T1 Raw Avg':<10} {'T1 Skel Del':<11} {'T1 DualOk':<9} {'T1 SS-NAV':<9} | {'T2 Raw Avg':<10} {'T2 Skel Del':<11} {'T2 DualOk':<9} {'T2 SS-NAV':<9}")
    print("=" * 115)

    for fname, mask in factors:
        # 1. Traj 1 Raw
        res_t1_raw = eval_factor_slice(cands[mask], ret_col="traj1_net_ret", exit_col="traj1_exit_date", rank_col="open_pct", base_mean=raw_t1_m)
        # 2. Traj 1 on Skeleton
        res_t1_skel = eval_factor_slice(cands[base_mask & mask], ret_col="traj1_net_ret", exit_col="traj1_exit_date", rank_col="open_pct", base_mean=base_t1_m)
        # 3. Traj 2 Raw
        res_t2_raw = eval_factor_slice(cands[mask], ret_col="traj2_net_ret", exit_col="traj2_exit_date", rank_col="open_pct", base_mean=raw_t2_m)
        # 4. Traj 2 on Skeleton
        res_t2_skel = eval_factor_slice(cands[base_mask & mask], ret_col="traj2_net_ret", exit_col="traj2_exit_date", rank_col="open_pct", base_mean=base_t2_m)

        row = {
            "factor": fname,
            "t1_raw_n": res_t1_raw["n_raw"],
            "t1_raw_wr": res_t1_raw["wr_raw"],
            "t1_raw_avg": res_t1_raw["avg_ret"],
            "t1_raw_po": res_t1_raw["payoff_raw"],
            "t1_raw_dual_ok": res_t1_raw["dual_same_sign"],
            "t1_skel_n": res_t1_skel["n_raw"],
            "t1_skel_wr": res_t1_skel["wr_raw"],
            "t1_skel_avg": res_t1_skel["avg_ret"],
            "t1_skel_delta": res_t1_skel["delta_vs_base"],
            "t1_skel_po": res_t1_skel["payoff_raw"],
            "t1_skel_dual_ok": res_t1_skel["dual_same_sign"],
            "t1_skel_ss_nav": res_t1_skel["ss_nav"],
            "t1_skel_ss_ex_top3": res_t1_skel["ss_ex_top3_nav"],
            "t1_skel_ss_excess": res_t1_skel["ss_net_excess_5y"],
            "t1_skel_pos_years": res_t1_skel["pos_years_vs_base"],
            "t2_raw_n": res_t2_raw["n_raw"],
            "t2_raw_wr": res_t2_raw["wr_raw"],
            "t2_raw_avg": res_t2_raw["avg_ret"],
            "t2_raw_po": res_t2_raw["payoff_raw"],
            "t2_raw_dual_ok": res_t2_raw["dual_same_sign"],
            "t2_skel_n": res_t2_skel["n_raw"],
            "t2_skel_wr": res_t2_skel["wr_raw"],
            "t2_skel_avg": res_t2_skel["avg_ret"],
            "t2_skel_delta": res_t2_skel["delta_vs_base"],
            "t2_skel_po": res_t2_skel["payoff_raw"],
            "t2_skel_dual_ok": res_t2_skel["dual_same_sign"],
            "t2_skel_ss_nav": res_t2_skel["ss_nav"],
            "t2_skel_ss_ex_top3": res_t2_skel["ss_ex_top3_nav"],
            "t2_skel_ss_excess": res_t2_skel["ss_net_excess_5y"],
            "t2_skel_pos_years": res_t2_skel["pos_years_vs_base"],
        }
        records.append(row)
        summary_dict["factors"][fname] = {
            "traj1_raw": res_t1_raw,
            "traj1_skel": res_t1_skel,
            "traj2_raw": res_t2_raw,
            "traj2_skel": res_t2_skel,
        }

        t1_raw_s = f"{res_t1_raw['avg_ret']:+.2f}%"
        t1_skel_s = f"{res_t1_skel['delta_vs_base']:+.2f}%"
        t1_dual_s = "YES" if res_t1_skel["dual_same_sign"] else "NO"
        t1_nav_s = f"{res_t1_skel['ss_nav']:.2f}"

        t2_raw_s = f"{res_t2_raw['avg_ret']:+.2f}%"
        t2_skel_s = f"{res_t2_skel['delta_vs_base']:+.2f}%"
        t2_dual_s = "YES" if res_t2_skel["dual_same_sign"] else "NO"
        t2_nav_s = f"{res_t2_skel['ss_nav']:.2f}"

        print(f"{fname:<34} | {t1_raw_s:<10} {t1_skel_s:<11} {t1_dual_s:<9} {t1_nav_s:<9} | {t2_raw_s:<10} {t2_skel_s:<11} {t2_dual_s:<9} {t2_nav_s:<9}")

    df_res = pd.DataFrame(records)
    df_res.to_csv(OUT_CORE_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[+] Factor CSV saved: {len(df_res)} rows -> {OUT_CORE_CSV}")

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, indent=2, ensure_ascii=False)
    print(f"[+] Summary JSON saved -> {OUT_SUMMARY_JSON}")
    print("=" * 80)
    print(">>> [B1: 2-to-3 V18 Theme Engine & Dragon Factor Migrator] Completed Successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
