#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
round2_scorecard_refine.py — 第二轮补充精细实证:
1) s_2to3: D3高换手/破3进4微收紧(10:30 VWAP & 13:45护利) + 断板真阳免死单因子IS表;
2) s_3to4: 条件96%异动单(dev96)的IS单因子表 + 断板免死的IS单因子表 + 极简整数风控分(risk>=2)与S102分档盲测;
3) s_pry: 有样本量的市场冰点(dt>=15/p1b<-0.5%)/真分歧拆解(弱转弱cut vs 弱转强extend)/T0龙虎榜净买/首板弱转二无免死.
"""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD2_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118/round2_factor_exits"
RD1_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
P5_DIR = f"{SIM}/backtests_astock2/p5_full_pry_universe"
GFM_DIR = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
for p in [RD2_DIR, RD1_DIR, UPG_DIR]:
    sys.path.insert(0, p)

import pit_factor_helpers as pfh
import upgrade_2to3_pit as u2
import upgrade_3to4_pit as u3
import task3_3to4_exit_audit as t3
import round2_task1_2to3_factors as r2t1
import round2_task2_3to4_factors as r2t2
import round2_task3_pry_factors as r2t3

FEE = 0.0020


def audit_2to3_refine(env: dict) -> dict:
    _, _, gated, _ = u2.build_pit_dataset("2026-11-16")
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
    lkp34 = r2t1.build_3to4_lookup()
    df_f = r2t1.compute_d4_factors(gated, env, plook, all_dts, dt_idx, lkp34)

    # 1. Broken-board true-yang immunity univariate IS test (all vs never)
    rb_all, _, _ = r2t1.sim_2to3_dynamic_exit(df_f, env, plook, b5m, all_dts, dt_idx, imm_mode="always")
    rn_all, _, _ = r2t1.sim_2to3_dynamic_exit(df_f, env, plook, b5m, all_dts, dt_idx, imm_mode="never")
    rc_all, _, _ = r2t1.sim_2to3_dynamic_exit(df_f, env, plook, b5m, all_dts, dt_idx, imm_mode="cond_v51")
    df_f["rb"], df_f["rn"], df_f["rc"] = rb_all, rn_all, rc_all
    df_f["is_diff_imm"] = np.abs(df_f["rb"] - df_f["rn"]) > 1e-6

    is90 = df_f[(df_f["buy_date"] <= "2023-12-31") & (df_f["score_v2"] >= 90)]
    is75 = df_f[(df_f["buy_date"] <= "2023-12-31") & (df_f["score_v2"] >= 75)]
    uni_imm = {
        "cancel_imm_std90_IS": pfh.univariate_summary(is90, "is_diff_imm", "rb", "rn"),
        "cancel_imm_wide75_IS": pfh.univariate_summary(is75, "is_diff_imm", "rb", "rn"),
        "cond_v51_imm_std90_IS": pfh.univariate_summary(is90, "is_diff_imm", "rb", "rc"),
        "cond_v51_imm_wide75_IS": pfh.univariate_summary(is75, "is_diff_imm", "rb", "rc"),
    }

    # 2. Refined composite variants:
    # - r1_no_imm + d4_cut_to_gt31
    # - r1_no_imm + d4_tighten_3to4_lt85 (only tighten D4 intraday 10:30 VWAP on weak 3to4 score)
    # - r1_no_imm + d4_risk2_tighten (intraday tighten when >=2 risk signals)
    # - r1_no_imm + d4_sealed_op_lt_neg2_cut (gap down <-2% on D4 open after sealing 3B)
    configs = [
        ("r1_no_imm", dict(imm_mode="never")),
        ("r2_noimm_d4cut_to_gt31", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.f_d3_to_gt31))),
        ("r2_noimm_d4tighten_3to4_lt85", dict(imm_mode="never", d4_sealed_tighten_fn=lambda row: bool(row.f_3to4_sc_lt85))),
        ("r2_noimm_d4cut_op_neg2", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.d4_op < -0.02))),
        ("r2_noimm_d4cut_to31_or_opneg2", dict(imm_mode="never", d4_sealed_cut_fn=lambda row: bool(row.f_d3_to_gt31 or row.d4_op < -0.02))),
    ]
    comp = []
    for nm, kw in configs:
        rv, edv, ehv = r2t1.sim_2to3_dynamic_exit(df_f, env, plook, b5m, all_dts, dt_idx, **kw)
        df_f["rt"], df_f["et"], df_f["ht"] = rv, edv, ehv
        comp.append({"name": nm, "std90": r2t1.eval_d15_2to3(df_f, 90, "rt", "et", "ht"), "strict96": r2t1.eval_d15_2to3(df_f, 96, "rt", "et", "ht")})
    return {"uni_imm": uni_imm, "comp": comp}


def audit_3to4_refine(env: dict) -> dict:
    res = u3.run_causal_pipeline("2026-11-16", verbose=False)
    cand_df, sc_v40, code_bars, p_1030 = res["cand_df"], res["sc_v40"], res["code_bars"], res["p_1030"]
    b5m, _ = t3.load_5m_and_extra(cand_df, code_bars)
    raw_sc = 78.0 + res["comp_v40"].sum(axis=1)
    eligible = [i for i in np.where(res["skel"] & (raw_sc >= 75.0))[0] if p_1030[i] is not None]
    items = []
    for i in eligible:
        pi = p_1030[i]; r = cand_df.iloc[i]; c6 = str(r["code"]).zfill(6); bd = str(r["buy_date"])
        cb = code_bars[c6]; pos = cb["date_to_pos"][bd]
        bpx_raw, _ = u3._sim_buy_5m(c6, bd, cb, pos, b5m, 1030)
        items.append({
            "code": c6, "name": str(r["name"]), "buy_date": bd,
            "buy_hhmm": int(pi["buy_hhmm"]), "buy_price": float(pi["buy_price"]),
            "bpx_raw": float(bpx_raw), "pos": pos, "cb": cb,
            "score": int(round(float(raw_sc[i]))),
            "priority_score": float(sc_v40[i]) * 10.0 + float(r["prio_3to4"]) * 0.1,
        })

    # 1. Univariate IS test for conditional dev96 (trade-level IS on wide75 & std90!)
    # AND broken-board immunity (always vs never vs cond_v51_soft) on wide75 & std90!
    def run_set(its, kw):
        out = []
        for it in its:
            ex, spx, adjs, hb, shh = r2t2.sim_3to4_dynamic(it["code"], it["cb"], it["pos"], it["bpx_raw"], b5m, env, **kw)
            nr = (spx * adjs) / (it["bpx_raw"] * float(it["cb"]["adjf"][it["pos"]])) * (1.0 - FEE) - 1.0
            out.append({
                "code": it["code"], "name": it["name"], "buy_date": it["buy_date"],
                "buy_hhmm": it["buy_hhmm"], "buy_price": it["buy_price"],
                "exit_date": ex, "exit_hhmm": shh, "exit_price": round(spx, 2),
                "hold_bars": hb, "net_ret": float(nr), "score": it["score"], "priority_score": it["priority_score"],
            })
        return pd.DataFrame(out)

    items_is = [it for it in items if it["buy_date"] <= "2023-12-31"]
    db_is = run_set(items_is, {})

    def risk2_cond(fl, cum, kr):
        # Integer risk score >= 2 (independent signals, avoiding single ex_reg false alarm!)
        pts = (
            int(fl["f_reg_new"]) * 2  # hard stock reg/tox immediately qualifies
            + int(fl["f_reg_or_ex2"] and (not fl["f_reg_new"]))
            + int(fl["f_lhb_lhasa_any"])
            + int(fl["f_lhb_surf_yz"])
            + int(fl["f_lhb_top_yz_dump"])
            + int(fl["f_xq_ov_4"])
        )
        return 0.04 if pts >= 2 else None

    def sreg_only_cond(fl, cum, kr):
        # Only stock-specific regulatory/tox notice (not routine exchange 3-day abnormal volatility)
        return 0.04 if fl["f_reg_new"] else None

    def dev96_k6_cond(fl, cum, kr):
        # Only apply 96% double-dev limit sell when kr >= 2 (i.e. 6B+!) and cum/reg_or_lhasa/xq/surf
        if kr < 2:
            return None
        return 0.04 if (cum or fl["f_xq_ov_8"] or fl["f_lhb_surf_yz"]) else None

    uni_is_dev_imm = {}
    for lbl, kw in [
        ("dev96_always", dict(cond_dev_fn=lambda fl, cum, kr: 0.04)),
        ("dev96_reg_or_lhasa_cum", dict(cond_dev_fn=lambda fl, cum, kr: 0.04 if cum else None)),
        ("dev96_reg_lhasa_xq", dict(cond_dev_fn=lambda fl, cum, kr: 0.04 if (cum or fl["f_xq_ov_8"] or fl["f_lhb_surf_yz"]) else None)),
        ("dev96_risk2_score", dict(cond_dev_fn=risk2_cond)),
        ("dev96_sreg_only", dict(cond_dev_fn=sreg_only_cond)),
        ("dev96_k6_reg_lh_xq", dict(cond_dev_fn=dev96_k6_cond)),
        ("imm_never", dict(imm_mode="never")),
        ("imm_cond_v51_soft", dict(imm_mode="cond_v51_soft")),
    ]:
        da_is = run_set(items_is, kw)
        m = db_is.merge(da_is, on=["code", "buy_date", "name", "score"], suffixes=("_b", "_a"))
        m["trig"] = np.abs(m["net_ret_b"] - m["net_ret_a"]) > 1e-6
        m90 = m[m["score"] >= 90]
        uni_is_dev_imm[lbl] = {
            "is_std90": pfh.univariate_summary(m90, "trig", "net_ret_b", "net_ret_a"),
            "is_wide75": pfh.univariate_summary(m, "trig", "net_ret_b", "net_ret_a"),
        }

    # 2. Full IS/OOS evaluation on std90 & strict102 for IS-locked candidates
    items_90 = [it for it in items if it["score"] >= 90]
    comp = []
    for lbl, kw in [
        ("r2_cond_dev96_risk2", dict(cond_dev_fn=risk2_cond)),
        ("r2_cond_dev96_sreg_only", dict(cond_dev_fn=sreg_only_cond)),
        ("r2_cond_dev96_k6_reglhxq", dict(cond_dev_fn=dev96_k6_cond)),
        ("r2_cond_dev96_reglhxq_non102", dict(cond_dev_fn=lambda fl, cum, kr: None)),  # computed via score filter below
    ]:
        if lbl == "r2_cond_dev96_reglhxq_non102":
            # Score-tiered rule: sc>=102 holds pure V4.0, 90<=sc<102 uses cond_dev96(reglhxq)
            rows = []
            for it in items_90:
                use_kw = {} if it["score"] >= 102 else dict(cond_dev_fn=lambda fl, cum, kr: 0.04 if (cum or fl["f_xq_ov_8"] or fl["f_lhb_surf_yz"]) else None)
                ex, spx, adjs, hb, shh = r2t2.sim_3to4_dynamic(it["code"], it["cb"], it["pos"], it["bpx_raw"], b5m, env, **use_kw)
                nr = (spx * adjs) / (it["bpx_raw"] * float(it["cb"]["adjf"][it["pos"]])) * (1.0 - FEE) - 1.0
                rows.append({"code": it["code"], "name": it["name"], "buy_date": it["buy_date"], "buy_hhmm": it["buy_hhmm"], "buy_price": it["buy_price"], "exit_date": ex, "exit_hhmm": shh, "exit_price": round(spx, 2), "hold_bars": hb, "net_ret": float(nr), "score": it["score"], "priority_score": it["priority_score"]})
            dfr = pd.DataFrame(rows)
        else:
            dfr = run_set(items_90, kw)
        comp.append({"name": lbl, "std90": r2t2.eval_d15_3to4(dfr), "strict102": r2t2.eval_d15_3to4(dfr[dfr["score"] >= 102])})
    return {"uni_is_dev_imm": uni_is_dev_imm, "comp": comp}


def audit_pry_refine(env: dict) -> dict:
    with open(f"{GFM_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]
    df_m = pd.read_parquet(f"{P5_DIR}/full_pry_master_enriched.parquet")
    v1 = pd.read_csv(f"{P5_DIR}/v1_oversold_pry_165_strict_ledger.csv"); v1["c6"] = v1["code"].astype(str).str.zfill(6)
    m435 = v1.merge(df_m[["c6", "dt_str", "prev_ret10"]], left_on=["c6", "buy_date"], right_on=["c6", "dt_str"], how="left")
    m435["p0"] = [cb[r.c6]["date_to_pos"][r.buy_date] for r in m435.itertuples(index=False)]

    non_st = (~df_m["is_st_or_delist"].values) & (df_m["pre_c"].values >= 2.0)
    no_poison = (~df_m["n_poison90"].fillna(False).values) & (~df_m["n_del90"].fillna(False).values) & (~df_m["n_inv90"].fillna(False).values)
    ptdt = df_m["prev_touch_dt"].fillna(False).values.astype(bool)
    pisdt = df_m["prev_is_dt"].fillna(True).values.astype(bool)
    pure_os = (df_m["prev_zt20"].fillna(0).values == 0) & (df_m["prev_c_ma20"].fillna(0).values <= -0.15) & (df_m["prev_dd20"].fillna(1.0).values <= 0.80)
    w2s = (df_m["o_pct"].values >= 0.0) & (df_m["o_pct"].values <= 0.05)
    m830 = df_m[non_st & no_poison & ptdt & (~pisdt) & pure_os & w2s].copy()
    m830["buy_date"] = m830["dt_str"].astype(str); m830["score"] = 100; m830["bias10"] = m830["prev_c_ma20"].fillna(0)
    p0s, keep = [], []
    for r in m830.itertuples(index=False):
        d = cb.get(r.c6); p = d["date_to_pos"].get(r.buy_date) if d else None
        if p is not None and p + 1 < len(d["dts"]): p0s.append(p); keep.append(True)
        else: keep.append(False)
    m830 = m830[keep].copy(); m830["p0"] = p0s

    def sim_pry_ext(c6, d, p0, base_hold=3, t1_cut=-0.02, yang_imm=True, mkt_weak_cut=False, dt15_cut=False, div_cut_only=False, div_ext_p1b_neg05=False, zt_weak_noimm=False, zt_nx_neg_cut=False, lhb_good_ext=False):
        L = len(d["dts"])
        o, c, dt_px, zt_px, is_zt, is_yz_dt, dts = d["open"], d["close"], d["dt_px"], d["zt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"]
        buy_px = float(o[p0])
        if bool(c[p0] <= dt_px[p0] + 0.001):
            ps = r2t3.first_sellable(d, p0 + 1)
            spx = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
            return float(spx / buy_px * (1.0 - FEE) - 1.0), str(dts[ps])

        def hold_zt(pk):
            kn = r2t3.first_sellable(d, pk + 1)
            if kn > pk + 1:
                spx = o[kn] if o[kn] > dt_px[kn] + 0.005 else c[kn]
                return float(spx / buy_px * (1.0 - FEE) - 1.0), str(dts[kn])
            strong, meta = r2t3.is_zt_strong_1to2(c6, d, pk, kn, env)
            is_yz_nx = bool(o[kn] >= zt_px[kn] - 0.005)
            if zt_nx_neg_cut and (not is_yz_nx) and meta["nx_op"] < 0.0:
                return float(o[kn] / buy_px * (1.0 - FEE) - 1.0), str(dts[kn])
            use_imm = yang_imm and ((not zt_weak_noimm) or strong)
            imm = False; cur = pk
            while cur < L - 1:
                nxt = cur + 1
                if is_yz_dt[nxt]:
                    nx2 = r2t3.first_sellable(d, nxt)
                    spx = o[nx2] if o[nx2] > dt_px[nx2] + 0.005 else c[nx2]
                    return float(spx / buy_px * (1.0 - FEE) - 1.0), str(dts[nx2])
                if is_zt[nxt]: cur = nxt; continue
                if use_imm and (not imm) and (c[nxt] > o[nxt]) and (c[nxt] >= c[cur] * 0.97):
                    imm = True; cur = nxt; continue
                return float(c[nxt] / buy_px * (1.0 - FEE) - 1.0), str(dts[nxt])
            return float(c[cur] / buy_px * (1.0 - FEE) - 1.0), str(dts[cur])

        if is_zt[p0]:
            return hold_zt(p0)

        dt0 = str(dts[p0])
        lb0 = env["lhb_buy_info"].get((dt0, c6), {}); ls0 = env["lhb_sell_info"].get((dt0, c6), {})
        max_h = 4 if (lhb_good_ext and ((lb0.get("inst_buy", 0) > ls0.get("inst_sell", 0) and lb0.get("inst_buy", 0) >= 5e6) or len(lb0.get("top_yz", [])) > 0)) else base_hold
        end_p = min(L - 1, p0 + max_h)
        k = p0 + 1
        while k <= end_p:
            if is_yz_dt[k]: k += 1; continue
            dk = str(dts[k]); ok = float(o[k])
            ms = env["mkt_stats"].get(dk, {})
            mkt_p1b = float(ms.get("mkt_prev_1b_open_avg", 0.0))
            dt_cnt = int(ms.get("mkt_0925_dt_cnt", 0))
            op_k = (ok / float(c[k - 1]) - 1.0) if c[k - 1] > 0 else 0.0
            if mkt_weak_cut and mkt_p1b < -0.005 and op_k < 0.0:
                return float(ok / buy_px * (1.0 - FEE) - 1.0), dk
            if dt15_cut and dt_cnt >= 15 and op_k < 0.0:
                return float(ok / buy_px * (1.0 - FEE) - 1.0), dk
            if k == p0 + 1:
                if div_cut_only and mkt_p1b >= 0.0 and op_k < -0.015:
                    return float(ok / buy_px * (1.0 - FEE) - 1.0), dk
                if div_ext_p1b_neg05 and mkt_p1b < -0.004 and op_k >= 0.010:
                    end_p = min(L - 1, p0 + 4)
                if t1_cut is not None and op_k < t1_cut:
                    return float(ok / buy_px * (1.0 - FEE) - 1.0), dk
            if is_zt[k]:
                return hold_zt(k)
            k += 1
        ps = r2t3.first_sellable(d, end_p)
        return float(c[ps] / buy_px * (1.0 - FEE) - 1.0), str(dts[ps])

    # Univariate IS test on 435 & 830 for actual non-zero frequency factors
    def build_uni(dfp):
        sub = dfp[dfp["buy_date"] <= "2023-12-31"]
        rows = []
        for r in sub.itertuples(index=False):
            d = cb[r.c6]; p0 = r.p0; dt0 = str(d["dts"][p0])
            rb, _ = sim_pry_ext(r.c6, d, p0)
            p1 = r2t3.first_sellable(d, p0 + 1); dk1 = str(d["dts"][p1])
            ms1 = env["mkt_stats"].get(dk1, {})
            p1b1 = float(ms1.get("mkt_prev_1b_open_avg", 0.0))
            dt1 = int(ms1.get("mkt_0925_dt_cnt", 0))
            op1 = (float(d["open"][p1]) / float(d["close"][p0]) - 1.0) if d["close"][p0] > 0 else 0.0
            lb0 = env["lhb_buy_info"].get((dt0, r.c6), {}); ls0 = env["lhb_sell_info"].get((dt0, r.c6), {})
            rows.append({
                "rb": rb,
                "r_mktweak": sim_pry_ext(r.c6, d, p0, mkt_weak_cut=True)[0],
                "r_dt15": sim_pry_ext(r.c6, d, p0, dt15_cut=True)[0],
                "r_divcut": sim_pry_ext(r.c6, d, p0, div_cut_only=True)[0],
                "r_divext": sim_pry_ext(r.c6, d, p0, div_ext_p1b_neg05=True)[0],
                "r_zt_noimm": sim_pry_ext(r.c6, d, p0, zt_weak_noimm=True)[0],
                "r_zt_nxneg": sim_pry_ext(r.c6, d, p0, zt_nx_neg_cut=True)[0],
                "r_lhbgood": sim_pry_ext(r.c6, d, p0, lhb_good_ext=True)[0],
                "f_mktweak": bool(p1b1 < -0.005 and op1 < 0.0),
                "f_dt15": bool(dt1 >= 15 and op1 < 0.0),
                "f_divcut": bool(p1b1 >= 0.0 and -0.020 <= op1 < -0.015),
                "f_divext": bool(p1b1 < -0.004 and op1 >= 0.010),
                "f_lhbgood": bool((lb0.get("inst_buy", 0) > ls0.get("inst_sell", 0) and lb0.get("inst_buy", 0) >= 5e6) or len(lb0.get("top_yz", [])) > 0),
            })
        dfu = pd.DataFrame(rows)
        dfu["f_zt_noimm"] = np.abs(dfu["rb"] - dfu["r_zt_noimm"]) > 1e-6
        dfu["f_zt_nxneg"] = np.abs(dfu["rb"] - dfu["r_zt_nxneg"]) > 1e-6
        return dfu

    u4, u8 = build_uni(m435), build_uni(m830)
    uni = []
    for fc, rc in [("f_mktweak","r_mktweak"),("f_dt15","r_dt15"),("f_divcut","r_divcut"),("f_divext","r_divext"),("f_lhbgood","r_lhbgood"),("f_zt_noimm","r_zt_noimm"),("f_zt_nxneg","r_zt_nxneg")]:
        uni.append({"factor": fc, "is_435": pfh.univariate_summary(u4, fc, "rb", rc), "is_830": pfh.univariate_summary(u8, fc, "rb", rc)})

    # Composite eval helper
    def eval_pool(df_base, **kw):
        rets, eds = [], []
        for r in df_base.itertuples(index=False):
            rv, ed = sim_pry_ext(r.c6, cb[r.c6], r.p0, **kw)
            rets.append(rv); eds.append(ed)
        df = df_base.copy(); df["net_ret"] = rets; df["exit_date"] = eds
        srt = df.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
        taken, fa = [], ""
        for r in srt.itertuples(index=False):
            if fa == "" or r.buy_date > fa:
                taken.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "net_ret": r.net_ret}); fa = r.exit_date
        df_1s = pd.DataFrame(taken); df_top1 = srt.groupby("buy_date").first().reset_index(); df_eq = df.groupby("buy_date")["net_ret"].mean().sort_index()
        res = {}
        for wn, sdt, edt, csip in r2t3.WINDOWS:
            s1 = df_1s[(df_1s["buy_date"] >= sdt) & (df_1s["buy_date"] <= edt)]["net_ret"].to_numpy(float) if not df_1s.empty else np.array([], float)
            eqa = df_eq[(df_eq.index >= sdt) & (df_eq.index <= edt)].to_numpy(float)
            t1 = df_top1[(df_top1["buy_date"] >= sdt) & (df_top1["buy_date"] <= edt)]["net_ret"].to_numpy(float)
            res[wn] = {"single_slot": pfh.calc_arr_metrics(s1, csip), "daily_eq_all": pfh.calc_arr_metrics(eqa, csip), "daily_top1_eq": pfh.calc_arr_metrics(t1, csip)}
        return res

    comp = []
    for nm, kw in [
        ("r2_h3_divcut_only", dict(div_cut_only=True)),
        ("r2_h3_divext_neg04", dict(div_ext_p1b_neg05=True)),
        ("r2_h3_mkt_weak_cut", dict(mkt_weak_cut=True)),
        ("r2_h3_dt15_cut", dict(dt15_cut=True)),
        ("r2_h3_zt_weak1to2_noimm", dict(zt_weak_noimm=True)),
        ("r2_h3_zt_nx_neg_cut", dict(zt_nx_neg_cut=True)),
    ]:
        comp.append({"name": nm, "pool_435_strict": eval_pool(m435, **kw), "pool_830_broad": eval_pool(m830, **kw)})
    return {"uni": uni, "comp": comp}


def main():
    t0 = time.time()
    with open(f"{RD2_DIR}/pit_exit_env.pkl", "rb") as f:
        env = pickle.load(f)
    r1 = audit_2to3_refine(env)
    r2 = audit_3to4_refine(env)
    r3 = audit_pry_refine(env)
    out = {"s_2to3_refine": r1, "s_3to4_refine": r2, "s_pry_refine": r3}
    with open(f"{RD2_DIR}/round2_refine.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("=== 2to3 Refine ===")
    for k, v in r1["uni_imm"].items():
        print(" ", k, v)
    for e in r1["comp"]:
        f5, isf, oo = e["std90"]["full_5y"]["single_slot"], e["std90"]["is_21_23_full"]["single_slot"], e["std90"]["oos_24_26"]["single_slot"]
        print(f"  {e['name']:30s} | 5Y={f5['nav']:6.2f} ISf={isf['nav']:5.2f} OOS={oo['nav']:5.2f} EQ={e['std90']['full_5y']['daily_eq']['nav']:6.2f} | S96={e['strict96']['full_5y']['single_slot']['nav']:5.2f}")

    print("\n=== 3to4 Refine Uni IS ===")
    for k, v in r2["uni_is_dev_imm"].items():
        a, b = v["is_std90"], v["is_wide75"]
        print(f"  {k:24s} | S90: n={a['n_trig']:2d} {a['base_mean_pct']:+5.2f}%->{a['alt_mean_pct']:+5.2f}% ({a['delta_bps']:+6.0f}bps, +{a.get('improved_trades',0)}/-{a.get('hurt_trades',0)}) | W75: n={b['n_trig']:2d} {b['base_mean_pct']:+5.2f}%->{b['alt_mean_pct']:+5.2f}% ({b['delta_bps']:+6.0f}bps, +{b.get('improved_trades',0)}/-{b.get('hurt_trades',0)})")
    print("=== 3to4 Refine Comp ===")
    for e in r2["comp"]:
        s90, s102 = e["std90"], e["strict102"]
        print(f"  {e['name']:30s} | S90: 5Y={s90['full_5y']['single_slot']['nav']:7.2f}(T5={s90['full_5y']['single_slot']['trim5_nav']:6.2f}) IS={s90['is_22_23']['single_slot']['nav']:5.2f} OOS={s90['oos_24_26']['single_slot']['nav']:6.2f} 25-26={s90['y25_26_reg']['single_slot']['nav']:5.2f} 26={s90['y2026_1y']['single_slot']['nav']:4.2f} EQ={s90['full_5y']['daily_eq']['nav']:7.2f} | S102={s102['full_5y']['single_slot']['nav']:5.2f}(OOS={s102['oos_24_26']['single_slot']['nav']:5.2f})")

    print("\n=== Pry Refine Uni IS ===")
    for x in r3["uni"]:
        a, b = x["is_435"], x["is_830"]
        print(f"  {x['factor']:14s} | 435: n={a['n_trig']:2d} {a['base_mean_pct']:+5.2f}%->{a['alt_mean_pct']:+5.2f}% ({a['delta_bps']:+5.0f}bps) | 830: n={b['n_trig']:2d} {b['base_mean_pct']:+5.2f}%->{b['alt_mean_pct']:+5.2f}% ({b['delta_bps']:+5.0f}bps)")
    print("=== Pry Refine Comp ===")
    for e in r3["comp"]:
        p4, p8 = e["pool_435_strict"], e["pool_830_broad"]
        print(f"  {e['name']:26s} | 435_1S: 5Y={p4['full_5y']['single_slot']['nav']:.3f}(IS={p4['is_22_23']['single_slot']['nav']:.3f},OOS={p4['oos_24_26']['single_slot']['nav']:.3f}) EQ435={p4['full_5y']['daily_eq_all']['nav']:.3f} Top1={p4['full_5y']['daily_top1_eq']['nav']:.3f} | 830_EQ={p8['full_5y']['daily_eq_all']['nav']:.3f}(IS={p8['is_22_23']['daily_eq_all']['nav']:.2f},OOS={p8['oos_24_26']['daily_eq_all']['nav']:.2f})")
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
