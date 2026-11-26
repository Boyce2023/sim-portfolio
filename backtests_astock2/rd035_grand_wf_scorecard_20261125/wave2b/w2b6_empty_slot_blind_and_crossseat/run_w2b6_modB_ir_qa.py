#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-6 Module B:
Research Brainstorm #2 — Institutional IR Survey '0-to-N Silence Mutation'
  x IR Q&A 'Hard Commitment vs Soft Evasion'
  x Xueqiu/Guba Low Attention Divergence (3d / 5d / 10d hold + V20 empty-slot patch).
Strict PIT using pub_datetime_cst < trade_date 09:25:00.
Peak RAM < 2.0 GB, single thread, zero yfinance.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import bisect
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

HARD_RE = re.compile(
    r"(?:满产|扩产|涨价|提价|在手订单|订单饱满|批量供货|批量交付|已量产|开始量产|独供|独家供应|"
    r"新客户突破|通过认证|客户认证|定点通知|产能利用率[^\n。]{0,12}(?:9\d|100|满|较高|饱和)|"
    r"营收占比|占营业收入)"
)
SOFT_RE = re.compile(
    r"(?:尚未形成收入|未形成收入|占比极小|占比较小|尚处于[^\n。]{0,8}阶段|送样测试|正在送样|"
    r"暂未合作|尚无合作|存在不确定性|尚存在不确定|尚未产生|未实现收入|研发阶段|小批量试产)"
)
HDR_SPLIT_RE = re.compile(r"(?:参与单位[^\n]*|活动参与人员[^\n]*|参加人员[^\n]*)(.*?)(?:时间|时\s*间|地点|地\s*点|上市公司接待|交流内容|主要内容|调研内容)", re.S)
ORG_KW_RE = re.compile(r"(?:基金|证券|资管|投资|私募|保险|银行|信托|Capital|Management|Asset|Partners|Research)")


def parse_ir_survey_record(txt: str) -> tuple[int, int, int, int]:
    if not txt:
        return 0, 0, 0, 0
    m = HDR_SPLIT_RE.search(txt[:3500])
    inst_cnt = 0
    if m:
        blk = m.group(1)
        items = [x.strip() for x in re.split(r"[\n、，,;；]+", blk) if len(x.strip()) >= 2]
        # Filter out obvious noise headers
        clean_items = [x for x in items if not x.startswith(("名称", "及人员", "姓名", "方式", "类别")) and len(x) <= 60]
        inst_cnt = len(clean_items)
    if inst_cnt == 0:
        inst_cnt = len(ORG_KW_RE.findall(txt[:3000]))
    hard_cnt = len(HARD_RE.findall(txt))
    soft_cnt = len(SOFT_RE.findall(txt))
    has_num = 1 if re.search(r"\d+(?:\.\d+)?\s*(?:亿元|%|GW|GWh|万吨|台|套)", txt) else 0
    return int(min(inst_cnt, 500)), int(hard_cnt), int(soft_cnt), int(has_num)


def build_pit_xq_attention(cal_dts: list[str], end_cutoff: str = "2026-11-16") -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """
    Build strictly causal Xueqiu post timestamps per code from xueqiu_guba_5y_pit.db.
    Also incorporates guba_posts counts if needed (note xueqiu_posts covers 2021..2026 evenly).
    """
    db_p = f"{cm.DATA_DIR}/xueqiu_guba_5y_pit.db"
    con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
    xq = pd.read_sql_query(
        "SELECT symbol, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2020-06-01' AND created_time_str <= ?",
        con,
        params=(f"{end_cutoff} 09:25:00",),
    )
    con.close()
    xq["c6"] = xq["symbol"].astype(str).str[-6:].str.zfill(6)
    xq["eff_dt"] = np.where(
        xq["created_time_str"].str[11:19] < "09:25:00",
        xq["created_time_str"].str[:10],
        (pd.to_datetime(xq["created_time_str"].str[:10]) + pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d"),
    )
    dt_to_idx = {d: i for i, d in enumerate(cal_dts)}
    # Map eff_dt to nearest trading day >= eff_dt
    cal_arr = np.array(cal_dts)
    pos = np.searchsorted(cal_arr, xq["eff_dt"].to_numpy(), side="left")
    ok = pos < len(cal_arr)
    xq = xq[ok].copy()
    xq["ti"] = pos[ok]
    xq = xq.sort_values(["c6", "ti"])
    out = {}
    for c, grp in xq.groupby("c6", sort=False):
        out[c] = grp["ti"].to_numpy(np.int32)
    return out


def load_ir_events(cal_dts: list[str], end_cutoff: str = "2026-11-16") -> pd.DataFrame:
    con_qa = sqlite3.connect(f"file:{cm.DATA_DIR}/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    df_qa = pd.read_sql_query(
        "SELECT sec_code, pub_datetime_cst, title, full_text FROM ir_qa WHERE fetch_status='DONE' AND substr(pub_datetime_cst,1,10) <= ?",
        con_qa,
        params=(end_cutoff,),
    )
    con_qa.close()

    # Also check ir_survey_fulltext_5y_pit.db (even though small, include any non-empty rows)
    con_ir = sqlite3.connect(f"file:{cm.DATA_DIR}/ir_survey_fulltext_5y_pit.db?mode=ro", uri=True)
    df_ir = pd.read_sql_query(
        "SELECT sec_code, pub_datetime_cst, title, notice_content AS full_text FROM ir_surveys WHERE length(notice_content) > 50 AND substr(pub_datetime_cst,1,10) <= ?",
        con_ir,
        params=(end_cutoff,),
    )
    con_ir.close()

    df = pd.concat([df_qa, df_ir], ignore_index=True)
    df["code"] = df["sec_code"].astype(str).str.zfill(6)
    df["pub_ts"] = df["pub_datetime_cst"].astype(str).str[:19]
    df = df.drop_duplicates(["code", "pub_ts", "title"]).reset_index(drop=True)

    # Effective pre-09:25 trading date
    cal_arr = np.array(cal_dts)
    pub_d = df["pub_ts"].str[:10].to_numpy()
    pub_h = df["pub_ts"].str[11:19].to_numpy()
    pos = np.searchsorted(cal_arr, pub_d, side="left")
    in_b = pos < len(cal_arr)
    on_same = np.zeros(len(df), dtype=bool)
    on_same[in_b] = cal_arr[pos[in_b]] == pub_d[in_b]
    eff_pos = np.where(on_same & (pub_h >= "09:25:00"), pos + 1, pos)
    ok = eff_pos < len(cal_arr)
    df = df[ok].copy()
    df["ti"] = eff_pos[ok].astype(np.int32)
    df["buy_date"] = cal_arr[df["ti"].to_numpy()]
    df = df[df["buy_date"] >= "2021-01-04"].sort_values(["code", "ti", "pub_ts"]).reset_index(drop=True)

    # Parse full texts
    parsed = [parse_ir_survey_record(t) for t in df["full_text"].tolist()]
    arr = np.asarray(parsed, dtype=np.int32)
    df["ir_inst_cnt"] = arr[:, 0]
    df["ir_hard_kw"] = arr[:, 1]
    df["ir_soft_kw"] = arr[:, 2]
    df["ir_has_num"] = arr[:, 3]
    df["ir_hard_net"] = df["ir_hard_kw"].astype(float) - 1.5 * df["ir_soft_kw"].astype(float)
    df["ir_text_len_log"] = np.log1p(df["full_text"].str.len().to_numpy(float))
    df.drop(columns=["full_text", "title", "sec_code"], inplace=True)

    # Collapse same (code, buy_date) taking max inst_cnt / sum keywords
    agg = df.groupby(["code", "buy_date", "ti"], as_index=False).agg(
        ir_inst_cnt=("ir_inst_cnt", "max"),
        ir_hard_kw=("ir_hard_kw", "sum"),
        ir_soft_kw=("ir_soft_kw", "sum"),
        ir_has_num=("ir_has_num", "max"),
        ir_hard_net=("ir_hard_net", "sum"),
        ir_text_len_log=("ir_text_len_log", "max"),
        ir_same_day_recs=("ti", "count"),
    ).sort_values(["code", "ti"]).reset_index(drop=True)

    # Causal rolling 10d surge vs prior 180d silence (strictly <= ti)
    c_arr = agg["code"].to_numpy()
    t_arr = agg["ti"].to_numpy()
    ic_arr = agg["ir_inst_cnt"].to_numpy()
    hn_arr = agg["ir_hard_net"].to_numpy()

    cnt_10d = np.zeros(len(agg), dtype=np.int32)
    cnt_prev180d = np.zeros(len(agg), dtype=np.int32)
    inst_10d = np.zeros(len(agg), dtype=np.int32)
    hnet_10d = np.zeros(len(agg), dtype=np.float32)

    brk = np.flatnonzero(c_arr[1:] != c_arr[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [len(agg)]))
    for s, e in zip(starts, ends):
        ts = t_arr[s:e]
        ics = ic_arr[s:e]
        hns = hn_arr[s:e]
        for k in range(e - s):
            tk = ts[k]
            # strictly [tk-10 .. tk]
            c10 = 0
            isum = 0
            hsum = 0.0
            c180 = 0
            for j in range(k, -1, -1):
                dt_diff = tk - ts[j]
                if dt_diff <= 10:
                    c10 += 1
                    isum += int(ics[j])
                    hsum += float(hns[j])
                elif dt_diff <= 190:
                    c180 += 1
                else:
                    break
            cnt_10d[s + k] = c10
            cnt_prev180d[s + k] = c180
            inst_10d[s + k] = isum
            hnet_10d[s + k] = hsum

    agg["ir_cnt_10d"] = cnt_10d
    agg["ir_cnt_prev180d"] = cnt_prev180d
    agg["ir_inst_10d"] = inst_10d
    agg["ir_hard_net_10d"] = hnet_10d
    agg["ir_is_silence_jump"] = ((cnt_prev180d <= 1) & ((ic_arr >= 10) | (inst_10d >= 15))).astype(np.int8)
    return agg


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(cm.BASE_DIR)
    px_idx = cm.PriceReturnIndex(end_cutoff="2026-11-25")
    cal_all = sorted(v20_ctx["bench"]["trade_date"].tolist())

    ir_df = load_ir_events(cal_all, end_cutoff="2026-11-16")
    print(f"[ModB] Loaded {len(ir_df)} IR stock-day events | silence_jump={int(ir_df['ir_is_silence_jump'].sum())} | RSS={cm.peak_rss_mb()} MB")

    # Attach PIT Xueqiu 30d/180d attention counts directly from xueqiu_guba_5y_pit.db
    xq_map = build_pit_xq_attention(cal_all, end_cutoff="2026-11-16")
    xq_30 = np.zeros(len(ir_df), dtype=np.int32)
    xq_180 = np.zeros(len(ir_df), dtype=np.int32)
    for i, (c, ti) in enumerate(zip(ir_df["code"], ir_df["ti"])):
        arr = xq_map.get(c)
        if arr is not None:
            r = int(np.searchsorted(arr, ti, side="right"))
            l30 = int(np.searchsorted(arr, ti - 29, side="left"))
            l180 = int(np.searchsorted(arr, ti - 179, side="left"))
            xq_30[i] = r - l30
            xq_180[i] = r - l180
    ir_df["xq_posts_30d_pit"] = xq_30
    ir_df["xq_posts_180d_pit"] = xq_180
    ir_df["xq_30v180_ratio"] = np.where(xq_180 >= 3, xq_30 / np.maximum(1.0, xq_180 / 6.0), 0.0)
    del xq_map
    gc.collect()

    # Keep non-overlapping signal per stock within 5 days to prevent consecutive-day spam
    ir_df = ir_df.sort_values(["code", "ti"]).reset_index(drop=True)
    keep = []
    last_c, last_ti = "", -999
    for idx, (c, ti) in enumerate(zip(ir_df["code"], ir_df["ti"])):
        if c != last_c or (ti - last_ti) >= 5:
            keep.append(idx)
            last_c, last_ti = c, ti
    ir_dedup = ir_df.iloc[keep].copy().reset_index(drop=True)
    print(f"[ModB] Deduped (>=5d gap) IR events: {len(ir_dedup)} | silence_jump={int(ir_dedup['ir_is_silence_jump'].sum())}")

    # Lookup forward returns for H = 3, 5, 10 at 09:25 open
    horizons = (3, 5, 10)
    ret_df = px_idx.lookup_forward_returns(ir_dedup, horizons=horizons, buy_at="open", min_amt_yi=0.0)
    ir_extra = [
        "ir_inst_cnt", "ir_hard_kw", "ir_soft_kw", "ir_has_num", "ir_hard_net",
        "ir_text_len_log", "ir_cnt_10d", "ir_cnt_prev180d", "ir_inst_10d",
        "ir_hard_net_10d", "ir_is_silence_jump", "xq_posts_30d_pit",
        "xq_posts_180d_pit", "xq_30v180_ratio",
    ]
    feat_df, fcols = cm.attach_pit_features(ret_df, buy_at="open", extra_cols=ir_extra)
    # Require minimum liquidity T-1 >= 0.5 yi and non-yizi
    feat_df = feat_df[feat_df["can_buy"] & (feat_df["amount_yi_t1"] >= 0.5)].copy().reset_index(drop=True)

    # Define 3 clear candidate pools for Module B:
    #   B1_IR_All: All clean IR surveys (min liquidity 0.5yi)
    #   B2_IR_SilenceJump: 0-to-N silence mutation (prev180d<=1 & inst>=10) + hard_kw>=1 & non-lianban
    #   B3_IR_HardLowHeat: hard_net >= 2 & xq_posts_1y_pct <= 0.45 (or xq_180d<=5) & prev_streak==0
    pools = {
        "B1_IR_AllClean": feat_df,
        "B2_IR_Silence0toN": feat_df[
            (feat_df["ir_cnt_prev180d"] <= 1)
            & ((feat_df["ir_inst_cnt"] >= 10) | (feat_df["ir_inst_10d"] >= 15))
            & (feat_df["prev_streak"] == 0)
        ].copy().reset_index(drop=True),
        "B3_IR_HardLowHeat": feat_df[
            (feat_df["ir_hard_net"] >= 1.5)
            & (feat_df["prev_streak"] == 0)
            & ((feat_df["xq_posts_1y_pct"].fillna(0.5) <= 0.50) | (feat_df["xq_posts_180d_pit"] <= 6))
        ].copy().reset_index(drop=True),
    }

    results = []
    for pname, p_df in pools.items():
        print(f"[ModB] Pool {pname}: {len(p_df)} rows across {p_df['buy_date'].nunique()} days")
        for h in horizons:
            sub = p_df.copy()
            sub["exit_date"] = sub[f"exit_date_h{h}"]
            sub["gross_ret"] = sub[f"gross_ret_h{h}"]
            sub = sub[(sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
            tid = f"ModB_{pname}_H{h}"
            # Note: use rare warmup threshold when pool is small
            min_w = 80 if len(sub) >= 1500 else 35
            min_wr = 40 if len(sub) >= 1500 else 20
            rfreq = "monthly" if len(sub) > 10000 else "daily"
            res = cm.evaluate_and_audit_track(
                track_id=tid,
                module_name="ModuleB_IR_Silence_QA",
                desc=f"{pname} hold {h}d (open, {rfreq})",
                cand_df=sub,
                feature_cols=fcols,
                px_idx=px_idx,
                v20_ctx=v20_ctx,
                buy_at="open",
                thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
                recalc_freq=rfreq,
                min_warmup_trades=min_w,
                min_warmup_trades_rare=min_wr,
                min_warmup_months=18,
                perm_n=1000,
                run_trunc_check=(h == 5),  # run full truncation proof per pool
                trunc_threshold="top20",
            )
            br = res["best_row"]
            t_pass = res["truncation_20241231"]["zero_leakage_pass"] if res["truncation_20241231"] else "NA"
            print(f"  -> {tid:30s} best={br['threshold']:8s} n={br['n_trades_wf']:3d} WR={br['wr_wf_pct']:5.1f}% mean={br['mean_wf_pct']:5.2f}% NAV={br['nav_wf']:6.3f} ex5={br['ex5_wf']:6.3f} Sh={br['sharpe_wf']:5.2f} MDD={br['mdd_wf_pct']:5.1f}% corrV20={br['corr_v20_wf']:6.3f} dNAV_V20={br['patch_delta_nav_ratio']:6.4f} p={br['perm_sd_p']} trunc={t_pass}")
            results.append(res)

    out_pkl = f"{cm.OUT_DIR}/_modB_results.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(results, f)
    print(f"[ModB] Completed in {time.time()-t0:.1f}s | Peak RSS={cm.peak_rss_mb()} MB -> {out_pkl}")


if __name__ == "__main__":
    main()
