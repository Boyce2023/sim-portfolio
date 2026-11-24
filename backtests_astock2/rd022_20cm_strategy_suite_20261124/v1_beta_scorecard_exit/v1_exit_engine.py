#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
20cm Beta-Resonance V1.0: Exact PIT Daily-Bar Exit Tree Engine & D15/HLZ/DSR/Capacity Evaluator.
- Enforces A-share T+1 lock (buy T+1 09:25 -> earliest sell T+2).
- Conservative intraday collision: SL checked strictly before intraday TP.
- Cannot fill TP above limit-up, cannot fill SL below/at sealed limit-down (defers to next tradable close).
"""
import math
import numpy as np
import pandas as pd
from scipy import stats

FEE_RT = 0.0030


def simulate_exit_v1(paths: dict, mkt_ew_map: dict, c6: str, t0_gidx: int,
                     rule: str, mkt_prev5d: float = 0.0, fee_rt: float = FEE_RT):
    st = paths.get(c6)
    if st is None:
        return None
    p0 = st["gidx_pos"].get(t0_gidx)
    if p0 is None:
        return None
    buy_pos = st["gidx_pos"].get(t0_gidx + 1)
    n_len = len(st["dt"])
    if buy_pos is None or st["vol"][buy_pos] <= 0:
        return None
    if st["op"][buy_pos] >= st["zt_px"][buy_pos] - 0.011:
        return None
    buy_px = st["ao"][buy_pos]
    buy_dt = st["dt"][buy_pos]
    first_sell_pos = buy_pos + 1
    if buy_px <= 0 or np.isnan(buy_px) or first_sell_pos >= n_len:
        return None

    def make_res(j_idx, px, why):
        net_r = (px / buy_px) * (1.0 - fee_rt) - 1.0
        return buy_dt, float(buy_px), st["dt"][j_idx], float(px), float(net_r), why, int(st["gidx"][j_idx] - (t0_gidx + 1))

    def defer_close(start_j, tag):
        for j in range(start_j, n_len):
            if st["vol"][j] > 0 and (not st["is_dt"][j]):
                w = tag if j == start_j else f"{tag}_DEF{j-start_j}"
                return make_res(j, st["ac"][j], w)
        return None

    # Fixed time exits (relative to T0: FIX_T2 => gidx >= t0_gidx + 2, etc.)
    if rule.startswith("FIX_T"):
        tk = int(rule.split("T")[1])
        for j in range(first_sell_pos, n_len):
            if st["gidx"][j] >= t0_gidx + tk:
                return defer_close(j, rule)
        return None

    # D1 (buy day T+1) bar state (strictly known at T+1 15:00 before T+2!)
    d1_op, d1_hi, d1_lo, d1_cl = st["op"][buy_pos], st["hi"] if "hi" in st else st["ah"][buy_pos]/st["adjf"][buy_pos], st["lo"] if "lo" in st else st["al"][buy_pos]/st["adjf"][buy_pos], st["cl"][buy_pos]
    d1_ao, d1_ac = st["ao"][buy_pos], st["ac"][buy_pos]
    d1_hl = max(st["ah"][buy_pos] - st["al"][buy_pos], 1e-6)
    d1_clv = (d1_ac - st["al"][buy_pos]) / d1_hl
    d1_co = d1_ac / d1_ao - 1.0
    d1_zt = bool(st["is_zt"][buy_pos])
    d1_strong_yang = (d1_co >= 0.04 and d1_clv >= 0.65)
    d1_big_yin = (d1_co <= -0.04 and d1_clv < 0.30)

    # Parse grid or dynamic tree
    tp_pct, sl_pct, max_k = None, None, 5
    trail_pct = None
    weak_cut_mode = None      # 'open', 'close', 'gap_open'
    stagnant_thr = None       # e.g. 0.02 at D2 close
    stagnant_day = 2
    use_zt_ride = False
    use_d1_yang_boost = False
    mkt_crash_thr = None      # e.g. -0.025

    if rule.startswith("GRID_"):
        # GRID_TP10_SL07_T5 or GRID_TP12_SLNO_T3
        for pt in rule.split("_")[1:]:
            if pt.startswith("TP") and pt[2:].isdigit():
                tp_pct = float(pt[2:]) / 100.0
            elif pt.startswith("SL"):
                sl_pct = None if pt[2:] == "NO" else float(pt[2:]) / 100.0
            elif pt.startswith("T") and pt[1:].isdigit():
                max_k = int(pt[1:])
    elif rule == "DYN_ZT_RIDE_T3":
        use_zt_ride = True; max_k = 3
    elif rule == "DYN_YANG_TP15_T5":
        use_zt_ride = True; tp_pct = 0.15 if d1_strong_yang else 0.10; sl_pct = 0.07; max_k = 5
    elif rule == "DYN_TRAIL5_T5":
        use_zt_ride = True; trail_pct = 0.05; sl_pct = 0.07; max_k = 5
    elif rule == "DYN_YANG_TRAIL5_T5":
        use_zt_ride = True; use_d1_yang_boost = True
        tp_pct = 0.15 if d1_strong_yang else 0.12
        trail_pct = 0.05 if d1_strong_yang else None
        sl_pct = 0.07; max_k = 5
    elif rule == "DYN_WEAK_OPEN_CUT":
        use_zt_ride = True; tp_pct = 0.12; sl_pct = 0.07; max_k = 5; weak_cut_mode = "open"
    elif rule == "DYN_WEAK_CLOSE_CUT":
        use_zt_ride = True; tp_pct = 0.12; sl_pct = 0.07; max_k = 5; weak_cut_mode = "close"
    elif rule == "DYN_WEAK_GAP_CUT":
        use_zt_ride = True; tp_pct = 0.12; sl_pct = 0.07; max_k = 5; weak_cut_mode = "gap_open"
    elif rule == "DYN_STAG2_T2_T5":
        use_zt_ride = True; tp_pct = 0.12; sl_pct = 0.07; max_k = 5; stagnant_thr = 0.02; stagnant_day = 2
    elif rule == "DYN_STAG2_T3_T5":
        use_zt_ride = True; tp_pct = 0.12; sl_pct = 0.07; max_k = 5; stagnant_thr = 0.02; stagnant_day = 3
    elif rule == "DYN_MKT_CRASH_T5":
        use_zt_ride = True; tp_pct = 0.12; sl_pct = 0.07; max_k = 5; mkt_crash_thr = -0.025
    elif rule == "DYN_TREE_FULL_OPEN":
        use_zt_ride = True; use_d1_yang_boost = True
        tp_pct = 0.15 if d1_strong_yang else 0.12
        trail_pct = 0.05 if d1_strong_yang else None
        sl_pct = 0.07; max_k = 5; weak_cut_mode = "open"; stagnant_thr = 0.02; stagnant_day = 2
    elif rule == "DYN_TREE_FULL_CLOSE":
        use_zt_ride = True; use_d1_yang_boost = True
        tp_pct = 0.15 if d1_strong_yang else 0.12
        trail_pct = 0.05 if d1_strong_yang else None
        sl_pct = 0.07; max_k = 5; weak_cut_mode = "close"; stagnant_thr = 0.02; stagnant_day = 2
    elif rule == "DYN_TREE_FULL_MKT":
        use_zt_ride = True; use_d1_yang_boost = True
        tp_pct = 0.15 if d1_strong_yang else 0.12
        trail_pct = 0.05 if d1_strong_yang else None
        sl_pct = 0.07; max_k = 5; weak_cut_mode = "open"; stagnant_thr = 0.02; stagnant_day = 2; mkt_crash_thr = -0.025
    elif rule == "DYN_TREE_LIGHT":
        use_zt_ride = True; use_d1_yang_boost = True
        tp_pct = 0.15 if d1_strong_yang else 0.12
        trail_pct = 0.05 if d1_strong_yang else None
        sl_pct = 0.07; max_k = 5; weak_cut_mode = "gap_open"; stagnant_thr = 0.015; stagnant_day = 3
    elif rule == "DYN_TREE_ICE_FAST":
        use_zt_ride = True; use_d1_yang_boost = True
        if mkt_prev5d < -0.02:
            tp_pct = 0.10; sl_pct = 0.06; max_k = 3
        else:
            tp_pct = 0.15 if d1_strong_yang else 0.12
            trail_pct = 0.05 if d1_strong_yang else None
            sl_pct = 0.07; max_k = 5

    peak_close = d1_ac
    zt_riding = d1_zt if use_zt_ride else False

    for j in range(first_sell_pos, n_len):
        gk = int(st["gidx"][j] - t0_gidx)  # 2 on T+2, 3 on T+3, ...
        if st["vol"][j] <= 0:
            continue

        o_p, h_p, l_p, c_p = st["ao"][j], st["ah"][j], st["al"][j], st["ac"][j]
        zt_adj = st["zt_px"][j] * st["adjf"][j]
        dt_adj = st["dt_px"][j] * st["adjf"][j]
        can_open = st["op"][j] > st["dt_px"][j] + 0.011
        can_close = not st["is_dt"][j]

        # 0. D1 Big Bearish Breakdown cut on D2 (gk == 2)
        if gk == 2 and d1_big_yin and (not zt_riding) and weak_cut_mode is not None:
            if weak_cut_mode == "open" and can_open:
                return make_res(j, o_p, "D1_YIN_D2OPEN")
            if weak_cut_mode == "gap_open" and o_p < d1_ac and can_open:
                return make_res(j, o_p, "D1_YIN_GAPOPEN")
            if weak_cut_mode == "close":
                return defer_close(j, "D1_YIN_D2CLOSE")

        # 1. Open SL check (conservative first)
        if sl_pct is not None:
            sl_px = buy_px * (1.0 - sl_pct)
            if o_p <= sl_px and can_open:
                return make_res(j, o_p, f"SL_OPEN_T{gk}")

        # 2. Open TP check (can always sell at open if >= TP and >= limit-down)
        if tp_pct is not None and (not zt_riding):
            tp_px = buy_px * (1.0 + tp_pct)
            if o_p >= tp_px and can_open:
                return make_res(j, o_p, f"TP_OPEN_T{gk}")

        # 3. Intraday SL check BEFORE Intraday TP check (conservative collision!)
        if sl_pct is not None:
            sl_px = buy_px * (1.0 - sl_pct)
            if l_p <= sl_px and sl_px >= dt_adj - 1e-4 and can_close:
                return make_res(j, sl_px, f"SL_HIT_T{gk}")
            if l_p <= sl_px and not can_close:
                # Sealed limit down -> defer close
                return defer_close(j, f"SL_DTDEF_T{gk}")

        # 4. Intraday TP check (only if not currently riding D1 ZT streak unless broken)
        if tp_pct is not None and (not zt_riding):
            tp_px = buy_px * (1.0 + tp_pct)
            if h_p >= tp_px and tp_px <= zt_adj + 1e-4:
                return make_res(j, tp_px, f"TP_HIT_T{gk}")

        # 5. ZT Streak Riding check
        if zt_riding:
            if st["is_zt"][j]:
                peak_close = max(peak_close, c_p)
                continue
            else:
                # First break of ZT streak -> exit at close (unless D1 was NOT ZT)
                return defer_close(j, f"ZT_BREAK_T{gk}")

        # 6. Trailing drawdown stop from highest holding close (only after j >= first_sell_pos)
        if trail_pct is not None and peak_close > buy_px * 1.03 and can_close:
            if c_p <= peak_close * (1.0 - trail_pct):
                return make_res(j, c_p, f"TRAIL_T{gk}")
        peak_close = max(peak_close, c_p)

        # 7. Market crash risk-off exit at close
        if mkt_crash_thr is not None and can_close:
            ew_d = mkt_ew_map.get(st["dt"][j], 0.0)
            if ew_d < mkt_crash_thr:
                return make_res(j, c_p, f"MKT_CRASH_T{gk}")

        # 8. Stagnant early exit on D2 or D3 close
        if stagnant_thr is not None and gk == stagnant_day:
            if (c_p / buy_px - 1.0) < stagnant_thr:
                return defer_close(j, f"STAG_T{gk}")

        # 9. Max hold exit
        if gk >= max_k:
            return defer_close(j, f"TIME_T{gk}")

    return None


def calc_cap_nav(rets: np.ndarray, init_w: float = 100.0, cap_w: float = 1000.0) -> float:
    cap = init_w
    for r in rets:
        bet = min(cap, cap_w)
        cap += bet * float(r)
    return cap / init_w


def _sim_k_slots_v1(tdf: pd.DataFrame, k_slots: int, fee_override: float | None = None):
    if tdf.empty:
        return pd.DataFrame(), 1.0, 0.0, 1.0
    srt = tdf.sort_values(["buy_dt", "score", "circ_mcap", "c6"], ascending=[True, False, True, True])
    slots_free = [""] * k_slots
    slots_eq = [1.0 / k_slots] * k_slots
    taken = []
    eq_hist = [1.0]
    for bdt, grp in srt.groupby("buy_dt", sort=True):
        avail = [i for i in range(k_slots) if slots_free[i] == "" or slots_free[i] < bdt]
        if not avail:
            continue
        for si, (_, row) in zip(avail, grp.head(len(avail)).iterrows()):
            r = float(row["net_ret"])
            if fee_override is not None:
                gross = (1.0 + r) / (1.0 - FEE_RT) - 1.0
                r = (1.0 + gross) * (1.0 - fee_override) - 1.0
            slots_eq[si] *= (1.0 + r)
            slots_free[si] = str(row["sell_dt"])
            d = row.to_dict()
            d["net_ret_eval"] = r
            d["slot_id"] = si
            taken.append(d)
        eq_hist.append(sum(slots_eq))
    if not taken:
        return pd.DataFrame(), 1.0, 0.0, 1.0
    res_df = pd.DataFrame(taken).sort_values(["sell_dt", "buy_dt"]).reset_index(drop=True)
    nav = float(sum(slots_eq))
    arr = np.array(eq_hist, dtype=float)
    mdd = float(np.min(arr / np.maximum.accumulate(arr) - 1.0))
    # Cap 100w -> 1000w simulation for k_slots (each slot starts at 100/k, total bet capped at 1000w)
    if k_slots == 1:
        cap_mult = calc_cap_nav(res_df["net_ret_eval"].to_numpy(dtype=float), 100.0, 1000.0)
    else:
        # Track 3 slots starting at 100/k, each slot bet capped at 1000/k
        s_cap = [100.0 / k_slots] * k_slots
        for row in res_df.itertuples(index=False):
            sid = int(row.slot_id)
            bet = min(s_cap[sid], 1000.0 / k_slots)
            s_cap[sid] += bet * float(row.net_ret_eval)
        cap_mult = sum(s_cap) / 100.0
    return res_df, nav, mdd, float(cap_mult)


def calc_hlz_dsr_from_trades(tdf: pd.DataFrame, sh300_map: dict, all_dts: list, m_trials: int = 150) -> dict:
    if tdf.empty or len(tdf) < 3:
        return {"hlz_t_raw": 0.0, "hlz_t_ex": 0.0, "dsr_raw": 0.0, "dsr_ex": 0.0}
    dt_prev = {}
    for i, d in enumerate(all_dts):
        dt_prev[d] = all_dts[i - 1] if i > 0 else d
    def b_ret(bdt, sdt):
        p0 = sh300_map.get(dt_prev.get(bdt, bdt))
        p1 = sh300_map.get(sdt)
        return (p1 / p0 - 1.0) if (p0 and p1 and p0 > 0) else 0.0
    raw = tdf["net_ret_eval"].to_numpy(dtype=float)
    ex = np.array([float(r.net_ret_eval) - b_ret(r.buy_dt, r.sell_dt) for r in tdf.itertuples(index=False)], dtype=float)
    def _calc(x):
        n = len(x)
        sd = float(np.std(x, ddof=1))
        if n < 3 or sd < 1e-12:
            return 0.0, 0.0
        sr = float(np.mean(x) / sd)
        t_v = sr * math.sqrt(n)
        sk = float(stats.skew(x, bias=False))
        ku = max(1.0, float(stats.kurtosis(x, fisher=False, bias=False)))
        gm = 0.5772156649
        sr0 = (1.0 / math.sqrt(n - 1)) * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / m_trials) + gm * stats.norm.ppf(1.0 - 1.0 / (m_trials * math.e)))
        den = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2)))
        dsr = float(stats.norm.cdf((sr - sr0) * math.sqrt(n - 1) / den))
        return round(t_v, 2), round(dsr, 4)
    tr, dr = _calc(raw)
    te, de = _calc(ex)
    return {"hlz_t_raw": tr, "hlz_t_ex": te, "dsr_raw": dr, "dsr_ex": de}


def calc_window_d15(tdf: pd.DataFrame, mkt: pd.DataFrame, s_dt: str, e_dt: str,
                    exclude_924: bool = False, m_trials: int = 150) -> dict:
    m_win = mkt[(mkt["dt"] >= s_dt) & (mkt["dt"] <= e_dt)].sort_values("dt")
    if exclude_924:
        m_win = m_win[~((m_win["dt"] >= "2024-09-24") & (m_win["dt"] <= "2024-10-08"))]
    if m_win.empty:
        return {"n_trades": 0}

    pre = mkt[mkt["dt"] < s_dt]
    hs0 = float(pre.iloc[-1]["sh000300"]) if len(pre) else float(m_win.iloc[0]["sh000300"])
    if exclude_924:
        hs_cum = float((1.0 + m_win["sh000300_ret"]).prod() - 1.0)
    else:
        hs_cum = float(m_win.iloc[-1]["sh000300"] / hs0 - 1.0)
    ew20_cum = float((1.0 + m_win["ew_ret_20cm"]).prod() - 1.0)

    sub = tdf[(tdf["signal_dt"] >= s_dt) & (tdf["signal_dt"] <= e_dt)].copy() if not tdf.empty else pd.DataFrame()
    if exclude_924 and not sub.empty:
        sub = sub[~((sub["signal_dt"] >= "2024-09-24") & (sub["signal_dt"] <= "2024-10-08"))]
    if sub.empty:
        return {"n_days": 0, "n_trades": 0, "hs300_pct": round(hs_cum * 100, 2), "ew20_pct": round(ew20_cum * 100, 2)}

    day_rets = sub.groupby("signal_dt", sort=True)["net_ret"].mean()
    dew_nav = float((1.0 + day_rets).prod())
    dew_c = (1.0 + day_rets).cumprod()
    dew_mdd = float((dew_c / dew_c.cummax() - 1.0).min())
    dew_ex5 = float((1.0 + day_rets.drop(day_rets.nlargest(5).index)).prod()) if len(day_rets) > 5 else 1.0

    t1, nav1, mdd1, cap1 = _sim_k_slots_v1(sub, 1)
    t3, nav3, mdd3, cap3 = _sim_k_slots_v1(sub, 3)
    _, nav1_50, _, _ = _sim_k_slots_v1(sub, 1, fee_override=0.0050)
    _, nav3_50, _, _ = _sim_k_slots_v1(sub, 3, fee_override=0.0050)

    r1 = t1["net_ret_eval"].to_numpy(dtype=float) if len(t1) else np.array([0.0])
    ex5_1 = float(np.prod(1.0 + np.sort(r1)[:-5])) if len(r1) > 5 else 1.0
    r3 = t3["net_ret_eval"].to_numpy(dtype=float) if len(t3) else np.array([0.0])
    if len(t3) > 5:
        top5_i = set(t3["net_ret_eval"].nlargest(5).index)
        s_ex = [1.0 / 3.0] * 3
        for idx, row in t3.iterrows():
            if idx not in top5_i:
                s_ex[int(row["slot_id"])] *= (1.0 + float(row["net_ret_eval"]))
        ex5_3 = float(sum(s_ex))
    else:
        ex5_3 = 1.0

    def _wr_po(r):
        w, l = r[r > 0], r[r <= 0]
        wr = float((r > 0).mean() * 100) if len(r) else 0.0
        po = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
        return round(wr, 1), round(po, 2)

    wr1, po1 = _wr_po(r1)
    wr3, po3 = _wr_po(r3)
    all_dts = mkt["dt"].tolist()
    sh300_map = dict(zip(mkt["dt"], mkt["sh000300"]))
    hd1 = calc_hlz_dsr_from_trades(t1, sh300_map, all_dts, m_trials=m_trials)
    hd3 = calc_hlz_dsr_from_trades(t3, sh300_map, all_dts, m_trials=m_trials)

    return {
        "n_days": int(len(day_rets)), "n_trades": int(len(sub)),
        "delisted_trades": int(sub["is_delisted"].sum()) if "is_delisted" in sub.columns else 0,
        "dew_nav": round(dew_nav, 3), "dew_ex5_nav": round(dew_ex5, 3), "dew_mdd_pct": round(dew_mdd * 100, 1),
        "n_1s": int(len(t1)), "wr_1s": wr1, "po_1s": po1, "nav_1s": round(nav1, 3), "mdd_1s_pct": round(mdd1 * 100, 1),
        "ex5_1s": round(ex5_1, 3), "fee50_1s": round(nav1_50, 3), "cap1m_10m_1s": round(cap1, 3),
        "n_3s": int(len(t3)), "wr_3s": wr3, "po_3s": po3, "nav_3s": round(nav3, 3), "mdd_3s_pct": round(mdd3 * 100, 1),
        "ex5_3s": round(ex5_3, 3), "fee50_3s": round(nav3_50, 3), "cap1m_10m_3s": round(cap3, 3),
        "hs300_pct": round(hs_cum * 100, 2), "ew20_pct": round(ew20_cum * 100, 2),
        "ex_1s_hs300_pp": round((nav1 - 1.0 - hs_cum) * 100, 1),
        "ex_3s_hs300_pp": round((nav3 - 1.0 - hs_cum) * 100, 1),
        "ex_3s_ew20_pp": round((nav3 - 1.0 - ew20_cum) * 100, 1),
        "ex_dew_hs300_pp": round((dew_nav - 1.0 - hs_cum) * 100, 1),
        "ex_dew_ew20_pp": round((dew_nav - 1.0 - ew20_cum) * 100, 1),
        "hlz_t_1s_raw": hd1["hlz_t_raw"], "hlz_t_1s_ex": hd1["hlz_t_ex"], "dsr_1s": hd1["dsr_ex"],
        "hlz_t_3s_raw": hd3["hlz_t_raw"], "hlz_t_3s_ex": hd3["hlz_t_ex"], "dsr_3s": hd3["dsr_ex"],
    }
