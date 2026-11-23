#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_water_scoring_audit.py
对三进四 V4.1 与高标首阴 V5.1 执行严格的 T-1 市场水温融入打分制实验：
  - 5 个独立因子: F1(zb_rate), F2(max_b_drop5), F3(dt_3d), F4(prem_3d), F_comp(v2_idx)
  - 4 类打分网格: plus_only, minus_only, bidir_sym, bidir_2d (步长 0,2,4,6,8,10,12) + linear k*(score-50)/50
  - 严格 IS (<= 2023-12-31) 挑参，全盲 OOS (2024-01-01 ~ 2026-11-12) 与 2026 验证
  - 完整防过拟合审计: CSCV PBO (S=8/S=10), 左右邻域 +/-2 平滑度, 去Top3/Top5, D15 全指标
"""
import os
import sys
import json
import math
import itertools
import numpy as np
import pandas as pd
import scipy.stats as stats

sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WORK_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

STEPS = [0, 2, 4, 6, 8, 10, 12]
FACTORS = [
    ("F1", "zb_rate_t1", "s_zb_t1", "F1_炸板甜区"),
    ("F2", "max_b_drop5_t1", "s_mb_t1", "F2_高度5日回落"),
    ("F3", "dt_3d_t1", "s_dt_t1", "F3_3日跌停洗盘"),
    ("F4", "prem_3d_t1", "s_p3_t1", "F4_3日溢价洗净"),
    ("F_comp", "v2_idx_t1", "v2_idx_t1", "F_comp_合成水温V2"),
]


def load_csi300() -> tuple[dict, list]:
    raw = json.load(open(IDX_JSON, encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw["sh000300"].items()}
    dts = sorted(sh300.keys())
    return sh300, dts


def get_csi_ret(sh300: dict, all_dts: list, s_dt: str, e_dt: str) -> float:
    dts = [d for d in all_dts if s_dt <= d <= e_dt]
    if not dts:
        return 0.0
    prevs = [d for d in all_dts if d < dts[0]]
    p0 = sh300[prevs[-1]] if prevs else sh300[dts[0]]
    p1 = sh300[dts[-1]]
    return float(p1 / p0 - 1.0)


def compute_zone_masks(df: pd.DataFrame, fid: str) -> tuple[np.ndarray, np.ndarray]:
    if fid == "F1":
        zb = df["zb_rate_t1"].to_numpy(dtype=float)
        sw = (zb >= 25.0) & (zb <= 40.0)
        dg = ~sw
        return sw, dg
    if fid == "F2":
        mb = df["max_b_drop5_t1"].to_numpy(dtype=float)
        return mb >= 2.0, mb <= 0.0
    if fid == "F3":
        d3 = df["dt_3d_t1"].to_numpy(dtype=float)
        return d3 >= 40.0, d3 <= 12.0
    if fid == "F4":
        p3 = df["prem_3d_t1"].to_numpy(dtype=float)
        return p3 <= 1.0, p3 > 3.0
    if fid == "F_comp":
        v2 = df["v2_idx_t1"].to_numpy(dtype=float)
        return v2 >= 65.0, v2 < 45.0
    raise ValueError(fid)


def sim_3to4_slot(df_cand: pd.DataFrame, scores: np.ndarray, thr: float = 90.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = scores >= thr
    sub = df_cand[mask].copy()
    if sub.empty:
        return sub, sub
    sub["new_score"] = scores[mask]
    sub["priority_score"] = sub["new_score"] * 10.0 + sub["prio_tie"] * 0.1
    srt = sub.sort_values(["buy_date", "buy_hhmm", "priority_score", "code"], ascending=[True, True, False, True])
    taken = []
    free_dt, free_hh = "", 0
    for r in srt.itertuples(index=False):
        bd, bh = str(r.buy_date), int(r.buy_hhmm)
        if (not free_dt) or (bd > free_dt) or (bd == free_dt and bh > free_hh):
            taken.append(r._asdict())
            free_dt, free_hh = str(r.exit_date), int(r.exit_hhmm)
    return sub.reset_index(drop=True), pd.DataFrame(taken)


def sim_high_slot(df_cand: pd.DataFrame, scores: np.ndarray, thr: float = 88.0, use_cb: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    mask = scores >= thr
    sub = df_cand[mask].copy()
    if sub.empty:
        return sub, sub
    sub["new_score"] = scores[mask]
    srt = sub.sort_values(["buy_date", "new_score", "code"], ascending=[True, False, True])
    taken = []
    fd, peo, cl, sk = "", False, 0, False
    for r in srt.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
            if use_cb and sk:
                fd, peo = str(r.exit_date), bool(r.eo)
                if float(r.net_ret) > 0.0:
                    sk, cl = False, 0
                continue
            taken.append(r._asdict())
            fd, peo = str(r.exit_date), bool(r.eo)
            if float(r.net_ret) < -0.02:
                cl += 1
                if cl >= 2:
                    sk = True
            elif float(r.net_ret) > 0.0:
                cl = 0
    return sub.reset_index(drop=True), pd.DataFrame(taken)


def calc_window_metrics(raw_df: pd.DataFrame, slot_df: pd.DataFrame, sh300: dict, all_dts: list, s_dt: str, e_dt: str) -> dict:
    csi_r = get_csi_ret(sh300, all_dts, s_dt, e_dt) * 100.0
    sr = raw_df[(raw_df["buy_date"] >= s_dt) & (raw_df["buy_date"] <= e_dt)] if not raw_df.empty else raw_df
    ss = slot_df[(slot_df["buy_date"] >= s_dt) & (slot_df["buy_date"] <= e_dt)] if not slot_df.empty else slot_df
    if ss.empty:
        return {
            "raw_n": int(len(sr)), "n": 0, "wr": 0.0, "plr": 0.0, "mean": 0.0,
            "nav_1s": 1.0, "nav_eq": 1.0, "trim3": 1.0, "trim5": 1.0,
            "mdd": 0.0, "csi_pct": round(csi_r, 2), "excess_1s_pp": round(-csi_r, 2),
            "excess_eq_pp": round(-csi_r, 2), "sr_trade": 0.0,
        }
    rets = ss["net_ret"].to_numpy(dtype=float)
    wins, losses = rets[rets > 0], np.abs(rets[rets <= 0])
    wr = float((rets > 0).mean() * 100.0)
    plr = float(wins.mean() / losses.mean()) if (len(wins) and len(losses) and losses.mean() > 0) else 99.0
    nav_1s = float(np.prod(1.0 + rets))
    pk = cur = 1.0
    mdd = 0.0
    for x in rets:
        cur *= 1.0 + x
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)

    eq_nav = float(np.prod(1.0 + sr.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy())) if not sr.empty else 1.0
    s_ret = np.sort(rets)
    t3 = float(np.prod(1.0 + s_ret[:-3])) if len(s_ret) > 3 else 1.0
    t5 = float(np.prod(1.0 + s_ret[:-5])) if len(s_ret) > 5 else 1.0
    sr_tr = float(rets.mean() / rets.std(ddof=1)) if len(rets) > 1 and rets.std(ddof=1) > 1e-12 else 0.0
    return {
        "raw_n": int(len(sr)),
        "n": int(len(rets)),
        "wr": round(wr, 2),
        "plr": round(plr, 2),
        "mean": round(float(rets.mean() * 100.0), 2),
        "nav_1s": round(nav_1s, 4),
        "nav_eq": round(eq_nav, 4),
        "trim3": round(t3, 4),
        "trim5": round(t5, 4),
        "mdd": round(mdd * 100.0, 2),
        "csi_pct": round(csi_r, 2),
        "excess_1s_pp": round((nav_1s - 1.0) * 100.0 - csi_r, 2),
        "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - csi_r, 2),
        "sr_trade": round(sr_tr, 4),
    }


def calc_hlz_dsr(slot_df: pd.DataFrame, sh300: dict, all_dts: list, m_trials: int = 30) -> tuple[float, float]:
    if slot_df.empty or len(slot_df) < 3:
        return 0.0, 0.0
    def _b(bd, ed):
        prevs = [x for x in all_dts if x < bd]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dts[0]]
        p1s = [x for x in all_dts if x <= ed]
        return float(sh300[p1s[-1]] / p0 - 1.0)
    ex = np.array([float(r.net_ret) - _b(r.buy_date, r.exit_date) for r in slot_df.itertuples()], dtype=float)
    n = len(ex)
    std = float(ex.std(ddof=1))
    if std <= 1e-12:
        return 0.0, 0.0
    sr = float(ex.mean() / std)
    t_val = sr * math.sqrt(n)
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(ex, fisher=False, bias=False))) if n > 3 else 3.0
    gm = 0.5772156649
    sr0 = (1.0 / math.sqrt(max(n - 1, 1))) * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / m_trials) + gm * stats.norm.ppf(1.0 - 1.0 / (m_trials * math.e)))
    den = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2)))
    dsr = float(stats.norm.cdf((sr - sr0) * math.sqrt(max(n - 1, 1)) / den))
    return round(t_val, 2), round(dsr, 4)


def compute_cscv_pbo(daily_mat: np.ndarray, ng: int = 8) -> dict:
    """CSCV PBO over (T_days, N_configs) daily return matrix."""
    t_len, n_cfg = daily_mat.shape
    if n_cfg < 2:
        return {"pbo_pct": 0.0, "mean_rank_oos": 0.5}
    gs = t_len // ng
    gidx = [list(range(i * gs, (i + 1) * gs if i < ng - 1 else t_len)) for i in range(ng)]
    omegas = []
    for te in itertools.combinations(range(ng), ng // 2):
        trg = [k for k in range(ng) if k not in te]
        tri = [x for k in trg for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = daily_mat[tri], daily_mat[tei]
        sd_t, sd_e = rt.std(0, ddof=1), re_.std(0, ddof=1)
        st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
        se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
        b = int(np.argmax(st))
        # Relative rank of IS-best config in OOS (<0.5 means below OOS median -> overfit!)
        # Note: rank_oos = proportion strictly beaten by others -> higher omega (>0.5) means more configs beat it = overfit!
        omegas.append(float(np.mean(se > se[b])))
    return {
        "pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2),
        "mean_rank_oos": round(float(np.mean(omegas)), 4),
    }


def eval_strategy(strat_key: str, df_cand: pd.DataFrame, thr: float, sim_fn, sh300: dict, all_dts: list) -> dict:
    t_days = sorted([d for d in all_dts if "2022-01-04" <= d <= "2026-11-12"])
    day_idx = {d: i for i, d in enumerate(t_days)}

    def build_daily_arr(slot_df: pd.DataFrame) -> np.ndarray:
        arr = np.zeros(len(t_days), dtype=float)
        if not slot_df.empty:
            for r in slot_df.itertuples(index=False):
                i = day_idx.get(str(r.exit_date))
                if i is not None:
                    arr[i] += float(r.net_ret)
        return arr

    def eval_scores(scores: np.ndarray) -> tuple[dict, np.ndarray]:
        raw_df, slot_df = sim_fn(df_cand, scores, thr)
        wins = {
            "IS": calc_window_metrics(raw_df, slot_df, sh300, all_dts, "2021-11-15", "2023-12-31"),
            "OOS": calc_window_metrics(raw_df, slot_df, sh300, all_dts, "2024-01-01", "2026-11-12"),
            "2026": calc_window_metrics(raw_df, slot_df, sh300, all_dts, "2026-01-01", "2026-11-12"),
            "3Y": calc_window_metrics(raw_df, slot_df, sh300, all_dts, "2023-11-16", "2026-11-12"),
            "5Y": calc_window_metrics(raw_df, slot_df, sh300, all_dts, "2021-11-15", "2026-11-12"),
        }
        hlz_all, dsr30 = calc_hlz_dsr(slot_df, sh300, all_dts, m_trials=30)
        _, dsr150 = calc_hlz_dsr(slot_df, sh300, all_dts, m_trials=150)
        wins["hlz_t"] = hlz_all
        wins["dsr_m30"] = dsr30
        wins["dsr_m150"] = dsr150
        return wins, build_daily_arr(slot_df)

    base_sc = df_cand["base_score"].to_numpy(dtype=float)
    base_res, base_daily = eval_scores(base_sc)
    base_is_n = base_res["IS"]["n"]
    min_is_n = max(8, int(math.floor(0.70 * base_is_n)))

    all_global_daily = [base_daily]
    all_global_meta = [{"factor": "BASE", "mode": "base", "param": "0"}]
    factor_results = {}

    for fid, raw_col, sub_col, f_label in FACTORS:
        sw, dg = compute_zone_masks(df_cand, fid)
        sub_s = df_cand[sub_col].to_numpy(dtype=float)

        grid_2d = {}
        daily_2d = []
        # 7 x 7 grid (w_plus, w_minus)
        for wp in STEPS:
            for wm in STEPS:
                delta = np.where(sw, float(wp), np.where(dg, -float(wm), 0.0))
                res, d_arr = eval_scores(base_sc + delta)
                grid_2d[(wp, wm)] = res
                daily_2d.append(d_arr)
                if not (wp == 0 and wm == 0):
                    all_global_daily.append(d_arr)
                    all_global_meta.append({"factor": fid, "mode": "bidir_2d", "param": f"+{wp}/-{wm}"})

        # Linear continuous mapping: k * (score - 50) / 50
        lin_res = {}
        daily_lin = []
        for k in STEPS:
            delta = float(k) * (sub_s - 50.0) / 50.0
            res, d_arr = eval_scores(base_sc + delta)
            lin_res[k] = res
            daily_lin.append(d_arr)
            if k > 0:
                all_global_daily.append(d_arr)
                all_global_meta.append({"factor": fid, "mode": "linear", "param": f"k={k}"})

        # Helper to pick STRICT IS-only optimal parameter (subject to min_is_n activity guard)
        def pick_is_best(cands_dict):
            # cands_dict: {param_key: metrics_dict}
            # Must satisfy IS n >= min_is_n; compare strictly on IS nav_1s
            valid = [(k, v) for k, v in cands_dict.items() if v["IS"]["n"] >= min_is_n]
            if not valid:
                valid = list(cands_dict.items())
            best_k, best_v = max(valid, key=lambda kv: (kv[1]["IS"]["nav_1s"], kv[1]["IS"]["nav_eq"]))
            return best_k, best_v

        modes_summary = {}
        # 1. plus_only: (w, 0)
        plus_dict = {w: grid_2d[(w, 0)] for w in STEPS}
        wp_best, wp_res = pick_is_best(plus_dict)
        modes_summary["plus_only"] = {
            "best_param_is": wp_best,
            "beats_base_is": wp_res["IS"]["nav_1s"] > base_res["IS"]["nav_1s"] + 1e-6,
            "beats_base_oos": wp_res["OOS"]["nav_1s"] > base_res["OOS"]["nav_1s"] + 1e-6,
            "metrics": wp_res,
            "neighbors": {
                "left_m2": plus_dict.get(wp_best - 2),
                "right_p2": plus_dict.get(wp_best + 2),
            },
            "curve": {str(w): {kk: plus_dict[w][kk]["nav_1s"] for kk in ("IS", "OOS", "2026", "5Y")} for w in STEPS},
        }

        # 2. minus_only: (0, w)
        minus_dict = {w: grid_2d[(0, w)] for w in STEPS}
        wm_best, wm_res = pick_is_best(minus_dict)
        modes_summary["minus_only"] = {
            "best_param_is": wm_best,
            "beats_base_is": wm_res["IS"]["nav_1s"] > base_res["IS"]["nav_1s"] + 1e-6,
            "beats_base_oos": wm_res["OOS"]["nav_1s"] > base_res["OOS"]["nav_1s"] + 1e-6,
            "metrics": wm_res,
            "neighbors": {
                "left_m2": minus_dict.get(wm_best - 2),
                "right_p2": minus_dict.get(wm_best + 2),
            },
            "curve": {str(w): {kk: minus_dict[w][kk]["nav_1s"] for kk in ("IS", "OOS", "2026", "5Y")} for w in STEPS},
        }

        # 3. bidir_sym: (w, w)
        sym_dict = {w: grid_2d[(w, w)] for w in STEPS}
        ws_best, ws_res = pick_is_best(sym_dict)
        modes_summary["bidir_sym"] = {
            "best_param_is": ws_best,
            "beats_base_is": ws_res["IS"]["nav_1s"] > base_res["IS"]["nav_1s"] + 1e-6,
            "beats_base_oos": ws_res["OOS"]["nav_1s"] > base_res["OOS"]["nav_1s"] + 1e-6,
            "metrics": ws_res,
            "neighbors": {
                "left_m2": sym_dict.get(ws_best - 2),
                "right_p2": sym_dict.get(ws_best + 2),
            },
            "curve": {str(w): {kk: sym_dict[w][kk]["nav_1s"] for kk in ("IS", "OOS", "2026", "5Y")} for w in STEPS},
        }

        # 4. bidir_2d: all 49 (wp, wm)
        b2d_best, b2d_res = pick_is_best(grid_2d)
        nb_2d = {}
        for dw_p, dw_m, lbl_n in [(-2, 0, "wp_m2"), (2, 0, "wp_p2"), (0, -2, "wm_m2"), (0, 2, "wm_p2")]:
            k_nb = (b2d_best[0] + dw_p, b2d_best[1] + dw_m)
            if k_nb in grid_2d:
                nb_2d[lbl_n] = grid_2d[k_nb]
        modes_summary["bidir_2d"] = {
            "best_param_is": f"+{b2d_best[0]}/-{b2d_best[1]}",
            "beats_base_is": b2d_res["IS"]["nav_1s"] > base_res["IS"]["nav_1s"] + 1e-6,
            "beats_base_oos": b2d_res["OOS"]["nav_1s"] > base_res["OOS"]["nav_1s"] + 1e-6,
            "metrics": b2d_res,
            "neighbors": nb_2d,
        }

        # 5. linear: k*(sub_score - 50)/50
        wl_best, wl_res = pick_is_best(lin_res)
        modes_summary["linear"] = {
            "best_param_is": wl_best,
            "beats_base_is": wl_res["IS"]["nav_1s"] > base_res["IS"]["nav_1s"] + 1e-6,
            "beats_base_oos": wl_res["OOS"]["nav_1s"] > base_res["OOS"]["nav_1s"] + 1e-6,
            "metrics": wl_res,
            "neighbors": {
                "left_m2": lin_res.get(wl_best - 2),
                "right_p2": lin_res.get(wl_best + 2),
            },
            "curve": {str(k): {kk: lin_res[k][kk]["nav_1s"] for kk in ("IS", "OOS", "2026", "5Y")} for k in STEPS},
        }

        # Overall IS-best across ALL modes for this factor
        best_mode_name, best_mode_obj = max(
            [(m, modes_summary[m]) for m in ("plus_only", "minus_only", "bidir_sym", "bidir_2d", "linear")],
            key=lambda kv: (kv[1]["metrics"]["IS"]["nav_1s"], kv[1]["metrics"]["IS"]["nav_eq"]),
        )

        # Neighbor smoothness summary (check +/-2 neighbors around best_mode_obj)
        nb_vals = [v for v in best_mode_obj["neighbors"].values() if v is not None]
        nb_beat_is = sum(1 for v in nb_vals if v["IS"]["nav_1s"] > base_res["IS"]["nav_1s"] + 1e-6)
        nb_beat_oos = sum(1 for v in nb_vals if v["OOS"]["nav_1s"] > base_res["OOS"]["nav_1s"] + 1e-6)

        # Factor-level CSCV PBO (over 49 2D grid + 6 non-zero linear = 55 configs)
        mat_f = np.column_stack(daily_2d + daily_lin[1:])
        pbo_s8 = compute_cscv_pbo(mat_f, 8)
        pbo_s10 = compute_cscv_pbo(mat_f, 10)

        # Grid OOS beat rate (excluding 0/0 baseline)
        non_base_res = [v for (wp, wm), v in grid_2d.items() if not (wp == 0 and wm == 0)] + [lin_res[k] for k in STEPS if k > 0]
        oos_beat_1s_pct = round(float(np.mean([r["OOS"]["nav_1s"] > base_res["OOS"]["nav_1s"] + 1e-6 for r in non_base_res]) * 100.0), 1)
        oos_beat_eq_pct = round(float(np.mean([r["OOS"]["nav_eq"] > base_res["OOS"]["nav_eq"] + 1e-6 for r in non_base_res]) * 100.0), 1)
        is_beat_1s_pct = round(float(np.mean([r["IS"]["nav_1s"] > base_res["IS"]["nav_1s"] + 1e-6 for r in non_base_res]) * 100.0), 1)

        factor_results[fid] = {
            "label": f_label,
            "is_best_overall": {
                "mode": best_mode_name,
                "param": str(best_mode_obj["best_param_is"]),
                "beats_base_is": best_mode_obj["beats_base_is"],
                "beats_base_oos": best_mode_obj["beats_base_oos"],
                "metrics": best_mode_obj["metrics"],
                "neighbors_count": len(nb_vals),
                "neighbors_beat_is": nb_beat_is,
                "neighbors_beat_oos": nb_beat_oos,
            },
            "modes": modes_summary,
            "pbo_s8": pbo_s8,
            "pbo_s10": pbo_s10,
            "grid_is_beat_1s_pct": is_beat_1s_pct,
            "grid_oos_beat_1s_pct": oos_beat_1s_pct,
            "grid_oos_beat_eq_pct": oos_beat_eq_pct,
        }

    # Global PBO across all 5 factors x all variants
    mat_global = np.column_stack(all_global_daily)
    global_pbo_s8 = compute_cscv_pbo(mat_global, 8)
    global_pbo_s10 = compute_cscv_pbo(mat_global, 10)

    return {
        "strategy": strat_key,
        "threshold": thr,
        "pool_size": int(len(df_cand)),
        "pool_is": int((df_cand["buy_date"] <= "2023-12-31").sum()),
        "pool_oos": int((df_cand["buy_date"] >= "2024-01-01").sum()),
        "baseline": base_res,
        "factors": factor_results,
        "global_pbo": {"n_configs": mat_global.shape[1], "S8": global_pbo_s8, "S10": global_pbo_s10},
    }


def main():
    sh300, all_dts = load_csi300()
    p34 = pd.read_csv(f"{WORK_DIR}/pool_3to4_full_clean.csv", dtype={"code": str})
    p34["code"] = p34["code"].str.zfill(6)
    ph = pd.read_csv(f"{WORK_DIR}/pool_high_full_clean.csv", dtype={"code": str})
    ph["code"] = ph["code"].str.zfill(6)

    res_34 = eval_strategy("3to4_V4.1", p34, 90.0, sim_3to4_slot, sh300, all_dts)
    res_h_cb = eval_strategy("High_V5.1_CB", ph, 88.0, lambda d, s, t: sim_high_slot(d, s, t, True), sh300, all_dts)
    res_h_nocb = eval_strategy("High_V5.1_NoCB", ph, 88.0, lambda d, s, t: sim_high_slot(d, s, t, False), sh300, all_dts)

    out = {
        "metadata": {
            "is_window": "2021-11-15 ~ 2023-12-31 (active 5m from 2022-01-04)",
            "oos_window": "2024-01-01 ~ 2026-11-12",
            "window_2026": "2026-01-01 ~ 2026-11-12",
            "steps": STEPS,
            "high_v51_cb_note": "On physically clean returns (000968 deferred to -7.86%), causal CB triggers after 000736(-3.75%)+000968(-7.86%), skipping 2022-05-09 000722(+7.35%): 41 trades/13.74x vs pre-defer frozen 42 trades/14.75x in ledger_base_high_v51.csv.",
        },
        "3to4_V4.1": res_34,
        "High_V5.1_CB": res_h_cb,
        "High_V5.1_NoCB": res_h_nocb,
    }
    out_path = f"{WORK_DIR}/results_part1_3to4_high.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Print crisp console summary
    for key in ("3to4_V4.1", "High_V5.1_CB", "High_V5.1_NoCB"):
        r = out[key]
        b = r["baseline"]
        print(f"\n==================== {key} (pool={r['pool_size']} | IS={r['pool_is']} OOS={r['pool_oos']}) ====================")
        print(f"BASE | IS: n={b['IS']['n']} WR={b['IS']['wr']}% 1S={b['IS']['nav_1s']:.2f}x EQ={b['IS']['nav_eq']:.2f}x MDD={b['IS']['mdd']}% | "
              f"OOS: n={b['OOS']['n']} WR={b['OOS']['wr']}% 1S={b['OOS']['nav_1s']:.2f}x EQ={b['OOS']['nav_eq']:.2f}x T5={b['OOS']['trim5']:.2f}x MDD={b['OOS']['mdd']}% | "
              f"2026: n={b['2026']['n']} 1S={b['2026']['nav_1s']:.2f}x | 5Y: 1S={b['5Y']['nav_1s']:.2f}x T5={b['5Y']['trim5']:.2f}x | GlobalPBO(S8/S10)={r['global_pbo']['S8']['pbo_pct']}%/{r['global_pbo']['S10']['pbo_pct']}%")
        for fid, _, _, _ in FACTORS:
            fd = r["factors"][fid]
            bo = fd["is_best_overall"]
            m = bo["metrics"]
            print(f"  {fid:6s} [{bo['mode']:10s} {bo['param']:7s}] | IS:{m['IS']['nav_1s']:6.2f}x(n={m['IS']['n']},beat={bo['beats_base_is']}) | "
                  f"OOS:{m['OOS']['nav_1s']:7.2f}x(n={m['OOS']['n']},EQ={m['OOS']['nav_eq']:.2f}x,T5={m['OOS']['trim5']:.2f}x,beat={bo['beats_base_oos']}) | "
                  f"2026:{m['2026']['nav_1s']:.2f}x | NB_IS={bo['neighbors_beat_is']}/{bo['neighbors_count']} NB_OOS={bo['neighbors_beat_oos']}/{bo['neighbors_count']} | "
                  f"PBO(S8/10)={fd['pbo_s8']['pbo_pct']}%/{fd['pbo_s10']['pbo_pct']}% | GridOOSBeat={fd['grid_oos_beat_1s_pct']}%")


if __name__ == "__main__":
    main()
