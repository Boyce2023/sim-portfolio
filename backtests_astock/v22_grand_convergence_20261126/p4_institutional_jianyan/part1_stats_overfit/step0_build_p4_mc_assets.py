#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step0_build_p4_mc_assets.py — Pre-build clean, read-only assets for V22.0 P4 Part 1 audit:
  1. Vectorized & parity-verified 4to5 full candidate pool (380+ rows covering open_pct [1.5%, 9.2%] & all strict_scores),
     with decomposed 26-column scorecard factor weight matrix + rich_bars / b5m / hold_states for continuous threshold & weight MC.
  2. Pre-filtered 3to4 DirA affected subset (only D1_zt & D2_risk7>=1 entries) for continuous DirA guard MC ([6.4%, 9.6%]).
  3. Pre-built invariant V21 strategy pools (20cm, 2to3, high, 1to2) for ultra-fast end-to-end MC bundle simulation.
Zero yfinance (D12). Read-only on V20/V21/RD038/RD048/RD049/P1A/P2/P3.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import pickle
import sys
import time
import warnings
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
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
os.makedirs(CACHE_DIR, exist_ok=True)

for p in (RD038, RD049, P1A, P2, P3):
    if p not in sys.path:
        sys.path.insert(0, p)

import _v22_engine as v22
import _p1a_common as cm1a
import run_dirA_4to5_to_3to4 as dirA
import run_dirB_3to4_to_4to5 as dirB

MAX_DT = "2026-11-16"

FACTOR_NAMES = [
    "w_lock_sweet", "w_lock_ok", "w_lock_bad",
    "w_hr_ge25", "w_hr_ge22",
    "w_maxb_4", "w_maxb_5", "w_maxb_ge6",
    "w_sole", "w_top1", "w_crowd",
    "w_d4_s34_sole", "w_held_3to4", "w_d4_strong_open", "w_obc_to",
    "w_quant_sell", "w_inst_sell", "w_top_yz_new", "w_lh_ge3",
    "w_plate_3b", "w_px_gt20", "w_nuke", "w_f47_reb",
    "w_mon_posthol", "w_thu_fri", "w_mo_1_5",
]


def decompose_4to5_score_row(r: dict, holders: dict, df_strict_tox: pd.DataFrame) -> dict:
    """Extract exact strict_tox/hard-gate flags and 26-dim nominal weight vector matching score_fixed_4to5."""
    c6_val = str(r["code"]).zfill(6)
    bd = str(r["buy_date"])[:10]
    d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    t_sub = df_strict_tox[
        (df_strict_tox["sec_code"] == c6_val)
        & (df_strict_tox["pub_datetime_cst"] >= d90)
        & (df_strict_tox["pub_datetime_cst"] <= bd + " 09:25:00")
    ]
    fail_tox = bool(not t_sub.empty)
    fail_reg = bool(r.get("f_s_reg_10d", False) or (float(r.get("has_stock_reg", 0) or 0) > 0))
    fail_d4_blown = bool(r.get("d4_blown_pm_5m", False) or r.get("d4_blown_pm_proxy", False))
    buyable = bool(r.get("buyable_open") is True)
    hr_pit = float(r.get("tighter_headroom_pit", 0.0) or 0.0)
    op_pct = float(r.get("open_pct", 0.0) or 0.0)

    w = np.zeros(len(FACTOR_NAMES), dtype=float)
    raw_h = holders.get(c6_val, [])
    sd = str(r.get("sig_date", bd))[:10]
    h_list = [x for x in raw_h if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sd]
    if h_list:
        lock_top10 = float(max(h_list, key=lambda x: str(x[1]))[2])
    else:
        h_dict = [x for x in raw_h if isinstance(x, dict) and str(x.get("ann_date", "")) <= sd]
        lock_top10 = float(h_dict[-1].get("top10_ratio", 0.0)) if h_dict else float(r.get("lock_top10", 0.0) or 0.0)
    real_mcap = float(r.get("real_free_mcap", 20.0) or 20.0)
    if (lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0):
        w[0] = 8.0
    elif (lock_top10 >= 45.0) or (real_mcap >= 45.0):
        w[1] = 3.0
    elif (lock_top10 < 45.0) and (real_mcap < 45.0):
        w[2] = -8.0

    if hr_pit >= 0.25:
        w[3] = 6.0
    elif hr_pit >= 0.22:
        w[4] = 4.0

    max_b = int(r.get("mkt_max_board_prev", 0) or 0)
    if max_b == 4:
        w[5] = 5.0
    elif max_b == 5:
        w[6] = 2.0
    elif max_b >= 6:
        w[7] = -5.0

    is_sole = int(r.get("is_sole_4b", 0) or 0) == 1
    if is_sole:
        w[8] = 6.0
    elif int(r.get("is_top1_4b_open", 0) or 0) == 1 and int(r.get("b4_rival_cnt", 0) or 0) < 2:
        w[9] = 3.0
    else:
        w[10] = -5.0

    d4_s34 = float(r.get("d4_v34_score", -999) or -999)
    if (82.0 <= d4_s34 <= 89.0) and is_sole:
        w[11] = 5.0
    if bool(r.get("is_held_3to4", False)):
        w[12] = 4.0
    d4_op = float(r.get("d4_open_pct", 0.0) or 0.0)
    d4_buyable = bool(r.get("d4_buyable_open", True))
    d3_yizi = bool(r.get("d3_prev_is_yizi", False))
    if ((d4_op > 0.092) or (not d4_buyable) or d3_yizi) and (0.020 <= op_pct <= 0.060):
        w[13] = 3.0
    obc = int(r.get("open_board_count", 0) or 0)
    d3_obc = int(r.get("d3_open_board_count", 0) or 0)
    to_r = float(r.get("to_ratio_d4_d3", 1.0) or 1.0)
    if (obc >= 1) and (d3_obc >= 1) and (0.70 <= to_r <= 1.35):
        w[14] = 3.0

    if int(r.get("f_d4_quant_sell", 0) or 0) >= 1:
        w[15] = -5.0
    if int(r.get("f52_d4_inst_sell", 0) or 0) >= 1:
        w[16] = -3.0
    if bool(r.get("f50_d4_top_yz_new_buy", False)):
        w[17] = -3.0
    if int(r.get("f51_d4_lh_cnt", 0) or 0) >= 3:
        w[18] = -6.0
    if int(r.get("plate_3b_cnt", 0) or 0) >= 1:
        w[19] = -6.0
    if float(r.get("px_d4", 0.0) or 0.0) > 20.0:
        w[20] = -6.0
    if int(r.get("d4_mkt_nuke_cnt", 0) or 0) >= 1:
        w[21] = -3.0
    if float(r.get("f47_reb_zt_r10", 0.0) or 0.0) >= 0.20:
        w[22] = 6.0
    dow = int(r.get("dow", 0) or 0)
    if dow == 1 or bool(r.get("is_post_holiday_or_mon_pit", False)):
        w[23] = 6.0
    elif dow in (4, 5):
        w[24] = -3.0
    mo = int(r.get("buy_month", 0) or 0)
    if mo in (1, 5):
        w[25] = -6.0

    return {
        "buyable_ok": buyable,
        "no_tox_ok": not fail_tox,
        "no_reg_ok": not fail_reg,
        "no_d4blown_ok": not fail_d4_blown,
        "hr_pit": hr_pit,
        "open_pct": op_pct,
        "w_vec": w,
        "nom_strict_score": float(100.0 + w.sum()) if (buyable and not fail_tox and not fail_reg and not fail_d4_blown and hr_pit >= 0.12 and 0.020 <= op_pct <= 0.075) else -999.0,
    }


def build_4to5_full_assets(bench_df, sh2, sz2, cal_dts, cal_5y):
    print("[Step 0.1] Building full 4to5 MC candidate assets (all buyable open_pct [1.5%, 9.2%])...", flush=True)
    df_e = pd.read_parquet(f"{dirB.P3_DIR}/w2_4to5_enriched_master.parquet")
    df_e = df_e[df_e["buy_date"].astype(str).str[:10] <= MAX_DT].copy().reset_index(drop=True)

    with open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
        holders = json.load(f)
    holders = {c6: [rec for rec in lst if str(rec[0])[:10] <= MAX_DT] for c6, lst in holders.items()}

    df_tox_all = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_tox_all = df_tox_all[df_tox_all["pub_datetime_cst"].astype(str) <= MAX_DT + " 23:59:59"].copy()
    df_real_tox = df_tox_all[df_tox_all["title"].astype(str).str.contains(dirB.TOX_RE)].copy()
    df_strict_tox = df_tox_all[df_tox_all["title"].astype(str).str.contains(dirB.TOX_STRICT_RE)].copy()

    sc_cols = [
        "dt", "c6", "open", "high", "low", "close", "open_pct", "ret_1d",
        "is_zt", "hit_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "is_st_pit", "is_20cm",
        "prev_streak", "streak", "turn_pct", "real_turn_pct_t1", "lock_top10_pct_pre",
        "free_mcap_yi_t1", "amount_yi_t1", "hr10d_space_t1", "hr30d_space_t1",
        "tox_reg_30d_pre", "abn_notice_30d_pre", "d1_open_board_cnt_t1",
        "d1_first_seal_hhmm_t1", "lhb_on_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
        "lhb_has_quant_t1", "kpl_in_t1", "kpl_zt3_t1",
    ]
    flt_sc = ((ds.field("prev_streak") >= 4) | (ds.field("dt") >= "2026-11-08")) & (ds.field("dt") <= MAX_DT)
    sc_ds = ds.dataset(f"{dirB.WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    df_sc = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=sc_cols, filter=flt_sc, batch_size=65536, use_threads=False).to_batches()], ignore_index=True)
    df_sc["dt"] = df_sc["dt"].astype(str)
    df_sc["c6"] = df_sc["c6"].astype(str)

    codes_needed = set(df_e["code"].astype(str).str.zfill(6))
    codes_needed |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= MAX_DT) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))

    df_hyd = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=["dt", "c6", "kpl_in_t1", "kpl_zt3_t1", "real_turn_pct_t1", "lock_top10_pct_pre", "d1_first_seal_hhmm_t1"], filter=ds.field("c6").isin(sorted(codes_needed)) & (ds.field("dt") <= MAX_DT), batch_size=65536, use_threads=False).to_batches()], ignore_index=True).drop_duplicates(["dt", "c6"])
    df_hyd["dt"] = df_hyd["dt"].astype(str)
    df_hyd["c6"] = df_hyd["c6"].astype(str)

    df_mk = pd.read_parquet(f"{dirB.WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")
    df_mk = df_mk[df_mk["trade_date"] <= MAX_DT].copy()

    # Load daily + 5m bars for ALL buyable 4to5 open_pct in [0.015, 0.095]
    cand_mask_pre = (df_e["buyable_open"] == True) & (df_e["open_pct"] >= 0.015) & (df_e["open_pct"] <= 0.095)
    b6_codes = set(df_e[cand_mask_pre]["code"].astype(str).str.zfill(6))
    b6_codes |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= MAX_DT) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))

    rich_bars = dirB.load_daily_bars_rich(b6_codes, max_dt=MAX_DT)
    bar_lu = {(c, cb["dts"][i]): (float(cb["open"][i]), float(cb["close"][i]), float(cb["adjf"][i])) for c, cb in rich_bars.items() for i in range(len(cb["dts"]))}
    b5m = cm1a.load_merged_5m_bars(b6_codes, max_dt=MAX_DT)

    df_ext = dirB.build_extension_20261110_20261124(list(df_e.columns), df_sc, df_mk, holders, df_real_tox, rich_bars, cal_dts, max_dt=MAX_DT)
    if not df_ext.empty:
        df_e = pd.concat([df_e, df_ext], ignore_index=True)

    df_e["code6"] = df_e["code"].astype(str).str.zfill(6)
    df_e = df_e.merge(df_hyd.rename(columns={"dt": "buy_date", "c6": "code6"}), on=["buy_date", "code6"], how="left")
    df_e["kpl_in_t1"] = df_e["kpl_in_t1"].fillna(0)
    df_e["prev_real_to"] = df_e["prev_real_to"].fillna(df_e["real_turn_pct_t1"]).fillna(20.0)
    df_e["lock_top10"] = np.where(df_e["lock_top10_pct_pre"].notna() & (df_e["lock_top10_pct_pre"] > 0), df_e["lock_top10_pct_pre"], df_e["lock_top10"])

    # Keep all buyable candidates in wide open_pct range [0.015, 0.095]
    b6_wide = df_e[(df_e["buyable_open"] == True) & (df_e["open_pct"] >= 0.015) & (df_e["open_pct"] <= 0.095)].copy().reset_index(drop=True)
    # Hydrate buy_price_val from rich_bars when B6_auc_sweet_2_7_px is NaN
    bpx_list = []
    for r in b6_wide.itertuples(index=False):
        px = getattr(r, "B6_auc_sweet_2_7_px", np.nan)
        if pd.notna(px) and float(px) > 0:
            bpx_list.append(float(px))
        else:
            cb = rich_bars.get(r.code6)
            bd = str(r.buy_date)[:10]
            bpx_list.append(float(cb["open"][cb["dt_idx"][bd]]) if (cb is not None and bd in cb["dt_idx"]) else 0.0)
    b6_wide["buy_price_val"] = bpx_list
    b6_wide = b6_wide[b6_wide["buy_price_val"] > 0].copy().reset_index(drop=True)

    # Set fallback exit_date / ret_E4_020 for non-B6 rows
    b6_wide["exit_date"] = b6_wide["exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].fillna(MAX_DT).astype(str)
    b6_wide["ret_E4_020"] = pd.to_numeric(b6_wide["ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"], errors="coerce").fillna(0.0)

    b6_wide = dirB.build_pos20_d0_and_xq_pit(b6_wide, rich_bars, max_dt=MAX_DT)
    risk_ctx = dirB.build_daily_7factor_hold_map(b6_codes, df_mk, df_sc, rich_bars, max_dt=MAX_DT)
    hold_states = dirB.compute_4to5_hold_states(b6_wide, rich_bars, risk_ctx, max_dt=MAX_DT)

    # Filter out rows that cannot pass basic non-numeric gates (tox / reg / d4_blown) & decompose weights
    decomp = [decompose_4to5_score_row(r.to_dict(), holders, df_strict_tox) for _, r in b6_wide.iterrows()]
    keep_idx = [
        i for i, d in enumerate(decomp)
        if d["buyable_ok"] and d["no_tox_ok"] and d["no_reg_ok"] and d["no_d4blown_ok"]
    ]
    b6_clean = b6_wide.iloc[keep_idx].copy().reset_index(drop=True)
    decomp_clean = [decomp[i] for i in keep_idx]

    # Pre-verify nominal strict_score parity vs dirB.score_fixed_4to5
    for i, (_, r) in enumerate(b6_clean.iterrows()):
        sc_ref, _ = dirB.score_fixed_4to5(r.to_dict(), holders, df_strict_tox)
        assert abs(sc_ref - decomp_clean[i]["nom_strict_score"]) < 1e-9, f"Score mismatch at {i}: {sc_ref} vs {decomp_clean[i]['nom_strict_score']}"

    # Pre-simulate E4_DtDefer for ALL clean rows (invariant across MC perturbations!)
    records = []
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    for i, r in enumerate(b6_clean.to_dict("records")):
        c6 = r["code6"]
        bd = str(r["buy_date"])[:10]
        if bd < cal_5y[0] or bd > MAX_DT:
            continue
        ed_e4, r30_e4, ehh_e4, r20_e4 = dirB.sim_4to5_exit_unified(
            r, rich_bars.get(c6), b5m, sh2, sz2, hold_states.get((c6, bd), {}), "E4_DtDefer", fee=cm1a.FEE_MAIN
        )
        if ed_e4 > MAX_DT:
            continue
        # Build exact MTM segs for E4_DtDefer at 0.30%
        tmp_df = pd.DataFrame([{
            "buy_date": bd, "exit_date": ed_e4, "code": c6,
            "net_ret": float(r30_e4), "buy_price": float(r["buy_price_val"]),
        }])
        mtm_json_e4 = cm1a.build_mtm_pairs(tmp_df, cal_5y, bar_lu, ret_col="net_ret", px_col="buy_price")[0]
        mtm_segs_e4 = v22.w2.mtm_json_to_segs(mtm_json_e4, idx_5y, True, float(r30_e4), float(r30_e4))
        records.append({
            "row_dict": r,
            "c6": c6,
            "name": str(r["name"]),
            "buy_date": bd,
            "buy_hhmm": 925,
            "buy_price_val": float(r["buy_price_val"]),
            "hr_pit": decomp_clean[i]["hr_pit"],
            "open_pct": decomp_clean[i]["open_pct"],
            "w_vec": decomp_clean[i]["w_vec"],
            "nom_strict_score": decomp_clean[i]["nom_strict_score"],
            "e4_exit_date": ed_e4,
            "e4_exit_hhmm": int(ehh_e4),
            "e4_ret_030": float(r30_e4),
            "e4_mtm_segs": mtm_segs_e4,
        })

    # Keep only slimmed rich_bars & b5m for codes in records
    used_codes = {rec["c6"] for rec in records}
    slim_bars = {c: rich_bars[c] for c in used_codes if c in rich_bars}
    slim_b5m = {k: v for k, v in b5m.items() if k[0] in used_codes}
    slim_hstates = {(rec["c6"], rec["buy_date"]): hold_states.get((rec["c6"], rec["buy_date"]), {}) for rec in records}
    slim_bar_lu = {k: v for k, v in bar_lu.items() if k[0] in used_codes}

    print(f"  4to5 clean wide pool: {len(records)} candidates (from {len(b6_wide)} wide B6). Parity check...", flush=True)
    # Parity check against v22_dirb_ledgers_full SJ114_E4_DtDefer and SJ114_7f_DtDefer
    dirb_pkg = pickle.load(open(f"{P3}/_cache/v22_dirb_ledgers_full.pkl", "rb"))["ledgers"]
    ref_e4 = dirb_pkg["SJ114_E4_DtDefer"]["raw"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    got_e4 = pd.DataFrame([
        {"buy_date": x["buy_date"], "code": x["c6"], "net_ret_030": x["e4_ret_030"], "exit_date": x["e4_exit_date"]}
        for x in records
        if x["hr_pit"] >= 0.12 and 0.020 <= x["open_pct"] <= 0.075 and x["nom_strict_score"] >= 114.0
    ]).sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(got_e4) == len(ref_e4), f"E4 len mismatch {len(got_e4)} vs {len(ref_e4)}"
    assert (got_e4["code"] == ref_e4["code"]).all()
    assert np.max(np.abs(got_e4["net_ret_030"] - ref_e4["net_ret_030"])) < 1e-10
    print("  4to5 E4_DtDefer exact parity: PASS (diff < 1e-10)", flush=True)

    return {
        "records": records,
        "factor_names": FACTOR_NAMES,
        "rich_bars": slim_bars,
        "b5m": slim_b5m,
        "hold_states": slim_hstates,
        "bar_lu": slim_bar_lu,
        "sh2": sh2,
        "sz2": sz2,
    }


def build_dirA_affected_assets(cal_dts: list[str]) -> dict:
    """Extract only 3to4 entries where D1 is ZT & D2 has risk7>=1 (the ONLY rows affected by DirA thr)."""
    print("[Step 0.2] Building DirA parametric 3to4 assets...", flush=True)
    with open(f"{dirA.F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache_a = pickle.load(f)
    states_a = dirA.efe.precompute_trade_day_states(cache_a, min_score=78.0)
    target_codes = {e["code"] for e in cache_a["buy_entries"] if e["skel"] and e["sc_v40"] >= 78.0 and e["buy_px"] is not None}
    daily_ctx_a = dirA.load_daily_context_pit(target_codes, max_dt=MAX_DT)

    affected_entries = []
    affected_codes = set()
    for e in cache_a["buy_entries"]:
        if (not e["skel"]) or (e["sc_v40"] < 90.0) or (e["buy_px"] is None):
            continue
        c6, pos = e["code"], e["pos"]
        cb = cache_a["code_bars_ext"][c6]
        if bool(cb["is_zt"][pos]) and pos + 1 < len(cb["dts"]):
            st_d2 = states_a.get(e["idx"], {}).get(pos + 1, {})
            if dirA._risk7_pts(st_d2) >= 1:
                affected_entries.append(e)
                affected_codes.add(c6)

    slim_code_bars = {c: cache_a["code_bars_ext"][c] for c in affected_codes}
    slim_bars_5m = {k: v for k, v in cache_a["bars_5m_map"].items() if k[0] in affected_codes}
    slim_states = {e["idx"]: states_a[e["idx"]] for e in affected_entries}
    slim_dctx = {
        "by_c": {c: daily_ctx_a["by_c"][c] for c in affected_codes if c in daily_ctx_a["by_c"]},
        "dmap": {k: SimpleNamespace(**v._asdict()) for k, v in daily_ctx_a["dmap"].items() if k[0] in affected_codes},
        "bar_lu": {k: v for k, v in daily_ctx_a["bar_lu"].items() if k[0] in affected_codes},
    }
    print(f"  DirA affected entries (D1_zt & D2_risk7>=1): {len(affected_entries)} across {len(affected_codes)} codes", flush=True)
    return {
        "entries": affected_entries,
        "code_bars_ext": slim_code_bars,
        "bars_5m_map": slim_bars_5m,
        "states": slim_states,
        "daily_ctx": slim_dctx,
    }


def main():
    t0 = time.time()
    bench_df, sh2, sz2, _, _ = cm1a.load_bench_and_indices(max_dt=MAX_DT)
    cal_dts = bench_df["trade_date"].tolist()
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache_base = pickle.load(f)
    cal_5y = cache_base["cal_5y"]

    assets_4to5 = build_4to5_full_assets(bench_df, sh2, sz2, cal_dts, cal_5y)
    assets_dira = build_dirA_affected_assets(cal_5y)

    # Precompute invariant V21 strategy pools (20cm, 2to3, high, 1to2)
    print("[Step 0.3] Precomputing invariant V21 strategy pools (20cm, 2to3, high, 1to2)...", flush=True)
    pool6_v21, _ = v22.eng.build_bundle_pools(cache_base, v22.CFG_V21, fee_mode="030")
    inv_pool4 = pool6_v21[pool6_v21["strategy"].isin(["20cm", "2to3", "high", "1to2"])].copy().reset_index(drop=True)
    inv_trig_dts = {st: set(inv_pool4[inv_pool4["strategy"] == st]["buy_date"]) for st in ("high", "1to2")}

    pkg = {
        "cal_dts": cal_dts,
        "assets_4to5": assets_4to5,
        "assets_dira": assets_dira,
        "inv_pool4": inv_pool4,
        "inv_trig_dts": inv_trig_dts,
    }
    out_pkl = f"{CACHE_DIR}/p4_mc_assets.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(pkg, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[Step 0 DONE in {time.time()-t0:.1f}s | RSS={v22.rss_mb()} MB] Saved {out_pkl}", flush=True)


if __name__ == "__main__":
    main()
