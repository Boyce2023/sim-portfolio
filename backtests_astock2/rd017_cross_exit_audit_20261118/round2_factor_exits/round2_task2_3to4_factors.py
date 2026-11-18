#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
round2_task2_3to4_factors.py — 第二轮任务二: 三进四 V4.0 (s_3to4) 动态持仓卖点因子实证
在 IS (2022~2023) 逐项检验盘后龙虎榜/公告/雪球/09:25队友竞价/高标V5.1条件免死/条件挂96%异动单,
对比 std90 (95笔) 与 strict102 (31笔) 在 IS/OOS/2026/25-26严监管期 的表现。
"""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD2_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118/round2_factor_exits"
RD1_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, RD2_DIR)
sys.path.insert(0, RD1_DIR)
sys.path.insert(0, UPG_DIR)

import pit_factor_helpers as pfh
import upgrade_3to4_pit as u3
import task3_3to4_exit_audit as t3

FEE = u3.FEE_RATE
WINDOWS = [
    ("full_5y", "2021-11-16", "2026-11-16", pfh.csi_ret_pct("2021-11-16", "2026-11-16")),
    ("is_22_23", "2022-01-04", "2023-12-31", pfh.csi_ret_pct("2022-01-04", "2023-12-31")),
    ("oos_24_26", "2024-01-01", "2026-11-16", pfh.csi_ret_pct("2024-01-01", "2026-11-16")),
    ("y25_26_reg", "2025-01-01", "2026-11-16", pfh.csi_ret_pct("2025-01-01", "2026-11-16")),
    ("y2026_1y", "2026-01-01", "2026-11-16", pfh.csi_ret_pct("2026-01-01", "2026-11-16")),
]


def get_day_risk_flags(c6: str, cb: dict, pos: int, k: int, env: dict, top_yz_buyers: set) -> dict:
    """严格 PIT 计算持仓第 k 日 09:25 已知的动态风险标志 (所有数据 <= k-1 盘后或 < k 09:25)"""
    dk = str(cb["dts"][k])
    prev_dk = str(cb["dts"][k - 1])
    d5_back = str(cb["dts"][max(0, k - 5)])

    lbp = env["lhb_buy_info"].get((prev_dk, c6), {})
    lsp = env["lhb_sell_info"].get((prev_dk, c6), {})
    lh_cnt = int(lbp.get("lh_cnt", 0))
    lh_rat = float(lbp.get("lh_ratio", 0.0))
    tot_b = float(lbp.get("tot_buy", 0.0))
    surf_yz = bool(lbp.get("surf_yz", False))
    inst_sell_amt = float(lsp.get("inst_sell", 0.0))
    inst_buy_amt = float(lbp.get("inst_buy", 0.0))
    inst_net_sell = (inst_sell_amt > inst_buy_amt) and (inst_sell_amt >= 1e7)

    sell_depts = lsp.get("sell_depts", [])
    top_yz_dump = any(any(ty[:6] in sd or ty == sd for sd in sell_depts) for ty in top_yz_buyers) if top_yz_buyers else False

    reg_new = pfh.has_ts_in_window(env["reg_ts_map"], c6, f"{prev_dk} 15:00:00", f"{dk} 09:25:00")
    abn_new = pfh.has_ts_in_window(env["abn_ts_map"], c6, f"{prev_dk} 15:00:00", f"{dk} 09:25:00")
    tox_new = pfh.has_ts_in_window(env["tox_ts_map"], c6, f"{prev_dk} 15:00:00", f"{dk} 09:25:00")
    ex_r5 = pfh.ex_reg_cnt_5d(env, c6, prev_dk, f"{dk} 09:25:00", d5_back)

    xq_ov = pfh.count_ts_in_window(env["xq_arr"], c6, f"{prev_dk} 15:00:00", f"{dk} 09:25:00")
    peers_op, peers_dt, _ = pfh.get_peers_0925(env, c6, prev_dk, dk)
    ms = env["mkt_stats"].get(dk, {})
    mkt_p1b = float(ms.get("mkt_prev_1b_open_avg", 0.0))

    return {
        "f_lhb_lhasa_cnt3": lh_cnt >= 3,
        "f_lhb_lhasa_rat20": bool(tot_b > 0 and lh_rat >= 0.20),
        "f_lhb_lhasa_any": bool(lh_cnt >= 3 or (tot_b > 0 and lh_rat >= 0.20)),
        "f_lhb_surf_yz": surf_yz,
        "f_lhb_inst_sell": inst_net_sell,
        "f_lhb_top_yz_dump": top_yz_dump,
        "f_reg_new": bool(reg_new or tox_new),
        "f_reg_or_ex2": bool(reg_new or tox_new or ex_r5 >= 2),
        "f_reg_or_abn": bool(reg_new or tox_new or abn_new or ex_r5 >= 2),
        "f_xq_ov_4": xq_ov >= 4,
        "f_xq_ov_8": xq_ov >= 8,
        "f_peers_nuke": bool(peers_op < -0.020 or peers_dt >= 2),
        "f_mkt_1b_nuke": bool(mkt_p1b < -0.005),
    }


def sim_3to4_dynamic(
    c6: str, cb: dict, pos: int, bpx_raw: float, b5m: dict, env: dict,
    cut_0925_fn=None,       # fn(flags, k_rel) -> bool: cut at k 09:25
    cond_dev_fn=None,       # fn(flags, cum_flags, k_rel) -> float|None: attach double_dev(disc) on day k
    imm_mode: str = "always",  # "always" | "never" | "cond_v51_strict" | "cond_v51_soft"
    unsealed_refine: str = "baseline",  # "baseline" | "refine_lhb_reg" | "refine_peers_gt0"
) -> tuple:
    n = len(cb["dts"])
    top_yz_buyers = set()
    # Seed top_yz from D3 (pos-1) & D4 (pos) when evaluating k >= pos+1
    lb_d3 = env["lhb_buy_info"].get((str(cb["dts"][max(0, pos - 1)]), c6), {})
    top_yz_buyers.update(lb_d3.get("top_yz", []))

    def _run_zt_hold(start_p: int):
        k = start_p + 1
        imm_used = False
        reg_or_lhasa_seen = False
        while k < n:
            if bool(cb["is_yizi_dt"][k]):
                k += 1; continue
            prev_dk = str(cb["dts"][k - 1])
            top_yz_buyers.update(env["lhb_buy_info"].get((prev_dk, c6), {}).get("top_yz", []))

            dt_s = str(cb["dts"][k])
            ok, hk, lk, clk, pck, ztk = float(cb["open"][k]), float(cb["high"][k]), float(cb["low"][k]), float(cb["close"][k]), float(cb["pre_c"][k]), float(cb["zt_px"][k])
            dtk = round(pck * 0.90, 2)
            if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925

            flags = get_day_risk_flags(c6, cb, pos, k, env, top_yz_buyers)
            if flags["f_reg_or_ex2"] or flags["f_lhb_lhasa_any"]:
                reg_or_lhasa_seen = True

            if cut_0925_fn is not None and cut_0925_fn(flags, k - pos) and ok > dtk + 0.005:
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925

            pl_dev = None
            if cond_dev_fn is not None:
                disc = cond_dev_fn(flags, reg_or_lhasa_seen, k - pos)
                if disc is not None:
                    pl_dev = t3.get_double_dev_px_causal(cb, c6, k, disc)
                    if ok >= pl_dev and ok > dtk + 0.005:
                        return dt_s, ok, float(cb["adjf"][k]), k - pos, 925

            arr = b5m.get((c6, dt_s))
            if arr is not None and len(arr) > 0:
                peak = ok
                for row in arr:
                    hh, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                    if bh <= dtk + 0.005:
                        continue
                    if pl_dev is not None and bh >= pl_dev:
                        px_d = float(max(bo, pl_dev))
                        if px_d > dtk + 0.005:
                            return dt_s, px_d, float(cb["adjf"][k]), k - pos, hh
                    if hh >= 1345 and peak >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                        return dt_s, float(min(bo, pck * 1.050)), float(cb["adjf"][k]), k - pos, hh
                    if bh > peak:
                        peak = bh
            elif pl_dev is not None and hk >= pl_dev and pl_dev > dtk + 0.005:
                return dt_s, pl_dev, float(cb["adjf"][k]), k - pos, 1030

            if bool(cb["is_zt"][k]):
                k += 1; continue

            is_ty = (clk > ok) and (clk >= pck)
            allow_imm = False
            if is_ty and (not imm_used):
                if imm_mode == "always":
                    allow_imm = True
                elif imm_mode == "never":
                    allow_imm = False
                else:
                    ms = env["mkt_stats"].get(dt_s, {})
                    brk_r10 = float(ms.get("brk_r10_prev", 0.0))
                    csi5 = float(env["csi_5d_prev"].get(dt_s, 0.0))
                    to_k = env["day_to_map"].get((dt_s, c6), (20.0,))[0]
                    d10_back = str(cb["dts"][max(0, k - 10)])
                    has_reg = pfh.has_ts_in_window(env["reg_ts_map"], c6, f"{d10_back} 00:00:00", f"{dt_s} 14:55:00")
                    not_tomb = (hk - clk) < (clk - ok) * 1.5
                    if imm_mode == "cond_v51_strict":
                        allow_imm = (brk_r10 >= 0.20) and (csi5 > -0.025) and (to_k <= 35.0) and (not flags["f_lhb_lhasa_cnt3"]) and (not has_reg) and not_tomb
                    elif imm_mode == "cond_v51_soft":
                        # Only veto immunity on extreme risk: to > 38% OR lhasa >= 3 OR reg_10d OR csi5 < -2.5% OR tomb
                        allow_imm = (to_k <= 38.0) and (not flags["f_lhb_lhasa_cnt3"]) and (not has_reg) and (csi5 >= -0.025) and not_tomb
            if allow_imm:
                imm_used = True; k += 1; continue
            return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500
        k = n - 1
        return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500

    if not bool(cb["is_zt"][pos]):
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
        o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        if k > pos + 1:
            return cb["dts"][k], o5, float(cb["adjf"][k]), k - pos, 925
        keep_d5 = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
        if keep_d5 and unsealed_refine != "baseline":
            flags5 = get_day_risk_flags(c6, cb, pos, k, env, top_yz_buyers)
            if unsealed_refine == "refine_lhb_reg":
                if flags5["f_lhb_surf_yz"] or flags5["f_lhb_lhasa_cnt3"] or flags5["f_reg_or_ex2"]:
                    keep_d5 = False
            elif unsealed_refine == "refine_peers_nuke":
                if flags5["f_peers_nuke"] or flags5["f_lhb_surf_yz"] or flags5["f_reg_or_ex2"]:
                    keep_d5 = False
        if not keep_d5:
            return cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
        if bool(cb["is_zt"][k]):
            return _run_zt_hold(k)
        return cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500
    return _run_zt_hold(pos)


def eval_d15_3to4(raw_df: pd.DataFrame) -> dict:
    slot_df = u3.sim_single_slot(raw_df)
    res = {}
    for wn, sdt, edt, csip in WINDOWS:
        sr = raw_df[(raw_df["buy_date"] >= sdt) & (raw_df["buy_date"] <= edt)]
        ss = slot_df[(slot_df["buy_date"] >= sdt) & (slot_df["buy_date"] <= edt)]
        rr = ss["net_ret"].to_numpy(dtype=float) if not ss.empty else np.array([], dtype=float)
        dq = sr.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy(dtype=float) if not sr.empty else np.array([], dtype=float)
        res[wn] = {
            "single_slot": pfh.calc_arr_metrics(rr, csip),
            "daily_eq": {**pfh.calc_arr_metrics(dq, csip), "raw_n": int(len(sr))},
        }
    return res


def main():
    t0 = time.time()
    with open(f"{RD2_DIR}/pit_exit_env.pkl", "rb") as f:
        env = pickle.load(f)
    res = u3.run_causal_pipeline("2026-11-16", verbose=False)
    cand_df, sc_v40, code_bars, p_1030 = res["cand_df"], res["sc_v40"], res["code_bars"], res["p_1030"]
    b5m, _ = t3.load_5m_and_extra(cand_df, code_bars)

    # Use score >= 75 for wide IS univariate check + score >= 90 for std90
    raw_sc = 78.0 + res["comp_v40"].sum(axis=1)
    eligible_idx = [i for i in np.where(res["skel"] & (raw_sc >= 75.0))[0] if p_1030[i] is not None]
    items = []
    for i in eligible_idx:
        pi = p_1030[i]; r = cand_df.iloc[i]
        c6 = str(r["code"]).zfill(6); bd = str(r["buy_date"])
        cb = code_bars[c6]; pos = cb["date_to_pos"][bd]
        bpx_raw, _ = u3._sim_buy_5m(c6, bd, cb, pos, b5m, 1030)
        items.append({
            "code": c6, "name": str(r["name"]), "buy_date": bd,
            "buy_hhmm": int(pi["buy_hhmm"]), "buy_price": float(pi["buy_price"]),
            "bpx_raw": float(bpx_raw), "pos": pos, "cb": cb,
            "score": int(round(float(raw_sc[i]))),
            "priority_score": float(sc_v40[i]) * 10.0 + float(r["prio_3to4"]) * 0.1,
            "ref_ret": float(pi["net_ret"]),
        })

    # 1. Build per-holding-day IS univariate test on ZT-holding days (k >= pos+1)
    hd_rows = []
    for it in items:
        if it["buy_date"] > "2023-12-31":
            continue
        cb, pos, c6, bpx_raw = it["cb"], it["pos"], it["code"], it["bpx_raw"]
        if not bool(cb["is_zt"][pos]):
            continue
        # Run baseline from pos to know remaining baseline return
        ex_b, sp_b, adj_b, _, _ = sim_3to4_dynamic(c6, cb, pos, bpx_raw, b5m, env)
        base_ret = (sp_b * adj_b) / (bpx_raw * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        # Walk k = pos+1 .. exit day
        top_yz = set(env["lhb_buy_info"].get((str(cb["dts"][max(0, pos - 1)]), c6), {}).get("top_yz", []))
        k = pos + 1
        while k < len(cb["dts"]) and str(cb["dts"][k]) <= ex_b:
            if not bool(cb["is_yizi_dt"][k]):
                prev_dk = str(cb["dts"][k - 1])
                top_yz.update(env["lhb_buy_info"].get((prev_dk, c6), {}).get("top_yz", []))
                flags = get_day_risk_flags(c6, cb, pos, k, env, top_yz)
                cut_ret = (float(cb["open"][k]) * float(cb["adjf"][k])) / (bpx_raw * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
                hd_rows.append({"c6": c6, "buy_date": it["buy_date"], "score": it["score"], "k_rel": k - pos, "base_ret": base_ret, "cut_ret": cut_ret, **flags})
            k += 1
    hd_df = pd.DataFrame(hd_rows)
    hd_90 = hd_df[hd_df["score"] >= 90]
    f_cols = [c for c in hd_df.columns if c.startswith("f_")]
    uni_list = []
    for fc in f_cols:
        u90 = pfh.univariate_summary(hd_90, fc, "base_ret", "cut_ret")
        u75 = pfh.univariate_summary(hd_df, fc, "base_ret", "cut_ret")
        uni_list.append({"factor": fc, "is_std90_hold_days": u90, "is_wide75_hold_days": u75})

    print("=== Task 2 Univariate IS (k 09:25 cut vs baseline hold) ===")
    print(f"IS ZT-holding day-observations: std90={len(hd_90)}, wide75={len(hd_df)}")
    for x in uni_list:
        a, b = x["is_std90_hold_days"], x["is_wide75_hold_days"]
        print(f"  {x['factor']:22s} | std90: n={a['n_trig']:2d} base={a['base_mean_pct']:+5.2f}%->cut={a['alt_mean_pct']:+5.2f}% ({a['delta_bps']:+6.0f}bps) | wide75: n={b['n_trig']:3d} base={b['base_mean_pct']:+5.2f}%->cut={b['alt_mean_pct']:+5.2f}% ({b['delta_bps']:+6.0f}bps)")

    # 2. Composite dynamic variants on std90 & strict102
    items_90 = [it for it in items if it["score"] >= 90]

    def run_variant(kw):
        rows = []
        for it in items_90:
            ex_dt, spx, adjs, hb, shh = sim_3to4_dynamic(it["code"], it["cb"], it["pos"], it["bpx_raw"], b5m, env, **kw)
            nr = (spx * adjs) / (it["bpx_raw"] * float(it["cb"]["adjf"][it["pos"]])) * (1.0 - FEE) - 1.0
            rows.append({
                "code": it["code"], "name": it["name"], "buy_date": it["buy_date"],
                "buy_hhmm": it["buy_hhmm"], "buy_price": it["buy_price"],
                "exit_date": ex_dt, "exit_hhmm": shh, "exit_price": round(spx, 2),
                "hold_bars": hb, "net_ret": float(nr), "score": it["score"], "priority_score": it["priority_score"],
            })
        return pd.DataFrame(rows)

    df_b = run_variant({})
    assert np.max(np.abs(df_b["net_ret"].to_numpy() - np.array([it["ref_ret"] for it in items_90]))) < 1e-6

    configs = [
        ("baseline_v40", {}),
        # Broken-board conditional true-yang immunity
        ("r2_no_imm", dict(imm_mode="never")),
        ("r2_cond_v51_strict_imm", dict(imm_mode="cond_v51_strict")),
        ("r2_cond_v51_soft_imm", dict(imm_mode="cond_v51_soft")),
        # Direct 09:25 cut on nightly/morning dynamic risks
        ("r2_cut_lhasa_cnt3", dict(cut_0925_fn=lambda fl, kr: fl["f_lhb_lhasa_cnt3"])),
        ("r2_cut_lhasa_any", dict(cut_0925_fn=lambda fl, kr: fl["f_lhb_lhasa_any"])),
        ("r2_cut_surf_yz", dict(cut_0925_fn=lambda fl, kr: fl["f_lhb_surf_yz"])),
        ("r2_cut_reg_or_ex2", dict(cut_0925_fn=lambda fl, kr: fl["f_reg_or_ex2"])),
        ("r2_cut_top_yz_dump", dict(cut_0925_fn=lambda fl, kr: fl["f_lhb_top_yz_dump"])),
        ("r2_cut_peers_nuke", dict(cut_0925_fn=lambda fl, kr: fl["f_peers_nuke"])),
        ("r2_cut_risk2_score", dict(cut_0925_fn=lambda fl, kr: (int(fl["f_lhb_lhasa_any"]) + int(fl["f_lhb_surf_yz"]) + int(fl["f_reg_or_ex2"]) + int(fl["f_peers_nuke"]) + int(fl["f_lhb_inst_sell"]) + int(fl["f_lhb_top_yz_dump"])) >= 2)),
        # Conditional dynamic 96% double-deviation limit sell!
        ("r1_always_dev96_5b", dict(cond_dev_fn=lambda fl, cum, kr: 0.04)),
        ("r2_cond_dev96_reg_or_lhasa", dict(cond_dev_fn=lambda fl, cum, kr: 0.04 if cum else None)),
        ("r2_cond_dev96_reg_lhasa_xq", dict(cond_dev_fn=lambda fl, cum, kr: 0.04 if (cum or fl["f_xq_ov_8"] or fl["f_lhb_surf_yz"]) else None)),
        ("r2_cond_dev96_reg_only", dict(cond_dev_fn=lambda fl, cum, kr: 0.04 if fl["f_reg_or_ex2"] else None)),
        ("r2_cond_dev96_lhasa_or_surf", dict(cond_dev_fn=lambda fl, cum, kr: 0.04 if (fl["f_lhb_lhasa_any"] or fl["f_lhb_surf_yz"]) else None)),
        # Combined dynamic rules
        ("r2_combo_softimm_conddev96_reglh", dict(imm_mode="cond_v51_soft", cond_dev_fn=lambda fl, cum, kr: 0.04 if cum else None)),
        ("r2_combo_softimm_peers_regcut", dict(imm_mode="cond_v51_soft", cut_0925_fn=lambda fl, kr: bool(fl["f_reg_or_ex2"] or fl["f_peers_nuke"]))),
        ("r2_unsealed_refine_lhb_reg", dict(unsealed_refine="refine_lhb_reg")),
        ("r2_unsealed_refine_peers", dict(unsealed_refine="refine_peers_nuke")),
    ]

    comp_res = []
    for name, kw in configs:
        df_r = run_variant(kw)
        comp_res.append({
            "name": name,
            "std90": eval_d15_3to4(df_r),
            "strict102": eval_d15_3to4(df_r[df_r["score"] >= 102]),
        })

    out = {"univariate_is_tests": uni_list, "is_oos_full_comparison": comp_res}
    with open(f"{RD2_DIR}/round2_task2_3to4.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n=== Task 2 Composite Comparison (done in {time.time()-t0:.1f}s) ===")
    for e in comp_res:
        s90, s102 = e["std90"], e["strict102"]
        f5, is_, oo, y25, y26 = s90["full_5y"]["single_slot"], s90["is_22_23"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y25_26_reg"]["single_slot"], s90["y2026_1y"]["single_slot"]
        eq5 = s90["full_5y"]["daily_eq"]
        f5_s = s102["full_5y"]["single_slot"]
        print(f"  {e['name']:32s} | S90: 5Y={f5['nav']:7.2f}(WR={f5['wr_pct']:4.1f}%,T5={f5['trim5_nav']:6.2f}) IS={is_['nav']:5.2f} OOS={oo['nav']:6.2f} 25-26={y25['nav']:5.2f} 26={y26['nav']:4.2f} EQ={eq5['nav']:7.2f} | S102: 5Y={f5_s['nav']:5.2f}(OOS={s102['oos_24_26']['single_slot']['nav']:5.2f})")


if __name__ == "__main__":
    main()
