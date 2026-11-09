"""
w2_04_nine_params_grid.py
30-Year US Stock Earnings Inflection & Macro Regime Backtest
Subagent W2_04: 9 Reference Indicators + 5 Proprietary Buyer Quality Indicators
Ultra-fine granularity slicing engine across Baseline, 1Q Inflection, and 3-4Q Trajectory.

Strict Guardrails:
- Zero Lookahead & Zero Survivorship Bias
- Calendar-Quarter Equal-Weight Net Alpha vs SPY
- 12-Month Cooldown Per-Ticker Deduplication
- Mandatory D15 Subperiod Checks (Full, Ex-Bubble, Last 10Y, High Rate Era)
- Pure Python & Pandas, No unhandled NaNs, Clean output to results/m4_params_grid/
"""

import os
import sys
import time
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd

# Path setup
PROJ_ROOT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
SCRIPTS_DIR = os.path.join(PROJ_ROOT, "scripts")
DATA_DIR = os.path.join(PROJ_ROOT, "data")
RESULTS_DIR = os.path.join(PROJ_ROOT, "results", "m4_params_grid")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from backtest_stats_lib import eval_slice, eval_d15_subperiods, deduplicate_cooldown

os.makedirs(RESULTS_DIR, exist_ok=True)

# -------------------------------------------------------------------------------------------------
# 1. Load Data
# -------------------------------------------------------------------------------------------------
PARQUET_FILE = os.path.join(DATA_DIR, "xbrl_master_pit_2009_2026.parquet")
print(f"[W2_04] Loading dataset: {PARQUET_FILE}...")
t0 = time.time()
df = pd.read_parquet(PARQUET_FILE)
print(f"[W2_04] Loaded {len(df):,} rows x {len(df.columns)} columns in {time.time()-t0:.2f}s.")

# Ensure date fields
df["entry_date"] = pd.to_datetime(df["entry_date"])
df["cal_qtr"] = df["entry_date"].dt.to_period("Q")

# -------------------------------------------------------------------------------------------------
# 2. Precompute Derived Features & Metrics
# -------------------------------------------------------------------------------------------------
print("[W2_04] Precomputing derived features...")

# PEG Rev & NI PIT
pe = df["pe_pit"].values
rev_y = df["rev_yoy"].values
ni_y = df["ni_yoy"].values

peg_rev = np.where((pe > 0) & (rev_y > 0), pe / (rev_y * 100.0), np.where((pe <= 0) | (rev_y <= 0), -1.0, np.nan))
peg_ni = np.where((pe > 0) & (ni_y > 0), pe / (ni_y * 100.0), np.where((pe <= 0) | (ni_y <= 0), -1.0, np.nan))
df["peg_rev_pit_calc"] = peg_rev
df["peg_ni_pit_calc"] = peg_ni

# Universe definitions
df["is_large_cap"] = df["mcap_2026_equiv_b"] >= 25.0
df["is_mid_cap"] = (df["mcap_2026_equiv_b"] >= 5.0) & (df["mcap_2026_equiv_b"] < 25.0)

# State definitions
# 1. Baseline: All rows
# 2. 1Q Inflection: Single-quarter revenue growth acceleration (rev_accel_1q > 0)
df["is_1q_inflection"] = df["rev_accel_1q"] > 0.0
# 3. 3-4Q Trajectory: Consecutive 3+ quarters of revenue acceleration (consec_rev_accel_n >= 3)
df["is_3_4q_trajectory"] = df["consec_rev_accel_n"] >= 3

print(f"  Large Cap (>=25B): {df['is_large_cap'].sum():,} | Mid Cap (5-25B): {df['is_mid_cap'].sum():,}")
print(f"  1Q Inflection: {df['is_1q_inflection'].sum():,} | 3-4Q Trajectory: {df['is_3_4q_trajectory'].sum():,}")

# -------------------------------------------------------------------------------------------------
# 3. Define 14 Indicators & Binning Specifications
# -------------------------------------------------------------------------------------------------

PARAM_CONFIGS = [
    # 1. 缓涨时间长度 (Slow rally duration / time length)
    {
        "id": "param01",
        "name": "Slow_Rally_Duration",
        "csv_file": "param01_slow_rally_duration.csv",
        "submetrics": [
            {
                "submetric_name": "slow_uptrend_tag",
                "col": "slow_uptrend_tag",
                "type": "categorical",
                "bins": [
                    "SlowUp_2to5Y",
                    "SlowUp_6Mto2Y",
                    "TightBase_6M",
                    "DeepDrawdown_Left",
                    "HighFlyer_Parabolic",
                    "Other_Neutral"
                ]
            },
            {
                "submetric_name": "pos_21d_win_12m",
                "col": "pos_21d_win_12m",
                "type": "cut",
                "bins": [-np.inf, 0.35, 0.50, 0.60, 0.70, 0.85, np.inf],
                "labels": [
                    "<35% (持续阴跌)",
                    "35%~50% (偏弱震荡)",
                    "50%~60% (温和攀升)",
                    "60%~70% (扎实缓涨)",
                    "70%~85% (强势缓涨)",
                    ">85% (极端连阳高热)"
                ]
            }
        ]
    },
    # 2. 缓涨幅度 (Slow rally magnitude / runup)
    {
        "id": "param02",
        "name": "Slow_Rally_Magnitude",
        "csv_file": "param02_slow_rally_magnitude.csv",
        "submetrics": [
            {
                "submetric_name": "pre_ret_252d",
                "col": "pre_ret_252d",
                "type": "cut",
                "bins": [-np.inf, -0.20, 0.0, 0.15, 0.35, 0.60, 1.0, np.inf],
                "labels": [
                    "<-20% (超跌左侧)",
                    "-20%~0% (微跌筑底)",
                    "0%~15% (温和缓涨甜点)",
                    "15%~35% (扎实走牛)",
                    "35%~60% (强势主升)",
                    "60%~100% (加速热潮)",
                    ">100% (翻倍泡沫透支)"
                ]
            },
            {
                "submetric_name": "pre_ret_126d",
                "col": "pre_ret_126d",
                "type": "cut",
                "bins": [-np.inf, -0.15, 0.0, 0.10, 0.25, 0.50, np.inf],
                "labels": [
                    "<-15% (半年超跌)",
                    "-15%~0% (半年微跌)",
                    "0%~10% (温和小幅爬坡)",
                    "10%~25% (稳健上行)",
                    "25%~50% (强劲拉升)",
                    ">50% (半年暴涨)"
                ]
            }
        ]
    },
    # 3. 市值 (Market Cap)
    {
        "id": "param03",
        "name": "Market_Cap",
        "csv_file": "param03_market_cap.csv",
        "submetrics": [
            {
                "submetric_name": "mcap_2026_equiv_b",
                "col": "mcap_2026_equiv_b",
                "type": "cut",
                "bins": [0.0, 5.0, 15.0, 25.0, 50.0, 150.0, 500.0, np.inf],
                "labels": [
                    "<5B (小微盘)",
                    "5-15B (中盘成长)",
                    "15-25B (中大盘临界)",
                    "25-50B (大盘起跑)",
                    "50-150B (核心蓝筹)",
                    "150-500B (超大盘龙头)",
                    ">500B (万亿巨头)"
                ]
            },
            {
                "submetric_name": "mcap_usd_b",
                "col": "mcap_usd_b",
                "type": "cut",
                "bins": [0.0, 5.0, 15.0, 25.0, 50.0, 150.0, 500.0, np.inf],
                "labels": [
                    "<5B (名义小微盘)",
                    "5-15B (名义中盘)",
                    "15-25B (名义中大盘)",
                    "25-50B (名义大盘)",
                    "50-150B (名义核心蓝筹)",
                    "150-500B (名义龙头)",
                    ">500B (名义巨头)"
                ]
            }
        ]
    },
    # 4. PE (Price to Earnings)
    {
        "id": "param04",
        "name": "PE_PIT",
        "csv_file": "param04_pe.csv",
        "submetrics": [
            {
                "submetric_name": "pe_pit",
                "col": "pe_pit",
                "type": "cut",
                "bins": [-np.inf, 0.0, 10.0, 15.0, 20.0, 28.0, 40.0, 65.0, np.inf],
                "labels": [
                    "<0 (亏损)",
                    "0-10 (极低估/周期顶)",
                    "10-15 (传统低估)",
                    "15-20 (合理中枢)",
                    "20-28 (成长溢价)",
                    "28-40 (高景气成长)",
                    "40-65 (高估值预期)",
                    ">65 (极端高估)"
                ]
            }
        ]
    },
    # 5. PS (Price to Sales)
    {
        "id": "param05",
        "name": "PS_PIT",
        "csv_file": "param05_ps.csv",
        "submetrics": [
            {
                "submetric_name": "ps_pit",
                "col": "ps_pit",
                "type": "cut",
                "bins": [0.0, 1.5, 3.0, 6.0, 10.0, 15.0, 25.0, np.inf],
                "labels": [
                    "<1.5 (传统工业/低毛利)",
                    "1.5-3 (合理温和)",
                    "3-6 (优质成长中枢)",
                    "6-10 (高毛利成长)",
                    "10-15 (高溢价边界)",
                    "15-25 (极度乐观)",
                    ">25 (极端泡沫)"
                ]
            }
        ]
    },
    # 6. 收入增速 (Rev YoY)
    {
        "id": "param06",
        "name": "Rev_YoY",
        "csv_file": "param06_rev_yoy.csv",
        "submetrics": [
            {
                "submetric_name": "rev_yoy",
                "col": "rev_yoy",
                "type": "cut",
                "bins": [-np.inf, 0.0, 0.08, 0.15, 0.25, 0.40, 0.70, np.inf],
                "labels": [
                    "<0% (收入下滑)",
                    "0%~8% (低速平稳)",
                    "8%~15% (稳健良性)",
                    "15%~25% (优质成长甜点)",
                    "25%~40% (高速爆发)",
                    "40%~70% (超高速狂飙)",
                    ">70% (极端爆发/并购)"
                ]
            }
        ]
    },
    # 7. 利润增速 (Net Income YoY & Operating Income YoY)
    {
        "id": "param07",
        "name": "Profit_YoY",
        "csv_file": "param07_ni_yoy.csv",
        "submetrics": [
            {
                "submetric_name": "ni_yoy",
                "col": "ni_yoy",
                "type": "cut",
                "bins": [-np.inf, -0.30, 0.0, 0.15, 0.35, 0.70, 1.50, np.inf],
                "labels": [
                    "<-30% (净利重挫)",
                    "-30%~0% (净利下滑)",
                    "0%~15% (平稳正增)",
                    "15%~35% (稳健改善)",
                    "35%~70% (高弹性释放)",
                    "70%~150% (翻倍释放)",
                    ">150% (极端拐点/扭亏)"
                ]
            },
            {
                "submetric_name": "opinc_yoy",
                "col": "opinc_yoy",
                "type": "cut",
                "bins": [-np.inf, -0.30, 0.0, 0.15, 0.35, 0.70, 1.50, np.inf],
                "labels": [
                    "<-30% (营业利润重挫)",
                    "-30%~0% (营业利润下滑)",
                    "0%~15% (营业利润平稳)",
                    "15%~35% (营业利润稳增)",
                    "35%~70% (营业利润高增)",
                    "70%~150% (营业利润翻倍)",
                    ">150% (营业利润扭亏爆发)"
                ]
            }
        ]
    },
    # 8. ROE (Return on Equity)
    {
        "id": "param08",
        "name": "ROE",
        "csv_file": "param08_roe.csv",
        "submetrics": [
            {
                "submetric_name": "roe_ttm",
                "col": "roe_ttm",
                "type": "cut",
                "bins": [-np.inf, 0.0, 0.08, 0.15, 0.25, 0.40, np.inf],
                "labels": [
                    "<0% (ROE亏损)",
                    "0%~8% (低资本回报)",
                    "8%~15% (全市场中枢)",
                    "15%~25% (优秀资本回报)",
                    "25%~40% (顶级资本回报)",
                    ">40% (超常垄断/高杠杆)"
                ]
            }
        ]
    },
    # 9. ROIC (Return on Invested Capital)
    {
        "id": "param09",
        "name": "ROIC",
        "csv_file": "param09_roic.csv",
        "submetrics": [
            {
                "submetric_name": "roic_ttm",
                "col": "roic_ttm",
                "type": "cut",
                "bins": [-np.inf, 0.0, 0.08, 0.15, 0.25, 0.40, np.inf],
                "labels": [
                    "<0% (价值毁灭)",
                    "0%~8% (低于资本成本)",
                    "8%~15% (扎实达标)",
                    "15%~25% (优秀护城河)",
                    "25%~40% (顶级护城河)",
                    ">40% (超级定价权/轻资产)"
                ]
            }
        ]
    },
    # 10. PIT PEG (Price/Earnings-to-Growth)
    {
        "id": "param10",
        "name": "PIT_PEG",
        "csv_file": "param10_pit_peg.csv",
        "submetrics": [
            {
                "submetric_name": "peg_rev_pit",
                "col": "peg_rev_pit_calc",
                "type": "cut",
                "bins": [-np.inf, 0.0, 0.8, 1.5, 2.5, 4.0, np.inf],
                "labels": [
                    "<0 (亏损或负增长)",
                    "0-0.8 (极度低估)",
                    "0.8-1.5 (合理甜点)",
                    "1.5-2.5 (温和溢价)",
                    "2.5-4.0 (显著透支)",
                    ">4.0 (高估泡沫)"
                ]
            },
            {
                "submetric_name": "peg_ni_pit",
                "col": "peg_ni_pit_calc",
                "type": "cut",
                "bins": [-np.inf, 0.0, 0.8, 1.5, 2.5, 4.0, np.inf],
                "labels": [
                    "<0 (亏损或负增长)",
                    "0-0.8 (极度低估)",
                    "0.8-1.5 (合理甜点)",
                    "1.5-2.5 (温和溢价)",
                    "2.5-4.0 (显著透支)",
                    ">4.0 (高估泡沫)"
                ]
            }
        ]
    },
    # 11. 商业化边际贡献率 (GM minus SGA)
    {
        "id": "param11",
        "name": "Commercial_Margin_Contribution",
        "csv_file": "param11_gm_minus_sga.csv",
        "submetrics": [
            {
                "submetric_name": "gm_minus_sga_q",
                "col": "gm_minus_sga_q",
                "type": "cut",
                "bins": [-np.inf, -0.10, 0.0, 0.10, 0.25, 0.40, np.inf],
                "labels": [
                    "<-10% (严重吞噬毛利)",
                    "-10%~0% (微额倒贴)",
                    "0%~10% (打平初现造血)",
                    "10%~25% (初具规模商业化)",
                    "25%~40% (扎实商业化留存)",
                    ">40% (顶级商业化护城河)"
                ]
            },
            {
                "submetric_name": "consec_gm_sga_expand_n",
                "col": "consec_gm_sga_expand_n",
                "type": "cut",
                "bins": [-0.5, 0.5, 1.5, 2.5, 3.5, np.inf],
                "labels": [
                    "0季 (未扩张)",
                    "1季 (初次改善)",
                    "2季 (连续两季提升)",
                    "3季 (连续三季改善)",
                    "4+季 (持续规模效应)"
                ]
            }
        ]
    },
    # 12. 自由现金流转化率 (FCF Margin & OCF to NI)
    {
        "id": "param12",
        "name": "FCF_Conversion",
        "csv_file": "param12_fcf_conversion.csv",
        "submetrics": [
            {
                "submetric_name": "fcf_margin_ttm",
                "col": "fcf_margin_ttm",
                "type": "cut",
                "bins": [-np.inf, -0.05, 0.0, 0.05, 0.12, 0.20, 0.30, np.inf],
                "labels": [
                    "<-5% (失血烧钱)",
                    "-5%~0% (临界保本)",
                    "0%~5% (微额正FCF)",
                    "5%~12% (稳健转化)",
                    "12%~20% (优质现金流)",
                    "20%~30% (充沛现金牛)",
                    ">30% (顶级印钞机)"
                ]
            },
            {
                "submetric_name": "ocf_to_ni_ttm",
                "col": "ocf_to_ni_ttm",
                "type": "cut",
                "bins": [-np.inf, 0.5, 0.9, 1.2, 1.8, np.inf],
                "labels": [
                    "<0.5 (含金量低/应收堆积)",
                    "0.5-0.9 (低于净利润)",
                    "0.9-1.2 (扎实1:1匹配)",
                    "1.2-1.8 (高质现金转化)",
                    ">1.8 (极高现金奶牛)"
                ]
            }
        ]
    },
    # 13. 年度股本净稀释率 (Share Dilution YoY Clean)
    {
        "id": "param13",
        "name": "Share_Dilution_YoY",
        "csv_file": "param13_share_dilution.csv",
        "submetrics": [
            {
                "submetric_name": "dilution_yoy_clean",
                "col": "dilution_yoy_clean",
                "type": "cut",
                "bins": [-np.inf, -0.02, 0.0, 0.02, 0.05, np.inf],
                "labels": [
                    "净回购 <-2% (强力注销回购)",
                    "微缩 -2%~0% (温和净回购)",
                    "稳健 0~2% (常规低稀释)",
                    "偏高 2~5% (中度SBC稀释)",
                    "抽血稀释 >5% (恶性SBC抽血/增发)"
                ]
            }
        ]
    },
    # 14. 5年利润率历史分位 (OPM 5Y Percentile)
    {
        "id": "param14",
        "name": "OPM_5Y_Percentile",
        "csv_file": "param14_opm_5y_percentile.csv",
        "submetrics": [
            {
                "submetric_name": "opm_5y_pct_pit",
                "col": "opm_5y_pct_pit",
                "type": "cut",
                "bins": [0.0, 0.15, 0.35, 0.65, 0.85, 1.01],
                "labels": [
                    "0-15% (极低洼地/戴维斯起点)",
                    "15-35% (底部复苏期)",
                    "35-65% (中枢合理区间)",
                    "65-85% (高景气成熟期)",
                    "85-100% (周期极顶/戴维斯双杀高危)"
                ]
            }
        ]
    }
]

# -------------------------------------------------------------------------------------------------
# 4. Compute Grid Slices for All 14 Indicators
# -------------------------------------------------------------------------------------------------
UNIVERSES = [
    ("Large_Cap_25B+", df["is_large_cap"]),
    ("Mid_Cap_5_25B", df["is_mid_cap"])
]

STATES = [
    ("Baseline", pd.Series(True, index=df.index)),
    ("1Q_Inflection", df["is_1q_inflection"]),
    ("3_4Q_Trajectory", df["is_3_4q_trajectory"])
]

HORIZONS = (63, 252, 504, 756, 1260)
all_master_rows = []

print("\n" + "="*80)
print("[W2_04] Starting Slicing Engine across 14 Indicators...")
print("="*80)

for p_cfg in PARAM_CONFIGS:
    p_id = p_cfg["id"]
    p_name = p_cfg["name"]
    csv_file = p_cfg["csv_file"]
    p_rows = []

    print(f"\nProcessing {p_id}: {p_name} -> {csv_file}")
    
    for sub in p_cfg["submetrics"]:
        sub_name = sub["submetric_name"]
        col_name = sub["col"]
        m_type = sub["type"]

        # Assign bins
        if m_type == "categorical":
            valid_cats = sub["bins"]
            bin_series = df[col_name].astype(str)
            # Filter only specified categories
            bin_series = bin_series.where(bin_series.isin(valid_cats), np.nan)
            cat_list = valid_cats
        elif m_type == "cut":
            bins = sub["bins"]
            labels = sub["labels"]
            bin_series = pd.cut(df[col_name], bins=bins, labels=labels, right=False).astype(str)
            bin_series = bin_series.replace("nan", np.nan)
            cat_list = labels

        for b_idx, b_label in enumerate(cat_list):
            b_mask = (bin_series == b_label)
            if b_mask.sum() == 0:
                continue

            for u_label, u_mask in UNIVERSES:
                for s_label, s_mask in STATES:
                    combo_mask = b_mask & u_mask & s_mask
                    sub_df = df[combo_mask]
                    
                    label_str = f"{p_id}_{sub_name}_{b_label}_{u_label}_{s_label}"
                    stats_res = eval_slice(sub_df, horizons=HORIZONS, label=label_str)

                    # Assemble row
                    row_data = {
                        "param_id": p_id,
                        "param_name": p_name,
                        "submetric": sub_name,
                        "bin_order": b_idx,
                        "bin_label": b_label,
                        "universe": u_label,
                        "state": s_label,
                        "n_raw": stats_res.get("n_raw", 0),
                        "n_dedup": stats_res.get("n_dedup", 0),
                        "n_tickers": stats_res.get("n_tickers", 0),
                        "jump_mean": stats_res.get("jump_mean", np.nan),
                        "jump_ge10_prob": stats_res.get("jump_ge10_prob", np.nan),
                        "jump_ge8_prob": stats_res.get("jump_ge8_prob", np.nan),
                        "drop_le5_prob": stats_res.get("drop_le5_prob", np.nan),
                    }

                    for h in HORIZONS:
                        for k in ("n", "qtr_ew_alpha", "qtr_ew_ret", "dedup_mean_alpha", "med_alpha", "med_ret",
                                  "win_rate", "payoff", "bag2x_prob", "halve_prob", "t_stat", "p_val", "n_qtrs"):
                            field_name = f"{k}_{h}d"
                            row_data[field_name] = stats_res.get(field_name, np.nan)

                    row_data["med_mdd_1y"] = stats_res.get("med_mdd_1y", np.nan)
                    row_data["mdd50_1y_prob"] = stats_res.get("mdd50_1y_prob", np.nan)

                    p_rows.append(row_data)
                    all_master_rows.append(row_data)

    df_param = pd.DataFrame(p_rows)
    out_csv = os.path.join(RESULTS_DIR, csv_file)
    df_param.to_csv(out_csv, index=False)
    print(f"  Saved {len(df_param)} slices -> {out_csv}")

# Save master consolidated table
df_all_params = pd.DataFrame(all_master_rows)
all_csv_path = os.path.join(RESULTS_DIR, "all_14_params_marginal_and_inflection.csv")
df_all_params.to_csv(all_csv_path, index=False)
print(f"\n[W2_04] Successfully saved all 14 parameters ({len(df_all_params)} rows) -> {all_csv_path}!")

# -------------------------------------------------------------------------------------------------
# 5. Key Non-Linear & Fatal Interaction Effects (Requirement 2)
# -------------------------------------------------------------------------------------------------
print("\n" + "="*80)
print("[W2_04] Computing Key 2-Way & 3-Way Non-Linear Interactions...")
print("="*80)

interaction_rows = []

# --- Interaction 1: PS x (GM-SGA) x Dilution ---
# Objective: Reveal high PS viability boundaries (when can high PS win, and when is it fatal?)
ps_bins = [
    ("PS_Low_<3", (df["ps_pit"] > 0) & (df["ps_pit"] < 3.0)),
    ("PS_Mid_3to8", (df["ps_pit"] >= 3.0) & (df["ps_pit"] < 8.0)),
    ("PS_High_8to15", (df["ps_pit"] >= 8.0) & (df["ps_pit"] < 15.0)),
    ("PS_Extreme_>=15", df["ps_pit"] >= 15.0)
]

gm_sga_bins = [
    ("GM_SGA_Negative_<0%", df["gm_minus_sga_q"] < 0.0),
    ("GM_SGA_Low_0to15%", (df["gm_minus_sga_q"] >= 0.0) & (df["gm_minus_sga_q"] < 0.15)),
    ("GM_SGA_Good_15to30%", (df["gm_minus_sga_q"] >= 0.15) & (df["gm_minus_sga_q"] < 0.30)),
    ("GM_SGA_Top_>=30%", df["gm_minus_sga_q"] >= 0.30)
]

dilution_bins = [
    ("Dilution_Buyback_<=0%", df["dilution_yoy_clean"] <= 0.0),
    ("Dilution_Normal_0to2%", (df["dilution_yoy_clean"] > 0.0) & (df["dilution_yoy_clean"] <= 0.02)),
    ("Dilution_Moderate_2to4%", (df["dilution_yoy_clean"] > 0.02) & (df["dilution_yoy_clean"] <= 0.04)),
    ("Dilution_HeavySBC_>4%", df["dilution_yoy_clean"] > 0.04)
]

for ps_name, ps_mask in ps_bins:
    for gm_name, gm_mask in gm_sga_bins:
        for dil_name, dil_mask in dilution_bins:
            for u_label, u_mask in UNIVERSES:
                combo = ps_mask & gm_mask & dil_mask & u_mask
                if combo.sum() < 5:
                    continue
                label_str = f"PS_GMSGA_Dilution | {ps_name} | {gm_name} | {dil_name} | {u_label}"
                res = eval_slice(df[combo], horizons=HORIZONS, label=label_str)
                r_entry = {
                    "interaction_type": "PS_x_GMSGA_x_Dilution",
                    "dimension_1": ps_name,
                    "dimension_2": gm_name,
                    "dimension_3": dil_name,
                    "universe": u_label,
                    "state": "All",
                    "n_raw": res.get("n_raw", 0),
                    "n_dedup": res.get("n_dedup", 0),
                    "n_tickers": res.get("n_tickers", 0),
                    "jump_mean": res.get("jump_mean", np.nan),
                    "jump_ge10_prob": res.get("jump_ge10_prob", np.nan),
                    "drop_le5_prob": res.get("drop_le5_prob", np.nan),
                }
                for h in HORIZONS:
                    for k in ("qtr_ew_alpha", "med_alpha", "win_rate", "payoff", "bag2x_prob", "halve_prob", "t_stat", "p_val"):
                        r_entry[f"{k}_{h}d"] = res.get(f"{k}_{h}d", np.nan)
                r_entry["med_mdd_1y"] = res.get("med_mdd_1y", np.nan)
                r_entry["mdd50_1y_prob"] = res.get("mdd50_1y_prob", np.nan)
                interaction_rows.append(r_entry)

# --- Interaction 2: PE x ROIC x OPM 5Y Percentile ---
# Objective: Uncover true Davis Double Play vs Cyclical Peak Traps
pe_tiers = [
    ("PE_Value_<15", (df["pe_pit"] > 0) & (df["pe_pit"] < 15.0)),
    ("PE_GARP_15to25", (df["pe_pit"] >= 15.0) & (df["pe_pit"] < 25.0)),
    ("PE_Growth_25to40", (df["pe_pit"] >= 25.0) & (df["pe_pit"] < 40.0)),
    ("PE_High_>=40", df["pe_pit"] >= 40.0)
]

roic_tiers = [
    ("ROIC_Low_<10%", df["roic_ttm"] < 0.10),
    ("ROIC_Solid_10to20%", (df["roic_ttm"] >= 0.10) & (df["roic_ttm"] < 0.20)),
    ("ROIC_Elite_>=20%", df["roic_ttm"] >= 0.20)
]

opm_pct_tiers = [
    ("OPM_Trough_<=35%", df["opm_5y_pct_pit"] <= 0.35),
    ("OPM_Mid_35to75%", (df["opm_5y_pct_pit"] > 0.35) & (df["opm_5y_pct_pit"] <= 0.75)),
    ("OPM_Peak_>75%", df["opm_5y_pct_pit"] > 0.75)
]

for pe_name, pe_mask in pe_tiers:
    for roic_name, roic_mask in roic_tiers:
        for opm_name, opm_mask in opm_pct_tiers:
            for u_label, u_mask in UNIVERSES:
                combo = pe_mask & roic_mask & opm_mask & u_mask
                if combo.sum() < 5:
                    continue
                label_str = f"PE_ROIC_OPMPct | {pe_name} | {roic_name} | {opm_name} | {u_label}"
                res = eval_slice(df[combo], horizons=HORIZONS, label=label_str)
                r_entry = {
                    "interaction_type": "PE_x_ROIC_x_OPM5YPct",
                    "dimension_1": pe_name,
                    "dimension_2": roic_name,
                    "dimension_3": opm_name,
                    "universe": u_label,
                    "state": "All",
                    "n_raw": res.get("n_raw", 0),
                    "n_dedup": res.get("n_dedup", 0),
                    "n_tickers": res.get("n_tickers", 0),
                    "jump_mean": res.get("jump_mean", np.nan),
                    "jump_ge10_prob": res.get("jump_ge10_prob", np.nan),
                    "drop_le5_prob": res.get("drop_le5_prob", np.nan),
                }
                for h in HORIZONS:
                    for k in ("qtr_ew_alpha", "med_alpha", "win_rate", "payoff", "bag2x_prob", "halve_prob", "t_stat", "p_val"):
                        r_entry[f"{k}_{h}d"] = res.get(f"{k}_{h}d", np.nan)
                r_entry["med_mdd_1y"] = res.get("med_mdd_1y", np.nan)
                r_entry["mdd50_1y_prob"] = res.get("mdd50_1y_prob", np.nan)
                interaction_rows.append(r_entry)

# --- Interaction 3: Share Dilution / Buyback x Earnings Inflection Trajectory ---
# Objective: Measure 3-year net alpha spread: 3Q Accel + Net Buyback vs 3Q Accel + SBC Heavy Dilution
inflect_states = [
    ("No_Accel", df["rev_accel_1q"] <= 0),
    ("1Q_Inflect", df["is_1q_inflection"]),
    ("3_4Q_Trajectory", df["is_3_4q_trajectory"])
]

capital_actions = [
    ("Strong_Buyback_<-2%", df["dilution_yoy_clean"] <= -0.02),
    ("Mild_Buyback_-2%to0%", (df["dilution_yoy_clean"] > -0.02) & (df["dilution_yoy_clean"] <= 0.0)),
    ("Disciplined_Dilution_0to2%", (df["dilution_yoy_clean"] > 0.0) & (df["dilution_yoy_clean"] <= 0.02)),
    ("Moderate_SBC_2to5%", (df["dilution_yoy_clean"] > 0.02) & (df["dilution_yoy_clean"] <= 0.05)),
    ("Severe_SBC_Dilution_>5%", df["dilution_yoy_clean"] > 0.05)
]

for st_name, st_mask in inflect_states:
    for cap_name, cap_mask in capital_actions:
        for u_label, u_mask in UNIVERSES:
            combo = st_mask & cap_mask & u_mask
            if combo.sum() < 5:
                continue
            label_str = f"Dilution_x_Inflection | {st_name} | {cap_name} | {u_label}"
            res = eval_slice(df[combo], horizons=HORIZONS, label=label_str)
            r_entry = {
                "interaction_type": "Dilution_x_Inflection",
                "dimension_1": st_name,
                "dimension_2": cap_name,
                "dimension_3": "None",
                "universe": u_label,
                "state": st_name,
                "n_raw": res.get("n_raw", 0),
                "n_dedup": res.get("n_dedup", 0),
                "n_tickers": res.get("n_tickers", 0),
                "jump_mean": res.get("jump_mean", np.nan),
                "jump_ge10_prob": res.get("jump_ge10_prob", np.nan),
                "drop_le5_prob": res.get("drop_le5_prob", np.nan),
            }
            for h in HORIZONS:
                for k in ("qtr_ew_alpha", "med_alpha", "win_rate", "payoff", "bag2x_prob", "halve_prob", "t_stat", "p_val"):
                    r_entry[f"{k}_{h}d"] = res.get(f"{k}_{h}d", np.nan)
            r_entry["med_mdd_1y"] = res.get("med_mdd_1y", np.nan)
            r_entry["mdd50_1y_prob"] = res.get("mdd50_1y_prob", np.nan)
            interaction_rows.append(r_entry)

df_interact = pd.DataFrame(interaction_rows)
interact_csv_path = os.path.join(RESULTS_DIR, "key_2way_3way_interactions.csv")
df_interact.to_csv(interact_csv_path, index=False)
print(f"[W2_04] Saved {len(df_interact)} interaction slices -> {interact_csv_path}!")

# -------------------------------------------------------------------------------------------------
# 6. D15 Subperiod Robustness Verification (Requirement 3)
# -------------------------------------------------------------------------------------------------
print("\n" + "="*80)
print("[W2_04] Running D15 Subperiod Robustness Stress Tests...")
print("="*80)

CORE_STRATEGIES = [
    # 1. Benchmarks
    ("LargeCap_Baseline", df["is_large_cap"]),
    ("LargeCap_1Q_Inflection", df["is_large_cap"] & df["is_1q_inflection"]),
    ("LargeCap_3_4Q_Trajectory", df["is_large_cap"] & df["is_3_4q_trajectory"]),
    ("MidCap_Baseline", df["is_mid_cap"]),
    ("MidCap_1Q_Inflection", df["is_mid_cap"] & df["is_1q_inflection"]),
    ("MidCap_3_4Q_Trajectory", df["is_mid_cap"] & df["is_3_4q_trajectory"]),
    
    # 2. Key Sweet Spots
    (
        "SweetSpot_DavisDoublePlay",
        df["is_large_cap"] &
        (df["pe_pit"] >= 15.0) & (df["pe_pit"] < 30.0) &
        (df["roic_ttm"] >= 0.15) &
        (df["opm_5y_pct_pit"] <= 0.35)
    ),
    (
        "SweetSpot_EliteCompounder_ROIC20_Buyback",
        df["is_large_cap"] &
        (df["roic_ttm"] >= 0.20) &
        (df["dilution_yoy_clean"] <= 0.0) &
        (df["pe_pit"] > 0) & (df["pe_pit"] < 35.0)
    ),
    (
        "SweetSpot_3QTrajectory_NetBuyback",
        df["is_large_cap"] &
        df["is_3_4q_trajectory"] &
        (df["dilution_yoy_clean"] <= -0.01)
    ),
    (
        "SweetSpot_SlowRally_TightBase_3QAccel",
        df["is_large_cap"] &
        df["slow_uptrend_tag"].isin(["SlowUp_6Mto2Y", "TightBase_6M"]) &
        df["is_3_4q_trajectory"]
    ),
    
    # 3. Fatal Traps
    (
        "Trap_SaaS_HighPS_LowGMSGA_HighDilution",
        df["is_large_cap"] &
        (df["ps_pit"] >= 8.0) &
        (df["gm_minus_sga_q"] < 0.10) &
        (df["dilution_yoy_clean"] > 0.03)
    ),
    (
        "Trap_Cyclical_Peak_ValueTrap_LowPE_PeakMargin",
        df["is_large_cap"] &
        (df["pe_pit"] > 0) & (df["pe_pit"] < 15.0) &
        (df["opm_5y_pct_pit"] >= 0.85)
    ),
    (
        "Trap_Parabolic_Overheated_PreRet100",
        df["is_large_cap"] &
        (df["pre_ret_252d"] > 1.0)
    ),
    (
        "Trap_3QTrajectory_SevereSBC_Dilution",
        df["is_large_cap"] &
        df["is_3_4q_trajectory"] &
        (df["dilution_yoy_clean"] > 0.05)
    )
]

d15_dfs = []
for strat_name, strat_mask in CORE_STRATEGIES:
    sub = df[strat_mask].copy()
    if len(sub) >= 5:
        sub_d15 = eval_d15_subperiods(sub, date_col="entry_date", label=strat_name)
        sub_d15["strategy_name"] = strat_name
        d15_dfs.append(sub_d15)

df_d15 = pd.concat(d15_dfs, ignore_index=True)
d15_csv_path = os.path.join(RESULTS_DIR, "d15_subperiod_robustness.csv")
df_d15.to_csv(d15_csv_path, index=False)
print(f"[W2_04] Saved {len(df_d15)} D15 subperiod evaluations -> {d15_csv_path}!")

print("\n" + "="*80)
print(f"[W2_04] All calculations completed successfully in {time.time()-t0:.1f} seconds!")
print("="*80)
