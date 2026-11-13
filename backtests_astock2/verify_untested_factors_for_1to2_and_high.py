#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""预核验：筛查一进二V17、五板高标、高标首阴V3「尚未开发」且真实提升胜率或赔率的增量因子"""
import sqlite3, pickle, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_HD = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"

# 加载公共只读底座
(all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, lhb_lh, lhb_in, lhb_qu, stock_reg, ex_reg, tox_dates, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{OUT_HD}/part1_cache.pkl", "rb"))
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
df_1b = pd.read_parquet(f"{MAT_DIR}/cand_0to1_firstboard.parquet")
df_34 = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock2/data_5y/cand_3to4_enriched54.parquet")

# 构造每日市场环境字典: 最高板、涨停数、3板+跌停数、沪深300涨跌、重点监控期
mkt_info = {}
for i, d in enumerate(all_dts):
    g = by_dt.get(d)
    if g is None: continue
    zt_g = g[g["is_zt"]]
    max_b = int(zt_g["streak"].max()) if len(zt_g) > 0 else 0
    n_zt = int(len(zt_g))
    # 当日昨日>=3板但今天跌停的家数
    dt3_cnt = 0
    if i > 0:
        gp = by_dt.get(all_dts[i-1])
        if gp is not None:
            hi_codes = set(gp[gp["streak"] >= 3]["c6"])
            if hi_codes:
                sub = g[g["c6"].isin(hi_codes)]
                dt3_cnt = int((sub["close"] <= sub["pre_c"] * 0.903).sum())
    c0 = CSI_MAP.get(d)
    c1 = CSI_MAP.get(all_dts[i-1]) if i >= 1 else None
    c5 = CSI_MAP.get(all_dts[i-5]) if i >= 5 else None
    r1 = (c0 / c1 - 1.0) if (c0 and c1) else 0.0
    r5 = (c0 / c5 - 1.0) if (c0 and c5) else 0.0
    # 近5日交易所重点监控密度
    w5 = all_dts[max(0, i-4):i+1]
    ex_cnt5 = sum(len(ex_reg.get(x, [])) for x in w5)
    mkt_info[d] = {"max_b": max_b, "n_zt": n_zt, "dt3_cnt": dt3_cnt, "csi1": r1, "csi5": r5, "ex5": ex_cnt5}

def get_lock(c6, dt):
    arr = holders.get(c6)
    if not arr: return np.nan
    # arr format check
    best = np.nan
    for item in arr:
        if item[0] <= dt: best = float(item[-1])
        else: break
    return best

def stat_bucket(sub, ret_col="net_ret"):
    if len(sub) == 0: return "N=0"
    r = sub[ret_col].dropna().values
    if len(r) == 0: return "N=0"
    wr = (r > 0).mean() * 100
    w = r[r > 0].mean() if (r > 0).any() else 0.0
    l = abs(r[r <= 0].mean()) if (r <= 0).any() else 0.01
    po = w / max(l, 1e-4)
    return f"N={len(r):3d} | WR={wr:5.1f}% | PO={po:4.2f} | Mean={r.mean()*100:+6.2f}%"

# ==============================================================================
# 1. 核验【一进二 V17 真实96笔账本】上尚未开发的增量因子
# ==============================================================================
print("=== [A] 一进二 V17 (96笔真实成交账本) 未开发因子检验 ===")
v17 = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock/full_day_by_day_v17_ledger.csv")
v17["c6"] = v17["c6"].astype(str).str.zfill(6)

rows_a = []
for r in v17.itertuples():
    idx2 = dt_to_idx.get(r.buy_date, -1)
    d1 = all_dts[idx2 - 1] if idx2 > 0 else ""
    mi = mkt_info.get(d1, {})
    lk = get_lock(r.c6, r.buy_date)
    bars = code_bars.get(r.c6)
    p1 = bars["p"].get(d1, -1) if bars else -1
    px1 = float(bars["close"][p1]) if p1 >= 0 else np.nan
    # 自由流通盘: 取 df_1b 里的 float_mv
    lh1 = lhb_lh.get((r.c6, d1), 0)
    qu1 = lhb_qu.get((r.c6, d1), 0)
    in1 = lhb_in.get((r.c6, d1), 0)
    s_reg = any(r.c6 in stock_reg.get(all_dts[k], set()) for k in range(max(0, idx2-10), idx2))
    rows_a.append({
        "buy_date": r.buy_date, "c6": r.c6, "name": r.name, "net_ret": r.net_ret,
        "buy_px": r.buy_price, "px1": px1, "lock": lk,
        "lh1": lh1, "qu1": qu1, "in1": in1, "s_reg": s_reg,
        "ex5": mi.get("ex5", 0), "n_zt1": mi.get("n_zt", 50),
        "max_b1": mi.get("max_b", 4), "dt3_1": mi.get("dt3_cnt", 0),
        "csi1": mi.get("csi1", 0.0), "csi5": mi.get("csi5", 0.0),
    })
dfa = pd.DataFrame(rows_a)
print("df_1b cols:", list(df_1b.columns)[:15])
print("V17 全样本:", stat_bucket(dfa), "| 24-26:", stat_bucket(dfa[dfa["buy_date"]>="2024-01-01"]))
for label, cond in [
    ("股价 <= 20元", dfa["px1"] <= 20.0),
    ("股价 > 25元", dfa["px1"] > 25.0),
    ("大股东锁仓 >= 45%", dfa["lock"] >= 45.0),
    ("大股东锁仓 < 35%", dfa["lock"] < 35.0),
    ("首板龙虎榜拉萨席位 >= 2", dfa["lh1"] >= 2),
    ("首板知名量化席位 >= 1", dfa["qu1"] >= 1),
    ("前日全市场涨停 >= 95(高潮分化)", dfa["n_zt1"] >= 95),
    ("前日沪深300急杀(1d<=-2%或5d<=-3%)", (dfa["csi1"] <= -0.02) | (dfa["csi5"] <= -0.03)),
    ("前日3板+断板跌停 >= 2家", dfa["dt3_1"] >= 2),
    ("前日全场最高板 <= 4(空间未透支)", dfa["max_b1"] <= 4),
    ("前日全场最高板 >= 7(高标虹吸期)", dfa["max_b1"] >= 7),
    ("近5日交易所重点监控 >= 2次", dfa["ex5"] >= 2),
]:
    s_all = dfa[cond]
    s_rec = dfa[cond & (dfa["buy_date"] >= "2024-01-01")]
    print(f"  {label:30s} | 5Y: {stat_bucket(s_all)} || 24-26: {stat_bucket(s_rec)}")

# 额外看一进二全量首板池(高开2%~8%可买池)上这些未开发因子的普适单调性
print("\n=== [A2] 一进二全市场可买高开池 (N>5000) 普适检验 ===")
# 在 df_1b 中测试: df_1b 的 buy_date 是首板日 d1! 次日 d2 收益从 code_bars 算
rows_1b = []
for r in df_1b[df_1b["is_zt_today"] == True].itertuples():
    c6 = str(r.code)[:6]
    bars = code_bars.get(c6)
    if not bars: continue
    p1 = bars["p"].get(r.buy_date, -1)
    if p1 < 0 or p1 + 2 >= len(bars["dts"]): continue
    o2, c2, zt2 = bars["open"][p1+1], bars["close"][p1+1], bars["zt_px"][p1+1]
    c1 = bars["close"][p1]
    if o2 >= zt2 - 0.01 or c1 <= 0: continue
    op2 = o2 / c1 - 1.0
    if not (0.02 <= op2 <= 0.08): continue
    c3 = bars["close"][p1+2]
    ret = (c3 / o2) * 0.9985 - 1.0
    lk = get_lock(c6, bars["dts"][p1+1])
    fmv_raw = getattr(r, "float_mv", getattr(r, "mcap", 40.0))
    fmv = float(fmv_raw) / 1e8 if pd.notna(fmv_raw) and fmv_raw > 1e6 else (float(fmv_raw) if pd.notna(fmv_raw) else 40.0)
    rfmv = fmv * (1.0 - (lk if pd.notna(lk) else 35.0)/100.0)
    mi = mkt_info.get(r.buy_date, {})
    rows_1b.append({
        "d2": bars["dts"][p1+1], "net_ret": ret, "px1": c1, "lock": lk, "fmv": fmv, "rfmv": rfmv,
        "lh1": lhb_lh.get((c6, r.buy_date), 0), "qu1": lhb_qu.get((c6, r.buy_date), 0),
        "n_zt1": mi.get("n_zt", 50), "dt3_1": mi.get("dt3_cnt", 0),
        "csi_drop": (mi.get("csi1", 0) <= -0.02) or (mi.get("csi5", 0) <= -0.03),
        "ex5": mi.get("ex5", 0), "max_b1": mi.get("max_b", 4),
    })
df1_pool = pd.DataFrame(rows_1b)
rec1 = df1_pool[df1_pool["d2"] >= "2024-01-01"]
print("1进2高开基准(24-26):", stat_bucket(rec1))
for lb, m in [
    ("股价<=20元", rec1["px1"] <= 20), ("股价>30元", rec1["px1"] > 30),
    ("锁仓>=45%", rec1["lock"] >= 45), ("锁仓<30%", rec1["lock"] < 30),
    ("真实自由流通盘<=35亿", rec1["rfmv"] <= 35), ("真实自由流通盘>80亿", rec1["rfmv"] > 80),
    ("拉萨席位==0", rec1["lh1"] == 0), ("拉萨席位>=3", rec1["lh1"] >= 3),
    ("前日百股涨停>=95", rec1["n_zt1"] >= 95), ("前日沪深300急杀", rec1["csi_drop"]),
    ("前日高位跌停>=2", rec1["dt3_1"] >= 2), ("近5日重点监控>=2", rec1["ex5"] >= 2),
]:
    print(f"  {lb:24s} | 24-26: {stat_bucket(rec1[m])}")

# ==============================================================================
# 2. 核验【高标五板买点 s_high_5ban】未开发的胜率与赔率因子
# ==============================================================================
print("\n=== [B] 高标五板买点 (verified_1a_5ban_cands) 未开发因子检验 ===")
import glob
p5_list = glob.glob(f"{ROOT}/sim-portfolio/**/verified_1a_5ban_cands.parquet", recursive=True) + glob.glob(f"{MAT_DIR}/*high*.parquet")
df5 = pd.read_parquet(p5_list[0])
print("Loaded 5ban/high:", p5_list[0], df5.shape, list(df5.columns)[:12])
# 构建同题材首板一字/换手高开字典 (按首板日 d0 -> 次日 d1 09:25 竞价)
fb_zt = df_1b[(df_1b["is_zt_today"] == True) & (df_1b["plate"].notna()) & (df_1b["plate"] != "其他")].copy()
fb_next = []
for r in fb_zt.itertuples():
    c6 = str(r.code)[:6]
    bars = code_bars.get(c6)
    if not bars: continue
    p0 = bars["p"].get(r.buy_date, -1)
    if p0 < 0 or p0 + 1 >= len(bars["dts"]): continue
    o1, zt1, c0 = bars["open"][p0+1], bars["zt_px"][p0+1], bars["close"][p0]
    yz1 = (o1 >= zt1 - 0.01)
    ho1 = (not yz1) and (c0 > 0) and (o1 / c0 - 1.0 >= 0.03)
    fb_next.append((r.buy_date, r.plate, int(yz1), int(ho1), (o1/c0 - 1.0) if c0>0 else 0.0))
df_fbn = pd.DataFrame(fb_next, columns=["sig_d", "plate", "yz1", "ho1", "op1"])
fbn_agg = df_fbn.groupby(["sig_d", "plate"]).agg(yz_cnt=("yz1", "sum"), ho_cnt=("ho1", "sum"), peer_op=("op1", "mean")).to_dict(orient="index")

# 题材映射: 从 df_1b 取 (code, date) 最近的 plate
plate_map = {}
for r in df_1b[df_1b["plate"].notna()].itertuples():
    plate_map[(str(r.code)[:6], r.buy_date)] = r.plate

rows_5b = []
for r in df5.itertuples():
    c6 = str(r.code)[:6]
    bd = str(r.buy_date)[:10]
    bars = code_bars.get(c6)
    if not bars: continue
    pb = bars["p"].get(bd, -1)
    if pb < 5 or pb + 1 >= len(bars["dts"]): continue
    o_b, zt_b, c_prev = bars["open"][pb], bars["zt_px"][pb], bars["close"][pb-1]
    if o_b >= zt_b - 0.01 or c_prev <= 0: continue # 排除一字不可买
    op_pct = o_b / c_prev - 1.0
    sig_d = bars["dts"][pb-1]
    lk = get_lock(c6, bd)
    # 找 5板期间的题材
    pl = "其他"
    for k in range(pb-5, pb):
        p_try = plate_map.get((c6, bars["dts"][k]))
        if p_try and p_try != "其他": pl = p_try
    fa = fbn_agg.get((sig_d, pl), {"yz_cnt": 0, "ho_cnt": 0, "peer_op": 0.0})
    mi = mkt_info.get(sig_d, {})
    # 前5板真实换手板数
    turn_cnt = sum(1 for k in range(pb-5, pb) if bars["is_zt"][k] and (not bars["is_yizi"][k]))
    # 计算持有到断板的真实收益 vs 若断板日高点>=8%回落收跌则按+5%护利止盈的赔率提升
    k_cur = pb
    while k_cur < len(bars["dts"]) - 1 and bars["is_zt"][k_cur] and (k_cur - pb < 8):
        k_cur += 1
    exit_c = bars["close"][k_cur]
    exit_h = bars["high"][k_cur]
    exit_pre = bars["close"][k_cur-1]
    ret_raw = (exit_c / o_b) * 0.9985 - 1.0
    # 若断板日曾摸高>=+8.5%而后回落破+5%收低，动态护利锁在pre*1.05
    if (not bars["is_zt"][k_cur]) and exit_pre > 0 and (exit_h / exit_pre - 1.0 >= 0.085) and (exit_c / exit_pre - 1.0 < 0.045):
        exit_protect = exit_pre * 1.05
    else:
        exit_protect = exit_c
    ret_prot = (exit_protect / o_b) * 0.9985 - 1.0
    rows_5b.append({
        "bd": bd, "c6": c6, "op": op_pct, "lock": lk, "px": c_prev, "pl": pl,
        "yz_cnt": fa["yz_cnt"], "ho_cnt": fa["ho_cnt"], "peer_op": fa["peer_op"],
        "turn_cnt": turn_cnt, "max_b": mi.get("max_b", 5), "n_zt": mi.get("n_zt", 50),
        "csi_drop": (mi.get("csi1", 0) <= -0.02) or (mi.get("csi5", 0) <= -0.03),
        "dt3_cnt": mi.get("dt3_cnt", 0), "ex5": mi.get("ex5", 0),
        "net_ret": ret_raw, "ret_prot": ret_prot,
        "in_handbook": (op_pct <= 0.055) and pd.notna(lk) and (lk >= 50.0),
    })
df5_clean = pd.DataFrame(rows_5b)
print("五板可买全池(5Y):", stat_bucket(df5_clean), "| 护利出场:", stat_bucket(df5_clean, "ret_prot"))
hb5 = df5_clean[df5_clean["in_handbook"]]
print("现行五板手册(op<=5.5%&lock>=50%):", stat_bucket(hb5), "| 护利出场:", stat_bucket(hb5, "ret_prot"))
rec5 = df5_clean[df5_clean["bd"] >= "2024-01-01"]
print("五板可买近三年(24-26):", stat_bucket(rec5), "| 护利出场:", stat_bucket(rec5, "ret_prot"))
for lb, m5, mr in [
    ("同题材首板顶一字>=1(反噬)", df5_clean["yz_cnt"] >= 1, rec5["yz_cnt"] >= 1),
    ("同题材换手首板>=2且零一字(真助攻)", (df5_clean["ho_cnt"] >= 2) & (df5_clean["yz_cnt"] == 0), (rec5["ho_cnt"] >= 2) & (rec5["yz_cnt"] == 0)),
    ("前5板换手板>=4(换手成龙)", df5_clean["turn_cnt"] >= 4, rec5["turn_cnt"] >= 4),
    ("前5板换手板<=2(连一字虚高)", df5_clean["turn_cnt"] <= 2, rec5["turn_cnt"] <= 2),
    ("全场唯一最高板(max_b==5无压制)", df5_clean["max_b"] == 5, rec5["max_b"] == 5),
    ("头顶有更高板压制(max_b>=6)", df5_clean["max_b"] >= 6, rec5["max_b"] >= 6),
    ("股价<=20元", df5_clean["px"] <= 20, rec5["px"] <= 20),
    ("股价>30元", df5_clean["px"] > 30, rec5["px"] > 30),
    ("前日百股涨停>=95(高潮抱团最高标)", df5_clean["n_zt"] >= 95, rec5["n_zt"] >= 95),
    ("前日沪深300急杀(抱团避险最高标)", df5_clean["csi_drop"], rec5["csi_drop"]),
    ("前日高位跌停>=2", df5_clean["dt3_cnt"] >= 2, rec5["dt3_cnt"] >= 2),
]:
    print(f"  {lb:34s} | 5Y: {stat_bucket(df5_clean[m5])} || 24-26: {stat_bucket(rec5[mr])}")

# ==============================================================================
# 3. 核验【高标首阴反包 V3 (dfr_deep_native)】尚未开发的增量因子
# ==============================================================================
print("\n=== [C] 高标首阴反包 V3 (dfr_deep_native 259笔) 未开发因子检验 ===")
dfr = pd.read_pickle(f"{OUT_HD}/dfr_deep_native.pkl").copy()
dfr["net_ret"] = dfr["ret_e2"]
# 挂载未开发因子: 同题材首板一字/竞价均值、前日高位跌停家数、单日沪深300急杀、冲高护利出场
yz_l, ho_l, pop_l, dt3_l, csi1_l, prot_l = [], [], [], [], [], []
for r in dfr.itertuples():
    c6 = str(r.code)[:6]
    bars = code_bars[c6]
    p1 = bars["p"][r.d1]; p2 = p1 + 1
    pl = "其他"
    for k in range(max(0, p1-6), p1+1):
        pt = plate_map.get((c6, bars["dts"][k]))
        if pt and pt != "其他": pl = pt
    fa = fbn_agg.get((r.d1, pl), {"yz_cnt": 0, "ho_cnt": 0, "peer_op": 0.0})
    mi = mkt_info.get(r.d1, {})
    yz_l.append(fa["yz_cnt"]); ho_l.append(fa["ho_cnt"]); pop_l.append(fa["peer_op"])
    dt3_l.append(mi.get("dt3_cnt", 0))
    csi1_l.append(mi.get("csi1", 0.0))
    # 检验反包买入日(p2)与次日(p2+1)若摸板炸板/冲高>=8.5%回落破4.5%主动护利 vs 死拿e2收盘
    o_buy = float(bars["open"][p2])
    ret_orig = float(r.ret_e2)
    if p2 + 1 < len(bars["dts"]):
        h_n, c_n, pre_n = float(bars["high"][p2+1]), float(bars["close"][p2+1]), float(bars["close"][p2])
        if (not bars["is_zt"][p2+1]) and pre_n > 0 and (h_n / pre_n - 1.0 >= 0.08) and (c_n / pre_n - 1.0 < 0.04):
            prot_l.append((pre_n * 1.045 / o_buy) * 0.9985 - 1.0)
        else:
            prot_l.append(ret_orig)
    else:
        prot_l.append(ret_orig)

dfr["yz_cnt"] = yz_l; dfr["ho_cnt"] = ho_l; dfr["peer_op"] = pop_l
dfr["dt3_cnt"] = dt3_l; dfr["csi1"] = csi1_l; dfr["ret_prot"] = prot_l
rec_d = dfr[dfr["buy_date"] >= "2024-01-01"]
print("首阴全池(5Y):", stat_bucket(dfr), "| 冲高护利:", stat_bucket(dfr, "ret_prot"))
print("首阴近三年(24-26):", stat_bucket(rec_d), "| 冲高护利:", stat_bucket(rec_d, "ret_prot"))
for lb, md, mr in [
    ("同题材首板顶一字>=1(低位抽血)", dfr["yz_cnt"] >= 1, rec_d["yz_cnt"] >= 1),
    ("同题材换手首板>=2且零一字", (dfr["ho_cnt"] >= 2) & (dfr["yz_cnt"] == 0), (rec_d["ho_cnt"] >= 2) & (rec_d["yz_cnt"] == 0)),
    ("同题材队友竞价均值<-1%(核按钮)", dfr["peer_op"] < -0.01, rec_d["peer_op"] < -0.01),
    ("前日3板+断板跌停>=2家(恐慌传导)", dfr["dt3_cnt"] >= 2, rec_d["dt3_cnt"] >= 2),
    ("前日3板+断板跌停==0家(情绪干净)", dfr["dt3_cnt"] == 0, rec_d["dt3_cnt"] == 0),
    ("前日沪深300单日急跌<=-2.0%", dfr["csi1"] <= -0.02, rec_d["csi1"] <= -0.02),
    ("10日100%异动空间<8%(空间锁死)", dfr["headroom_lt08"], rec_d["headroom_lt08"]),
    ("10日100%异动空间>=18%(空间充裕)", dfr["headroom_ge18"], rec_d["headroom_ge18"]),
]:
    print(f"  {lb:34s} | 5Y: {stat_bucket(dfr[md])} || 24-26: {stat_bucket(rec_d[mr])}")
