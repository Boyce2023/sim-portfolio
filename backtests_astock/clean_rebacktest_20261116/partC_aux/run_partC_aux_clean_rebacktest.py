#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_partC_aux_clean_rebacktest.py
================================================================================
Wave 2 · Part C: 两个辅助策略干净真账重跑（100% 完整 PIT 数据 + D15 严苛标准）
1. 辅助策略一：《超跌橡皮筋撬板 · V1.0》（满 165 分高严档，s_pry）
2. 辅助策略二：《五板卡异动辅助策略》（Buwen 原创五板策略）
3. 附表备查：《四进五 V2.0 除虫真实版》（已下放 stock2 不上实盘，仅作除虫对照）

遵循 D12（严禁 import yfinance）、D15（按日等权+单仓轮动+五期+同期沪深300净超额）。
================================================================================
"""
import os, sys, json, re
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
PART_C_DIR = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116/partC_aux"
CSI300_JSON = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"
FEE_RATE = 0.0020  # 0.20% 双边交易佣金 + 印花税 + 冲击滑点

with open(CSI300_JSON, "r", encoding="utf-8") as f:
    CSI_BENCH_MAP = json.load(f)

BENCH_VALS = {
    "10月以来": CSI_BENCH_MAP["2026年10月以来"][0],
    "7月以来": CSI_BENCH_MAP["2026年7月以来"][0],
    "2026全年": CSI_BENCH_MAP["2026全年"][0],
    "近三年": CSI_BENCH_MAP["近三年(2023-11-16起)"][0],
    "全五年": CSI_BENCH_MAP["全五年(2021-11-16起)"][0],
}


def calc_single_slot(df_trades):
    if df_trades.empty:
        return [], 1.0, 0.0
    srt = df_trades.sort_values(["buy_date", "score"], ascending=[True, False]).reset_index(drop=True)
    taken = []
    free_after = ""
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)
        if free_after == "" or bd > free_after:
            taken.append(r)
            free_after = str(r.exit_date)
            ret = float(r.net_ret)
            nav *= (1.0 + ret)
            pk = max(pk, nav)
            mdd = max(mdd, (pk - nav) / pk)
    return taken, nav, mdd


def calc_daily_eq(df_trades):
    if df_trades.empty:
        return 1.0, 0.0
    daily_m = df_trades.groupby("buy_date")["net_ret"].mean().sort_index()
    nav, pk, mdd = 1.0, 1.0, 0.0
    for ret in daily_m.values:
        nav *= (1.0 + float(ret))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
    return nav, mdd


def evaluate_5periods(df_trades, strategy_name=""):
    periods = {
        "10月以来": ("2026-10-01", "2026-11-16"),
        "7月以来": ("2026-07-01", "2026-11-16"),
        "2026全年": ("2026-01-01", "2026-11-16"),
        "近三年": ("2023-11-16", "2026-11-16"),
        "全五年": ("2021-11-15", "2026-11-16"),
    }
    res = {}
    for p_name, (s_dt, e_dt) in periods.items():
        sub = df_trades[(df_trades["buy_date"] >= s_dt) & (df_trades["buy_date"] <= e_dt)].copy()
        bench_ret = BENCH_VALS[p_name]  # %
        
        if sub.empty:
            res[p_name] = {
                "raw_n": 0, "single_n": 0, "wr": 0.0, "payoff": 0.0, "mean_pct": 0.0,
                "single_nav": 1.0, "single_ret_pct": 0.0, "single_mdd_pct": 0.0,
                "eq_nav": 1.0, "eq_ret_pct": 0.0, "eq_mdd_pct": 0.0,
                "csi300_pct": round(bench_ret, 2),
                "single_excess_pct": round(0.0 - bench_ret, 2),
                "eq_excess_pct": round(0.0 - bench_ret, 2),
            }
            continue
            
        taken, s_nav, s_mdd = calc_single_slot(sub)
        eq_nav, eq_mdd = calc_daily_eq(sub)
        
        rets = np.array([float(x.net_ret) for x in taken], dtype=float)
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        wr = float((rets > 0).mean() * 100.0) if len(rets) > 0 else 0.0
        if len(wins) > 0 and len(losses) > 0 and abs(losses.mean()) > 1e-6:
            po = float(wins.mean() / abs(losses.mean()))
        elif len(wins) > 0:
            po = 99.0
        else:
            po = 0.0
        mean_p = float(rets.mean() * 100.0) if len(rets) > 0 else 0.0
        
        s_ret_pct = (s_nav - 1.0) * 100.0
        eq_ret_pct = (eq_nav - 1.0) * 100.0
        
        res[p_name] = {
            "raw_n": int(len(sub)),
            "single_n": int(len(rets)),
            "wr": round(wr, 2),
            "payoff": round(po, 2),
            "mean_pct": round(mean_p, 2),
            "single_nav": round(s_nav, 4),
            "single_ret_pct": round(s_ret_pct, 2),
            "single_mdd_pct": round(s_mdd * 100.0, 2),
            "eq_nav": round(eq_nav, 4),
            "eq_ret_pct": round(eq_ret_pct, 2),
            "eq_mdd_pct": round(eq_mdd * 100.0, 2),
            "csi300_pct": round(bench_ret, 2),
            "single_excess_pct": round(s_ret_pct - bench_ret, 2),
            "eq_excess_pct": round(eq_ret_pct - bench_ret, 2),
        }
    return res


# ------------------------------------------------------------------------------
# 1. 超跌橡皮筋撬板 V1.0 (s_pry, 满165分高严档)
# ------------------------------------------------------------------------------
def run_pry_v10():
    print("[1/3] 重跑辅助策略一：《超跌橡皮筋撬板 · V1.0》（满165分）...")
    df_ledger = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock2/p5_full_pry_universe/v1_oversold_pry_165_strict_ledger.csv")
    df_sorted = df_ledger.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
    top1_per_day = df_sorted.groupby("buy_date").first().reset_index()
    
    # 丰富精确 buy_hhmm 与 exit_hhmm (基于 5 分钟线核验)
    # E8 开盘价买入，集合竞价 09:25
    buy_hhmm_list = ["09:25"] * len(top1_per_day)
    exit_hhmm_map = {
        ("2022-02-07", "603988"): "09:35",
        ("2022-04-26", "603217"): "09:35",
        ("2022-04-27", "603222"): "09:35",
        ("2022-04-28", "605289"): "10:15", # 5m 线实测 10:15 摸目标限价值
        ("2022-04-29", "002732"): "15:00", # Day 4 收盘未触线清仓
        ("2022-05-05", "002382"): "15:00", # Day 4 收盘
        ("2022-11-02", "603666"): "09:35",
        ("2022-12-05", "600026"): "15:00",
        ("2022-12-21", "603613"): "09:35",
        ("2023-03-17", "605369"): "15:00",
        ("2023-05-04", "600738"): "15:00",
        ("2024-02-05", "002715"): "09:30", # 买日不幸回封跌停，次日开盘无条件砍仓止损
        ("2024-02-06", "002644"): "09:35",
        ("2024-02-07", "002290"): "09:30", # 跳空高开直接超过止盈线，开盘价成交
        ("2024-02-08", "002889"): "09:35",
        ("2024-02-19", "600463"): "09:30", # 跳空高开止盈
        ("2024-04-17", "603266"): "09:30", # 跳空高开止盈
        ("2024-04-18", "000668"): "15:00",
        ("2024-06-07", "600358"): "09:35",
        ("2024-12-10", "600246"): "15:00",
        ("2025-04-09", "605018"): "09:35",
        ("2025-04-10", "001283"): "09:30", # 跳空高开止盈
        ("2026-07-21", "003026"): "15:00",
        ("2026-07-22", "001259"): "15:00",
        ("2026-10-16", "002829"): "15:00",
    }
    
    out_df = pd.DataFrame()
    out_df["buy_date"] = top1_per_day["buy_date"].astype(str)
    out_df["buy_hhmm"] = "09:25"
    out_df["exit_date"] = top1_per_day["exit_date"].astype(str)
    
    ex_hhmm = []
    for r in top1_per_day.itertuples():
        c6_s = str(r.code).zfill(6)
        ex_hhmm.append(exit_hhmm_map.get((r.buy_date, c6_s), "15:00"))
    out_df["exit_hhmm"] = ex_hhmm
    out_df["code"] = top1_per_day["code"].astype(str).str.zfill(6)
    out_df["name"] = top1_per_day["name"].astype(str)
    out_df["score"] = top1_per_day["score"].astype(int)
    out_df["net_ret"] = top1_per_day["net_ret"].round(6)
    out_df["o_pct"] = (top1_per_day["o_pct"] * 100.0).round(2)
    out_df["bias10"] = (top1_per_day["bias10"] * 100.0).round(2)
    out_df["down_streak"] = top1_per_day["down_streak"].astype(int)
    out_df["prev_c_ma20"] = (top1_per_day["prev_c_ma20"] * 100.0).round(2)
    out_df["real_free_mcap"] = top1_per_day["real_free_mcap"].round(2)
    out_df["mkt_open_zt_0925"] = top1_per_day["mkt_open_zt_0925"].astype(int)
    
    ledger_path = f"{PART_C_DIR}/ledger_aux_pry_v10.csv"
    out_df.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    print(f"  [+] 台账保存: {ledger_path} ({len(out_df)} 行)")
    
    # 评测五期 D15
    summary = evaluate_5periods(out_df, "s_pry")
    summary_path = f"{PART_C_DIR}/summary_aux_pry_v10.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  [+] 汇总保存: {summary_path}")
    return out_df, summary


# ------------------------------------------------------------------------------
# 2. 五板卡异动辅助策略 (Buwen 原创五板策略)
# ------------------------------------------------------------------------------
def run_5board():
    print("[2/3] 重跑辅助策略二：《五板卡异动辅助策略》（Buwen 原创）...")
    df_raw = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/verified_1a_5ban_cands.parquet")
    df_tox = pd.read_parquet(f"{ROOT}/sim-portfolio/data/pit_reg_tox_notices_5y_complete.parquet")
    TOX_RE = re.compile(r'(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)')
    df_real_tox = df_tox[df_tox['title'].astype(str).str.contains(TOX_RE)].copy()
    
    c6 = df_raw['code'].astype(str).str.zfill(6)
    m_main = c6.str.startswith(('00', '60'))
    m_non_st = ~df_raw['name'].str.contains('ST')
    m_buyable = df_raw['buyable_open'] & (~df_raw['is_yizi_open'])
    
    # 规则一: Day6开盘涨幅 <= +5.5% 且排除 -3.5% ~ +1.0%
    m_r1 = (df_raw['open_pct'] <= 0.055) & ((df_raw['open_pct'] < -0.035) | (df_raw['open_pct'] > 0.010))
    # 规则二: 前十流通股东锁仓比 >= 50.0% 且五板当日真实换手率处于 15% ~ 80%
    m_r2 = (df_raw['lock_top10'] >= 50.0) & (df_raw['prev_real_to'] >= 15.0) & (df_raw['prev_real_to'] <= 80.0)
    
    sub = df_raw[m_main & m_non_st & m_buyable & m_r1 & m_r2].copy()
    
    # 90日零毒丸公告排查
    tox_hit = set()
    for idx, r in sub.iterrows():
        c_val = str(r['code']).zfill(6)
        bd = str(r['buy_date'])
        d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime('%Y-%m-%d')
        t_sub = df_real_tox[(df_real_tox['sec_code'] == c_val) & (df_real_tox['pub_datetime_cst'] >= d90) & (df_real_tox['pub_datetime_cst'] <= bd + ' 09:25:00')]
        if not t_sub.empty:
            tox_hit.add(idx)
            
    clean_sub = sub.drop(list(tox_hit)).copy().reset_index(drop=True)
    clean_sub["score"] = clean_sub["lock_top10"]  # 单仓排序权重
    clean_sub["net_ret"] = clean_sub["ret_d4_93"].round(6)
    clean_sub["exit_date"] = clean_sub["ed_d4_93"].astype(str)
    
    out_df = pd.DataFrame()
    out_df["buy_date"] = clean_sub["buy_date"].astype(str)
    out_df["code"] = clean_sub["code"].astype(str).str.zfill(6)
    out_df["name"] = clean_sub["name"].astype(str)
    out_df["open_pct"] = (clean_sub["open_pct"] * 100.0).round(2)
    out_df["lock_top10"] = clean_sub["lock_top10"].round(2)
    out_df["prev_real_to"] = clean_sub["prev_real_to"].round(2)
    out_df["exit_date"] = clean_sub["exit_date"]
    out_df["net_ret"] = clean_sub["net_ret"]
    out_df["score"] = clean_sub["score"]
    out_df["hold_days"] = clean_sub["hb_d4_93"].astype(int)
    out_df["exit_mode"] = np.where(clean_sub["hb_d4_93"] < 4, "93%异动缓冲限价止盈", "Day9收盘全卖")
    
    ledger_path = f"{PART_C_DIR}/ledger_aux_5board.csv"
    out_df.to_csv(ledger_path, index=False, encoding="utf-8-sig")
    print(f"  [+] 台账保存: {ledger_path} ({len(out_df)} 行)")
    
    # 评测五期 D15
    summary = evaluate_5periods(out_df, "5board")
    summary_path = f"{PART_C_DIR}/summary_aux_5board.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  [+] 汇总保存: {summary_path}")
    return out_df, summary


# ------------------------------------------------------------------------------
# 3. 附表备查：《四进五 V2.0 除虫真实版》（已下放 stock2 不上实盘）
# ------------------------------------------------------------------------------
def run_ref_4to5_fixed():
    print("[3/3] 重跑透明附表备查：《四进五 V2.0 除虫真实版》（不上实盘）...")
    df_raw = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock2/p3_deep_100/w2_4to5_enriched_master.parquet")
    with open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
        holders = json.load(f)
    df_tox = pd.read_parquet(f"{ROOT}/sim-portfolio/data/pit_reg_tox_notices_5y_complete.parquet")
    TOX_RE = re.compile(r'(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规)')
    df_real_tox = df_tox[df_tox['title'].astype(str).str.contains(TOX_RE)].copy()
    
    def score_fixed(r):
        if not (r.get('buyable_open') == True): return -999, 'fail_not_buyable'
        c6_val = str(r['code']).zfill(6)
        bd = str(r['buy_date'])
        d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime('%Y-%m-%d')
        t_sub = df_real_tox[(df_real_tox['sec_code'] == c6_val) & (df_real_tox['pub_datetime_cst'] >= d90) & (df_real_tox['pub_datetime_cst'] <= bd + ' 09:25:00')]
        if not t_sub.empty: return -999, 'fail_tox_notice'
        if r.get('f_s_reg_10d', False) or (r.get('has_stock_reg', 0) > 0): return -999, 'fail_stock_reg'
        if float(r.get('tighter_headroom_pit', 0.0)) < 0.12: return -999, 'fail_headroom_lt12'
        if r.get('d4_blown_pm_5m', False) or r.get('d4_blown_pm_proxy', False): return -999, 'fail_d4_blown_pm'
        op_pct = float(r.get('open_pct', 0.0))
        if op_pct < 0.020 or op_pct > 0.075: return -999, 'fail_open_not_sweet' # B6 甜区
        
        score = 100
        raw_h = holders.get(c6_val, [])
        sd = str(r['sig_date'])
        h_list = [x for x in raw_h if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sd]
        if h_list: lock_top10 = float(max(h_list, key=lambda x: str(x[1]))[2])
        else:
            h_dict = [x for x in raw_h if isinstance(x, dict) and str(x.get('ann_date', '')) <= sd]
            lock_top10 = float(h_dict[-1].get('top10_ratio', 0.0)) if h_dict else 0.0
        
        oshare = float(r.get('oshare', 0.0))
        c_px = float(r.get('close', r.get('px_d4', 0.0)))
        real_mcap = float(c_px * oshare * (1.0 - lock_top10 / 100.0) / 1e8) if oshare > 0 else float(r.get('real_free_mcap', 20.0))
        
        if (lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0): score += 8
        elif (lock_top10 >= 45.0) or (real_mcap >= 45.0): score += 3
        elif (lock_top10 < 45.0) and (real_mcap < 45.0): score -= 8
            
        hr_pit = float(r.get('tighter_headroom_pit', 0.0))
        if hr_pit >= 0.25: score += 6
        elif hr_pit >= 0.22: score += 4
        
        max_b = int(r.get('mkt_max_board_prev', 0))
        if max_b == 4: score += 5
        elif max_b == 5: score += 2
        elif max_b >= 6: score -= 5
        
        # FIXED 1: 竞价头名送分除虫: 独苗只给+6，绝不叠加同身位第一+3
        is_sole = int(r.get('is_sole_4b', 0)) == 1
        if is_sole: score += 6
        elif int(r.get('is_top1_4b_open', 0)) == 1 and int(r.get('b4_rival_cnt', 0)) < 2: score += 3
        else: score -= 5
            
        d4_s34 = float(r.get('d4_v34_score', -999))
        if (82.0 <= d4_s34 <= 89.0) and is_sole: score += 5
        if bool(r.get('is_held_3to4', False)): score += 4
        d4_op = float(r.get('d4_open_pct', 0.0))
        d4_buyable = bool(r.get('d4_buyable_open', True))
        d3_yizi = bool(r.get('d3_prev_is_yizi', False))
        if ((d4_op > 0.092) or (not d4_buyable) or d3_yizi) and (0.020 <= op_pct <= 0.060): score += 3
        obc = int(r.get('open_board_count', 0))
        d3_obc = int(r.get('d3_open_board_count', 0))
        to_r = float(r.get('to_ratio_d4_d3', 1.0))
        if (obc >= 1) and (d3_obc >= 1) and (0.70 <= to_r <= 1.35): score += 3
        
        # 席位博弈
        if int(r.get('f_d4_quant_sell', 0)) >= 1: score -= 5
        if int(r.get('f52_d4_inst_sell', 0)) >= 1: score -= 3
        if bool(r.get('f50_d4_top_yz_new_buy', False)): score -= 3
        if int(r.get('f51_d4_lh_cnt', 0)) >= 3: score -= 6
        
        # 题材与日历
        if int(r.get('plate_3b_cnt', 0)) >= 1: score -= 6
        if float(r.get('px_d4', 0.0)) > 20.0: score -= 6
        if int(r.get('d4_mkt_nuke_cnt', 0)) >= 1: score -= 3
        if float(r.get('f47_reb_zt_r10', 0.0)) >= 0.20: score += 6
        dow = pd.Timestamp(bd).weekday() + 1
        if dow == 1: score += 6
        elif dow in (4, 5): score -= 3
        mo = pd.Timestamp(bd).month
        if mo in (1, 5): score -= 6
        
        return score, 'pass'
        
    scores = [score_fixed(r.to_dict())[0] for _, r in df_raw.iterrows()]
    df_raw['fixed_score'] = scores
    
    p120 = df_raw[df_raw['fixed_score'] >= 120].copy()
    ret_col = 'ret_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff'
    ex_col = 'exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff'
    
    p120['net_ret'] = p120[ret_col]
    p120['exit_date'] = p120[ex_col]
    p120['score'] = p120['fixed_score']
    
    out_df = pd.DataFrame()
    out_df['buy_date'] = p120['buy_date'].astype(str)
    out_df['code'] = p120['code'].astype(str).str.zfill(6)
    out_df['name'] = p120['name'].astype(str)
    out_df['score'] = p120['score'].astype(int)
    out_df['open_pct'] = (p120['open_pct'] * 100.0).round(2)
    out_df['exit_date'] = p120['exit_date'].astype(str)
    out_df['net_ret'] = p120['net_ret'].round(6)
    
    # 评测五期 D15
    summary = evaluate_5periods(out_df, "4to5_fixed_ref")
    summary["_metadata"] = {
        "status": "下放 astock2 研发管辖，不上实盘",
        "purpose": "仅作修虫前后诚实对照，透明备查",
        "bug_fixes": [
            "修完竞价头名送分: 独苗仅计+6分，排除虚假叠加+3分",
            "接入 100% 沪深主板锁仓覆盖 (pit_top10_all_codes.json，零 38% 假兜底)",
            "接入 100% 五年全量无断档毒丸与监管函 (pit_reg_tox_notices_5y_complete.parquet)",
            "修完买卖龙虎榜席位归属校验"
        ]
    }
    summary_path = f"{PART_C_DIR}/summary_ref_4to5_fixed.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  [+] 附表保存: {summary_path}")
    return out_df, summary


def main():
    os.makedirs(PART_C_DIR, exist_ok=True)
    
    # 1. 超跌橡皮筋撬板 V1.0
    df_pry, sum_pry = run_pry_v10()
    
    # 2. 五板卡异动辅助策略
    df_5b, sum_5b = run_5board()
    
    # 3. 附表备查：四进五除虫版
    df_4to5, sum_4to5 = run_ref_4to5_fixed()
    
    print("\n================== PART C 核心数字精炼汇报 ==================")
    print(f"1. 超跌橡皮筋撬板 V1.0 (s_pry, 满165分):")
    for p in ["10月以来", "7月以来", "2026全年", "近三年", "全五年"]:
        s = sum_pry[p]
        print(f"   [{p}] 笔数={s['single_n']}/{s['raw_n']} | 胜率={s['wr']}% | 盈亏比={s['payoff']} | 单仓净值={s['single_nav']}x (超额{s['single_excess_pct']:+}%) | 日等权={s['eq_nav']}x (超额{s['eq_excess_pct']:+}%)")
        
    print(f"\n2. 五板卡异动辅助策略 (5board):")
    for p in ["10月以来", "7月以来", "2026全年", "近三年", "全五年"]:
        s = sum_5b[p]
        print(f"   [{p}] 笔数={s['single_n']}/{s['raw_n']} | 胜率={s['wr']}% | 盈亏比={s['payoff']} | 单仓净值={s['single_nav']}x (超额{s['single_excess_pct']:+}%) | 日等权={s['eq_nav']}x (超额{s['eq_excess_pct']:+}%)")

    print(f"\n3. 附表备查: 四进五除虫真实版 (不上实盘):")
    for p in ["10月以来", "7月以来", "2026全年", "近三年", "全五年"]:
        s = sum_4to5[p]
        print(f"   [{p}] 笔数={s['single_n']}/{s['raw_n']} | 胜率={s['wr']}% | 盈亏比={s['payoff']} | 单仓净值={s['single_nav']}x (超额{s['single_excess_pct']:+}%) | 日等权={s['eq_nav']}x (超额{s['eq_excess_pct']:+}%)")


if __name__ == "__main__":
    main()
