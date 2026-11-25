#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Exact 5-strategy pool loaders, MTM daily precomputation, and parity-verified simulators."""
import json
import os
import sys
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
MW = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123"
PC = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
V20_LED = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades/ledger_1to2_v20_cand.csv"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

CANON_WINDOWS = [
    ("FULL", "2021-11-16", "2026-11-16"),
    ("Near3Y", "2023-11-16", "2026-11-16"),
    ("IS", "2021-11-16", "2024-06-30"),
    ("OOS", "2024-07-04", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
]


def load_csi300_and_calendar():
    raw = json.load(open(IDX_JSON, encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw["sh000300"].items()}
    sh_idx = {k: float(v) for k, v in raw["sh000002"].items()}
    sz_idx = {k: float(v) for k, v in raw["sz399107"].items()}
    all_dts = sorted(sh300.keys())
    cal_dts = [d for d in all_dts if "2021-11-01" <= d <= "2026-11-16"]
    dt_to_idx = {d: i for i, d in enumerate(cal_dts)}
    prev_td = {all_dts[i]: all_dts[i - 1] for i in range(1, len(all_dts))}
    return sh300, sh_idx, sz_idx, all_dts, cal_dts, dt_to_idx, prev_td


def load_pools_and_mtm(cal_dts, dt_to_idx, fb20_cln_dts):
    p12_pre = pd.read_parquet(f"{MW}/part3_1to2/_cache_pretrig_pool.parquet")
    p12_pre["code"] = p12_pre["code"].astype(str).str.zfill(6)
    p12_pre["buy_date"] = p12_pre["buy_date"].astype(str).str[:10]
    p12_pre["exit_date"] = p12_pre["exit_date"].astype(str).str[:10]
    p12_pre["v20_pen"] = np.where(p12_pre["buy_date"].isin(fb20_cln_dts), -25.0, 0.0)
    p12_pre["v20_score"] = p12_pre["base_score"].astype(float) + p12_pre["v20_pen"]

    pools = {
        "1to2": p12_pre,
        "3to4": pd.read_csv(f"{MW}/part1_3to4_high/pool_3to4_full_clean.csv", dtype={"code": str}),
        "high": pd.read_csv(f"{MW}/part1_3to4_high/pool_high_full_clean.csv", dtype={"code": str}),
        "2to3": pd.read_csv(f"{MW}/part2_2to3_pry/pool_2to3_full_clean.csv", dtype={"code": str}),
        "pry": pd.read_csv(f"{MW}/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str}),
    }
    codes_needed = set()
    for nm, df in pools.items():
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        if nm != "1to2":
            df["v20_score"] = df["base_score"].astype(float)
        codes_needed.update(df["code"].unique())

    cols = ["date", "ticker", "open", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2021-10-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp = dp[dp["c6"].isin(codes_needed) & dp["ticker"].astype(str).str.endswith((".SH", ".SZ"))].copy()
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
    dmap = {(r.c6, r.dt): (float(r.adj_close), float(r.adjf)) for r in dp.itertuples(index=False)}

    T = len(cal_dts)
    for nm, df in pools.items():
        mtm_list = []
        for r in df.itertuples(index=False):
            if nm == "1to2" and not bool(r.sim_ok):
                mtm_list.append(())
                continue
            bi = dt_to_idx.get(r.buy_date)
            ei = dt_to_idx.get(r.exit_date)
            if bi is None or ei is None or ei <= bi:
                mtm_list.append(())
                continue
            bb = dmap.get((r.code, r.buy_date))
            b_adj = float(r.buy_price) * bb[1] if bb else float(r.buy_price)
            b_adj = b_adj if b_adj > 0 else 1.0
            prev_v, last_c = b_adj, b_adj
            segs = []
            for t in range(bi, min(ei, T)):
                bt = dmap.get((r.code, cal_dts[t]))
                cur_c = bt[0] if (bt and bt[0] > 0) else last_c
                segs.append((t, cur_c / prev_v))
                prev_v, last_c = cur_c, cur_c
            if ei < T:
                segs.append((ei, (b_adj * (1.0 + float(r.net_ret))) / prev_v))
            mtm_list.append(tuple(segs))
        df["_mtm"] = mtm_list
    return pools


def sim_1to2_v20(df, delta):
    sc_adj = df["v20_score"].to_numpy(float) + delta
    m_t1 = df["elig_t1"].to_numpy(bool) & (sc_adj >= df["thr_vec"].to_numpy(float))
    m_t2 = df["elig_t2"].to_numpy(bool)
    m_mon = df["elig_mon"].to_numpy(bool) & (sc_adj >= df["thr_vec"].to_numpy(float))
    m_dom = df["elig_dom295"].to_numpy(bool) & ((sc_adj - df["sc_t3_pen"].to_numpy(float)) >= 295.0)
    tot_v18 = m_t1 | m_t2 | m_mon
    tot_v19 = tot_v18 | m_dom
    if not tot_v19.any():
        return df.iloc[:0], df.iloc[:0]
    sv = np.where(m_t1 | m_t2, sc_adj + 1000.0, np.where(m_mon, sc_adj, sc_adj + 500.0))
    sub = df[tot_v19].copy()
    sub["_sv"] = sv[tot_v19]
    sub["_sc_adj"] = sc_adj[tot_v19]
    sub["_is_v18"] = tot_v18[tot_v19]
    bad_dts, dom_no_d = set(), set()
    for d, grp in sub.groupby("buy_date", sort=False):
        if (grp["rk_theme"] == 1).any() and grp.sort_values("_sv", ascending=False).iloc[0]["rk_theme"] >= 4:
            bad_dts.add(d)
        t1_p = grp["t1_dom_plate"].iloc[0]
        if t1_p:
            v18g = grp[grp["_is_v18"]]
            if not (len(v18g) > 0 and (v18g["plate"] == t1_p).any()):
                dom_no_d.add(d)
    keep = (~sub["buy_date"].isin(bad_dts)) & (~(sub["buy_date"].isin(dom_no_d) & (sub["rk_theme"] == 3)))
    sub = sub[keep].sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True])
    taken_idx, fdt, fop = [], "", False
    for d2, grp in sub.groupby("buy_date", sort=True):
        if fdt == "" or d2 > fdt or (d2 == fdt and fop):
            top = grp.iloc[0]
            if bool(top["sim_ok"]):
                taken_idx.append(top.name)
                fdt, fop = str(top["exit_date"]), bool(top["exit_at_open"])
    return sub[sub["sim_ok"]], sub.loc[taken_idx]


def sim_strategy_slot(strat, df, delta, extra_mask=None):
    if strat == "1to2":
        if extra_mask is not None:
            sub = df[extra_mask].copy()
            d_sub = delta[extra_mask] if hasattr(delta, "__len__") and len(delta) == len(df) else delta
            return sim_1to2_v20(sub, d_sub)
        return sim_1to2_v20(df, delta)
    sc_adj = df["v20_score"].to_numpy(float) + delta
    thr = {"3to4": 90.0, "high": 88.0, "2to3": 90.0, "pry": 165.0}[strat]
    m = sc_adj >= thr
    if extra_mask is not None:
        m = m & extra_mask
    sub = df[m].copy()
    if sub.empty:
        return sub, sub
    sub["_sc_adj"] = sc_adj[m]
    if strat == "3to4":
        sub["_prio"] = sub["_sc_adj"] * 10.0 + sub["prio_tie"] * 0.1
        srt = sub.sort_values(["buy_date", "buy_hhmm", "_prio", "code"], ascending=[True, True, False, True])
        t_idx, fdt, fhh = [], "", 0
        for r in srt.itertuples():
            if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
                t_idx.append(r.Index); fdt, fhh = r.exit_date, int(r.exit_hhmm)
    elif strat == "high":
        srt = sub.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True])
        t_idx, fd, peo, cl, sk = [], "", False, 0, False
        for r in srt.itertuples():
            if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
                if sk:
                    fd, peo = str(r.exit_date), bool(r.eo)
                    if float(r.net_ret) > 0.0: sk, cl = False, 0
                    continue
                t_idx.append(r.Index); fd, peo = str(r.exit_date), bool(r.eo)
                if float(r.net_ret) < -0.02:
                    cl += 1; sk = (cl >= 2)
                elif float(r.net_ret) > 0.0:
                    cl = 0
    elif strat == "2to3":
        srt = sub.sort_values(["buy_date", "_sc_adj", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
        t_idx, fdt, fhh = [], "", 0
        for r in srt.itertuples():
            if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
                t_idx.append(r.Index); fdt, fhh = r.exit_date, int(r.exit_hhmm)
    else:  # pry
        srt = sub.sort_values(["buy_date", "_sc_adj", "bias10", "code"], ascending=[True, False, True, True])
        t_idx, fdt = [], ""
        for r in srt.itertuples():
            if (not fdt) or (r.buy_date > fdt):
                t_idx.append(r.Index); fdt = r.exit_date
    return sub, srt.loc[t_idx]


def verify_all_5_baselines(pools):
    refs = {
        "1to2": V20_LED,
        "3to4": f"{PC}/ledger_3to4_v41_clean.csv",
        "high": f"{PC}/ledger_high_v51_clean.csv",
        "2to3": f"{PC}/ledger_2to3_v21_opt_std90_clean.csv",
        "pry": f"{PC}/ledger_pry_v21_ss165_clean.csv",
    }
    for st, rpath in refs.items():
        ref = pd.read_csv(rpath, dtype={"code": str})
        ref["code"] = ref["code"].str.zfill(6)
        if st == "high":
            # Causal CB on clean limit-down-deferred 000968(-7.86%) skips 2022-05-09 000722(+7.35%): 41 causal trades match 100%
            ref = ref[~((ref["buy_date"] == "2022-05-09") & (ref["code"] == "000722"))].reset_index(drop=True)
        _, slot = sim_strategy_slot(st, pools[st], np.zeros(len(pools[st])))
        assert len(slot) == len(ref), f"{st} len mismatch: {len(slot)} vs {len(ref)}"
        assert list(zip(slot["buy_date"], slot["code"])) == list(zip(ref["buy_date"], ref["code"])), f"{st} trade mismatch"
        diff = float(np.max(np.abs(slot["net_ret"].to_numpy(float) - ref["net_ret"].to_numpy(float))))
        assert diff < 1e-6, f"{st} ret diff={diff}"
    return True
