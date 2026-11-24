#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part D2 Base: Reproduce P3_S2C_STierReserveOnly, export clean CSV, physical & old-suite audits."""
import json, math, os, sys
import numpy as np, pandas as pd, pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
PARTC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
MW_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123"
OUT_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan"
for p in (PARTC_V20, PARTA_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import tier_priority_engine as tpe
import mod_common as mc
import mod_1to2 as m12

STRAT_CN = {"3to4": "三进四V4.1", "high": "高标首阴V5.1", "pry": "超跌撬板V2.1", "2to3": "二进三V2.1", "1to2": "一进二V20", "20cm": "20cm首板V1.1_S82"}
S2C_MAP = {"3to4_S(>=102)": 1, "3to4_A(90-101)": 1, "high_S(>=96)": 2, "high_A(88-95)": 2,
           "pry_S(>=175)": 3, "pry_A(165-174)": 3, "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
           "1to2_S(>=340)": 5, "1to2_A(304.8-339.9)": 5, "1to2_FB(295-304.7)": 5, "20cm_S(>=82)": 6, "20cm_A(76-81)": 999}
CSV_MAP = {"3to4": f"{PARTC_DIR}/ledger_3to4_v41_clean.csv", "high": f"{PARTC_DIR}/ledger_high_v51_clean.csv",
           "pry": f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv", "2to3": f"{PARTC_DIR}/ledger_2to3_v21_opt_std90_clean.csv",
           "1to2": f"{PARTA_DIR}/ledger_1to2_v20_cand.csv", "20cm": f"{V11_DIR}/final_v11_ledger.csv"}

def sf(x, digits=6):
    if x is None: return None
    v = float(x)
    return None if (math.isnan(v) or math.isinf(v)) else round(v, digits)

def build_and_export_combined(bar_lu: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list]:
    pool6 = pd.concat([tpe.load_strategy_csv(st, p, "2021-11-16", "2026-11-16") for st, p in CSV_MAP.items()], ignore_index=True)
    untrig_df = tpe.build_untriggered_baseline_pool(pool6, "2021-11-16", "2026-11-16")
    tr_df, waits = tpe.run_single_slot(pool6, lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode="s_tier_reserve_only")
    assert len(tr_df) == 278, f"Expected 278 trades, got {len(tr_df)}"
    assert abs(float(np.prod(1.0 + tr_df["net_ret"])) - 69134091.1181) < 1.0, "FULL NAV mismatch"

    raw10 = {}
    for st in ("3to4", "high", "pry", "2to3", "1to2"):
        d = pd.read_csv(CSV_MAP[st]); d["code"] = d["code"].astype(str).str.zfill(6)
        for r in d.itertuples(index=False): raw10[(st, r.code, str(r.buy_date)[:10])] = (float(r.buy_price), float(r.exit_price))
    v11 = pd.read_csv(CSV_MAP["20cm"], dtype={"c6": str}); v11["c6"] = v11["c6"].str.zfill(6)
    v11_lu = {(r.c6, str(r.buy_date)[:10]): (float(r.buy_px), float(r.exit_px)) for r in v11.itertuples(index=False)}

    rows = []
    for r in tr_df.itertuples(index=False):
        bb, eb = bar_lu[(r.code, r.buy_date)], bar_lu[(r.code, r.exit_date)]
        if r.strategy == "20cm":
            bp_a, ep_a = v11_lu[(r.code, r.buy_date)]
            bp, ep, fee = round(bp_a / bb[4], 4), round(ep_a / eb[4], 4), 0.0030
        else:
            bp, ep = raw10[(r.strategy, r.code, r.buy_date)]
            bp_a, ep_a, fee = bp * bb[4], ep * eb[4], 0.0020
        rows.append({
            "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
            "code": r.code, "c6": r.code, "name": r.name, "strategy": r.strategy, "strategy_cn": STRAT_CN[r.strategy],
            "tier": r.tier, "phase": int(r.phase), "priority": int(r.prio), "score": float(r.score),
            "buy_price": bp, "exit_price": ep, "buy_px_adj": bp_a, "exit_px_adj": ep_a, "fee_rt": fee, "net_ret": float(r.net_ret),
        })
    out_df = pd.DataFrame(rows)
    out_df["nav_all"] = np.round(np.cumprod(1.0 + out_df["net_ret"].to_numpy()), 4)
    out_csv = f"{OUT_DIR}/ledger_combined_6strat_v20_slot1_clean.csv"
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return out_df, pool6, untrig_df, waits

def verify_physical_cleanliness(df: pd.DataFrame, px_df: pd.DataFrame) -> dict:
    p = px_df[px_df["c6"].isin(set(df["code"]))].copy()
    p["prev_c_adj"] = p.groupby("c6")["close"].shift(1) * p.groupby("c6")["adjf"].shift(1) / p["adjf"]
    lim = np.where(p["c6"].str.startswith(("300", "301", "688", "689")), 0.20, 0.10)
    p["zt_px"] = np.floor(p["prev_c_adj"] * (1 + lim) * 100.0 + 0.5) / 100.0
    p["dt_px"] = np.floor(p["prev_c_adj"] * (1 - lim) * 100.0 + 0.5) / 100.0
    lu = {(r.c6, r.dt): r for r in p.itertuples(index=False)}
    t0_v = int((df["exit_date"] <= df["buy_date"]).sum())
    ov_v = sum(1 for i in range(1, len(df)) if not ((df.loc[i, "buy_date"], int(df.loc[i, "buy_hhmm"])) > (df.loc[i - 1, "exit_date"], int(df.loc[i - 1, "exit_hhmm"]))))
    yz_b = yz_d = dt15 = oob = ex_err = 0
    for r in df.itertuples(index=False):
        bb, eb = lu[(r.code, r.buy_date)], lu[(r.code, r.exit_date)]
        if bb.open >= bb.zt_px - 0.015 and bb.low >= bb.zt_px - 0.015: yz_b += 1
        if eb.high <= eb.dt_px + 0.015 and eb.close <= eb.dt_px + 0.015: yz_d += 1
        if int(r.exit_hhmm) >= 1455 and eb.close <= eb.dt_px + 0.005: dt15 += 1
        if r.buy_price < bb.low - 0.015 or r.buy_price > bb.high + 0.015 or r.exit_price < eb.low - 0.015 or r.exit_price > eb.high + 0.015: oob += 1
        exp_r = (r.exit_price / r.buy_price) * (bb.qfq_factor / eb.qfq_factor) * (1.0 - r.fee_rt) - 1.0
        if abs(exp_r - r.net_ret) > 0.005: ex_err += 1
    res = {"n": int(len(df)), "t0_violations": t0_v, "overlap_violations": ov_v, "yizi_zt_buy": yz_b,
           "yizi_dt_exit": yz_d, "dt_sealed_1500_sell": dt15, "oob_price": oob, "ex_div_err_gt50bps": ex_err}
    assert all(v == 0 for k, v in res.items() if k != "n"), res
    return res

def run_old_suite(comb_df: pd.DataFrame, daily_s: np.ndarray, cal_dates: list[str], sh300: dict, all_sh_dts: list[str],
                  pool6: pd.DataFrame, untrig_df: pd.DataFrame) -> dict:
    dt_idx = {d: i for i, d in enumerate(cal_dates)}
    wins_spec = [("FULL", "2021-11-16", "2026-11-16"), ("IS", "2021-11-16", "2024-08-31"),
                 ("OOS", "2024-09-01", "2026-11-16"), ("Near3Y", "2023-11-16", "2026-11-16"), ("Y2026", "2026-01-01", "2026-11-16")]
    win_metrics = {}
    for wlbl, sdt, edt in wins_spec:
        m = tpe.calc_window_metrics(comb_df, daily_s, cal_dates, dt_idx, sh300, all_sh_dts, sdt, edt)
        sub_r = np.sort(comb_df[comb_df["buy_date"].between(sdt, edt)]["net_ret"].to_numpy(float))
        m["ex_top3_nav"] = round(float(np.prod(1.0 + sub_r[:-3])), 4) if len(sub_r) > 3 else 1.0
        win_metrics[wlbl] = m

    tr_list = comb_df.to_dict("records")
    hlz_t, dsr150 = mc.hlz_and_dsr150(tr_list, sh300, all_sh_dts, m_trials=150)
    _, dsr30 = mc.hlz_and_dsr150(tr_list, sh300, all_sh_dts, m_trials=30)
    _, dsr200 = mc.hlz_and_dsr150(tr_list, sh300, all_sh_dts, m_trials=200)
    csi_arr = np.array([sh300[d] / sh300[all_sh_dts[all_sh_dts.index(d) - 1]] - 1.0 for d in cal_dates], float)
    dex = daily_s - csi_arr
    hlz_d = float(dex.mean() / dex.std(ddof=1) * math.sqrt(len(dex)))

    # Monkey MC 5,000x across 6-strategy candidate pools & triggered 576 signals
    rng = np.random.default_rng(20261124)
    p6_all = pd.concat([
        pd.read_csv(f"{MW_DIR}/part1_3to4_high/pool_3to4_full_clean.csv")[["buy_date", "net_ret"]],
        pd.read_csv(f"{MW_DIR}/part1_3to4_high/pool_high_full_clean.csv")[["buy_date", "net_ret"]],
        pd.read_csv(f"{MW_DIR}/part2_2to3_pry/pool_pry_full_clean.csv")[["buy_date", "net_ret"]],
        pd.read_csv(f"{MW_DIR}/part2_2to3_pry/pool_2to3_full_clean.csv")[["buy_date", "net_ret"]],
        pd.read_csv(f"{MW_DIR}/part3_1to2/pool_1to2_full_clean.csv")[["buy_date", "net_ret"]],
        pd.read_csv(f"{V11_DIR}/final_v11_all_scored_signals.csv")[["buy_date", "net_ret"]],
    ], ignore_index=True)
    p6_all["buy_date"] = p6_all["buy_date"].astype(str).str[:10]
    p6_all = p6_all[p6_all["buy_date"].between("2021-11-16", "2026-11-16")]
    def _run_mk(pool_r: np.ndarray, by_dt: dict):
        act_r = comb_df["net_ret"].to_numpy(float)
        am, an, n = float(act_r.mean()), float(np.prod(1.0 + act_r)), len(act_r)
        dfull = pool_r[rng.integers(0, len(pool_r), size=(5000, n))]
        cands = [by_dt.get(d, pool_r) for d in comb_df["buy_date"]]
        dsd = np.column_stack([c[rng.integers(0, len(c), size=5000)] for c in cands])
        return {"n": n, "pool_n": int(len(pool_r)), "actual_mean_pct": sf(am * 100.0, 2), "pool_mean_pct": sf(pool_r.mean() * 100.0, 2),
                "full_pool_p_mean": sf((np.sum(dfull.mean(1) >= am) + 1) / 5001.0, 5), "full_pool_p_nav": sf((np.sum(np.prod(1 + dfull, 1) >= an) + 1) / 5001.0, 5),
                "same_day_p_mean": sf((np.sum(dsd.mean(1) >= am) + 1) / 5001.0, 5), "same_day_p_nav": sf((np.sum(np.prod(1 + dsd, 1) >= an) + 1) / 5001.0, 5)}

    monkey = {
        "all_6pools_3805": _run_mk(p6_all["net_ret"].to_numpy(float), {d: g["net_ret"].to_numpy(float) for d, g in p6_all.groupby("buy_date")}),
        "triggered_6strat_576": _run_mk(pool6["net_ret"].to_numpy(float), {d: g["net_ret"].to_numpy(float) for d, g in pool6.groupby("buy_date")}),
    }

    pc_json = json.load(open(f"{PARTC_V20}/partC_v20_final_tier_priority.json", encoding="utf-8"))
    cscv_reuse = pc_json["primary_exact_6csv"]["overfitting_audits"]

    # 2025-01-01 physical truncation (rebuild 1to2 V20 <=2024-12-31 + truncate all pools & untriggered <=2024-12-31)
    hf_t, inv_t, sc_t, _, _ = m12.build_1to2_ctx_and_cache("2024-12-31")
    fb20_tr = {d for d, c in mc.build_fb20_cln_dates_pit("2024-12-31").items() if c >= 2}
    _, tr12_t, _, _ = m12.run_1to2_variant(hf_t, inv_t, sc_t, np.where(hf_t["d2_dt"].isin(fb20_tr).to_numpy(), -25.0, 0.0))
    df12_t = pd.DataFrame([{k: t[k] for k in m12.LEDGER_COLS} for t in tr12_t])
    df12_t["code"] = df12_t["code"].astype(str).str.zfill(6)
    p6_tr = pd.concat([
        tpe.load_strategy_csv(st, CSV_MAP[st], "2021-11-16", "2024-12-31") for st in ("3to4", "high", "pry", "2to3", "20cm")
    ] + [tpe.load_strategy_csv("1to2", CSV_MAP["1to2"], "2021-11-16", "2024-12-31") if df12_t.empty else df12_t.assign(
        buy_price_val=df12_t["buy_price"].astype(float), is_adj_px=False, strategy="1to2",
        tier=[tpe.assign_physical_tier("1to2", sc) for sc in df12_t["score"]], is_untrig=False
    )[["buy_date","buy_hhmm","exit_date","exit_hhmm","code","name","strategy","tier","score","net_ret","buy_price_val","is_adj_px","is_untrig"]]], ignore_index=True)
    p6_tr = p6_tr[p6_tr["exit_date"] <= "2024-12-31"].copy()
    ut_tr = untrig_df[untrig_df["buy_date"] <= "2024-12-31"].copy()
    tr_trunc, _ = tpe.run_single_slot(p6_tr, lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), untrig_df=ut_tr, timing_mode="s_tier_reserve_only")
    f24 = comb_df[comb_df["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    t24 = tr_trunc[tr_trunc["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    assert len(f24) == len(t24) and (f24["code"].to_numpy() == t24["code"].to_numpy()).all(), "Trunc sequence mismatch!"
    trunc_diff = float(np.max(np.abs(f24["net_ret"].to_numpy() - t24["net_ret"].to_numpy())))
    assert trunc_diff == 0.0, f"Trunc max diff != 0: {trunc_diff}"

    return {"windows": win_metrics, "hlz_t_trade": hlz_t, "hlz_t_daily": sf(hlz_d, 2),
            "dsr_M30": dsr30, "dsr_M150": dsr150, "dsr_M200": dsr200, "monkey_mc_5000": monkey,
            "cscv_pbo_from_partC": cscv_reuse,
            "truncation_20250101": {"trades_exiting_le_20241231": int(len(t24)), "max_abs_diff": trunc_diff, "pass": trunc_diff == 0.0}}
