#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, sys, pickle, sqlite3
import numpy as np
import pandas as pd

FEE_RATE = 0.0020
CSI300_5Y = -0.1784
CSI300_3Y = 0.0912
CSI300_1Y = -0.1280
CSI300_JUL = -0.1850

with open("/tmp/astock_hist_fb_preprocessed.pkl", "rb") as fp:
    df = pickle.load(fp)

df = df[(df["d2_dt"] >= "2022-01-01") & (df["d2_dt"] <= "2026-11-10")].copy().reset_index(drop=True)
df["gap_days"] = (pd.to_datetime(df["d2_dt"]) - pd.to_datetime(df["dt_str"])).dt.days
df["c6"] = df["ticker"].astype(str).str[:6]

conn_tape = sqlite3.connect("file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
tape_df = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape", conn_tape)
conn_tape.close()
df = df.merge(tape_df.drop_duplicates(["trade_date", "sec_code"]), left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left")

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

seal_time = df["first_seal_time"].fillna("99:99:99")
open_cnt = df["open_board_count"].fillna(0)
dd20 = df["f_dd20_d0"].fillna(0.90).values
clean_brk60 = df["clean_brk60"].values == 1

is_granularity = df["is_pioneer_word"] | df["has_new_term"] | df["own_new_term"] | (df["sub_cluster_cnt"] >= 2)
bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(df["s_elo"] >= 105.0, 10.0, np.where(df["s_elo"] <= 95.0, -10.0, 0.0))
wk_mask = df["gap_days"] >= 3
f3_bonus = np.where(df["notice_hard"], 8.0, 0.0) + np.where(df["notice_bad"], -35.0, 0.0)

# V16 纯外行减20分
CSRC_PATH_PREF = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/csrc_industry_l2.csv"
CSRC_PATH_BACKUP = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-10-15-review2022/industry.csv"
csrc_file = CSRC_PATH_PREF if os.path.exists(CSRC_PATH_PREF) else CSRC_PATH_BACKUP
ind_df = pd.read_csv(csrc_file)
ind_df["c6"] = ind_df["code"].astype(str).str[-6:]
ind_map = dict(zip(ind_df["c6"], ind_df["industry"].fillna("")))
df["csrc_ind"] = df["c6"].map(ind_map).fillna("")
csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in df["csrc_ind"]]
CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05","D44","D45","D46","E47","E48","E49","E50",
    "F51","F52","G53","G54","G55","G56","G58","G59","H61","H62","K70","L72","N77","N78",
    "C13","C14","C15","C17","C18","C19","C20","C21","C22"
}
is_hard_tech = df["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
has_ma_hard = (df["notice_hard"] | df["is_ma"]).values
is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)
name_sub20 = np.where(is_pure_outsider, -20.0, 0.0)

df["s_prior_v16"] = df["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus + name_sub20
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)
is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (df["d1_seal_tightness"] >= 38.0)
bon_ht = np.where(is_ht, 5.0, 0.0)
bon_ir = np.where(df["has_ir_pit"], 5.0, 0.0)

df["s_q_base"] = df["s_q_base_dual"] + d_ov + bon_ht + bon_ir
df["static_v16"] = df["s_prior_v16"] + df["s_q_base"]

pass_l1 = (~df["is_event_basket"]) & (~(df["is_broad_ind"] & (df["sub_cluster_cnt"] < 2)))
pass_l2 = ~df["is_dying_pulse"]
pass_ac = ~(df["p_sz"] > 35) & (~df["notice_bad"])
p_tight = df["d1_seal_tightness"] >= 37.0
df["purifier_ok"] = df["gate_ok"] & pass_l1 & pass_l2 & pass_ac & p_tight

with open("/tmp/v15_cands.pkl", "rb") as fp:
    v15_data = pickle.load(fp)
all_dts = v15_data["all_dts"]
price_lookup = v15_data["price_lookup"]
dt_to_idx = v15_data["dt_to_idx"]
bars_5m_map = v15_data["bars_5m_map"].copy()
if os.path.exists("/tmp/yizi_broken_22cands_5m.parquet"):
    df_broken_5m = pd.read_parquet("/tmp/yizi_broken_22cands_5m.parquet")
    for (c6, dt), grp in df_broken_5m.groupby(["c6", "date"], sort=False):
        bars_5m_map[(c6, dt)] = grp[["hhmm", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

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
                elif bc_1030 < vwap_1030:
                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut"}
                else:
                    if iztc:
                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                    px = round(float(cc), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
        if iztc:
            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
        px = round(float(cc), 2)
        return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px, "tag": "eod_close"}
    return {"net_ret": round((prev_c / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": prev_c, "tag": "max_hold"}

def sim_dip_trade(row, dip_pct):
    c6, d2 = row["c6"], row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 >= len(all_dts) - 1: return None
    d2_bar = price_lookup.get((c6, d2))
    if not d2_bar: return None
    o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar[:8]
    d1_c = float(row["close"])
    buy_px = round(d1_c * (1.0 + dip_pct), 2)
    if l2 > buy_px + 1e-6:
        return None
    # Note: if stock opened at limit-up (yizi) and dropped to <= buy_px, could it reseal limit-up AFTER hitting <= buy_px?
    # Check 5m bar if available to avoid false lookahead when high==zt2 (since open was already zt2!)
    resealed_after_dip = bool(is_zt2)  # close == zt2 means it definitely resealed after dipping!
    idx3 = idx2 + 1
    d3 = all_dts[idx3]
    d3_bar = price_lookup.get((c6, d3))
    if not d3_bar: return None
    o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar[:8]
    prev_c = round(float(c2), 2)
    if not resealed_after_dip:
        d2_closed_up = (c2 >= d1_c)
        passes_nshape = d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3
        if passes_nshape:
            if is_zt3:
                res = simulate_holding_chain(c6, buy_px, idx3 + 1, 3, row["name"])
                res.update({"sealed_2b": 0, "buy_date": d2, "score": float(row["static_v16"]), "d2_low_pct": (l2/d1_c - 1)*100, "d2_close_pct": (c2/d1_c - 1)*100})
                return res
            else:
                px = round(float(c3), 2)
                return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "nshape_d3_close", "score": float(row["static_v16"]), "d2_low_pct": (l2/d1_c - 1)*100, "d2_close_pct": (c2/d1_c - 1)*100}
        curr = idx3
        while curr < len(all_dts):
            b = price_lookup.get((c6, all_dts[curr]))
            if not b or not b[7]:
                px = round(float(b[0]), 2) if b else prev_c
                return {"net_ret": round((px / buy_px) * (1.0 - FEE_RATE) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "fail_open_cut", "score": float(row["static_v16"]), "d2_low_pct": (l2/d1_c - 1)*100, "d2_close_pct": (c2/d1_c - 1)*100}
            curr += 1
        return None
    res = simulate_holding_chain(c6, buy_px, idx3, 2, row["name"])
    res.update({"sealed_2b": 1, "buy_date": d2, "score": float(row["static_v16"]), "d2_low_pct": (l2/d1_c - 1)*100, "d2_close_pct": (c2/d1_c - 1)*100})
    return res

def calc_stats(trades):
    if not trades:
        return "0笔"
    df_t = pd.DataFrame(trades).sort_values(["buy_date", "score"], ascending=[True, False])
    # Daily equal weight
    daily_grp = df_t.groupby("buy_date")["net_ret"].mean()
    eq_nav = float(np.prod(1.0 + daily_grp.values))
    # 1-slot rotation
    free_dt, free_open = "", False
    nav_1s, peak, mdd = 1.0, 1.0, 0.0
    rot_trades = []
    for dt, grp in df_t.groupby("buy_date", sort=True):
        if free_dt == "" or dt > free_dt or (dt == free_dt and free_open):
            tr = grp.iloc[0]
            nav_1s *= (1.0 + tr["net_ret"])
            peak = max(peak, nav_1s)
            mdd = max(mdd, (peak - nav_1s) / peak)
            free_dt, free_open = tr["exit_date"], bool(tr["exit_at_open"])
            rot_trades.append(tr)
    def sub_stat(sub):
        if len(sub) == 0: return "0笔"
        r = sub["net_ret"].values
        wr = (r > 0).mean() * 100
        w = r[r > 0].mean() if (r > 0).any() else 0.0
        l = abs(r[r < 0].mean()) if (r < 0).any() else 1e-4
        po = w / l if (r < 0).any() else 99.9
        nav = float(np.prod(1.0 + r))
        return f"{len(sub)}笔 胜率{wr:.1f}% 盈亏比{po:.2f} 笔均{r.mean()*100:+.2f}% 累乘{nav:.2f}x"
    t_df = pd.DataFrame(rot_trades)
    s5 = sub_stat(df_t)
    s3 = sub_stat(df_t[df_t["buy_date"] >= "2023-11-12"])
    s1 = sub_stat(df_t[df_t["buy_date"] >= "2025-11-12"])
    sj = sub_stat(df_t[df_t["buy_date"] >= "2026-07-01"])
    return f"全样本[{s5}] | 单仓轮动[{len(t_df)}笔 净值{nav_1s:.2f}x 回撤{mdd*100:.1f}% 较沪深300超额{(nav_1s - (1+CSI300_5Y))*100:+.1f}%] | 日等权[{eq_nav:.2f}x]\n    近3年[{s3}] | 近1年[{s1}] | 7月以来[{sj}]"

# Load V16 official 105 trades to also test merging into V16 1-slot rotation
v16_led = pd.read_csv("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v16_ledger.csv")
print(f"V16 定版主策略账本: {len(v16_led)}笔")

cond_yizi_all = (df["d2_open"] >= df["d2_zt_p"] - 0.01)

print("\n=== A. 全市场主板首板次日一字开盘（不限分数 vs 基础门）盘中炸破 +5% / +3% / 0% 低吸 ===")
for label, base_mask in [
    ("全市场一字开盘(不限分)", cond_yizi_all),
    ("过市值换手紧密度净化门(purifier_ok)", cond_yizi_all & df["purifier_ok"]),
    ("高分好票(purifier_ok & 底分>=220)", cond_yizi_all & df["purifier_ok"] & (df["static_v16"] >= 220)),
    ("高分好票(purifier_ok & 底分>=240)", cond_yizi_all & df["purifier_ok"] & (df["static_v16"] >= 240)),
    ("高分好票(purifier_ok & 底分>=260)", cond_yizi_all & df["purifier_ok"] & (df["static_v16"] >= 260)),
]:
    sub = df[base_mask]
    broken = sub[sub["d2_low"] < sub["d2_zt_p"] - 0.01]
    print(f"\n--- {label}: 一字总数={len(sub)}, 炸板数={len(broken)} ---")
    for dip_lbl, dip_p in [("炸破+5.0%接(昨收×1.05)", 0.05), ("炸破+3.0%接(昨收×1.03)", 0.03), ("炸破0.0%平盘接(昨收×1.00)", 0.00)]:
        trs = []
        for _, r in broken.iterrows():
            t = sim_dip_trade(r, dip_p)
            if t is not None:
                trs.append(t)
        print(f"  * {dip_lbl}: {calc_stats(trs)}")
        if "底分>=240" in label and dip_p == 0.05 and trs:
            print("    [底分>=240 一字炸破+5%逐笔明细]:")
            for t in trs:
                print(f"      {t['buy_date']} {t['c6']} {t['name']} 底分={t['score']:.1f} 买价={t['buy_price']:.2f} 当日最低={t['d2_low_pct']:+.1f}% 当日收={t['d2_close_pct']:+.1f}% -> {t['exit_date']} 卖={t['exit_price']:.2f} 净盈亏={t['net_ret']*100:+.2f}% ({t['tag']})")
        if "purifier_ok)" in label and dip_p == 0.05 and trs:
            print("    [purifier_ok 一字炸破+5% 近1年逐笔明细]:")
            for t in trs:
                if t["buy_date"] >= "2025-11-12":
                    print(f"      {t['buy_date']} {t['c6']} {t['name']} 底分={t['score']:.1f} 买价={t['buy_price']:.2f} 当日最低={t['d2_low_pct']:+.1f}% 当日收={t['d2_close_pct']:+.1f}% -> {t['exit_date']} 卖={t['exit_price']:.2f} 净盈亏={t['net_ret']*100:+.2f}% ({t['tag']})")
