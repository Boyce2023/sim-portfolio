#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD033 Execution Simulator & Institutional Anti-Overfitting Audit Engine (Fast Vectorized/Slim).
ZERO yfinance (D12). ZERO cap10m.
"""
import math
import sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

TRD_DAYS_YEAR = 242.0
FEE_RT = 0.0030
PEN_BUF = 0.0030


def bh_fdr(p_vals: list[float]) -> list[float]:
    m = len(p_vals)
    if m == 0:
        return []
    arr = np.asarray(p_vals, dtype=float)
    order = np.argsort(arr)
    ranked = arr[order]
    q_raw = ranked * m / np.arange(1, m + 1)
    q_mon = np.clip(np.minimum.accumulate(q_raw[::-1])[::-1], 0.0, 1.0)
    out = np.empty(m, dtype=float)
    out[order] = q_mon
    return [round(float(x), 6) for x in out]


def bench_ret(px_map: dict, sdt: str, edt: str, sorted_dts: list[str] | None = None) -> float:
    dts = sorted_dts if sorted_dts is not None else sorted(px_map.keys())
    prevs = [d for d in dts if d < sdt]
    posts = [d for d in dts if d <= edt]
    if not posts:
        return 0.0
    p0 = px_map[prevs[-1]] if prevs else px_map[dts[0]]
    p1 = px_map[posts[-1]]
    return float(p1 / p0 - 1.0)


def ew_bench_ret(daily_map: dict, sdt: str, edt: str) -> float:
    rets = [v for d, v in daily_map.items() if sdt <= d <= edt]
    return float(np.prod(1.0 + np.array(rets, dtype=float)) - 1.0) if rets else 0.0


def _defer_close(r, k: int, min_k: int = 2) -> tuple[int, float]:
    while k <= 12 and not getattr(r, f"f{k}_sellable_strict", False):
        k += 1
    while k >= min_k and np.isnan(getattr(r, f"f{k}_ac", np.nan)):
        k -= 1
    if k < min_k:
        return -1, np.nan
    px = float(getattr(r, f"f{k}_ac"))
    return (k, px) if (not np.isnan(px) and px > 0) else (-1, np.nan)


def simulate_trades(df_cand: pd.DataFrame, entry_rule: str, exit_rule: str, fee: float = FEE_RT, score_col: str | None = None) -> pd.DataFrame:
    if df_cand.empty:
        return pd.DataFrame()
    # Select only columns needed for simulation (5x faster itertuples!)
    need = ["dt", "c6", "ac", "ret", "f1_dt", "f1_buyable", "f1_abn_ret", "f1_ao", "f1_o_pct"]
    if entry_rule in ("E5a_pullback", "E5b_breakhigh"):
        need.extend(["ah", "f1_ah", "f1_al", "f1_zt_px_adj"])
    for opt in ("kpl_zt_cnt", "vol20_m1", "f2_ao", "f2_open_is_dt", "f2_dt"):
        if opt in df_cand.columns:
            need.append(opt)
    max_k = 4 if exit_rule in ("H1a_T2_open", "H1b_T2_close", "H2_T3_close", "H3_T4_close") else 12
    for k in range(2, max_k + 1):
        for suf in ("dt", "ac", "sellable_strict"):
            col = f"f{k}_{suf}"
            if col in df_cand.columns:
                need.append(col)
        if exit_rule == "H5_ma5_break":
            for suf in ("ma5", "is_zt"):
                col = f"f{k}_{suf}"
                if col in df_cand.columns:
                    need.append(col)
        elif exit_rule == "H6_tpsl_10_6":
            for suf in ("ao", "ah", "al", "open_is_dt", "is_dt", "zt_px_adj", "dt_px_adj"):
                col = f"f{k}_{suf}"
                if col in df_cand.columns:
                    need.append(col)
    if score_col and score_col in df_cand.columns:
        need.append(score_col)
    need = [c for c in dict.fromkeys(need) if c in df_cand.columns]
    slim = df_cand[need]
    sc_vals = df_cand[score_col].to_numpy(float) if (score_col and score_col in df_cand.columns) else None

    rows = []
    for idx, r in enumerate(slim.itertuples(index=False)):
        if not r.f1_buyable or r.f1_abn_ret or not r.f1_dt:
            continue
        ao1 = float(r.f1_ao)
        o1_pct = float(r.f1_o_pct)
        if np.isnan(ao1) or ao1 <= 0 or np.isnan(o1_pct):
            continue

        b_hhmm = 925
        if entry_rule == "E1_all":
            b_px = ao1
        elif entry_rule == "E2_gapup":
            if not (0.01 <= o1_pct <= 0.06):
                continue
            b_px = ao1
        elif entry_rule == "E3_mild":
            if not (-0.04 <= o1_pct < 0.01):
                continue
            b_px = ao1
        elif entry_rule == "E4_deep":
            if not (-0.09 <= o1_pct <= -0.03):
                continue
            b_px = ao1
        elif entry_rule == "E5a_pullback":
            al1 = float(r.f1_al)
            tgt = float(r.ac)
            if o1_pct <= -0.005 or np.isnan(al1) or al1 > tgt * (1.0 - PEN_BUF):
                continue
            b_px = min(ao1, tgt)
            b_hhmm = 1030
        elif entry_rule == "E5b_breakhigh":
            ah1 = float(r.f1_ah)
            tgt = float(r.ah)
            zt1_adj = float(getattr(r, "f1_zt_px_adj", 1e18) or 1e18)
            if ao1 >= tgt * 1.005 or np.isnan(ah1) or ah1 < tgt * (1.0 + PEN_BUF):
                continue
            b_px = max(ao1, tgt)
            if b_px >= zt1_adj - 0.011:
                continue
            b_hhmm = 1030
        else:
            raise ValueError(entry_rule)

        sell_k, s_px, ex_hhmm, reason = -1, np.nan, 1500, exit_rule
        if exit_rule == "H1a_T2_open":
            ao2 = float(getattr(r, "f2_ao", np.nan))
            op_dt2 = bool(getattr(r, "f2_open_is_dt", False))
            if not np.isnan(ao2) and ao2 > 0 and not op_dt2 and getattr(r, "f2_dt", ""):
                sell_k, s_px, ex_hhmm = 2, ao2, 925
            else:
                sell_k, s_px = _defer_close(r, 2)
        elif exit_rule in ("H1b_T2_close", "H2_T3_close", "H3_T4_close", "H4_T6_close"):
            tk = {"H1b_T2_close": 2, "H2_T3_close": 3, "H3_T4_close": 4, "H4_T6_close": 6}[exit_rule]
            sell_k, s_px = _defer_close(r, tk)
        elif exit_rule == "H5_ma5_break":
            chosen = 11
            for k in range(2, 12):
                ac_k = float(getattr(r, f"f{k}_ac", np.nan))
                ma5_k = float(getattr(r, f"f{k}_ma5", np.nan))
                if np.isnan(ac_k):
                    chosen = max(2, k - 1)
                    break
                if getattr(r, f"f{k}_sellable_strict", False) and not getattr(r, f"f{k}_is_zt", False) and not np.isnan(ma5_k) and ac_k < ma5_k:
                    chosen = k
                    break
            sell_k, s_px = _defer_close(r, chosen)
        elif exit_rule == "H6_tpsl_10_6":
            tp_px, sl_px, chosen = b_px * 1.10, b_px * 0.94, 11
            for k in range(2, 12):
                ao_k = float(getattr(r, f"f{k}_ao", np.nan))
                ah_k = float(getattr(r, f"f{k}_ah", np.nan))
                al_k = float(getattr(r, f"f{k}_al", np.nan))
                ac_k = float(getattr(r, f"f{k}_ac", np.nan))
                if np.isnan(ac_k) or np.isnan(ao_k):
                    chosen = max(2, k - 1)
                    break
                op_dt_k = bool(getattr(r, f"f{k}_open_is_dt", False))
                yizi_dt_k = bool(getattr(r, f"f{k}_is_dt", False)) and (ah_k == al_k)
                if yizi_dt_k:
                    continue
                if not op_dt_k and ao_k <= sl_px:
                    sell_k, s_px, ex_hhmm, reason = k, ao_k, 925, "gap_sl"
                    break
                if not op_dt_k and ao_k >= tp_px:
                    sell_k, s_px, ex_hhmm, reason = k, ao_k, 925, "gap_tp"
                    break
                hit_sl = al_k <= sl_px * (1.0 - PEN_BUF)
                zt_k = float(getattr(r, f"f{k}_zt_px_adj", 1e18) or 1e18)
                hit_tp = ah_k >= min(tp_px * (1.0 + PEN_BUF), zt_k - 1e-4)
                if hit_sl:
                    dt_k = float(getattr(r, f"f{k}_dt_px_adj", 0.0) or 0.0)
                    if sl_px <= dt_k + 1e-4 and bool(getattr(r, f"f{k}_is_dt", False)):
                        continue
                    sell_k, s_px, ex_hhmm, reason = k, max(sl_px, al_k), 1100, "intraday_sl"
                    break
                if hit_tp:
                    sell_k, s_px, ex_hhmm, reason = k, min(tp_px, ah_k), 1100, "intraday_tp"
                    break
            if np.isnan(s_px):
                sell_k, s_px = _defer_close(r, chosen)
                reason = "max10_close"
        else:
            raise ValueError(exit_rule)

        if sell_k < 2 or np.isnan(s_px) or s_px <= 0:
            continue
        s_dt = getattr(r, f"f{sell_k}_dt", "")
        if not s_dt:
            continue

        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        sc_v = float(sc_vals[idx]) if sc_vals is not None else float(getattr(r, "kpl_zt_cnt", 0) * 100.0 + float(r.ret) * 100.0)
        v20_v = getattr(r, "vol20_m1", 0.04)
        rows.append({
            "sig_date": r.dt, "buy_date": r.f1_dt, "exit_date": s_dt,
            "buy_hhmm": b_hhmm, "exit_hhmm": ex_hhmm, "c6": r.c6,
            "score": sc_v, "kpl_zt_cnt": int(getattr(r, "kpl_zt_cnt", 0)),
            "ret_t0": float(r.ret),
            "vol20_m1": float(v20_v) if pd.notna(v20_v) else 0.04,
            "buy_px": b_px, "exit_px": s_px, "gross_ret": gross, "net_ret": net,
            "hold_bars": sell_k - 1, "exit_reason": reason,
        })
    return pd.DataFrame(rows)


def sim_1_slot(trades: pd.DataFrame, fee_override: float | None = None) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    srt = trades.sort_values(["buy_date", "score", "c6"], ascending=[True, False, True])
    # Deduplicate to best signal per buy_date FIRST (much faster than groupby iterrows!)
    best_per_day = srt.drop_duplicates("buy_date", keep="first")
    free_dt = ""
    taken = []
    for row in best_per_day.itertuples(index=False):
        bdt = str(row.buy_date)
        if free_dt != "" and bdt <= free_dt:
            continue
        d = row._asdict()
        if fee_override is not None:
            d["net_ret"] = (1.0 + float(row.gross_ret)) * (1.0 - fee_override) - 1.0
        free_dt = str(row.exit_date)
        taken.append(d)
    return pd.DataFrame(taken) if taken else pd.DataFrame()


def build_daily_mtm_stream(slot_df: pd.DataFrame, cal_dts: list[str], dt_idx: dict, bar_ac_lu: dict) -> tuple[np.ndarray, np.ndarray, float]:
    T = len(cal_dts)
    dr = np.zeros(T, dtype=float)
    active = np.zeros(T, dtype=bool)
    if slot_df.empty:
        return dr, active, 0.0

    for r in slot_df.itertuples(index=False):
        bi = dt_idx.get(str(r.buy_date))
        ei = dt_idx.get(str(r.exit_date))
        if bi is None or ei is None or ei <= bi:
            continue
        active[bi: ei + 1] = True
        b_px = float(r.buy_px)
        prev_v, last_c = b_px, b_px
        for t in range(bi, ei):
            c_t = bar_ac_lu.get((r.c6, cal_dts[t]), last_c)
            if not (c_t > 0):
                c_t = last_c
            dr[t] = c_t / prev_v - 1.0
            prev_v, last_c = c_t, c_t
        end_val = b_px * (1.0 + float(r.net_ret))
        dr[ei] = end_val / prev_v - 1.0

    mtm_nav = float(np.prod(1.0 + dr))
    tr_nav = float(np.prod(1.0 + slot_df["net_ret"].to_numpy(float)))
    return dr, active, abs(mtm_nav - tr_nav)


def eval_window_metrics(
    all_trades: pd.DataFrame,
    slot_trades: pd.DataFrame,
    dr_full: np.ndarray,
    active_full: np.ndarray,
    cal_dts: list[str],
    dt_idx: dict,
    wh: dict,
    sorted_idx_dts: dict,
    sdt: str,
    edt: str,
) -> dict:
    sub_all = all_trades[(all_trades["buy_date"] >= sdt) & (all_trades["buy_date"] <= edt)] if not all_trades.empty else pd.DataFrame()
    sub_1s = slot_trades[(slot_trades["buy_date"] >= sdt) & (slot_trades["buy_date"] <= edt)] if not slot_trades.empty else pd.DataFrame()
    i0 = dt_idx[cal_dts[0]] if cal_dts else 0
    w_idx = [dt_idx[d] for d in cal_dts if sdt <= d <= edt]
    dr = dr_full[w_idx[0]: w_idx[-1] + 1] if w_idx else np.zeros(1)
    act = active_full[w_idx[0]: w_idx[-1] + 1] if w_idx else np.zeros(1, dtype=bool)
    T = len(dr)

    r_hs = bench_ret(wh["sh300"], sdt, edt, sorted_idx_dts["sh300"])
    r_cyb = bench_ret(wh["sz399006"], sdt, edt, sorted_idx_dts["sz399006"])
    r_kc = bench_ret(wh["sh000688"], sdt, edt, sorted_idx_dts["sh000688"])
    r_ew20 = ew_bench_ret(wh["ew20_daily"], sdt, edt)

    ew_day = sub_all.groupby("buy_date")["net_ret"].mean().to_numpy(float) if not sub_all.empty else np.array([])
    ew_nav = float(np.prod(1.0 + ew_day)) if len(ew_day) else 1.0

    if sub_1s.empty:
        return {
            "raw_n": int(len(sub_all)), "n_1s": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "ew_nav": round(ew_nav, 4), "nav_1s": 1.0, "mdd_daily_pct": 0.0,
            "ex3_nav": 1.0, "ex5_nav": 1.0, "sharpe": 0.0, "avg_exp": 0.0,
            "hs300_pct": round(r_hs * 100, 2), "cyb_pct": round(r_cyb * 100, 2), "kc50_pct": round(r_kc * 100, 2),
            "ex_hs300_pp": round(-r_hs * 100, 2), "ex_cyb_pp": round(-r_cyb * 100, 2), "ex_kc50_pp": round(-r_kc * 100, 2),
            "ex_ew_hs300_pp": round((ew_nav - 1.0 - r_hs) * 100, 2),
        }

    r1 = sub_1s["net_ret"].to_numpy(float)
    r_all = sub_all["net_ret"].to_numpy(float)
    w, l = r1[r1 > 0], r1[r1 <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nav_1s = float(np.prod(1.0 + r1))
    sr = np.sort(r1)
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(r1) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(r1) > 5 else 1.0

    cum = np.cumprod(1.0 + dr)
    pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd_d = float(np.max((pk - cum) / pk) * 100.0)
    sd_d = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd_d * math.sqrt(TRD_DAYS_YEAR)) if sd_d > 1e-12 else 0.0
    hlz_t = float(r1.mean() / r1.std(ddof=1) * math.sqrt(len(r1))) if (len(r1) > 1 and r1.std(ddof=1) > 0) else 0.0

    return {
        "raw_n": int(len(sub_all)), "raw_wr_pct": round(float((r_all > 0).mean() * 100), 2),
        "raw_mean_pct": round(float(r_all.mean() * 100), 2), "ew_nav": round(ew_nav, 4),
        "n_1s": int(len(r1)), "wr_pct": round(float((r1 > 0).mean() * 100), 2),
        "plr": round(plr, 2), "mean_pct": round(float(r1.mean() * 100), 2),
        "nav_1s": round(nav_1s, 4), "ex3_nav": round(ex3, 4), "ex5_nav": round(ex5, 4),
        "mdd_daily_pct": round(mdd_d, 2), "sharpe": round(sharpe, 3), "hlz_t": round(hlz_t, 2),
        "avg_exp": round(float(act.mean()), 4),
        "hs300_pct": round(r_hs * 100, 2), "cyb_pct": round(r_cyb * 100, 2),
        "kc50_pct": round(r_kc * 100, 2), "ew20_pct": round(r_ew20 * 100, 2),
        "ex_hs300_pp": round((nav_1s - 1.0 - r_hs) * 100, 2),
        "ex_cyb_pp": round((nav_1s - 1.0 - r_cyb) * 100, 2),
        "ex_kc50_pp": round((nav_1s - 1.0 - r_kc) * 100, 2),
        "ex_ew_hs300_pp": round((ew_nav - 1.0 - r_hs) * 100, 2),
        "ex_ew_cyb_pp": round((ew_nav - 1.0 - r_cyb) * 100, 2),
    }


def eval_full_suite(
    trades_raw: pd.DataFrame,
    bar_ac_lu: dict,
    wh: dict,
    windows: list[tuple[str, str, str]],
) -> tuple[dict, pd.DataFrame]:
    slot_df = sim_1_slot(trades_raw)
    cal_dts = wh["all_cal_dts"]
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    dr, act, mtm_diff = build_daily_mtm_stream(slot_df, cal_dts, dt_idx, bar_ac_lu)
    assert mtm_diff < 1e-4, f"MTM mismatch {mtm_diff}"

    sorted_idx_dts = {
        "sh300": sorted(wh["sh300"].keys()),
        "sz399006": sorted(wh["sz399006"].keys()),
        "sh000688": sorted(wh["sh000688"].keys()),
    }
    out = {"mtm_diff": round(mtm_diff, 8)}
    for wlbl, sdt, edt in windows:
        out[wlbl] = eval_window_metrics(trades_raw, slot_df, dr, act, cal_dts, dt_idx, wh, sorted_idx_dts, sdt, edt)

    slot_50 = sim_1_slot(trades_raw, fee_override=0.0050)
    out["fee50_full_nav_1s"] = round(float(np.prod(1.0 + slot_50["net_ret"].to_numpy(float))), 4) if not slot_50.empty else 1.0
    out["fee50_oos_nav_1s"] = round(float(np.prod(1.0 + slot_50[slot_50["buy_date"] >= "2024-07-01"]["net_ret"].to_numpy(float))), 4) if not slot_50.empty else 1.0

    if not slot_df.empty:
        avg_exp = float(act.mean())
        sh_dts = sorted_idx_dts["sh300"]
        sh_pos = {d: i for i, d in enumerate(sh_dts)}
        sh_r_d = np.array([wh["sh300"][d] / wh["sh300"][sh_dts[sh_pos[d] - 1]] - 1.0 for d in cal_dts], dtype=float)
        cyb_dts = sorted_idx_dts["sz399006"]
        cyb_pos = {d: i for i, d in enumerate(cyb_dts)}
        cyb_r_d = np.array([wh["sz399006"][d] / wh["sz399006"][cyb_dts[cyb_pos[d] - 1]] - 1.0 for d in cal_dts], dtype=float)
        ew20_d = np.array([wh["ew20_daily"].get(d, 0.0) for d in cal_dts], dtype=float)

        def _s_ab(vec):
            nv = float(np.prod(1.0 + vec))
            sd = float(np.std(vec, ddof=1))
            sr = float(np.mean(vec) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
            return {"nav": round(nv, 4), "sharpe": round(sr, 3)}

        raw_iv = 1.0 / np.maximum(slot_df["vol20_m1"].to_numpy(float), 0.005)
        w_iv = raw_iv / np.mean(raw_iv)
        iv_sizing_nav = float(np.prod(1.0 + slot_df["net_ret"].to_numpy(float) * w_iv))
        t_iv = trades_raw[["buy_date", "exit_date", "c6", "gross_ret", "net_ret", "vol20_m1"]].copy()
        t_iv["score"] = -t_iv["vol20_m1"].to_numpy(float)
        slot_iv_rank = sim_1_slot(t_iv)
        iv_rank_nav = float(np.prod(1.0 + slot_iv_rank["net_ret"].to_numpy(float))) if not slot_iv_rank.empty else 1.0
        iv_rank_oos = float(np.prod(1.0 + slot_iv_rank[slot_iv_rank["buy_date"] >= "2024-07-01"]["net_ret"].to_numpy(float))) if not slot_iv_rank.empty else 1.0

        out["ablations"] = {
            "avg_exp": round(avg_exp, 4),
            "static_hs300_matched": _s_ab(avg_exp * sh_r_d),
            "static_cyb_matched": _s_ab(avg_exp * cyb_r_d),
            "static_ew20_matched": _s_ab(avg_exp * ew20_d),
            "inv_vol20_sizing_nav_1s": round(iv_sizing_nav, 4),
            "pure_inv_vol20_rank_full_nav": round(iv_rank_nav, 4),
            "pure_inv_vol20_rank_oos_nav": round(iv_rank_oos, 4),
        }
    return out, slot_df


def v20_empty_slot_test(cand_trades: pd.DataFrame, v20_ledger_path: str, s82_ledger_path: str) -> dict:
    v20 = pd.read_csv(v20_ledger_path)
    v20["code"] = v20["code"].astype(str).str.zfill(6)
    s82 = pd.read_csv(s82_ledger_path)
    s82["c6"] = s82["c6"].astype(str).str.zfill(6)

    s_dt, e_dt = "2021-11-16", "2026-11-16"
    occ = [((str(r.buy_date), int(r.buy_hhmm)), (str(r.exit_date), int(r.exit_hhmm))) for r in v20.itertuples(index=False)]

    sub = cand_trades[(cand_trades["buy_date"] >= s_dt) & (cand_trades["buy_date"] <= e_dt)].sort_values(["buy_date", "score", "c6"], ascending=[True, False, True])
    added = []
    for r in sub.itertuples(index=False):
        st_i = (str(r.buy_date), int(r.buy_hhmm))
        en_i = (str(r.exit_date), int(r.exit_hhmm))
        if all((en_i < os_) or (st_i > oe_) for os_, oe_ in occ):
            added.append({
                "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm),
                "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                "code": r.c6, "strategy": "rd033_patch", "net_ret": float(r.net_ret),
            })
            occ.append((st_i, en_i))

    def _st(df_l):
        if df_l.empty:
            return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav": 1.0, "oos_nav": 1.0, "y26_nav": 1.0, "ex5_nav": 1.0}
        rt = df_l["net_ret"].to_numpy(float)
        w, l = rt[rt > 0], rt[rt <= 0]
        plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
        cum = np.cumprod(1.0 + rt)
        pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
        mdd = float(np.max((pk - cum) / pk) * 100.0)
        ex5 = float(np.prod(1.0 + np.sort(rt)[:-5])) if len(rt) > 5 else 1.0
        oos_r = df_l[df_l["buy_date"] >= "2024-07-01"]["net_ret"].to_numpy(float)
        y26_r = df_l[df_l["buy_date"] >= "2026-01-01"]["net_ret"].to_numpy(float)
        return {
            "n": int(len(rt)), "wr_pct": round(float((rt > 0).mean() * 100), 2),
            "plr": round(plr, 2), "mean_pct": round(float(rt.mean() * 100), 2),
            "nav": round(float(cum[-1]), 4), "mdd_pct": round(mdd, 2),
            "ex5_nav": round(ex5, 4),
            "oos_n": int(len(oos_r)), "oos_wr_pct": round(float((oos_r > 0).mean() * 100), 2) if len(oos_r) else 0.0,
            "oos_nav": round(float(np.prod(1.0 + oos_r)), 4) if len(oos_r) else 1.0,
            "y26_n": int(len(y26_r)), "y26_wr_pct": round(float((y26_r > 0).mean() * 100), 2) if len(y26_r) else 0.0,
            "y26_nav": round(float(np.prod(1.0 + y26_r)), 4) if len(y26_r) else 1.0,
        }

    add_df = pd.DataFrame(added)
    cmb = pd.concat([v20[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "strategy", "net_ret"]], add_df], ignore_index=True) if not add_df.empty else v20
    cmb = cmb.sort_values(["buy_date", "buy_hhmm", "exit_date"]).reset_index(drop=True)
    for i in range(1, len(cmb)):
        assert (str(cmb.iloc[i]["buy_date"]), int(cmb.iloc[i]["buy_hhmm"])) > (str(cmb.iloc[i - 1]["exit_date"]), int(cmb.iloc[i - 1]["exit_hhmm"]))

    return {
        "v20_baseline": _st(v20),
        "s82_standalone_ref": _st(s82.assign(code=s82["c6"], strategy="s82")),
        "added_patch_solo": _st(add_df),
        "v20_plus_patch": _st(cmb),
    }
