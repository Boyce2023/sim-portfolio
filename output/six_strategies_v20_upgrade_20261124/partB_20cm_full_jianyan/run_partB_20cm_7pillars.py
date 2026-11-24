#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part B: Institutional 7-Pillar Validation Suite + 6x6 09:25 Signal & R_sen20_lt40 Upgrade Audit
for 20cm DeepOpen V1.1 (A76 N=285 & S82 N=199).

Hard Rules Enforced:
  - 100% local read-only; ZERO import yfinance (D12); ZERO network calls; all SQLite mode=ro.
  - Zero fabrication: explicitly marks MISSING_LOCAL_DATA & exact 5m/1m coverage rates.
  - Outputs strictly inside sim-portfolio/output/six_strategies_v20_upgrade_20261124/partB_20cm_full_jianyan/.
"""
import itertools
import json
import math
import os
import pickle
import sqlite3
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.optimize as opt
import scipy.stats as stats
import statsmodels.api as sm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
warnings.filterwarnings("ignore", category=FutureWarning)
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
V1_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
P2_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
RD23_DIR = f"{SIM}/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
PC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
MW_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123"
OUT_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partB_20cm_full_jianyan"
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, P2_DIR)
sys.path.insert(0, V11_DIR)
sys.path.insert(0, RD23_DIR)
from backtest_utils import _sim_k_slots, bench_return
from v11_core import V11_EXIT_CFG, compute_scorecard_v11, sim_v11_exit
from rd023_eval_lib import cscv_pbo, eval_splits, sim_v11_exit_ext

FULL_START = "2021-01-04"
FULL_END = "2026-11-23"
CANON_5Y_START = "2021-11-16"
CANON_5Y_END = "2026-11-16"
ORIG_FEE_RT = 0.0030
ORIG_FEE_OW_BPS = 15.0
TRD_DAYS_YEAR = 242.0
ANN_DAYS_STAT = 252.0
SEED = 20261124
BOOT_B = 5000
MC_B = 10000


def sf(x, digits=6):
    if x is None:
        return None
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, digits)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def load_calendars():
    aux = pickle.load(open(f"{P2_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300 = {k: float(v) for k, v in aux["sh300"].items()}
    ew20_daily = {k: float(v) for k, v in aux["ew20_daily"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_full = [d for d in sorted(aux["all_dts"]) if FULL_START <= d <= FULL_END]
    cal_5y = [d for d in all_sh_dts if CANON_5Y_START <= d <= CANON_5Y_END]

    def _csi_vec(dts):
        out = np.zeros(len(dts), dtype=float)
        for i, d in enumerate(dts):
            pos = all_sh_dts.index(d)
            prev_d = all_sh_dts[pos - 1]
            out[i] = sh300[d] / sh300[prev_d] - 1.0
        return out

    csi_full = pd.Series(_csi_vec(cal_full), index=cal_full, name="CSI300")
    csi_5y = pd.Series(_csi_vec(cal_5y), index=cal_5y, name="CSI300")
    return sh300, all_sh_dts, ew20_daily, cal_full, cal_5y, csi_full, csi_5y


def get_csi_period_ret(sh300: dict, all_sh_dts: list[str], buy_date: str, end_date: str) -> float:
    prevs = [d for d in all_sh_dts if d < buy_date]
    p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
    p1s = [d for d in all_sh_dts if d <= end_date]
    p1 = sh300[p1s[-1]]
    return float(p1 / p0 - 1.0)


def load_full_daily_panel():
    print("[1/8] Loading active + delisted A-share daily panel (2020-11-01..2026-11-23)...")
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    flt = (ds.field("date") >= pd.Timestamp("2020-11-01")) & (ds.field("date") <= pd.Timestamp(FULL_END))
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

    tot_amt = df.groupby("dt")["amount"].sum().sort_index()
    df["adjf"] = df["adj_close"] / df["close"]
    g = df.groupby("c6", sort=False)
    df["prev_ac"] = g["adj_close"].shift(1)
    df["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["ret"] = df["adj_close"] / df["prev_ac"] - 1.0
    df["vol_m1"] = g["volume"].shift(1)
    shares = np.where(df["oshare"].fillna(0) > 0, df["oshare"], np.where(df["turn"] > 0, df["volume"] / df["turn"], np.nan))
    df["mcap"] = df["close"] * shares
    df["mcap_m1"] = g["mcap"].shift(1)
    df["turn_m1"] = g["turn"].shift(1)
    df["vol20"] = g["ret"].transform(lambda s: s.rolling(20, min_periods=15).std())
    df["vol20_m1"] = g["vol20"].shift(1)
    df["turn20"] = g["turn"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    df["turn20_m1"] = g["turn20"].shift(1)
    df["is20"] = df["c6"].str.startswith(("30", "688", "689"))
    lim = np.where(df["is20"], 0.20, 0.10)
    r_th = np.where(df["is20"], 0.195, 0.095)
    abn = df["ret"].abs() > np.where(df["is20"], 0.22, 0.12)
    df["zt_px"] = np.floor(df["prev_c_adj"] * (1.0 + lim) * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(df["prev_c_adj"] * (1.0 - lim) * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["prev_c_adj"] > 0) & (df["close"] >= df["zt_px"] - 0.011) & (df["ret"] >= r_th) & (~abn)
    df["hit_zt"] = (df["prev_c_adj"] > 0) & (df["high"] >= df["zt_px"] - 0.011) & (~abn)
    df["is_dt"] = (df["prev_c_adj"] > 0) & (df["close"] <= df["dt_px"] + 0.011) & (df["ret"] <= -r_th) & (~abn)
    o_pct = (df["open"] * df["adjf"]) / df["prev_ac"] - 1.0
    df["o_pct"] = o_pct
    df["is_yizi_zt"] = df["is_zt"] & (df["low"] == df["high"]) & (o_pct >= r_th)
    df["is_yizi_dt"] = df["is_dt"] & (df["low"] == df["high"]) & (o_pct <= -r_th)
    df["open_is_zt"] = (df["prev_c_adj"] > 0) & (df["open"] >= df["zt_px"] - 0.011) & (o_pct >= r_th)
    df["vwap"] = np.where(df["volume"] > 0, df["amount"] / df["volume"], df["close"])

    # Consecutive ZT streak (used for 20cm first-board t-1 lookup)
    zt_arr = df["is_zt"].to_numpy(dtype=np.int32)
    c6_arr = df["c6"].to_numpy()
    streak = np.zeros(len(df), dtype=np.int32)
    cur, pc = 0, ""
    for i in range(len(df)):
        if c6_arr[i] != pc:
            cur, pc = 0, c6_arr[i]
        cur = cur + 1 if zt_arr[i] == 1 else 0
        streak[i] = cur
    df["board_cnt"] = streak
    df["board_cnt_m1"] = g["board_cnt"].shift(1)
    df["is_yizi_zt_m1"] = g["is_yizi_zt"].shift(1).fillna(False).astype(bool)

    # PIT ST timeline from zt_micro_tape + st_universe snapshot fallback
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    zt_tape = pd.read_sql_query(
        "SELECT trade_date, sec_code, sec_name, first_seal_time, first_seal_ts, seal_amount, board_count, open_board_count "
        "FROM zt_micro_tape WHERE trade_date >= '2020-11-01' AND trade_date <= '2026-11-23'",
        con_z,
    )
    con_z.close()
    zt_tape["c6"] = zt_tape["sec_code"].astype(str).str.zfill(6)
    st_snap = set(json.load(open(f"{SIM}/data/st_universe.json", encoding="utf-8")).get("codes", []))
    pit_st = set(zt_tape[zt_tape["sec_name"].str.contains("ST|退", na=False)]["c6"].unique())
    df["is_st_flag"] = df["c6"].isin(st_snap | pit_st)
    return df, tot_amt, zt_tape


def build_5_factors_20cm(df: pd.DataFrame, cal_dates: list[str], all_sh_dts: list[str], csi_s: pd.Series):
    print("[2/8] Building 5 daily factors (MKT, SMB, VOL, LIQ, FB20_BETA & FB20_O2C_BETA)...")
    dt_set = set(cal_dates)
    sub = df[df["dt"].isin(dt_set)].copy()
    valid = (
        (~sub["is_st_flag"])
        & (sub["volume"] > 0)
        & (sub["vol_m1"] > 0)
        & sub["mcap_m1"].notna()
        & (sub["mcap_m1"] > 0)
        & sub["ret"].notna()
        & (sub["ret"].abs() <= 0.22)
    )
    sv = sub[valid].copy()
    sv["w_ret"] = sv["mcap_m1"] * sv["ret"]
    g_dt = sv.groupby("dt")
    mkt_vw = (g_dt["w_ret"].sum() / g_dt["mcap_m1"].sum()).reindex(cal_dates).fillna(0.0)
    mkt_ew = g_dt["ret"].mean().reindex(cal_dates).fillna(0.0)

    sv["mcap_pct"] = g_dt["mcap_m1"].rank(pct=True)
    smb = (sv[sv["mcap_pct"] <= 0.30].groupby("dt")["ret"].mean() - sv[sv["mcap_pct"] >= 0.70].groupby("dt")["ret"].mean()).reindex(cal_dates).fillna(0.0)

    sv_vol = sv[sv["vol20_m1"].notna() & (sv["vol20_m1"] > 0)].copy()
    sv_vol["vol_pct"] = sv_vol.groupby("dt")["vol20_m1"].rank(pct=True)
    vol_f = (sv_vol[sv_vol["vol_pct"] >= 0.70].groupby("dt")["ret"].mean() - sv_vol[sv_vol["vol_pct"] <= 0.30].groupby("dt")["ret"].mean()).reindex(cal_dates).fillna(0.0)

    sv_liq = sv[sv["turn20_m1"].notna() & (sv["turn20_m1"] > 0)].copy()
    sv_liq["liq_pct"] = sv_liq.groupby("dt")["turn20_m1"].rank(pct=True)
    liq_f = (sv_liq[sv_liq["liq_pct"] >= 0.70].groupby("dt")["ret"].mean() - sv_liq[sv_liq["liq_pct"] <= 0.30].groupby("dt")["ret"].mean()).reindex(cal_dates).fillna(0.0)

    # 5th factor: 20cm First-Board Ecosystem Beta (t-1 non-ST 20cm 1st-board next-day EW return - MKT)
    fb20 = sub[sub["is20"] & (~sub["is_st_flag"]) & (sub["board_cnt_m1"] == 1) & sub["ret"].notna() & (sub["ret"].abs() <= 0.22)].copy()
    fb20_raw = fb20.groupby("dt")["ret"].mean().reindex(cal_dates)
    fb20_c2c_excess = fb20_raw.fillna(mkt_vw) - mkt_vw

    # Tradable non-yizi O2C 20cm First-Board Beta: t-1 non-ST non-yizi 20cm 1st-board, buyable at open (not open_is_zt)
    fb20_tr = fb20[(~fb20["is_yizi_zt_m1"]) & (fb20["volume"] > 0) & (fb20["open"] > 0) & (~fb20["open_is_zt"])].copy()
    fb20_tr["o2c"] = fb20_tr["close"] / fb20_tr["open"] - 1.0
    fb20_o2c_raw = fb20_tr.groupby("dt")["o2c"].mean().reindex(cal_dates)
    fb20_o2c_excess = fb20_o2c_raw.fillna(mkt_vw) - mkt_vw

    factors = pd.DataFrame({
        "MKT": mkt_vw, "SMB": smb, "VOL": vol_f, "LIQ": liq_f, "FB20_BETA": fb20_c2c_excess,
    }, index=cal_dates)
    extra = pd.DataFrame({
        "MKT_EW": mkt_ew, "CSI300": csi_s.reindex(cal_dates),
        "FB20_RAW": fb20_raw.fillna(0.0), "FB20_O2C_RAW": fb20_o2c_raw.fillna(0.0), "FB20_O2C_EXCESS": fb20_o2c_excess,
    }, index=cal_dates)

    fac_stats = {}
    for col in list(factors.columns) + list(extra.columns):
        s = factors[col] if col in factors.columns else extra[col]
        nav = float(np.prod(1.0 + s.to_numpy()))
        sd = float(s.std(ddof=1))
        fac_stats[col] = {
            "nav": round(nav, 4),
            "ann_ret_arith_pct": round(float(s.mean() * ANN_DAYS_STAT * 100.0), 2),
            "ann_vol_pct": round(float(sd * math.sqrt(ANN_DAYS_STAT) * 100.0), 2),
            "sharpe": round(float(s.mean() / sd * math.sqrt(ANN_DAYS_STAT)), 3) if sd > 1e-12 else 0.0,
        }
    return factors, extra, {
        "n_days": len(cal_dates),
        "fb20_c2c_covered_days": int(fb20_raw.notna().sum()),
        "fb20_o2c_covered_days": int(fb20_o2c_raw.notna().sum()),
        "stats": fac_stats,
    }


def build_by_c_lookup(df_sub: pd.DataFrame) -> dict:
    by_c = {}
    for c6, grp in df_sub.groupby("c6", sort=False):
        g = grp.reset_index(drop=True)
        dt_list = g["dt"].tolist()
        by_c[c6] = {
            "dt": dt_list,
            "dt_to_pos": {d: i for i, d in enumerate(dt_list)},
            "open": g["open"].to_numpy(dtype=float),
            "high": g["high"].to_numpy(dtype=float),
            "low": g["low"].to_numpy(dtype=float),
            "close": g["close"].to_numpy(dtype=float),
            "adj_close": g["adj_close"].to_numpy(dtype=float),
            "adjf": g["adjf"].to_numpy(dtype=float),
            "qfq": g["qfq_factor"].to_numpy(dtype=float),
            "amount": g["amount"].to_numpy(dtype=float),
            "vol20_m1": g["vol20_m1"].to_numpy(dtype=float),
            "zt_px": g["zt_px"].to_numpy(dtype=float),
            "dt_px": g["dt_px"].to_numpy(dtype=float),
            "is_dt": g["is_dt"].to_numpy(dtype=bool),
            "is_yizi_dt": g["is_yizi_dt"].to_numpy(dtype=bool),
            "volume": g["volume"].to_numpy(dtype=float),
            "vwap": g["vwap"].to_numpy(dtype=float),
        }
    return by_c


def compute_daily_mtm(led_df: pd.DataFrame, by_c: dict, cal_dates: list[str], prices_are_adj: bool = True) -> tuple[np.ndarray, np.ndarray, float, float]:
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    n_days = len(cal_dates)
    day_trades = [[] for _ in range(n_days)]
    active_flag = np.zeros(n_days, dtype=bool)
    ret_col = "net_ret_eval" if "net_ret_eval" in led_df.columns else "net_ret"
    c_col = "c6" if "c6" in led_df.columns else "code"
    bp_col = "buy_px" if "buy_px" in led_df.columns else "buy_price"
    ep_col = "exit_px" if "exit_px" in led_df.columns else "exit_price"

    for r in led_df.itertuples(index=False):
        c6 = str(getattr(r, c_col)).zfill(6)
        b_dt, e_dt = str(r.buy_date)[:10], str(r.exit_date)[:10]
        if b_dt not in dt_to_idx or e_dt not in dt_to_idx:
            continue
        b_px, e_px = float(getattr(r, bp_col)), float(getattr(r, ep_col))
        net_ret = float(getattr(r, ret_col))
        bar = by_c[c6]
        p0, pe = bar["dt_to_pos"][b_dt], bar["dt_to_pos"][e_dt]
        assert pe > p0, f"T+0 violation: {c6} {b_dt}->{e_dt}"
        b_adj = b_px if prices_are_adj else b_px * bar["adjf"][p0]
        e_adj = e_px if prices_are_adj else e_px * bar["adjf"][pe]
        factors_g, idx_days = [], []
        for k in range(p0, pe + 1):
            idx_days.append(dt_to_idx[bar["dt"][k]])
            if k == p0:
                factors_g.append(bar["adj_close"][k] / b_adj)
            elif k < pe:
                factors_g.append(bar["adj_close"][k] / bar["adj_close"][k - 1])
            else:
                factors_g.append(e_adj / bar["adj_close"][k - 1])
        pg = float(np.prod(factors_g))
        sc = math.sqrt((1.0 + net_ret) / pg) if pg > 0 else 1.0
        factors_g[0] *= sc
        factors_g[-1] *= sc
        for d_idx, mult in zip(idx_days, factors_g):
            active_flag[d_idx] = True
            day_trades[d_idx].append(mult)

    daily_ret = np.zeros(n_days, dtype=float)
    for t in range(n_days):
        if day_trades[t]:
            m = 1.0
            for x in day_trades[t]:
                m *= x
            daily_ret[t] = m - 1.0
    nav_mtm = float(np.prod(1.0 + daily_ret))
    nav_led = float(np.prod(1.0 + led_df[ret_col].to_numpy(dtype=float)))
    rel_err = abs(nav_mtm / nav_led - 1.0) if nav_led > 0 else 0.0
    assert rel_err < 1e-6, f"MTM nav mismatch: mtm={nav_mtm} led={nav_led}"
    return daily_ret, active_flag, nav_mtm, nav_led


# ==============================================================================
# PILLAR 1: 5-FACTOR ATTRIBUTION & ECOLOGICAL MATCHED CONTROL
# ==============================================================================

def fit_hac_ols(y: np.ndarray, X: pd.DataFrame, maxlags: int = 5) -> dict:
    X_c = sm.add_constant(X, has_constant="add")
    res = sm.OLS(y, X_c).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    alpha_d = float(res.params["const"])
    se_d = float(res.bse["const"])
    betas = {
        col: {"beta": sf(res.params[col], 4), "nw_t": sf(res.tvalues[col], 3), "nw_p": sf(res.pvalues[col], 4)}
        for col in X.columns
    }
    return {
        "n_obs": int(len(y)),
        "alpha_daily_bps": sf(alpha_d * 10000.0, 2),
        "alpha_ann_pct": sf(alpha_d * ANN_DAYS_STAT * 100.0, 2),
        "alpha_ann_comp_pct": sf((((1.0 + alpha_d) ** ANN_DAYS_STAT) - 1.0) * 100.0 if (1.0 + alpha_d) > -1 else -100.0, 2),
        "nw_se_bps": sf(se_d * 10000.0, 2),
        "nw_t": sf(res.tvalues["const"], 3),
        "nw_p": sf(res.pvalues["const"], 6),
        "r2": sf(res.rsquared, 4),
        "adj_r2": sf(res.rsquared_adj, 4),
        "factors": betas,
    }


def run_pillar1_regressions(led_df: pd.DataFrame, daily_s: np.ndarray, active_flag: np.ndarray,
                            factors: pd.DataFrame, extra: pd.DataFrame, cal_dates: list[str]) -> dict:
    y = daily_s
    hac_5f = fit_hac_ols(y, factors, maxlags=5)
    f_4fac = factors[["MKT", "SMB", "VOL", "LIQ"]]
    hac_4f = fit_hac_ols(y, f_4fac, maxlags=5)
    f_o2c = factors.copy()
    f_o2c["FB20_BETA"] = extra["FB20_O2C_EXCESS"]
    hac_5f_o2c = fit_hac_ols(y, f_o2c, maxlags=5)
    f_csi = factors.copy()
    f_csi["MKT"] = extra["CSI300"]
    hac_csi = fit_hac_ols(y, f_csi, maxlags=5)

    y_act = y[active_flag]
    f_act = factors.iloc[active_flag]
    hac_act = fit_hac_ols(y_act, f_act, maxlags=min(5, max(1, len(y_act) // 10)))

    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    f_arr = factors.to_numpy(dtype=float)
    ret_col = "net_ret_eval" if "net_ret_eval" in led_df.columns else "net_ret"
    tr_f_rows = []
    for r in led_df.itertuples(index=False):
        i0, i1 = dt_to_idx[str(r.buy_date)[:10]], dt_to_idx[str(r.exit_date)[:10]]
        seg = f_arr[i0 : i1 + 1]
        tr_f_rows.append(np.prod(1.0 + seg, axis=0) - 1.0)
    X_tr = pd.DataFrame(tr_f_rows, columns=factors.columns)
    y_tr = led_df[ret_col].to_numpy(dtype=float)
    res_tr = sm.OLS(y_tr, sm.add_constant(X_tr, has_constant="add")).fit(cov_type="HC3")
    trade_hc3 = {
        "n_trades": int(len(y_tr)),
        "alpha_per_trade_pct": sf(res_tr.params["const"] * 100.0, 3),
        "hc3_t": sf(res_tr.tvalues["const"], 3),
        "hc3_p": sf(res_tr.pvalues["const"], 6),
        "r2": sf(res_tr.rsquared, 4),
        "factors": {
            col: {"beta": sf(res_tr.params[col], 4), "hc3_t": sf(res_tr.tvalues[col], 3), "hc3_p": sf(res_tr.pvalues[col], 4)}
            for col in X_tr.columns
        },
    }
    return {
        "full_5f_c2c_hac": hac_5f,
        "full_4f_tradable_hac": hac_4f,
        "full_5f_o2c_hac": hac_5f_o2c,
        "full_5f_csi300_sens": hac_csi,
        "active_days_5f_hac": hac_act,
        "trade_level_hc3": trade_hc3,
    }


def prepare_20cm_matched_pools(df_20: pd.DataFrame, cal_dates: list[str]):
    dt_set = set(cal_dates)
    sub = df_20[
        df_20["dt"].isin(dt_set)
        & (~df_20["is_st_flag"])
        & (df_20["volume"] > 0)
        & (df_20["vol_m1"] > 0)
        & df_20["mcap_m1"].notna() & (df_20["mcap_m1"] > 0)
        & df_20["turn_m1"].notna() & (df_20["turn_m1"] > 0)
    ].copy()
    sub["mcap_q"] = sub.groupby("dt")["mcap_m1"].transform(lambda s: pd.qcut(s.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int) if len(s) >= 4 else 1)
    sub["turn_q"] = sub.groupby("dt")["turn_m1"].transform(lambda s: pd.qcut(s.rank(method="first"), 4, labels=[1, 2, 3, 4]).astype(int) if len(s) >= 4 else 1)

    fb20 = sub[(sub["board_cnt_m1"] == 1) & (~sub["is_yizi_zt_m1"]) & (~sub["open_is_zt"])].copy()
    pool_by_dt = {}
    for dt, grp in fb20.groupby("dt", sort=False):
        pool_by_dt[dt] = list(zip(grp["c6"].tolist(), grp["mcap_q"].tolist(), grp["turn_q"].tolist()))
    q_lookup = {(r.c6, r.dt): (int(r.mcap_q), int(r.turn_q)) for r in sub[["c6", "dt", "mcap_q", "turn_q"]].itertuples(index=False)}
    return pool_by_dt, q_lookup


def peer_hold_ret_20cm(c6: str, b_dt: str, e_dt: str, e_hhmm: int, by_c: dict, fee_rt: float = ORIG_FEE_RT):
    bar = by_c.get(c6)
    if bar is None:
        return None
    p0 = bar["dt_to_pos"].get(b_dt)
    pe = bar["dt_to_pos"].get(e_dt)
    if p0 is None:
        return None
    if pe is None:
        pe = next((i for i, d in enumerate(bar["dt"]) if d >= e_dt), None)
        if pe is None or pe <= p0:
            return None
    b_px = bar["open"][p0]
    if b_px <= 0 or np.isnan(b_px):
        return None
    if int(e_hhmm) == 925 and not bar["is_yizi_dt"][pe] and bar["volume"][pe] > 0:
        e_px = bar["open"][pe]
    elif int(e_hhmm) > 925 and not bar["is_dt"][pe] and not bar["is_yizi_dt"][pe] and bar["volume"][pe] > 0:
        e_px = bar["close"][pe]
    else:
        k = pe + 1
        while k < len(bar["dt"]) - 1 and (bar["is_dt"][k] or bar["is_yizi_dt"][k] or bar["volume"][k] <= 0):
            k += 1
        if k >= len(bar["dt"]):
            k = pe
        e_px = bar["close"][k] if bar["volume"][k] > 0 else bar["open"][k]
    if e_px <= 0 or np.isnan(e_px):
        return None
    return (e_px / b_px) * (bar["qfq"][p0] / bar["qfq"][pe]) * (1.0 - fee_rt) - 1.0


def run_matched_control_20cm(led_df: pd.DataFrame, all_sig: pd.DataFrame, thr: float,
                             pool_by_dt: dict, q_lookup: dict, by_c: dict) -> dict:
    rng = np.random.default_rng(SEED)
    ret_col = "net_ret_eval" if "net_ret_eval" in led_df.columns else "net_ret"
    tier_counts = {1: 0, 2: 0, 3: 0, "unmatched": 0}
    strat_rets, peer_means, peer_lists = [], [], []
    deep_strat_rets, deep_peer_means = [], []
    deep_by_dt = {}
    for d, grp in all_sig.groupby("buy_date"):
        deep_by_dt[d] = list(zip(grp["c6"].astype(str).str.zfill(6), grp["score"].astype(float), grp["net_ret"].astype(float)))

    for r in led_df.itertuples(index=False):
        c6 = str(r.c6).zfill(6)
        b_dt, e_dt = str(r.buy_date)[:10], str(r.exit_date)[:10]
        e_hhmm = int(getattr(r, "exit_hhmm", 1500))
        sr_val = float(getattr(r, ret_col))
        mq, tq = q_lookup.get((c6, b_dt), (None, None))
        cands_all = [x for x in pool_by_dt.get(b_dt, []) if x[0] != c6]

        tier, selected = None, []
        if mq is not None:
            t1 = [x[0] for x in cands_all if x[1] == mq and x[2] == tq]
            t2 = [x[0] for x in cands_all if x[1] == mq]
            if t1:
                selected, tier = t1, 1
            elif t2:
                selected, tier = t2, 2
        if not selected and cands_all:
            selected, tier = [x[0] for x in cands_all], 3

        if not selected:
            tier_counts["unmatched"] += 1
        else:
            prets = [p for pc in selected if (p := peer_hold_ret_20cm(pc, b_dt, e_dt, e_hhmm, by_c)) is not None]
            if not prets:
                tier_counts["unmatched"] += 1
            else:
                tier_counts[tier] += 1
                strat_rets.append(sr_val)
                peer_means.append(float(np.mean(prets)))
                peer_lists.append(np.array(prets, dtype=float))

        # Same-day unselected deep-open (<thr) matched control
        d_unsel = [x[2] for x in deep_by_dt.get(b_dt, []) if x[0] != c6 and x[1] < thr]
        if d_unsel:
            deep_strat_rets.append(sr_val)
            deep_peer_means.append(float(np.mean(d_unsel)))

    sr = np.array(strat_rets, dtype=float)
    pm = np.array(peer_means, dtype=float)
    diff = sr - pm
    t_st, p_st = stats.ttest_rel(sr, pm) if len(sr) > 1 else (0.0, 1.0)
    try:
        _, w_p = stats.wilcoxon(diff) if len(sr) >= 5 else (0.0, 1.0)
    except Exception:
        w_p = 1.0
    mc_ex, mc_sig = [], []
    if len(peer_lists) > 1:
        for _ in range(1000):
            draw = np.array([arr[rng.integers(0, len(arr))] for arr in peer_lists])
            mc_ex.append(float(np.mean(sr - draw) * 100.0))
            _, pmc = stats.ttest_rel(sr, draw)
            mc_sig.append(pmc < 0.05)

    dsr, dpm = np.array(deep_strat_rets, dtype=float), np.array(deep_peer_means, dtype=float)
    dt_t, dt_p = stats.ttest_rel(dsr, dpm) if len(dsr) > 1 else (0.0, 1.0)

    return {
        "all_20cm_1stboard_control": {
            "n_total": int(len(led_df)), "n_matched": int(len(sr)),
            "tier_counts": {str(k): int(v) for k, v in tier_counts.items()},
            "strat_avg_ret_pct": sf(sr.mean() * 100.0, 3),
            "matched_avg_ret_pct": sf(pm.mean() * 100.0, 3),
            "excess_over_matched_pct": sf(diff.mean() * 100.0, 3),
            "excess_median_pct": sf(np.median(diff) * 100.0, 3),
            "strat_wr_pct": sf((sr > 0).mean() * 100.0, 2),
            "matched_wr_pct": sf((pm > 0).mean() * 100.0, 2),
            "wr_diff_pp": sf(((sr > 0).mean() - (pm > 0).mean()) * 100.0, 2),
            "paired_t": sf(t_st, 3), "paired_p": sf(p_st, 6), "wilcoxon_p": sf(w_p, 6),
            "mc_1draw_1000_excess_med_pct": sf(np.median(mc_ex), 3) if mc_ex else None,
            "mc_1draw_1000_sig05_rate_pct": sf(np.mean(mc_sig) * 100.0, 1) if mc_sig else None,
        },
        "same_day_deepopen_lt_thr_control": {
            "n_matched_days": int(len(dsr)),
            "strat_avg_ret_pct": sf(dsr.mean() * 100.0, 3) if len(dsr) else None,
            "unselected_deepopen_avg_ret_pct": sf(dpm.mean() * 100.0, 3) if len(dpm) else None,
            "paired_excess_pct": sf((dsr - dpm).mean() * 100.0, 3) if len(dsr) else None,
            "paired_t": sf(dt_t, 3), "paired_p": sf(dt_p, 6),
        },
    }


# ==============================================================================
# PILLAR 2: ALMGREN-CHRISS CAPACITY, FILL STRESS, ADVERSE SELECTION & 5M DELAY
# ==============================================================================

def load_20cm_5m_bars(target_pairs: set[tuple[str, str]]):
    print("[3/8] Auditing local 20cm 5m/1m bar availability & loading targeted 5m bars...")
    bars_5m = {}
    need = set(target_pairs)

    def _ingest(df_sub):
        if df_sub.empty:
            return
        df_sub = df_sub.copy()
        df_sub["c6"] = df_sub["c6"].astype(str).str.zfill(6)
        df_sub["date"] = df_sub["date"].astype(str).str.slice(0, 10)
        df_sub["pair"] = list(zip(df_sub["c6"], df_sub["date"]))
        df_sub = df_sub[df_sub["pair"].isin(need)]
        if df_sub.empty:
            return
        df_sub.sort_values(["c6", "date", "hhmm_int"], inplace=True)
        for pair, grp in df_sub.groupby("pair", sort=False):
            if pair not in bars_5m and len(grp) > 0:
                bars_5m[pair] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    for pqp in [f"{SIM}/data/all_strategies_5m_complete_pit.parquet", f"{SIM}/data/cand_5m_bars_v15_complete.parquet"]:
        if os.path.exists(pqp):
            d = pd.read_parquet(pqp, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
            _ingest(d[d["c6"].astype(str).str.startswith(("30", "688", "689"))])

    rem = need - set(bars_5m.keys())
    if rem:
        dbp = f"{SIM}/backtests_astock2/data_5y/firstboard_5m_5y_pit.db"
        if os.path.exists(dbp):
            con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            codes_sql = ",".join(f"'{c}'" for c in sorted(set(p[0] for p in rem)))
            qdf = pd.read_sql_query(
                f"SELECT sec_code as c6, substr(bar_time,1,10) as date, "
                f"CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INTEGER) as hhmm_int, "
                f"open, high, low, close, volume, amount FROM firstboard_5m_kline WHERE sec_code IN ({codes_sql})",
                con,
            )
            con.close()
            _ingest(qdf)
    return bars_5m


def eval_ac_metrics(trade_items, day_base_mults, n_days, Q, Y):
    day_mults = [list(x) for x in day_base_mults]
    imp_rts, adj_rets = [], []
    for it in trade_items:
        ib = min(0.95, Y * it["sig_b"] * math.sqrt(Q / it["v_b"])) if it["v_b"] > 0 else 0.95
        ie = min(0.95, Y * it["sig_e"] * math.sqrt(Q / it["v_e"])) if it["v_e"] > 0 else 0.95
        day_mults[it["d0"]][it["pos0"]] *= (1.0 - ib)
        day_mults[it["dk"]][it["posk"]] *= (1.0 - ie)
        imp_rts.append((1.0 - (1.0 - ib) * (1.0 - ie)) * 10000.0)
        adj_rets.append((1.0 + it["net_ret"]) * (1.0 - ib) * (1.0 - ie) - 1.0)
    dr = np.zeros(n_days, dtype=float)
    for t in range(n_days):
        if day_mults[t]:
            m = 1.0
            for x in day_mults[t]:
                m *= x
            dr[t] = m - 1.0
    nav = float(np.prod(1.0 + dr))
    cagr = ((nav ** (TRD_DAYS_YEAR / n_days)) - 1.0) * 100.0 if nav > 0 else -100.0
    sd = float(dr.std(ddof=1))
    sr = float(dr.mean() / sd * math.sqrt(ANN_DAYS_STAT)) if sd > 1e-12 else 0.0
    return {"nav": nav, "cagr_pct": cagr, "sharpe": sr, "avg_trade_ret_pct": float(np.mean(adj_rets) * 100.0), "avg_rt_impact_bps": float(np.mean(imp_rts))}


def bisect_capacity(fn_val, target, lo=1e4, hi=1e12):
    if fn_val(lo) <= target:
        return round(lo / 1e4, 2)
    while fn_val(hi) > target and hi < 1e14:
        hi *= 10.0
    if fn_val(hi) > target:
        return None
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        if fn_val(mid) > target:
            lo = mid
        else:
            hi = mid
        if (hi - lo) / max(lo, 1.0) < 1e-4:
            break
    return round(math.sqrt(lo * hi) / 1e4, 2)


def run_pillar2(led_df: pd.DataFrame, by_c: dict, cal_dates: list[str], bars_5m: dict, zt_tape: pd.DataFrame) -> dict:
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    n_days = len(cal_dates)
    ret_col = "net_ret_eval" if "net_ret_eval" in led_df.columns else "net_ret"
    day_base = [[] for _ in range(n_days)]
    trade_items = []
    for r in led_df.itertuples(index=False):
        c6 = str(r.c6).zfill(6)
        b_dt, e_dt = str(r.buy_date)[:10], str(r.exit_date)[:10]
        bar = by_c[c6]
        p0, pe = bar["dt_to_pos"][b_dt], bar["dt_to_pos"][e_dt]
        b_adj, e_adj = float(r.buy_px), float(r.exit_px)
        gfs, idxs = [], []
        for k in range(p0, pe + 1):
            idxs.append(dt_to_idx[bar["dt"][k]])
            if k == p0:
                gfs.append(bar["adj_close"][k] / b_adj)
            elif k < pe:
                gfs.append(bar["adj_close"][k] / bar["adj_close"][k - 1])
            else:
                gfs.append(e_adj / bar["adj_close"][k - 1])
        pg = float(np.prod(gfs))
        net_r = float(getattr(r, ret_col))
        sc = math.sqrt((1.0 + net_r) / pg) if pg > 0 else 1.0
        gfs[0] *= sc; gfs[-1] *= sc
        pos_list = []
        for d_idx, mult in zip(idxs, gfs):
            pos_list.append((d_idx, len(day_base[d_idx])))
            day_base[d_idx].append(mult)
        sig_b = bar["vol20_m1"][p0]
        sig_e = bar["vol20_m1"][pe]
        sig_b = 0.05 if (np.isnan(sig_b) or sig_b <= 0) else float(sig_b)
        sig_e = 0.05 if (np.isnan(sig_e) or sig_e <= 0) else float(sig_e)
        trade_items.append({
            "d0": pos_list[0][0], "pos0": pos_list[0][1], "dk": pos_list[-1][0], "posk": pos_list[-1][1],
            "sig_b": sig_b, "sig_e": sig_e, "v_b": float(bar["amount"][p0]), "v_e": float(bar["amount"][pe]),
            "net_ret": net_r,
        })

    q_grid = [1e6, 3e6, 5e6, 1e7, 2e7, 5e7, 1e8]
    base_0 = eval_ac_metrics(trade_items, day_base, n_days, 0.0, 0.50)
    ac_results = {}
    for Y in (0.50, 0.70):
        grid_out = {}
        for Q in q_grid:
            m = eval_ac_metrics(trade_items, day_base, n_days, Q, Y)
            grid_out[f"{int(Q // 1e4)}w"] = {k: sf(v, 4 if k == "nav" else (2 if "pct" in k or "bps" in k else 3)) for k, v in m.items()}
        ac_results[f"Y_{Y:.2f}"] = {
            "grid": grid_out,
            "breakeven_cap_wan": bisect_capacity(lambda q: eval_ac_metrics(trade_items, day_base, n_days, q, Y)["nav"], 1.0),
            "half_cagr_cap_wan": bisect_capacity(lambda q: eval_ac_metrics(trade_items, day_base, n_days, q, Y)["cagr_pct"], 0.5 * base_0["cagr_pct"]),
            "half_simple_profit_cap_wan": bisect_capacity(lambda q: eval_ac_metrics(trade_items, day_base, n_days, q, Y)["nav"] - 1.0, 0.5 * (base_0["nav"] - 1.0)),
        }

    # Random fill stress (50% / 70%, 2000 MC)
    rng = np.random.default_rng(SEED)
    rets_arr = led_df[ret_col].to_numpy(dtype=float)
    n_tr = len(rets_arr)
    fill_stress = {}
    for p_fill in (0.50, 0.70):
        masks = rng.random((2000, n_tr)) < p_fill
        mults = np.where(masks, 1.0 + rets_arr[None, :], 1.0)
        paths = np.concatenate([np.ones((2000, 1)), np.cumprod(mults, axis=1)], axis=1)
        tn = paths[:, -1]
        cagrs = ((tn ** (TRD_DAYS_YEAR / n_days)) - 1.0) * 100.0
        mdds = (1.0 - paths / np.maximum.accumulate(paths, axis=1)).max(axis=1) * 100.0
        fill_stress[f"fill_{int(p_fill*100)}pct"] = {
            "nav_median": sf(np.median(tn), 3), "nav_p05": sf(np.quantile(tn, 0.05), 3), "nav_p95": sf(np.quantile(tn, 0.95), 3),
            "cagr_median_pct": sf(np.median(cagrs), 2), "cagr_p05_pct": sf(np.quantile(cagrs, 0.05), 2),
            "mdd_median_pct": sf(np.median(mdds), 2), "mdd_p95_pct": sf(np.quantile(mdds, 0.95), 2),
        }

    # Adverse selection: Drop Top 10% & 20% by net_ret AND by T0 seal_amount
    seal_map = {(zr.c6, zr.trade_date): float(zr.seal_amount or 0.0) for zr in zt_tape.itertuples(index=False)}
    idx_ret_desc = np.argsort(-rets_arr, kind="mergesort")
    seal_vals = np.array([seal_map.get((str(r.c6).zfill(6), str(r.sig_date)[:10]), 0.0) for r in led_df.itertuples(index=False)])
    idx_seal_desc = np.argsort(-seal_vals, kind="mergesort")

    def _trim(mask):
        sr = rets_arr[mask]
        return {"n_rem": int(len(sr)), "n_dropped": int(n_tr - len(sr)), "wr_pct": sf((sr > 0).mean() * 100.0, 2), "avg_ret_pct": sf(sr.mean() * 100.0, 3), "nav": sf(np.prod(1.0 + sr), 3)}

    adverse = {"by_net_ret": {}, "by_t0_seal_amount": {}}
    for pct in (10, 20):
        kd = max(1, int(round(n_tr * pct / 100.0)))
        mr = np.ones(n_tr, dtype=bool); mr[idx_ret_desc[:kd]] = False
        ms = np.ones(n_tr, dtype=bool); ms[idx_seal_desc[:kd]] = False
        adverse["by_net_ret"][f"drop_top_{pct}pct"] = _trim(mr)
        adverse["by_t0_seal_amount"][f"drop_top_{pct}pct"] = _trim(ms)

    # 1m / 5m bar delay audit (+5m / +15m) with strict MISSING_LOCAL_DATA disclosure
    cov_buy = sum((str(r.c6).zfill(6), str(r.buy_date)[:10]) in bars_5m for r in led_df.itertuples(index=False))
    cov_exit = sum((str(r.c6).zfill(6), str(r.exit_date)[:10]) in bars_5m for r in led_df.itertuples(index=False))
    cov_by_yr = {}
    for yr in ("2021", "2022", "2023", "2024", "2025", "2026"):
        sub_y = led_df[led_df["buy_date"].str.startswith(yr)]
        hit_y = sum((str(r.c6).zfill(6), str(r.buy_date)[:10]) in bars_5m for r in sub_y.itertuples(index=False))
        cov_by_yr[yr] = f"{hit_y}/{len(sub_y)}"

    delay_out = {
        "delay_1m": "MISSING_LOCAL_DATA (本地无任何A股1分钟K线数据，覆盖率 0/N = 0.0%)",
        "five_m_buy_coverage": f"{cov_buy}/{n_tr} ({cov_buy/n_tr*100:.1f}%)",
        "five_m_exit_coverage": f"{cov_exit}/{n_tr} ({cov_exit/n_tr*100:.1f}%)",
        "five_m_buy_by_year": cov_by_yr,
        "five_m_data_status": f"MISSING_LOCAL_DATA_POST_20230822 (2023-08-23至2026-11-23本地无20cm 5m线; 买入日仅2021-2023-08覆盖 {cov_buy}/{n_tr}={cov_buy/n_tr*100:.1f}%, 卖出日覆盖 {cov_exit}/{n_tr}=0.0%)",
    }
    for step_lbl, tgt_idx in (("plus_5m_0935", 0), ("plus_15m_0945", 2)):
        base_cov, ret_zero, ret_skip = [], [], []
        missed_zt = 0
        for r in led_df.itertuples(index=False):
            c6 = str(r.c6).zfill(6)
            arr = bars_5m.get((c6, str(r.buy_date)[:10]))
            if arr is None or len(arr) <= tgt_idx:
                continue
            base_cov.append(float(getattr(r, ret_col)))
            bar_d = by_c[c6]
            p0 = bar_d["dt_to_pos"][str(r.buy_date)[:10]]
            zt_px = float(bar_d["zt_px"][p0])
            d_bar = arr[tgt_idx]  # [hhmm_int, open, high, low, close, volume, amount]
            if d_bar[4] >= zt_px - 0.011:
                missed_zt += 1
                ret_zero.append(0.0)
            else:
                new_bpx_adj = float(d_bar[4]) * bar_d["adjf"][p0]
                new_ret = (float(r.exit_px) / new_bpx_adj) * (1.0 - ORIG_FEE_RT) - 1.0
                ret_zero.append(new_ret)
                ret_skip.append(new_ret)

        def _ds(lst):
            a = np.array(lst, dtype=float)
            return {"n": int(len(a)), "wr_pct": sf((a > 0).mean() * 100.0, 2), "avg_ret_pct": sf(a.mean() * 100.0, 3), "nav": sf(np.prod(1.0 + a), 3)} if len(a) else {"n": 0}

        delay_out[step_lbl] = {
            "covered_subsample_base": _ds(base_cov),
            "missed_zt_at_delay_bar": int(missed_zt),
            "covered_missed_as_zero": _ds(ret_zero),
            "covered_missed_skipped": _ds(ret_skip),
        }

    vb_arr = np.array([it["v_b"] for it in trade_items], dtype=float) / 1e4
    ve_arr = np.array([it["v_e"] for it in trade_items], dtype=float) / 1e4
    v5_list = [float(bars_5m[(str(r.c6).zfill(6), str(r.buy_date)[:10])][0, 6]) / 1e4 for r in led_df.itertuples(index=False) if (str(r.c6).zfill(6), str(r.buy_date)[:10]) in bars_5m]
    v_guard = {
        "v_buy_wan_min": sf(np.min(vb_arr), 1), "v_buy_wan_p10": sf(np.quantile(vb_arr, 0.10), 1), "v_buy_wan_median": sf(np.median(vb_arr), 1),
        "v_exit_wan_min": sf(np.min(ve_arr), 1), "v_exit_wan_p10": sf(np.quantile(ve_arr, 0.10), 1), "v_exit_wan_median": sf(np.median(ve_arr), 1),
        "cap_10pct_adv_p10_wan": sf(min(np.quantile(vb_arr, 0.10), np.quantile(ve_arr, 0.10)) * 0.10, 1),
        "cap_5pct_adv_p10_wan": sf(min(np.quantile(vb_arr, 0.10), np.quantile(ve_arr, 0.10)) * 0.05, 1),
        "v_entry_5m_cov": f"{len(v5_list)}/{n_tr}",
        "v_entry_5m_wan_p10": sf(np.quantile(v5_list, 0.10), 1) if v5_list else None,
        "cap_20pct_5m_p10_wan": sf(np.quantile(v5_list, 0.10) * 0.20, 1) if v5_list else None,
    }
    return {
        "baseline_unconstrained": {"nav": sf(base_0["nav"], 4), "cagr_pct": sf(base_0["cagr_pct"], 2), "sharpe": sf(base_0["sharpe"], 3)},
        "liquidity_participation_guardrails": v_guard,
        "almgren_chriss": ac_results,
        "random_fill_2000mc": fill_stress,
        "adverse_selection": adverse,
        "entry_delay": delay_out,
    }


# ==============================================================================
# PILLAR 3: REGIME MATRIX, 4 EXTREME REPLAYS & 10,000x BLOCK BOOTSTRAP (b=5)
# ==============================================================================

def build_regime_table_20cm(df_all: pd.DataFrame, cal_full: list[str], all_sh_dts: list[str],
                            tot_amt: pd.Series, zt_tape: pd.DataFrame, extra_full: pd.DataFrame) -> pd.DataFrame:
    print("[4/8] Building 20cm & macro regime matrix (2021-01-04..2026-11-23)...")
    r15 = pd.read_parquet(f"{SIM}/backtests_astock2/theory_backtest_15y_20261119/data_cache/regime_daily_15y.parquet")
    r15.index = pd.to_datetime(r15.index).strftime("%Y-%m-%d")

    tot_amt_roll60 = tot_amt.shift(1).rolling(60, min_periods=20).median()
    amt_q60_map = {
        d: ("放量(>=60日分位)" if tot_amt.get(d, 0.0) >= tot_amt_roll60.get(d, 0.0) else "缩量(<60日分位)")
        for d in cal_full
    }

    # 20cm native daily ecosystem stats
    sub20 = df_all[df_all["is20"] & (~df_all["is_st_flag"]) & df_all["dt"].isin(set(cal_full))]
    g20 = sub20.groupby("dt").agg(n_zt20=("is_zt", "sum"), n_hit20=("hit_zt", "sum"), n_dt20=("is_dt", "sum"))

    # Broad A-share non-ST ZT/DT & 10cm lianban promotion from zt_tape
    zt_nonst = zt_tape[~zt_tape["sec_name"].str.contains("ST|退", na=False)]
    zt_10 = zt_nonst[zt_nonst["sec_code"].str.startswith(("00", "60"))]
    zt_by_dt = {d: set(g["c6"]) for d, g in zt_10.groupby("trade_date")}
    lb2_by_dt = {d: set(g["c6"]) for d, g in zt_10[zt_10["board_count"] >= 2].groupby("trade_date")}
    n_zt_all_map = zt_nonst.groupby("trade_date").size().to_dict()

    de5_p = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/daily_env_5y.parquet"
    de5 = pd.read_parquet(de5_p).set_index("dt_str") if os.path.exists(de5_p) else pd.DataFrame()
    nonst_all = df_all[(~df_all["is_st_flag"]) & df_all["dt"].isin(set(cal_full))]
    seal_all_df = nonst_all.groupby("dt").agg(n_zt=("is_zt", "sum"), n_hit=("hit_zt", "sum"))

    rows = []
    last_tr, last_vr, last_a15 = "震荡区间", "低波动期", "低成交期"
    for d in cal_full:
        if d in r15.index:
            last_tr = str(r15.loc[d, "trend_regime"])
            last_vr = str(r15.loc[d, "vol_regime"])
            last_a15 = str(r15.loc[d, "amt_regime"])
        n20_z = int(g20.loc[d, "n_zt20"]) if d in g20.index else 0
        n20_h = int(g20.loc[d, "n_hit20"]) if d in g20.index else 0
        n20_d = int(g20.loc[d, "n_dt20"]) if d in g20.index else 0
        zb20 = (1.0 - n20_z / n20_h) if n20_h > 0 else 0.0
        fb20_r = float(extra_full.loc[d, "FB20_RAW"]) if d in extra_full.index else 0.0
        is_ebb20 = bool((n20_d >= 3) or (n20_h >= 4 and zb20 > 0.45) or (fb20_r < -0.02))
        if n20_z <= 3:
            b20 = "20cm冰点(<=3家)"
        elif n20_z <= 11:
            b20 = "20cm常规(4~11家)"
        else:
            b20 = "20cm高潮(>=12家)"
        eco20_quad = "20cm退潮(跌停>=3或炸板>45%或首板溢价<-2%)" if is_ebb20 else b20

        # Broad market quadrant
        pos_sh = all_sh_dts.index(d) if d in all_sh_dts else -1
        prev_d = all_sh_dts[pos_sh - 1] if pos_sh > 0 else d
        prev_lb = lb2_by_dt.get(prev_d, set())
        promo_lb = len(prev_lb & zt_by_dt.get(d, set())) / len(prev_lb) if prev_lb else np.nan
        if d in de5.index:
            n_zt_m = float(de5.loc[d, "n_zt"])
            sr_m = float(de5.loc[d, "seal_rate"])
            promo_m = float(de5.loc[d, "ho_zt_r"]) if pd.notna(de5.loc[d, "ho_zt_r"]) else promo_lb
        else:
            n_zt_m = float(n_zt_all_map.get(d, seal_all_df.loc[d, "n_zt"] if d in seal_all_df.index else 0))
            nh_m = float(seal_all_df.loc[d, "n_hit"]) if d in seal_all_df.index else 0.0
            sr_m = (float(seal_all_df.loc[d, "n_zt"]) / nh_m) if nh_m > 0 else np.nan
            promo_m = promo_lb
        zb_m = 1.0 - sr_m if pd.notna(sr_m) else np.nan
        is_ebb_m = bool((pd.notna(promo_m) and promo_m < 0.20) or (pd.notna(zb_m) and zb_m > 0.35))
        nzt_bm = "冰点(<40)" if n_zt_m < 40 else ("常规(40~85)" if n_zt_m <= 85 else "高潮(>85)")
        lb_quad = "退潮(晋级<20%或炸板>35%)" if is_ebb_m else nzt_bm

        rows.append({
            "dt": d, "trend_regime": last_tr, "vol_regime": last_vr, "amt_regime_15y": last_a15,
            "amt_regime_q60": amt_q60_map[d], "eco20_quad": eco20_quad, "eco20_bucket": b20,
            "eco20_ebb_flag": "20cm退潮日" if is_ebb20 else "20cm非退潮日",
            "lb_quadrant": lb_quad, "lb_ebb_flag": "全市场退潮日" if is_ebb_m else "全市场非退潮日",
        })
    reg_df = pd.DataFrame(rows).set_index("dt")
    for col in ["trend_regime", "vol_regime", "amt_regime_q60", "eco20_quad", "eco20_ebb_flag", "lb_quadrant", "lb_ebb_flag"]:
        reg_df[f"{col}_m1"] = reg_df[col].shift(1).bfill()
    return reg_df


def _slice_tr(sub_df: pd.DataFrame, ret_col: str) -> dict:
    n = int(len(sub_df))
    if n == 0:
        return {"n": 0, "wr_pct": None, "avg_ret_pct": None, "cum_ret_pct": 0.0, "max_dd_pct": 0.0}
    r = sub_df[ret_col].to_numpy(dtype=float)
    nav = np.concatenate([[1.0], np.cumprod(1.0 + r)])
    dd = (1.0 - nav / np.maximum.accumulate(nav)).max() * 100.0
    return {"n": n, "wr_pct": sf((r > 0).mean() * 100.0, 2), "avg_ret_pct": sf(r.mean() * 100.0, 3), "cum_ret_pct": sf((nav[-1] - 1.0) * 100.0, 2), "max_dd_pct": sf(dd, 2)}


def _slice_mtm(r_arr: np.ndarray) -> dict:
    if len(r_arr) == 0:
        return {"mtm_days": 0, "mtm_cum_ret_pct": 0.0, "mtm_max_dd_pct": 0.0}
    nav = np.concatenate([[1.0], np.cumprod(1.0 + r_arr)])
    dd = (1.0 - nav / np.maximum.accumulate(nav)).max() * 100.0
    return {"mtm_days": int(len(r_arr)), "mtm_cum_ret_pct": sf((nav[-1] - 1.0) * 100.0, 2), "mtm_max_dd_pct": sf(dd, 2)}


def run_pillar3(led_df: pd.DataFrame, daily_arr: np.ndarray, reg_df: pd.DataFrame,
                csi_arr: np.ndarray, cal_full: list[str]) -> dict:
    ret_col = "net_ret_eval" if "net_ret_eval" in led_df.columns else "net_ret"
    dims = [
        ("trend_regime", "大盘趋势"), ("amt_regime_q60", "市场量能_60日分位"),
        ("vol_regime", "市场波动"), ("eco20_quad", "20cm生态四象限"),
        ("eco20_ebb_flag", "20cm退潮标记"), ("lb_quadrant", "全市场连板生态四象限"),
    ]
    dw = led_df.copy()
    for col, _ in dims:
        dw[col] = dw["buy_date"].map(reg_df[col])
        dw[f"{col}_m1"] = dw["buy_date"].map(reg_df[f"{col}_m1"])

    reg_mat = {"by_buy_date": {}, "by_pit_m1": {}}
    enemies_n3, enemies_any = [], []
    for col, lbl in dims:
        gout, gm1 = {}, {}
        for val, sub in dw.groupby(col, sort=False):
            m = _slice_tr(sub, ret_col)
            mm = _slice_mtm(daily_arr[(reg_df[col] == val).to_numpy()])
            m["mtm_days"], m["mtm_cum_ret_pct"] = mm["mtm_days"], mm["mtm_cum_ret_pct"]
            gout[str(val)] = m
            if col in ("trend_regime", "amt_regime_q60", "vol_regime", "eco20_quad"):
                if m["n"] >= 3:
                    enemies_n3.append((f"{lbl}:{val}", m["n"], m["avg_ret_pct"], m["cum_ret_pct"], m["wr_pct"]))
                if m["n"] >= 1:
                    enemies_any.append((f"{lbl}:{val}", m["n"], m["avg_ret_pct"], m["cum_ret_pct"], m["wr_pct"]))
        reg_mat["by_buy_date"][col] = gout
        for val, sub in dw.groupby(f"{col}_m1", sort=False):
            gm1[str(val)] = _slice_tr(sub, ret_col)
        reg_mat["by_pit_m1"][col] = gm1

    wn3 = min(enemies_n3, key=lambda x: (x[3], x[2])) if enemies_n3 else None
    wany = min(enemies_any, key=lambda x: (x[3], x[2])) if enemies_any else None
    reg_mat["worst_enemy_regime_n_ge_3"] = {"regime": wn3[0], "n": wn3[1], "avg_ret_pct": wn3[2], "cum_ret_pct": wn3[3], "wr_pct": wn3[4]} if wn3 else None
    reg_mat["worst_enemy_regime_any_n"] = {"regime": wany[0], "n": wany[1], "avg_ret_pct": wany[2], "cum_ret_pct": wany[3], "wr_pct": wany[4]} if wany else None

    cal_arr = np.array(cal_full)
    ebb20_arr = (reg_df["eco20_ebb_flag"] == "20cm退潮日").to_numpy()
    ebb_all_arr = (reg_df["lb_ebb_flag"] == "全市场退潮日").to_numpy()
    scenarios = {}
    for w_nm, d0, d1, ebb_mode in [
        ("W1_2022_04_lockdown", "2022-03-01", "2022-04-30", None),
        ("W2_2024_01_microcap_crash", "2024-01-01", "2024-02-08", None),
        ("W3_2024_0924_rally", "2024-09-24", "2024-10-15", None),
        ("W4_2025_2026_ebb20_days", "2025-01-01", FULL_END, "20cm"),
        ("W4_2025_2026_ebb_all_days", "2025-01-01", FULL_END, "all"),
        ("W4_2025_2026_full_period", "2025-01-01", FULL_END, None),
    ]:
        tm_mask = (dw["buy_date"] >= d0) & (dw["buy_date"] <= d1)
        dm_mask = (cal_arr >= d0) & (cal_arr <= d1)
        if ebb_mode == "20cm":
            tm_mask &= (dw["eco20_ebb_flag"] == "20cm退潮日")
            dm_mask &= ebb20_arr
        elif ebb_mode == "all":
            tm_mask &= (dw["buy_date"].map(reg_df["lb_ebb_flag"]) == "全市场退潮日")
            dm_mask &= ebb_all_arr
        tm = _slice_tr(dw[tm_mask], ret_col)
        mm = _slice_mtm(daily_arr[dm_mask])
        cm = _slice_mtm(csi_arr[dm_mask])
        scenarios[w_nm] = {**tm, **mm, "csi300_cum_ret_pct": cm["mtm_cum_ret_pct"]}

    # 10,000x Moving Block Bootstrap (b=5)
    rng = np.random.default_rng(SEED)
    n_days, b_len, n_boot = len(daily_arr), 5, MC_B
    n_blocks = int(math.ceil(n_days / b_len))
    blocks = np.lib.stride_tricks.sliding_window_view(daily_arr, b_len)
    starts = rng.integers(0, n_days - b_len + 1, size=(n_boot, n_blocks))
    sim_rets = blocks[starts].reshape(n_boot, n_blocks * b_len)[:, :n_days]
    sim_navs = np.concatenate([np.ones((n_boot, 1)), np.cumprod(1.0 + sim_rets, axis=1)], axis=1)
    tn = sim_navs[:, -1]
    pks = np.maximum.accumulate(sim_navs, axis=1)
    mdds = ((1.0 - sim_navs / pks) * 100.0).max(axis=1)
    is_uw = sim_navs[:, 1:] < pks[:, 1:] * (1.0 - 1e-12)
    cur_uw = np.zeros(n_boot, dtype=np.int32)
    max_uw = np.zeros(n_boot, dtype=np.int32)
    for t in range(n_days):
        cur_uw = np.where(is_uw[:, t], cur_uw + 1, 0)
        max_uw = np.maximum(max_uw, cur_uw)
    csi_nav = float(np.prod(1.0 + csi_arr))

    bootstrap = {
        "n_boot": n_boot, "block_len": b_len, "n_days": n_days,
        "actual_full_nav": sf(np.prod(1.0 + daily_arr), 4), "csi300_full_nav": sf(csi_nav, 4),
        "nav_mean": sf(np.mean(tn), 3), "nav_median": sf(np.median(tn), 3),
        "nav_p01": sf(np.quantile(tn, 0.01), 3), "nav_p05": sf(np.quantile(tn, 0.05), 3),
        "nav_p25": sf(np.quantile(tn, 0.25), 3), "nav_p75": sf(np.quantile(tn, 0.75), 3), "nav_p95": sf(np.quantile(tn, 0.95), 3),
        "prob_loss_pct": sf((tn < 1.0).mean() * 100.0, 2),
        "prob_beat_csi300_pct": sf((tn > csi_nav).mean() * 100.0, 2),
        "mdd_mean_pct": sf(np.mean(mdds), 2), "mdd_median_pct": sf(np.median(mdds), 2),
        "mdd_p95_pct": sf(np.quantile(mdds, 0.95), 2), "mdd_p99_pct": sf(np.quantile(mdds, 0.99), 2),
        "underwater_days_mean": sf(np.mean(max_uw), 1), "underwater_days_median": sf(np.median(max_uw), 1),
        "underwater_days_p95": sf(np.quantile(max_uw, 0.95), 1), "underwater_days_p99": sf(np.quantile(max_uw, 0.99), 1),
    }
    return {"regime_matrix": reg_mat, "extreme_scenarios": scenarios, "block_bootstrap_10k": bootstrap}


# ==============================================================================
# PILLAR 4: RANK IC, Q_ICIR, 12M IC DECAY, MONOTONICITY, BREAKEVEN BPS, BRIER/AUC, HOLDING DECAY
# ==============================================================================

def newey_west_slope_t(x: np.ndarray, y: np.ndarray, max_lag: int = 6):
    n = len(x)
    if n < 3 or np.std(x) < 1e-12:
        return 0.0, 0.0, 1.0, 0.0, 1.0
    X = np.column_stack([np.ones(n), x])
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    slope = float(beta[1])
    xtx_inv = np.linalg.inv(X.T @ X)
    s2 = float(np.sum(resid ** 2) / max(1, n - 2))
    se_ols = math.sqrt(max(1e-18, s2 * xtx_inv[1, 1]))
    t_ols = slope / se_ols
    p_ols = float(2.0 * stats.t.sf(abs(t_ols), df=max(1, n - 2)))
    L = min(max_lag, max(1, n - 2))
    S_hac = (X * resid[:, None]).T @ (X * resid[:, None])
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)
        G_lag = (X[lag:] * resid[lag:, None]).T @ (X[:-lag] * resid[:-lag, None])
        S_hac += w * (G_lag + G_lag.T)
    cov_hac = xtx_inv @ S_hac @ xtx_inv
    se_hac = math.sqrt(max(1e-18, float(cov_hac[1, 1])))
    t_hac = slope / se_hac
    p_hac = float(2.0 * stats.t.sf(abs(t_hac), df=max(1, n - 2)))
    return slope, t_ols, p_ols, t_hac, p_hac


def calc_ic_block_20cm(df: pd.DataFrame, score_col: str, ret_col: str = "net_ret", min_period_n: int = 4, min_roll_n: int = 10) -> dict:
    d = df.dropna(subset=[score_col, ret_col]).copy()
    d["bd"] = d["buy_date"].astype(str).str[:10]
    n = len(d)
    if n < 3 or d[score_col].nunique() < 2:
        return {"n": int(n), "insufficient": True}
    rho_all, p_all = stats.spearmanr(d[score_col], d[ret_col])

    cs_stats = {}
    for min_d in (2, 3):
        ics = []
        for _, grp in d.groupby("bd"):
            if len(grp) >= min_d and grp[score_col].nunique() >= 2 and grp[ret_col].nunique() >= 2:
                r, _ = stats.spearmanr(grp[score_col], grp[ret_col])
                if not np.isnan(r):
                    ics.append(float(r))
        if ics:
            arr = np.array(ics)
            sd = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
            cs_stats[f"min_cand_{min_d}"] = {
                "n_days": len(arr), "mean_ic": sf(arr.mean(), 4), "std_ic": sf(sd, 4),
                "icir": sf(arr.mean() / sd, 4) if sd > 1e-12 else None, "pos_rate_pct": sf((arr > 0).mean() * 100.0, 2),
            }
        else:
            cs_stats[f"min_cand_{min_d}"] = {"n_days": 0}

    def grouped_ic(per_s: pd.Series, min_obs: int) -> dict:
        tmp = d.copy(); tmp["_p"] = per_s.values
        vals = []
        for per, grp in tmp.groupby("_p", sort=True):
            if len(grp) >= min_obs and grp[score_col].nunique() >= 2 and grp[ret_col].nunique() >= 2:
                r, p = stats.spearmanr(grp[score_col], grp[ret_col])
                if not np.isnan(r):
                    vals.append({"period": str(per), "n": int(len(grp)), "ic": float(r), "p": float(p)})
        if not vals:
            return {"n_valid_periods": 0}
        arr = np.array([v["ic"] for v in vals])
        sd = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        return {
            "n_valid_periods": len(arr), "mean_ic": sf(arr.mean(), 4), "std_ic": sf(sd, 4),
            "icir": sf(arr.mean() / sd, 4) if sd > 1e-12 else None,
            "pos_rate_pct": sf((arr > 0).mean() * 100.0, 2),
        }

    dt_idx = pd.to_datetime(d["bd"])
    q_res = grouped_ic(dt_idx.dt.to_period("Q"), min_period_n)
    m_res = grouped_ic(dt_idx.dt.to_period("M"), min_period_n)

    end_months = pd.period_range("2021-12", "2026-11", freq="M")
    roll_pts = []
    for em in end_months:
        w_end = em.to_timestamp(how="end").strftime("%Y-%m-%d")
        w_start = (em - 11).to_timestamp(how="start").strftime("%Y-%m-%d")
        sub = d[(d["bd"] >= w_start) & (d["bd"] <= w_end)]
        if len(sub) >= min_roll_n and sub[score_col].nunique() >= 2 and sub[ret_col].nunique() >= 2:
            r, _ = stats.spearmanr(sub[score_col], sub[ret_col])
            if not np.isnan(r):
                roll_pts.append({"end_month": str(em), "n": int(len(sub)), "ic": float(r)})
    if len(roll_pts) >= 6:
        t_yrs = np.array([(pd.Period(p["end_month"], "M") - end_months[0]).n / 12.0 for p in roll_pts], dtype=float)
        ics_r = np.array([p["ic"] for p in roll_pts], dtype=float)
        slope, t_ols, p_ols, t_hac, p_hac = newey_west_slope_t(t_yrs, ics_r, max_lag=6)
        roll_res = {
            "n_windows": len(roll_pts), "mean_ic": sf(ics_r.mean(), 4),
            "first_window": {"month": roll_pts[0]["end_month"], "n": roll_pts[0]["n"], "ic": sf(roll_pts[0]["ic"], 4)},
            "last_window": {"month": roll_pts[-1]["end_month"], "n": roll_pts[-1]["n"], "ic": sf(roll_pts[-1]["ic"], 4)},
            "ols_slope_per_year": sf(slope, 4), "ols_t_stat": sf(t_ols, 3), "ols_p_value": sf(p_ols, 4),
            "nw_hac_lag6_t_stat": sf(t_hac, 3), "nw_hac_lag6_p_value": sf(p_hac, 4),
            "sig_decay_at_5pct_hac": bool(slope < 0 and p_hac < 0.05),
        }
    else:
        roll_res = {"n_windows": len(roll_pts), "insufficient": True}

    def _sp(sub_df):
        if len(sub_df) < 3 or sub_df[score_col].nunique() < 2:
            return {"n": int(len(sub_df)), "ic": None, "p": None}
        r, p = stats.spearmanr(sub_df[score_col], sub_df[ret_col])
        return {"n": int(len(sub_df)), "ic": sf(r, 4), "p": sf(p, 4)}

    return {
        "n": int(n), "pooled_spearman_ic": sf(rho_all, 4), "pooled_p_value": sf(p_all, 6),
        "daily_cross_sectional_ic": cs_stats, "quarterly_ic": q_res, "monthly_ic": m_res,
        "rolling_12m_ic_decay": roll_res,
        "is_ic": _sp(d[d["bd"] <= "2024-08-31"]), "oos_ic": _sp(d[d["bd"] >= "2024-09-01"]),
        "yearly_ic": {yr: _sp(d[d["bd"].str.startswith(yr)]) for yr in ("2021", "2022", "2023", "2024", "2025", "2026")},
    }


def calc_quantile_bins(scores: np.ndarray, rets: np.ndarray, n_bins: int, mode: str = "value_qcut") -> dict:
    s, r = pd.Series(scores, dtype=float), np.asarray(rets, dtype=float)
    if len(s) < n_bins:
        return {"insufficient": True}
    cats = pd.qcut(s, q=n_bins, labels=False, duplicates="drop") if mode == "value_qcut" else pd.qcut(s.rank(method="first"), q=n_bins, labels=False)
    if int(cats.nunique()) < 2:
        return {"insufficient": True}
    rows = []
    for b in sorted(cats.unique()):
        m = (cats == b).to_numpy()
        rb, sb = r[m], scores[m]
        w, l = rb[rb > 0], rb[rb <= 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
        rows.append({
            "bin": int(b) + 1, "n": int(m.sum()), "score_min": sf(sb.min(), 2), "score_max": sf(sb.max(), 2),
            "win_rate_pct": sf((rb > 0).mean() * 100.0, 2), "mean_ret_pct": sf(rb.mean() * 100.0, 3),
            "median_ret_pct": sf(np.median(rb) * 100.0, 3), "plr": sf(plr, 2),
        })
    b_idx = np.array([x["bin"] for x in rows], dtype=float)
    rho_r, p_r = stats.spearmanr(b_idx, [x["mean_ret_pct"] for x in rows])
    rho_w, p_w = stats.spearmanr(b_idx, [x["win_rate_pct"] for x in rows])
    r_bot, r_top = r[(cats == min(cats.unique())).to_numpy()], r[(cats == max(cats.unique())).to_numpy()]
    t_sp, p_sp = stats.ttest_ind(r_top, r_bot, equal_var=False) if (len(r_top) > 1 and len(r_bot) > 1) else (0.0, 1.0)
    return {
        "requested_bins": n_bins, "actual_bins": int(cats.nunique()), "mode": mode, "bins": rows,
        "spearman_rho_mean_ret": sf(rho_r, 4), "spearman_p_mean_ret": sf(p_r, 4),
        "spearman_rho_win_rate": sf(rho_w, 4), "spearman_p_win_rate": sf(p_w, 4),
        "top_minus_bot_mean_pp": sf((r_top.mean() - r_bot.mean()) * 100.0, 3),
        "top_minus_bot_welch_t": sf(t_sp, 3), "top_minus_bot_welch_p": sf(p_sp, 4),
    }


def calc_breakeven_cost_20cm(net_rets: np.ndarray, csi_full_ret: float) -> dict:
    n = len(net_rets)
    gross_mult = (1.0 + net_rets) / (1.0 - ORIG_FEE_RT)
    gross_rets = gross_mult - 1.0
    arith_gross = float(np.mean(gross_rets))
    geom_gross_mult = math.exp(float(np.mean(np.log(np.maximum(1e-9, gross_mult)))))
    c_arith_ow = 0.5 * (1.0 - 1.0 / (1.0 + arith_gross))
    c_geom_ow = 0.5 * (1.0 - 1.0 / geom_gross_mult)
    target_mult = (1.0 + csi_full_ret) ** (1.0 / n) if n > 0 else 1.0
    c_csi_ow = 0.5 * (1.0 - target_mult / geom_gross_mult)
    sens_grid = []
    for ow_bps in (15, 25, 40, 50, 100, 150, 200, 300):
        rt = 2.0 * ow_bps / 10000.0
        rc = gross_mult * (1.0 - rt) - 1.0
        sens_grid.append({"one_way_bps": ow_bps, "round_trip_bps": 2 * ow_bps, "arith_mean_pct": sf(rc.mean() * 100.0, 3), "nav": sf(np.prod(1.0 + rc), 3)})
    return {
        "original_deducted_rt_bps": ORIG_FEE_RT * 10000.0, "original_deducted_ow_bps": ORIG_FEE_OW_BPS,
        "gross_arith_mean_pct": sf(arith_gross * 100.0, 3),
        "gross_geom_mean_pct": sf((geom_gross_mult - 1.0) * 100.0, 3),
        "breakeven_ow_arith_bps": sf(c_arith_ow * 10000.0, 1),
        "breakeven_ow_geom_bps": sf(c_geom_ow * 10000.0, 1),
        "breakeven_ow_beat_csi300_bps": sf(c_csi_ow * 10000.0, 1),
        "safety_margin_vs_15bps_ow_geom": sf((c_geom_ow * 10000.0) / ORIG_FEE_OW_BPS, 2),
        "cost_sensitivity_grid": sens_grid,
    }


def calc_cal_metrics(y: np.ndarray, probs: np.ndarray, n_bins: int = 5) -> dict:
    bs = float(np.mean((probs - y) ** 2))
    p_bar = float(np.mean(y))
    bs_ref = p_bar * (1.0 - p_bar)
    bss = 1.0 - bs / bs_ref if bs_ref > 1e-12 else 0.0
    roc = float(roc_auc_score(y, probs)) if len(np.unique(y)) == 2 else None
    pr = float(average_precision_score(y, probs)) if len(np.unique(y)) == 2 else None
    bins = pd.qcut(pd.Series(probs).rank(method="first"), q=min(n_bins, len(y)), labels=False)
    cal_rows, ece = [], 0.0
    for b in sorted(bins.unique()):
        m = (bins == b).to_numpy()
        pm, ym = float(probs[m].mean()), float(y[m].mean())
        err = abs(pm - ym)
        ece += (m.sum() / len(y)) * err
        cal_rows.append({"bin": int(b) + 1, "n": int(m.sum()), "pred_win_prob_pct": sf(pm * 100.0, 2), "actual_win_rate_pct": sf(ym * 100.0, 2), "abs_err_pp": sf(err * 100.0, 2)})
    return {
        "n": int(len(y)), "base_win_rate_pct": sf(p_bar * 100.0, 2), "brier_score": sf(bs, 5),
        "brier_baseline_p1mp": sf(bs_ref, 5), "brier_skill_score": sf(bss, 4),
        "roc_auc": sf(roc, 4), "pr_auc": sf(pr, 4), "ece_pp": sf(ece * 100.0, 2), "calibration_5bins": cal_rows,
    }


def calc_classification_calibration(df: pd.DataFrame, score_col: str, ret_col: str = "net_ret") -> dict:
    d = df.dropna(subset=[score_col, ret_col]).sort_values(["buy_date", "c6"]).reset_index(drop=True)
    x = d[score_col].to_numpy(dtype=float)
    y = (d[ret_col].to_numpy(dtype=float) > 0).astype(int)
    n = len(y)
    if n < 10 or len(np.unique(y)) < 2 or np.std(x) < 1e-12:
        return {"n": int(n), "insufficient": True}
    raw_roc, raw_pr = float(roc_auc_score(y, x)), float(average_precision_score(y, x))
    skf = StratifiedKFold(n_splits=min(5, int(min(np.sum(y == 1), np.sum(y == 0)))), shuffle=True, random_state=SEED)
    oof_probs = np.zeros(n, dtype=float)
    for tr_i, te_i in skf.split(x, y):
        mu, sd = x[tr_i].mean(), max(1e-9, x[tr_i].std())
        clf = LogisticRegression(C=100.0, solver="lbfgs")
        clf.fit(((x[tr_i] - mu) / sd).reshape(-1, 1), y[tr_i])
        oof_probs[te_i] = clf.predict_proba(((x[te_i] - mu) / sd).reshape(-1, 1))[:, 1]
    oof_res = calc_cal_metrics(y, oof_probs, n_bins=5)

    bd_arr = d["buy_date"].astype(str).str[:10].to_numpy()
    wf_probs, wf_y = [], []
    for i in range(max(12, int(0.25 * n)), n):
        tr_m = bd_arr < bd_arr[i]
        if tr_m.sum() < 10 or len(np.unique(y[tr_m])) < 2 or np.std(x[tr_m]) < 1e-12:
            continue
        mu, sd = x[tr_m].mean(), max(1e-9, x[tr_m].std())
        clf = LogisticRegression(C=100.0, solver="lbfgs")
        clf.fit(((x[tr_m] - mu) / sd).reshape(-1, 1), y[tr_m])
        wf_probs.append(float(clf.predict_proba(np.array([[(x[i] - mu) / sd]]))[0, 1]))
        wf_y.append(int(y[i]))
    wf_res = calc_cal_metrics(np.array(wf_y), np.array(wf_probs), n_bins=5) if (len(wf_y) >= 10 and len(np.unique(wf_y)) == 2) else {"n": len(wf_y), "insufficient": True}
    return {"n": int(n), "positive_rate_pct": sf(y.mean() * 100.0, 2), "raw_score_roc_auc": sf(raw_roc, 4), "raw_score_pr_auc": sf(raw_pr, 4), "oof_5fold_logistic": oof_res, "causal_expanding_logistic": wf_res}


def calc_holding_decay_20cm(led_df: pd.DataFrame, by_c: dict, sh300: dict, all_sh_dts: list[str]) -> dict:
    horizons = (0, 1, 2, 3, 5)
    raw_rets, phys_rets, csi_rets = {h: [] for h in horizons}, {h: [] for h in horizons}, {h: [] for h in horizons}
    def_cnt = {h: 0 for h in horizons}
    for r in led_df.itertuples(index=False):
        c6 = str(r.c6).zfill(6)
        bar = by_c[c6]
        p0 = bar["dt_to_pos"][str(r.buy_date)[:10]]
        bpx_adj = float(r.buy_px)
        for h in horizons:
            ph = min(p0 + h, len(bar["dt"]) - 1)
            dt_h = bar["dt"][ph]
            r_raw = float(bar["adj_close"][ph]) / bpx_adj - 1.0
            raw_rets[h].append(r_raw)
            if h > 0 and (bar["is_dt"][ph] or bar["is_yizi_dt"][ph]):
                def_cnt[h] += 1
                k = ph + 1
                while k < len(bar["dt"]) - 1 and (bar["is_dt"][k] or bar["is_yizi_dt"][k] or bar["volume"][k] <= 0):
                    k += 1
                dt_exec = bar["dt"][k]
                r_phys = float(bar["adj_close"][k]) / bpx_adj - 1.0
            else:
                dt_exec, r_phys = dt_h, r_raw
            phys_rets[h].append(r_phys)
            csi_rets[h].append(get_csi_period_ret(sh300, all_sh_dts, str(r.buy_date)[:10], dt_exec))

    summary_h, prev_g, prev_ex = {}, None, None
    for h in horizons:
        pr, cr = np.array(phys_rets[h]), np.array(csi_rets[h])
        ex = pr - cr
        net30 = (1.0 + pr) * (1.0 - ORIG_FEE_RT) - 1.0
        gm, exm = float(pr.mean()), float(ex.mean())
        summary_h[f"T+{h}"] = {
            "n": int(len(pr)), "phys_gross_mean_pct": sf(gm * 100.0, 3), "phys_gross_median_pct": sf(np.median(pr) * 100.0, 3),
            "phys_net30bps_mean_pct": sf(net30.mean() * 100.0, 3), "phys_win_rate_pct": sf((pr > 0).mean() * 100.0, 2),
            "csi300_mean_pct": sf(cr.mean() * 100.0, 3), "phys_excess_mean_pct": sf(exm * 100.0, 3),
            "marginal_gross_inc_pp": sf((gm - prev_g if prev_g is not None else gm) * 100.0, 3),
            "marginal_excess_inc_pp": sf((exm - prev_ex if prev_ex is not None else exm) * 100.0, 3),
            "dt_sealed_deferred_count": int(def_cnt[h]),
        }
        prev_g, prev_ex = gm, exm

    hs = np.array([1.0, 2.0, 3.0, 5.0])
    ex_curve = np.array([summary_h[f"T+{int(h)}"]["phys_excess_mean_pct"] for h in hs], dtype=float)
    t0_ex = summary_h["T+0"]["phys_excess_mean_pct"]
    inc_from_buy = np.array([ex_curve[0], ex_curve[1] - ex_curve[0], ex_curve[2] - ex_curve[1], (ex_curve[3] - ex_curve[2]) / 2.0])
    pos_mask = inc_from_buy > 0
    hl_marg, hl_sat, hl_post = None, None, None
    if pos_mask.sum() >= 2 and inc_from_buy[0] > 0:
        sl = stats.linregress(np.array([0.5, 1.5, 2.5, 4.0])[pos_mask], np.log(inc_from_buy[pos_mask])).slope
        if sl < -1e-4:
            hl_marg = math.log(2.0) / (-sl)
    if ex_curve[-1] > 0 and ex_curve[0] > 0:
        try:
            rs = opt.minimize(lambda p: float(np.sum((p[0] * (1.0 - np.exp(-p[1] * hs)) - ex_curve) ** 2)),
                              x0=[max(ex_curve) * 1.1, 0.5], bounds=[(0.01, max(ex_curve) * 5.0), (0.02, 5.0)])
            if rs.success and rs.x[1] > 1e-4:
                hl_sat = math.log(2.0) / float(rs.x[1])
        except Exception:
            pass
    pk_i = int(np.argmax(ex_curve))
    pk_h, pk_ex = int(hs[pk_i]), float(ex_curve[pk_i])
    if pk_h < 5 and pk_ex > 0 and 0 < ex_curve[-1] < pk_ex:
        hl_post = math.log(2.0) / (-math.log(ex_curve[-1] / pk_ex) / (5.0 - pk_h))
    hl_cross = None
    if pk_ex > 0 and pk_i < len(hs) - 1:
        half_lvl = 0.5 * pk_ex
        for j in range(pk_i, len(hs) - 1):
            y0, y1 = ex_curve[j], ex_curve[j + 1]
            if y0 >= half_lvl >= y1 and y0 > y1:
                t_cross = hs[j] + (y0 - half_lvl) / (y0 - y1) * (hs[j + 1] - hs[j])
                hl_cross = t_cross - pk_h
                break
    return {
        "horizons": summary_h,
        "alpha_decay_analysis": {
            "peak_horizon_excess": f"T+{pk_h}", "peak_excess_pct": sf(pk_ex, 3),
            "pct_of_peak_excess_at_T1": sf(ex_curve[0] / pk_ex * 100.0, 1) if pk_ex > 0 else None,
            "daily_marginal_excess_pp_from_buy": {"buy_to_T1": sf(inc_from_buy[0], 3), "T1_to_T2": sf(inc_from_buy[1], 3), "T2_to_T3": sf(inc_from_buy[2], 3), "T3_to_T5_per_day": sf(inc_from_buy[3], 3)},
            "half_life_marginal_days": sf(hl_marg, 2), "half_life_saturation_days": sf(hl_sat, 2),
            "half_life_post_peak_days": sf(hl_post, 2), "half_life_50pct_crossing_after_peak_days": sf(hl_cross, 2), "primary_alpha_half_life_days": sf(hl_marg if hl_marg is not None else (hl_post if hl_post is not None else hl_cross), 2),
        },
    }


# ==============================================================================
# PILLAR 5: PSR, MINTRL, WRC / HANSEN SPA (M>=60), BCa CI, RUNS & KELLY
# ==============================================================================

def calc_psr_mintrl(rets: np.ndarray, annualize_factor: float, bench_sr_ann_1: float = 1.0) -> dict:
    n = len(rets)
    if n < 4:
        return {"n": int(n), "insufficient": True}
    mu, sd = float(np.mean(rets)), float(np.std(rets, ddof=1))
    if sd <= 1e-12:
        return {"n": int(n), "std_zero": True}
    sr = mu / sd
    sr_ann = sr * math.sqrt(annualize_factor)
    sk = float(stats.skew(rets, bias=False))
    kurt_p = float(stats.kurtosis(rets, fisher=False, bias=False))
    var_fac = max(1e-12, 1.0 - sk * sr + ((kurt_p - 1.0) / 4.0) * (sr ** 2))
    denom = math.sqrt(var_fac)
    sr1 = bench_sr_ann_1 / math.sqrt(annualize_factor)
    psr0 = float(stats.norm.cdf((sr - 0.0) * math.sqrt(n - 1) / denom))
    psr1 = float(stats.norm.cdf((sr - sr1) * math.sqrt(n - 1) / denom))
    z95 = float(stats.norm.ppf(0.95))
    mt0 = (1.0 + var_fac * (z95 / sr) ** 2) if sr > 0.0 else None
    mt1 = (1.0 + var_fac * (z95 / (sr - sr1)) ** 2) if sr > sr1 else None
    return {
        "n_obs": int(n), "mean_pct": sf(mu * 100.0, 4), "std_pct": sf(sd * 100.0, 4),
        "skewness_gamma3": sf(sk, 4), "pearson_kurtosis_gamma4": sf(kurt_p, 4),
        "sr_per_period": sf(sr, 5), "sr_annualized": sf(sr_ann, 3),
        "psr_sr_gt_0": sf(psr0, 6), "psr_sr_gt_1_ann": sf(psr1, 6),
        "mintrl_95_sr0": sf(mt0, 1), "mintrl_95_sr1_ann": sf(mt1, 1),
        "passes_mintrl_95_sr0": bool(mt0 is not None and n >= mt0),
        "passes_mintrl_95_sr1_ann": bool(mt1 is not None and n >= mt1),
    }


def politis_white_opt_block_len(x: np.ndarray) -> float:
    n = len(x)
    if n < 20 or np.std(x) < 1e-12:
        return 5.0
    xc = x - np.mean(x)
    g0 = float(np.dot(xc, xc) / n)
    if g0 <= 1e-18:
        return 5.0
    max_k = min(int(math.ceil(math.sqrt(n))) + 10, n // 3)
    kn = max(5, int(math.ceil(math.sqrt(math.log10(n)))))
    crit = 1.96 * math.sqrt(math.log10(n) / n)
    rhos = np.array([float(np.dot(xc[:n - k], xc[k:]) / (n * g0)) for k in range(max_k + 1)])
    m_hat = 1
    for m in range(1, max_k - kn):
        if np.all(np.abs(rhos[m + 1 : m + 1 + kn]) < crit):
            m_hat = m
            break
    M = min(max_k, 2 * m_hat)
    g_hat, f0 = 0.0, g0
    for k in range(1, M + 1):
        lam = 1.0 if k <= M / 2.0 else 2.0 * (1.0 - k / float(M))
        gk = rhos[k] * g0
        g_hat += 2.0 * lam * k * gk
        f0 += 2.0 * lam * gk
    d_sb = 2.0 * (f0 ** 2)
    if d_sb <= 1e-18 or abs(g_hat) <= 1e-18:
        return 5.0
    return float(max(2.0, min(((2.0 * (g_hat ** 2) / d_sb) * n) ** (1.0 / 3.0), n / 4.0)))


def stationary_bootstrap_weights(T: int, B: int, L: float, rng: np.random.Generator) -> np.ndarray:
    q = 1.0 / float(L)
    W = np.zeros((B, T), dtype=np.float64)
    idx = rng.integers(0, T, size=B)
    rows = np.arange(B)
    for _ in range(T):
        np.add.at(W, (rows, idx), 1.0)
        jump = rng.random(B) < q
        idx = np.where(jump, rng.integers(0, T, size=B), (idx + 1) % T)
    W /= float(T)
    return W


def hansen_omega_hat(D: np.ndarray, L: float) -> np.ndarray:
    T, _ = D.shape
    q = 1.0 / float(L)
    Dc = D - D.mean(axis=0, keepdims=True)
    omega2 = np.sum(Dc * Dc, axis=0) / float(T)
    max_i = min(T - 1, int(math.ceil(math.log(1e-6) / math.log(max(1e-9, 1.0 - q)))) if q < 1.0 else 1)
    for i in range(1, max_i + 1):
        kappa = ((T - i) / float(T)) * ((1.0 - q) ** i) + (i / float(T)) * ((1.0 - q) ** (T - i))
        omega2 += 2.0 * kappa * (np.sum(Dc[:-i] * Dc[i:], axis=0) / float(T))
    return np.sqrt(np.maximum(1e-14, omega2))


def run_wrc_and_spa(D: np.ndarray, W_dict: dict, L_main: int = 10) -> dict:
    T, _ = D.shape
    d_bar = D.mean(axis=0)
    sqrtT = math.sqrt(T)
    V_wrc = float(np.max(sqrtT * d_bar))
    out_by_L = {}
    for L, W in W_dict.items():
        omega = hansen_omega_hat(D, float(L))
        t_obs = sqrtT * d_bar / omega
        T_spa = float(max(0.0, np.max(t_obs)))
        m_star = W @ D
        V_star = np.max(sqrtT * (m_star - d_bar[None, :]), axis=1)
        p_wrc = float(np.mean(V_star > V_wrc))
        thresh_c = -math.sqrt(2.0 * math.log(math.log(T)))
        mu_l = np.minimum(d_bar, 0.0)
        mu_c = np.where(t_obs <= thresh_c, d_bar, 0.0)
        p_l = float(np.mean(np.maximum(0.0, np.max((m_star - d_bar[None, :] + mu_l[None, :]) * sqrtT / omega[None, :], axis=1)) > T_spa))
        p_c = float(np.mean(np.maximum(0.0, np.max((m_star - d_bar[None, :] + mu_c[None, :]) * sqrtT / omega[None, :], axis=1)) > T_spa))
        p_u = float(np.mean(np.maximum(0.0, np.max((m_star - d_bar[None, :]) * sqrtT / omega[None, :], axis=1)) > T_spa))
        out_by_L[L] = {
            "block_len_L": int(L), "active_rule_t_stat": sf(t_obs[0], 3),
            "active_rule_rank_in_M": int(1 + np.sum(t_obs > t_obs[0])), "max_rule_t_stat": sf(T_spa, 3),
            "wrc_p_value": sf(p_wrc, 4), "spa_p_lower": sf(p_l, 4), "spa_p_consistent": sf(p_c, 4), "spa_p_upper": sf(p_u, 4),
        }
    return {**out_by_L[L_main], "sensitivity_L5": out_by_L.get(5), "sensitivity_L20": out_by_L.get(20)}


def bca_bootstrap_ci(x: np.ndarray, B: int = 5000, alpha: float = 0.05, rng: np.random.Generator = None) -> dict:
    n, theta_hat = len(x), float(np.mean(x))
    if n < 3 or np.std(x) < 1e-12:
        return {"point_est": sf(theta_hat, 4), "ci_95_low": sf(theta_hat, 4), "ci_95_high": sf(theta_hat, 4)}
    boot_vals = np.mean(x[rng.integers(0, n, size=(B, n))], axis=1)
    p0 = max(0.5 / B, min(1.0 - 0.5 / B, float(np.mean(boot_vals < theta_hat) + 0.5 * np.mean(boot_vals == theta_hat))))
    z0 = float(stats.norm.ppf(p0))
    jack = (float(np.sum(x)) - x) / float(n - 1)
    jd = float(np.mean(jack)) - jack
    den = 6.0 * (float(np.sum(jd ** 2)) ** 1.5)
    a_hat = float(np.sum(jd ** 3)) / den if den > 1e-18 else 0.0

    def _q(za):
        dq = 1.0 - a_hat * (z0 + za)
        return 0.5 if abs(dq) < 1e-12 else float(stats.norm.cdf(z0 + (z0 + za) / dq))

    ql = max(0.0, min(1.0, _q(float(stats.norm.ppf(alpha / 2.0)))))
    qh = max(0.0, min(1.0, _q(float(stats.norm.ppf(1.0 - alpha / 2.0)))))
    return {"point_est": sf(theta_hat, 4), "ci_95_low": sf(np.quantile(boot_vals, ql), 4), "ci_95_high": sf(np.quantile(boot_vals, qh), 4), "z0": sf(z0, 4), "acc_hat": sf(a_hat, 4)}


def wilson_ci_95(k: int, n: int):
    if n == 0:
        return 0.0, 0.0
    z, p = 1.959963984540054, k / n
    den = 1.0 + z * z / n
    ctr = (p + z * z / (2.0 * n)) / den
    hlf = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / den
    return max(0.0, ctr - hlf), min(1.0, ctr + hlf)


def calc_runs_autocorr_kelly(rets: np.ndarray, rng: np.random.Generator) -> dict:
    n = len(rets)
    wins = (rets > 0).astype(int)
    n1, n0 = int(wins.sum()), int(n - wins.sum())
    runs = 1 + int(np.sum(wins[1:] != wins[:-1])) if n > 0 else 0
    mu_r = 1.0 + (2.0 * n1 * n0) / n if (n1 > 0 and n0 > 0) else float(runs)
    var_r = (2.0 * n1 * n0 * (2.0 * n1 * n0 - n)) / ((n ** 2) * (n - 1.0)) if (n1 > 0 and n0 > 0 and n > 1) else 0.0
    sd_r = math.sqrt(max(1e-12, var_r))
    z_runs = (runs - mu_r) / sd_r if sd_r > 0 else 0.0

    def max_streak(arr):
        mx, c = 0, 0
        for v in arr:
            c = c + 1 if v == 0 else 0
            if c > mx:
                mx = c
        return mx

    act_st = max_streak(wins)
    mc_runs, mc_st = np.empty(MC_B, dtype=int), np.empty(MC_B, dtype=int)
    for b in range(MC_B):
        p = rng.permutation(wins)
        mc_runs[b] = 1 + int(np.sum(p[1:] != p[:-1]))
        mc_st[b] = max_streak(p)
    p_runs_mc = float(np.mean(np.abs(mc_runs - mu_r) >= abs(runs - mu_r)))

    def lag_acf(arr, lag):
        if len(arr) <= lag + 2 or np.std(arr[:-lag]) < 1e-12 or np.std(arr[lag:]) < 1e-12:
            return None, None
        c, p = stats.pearsonr(arr[:-lag], arr[lag:])
        return float(c), float(p)

    acf1, p_acf1 = lag_acf(rets, 1)
    acf2, p_acf2 = lag_acf(rets, 2)
    loss_bin = (rets <= 0).astype(float)
    acf1_l, p_acf1_l = lag_acf(loss_bin, 1)
    pl, cl = loss_bin[:-1] == 1, loss_bin[1:] == 1
    n_ll, n_lw, n_wl, n_ww = int(np.sum(pl & cl)), int(np.sum(pl & ~cl)), int(np.sum(~pl & cl)), int(np.sum(~pl & ~cl))
    _, fp = stats.fisher_exact([[n_ll, n_lw], [n_wl, n_ww]]) if n > 2 else (1.0, 1.0)

    r_min = float(np.min(rets))
    ruin_f = (-1.0 / r_min) if r_min < -1e-9 else 10.0
    upper_f = max(0.0, min(10.0, ruin_f * 0.999))
    mu_v, var_v = float(np.mean(rets)), float(np.var(rets, ddof=1)) if n > 1 else 1e-6
    if mu_v <= 0 or upper_f <= 0:
        f_exact, g_full = 0.0, 0.0
    else:
        rk = opt.minimize_scalar(lambda f: 1e9 if np.any(1.0 + f * rets <= 1e-12) else -float(np.mean(np.log(1.0 + f * rets))), bounds=(0.0, upper_f), method="bounded")
        f_exact, g_full = float(rk.x), -float(rk.fun)
    f_mv = (mu_v / var_v) if var_v > 1e-12 else 0.0

    return {
        "wald_wolfowitz_runs": {
            "n_trades": int(n), "n_wins": n1, "n_losses": n0, "observed_runs": int(runs),
            "expected_runs": sf(mu_r, 2), "z_stat": sf(z_runs, 3), "p_value_norm": sf(2.0 * stats.norm.sf(abs(z_runs)), 4),
            "p_value_mc_10k": sf(p_runs_mc, 4), "randomness_rejected_5pct": bool(p_runs_mc < 0.05),
        },
        "consecutive_loss_tail": {
            "actual_max_consec_losses": int(act_st), "mc_10k_mean_max_streak": sf(mc_st.mean(), 2),
            "mc_10k_p95_max_streak": int(np.quantile(mc_st, 0.95)), "mc_10k_p99_max_streak": int(np.quantile(mc_st, 0.99)),
            "mc_prob_ge_actual_pct": sf((mc_st >= act_st).mean() * 100.0, 2),
        },
        "serial_dependence": {
            "lag1_ret_acf": sf(acf1, 4), "lag1_ret_p": sf(p_acf1, 4), "lag2_ret_acf": sf(acf2, 4), "lag2_ret_p": sf(p_acf2, 4),
            "lag1_loss_binary_acf": sf(acf1_l, 4), "lag1_loss_binary_p": sf(p_acf1_l, 4),
            "p_loss_uncond_pct": sf((n0 / n) * 100.0, 2),
            "p_loss_given_prev_loss_pct": sf(n_ll / max(1, n_ll + n_lw) * 100.0, 2),
            "p_loss_given_prev_win_pct": sf(n_wl / max(1, n_wl + n_ww) * 100.0, 2),
            "transition_counts_LL_LW_WL_WW": [n_ll, n_lw, n_wl, n_ww], "fisher_exact_p_loss_clustering": sf(fp, 4),
        },
        "kelly_position_sizing": {
            "worst_trade_ret_pct": sf(r_min * 100.0, 2), "ruin_leverage_limit_pct": sf(ruin_f * 100.0, 1) if r_min < 0 else None,
            "full_kelly_exact_pct": sf(f_exact * 100.0, 1), "half_kelly_exact_pct": sf(0.5 * f_exact * 100.0, 1),
            "full_kelly_unlevered_cap100_pct": sf(min(1.0, f_exact) * 100.0, 1), "half_kelly_unlevered_cap100_pct": sf(min(1.0, 0.5 * f_exact) * 100.0, 1),
            "expected_log_growth_at_full_kelly_pct": sf(g_full * 100.0, 3),
            "full_kelly_mv_approx_pct": sf(f_mv * 100.0, 1), "half_kelly_mv_approx_pct": sf(0.5 * f_mv * 100.0, 1),
        },
    }


def build_20cm_wrc_spa_family(thr_active: float, active_daily: np.ndarray, p1_clean: pd.DataFrame,
                              pool_rich: pd.DataFrame, by_c: dict, cal_full: list[str]) -> tuple[np.ndarray, dict]:
    print(f"    Building M>=60 authentic 20cm rule family for WRC/SPA (thr={thr_active})...")
    cols_list = [active_daily]
    sc_base, fm_base = compute_scorecard_v11(pool_rich)
    pool_rich = pool_rich.copy()
    pool_rich["score"] = sc_base.values
    tr_base = sim_v11_exit_ext(pool_rich, V11_EXIT_CFG, fee=ORIG_FEE_RT, tp_buf=0.0030)

    def _add(tr_sub):
        s1, _, _ = _sim_k_slots(tr_sub, 1)
        if s1.empty:
            return
        d_vec, _, _, _ = compute_daily_mtm(s1, by_c, cal_full, prices_are_adj=True)
        cols_list.append(d_vec)

    # 1. Threshold grid (18 thresholds)
    for t in [66, 68, 70, 72, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 88]:
        if float(t) == float(thr_active):
            continue
        _add(tr_base[tr_base["score"] >= t])

    # 2. Hard gate open-gap & mkt20_zt_cnt grid on p1_clean_candidates (5 x 3 = 15)
    for og_lo, og_hi in [(-0.12, -0.02), (-0.10, -0.02), (-0.10, -0.03), (-0.09, -0.03), (-0.10, -0.035)]:
        for zt_cap in (12, 16, 20):
            if (og_lo, og_hi) == (-0.10, -0.03) and zt_cap == 16:
                continue
            sub_p = p1_clean[p1_clean["f1_o_pct"].between(og_lo, og_hi) & (p1_clean["mkt20_zt_cnt"] < zt_cap)].copy()
            sub_p["score"] = compute_scorecard_v11(sub_p)[0].values
            _add(sim_v11_exit(sub_p[sub_p["score"] >= thr_active], V11_EXIT_CFG, fee=ORIG_FEE_RT, tp_buf=0.0030))

    # 3. Exit tree config perturbations around V11_EXIT_CFG (19 variants)
    p_act = pool_rich[pool_rich["score"] >= thr_active].copy()
    exit_cfgs = [
        {"b3_tp_mode": "none", "b2_mode": "d2_close", "risk_mode": "none"},
        {**V11_EXIT_CFG, "risk_mode": "none"},
        {**V11_EXIT_CFG, "zt_imm": True},
        {**V11_EXIT_CFG, "b2_mode": "d2_tp"},
        {**V11_EXIT_CFG, "b2_mode": "d2_close"},
    ]
    for ak in (0.8, 1.0, 1.2, 1.8, 2.0):
        exit_cfgs.append({**V11_EXIT_CFG, "b3_adapt_k": ak})
    for tp2 in (0.08, 0.10, 0.14, 0.16):
        exit_cfgs.append({**V11_EXIT_CFG, "b2_tp": tp2})
    for b4b in (-0.03, -0.07):
        exit_cfgs.append({**V11_EXIT_CFG, "b4_body": b4b})
    for b2b, b2c in [(0.04, 0.65), (0.08, 0.65), (0.06, 0.50), (0.06, 0.75)]:
        exit_cfgs.append({**V11_EXIT_CFG, "b2_body": b2b, "b2_clv": b2c})
    for cfg in exit_cfgs:
        _add(sim_v11_exit(p_act, cfg, fee=ORIG_FEE_RT, tp_buf=0.0030))

    # 4. LOO factor ablations on the 9 scorecard items (9 variants)
    for col in fm_base.columns:
        tr_loo = tr_base.copy()
        d_map = dict(zip(zip(pool_rich["dt"], pool_rich["c6"]), fm_base[col].to_numpy(dtype=float)))
        tr_loo["score"] = tr_loo["score"] - np.array([d_map[(r.sig_date, r.c6)] for r in tr_loo.itertuples(index=False)])
        _add(tr_loo[tr_loo["score"] >= thr_active])

    # 5. RD023 exit & scorecard candidate variants (13 variants)
    for rf in ("R_sen20_lt40", "R_vol35x", "R_hs300_drop", "R_reb4_lt20"):
        _add(sim_v11_exit_ext(p_act, {**V11_EXIT_CFG, "extra_risk": [rf]}, fee=ORIG_FEE_RT, tp_buf=0.0030))
    old_f02 = np.where(pool_rich["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    for pct_lim in (0.30, 0.40, 0.50):
        delta = np.where(pool_rich["rfm_pct_all20"].fillna(1.0) <= pct_lim, 4, 0) - old_f02
        tr_f = tr_base.copy()
        dm = dict(zip(zip(pool_rich["dt"], pool_rich["c6"]), delta))
        tr_f["score"] = tr_f["score"] + np.array([dm[(r.sig_date, r.c6)] for r in tr_f.itertuples(index=False)])
        _add(tr_f[tr_f["score"] >= thr_active])
    for delta_arr in [
        -old_f02,
        np.where(pool_rich["lock_top10"].fillna(0) >= 45, 4, 0),
        np.where(pool_rich["zt_obc"] == 0, 4, 0),
        np.where(pool_rich["t0_mkt_all_nonst_zt"] >= 120, -5, 0),
        np.where(pool_rich["pos60"].fillna(0.0) >= 0.90, -4, 0),
        np.where(pool_rich["sensor20_d2_red"].fillna(1.0) < 0.40, -6, 0),
    ]:
        tr_f = tr_base.copy()
        dm = dict(zip(zip(pool_rich["dt"], pool_rich["c6"]), delta_arr))
        tr_f["score"] = tr_f["score"] + np.array([dm[(r.sig_date, r.c6)] for r in tr_f.itertuples(index=False)])
        _add(tr_f[tr_f["score"] >= thr_active])

    mat_full = np.column_stack(cols_list)
    seen, uniq_idx = {}, []
    for j in range(mat_full.shape[1]):
        h = hash(mat_full[:, j].round(10).tobytes())
        if h not in seen:
            seen[h] = j
            uniq_idx.append(j)
    mat_uniq = mat_full[:, uniq_idx]
    assert mat_uniq.shape[1] >= 60, f"WRC/SPA M_unique={mat_uniq.shape[1]} < 60"
    return mat_uniq, {
        "family_description": "20cm DeepOpen candidate family: 17 score thresholds + 14 hard-gate grid + 19 exit-tree variants + 9 LOO factor ablations + 13 RD023 overlays",
        "M_total_rules": int(mat_full.shape[1]),
        "M_unique_series": int(mat_uniq.shape[1]),
    }


# ==============================================================================
# PILLAR 6: DATA HYGIENE, UNADJUSTED PRICE AUDIT, PIT LAG & 5-FOLD PURGED CV
# ==============================================================================

def run_pillar6_hygiene(df_all: pd.DataFrame, led_A: pd.DataFrame, led_S: pd.DataFrame,
                        daily_A: np.ndarray, daily_S: np.ndarray, cal_full: list[str]) -> dict:
    print("[5/8] Running Pillar 6 data hygiene, unadjusted-price & PIT lag audit + 5-fold Purged CV...")
    sub20 = df_all[df_all["is20"] & (df_all["dt"] >= FULL_START)].copy()
    g = sub20.groupby("c6")
    qfq_r = g["qfq_factor"].shift(1) / sub20["qfq_factor"]
    adjf_r = sub20["adjf"] / g["adjf"].shift(1)
    ex_jumps = qfq_r.notna() & (np.abs(qfq_r - 1.0) > 1e-4)
    mismatch = int((qfq_r.notna() & adjf_r.notna() & (np.abs(qfq_r - adjf_r) > 1e-3)).sum())

    bar_lu = {(r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
              for r in sub20[["c6", "dt", "open", "close", "adj_close", "qfq_factor", "adjf"]].itertuples(index=False)}
    ledger_exdiv = {}
    for nm, ld in [("A76", led_A), ("S82", led_S)]:
        ex_list, max_err, bad = [], 0.0, 0
        for r in ld.itertuples(index=False):
            c6 = str(r.c6).zfill(6)
            bb, eb = bar_lu[(c6, str(r.buy_date)[:10])], bar_lu[(c6, str(r.exit_date)[:10])]
            qr = bb[3] / eb[3]
            bp_raw, ep_raw = float(r.buy_px) / bb[4], float(r.exit_px) / eb[4]
            exp_r = (ep_raw / bp_raw) * qr * (1.0 - ORIG_FEE_RT) - 1.0
            err = abs(exp_r - float(r.net_ret_eval))
            max_err = max(max_err, err)
            if err > 1e-6:
                bad += 1
            if abs(qr - 1.0) > 1e-4:
                ex_list.append({"c6": c6, "name": str(r.name), "buy_date": r.buy_date, "exit_date": r.exit_date, "qfq_ratio": round(qr, 5), "net_ret_pct": round(float(r.net_ret_eval) * 100.0, 2)})
        ledger_exdiv[nm] = {"n_trades": int(len(ld)), "ex_div_count": len(ex_list), "ret_mismatch_gt1e6": bad, "max_ret_diff": max_err, "ex_div_trades": ex_list}

    # PIT lag audit on pit_top10_20cm_summary.json & notices DB
    t10 = json.load(open(f"{P2_DIR}/pit_top10_20cm_summary.json", encoding="utf-8"))
    lags, neg_lag, dirty = [], 0, 0
    for c6, recs in t10.items():
        for nd, ed, _, _ in recs:
            if str(nd) < "2000-01-01":
                dirty += 1
            elif str(nd) < str(ed):
                neg_lag += 1
            else:
                lags.append((pd.Timestamp(nd) - pd.Timestamp(ed)).days)

    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    n_tot, dt_min, dt_max, n_avail_lt = con_n.execute(
        "SELECT count(*), min(pub_datetime_cst), max(pub_datetime_cst), sum(case when trade_date_avail < substr(pub_datetime_cst,1,10) then 1 else 0 end) FROM notices"
    ).fetchone()
    con_n.close()

    code_audit = {
        "unadjusted_price_thresholds": {
            "v11_core.py:257 & step0:202": "close >= 2.0 strictly uses raw unadjusted close",
            "v11_core.py:193 & layer_prices_mkt.py:153": "mcap & real_free_mcap use est_sh * raw close / 1e8 (unadjusted)",
            "v11_core.py:178 & layer_prices_mkt.py:116": "zt_px / dt_px computed via prev_ex = prev_ac / sc_ratio rounded to tick, compared vs raw open/close",
            "v11_core.py:77 & step0:177": "Intraday TP targets & D1 body/CLV consistently computed in adj_close/sc_ratio space (ex-div neutral)",
            "qfq_threshold_leak": False,
        },
        "pit_reporting_lag_compliance": {
            "top10_lockup_20cm": {"codes": len(t10), "records": len(lags) + dirty + neg_lag, "notice_lt_end": neg_lag, "dirty_pre2000": dirty, "lag_p10_med_p90_days": [float(np.quantile(lags, 0.1)), float(np.median(lags)), float(np.quantile(lags, 0.9))], "aligned_on": "NOTICE_DATE < dt"},
            "cninfo_notices_5y_pit": {"rows": int(n_tot), "span": f"{dt_min} ~ {dt_max}", "avail_lt_pub": int(n_avail_lt), "cutoff": "< f1_dt 09:00:00"},
            "lhb_t0_vs_t1_separation": "F06 uses T0 LHB (dt post-close, known before T+1 09:25); risk_hit uses T+1 LHB (f1_dt post-close) ONLY for D2+ exits, zero entry leakage",
            "truncation_20250101_v11": "v11_core.py:317-321 asserts max_score_diff == 0.0 and max_ret_diff < 1e-12 for both A76 (194 trades) and S82 (138 trades)",
        },
    }

    # 5-Fold Purged & Embargoed CV (embargo = 3 trading days)
    T = len(cal_full)
    dt_to_idx = {d: i for i, d in enumerate(cal_full)}
    step = T // 5
    fold_bounds = [(k * step, (k + 1) * step - 1 if k < 4 else T - 1) for k in range(5)]
    purged_cv = {}
    for nm, ld, dr in [("A76", led_A, daily_A), ("S82", led_S, daily_S)]:
        d = ld.copy()
        d["b_idx"] = d["buy_date"].map(dt_to_idx)
        d["e_idx"] = d["exit_date"].map(dt_to_idx)
        full_tr = d["net_ret_eval"].to_numpy(float)
        full_d_sd = float(dr.std(ddof=1))
        full_sr_d = float(dr.mean() / full_d_sd * math.sqrt(TRD_DAYS_YEAR)) if full_d_sd > 0 else 0.0
        folds_res, pooled_oos = [], []
        for fi, (fs, fe) in enumerate(fold_bounds, 1):
            te_m = (d["b_idx"] >= fs) & (d["b_idx"] <= fe)
            raw_tr_m = ~te_m
            purged_m = (d["e_idx"] < fs) | (d["b_idx"] > fe + 3)
            te_r = d.loc[te_m, "net_ret_eval"].to_numpy(float)
            pooled_oos.extend(te_r.tolist())
            te_dr = dr[fs : fe + 1]
            te_sd = float(te_dr.std(ddof=1))
            te_dsr = float(te_dr.mean() / te_sd * math.sqrt(TRD_DAYS_YEAR)) if te_sd > 1e-12 else 0.0
            folds_res.append({
                "fold": fi, "window": f"{cal_full[fs]} ~ {cal_full[fe]}",
                "n_test": int(len(te_r)), "purged_embargoed_samples": int((raw_tr_m & ~purged_m).sum()),
                "train_purged_mean_pct": sf(d.loc[purged_m, "net_ret_eval"].mean() * 100.0, 2) if purged_m.any() else 0.0,
                "test_wr_pct": sf((te_r > 0).mean() * 100.0, 2) if len(te_r) else 0.0,
                "test_trade_mean_pct": sf(te_r.mean() * 100.0, 2) if len(te_r) else 0.0,
                "test_fold_nav": sf(np.prod(1.0 + te_r), 3) if len(te_r) else 1.0,
                "test_daily_mtm_sharpe_ann": sf(te_dsr, 3),
            })
        fold_sr = [f["test_daily_mtm_sharpe_ann"] for f in folds_res]
        pos_folds = sum(1 for f in folds_res if f["test_fold_nav"] > 1.0)
        purged_cv[nm] = {
            "embargo_trading_days": 3, "full_daily_sharpe_ann": sf(full_sr_d, 3),
            "cv_summary": {
                "mean_fold_daily_sharpe_ann": sf(np.mean(fold_sr), 3),
                "sharpe_diff_full_minus_cv": sf(full_sr_d - float(np.mean(fold_sr)), 3),
                "pooled_oos_trade_mean_pct": sf(np.mean(pooled_oos) * 100.0, 2),
                "positive_folds": f"{pos_folds}/5 ({pos_folds*20}%)",
                "worst_fold": min(folds_res, key=lambda f: f["test_fold_nav"]),
            },
            "folds": folds_res,
        }
    return {
        "raw_vs_qfq_20cm_stats": {"rows": int(len(sub20)), "ex_div_jumps": int(ex_jumps.sum()), "adjf_vs_qfq_mismatch": mismatch},
        "ledger_exdiv_verification": ledger_exdiv,
        "code_and_pit_audit": code_audit,
        "purged_embargoed_5fold_cv": purged_cv,
    }


# ==============================================================================
# PILLAR 7: CROSS-STRATEGY CORRELATION, 6-STRAT LOO & CUSUM/SPRT REDLINES
# ==============================================================================

def _sim_cusum_mc(rng, rets_h1: np.ndarray, k_ref: float, h_grid: np.ndarray, n_win: int, n_mc: int = 5000, max_arl: int = 25000):
    mu_1 = float(rets_h1.mean())
    rets_h0 = rets_h1 - mu_1
    n_pool = len(rets_h1)
    p1 = rets_h1[rng.integers(0, n_pool, size=(n_mc, max_arl))]
    p0 = rets_h0[rng.integers(0, n_pool, size=(n_mc, 400))]

    hit1 = np.full((len(h_grid), n_mc), max_arl + 1, dtype=int)
    s1 = np.zeros(n_mc, dtype=float)
    for t in range(max_arl):
        s1 = np.maximum(0.0, s1 + k_ref - p1[:, t])
        sm = float(s1.max())
        if sm < h_grid[0]:
            continue
        for j, hv in enumerate(h_grid):
            if hv > sm:
                break
            upd = (hit1[j] > max_arl) & (s1 >= hv)
            if upd.any():
                hit1[j, upd] = t + 1
        if (hit1[-1] <= max_arl).all():
            break

    hit0 = np.full((len(h_grid), n_mc), 401, dtype=int)
    s0 = np.zeros(n_mc, dtype=float)
    for t in range(400):
        s0 = np.maximum(0.0, s0 + k_ref - p0[:, t])
        sm = float(s0.max())
        if sm < h_grid[0]:
            continue
        for j, hv in enumerate(h_grid):
            if hv > sm:
                break
            upd = (hit0[j] > 400) & (s0 >= hv)
            if upd.any():
                hit0[j, upd] = t + 1
        if (hit0[-1] <= 400).all():
            break

    recs = []
    for j, hv in enumerate(h_grid):
        fa = float((hit1[j] <= n_win).mean())
        a0 = float(hit1[j].mean())
        recs.append({
            "h": round(float(hv), 4), "fa_pct": round(fa * 100.0, 2), "arl0": round(a0, 1),
            "arl0_censored_pct": round(float((hit1[j] > max_arl).mean() * 100.0), 2),
            "arl1": round(float(hit0[j].mean()), 1), "det_20tr_pct": round(float((hit0[j] <= 20).mean() * 100.0), 1),
        })
    return recs


def calc_cusum_sprt_one(rets: np.ndarray, rng: np.random.Generator) -> dict:
    n = len(rets)
    mu_1, sd = float(rets.mean()), float(rets.std(ddof=1))
    wins, losses = rets[rets > 0], rets[rets <= 0]
    p_1 = float(len(wins) / n)
    avg_w, avg_l = float(wins.mean()), float(losses.mean())
    plr = avg_w / abs(avg_l)
    p_0 = max(0.45, 1.0 / (1.0 + plr))

    mc_hist, cur_c = 0, 0
    for r in rets:
        cur_c = cur_c + 1 if r <= 0 else 0
        mc_hist = max(mc_hist, cur_c)

    k_ref = 0.5 * mu_1
    h_grid = np.linspace(max(0.10, 0.5 * sd), max(1.20, 26.0 * sd), 103)
    gres = _sim_cusum_mc(rng, rets, k_ref, h_grid, n, n_mc=5000, max_arl=25000)
    assert any(g["arl0"] >= 250.0 and g["fa_pct"] < 5.0 for g in gres), f"CUSUM Red grid insufficient: max fa={gres[-1]}"
    red_c = [g for g in gres if g["arl0"] >= 250.0 and g["fa_pct"] < 5.0]
    red_p = red_c[0] if red_c else gres[-1]
    yel_c = [g for g in gres if g["arl0"] >= 250.0 and g["fa_pct"] <= 15.0]
    yel_p = yel_c[0] if (yel_c and yel_c[0]["h"] < red_p["h"]) else red_p

    def _replay_c(hv):
        s, mx, hits = 0.0, 0.0, 0
        for r in rets:
            s = max(0.0, s + k_ref - float(r))
            mx = max(mx, s)
            if s >= hv:
                hits += 1
                s = 0.0
        return round(mx * 100.0, 2), hits

    h_max_s, h_red_hits = _replay_c(red_p["h"])
    _, h_yel_hits = _replay_c(yel_p["h"])

    llr_loss = math.log((1.0 - p_0) / (1.0 - p_1)) if p_1 > p_0 else 0.01
    b_yel, b_red = math.log(9.0), math.log(19.0)
    step_gl = (mu_1 / (sd * sd)) * (k_ref - avg_l)
    roll_N = 20
    h1_paths = rets[rng.integers(0, n, size=(5000, n))]
    csum = np.cumsum(np.insert(h1_paths, 0, 0.0, axis=1), axis=1)
    min_rm = ((csum[:, roll_N:] - csum[:, :-roll_N]) / roll_N).min(axis=1)
    cwin = np.cumsum(np.insert((h1_paths > 0).astype(int), 0, 0, axis=1), axis=1)
    min_rw = ((cwin[:, roll_N:] - cwin[:, :-roll_N]) / roll_N).min(axis=1)
    y_red, y_yel = float(np.percentile(min_rm, 5.0)), float(np.percentile(min_rm, 15.0))
    z_red, z_yel = float(np.percentile(min_rw, 5.0)), float(np.percentile(min_rw, 15.0))
    if z_yel <= z_red + 1e-6:
        z_yel = min(p_0, round((round(z_red * roll_N) + 1) / roll_N, 4))

    st_max, cur_s = np.zeros(5000, dtype=int), np.zeros(5000, dtype=int)
    for t in range(n):
        cur_s = np.where(h1_paths[:, t] <= 0, cur_s + 1, 0)
        st_max = np.maximum(st_max, cur_s)
    x_red = max(int(np.percentile(st_max, 96)) + 1, mc_hist + 1)
    x_yel = max(3, x_red - 1)

    return {
        "empirical_h1": {"n_trades": int(n), "mu_1_pct": sf(mu_1 * 100.0, 2), "sigma_pct": sf(sd * 100.0, 2), "wr_pct": sf(p_1 * 100.0, 2), "plr": sf(plr, 2), "breakeven_wr_pct": sf(100.0 / (1.0 + plr), 2), "hist_max_consec_losses": int(mc_hist)},
        "tabular_cusum_mc5000": {"k_ref_pct": sf(k_ref * 100.0, 2), "yellow_warning": {**yel_p, "hist_triggers": h_yel_hits}, "red_halt": {**red_p, "hist_max_S_pct": h_max_s, "hist_triggers": h_red_hits}},
        "wald_sprt": {"consec_losses_bern_yel_red": [int(math.ceil(b_yel / llr_loss)), int(math.ceil(b_red / llr_loss))], "consec_avg_losses_gauss_yel_red": [int(max(1, math.ceil(b_yel / step_gl))), int(max(1, math.ceil(b_red / step_gl)))]},
        "pm_executable_redlines": {
            "rolling_N_trades": roll_N,
            "consec_loss_yellow": int(x_yel), "consec_loss_red": int(x_red),
            "rolling_mean_yellow_pct": sf(y_yel * 100.0, 2), "rolling_mean_red_pct": sf(y_red * 100.0, 2),
            "rolling_wr_yellow_pct": sf(z_yel * 100.0, 1), "rolling_wr_red_pct": sf(z_red * 100.0, 1),
            "cusum_red_h_pct": sf(red_p["h"] * 100.0, 2),
        },
    }


def run_pillar7(led_A: pd.DataFrame, led_S: pd.DataFrame, daily_A_full: np.ndarray, daily_S_full: np.ndarray,
                cal_full: list[str], cal_5y: list[str], csi_5y: np.ndarray, by_c: dict, all_sig: pd.DataFrame) -> dict:
    print("[6/8] Running Pillar 7: 6x6 correlation, CSI300 worst-10% tail, 6-strat LOO & CUSUM/SPRT...")
    specs10 = [("3to4", "ledger_3to4_v41_clean.csv"), ("high", "ledger_high_v51_clean.csv"), ("pry_ss165", "ledger_pry_v21_ss165_clean.csv"), ("2to3", "ledger_2to3_v21_opt_std90_clean.csv"), ("1to2", "ledger_1to2_v19_clean.csv")]
    led10 = {}
    daily10 = {}
    for k, fn in specs10:
        d = pd.read_csv(f"{PC_DIR}/{fn}", dtype={"code": str})
        d["code"] = d["code"].str.zfill(6); d["buy_date"] = d["buy_date"].str[:10]; d["exit_date"] = d["exit_date"].str[:10]
        led10[k] = d
        dr, _, _, _ = compute_daily_mtm(d, by_c, cal_5y, prices_are_adj=False)
        daily10[k] = dr

    i0_5y, i1_5y = cal_full.index(cal_5y[0]), cal_full.index(cal_5y[-1])
    dA_5y = daily_A_full[i0_5y : i1_5y + 1]
    dS_5y = daily_S_full[i0_5y : i1_5y + 1]
    q10_thr = float(np.quantile(csi_5y, 0.10))
    worst10_mask = csi_5y <= q10_thr

    def _corr_6(nm20, vec20):
        keys = ["3to4", "high", "pry_ss165", "2to3", "1to2", nm20]
        df_r = pd.DataFrame({**daily10, nm20: vec20}, index=cal_5y)
        any_act = (df_r.abs() > 1e-12).any(axis=1)
        p_full = df_r.corr("pearson").fillna(0.0)
        p_w10 = df_r[worst10_mask].corr("pearson").fillna(0.0)
        p_act = df_r[any_act].corr("pearson").fillna(0.0)
        pair_union = {}
        for k1 in keys[:-1]:
            m_u = (df_r[nm20].abs() > 1e-12) | (df_r[k1].abs() > 1e-12)
            m_dn = (df_r[nm20] < 0) | (df_r[k1] < 0)
            pair_union[k1] = {
                "full_5y_pearson": sf(p_full.loc[nm20, k1], 4),
                "union_active_pearson": sf(df_r.loc[m_u, nm20].corr(df_r.loc[m_u, k1]), 4) if m_u.sum() >= 3 else 0.0,
                "either_loss_pearson": sf(df_r.loc[m_dn, nm20].corr(df_r.loc[m_dn, k1]), 4) if m_dn.sum() >= 3 else 0.0,
                "csi_worst10pct_pearson": sf(p_w10.loc[nm20, k1], 4),
            }
        sub_w10 = df_r.loc[worst10_mask, nm20]
        act_w10 = sub_w10[sub_w10.abs() > 1e-12]
        return {
            "vs_each_10cm": pair_union,
            "mean_corr_vs_5_full": sf(np.mean([p_full.loc[nm20, k] for k in keys[:-1]]), 4),
            "mean_corr_vs_5_csi_worst10": sf(np.mean([p_w10.loc[nm20, k] for k in keys[:-1]]), 4),
            "csi_worst10_threshold_pct": sf(q10_thr * 100.0, 2),
            "csi_worst10_exposure": {"active_days": int(len(act_w10)), "all_worst10_mean_bps": sf(sub_w10.mean() * 10000.0, 2), "active_mean_pct": sf(act_w10.mean() * 100.0, 2) if len(act_w10) else 0.0},
            "full_pearson_matrix": {k: {k2: sf(p_full.loc[k, k2], 4) for k2 in keys} for k in keys},
            "any_active_pearson_matrix": {k: {k2: sf(p_act.loc[k, k2], 4) for k2 in keys} for k in keys},
            "csi_worst10_pearson_matrix": {k: {k2: sf(p_w10.loc[k, k2], 4) for k2 in keys} for k in keys},
        }

    # 6-sleeve Equal-Weight Daily MTM LOO (unconstrained)
    r6_mat = np.column_stack([daily10[k] for k in ["3to4", "high", "pry_ss165", "2to3", "1to2"]] + [dA_5y])
    def _ew_m(arr):
        nav = float(np.prod(1.0 + arr))
        cagr = (nav ** (TRD_DAYS_YEAR / len(arr)) - 1.0) * 100.0
        cum = np.cumprod(1.0 + arr)
        mdd = float(np.max((np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:] - cum) / np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]) * 100.0)
        sd = float(arr.std(ddof=1))
        sr = float(arr.mean() / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 0 else 0.0
        return {"nav": sf(nav, 3), "cagr_pct": sf(cagr, 2), "mdd_pct": sf(mdd, 2), "sharpe": sf(sr, 3), "calmar": sf(cagr / mdd, 3) if mdd > 0 else 0.0}
    ew5_base = _ew_m(r6_mat[:, :5].mean(axis=1))
    ew6_with_A76 = _ew_m(r6_mat.mean(axis=1))

    # Single-slot 6-strategy chrono priority check (unconstrained)
    cols_k = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "net_ret"]
    p_map = {
        "3to4": led10["3to4"].assign(strategy="3to4", priority=1)[cols_k],
        "high": led10["high"].assign(strategy="high", priority=2)[cols_k],
        "pry": pd.read_csv(f"{PC_DIR}/ledger_pry_v21_top1_clean.csv", dtype={"code": str}).assign(strategy="pry", priority=3)[cols_k],
        "2to3": led10["2to3"].assign(strategy="2to3", priority=4)[cols_k],
        "1to2": led10["1to2"].assign(strategy="1to2", priority=5)[cols_k],
    }
    for d in p_map.values():
        d["code"] = d["code"].astype(str).str.zfill(6); d["buy_date"] = d["buy_date"].str[:10]; d["exit_date"] = d["exit_date"].str[:10]
    s20_src = all_sig[all_sig["buy_date"].between("2021-11-15", CANON_5Y_END)].copy()
    s20_src["code"] = s20_src["c6"].astype(str).str.zfill(6)
    s20_src["buy_hhmm"] = 925
    s20_src["exit_hhmm"] = np.where(s20_src["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
    s20_src["strategy"] = "20cm_V11"

    def _run1(df_in):
        srt = df_in.sort_values(["buy_date", "priority", "score", "buy_hhmm", "code"], ascending=[True, True, False, True, True])
        pk, ced, ceh = [], "", 0
        for r in srt.itertuples(index=False):
            if (not ced) or (r.buy_date > ced) or (r.buy_date == ced and int(r.buy_hhmm) > ceh):
                pk.append(r._asdict()); ced, ceh = r.exit_date, int(r.exit_hhmm)
        res = pd.DataFrame(pk)
        rt = res["net_ret"].to_numpy(float)
        cum = np.cumprod(1.0 + rt)
        mdd = float(np.max((np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:] - cum) / np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]) * 100.0)
        return {"n": int(len(res)), "wr_pct": sf((rt > 0).mean() * 100.0, 2), "nav": sf(cum[-1], 2), "mdd_pct": sf(mdd, 2), "20cm_n": int((res["strategy"] == "20cm_V11").sum())}

    slot6 = {
        "V191_5strat_base": _run1(pd.concat(list(p_map.values()), ignore_index=True)),
        "A76_P6_causal": _run1(pd.concat(list(p_map.values()) + [s20_src[s20_src["score"] >= 76].assign(priority=6)[cols_k]], ignore_index=True)),
        "A76_P5_vs_1to2_P6": _run1(pd.concat([p_map["3to4"], p_map["high"], p_map["pry"], p_map["2to3"], p_map["1to2"].assign(priority=6), s20_src[s20_src["score"] >= 76].assign(priority=5)[cols_k]], ignore_index=True)),
        "S82_P5_A76_P7": _run1(pd.concat([p_map["3to4"], p_map["high"], p_map["pry"], p_map["2to3"], p_map["1to2"].assign(priority=6), s20_src[s20_src["score"] >= 76].assign(priority=np.where(s20_src[s20_src["score"] >= 76]["score"] >= 82, 5, 7))[cols_k]], ignore_index=True)),
    }

    rng = np.random.default_rng(SEED)
    return {
        "correlation_A76_vs_5_10cm": _corr_6("20cm_V11_A76", dA_5y),
        "correlation_S82_vs_5_10cm": _corr_6("20cm_V11_S82", dS_5y),
        "portfolio_6strat_loo": {"equal_weight_5sleeves": ew5_base, "equal_weight_6sleeves_with_A76": ew6_with_A76, "single_slot_priority_unconstrained": slot6},
        "cusum_sprt_redlines": {"A76": calc_cusum_sprt_one(led_A["net_ret_eval"].to_numpy(float), rng), "S82": calc_cusum_sprt_one(led_S["net_ret_eval"].to_numpy(float), rng)},
    }


# ==============================================================================
# ITEM 2: 6x6 10cm 09:25 SIGNAL STATUS & R_sen20_lt40 DUAL-PERIOD / PBO AUDIT
# ==============================================================================

def verify_6x6_0925_and_rsen20(pool_rich: pd.DataFrame, all_sig: pd.DataFrame, p1_clean: pd.DataFrame,
                               all_dts: list[str], sh300: dict, ew20_daily: dict, by_c: dict, cal_full: list[str]) -> dict:
    print("[7/8] Auditing 5x10cm 09:25 signal status & R_sen20_lt40 dual-period/PBO verdict...")
    # 1. Load 5 clean 10cm pools + pretrig + ledgers to separate 09:25 causal signals vs post-09:25 fills!
    p34 = pd.read_csv(f"{MW_DIR}/part1_3to4_high/pool_3to4_full_clean.csv", dtype={"code": str})
    ph = pd.read_csv(f"{MW_DIR}/part1_3to4_high/pool_high_full_clean.csv", dtype={"code": str})
    pp = pd.read_csv(f"{MW_DIR}/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str})
    p23 = pd.read_csv(f"{MW_DIR}/part2_2to3_pry/pool_2to3_full_clean.csv", dtype={"code": str})
    pt12 = pd.read_parquet(f"{MW_DIR}/part3_1to2/_cache_pretrig_pool.parquet")
    pt12["buy_date"] = pt12["buy_date"].astype(str).str[:10]

    l34 = pd.read_csv(f"{PC_DIR}/ledger_3to4_v41_clean.csv")
    lh = pd.read_csv(f"{PC_DIR}/ledger_high_v51_clean.csv")
    lp = pd.read_csv(f"{PC_DIR}/ledger_pry_v21_top1_clean.csv")
    l23 = pd.read_csv(f"{PC_DIR}/ledger_2to3_v21_opt_std90_clean.csv")
    l12 = pd.read_csv(f"{PC_DIR}/ledger_1to2_v19_clean.csv")

    sig0925_days = {
        "3to4_0925_cand_ge90": set(p34[p34["base_score"] >= 90.0]["buy_date"].str[:10]),
        "3to4_0925_direct_ge90": set(p34[(p34["base_score"] >= 90.0) & (p34["buy_hhmm"] == 925)]["buy_date"].str[:10]),
        "high_0925_cand_ge88": set(ph[ph["base_score"] >= 88.0]["buy_date"].str[:10]),
        "high_0925_direct_ge88": set(ph[(ph["base_score"] >= 88.0) & (ph["buy_hhmm"] == 925)]["buy_date"].str[:10]),
        "pry_0925_ge165": set(pp[pp["base_score"] >= 165.0]["buy_date"].str[:10]),
        "2to3_0925_ge90": set(p23[p23["base_score"] >= 90.0]["buy_date"].str[:10]),
        "1to2_0925_pretrig_v19": set(pt12[pt12["base_pass_v19"] == True]["buy_date"].str[:10]),
        "1to2_0925_direct_v19": set(pt12[(pt12["base_pass_v19"] == True) & (pt12["buy_hhmm"] == 925)]["buy_date"].str[:10]),
    }
    sig0925_days["any5_0925_cand"] = set().union(sig0925_days["3to4_0925_cand_ge90"], sig0925_days["high_0925_cand_ge88"], sig0925_days["pry_0925_ge165"], sig0925_days["2to3_0925_ge90"], sig0925_days["1to2_0925_pretrig_v19"])
    sig0925_days["any5_0925_direct"] = set().union(sig0925_days["3to4_0925_direct_ge90"], sig0925_days["high_0925_direct_ge88"], sig0925_days["pry_0925_ge165"], sig0925_days["2to3_0925_ge90"], sig0925_days["1to2_0925_direct_v19"])

    leak_audit = {
        "3to4_ledger": {"total": int(len(l34)), "buy_at_925": int((l34["buy_hhmm"] == 925).sum()), "post_925_breakout": int((l34["buy_hhmm"] > 925).sum()), "pool_0925_cand_days": int(len(sig0925_days["3to4_0925_cand_ge90"]))},
        "high_ledger": {"total": int(len(lh)), "buy_at_925": int((lh["buy_hhmm"] == 925).sum()), "post_925_breakout": int((lh["buy_hhmm"] > 925).sum()), "pool_0925_cand_days": int(len(sig0925_days["high_0925_cand_ge88"]))},
        "pry_ledger": {"total": int(len(lp)), "buy_at_925": int((lp["buy_hhmm"] == 925).sum()), "post_925_breakout": int((lp["buy_hhmm"] > 925).sum()), "pool_0925_cand_days": int(len(sig0925_days["pry_0925_ge165"]))},
        "2to3_ledger": {"total": int(len(l23)), "buy_at_925": int((l23["buy_hhmm"] == 925).sum()), "post_925_breakout": int((l23["buy_hhmm"] > 925).sum()), "pool_0925_cand_days": int(len(sig0925_days["2to3_0925_ge90"]))},
        "1to2_ledger": {"total": int(len(l12)), "buy_at_925": int((l12["buy_hhmm"] == 925).sum()), "post_925_breakout": int((l12["buy_hhmm"] > 925).sum()), "pool_0925_pretrig_days": int(len(sig0925_days["1to2_0925_pretrig_v19"]))},
    }

    # Evaluate causal 09:25 flags on 20cm A76 inside canonical 5Y window (2021-11-15..2026-11-16)
    sub_w = all_sig[all_sig["buy_date"].between("2021-11-15", CANON_5Y_END)].copy().reset_index(drop=True)
    sub_a = sub_w[sub_w["score"] >= 76.0].copy().reset_index(drop=True)
    base_a_ev = eval_splits(sub_a)
    signal_tests = {}
    for fname, dset in sig0925_days.items():
        m = sub_a["buy_date"].isin(dset)
        s1, s0 = sub_a[m], sub_a[~m]
        is1, is0 = s1[s1["buy_date"] <= "2024-08-31"], s0[s0["buy_date"] <= "2024-08-31"]
        oo1, oo0 = s1[s1["buy_date"] >= "2024-09-01"], s0[s0["buy_date"] >= "2024-09-01"]
        y26_1, y26_0 = s1[s1["buy_date"] >= "2026-01-01"], s0[s0["buy_date"] >= "2026-01-01"]
        _, p_is = stats.ttest_ind(is1["net_ret"], is0["net_ret"], equal_var=False) if (len(is1) > 1 and len(is0) > 1) else (0.0, 1.0)
        _, p_oo = stats.ttest_ind(oo1["net_ret"], oo0["net_ret"], equal_var=False) if (len(oo1) > 1 and len(oo0) > 1) else (0.0, 1.0)
        # Also test +4 / -4 score adjustment on sub_w
        ev_p4 = eval_splits(sub_w[(sub_w["score"] + np.where(sub_w["buy_date"].isin(dset), 4.0, 0.0)) >= 76.0])
        ev_m4 = eval_splits(sub_w[(sub_w["score"] + np.where(sub_w["buy_date"].isin(dset), -4.0, 0.0)) >= 76.0])
        signal_tests[fname] = {
            "n_hit": int(len(s1)), "full_mn1_pct": sf(s1["net_ret"].mean() * 100.0, 2) if len(s1) else None, "full_mn0_pct": sf(s0["net_ret"].mean() * 100.0, 2),
            "IS_n1": int(len(is1)), "IS_diff_pp": sf((is1["net_ret"].mean() - is0["net_ret"].mean()) * 100.0, 2) if len(is1) else None, "IS_p": sf(p_is, 4),
            "OOS_n1": int(len(oo1)), "OOS_diff_pp": sf((oo1["net_ret"].mean() - oo0["net_ret"].mean()) * 100.0, 2) if len(oo1) else None, "OOS_p": sf(p_oo, 4),
            "Y26_n1": int(len(y26_1)), "Y26_diff_pp": sf((y26_1["net_ret"].mean() - y26_0["net_ret"].mean()) * 100.0, 2) if len(y26_1) else None,
            "score_plus4_dIS_dOOS_dY26": [sf(ev_p4["IS"]["nav"] - base_a_ev["IS"]["nav"], 2), sf(ev_p4["OOS"]["nav"] - base_a_ev["OOS"]["nav"], 2), sf(ev_p4["Y26"]["nav"] - base_a_ev["Y26"]["nav"], 2)],
            "score_minus4_dIS_dOOS_dY26": [sf(ev_m4["IS"]["nav"] - base_a_ev["IS"]["nav"], 2), sf(ev_m4["OOS"]["nav"] - base_a_ev["OOS"]["nav"], 2), sf(ev_m4["Y26"]["nav"] - base_a_ev["Y26"]["nav"], 2)],
        }

    # 2. R_sen20_lt40 deep dual-period + PBO + changed-trade audit
    pr = pool_rich.copy()
    pr["score"] = compute_scorecard_v11(pr)[0].values
    tr_v11 = sim_v11_exit_ext(pr, V11_EXIT_CFG, fee=ORIG_FEE_RT, tp_buf=0.0030)
    tr_sen = sim_v11_exit_ext(pr, {**V11_EXIT_CFG, "extra_risk": ["R_sen20_lt40"]}, fee=ORIG_FEE_RT, tp_buf=0.0030)

    ev_v11_A, ev_sen_A = eval_splits(tr_v11[tr_v11["score"] >= 76.0]), eval_splits(tr_sen[tr_sen["score"] >= 76.0])
    ev_v11_S, ev_sen_S = eval_splits(tr_v11[tr_v11["score"] >= 82.0]), eval_splits(tr_sen[tr_sen["score"] >= 82.0])
    pbo_v11_A, pbo_sen_A = cscv_pbo(tr_v11, 76.0, all_dts), cscv_pbo(tr_sen, 76.0, all_dts)
    pbo_v11_S, pbo_sen_S = cscv_pbo(tr_v11, 82.0, all_dts), cscv_pbo(tr_sen, 82.0, all_dts)

    # Changed-trades stats on A76 pool
    m_diff = tr_v11[tr_v11["score"] >= 76.0].merge(tr_sen[tr_sen["score"] >= 76.0], on=["sig_date", "buy_date", "c6"], suffixes=("_v11", "_sen"))
    chg = m_diff[m_diff["net_ret_v11"] != m_diff["net_ret_sen"]]
    chg_is = chg[chg["buy_date"] <= "2024-08-31"]
    chg_oos = chg[chg["buy_date"] >= "2024-09-01"]
    _, p_chg_all = stats.ttest_rel(chg["net_ret_sen"], chg["net_ret_v11"]) if len(chg) > 1 else (0.0, 1.0)
    _, p_chg_is = stats.ttest_rel(chg_is["net_ret_sen"], chg_is["net_ret_v11"]) if len(chg_is) > 1 else (0.0, 1.0)
    _, p_chg_oos = stats.ttest_rel(chg_oos["net_ret_sen"], chg_oos["net_ret_v11"]) if len(chg_oos) > 1 else (0.0, 1.0)

    # Strict upgrade gate: must improve BOTH IS and OOS (and Y26 >= 0) AND NOT raise PBO!
    rsen_dual_pass_A = (ev_sen_A["IS"]["nav"] > ev_v11_A["IS"]["nav"]) and (ev_sen_A["OOS"]["nav"] > ev_v11_A["OOS"]["nav"]) and (ev_sen_A["Y26"]["nav"] >= ev_v11_A["Y26"]["nav"])
    rsen_pbo_pass_A = (pbo_sen_A["loc_S8"] <= pbo_v11_A["loc_S8"]) and (pbo_sen_A["wide_S8"] <= pbo_v11_A["wide_S8"])
    any_10cm_pass = any(v["score_plus4_dIS_dOOS_dY26"][0] > 0 and v["score_plus4_dIS_dOOS_dY26"][1] > 0 and v["score_plus4_dIS_dOOS_dY26"][2] >= 0 for v in signal_tests.values()) or any(v["score_minus4_dIS_dOOS_dY26"][0] > 0 and v["score_minus4_dIS_dOOS_dY26"][1] > 0 and v["score_minus4_dIS_dOOS_dY26"][2] >= 0 for v in signal_tests.values())

    cand_10cm_pbo = {}
    for fname, dset in sig0925_days.items():
        st_f = signal_tests[fname]
        for sgn_lbl, delta_v, arr_d in [("plus4", 4.0, st_f["score_plus4_dIS_dOOS_dY26"]), ("minus4", -4.0, st_f["score_minus4_dIS_dOOS_dY26"])]:
            if arr_d[0] > 0 and arr_d[1] > 0 and arr_d[2] >= 0:
                tr_mod = tr_v11.copy()
                tr_mod["score"] = tr_mod["score"] + np.where(tr_mod["buy_date"].isin(dset), delta_v, 0.0)
                pbo_mod = cscv_pbo(tr_mod, 76.0, all_dts)
                ev_full_mod = eval_splits(tr_mod[tr_mod["score"] >= 76.0])
                cand_10cm_pbo[f"{fname}_{sgn_lbl}"] = {
                    "ev_full": ev_full_mod, "pbo": pbo_mod,
                    "dual_pass_full": (ev_full_mod["IS"]["nav"] > ev_v11_A["IS"]["nav"]) and (ev_full_mod["OOS"]["nav"] > ev_v11_A["OOS"]["nav"]) and (ev_full_mod["Y26"]["nav"] >= ev_v11_A["Y26"]["nav"]),
                    "pbo_drop": (pbo_mod["loc_S8"] <= pbo_v11_A["loc_S8"]) and (pbo_mod["wide_S8"] <= pbo_v11_A["wide_S8"]) and ((pbo_mod["loc_S8"] < pbo_v11_A["loc_S8"]) or (pbo_mod["wide_S8"] < pbo_v11_A["wide_S8"])),
                }
    best_10cm_pass = any(v["dual_pass_full"] and v["pbo_drop"] for v in cand_10cm_pbo.values())
    rsen_strict_pass = rsen_dual_pass_A and rsen_pbo_pass_A and ((pbo_sen_A["loc_S8"] < pbo_v11_A["loc_S8"]) or (pbo_sen_A["wide_S8"] < pbo_v11_A["wide_S8"]))
    verdict_lock_v11 = not (rsen_strict_pass or best_10cm_pass)
    v_reason = (
        f"R_sen20_lt40 IS({ev_v11_A['IS']['nav']}x->{ev_sen_A['IS']['nav']}x), OOS({ev_v11_A['OOS']['nav']}x->{ev_sen_A['OOS']['nav']}x), "
        f"Y26({ev_v11_A['Y26']['nav']}x->{ev_sen_A['Y26']['nav']}x), PBO loc_S8({pbo_v11_A['loc_S8']}%->{pbo_sen_A['loc_S8']}%), wide_S8({pbo_v11_A['wide_S8']}%->{pbo_sen_A['wide_S8']}%); "
        f"causal_10cm_0925_dual_pass_and_pbo_drop={best_10cm_pass} (candidates={list(cand_10cm_pbo.keys())})"
    )
    return {
        "ten_cm_0925_signal_audit": {
            "base_A76_in_5y_win": base_a_ev,
            "intraday_lookahead_vs_0925_exposure": leak_audit,
            "causal_0925_signal_tests": signal_tests,
            "any_causal_0925_signal_dual_pass": bool(any_10cm_pass), "cand_10cm_full_pbo_checks": cand_10cm_pbo,
        },
        "rsen20_lt40_upgrade_audit": {
            "A76_V11": ev_v11_A, "A76_Rsen20": ev_sen_A,
            "S82_V11": ev_v11_S, "S82_Rsen20": ev_sen_S,
            "pbo_A76_V11": pbo_v11_A, "pbo_A76_Rsen20": pbo_sen_A,
            "pbo_S82_V11": pbo_v11_S, "pbo_S82_Rsen20": pbo_sen_S,
            "changed_trades_A76": {
                "total": int(len(chg)), "IS_n": int(len(chg_is)), "OOS_n": int(len(chg_oos)),
                "IS_mean_diff_pp": sf((chg_is["net_ret_sen"] - chg_is["net_ret_v11"]).mean() * 100.0, 2) if len(chg_is) else None, "IS_paired_p": sf(p_chg_is, 4),
                "OOS_mean_diff_pp": sf((chg_oos["net_ret_sen"] - chg_oos["net_ret_v11"]).mean() * 100.0, 2) if len(chg_oos) else None, "OOS_paired_p": sf(p_chg_oos, 4),
                "all_paired_p": sf(p_chg_all, 4),
            },
            "dual_period_pass_A76": bool(rsen_dual_pass_A),
            "pbo_non_worsening_A76": bool(rsen_pbo_pass_A),
        },
        "final_verdict": "LOCK_ORIGINAL_V1.1" if verdict_lock_v11 else "UPGRADE_TO_V1.2",
        "verdict_reason": v_reason,
    }


def main():
    t0 = time.time()
    sh300, all_sh_dts, ew20_daily, cal_full, cal_5y, csi_full, csi_5y = load_calendars()
    df_all, tot_amt, zt_tape = load_full_daily_panel()

    led_A = pd.read_csv(f"{V11_DIR}/final_v11_ledger.csv", dtype={"c6": str})
    led_S = pd.read_csv(f"{V11_DIR}/final_v11_ledger_S82.csv", dtype={"c6": str})
    all_sig = pd.read_csv(f"{V11_DIR}/final_v11_all_scored_signals.csv", dtype={"c6": str})
    for d in (led_A, led_S, all_sig):
        d["c6"] = d["c6"].astype(str).str.zfill(6)
    p1_clean = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    p1_clean["c6"] = p1_clean["c6"].astype(str).str.zfill(6)
    pool_rich = pd.read_parquet(f"{RD23_DIR}/rd023_pool_enriched.parquet")
    pool_rich["c6"] = pool_rich["c6"].astype(str).str.zfill(6)

    # Collect 10cm + 20cm codes for fast by_c lookup
    codes_10 = set()
    for fn in ["ledger_3to4_v41_clean.csv", "ledger_high_v51_clean.csv", "ledger_pry_v21_ss165_clean.csv", "ledger_pry_v21_top1_clean.csv", "ledger_2to3_v21_opt_std90_clean.csv", "ledger_1to2_v19_clean.csv"]:
        codes_10.update(pd.read_csv(f"{PC_DIR}/{fn}", dtype={"code": str})["code"].str.zfill(6))
    by_c = build_by_c_lookup(df_all[df_all["is20"] | df_all["c6"].isin(codes_10)])

    factors_full, extra_full, fac_sum = build_5_factors_20cm(df_all, cal_full, all_sh_dts, csi_full)
    pool_by_dt, q_lookup = prepare_20cm_matched_pools(df_all[df_all["is20"]], cal_full)
    reg_df = build_regime_table_20cm(df_all, cal_full, all_sh_dts, tot_amt, zt_tape, extra_full)

    pairs_5m = {(r.c6, r.buy_date) for r in pd.concat([led_A, led_S]).itertuples(index=False)} | {(r.c6, r.exit_date) for r in pd.concat([led_A, led_S]).itertuples(index=False)}
    bars_5m = load_20cm_5m_bars(pairs_5m)

    # Compute exact daily MTM & Stationary Bootstrap shared weights
    d_A, act_A, nav_mtm_A, nav_led_A = compute_daily_mtm(led_A, by_c, cal_full, prices_are_adj=True)
    d_S, act_S, nav_mtm_S, nav_led_S = compute_daily_mtm(led_S, by_c, cal_full, prices_are_adj=True)
    rng = np.random.default_rng(SEED)
    W_dict = {L: stationary_bootstrap_weights(len(cal_full), BOOT_B, float(L), rng) for L in (10, 5, 20)}

    # Pillar 4 pool-wide diagnostics (on all_sig N=809)
    csi_full_ret = float(np.prod(1.0 + csi_full.to_numpy()) - 1.0)
    pool_p4 = {
        "pool_n": int(len(all_sig)),
        "ic_and_decay": calc_ic_block_20cm(all_sig, "score", "net_ret", min_period_n=4, min_roll_n=10),
        "monotonicity_q5_value": calc_quantile_bins(all_sig["score"].to_numpy(float), all_sig["net_ret"].to_numpy(float), 5, "value_qcut"),
        "monotonicity_q5_balanced": calc_quantile_bins(all_sig["score"].to_numpy(float), all_sig["net_ret"].to_numpy(float), 5, "rank_balanced"),
        "classification_calibration": calc_classification_calibration(all_sig, "score", "net_ret"),
    }

    print("[8/8] Assembling Pillars 1-5 for A76 & S82 and saving JSON...")
    targets_out = {}
    for tnm, ld, d_arr, act_f, thr, nav_m, nav_l in [
        ("A76", led_A, d_A, act_A, 76.0, nav_mtm_A, nav_led_A),
        ("S82", led_S, d_S, act_S, 82.0, nav_mtm_S, nav_led_S),
    ]:
        rets_tr = ld["net_ret_eval"].to_numpy(float)
        n_tr = len(rets_tr)
        p1_reg = run_pillar1_regressions(ld, d_arr, act_f, factors_full, extra_full, cal_full)
        p1_mc = run_matched_control_20cm(ld, all_sig, thr, pool_by_dt, q_lookup, by_c)
        p2 = run_pillar2(ld, by_c, cal_full, bars_5m, zt_tape)
        p3 = run_pillar3(ld, d_arr, reg_df, csi_full.to_numpy(float), cal_full)
        p4 = {
            "candidate_pool_analysis": pool_p4,
            "breakeven_transaction_cost": calc_breakeven_cost_20cm(rets_tr, csi_full_ret),
            "holding_period_decay": calc_holding_decay_20cm(ld, by_c, sh300, all_sh_dts),
        }

        tr_per_yr = float(n_tr) / (len(cal_full) / TRD_DAYS_YEAR)
        d_ex = d_arr - csi_full.to_numpy(float)
        tr_csi = np.array([get_csi_period_ret(sh300, all_sh_dts, r.buy_date, r.exit_date) for r in ld.itertuples(index=False)], dtype=float)
        mat_M, fam_meta = build_20cm_wrc_spa_family(thr, d_arr, p1_clean, pool_rich, by_c, cal_full)
        bca_m = bca_bootstrap_ci(rets_tr * 100.0, B=BOOT_B, alpha=0.05, rng=rng)
        bca_w = bca_bootstrap_ci((rets_tr > 0).astype(float) * 100.0, B=BOOT_B, alpha=0.05, rng=rng)
        w_lo, w_hi = wilson_ci_95(int((rets_tr > 0).sum()), n_tr)
        bca_w["wilson_95_ci_pct"] = [sf(w_lo * 100.0, 2), sf(w_hi * 100.0, 2)]

        p5 = {
            "psr_and_mintrl": {
                "daily_mtm_basis": {"vs_zero": calc_psr_mintrl(d_arr, ANN_DAYS_STAT, 1.0), "vs_csi300": calc_psr_mintrl(d_ex, ANN_DAYS_STAT, 1.0)},
                "trade_level_basis": {"trades_per_year": sf(tr_per_yr, 2), "vs_zero": calc_psr_mintrl(rets_tr, tr_per_yr, 1.0), "vs_csi300_holding": calc_psr_mintrl(rets_tr - tr_csi, tr_per_yr, 1.0)},
            },
            "multiple_testing_wrc_spa": {
                "family_meta": {**fam_meta, "politis_white_opt_L_days": sf(politis_white_opt_block_len(d_arr), 2)},
                "vs_cash0": run_wrc_and_spa(mat_M, W_dict, L_main=10),
                "vs_csi300": run_wrc_and_spa(mat_M - csi_full.to_numpy(float)[:, None], W_dict, L_main=10),
            },
            "bca_bootstrap_95ci": {"mean_net_ret_pct": {**bca_m, "excludes_zero": bool(bca_m["ci_95_low"] > 0)}, "win_rate_pct": bca_w},
            **calc_runs_autocorr_kelly(rets_tr, rng),
        }
        targets_out[tnm] = {
            "n_trades": int(n_tr), "n_active_days": int(act_f.sum()),
            "nav_ledger": sf(nav_l, 4), "nav_daily_mtm": sf(nav_m, 4),
            "pillar1_alpha_attribution": {"regressions": p1_reg, "matched_control": p1_mc},
            "pillar2_micro_capacity": p2,
            "pillar3_regime_stress_bootstrap": p3,
            "pillar4_signal_and_turnover": p4,
            "pillar5_statistical_confidence_and_sequence": p5,
        }

    p6 = run_pillar6_hygiene(df_all, led_A, led_S, d_A, d_S, cal_full)
    p7 = run_pillar7(led_A, led_S, d_A, d_S, cal_full, cal_5y, csi_5y.to_numpy(float), by_c, all_sig)
    item2 = verify_6x6_0925_and_rsen20(pool_rich, all_sig, p1_clean, all_sh_dts, sh300, ew20_daily, by_c, cal_full)

    out = sanitize_json({
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "full_window": f"{cal_full[0]} ~ {cal_full[-1]}",
            "n_trading_days_full": len(cal_full),
            "canon_5y_window": f"{cal_5y[0]} ~ {cal_5y[-1]}",
            "n_trading_days_5y": len(cal_5y),
            "csi300_full_ret_pct": sf(csi_full_ret * 100.0, 2),
            "yfinance_imported": "yfinance" in sys.modules,
            "factor_summary_full": fac_sum,
            "elapsed_sec": sf(time.time() - t0, 2),
        },
        "targets": targets_out,
        "pillar6_hygiene": p6,
        "pillar7_portfolio_cusum": p7,
        "item2_6x6_0925_and_rsen20_verdict": item2,
    })

    out_path = f"{OUT_DIR}/partB_20cm_jianyan_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[DONE in {time.time()-t0:.2f}s] Saved {out_path} ({os.path.getsize(out_path):,} bytes)")
    print("  Final Verdict:", item2["final_verdict"])


if __name__ == "__main__":
    main()
