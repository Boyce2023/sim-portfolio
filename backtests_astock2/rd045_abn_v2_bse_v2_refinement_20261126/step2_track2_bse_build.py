#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 2A: Build Track 2 BSE 30cm V2 event pool (B2_A/B2_B) + rotation panel (B2_C) for post-924."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import gc, json, resource, sys, time
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD042_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd042_bse30cm_subnew_20261126"
RD045_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
if RD045_DIR not in sys.path:
    sys.path.insert(0, RD045_DIR)
import _rd045_common as cm

BSE_PQ = f"{RD042_DIR}/bse_30cm_daily_cache.parquet"
MKT_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"

MKT_COLS = [
    "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1",
    "L1_duanban_damian_t1", "L1_zt_mom3v20_t1", "L1_sent_phase_t1", "L1_amt_ratio20_t1",
    "mkt_yizi_zt_cnt_t1", "mkt_amt_tril_t1", "mkt_0925_zt_cnt", "mkt_notices_sev_abn_5d_t1",
    "mkt_csi1000_ret1d_t1", "th_style_ice_point_sig_t1",
]


def simulate_bse_v2_exits(
    b: int, n: int, op: np.ndarray, hi: np.ndarray, lo: np.ndarray, cl: np.ndarray, af: np.ndarray,
    ac: np.ndarray, dts: np.ndarray, zt: np.ndarray, dt_f: np.ndarray, yzd: np.ndarray, ma5: np.ndarray, ma10: np.ndarray,
) -> dict:
    buy_px = op[b]
    if b + 1 >= n or buy_px <= 0 or af[b] <= 0:
        return {}
    b_ac = buy_px * af[b]
    out = {}

    def _finish(target_k: int, tag: str):
        if target_k >= n:
            return
        k = target_k
        while k < n - 1 and yzd[k]:
            k += 1
        if yzd[k]:
            return
        if k > target_k:
            ex_px, ehh, rsn = op[k], 925, f"{tag}_dt_open"
        elif dt_f[k] and k + 1 < n:
            k2 = k + 1
            while k2 < n - 1 and yzd[k2]:
                k2 += 1
            if yzd[k2]:
                return
            ex_px, ehh, rsn, k = op[k2], 925, f"{tag}_dt_next_open", k2
        else:
            ex_px, ehh, rsn = cl[k], 1500, tag
        if ex_px <= 0 or af[k] <= 0:
            return
        gr = (ex_px * af[k]) / b_ac - 1.0
        mtm = cm.build_mtm_pairs_dt(op, cl, af, dts, b, k, ex_px, buy_at_close=False)
        out[tag] = {"exit_date": str(dts[k]), "exit_hhmm": int(ehh), "gross_ret": float(gr), "reason": rsn, "mtm_gross": mtm}

    for h, nm in ((1, "S1_hold1c"), (2, "S2_hold2c"), (3, "S3_hold3c"), (5, "S4_hold5c")):
        _finish(b + h, nm)

    # Trend exits: MA5 trail (up to b+10) and MA10 trail (up to b+15)
    for ma_arr, max_h, nm in ((ma5, 10, "S_ma5_trail10"), (ma10, 15, "S_ma10_trail15")):
        km = -1
        for off in range(1, max_h + 1):
            k = b + off
            if k >= n:
                break
            if np.isfinite(ma_arr[k]) and cl[k] < ma_arr[k] * 0.995:
                km = k
                break
        if km == -1 and b + max_h < n:
            km = b + max_h
        if km > b:
            _finish(km, nm)

    # S_stop8_ma5: stop -8% close or break MA5 close (up to b+10)
    ks = -1
    for off in range(1, 11):
        k = b + off
        if k >= n:
            break
        ret_k = (cl[k] * af[k]) / b_ac - 1.0
        if ret_k <= -0.08 or (np.isfinite(ma5[k]) and cl[k] < ma5[k] * 0.995):
            ks = k
            break
    if ks == -1 and b + 10 < n:
        ks = b + 10
    if ks > b:
        _finish(ks, "S_stop8_ma5")
    return out


def build_bse_v2_datasets() -> tuple[pd.DataFrame, pd.DataFrame]:
    t0 = time.time()
    df = pd.read_parquet(BSE_PQ)
    df["c6"] = df["c6"].astype(str).str.zfill(6)
    df["dt"] = df["dt"].astype(str).str[:10]
    df = df.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"]).reset_index(drop=True)

    g = df.groupby("c6", sort=False)
    df["bar_idx"] = g.cumcount() + 1
    df["prev_adj_close"] = g["adj_close"].shift(1)
    df["prev_close_raw"] = df["prev_adj_close"] * (df["close"] / df["adj_close"])
    df["ret_1d"] = ((df["adj_close"] / df["prev_adj_close"] - 1.0) * 100.0).astype(np.float64)
    df["open_pct"] = ((df["open"] / df["prev_close_raw"] - 1.0) * 100.0).astype(np.float64)
    hl = (df["high"] - df["low"]).to_numpy(np.float64)
    df["clv"] = np.where(hl > 1e-6, (df["close"] - df["low"]) / hl, 0.5).astype(np.float64)
    df["is_ipo_day1"] = ((df["dt"] == df["list_date"]) & (df["list_date"] > "2021-11-15")).astype(np.int8)
    has_lim = (df["bar_idx"] >= 2) & (df["is_ipo_day1"] == 0) & df["prev_close_raw"].notna() & (df["prev_close_raw"] > 0)
    zt_px = np.round(df["prev_close_raw"].to_numpy(np.float64) * 1.30 + 1e-9, 2)
    dt_px = np.round(df["prev_close_raw"].to_numpy(np.float64) * 0.70 + 1e-9, 2)
    cl_v, hi_v, lo_v, op_v, r1_v = [df[c].to_numpy(np.float64) for c in ("close", "high", "low", "open", "ret_1d")]
    df["zt_px"] = zt_px
    df["is_zt30"] = (has_lim.to_numpy() & (r1_v >= 29.5) & (cl_v >= hi_v - 0.015)).astype(np.int8)
    df["is_yizi_zt30"] = ((df["is_zt30"] == 1) & (op_v >= hi_v - 0.015) & (lo_v >= hi_v - 0.015)).astype(np.int8)
    df["is_dt30"] = (has_lim.to_numpy() & (r1_v <= -29.5) & (cl_v <= lo_v + 0.015)).astype(np.int8)
    df["is_yizi_dt30"] = ((df["is_dt30"] == 1) & (op_v <= lo_v + 0.015) & (hi_v <= lo_v + 0.015)).astype(np.int8)

    bse_cal = sorted(df["dt"].unique())
    prev_dt_map = {bse_cal[i]: bse_cal[i - 1] for i in range(1, len(bse_cal))}
    df["prev_dt"] = df["dt"].map(prev_dt_map)

    mkt_bj = df.groupby("dt", as_index=False).agg(
        bj_mkt_zt30_cnt=("is_zt30", "sum"),
        bj_mkt_surge15_cnt=("ret_1d", lambda s: int((s >= 15.0).sum())),
        bj_mkt_surge12_cnt=("ret_1d", lambda s: int((s >= 12.0).sum())),
        bj_mkt_amt_yi=("amount_yi", "sum"),
        bj_mkt_med_ret=("ret_1d", "median"),
    ).sort_values("dt").reset_index(drop=True)
    mkt_a = pd.read_parquet(MKT_PQ, columns=["trade_date"] + MKT_COLS)
    mkt_a["dt"] = mkt_a["trade_date"].astype(str).str[:10]
    mkt_a = mkt_a.drop(columns=["trade_date"]).drop_duplicates("dt").sort_values("dt").reset_index(drop=True)
    mkt_a["L1_max_board_t2"] = mkt_a["L1_max_board_t1"].shift(1)

    mkt_bj["bj_mkt_amt_ma20"] = mkt_bj["bj_mkt_amt_yi"].rolling(20, min_periods=5).mean()
    mkt_bj["bj_mkt_amt_ratio20"] = mkt_bj["bj_mkt_amt_yi"] / mkt_bj["bj_mkt_amt_ma20"].replace(0, np.nan)
    t1_cols = ["bj_mkt_zt30_cnt", "bj_mkt_surge15_cnt", "bj_mkt_surge12_cnt", "bj_mkt_amt_yi", "bj_mkt_amt_ratio20", "bj_mkt_med_ret"]
    mkt_bj_t1 = mkt_bj[["dt"] + t1_cols].rename(columns={c: f"{c}_t1" for c in t1_cols}).rename(columns={"dt": "prev_dt"})
    df = df.merge(mkt_bj_t1, on="prev_dt", how="left").merge(mkt_a, on="dt", how="left")
    df["bj_amt_share_pct_t1"] = df["bj_mkt_amt_yi_t1"] / (df["mkt_amt_tril_t1"].clip(lower=0.05) * 10000.0) * 100.0
    # Compute 20d MA of bj_amt_share_pct_t1 strictly on dt level
    sh_ser = df.groupby("dt", as_index=False)["bj_amt_share_pct_t1"].first().sort_values("dt")
    sh_ser["bj_amt_share_ratio20_t1"] = sh_ser["bj_amt_share_pct_t1"] / sh_ser["bj_amt_share_pct_t1"].rolling(20, min_periods=5).mean().replace(0, np.nan)
    df = df.merge(sh_ser[["dt", "bj_amt_share_ratio20_t1"]], on="dt", how="left").sort_values(["c6", "dt"]).reset_index(drop=True)

    ev_rows, rot_rows = [], []
    for c6, grp in df.groupby("c6", sort=False):
        n = len(grp)
        if n < 20:
            continue
        dts = grp["dt"].to_numpy()
        op, hi, lo, cl, af, ac = [grp[x].to_numpy(np.float64) for x in ("open", "high", "low", "close", "adj_factor", "adj_close")]
        r1, opct, clv, amt, trn = [grp[x].to_numpy(np.float64) for x in ("ret_1d", "open_pct", "clv", "amount_yi", "turn_pct")]
        pc_raw, zt_px_a = grp["prev_close_raw"].to_numpy(np.float64), grp["zt_px"].to_numpy(np.float64)
        zt, yzz, dt_f, yzd = [grp[x].to_numpy(np.int8) for x in ("is_zt30", "is_yizi_zt30", "is_dt30", "is_yizi_dt30")]
        bidx, ipo1 = grp["bar_idx"].to_numpy(np.int32), grp["is_ipo_day1"].to_numpy(np.int8)
        ma5 = np.full(n, np.nan)
        ma10 = np.full(n, np.nan)
        for idx in range(4, n):
            ma5[idx] = np.mean(ac[idx - 4:idx + 1]) / af[idx]
        for idx in range(9, n):
            ma10[idx] = np.mean(ac[idx - 9:idx + 1]) / af[idx]
        mds = grp[["bj_mkt_zt30_cnt_t1", "bj_mkt_surge15_cnt_t1", "bj_mkt_surge12_cnt_t1", "bj_mkt_amt_yi_t1",
                   "bj_mkt_amt_ratio20_t1", "bj_mkt_med_ret_t1", "bj_amt_share_pct_t1", "bj_amt_share_ratio20_t1",
                   "L1_max_board_t2"] + MKT_COLS].to_dict("records")

        for b in range(20, n - 1):
            b_dt = str(dts[b])
            if b_dt < "2024-09-24":
                continue
            sig = b - 1
            if ipo1[sig] == 1 or ipo1[b] == 1 or bidx[sig] < 20:
                continue
            if op[b] <= 0 or af[b] <= 0 or yzz[b] == 1 or yzd[b] == 1 or not np.isfinite(pc_raw[b]) or pc_raw[b] <= 0:
                continue
            if op[b] >= zt_px_a[b] - 0.015 or opct[b] >= 29.0 or amt[sig] < 0.30:
                continue

            max_r5 = float(np.nanmax(r1[max(0, sig - 4):sig + 1]))
            max_r10 = float(np.nanmax(r1[max(0, sig - 9):sig + 1]))
            is_ev = (r1[sig] >= 12.0) or (max_r5 >= 15.0) or (zt[sig] == 1)
            is_rot = (amt[sig] >= 0.45) and (bidx[sig] >= 60)
            if not (is_ev or is_rot):
                continue

            ex_res = simulate_bse_v2_exits(b, n, op, hi, lo, cl, af, ac, dts, zt, dt_f, yzd, ma5, ma10)
            if not ex_res:
                continue

            a_m5 = float(np.mean(amt[max(0, sig - 4):sig + 1]))
            a_m20 = float(np.mean(amt[max(0, sig - 19):sig + 1]))
            hi60 = float(np.max(ac[max(0, sig - 59):sig + 1]))
            lo20 = float(np.min(ac[max(0, sig - 19):sig + 1]))
            hi20 = float(np.max(ac[max(0, sig - 19):sig + 1]))
            # Days since last >=15% surge strictly <= sig
            s15_idxs = [u for u in range(max(0, sig - 15), sig + 1) if np.isfinite(r1[u]) and r1[u] >= 15.0]
            ds_s15 = int(sig - s15_idxs[-1]) if s15_idxs else 99
            rec = {
                "code": c6, "sig_date": str(dts[sig]), "buy_date": b_dt, "buy_hhmm": 925,
                "buy_px": round(float(op[b]), 3), "is_yizi": False, "open_pct": round(float(opct[b]), 4),
                "bj_amt_yi_t1": round(float(amt[sig]), 4), "bj_ret_1d_t1": round(float(r1[sig]), 4),
                "bj_clv_t1": round(float(clv[sig]), 4), "bj_turn_pct_t1": round(float(trn[sig]), 4),
                "bj_vr5_t1": round(float(amt[sig] / max(1e-6, a_m5)), 4),
                "bj_amt_trend_5v20": round(float(a_m5 / max(1e-6, a_m20)), 4),
                "bj_ret_5d_t1": round(float((ac[sig] / ac[sig - 5] - 1.0) * 100.0), 3) if sig >= 5 else np.nan,
                "bj_ret_10d_t1": round(float((ac[sig] / ac[sig - 10] - 1.0) * 100.0), 3) if sig >= 10 else np.nan,
                "bj_ret_20d_t1": round(float((ac[sig] / ac[sig - 20] - 1.0) * 100.0), 3) if sig >= 20 else np.nan,
                "bj_dist_hi_60_t1": round(float((ac[sig] / hi60 - 1.0) * 100.0), 3) if hi60 > 0 else np.nan,
                "bj_pos_20d_t1": round(float((ac[sig] - lo20) / (hi20 - lo20)), 4) if hi20 > lo20 else 0.5,
                "bj_above_ma5_t1": int(np.isfinite(ma5[sig]) and cl[sig] >= ma5[sig] * 0.995),
                "bj_above_ma10_t1": int(np.isfinite(ma10[sig]) and cl[sig] >= ma10[sig] * 0.995),
                "bj_dist_ma5_pct_t1": round(float((cl[sig] / ma5[sig] - 1.0) * 100.0), 3) if np.isfinite(ma5[sig]) else np.nan,
                "bj_is_zt30_t1": int(zt[sig]), "bj_max_ret5d_t1": round(max_r5, 3), "bj_max_ret10d_t1": round(max_r10, 3),
                "bj_days_since_s15": ds_s15,
            }
            rec.update(mds[b])
            for sname, sdict in ex_res.items():
                rec[f"{sname}_exit_date"] = sdict["exit_date"]
                rec[f"{sname}_exit_hhmm"] = sdict["exit_hhmm"]
                rec[f"{sname}_gross_ret"] = sdict["gross_ret"]
                rec[f"{sname}_mtm_json"] = json.dumps(sdict["mtm_gross"])
            if is_ev:
                ev_rows.append(rec)
            if is_rot:
                rot_rows.append(rec)

    ev_df = pd.DataFrame(ev_rows).sort_values(["buy_date", "code"]).reset_index(drop=True)
    rot_df = pd.DataFrame(rot_rows).sort_values(["buy_date", "code"]).reset_index(drop=True)
    ev_df.to_parquet(f"{RD045_DIR}/track2_bse_events_pit.parquet", index=False, compression="snappy")
    rot_df.to_parquet(f"{RD045_DIR}/track2_bse_rot_panel_pit.parquet", index=False, compression="snappy")
    rss = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
    print(f"[Step2A DONE {time.time()-t0:.1f}s | RSS={rss}MB] events={len(ev_df)}, rot_panel={len(rot_df)}")
    return ev_df, rot_df


if __name__ == "__main__":
    build_bse_v2_datasets()
