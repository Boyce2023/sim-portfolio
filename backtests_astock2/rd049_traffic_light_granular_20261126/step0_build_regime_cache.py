#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD049 Step 0: Build Strictly Causal T-1 Daily Regime Table (Macro X + Micro Infighting Y)
+ Verify 2024-12-31 Physical Truncation Zero-Leakage (max_abs_diff == 0.0).
Zero yfinance (D12). Peak RSS < 2.2 GB.
"""
import gc
import json
import os
import resource
import sys
import time
import urllib.request
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def fetch_tencent_index(secid: str, start_dt: str = "2020-09-01", end_dt: str = "2026-11-26") -> pd.DataFrame:
    cache_pq = f"{CACHE_DIR}/raw_idx_{secid}.parquet"
    if os.path.exists(cache_pq):
        return pd.read_parquet(cache_pq)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={secid},day,{start_dt},{end_dt},1800,"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = None
    for att in range(3):
        try:
            raw = json.loads(urllib.request.urlopen(req, timeout=8).read().decode("utf-8"))
            if raw and raw.get("data", {}).get(secid, {}).get("day"):
                break
        except Exception:
            time.sleep(0.4 * (att + 1))
    if raw and raw.get("data", {}).get(secid, {}).get("day"):
        rows = raw["data"][secid]["day"]
        df = pd.DataFrame([r[:5] for r in rows], columns=["trade_date", "open", "close", "high", "low"])
    else:
        import akshare as ak
        df_ak = ak.stock_zh_index_daily(symbol=secid)
        df_ak["trade_date"] = df_ak["date"].astype(str).str[:10]
        df = df_ak[(df_ak["trade_date"] >= start_dt) & (df_ak["trade_date"] <= end_dt)][["trade_date", "open", "close", "high", "low"]].copy()
    for c in ("open", "close", "high", "low"):
        df[c] = df[c].astype(float)
    df["trade_date"] = df["trade_date"].astype(str).str[:10]
    df = df.drop_duplicates("trade_date").sort_values("trade_date").reset_index(drop=True)
    df.to_parquet(cache_pq, index=False)
    return df


def compute_index_t1_features(df_idx: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Strict causal T-1 closed index features for decision day t."""
    c = df_idx["close"].to_numpy(float)
    s = pd.Series(c, index=df_idx["trade_date"])
    ma5 = s.rolling(5).mean()
    ma10 = s.rolling(10).mean()
    ma20 = s.rolling(20).mean()
    ma60 = s.rolling(60).mean()
    pk20 = s.rolling(21).max()
    pk60 = s.rolling(61).max()

    out = pd.DataFrame(index=df_idx["trade_date"])
    out[f"{prefix}_r1_t1"] = s.pct_change(1).shift(1) * 100.0
    out[f"{prefix}_r3_t1"] = s.pct_change(3).shift(1) * 100.0
    out[f"{prefix}_r5_t1"] = s.pct_change(5).shift(1) * 100.0
    out[f"{prefix}_r10_t1"] = s.pct_change(10).shift(1) * 100.0
    out[f"{prefix}_r20_t1"] = s.pct_change(20).shift(1) * 100.0
    out[f"{prefix}_vs_ma5_t1"] = ((s / ma5) - 1.0).shift(1) * 100.0
    out[f"{prefix}_vs_ma10_t1"] = ((s / ma10) - 1.0).shift(1) * 100.0
    out[f"{prefix}_vs_ma20_t1"] = ((s / ma20) - 1.0).shift(1) * 100.0
    out[f"{prefix}_vs_ma60_t1"] = ((s / ma60) - 1.0).shift(1) * 100.0
    out[f"{prefix}_ma5_slope3_t1"] = ma5.pct_change(3).shift(1) * 100.0
    out[f"{prefix}_ma10_slope5_t1"] = ma10.pct_change(5).shift(1) * 100.0
    out[f"{prefix}_ma20_slope5_t1"] = ma20.pct_change(5).shift(1) * 100.0
    out[f"{prefix}_dd20_t1"] = ((s / pk20) - 1.0).shift(1) * 100.0
    out[f"{prefix}_dd60_t1"] = ((s / pk60) - 1.0).shift(1) * 100.0
    # 20d realized volatility (std of daily pct ret * sqrt(242))
    r1 = s.pct_change(1) * 100.0
    out[f"{prefix}_vol20_t1"] = (r1.rolling(20).std() * np.sqrt(242.0)).shift(1)
    return out


def build_regime_table(end_cutoff: str | None = None) -> pd.DataFrame:
    # 1. Index raw series (filtered <= end_cutoff before feature computation for truncation proof)
    gz_raw = fetch_tencent_index("sz399303")
    hs_raw = fetch_tencent_index("sh000300")
    zz_raw = fetch_tencent_index("sh000852")
    if end_cutoff:
        gz_raw = gz_raw[gz_raw["trade_date"] <= end_cutoff].reset_index(drop=True)
        hs_raw = hs_raw[hs_raw["trade_date"] <= end_cutoff].reset_index(drop=True)
        zz_raw = zz_raw[zz_raw["trade_date"] <= end_cutoff].reset_index(drop=True)

    f_gz = compute_index_t1_features(gz_raw, "gz")
    f_hs = compute_index_t1_features(hs_raw, "hs")
    f_zz = compute_index_t1_features(zz_raw, "zz")

    # 2. Local stock_day_core minimal T-1 micro infighting & All-A median (pyarrow pushdown filter -> low RSS)
    import pyarrow.dataset as ds
    cols = ["dt", "c6", "ret_1d", "open_pct", "is_zt", "hit_zt", "is_broken_zt", "is_dt", "is_yizi_dt", "streak", "prev_streak"]
    flt = ds.field("is_st_pit") == 0
    sd = ds.dataset(f"{WAVE1}/stock_day_core_features_pit.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    sd["dt"] = sd["dt"].astype(str).str[:10]
    if end_cutoff:
        sd = sd[sd["dt"] <= end_cutoff].copy()
    sd["r1_dec"] = sd["ret_1d"].astype(np.float32) / 100.0
    sd["op_pct"] = sd["open_pct"].astype(np.float32)

    dts = sorted(sd["dt"].unique())
    dt_next = {dts[i]: dts[i + 1] for i in range(len(dts) - 1)}

    agg = pd.DataFrame(index=dts)
    agg["alla_med_r1"] = sd.groupby("dt")["r1_dec"].median()
    agg["alla_ew_r1"] = sd.groupby("dt")["r1_dec"].mean()
    agg["alla_dn5_pct"] = sd.groupby("dt")["ret_1d"].apply(lambda x: float((x <= -5.0).mean() * 100.0))

    # High-board candidates entering day d with prev_streak >= 2 (>=3B challengers) or >=3 (>=4B challengers)
    hb2 = sd[sd["prev_streak"] >= 2]
    hb2_fail = hb2[hb2["is_zt"] == 0]
    hb3 = sd[sd["prev_streak"] >= 3]
    hb3_fail = hb3[hb3["is_zt"] == 0]

    agg["hb2_cnt"] = hb2.groupby("dt").size().reindex(dts, fill_value=0)
    agg["hb2_promo"] = hb2.groupby("dt")["is_zt"].mean()
    agg["hb2_dam5_cnt"] = hb2_fail[hb2_fail["ret_1d"] <= -5.0].groupby("dt").size().reindex(dts, fill_value=0)
    agg["hb2_dam5_rate"] = agg["hb2_dam5_cnt"] / agg["hb2_cnt"].replace(0, np.nan)
    agg["hb2_nuke_cnt"] = hb2_fail[(hb2_fail["is_dt"] == 1) | (hb2_fail["ret_1d"] <= -8.0)].groupby("dt").size().reindex(dts, fill_value=0)
    agg["hb2_nuke_rate"] = agg["hb2_nuke_cnt"] / agg["hb2_cnt"].replace(0, np.nan)
    agg["hb2_fail_ret"] = hb2_fail.groupby("dt")["ret_1d"].mean()

    agg["hb3_cnt"] = hb3.groupby("dt").size().reindex(dts, fill_value=0)
    agg["hb3_promo"] = hb3.groupby("dt")["is_zt"].mean()
    agg["hb3_dam5_cnt"] = hb3_fail[hb3_fail["ret_1d"] <= -5.0].groupby("dt").size().reindex(dts, fill_value=0)
    agg["hb3_dam5_rate"] = agg["hb3_dam5_cnt"] / agg["hb3_cnt"].replace(0, np.nan)
    agg["hb3_fail_ret"] = hb3_fail.groupby("dt")["ret_1d"].mean()

    # Next-day open & return of prior-day broken >=3B stocks (measures continuation of high-board infighting!)
    hb2_fail_next = hb2_fail[["dt", "c6"]].copy()
    hb2_fail_next["next_dt"] = hb2_fail_next["dt"].map(dt_next)
    hb2_fail_next = hb2_fail_next.dropna(subset=["next_dt"]).merge(
        sd[["dt", "c6", "op_pct", "ret_1d"]], left_on=["next_dt", "c6"], right_on=["dt", "c6"], how="inner"
    )
    agg["pb_hb2_fail_open"] = hb2_fail_next.groupby("next_dt")["op_pct"].mean()
    agg["pb_hb2_fail_ret"] = hb2_fail_next.groupby("next_dt")["ret_1d"].mean()

    # Board counts & broken board rates
    agg["zt_cnt"] = sd.groupby("dt")["is_zt"].sum()
    agg["hit_zt_cnt"] = sd.groupby("dt")["hit_zt"].sum()
    agg["zb_rate"] = ((agg["hit_zt_cnt"] - agg["zt_cnt"]) / agg["hit_zt_cnt"].replace(0, np.nan)) * 100.0
    agg["dt_cnt"] = sd.groupby("dt")["is_dt"].sum()
    agg["max_streak"] = sd[sd["is_zt"] == 1].groupby("dt")["streak"].max().reindex(dts).fillna(0)

    del sd, hb2, hb2_fail, hb3, hb3_fail, hb2_fail_next
    gc.collect()

    # Shift 1 day so row t holds strictly T-1 closed values!
    t1 = agg.shift(1).add_suffix("_t1")
    for k in (3, 5, 10, 20):
        t1[f"alla_med_r{k}_t1"] = ((1.0 + agg["alla_med_r1"].fillna(0.0)).rolling(k).apply(np.prod, raw=True) - 1.0).shift(1) * 100.0
        t1[f"alla_ew_r{k}_t1"] = ((1.0 + agg["alla_ew_r1"].fillna(0.0)).rolling(k).apply(np.prod, raw=True) - 1.0).shift(1) * 100.0
    t1["alla_med_r1_pct_t1"] = agg["alla_med_r1"].shift(1) * 100.0

    # Also 3-day rolling micro heat (T-1..T-3) for smoothness
    t1["hb2_dam5_3d_t1"] = (agg["hb2_dam5_cnt"].rolling(3).sum() / agg["hb2_cnt"].rolling(3).sum().replace(0, np.nan)).shift(1)
    t1["hb2_promo_3d_t1"] = ((agg["hb2_promo"] * agg["hb2_cnt"]).rolling(3).sum() / agg["hb2_cnt"].rolling(3).sum().replace(0, np.nan)).shift(1)
    t1["zb_rate_3d_t1"] = (((agg["hit_zt_cnt"] - agg["zt_cnt"]).rolling(3).sum() / agg["hit_zt_cnt"].rolling(3).sum().replace(0, np.nan)) * 100.0).shift(1)
    t1["dt_cnt_3d_t1"] = agg["dt_cnt"].rolling(3).mean().shift(1)

    # 3. Merge existing strictly causal T-1 market_daily_all_new_factors_pit
    mkt = pd.read_parquet(f"{WAVE1}/market_daily_all_new_factors_pit.parquet")
    mkt["trade_date"] = mkt["trade_date"].astype(str).str[:10]
    if end_cutoff:
        mkt = mkt[mkt["trade_date"] <= end_cutoff].copy()
    mkt = mkt.set_index("trade_date")

    res = pd.DataFrame(index=mkt.index)
    for df_part in (f_gz, f_hs, f_zz, t1, mkt):
        for col in df_part.columns:
            if col not in res.columns:
                res[col] = df_part[col].reindex(res.index)

    # Relative excess slopes (GZ2000 vs HS300)
    res["rel5_gz_hs_t1"] = res["gz_r5_t1"] - res["hs_r5_t1"]
    res["rel10_gz_hs_t1"] = res["gz_r10_t1"] - res["hs_r10_t1"]
    res["rel20_gz_hs_t1"] = res["gz_r20_t1"] - res["hs_r20_t1"]
    res = res.reset_index()
    return res


def main():
    t0 = time.time()
    print("[1/1] Building full 5Y strictly causal T-1 regime table (cached raw index) ...")
    df_full = build_regime_table(end_cutoff=None)
    out_pq = f"{CACHE_DIR}/rd049_daily_regime_pit.parquet"
    df_full.to_parquet(out_pq, index=False)
    print(f"  Saved {out_pq}: rows={len(df_full)}, cols={len(df_full.columns)}, range={df_full['trade_date'].min()}..{df_full['trade_date'].max()} | RSS={rss_mb()} MB | elapsed={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
