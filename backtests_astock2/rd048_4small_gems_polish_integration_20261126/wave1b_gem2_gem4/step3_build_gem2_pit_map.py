#!/usr/bin/env python3
"""Step 3 for Gem 2 (Ultra-Lean < 1.3 GB Peak RSS):
Audit hindsight contamination in w2b6 product_tree_map.json and build TWO 100% strict
causal PIT US->A-share candidate pools + controls.
Two-pass streaming:
  Pass 1+2: Load ONLY lightweight filter cols (dt, c6, ret_1d, csrc_ind_id, list_age, amount_yi_t1, is_st_pit, is_yizi_zt, is_yizi_dt)
            to identify ~264k candidate keys & causal rolling 250d corr/beta.
  Pass 3:   Attach 16 polish features + forward prices ONLY for the ~264k candidate rows!

Strictly ZERO yfinance imports. Supports physical truncation cutoff_date for zero-leakage verification.
"""
import os
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[k] = "1"

import gc
import json
import resource
import sqlite3
import time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)

BASE = Path("/Users/huaichuaibeimeng/claude-projects")
OUT_DIR = BASE / "sim-portfolio/backtests_astock2/rd048_4small_gems_polish_integration_20261126/wave1b_gem2_gem4"
W1_BASE = BASE / "sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
US_DB = BASE / "sim-portfolio/data/us_price_db"
PRODUCT_TREE_JSON = BASE / "sim-portfolio/data/product_tree_map.json"
CSRC_CSV = BASE / "sim-portfolio/data/csrc_industry_pit_clean.csv"
IR_QA_DB = BASE / "sim-portfolio/data/cninfo_ir_qa_5y_pit.db"

W2B6_TREE_TO_US = [
    (["半导体设备", "MLCC"], ["LRCX", "AMAT", "KLAC", "ASML"]),
    (["AI算力", "光纤光缆"], ["NVDA", "AVGO", "COHR", "LITE", "MU", "TSM"]),
    (["AI供电", "可控核聚变", "电力/核电"], ["VRT", "ETN", "GEV", "CEG", "VST"]),
    (["GLP-1", "CXO", "创新药"], ["LLY", "NVO", "TMO"]),
    (["苹果新形态", "AI端侧"], ["AAPL", "QCOM"]),
    (["人形机器人", "智能驾驶", "电动车", "固态电池"], ["TSLA", "ALB"]),
    (["钨硬质合金", "战略小金属", "铜"], ["FCX", "SCCO"]),
    (["军工", "商业航天"], ["LMT", "RTX", "RKLB"]),
]

PIT_GROUPS = [
    {
        "group": "G1_SEMI_AI_HW",
        "bench_etf": "SMH",
        "drivers": ["SMH", "SOXX", "NVDA", "AVGO", "AMD", "TSM", "MU", "ASML", "LRCX", "AMAT", "KLAC", "COHR", "LITE"],
        "csrc_prefixes": ("C39", "C35"),
        "ir_kws": ["英伟达", "NVIDIA", "台积电", "AMD", "博通", "美光", "光模块", "半导体设备"],
        "track2_pre2020": ["002371", "688012", "603986", "603501", "600584", "002156", "600703", "002049", "300666", "688008", "002916"],
    },
    {
        "group": "G2_APPLE_CE",
        "bench_etf": "AAPL",
        "drivers": ["AAPL", "QCOM"],
        "csrc_prefixes": ("C39", "C38"),
        "ir_kws": ["苹果", "Apple", "高通", "消费电子"],
        "track2_pre2020": ["002475", "002241", "300433", "002938", "002384", "601138", "002600", "300136"],
    },
    {
        "group": "G3_TSLA_EV",
        "bench_etf": "DRIV",
        "drivers": ["TSLA", "DRIV", "LIT", "ALB", "BOTZ"],
        "csrc_prefixes": ("C36", "C38", "C26", "C34", "C35"),
        "ir_kws": ["特斯拉", "Tesla", "比亚迪", "人形机器人", "新能源汽车"],
        "track2_pre2020": ["300750", "002050", "601689", "300124", "002460", "002466", "603799", "300450"],
    },
    {
        "group": "G4_POWER_GRID",
        "bench_etf": "ETN",
        "drivers": ["ETN", "VRT", "CEG", "VST", "GEV"],
        "csrc_prefixes": ("C38", "D44", "C34"),
        "ir_kws": ["特高压", "电网", "核电", "数据中心供电", "变压器"],
        "track2_pre2020": ["600406", "600089", "002028", "601179", "600312", "601985"],
    },
    {
        "group": "G5_BIOPHARMA",
        "bench_etf": "XBI",
        "drivers": ["XBI", "IBB", "LLY", "NVO", "TMO"],
        "csrc_prefixes": ("C27", "M73"),
        "ir_kws": ["礼来", "诺和诺德", "GLP-1", "CXO", "创新药", "ADC"],
        "track2_pre2020": ["603259", "300759", "300347", "600276", "002821"],
    },
    {
        "group": "G6_GOLD_COPPER",
        "bench_etf": "COPX",
        "drivers": ["GLD", "GDX", "COPX", "CPER", "FCX", "SCCO"],
        "csrc_prefixes": ("B09", "C32"),
        "ir_kws": ["铜矿", "金矿", "黄金", "有色金属"],
        "track2_pre2020": ["601899", "603993", "600362", "000878", "600547", "600489", "000975"],
    },
    {
        "group": "G7_DEFENSE_AERO",
        "bench_etf": "ITA",
        "drivers": ["ITA", "LMT", "RTX", "RKLB"],
        "csrc_prefixes": ("C37", "C39", "C34"),
        "ir_kws": ["航空发动机", "军工", "卫星", "商业航天"],
        "track2_pre2020": ["600893", "000768", "600760", "600038", "002025"],
    },
    {
        "group": "G8_TECH_SW",
        "bench_etf": "QQQ",
        "drivers": ["QQQ", "MSFT", "META"],
        "csrc_prefixes": ("I65", "I64", "C39"),
        "ir_kws": ["微软", "Meta", "大模型", "人工智能"],
        "track2_pre2020": ["002415", "688111", "002230", "600570"],
    },
]


def load_us_returns(max_us_date: str) -> pd.DataFrame:
    stock_tickers = sorted({t for g in PIT_GROUPS for t in g["drivers"]} | {"CEG", "GEV", "RKLB"})
    tbl = pq.read_table(
        US_DB / "all_daily.parquet",
        columns=["date", "ticker", "adj_close"],
        filters=[
            ("ticker", "in", stock_tickers),
            ("date", ">=", pd.Timestamp("2020-01-01")),
            ("date", "<=", pd.Timestamp(max_us_date)),
        ],
    )
    us_all = tbl.to_pandas()
    del tbl
    pa.default_memory_pool().release_unused()
    us_all["date"] = pd.to_datetime(us_all["date"]).dt.strftime("%Y-%m-%d")
    us_all = us_all.sort_values(["ticker", "date"]).reset_index(drop=True)
    us_all["ret_1d"] = us_all.groupby("ticker")["adj_close"].pct_change()
    frames = [us_all[["date", "ticker", "ret_1d"]]]

    etf_files = {
        "SMH": US_DB / "sectors/SMH.parquet",
        "SOXX": US_DB / "sectors/SOXX.parquet",
        "XBI": US_DB / "sectors/XBI.parquet",
        "IBB": US_DB / "sectors/IBB.parquet",
        "COPX": US_DB / "sectors/COPX.parquet",
        "CPER": US_DB / "sectors/CPER.parquet",
        "GLD": US_DB / "sectors/GLD.parquet",
        "GDX": US_DB / "sectors/GDX.parquet",
        "LIT": US_DB / "sectors/LIT.parquet",
        "DRIV": US_DB / "sectors/DRIV.parquet",
        "ITA": US_DB / "sectors/ITA.parquet",
        "BOTZ": US_DB / "sectors/BOTZ.parquet",
        "QQQ": US_DB / "benchmarks/QQQ.parquet",
    }
    for tk, p in etf_files.items():
        df = pd.read_parquet(p).reset_index()
        dt_col = "date" if "date" in df.columns else ("Date" if "Date" in df.columns else df.columns[0])
        s_dt = pd.to_datetime(df[dt_col])
        if isinstance(s_dt.dtype, pd.DatetimeTZDtype):
            s_dt = s_dt.dt.tz_localize(None)
        df["date"] = s_dt.dt.strftime("%Y-%m-%d")
        df = df[(df["date"] >= "2020-01-01") & (df["date"] <= max_us_date)].sort_values("date").reset_index(drop=True)
        px_col = "adj_close" if "adj_close" in df.columns else "close"
        df["ret_1d"] = df[px_col].pct_change()
        df["ticker"] = tk
        frames.append(df[["date", "ticker", "ret_1d"]])

    all_us = pd.concat(frames, ignore_index=True).dropna(subset=["ret_1d"]).drop_duplicates(["date", "ticker"])
    return all_us.pivot(index="date", columns="ticker", values="ret_1d").sort_index()


def build_us_to_cn_alignment(cn_dates: list[str], us_ret_wide: pd.DataFrame) -> pd.DataFrame:
    us_dates = pd.to_datetime(us_ret_wide.index)
    us_df = us_ret_wide.copy()
    us_df["us_dt"] = us_dates
    us_df = us_df.sort_values("us_dt").reset_index(drop=True)

    cn_df = pd.DataFrame({"buy_date": cn_dates, "cn_dt": pd.to_datetime(cn_dates)}).sort_values("cn_dt")
    aligned = pd.merge_asof(
        cn_df, us_df, left_on="cn_dt", right_on="us_dt",
        allow_exact_matches=False, direction="backward",
    )
    aligned["cal_lag_days"] = (aligned["cn_dt"] - aligned["us_dt"]).dt.days
    aligned["is_fresh_overnight"] = aligned["cal_lag_days"] <= 5
    return aligned


def audit_product_tree_hindsight() -> dict:
    with open(PRODUCT_TREE_JSON) as f:
        pt = json.load(f)
    tdf = pd.DataFrame(pt["trees"])
    tdf["code"] = tdf["code"].astype(str).str.zfill(6)
    patch_log = pt.get("patch_log", [])
    post_patch_trees = ["成熟制程涨价", "光纤光缆", "MLCC"]
    pcb_node_kw = "PCB本体"

    w2b6_rows = []
    for kws, us_list in W2B6_TREE_TO_US:
        m = tdf["tree"].apply(lambda s: any(k in str(s) for k in kws))
        sub = tdf[m].copy()
        sub["us_drivers"] = ",".join(us_list)
        w2b6_rows.append(sub)
    mapped = pd.concat(w2b6_rows, ignore_index=True)

    is_pcb_patch = mapped["node"].astype(str).str.contains(pcb_node_kw, regex=False)
    is_0814_patch = mapped["tree"].astype(str).apply(lambda s: any(k in s for k in post_patch_trees))
    is_modern_2025_tree = mapped["tree"].astype(str).str.contains("VR200|Rubin|Optimus|宇树|AI眼镜|折叠iPhone|可控核聚变|全固态|千帆星网|AI端侧", regex=True)

    pcb_stocks = sorted(set(zip(mapped.loc[is_pcb_patch, "code"], mapped.loc[is_pcb_patch, "name"])))
    p0814_stocks = sorted(set(zip(mapped.loc[is_0814_patch, "code"], mapped.loc[is_0814_patch, "name"])))
    modern_stocks = sorted(set(zip(mapped.loc[is_modern_2025_tree, "code"], mapped.loc[is_modern_2025_tree, "name"])))

    return {
        "built_at": pt.get("built_at"),
        "total_mapped_rows_in_w2b6": int(len(mapped)),
        "unique_stocks_in_w2b6": int(mapped["code"].nunique()),
        "mingmen_stocks_in_w2b6": int(mapped.loc[mapped["is_mingmen"] == True, "code"].nunique()),
        "patch_20260807_pcb_count": len(pcb_stocks),
        "patch_20260807_pcb_stocks": [f"{c}:{n}" for c, n in pcb_stocks],
        "patch_20260814_new_trees_count": len(p0814_stocks),
        "patch_20260814_new_trees_stocks": [f"{c}:{n}" for c, n in p0814_stocks],
        "posthoc_2025_2026_concept_trees_unique_stocks": len(modern_stocks),
        "posthoc_2025_2026_sample": [f"{c}:{n}" for c, n in modern_stocks[:20]],
        "patch_log": patch_log,
    }


def compute_rolling_corr_beta_slice(
    r_sub: np.ndarray,
    us_vec: np.ndarray,
    window: int = 250,
    min_periods: int = 60,
) -> tuple[np.ndarray, np.ndarray]:
    T, M = r_sub.shape
    corr_out = np.full((T, M), np.nan, dtype=np.float32)
    beta_out = np.full((T, M), np.nan, dtype=np.float32)

    valid_u = np.isfinite(us_vec)
    r_fin = np.isfinite(r_sub)
    valid = r_fin & valid_u[:, None]
    r_clean = np.where(valid, r_sub.astype(np.float64), 0.0)
    u = np.where(valid_u, us_vec.astype(np.float64), 0.0)[:, None]
    u_v = np.where(valid, u, 0.0)

    cn = np.zeros((T + 1, M), dtype=np.int32)
    np.cumsum(valid, axis=0, out=cn[1:])
    sr = np.zeros((T + 1, M), dtype=np.float64)
    np.cumsum(r_clean, axis=0, out=sr[1:])
    sr2 = np.zeros((T + 1, M), dtype=np.float64)
    np.cumsum(r_clean * r_clean, axis=0, out=sr2[1:])
    su = np.zeros((T + 1, M), dtype=np.float64)
    np.cumsum(u_v, axis=0, out=su[1:])
    su2 = np.zeros((T + 1, M), dtype=np.float64)
    np.cumsum(u_v * u_v, axis=0, out=su2[1:])
    sru = np.zeros((T + 1, M), dtype=np.float64)
    np.cumsum(r_clean * u_v, axis=0, out=sru[1:])

    for t in range(min_periods, T):
        s0 = max(0, t - window)
        s1 = t
        cnt = (cn[s1] - cn[s0]).astype(np.float64)
        ok = cnt >= min_periods
        if not np.any(ok):
            continue
        sum_r = sr[s1] - sr[s0]
        sum_r2 = sr2[s1] - sr2[s0]
        sum_u = su[s1] - su[s0]
        sum_u2 = su2[s1] - su2[s0]
        sum_ru = sru[s1] - sru[s0]

        cov = sum_ru - (sum_r * sum_u) / np.maximum(cnt, 1.0)
        var_r = sum_r2 - (sum_r * sum_r) / np.maximum(cnt, 1.0)
        var_u = sum_u2 - (sum_u * sum_u) / np.maximum(cnt, 1.0)

        denom_corr = np.sqrt(np.maximum(var_r, 0.0) * np.maximum(var_u, 0.0))
        vc = ok & (denom_corr > 1e-12) & (var_u > 1e-12)
        c_row = np.full(M, np.nan, dtype=np.float32)
        b_row = np.full(M, np.nan, dtype=np.float32)
        c_row[vc] = (cov[vc] / denom_corr[vc]).astype(np.float32)
        b_row[vc] = (cov[vc] / var_u[vc]).astype(np.float32)
        corr_out[t] = c_row
        beta_out[t] = b_row

    return corr_out, beta_out


def build_ir_qa_first_mention_map(cutoff_date: str) -> dict[str, dict[str, str]]:
    con = sqlite3.connect(str(IR_QA_DB))
    df_ir = pd.read_sql(
        "SELECT sec_code, trade_date_avail, title, full_text FROM ir_qa WHERE trade_date_avail <= ?",
        con, params=(cutoff_date,),
    )
    con.close()
    df_ir["c6"] = df_ir["sec_code"].astype(str).str.zfill(6)
    txt = df_ir["title"].fillna("") + " " + df_ir["full_text"].fillna("")

    group_first_dt = {}
    for g in PIT_GROUPS:
        pat = "|".join(g["ir_kws"])
        m = df_ir[txt.str.contains(pat, case=False, regex=True)]
        group_first_dt[g["group"]] = m.groupby("c6")["trade_date_avail"].min().to_dict()
    del df_ir, txt
    gc.collect()
    return group_first_dt


def build_all_pools(cutoff_date: str = "2026-11-25", save_outputs: bool = True) -> dict:
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pq_path = W1_BASE / "stock_day_core_features_pit.parquet"

    # Pass 1: Lightweight 9 cols streamed cleanly (~220 MB max!)
    p1_cols = ["dt", "c6", "ret_1d", "csrc_ind_id", "list_age", "amount_yi_t1", "is_st_pit", "is_yizi_zt", "is_yizi_dt"]
    pf = pq.ParquetFile(pq_path)
    p1_chunks = []
    for batch in pf.iter_batches(batch_size=350_000, columns=p1_cols):
        b = batch.to_pandas()
        dt_ok = {x for x in b["dt"].cat.categories if str(x) <= cutoff_date} if hasattr(b["dt"], "cat") else None
        m = b["dt"].isin(dt_ok) if dt_ok is not None else (b["dt"].astype(str) <= cutoff_date)
        sub = b[m].copy()
        del b, m
        if len(sub) > 0:
            sub["ret_1d"] = sub["ret_1d"].astype(np.float32)
            sub["list_age"] = sub["list_age"].astype(np.float32)
            sub["amount_yi_t1"] = sub["amount_yi_t1"].astype(np.float32)
            p1_chunks.append(sub)
    pa.default_memory_pool().release_unused()
    p1 = pd.concat(p1_chunks, ignore_index=True)
    del p1_chunks
    gc.collect()

    p1["dt"] = p1["dt"].cat.rename_categories(lambda s: str(s))
    p1["c6"] = p1["c6"].cat.rename_categories(lambda s: str(s).zfill(6))
    cn_dates = sorted([str(x) for x in p1["dt"].cat.categories if str(x) <= cutoff_date])
    dt_to_ti = {d: i for i, d in enumerate(cn_dates)}
    c6_list = sorted([str(x) for x in p1["c6"].cat.categories])
    c6_to_ci = {c: i for i, c in enumerate(c6_list)}

    cat_to_ti = np.array([dt_to_ti.get(str(d), -1) for d in p1["dt"].cat.categories], dtype=np.int32)
    cat_to_ci = np.array([c6_to_ci.get(str(c), -1) for c in p1["c6"].cat.categories], dtype=np.int32)
    ti_arr = cat_to_ti[p1["dt"].cat.codes.to_numpy(dtype=np.int32)]
    ci_arr = cat_to_ci[p1["c6"].cat.codes.to_numpy(dtype=np.int32)]

    T, N = len(cn_dates), len(c6_list)
    ret_mat = np.full((T, N), np.nan, dtype=np.float32)
    ret_mat[ti_arr, ci_arr] = p1["ret_1d"].to_numpy(dtype=np.float32)

    cdf = pd.read_csv(CSRC_CSV)
    cdf["c6_str"] = cdf["sec_code"].astype(int).astype(str).str.zfill(6)
    cdf = cdf[cdf["start_date"] <= cutoff_date].sort_values(["c6_str", "start_date"]).reset_index(drop=True)
    name_map = cdf.drop_duplicates("c6_str", keep="first").set_index("c6_str")["code_name"].to_dict()

    dict_anchor_dt = min(cutoff_date, "2024-12-31")
    max_anchor_ti = max((i for i, d in enumerate(cn_dates) if d <= dict_anchor_dt), default=0)
    anc_mask = (ti_arr >= 0) & (ti_arr <= max_anchor_ti)
    anc_df = pd.DataFrame({
        "ci": ci_arr[anc_mask],
        "ti": ti_arr[anc_mask],
        "csrc_ind_id": p1["csrc_ind_id"].to_numpy()[anc_mask],
    }).sort_values(["ci", "ti"]).drop_duplicates("ci", keep="last")
    anc_df["c6_str"] = [c6_list[i] for i in anc_df["ci"]]
    anchor_cdf = cdf[cdf["start_date"] <= dict_anchor_dt].drop_duplicates(["c6_str"], keep="last")[["c6_str", "industry"]]
    am = anc_df.merge(anchor_cdf, on="c6_str", how="inner")
    id_to_ind = am.groupby("csrc_ind_id")["industry"].agg(lambda s: s.dropna().value_counts().index[0] if len(s.dropna()) else "").to_dict()
    id_to_prefix = {int(k): str(v)[:3] for k, v in id_to_ind.items()}
    del ti_arr, ci_arr, anc_df, am, anchor_cdf, cdf
    gc.collect()

    # Keep only executable rows in p1
    p1["csrc_prefix"] = p1["csrc_ind_id"].map(id_to_prefix).fillna("").astype("category")
    can_exec = (
        (~p1["is_st_pit"].astype(bool))
        & (~p1["is_yizi_zt"].astype(bool))
        & (~p1["is_yizi_dt"].astype(bool))
    )
    sd = p1.loc[can_exec, ["dt", "c6", "csrc_prefix", "list_age", "amount_yi_t1"]].reset_index(drop=True)
    del p1, can_exec
    gc.collect()

    us_wide = load_us_returns(cutoff_date)
    us_aligned = build_us_to_cn_alignment(cn_dates, us_wide)
    us_aligned_idx = us_aligned.set_index("buy_date")
    fresh_mask = us_aligned["is_fresh_overnight"].to_numpy(dtype=bool)

    with open(PRODUCT_TREE_JSON) as f:
        pt_json = json.load(f)
    pt_df = pd.DataFrame(pt_json["trees"])
    pt_df["code"] = pt_df["code"].astype(str).str.zfill(6)
    pt_df["is_patch_08"] = (
        pt_df["node"].astype(str).str.contains("PCB本体", regex=False)
        | pt_df["tree"].astype(str).str.contains("成熟制程涨价|光纤光缆|MLCC", regex=True)
    )

    ir_first_map = build_ir_qa_first_mention_map(cutoff_date)
    track_frames = []

    # A. Control 0: Store Control0_Leaky_All ONCE with boolean flags
    c0_rows = []
    for kws, us_list in W2B6_TREE_TO_US:
        m_tree = pt_df["tree"].apply(lambda s: any(k in str(s) for k in kws))
        sub_pt = pt_df[m_tree]
        codes = sorted(sub_pt["code"].unique())
        mm_codes = set(sub_pt.loc[sub_pt["is_mingmen"] == True, "code"])
        prepatch_mm = set(sub_pt.loc[(sub_pt["is_mingmen"] == True) & (~sub_pt["is_patch_08"]), "code"])
        cols_avail = [u for u in us_list if u in us_aligned_idx.columns]
        if not codes or not cols_avail:
            continue
        max_us = us_aligned_idx[cols_avail].max(axis=1)
        trig_dts = set(max_us.index[(max_us >= 0.04) & us_aligned_idx["is_fresh_overnight"]].tolist())
        sub_sd = sd[sd["dt"].isin(trig_dts) & sd["c6"].isin(codes)].copy()
        if len(sub_sd) > 0:
            sub_sd["dt"] = sub_sd["dt"].astype(str)
            sub_sd["c6"] = sub_sd["c6"].astype(str)
            sub_sd["c0_mingmen"] = sub_sd["c6"].isin(mm_codes)
            sub_sd["c0_prepatch_mingmen"] = sub_sd["c6"].isin(prepatch_mm)
            sub_sd["us_max_ret"] = sub_sd["dt"].map(max_us).astype(np.float32)
            sub_sd["us_bench_ret"] = sub_sd["us_max_ret"]
            sub_sd["us_n_ge4"] = np.int16(1)
            sub_sd["us_corr_250d_t1"] = np.float32(np.nan)
            sub_sd["us_beta_250d_t1"] = np.float32(np.nan)
            sub_sd["us_group"] = "/".join(kws)
            sub_sd["pool_type"] = "Control0_Leaky_All"
            c0_rows.append(sub_sd)
    if c0_rows:
        df_c0 = pd.concat(c0_rows, ignore_index=True).sort_values(["dt", "c6", "us_max_ret"], ascending=[True, True, False])
        agg_flags = df_c0.groupby(["dt", "c6"], as_index=False).agg({"c0_mingmen": "max", "c0_prepatch_mingmen": "max"})
        df_c0 = df_c0.drop(columns=["c0_mingmen", "c0_prepatch_mingmen"]).drop_duplicates(["dt", "c6"], keep="first").merge(agg_flags, on=["dt", "c6"], how="left")
        track_frames.append(df_c0)
        del df_c0, c0_rows

    # B. PIT Track 1A, 1B, Track 2 & Negative Controls
    for g in PIT_GROUPS:
        gname = g["group"]
        cols_avail = [u for u in g["drivers"] if u in us_aligned_idx.columns]
        max_us = us_aligned_idx[cols_avail].max(axis=1)
        bench_ret = us_aligned_idx[g["bench_etf"]]
        n_ge4 = (us_aligned_idx[cols_avail] >= 0.04).sum(axis=1)
        trig_dts = set(max_us.index[(max_us >= 0.04) & us_aligned_idx["is_fresh_overnight"]].tolist())

        g_sd = sd[(sd["list_age"] >= 250) & (sd["csrc_prefix"].isin(g["csrc_prefixes"])) & (sd["dt"].isin(trig_dts))].copy()
        wl = set(g["track2_pre2020"])
        t2 = sd[(sd["list_age"] >= 250) & (sd["c6"].isin(wl)) & (sd["dt"].isin(trig_dts))].copy()

        g_sd["dt"] = g_sd["dt"].astype(str)
        g_sd["c6"] = g_sd["c6"].astype(str)
        t2["dt"] = t2["dt"].astype(str)
        t2["c6"] = t2["c6"].astype(str)

        sub_c6s = sorted(set(g_sd["c6"].unique()).union(set(t2["c6"].unique())))
        if sub_c6s:
            sub_cis = np.array([c6_to_ci[c] for c in sub_c6s if c in c6_to_ci], dtype=np.int32)
            sub_ci_map = {c6_list[ci]: k for k, ci in enumerate(sub_cis)}
            u_vec = np.where(fresh_mask, us_aligned[g["bench_etf"]].to_numpy(dtype=np.float64), np.nan)
            c_sub, b_sub = compute_rolling_corr_beta_slice(ret_mat[:, sub_cis], u_vec, window=250, min_periods=60)
        else:
            sub_ci_map, c_sub, b_sub = {}, np.empty((0, 0)), np.empty((0, 0))

        if len(g_sd) > 0:
            g_ti = g_sd["dt"].map(dt_to_ti).to_numpy()
            g_ci = g_sd["c6"].map(sub_ci_map).to_numpy()
            g_sd["us_corr_250d_t1"] = c_sub[g_ti, g_ci]
            g_sd["us_beta_250d_t1"] = b_sub[g_ti, g_ci]
            g_sd["us_max_ret"] = g_sd["dt"].map(max_us).astype(np.float32)
            g_sd["us_bench_ret"] = g_sd["dt"].map(bench_ret).astype(np.float32)
            g_sd["us_n_ge4"] = g_sd["dt"].map(n_ge4).astype(np.int16)
            g_sd["us_group"] = gname
            g_sd["c0_mingmen"] = False
            g_sd["c0_prepatch_mingmen"] = False

            t1a = g_sd[(g_sd["amount_yi_t1"] >= 5.0) & (g_sd["us_corr_250d_t1"] >= 0.15) & (g_sd["us_beta_250d_t1"] > 0)].copy()
            if len(t1a) > 0:
                t1a["rank_key"] = t1a["us_corr_250d_t1"] * np.log1p(np.maximum(t1a["amount_yi_t1"], 0.0))
                t1a = t1a.sort_values(["dt", "rank_key", "c6"], ascending=[True, False, True])
                t1a["grp_rank"] = t1a.groupby("dt").cumcount() + 1
                t1a_top5 = t1a[t1a["grp_rank"] <= 5].drop(columns=["rank_key", "grp_rank"]).copy()
                t1a_top5["pool_type"] = "PIT_Track1A_CausalCorr"
                track_frames.append(t1a_top5)

            ir_dict = ir_first_map[gname]
            first_ir_dt = g_sd["c6"].map(ir_dict)
            has_pit_ir = first_ir_dt.notna() & (first_ir_dt < g_sd["dt"])
            t1b = g_sd[has_pit_ir & (g_sd["amount_yi_t1"] >= 2.0) & (g_sd["us_corr_250d_t1"] >= 0.08)].copy()
            if len(t1b) > 0:
                t1b["pool_type"] = "PIT_Track1B_IR_Plus_Corr"
                track_frames.append(t1b)

            nc_lag = g_sd[(g_sd["amount_yi_t1"] < 3.0) & (g_sd["us_corr_250d_t1"].abs() < 0.08)].copy()
            if len(nc_lag) > 0:
                nc_lag = nc_lag.sort_values(["dt", "amount_yi_t1", "c6"]).groupby("dt").head(3).copy()
                nc_lag["pool_type"] = "NegCtrl_SameInd_LowCorrLag"
                track_frames.append(nc_lag)

        if len(t2) > 0:
            t2_ti = t2["dt"].map(dt_to_ti).to_numpy()
            t2_ci = t2["c6"].map(sub_ci_map).to_numpy()
            t2["us_corr_250d_t1"] = c_sub[t2_ti, t2_ci]
            t2["us_beta_250d_t1"] = b_sub[t2_ti, t2_ci]
            t2["us_max_ret"] = t2["dt"].map(max_us).astype(np.float32)
            t2["us_bench_ret"] = t2["dt"].map(bench_ret).astype(np.float32)
            t2["us_n_ge4"] = t2["dt"].map(n_ge4).astype(np.int16)
            t2["us_group"] = gname
            t2["c0_mingmen"] = False
            t2["c0_prepatch_mingmen"] = False
            t2["pool_type"] = "PIT_Track2_Pre2020_Whitelist"
            track_frames.append(t2)

        flat_dts = set(max_us.index[(max_us.abs() < 0.01) & us_aligned_idx["is_fresh_overnight"]].tolist())
        nc_flat = sd[(sd["list_age"] >= 250) & (sd["c6"].isin(wl)) & (sd["dt"].isin(flat_dts))].copy()
        if len(nc_flat) > 0:
            nc_flat["dt"] = nc_flat["dt"].astype(str)
            nc_flat["c6"] = nc_flat["c6"].astype(str)
            nc_flat["us_corr_250d_t1"] = np.float32(np.nan)
            nc_flat["us_beta_250d_t1"] = np.float32(np.nan)
            nc_flat["us_max_ret"] = nc_flat["dt"].map(max_us).astype(np.float32)
            nc_flat["us_bench_ret"] = nc_flat["dt"].map(bench_ret).astype(np.float32)
            nc_flat["us_n_ge4"] = np.int16(0)
            nc_flat["us_group"] = gname
            nc_flat["c0_mingmen"] = False
            nc_flat["c0_prepatch_mingmen"] = False
            nc_flat["pool_type"] = "NegCtrl_Track2_US_Flat"
            track_frames.append(nc_flat)

    del sd, ret_mat
    gc.collect()

    all_cands = pd.concat(track_frames, ignore_index=True)
    del track_frames
    gc.collect()

    all_cands = all_cands.sort_values(["pool_type", "dt", "c6", "us_max_ret"], ascending=[True, True, True, False]).drop_duplicates(["pool_type", "dt", "c6"]).reset_index(drop=True)
    all_cands["name"] = all_cands["c6"].map(name_map).fillna("")

    # Pass 2A: Attach 15 polish feature cols ONLY on unique (dt, c6) pairs (0 excess string allocs!)
    uniq_pairs = set(zip(all_cands["dt"].tolist(), all_cands["c6"].tolist()))
    cand_c6_set = set(all_cands["c6"].unique().tolist())
    cand_dt_set = set(all_cands["dt"].unique().tolist())
    feat_cols = [
        "dt", "c6", "open_pct", "is_20cm", "ret_1d_t1", "prev_streak",
        "pos_20d_t1", "pos_60d_t1", "dd_20d_t1", "ret_5d_t1", "ret_20d_t1",
        "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1", "csrc_ind_id",
        "csrc_ind_ex5_t1", "csrc_ind_rank20_t1", "kpl_in_t1", "kpl_zt1_t1",
    ]
    feat_chunks = []
    for batch in pq.ParquetFile(pq_path).iter_batches(batch_size=300_000, columns=feat_cols):
        b = batch.to_pandas()
        dt_ok = {x for x in b["dt"].cat.categories if str(x) in cand_dt_set} if hasattr(b["dt"], "cat") else None
        c6_ok = {x for x in b["c6"].cat.categories if str(x).zfill(6) in cand_c6_set} if hasattr(b["c6"], "cat") else None
        m = (b["dt"].isin(dt_ok) if dt_ok is not None else b["dt"].astype(str).isin(cand_dt_set)) & (b["c6"].isin(c6_ok) if c6_ok is not None else b["c6"].astype(str).str.zfill(6).isin(cand_c6_set))
        if m.any():
            sub = b[m].copy()
            sub["dt"] = sub["dt"].astype(str)
            sub["c6"] = sub["c6"].astype(str).str.zfill(6)
            pm = [((d, c) in uniq_pairs) for d, c in zip(sub["dt"], sub["c6"])]
            if any(pm):
                f_sub = sub.loc[pm].copy()
                for fc in f_sub.columns[2:]:
                    if f_sub[fc].dtype == np.float64:
                        f_sub[fc] = f_sub[fc].astype(np.float32)
                feat_chunks.append(f_sub)
        del b, m
    pa.default_memory_pool().release_unused()

    feat_df = pd.concat(feat_chunks, ignore_index=True).drop_duplicates(["dt", "c6"])
    all_cands = all_cands.merge(feat_df, on=["dt", "c6"], how="left")
    del feat_chunks, feat_df, uniq_pairs, cand_dt_set
    gc.collect()

    # Pass 2B: Load ONLY 6 lightweight price cols for candidate c6s
    px_chunks = []
    for batch in pq.ParquetFile(pq_path).iter_batches(batch_size=300_000, columns=["dt", "c6", "open", "close", "adj_factor", "is_yizi_dt"]):
        b = batch.to_pandas()
        dt_ok = {x for x in b["dt"].cat.categories if str(x) <= cutoff_date} if hasattr(b["dt"], "cat") else None
        c6_ok = {x for x in b["c6"].cat.categories if str(x).zfill(6) in cand_c6_set} if hasattr(b["c6"], "cat") else None
        m = (b["dt"].isin(dt_ok) if dt_ok is not None else (b["dt"].astype(str) <= cutoff_date)) & (b["c6"].isin(c6_ok) if c6_ok is not None else b["c6"].astype(str).str.zfill(6).isin(cand_c6_set))
        if m.any():
            sub = b[m].copy()
            sub["open"] = sub["open"].astype(np.float32)
            sub["close"] = sub["close"].astype(np.float32)
            sub["adj_factor"] = sub["adj_factor"].astype(np.float32)
            px_chunks.append(sub)
        del b, m
    pa.default_memory_pool().release_unused()

    px_df = pd.concat(px_chunks, ignore_index=True)
    del px_chunks
    gc.collect()
    px_df["dt"] = px_df["dt"].cat.rename_categories(lambda s: str(s)) if hasattr(px_df["dt"], "cat") else px_df["dt"].astype(str)
    px_df["c6"] = px_df["c6"].cat.rename_categories(lambda s: str(s).zfill(6)) if hasattr(px_df["c6"], "cat") else px_df["c6"].astype(str).str.zfill(6)
    px_df = px_df.sort_values(["c6", "dt"]).reset_index(drop=True)

    px_df["adj_o"] = px_df["open"].astype(np.float64) * px_df["adj_factor"].astype(np.float64)
    px_df["adj_c"] = px_df["close"].astype(np.float64) * px_df["adj_factor"].astype(np.float64)
    px_df["ma5_c"] = px_df.groupby("c6")["adj_c"].transform(lambda s: s.rolling(5, min_periods=5).mean())

    price_lookup, dt_pos_cache = {}, {}
    for c6_v, grp in px_df.groupby("c6", sort=False):
        dts_a = grp["dt"].to_numpy()
        price_lookup[c6_v] = (
            dts_a,
            grp["adj_o"].to_numpy(),
            grp["adj_c"].to_numpy(),
            grp["ma5_c"].to_numpy(),
            grp["is_yizi_dt"].to_numpy(dtype=bool),
        )
        dt_pos_cache[c6_v] = {d: i for i, d in enumerate(dts_a)}
    del px_df
    gc.collect()

    n_rows = len(all_cands)
    t1o_dt, t1o_ret = [""] * n_rows, np.full(n_rows, np.nan, dtype=np.float32)
    t1c_dt, t1c_ret = [""] * n_rows, np.full(n_rows, np.nan, dtype=np.float32)
    t2c_dt, t2c_ret = [""] * n_rows, np.full(n_rows, np.nan, dtype=np.float32)
    ma5_dt, ma5_ret = [""] * n_rows, np.full(n_rows, np.nan, dtype=np.float32)

    c6_col = all_cands["c6"].tolist()
    dt_col = all_cands["dt"].tolist()
    valid_px_mask = np.ones(n_rows, dtype=bool)

    for r_idx in range(n_rows):
        c6_v = c6_col[r_idx]
        bdt = dt_col[r_idx]
        dts_a, ao_a, ac_a, ma5_a, dt_yizi_a = price_lookup[c6_v]
        pos = dt_pos_cache[c6_v][bdt]
        entry_px = ao_a[pos]
        if entry_px <= 0 or not np.isfinite(entry_px) or ac_a[pos] <= 0 or not np.isfinite(ac_a[pos]):
            valid_px_mask[r_idx] = False
            continue
        n_bars = len(dts_a)
        if pos + 1 < n_bars:
            p1 = pos + 1
            ex_i = p1
            while ex_i < n_bars - 1 and dt_yizi_a[ex_i]:
                ex_i += 1
            if ex_i == p1 and ao_a[p1] > 0:
                t1o_dt[r_idx] = dts_a[p1]
                t1o_ret[r_idx] = np.float32(ao_a[p1] / entry_px - 1.0)
            elif ac_a[ex_i] > 0:
                t1o_dt[r_idx] = dts_a[ex_i]
                t1o_ret[r_idx] = np.float32(ac_a[ex_i] / entry_px - 1.0)

            ex_i = p1
            while ex_i < n_bars - 1 and dt_yizi_a[ex_i]:
                ex_i += 1
            t1c_dt[r_idx] = dts_a[ex_i]
            t1c_ret[r_idx] = np.float32(ac_a[ex_i] / entry_px - 1.0)

            max_i = min(pos + 10, n_bars - 1)
            ex_m = max_i
            for k_i in range(pos + 1, max_i + 1):
                if not dt_yizi_a[k_i] and np.isfinite(ma5_a[k_i]) and ac_a[k_i] < ma5_a[k_i]:
                    ex_m = k_i
                    break
            ma5_dt[r_idx] = dts_a[ex_m]
            ma5_ret[r_idx] = np.float32(ac_a[ex_m] / entry_px - 1.0)

        if pos + 2 < n_bars:
            ex_i = pos + 2
            while ex_i < n_bars - 1 and dt_yizi_a[ex_i]:
                ex_i += 1
            t2c_dt[r_idx] = dts_a[ex_i]
            t2c_ret[r_idx] = np.float32(ac_a[ex_i] / entry_px - 1.0)

    all_cands["exit_dt_t1o"] = t1o_dt
    all_cands["gret_t1o"] = t1o_ret
    all_cands["exit_dt_t1c"] = t1c_dt
    all_cands["gret_t1c"] = t1c_ret
    all_cands["exit_dt_t2c"] = t2c_dt
    all_cands["gret_t2c"] = t2c_ret
    all_cands["exit_dt_ma5"] = ma5_dt
    all_cands["gret_ma5"] = ma5_ret
    all_cands = all_cands[valid_px_mask].reset_index(drop=True)

    hindsight_audit = audit_product_tree_hindsight()
    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)

    if save_outputs:
        cands_pq = OUT_DIR / "_gem2_pit_candidates_cache.parquet"
        all_cands.to_parquet(cands_pq, index=False)
        audit_path = OUT_DIR / "_gem2_hindsight_audit.json"
        audit_path.write_text(json.dumps({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cutoff_date": cutoff_date,
            "elapsed_sec": round(time.time() - t0, 2),
            "peak_rss_mb": round(peak_rss_mb, 2),
            "d12_yfinance_imported": False,
            "pool_counts": all_cands["pool_type"].value_counts().to_dict(),
            "hindsight_audit_product_tree": hindsight_audit,
        }, ensure_ascii=False, indent=2))
        print(f"DONE step3_build_gem2_pit_map ({cutoff_date}) in {round(time.time()-t0,2)}s | RSS={round(peak_rss_mb,2)}MB")
        print("Pool counts:", all_cands["pool_type"].value_counts().to_dict())

    return {
        "cands": all_cands,
        "price_lookup": price_lookup,
        "dt_pos_cache": dt_pos_cache,
        "hindsight_audit": hindsight_audit,
        "peak_rss_mb": peak_rss_mb,
    }


if __name__ == "__main__":
    build_all_pools("2026-11-25", save_outputs=True)
