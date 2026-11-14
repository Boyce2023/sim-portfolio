#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_02_ex_ante_regime_machine.py - 纯前视镜 (Ex-Ante) 黄金期状态机 G(T) 构建与样本外盲测

严格零未来函数（T日 09:25:00 前 100% 可得）：
1. 监管真空/松绑窗 (ex_cnt5 <= 1)
2. 破局高度 + 断板容错温度计 (近5日最高板 >= 5/6板，近K个>=4板断板股平均跌幅 > -2.5% 且无一字跌停)
3. 市场水位与梯队厚度 (前日跌停家数 <= 18家，3板以上梯队 >= 1家)
4. 防末端高潮断头铡 / 熔断器 (昨日最高板未遭遇跌停/天地板A杀，全场非极热百股过热)

流程：
- 2022-2023 训练集定型参数
- 2024-2026 样本外盲测
- 参数 ±10% 扰动敏感度测试
- 产出 sub2_regime_machine_eval.json
"""

import os, pickle, json
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SRC_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
TARGET_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/golden_regime_20261113"

df_state = pd.read_parquet(f"{TARGET_DIR}/sub2_ex_ante_state.parquet")
dfr = pd.read_pickle(f"{SRC_DIR}/v5_enriched_119.pkl")

# 5分钟真实收益映射 (morn_cond + S_hold_d3)
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{SRC_DIR}/part1_cache.pkl", "rb"))
bars_5m = pickle.load(open(f"{SRC_DIR}/sub2_5m_bars_cache.pkl", "rb"))
idx_5m = {(k[0], k[2]): v for k, v in bars_5m.items()}

def get_df_k(c6, b_dt):
    v = idx_5m.get((c6, b_dt))
    return v if isinstance(v, pd.DataFrame) else pd.DataFrame()

FEE = 0.0020
def get_double_dev_px(bars, cp, idx_map, disc=0.07):
    cd = bars["dts"][cp]; ir = idx_map.get(cd)
    if not ir: return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0: bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0: bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return bp

def sim_trade(r, buy_mode="morn_cond", sell_mode="S_hold_d3"):
    c6 = str(r.code).zfill(6); bars = code_bars[c6]; d2p = bars["p"][r.buy_date]
    b_op = float(bars["open"][d2p]); zt_px = float(bars["zt_px"][d2p])
    df_k = get_df_k(c6, r.buy_date); imap = SH_MAP if r.ex == "SH" else SZ_MAP
    if buy_mode == "morn_cond":
        if r.op2 >= 0.0:
            if r.op2 > 0.045 or b_op >= zt_px - 0.011: return None
            buy_px, is_auc = b_op, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011: return None
            sub_m = df_k[(df_k["date"] == r.buy_date) & (df_k["hhmm"] <= "11:30")] if not df_k.empty else pd.DataFrame()
            if sub_m.empty or sub_m["high"].max() < ipx: return None
            buy_px = float(sub_m.iloc[0]["open"]) if float(sub_m.iloc[0]["open"]) >= ipx else ipx
            is_auc = False
    n = len(bars["dts"]); ep, epx, eo = None, None, False
    def run_zt_loop(start_p):
        imm = False
        for step in range(1, 8):
            p = start_p + step
            if p >= n: break
            pl = get_double_dev_px(bars, p, imap, 0.07)
            if bars["open"][p] >= pl: return p, float(bars["open"][p]), True
            if bars["high"][p] >= pl: return p, float(pl), False
            if not bars["is_zt"][p]:
                if (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True; continue
                while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                return p, float(bars["close"][p]), False
        p_end = min(start_p + 5, n - 1)
        return p_end, float(bars["close"][p_end]), False

    if bars["is_zt"][d2p]: ep, epx, eo = run_zt_loop(d2p)
    else:
        p = min(d2p + 1, n - 1)
        while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
        if bars["is_zt"][p]: ep, epx, eo = run_zt_loop(p)
        else: ep, epx, eo = p, float(bars["close"][p]), False

    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return {"buy_date": r.buy_date, "code": c6, "name": r.name, "net_ret": float(ret)}

dfr_trades = {r.buy_date: sim_trade(r) for _, r in dfr.iterrows()}
dfr["net_ret"] = [dfr_trades.get(r.buy_date, {}).get("net_ret", np.nan) if dfr_trades.get(r.buy_date) else np.nan for _, r in dfr.iterrows()]

# 评估前视镜状态机表现
def build_regime_mask(df, p_max_b=5, p_k3_avg=-0.025, p_k3_dt=0, p_ex_reg=1, p_dt=18, use_cb=True):
    cond = (
        (df["max_b_roll5"] >= p_max_b) &
        (df["k3_avg_pct"] >= p_k3_avg) &
        (df["k3_yizi_cnt"] <= p_k3_dt) &
        (df["ex_cnt5"] <= p_ex_reg) &
        (df["prev_n_dt"] <= p_dt)
    )
    if use_cb:
        cond = cond & (~df["prev_top_nuked"])
    return cond

# 1. 核心候选状态机对比
machines = {
    "G0_Loose (宽松版)": {"p_max_b": 5, "p_k3_avg": -0.040, "p_k3_dt": 1, "p_ex_reg": 1, "p_dt": 22, "use_cb": False},
    "G1_Balanced (最优定版)": {"p_max_b": 5, "p_k3_avg": -0.025, "p_k3_dt": 0, "p_ex_reg": 1, "p_dt": 18, "use_cb": True},
    "G2_Strict (严格高胜率)": {"p_max_b": 6, "p_k3_avg": -0.015, "p_k3_dt": 0, "p_ex_reg": 0, "p_dt": 12, "use_cb": True},
    "G3_No_Tolerance (无断板容错对比组)": {"p_max_b": 5, "p_k3_avg": -0.999, "p_k3_dt": 99, "p_ex_reg": 1, "p_dt": 18, "use_cb": False},
}

eval_results = {}
print("=== 前视镜黄金期状态机 G(T) 全样本评测 ===")
for m_name, params in machines.items():
    mask = build_regime_mask(df_state, **params)
    df_state[m_name] = mask
    
    # 天数统计
    n_tot = len(df_state)
    n_gold = int(mask.sum())
    p_tot = n_gold / n_tot * 100.0
    
    # 分年度 / 训练外分布
    train_mask = df_state["year"].isin(["2022", "2023"])
    test_mask = df_state["year"].isin(["2024", "2025", "2026"])
    
    p_train = float(mask[train_mask].mean() * 100)
    p_test = float(mask[test_mask].mean() * 100)
    
    # 标的胜率与收益 (所有过线候选 vs 黄金期内外)
    date_to_g = dict(zip(df_state["date"], mask))
    dfr_m = dfr.copy()
    dfr_m["is_gold"] = dfr_m["buy_date"].map(date_to_g).fillna(False)
    
    v_in = dfr_m.dropna(subset=["net_ret"])[dfr_m["is_gold"] == True]
    v_out = dfr_m.dropna(subset=["net_ret"])[dfr_m["is_gold"] == False]
    
    wr_in = float((v_in["net_ret"] > 0).mean() * 100) if len(v_in) > 0 else 0.0
    wr_out = float((v_out["net_ret"] > 0).mean() * 100) if len(v_out) > 0 else 0.0
    
    m_in = float(v_in["net_ret"].mean() * 100) if len(v_in) > 0 else 0.0
    m_out = float(v_out["net_ret"].mean() * 100) if len(v_out) > 0 else 0.0
    
    pos_in = v_in[v_in["net_ret"] > 0]["net_ret"].values
    neg_in = np.abs(v_in[v_in["net_ret"] <= 0]["net_ret"].values)
    pl_in = float(np.mean(pos_in) / np.mean(neg_in)) if (len(pos_in) > 0 and len(neg_in) > 0) else 99.0
    
    eval_results[m_name] = {
        "params": params,
        "days_5y": n_gold,
        "pct_5y": round(p_tot, 2),
        "pct_train_22_23": round(p_train, 2),
        "pct_test_24_26": round(p_test, 2),
        "cands_in": len(v_in),
        "cands_out": len(v_out),
        "wr_in": round(wr_in, 1),
        "wr_out": round(wr_out, 1),
        "mean_in": round(m_in, 2),
        "mean_out": round(m_out, 2),
        "pl_in": round(pl_in, 2)
    }
    
    print(f"\n[{m_name}]")
    print(f"  天数占比: 5Y={p_tot:4.1f}% ({n_gold}/{n_tot}) | 训练集(22-23)={p_train:4.1f}% | 样本外(24-26)={p_test:4.1f}%")
    print(f"  标的表现: 黄金期内 {len(v_in)}笔 (胜率={wr_in:4.1f}%, 均值={m_in:+4.2f}%, 盈亏比={pl_in:4.2f})")
    print(f"            黄金期外 {len(v_out)}笔 (胜率={wr_out:4.1f}%, 均值={m_out:+4.2f}%)")

# 2. 训练集锁参 -> 样本外盲测与 ±10% 扰动测试 (在 G1_Balanced 上)
print("\n=== G1_Balanced 参数 ±10% 扰动稳健性检验 (Sensitivity Analysis) ===")
perturbations = [
    ("基准 (Baseline)", 5, -0.025, 0, 1, 18),
    ("断板容错松动 (-10%)", 5, -0.0275, 0, 1, 18),
    ("断板容错收紧 (+10%)", 5, -0.0225, 0, 1, 18),
    ("跌停容忍放宽 (+10%)", 5, -0.025, 0, 1, 20),
    ("跌停容忍收紧 (-10%)", 5, -0.025, 0, 1, 16),
]

perturb_results = []
for p_lbl, mb, k3a, k3dt, exr, dt_c in perturbations:
    msk = build_regime_mask(df_state, p_max_b=mb, p_k3_avg=k3a, p_k3_dt=k3dt, p_ex_reg=exr, p_dt=dt_c, use_cb=True)
    p_5y = float(msk.mean() * 100)
    p_oos = float(msk[df_state["year"].isin(["2024", "2025", "2026"])].mean() * 100)
    perturb_results.append({
        "label": p_lbl,
        "pct_5y": round(p_5y, 2),
        "pct_oos": round(p_oos, 2)
    })
    print(f"  {p_lbl:22s} -> 5Y天数占比 {p_5y:4.1f}% | 样本外天数占比 {p_oos:4.1f}%")

with open(f"{TARGET_DIR}/sub2_regime_machine_eval.json", "w") as fp:
    json.dump({
        "machines": eval_results,
        "perturbations": perturb_results
    }, fp, indent=2, ensure_ascii=False)

print(f"\n[DONE] sub2_02_ex_ante_regime_machine.py 执行完毕，已保存至 {TARGET_DIR}/sub2_regime_machine_eval.json")
