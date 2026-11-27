#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD049 Step 2: Full Backtest Suite across Modules 1-4:
  - Module 1: Top-5 DD anatomy + 5-tier Traffic Light & 2D Continuous Risk State Machine
  - Module 2: 6x5 Strategy-Regime table, Full-Exposure Dynamic Thresholds, Vol-Parity65 Control, Plateau, De-Singleton
  - Module 3: 3to4 5m execution tightening (cancel cutoffs, honest 09:35 delay, pre-market plate assist)
  - Module 4: 1.5x Margin Simulation (TheoFull & RealEligibleOnly) + Intraday Low MMR + Historical Margin Eligibility
  - Outputs: rd049_audit.json, rd049_grid.csv, rd049_margin_15x_audit.csv, _cache/rd049_curves.npz
Zero yfinance (D12). Peak RSS < 2.2 GB.
"""
import gc
import json
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
CACHE = f"{RD049}/_cache"

for p in (RD038, RD049):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd038_engine as eng
import _rd049_common as cm


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return sanitize_json(obj.tolist())
    return obj


def extract_top5_dd(sim_res: dict, cal_5y: list[str], reg_idx: pd.DataFrame) -> list[dict]:
    dr = sim_res["dr_5y"]
    tr = sim_res["trades_df"]
    nav = np.cumprod(1.0 + dr)
    pk = np.maximum.accumulate(np.concatenate([[1.0], nav]))[1:]
    dd = (pk - nav) / pk
    eps = []
    i = 0
    while i < len(dd):
        if dd[i] > 0:
            pi = max(0, i - 1)
            j = i
            while j < len(dd) and dd[j] > 0:
                j += 1
            ti = i + int(np.argmax(dd[i:j]))
            eps.append((float(dd[ti] * 100.0), cal_5y[pi], cal_5y[ti], cal_5y[j] if j < len(dd) else "未回本"))
            i = j
        else:
            i += 1
    eps.sort(reverse=True)
    out = []
    for rk, (mdd_p, pk_d, tr_d, rec_d) in enumerate(eps[:5], 1):
        sub = tr[(tr["buy_date"] >= pk_d) & (tr["buy_date"] <= tr_d)]
        losers = []
        for r in sub[sub["net_ret"] < 0].sort_values("net_ret").itertuples():
            g = reg_idx.loc[r.buy_date] if r.buy_date in reg_idx.index else {}
            losers.append({
                "buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name,
                "strategy": r.strategy, "tier": r.tier, "score": float(r.score),
                "ret_pct": round(float(r.net_ret * 100.0), 2),
                "light_5": g.get("light_5", ""),
                "X_score": round(float(g.get("X_score", 0.0)), 1),
                "Y_score": round(float(g.get("Y_score", 0.0)), 1),
                "R_union": round(float(g.get("R_union", 0.0)), 1),
                "gz_vs_ma20_t1": round(float(g.get("gz_vs_ma20_t1", 0.0)), 2),
                "gz_dd20_t1": round(float(g.get("gz_dd20_t1", 0.0)), 2),
                "hb2_promo_t1": round(float(g.get("hb2_promo_t1", 0.0)), 3),
                "L1_duanban_damian_t1": round(float(g.get("L1_duanban_damian_t1", 0.0)), 2),
            })
        out.append({"rank": rk, "mdd_pct": round(mdd_p, 2), "peak_date": pk_d, "trough_date": tr_d, "recover_date": rec_d, "losers": losers})
    return out


def compute_vol_parity_65_sizing(sim_res: dict, cache: dict, cal_5y: list[str]) -> tuple[np.ndarray, float]:
    """Academic reference control ONLY: causal expanding strategy downside-vol parity scaled to 65% avg exposure."""
    tr = sim_res["trades_df"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    # Build causal expanding downside std per strategy (only trades with exit_date < t)
    hist_rets = {st: [] for st in ["3to4", "high", "pry", "2to3", "1to2", "20cm"]}
    tr_sorted = tr.sort_values("buy_date").reset_index(drop=True)
    # Pre-seed prior IS median downside std of 0.075 until 5 trades settled
    raw_sizes = []
    settled_ptr = 0
    tr_by_exit = tr.sort_values("exit_date").reset_index(drop=True)

    for r in tr_sorted.itertuples(index=False):
        while settled_ptr < len(tr_by_exit) and tr_by_exit.iloc[settled_ptr]["exit_date"] < r.buy_date:
            sr = tr_by_exit.iloc[settled_ptr]
            hist_rets[sr["strategy"]].append(float(sr["net_ret"]))
            settled_ptr += 1
        h = np.array(hist_rets.get(r.strategy, []), dtype=float)
        if len(h) >= 5:
            neg = h[h < 0]
            dvol = float(np.sqrt(np.mean(neg ** 2))) if len(neg) >= 2 else float(np.std(h, ddof=1))
        else:
            dvol = 0.08
        raw_sizes.append((r.buy_date, r.exit_date, 1.0 / max(0.03, dvol)))

    # Normalize using ONLY IS mean raw_weight so average active sizing ~= 65% (clipped to [0.25, 1.00])
    is_weights = [w for bd, _, w in raw_sizes if bd < "2024-01-01"]
    scale = 0.65 / float(np.mean(is_weights))
    sizing_arr = np.ones(T, dtype=float)
    active_sz = []
    for bd, ed, rw in raw_sizes:
        sz = float(np.clip(rw * scale, 0.25, 1.00))
        active_sz.append(sz)
        bi, ei = idx_5y.get(bd), idx_5y.get(ed)
        if bi is not None and ei is not None:
            sizing_arr[bi : ei + 1] = sz
    return sizing_arr, round(float(np.mean(active_sz) * 100.0), 1)


def main():
    t0 = time.time()
    print("[1/6] Loading caches (RD038 master + RD049 T-1 regime + 5m + margin cache) ...")
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg = pd.read_parquet(f"{CACHE}/rd049_daily_regime_pit.parquet")
    reg2 = cm.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0)
    reg_idx = reg2.set_index("trade_date")
    cal_5y = cache["cal_5y"]

    mc = json.load(open(f"{CACHE}/rd049_margin_eligibility_cache.json", encoding="utf-8"))
    elig_map = mc["pair_elig"]

    # Build lightweight 5m lookup ONLY for 3to4 / V20 / V21 holding-day intraday low checks & honest 935 delay
    f5 = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    f5["dt"] = f5["date"].astype(str).str[:10]
    f5["c6"] = f5["c6"].astype(str).str.zfill(6)

    df34_raw = cache["pools_ext"]["3to4"]
    b5_info = {}
    for r in df34_raw[df34_raw["orig_score"] >= 90].itertuples(index=False):
        bars = f5[(f5["c6"] == str(r.code).zfill(6)) & (f5["dt"] == str(r.buy_date)[:10])].sort_values("hhmm_int")
        if bars.empty:
            continue
        b935 = bars[bars["hhmm_int"] == 935].iloc[0]
        b940 = bars[bars["hhmm_int"] == 940].iloc[0] if not bars[bars["hhmm_int"] == 940].empty else b935
        o935, c935 = float(b935["open"]), float(b935["close"])
        o940, l940 = float(b940["open"]), float(b940["low"])
        pc = o935 / (1.0 + float(r.open_pct))
        zt_approx = round(pc * 1.10, 2)
        b5_info[(str(r.buy_date)[:10], str(r.code).zfill(6))] = {
            "red935": c935 < o935,
            "sealed_940": (o940 >= zt_approx - 0.015) and (l940 >= zt_approx - 0.015),
            "o940": o940,
        }

    # Precompute 5m min-low before/after cutoff lookup for any (c6, dt) in f5
    f5_low_lu = {}
    for (c6, dt), grp in f5.groupby(["c6", "dt"], sort=False):
        hh = grp["hhmm_int"].to_numpy(int)
        lo = grp["low"].to_numpy(float)
        for cut in (935, 940, 945, 950, 955, 1000, 1015, 1020, 1030, 1130, 1455):
            ma = hh >= cut
            if ma.any():
                f5_low_lu[(c6, dt, "after", cut)] = float(np.min(lo[ma]))
            mb = hh <= cut
            if mb.any():
                f5_low_lu[(c6, dt, "before", cut)] = float(np.min(lo[mb]))
    del f5
    gc.collect()

    # Module 1: Top-5 DD Anatomy for V21 & V20 + 6x5 Strategy-Regime Matrix
    print("[2/6] Module 1: Top-5 DD anatomy + 6x5 Strategy-Regime Matrix ...")
    s_v21_base = eng.run_bundle_sim(cache, cm.CFG_V21, fee_mode="030")
    s_v20_base = eng.run_bundle_sim(cache, cm.CFG_V20, fee_mode="030")
    dd_v21 = extract_top5_dd(s_v21_base, cal_5y, reg_idx)
    dd_v20 = extract_top5_dd(s_v20_base, cal_5y, reg_idx)

    pool6, _ = eng.build_bundle_pools(cache, cm.CFG_V21, fee_mode="030")
    pool6["light_5"] = pool6["buy_date"].map(reg_idx["light_5"].to_dict())
    strat_regime_tbl = []
    for st in ["3to4", "high", "pry", "2to3", "1to2", "20cm"]:
        sub = pool6[pool6["strategy"] == st]
        for l5 in ["L1_纯绿畅通", "L2_绿灯内杀", "L3_浅黄预警", "L4_深黄主跌", "L5_红灯地板"]:
            g = sub[sub["light_5"] == l5]
            gis = g[g["buy_date"] < "2024-01-01"]
            goos = g[g["buy_date"] >= "2024-01-01"]
            strat_regime_tbl.append({
                "strategy": st, "light_5": l5,
                "n_all": len(g), "wr_all": round(float((g["net_ret"] > 0).mean() * 100.0), 1) if len(g) else 0.0,
                "mean_all": round(float(g["net_ret"].mean() * 100.0), 2) if len(g) else 0.0,
                "min_all": round(float(g["net_ret"].min() * 100.0), 2) if len(g) else 0.0,
                "n_is": len(gis), "mean_is": round(float(gis["net_ret"].mean() * 100.0), 2) if len(gis) else 0.0,
                "n_oos": len(goos), "mean_oos": round(float(goos["net_ret"].mean() * 100.0), 2) if len(goos) else 0.0,
            })

    # Module 2 & 3: Main Candidate Matrix on V21 and V20 (Full + De-Singleton + Academic Control)
    print("[3/6] Module 2 & 3: Running Candidate Grid (V21 & V20, Full & De-Singleton) ...")
    candidate_specs = [
        ("BASE", dict(mode="base")),
        ("S1_SkipYellow34", dict(mode="skip_yellow", pry_cold=True)),
        ("S2_DynThr_Tier", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=False, pry_cold=True)),
        ("S3_RD049_Tier_Full", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=True)),
        ("S4_RD049_R2D_Full", dict(mode="runion", r0=38, rk=12, raf=45, af03_weak=True, pry_cold=True)),
        ("S5_RD049_Tier_NoPry", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=False)),
        ("M3_OnlyAf03_ALL_Bad", dict(mode="base", af03_all=True, pry_cold=False)),
        ("M3_OnlyAf03_Weak", dict(mode="base", af03_weak=True, pry_cold=False)),
        ("M3_Cancel_0945", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=True, hh_cut=945)),
        ("M3_Cancel_1000", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=True, hh_cut=1000)),
        ("M3_HonestDelay935", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=False, pry_cold=True, honest_delay935=True)),
        ("M3_StrongGap925_Weak", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=False, pry_cold=True, s34_925_weak=True)),
    ]

    grid_rows = []
    sim_store = {}
    windows_def = [
        ("FULL_5Y", "2021-11-16", "2026-11-16"),
        ("IS_2123", "2021-11-16", "2023-12-31"),
        ("OOS_2426", "2024-01-01", "2026-11-16"),
        ("WF_2326", "2023-01-03", "2026-11-16"),
        ("Y2025_2026", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("Y2026_H2", "2026-07-01", "2026-11-16"),
    ]

    for bname, cfg in [("V21", cm.CFG_V21), ("V20", cm.CFG_V20)]:
        for cname, kw in candidate_specs:
            # Full sample
            c_f = cm.apply_rd049_filter(cache, reg_idx, b5_info=b5_info, de_singleton=False, **kw)
            sim_f = eng.run_bundle_sim(c_f, cfg, fee_mode="030")
            nav_f5 = float(np.prod(1.0 + sim_f["dr_5y"]))
            nav_fwf = float(np.prod(1.0 + sim_f["dr_wf"]))
            rel_diff_5y = sim_f["mtm_diff_5y"] / max(1.0, nav_f5)
            rel_diff_wf = sim_f["mtm_diff_wf"] / max(1.0, nav_fwf)
            assert rel_diff_5y < 1e-10 and rel_diff_wf < 1e-10, f"MTM rel mismatch: {bname}_{cname} {rel_diff_5y} {rel_diff_wf}"
            # De-Singleton sample
            c_d = cm.apply_rd049_filter(cache, reg_idx, b5_info=b5_info, de_singleton=True, **kw)
            sim_d = eng.run_bundle_sim(c_d, cfg, fee_mode="030")

            key = f"{bname}_{cname}"
            if cname in ("BASE", "S1_SkipYellow34", "S2_DynThr_Tier", "S3_RD049_Tier_Full", "S4_RD049_R2D_Full", "S5_RD049_Tier_NoPry"):
                sim_store[key] = sim_f

            row = {
                "base_sys": bname, "variant": cname, "mtm_rel_diff_5y": round(rel_diff_5y, 12), "mtm_diff_wf": round(sim_f["mtm_diff_wf"], 9),
                "exposure_mode": "100%_Full",
            }
            for wn, s, e in windows_def:
                mf = cm.compute_window_metrics(sim_f["dr_5y"], sim_f["trades_df"], cal_5y, s, e)
                md = cm.compute_window_metrics(sim_d["dr_5y"], sim_d["trades_df"], cal_5y, s, e)
                for k_m, v_m in mf.items():
                    row[f"{wn}_{k_m}"] = v_m
                if wn in ("FULL_5Y", "OOS_2426"):
                    row[f"DS_{wn}_mdd"] = md["mdd_pct"]
                    row[f"DS_{wn}_sharpe"] = md["sharpe"]
                    row[f"DS_{wn}_nav"] = md["nav"]
            grid_rows.append(row)

        # Academic Control: VolParity_65 & Const_65 on BASE
        sim_base = sim_store[f"{bname}_BASE"]
        sz_vp, avg_vp = compute_vol_parity_65_sizing(sim_base, cache, cal_5y)
        for ctrl_nm, sz_arr, exp_lbl in [
            ("CTRL_VolParity65_Acad", sz_vp, f"Acad_{avg_vp}%"),
            ("CTRL_Const65_Acad", np.full(len(cal_5y), 0.65), "Acad_65.0%"),
        ]:
            row = {"base_sys": bname, "variant": ctrl_nm, "mtm_diff_5y": 0.0, "exposure_mode": exp_lbl}
            for wn, s, e in windows_def:
                mf = cm.compute_window_metrics(sim_base["dr_5y"], sim_base["trades_df"], cal_5y, s, e, sizing_arr=sz_arr)
                for k_m, v_m in mf.items():
                    row[f"{wn}_{k_m}"] = v_m
            row["DS_FULL_5Y_mdd"] = row["FULL_5Y_mdd_pct"]
            row["DS_FULL_5Y_sharpe"] = row["FULL_5Y_sharpe"]
            grid_rows.append(row)

    grid_df = pd.DataFrame(grid_rows)
    grid_df.to_csv(f"{RD049}/rd049_grid.csv", index=False, encoding="utf-8-sig")

    # Parameter Plateau Matrix around S3 (Tier) & S4 (R_union) on V21
    print("[4/6] Running Parameter Plateau Matrix (Tier 27 pts + R_union 18 pts) ...")
    plat_tier = []
    for yc in (40.0, 42.0, 44.0):
        for xsh, xdp in [(16.0, 38.0), (20.0, 42.0), (24.0, 46.0)]:
            r_tmp = cm.build_2d_states(reg, y_cut=yc, x_sh=xsh, x_dp=xdp).set_index("trade_date")
            for d4, d3, d2 in [(10, 6, 6), (12, 9, 9), (14, 10, 10)]:
                cf = cm.apply_rd049_filter(cache, r_tmp, mode="tier", d_l4=d4, d_l3=d3, d_l2=d2, af03_weak=True, pry_cold=True)
                sf = eng.run_bundle_sim(cf, cm.CFG_V21, fee_mode="030")
                m5 = cm.compute_window_metrics(sf["dr_5y"], sf["trades_df"], cal_5y, "2021-11-16", "2026-11-16")
                mo = cm.compute_window_metrics(sf["dr_5y"], sf["trades_df"], cal_5y, "2024-01-01", "2026-11-16")
                plat_tier.append({"yc": yc, "x_sh": xsh, "x_dp": xdp, "d": f"{d4}/{d3}/{d2}", "mdd_5y": m5["mdd_pct"], "sh_5y": m5["sharpe"], "nav_5y": m5["nav"], "mdd_oos": mo["mdd_pct"], "sh_oos": mo["sharpe"]})

    plat_r2d = []
    for r0 in (34.0, 38.0, 42.0):
        for rk in (10.0, 12.0, 14.0):
            for raf in (42.0, 45.0):
                cf = cm.apply_rd049_filter(cache, reg_idx, mode="runion", r0=r0, rk=rk, raf=raf, af03_weak=True, pry_cold=True)
                sf = eng.run_bundle_sim(cf, cm.CFG_V21, fee_mode="030")
                m5 = cm.compute_window_metrics(sf["dr_5y"], sf["trades_df"], cal_5y, "2021-11-16", "2026-11-16")
                mo = cm.compute_window_metrics(sf["dr_5y"], sf["trades_df"], cal_5y, "2024-01-01", "2026-11-16")
                plat_r2d.append({"r0": r0, "rk": rk, "raf": raf, "mdd_5y": m5["mdd_pct"], "sh_5y": m5["sharpe"], "nav_5y": m5["nav"], "mdd_oos": mo["mdd_pct"], "sh_oos": mo["sharpe"]})

    # Module 4: 1.5x Margin Simulation + Intraday Low MMR + Historical Eligibility
    print("[5/6] Module 4: Running 1.5x Margin Simulation & Intraday-Low MMR Audit ...")
    target_keys = ["V20_BASE", "V21_BASE", "V20_S3_RD049_Tier_Full", "V20_S4_RD049_R2D_Full", "V21_S3_RD049_Tier_Full", "V21_S4_RD049_R2D_Full"]
    bar_low_lu = cm.preload_low_bars_for_trades([sim_store[k]["trades_df"] for k in target_keys], cal_5y)

    margin_rows = []
    margin_curves = {}
    margin_details = {}
    for k in target_keys:
        sr = sim_store[k]
        # 1x baseline metrics
        m1x_5 = cm.compute_window_metrics(sr["dr_5y"], sr["trades_df"], cal_5y, "2021-11-16", "2026-11-16")
        m1x_3 = cm.compute_window_metrics(sr["dr_5y"], sr["trades_df"], cal_5y, "2024-01-01", "2026-11-16")
        m1x_wf = cm.compute_window_metrics(sr["dr_5y"], sr["trades_df"], cal_5y, "2023-01-03", "2026-11-16")
        m1x_26 = cm.compute_window_metrics(sr["dr_5y"], sr["trades_df"], cal_5y, "2026-01-01", "2026-11-16")

        # 1.5x TheoFull & 1.5x RealEligibleOnly
        s_theo = cm.simulate_margin_15x(sr, cal_5y, bar_low_lu, f5_low_lu, elig_map, mode="15x_theo_full", annual_rate=0.055)
        s_elig = cm.simulate_margin_15x(sr, cal_5y, bar_low_lu, f5_low_lu, elig_map, mode="15x_elig_only", annual_rate=0.055)

        tr = sr["trades_df"].copy()
        tr["elig"] = [bool(elig_map.get(f"{str(r.code).zfill(6)}|{r.buy_date}", False)) for r in tr.itertuples()]
        tr2526 = tr[tr["buy_date"] >= "2025-01-01"]
        tr26 = tr[tr["buy_date"] >= "2026-01-01"]
        elig_stats = {
            "elig_5y_pct": round(float(tr["elig"].mean() * 100.0), 1),
            "elig_2526_pct": round(float(tr2526["elig"].mean() * 100.0), 1) if len(tr2526) else 0.0,
            "elig_2026_pct": round(float(tr26["elig"].mean() * 100.0), 1) if len(tr26) else 0.0,
            "by_strat": {st: round(float(g["elig"].mean() * 100.0), 1) for st, g in tr.groupby("strategy")},
        }

        margin_curves[f"{k}_1x"] = sr["dr_5y"]
        margin_curves[f"{k}_15x_theo"] = s_theo["dr_lev"]
        margin_curves[f"{k}_15x_elig"] = s_elig["dr_lev"]

        margin_details[k] = {
            "elig_stats": elig_stats,
            "theo_15x": {k2: v2 for k2, v2 in s_theo.items() if k2 not in ("dr_lev", "mmr_df")},
            "elig_15x": {k2: v2 for k2, v2 in s_elig.items() if k2 not in ("dr_lev", "mmr_df")},
        }
        for lev_lbl, m_obj in [
            ("1.0x_Cash", {"elig_pct": elig_stats["elig_5y_pct"], "avg_eff_leverage": 1.0, "min_mmr_pct": 999.0, "n_warn_below_150": 0, "n_liq_below_130": 0,
                           "windows": {"FULL_5Y": m1x_5, "Y3_2426": m1x_3, "WF_2326": m1x_wf, "Y2026": m1x_26}}),
            ("1.5x_TheoFull", s_theo),
            ("1.5x_EligOnly", s_elig),
        ]:
            w = m_obj["windows"]
            margin_rows.append({
                "model": k, "leverage_mode": lev_lbl, "n_trades": len(tr),
                "elig_5y_pct": elig_stats["elig_5y_pct"], "elig_2526_pct": elig_stats["elig_2526_pct"], "elig_2026_pct": elig_stats["elig_2026_pct"],
                "avg_eff_lev": m_obj["avg_eff_leverage"],
                "min_mmr_pct": m_obj["min_mmr_pct"], "n_warn_150": m_obj["n_warn_below_150"], "n_liq_130": m_obj["n_liq_below_130"],
                "5Y_nav": w["FULL_5Y"]["nav"], "5Y_mdd": w["FULL_5Y"]["mdd_pct"], "5Y_sharpe": w["FULL_5Y"]["sharpe"], "5Y_calmar": w["FULL_5Y"]["calmar"],
                "3Y_nav": w["Y3_2426"]["nav"], "3Y_mdd": w["Y3_2426"]["mdd_pct"], "3Y_sharpe": w["Y3_2426"]["sharpe"],
                "WF_nav": w["WF_2326"]["nav"], "WF_mdd": w["WF_2326"]["mdd_pct"],
                "2026_nav": w["Y2026"]["nav"], "2026_mdd": w["Y2026"]["mdd_pct"],
            })

    margin_df = pd.DataFrame(margin_rows)
    margin_df.to_csv(f"{RD049}/rd049_margin_15x_audit.csv", index=False, encoding="utf-8-sig")

    # Save curves for plotting
    np.savez_compressed(
        f"{CACHE}/rd049_curves.npz",
        cal_5y=np.array(cal_5y),
        light_5=np.array([reg_idx.loc[d, "light_5"] for d in cal_5y]),
        r_union=np.array([reg_idx.loc[d, "R_union"] for d in cal_5y]),
        **margin_curves,
    )

    print("[6/6] Saving rd049_audit.json ...")
    audit = sanitize_json({
        "task": "RD049: Full-Exposure Granular Traffic Light + 2D Risk State Machine + 3to4 5m Tightening + 1.5x Margin Audit",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": cm.rss_mb(),
        "d12_yfinance_imported": False,
        "five_tier_day_counts_5y": reg2[reg2["trade_date"].between("2021-11-16", "2026-11-16")]["light_5"].value_counts().to_dict(),
        "top5_dd_anatomy": {"V21_BASE": dd_v21, "V20_BASE": dd_v20},
        "strategy_x_light5_table": strat_regime_tbl,
        "grid_summary": grid_rows,
        "plateau_tier_27pts": {
            "n_points": len(plat_tier),
            "n_mdd_le_30": sum(1 for r in plat_tier if r["mdd_5y"] <= 30.0),
            "mdd_5y_range": [min(r["mdd_5y"] for r in plat_tier), max(r["mdd_5y"] for r in plat_tier)],
            "mdd_oos_range": [min(r["mdd_oos"] for r in plat_tier), max(r["mdd_oos"] for r in plat_tier)],
            "sharpe_5y_range": [min(r["sh_5y"] for r in plat_tier), max(r["sh_5y"] for r in plat_tier)],
            "rows": plat_tier,
        },
        "plateau_r2d_18pts": {
            "n_points": len(plat_r2d),
            "n_mdd_le_30": sum(1 for r in plat_r2d if r["mdd_5y"] <= 30.0),
            "mdd_5y_range": [min(r["mdd_5y"] for r in plat_r2d), max(r["mdd_5y"] for r in plat_r2d)],
            "mdd_oos_range": [min(r["mdd_oos"] for r in plat_r2d), max(r["mdd_oos"] for r in plat_r2d)],
            "sharpe_5y_range": [min(r["sh_5y"] for r in plat_r2d), max(r["sh_5y"] for r in plat_r2d)],
            "rows": plat_r2d,
        },
        "margin_15x_audit": margin_details,
        "margin_15x_table": margin_rows,
    })
    with open(f"{RD049}/rd049_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"[DONE in {time.time()-t0:.1f}s | RSS={cm.rss_mb()} MB]")


if __name__ == "__main__":
    main()
