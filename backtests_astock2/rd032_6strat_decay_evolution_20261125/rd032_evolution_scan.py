#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Module 2: Scan 40 Objective PIT Candidate Features for Recent Evolution + 4 Anti-Overfit Gates."""
import sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
from rd032_common import STRAT_CN, STRATS, bh_fdr, perm_spearman, sf

# Features already present inside each strategy's active scorecard (tagged so we separate truly NEW candidates)
ALREADY_ACTIVE_MAP = {
    "1to2": {"evo_mcap_yi", "evo_prev_amt_yi", "evo_prev_real_turn", "evo_vol_ratio5", "evo_pos20_d1", "evo_mkt_zt_cnt_d1", "evo_mkt_dt_cnt_d1", "evo_open_pct"},
    "2to3": {"evo_free_mcap_yi", "evo_lock_top10", "evo_prev_real_turn", "evo_pos20_d1", "evo_mkt_max_streak_d1", "evo_open_pct", "evo_zt_seal_ratio_d1"},
    "3to4": {"evo_free_mcap_yi", "evo_lock_top10", "evo_prev_real_turn", "evo_pos20_d1", "evo_mkt_zt_cnt_d1", "evo_mkt_max_streak_d1", "evo_open_pct"},
    "high": {"evo_free_mcap_yi", "evo_lock_top10", "evo_prev_real_turn", "evo_mkt_zt_cnt_d1", "evo_open_pct"},
    "pry": {"evo_free_mcap_yi", "evo_lock_top10", "evo_vol_ratio5", "evo_mkt_dt_cnt_d1", "evo_open_pct"},
    "20cm": {"evo_free_mcap_yi", "evo_prev_amt_yi", "evo_mkt_zt_cnt_d1", "evo_open_pct", "evo_zt_seal_ratio_d1", "evo_hr10d_space"},
}

EVO_LABELS = {
    "evo_mcap_yi": "总市值(亿)", "evo_free_mcap_yi": "真实自由流通市值(亿)", "evo_lock_top10": "前十大锁仓比例(%)",
    "evo_small_vs_large_20d": "20日小盘减大盘风格差", "evo_prev_amt_yi": "信号日成交额(亿)",
    "evo_prev_real_turn": "信号日真实自由换手(%)", "evo_vol_ratio5": "信号日5日量比", "evo_cum_turn_1y": "过去1年累计换手",
    "evo_turn_5_20": "5日均换手除20日均换手", "evo_amp20_d1": "启动前20日振幅", "evo_dd60_d1": "距60日高点回撤",
    "evo_dd1y_high": "距1年高点回撤", "evo_dd3y_high": "距3年高点回撤", "evo_pos20_d1": "20日价格位置分位",
    "evo_ret20_d1": "前20日累计涨幅", "evo_mkt_zt_cnt_d1": "前日全A涨停家数", "evo_mkt_dt_cnt_d1": "前日全A跌停家数",
    "evo_mkt_broken_rate_d1": "前日全A炸板率", "evo_mkt_max_streak_d1": "前日最高连板数", "evo_mkt_b3plus_cnt_d1": "前日3板及以上家数",
    "evo_waves_3y_g15": "近3年大波段次数", "evo_zt_cnt_1y": "近1年涨停次数", "evo_comm_posts_1y_pct": "1年社区讨论分位",
    "evo_xq_posts_1y_pct": "1年雪球讨论分位", "evo_trap_waves_3y": "近3年脉冲坑人次数", "evo_cool_days_zt_log": "距上次涨停冷却天数",
    "evo_mkt_amount_yi_d1": "前日全A成交额(亿)", "evo_mkt_amount_ratio20_d1": "前日全A量能20日比",
    "evo_mkt_pct_above_ma20_d1": "全A站上20日线比例", "evo_mkt_pct_above_ma60_d1": "全A站上60日线比例",
    "evo_mkt_etf_flow_5d": "近5日宽基ETF净申购", "evo_mkt_margin_pct": "融资余额占流通市值比",
    "evo_us_ixic_ret1d": "隔夜纳指日涨跌幅", "evo_us_ixic_ret5d": "隔夜纳指5日涨跌幅", "evo_us_vix_chg1d": "隔夜VIX恐慌变动",
    "evo_open_pct": "买入日竞价开盘涨幅", "evo_open_vs_d1_amp": "竞价涨幅除前日振幅",
    "evo_zt_seal_ratio_d1": "信号日涨停封成比", "evo_lhb_bayes_t2_d1": "龙虎榜席位贝叶斯评分", "evo_hr10d_space": "距10日100%异动空间",
}


def _tercile_spread(x: np.ndarray, y: np.ndarray) -> float | None:
    v = np.isfinite(x) & np.isfinite(y)
    xv, yv = x[v], y[v]
    if len(xv) < 12 or np.unique(xv).size < 2:
        return None
    if np.unique(xv).size <= 3:
        hi, lo = yv[xv == xv.max()], yv[xv == xv.min()]
    else:
        q33, q67 = np.quantile(xv, 0.333), np.quantile(xv, 0.667)
        if q67 > q33:
            hi, lo = yv[xv >= q67], yv[xv <= q33]
        else:
            med = np.median(xv)
            hi, lo = yv[xv > med], yv[xv <= med]
    return sf((hi.mean() - lo.mean()) * 100.0, 2) if (len(hi) >= 3 and len(lo) >= 3) else None


def run_evolution_scan(pools: dict, win: dict, rng: np.random.Generator) -> dict:
    w1y, h_st, q_list = win["w1y_start"], win["h_start"], win["quarters"]
    evo_cols = sorted(EVO_LABELS.keys())
    records = []

    for st in STRATS:
        df = pools[st].copy()
        df["quarter"] = pd.to_datetime(df["buy_date"]).dt.to_period("Q").astype(str)
        m_pre = (df["buy_date"] < w1y).to_numpy()
        m_1y = (df["buy_date"] >= w1y).to_numpy()
        m_h2 = (df["buy_date"] >= h_st).to_numpy()
        y_all = df["net_ret"].to_numpy(float)

        for fc in evo_cols:
            x_all = df[fc].to_numpy(float)
            r_5y, p_5y, pp_5y = perm_spearman(x_all, y_all, rng, n_perm=800)
            r_pre, p_pre, pp_pre = perm_spearman(x_all[m_pre], y_all[m_pre], rng, n_perm=800)
            r_1y, p_1y, pp_1y = perm_spearman(x_all[m_1y], y_all[m_1y], rng, n_perm=2000)
            r_h2, p_h2, pp_h2 = perm_spearman(x_all[m_h2], y_all[m_h2], rng, n_perm=1000)
            sp_1y = _tercile_spread(x_all[m_1y], y_all[m_1y])
            sp_5y = _tercile_spread(x_all, y_all)

            # Gate 3: Quarterly stability across trailing 5 quarters (2025Q4..2026Q4)
            q_rhos = {}
            dir_1y = 1 if (r_1y or 0.0) >= 0 else -1
            same_q, pop_q = 0, 0
            for qk in q_list:
                sub_q = df[df["quarter"] == qk]
                if len(sub_q) >= 4:
                    xq, yq = sub_q[fc].to_numpy(float), sub_q["net_ret"].to_numpy(float)
                    rq, _, _ = perm_spearman(xq, yq, rng, n_perm=200)
                    q_rhos[qk] = {"n": int(len(sub_q)), "rho": rq}
                    if rq is not None:
                        pop_q += 1
                        if (rq >= 0 and dir_1y > 0) or (rq < 0 and dir_1y < 0):
                            same_q += 1

            # Gate 4: Drop top-2 highest return trades in 1Y + Date-clustered sanity check
            sub_1y = df[m_1y].copy()
            r_ex2, pp_ex2, sp_ex2 = None, None, None
            if len(sub_1y) >= 10:
                drop_idx = sub_1y["net_ret"].nlargest(2).index
                s_ex2 = sub_1y.drop(index=drop_idx)
                r_ex2, _, pp_ex2 = perm_spearman(s_ex2[fc].to_numpy(float), s_ex2["net_ret"].to_numpy(float), rng, n_perm=1000)
                sp_ex2 = _tercile_spread(s_ex2[fc].to_numpy(float), s_ex2["net_ret"].to_numpy(float))

            n_days_1y = int(sub_1y["buy_date"].nunique())
            ic_day_1y, p_day_1y = None, None
            if n_days_1y >= 8:
                d_agg = sub_1y.groupby("buy_date")[[fc, "net_ret"]].mean().dropna()
                if len(d_agg) >= 8:
                    ic_day_1y, _, p_day_1y = perm_spearman(d_agg[fc].to_numpy(float), d_agg["net_ret"].to_numpy(float), rng, n_perm=1000)

            is_new = fc not in ALREADY_ACTIVE_MAP[st]
            hist_weak = (r_pre is None) or (abs(r_pre) < 0.08) or ((pp_pre or 1.0) > 0.10)
            recent_strong = (r_1y is not None and abs(r_1y) >= 0.12 and int(m_1y.sum()) >= 15) or (r_h2 is not None and abs(r_h2) >= 0.20 and int(m_h2.sum()) >= 10)
            is_emergent = bool(is_new and hist_weak and recent_strong)

            records.append({
                "strategy": st, "name_cn": STRAT_CN[st], "feature": fc, "label_cn": EVO_LABELS[fc],
                "is_new_candidate": is_new, "is_emergent": is_emergent,
                "n_pre": int(m_pre.sum()), "n_1y": int(m_1y.sum()), "n_days_1y": n_days_1y, "n_h2": int(m_h2.sum()),
                "rho_pre": r_pre, "p_perm_pre": pp_pre, "rho_5y": r_5y, "p_perm_5y": pp_5y, "spread_5y_pp": sp_5y,
                "rho_1y": r_1y, "p_asym_1y": p_1y, "p_perm_1y": pp_1y, "spread_1y_pp": sp_1y,
                "ic_day_1y": ic_day_1y, "p_day_1y": p_day_1y,
                "rho_h2": r_h2, "p_perm_h2": pp_h2,
                "q_pop": pop_q, "q_same_dir": same_q, "quarter_detail": q_rhos,
                "rho_1y_ex_top2": r_ex2, "p_perm_1y_ex_top2": pp_ex2, "spread_1y_ex_top2_pp": sp_ex2,
            })

    # BH-FDR across all 240 tests AND separately across new candidates only
    q_all_1y = bh_fdr([r["p_perm_1y"] for r in records])
    q_all_h2 = bh_fdr([r["p_perm_h2"] for r in records])
    new_idx = [i for i, r in enumerate(records) if r["is_new_candidate"]]
    q_new_1y = bh_fdr([records[i]["p_perm_1y"] for i in new_idx])
    new_q_map = {idx: sf(qv, 5) for idx, qv in zip(new_idx, q_new_1y)}

    for i, r in enumerate(records):
        r["q_fdr_all_1y"] = sf(q_all_1y[i], 5)
        r["q_fdr_all_h2"] = sf(q_all_h2[i], 5)
        r["q_fdr_new_1y"] = new_q_map.get(i)
        g1 = (r["p_perm_1y"] is not None) and (r["p_perm_1y"] < 0.05)
        g2 = (r["q_fdr_all_1y"] is not None) and (r["q_fdr_all_1y"] < 0.10)
        g3 = (r["q_pop"] >= 3) and (r["q_same_dir"] >= max(3, int(np.ceil(0.75 * r["q_pop"]))))
        same_ex2 = (r["rho_1y_ex_top2"] is not None) and (r["rho_1y"] is not None) and ((r["rho_1y_ex_top2"] * r["rho_1y"]) > 0)
        g4 = same_ex2 and ((r["p_perm_1y_ex_top2"] or 1.0) < 0.05)
        r["gates"] = {"g1_perm": g1, "g2_fdr": g2, "g3_qtr": g3, "g4_ex2": g4, "pass_cnt": int(g1) + int(g2) + int(g3) + int(g4)}
        r["survived_all_4"] = bool(r["is_new_candidate"] and g1 and g2 and g3 and g4)

    emergents = [r for r in records if r["is_emergent"]]
    emergents.sort(key=lambda x: (x["gates"]["pass_cnt"], abs(x["rho_1y"] or 0.0)), reverse=True)
    survivors = [r for r in records if r["survived_all_4"]]
    survivors.sort(key=lambda x: abs(x["rho_1y"] or 0.0), reverse=True)
    raw_spikes = [r for r in records if r["is_new_candidate"] and ((r["p_perm_1y"] or 1.0) < 0.05 or (r["p_perm_h2"] or 1.0) < 0.05) and not r["survived_all_4"]]
    raw_spikes.sort(key=lambda x: (x["p_perm_1y"] or 1.0))

    return {
        "total_pairs_tested": len(records),
        "new_candidate_pairs": len(new_idx),
        "emergent_candidates_count": len(emergents),
        "survivors_all_4_count": len(survivors),
        "survivors_all_4": survivors,
        "emergent_top20": emergents[:20],
        "false_positive_mirages_top15": raw_spikes[:15],
        "all_records": records,
    }
