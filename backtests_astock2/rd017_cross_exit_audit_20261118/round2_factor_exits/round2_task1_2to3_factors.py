#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
round2_task1_2to3_factors.py — 第二轮任务一: 二进三 V2.0 (s_2to3) 动态持仓卖点因子实证
在 IS (2021~2023) 做单因子边际检验 (同时在 std90 与宽池 gated>=75 验证样本量与稳健性),
锁定极简整数对手盘风控打分卡, 在 OOS (2024~2026) 与 2026 做纯盲测 D15 双轨对比。
"""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD2_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118/round2_factor_exits"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, RD2_DIR)
sys.path.insert(0, UPG_DIR)

import pit_factor_helpers as pfh
import upgrade_2to3_pit as u2
import upgrade_3to4_pit as u3

FEE = u2.FEE_ROUNDTRIP
WINDOWS = [
    ("full_5y", "2021-11-16", "2026-11-16", pfh.csi_ret_pct("2021-11-16", "2026-11-16")),
    ("is_21_23_canon", "2021-11-16", "2023-12-31", pfh.csi_ret_pct("2021-11-16", "2023-12-31")),
    ("is_21_23_full", "2021-01-04", "2023-12-31", pfh.csi_ret_pct("2021-01-04", "2023-12-31")),
    ("oos_24_26", "2024-01-01", "2026-11-16", pfh.csi_ret_pct("2024-01-01", "2026-11-16")),
    ("y2026_1y", "2026-01-01", "2026-11-16", pfh.csi_ret_pct("2026-01-01", "2026-11-16")),
]


def build_3to4_lookup():
    res3 = u3.run_causal_pipeline("2026-11-16", verbose=False)
    cdf = res3["cand_df"]
    raw_sc = 78.0 + res3["comp_v40"].sum(axis=1)
    rc = res3["raw_core"]
    lkp = {}
    for i, r in enumerate(cdf.itertuples(index=False)):
        lkp[(str(r.code).zfill(6), str(r.buy_date))] = (float(raw_sc[i]), bool(rc[i]))
    return lkp


def compute_d4_factors(gated: pd.DataFrame, env: dict, plook: dict, all_dts: list, dt_idx: dict, lkp_34: dict) -> pd.DataFrame:
    """为每笔 2to3 交易预计算严格 PIT 的 D3盘后 + D4 09:25 全部动态因子与 D4 09:25 直接退场收益"""
    rows = []
    for r in gated.itertuples(index=False):
        c6 = str(r.code).zfill(6); bd = str(r.buy_date); d1_dt = str(r.d1_date)
        pos = dt_idx.get(bd, -1)
        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)
        b3 = plook.get((c6, bd))
        if pos < 0 or pos >= len(all_dts) - 1 or not b3:
            rows.append({"valid_d4": False, "d4_open_ret": float(r.ret_v2)})
            continue
        o3, h3, l3, c3, pc3, zt3, dt3, izt3, idt3, iyz3, iyzdt3 = b3

        # Next sellable D4
        k = pos + 1
        while k < len(all_dts) and plook.get((c6, all_dts[k]), (0,)*11)[10]:
            k += 1
        k = min(k, len(all_dts) - 1)
        d4 = all_dts[k]
        b4 = plook.get((c6, d4))
        if not b4 or b4[10]:
            rows.append({"valid_d4": False, "d4_open_ret": float(r.ret_v2)})
            continue
        o4 = b4[0]; pc4 = b4[4]
        d4_open_ret = (o4 / buy_px) * (1.0 - FEE) - 1.0
        d4_op = (o4 / pc4 - 1.0) if pc4 > 0 else 0.0

        # 1) 3to4 V4.0 counterparty score at D4 09:25
        sc34, skel34 = lkp_34.get((c6, d4), (-999.0, False))

        # 2) D3 LHB
        lb3 = env["lhb_buy_info"].get((bd, c6), {})
        d3_surf = bool(lb3.get("surf_yz", False))
        d3_lh_cnt = int(lb3.get("lh_cnt", 0))
        d3_lh_rat = float(lb3.get("lh_ratio", 0.0))

        # 3) D3 turnover & free-float turnover
        to3 = env["day_to_map"].get((bd, c6), (20.0,))[0]
        lock10 = float(r.lock_top10) if pd.notna(r.lock_top10) else 38.0
        real_to3 = to3 / max(0.05, 1.0 - lock10 / 100.0)

        # 4) Xueqiu overnight surge (bought as dark card xq_cnt_tot<4, then D3 15:00 ~ D4 09:25 surge)
        xq_overnight = pfh.count_ts_in_window(env["xq_arr"], c6, f"{bd} 15:00:00", f"{d4} 09:25:00")
        xq_pre_d4 = pfh.count_ts_in_window(env["xq_arr"], c6, f"{d1_dt} 00:00:00", f"{d4} 09:25:00")

        # 5) D4 09:25 peers & market open
        peers_op, peers_dt, _ = pfh.get_peers_0925(env, c6, bd, d4)
        ms4 = env["mkt_stats"].get(d4, {})
        mkt_p1b_op = float(ms4.get("mkt_prev_1b_open_avg", 0.0))
        mkt_pzt_op = float(ms4.get("mkt_prev_zt_open_avg", 0.0))

        # 6) D3 post-close ~ D4 09:25 regulatory / abnormal / tox notice
        reg_new = pfh.has_ts_in_window(env["reg_ts_map"], c6, f"{bd} 15:00:00", f"{d4} 09:25:00")
        abn_new = pfh.has_ts_in_window(env["abn_ts_map"], c6, f"{bd} 15:00:00", f"{d4} 09:25:00")
        tox_new = pfh.has_ts_in_window(env["tox_ts_map"], c6, f"{bd} 15:00:00", f"{d4} 09:25:00")
        d5_back = all_dts[max(0, pos - 4)]
        ex_r5 = pfh.ex_reg_cnt_5d(env, c6, bd, f"{d4} 09:25:00", d5_back)

        # 7) D3 rotten board
        tp3 = env["tape_map"].get((bd, c6))
        d3_fst, d3_obc, d3_sr = tp3 if tp3 else ("09:30:00", 0, np.nan)
        d3_rotten = bool(izt3 and ((d3_fst >= "14:00:00") or (d3_obc >= 3 and (not np.isnan(d3_sr)) and d3_sr < 0.015)))

        # 8) Unsealed D3 candle shape
        d3_tombstone = bool((not izt3) and ((c3 < o3 and (h3 - c3) / max(0.01, pc3) >= 0.04) or (c3 < buy_px * 0.97)))

        rows.append({
            "valid_d4": True, "d4": d4, "d4_k": k, "d4_op": d4_op, "d4_open_ret": d4_open_ret,
            "sc34": sc34, "skel34": skel34,
            "f_3to4_skel_veto": bool(izt3 and (not skel34)),
            "f_3to4_sc_lt85": bool(izt3 and ((not skel34) or sc34 < 85.0)),
            "f_3to4_sc_lt90": bool(izt3 and ((not skel34) or sc34 < 90.0)),
            "f_d3_surf_yz": d3_surf,
            "f_d3_lhasa": bool(d3_lh_cnt >= 3 or (d3_lh_rat >= 0.20 and lb3.get("tot_buy", 0) > 0)),
            "f_d3_to_gt31": bool(to3 > 31.0),
            "f_d3_realto_gt65": bool(real_to3 > 65.0),
            "f_xq_surge_4": bool(int(r.xq_cnt_tot) < 4 and xq_pre_d4 >= 4),
            "f_xq_overnight_3": bool(xq_overnight >= 3),
            "f_peers_nuke": bool(peers_op < -0.015 or mkt_p1b_op < 0.0),
            "f_peers_only_nuke": bool(peers_op < -0.015),
            "f_reg_bad": bool(reg_new or tox_new or ex_r5 >= 2),
            "f_reg_or_abn": bool(reg_new or tox_new or abn_new or ex_r5 >= 2),
            "f_d3_rotten": d3_rotten,
            "f_unsealed_tomb": d3_tombstone,
            "f_unsealed_bad_yz": bool(reg_new or tox_new or d3_surf or d3_lh_cnt >= 3),
            "f_unsealed_mkt_nuke": bool(mkt_pzt_op < 0.0 and d4_op < 0.0),
            "f_unsealed_toxic_2": bool((int(d3_tombstone) + int(reg_new or tox_new or d3_surf) + int(mkt_pzt_op < 0.0 and d4_op < 0.0)) >= 2),
        })
    return pd.concat([gated.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def sim_2to3_dynamic_exit(
    df: pd.DataFrame, env: dict, plook: dict, b5m: dict, all_dts: list, dt_idx: dict,
    d4_sealed_cut_fn=None,      # fn(row) -> bool (cut at D4 09:25 if sealed_3b)
    d4_sealed_tighten_fn=None,  # fn(row) -> bool (tighten D4 intraday to 10:30 VWAP / +3%)
    d4_unsealed_cut_fn=None,    # fn(row) -> bool (cut at D4 09:25 if ~sealed_3b)
    imm_mode: str = "always",   # "always" | "never" | "cond_v51"
    nightly_relay_cut: bool = False,  # also cut at k>=pos+2 09:25 if reg/lhasa>=3/surf_yz/peers_nuke
) -> tuple[list, list, list]:
    rets, eds, ehs = [], [], []
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        pos = dt_idx.get(bd, -1)
        if pos < 0 or pos >= len(all_dts) - 1 or not plook.get((c6, bd)):
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)
        b3 = plook[(c6, bd)]

        def run_zt_hold(sp_idx: int):
            k = sp_idx + 1
            used_imm = False
            while k < len(all_dts) and (k - pos <= 18):
                dk = all_dts[k]
                bk = plook.get((c6, dk))
                if not bk:
                    k += 1; continue
                ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = bk
                if iyzdtk:
                    k += 1; continue
                if k > sp_idx + 1:
                    pb = plook.get((c6, all_dts[k - 1]))
                    if pb and (pb[10] or pb[8]):
                        return (ok / buy_px) * (1.0 - FEE) - 1.0, dk, 925

                if k == pos + 1:
                    d4_op = ok / pck - 1.0 if pck > 0 else 0.0
                    if (d4_op > 0.092) and (ok < ztk - 0.005):
                        return (ok / buy_px) * (1.0 - FEE) - 1.0, dk, 925
                    if d4_sealed_cut_fn is not None and d4_sealed_cut_fn(r) and ok > dtk + 0.005:
                        return (ok / buy_px) * (1.0 - FEE) - 1.0, dk, 925

                if nightly_relay_cut and k >= sp_idx + 2:
                    prev_dk = all_dts[k - 1]
                    lbp = env["lhb_buy_info"].get((prev_dk, c6), {})
                    reg_k = pfh.has_ts_in_window(env["reg_ts_map"], c6, f"{prev_dk} 15:00:00", f"{dk} 09:25:00")
                    if (lbp.get("lh_cnt", 0) >= 3 or lbp.get("surf_yz", False) or reg_k) and ok > dtk + 0.005:
                        return (ok / buy_px) * (1.0 - FEE) - 1.0, dk, 925

                tighten_today = bool(k == pos + 1 and d4_sealed_tighten_fn is not None and d4_sealed_tighten_fn(r))
                arr = b5m.get((c6, dk))
                if arr is not None and len(arr) > 0:
                    if tighten_today and len(arr) >= 12:
                        cum_v = cum_a = 0.0
                        for bi in range(len(arr)):
                            hh, bo, bh, bl, bc, bv, ba = int(arr[bi, 0]), arr[bi, 1], arr[bi, 2], arr[bi, 3], arr[bi, 4], arr[bi, 5], arr[bi, 6]
                            cum_v += bv; cum_a += ba
                            if hh == 1030 and bc < ztk - 0.01:
                                vwap = cum_a / cum_v if cum_v > 0 else bc
                                if bc < vwap:
                                    px = float(arr[bi + 1, 1]) if bi + 1 < len(arr) else float(bc)
                                    if px > dtk + 0.005:
                                        return (px / buy_px) * (1.0 - FEE) - 1.0, dk, int(arr[bi + 1, 0]) if bi + 1 < len(arr) else 1030
                    pk = ok
                    for row5 in arr:
                        hh, bo, bh, bl, bc = int(row5[0]), row5[1], row5[2], row5[3], row5[4]
                        if bh <= dtk + 0.005:
                            continue
                        if hh >= 1345 and pk >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                            px = min(bo, pck * 1.050)
                            if px > dtk + 0.005:
                                return (px / buy_px) * (1.0 - FEE) - 1.0, dk, hh
                        if bh > pk:
                            pk = bh
                if iztk:
                    k += 1; continue
                if idtk:
                    k += 1; continue

                # Broken board at 14:55/15:00: check true-yang immunity
                is_true_yang = (ck > ok) and (ck >= pck)
                allow_imm = False
                if is_true_yang and (not used_imm):
                    if imm_mode == "always":
                        allow_imm = True
                    elif imm_mode == "never":
                        allow_imm = False
                    elif imm_mode == "cond_v51":
                        prev_dk = all_dts[k - 1]
                        ms = env["mkt_stats"].get(dk, {})
                        brk_r10 = float(ms.get("brk_r10_prev", 0.0))
                        csi5 = float(env["csi_5d_prev"].get(dk, 0.0))
                        to_k = env["day_to_map"].get((dk, c6), (20.0,))[0]
                        lbp = env["lhb_buy_info"].get((prev_dk, c6), {})
                        d10_back = all_dts[max(0, k - 10)]
                        has_reg = pfh.has_ts_in_window(env["reg_ts_map"], c6, f"{d10_back} 00:00:00", f"{dk} 14:55:00")
                        not_tombstone = (hk - ck) < (ck - ok) * 1.5
                        if (brk_r10 >= 0.20) and (csi5 > -0.020) and (to_k <= 35.0) and not_tombstone and (not has_reg) and (lbp.get("lh_cnt", 0) < 3):
                            allow_imm = True
                if allow_imm:
                    used_imm = True; k += 1; continue
                return (ck / buy_px) * (1.0 - FEE) - 1.0, dk, 1500
            return float(r.ret_opn_cc), str(r.exit_dt_cc), int(r.exit_hh_cc)

        if b3[7]:
            rv, edv, ehv = run_zt_hold(pos)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
            continue

        # Unsealed D3
        k = pos + 1
        while k < len(all_dts):
            bk = plook.get((c6, all_dts[k]))
            if bk and not bk[10]:
                break
            k += 1
        if k >= len(all_dts):
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        dk = all_dts[k]
        ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = plook[(c6, dk)]
        if k > pos + 1:
            rets.append((ok / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(925)
        elif d4_unsealed_cut_fn is not None and d4_unsealed_cut_fn(r) and ok > dtk + 0.005:
            rets.append((ok / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(925)
        elif iztk:
            rv, edv, ehv = run_zt_hold(k)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
        elif idtk:
            m = k + 1; sold = False
            while m < len(all_dts):
                bm = plook.get((c6, all_dts[m]))
                if bm and not bm[10]:
                    rets.append((bm[0] / buy_px) * (1.0 - FEE) - 1.0); eds.append(all_dts[m]); ehs.append(925)
                    sold = True; break
                m += 1
            if not sold:
                rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
        else:
            rets.append((ck / buy_px) * (1.0 - FEE) - 1.0); eds.append(dk); ehs.append(1500)

    return rets, eds, ehs


def eval_d15_2to3(df: pd.DataFrame, th: int, rcol: str, ecol: str, hcol: str) -> dict:
    sub_all = df[df["score_v2"] >= th].copy()
    sub_5y = sub_all[sub_all["buy_date"] >= u2.CANON_5Y_START].copy()
    led_5y = u2.sim_single_slot(sub_5y, "score_v2", rcol, ecol, hcol)
    led_full = u2.sim_single_slot(sub_all, "score_v2", rcol, ecol, hcol)
    res = {}
    for wn, sdt, edt, csip in WINDOWS:
        sa = sub_all[(sub_all["buy_date"] >= sdt) & (sub_all["buy_date"] <= edt)]
        ws = (led_full if wn == "is_21_23_full" else led_5y)
        ws = ws[(ws["buy_date"] >= sdt) & (ws["buy_date"] <= edt)]
        rr = ws["net_ret"].to_numpy(dtype=float) if not ws.empty else np.array([], dtype=float)
        dq = sa.groupby("buy_date")[rcol].mean().sort_index().to_numpy(dtype=float) if not sa.empty else np.array([], dtype=float)
        res[wn] = {
            "single_slot": pfh.calc_arr_metrics(rr, csip),
            "daily_eq": {**pfh.calc_arr_metrics(dq, csip), "raw_n": int(len(sa))},
        }
    return res


def main():
    t0 = time.time()
    with open(f"{RD2_DIR}/pit_exit_env.pkl", "rb") as f:
        env = pickle.load(f)
    raw_all, df_all, gated, asof = u2.build_pit_dataset("2026-11-16")
    gated["score_v2"] = 60.0 + u2.compute_v20_components(gated).sum(axis=1)
    da, b5m = u2.load_daily_and_5m("2026-11-16")
    all_dts = sorted(da["dt"].unique()); dt_idx = {d: i for i, d in enumerate(all_dts)}
    plook = {
        (r.c6, r.dt): (
            float(r.open), float(r.high), float(r.low), float(r.close),
            float(r.pre_c) if pd.notna(r.pre_c) else float(r.close),
            float(r.zt_px) if pd.notna(r.zt_px) else 9999.0,
            float(r.dt_px) if pd.notna(r.dt_px) else 0.0,
            bool(r.is_zt), bool(r.is_dt_exact), bool(r.is_yizi), bool(r.is_yizi_dt),
        )
        for r in da[da["dt"] >= "2020-12-25"][
            ["c6", "dt", "open", "high", "low", "close", "pre_c", "zt_px", "dt_px", "is_zt", "is_dt_exact", "is_yizi", "is_yizi_dt"]
        ].itertuples(index=False)
    }

    lkp_34 = build_3to4_lookup()
    df_f = compute_d4_factors(gated, env, plook, all_dts, dt_idx, lkp_34)

    # Verify baseline & no_imm
    rb, edb, ehb = sim_2to3_dynamic_exit(df_f, env, plook, b5m, all_dts, dt_idx, imm_mode="always")
    assert np.max(np.abs(np.array(rb) - df_f["ret_v2"].to_numpy())) < 1e-12
    df_f["ret_base"] = rb
    rn, edn, ehn = sim_2to3_dynamic_exit(df_f, env, plook, b5m, all_dts, dt_idx, imm_mode="never")
    df_f["ret_noimm"] = rn

    # Univariate IS Tests (2021-01-04 ~ 2023-12-31) on both std90 & wider gated>=75
    is_90_sealed = df_f[(df_f["buy_date"] <= "2023-12-31") & (df_f["score_v2"] >= 90) & df_f["sealed_3b"] & df_f["valid_d4"]].copy()
    is_75_sealed = df_f[(df_f["buy_date"] <= "2023-12-31") & (df_f["score_v2"] >= 75) & df_f["sealed_3b"] & df_f["valid_d4"]].copy()
    is_90_unseal = df_f[(df_f["buy_date"] <= "2023-12-31") & (df_f["score_v2"] >= 90) & (~df_f["sealed_3b"]) & df_f["valid_d4"]].copy()
    is_75_unseal = df_f[(df_f["buy_date"] <= "2023-12-31") & (df_f["score_v2"] >= 75) & (~df_f["sealed_3b"]) & df_f["valid_d4"]].copy()

    sealed_factors = [
        "f_3to4_skel_veto", "f_3to4_sc_lt85", "f_3to4_sc_lt90",
        "f_d3_surf_yz", "f_d3_lhasa", "f_d3_to_gt31", "f_d3_realto_gt65",
        "f_xq_surge_4", "f_xq_overnight_3", "f_peers_nuke", "f_peers_only_nuke",
        "f_reg_bad", "f_reg_or_abn", "f_d3_rotten",
    ]
    unsealed_factors = ["f_unsealed_tomb", "f_unsealed_bad_yz", "f_unsealed_mkt_nuke", "f_unsealed_toxic_2", "f_peers_nuke", "f_reg_bad"]

    uni_results = {"sealed_3b_d4_open_cut": [], "unsealed_3b_d4_open_cut": []}
    for fc in sealed_factors:
        u90 = pfh.univariate_summary(is_90_sealed, fc, "ret_noimm", "d4_open_ret")
        u75 = pfh.univariate_summary(is_75_sealed, fc, "ret_noimm", "d4_open_ret")
        uni_results["sealed_3b_d4_open_cut"].append({"factor": fc, "is_std90": u90, "is_wide75": u75})
    for fc in unsealed_factors:
        u90 = pfh.univariate_summary(is_90_unseal, fc, "ret_noimm", "d4_open_ret")
        u75 = pfh.univariate_summary(is_75_unseal, fc, "ret_noimm", "d4_open_ret")
        uni_results["unsealed_3b_d4_open_cut"].append({"factor": fc, "is_std90": u90, "is_wide75": u75})

    print("=== Task 1 Univariate IS (D4 09:25 cut vs ret_noimm) ===")
    print("-- Sealed 3B (IS std90 N=", len(is_90_sealed), ", IS wide75 N=", len(is_75_sealed), ") --")
    for x in uni_results["sealed_3b_d4_open_cut"]:
        a, b = x["is_std90"], x["is_wide75"]
        print(f"  {x['factor']:22s} | std90: n={a['n_trig']:2d} base={a['base_mean_pct']:+5.2f}%->cut={a['alt_mean_pct']:+5.2f}% ({a['delta_bps']:+6.0f}bps) | wide75: n={b['n_trig']:3d} base={b['base_mean_pct']:+5.2f}%->cut={b['alt_mean_pct']:+5.2f}% ({b['delta_bps']:+6.0f}bps)")
    print("-- Unsealed 3B (IS std90 N=", len(is_90_unseal), ", IS wide75 N=", len(is_75_unseal), ") --")
    for x in uni_results["unsealed_3b_d4_open_cut"]:
        a, b = x["is_std90"], x["is_wide75"]
        print(f"  {x['factor']:22s} | std90: n={a['n_trig']:2d} base={a['base_mean_pct']:+5.2f}%->cut={a['alt_mean_pct']:+5.2f}% ({a['delta_bps']:+6.0f}bps) | wide75: n={b['n_trig']:3d} base={b['base_mean_pct']:+5.2f}%->cut={b['alt_mean_pct']:+5.2f}% ({b['delta_bps']:+6.0f}bps)")

    # Composite dynamic rules & conditional immunity comparisons (locked on IS, evaluated IS/OOS/5Y/2026)
    configs = [
        ("baseline_v20", dict(imm_mode="always")),
        ("r1_no_imm", dict(imm_mode="never")),
        ("r2_cond_v51_imm", dict(imm_mode="cond_v51")),
        # Dynamic D4 counterparty / risk rules on top of r1_no_imm
        ("r2_noimm_d4cut_surf_lhasa", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.f_d3_surf_yz or row.f_d3_lhasa))),
        ("r2_noimm_d4cut_reg_or_lhasa", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.f_reg_bad or row.f_d3_lhasa or row.f_d3_surf_yz))),
        ("r2_noimm_d4cut_3to4_lt85", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.f_3to4_sc_lt85))),
        ("r2_noimm_d4cut_peers_nuke", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.f_peers_nuke))),
        ("r2_noimm_d4cut_rotten", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.f_d3_rotten))),
        ("r2_noimm_d4cut_risk2", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: (int(row.f_d3_surf_yz) + int(row.f_d3_lhasa) + int(row.f_reg_bad) + int(row.f_peers_only_nuke) + int(row.f_d3_rotten) + int(row.f_xq_surge_4)) >= 2)),
        ("r2_noimm_d4tighten_risk1", dict(imm_mode="never", d4_sealed_tighten_fn=lambda row: bool(row.f_d3_surf_yz or row.f_d3_lhasa or row.f_reg_bad or row.f_peers_only_nuke or row.f_d3_rotten))),
        ("r2_noimm_unsealed_toxic2", dict(imm_mode="never", d4_unsealed_cut_fn=lambda row: bool(row.f_unsealed_toxic_2))),
        ("r2_noimm_unsealed_tomb", dict(imm_mode="never", d4_unsealed_cut_fn=lambda row: bool(row.f_unsealed_tomb))),
        ("r2_noimm_unsealed_mktnuke", dict(imm_mode="never", d4_unsealed_cut_fn=lambda row: bool(row.f_unsealed_mkt_nuke))),
        ("r2_noimm_nightly_relay_cut", dict(imm_mode="never", nightly_relay_cut=True)),
        ("r2_condimm_plus_d4_nightly", dict(imm_mode="cond_v51", d4_sealed_cut_fn=lambda row: bool(row.f_reg_bad or row.f_d3_lhasa or row.f_d3_surf_yz), nightly_relay_cut=True)),
    ]

    comp_res = []
    for name, kw in configs:
        rv, edv, ehv = sim_2to3_dynamic_exit(df_f, env, plook, b5m, all_dts, dt_idx, **kw)
        df_f["rt"], df_f["et"], df_f["ht"] = rv, edv, ehv
        comp_res.append({
            "name": name,
            "std90": eval_d15_2to3(df_f, 90, "rt", "et", "ht"),
            "strict96": eval_d15_2to3(df_f, 96, "rt", "et", "ht"),
        })

    out = {"univariate_is_tests": uni_results, "is_oos_full_comparison": comp_res}
    with open(f"{RD2_DIR}/round2_task1_2to3.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n=== Task 1 Composite Comparison (done in {time.time()-t0:.1f}s) ===")
    for e in comp_res:
        s90, s96 = e["std90"], e["strict96"]
        f5, isc, isf, oo, y26 = s90["full_5y"]["single_slot"], s90["is_21_23_canon"]["single_slot"], s90["is_21_23_full"]["single_slot"], s90["oos_24_26"]["single_slot"], s90["y2026_1y"]["single_slot"]
        eq5 = s90["full_5y"]["daily_eq"]
        print(f"  {e['name']:28s} | S90: 5Y={f5['nav']:6.2f}(WR={f5['wr_pct']:4.1f}%,T3={f5['trim3_nav']:5.2f},MDD={f5['mdd_pct']:4.1f}%) ISc={isc['nav']:5.2f} ISf={isf['nav']:5.2f} OOS={oo['nav']:5.2f} 26={y26['nav']:4.2f} EQ={eq5['nav']:6.2f} | S96: 5Y={s96['full_5y']['single_slot']['nav']:5.2f}(ISf={s96['is_21_23_full']['single_slot']['nav']:4.2f},OOS={s96['oos_24_26']['single_slot']['nav']:4.2f})")


if __name__ == "__main__":
    main()
