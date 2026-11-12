#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
audit_old_m2.py — 「一进二定式 M2」5年全周期剥皮拆骨式消融审计
严格执行单仓轮动、同日等权对比、扣除双边 0.25% 磨损、对比沪深300基准。
"""

import os
import sys
import json
import sqlite3
import datetime
import numpy as np
import pandas as pd

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
DOCS_DIR = f"{ROOT_DIR}/docs/90_内部_给Claude读/astock/一进二递归工程"
LEDGER_PATH = f"{DOCS_DIR}/MASTER_5Y_239_TRADES_LEDGER.json"
FAST_SCRIPT_PATH = f"{SIM_DIR}/scripts/fast_1to2_today.py"
NOTICES_DB_PATH = f"{SIM_DIR}/backtest/2026-08-24-daban/notices.db"
OUTPUT_JSON_PATH = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean/audit_old_m2_results.json"
PARQUET_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"

FEE_RATE = 0.0025  # 双边印花税+佣金+滑点 0.25%

# CSI 300 基准年度收益率
CSI300_ANNUAL = {
    "2021": -0.0520,
    "2022": -0.2163,
    "2023": -0.1138,
    "2024": 0.1468,
    "2025": -0.0280,
    "2026": 0.1250,
}

def load_data():
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        ledger = json.load(f)
    trades = ledger["trades"]

    # 查 notices.db 看哪些公告是偷看未来4天得到的
    notice_future_lookup = {}
    if os.path.exists(NOTICES_DB_PATH):
        conn = sqlite3.connect(NOTICES_DB_PATH)
        for t in trades:
            c6 = t["ticker"][:6]
            d2 = t["dt_str"]
            # D1 是前一个交易日，通常为 d2 减去 1 到 3 天
            # 检查是否有 ndate > d1 的公告被提前计入
            cur = conn.cursor()
            cur.execute("SELECT ndate, title FROM notice WHERE code = ? AND ndate >= date(?, '-5 days') AND ndate <= date(?, '+5 days')", (c6, d2, d2))
            rows = cur.fetchall()
            notice_future_lookup[f"{c6}_{d2}"] = rows
        conn.close()

    # 读取日线行情用于精确验证价格、突破买与竞价买收益
    df_price = pd.read_parquet(PARQUET_PATH, columns=["date", "ticker", "open", "high", "low", "close"])
    df_price["date_str"] = df_price["date"].dt.strftime("%Y-%m-%d")
    df_price["pre_c"] = df_price.groupby("ticker")["close"].shift(1)
    df_price.set_index(["ticker", "date_str"], inplace=True)

    return trades, notice_future_lookup, df_price

def simulate_trades(trade_list, df_price, buy_type="open", fee=FEE_RATE):
    """
    单仓轮动模拟：
    同一时间只持有一只股票，在持有期间触发的其他信号无法买入。
    计算真实胜率、盈亏比、年化收益、最大回撤。
    """
    if not trade_list:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "pl_ratio": 0.0,
            "cum_return": 0.0,
            "max_drawdown": 0.0,
            "annual": {},
            "trades": []
        }

    # 按买入日期排序
    sorted_trades = sorted(trade_list, key=lambda x: (x["dt_str"], -x.get("tot", 0)))

    # 单仓轮动过滤：当前仓位未卖出前，不能开新仓
    single_pos_trades = []
    current_free_date = "1990-01-01"

    for t in sorted_trades:
        buy_date = t["dt_str"]
        exit_date = str(t.get("exit_d_daban_s", ""))[:10]
        if not exit_date:
            exit_date = buy_date

        if buy_date >= current_free_date:
            single_pos_trades.append(t)
            # 卖出次日才能买入新票
            current_free_date = exit_date

    # 计算每笔交易的实际净收益
    executed_trades = []
    for t in single_pos_trades:
        tk = t["ticker"]
        d2 = t["dt_str"]
        exit_d = str(t.get("exit_d_daban_s", ""))[:10]
        
        # 默认取 ledger 里的收益率作为基准，扣除双边手续费
        raw_ret = float(t.get("rs_m2", 0.0))
        
        if (tk, d2) in df_price.index:
            row_d2 = df_price.loc[(tk, d2)]
            pre_c = float(row_d2["pre_c"]) if pd.notna(row_d2["pre_c"]) and row_d2["pre_c"] > 0 else float(row_d2["open"]) / (1.0 + float(t.get("o_pct", 0.04)))
            open_p = float(row_d2["open"])
            high_p = float(row_d2["high"])
            zt_p = np.floor(pre_c * 1.10 * 100 + 0.5) / 100.0
            trig_p = min(zt_p, max(open_p * 1.012, pre_c * 1.065))

            if buy_type == "trig":
                # 盘中突破买逻辑：如果最高价连 trig_p 都没碰到，则无法成交！
                if high_p < trig_p:
                    # 无法成交，跳过
                    continue
                # 若能成交，买入价为 trig_p
                # 重新计算相对于原先 open 买的收益损耗
                buy_price = trig_p
                # 获取卖出价
                if (tk, exit_d) in df_price.index:
                    row_ex = df_price.loc[(tk, exit_d)]
                    # 假定原版是按次日开盘或收盘卖出
                    exit_price = float(row_ex["open"])
                    ret_calc = (exit_price / buy_price) - 1.0
                else:
                    ret_calc = raw_ret - ((trig_p - open_p) / open_p)
                net_ret = (1.0 + ret_calc) * (1.0 - fee) - 1.0
            else:
                # 纯 09:25 竞价直接买
                if (tk, exit_d) in df_price.index:
                    row_ex = df_price.loc[(tk, exit_d)]
                    exit_price = float(row_ex["open"])
                    ret_calc = (exit_price / open_p) - 1.0
                else:
                    ret_calc = raw_ret
                net_ret = (1.0 + ret_calc) * (1.0 - fee) - 1.0
        else:
            net_ret = (1.0 + raw_ret) * (1.0 - fee) - 1.0

        t_copy = dict(t)
        t_copy["net_ret"] = net_ret
        executed_trades.append(t_copy)

    # 统计年化与全局指标
    years = sorted(list(set(t["dt_str"][:4] for t in executed_trades)))
    annual_stats = {}
    cum_nav = 1.0
    nav_series = [1.0]

    for yr in ["2021", "2022", "2023", "2024", "2025", "2026"]:
        yr_trades = [t for t in executed_trades if t["dt_str"].startswith(yr)]
        cnt = len(yr_trades)
        if cnt == 0:
            annual_stats[yr] = {
                "trades_count": 0,
                "win_rate": 0.0,
                "pl_ratio": 0.0,
                "annual_return": 0.0,
                "max_drawdown": 0.0,
                "csi300_return": CSI300_ANNUAL.get(yr, 0.0),
                "alpha": 0.0 - CSI300_ANNUAL.get(yr, 0.0)
            }
            continue

        wins = [t["net_ret"] for t in yr_trades if t["net_ret"] > 0]
        losses = [t["net_ret"] for t in yr_trades if t["net_ret"] <= 0]
        win_rate = len(wins) / cnt if cnt > 0 else 0.0
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = abs(np.mean(losses)) if losses else 1e-6
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

        yr_nav = 1.0
        yr_peak = 1.0
        yr_mdd = 0.0
        for t in yr_trades:
            yr_nav *= (1.0 + t["net_ret"])
            if yr_nav > yr_peak:
                yr_peak = yr_nav
            dd = (yr_peak - yr_nav) / yr_peak
            if dd > yr_mdd:
                yr_mdd = dd

        annual_stats[yr] = {
            "trades_count": cnt,
            "win_rate": round(win_rate, 4),
            "pl_ratio": round(pl_ratio, 2),
            "annual_return": round(yr_nav - 1.0, 4),
            "max_drawdown": round(yr_mdd, 4),
            "csi300_return": round(CSI300_ANNUAL.get(yr, 0.0), 4),
            "alpha": round((yr_nav - 1.0) - CSI300_ANNUAL.get(yr, 0.0), 4)
        }

    # 全周期总指标
    all_rets = [t["net_ret"] for t in executed_trades]
    tot_cnt = len(all_rets)
    tot_wins = [r for r in all_rets if r > 0]
    tot_losses = [r for r in all_rets if r <= 0]
    tot_win_rate = len(tot_wins) / tot_cnt if tot_cnt > 0 else 0.0
    tot_pl = (np.mean(tot_wins) / abs(np.mean(tot_losses))) if tot_losses and tot_wins else 0.0

    peak = 1.0
    mdd = 0.0
    for r in all_rets:
        cum_nav *= (1.0 + r)
        nav_series.append(cum_nav)
        if cum_nav > peak:
            peak = cum_nav
        dd = (peak - cum_nav) / peak
        if dd > mdd:
            mdd = dd

    return {
        "total_trades": tot_cnt,
        "win_rate": round(tot_win_rate, 4),
        "pl_ratio": round(tot_pl, 2),
        "cum_nav": round(cum_nav, 4),
        "cum_return": round(cum_nav - 1.0, 4),
        "max_drawdown": round(mdd, 4),
        "annual": annual_stats,
        "trades": executed_trades
    }

def simulate_equal_weight_daily(trade_list, df_price, buy_type="open", fee=FEE_RATE):
    """
    同日多只过线等权均分版本：
    彻底消除日线不知道谁先涨到触发价的先后偏差。
    """
    if not trade_list:
        return {"cum_nav": 1.0, "total_days": 0}

    # 按日聚合
    daily_groups = {}
    for t in trade_list:
        d = t["dt_str"]
        daily_groups.setdefault(d, []).append(t)

    sorted_dates = sorted(daily_groups.keys())
    daily_rets = []
    
    for d in sorted_dates:
        day_cands = daily_groups[d]
        rets_this_day = []
        for t in day_cands:
            tk = t["ticker"]
            exit_d = str(t.get("exit_d_daban_s", ""))[:10]
            raw_ret = float(t.get("rs_m2", 0.0))
            if (tk, d) in df_price.index and (tk, exit_d) in df_price.index:
                row_d = df_price.loc[(tk, d)]
                row_ex = df_price.loc[(tk, exit_d)]
                open_p = float(row_d["open"])
                high_p = float(row_d["high"])
                pre_c = float(row_d["pre_c"]) if pd.notna(row_d["pre_c"]) and row_d["pre_c"] > 0 else open_p
                zt_p = np.floor(pre_c * 1.10 * 100 + 0.5) / 100.0
                trig_p = min(zt_p, max(open_p * 1.012, pre_c * 1.065))
                
                if buy_type == "trig":
                    if high_p < trig_p:
                        continue
                    buy_price = trig_p
                else:
                    buy_price = open_p
                exit_price = float(row_ex["open"])
                ret_calc = (exit_price / buy_price) - 1.0
                net_r = (1.0 + ret_calc) * (1.0 - fee) - 1.0
            else:
                net_r = (1.0 + raw_ret) * (1.0 - fee) - 1.0
            rets_this_day.append(net_r)

        if rets_this_day:
            daily_rets.append({"date": d, "mean_ret": np.mean(rets_this_day), "count": len(rets_this_day)})

    cum_nav = 1.0
    peak = 1.0
    mdd = 0.0
    for dr in daily_rets:
        cum_nav *= (1.0 + dr["mean_ret"])
        if cum_nav > peak:
            peak = cum_nav
        dd = (peak - cum_nav) / peak
        if dd > mdd:
            mdd = dd

    return {
        "cum_nav": round(cum_nav, 4),
        "total_days": len(daily_rets),
        "mean_candidates_per_day": round(np.mean([dr["count"] for dr in daily_rets]), 2) if daily_rets else 0.0,
        "max_drawdown": round(mdd, 4)
    }

def run_ablation_experiments():
    print("=" * 70)
    print("开始执行「一进二定式 M2」5年全周期剥皮拆骨式消融实验 (2021-10-20 至 2026-11-10)")
    print("=" * 70)

    trades, notice_lookup, df_price = load_data()
    print(f"成功加载原始交易账本，历史交易总笔数: {len(trades)}")

    # -------------------------------------------------------------
    # V0: 原版复现 (Original Reproduction)
    # -------------------------------------------------------------
    print("\n>>> 正在运行 V0: 原版复现 (严格单仓轮动 + 0.25% 真实印花滑点)...")
    v0_res = simulate_trades(trades, df_price, buy_type="open", fee=FEE_RATE)
    v0_eq = simulate_equal_weight_daily(trades, df_price, buy_type="open", fee=FEE_RATE)

    # -------------------------------------------------------------
    # V1: 砍掉 2026 后视镜题材词 TECH_PAT 与新概念词表加分
    # -------------------------------------------------------------
    print("\n>>> 正在运行 V1: 砍掉 2026 后视镜题材词 TECH_PAT 与新概念加分...")
    v1_trades = []
    v1_dropped = 0
    for t in trades:
        # TECH_PAT 扣除 16 分，has_new_term 扣除 15 分
        tech_bonus = 16.0 if t.get("is_tech") else 0.0
        new_term_bonus = 15.0 if t.get("has_new_term") else 0.0
        
        # 重新核算先验分与总分
        new_s_prior = t["s_prior"] - tech_bonus - new_term_bonus
        new_tot = t["tot"] - tech_bonus - new_term_bonus
        
        # 门槛校验: s_prior >= 35 且 tot >= 230
        if new_s_prior >= 35.0 and new_tot >= 230.0:
            t_v1 = dict(t)
            t_v1["s_prior"] = new_s_prior
            t_v1["tot"] = new_tot
            v1_trades.append(t_v1)
        else:
            v1_dropped += 1

    print(f"V1 过滤后保留笔数: {len(v1_trades)}, 淘汰后视镜违规样本: {v1_dropped}")
    v1_res = simulate_trades(v1_trades, df_price, buy_type="open", fee=FEE_RATE)
    v1_eq = simulate_equal_weight_daily(v1_trades, df_price, buy_type="open", fee=FEE_RATE)

    # -------------------------------------------------------------
    # V2: 砍掉公告未来函数 (ndate <= d1_date + 4 -> 严格 ndate <= d1_date)
    # -------------------------------------------------------------
    print("\n>>> 正在运行 V2: 砍掉公告未来函数 (ndate <= d1_date 滞后一日或剔除)...")
    v2_trades = []
    v2_dropped = 0
    for t in trades:
        # 旧版只要 notice_hard 就加了 18 分，且旧版 SQL 允许 ndate <= d1_date + 4
        # 若剥离非同日硬公告加分 (即公告实际上在首板次日之后才发出的虚假加分)
        # 对无时分秒公告，采取严格滞后一日或完全剔除该 18 分
        has_notice = bool(t.get("notice_hard", 0))
        notice_bonus = 18.0 if has_notice else 0.0
        
        new_s_prior = t["s_prior"] - notice_bonus
        new_tot = t["tot"] - notice_bonus
        
        if new_s_prior >= 35.0 and new_tot >= 230.0:
            t_v2 = dict(t)
            t_v2["s_prior"] = new_s_prior
            t_v2["tot"] = new_tot
            v2_trades.append(t_v2)
        else:
            v2_dropped += 1

    print(f"V2 过滤后保留笔数: {len(v2_trades)}, 淘汰未来公告依赖样本: {v2_dropped}")
    v2_res = simulate_trades(v2_trades, df_price, buy_type="open", fee=FEE_RATE)
    v2_eq = simulate_equal_weight_daily(v2_trades, df_price, buy_type="open", fee=FEE_RATE)

    # -------------------------------------------------------------
    # V3: 参数微扰过拟合压力测试 (±10% 扰动)
    # -------------------------------------------------------------
    print("\n>>> 正在运行 V3: 参数微扰过拟合压力测试 (±10% 魔法阈值扰动)...")
    # 收紧 10%: tot_thr 230 -> 253, s_prior 35 -> 38.5, o_pct [0.033, 0.074]
    v3_tight_trades = []
    for t in trades:
        if (t["tot"] >= 253.0 and t["s_prior"] >= 38.5 and 
            0.033 <= t.get("o_pct", 0.0) <= 0.074 and 
            t.get("dd20_d0", 1.0) <= 0.82 * 0.90):
            v3_tight_trades.append(t)

    # 放宽 10%: tot_thr 230 -> 207, s_prior 35 -> 31.5, o_pct [0.027, 0.090]
    v3_loose_trades = []
    for t in trades:
        if (t["tot"] >= 207.0 and t["s_prior"] >= 31.5 and 
            0.027 <= t.get("o_pct", 0.0) <= 0.090 and 
            t.get("dd20_d0", 1.0) <= 0.82 * 1.10):
            v3_loose_trades.append(t)

    v3_tight_res = simulate_trades(v3_tight_trades, df_price, buy_type="open", fee=FEE_RATE)
    v3_loose_res = simulate_trades(v3_loose_trades, df_price, buy_type="open", fee=FEE_RATE)

    # -------------------------------------------------------------
    # V4: 纯 09:25 竞价直接买 vs 盘中 trig_p 突破买对比
    # -------------------------------------------------------------
    print("\n>>> 正在运行 V4: 纯 09:25 竞价直接买 vs 盘中 trig_p 突破买对比...")
    v4_open_res = simulate_trades(trades, df_price, buy_type="open", fee=FEE_RATE)
    v4_trig_res = simulate_trades(trades, df_price, buy_type="trig", fee=FEE_RATE)

    # 汇总结果
    results = {
        "audit_meta": {
            "model": "1to2_Model_M2",
            "period": "2021-10-20 to 2026-11-10",
            "fee_rate": FEE_RATE,
            "raw_ledger_trades": len(trades),
        },
        "V0_original": {
            "single_pos": v0_res,
            "equal_weight": v0_eq,
        },
        "V1_no_hindsight_tech": {
            "dropped_count": v1_dropped,
            "remaining_count": len(v1_trades),
            "single_pos": v1_res,
            "equal_weight": v1_eq,
        },
        "V2_no_notice_lookahead": {
            "dropped_count": v2_dropped,
            "remaining_count": len(v2_trades),
            "single_pos": v2_res,
            "equal_weight": v2_eq,
        },
        "V3_param_perturbation": {
            "tighten_10pct": v3_tight_res,
            "loosen_10pct": v3_loose_res,
        },
        "V4_execution_compare": {
            "open_buy": v4_open_res,
            "trig_buy": v4_trig_res,
        }
    }

    # 落盘
    os.makedirs(os.path.dirname(OUTPUT_JSON_PATH), exist_ok=True)
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n消融实验结果已成功保存到: {OUTPUT_JSON_PATH}")

    # 打印逐年详细对比报告
    print_report(results)

def print_report(res):
    v0 = res["V0_original"]["single_pos"]
    v1 = res["V1_no_hindsight_tech"]["single_pos"]
    v2 = res["V2_no_notice_lookahead"]["single_pos"]
    v3_t = res["V3_param_perturbation"]["tighten_10pct"]
    v3_l = res["V3_param_perturbation"]["loosen_10pct"]
    v4_o = res["V4_execution_compare"]["open_buy"]
    v4_t = res["V4_execution_compare"]["trig_buy"]

    print("\n" + "=" * 80)
    print("【一进二定式 M2 真实消融实验审计报告】")
    print("=" * 80)

    print("\n[一、5个对照版本总览与抗造度对比]")
    print(f"{'版本':<18} | {'样本笔数':<8} | {'胜率':<8} | {'盈亏比':<8} | {'5年累计净值':<12} | {'最大回撤':<8}")
    print("-" * 75)
    print(f"{'V0 原版复现':<18} | {v0['total_trades']:<8} | {v0['win_rate']*100:.1f}%   | {v0['pl_ratio']:<8} | {v0['cum_nav']:<12.2f}x | {v0['max_drawdown']*100:.1f}%")
    print(f"{'V1 砍后视镜题材':<18} | {v1['total_trades']:<8} | {v1['win_rate']*100:.1f}%   | {v1['pl_ratio']:<8} | {v1['cum_nav']:<12.2f}x | {v1['max_drawdown']*100:.1f}%")
    print(f"{'V2 砍未来公告':<18} | {v2['total_trades']:<8} | {v2['win_rate']*100:.1f}%   | {v2['pl_ratio']:<8} | {v2['cum_nav']:<12.2f}x | {v2['max_drawdown']*100:.1f}%")
    print(f"{'V3 收紧10%微扰':<18} | {v3_t['total_trades']:<8} | {v3_t['win_rate']*100:.1f}%   | {v3_t['pl_ratio']:<8} | {v3_t['cum_nav']:<12.2f}x | {v3_t['max_drawdown']*100:.1f}%")
    print(f"{'V3 放宽10%微扰':<18} | {v3_l['total_trades']:<8} | {v3_l['win_rate']*100:.1f}%   | {v3_l['pl_ratio']:<8} | {v3_l['cum_nav']:<12.2f}x | {v3_l['max_drawdown']*100:.1f}%")
    print(f"{'V4 竞价开盘买':<18} | {v4_o['total_trades']:<8} | {v4_o['win_rate']*100:.1f}%   | {v4_o['pl_ratio']:<8} | {v4_o['cum_nav']:<12.2f}x | {v4_o['max_drawdown']*100:.1f}%")
    print(f"{'V4 盘中突破买':<18} | {v4_t['total_trades']:<8} | {v4_t['win_rate']*100:.1f}%   | {v4_t['pl_ratio']:<8} | {v4_t['cum_nav']:<12.2f}x | {v4_t['max_drawdown']*100:.1f}%")

    print("\n[二、V0 原版逐年绩效与同期沪深300基准对比]")
    print(f"{'年份':<6} | {'真实笔数':<8} | {'胜率':<8} | {'盈亏比':<8} | {'年化收益':<10} | {'最大回撤':<8} | {'沪深300':<10} | {'超额收益(Alpha)':<14}")
    print("-" * 88)
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        st = v0["annual"].get(yr, {})
        print(f"{yr:<6} | {st.get('trades_count', 0):<8} | {st.get('win_rate', 0)*100:.1f}%   | {st.get('pl_ratio', 0):<8} | {st.get('annual_return', 0)*100:+.1f}%    | {st.get('max_drawdown', 0)*100:.1f}%   | {st.get('csi300_return', 0)*100:+.1f}%    | {st.get('alpha', 0)*100:+.1f}%")

    print("\n[三、V1 砍掉后视镜题材后逐年表现]")
    print(f"{'年份':<6} | {'真实笔数':<8} | {'胜率':<8} | {'盈亏比':<8} | {'年化收益':<10} | {'最大回撤':<8} | {'沪深300':<10} | {'超额收益(Alpha)':<14}")
    print("-" * 88)
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        st = v1["annual"].get(yr, {})
        print(f"{yr:<6} | {st.get('trades_count', 0):<8} | {st.get('win_rate', 0)*100:.1f}%   | {st.get('pl_ratio', 0):<8} | {st.get('annual_return', 0)*100:+.1f}%    | {st.get('max_drawdown', 0)*100:.1f}%   | {st.get('csi300_return', 0)*100:+.1f}%    | {st.get('alpha', 0)*100:+.1f}%")

    print("\n[四、同日多只过线对比：总分第1 vs 等权均分]")
    print(f"V0 单仓总分第1累计净值: {v0['cum_nav']:.2f}x, 最大回撤: {v0['max_drawdown']*100:.1f}%")
    print(f"V0 同日等权均分累计净值: {res['V0_original']['equal_weight']['cum_nav']:.2f}x, 交易天数: {res['V0_original']['equal_weight']['total_days']}, 最大回撤: {res['V0_original']['equal_weight']['max_drawdown']*100:.1f}%")

if __name__ == "__main__":
    run_ablation_experiments()
