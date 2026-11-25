#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Track B2 Macro PIT Builder: Attaches NT V3.0, CSRC 22 Core Policy, US Overnight + Commodities, 15Y Style/Tech/Macro strictly PIT at buy_date 09:25."""
import bisect, os, sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT = f"{ROOT}/output/csrc_policy_100factors_20261114"
sys.path.insert(0, f"{SIM}/backtests_astock2/csrc_policy_model")
import csrc_v3_backtest_calibrate as nt_v3
from csrc_factors_part1 import get_factors_part1
from csrc_factors_part2 import get_factors_part2

CSRC_22_IDS = {
    "F009", "F033", "F047", "F048", "F058", "F062", "F064", "F070", "F073", "F075", "F077",
    "F081", "F092", "F096", "F097", "F115", "F120", "F133", "F134", "F137", "F143", "F144",
}


def build_csrc_22_daily(cal_dts: list[str]) -> pd.DataFrame:
    me = pd.read_parquet(f"{OUT}/backtest/master_events_pit.parquet")
    me = me[me["tradable_date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")].copy()
    me = me[me["tradable_date"] >= "2020-09-01"].reset_index(drop=True)
    fdefs = [f for f in (get_factors_part1() + get_factors_part2()) if f["id"] in CSRC_22_IDS]
    ev_pos, ev_neg, ev_tech, ev_exch = {}, {}, {}, {}
    ev_net = {}
    pos_hit = np.zeros(len(me), dtype=int)
    neg_hit = np.zeros(len(me), dtype=int)
    for f in fdefs:
        m = f["mask_fn"](me).fillna(False).to_numpy(dtype=bool)
        if f["exp_dir"] > 0:
            pos_hit += m.astype(int)
        else:
            neg_hit += m.astype(int)
    me["c22_pos"] = (pos_hit > 0).astype(int)
    me["c22_neg"] = (neg_hit > 0).astype(int)
    me["c22_net"] = pos_hit - neg_hit
    me["c_tech_ma"] = ((me["tech_innovation_support"] >= 2) | (me["ma_restructuring_support"] >= 2)).astype(int)
    me["c_exch"] = (me["authority_level"] == "EXCHANGE_SURVEILLANCE").astype(int)
    agg = me.groupby("tradable_date")[["c22_pos", "c22_neg", "c22_net", "c_tech_ma", "c_exch"]].sum()
    df_c = pd.DataFrame(index=pd.Index(cal_dts, name="dt")).join(agg, how="left").fillna(0.0)
    df_c["pol_22_net_10d"] = df_c["c22_net"].rolling(10, min_periods=1).sum()
    df_c["pol_22_pos_20d"] = df_c["c22_pos"].rolling(20, min_periods=1).sum()
    df_c["pol_22_neg_20d"] = df_c["c22_neg"].rolling(20, min_periods=1).sum()
    df_c["pol_tech_ma_10d"] = df_c["c_tech_ma"].rolling(10, min_periods=1).sum()
    df_c["pol_exch_surv_5d"] = df_c["c_exch"].rolling(5, min_periods=1).sum()
    return df_c[["pol_22_net_10d", "pol_22_pos_20d", "pol_22_neg_20d", "pol_tech_ma_10d", "pol_exch_surv_5d"]]


def build_us_overnight_daily(cal_dts: list[str]) -> pd.DataFrame:
    series = {}
    for sym in ["IXIC", "GSPC", "VIX", "GC_F", "CL_F"]:
        d = pd.read_parquet(f"{SIM}/data/us_price_db/benchmarks/{sym}.parquet")
        idx_dt = pd.to_datetime(d.index).tz_localize(None).strftime("%Y-%m-%d")
        s = pd.DataFrame({"us_dt": idx_dt, "close": d["close"].to_numpy(dtype=float)}).drop_duplicates("us_dt").sort_values("us_dt")
        s["ret"] = s["close"] / s["close"].shift(1) - 1.0
        series[sym] = (s["us_dt"].tolist(), s["ret"].to_numpy(), s["close"].to_numpy())
    rows = []
    for d in cal_dts:
        row = {"dt": d}
        d_ts = pd.Timestamp(d)
        for sym, col_pfx in [("IXIC", "us_ixic"), ("GSPC", "us_gspc"), ("VIX", "us_vix"), ("GC_F", "comm_gc"), ("CL_F", "comm_cl")]:
            udts, urets, ucls = series[sym]
            pos = bisect.bisect_left(udts, d) - 1
            if pos >= 0 and (d_ts - pd.Timestamp(udts[pos])).days <= 10:
                row[f"{col_pfx}_ret"] = float(urets[pos]) if pd.notna(urets[pos]) else 0.0
                if sym == "VIX":
                    row["us_vix_level"] = float(ucls[pos])
            else:
                row[f"{col_pfx}_ret"] = 0.0
                if sym == "VIX":
                    row["us_vix_level"] = 20.0
        rows.append(row)
    return pd.DataFrame(rows).set_index("dt")


def build_style15_daily(cal_dts: list[str]) -> pd.DataFrame:
    ds_st = pd.read_parquet(f"{SIM}/backtests_astock2/theory_backtest_15y_20261119/daily_ret_style.parquet")
    ds_tc = pd.read_parquet(f"{SIM}/backtests_astock2/theory_backtest_15y_20261119/daily_ret_tech.parquet")
    ds_mc = pd.read_parquet(f"{SIM}/backtests_astock2/theory_backtest_15y_20261119/daily_ret_macro.parquet")
    for x in (ds_st, ds_tc, ds_mc):
        x.index = pd.to_datetime(x.index).strftime("%Y-%m-%d")
    comb = pd.DataFrame(index=pd.Index(cal_dts, name="dt"))
    comb["r_sc"] = ds_st["小市值轮动_含退市检验"]
    comb["r_lv"] = ds_st["核心资产大蓝筹低波_茅指数本土化"]
    comb["r_os"] = ds_st["超跌反转效应_跌多了就买"]
    comb["r_ice"] = ds_st["情绪冰点与量能拥挤择时_游资周期论"]
    comb["r_rsi"] = ds_tc["传统超买超卖_RSI逆势"]
    comb["r_erp"] = ds_mc["股债ERP_三档择时"]
    comb = comb.fillna(0.0)
    out = pd.DataFrame(index=comb.index)
    for col, nm in [("r_sc", "st15_smallcap_5d"), ("r_lv", "st15_lowvol_5d"), ("r_os", "st15_oversold_5d"), ("r_ice", "st15_ice_5d"), ("r_rsi", "tech15_rsi_5d")]:
        out[nm] = (1.0 + comb[col]).rolling(5, min_periods=1).apply(np.prod, raw=True) - 1.0
    out["st15_small_minus_big_5d"] = out["st15_smallcap_5d"] - out["st15_lowvol_5d"]
    out["macro15_erp_20d"] = (1.0 + comb["r_erp"]).rolling(20, min_periods=1).apply(np.prod, raw=True) - 1.0
    return out


def build_mkt_buy_pit(mkt_daily: pd.DataFrame) -> pd.DataFrame:
    """Strictly PIT buy-day (d 09:25 CST) macro table: all d-1 EOD features lagged by 1 trading day."""
    cal_dts = mkt_daily["dt"].tolist()
    nt_raw = nt_v3.score_panel(nt_v3.load_master_panel())
    nt_raw["fake_supp"] = ((np.maximum(nt_raw["core10_amt_spike"].fillna(0), nt_raw["etf22_amt_spike"].fillna(0)) < 1.3)
                           & (((nt_raw["big4_oil_ret"] - nt_raw["c1000_ret"]) >= 0.020)
                              | ((nt_raw["big4_oil_ret"] >= 0.008) & (nt_raw["c1000_ret"] <= -0.008)))).astype(int)
    nt_raw["rd019_trap"] = ((np.maximum(nt_raw["core10_amt_spike"].fillna(0), nt_raw["etf22_amt_spike"].fillna(0)) >= 1.8)
                            & (nt_raw["if0_spike"].fillna(0) >= 1.5) & (~nt_raw["is_deliv"].fillna(False))).astype(int)
    nt_raw["redemp_press"] = ((nt_raw["etf22_wflow_yi"].fillna(0) <= -80.0) | (nt_raw["etf22_wflow_5d"].fillna(0) <= -250.0)
                              | (nt_raw["nt_tapering_stop"].fillna(0) == 1) | (nt_raw["sec9_flow_5d_yi"].fillna(0) <= -35.0)
                              | (nt_raw["lhb_5d_net_yi"].fillna(0) <= -40.0) | (nt_raw["fund8_dump_cnt"].fillna(0) >= 3)).astype(int)
    nt_raw["t1_t2_sync"] = np.where((nt_raw["t1_flow_yi"].fillna(0) >= 50) & (nt_raw["t2_flow_yi"].fillna(0) >= 25), 1,
                                    np.where((nt_raw["t1_flow_yi"].fillna(0) >= 75) & (nt_raw["t2_flow_yi"].fillna(0) < 15), -1, 0))
    nt_raw["high_overheat"] = ((nt_raw["c300_close"] > nt_raw["c300_ma20"]) & (nt_raw["c300_ret20"] >= 0.05)).astype(int)
    nt_cols = ["date", "score_eod", "score_live", "core10_amt_spike", "etf22_wflow_yi", "etf22_wflow_5d",
               "hw16_sync_cnt", "if0_basis_pct", "fake_supp", "rd019_trap", "redemp_press", "t1_t2_sync",
               "high_overheat", "nt_tapering_stop", "official_nt_5d_eod"]
    eod_df = mkt_daily.merge(nt_raw[nt_cols].rename(columns={"date": "dt"}), on="dt", how="left").set_index("dt")
    eod_df = eod_df.join(build_style15_daily(cal_dts), how="left")
    # Lag ALL EOD features by 1 trading day so buy_date d observes strictly <= d-1!
    eod_lag = eod_df.shift(1).add_suffix("_d1")
    open_d = eod_df[["mkt_all_nonst_0925_zt", "mkt20_0925_zt", "mkt20_0925_gap"]].copy()
    pol_d = build_csrc_22_daily(cal_dts)
    us_d = build_us_overnight_daily(cal_dts)
    return pd.concat([eod_lag, open_d, pol_d, us_d], axis=1)
