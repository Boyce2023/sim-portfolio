#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
study12_yizi_open_break_reseal.py
================================================================================
专项回测 12：高分一字开盘炸板接盘与二次回封打板五年全量回测
核心结论：
- 静态底分>=260分档次日一字开盘炸板全接五年胜率仅38.5%，均亏2.79%；
- 二次回封仍有42.9%尾盘再度炸板，均亏1.05%；
- 纳入单仓轮动使净值从124.43倍降至101.31倍，回撤放大至28.5%；
- 决策结论：淘汰禁接。
================================================================================
"""
import os, sys, time, pickle, sqlite3
import numpy as np
import pandas as pd

FEE_RATE = 0.0020
CSI300_5Y_CUM = -0.1784 # 5年沪深300累计收益 -17.84%

print(">>> [1/5] 加载全量历史候选与特征...")
with open("/tmp/astock_hist_fb_preprocessed.pkl", "rb") as fp:
    df = pickle.load(fp)

df = df[(df["d2_dt"] >= "2022-01-01") & (df["d2_dt"] <= "2026-11-10")].copy().reset_index(drop=True)
df["gap_days"] = (pd.to_datetime(df["d2_dt"]) - pd.to_datetime(df["dt_str"])).dt.days
df["c6"] = df["ticker"].astype(str).str[:6]

# 严格只读连接微观盘口
conn_tape = sqlite3.connect("file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
conn_tape.close()
df = df.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

# 严格只读连接机构调研
conn_ir = sqlite3.connect("file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst IS NOT NULL", conn_ir)
conn_ir.close()
ir_grp = ir_df.groupby("sec_code")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()

ir_7d_pit = np.zeros(len(df), dtype=bool)
for idx, (c6, d2) in enumerate(zip(df["c6"], df["d2_dt"])):
    arr = ir_grp.get(c6)
    if arr is not None:
        pos = np.searchsorted(arr, f"{d2} 09:25:00", side="left")
        if pos > 0:
            last_dt = arr[pos - 1][:10]
            if 0 <= (pd.Timestamp(d2) - pd.Timestamp(last_dt)).days <= 8:
                ir_7d_pit[idx] = True
df["has_ir_pit"] = ir_7d_pit

# 计算 V15 盘前静态底分
seal_time = df["first_seal_time"].fillna("99:99:99")
open_cnt = df["open_board_count"].fillna(0)
dd20 = df["f_dd20_d0"].fillna(0.90).values
clean_brk60 = df["clean_brk60"].values == 1

is_granularity = df["is_pioneer_word"] | df["has_new_term"] | df["own_new_term"] | (df["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(df["s_elo"] >= 105.0, 10.0, np.where(df["s_elo"] <= 95.0, -10.0, 0.0))
wk_mask = df["gap_days"] >= 3
f3_bonus = np.where(df["notice_hard"], 8.0, 0.0) + np.where(df["notice_bad"], -35.0, 0.0)

df["s_prior_wk"] = df["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (df["d1_seal_tightness"] >= 38.0)
bon_ht = np.where(is_ht, 5.0, 0.0)
bon_ir = np.where(df["has_ir_pit"], 5.0, 0.0)

df["s_q_base"] = df["s_q_base_dual"] + d_ov + bon_ht + bon_ir
df["static_tot"] = df["s_prior_wk"] + df["s_q_base"]

pass_l1 = (~df["is_event_basket"]) & (~(df["is_broad_ind"] & (df["sub_cluster_cnt"] < 2)))
pass_l2 = ~df["is_dying_pulse"]
pass_ac = ~(df["p_sz"] > 35) & (~df["notice_bad"])
p_tight = df["d1_seal_tightness"] >= 37.0
df["purifier_ok"] = df["gate_ok"] & pass_l1 & pass_l2 & pass_ac & p_tight

print(">>> [2/5] 加载基准日线与分时底座...")
with open("/tmp/v15_cands.pkl", "rb") as fp:
    v15_data = pickle.load(fp)

all_dts = v15_data["all_dts"]
price_lookup = v15_data["price_lookup"]
dt_to_idx = v15_data["dt_to_idx"]
bars_5m_map = v15_data["bars_5m_map"].copy()

# 增量补齐 22 只炸板候选的 5m bars
df_broken_5m = pd.read_parquet("/tmp/yizi_broken_22cands_5m.parquet")
for (c6, dt), grp in df_broken_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

print(f"分时轨迹总数: {len(bars_5m_map):,} 个 (股票, 交易日)")

# ==============================================================================
# 5m 分时离场引擎（严格按 boards_held 控制免死与均线卖点）
# ==============================================================================
def simulate_holding_chain(c6, buy_px, start_idx, init_boards_held, name=""):
    curr = start_idx
    boards_held = init_boards_held
    used_immunity = False
    
    prev_bar = price_lookup.get((c6, all_dts[curr - 1]))
    prev_c = round(float(prev_bar[3]), 2) if prev_bar else buy_px

    while curr < len(all_dts) and (curr - start_idx <= 12):
        dc = all_dts[curr]
        b = price_lookup.get((c6, dc))
        if not b: break
        # unpack 8 elements or 9 elements safely
        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b[:8]
        if iyzc:
            prev_c = round(float(cc), 2); curr += 1; continue

        arr = bars_5m_map.get((c6, dc))
        if arr is not None and len(arr) >= 12:
            idx_1030 = -1
            cum_v, cum_a = 0.0, 0.0
            for bi in range(len(arr)):
                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                if arr[bi, 0] == 1030:
                    idx_1030 = bi; break
            if idx_1030 >= 0:
                bc_1030 = arr[idx_1030, 4]
                vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                # 分支 A: 10:30 封板，洗盘不动，14:30 炸板抢跑
                if bc_1030 >= ztc - 0.01:
                    for bi in range(idx_1030 + 1, len(arr) - 1):
                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                            px = round(float(arr[bi + 1, 1]), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush"}
                    if iztc:
                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    else:
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "eod_break"}
                # 分支 B: 10:30 未封板且破均线 -> 10:35 开盘立即全卖离场
                elif bc_1030 < vwap_1030:
                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                # 分支 C: 10:30 站上均线 -> 拿至收盘
                else:
                    if iztc:
                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                    px = round(float(cc), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

        # 基础收盘模式
        if iztc:
            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
        px = round(float(cc), 2)
        return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}

    return {"net_ret": round((prev_c / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": prev_c, "tag": "max_hold"}

# ==============================================================================
# 单笔交易仿真器 (处理 D2 炸板买入与离场)
# ==============================================================================
def sim_yizi_broken_trade(c6, d2, buy_px, is_zt2, name=""):
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 >= len(all_dts) - 1:
        return None
    d2_bar = price_lookup.get((c6, d2))
    if not d2_bar: return None
    o2, h2, l2, c2, zt2, dt2, _, _ = d2_bar[:8]

    prev_c = round(float(c2), 2)
    idx3 = idx2 + 1
    d3 = all_dts[idx3]
    d3_bar = price_lookup.get((c6, d3))
    if not d3_bar:
        net = round((prev_c / buy_px) * (1.0 - FEE_RATE) - 1.0, 4)
        return {"net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": prev_c, "tag": "no_d3_bar"}
    o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar[:8]

    # 分支 1：买入日未封板 (not is_zt2)
    if not is_zt2:
        d1_bar = price_lookup.get((c6, all_dts[idx2 - 1])) if idx2 > 0 else None
        d1_c = d1_bar[3] if d1_bar else buy_px / 1.10
        d2_closed_up = (c2 >= float(d1_c))
        passes_nshape = d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3
        if passes_nshape:
            if is_zt3:
                res = simulate_holding_chain(c6, buy_px, idx3 + 1, 3, name)
                res.update({"sealed_2b": 0, "buy_date": d2})
                return res
            else:
                px = round(float(c3), 2)
                return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "nshape_d3_close"}
        # 未满足弱转强: D3 09:25 开盘全卖
        curr = idx3
        while curr < len(all_dts):
            b = price_lookup.get((c6, all_dts[curr]))
            if not b or not b[7]:
                px = round(float(b[0]), 2) if b else prev_c
                return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "fail_open_cut"}
            curr += 1
        return None

    # 分支 2：买入日封死二板 (sealed_2b == 1)
    res = simulate_holding_chain(c6, buy_px, idx3, 2, name)
    res.update({"sealed_2b": 1, "buy_date": d2})
    return res

# 原始 V15 候选的交易模拟器
def sim_v15_cand(row):
    c6, d2 = row["c6"], row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 >= len(all_dts) - 1:
        return None
    d2_bar = price_lookup.get((c6, d2))
    if not d2_bar: return None
    o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar[:8]
    if o2 >= zt2 - 0.005 or o2 <= 0:
        return None
    is_monday = row.get("gap_days", 1) >= 3
    cand_score = row.get("score_active", row.get("score_0", 0.0))
    cand_lead = row.get("buy_open_lead", 0.0)
    do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
    buy_px = round(float(o2), 2) if do_direct else round(float(row["trig_p"]), 2)
    if (not do_direct) and (h2 < float(row["trig_p"]) or float(row["trig_p"]) >= zt2 - 0.005):
        return None

    prev_c = round(float(c2), 2)
    idx3 = idx2 + 1
    d3 = all_dts[idx3]
    d3_bar = price_lookup.get((c6, d3))
    if not d3_bar:
        net = round((prev_c / buy_px) * (1.0 - FEE_RATE) - 1.0, 4)
        return {"net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c, "tag": "no_d3_bar"}
    o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar[:8]

    if not is_zt2:
        d2_closed_up = (c2 >= float(row["close"]))
        passes_nshape = d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3
        if passes_nshape:
            if is_zt3:
                res = simulate_holding_chain(c6, buy_px, idx3 + 1, 3, row["name"])
                res.update({"sealed_2b": 0, "buy_date": d2})
                return res
            else:
                px = round(float(c3), 2)
                return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "nshape_d3_close"}
        curr = idx3
        while curr < len(all_dts):
            b = price_lookup.get((c6, all_dts[curr]))
            if not b or not b[7]:
                px = round(float(b[0]), 2) if b else prev_c
                return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "fail_open_cut"}
            curr += 1
        return None

    res = simulate_holding_chain(c6, buy_px, idx3, 2, row["name"])
    res.update({"sealed_2b": 1, "buy_date": d2})
    return res

# 检验 V15 原版基准
cands_v15_orig = v15_data["cands_df"].copy()
v15_trades_map = {}
for _, row in cands_v15_orig.iterrows():
    tr = sim_v15_cand(row)
    if tr is not None:
        v15_trades_map[(row["c6"], row["d2_dt"])] = tr

def run_rotation_sim(trades_dict, cands_grouped):
    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    trades_1s = []
    
    for d2, cands in cands_grouped:
        if not cands: continue
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            best_c6 = cands[0][0]
            tr = trades_dict.get((best_c6, d2))
            if tr is not None:
                nav_1s *= (1.0 + tr["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr["exit_date"], tr["exit_at_open"]
                trades_1s.append(tr)
                
    tot = len(trades_1s)
    if tot == 0:
        return {"trades": 0, "nav": 1.0, "mdd": 0.0, "wr": 0.0, "payoff": 0.0, "avg_ret": 0.0, "trades_list": []}
    rets = [t["net_ret"] for t in trades_1s]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    wr = len(wins) / tot
    avg_w = np.mean(wins) if wins else 0.0
    avg_l = abs(np.mean(losses)) if losses else 1e-4
    payoff = avg_w / avg_l if avg_l > 0 else 0.0
    return {
        "trades": tot, "nav": nav_1s, "mdd": mdd_1s,
        "wr": wr, "payoff": payoff, "avg_ret": np.mean(rets),
        "trades_list": trades_1s
    }

v15_grouped = []
for d2, grp in cands_v15_orig.sort_values(["d2_dt", "_sv_eval"], ascending=[True, False]).groupby("d2_dt", sort=True):
    v15_grouped.append((d2, list(zip(grp["c6"], grp["_sv_eval"]))))

base_v15 = run_rotation_sim(v15_trades_map, v15_grouped)
print(f"✅ V15 基准检验: 笔数={base_v15['trades']}, 净值={base_v15['nav']:.2f}x, 最大回撤={base_v15['mdd']*100:.1f}%, 胜率={base_v15['wr']*100:.1f}%, 盈亏比={base_v15['payoff']:.2f}")

print("\n" + "=" * 90)
print(">>> [4/5] 统计三大分段 (>=240, >=260, >=280) 下动作1与动作2真实样本...")
print("=" * 90)

# 检验 5 分钟线二次触及涨停
def check_5m_reseal(c6, d2, zt_p):
    sub = df_broken_5m[(df_broken_5m["c6"] == c6) & (df_broken_5m["date"] == d2)].sort_values("hhmm").reset_index(drop=True)
    if len(sub) == 0:
        return False, False, 0, 0.0
    first_break_idx = -1
    for i, r in sub.iterrows():
        if r["low"] < zt_p - 0.005:
            first_break_idx = i
            break
    if first_break_idx < 0:
        return False, False, 0, 0.0
    
    re_touch = False
    re_touch_time = 0
    for j in range(first_break_idx + 1, len(sub)):
        if sub.iloc[j]["high"] >= zt_p - 0.005:
            re_touch = True
            re_touch_time = int(sub.iloc[j]["hhmm"])
            break
            
    final_close = sub.iloc[-1]["close"]
    is_resealed = final_close >= zt_p - 0.005
    return re_touch, is_resealed, re_touch_time, final_close

# 运行三大门槛全量统计
results_all = {}

for mode_name, is_exact in [("严格 open==zt_p", True), ("宽松 open>=zt_p-0.01", False)]:
    print(f"\n====================== 统计口径: {mode_name} ======================")
    results_all[mode_name] = {}
    
    for th in [240, 260, 280]:
        if is_exact:
            cond_yizi = df["purifier_ok"] & (df["d2_open"] >= df["d2_zt_p"] - 0.005) & (df["static_tot"] >= th)
            cond_broken = cond_yizi & (df["d2_low"] < df["d2_zt_p"] - 0.005)
        else:
            cond_yizi = df["purifier_ok"] & (df["d2_open"] >= df["d2_zt_p"] - 0.01) & (df["static_tot"] >= th)
            cond_broken = cond_yizi & (df["d2_low"] < df["d2_zt_p"] - 0.01)
            
        sub_yizi = df[cond_yizi].copy()
        sub_broken = df[cond_broken].copy()
        
        n_total = len(sub_yizi)
        n_sealed = n_total - len(sub_broken)
        n_broken = len(sub_broken)
        
        # 动作 1 逐笔模拟
        act1_trades = []
        for _, r in sub_broken.iterrows():
            c6, d2, name = r["c6"], r["d2_dt"], r["name"]
            zt_p = r["d2_zt_p"]
            is_zt2 = r["d2_close"] >= r["d2_zt_p"] - 0.005
            tr = sim_yizi_broken_trade(c6, d2, zt_p, is_zt2, name)
            if tr:
                tr["static_tot"] = r["static_tot"]
                tr["is_zt2"] = is_zt2
                tr["d2_close"] = r["d2_close"]
                tr["d2_low"] = r["d2_low"]
                act1_trades.append(tr)
                
        # 动作 2 逐笔模拟 (5m线检验二次触板)
        act2_trades = []
        for _, r in sub_broken.iterrows():
            c6, d2, name = r["c6"], r["d2_dt"], r["name"]
            zt_p = r["d2_zt_p"]
            re_touch, is_resealed, re_time, final_c = check_5m_reseal(c6, d2, zt_p)
            if re_touch:
                # 触发打板买入
                tr = sim_yizi_broken_trade(c6, d2, zt_p, is_resealed, name)
                if tr:
                    tr["static_tot"] = r["static_tot"]
                    tr["is_zt2"] = is_resealed
                    tr["re_time"] = re_time
                    tr["re_broken"] = (not is_resealed)
                    tr["d2_close"] = final_c
                    act2_trades.append(tr)
                    
        # 统计动作 1
        rets_a1 = [t["net_ret"] for t in act1_trades]
        w_a1 = [r for r in rets_a1 if r > 0]
        l_a1 = [r for r in rets_a1 if r < 0]
        wr_a1_5y = len(w_a1) / len(rets_a1) if rets_a1 else 0.0
        avg_a1_5y = np.mean(rets_a1) if rets_a1 else 0.0
        payoff_a1_5y = (np.mean(w_a1) / abs(np.mean(l_a1))) if w_a1 and l_a1 else 0.0
        reseal_rate_a1 = sum(t["is_zt2"] for t in act1_trades) / len(act1_trades) if act1_trades else 0.0
        
        # 近3年 (2024-01-01 起)
        t_a1_3y = [t for t in act1_trades if t["buy_date"] >= "2024-01-01"]
        w_a1_3y = [t["net_ret"] for t in t_a1_3y if t["net_ret"] > 0]
        l_a1_3y = [t["net_ret"] for t in t_a1_3y if t["net_ret"] < 0]
        wr_a1_3y = len(w_a1_3y) / len(t_a1_3y) if t_a1_3y else 0.0
        avg_a1_3y = np.mean([t["net_ret"] for t in t_a1_3y]) if t_a1_3y else 0.0
        payoff_a1_3y = (np.mean(w_a1_3y) / abs(np.mean(l_a1_3y))) if w_a1_3y and l_a1_3y else 0.0
        
        # 2026年 (2026-01-01 起)
        t_a1_26 = [t for t in act1_trades if t["buy_date"] >= "2026-01-01"]
        w_a1_26 = [t["net_ret"] for t in t_a1_26 if t["net_ret"] > 0]
        l_a1_26 = [t["net_ret"] for t in t_a1_26 if t["net_ret"] < 0]
        wr_a1_26 = len(w_a1_26) / len(t_a1_26) if t_a1_26 else 0.0
        avg_a1_26 = np.mean([t["net_ret"] for t in t_a1_26]) if t_a1_26 else 0.0
        payoff_a1_26 = (np.mean(w_a1_26) / abs(np.mean(l_a1_26))) if w_a1_26 and l_a1_26 else 0.0
        
        # 统计动作 2
        rets_a2 = [t["net_ret"] for t in act2_trades]
        w_a2 = [r for r in rets_a2 if r > 0]
        l_a2 = [r for r in rets_a2 if r < 0]
        wr_a2_5y = len(w_a2) / len(rets_a2) if rets_a2 else 0.0
        avg_a2_5y = np.mean(rets_a2) if rets_a2 else 0.0
        payoff_a2_5y = (np.mean(w_a2) / abs(np.mean(l_a2))) if w_a2 and l_a2 else 0.0
        re_broken_rate = sum(t["re_broken"] for t in act2_trades) / len(act2_trades) if act2_trades else 0.0
        
        t_a2_3y = [t for t in act2_trades if t["buy_date"] >= "2024-01-01"]
        w_a2_3y = [t["net_ret"] for t in t_a2_3y if t["net_ret"] > 0]
        l_a2_3y = [t["net_ret"] for t in t_a2_3y if t["net_ret"] < 0]
        wr_a2_3y = len(w_a2_3y) / len(t_a2_3y) if t_a2_3y else 0.0
        avg_a2_3y = np.mean([t["net_ret"] for t in t_a2_3y]) if t_a2_3y else 0.0
        
        t_a2_26 = [t for t in act2_trades if t["buy_date"] >= "2026-01-01"]
        w_a2_26 = [t["net_ret"] for t in t_a2_26 if t["net_ret"] > 0]
        l_a2_26 = [t["net_ret"] for t in t_a2_26 if t["net_ret"] < 0]
        wr_a2_26 = len(w_a2_26) / len(t_a2_26) if t_a2_26 else 0.0
        avg_a2_26 = np.mean([t["net_ret"] for t in t_a2_26]) if t_a2_26 else 0.0

        # ======================================================================
        # 叠加进 V15 单仓满仓轮动测试
        # ======================================================================
        # 1. 动作 1 叠加进 V15:
        # 组合候选池: V15 候选 + 动作1 炸板候选
        combo1_trades_map = v15_trades_map.copy()
        for t in act1_trades:
            combo1_trades_map[(t["c6"], t["buy_date"])] = t
            
        # 策略 A: 评分并列排位 (按 _sv_eval 或 static_tot+1000)
        # 策略 B: 严格优先原版 V15 候选，若当日有空位才接一字炸板
        all_d2_set = sorted(set(list(cands_v15_orig["d2_dt"].unique()) + [t["buy_date"] for t in act1_trades]))
        grouped_combo1_score = []
        grouped_combo1_v15_prio = []
        
        v15_by_date = {d: list(grp[["c6", "_sv_eval"]].itertuples(index=False)) for d, grp in cands_v15_orig.groupby("d2_dt")}
        act1_by_date = {}
        for t in act1_trades:
            act1_by_date.setdefault(t["buy_date"], []).append((t["c6"], t["static_tot"] + 1000.0))
            
        for d in all_d2_set:
            v_list = v15_by_date.get(d, [])
            a_list = act1_by_date.get(d, [])
            # 方案 A: 统一按分数降序
            tot_list_a = sorted(v_list + a_list, key=lambda x: x[1], reverse=True)
            grouped_combo1_score.append((d, tot_list_a))
            # 方案 B: V15 优先，炸板排后
            tot_list_b = sorted(v_list, key=lambda x: x[1], reverse=True) + sorted(a_list, key=lambda x: x[1], reverse=True)
            grouped_combo1_v15_prio.append((d, tot_list_b))
            
        sim_v15_plus_a1_score = run_rotation_sim(combo1_trades_map, grouped_combo1_score)
        sim_v15_plus_a1_prio = run_rotation_sim(combo1_trades_map, grouped_combo1_v15_prio)

        # 2. 动作 2 叠加进 V15:
        combo2_trades_map = v15_trades_map.copy()
        for t in act2_trades:
            combo2_trades_map[(t["c6"], t["buy_date"])] = t
            
        act2_by_date = {}
        for t in act2_trades:
            act2_by_date.setdefault(t["buy_date"], []).append((t["c6"], t["static_tot"] + 1000.0))
            
        grouped_combo2_score = []
        grouped_combo2_v15_prio = []
        for d in all_d2_set:
            v_list = v15_by_date.get(d, [])
            a_list = act2_by_date.get(d, [])
            tot_list_a = sorted(v_list + a_list, key=lambda x: x[1], reverse=True)
            grouped_combo2_score.append((d, tot_list_a))
            tot_list_b = sorted(v_list, key=lambda x: x[1], reverse=True) + sorted(a_list, key=lambda x: x[1], reverse=True)
            grouped_combo2_v15_prio.append((d, tot_list_b))
            
        sim_v15_plus_a2_score = run_rotation_sim(combo2_trades_map, grouped_combo2_score)
        sim_v15_plus_a2_prio = run_rotation_sim(combo2_trades_map, grouped_combo2_v15_prio)

        results_all[mode_name][th] = {
            "n_total": n_total, "n_sealed": n_sealed, "n_broken": n_broken,
            # 动作 1
            "act1_n": len(act1_trades),
            "reseal_rate_a1": reseal_rate_a1,
            "wr_a1_5y": wr_a1_5y, "avg_a1_5y": avg_a1_5y, "payoff_a1_5y": payoff_a1_5y,
            "wr_a1_3y": wr_a1_3y, "avg_a1_3y": avg_a1_3y, "payoff_a1_3y": payoff_a1_3y,
            "wr_a1_26": wr_a1_26, "avg_a1_26": avg_a1_26, "payoff_a1_26": payoff_a1_26,
            "v15_plus_a1_score": sim_v15_plus_a1_score,
            "v15_plus_a1_prio": sim_v15_plus_a1_prio,
            "act1_trades": act1_trades,
            # 动作 2
            "act2_n": len(act2_trades),
            "re_broken_rate": re_broken_rate,
            "wr_a2_5y": wr_a2_5y, "avg_a2_5y": avg_a2_5y, "payoff_a2_5y": payoff_a2_5y,
            "wr_a2_3y": wr_a2_3y, "avg_a2_3y": avg_a2_3y,
            "wr_a2_26": wr_a2_26, "avg_a2_26": avg_a2_26,
            "v15_plus_a2_score": sim_v15_plus_a2_score,
            "v15_plus_a2_prio": sim_v15_plus_a2_prio,
            "act2_trades": act2_trades,
        }

        print(f"门槛 >= {th}: 一字总数={n_total:2d} | 封死未给机会={n_sealed:2d} | 炸板可买={n_broken:2d}")
        print(f"  【动作1 炸板排板全接】(n={len(act1_trades)}): 当日回封率={reseal_rate_a1*100:4.1f}% | 5年胜率={wr_a1_5y*100:4.1f}% 均盈亏={avg_a1_5y*100:+5.2f}% 盈亏比={payoff_a1_5y:4.2f} | 近3年胜率={wr_a1_3y*100:4.1f}% 均盈亏={avg_a1_3y*100:+5.2f}% | 2026胜率={wr_a1_26*100:4.1f}% 均盈亏={avg_a1_26*100:+5.2f}%")
        print(f"     -> 叠加V15(评分优先): 笔数={sim_v15_plus_a1_score['trades']}, 净值={sim_v15_plus_a1_score['nav']:.2f}x (基线 {base_v15['nav']:.2f}x), 回撤={sim_v15_plus_a1_score['mdd']*100:.1f}% (基线 {base_v15['mdd']*100:.1f}%), 超额={sim_v15_plus_a1_score['nav']-(1.0+CSI300_5Y_CUM):+.2f}x")
        print(f"     -> 叠加V15(原版优先): 笔数={sim_v15_plus_a1_prio['trades']}, 净值={sim_v15_plus_a1_prio['nav']:.2f}x (基线 {base_v15['nav']:.2f}x), 回撤={sim_v15_plus_a1_prio['mdd']*100:.1f}% (基线 {base_v15['mdd']*100:.1f}%), 超额={sim_v15_plus_a1_prio['nav']-(1.0+CSI300_5Y_CUM):+.2f}x")
        print(f"  【动作2 5m二次回封打板】(n={len(act2_trades)}): 尾盘再炸率={re_broken_rate*100:4.1f}% | 5年胜率={wr_a2_5y*100:4.1f}% 均盈亏={avg_a2_5y*100:+5.2f}% 盈亏比={payoff_a2_5y:4.2f} | 近3年胜率={wr_a2_3y*100:4.1f}% 均盈亏={avg_a2_3y*100:+5.2f}% | 2026胜率={wr_a2_26*100:4.1f}% 均盈亏={avg_a2_26*100:+5.2f}%")
        print(f"     -> 叠加V15(评分优先): 笔数={sim_v15_plus_a2_score['trades']}, 净值={sim_v15_plus_a2_score['nav']:.2f}x, 回撤={sim_v15_plus_a2_score['mdd']*100:.1f}%")
        print(f"     -> 叠加V15(原版优先): 笔数={sim_v15_plus_a2_prio['trades']}, 净值={sim_v15_plus_a2_prio['nav']:.2f}x, 回撤={sim_v15_plus_a2_prio['mdd']*100:.1f}%")

with open("/tmp/yizi_highscore_study_results.pkl", "wb") as fp:
    pickle.dump({"results_all": results_all, "base_v15": base_v15}, fp)
print("\n>>> 数据计算完成并保存至 /tmp/yizi_highscore_study_results.pkl")
