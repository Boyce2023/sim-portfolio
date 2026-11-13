#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三进四「纯软打分卡 vs 硬骨架+近期高权重打分卡 V3 vs 5因子硬门槛基线」终极对照与滚动样本外验证
底座：100% 真实 5 分钟 K 线时序撮合（touch65_1130 + pm1345），严守 D15 四必核与零未来函数
"""
import os
import sys
import json
import pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from core_3to4_5m_engine import BARS_5M_PATH, MATRIX_DIR, evaluate_5m_d15
from bt_3to4_step1_clean_5m_master import build_clean_5m_pool


def sim_dd_ctrl(trades_df: pd.DataFrame, mode: str = "none"):
    if trades_df.empty:
        return 1.0, 0.0
    srt = trades_df.sort_values(["buy_date", "buy_hhmm", "priority_score"], ascending=[True, True, False])
    free_dt, free_hh, nav, pk, mdd, closs = "", 0, 1.0, 1.0, 0.0, 0
    for r in srt.itertuples(index=False):
        bd, bh = r.buy_date, int(r.buy_hhmm)
        if not ((free_dt == "") or (bd > free_dt) or (bd == free_dt and bh > free_hh)):
            continue
        free_dt, free_hh = r.exit_date, int(r.exit_hhmm)
        ret = float(r.net_ret)
        w = 0.5 if (mode == "half_cb" and closs >= 2) else 1.0
        nav *= (1.0 + ret * w)
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
        closs = (closs + 1) if ret < -0.02 else (0 if ret > 0 else closs)
    return float(nav), float(mdd)


def load_all_5m():
    df = pd.read_parquet(f"{CUR_DIR}/data_5y/cand_3to4_enriched54.parquet")
    with open(f"{MATRIX_DIR}/code_bars_5y.pkl", "rb") as f:
        code_bars = pickle.load(f)["code_bars"]
    df_5m = pd.read_parquet(BARS_5M_PATH)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, dt_s): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, dt_s), g in df_5m.groupby(["c6", "date"], sort=False)
    }
    with open(f"{MATRIX_DIR}/../index_klines_5y_cache.json", "r") as f:
        csi_map = json.load(f)["sh000300"]
    dts_s = sorted(csi_map.keys())
    d_pos = {d: i for i, d in enumerate(dts_s)}
    df["csi_1d_prev"] = [
        (csi_map[r.sig_date] / csi_map[dts_s[d_pos[r.sig_date] - 1]] - 1.0) if r.sig_date in d_pos and d_pos[r.sig_date] >= 1 else 0.0
        for r in df.itertuples(index=False)
    ]
    df["prio_3to4"] = df["open_pct"] * 1000.0 + df["lock_top10"] * 0.5 + df["csrc_zt_cnt"] * 2.0
    pool = build_clean_5m_pool(df, code_bars, bars_5m_map, "touch65_1130", 1345, 1.050, prio_col="prio_3to4")
    df["has_trig"] = [p is not None for p in pool]
    df["net_ret_5m"] = [p["net_ret"] if p is not None else np.nan for p in pool]
    return df, pool


def build_scores(df: pd.DataFrame):
    # 物理生死门硬骨架：主板10cm非ST + 非前日一字 + 可买 + 无真减持立案个股监管雷 + 三板盘中开板洗盘 + 筹码承接底线 + 换手[8.5,31] + 竞价[3.0%,9.2%]
    skel = (
        df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"]
        & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
        & (df["open_board_count"] >= 1)
        & ((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0))
        & df["prev_to"].between(8.5, 31.0) & df["open_pct"].between(0.030, 0.092)
    )
    # 近期市场(2024-2026)高权重加减分模块（基准 70 分，满分 106 分，清晰百人可读）
    pts = np.full(len(df), 70.0, dtype=float)
    pts += np.where(df["px_d3"] <= 20.0, 8.0, np.where(df["px_d3"] > 32.0, -5.0, 0.0))          # 近期核心：20元内低中价股 (+9.8%超额)
    pts += np.where(df["is_top1_3b_open"], 8.0, 0.0)                                             # 同日三板竞价头名卡位 (+6.7%超额)
    pts += np.where(df["mkt_max_board_prev"] <= 4, 8.0, 0.0)                                     # 无高标压制空间破局期 (+19%胜率/+5.1%超额)
    pts += np.where(df["mkt_zt_prev"] >= 95, -10.0, np.where(df["mkt_zt_prev"].between(35, 85), 5.0, 0.0))  # 防百股涨停次日量化兑现
    pts += np.where(df["has_ex_reg"], -12.0, 0.0)                                                # 防交易所重点监控密集期 (-21%胜率)
    pts += np.where(df["lhb_lh_cnt"] == 0, 4.0, np.where(df["lhb_lh_cnt"] >= 3, -5.0, 0.0))      # 零拉萨散户席位纯度 (+9.2%近期胜率)
    pts += np.where((df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0), 4.0, 0.0)       # 同题材首板小弟换手高开真助攻
    pts += np.where(df["plate_fb_yz_cnt"] >= 1, -7.0, 0.0)                                       # 防同题材低位首板顶一字高潮兑现陷阱
    pts += np.where(df["plate_peers_open_avg"] < -0.015, -10.0, 0.0)                             # 防同题材队友集体核按钮
    pts += np.where(df["prev_3b_dt_cnt"] == 0, 3.0, np.where(df["prev_3b_dt_cnt"] >= 2, -4.0, 0.0))
    pts += np.where((df["csi_1d_prev"] <= -0.020) | (df["csi_5d_prev"] <= -0.030), -8.0, 0.0)  # 防前日指数急杀或5日破位
    pts += np.where(df["prev_to"].between(9.5, 28.0), 3.0, 0.0)

    sc_hybrid = np.where(skel, pts, -999.0)

    # 对照组：无硬骨架纯软打分卡（把三板洗盘、锁仓、换手也改成软加减分）
    soft = pts - 10.0
    soft += np.where(df["open_board_count"] >= 1, 10.0, -14.0)
    soft += np.where((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0), 8.0, -10.0)
    soft += np.where(df["prev_to"].between(9.0, 30.0), 6.0, -8.0)
    veto_min = (~df["is_10cm_non_st"]) | df["prev_is_yizi"] | (~df["buyable_open"]) | df["has_tox_notice"] | df["has_stock_reg"] | (~df["open_pct"].between(0.025, 0.092))
    sc_soft = np.where(veto_min, -999.0, soft)
    return skel, sc_hybrid, sc_soft


def rolling_exp_wf_hybrid(df: pd.DataFrame, skel: pd.Series, pool: list, half_life_days: float = 450.0, keep_frac: float = 0.72):
    """严格零未来函数：在硬骨架底座上，每月初仅用 exit_date < 当月1日 的历史样本按15个月半衰期学各因子分值"""
    f_cols = [
        df["px_d3"] <= 20.0, df["is_top1_3b_open"].astype(bool), df["mkt_max_board_prev"] <= 4,
        df["mkt_zt_prev"] >= 95, df["mkt_zt_prev"].between(35, 85), df["has_ex_reg"].astype(bool),
        df["lhb_lh_cnt"] == 0, (df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0),
        df["plate_fb_yz_cnt"] >= 1, df["plate_peers_open_avg"] < -0.015, df["prev_3b_dt_cnt"] == 0,
    ]
    F = np.column_stack([c.to_numpy(dtype=float) for c in f_cols])
    vb = skel.values & df["has_trig"].values
    ex_d = np.array([pool[i]["exit_date"] if pool[i] is not None else "9999-99-99" for i in range(len(df))])
    bd_t = pd.to_datetime(df["buy_date"]).values.astype("datetime64[D]").astype(float)
    rets = df["net_ret_5m"].to_numpy(dtype=float)
    wf_pass, wf_sc = np.zeros(len(df), dtype=bool), np.full(len(df), -999.0)
    for ym in sorted(df.loc[df["buy_date"] >= "2024-01-01", "buy_date"].str[:7].unique()):
        ms = f"{ym}-01"
        tr = np.where(vb & (ex_d < ms))[0]
        te = np.where(vb & (df["buy_date"].str[:7].values == ym))[0]
        if len(tr) < 40 or len(te) == 0:
            continue
        w = np.exp(-np.log(2.0) * np.maximum(0.0, float(np.datetime64(ms, "D").astype(float)) - bd_t[tr]) / half_life_days)
        y = rets[tr]
        pts = np.zeros(F.shape[1])
        for j in range(F.shape[1]):
            on = F[tr, j] == 1.0
            if on.sum() >= 5 and (~on).sum() >= 5:
                d_wr = np.average((y[on] > 0).astype(float), weights=w[on]) - np.average((y[~on] > 0).astype(float), weights=w[~on])
                d_rt = np.average(y[on], weights=w[on]) - np.average(y[~on], weights=w[~on])
                pts[j] = np.clip(d_wr * 50.0 + d_rt * 120.0, -12.0, 12.0)
        sc_tr = 70.0 + F[tr] @ pts
        thr = float(np.quantile(sc_tr, 1.0 - keep_frac))
        sc_te = 70.0 + F[te] @ pts
        wf_sc[te], wf_pass[te] = sc_te, (sc_te >= thr)
    return wf_pass, wf_sc


def main():
    df, pool = load_all_5m()
    skel, sc_hyb, sc_soft = build_scores(df)
    wf_p75, wf_s75 = rolling_exp_wf_hybrid(df, skel, pool, 450.0, 0.75)
    wf_p60, wf_s60 = rolling_exp_wf_hybrid(df, skel, pool, 450.0, 0.60)
    m_baseA = df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"] & (df["open_board_count"] >= 1) & df["prev_to"].between(9.0, 30.0) & df["open_pct"].between(0.030, 0.092) & ((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0))

    def run_one(name, msk, sc_arr=None):
        arr_m = np.asarray(msk, dtype=bool)
        recs = []
        for i in np.where(arr_m)[0]:
            if pool[i] is not None:
                d = dict(pool[i])
                if sc_arr is not None:
                    d["priority_score"] = float(sc_arr[i]) * 10.0 + float(df["prio_3to4"].iloc[i]) * 0.1
                recs.append(d)
        tdf = pd.DataFrame(recs)
        ev = evaluate_5m_d15(tdf)
        hnav, hmdd = sim_dd_ctrl(tdf, "half_cb")
        r3_hnav, r3_hmdd = sim_dd_ctrl(tdf[tdf["buy_date"] >= "2024-01-02"] if not tdf.empty else tdf, "half_cb")
        s5, r3, ex4, j26, ann = ev["full_5y"], ev["recent_3y"], ev["ex2025_4y"], ev["since_jul2026"], ev["annual"]
        yrs = " ".join(f"{y[-2:]}:{ann[y]['single_nav']:.2f}x({ann[y]['single_n']}b,{ann[y]['wr']:.0f}%)" for y in ["2022", "2023", "2024", "2025", "2026"])
        print(
            f"{name:27s} | 5Y:{s5['single_n']:3d}b WR={s5['wr']:4.1f}% PO={s5['payoff']:4.2f} NAV={s5['single_nav']:6.2f}x MDD={s5['single_mdd_pct']:4.1f}% "
            f"[半CB:{hnav:6.2f}x/{hmdd*100:4.1f}% 双半:{s5['half2_nav']:5.2f}x/{s5['half2_mdd_pct']:4.1f}% Eq:{s5['eq_nav']:6.2f}x 去5:{s5['trimmed5_nav']:4.2f}x] | "
            f"24-26:{r3['single_n']:2d}b WR={r3['wr']:4.1f}% {r3['single_nav']:6.2f}x(MDD{r3['single_mdd_pct']:4.1f}%,半CB:{r3_hnav:5.2f}x/{r3_hmdd*100:4.1f}%) | {yrs} | 26.7+:{j26['single_n']}b({j26['wr']:.0f}%,{j26['single_nav']:.2f}x)"
        )
        return ev, tdf, {"hcb_5y": [round(hnav, 3), round(hmdd * 100, 2)], "hcb_r3": [round(r3_hnav, 3), round(r3_hmdd * 100, 2)]}

    res = {}
    res["baseA"], _, _ = run_one("基线A_5硬门槛纯量化", m_baseA)
    for th in [76, 78, 80, 82, 84, 86, 88, 90, 94, 98, 100]:
        ev, tdf, dd = run_one(f"硬骨架+打分V3.1>={th}", sc_hyb >= th, sc_hyb)
        res[f"hyb_{th}"] = {"ev": ev, "dd": dd}
        if th in (78, 90, 98):
            tdf.to_csv(f"{CUR_DIR}/ledger_3to4_hyb_v31_thr{th}.csv", index=False)
    for th in [94, 98, 102]:
        ev, _, dd = run_one(f"对照_纯软打分>={th}", sc_soft >= th, sc_soft)
        res[f"soft_{th}"] = {"ev": ev, "dd": dd}
    res["wf_hyb_top75"], _, _ = run_one("纯样本外WF_骨架+近期Top75%", wf_p75, wf_s75)
    res["wf_hyb_top60"], _, _ = run_one("纯样本外WF_骨架+近期Top60%", wf_p60, wf_s60)

    with open(f"{CUR_DIR}/scorecard_3to4_v3_final.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
