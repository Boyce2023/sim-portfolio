#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD046 Stage 2C: Build 5-Year Causal CB-Stock Panel + All Prototype Blind Matrix (2021-01-04..2026-11-24).
Tests:
  - CB1: Stock 09:25 opens at limit-up -> buy CB 09:30 open -> exit T+0 close / T+1 open / T+1 close
    (with Lookahead Audit comparing fake `is_yizi_zt==1` vs true causal `stk_open_at_zt`, plus Active-Only vs Full Survivorship Audit!)
  - P2 (PrevZT): Stock sealed ZT on T-1 -> buy CB T open -> exit T+0 / T+1O / T+1C
  - P3 (StrongGap): Stock opens >= +5% (non-yizi) -> buy CB T open -> exit T+0 / T+1O
  - P4 (ZTCloseCarry): Stock sealed ZT on T (non-20%-locked CB) -> buy CB T 15:00 close -> exit T+1O / T+1C
  - P5 (LowPremStrong): Union of causal strong stock triggers with `cb_prem_t1 < 20%`
Zero yfinance (D12). Peak memory < 1.2 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd046_convertible_bond_t0_20261126"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
STOCK_PARQUET = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
MKT_PARQUET = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"


def _eval_slice(df: pd.DataFrame, ret_col: str, fee_bps_list=(0, 10, 20, 30, 50, 80, 100, 150)) -> dict:
    s = df[ret_col].dropna().to_numpy(float)
    n = len(s)
    if n == 0:
        return {"n": 0}
    w, l = s[s > 0], s[s <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    out = {
        "n": int(n),
        "wr_gross_pct": round(float((s > 0).mean() * 100.0), 2),
        "plr_gross": round(plr, 2),
        "mean_gross_pct": round(float(s.mean() * 100.0), 2),
        "med_gross_pct": round(float(np.median(s) * 100.0), 2),
    }
    # Daily equal-weight NAV & Top-1 (lowest prem or highest amt_5d_t1) NAV at each fee tier
    for bps in fee_bps_list:
        f = bps / 10000.0
        net = (1.0 + s) * (1.0 - f) - 1.0
        tmp = pd.DataFrame({"dt": df.loc[df[ret_col].notna(), "dt"].values, "net": net})
        eq_d = tmp.groupby("dt", sort=True)["net"].mean().to_numpy(float)
        eq_nav = float(np.prod(1.0 + eq_d))
        out[f"eq_nav_{bps}bps"] = round(eq_nav, 4)
        out[f"mean_{bps}bps_pct"] = round(float(net.mean() * 100.0), 2)
        out[f"wr_{bps}bps_pct"] = round(float((net > 0).mean() * 100.0), 2)
    return out


def main():
    t0 = time.time()
    print("[Step 3] Loading CB daily panel...")
    cb = pd.read_parquet(f"{OUT_DIR}/cb_daily_all_pit.parquet")
    cb = cb.sort_values(["cb_code", "dt"]).reset_index(drop=True)

    # Next trading date on CB for exact T+1 exit alignment
    g = cb.groupby("cb_code")
    cb["cb_prev_close"] = g["close"].shift(1)
    cb["cb_next_dt"] = g["dt"].shift(-1)
    cb["cb_next_open"] = g["open"].shift(-1)
    cb["cb_next_close"] = g["close"].shift(-1)

    # PIT remaining scale fill
    before_conv = cb["transfer_start_dt"].notna() & (cb["dt"] < cb["transfer_start_dt"])
    rs = cb["remain_scale_yi"].copy()
    rs[before_conv & rs.isna()] = cb.loc[before_conv & rs.isna(), "issue_scale_yi"]
    cb["has_exact_remain_scale"] = rs.notna()
    cb["remain_scale_pit"] = rs.groupby(cb["cb_code"]).ffill().fillna(cb["issue_scale_yi"])

    # Causal CB features (strictly T-1 or T open)
    g = cb.groupby("cb_code")
    cb["cb_open_pct"] = cb["open"] / cb["cb_prev_close"] - 1.0
    cb["cb_ret_oc"] = cb["close"] / cb["open"] - 1.0
    cb["cb_ret_cc"] = cb["close"] / cb["cb_prev_close"] - 1.0
    cb["cb_ret_t1o"] = cb["cb_next_open"] / cb["open"] - 1.0
    cb["cb_ret_t1c"] = cb["cb_next_close"] / cb["open"] - 1.0
    cb["cb_ret_c2no"] = cb["cb_next_open"] / cb["close"] - 1.0
    cb["cb_ret_c2nc"] = cb["cb_next_close"] / cb["close"] - 1.0

    cb["cb_ret_1d_t1"] = g["cb_ret_cc"].shift(1)
    cb["cb_ret_5d_t1"] = g["close"].shift(1) / g["close"].shift(6) - 1.0
    cb["cb_prem_t1"] = g["conv_prem_pct"].shift(1)
    cb["cb_pure_prem_t1"] = g["pure_bond_prem_pct"].shift(1)
    cb["cb_swap_val_t1"] = g["swap_value"].shift(1)
    cb["cb_double_low_t1"] = cb["cb_prev_close"] + cb["cb_prem_t1"]
    cb["cb_amt_t1"] = g["amount_yi"].shift(1)
    cb["cb_amt_5d_t1"] = g["amount_yi"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    cb["cb_remain_scale_t1"] = g["remain_scale_pit"].shift(1)
    cb["cb_turn_t1"] = cb["cb_amt_t1"] / cb["cb_remain_scale_t1"].clip(lower=0.05) * 100.0
    cb["cb_turn_5d_t1"] = cb["cb_amt_5d_t1"] / cb["cb_remain_scale_t1"].clip(lower=0.05) * 100.0
    cb["cb_list_age"] = g.cumcount() + 1

    cb["cb_is_halt"] = (cb["vol_shou"] <= 0) | (cb["open"] <= 0)
    cb["cb_is_yizi"] = (
        ((cb["dt"] >= "2022-08-01") & (cb["cb_open_pct"] >= 0.195) & (cb["low"] >= cb["open"] * 0.999))
        | ((cb["open"] == cb["high"]) & (cb["open"] == cb["low"]) & (cb["open"] == cb["close"]) & (cb["cb_open_pct"] > 0.09))
    )
    cb["cb_close_locked_20zt"] = (cb["dt"] >= "2022-08-01") & (cb["cb_ret_cc"] >= 0.195) & (cb["close"] >= cb["high"] * 0.999)

    # Load stock columns carefully
    stk_cols = [
        "dt", "c6", "open", "high", "low", "close", "prev_close_raw", "ret_1d", "open_pct",
        "is_zt", "hit_zt", "is_yizi_zt", "is_broken_zt", "is_st_pit", "is_20cm",
        "amount_yi", "amount_yi_t1", "ret_5d_t1", "ret_20d_t1", "pos_20d_t1",
        "streak", "prev_streak", "list_age", "mcap_yi_t1", "free_mcap_yi_t1",
        "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
    ]
    stk = pq.read_table(STOCK_PARQUET, columns=stk_cols).to_pandas()
    stk = stk.rename(columns={"c6": "stock_code", "open": "stk_open", "high": "stk_high", "low": "stk_low", "close": "stk_close", "amount_yi": "stk_amt_yi"})

    # Filter stk to CB stock codes early to slash memory
    cb_stks = set(cb["stock_code"].unique())
    stk = stk[stk["stock_code"].isin(cb_stks)].copy()
    lim_rate = np.where(stk["is_st_pit"] == 1, 0.05, np.where(stk["is_20cm"] == 1, 0.20, 0.10))
    stk["zt_px_est"] = np.round(stk["prev_close_raw"] * (1.0 + lim_rate) + 1e-9, 2)
    stk["stk_open_at_zt"] = (stk["stk_open"] >= stk["zt_px_est"] - 0.011) & (stk["prev_close_raw"] > 0) & (stk["is_st_pit"] == 0) & (stk["list_age"] > 10)

    m = cb[(cb["dt"] >= "2021-01-04") & (cb["dt"] <= "2026-11-24")].merge(stk, on=["dt", "stock_code"], how="inner")
    del cb, stk
    gc.collect()

    # Compute 20d rolling CB-Stock correlation & beta (strictly shifted by 1 day!)
    m = m.sort_values(["cb_code", "dt"]).reset_index(drop=True)
    m["stk_ret_dec"] = m["ret_1d"] / 100.0
    # Rolling 20d correlation and std ratio shifted by 1
    def _calc_beta(grp):
        rc = grp["cb_ret_cc"].shift(1)
        rs = grp["stk_ret_dec"].shift(1)
        cov = rc.rolling(20, min_periods=10).cov(rs)
        var = rs.rolling(20, min_periods=10).var()
        return cov / var.clip(lower=1e-6)
    m["cb_beta_20d_t1"] = m.groupby("cb_code", group_keys=False).apply(_calc_beta).values

    # Static init_conv_px error audit (comparing static 100/init_conv_px * stk_close vs official PIT swap_value)
    static_swap = 100.0 / m["init_conv_px"].clip(lower=0.01) * m["stk_close"]
    static_prem = (m["close"] / static_swap - 1.0) * 100.0
    prem_err = (static_prem - m["conv_prem_pct"]).abs()
    conv_prem_error_audit = {
        "n_rows": int(prem_err.notna().sum()),
        "abs_prem_err_gt_5pp_pct": round(float((prem_err > 5.0).mean() * 100.0), 2),
        "abs_prem_err_gt_15pp_pct": round(float((prem_err > 15.0).mean() * 100.0), 2),
        "median_abs_err_pp": round(float(prem_err.median()), 2),
        "p90_abs_err_pp": round(float(prem_err.quantile(0.90)), 2),
    }

    # Merge causal market daily factors (T-1)
    mkt = pd.read_parquet(
        MKT_PARQUET,
        columns=["trade_date", "L1_zt_cnt_t1", "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1", "L1_zt_prem_t1", "L1_sent_phase_t1", "L1_smb_20d_t1"],
    ).rename(columns={"trade_date": "dt"})
    m = m.merge(mkt, on="dt", how="left")

    # Open-time causal parity & lag features
    m["parity_open_est"] = m["cb_swap_val_t1"] * (1.0 + m["open_pct"] / 100.0)
    m["cb_open_prem_est"] = (m["open"] / m["parity_open_est"].clip(lower=1.0) - 1.0) * 100.0
    m["cb_open_lag"] = m["open_pct"] / 100.0 - m["cb_open_pct"]

    # Base hygiene for open-buy pools
    base_ok = (~m["cb_is_halt"]) & (~m["cb_is_yizi"]) & (m["cb_prev_close"].notna()) & (m["is_st_pit"] == 0) & (m["list_age"] > 10) & (m["cb_list_age"] >= 2)
    m["base_ok_open"] = base_ok
    m["base_ok_close"] = (~m["cb_is_halt"]) & (~m["cb_close_locked_20zt"]) & (m["cb_prev_close"].notna()) & (m["is_st_pit"] == 0) & (m["list_age"] > 10) & (m["cb_list_age"] >= 2)

    m.to_parquet(f"{OUT_DIR}/cb_panel_features_pit.parquet", index=False)

    # --- Build Comprehensive Blind Matrix ---
    bm_rows = []
    def add_bm(proto, slice_name, sub_df, ret_col, causal_note="causal"):
        res = _eval_slice(sub_df, ret_col)
        res.update({"prototype": proto, "slice": slice_name, "exit_col": ret_col, "causal_note": causal_note})
        bm_rows.append(res)

    # 1. CB1 Lookahead Audit vs Causal Open-at-ZT
    fake_yizi = m[m["base_ok_open"] & (m["is_yizi_zt"] == 1)]
    add_bm("CB1_AUDIT_PEEK", "fake_is_yizi_zt_ALL", fake_yizi, "cb_ret_oc", "PEEK_1500_LOCK")
    add_bm("CB1_AUDIT_PEEK", "fake_is_yizi_zt_prem_lt10", fake_yizi[fake_yizi["cb_prem_t1"] < 10], "cb_ret_oc", "PEEK_1500_LOCK")

    cb1 = m[m["base_ok_open"] & m["stk_open_at_zt"]].copy()
    for exit_c, ex_lbl in [("cb_ret_oc", "T0_Close"), ("cb_ret_t1o", "T1_Open"), ("cb_ret_t1c", "T1_Close")]:
        add_bm("CB1", f"all_causal_{ex_lbl}", cb1, exit_c)
        add_bm("CB1", f"active_only_{ex_lbl}", cb1[~cb1["is_delisted"]], exit_c)
        add_bm("CB1", f"delisted_only_{ex_lbl}", cb1[cb1["is_delisted"]], exit_c)
        add_bm("CB1", f"pre_202208_{ex_lbl}", cb1[cb1["dt"] < "2022-08-01"], exit_c)
        add_bm("CB1", f"post_202208_{ex_lbl}", cb1[cb1["dt"] >= "2022-08-01"], exit_c)

    # CB1 sub-slices on T0_Close & T1_Open
    for s_lbl, cond in [
        ("px_lt120", cb1["cb_prev_close"] < 120),
        ("px_120_150", cb1["cb_prev_close"].between(120, 150)),
        ("px_gt150", cb1["cb_prev_close"] > 150),
        ("prem_lt10", cb1["cb_prem_t1"] < 10),
        ("prem_10_30", cb1["cb_prem_t1"].between(10, 30)),
        ("prem_gt30", cb1["cb_prem_t1"] > 30),
        ("amt5d_ge0.5yi", cb1["cb_amt_5d_t1"] >= 0.5),
        ("amt5d_ge1.0yi", cb1["cb_amt_5d_t1"] >= 1.0),
        ("rem_lt3yi", cb1["cb_remain_scale_t1"] < 3.0),
        ("rem_ge3yi", cb1["cb_remain_scale_t1"] >= 3.0),
        ("cb_open_lt3pct", cb1["cb_open_pct"] < 0.03),
        ("cb_open_3_6pct", cb1["cb_open_pct"].between(0.03, 0.06)),
        ("cb_open_gt10pct", cb1["cb_open_pct"] > 0.10),
        ("prev_streak_ge1", cb1["prev_streak"] >= 1),
        ("prev_streak_ge1_prem_lt15", (cb1["prev_streak"] >= 1) & (cb1["cb_prem_t1"] < 15)),
        ("post2208_prem_lt10", (cb1["dt"] >= "2022-08-01") & (cb1["cb_prem_t1"] < 10)),
        ("post2208_prem_lt15_amt0.5", (cb1["dt"] >= "2022-08-01") & (cb1["cb_prem_t1"] < 15) & (cb1["cb_amt_5d_t1"] >= 0.5)),
        ("decomp_broken_zt", cb1["is_zt"] == 0),
        ("decomp_held_yizi", cb1["is_yizi_zt"] == 1),
    ]:
        note = "POST_DECOMP" if s_lbl.startswith("decomp_") else "causal"
        add_bm("CB1", f"{s_lbl}_T0_Close", cb1[cond], "cb_ret_oc", note)
        add_bm("CB1", f"{s_lbl}_T1_Open", cb1[cond], "cb_ret_t1o", note)

    # 2. P2: PrevZT (T-1 ZT continuation)
    p2 = m[m["base_ok_open"] & (m["prev_streak"] >= 1)].copy()
    for s_lbl, cond in [
        ("all_prev_zt", p2["prev_streak"] >= 1),
        ("stk_open_ge2", p2["open_pct"] >= 2.0),
        ("stk_open_ge3", p2["open_pct"] >= 3.0),
        ("stk_open_ge5", p2["open_pct"] >= 5.0),
        ("stk_open_ge2_prem_lt15", (p2["open_pct"] >= 2.0) & (p2["cb_prem_t1"] < 15)),
        ("lianban_ge2", p2["prev_streak"] >= 2),
        ("low_open_neg3_to_2", p2["open_pct"].between(-3.0, 2.0)),
    ]:
        add_bm("P2_PrevZT", f"{s_lbl}_T0_Close", p2[cond], "cb_ret_oc")
        add_bm("P2_PrevZT", f"{s_lbl}_T1_Open", p2[cond], "cb_ret_t1o")

    # 3. P3: Stock 09:25 Strong Gap (>= +5%, non-yizi)
    p3 = m[m["base_ok_open"] & (m["open_pct"] >= 5.0) & (~m["stk_open_at_zt"])].copy()
    for s_lbl, cond in [
        ("all_gap5", p3["open_pct"] >= 5.0),
        ("prem_lt15_lag_gt2", (p3["cb_prem_t1"] < 15) & (p3["cb_open_lag"] > 0.02)),
        ("open_prem_lt0", p3["cb_open_prem_est"] < 0.0),
        ("prem_lt10_cbopen_lt2", (p3["cb_prem_t1"] < 10) & (p3["cb_open_pct"] < 0.02)),
    ]:
        add_bm("P3_StrongGap", f"{s_lbl}_T0_Close", p3[cond], "cb_ret_oc")
        add_bm("P3_StrongGap", f"{s_lbl}_T1_Open", p3[cond], "cb_ret_t1o")

    # 4. P4: Stock ZT Close -> Buy CB 15:00 Close -> Sell T+1
    p4 = m[m["base_ok_close"] & (m["is_zt"] == 1)].copy()
    for s_lbl, cond in [
        ("all_zt_close", p4["is_zt"] == 1),
        ("streak1_zt_close", p4["streak"] == 1),
        ("streak2plus_zt_close", p4["streak"] >= 2),
        ("prem_lt10", p4["conv_prem_pct"] < 10),
        ("prem_lt15", p4["conv_prem_pct"] < 15),
        ("post2208_prem_lt15", (p4["dt"] >= "2022-08-01") & (p4["conv_prem_pct"] < 15)),
        ("20cm_zt_close", p4["is_20cm"] == 1),
    ]:
        add_bm("P4_ZTCloseCarry", f"{s_lbl}_T1_Open", p4[cond], "cb_ret_c2no")
        add_bm("P4_ZTCloseCarry", f"{s_lbl}_T1_Close", p4[cond], "cb_ret_c2nc")

    bm_df = pd.DataFrame(bm_rows)
    bm_df.to_csv(f"{OUT_DIR}/rd046_blind_matrix.csv", index=False)

    with open(f"{OUT_DIR}/rd046_step3_meta.json", "w", encoding="utf-8") as f:
        json.dump({"conv_prem_error_audit": conv_prem_error_audit, "n_blind_rows": len(bm_df), "elapsed_sec": round(time.time() - t0, 2)}, f, ensure_ascii=False, indent=2)

    print(f"[Step 3] Done in {time.time()-t0:.1f}s | blind rows={len(bm_df)} | prem err >5pp={conv_prem_error_audit['abs_prem_err_gt_5pp_pct']}%")
    # Print top 10 by mean_10bps_pct (excluding PEEK & POST_DECOMP)
    clean_bm = bm_df[(bm_df["causal_note"] == "causal") & (bm_df["n"] >= 30)].sort_values("mean_10bps_pct", ascending=False)
    print("\nTop 10 causal blind slices (mean @ 10bps):")
    print(clean_bm[["prototype", "slice", "n", "wr_gross_pct", "mean_gross_pct", "mean_10bps_pct", "eq_nav_10bps", "eq_nav_50bps"]].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
