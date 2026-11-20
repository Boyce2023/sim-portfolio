#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Data Cache Builder for National Team Five-Mantra Empirical Backtest
Period: 2011-01-04 to 2026-11-19 (Core Futures+ETF Window: 2017-01-17 to 2026-11-19)
Strictly NO yfinance (D12 compliant). Extends cached ETF & broad index data cleanly to 2026-11-19.
"""
import os
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import akshare as ak

os.environ["NO_PROXY"] = "*"

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/nt_mantra_backtest_20261120"
CACHE_DIR = f"{OUT_DIR}/data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

ETF_PX_PATH = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team/etf_daily_prices.parquet"
NT_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team/etf_national_team_daily.parquet"
SSE_SHARES_PATH = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team/sse_shares_cache.parquet"
SZSE_SHARES_PATH = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team/szse_shares_cache.parquet"
BROAD_IDX_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119/data_cache/broad_indices_15y.parquet"


def build_broad_indices():
    idx = pd.read_parquet(BROAD_IDX_PATH)
    idx["date"] = pd.to_datetime(idx["date"]).dt.strftime("%Y-%m-%d")
    idx = idx[idx["date"] <= "2026-11-18"].copy()

    # Append 2026-11-19 from AKShare EastMoney index daily (exact match verified on 2026-11-18)
    meta = idx[["symbol", "name"]].drop_duplicates()
    add_rows = []
    for _, r in meta.iterrows():
        sym = r["symbol"]
        df = ak.stock_zh_index_daily_em(symbol=sym, start_date="20261118", end_date="20261119")
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        sub = df[df["date"] == "2026-11-19"]
        for _, sr in sub.iterrows():
            add_rows.append({
                "date": sr["date"],
                "open": float(sr["open"]),
                "high": float(sr["high"]),
                "low": float(sr["low"]),
                "close": float(sr["close"]),
                "volume": float(sr["volume"]),
                "symbol": sym,
                "name": r["name"],
            })
    if add_rows:
        idx = pd.concat([idx, pd.DataFrame(add_rows)], ignore_index=True)
    idx = idx.drop_duplicates(subset=["symbol", "date"], keep="last").sort_values(["symbol", "date"]).reset_index(drop=True)
    idx.to_parquet(f"{CACHE_DIR}/broad_indices_to_20261119.parquet", index=False)
    print(f"[broad_indices] rows={len(idx)}, max_date={idx['date'].max()}")
    return idx


def build_etf_daily():
    etf_raw = pd.read_parquet(ETF_PX_PATH)
    etf_raw["date"] = pd.to_datetime(etf_raw["date"]).dt.strftime("%Y-%m-%d")
    # Note: etf_daily_prices.parquet had partial intraday capture on 2026-11-18 (13:20); replace 11-18 and add 11-19 from full close Sina data
    etf_base = etf_raw[etf_raw["date"] <= "2026-11-17"].copy()
    nt_raw = pd.read_parquet(NT_DAILY_PATH)
    nt_raw["date"] = pd.to_datetime(nt_raw["date"]).dt.strftime("%Y-%m-%d")
    nt_base = nt_raw[nt_raw["date"] <= "2026-11-17"].copy()

    sse = pd.read_parquet(SSE_SHARES_PATH)
    szse = pd.read_parquet(SZSE_SHARES_PATH)
    shares = pd.concat([sse, szse], ignore_index=True)
    shares["date"] = pd.to_datetime(shares["date"]).dt.strftime("%Y-%m-%d")

    meta = etf_raw[["code", "name", "exch", "idx_grp", "team", "nt_w"]].drop_duplicates()
    ext_rows = []
    for _, r in meta.iterrows():
        sym = ("sh" if r["exch"] == "SSE" or r["code"].startswith(("51", "56", "58")) else "sz") + r["code"]
        df = ak.fund_etf_hist_sina(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        sub = df[df["date"].isin(["2026-11-17", "2026-11-18", "2026-11-19"])].sort_values("date")
        prev_c = None
        for _, sr in sub.iterrows():
            c = float(sr["close"])
            pct = ((c / prev_c - 1.0) * 100.0) if prev_c is not None else np.nan
            prev_c = c
            if sr["date"] in ("2026-11-18", "2026-11-19"):
                ext_rows.append({
                    "date": sr["date"],
                    "code": r["code"],
                    "name": r["name"],
                    "exch": r["exch"],
                    "idx_grp": r["idx_grp"],
                    "team": r["team"],
                    "nt_w": float(r["nt_w"]),
                    "open": float(sr["open"]),
                    "high": float(sr["high"]),
                    "low": float(sr["low"]),
                    "close": c,
                    "close_qfq": c,
                    "split_ratio": 1.0,
                    "volume": float(sr["volume"]),
                    "amount": float(sr["amount"]),
                    "pct_chg": pct,
                })
    ext_df = pd.DataFrame(ext_rows)

    # Compute exact 11-18 and 11-19 flows using shares cache (including 11-17 close & shares for diff)
    px17 = etf_base[etf_base["date"] == "2026-11-17"][["date", "code", "nt_w", "close", "amount"]].copy()
    px_all3 = pd.concat([px17, ext_df[["date", "code", "nt_w", "close", "amount"]]], ignore_index=True)
    px_all3 = px_all3.merge(shares, on=["date", "code"], how="left").sort_values(["code", "date"])
    px_all3["d_sh"] = px_all3.groupby("code")["shares_wan"].diff()
    px_all3["flow_yi"] = px_all3["d_sh"] * px_all3["close"] / 1e4
    px_all3["wflow_yi"] = px_all3["flow_yi"] * px_all3["nt_w"]

    etf_full = pd.concat([etf_base, ext_df], ignore_index=True).sort_values(["code", "date"]).reset_index(drop=True)
    etf_full.to_parquet(f"{CACHE_DIR}/etf_daily_to_20261119.parquet", index=False)

    # Build daily nt panel through 2026-11-19
    # Recalculate etf_amt_spike_20d consistently using shift(1) 20d median
    tot_amt_daily = etf_full.groupby("date")["amount"].sum() / 1e8
    amt510300_daily = etf_full[etf_full["code"] == "510300"].set_index("date")["amount"] / 1e8
    close510300_daily = etf_full[etf_full["code"] == "510300"].set_index("date")["close"]

    ext_nt_rows = []
    for d in ["2026-11-18", "2026-11-19"]:
        sub = px_all3[px_all3["date"] == d]
        sub_300 = sub[sub["code"] == "510300"]
        ext_nt_rows.append({
            "date": d,
            "etf_tot_amt_yi": float(sub["amount"].sum() / 1e8),
            "etf_net_flow_yi": float(sub["flow_yi"].sum()),
            "etf_nt_weighted_flow_yi": float(sub["wflow_yi"].sum()),
            "etf510300_close": float(sub_300["close"].iloc[0]),
            "etf510300_amt_yi": float(sub_300["amount"].iloc[0] / 1e8),
            "etf510300_net_flow_yi": float(sub_300["flow_yi"].iloc[0]),
        })
    nt_ext = pd.DataFrame(ext_nt_rows)
    nt_keep = nt_base[["date", "etf_tot_amt_yi", "etf_net_flow_yi", "etf_nt_weighted_flow_yi",
                       "etf510300_close", "etf510300_amt_yi", "etf510300_net_flow_yi"]].copy()
    nt_full = pd.concat([nt_keep, nt_ext], ignore_index=True).sort_values("date").reset_index(drop=True)
    # Strictly shift(1) 20-day median for spike ratios
    nt_full["etf_amt_med20_s1"] = nt_full["etf_tot_amt_yi"].rolling(20, min_periods=10).median().shift(1)
    nt_full["etf_amt_spike_20d"] = nt_full["etf_tot_amt_yi"] / nt_full["etf_amt_med20_s1"]
    nt_full["etf510300_amt_med20_s1"] = nt_full["etf510300_amt_yi"].rolling(20, min_periods=10).median().shift(1)
    nt_full["etf510300_amt_spike"] = nt_full["etf510300_amt_yi"] / nt_full["etf510300_amt_med20_s1"]
    # Also compute CSI300-group 4 ETFs total spike & T1/T2 flows
    nt_full.to_parquet(f"{CACHE_DIR}/nt_daily_to_20261119.parquet", index=False)
    print(f"[nt_daily] rows={len(nt_full)}, max_date={nt_full['date'].max()}")
    print(nt_full.tail(5)[["date", "etf_tot_amt_yi", "etf_amt_spike_20d", "etf_net_flow_yi", "etf510300_amt_spike"]].to_string(index=False))
    return nt_full


def build_futures():
    dfs = []
    for sym in ["IF0", "IH0", "IC0", "IM0"]:
        df = ak.futures_main_sina(symbol=sym, start_date="20150101", end_date="20261120")
        df["date"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
        df = df[df["date"] <= "2026-11-19"].copy()
        df = df[["date", "开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]].rename(columns={
            "开盘价": f"{sym}_open",
            "最高价": f"{sym}_high",
            "最低价": f"{sym}_low",
            "收盘价": f"{sym}_close",
            "成交量": f"{sym}_vol",
            "持仓量": f"{sym}_oi",
        })
        dfs.append(df)
    fut = dfs[0]
    for d in dfs[1:]:
        fut = fut.merge(d, on="date", how="outer")
    fut = fut.sort_values("date").reset_index(drop=True)
    fut["fut3_vol"] = fut["IF0_vol"] + fut["IH0_vol"] + fut["IC0_vol"]
    fut["fut3_oi"] = fut["IF0_oi"] + fut["IH0_oi"] + fut["IC0_oi"]
    fut["fut3_d_oi"] = fut["fut3_oi"].diff()
    fut["fut3_med20_s1"] = fut["fut3_vol"].rolling(20, min_periods=10).median().shift(1)
    fut["fut3_spike_20d"] = fut["fut3_vol"] / fut["fut3_med20_s1"]
    fut["if0_spike_20d"] = fut["IF0_vol"] / fut["IF0_vol"].rolling(20, min_periods=10).median().shift(1)
    # 4-contract variant when IM0 exists
    fut["fut4_vol"] = fut["fut3_vol"] + fut["IM0_vol"].fillna(0.0)
    fut["fut4_med20_s1"] = fut["fut4_vol"].rolling(20, min_periods=10).median().shift(1)
    fut["fut4_spike_20d"] = fut["fut4_vol"] / fut["fut4_med20_s1"]
    fut.to_parquet(f"{CACHE_DIR}/futures_main_to_20261119.parquet", index=False)
    print(f"[futures] rows={len(fut)}, min_date={fut['date'].min()}, max_date={fut['date'].max()}")
    print(fut.tail(5)[["date", "IF0_vol", "fut3_vol", "fut3_spike_20d", "fut3_d_oi"]].to_string(index=False))
    return fut


def main():
    idx = build_broad_indices()
    nt = build_etf_daily()
    fut = build_futures()

    # Build aligned master daily panel (2011-01-04 to 2026-11-19) on sh000300 calendar
    c300 = idx[idx["symbol"] == "sh000300"].copy().sort_values("date").reset_index(drop=True)
    c500 = idx[idx["symbol"] == "sh000905"][["date", "open", "high", "low", "close"]].rename(
        columns={"open": "c500_open", "high": "c500_high", "low": "c500_low", "close": "c500_close"}
    )
    c50 = idx[idx["symbol"] == "sh000016"][["date", "close"]].rename(columns={"close": "c50_close"})
    cyb = idx[idx["symbol"] == "sz399006"][["date", "close"]].rename(columns={"close": "cyb_close"})

    p = c300[["date", "open", "high", "low", "close", "volume"]].rename(
        columns={"open": "c300_open", "high": "c300_high", "low": "c300_low", "close": "c300_close", "volume": "c300_vol"}
    )
    p = p.merge(c500, on="date", how="left").merge(c50, on="date", how="left").merge(cyb, on="date", how="left")
    p = p.merge(nt, on="date", how="left").merge(fut, on="date", how="left")
    p = p.sort_values("date").reset_index(drop=True)

    # Compute exact PIT price features on CSI300 & CSI500
    p["c300_prev_close"] = p["c300_close"].shift(1)
    p["c300_ret"] = p["c300_close"] / p["c300_prev_close"] - 1.0
    p["c300_overnight"] = p["c300_open"] / p["c300_prev_close"] - 1.0
    p["c300_intraday"] = p["c300_close"] / p["c300_open"] - 1.0
    p["c300_pullup"] = (p["c300_close"] - p["c300_low"]) / p["c300_prev_close"]
    p["c300_ma20"] = p["c300_close"].rolling(20, min_periods=20).mean()
    p["c300_high20"] = p["c300_close"].rolling(20, min_periods=20).max()
    p["c300_dd20"] = p["c300_close"] / p["c300_high20"] - 1.0
    p["c300_ret20"] = p["c300_close"] / p["c300_close"].shift(20) - 1.0

    p["c500_prev_close"] = p["c500_close"].shift(1)
    p["c500_ret"] = p["c500_close"] / p["c500_prev_close"] - 1.0
    p["c500_overnight"] = p["c500_open"] / p["c500_prev_close"] - 1.0
    p["c500_intraday"] = p["c500_close"] / p["c500_open"] - 1.0

    # Calendar / Delivery Day flags (3rd Friday of month, plus exact rollover Thursday)
    dt = pd.to_datetime(p["date"])
    p["dow"] = dt.dt.dayofweek
    p["dom"] = dt.dt.day
    p["ym"] = dt.dt.strftime("%Y-%m")
    # Standard 3rd Friday rule: Friday (dow==4) with 15 <= day <= 21
    p["is_3rd_fri"] = (p["dow"] == 4) & (p["dom"] >= 15) & (p["dom"] <= 21)
    # Also handle rare months where 3rd Friday was a market holiday -> first trading day after 3rd Friday
    # Compute calendar 3rd Friday for each ym in panel
    deliv_dates = set()
    for ym_val, grp in p.groupby("ym"):
        y, m = map(int, ym_val.split("-"))
        first_day = pd.Timestamp(year=y, month=m, day=1)
        # First Friday: (4 - first_day.weekday()) % 7 + 1
        first_fri = 1 + (4 - first_day.weekday()) % 7
        third_fri = pd.Timestamp(year=y, month=m, day=first_fri + 14)
        # Actual delivery day = first trading day on or after third_fri
        cand = grp[pd.to_datetime(grp["date"]) >= third_fri]
        if len(cand) > 0:
            deliv_dates.add(cand["date"].iloc[0])
    p["is_delivery_day"] = p["date"].isin(deliv_dates)
    p["is_delivery_prev_thu"] = p["is_delivery_day"].shift(-1).fillna(False)
    p["is_delivery_win"] = p["is_delivery_day"] | p["is_delivery_prev_thu"]

    p_15y = p[p["date"] >= "2011-01-04"].reset_index(drop=True)
    p_15y.to_parquet(f"{CACHE_DIR}/nt_mantra_daily_panel.parquet", index=False)
    print(f"[master_panel] rows={len(p_15y)}, min={p_15y['date'].min()}, max={p_15y['date'].max()}")
    print("2026-11-17..19 summary:")
    print(p_15y.tail(3)[["date", "c300_close", "c300_ret", "c300_pullup", "etf_tot_amt_yi", "etf_amt_spike_20d", "etf_net_flow_yi", "fut3_spike_20d"]].to_string(index=False))


if __name__ == "__main__":
    main()
