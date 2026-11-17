#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Precompute Strict Zero-Lookahead 8 Entries x 10 Exits Return & Exit-Date Matrices on full_pry_master_enriched.parquet."""
import os, time, pickle
import numpy as np
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
GFM_DIR = f"{BASE}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{BASE}/backtests_astock2/p5_full_pry_universe"
COST = 0.0020  # 0.20% round-trip commission + stamp duty + slippage


def first_sellable_day(d, start_pos):
    """If locked in one-word limit-down (high <= dt_px + 0.005), defer until unsealed."""
    L = len(d["dts"])
    p = start_pos
    while p < L - 1 and d["is_yizi_dt"][p]:
        p += 1
    return min(p, L - 1)


def sim_single_trade(d, p0, buy_px, day0_reseal, exit_code, dyn_tp):
    L = len(d["dts"])
    if p0 + 1 >= L or buy_px <= 0:
        return np.nan, ""
    o, h, l, c, dt_px, is_zt, is_yz_dt, dts = (
        d["open"], d["high"], d["low"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"]
    )
    # 1. Immediate cut at T+1 open if Day-0 re-sealed limit-down (for X2..X10)
    if day0_reseal and exit_code != "X1":
        ps = first_sellable_day(d, p0 + 1)
        s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return float(s_px / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    # Helper for ZT board-relay from day pk onward
    def hold_zt_relay(pk, allow_yang_forgive=False):
        forgive_used = False
        cur = pk
        while cur < L - 1:
            nxt = cur + 1
            if is_yz_dt[nxt]:
                nxt2 = first_sellable_day(d, nxt)
                s_px = o[nxt2] if o[nxt2] > dt_px[nxt2] + 0.005 else c[nxt2]
                return float(s_px / buy_px * (1.0 - COST) - 1.0), str(dts[nxt2])
            if is_zt[nxt]:
                cur = nxt
                continue
            if allow_yang_forgive and (not forgive_used) and (c[nxt] > o[nxt]) and (c[nxt] >= c[cur] * 0.97):
                forgive_used = True
                cur = nxt
                continue
            return float(c[nxt] / buy_px * (1.0 - COST) - 1.0), str(dts[nxt])
        return float(c[cur] / buy_px * (1.0 - COST) - 1.0), str(dts[cur])

    # If Day-0 itself closed at ZT (地天板!), relay boards!
    if is_zt[p0]:
        return hold_zt_relay(p0, allow_yang_forgive=(exit_code == "X7"))

    if exit_code == "X1":
        ps = first_sellable_day(d, p0 + 1)
        s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return float(s_px / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if exit_code == "X2":
        ps = first_sellable_day(d, p0 + 1)
        if ps == p0 + 1 and is_zt[ps]:
            return hold_zt_relay(ps, False)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if exit_code in ("X3", "X4", "X5", "X10"):
        tp_map = {"X3": (0.05, 2), "X4": (0.07, 3), "X5": (0.10, 5), "X10": (dyn_tp, 4)}
        tp_r, max_h = tp_map[exit_code]
        tp_px = round(buy_px * (1.0 + tp_r), 2)
        end_p = min(L - 1, p0 + max_h)
        for k in range(p0 + 1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if o[k] >= tp_px:
                if is_zt[k]:
                    return hold_zt_relay(k, False)
                return float(o[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k])
            if h[k] >= tp_px:
                if is_zt[k]:
                    return hold_zt_relay(k, False)
                return float(tp_px / buy_px * (1.0 - COST) - 1.0), str(dts[k])
        ps = first_sellable_day(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if exit_code == "X6":  # 去弱留强: T+1低开超2.5%立砍，否则4日摸+9%
        p1 = p0 + 1
        if (not is_yz_dt[p1]) and (o[p1] < c[p0] * 0.975):
            return float(o[p1] / buy_px * (1.0 - COST) - 1.0), str(dts[p1])
        tp_px = round(buy_px * 1.09, 2)
        end_p = min(L - 1, p0 + 4)
        for k in range(p1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if h[k] >= tp_px:
                if is_zt[k]:
                    return hold_zt_relay(k, False)
                return float(max(o[k], tp_px) / buy_px * (1.0 - COST) - 1.0), str(dts[k])
        ps = first_sellable_day(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if exit_code == "X7":  # 连板主升格局卖法
        p1 = first_sellable_day(d, p0 + 1)
        if is_zt[p1]:
            return hold_zt_relay(p1, True)
        if c[p1] < c[p0]:
            return float(c[p1] / buy_px * (1.0 - COST) - 1.0), str(dts[p1])
        end_p = min(L - 1, p0 + 3)
        for k in range(p1 + 1, end_p + 1):
            if is_zt[k]:
                return hold_zt_relay(k, True)
            if c[k] < c[k - 1] * 0.985:
                ps = first_sellable_day(d, k)
                return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])
        ps = first_sellable_day(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if exit_code == "X8":  # 移动高水位止盈 (摸+6%后回撤3%锁利, 破buy_px*0.95止损, 4天)
        end_p = min(L - 1, p0 + 4)
        peak = max(buy_px, c[p0])
        for k in range(p0 + 1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if is_zt[k]:
                return hold_zt_relay(k, False)
            peak = max(peak, h[k])
            if peak >= buy_px * 1.06 and l[k] <= peak * 0.97:
                s_px = min(o[k], peak * 0.97) if o[k] < peak * 0.97 else peak * 0.97
                return float(s_px / buy_px * (1.0 - COST) - 1.0), str(dts[k])
            if l[k] <= buy_px * 0.945:
                s_px = min(o[k], buy_px * 0.945)
                return float(s_px / buy_px * (1.0 - COST) - 1.0), str(dts[k])
        ps = first_sellable_day(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if exit_code == "X9":  # 超跌回归5日均线卖出 (最长5天)
        end_p = min(L - 1, p0 + 5)
        for k in range(p0 + 1, end_p + 1):
            if is_yz_dt[k]:
                continue
            ma5_prev = float(np.mean(c[max(0, k - 4):k])) if k >= 1 else buy_px * 1.06
            tgt = max(buy_px * 1.03, ma5_prev)
            if h[k] >= tgt:
                if is_zt[k]:
                    return hold_zt_relay(k, False)
                return float(max(o[k], tgt) / buy_px * (1.0 - COST) - 1.0), str(dts[k])
        ps = first_sellable_day(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    return np.nan, ""


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/full_pry_master_enriched.parquet")
    with open(f"{GFM_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    n = len(df)
    c6_v = df["c6"].values
    dt_v = df["dt_str"].values
    o_v = df["open"].values; h_v = df["high"].values; l_v = df["low"].values; c_v = df["close"].values
    prec_v = df["pre_c"].values; dtpx_v = df["dt_price"].values; ztpx_v = df["zt_price"].values
    tdt_v = df["touch_dt"].values; odt_v = df["open_is_dt"].values; isdt_v = df["is_dt"].values; iszt_v = df["is_zt"].values
    ptdt_v = df["prev_touch_dt"].fillna(False).values.astype(bool)
    pisdt_v = df["prev_is_dt"].fillna(True).values.astype(bool)
    opct_v = df["o_pct"].values
    ret10_v = df["prev_ret10"].fillna(-0.15).values

    # 8 strict zero-lookahead entry definitions: (code_name, trigger_mask, buy_px_array, day0_reseal_flag)
    entries = [
        ("E1_opendt_lift15", tdt_v & odt_v & (h_v >= dtpx_v * 1.015), np.round(dtpx_v * 1.015, 2), isdt_v),
        ("E2_opendt_lift35", tdt_v & odt_v & (h_v >= dtpx_v * 1.035), np.round(dtpx_v * 1.035, 2), isdt_v),
        ("E3_opendt_red0", tdt_v & odt_v & (h_v >= prec_v), np.round(prec_v, 2), isdt_v),
        ("E4_intradive_dt", tdt_v & (~odt_v), np.round(dtpx_v + 0.01, 2), isdt_v),
        ("E5_tail1457_all", tdt_v & (~isdt_v) & (~iszt_v) & (c_v >= dtpx_v * 1.015), c_v, np.zeros(n, dtype=bool)),
        ("E6_tail1457_yang", tdt_v & (~isdt_v) & (~iszt_v) & (c_v > o_v) & (c_v >= dtpx_v * 1.03), c_v, np.zeros(n, dtype=bool)),
        ("E7_tail1457_opendt", tdt_v & odt_v & (~isdt_v) & (~iszt_v) & (c_v >= dtpx_v * 1.02), c_v, np.zeros(n, dtype=bool)),
        ("E8_nextday_w2s", ptdt_v & (~pisdt_v) & (~odt_v) & (o_v < ztpx_v - 0.011) & (opct_v >= -0.03) & (opct_v <= 0.06), o_v, isdt_v),
    ]
    exits = ["X1", "X2", "X3", "X4", "X5", "X6", "X7", "X8", "X9", "X10"]

    out_ret = {}
    out_edt = {}
    for ename, mask, bpx_arr, reseal_arr in entries:
        idxs = np.where(mask & (~df["is_st_or_delist"].values))[0]
        print(f"  Simulating {ename}: {len(idxs):,} triggers...")
        r_mat = {ex: np.full(n, np.nan, dtype=np.float32) for ex in exits}
        d_mat = {ex: np.full(n, "", dtype="U10") for ex in exits}
        for i in idxs:
            d = cb.get(c6_v[i])
            if d is None:
                continue
            p0 = d["date_to_pos"].get(dt_v[i])
            if p0 is None or p0 + 1 >= len(d["dts"]):
                continue
            dyn_tp = float(np.clip(0.45 * abs(ret10_v[i]), 0.06, 0.16))
            for ex in exits:
                rv, ed = sim_single_trade(d, p0, float(bpx_arr[i]), bool(reseal_arr[i]), ex, dyn_tp)
                r_mat[ex][i] = rv
                d_mat[ex][i] = ed
        out_ret[ename] = r_mat
        out_edt[ename] = d_mat

    with open(f"{OUT_DIR}/return_matrix_8x10.pkl", "wb") as f:
        pickle.dump({"ret": out_ret, "exit_dt": out_edt, "entries": [e[0] for e in entries], "exits": exits}, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[+] Saved return_matrix_8x10.pkl across 8x10=80 execution pairs in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
