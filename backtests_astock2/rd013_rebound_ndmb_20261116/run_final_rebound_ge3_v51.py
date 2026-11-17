#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""最终定版：反包策略22因子选股模型（包含3板：3连板+4连板+5连板以上首阴真阳）全量5m回测"""
import os, re, json, pickle, warnings
from collections import defaultdict
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
OUT_H = f"{SANDBOX}/high_dragon_scorecard_20261113"
SAVE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd013_rebound_ndmb_20261116"
FEE = 0.0020

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_H}/part1_cache.pkl", "rb"))
df_5m = pd.read_parquet(f"{ROOT}/sim-portfolio/data/all_strategies_5m_complete_pit.parquet")
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m = {(c, d): g[["hhmm_int", "open", "high", "low", "close"]].to_numpy(dtype=float) for (c, d), g in df_5m.groupby(["c6", "date"], sort=False)}

Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
RE_TOP_YZ = re.compile(r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)")
RE_SURF = re.compile(r"(?:杭州上塘路|宜昌沿江大道|宜昌珍珠路|佛山绿景路|佛山季华六路|佛山季华五路|江阴.*营业部|苏州.*营业部)")
TECH_RE = re.compile(r"(?:算力|芯片|半导体|机器人|人工智能|AI|华为|低空|固态电池)")

lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
ls = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_sell.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
ls["dt"], ls["c6"] = ls["TRADE_DATE"].astype(str).str[:10], ls["SECURITY_CODE"].astype(str).str[:6]
lhb_b = {(d, c): list(zip(g["OPERATEDEPT_NAME"].astype(str), g["BUY"].astype(float))) for (d, c), g in lb[lb["dt"]>="2021-09-01"].groupby(["dt","c6","OPERATEDEPT_NAME"],as_index=False)["BUY"].min().groupby(["dt","c6"])}
lhb_s = {(d, c): list(zip(g["OPERATEDEPT_NAME"].astype(str), g["SELL"].astype(float))) for (d, c), g in ls[ls["dt"]>="2021-09-01"].groupby(["dt","c6","OPERATEDEPT_NAME"],as_index=False)["SELL"].min().groupby(["dt","c6"])}

kpl_zt, kpl_first = defaultdict(list), {}
for ln in open(f"{ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8"):
    it = json.loads(ln); d = it["date"]
    for pl in it.get("plates", it.get("themes", [])):
        pn = pl.get("plate") or pl.get("plate_name") or ""
        if pn and pn not in kpl_first: kpl_first[pn] = d
        for st in pl.get("stocks", []):
            c6 = str(st[0]).zfill(6); rsn = f"{st[2] if len(st)>2 else ''} {st[3] if len(st)>3 else ''}".strip()
            kpl_zt[c6].append((d, pn, str(st[1]), rsn))

import sqlite3
con_t = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
tape = {(r[0], str(r[1]).zfill(6)): (str(r[2] or "99:99:99"), int(r[3] or 0)) for r in con_t.execute("SELECT trade_date, sec_code, first_seal_time, open_board_count FROM zt_micro_tape")}
con_t.close()
df_1c = pd.read_parquet(f"{SANDBOX}/grand_factor_matrix_20261112/verified_1c_rebound_cands.parquet", columns=["buy_date", "code", "open_board_count", "p_elo"])
df_1c["c6"] = df_1c["code"].astype(str).str.zfill(6)
c1_map = {(str(r.buy_date)[:10], r.c6): (int(r.open_board_count), float(r.p_elo)) for r in df_1c.itertuples()}

def get_dev_px(bars, cp, imap, disc=0.07):
    cd = bars["dts"][cp]; ir = imap.get(cd)
    if not ir: return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp+1)):
        p = cp-k; bi = imap.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0: bp = min(bp, bc*(1.0 + (1.0-disc) + (ir/bi - 1.0)))
    for k in range(1, min(31, cp+1)):
        p = cp-k; bi = imap.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0: bp = min(bp, bc*(1.0 + (2.0-disc) + (ir/bi - 1.0)))
    return bp

cands = []
for idx in range(15, len(all_dts) - 1):
    d1, d0, d2 = all_dts[idx], all_dts[idx-1], all_dts[idx+1]
    if d2 < "2021-11-15" or d2 > "2026-11-16": continue
    g1, g0 = by_dt[d1], by_dt[d0]
    zt0 = g0[g0["is_zt"] & (~g0["name"].str.contains("ST", na=False))]
    if zt0.empty: continue
    max_st = int(zt0["streak"].max())
    top_cnt = int((zt0["streak"] == max_st).sum())
    non_yz = zt0[zt0["yz_streak"] < zt0["streak"]]
    max_turn_st = int(non_yz["streak"].max()) if not non_yz.empty else 0
    all_yz_top = bool((zt0[zt0["streak"] == max_st]["yz_streak"] >= max_st).all())
    sts = sorted(zt0["streak"].unique(), reverse=True)
    sec_st = int(sts[1]) if len(sts) > 1 else 0
    n_zt_d1 = int(g1["is_zt"].sum())
    csi5 = CSI_MAP[d1] / CSI_MAP[all_dts[max(0, idx-5)]] - 1.0
    brk_r10 = env_stats[d1]["brk_r10"]
    w5_s = all_dts[max(0, idx-5)]

    sub = g1[(g1["prev_streak"] >= 3) & (~g1["is_zt"]) & (g1["close"] > g1["open"]) & (~g1["name"].str.contains("ST", na=False))]
    for r1 in sub.itertuples():
        c6 = r1.c6; bars = code_bars[c6]
        if d2 not in bars["p"]: continue
        d1p, d2p = bars["p"][d1], bars["p"][d2]; d0p = d1p - 1
        st0 = int(r1.prev_streak)
        is_top_dragon = ((st0 == max_st and top_cnt == 1) or (all_yz_top and st0 == max_turn_st and int((non_yz["streak"] == max_turn_st).sum()) == 1 and st0 >= 3))
        ex = "SH" if c6.startswith("60") else "SZ"
        op2 = float(bars["o_pct"][d2p]); d1_to = float(r1.to)
        s_reg = any(-5 <= (pd.Timestamp(d1)-pd.Timestamp(x)).days <= 10 for x in stock_reg.get(c6, []))
        tox = any(0 <= (pd.Timestamp(d1)-pd.Timestamp(x)).days <= 90 for x in tox_dates.get(c6, []))
        ex_cnt = sum(1 for x in ex_reg[ex] if w5_s <= x <= d1)
        b0, b1, s1 = lhb_b.get((d0, c6), []), lhb_b.get((d1, c6), []), lhb_s.get((d1, c6), [])
        lh1 = sum(1 for dp, _ in b1 if "拉萨" in dp)
        in1 = sum(1 for dp, _ in b1 if "机构专用" in dp)
        qu1 = sum(1 for dp, _ in b1 if Q_RE.search(dp))
        if s_reg or tox or ex_cnt >= 2 or d1_to > 35.0 or lh1 >= 3 or op2 > 0.045 or op2 < -0.065: continue

        sc = 60 + (12 if brk_r10 >= 0.20 else -8) + (10 if n_zt_d1 < 70 else (-10 if n_zt_d1 >= 95 else 0))
        sc += (8 if csi5 >= -0.005 else (-10 if csi5 < -0.025 else 0)) + (8 if r1.o_pct < 0 else 0)
        sc += (8 if op2 < 0 else (6 if op2 <= 0.025 else 0))
        fst, obc_t = tape.get((d0, c6), ("10:00:00", 0))
        obc_c, pelo = c1_map.get((d2, c6), (obc_t, 120.0))
        if obc_c == 0 and r1.d0_tight >= 35.0: sc += 6
        dom = (st0 >= max_st and (st0 - sec_st) >= 2)
        if pelo < 135.0 and (not dom): sc += 6
        sc += (6 if lh1 == 0 else (-10 if lh1 == 2 else 0)) + (-6 if in1 >= 1 else 0)
        sc += (5 if r1.close <= 20.0 else (-10 if r1.close > 35.0 else 0))
        tb_cnt = sum(1 for k in range(max(0, d0p-st0+1), d0p+1) if bars["is_zt"][k] and (not bars["is_yizi"][k]))
        sc += (5 if tb_cnt >= 4 else (-5 if tb_cnt <= 2 else 0))
        if r1.l_pct <= -0.06: sc += 5
        h_rows = [x for x in holders.get(c6, []) if x[0] < d1]
        lk = float(max(h_rows, key=lambda x: x[1])[2]) if h_rows else 38.0
        fmcap = float(r1.mcap) * (1.0 - lk/100.0)
        sc += (6 if (lk >= 45.0 or fmcap >= 45.0) else -6)
        if qu1 >= 1 and lh1 <= 1: sc += 4
        # KPL memory & seats
        pz = [x for x in kpl_zt.get(c6, []) if x[0] < d0]
        cur_z = [x for x in kpl_zt.get(c6, []) if x[0] == d0]
        cur_p = cur_z[0][1] if cur_z else ""; cur_r = cur_z[0][3] if cur_z else ""
        z1y = [x for x in pz if (pd.Timestamp(d0)-pd.Timestamp(x[0])).days <= 365]
        z3y = [x for x in pz if (pd.Timestamp(d0)-pd.Timestamp(x[0])).days <= 1095]
        # streak hist 1y/3y
        s_pre = []
        cur_s = 0
        for k in range(max(0, d0p-750), max(0, d0p-st0+1)):
            cur_s = cur_s+1 if bars["is_zt"][k] else 0
            s_pre.append((d0p-k, cur_s))
        m1y = max([v for dist, v in s_pre if isinstance(dist,int) and dist<=250] or [0])
        m3y = max([v for dist, v in s_pre if isinstance(dist,int) and dist<=750] or [0])
        sc += (6 if m1y >= 5 else (3 if m3y >= 5 else 0))
        old_th = cur_p and kpl_first.get(cur_p, d0) < (pd.Timestamp(d0)-pd.Timedelta(days=180)).strftime("%Y-%m-%d")
        if z1y: sc += (3 if old_th else -5)
        top_b0 = {dp for dp, _ in b0 if RE_TOP_YZ.search(dp)}
        s1_dps = {dp for dp, _ in s1}
        if top_b0 and not (top_b0 & s1_dps): sc += 5
        tb1 = sum(a for _, a in b1); ts1 = sum(a for _, a in s1)
        lh_amt = sum(a for dp, a in b1 if "拉萨" in dp)
        if tb1 > 0 and lh_amt / tb1 >= 0.20: sc -= 10
        if (tb1 - ts1) > 2e7: sc -= 5
        if any(RE_SURF.search(dp) for dp, _ in b0): sc -= 6
        if fst <= "09:35:00": sc -= 5
        if TECH_RE.search(cur_p + " " + cur_r): sc -= 4

        # Simulate trade with 5m bars
        b_op, zt_px = float(bars["open"][d2p]), float(bars["zt_px"][d2p])
        if b_op >= zt_px - 0.011: continue
        arr_b = bars_5m.get((c6, d2))
        if op2 >= 0.0: b_px, b_hh = b_op, 925
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011: continue
            hit = [row for row in (arr_b if arr_b is not None else []) if int(row[0]) <= 1130 and row[2] >= ipx]
            if not hit: continue
            b_hh, b_px = int(hit[0][0]), float(max(hit[0][1], ipx))
        imap = SH_MAP if ex == "SH" else SZ_MAP
        n = len(bars["dts"])
        if bars["is_zt"][d2p]:
            imm = False; ep, epx, eh = min(d2p+5, n-1), float(bars["close"][min(d2p+5, n-1)]), 1500
            for step in range(1, 8):
                p = d2p + step
                if p >= n: break
                pl = get_dev_px(bars, p, imap, 0.07)
                if bars["open"][p] >= pl: ep, epx, eh = p, float(bars["open"][p]), 925; break
                if bars["high"][p] >= pl: ep, epx, eh = p, float(pl), 1030; break
                if not bars["is_zt"][p]:
                    if (not imm) and (bars["close"][p] > bars["open"][p]): imm = True; continue
                    while p < n-1 and bars["is_yizi_dt"][p]: p += 1
                    ep, epx, eh = p, float(bars["close"][p]), 1455; break
        else:
            p = min(d2p+1, n-1)
            while p < n-1 and bars["is_yizi_dt"][p]: p += 1
            d2_c = float(bars["close"][d2p]); d2_ret = d2_c / b_px - 1.0
            d3_op = float(bars["open"][p]) / float(bars["pre_c"][p]) - 1.0
            if d2_ret <= -0.02 or (d2_c < b_op and d2_ret < 0) or d3_op <= -0.035:
                ep, epx, eh = p, float(bars["open"][p]), 925
            else:
                ep, epx, eh = p, float(bars["close"][p]), 1455
        ret = (epx * bars["adjf"][ep]) / (b_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
        cands.append({"buy_date": d2, "buy_hhmm": b_hh, "exit_date": bars["dts"][ep], "exit_hhmm": eh, "code": c6, "name": r1.name, "st0": st0, "is_top": is_top_dragon, "sc": int(sc), "buy_px": round(b_px,2), "exit_px": round(epx,2), "net_ret": float(ret), "d2_zt": bool(bars["is_zt"][d2p])})

cdf = pd.DataFrame(cands)
def eval_pool(sub, label, th=88, cb=True):
    q = sub[sub["sc"] >= th].sort_values(["buy_date", "sc", "st0"], ascending=[True, False, False])
    taken, ed, eh, cl, sk = [], "", 0, 0, False
    for r in q.itertuples(index=False):
        if ed == "" or r.buy_date > ed or (r.buy_date == ed and r.buy_hhmm > eh):
            if cb and sk:
                ed, eh = r.exit_date, r.exit_hhmm
                if r.net_ret > 0: sk, cl = False, 0
                continue
            taken.append(r); ed, eh = r.exit_date, r.exit_hhmm
            if r.net_ret < -0.02:
                cl += 1
                if cl >= 2: sk = True
            elif r.net_ret > 0: cl = 0
    ldf = pd.DataFrame(taken)
    out = {}
    idx_fresh = json.load(open(f"{SANDBOX}/index_klines_5y_cache.json"))["sh000300"]
    max_csi_d = max(idx_fresh.keys())
    for wn, sd, ed_w in [("全5年","2021-11-15","2026-11-16"), ("近3年","2023-11-16","2026-11-16"), ("2026全年","2026-01-01","2026-11-16")]:
        w = ldf[(ldf["buy_date"]>=sd) & (ldf["buy_date"]<=ed_w)]
        eq_all = sub[(sub["sc"]>=th) & (sub["buy_date"]>=sd) & (sub["buy_date"]<=ed_w)]
        ed_c = ed_w if ed_w in idx_fresh else max_csi_d
        sd_c = sd if sd in idx_fresh else min(k for k in idx_fresh if k >= sd)
        csi = (idx_fresh[ed_c]/idx_fresh[sd_c] - 1.0)*100
        if len(w)==0: continue
        rets = w["net_ret"].values; wr = float((rets>0).mean()*100)
        plr = float(rets[rets>0].mean()/abs(rets[rets<=0].mean())) if (rets<=0).any() else 99.0
        nav = float(np.prod(1+rets)); eq = float(np.prod(1+eq_all.groupby("buy_date")["net_ret"].mean().values))
        pk, cur, mdd = 1.0, 1.0, 0.0
        for x in rets: cur *= (1+x); pk = max(pk, cur); mdd = max(mdd, (pk-cur)/pk)
        out[wn] = {"N": len(w), "WR": round(wr,1), "PLR": round(plr,2), "SS_NAV": round(nav,2), "EQ_NAV": round(eq,2), "MDD": round(mdd*100,1), "CSI": round(csi,1), "EX": round((nav-1)*100-csi,1), "N_st3": int((w["st0"]==3).sum())}
    print(f"=== {label} (th>={th}) ===")
    for k, v in out.items(): print(" ", k, v)
    return ldf, out

l_top3, o_top3 = eval_pool(cdf[cdf["is_top"]], "定式一：最高标首阴V5.1含3板(>=3板全场第一高)", 88)
l_all3, o_all3 = eval_pool(cdf, "定式二：全市场>=3板真阳反包22因子精选(不限第一高)", 88)
l_all3_92, o_all3_92 = eval_pool(cdf, "定式三：全市场>=3板真阳反包22因子高严档", 92)
l_top3.to_csv(f"{SAVE_DIR}/ledger_v51_ge3_topdragon.csv", index=False, encoding="utf-8-sig")
l_all3.to_csv(f"{SAVE_DIR}/ledger_v51_ge3_allpool.csv", index=False, encoding="utf-8-sig")
json.dump({"topdragon_ge3_88": o_top3, "allpool_ge3_88": o_all3, "allpool_ge3_92": o_all3_92}, open(f"{SAVE_DIR}/summary_v51_ge3_final.json", "w"), ensure_ascii=False, indent=2)
print("Recent 2026 trades (topdragon_ge3):", l_top3[l_top3["buy_date"]>="2026-01-01"][["buy_date","code","name","st0","sc","net_ret"]].to_dict("records"))
