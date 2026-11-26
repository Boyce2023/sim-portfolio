#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD036-A Step 1: Prepare strictly-PIT 20cm enriched cache & lean V20.0 6-strategy context
with Peak RSS strictly < 1.8 GB (verified 100% parity: 278 trades / 69,134,091.51x 5Y / 611,729.55x WF).
"""
import gc
import json
import os
import pickle
import resource
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(2)
pa.set_io_thread_count(2)
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import rd036_lib as lib


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def build_lean_untrig_under_2gb(trig_dts_other: dict, cal_5y: list[str]) -> pd.DataFrame:
    """
    Reproduce exact `ut_final` (3to4 / high / 1to2 untriggered conditional orders) WITHOUT loading
    the 1.3GB `part1_cache.pkl` (which spikes to 3.8GB in RAM).
    """
    SIM = lib.SIM
    tpe = lib.tpe
    rows = []

    # 1. 3to4 (>=90, buy_px is None) -> load 656MB pkl, extract rows, free immediately
    p34_pkl = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl"
    with open(p34_pkl, "rb") as f:
        c34 = pickle.load(f)
    cand34 = c34["cand_df"].copy()
    cand34["score"] = c34["sc_v40"]
    d34_dts = trig_dts_other["3to4"]
    u34 = []
    for i in cand34.index:
        bd = str(cand34.loc[i, "buy_date"])[:10]
        if cand34.loc[i, "score"] >= 90.0 and c34["buy_entries"][i]["buy_px"] is None and "2021-11-16" <= bd <= "2026-11-16" and bd not in d34_dts:
            u34.append({
                "buy_date": bd, "buy_hhmm": 935, "exit_date": bd, "exit_hhmm": 1030,
                "code": str(cand34.loc[i, "code"]).zfill(6), "name": str(cand34.loc[i, "name"]),
                "strategy": "3to4", "score": float(cand34.loc[i, "score"]),
            })
    del c34, cand34
    gc.collect()
    if u34:
        u34_df = pd.DataFrame(u34).sort_values(["buy_date", "score"], ascending=[True, False]).groupby("buy_date", as_index=False).first()
        rows.append(u34_df)

    # 2. High V5.1 (sc5_1 >= 88, untriggered) -> evaluate directly from 89KB v5_enriched_119.pkl + 5.9MB 5m bars + targeted a_daily!
    SRC_HD = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
    dfr = pd.read_pickle(f"{SRC_HD}/v5_enriched_119.pkl")
    # Run exact score_v5_1 from sub2_03_golden_relaxation_backtest.py (with d1_to > 35.0)
    hd_src = open(f"{SIM}/backtests_astock/sandbox_lab/golden_regime_20261113/sub2_03_golden_relaxation_backtest.py", encoding="utf-8").read().splitlines()
    score_fn_src = "\n".join(hd_src[35:75]).replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
    ns_sc = {}
    exec(score_fn_src, ns_sc)
    dfr["sc5_1"] = [ns_sc["score_v5_1"](r) for _, r in dfr.iterrows()]
    dhd_dts = trig_dts_other["high"]
    sub_hd = dfr[(dfr["sc5_1"] >= 88) & dfr["buy_date"].between("2021-11-16", "2026-11-16")].sort_values(["buy_date", "sc5_1"], ascending=[True, False]).groupby("buy_date", as_index=False).first()
    sub_hd = sub_hd[~sub_hd["buy_date"].isin(dhd_dts)].copy()
    if not sub_hd.empty:
        bars_5m = pickle.load(open(f"{SRC_HD}/sub2_5m_bars_cache.pkl", "rb"))
        idx_5m = {(k[0], k[2]): v for k, v in bars_5m.items()}
        del bars_5m
        hd_codes = sorted(sub_hd["code"].astype(str).str.zfill(6).unique())
        hd_tks = sorted([f"{c}.SH" for c in hd_codes] + [f"{c}.SZ" for c in hd_codes])
        hd_dts = sorted(sub_hd["buy_date"].unique())
        flt_hd = (ds.field("date") >= pd.Timestamp(min(hd_dts))) & (ds.field("date") <= pd.Timestamp(max(hd_dts))) & (ds.field("ticker").isin(hd_tks))
        dp_hd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=["date", "ticker", "open", "close"], filter=flt_hd).to_table().to_pandas()
        dp_hd["c6"] = dp_hd["ticker"].astype(str).str[:6]
        dp_hd["dt"] = dp_hd["date"].dt.strftime("%Y-%m-%d")
        op_lu = {(r.c6, r.dt): float(r.open) for r in dp_hd.itertuples(index=False)}
        del dp_hd
        uhd = []
        for r in sub_hd.itertuples():
            bd = str(r.buy_date)
            ck = str(r.code).zfill(6)
            if r.op2 >= 0.0:
                continue  # Red open triggers at 09:25 unless yizi/over-gap (which wouldn't be in untrig with green open check)
            b_op = op_lu.get((ck, bd))
            if b_op is None:
                continue
            ipx = round(b_op * 1.015, 2)
            df_k = idx_5m.get((ck, bd), pd.DataFrame())
            sub_m = df_k[(df_k["date"] == bd) & (df_k["hhmm"] <= "11:30")] if not df_k.empty else pd.DataFrame()
            # Untriggered if morning high < ipx (or sub_m empty)
            if sub_m.empty or float(sub_m["high"].max()) < ipx:
                uhd.append({
                    "buy_date": bd, "buy_hhmm": 935, "exit_date": bd, "exit_hhmm": 1130,
                    "code": ck, "name": str(r.name), "strategy": "high", "score": float(r.sc5_1),
                })
        del idx_5m
        if uhd:
            rows.append(pd.DataFrame(uhd))

    # 3. 1to2 V19 (base_pass_v19 & ~sim_ok) -> 84KB parquet
    pt12_pq = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2/_cache_pretrig_pool.parquet"
    pt12 = pd.read_parquet(pt12_pq)
    d12_dts = trig_dts_other["1to2"]
    v19_pt = pt12[pt12["base_pass_v19"] & pt12["buy_date"].between("2021-11-16", "2026-11-16")].sort_values(["buy_date", "sv_base", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    u12 = v19_pt[(~v19_pt["sim_ok"]) & (~v19_pt["buy_date"].isin(d12_dts))][["buy_date", "code", "name", "base_score"]].copy()
    if not u12.empty:
        u12["buy_hhmm"] = 935
        u12["exit_date"] = u12["buy_date"]
        u12["exit_hhmm"] = 1130
        u12["strategy"] = "1to2"
        u12.rename(columns={"base_score": "score"}, inplace=True)
        rows.append(u12)

    out = pd.concat(rows, ignore_index=True)
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["name"] = out["name"].fillna("").astype(str)
    out["tier"] = [tpe.assign_physical_tier(r.strategy, r.score) for r in out.itertuples(index=False)]
    out["net_ret"] = 0.0
    out["buy_price_val"] = np.nan
    out["is_adj_px"] = False
    out["is_untrig"] = True

    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = out[(out["strategy"] == st_u) & (~out["buy_date"].isin(trig_dts_other[st_u]))].copy()
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].copy()
        if not sub_u.empty:
            sub_u = sub_u.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
            ut_parts.append(sub_u)
    ut_final = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    return ut_final[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]]


def main():
    t0 = time.time()
    print(f"[Step 1] Building lean PIT caches in {OUT_DIR} ...")

    # Build V20 5-strat & untriggered pool FIRST before loading p20/stock_day so Peak RSS stays ~1.3GB
    wf_ctx = lib.wf.load_v20_reference_context(lib.WAVE1_DIR)
    raw_idx = json.load(open(f"{lib.SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw_idx["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}

    other_parts, trig_dts_other = [], {}
    for st in ("3to4", "high", "pry", "2to3", "1to2"):
        df = pd.read_parquet(f"{lib.RD028_DIR}/pool_{st}_oldhot.parquet")
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        df["buy_price_val"] = df["buy_price"].astype(float)
        df["is_adj_px"] = False
        if st == "high":
            df["v51_cb_loss"] = (df["net_ret"].to_numpy(float) < -0.02) & (~df["dt_deferred"].to_numpy(bool))
        _, slot_df = lib.m1.sim_standalone(st, df, np.zeros(len(df)), high_cb_mode="v51_exact")
        chosen = slot_df[slot_df["buy_date"].between("2021-11-16", "2026-11-16")].copy()
        chosen["score"] = [round(float(x), 1) for x in chosen["v20_score"]] if st == "1to2" else chosen["v20_score"]
        chosen["tier"] = [lib.tpe.assign_physical_tier(st, sc) for sc in chosen["score"]]
        chosen["is_untrig"] = False
        trig_dts_other[st] = set(chosen["buy_date"])
        other_parts.append(chosen)
    other_pool5 = pd.concat(other_parts, ignore_index=True)

    ut_final = build_lean_untrig_under_2gb(trig_dts_other, cal_5y)
    print(f"  Built ut_final ({len(ut_final)} rows) | RSS={rss_mb()}MB")

    p20_old = pd.read_parquet(f"{lib.RD028_DIR}/pool_20cm_oldhot.parquet")
    p20_old["code"] = p20_old["code"].astype(str).str.zfill(6)
    p20_old["buy_date"] = p20_old["buy_date"].astype(str).str[:10]
    p20_old["exit_date"] = p20_old["exit_date"].astype(str).str[:10]
    p20_old["exit_hhmm"] = np.where(p20_old["exit_reason"].astype(str).str.contains("open|gap|tp"), 1030, 1500)
    p20_old["buy_price_val"] = p20_old["buy_px"].astype(float)
    p20_old["is_adj_px"] = True

    all_need_rows = pd.concat([other_pool5[["code", "buy_date", "exit_date"]], p20_old[["code", "buy_date", "exit_date"]]], ignore_index=True)
    bar_lu = lib._build_needed_bar_lu(all_need_rows, cal_5y)
    other_pool5["mtm_5y"] = lib.m1.precompute_mtm_segments(other_pool5, cal_5y, idx_5y, bar_lu, is_20cm_adj=False)
    p20_old["mtm_5y"] = lib.m1.precompute_mtm_segments(p20_old, cal_5y, idx_5y, bar_lu, is_20cm_adj=True)
    del bar_lu
    gc.collect()
    pa.default_memory_pool().release_unused()

    cols_keep = [
        "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
        "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig", "mtm_5y",
    ]
    other_pool5 = other_pool5[cols_keep].copy()
    p20_map = {(r.buy_date, r.code): (r.mtm_5y, float(r.buy_price_val), int(r.exit_hhmm), float(r.net_ret)) for r in p20_old.itertuples(index=False)}

    v20_ctx = {
        "wf_ctx": wf_ctx,
        "cal_5y": cal_5y,
        "idx_5y": idx_5y,
        "sh300": sh300,
        "all_sh_dts": all_sh_dts,
        "other_pool5": other_pool5,
        "ut_final": ut_final,
        "p20_old": p20_old,
        "p20_map": p20_map,
    }
    base_comb = lib.w23.get_official_v20_comb_metrics(v20_ctx)
    assert base_comb["FULL_5Y"]["n"] == 278 and abs(base_comb["FULL_5Y"]["nav"] - 69134091.51) < 10.0, f"5Y parity fail: {base_comb['FULL_5Y']}"
    assert base_comb["FULL_WF"]["n"] == 207 and abs(base_comb["FULL_WF"]["nav"] - 611729.55) < 10.0, f"WF parity fail: {base_comb['FULL_WF']}"

    with open(f"{OUT_DIR}/_cache_v20_comb_ctx.pkl", "wb") as f:
        pickle.dump(v20_ctx, f)
    del v20_ctx, wf_ctx, other_pool5, p20_old, ut_final
    gc.collect()

    p20, meta = lib.load_20cm_enriched_data()
    p20_segs = {
        "segs_30": p20["segs_30"].tolist(),
        "segs_50": p20["segs_50"].tolist(),
        "segs_80": p20["segs_80"].tolist(),
        "meta": meta,
    }
    p20.drop(columns=["segs_30", "segs_50", "segs_80"]).to_parquet(f"{OUT_DIR}/_cache_p20.parquet", index=False)
    with open(f"{OUT_DIR}/_cache_p20_segs.pkl", "wb") as f:
        pickle.dump(p20_segs, f)
    print(f"[Step 1 DONE in {time.time()-t0:.1f}s | V20 Parity OK: 5Y={base_comb['FULL_5Y']['nav']}, WF={base_comb['FULL_WF']['nav']} | Peak RSS={rss_mb()}MB]")
    assert rss_mb() < 2000.0, f"Peak RSS exceeded 2GB: {rss_mb()}"


if __name__ == "__main__":
    main()
