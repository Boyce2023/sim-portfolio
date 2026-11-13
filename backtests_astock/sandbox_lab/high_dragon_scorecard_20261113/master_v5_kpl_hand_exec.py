#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import pickle, re, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
FEE = 0.0020

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/sub1_kpl_enriched.pkl")
bars_5m = pickle.load(open(f"{OUT_DIR}/sub2_5m_bars_cache.pkl", "rb"))

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

for col_n, fn in [
    ("csi5", lambda r: CSI_MAP[r.d1] / CSI_MAP[all_dts[max(0, dt_to_idx[r.d1]-5)]] - 1.0),
    ("lh1", lambda r: lhb_clean.get((r.d1, r.code), (0,0.0,0,0))[0]),
    ("qu1", lambda r: lhb_clean.get((r.d1, r.code), (0,0.0,0,0))[2]),
    ("in1", lambda r: lhb_clean.get((r.d1, r.code), (0,0.0,0,0))[3]),
    ("obc", lambda r: int(getattr(c1_map.get((r.buy_date, r.code)), "open_board_count", 0)) if c1_map.get((r.buy_date, r.code)) else 0),
    ("pelo", lambda r: float(getattr(c1_map.get((r.buy_date, r.code)), "p_elo", 120.0)) if c1_map.get((r.buy_date, r.code)) else 120.0),
]:
    dfr[col_n] = [fn(r) for r in dfr.itertuples()]

def score_v4(r):
    if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 38.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
        return -999
    sc = 60
    sc += 12 if r["brk_r10"] >= 0.20 else -8
    if r["n_zt"] < 70: sc += 10
    elif r["n_zt"] >= 95: sc -= 10
    if r["csi5"] >= -0.005: sc += 8
    elif r["csi5"] < -0.025: sc -= 10
    if r["d1_op"] < 0.0: sc += 8
    if r["op2"] < 0.0: sc += 8
    elif 0.0 <= r["op2"] <= 0.025: sc += 6
    if r["obc"] == 0 and r["d0_tight"] >= 35.0: sc += 6
    if r["pelo"] < 135.0 and (not r["dom"]): sc += 6
    if r["lh1"] == 0: sc += 6
    elif r["lh1"] == 2: sc -= 10
    if r["in1"] >= 1: sc -= 6
    # V3 5f
    if r["low_price_le20"]: sc += 5
    elif r["high_price_gt35"]: sc -= 10
    if r["turn_boards_ge4"]: sc += 5
    elif r["turn_boards_cnt"] <= 2: sc -= 5
    if r["d1_deep_dip_le6"]: sc += 5
    if r["lock"] >= 45.0: sc += 4
    elif r["lock"] < 25.0: sc -= 4
    if r["qu1"] >= 1 and r["lh1"] <= 1: sc += 4
    # V4 KPL + Youzi + Memory
    if r["kpl_hist_1y_has_ge5"]: sc += 6
    elif r["kpl_hist_3y_has_ge5"]: sc += 3
    if r["kpl_old_stock_old_theme"]: sc += 3
    elif r["kpl_old_stock_new_theme"]: sc -= 5
    if r["lhb_d0_top_locked"]: sc += 5
    if r["lhb_d1_lhasa_heavy"]: sc -= 10
    if r["lhb_d1_net_positive"]: sc -= 5
    if r["lhb_d0_day_surf_buy"]: sc -= 6
    if r["kpl_d0_seal_early_0935"]: sc -= 5
    if r["kpl_reason_tech"]: sc -= 4
    return sc

dfr["sc4"] = [score_v4(row) for _, row in dfr.iterrows()]

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

idx_5m = {(k[0], k[2]): v for k, v in bars_5m.items()}
def get_df_k(c6, b_dt):
    v = idx_5m.get((c6, b_dt))
    return v if isinstance(v, pd.DataFrame) else pd.DataFrame()

def sim_trade(r, buy_mode, sell_mode):
    c6 = str(r.code).zfill(6); bars = code_bars[c6]; d2p = bars["p"][r.buy_date]
    b_op = float(bars["open"][d2p]); zt_px = float(bars["zt_px"][d2p])
    df_k = get_df_k(c6, r.buy_date); imap = SH_MAP if r.ex == "SH" else SZ_MAP
    # Buy
    if buy_mode == "red_auc":
        if not (0.0 <= r.op2 <= 0.045) or b_op >= zt_px - 0.011: return None
        buy_px, is_auc = b_op, True
    elif buy_mode == "band_m2":
        if not (-0.02 <= r.op2 <= 0.045) or b_op >= zt_px - 0.011: return None
        buy_px, is_auc = b_op, True
    elif buy_mode == "morn_cond":
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
    # Sell
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

    if bars["is_zt"][d2p]:
        ep, epx, eo = run_zt_loop(d2p)
    else:
        p = min(d2p + 1, n - 1)
        while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
        d2_c = float(bars["close"][d2p]); d2_ret = d2_c / buy_px - 1.0
        d3_op_pct = float(bars["open"][p]) / float(bars["pre_c"][p]) - 1.0
        if sell_mode == "S_cut_weak":
            # 极简手操：买入日亏超2%或收绿阴线且浮亏 -> 次日09:25竞价一键走；买入日抗住收红/浮盈 -> 若次日核按钮<-3.5%竞价走，否则拿至收盘(涨停转锁仓)
            if d2_ret <= -0.02 or (d2_c < b_op and d2_ret < 0) or d3_op_pct <= -0.035:
                ep, epx, eo = p, float(bars["open"][p]), True
            elif bars["is_zt"][p]:
                ep, epx, eo = run_zt_loop(p)
            else:
                ep, epx, eo = p, float(bars["close"][p]), False
        elif sell_mode == "S_pure_auc":
            ep, epx, eo = p, float(bars["open"][p]), True
        elif sell_mode == "S_hold_d3":
            if bars["is_zt"][p]: ep, epx, eo = run_zt_loop(p)
            else: ep, epx, eo = p, float(bars["close"][p]), False

    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2p]) * (1.0 - FEE) - 1.0
    return {"buy_date": r.buy_date, "exit_date": bars["dts"][ep], "code": c6, "name": r.name, "sc": r.sc4, "net_ret": float(ret), "b_open_h": is_auc, "eo": eo}

def eval_combo(th, buy_m, sell_m, cb):
    rows = [x for r in dfr[dfr["sc4"] >= th].itertuples() if (x := sim_trade(r, buy_m, sell_m)) is not None]
    if not rows: return pd.DataFrame()
    tdf = pd.DataFrame(rows).sort_values(["buy_date", "sc"], ascending=[True, False])
    taken, fd, peo, cl, sk = [], "", False, 0, False
    for r in tdf.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            if cb and sk:
                fd, peo = r.exit_date, r.eo
                if r.net_ret > 0: sk, cl = False, 0
                continue
            taken.append(r); fd, peo = r.exit_date, r.eo
            if r.net_ret < -0.02:
                cl += 1
                if cl >= 2: sk = True
            elif r.net_ret > 0: cl = 0
    return pd.DataFrame(taken)

def fmt_p(led, s_dt, e_dt):
    w = led[(led["buy_date"] >= s_dt) & (led["buy_date"] <= e_dt)]
    csi_r = (CSI_MAP[e_dt] / CSI_MAP[s_dt] - 1.0) * 100
    if w.empty: return f"0笔 (CSI={csi_r:+.1f}%)"
    rets = w["net_ret"].values; nav = float(np.prod(1.0 + rets))
    eq = float(np.prod(1.0 + w.groupby("buy_date")["net_ret"].mean().values))
    pk, cur, mdd = 1.0, 1.0, 0.0
    for x in rets: cur *= (1.0 + x); pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
    wr = float(np.mean(rets > 0) * 100)
    pos, neg = rets[rets > 0], np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    sr = np.sort(rets); t5 = float(np.prod(1.0 + (sr[:-5] if len(sr) > 5 else np.array([0.0]))))
    ex = (nav - 1.0) * 100 - csi_r
    return f"{len(w):2d}b WR={wr:4.1f}% PL={plr:4.2f} NAV={nav:6.2f}x EQ={eq:5.2f}x T5={t5:5.2f}x MDD={mdd*100:4.1f}% ExCSI={ex:+.1f}pp"

dfr.to_pickle(f"{OUT_DIR}/v5_enriched_119.pkl")
print(f"CSI300 Benchmarks: 22-24={(CSI_MAP['2024-12-31']/CSI_MAP['2022-01-04']-1)*100:+.2f}% | 25-26={(CSI_MAP['2026-11-12']/CSI_MAP['2025-01-02']-1)*100:+.2f}% | 24-26={(CSI_MAP['2026-11-12']/CSI_MAP['2024-01-02']-1)*100:+.2f}% | 22-26={(CSI_MAP['2026-11-12']/CSI_MAP['2022-01-04']-1)*100:+.2f}%")
for th in [84, 88]:
    for bm in ["red_auc", "morn_cond"]:
        for sm in ["S_cut_weak", "S_hold_d3", "S_pure_auc"]:
            l_no = eval_combo(th, bm, sm, False)
            l_cb = eval_combo(th, bm, sm, True)
            yrs_no = " ".join(f"{y[2:]}:{float(np.prod(1+l_no[(l_no['buy_date']>=f'{y}-01-01')&(l_no['buy_date']<=f'{y}-12-31')]['net_ret'].values)):.2f}x" for y in ["2022","2023","2024","2025","2026"])
            yrs_cb = " ".join(f"{y[2:]}:{float(np.prod(1+l_cb[(l_cb['buy_date']>=f'{y}-01-01')&(l_cb['buy_date']<=f'{y}-12-31')]['net_ret'].values)):.2f}x" for y in ["2022","2023","2024","2025","2026"])
            print(f"\n[V4>={th} | {bm:9s} | {sm:10s}]")
            print(f"  NoCB 5Y: {fmt_p(l_no,'2022-01-04','2026-11-12')} | {yrs_no}")
            print(f"  CB   5Y: {fmt_p(l_cb,'2022-01-04','2026-11-12')} | {yrs_cb}")
            print(f"  22-24(CB): {fmt_p(l_cb,'2022-01-04','2024-12-31')} || 25-26(CB): {fmt_p(l_cb,'2025-01-02','2026-11-12')} || 24-26(CB): {fmt_p(l_cb,'2024-01-02','2026-11-12')}")
            if th == 88 and bm == "morn_cond" and sm == "S_cut_weak":
                l_cb.to_csv(f"{OUT_DIR}/v5_morn_cutweak_cb_ledger.csv", index=False)
            if th == 84 and bm == "red_auc" and sm == "S_hold_d3":
                l_no.to_csv(f"{OUT_DIR}/v5_redauc_hold_nocb_ledger.csv", index=False)
