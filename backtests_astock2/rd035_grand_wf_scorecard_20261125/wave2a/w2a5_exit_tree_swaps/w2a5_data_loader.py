#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-5 Data Loader:
Loads V20.0 6-strategy oldhot pools, master PIT table, daily OHLC+adjf+ZT/DT series (2020-09..2026-11-25),
index series (sh000300/sh000002/sz399107), and unified multi-cache 5m bars (strictly PIT, zero yfinance).
"""
import bisect
import json
import os
import pickle
import re
import sqlite3
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028 = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"

if WAVE1 not in sys.path:
    sys.path.insert(0, WAVE1)
if RD028 not in sys.path:
    sys.path.insert(0, RD028)

import step4_mod_rules_and_sim as m1
import wf_scorecard_engine as wfe


def load_unified_5m_bars(codes_needed: set[str], raw_open_map: dict[tuple[str, str], float]) -> dict[tuple[str, str], np.ndarray]:
    """
    Merge all local PIT 5m bar caches for codes_needed.
    Each entry is np.ndarray of shape (N, 7): [hhmm_int, open, high, low, close, volume, amount].
    Causally normalizes units using day 09:30 open if forward-split mismatch > 2%.
    """
    b5m = {}

    def _add_arr(c6: str, dt: str, arr: np.ndarray):
        key = (c6, dt)
        if key in b5m or arr is None or len(arr) == 0:
            return
        o_day = raw_open_map.get(key)
        o_5m = float(arr[0, 1])
        if o_day and o_day > 0 and o_5m > 0 and abs(o_5m / o_day - 1.0) > 0.02:
            scale = o_day / o_5m
            arr = arr.copy()
            arr[:, 1:5] *= scale
            arr[:, 6] *= scale
        b5m[key] = arr

    def _load_pq(path: str, cols_req=("c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount")):
        if not os.path.exists(path):
            return
        df = pd.read_parquet(path, columns=list(cols_req))
        df["c6"] = df["c6"].astype(str).str.zfill(6)
        df = df[df["c6"].isin(codes_needed)].copy()
        df["dt"] = df["date"].astype(str).str[:10]
        df.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
        for (c6, dt), grp in df.groupby(["c6", "dt"], sort=False):
            _add_arr(c6, dt, grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=np.float64))

    _load_pq(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    _load_pq(f"{SIM}/output/slippage_velocity_audit_20261125/part2_trigger_price_opt/_patch_5m_bars.parquet")
    _load_pq(f"{SIM}/backtests_astock/ablation_1to2_price60_20261119/gt60_5m_patch.parquet")

    sub2_p = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"
    if os.path.exists(sub2_p):
        sub2 = pickle.load(open(sub2_p, "rb"))
        for k, v in sub2.items():
            c6, dt = str(k[0]).zfill(6), str(k[2])[:10]
            if c6 in codes_needed and isinstance(v, pd.DataFrame) and not v.empty:
                sub = v[v["date"] == dt] if "date" in v.columns else v
                if not sub.empty:
                    hh = sub["hhmm"].astype(str).str.replace(":", "").astype(int).to_numpy(dtype=np.float64)
                    arr = np.column_stack([
                        hh, sub["open"].to_numpy(float), sub["high"].to_numpy(float),
                        sub["low"].to_numpy(float), sub["close"].to_numpy(float),
                        sub["volume"].to_numpy(float), sub["amount"].to_numpy(float),
                    ])
                    _add_arr(c6, dt, arr)

    supp_p = f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_5m_supplement_bs.pkl"
    if os.path.exists(supp_p):
        s23 = pickle.load(open(supp_p, "rb")).get("supp_5m", {})
        for k, arr in s23.items():
            c6, dt = str(k[0]).zfill(6), str(k[1])[:10]
            if c6 in codes_needed and arr is not None and len(arr) > 0:
                _add_arr(c6, dt, np.asarray(arr, dtype=np.float64))

    c23_p = f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl"
    if os.path.exists(c23_p):
        c23 = pickle.load(open(c23_p, "rb")).get("b5m_need", {})
        for k, arr in c23.items():
            c6, dt = str(k[0]).zfill(6), str(k[1])[:10]
            if c6 in codes_needed and arr is not None and len(arr) > 0:
                _add_arr(c6, dt, np.asarray(arr, dtype=np.float64))

    return b5m


def load_w2a5_context(end_cutoff: str = "2026-11-16", load_5m: bool = True) -> dict:
    """Load complete W2A-5 context with zero production mutations."""
    v20_ctx = wfe.load_v20_reference_context(WAVE1)
    master = pd.read_parquet(f"{WAVE1}/pools_6strat_master_newfactors_pit.parquet")
    master["code"] = master["code"].astype(str).str.zfill(6)
    master["buy_date"] = master["buy_date"].astype(str).str[:10]
    master["exit_date"] = master["exit_date"].astype(str).str[:10]
    master = master[master["buy_date"] <= end_cutoff].copy().reset_index(drop=True)

    codes = set(master["code"].unique())
    raw_idx = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw_idx["sh000300"].items() if k <= end_cutoff}
    sh_idx = {k: float(v) for k, v in raw_idx["sh000002"].items() if k <= end_cutoff}
    sz_idx = {k: float(v) for k, v in raw_idx["sz399107"].items() if k <= end_cutoff}
    all_sh_dts = sorted(sh300.keys())
    cal_full = [d for d in all_sh_dts if "2021-01-04" <= d <= end_cutoff]
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= min(end_cutoff, "2026-11-16")]

    # Load daily bars for all pool codes strictly <= end_cutoff
    cols_b = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor", "turn", "volume"]
    flt = (ds.field("date") >= pd.Timestamp("2020-09-01")) & (ds.field("date") <= pd.Timestamp(end_cutoff))
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols_b, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols_b, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    del da, dd
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp = dp[dp["c6"].isin(codes) & dp["ticker"].astype(str).str.endswith((".SH", ".SZ")) & (dp["close"] > 0) & (dp["adj_close"] > 0)].copy()
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = dp["adj_close"] / dp["close"]

    # Strictly PIT ST timeline from zt_micro_tape + reg_tox_notices (same as build_v20_calendar_and_parity.py)
    st_on_re = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
    st_exc_re = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
    st_rev_re = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")
    st_ev = defaultdict(list)
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for td, sc6, nm in con_z.execute("SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ?", (end_cutoff,)):
        c6s = str(sc6).zfill(6)
        if c6s in codes:
            s = str(nm or "").strip()
            if s:
                st_ev[c6s].append((f"{td} 15:00:00", 1 if ("ST" in s.upper() or "退" in s) else 0))
    con_z.close()
    rt = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    rt["ts"] = rt["pub_datetime_cst"].astype(str).str[:19]
    rt = rt[(rt["ts"] <= f"{end_cutoff} 23:59:59") & rt["c6"].isin(codes)]
    for r in rt.itertuples(index=False):
        t_s = str(r.title or "")
        if st_rev_re.search(t_s):
            st_ev[r.c6].append((r.ts, 0))
        elif st_on_re.search(t_s) and not st_exc_re.search(t_s):
            st_ev[r.c6].append((r.ts, 1))
    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}

    is_st = np.zeros(len(dp), dtype=bool)
    c6_arr = dp["c6"].to_numpy()
    dt_arr = dp["dt"].to_numpy()
    i, n_tot = 0, len(dp)
    while i < n_tot:
        c = c6_arr[i]
        j = i + 1
        while j < n_tot and c6_arr[j] == c:
            j += 1
        tl = st_tl.get(c)
        if tl:
            ts_l, val_l = tl
            for k_i in range(i, j):
                pos_s = bisect.bisect_left(ts_l, f"{dt_arr[k_i]} 15:00:00")
                if pos_s > 0 and val_l[pos_s - 1] == 1:
                    is_st[k_i] = True
        i = j

    g = dp.groupby("c6", sort=False)
    dp["prev_adj_c"] = g["adj_close"].shift(1)
    dp["prev_c_raw"] = dp["prev_adj_c"] / dp["adjf"]
    is_20 = dp["c6"].str.startswith(("30", "688", "689")).to_numpy()
    lim = np.where(is_20, 0.20, np.where(is_st & (dt_arr < "2026-07-06"), 0.05, 0.10))
    pc_v = dp["prev_c_raw"].to_numpy(float)
    dp["lim"] = lim
    dp["zt_px"] = np.floor(pc_v * (1.0 + lim) * 100.0 + 0.5) / 100.0
    dp["dt_px"] = np.floor(pc_v * (1.0 - lim) * 100.0 + 0.5) / 100.0
    vp = np.isfinite(pc_v) & (pc_v > 0)
    dp["is_zt"] = vp & (~is_st) & (dp["close"] >= dp["zt_px"] - 0.011) & (dp["adj_close"] / dp["prev_adj_c"] - 1.0 >= lim - 0.005)
    dp["is_dt"] = vp & (~is_st) & (dp["close"] <= dp["dt_px"] + 0.011) & (dp["adj_close"] / dp["prev_adj_c"] - 1.0 <= -(lim - 0.005))
    dp["is_yizi_zt"] = dp["is_zt"] & (dp["open"] >= dp["zt_px"] - 0.011) & (dp["low"] >= dp["zt_px"] - 0.011)
    dp["is_yizi_dt"] = dp["is_dt"] & (dp["open"] <= dp["dt_px"] + 0.011) & (dp["high"] <= dp["dt_px"] + 0.011)
    dp["open_is_dt"] = vp & (dp["open"] <= dp["dt_px"] + 0.011)
    dp["open_is_zt"] = vp & (dp["open"] >= dp["zt_px"] - 0.011)

    bar_lu = {}
    raw_open_map = {}
    stock_series = {}
    for c6, grp in dp.groupby("c6", sort=False):
        dts_a = grp["dt"].to_numpy()
        o_a = grp["open"].to_numpy(float)
        h_a = grp["high"].to_numpy(float)
        l_a = grp["low"].to_numpy(float)
        c_a = grp["close"].to_numpy(float)
        ac_a = grp["adj_close"].to_numpy(float)
        qf_a = grp["qfq_factor"].to_numpy(float)
        af_a = grp["adjf"].to_numpy(float)
        pc_a = grp["prev_c_raw"].to_numpy(float)
        zt_a = grp["zt_px"].to_numpy(float)
        dt_a = grp["dt_px"].to_numpy(float)
        izt_a = grp["is_zt"].to_numpy(bool)
        idt_a = grp["is_dt"].to_numpy(bool)
        iyzz_a = grp["is_yizi_zt"].to_numpy(bool)
        iyzd_a = grp["is_yizi_dt"].to_numpy(bool)
        oid_a = grp["open_is_dt"].to_numpy(bool)
        oiz_a = grp["open_is_zt"].to_numpy(bool)
        lim_a = grp["lim"].to_numpy(float)
        turn_a = grp["turn"].fillna(0.0).to_numpy(float)
        d2i = {str(d): i for i, d in enumerate(dts_a)}
        stock_series[c6] = {
            "dts": dts_a, "d2i": d2i, "open": o_a, "high": h_a, "low": l_a, "close": c_a,
            "adj_close": ac_a, "adjf": af_a, "prev_c": pc_a, "zt_px": zt_a, "dt_px": dt_a,
            "is_zt": izt_a, "is_dt": idt_a, "is_yizi_zt": iyzz_a, "is_yizi_dt": iyzd_a,
            "open_is_dt": oid_a, "open_is_zt": oiz_a, "lim": lim_a, "turn": turn_a,
        }
        for i in range(len(dts_a)):
            dstr = str(dts_a[i])
            bar_lu[(c6, dstr)] = (o_a[i], c_a[i], ac_a[i], qf_a[i], af_a[i])
            raw_open_map[(c6, dstr)] = o_a[i]

    b5m = load_unified_5m_bars(codes, raw_open_map) if load_5m else {}

    pools = {}
    for st in m1.STRAT_ORDER:
        df_p = pd.read_parquet(f"{RD028}/pool_{st}_oldhot.parquet")
        df_p["code"] = df_p["code"].astype(str).str.zfill(6)
        df_p["buy_date"] = df_p["buy_date"].astype(str).str[:10]
        df_p["exit_date"] = df_p["exit_date"].astype(str).str[:10]
        df_p = df_p[df_p["buy_date"] <= end_cutoff].copy().reset_index(drop=True)
        if st == "20cm":
            df_p["exit_hhmm"] = np.where(df_p["exit_reason"].astype(str).str.contains("open|gap|tp"), 1030, 1500)
            df_p["buy_price_val"] = df_p["buy_px"].astype(float)
            df_p["is_adj_px"] = True
        else:
            df_p["buy_price_val"] = df_p["buy_price"].astype(float)
            df_p["is_adj_px"] = False
        if st == "high":
            df_p["v51_cb_loss"] = (df_p["net_ret"].to_numpy(float) < -0.02) & (~df_p["dt_deferred"].to_numpy(bool))
        df_p["native_net_ret"] = df_p["net_ret"].astype(float)
        df_p["native_exit_date"] = df_p["exit_date"].astype(str)
        df_p["native_exit_hhmm"] = df_p["exit_hhmm"].astype(int)
        if "exit_price" not in df_p.columns and "exit_px" in df_p.columns:
            df_p["exit_price"] = df_p["exit_px"].astype(float)
        df_p["native_exit_price"] = df_p["exit_price"].astype(float)
        pools[st] = df_p

    # Fast light-weight untriggered pool (100% identical to m1.load_untrig_with_oldhot())
    untrig_p = f"{SIM}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125/rd034_untrig_with_3layer_cycles.parquet"
    untrig_base = pd.read_parquet(untrig_p)
    untrig_base["buy_date"] = untrig_base["buy_date"].astype(str).str[:10]
    untrig_base["code"] = untrig_base["code"].astype(str).str.zfill(6)
    untrig_base["v20_score"] = untrig_base["score"].astype(float)
    untrig_base = untrig_base[untrig_base["buy_date"] <= end_cutoff].copy().reset_index(drop=True)
    mkt_daily = pd.read_parquet(f"{WAVE1}/market_daily_all_new_factors_pit.parquet")
    mkt_daily["trade_date"] = mkt_daily["trade_date"].astype(str).str[:10]
    mkt_daily = mkt_daily[mkt_daily["trade_date"] <= end_cutoff].copy().reset_index(drop=True)
    # Build causal previous-day market DT map keyed by (trade_date -> dt10_t1, dt20_t1)
    # Note: on day tp1_dt, L1_dt_cnt_t1 and mkt20_dt_cnt_t1 in mkt_daily[trade_date == tp1_dt] ARE b0_dt's EOD counts!
    mkt_tp1_risk = {
        str(r.trade_date): (float(r.L1_dt_cnt_t1) >= 20.0 or float(r.mkt20_dt_cnt_t1) >= 3.0)
        for r in mkt_daily.itertuples(index=False)
    }
    xq_m1_map = {
        (str(r.strategy), str(r.buy_date), str(r.code)): (
            float(r.rd25_xq_3d_pre if pd.notna(r.rd25_xq_3d_pre) else 0.0),
            float(r.evo_zt_seal_ratio_d1 if pd.notna(r.evo_zt_seal_ratio_d1) else np.nan),
        )
        for r in master[["strategy", "buy_date", "code", "rd25_xq_3d_pre", "evo_zt_seal_ratio_d1"]].itertuples(index=False)
    }

    return {
        "v20_ctx": v20_ctx,
        "master": master,
        "pools": pools,
        "untrig_base": untrig_base,
        "mkt_daily": mkt_daily,
        "mkt_tp1_risk": mkt_tp1_risk,
        "xq_m1_map": xq_m1_map,
        "sh300": sh300,
        "sh_idx": sh_idx,
        "sz_idx": sz_idx,
        "all_sh_dts": all_sh_dts,
        "cal_full": cal_full,
        "cal_5y": cal_5y,
        "bar_lu": bar_lu,
        "stock_series": stock_series,
        "b5m": b5m,
    }
