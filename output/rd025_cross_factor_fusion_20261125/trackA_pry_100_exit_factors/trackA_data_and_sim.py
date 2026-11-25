#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
trackA_data_and_sim.py
Strictly PIT data loaders, 5m merger, market breadth builder, per-day feature extractor,
and unified 5-strategy exit simulator with exact baseline parity verification.
"""
import bisect
import datetime
import json
import os
import pickle
import re
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"

LEDGER_PATHS = {
    "1to2": f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades/ledger_1to2_v20_cand.csv",
    "3to4": f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_3to4_v41_clean.csv",
    "high": f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_high_v51_clean.csv",
    "2to3": f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_2to3_v21_opt_std90_clean.csv",
    "20cm": f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_ledger_S82.csv",
}

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")
LHB_CAT_EXPLAIN_RE = re.compile(r"(?:10个交易日|30个交易日|严重异常)")
LHB_CAT_NAMES = {"自然人", "中小投资者", "其他自然人", "机构投资者", "深股通投资者", "机构", "沪股通", "投资者分类"}


def _is_st_at(st_tl: dict, c6: str, cut_ts: str) -> int:
    tl = st_tl.get(c6)
    if not tl:
        return 0
    idx = bisect.bisect_left(tl[0], cut_ts)
    return int(tl[1][idx - 1]) if idx > 0 else 0


def _build_st_timeline() -> dict:
    st_ev = defaultdict(list)
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for td, sc, nm in con_z.execute("SELECT trade_date, sec_code, sec_name FROM zt_micro_tape"):
        s = str(nm or "").strip()
        if s:
            st_ev[str(sc).zfill(6)].append((f"{str(td)[:10]} 15:00:00", 1 if ("ST" in s.upper() or "退" in s) else 0))
    con_z.close()

    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, ti, ts in con_n.execute("SELECT sec_code, title, pub_datetime_cst FROM notices"):
        t_s, ts_s = str(ti or ""), str(ts or "")[:19]
        if not ts_s:
            continue
        c6 = str(sc).zfill(6)
        if ST_REV_RE.search(t_s) and "不" not in t_s[:10]:
            st_ev[c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[c6].append((ts_s, 1))
    con_n.close()

    rt = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    for r in rt.itertuples(index=False):
        t_s, ts_s = str(r.title or ""), str(r.pub_datetime_cst or "")[:19]
        c6 = str(r.sec_code)[:6].zfill(6)
        if ST_REV_RE.search(t_s) and "不" not in t_s[:10]:
            st_ev[c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[c6].append((ts_s, 1))

    return {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}


def _load_5m_bars(target_codes: set[str], dmap: dict) -> dict:
    bars = {}
    p5 = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    p5["c6"] = p5["c6"].astype(str).str.zfill(6)
    p5 = p5[p5["c6"].isin(target_codes)].copy()
    p5["dt"] = p5["date"].astype(str).str[:10]
    p5.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
    for (c6, dt), grp in p5.groupby(["c6", "dt"], sort=False):
        bars[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    def _try_add(key, arr):
        if key in bars or arr is None or len(arr) < 12 or key[0] not in target_codes:
            return
        db = dmap.get(key)
        if db is None or db.close <= 0:
            return
        if abs(float(arr[-1, 4]) - float(db.close)) / float(db.close) > 0.005:
            return
        bars[key] = arr

    for fp in [
        f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet",
        f"{SIM}/backtests_astock/ablation_1to2_price60_20261119/gt60_5m_patch.parquet",
    ]:
        if not os.path.exists(fp):
            continue
        d = pd.read_parquet(fp)
        d["c6"] = d["c6"].astype(str).str.zfill(6)
        d = d[d["c6"].isin(target_codes)].copy()
        if d.empty:
            continue
        if "hhmm_int" not in d.columns:
            d["hhmm_int"] = d["hhmm"].astype(int)
        d["dt"] = d["date"].astype(str).str[:10]
        d.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
        for (c6, dt), grp in d.groupby(["c6", "dt"], sort=False):
            _try_add((c6, dt), grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float))

    for fp, mode in [
        (f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "supp"),
        (f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl", "k02"),
    ]:
        if not os.path.exists(fp):
            continue
        obj = pickle.load(open(fp, "rb"))
        if mode == "supp":
            obj = obj.get("supp_5m", {})
        for k, val in obj.items():
            c6 = str(k[0]).zfill(6)
            if c6 not in target_codes:
                continue
            dt = str(k[2] if mode == "k02" else k[1])[:10]
            if (c6, dt) in bars:
                continue
            if isinstance(val, np.ndarray):
                _try_add((c6, dt), val.astype(float))
            elif isinstance(val, pd.DataFrame) and not val.empty:
                sub = val[val["date"].astype(str).str[:10] == dt] if "date" in val.columns else val
                if len(sub) >= 12:
                    hh = sub["hhmm"].astype(str).str.replace(":", "").astype(int).to_numpy()
                    arr = np.column_stack([
                        hh, sub["open"].to_numpy(), sub["high"].to_numpy(),
                        sub["low"].to_numpy(), sub["close"].to_numpy(),
                        sub["volume"].to_numpy(), sub["amount"].to_numpy(),
                    ]).astype(float)
                    _try_add((c6, dt), arr)
    return bars


def _load_lhb_pit(target_codes: set[str]) -> dict:
    cols = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "EXPLANATION", "TRADE_ID"]
    b_by_tid, s_by_tid, tid_meta = defaultdict(list), defaultdict(list), {}
    for fp, dst, is_b in [
        (f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet", b_by_tid, True),
        (f"{SIM}/backtest/2026-10-20-lhasa/lhb_sell.parquet", s_by_tid, False),
    ]:
        df = pd.read_parquet(fp, columns=cols)
        df["c6"] = df["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
        df = df[df["c6"].isin(target_codes)].copy()
        for r in df.itertuples(index=False):
            exp_s = str(r.EXPLANATION or "")
            dept_s = str(r.OPERATEDEPT_NAME or "").strip()
            if LHB_CAT_EXPLAIN_RE.search(exp_s) or dept_s in LHB_CAT_NAMES:
                continue
            dt_s = str(r.TRADE_DATE)[:10]
            tid_s = str(r.TRADE_ID or "")
            bf, sf = float(r.BUY or 0.0), float(r.SELL or 0.0)
            dst[(r.c6, dt_s, tid_s)].append((dept_s, bf, sf))
            cur = tid_meta.get((r.c6, dt_s, tid_s))
            if cur is None:
                tid_meta[(r.c6, dt_s, tid_s)] = ["连续" in exp_s, bf + sf]
            else:
                cur[1] += bf + sf

    best_tid = {}
    for (c6, dt_s, tid_s), (is3, vol) in tid_meta.items():
        ck = (1 if is3 else 0, -vol, tid_s)
        prev = best_tid.get((c6, dt_s))
        if prev is None or ck < prev[0]:
            best_tid[(c6, dt_s)] = (ck, tid_s)

    lhb_map = {}
    for (c6, dt_s), (_, tid_s) in best_tid.items():
        tot_b = tot_s = inst_b = inst_s = lh_b = 0.0
        lh_cnt = 0
        seen_lh = set()
        for dept, bf, sf in b_by_tid.get((c6, dt_s, tid_s), []):
            tot_b += bf
            if "机构专用" in dept:
                inst_b += bf
            if "拉萨" in dept:
                lh_b += bf
                if dept not in seen_lh:
                    seen_lh.add(dept)
                    lh_cnt += 1
        for dept, bf, sf in s_by_tid.get((c6, dt_s, tid_s), []):
            tot_s += sf
            if "机构专用" in dept:
                inst_s += sf
        lhb_map[(c6, dt_s)] = {
            "tot_b": tot_b,
            "tot_s": tot_s,
            "tot_net": tot_b - tot_s,
            "inst_net": inst_b - inst_s,
            "lh_ratio": (lh_b / tot_b) if tot_b > 0 else 0.0,
            "lh_cnt": lh_cnt,
        }
    return lhb_map


def _get_lock10_pit(holders: dict, c6: str, ref_dt: str) -> float:
    raw = holders.get(c6, [])
    best_ed, best_l = "", np.nan
    for x in raw:
        if isinstance(x, (list, tuple)) and len(x) >= 3:
            nd, ed, l10 = str(x[0])[:10], str(x[1])[:10], float(x[2])
            if nd <= ref_dt and ed >= best_ed:
                best_ed, best_l = ed, l10
        elif isinstance(x, dict):
            nd = str(x.get("ann_date", ""))[:10]
            if nd and nd <= ref_dt:
                best_l = float(x.get("top10_ratio", 0.0))
    return float(np.clip(best_l, 0.0, 95.0)) if not np.isnan(best_l) else 38.0


def build_context() -> dict:
    idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {str(k)[:10]: float(v) for k, v in idx_cache["sh000300"].items()}
    sh_map = {str(k)[:10]: float(v) for k, v in idx_cache["sh000002"].items()}
    sz_map = {str(k)[:10]: float(v) for k, v in idx_cache["sz399107"].items()}
    all_dts = sorted(d for d in sh300.keys() if "2020-09-01" <= d <= "2026-11-20")
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}

    ledgers = {}
    target_codes = set()
    for sk, fp in LEDGER_PATHS.items():
        df = pd.read_csv(fp)
        cc = "c6" if "c6" in df.columns else "code"
        df["c6"] = df[cc].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        if "buy_price" not in df.columns and "buy_px" in df.columns:
            df["buy_price"] = df["buy_px"]
        if "exit_price" not in df.columns and "exit_px" in df.columns:
            df["exit_price"] = df["exit_px"]
        df = df.sort_values(["buy_date", "buy_hhmm", "c6"]).reset_index(drop=True)
        ledgers[sk] = df
        target_codes.update(df["c6"].tolist())

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    flt = ds.field("date") >= pd.Timestamp("2020-09-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df_all = pd.concat([da, dd], ignore_index=True)
    df_all["c6"] = df_all["ticker"].astype(str).str[:6]
    df_all = df_all[df_all["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df_all["c6"].str.startswith(("00", "60", "30", "688", "689")) & (df_all["close"] > 0) & (df_all["adj_close"] > 0)].copy()
    df_all["dt"] = pd.to_datetime(df_all["date"]).dt.strftime("%Y-%m-%d")
    df_all = df_all.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    st_tl = _build_st_timeline()

    g_all = df_all.groupby("c6", sort=False)
    adjf_all = df_all["adj_close"] / df_all["close"]
    df_all["adjf"] = adjf_all
    df_all["pre_c"] = g_all["close"].shift(1) * g_all["adjf"].shift(1) / df_all["adjf"]
    is_20 = df_all["c6"].str.startswith(("30", "688", "689")).to_numpy()
    lim_r = np.where(is_20, 0.20, 0.10)
    df_all["zt_px"] = np.floor(df_all["pre_c"] * (1.0 + lim_r) * 100.0 + 0.5) / 100.0
    df_all["dt_px"] = np.floor(df_all["pre_c"] * (1.0 - lim_r) * 100.0 + 0.5) / 100.0
    pct_all = df_all["close"] / df_all["pre_c"] - 1.0
    opct_all = df_all["open"] / df_all["pre_c"] - 1.0
    abn_all = pct_all.abs() > np.where(is_20, 0.22, 0.12)
    df_all["is_zt"] = (df_all["pre_c"] > 0) & (df_all["close"] >= df_all["zt_px"] - 0.011) & (pct_all >= np.where(is_20, 0.195, 0.095)) & (~abn_all)
    df_all["is_dt"] = (df_all["pre_c"] > 0) & (df_all["close"] <= df_all["dt_px"] + 0.011) & (pct_all <= np.where(is_20, -0.195, -0.095)) & (~abn_all)
    df_all["open_zt"] = (df_all["pre_c"] > 0) & (df_all["open"] >= df_all["zt_px"] - 0.011) & (opct_all >= np.where(is_20, 0.195, 0.095))

    # PIT ST mask ONLY for zt/dt/open_zt rows (fast!)
    cand_st_idx = df_all.index[df_all["is_zt"] | df_all["is_dt"] | df_all["open_zt"]].to_numpy()
    st_flags = np.zeros(len(df_all), dtype=bool)
    c6_arr = df_all["c6"].to_numpy()
    dt_arr = df_all["dt"].to_numpy()
    for idx_i in cand_st_idx:
        if _is_st_at(st_tl, c6_arr[idx_i], f"{dt_arr[idx_i]} 15:00:00") == 1:
            st_flags[idx_i] = True
    df_all["is_st_row"] = st_flags

    clean_m = ~df_all["is_st_row"]
    mkt_dt_all = df_all[df_all["is_dt"] & clean_m].groupby("dt").size().to_dict()
    mkt_zt_all = df_all[df_all["is_zt"] & clean_m].groupby("dt").size().to_dict()
    mkt_open_zt_all = df_all[df_all["open_zt"] & clean_m].groupby("dt").size().to_dict()
    mkt_dt_10 = df_all[df_all["is_dt"] & clean_m & (~is_20)].groupby("dt").size().to_dict()

    # Override/supplement with rt_env_map where available? Wait: let's check alignment in run_trackA!
    rt_map = json.load(open(f"{SIM}/backtests_astock2/p5_full_pry_universe/rt_env_map.json", encoding="utf-8"))
    # Compute 5-day rolling mean of mkt_dt_10 strictly up to dt (excluding dt itself for next-day use)
    mkt_env = {}
    dt_hist_10 = []
    for d in all_dts:
        nd10 = int(mkt_dt_10.get(d, 0))
        nd_all = int(mkt_dt_all.get(d, 0))
        nz_all = int(mkt_zt_all.get(d, 0))
        ozt = int(rt_map[d]["mkt_open_zt_0925"]) if d in rt_map else int(mkt_open_zt_all.get(d, 0))
        ma5_dt10 = float(np.mean(dt_hist_10[-5:])) if dt_hist_10 else float(nd10)
        dt_hist_10.append(nd10)
        mkt_env[d] = {
            "mkt_dt_10": nd10,
            "mkt_dt_all": nd_all,
            "mkt_dt_ma5": ma5_dt10,
            "mkt_zt_all": nz_all,
            "mkt_0925_zt": ozt,
        }

    # Build rich target-stock daily bars
    df_tgt = df_all[df_all["c6"].isin(target_codes)].copy().sort_values(["c6", "dt"]).reset_index(drop=True)
    gt = df_tgt.groupby("c6", sort=False)
    df_tgt["ac"] = df_tgt["adj_close"]
    df_tgt["ao"] = df_tgt["open"] * df_tgt["adjf"]
    df_tgt["ah"] = df_tgt["high"] * df_tgt["adjf"]
    df_tgt["al"] = df_tgt["low"] * df_tgt["adjf"]
    df_tgt["is_dt_exact"] = (df_tgt["close"] <= df_tgt["dt_px"] + 0.005) & (df_tgt["pre_c"] > 0)
    df_tgt["is_yizi_dt"] = df_tgt["is_dt_exact"] & (df_tgt["open"] <= df_tgt["dt_px"] + 0.005) & (df_tgt["high"] <= df_tgt["dt_px"] + 0.005)
    df_tgt["ma5_ac"] = gt["ac"].transform(lambda s: s.rolling(5, min_periods=1).mean())
    df_tgt["ma10_ac"] = gt["ac"].transform(lambda s: s.rolling(10, min_periods=1).mean())
    df_tgt["ma20_ac"] = gt["ac"].transform(lambda s: s.rolling(20, min_periods=1).mean())
    df_tgt["max20_ac"] = gt["ac"].transform(lambda s: s.rolling(20, min_periods=1).max())
    df_tgt["max60_ac"] = gt["ac"].transform(lambda s: s.rolling(60, min_periods=1).max())
    df_tgt["min60_ac"] = gt["ac"].transform(lambda s: s.rolling(60, min_periods=1).min())
    df_tgt["ret10"] = df_tgt["ac"] / gt["ac"].shift(10) - 1.0
    df_tgt["amt_ma5_prev"] = gt["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    df_tgt["vr"] = df_tgt["amount"] / np.maximum(1.0, df_tgt["amt_ma5_prev"])
    est_sh = np.where(df_tgt["oshare"].fillna(0) > 0, df_tgt["oshare"], np.where(df_tgt["turn"] > 0, df_tgt["volume"] / df_tgt["turn"], np.nan))
    df_tgt["mcap"] = est_sh * df_tgt["close"] / 1e8

    holders10 = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json", encoding="utf-8"))
    holders20 = json.load(open(f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies/pit_top10_20cm_summary.json", encoding="utf-8"))
    holders_all = {**holders10, **holders20}

    code_bars = {}
    dmap = {}
    for c6, grp in df_tgt.groupby("c6", sort=False):
        grp = grp.reset_index(drop=True)
        dts = grp["dt"].tolist()
        # yang streak up to each bar
        c_arr = grp["close"].to_numpy(float)
        o_arr = grp["open"].to_numpy(float)
        pc_arr = grp["pre_c"].to_numpy(float)
        ys = np.zeros(len(grp), dtype=int)
        for i in range(len(grp)):
            if (c_arr[i] > o_arr[i]) or (pc_arr[i] > 0 and c_arr[i] > pc_arr[i]):
                ys[i] = (ys[i - 1] + 1) if i > 0 else 1
        code_bars[c6] = {
            "dts": dts,
            "dt_pos": {d: i for i, d in enumerate(dts)},
            "open": o_arr,
            "high": grp["high"].to_numpy(float),
            "low": grp["low"].to_numpy(float),
            "close": c_arr,
            "adj_close": grp["adj_close"].to_numpy(float),
            "ao": grp["ao"].to_numpy(float),
            "ah": grp["ah"].to_numpy(float),
            "al": grp["al"].to_numpy(float),
            "ac": grp["ac"].to_numpy(float),
            "adjf": grp["adjf"].to_numpy(float),
            "pre_c": pc_arr,
            "zt_px": grp["zt_px"].to_numpy(float),
            "dt_px": grp["dt_px"].to_numpy(float),
            "is_zt": grp["is_zt"].to_numpy(bool),
            "is_dt": grp["is_dt"].to_numpy(bool),
            "is_dt_exact": grp["is_dt_exact"].to_numpy(bool),
            "is_yizi_dt": grp["is_yizi_dt"].to_numpy(bool),
            "ma5_ac": grp["ma5_ac"].to_numpy(float),
            "ma10_ac": grp["ma10_ac"].to_numpy(float),
            "ma20_ac": grp["ma20_ac"].to_numpy(float),
            "max20_ac": grp["max20_ac"].to_numpy(float),
            "max60_ac": grp["max60_ac"].to_numpy(float),
            "min60_ac": grp["min60_ac"].to_numpy(float),
            "ret10": grp["ret10"].fillna(0.0).to_numpy(float),
            "vr": grp["vr"].fillna(1.0).to_numpy(float),
            "turn": grp["turn"].fillna(0.0).to_numpy(float),
            "mcap": grp["mcap"].fillna(50.0).to_numpy(float),
            "yang_streak": ys,
            "is_20cm": c6.startswith(("30", "688", "689")),
        }
        for r in grp.itertuples(index=False):
            dmap[(c6, r.dt)] = r

    bars_5m = _load_5m_bars(target_codes, dmap)
    lhb_map = _load_lhb_pit(target_codes)

    # Load 1to2 auxiliary M1 data (Xueqiu + seal_amount)
    c12_codes = set(ledgers["1to2"]["c6"].tolist())
    xq_sets = defaultdict(set)
    ph12 = ",".join(["?"] * len(c12_codes))
    con_xg = sqlite3.connect(f"file:{SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, ts in con_xg.execute(f"SELECT symbol, created_time_str FROM xueqiu_posts WHERE symbol IN ({ph12})", sorted(c12_codes)):
        if ts:
            xq_sets[str(sym)[:6].zfill(6)].add(str(ts)[:19])
    con_xg.close()
    con_cm = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, ts in con_cm.execute("SELECT symbol, pub_datetime_cst FROM community_posts WHERE source LIKE '%xueqiu%'"):
        c6s = str(sym)[-6:].zfill(6)
        if c6s in c12_codes and ts:
            xq_sets[c6s].add(str(ts)[:19])
    con_cm.close()
    xq_by_c6 = {k: np.array(sorted(v), dtype=object) for k, v in xq_sets.items()}

    con_zt = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    seal_amt_map = {}
    for td, sc, sa in con_zt.execute("SELECT trade_date, sec_code, seal_amount FROM zt_micro_tape"):
        c6s = str(sc).zfill(6)
        if c6s in c12_codes:
            seal_amt_map[(str(td)[:10], c6s)] = float(sa or 0.0)
    con_zt.close()

    # Load 3to4 risk7_score per (buy_date, code, dt_k) from pit_exit_cache_full.pkl
    sys.path.insert(0, f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4")
    import exit_factor_engine as efe34, step4_audit_trunc_and_report as s434
    c34 = pickle.load(open(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl", "rb"))
    states34 = efe34.precompute_trade_day_states(c34, min_score=90.0)
    risk7_3to4 = {}
    for e in c34["buy_entries"]:
        if e["skel"] and e["sc_v40"] >= 90.0:
            c6s = str(e["code"]).zfill(6)
            bd = str(e["buy_date"])
            cb34 = c34["code_bars_ext"][e["code"]]
            for k_idx, st_d in states34.get(e["idx"], {}).items():
                risk7_3to4[(bd, c6s, str(cb34["dts"][k_idx]))] = s434.risk7_score(st_d)

    # Index daily returns map
    csi_dts = sorted(sh300.keys())
    csi_ret = {}
    for i in range(1, len(csi_dts)):
        csi_ret[csi_dts[i]] = sh300[csi_dts[i]] / sh300[csi_dts[i - 1]] - 1.0
    sz_dts = sorted(sz_map.keys())
    sz_ret = {}
    for i in range(1, len(sz_dts)):
        sz_ret[sz_dts[i]] = sz_map[sz_dts[i]] / sz_map[sz_dts[i - 1]] - 1.0

    # Precompute trade metadata & per-day PIT states
    ctx = {
        "sh300": sh300, "sh_map": sh_map, "sz_map": sz_map,
        "csi_ret": csi_ret, "sz_ret": sz_ret,
        "all_dts": all_dts, "dt_to_idx": dt_to_idx,
        "ledgers": ledgers, "code_bars": code_bars, "dmap": dmap,
        "bars_5m": bars_5m, "lhb_map": lhb_map, "holders": holders_all,
        "mkt_env": mkt_env, "xq_by_c6": xq_by_c6, "seal_amt_map": seal_amt_map,
        "risk7_3to4": risk7_3to4,
    }
    ctx["trade_cache"] = _precompute_trade_caches(ctx)
    return ctx


def _get_double_dev_px_pit(c6: str, cb: dict, cp: int, sh_map: dict, sz_map: dict, ratio: float = 0.93, use_adj: bool = True) -> float:
    if cp < 1:
        return 99999.0
    imap = sh_map if c6.startswith("60") else sz_map
    sd = cb["dts"][cp - 1]
    ir = imap.get(sd)
    if not ir:
        return 99999.0
    disc = 1.0 - ratio
    bp_buf = 99999.0
    adj_cp = cb["adjf"][cp]
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = (cb["close"][p] * cb["adjf"][p] / adj_cp) if use_adj else cb["close"][p]
        if bi and bc > 0:
            bp_buf = min(bp_buf, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = (cb["close"][p] * cb["adjf"][p] / adj_cp) if use_adj else cb["close"][p]
        if bi and bc > 0:
            bp_buf = min(bp_buf, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return float(bp_buf)


def _precompute_trade_caches(ctx: dict) -> dict:
    """Precompute PIT per-day features for every holding day k = pos+1 .. min(n-1, pos+14) of every trade."""
    code_bars = ctx["code_bars"]
    lhb_map = ctx["lhb_map"]
    holders = ctx["holders"]
    mkt_env = ctx["mkt_env"]
    csi_ret = ctx["csi_ret"]
    sz_ret = ctx["sz_ret"]
    xq_by_c6 = ctx["xq_by_c6"]
    seal_amt_map = ctx["seal_amt_map"]
    dmap = ctx["dmap"]
    trade_cache = {}

    for sk, df in ctx["ledgers"].items():
        tlist = []
        for tidx, r in enumerate(df.itertuples(index=False)):
            c6 = r.c6
            cb = code_bars[c6]
            pos = cb["dt_pos"][r.buy_date]
            n = len(cb["dts"])
            b_o, b_h, b_l, b_c, b_pc = cb["open"][pos], cb["high"][pos], cb["low"][pos], cb["close"][pos], cb["pre_c"][pos]
            b_clv = float((b_c - b_l) / (b_h - b_l)) if b_h > b_l else 0.5
            b_up_sh = float((b_h - b_c) / (b_h - b_l)) if b_h > b_l else 0.0
            b_low_pct = float(b_l / b_pc - 1.0) if b_pc > 0 else 0.0

            # M1 exempt on 1to2 d3
            m1_d3 = False
            if sk == "1to2" and int(r.sealed_2b) == 1 and pos + 1 < n:
                d3_dt = cb["dts"][pos + 1]
                d1_dt = cb["dts"][max(0, pos - 1)]
                op3 = cb["open"][pos + 1] / cb["close"][pos] - 1.0 if cb["close"][pos] > 0 else 0.0
                # Wait: check exact adjf op3
                op3 = (cb["open"][pos + 1] / cb["pre_c"][pos + 1] - 1.0) if cb["pre_c"][pos + 1] > 0 else 0.0
                arr_xq = xq_by_c6.get(c6)
                xq_d3 = 0
                if arr_xq is not None and len(arr_xq) > 0:
                    lo = np.searchsorted(arr_xq, f"{d1_dt} 00:00:00", side="left")
                    hi = np.searchsorted(arr_xq, f"{d3_dt} 09:25:00", side="left")
                    xq_d3 = int(hi - lo)
                db2 = dmap.get((c6, r.buy_date))
                sa2 = seal_amt_map.get((r.buy_date, c6), None)
                sr2 = (sa2 / float(db2.amount)) if (sa2 is not None and db2 is not None and db2.amount > 0) else np.nan
                if (-0.065 <= op3 <= 0.025) and (xq_d3 < 4) and (np.isnan(sr2) or sr2 < 0.25):
                    m1_d3 = True

            # Signal start date for LHB window (pos-1 for 20cm/high/etc., pos for 1to2/2to3/3to4)
            sig_pos = max(0, pos - 1)
            k_states = {}
            latest_lhb = None
            max_lh_cnt = 0
            # Seed latest LHB from sig_pos (D0) if pos == buy_date (note: LHB on buy_date-1 is known at buy_date+1, AND at buy_date too)
            for k in range(pos + 1, min(n, pos + 15)):
                dt_k = cb["dts"][k]
                dt_p = cb["dts"][k - 1]
                # Scan any LHB up to dt_p (k-1 evening, known before k 09:25)
                for m_i in range(sig_pos if k == pos + 1 else k - 1, k):
                    lhb_m = lhb_map.get((c6, cb["dts"][m_i]))
                    if lhb_m is not None:
                        latest_lhb = lhb_m
                        max_lh_cnt = max(max_lh_cnt, lhb_m["lh_cnt"])

                env_k = mkt_env.get(dt_k, {})
                env_p = mkt_env.get(dt_p, {})
                lock10 = _get_lock10_pit(holders, c6, dt_p)
                mcap_p = float(cb["mcap"][k - 1])
                real_fmcap_p = mcap_p * max(0.05, 1.0 - lock10 / 100.0)
                turn_p = float(cb["turn"][k - 1]) * 100.0 if cb["turn"][k - 1] < 1.0 else float(cb["turn"][k - 1])
                # Note: check turn scale in a_daily! Let's handle dynamically below via actual check
                p_o, p_h, p_l, p_c, p_pc = cb["open"][k - 1], cb["high"][k - 1], cb["low"][k - 1], cb["close"][k - 1], cb["pre_c"][k - 1]
                p_clv = float((p_c - p_l) / (p_h - p_l)) if p_h > p_l else 0.5
                p_up_sh = float((p_h - p_c) / (p_h - p_l)) if p_h > p_l else 0.0
                p_dip5_or_dt = bool(cb["is_dt"][k - 1] or (p_pc > 0 and p_l / p_pc - 1.0 <= -0.05))
                ac_p = cb["ac"][k - 1]
                ma5_p = cb["ma5_ac"][k - 1]
                ma10_p = cb["ma10_ac"][k - 1]
                ma20_p = cb["ma20_ac"][k - 1]
                max20_p = cb["max20_ac"][k - 1]
                max60_p = cb["max60_ac"][k - 1]
                min60_p = cb["min60_ac"][k - 1]

                k_states[k] = {
                    "dt_k": dt_k,
                    "dt_p": dt_p,
                    "off": k - pos,
                    "o_pct": float(cb["open"][k] / cb["pre_c"][k] - 1.0) if cb["pre_c"][k] > 0 else 0.0,
                    "prev_zt": bool(cb["is_zt"][k - 1]),
                    "prev_dt": bool(cb["is_dt"][k - 1]),
                    # Market breadth
                    "prev_mkt_dt_10": int(env_p.get("mkt_dt_10", 0)),
                    "prev_mkt_dt_all": int(env_p.get("mkt_dt_all", 0)),
                    "prev_mkt_dt_ma5": float(env_p.get("mkt_dt_ma5", 5.0)),
                    "mkt_0925_zt": int(env_k.get("mkt_0925_zt", 10)),
                    # Bias / Rubber band (strictly <= k-1)
                    "prev_bias5": float(ac_p / ma5_p - 1.0) if ma5_p > 0 else 0.0,
                    "prev_bias10": float(ac_p / ma10_p - 1.0) if ma10_p > 0 else 0.0,
                    "prev_bias20": float(ac_p / ma20_p - 1.0) if ma20_p > 0 else 0.0,
                    "prev_dd20": float(ac_p / max20_p) if max20_p > 0 else 1.0,
                    "prev_pos60": float((ac_p - min60_p) / (max60_p - min60_p)) if max60_p > min60_p else 0.5,
                    "prev_ret10": float(cb["ret10"][k - 1]),
                    # Candle quality (buy day & prev day)
                    "buy_clv": b_clv,
                    "buy_c_gt_o": bool(b_c > b_o),
                    "buy_zt": bool(cb["is_zt"][pos]),
                    "buy_upper_shad": b_up_sh,
                    "buy_low_pct": b_low_pct,
                    "prev_clv": p_clv,
                    "prev_c_gt_o": bool(p_c > p_o),
                    "prev_upper_shad": p_up_sh,
                    "prev_dip5_or_dt": p_dip5_or_dt,
                    "prev_yang_streak": int(cb["yang_streak"][k - 1]),
                    # Volume / Lockup / Real turnover / Free mcap
                    "prev_vr": float(cb["vr"][k - 1]),
                    "lock10": lock10,
                    "prev_real_fmcap": real_fmcap_p,
                    "prev_real_turn": float(cb["turn"][k - 1]) / max(0.05, 1.0 - lock10 / 100.0),
                    # LHB strictly <= k-1
                    "lhb_lh_ratio": latest_lhb["lh_ratio"] if latest_lhb else 0.0,
                    "lhb_lh_cnt": max_lh_cnt,
                    "lhb_inst_net": latest_lhb["inst_net"] if latest_lhb else 0.0,
                    "lhb_tot_net": latest_lhb["tot_net"] if latest_lhb else 0.0,
                    "has_lhb": bool(latest_lhb is not None),
                    # Index returns strictly <= k-1
                    "prev_csi_ret": float(csi_ret.get(dt_p, 0.0)),
                    "prev_sz_ret": float(sz_ret.get(dt_p, 0.0)),
                }

            tlist.append({
                "tidx": tidx,
                "c6": c6,
                "name": str(r.name),
                "buy_date": r.buy_date,
                "buy_hhmm": int(r.buy_hhmm),
                "buy_price": float(cb["ao"][pos]) if sk == "20cm" else float(r.buy_price),
                "base_exit_date": r.exit_date,
                "base_exit_hhmm": int(r.exit_hhmm),
                "base_exit_price": float(r.exit_price),
                "base_net_ret": float(r.net_ret),
                "pos": pos,
                "m1_d3": m1_d3,
                "sealed_2b": int(r.sealed_2b) if sk == "1to2" else 0,
                "sealed_3b": bool(r.sealed_3b) if sk == "2to3" else False,
                "d1_branch": str(r.d1_branch) if sk == "20cm" else "",
                "risk_hit": int(r.risk_hit) if sk == "20cm" else 0,
                "open_pct_20": float(cb["ao"][pos] / cb["ac"][pos - 1] - 1.0) if (sk == "20cm" and pos > 0 and cb["ac"][pos - 1] > 0) else 0.0,
                "k_states": k_states,
            })
        trade_cache[sk] = tlist
    return trade_cache


def _defer_dt_sell(cb: dict, k_start: int, pos: int, buy_px: float, fee: float, is_adj_px: bool = False) -> tuple[str, int, float, float]:
    n = len(cb["dts"])
    k = min(k_start, n - 1)
    while k < n - 1 and bool(cb["is_yizi_dt"][k]):
        k += 1
    dt_s = cb["dts"][k]
    px = float(cb["ao"][k] if is_adj_px else cb["open"][k])
    if is_adj_px:
        nr = (px / buy_px) * (1.0 - fee) - 1.0
    else:
        adj_r = float(cb["adjf"][k]) / float(cb["adjf"][pos])
        nr = (px / buy_px) * adj_r * (1.0 - fee) - 1.0
    return dt_s, 925, round(px, 4 if is_adj_px else 2), float(nr)


def _check_5m_intraday(arr: np.ndarray, pck: float, ztk: float, dtk: float, act: dict, base_1345_drop: float | None, allow_1030_vwap: bool, allow_1430_rush: bool, exempt_1030: bool, eod_weak_thr: float | None, is_3to4: bool = False) -> tuple[bool, int, float, str]:
    """Scan 5m bars on holding day k strictly chronologically without lookahead."""
    if arr is None or len(arr) == 0:
        return False, 0, 0.0, ""
    peak = float(arr[0, 1])  # open price
    cum_v = 0.0
    cum_a = 0.0
    sealed_1030 = False
    seen_1030 = False

    g_peak = act.get("g_peak_drop")  # (peak_pct, drop_pct) for 09:35~10:30
    g_sl = act.get("g_panic_sl")     # -0.03 / -0.05 / -0.07 up to 10:30
    g_pry_bounce = False

    drop_1345 = act.get("tight_1345_thr", base_1345_drop)
    if act.get("relax_1345_delta") and drop_1345 is not None:
        drop_1345 = max(0.01, float(drop_1345) - float(act["relax_1345_delta"]))

    for bi in range(len(arr)):
        hh = int(arr[bi, 0])
        bo, bh, bl, bc, bv, ba = float(arr[bi, 1]), float(arr[bi, 2]), float(arr[bi, 3]), float(arr[bi, 4]), float(arr[bi, 5]), float(arr[bi, 6])
        cum_v += bv
        cum_a += ba
        vwap = (cum_a / cum_v) if cum_v > 0 else bc

        # Baseline 10:30 check runs even if 10:30 bar sits at limit-down (matching upgrade_1to2_pit.py)
        if hh == 1030 and not seen_1030:
            seen_1030 = True
            if bc >= ztk - 0.01:
                sealed_1030 = True
            else:
                g08_ok = bool(act.get("g_bounce_exempt") and g_pry_bounce and bc >= vwap)
                if not g08_ok:
                    want_1030 = bool(act.get("vwap_1030")) or allow_1030_vwap
                    if want_1030 and (not exempt_1030) and bc < vwap:
                        px = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                        ehh = int(arr[bi + 1, 0]) if bi + 1 < len(arr) else 1030
                        if allow_1030_vwap and act.get("vwap_1030") is None:
                            return True, ehh, px, "vwap_1030"
                        if px > dtk + 0.005:
                            return True, ehh, px, "vwap_1030"

        if bh <= dtk + 0.005:
            continue

        # Pre-market / intraday limit TP
        tp_px = act.get("tp_px")
        if tp_px is not None and bh >= tp_px:
            px = min(ztk, max(bo, tp_px))
            if px > dtk + 0.005:
                return True, hh, px, "tp_limit_5m"

        # G05..G07 morning panic SL <= 10:30
        if g_sl is not None and hh <= 1030 and pck > 0 and bl <= pck * (1.0 + g_sl) and bc < ztk - 0.01:
            px = min(bo, pck * (1.0 + g_sl))
            if px > dtk + 0.005:
                return True, hh, px, "g_panic_sl"

        # G01..G04 morning rubber-band surge & fade <= 10:30
        if g_peak is not None and hh <= 1030 and pck > 0:
            pk_r, dr_r = g_peak
            if peak >= pck * (1.0 + pk_r) and bl <= pck * (1.0 + dr_r) and bc < ztk - 0.01:
                px = min(bo, pck * (1.0 + dr_r))
                if px > dtk + 0.005:
                    return True, hh, px, "g_morning_fade"

        # G08 check if dipped <= -4% by 10:30
        if hh <= 1030 and pck > 0 and bl <= pck * 0.96:
            g_pry_bounce = True

        # 14:30 unseal rush (for 1to2 strictly when 10:30 bar was sealed at limit-up)
        if allow_1430_rush and sealed_1030 and hh >= 1430 and bc < ztk - 0.01 and bi + 1 < len(arr):
            px = float(arr[bi + 1, 1])
            if px > dtk + 0.005:
                return True, int(arr[bi + 1, 0]), px, "1430_rush"

        # 13:45 intraday pullback guard
        if drop_1345 is not None and hh >= 1345 and pck > 0:
            pk_req = float(act.get("tight_1345_peak", 0.085))
            if peak >= pck * (1.0 + pk_req) and bl <= pck * (1.0 + drop_1345) and bc < ztk - 0.01:
                px = min(bo, pck * (1.0 + drop_1345))
                if (is_3to4 and act.get("tight_1345_thr") is None) or px > dtk + 0.005:
                    return True, hh, px, "guard_1345"

        # 14:55 EOD weak cut check
        if eod_weak_thr is not None and hh == 1455 and pck > 0 and bc < ztk - 0.01:
            if bc < pck * (1.0 + eod_weak_thr):
                px = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else bc
                if px > dtk + 0.005:
                    return True, 1500, px, "eod_1455_weak"

        if bh > peak:
            peak = bh

    return False, 0, 0.0, ""


def simulate_trade(sk: str, tr: dict, ctx: dict, rule_fn=None) -> dict:
    """Unified strictly-PIT trade exit simulator covering all 5 strategies."""
    c6 = tr["c6"]
    cb = ctx["code_bars"][c6]
    pos = tr["pos"]
    buy_px = tr["buy_price"]
    n = len(cb["dts"])
    bars_5m = ctx["bars_5m"]
    sh_map, sz_map = ctx["sh_map"], ctx["sz_map"]
    fee = 0.0030 if sk == "20cm" else 0.0020

    def _finish(k_idx: int, hh: int, px: float, tag: str, is_adj: bool = False) -> dict:
        if not is_adj and hh >= 1455 and bool(cb["is_dt_exact"][k_idx]):
            ed, eh, ep, nr = _defer_dt_sell(cb, k_idx + 1, pos, buy_px, fee, is_adj_px=False)
            return {"exit_date": ed, "exit_hhmm": eh, "exit_price": ep, "net_ret": nr, "tag": f"{tag}_dt_defer"}
        if is_adj and hh >= 1455 and (bool(cb["is_dt"][k_idx]) or bool(cb["is_yizi_dt"][k_idx])):
            ed, eh, ep, nr = _defer_dt_sell(cb, k_idx + 1, pos, buy_px, fee, is_adj_px=True)
            return {"exit_date": ed, "exit_hhmm": eh, "exit_price": ep, "net_ret": nr, "tag": f"{tag}_dt_defer"}
        if is_adj:
            nr = (px / buy_px) * (1.0 - fee) - 1.0
            return {"exit_date": cb["dts"][k_idx], "exit_hhmm": hh, "exit_price": px, "net_ret": float(nr), "tag": tag}
        adj_r = float(cb["adjf"][k_idx]) / float(cb["adjf"][pos])
        nr = (px / buy_px) * adj_r * (1.0 - fee) - 1.0
        if sk == "1to2":
            nr = round(nr, 4)
        return {"exit_date": cb["dts"][k_idx], "exit_hhmm": hh, "exit_price": round(px, 2), "net_ret": float(nr), "tag": tag}

    # --- 20cm V1.1 S82 Branch ---
    if sk == "20cm":
        k1 = pos + 1
        if k1 >= n:
            return {"exit_date": tr["base_exit_date"], "exit_hhmm": tr["base_exit_hhmm"], "exit_price": tr["base_exit_price"], "net_ret": tr["base_net_ret"], "tag": "end"}

        # Helper to simulate TP with +0.30% penetration on 20cm
        def _try_20_tp(k_i: int, tp_r: float, ref_ac: float):
            ao, ah, zta = float(cb["ao"][k_i]), float(cb["ah"][k_i]), float(cb["zt_px"][k_i] * cb["adjf"][k_i])
            if cb["is_yizi_dt"][k_i]:
                return False, 0.0, 0
            open_dt = bool(cb["open"][k_i] <= cb["dt_px"][k_i] + 0.011)
            # 10cm/20cm tp_buf=0.003 check
            tp_px = ref_ac * (1.0 + tp_r)
            if ao >= tp_px and not open_dt:
                return True, ao, 1030
            need_ah = min(tp_px * 1.003, zta - 1e-4)
            if ah >= need_ah:
                return True, tp_px, 1030
            return False, 0.0, 0

        br = tr["d1_branch"]
        st1 = tr["k_states"].get(k1, {})
        act1 = rule_fn(sk, tr, st1) if rule_fn else {}

        # Check 09:25 cut on D2 (or defer if yizi_dt)
        if act1.get("cut_0925"):
            k_c = k1
            while k_c < n - 1 and bool(cb["is_yizi_dt"][k_c]):
                k_c += 1
            if float(cb["open"][k_c]) < float(cb["zt_px"][k_c]) - 0.011 and float(cb["open"][k_c]) > float(cb["dt_px"][k_c]) + 0.011:
                return _finish(k_c, 925, float(cb["ao"][k_c]), "f_0925_cut", is_adj=True)

        # Resolve risk_hit override
        risk_hit = bool(tr["risk_hit"])
        if act1.get("strip_20cm_d3") or act1.get("strip_imm"):
            risk_hit = True
        elif act1.get("exempt_20cm_risk"):
            risk_hit = False

        # B1: D1 ZT continuation
        if br == "B1_D1_ZT":
            imm_used = False
            k = k1
            while k < min(n, pos + 10):
                if bool(cb["is_yizi_dt"][k]):
                    k += 1
                    continue
                st_k = tr["k_states"].get(k, {})
                act_k = rule_fn(sk, tr, st_k) if rule_fn else {}
                if k > k1 and act_k.get("cut_0925") and float(cb["open"][k]) < float(cb["zt_px"][k]) - 0.011 and float(cb["open"][k]) > float(cb["dt_px"][k]) + 0.011:
                    return _finish(k, 925, float(cb["ao"][k]), "f_0925_cut", is_adj=True)
                tp_r = act_k.get("tp_rel_buy")
                if tp_r is not None:
                    hit, px_h, hh_h = _try_20_tp(k, tp_r, buy_px)
                    if hit:
                        return _finish(k, hh_h, px_h, "f_tp_limit", is_adj=True)
                if act_k.get("force_eod_off") and (k - pos) >= int(act_k["force_eod_off"]) and (not bool(cb["is_zt"][k])):
                    return _finish(k, 1500, float(cb["ac"][k]), "f_time_stop", is_adj=True)
                if bool(cb["is_zt"][k]):
                    k += 1
                    continue
                if act_k.get("extra_imm") and (not imm_used) and (not act_k.get("strip_imm")) and float(cb["close"][k]) > float(cb["open"][k]):
                    imm_used = True
                    k += 1
                    continue
                return _finish(k, 1500, float(cb["ac"][k]), "B1_zt_break", is_adj=True)
            return _finish(min(n - 1, pos + 9), 1500, float(cb["ac"][min(n - 1, pos + 9)]), "B1_end", is_adj=True)

        # Non-ZT D1 branches (B2, B3, B4)
        if not bool(cb["is_yizi_dt"][k1]):
            # Factor pre-market limit TP relative to buy_px
            if act1.get("tp_rel_buy") is not None:
                hit, px_h, hh_h = _try_20_tp(k1, float(act1["tp_rel_buy"]), buy_px)
                if hit:
                    return _finish(k1, hh_h, px_h, "f_tp_limit_d2", is_adj=True)
            # Factor TP relative to prev_ac (pck)
            if act1.get("tp_rel_prev") is not None:
                hit, px_h, hh_h = _try_20_tp(k1, float(act1["tp_rel_prev"]), float(cb["ac"][pos]))
                if hit:
                    return _finish(k1, hh_h, px_h, "f_tp_prev_d2", is_adj=True)

        # Baseline branch TP & hold logic
        d1_ac = float(cb["ac"][pos])
        if br == "B4_D1_DeepYin":
            if act1.get("extend_20cm_d3") and (not risk_hit) and k1 + 1 < n and (not bool(cb["is_dt"][k1])) and (not bool(cb["is_yizi_dt"][k1])):
                k2 = k1 + 1
                if not bool(cb["is_yizi_dt"][k2]):
                    st2 = tr["k_states"].get(k2, {})
                    act2 = rule_fn(sk, tr, st2)
                    if act2.get("cut_0925") and float(cb["open"][k2]) > float(cb["dt_px"][k2]) + 0.011:
                        return _finish(k2, 925, float(cb["ao"][k2]), "f_d3_0925_cut", is_adj=True)
                return _finish(k2, 1500, float(cb["ac"][k2]), "f_b4_ext_d3", is_adj=True)
            return _finish(k1, 1500, float(cb["ac"][k1]), "B4_d2_close", is_adj=True)

        elif br == "B2_D1_StrongYang":
            tp2 = 0.12 + float(act1.get("tp_boost_20cm", 0.0))
            if risk_hit:
                tp2 = min(tp2, 0.07)
            if act1.get("tight_20cm_tp_cap") is not None:
                tp2 = min(tp2, float(act1["tight_20cm_tp_cap"]))
            hit, px_h, hh_h = _try_20_tp(k1, tp2, d1_ac)
            if hit:
                return _finish(k1, hh_h, px_h, "B2_tp", is_adj=True)
            # Check D2 EOD weak cut override
            ew_thr = act1.get("eod_1455_weak_thr")
            if ew_thr is not None and float(cb["ac"][k1]) < d1_ac * (1.0 + ew_thr) and (not act1.get("exempt_weak")):
                return _finish(k1, 1500, float(cb["ac"][k1]), "f_b2_d2_weak", is_adj=True)
            if (not risk_hit) and k1 + 1 < n:
                if bool(cb["is_zt"][k1]):
                    k = k1 + 1
                    while k < min(n, pos + 10) and bool(cb["is_zt"][k]):
                        k += 1
                    return _finish(min(k, n - 1), 1500, float(cb["ac"][min(k, n - 1)]), "B2_d2zt_ride", is_adj=True)
                k2 = k1 + 1
                st2 = tr["k_states"].get(k2, {})
                act2 = rule_fn(sk, tr, st2) if rule_fn else {}
                if act2.get("cut_0925") and not bool(cb["is_yizi_dt"][k2]) and float(cb["open"][k2]) > float(cb["dt_px"][k2]) + 0.011:
                    return _finish(k2, 925, float(cb["ao"][k2]), "f_b2_d3_0925", is_adj=True)
                hit3, px3, hh3 = _try_20_tp(k2, tp2, float(cb["ac"][k1]))
                if hit3:
                    return _finish(k2, hh3, px3, "B2_d3_tp", is_adj=True)
                return _finish(k2, 1500, float(cb["ac"][k2]), "B2_d3_close", is_adj=True)
            return _finish(k1, 1500, float(cb["ac"][k1]), "B2_d2_close", is_adj=True)

        else:  # B3_D1_Mild
            tp3 = max(0.06, min(0.15, abs(tr["open_pct_20"]) * 1.5)) + float(act1.get("tp_boost_20cm", 0.0))
            if risk_hit:
                tp3 = min(tp3, 0.07)
            if act1.get("tight_20cm_tp_cap") is not None:
                tp3 = min(tp3, float(act1["tight_20cm_tp_cap"]))
            hit, px_h, hh_h = _try_20_tp(k1, tp3, d1_ac)
            if hit:
                return _finish(k1, hh_h, px_h, "B3_tp", is_adj=True)
            if act1.get("extend_20cm_d3") and (not risk_hit) and k1 + 1 < n and (not bool(cb["is_dt"][k1])) and (not bool(cb["is_yizi_dt"][k1])) and (not act1.get("force_eod_off")):
                k2 = k1 + 1
                st2 = tr["k_states"].get(k2, {})
                act2 = rule_fn(sk, tr, st2) if rule_fn else {}
                if act2.get("cut_0925") and not bool(cb["is_yizi_dt"][k2]) and float(cb["open"][k2]) > float(cb["dt_px"][k2]) + 0.011:
                    return _finish(k2, 925, float(cb["ao"][k2]), "f_b3_d3_0925", is_adj=True)
                hit3, px3, hh3 = _try_20_tp(k2, tp3, float(cb["ac"][k1]))
                if hit3:
                    return _finish(k2, hh3, px3, "f_b3_d3_tp", is_adj=True)
                return _finish(k2, 1500, float(cb["ac"][k2]), "f_b3_ext_d3", is_adj=True)
            return _finish(k1, 1500, float(cb["ac"][k1]), "B3_d2_close", is_adj=True)

    # --- 10cm Unified Holding Loop (1to2, 3to4, high, 2to3) ---
    max_hold = 12 if sk == "1to2" else (18 if sk in ("3to4", "2to3") else 10)

    def _run_10cm_ride(start_p: int, init_boards: int, check_2to3_hiopen: bool = False):
        k = start_p + 1
        imm_used = False
        boards = init_boards
        while k < min(n, pos + max_hold + 1):
            if bool(cb["is_yizi_dt"][k]):
                k += 1
                continue
            dt_s = cb["dts"][k]
            ok, hk, lk, ck = float(cb["open"][k]), float(cb["high"][k]), float(cb["low"][k]), float(cb["close"][k])
            pck, ztk, dtk = float(cb["pre_c"][k]), float(cb["zt_px"][k]), float(cb["dt_px"][k])

            if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                return _finish(k, 925, ok, "yizi_dt_open")

            st = tr["k_states"].get(k, {})
            act = rule_fn(sk, tr, st) if rule_fn else {}

            # 1. Policy 09:25 cut (strictly non-ZT open and non-DT open)
            if act.get("cut_0925") and ok < ztk - 0.005 and ok > dtk + 0.005:
                return _finish(k, 925, ok, "f_0925_cut")

            # 2. Baseline 2to3 D4 > +9.2% high-open TP
            if check_2to3_hiopen and k == pos + 1 and pck > 0 and (ok / pck - 1.0 > 0.092) and ok < ztk - 0.005 and ok > dtk + 0.005:
                return _finish(k, 925, ok, "2to3_hi_open")

            # 3. Baseline high V5.1 93% double severe abnormal volatility
            if sk == "high":
                pl_dev = _get_double_dev_px_pit(c6, cb, k, sh_map, sz_map, 0.93, use_adj=False)
                if ok >= pl_dev and ok > dtk + 0.005:
                    return _finish(k, 925, ok, "high_dev93_open")
            else:
                pl_dev = 99999.0

            # 4. Policy pre-market limit TP
            tp_px = None
            if act.get("tp_rel_buy") is not None:
                tp_px = round(buy_px * (1.0 + float(act["tp_rel_buy"])) * (float(cb["adjf"][pos]) / float(cb["adjf"][k])), 2)
            elif act.get("tp_rel_prev") is not None and pck > 0:
                tp_px = round(pck * (1.0 + float(act["tp_rel_prev"])), 2)
            if tp_px is not None and ok >= tp_px and ok > dtk + 0.005:
                return _finish(k, 925, ok, "f_tp_open")

            # 5. Baseline intraday 5m settings per strategy
            base_1345 = None
            if sk == "3to4":
                r7 = ctx["risk7_3to4"].get((tr["buy_date"], c6, dt_s), 0)
                base_1345 = 0.070 if r7 >= 1 else 0.050
            elif sk == "2to3":
                base_1345 = 0.065

            allow_1030_vwap = (sk == "1to2")
            allow_1430_rush = (sk == "1to2")
            exempt_1030 = bool((sk == "1to2" and k == pos + 1 and tr["m1_d3"]) or act.get("exempt_1030"))
            eod_weak_thr = None if act.get("exempt_weak") else act.get("eod_1455_weak_thr")

            arr = bars_5m.get((c6, dt_s))
            if sk == "high" and pl_dev < 99990.0:
                # high checks 93% dev on 5m bars first
                if arr is not None and len(arr) > 0:
                    for row5 in arr:
                        if float(row5[2]) >= pl_dev:
                            return _finish(k, int(row5[0]), float(max(row5[1], pl_dev)), "high_dev93_5m")
                elif hk >= pl_dev:
                    return _finish(k, 1030, float(pl_dev), "high_dev93_day")

            act_5m = dict(act)
            if tp_px is not None:
                act_5m["tp_px"] = tp_px

            hit_5m, ehh_5m, epx_5m, tag_5m = _check_5m_intraday(
                arr, pck, ztk, dtk, act_5m, base_1345, allow_1030_vwap, allow_1430_rush, exempt_1030, eod_weak_thr, is_3to4=(sk == "3to4")
            )
            if hit_5m:
                return _finish(k, ehh_5m, epx_5m, tag_5m)

            # Fallback EOD weak cut if no 5m bar existed
            if arr is None and eod_weak_thr is not None and not bool(cb["is_zt"][k]) and pck > 0 and ck < pck * (1.0 + eod_weak_thr):
                return _finish(k, 1500, ck, "eod_weak_day")

            if bool(cb["is_zt"][k]):
                boards += 1
                k += 1
                continue

            # Policy time-stop at off >= force_eod_off
            if act.get("force_eod_off") and (k - pos) >= int(act["force_eod_off"]):
                return _finish(k, 1500, ck, "f_time_stop")

            # Breaking-day immunity per strategy
            if sk == "1to2":
                base_imm = (boards >= 3) and (ck >= pck * 1.02)
            elif sk in ("3to4", "2to3"):
                base_imm = (ck > ok) and (ck >= pck)
            elif sk == "high":
                base_imm = (ck > ok)
            else:
                base_imm = False

            if act.get("strip_imm"):
                imm_ok = False
            elif act.get("extra_imm") and (ck > ok):
                imm_ok = True
            else:
                imm_ok = base_imm

            if (not imm_used) and imm_ok and k + 1 < n:
                imm_used = True
                k += 1
                continue

            return _finish(k, 1500, ck, "eod_break_close")

        ke = min(n - 1, pos + max_hold)
        return _finish(ke, 1500, float(cb["close"][ke]), "max_hold_exit")

    # Initial D_buy sealed vs unsealed branching per 10cm strategy
    buy_sealed = bool(cb["is_zt"][pos])
    if sk == "1to2":
        if tr["sealed_2b"] == 1:
            return _run_10cm_ride(pos, 2, False)
        # Unsealed D2 -> D3 decision
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        st = tr["k_states"].get(k, {})
        act = rule_fn(sk, tr, st) if rule_fn else {}
        d1_c = float(cb["close"][max(0, pos - 1)])
        o3, c2 = float(cb["open"][k]), float(cb["close"][pos])
        base_keep = (c2 >= d1_c) and (o3 >= round(c2 * 1.005, 2)) and (k == pos + 1)
        if k > pos + 1:
            return _finish(k, 925, o3, "fail_yizi_dt_open")
        keep = (base_keep and (not act.get("strip_d5_keep")) and (not act.get("cut_0925"))) or (bool(act.get("exempt_d5")) and o3 > float(cb["dt_px"][k]) + 0.005)
        if not keep:
            return _finish(k, 925, o3, "fail_open_cut")
        # Check D3 intraday rules (TP / 1030 / G / weak)
        pck, ztk, dtk = float(cb["pre_c"][k]), float(cb["zt_px"][k]), float(cb["dt_px"][k])
        tp_px = round(buy_px * (1.0 + float(act["tp_rel_buy"])) * (float(cb["adjf"][pos]) / float(cb["adjf"][k])), 2) if act.get("tp_rel_buy") is not None else (round(pck * (1.0 + float(act["tp_rel_prev"])), 2) if act.get("tp_rel_prev") is not None else None)
        if tp_px is not None and o3 >= tp_px and o3 > dtk + 0.005:
            return _finish(k, 925, o3, "f_d3_tp_open")
        act_5m = dict(act)
        if tp_px is not None:
            act_5m["tp_px"] = tp_px
        ew_thr = None if act.get("exempt_weak") else act.get("eod_1455_weak_thr")
        hit_5m, ehh_5m, epx_5m, tag_5m = _check_5m_intraday(bars_5m.get((c6, cb["dts"][k])), pck, ztk, dtk, act_5m, None, bool(act.get("vwap_1030")), False, bool(act.get("exempt_1030")), ew_thr)
        if hit_5m:
            return _finish(k, ehh_5m, epx_5m, tag_5m)
        if bool(cb["is_zt"][k]):
            return _run_10cm_ride(k, 3, False)
        return _finish(k, 1500, float(cb["close"][k]), "nshape_d3_close")

    elif sk == "3to4":
        if buy_sealed:
            return _run_10cm_ride(pos, 4, False)
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        if k > pos + 1:
            return _finish(k, 925, float(cb["open"][k]), "d5_yizi_dt_open")
        st = tr["k_states"].get(k, {})
        act = rule_fn(sk, tr, st) if rule_fn else {}
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        base_keep = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
        keep = (base_keep and (not act.get("strip_d5_keep")) and (not act.get("cut_0925"))) or (bool(act.get("exempt_d5")) and o5 > float(cb["dt_px"][k]) + 0.005)
        if not keep:
            return _finish(k, 925, o5, "d5_open_cut")
        ztk, dtk = float(cb["zt_px"][k]), float(cb["dt_px"][k])
        tp_px = round(buy_px * (1.0 + float(act["tp_rel_buy"])) * (float(cb["adjf"][pos]) / float(cb["adjf"][k])), 2) if act.get("tp_rel_buy") is not None else (round(p5 * (1.0 + float(act["tp_rel_prev"])), 2) if act.get("tp_rel_prev") is not None else None)
        if tp_px is not None and o5 >= tp_px and o5 > dtk + 0.005:
            return _finish(k, 925, o5, "f_d5_tp_open")
        act_5m = dict(act)
        if tp_px is not None:
            act_5m["tp_px"] = tp_px
        ew_thr = None if act.get("exempt_weak") else act.get("eod_1455_weak_thr")
        hit_5m, ehh_5m, epx_5m, tag_5m = _check_5m_intraday(bars_5m.get((c6, cb["dts"][k])), p5, ztk, dtk, act_5m, None, bool(act.get("vwap_1030")), False, bool(act.get("exempt_1030")), ew_thr)
        if hit_5m:
            return _finish(k, ehh_5m, epx_5m, tag_5m)
        if bool(cb["is_zt"][k]):
            return _run_10cm_ride(k, 4, False)
        return _finish(k, 1500, c5, "d5_eod")

    elif sk == "2to3":
        if tr["sealed_3b"]:
            return _run_10cm_ride(pos, 3, check_2to3_hiopen=True)
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        if k > pos + 1:
            return _finish(k, 925, float(cb["open"][k]), "d4_yizi_dt_open")
        st = tr["k_states"].get(k, {})
        act = rule_fn(sk, tr, st) if rule_fn else {}
        o4, p4, ztk, dtk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["zt_px"][k]), float(cb["dt_px"][k])
        if act.get("cut_0925") and o4 < ztk - 0.005 and o4 > dtk + 0.005:
            return _finish(k, 925, o4, "f_d4_0925_cut")
        tp_px = round(buy_px * (1.0 + float(act["tp_rel_buy"])) * (float(cb["adjf"][pos]) / float(cb["adjf"][k])), 2) if act.get("tp_rel_buy") is not None else (round(p4 * (1.0 + float(act["tp_rel_prev"])), 2) if act.get("tp_rel_prev") is not None else None)
        if tp_px is not None and o4 >= tp_px and o4 > dtk + 0.005:
            return _finish(k, 925, o4, "f_d4_tp_open")
        act_5m = dict(act)
        if tp_px is not None:
            act_5m["tp_px"] = tp_px
        ew_thr = None if act.get("exempt_weak") else act.get("eod_1455_weak_thr")
        hit_5m, ehh_5m, epx_5m, tag_5m = _check_5m_intraday(bars_5m.get((c6, cb["dts"][k])), p4, ztk, dtk, act_5m, None, bool(act.get("vwap_1030")), False, bool(act.get("exempt_1030")), ew_thr)
        if hit_5m:
            return _finish(k, ehh_5m, epx_5m, tag_5m)
        if bool(cb["is_zt"][k]):
            return _run_10cm_ride(k, 1, check_2to3_hiopen=False)
        if act.get("extra_imm") and float(cb["close"][k]) > o4 and (not act.get("strip_imm")) and k + 1 < n:
            return _run_10cm_ride(k, 1, check_2to3_hiopen=False)
        return _finish(k, 1500, float(cb["close"][k]), "d4_eod")

    elif sk == "high":
        if buy_sealed:
            return _run_10cm_ride(pos, 1, False)
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        if k > pos + 1:
            return _finish(k, 925, float(cb["open"][k]), "hd_yizi_dt_open")
        st = tr["k_states"].get(k, {})
        act = rule_fn(sk, tr, st) if rule_fn else {}
        ok, pck, ztk, dtk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["zt_px"][k]), float(cb["dt_px"][k])
        if act.get("cut_0925") and ok < ztk - 0.005 and ok > dtk + 0.005:
            return _finish(k, 925, ok, "f_hd_0925_cut")
        tp_px = round(buy_px * (1.0 + float(act["tp_rel_buy"])) * (float(cb["adjf"][pos]) / float(cb["adjf"][k])), 2) if act.get("tp_rel_buy") is not None else (round(pck * (1.0 + float(act["tp_rel_prev"])), 2) if act.get("tp_rel_prev") is not None else None)
        if tp_px is not None and ok >= tp_px and ok > dtk + 0.005:
            return _finish(k, 925, ok, "f_hd_tp_open")
        act_5m = dict(act)
        if tp_px is not None:
            act_5m["tp_px"] = tp_px
        ew_thr = None if act.get("exempt_weak") else act.get("eod_1455_weak_thr")
        hit_5m, ehh_5m, epx_5m, tag_5m = _check_5m_intraday(bars_5m.get((c6, cb["dts"][k])), pck, ztk, dtk, act_5m, None, bool(act.get("vwap_1030")), False, bool(act.get("exempt_1030")), ew_thr)
        if hit_5m:
            return _finish(k, ehh_5m, epx_5m, tag_5m)
        if bool(cb["is_zt"][k]):
            return _run_10cm_ride(k, 1, False)
        return _finish(k, 1500, float(cb["close"][k]), "hd_eod")

    raise ValueError(f"Unknown strategy {sk}")


def verify_baseline_parity(ctx: dict) -> dict:
    res = {}
    for sk in ("1to2", "3to4", "high", "2to3", "20cm"):
        mism = []
        max_ret_d = 0.0
        for tr in ctx["trade_cache"][sk]:
            sim = simulate_trade(sk, tr, ctx, rule_fn=None)
            rd = abs(sim["net_ret"] - tr["base_net_ret"])
            max_ret_d = max(max_ret_d, rd)
            if sim["exit_date"] != tr["base_exit_date"] or sim["exit_hhmm"] != tr["base_exit_hhmm"] or rd > 0.0025:
                mism.append({
                    "c6": tr["c6"], "buy_date": tr["buy_date"],
                    "base": (tr["base_exit_date"], tr["base_exit_hhmm"], round(tr["base_net_ret"], 4)),
                    "sim": (sim["exit_date"], sim["exit_hhmm"], round(sim["net_ret"], 4)),
                })
        res[sk] = {"n": len(ctx["trade_cache"][sk]), "mismatches": len(mism), "max_ret_diff": round(max_ret_d, 6), "sample": mism[:3]}
    return res
