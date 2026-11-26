#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD030 Wave 1 - Step 2: Attach 6-dim PIT Old-Hot features to ALL 6 V20.0 strategies
(full candidate pool + near-threshold edge pool + V20.0 official standalone & slot1 ledgers)
AND <<临时策略：五板>> (temp5b, strictly date >= 2026-07-01), then produce wave1_old_hot_audit.json.

Hard rules:
  - ZERO yfinance (D12).
  - Pure compounding & equal-weight evaluation only.
  - Strictly read-only on all production files and strategy_astock.md.
  - All SQLite opened with file:...?mode=ro (uri=True).
"""
import json
import math
import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
OLD_HOT_PQ = f"{OUT_DIR}/old_hot_6dim_stock_day_pit.parquet"

MW = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123"
PC = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
PARTA = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
PARTD = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan"
TB1 = f"{SIM}/output/rd025_cross_factor_fusion_20261125/trackB1_10cm_fusion"
V11 = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
FIVE_MERGED = f"{ROOT}/docs/90_内部_给Claude读/astock/五板策略明细/merged_final.csv"

for p in (PARTA, TB1):
    if p not in sys.path:
        sys.path.insert(0, p)

import mod_common as mc
import trackB1_pools_and_sim as tb1

OLD_HOT_COLS = [
    "list_age", "has_active_wave", "curr_wave_streak",
    "waves_3y_g15", "waves_5y_g15", "waves_3y_g20", "waves_5y_g20",
    "active_years_3y", "active_years_5y", "active_2b_years_3y", "active_2b_years_5y",
    "zt_cnt_1y", "zt_cnt_3y", "zt_cnt_5y",
    "streak3_waves_3y", "streak3_waves_5y", "streak5_waves_5y",
    "max_streak_3y", "max_streak_5y",
    "zt_cnt_1y_t1", "zt_cnt_3y_t1", "waves_3y_g15_t1", "waves_5y_g15_t1",
    "comm_posts_1y", "comm_posts_3y", "comm_posts_1y_pct", "comm_posts_3y_pct",
    "xq_posts_1y_pct", "xq_posts_3y_pct",
    "comm_active_month_ratio_1y", "comm_active_month_ratio_3y",
    "cum_turnover_1y", "cum_turnover_3y", "trap_waves_1y", "trap_waves_3y",
    "dd_from_1y_high", "dd_from_3y_high",
    "kpl_unique_plates_3y", "kpl_unique_plates_5y",
    "kpl_plate_switch_ratio", "kpl_top_plate_share",
    "cool_days_since_last_zt", "cool_days_since_last_2b",
    "cool_bin_zt", "cool_bin_2b", "year", "era_tag", "is_oos_split",
]

UNIFIED_BASE_COLS = [
    "strategy", "code", "name", "sig_date", "buy_date", "exit_date",
    "buy_hhmm", "exit_hhmm", "buy_price", "exit_price", "net_ret",
    "base_score", "v20_score", "open_pct",
    "pool_layer", "sim_ok", "is_edge_cand", "is_near_line",
    "is_pass_official", "is_s_tier", "is_obs_a76",
    "is_standalone_slot1", "is_v20_slot1",
]


def build_temp5b_pool(end_dt: str = "2026-11-25") -> tuple[pd.DataFrame, list[dict]]:
    """Build <<临时策略：五板>> pool strictly >= 2026-07-01, parity-checked against merged_final.csv."""
    idx_json = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    idx_sh = {k: float(v) for k, v in idx_json["sh000002"].items()}
    idx_sz = {k: float(v) for k, v in idx_json["sz399107"].items()}

    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(
        columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "turn"],
        filter=ds.field("date") >= pd.Timestamp("2026-05-01"),
    ).to_table().to_pandas()
    da["c6"] = da["ticker"].astype(str).str[:6]
    da = da[da["c6"].str.startswith(("00", "60")) & (~da["ticker"].astype(str).str.endswith(".BJ")) & (da["volume"] > 0)].copy()
    da["dt"] = da["date"].dt.strftime("%Y-%m-%d")
    da = da[da["dt"] <= end_dt].sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"]).reset_index(drop=True)

    all_dts = sorted(da["dt"].unique())
    dt_to_mkt = {d: i for i, d in enumerate(all_dts)}
    da["mkt_idx"] = da["dt"].map(dt_to_mkt).astype(int)

    # PIT names / ST filter
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    st_tape = set()
    name_map = {}
    for td, sc6, nm in con_z.execute("SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date >= '2026-05-01'"):
        c6 = str(sc6).zfill(6)
        s = str(nm or "").strip()
        if s:
            name_map[c6] = s
        if "ST" in s.upper() or "退" in s:
            st_tape.add((c6, str(td)))
    con_z.close()
    st_u = {str(x)[:6].zfill(6) for x in json.load(open(f"{SIM}/data/st_universe.json", encoding="utf-8")).get("codes", [])}

    g = da.groupby("c6", sort=False)
    sc = da["adj_close"] / da["close"]
    pac = g["adj_close"].shift(1)
    pre_ex = pac / sc
    da["ref_prev"] = pre_ex
    da["adjf"] = sc
    da["ret"] = da["adj_close"] / pac - 1.0
    da["o_pct"] = (da["open"] * sc) / pac - 1.0
    da["zt_px"] = np.floor(pre_ex * 1.10 * 100.0 + 0.5) / 100.0
    da["dt_px"] = np.floor(pre_ex * 0.90 * 100.0 + 0.5) / 100.0
    da["abn"] = da["ret"].abs() > 0.12
    da["is_zt"] = (pac > 0) & (da["close"] >= da["zt_px"] - 0.011) & (da["ret"] >= 0.095) & (~da["abn"])
    da["is_dt"] = (pac > 0) & (da["close"] <= da["dt_px"] + 0.005)
    da["is_yizi_zt"] = da["is_zt"] & (da["open"] >= da["zt_px"] - 0.011) & (da["low"] >= da["zt_px"] - 0.011)
    da["is_yizi_dt"] = da["is_dt"] & (da["open"] <= da["dt_px"] + 0.005) & (da["high"] <= da["dt_px"] + 0.005)

    s_zt = da["is_zt"].astype(int)
    s_sh = g["is_zt"].shift(1, fill_value=False).astype(bool)
    da["streak"] = s_zt.groupby([da["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt

    m5 = pd.read_csv(FIVE_MERGED, dtype={"code": str})
    m5["code"] = m5["code"].str.zfill(6)
    m5_ref = {(r.code, r.five_date): r for r in m5.itertuples(index=False)}
    for r in m5.itertuples(index=False):
        if pd.notna(r.name_current):
            name_map[r.code] = str(r.name_current)

    # KPL severe abnormal resets for DEV95 matching returns.py
    reset_m = {}
    kpl_pub_p = "/tmp/astock_abnormal_steps_20261027/inputs/kpl_public_36.json"
    if os.path.exists(kpl_pub_p):
        for r in json.load(open(kpl_pub_p, encoding="utf-8")).get("rows", []):
            if ("10日100" in str(r[2]) or "30日200" in str(r[2]) or r[2] == "同向异动") and r[18] in dt_to_mkt:
                reset_m.setdefault(str(r[0]).zfill(6), []).append(dt_to_mkt[r[18]])
    resume_map = {"603137": ["2026-07-01"], "600825": ["2026-09-21", "2026-10-16"], "002084": ["2026-08-24"], "605577": ["2026-09-14"], "603221": ["2026-08-06", "2026-08-18"]}

    by_c = {c6: grp.reset_index(drop=True) for c6, grp in da.groupby("c6", sort=False)}
    s5 = da[(da["dt"] >= "2026-07-01") & (da["streak"] == 5)].copy()
    s5 = s5[~s5.apply(lambda r: ((r["c6"], r["dt"]) in st_tape) or (r["c6"] in st_u), axis=1)].copy()

    rows, pending_eps = [], []
    for r5 in s5.sort_values(["dt", "c6"]).itertuples(index=False):
        c6 = r5.c6
        five_dt = r5.dt
        grp = by_c[c6]
        j = int(grp.index[grp["dt"] == five_dt][0])

        # Walk forward along continuous ZT streak until first <= +5.5% non-yizi open or streak breaks
        status, sel_sig_dt, entry_dt, entry_px, entry_gap, sel_h = "", five_dt, "", np.nan, np.nan, 5
        entry_j = -1
        while True:
            sig_row = grp.iloc[j]
            sel_sig_dt = str(sig_row["dt"])
            sel_h = int(sig_row["streak"])
            if j + 1 >= len(grp):
                status = "pending_next_open"
                break
            nxt = grp.iloc[j + 1]
            gap = (float(nxt["open"]) * float(nxt["adjf"]) / float(sig_row["adj_close"]) - 1.0) * 100.0
            is_open_zt = float(nxt["open"]) >= float(nxt["zt_px"]) - 0.005
            if gap <= 5.5 + 1e-8 and not is_open_zt:
                status = "selected"
                entry_dt = str(nxt["dt"])
                entry_px = float(nxt["open"])
                entry_gap = gap
                entry_j = j + 1
                break
            if bool(nxt["is_zt"]) and int(nxt["streak"]) >= 6:
                j += 1
                continue
            status = "unselected_open_above5_5_then_streak_broke"
            entry_dt = str(nxt["dt"])  # decision date at 09:25 when rejected
            entry_gap = gap
            break

        if status == "pending_next_open":
            pending_eps.append({"code": c6, "name": name_map.get(c6, ""), "five_date": five_dt, "sig_date": sel_sig_dt, "height": sel_h})
            continue

        exit_dt, exit_hhmm, exit_px, net_ret, exit_reason = "", 1500, np.nan, np.nan, status
        if status == "selected":
            # Check if merged_final already has resolved DEV95
            ref_r = m5_ref.get((c6, five_dt))
            if ref_r is not None and str(ref_r.DEV95_day2to4_status) == "resolved":
                exit_dt = str(ref_r.DEV95_day2to4_exit_date)
                exit_px = float(ref_r.DEV95_day2to4_exit_price)
                exit_reason = str(ref_r.DEV95_day2to4_reason)
                exit_hhmm = 925 if "gap_open" in exit_reason else (1030 if "trade_through" in exit_reason else (925 if "delayed" in exit_reason else 1500))
                net_ret = round(float(ref_r.DEV95_day2to4_net030_pct) / 100.0, 6)
            else:
                # Simulate DEV95_day2to4 from local daily bars & sh000002/sz399107
                imap = idx_sh if c6.startswith("6") else idx_sz
                mi_arr = grp["mkt_idx"].to_numpy()
                e_row = grp.iloc[entry_j]
                em = int(e_row["mkt_idx"])
                # Find exit over Day 2..Day 4 (entry_j + 1 .. entry_j + 3)
                if entry_j + 3 >= len(grp):
                    exit_reason = "immature_day4_unfinished"
                else:
                    sold = False
                    for off in (1, 2, 3):
                        pos_d = entry_j + off
                        brow = grp.iloc[pos_d]
                        m_cur = int(brow["mkt_idx"])
                        m_prev = int(grp.iloc[pos_d - 1]["mkt_idx"])
                        d_prev_str = str(grp.iloc[pos_d - 1]["dt"])
                        iprev = imap.get(d_prev_str)
                        floor = max([v for v in reset_m.get(c6, []) if v < m_cur], default=-1)
                        for rd in resume_map.get(c6, []):
                            if brow["dt"] >= rd:
                                prev_ms = mi_arr[mi_arr < dt_to_mkt.get(rd, 999999)]
                                if len(prev_ms) > 0:
                                    floor = max(floor, int(prev_ms[-1]))
                        cands_p95 = []
                        if iprev:
                            for kk in range(max(0, pos_d - 10), pos_d):
                                old = grp.iloc[kk]
                                if int(old["mkt_idx"]) < floor:
                                    continue
                                ib = imap.get(str(old["dt"]))
                                if ib and ib > 0:
                                    raw_p = float(old["close"]) * float(old["adjf"]) / float(brow["adjf"]) * (0.95 + iprev / ib)
                                    cands_p95.append(raw_p)
                        if cands_p95:
                            p95 = math.ceil(min(cands_p95) * 100.0 - 1e-8) / 100.0
                            if float(brow["open"]) >= p95 and not bool(brow["is_yizi_dt"]):
                                exit_dt, exit_hhmm, exit_px, exit_reason = str(brow["dt"]), 925, float(brow["open"]), "95_frozen_line_gap_open"
                                sold = True
                                break
                            if float(brow["high"]) >= p95 + 0.01 - 1e-9:
                                exit_dt, exit_hhmm, exit_px, exit_reason = str(brow["dt"]), 1030, p95, "95_frozen_line_trade_through_tick"
                                sold = True
                                break
                    if not sold:
                        # Scheduled Day 4 close (defer if limit-down)
                        p_sell = entry_j + 3
                        if bool(grp.iloc[p_sell]["is_dt"]):
                            k = p_sell + 1
                            while k < len(grp) and bool(grp.iloc[k]["is_yizi_dt"]):
                                k += 1
                            if k < len(grp):
                                srow = grp.iloc[k]
                                exit_dt, exit_hhmm, exit_px, exit_reason = str(srow["dt"]), 925, float(srow["open"]), "delayed_first_sellable_open"
                            else:
                                exit_reason = "unresolved_dt_end"
                        else:
                            srow = grp.iloc[p_sell]
                            exit_dt, exit_hhmm, exit_px, exit_reason = str(srow["dt"]), 1500, float(srow["close"]), "scheduled_close"
                    if exit_dt and pd.notna(exit_px):
                        erow_s = grp[grp["dt"] == exit_dt].iloc[0]
                        gross = (exit_px * float(erow_s["adjf"])) / (entry_px * float(e_row["adjf"])) - 1.0
                        net_ret = round(gross - 0.0030, 6)

        is_sel = (status == "selected")
        rows.append({
            "strategy": "temp5b",
            "code": c6,
            "name": name_map.get(c6, ""),
            "sig_date": sel_sig_dt,
            "buy_date": entry_dt,
            "exit_date": exit_dt,
            "buy_hhmm": 925 if is_sel else 0,
            "exit_hhmm": int(exit_hhmm) if is_sel and exit_dt else 0,
            "buy_price": round(entry_px, 2) if pd.notna(entry_px) else np.nan,
            "exit_price": round(exit_px, 2) if pd.notna(exit_px) else np.nan,
            "net_ret": net_ret,
            "base_score": float(sel_h),
            "v20_score": float(sel_h),
            "open_pct": round(float(entry_gap) / 100.0, 6) if pd.notna(entry_gap) else np.nan,
            "pool_layer": "standalone_pass" if is_sel else "edge_cand",
            "sim_ok": bool(is_sel and pd.notna(net_ret)),
            "is_edge_cand": bool(not is_sel),
            "is_near_line": bool(not is_sel),
            "is_pass_official": bool(is_sel),
            "is_s_tier": bool(sel_h >= 6 and is_sel),
            "is_obs_a76": False,
            "is_standalone_slot1": bool(is_sel),
            "is_v20_slot1": False,
            "five_date": five_dt,
            "selected_height": sel_h,
            "exit_reason": exit_reason,
        })

    return pd.DataFrame(rows), pending_eps


def load_all_pools(end_dt: str = "2026-11-25") -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Load all 6 V20.0 clean pools + temp5b with exact 3-layer flags."""
    slot1_df = pd.read_csv(f"{PARTD}/ledger_combined_6strat_v20_slot1_clean.csv", dtype={"code": str, "c6": str})
    slot1_df["code"] = slot1_df["code"].str.zfill(6)
    slot1_keys = {(r.strategy, str(r.buy_date)[:10], r.code) for r in slot1_df.itertuples(index=False)}

    def _load_led_keys(path, code_col="code"):
        d = pd.read_csv(path, dtype={code_col: str})
        d[code_col] = d[code_col].str.zfill(6)
        return {(str(r.buy_date)[:10], getattr(r, code_col)) for r in d.itertuples(index=False)}

    led_keys = {
        "1to2": _load_led_keys(f"{PARTA}/ledger_1to2_v20_cand.csv"),
        "2to3": _load_led_keys(f"{PC}/ledger_2to3_v21_opt_std90_clean.csv"),
        "3to4": _load_led_keys(f"{PC}/ledger_3to4_v41_clean.csv"),
        "high": _load_led_keys(f"{PC}/ledger_high_v51_clean.csv"),
        "pry": _load_led_keys(f"{PC}/ledger_pry_v21_ss165_clean.csv"),
        "20cm_s82": _load_led_keys(f"{V11}/final_v11_ledger_S82.csv", "c6"),
        "20cm_a76": _load_led_keys(f"{V11}/final_v11_ledger.csv", "c6"),
    }

    pools = {}

    # 1. 1to2 V20 (from _cache_pretrig_pool.parquet + fb20_cln>=2 -25 penalty)
    fb20_pit = {d for d, c in mc.build_fb20_cln_dates_pit("2026-11-16").items() if c >= 2}
    p12 = pd.read_parquet(f"{MW}/part3_1to2/_cache_pretrig_pool.parquet").copy()
    p12["code"] = p12["code"].astype(str).str.zfill(6)
    p12["buy_date"] = p12["buy_date"].astype(str).str[:10]
    p12["exit_date"] = p12["exit_date"].astype(str).str[:10]
    p12["sig_date"] = ""
    p12["v20_pen"] = np.where(p12["buy_date"].isin(fb20_pit), -25.0, 0.0)
    p12["v20_score"] = p12["base_score"].astype(float) + p12["v20_pen"]
    pass12_sub, slot12_df = tb1.sim_1to2_v20(p12, 0.0)
    assert len(slot12_df) == 92, f"1to2 V20 parity len fail: {len(slot12_df)}"
    pass12_keys = {(str(r.buy_date)[:10], str(r.code).zfill(6)) for r in pass12_sub.itertuples(index=False)}
    p12["strategy"] = "1to2"
    p12["open_pct"] = p12["d2_o_pct"].astype(float)
    p12["is_pass_official"] = [(r.buy_date, r.code) in pass12_keys for r in p12.itertuples(index=False)]
    p12["is_s_tier"] = p12["is_pass_official"] & (p12["v20_score"] >= 340.0)
    p12["is_edge_cand"] = p12["sim_ok"].astype(bool) & (~p12["is_pass_official"])
    p12["is_near_line"] = p12["is_edge_cand"] & (p12["v20_score"] >= 285.0)
    p12["is_obs_a76"] = False
    p12["is_standalone_slot1"] = [(r.buy_date, r.code) in led_keys["1to2"] for r in p12.itertuples(index=False)]
    p12["is_v20_slot1"] = [("1to2", r.buy_date, r.code) in slot1_keys for r in p12.itertuples(index=False)]
    p12["pool_layer"] = np.where(
        p12["is_v20_slot1"], "slot1_v20",
        np.where(p12["is_pass_official"], "standalone_pass",
                 np.where(p12["sim_ok"], "edge_cand", "untrig")),
    )
    pools["1to2"] = p12

    # 2. 2to3 V2.1
    p23 = pd.read_csv(f"{MW}/part2_2to3_pry/pool_2to3_full_clean.csv", dtype={"code": str})
    p23["code"] = p23["code"].str.zfill(6)
    p23["buy_date"] = p23["buy_date"].astype(str).str[:10]
    p23["exit_date"] = p23["exit_date"].astype(str).str[:10]
    p23["sig_date"] = p23["sig_date"].astype(str).str[:10]
    p23["strategy"] = "2to3"
    p23["v20_score"] = p23["base_score"].astype(float)
    p23["sim_ok"] = True
    p23["is_pass_official"] = p23["v20_score"] >= 90.0
    p23["is_s_tier"] = p23["v20_score"] >= 96.0
    p23["is_edge_cand"] = p23["v20_score"] < 90.0
    p23["is_near_line"] = p23["v20_score"].between(80.0, 89.99)
    p23["is_obs_a76"] = False
    p23["is_standalone_slot1"] = [(r.buy_date, r.code) in led_keys["2to3"] for r in p23.itertuples(index=False)]
    p23["is_v20_slot1"] = [("2to3", r.buy_date, r.code) in slot1_keys for r in p23.itertuples(index=False)]
    p23["pool_layer"] = np.where(p23["is_v20_slot1"], "slot1_v20", np.where(p23["is_pass_official"], "standalone_pass", "edge_cand"))
    pools["2to3"] = p23

    # 3. 3to4 V4.1
    p34 = pd.read_csv(f"{MW}/part1_3to4_high/pool_3to4_full_clean.csv", dtype={"code": str})
    p34["code"] = p34["code"].str.zfill(6)
    p34["buy_date"] = p34["buy_date"].astype(str).str[:10]
    p34["exit_date"] = p34["exit_date"].astype(str).str[:10]
    p34["sig_date"] = ""
    p34["strategy"] = "3to4"
    p34["v20_score"] = p34["base_score"].astype(float)
    p34["sim_ok"] = True
    p34["is_pass_official"] = p34["v20_score"] >= 90.0
    p34["is_s_tier"] = p34["v20_score"] >= 102.0
    p34["is_edge_cand"] = p34["v20_score"] < 90.0
    p34["is_near_line"] = p34["v20_score"].between(80.0, 89.99)
    p34["is_obs_a76"] = False
    p34["is_standalone_slot1"] = [(r.buy_date, r.code) in led_keys["3to4"] for r in p34.itertuples(index=False)]
    p34["is_v20_slot1"] = [("3to4", r.buy_date, r.code) in slot1_keys for r in p34.itertuples(index=False)]
    p34["pool_layer"] = np.where(p34["is_v20_slot1"], "slot1_v20", np.where(p34["is_pass_official"], "standalone_pass", "edge_cand"))
    pools["3to4"] = p34

    # 4. high V5.1
    ph = pd.read_csv(f"{MW}/part1_3to4_high/pool_high_full_clean.csv", dtype={"code": str})
    ph["code"] = ph["code"].str.zfill(6)
    ph["buy_date"] = ph["buy_date"].astype(str).str[:10]
    ph["exit_date"] = ph["exit_date"].astype(str).str[:10]
    ph["sig_date"] = ""
    ph["strategy"] = "high"
    ph["v20_score"] = ph["base_score"].astype(float)
    ph["sim_ok"] = True
    ph["is_pass_official"] = ph["v20_score"] >= 88.0
    ph["is_s_tier"] = ph["v20_score"] >= 96.0
    ph["is_edge_cand"] = ph["v20_score"] < 88.0
    ph["is_near_line"] = ph["v20_score"].between(76.0, 87.99)
    ph["is_obs_a76"] = False
    ph["is_standalone_slot1"] = [(r.buy_date, r.code) in led_keys["high"] for r in ph.itertuples(index=False)]
    ph["is_v20_slot1"] = [("high", r.buy_date, r.code) in slot1_keys for r in ph.itertuples(index=False)]
    ph["pool_layer"] = np.where(ph["is_v20_slot1"], "slot1_v20", np.where(ph["is_pass_official"], "standalone_pass", "edge_cand"))
    pools["high"] = ph

    # 5. pry V2.1
    ppr = pd.read_csv(f"{MW}/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str})
    ppr["code"] = ppr["code"].str.zfill(6)
    ppr["buy_date"] = ppr["buy_date"].astype(str).str[:10]
    ppr["exit_date"] = ppr["exit_date"].astype(str).str[:10]
    ppr["sig_date"] = ppr["sig_date"].astype(str).str[:10]
    ppr["strategy"] = "pry"
    ppr["v20_score"] = ppr["base_score"].astype(float)
    ppr["open_pct"] = np.nan
    ppr["sim_ok"] = True
    ppr["is_pass_official"] = ppr["v20_score"] >= 165.0
    ppr["is_s_tier"] = ppr["v20_score"] >= 175.0
    ppr["is_edge_cand"] = ppr["v20_score"] < 165.0
    ppr["is_near_line"] = ppr["v20_score"].between(150.0, 164.99)
    ppr["is_obs_a76"] = False
    ppr["is_standalone_slot1"] = [(r.buy_date, r.code) in led_keys["pry"] for r in ppr.itertuples(index=False)]
    ppr["is_v20_slot1"] = [("pry", r.buy_date, r.code) in slot1_keys for r in ppr.itertuples(index=False)]
    ppr["pool_layer"] = np.where(ppr["is_v20_slot1"], "slot1_v20", np.where(ppr["is_pass_official"], "standalone_pass", "edge_cand"))
    pools["pry"] = ppr

    # 6. 20cm V1.1
    p20 = pd.read_csv(f"{V11}/final_v11_all_scored_signals.csv", dtype={"c6": str})
    p20["code"] = p20["c6"].str.zfill(6)
    p20["buy_date"] = p20["buy_date"].astype(str).str[:10]
    p20["exit_date"] = p20["exit_date"].astype(str).str[:10]
    p20["sig_date"] = p20["sig_date"].astype(str).str[:10]
    p20["strategy"] = "20cm"
    p20["buy_hhmm"] = 925
    p20["exit_hhmm"] = 1500
    p20["buy_price"] = p20["buy_px"].astype(float)
    p20["exit_price"] = p20["exit_px"].astype(float)
    p20["base_score"] = p20["score"].astype(float)
    p20["v20_score"] = p20["score"].astype(float)
    p20["open_pct"] = p20["open_pct"].astype(float) / 100.0
    p20["sim_ok"] = True
    p20["is_pass_official"] = p20["v20_score"] >= 82.0
    p20["is_s_tier"] = p20["v20_score"] >= 82.0
    p20["is_obs_a76"] = p20["v20_score"].between(76.0, 81.99)
    p20["is_edge_cand"] = p20["v20_score"] < 82.0
    p20["is_near_line"] = p20["v20_score"].between(72.0, 81.99)
    p20["is_standalone_slot1"] = [(r.buy_date, r.code) in led_keys["20cm_s82"] for r in p20.itertuples(index=False)]
    p20["is_standalone_a76"] = [(r.buy_date, r.code) in led_keys["20cm_a76"] for r in p20.itertuples(index=False)]
    p20["is_v20_slot1"] = [("20cm", r.buy_date, r.code) in slot1_keys for r in p20.itertuples(index=False)]
    p20["pool_layer"] = np.where(
        p20["is_v20_slot1"], "slot1_v20",
        np.where(p20["is_pass_official"], "standalone_pass",
                 np.where(p20["is_obs_a76"], "obs_a76", "edge_cand")),
    )
    pools["20cm"] = p20

    # 7. temp5b (>= 2026-07-01)
    p5b, pending_5b = build_temp5b_pool(end_dt)
    pools["temp5b"] = p5b

    return pools, pending_5b


def main():
    t0 = time.time()
    print("[Step2] Loading 6-dim PIT warehouse & all 7 strategy pools...")
    pools, pending_5b = load_all_pools("2026-11-25")

    all_codes = sorted({c for df in pools.values() for c in df["code"].unique()} | {"600722", "600103", "002242", "002579"})
    oh_df = ds.dataset(OLD_HOT_PQ, format="parquet").scanner(
        filter=ds.field("c6").isin(all_codes)
    ).to_table().to_pandas()
    oh_df["c6"] = oh_df["c6"].astype(str).str.zfill(6)
    oh_df["dt"] = oh_df["dt"].astype(str).str[:10]

    attached_unified = []
    pool_audit = {}
    for st, df in pools.items():
        merged = df.merge(
            oh_df,
            left_on=["code", "buy_date"],
            right_on=["c6", "dt"],
            how="left",
        )
        if "c6" in merged.columns and st != "20cm":
            merged.drop(columns=["c6"], inplace=True)
        if "dt" in merged.columns:
            merged.drop(columns=["dt"], inplace=True)
        out_p = f"{OUT_DIR}/pool_{st}_oldhot.parquet"
        merged.to_parquet(out_p, index=False, compression="zstd")

        # Audit Q8 missingness across OLD_HOT_COLS
        miss_rates = {}
        for col in OLD_HOT_COLS:
            mr = float(merged[col].isna().mean() * 100.0)
            if mr > 0:
                miss_rates[col] = round(mr, 2)
        core_miss = {c: miss_rates.get(c, 0.0) for c in ("waves_3y_g15", "zt_cnt_1y", "comm_posts_1y", "dd_from_1y_high", "kpl_unique_plates_3y", "era_tag")}
        assert all(v == 0.0 for v in core_miss.values()), f"Unexpected core missingness in {st}: {core_miss}"

        pool_audit[st] = {
            "total_rows": int(len(merged)),
            "buyable_sim_ok": int(merged["sim_ok"].sum()),
            "edge_cand_rows": int(merged["is_edge_cand"].sum()),
            "near_line_rows": int(merged["is_near_line"].sum()),
            "pass_official_rows": int(merged["is_pass_official"].sum()),
            "s_tier_rows": int(merged["is_s_tier"].sum()),
            "standalone_slot1_trades": int(merged["is_standalone_slot1"].sum()),
            "v20_slot1_trades": int(merged["is_v20_slot1"].sum()),
            "date_min": str(merged["buy_date"].min()),
            "date_max": str(merged["buy_date"].max()),
            "missing_pct_gt0": miss_rates,
            "file": out_p,
        }
        u_sub = merged[UNIFIED_BASE_COLS + OLD_HOT_COLS].copy()
        attached_unified.append(u_sub)
        print(f"  Attached {st:6s}: total={len(merged):4d}, sim_ok={int(merged['sim_ok'].sum()):4d}, edge={int(merged['is_edge_cand'].sum()):4d}, pass={int(merged['is_pass_official'].sum()):3d}, slot1={int(merged['is_v20_slot1'].sum()):2d}")

    uni_df = pd.concat(attached_unified, ignore_index=True)
    uni_path = f"{OUT_DIR}/pools_6strat_with_oldhot.parquet"
    uni_df.to_parquet(uni_path, index=False, compression="zstd")
    print(f"  Saved unified {uni_path}: {len(uni_df):,} rows x {uni_df.shape[1]} cols")

    # Typical stock intuition table (600722, 600103, 002242, 002579 + 2 cold new stocks)
    # Pick 2 genuine cold new stocks from 2025-2026 pools with zt_cnt_5y == 0 and lowest comm_posts_1y
    cold_cands = uni_df[
        (uni_df["buy_date"] >= "2025-01-01")
        & (uni_df["zt_cnt_5y"] == 0)
        & (uni_df["waves_5y_g15"] == 0)
        & (uni_df["kpl_unique_plates_5y"] == 0)
        & (uni_df["list_age"] >= 60)
        & (uni_df["list_age"] <= 400)
    ].sort_values(["comm_posts_1y_pct", "cum_turnover_1y", "buy_date"]).drop_duplicates("code")
    cold2 = cold_cands.head(2)

    snap_targets = [("600722", "金牛化工", "2026-11-25"), ("600103", "青山纸业", "2026-11-25"),
                    ("002242", "九阳股份", "2026-11-25"), ("002579", "中京电子", "2026-11-25")]
    for r in cold2.itertuples(index=False):
        snap_targets.append((r.code, f"{r.name}(冷门新票_{r.strategy})", r.buy_date))

    intuition_table = []
    for c6, nm, dt_q in snap_targets:
        row_s = oh_df[(oh_df["c6"] == c6) & (oh_df["dt"] == dt_q)]
        if row_s.empty:
            continue
        r = row_s.iloc[0]
        intuition_table.append({
            "code": c6, "name": nm, "query_date_T": dt_q,
            "list_age": int(r["list_age"]),
            "has_active_wave": int(r["has_active_wave"]),
            "curr_wave_streak": int(r["curr_wave_streak"]),
            "excl_curr_wave": {
                "waves_3y_g15": int(r["waves_3y_g15"]), "waves_5y_g15": int(r["waves_5y_g15"]),
                "active_years_3y": int(r["active_years_3y"]), "active_years_5y": int(r["active_years_5y"]),
                "zt_cnt_1y": int(r["zt_cnt_1y"]), "zt_cnt_3y": int(r["zt_cnt_3y"]), "zt_cnt_5y": int(r["zt_cnt_5y"]),
                "streak3_waves_5y": int(r["streak3_waves_5y"]), "streak5_waves_5y": int(r["streak5_waves_5y"]),
                "max_streak_5y": int(r["max_streak_5y"]),
                "cool_days_since_last_zt": None if pd.isna(r["cool_days_since_last_zt"]) else int(r["cool_days_since_last_zt"]),
                "cool_bin_zt": str(r["cool_bin_zt"]),
            },
            "strict_t1_control": {
                "zt_cnt_1y_t1": int(r["zt_cnt_1y_t1"]), "zt_cnt_3y_t1": int(r["zt_cnt_3y_t1"]),
                "waves_3y_g15_t1": int(r["waves_3y_g15_t1"]), "waves_5y_g15_t1": int(r["waves_5y_g15_t1"]),
            },
            "comm_and_chip_and_kpl": {
                "comm_posts_1y": int(r["comm_posts_1y"]), "comm_posts_1y_pct": round(float(r["comm_posts_1y_pct"]), 4),
                "comm_posts_3y": int(r["comm_posts_3y"]), "comm_posts_3y_pct": round(float(r["comm_posts_3y_pct"]), 4),
                "comm_active_month_ratio_1y": round(float(r["comm_active_month_ratio_1y"]), 3),
                "cum_turnover_1y": None if pd.isna(r["cum_turnover_1y"]) else round(float(r["cum_turnover_1y"]), 2),
                "trap_waves_3y": int(r["trap_waves_3y"]),
                "dd_from_1y_high": None if pd.isna(r["dd_from_1y_high"]) else round(float(r["dd_from_1y_high"]), 4),
                "kpl_unique_plates_3y": int(r["kpl_unique_plates_3y"]),
                "kpl_unique_plates_5y": int(r["kpl_unique_plates_5y"]),
                "kpl_plate_switch_ratio": None if pd.isna(r["kpl_plate_switch_ratio"]) else round(float(r["kpl_plate_switch_ratio"]), 3),
                "kpl_top_plate_share": None if pd.isna(r["kpl_top_plate_share"]) else round(float(r["kpl_top_plate_share"]), 3),
            },
        })

    # Load step1 truncation proof if present
    trunc_p = f"{OUT_DIR}/step1_truncation_proof.json"
    trunc_proof = json.load(open(trunc_p, encoding="utf-8")) if os.path.exists(trunc_p) else {}

    # Check pool-level Q8 completeness (overall warehouse & pools)
    oh_full_meta = ds.dataset(OLD_HOT_PQ, format="parquet").scanner().to_table()
    q8_warehouse = {
        "rows": int(oh_full_meta.num_rows),
        "cols": int(oh_full_meta.num_columns),
        "unique_stocks": int(oh_full_meta.column("c6").to_pandas().nunique()),
        "dt_min": str(oh_full_meta.column("dt").to_pandas().min()),
        "dt_max": str(oh_full_meta.column("dt").to_pandas().max()),
    }

    audit = {
        "truncation_proof_20241231": trunc_proof,
        "q8_warehouse_audit": q8_warehouse,
        "pools_audit": pool_audit,
        "temp5b_pending_next_open": pending_5b,
        "typical_stock_intuition_table": intuition_table,
        "output_files": {
            "warehouse": OLD_HOT_PQ,
            "unified_pools": uni_path,
            **{f"pool_{st}": pool_audit[st]["file"] for st in pool_audit},
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    audit_path = f"{OUT_DIR}/wave1_old_hot_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"[DONE Step2 in {time.time()-t0:.1f}s] Saved {audit_path}")


if __name__ == "__main__":
    main()
