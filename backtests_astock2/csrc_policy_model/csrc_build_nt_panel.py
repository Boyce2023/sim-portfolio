#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Update daily_market_panel.parquet to 2026-11-17 and merge:
1. 21 Verified National-Team ETFs: daily turnover, spike ratio, raw & NT-weighted net flow (亿元)
2. Standalone 510300 (Huatai-PB CSI300 ETF) thermometer + Team 1 / Team 2 / Team 3 sub-flows
3. Big-4 State Banks equal-weight return & divergence vs CSI1000
"""
import os
os.environ["NO_PROXY"] = "*"
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import akshare as ak

BASE = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE, "backtest")
NT_DIR = os.path.join(BASE, "national_team")
DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db"

INDEX_MAP = {
    "sh000001": "sh_comp", "sh000300": "csi300", "sz399006": "chinext",
    "sh000688": "star50", "sh000905": "csi500", "sh000852": "csi1000",
    "sh000016": "sse50", "sh000922": "csi_div", "sz399975": "brokerage",
    "sz399986": "bank_idx", "sh000941": "new_energy", "sz399997": "baijiu",
    "sh000933": "pharma", "sz399974": "soe_reform", "sh000926": "central_soe",
    "sz399967": "defense", "sz399971": "media_ai", "sh000993": "tmt_info",
    "sh000989": "cons_opt", "sz399393": "real_estate", "sh512480": "semi_etf",
}


def build_updated_market_panel():
    idx_frames = {}
    for sym, pref in INDEX_MAP.items():
        df = ak.stock_zh_index_daily_tx(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values("date").drop_duplicates("date")
        df = df[df["date"] >= "2000-01-01"].copy()
        for c in ("open", "high", "low", "close"):
            df[f"{pref}_{c}"] = df[c].astype(float)
        pc = df[f"{pref}_close"].shift(1)
        df[f"{pref}_cc_ret"] = df[f"{pref}_close"] / pc - 1.0
        df[f"{pref}_gap_ret"] = df[f"{pref}_open"] / pc - 1.0
        df[f"{pref}_oc_ret"] = df[f"{pref}_close"] / df[f"{pref}_open"] - 1.0
        keep = ["date", f"{pref}_open", f"{pref}_high", f"{pref}_low", f"{pref}_close",
                f"{pref}_cc_ret", f"{pref}_gap_ret", f"{pref}_oc_ret"]
        idx_frames[pref] = df[keep]
        print(f"Idx {pref}: {df['date'].min()} -> {df['date'].max()}")

    cal = idx_frames["sh_comp"].copy()
    for k, v in idx_frames.items():
        if k != "sh_comp":
            cal = cal.merge(v, on="date", how="left")

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "oshare", "qfq_factor"]
    parts = []
    for fn in ["a_daily.parquet", "a_delisted_daily.parquet", "bj_daily.parquet"]:
        p = os.path.join(DATA_DIR, fn)
        if os.path.exists(p):
            df_p = pq.read_table(p, columns=cols, filters=[("date", ">=", pd.Timestamp("2000-01-01"))]).to_pandas()
            df_p["date"] = pd.to_datetime(df_p["date"]).dt.strftime("%Y-%m-%d")
            parts.append(df_p)
    stk = pd.concat(parts, ignore_index=True).drop_duplicates(["date", "ticker"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    ratio = np.where(stk["close"] > 0, stk["adj_close"] / stk["close"], 1.0)
    stk["open_adj"] = stk["open"] * ratio
    stk["high_adj"] = stk["high"] * ratio
    stk["prev_adj_close"] = stk.groupby("ticker")["adj_close"].shift(1)
    stk = stk[(stk["prev_adj_close"] > 0) & (stk["open_adj"] > 0) & (stk["adj_close"] > 0) & (stk["amount"] > 0)].copy()

    stk["cc_ret"] = stk["adj_close"] / stk["prev_adj_close"] - 1.0
    stk["gap_ret"] = stk["open_adj"] / stk["prev_adj_close"] - 1.0
    stk["oc_ret"] = stk["adj_close"] / stk["open_adj"] - 1.0
    stk["high_ret"] = stk["high_adj"] / stk["prev_adj_close"] - 1.0
    stk["mkt_cap"] = stk["close"] * stk["oshare"]

    tk = stk["ticker"].astype(str)
    is_20 = tk.str.startswith("688") | ((tk.str.startswith("300") | tk.str.startswith("301")) & (stk["date"] >= "2020-08-24"))
    is_bj = tk.str.startswith("8") | tk.str.startswith("4") | tk.str.startswith("92")
    zt_th = np.where(is_bj, 0.292, np.where(is_20, 0.195, 0.0975))
    dt_th = np.where(is_bj, -0.292, np.where(is_20, -0.195, -0.0975))
    stk["is_zt"] = (stk["cc_ret"] >= zt_th) & (stk["cc_ret"] <= 0.35)
    stk["is_dt"] = (stk["cc_ret"] <= dt_th) & (stk["cc_ret"] >= -0.35)
    stk["touched_zt"] = (stk["high_ret"] >= zt_th) & (stk["high_ret"] <= 0.35)
    stk["is_broken_zt"] = stk["touched_zt"] & (~stk["is_zt"])

    def calc_streak(s):
        arr = s.to_numpy(dtype=np.int8)
        out = np.zeros(len(arr), dtype=np.int16)
        c = 0
        for i, v in enumerate(arr):
            c = c + 1 if v else 0
            out[i] = c
        return out

    stk["zt_streak"] = stk.groupby("ticker", sort=False)["is_zt"].transform(calc_streak)
    stk["prev_zt_streak"] = stk.groupby("ticker", sort=False)["zt_streak"].shift(1).fillna(0)
    stk["is_tech_board"] = tk.str.startswith("688") | tk.str.startswith("300") | tk.str.startswith("301")
    stk["cap_pct"] = stk.groupby("date")["mkt_cap"].rank(pct=True)
    stk["cc_clean"] = stk["cc_ret"].clip(-0.30, 0.30)
    stk["oc_clean"] = stk["oc_ret"].clip(-0.25, 0.25)
    stk["gap_clean"] = stk["gap_ret"].clip(-0.20, 0.20)

    g = stk.groupby("date")
    daily = pd.DataFrame({
        "n_stocks": g["ticker"].count(), "total_amount_yi": g["amount"].sum() / 1e8,
        "ew_cc_ret": g["cc_clean"].mean(), "ew_oc_ret": g["oc_clean"].mean(), "ew_gap_ret": g["gap_clean"].mean(),
        "up_ratio": g["cc_ret"].apply(lambda s: (s > 0).mean()), "zt_cnt": g["is_zt"].sum(), "dt_cnt": g["is_dt"].sum(),
        "touched_zt_cnt": g["touched_zt"].sum(), "broken_zt_cnt": g["is_broken_zt"].sum(),
        "max_zt_streak": g["zt_streak"].max(), "b3plus_cnt": g["zt_streak"].apply(lambda s: (s >= 3).sum()),
    }).reset_index()
    daily["broken_rate"] = np.where(daily["touched_zt_cnt"] > 0, daily["broken_zt_cnt"] / daily["touched_zt_cnt"], np.nan)

    for lbl, msk in [
        ("micro30", stk["cap_pct"] <= 0.30), ("large10", stk["cap_pct"] >= 0.90),
        ("tech_board", stk["is_tech_board"]), ("high_relay", stk["prev_zt_streak"] >= 3),
        ("big4_bank", tk.isin(["601398", "601939", "601288", "601988"])),
    ]:
        sub = stk[msk].groupby("date").agg(**{
            f"{lbl}_cc_ret": ("cc_clean", "mean"), f"{lbl}_oc_ret": ("oc_clean", "mean"), f"{lbl}_gap_ret": ("gap_clean", "mean")
        }).reset_index()
        daily = daily.merge(sub, on="date", how="left")

    panel = cal.merge(daily, on="date", how="left").sort_values("date").reset_index(drop=True)
    panel["bench_cc_ret"] = panel["csi300_cc_ret"].fillna(panel["large10_cc_ret"]).fillna(panel["sh_comp_cc_ret"])
    panel["bench_oc_ret"] = panel["csi300_oc_ret"].fillna(panel["large10_oc_ret"]).fillna(panel["sh_comp_oc_ret"])
    panel["bench_gap_ret"] = panel["csi300_gap_ret"].fillna(panel["large10_gap_ret"]).fillna(panel["sh_comp_gap_ret"])
    panel["bench_level"] = (1.0 + panel["bench_cc_ret"].fillna(0.0)).cumprod()
    panel["bench_ret_5d"] = panel["bench_level"] / panel["bench_level"].shift(5) - 1.0
    panel["bench_ret_20d"] = panel["bench_level"] / panel["bench_level"].shift(20) - 1.0
    panel["bench_ret_60d"] = panel["bench_level"] / panel["bench_level"].shift(60) - 1.0
    panel["bench_dd_60d"] = panel["bench_level"] / panel["bench_level"].rolling(60, min_periods=10).max() - 1.0
    panel["bench_dd_250d"] = panel["bench_level"] / panel["bench_level"].rolling(250, min_periods=30).max() - 1.0
    panel["bench_vol_20d"] = panel["bench_cc_ret"].rolling(20, min_periods=10).std() * np.sqrt(242)
    panel["amount_pct_250d"] = panel["total_amount_yi"].rolling(250, min_periods=30).rank(pct=True)
    panel["amount_ratio_20d"] = panel["total_amount_yi"] / panel["total_amount_yi"].rolling(20, min_periods=5).mean()

    # Big-4 bank support divergence & CSI300 intraday lower shadow
    panel["big4_vs_1000_ret"] = panel["big4_bank_cc_ret"] - panel["csi1000_cc_ret"]
    panel["csi300_lower_shadow"] = np.where(panel["csi300_low"] > 0, (panel["csi300_close"] - panel["csi300_low"]) / panel["csi300_low"], np.nan)
    return panel


def merge_etf_and_extras(panel):
    px = pd.read_parquet(os.path.join(NT_DIR, "etf_daily_prices.parquet"))
    sh = pd.concat([pd.read_parquet(os.path.join(NT_DIR, "sse_shares_cache.parquet")),
                    pd.read_parquet(os.path.join(NT_DIR, "szse_shares_cache.parquet"))], ignore_index=True).drop_duplicates(["date", "code"])
    df = px.merge(sh, on=["date", "code"], how="left").sort_values(["code", "date"]).reset_index(drop=True)
    df["prev_sh"] = df.groupby("code")["shares_wan"].shift(1)
    df["prev_sr"] = df.groupby("code")["split_ratio"].shift(1)
    df["next_sr"] = df.groupby("code")["split_ratio"].shift(-1)
    sr_jmp = (df["split_ratio"] / df["prev_sr"] - 1.0).abs() > 0.08
    nsr_jmp = (df["next_sr"] / df["split_ratio"] - 1.0).abs() > 0.08
    sh_jmp = (df["shares_wan"] / df["prev_sh"] - 1.0).abs() > 0.10
    explicit_splits = (
        ((df["code"] == "510310") & (df["date"].isin(["2024-09-20", "2024-09-23"]))) |
        ((df["code"] == "512100") & (df["date"].isin(["2022-09-02", "2022-09-05"]))) |
        ((df["code"] == "159845") & (df["date"].isin(["2022-08-01", "2022-08-02"]))) |
        ((df["code"] == "510500") & (df["date"].isin(["2015-04-14", "2015-04-15"]))) |
        ((df["code"] == "510180") & (df["date"].isin(["2013-12-20", "2013-12-23"]))) |
        ((df["code"] == "510230") & (df["date"].isin(["2020-08-14", "2020-08-17"]))) |
        ((df["code"] == "560010") & (df["date"].isin(["2022-09-13", "2022-09-14"]))) |
        ((df["code"] == "159922") & (df["date"].isin(["2024-11-29", "2024-12-02"]))) |
        ((df["code"] == "159919") & (df["date"].isin(["2019-01-11", "2019-01-14"])))
    )
    split_msk = explicit_splits | ((sr_jmp | nsr_jmp) & sh_jmp)
    df["net_flow_yi"] = np.where(split_msk, 0.0, (df["shares_wan"] - df["prev_sh"]) * 1e4 * df["close"] / 1e8)
    df["nt_w_flow_yi"] = df["net_flow_yi"] * df["nt_w"].astype(float)
    df["aum_yi"] = df["shares_wan"] * 1e4 * df["close"] / 1e8
    df["nt_w_aum_yi"] = df["aum_yi"] * df["nt_w"].astype(float)

    def grp_sum(col, mask_col, val):
        return (col, lambda s: s[df.loc[s.index, mask_col] == val].sum())

    etf_d = df.groupby("date").agg(
        etf_tot_amt_yi=("amount", lambda s: s.sum() / 1e8),
        etf_net_flow_yi=("net_flow_yi", "sum"),
        etf_nt_weighted_flow_yi=("nt_w_flow_yi", "sum"),
        etf_tot_aum_yi=("aum_yi", "sum"),
        etf_nt_weighted_aum_yi=("nt_w_aum_yi", "sum"),
        etf_n_shares=("shares_wan", lambda s: int(s.notna().sum())),
        etf_t1_flow_yi=grp_sum("net_flow_yi", "team", "T1"),
        etf_t2_flow_yi=grp_sum("net_flow_yi", "team", "T2"),
        etf_t3_flow_yi=grp_sum("net_flow_yi", "team", "T3"),
        etf_t1_wflow_yi=grp_sum("nt_w_flow_yi", "team", "T1"),
        etf_t2_wflow_yi=grp_sum("nt_w_flow_yi", "team", "T2"),
        etf_csi300_flow_yi=grp_sum("net_flow_yi", "idx_grp", "CSI300"),
        etf_sse50_flow_yi=grp_sum("net_flow_yi", "idx_grp", "SSE50"),
        etf_csi500_flow_yi=grp_sum("net_flow_yi", "idx_grp", "CSI500"),
        etf_csi1000_flow_yi=grp_sum("net_flow_yi", "idx_grp", "CSI1000"),
        etf_chinext_flow_yi=grp_sum("net_flow_yi", "idx_grp", "CHINEXT"),
        etf_star50_flow_yi=grp_sum("net_flow_yi", "idx_grp", "STAR50"),
        etf_soetech_flow_yi=grp_sum("net_flow_yi", "idx_grp", "SOETECH"),
    ).reset_index().sort_values("date")

    # Standalone 510300 (Huatai-PB CSI300 ETF) thermometer
    s300 = df[df["code"] == "510300"][["date", "close", "amount", "net_flow_yi", "aum_yi", "shares_wan"]].copy()
    s300["etf510300_amt_yi"] = s300["amount"] / 1e8
    s300 = s300.rename(columns={"close": "etf510300_close", "net_flow_yi": "etf510300_net_flow_yi", "aum_yi": "etf510300_aum_yi", "shares_wan": "etf510300_shares_wan"})
    s300["etf510300_amt_spike"] = s300["etf510300_amt_yi"] / s300["etf510300_amt_yi"].rolling(20, min_periods=5).median().shift(1).replace(0, np.nan)
    s300["etf510300_flow_5d_yi"] = s300["etf510300_net_flow_yi"].rolling(5, min_periods=1).sum()
    etf_d = etf_d.merge(s300[["date", "etf510300_close", "etf510300_amt_yi", "etf510300_amt_spike", "etf510300_net_flow_yi", "etf510300_flow_5d_yi", "etf510300_aum_yi", "etf510300_shares_wan"]], on="date", how="left")

    etf_d = etf_d[etf_d["date"] <= "2026-11-17"].copy()
    med20 = etf_d["etf_tot_amt_yi"].rolling(20, min_periods=5).median().shift(1)
    etf_d["etf_amt_spike_20d"] = etf_d["etf_tot_amt_yi"] / med20.replace(0, np.nan)
    etf_d["etf_net_flow_5d_yi"] = etf_d["etf_net_flow_yi"].rolling(5, min_periods=1).sum()
    etf_d["etf_net_flow_20d_yi"] = etf_d["etf_net_flow_yi"].rolling(20, min_periods=1).sum()
    etf_d["etf_nt_weighted_flow_5d_yi"] = etf_d["etf_nt_weighted_flow_yi"].rolling(5, min_periods=1).sum()
    etf_d["etf_nt_weighted_flow_20d_yi"] = etf_d["etf_nt_weighted_flow_yi"].rolling(20, min_periods=1).sum()
    etf_d["etf_300_minus_1000_flow_yi"] = etf_d["etf_csi300_flow_yi"] - etf_d["etf_csi1000_flow_yi"]
    etf_d["etf_t1_minus_t2_flow_yi"] = etf_d["etf_t1_flow_yi"] - etf_d["etf_t2_flow_yi"]
    etf_d["etf_data_avail"] = (etf_d["etf_n_shares"] > 0).astype(int)

    consec, c = [], 0
    for v, avail in zip(etf_d["etf_nt_weighted_flow_yi"], etf_d["etf_data_avail"]):
        c = c + 1 if (avail and v >= 30.0) else 0
        consec.append(c)
    etf_d["nt_consec_buy_days"] = consec
    prev_consec = pd.Series(consec).shift(1).fillna(0)
    prev_5d_flow = etf_d["etf_nt_weighted_flow_5d_yi"].shift(1).fillna(0)
    etf_d["nt_tapering_stop"] = ((prev_consec >= 3) & (prev_5d_flow >= 220.0) & (etf_d["etf_nt_weighted_flow_yi"] <= 0.0)).astype(int)

    etf_d.to_parquet(os.path.join(NT_DIR, "etf_national_team_daily.parquet"), index=False)
    panel = panel.merge(etf_d, on="date", how="left")

    for p, col_src, col_ret, col_cnt in [
        ("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v18_ledger.csv", "buy_date", "v18_1to2_ret", "v18_1to2_cnt"),
        ("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/trainer_high_v51/v51_ledger_42.csv", "buy_date", "v51_high_dip_ret", "v51_high_dip_cnt"),
    ]:
        if os.path.exists(p):
            sub = pd.read_csv(p).groupby(col_src).agg(**{col_ret: ("net_ret", "mean"), col_cnt: ("net_ret", "count")}).reset_index().rename(columns={col_src: "date"})
            panel = panel.merge(sub, on="date", how="left")
    reg_p = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113/sub2_daily_regime.parquet"
    if os.path.exists(reg_p):
        reg = pd.read_parquet(reg_p)
        reg["date"] = reg["date"].astype(str).str[:10]
        rc = [c for c in ["date", "ex_cnt5", "brk_nuke", "brk_avg_pct", "n_b4p"] if c in reg.columns]
        panel = panel.merge(reg[rc].drop_duplicates("date"), on="date", how="left")

    out_p = os.path.join(BT_DIR, "daily_market_panel.parquet")
    panel.to_parquet(out_p, index=False)
    print(f"SUCCESS updated panel -> {out_p}: {len(panel)} days [{panel['date'].min()} -> {panel['date'].max()}], cols={len(panel.columns)}")


if __name__ == "__main__":
    pnl = build_updated_market_panel()
    merge_etf_and_extras(pnl)
