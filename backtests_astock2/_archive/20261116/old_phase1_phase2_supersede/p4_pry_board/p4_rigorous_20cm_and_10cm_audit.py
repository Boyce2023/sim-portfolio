#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""p4_rigorous_20cm_and_10cm_audit.py: 含退市全库合并(零幸存者偏差)+PIT简称+除权校验+卖点矩阵终极核验"""
import sqlite3, json, pickle, sys, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
WORK_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p4_pry_board"
FEE = 0.0020

env = pd.read_parquet(f"{MAT_DIR}/daily_env_5y.parquet").set_index("dt_str").to_dict("index")

# 1. Merge live + delisted daily bars for 20cm (300/301/688) -> ZERO survivorship bias!
cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount"]
df_live = pd.read_parquet(f"{ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet", columns=cols)
df_del = pd.read_parquet(f"{ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols)
adf = pd.concat([df_live, df_del], ignore_index=True)
adf["c6"] = adf["ticker"].astype(str).str[:6]
adf = adf[adf["c6"].str.startswith(("300", "301", "688")) & (adf["date"] >= "2021-09-01")].copy()
adf["date"] = adf["date"].astype(str).str[:10]
adf.drop_duplicates(subset=["c6", "date"], keep="first", inplace=True)
adf.sort_values(["c6", "date"], inplace=True)

# 2. PIT stock name & 90d toxic notices from cninfo_notices_5y_pit.db (mode=ro)
con = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
ndf = pd.read_sql("SELECT sec_code, sec_name, title, trade_date_avail FROM notices WHERE trade_date_avail >= '2021-06-01' ORDER BY trade_date_avail", con)
con.close()
ndf["c6"] = ndf["sec_code"].astype(str).str.zfill(6)
ndf["dt"] = ndf["trade_date_avail"].astype(str).str[:10]

# Build PIT name lookup per code: sorted (dt, sec_name)
name_pit = {}
for c6, g in ndf[["c6", "dt", "sec_name"]].drop_duplicates(subset=["c6", "dt"], keep="last").groupby("c6", sort=False):
    name_pit[c6] = (g["dt"].to_numpy(), g["sec_name"].astype(str).to_numpy())

bad_kw = "立案|退市|终止上市|风险警示|被调查|违规|无法表示意见|保留意见|资金占用|冻结|破产|重整|预亏|大幅下降|减持|暂停上市"
ndf_bad = ndf[ndf["title"].str.contains(bad_kw, na=False)]
bad_pit = {c6: np.sort(g["dt"].unique()) for c6, g in ndf_bad.groupby("c6", sort=False)}

def get_pit_name(c6, ds):
    if c6 not in name_pit: return ""
    dts_n, nms = name_pit[c6]
    idx = np.searchsorted(dts_n, ds, side="right") - 1
    return nms[idx] if idx >= 0 else nms[0]

def has_90d_bad(c6, ds):
    bads = bad_pit.get(c6)
    if bads is None or len(bads) == 0: return False
    idx = np.searchsorted(bads, ds, side="right") - 1
    if idx < 0: return False
    return (pd.Timestamp(ds) - pd.Timestamp(bads[idx])).days <= 90

def sim_20cm_exit(d_arr, o, h, l, c, adjf, v, i, buy_px, emode):
    n = len(d_arr); buy_adj = buy_px * adjf[i]
    pc0 = c[i-1] * adjf[i-1] / (adjf[i] + 1e-12)
    dtp0 = round(pc0 * 0.80, 2)
    reseal0 = (c[i] <= dtp0 + 0.02)
    t_step = 0
    for st in range(1, n - i):
        k = i + st
        if v[k] <= 0 or np.isnan(v[k]): continue
        pck = c[k-1] * adjf[k-1] / (adjf[k] + 1e-12)
        dtpk = round(pck * 0.80, 2)
        # Locked yizi -20% (or -20% close lock for close exits)
        if o[k] == h[k] == l[k] == c[k] and c[k] <= dtpk + 0.02: continue
        t_step += 1
        oa, ha, ca = o[k]*adjf[k], h[k]*adjf[k], c[k]*adjf[k]
        op_r = oa / buy_adj - 1.0 - FEE
        cl_r = ca / buy_adj - 1.0 - FEE
        cl_dt = (c[k] <= dtpk + 0.02)
        if emode == "next_open": return d_arr[k], op_r, st
        if emode == "next_close":
            if cl_dt: continue
            return d_arr[k], cl_r, st
        tp_p, mh, cut = {
            "tp7_h2": (0.07, 2, False), "tp7_h3": (0.07, 3, False), "tp8_h3": (0.08, 3, False),
            "tp10_h3": (0.10, 3, False), "tp10_h5": (0.10, 5, False), "cut_reseal_tp8_h3": (0.08, 3, True)
        }[emode]
        if cut and reseal0: return d_arr[k], op_r, st
        if t_step > mh: return d_arr[k], op_r, st
        if oa >= buy_adj * (1.0 + tp_p): return d_arr[k], op_r, st
        if ha >= buy_adj * (1.0 + tp_p): return d_arr[k], tp_p - FEE, st
        if t_step == mh:
            if cl_dt: continue
            return d_arr[k], cl_r, st
    # If delisted/halted after entry without exit, penalize -50% realistic delisting haircut!
    return d_arr[-1], min((c[-1]*adjf[-1])/buy_adj - 1.0 - FEE, -0.50), len(d_arr)-1-i

events_20 = []
for c6, g in adf.groupby("c6", sort=False):
    d_arr = g["date"].to_numpy()
    o, h, l, c, ac, v, amt = g["open"].to_numpy(float), g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float), g["adj_close"].to_numpy(float), g["volume"].to_numpy(float), g["amount"].to_numpy(float)
    adjf = np.where(c > 0, ac / c, 1.0)
    for i in range(22, len(d_arr) - 2):
        ds = d_arr[i]
        if ds < "2022-01-04" or ds > "2026-11-10" or v[i] <= 0 or o[i] < 3.0: continue
        nm = get_pit_name(c6, ds)
        if "ST" in nm.upper() or "退" in nm: continue
        pc = c[i-1] * adjf[i-1] / (adjf[i] + 1e-12)
        if abs(pc - c[i-1]) / (c[i-1] + 1e-9) > 0.025: continue
        dtp = round(pc * 0.80, 2)
        trig = round(dtp * 1.025, 2)
        # Open at -20% limit-down (<= dtp + 0.015) and intraday pried up >= +2.5%
        if not (o[i] <= dtp + 0.015 and h[i] >= trig): continue
        bad90 = has_90d_bad(c6, ds)
        zt20 = sum((c[j]*adjf[j])/(c[j-1]*adjf[j-1]+1e-12) >= 1.195 for j in range(i-20, i))
        ret10 = (c[i-1]*adjf[i-1]) / (c[i-11]*adjf[i-11] + 1e-12) - 1.0
        n_dt_p = env.get(d_arr[i-1], {}).get("n_dt", 0)
        reseal0 = int(c[i] <= dtp + 0.02)
        ex_dict = {em: sim_20cm_exit(d_arr, o, h, l, c, adjf, v, i, trig, em)
                   for em in ["next_open","next_close","tp7_h2","tp7_h3","tp8_h3","tp10_h3","tp10_h5","cut_reseal_tp8_h3"]}
        events_20.append({"c6":c6,"name":nm,"buy_date":ds,"bad90":bad90,"zt20":zt20,"ret10":ret10,"n_dt_p":n_dt_p,"reseal0":reseal0,"is_300":c6.startswith(("300","301")),"ex":ex_dict,"prev_amt":amt[i-1]})

print(f"Total 20cm (live+delisted) open-at-DT20 pry2.5% events: {len(events_20)}, clean(!bad90): {sum(not x['bad90'] for x in events_20)}")
for label, flt in [
    ("ALL_20cm_clean(!bad90)", lambda x: not x["bad90"]),
    ("300_only_clean(!bad90)", lambda x: (not x["bad90"]) and x["is_300"]),
    ("20cm_Momentum(zt20>=1 & !bad90)", lambda x: (not x["bad90"]) and x["zt20"] >= 1),
    ("20cm_Oversold(zt20==0 & !bad90)", lambda x: (not x["bad90"]) and x["zt20"] == 0),
    ("20cm_Panic(n_dt>=15 & !bad90)", lambda x: (not x["bad90"]) and x["n_dt_p"] >= 15),
]:
    sub = [x for x in events_20 if flt(x)]
    for em in ["next_open", "tp7_h2", "tp8_h3", "tp10_h3", "cut_reseal_tp8_h3"]:
        # Single slot simulation
        srt = sorted(sub, key=lambda x: (x["buy_date"], -x["prev_amt"]))
        free = ""; nav = 1.0; eq = [1.0]; rets = []; is_r = []; oos_r = []
        for x in srt:
            if x["buy_date"] <= free: continue
            ed, r, _ = x["ex"][em]
            nav *= (1.0 + r); free = max(x["buy_date"], ed); eq.append(nav); rets.append(r)
            if x["buy_date"] <= "2024-12-31": is_r.append(r)
            else: oos_r.append(r)
        if not rets: continue
        ra = np.array(rets); w = ra[ra>0]; l = ra[ra<=0]
        po = float(w.mean()/abs(l.mean())) if len(w) and len(l) and l.mean()<0 else 9.99
        pk = np.maximum.accumulate(eq); mdd = float(np.max((pk-eq)/pk)*100)
        ex3 = float(np.prod(1.0 + np.sort(ra)[:-3])) if len(ra)>3 else nav
        print(f"{label:32s} | {em:17s} | n={len(ra):2d} WR={(ra>0).mean()*100:5.1f}% PO={po:4.2f} NAV={nav:6.2f}x MDD={mdd:4.1f}% ex3={ex3:5.2f}x | IS({len(is_r)}):{np.prod(1+np.array(is_r)):5.2f}x OOS({len(oos_r)}):{np.prod(1+np.array(oos_r)):5.2f}x")
