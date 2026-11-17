#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import pickle, pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
MAT = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_HD = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_HD}/part1_cache.pkl", "rb"))

ex_all_dts = sorted(ex_reg["SH"] + ex_reg["SZ"])
def has_ex_5d(dt):
    idx = dt_to_idx.get(dt, -1)
    w = set(all_dts[max(0, idx-5):idx]) if idx >= 1 else set()
    return sum(1 for x in ex_all_dts if x in w) >= 1

def st(r):
    r = np.asarray(r, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) == 0: return "N=0"
    wr = (r > 0).mean() * 100
    w = r[r > 0].mean() if (r > 0).any() else 0.0
    l = abs(r[r <= 0].mean()) if (r <= 0).any() else 0.01
    return f"N={len(r):3d} WR={wr:5.1f}% PO={w/max(l,1e-4):4.2f} Mean={r.mean()*100:+6.2f}%"

df12 = pd.read_parquet(f"{MAT}/cand_0to1_firstboard.parquet")
df12["c6"] = df12["code"].astype(str).str[:6]
df12 = df12.rename(columns={"buy_date": "d1_date"})
v17 = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock/full_day_by_day_v17_ledger.csv")
v17["c6"] = v17["c6"].astype(str).str.zfill(6)
v17["d1_date"] = [all_dts[dt_to_idx[d]-1] for d in v17["buy_date"]]
m17 = v17.merge(df12, on=["c6", "d1_date"], how="left")
r17 = m17[m17["buy_date"] >= "2024-01-01"]
print("V17 rfmcap>30亿 5Y:", st(m17.loc[m17["real_free_mcap"]>30, "net_ret"]), "|| 24-26:", st(r17.loc[r17["real_free_mcap"]>30, "net_ret"]))
print("V17 rfmcap<=30亿 5Y:", st(m17.loc[m17["real_free_mcap"]<=30, "net_ret"]), "|| 24-26:", st(r17.loc[r17["real_free_mcap"]<=30, "net_ret"]))
print("V17 rfmcap<=25亿 5Y:", st(m17.loc[m17["real_free_mcap"]<=25, "net_ret"]), "|| 24-26:", st(r17.loc[r17["real_free_mcap"]<=25, "net_ret"]))

df5m = pd.read_parquet(f"{ROOT}/sim-portfolio/data/cand_5m_bars_v15_complete.parquet")
b5_map = {k: g[["hhmm", "open", "high", "low", "close"]].to_numpy() for k, g in df5m.groupby(["c6", "date"], sort=False)}
df5 = pd.read_parquet(f"{MAT}/verified_1a_5ban_cands.parquet")
df5 = df5[(df5["buyable_open"] == True) & (df5["open_pct"] <= 5.5) & (df5["lock_top10"] >= 50.0)].copy()
df5["c6"] = df5["code"].astype(str).str[:6]
df5["ex_active"] = [has_ex_5d(d) for d in df5["buy_date"]]
ret_close, ret_5m_prot, n_5m_cov = [], [], 0
for r in df5.itertuples():
    bars = code_bars[r.c6]
    pb = bars["p"][r.buy_date]
    ob = bars["open"][pb]
    k = pb
    while k < len(bars["dts"]) - 1 and bars["is_zt"][k] and (k - pb < 8):
        k += 1
    ec = bars["close"][k]; pre = bars["close"][k-1]
    rc = (ec / ob) * 0.9985 - 1.0
    ret_close.append(rc)
    arr = b5_map.get((r.c6, bars["dts"][k]))
    rp = rc
    if arr is not None:
        n_5m_cov += 1
        if (not bars["is_zt"][k]) and pre > 0:
            seen_high8 = False
            for row5 in arr:
                hhmm = int(row5[0])
                if float(row5[2]) / pre - 1.0 >= 0.08:
                    seen_high8 = True
                if seen_high8 and hhmm >= 1000 and (float(row5[4]) / pre - 1.0 <= 0.045):
                    rp = (float(row5[4]) / ob) * 0.9985 - 1.0
                    break
    ret_5m_prot.append(rp)
df5["rc"] = ret_close; df5["rp"] = ret_5m_prot
df5_r = df5[df5["buy_date"] >= "2024-01-01"]
print(f"\n5ban S4断板收盘卖 (N={len(df5)}, 5m覆盖={n_5m_cov}) 5Y:", st(df5["rc"]), "|| 5m因果冲高护利:", st(df5["rp"]))
print("5ban S4断板收盘卖 24-26:", st(df5_r["rc"]), "|| 5m因果冲高护利:", st(df5_r["rp"]))
for nm, c5, cr in [
    ("全场唯一最高板(max_b==5)", df5["mkt_max_board_prev"]==5, df5_r["mkt_max_board_prev"]==5),
    ("头顶有压制(max_b>=6)", df5["mkt_max_board_prev"]>=6, df5_r["mkt_max_board_prev"]>=6),
    ("同题材首板顶一字>=1(低位抢风头)", df5["plate_yizi_cnt"]>=1, df5_r["plate_yizi_cnt"]>=1),
    ("同题材零一字(plate_yizi_cnt==0)", df5["plate_yizi_cnt"]==0, df5_r["plate_yizi_cnt"]==0),
    ("百股涨停>=95(高潮抱团最高标)", df5["mkt_zt_prev"]>=95, df5_r["mkt_zt_prev"]>=95),
    ("近5日交易所重点监控期", df5["ex_active"], df5_r["ex_active"]),
    ("非重点监控期", ~df5["ex_active"], ~df5_r["ex_active"]),
]:
    print(f"  {nm:32s} | 5Y: {st(df5.loc[c5, 'rc'])} || 24-26: {st(df5_r.loc[cr, 'rc'])}")

df_reb = pd.read_parquet(f"{MAT}/verified_1c_rebound_cands.parquet")
print("\n1c_rebound cols:", [c for c in df_reb.columns if "ret" in c or "ed_" in c])
df_reb = df_reb[df_reb["buyable_open"] == True].copy()
rcol = [c for c in df_reb.columns if c.startswith("ret_")][-1]
reb_r = df_reb[df_reb["buy_date"] >= "2024-01-01"]
print(f"1c_rebound Base ({rcol}) 5Y:", st(df_reb[rcol]), "|| 24-26:", st(reb_r[rcol]))
for nm, c5, cr in [
    ("同题材首板顶一字>=1", df_reb["plate_yizi_cnt"]>=1, reb_r["plate_yizi_cnt"]>=1),
    ("同题材零一字", df_reb["plate_yizi_cnt"]==0, reb_r["plate_yizi_cnt"]==0),
    ("同题材队友竞价<-1.5%", df_reb["plate_peers_open_avg"]<-0.015, reb_r["plate_peers_open_avg"]<-0.015),
    ("同题材队友竞价>=0%", df_reb["plate_peers_open_avg"]>=0.0, reb_r["plate_peers_open_avg"]>=0.0),
    ("近20日3进4核按钮率>35%", df_reb["prev_3to4_nuke_rate_20d"]>0.35, reb_r["prev_3to4_nuke_rate_20d"]>0.35),
    ("近20日3进4核按钮率<=25%", df_reb["prev_3to4_nuke_rate_20d"]<=0.25, reb_r["prev_3to4_nuke_rate_20d"]<=0.25),
    ("真实自由流通换手>45%(派发)", df_reb["prev_real_to"]>45, reb_r["prev_real_to"]>45),
    ("真实自由流通换手<=40%", df_reb["prev_real_to"]<=40, reb_r["prev_real_to"]<=40),
]:
    print(f"  {nm:28s} | 5Y: {st(df_reb.loc[c5, rcol])} || 24-26: {st(reb_r.loc[cr, rcol])}")
