#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Track B2 Market Panel & Daily Bars Loader: RD012, RD013 brk_r10, Streak Gap, Limit-Down, Bar Lookup."""
import json, os, sqlite3, sys
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"


def load_market_daily_and_bars(target_codes: set[str]):
    with open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8") as f:
        idx_d = json.load(f)
    sh300 = {k: float(v) for k, v in idx_d.get("sh000300", {}).items()}
    sz399107 = {k: float(v) for k, v in idx_d.get("sz399107", {}).items()}
    all_sh_dts = sorted(sh300.keys())

    df_ind = pd.read_csv(f"{SIM}/data/industry.csv")
    ind_codes = df_ind["code"].astype(str).str[-6:].str.zfill(6)
    name_map = dict(zip(ind_codes, df_ind["code_name"].fillna("").astype(str)))
    ind_map = dict(zip(ind_codes, df_ind["industry"].fillna("").astype(str)))
    tech_codes = {c for c, ind in ind_map.items() if ind.startswith(("C39", "I65", "I63"))}
    bank_codes = {c for c, ind in ind_map.items() if ind.startswith("J66") and ("银行" in name_map.get(c, ""))}

    st_set = set()
    st_p = f"{SIM}/data/st_universe.json"
    if os.path.exists(st_p):
        st_set = {str(x)[:6].zfill(6) for x in json.load(open(st_p, encoding="utf-8")).get("codes", [])}
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for sc, nm in con_z.execute("SELECT DISTINCT sec_code, sec_name FROM zt_micro_tape WHERE sec_name LIKE '%ST%' OR sec_name LIKE '%退%'"):
        st_set.add(str(sc).zfill(6))
    con_z.close()

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-09-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df = pd.concat([da, dd], ignore_index=True)
    del da, dd
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & (df["close"] > 0) & (df["adj_close"] > 0)].copy()
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt", "dl"], inplace=True)
    df.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    df["adjf"] = df["adj_close"] / df["close"]
    sub_b = df[df["c6"].isin(target_codes)][["c6", "dt", "open", "close", "adj_close", "qfq_factor", "adjf"]]
    bar_lu = {(r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
              for r in sub_b.itertuples(index=False)}
    # Also keep full OHLCV for target_codes for down_streak & dist headroom exact check
    stk_sub = df[df["c6"].isin(target_codes)][["c6", "dt", "close", "adj_close", "ret" if "ret" in df.columns else "volume"]].copy() if False else None

    g = df.groupby("c6", sort=False)
    pac = g["adj_close"].shift(1)
    pc_raw = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["ret"] = df["adj_close"] / pac - 1.0
    df["o_pct"] = (df["open"] * df["adjf"]) / pac - 1.0
    df["is20"] = df["c6"].str.startswith(("30", "688", "689"))
    df["is10"] = df["c6"].str.startswith(("00", "60"))
    df["non_st"] = ~df["c6"].isin(st_set)
    lim = np.where(df["is20"], 0.20, 0.10)
    r_th = np.where(df["is20"], 0.195, 0.095)
    abn = df["ret"].abs() > np.where(df["is20"], 0.22, 0.12)
    zt_px = np.floor(pc_raw * (1.0 + lim) * 100.0 + 0.5) / 100.0
    dt_px = np.floor(pc_raw * (1.0 - lim) * 100.0 + 0.5) / 100.0
    df["is_zt"] = (pac > 0) & (df["close"] >= zt_px - 0.011) & (df["ret"] >= r_th) & (~abn)
    df["is_dt"] = (pac > 0) & (df["close"] <= dt_px + 0.011) & (df["ret"] <= -r_th) & (~abn)
    df["open_zt"] = (pac > 0) & (df["open"] >= zt_px - 0.011) & (df["o_pct"] >= r_th)

    zt_ns = (df["non_st"] & df["is_zt"] & (df["is10"] | df["is20"])).to_numpy(dtype=np.int32)
    zt10_ns = (df["non_st"] & df["is10"] & df["is_zt"]).to_numpy(dtype=np.int32)
    c6_a = df["c6"].to_numpy()
    st_all, st10 = np.zeros(len(df), dtype=np.int32), np.zeros(len(df), dtype=np.int32)
    ca, c1, prev_c = 0, 0, ""
    for i in range(len(df)):
        if c6_a[i] != prev_c:
            ca, c1, prev_c = 0, 0, c6_a[i]
        ca = ca + 1 if zt_ns[i] else 0
        c1 = c1 + 1 if zt10_ns[i] else 0
        st_all[i], st10[i] = ca, c1
    df["st_all"] = st_all
    df["st10"] = st10
    df["prev_st_all"] = g["st_all"].shift(1).fillna(0).astype(int)
    df["prev_st10"] = g["st10"].shift(1).fillna(0).astype(int)
    df["next_dt"] = g["dt"].shift(-1).fillna("")
    df["next_is_zt"] = g["is_zt"].shift(-1).fillna(False).astype(bool)
    df["next_ret"] = g["ret"].shift(-1)

    # Stock-level precomputed fields for target_codes
    sub_df = df[df["c6"].isin(target_codes)][["c6", "dt", "close", "adj_close", "ret", "is_zt", "is_dt"]].copy()
    sub_df = sub_df.sort_values(["c6", "dt"]).reset_index(drop=True)

    # Compute RD013 settled brk_r10 & reb4_10d by SETTLEMENT date = next_dt!
    brk_mask = df["non_st"] & (df["is10"] | df["is20"]) & (df["prev_st_all"] >= 1) & (~df["is_zt"]) & (df["next_dt"] != "")
    reb4_mask = df["non_st"] & df["is10"] & (df["prev_st10"] >= 4) & (~df["is_zt"]) & (df["next_dt"] != "")
    brk_agg = df[brk_mask].groupby("next_dt").agg(brk_den=("next_is_zt", "count"), brk_num=("next_is_zt", "sum"))
    reb4_agg = df[reb4_mask].groupby("next_dt").agg(reb4_den=("next_ret", "count"), reb4_num=("next_ret", lambda s: int((s > 0).sum())))

    df["is_tech"] = df["c6"].isin(tech_codes)
    df["is_bank"] = df["c6"].isin(bank_codes)
    all_dts = sorted(df["dt"].unique())
    rows = []
    for dt, grp in df.groupby("dt", sort=True):
        ns = grp[grp["non_st"]]
        ns10 = ns[ns["is10"]]
        ns20 = ns[ns["is20"]]
        t_g = grp[grp["is_tech"] & grp["ret"].notna()]
        b_g = grp[grp["is_bank"] & grp["ret"].notna()]
        s10_zt = ns10[ns10["st10"] > 0]["st10"]
        rows.append({
            "dt": dt,
            "mkt_amt": float(grp["amount"].sum()),
            "mkt_ret": float(grp["ret"].mean()) if len(grp) else 0.0,
            "tech_ret": float(t_g["ret"].mean()) if len(t_g) else 0.0,
            "bank_ret": float(b_g["ret"].mean()) if len(b_g) else 0.0,
            "mkt_all_nonst_dt": int(ns["is_dt"].sum()),
            "mkt_all_nonst_zt": int(ns["is_zt"].sum()),
            "mkt10_nonst_zt": int(ns10["is_zt"].sum()),
            "mkt20_nonst_zt": int(ns20["is_zt"].sum()),
            "mkt20_nonst_dt": int(ns20["is_dt"].sum()),
            "mkt_all_nonst_0925_zt": int(ns["open_zt"].sum()),
            "mkt20_0925_zt": int(ns20["open_zt"].sum()),
            "mkt20_0925_gap": float(ns20["o_pct"].mean()) if len(ns20) else 0.0,
            "max_streak_10cm": int(s10_zt.max()) if len(s10_zt) else 0,
            "cnt_1_2": int(((s10_zt >= 1) & (s10_zt <= 2)).sum()),
            "cnt_3plus": int((s10_zt >= 3).sum()),
            "cnt_4_6": int(((s10_zt >= 4) & (s10_zt <= 6)).sum()),
            "old_dragon_brk_cnt": int(((ns10["prev_st10"] >= 4) & (~ns10["is_zt"])).sum()),
        })
    mkt = pd.DataFrame(rows).sort_values("dt").reset_index(drop=True)
    mkt["hs300_close"] = mkt["dt"].map(sh300)
    mkt["sz399107_close"] = mkt["dt"].map(sz399107)
    mkt["hs300_ret"] = mkt["hs300_close"] / mkt["hs300_close"].shift(1) - 1.0
    mkt["hs300_ma20"] = mkt["hs300_close"].rolling(20, min_periods=10).mean()
    mkt["hs300_dd60"] = mkt["hs300_close"] / mkt["hs300_close"].rolling(60, min_periods=10).max() - 1.0
    mkt["mkt_amt_ma20"] = mkt["mkt_amt"].rolling(20, min_periods=5).mean()
    mkt["mkt_dt_ma20"] = mkt["mkt_all_nonst_dt"].rolling(20, min_periods=5).mean()
    mkt["mkt_dt_spike20"] = mkt["mkt_all_nonst_dt"] / mkt["mkt_dt_ma20"].clip(lower=1.0)
    mkt = mkt.merge(brk_agg, left_on="dt", right_index=True, how="left").merge(reb4_agg, left_on="dt", right_index=True, how="left")
    for c in ["brk_den", "brk_num", "reb4_den", "reb4_num"]:
        mkt[c] = mkt[c].fillna(0.0)
    mkt["brk_r10"] = mkt["brk_num"].rolling(10, min_periods=1).sum() / mkt["brk_den"].rolling(10, min_periods=1).sum().clip(lower=1.0)
    mkt["reb4_10d"] = mkt["reb4_num"].rolling(10, min_periods=1).sum() / mkt["reb4_den"].rolling(10, min_periods=1).sum().clip(lower=1.0)
    mkt["gap_void_defA"] = ((mkt["cnt_4_6"] == 0) & (mkt["cnt_1_2"] >= 30)).astype(int)
    mkt["gap_ice_defB"] = ((mkt["max_streak_10cm"] <= 2) & (mkt["cnt_3plus"] == 0)).astype(int)
    mkt["old_dragon_brk_1_2d"] = ((mkt["old_dragon_brk_cnt"] + mkt["old_dragon_brk_cnt"].shift(1).fillna(0)) >= 1).astype(int)
    mkt["rd012_shrink_bank_fake"] = ((mkt["mkt_amt"] < mkt["mkt_amt_ma20"]) & (mkt["bank_ret"] > 0)).astype(int)
    mkt["rd012_panic_crash"] = ((mkt["mkt_amt"] >= mkt["mkt_amt_ma20"]) & (mkt["hs300_ret"] <= -0.02)).astype(int)
    mkt["rd012_tech_retreat"] = (mkt["tech_ret"] <= -0.02).astype(int)
    mkt["rd012_bank_minus_tech"] = mkt["bank_ret"] - mkt["tech_ret"]
    return mkt, bar_lu, sub_df, sh300, sz399107, all_sh_dts, all_dts
