#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Track B2 20cm Stock-Level PIT Feature Assembly: Builds >=60 strictly PIT atomic factors on all 809 V1.1 signals."""
import bisect, sqlite3, sys
from collections import defaultdict
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
RD23_DIR = f"{SIM}/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
sys.path.insert(0, V11_DIR)
from v11_core import V11_EXIT_CFG, compute_scorecard_v11, sim_v11_exit


def attach_lhb_youzi_lasa(df: pd.DataFrame) -> pd.DataFrame:
    lhb = pd.read_parquet(f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet")
    bayes = pd.read_parquet(f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/bayes_seat_scores_d1_5y.parquet")
    c6_set = set(df["c6"].unique())
    lhb = lhb[lhb["stock_code"].isin(c6_set)].copy()
    depts = lhb[lhb["dept_code"] != "0"][["dept_code", "dept_name"]].drop_duplicates()
    lasa_c = set(depts[depts["dept_name"].str.contains("拉萨", na=False) & (~depts["dept_name"].str.contains("东亚", na=False))]["dept_code"])
    good_yz = {"10430845", "10102873", "10046704", "10023415", "10026767", "10142874", "10122927", "10045035", "10025390", "10147201", "10318896", "10434470", "10634757", "10000100571", "10000399618", "10110478"}
    surf_c = {"10063083", "10026729", "10477736", "10023559", "10026897", "10342919"} | set(depts[depts["dept_name"].str.contains("佛山绿景路|光大证券.*佛山", regex=True, na=False)]["dept_code"])
    lhb_m = {}
    for (dt, sc, is3), grp in lhb.sort_values(["date", "stock_code", "is_three"]).groupby(["date", "stock_code", "is_three"], sort=False):
        if is3 == 1 and (dt, sc) in lhb_m:
            continue
        br, sr = grp[grp["side"] == "B"], grp[grp["side"] == "S"]
        tot_b = max(1.0, float(br["BUY"].sum()))
        tot_s = max(1.0, float(sr["SELL"].sum()))
        b_lh = br[br["dept_code"].isin(lasa_c)]
        s_lh = sr[sr["dept_code"].isin(lasa_c)]
        s_yz = sr[sr["dept_code"].isin(good_yz)]
        b_yz = br[br["dept_code"].isin(good_yz)]
        lhb_m[(dt, sc)] = (
            float(b_lh["BUY"].sum()) / tot_b,
            float(-s_lh["NET"].sum()) / 1e4,   # sell_lasa_net_sell (万元, positive = net selling)
            float(s_lh["SELL"].sum()) / tot_s,   # sell_lasa_share
            int(len(s_lh)),
            float(b_yz["NET"].sum() - s_yz["SELL"].sum()) / 1e4,
            float(s_yz["SELL"].sum()) / 1e4,
            int(any(c in surf_c for c in br["dept_code"])),
        )
    bayes = bayes[bayes["stock_code"].isin(c6_set)]
    b_m = {}
    for (dt, sc), g in bayes.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(g["NET"].to_numpy(float), 1.0)
        b_m[(dt, sc)] = (float(np.sum(w * g["b_c"].to_numpy()) / np.sum(w)), float(np.sum(w * g["b_t2"].to_numpy()) / np.sum(w)))
    cols = ["lhb_buy_lasa_share", "lhb_sell_lasa_net_sell", "lhb_sell_lasa_share", "lhb_sell_lasa_cnt", "lhb_famous_yz_net", "lhb_yz_sell_dump", "lhb_surf_flag"]
    vals = [lhb_m.get((r.sig_date, r.c6), (0.0, 0.0, 0.0, 0, 0.0, 0.0, 0)) for r in df.itertuples(index=False)]
    df_out = pd.DataFrame(vals, columns=cols, index=df.index)
    bv = [b_m.get((r.sig_date, r.c6), (0.0, 0.0)) for r in df.itertuples(index=False)]
    df_out["yz_bayes_c"] = [x[0] for x in bv]
    df_out["yz_bayes_t2"] = [x[1] for x in bv]
    return df_out


def attach_cninfo_and_stock_hist(df: pd.DataFrame, sub_df: pd.DataFrame) -> pd.DataFrame:
    c6_set = set(df["c6"].unique())
    ph = ",".join("?" for _ in c6_set)
    ir_m, pos_m, reg_m = defaultdict(list), defaultdict(list), defaultdict(list)
    con_ir = sqlite3.connect(f"file:{SIM}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    for sc, ts in con_ir.execute(f"SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code IN ({ph})", list(c6_set)):
        ir_m[str(sc).zfill(6)].append(str(ts)[:19])
    con_ir.close()
    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    q_n = f"""SELECT sec_code, pub_datetime_cst, title FROM notices WHERE sec_code IN ({ph})
              AND (title LIKE '%预增%' OR title LIKE '%预盈%' OR title LIKE '%扭亏%' OR title LIKE '%重大合同%' OR title LIKE '%中标%'
                   OR title LIKE '%回购%' OR title LIKE '%增持%' OR title LIKE '%战略合作%' OR title LIKE '%问询%' OR title LIKE '%关注函%'
                   OR title LIKE '%监管函%' OR title LIKE '%警示函%' OR title LIKE '%减持%' OR title LIKE '%预亏%' OR title LIKE '%亏损%')"""
    pos_kw = ("预增", "预盈", "扭亏", "重大合同", "中标", "回购", "增持", "战略合作")
    neg_kw = ("问询", "关注函", "监管函", "警示函", "减持", "预亏", "亏损")
    for sc, ts, ti in con_n.execute(q_n, list(c6_set)):
        t_s, ts_s, c6 = str(ti or ""), str(ts)[:19], str(sc).zfill(6)
        if any(k in t_s for k in pos_kw) and not any(k in t_s for k in ("减持", "预亏", "亏损", "终止")):
            pos_m[c6].append(ts_s)
        if any(k in t_s for k in neg_kw) and ("回复" not in t_s) and ("回函" not in t_s):
            reg_m[c6].append(ts_s)
    con_n.close()
    for m in (ir_m, pos_m, reg_m):
        for k in m: m[k].sort()

    # Down-streak immediately prior to T0 (from T0-1 backwards)
    hist_lu = {}
    for c6, g in sub_df.groupby("c6"):
        dts = g["dt"].tolist()
        rets = g["ret"].to_numpy(float)
        hist_lu[c6] = (dts, rets, {d: i for i, d in enumerate(dts)})

    rows = []
    for r in df.itertuples(index=False):
        bdt = pd.Timestamp(r.buy_date)
        cut_end = f"{r.buy_date} 09:00:00"
        cut30 = f"{(bdt - pd.Timedelta(days=30)).strftime('%Y-%m-%d')} 00:00:00"
        cut45 = f"{(bdt - pd.Timedelta(days=45)).strftime('%Y-%m-%d')} 00:00:00"
        cut90 = f"{(bdt - pd.Timedelta(days=90)).strftime('%Y-%m-%d')} 00:00:00"
        c_cnt = lambda arr, lo: bisect.bisect_right(arr, cut_end) - bisect.bisect_left(arr, lo)
        ir30 = c_cnt(ir_m.get(r.c6, []), cut30)
        ir90 = c_cnt(ir_m.get(r.c6, []), cut90)
        pos45 = c_cnt(pos_m.get(r.c6, []), cut45)
        reg30 = c_cnt(reg_m.get(r.c6, []), cut30)
        ds_pre = 0
        h = hist_lu.get(r.c6)
        if h and r.sig_date in h[2]:
            j = h[2][r.sig_date] - 1
            while j >= 0 and h[1][j] < 0:
                ds_pre += 1; j -= 1
        rows.append((ir30, int(ir90 == 0), pos45, reg30, ds_pre))
    return pd.DataFrame(rows, columns=["cninfo_ir_30d", "cninfo_ir_unpop90", "cninfo_pos_45d", "cninfo_reg_neg_30d", "pry_down_streak_pre"], index=df.index)


def build_20cm_enriched_panel(mkt_buy_pit: pd.DataFrame, sub_df: pd.DataFrame):
    pool = pd.read_parquet(f"{RD23_DIR}/rd023_pool_enriched.parquet")
    v11 = pd.read_csv(f"{V11_DIR}/final_v11_all_scored_signals.csv")
    v11["c6"] = v11["c6"].astype(str).str.zfill(6)
    sc, fm = compute_scorecard_v11(pool)
    pool["score"] = sc.values
    for c in fm.columns:
        pool[f"V11_{c}"] = fm[c].values
    tr = sim_v11_exit(pool, V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    keep_cols = ["dt", "c6", "real_free_mcap", "rfm_pct_all20", "dist_3d30", "dist_10d100", "dist_30d200", "zt_cnt_60d", "zt_seal_ratio", "zt_seal_amt", "zt_obc", "zt_mins", "lhb_inst_net", "lhb_lh_share", "kpl_10_20_zt", "kpl_peers_f1o_ex", "prev_bias20", "prev_pos60", "vol_ratio5", "dt_cnt_10d", "lock_top10", "box20_prev", "real_to", "f1_o_pct", "f1_weekday"] + [f"V11_{c}" for c in fm.columns]
    merged = tr.assign(c6=tr["c6"].astype(str).str.zfill(6)).merge(pool[keep_cols], left_on=["sig_date", "c6"], right_on=["dt", "c6"], how="inner")
    chk = merged[["sig_date", "c6", "score", "net_ret"]].merge(v11[["sig_date", "c6", "score", "net_ret"]], on=["sig_date", "c6"], suffixes=("_t", "_v"))
    assert len(chk) == len(v11) == 809, f"Expected 809 rows, got {len(chk)}"
    assert float(np.max(np.abs(chk["score_t"] - chk["score_v"]))) == 0.0
    assert float(np.max(np.abs(chk["net_ret_t"] - chk["net_ret_v"]))) < 1e-12

    lhb_feat = attach_lhb_youzi_lasa(merged)
    cn_feat = attach_cninfo_and_stock_hist(merged, sub_df)
    mac_feat = mkt_buy_pit.reindex(merged["buy_date"]).reset_index(drop=True)
    df = pd.concat([merged.reset_index(drop=True), lhb_feat.reset_index(drop=True), cn_feat.reset_index(drop=True), mac_feat], axis=1)
    df["abn_tight_headroom"] = np.minimum(df["dist_10d100"].fillna(1.0), df["dist_30d200"].fillna(2.0))
    df["micro_seal_to_rfm"] = df["zt_seal_amt"].fillna(0.0) / (df["real_free_mcap"].clip(lower=1.0) * 1e8)
    df["us_ixic_drop15_panic_open"] = ((df["us_ixic_ret"] <= -0.015) & (df["f1_o_pct"] <= -0.050)).astype(int)
    df["us_ixic_drop10_panic_open"] = ((df["us_ixic_ret"] <= -0.010) & (df["f1_o_pct"] <= -0.050)).astype(int)
    df["us_ixic_drop15_mkt_lowopen"] = ((df["us_ixic_ret"] <= -0.015) & (df["mkt20_0925_gap"] <= -0.005)).astype(int)
    df["us_ixic_drop15_flag"] = (df["us_ixic_ret"] <= -0.015).astype(int)
    df["score_base_v11"] = df["score"].astype(float)
    return df, list(fm.columns)
