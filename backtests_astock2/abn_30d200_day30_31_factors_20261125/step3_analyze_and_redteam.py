#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 3: Exhaustive Baseline Comparison (D30 Close vs D31 Open),
48-Factor Strictly PIT Scan (IS 2021-2023 vs OOS 2024-2026 vs 2026),
and 4-Gate Red-Team Audit (Single-slot + EW + Trim-Top-3 + 50bps slippage + HS300 excess).
"""

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from step1_extract_events_and_returns import OUT_DIR, load_indices


def hs300_period_ret(hs_s: pd.Series, start_dt: str, end_dt: str) -> float:
    sub = hs_s[(hs_s.index >= pd.Timestamp(start_dt)) & (hs_s.index <= pd.Timestamp(end_dt))]
    if len(sub) < 2:
        return np.nan
    return float((sub.iloc[-1] / sub.iloc[0] - 1.0) * 100.0)


def eval_portfolio_metrics(df_sub: pd.DataFrame, ret_col: str, entry_col: str, exit_col: str,
                           hs_s: pd.Series, period_start: str, period_end: str,
                           open_exit: bool = False, score_col: str = "end_dev30") -> dict:
    """Compute trade-level, daily-EW, single-slot rotation, trim-top-3, MDD, and HS300 excess."""
    d = df_sub.dropna(subset=[ret_col, exit_col]).copy()
    if len(d) == 0:
        return {"n": 0}

    vals = d[ret_col].values.astype(float)
    wins = vals[vals > 0]
    losses = vals[vals <= 0]
    wr = float(len(wins) / len(vals) * 100.0)
    po = float(wins.mean() / abs(losses.mean())) if len(wins) > 0 and len(losses) > 0 else np.nan
    mean_pct = float(vals.mean() * 100.0)
    med_pct = float(np.median(vals) * 100.0)

    # Trim top 3 trades
    if len(vals) > 3:
        vals_sorted = np.sort(vals)
        trim3_vals = vals_sorted[:-3]
        trim3_mean = float(trim3_vals.mean() * 100.0)
        trim3_cum = float((np.prod(1.0 + trim3_vals) - 1.0) * 100.0)
    else:
        trim3_mean = np.nan
        trim3_cum = np.nan

    # Daily Equal Weight
    ew_series = d.groupby(entry_col)[ret_col].mean().sort_index()
    ew_nav = (1.0 + ew_series).cumprod()
    ew_cum = float((ew_nav.iloc[-1] - 1.0) * 100.0)
    ew_mdd = float(((ew_nav / ew_nav.cummax()) - 1.0).min() * 100.0)

    # Single-slot zero-overlap rotation (deterministic PIT tie-break: score_col desc, then c6 asc)
    d_sorted = d.sort_values([entry_col, score_col, "c6"], ascending=[True, False, True])
    slot_rets = []
    slot_dates = []
    last_exit = "1900-01-01"
    for r in d_sorted.itertuples(index=False):
        ent = getattr(r, entry_col)
        ext = getattr(r, exit_col)
        if open_exit and entry_col == "d30_date":
            if ent < last_exit:
                continue
        else:
            if ent <= last_exit:
                continue
        slot_rets.append(float(getattr(r, ret_col)))
        slot_dates.append(ent)
        last_exit = ext

    s_arr = np.array(slot_rets, dtype=float)
    if len(s_arr) > 0:
        s_nav = np.cumprod(1.0 + s_arr)
        slot_cum = float((s_nav[-1] - 1.0) * 100.0)
        slot_mdd = float(np.min(s_nav / np.maximum.accumulate(s_nav) - 1.0) * 100.0)
        s_wins = s_arr[s_arr > 0]
        s_losses = s_arr[s_arr <= 0]
        slot_wr = float(len(s_wins) / len(s_arr) * 100.0)
        slot_po = float(s_wins.mean() / abs(s_losses.mean())) if len(s_wins) and len(s_losses) else np.nan
        if len(s_arr) > 3:
            s_trim3 = np.sort(s_arr)[:-3]
            slot_trim3_cum = float((np.prod(1.0 + s_trim3) - 1.0) * 100.0)
        else:
            slot_trim3_cum = np.nan
    else:
        slot_cum = slot_mdd = slot_wr = slot_po = slot_trim3_cum = np.nan

    hs_ret = hs300_period_ret(hs_s, period_start, period_end)
    return {
        "n": int(len(vals)),
        "ew_days": int(len(ew_series)),
        "wr": round(wr, 1),
        "po": round(po, 2) if pd.notna(po) else np.nan,
        "mean": round(mean_pct, 2),
        "med": round(med_pct, 2),
        "trim3_mean": round(trim3_mean, 2) if pd.notna(trim3_mean) else np.nan,
        "trim3_cum": round(trim3_cum, 1) if pd.notna(trim3_cum) else np.nan,
        "ew_cum": round(ew_cum, 1),
        "ew_mdd": round(ew_mdd, 1),
        "ew_excess": round(ew_cum - hs_ret, 1) if pd.notna(hs_ret) else np.nan,
        "slot_n": int(len(s_arr)),
        "slot_wr": round(slot_wr, 1) if pd.notna(slot_wr) else np.nan,
        "slot_po": round(slot_po, 2) if pd.notna(slot_po) else np.nan,
        "slot_cum": round(slot_cum, 1) if pd.notna(slot_cum) else np.nan,
        "slot_mdd": round(slot_mdd, 1) if pd.notna(slot_mdd) else np.nan,
        "slot_trim3_cum": round(slot_trim3_cum, 1) if pd.notna(slot_trim3_cum) else np.nan,
        "slot_excess": round(slot_cum - hs_ret, 1) if pd.notna(slot_cum) and pd.notna(hs_ret) else np.nan,
        "hs300_ret": round(hs_ret, 1) if pd.notna(hs_ret) else np.nan,
    }


def build_baseline_tables(df: pd.DataFrame, eb: pd.DataFrame, hs_s: pd.Series):
    """Part 1: Exhaustive D30 Close vs D31 Open Baseline across pools, horizons, and periods."""
    results = []

    pools = [
        ("10cm_peak165_D30c", df[(~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"]], "d30_date", "30c"),
        ("10cm_peak165_D30notYZ", df[(~df["is_20"]) & df["in_peak_pool"] & (~df["d30_yizi"])], "d30_date", "30c"),
        ("10cm_peak165_D31o", df[(~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"]], "d31_date", "31o"),
        ("10cm_end165_D30c", df[(~df["is_20"]) & df["in_end_pool"] & df["d30_buyable"]], "d30_date", "30c"),
        ("10cm_end165_D30notYZ", df[(~df["is_20"]) & df["in_end_pool"] & (~df["d30_yizi"])], "d30_date", "30c"),
        ("10cm_end165_D31o", df[(~df["is_20"]) & df["in_end_pool"] & df["d31_buyable"]], "d31_date", "31o"),
        ("10cm_end175_D30c", df[(~df["is_20"]) & df["in_end_pool"] & (df["end_dev30"] >= 175) & df["d30_buyable"]], "d30_date", "30c"),
        ("10cm_end175_D31o", df[(~df["is_20"]) & df["in_end_pool"] & (df["end_dev30"] >= 175) & df["d31_buyable"]], "d31_date", "31o"),
        # Apples-to-apples exact same sample (both D30c and D31o buyable)
        ("10cm_peak165_SAME_D30c", df[(~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"] & df["d31_buyable"]], "d30_date", "30c"),
        ("10cm_peak165_SAME_D31o", df[(~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"] & df["d31_buyable"]], "d31_date", "31o"),
        ("10cm_end165_SAME_D30c", df[(~df["is_20"]) & df["in_end_pool"] & df["d30_buyable"] & df["d31_buyable"]], "d30_date", "30c"),
        ("10cm_end165_SAME_D31o", df[(~df["is_20"]) & df["in_end_pool"] & df["d30_buyable"] & df["d31_buyable"]], "d31_date", "31o"),
        # 20cm ChiNext/STAR controls
        ("20cm_peak165_D30c", df[df["is_20"] & df["in_peak_pool"] & df["d30_buyable"]], "d30_date", "30c"),
        ("20cm_peak165_D31o", df[df["is_20"] & df["in_peak_pool"] & df["d31_buyable"]], "d31_date", "31o"),
        ("20cm_end165_D30c", df[df["is_20"] & df["in_end_pool"] & df["d30_buyable"]], "d30_date", "30c"),
        ("20cm_end165_D31o", df[df["is_20"] & df["in_end_pool"] & df["d31_buyable"]], "d31_date", "31o"),
        # Breach (>=200%) control group
        ("10cm_breach200_D30c", eb[(~eb["is_20"]) & eb["d30_buyable"]], "d30_date", "30c"),
        ("10cm_breach200_D31o", eb[(~eb["is_20"]) & eb["d31_buyable"]], "d31_date", "31o"),
    ]

    horizons_30c = [
        ("D31开", "r30c_d31o_f30", "exdt_30c_d31o", True),
        ("D31收(T+1)", "r30c_d31c_f30", "exdt_30c_d31c", False),
        ("D32收(T+2)", "r30c_d32c_f30", "exdt_30c_d32c", False),
        ("D33收(T+3)", "r30c_d33c_f30", "exdt_30c_d33c", False),
        ("D35收(T+5)", "r30c_d35c_f30", "exdt_30c_d35c", False),
        ("D40收(T+10)", "r30c_d40c_f30", "exdt_30c_d40c", False),
        ("D50收(T+20)", "r30c_d50c_f30", "exdt_30c_d50c", False),
    ]
    horizons_31o = [
        ("D31收(T0违规)", "r31o_d31c_t0diag_f30", "d31_date", False),
        ("D32开(T+1)", "r31o_d32o_f30", "exdt_31o_d32o", True),
        ("D32收(T+1)", "r31o_d32c_f30", "exdt_31o_d32c", False),
        ("D33收(T+2)", "r31o_d33c_f30", "exdt_31o_d33c", False),
        ("D35收(T+4)", "r31o_d35c_f30", "exdt_31o_d35c", False),
        ("D40收(T+9)", "r31o_d40c_f30", "exdt_31o_d40c", False),
        ("D50收(T+19)", "r31o_d50c_f30", "exdt_31o_d50c", False),
    ]

    periods = [
        ("ALL_21_26", "2021-01-04", "2026-11-24"),
        ("IS_21_23", "2021-01-04", "2023-12-29"),
        ("OOS_24_26", "2024-01-02", "2026-11-24"),
        ("Y2026", "2026-01-05", "2026-11-24"),
    ]

    for p_nm, p_df, ent_col, mode in pools:
        h_list = horizons_30c if mode == "30c" else horizons_31o
        for h_nm, r_col, ex_col, is_op in h_list:
            for per_nm, p_lo, p_hi in periods:
                sub = p_df[(p_df[ent_col] >= p_lo) & (p_df[ent_col] <= p_hi)]
                m = eval_portfolio_metrics(sub, r_col, ent_col, ex_col, hs_s, p_lo, p_hi, open_exit=is_op)
                m.update({"pool": p_nm, "horizon": h_nm, "period": per_nm})
                results.append(m)

    res_df = pd.DataFrame(results)
    res_df.to_csv(OUT_DIR / "part1_baseline_comparison.csv", index=False)
    return res_df


def define_binary_factors(df: pd.DataFrame) -> list[tuple[str, str, pd.Series]]:
    """Define 48+ strictly PIT binary/categorical factor tests with clean physical meaning."""
    f = []
    # Group A: Theme & Echelon (<= D29 strictly lagged + D30 live)
    f.append(("A01_kpl_in_1d_d29", "D29在KPL真实题材涨停池", df["kpl_in_1d_d29"]))
    f.append(("A02_kpl_in_3d_d29", "近3日(D27-29)在KPL真实题材池", df["kpl_in_3d_d29"]))
    f.append(("A03_kpl_in_5d_d29", "近5日(D25-29)在KPL真实题材池", df["kpl_in_5d_d29"]))
    f.append(("A04_kpl_in_10d_d29", "近10日在KPL真实题材池", df["kpl_in_10d_d29"]))
    f.append(("A05_has_real_theme_d29", "有非NON_THEME真实题材归属(<=D29)", df["has_real_theme_d29"]))
    f.append(("A06_kpl_days_30d_ge3", "波段内KPL上榜天数>=3天(<=D29)", df["kpl_days_30d_d29"] >= 3))
    f.append(("A07_theme_zt_d29_ge1", "D29同题材KPL涨停>=1家", df["theme_zt_d29"] >= 1))
    f.append(("A08_theme_zt_d29_ge2", "D29同题材KPL涨停>=2家", df["theme_zt_d29"] >= 2))
    f.append(("A09_theme_zt_d29_ge3", "D29同题材KPL涨停>=3家", df["theme_zt_d29"] >= 3))
    f.append(("A10_theme_zt_5d_ge5", "近5日(D25-29)同题材累计涨停>=5家", df["theme_zt_5d_d29"] >= 5))
    f.append(("A11_theme_trend_up_d29", "题材近3日涨停趋势上升(vs前5日)", df["theme_trend_up_d29"]))
    f.append(("A12_theme_low_assist_d29", "D29同题材有低位首二板助攻", df["theme_low_assist_d29"]))
    f.append(("A13_is_theme_leader_d29", "题材内20日涨幅最高龙头(D29)", df["is_theme_leader_d29"]))
    f.append(("A14_theme_zt_d30_live_ge1", "D30当日(PIT题材成员)涨停助攻>=1家", df["theme_zt_d30_live"] >= 1))
    f.append(("A15_theme_zt_d30_live_ge2", "D30当日(PIT题材成员)涨停助攻>=2家", df["theme_zt_d30_live"] >= 2))
    f.append(("A16_theme_low_assist_d30", "D30当日同题材有首二板低位助攻", df["theme_low_assist_d30"]))
    f.append(("A17_kpl_theme_zt_d30_ge3", "D30KPL同题材涨停>=3家(D31买可用)", df["kpl_theme_zt_d30"] >= 3))

    # Group B: 30d Abnormality Structure & Price-Volume Control
    f.append(("B01_end_dev_ge170", "D30偏离度>=170%(紧贴红线)", df["end_dev30"] >= 170.0))
    f.append(("B02_end_dev_ge175", "D30偏离度>=175%(极贴红线)", df["end_dev30"] >= 175.0))
    f.append(("B03_end_dev_ge180", "D30偏离度>=180%", df["end_dev30"] >= 180.0))
    f.append(("B04_relief_1d_ge10", "D31单日滚出空间>=10pp", df["relief_1d_pp"] >= 10.0))
    f.append(("B05_relief_1d_ge15", "D31单日滚出空间>=15pp", df["relief_1d_pp"] >= 15.0))
    f.append(("B06_relief_3d_ge20", "D31-33三日PIT滚出空间>=20pp", df["relief_3d_pp"] >= 20.0))
    f.append(("B07_relief_3d_ge30", "D31-33三日PIT滚出空间>=30pp", df["relief_3d_pp"] >= 30.0))
    f.append(("B08_dd30_tight_lt5", "D30距峰回撤<5%(强横盘控盘)", df["dd_at_d30"] >= -5.0))
    f.append(("B09_dd30_mod_lt10", "D30距峰回撤<10%", df["dd_at_d30"] >= -10.0))
    f.append(("B10_d30_neg_washout", "D30当日收跌(<0%,主动控异动阴洗)", df["d30_pct"] < 0.0))
    f.append(("B11_d30_small_pos", "D30小涨(0%~+5%,温和控盘)", (df["d30_pct"] >= 0.0) & (df["d30_pct"] <= 5.0)))
    f.append(("B12_d30_big_drop", "D30大跌(<-3%,主动深砸躲异动)", df["d30_pct"] < -3.0))
    f.append(("B13_d30_is_yang", "D30收阳线(C>O)", df["d30_is_yang"]))
    f.append(("B14_d30_is_true_yin", "D30真阴线(C<O且跌)", df["d30_is_true_yin"]))
    f.append(("B15_box5_tight_lt10", "近5日收盘箱体振幅<10%", df["box5_range"] < 10.0))
    f.append(("B16_amp5_tight_lt6", "近5日日均振幅<6%", df["amp5_avg"] < 6.0))
    f.append(("B17_vol_shrink_lt08", "5日/20日缩量比<0.8(明显缩量)", df["vol_shrink_5_20"] < 0.8))
    f.append(("B18_vol_d30_shrink_lt08", "D30当日缩量(量<前5日均0.8倍)", df["vol_d30_to_5"] < 0.8))
    f.append(("B19_turn_mid_5_15", "D30换手率5%~15%", (df["d30_turn_pct"] >= 5.0) & (df["d30_turn_pct"] <= 15.0)))
    f.append(("B20_turn_low_lt8", "D30换手率<8%(低换手锁仓)", df["d30_turn_pct"] < 8.0))
    f.append(("B21_above_ma5", "D30收盘站上MA5", df["above_ma5"]))
    f.append(("B22_above_ma10", "D30收盘站上MA10", df["above_ma10"]))
    f.append(("B23_streak_ge3_demon", "30日内有过>=3连板妖股基因", df["max_streak_30d"] >= 3))
    f.append(("B24_streak_le2_trend", "30日内无>=3连板(纯趋势爬坡)", df["max_streak_30d"] <= 2))
    f.append(("B25_recent_zt_le3d", "距最近一次涨停<=3个交易日", df["days_since_last_zt"] <= 3))
    f.append(("B26_d30_touch_zt_fail", "D30盘中触及涨停但未封死(炸板躲异动)", df["d30_touch_zt_unsealed"]))
    f.append(("B27_ret5_flat_lt10", "近5日涨幅<10%(横盘等时间换空间)", df["d30_ret_5d"] < 10.0))

    # Group C: Cap, Chips, Notices, LHB, Market Environment
    f.append(("C01_mcap_lt50", "流通/总市值<50亿", df["mcap_yi"] < 50.0))
    f.append(("C02_mcap_ge80", "市值>=80亿(中大盘容量)", df["mcap_yi"] >= 80.0))
    f.append(("C03_price_lt20", "D30股价<20元", df["d30_close_raw"] < 20.0))
    f.append(("C04_amt_ge5yi", "D30成交额>=5亿元", df["d30_amount_yi"] >= 5.0))
    f.append(("C05_no_reg_inq_30d", "30日内无问询/监管/关注/立案函", df["reg_inquiry_30d"] == 0))
    f.append(("C06_abn_notice_ge2", "30日内发过>=2次异动/风险提示公告", df["reg_abn_cnt_30d"] >= 2))
    f.append(("C07_no_susp_30d", "30日内无停牌核查历史", df["had_susp_30d"] == 0))
    f.append(("C08_lhb_5d_any_d29", "D25-D29上过龙虎榜", df["lhb_cnt_5d_d29"] >= 1))
    f.append(("C09_lhb_inst_net_pos_d29", "D25-D29龙虎榜机构净买入>0", df["lhb_inst_net_5d_d29"] > 0.0))
    f.append(("C10_lhb_no_lasa_d29", "D25-D29龙虎榜无拉萨或拉萨占比<20%", df["lhb_lasa_ratio_5d_d29"].fillna(0.0) < 0.20))
    f.append(("C11_lhb_yz_net_pos_d29", "D25-D29知名游资净买入>0", df["lhb_famous_yz_net_5d_d29"] > 0.0))
    f.append(("C12_lhb_d30_inst_pos_d31", "D30当日龙虎榜机构净买>0(D31买可用)", df["lhb_d30_inst_net"].fillna(0.0) > 0.0))
    f.append(("C13_mkt_zt_ge60_d30", "D30全市场涨停>=60家(情绪强)", df["mkt_zt_cnt_d30"] >= 60))
    f.append(("C14_mkt_dt_le10_d30", "D30全市场跌停<=10家(低恐慌)", df["mkt_dt_cnt_d30"] <= 10))
    f.append(("C15_mkt_amt_ge1p2T", "D30全市场成交额>=1.2万亿(放量牛市)", df["mkt_amt_tril_d30"] >= 1.2))
    f.append(("C16_mkt_amt_ge1p5T", "D30全市场成交额>=1.5万亿", df["mkt_amt_tril_d30"] >= 1.5))
    f.append(("C17_hs300_5d_pos", "沪深300近5日收红(>0%)", df["hs300_ret5_d30"] > 0.0))
    f.append(("C18_hs300_20d_pos", "沪深300近20日趋势向上(>0%)", df["hs300_ret20_d30"] > 0.0))
    f.append(("C19_d30_fri", "D30为周五(周末消化出笼)", df["d30_weekday"] == 4))
    f.append(("C20_top10_lock_ge45", "十大流通锁仓>=45%(有覆盖样本)", df["top10_free_lock_pct"] >= 45.0))
    return f


def scan_factors(df: pd.DataFrame):
    """Part 2: Scan all 60+ binary conditions & continuous correlations across IS vs OOS vs 2026."""
    f_list = define_binary_factors(df)
    scan_configs = [
        ("10cm_peak_D30c", (~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"], "d30_date",
         [("D31开", "r30c_d31o_f30"), ("D31收", "r30c_d31c_f30"), ("D32收", "r30c_d32c_f30"), ("D35收", "r30c_d35c_f30")]),
        ("10cm_peak_D31o", (~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"], "d31_date",
         [("D32收", "r31o_d32c_f30"), ("D33收", "r31o_d33c_f30"), ("D35收", "r31o_d35c_f30"), ("D40收", "r31o_d40c_f30")]),
        ("10cm_end165_D30c", (~df["is_20"]) & df["in_end_pool"] & df["d30_buyable"], "d30_date",
         [("D31开", "r30c_d31o_f30"), ("D31收", "r30c_d31c_f30"), ("D32收", "r30c_d32c_f30"), ("D35收", "r30c_d35c_f30")]),
        ("10cm_end165_D31o", (~df["is_20"]) & df["in_end_pool"] & df["d31_buyable"], "d31_date",
         [("D32收", "r31o_d32c_f30"), ("D33收", "r31o_d33c_f30"), ("D35收", "r31o_d35c_f30")]),
        ("20cm_peak_D30c", df["is_20"] & df["in_peak_pool"] & df["d30_buyable"], "d30_date",
         [("D31开", "r30c_d31o_f30"), ("D31收", "r30c_d31c_f30"), ("D32收", "r30c_d32c_f30")]),
        ("20cm_peak_D31o", df["is_20"] & df["in_peak_pool"] & df["d31_buyable"], "d31_date",
         [("D32收", "r31o_d32c_f30"), ("D33收", "r31o_d33c_f30"), ("D35收", "r31o_d35c_f30")]),
    ]

    rows = []
    for cfg_nm, base_mask, ent_col, h_list in scan_configs:
        sub_base = df[base_mask].copy()
        is_m = sub_base[ent_col] <= "2023-12-31"
        oos_m = sub_base[ent_col] >= "2024-01-01"
        y26_m = sub_base[ent_col] >= "2026-01-01"
        for f_code, f_desc, cond_full in f_list:
            cond = cond_full.reindex(sub_base.index).fillna(False).astype(bool)
            # For top10_free_lock_pct, exclude NaNs from False group
            if f_code == "C20_top10_lock_ge45":
                valid_m = sub_base["top10_free_lock_pct"].notna()
            else:
                valid_m = pd.Series(True, index=sub_base.index)
            for h_nm, r_col in h_list:
                r = sub_base[r_col]
                v_is = valid_m & is_m & r.notna()
                v_oos = valid_m & oos_m & r.notna()
                v_26 = valid_m & y26_m & r.notna()

                t_is = r[v_is & cond]
                f_is = r[v_is & (~cond)]
                t_oos = r[v_oos & cond]
                f_oos = r[v_oos & (~cond)]
                t_26 = r[v_26 & cond]

                if len(t_is) < 3 or len(t_oos) < 3 or len(f_is) < 3 or len(f_oos) < 3:
                    continue

                m_t_is, m_f_is = float(t_is.mean() * 100), float(f_is.mean() * 100)
                m_t_oos, m_f_oos = float(t_oos.mean() * 100), float(f_oos.mean() * 100)
                sp_is = m_t_is - m_f_is
                sp_oos = m_t_oos - m_f_oos
                m_t_26 = float(t_26.mean() * 100) if len(t_26) > 0 else np.nan
                wr_is = float((t_is > 0).mean() * 100)
                wr_oos = float((t_oos > 0).mean() * 100)
                wr_26 = float((t_26 > 0).mean() * 100) if len(t_26) > 0 else np.nan

                same_dir_pos = (sp_is > 0 and sp_oos > 0)
                same_dir_neg = (sp_is < 0 and sp_oos < 0)
                all_pos = (m_t_is > 0 and m_t_oos > 0 and (pd.isna(m_t_26) or m_t_26 > 0))
                rows.append({
                    "config": cfg_nm, "horizon": h_nm, "ret_col": r_col, "ent_col": ent_col,
                    "factor": f_code, "desc": f_desc,
                    "n_IS": int(len(t_is)), "n_OOS": int(len(t_oos)), "n_2026": int(len(t_26)),
                    "mean_T_IS": round(m_t_is, 2), "mean_F_IS": round(m_f_is, 2), "spread_IS": round(sp_is, 2),
                    "mean_T_OOS": round(m_t_oos, 2), "mean_F_OOS": round(m_f_oos, 2), "spread_OOS": round(sp_oos, 2),
                    "mean_T_2026": round(m_t_26, 2) if pd.notna(m_t_26) else np.nan,
                    "wr_T_IS": round(wr_is, 1), "wr_T_OOS": round(wr_oos, 1),
                    "wr_T_2026": round(wr_26, 1) if pd.notna(wr_26) else np.nan,
                    "same_dir_pos": bool(same_dir_pos),
                    "same_dir_neg": bool(same_dir_neg),
                    "all_periods_pos": bool(all_pos),
                })

    scan_df = pd.DataFrame(rows)
    scan_df.to_csv(OUT_DIR / "part2_single_factor_scan.csv", index=False)

    # Also continuous Spearman correlation scan for key numeric features on 10cm_peak_D30c & D31o
    num_cols = [
        "end_dev30", "peak_dev30", "relief_1d_pp", "relief_3d_pp", "dd_at_d30",
        "d30_pct", "amp5_avg", "box5_range", "vol_shrink_5_20", "vol_d30_to_5",
        "d30_turn_pct", "dist_ma5_pct", "max_streak_30d", "zt_days_30d", "days_since_last_zt",
        "d30_ret_5d", "mcap_yi", "d30_close_raw", "d30_amount_yi",
        "theme_zt_d29", "theme_zt_5d_d29", "theme_zt_d30_live", "kpl_theme_zt_d30",
        "reg_abn_cnt_30d", "lhb_inst_net_5d_d29", "lhb_lasa_ratio_5d_d29",
        "mkt_zt_cnt_d30", "mkt_dt_cnt_d30", "mkt_amt_tril_d30", "hs300_ret5_d30", "hs300_ret20_d30",
    ]
    corr_rows = []
    for cfg_nm, base_mask, ent_col, h_list in scan_configs[:4]:
        sub_base = df[base_mask].copy()
        is_m = sub_base[ent_col] <= "2023-12-31"
        oos_m = sub_base[ent_col] >= "2024-01-01"
        for h_nm, r_col in h_list[:3]:
            for nc in num_cols:
                a_is = sub_base.loc[is_m, [nc, r_col]].dropna()
                a_oos = sub_base.loc[oos_m, [nc, r_col]].dropna()
                if len(a_is) < 8 or len(a_oos) < 10:
                    continue
                rho_is, p_is = spearmanr(a_is[nc], a_is[r_col])
                rho_oos, p_oos = spearmanr(a_oos[nc], a_oos[r_col])
                if pd.notna(rho_is) and pd.notna(rho_oos):
                    corr_rows.append({
                        "config": cfg_nm, "horizon": h_nm, "feature": nc,
                        "n_IS": len(a_is), "n_OOS": len(a_oos),
                        "rho_IS": round(float(rho_is), 3), "p_IS": round(float(p_is), 3),
                        "rho_OOS": round(float(rho_oos), 3), "p_OOS": round(float(p_oos), 3),
                        "same_sign": (rho_is * rho_oos > 0),
                    })
    corr_df = pd.DataFrame(corr_rows)
    corr_df.to_csv(OUT_DIR / "part2_continuous_spearman.csv", index=False)
    return scan_df, corr_df


def run_redteam_audit_on_combos(df: pd.DataFrame, scan_df: pd.DataFrame, hs_s: pd.Series):
    """Part 3: Construct simple orthogonal IS-grounded combos & run 4 strict Red-Team gates."""
    f_dict = {code: cond for code, _, cond in define_binary_factors(df)}

    # Define candidate orthogonal combos & additive scorecard based on physical hypotheses
    # (Explicitly test pre-registered hypotheses + IS-consistent factors without p-hacking)
    candidates = [
        # (name, entry_mode, base_mask, cond_mask, horizon_nm, ret30_col, ret50_col, exit_col, open_exit)
        ("C1_10cm_D30c_RealTheme_Relief10_NoDrop", "D30尾盘买",
         (~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"],
         f_dict["A05_has_real_theme_d29"] & f_dict["B04_relief_1d_ge10"] & (df["d30_pct"] > -3.0),
         "D32收(T+2)", "r30c_d32c_f30", "r30c_d32c_f50", "exdt_30c_d32c", False),

        ("C2_10cm_D30c_ThemeZT2_Relief10", "D30尾盘买",
         (~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"],
         f_dict["A08_theme_zt_d29_ge2"] & f_dict["B04_relief_1d_ge10"],
         "D32收(T+2)", "r30c_d32c_f30", "r30c_d32c_f50", "exdt_30c_d32c", False),

        ("C3_10cm_D30c_Shrink_NoStreak_MktBull", "D30尾盘买",
         (~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"],
         f_dict["B17_vol_shrink_lt08"] & f_dict["B24_streak_le2_trend"] & f_dict["C15_mkt_amt_ge1p2T"],
         "D32收(T+2)", "r30c_d32c_f30", "r30c_d32c_f50", "exdt_30c_d32c", False),

        ("C4_10cm_D31o_ThemeZT2_Relief10", "D31开盘买",
         (~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"],
         f_dict["A08_theme_zt_d29_ge2"] & f_dict["B04_relief_1d_ge10"],
         "D32收(T+1)", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),

        ("C5_10cm_D31o_D30ThemeLive_NoRegInq", "D31开盘买",
         (~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"],
         f_dict["A14_theme_zt_d30_live_ge1"] & f_dict["C05_no_reg_inq_30d"] & f_dict["B04_relief_1d_ge10"],
         "D32收(T+1)", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),

        ("C6_10cm_D31o_LowLasa_AboveMA5_Theme", "D31开盘买",
         (~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"],
         f_dict["C10_lhb_no_lasa_d29"] & f_dict["B21_above_ma5"] & f_dict["A03_kpl_in_5d_d29"],
         "D32收(T+1)", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),

        ("C7_10cm_D31o_End165_Shrink_Theme", "D31开盘买",
         (~df["is_20"]) & df["in_end_pool"] & df["d31_buyable"],
         f_dict["B17_vol_shrink_lt08"] & f_dict["A05_has_real_theme_d29"],
         "D32收(T+1)", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),

        ("C8_20cm_D31o_ThemeAssist_Relief10", "D31开盘买(20cm)",
         df["is_20"] & df["in_peak_pool"] & df["d31_buyable"],
         f_dict["A14_theme_zt_d30_live_ge1"] & f_dict["B04_relief_1d_ge10"],
         "D32收(T+1)", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
    ]

    # Also auto-generate best IS-consistent scorecards (1pt per factor with spread_IS >= +2.0% and n_IS >= 6, NO OOS peaking!)
    # Strictly select factors from IS ONLY, then blind-test on OOS & 2026!
    for cfg_nm, ent_col, base_m, h_nm, r30, r50, ex_col, is_op in [
        ("10cm_peak_D30c", "d30_date", (~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"], "D32收", "r30c_d32c_f30", "r30c_d32c_f50", "exdt_30c_d32c", False),
        ("10cm_peak_D30c", "d30_date", (~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"], "D31开", "r30c_d31o_f30", "r30c_d31o_f50", "exdt_30c_d31o", True),
        ("10cm_peak_D31o", "d31_date", (~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"], "D32收", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("10cm_peak_D31o", "d31_date", (~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"], "D35收", "r31o_d35c_f30", "r31o_d35c_f50", "exdt_31o_d35c", False),
        ("20cm_peak_D31o", "d31_date", df["is_20"] & df["in_peak_pool"] & df["d31_buyable"], "D32收", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
    ]:
        # Pick top 4 strictly IS-selected orthogonal factors (largest spread_IS with n_IS >= 8)
        sub_s = scan_df[(scan_df["config"] == cfg_nm) & (scan_df["horizon"] == h_nm) & (scan_df["n_IS"] >= 8) & (scan_df["spread_IS"] > 1.5)]
        sub_s = sub_s.sort_values("spread_IS", ascending=False)
        picked = []
        used_grp = set()
        for rr in sub_s.itertuples(index=False):
            grp_prefix = rr.factor[:3]
            if grp_prefix not in used_grp or len(picked) < 4:
                picked.append(rr.factor)
                used_grp.add(grp_prefix)
            if len(picked) >= 4:
                break
        if len(picked) >= 2:
            sc_vec = sum(f_dict[p].fillna(False).astype(int) for p in picked)
            for thr in (2, 3):
                candidates.append((
                    f"IS_Score_{cfg_nm}_{h_nm}_ge{thr}({'+'.join(p[:3] for p in picked)})",
                    cfg_nm, base_m, sc_vec >= thr, h_nm, r30, r50, ex_col, is_op
                ))

    # Also test pairs of two-period consistent factors (explicitly marked as Post-Scan Discovery for audit)
    for cfg_nm, ent_col, base_m, h_nm, r30, r50, ex_col, is_op in [
        ("10cm_peak_D30c", "d30_date", (~df["is_20"]) & df["in_peak_pool"] & df["d30_buyable"], "D32收", "r30c_d32c_f30", "r30c_d32c_f50", "exdt_30c_d32c", False),
        ("10cm_peak_D31o", "d31_date", (~df["is_20"]) & df["in_peak_pool"] & df["d31_buyable"], "D32收", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("10cm_end165_D31o", "d31_date", (~df["is_20"]) & df["in_end_pool"] & df["d31_buyable"], "D32收", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
        ("20cm_peak_D31o", "d31_date", df["is_20"] & df["in_peak_pool"] & df["d31_buyable"], "D32收", "r31o_d32c_f30", "r31o_d32c_f50", "exdt_31o_d32c", False),
    ]:
        both_pos = scan_df[(scan_df["config"] == cfg_nm) & (scan_df["horizon"] == h_nm) & (scan_df["same_dir_pos"]) & (scan_df["n_IS"] >= 6) & (scan_df["n_OOS"] >= 8)]
        both_pos = both_pos.sort_values("spread_IS", ascending=False)
        top_f = both_pos["factor"].tolist()[:3]
        if len(top_f) >= 2:
            candidates.append((
                f"Audit2F_{cfg_nm}_{h_nm}({top_f[0][:8]}&{top_f[1][:8]})",
                cfg_nm, base_m, f_dict[top_f[0]].fillna(False) & f_dict[top_f[1]].fillna(False),
                h_nm, r30, r50, ex_col, is_op
            ))
        for tf in top_f[:2]:
            candidates.append((
                f"SingleBest_{cfg_nm}_{h_nm}({tf[:16]})",
                cfg_nm, base_m, f_dict[tf].fillna(False),
                h_nm, r30, r50, ex_col, is_op
            ))

    audit_rows = []
    for name, mode, base_m, cond_m, h_nm, r30, r50, ex_col, is_op in candidates:
        ent_col = "d30_date" if "d30" in r30[:4] else "d31_date"
        sub = df[base_m & cond_m].copy()
        if len(sub) < 5:
            continue
        m_all = eval_portfolio_metrics(sub, r30, ent_col, ex_col, hs_s, "2021-01-04", "2026-11-24", open_exit=is_op)
        m_is = eval_portfolio_metrics(sub[sub[ent_col] <= "2023-12-31"], r30, ent_col, ex_col, hs_s, "2021-01-04", "2023-12-29", open_exit=is_op)
        m_oos = eval_portfolio_metrics(sub[sub[ent_col] >= "2024-01-01"], r30, ent_col, ex_col, hs_s, "2024-01-02", "2026-11-24", open_exit=is_op)
        m_26 = eval_portfolio_metrics(sub[sub[ent_col] >= "2026-01-01"], r30, ent_col, ex_col, hs_s, "2026-01-05", "2026-11-24", open_exit=is_op)
        m_50 = eval_portfolio_metrics(sub, r50, ent_col, ex_col, hs_s, "2021-01-04", "2026-11-24", open_exit=is_op)

        g1_3periods_pos = (
            m_is.get("n", 0) >= 4 and m_oos.get("n", 0) >= 6 and m_26.get("n", 0) >= 2
            and m_is.get("mean", -99) > 0 and m_oos.get("mean", -99) > 0 and m_26.get("mean", -99) > 0
            and m_is.get("slot_cum", -99) > 0 and m_oos.get("slot_cum", -99) > 0 and m_26.get("slot_cum", -99) > 0
        )
        g2_beat_hs300 = (
            m_all.get("slot_excess", -999) > 0 and m_all.get("ew_excess", -999) > 0
            and m_oos.get("slot_excess", -999) > 0 and m_oos.get("ew_excess", -999) > 0
        )
        g3_trim3_pos = (
            (m_all.get("trim3_mean", -99) > 0) and (m_all.get("slot_trim3_cum", -99) > 0)
        )
        g4_slip50_pos = (
            (m_50.get("mean", -99) > 0) and (m_50.get("slot_cum", -99) > 0) and (m_50.get("ew_cum", -99) > 0)
        )
        pass_all4 = bool(g1_3periods_pos and g2_beat_hs300 and g3_trim3_pos and g4_slip50_pos)

        audit_rows.append({
            "strategy": name, "mode": mode, "horizon": h_nm,
            "n_all": m_all.get("n", 0), "n_IS": m_is.get("n", 0), "n_OOS": m_oos.get("n", 0), "n_2026": m_26.get("n", 0),
            "mean_all": m_all.get("mean"), "wr_all": m_all.get("wr"),
            "slot_cum_all": m_all.get("slot_cum"), "slot_exc_all": m_all.get("slot_excess"),
            "ew_cum_all": m_all.get("ew_cum"), "ew_exc_all": m_all.get("ew_excess"),
            "mean_IS": m_is.get("mean"), "slot_IS": m_is.get("slot_cum"), "ew_IS": m_is.get("ew_cum"),
            "mean_OOS": m_oos.get("mean"), "slot_OOS": m_oos.get("slot_cum"), "ew_OOS": m_oos.get("ew_cum"), "slot_exc_OOS": m_oos.get("slot_excess"),
            "mean_2026": m_26.get("mean"), "slot_2026": m_26.get("slot_cum"),
            "trim3_mean": m_all.get("trim3_mean"), "slot_trim3_cum": m_all.get("slot_trim3_cum"),
            "slip50_mean": m_50.get("mean"), "slip50_slot_cum": m_50.get("slot_cum"),
            "G1_3per": g1_3periods_pos, "G2_hs300": g2_beat_hs300, "G3_trim3": g3_trim3_pos, "G4_slip50": g4_slip50_pos,
            "PASS_ALL4": pass_all4,
        })

    audit_df = pd.DataFrame(audit_rows)
    audit_df.to_csv(OUT_DIR / "part3_redteam_audit.csv", index=False)
    return audit_df


def main():
    t0 = time.time()
    df = pd.read_parquet(OUT_DIR / "events_hold_48factors.parquet")
    eb = pd.read_parquet(OUT_DIR / "events_breach_base.parquet")
    idx_map = load_indices()
    hs_s = idx_map["sh000300"]

    base_df = build_baseline_tables(df, eb, hs_s)
    scan_df, corr_df = scan_factors(df)
    audit_df = run_redteam_audit_on_combos(df, scan_df, hs_s)

    # Extract representative winners & losers in 10cm_end165 & 10cm_peak165
    p10_end = df[(~df["is_20"]) & df["in_end_pool"]].copy()
    p10_end["r_best"] = p10_end["r31o_d35c_f30"].fillna(p10_end["r30c_d35c_f30"])
    top_win = p10_end.sort_values("r_best", ascending=False).head(8)[
        ["d30_date", "c6", "name", "primary_theme", "end_dev30", "relief_1d_pp", "d30_buyable", "d31_buyable", "d31_gap", "r30c_d31o_f30", "r30c_d35c_f30", "r31o_d32c_f30", "r31o_d35c_f30"]
    ]
    top_lose = p10_end.sort_values("r_best", ascending=True).head(8)[
        ["d30_date", "c6", "name", "primary_theme", "end_dev30", "relief_1d_pp", "d30_buyable", "d31_buyable", "d31_gap", "r30c_d31o_f30", "r30c_d35c_f30", "r31o_d32c_f30", "r31o_d35c_f30"]
    ]

    summary = {
        "meta": {
            "sample_start": "2021-01-04",
            "sample_end": "2026-11-24",
            "hs300_all_pct": round(hs300_period_ret(hs_s, "2021-01-04", "2026-11-24"), 2),
            "hs300_is_pct": round(hs300_period_ret(hs_s, "2021-01-04", "2023-12-29"), 2),
            "hs300_oos_pct": round(hs300_period_ret(hs_s, "2024-01-02", "2026-11-24"), 2),
            "hs300_2026_pct": round(hs300_period_ret(hs_s, "2026-01-05", "2026-11-24"), 2),
            "hold_peak165_10cm": int(((~df["is_20"]) & df["in_peak_pool"]).sum()),
            "hold_end165_10cm": int(((~df["is_20"]) & df["in_end_pool"]).sum()),
            "hold_peak165_20cm": int((df["is_20"] & df["in_peak_pool"]).sum()),
            "hold_end165_20cm": int((df["is_20"] & df["in_end_pool"]).sum()),
            "breach_10cm": int((~eb["is_20"]).sum()),
            "breach_20cm": int(eb["is_20"].sum()),
        },
        "pass_all4_count": int(audit_df["PASS_ALL4"].sum()) if len(audit_df) > 0 else 0,
        "top_winners": top_win.to_dict("records"),
        "top_losers": top_lose.to_dict("records"),
    }
    with open(OUT_DIR / "summary_redteam.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"[Step 3] Completed in {time.time()-t0:.1f}s | Audit rows={len(audit_df)}, PASS_ALL4={summary['pass_all4_count']}")


if __name__ == "__main__":
    main()
