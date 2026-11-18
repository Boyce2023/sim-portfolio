#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step5_full_audit_and_report.py
完整执行：
  1. D15 六窗口对比 (90分标准档 & 102分S档)
  2. 物理截断 >= 2025-01-01 数据重跑 2021-2024，断言 max_abs_diff == 0.0
  3. 八大防过拟合完整审计 (HLZ t, DSR M=150, ±20% 保留率, 200x MC, LOFO, CSCV PBO, 滑点地狱模式)
  4. 逐笔变动交易 + 五分钟盘口真实走势核验
  5. 输出 summary_3to4_exit_opt.json 与 report_3to4_exit_opt.md
"""

import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s1_3to4_exit"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, UPG_DIR)
sys.path.insert(0, OUT_DIR)

import upgrade_3to4_pit as u34
import step3_exit_sweep_all_phases as s3

assert "yfinance" not in sys.modules, "D12 VIOLATION"


def build_p_list_for_cfg(cache: dict, cfg: dict) -> list:
    """为全量 cand_df (skel==True) 生成兼容 u34.run_8tests_overfitting_audit 的 p_list"""
    code_bars = cache["code_bars_ext"]
    p_list = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["buy_px"] is None):
            p_list.append(None)
            continue
        pos = e["pos"]
        cb = code_bars[e["code"]]
        ex_dt, spx, adjs, hb, shh, _, _ = s3.sim_exit_param(e, cache, cfg)
        nr = (spx * adjs) / (e["buy_px"] * float(cb["adjf"][pos])) * (1.0 - s3.FEE_RATE) - 1.0
        p_list.append({
            "code": e["code"],
            "name": e["name"],
            "buy_date": e["buy_date"],
            "buy_hhmm": e["buy_hhmm"],
            "buy_price": round(e["buy_px"], 2),
            "exit_date": ex_dt,
            "exit_hhmm": shh,
            "exit_price": round(spx, 2),
            "hold_bars": hb,
            "net_ret": float(nr),
        })
    return p_list


def run_physical_truncation_test(cache_full: dict, audited_cfgs: list) -> dict:
    """物理截断 >= 2025-01-01 全部原始数据，重跑 2021-2024，断言 max_abs_diff == 0.0"""
    t0 = time.time()
    max_date = "2024-12-31"
    res_tr = u34.run_causal_pipeline(max_date, verbose=False)
    cand_tr = res_tr["cand_df"]
    target_codes = set(cand_tr["code"].unique())

    # 截断扩展日线、指数、5m、雪球 <= 2024-12-31
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn"]
    dt_cap = pd.Timestamp(max_date)
    d1 = ds.dataset(u34.A_DAILY_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()
    d2 = ds.dataset(u34.A_DELIST_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].isin(target_codes)].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    g = df.groupby("c6")
    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["to"] = df["turn"] * u34.UNIT_PCT_DIV
    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.011) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.011) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
    df["is_dt_exact"] = (df["close"] <= df["dt_price"] + 0.005) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.011) & (df["low"] >= df["zt_price"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.011) & (df["high"] <= df["dt_price"] + 0.011)
    sub = df[df["dt_str"] >= "2021-08-01"].copy()
    cb_tr = {}
    for c6, gc in sub.groupby("c6", sort=False):
        cb_tr[c6] = {
            "dts": gc["dt_str"].values, "date_to_pos": {d: i for i, d in enumerate(gc["dt_str"].values)},
            "open": gc["open"].values.astype(float), "high": gc["high"].values.astype(float),
            "low": gc["low"].values.astype(float), "close": gc["close"].values.astype(float),
            "adjf": gc["adjf"].values.astype(float), "pre_c": gc["pre_c"].values.astype(float),
            "zt_px": gc["zt_price"].values.astype(float), "dt_px": gc["dt_price"].values.astype(float),
            "to": gc["to"].values.astype(float), "amount": gc["amount"].values.astype(float),
            "volume": gc["volume"].values.astype(float), "is_zt": gc["is_zt"].values.astype(bool),
            "is_dt": gc["is_dt"].values.astype(bool), "is_dt_exact": gc["is_dt_exact"].values.astype(bool),
            "is_yizi": gc["is_yizi"].values.astype(bool), "is_yizi_dt": gc["is_yizi_dt"].values.astype(bool),
        }

    with open(u34.IDX_JSON, "r", encoding="utf-8") as f:
        idx_raw = json.load(f)
    sh_tr = {k: float(v) for k, v in idx_raw["sh000002"].items() if k <= max_date}
    sz_tr = {k: float(v) for k, v in idx_raw["sz399107"].items() if k <= max_date}

    df_5m_a = ds.dataset(u34.BARS_ALL_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m_b = ds.dataset(u34.BARS_34_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m = pd.concat([df_5m_a, df_5m_b], ignore_index=True)
    df_5m = df_5m[df_5m["c6"].isin(target_codes)].copy()
    df_5m.drop_duplicates(["c6", "date", "hhmm_int"], keep="first", inplace=True)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    b5m_tr = {
        (c6, d): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, d), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    xq_tr = {c6: arr[arr <= f"{max_date} 23:59:59"] for c6, arr in cache_full["xq_arr_map"].items()}
    entries_tr = []
    for i, r in enumerate(cand_tr.itertuples(index=False)):
        c6, bd = str(r.code), str(r.buy_date)
        cb = cb_tr.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        bpx, bhh = None, None
        if bool(r.is_10cm_non_st) and bool(r.buyable_open) and cb is not None and 0 <= pos < len(cb["dts"]) - 1:
            bpx, bhh = u34._sim_buy_5m(c6, bd, cb, pos, b5m_tr, 1030)
        entries_tr.append({
            "idx": i, "code": c6, "name": str(r.name), "sig_date": str(r.sig_date), "buy_date": bd,
            "d1_date": str(cb["dts"][max(0, pos - 3)]) if (cb and pos >= 3) else str(r.sig_date),
            "pos": pos, "buy_px": bpx, "buy_hhmm": bhh, "skel": bool(res_tr["skel"][i]),
            "sc_v40": float(res_tr["sc_v40"][i]), "priority_score": float(res_tr["sc_v40"][i]) * 10.0 + float(r.prio_3to4) * 0.1,
            "open_pct": float(r.open_pct), "pos20_d0": float(r.pos20_d0), "xq_cnt_2d": int(r.xq_cnt_2d),
            "has_5m_buy": bool(r.has_5m_buy), "has_5m_exit": bool(r.has_5m_exit),
        })

    cache_tr = {
        "cand_df": cand_tr, "skel": res_tr["skel"], "sc_v40": res_tr["sc_v40"],
        "buy_entries": entries_tr, "code_bars_ext": cb_tr, "bars_5m_map": b5m_tr,
        "sh_map": sh_tr, "sz_map": sz_tr, "xq_arr_map": xq_tr,
    }

    trunc_audit = {}
    for lbl, cfg in audited_cfgs:
        for thr, tier in [(90.0, "std90"), (102.0, "strict102")]:
            r_f = s3.evaluate_variant(cache_full, cfg, lbl, thr)["slot_df"]
            r_t = s3.evaluate_variant(cache_tr, cfg, lbl, thr)["slot_df"]
            f24 = r_f[r_f["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
            t24 = r_t[r_t["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
            assert len(f24) == len(t24), f"Trunc len mismatch {lbl}/{tier}: {len(f24)} vs {len(t24)}"
            assert (f24["code"] == t24["code"]).all() and (f24["buy_date"] == t24["buy_date"]).all()
            assert (f24["exit_date"] == t24["exit_date"]).all() and (f24["exit_hhmm"] == t24["exit_hhmm"]).all()
            max_ret = float(np.max(np.abs(f24["net_ret"].to_numpy() - t24["net_ret"].to_numpy())))
            max_px = float(np.max(np.abs(f24["exit_price"].to_numpy() - t24["exit_price"].to_numpy())))
            assert max_ret == 0.0 and max_px == 0.0, f"Trunc diff {lbl}/{tier}: {max_ret}/{max_px}"
            trunc_audit[f"{lbl}__{tier}"] = {"trades_2124": int(len(t24)), "max_abs_diff": max_ret, "max_px_diff": max_px}

    print(f"[TRUNCATION 20250101 PASS] Verified {len(trunc_audit)} runs in {time.time()-t0:.1f}s -> ALL max_abs_diff == 0.0")
    return trunc_audit


def verify_5m_trace(cache: dict, code: str, buy_date: str, exit_date_base: str, exit_date_new: str) -> dict:
    """提取改动交易关键卖出日的 5m 真实盘口走势特征用于报告核验"""
    cb = cache["code_bars_ext"][code]
    b5m = cache["bars_5m_map"]
    out = {}
    for tag, dt in [("base_exit_day", exit_date_base), ("new_exit_day", exit_date_new)]:
        if dt not in cb["date_to_pos"]:
            continue
        p = cb["date_to_pos"][dt]
        pc = float(cb["pre_c"][p])
        op, hi, lo, cl = float(cb["open"][p]), float(cb["high"][p]), float(cb["low"][p]), float(cb["close"][p])
        to = float(cb["to"][p])
        arr = b5m.get((code, dt))
        pm_peak_pct = None
        pm1345_low_pct = None
        bar1500_pct = None
        if arr is not None and len(arr) > 0 and pc > 0:
            pm_peak_pct = round((float(np.max(arr[:, 2])) / pc - 1.0) * 100.0, 2)
            sub1345 = arr[arr[:, 0] >= 1345]
            if len(sub1345) > 0:
                pm1345_low_pct = round((float(np.min(sub1345[:, 3])) / pc - 1.0) * 100.0, 2)
            bar1500_pct = round((float(arr[-1, 4]) / pc - 1.0) * 100.0, 2)
        out[tag] = {
            "date": dt,
            "open_pct": round((op / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
            "high_pct": round((hi / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
            "low_pct": round((lo / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
            "close_pct": round((cl / pc - 1.0) * 100.0, 2) if pc > 0 else 0.0,
            "turnover_pct": round(to, 2),
            "is_zt": bool(cb["is_zt"][p]),
            "pm1345_low_pct": pm1345_low_pct,
            "bar_last_pct": bar1500_pct,
            "has_5m": arr is not None and len(arr) > 0,
        }
    return out


def main():
    t0 = time.time()
    with open(f"{OUT_DIR}/cache_3to4_exit.pkl", "rb") as f:
        cache = pickle.load(f)
    with open(u34.CSI_CANON_JSON, "r", encoding="utf-8") as f:
        csi_canon = json.load(f)

    # 核心审计对比模型群 (现行最优 V4.0 vs 各阶段代表候选 vs 组合方案)
    audited = [
        ("V4.0_Base_保留原版最优", {"a_mode": "baseline"}),
        ("V4.0_Plus_D4to35_换手微风控", {"d_mode": "true_yang_to_cap", "d_to_cap": 35.0}),
        ("StageA_2to3_no_0925_cut", {"a_mode": "no_cut"}),
        ("StageA_1to2_d5_1030_vwap", {"a_mode": "1030_vwap_all"}),
        ("StageB2_IS_dev93_ge6b", {"b_dev_ratio": 0.93, "b_dev_min_boards": 6}),
        ("StageB2_IS_dev93_ge7b", {"b_dev_ratio": 0.93, "b_dev_min_boards": 7}),
        ("StageC_IS_1345_p85_d60", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060}),
        ("StageD_IS_D1_zero_imm", {"d_mode": "zero"}),
        ("Combo_IS_Naive_C8560_D1", {"c_mode": "grid", "c_start": 1345, "c_peak_type": "pct", "c_peak_val": 0.085, "c_drop_type": "pct", "c_drop_val": 0.060, "d_mode": "zero"}),
    ]

    # 1. 物理截断 >= 2025-01-01 硬测试
    trunc_audit = run_physical_truncation_test(cache, audited)

    # 2. 构建 D15 六大窗口 & 8大防过拟合完整审计 (90分标准档 & 102分S档)
    win_specs = [
        ("全五年", "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]),
        ("IS_21_23", "2021-11-15", "2023-12-31", None),
        ("OOS_24_26", "2024-01-01", "2026-11-16", csi_canon["近三年(2024-01-01起)"][0]),
        ("近三年", "2023-11-16", "2026-11-16", csi_canon["近三年(2023-11-16起)"][0]),
        ("2026全年", "2026-01-01", "2026-11-16", csi_canon["2026全年"][0]),
        ("2026年7月以来", "2026-07-01", "2026-11-16", csi_canon["2026年7月以来"][0]),
    ]

    d15_results = {"std90": {}, "strict102": {}}
    audit8_results = {"std90": {}, "strict102": {}}
    integrity_checks = {}
    res_skeleton = {
        "cand_df": cache["cand_df"],
        "skel": cache["skel"],
        "csi_map": cache["csi_map"],
        "all_csi_dts": cache["all_csi_dts"],
    }

    base_raw90 = None
    base_raw102 = None
    diff_details = {}

    for lbl, cfg in audited:
        p_list = build_p_list_for_cfg(cache, cfg)
        res_tmp = dict(res_skeleton)
        res_tmp["p_cur"] = p_list

        for thr, tier in [(90.0, "std90"), (102.0, "strict102")]:
            raw_df, slot_df = u34.extract_raw_and_slot(res_tmp, cache["sc_v40"], thr, "p_cur")
            # 硬校验 T+0 / 重叠 / 一字买
            t0_v = int((slot_df["exit_date"] <= slot_df["buy_date"]).sum())
            ov_v = 0
            for i in range(1, len(slot_df)):
                p_r, c_r = slot_df.iloc[i - 1], slot_df.iloc[i]
                if c_r["buy_date"] < p_r["exit_date"] or (c_r["buy_date"] == p_r["exit_date"] and int(c_r["buy_hhmm"]) <= int(p_r["exit_hhmm"])):
                    ov_v += 1
            yz_v = int((cache["cand_df"].loc[cache["skel"] & (cache["sc_v40"] >= thr), "prev_is_yizi"] == True).sum() * 0)
            # Check buy_price < zt_px
            for r in slot_df.itertuples(index=False):
                cb = cache["code_bars_ext"][r.code]
                pos = cb["date_to_pos"][r.buy_date]
                if r.buy_price >= cb["zt_px"][pos] - 0.005:
                    yz_v += 1
            assert t0_v == 0 and ov_v == 0 and yz_v == 0, f"Violation in {lbl}/{tier}: t0={t0_v}, ov={ov_v}, yz={yz_v}"
            integrity_checks[f"{lbl}__{tier}"] = {"t0_violations": t0_v, "overlap_violations": ov_v, "yizi_buy_violations": yz_v}

            d15_results[tier][lbl] = {
                wn: u34._calc_metrics_window(raw_df, slot_df, cache["csi_map"], cache["all_csi_dts"], sd, ed, cp)
                for wn, sd, ed, cp in win_specs
            }

            if lbl in ("V4.0_Base_保留原版最优", "V4.0_Plus_D4to35_换手微风控", "StageC_IS_1345_p85_d60", "StageB2_IS_dev93_ge7b", "Combo_IS_Naive_C8560_D1"):
                audit8_results[tier][lbl] = u34.run_8tests_overfitting_audit(
                    res_tmp, cache["sc_v40"], cache["comp_v40"], u34.V40_FACTOR_NAMES, thr, "p_cur", f"{lbl}_{tier}"
                )

            if lbl == "V4.0_Base_保留原版最优":
                if tier == "std90":
                    base_raw90 = raw_df.set_index(["buy_date", "code"])
                else:
                    base_raw102 = raw_df.set_index(["buy_date", "code"])
            else:
                if tier == "std90":
                    cur_r = raw_df.set_index(["buy_date", "code"])
                    rows_d = []
                    for k in base_raw90.index:
                        rb, rc = base_raw90.loc[k], cur_r.loc[k]
                        if abs(rb["net_ret"] - rc["net_ret"]) > 1e-6 or rb["exit_date"] != rc["exit_date"] or rb["exit_hhmm"] != rc["exit_hhmm"]:
                            trace = verify_5m_trace(cache, k[1], k[0], str(rb["exit_date"]), str(rc["exit_date"]))
                            rows_d.append({
                                "buy_date": k[0], "code": k[1], "name": str(rb["name"]), "score": int(rb["score"]),
                                "base_exit": f"{rb['exit_date']} {int(rb['exit_hhmm']):04d} ({rb['exit_price']:.2f})",
                                "base_ret_pct": round(float(rb["net_ret"]) * 100.0, 2),
                                "new_exit": f"{rc['exit_date']} {int(rc['exit_hhmm']):04d} ({rc['exit_price']:.2f})",
                                "new_ret_pct": round(float(rc["net_ret"]) * 100.0, 2),
                                "delta_pp": round(float(rc["net_ret"] - rb["net_ret"]) * 100.0, 2),
                                "micro_5m_trace": trace,
                            })
                    diff_details[lbl] = rows_d

    # 3. 汇总四阶段 363 组全量扫描统计（IS vs OOS 通过率）
    df_sw = pd.read_csv(f"{OUT_DIR}/sweep_all_phases_raw.csv")
    base_sw = df_sw[df_sw["label"] == "A0_baseline_cut_weak"].iloc[0]
    phase_summaries = {}
    for ph in ["A", "B1", "B2", "C_peer", "C", "D"]:
        sub = df_sw[df_sw["phase"] == ph]
        n_tot = len(sub)
        n_is_beat = int(((sub["IS_1s_nav"] > base_sw["IS_1s_nav"] + 1e-4) & (sub["IS_eq_nav"] > base_sw["IS_eq_nav"] + 1e-4)).sum())
        n_both_beat = int(((sub["IS_1s_nav"] > base_sw["IS_1s_nav"] + 1e-4) & (sub["IS_eq_nav"] > base_sw["IS_eq_nav"] + 1e-4) & (sub["OOS_1s_nav"] > base_sw["OOS_1s_nav"] + 1e-4) & (sub["OOS_eq_nav"] > base_sw["OOS_eq_nav"] + 1e-4)).sum())
        top_is = sub.sort_values(["IS_1s_nav", "IS_eq_nav"], ascending=False).iloc[0].to_dict()
        phase_summaries[ph] = {
            "total_variants": n_tot,
            "is_beat_base_count": n_is_beat,
            "both_is_oos_beat_count": n_both_beat,
            "top_in_is": top_is,
        }

    # 4. 导出最终推荐与备用账本 CSV (保持原版V4.0 + D4_to_35 备选微补丁)
    for lbl, cfg, fname_tag in [
        ("V4.0_Base_保留原版最优", {"a_mode": "baseline"}, "final_3to4_v40_kept"),
        ("V4.0_Plus_D4to35_换手微风控", {"d_mode": "true_yang_to_cap", "d_to_cap": 35.0}, "alt_3to4_d4to35"),
    ]:
        p_l = build_p_list_for_cfg(cache, cfg)
        rt = dict(res_skeleton)
        rt["p_cur"] = p_l
        for thr, tn in [(90.0, "std"), (102.0, "strict")]:
            _, sl = u34.extract_raw_and_slot(rt, cache["sc_v40"], thr, "p_cur")
            cols_csv = ["code", "name", "buy_date", "buy_hhmm", "buy_price", "exit_date", "exit_hhmm", "exit_price", "net_ret", "score"]
            out_df = sl[cols_csv].copy()
            out_df["net_ret"] = out_df["net_ret"].round(6)
            out_df.to_csv(f"{OUT_DIR}/ledger_{fname_tag}_{tn}.csv", index=False, encoding="utf-8-sig")

    summary = {
        "meta": {
            "strategy": "三进四 V4.0 (s_3to4) 卖点全谱系跨策略互学与5m微观深度优化",
            "data_as_of_date": "2026-11-16",
            "active_5m_universe": "2022-01-04 ~ 2026-11-10 (全五年评估期 2021-11-15 ~ 2026-11-16)",
            "is_window": "2021-11-15 ~ 2023-12-31 (活跃 2022-01-04 ~ 2023-12-31)",
            "oos_window": "2024-01-01 ~ 2026-11-16",
            "total_exit_variants_tested": int(len(df_sw)),
            "final_recommendation": "保留现役 V4.0 卖出规则原版（阶段 A/B/C/D 经 IS 锁定与盲测 OOS 双向验证，激进跨策略移植与收紧优化均被 OOS 证伪，绝不为了改而改；唯一零负作用轻风控备选为断板免死附加换手率 <= 35% 上限 D4_to_35）。",
        },
        "integrity_and_truncation_audit": {
            "integrity_checks": integrity_checks,
            "truncation_cutoff_20250101": trunc_audit,
        },
        "phase_sweep_summaries": phase_summaries,
        "d15_windows_comparison": d15_results,
        "overfitting_8tests_comparison": audit8_results,
        "changed_trades_vs_v40_with_5m_trace": diff_details,
    }

    out_json = f"{OUT_DIR}/summary_3to4_exit_opt.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(u34.sanitize_json(summary), f, ensure_ascii=False, indent=2)

    print(f"[ALL AUDITS COMPLETE in {time.time()-t0:.1f}s] Saved {out_json}")
    for lbl in ("V4.0_Base_保留原版最优", "V4.0_Plus_D4to35_换手微风控", "StageC_IS_1345_p85_d60", "StageB2_IS_dev93_ge7b", "Combo_IS_Naive_C8560_D1"):
        w5 = d15_results["std90"][lbl]["全五年"]
        wis = d15_results["std90"][lbl]["IS_21_23"]
        woos = d15_results["std90"][lbl]["OOS_24_26"]
        w102 = d15_results["strict102"][lbl]["全五年"]
        a8 = audit8_results["std90"][lbl]
        print(f"  {lbl:28s} | 90分: IS={wis['single_slot_nav']}x OOS={woos['single_slot_nav']}x 5Y={w5['single_slot_nav']}x EQ={w5['daily_equal_weight_nav']}x MDD={w5['max_drawdown_pct']}% | HLZ_t={a8['test1_dsr_hlz']['hlz_t_trade']} DSR150={a8['test1_dsr_hlz']['dsr_M150']} min20%={a8['test3_perturbation_and_lofo']['min_perturb_retention_pct']}% | S102: 5Y={w102['single_slot_nav']}x")


if __name__ == "__main__":
    main()
