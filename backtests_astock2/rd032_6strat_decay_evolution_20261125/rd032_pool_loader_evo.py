#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Attach 40 strictly PIT candidate evolution features across all 6 V20.0 strategy pools."""
import json
import os
import sqlite3
import sys
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation!"
from rd032_common import ROOT, SIM


def attach_40_evo_features(pools: dict[str, pd.DataFrame], as_of: str, prev_td: dict, sh_idx: dict, sz_idx: dict) -> dict[str, pd.DataFrame]:
    all_codes = sorted({c for df in pools.values() for c in df["code"].unique()})

    # 1. Stock daily PIT features from a_daily + a_delisted_daily (up to as_of)
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    flt = (ds.field("date") >= pd.Timestamp("2020-09-01")) & (ds.field("date") <= pd.Timestamp(as_of))
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp = dp[dp["c6"].isin(all_codes) & dp["ticker"].astype(str).str.endswith((".SH", ".SZ")) & (dp["close"] > 0)].copy()
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp[dp["dt"] <= as_of].sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    dp["adjf"] = np.where(dp["adj_close"] > 0, dp["adj_close"] / dp["close"], 1.0)
    dp["ac"] = dp["close"] * dp["adjf"]
    dp["ah"] = dp["high"] * dp["adjf"]
    dp["al"] = dp["low"] * dp["adjf"]
    dp["ao"] = dp["open"] * dp["adjf"]
    g = dp.groupby("c6", sort=False)
    dp["pre_ac"] = g["ac"].shift(1)
    dp["o_pct_day"] = dp["ao"] / dp["pre_ac"] - 1.0
    dp["amt_yi"] = dp["amount"].fillna(0.0) / 1e8
    est_sh = np.where(dp["oshare"].fillna(0) > 0, dp["oshare"], np.where(dp["turn"] > 0, dp["volume"] / dp["turn"], np.nan))
    dp["mcap_yi"] = est_sh * dp["close"] / 1e8
    dp["amt_ma5_prev"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    dp["vol_ratio5"] = dp["amount"] / dp["amt_ma5_prev"].replace(0, np.nan)
    dp["max20"] = g["ah"].transform(lambda s: s.rolling(20, min_periods=5).max())
    dp["min20"] = g["al"].transform(lambda s: s.rolling(20, min_periods=5).min())
    dp["max60"] = g["ah"].transform(lambda s: s.rolling(60, min_periods=10).max())
    dp["amp20"] = (dp["max20"] - dp["min20"]) / dp["min20"].replace(0, np.nan)
    dp["pos20"] = (dp["ac"] - dp["min20"]) / (dp["max20"] - dp["min20"]).replace(0, np.nan)
    dp["dd60"] = dp["ac"] / dp["max60"].replace(0, np.nan) - 1.0
    dp["ret20"] = dp["ac"] / g["ac"].shift(20).replace(0, np.nan) - 1.0
    dp["t_ma5"] = g["turn"].transform(lambda s: s.rolling(5, min_periods=2).mean())
    dp["t_ma20"] = g["turn"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    dp["turn_5_20"] = dp["t_ma5"] / dp["t_ma20"].replace(0, np.nan)
    dp["day_amp"] = (dp["ah"] - dp["al"]) / dp["pre_ac"].replace(0, np.nan)
    dp["to_pct"] = dp["turn"].fillna(0.0) * 100.0

    # Index-based 10-day 100% headroom at sig_date close
    bar_idx = {}
    for c6, grp in dp.groupby("c6", sort=False):
        grp = grp.reset_index(drop=True)
        bar_idx[c6] = (grp["dt"].to_numpy(), dict(zip(grp["dt"], range(len(grp)))), grp)

    # 2. Top-10 lockup + ZT micro tape + LHB Bayes
    t10_raw = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"))
    t10_20 = json.load(open(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies/pit_top10_20cm_summary.json"))

    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    tape_m = {}
    for td, sc6, sa in con_z.execute("SELECT trade_date, sec_code, seal_amount FROM zt_micro_tape WHERE trade_date <= ?", (as_of,)):
        tape_m[(str(td), str(sc6).zfill(6))] = float(sa or 0.0)
    con_z.close()

    bay = pd.read_parquet(f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/bayes_seat_scores_d1_5y.parquet")
    bay["stock_code"] = bay["stock_code"].astype(str).str.zfill(6)
    bay = bay[(bay["date"] <= as_of) & bay["stock_code"].isin(all_codes)]
    bay_map = {}
    for (dt, sc), grp in bay.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(grp["NET"].to_numpy(float), 1.0)
        bay_map[(dt, sc)] = float(np.sum(w * grp["b_t2"].to_numpy(float)) / np.sum(w))

    # 3. Macro / market breadth panels (strictly shifted to prev_td[buy_date])
    p1 = pd.read_parquet(f"{ROOT}/output/china_policy_macro_rd027_20261125/data_pillars/pillar1_market_breadth_daily.parquet")
    p1["dt"] = pd.to_datetime(p1["date"]).dt.strftime("%Y-%m-%d")
    p1 = p1[p1["dt"] <= as_of].drop_duplicates("dt").set_index("dt")

    p2 = pd.read_parquet(f"{ROOT}/output/csrc_policy_100factors_20261114/policy_polymarket_v1/daily_market_panel_v2_20261124.parquet")
    p2["dt"] = pd.to_datetime(p2["date"]).dt.strftime("%Y-%m-%d")
    p2 = p2[p2["dt"] <= as_of].drop_duplicates("dt").set_index("dt")

    ix = pd.read_parquet(f"{SIM}/data/us_price_db/benchmarks/IXIC.parquet").sort_index()
    ix_df = pd.DataFrame({"us_dt": pd.to_datetime(ix.index).tz_localize(None).strftime("%Y-%m-%d"), "c": ix["adj_close"].to_numpy(float)}).drop_duplicates("us_dt")
    ix_df = ix_df[ix_df["us_dt"] <= as_of].reset_index(drop=True)
    ix_df["r1"] = ix_df["c"].pct_change(1)
    ix_df["r5"] = ix_df["c"].pct_change(5)
    vx = pd.read_parquet(f"{SIM}/data/us_price_db/benchmarks/VIX.parquet").sort_index()
    vx_df = pd.DataFrame({"us_dt": pd.to_datetime(vx.index).tz_localize(None).strftime("%Y-%m-%d"), "vc": vx["close"].to_numpy(float)}).drop_duplicates("us_dt")
    vx_df["vr1"] = vx_df["vc"].pct_change(1)
    us_df = ix_df.merge(vx_df[["us_dt", "vr1"]], on="us_dt", how="left").sort_values("us_dt").reset_index(drop=True)
    us_dts = us_df["us_dt"].to_numpy()

    def _lock10(c6, bd):
        recs = [x for x in (t10_20.get(c6, []) if c6.startswith(("30", "688", "689")) else t10_raw.get(c6, [])) if str(x[0])[:10] < bd]
        return float(max(recs, key=lambda x: str(x[1]))[2]) if recs else 38.0

    def _hr10(c6, grp, pos, op_adj):
        if pos < 1 or op_adj <= 0:
            return np.nan
        idx_d = sh_idx if c6.startswith("6") else sz_idx
        i_cur = idx_d.get(str(grp["dt"].iloc[pos]))
        if not i_cur:
            return np.nan
        mp = 999999.0
        for w in range(1, min(11, pos + 1)):
            bi = pos - w
            ib = idx_d.get(str(grp["dt"].iloc[bi]))
            bc = float(grp["ac"].iloc[bi])
            if ib and bc > 0:
                mp = min(mp, bc * (2.0 + (i_cur / ib - 1.0)))
        return float(np.clip(mp / op_adj - 1.0, -0.5, 3.0)) if mp < 999990.0 else np.nan

    out = {}
    for st, df in pools.items():
        rows = []
        for r in df.itertuples(index=False):
            c6, bd = r.code, r.buy_date
            d1 = prev_td.get(bd, "")
            dts_a, pos_m, grp = bar_idx.get(c6, (np.array([]), {}, None))
            pb = pos_m.get(bd, -1)
            pd1 = (pb - 1) if pb >= 1 else (int(np.searchsorted(dts_a, bd, side="left")) - 1 if len(dts_a) else -1)
            sd_eff = str(dts_a[pd1]) if (grp is not None and pd1 >= 0) else d1
            sr = grp.iloc[pd1] if (grp is not None and pd1 >= 0) else None
            br = grp.iloc[pb] if (grp is not None and pb >= 0) else None

            op_v = float(r.open_pct) if pd.notna(r.open_pct) else (float(br["o_pct_day"]) if (br is not None and pd.notna(br["o_pct_day"])) else np.nan)
            lk = _lock10(c6, bd)
            mcap = float(sr["mcap_yi"]) if sr is not None else np.nan
            fmcap = mcap * max(0.05, 1.0 - lk / 100.0) if np.isfinite(mcap) else np.nan
            amt_yi = float(sr["amt_yi"]) if sr is not None else np.nan
            to_r = float(sr["to_pct"]) / max(0.05, 1.0 - lk / 100.0) if sr is not None else np.nan
            d_amp = float(sr["day_amp"]) if sr is not None else np.nan
            op_adj = float(br["ao"]) if br is not None else np.nan

            r1 = p1.loc[d1] if d1 in p1.index else None
            r2 = p2.loc[d1] if d1 in p2.index else None
            ui = int(np.searchsorted(us_dts, bd, side="left")) - 1
            ur = us_df.iloc[ui] if ui >= 0 else None

            seal_amt = tape_m.get((sd_eff, c6), np.nan)
            seal_rat = (seal_amt / (amt_yi * 1e8)) if (np.isfinite(seal_amt) and np.isfinite(amt_yi) and amt_yi > 0) else np.nan

            rows.append({
                "evo_mcap_yi": mcap,
                "evo_free_mcap_yi": fmcap,
                "evo_lock_top10": lk,
                "evo_small_vs_large_20d": -float(r1["large10_minus_micro30_ret_20d"]) if (r1 is not None and pd.notna(r1["large10_minus_micro30_ret_20d"])) else np.nan,
                "evo_prev_amt_yi": amt_yi,
                "evo_prev_real_turn": to_r,
                "evo_vol_ratio5": float(sr["vol_ratio5"]) if sr is not None else np.nan,
                "evo_cum_turn_1y": float(r.cum_turnover_1y) if pd.notna(r.cum_turnover_1y) else np.nan,
                "evo_turn_5_20": float(sr["turn_5_20"]) if sr is not None else np.nan,
                "evo_amp20_d1": float(sr["amp20"]) if sr is not None else np.nan,
                "evo_dd60_d1": float(sr["dd60"]) if sr is not None else np.nan,
                "evo_dd1y_high": float(r.dd_from_1y_high) if pd.notna(r.dd_from_1y_high) else np.nan,
                "evo_dd3y_high": float(r.dd_from_3y_high) if pd.notna(r.dd_from_3y_high) else np.nan,
                "evo_pos20_d1": float(sr["pos20"]) if sr is not None else np.nan,
                "evo_ret20_d1": float(sr["ret20"]) if sr is not None else np.nan,
                "evo_mkt_zt_cnt_d1": float(r2["zt_cnt"]) if r2 is not None else np.nan,
                "evo_mkt_dt_cnt_d1": float(r2["dt_cnt"]) if r2 is not None else np.nan,
                "evo_mkt_broken_rate_d1": float(r2["broken_rate"]) if r2 is not None else np.nan,
                "evo_mkt_max_streak_d1": float(r2["max_zt_streak"]) if r2 is not None else np.nan,
                "evo_mkt_b3plus_cnt_d1": float(r2["b3plus_cnt"]) if r2 is not None else np.nan,
                "evo_waves_3y_g15": float(r.waves_3y_g15),
                "evo_zt_cnt_1y": float(r.zt_cnt_1y),
                "evo_comm_posts_1y_pct": float(r.comm_posts_1y_pct),
                "evo_xq_posts_1y_pct": float(r.xq_posts_1y_pct),
                "evo_trap_waves_3y": float(r.trap_waves_3y),
                "evo_cool_days_zt_log": float(np.log1p(r.cool_days_since_last_zt)) if pd.notna(r.cool_days_since_last_zt) else np.nan,
                "evo_mkt_amount_yi_d1": float(r1["total_amount_yi"]) if r1 is not None else np.nan,
                "evo_mkt_amount_ratio20_d1": float(r1["amount_ratio_20d"]) if r1 is not None else np.nan,
                "evo_mkt_pct_above_ma20_d1": float(r1["pct_above_ma20"]) if r1 is not None else np.nan,
                "evo_mkt_pct_above_ma60_d1": float(r1["pct_above_ma60"]) if r1 is not None else np.nan,
                "evo_mkt_etf_flow_5d": float(r2["etf_net_flow_5d_yi"]) if r2 is not None else np.nan,
                "evo_mkt_margin_pct": float(r1["margin_to_float_mcap_pct"]) if (r1 is not None and pd.notna(r1["margin_to_float_mcap_pct"])) else np.nan,
                "evo_us_ixic_ret1d": float(ur["r1"]) if (ur is not None and pd.notna(ur["r1"])) else np.nan,
                "evo_us_ixic_ret5d": float(ur["r5"]) if (ur is not None and pd.notna(ur["r5"])) else np.nan,
                "evo_us_vix_chg1d": float(ur["vr1"]) if (ur is not None and pd.notna(ur["vr1"])) else np.nan,
                "evo_open_pct": op_v,
                "evo_open_vs_d1_amp": (op_v / d_amp) if (np.isfinite(op_v) and np.isfinite(d_amp) and d_amp > 0.005) else np.nan,
                "evo_zt_seal_ratio_d1": seal_rat,
                "evo_lhb_bayes_t2_d1": float(bay_map.get((sd_eff, c6), 0.0)),
                "evo_hr10d_space": _hr10(c6, grp, pd1, op_adj),
            })
        out[st] = pd.concat([df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    return out
