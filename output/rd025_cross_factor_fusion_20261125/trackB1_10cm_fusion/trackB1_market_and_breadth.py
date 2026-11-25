#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Single-pass market breadth, defensive, rebound, ladder-gap, 20cm cross-board & stock bars builder."""
import bisect
import json
import os
import sqlite3
import sys
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
if PARTA_DIR not in sys.path:
    sys.path.insert(0, PARTA_DIR)
import mod_common as mc


def build_market_breadth_and_bars(pool_codes: set, all_dts: list[str], prev_td: dict, sh300: dict):
    fb20_cnt_map = mc.build_fb20_cln_dates_pit("2026-11-16")
    s20 = pd.read_csv(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_all_scored_signals.csv", dtype={"c6": str})
    a76_dts = set(s20[s20["score"] >= 76]["buy_date"].astype(str))

    ind_df = pd.read_csv(f"{SIM}/data/industry.csv")
    ind_map = dict(zip(ind_df["code"].astype(str).str[-6:].str.zfill(6), ind_df["industry"].fillna("")))
    nm_map = dict(zip(ind_df["code"].astype(str).str[-6:].str.zfill(6), ind_df["code_name"].fillna("")))
    tech_c = {c for c, ind in ind_map.items() if str(ind).startswith(("C39", "I65", "I63"))}
    bank_c = {c for c, ind in ind_map.items() if str(ind).startswith("J66") and "银行" in nm_map.get(c, "")}

    # PIT ST set from zt_micro_tape + notices (strictly per date)
    st_ev = defaultdict(list)
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for td, sc6, nm in con_z.execute("SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date >= '2020-09-01'"):
        s = str(nm or "").strip()
        if s: st_ev[str(sc6).zfill(6)].append((f"{td} 15:00:00", 1 if ("ST" in s or "退" in s) else 0))
    con_z.close()
    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc6, ti, ts in con_n.execute("SELECT sec_code, title, pub_datetime_cst FROM notices WHERE pub_datetime_cst >= '2020-09-01' AND (title LIKE '%风险警示%' OR title LIKE '%整理期%' OR title LIKE '%终止上市%')"):
        t_s, ts_s, c6 = str(ti or ""), str(ts)[:19], str(sc6).zfill(6)
        if mc.ST_REV_RE.search(t_s) and "不" not in t_s[:10]: st_ev[c6].append((ts_s, 0))
        elif mc.ST_ON_RE.search(t_s) and not mc.ST_EXC_RE.search(t_s): st_ev[c6].append((ts_s, 1))
    con_n.close()
    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    flt = ds.field("date") >= pd.Timestamp("2020-09-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df = pd.concat([da, dd], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & (df["close"] > 0) & (df["adj_close"] > 0)].copy()
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    g = df.groupby("c6", sort=False)
    sc = df["adj_close"] / df["close"]
    pac = g["adj_close"].shift(1)
    pc_raw = pac / sc
    df["ret"] = df["adj_close"] / pac - 1.0
    is20 = df["c6"].str.startswith(("30", "688", "689"))
    is10 = df["c6"].str.startswith(("00", "60"))
    lim = np.where(is20, 0.20, 0.10)
    r_th = np.where(is20, 0.195, 0.095)
    abn = df["ret"].abs() > np.where(is20, 0.22, 0.12)
    zt_px = np.floor(pc_raw * (1.0 + lim) * 100.0 + 0.5) / 100.0
    dt_px = np.floor(pc_raw * (1.0 - lim) * 100.0 + 0.5) / 100.0

    df["is10"], df["is20"] = is10, is20
    df["is_zt"] = (pac > 0) & (df["close"] >= zt_px - 0.011) & (df["ret"] >= r_th) & (~abn)
    df["is_dt"] = (pac > 0) & (df["close"] <= dt_px + 0.011) & (df["ret"] <= -r_th) & (~abn)
    df["is_yizi"] = df["is_zt"] & (df["low"] == df["high"]) & ((df["open"] * sc / pac - 1.0) >= r_th)
    df["mcap_yi"] = df["close"] * df["oshare"].fillna(0.0) / 1e8
    df["is_st"] = [0 if c6 not in st_tl else mc._is_st_at(st_tl, c6, f"{dt} 15:00:00") for c6, dt in zip(df["c6"], df["dt"])]

    s10 = (df["is10"] & (df["is_st"] == 0) & df["is_zt"]).astype(int)
    s10_sh = df.groupby("c6", sort=False)["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak10"] = s10.groupby([df["c6"], (s10 != s10_sh).cumsum()]).cumsum() * s10
    g = df.groupby("c6", sort=False)
    df["prev_st10"] = g["streak10"].shift(1).fillna(0).astype(int)
    df["next_ret"] = g["ret"].shift(-1)
    df["next_is_zt10"] = (g["is_zt"].shift(-1).fillna(False) & df["is10"] & (df["is_st"] == 0))

    # Build daily market aggregates (settled on date t)
    d_rows = {}
    dts_m = sorted(df["dt"].unique())
    csi_s = pd.Series({d: sh300[d] for d in sorted(sh300)})
    csi_ret = csi_s.pct_change().to_dict()
    for dt, grp in df[df["dt"] >= "2021-01-01"].groupby("dt", sort=True):
        ns = grp[grp["is_st"] == 0]
        ns10 = ns[ns["is10"]]
        ns20 = ns[ns["is20"]]
        mkt_amt = float(grp["amount"].sum())
        t_ret = float(grp[grp["c6"].isin(tech_c)]["ret"].mean()) if grp["c6"].isin(tech_c).any() else 0.0
        b_ret = float(grp[grp["c6"].isin(bank_c)]["ret"].mean()) if grp["c6"].isin(bank_c).any() else 0.0
        st10 = ns10["streak10"].to_numpy()
        c1, c2, c3, c4, c5, c6 = [int((st10 == k).sum()) for k in range(1, 7)]
        c3p = int((st10 >= 3).sum())
        max_b = int(st10.max()) if len(st10) else 0
        # Breaks on t -> outcome at t+1 (settled at t+1 close!)
        brk_all = ns10[(ns10["prev_st10"] >= 1) & (~ns10["is_zt"])]
        brk_4p = ns10[(ns10["prev_st10"] >= 4) & (~ns10["is_zt"])]
        s1_t = ns10[(ns10["streak10"] == 1) & (~ns10["is_yizi"])]
        d_rows[dt] = {
            "dt": dt, "mkt_amt": mkt_amt, "tech_ret": t_ret, "bank_ret": b_ret,
            "csi_ret": float(csi_ret.get(dt, 0.0)), "dt_cnt": int(ns["is_dt"].sum()),
            "mkt20_zt": int(ns20["is_zt"].sum()), "mkt20_dt": int(ns20["is_dt"].sum()),
            "c1": c1, "c2": c2, "c3p": c3p, "c4": c4, "c5": c5, "c6": c6, "max_b": max_b,
            "brk_den": int(len(brk_all)), "brk_reb_num": int(brk_all["next_is_zt10"].sum()),
            "brk4_den": int(len(brk_4p)), "brk4_red_num": int((brk_4p["next_ret"] > 0).sum()),
            "s1_den": int(len(s1_t)), "s1_num": int(s1_t["next_is_zt10"].sum()),
        }
    md = pd.DataFrame(d_rows.values()).sort_values("dt").reset_index(drop=True)
    md["amt_ma20"] = md["mkt_amt"].rolling(20, min_periods=5).mean()
    md["amt_ratio20"] = md["mkt_amt"] / md["amt_ma20"].replace(0, np.nan)
    # Outcomes from day t settle at t+1 close -> shift(1) so at EOD d-1 we only include t <= d-2 (settled <= d-1)!
    md["brk_r10_settled"] = (
        md["brk_reb_num"].shift(1).rolling(10, min_periods=1).sum()
        / md["brk_den"].shift(1).rolling(10, min_periods=1).sum().replace(0, np.nan)
    ).fillna(0.10)
    md["reb4_10d_settled"] = (
        md["brk4_red_num"].shift(1).rolling(10, min_periods=1).sum()
        / md["brk4_den"].shift(1).rolling(10, min_periods=1).sum().replace(0, np.nan)
    ).fillna(0.35)
    md["s1_promo_settled"] = (md["s1_num"].shift(1) / md["s1_den"].shift(1).replace(0, np.nan)).fillna(0.15)
    md_map = md.set_index("dt").to_dict("index")

    # Map buy_date -> strictly PIT market breadth/defensive/rebound/ladder/20cm features
    mkt_feats = {}
    for dt in all_dts:
        if dt < "2021-10-01" or dt > "2026-11-16": continue
        d1 = prev_td.get(dt, "")
        r = md_map.get(d1)
        if not r:
            continue
        ar = float(r["amt_ratio20"]) if pd.notna(r["amt_ratio20"]) else 1.0
        cr = float(r["csi_ret"]) if pd.notna(r["csi_ret"]) else 0.0
        br = float(r["bank_ret"]) if pd.notna(r["bank_ret"]) else 0.0
        tr = float(r["tech_ret"]) if pd.notna(r["tech_ret"]) else 0.0
        mkt_feats[dt] = {
            "f21_mkt_shrink_bank_fake_d1": int((ar < 1.0) and (br > 0.0) and (cr < 0.0)),
            "f22_mkt_panic_wash_d1": int((ar >= 1.0) and ((cr <= -0.015) or (r["dt_cnt"] >= 25))),
            "f23_mkt_csi300_ret_d1": cr,
            "f24_mkt_tech_retreat_d1": tr,
            "f25_mkt_amt_ratio20_d1": ar,
            "f41_reb_brk_r10_d1": float(r["brk_r10_settled"]),
            "f42_reb_4p_10d_d1": float(r["reb4_10d_settled"]),
            "f43_reb_mkt_max_board_d1": int(r["max_b"]),
            "f50_lad_gap_A_d1": int((r["c4"] == 0) and (r["c5"] == 0) and (r["c6"] == 0) and ((r["c1"] + r["c2"]) >= 30)),
            "f51_lad_gap_B_d1": int(r["max_b"] <= 2),
            "f52_lad_3p_cnt_d1": int(r["c3p"]),
            "f53_lad_s1_promo_d1": float(r["s1_promo_settled"]),
            "f54_c20_fb20_cln_cnt": int(fb20_cnt_map.get(dt, 0)),
            "f55_c20_a76_flag": int(dt in a76_dts),
            "f56_c20_mkt20_zt_d1": int(r["mkt20_zt"]),
            "f57_c20_mkt20_dt_d1": int(r["mkt20_dt"]),
        }

    # Build (dt, c6) -> big100yi_active set for midfielder resonance
    big_active = {
        dt: set(grp.loc[(grp["mcap_yi"] >= 100.0) & ((grp["ret"] >= 0.05) | grp["is_zt"]), "c6"])
        for dt, grp in df[df["dt"] >= "2021-10-01"].groupby("dt", sort=False)
    }

    # Extract per-stock bar arrays for pool_codes
    sub_df = df[df["c6"].isin(pool_codes)].copy()
    stock_bars = {}
    for c6, grp in sub_df.groupby("c6", sort=False):
        grp = grp.reset_index(drop=True)
        dts = grp["dt"].to_numpy()
        stock_bars[c6] = {
            "dts": dts, "dt_to_idx": {d: i for i, d in enumerate(dts)},
            "open": grp["open"].to_numpy(float), "close": grp["close"].to_numpy(float),
            "adj_close": grp["adj_close"].to_numpy(float), "mcap_yi": grp["mcap_yi"].to_numpy(float),
            "is_zt": grp["is_zt"].to_numpy(bool), "streak10": grp["streak10"].to_numpy(int),
        }
    return pd.DataFrame.from_dict(mkt_feats, orient="index"), stock_bars, big_active, fb20_cnt_map
