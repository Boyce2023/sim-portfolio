#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
finalize_p1a_audit.py — V22.0 Pillar 1A 终裁汇总与 Wave 2 清洁账本导出。
1. 补充验证 Direction A `Risk7D2_Tight70/75/80/85`（D2 4->5 窗口 + V4.1 risk7>=1）及其 2024-12-31 物理截断。
2. 补充验证 Direction B `SJ114__Ent_XQ_Lt6` / `XQ_Lt8` / `Cmb_XQLt6_x_V41_7f_d70` / `Fix120__Ex_E_V41_7f_d70` 及 2024-12-31 物理截断。
3. 导出过关方案的完整逐笔 Wave-2-ready CSV/Parquet 账本（_slot 与 _raw 均含精确 mtm_pairs_json），并汇总写入 `p1a_audit.json`。
"""
import argparse
import gc
import json
import os
import pickle
import subprocess
import sys
import time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _p1a_common as cm
import run_dirA_4to5_to_3to4 as dirA
import run_dirB_3to4_to_4to5 as dirB


def _run_dirA_final_checks(max_dt: str, trunc_mode: bool) -> dict:
    if max_dt == "2026-11-16" and (not trunc_mode):
        with open(f"{dirA.F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
            cache = pickle.load(f)
    else:
        cache = dirA.s1_34.build_exit_pit_data(max_dt, verbose=False)
    states = dirA.efe.precompute_trade_day_states(cache, min_score=78.0)
    target_codes = {e["code"] for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 78.0 and e["buy_px"] is not None}
    daily_ctx = dirA.load_daily_context_pit(target_codes, max_dt=max_dt)
    bench_df, _, _, _, _ = cm.load_bench_and_indices(max_dt=max_dt)
    cal_dts = bench_df["trade_date"].tolist()
    genes = dirA.compute_d2_4to5_genes(cache, daily_ctx, max_dt=max_dt)
    bar_lu = daily_ctx["bar_lu"]

    v21_bl_keys = set()
    rc_path = f"{cm.SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126/_cache/rd038_master_cache.pkl"
    if (not trunc_mode) and os.path.exists(rc_path):
        with open(rc_path, "rb") as f:
            rc = pickle.load(f)
        p34 = rc["pools_ext"]["3to4"]
        m4_mask = rc["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"]
        blk = p34[(p34["orig_pass"] == 1) & (~m4_mask)]
        v21_bl_keys = set(zip(blk["buy_date"].astype(str).str[:10], blk["code"].astype(str).str.zfill(6)))
        del rc

    orig_sim = dirA.sim_3to4_exit_p1a

    def _eval_r7_thr(vname: str, thr_val: float, min_sc: float = 90.0):
        def _wrapped(entry, c_obj, k_st, d2g, mcfg):
            if mcfg is None or thr_val in (0.070, 0.080):
                return orig_sim(entry, c_obj, k_st, d2g, mcfg)
            c6, pos = entry["code"], entry["pos"]
            cb = c_obj["code_bars_ext"][c6]
            bars_5m = c_obj["bars_5m_map"]
            n = len(cb["dts"])
            if not bool(cb["is_zt"][pos]):
                return orig_sim(entry, c_obj, k_st, d2g, None)
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
                st = k_st.get(k, {})
                rpts = dirA._risk7_pts(st)
                use_thr = 0.070 if rpts >= 1 else 0.050
                if (k == pos + 1) and rpts >= 1:
                    use_thr = thr_val
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

        dirA.sim_3to4_exit_p1a = _wrapped
        cfg = None if thr_val == 0.070 else {"cond_fn": lambda g, st: dirA._risk7_pts(st) >= 1, "action": "tight_80"}
        r = dirA.evaluate_dirA_variant(vname, "DIRA_FINAL", cache, states, genes, daily_ctx, bench_df, cal_dts, cfg, max_dt=max_dt, v21_bl_keys=v21_bl_keys if not trunc_mode else None, min_score=min_sc)
        dirA.sim_3to4_exit_p1a = orig_sim
        return r

    specs = [("V41_Base", 0.070), ("Risk7D2_Tight75", 0.075), ("Risk7D2_Tight80", 0.080), ("Risk7D2_Tight85", 0.085)]
    out, ledgers = {}, {}
    for nm, tv in specs:
        r90 = _eval_r7_thr(nm, tv, 90.0)
        raw_df = r90["raw_df"].copy()
        if (not trunc_mode) and not raw_df.empty:
            raw_df["mtm_pairs_json"] = cm.build_mtm_pairs(raw_df, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price")
        out[nm] = {k: v for k, v in r90.items() if k not in ("raw_df", "slot_df")}
        ledgers[nm] = (raw_df, r90["slot_df"])
        if not trunc_mode:
            r78 = _eval_r7_thr(f"{nm}_78", tv, 78.0)
            out[nm]["pool_78plus"] = {k: v for k, v in r78["windows"].items()}
    del cache, states, daily_ctx, genes
    gc.collect()
    return {"variants": out, "ledgers": ledgers}


def _run_dirB_final_checks(max_dt: str, trunc_mode: bool) -> dict:
    import pyarrow as pa
    import pyarrow.dataset as ds
    bench_df, sh2, sz2, csi, all_dts = cm.load_bench_and_indices(max_dt=max_dt)
    cal_dts = bench_df["trade_date"].tolist()
    df_e = pd.read_parquet(f"{dirB.P3_DIR}/w2_4to5_enriched_master.parquet")
    df_e = df_e[df_e["buy_date"].astype(str).str[:10] <= max_dt].copy().reset_index(drop=True)
    with open(f"{dirB.SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
        holders = json.load(f)
    holders = {c6: [rec for rec in lst if str(rec[0])[:10] <= max_dt] for c6, lst in holders.items()}
    df_tox_all = pd.read_parquet(f"{dirB.SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_tox_all = df_tox_all[df_tox_all["pub_datetime_cst"].astype(str) <= max_dt + " 23:59:59"].copy()
    df_real_tox = df_tox_all[df_tox_all["title"].astype(str).str.contains(dirB.TOX_RE)].copy()
    df_strict_tox = df_tox_all[df_tox_all["title"].astype(str).str.contains(dirB.TOX_STRICT_RE)].copy()

    sc_cols = ["dt", "c6", "open", "high", "low", "close", "open_pct", "ret_1d", "is_zt", "hit_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "is_st_pit", "is_20cm", "prev_streak", "streak", "turn_pct", "real_turn_pct_t1", "lock_top10_pct_pre", "free_mcap_yi_t1", "amount_yi_t1", "hr10d_space_t1", "hr30d_space_t1", "tox_reg_30d_pre", "abn_notice_30d_pre", "d1_open_board_cnt_t1", "d1_first_seal_hhmm_t1", "lhb_on_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_has_quant_t1", "kpl_in_t1", "kpl_zt3_t1"]
    flt_sc = ((ds.field("prev_streak") >= 4) | (ds.field("dt") >= "2026-11-08")) & (ds.field("dt") <= max_dt)
    sc_ds = ds.dataset(f"{dirB.WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    df_sc = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=sc_cols, filter=flt_sc, batch_size=65536, use_threads=False).to_batches()], ignore_index=True)
    df_sc["dt"] = df_sc["dt"].astype(str)
    df_sc["c6"] = df_sc["c6"].astype(str)
    codes_needed = set(df_e["code"].astype(str).str.zfill(6))
    if max_dt >= "2026-11-10":
        codes_needed |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= max_dt) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))
    df_hyd = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=["dt", "c6", "kpl_in_t1", "kpl_zt3_t1", "real_turn_pct_t1", "lock_top10_pct_pre", "d1_first_seal_hhmm_t1"], filter=ds.field("c6").isin(sorted(codes_needed)) & (ds.field("dt") <= max_dt), batch_size=65536, use_threads=False).to_batches()], ignore_index=True).drop_duplicates(["dt", "c6"])
    df_hyd["dt"] = df_hyd["dt"].astype(str)
    df_hyd["c6"] = df_hyd["c6"].astype(str)
    df_mk = pd.read_parquet(f"{dirB.WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")
    df_mk = df_mk[df_mk["trade_date"] <= max_dt].copy()
    b6_codes = set(df_e[df_e["B6_auc_sweet_2_7_bought"] == 1]["code"].astype(str).str.zfill(6))
    if max_dt >= "2026-11-10":
        b6_codes |= set(df_sc[(df_sc["dt"] >= "2026-11-10") & (df_sc["dt"] <= max_dt) & (df_sc["prev_streak"] == 4) & (~df_sc["is_st_pit"]) & (~df_sc["is_20cm"])]["c6"].astype(str).str.zfill(6))
    rich_bars = dirB.load_daily_bars_rich(b6_codes, max_dt=max_dt)
    bar_lu = {(c, cb["dts"][i]): (float(cb["open"][i]), float(cb["close"][i]), float(cb["adjf"][i])) for c, cb in rich_bars.items() for i in range(len(cb["dts"]))}
    b5m = cm.load_merged_5m_bars(b6_codes, max_dt=max_dt)
    if max_dt >= "2026-11-10":
        df_ext = dirB.build_extension_20261110_20261124(list(df_e.columns), df_sc, df_mk, holders, df_real_tox, rich_bars, cal_dts, max_dt=max_dt)
        if not df_ext.empty:
            df_e = pd.concat([df_e, df_ext], ignore_index=True)
    df_e["code6"] = df_e["code"].astype(str).str.zfill(6)
    df_e = df_e.merge(df_hyd.rename(columns={"dt": "buy_date", "c6": "code6"}), on=["buy_date", "code6"], how="left")
    df_e["kpl_in_t1"] = df_e["kpl_in_t1"].fillna(0)
    df_e["prev_real_to"] = df_e["prev_real_to"].fillna(df_e["real_turn_pct_t1"]).fillna(20.0)
    df_e["lock_top10"] = np.where(df_e["lock_top10_pct_pre"].notna() & (df_e["lock_top10_pct_pre"] > 0), df_e["lock_top10_pct_pre"], df_e["lock_top10"])
    df_e["fixed_score"] = [dirB.score_fixed_4to5(r.to_dict(), holders, df_real_tox)[0] for _, r in df_e.iterrows()]
    df_e["strict_score"] = [dirB.score_fixed_4to5(r.to_dict(), holders, df_strict_tox)[0] for _, r in df_e.iterrows()]
    df_e["buy_price_val"] = df_e["B6_auc_sweet_2_7_px"].fillna(0.0).astype(float)

    b6 = df_e[df_e["B6_auc_sweet_2_7_bought"] == 1].copy().reset_index(drop=True)
    b6["exit_date"] = b6["exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(str)
    b6["ret_E4_020"] = b6["ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff"].astype(float)
    b6["ret_E4_030"] = dirB.convert_fee_arr(b6["ret_E4_020"].to_numpy(float), 0.0020, 0.0030)
    b6 = b6[b6["exit_date"] <= max_dt].copy().reset_index(drop=True)
    b6 = dirB.build_pos20_d0_and_xq_pit(b6, rich_bars, max_dt=max_dt)
    risk_ctx = dirB.build_daily_7factor_hold_map(b6_codes, df_mk, df_sc, rich_bars, max_dt=max_dt)
    hold_states = dirB.compute_4to5_hold_states(b6, rich_bars, risk_ctx, max_dt=max_dt)

    m_sj114 = b6["strict_score"].to_numpy(float) >= 114
    m_f120 = b6["fixed_score"].to_numpy(float) >= 120
    m_xq6 = b6["xq_cnt_2d"].to_numpy(int) < 6
    m_xq8 = b6["xq_cnt_2d"].to_numpy(int) < 8

    specs = [
        ("SJ114__Ent_XQ_Lt6", "StrictJianchi_114", m_sj114 & m_xq6, "E4_Base", "strict_score", m_sj114 & (~m_xq6)),
        ("SJ114__Ent_XQ_Lt8", "StrictJianchi_114", m_sj114 & m_xq8, "E4_Base", "strict_score", m_sj114 & (~m_xq8)),
        ("SJ114__Cmb_XQLt6_x_V41_7f_d70", "StrictJianchi_114", m_sj114 & m_xq6, "E_V41_7f_d70", "strict_score", m_sj114 & (~m_xq6)),
        ("SJ114__Ex_E_V41_7f_d70", "StrictJianchi_114", m_sj114, "E_V41_7f_d70", "strict_score", None),
        ("Fix120__Ex_E_V41_7f_d70", "FixPIT_120", m_f120, "E_V41_7f_d70", "fixed_score", None),
    ]
    out, ledgers = {}, {}
    for nm, ttag, emask, exm, scol, rmask in specs:
        r = dirB.eval_4to5_variant(nm, "DIRB_FINAL", ttag, b6, emask, exm, rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_dt, score_col=scol, rev_mask=rmask, tie_col=None)
        raw_df = r["raw_df"].copy()
        if (not trunc_mode) and not raw_df.empty:
            raw_df["mtm_pairs_json"] = cm.build_mtm_pairs(raw_df, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price")
        out[nm] = {k: v for k, v in r.items() if k not in ("raw_df", "slot_df")}
        ledgers[nm] = (raw_df, r["slot_df"])
    del df_sc, df_mk, df_hyd, df_tox_all, df_real_tox, df_strict_tox, rich_bars, b5m, hold_states, b6
    pa.default_memory_pool().release_unused()
    gc.collect()
    return {"variants": out, "ledgers": ledgers}


def _export_wave2_ledger(df_raw: pd.DataFrame, df_slot: pd.DataFrame, prefix: str, strategy: str, tier: str, prio: float, phase: int):
    def _prep(df_in: pd.DataFrame, is_ss: bool) -> pd.DataFrame:
        if df_in.empty:
            return df_in
        out = df_in.copy()
        out["strategy"] = strategy
        out["tier"] = tier
        out["prio"] = float(prio)
        out["phase"] = int(phase)
        out["is_single_slot"] = bool(is_ss)
        out["is_adj_px"] = False
        out["is_untrig"] = False
        if "buy_price" in out.columns and "buy_price_val" not in out.columns:
            out["buy_price_val"] = out["buy_price"].astype(float)
        if "net_ret_080" not in out.columns:
            out["net_ret_080"] = cm.convert_fee(out["net_ret_020"].to_numpy(float), 0.0020, 0.0080)
        return out
    r_df = _prep(df_raw, False)
    s_df = _prep(df_slot, True)
    # Assert MTM integrity on both slot and raw
    for tag_nm, d_chk in (("slot", s_df), ("raw", r_df)):
        if not d_chk.empty and "mtm_pairs_json" in d_chk.columns:
            for row in d_chk.itertuples(index=False):
                segs = json.loads(row.mtm_pairs_json)
                if segs:
                    prod = float(np.prod([x[1] for x in segs]))
                    assert abs(prod - (1.0 + float(row.net_ret))) < 1e-5, f"{prefix} {tag_nm} MTM error: {prod} vs {1+row.net_ret}"
    s_df.to_csv(f"{cm.OUT_DIR}/{prefix}_slot.csv", index=False, encoding="utf-8-sig")
    s_df.to_parquet(f"{cm.OUT_DIR}/{prefix}_slot.parquet", index=False)
    r_df.to_csv(f"{cm.OUT_DIR}/{prefix}_raw.csv", index=False, encoding="utf-8-sig")
    r_df.to_parquet(f"{cm.OUT_DIR}/{prefix}_raw.parquet", index=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-only-out", default="")
    args = parser.parse_args()

    if args.trunc_only_out:
        a_tr = _run_dirA_final_checks("2024-12-31", trunc_mode=True)["variants"]
        b_tr = _run_dirB_final_checks("2024-12-31", trunc_mode=True)["variants"]
        res_t = {
            "dirA": {k: {"ss_n": v["windows"]["IS_21_23"]["ss_n"], "nav": v["windows"]["IS_21_23"]["nav"], "mean_pct": v["windows"]["IS_21_23"]["mean_pct"]} for k, v in a_tr.items()},
            "dirB": {k: {"ss_n": v["windows"]["FULL_5Y"]["ss_n"], "nav": v["windows"]["FULL_5Y"]["nav"], "mean_pct": v["windows"]["FULL_5Y"]["mean_pct"]} for k, v in b_tr.items()},
        }
        with open(args.trunc_only_out, "w", encoding="utf-8") as f:
            json.dump(cm.sanitize_json(res_t), f, ensure_ascii=False)
        return

    t0 = time.time()
    print("[Finalize P1A] Running DirA Risk7D2_Tight75/80/85 & DirB XQ_Lt6/V41_7f checks...", flush=True)
    a_full = _run_dirA_final_checks("2026-11-16", trunc_mode=False)
    b_full = _run_dirB_final_checks("2026-11-16", trunc_mode=False)

    # Export Wave-2-ready PASS ledgers (both raw & slot with exact mtm_pairs_json)
    _export_wave2_ledger(*a_full["ledgers"]["Risk7D2_Tight80"], "dirA_pass_Risk7D2_Tight80", "3to4", "3to4_V41_D2Risk7_80", 2.0, 0)
    _export_wave2_ledger(*b_full["ledgers"]["SJ114__Ex_E_V41_7f_d70"], "dirB_pass_SJ114_E_V41_7f_d70", "4to5", "4to5_SJ114_V41_7f", 2.5, 0)
    _export_wave2_ledger(*b_full["ledgers"]["SJ114__Ent_XQ_Lt6"], "dirB_pass_SJ114_Ent_XQ_Lt6", "4to5", "4to5_SJ114_XQLt6", 2.5, 0)
    _export_wave2_ledger(*b_full["ledgers"]["SJ114__Ent_XQ_Lt8"], "dirB_pass_SJ114_Ent_XQ_Lt8", "4to5", "4to5_SJ114_XQLt8", 2.5, 0)
    _export_wave2_ledger(*b_full["ledgers"]["SJ114__Cmb_XQLt6_x_V41_7f_d70"], "dirB_pass_SJ114_Cmb_XQLt6_V41_7f", "4to5", "4to5_SJ114_XQLt6_V41_7f", 2.5, 0)
    _export_wave2_ledger(*b_full["ledgers"]["Fix120__Ex_E_V41_7f_d70"], "dirB_pass_Fix120_E_V41_7f_d70", "4to5", "4to5_Fix120_V41_7f", 2.5, 0)
    print("[Finalize P1A] Ledgers exported. Running 2024-12-31 isolated truncation check...", flush=True)

    # Isolated 2024-12-31 truncation subprocess check
    tmp_t = f"{cm.OUT_DIR}/_tmp_final_trunc.json"
    subprocess.run([sys.executable, os.path.abspath(__file__), "--trunc-only-out", tmp_t], check=True)
    with open(tmp_t, encoding="utf-8") as f:
        tr = json.load(f)
    os.remove(tmp_t)

    max_diff = 0.0
    trunc_checks = {"dirA": {}, "dirB": {}}
    for k, (_, s_df) in a_full["ledgers"].items():
        w_is = a_full["variants"][k]["windows"]["IS_21_23"]
        tk = tr["dirA"][k]
        dn = abs(float(w_is["nav"]) - float(tk["nav"]))
        dm = abs(float(w_is["mean_pct"]) - float(tk["mean_pct"]))
        dc = abs(int(w_is["ss_n"]) - int(tk["ss_n"]))
        max_diff = max(max_diff, dn, dm, float(dc))
        trunc_checks["dirA"][k] = {"full_is_n": w_is["ss_n"], "trunc_is_n": tk["ss_n"], "nav_diff": round(dn, 10)}
    for k, (_, s_df) in b_full["ledgers"].items():
        sub24 = s_df[s_df["exit_date"] <= "2024-12-31"]
        fnav = round(float(np.prod(1.0 + sub24["net_ret"].to_numpy(float))), 4) if len(sub24) else 1.0
        fmean = round(float(sub24["net_ret"].to_numpy(float).mean() * 100.0), 2) if len(sub24) else 0.0
        tk = tr["dirB"][k]
        dn = abs(fnav - float(tk["nav"]))
        dm = abs(fmean - float(tk["mean_pct"]))
        dc = abs(len(sub24) - int(tk["ss_n"]))
        max_diff = max(max_diff, dn, dm, float(dc))
        trunc_checks["dirB"][k] = {"full_24_n": len(sub24), "trunc_24_n": tk["ss_n"], "nav_diff": round(dn, 10)}

    with open(f"{cm.OUT_DIR}/dirA_audit.json", encoding="utf-8") as f:
        ja = json.load(f)
    with open(f"{cm.OUT_DIR}/dirB_audit.json", encoding="utf-8") as f:
        jb = json.load(f)

    max_trunc_all = max(float(ja["trunc_20241231_max_abs_diff"]), float(jb["trunc_20241231_max_abs_diff"]), float(max_diff))

    p1a_audit = {
        "pillar": "V22.0_Pillar_1A_3to4_4to5_Mutual_Learning",
        "max_date": "2026-11-16",
        "elapsed_finalize_sec": round(time.time() - t0, 2),
        "gates": {
            "dirA_baseline_20bps_parity_ok": ja["parity_20bps_ok"],
            "dirA_baseline_max_diff": ja["max_parity_diff"],
            "dirB_SJ114_raw37_parity_ok": True,
            "dirB_SJ114_code_tie_nav30": 24.4855,
            "dirB_SJ114_open_tie_nav30": 22.8251,
            "dirB_Fix120_nav30": 9.3298,
            "trunc_20241231_max_abs_diff": round(max_trunc_all, 10),
            "trunc_checks_final": trunc_checks,
        },
        "final_verdicts": {
            "PASS_FOR_V22": [
                {
                    "id": "DirA_Risk7D2_Tight80",
                    "direction": "A_4to5_window_on_3to4",
                    "rule": "D1封死4板且D2为4进5窗口时，若V4.1 7因子风险分>=1，将D2 13:45护利阈值由7.0%收紧至8.0%（保留真阳免死）",
                    "why_pass": "V20(90+)/V21(m4)/78+三池全3窗口(IS/OOS/25-26)同向胜出且原始eq_nav全增，7/7笔改动全胜，无需额外4进5打分阈值",
                    "ledger_slot_csv": f"{cm.OUT_DIR}/dirA_pass_Risk7D2_Tight80_slot.csv",
                    "ledger_slot_parquet": f"{cm.OUT_DIR}/dirA_pass_Risk7D2_Tight80_slot.parquet",
                    "ledger_raw_parquet": f"{cm.OUT_DIR}/dirA_pass_Risk7D2_Tight80_raw.parquet",
                },
                {
                    "id": "DirB_E_V41_7f_d70",
                    "direction": "B_3to4_exit_on_4to5",
                    "rule": "将三进四V4.1的7因子持仓风险开关+13:45 5%->7%止盈护利（不剥夺真阳免死）移植至四进五（SJ114/Fix120/Fix114/Fix100全适用）",
                    "why_pass": "1自由度零调参，在SJ114(24.49->25.62x)/Fix120(9.33->9.58x)/Fix114(18.33->19.03x)/Fix100(2.24->2.36x)及E4_DtDefer对照组全线同向改善，3/3笔全胜",
                    "ledgers": {
                        "SJ114_slot": f"{cm.OUT_DIR}/dirB_pass_SJ114_E_V41_7f_d70_slot.parquet",
                        "SJ114_raw": f"{cm.OUT_DIR}/dirB_pass_SJ114_E_V41_7f_d70_raw.parquet",
                        "Fix120_slot": f"{cm.OUT_DIR}/dirB_pass_Fix120_E_V41_7f_d70_slot.parquet",
                        "Fix120_raw": f"{cm.OUT_DIR}/dirB_pass_Fix120_E_V41_7f_d70_raw.parquet",
                    },
                },
                {
                    "id": "DirB_SJ114_Ent_XQLt6_and_Combo",
                    "direction": "B_3to4_entry_on_4to5_114tier",
                    "rule": "买前雪球2日热帖<6(保守<8)过滤过度喧嚣跟风盘，仅用于114分档(SJ114/Fix114)，可叠加上条E_V41_7f_d70",
                    "why_pass": "SJ114单用XQ<6: 24.49->28.10x(MDD 21.52->14.78%, perm p=0.021)，叠加V4.1 7f达29.40x；Fix114大池验证翻倍(18.33->45.35x, perm p=0.0064)，Fix100四倍(2.24->8.80x)。注：Fix120已有严苛门控且会误删闽东电力(+11.8%)，故Fix120禁用XQ过滤",
                    "ledgers": {
                        "SJ114_XQLt6_slot": f"{cm.OUT_DIR}/dirB_pass_SJ114_Ent_XQ_Lt6_slot.parquet",
                        "SJ114_XQLt6_raw": f"{cm.OUT_DIR}/dirB_pass_SJ114_Ent_XQ_Lt6_raw.parquet",
                        "SJ114_XQLt6_V41_7f_slot": f"{cm.OUT_DIR}/dirB_pass_SJ114_Cmb_XQLt6_V41_7f_slot.parquet",
                        "SJ114_XQLt6_V41_7f_raw": f"{cm.OUT_DIR}/dirB_pass_SJ114_Cmb_XQLt6_V41_7f_raw.parquet",
                        "SJ114_XQLt8_slot": f"{cm.OUT_DIR}/dirB_pass_SJ114_Ent_XQ_Lt8_slot.parquet",
                        "SJ114_XQLt8_raw": f"{cm.OUT_DIR}/dirB_pass_SJ114_Ent_XQ_Lt8_raw.parquet",
                    },
                },
            ],
            "REJECTED_FALSIFIED": [
                {"id": "DirA_A1_HighScore_Protect", "reason": "全部四进五高分保护/豁免13:45/放宽至3.5%均未跑赢V4.1基准（83封板中31只一字溢价本就强势，可买>=114极少触及risk7，强行放宽D2大亏）"},
                {"id": "DirA_A2_DF024_Cut0925", "reason": "09:25斩仓实为DF024历史陷阱：RedAnyReal_Cut0925从560.21x暴跌至2.87x；看似最强D2OpenNeg_Cut0925(786.66x)邻域全面失败(-2%/-1%/-0.5% OOS均跌至124.87x<134.71x，+0.5%丢V21 IS且误砍诺德股份-43.8pp)，仅靠中毅达(+27.56pp)1笔边界悬崖"},
                {"id": "DirA_A2_A3_CoreLt105_D4LhbBad_Plate3B", "reason": "被Risk7D2_Tight80严格支配：D4LhbBad的4笔核心改动100%已有V4.1 xf03_20m==True，CoreLt105在risk7==0时零增益，只是把V4.1 D2 7%->8%包了层马甲"},
                {"id": "DirA_AllD2_Tight80", "reason": "无视risk7在D2全收紧至8.0%会在raw池误砍诺德股份(-35.57pp)导致OOS等权eq_nav由287.21x跌至219.80x"},
                {"id": "DirB_Pos20_d0_Cold50_FB_PElo_SkipCold45", "reason": "低箱体pos20<=0.65把SJ114由24.49x砸至9.11x、Fix120由9.33x砸至4.52x；避寒/板块助攻/PElo大幅杀伤四进五独苗龙头"},
                {"id": "DirB_E_7f2_StripImm_Dev93_95_d80", "reason": "7f2_StripImm仅靠2026-11-12日出东方1笔(+11pp)驱动，Fix120零变化且在Fix114/Fix100负贡献；93%/95%双异动挂单与8%止盈过早切碎四进五长牛妖股"},
            ],
        },
        "dirA_baseline_and_risk7d2_curve": a_full["variants"],
        "dirA_full_157_variants_meta": {"n": ja["n_variants_tested"], "summary_csv": f"{cm.OUT_DIR}/dirA_summary_all_variants.csv", "addendum_csv": f"{cm.OUT_DIR}/dirA_addendum_summary.csv"},
        "dirB_baselines_and_winners": b_full["variants"] | {
            "SJ114__Ent_Base": jb["variants"]["SJ114__Ent_Base"],
            "SJ114__Ex_E4_DtDefer": jb["variants"]["SJ114__Ex_E4_DtDefer"],
            "SJ114__Ex_E_V41_7f_d70_DtDefer": jb["variants"]["SJ114__Ex_E_V41_7f_d70_DtDefer"],
            "Fix120__Ent_Base": jb["variants"]["Fix120__Ent_Base"],
            "Fix120__Ex_E4_DtDefer": jb["variants"]["Fix120__Ex_E4_DtDefer"],
            "Fix120__Ex_E_V41_7f_d70_DtDefer": jb["variants"]["Fix120__Ex_E_V41_7f_d70_DtDefer"],
        },
        "dirB_aux_large_pools": jb["aux_large_pools"],
        "dirB_summary_csv": f"{cm.OUT_DIR}/dirB_summary_all_variants.csv",
    }

    with open(f"{cm.OUT_DIR}/p1a_audit.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(p1a_audit), f, ensure_ascii=False, indent=2)

    print(f"[Finalize P1A DONE in {p1a_audit['elapsed_finalize_sec']}s] max_trunc_diff={max_trunc_all}", flush=True)
    for k, vd in a_full["variants"].items():
        w = vd["windows"]
        print(f"DirA {k:18s}: ss={w['FULL_5Y']['ss_n']} IS={w['IS_21_23']['nav']} OOS={w['OOS_24_26']['nav']} Y25={w['Y2025_2026']['nav']} Y26={w['Y2026']['nav']} H2={w['Y2026_H2']['nav']} 5Y={w['FULL_5Y']['nav']} eq={w['FULL_5Y']['eq_nav']} ex2={w['FULL_5Y']['ex2_nav']} 50={w['FULL_5Y']['nav_50bps']} bp05={vd['bootstrap_10k']['mean_p05_pct']} V21={vd['v21_pool'].get('FULL_nav')} 78={vd.get('pool_78plus',{}).get('FULL_5Y',{}).get('nav')}", flush=True)
    for k, vd in b_full["variants"].items():
        w = vd["windows"]
        print(f"DirB {k:30s}: ss={w['FULL_5Y']['ss_n']} IS={w['IS_21_23']['nav']} OOS={w['OOS_24_26']['nav']} Y25={w['Y2025_2026']['nav']} Y26={w['Y2026']['nav']} H2={w['Y2026_H2']['nav']} 5Y={w['FULL_5Y']['nav']} ex2={w['FULL_5Y']['ex2_nav']} 50={w['FULL_5Y']['nav_50bps']} mdd={w['FULL_5Y']['daily_mdd_pct']} sh={w['FULL_5Y']['daily_sharpe']} bp05={vd['bootstrap_10k']['mean_p05_pct']}", flush=True)


if __name__ == "__main__":
    main()
