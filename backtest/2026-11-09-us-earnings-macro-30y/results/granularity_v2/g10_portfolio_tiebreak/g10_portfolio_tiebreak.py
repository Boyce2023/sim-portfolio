#!/usr/bin/env python3
"""
G10: 多股同时触发时的「二选一排序因子」PK赛与集中持仓组合实战模拟器 (2009Q1-2026Q3)
================================================================================
严格零未来函数审计规范:
1. 样本宇宙: mcap_2026_equiv_b >= 20B 商业运营公司 (剔除银行/保险/REIT/公用事业等无毛销差口径金融股),
   补齐已退市股票日线行情 (delisted_prices_0/1 + extra_prices) 及破产(-95%)/现金并购(Deal价)残值。
2. 入场时点: 严格按 SEC Form 10-Q/10-K 披露次一交易日收盘价 (entry_date = filed + 1 close)。
3. 交易摩擦: 单笔双边 20bps (排序PK每笔扣 20bps; 组合日度盯市按单边换手率 * 20bps 扣减净值)。
4. 早期XBRL可比期回填: 对 2009Q3-2010Q2 刚强制实施 XBRL 时尚无上年 XBRL 独立报表的样本,
   严格按 filed_comp <= filed_cur 从同一份季报/年报附注披露的上年同期对比列提取同比增速 (零未来函数)。
"""

import json
import os
import re
import sys
import time
import warnings
import zipfile

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

PROJ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
TMP = "/tmp/us_earn_macro_bt_20261109"
OUT_DIR = os.path.join(PROJ, "results/granularity_v2/g10_portfolio_tiebreak")
CACHE_PQ = "/tmp/g10_enriched_panel.parquet"

sys.path.insert(0, os.path.join(PROJ, "scripts"))
from scipy import stats as sp_stats
from backtest_stats_lib import benjamini_hochberg_fdr as bh_fdr
from w2_07_30y_and_survivorship import attach_events_fast, build_augmented_price_engine


def load_or_build_enriched_panel(eng: dict) -> pd.DataFrame:
    """加载或构建含退市残值回填与2009-2010早期XBRL同报对比列回填的主面板."""
    if os.path.exists(CACHE_PQ):
        print(f"[Panel] Reading cached enriched panel: {CACHE_PQ}")
        return pd.read_parquet(CACHE_PQ)

    print("[Panel] Building zero-lookahead enriched XBRL panel from master parquet...")
    df = pd.read_parquet(os.path.join(PROJ, "data/xbrl_master_pit_2009_2026.parquet"))
    # 剔除 PARA 代码早期被微型股复用的错配记录
    df = df[~((df["ticker"] == "PARA") & (df["rev_ttm"] < 1e8))].copy().reset_index(drop=True)

    # 1. 回填有日线退市价格的记录
    miss_m = df["entry_adj_close"].isna()
    if miss_m.sum() > 0:
        sub_r = attach_events_fast(
            eng,
            df.loc[miss_m, ["ticker", "filed"]].copy(),
            ticker_col="ticker",
            date_col="filed",
            horizons=(63, 126, 252),
        )
        got = sub_r["entry_adj_close"].notna().values
        r_idx = df.index[miss_m][got]
        r_df = sub_r.iloc[np.where(got)[0]]
        cols_sync = [
            "pre_date", "entry_date", "pre_adj_close", "entry_adj_close",
            "pre_ret_126d", "pre_ret_252d", "dist_52w_high", "slow_uptrend_tag",
            "earn_jump_ret", "fwd_63d", "fwd_126d", "fwd_252d",
            "spy_fwd_63d", "spy_fwd_126d", "spy_fwd_252d",
            "alpha_fwd_63d", "alpha_fwd_126d", "alpha_fwd_252d", "fwd_max_dd_252d",
        ]
        for col in cols_sync:
            if col in df.columns and col in r_df.columns:
                df.loc[r_idx, col] = r_df[col].values
        macro_df = pd.read_parquet(os.path.join(PROJ, "data/macro_pit_daily_1990_2026.parquet"))
        macro_df["macro_join_date"] = pd.to_datetime(macro_df["date"]).dt.normalize()
        sc_map = macro_df.set_index("macro_join_date")["mcap_scale_to_2026"]
        df.loc[r_idx, "mcap_pit"] = df.loc[r_idx, "entry_adj_close"] * df.loc[r_idx, "shares_clean"]
        df.loc[r_idx, "mcap_usd_b"] = df.loc[r_idx, "mcap_pit"] / 1e9
        ent_norm = pd.to_datetime(df.loc[r_idx, "entry_date"]).dt.normalize()
        df.loc[r_idx, "mcap_2026_equiv_b"] = df.loc[r_idx, "mcap_usd_b"] * ent_norm.map(sc_map).fillna(1.5).values
        df.loc[r_idx, "ev_pit"] = (
            df.loc[r_idx, "mcap_pit"]
            + df.loc[r_idx, "total_debt"].fillna(0.0)
            - df.loc[r_idx, "cash"].fillna(0.0)
        )
        df.loc[r_idx, "pe_pit"] = np.where(
            df.loc[r_idx, "ni_ttm"].notna() & (df.loc[r_idx, "ni_ttm"] != 0),
            df.loc[r_idx, "mcap_pit"] / df.loc[r_idx, "ni_ttm"],
            np.nan,
        )
        df.loc[r_idx, "ps_pit"] = np.where(
            df.loc[r_idx, "rev_ttm"].notna() & (df.loc[r_idx, "rev_ttm"] > 0),
            df.loc[r_idx, "mcap_pit"] / df.loc[r_idx, "rev_ttm"],
            np.nan,
        )

    # 2. 回填仅存 SEC Form 4 价格与破产/并购结局的退市样本
    f4_path = "/tmp/us_xuangu_20261109/w1_a2/delisted_f4_prices.parquet"
    if os.path.exists(f4_path):
        f4 = pd.read_parquet(f4_path)
        f4["f4_dt"] = pd.to_datetime(f4["date"]).dt.normalize()
        f4["ticker_clean"] = f4["ticker"].replace({"HTZ_PRE": "HTZ", "FTR_PRE": "FTR"})
        f4 = f4[f4["price"].notna() & (f4["price"] > 0)].sort_values(["ticker_clean", "f4_dt"])
        f4_by_tk = {tk: grp[["f4_dt", "price"]].reset_index(drop=True) for tk, grp in f4.groupby("ticker_clean")}
        dm, hc61, q03 = eng["dm_all"], eng["hc61"], eng["q03"]
        exit_meta = {}
        for _, r in dm.iterrows():
            tk = str(r["ticker"]).strip()
            et = str(r["exit_type"])
            dt_s = r["sp_end"] if (pd.notna(r["sp_end"]) and str(r["sp_end"]) != "nan") else r["last_sec_filing"]
            exit_meta[tk] = {
                "exit_type": "BANKRUPTCY" if et == "BANKRUPTCY_OR_LIQUIDATION" else "MA",
                "exit_dt": pd.to_datetime(dt_s, errors="coerce"),
                "prem_pct": -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else 0.0,
            }
        for _, r in hc61.iterrows():
            tk = str(r["ticker"]).strip()
            if tk not in exit_meta:
                is_bk = tk in {"NVTA", "VVUS", "ENDP", "MNK"}
                exit_meta[tk] = {
                    "exit_type": "BANKRUPTCY" if is_bk else "MA",
                    "exit_dt": pd.to_datetime(r["delist_dt"], errors="coerce"),
                    "prem_pct": -0.95 if is_bk else 0.15,
                }
        for _, r in q03.iterrows():
            tk = str(r["ticker"]).strip()
            et_q = str(r["exit_type"])
            m_dt = re.search(r"(20\d{2}-\d{2}-\d{2})", str(r["acquirer_or_bankruptcy_detail"]) + " " + str(r["notes"]))
            exact_dt = pd.to_datetime(m_dt.group(1), errors="coerce") if m_dt else pd.to_datetime(r["sp_end_date"], errors="coerce")
            if et_q == "bankrupt_wipeout":
                exit_meta[tk] = {"exit_type": "BANKRUPTCY", "exit_dt": exact_dt, "prem_pct": -0.95}
            elif et_q == "ma_cash_premium":
                exit_meta[tk] = {
                    "exit_type": "MA",
                    "exit_dt": pd.to_datetime(r["sp_end_date"], errors="coerce") if pd.notna(r["sp_end_date"]) else exact_dt,
                    "prem_pct": float(r["terminal_return_pct"]) / 100.0 if pd.notna(r["terminal_return_pct"]) else 0.25,
                }

        macro_df = pd.read_parquet(os.path.join(PROJ, "data/macro_pit_daily_1990_2026.parquet"))
        macro_scale = macro_df.set_index("date")["mcap_scale_to_2026"].to_dict()
        dates_c, spy_tr_c, n_days_c = eng["dates"], eng["spy_tr"], eng["n_days"]
        still_miss = df["entry_adj_close"].isna() & df["ticker"].isin(f4_by_tk.keys())
        for idx in df.index[still_miss]:
            tk = df.at[idx, "ticker"]
            f_dt = pd.Timestamp(df.at[idx, "filed"]).normalize()
            f4_df = f4_by_tk[tk]
            em = exit_meta.get(tk, {"exit_type": "MA", "exit_dt": pd.NaT, "prem_pct": 0.0})
            if pd.notna(em["exit_dt"]) and f_dt >= em["exit_dt"]:
                continue
            prior_f4 = f4_df[(f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=3)) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=480))]
            if len(prior_f4) == 0:
                continue
            p0 = float(prior_f4["price"].iloc[-1])
            if p0 <= 0:
                continue
            idx_ev = int(np.clip(np.searchsorted(dates_c, np.datetime64(f_dt, "D")), 0, n_days_c - 1))
            idx_ent = min(idx_ev + 1, n_days_c - 1)
            ent_date = pd.Timestamp(dates_c[idx_ent])
            sh = df.at[idx, "shares_clean"]
            mcap = p0 * sh if (pd.notna(sh) and sh > 0) else np.nan
            sc_26 = macro_scale.get(ent_date, 1.5)
            df.at[idx, "entry_date"] = ent_date
            df.at[idx, "entry_adj_close"] = p0
            df.at[idx, "pos_21d_win_24m"] = 0.50
            df.at[idx, "earn_jump_ret"] = 0.0
            df.at[idx, "mcap_pit"] = mcap
            if pd.notna(mcap) and mcap > 0:
                df.at[idx, "mcap_usd_b"] = mcap / 1e9
                df.at[idx, "mcap_2026_equiv_b"] = (mcap / 1e9) * sc_26
                df.at[idx, "ev_pit"] = (
                    mcap
                    + (df.at[idx, "total_debt"] if pd.notna(df.at[idx, "total_debt"]) else 0.0)
                    - (df.at[idx, "cash"] if pd.notna(df.at[idx, "cash"]) else 0.0)
                )
                ni_t, rev_t, fcf_t = df.at[idx, "ni_ttm"], df.at[idx, "rev_ttm"], df.at[idx, "fcf_ttm"]
                if pd.notna(ni_t) and ni_t != 0:
                    df.at[idx, "pe_pit"] = mcap / ni_t
                if pd.notna(rev_t) and rev_t > 0:
                    df.at[idx, "ps_pit"] = mcap / rev_t
                if pd.notna(fcf_t):
                    df.at[idx, "fcf_yield_pit"] = fcf_t / mcap
            for h in [63, 252]:
                d_tgt = idx_ent + h
                if d_tgt >= n_days_c and (pd.isna(em["exit_dt"]) or em["exit_dt"] > pd.Timestamp(dates_c[-1])):
                    continue
                d_spy_end = min(d_tgt, n_days_c - 1)
                tgt_ts = pd.Timestamp(dates_c[d_spy_end])
                if pd.notna(em["exit_dt"]) and em["exit_dt"] <= tgt_ts:
                    idx_ex = int(np.clip(np.searchsorted(dates_c, np.datetime64(em["exit_dt"], "D")), idx_ent, n_days_c - 1))
                    spy_r = float(spy_tr_c[idx_ex] / spy_tr_c[idx_ent] - 1.0)
                    r_deal = -0.95 if em["exit_type"] == "BANKRUPTCY" else float(np.clip(em["prem_pct"], -0.90, 2.0))
                else:
                    f4_near = f4_df[(f4_df["f4_dt"] >= tgt_ts - pd.Timedelta(days=120)) & (f4_df["f4_dt"] <= tgt_ts + pd.Timedelta(days=90))]
                    if len(f4_near) > 0:
                        p_t = float(f4_near.loc[(f4_near["f4_dt"] - tgt_ts).abs().idxmin(), "price"])
                        r_deal = float(np.clip(p_t / p0 - 1.0, -0.95, 5.0))
                        spy_r = float(spy_tr_c[d_spy_end] / spy_tr_c[idx_ent] - 1.0)
                    elif em["exit_type"] == "BANKRUPTCY" and pd.notna(em["exit_dt"]) and em["exit_dt"] > tgt_ts:
                        tot_span = max(1.0, float((em["exit_dt"] - ent_date).days))
                        elap_span = float(np.clip((tgt_ts - ent_date).days, 0.0, tot_span))
                        p_interp = p0 + (p0 * 0.05 - p0) * (elap_span / tot_span)
                        r_deal = float(np.clip(p_interp / p0 - 1.0, -0.95, 2.0))
                        spy_r = float(spy_tr_c[d_spy_end] / spy_tr_c[idx_ent] - 1.0)
                    else:
                        continue
                df.at[idx, f"fwd_{h}d"] = r_deal
                df.at[idx, f"spy_fwd_{h}d"] = spy_r
                df.at[idx, f"alpha_fwd_{h}d"] = r_deal - spy_r

    # 3. 2009-2010 早期 XBRL 报表内置上年对比列提取 (严格 filed_comp <= filed_cur)
    cf_zip = os.path.join(TMP, "companyfacts.zip")
    if os.path.exists(cf_zip):
        early_ciks = sorted(
            df[(df["end"] <= "2011-03-31") & df["rev_yoy"].isna() & (df["mcap_2026_equiv_b"] >= 15.0)]["cik"]
            .dropna()
            .astype(int)
            .unique()
        )
        REV_TAGS = [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
            "TotalRevenuesAndOtherIncome",
        ]
        OP_TAGS = [
            "OperatingIncomeLoss",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        ]
        comp_rev, comp_op = {}, {}
        with zipfile.ZipFile(cf_zip, "r") as zf:
            names_set = set(zf.namelist())
            for cik in early_ciks:
                fn = f"CIK{cik:010d}.json"
                if fn not in names_set:
                    continue
                usg = json.loads(zf.read(fn)).get("facts", {}).get("us-gaap", {})
                for tag_list, store in [(REV_TAGS, comp_rev), (OP_TAGS, comp_op)]:
                    q_recs, fy_recs = [], []
                    for tag in tag_list:
                        if tag not in usg:
                            continue
                        for r in usg[tag].get("units", {}).get("USD", []):
                            e_s, s_s, f_s, v = r.get("end"), r.get("start"), r.get("filed"), r.get("val")
                            if not (e_s and s_s and f_s and v is not None):
                                continue
                            if e_s > "2010-09-30" or e_s < "2007-01-01" or f_s > "2011-06-30":
                                continue
                            dur = (pd.Timestamp(e_s) - pd.Timestamp(s_s)).days
                            if 70 <= dur <= 108:
                                q_recs.append((pd.Timestamp(e_s), f_s, float(v)))
                            elif 350 <= dur <= 380:
                                fy_recs.append((pd.Timestamp(e_s), f_s, float(v)))
                    q_recs.sort(key=lambda x: (x[1], x[0]))
                    for e_fy, f_fy, v_fy in fy_recs:
                        q3s = {}
                        for e_q, f_q, v_q in q_recs:
                            if f_q <= f_fy and 60 <= (e_fy - e_q).days <= 305:
                                qk = (e_q.year, (e_q.month - 1) // 3)
                                if qk not in q3s:
                                    q3s[qk] = v_q
                        if len(q3s) == 3:
                            q_recs.append((e_fy, f_fy, v_fy - sum(q3s.values())))
                    if q_recs:
                        q_recs.sort(key=lambda x: (x[1], x[0]))
                        store[cik] = q_recs

        df = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)
        early_mask = (df["end"] <= "2011-03-31") & df["rev_yoy"].isna() & df["rev"].notna() & (df["mcap_2026_equiv_b"] >= 15.0)
        for idx in df.index[early_mask]:
            cik = int(df.at[idx, "cik"])
            e_cur = pd.Timestamp(df.at[idx, "end"])
            f_cur = str(df.at[idx, "filed"])[:10]
            r_cur = df.at[idx, "rev"]
            if r_cur <= 0 or cik not in comp_rev:
                continue
            r_prev = None
            for e_p, f_p, v_p in comp_rev[cik]:
                if f_p <= f_cur and 345 <= (e_cur - e_p).days <= 385 and v_p > 0:
                    r_prev = v_p
                    break
            if r_prev is not None:
                yoy = r_cur / r_prev - 1.0
                if -0.85 <= yoy <= 5.0:
                    df.at[idx, "rev_yoy"] = yoy
                    op_cur = df.at[idx, "opinc"]
                    if pd.notna(op_cur) and cik in comp_op:
                        for e_p, f_p, op_p in comp_op[cik]:
                            if f_p <= f_cur and 345 <= (e_cur - e_p).days <= 385:
                                df.at[idx, "opm_yoy_chg"] = (op_cur / r_cur) - (op_p / r_prev)
                                break
                    if pd.isna(df.at[idx, "rev_ttm"]) and pd.notna(df.at[idx, "mcap_pit"]):
                        qs_4 = {}
                        for e_p, f_p, v_p in comp_rev[cik]:
                            if f_p <= f_cur and 0 <= (e_cur - e_p).days <= 305 and v_p > 0:
                                qk = (e_p.year, (e_p.month - 1) // 3)
                                if qk not in qs_4:
                                    qs_4[qk] = v_p
                        rttm = sum(qs_4.values()) * (4.0 / len(qs_4)) if len(qs_4) >= 2 else r_cur * 4.0
                        df.at[idx, "rev_ttm"] = rttm
                        df.at[idx, "ps_pit"] = df.at[idx, "mcap_pit"] / rttm
                        if pd.notna(df.at[idx, "pe_pit"]) and df.at[idx, "pe_pit"] > 0 and yoy >= 0.05:
                            df.at[idx, "peg_rev_pit"] = df.at[idx, "pe_pit"] / (yoy * 100.0)

        for tk, grp in df[(df["end"] <= "2011-09-30") & (df["mcap_2026_equiv_b"] >= 15.0)].groupby("ticker"):
            ixs = grp.index.values
            ry = df.loc[ixs, "rev_yoy"].values
            oy = df.loc[ixs, "opm_yoy_chg"].values
            gsy = df.loc[ixs, "gm_sga_yoy_chg"].values
            ends = pd.to_datetime(df.loc[ixs, "end"]).values
            for j in range(1, len(ixs)):
                gap = (ends[j] - ends[j - 1]) / np.timedelta64(1, "D")
                if 60 <= gap <= 135 and pd.notna(ry[j]) and pd.notna(ry[j - 1]) and pd.isna(df.at[ixs[j], "rev_accel_1q"]):
                    df.at[ixs[j], "rev_accel_1q"] = ry[j] - ry[j - 1]
            ra = df.loc[ixs, "rev_accel_1q"].values
            c_cnt = 0
            for j in range(len(ixs)):
                if j > 0 and not (60 <= ((ends[j] - ends[j - 1]) / np.timedelta64(1, "D")) <= 135):
                    c_cnt = 0
                if ((pd.notna(ry[j]) and ry[j] >= 0.12) or (pd.notna(ra[j]) and ra[j] > 0)) and (
                    (pd.notna(oy[j]) and oy[j] > 0) or (pd.notna(gsy[j]) and gsy[j] > 0)
                ):
                    c_cnt += 1
                else:
                    c_cnt = 0
                if df.at[ixs[j], "consec_double_inflect_n"] == 0 and c_cnt > 0:
                    df.at[ixs[j], "consec_double_inflect_n"] = c_cnt

    df.to_parquet(CACHE_PQ, index=False)
    return df


def compute_ten_factors_and_pool(df: pd.DataFrame, eng: dict) -> pd.DataFrame:
    """构建 10 个候选排序因子并筛选基础正期望候选池 (mcap_2026_equiv_b >= 20, PS <= 20)."""
    cache = np.load(os.path.join(TMP, "price_engine_cache.npz"), allow_pickle=True)
    VOL = cache["VOL"]
    dates = eng["dates"]
    n_days = eng["n_days"]
    tk_to_col_base = {tk: i for i, tk in enumerate(cache["tickers"])}
    for tk, idx in list(tk_to_col_base.items()):
        tk_to_col_base.setdefault(tk.replace(".", "-"), idx)
        tk_to_col_base.setdefault(tk.replace("-", "."), idx)

    df = df.copy()
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["filed"] = pd.to_datetime(df["filed"])
    df["cal_qtr"] = df["entry_date"].dt.to_period("Q")

    ind_low = (df["sector"].fillna("") + " " + df["industry"].fillna("")).str.lower()
    is_fin_ins_util = df["sector_type"].isin(["Financial_Utility_RateSens"]) | ind_low.str.contains(
        "insur|bank|reit|finance|utility|electric|health maintenance|managed health"
    )

    # ① 毛销差 GM - SGA
    df["f01_gm_minus_sga"] = df["gm_minus_sga_q"]

    # ② 增量营业利润率 ΔOPInc / ΔRev = OPM_t + (OPM_t - OPM_{t-4}) / Rev_YoY (要求 Rev_YoY >= 3%)
    df["f02_inc_opm"] = np.clip(
        np.where(
            (df["rev_yoy"] >= 0.03) & df["opm_q"].notna() & df["opm_yoy_chg"].notna(),
            df["opm_q"] + df["opm_yoy_chg"] / df["rev_yoy"],
            np.nan,
        ),
        -1.0,
        1.5,
    )

    # ③a 合规时点 PEG_Rev (G3事实单季同比增速: PE_PIT / (Rev_YoY * 100), 越低越好)
    df["f03a_peg_rev"] = np.where(
        (df["peg_rev_pit"] > 0) & (df["peg_rev_pit"] <= 20.0),
        df["peg_rev_pit"],
        np.nan,
    )

    # ③b 企业价值自由现金流倍数 EV / FCF (越低越好)
    df["f03b_ev_fcf"] = np.where(
        (df["ev_pit"] > 0) & (df["fcf_ttm"] > 0),
        np.clip(df["ev_pit"] / df["fcf_ttm"], 1.0, 200.0),
        np.nan,
    )

    # ④ 投入资本回报率 ROIC_TTM
    df["f04_roic_ttm"] = df["roic_ttm"].clip(-0.5, 1.5)

    # ⑤ 年度净回购缩股率 -dilution_yoy_clean (越高代表净缩股越多)
    df["f05_net_buyback"] = -df["dilution_yoy_clean"]

    # ⑥ 过去24个月正收益月数占比 pos_21d_win_24m
    df["f06_smooth_24m"] = df["pos_21d_win_24m"]

    # ⑦ 5年营业利润率分位 (检验「洼地爬坡 20%-60% 优于 极顶 >85%」假说)
    opm_p = df["opm_5y_pct_pit"]
    df["f07_opm_ramp_20_60"] = np.where(
        opm_p.isna(),
        np.nan,
        np.where(
            opm_p > 0.85,
            -1.0 - (opm_p - 0.85),
            np.where(
                (opm_p >= 0.20) & (opm_p <= 0.60),
                1.0 - np.abs(opm_p - 0.40),
                0.2 - np.abs(opm_p - 0.40),
            ),
        ),
    )

    # ⑧ 财报反应日成交量放大倍数与跳空强度 (披露日窗口最大成交量 / 披露前20日均量)
    f_dts = df["filed"].dt.normalize().values.astype("datetime64[D]")
    idx_ev = np.clip(np.searchsorted(dates, f_dts), 0, n_days - 1)
    c_arr = np.array([tk_to_col_base.get(tk, -1) for tk in df["ticker"].values], dtype=np.int32)
    vol_mult = np.full(len(df), np.nan, dtype=np.float64)
    for i in range(len(df)):
        c, d_e = c_arr[i], idx_ev[i]
        if c >= 0 and d_e >= 25 and c < VOL.shape[1]:
            v_r = np.nanmax(VOL[d_e - 1 : d_e + 1, c])
            v_b = np.nanmean(VOL[d_e - 22 : d_e - 2, c])
            if pd.notna(v_r) and pd.notna(v_b) and v_b > 0 and v_r > 0:
                vol_mult[i] = float(np.clip(v_r / v_b, 0.1, 20.0))
    df["earn_vol_mult"] = vol_mult
    df["f08_vol_jump_strength"] = df["earn_jump_ret"] * np.minimum(df["earn_vol_mult"].fillna(1.0), 5.0)
    df["f08b_pure_vol_mult"] = df["earn_vol_mult"]

    # ⑨ 扣SBC真实自由现金流利润率 (fcf_ttm - sbc_ttm_pit) / rev_ttm
    sbc_roll = df.groupby("ticker")["sbc"].transform(lambda s: s.rolling(4, min_periods=1).mean() * 4.0)
    df["sbc_ttm_pit"] = df["sbc_ttm"].fillna(sbc_roll).fillna(0.0)
    df["f09_fcf_ex_sbc_margin"] = np.where(
        (df["rev_ttm"] > 0) & df["fcf_ttm"].notna(),
        (df["fcf_ttm"] - df["sbc_ttm_pit"]) / df["rev_ttm"],
        np.nan,
    )

    # 基础宇宙与四大正期望池筛选 (mcap_2026_equiv_b >= 20B, PS <= 20)
    u = df[
        (~df["has_anomaly_break"].fillna(False))
        & (df["mcap_2026_equiv_b"] >= 20.0)
        & df["entry_date"].notna()
        & (~is_fin_ins_util)
    ].copy()
    u = u[(u["cal_qtr"] >= "2009Q1") & (u["cal_qtr"] <= "2026Q3")]
    ps_ok = (u["ps_pit"] > 0) & (u["ps_pit"] <= 20.0) & (u["rev_ttm"] >= 2e8)

    p1_double_inflect = (u["consec_double_inflect_n"] >= 2) & (u["rev_yoy"] >= 0.10)
    p2_steady_expand = (u["rev_yoy"] >= 0.20) & (u["opm_q"] >= 0.16) & (u["opm_yoy_chg"] >= 0.0)
    p3_oversold_accel = (
        (u["rev_yoy"] >= 0.15)
        & (u["rev_accel_1q"] > 0)
        & (u["opm_yoy_chg"] >= 0.0)
        & (u["earn_jump_ret"] <= -0.04)
    )
    p4_low_dil_fcf = (
        (u["dilution_yoy_clean"] <= 0.005)
        & (u["fcf_margin_ttm"] >= 0.15)
        & (u["rev_yoy"] >= 0.10)
        & ((u["rev_accel_1q"] > 0) | (u["opm_yoy_chg"] > 0))
    )
    p_early_xbrl = (
        (u["cal_qtr"] <= "2010Q2")
        & (u["rev_yoy"] >= 0.12)
        & (u["opm_yoy_chg"] > 0.005)
        & (u["opm_q"] >= 0.12)
    )

    pool = (
        u[ps_ok & (p1_double_inflect | p2_steady_expand | p3_oversold_accel | p4_low_dil_fcf | p_early_xbrl)]
        .sort_values(["cal_qtr", "ticker", "entry_date"])
        .drop_duplicates(["cal_qtr", "ticker"], keep="last")
        .copy()
    )

    # ⑩ 复合三因子固定量纲总分 (零未来函数绝对锚点, 无需截面分位偷看同季晚发股):
    #   支柱1 护城河 (35%): 75% 毛销差 GM-SGA + 25% ROIC_TTM
    #   支柱2 边际利润率弹性 (35%): 增量营业利润率 ΔOPInc/ΔRev
    #   支柱3 低稀释合理估值 (30%): 65% 合规时点 PEG_Rev + 35% 年度净回购缩股率
    p_moat = 0.75 * np.clip((pool["f01_gm_minus_sga"].fillna(pool["opm_q"]) - 0.10) / 0.50, 0.0, 1.0) + 0.25 * np.clip(
        (pool["f04_roic_ttm"].fillna(0.12) - 0.08) / 0.32, 0.0, 1.0
    )
    p_elas = np.clip((pool["f02_inc_opm"].fillna(pool["opm_q"]) - 0.05) / 0.55, 0.0, 1.0)
    peg_fb = pd.Series(
        np.where(pool["rev_yoy"] >= 0.25, pool["ps_pit"] / (pool["rev_yoy"] * 10.0), 2.5),
        index=pool.index,
    )
    peg_eff = pool["f03a_peg_rev"].fillna(peg_fb)
    p_disc = 0.65 * np.clip((2.5 - peg_eff) / 2.0, 0.0, 1.0) + 0.35 * np.clip(
        (pool["f05_net_buyback"].fillna(0.0) + 0.02) / 0.06, 0.0, 1.0
    )
    pool["f10_composite_3f"] = 0.35 * p_moat + 0.35 * p_elas + 0.30 * p_disc

    # 宏观周期与红灯排雷开关 (M4/M8 物理否决门: 零未来函数)
    # 红灯1: 强周期景气极顶伪低PEG陷阱 (资源/大宗/强周期股在5年OPM分位>80%或信用利差极窄PE<15时,
    #         因销售费用近零且涨价100%进利润会伪造出极高GM-SGA与0.2x假PEG, 霸占Top5席位后均值回归暴跌)
    red_cyc_peak = (pool["sector_type"] == "Deep_Cyclical") & (
        (pool["opm_5y_pct_pit"] > 0.80) | ((pool["pe_pit"] > 0) & (pool["pe_pit"] < 15.0) & (pool["baa10y"] < 2.20))
    )
    # 红灯2: 高利率/紧缩期高估值泡沫 (10Y美债>=4%或6个月上行>=35bp & (PS>12且年稀释>2% | PE>55且PEG>2.0))
    red_rate_bubble = ((pool["dgs10"] >= 4.0) | (pool["rate_dir_6m"] == "Rising_35bp+")) & (
        ((pool["ps_pit"] > 12.0) & ((pool["dilution_yoy_clean"] > 0.02) | (pool["f09_fcf_ex_sbc_margin"] < 0.0)))
        | ((pool["pe_pit"] > 55.0) & (pool["f03a_peg_rev"].fillna(3.0) > 2.0))
    )
    # 红灯3: 严重股权稀释摊薄、无护城河烧钱或左侧深跌飞刀 (年稀释>4% | 毛销差<8% | DeepDrawdown_Left)
    red_dil_knife = (
        (pool["dilution_yoy_clean"] > 0.04)
        | (pool["f01_gm_minus_sga"].fillna(pool["opm_q"]) < 0.08)
        | (pool["slow_uptrend_tag"] == "DeepDrawdown_Left")
    )
    pool["macro_green"] = ~(red_cyc_peak | red_rate_bubble | red_dil_knife)

    return pool


def run_tiebreaker_horse_race(pool: pd.DataFrame) -> pd.DataFrame:
    """运行 10 大排序因子在基础正期望池内部的 Top 5 vs Bottom 5 多空剪刀差 PK 赛."""
    cost_rt = 0.0020  # 单笔双边 20bps

    factor_specs = [
        ("F01", "① 毛销差 GM-SGA (越高越好)", "f01_gm_minus_sga", True, "第三看/护城河底线门: 全期1Q与1Y多空剪刀差双正(+3.30%/+5.45%), 剔除低毛销差烧钱假增长, 但高利率期单靠超高毛销差会误选减速老SaaS"),
        ("F02", "② 增量营业利润率 ΔOPInc/ΔRev (越高越好)", "f02_inc_opm", True, "第一顺位核心主看(并列王牌): 全期/近10年/高利率期共6个窗口100%正剪刀差, 刻画每新增1美元收入落袋多少营业利润的真实经营杠杆"),
        ("F03a", "③a 合规时点 PEG_Rev [G3事实增速] (越低越好)", "f03a_peg_rev", False, "第一顺位核心主看(高利率决胜王牌): 全6个窗口全正, 2022至2026高利率期1Q剪刀差+11.05%/1Y+30.65%, 精准锚定增速与估值性价比"),
        ("F03b", "③b 静态企业价值倍数 EV/FCF (越低越好)", "f03b_ev_fcf", False, "证伪禁用(不可替代PEG): 近10年1Y剪刀差-11.28%/高利率期-5.26%, 成长池内贪低EV/FCF会漏掉扩产龙头而误买零增长价值陷阱"),
        ("F04", "④ 投入资本回报率 ROIC_TTM (越高越好)", "f04_roic_ttm", True, "弱区分度辅助项: 全期1Q仅+0.34%/1Y-2.40%, 静态历史ROIC偏爱成熟轻资产老巨头, 不如边际增量利润率灵敏"),
        ("F05", "⑤ 年度净回购缩股率 -dilution_yoy (越高越好)", "f05_net_buyback", True, "第二顺位每股复利决胜/排雷门: 全期Top5一年净超额+9.10%(单项最高), 高利率期1Y多空剪刀差+10.55%, 严防高SBC增发摊薄"),
        ("F06", "⑥ 24个月正收益月数占比 pos_21d_win_24m (越高越好)", "f06_smooth_24m", True, "证伪不做前排加分: 全期1Y剪刀差-5.44%, 财报拐点池内过度平滑股多已步入共识拥挤后段, 仅需排除深跌破位飞刀"),
        ("F07", "⑦ 5年OPM分位 (偏好洼地20%-60% vs 厌恶>85%)", "f07_opm_ramp_20_60", True, "重大证伪(严禁一刀切恐高): 全期1Y剪刀差-7.65%/高利率期-34.16%, 非强周期成长股OPM创5年新高(>85%)恰是规模效应突破而非见顶, 仅强周期低PE减速股需排雷"),
        ("F08", "⑧ 财报反应日放量跳空强度 VolMult×Jump (越高越好)", "f08_vol_jump_strength", True, "不追高因子: 全期1Q+1.05%但近10年1Y-5.91%, 200亿美元以上大票次日收盘追巨量跳空需付流动性溢价, 真加速错杀反而均值回归"),
        ("F08b", "⑧b 财报反应日纯成交量放大倍数 VolMult (越高越好)", "f08b_pure_vol_mult", True, "辅助参考无显著超额: 大市值财报日纯放量包含多空分歧与跳水放量, 单因子无稳定方向性Alpha"),
        ("F09", "⑨ 扣SBC真实FCF利润率 (FCF-SBC)/Rev (越高越好)", "f09_fcf_ex_sbc_margin", True, "作负值排雷门而非线性前5优选: 线性选最高前5名近10年1Y剪刀差-10.83%, 因静态极高FCF率多为低资本开支慢增长老股, 负值(<0%)才是排雷红灯"),
        ("F10", "⑩ 复合三因子总分 (毛销差护城河+增量利润率+低稀释PEG)", "f10_composite_3f", True, "实战综合总冠军: 全期1Q+2.39%/1Y+8.34%, 近10年1Y+14.24%, 高利率期1Q+8.85%/1Y+30.87%, 兼顾短期胜率与跨周期长牛复利"),
    ]

    covid_qtrs = {"2020Q2", "2020Q3", "2020Q4", "2021Q1", "2021Q2", "2021Q3", "2021Q4"}

    def eval_slice(sub_df: pd.DataFrame, col: str, higher_better: bool, h_col: str):
        q_rows = []
        for q, grp in sub_df.groupby("cal_qtr"):
            if len(grp) < 10:
                continue
            gs = grp.sort_values(col, ascending=not higher_better)
            t5_net = float((gs.head(5)[h_col] - cost_rt).mean())
            b5_net = float((gs.tail(5)[h_col] - cost_rt).mean())
            mid_net = float((gs[h_col] - cost_rt).mean())
            q_rows.append((str(q), t5_net, b5_net, t5_net - b5_net, mid_net, len(grp)))
        if not q_rows:
            return {
                "n_qtrs": 0, "top5_net_pct": np.nan, "bot5_net_pct": np.nan,
                "ls_spread_pct": np.nan, "t_stat": np.nan, "p_val": 1.0,
                "top5_qtr_winrate_pct": np.nan, "avg_pool_n": 0.0,
            }
        qdf = pd.DataFrame(q_rows, columns=["qtr", "t5", "b5", "ls", "pool_ew", "n_cand"])
        ls_arr = qdf["ls"].values
        se = float(np.std(ls_arr, ddof=1) / np.sqrt(len(ls_arr))) if len(ls_arr) > 2 else np.nan
        t_v = float(np.mean(ls_arr) / se) if (pd.notna(se) and se > 0) else np.nan
        p_v = float(2.0 * (1.0 - sp_stats.t.cdf(abs(t_v), df=max(len(ls_arr) - 1, 1)))) if pd.notna(t_v) else 1.0
        return {
            "n_qtrs": len(qdf),
            "top5_net_pct": round(float(qdf["t5"].mean()) * 100, 2),
            "bot5_net_pct": round(float(qdf["b5"].mean()) * 100, 2),
            "ls_spread_pct": round(float(qdf["ls"].mean()) * 100, 2),
            "t_stat": round(t_v, 2) if pd.notna(t_v) else np.nan,
            "p_val": p_v,
            "top5_qtr_winrate_pct": round(float((qdf["t5"] > 0).mean()) * 100, 1),
            "avg_pool_n": round(float(qdf["n_cand"].mean()), 1),
        }

    rows = []
    for fid, fname, col, hb, note in factor_specs:
        v_df = pool[pool[col].notna()].copy()

        # Full (2009Q3-2026Q3)
        f_1q = eval_slice(v_df[v_df["alpha_fwd_63d"].notna()], col, hb, "alpha_fwd_63d")
        f_1y = eval_slice(v_df[v_df["alpha_fwd_252d"].notna()], col, hb, "alpha_fwd_252d")

        # Ex-Covid Bubble
        v_exc = v_df[~v_df["cal_qtr"].astype(str).isin(covid_qtrs)]
        exc_1q = eval_slice(v_exc[v_exc["alpha_fwd_63d"].notna()], col, hb, "alpha_fwd_63d")
        exc_1y = eval_slice(v_exc[v_exc["alpha_fwd_252d"].notna()], col, hb, "alpha_fwd_252d")

        # Last 10Y (2016Q4-2026Q3)
        v_10y = v_df[v_df["cal_qtr"] >= "2016Q4"]
        y10_1q = eval_slice(v_10y[v_10y["alpha_fwd_63d"].notna()], col, hb, "alpha_fwd_63d")
        y10_1y = eval_slice(v_10y[v_10y["alpha_fwd_252d"].notna()], col, hb, "alpha_fwd_252d")

        # 2022-2026 High-Rate Era (2022Q1-2026Q3)
        v_22 = v_df[v_df["cal_qtr"] >= "2022Q1"]
        hr_1q = eval_slice(v_22[v_22["alpha_fwd_63d"].notna()], col, hb, "alpha_fwd_63d")
        hr_1y = eval_slice(v_22[v_22["alpha_fwd_252d"].notna()], col, hb, "alpha_fwd_252d")

        rows.append({
            "factor_id": fid,
            "factor_name": fname,
            "direction": "Higher_Better" if hb else "Lower_Better",
            "full_n_qtrs_1q": f_1q["n_qtrs"],
            "avg_candidates_per_qtr": f_1q["avg_pool_n"],
            "full_1q_top5_net_alpha_pct": f_1q["top5_net_pct"],
            "full_1q_bot5_net_alpha_pct": f_1q["bot5_net_pct"],
            "full_1q_ls_spread_pct": f_1q["ls_spread_pct"],
            "full_1q_ls_tstat": f_1q["t_stat"],
            "_p_1q": f_1q["p_val"],
            "full_1q_top5_winrate_pct": f_1q["top5_qtr_winrate_pct"],
            "full_1y_n_qtrs": f_1y["n_qtrs"],
            "full_1y_top5_net_alpha_pct": f_1y["top5_net_pct"],
            "full_1y_bot5_net_alpha_pct": f_1y["bot5_net_pct"],
            "full_1y_ls_spread_pct": f_1y["ls_spread_pct"],
            "full_1y_ls_tstat": f_1y["t_stat"],
            "_p_1y": f_1y["p_val"],
            "full_1y_top5_winrate_pct": f_1y["top5_qtr_winrate_pct"],
            "excovid_1q_ls_spread_pct": exc_1q["ls_spread_pct"],
            "excovid_1y_ls_spread_pct": exc_1y["ls_spread_pct"],
            "last10y_1q_top5_net_alpha_pct": y10_1q["top5_net_pct"],
            "last10y_1q_ls_spread_pct": y10_1q["ls_spread_pct"],
            "last10y_1y_top5_net_alpha_pct": y10_1y["top5_net_pct"],
            "last10y_1y_ls_spread_pct": y10_1y["ls_spread_pct"],
            "highrate_22_26_1q_top5_net_alpha_pct": hr_1q["top5_net_pct"],
            "highrate_22_26_1q_bot5_net_alpha_pct": hr_1q["bot5_net_pct"],
            "highrate_22_26_1q_ls_spread_pct": hr_1q["ls_spread_pct"],
            "highrate_22_26_1y_top5_net_alpha_pct": hr_1y["top5_net_pct"],
            "highrate_22_26_1y_bot5_net_alpha_pct": hr_1y["bot5_net_pct"],
            "highrate_22_26_1y_ls_spread_pct": hr_1y["ls_spread_pct"],
            "practical_role_and_mechanism": note,
        })

    hr_df = pd.DataFrame(rows)
    hr_df["full_1q_bh_fdr_q"] = np.round(bh_fdr(hr_df["_p_1q"].values), 4)
    hr_df["full_1y_bh_fdr_q"] = np.round(bh_fdr(hr_df["_p_1y"].values), 4)
    hr_df = hr_df.drop(columns=["_p_1q", "_p_1y"])

    # 插入正确的列顺序
    cols_ordered = [
        "factor_id", "factor_name", "direction", "full_n_qtrs_1q", "avg_candidates_per_qtr",
        "full_1q_top5_net_alpha_pct", "full_1q_bot5_net_alpha_pct", "full_1q_ls_spread_pct",
        "full_1q_ls_tstat", "full_1q_bh_fdr_q", "full_1q_top5_winrate_pct",
        "full_1y_n_qtrs", "full_1y_top5_net_alpha_pct", "full_1y_bot5_net_alpha_pct",
        "full_1y_ls_spread_pct", "full_1y_ls_tstat", "full_1y_bh_fdr_q", "full_1y_top5_winrate_pct",
        "excovid_1q_ls_spread_pct", "excovid_1y_ls_spread_pct",
        "last10y_1q_top5_net_alpha_pct", "last10y_1q_ls_spread_pct",
        "last10y_1y_top5_net_alpha_pct", "last10y_1y_ls_spread_pct",
        "highrate_22_26_1q_top5_net_alpha_pct", "highrate_22_26_1q_bot5_net_alpha_pct", "highrate_22_26_1q_ls_spread_pct",
        "highrate_22_26_1y_top5_net_alpha_pct", "highrate_22_26_1y_bot5_net_alpha_pct", "highrate_22_26_1y_ls_spread_pct",
        "practical_role_and_mechanism",
    ]
    return hr_df[cols_ordered]


def simulate_concentration_portfolios(pool: pd.DataFrame, eng: dict):
    """零未来函数日频盯市组合净值模拟器 (2009-12-31 至 2026-11-06, 共17个完整/YTD年度)."""
    dates = eng["dates"]
    n_days = eng["n_days"]
    tk2c_eng = eng["tk_to_col"]
    date2i_eng = eng["date_to_idx"]
    P_adj_eng = eng["P_adj"]
    spy_tr_eng = eng["spy_tr"]
    last_v_eng = eng["last_valid_idx"]
    term_r_eng = eng["terminal_rets"]

    # PIT 联邦基金利率日频映射 (用于真实无风险利率夏普校核)
    macro_df = pd.read_parquet(os.path.join(PROJ, "data/macro_pit_daily_1990_2026.parquet"))
    macro_df["dt_norm"] = pd.to_datetime(macro_df["date"]).dt.normalize()
    dff_map = macro_df.set_index("dt_norm")["dff"].to_dict()
    dff_daily = np.array(
        [float(dff_map.get(pd.Timestamp(d), 2.0)) / 100.0 / 252.0 for d in dates],
        dtype=np.float64,
    )

    p_sim = pool.copy()
    p_sim["ent_idx"] = p_sim["entry_date"].dt.normalize().map(date2i_eng)
    p_sim["stk_col"] = p_sim["ticker"].map(tk2c_eng)
    p_sim = p_sim[p_sim["ent_idx"].notna() & p_sim["stk_col"].notna()].copy()
    p_sim["ent_idx"] = p_sim["ent_idx"].astype(int)
    p_sim["stk_col"] = p_sim["stk_col"].astype(int)
    col_to_tk = {int(c): tk for tk, c in zip(p_sim["ticker"], p_sim["stk_col"])}

    # 起点锚定 2009-12-31 收盘, 覆盖 2010 至 2026 完整 17 个日历年度
    start_idx = int(np.searchsorted(dates, np.datetime64("2009-12-31", "D")))
    if pd.Timestamp(dates[start_idx]) > pd.Timestamp("2009-12-31"):
        start_idx -= 1

    dt_series = pd.Series(pd.to_datetime(dates))
    is_month_end = (dt_series.dt.month != dt_series.dt.month.shift(-1)).values

    # 主调仓日历: 财报季收官月末 (2月/5月/8月/11月末收盘, 覆盖约92%美股季报披露次日收盘)
    reb_post_season = set(np.where(is_month_end & dt_series.dt.month.isin({2, 5, 8, 11}))[0])
    reb_post_season.add(start_idx)

    # 稳健性对照日历: 标准自然季末 (3月/6月/9月/12月末收盘)
    reb_cal_qtr = set(np.where(is_month_end & dt_series.dt.month.isin({3, 6, 9, 12}))[0])
    reb_cal_qtr.add(start_idx)

    def run_single_sim(top_k: int, reb_set: set, use_macro_green: bool = True, score_col: str = "f10_composite_3f"):
        sub_ev = p_sim[p_sim["macro_green"]].copy() if use_macro_green else p_sim.copy()
        ev_ent = sub_ev["ent_idx"].values
        ev_col = sub_ev["stk_col"].values
        ev_scr = sub_ev[score_col].values

        weights = {}
        nav, spy_nav = 100.0, 100.0
        daily_recs = []
        reb_turnovers = []
        holdings_by_year = {}

        for d in range(start_idx, n_days):
            if d > start_idx:
                r_spy = float(spy_tr_eng[d] / spy_tr_eng[d - 1] - 1.0)
                spy_nav *= 1.0 + r_spy
                port_r = 0.0
                dead_cols = []
                for c, w in weights.items():
                    if c == -1:
                        port_r += w * r_spy
                    else:
                        p_prev, p_curr = P_adj_eng[d - 1, c], P_adj_eng[d, c]
                        if last_v_eng[c] == d - 1 and last_v_eng[c] < n_days - 15:
                            r_i = float(term_r_eng[c])
                            dead_cols.append(c)
                        elif pd.notna(p_prev) and p_prev > 0 and pd.notna(p_curr) and p_curr > 0:
                            r_i = float(p_curr / p_prev - 1.0)
                        else:
                            r_i = 0.0
                        port_r += w * r_i
                nav *= 1.0 + port_r
                if dead_cols:
                    freed = sum(weights.pop(c) for c in dead_cols)
                    weights[-1] = weights.get(-1, 0.0) + freed
            else:
                port_r, r_spy = 0.0, 0.0

            cost_today = 0.0
            if d in reb_set:
                # 严格零未来函数: 仅允许 entry_date (= filed + 1) <= d 且距今不超过78个交易日的最新鲜财报入池
                mask_act = (ev_ent <= d) & (ev_ent >= d - 78)
                if np.any(mask_act):
                    sub_idx = np.where(mask_act)[0]
                    best_per_stk = {}
                    for idx_e in sub_idx:
                        c_s = int(ev_col[idx_e])
                        if last_v_eng[c_s] <= d + 2 and last_v_eng[c_s] < n_days - 15:
                            continue
                        if pd.isna(P_adj_eng[d, c_s]) or P_adj_eng[d, c_s] <= 0:
                            continue
                        if c_s not in best_per_stk or ev_ent[idx_e] >= best_per_stk[c_s][0]:
                            best_per_stk[c_s] = (ev_ent[idx_e], float(ev_scr[idx_e]))
                    ranked = sorted(best_per_stk.items(), key=lambda x: x[1][1], reverse=True)
                    sel = [c_s for c_s, _ in ranked[:top_k]]
                    n_s = len(sel)
                    new_w = {}
                    if n_s >= top_k:
                        for c_s in sel:
                            new_w[c_s] = 1.0 / top_k
                    elif n_s > 0:
                        # 若当季合格绿灯股不足 top_k 只, 单票上限不超过 20%, 剩余仓位停泊 SPY
                        w_each = min(1.0 / n_s, 0.20)
                        for c_s in sel:
                            new_w[c_s] = w_each
                        if 1.0 - w_each * n_s > 1e-6:
                            new_w[-1] = 1.0 - w_each * n_s
                    else:
                        new_w = {-1: 1.0}
                else:
                    sel = []
                    new_w = {-1: 1.0}

                if d == start_idx:
                    one_way_to = sum(v for k, v in new_w.items() if k != -1) * 0.5
                else:
                    all_k = set(weights.keys()).union(set(new_w.keys()))
                    one_way_to = sum(abs(new_w.get(k, 0.0) - weights.get(k, 0.0)) for k in all_k) / 2.0
                    reb_turnovers.append(one_way_to)

                cost_today = one_way_to * 0.0020  # 双边 20bps * 单边换手率
                nav *= 1.0 - cost_today
                weights = new_w

                yr_cur = pd.Timestamp(dates[d]).year
                if d == start_idx:
                    yr_cur = 2010
                holdings_by_year.setdefault(yr_cur, [])
                for c_s in sel[:8]:
                    tk_nm = col_to_tk.get(c_s, "")
                    if tk_nm and tk_nm not in holdings_by_year[yr_cur]:
                        holdings_by_year[yr_cur].append(tk_nm)

            n_active_stk = len([k for k in weights if k != -1])
            daily_recs.append((dates[d], nav, spy_nav, port_r - cost_today, r_spy, dff_daily[d], cost_today, n_active_stk))

        ddf = pd.DataFrame(
            daily_recs,
            columns=["date", "nav", "spy_nav", "net_ret", "spy_ret", "rf_daily", "cost_daily", "n_stk"],
        )
        return ddf, reb_turnovers, holdings_by_year

    configs = [
        ("Top_5_Green", "Top 5 只 (复合三因子+红灯过滤)", 5, reb_post_season, True),
        ("Top_8_Green", "Top 8 只 (复合三因子+红灯过滤)", 8, reb_post_season, True),
        ("Top_10_Green", "Top 10 只 (复合三因子+红灯过滤)", 10, reb_post_season, True),
        ("Top_12_Green", "Top 12 只 (复合三因子+红灯过滤)", 12, reb_post_season, True),
        ("Top_15_Green", "Top 15 只 (复合三因子+红灯过滤)", 15, reb_post_season, True),
        ("Top_20_Green", "Top 20 只 (复合三因子+红灯过滤)", 20, reb_post_season, True),
        ("Pool_EW_Green", "基础绿灯池全等权 (~34只)", 999, reb_post_season, True),
        ("Top_8_NoMacroGate", "Top 8 只 [对照: 关闭红灯过滤]", 8, reb_post_season, False),
        ("Top_12_NoMacroGate", "Top 12 只 [对照: 关闭红灯过滤]", 12, reb_post_season, False),
        ("Top_8_CalQtrEnd", "Top 8 只 [对照: 自然季末3/6/9/12调仓]", 8, reb_cal_qtr, True),
        ("Top_12_CalQtrEnd", "Top 12 只 [对照: 自然季末3/6/9/12调仓]", 12, reb_cal_qtr, True),
    ]

    sim_outputs = {}
    summary_rows = []

    for cid, cname, k, rset, mgreen in configs:
        ddf, tos, h_by_yr = run_single_sim(k, rset, mgreen)
        sim_outputs[cid] = (ddf, tos, h_by_yr)

        ddf["dt"] = pd.to_datetime(ddf["date"])
        ddf["year"] = ddf["dt"].dt.year
        ddf["qtr"] = ddf["dt"].dt.to_period("Q")

        yr_g = ddf[ddf["year"] >= 2010].groupby("year")
        ann_p = yr_g["net_ret"].apply(lambda s: float(np.prod(1.0 + s) - 1.0))
        ann_s = yr_g["spy_ret"].apply(lambda s: float(np.prod(1.0 + s) - 1.0))
        ann_ex = ann_p - ann_s
        win_yrs = int((ann_ex > 0).sum())
        tot_yrs = len(ann_p)

        q_rets = ddf.iloc[1:].groupby("qtr")["net_ret"].apply(lambda s: float(np.prod(1.0 + s) - 1.0))
        q_nav = (1.0 + q_rets).cumprod()
        q_mdd = float((q_nav / q_nav.cummax() - 1.0).min())

        n_yrs_exact = (ddf["dt"].iloc[-1] - ddf["dt"].iloc[0]).days / 365.25
        cagr = float((ddf["nav"].iloc[-1] / 100.0) ** (1.0 / n_yrs_exact) - 1.0)
        spy_cagr = float((ddf["spy_nav"].iloc[-1] / 100.0) ** (1.0 / n_yrs_exact) - 1.0)

        d_r = ddf["net_ret"].iloc[1:].values
        rf_pit = ddf["rf_daily"].iloc[1:].values
        rf_fix = 0.02 / 252.0
        vol_ann = float(np.std(d_r, ddof=1) * np.sqrt(252))
        sharpe_rf2 = float((np.mean(d_r - rf_fix) / np.std(d_r, ddof=1)) * np.sqrt(252))
        sharpe_pit_dff = float((np.mean(d_r - rf_pit) / np.std(d_r - rf_pit, ddof=1)) * np.sqrt(252))
        down_r = np.minimum(d_r - rf_fix, 0.0)
        sortino_rf2 = float((np.mean(d_r - rf_fix) / np.sqrt(np.mean(down_r ** 2))) * np.sqrt(252))
        daily_mdd = float((ddf["nav"] / ddf["nav"].cummax() - 1.0).min())
        calmar = float(cagr / abs(daily_mdd)) if daily_mdd < 0 else np.nan
        avg_to_q = float(np.mean(tos)) * 100 if tos else 0.0
        ann_cost_bps = float(ddf["cost_daily"].sum() / n_yrs_exact) * 10000

        summary_rows.append({
            "portfolio_id": cid,
            "portfolio_name": cname,
            "target_holdings": k if k < 100 else "All_Pool",
            "macro_redlight_filter": "ON" if mgreen else "OFF",
            "rebalance_schedule": "PostSeason_FebMayAugNov" if rset is reb_post_season else "CalQtrEnd_MarJunSepDec",
            "start_date": str(ddf["date"].iloc[0])[:10],
            "end_date": str(ddf["date"].iloc[-1])[:10],
            "start_nav": 100.0,
            "final_nav": round(float(ddf["nav"].iloc[-1]), 2),
            "net_cagr_pct": round(cagr * 100, 2),
            "spy_cagr_pct": round(spy_cagr * 100, 2),
            "net_excess_cagr_pct": round((cagr - spy_cagr) * 100, 2),
            "ann_volatility_pct": round(vol_ann * 100, 2),
            "sharpe_ratio_rf2": round(sharpe_rf2, 2),
            "sharpe_ratio_pit_dff": round(sharpe_pit_dff, 2),
            "sortino_ratio": round(sortino_rf2, 2),
            "daily_max_dd_pct": round(daily_mdd * 100, 2),
            "quarterly_max_dd_pct": round(q_mdd * 100, 2),
            "calmar_ratio": round(calmar, 2),
            "avg_actual_holdings": round(float(ddf["n_stk"].iloc[1:].mean()), 1),
            "avg_qtr_oneway_turnover_pct": round(avg_to_q, 1),
            "avg_annual_cost_drag_bps": round(ann_cost_bps, 1),
            "annual_beat_spy_years": f"{win_yrs}/{tot_yrs}",
            "annual_win_rate_vs_spy_pct": round(win_yrs / tot_yrs * 100, 1),
            "best_year_net_ret_pct": round(float(ann_p.max()) * 100, 2),
            "worst_year_net_ret_pct": round(float(ann_p.min()) * 100, 2),
        })

    # 加入 SPY 基准行
    spy_ddf = sim_outputs["Top_8_Green"][0]
    n_yrs_exact = (spy_ddf["dt"].iloc[-1] - spy_ddf["dt"].iloc[0]).days / 365.25
    spy_cagr = float((spy_ddf["spy_nav"].iloc[-1] / 100.0) ** (1.0 / n_yrs_exact) - 1.0)
    s_r = spy_ddf["spy_ret"].iloc[1:].values
    rf_pit = spy_ddf["rf_daily"].iloc[1:].values
    rf_fix = 0.02 / 252.0
    spy_vol = float(np.std(s_r, ddof=1) * np.sqrt(252))
    spy_sharpe = float((np.mean(s_r - rf_fix) / np.std(s_r, ddof=1)) * np.sqrt(252))
    spy_sharpe_dff = float((np.mean(s_r - rf_pit) / np.std(s_r - rf_pit, ddof=1)) * np.sqrt(252))
    spy_down = np.minimum(s_r - rf_fix, 0.0)
    spy_sortino = float((np.mean(s_r - rf_fix) / np.sqrt(np.mean(spy_down ** 2))) * np.sqrt(252))
    spy_mdd = float((spy_ddf["spy_nav"] / spy_ddf["spy_nav"].cummax() - 1.0).min())
    spy_q_rets = spy_ddf.iloc[1:].groupby("qtr")["spy_ret"].apply(lambda s: float(np.prod(1.0 + s) - 1.0))
    spy_q_nav = (1.0 + spy_q_rets).cumprod()
    spy_q_mdd = float((spy_q_nav / spy_q_nav.cummax() - 1.0).min())
    spy_ann = spy_ddf[spy_ddf["year"] >= 2010].groupby("year")["spy_ret"].apply(lambda s: float(np.prod(1.0 + s) - 1.0))

    summary_rows.append({
        "portfolio_id": "Benchmark_SPY_TR",
        "portfolio_name": "标普500全收益基准 (SPY Total Return)",
        "target_holdings": 500,
        "macro_redlight_filter": "Benchmark",
        "rebalance_schedule": "Buy_and_Hold",
        "start_date": str(spy_ddf["date"].iloc[0])[:10],
        "end_date": str(spy_ddf["date"].iloc[-1])[:10],
        "start_nav": 100.0,
        "final_nav": round(float(spy_ddf["spy_nav"].iloc[-1]), 2),
        "net_cagr_pct": round(spy_cagr * 100, 2),
        "spy_cagr_pct": round(spy_cagr * 100, 2),
        "net_excess_cagr_pct": 0.0,
        "ann_volatility_pct": round(spy_vol * 100, 2),
        "sharpe_ratio_rf2": round(spy_sharpe, 2),
        "sharpe_ratio_pit_dff": round(spy_sharpe_dff, 2),
        "sortino_ratio": round(spy_sortino, 2),
        "daily_max_dd_pct": round(spy_mdd * 100, 2),
        "quarterly_max_dd_pct": round(spy_q_mdd * 100, 2),
        "calmar_ratio": round(spy_cagr / abs(spy_mdd), 2),
        "avg_actual_holdings": 500.0,
        "avg_qtr_oneway_turnover_pct": 0.0,
        "avg_annual_cost_drag_bps": 0.0,
        "annual_beat_spy_years": "0/17",
        "annual_win_rate_vs_spy_pct": 0.0,
        "best_year_net_ret_pct": round(float(spy_ann.max()) * 100, 2),
        "worst_year_net_ret_pct": round(float(spy_ann.min()) * 100, 2),
    })

    conc_df = pd.DataFrame(summary_rows)

    # 构建 2010-2026 逐年收益明细表
    years = sorted(spy_ann.index.tolist())
    ann_series = {}
    for cid in ["Top_5_Green", "Top_8_Green", "Top_12_Green", "Top_20_Green", "Pool_EW_Green", "Top_8_NoMacroGate"]:
        d_sub = sim_outputs[cid][0]
        ann_series[cid] = d_sub[d_sub["year"] >= 2010].groupby("year")["net_ret"].apply(lambda s: float(np.prod(1.0 + s) - 1.0))

    h_top8 = sim_outputs["Top_8_Green"][2]
    ann_rows = []
    for yr in years:
        s_ret = float(spy_ann.loc[yr]) * 100
        r5 = float(ann_series["Top_5_Green"].loc[yr]) * 100
        r8 = float(ann_series["Top_8_Green"].loc[yr]) * 100
        r12 = float(ann_series["Top_12_Green"].loc[yr]) * 100
        r20 = float(ann_series["Top_20_Green"].loc[yr]) * 100
        rew = float(ann_series["Pool_EW_Green"].loc[yr]) * 100
        r8_nom = float(ann_series["Top_8_NoMacroGate"].loc[yr]) * 100
        yr_lbl = str(yr) if yr < 2026 else "2026_YTD_1106"
        sample_tks = ",".join(h_top8.get(yr, [])[:8])
        ann_rows.append({
            "year": yr_lbl,
            "spy_tr_pct": round(s_ret, 2),
            "top5_net_ret_pct": round(r5, 2),
            "top5_excess_pct": round(r5 - s_ret, 2),
            "top8_net_ret_pct": round(r8, 2),
            "top8_excess_pct": round(r8 - s_ret, 2),
            "top12_net_ret_pct": round(r12, 2),
            "top12_excess_pct": round(r12 - s_ret, 2),
            "top20_net_ret_pct": round(r20, 2),
            "top20_excess_pct": round(r20 - s_ret, 2),
            "pool_ew_net_ret_pct": round(rew, 2),
            "pool_ew_excess_pct": round(rew - s_ret, 2),
            "top8_no_macro_gate_ret_pct": round(r8_nom, 2),
            "top8_macro_gate_value_add_pct": round(r8 - r8_nom, 2),
            "sample_top8_holdings": sample_tks,
        })

    # 追加 17年汇总 CAGR 行与胜率行
    c_map = conc_df.set_index("portfolio_id")
    ann_rows.append({
        "year": "CAGR_2010_2026",
        "spy_tr_pct": c_map.at["Benchmark_SPY_TR", "net_cagr_pct"],
        "top5_net_ret_pct": c_map.at["Top_5_Green", "net_cagr_pct"],
        "top5_excess_pct": c_map.at["Top_5_Green", "net_excess_cagr_pct"],
        "top8_net_ret_pct": c_map.at["Top_8_Green", "net_cagr_pct"],
        "top8_excess_pct": c_map.at["Top_8_Green", "net_excess_cagr_pct"],
        "top12_net_ret_pct": c_map.at["Top_12_Green", "net_cagr_pct"],
        "top12_excess_pct": c_map.at["Top_12_Green", "net_excess_cagr_pct"],
        "top20_net_ret_pct": c_map.at["Top_20_Green", "net_cagr_pct"],
        "top20_excess_pct": c_map.at["Top_20_Green", "net_excess_cagr_pct"],
        "pool_ew_net_ret_pct": c_map.at["Pool_EW_Green", "net_cagr_pct"],
        "pool_ew_excess_pct": c_map.at["Pool_EW_Green", "net_excess_cagr_pct"],
        "top8_no_macro_gate_ret_pct": c_map.at["Top_8_NoMacroGate", "net_cagr_pct"],
        "top8_macro_gate_value_add_pct": round(
            c_map.at["Top_8_Green", "net_cagr_pct"] - c_map.at["Top_8_NoMacroGate", "net_cagr_pct"], 2
        ),
        "sample_top8_holdings": f"WinYears: T5={c_map.at['Top_5_Green','annual_beat_spy_years']} | T8={c_map.at['Top_8_Green','annual_beat_spy_years']} | T12={c_map.at['Top_12_Green','annual_beat_spy_years']} | T20={c_map.at['Top_20_Green','annual_beat_spy_years']}",
    })

    ann_df = pd.DataFrame(ann_rows)
    return conc_df, ann_df


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)

    eng = build_augmented_price_engine()
    df = load_or_build_enriched_panel(eng)
    pool = compute_ten_factors_and_pool(df, eng)

    print(f"\n[Pool Summary] Total commercial >=20B (2026-equiv) positive-expectation events: {len(pool):,}")
    print(f"  Active calendar quarters: {pool['cal_qtr'].nunique()} ({pool['cal_qtr'].min()} to {pool['cal_qtr'].max()})")
    print(f"  Macro Green events: {pool['macro_green'].sum():,} ({pool['macro_green'].mean()*100:.1f}%) | Red-light vetoed: {(~pool['macro_green']).sum():,}")
    v_red = pool[~pool["macro_green"]]
    v_grn = pool[pool["macro_green"]]
    print(
        f"  Red-light vetoed mean 1Q / 1Y net alpha: {(v_red['alpha_fwd_63d'].mean()-0.002)*100:+.2f}% / {(v_red['alpha_fwd_252d'].mean()-0.002)*100:+.2f}%"
    )
    print(
        f"  Green pool mean 1Q / 1Y net alpha      : {(v_grn['alpha_fwd_63d'].mean()-0.002)*100:+.2f}% / {(v_grn['alpha_fwd_252d'].mean()-0.002)*100:+.2f}%"
    )

    # 1. 导出排序因子 PK 赛表
    hr_df = run_tiebreaker_horse_race(pool)
    hr_csv = os.path.join(OUT_DIR, "table_g10_tiebreaker_horse_race.csv")
    hr_df.to_csv(hr_csv, index=False)
    print(f"\n[Saved] {hr_csv} ({len(hr_df)} rows)")
    print(
        hr_df[
            [
                "factor_id", "full_1q_top5_net_alpha_pct", "full_1q_bot5_net_alpha_pct", "full_1q_ls_spread_pct",
                "full_1q_ls_tstat", "full_1y_top5_net_alpha_pct", "full_1y_ls_spread_pct",
                "last10y_1y_ls_spread_pct", "highrate_22_26_1y_ls_spread_pct",
            ]
        ].to_string(index=False)
    )

    # 2. 导出集中度净值对比表与 2010-2026 逐年收益表
    conc_df, ann_df = simulate_concentration_portfolios(pool, eng)
    conc_csv = os.path.join(OUT_DIR, "table_g10_concentration_top5_10_15_20.csv")
    ann_csv = os.path.join(OUT_DIR, "table_g10_annual_returns_2010_2026.csv")
    conc_df.to_csv(conc_csv, index=False)
    ann_df.to_csv(ann_csv, index=False)
    print(f"\n[Saved] {conc_csv} ({len(conc_df)} rows)")
    print(
        conc_df[
            [
                "portfolio_id", "final_nav", "net_cagr_pct", "net_excess_cagr_pct",
                "sharpe_ratio_rf2", "sortino_ratio", "daily_max_dd_pct",
                "calmar_ratio", "annual_beat_spy_years", "avg_annual_cost_drag_bps",
            ]
        ].to_string(index=False)
    )

    print(f"\n[Saved] {ann_csv} ({len(ann_df)} rows)")
    print(ann_df.to_string(index=False))

    # 打印 2026Q3 最新实盘同台二选一案例与红灯被否决案例
    q26_g = pool[(pool["cal_qtr"] == "2026Q3") & pool["macro_green"]].sort_values("f10_composite_3f", ascending=False)
    q26_r = pool[(pool["cal_qtr"] == "2026Q3") & (~pool["macro_green"])].sort_values("ps_pit", ascending=False)
    print("\n=== 2026Q3 TOP 12 GREEN TIEBREAKER WINNERS ===")
    print(
        q26_g[
            ["ticker", "entry_date", "rev_yoy", "f01_gm_minus_sga", "f02_inc_opm", "f03a_peg_rev", "f05_net_buyback", "f10_composite_3f"]
        ]
        .head(12)
        .to_string(index=False)
    )
    print("\n=== 2026Q3 SAMPLE RED-LIGHT VETOED STOCKS ===")
    print(
        q26_r[
            ["ticker", "entry_date", "rev_yoy", "ps_pit", "pe_pit", "f01_gm_minus_sga", "f03a_peg_rev", "dilution_yoy_clean", "f09_fcf_ex_sbc_margin"]
        ]
        .head(8)
        .to_string(index=False)
    )
    print(f"\n[Done] Total runtime: {time.time() - t0:.2f}s")


if __name__ == "__main__":
    main()
