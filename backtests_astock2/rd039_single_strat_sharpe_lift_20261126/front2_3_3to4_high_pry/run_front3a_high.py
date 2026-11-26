#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-B Front 3A: 高标首阴 V5.1 Unified Intraday Confirmation Conditional Orders
  - 100% Baseline Parity Check (42 trades 14.7494x @ 20bps, WF 31 trades 9.8287x / Sharpe 2.377 / MDD 17.90%)
  - Upgrade 平红开 (24/46 = 52.2%) from 09:25 direct buy to 09:30+ intraday confirmation:
      open * {1.005, 1.010, 1.015, 1.020}, first-5m high breakout (f5_break), f5_hold,
      across cancel cutoffs {0945, 1000, 1030, 1130}, paired with green-open triggers.
  - Evaluates under Matched42CB, CausalCB, NoCB + Velocity Slippage + 30/50/80bps + CSCV PBO + IS->OOS.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import pickle
import sys
import time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _f23_common as cm
from part2_loaders import build_high_full_pool
from v191_dt_defer_helper import defer_eod_limit_down


def eval_high_unified(
    vid: str,
    dfh_all: pd.DataFrame,
    ctx: dict,
    dt_tables: dict,
    red_mode: str,
    red_cancel: int,
    green_mode: str,
    green_cancel: int,
    cb_mode: str = "Matched42CB",
    base_dr_wf: np.ndarray | None = None,
    base_dr_5y: np.ndarray | None = None,
) -> tuple[dict, pd.DataFrame]:
    """
    Simulate High V5.1 with unified conditional confirmation across ALL 52 eligible signals.
    Strictly zero intraday lookahead & strictly T+1.
    """
    bars_5m = ctx["bars_5m"]
    dmap = ctx["dmap"]
    filled_rows = []
    n_elig = len(dfh_all)

    for r in dfh_all.itertuples(index=False):
        c6, bd = r.c6, r.buy_date
        open_d, pre_c, zt_px = float(r.open_d), float(r.pre_c), float(r.zt_px)
        if open_d <= 0 or pre_c <= 0 or zt_px <= 0 or open_d >= zt_px - 0.005:
            continue
        is_rf = bool(r.is_red_flat)
        mode = red_mode if is_rf else green_mode
        cancel_hh = red_cancel if is_rf else green_cancel
        arr = bars_5m.get((c6, bd))

        binfo = None
        if mode == "direct_0925":
            binfo = {"buy_hhmm": 925, "buy_price": round(open_d, 2), "eff_buy_price": round(open_d, 2), "vel_tier": "auction_0925"}
        elif mode.startswith("open_p"):
            step = float(mode.split("_p")[1]) / 1000.0  # open_p005 -> 0.005, open_p010 -> 0.010, open_p015 -> 0.015, open_p020 -> 0.020
            ntrig = round(open_d * (1.0 + step), 2)
            if ntrig < zt_px - 0.005 and arr is not None and len(arr) > 0:
                for bi in range(len(arr)):
                    hh = int(arr[bi, 0])
                    if hh > cancel_hh:
                        break
                    o5, h5, l5 = float(arr[bi, 1]), float(arr[bi, 2]), float(arr[bi, 3])
                    if l5 >= zt_px - 0.01:
                        continue
                    if h5 >= ntrig:
                        bp_pre = round(max(o5, ntrig), 2)
                        if bp_pre < zt_px - 0.005:
                            eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, bi, ntrig, pre_c, zt_px)
                            binfo = {"buy_hhmm": hh, "buy_price": bp_pre, "eff_buy_price": eff_p, "vel_tier": vt}
                        break
        elif mode in ("f5_break", "f5_break_redbar"):
            if arr is not None and len(arr) >= 2:
                h_935, c_935 = float(arr[0, 2]), float(arr[0, 4])
                ok_bar1 = (c_935 >= open_d - 1e-4) if mode == "f5_break_redbar" else True
                if ok_bar1 and h_935 < zt_px - 0.005:
                    for bi in range(1, len(arr)):
                        hh = int(arr[bi, 0])
                        if hh > cancel_hh:
                            break
                        o5, h5, l5 = float(arr[bi, 1]), float(arr[bi, 2]), float(arr[bi, 3])
                        if l5 >= zt_px - 0.01:
                            continue
                        if h5 >= h_935:
                            bp_pre = round(max(o5, h_935), 2)
                            if bp_pre < zt_px - 0.005:
                                eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, bi, h_935, pre_c, zt_px)
                                binfo = {"buy_hhmm": hh, "buy_price": bp_pre, "eff_buy_price": eff_p, "vel_tier": vt}
                            break
        elif mode == "f5_hold_0":
            if arr is not None and len(arr) >= 2:
                c_935 = float(arr[0, 4])
                if c_935 >= open_d - 1e-4:
                    o_940, l_940 = float(arr[1, 1]), float(arr[1, 3])
                    if l_940 < zt_px - 0.01 and o_940 < zt_px - 0.005:
                        eff_p, vt, _ = cm.apply_vel_slip_on_bar(arr, 1, o_940, pre_c, zt_px)
                        binfo = {"buy_hhmm": int(arr[1, 0]), "buy_price": round(o_940, 2), "eff_buy_price": eff_p, "vel_tier": vt}

        if binfo is None:
            continue

        pre_b = float(binfo["buy_price"])
        eff_b = float(binfo["eff_buy_price"])
        # Recompute limit-down deferral using actual pre_b (preserving exact baseline parity)
        if r.dt_deferred:
            nr_tmp = (float(r.pre_defer_e_px) / pre_b) * float(r.adj_ratio) * 0.9980 - 1.0
            ned, neh, nep, _, dt_def = defer_eod_limit_down(
                c6, bd, pre_b, str(r.pre_defer_exit_date), int(r.exit_hhmm) if not r.dt_deferred else 1500,
                float(r.pre_defer_e_px), nr_tmp, dt_tables, 0.0020
            )
            db_b, db_e = dmap[(c6, bd)], dmap[(c6, str(ned))]
            adj_r = float(db_e["adjf"]) / float(db_b["adjf"]) if db_b["adjf"] > 0 else 1.0
            ret_020 = (float(nep) / pre_b) * adj_r * 0.9980 - 1.0
            ret_v020 = (float(nep) / eff_b) * adj_r * 0.9980 - 1.0
            ex_dt, ex_hh, ex_px, eo_flag = str(ned), int(neh), float(nep), bool(neh == 925)
        else:
            ret_020 = round((float(r.exit_price_raw) / pre_b) * float(r.adj_ratio) * 0.9980 - 1.0, 6)
            ret_v020 = round((1.0 + ret_020) * (pre_b / eff_b) - 1.0, 8)
            ex_dt, ex_hh, ex_px, eo_flag = str(r.exit_date), int(r.exit_hhmm), float(r.exit_price), bool(r.eo)

        pre_def_ret = (float(r.pre_defer_e_px) / pre_b) * float(r.adj_ratio) * 0.9980 - 1.0
        filled_rows.append({
            "buy_date": bd,
            "code": c6,
            "name": r.name,
            "is_red_flat": is_rf,
            "buy_hhmm": int(binfo["buy_hhmm"]),
            "buy_price": pre_b,
            "eff_buy_price": eff_b,
            "vel_tier": binfo["vel_tier"],
            "exit_date": ex_dt,
            "exit_hhmm": ex_hh,
            "exit_price": ex_px,
            "eo": eo_flag,
            "b_open_h": bool(binfo["buy_hhmm"] == 925),
            "score": float(r.score),
            "net_ret": float(ret_020),
            "net_ret_020": float(ret_020),
            "net_ret_vel_020": float(ret_v020),
            "net_ret_vel_030": float(cm.fee_adjust(ret_v020, 0.0030)),
            "pre_defer_ret": float(pre_def_ret),
        })

    miss_rate = (n_elig - len(filled_rows)) / max(1, n_elig) * 100.0
    if not filled_rows:
        return {"strategy": "high", "variant_id": vid, "n_5y": 0, "n_wf": 0}, pd.DataFrame()

    df_pool = pd.DataFrame(filled_rows).sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).reset_index(drop=True)
    taken = []
    fd, peo, cl, sk = "", False, 0, False
    for r in df_pool.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
            rv = float(r.net_ret_020)
            rv_cb = float(r.pre_defer_ret) if cb_mode == "Matched42CB" else rv
            if cb_mode in ("Matched42CB", "CausalCB") and sk:
                fd, peo = str(r.exit_date), bool(r.eo)
                if rv_cb > 0.0:
                    sk, cl = False, 0
                continue
            taken.append(r._asdict())
            fd, peo = str(r.exit_date), bool(r.eo)
            if cb_mode in ("Matched42CB", "CausalCB"):
                if rv_cb < -0.02:
                    cl += 1
                    if cl >= 2:
                        sk = True
                elif rv_cb > 0.0:
                    cl = 0

    slot_df = pd.DataFrame(taken)
    res = cm.evaluate_full_suite(ctx, "high", vid, slot_df, miss_rate, base_dr_wf, base_dr_5y)
    return res, slot_df


def main():
    t0 = time.time()
    mh = pd.read_parquet(f"{cm.WAVE1}/pool_high_master_pit.parquet", columns=["code", "buy_date"])
    codes = set(mh["code"].astype(str).str.zfill(6))
    # Union all 52 sc5_1>=88 candidates (including 6 untriggered codes missing from pool_high_master_pit)
    import part2_loaders as p2l
    _src = "\n".join(open(f"{p2l.GOLD_DIR}/sub2_03_golden_relaxation_backtest.py", encoding="utf-8").read().splitlines()[:192])
    _src = _src.replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
    _G = {"__name__": "eng"}
    exec(_src, _G)
    _dfr = _G["dfr"]
    codes |= set(_dfr.loc[_dfr["sc5_1"] >= 88, "code"].astype(str).str.zfill(6))
    del _G, _dfr
    ctx = cm.load_filtered_5m_and_dmap(codes)
    dfh_all = build_high_full_pool(ctx["bars_5m"], ctx["dmap"])
    dt_tables = cm.build_lean_dt_tables(ctx["code_series"])
    print(f"[Front3A High] Pool={len(dfh_all)} (red_flat={int(dfh_all['is_red_flat'].sum())}, green={int((~dfh_all['is_red_flat']).sum())}) | RSS={cm.rss_mb()} MB")

    # 1. Exact Baseline Parity Check
    res_base, sl_base = eval_high_unified("V51_Baseline_Matched42CB", dfh_all, ctx, dt_tables, "direct_0925", 1130, "open_p015", 1130, cb_mode="Matched42CB")
    refh = pd.read_csv(f"{cm.SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_high_v51_clean.csv", dtype={"code": str})
    refh["code"] = refh["code"].str.zfill(6)
    assert len(sl_base) == 42 and list(zip(sl_base["buy_date"], sl_base["code"])) == list(zip(refh["buy_date"], refh["code"]))
    ret_diff = float(np.max(np.abs(sl_base["net_ret_020"].to_numpy() - refh["net_ret"].to_numpy())))
    assert ret_diff < 1e-6, f"High parity diff={ret_diff}"
    base_dr_wf = res_base["dr_wf_030"]
    base_dr_5y = res_base["dr_5y_030"]
    wb = res_base["windows_030"]["WF_2326"]
    print(f"  [Parity PASS] diff={ret_diff:.2e} | 5Y_020={np.prod(1+sl_base['net_ret_020']):.4f}x | WF_030 n={wb['n']} nav={wb['nav']}x sh={wb['sharpe']} mdd={wb['mdd_pct']}%")

    res_base, sl_base = eval_high_unified("V51_Baseline_Matched42CB", dfh_all, ctx, dt_tables, "direct_0925", 1130, "open_p015", 1130, cb_mode="Matched42CB", base_dr_wf=base_dr_wf, base_dr_5y=base_dr_5y)

    results = [res_base]
    slot_map = {"V51_Baseline_Matched42CB": sl_base}

    # Test unified intraday confirmation grid across Matched42CB and CausalCB
    red_modes = ["open_p005", "open_p010", "open_p015", "open_p020", "f5_break", "f5_break_redbar", "f5_hold_0"]
    red_cancels = [945, 1000, 1030, 1130]
    green_modes = ["open_p015", "open_p010", "open_p005", "open_p020", "f5_break"]

    specs = []
    # First sweep red_mode x red_cancel keeping green at open_p015 (11:30)
    for _rm, _gm in [("direct_0925", "open_p015"), ("open_p005", "open_p015"), ("open_p010", "open_p015"), ("open_p010", "open_p010"), ("f5_break", "open_p015")]:
        specs.append((f"NoCB_R_{_rm}_G_{_gm}_c1030", _rm, 1030, _gm, 1030, "NoCB"))
    for cbm in ("Matched42CB", "CausalCB"):
        if cbm == "CausalCB":
            specs.append((f"Base_{cbm}", "direct_0925", 1130, "open_p015", 1130, cbm))
        for rm in red_modes:
            for rc in red_cancels:
                if rm == "f5_hold_0" and rc != 1030:
                    continue
                specs.append((f"Red_{rm}_c{rc}__{cbm}", rm, rc, "open_p015", 1130, cbm))
        # Unified symmetric triggers (same mode & cancel for BOTH red and green!)
        for m in ["open_p005", "open_p010", "open_p015", "open_p020", "f5_break"]:
            for cc in [1000, 1030, 1130]:
                specs.append((f"Uni_{m}_c{cc}__{cbm}", m, cc, m, cc, cbm))
        # Red=open_p005/p010 x Green=open_p005/p010/p015
        for rm in ["open_p005", "open_p010", "open_p015"]:
            for gm in ["open_p005", "open_p010"]:
                specs.append((f"R_{rm}_G_{gm}_c1030__{cbm}", rm, 1030, gm, 1030, cbm))

    for vid, rm, rc, gm, gc_, cbm in specs:
        r, sl = eval_high_unified(vid, dfh_all, ctx, dt_tables, rm, rc, gm, gc_, cbm, base_dr_wf, base_dr_5y)
        results.append(r)
        slot_map[vid] = sl

    mat_wf = {r["variant_id"]: r["dr_wf_030"] for r in results if r.get("dr_wf_030") is not None}
    mat_5y = {r["variant_id"]: r["dr_5y_030"] for r in results if r.get("dr_5y_030") is not None}
    pbo_wf_16 = cm.cscv_pbo(mat_wf, S=16)
    pbo_5y_16 = cm.cscv_pbo(mat_5y, S=16)

    rows_print = []
    for r in results:
        if r.get("n_5y") == 0 or "windows_030" not in r:
            continue
        wf = r["windows_030"]["WF_2326"]
        f5 = r["windows_030"]["FULL_5Y"]
        oos = r["windows_030"]["OOS_2526"]
        y26 = r["windows_030"]["Y2026"]
        h2 = r["windows_030"]["Y26H2"]
        wv = r["windows_vel030"]["WF_2326"]
        rows_print.append({
            "variant_id": r["variant_id"],
            "n_5y": f5["n"], "n_wf": wf["n"], "miss": r["miss_rate_pct"],
            "wr_wf": wf["wr_pct"], "plr_wf": wf["plr"], "mloss_wf": wf["mean_loss_pct"], "le7_wf": wf["big_loss_rate_pct"],
            "nav_wf": wf["nav"], "ex5_wf": wf["ex_top5_nav"], "mdd_wf": wf["mdd_pct"], "sh_wf": wf["sharpe"],
            "sh_vel_wf": wv["sharpe"], "nav_vel_wf": wv["nav"],
            "nav_5y": f5["nav"], "sh_5y": f5["sharpe"], "mdd_5y": f5["mdd_pct"],
            "nav_2526": oos["nav"], "nav_26": y26["nav"], "nav_26h2": h2["nav"],
            "pt_vwf": r["paired_t_wf_vel030"], "pp_vwf": r["paired_p_wf_vel030"],
        })
    df_sum = pd.DataFrame(rows_print).sort_values("sh_vel_wf", ascending=False)
    print("\n=== TOP 20 HIGH VARIANTS BY WF VELOCITY-SLIPPAGE EXACT MTM SHARPE ===")
    print(df_sum.head(20)[["variant_id", "n_5y", "n_wf", "miss", "wr_wf", "nav_wf", "mdd_wf", "sh_wf", "nav_vel_wf", "sh_vel_wf", "nav_2526", "nav_26h2", "pp_vwf"]].to_string(index=False))
    print(f"CSCV PBO (S=16): WF={pbo_wf_16['pbo']} | 5Y={pbo_5y_16['pbo']}")

    out_cache = {
        "results": [{k: v for k, v in r.items() if not k.startswith("dr_")} for r in results],
        "drs_wf": mat_wf,
        "drs_5y": mat_5y,
        "pbo_wf_16": pbo_wf_16,
        "pbo_5y_16": pbo_5y_16,
        "summary_df": df_sum,
        "top_slots": {k: slot_map[k] for k in ["V51_Baseline_Matched42CB"] + df_sum.head(8)["variant_id"].tolist() if k in slot_map},
    }
    with open(f"{cm.CACHE_DIR}/front3a_high.pkl", "wb") as f:
        pickle.dump(out_cache, f)
    print(f"[Front3A DONE in {time.time()-t0:.1f}s] RSS={cm.rss_mb()} MB")


if __name__ == "__main__":
    main()
