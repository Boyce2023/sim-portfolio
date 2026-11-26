#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Exact bit-for-bit reconstruction of W2B6 ModE_E3 (using original `us_ret1d.abs() >= 4.0` before
drop_duplicates(["buy_date", "code"])) across all thresholds + daily vs monthly, saving
exact daily MTM (`dr_exact`, `dr_emp`, `dr_comb`) for side-by-side Red Team comparison against
the clean positive-only deduplicated pool.
"""
import os
for _env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_env] = "1"

import gc
import pickle
import sys
import time
import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1_DIR = f"{RD035_DIR}/wave1_base"
W2B6_DIR = f"{RD035_DIR}/wave2b/w2b6_empty_slot_blind_and_crossseat"
OUT_DIR = f"{RD035_DIR}/wave3_final/w3_3_redteam_audit_b"

for p in (WAVE1_DIR, W2B6_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _w2b6_common as cm6
import run_w2b6_modE_us_gap as r6e
import step_build_b5_b6 as b56


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(WAVE1_DIR)
    cal5 = v20_ctx["calendar_5y"]
    cal_dts_wf = cal5[cal5["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date")["trade_date"].tolist()
    px_idx = cm6.PriceReturnIndex(end_cutoff="2026-11-25")

    cal_cn = sorted([d for d in v20_ctx["bench"]["trade_date"].tolist() if "2021-01-04" <= d <= "2026-11-16"])
    map_df, us_p = r6e.load_us_leaders_map()
    cn_dt_df = pd.DataFrame({"buy_date": cal_cn, "cn_ts": pd.to_datetime(cal_cn)}).sort_values("cn_ts")
    us_p["us_ts"] = pd.to_datetime(us_p["us_date"])
    aligned_list = []
    for utk, grp in us_p.groupby("ticker"):
        m = pd.merge_asof(cn_dt_df, grp.sort_values("us_ts"), left_on="cn_ts", right_on="us_ts", direction="backward", allow_exact_matches=False)
        m["us_ticker"] = utk
        aligned_list.append(m[["buy_date", "us_ticker", "us_ret1d", "us_ret3d", "us_vol_r20"]])
    us_cn = pd.concat(aligned_list, ignore_index=True)

    # Exact original line 104: us_ret1d.abs() >= 4.0 BEFORE drop_duplicates
    us_trig = us_cn[(us_cn["us_ret1d"].abs() >= 4.0) & (us_cn["us_vol_r20"] >= 1.4)].copy()
    cands = us_trig.merge(map_df, on="us_ticker", how="inner")
    cands["abs_r"] = cands["us_ret1d"].abs()
    cands = cands.sort_values(["buy_date", "code", "abs_r"], ascending=[True, True, False]).drop_duplicates(["buy_date", "code"]).drop(columns=["abs_r", "tree_name", "us_ticker"]).reset_index(drop=True)

    ret_df = px_idx.lookup_forward_returns(cands, horizons=(1, 3, 5), buy_at="open", min_amt_yi=0.0)
    ret_df = ret_df[ret_df["can_buy"]].copy().reset_index(drop=True)
    op_vals = np.full(len(ret_df), np.nan, dtype=np.float32)
    for idx_r, (c_r, d_r) in enumerate(zip(ret_df["code"], ret_df["buy_date"])):
        cid = px_idx.c6_to_id.get(c_r, -1)
        did = px_idx.dt_to_id.get(d_r, -1)
        if cid >= 0 and did >= 0:
            s, e = px_idx.bounds[cid]
            dt_sub = px_idx.dt_id[s:e]
            rel = int(np.searchsorted(dt_sub, did))
            if rel < len(dt_sub) and int(dt_sub[rel]) == did:
                op_vals[idx_r] = px_idx.open_pct[s + rel]
    ret_df["_op_pre"] = op_vals
    keep_mask = ((ret_df["us_ret1d"] >= 4.0) & (ret_df["_op_pre"].between(-2.0, 3.0))) | ((ret_df["us_ret1d"] <= -4.0) & (ret_df["_op_pre"] >= 1.5))
    ret_df = ret_df[keep_mask].drop(columns=["_op_pre"]).reset_index(drop=True)

    feat_df, fcols = cm6.attach_pit_features(ret_df, buy_at="open", extra_cols=["us_ret1d", "us_ret3d", "us_vol_r20", "is_mingmen_node"])
    feat_df = feat_df[feat_df["can_buy"] & (feat_df["amount_yi_t1"] >= 0.8)].copy().reset_index(drop=True)
    feat_df["us_a_unpriced_gap"] = feat_df["us_ret1d"] - feat_df["open_pct"]
    fcols = fcols + ["us_a_unpriced_gap"]

    e3_df = feat_df[(feat_df["us_ret1d"] >= 4.0) & (feat_df["is_mingmen_node"] == 1) & (feat_df["open_pct"].between(-2.0, 3.0))].copy().reset_index(drop=True)
    e3_df["exit_date"] = e3_df["exit_date_h1"]
    e3_df["gross_ret"] = e3_df["gross_ret_h1"]
    e3_df = e3_df[(e3_df["exit_date"] > e3_df["buy_date"]) & e3_df["gross_ret"].notna()].reset_index(drop=True)
    min_w = 80 if len(e3_df) >= 1500 else 35
    min_wr = 40 if len(e3_df) >= 1500 else 20

    th_e = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80)
    out = {}
    for rfreq in ("daily", "monthly"):
        pack = b56.run_scorecard_pack(e3_df, fcols, px_idx, v20_ctx, cal_dts_wf, rfreq, th_e, min_w, min_wr, top_k=12)
        for th_name, v in pack.items():
            out[f"E3_ORIG_US4pct_Mingmen_H1_{rfreq}::{th_name}"] = v

    with open(f"{OUT_DIR}/_cache_orig_mode_e3.pkl", "wb") as f:
        pickle.dump(out, f)
    print(f"[Orig ModE E3 DONE in {time.time()-t0:.1f}s] {len(out)} variants | RSS={b56.rss_mb()} MB", flush=True)


if __name__ == "__main__":
    main()
