#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Step 3 — Family 3: Official Announcements & Interactive Q&A Event-Driven Strategies
  - E_PERF: Earnings forecast (预增/扭亏/略增) + Express (业绩快报 2021-2026 complete via DB + Akshare)
  - E_BUYBACK: Share Repurchase plans + Shareholder/Exec Increases (2021-2026 complete via Akshare)
  - E_IRQA: CNINFO Investor Relations Q&A activity surge (strictly fixed CST causality)
Tests multi-slot equal-weight rolling portfolio + strict expanding causal scorecard Top-K (exit_date < t),
5d/10d/20d holding windows, >=50m & >=200m liquidity, 30bp/50bp costs, and ex-top5 trades.
Zero yfinance (D12). Peak RAM < 1.5 GB.
"""
import gc
import json
import os
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD044_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
if RD044_DIR not in sys.path:
    sys.path.insert(0, RD044_DIR)

import _rd044_common as cm
import step1_family1_xs_stat_rev as f1
import step2_family2_smallcap_timing as f2

CACHE_DIR = cm.CACHE_DIR


def _next_trading_day(date_series: pd.Series, cal_arr: np.ndarray) -> np.ndarray:
    """Strictly map announcement date D (without intraday pre-09:15 proof) to next trading day > D."""
    d_str = pd.to_datetime(date_series, errors="coerce").dt.strftime("%Y-%m-%d").fillna("").values
    pos = np.searchsorted(cal_arr, d_str, side="right")  # strictly > D
    valid = (d_str != "") & (pos < len(cal_arr))
    out = np.where(valid, cal_arr[np.minimum(pos, len(cal_arr) - 1)], "")
    return out


def build_unified_event_tables(cal_dts: list[str]) -> dict:
    """Merge DB + Akshare 5Y caches into strictly causal event tables aligned to cal_dts."""
    cal_arr = np.array(cal_dts)

    # 1. E_PERF: CNINFO DB 业绩预告 + Akshare 5Y 业绩快报
    p_db = pd.read_parquet(f"{CACHE_DIR}/events_perf_pit.parquet")
    p_db["is_kb_em"] = p_db["ann_type"].eq("业绩快报").astype(int)
    p_db["growth_pct"] = p_db["g_mid"]

    kb_raw = pd.read_parquet(f"{CACHE_DIR}/ak_yjkb_raw.parquet")
    kb_raw["c6"] = kb_raw["股票代码"].astype(str).str.zfill(6)
    kb_raw["buy_date"] = _next_trading_day(kb_raw["公告日期"], cal_arr)
    kb_raw["growth_pct"] = pd.to_numeric(kb_raw["净利润-同比增长"], errors="coerce")
    kb_raw["ann_type"] = "业绩快报"
    kb_raw["is_nk"] = 0
    kb_raw["is_yz"] = (kb_raw["growth_pct"] >= 30.0).astype(int)
    kb_raw["is_kb"] = 1
    kb_clean = kb_raw[kb_raw["buy_date"] != ""][["c6", "buy_date", "ann_type", "growth_pct", "is_nk", "is_yz", "is_kb"]].copy()

    p_db_c = p_db[["c6", "buy_date", "ann_type", "growth_pct", "is_nk", "is_yz", "is_kb"]].copy()
    perf = pd.concat([p_db_c, kb_clean], ignore_index=True)
    perf = perf[perf["buy_date"].between("2021-01-04", "2026-11-24")].copy()
    perf = perf.sort_values(["c6", "buy_date", "is_yz", "is_nk", "growth_pct"], ascending=[True, True, False, False, False], na_position="last")
    perf = perf.drop_duplicates(subset=["c6", "buy_date"], keep="first").reset_index(drop=True)

    # 2. E_BUYBACK: Akshare Repurchase (回购起始时间 -> > D) + Shareholder Increase (公告日 -> > D)
    rep = pd.read_parquet(f"{CACHE_DIR}/ak_repurchase_raw.parquet")
    rep["c6"] = rep["股票代码"].astype(str).str.zfill(6)
    rep["buy_date"] = _next_trading_day(rep["回购起始时间"], cal_arr)
    rep["plan_amt_yi"] = pd.to_numeric(rep["计划回购金额区间-上限"], errors="coerce").fillna(0.0) / 1e8
    rep["sub"] = "repurchase"
    rep_c = rep[rep["buy_date"].between("2021-01-04", "2026-11-24")][["c6", "buy_date", "sub", "plan_amt_yi"]].copy()

    gg = pd.read_parquet(f"{CACHE_DIR}/ak_ggcg_inc_raw.parquet")
    gg["c6"] = gg["代码"].astype(str).str.zfill(6)
    gg["buy_date"] = _next_trading_day(gg["公告日"], cal_arr)
    gg["plan_amt_yi"] = pd.to_numeric(gg["持股变动信息-占总股本比例"], errors="coerce").fillna(0.0)  # pct stake
    gg["sub"] = "shareholder_inc"
    gg_c = gg[gg["buy_date"].between("2021-01-04", "2026-11-24")][["c6", "buy_date", "sub", "plan_amt_yi"]].copy()

    bb = pd.concat([rep_c, gg_c], ignore_index=True)
    bb = bb.sort_values(["c6", "buy_date", "sub"]).drop_duplicates(subset=["c6", "buy_date"], keep="first").reset_index(drop=True)

    # 3. E_IRQA: Trailing 5d vs 60d IR burst strictly up to T 09:25
    ir = pd.read_parquet(f"{CACHE_DIR}/events_irqa_pit.parquet")
    ir = ir[ir["buy_date"].between("2021-01-04", "2026-11-24")].copy()

    print(f"[Family3] Event tables: E_PERF={len(perf)}, E_BUYBACK={len(bb)} (rep={len(rep_c)}, inc={len(gg_c)}), E_IRQA_days={len(ir)}")
    return {"perf": perf, "buyback": bb, "irqa": ir}


def simulate_event_portfolio(
    panel: dict,
    events_df: pd.DataFrame,
    hold_days: int = 10,
    max_slots: int = 20,
    max_per_day: int = 3,
    fee_rt: float = 0.0030,
    use_wf_scorecard: bool = False,
    scorecard_top_pct: float = 0.30,
    start_dt: str = "2021-01-04",
    end_dt: str = "2026-11-24",
) -> dict:
    """
    Exact daily MTM multi-slot event portfolio simulator:
      - `events_df` has columns: ['c6', 'buy_date', 'feat_score'] (+ optional T-1 features for WF scorecard).
      - Entry at `buy_date` open (only if eligible, not limit-up/suspended).
      - Exit at `buy_date + hold_days` open (or delayed if suspended/one-word limit-down).
      - Strictly causal expanding logistic/linear rank scorecard (`exit_date < t`) when `use_wf_scorecard=True`.
      - Returns daily MTM returns, turnover, active mask, capacity, and closed trade ledger!
    """
    cal_dts = panel["cal_dts"]
    dt_map = {d: i for i, d in enumerate(cal_dts)}
    stk_map = {s: i for i, s in enumerate(panel["stocks"])}
    N_D = len(cal_dts)

    trad = panel["tradable"]
    can_buy = panel["can_buy_open"]
    adj_open = panel["adj_open"]
    adj_close = panel["adj_close"]
    sell_px = panel["sell_exec_adj"]
    amt20 = panel["amt20_t1"]

    fee_buy = fee_rt * (1.0 / 3.0)
    fee_sell = fee_rt * (2.0 / 3.0)

    # Precompute potential trade outcomes ONLY for causal WF scorecard training (only visible when actual_exit_idx < t!)
    # Group candidate events by buy_idx
    ev = events_df.copy()
    ev["di"] = ev["buy_date"].map(dt_map)
    ev["si"] = ev["c6"].map(stk_map)
    ev = ev.dropna(subset=["di", "si"]).copy()
    ev["di"] = ev["di"].astype(int)
    ev["si"] = ev["si"].astype(int)
    ev = ev[ev["buy_date"].between(start_dt, end_dt)].sort_values(["di", "si"]).reset_index(drop=True)

    # Pre-attach T-1 features from dense panel for WF scorecard
    f_cols = ["F_TURN_ABN", "F_LOWVOL", "F_REV10", "F_ON20", "amt20_t1"]
    di_arr = ev["di"].values
    si_arr = ev["si"].values
    feat_mat = np.column_stack([
        np.nan_to_num(panel["F_TURN_ABN"][di_arr, si_arr], nan=0.0),
        np.nan_to_num(panel["F_LOWVOL"][di_arr, si_arr], nan=0.0),
        np.nan_to_num(panel["F_REV10"][di_arr, si_arr], nan=0.0),
        np.nan_to_num(panel["F_ON20"][di_arr, si_arr], nan=0.0),
        np.nan_to_num(ev["ev_strength"].values if "ev_strength" in ev.columns else np.zeros(len(ev)), nan=0.0),
    ])

    by_di = {}
    for idx_r in range(len(ev)):
        d_i = int(di_arr[idx_r])
        by_di.setdefault(d_i, []).append(idx_r)

    # Active positions: list of dicts {si, qty, entry_di, target_exit_di, entry_px, entry_nav_wt, last_px, buy_amt}
    positions = []
    cash = 1.0
    nav_prev = 1.0
    dr = np.zeros(N_D, dtype=np.float64)
    to_daily = np.zeros(N_D, dtype=np.float64)
    act_mask = np.zeros(N_D, dtype=bool)
    cap_daily_yi = np.full(N_D, np.nan, dtype=np.float64)
    closed_trades = []  # settled trades for both audit and strictly causal WF training (exit_di < t)

    sim_indices = [i for i, d in enumerate(cal_dts) if start_dt <= d <= end_dt]

    # Causal WF weights cache updated every 20 trading days
    wf_w = np.zeros(feat_mat.shape[1], dtype=np.float64)
    wf_thresh = -1e9
    last_fit_di = -999

    for t in sim_indices:
        traded_val = 0.0

        # 1. Exit matured or delayed positions
        still_open = []
        for pos in positions:
            s = pos["si"]
            if t >= pos["target_exit_di"]:
                px = float(sell_px[t, s])
                if np.isfinite(px) and px > 0:
                    proceeds = pos["qty"] * px * (1.0 - fee_sell)
                    traded_val += pos["qty"] * px
                    cash += proceeds
                    net_ret = (px * (1.0 - fee_sell)) / (pos["entry_px"] * (1.0 + fee_buy)) - 1.0
                    closed_trades.append({
                        "c6": panel["stocks"][s],
                        "buy_date": cal_dts[pos["entry_di"]],
                        "exit_date": cal_dts[t],
                        "entry_di": pos["entry_di"],
                        "exit_di": t,
                        "net_ret": float(net_ret),
                        "feat_row": pos["feat_row"],
                    })
                    continue
            still_open.append(pos)
        positions = still_open

        # 2. Refit causal WF scorecard using ONLY trades with exit_di < t
        if use_wf_scorecard and (t - last_fit_di >= 20):
            settled = [tr for tr in closed_trades if tr["exit_di"] < t]
            if len(settled) >= 60:
                X_tr = np.vstack([tr["feat_row"] for tr in settled])
                y_tr = np.array([tr["net_ret"] for tr in settled], dtype=np.float64)
                mu_x = np.mean(X_tr, axis=0)
                sd_x = np.maximum(np.std(X_tr, axis=0), 1e-6)
                Xz = np.clip((X_tr - mu_x) / sd_x, -3.0, 3.0)
                y_z = (y_tr - np.mean(y_tr)) / max(np.std(y_tr), 1e-6)
                # Ridge t-stat style standardized linear weights
                corrs = np.mean(Xz * y_z[:, None], axis=0)
                wf_w = corrs / max(np.linalg.norm(corrs), 1e-6)
                scores_hist = Xz @ wf_w
                wf_thresh = float(np.quantile(scores_hist, 1.0 - scorecard_top_pct))
                last_fit_di = t
            else:
                wf_w = np.zeros(feat_mat.shape[1], dtype=np.float64)
                wf_thresh = -1e9

        # 3. Evaluate today's candidate events
        free_slots = max_slots - len(positions)
        if free_slots > 0 and t in by_di:
            held_set = {p["si"] for p in positions}
            cands = []
            for idx_r in by_di[t]:
                s = int(si_arr[idx_r])
                if s in held_set:
                    continue
                if not can_buy[t, s]:
                    continue
                px_b = float(adj_open[t, s])
                if not (np.isfinite(px_b) and px_b > 0):
                    continue
                f_row = feat_mat[idx_r]
                if use_wf_scorecard and last_fit_di >= 0:
                    # Standardize with settled stats? Use raw dot since monotonic rank matters + quantile on settled raw dot
                    settled = [tr for tr in closed_trades if tr["exit_di"] < t]
                    X_tr = np.vstack([tr["feat_row"] for tr in settled])
                    mu_x = np.mean(X_tr, axis=0)
                    sd_x = np.maximum(np.std(X_tr, axis=0), 1e-6)
                    sc = float(np.clip((f_row - mu_x) / sd_x, -3.0, 3.0) @ wf_w)
                    if sc < wf_thresh:
                        continue
                else:
                    sc = float(ev["ev_strength"].iloc[idx_r]) if "ev_strength" in ev.columns else 0.0
                cands.append((sc, idx_r, s, px_b, f_row))

            if cands:
                cands.sort(key=lambda x: (-x[0], x[2]))
                n_take = min(free_slots, max_per_day, len(cands))
                picks = cands[:n_take]
                # Slot budget = min(cash / n_take, nav_prev / max_slots)
                slot_budget = min(cash / (n_take * (1.0 + fee_buy)), nav_prev / max_slots)
                if slot_budget > 1e-6:
                    for sc, idx_r, s, px_b, f_row in picks:
                        dq = slot_budget / px_b
                        cash -= slot_budget * (1.0 + fee_buy)
                        traded_val += slot_budget
                        positions.append({
                            "si": s,
                            "qty": dq,
                            "entry_di": t,
                            "target_exit_di": t + hold_days,
                            "entry_px": px_b,
                            "last_px": px_b,
                            "feat_row": f_row,
                        })

        # 4. Daily MTM mark
        pos_val = 0.0
        advs = []
        for pos in positions:
            s = pos["si"]
            if trad[t, s] and np.isfinite(adj_close[t, s]) and adj_close[t, s] > 0:
                pos["last_px"] = float(adj_close[t, s])
            pos_val += pos["qty"] * pos["last_px"]
            a20 = float(amt20[t, s])
            if np.isfinite(a20) and a20 > 0:
                advs.append(a20)

        nav_now = cash + pos_val
        dr[t] = nav_now / nav_prev - 1.0 if nav_prev > 0 else 0.0
        to_daily[t] = traded_val / (2.0 * nav_prev) if nav_prev > 0 else 0.0
        if len(positions) > 0:
            act_mask[t] = True
            if advs:
                cap_daily_yi[t] = 0.01 * float(np.percentile(advs, 20)) * max_slots
        nav_prev = nav_now

    return {
        "dr": dr,
        "to_daily": to_daily,
        "act_mask": act_mask,
        "cap_daily_yi": cap_daily_yi,
        "closed_trades": closed_trades,
    }


def run_family3(end_dt: str = "2026-11-24", run_trunc_check: bool = True) -> dict:
    t0 = time.time()
    bench_ctx = cm.load_bench_and_v20(end_dt=end_dt)
    panel = f2.load_smallcap_panel(end_dt=end_dt)
    ev_tables = build_unified_event_tables(panel["cal_dts"])

    cal_dts = panel["cal_dts"]
    dt_map = {d: i for i, d in enumerate(cal_dts)}
    stk_map = {s: i for i, s in enumerate(panel["stocks"])}
    N_D, N_S = panel["N_D"], panel["N_S"]

    # Attach pos_60d_t1 and ret_20d_t1 from parquet for low-pos filtering
    import pyarrow.parquet as pq
    pq_p = f"{cm.BASE_DIR}/stock_day_core_features_pit.parquet"
    s_pos = pq.read_table(pq_p, columns=["dt", "c6", "pos_60d_t1", "ret_20d_t1", "prev_streak"], filters=[("dt", "<=", end_dt)]).to_pandas()
    di_p = s_pos["dt"].cat.codes.values.astype(np.int32)
    si_p = s_pos["c6"].cat.codes.values.astype(np.int32)
    pos60_mat = np.full((N_D, N_S), np.nan, dtype=np.float32)
    pos60_mat[di_p, si_p] = s_pos["pos_60d_t1"].values.astype(np.float32)
    ret20_mat = np.full((N_D, N_S), np.nan, dtype=np.float32)
    ret20_mat[di_p, si_p] = s_pos["ret_20d_t1"].values.astype(np.float32)
    pstreak_mat = np.zeros((N_D, N_S), dtype=np.int8)
    pstreak_mat[di_p, si_p] = s_pos["prev_streak"].values.astype(np.int8)
    del s_pos, di_p, si_p
    gc.collect()

    elig_50m = (~panel["is_st"]) & (panel["list_age"] >= 60) & (~panel["tox_20d"]) & (panel["amt20_t1"] >= 0.50) & (panel["amt_t1"] >= 0.25)
    elig_200m = (~panel["is_st"]) & (panel["list_age"] >= 60) & (~panel["tox_20d"]) & (panel["amt20_t1"] >= 2.00) & (panel["amt_t1"] >= 1.00)

    def _filter_ev(df_e: pd.DataFrame, elig_m: np.ndarray, extra_fn=None) -> pd.DataFrame:
        d = df_e.copy()
        d["di"] = d["buy_date"].map(dt_map)
        d["si"] = d["c6"].map(stk_map)
        d = d.dropna(subset=["di", "si"]).copy()
        di_a = d["di"].astype(int).values
        si_a = d["si"].astype(int).values
        ok = elig_m[di_a, si_a]
        if extra_fn is not None:
            ok &= extra_fn(d, di_a, si_a)
        return d[ok].drop(columns=["di", "si"]).reset_index(drop=True)

    # 1. Build E_PERF variants
    perf = ev_tables["perf"].copy()
    perf["ev_strength"] = perf["growth_pct"].fillna(30.0).clip(-100, 500)
    perf_all_50 = _filter_ev(perf, elig_50m, lambda d, di_a, si_a: (d["is_yz"].values == 1) | (d["is_nk"].values == 1) | (d["growth_pct"].fillna(0).values >= 20.0))
    perf_surge_50 = _filter_ev(perf, elig_50m, lambda d, di_a, si_a: (d["is_nk"].values == 1) | (d["growth_pct"].fillna(0).values >= 50.0))
    perf_lowp_50 = _filter_ev(perf, elig_50m, lambda d, di_a, si_a: ((d["is_nk"].values == 1) | (d["growth_pct"].fillna(0).values >= 50.0)) & (pos60_mat[di_a, si_a] < 0.70) & (-panel["F_TURN_ABN"][di_a, si_a] < 1.5))
    perf_surge_200 = _filter_ev(perf, elig_200m, lambda d, di_a, si_a: (d["is_nk"].values == 1) | (d["growth_pct"].fillna(0).values >= 50.0))

    # 2. Build E_BUYBACK variants
    bb = ev_tables["buyback"].copy()
    bb["ev_strength"] = bb["plan_amt_yi"].fillna(0.0)
    bb_all_50 = _filter_ev(bb, elig_50m)
    bb_rep_50 = _filter_ev(bb, elig_50m, lambda d, di_a, si_a: d["sub"].values == "repurchase")
    bb_inc_50 = _filter_ev(bb, elig_50m, lambda d, di_a, si_a: d["sub"].values == "shareholder_inc")
    bb_low_50 = _filter_ev(bb, elig_50m, lambda d, di_a, si_a: (pos60_mat[di_a, si_a] < 0.55) & (ret20_mat[di_a, si_a] < 0.0) & (-panel["F_TURN_ABN"][di_a, si_a] < 1.1))
    bb_low_200 = _filter_ev(bb, elig_200m, lambda d, di_a, si_a: (pos60_mat[di_a, si_a] < 0.55) & (ret20_mat[di_a, si_a] < 0.0))

    # 3. Build E_IRQA surge variants strictly from causal 5d vs 60d IR matrix
    ir_df = ev_tables["irqa"].copy()
    ir_cnt_mat = np.zeros((N_D, N_S), dtype=np.int16)
    ir_q_mat = np.zeros((N_D, N_S), dtype=np.int16)
    ir_di = ir_df["buy_date"].map(dt_map)
    ir_si = ir_df["c6"].map(stk_map)
    ok_ir = ir_di.notna() & ir_si.notna()
    ir_cnt_mat[ir_di[ok_ir].astype(int).values, ir_si[ok_ir].astype(int).values] = ir_df.loc[ok_ir, "ir_rec_cnt"].values.astype(np.int16)
    ir_q_mat[ir_di[ok_ir].astype(int).values, ir_si[ok_ir].astype(int).values] = ir_df.loc[ok_ir, "ir_q_cnt"].values.astype(np.int16)

    # Trailing 5d (including t because buy_date is strictly pre-09:25!) vs trailing 60d
    cs_ir_c = np.vstack([np.zeros((1, N_S), dtype=np.int32), np.cumsum(ir_cnt_mat, axis=0, dtype=np.int32)])
    cs_ir_q = np.vstack([np.zeros((1, N_S), dtype=np.int32), np.cumsum(ir_q_mat, axis=0, dtype=np.int32)])
    ir_rows = []
    for t in range(60, N_D):
        # Strictly events available on day t (ir_cnt_mat[t] > 0) AND surge vs past 60d!
        has_today = ir_cnt_mat[t] > 0
        if not has_today.any():
            continue
        c5 = cs_ir_c[t + 1] - cs_ir_c[t - 4]
        q5 = cs_ir_q[t + 1] - cs_ir_q[t - 4]
        c60_prev = cs_ir_c[t - 4] - cs_ir_c[max(0, t - 64)]  # strictly preceding 60d baseline
        surge = has_today & (((c5 >= 2) & (c5 / np.maximum(c60_prev / 12.0, 0.25) >= 3.0)) | ((q5 >= 15) & (c60_prev <= 2)))
        no_high_board = (pstreak_mat[t] == 0) & (np.nan_to_num(ret20_mat[t], nan=0.0) < 25.0)
        hit_s = np.flatnonzero(surge & no_high_board & elig_50m[t])
        for s in hit_s:
            ir_rows.append((panel["stocks"][s], cal_dts[t], float(q5[s])))

    irqa_surge_50 = pd.DataFrame(ir_rows, columns=["c6", "buy_date", "ev_strength"])
    irqa_surge_200 = _filter_ev(irqa_surge_50, elig_200m)

    print(f"[Family3] Filtered pools: perf_all={len(perf_all_50)}, perf_surge={len(perf_surge_50)}, perf_lowp={len(perf_lowp_50)}, bb_all={len(bb_all_50)}, bb_low={len(bb_low_50)}, irqa_surge={len(irqa_surge_50)}")

    results = []
    daily_series = {}
    trade_logs = {}

    def _run_ev(tag: str, subtype: str, df_pool: pd.DataFrame, liq: str, hold: int, slots: int, fee: float, use_wf: bool = False):
        sim = simulate_event_portfolio(panel, df_pool, hold_days=hold, max_slots=slots, max_per_day=3, fee_rt=fee, use_wf_scorecard=use_wf, scorecard_top_pct=0.35, start_dt="2021-01-04", end_dt=end_dt)
        ev = cm.evaluate_daily_series(sim["dr"], bench_ctx, turnover_daily=sim["to_daily"], active_mask=sim["act_mask"], cap_daily_yi=sim["cap_daily_yi"])
        trs = sim["closed_trades"]
        wf_trs = [x for x in trs if x["buy_date"] >= "2023-01-03"]
        rets_wf = np.array([x["net_ret"] for x in wf_trs], dtype=float)
        wr_wf = round(float((rets_wf > 0).mean() * 100.0), 1) if len(rets_wf) else 0.0
        mean_wf = round(float(rets_wf.mean() * 100.0), 2) if len(rets_wf) else 0.0
        # Ex-top5 trades nav multiplier estimate
        ex5_tr_mult = round(float(np.prod(1.0 + np.sort(rets_wf)[:-5] / slots)), 4) if len(rets_wf) > 5 else 1.0
        row = {
            "family": "F3_Events",
            "strategy_id": tag,
            "subtype": subtype,
            "liq_tier": liq,
            "hold_days": hold,
            "max_slots": slots,
            "fee_bps": int(round(fee * 10000)),
            "wf_n_trades": len(wf_trs),
            "wf_wr_pct": wr_wf,
            "wf_mean_trade_pct": mean_wf,
            "wf_ex5_slot_nav": ex5_tr_mult,
            "windows": ev,
        }
        results.append(row)
        daily_series[tag] = sim["dr"]
        trade_logs[tag] = trs
        return row

    # E_PERF suite
    for nm, df_p, lq in [("PERF_ALL", perf_all_50, ">=50m"), ("PERF_SURGE", perf_surge_50, ">=50m"), ("PERF_LOWP", perf_lowp_50, ">=50m"), ("PERF_SURGE_200m", perf_surge_200, ">=200m")]:
        for h in [5, 10, 20]:
            for fee in [0.0030, 0.0050]:
                if nm == "PERF_SURGE_200m" and h == 5:
                    continue
                _run_ev(f"F3_{nm}_H{h}_{int(fee*10000)}bp", "E_PERF", df_p, lq, h, 20, fee, False)
        _run_ev(f"F3_{nm}_WF35_H10_30bp", "E_PERF", df_p, lq, 10, 20, 0.0030, True)

    # E_BUYBACK suite
    for nm, df_p, lq in [("BB_ALL", bb_all_50, ">=50m"), ("BB_REP", bb_rep_50, ">=50m"), ("BB_INC", bb_inc_50, ">=50m"), ("BB_LOWPOS", bb_low_50, ">=50m"), ("BB_LOWPOS_200m", bb_low_200, ">=200m")]:
        for h in [10, 20]:
            for fee in [0.0030, 0.0050]:
                if nm in ("BB_REP", "BB_INC") and fee == 0.0050:
                    continue
                _run_ev(f"F3_{nm}_H{h}_{int(fee*10000)}bp", "E_BUYBACK", df_p, lq, h, 20, fee, False)
        if nm in ("BB_ALL", "BB_LOWPOS"):
            _run_ev(f"F3_{nm}_WF35_H20_30bp", "E_BUYBACK", df_p, lq, 20, 20, 0.0030, True)

    # E_IRQA suite
    for nm, df_p, lq in [("IRQA_SURGE", irqa_surge_50, ">=50m"), ("IRQA_SURGE_200m", irqa_surge_200, ">=200m")]:
        for h in [5, 10]:
            for fee in [0.0030, 0.0050]:
                _run_ev(f"F3_{nm}_H{h}_{int(fee*10000)}bp", "E_IRQA", df_p, lq, h, 20, fee, False)
        if lq == ">=50m":
            _run_ev(f"F3_{nm}_WF35_H10_30bp", "E_IRQA", df_p, lq, 10, 20, 0.0030, True)

    # Best >=50m 30bps model truncation check
    cand_30 = [r for r in results if r["fee_bps"] == 30 and r["liq_tier"] == ">=50m"]
    best_30 = max(cand_30, key=lambda r: r["windows"]["WF_OOS"]["sharpe"])

    trunc_audit = {}
    if run_trunc_check:
        import subprocess
        # Map pool expression cleanly
        sub_code = (
            f"import sys, numpy as np, pandas as pd; sys.path.insert(0, {RD044_DIR!r}); "
            f"import step2_family2_smallcap_timing as f2, step3_family3_event_driven as f3; "
            f"p_tr = f2.load_smallcap_panel(end_dt='2024-12-31'); "
            f"ev_tr = f3.build_unified_event_tables(p_tr['cal_dts']); "
            f"el = (~p_tr['is_st']) & (p_tr['list_age'] >= 60) & (~p_tr['tox_20d']) & (p_tr['amt20_t1'] >= 0.50) & (p_tr['amt_t1'] >= 0.25); "
            f"sid = {best_30['strategy_id']!r}; "
            f"print('Truncation setup ready for', sid)"
        )
        # Better: call run_family3(end_dt='2024-12-31', run_trunc_check=False) in subprocess and compare!
        sub_code = (
            f"import sys, json, numpy as np; sys.path.insert(0, {RD044_DIR!r}); "
            f"import step3_family3_event_driven as f3; "
            f"f3.run_family3_trunc_only()"
        )
        # Even simpler: expose a small helper inside this module!
        trunc_audit = {"note": "run via --trunc-sub"}

    np.savez_compressed(f"{CACHE_DIR}/f3_daily_returns.npz", cal_dts=np.array(bench_ctx["cal_dts"]), **{k: v for k, v in daily_series.items()})
    out_obj = {
        "family": "F3_Events",
        "elapsed_sec": round(time.time() - t0, 1),
        "best_50m": best_30["strategy_id"],
        "physical_truncation_20241231": trunc_audit,
        "results": results,
    }
    with open(f"{CACHE_DIR}/f3_results.json", "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print("\n=== FAMILY 3 TOP OOS SUMMARY (WF 2023-01-03..2026-11-24) ===")
    for r in sorted(results, key=lambda x: -x["windows"]["WF_OOS"]["sharpe"])[:15]:
        w = r["windows"]["WF_OOS"]
        print(f"{r['strategy_id']:36s} | n={r['wf_n_trades']:4d} wr={r['wf_wr_pct']:4.1f}% | CAGR={w['cagr_pct']:6.2f}% Sh={w['sharpe']:5.3f} MDD={w['mdd_pct']:5.2f}%")
    return out_obj


def verify_f3_truncation():
    """Run exact 2024-12-31 physical truncation in isolated subprocess."""
    import subprocess
    full_res = json.load(open(f"{CACHE_DIR}/f3_results.json", encoding="utf-8"))
    best_id = full_res["best_50m"]
    full_npz = np.load(f"{CACHE_DIR}/f3_daily_returns.npz")
    sub_code = (
        f"import sys; sys.path.insert(0, {RD044_DIR!r}); "
        f"import step3_family3_event_driven as f3; "
        f"f3._run_trunc_worker()"
    )
    subprocess.run([sys.executable, "-c", sub_code], check=True)
    tr_npz = np.load(f"{CACHE_DIR}/_f3_trunc_tmp.npz")
    n_tr = int(len(tr_npz["cal_dts"]))
    diff = float(np.max(np.abs(full_npz[best_id][:n_tr] - tr_npz[best_id][:n_tr])))
    full_res["physical_truncation_20241231"] = {"strategy_id": best_id, "n_days_to_20241231": n_tr, "max_abs_ret_diff": diff, "passed": diff == 0.0}
    with open(f"{CACHE_DIR}/f3_results.json", "w", encoding="utf-8") as f:
        json.dump(full_res, f, ensure_ascii=False, indent=2)
    print(f"[Family3] 2024-12-31 Physical Truncation Check ({best_id}): max_abs_diff={diff}")


def _run_trunc_worker():
    """Helper run in fresh subprocess with end_dt=2024-12-31."""
    # Temporarily write to _f3_trunc_tmp.npz without overwriting f3_results.json
    bench_ctx = cm.load_bench_and_v20(end_dt="2024-12-31")
    panel = f2.load_smallcap_panel(end_dt="2024-12-31")
    ev_tables = build_unified_event_tables(panel["cal_dts"])
    cal_dts = panel["cal_dts"]
    dt_map = {d: i for i, d in enumerate(cal_dts)}
    stk_map = {s: i for i, s in enumerate(panel["stocks"])}
    N_D, N_S = panel["N_D"], panel["N_S"]
    import pyarrow.parquet as pq
    pq_p = f"{cm.BASE_DIR}/stock_day_core_features_pit.parquet"
    s_pos = pq.read_table(pq_p, columns=["dt", "c6", "pos_60d_t1", "ret_20d_t1", "prev_streak"], filters=[("dt", "<=", "2024-12-31")]).to_pandas()
    di_p = s_pos["dt"].cat.codes.values.astype(np.int32)
    si_p = s_pos["c6"].cat.codes.values.astype(np.int32)
    pos60_mat = np.full((N_D, N_S), np.nan, dtype=np.float32); pos60_mat[di_p, si_p] = s_pos["pos_60d_t1"].values.astype(np.float32)
    ret20_mat = np.full((N_D, N_S), np.nan, dtype=np.float32); ret20_mat[di_p, si_p] = s_pos["ret_20d_t1"].values.astype(np.float32)
    pstreak_mat = np.zeros((N_D, N_S), dtype=np.int8); pstreak_mat[di_p, si_p] = s_pos["prev_streak"].values.astype(np.int8)
    elig_50m = (~panel["is_st"]) & (panel["list_age"] >= 60) & (~panel["tox_20d"]) & (panel["amt20_t1"] >= 0.50) & (panel["amt_t1"] >= 0.25)

    def _flt(df_e, fn=None):
        d = df_e.copy()
        d["di"] = d["buy_date"].map(dt_map); d["si"] = d["c6"].map(stk_map)
        d = d.dropna(subset=["di", "si"]).copy()
        di_a, si_a = d["di"].astype(int).values, d["si"].astype(int).values
        ok = elig_50m[di_a, si_a]
        if fn is not None: ok &= fn(d, di_a, si_a)
        return d[ok].drop(columns=["di", "si"]).reset_index(drop=True)

    perf = ev_tables["perf"].copy(); perf["ev_strength"] = perf["growth_pct"].fillna(30.0).clip(-100, 500)
    bb = ev_tables["buyback"].copy(); bb["ev_strength"] = bb["plan_amt_yi"].fillna(0.0)
    ir_df = ev_tables["irqa"].copy()
    ir_cnt_mat = np.zeros((N_D, N_S), dtype=np.int16); ir_q_mat = np.zeros((N_D, N_S), dtype=np.int16)
    ir_di, ir_si = ir_df["buy_date"].map(dt_map), ir_df["c6"].map(stk_map)
    ok_ir = ir_di.notna() & ir_si.notna()
    ir_cnt_mat[ir_di[ok_ir].astype(int).values, ir_si[ok_ir].astype(int).values] = ir_df.loc[ok_ir, "ir_rec_cnt"].values.astype(np.int16)
    ir_q_mat[ir_di[ok_ir].astype(int).values, ir_si[ok_ir].astype(int).values] = ir_df.loc[ok_ir, "ir_q_cnt"].values.astype(np.int16)
    cs_c = np.vstack([np.zeros((1, N_S), dtype=np.int32), np.cumsum(ir_cnt_mat, axis=0, dtype=np.int32)])
    cs_q = np.vstack([np.zeros((1, N_S), dtype=np.int32), np.cumsum(ir_q_mat, axis=0, dtype=np.int32)])
    ir_rows = []
    for t in range(60, N_D):
        ht = ir_cnt_mat[t] > 0
        if not ht.any(): continue
        c5, q5, c60 = cs_c[t + 1] - cs_c[t - 4], cs_q[t + 1] - cs_q[t - 4], cs_c[t - 4] - cs_c[max(0, t - 64)]
        sg = ht & (((c5 >= 2) & (c5 / np.maximum(c60 / 12.0, 0.25) >= 3.0)) | ((q5 >= 15) & (c60 <= 2))) & (pstreak_mat[t] == 0) & (np.nan_to_num(ret20_mat[t], nan=0.0) < 25.0) & elig_50m[t]
        for s in np.flatnonzero(sg): ir_rows.append((panel["stocks"][s], cal_dts[t], float(q5[s])))
    irqa_50 = pd.DataFrame(ir_rows, columns=["c6", "buy_date", "ev_strength"])

    full_res = json.load(open(f"{CACHE_DIR}/f3_results.json", encoding="utf-8"))
    bid = full_res["best_50m"]
    pool_map = {
        "PERF_ALL": _flt(perf, lambda d, di_a, si_a: (d["is_yz"].values == 1) | (d["is_nk"].values == 1) | (d["growth_pct"].fillna(0).values >= 20.0)),
        "PERF_SURGE": _flt(perf, lambda d, di_a, si_a: (d["is_nk"].values == 1) | (d["growth_pct"].fillna(0).values >= 50.0)),
        "PERF_LOWP": _flt(perf, lambda d, di_a, si_a: ((d["is_nk"].values == 1) | (d["growth_pct"].fillna(0).values >= 50.0)) & (pos60_mat[di_a, si_a] < 0.70) & (-panel["F_TURN_ABN"][di_a, si_a] < 1.5)),
        "BB_ALL": _flt(bb),
        "BB_REP": _flt(bb, lambda d, di_a, si_a: d["sub"].values == "repurchase"),
        "BB_INC": _flt(bb, lambda d, di_a, si_a: d["sub"].values == "shareholder_inc"),
        "BB_LOWPOS": _flt(bb, lambda d, di_a, si_a: (pos60_mat[di_a, si_a] < 0.55) & (ret20_mat[di_a, si_a] < 0.0) & (-panel["F_TURN_ABN"][di_a, si_a] < 1.1)),
        "IRQA_SURGE": irqa_50,
    }
    row_b = [r for r in full_res["results"] if r["strategy_id"] == bid][0]
    p_key = next(k for k in sorted(pool_map, key=len, reverse=True) if k in bid)
    sim = simulate_event_portfolio(panel, pool_map[p_key], hold_days=row_b["hold_days"], max_slots=row_b["max_slots"], max_per_day=3, fee_rt=row_b["fee_bps"]/10000.0, use_wf_scorecard=("WF35" in bid), scorecard_top_pct=0.35, start_dt="2021-01-04", end_dt="2024-12-31")
    np.savez(f"{CACHE_DIR}/_f3_trunc_tmp.npz", cal_dts=np.array(bench_ctx["cal_dts"]), **{bid: sim["dr"]})


if __name__ == "__main__":
    run_family3(run_trunc_check=True)
    verify_f3_truncation()
