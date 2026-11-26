#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 3-3 Red Team B - Part 2B1:
Build exact close-to-close daily MTM series (`dr_exact`, `dr_emp`, `dr_comb`) & slim ledgers
for ALL W2B5 (TrackC National Team ETF full 144-variant cross) and W2B6 (ModE US Gap incl.
us>=3/4/5/6% + daily/monthly, ModC EarnPre C1/C1b/C3).
Read-only on Wave 1/2 files. Single-thread, zero yfinance, RSS < 1.8 GB.
"""
import os

for _env in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_env] = "1"

import gc
import pickle
import resource
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD035_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125"
WAVE1_DIR = f"{RD035_DIR}/wave1_base"
W2B5_DIR = f"{RD035_DIR}/wave2b/w2b5_event_crossmarket_lowcorr_scorecard"
W2B6_DIR = f"{RD035_DIR}/wave2b/w2b6_empty_slot_blind_and_crossseat"
OUT_DIR = f"{RD035_DIR}/wave3_final/w3_3_redteam_audit_b"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (WAVE1_DIR, W2B5_DIR, W2B6_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import _wf_v20_patch as wfp
import _w2b5_common as wc5
import run_w2b5_track_c as r5c
import _w2b6_common as cm6
import run_w2b6_modE_us_gap as r6e
import run_w2b6_modC_notices as r6c


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def attach_mtm_segs_px_idx(
    df: pd.DataFrame,
    px_idx: cm6.PriceReturnIndex,
    cal_dts: list[str],
    buy_at: str = "open",
    fee_rt: float = 0.0030,
) -> pd.DataFrame:
    if df.empty:
        out = df.copy()
        out["mtm_segs"] = []
        return out
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    f_buy = fee_rt * 0.5
    f_sell_mult = (1.0 - fee_rt) / (1.0 - f_buy)
    segs_col = []
    for r in df.itertuples(index=False):
        c = str(r.code).zfill(6)
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        cid = px_idx.c6_to_id.get(c, -1)
        did0 = px_idx.dt_to_id.get(bd, -1)
        did1 = px_idx.dt_to_id.get(ed, -1)
        segs = []
        if cid >= 0 and did0 >= 0 and did1 >= 0 and cid in px_idx.bounds:
            s, e = px_idx.bounds[cid]
            dt_sub = px_idx.dt_id[s:e]
            p0 = int(np.searchsorted(dt_sub, did0))
            p1 = int(np.searchsorted(dt_sub, did1))
            if p0 < len(dt_sub) and int(dt_sub[p0]) == did0 and p1 < len(dt_sub) and int(dt_sub[p1]) == did1 and p1 > p0:
                g0, g1 = s + p0, s + p1
                ti0 = dt_idx.get(str(px_idx.dt_list[int(px_idx.dt_id[g0])]))
                if ti0 is not None:
                    m0 = ((float(px_idx.close[g0]) / float(px_idx.open[g0])) * (1.0 - f_buy)) if buy_at == "open" else (1.0 - f_buy)
                    segs.append((ti0, m0))
                for g in range(g0 + 1, g1 + 1):
                    tig = dt_idx.get(str(px_idx.dt_list[int(px_idx.dt_id[g])]))
                    if tig is None:
                        continue
                    ac_cur = float(px_idx.close[g]) * float(px_idx.adj_factor[g])
                    ac_prev = float(px_idx.close[g - 1]) * float(px_idx.adj_factor[g - 1])
                    mg = ac_cur / ac_prev
                    if g == g1:
                        mg *= f_sell_mult
                    segs.append((tig, mg))
        segs_col.append(segs)
    out = df.copy()
    out["mtm_segs"] = segs_col
    return out


def build_comb_and_emp_mtm(
    pass_df: pd.DataFrame,
    v20_ctx: dict,
    cal_dts: list[str],
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
    patch_mtm_col: str = "mtm_segs",
) -> dict:
    cal_df = v20_ctx["calendar_5y"]
    cal_win = cal_df[cal_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    empty_set = set(cal_win.loc[cal_win["v20_empty_slot"] & (~cal_win["v20_has_stier_wait"]), "trade_date"])

    p = pass_df.copy()
    p["buy_date"] = p["buy_date"].astype(str).str[:10]
    p["exit_date"] = p["exit_date"].astype(str).str[:10]
    p["code"] = p["code"].astype(str).str.zfill(6)
    p = p[p["buy_date"].between(wf_start_dt, end_dt) & (p["exit_date"] > p["buy_date"])].copy()
    if "buy_hhmm" not in p.columns:
        p["buy_hhmm"] = 925
    if "exit_hhmm" not in p.columns:
        p["exit_hhmm"] = 1500
    p["buy_hhmm"] = pd.to_numeric(p["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    p["exit_hhmm"] = pd.to_numeric(p["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    if "wf_score" not in p.columns:
        p["wf_score"] = 100.0
    p_top1 = p.sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()

    p_emp = p_top1[p_top1["buy_date"].isin(empty_set)].sort_values("buy_date").reset_index(drop=True)
    _, emp_slot_df = wfm.select_single_slot_trades(p_emp.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False)
    dr_emp, _ = wfm.build_daily_mtm_returns(emp_slot_df, cal_dts, mtm_col=patch_mtm_col)

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    events = []
    for r in v20_win.itertuples(index=False):
        events.append({
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
            "prio_src": 0, "is_wait": False, "source": "v20", "mtm_pairs": r.mtm_pairs,
        })
    for w in v20_ctx["v20_waits"]:
        if wf_start_dt <= w["buy_date"] <= end_dt and w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)"):
            events.append({
                "buy_date": w["buy_date"], "buy_hhmm": 935, "exit_date": w["buy_date"], "exit_hhmm": int(w["cancel_hhmm"]),
                "code": w["wait_code"], "strategy": w["wait_strategy"], "net_ret": 0.0,
                "prio_src": 0, "is_wait": True, "source": "v20_wait", "mtm_pairs": [],
            })
    for r in p_top1.itertuples(index=False):
        rec = {
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "strategy": "patch", "net_ret": float(r.net_ret),
            "prio_src": 1, "is_wait": False, "source": "patch", "mtm_pairs": [],
        }
        if patch_mtm_col and hasattr(r, patch_mtm_col):
            rec[patch_mtm_col] = getattr(r, patch_mtm_col)
        events.append(rec)

    ev_df = pd.DataFrame(events).sort_values(["buy_date", "prio_src", "buy_hhmm", "code"], ascending=[True, True, True, True]).reset_index(drop=True)
    taken_comb = []
    skipped_v20 = []
    cur_ed, cur_eh = "", 0
    for r in ev_df.itertuples(index=False):
        if r.source == "patch" and r.buy_date not in empty_set:
            continue
        can_enter = (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh)
        if can_enter:
            if not r.is_wait:
                taken_comb.append(r._asdict())
            cur_ed, cur_eh = r.exit_date, int(r.exit_hhmm)
        elif r.source == "v20":
            skipped_v20.append(float(r.net_ret))

    comb_df = pd.DataFrame(taken_comb) if taken_comb else pd.DataFrame(columns=["buy_date", "exit_date", "code", "strategy", "net_ret", "source", "mtm_pairs"])
    dr_comb, _ = wfp._build_combined_mtm(comb_df, cal_dts, patch_mtm_col=patch_mtm_col)
    n_patch_added = int((comb_df["source"] == "patch").sum()) if not comb_df.empty else 0
    return {
        "dr_emp": dr_emp,
        "dr_comb": dr_comb,
        "emp_slot_df": emp_slot_df,
        "n_patch_added": n_patch_added,
        "n_v20_skipped": int(len(skipped_v20)),
        "skipped_v20_prod": float(np.prod(1.0 + np.asarray(skipped_v20))) if skipped_v20 else 1.0,
    }


def sim_etf_yield_with_dr(
    etf_sub: pd.DataFrame,
    sig_mask: np.ndarray,
    v20_ctx: dict,
    cal_dts: list[str],
    px_lu: dict,
    max_hold_td: int,
    yield_scope: str,
    fee_rt: float = 0.0005,
) -> dict:
    """Exact mirror of r5c._sim_yield_to_v20 returning dr_patch (=dr_emp) and dr_comb."""
    cal5 = v20_ctx["calendar_5y"]
    cal_win = cal5[cal5["trade_date"].isin(cal_dts)].sort_values("trade_date").reset_index(drop=True)
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(cal_dts[0], cal_dts[-1])].copy().reset_index(drop=True)
    v20_by_buy = {d: g for d, g in v20_win.groupby("buy_date")}
    wait_dts = {w["buy_date"] for w in v20_ctx["v20_waits"] if w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)")}
    emp_strict = set(cal_win.loc[cal_win["v20_empty_strict_no_stier_wait"], "trade_date"])

    etf_m = pd.DataFrame({"date": cal_dts}).merge(etf_sub, on="date", how="left")
    etf_sig_map = {str(d): bool(s) for d, s in zip(etf_sub["date"], sig_mask)}
    sig_aligned = np.array([etf_sig_map.get(d, False) for d in cal_dts], dtype=bool)
    opens = etf_m["open"].to_numpy(float)
    closes = etf_m["close"].to_numpy(float)
    code = str(etf_sub["code"].iloc[0]).zfill(6)

    patch_trades, comb_trades, skipped_v20 = [], [], []
    in_etf, in_v20_until_idx, in_v20_exit_hh = False, -1, 0
    etf_buy_i, etf_bpx, etf_rem = -1, 0.0, 0

    for i, d in enumerate(cal_dts):
        v20_free_morning = in_v20_until_idx < i
        v20_today = v20_by_buy.get(d)
        is_st_wait = d in wait_dts

        if in_etf:
            v20_wants_morning = False
            if v20_free_morning:
                if is_st_wait:
                    v20_wants_morning = True
                elif v20_today is not None:
                    if yield_scope == "all_v20" or (v20_today["buy_hhmm"] == 925).any():
                        v20_wants_morning = True
            if v20_wants_morning and np.isfinite(opens[i]) and opens[i] > 0:
                epx = opens[i]
                gr = float(epx / etf_bpx - 1.0)
                nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
                tr = {
                    "buy_date": cal_dts[etf_buy_i], "exit_date": d,
                    "buy_hhmm": 925, "exit_hhmm": 924,
                    "code": code, "strategy": "patch_yield",
                    "buy_px": etf_bpx, "exit_px": epx,
                    "gross_ret": gr, "net_ret": nr, "source": "patch", "mtm_pairs": [],
                }
                patch_trades.append(tr)
                comb_trades.append(tr)
                in_etf = False

        if v20_today is not None:
            for r in v20_today.itertuples(index=False):
                can_enter_v20 = (not in_etf) and ((in_v20_until_idx < i) or (in_v20_until_idx == i and int(r.buy_hhmm) > in_v20_exit_hh))
                if can_enter_v20:
                    comb_trades.append({
                        "buy_date": r.buy_date, "exit_date": r.exit_date,
                        "buy_hhmm": int(r.buy_hhmm), "exit_hhmm": int(r.exit_hhmm),
                        "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
                        "source": "v20", "mtm_pairs": r.mtm_pairs,
                    })
                    in_v20_until_idx = dt_idx.get(r.exit_date, i)
                    in_v20_exit_hh = int(r.exit_hhmm)
                    break
                elif in_etf:
                    skipped_v20.append(float(r.net_ret))
                    break

        if in_v20_until_idx < i and is_st_wait and not in_etf:
            in_v20_until_idx = max(in_v20_until_idx, i)
            in_v20_exit_hh = max(in_v20_exit_hh, 1500)

        if in_etf:
            etf_rem = (max_hold_td - 1) if sig_aligned[i] else (etf_rem - 1)
            if (etf_rem <= 0 or i == T - 1) and np.isfinite(closes[i]) and closes[i] > 0:
                epx = closes[i]
                gr = float(epx / etf_bpx - 1.0)
                nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
                tr = {
                    "buy_date": cal_dts[etf_buy_i], "exit_date": d,
                    "buy_hhmm": 925, "exit_hhmm": 1500,
                    "code": code, "strategy": "patch_hold",
                    "buy_px": etf_bpx, "exit_px": epx,
                    "gross_ret": gr, "net_ret": nr, "source": "patch", "mtm_pairs": [],
                }
                patch_trades.append(tr)
                comb_trades.append(tr)
                in_etf = False
                continue

        if (not in_etf) and (d in emp_strict) and sig_aligned[i] and i < T - 1:
            if np.isfinite(opens[i]) and opens[i] > 0:
                in_etf = True
                etf_buy_i = i
                etf_bpx = opens[i]
                etf_rem = max_hold_td - 1

    patch_df = pd.DataFrame(patch_trades)
    comb_df = pd.DataFrame(comb_trades)
    if not patch_df.empty:
        patch_df = wc5.build_mtm_segs_for_df(patch_df, cal_dts, px_lu, fee_rt=fee_rt, end_cap_dt=cal_dts[-1])
    if not comb_df.empty:
        p_only = comb_df[comb_df["source"] == "patch"].copy()
        if not p_only.empty:
            p_only = wc5.build_mtm_segs_for_df(p_only, cal_dts, px_lu, fee_rt=fee_rt, end_cap_dt=cal_dts[-1])
            comb_df["mtm_segs"] = [[] for _ in range(len(comb_df))]
            comb_df.loc[comb_df["source"] == "patch", "mtm_segs"] = p_only["mtm_segs"].values
        else:
            comb_df["mtm_segs"] = [[] for _ in range(len(comb_df))]

    dr_comb, _ = wfp._build_combined_mtm(comb_df, cal_dts, patch_mtm_col="mtm_segs")
    dr_patch, diff_p = wfm.build_daily_mtm_returns(patch_df, cal_dts, mtm_col="mtm_segs")
    return {
        "slot_df": patch_df[["buy_date", "exit_date", "code", "net_ret"]].copy() if not patch_df.empty else pd.DataFrame(columns=["buy_date", "exit_date", "code", "net_ret"]),
        "emp_slot_df": patch_df[["buy_date", "exit_date", "code", "net_ret"]].copy() if not patch_df.empty else pd.DataFrame(columns=["buy_date", "exit_date", "code", "net_ret"]),
        "dr_exact": dr_patch,
        "dr_emp": dr_patch,
        "dr_comb": dr_comb,
        "n_patch_added": int(len(patch_df)),
        "n_v20_skipped": int(len(skipped_v20)),
        "skipped_v20_prod": float(np.prod(1.0 + np.asarray(skipped_v20))) if skipped_v20 else 1.0,
        "diff": float(diff_p),
    }


def slim_df(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["buy_date", "exit_date", "code", "net_ret", "wf_score"] if c in df.columns]
    return df[cols].copy() if not df.empty else pd.DataFrame(columns=["buy_date", "exit_date", "code", "net_ret"])


def run_scorecard_pack(
    cand_df: pd.DataFrame,
    fcols: list[str],
    px_idx: cm6.PriceReturnIndex,
    v20_ctx: dict,
    cal_dts_wf: list[str],
    recalc_freq: str,
    thresholds: tuple,
    min_w: int,
    min_wr: int,
    top_k: int = 12,
) -> dict:
    res = wf.run_wf_scorecard_new_strategy(
        cand_df,
        feature_cols=fcols,
        v20_ctx=v20_ctx,
        wf_start_date="2023-01-03",
        end_date="2026-11-16",
        min_warmup_trades=min_w,
        min_warmup_trades_rare=min_wr,
        min_warmup_months=18,
        recalc_freq=recalc_freq,
        top_k=top_k,
        min_k=min(5, len(fcols)),
        max_corr=0.65,
        min_t_stat=1.0,
        shrink_tau=20.0,
        fee_rt=0.0030,
        gross_ret_col="gross_ret",
        thresholds=thresholds,
        eval_v20_patch=False,
        perm_n=0,
    )
    actual_wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
    out = {}
    for th_name, obj in res["threshold_results"].items():
        slot_df = obj["slot_df"]
        pass_df = obj["pass_df"]
        dr_exact, diff = px_idx.compute_exact_mtm_series(slot_df, cal_dts_wf, buy_at="open", fee_rt=0.0030)
        if th_name != "all_cands" and not pass_df.empty:
            pass_mtm = attach_mtm_segs_px_idx(pass_df, px_idx, cal_dts_wf, buy_at="open", fee_rt=0.0030)
            p_res = build_comb_and_emp_mtm(pass_mtm, v20_ctx, cal_dts_wf, wf_start_dt="2023-01-03", end_dt="2026-11-16", patch_mtm_col="mtm_segs")
        else:
            p_res = {
                "dr_emp": np.zeros(len(cal_dts_wf)),
                "dr_comb": None,
                "emp_slot_df": pd.DataFrame(columns=["buy_date", "exit_date", "code", "net_ret"]),
                "n_patch_added": 0,
                "n_v20_skipped": 0,
                "skipped_v20_prod": 1.0,
            }
        out[th_name] = {
            "wf_actual_start": actual_wf_start,
            "n_cands_total": int(len(cand_df)),
            "n_pass": int(obj["n_passing_cands"]),
            "slot_df": slim_df(slot_df),
            "emp_slot_df": slim_df(p_res["emp_slot_df"]),
            "dr_exact": dr_exact,
            "dr_emp": p_res["dr_emp"],
            "dr_comb": p_res["dr_comb"],
            "n_patch_added": p_res["n_patch_added"],
            "n_v20_skipped": p_res["n_v20_skipped"],
            "skipped_v20_prod": p_res["skipped_v20_prod"],
            "diff": float(diff),
        }
    del res
    gc.collect()
    return out


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(WAVE1_DIR)
    cal5 = v20_ctx["calendar_5y"]
    cal_wf = cal5[cal5["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    cal_dts_wf = cal_wf["trade_date"].tolist()

    tracks = {}

    # -------------------------------------------------------------------------
    # PART A: W2B5 TrackC National Team ETF Full 144-Variant Cross
    # -------------------------------------------------------------------------
    etf_df = wc5.build_or_load_clean_etf_cache()
    mkt_df = pd.read_parquet(r5c.MKT_PIT_PQ)
    px_lu = r5c._build_etf_px_lookup(etf_df)
    t_etf = {}
    for code in ("512100", "510300"):
        esub = etf_df[etf_df["code"] == code].sort_values("date").reset_index(drop=True)
        esub = esub.merge(
            mkt_df[["trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1"]],
            left_on="date", right_on="trade_date", how="left",
        )
        for sig_lbl, sig_col in (("V3Live", "nt_v3_score_live_t1"), ("V3EOD", "nt_v3_score_eod_t1")):
            for thr in (50, 55, 60, 65):
                sig_m = (esub[sig_col].fillna(0.0) >= float(thr)).to_numpy(bool)
                for hold_d in (5, 10, 20):
                    ext_fl = (hold_d == 20)
                    # FixedRule
                    tr_df = r5c._build_etf_trades_from_signal(esub, sig_m, hold_td=hold_d, extend_on_retrig=ext_fl, fee_rt=r5c.ETF_FEE_RT)
                    tr_wf = tr_df[tr_df["buy_date"].between("2023-01-03", "2026-11-16")].copy().reset_index(drop=True)
                    tr_wf = wc5.build_mtm_segs_for_df(tr_wf, cal_dts_wf, px_lu, fee_rt=r5c.ETF_FEE_RT, end_cap_dt="2026-11-16")
                    _, slot_wf = wfm.select_single_slot_trades(tr_wf.assign(can_buy_hygiene=True), score_col="wf_score", threshold=None, wf_only=False)
                    dr_exact, diff = wfm.build_daily_mtm_returns(slot_wf, cal_dts_wf, mtm_col="mtm_segs")
                    p_res = build_comb_and_emp_mtm(tr_wf, v20_ctx, cal_dts_wf, wf_start_dt="2023-01-03", end_dt="2026-11-16", patch_mtm_col="mtm_segs")
                    vid = f"C_{code}_{sig_lbl}_ge{thr}_H{hold_d}"
                    t_etf[vid] = {
                        "wf_actual_start": "2023-01-03",
                        "slot_df": slim_df(slot_wf),
                        "emp_slot_df": slim_df(p_res["emp_slot_df"]),
                        "dr_exact": dr_exact,
                        "dr_emp": p_res["dr_emp"],
                        "dr_comb": p_res["dr_comb"],
                        "n_patch_added": p_res["n_patch_added"],
                        "n_v20_skipped": p_res["n_v20_skipped"],
                        "skipped_v20_prod": p_res["skipped_v20_prod"],
                        "diff": float(diff),
                    }
                    # Yield_all_v20 & Yield_open_0925_only
                    for y_scope in ("all_v20", "open_0925_only"):
                        y_res = sim_etf_yield_with_dr(esub, sig_m, v20_ctx, cal_dts_wf, px_lu, max_hold_td=hold_d, yield_scope=y_scope, fee_rt=r5c.ETF_FEE_RT)
                        t_etf[f"{vid}_Yield_{y_scope}"] = {
                            "wf_actual_start": "2023-01-03",
                            "slot_df": y_res["slot_df"],
                            "emp_slot_df": y_res["emp_slot_df"],
                            "dr_exact": y_res["dr_exact"],
                            "dr_emp": y_res["dr_emp"],
                            "dr_comb": y_res["dr_comb"],
                            "n_patch_added": y_res["n_patch_added"],
                            "n_v20_skipped": y_res["n_v20_skipped"],
                            "skipped_v20_prod": y_res["skipped_v20_prod"],
                            "diff": y_res["diff"],
                        }
    tracks["TrackC_NT_ETF"] = t_etf
    del etf_df, mkt_df, px_lu
    gc.collect()
    print(f"[TrackC ETF] {len(t_etf)} variants built | RSS={rss_mb()} MB", flush=True)

    # -------------------------------------------------------------------------
    # Load Compact PriceReturnIndex ONCE for ModE + ModC
    # -------------------------------------------------------------------------
    px_idx = cm6.PriceReturnIndex(end_cutoff="2026-11-25")
    print(f"[PriceReturnIndex loaded] RSS={rss_mb()} MB", flush=True)

    # -------------------------------------------------------------------------
    # PART B: W2B6 ModE US Bottleneck Gap (us>=3/4/5/6% x daily/monthly + E1/E2)
    # -------------------------------------------------------------------------
    cal_cn = sorted([d for d in v20_ctx["bench"]["trade_date"].tolist() if "2021-01-04" <= d <= "2026-11-16"])
    map_df, us_p = r6e.load_us_leaders_map()
    cn_dt_df = pd.DataFrame({"buy_date": cal_cn, "cn_ts": pd.to_datetime(cal_cn)}).sort_values("cn_ts")
    us_p["us_ts"] = pd.to_datetime(us_p["us_date"])
    aligned_list = []
    for utk, grp in us_p.groupby("ticker"):
        m = pd.merge_asof(cn_dt_df, grp.sort_values("us_ts"), left_on="cn_ts", right_on="us_ts", direction="backward", allow_exact_matches=False)
        m["us_ticker"] = utk
        aligned_list.append(m[["buy_date", "us_ticker", "us_ret1d", "us_ret3d", "us_vol_r20"]])
    us_cn = pd.concat(aligned_list, ignore_index=True)

    # Filter us_ret1d >= 3.0 & us_vol_r20 >= 1.4
    us_trig = us_cn[(us_cn["us_ret1d"] >= 3.0) & (us_cn["us_vol_r20"] >= 1.4)].copy()
    cands_e = us_trig.merge(map_df, on="us_ticker", how="inner")
    cands_e["abs_r"] = cands_e["us_ret1d"].abs()
    cands_e = cands_e.sort_values(["buy_date", "code", "abs_r"], ascending=[True, True, False]).drop_duplicates(["buy_date", "code"]).drop(columns=["abs_r", "tree_name", "us_ticker"]).reset_index(drop=True)

    horizons = (1, 3, 5)
    ret_e = px_idx.lookup_forward_returns(cands_e, horizons=horizons, buy_at="open", min_amt_yi=0.0)
    ret_e = ret_e[ret_e["can_buy"]].copy().reset_index(drop=True)
    op_vals = np.full(len(ret_e), np.nan, dtype=np.float32)
    for idx_r, (c_r, d_r) in enumerate(zip(ret_e["code"], ret_e["buy_date"])):
        cid = px_idx.c6_to_id.get(c_r, -1)
        did = px_idx.dt_to_id.get(d_r, -1)
        if cid >= 0 and did >= 0:
            s, e = px_idx.bounds[cid]
            dt_sub = px_idx.dt_id[s:e]
            rel = int(np.searchsorted(dt_sub, did))
            if rel < len(dt_sub) and int(dt_sub[rel]) == did:
                op_vals[idx_r] = px_idx.open_pct[s + rel]
    ret_e = ret_e[(op_vals >= -2.0) & (op_vals <= 3.0)].reset_index(drop=True)
    # Attach PIT features separately for E3 (all us>=3% mingmen) + E1/E2 (us>=4% all) to keep merge super small!
    sub_e13 = ret_e[(ret_e["is_mingmen_node"] == 1) | (ret_e["us_ret1d"] >= 4.0)].copy().reset_index(drop=True)
    feat_e, fcols_e = cm6.attach_pit_features(sub_e13, buy_at="open", extra_cols=["us_ret1d", "us_ret3d", "us_vol_r20", "is_mingmen_node"])
    feat_e = feat_e[feat_e["can_buy"] & (feat_e["amount_yi_t1"] >= 0.8)].copy().reset_index(drop=True)
    feat_e["us_a_unpriced_gap"] = feat_e["us_ret1d"] - feat_e["open_pct"]
    fcols_e = fcols_e + ["us_a_unpriced_gap"]
    del us_cn, us_trig, cands_e, ret_e, sub_e13, map_df, us_p
    gc.collect()

    e_specs = [
        ("E3_US3pct_Mingmen_H1_daily", (feat_e["us_ret1d"] >= 3.0) & (feat_e["is_mingmen_node"] == 1), 1, "daily"),
        ("E3_US3pct_Mingmen_H1_monthly", (feat_e["us_ret1d"] >= 3.0) & (feat_e["is_mingmen_node"] == 1), 1, "monthly"),
        ("E3_US4pct_Mingmen_H1_daily", (feat_e["us_ret1d"] >= 4.0) & (feat_e["is_mingmen_node"] == 1), 1, "daily"),
        ("E3_US4pct_Mingmen_H1_monthly", (feat_e["us_ret1d"] >= 4.0) & (feat_e["is_mingmen_node"] == 1), 1, "monthly"),
        ("E3_US5pct_Mingmen_H1_daily", (feat_e["us_ret1d"] >= 5.0) & (feat_e["is_mingmen_node"] == 1), 1, "daily"),
        ("E3_US5pct_Mingmen_H1_monthly", (feat_e["us_ret1d"] >= 5.0) & (feat_e["is_mingmen_node"] == 1), 1, "monthly"),
        ("E3_US6pct_Mingmen_H1_daily", (feat_e["us_ret1d"] >= 6.0) & (feat_e["is_mingmen_node"] == 1), 1, "daily"),
        ("E3_US6pct_Mingmen_H1_monthly", (feat_e["us_ret1d"] >= 6.0) & (feat_e["is_mingmen_node"] == 1), 1, "monthly"),
        ("E3_US4pct_Mingmen_H3_monthly", (feat_e["us_ret1d"] >= 4.0) & (feat_e["is_mingmen_node"] == 1), 3, "monthly"),
        ("E3_US4pct_Mingmen_H3_daily", (feat_e["us_ret1d"] >= 4.0) & (feat_e["is_mingmen_node"] == 1), 3, "daily"),
        ("E3_US4pct_Mingmen_H5_monthly", (feat_e["us_ret1d"] >= 4.0) & (feat_e["is_mingmen_node"] == 1), 5, "monthly"),
        ("E1_US4pct_All_H1_monthly", (feat_e["us_ret1d"] >= 4.0), 1, "monthly"),
        ("E1_US4pct_All_H1_daily", (feat_e["us_ret1d"] >= 4.0), 1, "daily"),
        ("E2_US6pct2xVol_H1_daily", (feat_e["us_ret1d"] >= 6.0) & (feat_e["us_vol_r20"] >= 2.0) & (feat_e["open_pct"].between(-1.5, 2.5)), 1, "daily"),
    ]
    t_mode = {}
    th_e = ("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80)
    for sp_id, mask, h, rfreq in e_specs:
        sub = feat_e[mask].copy()
        sub["exit_date"] = sub[f"exit_date_h{h}"]
        sub["gross_ret"] = sub[f"gross_ret_h{h}"]
        sub = sub[(sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
        min_w = 80 if len(sub) >= 1500 else 35
        min_wr = 40 if len(sub) >= 1500 else 20
        pack = run_scorecard_pack(sub, fcols_e, px_idx, v20_ctx, cal_dts_wf, rfreq, th_e, min_w, min_wr, top_k=12)
        for th_name, v in pack.items():
            t_mode[f"{sp_id}::{th_name}"] = v
    tracks["ModE_USGap"] = t_mode
    del feat_e
    gc.collect()
    print(f"[ModE USGap] {len(t_mode)} variants built | RSS={rss_mb()} MB", flush=True)

    # -------------------------------------------------------------------------
    # PART C: W2B6 ModC Earnings Pre-Announcement & Contract/Ice Islands
    # -------------------------------------------------------------------------
    cal_all = np.array(sorted(v20_ctx["bench"]["trade_date"].tolist()))
    earn_df = r6c.load_earnings_pre_islands(cal_all, end_cutoff="2026-11-16")
    name_map = r6c.build_pit_name_map(end_cutoff="2026-11-16")
    cont_df = r6c.load_contract_islands(cal_all, name_map, end_cutoff="2026-11-16")

    e_ret = px_idx.lookup_forward_returns(earn_df, horizons=horizons, buy_at="open", min_amt_yi=0.0)
    e_extra = ["cat_yoy_mid_pct", "cat_np_ann_yi", "cat_is_kfe", "cat_is_niukui", "cat_is_yuzeng", "cat_imp_ey_pct"]
    e_feat, fcols_ce = cm6.attach_pit_features(e_ret, buy_at="open", extra_cols=e_extra)
    e_feat["cat_imp_ey_pct"] = np.where(e_feat["mcap_yi_t1"] > 0, e_feat["cat_np_ann_yi"] / e_feat["mcap_yi_t1"] * 100.0, np.nan)
    e_clean = e_feat[e_feat["can_buy"] & (e_feat["amount_yi_t1"] >= 0.5) & (e_feat["ret_20d_t1"].fillna(0.0) < 15.0) & (e_feat["prev_streak"] == 0)].copy().reset_index(drop=True)
    e_lowheat = e_clean[((e_clean["cat_yoy_mid_pct"] >= 80.0) | (e_clean["cat_is_niukui"] == 1)) & (e_clean["xq_posts_1y_pct"].fillna(0.5) <= 0.55)].copy().reset_index(drop=True)

    c_ret = px_idx.lookup_forward_returns(cont_df, horizons=horizons, buy_at="open", min_amt_yi=0.0)
    c_extra = ["cat_amt_yi", "cat_rev_pct", "cat_src_cninfo", "cat_amt_to_mcap_pct"]
    c_feat, fcols_cc = cm6.attach_pit_features(c_ret, buy_at="open", extra_cols=c_extra)
    c_clean = c_feat[c_feat["can_buy"] & (c_feat["amount_yi_t1"] >= 0.4) & (c_feat["ret_20d_t1"].fillna(0.0) < 15.0) & (c_feat["prev_streak"] == 0)].copy().reset_index(drop=True)

    e_sub = e_clean[["buy_date", "code", "can_buy", "is_yizi", "buy_hhmm", "exit_hhmm", "exit_date_h1", "gross_ret_h1", "exit_date_h3", "gross_ret_h3", "exit_date_h5", "gross_ret_h5"]].copy()
    e_sub["cat_type"] = 1
    c_sub = c_clean[["buy_date", "code", "can_buy", "is_yizi", "buy_hhmm", "exit_hhmm", "exit_date_h1", "gross_ret_h1", "exit_date_h3", "gross_ret_h3", "exit_date_h5", "gross_ret_h5"]].copy()
    c_sub["cat_type"] = 2
    comb_raw = pd.concat([e_sub, c_sub], ignore_index=True).drop_duplicates(["buy_date", "code"]).reset_index(drop=True)
    comb_feat, fcols_comb = cm6.attach_pit_features(comb_raw, buy_at="open", extra_cols=["cat_type"])
    comb_ice = comb_feat[comb_feat["L1_sent_phase_t1"].isin([1, 2, 5])].copy().reset_index(drop=True)
    del earn_df, cont_df, e_ret, e_feat, c_ret, c_feat, c_clean, e_sub, c_sub, comb_raw, comb_feat
    gc.collect()

    c_specs = [
        ("ModC_C1_EarnPre_NoRun", e_clean, fcols_ce, (1, 3, 5)),
        ("ModC_C1b_EarnPre_HighLowHeat", e_lowheat, fcols_ce, (1, 3)),
        ("ModC_C3_Cat_IceWeakRegime", comb_ice, fcols_comb, (1, 3, 5)),
    ]
    t_modc = {}
    th_c = ("all_cands", "top30", "top20", "top10", "top5", 70, 75)
    for cname, cdf, cfcols, chs in c_specs:
        for h in chs:
            sub = cdf.copy()
            sub["exit_date"] = sub[f"exit_date_h{h}"]
            sub["gross_ret"] = sub[f"gross_ret_h{h}"]
            sub = sub[(sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
            min_w = 80 if len(sub) >= 1200 else 35
            min_wr = 40 if len(sub) >= 1200 else 20
            pack = run_scorecard_pack(sub, cfcols, px_idx, v20_ctx, cal_dts_wf, "daily", th_c, min_w, min_wr, top_k=12)
            for th_name, v in pack.items():
                t_modc[f"{cname}_H{h}::{th_name}"] = v
    tracks["ModC_EarnPre"] = t_modc
    print(f"[ModC EarnPre] {len(t_modc)} variants built | RSS={rss_mb()} MB", flush=True)

    out_pkl = f"{OUT_DIR}/_cache_tracks_b5_b6.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(tracks, f)
    print(f"[Part 2B1 DONE in {time.time()-t0:.1f}s] Saved -> {out_pkl} | Peak RSS={rss_mb()} MB", flush=True)


if __name__ == "__main__":
    main()
