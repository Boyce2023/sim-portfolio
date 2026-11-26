#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Helpers for RD036-C cold-blooded red-team audit: forensics, DSR, and V20 displacement."""
import json
import math
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
PART1 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
if PART1 not in sys.path:
    sys.path.insert(0, PART1)

import rd036_lib as lib
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe


def calc_dsr_explicit(dr: np.ndarray, n_trials: int, var_sr_daily: float, T: int = 936) -> dict:
    """Bailey & Lopez de Prado (2014) DSR with exact skew/kurtosis and arbitrary N & V[SR]."""
    x = np.asarray(dr, dtype=float)
    mu = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    sr = mu / sd if sd > 1e-12 else 0.0
    sk = float(stats.skew(x, bias=False))
    ku = max(1.0, float(stats.kurtosis(x, fisher=False, bias=False)))
    gm = 0.5772156649015329
    if n_trials <= 1 or var_sr_daily <= 0.0:
        sr0 = 0.0
    else:
        z1 = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
        z2 = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
        sr0 = math.sqrt(var_sr_daily) * ((1.0 - gm) * z1 + gm * z2)
    den = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2)))
    z = (sr - sr0) * math.sqrt(max(1, T - 1)) / den
    return {
        "n_trials": int(n_trials),
        "var_sr_daily": round(float(var_sr_daily), 6),
        "sr_ann": round(sr * math.sqrt(242.0), 3),
        "sr0_ann": round(sr0 * math.sqrt(242.0), 3),
        "z_dsr": round(float(z), 4),
        "dsr": round(float(stats.norm.cdf(z)), 4),
        "skew": round(sk, 3),
        "kurt": round(ku, 2),
    }


def build_forensic_lookup(codes: set[str]) -> dict:
    """Load read-only PIT bar, static/dynamic ST, and delisted status for audited codes."""
    codes_l = sorted(codes)
    with open(f"{SIM}/data/st_universe.json") as f:
        st_static = set(str(x)[-6:] for x in json.load(f)["codes"])

    dl_df = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=["ticker", "date"])
    dl_df["c6"] = dl_df["ticker"].astype(str).str[:6]
    dl_df["dt"] = pd.to_datetime(dl_df["date"]).dt.strftime("%Y-%m-%d")
    dl_last = dl_df[dl_df["c6"].isin(codes)].groupby("c6")["dt"].max().to_dict()
    del dl_df

    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    tox_n = pd.read_sql_query(
        "SELECT sec_code, substr(pub_datetime_cst,1,10) as dt, title FROM notices "
        "WHERE title LIKE '%被实施退市风险警示%' OR title LIKE '%被实施其他风险警示%' OR title LIKE '%实施风险警示%' OR title LIKE '%终止上市%' OR title LIKE '%退市整理%'",
        con_n,
    )
    con_n.close()
    tox_n["c6"] = tox_n["sec_code"].astype(str).str.zfill(6)
    tox_n = tox_n[tox_n["c6"].isin(codes)]
    dyn_st = tox_n.groupby("c6")["dt"].min().to_dict()

    cols_sd = ["dt", "c6", "open", "close", "adj_factor", "open_pct", "ret_1d", "amount_yi", "amount_yi_t1", "is_st_pit", "is_yizi_zt", "is_yizi_dt", "list_age"]
    sd = ds.dataset(f"{WAVE1}/stock_day_core_features_pit.parquet").scanner(
        columns=cols_sd, filter=ds.field("c6").isin(codes_l)
    ).to_table().to_pandas()
    sd["dt"] = sd["dt"].astype(str).str[:10]
    sd["c6"] = sd["c6"].astype(str).str.zfill(6)
    bar_lu = {}
    for r in sd.itertuples(index=False):
        bar_lu[(r.c6, r.dt)] = (
            float(r.open), float(r.close), float(r.adj_factor),
            float(r.open_pct) if np.isfinite(r.open_pct) else np.nan,
            float(r.amount_yi) if np.isfinite(r.amount_yi) else np.nan,
            float(r.amount_yi_t1) if np.isfinite(r.amount_yi_t1) else np.nan,
            int(r.is_st_pit), int(r.is_yizi_zt), int(r.is_yizi_dt), int(r.list_age),
        )
    del sd
    return {"st_static": st_static, "dl_last": dl_last, "dyn_st": dyn_st, "bar_lu": bar_lu}


def forensic_audit_trades(name: str, slot_df: pd.DataFrame, ref: dict) -> dict:
    """Full trade-by-trade forensic audit: top5/bot5, ex5/ex10 at 30/80bps, ST/delisted/yizi."""
    d = slot_df.sort_values(["buy_date", "code"]).reset_index(drop=True).copy()
    rows = []
    for r in d.itertuples(index=False):
        c6, bd, ed = str(r.code).zfill(6), str(r.buy_date)[:10], str(r.exit_date)[:10]
        b = ref["bar_lu"].get((c6, bd))
        e = ref["bar_lu"].get((c6, ed))
        dl_dt = ref["dl_last"].get(c6, "")
        dyn_st_dt = ref["dyn_st"].get(c6, "")
        is_st_on_buy = bool(dyn_st_dt and dyn_st_dt <= bd)
        is_dl_before_exit = bool(dl_dt and dl_dt < ed)
        op_pct = b[3] if b else np.nan
        # Note: stock_day_core_features_pit.open_pct is in percent (e.g. -6.2)
        rows.append({
            "buy_date": bd, "exit_date": ed, "code": c6, "name": str(r.name),
            "v20_score": float(r.v20_score), "score": float(r.score),
            "net_ret_30": float(r.net_ret_30), "net_ret_80": float(r.net_ret_80),
            "buy_px": round(b[0] * b[2], 3) if b else None,
            "exit_px": round(e[1] * e[2], 3) if e else None,
            "buy_amt_yi": round(b[4], 2) if (b and np.isfinite(b[4])) else None,
            "t1_amt_yi": round(float(r.sd_amount_yi_t1), 2) if pd.notna(r.sd_amount_yi_t1) else None,
            "open_pct": round(op_pct, 2) if np.isfinite(op_pct) else None,
            "is_st_static": int(b[6]) if b else (1 if c6 in ref["st_static"] else 0),
            "dyn_st_dt": dyn_st_dt, "is_st_on_buy": is_st_on_buy,
            "delisted_dt": dl_dt, "is_dl_before_exit": is_dl_before_exit,
            "is_yizi_zt": int(b[7]) if b else 0, "is_yizi_dt": int(b[8]) if b else 0,
            "list_age": int(b[9]) if b else 999,
            "adj_ratio": round(e[2] / b[2], 4) if (b and e and b[2] > 0) else 1.0,
        })
    df_f = pd.DataFrame(rows)
    r30 = df_f["net_ret_30"].to_numpy(float)
    r80 = df_f["net_ret_80"].to_numpy(float)
    log30 = np.log1p(r30)
    tot_log30 = float(np.sum(log30))
    sr30 = np.sort(r30)
    sr80 = np.sort(r80)
    top5_log = float(np.sum(np.log1p(sr30[-5:]))) if len(sr30) >= 5 else tot_log30
    top10_log = float(np.sum(np.log1p(sr30[-10:]))) if len(sr30) >= 10 else tot_log30

    top5_best = df_f.sort_values("net_ret_30", ascending=False).head(5).to_dict("records")
    top5_worst = df_f.sort_values("net_ret_30", ascending=True).head(5).to_dict("records")
    for row_x in top5_best + top5_worst:
        row_x["net_ret_30_pct"] = round(row_x["net_ret_30"] * 100.0, 2)
        row_x["net_ret_80_pct"] = round(row_x["net_ret_80"] * 100.0, 2)

    return {
        "variant": name,
        "n_trades": int(len(df_f)),
        "nav_30bps": round(float(np.prod(1.0 + r30)), 4),
        "ex5_nav_30bps": round(float(np.prod(1.0 + sr30[:-5])), 4) if len(sr30) > 5 else 1.0,
        "ex10_nav_30bps": round(float(np.prod(1.0 + sr30[:-10])), 4) if len(sr30) > 10 else 1.0,
        "nav_80bps": round(float(np.prod(1.0 + r80)), 4),
        "ex5_nav_80bps": round(float(np.prod(1.0 + sr80[:-5])), 4) if len(sr80) > 5 else 1.0,
        "ex10_nav_80bps": round(float(np.prod(1.0 + sr80[:-10])), 4) if len(sr80) > 10 else 1.0,
        "tot_log_ret_30bps": round(tot_log30, 4),
        "top5_log_ret_share_pct": round(top5_log / max(1e-9, tot_log30) * 100.0, 2),
        "top10_log_ret_share_pct": round(top10_log / max(1e-9, tot_log30) * 100.0, 2),
        "hygiene_checks": {
            "n_nan_ret": int((~np.isfinite(r30)).sum()),
            "n_st_on_buy_date": int(df_f["is_st_on_buy"].sum()),
            "n_st_static_post_event": int(df_f["is_st_static"].sum()),
            "st_static_details": df_f[df_f["is_st_static"] == 1][["buy_date", "code", "name", "dyn_st_dt", "net_ret_30"]].to_dict("records"),
            "n_delisted_before_exit": int(df_f["is_dl_before_exit"].sum()),
            "n_delisted_later": int((df_f["delisted_dt"] != "").sum()),
            "delisted_later_details": df_f[df_f["delisted_dt"] != ""][["buy_date", "code", "name", "delisted_dt", "net_ret_30"]].to_dict("records"),
            "n_yizi_zt_buy": int(df_f["is_yizi_zt"].sum()),
            "n_yizi_dt_buy": int(df_f["is_yizi_dt"].sum()),
            "n_open_ge_195": int((df_f["open_pct"].fillna(0.0) >= 19.5).sum()),
            "n_list_age_le_10": int((df_f["list_age"] <= 10).sum()),
            "n_buy_amt_lt_2yi": int((df_f["buy_amt_yi"].fillna(999.0) < 2.0).sum()),
            "n_t1_amt_lt_2yi": int((df_f["t1_amt_yi"].fillna(999.0) < 2.0).sum()),
            "min_buy_amt_yi": round(float(df_f["buy_amt_yi"].min()), 2),
            "median_buy_amt_yi": round(float(df_f["buy_amt_yi"].median()), 2),
            "min_t1_amt_yi": round(float(df_f["t1_amt_yi"].min()), 2),
        },
        "top5_best": top5_best,
        "top5_worst": top5_worst,
    }


def extract_v20_comb_ledger(v20_comb_ctx: dict, new_20cm_slot_wf: pd.DataFrame, wf_start_dt: str = "2023-01-03", end_dt: str = "2026-11-16") -> pd.DataFrame:
    """Run V20.0 single-slot replacement and return full WF trade ledger for displacement analysis."""
    p20_old = v20_comb_ctx["p20_old"]
    p20_map = v20_comb_ctx["p20_map"]
    _, base_s76 = m1.sim_standalone("20cm", p20_old, np.zeros(len(p20_old)), cm20_thr=76.0)
    pre_20 = base_s76[base_s76["buy_date"].between("2021-11-16", wf_start_dt) & (base_s76["buy_date"] < wf_start_dt) & (base_s76["v20_score"] >= 82.0)].copy()
    pre_20["score"] = pre_20["v20_score"]
    pre_20["tier"] = "20cm_S(>=82)"
    pre_20["is_untrig"] = False

    nw = new_20cm_slot_wf[new_20cm_slot_wf["buy_date"].between(wf_start_dt, end_dt)].copy()
    nw["strategy"] = "20cm"
    nw["tier"] = "20cm_S(>=82)"
    nw["is_untrig"] = False
    if "score" not in nw.columns:
        nw["score"] = 85.0
    mtm_5y_list, bpx_list, ehh_list, nr_list = [], [], [], []
    for r in nw.itertuples(index=False):
        tup = p20_map.get((r.buy_date, r.code))
        if tup is not None:
            mtm_5y_list.append(tup[0]); bpx_list.append(tup[1]); ehh_list.append(tup[2]); nr_list.append(tup[3])
        else:
            mtm_5y_list.append(()); bpx_list.append(float(getattr(r, "buy_price", 1.0))); ehh_list.append(1500); nr_list.append(float(r.net_ret))
    nw["mtm_5y"] = mtm_5y_list; nw["buy_price_val"] = bpx_list; nw["exit_hhmm"] = ehh_list; nw["net_ret"] = nr_list
    nw["is_adj_px"] = True; nw["buy_hhmm"] = 925

    cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig", "mtm_5y"]
    p6 = pd.concat([v20_comb_ctx["other_pool5"][cols], pd.concat([pre_20[cols], nw[cols]], ignore_index=True)], ignore_index=True)
    tr_df, _ = tpe.run_single_slot(
        p6.drop(columns=["mtm_5y"]),
        lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(),
        untrig_df=v20_comb_ctx["ut_final"],
        timing_mode="s_tier_reserve_only",
    )
    return tr_df[tr_df["buy_date"].between(wf_start_dt, end_dt)].sort_values("buy_date").reset_index(drop=True)


def analyze_comb_displacement(cand_name: str, cand_tr: pd.DataFrame, ref_name: str, ref_tr: pd.DataFrame) -> dict:
    """Compare cand_tr vs ref_tr in V20 combined single-slot portfolio to detect crowding illusions."""
    key_cols = ["strategy", "buy_date", "code"]
    ref_map = {(r.strategy, r.buy_date, r.code): r for r in ref_tr.itertuples(index=False)}
    cnd_map = {(r.strategy, r.buy_date, r.code): r for r in cand_tr.itertuples(index=False)}

    removed = [ref_map[k] for k in sorted(set(ref_map) - set(cnd_map))]
    added = [cnd_map[k] for k in sorted(set(cnd_map) - set(ref_map))]

    rem_20 = [r for r in removed if r.strategy == "20cm"]
    add_20 = [r for r in added if r.strategy == "20cm"]
    rem_other = [r for r in removed if r.strategy != "20cm"]
    add_other = [r for r in added if r.strategy != "20cm"]

    def _summ(lst):
        rets = [float(r.net_ret) for r in lst]
        return {
            "n": len(lst),
            "mult": round(float(np.prod([1.0 + x for x in rets])), 4) if rets else 1.0,
            "by_strategy": pd.Series([r.strategy for r in lst]).value_counts().to_dict() if lst else {},
            "trades": [{"strategy": r.strategy, "buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name, "net_ret_pct": round(float(r.net_ret) * 100.0, 2)} for r in lst],
        }

    ref_nav = float(np.prod(1.0 + ref_tr["net_ret"].to_numpy(float)))
    cnd_nav = float(np.prod(1.0 + cand_tr["net_ret"].to_numpy(float)))
    m_20_add = _summ(add_20)["mult"]
    m_20_rem = _summ(rem_20)["mult"]
    m_oth_add = _summ(add_other)["mult"]
    m_oth_rem = _summ(rem_other)["mult"]
    pure_20_ratio = m_20_add / max(1e-9, m_20_rem)
    other_crowd_ratio = m_oth_add / max(1e-9, m_oth_rem)

    return {
        "comparison": f"{cand_name}_vs_{ref_name}",
        "cand_nav": round(cnd_nav, 2),
        "ref_nav": round(ref_nav, 2),
        "total_nav_ratio": round(cnd_nav / max(1e-9, ref_nav), 4),
        "pure_20cm_swap_ratio": round(pure_20_ratio, 4),
        "non20cm_displacement_ratio": round(other_crowd_ratio, 4),
        "non20cm_displacement_share_of_log_gain_pct": round(
            math.log(max(1e-9, other_crowd_ratio)) / max(1e-9, abs(math.log(max(1e-9, cnd_nav / ref_nav)))) * 100.0, 2
        ),
        "added_20cm": _summ(add_20),
        "removed_20cm": _summ(rem_20),
        "added_non20cm_freed_slots": _summ(add_other),
        "removed_non20cm_bumped": _summ(rem_other),
    }
