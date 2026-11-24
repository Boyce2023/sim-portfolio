#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 4: Full Industrial Red-Team Audit & Physical Truncation Zero-Lookahead Verification.
  1. Yearly breakdown (2021~2026) for A-tier (>=78), S-tier (>=88), Pure_T2
  2. Delisted 20cm stocks hit count & return contribution
  3. 8-test Overfitting Suite (HLZ t, DSR M=30/150, CSCV PBO S=8/10, Monkey p, +-20% Weight/Exit/Thresh plateau, Bootstrap)
  4. Physical raw-data truncation at 2024-12-31 rebuild & max_abs_diff == 0.0 assertion
  5. kline_cache.db open price cross-check & V19.1 physical integrity assertions
  6. V19.1 10cm 5-strategy empty-slot (priority=6) insertion incremental contribution
Outputs: v1_final_summary.json
"""
import bisect, glob, itertools, json, math, os, pickle, re, sqlite3, sys, time
from collections import defaultdict
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.stats as stats

sys.dont_write_bytecode = True

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
OUT_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
V191_PATH = f"{BASE}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_combined_5strat_v191_slot1_clean.csv"
sys.path.insert(0, OUT_DIR)
sys.path.insert(0, PART2_DIR)

from backtest_utils import calc_d15_suite, _sim_k_slots, bench_return, ew20_bench_return
from step2_is_exit_tree_opt import compute_scorecard_v1, sim_exit_tree
from step3_oos_and_tables import FINAL_EXIT_CFG, calc_cap10m_nav, eval_full_suite
from step0_build_clean_p1_pool import (
    ST_ON_RE, ST_EXC_RE, ST_REV_RE, TOX_RE, REG_RE, REG_EXC, EARN_POS_RE,
    shift_cal, cnt_ts_win, is_st_at
)


def yearly_full_table(tr: pd.DataFrame, sh300: dict, ew20: dict) -> dict:
    out = {}
    for yr in ["2021", "2022", "2023", "2024", "2025", "2026"]:
        sdt = f"{yr}-01-01"
        edt = f"{yr}-12-31" if yr != "2026" else "2026-11-23"
        hs = bench_return(sh300, sdt, edt)
        ew20_r = ew20_bench_return(ew20, sdt, edt)
        sub = tr[(tr["buy_date"] >= sdt) & (tr["buy_date"] <= edt)] if not tr.empty else pd.DataFrame()
        if sub.empty:
            out[yr] = {"raw_n": 0, "n_1s": 0, "nav_1s": 1.0, "cap10m": 1.0, "hs300_pct": round(hs * 100, 2), "ew20_pct": round(ew20_r * 100, 2)}
            continue
        t1, nav1, mdd1 = _sim_k_slots(sub, 1)
        _, nav3, _ = _sim_k_slots(sub, 3)
        ew_n = float(np.prod(1.0 + sub.groupby("buy_date")["net_ret"].mean().to_numpy()))
        r1 = t1["net_ret_eval"].to_numpy()
        w1, l1 = r1[r1 > 0], r1[r1 <= 0]
        po1 = float(w1.mean() / abs(l1.mean())) if (len(w1) and len(l1) and l1.mean() < 0) else (99.0 if len(w1) else 0.0)
        cap10 = calc_cap10m_nav(r1)
        out[yr] = {
            "raw_n": int(len(sub)), "n_1s": int(len(t1)),
            "wr_1s": round(float((r1 > 0).mean() * 100), 2),
            "po_1s": round(po1, 2),
            "mean_1s": round(float(r1.mean() * 100), 2),
            "nav_1s": round(nav1, 3), "cap10m": cap10, "nav_3s": round(nav3, 3), "ew_nav": round(ew_n, 3),
            "mdd_1s": round(mdd1 * 100, 2),
            "hs300_pct": round(hs * 100, 2), "ew20_pct": round(ew20_r * 100, 2),
            "ex_hs300_pp": round((nav1 - 1.0 - hs) * 100, 2),
            "ex_ew20_pp": round((nav1 - 1.0 - ew20_r) * 100, 2),
        }
    return out


def run_overfitting_audit(label: str, pool: pd.DataFrame, fm: pd.DataFrame, sc: np.ndarray,
                          thr: float, all_sig: pd.DataFrame, sh300: dict, all_dts: list[str]) -> dict:
    tr_raw = all_sig[all_sig["score"] >= thr].copy()
    t1, nav1, mdd1 = _sim_k_slots(tr_raw, 1)
    n = len(t1)
    r1 = t1["net_ret_eval"].to_numpy(dtype=float)

    def _b(bd: str, ed: str) -> float:
        return bench_return(sh300, bd, ed)

    ex = np.array([float(r.net_ret_eval) - _b(str(r.buy_date), str(r.exit_date)) for r in t1.itertuples(index=False)], dtype=float)
    sr_tr = float(ex.mean() / ex.std(ddof=1)) if n > 1 else 0.0
    t_tr = float(sr_tr * np.sqrt(n))

    t_days = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2026-11-23"]
    day_idx = {d: i for i, d in enumerate(t_days)}

    def _build_daily(led: pd.DataFrame) -> np.ndarray:
        arr = np.zeros(len(t_days), dtype=float)
        for r in led.itertuples(index=False):
            i = day_idx.get(str(r.exit_date))
            if i is not None:
                arr[i] += float(r.net_ret_eval)
        return arr

    d_arr = _build_daily(t1)
    sr_d = float(d_arr.mean() / d_arr.std(ddof=1)) if d_arr.std(ddof=1) > 1e-12 else 0.0
    t_d = float(sr_d * np.sqrt(len(d_arr)))
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(ex, fisher=False, bias=False))) if n > 3 else 3.0
    gm = 0.5772156649
    dsr_out = {}
    for M in (30, 150):
        sr0 = (1.0 / math.sqrt(max(n - 1, 1))) * (
            (1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / M) + gm * stats.norm.ppf(1.0 - 1.0 / (M * math.e))
        )
        den = math.sqrt(max(1e-12, 1.0 - sk * sr_tr + ((ku - 1.0) / 4.0) * (sr_tr ** 2)))
        dsr_out[f"M{M}"] = round(float(stats.norm.cdf((sr_tr - sr0) * math.sqrt(max(n - 1, 1)) / den)), 4)

    # Monkey 5000 draws from skeleton pool
    rng = np.random.default_rng(20261124)
    bg_rets = all_sig["net_ret"].to_numpy(dtype=float)
    wins_m = sum(1 for _ in range(5000) if np.prod(1.0 + rng.choice(bg_rets, size=n, replace=True)) >= nav1)
    monkey_p = round((wins_m + 1) / 5001, 5)

    # CSCV PBO across threshold ladder & quantile ladder
    def _cscv(R: np.ndarray, ng: int) -> dict:
        gs = len(t_days) // ng
        gidx = [list(range(i * gs, (i + 1) * gs if i < ng - 1 else len(t_days))) for i in range(ng)]
        omegas = []
        for te in itertools.combinations(range(ng), ng // 2):
            trg = [k for k in range(ng) if k not in te]
            tri = [x for k in trg for x in gidx[k]]
            tei = [x for k in te for x in gidx[k]]
            rt, re_ = R[tri], R[tei]
            sd_t, sd_e = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
            se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
            b = int(np.argmax(st))
            omegas.append(float(np.mean(se > se[b])))
        return {"pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2), "mean_rank_oos": round(float(np.mean(omegas)), 4)}

    th_lad = [70, 72, 74, 76, 78, 80, 82, 84, 86, 88]
    R_lad = np.column_stack([_build_daily(_sim_k_slots(all_sig[all_sig["score"] >= t_i], 1)[0]) for t_i in th_lad])
    loc_lad = [int(thr + d) for d in (-4, -3, -2, -1, 0, 1, 2, 3, 4)]
    R_loc = np.column_stack([_build_daily(_sim_k_slots(all_sig[all_sig["score"] >= t_i], 1)[0]) for t_i in loc_lad])
    R_q = np.zeros((len(t_days), 14), dtype=float)
    R_q[:, 0] = d_arr
    sc_sub = all_sig[all_sig["score"] >= thr]["score"]
    for v in range(1, 14):
        qv = float(np.quantile(sc_sub, 0.05 + (v / 14.0) * 0.40))
        R_q[:, v] = _build_daily(_sim_k_slots(all_sig[all_sig["score"] >= qv], 1)[0])
    pbo_lad_s8 = _cscv(R_lad, 8)
    pbo_lad_s10 = _cscv(R_lad, 10)
    pbo_loc_s8 = _cscv(R_loc, 8)
    pbo_loc_s10 = _cscv(R_loc, 10)
    pbo_q_s8 = _cscv(R_q, 8)
    pbo_q_s10 = _cscv(R_q, 10)

    # Weight ±20% 200x MC + Threshold ±20% plateau + Exit parameter ±20% plateau
    fm_mat = all_sig[list(fm.columns)].to_numpy(dtype=float)
    mc_navs, mc_wrs, mc_ns, mc_is_navs, mc_oos_navs = [], [], [], [], []
    for _ in range(200):
        mult = rng.uniform(0.80, 1.20, size=fm_mat.shape[1])
        sc_p = 70.0 + fm_mat @ mult
        sub_p = all_sig[sc_p >= thr]
        s1_p, nv_p, _ = _sim_k_slots(sub_p, 1)
        _, nv_is, _ = _sim_k_slots(sub_p[sub_p["buy_date"] <= "2024-08-31"], 1)
        _, nv_oos, _ = _sim_k_slots(sub_p[sub_p["buy_date"] >= "2024-09-01"], 1)
        mc_ns.append(len(s1_p))
        mc_navs.append(nv_p)
        mc_is_navs.append(nv_is)
        mc_oos_navs.append(nv_oos)
        mc_wrs.append(float((s1_p["net_ret_eval"] > 0).mean() * 100.0) if not s1_p.empty else 0.0)

    # Threshold +-20% of margin above base 70 (e.g. 78 -> margin 8 -> +-20% => [76, 77, 78, 79, 80]; 88 -> [84..92])
    margin = max(5.0, thr - 70.0)
    th_pert = {}
    for d_lbl, th_v in [("-20%", round(70 + margin * 0.8)), ("-10%", round(70 + margin * 0.9)), ("base", thr), ("+10%", round(70 + margin * 1.1)), ("+20%", round(70 + margin * 1.2))]:
        s_th = all_sig[all_sig["score"] >= th_v]
        _, nv_f, _ = _sim_k_slots(s_th, 1)
        _, nv_i, _ = _sim_k_slots(s_th[s_th["buy_date"] <= "2024-08-31"], 1)
        _, nv_o, _ = _sim_k_slots(s_th[s_th["buy_date"] >= "2024-09-01"], 1)
        th_pert[d_lbl] = {"th": th_v, "full_1s": round(nv_f, 2), "is_1s": round(nv_i, 2), "oos_1s": round(nv_o, 2)}

    # Exit parameter +-20% plateau vs Pure T2 Close (on A-tier >= thr)
    pool_sub = pool[sc >= thr].copy()
    pure_t2_tr = sim_exit_tree(pool_sub, {"b3_tp_mode": "none"})
    _, pt2_is, _ = _sim_k_slots(pure_t2_tr[pure_t2_tr["buy_date"] <= "2024-08-31"], 1)
    _, pt2_oos, _ = _sim_k_slots(pure_t2_tr[pure_t2_tr["buy_date"] >= "2024-09-01"], 1)
    exit_grid = [
        ("adapt_k=1.2(-20%)", {**FINAL_EXIT_CFG, "b3_adapt_k": 1.2}),
        ("adapt_k=1.8(+20%)", {**FINAL_EXIT_CFG, "b3_adapt_k": 1.8}),
        ("b2_tp=0.096(-20%)", {**FINAL_EXIT_CFG, "b2_tp": 0.096}),
        ("b2_tp=0.144(+20%)", {**FINAL_EXIT_CFG, "b2_tp": 0.144}),
        ("b2_body=0.048(-20%)", {**FINAL_EXIT_CFG, "b2_body": 0.048}),
        ("b2_body=0.072(+20%)", {**FINAL_EXIT_CFG, "b2_body": 0.072}),
        ("b2_clv=0.52(-20%)", {**FINAL_EXIT_CFG, "b2_clv": 0.52}),
        ("b2_clv=0.78(+20%)", {**FINAL_EXIT_CFG, "b2_clv": 0.78}),
    ]
    ex_plat = []
    beat_both = 0
    for e_nm, e_cfg in exit_grid:
        etr = sim_exit_tree(pool_sub, e_cfg)
        _, e_is, _ = _sim_k_slots(etr[etr["buy_date"] <= "2024-08-31"], 1)
        _, e_oos, _ = _sim_k_slots(etr[etr["buy_date"] >= "2024-09-01"], 1)
        _, e_full, _ = _sim_k_slots(etr, 1)
        ok = (e_is > pt2_is) and (e_oos > pt2_oos)
        beat_both += int(ok)
        ex_plat.append({"param": e_nm, "is_1s": round(e_is, 2), "oos_1s": round(e_oos, 2), "full_1s": round(e_full, 2), "beat_pure_t2_both": ok})

    # Bootstrap 5000x
    b_means = np.array([np.mean(ex[rng.integers(0, n, size=n)]) for _ in range(5000)], dtype=float)
    rho1 = float(np.corrcoef(ex[:-1], ex[1:])[0, 1]) if n > 2 else 0.0
    rho1 = 0.0 if math.isnan(rho1) else rho1
    n_eff = float(n * (1.0 - rho1) / (1.0 + rho1)) if rho1 > 0 else float(n)

    return {
        "label": label,
        "hlz_t_trade": round(t_tr, 2), "hlz_t_daily": round(t_d, 2),
        "sr_trade": round(sr_tr, 4), "sr_annual_daily": round(sr_d * math.sqrt(242), 3),
        "dsr_M30": dsr_out["M30"], "dsr_M150": dsr_out["M150"],
        "monkey_p": monkey_p,
        "cscv_pbo_S8": pbo_lad_s8, "cscv_pbo_S10": pbo_lad_s10,
        "cscv_pbo_local_S8": pbo_loc_s8, "cscv_pbo_local_S10": pbo_loc_s10,
        "cscv_pbo_q14_S8": pbo_q_s8, "cscv_pbo_q14_S10": pbo_q_s10,
        "weight_mc_200": {
            "mean_n": round(float(np.mean(mc_ns)), 1), "mean_wr": round(float(np.mean(mc_wrs)), 2),
            "full_p10": round(float(np.percentile(mc_navs, 10)), 2), "full_med": round(float(np.median(mc_navs)), 2),
            "is_p10": round(float(np.percentile(mc_is_navs, 10)), 2), "oos_p10": round(float(np.percentile(mc_oos_navs, 10)), 2),
            "prob_oos_gt_2x_pct": round(float((np.array(mc_oos_navs) > 2.0).mean() * 100.0), 1),
            "prob_full_gt_1x_pct": round(float((np.array(mc_navs) > 1.0).mean() * 100.0), 1),
        },
        "threshold_pm20": th_pert,
        "exit_param_pm20_plateau": {"pass_rate_pct": round(beat_both / len(exit_grid) * 100.0, 1), "pure_t2_is": round(pt2_is, 2), "pure_t2_oos": round(pt2_oos, 2), "cases": ex_plat},
        "bootstrap_5pct_excess_pct": round(float(np.percentile(b_means, 5) * 100.0), 2),
        "n_eff": round(n_eff, 2),
    }


def physical_truncation_rebuild_audit(slot_A_full: pd.DataFrame, slot_S_full: pd.DataFrame) -> dict:
    """
    Strictly rebuild EVERYTHING from raw files truncated at <= 2024-12-31
    (no cache_20cm_panel.parquet!) and verify max_abs_diff == 0.0 on 2021~2024!
    """
    t0 = time.time()
    CUT_DT = "2024-12-31"
    CUT_TS = "2024-12-31 23:59:59"
    ts_cut = pd.Timestamp(CUT_DT)

    # 1. Raw prices (20cm + 10cm) truncated at 2024-12-31
    cols_p = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    flt = ds.field("date") <= ts_cut
    a1 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols_p, filter=flt).to_table().to_pandas()
    a2 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols_p, filter=flt).to_table().to_pandas()
    a1["dl"], a2["dl"] = 0, 1
    raw_all = pd.concat([a1, a2], ignore_index=True)
    raw_all["c6"] = raw_all["ticker"].astype(str).str[:6]
    raw_all["dt"] = pd.to_datetime(raw_all["date"]).dt.strftime("%Y-%m-%d")
    raw_all = raw_all[raw_all["ticker"].str.endswith((".SH", ".SZ")) & (raw_all["close"] > 0) & (raw_all["adj_close"] > 0)].copy()
    raw_all = raw_all.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    # 10cm market stats <= 2024-12-31
    d10 = raw_all[raw_all["c6"].str.startswith(("00", "60")) & (raw_all["dt"] >= "2020-12-01")].copy()
    g10 = d10.groupby("c6", sort=False)
    s10 = d10["adj_close"] / d10["close"]
    pac10 = g10["adj_close"].shift(1)
    r10 = d10["adj_close"] / pac10 - 1.0
    ztp10 = np.floor((pac10 / s10) * 1.10 * 100.0 + 0.5) / 100.0
    dtp10 = np.floor((pac10 / s10) * 0.90 * 100.0 + 0.5) / 100.0
    abn10 = r10.abs() > 0.12
    d10["is_zt"] = (pac10 > 0) & (d10["close"] >= ztp10 - 0.011) & (r10 >= 0.095) & (~abn10)
    d10["is_dt"] = (pac10 > 0) & (d10["close"] <= dtp10 + 0.011) & (r10 <= -0.095) & (~abn10)
    mkt10_zt = d10[d10["dt"] >= "2021-01-01"].groupby("dt")["is_zt"].sum().to_dict()
    mkt10_dt = d10[d10["dt"] >= "2021-01-01"].groupby("dt")["is_dt"].sum().to_dict()

    # 20cm panel <= 2024-12-31
    df = raw_all[raw_all["c6"].str.startswith(("30", "688", "689"))].copy().reset_index(drop=True)
    df["list_age"] = df.groupby("c6", sort=False).cumcount() + 1
    df = df[df["dt"] >= "2020-08-24"].copy().reset_index(drop=True)
    g = df.groupby("c6", sort=False)
    # Use qfq_factor directly to normalize to truncated window end (price ratios are scale-invariant!)
    sc_ratio = df["adj_close"] / df["close"]
    df["ao"], df["ah"], df["al"], df["ac"] = df["open"] * sc_ratio, df["high"] * sc_ratio, df["low"] * sc_ratio, df["adj_close"]
    df["prev_ac"] = g["ac"].shift(1)
    df["ret"] = df["ac"] / df["prev_ac"] - 1.0
    df["o_pct"] = df["ao"] / df["prev_ac"] - 1.0
    df["abn_ret"] = df["ret"].abs() > 0.22
    df["tradable"] = (df["volume"] > 0) & (df["open"] > 0) & (df["list_age"] > 10) & (~df["abn_ret"])
    prev_ex = df["prev_ac"] / sc_ratio
    df["zt_px"] = np.floor(prev_ex * 1.20 * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(prev_ex * 0.80 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["prev_ac"] > 0) & (df["close"] >= df["zt_px"] - 0.011) & (df["ret"] >= 0.195) & (~df["abn_ret"])
    df["is_dt"] = (df["prev_ac"] > 0) & (df["close"] <= df["dt_px"] + 0.011) & (df["ret"] <= -0.195) & (~df["abn_ret"])
    df["is_yizi_zt"] = df["is_zt"] & (df["low"] == df["high"]) & (df["o_pct"] >= 0.195)
    df["buyable_open"] = (df["volume"] > 0) & (df["open"] > 0) & (~((df["o_pct"] >= 0.195) & (df["low"] == df["high"])))
    df["sellable_close"] = (df["volume"] > 0) & (df["close"] > 0) & (~((df["ret"] <= -0.195) & (df["low"] == df["high"])))
    df["open_is_dt"] = (df["prev_ac"] > 0) & (df["open"] <= df["dt_px"] + 0.011) & (df["o_pct"] <= -0.195)
    df["open_is_zt"] = (df["prev_ac"] > 0) & (df["open"] >= df["zt_px"] - 0.011) & (df["o_pct"] >= 0.195)
    df["sellable_strict"] = df["sellable_close"] & (~df["is_dt"])
    df["dt_px_adj"] = df["dt_px"] * sc_ratio
    df["is_true_yang"] = df["close"] > df["open"]
    df["clv"] = np.where(df["ah"] > df["al"], (df["ac"] - df["al"]) / (df["ah"] - df["al"]), 0.5)
    s_zt = df["is_zt"].astype(int); s_sh = g["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    df["ma20"] = g["ac"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    df["bias20"] = df["ac"] / df["ma20"] - 1.0
    df["ret3"] = df["ac"] / g["ac"].shift(3) - 1.0
    df["to"] = df["turn"] * 100.0
    est_sh = np.where(df["oshare"].fillna(0) > 0, df["oshare"], np.where(df["turn"] > 0, df["volume"] / df["turn"], np.nan))
    df["mcap"] = est_sh * df["close"] / 1e8
    df["zt_cnt_60d"] = g["is_zt"].transform(lambda s: s.rolling(60, min_periods=1).sum())

    # Top10 lockup (< dt)
    t10 = json.load(open(f"{PART2_DIR}/pit_top10_20cm_summary.json", encoding="utf-8"))
    lock_arr = np.full(len(df), np.nan)
    for c6, idx_arr in g.groups.items():
        recs = [x for x in t10.get(c6, []) if x[0] <= CUT_DT]
        if not recs: continue
        dts = df.loc[idx_arr, "dt"].values
        l_vals = np.full(len(dts), np.nan)
        for j, d in enumerate(dts):
            best_ed, best_l = "", np.nan
            for nd, ed, l10, _ in recs:
                if nd < d and ed >= best_ed:
                    best_ed, best_l = ed, l10
            l_vals[j] = best_l
        lock_arr[idx_arr] = l_vals
    df["lock_top10"] = lock_arr
    lock_fill = np.where(np.isnan(lock_arr), 40.0, np.clip(lock_arr, 0.0, 95.0))
    df["real_free_mcap"] = df["mcap"] * (1.0 - lock_fill / 100.0)

    # Benchmarks <= 2024-12-31 for dist_3d30
    idx_json = json.load(open(f"{BASE}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300_t = {k: float(v) for k, v in idx_json.get("sh000300", {}).items() if k <= CUT_DT}
    sz_t = {k: float(v) for k, v in idx_json.get("sz399107", {}).items() if k <= CUT_DT}

    # ZT tape & KPL <= 2024-12-31
    con_z = sqlite3.connect(f"file:{BASE}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    zt_tape = {}
    st_events = defaultdict(list)
    zt_names = defaultdict(list)
    for td, sc, nm, fst, sa in con_z.execute(
        "SELECT trade_date, sec_code, sec_name, first_seal_time, seal_amount FROM zt_micro_tape WHERE trade_date <= ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')", (CUT_DT,)
    ):
        c6 = str(sc).zfill(6)
        fst_s = str(fst or "15:00:00").replace(":", "")[:6]
        hhmm = int(fst_s[:4]) if fst_s[:4].isdigit() else 1500
        zt_tape[(str(td), c6)] = (hhmm, float(sa or 0.0))
        s = str(nm or "").strip()
        if s:
            zt_names[c6].append((str(td), s))
            st_events[c6].append((f"{td} 15:00:00", 1 if ("ST" in s or "退" in s) else 0))
    con_z.close()

    from layer_events_pit import NON_THEME
    plate_elo = defaultdict(lambda: 100.0)
    stock_kpl = {}
    with open(f"{BASE}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip(): continue
            obj = json.loads(ln); dt = obj.get("date", "")
            if dt < "2020-11-01" or dt > CUT_DT: continue
            today_p = []
            for pl in obj.get("plates", []):
                pname = str(pl.get("plate", ""))
                stks = pl.get("stocks", [])
                if not stks or pname in NON_THEME: continue
                n20 = sum(1 for s in stks if str(s[0]).strip()[:6].zfill(6).startswith(("30", "688", "689")))
                sz = len(stks); elo_v = plate_elo[pname]; today_p.append(pname)
                if dt >= "2021-01-01":
                    for s in stks:
                        c6 = str(s[0]).strip()[:6].zfill(6)
                        if c6.startswith(("30", "688", "689")):
                            cur = stock_kpl.get((dt, c6))
                            if cur is None or sz > cur[0]:
                                stock_kpl[(dt, c6)] = (sz, n20, elo_v)
            for pname in set(today_p):
                plate_elo[pname] = plate_elo[pname] * 0.96 + 4.5

    # LHB <= 2024-12-31
    lhb = pd.read_parquet(f"{BASE}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet")
    lhb = lhb[(lhb["date"] <= CUT_DT) & lhb["stock_code"].str.startswith(("30", "688", "689"))].copy().sort_values(["date", "stock_code", "is_three"])
    from layer_events_pit import RE_LHASA, RE_QUANT, RE_SURF_YZ, IS_BAD_CODES
    lhb_map = {}
    for (dt, sc, is3), grp in lhb.groupby(["date", "stock_code", "is_three"], sort=False):
        if is3 == 1 and (dt, sc) in lhb_map: continue
        b_rows = grp[grp["side"] == "B"]
        inst_net = float(grp[grp["dept_code"] == "0"]["NET"].sum()) / 1e4
        dnames_b = b_rows["dept_name"].astype(str).tolist()
        dcodes_b = set(b_rows[b_rows["NET"] > 0]["dept_code"].astype(str))
        lh_net = float(sum(v for d, v in zip(dnames_b, b_rows["NET"]) if RE_LHASA.search(d) and "东亚" not in d))
        q_cnt = sum(1 for d in dnames_b if RE_QUANT.search(d))
        s_cnt = sum(1 for d in dnames_b if RE_SURF_YZ.search(d))
        lhb_map[(dt, sc)] = (inst_net, int(lh_net > 0), q_cnt, int(s_cnt > 0 or bool(dcodes_b & IS_BAD_CODES)))

    # Attach forward bars <= 2024-12-31
    for k in range(1, 12):
        df[f"f{k}_dt"] = g["dt"].shift(-k).fillna("")
        df[f"f{k}_ao"] = g["ao"].shift(-k); df[f"f{k}_ah"] = g["ah"].shift(-k)
        df[f"f{k}_al"] = g["al"].shift(-k); df[f"f{k}_ac"] = g["ac"].shift(-k)
        df[f"f{k}_o_pct"] = g["o_pct"].shift(-k)
        df[f"f{k}_buyable"] = g["buyable_open"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_sellable"] = g["sellable_close"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_sellable_strict"] = g["sellable_strict"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_is_dt"] = g["is_dt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_open_is_dt"] = g["open_is_dt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_open_is_zt"] = g["open_is_zt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_zt"] = g["is_zt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_ty"] = g["is_true_yang"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_dt_px_adj"] = g["dt_px_adj"].shift(-k)
    df["f1_abn_ret"] = g["abn_ret"].shift(-1).fillna(False).astype(bool)
    df["f1_clv"] = g["clv"].shift(-1)
    df["f1_body"] = np.where(df["f1_ao"] > 0, df["f1_ac"] / df["f1_ao"] - 1.0, np.nan)

    df = df[df["dt"] >= "2021-01-04"].copy().reset_index(drop=True)
    ew20_dts = sorted(df["dt"].unique())
    idx_s = pd.Series([sz_t.get(d, sh300_t.get(d, np.nan)) for d in ew20_dts], index=ew20_dts)
    df["dist_3d30"] = 0.30 - (df["ret3"] - df["dt"].map(idx_s.pct_change(3).to_dict()).fillna(0.0))
    df["mkt10_zt_cnt"] = df["dt"].map(mkt10_zt).fillna(0).astype(int)
    df["mkt10_dt_cnt"] = df["dt"].map(mkt10_dt).fillna(0).astype(int)
    df["f1_mkt10_dt_cnt"] = df["f1_dt"].map(mkt10_dt).fillna(0).astype(int)
    mkt20_dt_map = df[df["is_dt"]].groupby("dt").size().to_dict()
    df["mkt20_dt_cnt"] = df["dt"].map(mkt20_dt_map).fillna(0).astype(int)
    df["f1_mkt20_dt_cnt"] = df["f1_dt"].map(mkt20_dt_map).fillna(0).astype(int)

    mkt20_ozt = df.groupby("dt")["open_is_zt"].sum().to_dict()
    df["f1_mkt20_0925_zt"] = df["f1_dt"].map(mkt20_ozt).fillna(0).astype(int)
    first_b = df[df["is_zt"] & (df["streak"] == 1) & (~df["is_yizi_zt"]) & df["f1_o_pct"].notna()]
    fb_sum = first_b.groupby("dt")["f1_o_pct"].agg(["sum", "count"]).to_dict("index")

    cand = df[df["tradable"] & (df["close"] >= 2.0) & df["is_zt"] & (df["streak"] == 1) & (~df["is_yizi_zt"])
              & (df["amount"] >= 1e8) & df["f1_buyable"] & (~df["f1_abn_ret"]) & df["f1_o_pct"].between(-0.10, -0.030)].copy().reset_index(drop=True)

    # PIT events strictly <= CUT_TS (use ALL 20cm tickers for ST timeline so mkt20_zt_cnt is 100% consistent!)
    all_20_set = set(df["c6"].unique())
    c6_set = set(cand["c6"].unique()); c6_list = sorted(c6_set); ph = ",".join("?" * len(c6_list))
    tox_m, reg_m, ep_m = defaultdict(list), defaultdict(list), defaultdict(list)
    con_n = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, ti, at, ts in con_n.execute("SELECT sec_code, title, ann_type, pub_datetime_cst FROM notices WHERE pub_datetime_cst <= ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')", (CUT_TS,)):
        c6, ts_s, t_s, a_s = str(sc).zfill(6), str(ts)[:19], str(ti or ""), str(at or "")
        if c6 in all_20_set:
            if ST_REV_RE.search(t_s) and "不" not in t_s[:10]: st_events[c6].append((ts_s, 0))
            elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s): st_events[c6].append((ts_s, 1))
        if c6 in c6_set:
            if TOX_RE.search(t_s): tox_m[c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg_m[c6].append(ts_s)
            if (EARN_POS_RE.search(a_s) or EARN_POS_RE.search(t_s)) and not re.search(r"(?:预减|首亏|续亏|增亏|略减|修正.*向下|预亏)", a_s + t_s):
                ep_m[c6].append(ts_s)
    con_n.close()
    rt = pd.read_parquet(f"{BASE}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    for r in rt[(rt["pub_datetime_cst"].astype(str) <= CUT_TS) & rt["c6"].isin(all_20_set)].itertuples(index=False):
        t_s, ts_s = str(r.title or ""), str(r.pub_datetime_cst)[:19]
        if ST_REV_RE.search(t_s): st_events[r.c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s): st_events[r.c6].append((ts_s, 1))
        if r.c6 in c6_set:
            if TOX_RE.search(t_s): tox_m[r.c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg_m[r.c6].append(ts_s)
    for zf in glob.glob(f"{BASE}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6, d_z = str(it[0]).zfill(6), str(it[2])[:10]
            if c6 in c6_set and d_z <= CUT_DT:
                reg_m[c6].append(d_z + " 08:00:00")
    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_events.items()}

    # Compute true ST-filtered mkt20_zt_cnt <= 2024-12-31 (and mkt20_dt_cnt excluding old ST if needed)
    df_st_mask = np.array([is_st_at(st_tl, r.c6, f"{r.dt} 15:00:00") for r in df.itertuples(index=False)], dtype=int)
    mkt20_zt_clean = df[df["is_zt"] & (df_st_mask == 0)].groupby("dt").size().to_dict()
    mkt20_dt_clean = df[df["is_dt"] & (df_st_mask == 0)].groupby("dt").size().to_dict()
    cand["mkt20_zt_cnt"] = cand["dt"].map(mkt20_zt_clean).fillna(0).astype(int)
    cand["f1_mkt20_dt_cnt"] = cand["f1_dt"].map(mkt20_dt_clean).fillna(0).astype(int)

    xq_p, seen_xq = defaultdict(list), defaultdict(set)
    con_x = sqlite3.connect(f"file:{BASE}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_x.execute(f"SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE substr(symbol,1,6) IN ({ph}) AND created_time_str >= '2020-12-01' AND created_time_str <= ?", c6_list + [CUT_TS]):
        c6 = str(sym)[:6].zfill(6); p = str(pid).replace("xq_", "")
        if p not in seen_xq[c6] and cts: seen_xq[c6].add(p); xq_p[c6].append(str(cts)[:19])
    con_x.close()
    con_c = sqlite3.connect(f"file:{BASE}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_c.execute(f"SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND substr(symbol,1,6) IN ({ph}) AND pub_datetime_cst >= '2020-12-01' AND pub_datetime_cst <= ?", c6_list + [CUT_TS]):
        c6 = str(sym)[:6].zfill(6); p = str(pid).replace("xq_", "")
        if p not in seen_xq[c6] and cts: seen_xq[c6].add(p); xq_p[c6].append(str(cts)[:19])
    con_c.close()
    xq_s = {k: sorted(v) for k, v in xq_p.items()}
    for m in (tox_m, reg_m, ep_m):
        for k in list(m.keys()): m[k] = sorted(set(m[k]))

    n = len(cand)
    keep = np.zeros(n, dtype=bool)
    f1_p1b, zt_hh, zt_sr, kpl_20, kpl_el = [], [], [], [], []
    inst_n, lh_p, q_a, s_a, xq_a, ep_a, f1_inst_a = [], [], [], [], [], [], []
    for i, r in enumerate(cand.itertuples(index=False)):
        c6, dt, f1dt = r.c6, r.dt, r.f1_dt or r.dt
        if f1dt > CUT_DT or r.f2_dt == "" or r.f2_dt > CUT_DT:
            f1_p1b.append(np.nan); zt_hh.append(9999); zt_sr.append(0.0); kpl_20.append(0); kpl_el.append(100.0)
            inst_n.append(0.0); lh_p.append(0); q_a.append(0); s_a.append(0); xq_a.append(0); ep_a.append(0); f1_inst_a.append(0.0)
            continue
        t1c = f"{f1dt} 09:00:00"
        st0 = is_st_at(st_tl, c6, f"{dt} 15:00:00")
        st1 = is_st_at(st_tl, c6, t1c)
        tx = cnt_ts_win(tox_m.get(c6), f"{shift_cal(dt,-90)} 00:00:00", t1c)
        rg = cnt_ts_win(reg_m.get(c6), f"{shift_cal(dt,-10)} 00:00:00", t1c)
        keep[i] = (st0 == 0 and st1 == 0 and tx == 0 and rg == 0 and r.mkt20_zt_cnt < 16)
        fs = fb_sum.get(dt)
        f1_p1b.append((fs["sum"] - r.f1_o_pct) / (fs["count"] - 1) if (fs and fs["count"] > 1) else np.nan)
        zt = zt_tape.get((dt, c6), (9999, 0.0))
        zt_hh.append(zt[0]); zt_sr.append(zt[1] / r.amount if r.amount > 0 else 0.0)
        kp = stock_kpl.get((dt, c6), (0, 0, 100.0))
        kpl_20.append(kp[1]); kpl_el.append(kp[2])
        lh = lhb_map.get((dt, c6), (0.0, 0, 0, 0))
        inst_n.append(lh[0]); lh_p.append(lh[1]); q_a.append(lh[2]); s_a.append(lh[3])
        f1_inst_a.append(lhb_map.get((f1dt, c6), (0.0, 0, 0, 0))[0])
        xq_a.append(cnt_ts_win(xq_s.get(c6), f"{dt} 00:00:00", t1c))
        ep_a.append(int(cnt_ts_win(ep_m.get(c6), f"{shift_cal(dt,-3)} 00:00:00", t1c) > 0))

    cand["f1_mkt20_prev1b_open"] = f1_p1b; cand["zt_hhmm"] = zt_hh; cand["zt_seal_ratio"] = zt_sr
    cand["kpl_20zt"] = kpl_20; cand["kpl_elo"] = kpl_el
    cand["lhb_inst_net"] = inst_n; cand["lhb_lh_net_pos"] = lh_p; cand["lhb_quant"] = q_a; cand["lhb_surf"] = s_a
    cand["f1_lhb_inst_net"] = f1_inst_a; cand["xq_t1_0900"] = xq_a; cand["cat_earn_pos_3d"] = ep_a
    cand["f1_weekday"] = pd.to_datetime(cand["f1_dt"]).dt.dayofweek.fillna(-1).astype(int)
    cand["name"] = cand["c6"]

    sub_tr = cand[keep].copy().reset_index(drop=True)
    sc_t, _ = compute_scorecard_v1(sub_tr)
    sub_tr["score"] = sc_t.values

    res = {}
    for tier_lbl, th, full_df in [("A_78", 78.0, slot_A_full), ("S_88", 88.0, slot_S_full)]:
        tr_t = sim_exit_tree(sub_tr[sub_tr["score"] >= th], FINAL_EXIT_CFG)
        s1_t, _, _ = _sim_k_slots(tr_t, 1)
        t24 = s1_t[s1_t["exit_date"] <= CUT_DT].sort_values(["buy_date", "c6"]).reset_index(drop=True)
        f24 = full_df[full_df["exit_date"] <= CUT_DT].sort_values(["buy_date", "c6"]).reset_index(drop=True)
        if len(t24) != len(f24):
            kt = set(zip(t24["buy_date"], t24["c6"].astype(str).str.zfill(6)))
            kf = set(zip(f24["buy_date"], f24["c6"].astype(str).str.zfill(6)))
            print("  [TRUNC DIFF]", tier_lbl, "only in full:", sorted(kf - kt), "only in trunc:", sorted(kt - kf))
            for bd, c6 in sorted((kf ^ kt)):
                r_tr = sub_tr[(sub_tr["f1_dt"] == bd) & (sub_tr["c6"] == c6)]
                print("    in sub_tr:", r_tr[["dt","f1_dt","c6","score","mkt20_zt_cnt","lock_top10","real_free_mcap","dist_3d30","zt_hhmm","zt_seal_ratio","lhb_inst_net","kpl_elo","kpl_20zt","f1_mkt20_prev1b_open","f1_mkt20_0925_zt","xq_t1_0900"]].to_dict("records"))
        assert len(t24) == len(f24), f"Trunc len mismatch {tier_lbl}: {len(t24)} vs {len(f24)}"
        assert (t24["buy_date"] == f24["buy_date"]).all() and (t24["c6"].astype(str).str.zfill(6) == f24["c6"].astype(str).str.zfill(6)).all()
        assert (t24["exit_date"] == f24["exit_date"]).all() and (t24["exit_reason"] == f24["exit_reason"]).all()
        max_sc_diff = float(np.max(np.abs(t24["score"].to_numpy() - f24["score"].to_numpy())))
        max_ret_diff = float(np.max(np.abs(t24["net_ret_eval"].to_numpy() - f24["net_ret_eval"].to_numpy())))
        assert max_sc_diff == 0.0 and max_ret_diff < 1e-12, (tier_lbl, max_sc_diff, max_ret_diff)
        res[tier_lbl] = {"trades_2021_2024": int(len(t24)), "max_score_diff": max_sc_diff, "max_ret_diff": round(max_ret_diff, 15)}
    res["elapsed_sec"] = round(time.time() - t0, 2)
    return res


def kline_and_integrity_audit(slot_A: pd.DataFrame, slot_S: pd.DataFrame, all_sig: pd.DataFrame) -> dict:
    # 1. kline_cache.db cross-check on all_sig & slot_A
    con_k = sqlite3.connect(f"file:{BASE}/data/kline_cache.db?mode=ro", uri=True)
    k_df = pd.read_sql_query("SELECT code as c6, date as buy_date, open as k_open FROM daily_kline", con_k)
    con_k.close()
    da = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_daily.parquet", columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"])
    dd = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"])
    da["c6"] = da["ticker"].str[:6]; dd["c6"] = dd["ticker"].str[:6]
    cset = set(all_sig["c6"].astype(str).str.zfill(6))
    dall = pd.concat([da[da["c6"].isin(cset)], dd[dd["c6"].isin(cset)]], ignore_index=True)
    dall["dt"] = dall["date"].dt.strftime("%Y-%m-%d")
    dall = dall.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dall["prev_c_adj"] = dall.groupby("c6")["close"].shift(1) * dall.groupby("c6")["qfq_factor"].shift(0) / dall.groupby("c6")["qfq_factor"].shift(1)
    q_levels = dall[dall["dt"] >= "2025-01-01"].groupby("c6")["qfq_factor"].unique().to_dict()
    bar_m = {(r.c6, r.dt): r for r in dall.itertuples(index=False)}

    m_k = all_sig.assign(c6=all_sig["c6"].astype(str).str.zfill(6)).merge(k_df, on=["c6", "buy_date"], how="inner")
    m_k_A = slot_A.assign(c6=slot_A["c6"].astype(str).str.zfill(6)).merge(k_df, on=["c6", "buy_date"], how="inner")
    k_err_all, k_err_A = 0, 0
    for df_m, is_a in [(m_k, False), (m_k_A, True)]:
        for r in df_m.itertuples(index=False):
            bb = bar_m.get((r.c6, r.buy_date))
            if bb is None: continue
            # kline_cache stores either unadjusted or QFQ prices anchored to a snapshot date in 2025-2026
            diffs = [abs(r.k_open - bb.open)] + [abs(r.k_open - bb.open * (float(qc) / bb.qfq_factor)) for qc in q_levels.get(r.c6, [1.0])]
            if min(diffs) > 0.02:
                if is_a: k_err_A += 1
                else: k_err_all += 1

    # 2. V19.1 physical integrity assertions on slot_A and slot_S
    integ = {}
    for nm, led in [("A_78", slot_A), ("S_88", slot_S)]:
        d = led.copy(); d["c6"] = d["c6"].astype(str).str.zfill(6)
        t0_v = int((d["exit_date"] <= d["buy_date"]).sum())
        ov_v = sum(1 for i in range(1, len(d)) if d.iloc[i]["buy_date"] <= d.iloc[i-1]["exit_date"])
        yz_b, dt_e_close, yz_dt_e, oob_b, oob_e = 0, 0, 0, 0, 0
        for r in d.itertuples(index=False):
            bb = bar_m[(r.c6, r.buy_date)]; eb = bar_m[(r.c6, r.exit_date)]
            b_zt = np.floor(bb.prev_c_adj * 1.20 * 100.0 + 0.5) / 100.0
            e_dt = np.floor(eb.prev_c_adj * 0.80 * 100.0 + 0.5) / 100.0
            if bb.open >= b_zt - 0.011 and bb.low == bb.high: yz_b += 1
            if eb.close <= e_dt + 0.011 and eb.low == eb.high: yz_dt_e += 1
            if r.exit_hhmm >= 1455 and eb.close <= e_dt + 0.011 and (eb.close / eb.prev_c_adj - 1.0) <= -0.195: dt_e_close += 1
            bp_raw = r.buy_px * (bb.close / bb.adj_close)
            ep_raw = r.exit_px * (eb.close / eb.adj_close)
            if bp_raw < bb.low - 0.02 or bp_raw > bb.high + 0.02: oob_b += 1
            if ep_raw < eb.low - 0.02 or ep_raw > eb.high + 0.02: oob_e += 1
        assert t0_v == 0 and ov_v == 0 and yz_b == 0 and yz_dt_e == 0 and dt_e_close == 0 and oob_b == 0 and oob_e == 0, (nm, t0_v, ov_v, yz_b, yz_dt_e, dt_e_close, oob_b, oob_e)
        integ[nm] = {"n": int(len(d)), "t0": t0_v, "overlap": ov_v, "yizi_zt_buy": yz_b, "yizi_dt_exit": yz_dt_e, "dt_sealed_1500_sell": dt_e_close, "buy_oob": oob_b, "exit_oob": oob_e}
    return {"kline_matched_all": int(len(m_k)), "kline_matched_A": int(len(m_k_A)), "kline_err_all": k_err_all, "kline_err_A": k_err_A, "integrity": integ}


def v191_empty_slot_test(all_sig: pd.DataFrame, sh300: dict) -> dict:
    v191 = pd.read_csv(V191_PATH)
    v191["code"] = v191["code"].astype(str).str.zfill(6)
    s_dt, e_dt = "2021-11-15", "2026-11-16"
    hs_v = bench_return(sh300, s_dt, e_dt)

    def _stats(df_l):
        r = df_l["net_ret"].to_numpy(dtype=float)
        cum = np.cumprod(1.0 + r)
        pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
        mdd = float(np.max((pk - cum) / pk) * 100.0)
        w, l = r[r > 0], r[r <= 0]
        po = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
        return {
            "n": int(len(r)), "wr": round(float((r > 0).mean() * 100), 2), "po": round(po, 2),
            "nav": round(float(cum[-1]), 2), "cap10m": calc_cap10m_nav(r), "mdd": round(mdd, 2),
            "ex_hs300_pp": round((float(cum[-1]) - 1.0 - hs_v) * 100, 1),
            "by_strat": df_l["strategy"].value_counts().to_dict(),
        }

    out = {"v191_base": _stats(v191)}
    cols_k = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "net_ret"]
    v191_intervals = [((r.buy_date, int(r.buy_hhmm)), (r.exit_date, int(r.exit_hhmm))) for r in v191.itertuples(index=False)]

    def _fill_add_stats(cmb_df: pd.DataFrame) -> dict:
        v191_kept = int((cmb_df["priority"] <= 5).sum())
        add_df = cmb_df[cmb_df["priority"] == 6]
        r_add = add_df["net_ret"].to_numpy(dtype=float)
        st_c = _stats(cmb_df)
        st_c["v191_trades_preserved"] = f"{v191_kept}/{len(v191)}"
        st_c["added_20cm_n"] = int(len(add_df))
        st_c["added_20cm_wr"] = round(float((r_add > 0).mean() * 100), 2) if len(r_add) else 0.0
        st_c["added_20cm_mean_pct"] = round(float(r_add.mean() * 100), 2) if len(r_add) else 0.0
        st_c["added_20cm_solo_nav"] = round(float(np.prod(1.0 + r_add)), 3) if len(r_add) else 1.0
        return st_c

    for t_lbl, th in [("add_20cm_A78", 78.0), ("add_20cm_S88", 88.0)]:
        s20 = all_sig[(all_sig["score"] >= th) & (all_sig["buy_date"] >= s_dt) & (all_sig["buy_date"] <= e_dt)].copy()
        s20["code"] = s20["c6"].astype(str).str.zfill(6)
        s20["buy_hhmm"] = 925
        s20["exit_hhmm"] = np.where(s20["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
        s20["strategy"] = "20cm首板深水V1"
        s20["priority"] = 6
        pool = pd.concat([v191[cols_k], s20[cols_k]], ignore_index=True)
        pool = pool.sort_values(["buy_date", "priority", "score", "buy_hhmm", "code"], ascending=[True, True, False, True, True]).reset_index(drop=True)
        picked, cur_ed, cur_eh = [], "", 0
        for row in pool.itertuples(index=False):
            ok = (not cur_ed) or (row.buy_date > cur_ed) or (row.buy_date == cur_ed and row.buy_hhmm > cur_eh)
            if ok:
                picked.append(row._asdict())
                cur_ed, cur_eh = row.exit_date, row.exit_hhmm
        out[t_lbl] = _fill_add_stats(pd.DataFrame(picked))

        # Strict zero-preemption empty-slot insertion: freeze all 228 V19.1 trades, insert non-overlapping 20cm trades
        s20_ord = s20[cols_k].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).reset_index(drop=True)
        accepted_s20 = []
        occupied = list(v191_intervals)
        for row in s20_ord.itertuples(index=False):
            st_i = (row.buy_date, int(row.buy_hhmm))
            en_i = (row.exit_date, int(row.exit_hhmm))
            # Disjoint iff strictly before or strictly after every occupied interval
            if all((en_i < o_st) or (st_i > o_en) for o_st, o_en in occupied):
                accepted_s20.append(row._asdict())
                occupied.append((st_i, en_i))
        cmb_strict = pd.concat([v191[cols_k], pd.DataFrame(accepted_s20, columns=cols_k)], ignore_index=True)
        cmb_strict = cmb_strict.sort_values(["buy_date", "buy_hhmm", "exit_date"]).reset_index(drop=True)
        for idx_c in range(1, len(cmb_strict)):
            p_r, c_r = cmb_strict.iloc[idx_c - 1], cmb_strict.iloc[idx_c]
            assert (c_r["buy_date"], int(c_r["buy_hhmm"])) > (p_r["exit_date"], int(p_r["exit_hhmm"])), (t_lbl, p_r.to_dict(), c_r.to_dict())
        out[f"{t_lbl}_strict228"] = _fill_add_stats(cmb_strict)
    return out


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    aux = pickle.load(open(f"{PART2_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20, all_dts = aux["sh300"], aux["ew20_daily"], aux["all_dts"]

    skel_mask = df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)
    pool = df[skel_mask].copy().reset_index(drop=True)
    sc, fm = compute_scorecard_v1(pool)
    pool["score"] = sc.values

    all_sig = pd.read_csv(f"{OUT_DIR}/all_scored_signals_v1.csv")
    all_sig["c6"] = all_sig["c6"].astype(str).str.zfill(6)
    slot_A = pd.read_csv(f"{OUT_DIR}/ledger_v1_A.csv")
    slot_A["c6"] = slot_A["c6"].astype(str).str.zfill(6)
    slot_S = pd.read_csv(f"{OUT_DIR}/ledger_v1_S.csv")
    slot_S["c6"] = slot_S["c6"].astype(str).str.zfill(6)

    print("[1/5] Yearly breakdown & Delisted stock contribution audit...")
    tr_A_raw = all_sig[all_sig["score"] >= 78.0]
    tr_S_raw = all_sig[all_sig["score"] >= 88.0]
    yr_A = yearly_full_table(tr_A_raw, sh300, ew20)
    yr_S = yearly_full_table(tr_S_raw, sh300, ew20)
    for lbl, yt in [("A_78", yr_A), ("S_88", yr_S)]:
        print(f"  [{lbl} Yearly]: " + " | ".join(f"{y}:1s={v['nav_1s']}x(N={v['n_1s']},WR={v.get('wr_1s',0)}%,cap10={v['cap10m']}x,MDD={v.get('mdd_1s',0)}%,exHS={v.get('ex_hs300_pp',0):+.0f}pp)" for y, v in yt.items()))

    dl_all = all_sig[all_sig["dl"] == 1][["sig_date", "buy_date", "exit_date", "c6", "name", "score", "net_ret", "exit_reason"]]
    dl_A = slot_A[slot_A["dl"] == 1][["buy_date", "exit_date", "c6", "name", "score", "net_ret_eval", "exit_reason"]]
    dl_S = slot_S[slot_S["dl"] == 1][["buy_date", "exit_date", "c6", "name", "score", "net_ret_eval", "exit_reason"]]
    print("  [Delisted 20cm in skeleton pool]:", len(dl_all), "rows | in 1-slot A:", len(dl_A), "| in 1-slot S:", len(dl_S))
    print(dl_all.to_string(index=False))

    print("\n[2/5] Statistical Anti-Overfitting Audit (HLZ t, DSR, CSCV PBO, Monkey, +-20% MC/Exit Plateau)...")
    ov_A = run_overfitting_audit("A_78", pool, fm, sc.to_numpy(), 78.0, all_sig, sh300, all_dts)
    ov_S = run_overfitting_audit("S_88", pool, fm, sc.to_numpy(), 88.0, all_sig, sh300, all_dts)
    for ov in (ov_A, ov_S):
        print(f"  [{ov['label']}] HLZ_t={ov['hlz_t_trade']} (daily={ov['hlz_t_daily']}) | DSR(M30/M150)={ov['dsr_M30']}/{ov['dsr_M150']} | "
              f"PBO_wide={ov['cscv_pbo_S8']['pbo_pct']}%/{ov['cscv_pbo_S10']['pbo_pct']}% PBO_loc={ov['cscv_pbo_local_S8']['pbo_pct']}%/{ov['cscv_pbo_local_S10']['pbo_pct']}% PBO_q14={ov['cscv_pbo_q14_S8']['pbo_pct']}% | Monkey_p={ov['monkey_p']} | "
              f"WeightMC_p10={ov['weight_mc_200']['full_p10']}x (OOS_p10={ov['weight_mc_200']['oos_p10']}x) | "
              f"Exit_pm20_pass={ov['exit_param_pm20_plateau']['pass_rate_pct']}% | Boot5%={ov['bootstrap_5pct_excess_pct']:+.2f}%")

    print("\n[3/5] Running 2025-01-01 Physical Raw-Data Truncation Rebuild...")
    trunc_res = physical_truncation_rebuild_audit(slot_A, slot_S)
    print("  [TRUNCATION PASS]:", trunc_res)

    print("\n[4/5] Running kline_cache.db Open Check & Physical Integrity Assertions...")
    k_int = kline_and_integrity_audit(slot_A, slot_S, all_sig)
    print("  [KLINE & INTEGRITY PASS]:", k_int)

    print("\n[5/5] Running V19.1 10cm 5-Strategy Empty-Slot Insertion Test (priority=6)...")
    v191_res = v191_empty_slot_test(all_sig, sh300)
    print("  [V19.1 SLOT TEST]:", json.dumps(v191_res, ensure_ascii=False))

    summary = {
        "strategy_name": "20cm_首板深水错杀反抽_V1.0",
        "is_window": "2021-01-04 ~ 2024-08-31",
        "oos_window": "2024-09-01 ~ 2026-11-23",
        "hard_skeleton": "20cm(30/688/689), list_age>10, close>=2, PIT non-ST(<09:00), tox90d==0(<09:00), reg10d==0(<09:00), T0 non-yizi first ZT, amount>=1e8, mkt20_zt<16, T+1 open [-10.0%,-3.0%]",
        "thresholds": {"A_tier": 78, "S_tier": 88},
        "exit_cfg": FINAL_EXIT_CFG,
        "metrics": {
            "A_78": eval_full_suite(tr_A_raw, sh300, ew20),
            "S_88": eval_full_suite(tr_S_raw, sh300, ew20),
            "A_78_PureT2": eval_full_suite(sim_exit_tree(pool[pool["score"] >= 78.0], {"b3_tp_mode": "none"}), sh300, ew20),
        },
        "yearly": {"A_78": yr_A, "S_88": yr_S},
        "delisted_audit": {
            "pool_hits": dl_all.to_dict("records"),
            "slot_A_hits": dl_A.to_dict("records"),
            "slot_S_hits": dl_S.to_dict("records"),
        },
        "overfitting_audit": {"A_78": ov_A, "S_88": ov_S},
        "truncation_20250101": trunc_res,
        "kline_and_integrity": k_int,
        "v191_empty_slot_test": v191_res,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/v1_final_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Saved v1_final_summary.json in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
