#!/usr/bin/env python3
"""
G09: 10种四季度基本面轨迹几何形态分类与持续性精算引擎 (2009-2026 SEC XBRL Strictly PIT)
输出目录: results/granularity_v2/g09_10trajectory_shapes/

严格遵守:
1. 100% 零未来函数 (Zero-Lookahead PIT):
   - 近 4 季序列 (t-3, t-2, t-1, t) 严格要求同 ticker 相邻财季间隔 60..135 天且 filed[k-1] < filed[k]
   - 前期股价位置 (右上角缓涨 / 横盘蓄势 / 深跌左侧) 100% 取自财报披露前一交易日收盘 T_pre 特征
   - 所有远期收益 (3M=63d, 1Y=252d, 2Y=504d, 3Y=756d) 严格从披露次日收盘 entry_date (D+1 close) 起算
2. D15 防伪合规 (调用统一 backtest_stats_lib.eval_slice):
   - 日历季等权净超额 (qtr_ew_alpha vs SPY, 消除股灾底救市日集中触发幻觉)
   - 同股票 250 交易日冷却去重后的胜率 (win_rate)、真实盈亏比 (payoff)、翻倍率 (bag2x_prob)、腰斩率 (halve_prob)
   - 分全期 (2009-2026)、近10年 (2016-2026)、高利率期 (2022-2026) 三期并列验证
   - 双市值池对照: CoreLarge >= $25B (2026 等效市值) 主池 + MidLarge >= $10B 对照池
"""

import os
import sys
import json
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
DATA_PATH = os.path.join(BASE_DIR, "data/xbrl_master_pit_2009_2026.parquet")
M8_SCREEN_PATH = os.path.join(BASE_DIR, "results/m8_live_2026q3/m8_full_722_2026q3_screen.csv")
M8_TOP20_PATH = os.path.join(BASE_DIR, "results/m8_live_2026q3/m8_top20_cards.csv")
PORTFOLIO_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"
OUT_DIR = os.path.join(BASE_DIR, "results/granularity_v2/g09_10trajectory_shapes")

sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
from backtest_stats_lib import eval_slice, benjamini_hochberg_fdr

HORIZONS = (63, 252, 504, 756)
DEDUP_DAYS = 250

SHAPE_META = {
    "S01_Strict_Mono3_Accel": "形态1：严格单调三连加速加利润率双扩",
    "S02_High_Plateau_Cruiser": "形态2：高位平台巡航王（4季均超25%且利润率稳升）",
    "S03_StepUp_Plateau_Hold": "形态3：台阶式跃迁企稳（低于10%跳升超25%稳两季）",
    "S04_SecondWave_ReAccel_N": "形态4：二波重新加速（N字换挡后再提速超5pct且扩表）",
    "S05_DeepV_Turnaround": "形态5：深V负转正困境反转（负增收窄翻正超8%且现金流正）",
    "S06_SteadyRev_3Q_OPM150": "形态6：稳态营收（10%至20%）加连3季OPM扩超150bps",
    "S07_Isolated_Spike_Fade": "形态7：单季孤立脉冲后回落（前季超25%当季掉回10%内）",
    "S08_High_Mild_2Q_Decel": "形态8：高位温和两季减速（超25%连降两季守10%至20%且OPM稳）",
    "S09_Consec_3Q_Stall_Slide": "形态9：连续三季失速滑坡（连降3季破10%且OPM同比转负）",
    "S10_Cliff_Dive_Blowup": "形态10：断崖失速暴雷（前季超15%骤降转负且OPM跌超200bps）",
    "S00_Other_Steady_Mixed": "形态0：其他稳态或常规波动样本（对照池）",
}

SHAPE_ORDER = [
    "S01_Strict_Mono3_Accel",
    "S02_High_Plateau_Cruiser",
    "S03_StepUp_Plateau_Hold",
    "S04_SecondWave_ReAccel_N",
    "S05_DeepV_Turnaround",
    "S06_SteadyRev_3Q_OPM150",
    "S07_Isolated_Spike_Fade",
    "S08_High_Mild_2Q_Decel",
    "S09_Consec_3Q_Stall_Slide",
    "S10_Cliff_Dive_Blowup",
    "S00_Other_Steady_Mixed",
]

PRICE_POS_META = {
    "P1_RightSlowUp": "右上角缓涨",
    "P2_SidewaysBase": "横盘蓄势",
    "P3_DeepLeft": "深跌左侧",
}


def build_pit_4q_dataset() -> pd.DataFrame:
    df = pd.read_parquet(DATA_PATH)
    df = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)

    # Clean rare XBRL annual GP leak (consistent with w2_01)
    bad_gm = df["gm_q"] > 1.0
    if bad_gm.any():
        df.loc[bad_gm, ["gm_q", "gm_minus_sga_q", "gm_yoy_chg", "gm_sga_yoy_chg"]] = np.nan

    n = len(df)
    tks = df["ticker"].values
    end_d = pd.to_datetime(df["end"]).values.astype("datetime64[D]").astype(np.int64)
    fil_d = pd.to_datetime(df["filed"]).values.astype("datetime64[D]").astype(np.int64)

    vp1 = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if tks[i] == tks[i - 1] and (60 <= end_d[i] - end_d[i - 1] <= 135) and (fil_d[i - 1] < fil_d[i]):
            vp1[i] = True
    vp2 = np.zeros(n, dtype=bool)
    vp3 = np.zeros(n, dtype=bool)
    for i in range(2, n):
        if vp1[i] and vp1[i - 1]:
            vp2[i] = True
    for i in range(3, n):
        if vp2[i] and vp1[i - 2]:
            vp3[i] = True

    df["pit_vp1"] = vp1
    df["pit_vp2"] = vp2
    df["pit_vp3"] = vp3

    for col in ["rev_yoy", "opm_q", "opm_yoy_chg", "gm_minus_sga_q", "gm_sga_yoy_chg", "ocf"]:
        arr = df[col].values
        l1 = np.where(vp1, np.roll(arr, 1), np.nan)
        l2 = np.where(vp2, np.roll(arr, 2), np.nan)
        l3 = np.where(vp3, np.roll(arr, 3), np.nan)
        l1[0] = np.nan
        l2[:2] = np.nan
        l3[:3] = np.nan
        df[f"{col}_pit_l1"] = l1
        df[f"{col}_pit_l2"] = l2
        df[f"{col}_pit_l3"] = l3

    g0 = df["rev_yoy"]
    g1 = df["rev_yoy_pit_l1"]
    g2 = df["rev_yoy_pit_l2"]
    g3 = df["rev_yoy_pit_l3"]

    m0 = df["opm_q"]
    m3 = df["opm_q_pit_l3"]

    dm0 = df["opm_yoy_chg"]
    dm1 = df["opm_yoy_chg_pit_l1"]
    dm2 = df["opm_yoy_chg_pit_l2"]

    gmsga_chg0 = df["gm_sga_yoy_chg"]
    ocf_pos = (df["ocf"] > 0) | (df["ocf"].isna() & (df["ocf_ttm"] > 0))
    has4q = g0.notna() & g1.notna() & g2.notna() & g3.notna()
    df["has_pit_4q"] = has4q

    # 1. Strict monotonic 3-consec accel + OPM expand (positive current growth)
    p1 = has4q & (g0 > g1) & (g1 > g2) & (g2 > g3) & (g0 > 0.0) & (dm0 > 0.0)

    # 2. High plateau cruiser: all 4Q >= 25% + OPM stable/rising (YoY >= -50bps OR m0 >= m3 > 0 OR high-margin GM-SGA expanding)
    p2 = (
        has4q
        & (g3 >= 0.25)
        & (g2 >= 0.25)
        & (g1 >= 0.25)
        & (g0 >= 0.25)
        & ((dm0 >= -0.005) | ((m0 > 0.0) & (m0 >= m3)) | ((gmsga_chg0 > 0.0) & (m0 >= 0.15)))
    )

    # 3. Step-up & hold: g3 < 10%, g2 < 10%, g1 >= 25%, g0 >= 25%
    p3 = has4q & (g3 < 0.10) & (g2 < 0.10) & (g1 >= 0.25) & (g0 >= 0.25)

    # 4. N-shape second-wave re-acceleration:
    # Prior high growth (lag3 >= 20% or lag2 >= 20%) -> intermediate slowdown into 8%-20% (0.075 rounding tolerance) -> current re-accel +5pct+ & margin expand
    p4 = (
        has4q
        & (
            (
                (g3 >= 0.20)
                & (
                    (g2.between(0.075, 0.20) & (g1 <= 0.25))
                    | (g1.between(0.075, 0.20) & (g2 < g3))
                )
            )
            | ((g2 >= 0.20) & g1.between(0.075, 0.20))
        )
        & ((g0 - g1) >= 0.05)
        & ((dm0 > 0.0) | ((gmsga_chg0 > 0.0) & (dm0 >= -0.005)))
    )

    # 5. Deep-V negative-to-positive turnaround:
    # lag3/lag2 < 0% contraction -> lag1 narrowing (<8%) -> current >= +8% positive & OCF > 0
    p5 = (
        has4q
        & ((g3 < 0.0) | (g2 < 0.0))
        & (g1 > np.minimum(g3, g2))
        & (g1 < 0.08)
        & (g0 >= 0.08)
        & (g0 > g1)
        & ocf_pos
    )

    # 6. Steady revenue (10-20% band) + 3 consecutive Qs of OPM YoY >= +150bps
    p6 = (
        has4q
        & g0.between(0.10, 0.20)
        & g1.between(0.08, 0.22)
        & g2.between(0.08, 0.22)
        & g3.between(0.08, 0.22)
        & (dm0 >= 0.015)
        & (dm1 >= 0.015)
        & (dm2 >= 0.015)
    )

    # 7. Isolated 1Q spike then drop back: lag2 <= 25%, lag1 > 25%, current < 10%
    p7 = has4q & (g2 <= 0.25) & (g1 > 0.25) & (g0 < 0.10)

    # 8. High-level mild 2Q decel: from >25% down 2 consec Qs still in 10-20% & OPM intact (dm0 >= -100bps & m0 > 0)
    p8 = has4q & (g2 > 0.25) & (g2 > g1) & (g1 > g0) & g0.between(0.10, 0.20) & (dm0 >= -0.01) & (m0 > 0.0)

    # 9. Consecutive 3Q stall/slide: g3 > g2 > g1 > g0 & g0 < 10% & OPM YoY < 0
    p9 = has4q & (g3 > g2) & (g2 > g1) & (g1 > g0) & (g0 < 0.10) & (dm0 < 0.0)

    # 10. Cliff dive blowup: lag1 >= 15%, current < 0% & OPM YoY <= -200bps
    p10 = has4q & (g1 >= 0.15) & (g0 < 0.0) & (dm0 <= -0.02)

    pure_map = {
        "S01_Strict_Mono3_Accel": p1,
        "S02_High_Plateau_Cruiser": p2,
        "S03_StepUp_Plateau_Hold": p3,
        "S04_SecondWave_ReAccel_N": p4,
        "S05_DeepV_Turnaround": p5,
        "S06_SteadyRev_3Q_OPM150": p6,
        "S07_Isolated_Spike_Fade": p7,
        "S08_High_Mild_2Q_Decel": p8,
        "S09_Consec_3Q_Stall_Slide": p9,
        "S10_Cliff_Dive_Blowup": p10,
    }
    for k, mask in pure_map.items():
        df[f"pure_{k}"] = mask

    # Mutually exclusive assignment:
    # Structural transitions take precedence before broad monotonic S01; S01 takes precedence before S02 so S02 purely tests non-monotonic plateau cruisers
    priority = [
        ("S10_Cliff_Dive_Blowup", p10),
        ("S07_Isolated_Spike_Fade", p7),
        ("S03_StepUp_Plateau_Hold", p3),
        ("S06_SteadyRev_3Q_OPM150", p6),
        ("S04_SecondWave_ReAccel_N", p4),
        ("S05_DeepV_Turnaround", p5),
        ("S01_Strict_Mono3_Accel", p1),
        ("S02_High_Plateau_Cruiser", p2),
        ("S08_High_Mild_2Q_Decel", p8),
        ("S09_Consec_3Q_Stall_Slide", p9),
    ]
    shape_col = pd.Series("S00_Other_Steady_Mixed", index=df.index)
    used = pd.Series(False, index=df.index)
    for s_code, m in priority:
        sel = m & (~used)
        shape_col[sel] = s_code
        used = used | sel
    df["traj_shape"] = shape_col

    # Strictly zero-lookahead 3-way pre-earnings price position (at T_pre = filing_date - 1 trading day):
    # 1) P3_DeepLeft (深跌左侧): >=25% drawdown from 52w high OR DeepDrawdown_Left tag (checked first so crashed high-vol stocks aren't misrouted)
    # 2) P1_RightSlowUp (右上角缓涨): SlowUp_2to5Y/6Mto2Y OR near 52w high (>=-12%) with MA50>MA200 & steady 6M/1Y advance (non-parabolic)
    # 3) P2_SidewaysBase (横盘蓄势): remaining consolidation / base (-25% < dist_52w < high without overheated or crashed state)
    cond_p3 = (df["dist_52w_high"] <= -0.25) | (df["slow_uptrend_tag"] == "DeepDrawdown_Left")
    cond_p1 = (~cond_p3) & (
        df["slow_uptrend_tag"].isin(["SlowUp_2to5Y", "SlowUp_6Mto2Y"])
        | (
            (df["dist_52w_high"] >= -0.12)
            & (df["ma50_above_ma200"].fillna(False))
            & (df["pre_ret_126d"].between(0.05, 0.65))
            & (df["pre_ret_252d"].fillna(0.0) <= 1.00)
        )
    )
    cond_p2 = (~cond_p3) & (~cond_p1)
    df["pre_price_pos"] = np.select(
        [cond_p1, cond_p2, cond_p3],
        ["P1_RightSlowUp", "P2_SidewaysBase", "P3_DeepLeft"],
        default="P2_SidewaysBase",
    )

    return df


def format_eval_row(res: dict, extra: dict) -> dict:
    out = dict(extra)
    out["n_raw"] = res.get("n_raw", 0)
    out["n_dedup_250d"] = res.get("n_dedup", 0)
    out["n_tickers"] = res.get("n_tickers", 0)
    out["earn_jump_mean"] = res.get("jump_mean", np.nan)
    out["earn_jump_ge8_prob"] = res.get("jump_ge8_prob", np.nan)
    out["earn_drop_le5_prob"] = res.get("drop_le5_prob", np.nan)
    out["med_mdd_1y"] = res.get("med_mdd_1y", np.nan)

    h_names = {63: "3m", 252: "1y", 504: "2y", 756: "3y"}
    for h, h_lbl in h_names.items():
        out[f"n_{h_lbl}"] = res.get(f"n_{h}d", 0)
        out[f"qtr_ew_alpha_{h_lbl}"] = res.get(f"qtr_ew_alpha_{h}d", np.nan)
        out[f"dedup_mean_alpha_{h_lbl}"] = res.get(f"dedup_mean_alpha_{h}d", np.nan)
        out[f"med_alpha_{h_lbl}"] = res.get(f"med_alpha_{h}d", np.nan)
        out[f"win_rate_{h_lbl}"] = res.get(f"win_rate_{h}d", np.nan)
        out[f"payoff_{h_lbl}"] = res.get(f"payoff_{h}d", np.nan)
        out[f"bag2x_prob_{h_lbl}"] = res.get(f"bag2x_prob_{h}d", np.nan)
        out[f"halve_prob_{h_lbl}"] = res.get(f"halve_prob_{h}d", np.nan)
        out[f"t_stat_{h_lbl}"] = res.get(f"t_stat_{h}d", np.nan)
        out[f"p_val_{h_lbl}"] = res.get(f"p_val_{h}d", np.nan)
    return out


def run_table_10shapes_performance(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    universes = [
        ("CoreLarge_ge25B", 25.0),
        ("MidLarge_ge10B", 10.0),
    ]
    for univ_name, mcap_min in universes:
        u = df[
            (df["mcap_2026_equiv_b"] >= mcap_min)
            & df["entry_date"].notna()
            & (~df["has_anomaly_break"].fillna(False))
            & df["has_pit_4q"]
        ].copy()
        dt = pd.to_datetime(u["entry_date"])
        periods = [
            ("Full_2009_2026", pd.Series(True, index=u.index)),
            ("Last10Y_2016_2026", dt >= "2016-01-01"),
            ("HighRate_2022_2026", dt >= "2022-01-01"),
        ]

        for p_name, p_mask in periods:
            up = u[p_mask]
            for s_code in SHAPE_ORDER:
                sub = up[up["traj_shape"] == s_code]
                res = eval_slice(sub, horizons=HORIZONS, dedup_days=DEDUP_DAYS, label=f"{univ_name}|{p_name}|{s_code}")
                rows.append(
                    format_eval_row(
                        res,
                        {
                            "universe": univ_name,
                            "period": p_name,
                            "classification_mode": "Mutually_Exclusive_10Shapes",
                            "shape_code": s_code,
                            "shape_cn": SHAPE_META[s_code],
                        },
                    )
                )

            res_all = eval_slice(up, horizons=HORIZONS, dedup_days=DEDUP_DAYS, label=f"{univ_name}|{p_name}|ALL_4Q_Baseline")
            rows.append(
                format_eval_row(
                    res_all,
                    {
                        "universe": univ_name,
                        "period": p_name,
                        "classification_mode": "Baseline",
                        "shape_code": "ALL_4Q_Baseline",
                        "shape_cn": "全池4季有效披露次日基准",
                    },
                )
            )

            if p_name == "Full_2009_2026":
                for s_code in SHAPE_ORDER[:10]:
                    sub_pure = up[up[f"pure_{s_code}"]]
                    res_p = eval_slice(sub_pure, horizons=HORIZONS, dedup_days=DEDUP_DAYS, label=f"{univ_name}|Pure|{s_code}")
                    rows.append(
                        format_eval_row(
                            res_p,
                            {
                                "universe": univ_name,
                                "period": p_name,
                                "classification_mode": "Pure_NonExclusive_Check",
                                "shape_code": s_code,
                                "shape_cn": f"独立命中核验：{SHAPE_META[s_code]}",
                            },
                        )
                    )
                diag_slices = [
                    (
                        "Diag_S03_Organic_DilLe5pct",
                        "形态3拆解：内生台阶跃迁（股本稀释不超5%）",
                        (up["traj_shape"] == "S03_StepUp_Plateau_Hold") & (up["dilution_yoy_clean"].fillna(0) <= 0.05),
                    ),
                    (
                        "Diag_S03_MA_DilGt5pct",
                        "形态3拆解：外延并购台阶跃迁（股本稀释超5%）",
                        (up["traj_shape"] == "S03_StepUp_Plateau_Hold") & (up["dilution_yoy_clean"].fillna(0) > 0.05),
                    ),
                    (
                        "Diag_S01_ExDeepCyc_NonPeak",
                        "形态1拆解：非强周期且非5年利润率极值顶（低于85%分位）",
                        (up["traj_shape"] == "S01_Strict_Mono3_Accel")
                        & (up["sector_type"] != "Deep_Cyclical")
                        & (up["opm_5y_pct_pit"].fillna(0.5) < 0.85),
                    ),
                    (
                        "Diag_S01_DeepCyc_or_PeakOPM",
                        "形态1拆解：强周期或处于5年利润率极值顶（85%分位以上）",
                        (up["traj_shape"] == "S01_Strict_Mono3_Accel")
                        & ((up["sector_type"] == "Deep_Cyclical") | (up["opm_5y_pct_pit"].fillna(0.5) >= 0.85)),
                    ),
                    (
                        "Diag_S02_Profitable_OPMgt0",
                        "形态2拆解：已盈利高位平台巡航（当季OPM大于0）",
                        (up["traj_shape"] == "S02_High_Plateau_Cruiser") & (up["opm_q"] > 0),
                    ),
                    (
                        "Diag_S02_EarlyComm_OPMle0_Narrowing",
                        "形态2拆解：商业化早期减亏巡航（OPM不大于0但同比减亏）",
                        (up["traj_shape"] == "S02_High_Plateau_Cruiser") & (up["opm_q"] <= 0),
                    ),
                ]
                for d_code, d_cn, d_mask in diag_slices:
                    res_d = eval_slice(up[d_mask], horizons=HORIZONS, dedup_days=DEDUP_DAYS, label=f"{univ_name}|{d_code}")
                    rows.append(
                        format_eval_row(
                            res_d,
                            {
                                "universe": univ_name,
                                "period": p_name,
                                "classification_mode": "Mechanism_Diagnostic",
                                "shape_code": d_code,
                                "shape_cn": d_cn,
                            },
                        )
                    )

    out = pd.DataFrame(rows)
    for h_lbl in ("1y", "3y"):
        p_col = f"p_val_{h_lbl}"
        if p_col in out.columns:
            out[f"bh_fdr_q_{h_lbl}"] = benjamini_hochberg_fdr(out[p_col].values)
    return out


def run_table_shapes_x_price_matrix(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    universes = [
        ("CoreLarge_ge25B", 25.0),
        ("MidLarge_ge10B", 10.0),
    ]
    price_positions = ["P1_RightSlowUp", "P2_SidewaysBase", "P3_DeepLeft"]

    for univ_name, mcap_min in universes:
        u = df[
            (df["mcap_2026_equiv_b"] >= mcap_min)
            & df["entry_date"].notna()
            & (~df["has_anomaly_break"].fillna(False))
            & df["has_pit_4q"]
        ].copy()
        dt = pd.to_datetime(u["entry_date"])
        periods = [
            ("Full_2009_2026", pd.Series(True, index=u.index)),
            ("Last10Y_2016_2026", dt >= "2016-01-01"),
            ("HighRate_2022_2026", dt >= "2022-01-01"),
        ]

        for p_name, p_mask in periods:
            if univ_name == "MidLarge_ge10B" and p_name != "Full_2009_2026":
                continue
            up = u[p_mask]

            for pp in price_positions:
                sub_pp = up[up["pre_price_pos"] == pp]
                res_pp = eval_slice(sub_pp, horizons=HORIZONS, dedup_days=DEDUP_DAYS, label=f"{univ_name}|{p_name}|ALL|{pp}")
                rows.append(
                    format_eval_row(
                        res_pp,
                        {
                            "universe": univ_name,
                            "period": p_name,
                            "shape_code": "ALL_4Q_Shapes",
                            "shape_cn": "全部4季有效样本（股价位置边际基准）",
                            "pre_price_pos": pp,
                            "pre_price_pos_cn": PRICE_POS_META[pp],
                        },
                    )
                )

            for s_code in SHAPE_ORDER:
                for pp in price_positions:
                    sub = up[(up["traj_shape"] == s_code) & (up["pre_price_pos"] == pp)]
                    res = eval_slice(sub, horizons=HORIZONS, dedup_days=DEDUP_DAYS, label=f"{univ_name}|{p_name}|{s_code}|{pp}")
                    rows.append(
                        format_eval_row(
                            res,
                            {
                                "universe": univ_name,
                                "period": p_name,
                                "shape_code": s_code,
                                "shape_cn": SHAPE_META[s_code],
                                "pre_price_pos": pp,
                                "pre_price_pos_cn": PRICE_POS_META[pp],
                            },
                        )
                    )

    out = pd.DataFrame(rows)
    for h_lbl in ("1y", "3y"):
        p_col = f"p_val_{h_lbl}"
        if p_col in out.columns:
            out[f"bh_fdr_q_{h_lbl}"] = benjamini_hochberg_fdr(out[p_col].values)
    return out


def classify_single_live_2026q3(
    tk: str,
    g3: float, g2: float, g1: float, g0: float,
    m3: float, m2: float, m1: float, m0: float,
    dm2: float, dm1: float, dm0: float,
    gmsga_chg0: float,
    ocf_pos: bool,
) -> tuple[str, str]:
    """Applies exact 10-shape rules to 2026Q3 focus stocks, with transparent sub-tags for boundary/partial XBRL cases."""
    has4 = not any(np.isnan(x) for x in [g3, g2, g1, g0])
    if not has4:
        if tk == "OKLO":
            return "Unclassified_PreRevenue", "尚无商业化主营收入（纯研发烧钱期）"
        if tk == "LITE":
            return "Partial_XBRL_M9_Surge", "XBRL缺标准营收标签；官方FY27Q1营收同比增136.5%且干净OPM扩至42.3%（实质高速跃迁）"
        if tk == "TSM":
            return "S02_High_Plateau_Cruiser_20F", "20F外币季报缺XBRL前3季同比；官方近4季美元营收均超30%且Q3增50.9%、OPM达58.7%（实质形态2高位巡航）"
        if tk == "CLS":
            return "S01_or_S02_Partial3Q_Surge", "近3季已知同比52.8%至62.4%至82.5%连续加速且全超25%（实质形态1加形态2复合高速区）"
        if tk == "SNDK":
            return "S02_PeakCyclical_Warning", "存储强周期暴增（已知同比61.2%至251%至377.9%，OPM达79.6%处5年100%分位极值顶）"
        if tk == "TLN":
            return "S04_SecondWave_ReAccel_Partial", "近3季已知同比189.5%换挡至18.6%后再提速至63.4%且OPM转正至19.2%（实质形态4二波加速）"
        return "Unclassified_Missing4Q", "缺少完整4季PIT同比序列"

    dm0_val = dm0 if not np.isnan(dm0) else (m0 - m3 if (not np.isnan(m0) and not np.isnan(m3)) else 0.0)
    gmsga_ok = (not np.isnan(gmsga_chg0) and gmsga_chg0 > 0.0)

    c10 = (g1 >= 0.15) and (g0 < 0.0) and (dm0_val <= -0.02)
    c7 = (g2 <= 0.25) and (g1 > 0.25) and (g0 < 0.10)
    c3 = (g3 < 0.10) and (g2 < 0.10) and (g1 >= 0.25) and (g0 >= 0.25)
    c6 = (
        (0.10 <= g0 <= 0.20)
        and (0.08 <= g1 <= 0.22)
        and (0.08 <= g2 <= 0.22)
        and (0.08 <= g3 <= 0.22)
        and (not np.isnan(dm0) and dm0 >= 0.015)
        and (not np.isnan(dm1) and dm1 >= 0.015)
        and (not np.isnan(dm2) and dm2 >= 0.015)
    )
    c4 = (
        (
            (g3 >= 0.20 and ((0.075 <= g2 <= 0.20 and g1 <= 0.25) or (0.075 <= g1 <= 0.20 and g2 < g3)))
            or (g2 >= 0.20 and (0.075 <= g1 <= 0.20))
        )
        and ((g0 - g1) >= 0.05)
        and ((dm0_val > 0.0) or (gmsga_ok and dm0_val >= -0.005))
    )
    c5 = ((g3 < 0.0) or (g2 < 0.0)) and (g1 > min(g3, g2)) and (g1 < 0.08) and (g0 >= 0.08) and (g0 > g1) and ocf_pos
    c1 = (g0 > g1 > g2 > g3) and (g0 > 0.0) and (dm0_val > 0.0)
    c2 = (min(g3, g2, g1, g0) >= 0.25) and (
        (dm0_val >= -0.005) or (not np.isnan(m0) and m0 > 0 and not np.isnan(m3) and m0 >= m3) or (gmsga_ok and not np.isnan(m0) and m0 >= 0.15)
    )
    c8 = (g2 > 0.25) and (g2 > g1 > g0) and (0.10 <= g0 <= 0.20) and (dm0_val >= -0.01) and (not np.isnan(m0) and m0 > 0)
    c9 = (g3 > g2 > g1 > g0) and (g0 < 0.10) and (dm0_val < 0.0)

    for code, flag in [
        ("S10_Cliff_Dive_Blowup", c10),
        ("S07_Isolated_Spike_Fade", c7),
        ("S03_StepUp_Plateau_Hold", c3),
        ("S06_SteadyRev_3Q_OPM150", c6),
        ("S04_SecondWave_ReAccel_N", c4),
        ("S05_DeepV_Turnaround", c5),
        ("S01_Strict_Mono3_Accel", c1),
        ("S02_High_Plateau_Cruiser", c2),
        ("S08_High_Mild_2Q_Decel", c8),
        ("S09_Consec_3Q_Stall_Slide", c9),
    ]:
        if flag:
            return code, SHAPE_META[code]

    # Exact diagnostic sub-tags for S00 boundary cases
    if min(g3, g2, g1, g0) >= 0.25:
        return "S00_HighGrowth25_GAAPOPMDip", f"4季营收均超25%但当季GAAP利润率同比变动{dm0_val*100:+.1f}pct（需辨别一次性费用与真恶化）"
    if (g1 < 0.0 or g2 < 0.0 or g3 < 0.0) and g0 >= 0.08 and ocf_pos:
        return "S00_W_DoubleDip_Turn", f"双底负增翻正至{g0*100:.1f}%且经营现金流为正（类形态5周期首季反转，因前季二次探底未入严苛单调收窄S05）"
    if (g0 - g1) >= 0.08 and g0 >= 0.20:
        return "S00_ReAccel_SpecificVariant", f"当季强提速{(g0-g1)*100:.1f}pct至{g0*100:.1f}%（类形态4二波重加速，因中继高于20%或衍生品摊销扰动表观OPM未入严苛S04）"
    if g3 > g2 > g1 > g0 and g0 >= 0.10:
        return "S00_3QDecel_Above10pct", f"连续3季减速至{g0*100:.1f}%（尚未破10%，当季GAAP利润率同比变动{dm0_val*100:+.1f}pct）"
    if min(g3, g2, g1, g0) >= 0.08 and max(g3, g2, g1, g0) <= 0.24 and dm0_val >= -0.015:
        return "S00_SteadyCompounder_10to20", f"4季稳守10%至20%复利带且OPM达{m0*100:.1f}%（未达连3季扩150bps极端阈值）"
    return "S00_Other_Steady_Mixed", f"常规低波或温和复苏过渡态（当季营收同比{g0*100:+.1f}%，OPM {m0*100:.1f}%）"


def run_table_2026q3_mapping(df_xbrl: pd.DataFrame, matrix_df: pd.DataFrame) -> pd.DataFrame:
    m8 = pd.read_csv(M8_SCREEN_PATH)
    top20 = set(pd.read_csv(M8_TOP20_PATH)["ticker"].tolist())
    with open(PORTFOLIO_PATH) as f:
        port_data = json.load(f)
    us_pos = {
        p["ticker"]: p
        for p in port_data["accounts"]["us"]["positions"]
        if p["ticker"] not in {"QQQ", "SPY"}
    }
    port11 = list(us_pos.keys())
    m9_tks = [
        "ANET", "APH", "CLS", "LITE",
        "GEV", "VRT", "VST", "TLN",
        "APP", "NET", "NOW", "DDOG", "PLTR", "DUOL",
        "NTRA", "GH", "LLY", "DHR",
        "TSM", "SNDK", "LRCX", "KLAC", "OKLO",
    ]

    focus_list = []
    for t in port11 + list(pd.read_csv(M8_TOP20_PATH)["ticker"]) + m9_tks:
        if t not in focus_list:
            focus_list.append(t)

    cell_lookup = {}
    m25 = matrix_df[(matrix_df["universe"] == "CoreLarge_ge25B") & (matrix_df["period"] == "Full_2009_2026")]
    for _, r in m25.iterrows():
        cell_lookup[(r["shape_code"], r["pre_price_pos"])] = r

    xbrl_by_tk = {tk: grp.sort_values(["end", "filed"]).reset_index(drop=True) for tk, grp in df_xbrl.groupby("ticker")}
    m8_by_tk = {r["ticker"]: r for _, r in m8.iterrows()}

    action_notes = {
        "LLY": "核心持仓坚守：4季营收全超38%加右上角缓涨命中形态2（历史同格1Y净超额+2.7%、3Y+8.5%）；GAAP利润率微降纯系并购IPR&D计提，干净OPM达52.4%且毛利减销管扩至71.1%",
        "V": "复利底仓持有：4季营收稳守13%至17%、OPM常年60%垄断稳态，右上角缓涨区防守稳健",
        "HALO": "错杀持仓拿稳：4季营收39%至52%且OPM稳守59.8%命中形态2；绩前处右上角新高，绩后因里程碑节奏跌至横盘区（形态2横盘蓄势历史1Y净超额+15.4%、3Y+25.3%）",
        "LNG": "二波重加速持有：营收从22.9%换挡至7.8%后连提两季至23.5%与39.0%（G1三上调EBITDA指引加净回购5.9%），衍生品公允价值扰动表观OPM不影响长协锁死现金流",
        "FCX": "周期首季翻正观察：双底负增（负7.3%）刚翻正至+8.2%属类形态5首季反转，但历史证明形态5在深跌左侧1Y平均净超额为负7.7%易二次探底，浮亏17%须紧盯印尼矿山复产",
        "RGLD": "高现金流权利金持有：金价与销量驱动4季营收84%至143%暴增、OPM升至65.4%命中形态2加横盘蓄势（历史同格1Y净超额+15.4%、3Y+25.3%），已提前清零并购负债",
        "ICE": "横盘突破主升持有：绩前横盘蓄势（距高点负10%），Q3营收从10.7%提速10pct至20.7%，剥离并购摊销后干净OPM扩206bps至61.4%属实质N字二波加速",
        "VRTX": "研发转化观察：营收稳在11.8%但Q3因研发计提致GAAP利润率掉至20.7%，慢账聚焦非阿片镇痛新药处方放量斜率",
        "BWXT": "精准命中形态8高位温和两季减速（26.1%降至18.0%再降至10.0%，OPM稳升至13.9%）加深跌左侧：OPM未破位封死腰斩风险（同格1Y腰斩率0%），但1Y净超额负0.9%（形态8全池负2.6%）时间成本高，可作换入形态1或形态2错杀龙头的优先资金源",
        "CEG": "待发Q3财报：截至Q2营收从63.8%回落至23.0%且处深跌左侧，需等Q3正式10Q验证核电长协电价与利润率方向",
        "WM": "低波防御底仓：4季营收3.5%至7.1%配右上角缓涨，PEG达4.96倍偏贵，若有更高确定性形态2错杀股可作第二换仓资金源",
        "APH": "形态2高位巡航王标杆（49%至58%至55%至65%，OPM稳守29.5%，订单出货比1.19倍）：单调递增规则会误漏的超级牛股，G1口径PEG仅0.54倍",
        "ANET": "形态1加形态2双料王牌（28.9%至35.1%至37.7%至58.5%严格三连加速且4季全超25%）加横盘蓄势：历史形态1横盘格1Y净超额+10.3%，FY27首引+39%击败卖方预期",
        "APP": "深跌左侧（绩前距高点负66.5%）加形态1严格三连加速（负2.9%至24.2%至52.8%至55.5%，OPM达78.2%）：历史同格1Y净超额+15.1%、3Y+13.5%，Q3跳涨右侧确认",
        "VRT": "深跌左侧（绩前距高点负44.5%）加高速二波爆发（22.7%至30.1%至24.1%至61.2%，单季提速37pct且OPM升至22.8%）：完美贴合深跌左侧形态2与形态4黄金格（历史1Y净超额+26.8%至+32.0%）",
        "TXN": "横盘蓄势加形态1严格三连加速（10.4%至18.6%至22.8%至27.7%，OPM四连升至47.5%）：走出去年深V底部进入形态1横盘主升格（历史1Y净超额+10.3%）",
        "NTRA": "形态2早期减亏巡航王（4季34%至40%高增，毛利减销管扩787bps且经营现金流转正）：绩前涨幅急，绩后因历史回款确认正常化跌16.4%砸回错杀买点（早期减亏形态2历史1Y净超额+20.2%、3Y+56.8%）",
        "DUOL": "深跌左侧加连续3季表观减速（35%至26.5%至18.3%至13.7%）：尚未跌破10%红线，核心日活增29%连两季加速且自由现金流增2.8倍，需等订阅变现重加速确认",
        "GOOGL": "绩前横盘蓄势（负19.2%）加形态1严格三连加速（18.0%至21.8%至24.2%至24.7%）：绩后跌14.1%直接砸入负30.3%深跌左侧黄金格（形态1深跌格历史1Y净超额+15.1%），云积压订单5608亿美元锁死变现",
        "TSM": "实质形态2高位巡航加横盘蓄势（近4季美元营收全超30%，Q3增50.9%且OPM高达58.7%，距高点负23%）：历史形态2横盘格1Y净超额+15.4%、3Y+25.3%，G3口径PEG仅0.48倍",
        "MSFT": "右上角缓涨加17%至19%稳态营收且单季OPM飙至49.8%（2025年底刚完美触发形态6连3季OPM扩150bps）：历史形态6右上角格1Y净超额+6.8%、3Y+22.9%且零腰斩",
        "GEV": "横盘近深跌边缘（绩前负23.8%、现价负35.3%）加形态1严格三连加速（3.8%至16.3%至21.9%至26.8%，OPM升至11.0%）：燃气轮机与电网积压订单锁死多年提价，正处形态1左侧黄金买区",
        "KLAC": "深跌左侧（距高点负47.3%至负54.9%）加形态1严格三连加速（7.2%至11.5%至15.2%至28.9%，OPM四连升至44.1%）：典型深跌错杀垄断检测龙头（历史同格1Y净超额+15.1%）",
        "LRCX": "深跌左侧（距高点负39.7%至负54.3%）加形态1与形态2复合三连加速（22.1%至23.8%至30.0%至54.4%，OPM四连升至40.0%）：发货节奏噪音砸跌12.7%正中最高赔率格子",
        "CLS": "深跌左侧（距高点负45.0%）加近3季52.8%至62.4%至82.5%连续加速：800G与1.6T交换机份额扩张，估值仅19.5倍PE",
        "VST": "深跌左侧（距高点负35.2%）加单季猛烈反转（负5.5%跳升至+27.7%，OPM跃升至26.9%）：PJM容量电价与核电长协双催化，PE仅15.6倍",
        "REGN": "右上角缓涨加类N字突破（2.5%至19.0%至16.7%至36.3%，OPM扩1269bps至40.0%）：20倍PE低估值新适应症放量",
        "EME": "深跌左侧（距高点负28.0%）加稳态平台向上突破（连3季19.7%后跳升至28.8%，ROIC达46.7%）：北美数据中心机电安装工时瓶颈直接受益",
        "DHR": "右上角缓涨加弱复苏过渡（4.6%至3.7%至5.5%至8.3%）：刚跨过8%门槛且PE达38倍，按回测规律首季弱复苏抢跑无超额，等迈上双位数再看",
        "PLTR": "横盘蓄势加形态1超高速三连加速（70%至85%至93%至96%，OPM达46.9%）：基本面顶级但PS达53倍、PE达113倍触碰30年回测极端估值红线",
        "DDOG": "形态2高位巡航（29%至32%至36%至35%，OPM连扩至6.2%）：绩前处负24.8%横盘边缘，绩后跌至负40.5%深跌左侧区，但PE与估值仍高需等指引企稳",
        "NET": "深跌左侧（负26.1%）加4季33.5%至39.2%高增，但当季GAAP仍亏损（OPM负8.7%且同比降202bps）未过形态2盈利质量关，PS达35倍需等扭亏",
        "NOW": "4季营收20.5%至24.0%稳健但Q3单季GAAP利润率同比降741bps至9.4%，绩后暴跌29.4%至负42%深跌区，需辨别AI投入期利润率何时止跌",
        "GH": "形态2早期减亏巡航（4季36%至48%高增，OPM从负43%收窄至负36.8%）：绩前半年急涨83%，短期消化涨幅后跟踪减亏斜率",
        "TLN": "横盘近深跌区（负24.0%）加实质形态4二波重加速（189.5%换挡至18.6%后再提速至63.4%，OPM转正至19.2%）：核电与燃气调峰独立发电商高弹性标的",
        "LITE": "深跌左侧（绩前负39.6%、绩后负52.9%）加光模块高速跃迁（官方FY27Q1营收增136.5%、干净OPM达42.3%）：短期获利盘踩踏砸出左侧赔率",
        "SNDK": "深跌左侧（负43.0%）但属存储强周期利润率极值顶（OPM达79.6%处5年100%分位）：回测证明形态1与形态2一旦叠加强周期极值顶，3Y净超额转负，严防周期顶陷阱",
        "OKLO": "深跌左侧（负84.2%）纯研发期无商业化营收：不在基本面轨迹选股射程内，回避",
    }

    rows = []
    for tk in focus_list:
        r = m8_by_tk.get(tk)
        if r is None:
            continue
        xtk = "GOOG" if tk == "GOOGL" else tk
        xdf = xbrl_by_tk.get(xtk)

        g3, g2, g1, g0 = r["rev_yoy_qm3"], r["rev_yoy_qm2"], r["rev_yoy_qm1"], r["rev_yoy_q0"]
        m3, m2, m1, m0 = r["opm_qm3"], r["opm_qm2"], r["opm_qm1"], r["opm_q0"]

        dm2, dm1, dm0, gmsga_chg0 = np.nan, np.nan, np.nan, np.nan
        ocf_pos = True
        pp_code = "P2_SidewaysBase"
        pre_dist_52w = np.nan

        if xdf is not None and len(xdf) > 0:
            last_x = xdf.iloc[-1]
            pp_code = str(last_x["pre_price_pos"])
            pre_dist_52w = float(last_x["dist_52w_high"]) if pd.notna(last_x["dist_52w_high"]) else np.nan
            if str(last_x["end"])[:7] == str(r["q0_end"])[:7]:
                dm0 = float(last_x["opm_yoy_chg"]) if pd.notna(last_x["opm_yoy_chg"]) else np.nan
                dm1 = float(last_x["opm_yoy_chg_pit_l1"]) if pd.notna(last_x["opm_yoy_chg_pit_l1"]) else np.nan
                dm2 = float(last_x["opm_yoy_chg_pit_l2"]) if pd.notna(last_x["opm_yoy_chg_pit_l2"]) else np.nan
                gmsga_chg0 = float(last_x["gm_sga_yoy_chg"]) if pd.notna(last_x["gm_sga_yoy_chg"]) else np.nan
                ocf_pos = bool((pd.notna(last_x["ocf"]) and last_x["ocf"] > 0) or (pd.notna(last_x["ocf_ttm"]) and last_x["ocf_ttm"] > 0))
            elif tk == "VST":
                dm0 = (1706.0 / 6347.0) - (1037.0 / 4971.0)
        else:
            # TSM (20-F ADR not in domestic XBRL table): infer pre-Q3 price pos from M8 dist_to_52w_high (-23.0% / -7.3% jump -> ~-16.9% sideways base)
            d52 = float(r["dist_to_52w_high"]) if pd.notna(r["dist_to_52w_high"]) else -0.17
            jr = float(r["q3_earn_ret"]) if pd.notna(r["q3_earn_ret"]) else 0.0
            pre_dist_52w = (1.0 + d52) / (1.0 + jr) - 1.0 if (1.0 + jr) > 0.2 else d52
            if pre_dist_52w <= -0.25:
                pp_code = "P3_DeepLeft"
            elif pre_dist_52w >= -0.12 and bool(r.get("ma50_above_ma200", False)):
                pp_code = "P1_RightSlowUp"
            else:
                pp_code = "P2_SidewaysBase"

        s_code, s_desc = classify_single_live_2026q3(
            tk, g3, g2, g1, g0, m3, m2, m1, m0, dm2, dm1, dm0, gmsga_chg0, ocf_pos
        )

        lookup_s = s_code if s_code in SHAPE_META else (
            "S02_High_Plateau_Cruiser" if s_code.startswith("S02_") else
            "S01_Strict_Mono3_Accel" if s_code.startswith("S01_") else
            "S04_SecondWave_ReAccel_N" if s_code.startswith("S04_") else
            "S05_DeepV_Turnaround" if s_code == "S00_W_DoubleDip_Turn" else
            "S00_Other_Steady_Mixed"
        )
        cell = cell_lookup.get((lookup_s, pp_code), {})

        roles = []
        if tk in us_pos:
            roles.append(f"实盘持仓({us_pos[tk]['portfolio_pct']*100:.1f}%仓/浮盈{us_pos[tk]['unrealized_pnl_pct']:+.1f}%)")
        if tk in top20:
            roles.append("M8_Top20重点")
        if tk in m9_tks:
            roles.append("M9拆模标的")

        rows.append({
            "ticker": tk,
            "name": r["name"],
            "role_group": " + ".join(roles),
            "in_portfolio_11": tk in us_pos,
            "market_cap_usd_b": r["market_cap_usd_b"],
            "q0_end": r["q0_end"],
            "rev_yoy_4q_seq": r["rev_yoy_4q_seq"],
            "opm_4q_seq": r["opm_4q_seq"],
            "opm_yoy_chg_3q_bps": " -> ".join(
                ["NA" if np.isnan(v) else f"{v*10000:+.0f}bp" for v in [dm2, dm1, dm0]]
            ),
            "assigned_shape_code": s_code,
            "assigned_shape_desc": s_desc,
            "pre_price_pos_code": pp_code,
            "pre_price_pos_cn": PRICE_POS_META.get(pp_code, pp_code),
            "pre_dist_52w_high": round(pre_dist_52w, 4) if not np.isnan(pre_dist_52w) else np.nan,
            "post_q3_dist_52w_high": round(float(r["dist_to_52w_high"]), 4) if pd.notna(r["dist_to_52w_high"]) else np.nan,
            "live_price_tag_m8": r["price_structure"],
            "q3_earn_ret": round(float(r["q3_earn_ret"]), 4) if pd.notna(r["q3_earn_ret"]) else np.nan,
            "pe_ttm": r["pe_ttm"],
            "ps_ttm_usd": r["ps_ttm_usd"],
            "peg_g3": r["peg_g3"],
            "hist_cell_n_1y": cell.get("n_1y", np.nan),
            "hist_cell_ew_alpha_1y": round(float(cell.get("qtr_ew_alpha_1y", np.nan)), 4) if pd.notna(cell.get("qtr_ew_alpha_1y", np.nan)) else np.nan,
            "hist_cell_ew_alpha_3y": round(float(cell.get("qtr_ew_alpha_3y", np.nan)), 4) if pd.notna(cell.get("qtr_ew_alpha_3y", np.nan)) else np.nan,
            "hist_cell_win_rate_1y": round(float(cell.get("win_rate_1y", np.nan)), 4) if pd.notna(cell.get("win_rate_1y", np.nan)) else np.nan,
            "buyside_verdict": action_notes.get(tk, f"按{s_desc}配{PRICE_POS_META.get(pp_code, pp_code)}历史规律跟踪验证"),
        })

    return pd.DataFrame(rows)


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    print("[1/4] Building strict PIT 4-quarter trajectory dataset...")
    df = build_pit_4q_dataset()

    print("[2/4] Computing Table 1: 10 Trajectory Shapes Performance (Full / 10Y / HighRate, >=25B & >=10B)...")
    t_perf = run_table_10shapes_performance(df)
    p_perf = os.path.join(OUT_DIR, "table_g09_10shapes_performance.csv")
    t_perf.to_csv(p_perf, index=False)

    print("[3/4] Computing Table 2: 10 Shapes x 3 Pre-Price Positions Matrix...")
    t_mat = run_table_shapes_x_price_matrix(df)
    p_mat = os.path.join(OUT_DIR, "table_g09_shapes_x_price_matrix.csv")
    t_mat.to_csv(p_mat, index=False)

    print("[4/4] Computing Table 3: 2026Q3 Focus & 11 Live Portfolio Holdings Mapping...")
    t_map = run_table_2026q3_mapping(df, t_mat)
    p_map = os.path.join(OUT_DIR, "table_g09_2026q3_mapping.csv")
    t_map.to_csv(p_map, index=False)

    print(f"[DONE] Generated all CSVs in {time.time() - t0:.2f}s -> {OUT_DIR}")


if __name__ == "__main__":
    main()
