#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
完整复现基准环境并严格测试 V2 vs V3 vs V4 打分卡
- 严守零未来函数（100% PIT）
- 单仓净值、按日等权净值、去Top5净值、胜率、盈亏比、最大回撤
- 2022-2024 (前三年熊市/震荡) vs 2025-2026 (近两年牛市/反弹) 双期同向检验
"""
import pickle, re, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
FEE = 0.0020

# 1. 加载数据
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_DIR}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_DIR}/sub1_kpl_enriched.pkl")
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

def get_dev_px(bars, cp, idx_map, disc=0.07):
    cd = bars["dts"][cp]; ir = idx_map.get(cd)
    if not ir: return 99999.0
    bp_min = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = idx_map.get(bars["dts"][p]); bc = bars["close"][p]
        if bi and bc > 0:
            pl = bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0))
            if pl < bp_min: bp_min = pl
    return bp_min

def sim_exit_e2(bars, d2_p, buy_px, idx_map, smart_bounce=False, yang_immune=False):
    d2_zt = bool(bars["is_zt"][d2_p])
    d2_c_ret = bars["close"][d2_p] / buy_px - 1.0
    n = len(bars["dts"])
    ep, epx, eo = None, None, False
    if d2_zt:
        imm = False
        for step in range(1, 8):
            p = d2_p + step
            if p >= n: break
            pl = get_dev_px(bars, p, idx_map, 0.07)
            if bars["open"][p] >= pl: ep, epx, eo = p, bars["open"][p], True; break
            elif bars["high"][p] >= pl: ep, epx, eo = p, pl, False; break
            if not bars["is_zt"][p]:
                if yang_immune and (not imm) and (bars["close"][p] > bars["open"][p]):
                    imm = True; continue
                while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                ep, epx, eo = p, bars["close"][p], False; break
    else:
        p = min(d2_p + 1, n - 1)
        if smart_bounce and d2_c_ret <= -0.04 and (not bars["is_yizi_dt"][p]):
            bt = bars["pre_c"][p] * 1.015
            if bars["open"][p] >= bt: ep, epx, eo = p, bars["open"][p], True
            elif bars["high"][p] >= bt: ep, epx, eo = p, bt, False
        if ep is None:
            while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
            ep, epx, eo = p, bars["close"][p], False
    if ep is None:
        ep = min(d2_p + 5, n - 1); epx, eo = bars["close"][ep], False
    ret = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2_p]) * (1.0 - FEE) - 1.0
    return bars["dts"][ep], float(ret), max(1, ep - d2_p), eo

csi5_l, lh1_l, qu1_l, in1_l, ign_ok_l, hyb_l, obc_l, pelo_l, fmv_l = [], [], [], [], [], [], [], [], []
for r in dfr.itertuples():
    i1 = dt_to_idx[r.d1]
    csi5_l.append(CSI_MAP[r.d1] / CSI_MAP[all_dts[max(0, i1-5)]] - 1.0)
    a1 = lhb_clean.get((r.d1, r.code), (0,0.0,0,0))
    lh1_l.append(a1[0]); qu1_l.append(a1[2]); in1_l.append(a1[3])
    m = c1_map.get((r.buy_date, r.code))
    obc_l.append(int(getattr(m, "open_board_count", 0)) if m else 0)
    pelo_l.append(float(getattr(m, "p_elo", 120.0)) if m else 120.0)
    fmv_l.append(float(getattr(m, "float_mv", 50e8)) / 1e8 if m and pd.notna(getattr(m, "float_mv", np.nan)) else 50.0)
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

dfr["csi5"], dfr["lh1"], dfr["qu1"], dfr["in1"], dfr["can_ign"], dfr["hyb_sm"], dfr["obc"], dfr["pelo"], dfr["fmv_yi"] = csi5_l, lh1_l, qu1_l, in1_l, ign_ok_l, hyb_l, obc_l, pelo_l, fmv_l
dfr["b_open_h"] = dfr["op2"] >= 0.0

# 2. 打分卡体系定义
def score_v2(r):
    if r["s_reg"] or r["tox"] or r["ex_reg5"] >= 2 or r["d1_to"] > 38.0 or r["lh1"] >= 3 or r["op2"] > 0.045 or r["op2"] < -0.065:
        return -999
    sc = 60
    if r["brk_r10"] >= 0.20: sc += 12
    else: sc -= 8
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
    return sc

def score_v3_14f(r):
    sc = score_v2(r)
    if sc < 0: return -999
    # 新增 5 个高标专属双期同向真因子
    if r["low_price_le20"]: sc += 5
    elif r["high_price_gt35"]: sc -= 10
    if r["turn_boards_ge4"]: sc += 5
    elif r["turn_boards_cnt"] <= 2: sc -= 5
    if r["d1_deep_dip_le6"]: sc += 5
    if r["lock"] >= 45.0: sc += 4
    elif r["lock"] < 25.0: sc -= 4
    if r["qu1"] >= 1 and r["lh1"] <= 1: sc += 4
    return sc

def score_v4_kpl(r):
    sc = score_v3_14f(r)
    if sc < 0: return -999

    # 【老妖记忆真因子】
    if r["kpl_hist_1y_has_ge5"]: sc += 6      # 过去1年曾走出>=5连板妖股 (+7.99%)
    elif r["kpl_hist_3y_has_ge5"]: sc += 3    # 过去3年曾走出>=5连板妖股 (+3.63%)
    
    # 【老票新炒 vs 蹭概念甄别】
    if r["kpl_old_stock_old_theme"]: sc += 3  # 纯正老题材老熟票 (+1.35%)
    elif r["kpl_old_stock_new_theme"]: sc -= 5# 老熟票蹭陌生新概念 (-2.49%)

    # 【龙虎榜游资行为与避坑】
    if r["lhb_d0_top_locked"]: sc += 5        # D0顶级游资买入且D1锁仓未出 (+4.47%)
    if r["lhb_d1_lhasa_heavy"]: sc -= 10      # D1拉萨买入占比>=20%散户踩踏坑 (-6.00%)
    if r["lhb_d1_net_positive"]: sc -= 5     # D1龙虎榜总买远大于总卖高位接盘 (-4.77%)
    if r["lhb_d0_day_surf_buy"]: sc -= 6     # D0上塘路/消闲派一日游砸盘席位 (-3.46%)

    # 【开盘啦微观盘口】
    if r["kpl_d0_seal_early_0935"]: sc -= 5   # D0 09:35前秒封极度一致次日大分歧 (-4.56%)
    if r["kpl_reason_tech"]: sc -= 4          # 高位科技股机构量化沉重抛压 (-4.66%)

    return sc

dfr["sc2"] = [score_v2(row) for _, row in dfr.iterrows()]
dfr["sc3"] = [score_v3_14f(row) for _, row in dfr.iterrows()]
dfr["sc4"] = [score_v4_kpl(row) for _, row in dfr.iterrows()]

def run_sim(col, th, use_cb=True):
    sub = dfr[(dfr[col] >= th) & dfr["can_ign"]].copy()
    rs = []
    for r in sub.itertuples():
        ed, rt, hb, eo = r.hyb_sm
        rs.append({
            "buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name,
            "sc": getattr(r, col), "net_ret": rt, "b_open_h": r.b_open_h, "eo": eo,
            "d0": r.d0, "d1": r.d1
        })
    tdf = pd.DataFrame(rs).sort_values(["buy_date", "sc"], ascending=[True, False])
    taken, fd, peo = [], "", False
    consec_loss, skip_next = 0, False
    for r in tdf.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            if use_cb and skip_next:
                fd = r.exit_date; peo = r.eo
                if r.net_ret > 0:
                    skip_next = False; consec_loss = 0
                continue
            taken.append(r); fd = r.exit_date; peo = r.eo
            if r.net_ret < -0.02:
                consec_loss += 1
                if consec_loss >= 2: skip_next = True
            elif r.net_ret > 0:
                consec_loss = 0
    return pd.DataFrame(taken)

def calc_daily_equal_weight_nav(sub_df):
    if sub_df.empty: return 1.0
    by_day = sub_df.groupby("buy_date")["net_ret"].mean()
    nav = 1.0
    for r in by_day:
        nav *= (1.0 + r)
    return nav

def stats_period(led, s_dt, e_dt):
    w = led[(led["buy_date"] >= s_dt) & (led["buy_date"] <= e_dt)]
    if w.empty: return "0笔"
    rets = w["net_ret"].values
    nav = float(np.prod(1.0 + rets))
    eq_nav = calc_daily_equal_weight_nav(w)
    pk, cur, mdd = 1.0, 1.0, 0.0
    for x in rets:
        cur *= (1.0 + x); pk = max(pk, cur); mdd = max(mdd, (pk - cur) / pk)
    wr = float(np.mean(rets > 0) * 100)
    pos, neg = rets[rets > 0], np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    sr = np.sort(rets)
    t5 = float(np.prod(1.0 + (sr[:-5] if len(sr) > 5 else np.array([0.0]))))
    return f"{len(w):2d}笔 WR={wr:4.1f}% PLR={plr:4.2f} 单仓={nav:6.2f}x 等权={eq_nav:5.2f}x 去Top5={t5:5.2f}x MDD={mdd*100:4.1f}%"

print("="*95)
print("=== EXACT COMPARISON: V2 (9F) vs V3 (14F) vs V4 (20F KPL+YOUZI+MEMORY) ===")
print("="*95)

configs = [
    ("V2_9因子", "sc2", 80, True),
    ("V3_14因子", "sc3", 88, True),
    ("V3_14因子", "sc3", 90, True),
    ("V4_20因子_KPL", "sc4", 80, True),
    ("V4_20因子_KPL", "sc4", 82, True),
    ("V4_20因子_KPL", "sc4", 84, True),
    ("V4_20因子_KPL", "sc4", 86, True),
    ("V4_20因子_KPL", "sc4", 88, True),
    ("V4_20因子_KPL", "sc4", 90, True),
]

for label, col, th, cb in configs:
    led = run_sim(col, th, cb)
    s_22_24 = stats_period(led, "2022-01-04", "2024-12-31")
    s_25_26 = stats_period(led, "2025-01-02", "2026-11-12")
    s_3y = stats_period(led, "2024-01-02", "2026-11-12")
    s_5y = stats_period(led, "2022-01-04", "2026-11-12")
    yrs = " | ".join(f"{y}:{float(np.prod(1+led[(led['buy_date']>=f'{y}-01-01')&(led['buy_date']<=f'{y}-12-31')]['net_ret'].values)):.2f}x({len(led[(led['buy_date']>=f'{y}-01-01')&(led['buy_date']<=f'{y}-12-31')])}b)" for y in ["2022","2023","2024","2025","2026"])
    print(f"\n[{label} Thr>={th} CB={cb}]")
    print(f"  22-24 : {s_22_24}")
    print(f"  25-26 : {s_25_26}")
    print(f"  近3年 : {s_3y}")
    print(f"  5Y全期: {s_5y}")
    print(f"  逐年  : {yrs}")

    if label == "V4_20因子_KPL" and th == 84:
        led.to_csv(f"{OUT_DIR}/sub1_v4_ledger.csv", index=False)
        print(f"  --> Saved {OUT_DIR}/sub1_v4_ledger.csv")
