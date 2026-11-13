#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import pickle, re, numpy as np, pandas as pd
from collections import defaultdict
from eval_scorecard_final import sim_exit_e2

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/dfr_all75_factors.pkl")
df_1c = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/verified_1c_rebound_cands.parquet")
df_1c["c6"] = df_1c["code"].astype(str).str.zfill(6)
c1_map = {(str(r.buy_date)[:10], r.c6): r for r in df_1c.itertuples()}

Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
g_seat = lb[lb["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
lhb_clean = {}
for (d, c), gl in g_seat.groupby(["dt", "c6"]):
    tb = float(gl["BUY"].sum()); ns = gl["OPERATEDEPT_NAME"].astype(str); lm = ns.str.contains("拉萨", na=False)
    lhb_clean[(d, c)] = (int(lm.sum()), float(gl.loc[lm, "BUY"].sum()) / tb if tb > 0 else 0.0, int(ns.str.contains(Q_RE, na=False).sum()), int(ns.str.contains("机构专用", na=False).sum()))

csi5_l, lh1_l, in1_l, ign_ok_l, hyb_l, obc_l, pelo_l = [], [], [], [], [], [], []
for r in dfr.itertuples():
    i1 = dt_to_idx[r.d1]
    csi5_l.append(CSI_MAP[r.d1] / CSI_MAP[all_dts[max(0, i1-5)]] - 1.0)
    a1 = lhb_clean.get((r.d1, r.code), (0,0.0,0,0))
    lh1_l.append(a1[0]); in1_l.append(a1[3])
    m = c1_map.get((r.buy_date, r.code))
    obc_l.append(int(getattr(m, "open_board_count", 0)) if m else 0)
    pelo_l.append(float(getattr(m, "p_elo", 120.0)) if m else 120.0)
    bars = code_bars[r.code]; d2p = bars["p"][r.buy_date]; b_op = float(bars["open"][d2p])
    imap = SH_MAP if r.ex == "SH" else SZ_MAP
    if r.op2 < 0.0:
        ipx = b_op * 1.015
        if float(bars["high"][d2p]) >= ipx and ipx < float(bars["zt_px"][d2p]) - 0.011:
            ign_ok_l.append(True); hyb_l.append(sim_exit_e2(bars, d2p, ipx, imap, True, True))
        else:
            ign_ok_l.append(False); hyb_l.append(None)
    else:
        ign_ok_l.append(True); hyb_l.append(sim_exit_e2(bars, d2p, b_op, imap, True, True))
dfr["csi5"], dfr["lh1"], dfr["in1"], dfr["can_ign"], dfr["hyb_sm"], dfr["obc"], dfr["pelo"] = csi5_l, lh1_l, in1_l, ign_ok_l, hyb_l, obc_l, pelo_l
dfr["b_open_h"] = dfr["op2"] >= 0.0

def score_v2(r):
    if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 38.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
        return -999
    sc = 60
    # 择时三大真柱（98因子双期同向验证：分歧洗礼后抱团 + 非百股涨停分流 + 大盘5日止跌企稳）
    if r["brk_r10"] >= 0.20: sc += 12
    else: sc -= 8
    if r["n_zt"] < 70: sc += 10
    elif r["n_zt"] >= 95: sc -= 10
    if r["csi5"] >= -0.005: sc += 8
    elif r["csi5"] < -0.025: sc -= 10
    # 微观承接与席位
    if r["d1_op"] < 0.0: sc += 8
    if r["op2"] < 0.0: sc += 8
    elif 0.0 <= r["op2"] <= 0.025: sc += 6
    if r["obc"] == 0 and r["d0_tight"] >= 35.0: sc += 6
    if r["pelo"] < 135.0 and (not r["dom"]): sc += 6
    if r["lh1"] == 0: sc += 6
    elif r["lh1"] == 2: sc -= 10
    if r["in1"] >= 1: sc -= 6
    return sc

dfr["sc2"] = [score_v2(row) for _, row in dfr.iterrows()]

# Load 5B benign regime module (顺周期互补腿)
df_1a = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/verified_1a_5ban_cands.parquet")
df_1a["c6"] = df_1a["code"].astype(str).str.zfill(6)
f1a = df_1a[(df_1a["open_pct"] <= 0.055) & (df_1a["lock_top10"] >= 50.0)].sort_values(["buy_date", "lock_top10"], ascending=[True, False]).reset_index(drop=True)
closed_5b, rows_5b = [], []
for r in f1a.itertuples(index=False):
    past = [x for x in closed_5b if x[0] < r.buy_date]
    closed_5b.append((str(r.ed_d4_93)[:10], float(r.ret_d4_93)))
    if len(past) < 4: continue
    l4 = [x[1] for x in past[-4:]]
    ex = "SH" if r.c6.startswith("60") else "SZ"
    i_sig = dt_to_idx.get(str(r.sig_date)[:10], 5); w5 = all_dts[max(0, i_sig - 5)]
    ex_cnt = sum(1 for x in ex_reg[ex] if w5 <= x <= str(r.sig_date)[:10])
    s_tox = any(0 <= (pd.Timestamp(str(r.sig_date)[:10]) - pd.Timestamp(x)).days <= 10 for x in (tox_dates.get(r.c6, []) + stock_reg.get(r.c6, [])))
    if (sum(v > 0 for v in l4) / 4.0 >= 0.60) and (np.mean(l4) >= 0.04) and (r.prev_break_dt_rate_10d <= 0.30) and (not (-0.035 <= r.open_pct <= 0.010)) and (r.lhasa_seats_prev <= 1) and ex_cnt == 0 and (not s_tox):
        rows_5b.append({"buy_date": str(r.buy_date)[:10], "exit_date": str(r.ed_d4_93)[:10], "code": r.c6, "name": str(r.name), "sc2": 98, "net_ret": float(r.ret_d4_93), "b_open_h": True, "eo": bool(r.eo_d4_93), "pool": "5B_顺周期"})

def to_tdf(sub):
    rs = []
    for r in sub[sub["can_ign"]].itertuples():
        ed, rt, hb, eo = r.hyb_sm
        rs.append({"buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name, "sc2": r.sc2, "net_ret": rt, "b_open_h": r.b_open_h, "eo": eo, "pool": "首阴抱团"})
    return pd.DataFrame(rs)

def eval_tdf(tdf, s_dt, e_dt):
    w = tdf[(tdf["buy_date"]>=s_dt)&(tdf["buy_date"]<=e_dt)].sort_values(["buy_date","sc2"], ascending=[True,False])
    if w.empty: return 0, 0, 0, 1.0, 1.0, 0.0, pd.DataFrame()
    ew = float((1.0 + w.groupby("buy_date")["net_ret"].mean()).prod())
    taken, fd, peo, nav, pk, mdd = [], "", False, 1.0, 1.0, 0.0
    for r in w.itertuples(index=False):
        if fd=="" or r.buy_date>fd or (r.buy_date==fd and peo and (not r.b_open_h)):
            taken.append(r); fd=r.exit_date; peo=r.eo; nav*=(1+r.net_ret); pk=max(pk,nav); mdd=max(mdd,(pk-nav)/pk)
    rets = [x.net_ret for x in taken]
    wr = np.mean([x>0 for x in rets])*100
    pos = [x for x in rets if x>0]; neg = [abs(x) for x in rets if x<=0]
    plr = (np.mean(pos)/np.mean(neg)) if (pos and neg) else 99.0
    sr = np.sort(rets); top5 = float(np.prod(1.0 + (sr[:-5] if len(sr)>5 else np.array([0.0]))))
    return len(taken), wr, plr, nav, ew, top5, mdd*100, pd.DataFrame(taken)

print("=== 纯首阴抱团择时 V2 (修正逆向择时后) ===")
for th in [76, 80, 84, 88]:
    t1 = to_tdf(dfr[dfr["sc2"]>=th])
    ni, wri, plri, navi, ewi, t5i, mddi, _ = eval_tdf(t1, "2022-01-04", "2024-12-31")
    no, wro, plro, navo, ewo, t5o, mddo, _ = eval_tdf(t1, "2025-01-02", "2026-11-12")
    nf, wrf, plrf, navf, ewf, t5f, mddf, ledf = eval_tdf(t1, "2022-01-04", "2026-11-12")
    yrs = [f"{y}:{eval_tdf(t1, f'{y}-01-01', f'{y}-12-31')[3]:.2f}x({eval_tdf(t1, f'{y}-01-01', f'{y}-12-31')[0]}笔)" for y in ["2022","2023","2024","2025","2026"]]
    print(f"  V2纯首阴 Thr>={th} | 22-24: {ni:2d}笔 WR={wri:4.1f}% PLR={plri:4.2f} 单仓={navi:5.2f}x MDD={mddi:4.1f}% | 25-26: {no:2d}笔 WR={wro:4.1f}% 单仓={navo:6.2f}x | 5Y: {nf:2d}笔 WR={wrf:4.1f}% PLR={plrf:4.2f} 单仓={navf:6.2f}x 日等权={ewf:6.2f}x 去Top5={t5f:5.2f}x MDD={mddf:4.1f}%")
    print("    逐年:", " | ".join(yrs))
    if th == 80: ledf.to_csv(f"{OUT_DIR}/v2_pure_yin_80_ledger.csv", index=False)

print("\n=== 阴阳双择时互补单仓 V2 (分歧期做首阴抱团 + 顺周期做五板加速) ===")
for th in [80, 84]:
    tc = pd.concat([to_tdf(dfr[dfr["sc2"]>=th]), pd.DataFrame(rows_5b)], ignore_index=True)
    ni, wri, plri, navi, ewi, t5i, mddi, _ = eval_tdf(tc, "2022-01-04", "2024-12-31")
    no, wro, plro, navo, ewo, t5o, mddo, _ = eval_tdf(tc, "2025-01-02", "2026-11-12")
    nf, wrf, plrf, navf, ewf, t5f, mddf, ledc = eval_tdf(tc, "2022-01-04", "2026-11-12")
    yrs = [f"{y}:{eval_tdf(tc, f'{y}-01-01', f'{y}-12-31')[3]:.2f}x({eval_tdf(tc, f'{y}-01-01', f'{y}-12-31')[0]}笔)" for y in ["2022","2023","2024","2025","2026"]]
    print(f"  V2阴阳互补 Thr>={th} | 22-24: {ni:2d}笔 WR={wri:4.1f}% PLR={plri:4.2f} 单仓={navi:5.2f}x MDD={mddi:4.1f}% | 25-26: {no:2d}笔 WR={wro:4.1f}% 单仓={navo:6.2f}x | 5Y: {nf:2d}笔 WR={wrf:4.1f}% PLR={plrf:4.2f} 单仓={navf:6.2f}x 日等权={ewf:6.2f}x 去Top5={t5f:5.2f}x MDD={mddf:4.1f}%")
    print("    逐年:", " | ".join(yrs))
    if th == 80: ledc.to_csv(f"{OUT_DIR}/v2_dual_timing_80_ledger.csv", index=False)
