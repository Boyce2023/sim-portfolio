#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Macro & daily-level PIT factors: Family 1 (NT V3), Family 2 (CSRC 22), Family 3 (US IXIC), Family 5 (15Y Style)."""
import os
import sys
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
CSRC_MODEL_DIR = f"{SIM}/backtests_astock2/csrc_policy_model"
if CSRC_MODEL_DIR not in sys.path:
    sys.path.insert(0, CSRC_MODEL_DIR)


def build_macro_daily_factors(all_dts: list[str], prev_td: dict) -> pd.DataFrame:
    # 1. Family 1: National Team V3.0 (strictly d-1 settled EOD)
    import csrc_v3_backtest_calibrate as nt_cal
    nt_raw = nt_cal.score_panel(nt_cal.load_master_panel())
    nt_raw = nt_raw[nt_raw["date"] >= "2021-01-01"].set_index("date")
    c10_s = nt_raw["core10_amt_spike"].fillna(0.0)
    e22_s = nt_raw["etf22_amt_spike"].fillna(0.0)
    spk = np.maximum(c10_s, e22_s)
    b4o = nt_raw["big4_oil_ret"].fillna(0.0)
    c1k = nt_raw["c1000_ret"].fillna(0.0)
    nt_raw["nt_etf_spike"] = spk
    nt_raw["nt_fake_support"] = ((spk < 1.3) & (((b4o - c1k) >= 0.020) | ((b4o >= 0.008) & (c1k <= -0.008)))).astype(int)
    nt_raw["nt_rd019_trap"] = ((spk >= 1.8) & (nt_raw["if0_spike"].fillna(0.0) >= 1.5) & (~nt_raw["is_deliv"].fillna(False))).astype(int)
    nt_raw["nt_t1_skew"] = nt_raw["t1_flow_yi"].fillna(0.0) - nt_raw["t2_flow_yi"].fillna(0.0)
    nt_raw["nt_t2_res"] = nt_raw["t2_flow_yi"].fillna(0.0)
    nt_raw["nt_f152_sync"] = ((nt_raw["t1_flow_yi"].fillna(0.0) >= 50.0) & (nt_raw["t2_flow_yi"].fillna(0.0) >= 25.0)).astype(int)
    nt_raw["nt_fund8_dump"] = nt_raw["fund8_dump_cnt"].fillna(0).astype(int)
    nt_raw["nt_wflow5d"] = nt_raw["etf22_wflow_5d"].fillna(0.0)
    nt_raw["nt_if0_basis"] = nt_raw["if0_basis_pct"].fillna(0.0)

    # 2. Family 2: CSRC Policy 22 Core (strictly tradable_date <= buy_date)
    mep = pd.read_parquet(f"{ROOT}/output/csrc_policy_100factors_20261114/backtest/master_events_pit.parquet")
    td_s = mep["tradable_date"].astype(str)
    mep["td_eff"] = np.where(td_s == "PENDING_NEXT_OPEN", "2026-11-16", td_s)
    mep = mep[mep["td_eff"] >= "2021-01-01"].copy()
    hl = mep["hard_levers_joined"].fillna("").astype(str)
    qu = mep["quotes_joined"].fillna("").astype(str)
    to_ = mep["title_or_occasion"].fillna("").astype(str)
    # Positive rescue/long-money/short-squeeze core signals (F015, F033, F062, F064, F115, F120, F143, F144)
    mep["ev_rescue"] = (
        ((mep["market_rescue_signal"] >= 2) & (mep["is_joint_ministry"] == 1))
        | (mep["quant_short_selling_tightening"] >= 2)
        | (mep["authority_level"] == "PBOC_HARD_TOOL")
        | hl.str.contains("PBOC_SFISF|HUIJIN_BUY|IPO_PAUSE", regex=True)
        | qu.str.contains("减少交易阻力|不干预正常交易", regex=True)
        | ((mep["days_in_office"] >= 0) & (mep["days_in_office"] <= 30))
    ).astype(int)
    # Hard tech & M&A tailwinds (F073, F077, F081, F133, F134)
    mep["ev_tech_ma"] = (
        ((mep["tech_innovation_support"] >= 2) | (mep["ma_restructuring_support"] >= 2))
        & (mep["prior_amt_pct_250d"].fillna(0.5) < 0.85)
    ).astype(int)
    # Headwind / Crackdown / Surveillance / Politburo omit (F009, F058, F121, F065/66)
    mep["ev_headwind"] = (
        (mep["speculation_fraud_crackdown"] >= 2)
        | (mep["authority_level"] == "EXCHANGE_SURVEILLANCE")
        | hl.str.contains("DELISTING_CRACKDOWN", regex=True)
        | ((mep["authority_level"] == "POLITBURO") & (~qu.str.contains("资本市场|股市|股票|投资者", regex=True)) & (mep["market_rescue_signal"] == 0))
    ).astype(int)
    # Large-cap dividend tilt vs microcap (F070, F096, F137)
    mep["ev_div_large"] = (
        ((mep["dividend_buyback_push"] >= 1) | (mep["liquidity_long_term_capital"] >= 1))
        & ((mep["speculation_fraud_crackdown"] >= 1) | (mep["share_reduction_crackdown"] >= 1))
    ).astype(int)

    pol_by_td = mep.groupby("td_eff")[["ev_rescue", "ev_tech_ma", "ev_headwind", "ev_div_large"]].sum().to_dict("index")

    # 3. Family 3: US Nasdaq Overnight (strictly us_date < buy_date)
    ix = pd.read_parquet(f"{SIM}/data/us_price_db/benchmarks/IXIC.parquet").sort_index()
    ix_dt = pd.to_datetime(ix.index).tz_localize(None).strftime("%Y-%m-%d")
    ix_df = pd.DataFrame({"us_dt": ix_dt, "ix_c": ix["adj_close"].to_numpy(float)}).drop_duplicates("us_dt")
    ix_df["ix_ret1"] = ix_df["ix_c"].pct_change(1)
    ix_df["ix_ret5"] = ix_df["ix_c"].pct_change(5)

    vx = pd.read_parquet(f"{SIM}/data/us_price_db/benchmarks/VIX.parquet").sort_index()
    vx_dt = pd.to_datetime(vx.index).tz_localize(None).strftime("%Y-%m-%d")
    vx_df = pd.DataFrame({"us_dt": vx_dt, "vx_c": vx["close"].to_numpy(float)}).drop_duplicates("us_dt")
    vx_df["vx_chg1"] = vx_df["vx_c"].pct_change(1)
    us_df = ix_df.merge(vx_df[["us_dt", "vx_chg1"]], on="us_dt", how="left").sort_values("us_dt").reset_index(drop=True)
    us_dts_arr = us_df["us_dt"].to_numpy()

    # 4. Family 5: 15Y Style Spreads (strictly d-1 settled)
    drs = pd.read_parquet(f"{SIM}/backtests_astock2/theory_backtest_15y_20261119/daily_ret_style.parquet").sort_index()
    drs.index = pd.to_datetime(drs.index).strftime("%Y-%m-%d")
    r_small = (1.0 + drs["小市值轮动_含退市检验"]).rolling(20, min_periods=10).apply(np.prod, raw=True) - 1.0
    r_big = (1.0 + drs["核心资产大蓝筹低波_茅指数本土化"]).rolling(20, min_periods=10).apply(np.prod, raw=True) - 1.0
    r_rev = (1.0 + drs["超跌反转效应_跌多了就买"]).rolling(20, min_periods=10).apply(np.prod, raw=True) - 1.0
    r_mom = (1.0 + drs["动量追强效应_强者恒强"]).rolling(20, min_periods=10).apply(np.prod, raw=True) - 1.0
    style_df = pd.DataFrame({"small_vs_big_20d": r_small - r_big, "rev_vs_mom_20d": r_rev - r_mom})

    # Assemble strictly PIT daily DataFrame indexed by buy_date in all_dts
    rows = []
    target_dts = [d for d in all_dts if "2021-10-01" <= d <= "2026-11-16"]
    td_pos = {d: i for i, d in enumerate(all_dts)}
    for dt in target_dts:
        d1 = prev_td.get(dt, "")
        nt_r = nt_raw.loc[d1] if d1 in nt_raw.index else None
        i_cur = td_pos[dt]
        w20_dts = all_dts[max(0, i_cur - 19):i_cur + 1]
        w10_dts = all_dts[max(0, i_cur - 9):i_cur + 1]
        p_res = sum(pol_by_td.get(x, {}).get("ev_rescue", 0) for x in w20_dts)
        p_tec = sum(pol_by_td.get(x, {}).get("ev_tech_ma", 0) for x in w20_dts)
        p_hdw = sum(pol_by_td.get(x, {}).get("ev_headwind", 0) for x in w10_dts)
        p_hdw20 = sum(pol_by_td.get(x, {}).get("ev_headwind", 0) for x in w20_dts)
        p_div = sum(pol_by_td.get(x, {}).get("ev_div_large", 0) for x in w20_dts)

        # US strictly < buy_date (settled at ~05:00 CST on buy_date)
        u_idx = int(np.searchsorted(us_dts_arr, dt, side="left")) - 1
        u_row = us_df.iloc[u_idx] if u_idx >= 0 else None
        ix1 = float(u_row["ix_ret1"]) if (u_row is not None and pd.notna(u_row["ix_ret1"])) else 0.0
        ix5 = float(u_row["ix_ret5"]) if (u_row is not None and pd.notna(u_row["ix_ret5"])) else 0.0
        vx1 = float(u_row["vx_chg1"]) if (u_row is not None and pd.notna(u_row["vx_chg1"])) else 0.0

        st_r = style_df.loc[d1] if d1 in style_df.index else None
        rows.append({
            "buy_date": dt,
            "f01_nt_v3_eod_d1": float(nt_r["score_eod"]) if nt_r is not None else 20.0,
            "f02_nt_v3_live_d1": float(nt_r["score_live"]) if nt_r is not None else 20.0,
            "f03_nt_etf_spike_d1": float(nt_r["nt_etf_spike"]) if nt_r is not None else 1.0,
            "f04_nt_fake_support_d1": int(nt_r["nt_fake_support"]) if nt_r is not None else 0,
            "f05_nt_rd019_trap_d1": int(nt_r["nt_rd019_trap"]) if nt_r is not None else 0,
            "f06_nt_t1_skew_d1": float(nt_r["nt_t1_skew"]) if nt_r is not None else 0.0,
            "f07_nt_t2_res_d1": float(nt_r["nt_t2_res"]) if nt_r is not None else 0.0,
            "f08_nt_f152_sync_d1": int(nt_r["nt_f152_sync"]) if nt_r is not None else 0,
            "f09_nt_fund8_dump_d1": int(nt_r["nt_fund8_dump"]) if nt_r is not None else 0,
            "f10_nt_wflow5d_d1": float(nt_r["nt_wflow5d"]) if nt_r is not None else 0.0,
            "f11_nt_if0_basis_d1": float(nt_r["nt_if0_basis"]) if nt_r is not None else 0.0,
            "f12_pol_rescue_20d": int(p_res),
            "f13_pol_tech_ma_20d": int(p_tec),
            "f14_pol_headwind_10d": int(p_hdw),
            "f15_pol_div_large_20d": int(p_div),
            "f16_pol_net_score_20d": int(p_res + p_tec - p_hdw20),
            "f17_us_ixic_ret1d": ix1,
            "f18_us_ixic_drop15": int(ix1 <= -0.015),
            "f19_us_ixic_ret5d": ix5,
            "f20_us_vix_chg1d": vx1,
            "f26_style_small_vs_big_20d": float(st_r["small_vs_big_20d"]) if (st_r is not None and pd.notna(st_r["small_vs_big_20d"])) else 0.0,
            "f27_style_rev_vs_mom_20d": float(st_r["rev_vs_mom_20d"]) if (st_r is not None and pd.notna(st_r["rev_vs_mom_20d"])) else 0.0,
        })
    return pd.DataFrame(rows).set_index("buy_date")
