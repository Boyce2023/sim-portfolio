#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import pickle, pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_HD = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
MAT = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"

(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, _, _, _, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_HD}/part1_cache.pkl", "rb"))
dfr = pd.read_pickle(f"{OUT_HD}/v5_enriched_119.pkl")
led42 = pd.read_csv(f"{OUT_HD}/v5_morn_42_ledger.csv")
led42["code"] = led42["code"].astype(str).str.zfill(6)
dfr["code"] = dfr["code"].astype(str).str.zfill(6)

df_1c = pd.read_parquet(f"{MAT}/verified_1c_rebound_cands.parquet")
df_1c["c6"] = df_1c["code"].astype(str).str.zfill(6)
c1_map = {(str(r.buy_date)[:10], r.c6): r for r in df_1c.itertuples()}

def get_double_dev_px(bars, cp, idx_map, disc=0.00):
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

def st(r):
    r = np.asarray(r, dtype=float); r = r[~np.isnan(r)]
    if len(r) == 0: return "N=0"
    wr = (r > 0).mean() * 100
    w = r[r > 0].mean() if (r > 0).any() else 0.0
    l = abs(r[r <= 0].mean()) if (r <= 0).any() else 0.01
    return f"N={len(r):3d} WR={wr:5.1f}% PO={w/max(l,1e-4):4.2f} Mean={r.mean()*100:+6.2f}%"

# 为 dfr 119 笔计算 V5 尚未使用的候选新因子
hr_d2, real_to1, rfmcap, peer_op, pyz, dt3_prev, csi1_prev, c_pos, vr1, lead_g = [], [], [], [], [], [], [], [], [], []
for r in dfr.itertuples():
    c6 = r.code; bars = code_bars[c6]; d1p = bars["p"][r.d1]; d2p = bars["p"][r.buy_date]
    imap = SH_MAP if r.ex == "SH" else SZ_MAP
    p_lim = get_double_dev_px(bars, d2p, imap, 0.00)
    hr_d2.append(p_lim / float(bars["open"][d2p]) - 1.0)
    lk = float(r.lock) if pd.notna(r.lock) else 35.0
    free_ratio = max(0.10, 1.0 - lk / 100.0)
    real_to1.append(float(r.d1_to) / free_ratio)
    c1r = c1_map.get((r.buy_date, c6))
    rfmcap.append(float(getattr(c1r, "real_free_mcap", np.nan)) if c1r else np.nan)
    peer_op.append(float(getattr(c1r, "plate_peers_open_avg", np.nan)) if c1r else np.nan)
    pyz.append(int(getattr(c1r, "plate_yizi_cnt", 0)) if c1r else 0)
    dt3_prev.append(int(getattr(c1r, "prev_3b_dt_cnt", 0)) if c1r else 0)
    idx1 = dt_to_idx[r.d1]
    csi1_prev.append(CSI_MAP[r.d1] / CSI_MAP[all_dts[idx1-1]] - 1.0 if idx1 >= 1 else 0.0)
    rng = max(float(bars["high"][d1p] - bars["low"][d1p]), 0.01)
    c_pos.append(float(bars["close"][d1p] - bars["low"][d1p]) / rng)
    g1_row = by_dt[r.d1].set_index("c6").loc[c6]
    vr1.append(float(g1_row["d1_vol_r"]))
    g0 = by_dt[r.d0]; zt0 = g0[g0["is_zt"]]
    stks = sorted(zt0["streak"].unique(), reverse=True)
    sec_b = int(stks[1]) if len(stks) > 1 else 0
    lead_g.append(int(r.st0 - sec_b))

dfr["hr_dbl"] = hr_d2; dfr["real_to1"] = real_to1; dfr["rfmcap"] = rfmcap
dfr["peer_op"] = peer_op; dfr["pyz"] = pyz; dfr["dt3_prev"] = dt3_prev
dfr["csi1"] = csi1_prev; dfr["c_pos"] = c_pos; dfr["vr1"] = vr1; dfr["lead_g"] = lead_g

# 1. 在 V5 真实42笔成交账本上检验
m42 = led42.merge(dfr, on=["buy_date", "code"], how="left", suffixes=("", "_d"))
r42 = m42[m42["buy_date"] >= "2024-01-01"]
print(f"=== [高标 V5 真实42笔成交账本] Base 5Y: {st(m42['net_ret'])} || 24-26: {st(r42['net_ret'])} ===")
for nm, c5, cr in [
    ("双异动剩余空间>=18%(够连板空间)", m42["hr_dbl"]>=0.18, r42["hr_dbl"]>=0.18),
    ("双异动剩余空间<12%(买进即撞异动顶)", m42["hr_dbl"]<0.12, r42["hr_dbl"]<0.12),
    ("身位断层领先>=2板(绝对孤龙)", m42["lead_g"]>=2, r42["lead_g"]>=2),
    ("身位仅领先<=1板(身位紧咬)", m42["lead_g"]<=1, r42["lead_g"]<=1),
    ("首阴真实自由换手<=50%(锁筹良性)", m42["real_to1"]<=50, r42["real_to1"]<=50),
    ("首阴真实自由换手>50%(真实浮筹大派发)", m42["real_to1"]>50, r42["real_to1"]>50),
    ("首阴收盘处全天振幅>=65%(光头强承接)", m42["c_pos"]>=0.65, r42["c_pos"]>=0.65),
    ("首阴收盘处全天振幅<45%(长上影回落)", m42["c_pos"]<0.45, r42["c_pos"]<0.45),
    ("首阴量比温和0.75~1.80", m42["vr1"].between(0.75,1.80), r42["vr1"].between(0.75,1.80)),
    ("首阴量比极端(<0.75缩闷或>1.80爆量)", ~m42["vr1"].between(0.75,1.80), ~r42["vr1"].between(0.75,1.80)),
    ("同题材队友09:25竞价<-1.5%(队友核按钮)", m42["peer_op"]<-0.015, r42["peer_op"]<-0.015),
    ("同题材队友09:25竞价>=-1.5%", m42["peer_op"]>=-0.015, r42["peer_op"]>=-0.015),
    ("真实自由流通市值>25亿", m42["rfmcap"]>25, r42["rfmcap"]>25),
    ("真实自由流通市值<=25亿", m42["rfmcap"]<=25, r42["rfmcap"]<=25),
]:
    print(f"  {nm:36s} | 5Y: {st(m42.loc[c5,'net_ret'])} || 24-26: {st(r42.loc[cr,'net_ret'])}")

# 2. 在 119 笔高标首阴全候选池 (ret_e2) 上同步交叉检验样本稳定性
r119 = dfr[dfr["buy_date"] >= "2024-01-01"]
print(f"\n=== [高标首阴 119笔全候选池交叉核验] Base 5Y: {st(dfr['ret_e2'])} || 24-26: {st(r119['ret_e2'])} ===")
for nm, c5, cr in [
    ("双异动剩余空间>=18%", dfr["hr_dbl"]>=0.18, r119["hr_dbl"]>=0.18),
    ("双异动剩余空间<12%", dfr["hr_dbl"]<0.12, r119["hr_dbl"]<0.12),
    ("身位断层领先>=2板", dfr["lead_g"]>=2, r119["lead_g"]>=2),
    ("身位领先<=1板", dfr["lead_g"]<=1, r119["lead_g"]<=1),
    ("首阴真实自由换手<=50%", dfr["real_to1"]<=50, r119["real_to1"]<=50),
    ("首阴真实自由换手>50%", dfr["real_to1"]>50, r119["real_to1"]>50),
    ("首阴收盘分位>=65%", dfr["c_pos"]>=0.65, r119["c_pos"]>=0.65),
    ("首阴收盘分位<45%", dfr["c_pos"]<0.45, r119["c_pos"]<0.45),
    ("首阴量比0.75~1.80", dfr["vr1"].between(0.75,1.80), r119["vr1"].between(0.75,1.80)),
    ("首阴量比极端", ~dfr["vr1"].between(0.75,1.80), ~r119["vr1"].between(0.75,1.80)),
    ("前日沪深300单日跌<=-1.8%", dfr["csi1"]<=-0.018, r119["csi1"]<=-0.018),
    ("真实自由流通市值>25亿", dfr["rfmcap"]>25, r119["rfmcap"]>25),
    ("真实自由流通市值<=25亿", dfr["rfmcap"]<=25, r119["rfmcap"]<=25),
]:
    print(f"  {nm:36s} | 5Y: {st(dfr.loc[c5,'ret_e2'])} || 24-26: {st(r119.loc[cr,'ret_e2'])}")
