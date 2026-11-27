#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Wave 2 Step 0: Build clean local caches in p3_v22_grand_assembly/_cache/:
  1. All 4to5 DirB ledgers (Fix120 / SJ114 / SJ114_XQLt6 x E4_Base / E_V41_7f_d70 x NoDefer / DtDefer)
     for BOTH max_date='2026-11-16' and max_date='2024-12-31' (physical truncation proof).
  2. Extended T-1 official SSE/SZSE margin eligibility cache covering V20, V21, P2_R_OPT, and 4to5.
  3. Merged 5m intraday low lookup for accurate intraday MMR auditing.
Strictly ZERO yfinance (D12), SQLite read-only (?mode=ro), zero edits to production V20/V21.
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
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import requests

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
P1A = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p1a_3to4_4to5_mutual"
P2 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p2_rd049_falsekill_audit"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

for p in (RD038, RD049, P1A, P2):
    if p not in sys.path:
        sys.path.insert(0, p)

import _p1a_common as cm1a
import run_dirB_3to4_to_4to5 as dirB
import _rd038_engine as eng
import _rd049_common as cm49
import step2_targeted_rescue_and_truncation as p2s


def build_dirb_ledgers_for_cutoff(max_dt: str) -> dict:
    """Build exact 4to5 raw & slot ledgers (E4 vs DtDefer) strictly <= max_dt."""
    bench_df, sh2, sz2, csi, _ = cm1a.load_bench_and_indices(max_dt=max_dt)
    cal_dts = bench_df["trade_date"].tolist()
    df_e = pd.read_parquet(f"{dirB.P3_DIR}/w2_4to5_enriched_master.parquet")
    df_e = df_e[df_e["buy_date"].astype(str).str[:10] <= max_dt].copy().reset_index(drop=True)

    with open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
        holders = json.load(f)
    holders = {c6: [rec for rec in lst if str(rec[0])[:10] <= max_dt] for c6, lst in holders.items()}

    df_tox_all = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_tox_all = df_tox_all[df_tox_all["pub_datetime_cst"].astype(str) <= max_dt + " 23:59:59"].copy()
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
    b5m = cm1a.load_merged_5m_bars(b6_codes, max_dt=max_dt)

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

    specs = [
        ("Fix120_E4", "FixPIT_120", m_f120, "E4_Base", "fixed_score"),
        ("Fix120_E4_DtDefer", "FixPIT_120", m_f120, "E4_DtDefer", "fixed_score"),
        ("Fix120_7f", "FixPIT_120", m_f120, "E_V41_7f_d70", "fixed_score"),
        ("Fix120_7f_DtDefer", "FixPIT_120", m_f120, "E_V41_7f_d70_DtDefer", "fixed_score"),
        ("SJ114_E4", "StrictJianchi_114", m_sj114, "E4_Base", "strict_score"),
        ("SJ114_E4_DtDefer", "StrictJianchi_114", m_sj114, "E4_DtDefer", "strict_score"),
        ("SJ114_7f", "StrictJianchi_114", m_sj114, "E_V41_7f_d70", "strict_score"),
        ("SJ114_7f_DtDefer", "StrictJianchi_114", m_sj114, "E_V41_7f_d70_DtDefer", "strict_score"),
        ("SJ114_XQLt6_E4", "StrictJianchi_114", m_sj114 & m_xq6, "E4_Base", "strict_score"),
        ("SJ114_XQLt6_E4_DtDefer", "StrictJianchi_114", m_sj114 & m_xq6, "E4_DtDefer", "strict_score"),
        ("SJ114_XQLt6_7f", "StrictJianchi_114", m_sj114 & m_xq6, "E_V41_7f_d70", "strict_score"),
        ("SJ114_XQLt6_7f_DtDefer", "StrictJianchi_114", m_sj114 & m_xq6, "E_V41_7f_d70_DtDefer", "strict_score"),
    ]
    ledgers = {}
    summary = {}
    for nm, ttag, emask, exm, scol in specs:
        r = dirB.eval_4to5_variant(nm, "V22_4TO5", ttag, b6, emask, exm, rich_bars, b5m, sh2, sz2, hold_states, bench_df, cal_dts, bar_lu, max_dt, score_col=scol, tie_col=None)
        rdf = r["raw_df"].copy()
        sdf = r["slot_df"].copy()
        if not rdf.empty:
            rdf["mtm_pairs_json"] = cm1a.build_mtm_pairs(rdf, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price")
            rdf["net_ret_080"] = cm1a.convert_fee(rdf["net_ret_020"].to_numpy(float), 0.0020, 0.0080)
            rdf["buy_price_val"] = rdf["buy_price"].astype(float)
        if not sdf.empty:
            sdf["net_ret_080"] = cm1a.convert_fee(sdf["net_ret_020"].to_numpy(float), 0.0020, 0.0080)
            sdf["buy_price_val"] = sdf["buy_price"].astype(float)
        ledgers[nm] = {"raw": rdf, "slot": sdf}
        summary[nm] = r["windows"]

    del df_sc, df_mk, df_hyd, df_tox_all, df_real_tox, df_strict_tox, rich_bars, b5m, hold_states, b6
    pa.default_memory_pool().release_unused()
    gc.collect()
    return {"ledgers": ledgers, "summary": summary}


def extend_margin_eligibility(cache: dict, reg: pd.DataFrame, dirb_ledgers: dict) -> dict:
    """Extend RD049 T-1 official SSE/SZSE margin cache to cover P2_R_OPT and all 4to5 pairs."""
    with open(f"{RD049}/_cache/rd049_margin_eligibility_cache.json", encoding="utf-8") as f:
        mc = json.load(f)
    sz_sets = dict(mc["sz_date_sets"])
    sh_sets = dict(mc["sh_date_sets"])
    pair_elig = dict(mc["pair_elig"])

    dts_all = sorted(reg["trade_date"].astype(str).str[:10].unique().tolist())
    prev_dt_map = {dts_all[i]: dts_all[i - 1] for i in range(1, len(dts_all))}

    reg2 = cm49.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")
    c_p2 = p2s.apply_rescue_filter(cache, reg2, pos_cut=0.50, pry_mkt_cut=50.0, pry_dt_climax=100.0)
    tr_v21_p2 = eng.run_bundle_sim(c_p2, cm49.CFG_V21, fee_mode="030")["trades_df"]
    tr_v20_p2 = eng.run_bundle_sim(c_p2, cm49.CFG_V20, fee_mode="030")["trades_df"]
    dirA_raw = pd.read_parquet(f"{P1A}/dirA_pass_Risk7D2_Tight80_raw.parquet")

    pairs_all = set()
    for df_x in [tr_v21_p2, tr_v20_p2, cache["pools_ext"]["3to4"], dirA_raw] + [v["raw"] for v in dirb_ledgers.values()]:
        if df_x is not None and not df_x.empty:
            for r in df_x.itertuples(index=False):
                pairs_all.add((str(r.code).zfill(6), str(r.buy_date)[:10]))

    todo_sz, todo_sh = set(), set()
    for c6, bd in pairs_all:
        pd1 = prev_dt_map.get(bd)
        if not pd1:
            continue
        if c6.startswith(("00", "30")) and pd1 not in sz_sets:
            todo_sz.add(pd1)
        elif c6.startswith(("60", "68")) and pd1 not in sh_sets:
            todo_sh.add(pd1)

    print(f"  Margin fetch needed: SZ={len(todo_sz)} dates, SH={len(todo_sh)} dates", flush=True)

    def fetch_sz(dt):
        df = ak.stock_margin_underlying_info_szse(date=dt.replace("-", ""))
        if df is None or df.empty:
            return dt, []
        m = df["融资标的"].astype(str).str.upper() == "Y"
        return dt, sorted(df.loc[m, "证券代码"].astype(str).str.zfill(6).unique().tolist())

    if todo_sz:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for f in as_completed([ex.submit(fetch_sz, d) for d in sorted(todo_sz)]):
                dt, codes = f.result()
                sz_sets[dt] = codes

    url = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
    hdrs = {"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"}

    def fetch_sh(dt):
        dt8 = dt.replace("-", "")
        sess = requests.Session()
        codes = set()
        for pno in (1, 2):
            r = sess.get(url, params={
                "isPagination": "true", "tabType": "mxtype", "detailsDate": dt8,
                "stockCode": "", "pageHelp.pageSize": "2000", "pageHelp.pageNo": str(pno),
                "pageHelp.beginPage": str(pno), "pageHelp.endPage": str(pno + 5),
            }, headers=hdrs, timeout=12).json()
            res = r.get("result") or []
            for row in res:
                codes.add(str(row.get("stockCode", "")).zfill(6))
            if len(res) < 2000:
                break
        return dt, sorted(codes)

    if todo_sh:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for f in as_completed([ex.submit(fetch_sh, d) for d in sorted(todo_sh)]):
                dt, codes = f.result()
                sh_sets[dt] = codes

    for c6, bd in sorted(pairs_all):
        k = f"{c6}|{bd}"
        pd1 = prev_dt_map.get(bd)
        if not pd1:
            pair_elig[k] = False
        elif c6.startswith(("00", "30")):
            pair_elig[k] = bool(c6 in set(sz_sets.get(pd1, [])))
        elif c6.startswith(("60", "68")):
            pair_elig[k] = bool(c6 in set(sh_sets.get(pd1, [])))
        else:
            pair_elig[k] = False

    out_path = f"{CACHE_DIR}/v22_margin_eligibility_ext.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"pair_elig": pair_elig, "sz_date_sets": sz_sets, "sh_date_sets": sh_sets}, f, ensure_ascii=False)
    return {"total_pairs": len(pair_elig), "sz_dates": len(sz_sets), "sh_dates": len(sh_sets)}


def build_f5_low_lookup(codes: set[str]) -> dict:
    """Build exact 5m intraday min-low before/after cutoffs for MMR audit."""
    f5_low_lu = {}
    b5m = cm1a.load_merged_5m_bars(codes, max_dt="2026-11-16")
    cuts = (935, 940, 945, 950, 955, 1000, 1015, 1020, 1030, 1130, 1345, 1350, 1355, 1400, 1405, 1410, 1455)
    for (c6, dt), arr in b5m.items():
        if arr is None or len(arr) == 0:
            continue
        hh = arr[:, 0].astype(int)
        lo = arr[:, 3].astype(float)
        for cut in cuts:
            ma = hh >= cut
            if ma.any():
                f5_low_lu[(c6, dt, "after", cut)] = float(np.min(lo[ma]))
            mb = hh <= cut
            if mb.any():
                f5_low_lu[(c6, dt, "before", cut)] = float(np.min(lo[mb]))
    with open(f"{CACHE_DIR}/v22_5m_low_lu.pkl", "wb") as f:
        pickle.dump(f5_low_lu, f, protocol=pickle.HIGHEST_PROTOCOL)
    return f5_low_lu


def main():
    t0 = time.time()
    print("[Step 0.1] Rebuilding DirB 4to5 ledgers (full 2026-11-16 & trunc 2024-12-31)...", flush=True)
    res_full = build_dirb_ledgers_for_cutoff("2026-11-16")
    # Parity assertions vs P1A audit
    s_full = res_full["summary"]
    assert abs(s_full["SJ114_E4"]["FULL_5Y"]["nav"] - 24.4855) < 0.001
    assert abs(s_full["SJ114_E4_DtDefer"]["FULL_5Y"]["nav"] - 17.3731) < 0.001
    assert abs(s_full["SJ114_7f"]["FULL_5Y"]["nav"] - 25.6190) < 0.001
    assert abs(s_full["SJ114_7f_DtDefer"]["FULL_5Y"]["nav"] - 18.1774) < 0.001
    assert abs(s_full["SJ114_XQLt6_7f"]["FULL_5Y"]["nav"] - 29.4000) < 0.001
    assert abs(s_full["Fix120_E4"]["FULL_5Y"]["nav"] - 9.3298) < 0.001
    assert abs(s_full["Fix120_E4_DtDefer"]["FULL_5Y"]["nav"] - 7.7353) < 0.001
    assert abs(s_full["Fix120_7f"]["FULL_5Y"]["nav"] - 9.5793) < 0.001
    assert abs(s_full["Fix120_7f_DtDefer"]["FULL_5Y"]["nav"] - 7.9422) < 0.001
    print("  DirB Full Parity Checks: ALL 9 PASSED!", flush=True)

    with open(f"{CACHE_DIR}/v22_dirb_ledgers_full.pkl", "wb") as f:
        pickle.dump(res_full, f, protocol=pickle.HIGHEST_PROTOCOL)

    res_trunc = build_dirb_ledgers_for_cutoff("2024-12-31")
    with open(f"{CACHE_DIR}/v22_dirb_ledgers_trunc2024.pkl", "wb") as f:
        pickle.dump(res_trunc, f, protocol=pickle.HIGHEST_PROTOCOL)

    # Check DirB 2024-12-31 truncation zero diff
    for k in res_full["ledgers"]:
        sf = res_full["ledgers"][k]["slot"]
        st = res_trunc["ledgers"][k]["slot"]
        sf24 = sf[sf["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        st24 = st[st["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        assert len(sf24) == len(st24), f"DirB trunc count diff on {k}"
        if len(sf24):
            d_r = float(np.max(np.abs(sf24["net_ret"].to_numpy(float) - st24["net_ret"].to_numpy(float))))
            assert d_r == 0.0, f"DirB trunc ret diff on {k}: {d_r}"
    print("  DirB 2024-12-31 Physical Truncation Checks: ALL 12 PASSED (max_abs_diff=0.0)!", flush=True)

    print("[Step 0.2] Extending T-1 official SSE/SZSE margin eligibility cache...", flush=True)
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    m_stat = extend_margin_eligibility(cache, reg, res_full["ledgers"])
    print("  Extended Margin Cache:", m_stat, flush=True)

    print("[Step 0.3] Building merged 5m intraday low lookup for MMR...", flush=True)
    codes_all = set()
    for dfp in cache["pools_ext"].values():
        codes_all |= set(dfp["code"].astype(str).str.zfill(6))
    for v in res_full["ledgers"].values():
        codes_all |= set(v["raw"]["code"].astype(str).str.zfill(6))
    f5_lu = build_f5_low_lookup(codes_all)
    print(f"[Step 0 DONE in {time.time()-t0:.1f}s] f5_low_lu keys={len(f5_lu)}", flush=True)


if __name__ == "__main__":
    main()
