#!/usr/bin/env python3
"""
run_g06_accounting_forensics.py
US 30-Year Stock Selection Joint Backtest — Subagent G06:
Deep Accounting Forensics & Capital Allocation Actuarial Engine (2009-2026 Strict PIT XBRL)

Four Core Buy-Side Accounting Pillars:
1. Clean Shareholder FCF Margin = (OCF_TTM - Capex_TTM - SBC_TTM) / Rev_TTM
   & Headline FCF Illusion (Gross FCF > 0% but Clean FCF < 0%, e.g., NET) x Interest Rate Cycles & Valuation.
2. Incremental Operating Margin = (OpInc_TTM - OpInc_TTM_1Y_Ago) / (Rev_TTM - Rev_TTM_1Y_Ago)
   & Rule of 40/50/65 (Rev_YoY + Clean_FCF_Margin vs Fake Gross Rule of 40).
3. Tangible ROIC (stripping Goodwill & Intangibles, rescuing M&A compounders APH/DHR/TMO and
   negative-equity cannibals ORLY/AZO) vs Traditional GAAP ROIC / GAAP ROE.
4. Working Capital Forensics (AR_YoY - Rev_YoY >= +15pct channel-stuffing warning, decomposing
   late-quarter hockey-stick surges vs true decelerating channel stuffing;
   Inv_YoY - Rev_YoY >= +20pct inventory-glut warning; DeferredRev/ContractLiability leading indicator)
   & True Cash Cannibal Buybacks vs Levered Stagnant Debt-Funded Buyback Traps.

Zero-Lookahead & Anti-Bias Guarantees:
- Every XBRL item extracted from companyfacts.zip strictly enforces:
    form in {'10-Q','10-K','10-Q/A','10-K/A'}, 0 < (filed - end).days <= 130, AND record_filed <= row.filed <= entry_date.
- Cash flow YTD items (SBC, CapEx, D&A, Intangibles Amortization, Share Repurchases) properly
  YTD-differenced using strictly prior/contemporaneous filings (filed <= row.filed).
- Fixes 67 XBRL 1000x/1000000x share-unit scaling bugs (mcap_pit/assets > 250 & mcap > $500B) with zero lookahead.
- Delisted daily prices + conservative terminal delisting residuals (-95% bankruptcy / deal return)
  spliced via w2_07 augmented price engine.
- Returns evaluated strictly via Calendar-Quarter Equal-Weight Net Excess vs SPY (qtr_ew_alpha),
  12-month-deduplicated Calendar-Quarter EW Alpha (dedup_qtr_ew_alpha, preventing 1 stock like PLTR
  being counted 6 quarters in a row), outlier-capped EW Alpha, Median Alpha, Win Rate, Payoff, Bag2x, and Blowup rates.
"""

import os
import sys
import json
import time
import zipfile
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

PROJ = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
TMP = "/tmp/us_earn_macro_bt_20261109"
OUT_DIR = f"{PROJ}/results/granularity_v2/g06_accounting_forensics"
os.makedirs(OUT_DIR, exist_ok=True)

if f"{PROJ}/scripts" not in sys.path:
    sys.path.insert(0, f"{PROJ}/scripts")

from backtest_stats_lib import eval_slice, deduplicate_cooldown, benjamini_hochberg_fdr
from w2_07_30y_and_survivorship import build_augmented_price_engine, attach_events_fast

VALID_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}

GOODWILL_TAGS = ["Goodwill"]
INTANG_EXCL_GW_TAGS = ["IntangibleAssetsNetExcludingGoodwill", "OtherIntangibleAssetsNet"]
INTANG_FINITE_TAGS = ["FiniteLivedIntangibleAssetsNet"]
INTANG_INDEF_TAGS = ["IndefiniteLivedIntangibleAssetsExcludingGoodwill"]

AR_TAGS = [
    "AccountsReceivableNetCurrent",
    "ReceivablesNetCurrent",
    "AccountsReceivableNet",
    "AccountsNotesAndLoansReceivableNetCurrent",
    "BilledContractReceivables",
]
INV_TAGS = [
    "InventoryNet",
    "InventoryFinishedGoodsNetOfReserves",
    "InventoryFinishedGoods",
]
DEFREV_CURR_TAGS = [
    "ContractWithCustomerLiabilityCurrent",
    "DeferredRevenueCurrent",
    "CustomerAdvancesCurrent",
    "CustomerAdvancesAndDeposits",
]
DEFREV_TOT_TAGS = [
    "ContractWithCustomerLiability",
    "DeferredRevenue",
]

SBC_CF_TAGS = [
    "ShareBasedCompensation",
    "AllocatedShareBasedCompensationExpense",
    "AdjustmentsToAdditionalPaidInCapitalSharebasedCompensationRequisiteServicePeriodRecognitionValue",
    "EmployeeBenefitsAndShareBasedCompensation",
]
CAPEX_CF_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
    "PaymentsToAcquireOtherPropertyPlantAndEquipment",
    "PaymentsForCapitalImprovements",
]
INV_CF_EXIST_TAGS = [
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
]
DA_CF_TAGS = [
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "Depreciation",
]
AMORT_INTANG_TAGS = [
    "AmortizationOfIntangibleAssets",
    "FiniteLivedIntangibleAssetsAmortizationExpense",
]
BUYBACK_CF_TAGS = [
    "PaymentsForRepurchaseOfCommonStock",
    "PaymentsForRepurchaseOfEquity",
]


def parse_ymd_days(s):
    try:
        return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10])).toordinal()
    except Exception:
        return None


def get_dur_type(dur):
    if 68 <= dur <= 112:
        return 1
    if 165 <= dur <= 200:
        return 2
    if 255 <= dur <= 295:
        return 3
    if 345 <= dur <= 385:
        return 4
    return None


def collect_instant_candidates(usg, tag_list):
    by_end = {}
    for prio, tag in enumerate(tag_list):
        node = usg.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get("USD", [])
        for it in arr:
            fm = it.get("form", "")
            if fm not in VALID_FORMS:
                continue
            e_s, f_s, val = it.get("end"), it.get("filed"), it.get("val")
            if not (e_s and f_s and val is not None):
                continue
            eo, fo = parse_ymd_days(e_s), parse_ymd_days(f_s)
            if eo is None or fo is None:
                continue
            if not (0 < (fo - eo) <= 130):
                continue
            is_am = 1 if "/A" in fm else 0
            by_end.setdefault(e_s, []).append((fo, is_am, prio, float(val), f_s))
    for e_s in by_end:
        by_end[e_s].sort(key=lambda x: (x[0], x[1], x[2]))
    return by_end


def get_pit_instant(by_end, e_s, max_fo):
    arr = by_end.get(e_s)
    if not arr:
        return np.nan
    for fo, _, _, val, _ in arr:
        if fo <= max_fo:
            return val
    return np.nan


def collect_flow_candidates(usg, tag_list):
    by_ed = {}
    for prio, tag in enumerate(tag_list):
        node = usg.get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get("USD", [])
        for it in arr:
            fm = it.get("form", "")
            if fm not in VALID_FORMS:
                continue
            s_s, e_s, f_s, val = it.get("start"), it.get("end"), it.get("filed"), it.get("val")
            if not (s_s and e_s and f_s and val is not None):
                continue
            so, eo, fo = parse_ymd_days(s_s), parse_ymd_days(f_s), parse_ymd_days(f_s)
            if so is None or eo is None or fo is None:
                continue
            if not (0 < (fo - eo) <= 130):
                continue
            dt = get_dur_type(eo - so)
            if dt is None:
                continue
            is_am = 1 if "/A" in fm else 0
            by_ed.setdefault((e_s, dt), []).append((fo, is_am, prio, float(val), eo))
    for k in by_ed:
        by_ed[k].sort(key=lambda x: (x[0], x[1], x[2]))
    return by_ed


def compute_pit_ttm_flow(by_ed, q_ends_ords, target_idx, max_fo):
    """Strict PIT TTM flow: only uses records filed on or before max_fo."""
    e_curr, eo_curr = q_ends_ords[target_idx]

    def get_ed(e_s, dt):
        arr = by_ed.get((e_s, dt))
        if not arr:
            return np.nan
        for fo, _, _, val, _ in arr:
            if fo <= max_fo:
                return val
        return np.nan

    v_fy = get_ed(e_curr, 4)
    if not np.isnan(v_fy):
        return v_fy

    def get_1q_at(idx):
        es, eo = q_ends_ords[idx]
        v1 = get_ed(es, 1)
        if not np.isnan(v1):
            return v1
        v2 = get_ed(es, 2)
        if not np.isnan(v2) and idx >= 1:
            es1, eo1 = q_ends_ords[idx - 1]
            if 70 <= (eo - eo1) <= 115:
                vq1 = get_ed(es1, 1)
                if not np.isnan(vq1):
                    return v2 - vq1
        v3 = get_ed(es, 3)
        if not np.isnan(v3) and idx >= 1:
            es2, eo2 = q_ends_ords[idx - 1]
            if 70 <= (eo - eo2) <= 115:
                v_6m = get_ed(es2, 2)
                if not np.isnan(v_6m):
                    return v3 - v_6m
                if idx >= 2:
                    es1, eo1 = q_ends_ords[idx - 2]
                    if 70 <= (eo2 - eo1) <= 115:
                        vq1, vq2 = get_ed(es1, 1), get_ed(es2, 1)
                        if not np.isnan(vq1) and not np.isnan(vq2):
                            return v3 - vq1 - vq2
        v4 = get_ed(es, 4)
        if not np.isnan(v4) and idx >= 1:
            es3, eo3 = q_ends_ords[idx - 1]
            if 70 <= (eo - eo3) <= 115:
                v_9m = get_ed(es3, 3)
                if not np.isnan(v_9m):
                    return v4 - v_9m
                if idx >= 3:
                    es2, eo2 = q_ends_ords[idx - 2]
                    es1, eo1 = q_ends_ords[idx - 3]
                    if 70 <= (eo3 - eo2) <= 115 and 70 <= (eo2 - eo1) <= 115:
                        vq1, vq2, vq3 = get_ed(es1, 1), get_ed(es2, 1), get_ed(es3, 1)
                        if not (np.isnan(vq1) or np.isnan(vq2) or np.isnan(vq3)):
                            return v4 - vq1 - vq2 - vq3
        return np.nan

    if target_idx >= 3:
        idxs = [target_idx - 3, target_idx - 2, target_idx - 1, target_idx]
        eos = [q_ends_ords[k][1] for k in idxs]
        if (250 <= (eos[3] - eos[0]) <= 305 and
            70 <= (eos[1] - eos[0]) <= 115 and
            70 <= (eos[2] - eos[1]) <= 115 and
            70 <= (eos[3] - eos[2]) <= 115):
            vals = [get_1q_at(k) for k in idxs]
            if not any(np.isnan(v) for v in vals):
                return float(sum(vals))

    for dt_ytd, back_fy_q in ((3, 3), (2, 2), (1, 1)):
        v_ytd_curr = get_ed(e_curr, dt_ytd)
        if not np.isnan(v_ytd_curr) and target_idx >= 4:
            fy_idx = target_idx - back_fy_q
            es_fy, eo_fy = q_ends_ords[fy_idx]
            if (dt_ytd * 70) <= (eo_curr - eo_fy) <= (dt_ytd * 110):
                v_fy_prev = get_ed(es_fy, 4)
                if not np.isnan(v_fy_prev):
                    for p_idx in range(target_idx - 3, max(-1, target_idx - 6), -1):
                        es_p, eo_p = q_ends_ords[p_idx]
                        if 340 <= (eo_curr - eo_p) <= 390:
                            v_ytd_prev = get_ed(es_p, dt_ytd)
                            if not np.isnan(v_ytd_prev):
                                return float(v_ytd_curr + v_fy_prev - v_ytd_prev)
                            break
    return np.nan


def build_or_load_enriched_panel(force_rebuild=False):
    cache_pq = f"{TMP}/g06_enriched_pit_v3.parquet"
    if os.path.exists(cache_pq) and not force_rebuild:
        print(f"[G06] Loading cached enriched PIT panel: {cache_pq}")
        return pd.read_parquet(cache_pq)

    raw_cache_v2 = f"{TMP}/g06_enriched_pit_v2.parquet"
    if os.path.exists(raw_cache_v2) and not force_rebuild:
        df = pd.read_parquet(raw_cache_v2)
    else:
        t0 = time.time()
        print("[G06 1/4] Loading master PIT XBRL panel...")
        df = pd.read_parquet(f"{PROJ}/data/xbrl_master_pit_2009_2026.parquet")

        print("[G06 2/4] Splicing delisted prices & terminal delisting residuals (-95% bankruptcy / deal)...")
        eng = build_augmented_price_engine()
        horizons_all = (21, 63, 126, 252, 504, 756, 1260)
        df_aug = attach_events_fast(eng, df[["ticker", "filed"]], ticker_col="ticker", date_col="filed", horizons=horizons_all)

        missing_ent = df["entry_date"].isna() & df_aug["entry_date"].notna()
        for col in ["pre_date", "entry_date", "pre_adj_close", "entry_adj_close", "pre_ret_126d", "pre_ret_252d",
                    "dist_52w_high", "slow_uptrend_tag", "has_anomaly_break", "earn_jump_ret", "fwd_max_dd_252d"]:
            if col in df_aug.columns:
                df.loc[missing_ent, col] = df_aug.loc[missing_ent, col]

        tk2c = eng["tk_to_col"]
        cols_idx = np.array([tk2c.get(str(t), -1) for t in df["ticker"].values], dtype=np.int32)
        last_v = eng["last_valid_idx"]
        term_r = eng["terminal_rets"]
        exit_t = eng["exit_types"]
        n_days = eng["n_days"]

        df["exit_type_pit_audit"] = [exit_t[c] if c >= 0 else "UNKNOWN" for c in cols_idx]
        df["terminal_ret_audit"] = [float(term_r[c]) if c >= 0 else 0.0 for c in cols_idx]

        ent_dt_arr = pd.to_datetime(df["entry_date"]).dt.normalize().values.astype("datetime64[D]")
        idx_ent = np.clip(np.searchsorted(eng["dates"], ent_dt_arr), 0, n_days - 1)
        valid_c = (cols_idx >= 0) & df["entry_date"].notna().values
        lv_arr = np.where(valid_c, last_v[np.maximum(cols_idx, 0)], n_days)

        for h in horizons_all:
            delist_in_h = valid_c & (lv_arr < (idx_ent + h)) & (lv_arr < n_days - 15) & (lv_arr >= idx_ent)
            for prefix in ("fwd_", "spy_fwd_", "alpha_fwd_"):
                col = f"{prefix}{h}d"
                upd_mask = (df[col].isna() & df_aug[col].notna()) | (delist_in_h & df_aug[col].notna())
                df.loc[upd_mask, col] = df_aug.loc[upd_mask, col]
            if h == 252:
                df["delisted_within_1y"] = delist_in_h
            if h == 756:
                df["delisted_within_3y"] = delist_in_h

        macro = pd.read_parquet(f"{PROJ}/data/macro_pit_daily_1990_2026.parquet")
        macro_scale_map = dict(zip(pd.to_datetime(macro["date"]).dt.normalize(), macro["mcap_scale_to_2026"]))
        macro_era_map = dict(zip(pd.to_datetime(macro["date"]).dt.normalize(), macro["era_regime"]))
        macro_rate_map = dict(zip(pd.to_datetime(macro["date"]).dt.normalize(), macro["rate_level_bin"]))
        macro_dgs10_map = dict(zip(pd.to_datetime(macro["date"]).dt.normalize(), macro["dgs10"]))

        for i in np.where(missing_ent)[0]:
            tk = str(df.at[i, "ticker"])
            c = tk2c.get(tk, -1)
            ent_dt = pd.Timestamp(df.at[i, "entry_date"]).normalize()
            pre_dt = pd.Timestamp(df.at[i, "pre_date"]).normalize() if pd.notna(df.at[i, "pre_date"]) else ent_dt
            d_i = eng["date_to_idx"].get(ent_dt, -1)
            sh = df.at[i, "shares_clean"]
            if c >= 0 and d_i >= 0 and pd.notna(sh) and sh > 0:
                px_cls = float(eng["P_cls"][d_i, c])
                if np.isnan(px_cls) or px_cls <= 0:
                    px_cls = float(eng["P_adj"][d_i, c])
                if px_cls > 0:
                    mc = px_cls * sh
                    df.at[i, "mcap_pit"] = mc
                    df.at[i, "mcap_usd_b"] = mc / 1e9
                    sc = macro_scale_map.get(pre_dt) or macro_scale_map.get(ent_dt) or 1.5
                    df.at[i, "mcap_scale_to_2026"] = sc
                    df.at[i, "mcap_2026_equiv_b"] = (mc / 1e9) * sc
                    if pd.isna(df.at[i, "rate_level_bin"]):
                        df.at[i, "rate_level_bin"] = macro_rate_map.get(pre_dt)
                    if pd.isna(df.at[i, "era_regime"]):
                        df.at[i, "era_regime"] = macro_era_map.get(pre_dt)
                    if pd.isna(df.at[i, "dgs10"]):
                        df.at[i, "dgs10"] = macro_dgs10_map.get(pre_dt)

        print("[G06 3/4] Extracting strict PIT Balance Sheet & YTD Cash Flow tags from companyfacts.zip...")
        n_rows = len(df)
        gw_arr = np.full(n_rows, np.nan)
        intang_arr = np.full(n_rows, np.nan)
        has_gw_intang_tag = np.zeros(n_rows, dtype=bool)
        ar_arr = np.full(n_rows, np.nan)
        inv_arr = np.full(n_rows, np.nan)
        defrev_curr_arr = np.full(n_rows, np.nan)
        sbc_ttm_new = np.full(n_rows, np.nan)
        capex_ttm_new = np.full(n_rows, np.nan)
        inv_cf_exists = np.zeros(n_rows, dtype=bool)
        da_ttm_arr = np.full(n_rows, np.nan)
        amort_ttm_arr = np.full(n_rows, np.nan)
        buyback_ttm_arr = np.full(n_rows, np.nan)

        zf_path = f"{TMP}/companyfacts.zip"
        grouped = df.groupby("cik").indices

        with zipfile.ZipFile(zf_path, "r") as zf:
            names_set = set(zf.namelist())
            for cik_val, row_idxs in grouped.items():
                fn = f"CIK{int(cik_val):010d}.json"
                if fn not in names_set:
                    continue
                raw = json.loads(zf.read(fn))
                usg = raw.get("facts", {}).get("us-gaap", {})
                if not usg:
                    continue

                sub_ends = df.loc[row_idxs, "end"].values
                order = np.argsort(sub_ends)
                row_idxs_sorted = row_idxs[order]
                q_ends_ords = [(df.at[idx, "end"], parse_ymd_days(df.at[idx, "end"])) for idx in row_idxs_sorted]
                q_filed_ords = [parse_ymd_days(df.at[idx, "filed"]) for idx in row_idxs_sorted]

                gw_c = collect_instant_candidates(usg, GOODWILL_TAGS)
                int_ex_c = collect_instant_candidates(usg, INTANG_EXCL_GW_TAGS)
                int_fin_c = collect_instant_candidates(usg, INTANG_FINITE_TAGS)
                int_ind_c = collect_instant_candidates(usg, INTANG_INDEF_TAGS)
                ar_c = collect_instant_candidates(usg, AR_TAGS)
                inv_c = collect_instant_candidates(usg, INV_TAGS)
                dr_curr_c = collect_instant_candidates(usg, DEFREV_CURR_TAGS)
                dr_tot_c = collect_instant_candidates(usg, DEFREV_TOT_TAGS)

                sbc_f = collect_flow_candidates(usg, SBC_CF_TAGS)
                capex_f = collect_flow_candidates(usg, CAPEX_CF_TAGS)
                invcf_f = collect_flow_candidates(usg, INV_CF_EXIST_TAGS)
                da_f = collect_flow_candidates(usg, DA_CF_TAGS)
                amort_f = collect_flow_candidates(usg, AMORT_INTANG_TAGS)
                bb_f = collect_flow_candidates(usg, BUYBACK_CF_TAGS)

                first_eo = q_ends_ords[0][1]
                pre_qs = []
                cand_pre = sorted(
                    set((es, parse_ymd_days(es)) for (es, _) in list(sbc_f.keys()) + list(capex_f.keys())
                        if parse_ymd_days(es) and parse_ymd_days(es) < first_eo - 60),
                    key=lambda x: x[1]
                )
                cur_anchor = first_eo
                for es, eo in reversed(cand_pre):
                    if 70 <= (cur_anchor - eo) <= 115:
                        pre_qs.append((es, eo))
                        cur_anchor = eo
                        if len(pre_qs) >= 5:
                            break
                pre_qs.reverse()
                chain_qs = pre_qs + q_ends_ords
                offset = len(pre_qs)

                for local_i, r_idx in enumerate(row_idxs_sorted):
                    e_s, _ = q_ends_ords[local_i]
                    fo = q_filed_ords[local_i]
                    if fo is None:
                        continue
                    c_idx = offset + local_i

                    v_gw = get_pit_instant(gw_c, e_s, fo)
                    v_int = get_pit_instant(int_ex_c, e_s, fo)
                    if np.isnan(v_int):
                        vf = get_pit_instant(int_fin_c, e_s, fo)
                        vi = get_pit_instant(int_ind_c, e_s, fo)
                        if not np.isnan(vf) or not np.isnan(vi):
                            v_int = (0.0 if np.isnan(vf) else vf) + (0.0 if np.isnan(vi) else vi)
                    if not np.isnan(v_gw) or not np.isnan(v_int):
                        has_gw_intang_tag[r_idx] = True
                    gw_arr[r_idx] = v_gw
                    intang_arr[r_idx] = v_int

                    ar_arr[r_idx] = get_pit_instant(ar_c, e_s, fo)
                    inv_arr[r_idx] = get_pit_instant(inv_c, e_s, fo)
                    vc_dr = get_pit_instant(dr_curr_c, e_s, fo)
                    vt_dr = get_pit_instant(dr_tot_c, e_s, fo)
                    defrev_curr_arr[r_idx] = vc_dr if not np.isnan(vc_dr) else vt_dr

                    sbc_ttm_new[r_idx] = compute_pit_ttm_flow(sbc_f, chain_qs, c_idx, fo)
                    capex_ttm_new[r_idx] = compute_pit_ttm_flow(capex_f, chain_qs, c_idx, fo)
                    invcf_val = compute_pit_ttm_flow(invcf_f, chain_qs, c_idx, fo)
                    inv_cf_exists[r_idx] = not np.isnan(invcf_val)
                    da_ttm_arr[r_idx] = compute_pit_ttm_flow(da_f, chain_qs, c_idx, fo)
                    amort_ttm_arr[r_idx] = compute_pit_ttm_flow(amort_f, chain_qs, c_idx, fo)
                    buyback_ttm_arr[r_idx] = compute_pit_ttm_flow(bb_f, chain_qs, c_idx, fo)

        df["goodwill_pit"] = gw_arr
        df["intangibles_pit"] = intang_arr
        df["has_gw_intang_tag"] = has_gw_intang_tag
        df["ar_pit"] = ar_arr
        df["inv_pit"] = inv_arr
        df["defrev_pit"] = defrev_curr_arr
        df["sbc_ttm_pit"] = np.where(df["sbc_ttm"].notna(), df["sbc_ttm"], sbc_ttm_new)
        df["capex_ttm_pit"] = np.where(df["capex_ttm"].notna(), df["capex_ttm"], capex_ttm_new)

        immaterial_ppe = (
            df["ocf_ttm"].notna()
            & df["capex_ttm_pit"].isna()
            & inv_cf_exists
            & df["sector_type"].isin(["Software_Internet", "Tech_Hardware_Semi", "Healthcare_LifeSci", "Industrial_Consumer_Compounder"])
        )
        df.loc[immaterial_ppe, "capex_ttm_pit"] = 0.0
        df["fcf_ttm_pit"] = np.where(
            df["ocf_ttm"].notna() & df["capex_ttm_pit"].notna(),
            df["ocf_ttm"] - df["capex_ttm_pit"],
            np.where(df["fcf_ttm"].notna(), df["fcf_ttm"], np.nan)
        )
        df["da_ttm_pit"] = da_ttm_arr
        df["amort_intang_ttm_pit"] = amort_ttm_arr
        df["buyback_ttm_pit"] = buyback_ttm_arr

    print("[G06 4/4] Calibrating 1000x share-unit bugs & computing strict PIT multi-year forensic lags...")
    df = df.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)

    # Zero-lookahead fix for 1000x / 1000000x XBRL share-unit tagging bugs (where mcap_pit / assets > 250 AND mcap_usd_b > $500B)
    mc_clean = df["mcap_pit"].values.copy()
    assets_arr = df["assets"].values
    for i in range(len(df)):
        mc = mc_clean[i]
        a = assets_arr[i]
        if pd.notna(mc) and mc > 5e11 and pd.notna(a) and a > 0:
            ratio_ma = mc / a
            if ratio_ma > 50000.0:
                mc_clean[i] = mc / 1e6
            elif ratio_ma > 250.0:
                mc_clean[i] = mc / 1e3
    df["mcap_pit_clean"] = mc_clean
    df["mcap_usd_b_clean"] = mc_clean / 1e9
    df["mcap_2026_equiv_b_clean"] = df["mcap_usd_b_clean"] * df["mcap_scale_to_2026"]
    df["ev_pit_clean"] = mc_clean + df["total_debt"].fillna(0.0) - df["cash"].fillna(0.0)
    df["ev_sales_pit_clean"] = np.where(df["rev_ttm"] > 0, df["ev_pit_clean"] / df["rev_ttm"], np.nan)

    n = len(df)
    da_fill = np.where(df["da_ttm_pit"].notna(), df["da_ttm_pit"], df["amort_intang_ttm_pit"].fillna(0.0))
    df["ebitda_ttm_pit"] = np.where(df["opinc_ttm"].notna(), df["opinc_ttm"] + da_fill, np.nan)
    df["net_debt_pit"] = df["total_debt"].fillna(0.0) - df["cash"].fillna(0.0)
    df.loc[df["total_debt"].isna() & df["cash"].isna(), "net_debt_pit"] = np.nan
    df["nd_to_ebitda_pit"] = np.where(
        df["net_debt_pit"].notna() & df["ebitda_ttm_pit"].notna() & (df["ebitda_ttm_pit"] > 0),
        df["net_debt_pit"] / df["ebitda_ttm_pit"],
        np.nan
    )

    rev_ttm_1y = np.full(n, np.nan)
    rev_ttm_2y = np.full(n, np.nan)
    opinc_ttm_1y = np.full(n, np.nan)
    assets_1y = np.full(n, np.nan)
    gw_1y = np.full(n, np.nan)
    ar_1y = np.full(n, np.nan)
    inv_1y = np.full(n, np.nan)
    defrev_1y = np.full(n, np.nan)
    net_debt_1y = np.full(n, np.nan)
    nd_ebitda_1y = np.full(n, np.nan)

    ends_dt = pd.to_datetime(df["end"]).values
    flds_dt = pd.to_datetime(df["filed"]).values
    rev_ttm_v = df["rev_ttm"].values
    opinc_ttm_v = df["opinc_ttm"].values
    assets_v = df["assets"].values
    gw_v = df["goodwill_pit"].fillna(0.0).values
    ar_v = df["ar_pit"].values
    inv_v = df["inv_pit"].values
    dr_v = df["defrev_pit"].values
    nd_v = df["net_debt_pit"].values
    nde_v = df["nd_to_ebitda_pit"].values

    for _, grp_idxs in df.groupby("ticker").indices.items():
        m = len(grp_idxs)
        for j in range(m):
            curr_i = grp_idxs[j]
            # 1Y lag (335..395d)
            for k in range(j - 1, max(-1, j - 7), -1):
                prev_i = grp_idxs[k]
                dd = (ends_dt[curr_i] - ends_dt[prev_i]) / np.timedelta64(1, "D")
                if 335 <= dd <= 395 and flds_dt[prev_i] < flds_dt[curr_i]:
                    rev_ttm_1y[curr_i] = rev_ttm_v[prev_i]
                    opinc_ttm_1y[curr_i] = opinc_ttm_v[prev_i]
                    assets_1y[curr_i] = assets_v[prev_i]
                    gw_1y[curr_i] = gw_v[prev_i]
                    ar_1y[curr_i] = ar_v[prev_i]
                    inv_1y[curr_i] = inv_v[prev_i]
                    defrev_1y[curr_i] = dr_v[prev_i]
                    net_debt_1y[curr_i] = nd_v[prev_i]
                    nd_ebitda_1y[curr_i] = nde_v[prev_i]
                    break
            # 2Y lag (690..770d) for chronic secular stagnation check
            for k2 in range(j - 5, max(-1, j - 12), -1):
                prev2_i = grp_idxs[k2]
                dd2 = (ends_dt[curr_i] - ends_dt[prev2_i]) / np.timedelta64(1, "D")
                if 690 <= dd2 <= 770 and flds_dt[prev2_i] < flds_dt[curr_i]:
                    rev_ttm_2y[curr_i] = rev_ttm_v[prev2_i]
                    break

    df["rev_ttm_1y_ago"] = rev_ttm_1y
    df["opinc_ttm_1y_ago"] = opinc_ttm_1y
    df["rev_ttm_yoy"] = np.where((rev_ttm_1y > 0) & df["rev_ttm"].notna(), df["rev_ttm"] / rev_ttm_1y - 1.0, np.nan)
    df["rev_2y_cagr"] = np.where((rev_ttm_2y > 0) & (df["rev_ttm"] > 0), np.sqrt(df["rev_ttm"] / rev_ttm_2y) - 1.0, df["rev_ttm_yoy"])

    # M&A balance sheet spike flag (to separate M&A balance-sheet consolidation from organic channel stuffing!)
    assets_yoy = np.where((assets_1y > 0) & (df["assets"] > 0), df["assets"] / assets_1y - 1.0, 0.0)
    gw_jump_to_assets = np.where(df["assets"] > 0, (df["goodwill_pit"].fillna(0.0) - gw_1y) / df["assets"], 0.0)
    df["is_ma_consolidation_spike"] = (assets_yoy >= 0.25) & (gw_jump_to_assets >= 0.05)

    # 1. Clean FCF Margin & SBC Ratio
    valid_rev_ttm = df["rev_ttm"].notna() & (df["rev_ttm"] > 0)
    df["gross_fcf_margin"] = np.where(valid_rev_ttm & df["fcf_ttm_pit"].notna(), df["fcf_ttm_pit"] / df["rev_ttm"], np.nan)
    df["sbc_to_rev"] = np.where(valid_rev_ttm & df["sbc_ttm_pit"].notna(), df["sbc_ttm_pit"] / df["rev_ttm"], np.nan)
    df["clean_fcf_ttm"] = np.where(df["fcf_ttm_pit"].notna() & df["sbc_ttm_pit"].notna(), df["fcf_ttm_pit"] - df["sbc_ttm_pit"], np.nan)
    df["clean_fcf_margin"] = np.where(valid_rev_ttm & df["clean_fcf_ttm"].notna(), df["clean_fcf_ttm"] / df["rev_ttm"], np.nan)

    # 2. Incremental Operating Margin & Rule of 40/50
    d_rev = df["rev_ttm"] - df["rev_ttm_1y_ago"]
    d_op = df["opinc_ttm"] - df["opinc_ttm_1y_ago"]
    df["incremental_opm_expanding"] = np.where(
        (df["rev_ttm_yoy"] >= 0.02) & d_op.notna() & (d_rev > 0),
        d_op / d_rev,
        np.nan
    )
    df["rule_of_clean_fcf"] = np.where(
        df["rev_ttm_yoy"].notna() & df["clean_fcf_margin"].notna() & (df["rev_ttm_yoy"] <= 3.0) & (df["rev_ttm_yoy"] >= -0.80),
        df["rev_ttm_yoy"] + df["clean_fcf_margin"],
        np.nan
    )
    df["rule_of_gross_fcf"] = np.where(
        df["rev_ttm_yoy"].notna() & df["gross_fcf_margin"].notna() & (df["rev_ttm_yoy"] <= 3.0) & (df["rev_ttm_yoy"] >= -0.80),
        df["rev_ttm_yoy"] + df["gross_fcf_margin"],
        np.nan
    )

    # 3. Tangible ROIC vs GAAP ROIC / ROE
    gw_clean = np.where(df["assets"].notna(), np.maximum(df["goodwill_pit"].fillna(0.0), 0.0), np.nan)
    int_clean = np.where(df["assets"].notna(), np.maximum(df["intangibles_pit"].fillna(0.0), 0.0), np.nan)
    df["gw_plus_intang_to_assets"] = np.where(df["assets"] > 0, (gw_clean + int_clean) / df["assets"], np.nan)

    raw_ic = df["equity"] + df["total_debt"].fillna(0.0) - df["cash"].fillna(0.0)
    raw_tang_ic = raw_ic - gw_clean - int_clean
    tang_assets = np.maximum(df["assets"] - gw_clean - int_clean, 1e5)
    floor_tang_ic = np.maximum(0.05 * tang_assets, np.where(df["rev_ttm"] > 0, 0.05 * df["rev_ttm"], 1e5))
    df["tangible_ic_pit"] = np.where(df["assets"].notna() & df["equity"].notna(), np.maximum(raw_tang_ic, floor_tang_ic), np.nan)

    nopat_ttm = df["opinc_ttm"] * 0.79
    ebita_nopat_ttm = (df["opinc_ttm"] + df["amort_intang_ttm_pit"].fillna(0.0)) * 0.79
    df["tangible_roic_nopat"] = np.where(df["tangible_ic_pit"] > 0, nopat_ttm / df["tangible_ic_pit"], np.nan)
    df["tangible_roic_ebita"] = np.where(df["tangible_ic_pit"] > 0, ebita_nopat_ttm / df["tangible_ic_pit"], np.nan)

    # 4. Working Capital Forensics
    valid_ar = (ar_1y > 0) & (df["ar_pit"] > 0) & valid_rev_ttm & ((df["ar_pit"] / df["rev_ttm"]) >= 0.03)
    df["ar_yoy"] = np.where(valid_ar, df["ar_pit"] / ar_1y - 1.0, np.nan)
    df["ar_minus_rev_yoy"] = np.where(
        df["ar_yoy"].notna() & df["rev_yoy"].notna() & (df["rev_yoy"] > -0.80) & (df["rev_yoy"] < 3.0) & (df["ar_yoy"] < 5.0),
        df["ar_yoy"] - df["rev_yoy"],
        np.nan
    )

    valid_inv = (inv_1y > 0) & (df["inv_pit"] > 0) & valid_rev_ttm & ((df["inv_pit"] / df["rev_ttm"]) >= 0.02)
    df["inv_yoy"] = np.where(valid_inv, df["inv_pit"] / inv_1y - 1.0, np.nan)
    df["inv_minus_rev_yoy"] = np.where(
        df["inv_yoy"].notna() & df["rev_yoy"].notna() & (df["rev_yoy"] > -0.80) & (df["rev_yoy"] < 3.0) & (df["inv_yoy"] < 5.0),
        df["inv_yoy"] - df["rev_yoy"],
        np.nan
    )

    valid_dr = (defrev_1y > 0) & (df["defrev_pit"] > 0) & valid_rev_ttm & ((df["defrev_pit"] / df["rev_ttm"]) >= 0.02)
    df["defrev_yoy"] = np.where(valid_dr, df["defrev_pit"] / defrev_1y - 1.0, np.nan)
    df["defrev_minus_rev_yoy"] = np.where(
        df["defrev_yoy"].notna() & df["rev_yoy"].notna() & (df["rev_yoy"] > -0.80) & (df["rev_yoy"] < 3.0) & (df["defrev_yoy"] < 5.0),
        df["defrev_yoy"] - df["rev_yoy"],
        np.nan
    )

    df["net_debt_chg_1y"] = df["net_debt_pit"] - net_debt_1y
    df["nd_ebitda_chg_1y"] = df["nd_to_ebitda_pit"] - nd_ebitda_1y

    df.to_parquet(cache_pq, index=False)
    print(f"[G06] Saved clean enriched PIT panel v3 ({len(df):,} rows).")
    return df


def evaluate_bucket_row(df_slice: pd.DataFrame, meta: dict) -> dict:
    """
    Computes D15-compliant Calendar-Quarter EW Net Excess vs SPY + 12M Cooldown Deduplicated stats
    + Winsorized/Capped Calendar-Quarter EW Alpha (preventing single 20x outlier from hiding <40% win rates!).
    """
    r = eval_slice(df_slice, horizons=(63, 252, 504, 756, 1260), dedup_days=250, date_col="entry_date", label=meta.get("bucket", ""))
    out = dict(meta)
    out["n_raw"] = r.get("n_raw", 0)
    out["n_dedup_12m"] = r.get("n_dedup", 0)
    out["n_tickers"] = r.get("n_tickers", 0)
    out["earn_jump_mean"] = r.get("jump_mean", np.nan)
    out["earn_drop_le5_prob"] = r.get("drop_le5_prob", np.nan)
    out["med_mdd_1y"] = r.get("med_mdd_1y", np.nan)
    out["mdd50_1y_prob"] = r.get("mdd50_1y_prob", np.nan)

    clean_s = df_slice[~df_slice["has_anomaly_break"].fillna(False)].copy() if (len(df_slice) > 0 and "has_anomaly_break" in df_slice.columns) else df_slice.copy()
    if len(clean_s) > 0:
        clean_s["cal_qtr"] = pd.to_datetime(clean_s["entry_date"]).dt.to_period("Q")
        ded = deduplicate_cooldown(clean_s, date_col="entry_date", cooldown_days=250)
    else:
        ded = clean_s

    if len(ded) >= 5 and "delisted_within_3y" in ded.columns:
        out["delist_3y_prob"] = float(ded["delisted_within_3y"].mean())
        bankrupt_3y = ded["delisted_within_3y"] & (ded["exit_type_pit_audit"] == "BANKRUPTCY_OR_LIQUIDATION")
        out["bankrupt_3y_prob"] = float(bankrupt_3y.mean())
    else:
        out["delist_3y_prob"] = np.nan
        out["bankrupt_3y_prob"] = np.nan

    caps = {63: 1.0, 252: 2.0, 504: 3.0, 756: 4.0, 1260: 6.0}
    for h, h_tag in ((63, "1q"), (252, "1y"), (504, "2y"), (756, "3y"), (1260, "5y")):
        out[f"n_{h_tag}"] = r.get(f"n_{h}d", 0)
        out[f"qtr_ew_alpha_{h_tag}"] = r.get(f"qtr_ew_alpha_{h}d", np.nan)
        # Also compute deduplicated + outlier-capped Calendar-Quarter EW Alpha so 1 stock (e.g. PLTR +2200% x 6 quarters) never distorts structural inference!
        a_col = f"alpha_fwd_{h}d"
        if len(ded) >= 5 and a_col in ded.columns:
            sub_d = ded.dropna(subset=[a_col])
            if len(sub_d) >= 5:
                capped_a = sub_d[a_col].clip(lower=-1.5, upper=caps[h])
                q_m = sub_d.assign(_ca=capped_a).groupby("cal_qtr")["_ca"].mean()
                out[f"dedup_qtr_ew_alpha_cap_{h_tag}"] = float(q_m.mean())
            else:
                out[f"dedup_qtr_ew_alpha_cap_{h_tag}"] = np.nan
        else:
            out[f"dedup_qtr_ew_alpha_cap_{h_tag}"] = np.nan

        out[f"med_alpha_{h_tag}"] = r.get(f"med_alpha_{h}d", np.nan)
        out[f"win_rate_{h_tag}"] = r.get(f"win_rate_{h}d", np.nan)
        out[f"payoff_{h_tag}"] = r.get(f"payoff_{h}d", np.nan)
        out[f"bag2x_prob_{h_tag}"] = r.get(f"bag2x_prob_{h}d", np.nan)
        out[f"halve_prob_{h_tag}"] = r.get(f"halve_prob_{h}d", np.nan)
        out[f"t_stat_{h_tag}"] = r.get(f"t_stat_{h}d", np.nan)
        out[f"p_val_{h_tag}"] = r.get(f"p_val_{h}d", np.nan)
    return out


def get_subperiod_masks(df: pd.DataFrame):
    dt = pd.to_datetime(df["entry_date"])
    return [
        ("Full_2009_2026", pd.Series(True, index=df.index)),
        ("Last_10Y_2016_2026", dt >= "2016-01-01"),
        ("HighRate_2022_2026", dt >= "2022-01-01"),
        ("LowRate_2010_2019", (dt >= "2010-01-01") & (dt <= "2019-12-31")),
        ("ZIRP_Bubble_2020_2021", (dt >= "2020-01-01") & (dt <= "2021-12-31")),
    ]


def get_universes(df_valid: pd.DataFrame):
    non_fin = df_valid["sector_type"] != "Financial_Utility_RateSens"
    return [
        ("Mcap2026_ge25B_NonFin", (df_valid["mcap_2026_equiv_b_clean"] >= 25.0) & non_fin),
        ("Mcap2026_ge10B_NonFin", (df_valid["mcap_2026_equiv_b_clean"] >= 10.0) & non_fin),
        ("Mcap2026_ge25B_AllSectors", df_valid["mcap_2026_equiv_b_clean"] >= 25.0),
    ]


def build_table_1_clean_fcf(df_valid: pd.DataFrame) -> pd.DataFrame:
    print("[G06 Table 1] Computing Clean FCF Margin, SBC Illusion & Interest Rate Cycle Matrix...")
    rows = []
    fcf_bins = [-np.inf, -0.05, 0.0, 0.10, 0.20, 0.35, np.inf]
    fcf_labels = [
        "1_lt_-5% (重度现金失血)",
        "2_-5%_to_0% (轻度失血)",
        "3_0%_to_10% (微利造血)",
        "4_10%_to_20% (稳健造血)",
        "5_20%_to_35% (高现金奶牛)",
        "6_ge_35% (顶级印钞机)",
    ]

    for univ_name, u_mask in get_universes(df_valid):
        du = df_valid[u_mask].copy()
        du["clean_fcf_bin"] = pd.cut(du["clean_fcf_margin"], bins=fcf_bins, labels=fcf_labels, right=False)
        du["gross_fcf_bin"] = pd.cut(du["gross_fcf_margin"], bins=fcf_bins, labels=fcf_labels, right=False)

        dt = pd.to_datetime(du["entry_date"])
        regime_cuts = [
            ("Period_Full_2009_2026", pd.Series(True, index=du.index)),
            ("Period_Last10Y_2016_2026", dt >= "2016-01-01"),
            ("Period_HighRate_2022_2026", dt >= "2022-01-01"),
            ("Period_LowRate_2010_2019", (dt >= "2010-01-01") & (dt <= "2019-12-31")),
            ("Period_ZIRP_2020_2021", (dt >= "2020-01-01") & (dt <= "2021-12-31")),
            ("RateBin_DGS10_lt_2.5%", du["dgs10"] < 2.5),
            ("RateBin_DGS10_2.5%_to_4.0%", (du["dgs10"] >= 2.5) & (du["dgs10"] < 4.0)),
            ("RateBin_DGS10_ge_4.0%", du["dgs10"] >= 4.0),
        ]

        for reg_name, r_mask in regime_cuts:
            if univ_name != "Mcap2026_ge25B_NonFin" and reg_name not in ("Period_Full_2009_2026", "Period_Last10Y_2016_2026", "Period_HighRate_2022_2026"):
                continue
            dr = du[r_mask]
            if len(dr) < 20:
                continue

            both_ok = dr.dropna(subset=["gross_fcf_margin", "clean_fcf_margin"])
            illusion_groups = [
                ("Illusion_All_GrossPos_CleanNeg (表面FCF>0但扣SBC实亏)", (both_ok["gross_fcf_margin"] > 0) & (both_ok["clean_fcf_margin"] < 0)),
                ("Illusion_Severe_GrossPos_Clean_le_-5% (表面FCF>0但扣SBC巨亏<=-5%, 如NET)", (both_ok["gross_fcf_margin"] > 0) & (both_ok["clean_fcf_margin"] <= -0.05)),
                ("Illusion_HighVal_EVSales_ge8x (高估值SBC幻觉杀猪盘: 表面FCF>0+扣SBC实亏+EV/Sales>=8x, 如NET/SNOW)",
                 (both_ok["gross_fcf_margin"] > 0) & (both_ok["clean_fcf_margin"] < 0) & (both_ok["ev_sales_pit_clean"] >= 8.0)),
                ("Illusion_SlowingRev_SBC_Trap (失速SBC幻觉陷阱: 表面FCF>0+扣SBC实亏+营收降速rev_accel<=0)",
                 (both_ok["gross_fcf_margin"] > 0) & (both_ok["clean_fcf_margin"] < 0) & (both_ok["rev_accel_1q"] <= 0)),
                ("DoubleNeg_GrossNeg_CleanNeg (表面与扣SBC双亏)", both_ok["gross_fcf_margin"] <= 0),
                ("TruePos_GrossPos_Clean_0%_to_15% (真FCF为正0-15%)", (both_ok["gross_fcf_margin"] > 0) & (both_ok["clean_fcf_margin"] >= 0) & (both_ok["clean_fcf_margin"] < 0.15)),
                ("TruePos_GrossPos_Clean_ge_15% (真FCF强造血>=15%)", (both_ok["gross_fcf_margin"] > 0) & (both_ok["clean_fcf_margin"] >= 0.15)),
            ]
            for b_label, m in illusion_groups:
                rows.append(evaluate_bucket_row(both_ok[m], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A_SBC_FCF_Illusion_Forensics",
                    "bucket": b_label,
                }))

            for lbl in fcf_labels:
                rows.append(evaluate_bucket_row(dr[dr["clean_fcf_bin"] == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "B_Clean_FCF_Margin_6Tiers",
                    "bucket": lbl,
                }))

            if reg_name in ("Period_Full_2009_2026", "Period_Last10Y_2016_2026", "Period_HighRate_2022_2026") and univ_name == "Mcap2026_ge25B_NonFin":
                for lbl in fcf_labels:
                    rows.append(evaluate_bucket_row(dr[dr["gross_fcf_bin"] == lbl], {
                        "universe": univ_name,
                        "regime": reg_name,
                        "panel_section": "C_Naive_Gross_FCF_Margin_Control",
                        "bucket": lbl,
                    }))

            if reg_name in ("Period_Full_2009_2026", "Period_Last10Y_2016_2026", "Period_HighRate_2022_2026"):
                sbc_bins = [-np.inf, 0.01, 0.03, 0.08, 0.15, np.inf]
                sbc_lbls = [
                    "SBC_lt_1% (极低激励克制)",
                    "SBC_1%_to_3% (常规蓝筹激励)",
                    "SBC_3%_to_8% (中度科技激励)",
                    "SBC_8%_to_15% (重度股权激励)",
                    "SBC_ge_15% (极端SBC抽血>=15%)",
                ]
                sbc_cut = pd.cut(dr["sbc_to_rev"], bins=sbc_bins, labels=sbc_lbls, right=False)
                for lbl in sbc_lbls:
                    rows.append(evaluate_bucket_row(dr[sbc_cut == lbl], {
                        "universe": univ_name,
                        "regime": reg_name,
                        "panel_section": "D_SBC_to_Revenue_Burden",
                        "bucket": lbl,
                    }))

    out_df = pd.DataFrame(rows)
    out_df["bh_fdr_q_1y"] = benjamini_hochberg_fdr(out_df["p_val_1y"].values)
    out_df["bh_fdr_q_3y"] = benjamini_hochberg_fdr(out_df["p_val_3y"].values)
    return out_df


def build_table_2_tangible_roic_and_inc_opm(df_valid: pd.DataFrame) -> pd.DataFrame:
    print("[G06 Table 2] Computing Tangible ROIC vs GAAP ROIC/ROE, Incremental OPM & Rule of 40/50...")
    rows = []

    roic_bins = [-np.inf, 0.0, 0.08, 0.15, 0.25, 0.45, np.inf]
    roic_lbls = [
        "1_lt_0% (亏损负回报)",
        "2_0%_to_8% (低于资本成本)",
        "3_8%_to_15% (平庸回报)",
        "4_15%_to_25% (良好回报)",
        "5_25%_to_45% (优秀复利)",
        "6_ge_45% (顶级轻资产皇冠)",
    ]

    inc_bins = [-np.inf, 0.0, 0.20, 0.40, 0.65, np.inf]
    inc_lbls = [
        "1_IncOPM_lt_0% (增收不增利/负经营杠杆)",
        "2_IncOPM_0%_to_20% (低经营杠杆弹性)",
        "3_IncOPM_20%_to_40% (稳健规模效应)",
        "4_IncOPM_40%_to_65% (强经营杠杆)",
        "5_IncOPM_ge_65% (印钞级边际弹性, 如TXN/APP)",
    ]

    r40_bins = [-np.inf, 0.0, 0.15, 0.30, 0.40, 0.50, 0.65, np.inf]
    r40_lbls = [
        "1_RuleClean_lt_0% (失血萎缩)",
        "2_RuleClean_0%_to_15% (低速平庸)",
        "3_RuleClean_15%_to_30% (中等及格线前)",
        "4_RuleClean_30%_to_40% (准Rule40梯队)",
        "5_RuleClean_40%_to_50% (达标Rule_of_40)",
        "6_RuleClean_50%_to_65% (精英Rule_of_50)",
        "7_RuleClean_ge_65% (殿堂级Rule_of_65+)",
    ]

    for univ_name, u_mask in get_universes(df_valid)[:2]:
        du = df_valid[u_mask].copy()
        for reg_name, r_mask in get_subperiod_masks(du)[:3]:
            dr = du[r_mask].copy()
            if len(dr) < 20:
                continue

            c_tang_ebita = pd.cut(dr["tangible_roic_ebita"], bins=roic_bins, labels=roic_lbls, right=False)
            for lbl in roic_lbls:
                rows.append(evaluate_bucket_row(dr[c_tang_ebita == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A1_Tangible_ROIC_EBITA_6Tiers",
                    "bucket": lbl,
                }))

            c_tang_nopat = pd.cut(dr["tangible_roic_nopat"], bins=roic_bins, labels=roic_lbls, right=False)
            for lbl in roic_lbls:
                rows.append(evaluate_bucket_row(dr[c_tang_nopat == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A2_Tangible_ROIC_NOPAT_6Tiers",
                    "bucket": lbl,
                }))

            c_gaap_roic = pd.cut(dr["roic_ttm"], bins=roic_bins, labels=roic_lbls, right=False)
            for lbl in roic_lbls:
                rows.append(evaluate_bucket_row(dr[c_gaap_roic == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A3_Traditional_GAAP_ROIC_6Tiers",
                    "bucket": lbl,
                }))

            c_roe = pd.cut(dr["roe_ttm"], bins=roic_bins, labels=roic_lbls, right=False)
            for lbl in roic_lbls:
                rows.append(evaluate_bucket_row(dr[c_roe == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A4_Traditional_GAAP_ROE_6Tiers",
                    "bucket": lbl,
                }))
            neg_eq_high_troic = dr["neg_equity"] & (dr["tangible_roic_ebita"] >= 0.25) & (dr["clean_fcf_margin"] > 0)
            rows.append(evaluate_bucket_row(dr[neg_eq_high_troic], {
                "universe": univ_name,
                "regime": reg_name,
                "panel_section": "A4_Traditional_GAAP_ROE_6Tiers",
                "bucket": "7_NegBookEquity_HighTangROIC_Cannibals (负净资产ROE失效但有形ROIC>=25%, 如ORLY/AZO)",
            }))

            # A5. M&A Goodwill Compounder Forensics (APH / DHR / TMO)
            gw_heavy = dr["gw_plus_intang_to_assets"] >= 0.30
            ma_groups = [
                ("MA1_GW_Heavy_GAAP_5to15%_Tang_ge30%_Growing (商誉压低GAAP_ROIC至5-15%但有形ROIC>=30%且增长>=5%, 如DHR/TMO/ROP)",
                 gw_heavy & (dr["roic_ttm"] >= 0.05) & (dr["roic_ttm"] < 0.15) & (dr["tangible_roic_ebita"] >= 0.30) & (dr["rev_ttm_yoy"] >= 0.05)),
                ("MA2_GW_Heavy_Tang_ge30%_Plus_Inflection (商誉重>=30%+有形ROIC>=30%+营收加速拐点, 如APH/DHR景气拐点)",
                 gw_heavy & (dr["tangible_roic_ebita"] >= 0.30) & (dr["rev_ttm_yoy"] >= 0.08) & (dr["rev_accel_1q"] > 0)),
                ("MA3_GW_Heavy_GAAP_5to15%_Tang_ge30%_Stagnant (商誉重+有形ROIC高但营收停滞<5%, 如老IBM)",
                 gw_heavy & (dr["roic_ttm"] >= 0.05) & (dr["roic_ttm"] < 0.15) & (dr["tangible_roic_ebita"] >= 0.30) & (dr["rev_ttm_yoy"] < 0.05)),
                ("MA4_GW_Heavy_Both_High_GAAP_ge15%_Tang_ge45% (顶级并购+内生双轮驱动, 如APH/TDG)",
                 gw_heavy & (dr["roic_ttm"] >= 0.15) & (dr["tangible_roic_ebita"] >= 0.45)),
                ("MA5_GW_Heavy_Low_Tang_lt15% (伪并购整合失败陷阱: 商誉>=30%且有形ROIC<15%)",
                 gw_heavy & (dr["tangible_roic_ebita"] < 0.15)),
            ]
            for b_lbl, m in ma_groups:
                rows.append(evaluate_bucket_row(dr[m], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A5_MA_Goodwill_Compounder_Matrix",
                    "bucket": b_lbl,
                }))

            # B1. Incremental OPM 5-Tier Ladder
            c_inc = pd.cut(dr["incremental_opm_expanding"], bins=inc_bins, labels=inc_lbls, right=False)
            for lbl in inc_lbls:
                rows.append(evaluate_bucket_row(dr[c_inc == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "B1_Incremental_OPM_5Tiers_RevExpanding",
                    "bucket": lbl,
                }))
            rev_contract = dr["rev_ttm_yoy"].notna() & (dr["rev_ttm_yoy"] < 0.02)
            rows.append(evaluate_bucket_row(dr[rev_contract], {
                "universe": univ_name,
                "regime": reg_name,
                "panel_section": "B1_Incremental_OPM_5Tiers_RevExpanding",
                "bucket": "0_Control_Rev_Contracting_or_Stagnant (<+2% YoY, 营收未扩张对照)",
            }))
            # Structural Operating Leverage Compounder (ex-low-ROIC cyclicals): IncOPM>=50% + TangROIC>=25% + CleanFCF>=15%
            struct_oplev = (dr["incremental_opm_expanding"] >= 0.50) & (dr["tangible_roic_ebita"] >= 0.25) & (dr["clean_fcf_margin"] >= 0.15)
            rows.append(evaluate_bucket_row(dr[struct_oplev], {
                "universe": univ_name,
                "regime": reg_name,
                "panel_section": "B1_Incremental_OPM_5Tiers_RevExpanding",
                "bucket": "6_Structural_HighOpLev_Compounder (IncOPM>=50% + 有形ROIC>=25% + 真FCF>=15%, 剔除周期底部噪音如TXN/APP/NVDA)",
            }))

            # C1 & C2. Clean Rule of 40/50/65
            c_r40 = pd.cut(dr["rule_of_clean_fcf"], bins=r40_bins, labels=r40_lbls, right=False)
            for lbl in r40_lbls:
                rows.append(evaluate_bucket_row(dr[c_r40 == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "C1_Clean_Rule_of_40_50_AllNonFin",
                    "bucket": lbl,
                }))

            dr_tech = dr[dr["sector_type"].isin(["Software_Internet", "Tech_Hardware_Semi"])]
            if len(dr_tech) >= 30:
                c_r40_t = pd.cut(dr_tech["rule_of_clean_fcf"], bins=r40_bins, labels=r40_lbls, right=False)
                for lbl in r40_lbls:
                    rows.append(evaluate_bucket_row(dr_tech[c_r40_t == lbl], {
                        "universe": univ_name,
                        "regime": reg_name,
                        "panel_section": "C2_Clean_Rule_of_40_50_Tech_Software_Only",
                        "bucket": lbl,
                    }))
                fake_r40 = (dr_tech["rule_of_gross_fcf"] >= 0.40) & (dr_tech["rule_of_clean_fcf"] < 0.30)
                true_r40 = (dr_tech["rule_of_gross_fcf"] >= 0.40) & (dr_tech["rule_of_clean_fcf"] >= 0.40)
                rows.append(evaluate_bucket_row(dr_tech[fake_r40], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "C2_Clean_Rule_of_40_50_Tech_Software_Only",
                    "bucket": "8_Fake_Rule40_SBC_Illusion (表面Rule40>=40%但扣SBC后<30%, 高SBC软件伪达标)",
                }))
                rows.append(evaluate_bucket_row(dr_tech[true_r40], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "C2_Clean_Rule_of_40_50_Tech_Software_Only",
                    "bucket": "9_True_Rule40_Clean_Verified (扣完SBC依然>=40%真Rule40王者)",
                }))

    out_df = pd.DataFrame(rows)
    out_df["bh_fdr_q_1y"] = benjamini_hochberg_fdr(out_df["p_val_1y"].values)
    out_df["bh_fdr_q_3y"] = benjamini_hochberg_fdr(out_df["p_val_3y"].values)
    return out_df


def build_table_3_wc_and_buybacks(df_valid: pd.DataFrame) -> pd.DataFrame:
    print("[G06 Table 3] Computing AR/Inventory/DeferredRev Forensics & Cannibal vs Debt-Trap Buybacks...")
    rows = []

    ar_bins = [-np.inf, -0.15, -0.05, 0.05, 0.15, 0.25, np.inf]
    ar_lbls = [
        "1_AR_Gap_lt_-15pct (回款极快/DSO大幅改善)",
        "2_AR_Gap_-15_to_-5pct (回款快于营收)",
        "3_AR_Gap_-5_to_+5pct (应收与营收健康同步)",
        "4_AR_Gap_+5_to_+15pct (轻度账期放宽)",
        "5_AR_Gap_+15_to_+25pct (应收超增15-25pct)",
        "6_AR_Gap_ge_+25pct (应收超增>=+25pct粗口径)",
    ]

    inv_bins = [-np.inf, -0.15, 0.0, 0.10, 0.20, 0.30, np.inf]
    inv_lbls = [
        "1_Inv_Gap_lt_-15pct (强劲去库/供不应求)",
        "2_Inv_Gap_-15_to_0pct (库存健康消化)",
        "3_Inv_Gap_0_to_+10pct (温和备货)",
        "4_Inv_Gap_+10_to_+20pct (库存偏高)",
        "5_Inv_Gap_+20_to_+30pct (库存积压20-30pct)",
        "6_Inv_Gap_ge_+30pct (库存超增>=+30pct粗口径)",
    ]

    dr_bins = [-np.inf, -0.15, -0.05, 0.05, 0.15, np.inf]
    dr_lbls = [
        "1_DefRev_Gap_lt_-15pct (预收蓄水池枯竭预警)",
        "2_DefRev_Gap_-15_to_-5pct (预收弱于当期确认营收)",
        "3_DefRev_Gap_-5_to_+5pct (预收与营收同步)",
        "4_DefRev_Gap_+5_to_+15pct (在手合同负债领先扩张)",
        "5_DefRev_Gap_ge_+15pct (强锁单预收爆发领先指标)",
    ]

    dil_bins = [-np.inf, -0.04, -0.02, -0.005, 0.005, 0.02, 0.05, np.inf]
    dil_lbls = [
        "1_Shrink_ge_4% (顶级食人族净缩股>=4%/年)",
        "2_Shrink_2%_to_4% (强力净缩股2%~4%/年)",
        "3_Shrink_0.5%_to_2% (温和净缩股0.5%~2%/年)",
        "4_Flat_-0.5%_to_+0.5% (股本基本恒定)",
        "5_Dilute_0.5%_to_2% (轻度股权稀释)",
        "6_Dilute_2%_to_5% (中度增发/激励稀释)",
        "7_Dilute_ge_5% (重度增发抽血机>=+5%/年)",
    ]

    for univ_name, u_mask in get_universes(df_valid)[:2]:
        du = df_valid[u_mask].copy()
        for reg_name, r_mask in get_subperiod_masks(du)[:3]:
            dr = du[r_mask].copy()
            if len(dr) < 20:
                continue

            # A. Accounts Receivable Forensics (separating M&A & Late-Q Hockey-Stick Surges vs True Channel Stuffing!)
            c_ar = pd.cut(dr["ar_minus_rev_yoy"], bins=ar_bins, labels=ar_lbls, right=False)
            for lbl in ar_lbls:
                rows.append(evaluate_bucket_row(dr[c_ar == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A_Accounts_Receivable_Channel_Stuffing",
                    "bucket": lbl,
                }))
            ar_ge15 = dr["ar_minus_rev_yoy"] >= 0.15
            ar_ma = ar_ge15 & dr["is_ma_consolidation_spike"]
            ar_hockey = ar_ge15 & (~dr["is_ma_consolidation_spike"]) & (dr["rev_accel_1q"] > 0) & (dr["gm_yoy_chg"] >= 0)
            ar_true_stuff = ar_ge15 & (~dr["is_ma_consolidation_spike"]) & (dr["rev_accel_1q"] <= 0) & (dr["gm_yoy_chg"] < 0)
            ar_severe_stuff = ar_true_stuff & (dr["ocf_ttm"] < dr["ni_ttm"])

            for b_lbl, m in [
                ("7_Raw_AR_Warning_ge_+15pct (粗口径AR增速-营收增速>=+15pct总池)", ar_ge15),
                ("8A_Confounder_MA_Consolidation_Spike (混杂项1: 季中并购并表致AR虚高>=+15pct)", ar_ma),
                ("8B_Confounder_HockeyStick_Inflection (混杂项2: 季末爆单拐点=非并购+营收加速+毛利扩张, 如PLTR/MU/STX)", ar_hockey),
                ("8C_True_Organic_Channel_Stuffing (真内生塞渠道排雷: AR超增>=15pct+非并购+营收降速+毛利下滑)", ar_true_stuff),
                ("8D_Severe_Channel_Stuffing_TripleRed (极高危塞渠道三杀: 真塞渠道+经营现金流<净利润)", ar_severe_stuff),
            ]:
                rows.append(evaluate_bucket_row(dr[m], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "A_Accounts_Receivable_Channel_Stuffing",
                    "bucket": b_lbl,
                }))

            # B. Inventory Bloat Forensics
            c_inv = pd.cut(dr["inv_minus_rev_yoy"], bins=inv_bins, labels=inv_lbls, right=False)
            for lbl in inv_lbls:
                rows.append(evaluate_bucket_row(dr[c_inv == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "B_Inventory_Bloat_Forensics",
                    "bucket": lbl,
                }))
            inv_ge20 = dr["inv_minus_rev_yoy"] >= 0.20
            inv_ramp = inv_ge20 & (~dr["is_ma_consolidation_spike"]) & (dr["rev_accel_1q"] > 0) & (dr["gm_yoy_chg"] >= 0)
            inv_true_glut = inv_ge20 & (~dr["is_ma_consolidation_spike"]) & (dr["rev_accel_1q"] <= 0) & (dr["gm_yoy_chg"] < -0.005)
            for b_lbl, m in [
                ("7_Raw_Inv_Warning_ge_+20pct (粗口径存货增速-营收增速>=+20pct总池)", inv_ge20),
                ("8A_Confounder_NewProduct_Ramp_Build (混杂项: 新品景气备货=存货超增>=20pct但营收加速+毛利扩张)", inv_ramp),
                ("8B_True_Organic_Inventory_Glut (真库存积压暴雷: 存货超增>=20pct+非并购+营收降速+毛利承压)", inv_true_glut),
            ]:
                rows.append(evaluate_bucket_row(dr[m], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "B_Inventory_Bloat_Forensics",
                    "bucket": b_lbl,
                }))

            # C. Contract Liability / Deferred Revenue Leading Indicator
            c_dr = pd.cut(dr["defrev_minus_rev_yoy"], bins=dr_bins, labels=dr_lbls, right=False)
            for lbl in dr_lbls:
                rows.append(evaluate_bucket_row(dr[c_dr == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "C_DeferredRev_ContractLiability_LeadingIndicator",
                    "bucket": lbl,
                }))

            # D1. Overall Share Dilution / Cannibal 7-Tier Ladder
            c_dil = pd.cut(dr["dilution_yoy_clean"], bins=dil_bins, labels=dil_lbls, right=False)
            for lbl in dil_lbls:
                rows.append(evaluate_bucket_row(dr[c_dil == lbl], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "D1_Share_Dilution_Cannibal_7Tiers",
                    "bucket": lbl,
                }))

            # D2. True Cash Cannibal vs Levered Secular-Stagnant Debt-Funded Buyback Trap (Strict Positive Net Debt!)
            cannibal_base = dr["dilution_yoy_clean"] <= -0.02

            # 1) Elite True Cash-Engine Growth Cannibals (ORLY/AZO/AAPL/MA/APP/LNG):
            #    Shrink >=2%, Clean FCF >= 10%, 2Y Rev CAGR >= 5%, ND/EBITDA <= 2.5x (or net cash)
            true_cannibal_elite = (
                cannibal_base
                & (dr["clean_fcf_margin"] >= 0.10)
                & (dr["rev_2y_cagr"] >= 0.05)
                & (dr["nd_to_ebitda_pit"].fillna(0.0) <= 2.5)
            )
            # 2) Broad Healthy Cash Cannibals: Shrink >=2%, Clean FCF >= 6%, Positive 2Y Rev Growth, ND/EBITDA <= 3.0x
            true_cannibal_broad = (
                cannibal_base
                & (dr["clean_fcf_margin"] >= 0.06)
                & (dr["rev_2y_cagr"] >= 0.03)
                & (dr["nd_to_ebitda_pit"].fillna(0.0) <= 3.0)
            )
            # 3) Levered Secular-Stagnant Buyback Trap (BA/IBM/MMM/GIS/KMB/WBA):
            #    Shrink >=2%, Chronic Revenue Stagnation (2Y Rev CAGR in [-15%, +2%], excluding deep semi -45% troughs!),
            #    STRICTLY POSITIVE Net Debt (`net_debt_pit > 0`) with High Leverage (`ND/EBITDA >= 2.0x` or `TotalDebt/Assets >= 0.30`)
            #    AND Rising Net Debt (`net_debt_chg_1y > 0`)!
            debt_trap_stagnant = (
                cannibal_base
                & (dr["rev_2y_cagr"] <= 0.02)
                & (dr["rev_2y_cagr"] >= -0.15)
                & (dr["net_debt_pit"] > 0)
                & ((dr["nd_to_ebitda_pit"] >= 2.0) | ((dr["total_debt"] / dr["assets"]) >= 0.30))
                & (dr["net_debt_chg_1y"] > 0)
            )
            # 4) Severe Debt-Over-FCF Levered Buyback Trap:
            #    Same positive net debt & chronic stagnation, PLUS Gross Buybacks > Clean FCF (literally borrowing to buy back!) or ND/EBITDA >= 3.0x
            debt_trap_severe = (
                debt_trap_stagnant
                & (
                    (dr["nd_to_ebitda_pit"] >= 2.8)
                    | (dr["nd_ebitda_chg_1y"] >= 0.35)
                    | (dr["buyback_ttm_pit"].notna() & dr["clean_fcf_ttm"].notna() & (dr["buyback_ttm_pit"] > dr["clean_fcf_ttm"]))
                )
            )

            for b_lbl, m in [
                ("BB0_All_Shrink_ge_2% (全部年化净缩股>=2%基准池)", cannibal_base),
                ("BB1_True_Cash_Growth_Cannibal (真造血高增缩股王: 缩股>=2%+真FCF>=10%+2Y营收增>=5%+ND/EBITDA<=2.5x, 如ORLY/AZO/APP/AAPL)", true_cannibal_elite),
                ("BB2_Healthy_FCF_Cannibal_Broad (稳健造血净缩股: 缩股>=2%+真FCF>=6%+2Y营收增>=3%+低杠杆)", true_cannibal_broad),
                ("BB3_Levered_Stagnant_Buyback_Trap (借债停滞回购陷阱: 缩股>=2%+2Y营收停滞<=2%+正净债务高杠杆且净债上升, 如IBM/MMM/BA/GIS)", debt_trap_stagnant),
                ("BB4_Severe_OverPayout_Debt_Trap (重度透支举债回购陷阱: 缩股>=2%+营收停滞+举债超额回购/ND_EBITDA>=2.8x)", debt_trap_severe),
            ]:
                rows.append(evaluate_bucket_row(dr[m], {
                    "universe": univ_name,
                    "regime": reg_name,
                    "panel_section": "D2_True_Cannibal_vs_Debt_Buyback_Trap",
                    "bucket": b_lbl,
                }))

    out_df = pd.DataFrame(rows)
    out_df["bh_fdr_q_1y"] = benjamini_hochberg_fdr(out_df["p_val_1y"].values)
    out_df["bh_fdr_q_3y"] = benjamini_hochberg_fdr(out_df["p_val_3y"].values)
    return out_df


def main():
    t_all = time.time()
    df = build_or_load_enriched_panel(force_rebuild=False)
    df_valid = df[df["entry_date"].notna()].copy()
    print(f"[G06] Valid tradeable PIT snapshots (incl. delisted residuals): {len(df_valid):,}")

    t1 = build_table_1_clean_fcf(df_valid)
    p1 = f"{OUT_DIR}/table_g06_clean_fcf_and_sbc.csv"
    t1.to_csv(p1, index=False, float_format="%.6f")
    print(f"  -> Saved {p1} ({len(t1)} rows)")

    t2 = build_table_2_tangible_roic_and_inc_opm(df_valid)
    p2 = f"{OUT_DIR}/table_g06_tangible_roic_and_inc_opm.csv"
    t2.to_csv(p2, index=False, float_format="%.6f")
    print(f"  -> Saved {p2} ({len(t2)} rows)")

    t3 = build_table_3_wc_and_buybacks(df_valid)
    p3 = f"{OUT_DIR}/table_g06_working_capital_and_buyback_forensics.csv"
    t3.to_csv(p3, index=False, float_format="%.6f")
    print(f"  -> Saved {p3} ({len(t3)} rows)")

    print(f"[G06] All 3 forensic tables generated in {time.time() - t_all:.2f}s!")


if __name__ == "__main__":
    main()
