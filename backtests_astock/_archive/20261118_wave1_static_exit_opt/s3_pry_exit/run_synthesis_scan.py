#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_synthesis_scan.py
基于第一轮 150 变体发现，对「X7 弱斩连板机制 + 时间衰减动态限价止盈 + 缩短周期(2~3日)」做精确消融与正交合成扫描。
严格先看 IS (2022~2023) 在 P165/P150/P140/P000 四池同向性，再看 OOS (2024~2026-11-16)。
"""
import os, sys, json, time
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s3_pry_exit"
sys.path.insert(0, OUT_DIR)
import run_exit_scan as base


def sim_synth(d, p0, buy_px, tp_fn, max_h=3,
              t1_cut_mode="none", t2_stall_ratio=None,
              zt_relay_if_unfilled=True, end_zt_relay=True,
              day0_cut_mode="reseal_only"):
    L = len(d["dts"])
    if p0 + 1 >= L or buy_px <= 0:
        return np.nan, "", 0
    o, h, l, c, pre_c, dt_px, zt_px, is_zt, is_yz_dt, adjf = (
        d["open"], d["high"], d["low"], d["close"], d["pre_c"], d["dt_px"], d["zt_px"],
        d["is_zt"], d["is_yizi_dt"], d["adjf"]
    )
    if is_zt[p0]:
        return base.hold_zt_relay(d, p0, p0, buy_px)

    day0_reseal = (c[p0] <= dt_px[p0] + 0.005)
    do_cut = day0_reseal
    if day0_cut_mode == "reseal_or_neg5" and (c[p0] < o[p0]) and (c[p0] / pre_c[p0] - 1.0 <= -0.05):
        do_cut = True
    if do_cut:
        ps = base.first_sellable_day(d, p0 + 1)
        s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return base.ret_from_px(d, p0, ps, s_px, buy_px)

    end_p = min(L - 1, p0 + max_h)
    for step_idx, k in enumerate(range(p0 + 1, end_p + 1), start=1):
        if is_yz_dt[k]:
            continue
        af_ratio = adjf[p0] / adjf[k]

        # Pre-market limit sell price if tp_fn is given
        if tp_fn is not None:
            tp_r = tp_fn(step_idx)
            if tp_r is not None:
                tp_px = round(buy_px * (1.0 + tp_r) * af_ratio, 2)
                if o[k] >= tp_px:
                    return base.ret_from_px(d, p0, k, o[k], buy_px)
                if h[k] >= tp_px:
                    return base.ret_from_px(d, p0, k, tp_px, buy_px)

        # Unfilled at TP: check limit-up board relay
        if zt_relay_if_unfilled and is_zt[k]:
            # Only possible if tp_fn is None or tp_px > zt_px[k]
            return base.hold_zt_relay(d, p0, k, buy_px)

        # EOD weak / stall cut (only if not final day and not limit-down locked)
        if k < end_p:
            c_adj_k = c[k] * (adjf[k] / adjf[p0])
            c_adj_prev = c[k - 1] * (adjf[k - 1] / adjf[p0])
            if step_idx == 1 and t1_cut_mode != "none":
                cut_now = False
                if t1_cut_mode == "lt_d0_close" and c_adj_k < c_adj_prev:
                    cut_now = True
                elif t1_cut_mode == "lt_buy_px" and c_adj_k < buy_px:
                    cut_now = True
                elif t1_cut_mode == "lt_buy_m2" and c_adj_k < buy_px * 0.98:
                    cut_now = True
                elif t1_cut_mode == "lt_d0_m15" and c_adj_k < c_adj_prev * 0.985:
                    cut_now = True
                elif t1_cut_mode == "lt_d0_low" and c_adj_k < d["low"][p0]:
                    cut_now = True
                if cut_now:
                    if c[k] > dt_px[k] + 0.005:
                        return base.ret_from_px(d, p0, k, c[k], buy_px)
                    ps = base.first_sellable_day(d, k + 1)
                    s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
                    return base.ret_from_px(d, p0, ps, s_px, buy_px)

            if step_idx >= 2 and t2_stall_ratio is not None:
                if c_adj_k < c_adj_prev * t2_stall_ratio:
                    if c[k] > dt_px[k] + 0.005:
                        return base.ret_from_px(d, p0, k, c[k], buy_px)
                    ps = base.first_sellable_day(d, k + 1)
                    s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
                    return base.ret_from_px(d, p0, ps, s_px, buy_px)

    ps = base.first_sellable_day(d, end_p)
    if end_zt_relay and is_zt[ps]:
        return base.hold_zt_relay(d, p0, ps, buy_px)
    return base.ret_from_px(d, p0, ps, c[ps], buy_px)


def main():
    t0 = time.time()
    df, cb, _, _, _, _, _ = base.load_all_data()
    sub = base.build_base_candidates(df, cb)
    n_sub = len(sub)

    def run_sim(fn):
        rets = np.full(n_sub, np.nan, dtype=float)
        edts = np.full(n_sub, "", dtype=object)
        hlds = np.zeros(n_sub, dtype=int)
        for idx, r in enumerate(sub.itertuples(index=False)):
            rv, ed, hd = fn(cb[r.c6], r.p0, r.buy_px, r)
            rets[idx], edts[idx], hlds[idx] = rv, ed, hd
        return rets, edts, hlds

    specs = []

    # 1. X7 ablation
    specs.append(("S00_X10_v1_ref", lambda d, p0, b, r: sim_synth(
        d, p0, b, lambda s: float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), max_h=4, t1_cut_mode="none", t2_stall_ratio=None, zt_relay_if_unfilled=False, end_zt_relay=False)))
    specs.append(("S01_X7_exact_3d", lambda d, p0, b, r: base.sim_x7_relay(d, p0, b)))
    specs.append(("S02_X7_no_t1_cut", lambda d, p0, b, r: sim_synth(
        d, p0, b, None, max_h=3, t1_cut_mode="none", t2_stall_ratio=0.985)))
    specs.append(("S03_X7_cut_lt_buy", lambda d, p0, b, r: sim_synth(
        d, p0, b, None, max_h=3, t1_cut_mode="lt_buy_px", t2_stall_ratio=0.985)))
    specs.append(("S04_X7_cut_lt_buym2", lambda d, p0, b, r: sim_synth(
        d, p0, b, None, max_h=3, t1_cut_mode="lt_buy_m2", t2_stall_ratio=0.985)))
    specs.append(("S05_X7_2d", lambda d, p0, b, r: sim_synth(
        d, p0, b, None, max_h=2, t1_cut_mode="lt_d0_close", t2_stall_ratio=None)))
    specs.append(("S06_X7_4d", lambda d, p0, b, r: sim_synth(
        d, p0, b, None, max_h=4, t1_cut_mode="lt_d0_close", t2_stall_ratio=0.985)))

    # 2. X10 + weak cut + max_h + ZT relay
    for mh in [2, 3, 4]:
        for t1c in ["none", "lt_d0_close", "lt_buy_px", "lt_buy_m2", "lt_d0_low"]:
            for t2s in [None, 0.985]:
                if mh == 2 and t2s is not None:
                    continue
                nm = f"S_X10_{mh}d_t1_{t1c}_t2_{'985' if t2s else 'no'}"
                specs.append((nm, (lambda m0, c1, s2: lambda d, p0, b, r: sim_synth(
                    d, p0, b, lambda s: float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)),
                    max_h=m0, t1_cut_mode=c1, t2_stall_ratio=s2, zt_relay_if_unfilled=True, end_zt_relay=True))(mh, t1c, t2s)))

    # 3. High-T1 TimeDecay + weak cut + ZT relay (so T+1 ZT never gets capped early, spikes >11% still captured, weak fades get cut!)
    decay_schedules = [
        ("DecA", lambda r: [float(np.clip(0.55*abs(r.prev_ret10), 0.11, 0.20)), float(np.clip(0.40*abs(r.prev_ret10), 0.06, 0.14)), 0.05, 0.02]),
        ("DecB", lambda r: [float(np.clip(0.55*abs(r.prev_ret10), 0.08, 0.20)), float(np.clip(0.40*abs(r.prev_ret10), 0.06, 0.14)), 0.05, 0.02]),
        ("DecC", lambda r: [float(np.clip(0.50*abs(r.prev_ret10), 0.11, 0.18)), float(np.clip(0.40*abs(r.prev_ret10), 0.06, 0.14)), 0.05, 0.03]),
        ("DecD_t1noTP", lambda r: [None, float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), 0.05, 0.02]),
        ("DecE_t111_t28", lambda r: [0.11, 0.08, 0.05, 0.03]),
    ]
    for dnm, dfn in decay_schedules:
        for mh in [2, 3, 4]:
            for t1c in ["none", "lt_d0_close", "lt_buy_px", "lt_buy_m2"]:
                for t2s in [None, 0.985]:
                    if mh == 2 and t2s is not None:
                        continue
                    if t1c == "none" and t2s is not None:
                        continue
                    nm = f"S_{dnm}_{mh}d_t1_{t1c}_t2_{'985' if t2s else 'no'}"
                    specs.append((nm, (lambda f0, m0, c1, s2: lambda d, p0, b, r: sim_synth(
                        d, p0, b, lambda s: f0(r)[min(s-1, len(f0(r))-1)],
                        max_h=m0, t1_cut_mode=c1, t2_stall_ratio=s2, zt_relay_if_unfilled=True, end_zt_relay=True))(dfn, mh, t1c, t2s)))

    # 4. Also test Pure X7 + High Cap limit TP on T+2/T+3 (T+1 no TP ceiling -> catch any ZT! T+2/T+3 lock spikes)
    for tp2 in [0.10, 0.12, 0.15]:
        specs.append((f"S_X7_plus_T2TP{int(tp2*100)}", (lambda t2: lambda d, p0, b, r: sim_synth(
            d, p0, b, lambda s: None if s == 1 else (t2 if s == 2 else 0.08),
            max_h=3, t1_cut_mode="lt_d0_close", t2_stall_ratio=0.985, zt_relay_if_unfilled=True, end_zt_relay=True))(tp2)))

    print(f"Running {len(specs)} synthesis variants...")
    rows = []
    full = {}
    for nm, fn in specs:
        rets, edts, hlds = run_sim(fn)
        r65 = base.eval_variant(sub, rets, edts, hlds, 165)
        r50 = base.eval_variant(sub, rets, edts, hlds, 150)
        r40 = base.eval_variant(sub, rets, edts, hlds, 140)
        r00 = base.eval_variant(sub, rets, edts, hlds, 0)
        full[nm] = {"P165": r65, "P150": r50, "P140": r40, "P000": r00}
        rows.append({
            "variant": nm,
            "P165_ss": r65["ALL"]["ss"]["nav"],
            "P165_ss_wr": r65["ALL"]["ss"]["wr"],
            "P165_ss_plr": r65["ALL"]["ss"]["plr"],
            "P165_ss_mdd": r65["ALL"]["ss"]["mdd"],
            "P165_ss_h": r65["ALL"]["ss"]["avg_hold"],
            "P165_IS_s": r65["IS"]["ss"]["nav"],
            "P165_OOS_s": r65["OOS"]["ss"]["nav"],
            "P165_IS_d": r65["IS"]["deq"]["nav"],
            "P165_OOS_d": r65["OOS"]["deq"]["nav"],
            "P150_IS_d": r50["IS"]["deq"]["nav"],
            "P150_OOS_d": r50["OOS"]["deq"]["nav"],
            "P150_IS_s": r50["IS"]["ss"]["nav"],
            "P150_OOS_s": r50["OOS"]["ss"]["nav"],
            "P140_IS_d": r40["IS"]["deq"]["nav"],
            "P140_OOS_d": r40["OOS"]["deq"]["nav"],
            "P000_IS_d": r00["IS"]["deq"]["nav"],
            "P000_OOS_d": r00["OOS"]["deq"]["nav"],
            "P000_ALL_d": r00["ALL"]["deq"]["nav"],
        })

    out_df = pd.DataFrame(rows)
    out_df.to_csv(f"{OUT_DIR}/scan_synthesis.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/scan_synthesis_full.json", "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, indent=2)

    # Rank strictly by IS combined robustness (geometric mean of P165_IS_d, P150_IS_d, P140_IS_d, P000_IS_d and P165_IS_s, P150_IS_s)
    out_df["IS_rank_score"] = (
        out_df["P165_IS_d"] * out_df["P150_IS_d"] * out_df["P140_IS_d"] * out_df["P000_IS_d"] * out_df["P165_IS_s"] * out_df["P150_IS_s"]
    ) ** (1.0 / 6.0)
    print("\n=== TOP 25 BY PURE IS MULTI-POOL GEOMETRIC SCORE ===")
    cols = ["variant", "P165_ss", "P165_ss_wr", "P165_ss_mdd", "P165_ss_h",
            "P165_IS_d", "P165_OOS_d", "P150_IS_d", "P150_OOS_d", "P140_IS_d", "P140_OOS_d", "P000_ALL_d"]
    print(out_df.sort_values("IS_rank_score", ascending=False).head(25)[cols].to_string(index=False))

    print("\n=== REFERENCE ROWS (X10_v1 vs X7 vs X10_2d) ===")
    print(out_df[out_df["variant"].isin(["S00_X10_v1_ref", "S01_X7_exact_3d", "S_X10_2d_t1_none_t2_no", "S_X10_3d_t1_lt_d0_close_t2_985"])][cols].to_string(index=False))
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
