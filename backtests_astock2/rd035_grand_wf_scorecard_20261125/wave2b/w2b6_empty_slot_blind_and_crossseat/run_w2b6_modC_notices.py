#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-6 Module C:
Research Brainstorm #3 + US Brainstorm #2:
  - C1: Earnings Pre-announcement Breakaway Surprise Island (2021-2026 full 5Y PIT from cninfo_notices_5y_pit.db)
  - C2: Major Contract / Bid Win Island (2021-2026 full 5Y PIT combining cninfo_notices_5y_pit.db + flash_news_5y_pit.db)
  - C3: Combined High-Conviction Catalyst Island (pre-event 20d ret < 15%, non-yizi, T+1/T+3/T+5 + ice-point empty-slot patch)
Peak RAM < 2.0 GB, single thread, zero yfinance.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import pickle
import re
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b6_common as cm
import wf_scorecard_engine as wf

PCT_RANGE_RE = re.compile(r"净利润变动\s*(-?\d+(?:\.\d+)?)%~(-?\d+(?:\.\d+)?)%")
NP_AMT_RE = re.compile(r"盈利[：:约]*([\d,\.]+)万元(?:至([\d,\.]+)万元)?")
PERIOD_RE = re.compile(r"(202\d)-(\d{2})-(\d{2})")

FN_AMT_YI_RE = re.compile(r"(?:中标|合同|项目|订单)[^。；\n]{0,25}?(?:约|达|为|共|合计|总投资|金额)?\s*([\d,\.]+)\s*(亿元|万元)")
FN_REV_PCT_RE = re.compile(r"(?:占[^。；\n]{0,16}?营业(?:总)?收入的?|约占[^。；\n]{0,12}?营收)\s*([\d,\.]+)%")
FN_TITLE_HEAD_RE = re.compile(r"^【([^：:】]{2,10})[：:]")
FN_CODE_RE = re.compile(r"\((\d{6})\.(?:SH|SZ)\)")
FN_NOISE_RE = re.compile(r"(?:央行|逆回购|财政部|国债|集采|征求意见|中标候选人公示失效|未中标|终止|废标|放弃)")


def _effective_trade_date(pub_ts_series: pd.Series, cal_arr: np.ndarray) -> np.ndarray:
    pub_d = pub_ts_series.astype(str).str[:10].to_numpy()
    pub_h = pub_ts_series.astype(str).str[11:19].to_numpy()
    pos = np.searchsorted(cal_arr, pub_d, side="left")
    in_b = pos < len(cal_arr)
    on_same = np.zeros(len(pub_d), dtype=bool)
    on_same[in_b] = cal_arr[pos[in_b]] == pub_d[in_b]
    eff_pos = np.where(on_same & (pub_h >= "09:25:00"), pos + 1, pos)
    out = np.empty(len(pub_d), dtype=object)
    out[:] = ""
    ok = eff_pos < len(cal_arr)
    out[ok] = cal_arr[eff_pos[ok]]
    return out


def build_pit_name_map(end_cutoff: str = "2026-11-16") -> dict[str, str]:
    """Build unambiguous sec_name -> c6 map strictly from notices + ir_qa + zt_micro_tape <= end_cutoff."""
    pairs = []
    con1 = sqlite3.connect(f"file:{cm.DATA_DIR}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    pairs.append(pd.read_sql_query("SELECT DISTINCT sec_code, sec_name FROM notices WHERE substr(pub_datetime_cst,1,10) <= ?", con1, params=(end_cutoff,)))
    con1.close()
    con2 = sqlite3.connect(f"file:{cm.DATA_DIR}/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    pairs.append(pd.read_sql_query("SELECT DISTINCT sec_code, sec_name FROM ir_qa WHERE substr(pub_datetime_cst,1,10) <= ?", con2, params=(end_cutoff,)))
    con2.close()
    con3 = sqlite3.connect(f"file:{cm.DATA_DIR}/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    pairs.append(pd.read_sql_query("SELECT DISTINCT sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ?", con3, params=(end_cutoff,)))
    con3.close()
    df = pd.concat(pairs, ignore_index=True).dropna()
    df["c6"] = df["sec_code"].astype(str).str.zfill(6)
    df = df[df["c6"].str.startswith(("00", "60", "30", "688", "689"))].copy()
    df["clean_name"] = df["sec_name"].astype(str).str.strip().str.replace(r"^\*?ST", "", regex=True)
    # Keep only names mapping uniquely to a single c6
    counts = df.groupby("clean_name")["c6"].nunique()
    uniq_names = set(counts[counts == 1].index)
    sub = df[df["clean_name"].isin(uniq_names)].drop_duplicates("clean_name")
    name_map = dict(zip(sub["clean_name"], sub["c6"]))
    # Also exact sec_name mapping
    cnt2 = df.groupby("sec_name")["c6"].nunique()
    sub2 = df[df["sec_name"].isin(set(cnt2[cnt2 == 1].index))].drop_duplicates("sec_name")
    name_map.update(dict(zip(sub2["sec_name"], sub2["c6"])))
    return name_map


def load_earnings_pre_islands(cal_arr: np.ndarray, end_cutoff: str = "2026-11-16") -> pd.DataFrame:
    con = sqlite3.connect(f"file:{cm.DATA_DIR}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    df = pd.read_sql_query(
        """
        SELECT sec_code, ann_type, pub_datetime_cst, trade_date_avail, title
        FROM notices
        WHERE ann_type IN ('业绩预告:预增', '业绩预告:扭亏', '业绩预告:略增')
          AND trade_date_avail BETWEEN '2021-01-04' AND ?
        """,
        con,
        params=(end_cutoff,),
    )
    con.close()

    df["code"] = df["sec_code"].astype(str).str.zfill(6)
    df = df[df["code"].str.startswith(("00", "60", "30", "688", "689"))].copy()
    # Strict PIT: use max(trade_date_avail, eff_dt(pub_datetime_cst))
    eff = _effective_trade_date(df["pub_datetime_cst"], cal_arr)
    df["buy_date"] = np.maximum(df["trade_date_avail"].astype(str).str[:10].to_numpy(), eff)
    df = df[df["buy_date"].between("2021-01-04", end_cutoff)].copy()

    yoy_mids, np_yis, ann_fracs, is_kfs, is_nks = [], [], [], [], []
    for at, t in zip(df["ann_type"], df["title"]):
        m_y = PCT_RANGE_RE.search(t)
        if m_y:
            y0, y1 = float(m_y.group(1)), float(m_y.group(2))
            yoy_mid = 0.5 * (y0 + y1)
        else:
            yoy_mid = np.nan
        m_np = NP_AMT_RE.search(t)
        if m_np:
            v0 = float(m_np.group(1).replace(",", ""))
            v1 = float(m_np.group(2).replace(",", "")) if m_np.group(2) else v0
            np_yi = 0.5 * (v0 + v1) / 10000.0
        else:
            np_yi = np.nan
        m_p = PERIOD_RE.search(t)
        frac = 1.0
        if m_p:
            mo = int(m_p.group(2))
            if mo in (3, 6, 9, 12):
                frac = mo / 12.0
        yoy_mids.append(yoy_mid)
        np_yis.append(np_yi)
        ann_fracs.append(frac)
        is_kfs.append(1 if "扣非" in t else 0)
        is_nks.append(1 if "扭亏" in at else 0)

    df["cat_yoy_mid_pct"] = yoy_mids
    df["cat_np_ann_yi"] = np.where(np.array(ann_fracs) > 0, np.array(np_yis) / np.array(ann_fracs), np.nan)
    df["cat_is_kfe"] = is_kfs
    df["cat_is_niukui"] = is_nks
    df["cat_is_yuzeng"] = (df["ann_type"] == "业绩预告:预增").astype(np.int8)

    # Collapse duplicate lines for same (code, buy_date), prioritizing 扣非 & highest yoy_mid
    df = df.sort_values(["code", "buy_date", "cat_is_kfe", "cat_yoy_mid_pct"], ascending=[True, True, False, False])
    agg = df.drop_duplicates(["code", "buy_date"], keep="first").copy()
    # Keep high surprise (>= 50% YoY or 扭亏)
    agg = agg[(agg["cat_yoy_mid_pct"] >= 50.0) | (agg["cat_is_niukui"] == 1)].reset_index(drop=True)
    return agg[["code", "buy_date", "cat_yoy_mid_pct", "cat_np_ann_yi", "cat_is_kfe", "cat_is_niukui", "cat_is_yuzeng"]]


def load_contract_islands(cal_arr: np.ndarray, name_map: dict[str, str], end_cutoff: str = "2026-11-16") -> pd.DataFrame:
    # 1. CNINFO notices (2021-01 + 2025-2026)
    con1 = sqlite3.connect(f"file:{cm.DATA_DIR}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    df_cn = pd.read_sql_query(
        """
        SELECT sec_code, pub_datetime_cst, trade_date_avail, title, ann_type
        FROM notices
        WHERE (ann_type='重大合同' OR title LIKE '%中标%' OR title LIKE '%重大合同%')
          AND substr(pub_datetime_cst,1,10) <= ?
        """,
        con1,
        params=(end_cutoff,),
    )
    con1.close()
    df_cn["code"] = df_cn["sec_code"].astype(str).str.zfill(6)
    df_cn = df_cn[df_cn["code"].str.startswith(("00", "60", "30", "688", "689"))].copy()
    df_cn = df_cn[~df_cn["title"].str.contains("放弃|终止|废标|不予|未中标", regex=True, na=False)].copy()
    df_cn["buy_date"] = _effective_trade_date(df_cn["pub_datetime_cst"], cal_arr)
    df_cn["cat_amt_yi"] = np.nan
    df_cn["cat_rev_pct"] = np.nan
    df_cn["cat_src_cninfo"] = 1

    # 2. Flash News Sina 724 (full 2021-2026!)
    con2 = sqlite3.connect(f"file:{cm.DATA_DIR}/flash_news_5y_pit.db?mode=ro", uri=True)
    df_fn = pd.read_sql_query(
        """
        SELECT pub_datetime_cst, content
        FROM flash_news
        WHERE pub_datetime_cst BETWEEN '2021-01-01' AND ?
          AND (content LIKE '%中标%' OR content LIKE '%签订重大合同%' OR content LIKE '%签署重大合同%' OR content LIKE '%中标通知书%')
        """,
        con2,
        params=(f"{end_cutoff} 09:25:00",),
    )
    con2.close()

    fn_rows = []
    eff_fn = _effective_trade_date(df_fn["pub_datetime_cst"], cal_arr)
    for dt_v, txt in zip(eff_fn, df_fn["content"]):
        if not dt_v or not txt or FN_NOISE_RE.search(txt):
            continue
        code = None
        mc = FN_CODE_RE.search(txt[:160])
        if mc:
            code = mc.group(1)
        else:
            mh = FN_TITLE_HEAD_RE.search(txt[:80])
            if mh:
                nm = mh.group(1).strip()
                code = name_map.get(nm)
        if not code or not code.startswith(("00", "60", "30", "688", "689")):
            continue
        amt_yi = np.nan
        ma = FN_AMT_YI_RE.search(txt[:450])
        if ma:
            val = float(ma.group(1).replace(",", ""))
            amt_yi = val if ma.group(2) == "亿元" else val / 10000.0
        rev_pct = np.nan
        mr = FN_REV_PCT_RE.search(txt[:450])
        if mr:
            rev_pct = float(mr.group(1).replace(",", ""))
        fn_rows.append((code, dt_v, amt_yi, rev_pct, 0))

    df_fn_clean = pd.DataFrame(fn_rows, columns=["code", "buy_date", "cat_amt_yi", "cat_rev_pct", "cat_src_cninfo"])
    comb = pd.concat(
        [df_cn[["code", "buy_date", "cat_amt_yi", "cat_rev_pct", "cat_src_cninfo"]], df_fn_clean],
        ignore_index=True,
    )
    comb = comb[comb["buy_date"].between("2021-01-04", end_cutoff)].copy()
    agg = comb.groupby(["code", "buy_date"], as_index=False).agg(
        cat_amt_yi=("cat_amt_yi", "max"),
        cat_rev_pct=("cat_rev_pct", "max"),
        cat_src_cninfo=("cat_src_cninfo", "max"),
    ).sort_values(["code", "buy_date"]).reset_index(drop=True)
    return agg


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(cm.BASE_DIR)
    px_idx = cm.PriceReturnIndex(end_cutoff="2026-11-25")
    cal_all = np.array(sorted(v20_ctx["bench"]["trade_date"].tolist()))

    earn_df = load_earnings_pre_islands(cal_all, end_cutoff="2026-11-16")
    print(f"[ModC] Earnings pre-announcement islands: {len(earn_df)} rows | by yr: {earn_df['buy_date'].str[:4].value_counts().sort_index().to_dict()}")

    name_map = build_pit_name_map(end_cutoff="2026-11-16")
    cont_df = load_contract_islands(cal_all, name_map, end_cutoff="2026-11-16")
    print(f"[ModC] Contract/bid islands (cninfo+flash5y): {len(cont_df)} rows | by yr: {cont_df['buy_date'].str[:4].value_counts().sort_index().to_dict()}")

    horizons = (1, 3, 5)

    # Prepare Track C1: Earnings Breakaway Surprise (non-prerun ret_20d_t1 < 15%, non-yizi)
    e_ret = px_idx.lookup_forward_returns(earn_df, horizons=horizons, buy_at="open", min_amt_yi=0.0)
    e_extra = ["cat_yoy_mid_pct", "cat_np_ann_yi", "cat_is_kfe", "cat_is_niukui", "cat_is_yuzeng", "cat_imp_ey_pct"]
    e_feat, fcols_e = cm.attach_pit_features(e_ret, buy_at="open", extra_cols=e_extra)
    e_feat["cat_imp_ey_pct"] = np.where(e_feat["mcap_yi_t1"] > 0, e_feat["cat_np_ann_yi"] / e_feat["mcap_yi_t1"] * 100.0, np.nan)
    e_clean = e_feat[
        e_feat["can_buy"]
        & (e_feat["amount_yi_t1"] >= 0.5)
        & (e_feat["ret_20d_t1"].fillna(0.0) < 15.0)
        & (e_feat["prev_streak"] == 0)
    ].copy().reset_index(drop=True)
    # Also low-attention subset (Brainstorm: xq_posts_1y_pct <= 0.50 & yoy >= 80%)
    e_lowheat = e_clean[
        ((e_clean["cat_yoy_mid_pct"] >= 80.0) | (e_clean["cat_is_niukui"] == 1))
        & (e_clean["xq_posts_1y_pct"].fillna(0.5) <= 0.55)
    ].copy().reset_index(drop=True)

    # Prepare Track C2: Large Contract / Bid Win Island (non-prerun ret_20d_t1 < 15%, non-yizi)
    c_ret = px_idx.lookup_forward_returns(cont_df, horizons=horizons, buy_at="open", min_amt_yi=0.0)
    c_extra = ["cat_amt_yi", "cat_rev_pct", "cat_src_cninfo", "cat_amt_to_mcap_pct"]
    c_feat, fcols_c = cm.attach_pit_features(c_ret, buy_at="open", extra_cols=c_extra)
    c_feat["cat_amt_to_mcap_pct"] = np.where(c_feat["mcap_yi_t1"] > 0, c_feat["cat_amt_yi"] / c_feat["mcap_yi_t1"] * 100.0, np.nan)
    c_clean = c_feat[
        c_feat["can_buy"]
        & (c_feat["amount_yi_t1"] >= 0.4)
        & (c_feat["ret_20d_t1"].fillna(0.0) < 15.0)
        & (c_feat["prev_streak"] == 0)
    ].copy().reset_index(drop=True)
    c_large = c_clean[
        (c_clean["cat_rev_pct"].fillna(0.0) >= 10.0)
        | (c_clean["cat_amt_to_mcap_pct"].fillna(0.0) >= 5.0)
        | (c_clean["cat_amt_yi"].fillna(0.0) >= 3.0)
    ].copy().reset_index(drop=True)

    # Prepare Track C3: Ice-Point / Weak-Market Catalyst Island (combines EarnSurprise + Contract on sent_phase_t1 in {1,2,5} or V20 empty)
    e_sub = e_clean[["buy_date", "code", "can_buy", "is_yizi", "buy_hhmm", "exit_hhmm", "exit_date_h1", "gross_ret_h1", "exit_date_h3", "gross_ret_h3", "exit_date_h5", "gross_ret_h5"]].copy()
    e_sub["cat_type"] = 1
    c_sub = c_clean[["buy_date", "code", "can_buy", "is_yizi", "buy_hhmm", "exit_hhmm", "exit_date_h1", "gross_ret_h1", "exit_date_h3", "gross_ret_h3", "exit_date_h5", "gross_ret_h5"]].copy()
    c_sub["cat_type"] = 2
    comb_raw = pd.concat([e_sub, c_sub], ignore_index=True).drop_duplicates(["buy_date", "code"]).reset_index(drop=True)
    comb_feat, fcols_comb = cm.attach_pit_features(comb_raw, buy_at="open", extra_cols=["cat_type"])
    comb_ice = comb_feat[comb_feat["L1_sent_phase_t1"].isin([1, 2, 5])].copy().reset_index(drop=True)

    pools = {
        "C1_EarnPre_NoRun": (e_clean, fcols_e),
        "C1b_EarnPre_HighLowHeat": (e_lowheat, fcols_e),
        "C2_Contract_AllNoRun": (c_clean, fcols_c),
        "C2b_Contract_LargeAmt": (c_large, fcols_c),
        "C3_Cat_IceWeakRegime": (comb_ice, fcols_comb),
    }

    results = []
    for pname, (pdf, fcols) in pools.items():
        print(f"[ModC] Pool {pname}: {len(pdf)} cands across {pdf['buy_date'].nunique()} days")
        for h in horizons:
            sub = pdf.copy()
            sub["exit_date"] = sub[f"exit_date_h{h}"]
            sub["gross_ret"] = sub[f"gross_ret_h{h}"]
            sub = sub[(sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
            tid = f"ModC_{pname}_H{h}"
            min_w = 80 if len(sub) >= 1200 else 35
            min_wr = 40 if len(sub) >= 1200 else 20
            res = cm.evaluate_and_audit_track(
                track_id=tid,
                module_name="ModuleC_NoticeIslands",
                desc=f"{pname} hold {h}d (open)",
                cand_df=sub,
                feature_cols=fcols,
                px_idx=px_idx,
                v20_ctx=v20_ctx,
                buy_at="open",
                thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
                recalc_freq="daily",
                min_warmup_trades=min_w,
                min_warmup_trades_rare=min_wr,
                min_warmup_months=18,
                perm_n=1000,
                run_trunc_check=(h == 3),
                trunc_threshold="top20",
            )
            br = res["best_row"]
            t_pass = res["truncation_20241231"]["zero_leakage_pass"] if res["truncation_20241231"] else "NA"
            print(f"  -> {tid:32s} best={br['threshold']:8s} n={br['n_trades_wf']:3d} WR={br['wr_wf_pct']:5.1f}% mean={br['mean_wf_pct']:5.2f}% NAV={br['nav_wf']:6.3f} ex5={br['ex5_wf']:6.3f} Sh={br['sharpe_wf']:5.2f} MDD={br['mdd_wf_pct']:5.1f}% corrV20={br['corr_v20_wf']:6.3f} dNAV_V20={br['patch_delta_nav_ratio']:6.4f} p={br['perm_sd_p']} trunc={t_pass}")
            results.append(res)

    out_pkl = f"{cm.OUT_DIR}/_modC_results.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(results, f)
    print(f"[ModC] Completed in {time.time()-t0:.1f}s | Peak RSS={cm.peak_rss_mb()} MB -> {out_pkl}")


if __name__ == "__main__":
    main()
