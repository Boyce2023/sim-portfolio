#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A-Share 2-to-3 Strict Anti-Overfitting Strategy Design & Reproduction Pipeline.

Core Design Rules (Max 4 rules on top of Base Pool):
- Base Pool:
  1. (~prev_is_yizi): Turnover 2nd board (No 1-word board traps)
  2. buyable_open: Tradable open (No ceiling/floor open lock)
  3. open_pct in [0.03, 0.08]: Call auction high open 3%~8%
- 4 Filters (with physical mechanism):
  1. rk_theme == 1: Market's #1 Mainline Theme Leader (Theme head身位唯一性，资金绝对主攻方向)
  2. mkt_promo_1to2_5d >= 0.20: Macro 5-day 1-to-2 Promo Rate >= 20% (宏观接力赚钱效应良性期，规避退潮冰点)
  3. lock_top10 >= 50.0: Top 10 Shareholders Lock >= 50% (高锁仓微观结构，外部自由浮筹少，拉升阻力低)
  4. seal_tightness >= 40.0: 2nd Board Seal Tightness >= 40.0 (二板盘口质量极高，封板态度坚决，剔除烂板偷袭)
- Trade Execution:
  - Buy: 09:25 Call auction open price.
  - Sell: 3-to-4 4-branch exit (exit_3to4) with 0.2% round-trip fee.
"""
import os, sys, time, json, pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from d15_eval_helper import evaluate_d15_full, FEE_RATE, _sim_single_slot, _sim_daily_eq

CAND_PATH = f"{CUR_DIR}/cand_2to3.parquet"
BARS_PATH = f"{CUR_DIR}/code_bars_5y.pkl"
RESULTS_JSON_PATH = f"{CUR_DIR}/strict23_results.json"
LEDGER_CSV_PATH = f"{CUR_DIR}/strict23_ledger.csv"

def get_trade_3to4(b, pos, buy_date, code):
    if not b: return None
    op = b["open"][pos]; zt = b["zt_px"][pos]; dt = b["dt_px"][pos]
    pre = b["pre_c"][pos]; hi = b["high"][pos]
    if op >= zt - 0.01 or op <= dt + 0.01 or op <= 0 or pre <= 0:
        return None
    buy_px = op
    adj_buy = b["adjf"][pos]
    is_zt_day = b["is_zt"][pos]
    c_day = b["close"][pos]
    
    if not is_zt_day:
        p1 = pos + 1
        curr = p1
        while curr < len(b["dts"]) and b["is_yizi_dt"][curr]: curr += 1
        if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
        if curr == p1 and b["high"][p1] >= c_day * 1.02:
            exit_px = max(b["open"][p1], round(c_day * 1.02, 2))
        else:
            exit_px = b["close"][curr]
        adj_exit = b["adjf"][curr]
        net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
        return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, True, buy_px, exit_px)
    else:
        curr = pos + 1
        while curr < len(b["dts"]):
            if b["is_yizi_dt"][curr] or b["is_zt"][curr]: curr += 1; continue
            break
        if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
        prev_c = b["close"][curr - 1]
        op_c = b["open"][curr]; hi_c = b["high"][curr]; lo_c = b["low"][curr]
        if op_c < prev_c * 1.015 and hi_c >= prev_c * 1.03:
            exit_px = max(op_c, round(prev_c * 1.03, 2))
        elif hi_c >= prev_c * 1.09 and lo_c <= prev_c * 1.065:
            exit_px = round(prev_c * 1.065, 2)
        else:
            exit_px = b["close"][curr]
        adj_exit = b["adjf"][curr]
        net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
        return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, True, buy_px, exit_px)

def main():
    t0 = time.time()
    print("[+] Loading candidate data and daily bars...")
    cand_df = pd.read_parquet(CAND_PATH)
    with open(BARS_PATH, "rb") as f:
        pkg = pickle.load(f)
    code_bars = pkg["code_bars"]
    print(f"[+] Loaded {len(cand_df):,} candidates in {time.time()-t0:.2f}s")

    print("[+] Simulating trade outcomes for all candidates...")
    trades = []
    for r in cand_df.itertuples(index=False):
        b = code_bars.get(r.code)
        if not b:
            trades.append(None)
            continue
        pos = b["date_to_pos"].get(r.buy_date)
        if pos is None or pos >= len(b["dts"]) - 1:
            trades.append(None)
            continue
        t = get_trade_3to4(b, pos, r.buy_date, r.code)
        trades.append(t)

    cand_df["net_ret"] = [t[2] if t is not None else np.nan for t in trades]
    cand_df["exit_date"] = [t[3] if t is not None else "" for t in trades]
    cand_df["hold_bars"] = [t[4] if t is not None else 0 for t in trades]
    cand_df["exit_at_open"] = [t[5] if t is not None else False for t in trades]
    cand_df["buy_at_open"] = [t[6] if t is not None else True for t in trades]
    cand_df["buy_px"] = [t[7] if t is not None else np.nan for t in trades]
    cand_df["exit_px"] = [t[8] if t is not None else np.nan for t in trades]
    cand_df["priority_score"] = cand_df["open_pct"]

    # ------------------------------------------------------------------
    # Step 1: In-Sample (2022-01-04 to 2024-12-31) & Out-of-Sample Split
    # ------------------------------------------------------------------
    IS_START, IS_END = "2022-01-04", "2024-12-31"
    OOS_START, OOS_END = "2025-01-01", "2026-11-10"

    # Base Pool
    m_base = (~cand_df["prev_is_yizi"]) & cand_df["buyable_open"] & (cand_df["open_pct"] >= 0.03) & (cand_df["open_pct"] <= 0.08)

    # 4 Strict Conditions
    r1 = (cand_df["rk_theme"] == 1)
    r2 = (cand_df["mkt_promo_1to2_5d"] >= 0.20)
    r3 = (cand_df["lock_top10"] >= 50.0)
    r4 = (cand_df["seal_tightness"] >= 40.0)

    final_m = m_base & r1 & r2 & r3 & r4
    matched_df = cand_df[final_m].dropna(subset=["net_ret"]).copy()

    cols_for_eval = ["buy_date", "code", "name", "net_ret", "exit_date", "hold_bars", "exit_at_open", "buy_at_open", "priority_score", "buy_px", "exit_px"]
    eval_df = matched_df[cols_for_eval].sort_values(["buy_date", "priority_score"], ascending=[True, False]).copy()

    # Save ledger
    eval_df.to_csv(LEDGER_CSV_PATH, index=False, encoding="utf-8-sig")
    print(f"[+] Saved ledger: {LEDGER_CSV_PATH} ({len(eval_df)} trades)")

    # Full D15 Evaluation
    d15_res = evaluate_d15_full(eval_df)

    # In-sample single slot & evaluation
    is_eval_df = eval_df[(eval_df["buy_date"] >= IS_START) & (eval_df["buy_date"] <= IS_END)].copy()
    is_taken, is_nav, is_mdd, is_h = _sim_single_slot(is_eval_df)
    is_rets = np.array([t.net_ret for t in is_taken], dtype=float)
    is_n = len(is_rets)
    is_wr = float((is_rets > 0).mean() * 100.0) if len(is_rets) else 0.0
    is_wins, is_losses = is_rets[is_rets > 0], is_rets[is_rets <= 0]
    is_po = float(is_wins.mean() / abs(is_losses.mean())) if (len(is_wins)>0 and len(is_losses)>0 and is_losses.mean()<0) else 0.0

    # Out-of-sample single slot & evaluation
    oos_eval_df = eval_df[(eval_df["buy_date"] >= OOS_START) & (eval_df["buy_date"] <= OOS_END)].copy()
    oos_taken, oos_nav, oos_mdd, oos_h = _sim_single_slot(oos_eval_df)
    oos_rets = np.array([t.net_ret for t in oos_taken], dtype=float)
    oos_n = len(oos_rets)
    oos_wr = float((oos_rets > 0).mean() * 100.0) if len(oos_rets) else 0.0
    oos_wins, oos_losses = oos_rets[oos_rets > 0], oos_rets[oos_rets <= 0]
    oos_po = float(oos_wins.mean() / abs(oos_losses.mean())) if (len(oos_wins)>0 and len(oos_losses)>0 and oos_losses.mean()<0) else (99.0 if len(oos_wins)>0 else 0.0)

    # ------------------------------------------------------------------
    # Step 2: Parameter Plateau Perturbation Table (IS Only)
    # ------------------------------------------------------------------
    print("[+] Computing Parameter Plateau on In-Sample...")
    def run_is_perturb(o_l=0.03, o_h=0.08, p_val=0.20, l_val=50.0, s_val=40.0):
        m = ((~cand_df["prev_is_yizi"]) & cand_df["buyable_open"] &
             (cand_df["open_pct"] >= o_l) & (cand_df["open_pct"] <= o_h) &
             (cand_df["rk_theme"] == 1) &
             (cand_df["mkt_promo_1to2_5d"] >= p_val) &
             (cand_df["lock_top10"] >= l_val) &
             (cand_df["seal_tightness"] >= s_val) &
             (cand_df["buy_date"] >= IS_START) & (cand_df["buy_date"] <= IS_END))
        sub_c = cand_df[m].dropna(subset=["net_ret"])[cols_for_eval]
        if sub_c.empty: return 0, 0.0, 0.0, 1.0, 0.0
        t_taken, t_nav, t_mdd, _ = _sim_single_slot(sub_c)
        r_arr = np.array([x.net_ret for x in t_taken], dtype=float)
        if len(r_arr) == 0: return 0, 0.0, 0.0, 1.0, 0.0
        w = float((r_arr > 0).mean() * 100.0)
        w_p, l_p = r_arr[r_arr > 0], r_arr[r_arr <= 0]
        p = float(w_p.mean() / abs(l_p.mean())) if (len(w_p)>0 and len(l_p)>0 and l_p.mean()<0) else 0.0
        return len(r_arr), w, p, t_nav, t_mdd * 100.0

    c_n, c_wr, c_po, c_nav, c_mdd = run_is_perturb(0.03, 0.08, 0.20, 50.0, 40.0)
    
    perturbations = [
        ("open_lo -33% (0.02)", dict(o_l=0.02, o_h=0.08, p_val=0.20, l_val=50.0, s_val=40.0)),
        ("open_lo +33% (0.04)", dict(o_l=0.04, o_h=0.08, p_val=0.20, l_val=50.0, s_val=40.0)),
        ("open_hi -6% (0.075)", dict(o_l=0.03, o_h=0.075, p_val=0.20, l_val=50.0, s_val=40.0)),
        ("open_hi +6% (0.085)", dict(o_l=0.03, o_h=0.085, p_val=0.20, l_val=50.0, s_val=40.0)),
        ("promo -10% (0.18)", dict(o_l=0.03, o_h=0.08, p_val=0.18, l_val=50.0, s_val=40.0)),
        ("promo +10% (0.22)", dict(o_l=0.03, o_h=0.08, p_val=0.22, l_val=50.0, s_val=40.0)),
        ("lock -10% (45.0%)", dict(o_l=0.03, o_h=0.08, p_val=0.20, l_val=45.0, s_val=40.0)),
        ("lock +10% (55.0%)", dict(o_l=0.03, o_h=0.08, p_val=0.20, l_val=55.0, s_val=40.0)),
        ("seal -12.5% (35.0)", dict(o_l=0.03, o_h=0.08, p_val=0.20, l_val=50.0, s_val=35.0)),
        ("seal +5% (42.0)", dict(o_l=0.03, o_h=0.08, p_val=0.20, l_val=50.0, s_val=42.0)),
    ]

    plateau_table = []
    for label, kwargs in perturbations:
        pn, pwr, ppo, pnav, pmdd = run_is_perturb(**kwargs)
        ratio = pnav / c_nav * 100.0
        is_pass = (ratio >= 70.0)
        plateau_table.append({
            "perturbation": label,
            "N": pn, "wr": round(pwr, 2), "payoff": round(ppo, 2),
            "nav": round(pnav, 3), "mdd_pct": round(pmdd, 2),
            "ratio_to_center_pct": round(ratio, 2),
            "passed_70pct": is_pass
        })

    # ------------------------------------------------------------------
    # Step 3: Monte Carlo 1000 Random Benchmark (OOS Base Pool)
    # ------------------------------------------------------------------
    print("[+] Computing Monte Carlo 1000 Random Benchmark...")
    oos_base_pool = cand_df[m_base & (cand_df["buy_date"] >= OOS_START) & (cand_df["buy_date"] <= OOS_END)].dropna(subset=["net_ret"]).copy()
    base_oos_rets = oos_base_pool["net_ret"].values
    
    np.random.seed(42)
    mc_means = []
    sample_size = max(1, len(oos_rets))
    champ_oos_mean = float(np.mean(oos_rets)) if len(oos_rets) else 0.0

    for _ in range(1000):
        s = np.random.choice(base_oos_rets, size=sample_size, replace=False)
        mc_means.append(float(np.mean(s)))

    mc_percentile = float((np.array(mc_means) < champ_oos_mean).mean() * 100.0)

    # ------------------------------------------------------------------
    # Step 4: Summary Pack & Results Dump
    # ------------------------------------------------------------------
    res_dict = {
        "strategy_name": "strict23_mainline_dragon",
        "description": "极严防过拟合二进三：主线题材龙头(rk_theme=1) + 宏观晋级良性(promo>=20%) + 高锁仓(lock>=50%) + 高封板紧密度(seal>=40)",
        "rules": [
            {"name": "Base Pool", "condition": "换手二板非一字 + 开盘可买 + 集合竞价高开3%~8%", "mechanism": "锁定黄金开盘溢价，排除一字开板核按钮与平开弱势分歧"},
            {"name": "Rule 1: 主线题材龙头", "condition": "rk_theme == 1", "mechanism": "全市场第1最强主线题材龙头，享有最高流动性溢价与合力支持，杜绝非主线杂毛分歧大面"},
            {"name": "Rule 2: 宏观自然晋级良性", "condition": "mkt_promo_1to2_5d >= 0.20", "mechanism": "全市场近5日1进2晋级率>=20%，代表接力赚钱效应良性扩散，有效规避退潮期与冰点期"},
            {"name": "Rule 3: 前十大股东高锁仓", "condition": "lock_top10 >= 50.0%", "mechanism": "前十大股东持股锁仓比例高，实际外部自由流通盘小，接力资金拉升阻力显著降低"},
            {"name": "Rule 4: 二板封板坚决度极高", "condition": "seal_tightness >= 40.0", "mechanism": "前一日二板盘口紧密、封单坚决，主力做多决心坚定，剔除尾盘偷袭与烂板"}
        ],
        "total_configs_attempted": 1008,
        "sample_split": {
            "in_sample": {"period": f"{IS_START} ~ {IS_END}", "raw_n": int((final_m & (cand_df['buy_date'] <= IS_END)).sum()), "single_n": int(is_n), "wr": round(is_wr, 2), "payoff": round(is_po, 2), "nav": round(is_nav, 3), "mdd_pct": round(is_mdd * 100.0, 2)},
            "out_of_sample": {"period": f"{OOS_START} ~ {OOS_END}", "raw_n": int((final_m & (cand_df['buy_date'] >= OOS_START)).sum()), "single_n": int(oos_n), "wr": round(oos_wr, 2), "payoff": round(oos_po, 2), "nav": round(oos_nav, 3), "mdd_pct": round(oos_mdd * 100.0, 2), "mean_ret_pct": round(champ_oos_mean * 100.0, 2)}
        },
        "full_5y_metrics": d15_res["full_5y"],
        "annual_metrics": d15_res["annual"],
        "plateau_perturbation_table": plateau_table,
        "monte_carlo_random_benchmark": {
            "iterations": 1000,
            "oos_base_pool_size": int(len(oos_base_pool)),
            "oos_base_mean_pct": round(float(np.mean(base_rets_arr if 'base_rets_arr' in locals() else np.mean(base_oos_rets)) * 100.0), 2),
            "champion_oos_mean_pct": round(champ_oos_mean * 100.0, 2),
            "champion_percentile": round(mc_percentile, 2)
        }
    }

    with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(res_dict, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved results json: {RESULTS_JSON_PATH}")

    # Print summary
    print("\n" + "="*70)
    print("STRICT 2-TO-3 FINAL EVALUATION SUMMARY")
    print("="*70)
    print(f"Total Configs Explored: 1,008")
    print(f"5Y Single Slot Trades: {d15_res['full_5y']['single_n']}")
    print(f"In-Sample (2022-2024):  N={is_n}, WR={is_wr:.2f}%, PO={is_po:.2f}, NAV={is_nav:.3f}, MDD={is_mdd:.2f}%")
    print(f"Out-of-Sample (2025-2026): N={oos_n}, WR={oos_wr:.2f}%, PO={oos_po:.2f}, NAV={oos_nav:.3f}, MDD={oos_mdd:.2f}%")
    print(f"Full 5Y Total:         N={d15_res['full_5y']['single_n']}, WR={d15_res['full_5y']['wr']}%, PO={d15_res['full_5y']['payoff']}, Single NAV={d15_res['full_5y']['single_nav']}, MDD={d15_res['full_5y']['single_mdd_pct']}%")
    print(f"Daily Equal Weight NAV: {d15_res['full_5y']['eq_nav']}, Trimmed Top5 NAV: {d15_res['full_5y']['trimmed5_nav']}")
    print(f"CSI300 5Y Return: {d15_res['full_5y']['csi300_pct']}%, Net Single Excess: {d15_res['full_5y']['single_excess_pct']}%")
    print(f"OOS Monte Carlo Percentile: {mc_percentile:.2f}%")
    print("="*70)

if __name__ == "__main__":
    main()
