#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-A Front 1 Step 1:
  1. Audit exact raw 5m coverage of `all_strategies_5m_complete_pit.parquet`
     (= `cand_5m_bars_v15_complete.parquet`, MD5 verified identical) over
     `pool_2to3_master_pit.parquet` and `pool_20cm_master_pit.parquet`
     (including RD036 Stack and Blend).
  2. Backfill missing (code, buy_date) 5m bars for 2to3 (v20_score >= 90) and
     20cm (all 809 rows) via Baostock (adjustflag='3', zero yfinance),
     strictly cross-validated against `a_daily.parquet` & `a_delisted_daily.parquet`.
  3. Reconstruct exact RD036 Stack & Blend scores and verify 100% 09:25 baseline parity:
     - 2to3: 95t / 404.71x (20bps 5Y); WF 66t / 36.98x / MTM Sharpe 2.304 (30bps)
     - 20cm S82: 199t / 468.29x (30bps full); WF 120t / 21.45x / MTM Sharpe 1.737
     - 20cm Stack: WF 129t / 125.96x / MTM Sharpe 2.385
     - 20cm Blend: WF 135t / 146.36x / MTM Sharpe 2.413
  4. Save lean cache in `front1_2to3_20cm_cond/` (Peak RSS < 2.0 GB, threads <= 2).
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import hashlib
import json
import math
import pickle
import resource
import sys
import time
import warnings

import baostock as bs
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(2)
pa.set_io_thread_count(2)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

bs.common.contants.BAOSTOCK_SERVER_IP = "114.94.20.42"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
RD036_P1 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
OUT_DIR = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front1_2to3_20cm_cond"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (RD036_P1, WAVE1, RD028, PARTC_V20):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_sim_and_metrics as wfm
import rd036_lib as lib20
import step4_mod_rules_and_sim as m1

PATH_5M_MAIN = f"{SIM}/data/all_strategies_5m_complete_pit.parquet"
PATH_5M_CAND = f"{SIM}/data/cand_5m_bars_v15_complete.parquet"
PATH_PATCH_5M = f"{OUT_DIR}/_cache_5m_baostock_patch.parquet"
PATH_CACHE_OUT = f"{OUT_DIR}/_cache_rd039_f1_inputs.pkl"
TRD_DAYS_YEAR = 242.0


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_exact_daily_mtm(
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    dmap: dict,
    ret_col: str,
    buy_px_raw_col: str = "eff_buy_raw",
) -> tuple[np.ndarray, float]:
    """
    Exact daily close-to-close bar MTM aligned to `cal_dts` (`mtm_diff == 0.0`),
    cancellable adjf on buy_date via raw `eff_buy_raw` and `dmap[(c6, dt)]`.
    """
    T = len(cal_dts)
    if slot_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    for r in slot_df.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi = dt_idx.get(bd)
        ei = dt_idx.get(ed)
        if bi is None:
            continue
        c6 = str(r.code).zfill(6)
        bb = dmap.get((c6, bd))
        bp_raw = float(getattr(r, buy_px_raw_col))
        adjf_b = bb["adjf"] if bb else 1.0
        b_adj = bp_raw * adjf_b
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        for t in range(bi, end_loop):
            bt = dmap.get((c6, cal_dts[t]))
            cur_c = bt["adj_close"] if (bt and bt["adj_close"] > 0) else last_c
            day_mult[t] *= (cur_c / prev_v)
            prev_v, last_c = cur_c, cur_c
        ret_v = float(getattr(r, ret_col))
        if ei is not None and ei > bi:
            day_mult[ei] *= (b_adj * (1.0 + ret_v)) / prev_v
    dr = day_mult - 1.0
    tr_sub = slot_df[slot_df["buy_date"].isin(dt_idx)]
    tr_nav = float(np.prod(1.0 + tr_sub[ret_col].to_numpy(float))) if not tr_sub.empty else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def fetch_missing_5m_baostock(
    targets: list[tuple[str, str]],
    dmap: dict,
) -> pd.DataFrame:
    """
    Fetch missing 5m bars via Baostock (adjustflag='3'), verify against daily OHLC,
    and normalize any split factor if daily open differs >2%.
    """
    if os.path.exists(PATH_PATCH_5M):
        old_df = pd.read_parquet(PATH_PATCH_5M)
        old_df["c6"] = old_df["c6"].astype(str).str.zfill(6)
        old_df["date"] = old_df["date"].astype(str).str[:10]
        have = set(zip(old_df["c6"], old_df["date"]))
        todo = [k for k in targets if k not in have]
    else:
        old_df = pd.DataFrame()
        todo = list(targets)

    print(f"  [Baostock] Total targets={len(targets)}, already cached={len(targets)-len(todo)}, to_fetch={len(todo)}")
    if not todo:
        return old_df

    lg = bs.login()
    assert lg.error_code == "0", f"Baostock login fail: {lg.error_msg}"
    rows_out = []
    failed = []
    t0 = time.time()
    try:
        for idx, (c6, dt) in enumerate(todo, 1):
            bc = f"sh.{c6}" if c6.startswith(("60", "68")) else f"sz.{c6}"
            fetched = []
            for attempt in range(3):
                rs = bs.query_history_k_data_plus(
                    bc,
                    "date,time,open,high,low,close,volume,amount",
                    start_date=dt,
                    end_date=dt,
                    frequency="5",
                    adjustflag="3",
                )
                if rs.error_code == "0":
                    while rs.next():
                        fetched.append(rs.get_row_data())
                    break
                time.sleep(0.3)
            if not fetched:
                failed.append((c6, dt))
                continue
            for rr in fetched:
                # rr: [date, time(YYYYMMDDHHMMSS000), open, high, low, close, volume, amount]
                hh_s = str(rr[1])[8:12]
                rows_out.append((
                    c6,
                    dt,
                    int(hh_s),
                    float(rr[2] or 0.0),
                    float(rr[3] or 0.0),
                    float(rr[4] or 0.0),
                    float(rr[5] or 0.0),
                    float(rr[6] or 0.0),
                    float(rr[7] or 0.0),
                ))
            if idx % 100 == 0 or idx == len(todo):
                print(f"    ... fetched {idx}/{len(todo)} ({len(rows_out)} bars, failed={len(failed)}) in {time.time()-t0:.1f}s", flush=True)
    finally:
        bs.logout()

    new_df = pd.DataFrame(rows_out, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
    if not old_df.empty and not new_df.empty:
        comb = pd.concat([old_df, new_df], ignore_index=True)
    elif not new_df.empty:
        comb = new_df
    else:
        comb = old_df
    comb = comb.drop_duplicates(["c6", "date", "hhmm_int"], keep="last").sort_values(["c6", "date", "hhmm_int"]).reset_index(drop=True)
    comb.to_parquet(PATH_PATCH_5M, index=False)
    print(f"  [Baostock] Saved {len(comb)} total bars -> {PATH_PATCH_5M} (failed={len(failed)})")
    return comb


def main():
    t0 = time.time()
    print("[Step 1] Auditing MD5 and loading master pools ...")
    md5_main = md5_file(PATH_5M_MAIN)
    md5_cand = md5_file(PATH_5M_CAND)
    print(f"  MD5 all_strategies_5m_complete_pit = {md5_main}")
    print(f"  MD5 cand_5m_bars_v15_complete      = {md5_cand} (identical={md5_main == md5_cand})")

    # 1. Load 2to3 pools
    p23_m = pd.read_parquet(f"{WAVE1}/pool_2to3_master_pit.parquet", columns=[
        "buy_date", "exit_date", "sig_date", "code", "name", "v20_score", "orig_score",
        "is_pass_official", "net_ret", "buy_hhmm", "exit_hhmm", "buy_price", "exit_price",
        "sim_ok", "open_pct", "plate",
    ]).sort_values(["buy_date", "code"]).reset_index(drop=True)
    p23_oh = pd.read_parquet(f"{RD028}/pool_2to3_oldhot.parquet", columns=[
        "buy_date", "code", "prev_close", "buyable_open", "prev_is_yizi", "plate_sz", "sealed_3b",
    ]).sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert (p23_m["buy_date"] == p23_oh["buy_date"]).all() and (p23_m["code"] == p23_oh["code"]).all()
    for c in ("prev_close", "buyable_open", "prev_is_yizi", "plate_sz", "sealed_3b"):
        p23_m[c] = p23_oh[c].values
    p23_m["code"] = p23_m["code"].astype(str).str.zfill(6)
    p23_m["buy_date"] = p23_m["buy_date"].astype(str).str[:10]
    p23_m["exit_date"] = p23_m["exit_date"].astype(str).str[:10]
    p23_m["net_ret_20"] = pd.to_numeric(p23_m["net_ret"], errors="coerce").astype(float)
    p23_m["gross_ret"] = (1.0 + p23_m["net_ret_20"]) / 0.9980 - 1.0
    p23_m["net_ret_30"] = (1.0 + p23_m["gross_ret"]) * 0.9970 - 1.0
    p23_m["net_ret_50"] = (1.0 + p23_m["gross_ret"]) * 0.9950 - 1.0
    p23_m["net_ret_80"] = (1.0 + p23_m["gross_ret"]) * 0.9920 - 1.0
    p23_90 = p23_m[p23_m["v20_score"] >= 90.0].copy().reset_index(drop=True)
    assert len(p23_90) == 138

    # 2. Load 20cm master & reconstruct RD036 Stack & Blend scores
    print("[Step 1] Reconstructing RD036 Stack & Blend causal scores on pool_20cm_master_pit ...")
    p20, meta20 = lib20.load_20cm_enriched_data()
    p20["wf_in_window"] = p20["buy_date"] >= "2023-01-03"
    dm_cb, _ = lib20.run_mode_b_multi_grid(p20, meta20["feat_clean_b"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)
    dm_mn, _ = lib20.run_mode_b_multi_grid(p20, meta20["ix_cols"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=0, top_k=10)
    ho_res = lib20.run_causal_highorder_and_tree_wf(
        p20,
        atomic_cols=meta20["atomic_cols"],
        extra_static_cols=meta20["feat_union_cb_mech"],
        wf_start_date="2023-01-03",
        min_warmup_trades=80,
        deltas=(12,),
        enable_4way=False,
    )
    c50 = p20["v20_cold50"].to_numpy(float)
    d_cb15 = dm_cb[("v20_cold50", 15)]
    d_mn15 = dm_mn[("v20_cold50", 15)]
    d_3w12 = ho_res["rule_deltas"][("Rule3Way", 12)]
    sc_blend_wf = c50 + np.round(0.5 * d_cb15 + 0.5 * d_mn15)
    sc_stack_wf = c50 + np.round((d_cb15 + d_mn15 + d_3w12) / 3.0)

    # Also keep clean lean columns on p20
    p20_oh = pd.read_parquet(f"{RD028}/pool_20cm_oldhot.parquet", columns=[
        "buy_date", "code", "buy_px", "exit_px", "gross_ret", "exit_reason", "dl", "open_pct",
    ])
    p20_oh["buy_date"] = p20_oh["buy_date"].astype(str).str[:10]
    p20_oh["code"] = p20_oh["code"].astype(str).str.zfill(6)
    p20["sc_v20"] = p20["v20_score"].to_numpy(float)
    p20["sc_blend"] = np.where(p20["buy_date"] >= "2023-01-03", sc_blend_wf, np.where(p20["v20_score"] >= 82.0, p20["v20_score"], -999.0))
    p20["sc_stack"] = np.where(p20["buy_date"] >= "2023-01-03", sc_stack_wf, np.where(p20["v20_score"] >= 82.0, p20["v20_score"], -999.0))
    p20["sc_cold50"] = c50
    p20["exit_hhmm"] = np.where(p20["exit_reason"].astype(str).str.contains("open|gap|tp"), 1030, 1500)
    keep20 = [
        "buy_date", "exit_date", "sig_date", "code", "name",
        "sc_v20", "sc_blend", "sc_stack", "sc_cold50",
        "buy_px", "gross_ret", "net_ret_30", "net_ret_50", "net_ret_80",
        "exit_hhmm", "exit_reason", "open_pct", "can_buy_hygiene", "sd_amount_yi_t1",
        "L1_weekday", "mkt10_zt_est_t1",
    ]
    df20 = p20[keep20].merge(p20_oh[["buy_date", "code", "exit_px", "dl"]], on=["buy_date", "code"], how="left")
    del p20, dm_cb, dm_mn, ho_res
    gc.collect()

    # 3. Audit raw local 5m coverage BEFORE patching
    print("[Step 1] Auditing raw local 5m coverage ...")
    all_codes = sorted(set(p23_m["code"]).union(set(df20["code"])))
    df5_main = pd.read_parquet(PATH_5M_MAIN, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
    df5_main["c6"] = df5_main["c6"].astype(str).str.zfill(6)
    df5_main["date"] = df5_main["date"].astype(str).str[:10]
    df5_sub = df5_main[df5_main["c6"].isin(all_codes)].copy()
    local_pairs = set(zip(df5_main["c6"], df5_main["date"]))
    del df5_main
    gc.collect()

    def _cov(sub_df: pd.DataFrame) -> dict:
        n = len(sub_df)
        h = sum((c, d) in local_pairs for c, d in zip(sub_df["code"], sub_df["buy_date"]))
        return {"total": int(n), "has_local_5m": int(h), "missing": int(n - h), "coverage_pct": round(h / max(1, n) * 100.0, 2)}

    cov_audit = {
        "main_5m_file": PATH_5M_MAIN,
        "cand_5m_file": PATH_5M_CAND,
        "md5_identical": (md5_main == md5_cand),
        "2to3_all_1532": _cov(p23_m),
        "2to3_v20ge90_all": _cov(p23_90),
        "2to3_v20ge90_wf": _cov(p23_90[p23_90["buy_date"] >= "2023-01-03"]),
        "20cm_all_809": _cov(df20),
        "20cm_s82_all": _cov(df20[df20["sc_v20"] >= 82.0]),
        "20cm_s82_5y": _cov(df20[(df20["sc_v20"] >= 82.0) & (df20["buy_date"] >= "2021-11-16")]),
        "20cm_s82_wf": _cov(df20[(df20["sc_v20"] >= 82.0) & (df20["buy_date"] >= "2023-01-03")]),
        "20cm_stack_wf": _cov(df20[(df20["sc_stack"] >= 80.0) & (df20["buy_date"] >= "2023-01-03")]),
        "20cm_blend_wf": _cov(df20[(df20["sc_blend"] >= 80.0) & (df20["buy_date"] >= "2023-01-03")]),
        "20cm_2024_2026_wf": _cov(df20[(df20["sc_v20"] >= 82.0) & (df20["buy_date"] >= "2024-01-01")]),
    }
    for k, v in cov_audit.items():
        if isinstance(v, dict):
            print(f"  {k:22s}: {v['has_local_5m']:4d} / {v['total']:4d} ({v['coverage_pct']:5.2f}%)")

    # 4. Load daily bars for all needed codes across [2020-12-01 .. 2026-11-25]
    print("[Step 1] Loading daily bars for exact open/pre_c/zt_px & daily MTM ...")
    tks = sorted([f"{c}.SH" for c in all_codes] + [f"{c}.SZ" for c in all_codes])
    cols_d = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt_d = (ds.field("date") >= pd.Timestamp("2020-12-01")) & (ds.field("ticker").isin(tks))
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols_d, filter=flt_d).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols_d, filter=flt_d).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    del da, dd
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp[dp["ticker"].astype(str).str.endswith((".SH", ".SZ")) & (dp["close"] > 0) & (dp["adj_close"] > 0)].copy()
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = dp["adj_close"] / dp["close"]
    g = dp.groupby("c6", sort=False)
    dp["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / dp["adjf"]
    lim = np.where(dp["c6"].str.startswith(("300", "301", "688", "689")), 0.20, 0.10)
    dp["zt_px"] = np.floor(dp["pre_c"] * (1.0 + lim) * 100.0 + 0.5 + 1e-9) / 100.0
    dp["dt_px"] = np.floor(dp["pre_c"] * (1.0 - lim) * 100.0 + 0.5 + 1e-9) / 100.0

    dmap = {
        (r.c6, r.dt): {
            "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close),
            "adj_close": float(r.adj_close), "adjf": float(r.adjf),
            "pre_c": float(r.pre_c) if pd.notna(r.pre_c) else np.nan,
            "zt_px": float(r.zt_px) if pd.notna(r.zt_px) else np.nan,
            "dt_px": float(r.dt_px) if pd.notna(r.dt_px) else np.nan,
        }
        for r in dp.itertuples(index=False)
    }
    del dp
    gc.collect()

    # Enrich p23_90 and df20 with exact daily fields
    p23_90["open_d"] = [dmap[(r.code, r.buy_date)]["open"] for r in p23_90.itertuples(index=False)]
    p23_90["pre_c"] = [dmap[(r.code, r.buy_date)]["pre_c"] for r in p23_90.itertuples(index=False)]
    p23_90["zt_px"] = [dmap[(r.code, r.buy_date)]["zt_px"] for r in p23_90.itertuples(index=False)]
    p23_90["has_local_5m"] = [(r.code, r.buy_date) in local_pairs for r in p23_90.itertuples(index=False)]

    df20["open_d"] = [dmap[(r.code, r.buy_date)]["open"] for r in df20.itertuples(index=False)]
    df20["pre_c"] = [dmap[(r.code, r.buy_date)]["pre_c"] for r in df20.itertuples(index=False)]
    df20["zt_px"] = [dmap[(r.code, r.buy_date)]["zt_px"] for r in df20.itertuples(index=False)]
    df20["has_local_5m"] = [(r.code, r.buy_date) in local_pairs for r in df20.itertuples(index=False)]

    # 5. Backfill missing 5m bars via Baostock for ALL 2to3(>=90) + ALL 20cm(809)
    print("[Step 1] Backfilling missing 5m bars via Baostock (strictly into front1 cache) ...")
    need_pairs = sorted(
        {(r.code, r.buy_date) for r in p23_90.itertuples(index=False)}
        | {(r.code, r.buy_date) for r in df20.itertuples(index=False)}
    )
    missing_targets = [k for k in need_pairs if k not in local_pairs]
    patch_df = fetch_missing_5m_baostock(missing_targets, dmap)

    # Build normalized bars_5m_local and bars_5m_full
    def _build_bar_dict(df_in: pd.DataFrame) -> tuple[dict, dict]:
        out = {}
        stats = {"total_days": 0, "rescaled_days": 0, "close_mismatch_gt1pct": 0, "bad_bar_count": 0}
        df_s = df_in.sort_values(["c6", "date", "hhmm_int"])
        for (c6, dt), grp in df_s.groupby(["c6", "date"], sort=False):
            key = (c6, dt)
            if key not in set(need_pairs):
                continue
            arr = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=np.float64)
            if len(arr) < 12:
                stats["bad_bar_count"] += 1
                continue
            db = dmap.get(key)
            if db is not None and db["open"] > 0 and arr[0, 1] > 0:
                if abs(arr[0, 1] / db["open"] - 1.0) > 0.015:
                    scale = db["open"] / arr[0, 1]
                    arr = arr.copy()
                    arr[:, 1:5] *= scale
                    arr[:, 6] *= scale
                    stats["rescaled_days"] += 1
                if abs(arr[-1, 4] / db["close"] - 1.0) > 0.01:
                    stats["close_mismatch_gt1pct"] += 1
            stats["total_days"] += 1
            out[key] = arr
        return out, stats

    bars_5m_local, st_loc = _build_bar_dict(df5_sub)
    bars_5m_patch, st_pat = _build_bar_dict(patch_df)
    bars_5m_full = dict(bars_5m_local)
    for k, v in bars_5m_patch.items():
        if k not in bars_5m_full:
            bars_5m_full[k] = v

    cov_23_full = sum((r.code, r.buy_date) in bars_5m_full for r in p23_90.itertuples(index=False))
    cov_20_full = sum((r.code, r.buy_date) in bars_5m_full for r in df20.itertuples(index=False))
    print(f"  [5m Validation] local={st_loc} | patch={st_pat}")
    print(f"  [Post-Backfill Coverage] 2to3(>=90)={cov_23_full}/{len(p23_90)} ({cov_23_full/len(p23_90)*100:.2f}%), 20cm(all)={cov_20_full}/{len(df20)} ({cov_20_full/len(df20)*100:.2f}%)")

    # 6. Load benchmark & calendars and verify 100% 09:25 baseline parity
    bench_df = pd.read_parquet(f"{WAVE1}/v20_daily_bench_20210104_20261125.parquet")
    bench_df = bench_df[bench_df["trade_date"] <= "2026-11-16"].sort_values("trade_date").reset_index(drop=True)
    cal_full = bench_df["trade_date"].tolist()
    cal_5y = [d for d in cal_full if "2021-11-16" <= d <= "2026-11-16"]
    cal_wf = [d for d in cal_full if "2023-01-03" <= d <= "2026-11-16"]

    # Parity 1: 2to3 09:25 baseline
    srt23 = p23_90.sort_values(["buy_date", "v20_score", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
    t23_idx, fed, feh = [], "", 0
    for r in srt23.itertuples():
        if (not fed) or (r.buy_date > fed) or (r.buy_date == fed and 925 > feh):
            t23_idx.append(r.Index)
            fed, feh = r.exit_date, int(r.exit_hhmm)
    sl23 = srt23.loc[t23_idx].copy()
    sl23["eff_buy_raw"] = sl23["open_d"]
    nav23_20 = float(np.prod(1.0 + sl23["net_ret_20"].to_numpy(float)))
    sl23_wf = sl23[sl23["buy_date"] >= "2023-01-03"].copy()
    dr23_wf, diff23 = build_exact_daily_mtm(sl23_wf, cal_wf, dmap, "net_ret_30")
    sh23_wf = float(np.mean(dr23_wf) / np.std(dr23_wf, ddof=1) * math.sqrt(TRD_DAYS_YEAR))
    nav23_wf = float(np.prod(1.0 + sl23_wf["net_ret_30"].to_numpy(float)))
    assert len(sl23) == 95 and abs(nav23_20 - 404.7082) < 0.05, (len(sl23), nav23_20)
    assert len(sl23_wf) == 66 and abs(nav23_wf - 36.9783) < 0.05 and abs(sh23_wf - 2.304) < 0.01 and diff23 < 1e-8, (len(sl23_wf), nav23_wf, sh23_wf, diff23)
    print(f"  [Parity 2to3 OK] 5Y@20bps: n={len(sl23)}, nav={nav23_20:.4f}x | WF@30bps: n={len(sl23_wf)}, nav={nav23_wf:.4f}x, Sharpe={sh23_wf:.3f}, mtm_diff={diff23:.2e}")

    # Parity 2: 20cm S82, Stack, Blend 09:25 baselines
    def _sim20(sc_col: str, thr: float, start_dt: str):
        sub = df20[df20["can_buy_hygiene"] & (df20["buy_date"] >= start_dt) & (df20[sc_col] >= thr)].copy()
        srt = sub.sort_values(["buy_date", sc_col, "code"], ascending=[True, False, True])
        ti, fd = [], ""
        for r in srt.itertuples():
            if (not fd) or (r.buy_date > fd):
                ti.append(r.Index)
                fd = r.exit_date
        sl = srt.loc[ti].copy()
        sl["eff_buy_raw"] = sl["open_d"]
        return sl

    sl20_full = _sim20("sc_v20", 82.0, "2021-01-04")
    sl20_wf = _sim20("sc_v20", 82.0, "2023-01-03")
    sl20_stk = _sim20("sc_stack", 80.0, "2023-01-03")
    sl20_bld = _sim20("sc_blend", 80.0, "2023-01-03")

    for lbl, sl, cal, exp_n, exp_nav, exp_sh in [
        ("20cm_S82_FULL", sl20_full, cal_full, 199, 468.2894, None),
        ("20cm_S82_WF", sl20_wf, cal_wf, 120, 21.4496, 1.737),
        ("20cm_Stack_WF", sl20_stk, cal_wf, 129, 125.9588, 2.385),
        ("20cm_Blend_WF", sl20_bld, cal_wf, 135, 146.3644, 2.413),
    ]:
        dr, df_m = build_exact_daily_mtm(sl, cal, dmap, "net_ret_30")
        nav = float(np.prod(1.0 + sl["net_ret_30"].to_numpy(float)))
        sh = float(np.mean(dr) / np.std(dr, ddof=1) * math.sqrt(TRD_DAYS_YEAR))
        assert len(sl) == exp_n and abs(nav - exp_nav) < 0.05 and df_m < 1e-8, (lbl, len(sl), nav, sh, df_m)
        if exp_sh is not None:
            assert abs(sh - exp_sh) < 0.005, (lbl, sh, exp_sh)
        print(f"  [Parity {lbl} OK] n={len(sl)}, nav={nav:.4f}x, Sharpe={sh:.3f}, mtm_diff={df_m:.2e}")

    # 7. Save lean master cache
    cache_obj = {
        "cov_audit": cov_audit,
        "bar_stats_local": st_loc,
        "bar_stats_patch": st_pat,
        "p23_90": p23_90,
        "p23_all_dates": p23_m[["buy_date", "exit_date", "code", "v20_score", "net_ret_30", "sim_ok"]].copy(),
        "df20": df20,
        "bars_5m_local": bars_5m_local,
        "bars_5m_full": bars_5m_full,
        "dmap": dmap,
        "bench_df": bench_df,
        "cal_full": cal_full,
        "cal_5y": cal_5y,
        "cal_wf": cal_wf,
    }
    with open(PATH_CACHE_OUT, "wb") as f:
        pickle.dump(cache_obj, f)

    print(f"[Step 1 DONE in {time.time()-t0:.1f}s | Peak RSS={rss_mb()} MB] Saved -> {PATH_CACHE_OUT}")
    assert rss_mb() < 2500.0, f"Peak RSS exceeded 2.5GB: {rss_mb()}"


if __name__ == "__main__":
    main()
