#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-1 Data Loader, Baseline Parity Verifier, and Unified 0.30%-Cost Evaluator.
Zero yfinance (D12). Read-only on wave1_base and production scripts.
"""
import gc
import json
import os
import pickle
import sys
from typing import Optional

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a1_old_1to2_2to3"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (WAVE1_DIR, RD028_DIR, PARTC_V20):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import step4_mod_rules_and_sim as m1
import tier_priority_engine as tpe

WF_START = "2023-01-03"
WF_END = "2026-11-16"


def to_30bps(r20: np.ndarray | pd.Series) -> np.ndarray:
    arr = np.asarray(r20, dtype=np.float64)
    return (1.0 + arr) * (0.997 / 0.998) - 1.0


def build_1to2_contrib_matrix(df: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    """Return exact (28 s12_atom_* col names, N x 28 point contribution matrix in v20_score)."""
    cols = [c for c in df.columns if c.startswith("s12_atom_")]
    assert len(cols) == 28, f"Expected 28 s12_atom_ cols, got {len(cols)}"
    cb = (df["s12_atom_clean_brk60"].fillna(0).to_numpy(float) == 1.0)
    mcap = df["s12_atom_mcap"].fillna(50.0).to_numpy(float)
    amt = df["s12_atom_amt"].fillna(2e8).to_numpy(float)
    dd20 = df["s12_atom_dd20"].fillna(0.9).to_numpy(float)
    pos20 = df["s12_atom_pos20"].fillna(0.5).to_numpy(float)
    to = df["s12_atom_to"].fillna(8.0).to_numpy(float)
    vr = df["s12_atom_vr"].fillna(1.5).to_numpy(float)

    fixed_w = {
        "s12_atom_pure_outsider": -20.0,
        "s12_atom_is_gran": 15.0,
        "s12_atom_s_elo_hot": 10.0,
        "s12_atom_s_elo_cold": -10.0,
        "s12_atom_wk_mask": 10.0,
        "s12_atom_rk_theme_1": 28.0,
        "s12_atom_p_sz_ge4": 18.0,
        "s12_atom_hard_cat": 18.0,
        "s12_atom_dd20_deep": np.where(cb, 0.0, np.where(dd20 <= 0.82, 42.0, 32.0)),
        "s12_atom_clean_brk60": 24.0,
        "s12_atom_true_buy_rk1": 35.0,
        "s12_atom_mkt_open_top3": 20.0,
        "s12_atom_open_sweet": 20.0,
        "s12_atom_front_lock1": 8.0,
        "s12_atom_front_lock_crowd": -15.0,
        "s12_atom_tight_open1": 5.0,
        "s12_atom_has_ir": 5.0,
        "s12_atom_cap_yizi_gt90": -25.0,
        "s12_atom_climax_95": -10.0,
        "s12_atom_seal_80": -10.0,
        "s12_atom_v20_fb20_pen": -25.0,
        "s12_atom_xq_cold": 0.0,
    }
    mat = np.zeros((len(df), len(cols)), dtype=np.float64)
    for j, c in enumerate(cols):
        if c == "s12_atom_mcap":
            mat[:, j] = np.where((mcap >= 60) & (mcap <= 155), 28.0, np.where((mcap >= 40) & (mcap < 60), 10.0, np.where(mcap < 35, -20.0, 0.0)))
        elif c == "s12_atom_amt":
            mat[:, j] = np.where((amt >= 2.2e8) & (amt <= 15e8), 18.0, np.where(amt < 1.8e8, -25.0, -10.0))
        elif c == "s12_atom_dd20":
            mat[:, j] = np.where(cb, 0.0, np.where(dd20 <= 0.82, 42.0, np.where(dd20 <= 0.86, 32.0, np.where(dd20 <= 0.90, 18.0, np.where(dd20 > 0.95, -40.0, 0.0)))))
        elif c == "s12_atom_pos20":
            mat[:, j] = np.where(cb, 0.0, np.where(pos20 <= 0.30, 25.0, np.where(pos20 <= 0.45, 12.0, np.where(pos20 > 0.75, -35.0, 0.0))))
        elif c == "s12_atom_to":
            mat[:, j] = np.where(to <= 9.0, 15.0, np.where(to <= 15.0, 8.0, np.where(to > 18.0, -25.0, 0.0)))
        elif c == "s12_atom_vr":
            mat[:, j] = np.where(vr <= 1.75, 15.0, np.where(vr > 2.3, -15.0, 0.0))
        elif c == "s12_atom_dd20_deep":
            mat[:, j] = df[c].fillna(0).to_numpy(float) * fixed_w[c]
        else:
            mat[:, j] = df[c].fillna(0).to_numpy(float) * float(fixed_w[c])
    return cols, mat


def _adjust_mtm_30bps(segs: tuple, nr20: float, nr30: float) -> tuple:
    if not segs or not np.isfinite(nr20) or (1.0 + nr20) <= 0:
        return segs
    lst = list(segs)
    t_last, m_last = lst[-1]
    lst[-1] = (t_last, m_last * ((1.0 + nr30) / (1.0 + nr20)))
    return tuple(lst)


def _load_calendars_and_bars_lean(codes_needed: set[str], needed_pairs: set[tuple[str, str]]):
    raw = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_full = [d for d in all_sh_dts if "2021-01-04" <= d <= "2026-11-25"]
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]

    tickers = sorted([f"{c}.SH" for c in codes_needed] + [f"{c}.SZ" for c in codes_needed])
    cols = ["date", "ticker", "open", "close", "adj_close", "qfq_factor"]
    flt = (ds.field("date") >= pd.Timestamp("2021-11-01")) & ds.field("ticker").isin(tickers)
    chunks = []
    for fpath, dl_flag in [(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0), (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1)]:
        scanner = ds.dataset(fpath).scanner(columns=cols, filter=flt, batch_size=65536)
        for batch in scanner.to_batches():
            dfb = batch.to_pandas()
            if dfb.empty:
                continue
            c6s = dfb["ticker"].astype(str).str[:6]
            dts = dfb["date"].dt.strftime("%Y-%m-%d")
            m = pd.MultiIndex.from_arrays([c6s, dts]).isin(needed_pairs)
            if m.any():
                sub = dfb.loc[m].copy()
                sub["c6"] = c6s.loc[m].values
                sub["dt"] = dts.loc[m].values
                sub["dl"] = dl_flag
                chunks.append(sub)
    dp = pd.concat(chunks, ignore_index=True)
    del chunks
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in dp.itertuples(index=False)
    }
    del dp
    gc.collect()
    return sh300, all_sh_dts, cal_full, cal_5y, bar_lu


def _load_untrig_lean(pools_oh: dict) -> pd.DataFrame:
    """Lean <10MB untriggered conditional order pool for 3to4, high, 1to2."""
    rows = []
    # 1. 3to4
    c34 = pickle.load(open(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl", "rb"))
    cand34 = c34["cand_df"].copy()
    cand34["score"] = c34["sc_v40"]
    d34_dts = set(pd.read_csv(f"{m1.PARTC_DIR}/ledger_3to4_v41_clean.csv")["buy_date"].astype(str).str[:10])
    u34 = []
    for i in cand34.index:
        bd = str(cand34.loc[i, "buy_date"])[:10]
        if cand34.loc[i, "score"] >= 90.0 and c34["buy_entries"][i]["buy_px"] is None and "2021-11-16" <= bd <= "2026-11-16" and bd not in d34_dts:
            u34.append({"buy_date": bd, "buy_hhmm": 935, "exit_date": bd, "exit_hhmm": 1030, "code": str(cand34.loc[i, "code"]).zfill(6), "name": str(cand34.loc[i, "name"]), "strategy": "3to4", "score": float(cand34.loc[i, "score"])})
    if u34:
        rows.append(pd.DataFrame(u34).sort_values(["buy_date", "score"], ascending=[True, False]).groupby("buy_date", as_index=False).first())

    # 2. high (using tiny 90KB v5_enriched_119.pkl directly without loading 3.5GB caches)
    v5 = pd.read_pickle(f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_enriched_119.pkl")
    dhd_dts = set(pd.read_csv(f"{m1.PARTC_DIR}/ledger_high_v51_clean.csv")["buy_date"].astype(str).str[:10])
    uhd = []
    for _, r in v5.iterrows():
        if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 35.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
            continue
        sc = 60 + (12 if r["brk_r10"] >= 0.20 else -8)
        sc += 10 if r["n_zt"] < 70 else (-10 if r["n_zt"] >= 95 else 0)
        sc += 8 if r["csi5"] >= -0.005 else (-10 if r["csi5"] < -0.025 else 0)
        sc += (8 if r["d1_op"] < 0.0 else 0) + (8 if r["op2"] < 0.0 else (6 if r["op2"] <= 0.025 else 0))
        sc += (6 if (r["obc"] == 0 and r["d0_tight"] >= 35.0) else 0) + (6 if (r["pelo"] < 135.0 and not r["dom"]) else 0)
        sc += 6 if r["lh1"] == 0 else (-10 if r["lh1"] == 2 else 0)
        sc += (-6 if r["in1"] >= 1 else 0) + (5 if r["low_price_le20"] else (-10 if r["high_price_gt35"] else 0))
        sc += (5 if r["turn_boards_ge4"] else (-5 if r["turn_boards_cnt"] <= 2 else 0)) + (5 if r["d1_deep_dip_le6"] else 0)
        sc += (6 if (r["lock"] >= 45.0 or r["fmcap"] >= 45.0) else -6) + (4 if (r["qu1"] >= 1 and r["lh1"] <= 1) else 0)
        sc += (6 if r["kpl_hist_1y_has_ge5"] else (3 if r["kpl_hist_3y_has_ge5"] else 0))
        sc += (3 if r["kpl_old_stock_old_theme"] else (-5 if r["kpl_old_stock_new_theme"] else 0))
        sc += (5 if r["lhb_d0_top_locked"] else 0) + (-10 if r["lhb_d1_lhasa_heavy"] else 0) + (-5 if r["lhb_d1_net_positive"] else 0)
        sc += (-6 if r["lhb_d0_day_surf_buy"] else 0) + (-5 if r["kpl_d0_seal_early_0935"] else 0) + (-4 if r["kpl_reason_tech"] else 0)
        bd = str(r["buy_date"])[:10]
        if sc >= 88 and r["op2"] < 0.0 and "2021-11-16" <= bd <= "2026-11-16" and bd not in dhd_dts:
            uhd.append({"buy_date": bd, "buy_hhmm": 935, "exit_date": bd, "exit_hhmm": 1130, "code": str(r["code"]).zfill(6), "name": str(r["name"]), "strategy": "high", "score": float(sc)})
    if uhd:
        rows.append(pd.DataFrame(uhd).sort_values(["buy_date", "score"], ascending=[True, False]).groupby("buy_date", as_index=False).first())

    # 3. 1to2
    pt12 = pd.read_parquet(f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2/_cache_pretrig_pool.parquet")
    d12_dts = set(pd.read_csv(f"{m1.PARTA_DIR}/ledger_1to2_v20_cand.csv")["buy_date"].astype(str).str[:10])
    v19_pt = pt12[pt12["base_pass_v19"] & pt12["buy_date"].between("2021-11-16", "2026-11-16")].sort_values(["buy_date", "sv_base", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    u12 = v19_pt[(~v19_pt["sim_ok"]) & (~v19_pt["buy_date"].isin(d12_dts))][["buy_date", "code", "name", "base_score"]].copy()
    if not u12.empty:
        u12["buy_hhmm"], u12["exit_date"], u12["exit_hhmm"], u12["strategy"] = 935, u12["buy_date"], 1130, "1to2"
        u12.rename(columns={"base_score": "score"}, inplace=True)
        rows.append(u12)

    out = pd.concat(rows, ignore_index=True)
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["name"] = out["name"].fillna("").astype(str)
    out["tier"] = [tpe.assign_physical_tier(r.strategy, r.score) for r in out.itertuples(index=False)]
    out["net_ret"], out["buy_price_val"], out["is_adj_px"], out["is_untrig"] = 0.0, np.nan, False, True
    out["v20_score"] = out["score"].astype(float)
    return out


def load_all_bundle() -> dict:
    """Load shared PIT pools, oldhot sim metadata, V20 6-strat context, and verify 100% parity."""
    v20_ctx = wf.load_v20_reference_context(WAVE1_DIR)
    p12 = pd.read_parquet(f"{WAVE1_DIR}/pool_1to2_master_pit.parquet").sort_values(["buy_date", "code"]).reset_index(drop=True)
    p23 = pd.read_parquet(f"{WAVE1_DIR}/pool_2to3_master_pit.parquet").sort_values(["buy_date", "code"]).reset_index(drop=True)
    p12_oh = pd.read_parquet(f"{RD028_DIR}/pool_1to2_oldhot.parquet").sort_values(["buy_date", "code"]).reset_index(drop=True)
    p23_oh = pd.read_parquet(f"{RD028_DIR}/pool_2to3_oldhot.parquet").sort_values(["buy_date", "code"]).reset_index(drop=True)

    assert (p12["buy_date"] == p12_oh["buy_date"]).all() and (p12["code"] == p12_oh["code"]).all()
    assert (p23["buy_date"] == p23_oh["buy_date"]).all() and (p23["code"] == p23_oh["code"]).all()

    for c in ["elig_t1", "elig_mon", "elig_t2", "elig_dom295", "thr_vec", "sc_t3_pen", "rk_theme", "t1_dom_plate", "exit_at_open", "v20_pen"]:
        p12[c] = p12_oh[c].values
    p23["plate_sz"] = p23_oh["plate_sz"].values
    p23["prev_is_yizi"] = p23_oh["prev_is_yizi"].values
    p23["buyable_open"] = p23_oh["buyable_open"].values

    for df in (p12, p23):
        df["net_ret_20"] = pd.to_numeric(df["net_ret"], errors="coerce").astype(np.float64)
        df["net_ret_30"] = to_30bps(df["net_ret_20"])
        df["net_ret"] = df["net_ret_30"]
        is_yz = (pd.to_numeric(df["open_pct"], errors="coerce").fillna(0.0) >= 0.095)
        if "prev_is_yizi" in df.columns:
            is_yz = is_yz | df["prev_is_yizi"].fillna(False)
        df["is_yizi"] = is_yz.astype(bool)

    with open(f"{WAVE1_DIR}/wave1a_factor_catalog_and_pit_audit.json", encoding="utf-8") as f:
        cat = json.load(f)["master_factor_catalog"]

    s12_atom_28, s12_contrib = build_1to2_contrib_matrix(p12)
    s23_af_18 = [f"s23_af_{i:02d}" for i in range(18)]
    xtr_37 = [c for c in p12.columns if c.startswith("xtr_")]
    new_330 = [c for c, v in cat.items() if v["role"] == "entry_feature" and pd.api.types.is_numeric_dtype(p12[c])]

    # Precompute exact MTM segments for 6 strategies using PyArrow ticker+pair filter (<1GB RSS)
    raw_sh = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    cal_sh_all = sorted(raw_sh["sh000300"].keys())
    sh_idx = {d: i for i, d in enumerate(cal_sh_all)}
    codes = set(p12["code"]).union(set(p23["code"])).union(set(v20_ctx["v20_ledger"]["code"].astype(str).str.zfill(6)))
    needed_pairs = set()
    for st in m1.STRAT_ORDER:
        d_s = pd.read_parquet(f"{RD028_DIR}/pool_{st}_oldhot.parquet")
        if st not in ("1to2", "2to3"):
            d_s = d_s[d_s["is_standalone_slot1"].astype(bool)]
        for r in d_s.itertuples(index=False):
            c6 = str(r.code).zfill(6)
            codes.add(c6)
            bd, ed = str(r.buy_date)[:10], str(r.exit_date)[:10]
            bi, ei = sh_idx.get(bd), sh_idx.get(ed)
            if bi is not None:
                ei_use = ei if (ei is not None and ei >= bi) else min(len(cal_sh_all) - 1, bi + 15)
                for k in range(bi, ei_use + 1):
                    needed_pairs.add((c6, cal_sh_all[k]))
    sh300, all_sh_dts, cal_full, cal_5y, bar_lu = _load_calendars_and_bars_lean(codes, needed_pairs)
    pools_oh = m1.load_pools_oldhot(cal_full, cal_5y, bar_lu)
    untrig = _load_untrig_lean(pools_oh)
    parity_rep = m1.verify_all_baselines(pools_oh, untrig)
    assert parity_rep["1to2"]["n"] == 92 and round(parity_rep["1to2"]["nav"], 2) == 474.35
    assert parity_rep["2to3"]["n"] == 95 and round(parity_rep["2to3"]["nav"], 2) == 404.71
    assert parity_rep["combined_v20"]["n"] == 278

    # Attach mtm_5y_20 and mtm_5y_30 directly onto p12 and p23
    for st, df in [("1to2", p12), ("2to3", p23)]:
        po = pools_oh[st].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert (po["buy_date"] == df["buy_date"]).all() and (po["code"] == df["code"]).all()
        df["mtm_5y_20"] = po["mtm_5y"].values
        df["mtm_5y_30"] = [_adjust_mtm_30bps(s, r20, r30) for s, r20, r30 in zip(df["mtm_5y_20"], df["net_ret_20"], df["net_ret_30"])]
        df["buy_price_val"] = po["buy_price_val"].values
        df["is_adj_px"] = po["is_adj_px"].values

    # Build baseline WF 0.30% parts for the other 4 strategies + baseline 1to2 / 2to3
    base_slots_30 = {}
    for st in m1.STRAT_ORDER:
        po = pools_oh[st]
        _, sl = m1.sim_standalone(st, po, np.zeros(len(po)), high_cb_mode="v51_exact", cm20_thr=82.0)
        sl = sl[sl["buy_date"].between(WF_START, WF_END)].copy()
        sl["score"] = sl["v20_score"].astype(float)
        sl["tier"] = [tpe.assign_physical_tier(st, sc) for sc in sl["score"]]
        sl["is_untrig"] = False
        nr20 = sl["net_ret"].to_numpy(float)
        nr30 = to_30bps(nr20)
        sl["net_ret"] = nr30
        sl["mtm_5y_30"] = [_adjust_mtm_30bps(s, r2, r3) for s, r2, r3 in zip(sl["mtm_5y"], nr20, nr30)]
        base_slots_30[st] = sl

    bundle = {
        "v20_ctx": v20_ctx,
        "p12": p12,
        "p23": p23,
        "s12_atom_28": s12_atom_28,
        "s12_contrib": s12_contrib,
        "s23_af_18": s23_af_18,
        "xtr_37": xtr_37,
        "new_330": new_330,
        "cal_5y": cal_5y,
        "cal_5y_idx": {d: i for i, d in enumerate(cal_5y)},
        "pools_oh": pools_oh,
        "untrig": untrig,
        "base_slots_30": base_slots_30,
        "parity_rep": parity_rep,
    }
    bundle["base_comb_wf_30"] = eval_v20_combined_30bps(bundle, {"1to2": base_slots_30["1to2"]})
    return bundle


def sim_1to2_custom(
    df: pd.DataFrame,
    score_vec: np.ndarray,
    thr_vec: Optional[np.ndarray] = None,
    allow_next_rank: bool = False,
    mask: Optional[np.ndarray] = None,
    require_elig: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate 1to2 using custom score_vec and optional mask/next-rank fallback."""
    sc = np.asarray(score_vec, dtype=np.float64)
    tv = df["thr_vec"].to_numpy(float) if thr_vec is None else np.asarray(thr_vec, dtype=np.float64)
    if require_elig:
        m_t1 = df["elig_t1"].to_numpy(bool) & (sc >= tv)
        m_t2 = df["elig_t2"].to_numpy(bool)
        m_mon = df["elig_mon"].to_numpy(bool) & (sc >= tv)
        m_dom = df["elig_dom295"].to_numpy(bool) & ((sc - df["sc_t3_pen"].to_numpy(float)) >= 295.0)
        tot_v18 = m_t1 | m_t2 | m_mon
        tot_v19 = tot_v18 | m_dom
        sv = np.where(m_t1 | m_t2, sc + 1000.0, np.where(m_mon, sc, sc + 500.0))
    else:
        tot_v19 = (sc >= tv) & (~df["is_yizi"].to_numpy(bool))
        tot_v18 = tot_v19
        sv = sc
    if mask is not None:
        tot_v19 = tot_v19 & np.asarray(mask, dtype=bool)
        tot_v18 = tot_v18 & np.asarray(mask, dtype=bool)
    if not tot_v19.any():
        return df.iloc[:0].copy(), df.iloc[:0].copy()

    sub = df[tot_v19].copy()
    sub["_sv"] = sv[tot_v19]
    sub["_sc_adj"] = sc[tot_v19]
    sub["_is_v18"] = tot_v18[tot_v19]

    if require_elig:
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
        sub = sub[keep]

    sub = sub.sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True])
    taken_idx, fdt, fop = [], "", False
    for d2, grp in sub.groupby("buy_date", sort=True):
        if fdt == "" or d2 > fdt or (d2 == fdt and fop):
            if allow_next_rank:
                ok_g = grp[grp["sim_ok"].astype(bool)]
                if not ok_g.empty:
                    top = ok_g.iloc[0]
                    taken_idx.append(top.name)
                    fdt, fop = str(top["exit_date"]), bool(top["exit_at_open"])
            else:
                top = grp.iloc[0]
                if bool(top["sim_ok"]):
                    taken_idx.append(top.name)
                    fdt, fop = str(top["exit_date"]), bool(top["exit_at_open"])
    pass_df = sub[sub["sim_ok"].astype(bool)].copy().reset_index(drop=True)
    slot_df = sub.loc[taken_idx].copy().reset_index(drop=True) if taken_idx else sub.iloc[:0].copy()
    return pass_df, slot_df


def sim_2to3_custom(
    df: pd.DataFrame,
    score_vec: np.ndarray,
    thr: float | np.ndarray = 90.0,
    mask: Optional[np.ndarray] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate 2to3 using custom score_vec, threshold, and optional mask."""
    sc = np.asarray(score_vec, dtype=np.float64)
    m = (sc >= thr) & (~df["is_yizi"].to_numpy(bool)) & df["net_ret"].notna().to_numpy(bool)
    if mask is not None:
        m = m & np.asarray(mask, dtype=bool)
    sub = df[m].copy()
    if sub.empty:
        return sub, sub
    sub["_sc_adj"] = sc[m]
    srt = sub.sort_values(["buy_date", "_sc_adj", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
    t_idx, fdt, fhh = [], "", 0
    for r in srt.itertuples():
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            t_idx.append(r.Index)
            fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
    return srt.reset_index(drop=True), srt.loc[t_idx].copy().reset_index(drop=True)


def eval_v20_combined_30bps(bundle: dict, replace_slots: dict[str, pd.DataFrame]) -> dict:
    """Plug modified 1to2/2to3 WF slot_df (0.30% cost) into V20.0 6-strategy combined simulator."""
    parts = []
    trig_dts = {}
    cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig", "mtm_5y_30"]
    for st in m1.STRAT_ORDER:
        if st in replace_slots:
            df = replace_slots[st].copy()
            df = df[df["buy_date"].between(WF_START, WF_END)].copy()
            if not df.empty:
                df["strategy"] = st
                if "_sc_adj" in df.columns:
                    df["score"] = df["_sc_adj"].astype(float)
                elif "wf_score" in df.columns and df["wf_score"].notna().all():
                    df["score"] = df["wf_score"].astype(float)
                else:
                    df["score"] = df["v20_score"].astype(float)
                df["tier"] = "1to2_A(304.8-339.9)" if st == "1to2" else "2to3_A(90-95)"
                if st == "1to2":
                    df["tier"] = np.where(df["score"] >= 340.0, "1to2_S(>=340)", df["tier"])
                else:
                    df["tier"] = np.where(df["score"] >= 96.0, "2to3_S(>=96)", df["tier"])
                df["is_untrig"] = False
            trig_dts[st] = set(df["buy_date"]) if not df.empty else set()
            if not df.empty:
                parts.append(df[cols])
        else:
            sl = bundle["base_slots_30"][st]
            trig_dts[st] = set(sl["buy_date"])
            parts.append(sl[cols])

    pool6 = pd.concat(parts, ignore_index=True)
    ut = bundle["untrig"][bundle["untrig"]["buy_date"].between(WF_START, WF_END)].copy()
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut[(ut["strategy"] == st_u) & (~ut["buy_date"].isin(trig_dts.get(st_u, set())))].copy()
        if sub_u.empty:
            continue
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        ut_parts.append(sub_u)
    ut_final = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    if not ut_final.empty:
        ut_final["is_untrig"] = True
        ut_final["net_ret"] = 0.0
        ut_final["buy_price_val"] = np.nan
        ut_final["is_adj_px"] = False
        ut_final = ut_final[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig"]]

    mtm_map = {(r.strategy, r.buy_date, r.code): r.mtm_5y_30 for r in pool6.itertuples(index=False)}
    tr_df, _ = tpe.run_single_slot(pool6.drop(columns=["mtm_5y_30"]), lambda d: d["tier"].map(m1.S2C_MAP).fillna(999).to_numpy(), untrig_df=ut_final, timing_mode="s_tier_reserve_only")
    if tr_df.empty:
        return {"nav_wf": 1.0, "nav_2526": 1.0, "nav_y26": 1.0, "ex5_wf": 1.0, "mdd_pct": 0.0, "sharpe": 0.0, "n": 0}
    tr_df["mtm_5y_30"] = [mtm_map[(r.strategy, r.buy_date, r.code)] for r in tr_df.itertuples(index=False)]
    cal_wf = [d for d in bundle["cal_5y"] if WF_START <= d <= WF_END]
    idx_wf = {d: i for i, d in enumerate(cal_wf)}
    # Remap mtm_5y_30 indices from cal_5y to cal_wf
    off = bundle["cal_5y_idx"][cal_wf[0]]
    T = len(cal_wf)
    tr_df["mtm_wf"] = [tuple((ti - off, mult) for ti, mult in segs if 0 <= (ti - off) < T) for segs in tr_df["mtm_5y_30"]]
    ev = wfm.evaluate_wf_ledger(tr_df, None, tr_df.assign(can_buy_hygiene=True), bundle["v20_ctx"]["bench"], wf_start_dt=WF_START, end_dt=WF_END, mtm_col="mtm_wf", perm_n=10)
    fw, w25, w26 = ev["windows"]["FULL_WF"], ev["windows"]["Y2025_2026"], ev["windows"]["Y2026"]
    return {
        "n": fw["n"], "nav_wf": fw["nav"], "ex5_wf": fw["ex_top5_nav"], "mdd_pct": fw["daily_mdd_pct"], "sharpe": fw["daily_sharpe"],
        "nav_2526": w25["nav"], "nav_y26": w26["nav"], "n_target_strat": int((tr_df["strategy"] == list(replace_slots.keys())[0]).sum()) if len(replace_slots) == 1 else int(tr_df["strategy"].isin(replace_slots.keys()).sum()),
    }


def eval_variant_full(
    bundle: dict,
    strat: str,
    module: str,
    variant: str,
    pass_df: pd.DataFrame,
    slot_df: pd.DataFrame,
    perm_n: int = 1000,
    seed: int = 20261125,
) -> dict:
    """Evaluate single variant across FULL_WF, Y2025_2026, Y2026, 1000x perm, and V20 combined delta."""
    cand_df = bundle["p12"] if strat == "1to2" else bundle["p23"]
    cand_h = cand_df.assign(can_buy_hygiene=(~cand_df["is_yizi"].to_numpy(bool)) & cand_df["net_ret"].notna().to_numpy(bool))
    wf_cands = cand_h[cand_h["buy_date"] >= WF_START]

    s_wf = slot_df[slot_df["buy_date"].between(WF_START, WF_END)].copy().reset_index(drop=True)
    p_wf = pass_df[pass_df["buy_date"].between(WF_START, WF_END)].copy().reset_index(drop=True)
    cal_wf = [d for d in bundle["cal_5y"] if WF_START <= d <= WF_END]
    off = bundle["cal_5y_idx"][cal_wf[0]]
    T = len(cal_wf)
    if not s_wf.empty and "mtm_5y_30" in s_wf.columns:
        s_wf["mtm_wf"] = [tuple((ti - off, mult) for ti, mult in segs if 0 <= (ti - off) < T) for segs in s_wf["mtm_5y_30"]]
        mtm_c = "mtm_wf"
    else:
        mtm_c = None

    ev = wfm.evaluate_wf_ledger(s_wf, p_wf, wf_cands, bundle["v20_ctx"]["bench"], wf_start_dt=WF_START, end_dt=WF_END, mtm_col=mtm_c, perm_n=perm_n, seed=seed)
    fw = ev["windows"]["FULL_WF"]
    w25 = ev["windows"]["Y2025_2026"]
    w26 = ev["windows"]["Y2026"]
    pm = ev["permutation_1000"]

    comb = eval_v20_combined_30bps(bundle, {strat: s_wf})
    base_comb = bundle["base_comb_wf_30"]
    return {
        "strat": strat, "module": module, "variant": variant,
        "n_pass": int(len(p_wf)), "n_trades": fw.get("n", 0),
        "wr_pct": fw.get("wr_pct", 0.0), "plr": fw.get("plr", 0.0), "mean_pct": fw.get("mean_pct", 0.0),
        "nav_wf": fw.get("nav", 1.0), "eq_nav_wf": fw.get("eq_nav", 1.0), "ex5_wf": fw.get("ex_top5_nav", 1.0),
        "mdd_wf": fw.get("daily_mdd_pct", 0.0), "sharpe_wf": fw.get("daily_sharpe", 0.0),
        "excess_csi_wf": fw.get("excess_csi300_pp", 0.0), "excess_ew_wf": fw.get("excess_alla_ew_pp", 0.0),
        "n_2526": w25.get("n", 0), "wr_2526": w25.get("wr_pct", 0.0), "plr_2526": w25.get("plr", 0.0),
        "nav_2526": w25.get("nav", 1.0), "eq_nav_2526": w25.get("eq_nav", 1.0), "ex5_2526": w25.get("ex_top5_nav", 1.0),
        "mdd_2526": w25.get("daily_mdd_pct", 0.0), "excess_csi_2526": w25.get("excess_csi300_pp", 0.0),
        "n_y26": w26.get("n", 0), "wr_y26": w26.get("wr_pct", 0.0), "nav_y26": w26.get("nav", 1.0),
        "eq_nav_y26": w26.get("eq_nav", 1.0), "ex5_y26": w26.get("ex_top5_nav", 1.0),
        "mdd_y26": w26.get("daily_mdd_pct", 0.0), "excess_csi_y26": w26.get("excess_csi300_pp", 0.0),
        "perm_sd_p": pm["same_day_p_nav"], "perm_any_p": pm["any_cand_day_p_nav"],
        "comb_nav_wf": comb["nav_wf"],
        "comb_nav_ratio": round(comb["nav_wf"] / max(1e-9, base_comb["nav_wf"]), 4),
        "comb_2526_ratio": round(comb["nav_2526"] / max(1e-9, base_comb["nav_2526"]), 4),
        "comb_y26_ratio": round(comb["nav_y26"] / max(1e-9, base_comb["nav_y26"]), 4),
        "comb_ex5_ratio": round(comb["ex5_wf"] / max(1e-9, base_comb["ex5_wf"]), 4),
        "comb_mdd_delta": round(comb["mdd_pct"] - base_comb["mdd_pct"], 2),
        "comb_sharpe_delta": round(comb["sharpe"] - base_comb["sharpe"], 3),
        "comb_n_strat": comb["n_target_strat"],
    }
