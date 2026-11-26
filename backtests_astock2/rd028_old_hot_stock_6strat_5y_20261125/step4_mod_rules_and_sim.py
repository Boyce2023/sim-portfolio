#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD030 Wave 2B Module 1: Exact 6-strategy + V20.0 combined baseline parity,
fast precomputed daily MTM, 29 clean physical Old-Hot rules, and dynamic slot simulators.
Zero yfinance (D12). Zero cap10m. Read-only on production files.
"""
import json
import math
import os
import sys
from typing import Callable

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WORK_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
PARTC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
PARTC_V20 = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
PARTD_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partD_final_jianyan"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
TB1_DIR = f"{SIM}/output/rd025_cross_factor_fusion_20261125/trackB1_10cm_fusion"

for p in (PARTC_V20, TB1_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import tier_priority_engine as tpe
import trackB1_pools_and_sim as tb1

STRAT_ORDER = ["3to4", "high", "pry", "2to3", "1to2", "20cm"]
TRD_DAYS_YEAR = 242.0
S2C_MAP = {
    "3to4_S(>=102)": 1, "3to4_A(90-101)": 1,
    "high_S(>=96)": 2, "high_A(88-95)": 2,
    "pry_S(>=175)": 3, "pry_A(165-174)": 3,
    "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
    "1to2_S(>=340)": 5, "1to2_A(304.8-339.9)": 5, "1to2_FB(295-304.7)": 5,
    "20cm_S(>=82)": 6, "20cm_A(76-81)": 999,
}

# Weight grids per strategy scale
WEIGHT_GRIDS = {
    "1to2": [5, 10, 15, 20],
    "2to3": [3, 5, 8, 10],
    "3to4": [3, 5, 8, 10],
    "high": [3, 5, 8, 10],
    "pry": [3, 5, 8, 10],
    "20cm": [3, 5, 8, 10],
}

RULE_SPECS = [
    ("P01_short_cool30_pen", "penalty", "冷却<=30天扣分", "cool_days_since_last_zt<=30 -> -w"),
    ("P02_short_cool15_pen", "penalty", "超短冷却<=15天扣分", "cool_days_since_last_zt<=15 -> -w"),
    ("P03_waves3y_ge10_pen", "penalty", "3年>=10波极端老油条扣分", "waves_3y_g15>=10 -> -w"),
    ("P04_waves3y_ge8_pen", "penalty", "3年>=8波高频老热股扣分", "waves_3y_g15>=8 -> -w"),
    ("P05_zt1y_ge10_pen", "penalty", "近1年涨停>=10次扣分", "zt_cnt_1y>=10 -> -w"),
    ("P06_zt3y_ge20_pen", "penalty", "近3年涨停>=20次扣分", "zt_cnt_3y>=20 -> -w"),
    ("P07_comm_p85_pen", "penalty", "1年社区热度>=85%分位拥挤扣分", "comm_posts_1y_pct>=0.85 -> -w"),
    ("P08_comm_p90_pen", "penalty", "1年社区热度>=90%分位极挤扣分", "comm_posts_1y_pct>=0.90 -> -w"),
    ("P09_comm_actm_ge50_pen", "penalty", "全年>=50%月高讨论常驻盘扣分", "comm_active_month_ratio_1y>=0.50 -> -w"),
    ("P10_dd1y_le35_pen", "penalty", "距1年高点回撤>=35%套牢盘扣分", "dd_from_1y_high<=-0.35 -> -w"),
    ("P11_dd1y_le45_pen", "penalty", "距1年高点回撤>=45%深套扣分", "dd_from_1y_high<=-0.45 -> -w"),
    ("P12_trap3y_ge4_pen", "penalty", "3年坑人脉冲>=4次派发股扣分", "trap_waves_3y>=4 -> -w"),
    ("P13_kpl_cham6_pen", "penalty", "3年开盘啦>=6题材万能马甲扣分", "kpl_unique_plates_3y>=6 -> -w"),
    ("P14_kpl_switch75_pen", "penalty", "高频切换题材马甲扣分", "kpl_unique_plates_3y>=4 & switch>=0.75 -> -w"),
    ("P15_turn1y_ge15_pen", "penalty", "1年累计换手>=1500%过度博弈扣分", "cum_turnover_1y>=15 -> -w"),
    ("P16_hot_trap_combo_pen", "penalty", "高频+多坑+深套三重老油条扣分", "waves3y>=8 & trap3y>=3 & dd1y<=-0.25 -> -w"),
    ("B01_dormant180_bon", "bonus", "沉睡>180天老妖再起加分", "waves_3y_g15>=2 & cool>180d -> +w"),
    ("B02_dormant90_bon", "bonus", "沉睡>90天老妖再起加分", "waves_3y_g15>=2 & cool>90d -> +w"),
    ("B03_mid_waves2_6_bon", "bonus", "3年2-6波中频甜区加分", "2<=waves_3y_g15<=6 -> +w"),
    ("B04_clean_high_bon", "bonus", "高位无深套+适度股性加分", "dd1y>=-0.15 & 1<=waves3y<=7 -> +w"),
    ("B05_cold_stealth_bon", "bonus", "低讨论+有股性潜伏加分", "comm_1y_pct<=0.45 & zt_cnt_3y>=2 -> +w"),
    ("B06_focused_kpl_bon", "bonus", "开盘啦题材专一聚焦加分", "1<=kpl_plates_3y<=3 & top_share>=0.60 -> +w"),
    ("B07_fresh_cold_bon", "bonus", "低关注新面孔加分", "zt_cnt_3y<=2 & comm_1y_pct<=0.50 -> +w"),
    ("U01_waves_invU", "bidir", "波次倒U(2-6加分,>=10扣分)", "2-6:+w, >=10:-w"),
    ("U02_cool_bidir", "bidir", "冷却双向(>180老妖加分,<=30扣分)", "waves>=2 & cool>180:+w, cool<=30:-w"),
    ("U03_comm_bidir", "bidir", "热度双向(<=0.45加分,>=0.85扣分)", "comm<=0.45:+w, >=0.85:-w"),
    ("U04_trap_clean_bidir", "bidir", "套牢双向(无套加分,深套/多坑扣分)", "dd>=-0.15&trap<=1:+w, dd<=-0.35|trap>=4:-w"),
    ("U05_kpl_focus_vs_cham", "bidir", "马甲双向(专一加分,>=6题材扣分)", "1-3&top>=0.6:+w, >=6:-w"),
    ("U06_zt1y_invU", "bidir", "1年涨停倒U(1-5加分,>=10扣分)", "1<=zt1y<=5:+w, zt1y>=10:-w"),
]


def compute_rule_delta(df: pd.DataFrame, rule_id: str, w: float) -> np.ndarray:
    """Compute exact score delta array for a given rule_id and weight w (NaN-safe, strictly PIT)."""
    w = float(w)
    cool = df["cool_days_since_last_zt"].fillna(9999.0).to_numpy(float)
    has_cool = df["cool_days_since_last_zt"].notna().to_numpy(bool)
    w3 = df["waves_3y_g15"].fillna(0.0).to_numpy(float)
    z1 = df["zt_cnt_1y"].fillna(0.0).to_numpy(float)
    z3 = df["zt_cnt_3y"].fillna(0.0).to_numpy(float)
    cm = df["comm_posts_1y_pct"].fillna(0.5).to_numpy(float)
    cam = df["comm_active_month_ratio_1y"].fillna(0.0).to_numpy(float)
    dd1 = df["dd_from_1y_high"].fillna(0.0).to_numpy(float)
    tr3 = df["trap_waves_3y"].fillna(0.0).to_numpy(float)
    kp = df["kpl_unique_plates_3y"].fillna(0.0).to_numpy(float)
    ksw = df["kpl_plate_switch_ratio"].fillna(0.0).to_numpy(float)
    kts = df["kpl_top_plate_share"].fillna(0.0).to_numpy(float)
    turn1 = df["cum_turnover_1y"].fillna(0.0).to_numpy(float)

    if rule_id == "P01_short_cool30_pen":
        return np.where(has_cool & (cool <= 30.0), -w, 0.0)
    if rule_id == "P02_short_cool15_pen":
        return np.where(has_cool & (cool <= 15.0), -w, 0.0)
    if rule_id == "P03_waves3y_ge10_pen":
        return np.where(w3 >= 10.0, -w, 0.0)
    if rule_id == "P04_waves3y_ge8_pen":
        return np.where(w3 >= 8.0, -w, 0.0)
    if rule_id == "P05_zt1y_ge10_pen":
        return np.where(z1 >= 10.0, -w, 0.0)
    if rule_id == "P06_zt3y_ge20_pen":
        return np.where(z3 >= 20.0, -w, 0.0)
    if rule_id == "P07_comm_p85_pen":
        return np.where(cm >= 0.85, -w, 0.0)
    if rule_id == "P08_comm_p90_pen":
        return np.where(cm >= 0.90, -w, 0.0)
    if rule_id == "P09_comm_actm_ge50_pen":
        return np.where(cam >= 0.50, -w, 0.0)
    if rule_id == "P10_dd1y_le35_pen":
        return np.where(dd1 <= -0.35, -w, 0.0)
    if rule_id == "P11_dd1y_le45_pen":
        return np.where(dd1 <= -0.45, -w, 0.0)
    if rule_id == "P12_trap3y_ge4_pen":
        return np.where(tr3 >= 4.0, -w, 0.0)
    if rule_id == "P13_kpl_cham6_pen":
        return np.where(kp >= 6.0, -w, 0.0)
    if rule_id == "P14_kpl_switch75_pen":
        return np.where((kp >= 4.0) & (ksw >= 0.75), -w, 0.0)
    if rule_id == "P15_turn1y_ge15_pen":
        return np.where(turn1 >= 15.0, -w, 0.0)
    if rule_id == "P16_hot_trap_combo_pen":
        return np.where((w3 >= 8.0) & (tr3 >= 3.0) & (dd1 <= -0.25), -w, 0.0)
    if rule_id == "B01_dormant180_bon":
        return np.where((w3 >= 2.0) & has_cool & (cool > 180.0), w, 0.0)
    if rule_id == "B02_dormant90_bon":
        return np.where((w3 >= 2.0) & has_cool & (cool > 90.0), w, 0.0)
    if rule_id == "B03_mid_waves2_6_bon":
        return np.where((w3 >= 2.0) & (w3 <= 6.0), w, 0.0)
    if rule_id == "B04_clean_high_bon":
        return np.where((dd1 >= -0.15) & (w3 >= 1.0) & (w3 <= 7.0), w, 0.0)
    if rule_id == "B05_cold_stealth_bon":
        return np.where((cm <= 0.45) & (z3 >= 2.0), w, 0.0)
    if rule_id == "B06_focused_kpl_bon":
        return np.where((kp >= 1.0) & (kp <= 3.0) & (kts >= 0.60), w, 0.0)
    if rule_id == "B07_fresh_cold_bon":
        return np.where((z3 <= 2.0) & (cm <= 0.50), w, 0.0)
    if rule_id == "U01_waves_invU":
        return np.where((w3 >= 2.0) & (w3 <= 6.0), w, np.where(w3 >= 10.0, -w, 0.0))
    if rule_id == "U02_cool_bidir":
        return np.where((w3 >= 2.0) & has_cool & (cool > 180.0), w, np.where(has_cool & (cool <= 30.0), -w, 0.0))
    if rule_id == "U03_comm_bidir":
        return np.where(cm <= 0.45, w, np.where(cm >= 0.85, -w, 0.0))
    if rule_id == "U04_trap_clean_bidir":
        return np.where((dd1 >= -0.15) & (tr3 <= 1.0), w, np.where((dd1 <= -0.35) | (tr3 >= 4.0), -w, 0.0))
    if rule_id == "U05_kpl_focus_vs_cham":
        return np.where((kp >= 1.0) & (kp <= 3.0) & (kts >= 0.60), w, np.where(kp >= 6.0, -w, 0.0))
    if rule_id == "U06_zt1y_invU":
        return np.where((z1 >= 1.0) & (z1 <= 5.0), w, np.where(z1 >= 10.0, -w, 0.0))
    raise ValueError(f"Unknown rule_id: {rule_id}")


def load_calendars_and_bars(codes_needed: set[str]):
    raw = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300 = {k: float(v) for k, v in raw["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_full = [d for d in all_sh_dts if "2021-01-04" <= d <= "2026-11-25"]
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]

    cols = ["date", "ticker", "open", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-12-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp = pd.concat([da, dd], ignore_index=True)
    dp["c6"] = dp["ticker"].astype(str).str[:6]
    dp = dp[dp["c6"].isin(codes_needed) & dp["ticker"].astype(str).str.endswith((".SH", ".SZ"))].copy()
    dp["dt"] = dp["date"].dt.strftime("%Y-%m-%d")
    dp = dp.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dp["adjf"] = np.where((dp["close"] > 0) & (dp["adj_close"] > 0), dp["adj_close"] / dp["close"], 1.0)
    bar_lu = {
        (r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.qfq_factor), float(r.adjf))
        for r in dp.itertuples(index=False)
    }
    return sh300, all_sh_dts, cal_full, cal_5y, bar_lu


def precompute_mtm_segments(df: pd.DataFrame, cal_dts: list[str], dt_to_idx: dict, bar_lu: dict, is_20cm_adj: bool = False) -> list:
    """Precompute exact daily MTM segment multipliers matching build_daily_mtm_series."""
    T = len(cal_dts)
    segs_all = []
    px_col = "buy_px" if (is_20cm_adj and "buy_px" in df.columns) else "buy_price"
    for r in df.itertuples(index=False):
        if "sim_ok" in df.columns and not bool(r.sim_ok):
            segs_all.append(())
            continue
        bi = dt_to_idx.get(str(r.buy_date)[:10])
        ei = dt_to_idx.get(str(r.exit_date)[:10])
        if bi is None:
            segs_all.append(())
            continue
        c6 = str(r.code).zfill(6)
        bdt = str(r.buy_date)[:10]
        bb = bar_lu.get((c6, bdt))
        bp_val = getattr(r, px_col, np.nan)
        if is_20cm_adj and pd.notna(bp_val):
            b_adj = float(bp_val)
        elif (not is_20cm_adj) and pd.notna(bp_val) and bb is not None:
            b_adj = float(bp_val) * bb[4]
        elif bb is not None:
            b_adj = bb[1] * bb[4]
        else:
            b_adj = 1.0
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        segs = []
        for t in range(bi, end_loop):
            bt = bar_lu.get((c6, cal_dts[t]))
            cur_c = (bt[1] * bt[4]) if bt else last_c
            if cur_c <= 0:
                cur_c = last_c
            segs.append((t, cur_c / prev_v))
            prev_v, last_c = cur_c, cur_c
        if ei is not None and ei > bi:
            segs.append((ei, (b_adj * (1.0 + float(r.net_ret))) / prev_v))
        segs_all.append(tuple(segs))
    return segs_all


def daily_mtm_from_segs(df_tr: pd.DataFrame, T: int, mtm_col: str = "mtm_full") -> tuple[np.ndarray, float]:
    day_mult = np.ones(T, dtype=float)
    if df_tr.empty:
        return np.zeros(T, dtype=float), 0.0
    for segs in df_tr[mtm_col]:
        for t, mult in segs:
            day_mult[t] *= mult
    daily_r = day_mult - 1.0
    mtm_nav = float(np.prod(day_mult))
    tr_nav = float(np.prod(1.0 + df_tr["net_ret"].to_numpy(float)))
    return daily_r, abs(mtm_nav - tr_nav)


def load_pools_oldhot(cal_full: list[str], cal_5y: list[str], bar_lu: dict) -> dict[str, pd.DataFrame]:
    idx_full = {d: i for i, d in enumerate(cal_full)}
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    pools = {}
    for st in STRAT_ORDER:
        df = pd.read_parquet(f"{WORK_DIR}/pool_{st}_oldhot.parquet")
        df["code"] = df["code"].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        if st == "20cm":
            df["exit_hhmm"] = np.where(df["exit_reason"].astype(str).str.contains("open|gap|tp"), 1030, 1500)
            df["buy_price_val"] = df["buy_px"].astype(float)
            df["is_adj_px"] = True
        else:
            df["buy_price_val"] = df["buy_price"].astype(float)
            df["is_adj_px"] = False
        if st == "high":
            # Replicate V5.1 pre-deferral CB flag (000968 had +2.385% pre-deferral, 2025 losses were non-deferred <-2%)
            df["v51_cb_loss"] = (df["net_ret"].to_numpy(float) < -0.02) & (~df["dt_deferred"].to_numpy(bool))
        df["mtm_full"] = precompute_mtm_segments(df, cal_full, idx_full, bar_lu, is_20cm_adj=(st == "20cm"))
        df["mtm_5y"] = precompute_mtm_segments(df, cal_5y, idx_5y, bar_lu, is_20cm_adj=(st == "20cm"))
        pools[st] = df
    return pools


def load_untrig_with_oldhot() -> pd.DataFrame:
    """Load untriggered conditional order pool (3to4/high/1to2) and attach PIT old-hot features."""
    pool6_csv = pd.concat([
        tpe.load_strategy_csv("3to4", f"{PARTC_DIR}/ledger_3to4_v41_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("high", f"{PARTC_DIR}/ledger_high_v51_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("pry", f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("2to3", f"{PARTC_DIR}/ledger_2to3_v21_opt_std90_clean.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("1to2", f"{PARTA_DIR}/ledger_1to2_v20_cand.csv", "2021-11-16", "2026-11-16"),
        tpe.load_strategy_csv("20cm", f"{V11_DIR}/final_v11_ledger.csv", "2021-11-16", "2026-11-16"),
    ], ignore_index=True)
    ut = tpe.build_untriggered_baseline_pool(pool6_csv, "2021-11-16", "2026-11-16")
    codes = sorted(ut["code"].unique())
    dts = sorted(ut["buy_date"].unique())
    oh = ds.dataset(f"{WORK_DIR}/old_hot_6dim_stock_day_pit.parquet", format="parquet").scanner(
        filter=ds.field("c6").isin(codes) & ds.field("dt").isin(dts)
    ).to_table().to_pandas()
    oh["c6"] = oh["c6"].astype(str).str.zfill(6)
    oh["dt"] = oh["dt"].astype(str).str[:10]
    ut_m = ut.merge(oh, left_on=["code", "buy_date"], right_on=["c6", "dt"], how="left")
    ut_m["v20_score"] = ut_m["score"].astype(float)
    return ut_m


def sim_standalone(
    strat: str,
    df: pd.DataFrame,
    delta: np.ndarray,
    high_cb_mode: str = "v51_exact",
    cm20_thr: float = 82.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run standalone single-slot simulation for any of the 6 strategies with score delta."""
    if strat == "1to2":
        pass_df, slot_df = tb1.sim_1to2_v20(df, delta)
        return pass_df.copy(), slot_df.copy()

    sc_adj = df["v20_score"].to_numpy(float) + delta
    if strat == "20cm":
        m = sc_adj >= cm20_thr
        sub = df[m].copy()
        if sub.empty:
            return sub, sub
        sub["_sc_adj"] = sc_adj[m]
        srt = sub.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True])
        t_idx, fd = [], ""
        for r in srt.itertuples():
            if (not fd) or (r.buy_date > fd):
                t_idx.append(r.Index)
                fd = str(r.exit_date)
        return sub, srt.loc[t_idx].copy()

    if strat == "high":
        m = sc_adj >= 88.0
        sub = df[m].copy()
        if sub.empty:
            return sub, sub
        sub["_sc_adj"] = sc_adj[m]
        srt = sub.sort_values(["buy_date", "_sc_adj", "code"], ascending=[True, False, True])
        t_idx, fd, peo, cl, sk = [], "", False, 0, False
        for r in srt.itertuples():
            if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
                if high_cb_mode != "none" and sk:
                    fd, peo = str(r.exit_date), bool(r.eo)
                    if float(r.net_ret) > 0.0:
                        sk, cl = False, 0
                    continue
                t_idx.append(r.Index)
                fd, peo = str(r.exit_date), bool(r.eo)
                is_cb_loss = bool(r.v51_cb_loss) if high_cb_mode == "v51_exact" else (float(r.net_ret) < -0.02)
                if is_cb_loss:
                    cl += 1
                    sk = (cl >= 2)
                elif float(r.net_ret) > 0.0:
                    cl = 0
        return sub, srt.loc[t_idx].copy()

    return tb1.sim_strategy_slot(strat, df, delta)


def run_combined_v20(
    pools: dict[str, pd.DataFrame],
    untrig_base: pd.DataFrame,
    deltas: dict[str, np.ndarray],
    start_dt: str = "2021-11-16",
    end_dt: str = "2026-11-16",
    cm20_preslot_thr: float = 76.0,
    use_crosscheck_pass_pool: bool = False,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Exact V20.0 P3_S2C_STierReserveOnly combined 6-strategy single-slot engine.
    When deltas are all 0 and use_crosscheck_pass_pool=False, reproduces 278 trades (69,134,091.12x).
    """
    parts = []
    trig_dts_by_strat = {}
    for st in STRAT_ORDER:
        df = pools[st]
        d_vec = deltas.get(st, np.zeros(len(df), dtype=float))
        if st == "20cm":
            pass_df, slot_df = sim_standalone(st, df, d_vec, cm20_thr=cm20_preslot_thr)
            chosen = pass_df if use_crosscheck_pass_pool else slot_df
        else:
            pass_df, slot_df = sim_standalone(st, df, d_vec, high_cb_mode="v51_exact")
            chosen = pass_df if use_crosscheck_pass_pool else slot_df
        chosen = chosen[chosen["buy_date"].between(start_dt, end_dt)].copy()
        if chosen.empty:
            trig_dts_by_strat[st] = set()
            continue
        if st == "1to2":
            sc_s = chosen["_sc_adj"] if "_sc_adj" in chosen.columns else chosen["v20_score"]
            chosen["score"] = [round(float(x), 1) for x in sc_s]
        else:
            chosen["score"] = chosen["_sc_adj"] if "_sc_adj" in chosen.columns else chosen["v20_score"]
        chosen["tier"] = [tpe.assign_physical_tier(st, sc) for sc in chosen["score"]]
        chosen["is_untrig"] = False
        trig_dts_by_strat[st] = set(chosen["buy_date"])
        cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px",
            "is_untrig", "mtm_full", "mtm_5y",
        ]
        parts.append(chosen[cols])

    pool6 = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    # Dynamic untriggered conditional orders respecting modified scores on 3to4/high/1to2
    ut = untrig_base[untrig_base["buy_date"].between(start_dt, end_dt)].copy()
    if not ut.empty:
        ut_parts = []
        for st_u in ("3to4", "high", "1to2"):
            sub_u = ut[ut["strategy"] == st_u].copy()
            if sub_u.empty:
                continue
            sub_u = sub_u[~sub_u["buy_date"].isin(trig_dts_by_strat.get(st_u, set()))].copy()
            if sub_u.empty:
                continue
            # If rule modifies this strategy's scores, recompute score on untriggered rows too
            spec_rule = deltas.get(f"_rule_{st_u}")
            if spec_rule is not None:
                rid, w = spec_rule
                sub_u["score"] = sub_u["v20_score"].to_numpy(float) + compute_rule_delta(sub_u, rid, w)
            thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
            sub_u = sub_u[sub_u["score"] >= thr_u].copy()
            if not sub_u.empty:
                sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
                sub_u = sub_u.sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
                ut_parts.append(sub_u)
        if ut_parts:
            ut_final = pd.concat(ut_parts, ignore_index=True)
            ut_final["is_untrig"] = True
            ut_final["net_ret"] = 0.0
            ut_final["buy_price_val"] = np.nan
            ut_final["is_adj_px"] = False
            ut_cols = [
                "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
                "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig",
            ]
            ut_final = ut_final[ut_cols]
        else:
            ut_final = pd.DataFrame()
    else:
        ut_final = pd.DataFrame()

    # Keep _mtm lookup keyed by (strategy, buy_date, code)
    mtm_map = {}
    if not pool6.empty:
        for r in pool6.itertuples(index=False):
            mtm_map[(r.strategy, r.buy_date, r.code)] = (r.mtm_full, r.mtm_5y)
        p6_clean = pool6.drop(columns=["mtm_full", "mtm_5y"])
    else:
        p6_clean = pool6

    tr_df, waits = tpe.run_single_slot(
        p6_clean,
        lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(),
        untrig_df=ut_final,
        timing_mode="s_tier_reserve_only",
    )
    if not tr_df.empty:
        tr_df["mtm_full"] = [mtm_map[(r.strategy, r.buy_date, r.code)][0] for r in tr_df.itertuples(index=False)]
        tr_df["mtm_5y"] = [mtm_map[(r.strategy, r.buy_date, r.code)][1] for r in tr_df.itertuples(index=False)]
    return tr_df, waits


def verify_all_baselines(pools: dict[str, pd.DataFrame], untrig_base: pd.DataFrame) -> dict:
    """Assert 100% parity for all 6 standalone baselines + V20.0 combined (278 trades)."""
    refs = {
        "1to2": (f"{PARTA_DIR}/ledger_1to2_v20_cand.csv", "code", 92, 474.3511),
        "2to3": (f"{PARTC_DIR}/ledger_2to3_v21_opt_std90_clean.csv", "code", 95, 404.7082),
        "3to4": (f"{PARTC_DIR}/ledger_3to4_v41_clean.csv", "code", 95, 616.1818),
        "high": (f"{PARTC_DIR}/ledger_high_v51_clean.csv", "code", 42, 14.7494),
        "pry": (f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv", "code", 16, 2.4400),
        "20cm": (f"{V11_DIR}/final_v11_ledger_S82.csv", "c6", 199, 468.2894),
    }
    report = {}
    for st, (rpath, ccol, exp_n, exp_nav) in refs.items():
        ref = pd.read_csv(rpath, dtype={ccol: str})
        ref["code"] = ref[ccol].str.zfill(6)
        _, slot_df = sim_standalone(st, pools[st], np.zeros(len(pools[st])), high_cb_mode="v51_exact", cm20_thr=82.0)
        if st == "20cm":
            slot_s = slot_df.sort_values(["buy_date", "code"]).reset_index(drop=True)
            ref_s = ref.sort_values(["buy_date", "code"]).reset_index(drop=True)
        else:
            slot_s = slot_df.reset_index(drop=True)
            ref_s = ref.reset_index(drop=True)
        assert len(slot_s) == exp_n == len(ref_s), f"{st} len {len(slot_s)} != {exp_n}"
        assert list(zip(slot_s["buy_date"], slot_s["code"])) == list(zip(ref_s["buy_date"], ref_s["code"])), f"{st} sequence mismatch"
        max_diff = float(np.max(np.abs(slot_s["net_ret"].to_numpy(float) - ref_s["net_ret"].to_numpy(float))))
        nav = float(np.prod(1.0 + slot_s["net_ret"].to_numpy(float)))
        assert max_diff < 1e-6, f"{st} ret diff={max_diff}"
        report[st] = {
            "n": int(len(slot_s)), "expected_n": exp_n,
            "nav": round(nav, 4), "expected_nav": exp_nav,
            "max_abs_ret_diff": max_diff, "exact_match": True,
        }

    # Combined V20.0 P3_S2C_STierReserveOnly
    ref_comb = pd.read_csv(f"{PARTD_DIR}/ledger_combined_6strat_v20_slot1_clean.csv", dtype={"code": str})
    ref_comb["code"] = ref_comb["code"].str.zfill(6)
    tr_c, waits_c = run_combined_v20(pools, untrig_base, {})
    assert len(tr_c) == len(ref_comb) == 278, f"Combined len {len(tr_c)} != 278"
    assert list(zip(tr_c["buy_date"], tr_c["code"], tr_c["strategy"])) == list(zip(ref_comb["buy_date"], ref_comb["code"], ref_comb["strategy"]))
    c_diff = float(np.max(np.abs(tr_c["net_ret"].to_numpy(float) - ref_comb["net_ret"].to_numpy(float))))
    c_nav = float(np.prod(1.0 + tr_c["net_ret"].to_numpy(float)))
    assert c_diff < 1e-6, f"Combined ret diff={c_diff}"
    report["combined_v20"] = {
        "n": int(len(tr_c)), "expected_n": 278,
        "nav": round(c_nav, 4), "expected_nav": 69134091.1181,
        "max_abs_ret_diff": c_diff, "waits_count": int(len(waits_c)), "exact_match": True,
    }
    return report


def extract_trade_diffs(base_tr: pd.DataFrame, cand_tr: pd.DataFrame, strategy_label: str, rule_label: str) -> list[dict]:
    """Extract exact kicked vs newly added trades between baseline and candidate."""
    b_cols = ["buy_date", "code"] + (["strategy"] if "strategy" in base_tr.columns else [])
    b_map = {tuple(getattr(r, c) for c in b_cols): r for r in base_tr.itertuples(index=False)}
    c_map = {tuple(getattr(r, c) for c in b_cols): r for r in cand_tr.itertuples(index=False)}
    diffs = []
    for k in sorted(set(b_map.keys()) - set(c_map.keys())):
        r = b_map[k]
        diffs.append({
            "scope": strategy_label, "rule": rule_label, "action": "KICKED",
            "strategy": getattr(r, "strategy", strategy_label),
            "buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": getattr(r, "name", ""),
            "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
            "is_oos": r.buy_date >= "2025-01-01",
            "v20_score": round(float(getattr(r, "v20_score", getattr(r, "score", np.nan))), 2),
        })
    for k in sorted(set(c_map.keys()) - set(b_map.keys())):
        r = c_map[k]
        diffs.append({
            "scope": strategy_label, "rule": rule_label, "action": "ADDED",
            "strategy": getattr(r, "strategy", strategy_label),
            "buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": getattr(r, "name", ""),
            "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
            "is_oos": r.buy_date >= "2025-01-01",
            "v20_score": round(float(getattr(r, "v20_score", getattr(r, "score", np.nan))), 2),
        })
    return diffs
