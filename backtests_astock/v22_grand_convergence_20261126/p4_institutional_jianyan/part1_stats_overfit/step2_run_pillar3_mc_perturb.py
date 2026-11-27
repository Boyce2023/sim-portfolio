#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step2_run_pillar3_mc_perturb.py — V22.0 Institutional Audit Part 1 (Pillar 3):
  Full-parameter ±20% Joint Monte Carlo Random Perturbation (Uniform[-20%, +20%]).
  Runs BOTH:
    - Suite A (MC_CORE_12): 12 core V22 parameters perturbed simultaneously (N=500 worlds)
    - Suite B (MC_FULL_38): All 12 core V22 parameters + 26 4to5 scorecard weights & entry gates perturbed simultaneously (N=500 worlds)
  Uses Common Random Numbers across V21_M5_B_NoXQ_Pos5 (Champion) and Pure_V21_P2_SJ114_E4_Pos5 (Pure).
  Every trial runs 100% real end-to-end signal filtering, exit simulation, and causal single-slot execution.
Zero yfinance (D12). Read-only on V20/V21/RD038/RD048/RD049/P1A/P2/P3.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import math
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
P1A = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p1a_3to4_4to5_mutual"
P2 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p2_rd049_falsekill_audit"
P3 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p4_institutional_jianyan/part1_stats_overfit"
CACHE_DIR = f"{OUT_DIR}/_cache"

for p in (RD038, RD049, P1A, P2, P3):
    if p not in sys.path:
        sys.path.insert(0, p)

import _v22_engine as v22
import _p1a_common as cm1a
import _common_rd036 as cm36
import tier_priority_engine as tpe
import step4_mod_rules_and_sim as m1
import run_dirA_4to5_to_3to4 as dirA
import run_dirB_3to4_to_4to5 as dirB

TRD_DAYS_YEAR = 242.0
N_MC = 500
SEED_A = 202611261
SEED_B = 202611262


def fast_2d_states_arrays(reg_df: pd.DataFrame) -> dict:
    """Precompute invariant X_score, Y_score, is_red_floor, dt_cnt_t1 arrays from reg_df."""
    x_ma20 = np.clip((-1.0 - reg_df["gz_vs_ma20_t1"].fillna(0.0).to_numpy(float)) / 5.5, 0.0, 1.0)
    x_dd20 = np.clip((-3.0 - reg_df["gz_dd20_t1"].fillna(0.0).to_numpy(float)) / 8.5, 0.0, 1.0)
    x_r5 = np.clip((-1.5 - reg_df["gz_r5_t1"].fillna(0.0).to_numpy(float)) / 5.5, 0.0, 1.0)
    x_r10 = np.clip((-2.0 - reg_df["gz_r10_t1"].fillna(0.0).to_numpy(float)) / 7.5, 0.0, 1.0)
    x_med5 = np.clip((-1.5 - reg_df["alla_med_r5_t1"].fillna(0.0).to_numpy(float)) / 5.0, 0.0, 1.0)
    xs = (0.25 * x_ma20 + 0.25 * x_dd20 + 0.20 * x_r5 + 0.15 * x_r10 + 0.15 * x_med5) * 100.0

    y_prm = np.clip((0.40 - reg_df["hb2_promo_t1"].fillna(0.40).to_numpy(float)) / 0.22, 0.0, 1.0)
    y_dbm = np.clip((reg_df["L1_duanban_damian_t1"].fillna(15.0).to_numpy(float) - 15.0) / 25.0, 0.0, 1.0)
    y_pb = np.clip((-2.0 - reg_df["pb_hb2_fail_open_t1"].fillna(-2.0).to_numpy(float)) / 4.0, 0.0, 1.0)
    y_zb = np.clip((reg_df["zb_rate_t1"].fillna(30.0).to_numpy(float) - 30.0) / 16.0, 0.0, 1.0)
    y_dt = np.clip((reg_df["dt_cnt_t1"].fillna(5.0).to_numpy(float) - 5.0) / 15.0, 0.0, 1.0)
    ys = (0.20 * y_prm + 0.20 * y_dbm + 0.20 * y_pb + 0.20 * y_zb + 0.20 * y_dt) * 100.0

    reds = ((reg_df["gz_dd20_t1"] <= -13.5) | (reg_df["gz_r10_t1"] <= -11.5) | (reg_df["gz_r5_t1"] <= -8.5)).fillna(False).to_numpy(bool)
    dts = reg_df["trade_date"].astype(str).str[:10].tolist()
    dt_cnt = reg_df["dt_cnt_t1"].to_numpy(float)
    return {"dts": dts, "xs": xs, "ys": ys, "reds": reds, "dt_cnt": dt_cnt, "dt_to_pos": {d: i for i, d in enumerate(dts)}}


def sim_3to4_dirA_custom(entry: dict, assets_dira: dict, dirA_thr: float) -> tuple[str, float, float, int, int, str]:
    """Exact causal 3to4 V4.1 exit with parametric D2 risk7>=1 threshold `dirA_thr`."""
    c6, pos = entry["code"], entry["pos"]
    cb = assets_dira["code_bars_ext"][c6]
    bars_5m = assets_dira["bars_5m_map"]
    k_states = assets_dira["states"].get(entry["idx"], {})
    n = len(cb["dts"])
    k = pos + 1
    imm_used = False
    while k < n:
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue
        dt_s = str(cb["dts"][k])
        ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
        dtk = round(pck * 0.90, 2)
        if k > pos + 1 and bool(cb["is_yizi_dt"][k - 1]):
            return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "yizi_dt_open"
        st = k_states.get(k, {})
        rpts = dirA._risk7_pts(st)
        use_thr = 0.070 if rpts >= 1 else 0.050
        if (k == pos + 1) and rpts >= 1:
            use_thr = float(dirA_thr)
        arr = bars_5m.get((c6, dt_s))
        if arr is not None and len(arr) > 0:
            peak = ok
            for row in arr:
                hh, bo, bh, bl, bc = int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])
                if bh <= dtk + 0.005:
                    continue
                if hh >= 1345 and peak >= pck * 1.085 and bl <= pck * (1.0 + use_thr) and bc < ztk - 0.01:
                    return dt_s, float(min(bo, pck * (1.0 + use_thr))), float(cb["adjf"][k]), k - pos, hh, "c_1345_guard"
                if bh > peak:
                    peak = bh
        if bool(cb["is_zt"][k]):
            k += 1
            continue
        if (not imm_used) and (clk > ok) and (clk >= pck):
            imm_used = True
            k += 1
            continue
        return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500, "d_eod_close"
    k_end = n - 1
    return str(cb["dts"][k_end]), float(cb["close"][k_end]), float(cb["adjf"][k_end]), max(1, k_end - pos), 1500, "end_data"


def build_dirA_map_for_thr(assets_dira: dict, cal_dts: list[str], idx_5y: dict, dirA_thr: float) -> dict:
    """Compute exact DirA override map `(bd, c6) -> (ed, eh, r20, r30, mtm_5y_030)` for continuous `dirA_thr`."""
    dctx = assets_dira["daily_ctx"]
    bar_lu = dctx["bar_lu"]
    code_bars = assets_dira["code_bars_ext"]
    out = {}
    for e in assets_dira["entries"]:
        c6, bd, pos = e["code"], e["buy_date"], e["pos"]
        cb = code_bars[c6]
        ex_dt, spx, adjs, _, shh, _ = sim_3to4_dirA_custom(e, assets_dira, dirA_thr)
        bpx_r = round(float(e["buy_px"]), 2)
        spx_r = round(float(spx), 2)
        nr20 = (float(spx) * float(adjs)) / (float(e["buy_px"]) * float(cb["adjf"][pos])) * (1.0 - 0.0020) - 1.0
        ned, neh, _, nret20_def, dt_def = dirA.defer_dt_local(c6, bd, bpx_r, ex_dt, shh, spx_r, nr20, dctx, 0.0020)
        r20 = float(nret20_def if dt_def else nr20)
        if ned > "2026-11-16":
            continue
        r30 = float(cm1a.convert_fee(r20, 0.0020, 0.0030))
        # Build exact 5Y MTM segs
        bi, ei = idx_5y.get(bd), idx_5y.get(ned)
        if bi is None or ei is None:
            continue
        bb = bar_lu.get((c6, bd))
        b_adj = (bpx_r * bb[2]) if bb is not None else 1.0
        prev_v = b_adj
        segs = []
        for t in range(bi, ei):
            bt = bar_lu.get((c6, cal_dts[t]))
            cur_c = (bt[1] * bt[2]) if (bt is not None and bt[1] > 0) else prev_v
            segs.append((t, cur_c / prev_v))
            prev_v = cur_c
        segs.append((ei, (b_adj * (1.0 + r30)) / prev_v))
        out[(bd, c6)] = (ned, int(neh), r20, r30, tuple(segs))
    return out


def sim_4to5_exit_7f_custom(
    row: dict,
    cb: dict,
    b5m: dict,
    k_states: dict,
    drop_thr_r7: float,
    fee: float = 0.0030,
) -> tuple[str, float, int, float]:
    """Exact 4to5 E_V41_7f_DtDefer exit with continuous `drop_thr_r7` (nominal 0.070)."""
    bd = str(row["buy_date"])[:10]
    bpx = float(row["buy_price_val"])
    c6 = row["code6"]
    pos = cb["dt_idx"][bd]
    n = len(cb["dts"])
    a0 = float(cb["adjf"][pos])

    def _ret(k_i: int, px: float, f_v: float) -> float:
        return (px * float(cb["adjf"][k_i])) / (bpx * a0) * (1.0 - f_v) - 1.0

    if not bool(cb["is_zt"][pos]):
        is_f61 = bool(row.get("f61_eligible", False))
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        if k >= n:
            k = n - 1
            px = float(cb["close"][k])
            return cb["dts"][k], _ret(k, px, fee), 1500, _ret(k, px, 0.0020)
        if is_f61:
            o6, p6, c6_px = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            if (o6 / p6 - 1.0) <= -0.035:
                return cb["dts"][k], _ret(k, o6, fee), 925, _ret(k, o6, 0.0020)
            if bool(cb["is_zt"][k]):
                pos_start = k + 1
            else:
                return cb["dts"][k], _ret(k, c6_px, fee), 1500, _ret(k, c6_px, 0.0020)
        else:
            if k > pos + 1:
                px = float(cb["open"][k])
                return cb["dts"][k], _ret(k, px, fee), 925, _ret(k, px, 0.0020)
            o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
            o5, p5, c5_px = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            if not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)):
                return cb["dts"][k], _ret(k, o5, fee), 925, _ret(k, o5, 0.0020)
            if bool(cb["is_zt"][k]):
                pos_start = k + 1
            else:
                return cb["dts"][k], _ret(k, c5_px, fee), 1500, _ret(k, c5_px, 0.0020)
    else:
        pos_start = pos + 1

    k = pos_start
    imm_used = False
    while k < n:
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue
        dt_s = cb["dts"][k]
        ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
        dtk = round(pck * 0.90, 2)
        if k > pos_start and bool(cb["is_yizi_dt"][k - 1]):
            return dt_s, _ret(k, ok, fee), 925, _ret(k, ok, 0.0020)

        st = k_states.get(k, {})
        rpts = int(st.get("risk7", 0))
        drop_thr = float(drop_thr_r7) if rpts >= 1 else 0.050

        arr = b5m.get((c6, dt_s))
        if arr is not None and len(arr) > 0:
            pk_v = ok
            for row5 in arr:
                hh5, bo5, bh5, bl5, bc5 = int(row5[0]), float(row5[1]), float(row5[2]), float(row5[3]), float(row5[4])
                if bh5 <= dtk + 0.005:
                    continue
                if hh5 >= 1345 and pk_v >= pck * 1.085 and bl5 <= pck * (1.0 + drop_thr) and bc5 < ztk - 0.01:
                    spx_g = float(min(bo5, pck * (1.0 + drop_thr)))
                    return dt_s, _ret(k, spx_g, fee), hh5, _ret(k, spx_g, 0.0020)
                if bh5 > pk_v:
                    pk_v = bh5

        if bool(cb["is_zt"][k]):
            k += 1
            continue
        if (not imm_used) and (clk > ok) and (clk >= pck):
            imm_used = True
            k += 1
            continue
        if clk <= round(pck * 0.90, 2) + 0.005:
            kd = k + 1
            while kd < n - 1 and bool(cb["is_yizi_dt"][kd]):
                kd += 1
            if kd < n:
                return cb["dts"][kd], _ret(kd, float(cb["open"][kd]), fee), 925, _ret(kd, float(cb["open"][kd]), 0.0020)
        return dt_s, _ret(k, clk, fee), 1500, _ret(k, clk, 0.0020)

    k_end = n - 1
    px_end = float(cb["close"][k_end])
    return cb["dts"][k_end], _ret(k_end, px_end, fee), 1500, _ret(k_end, px_end, 0.0020)


class FastV22Evaluator:
    """Zero-overhead exact V22 evaluator for rapid Monte Carlo parameter sweeps."""

    def __init__(self, cache_base: dict, reg_df: pd.DataFrame, mc_assets: dict):
        self.cal_5y = cache_base["cal_5y"]
        self.idx_5y = {d: i for i, d in enumerate(self.cal_5y)}
        self.T = len(self.cal_5y)
        self.wf_off = self.idx_5y[v22.eng.WF_START]
        self.y26_off = self.idx_5y["2026-01-05"]
        self.reg_arr = fast_2d_states_arrays(reg_df)

        # 3to4 precomputed arrays
        df34 = cache_base["pools_ext"]["3to4"].copy()
        self.df34_base = df34
        self.d34_keys = [(str(r.buy_date)[:10], str(r.code).zfill(6)) for r in df34.itertuples(index=False)]
        self.d34_reg_pos = np.array([self.reg_arr["dt_to_pos"].get(str(r.buy_date)[:10], -1) for r in df34.itertuples(index=False)], dtype=int)
        self.d34_base_hyg = df34["can_buy_hygiene"].to_numpy(bool).copy()
        self.d34_sc = df34["orig_score"].to_numpy(float).copy()
        self.d34_af03_ok = (df34["s34_af_03"].to_numpy(float) == 4.0)
        self.d34_pos750 = df34["L3_pos_750d_t1"].to_numpy(float).copy()
        self.d34_m4_mask = cache_base["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"].copy()
        self.d34_r30_base = df34["net_ret_030"].to_numpy(float).copy()
        self.d34_mtm_base = list(df34["mtm_5y_030"])
        self.d34_ed_base = df34["exit_date"].astype(str).to_numpy()
        self.d34_eh_base = df34["exit_hhmm"].to_numpy(int)

        # pry precomputed arrays
        dp = cache_base["pools_ext"]["pry"].copy()
        self.dp_base = dp
        self.dp_reg_pos = np.array([self.reg_arr["dt_to_pos"].get(str(r.buy_date)[:10], -1) for r in dp.itertuples(index=False)], dtype=int)
        self.dp_base_hyg = dp["can_buy_hygiene"].to_numpy(bool).copy()
        self.dp_mkt = dp["mkt10_zt_est_t1"].to_numpy(float).copy()
        self.dp_orig_sc = dp["orig_score"].to_numpy(float).copy()

        # Invariant 4 strategies (20cm, 2to3, high, 1to2) + ut_raw
        inv4 = mc_assets["inv_pool4"].copy()
        inv4["prio"] = inv4["tier"].map(m1.S2C_MAP).fillna(999).astype(float)
        inv4 = inv4[inv4["prio"] < 999].copy()
        is_s_inv = inv4["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
        inv4["phase"] = np.where((inv4["buy_hhmm"] == 925) | is_s_inv, 0, 1)
        self.inv4 = inv4

        ut_raw = cache_base["ut_full_raw"]
        ut_inv_parts = []
        for st_u in ("high", "1to2"):
            sub_u = ut_raw[(ut_raw["strategy"] == st_u) & (~ut_raw["buy_date"].isin(mc_assets["inv_trig_dts"][st_u]))].copy()
            thr_u = {"high": 88.0, "1to2": 0.0}[st_u]
            sub_u = sub_u[sub_u["score"] >= thr_u].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            if not sub_u.empty:
                sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
                ut_inv_parts.append(sub_u)
        self.ut_inv = self._fmt_ut(pd.concat(ut_inv_parts, ignore_index=True))
        self.ut_raw_34 = ut_raw[(ut_raw["strategy"] == "3to4") & (ut_raw["score"] >= 90.0)].copy()

        # 4to5 & DirA assets
        self.assets_4to5 = mc_assets["assets_4to5"]
        self.assets_dira = mc_assets["assets_dira"]

        # Precompute 4to5 numpy arrays for ultra-fast filtering & scoring
        recs = self.assets_4to5["records"]
        self.n45 = len(recs)
        self.f45_hr = np.array([r["hr_pit"] for r in recs], dtype=float)
        self.f45_op = np.array([r["open_pct"] for r in recs], dtype=float)
        self.f45_wmat = np.vstack([r["w_vec"] for r in recs])
        self.f45_has_r7 = np.array([
            any(int(st.get("risk7", 0)) >= 1 for st in self.assets_4to5["hold_states"].get((r["c6"], r["buy_date"]), {}).values())
            for r in recs
        ], dtype=bool)

    def _fmt_ut(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()
        out = df.copy()
        out["is_untrig"] = True
        out["net_ret"] = 0.0
        out["mtm_use"] = [() for _ in range(len(out))]
        out["buy_price_val"] = np.nan
        out["is_adj_px"] = False
        out["prio"] = out["tier"].map(m1.S2C_MAP).fillna(999).astype(float)
        out = out[out["prio"] < 999].copy()
        is_s_cond = out["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
        out["phase"] = np.where((out["buy_hhmm"] == 925) | is_s_cond, 0, 1)
        cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig", "prio", "phase"]
        return out[cols]

    def run_one(self, params: dict, use_dira: bool = True, use_7f_4to5: bool = True) -> dict:
        """Run exact single-slot simulation for given parameter dictionary."""
        # 1. 2D Regime lights
        xs = self.reg_arr["xs"]
        ys = self.reg_arr["ys"]
        reds = self.reg_arr["reds"]
        x_dp, x_sh, y_cut = params["x_dp"], params["x_sh"], params["y_cut"]
        # Ensure x_sh < x_dp even if extreme draws
        if x_sh >= x_dp:
            x_sh = x_dp - 1e-3
        # Codes: 5=L5, 4=L4, 3=L3, 2=L2, 1=L1
        lcode = np.where(reds, 5, np.where(xs >= x_dp, 4, np.where(xs >= x_sh, 3, np.where(ys >= y_cut, 2, 1))))

        # 2. 3to4 P2 + RD049 filter + DirA
        pos34 = self.d34_reg_pos
        lc34 = np.where(pos34 >= 0, lcode[pos34], 1)
        weak34 = (lc34 >= 2) & (lc34 <= 4)
        deltas = np.where(lc34 == 4, params["d_l4"], np.where(lc34 == 3, params["d_l3"], np.where(lc34 == 2, params["d_l2"], 0.0)))
        keep34 = self.d34_base_hyg & (self.d34_sc >= 90.0 + deltas)
        keep34 &= (~weak34) | self.d34_af03_ok
        keep34 |= (self.d34_base_hyg & (self.d34_pos750 < params["pos750"]))

        df34 = self.df34_base.copy()
        df34["can_buy_hygiene"] = keep34
        df34["net_ret"] = self.d34_r30_base.copy()
        df34["mtm_use"] = self.d34_mtm_base

        if use_dira:
            da_map = build_dirA_map_for_thr(self.assets_dira, self.cal_5y, self.idx_5y, params["dirA_thr"])
            ed_arr = df34["exit_date"].astype(str).to_numpy().copy()
            eh_arr = df34["exit_hhmm"].to_numpy(int).copy()
            r_arr = df34["net_ret"].to_numpy(float).copy()
            mtm_list = list(df34["mtm_use"])
            for idx_i, k_pair in enumerate(self.d34_keys):
                ov = da_map.get(k_pair)
                if ov is not None:
                    ned, neh, _, r30, segs = ov
                    if abs(r30 - r_arr[idx_i]) > 1e-6 or ned != ed_arr[idx_i][:10]:
                        ed_arr[idx_i] = ned
                        eh_arr[idx_i] = neh
                        r_arr[idx_i] = r30
                        mtm_list[idx_i] = segs
            df34["exit_date"] = ed_arr
            df34["exit_hhmm"] = eh_arr
            df34["net_ret"] = r_arr
            df34["mtm_use"] = mtm_list

        _, sl34 = cm36.sim_strategy("3to4", df34, self.d34_sc, mask=self.d34_m4_mask, wf_only=False)
        sl34 = sl34[sl34["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        sl34["score"] = sl34["orig_score"].astype(float)
        sl34["tier"] = [tpe.assign_physical_tier("3to4", sc) for sc in sl34["score"]]
        sl34["strategy"] = "3to4"
        sl34["is_untrig"] = False
        if "buy_price_val" not in sl34.columns:
            sl34["buy_price_val"] = pd.to_numeric(sl34.get("buy_price", np.nan), errors="coerce")
        sl34["is_adj_px"] = False
        sl34["prio"] = sl34["tier"].map(m1.S2C_MAP).fillna(999).astype(float)
        sl34 = sl34[sl34["prio"] < 999].copy()
        sl34["phase"] = np.where((sl34["buy_hhmm"] == 925) | sl34["tier"].isin(["3to4_S(>=102)"]), 0, 1)

        # 3. pry P2 filter
        pos_pr = self.dp_reg_pos
        dt_pr = np.where(pos_pr >= 0, self.reg_arr["dt_cnt"][pos_pr], 0.0)
        keep_pr = self.dp_base_hyg & ((self.dp_mkt >= params["pry_mkt"]) | (dt_pr >= params["pry_dt"]))
        dp = self.dp_base.copy()
        dp["can_buy_hygiene"] = keep_pr
        dp["net_ret"] = dp["net_ret_030"]
        dp["mtm_use"] = dp["mtm_5y_030"]
        _, slpr = cm36.sim_strategy("pry", dp, self.dp_orig_sc, wf_only=False)
        slpr = slpr[slpr["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        slpr["score"] = slpr["orig_score"].astype(float)
        slpr["tier"] = [tpe.assign_physical_tier("pry", sc) for sc in slpr["score"]]
        slpr["strategy"] = "pry"
        slpr["is_untrig"] = False
        if "buy_price_val" not in slpr.columns:
            slpr["buy_price_val"] = pd.to_numeric(slpr.get("buy_price", np.nan), errors="coerce")
        slpr["is_adj_px"] = False
        slpr["prio"] = slpr["tier"].map(m1.S2C_MAP).fillna(999).astype(float)
        slpr = slpr[slpr["prio"] < 999].copy()
        slpr["phase"] = np.where(slpr["buy_hhmm"] == 925, 0, 1)

        # 4. 3to4 untriggered waits
        trig_34 = set(sl34["buy_date"])
        u34 = self.ut_raw_34[~self.ut_raw_34["buy_date"].isin(trig_34)]
        if not u34.empty:
            u34 = u34.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            u34["tier"] = [tpe.assign_physical_tier("3to4", sc) for sc in u34["score"]]
            u34_fmt = self._fmt_ut(u34)
        else:
            u34_fmt = pd.DataFrame()

        cols_base = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig", "prio", "phase"]
        base_df = pd.concat([self.inv4[cols_base], sl34[cols_base], slpr[cols_base], self.ut_inv[cols_base], u34_fmt], ignore_index=True)

        # 5. 4to5 filtering, scorecard weights, & 7f/E4 exit
        w_mult = params.get("w_mult")
        if w_mult is None:
            sc_vec = 100.0 + self.f45_wmat.sum(axis=1)
        else:
            sc_vec = 100.0 + self.f45_wmat @ w_mult
        m45 = (
            (self.f45_hr >= params["hr_min"])
            & (self.f45_op >= params["open_lo"])
            & (self.f45_op <= params["open_hi"])
            & (sc_vec >= params["sj_thr"])
        )
        idxs_45 = np.where(m45)[0]
        extra_rows = []
        recs = self.assets_4to5["records"]
        rbars = self.assets_4to5["rich_bars"]
        b5m = self.assets_4to5["b5m"]
        hstates = self.assets_4to5["hold_states"]
        bar_lu = self.assets_4to5["bar_lu"]

        for idx45 in idxs_45:
            rec = recs[idx45]
            c6, bd = rec["c6"], rec["buy_date"]
            if (not use_7f_4to5) or (not self.f45_has_r7[idx45]):
                ed, eh, ret30, segs = rec["e4_exit_date"], rec["e4_exit_hhmm"], rec["e4_ret_030"], rec["e4_mtm_segs"]
            else:
                ed, ret30, eh, _ = sim_4to5_exit_7f_custom(
                    rec["row_dict"], rbars[c6], b5m, hstates.get((c6, bd), {}), params["dirB_7f_thr"], fee=0.0030
                )
                if ed > "2026-11-16":
                    continue
                if ed == rec["e4_exit_date"] and abs(ret30 - rec["e4_ret_030"]) < 1e-10:
                    segs = rec["e4_mtm_segs"]
                else:
                    tmp_df = pd.DataFrame([{"buy_date": bd, "exit_date": ed, "code": c6, "net_ret": float(ret30), "buy_price": rec["buy_price_val"]}])
                    mjson = cm1a.build_mtm_pairs(tmp_df, self.cal_5y, bar_lu, ret_col="net_ret", px_col="buy_price")[0]
                    segs = v22.w2.mtm_json_to_segs(mjson, self.idx_5y, True, float(ret30), float(ret30))
            extra_rows.append({
                "buy_date": bd, "buy_hhmm": 925, "exit_date": ed, "exit_hhmm": int(eh),
                "code": c6, "name": rec["name"], "strategy": "4to5", "tier": "4to5",
                "score": float(sc_vec[idx45]), "net_ret": float(ret30), "mtm_use": segs,
                "buy_price_val": rec["buy_price_val"], "is_adj_px": False, "is_untrig": False,
                "prio": 99.0, "phase": 0,
            })

        # 6. Pos5 empty_fill causal single-slot matching
        srt_b = base_df.sort_values(["buy_date", "phase", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, True, False, True, True], kind="mergesort")
        by_dt_b = {dt: grp for dt, grp in srt_b.groupby("buy_date", sort=False)}
        by_dt_e = {}
        if extra_rows:
            ex_df = pd.DataFrame(extra_rows).sort_values(["buy_date", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, False, True, True], kind="mergesort")
            by_dt_e = {dt: grp for dt, grp in ex_df.groupby("buy_date", sort=False)}

        taken = []
        cur_ed, cur_eh = "", 0
        for dt in self.cal_5y:
            picked = False
            gb = by_dt_b.get(dt)
            if gb is not None:
                for r in gb.itertuples(index=False):
                    if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                        if not r.is_untrig:
                            taken.append(r)
                        cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                        picked = True
                        break
            if picked:
                continue
            ge = by_dt_e.get(dt)
            if ge is not None:
                for r in ge.itertuples(index=False):
                    if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                        taken.append(r)
                        cur_ed, cur_eh = str(r.exit_date), int(r.exit_hhmm)
                        break

        # 7. Exact daily MTM metrics
        day_mult = np.ones(self.T, dtype=float)
        for r in taken:
            segs = r.mtm_use
            if segs:
                for ti, mult in segs:
                    if 0 <= int(ti) < self.T:
                        day_mult[int(ti)] *= float(mult)
            else:
                bi, ei = self.idx_5y.get(r.buy_date), self.idx_5y.get(r.exit_date)
                if bi is not None and ei is not None and ei > bi:
                    span = ei - bi + 1
                    day_mult[bi : ei + 1] *= (1.0 + float(r.net_ret)) ** (1.0 / span)
        dr_5y = day_mult - 1.0
        dr_wf = dr_5y[self.wf_off :]
        dr_26 = dr_5y[self.y26_off :]

        nav_5y = float(np.prod(1.0 + dr_5y))
        nav_wf = float(np.prod(1.0 + dr_wf))
        nav_26 = float(np.prod(1.0 + dr_26))
        mdd_5y, dd2_5y = v22.calc_top2_dd(dr_5y)
        mdd_wf, _ = v22.calc_top2_dd(dr_wf)
        sd_5y = float(np.std(dr_5y, ddof=1))
        sh_5y = float(np.mean(dr_5y) / sd_5y * math.sqrt(TRD_DAYS_YEAR)) if sd_5y > 1e-12 else 0.0
        sd_wf = float(np.std(dr_wf, ddof=1))
        sh_wf = float(np.mean(dr_wf) / sd_wf * math.sqrt(TRD_DAYS_YEAR)) if sd_wf > 1e-12 else 0.0

        return {
            "n_trades": len(taken),
            "n_4to5_trades": sum(1 for r in taken if r.strategy == "4to5"),
            "nav_5y": nav_5y,
            "nav_wf": nav_wf,
            "nav_2026": nav_26,
            "sh_5y": sh_5y,
            "sh_wf": sh_wf,
            "mdd_5y": mdd_5y,
            "dd2_5y": dd2_5y,
            "mdd_wf": mdd_wf,
            "dr_5y": dr_5y,
        }


def summarize_mc_suite(df_mc: pd.DataFrame, model_lbl: str, v21_wf_sh: float, v21_5y_sh: float) -> dict:
    sub = df_mc[df_mc["model"] == model_lbl]
    def _stats(col: str, rnd: int = 4):
        v = sub[col].to_numpy(float)
        return {
            "p05": round(float(np.quantile(v, 0.05)), rnd),
            "p25": round(float(np.quantile(v, 0.25)), rnd),
            "median": round(float(np.median(v)), rnd),
            "p75": round(float(np.quantile(v, 0.75)), rnd),
            "p95": round(float(np.quantile(v, 0.95)), rnd),
            "min": round(float(np.min(v)), rnd),
            "max": round(float(np.max(v)), rnd),
        }

    beat_v21_wf_sh_pct = round(float((sub["sh_wf"] > v21_wf_sh).mean() * 100.0), 2)
    beat_v21_5y_sh_pct = round(float((sub["sh_5y"] > v21_5y_sh).mean() * 100.0), 2)
    mdd_le_32_pct = round(float((sub["mdd_5y"] <= 32.0).mean() * 100.0), 2)
    mdd_le_35_pct = round(float((sub["mdd_5y"] <= 35.0).mean() * 100.0), 2)
    joint_pass_pct = round(float(((sub["sh_wf"] > v21_wf_sh) & (sub["mdd_5y"] <= 35.0)).mean() * 100.0), 2)

    return {
        "n_mc": int(len(sub)),
        "nav_5y": _stats("nav_5y", 2),
        "nav_wf": _stats("nav_wf", 2),
        "sh_wf": _stats("sh_wf", 3),
        "sh_5y": _stats("sh_5y", 3),
        "mdd_5y": _stats("mdd_5y", 2),
        "nav_2026": _stats("nav_2026", 3),
        "n_4to5_trades": _stats("n_4to5_trades", 1),
        "beat_v21_wf_sharpe_pct": beat_v21_wf_sh_pct,
        "beat_v21_5y_sharpe_pct": beat_v21_5y_sh_pct,
        "mdd_5y_le_32_pct": mdd_le_32_pct,
        "mdd_5y_le_35_pct": mdd_le_35_pct,
        "joint_beat_v21_and_mdd_le_35_pct": joint_pass_pct,
        "pass_gate_beat_ge85": bool(beat_v21_wf_sh_pct >= 85.0),
        "pass_gate_mdd35_ge80": bool(mdd_le_35_pct >= 80.0),
    }


def main():
    t0 = time.time()
    print("[Step 2.1] Loading caches & assets...", flush=True)
    with open(f"{CACHE_DIR}/p4_mc_assets.pkl", "rb") as f:
        mc_assets = pickle.load(f)
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache_base = pickle.load(f)
    with open(f"{P3}/_cache/step1_ablation_results.pkl", "rb") as f:
        s1 = pickle.load(f)
    reg_df = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")

    ev = FastV22Evaluator(cache_base, reg_df, mc_assets)

    # 1. Zero-perturbation exact parity checks
    nom_params = {
        "y_cut": 42.0, "x_sh": 20.0, "x_dp": 42.0,
        "d_l2": 9.0, "d_l3": 9.0, "d_l4": 12.0,
        "pos750": 0.50, "pry_mkt": 50.0, "pry_dt": 100.0,
        "sj_thr": 114.0, "dirA_thr": 0.080, "dirB_7f_thr": 0.070,
        "hr_min": 0.12, "open_lo": 0.020, "open_hi": 0.075, "w_mult": None,
    }
    res_ch0 = ev.run_one(nom_params, use_dira=True, use_7f_4to5=True)
    res_pu0 = ev.run_one(nom_params, use_dira=False, use_7f_4to5=False)
    ref_ch = s1["sim_030"]["V21_M5_B_NoXQ_Pos5"]["dr_5y"]
    diff_ch = float(np.max(np.abs(res_ch0["dr_5y"] - ref_ch)))
    assert diff_ch < 1e-10, f"Champion u=0 parity fail: {diff_ch}"
    assert abs(res_pu0["nav_5y"] - 4165511674.4658) < 0.01, f"Pure u=0 parity fail: {res_pu0['nav_5y']}"
    print(f"  Zero-perturbation parity PASS: Champ diff={diff_ch:.2e} (5Y={res_ch0['nav_5y']:.2f}), Pure 5Y={res_pu0['nav_5y']:.2f}", flush=True)

    v21_wf_sh = float(s1["evals"]["B1_V21__030"]["windows"]["WF_2326"]["daily_sharpe"])
    v21_5y_sh = float(s1["evals"]["B1_V21__030"]["windows"]["FULL_5Y"]["daily_sharpe"])

    # 2. Run Suite A (MC_CORE_12, N=500) & Suite B (MC_FULL_38, N=500)
    rows_all = []
    suite_summaries = {}

    for suite_name, n_trials, seed, perturb_weights in [
        ("MC_CORE_12", N_MC, SEED_A, False),
        ("MC_FULL_38", N_MC, SEED_B, True),
    ]:
        ts = time.time()
        rng = np.random.default_rng(seed)
        print(f"[Step 2.2] Running {suite_name} ({n_trials} worlds x 2 models = {n_trials*2} sims)...", flush=True)
        n_factors = len(mc_assets["assets_4to5"]["factor_names"])
        for i in range(n_trials):
            u12 = rng.uniform(-0.20, 0.20, size=12)
            p = {
                "y_cut": 42.0 * (1.0 + u12[0]),
                "x_sh": 20.0 * (1.0 + u12[1]),
                "x_dp": 42.0 * (1.0 + u12[2]),
                "d_l2": 9.0 * (1.0 + u12[3]),
                "d_l3": 9.0 * (1.0 + u12[4]),
                "d_l4": 12.0 * (1.0 + u12[5]),
                "pos750": 0.50 * (1.0 + u12[6]),
                "pry_mkt": 50.0 * (1.0 + u12[7]),
                "pry_dt": 100.0 * (1.0 + u12[8]),
                "sj_thr": 114.0 * (1.0 + u12[9]),
                "dirA_thr": 0.080 * (1.0 + u12[10]),
                "dirB_7f_thr": 0.070 * (1.0 + u12[11]),
            }
            if perturb_weights:
                ug = rng.uniform(-0.20, 0.20, size=3)
                uw = rng.uniform(-0.20, 0.20, size=n_factors)
                p["hr_min"] = 0.12 * (1.0 + ug[0])
                p["open_lo"] = 0.020 * (1.0 + ug[1])
                p["open_hi"] = 0.075 * (1.0 + ug[2])
                p["w_mult"] = 1.0 + uw
            else:
                p["hr_min"] = 0.12
                p["open_lo"] = 0.020
                p["open_hi"] = 0.075
                p["w_mult"] = None

            rc = ev.run_one(p, use_dira=True, use_7f_4to5=True)
            rp = ev.run_one(p, use_dira=False, use_7f_4to5=False)
            for m_lbl, r_obj in [("V22_Champ", rc), ("V22_Pure", rp)]:
                rows_all.append({
                    "suite": suite_name,
                    "trial_id": i,
                    "model": m_lbl,
                    "y_cut": round(p["y_cut"], 3),
                    "x_sh": round(p["x_sh"], 3),
                    "x_dp": round(p["x_dp"], 3),
                    "d_l2": round(p["d_l2"], 3),
                    "d_l3": round(p["d_l3"], 3),
                    "d_l4": round(p["d_l4"], 3),
                    "pos750": round(p["pos750"], 4),
                    "pry_mkt": round(p["pry_mkt"], 3),
                    "pry_dt": round(p["pry_dt"], 3),
                    "sj_thr": round(p["sj_thr"], 3),
                    "dirA_thr": round(p["dirA_thr"], 4),
                    "dirB_7f_thr": round(p["dirB_7f_thr"], 4),
                    "hr_min": round(p["hr_min"], 4),
                    "open_lo": round(p["open_lo"], 4),
                    "open_hi": round(p["open_hi"], 4),
                    "n_trades": r_obj["n_trades"],
                    "n_4to5_trades": r_obj["n_4to5_trades"],
                    "nav_5y": round(r_obj["nav_5y"], 4),
                    "nav_wf": round(r_obj["nav_wf"], 4),
                    "nav_2026": round(r_obj["nav_2026"], 4),
                    "sh_5y": round(r_obj["sh_5y"], 4),
                    "sh_wf": round(r_obj["sh_wf"], 4),
                    "mdd_5y": round(r_obj["mdd_5y"], 2),
                    "dd2_5y": round(r_obj["dd2_5y"], 2),
                    "mdd_wf": round(r_obj["mdd_wf"], 2),
                })

        df_s = pd.DataFrame([r for r in rows_all if r["suite"] == suite_name])
        s_ch = summarize_mc_suite(df_s, "V22_Champ", v21_wf_sh, v21_5y_sh)
        s_pu = summarize_mc_suite(df_s, "V22_Pure", v21_wf_sh, v21_5y_sh)
        # Direct paired comparison Champ vs Pure in same world
        ch_df = df_s[df_s["model"] == "V22_Champ"].sort_values("trial_id").reset_index(drop=True)
        pu_df = df_s[df_s["model"] == "V22_Pure"].sort_values("trial_id").reset_index(drop=True)
        ch_beats_pu_sh_wf = round(float((ch_df["sh_wf"] > pu_df["sh_wf"]).mean() * 100.0), 2)
        ch_beats_pu_nav_wf = round(float((ch_df["nav_wf"] > pu_df["nav_wf"]).mean() * 100.0), 2)

        suite_summaries[suite_name] = {
            "elapsed_sec": round(time.time() - ts, 2),
            "V22_Champ": s_ch,
            "V22_Pure": s_pu,
            "champ_beats_pure_wf_sharpe_pct": ch_beats_pu_sh_wf,
            "champ_beats_pure_wf_nav_pct": ch_beats_pu_nav_wf,
        }
        print(f"  {suite_name} done in {time.time()-ts:.1f}s | Champ beat V21={s_ch['beat_v21_wf_sharpe_pct']}% MDD<=35={s_ch['mdd_5y_le_35_pct']}% | Pure beat V21={s_pu['beat_v21_wf_sharpe_pct']}% MDD<=35={s_pu['mdd_5y_le_35_pct']}%", flush=True)

    df_all = pd.DataFrame(rows_all)
    df_all.to_csv(f"{OUT_DIR}/p4_mc_perturb_samples.csv", index=False, encoding="utf-8-sig")

    mc_audit = v22.sanitize_json({
        "n_mc_per_suite": N_MC,
        "total_sims_executed": int(len(df_all)),
        "v21_ref_wf_sharpe": v21_wf_sh,
        "v21_ref_5y_sharpe": v21_5y_sh,
        "zero_perturb_parity_diff": diff_ch,
        "suites": suite_summaries,
        "elapsed_sec": round(time.time() - t0, 2),
    })
    with open(f"{CACHE_DIR}/p4_pillar3_mc.json", "w", encoding="utf-8") as f:
        json.dump(mc_audit, f, ensure_ascii=False, indent=2)
    print(f"[Step 2 DONE in {time.time()-t0:.1f}s | RSS={v22.rss_mb()} MB]", flush=True)


if __name__ == "__main__":
    main()
