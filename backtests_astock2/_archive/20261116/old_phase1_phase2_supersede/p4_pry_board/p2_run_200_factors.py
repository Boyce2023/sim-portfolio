#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p2_run_200_factors.py: Run 200+ factor slice backtests and generate p2_dragon_pry_factor_catalog.csv.
"""
import os, sys, time, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p4_pry_board"
FEE_RATE = 0.0020
CSI300_5Y = -0.1784

print("[+] Loading enriched triggers...")
t0 = time.time()
df = pd.read_parquet(f"{OUT_DIR}/p2_master_enriched_triggers.parquet")
print(f"Loaded {len(df)} rows in {time.time()-t0:.2f}s")

# Helper for D15 evaluation
def eval_slice(sub_df, ret_col, exdt_col, base_mean=0.0):
    n_raw = len(sub_df)
    if n_raw == 0:
        return {
            "n_raw": 0, "wr_raw": 0.0, "payoff_raw": 0.0, "avg_ret": 0.0, "delta_vs_base": 0.0,
            "dt_reseal_r": 0.0, "zt_seal_r": 0.0, "is_wr": 0.0, "oos_wr": 0.0, "dual_same_sign": False,
            "ss_n": 0, "ss_wr": 0.0, "ss_payoff": 0.0, "ss_nav": 1.0, "ss_mdd": 0.0, "ss_ex_top3_nav": 1.0,
            "ss_excess_5y": 0.0, "eq_nav": 1.0
        }
    rets = sub_df[ret_col].values
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / n_raw)
    po = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (9.99 if len(wins) > 0 else 0.0)
    avg_r = float(rets.mean())
    delta = avg_r - base_mean
    
    dt_reseal_r = float(sub_df["is_dt0"].mean())
    zt_seal_r = float(sub_df["is_zt0"].mean())
    
    is_mask = sub_df["buy_date"] < "2025-01-01"
    oos_mask = sub_df["buy_date"] >= "2025-01-01"
    is_r = rets[is_mask]
    oos_r = rets[oos_mask]
    is_wr = float((is_r > 0).mean()) if len(is_r) > 0 else 0.0
    oos_wr = float((oos_r > 0).mean()) if len(oos_r) > 0 else 0.0
    is_avg = float(is_r.mean()) if len(is_r) > 0 else 0.0
    oos_avg = float(oos_r.mean()) if len(oos_r) > 0 else 0.0
    dual_ok = bool(len(is_r) >= 3 and len(oos_r) >= 3 and (is_avg - base_mean) * (oos_avg - base_mean) > 0)
    
    # Single slot simulation
    s_ord = sub_df.sort_values(["buy_date", "o_pct"], ascending=[True, False])
    free_dt = ""
    ss_trades = []
    ss_nav, ss_pk, ss_mdd = 1.0, 1.0, 0.0
    for r in s_ord.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        if free_dt == "" or bd > free_dt:
            rt = float(getattr(r, ret_col))
            ed = str(getattr(r, exdt_col))[:10]
            ss_trades.append(rt)
            free_dt = max(bd, ed)
            ss_nav *= (1.0 + rt)
            ss_pk = max(ss_pk, ss_nav)
            ss_mdd = max(ss_mdd, (ss_pk - ss_nav) / ss_pk)
            
    ss_rets = np.array(ss_trades, dtype=float)
    ss_w = ss_rets[ss_rets > 0]
    ss_l = ss_rets[ss_rets <= 0]
    ss_wr = float(len(ss_w) / len(ss_rets)) if len(ss_rets) > 0 else 0.0
    ss_po = float(ss_w.mean() / abs(ss_l.mean())) if (len(ss_w) > 0 and len(ss_l) > 0 and ss_l.mean() < 0) else 0.0
    
    if len(ss_rets) > 3:
        ex_top3 = float(np.prod(1.0 + np.sort(ss_rets)[:-3]))
    else:
        ex_top3 = ss_nav
        
    eq_daily = sub_df.groupby("buy_date")[ret_col].mean().sort_index()
    eq_nav = float(np.prod(1.0 + eq_daily.values))
    
    return {
        "n_raw": n_raw,
        "wr_raw": round(wr * 100, 1),
        "payoff_raw": round(po, 2),
        "avg_ret": round(avg_r * 100, 2),
        "delta_vs_base": round(delta * 100, 2),
        "dt_reseal_r": round(dt_reseal_r * 100, 1),
        "zt_seal_r": round(zt_seal_r * 100, 1),
        "is_wr": round(is_wr * 100, 1),
        "oos_wr": round(oos_wr * 100, 1),
        "dual_same_sign": dual_ok,
        "ss_n": len(ss_trades),
        "ss_wr": round(ss_wr * 100, 1),
        "ss_payoff": round(ss_po, 2),
        "ss_nav": round(ss_nav, 3),
        "ss_mdd": round(ss_mdd * 100, 1),
        "ss_ex_top3_nav": round(ex_top3, 3),
        "ss_excess_5y": round((ss_nav - 1.0 - CSI300_5Y) * 100, 1),
        "eq_nav": round(eq_nav, 3)
    }

# Define clean factor slices: (category, factor_name, eval_expr, desc)
FACTORS = [
    # 1. 身位垄断 (Rank / Echelon Monopoly)
    ("Rank_Echelon", "is_max_board_prev", "is_max_board_prev == True", "昨日全场最高连板"),
    ("Rank_Echelon", "is_sole_max_board_prev", "is_sole_max_board_prev == True", "昨日全场唯一最高连板"),
    ("Rank_Echelon", "is_mid_nuke", "is_mid_nuke == True", "中位跟风股核按钮"),
    ("Rank_Echelon", "prior_mb_gap_0", "prior_mb_gap == 0", "身位差为0"),
    ("Rank_Echelon", "prior_mb_gap_ge2", "prior_mb_gap >= 2", "落后最高身位>=2板的跟风"),
    ("Rank_Echelon", "prev_streak_ge4", "prev_streak >= 4", "超高标连板>=4"),
    ("Rank_Echelon", "prev_streak_ge5", "prev_streak >= 5", "5板以上大妖龙"),
    ("Rank_Echelon", "dom_gap_ge20", "dom_gap >= 20.0", "主线题材断层领先>=20分"),
    ("Rank_Echelon", "is_dominant_day", "is_dominant_day == True", "全天主线一枝独秀日"),
    ("Rank_Echelon", "is_melee_day", "is_melee_day == True", "多题材混战日"),

    # 2. 换手基因 vs 一字A杀
    ("Turnover_Gene", "prev_is_yizi_false", "prev_is_yizi == False", "前一日换手实体板"),
    ("Turnover_Gene", "prev_is_yizi_true", "prev_is_yizi == True", "前一日缩量一字板A杀"),
    ("Turnover_Gene", "prev_to_ge15", "prev_to >= 15.0", "昨日换手率>=15%"),
    ("Turnover_Gene", "prev_to_ge25", "prev_to >= 25.0", "昨日大换手爆量>=25%"),
    ("Turnover_Gene", "prev_to_lt10", "prev_to < 10.0", "昨日低换手<10%"),
    ("Turnover_Gene", "prev_real_to_ge30", "prev_real_to >= 30.0", "实际自由流通换手>=30%"),
    ("Turnover_Gene", "pos20_ge08", "pos20 >= 0.80", "20日高位筹码聚集"),
    ("Turnover_Gene", "pos20_lt04", "pos20 < 0.40", "20日低位"),
    ("Turnover_Gene", "dd20_ge085", "dd20 >= 0.85", "近期回撤<15%"),
    ("Turnover_Gene", "dd60_ge075", "dd60 >= 0.75", "60日高位抗跌"),
    ("Turnover_Gene", "ret_pre10_ge05", "ret_pre10 >= 0.50", "前10日涨幅>=50%"),
    ("Turnover_Gene", "clean_brk60_true", "clean_brk60 == True", "前期60日有效突破"),

    # 3. 板块活口助攻
    ("Theme_Support", "p_sz_ge2", "p_sz >= 2", "同题材昨日涨停>=2家"),
    ("Theme_Support", "p_sz_ge4", "p_sz >= 4", "同题材昨日涨停>=4家，板块有梯队"),
    ("Theme_Support", "p_sz_eq1", "p_sz == 1", "孤儿标的，无队友助攻"),
    ("Theme_Support", "s_prior_ge105", "s_prior >= 105.0", "题材先验强势"),
    ("Theme_Support", "p_elo_ge105", "p_elo >= 105.0", "板块Elo积分强势"),
    ("Theme_Support", "plate_peers_open_avg_pos", "plate_peers_open_avg > 0.0", "今日同板块队友竞价高开"),
    ("Theme_Support", "plate_peers_open_avg_neg2", "plate_peers_open_avg <= -0.02", "今日板块队友整体深水踩踏"),
    ("Theme_Support", "plate_yizi_cnt_ge1", "plate_yizi_cnt >= 1", "板块今日有队友顶一字助攻"),
    ("Theme_Support", "is_event_basket_false", "is_event_basket == False", "非消息驱动杂毛概念"),
    ("Theme_Support", "is_broad_ind_false", "is_broad_ind == False", "非大盘周期宽基行业"),
    ("Theme_Support", "sub_cluster_cnt_ge2", "sub_cluster_cnt >= 2", "细分题材具备横向扩散"),

    # 4. 筹码与容量
    ("Chips_Capacity", "lock_top10_ge45", "lock_top10 >= 45.0", "前十大股东锁仓>=45%"),
    ("Chips_Capacity", "lock_top10_ge55", "lock_top10 >= 55.0", "高锁仓控盘>=55%"),
    ("Chips_Capacity", "lock_top10_lt30", "lock_top10 < 30.0", "筹码极其分散<30%"),
    ("Chips_Capacity", "real_free_mcap_12_40", "real_free_mcap >= 12.0 and real_free_mcap <= 40.0", "游资黄金流通盘12~40亿"),
    ("Chips_Capacity", "real_free_mcap_lt15", "real_free_mcap < 15.0", "极小盘<15亿"),
    ("Chips_Capacity", "real_free_mcap_ge50", "real_free_mcap >= 50.0", "大盘承接困难>=50亿"),
    ("Chips_Capacity", "open_px_lt10", "open_px_raw < 10.0", "低价股<10元"),
    ("Chips_Capacity", "open_px_10_25", "open_px_raw >= 10.0 and open_px_raw <= 25.0", "中价股10~25元"),
    ("Chips_Capacity", "open_px_ge30", "open_px_raw >= 30.0", "高价股>=30元"),

    # 5. 席位、异动与公告
    ("Seats_Notices", "lhasa_seats_prev_ge2", "lhasa_seats_prev >= 2", "昨日龙虎榜拉萨散户席位>=2个"),
    ("Seats_Notices", "lhasa_seats_prev_0", "lhasa_seats_prev == 0", "昨日无拉萨席位"),
    ("Seats_Notices", "lhasa_buy_share_ge10", "lhasa_buy_share_prev >= 10.0", "拉萨散户买入占比>=10%"),
    ("Seats_Notices", "notice_bad_true", "notice_bad == True", "90日内有立案/违规/监管暴雷公告"),
    ("Seats_Notices", "notice_bad_false", "notice_bad == False", "无重大暴雷公告"),
    ("Seats_Notices", "notice_hard_true", "notice_hard == True", "硬科技/算力/芯片类公告"),
    ("Seats_Notices", "notice_ma_true", "notice_ma == True", "资产重组/并购公告"),
    ("Seats_Notices", "notice_earn_true", "notice_earn == True", "业绩预增/扭亏公告"),
    ("Seats_Notices", "has_ir_8d_true", "has_ir_8d == True", "近8日有机构互动易/调研"),
    ("Seats_Notices", "comm_posts_ge50", "comm_posts_24h >= 50", "股吧高热度讨论>=50帖"),

    # 6. 5m 盘口微观因子
    ("Micro_Tape", "pry_window_0930_1000", "pry_window == '09:30~10:00'", "早盘半小时急翘反核"),
    ("Micro_Tape", "pry_window_1000_1130", "pry_window == '10:00~11:30'", "上午盘中震荡翘板"),
    ("Micro_Tape", "pry_window_1300_1430", "pry_window == '13:00~14:30'", "午后偷翘"),
    ("Micro_Tape", "pry_window_1430_late", "pry_window == '14:30后'", "尾盘偷鸡翘板"),
    ("Micro_Tape", "pry_vol_mult_ge2", "pry_vol_mult >= 2.0", "翘板单根5m成交额为均值2倍以上爆发"),
    ("Micro_Tape", "pry_vol_mult_ge3", "pry_vol_mult >= 3.0", "翘板单根5m成交额为均值3倍以上巨量抢筹"),
    ("Micro_Tape", "pry_vol_mult_lt15", "pry_vol_mult < 1.5", "弱承接翘板"),

    # 7. 大盘环境与日历
    ("Market_Calendar", "mkt_panic_dt_ge20", "mkt_dt_prev >= 20", "昨日全场跌停>=20家极端恐慌冰点"),
    ("Market_Calendar", "mkt_panic_dt_ge30", "mkt_dt_prev >= 30", "极端大恐慌>=30家"),
    ("Market_Calendar", "mkt_dt_lt10", "mkt_dt_prev < 10", "市场非恐慌环境，跌停<10家"),
    ("Market_Calendar", "mkt_zt_ge50", "mkt_zt_prev >= 50", "昨日全场涨停>=50家情绪高潮"),
    ("Market_Calendar", "mkt_seal_rate_ge75", "mkt_seal_rate_prev >= 0.75", "市场打板封板率高"),
    ("Market_Calendar", "mkt_promo_ge22", "mkt_promo_1to2_5d >= 0.22", "一进二赚钱效应好"),
    ("Market_Calendar", "csi300_ret5_pos", "csi300_ret5 > 0.0", "沪深300指数5日上行周期"),
    ("Market_Calendar", "csi300_ret5_neg", "csi300_ret5 <= -0.015", "指数处于5日连续下杀"),
    ("Market_Calendar", "weekday_mon", "weekday == 0", "周一反核"),
    ("Market_Calendar", "weekday_fri", "weekday == 4", "周五反核"),
    ("Market_Calendar", "weekday_mid", "weekday in (1, 2, 3)", "周二至周四"),
    ("Market_Calendar", "quarter_q1", "quarter == 1", "Q1 春季躁动"),
    ("Market_Calendar", "quarter_q4", "quarter == 4", "Q4 年末炒妖"),
]

print(f"[+] Total factor definitions: {len(FACTORS)}")

catalog_rows = []

TARGET_POOLS = [
    ("Pool_A_HighDragon", df["pool"] == "Pool_A_HighDragon_Nuke"),
    ("Pool_A_and_B", df["pool"].isin(["Pool_A_HighDragon_Nuke", "Pool_B_1to2Board_Nuke"])),
    ("All_Pools", pd.Series(True, index=df.index)),
]

MODES = ["M1", "M2_15", "M3_15"]
EXITS = ["E1_next_open", "E2_tp5", "E4_dragon_hold"]

t_loop = time.time()
counter = 0

for p_tag, p_mask in TARGET_POOLS:
    for m in MODES:
        for ex_m in EXITS:
            base_df = df[p_mask & (df["mode"] == m)]
            if len(base_df) == 0: continue
            ret_col = f"ret_{ex_m}"
            exdt_col = f"exdt_{ex_m}"
            base_res = eval_slice(base_df, ret_col, exdt_col, base_mean=0.0)
            base_mean = base_res["avg_ret"] / 100.0
            
            catalog_rows.append({
                "factor_category": "Baseline",
                "factor_name": "Full_Pool_Baseline",
                "filter_expr": "No_Filter",
                "factor_desc": "无过滤基准池",
                "target_pool": p_tag,
                "mode": m,
                "exit_mode": ex_m,
                **base_res
            })
            
            for cat, fname, fexpr, fdesc in FACTORS:
                try:
                    f_mask = base_df.eval(fexpr)
                except Exception as err:
                    continue
                sub_df = base_df[f_mask]
                res = eval_slice(sub_df, ret_col, exdt_col, base_mean=base_mean)
                res.update({
                    "factor_category": cat,
                    "factor_name": fname,
                    "filter_expr": fexpr,
                    "factor_desc": fdesc,
                    "target_pool": p_tag,
                    "mode": m,
                    "exit_mode": ex_m,
                })
                catalog_rows.append(res)
                counter += 1

cat_df = pd.DataFrame(catalog_rows)
out_csv = f"{OUT_DIR}/p2_dragon_pry_factor_catalog.csv"
cat_df.to_csv(out_csv, index=False)
print(f"[+] Evaluated {counter} factor slices in {time.time()-t_loop:.2f}s!")
print(f"[+] Saved catalog to {out_csv} (shape: {cat_df.shape})")

# Print top 15 positive excess factors on Pool_A_HighDragon
print("\n" + "="*120)
print("TOP 15 FACTOR SLICES ON POOL A HIGH DRAGON (by Single-Slot NAV):")
print("="*120)
pA = cat_df[(cat_df["target_pool"] == "Pool_A_HighDragon") & (cat_df["factor_name"] != "Full_Pool_Baseline") & (cat_df["n_raw"] >= 10)]
topA = pA.sort_values("ss_nav", ascending=False).head(15)
show_cols = ["factor_name", "factor_desc", "mode", "exit_mode", "n_raw", "wr_raw", "payoff_raw", "avg_ret", "dt_reseal_r", "zt_seal_r", "ss_n", "ss_nav", "ss_mdd", "ss_ex_top3_nav", "is_wr", "oos_wr", "dual_same_sign"]
print(topA[show_cols].to_string(index=False))

# Print top factors by average return
print("\n" + "="*120)
print("TOP 10 FACTOR SLICES ON POOL A HIGH DRAGON (by Avg Net Return, n >= 15):")
print("="*120)
topA_avg = pA[pA["n_raw"] >= 15].sort_values("avg_ret", ascending=False).head(10)
print(topA_avg[show_cols].to_string(index=False))

# Print death traps
print("\n" + "="*120)
print("BOTTOM 10 DEATH TRAP SLICES ON POOL A HIGH DRAGON (Lowest Avg Net Return, n >= 15):")
print("="*120)
botA = pA[pA["n_raw"] >= 15].sort_values("avg_ret", ascending=True).head(10)
print(botA[show_cols].to_string(index=False))
