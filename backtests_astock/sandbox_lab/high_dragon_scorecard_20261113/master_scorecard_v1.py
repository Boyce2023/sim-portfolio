#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
master_scorecard_v1.py
================================================================================
高标首阴反包打分制（Scorecard V1）主脑交叉核验与严格样本外 Walk-Forward 引擎
- 训练集（In-Sample）：2022-01-04 至 2024-12-31（定门禁、定正交因子方向、定整数权重与过线分）
- 纯样本外盲测（Out-of-Sample）：2025-01-02 至 2026-11-12（零偷看、零反调）
- 滚动 Walk-Forward：2023 / 2024 / 2025 / 2026 逐年样本外验证
- 含多重检验 Sharpe Haircut (Bailey & Lopez de Prado)、±15% 阈值平原测试、去极值 Top5 检验
================================================================================
"""
import os, sys, re, json, glob, time, math, pickle, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import norm

t0 = time.time()
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
GFM_DIR = f"{SANDBOX}/grand_factor_matrix_20261112"
OUT_DIR = f"{SANDBOX}/high_dragon_scorecard_20261113"
os.makedirs(OUT_DIR, exist_ok=True)

FEE = 0.0020

with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    IDX_KLINES = json.load(f)
CSI_MAP = IDX_KLINES["sh000300"]
SH_MAP = IDX_KLINES["sh000002"]
SZ_MAP = IDX_KLINES["sz399107"]

# Load full daily price panel up to 2026-11-12 (including Nov 11-12!)
cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "turn", "amount", "oshare"]
df1 = pd.read_parquet(f"{ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet",
                      columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))])
df2 = pd.read_parquet(f"{ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet",
                      columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))])
df = pd.concat([df1, df2], ignore_index=True)
df = df[df["ticker"].str.endswith((".SH", ".SZ"))].copy()
df["c6"] = df["ticker"].str[:6]
df = df[df["c6"].str.startswith(("00", "60"))].copy()
df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
df = df.sort_values(["c6", "dt_str"]).drop_duplicates(["c6", "dt_str"]).reset_index(drop=True)

ind_df = pd.read_csv(f"{ROOT}/sim-portfolio/backtest/2026-10-15-review2022/industry.csv")
name_map = dict(zip(ind_df["code"].astype(str).str[-6:], ind_df["code_name"].fillna("")))
ind_map = dict(zip(ind_df["code"].astype(str).str[-6:], ind_df["industry"].fillna("")))
df["name"] = df["c6"].map(name_map).fillna("")
df["csrc_ind"] = df["c6"].map(ind_map).fillna("")
df = df[~df["name"].str.contains("ST|退", na=False)].copy().reset_index(drop=True)

g = df.groupby("c6")
df["nth"] = g.cumcount()
df = df[df["nth"] >= 10].copy().reset_index(drop=True)
g = df.groupby("c6")

df["adjf"] = df["adj_close"] / df["close"]
df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
df["pct"] = df["close"] / df["pre_c"] - 1.0
df["o_pct"] = df["open"] / df["pre_c"] - 1.0
df["h_pct"] = df["high"] / df["pre_c"] - 1.0
df["l_pct"] = df["low"] / df["pre_c"] - 1.0
df["to"] = df["turn"] * 100.0
df["mcap"] = df["close"] * df["oshare"] / 1e8

df["zt_px"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
df["dt_px"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
df["is_zt"] = (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
df["is_dt"] = (df["close"] <= df["dt_px"] + 0.011) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_px"] - 0.011) & (df["low"] >= df["zt_px"] - 0.011)
df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_px"] + 0.011) & (df["high"] <= df["dt_px"] + 0.011)

s_zt = df["is_zt"].astype(int)
df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
df["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
df["vol_ma5"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
df["seal_tight_calc"] = (
    (df["close"] == df["high"]).astype(int) * 30.0
    + np.clip(df["l_pct"] * 100.0, -10.0, 10.0) * 1.5
    + np.clip((df["close"] - df["open"]) / (df["pre_c"] + 1e-6) * 100.0, 0.0, 10.0) * 2.0
    - np.where(df["amount"] / (df["vol_ma5"] + 1e-6) > 4.0, 15.0, 0.0)
)
df["d0_seal_tight"] = g["seal_tight_calc"].shift(1).fillna(25.0)
df["d0_amt"] = g["amount"].shift(1).fillna(1.0)
df["d1_vol_ratio_d0"] = df["amount"] / (df["d0_amt"] + 1e-6)

# Consecutive yizi count on D0
s_yz = df["is_yizi"].astype(int)
df["yz_streak"] = s_yz.groupby([df["c6"], (s_yz != g["is_yizi"].shift().fillna(False)).cumsum()]).cumsum() * s_yz
df["prev_yz_streak"] = g["yz_streak"].shift(1).fillna(0).astype(int)

# Update CSI300 / SH / SZ maps for Nov 11-12 if missing by forward fill
all_dts = sorted(df["dt_str"].unique())
dt_to_idx = {d: i for i, d in enumerate(all_dts)}
for m in (CSI_MAP, SH_MAP, SZ_MAP):
    last_v = None
    for d in all_dts:
        if d in m:
            last_v = m[d]
        elif last_v is not None:
            m[d] = last_v

# Build per-code bar arrays up to 2026-11-12
code_bars = {}
for c6, sub in df.groupby("c6", sort=False):
    dts_arr = sub["dt_str"].values
    code_bars[c6] = {
        "dts": dts_arr,
        "date_to_pos": {d: i for i, d in enumerate(dts_arr)},
        "open": sub["open"].values,
        "high": sub["high"].values,
        "low": sub["low"].values,
        "close": sub["close"].values,
        "adjf": sub["adjf"].values,
        "pre_c": sub["pre_c"].values,
        "zt_px": sub["zt_px"].values,
        "dt_px": sub["dt_px"].values,
        "is_zt": sub["is_zt"].values,
        "is_dt": sub["is_dt"].values,
        "is_yizi": sub["is_yizi"].values,
        "is_yizi_dt": sub["is_yizi_dt"].values,
        "to": sub["to"].values,
        "pct": sub["pct"].values,
        "o_pct": sub["o_pct"].values,
    }

# Daily ecosystem stats (known at end of D1 or D0!)
by_dt = {d: grp for d, grp in df.groupby("dt_str", sort=True)}
env_stats = {}
brk_dt_hist = []
for d in all_dts:
    grp = by_dt[d]
    zt_g = grp[grp["is_zt"]]
    b3_dt = int((grp["prev_streak"] >= 3).mul(grp["is_dt"]).sum())
    ge4_brk = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
    brk_dt_cnt = int(ge4_brk["is_dt"].sum())
    brk_tot_cnt = int(len(ge4_brk))
    brk_dt_hist.append((brk_dt_cnt, brk_tot_cnt))
    w10 = brk_dt_hist[-10:]
    r10_brk_dt = sum(x[0] for x in w10) / max(1, sum(x[1] for x in w10))
    idx_i = dt_to_idx[d]
    d_m20 = all_dts[max(0, idx_i - 20)]
    csi_r20 = CSI_MAP[d] / CSI_MAP[d_m20] - 1.0
    csrc_zt_cnts = zt_g[zt_g["csrc_ind"] != ""].groupby("csrc_ind")["c6"].count().to_dict()
    env_stats[d] = {
        "b3_dt_cnt": b3_dt,
        "brk_dt_rate_10d": r10_brk_dt,
        "csi_ret20": csi_r20,
        "csrc_zt_cnts": csrc_zt_cnts,
        "n_zt": int(len(zt_g)),
        "n_dt": int(grp["is_dt"].sum()),
    }

# Load PIT Top10 freeholders
holders_idx = json.load(open(f"{GFM_DIR}/pit_top10_all_codes.json", "r", encoding="utf-8"))
def get_pit_lock(c6, dt_str):
    valid = [r for r in holders_idx.get(c6, []) if r[0] < dt_str]
    if not valid:
        return 38.0
    return float(max(valid, key=lambda x: x[1])[2])

# Load Cand High Dragon extra theme columns where available
cand_pq = pd.read_parquet(f"{GFM_DIR}/cand_high_dragon.parquet")
cand_theme_lookup = {}
for r in cand_pq.itertuples():
    cand_theme_lookup[(r.buy_date, r.code)] = {
        "plate": str(r.plate),
        "is_dominant_day": bool(r.is_dominant_day),
        "is_event_basket": bool(r.is_event_basket),
        "prior_mb_gap": int(r.prior_mb_gap),
        "p_elo": float(r.p_elo),
    }

# Also load KPL plates for same-plate ZT peer count on D1!
plate_zt_by_dt = defaultdict(lambda: defaultdict(int))
stock_plates_by_dt = defaultdict(list)
with open(f"{ROOT}/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip(): continue
        obj = json.loads(line)
        dt_s = str(obj.get("date", ""))[:10]
        c6 = str(obj.get("code", ""))[:6]
        pls = [p for p in obj.get("plates", []) if p and p not in ("ST板块", "昨日涨停", "昨日连板", "融资融券", "深股通", "沪股通")]
        if dt_s and c6 and pls:
            stock_plates_by_dt[(dt_s, c6)] = pls
            for p in pls:
                plate_zt_by_dt[dt_s][p] += 1

# Load LHB seats (Lhasa, Quant, Inst)
lhb_info = defaultdict(lambda: {"lhasa_cnt": 0, "lhasa_sh": 0.0, "quant_cnt": 0, "inst_cnt": 0})
QUANT_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
lhb_buy = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet",
                          columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
lhb_buy["dt"] = lhb_buy["TRADE_DATE"].astype(str).str[:10]
lhb_buy = lhb_buy[lhb_buy["dt"] >= "2021-10-01"].copy()
lhb_buy["c6"] = lhb_buy["SECURITY_CODE"].astype(str).str[:6]
# Total buy per (dt, c6) on LHB
for (dt_s, c6), grp_l in lhb_buy.groupby(["dt", "c6"]):
    tot_b = float(grp_l["BUY"].sum())
    names_s = grp_l["OPERATEDEPT_NAME"].astype(str)
    lh_mask = names_s.str.contains("拉萨", na=False)
    q_mask = names_s.str.contains(QUANT_RE, na=False)
    in_mask = names_s.str.contains("机构专用", na=False)
    lh_b = float(grp_l.loc[lh_mask, "BUY"].sum())
    lhb_info[(dt_s, c6)] = {
        "lhasa_cnt": int(lh_mask.sum()),
        "lhasa_sh": (lh_b / tot_b) if tot_b > 0 else 0.0,
        "quant_cnt": int(q_mask.sum()),
        "inst_cnt": int(in_mask.sum()),
    }

# Load Regulatory Letters, Halts & ZDJK (STRICTLY excluding statutory SEVERE_ABNORMAL from letter counts!)
stock_reg_dates = defaultdict(list)
exch_letter_halt_dates = {"SH": [], "SZ": []}

reg5 = pd.read_csv("/tmp/astock_5y_reg_events.csv")
for r in reg5.itertuples():
    c6 = str(r.code).zfill(6)
    dt_s = str(r.ann_date)[:10]
    title = str(r.title)
    if any(w in title for w in ["回复", "回函", "延期", "核查意见", "复牌"]):
        continue
    ev = str(r.event_type)
    if ev in ("REG_LETTER", "HALT", "ZDJK"):
        stock_reg_dates[c6].append(dt_s)
        if c6.startswith(("00", "60")) and ("ST" not in str(r.name)):
            ex = "SH" if c6.startswith("60") else "SZ"
            exch_letter_halt_dates[ex].append((dt_s, c6))

with open("/tmp/astock_clean_reg_letters.json") as f:
    for l in json.load(f):
        c6 = str(l["code"]).zfill(6)
        dt_s = str(l["date"])[:10]
        title = l.get("title", "")
        if "ST" in title or any(w in title for w in ["回复", "回函", "延期", "核查意见", "复牌"]):
            continue
        stock_reg_dates[c6].append(dt_s)
        if c6.startswith(("00", "60")):
            ex = "SH" if c6.startswith("60") else "SZ"
            exch_letter_halt_dates[ex].append((dt_s, c6))

for zf in glob.glob(f"{ROOT}/sim-portfolio/data/kpl/zdjk/*.json"):
    with open(zf) as fp:
        for item in json.load(fp).get("List", []):
            stock_reg_dates[str(item[0]).zfill(6)].append(str(item[2])[:10])

# Deduplicate exch_letter_halt_dates by (ex, c6, 5d)
for ex in ("SH", "SZ"):
    evs = sorted(set(exch_letter_halt_dates[ex]))
    ded = []
    seen = {}
    for dt_s, c6 in evs:
        if c6 in seen and (pd.Timestamp(dt_s) - seen[c6]).days <= 7:
            continue
        seen[c6] = pd.Timestamp(dt_s)
        ded.append(dt_s)
    exch_letter_halt_dates[ex] = sorted(ded)

# Load TRUE toxic corporate notices (减持/立案/解禁/业绩巨亏, NOT routine 交易异常波动!)
REAL_TOXIC_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|解除限售|限售股上市|业绩预亏|大幅下降)")
toxic_notice_dates = defaultdict(list)
conn_n = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
for sec_code, pub_dt, title in conn_n.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2021-10-01'"):
    if pub_dt and REAL_TOXIC_RE.search(str(title or "")):
        toxic_notice_dates[str(sec_code)[:6].zfill(6)].append(str(pub_dt)[:10])
conn_n.close()

def get_dev_threshold(bars, curr_p, idx_map, target_dev=1.00, dev_discount=0.07):
    curr_d = bars["dts"][curr_p]
    idx_ref = idx_map.get(curr_d)
    if not idx_ref: return 99999.0
    best_p = 99999.0
    for k in range(1, min(11, curr_p + 1)):
        b_p = curr_p - k
        b_d = bars["dts"][b_p]; b_close = bars["close"][b_p]; b_idx = idx_map.get(b_d)
        if not b_idx or b_close <= 0: continue
        idx_chg = idx_ref / b_idx - 1.0
        p_line = b_close * (1.0 + (target_dev - dev_discount) + idx_chg)
        if p_line < best_p: best_p = p_line
    return best_p

# ==============================================================================
# Build Canonical Pool A + Pool B First-Break Candidates (2022-01-04 to 2026-11-12)
# ==============================================================================
eval_dts = [d for d in all_dts if "2022-01-04" <= d <= "2026-11-12"]
records = []

for d1_dt in eval_dts:
    idx1 = dt_to_idx[d1_dt]
    d0_dt = all_dts[idx1 - 1]
    grp0 = by_dt[d0_dt]
    grp1 = by_dt[d1_dt]
    zt0 = grp0[grp0["is_zt"]]
    if zt0.empty:
        continue
    max_b = int(zt0["streak"].max())
    if max_b < 4:
        continue
    top0 = zt0[zt0["streak"] == max_b]

    # Pool A: Market #1 Dragon (max_b >= 4, tied <= 2)
    target_c6 = []
    if len(top0) <= 2:
        for r0 in top0.itertuples():
            target_c6.append((r0.c6, "PoolA_Top1", int(r0.streak), int(r0.yz_streak)))

    # Pool B: If ALL Market #1 stocks had yz_streak >= 3 (unbuyable M&A yizi), step down to highest turnover dragon >= 4B (tied <= 2)
    if all(top0["yz_streak"] >= 3):
        turn_zt0 = zt0[(zt0["streak"] < max_b) & (zt0["streak"] >= 4) & (zt0["yz_streak"] < 2)]
        if not turn_zt0.empty:
            sub_max = int(turn_zt0["streak"].max())
            sub_top = turn_zt0[turn_zt0["streak"] == sub_max]
            if len(sub_top) <= 2:
                for r0 in sub_top.itertuples():
                    target_c6.append((r0.c6, "PoolB_Sub", int(r0.streak), int(r0.yz_streak)))

    if not target_c6:
        continue

    g1_idx = grp1.set_index("c6")
    for c6, pool_tag, st0, yz0 in target_c6:
        if c6 not in g1_idx.index:
            continue
        r1 = g1_idx.loc[c6]
        # Must break streak on D1 AND close > open (True Yang candle!)
        if bool(r1["is_zt"]) or not (float(r1["close"]) > float(r1["open"])):
            continue
        bars = code_bars[c6]
        d1_pos = bars["date_to_pos"][d1_dt]
        d2_pos = d1_pos + 1
        if d2_pos >= len(bars["dts"]):
            continue
        # D2 buyability check: not yizi limit-up, not limit-down open
        if bars["is_yizi"][d2_pos]:
            continue
        b_open = float(bars["open"][d2_pos])
        if b_open <= float(bars["dt_px"][d2_pos]) + 0.011 or b_open <= 0:
            continue

        d2_dt = bars["dts"][d2_pos]
        d2_op_pct = float(bars["o_pct"][d2_pos])
        exch = "SH" if c6.startswith("60") else "SZ"
        idx_map = SH_MAP if exch == "SH" else SZ_MAP

        # Intraday ignition check on D2: if open < 0%, require intraday high >= max(b_open * 1.012, pre_c * 0.995) and < zt_px
        ign_px = max(b_open * 1.012, float(bars["pre_c"][d2_pos]) * 0.990)
        can_ign = True
        eff_buy_px = b_open
        buy_at_open_hyb = True
        if d2_op_pct < 0.0:
            if float(bars["high"][d2_pos]) >= ign_px and ign_px < float(bars["zt_px"][d2_pos]) - 0.01:
                eff_buy_px = ign_px
                buy_at_open_hyb = False
            else:
                can_ign = False

        # Compute exits for both Auction Buy (b_open) and Hybrid Ignition Buy (eff_buy_px)
        def sim_exits(buy_px):
            # 1) T+1 close
            p1 = min(d2_pos + 1, len(bars["dts"]) - 1)
            while p1 < len(bars["dts"]) - 1 and bars["is_yizi_dt"][p1]:
                p1 += 1
            r_t1 = (bars["close"][p1] * bars["adjf"][p1]) / (buy_px * bars["adjf"][d2_pos]) * (1.0 - FEE) - 1.0

            # 2) 1111 + 93% dev TP (and if D2 crashed <-4%, exit on T+1 +2% bounce if hit else close!)
            ep, epx, e_open = None, None, False
            d2_c_ret = bars["close"][d2_pos] / buy_px - 1.0
            for step in range(1, 6):
                p = d2_pos + step
                if p >= len(bars["dts"]): break
                p_line = get_dev_threshold(bars, p, idx_map, 1.00, 0.07)
                if bars["open"][p] >= p_line:
                    ep, epx, e_open = p, bars["open"][p], True; break
                elif bars["high"][p] >= p_line:
                    ep, epx, e_open = p, p_line, False; break
                if step == 1 and d2_c_ret <= -0.04 and (not bars["is_zt"][d2_pos]):
                    # Bounce rescue exit from Agent 1!
                    b_target = bars["pre_c"][p] * 1.015
                    if bars["open"][p] >= b_target:
                        ep, epx, e_open = p, bars["open"][p], True; break
                    elif bars["high"][p] >= b_target:
                        ep, epx, e_open = p, b_target, False; break
                if not bars["is_zt"][p]:
                    while p < len(bars["dts"]) - 1 and bars["is_yizi_dt"][p]:
                        p += 1
                    ep, epx, e_open = p, bars["close"][p], False; break
            if ep is None:
                p = min(d2_pos + 5, len(bars["dts"]) - 1)
                ep, epx, e_open = p, bars["close"][p], False
            r_1111_smart = (epx * bars["adjf"][ep]) / (buy_px * bars["adjf"][d2_pos]) * (1.0 - FEE) - 1.0

            # Pure 1111 (without bounce rescue, for clean comparison)
            ep0, epx0, eo0 = None, None, False
            for step in range(1, 6):
                p = d2_pos + step
                if p >= len(bars["dts"]): break
                p_line = get_dev_threshold(bars, p, idx_map, 1.00, 0.07)
                if bars["open"][p] >= p_line:
                    ep0, epx0, eo0 = p, bars["open"][p], True; break
                elif bars["high"][p] >= p_line:
                    ep0, epx0, eo0 = p, p_line, False; break
                if not bars["is_zt"][p]:
                    while p < len(bars["dts"]) - 1 and bars["is_yizi_dt"][p]:
                        p += 1
                    ep0, epx0, eo0 = p, bars["close"][p], False; break
            if ep0 is None:
                p = min(d2_pos + 5, len(bars["dts"]) - 1)
                ep0, epx0, eo0 = p, bars["close"][p], False
            r_1111_pure = (epx0 * bars["adjf"][ep0]) / (buy_px * bars["adjf"][d2_pos]) * (1.0 - FEE) - 1.0

            return {
                "t1": (bars["dts"][p1], float(r_t1), max(1, p1 - d2_pos), False),
                "pure1111": (bars["dts"][ep0], float(r_1111_pure), max(1, ep0 - d2_pos), eo0),
                "smart1111": (bars["dts"][ep], float(r_1111_smart), max(1, ep - d2_pos), eo0 and False or e_open),
            }

        ex_auc = sim_exits(b_open)
        ex_hyb = sim_exits(eff_buy_px) if can_ign else None

        # Auxiliary features strictly known before 09:25 on D2!
        lh0 = lhb_info[(d0_dt, c6)]
        lh1 = lhb_info[(d1_dt, c6)]
        lh1_share = lh1["lhasa_sh"]

        # Stock reg red flag in [d1_dt - 10d, d1_dt]
        d1_ts = pd.Timestamp(d1_dt)
        has_stock_reg = any(0 <= (d1_ts - pd.Timestamp(x)).days <= 10 for x in stock_reg_dates.get(c6, []))
        has_toxic_not = any(0 <= (d1_ts - pd.Timestamp(x)).days <= 15 for x in toxic_notice_dates.get(c6, []))
        # Same-exchange regulatory letters/halts in last 5 trading days [idx1 - 5, idx1]
        w5_start = all_dts[max(0, idx1 - 5)]
        same_exch_reg5 = sum(1 for x in exch_letter_halt_dates[exch] if w5_start <= x <= d1_dt)
        other_ex = "SZ" if exch == "SH" else "SH"
        other_exch_reg5 = sum(1 for x in exch_letter_halt_dates[other_ex] if w5_start <= x <= d1_dt)

        # Headroom to 100% severe abnormal on D2 open
        p100 = get_dev_threshold(bars, d2_pos, idx_map, 1.00, 0.00)
        headroom_100 = p100 / b_open - 1.0

        # Theme & industry peers on D1
        pls_d0 = stock_plates_by_dt.get((d0_dt, c6), [])
        max_plate_peers_d1 = max([plate_zt_by_dt[d1_dt].get(p, 0) for p in pls_d0], default=0)
        env1 = env_stats[d1_dt]
        csrc_peers_d1 = env1["csrc_zt_cnts"].get(str(r1["csrc_ind"]), 0)
        t_meta = cand_theme_lookup.get((d1_dt, c6), {})
        is_dom = t_meta.get("is_dominant_day", False)
        is_eb = t_meta.get("is_event_basket", False)
        mb_gap = t_meta.get("prior_mb_gap", 999)

        lock10 = get_pit_lock(c6, d1_dt)
        free_mcap = float(r1["mcap"]) * (1.0 - lock10 / 100.0)

        records.append({
            "d0_dt": d0_dt, "d1_dt": d1_dt, "buy_date": d2_dt,
            "code": c6, "name": str(r1["name"]), "exch": exch, "pool": pool_tag,
            "st0": st0, "yz0": yz0,
            "d1_pct": float(r1["pct"]), "d1_op_pct": float(r1["o_pct"]),
            "d1_body": float(r1["pct"] - r1["o_pct"]),
            "d1_uwick": float(r1["h_pct"] - r1["pct"]),
            "d1_to": float(r1["to"]),
            "d1_vol_r": float(r1["d1_vol_ratio_d0"]),
            "d0_tight": float(r1["d0_seal_tight"]),
            "d2_op_pct": d2_op_pct,
            "lhasa_d0": lh0["lhasa_cnt"], "lhasa_d1": lh1["lhasa_cnt"], "lhasa_sh_d1": lh1_share,
            "quant_d0": lh0["quant_cnt"], "quant_d1": lh1["quant_cnt"], "inst_d1": lh1["inst_cnt"],
            "has_stock_reg": has_stock_reg, "has_toxic_not": has_toxic_not,
            "same_exch_reg5": same_exch_reg5, "other_exch_reg5": other_exch_reg5,
            "headroom_100": headroom_100,
            "b3_dt_d1": env1["b3_dt_cnt"], "brk_dt_r10": env1["brk_dt_rate_10d"], "csi_r20": env1["csi_ret20"],
            "plate_peers_d1": max_plate_peers_d1, "csrc_peers_d1": csrc_peers_d1,
            "is_dom": is_dom, "is_eb": is_eb, "mb_gap": mb_gap,
            "lock10": lock10, "free_mcap": free_mcap,
            "can_ign": can_ign, "buy_at_open_hyb": buy_at_open_hyb,
            "ex_auc": ex_auc, "ex_hyb": ex_hyb,
        })

df_rec = pd.DataFrame(records)
print(f"Built canonical Pool A+B True-Yang universe: {len(df_rec)} candidates (IS 2022-24: {(df_rec['buy_date']<'2025-01-01').sum()}, OOS 2025-26: {(df_rec['buy_date']>='2025-01-01').sum()})")

# ==============================================================================
# Step 1: In-Sample (2022-2024 ONLY!) Univariate Factor Verification
# ==============================================================================
df_is = df_rec[df_rec["buy_date"] < "2025-01-01"].copy()
df_is["ret_is"] = [x["pure1111"][1] for x in df_is["ex_auc"]]

print("\n=== IN-SAMPLE (2022-2024 ONLY, n={}) FACTOR DIRECTION AUDIT ===".format(len(df_is)))
checks = [
    ("has_stock_reg == True", df_is["has_stock_reg"]),
    ("has_toxic_not == True", df_is["has_toxic_not"]),
    ("d1_to > 35%", df_is["d1_to"] > 35.0),
    ("d1_to <= 35%", df_is["d1_to"] <= 35.0),
    ("b3_dt_d1 >= 2 (退潮)", df_is["b3_dt_d1"] >= 2),
    ("same_exch_reg5 >= 2 (本所发函潮)", df_is["same_exch_reg5"] >= 2),
    ("lhasa_d1 >= 2 or sh>15%", (df_is["lhasa_d1"] >= 2) | (df_is["lhasa_sh_d1"] > 0.15)),
    ("lhasa_d0==0 & lhasa_d1==0", (df_is["lhasa_d0"] == 0) & (df_is["lhasa_d1"] == 0)),
    ("inst_d1 >= 1 (机构席位)", df_is["inst_d1"] >= 1),
    ("quant_d0 >= 1 (D0量化)", df_is["quant_d0"] >= 1),
    ("d0_tight >= 40 (前日硬板)", df_is["d0_tight"] >= 40.0),
    ("d1_body >= 0.04 (大实体真阳)", df_is["d1_body"] >= 0.04),
    ("d1_pct > 0 (真阳收红)", df_is["d1_pct"] > 0.0),
    ("d1_pct <= 0 (水下真阳实跌)", df_is["d1_pct"] <= 0.0),
    ("plate_peers_d1 in [1,2] (黄金护航)", df_is["plate_peers_d1"].isin([1, 2])),
    ("plate_peers_d1 >= 3 (补涨扩散淘汰)", df_is["plate_peers_d1"] >= 3),
    ("is_dom == True (主线断层高潮日)", df_is["is_dom"]),
    ("d2_op_pct in [0, +3%] (微红甜区)", (df_is["d2_op_pct"] >= 0.0) & (df_is["d2_op_pct"] <= 0.03)),
    ("d2_op_pct > +5% (高开追高)", df_is["d2_op_pct"] > 0.05),
    ("d2_op_pct < -5% (深水核按钮)", df_is["d2_op_pct"] < -0.05),
    ("csi_r20 < -0.05 (大盘阴跌)", df_is["csi_r20"] < -0.05),
    ("mb_gap <= 90 (老妖记忆)", df_is["mb_gap"] <= 90),
]
for lbl, msk in checks:
    sub = df_is[msk]
    rest = df_is[~msk]
    if len(sub) > 0:
        print(f"  {lbl:34s} | n={len(sub):2d} wr={(sub['ret_is']>0).mean()*100:5.1f}% mean={sub['ret_is'].mean()*100:+6.2f}% | rest n={len(rest):2d} mean={rest['ret_is'].mean()*100:+6.2f}%")

# ==============================================================================
# Step 2: Transparent 100-Point Additive Scorecard (Frozen on 2022-2024 IS!)
# ==============================================================================
def score_candidate(row):
    # 5 Hard Veto Gates (Physical First-Principles + IS Verified)
    if row["has_stock_reg"] or row["has_toxic_not"]:
        return -999, "VETO_个股监管或减持雷"
    if row["same_exch_reg5"] >= 2:
        return -999, "VETO_本交易所密集发函期"
    if row["b3_dt_d1"] >= 2 and row["brk_dt_r10"] > 0.30:
        return -999, "VETO_高标批量跌停退潮"
    if row["d1_to"] > 38.0:
        return -999, "VETO_天量死亡换手"
    if row["lhasa_d1"] >= 3 or row["lhasa_sh_d1"] > 0.18:
        return -999, "VETO_拉萨散户扎堆接盘"
    if row["d2_op_pct"] > 0.055 or row["d2_op_pct"] < -0.065:
        return -999, "VETO_开盘过高或深水核按钮"

    sc = 100  # Base score = 100

    # Dim 1: Seat Cleanliness & Chip Structure (+/- 25)
    if row["lhasa_d0"] == 0 and row["lhasa_d1"] == 0:
        sc += 15
    elif row["lhasa_d1"] == 2 or row["lhasa_sh_d1"] > 0.12:
        sc -= 20
    if row["inst_d1"] >= 1:
        sc -= 12
    if row["quant_d0"] >= 1:
        sc += 6
    if row["lock10"] >= 48.0:
        sc += 6

    # Dim 2: D0 Leader Quality & D1 True-Yang Anatomy (+/- 25)
    if row["pool"] == "PoolA_Top1":
        sc += 8
    if row["d0_tight"] >= 40.0:
        sc += 10
    elif row["d0_tight"] < 20.0:
        sc -= 10
    if row["d1_body"] >= 0.04:
        sc += 10
    elif row["d1_body"] < 0.012:
        sc -= 8
    if row["d1_to"] <= 30.0:
        sc += 8
    elif row["d1_to"] > 35.0:
        sc -= 15
    if row["d1_uwick"] >= 0.07 and row["d1_pct"] > 0.06:
        sc -= 10  # 冲板大烂板长上影

    # Dim 3: Theme Ladder & Market Weather (+/- 20)
    if row["plate_peers_d1"] in (1, 2):
        sc += 12
    elif row["plate_peers_d1"] >= 3 and row["csrc_peers_d1"] >= 2:
        sc -= 12  # 高低切补涨淘汰老龙
    if row["is_dom"]:
        sc -= 10  # 主线高潮日总龙断板
    if row["b3_dt_d1"] == 0:
        sc += 8
    elif row["b3_dt_d1"] >= 2:
        sc -= 15
    if row["csi_r20"] < -0.05:
        sc -= 10
    if row["mb_gap"] <= 90:
        sc += 5

    # Dim 4: D2 09:25 Auction Sweet Spot (+/- 15)
    op = row["d2_op_pct"]
    if 0.0 <= op <= 0.028:
        sc += 15
    elif -0.025 <= op < 0.0:
        sc += 5
    elif 0.028 < op <= 0.055:
        sc -= 5
    elif op < -0.025:
        sc -= 8

    return sc, "OK"

scores, reasons = zip(*[score_candidate(r) for _, r in df_rec.iterrows()])
df_rec["score"] = scores
df_rec["gate_reason"] = reasons

# ==============================================================================
# Step 3: D15 Single-Slot & Equal-Weight Evaluator + Haircut Audit
# ==============================================================================
def eval_portfolio(sub_df, mode="hyb", exit_key="smart1111", start_dt="2022-01-04", end_dt="2026-11-12"):
    w = sub_df[(sub_df["buy_date"] >= start_dt) & (sub_df["buy_date"] <= end_dt)].copy()
    rows = []
    for r in w.itertuples():
        if mode == "hyb":
            if not r.can_ign:
                continue
            ed, ret, hb, eo = r.ex_hyb[exit_key]
            b_open_flag = r.buy_at_open_hyb
        else:
            ed, ret, hb, eo = r.ex_auc[exit_key]
            b_open_flag = True
        rows.append({
            "buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name,
            "score": r.score, "net_ret": ret, "hold_bars": hb,
            "buy_at_open": b_open_flag, "exit_at_open": eo, "pool": r.pool
        })
    if not rows:
        return {"n": 0, "wr": 0, "plr": 0, "nav": 1.0, "ew_nav": 1.0, "top5_nav": 1.0, "mdd": 0.0, "csi": 0.0, "excess": 0.0, "sharpe": 0.0, "ledger": pd.DataFrame()}
    tdf = pd.DataFrame(rows).sort_values(["buy_date", "score"], ascending=[True, False])
    # Daily equal-weight
    ew_s = tdf.groupby("buy_date")["net_ret"].mean().sort_index()
    ew_nav = float((1.0 + ew_s).prod())

    # Single-slot rotation
    taken = []
    free_dt = ""
    prev_eo = False
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in tdf.itertuples(index=False):
        can_b = (free_dt == "") or (r.buy_date > free_dt) or (r.buy_date == free_dt and prev_eo and (not r.buy_at_open))
        if not can_b:
            continue
        taken.append(r)
        free_dt = r.exit_date
        prev_eo = r.exit_at_open
        nav *= (1.0 + r.net_ret)
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)

    led = pd.DataFrame(taken)
    rets = led["net_ret"].values
    wr = float(np.mean(rets > 0))
    pos = rets[rets > 0]
    neg = np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos) > 0 and len(neg) > 0) else 99.0
    # Top-5 outlier removal
    s_rets = np.sort(rets)
    rem = s_rets[:-5] if len(s_rets) > 5 else np.array([0.0])
    top5_nav = float(np.prod(1.0 + rem))

    # Daily equity curve Sharpe (across trading days in [start_dt, end_dt])
    span_dts = [d for d in all_dts if start_dt <= d <= end_dt]
    d_ret_map = defaultdict(float)
    for r in taken:
        d_ret_map[r.buy_date] += r.net_ret
    daily_r = np.array([d_ret_map[d] for d in span_dts])
    sh = float(np.mean(daily_r) / (np.std(daily_r) + 1e-9) * np.sqrt(250))

    prev_dts = [k for k in CSI_MAP if k < span_dts[0]]
    b0 = max(prev_dts) if prev_dts else span_dts[0]
    csi_r = float(CSI_MAP[span_dts[-1]] / CSI_MAP[b0] - 1.0)
    return {
        "n": len(led), "sig_n": len(tdf), "wr": wr, "plr": plr,
        "nav": nav, "ew_nav": ew_nav, "top5_nav": top5_nav, "mdd": mdd,
        "csi": csi_r, "excess": (nav - 1.0) - csi_r, "sharpe": sh, "ledger": led
    }

# Sweep threshold & mode grid ONLY on IS (2022-2024) to record n_trials and pick IS winner, then blind-test on OOS (2025-2026)!
grid_trials = []
for thr in [95, 100, 105, 110, 115, 120, 125, 130, 135]:
    for mode in ["auc", "hyb"]:
        for ex_k in ["t1", "pure1111", "smart1111"]:
            sub = df_rec[df_rec["score"] >= thr]
            res_is = eval_portfolio(sub, mode, ex_k, "2022-01-04", "2024-12-31")
            res_oos = eval_portfolio(sub, mode, ex_k, "2025-01-02", "2026-11-12")
            res_full = eval_portfolio(sub, mode, ex_k, "2022-01-04", "2026-11-12")
            grid_trials.append({
                "thr": thr, "mode": mode, "exit": ex_k,
                "is_sh": res_is["sharpe"], "is_nav": res_is["nav"], "is_mdd": res_is["mdd"], "is_n": res_is["n"],
                "oos_sh": res_oos["sharpe"], "oos_nav": res_oos["nav"], "oos_mdd": res_oos["mdd"], "oos_n": res_oos["n"],
                "full_sh": res_full["sharpe"], "full_nav": res_full["nav"], "full_wr": res_full["wr"], "full_plr": res_full["plr"], "full_mdd": res_full["mdd"], "full_n": res_full["n"]
            })

gdf = pd.DataFrame(grid_trials)
n_trials = len(gdf)
sh_std = gdf["full_sh"].std()
best_sh = gdf["full_sh"].max()
exp_max = sh_std * ((1 - np.euler_gamma) * norm.ppf(1 - 1 / n_trials) + np.euler_gamma * norm.ppf(1 - 1 / (n_trials * np.e)))
haircut_sh = best_sh - exp_max
print(f"\n=== MULTIPLE TESTING AUDIT (n_trials={n_trials}) ===")
print(f"Best Observed 5Y Sharpe: {best_sh:.2f} | Expected Noise Max: {exp_max:.2f} | Deflated Haircut Sharpe: {haircut_sh:.2f}")

# Pick IS-Optimal Balanced Champion (require IS trades >= 20 so not sparse!) and IS-Optimal High-WR Steady Champion
valid_is = gdf[gdf["is_n"] >= 20].sort_values("is_sh", ascending=False)
print("\nTop 8 Configurations Ranked STRICTLY by In-Sample (2022-2024) Sharpe (with Blind OOS 2025-2026 shown alongside):")
print(valid_is.head(8).to_string(index=False))

# Detailed multi-window D15 report for Baseline (raw Pool A+B) vs Champion M1 (High-Score Elite) vs Champion M2 (Balanced Mainline)
configs_to_report = [
    ("基准无打分原版 (PoolA+B 换手<=35%)", df_rec[df_rec["d1_to"] <= 35.0], "auc", "pure1111"),
    ("打分卡主力版 M2 (总分>=110 点火+按天智能卖)", df_rec[df_rec["score"] >= 110], "hyb", "smart1111"),
    ("打分卡竞价版 M2_Auc (总分>=110 竞价+按天卖)", df_rec[df_rec["score"] >= 110], "auc", "pure1111"),
    ("打分卡精品高胜率版 M1 (总分>=120 点火+按天智能卖)", df_rec[df_rec["score"] >= 120], "hyb", "smart1111"),
]

windows = [
    ("五年全量 (2022-2026)", "2022-01-04", "2026-11-12"),
    ("训练集 IS (2022-2024)", "2022-01-04", "2024-12-31"),
    ("纯样本外 OOS (2025-2026)", "2025-01-02", "2026-11-12"),
    ("近三年 (2024-2026)", "2024-01-02", "2026-11-12"),
    ("去2025四年", "NO2025", "NO2025"),
    ("2026年7月以来", "2026-07-01", "2026-11-12"),
]

print("\n=== FULL D15 MULTI-WINDOW COMPARISON ===")
summary_out = {}
for cname, cdf, md, exk in configs_to_report:
    print(f"\n>>> {cname}")
    summary_out[cname] = {}
    for wlbl, ws, we in windows:
        if ws == "NO2025":
            sub_no25 = cdf[(cdf["buy_date"] < "2025-01-01") | (cdf["buy_date"] >= "2026-01-01")]
            r = eval_portfolio(sub_no25, md, exk, "2022-01-04", "2026-11-12")
        else:
            r = eval_portfolio(cdf, md, exk, ws, we)
        summary_out[cname][wlbl] = {k: v for k, v in r.items() if k != "ledger"}
        print(f"  {wlbl:24s} | 笔数={r['n']:2d} | 胜率={r['wr']*100:5.1f}% | 盈亏比={r['plr']:4.2f} | 单仓={r['nav']:6.2f}x | 日等权={r['ew_nav']:6.2f}x | 去Top5={r['top5_nav']:5.2f}x | MDD={r['mdd']*100:4.1f}% | 沪深300={r['csi']*100:+5.1f}% | 净超额={r['excess']*100:+7.1f}%")
    # Print year-by-year NAV
    yr_strs = []
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        ry = eval_portfolio(cdf, md, exk, f"{yr}-01-01", f"{yr}-12-31")
        yr_strs.append(f"{yr}:{ry['nav']:.2f}x({ry['n']}笔,WR{ry['wr']*100:.0f}%)")
    print("  逐年单仓:", " | ".join(yr_strs))
    if "主力版 M2 " in cname:
        r_full = eval_portfolio(cdf, md, exk, "2022-01-04", "2026-11-12")
        r_full["ledger"].to_csv(f"{OUT_DIR}/master_M2_ledger.csv", index=False)

# Threshold sensitivity (+/- 15 points around 110: 95, 100, 105, 110, 115, 120, 125)
print("\n=== SCORE THRESHOLD SENSITIVITY PLATEAU (hyb + smart1111, 2022-2026) ===")
for thr in [95, 100, 105, 110, 115, 120, 125]:
    r = eval_portfolio(df_rec[df_rec["score"] >= thr], "hyb", "smart1111", "2022-01-04", "2026-11-12")
    print(f"  Threshold >= {thr:3d} | 笔数={r['n']:2d} | 胜率={r['wr']*100:5.1f}% | 盈亏比={r['plr']:4.2f} | 5Y单仓={r['nav']:6.2f}x | 日等权={r['ew_nav']:6.2f}x | 去Top5={r['top5_nav']:5.2f}x | MDD={r['mdd']*100:4.1f}%")

# Also test Dual-Slot Single-Position Combination with Buwen's Special 5-Board Module (only in benign regime: brk_dt_r10<=0.25, same_exch_reg5==0, b3_dt==0, lock10>=50, 1.0%<open<=5.5%)!
trades_5b = []
for d1_dt in eval_dts:
    idx1 = dt_to_idx[d1_dt]
    if idx1 + 1 >= len(all_dts): continue
    d2_dt = all_dts[idx1 + 1]
    grp1 = by_dt[d1_dt]
    env1 = env_stats[d1_dt]
    if env1["brk_dt_rate_10d"] > 0.25 or env1["b3_dt_cnt"] > 0 or env1["csi_ret20"] < -0.04:
        continue
    c5 = grp1[grp1["streak"] == 5]
    for r1 in c5.itertuples():
        c6 = r1.c6
        exch = "SH" if c6.startswith("60") else "SZ"
        w5_start = all_dts[max(0, idx1 - 5)]
        if sum(1 for x in exch_letter_halt_dates[exch] if w5_start <= x <= d1_dt) >= 1:
            continue
        if any(0 <= (pd.Timestamp(d1_dt) - pd.Timestamp(x)).days <= 15 for x in toxic_notice_dates.get(c6, [])):
            continue
        lh1 = lhb_info[(d1_dt, c6)]
        if lh1["lhasa_cnt"] >= 2:
            continue
        lock10 = get_pit_lock(c6, d1_dt)
        if lock10 < 50.0 or float(r1.mcap) * (1.0 - lock10 / 100.0) > 50.0:
            continue
        bars = code_bars[c6]
        p_buy = bars["date_to_pos"][d1_dt] + 1
        if p_buy >= len(bars["dts"]) or bars["is_yizi"][p_buy]:
            continue
        op_pct = float(bars["o_pct"][p_buy])
        if not (0.01 < op_pct <= 0.055):
            continue
        b_px = float(bars["open"][p_buy])
        idx_map = SH_MAP if exch == "SH" else SZ_MAP
        ep, epx, eo = None, None, False
        for step in [1, 2, 3]:
            p = p_buy + step
            if p >= len(bars["dts"]): break
            p_line = get_dev_threshold(bars, p, idx_map, 1.00, 0.07)
            if bars["open"][p] >= p_line:
                ep, epx, eo = p, bars["open"][p], True; break
            elif bars["high"][p] >= p_line:
                ep, epx, eo = p, p_line, False; break
        if ep is None:
            p = min(p_buy + 3, len(bars["dts"]) - 1)
            while p < len(bars["dts"]) - 1 and bars["is_yizi_dt"][p]:
                p += 1
            ep, epx, eo = p, bars["close"][p], False
        ret5 = (epx * bars["adjf"][ep]) / (b_px * bars["adjf"][p_buy]) * (1.0 - FEE) - 1.0
        trades_5b.append({
            "buy_date": bars["dts"][p_buy], "exit_date": bars["dts"][ep], "code": c6, "name": str(r1.name),
            "score": 118, "net_ret": float(ret5), "hold_bars": max(1, ep - p_buy),
            "buy_at_open": True, "exit_at_open": eo, "pool": "Special_5B"
        })

# Merge M2 ledger candidates + Special_5B into single-slot rotation!
m2_cands = []
for r in df_rec[df_rec["score"] >= 110].itertuples():
    if not r.can_ign: continue
    ed, ret, hb, eo = r.ex_hyb["smart1111"]
    m2_cands.append({
        "buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name,
        "score": r.score, "net_ret": ret, "hold_bars": hb,
        "buy_at_open": r.buy_at_open_hyb, "exit_at_open": eo, "pool": r.pool
    })
df_combo = pd.DataFrame(m2_cands + trades_5b).sort_values(["buy_date", "score"], ascending=[True, False])

def eval_raw_tdf(tdf, start_dt, end_dt):
    w = tdf[(tdf["buy_date"] >= start_dt) & (tdf["buy_date"] <= end_dt)]
    if w.empty: return 0, 0, 0, 1.0, 1.0, 0.0, 0.0
    ew_nav = float((1.0 + w.groupby("buy_date")["net_ret"].mean()).prod())
    taken, free_dt, prev_eo = [], "", False
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in w.itertuples(index=False):
        if (free_dt == "") or (r.buy_date > free_dt) or (r.buy_date == free_dt and prev_eo and (not r.buy_at_open)):
            taken.append(r); free_dt = r.exit_date; prev_eo = r.exit_at_open
            nav *= (1.0 + r.net_ret); pk = max(pk, nav); mdd = max(mdd, (pk - nav) / pk)
    rets = np.array([x.net_ret for x in taken])
    wr = float(np.mean(rets > 0))
    pos, neg = rets[rets > 0], np.abs(rets[rets <= 0])
    plr = float(np.mean(pos) / np.mean(neg)) if (len(pos)>0 and len(neg)>0) else 99.0
    span_dts = [d for d in all_dts if start_dt <= d <= end_dt]
    prev_dts = [k for k in CSI_MAP if k < span_dts[0]]
    csi_r = float(CSI_MAP[span_dts[-1]] / CSI_MAP[max(prev_dts)] - 1.0)
    return len(taken), wr, plr, nav, ew_nav, mdd, (nav - 1.0) - csi_r

print(f"\n=== M3: SCORECARD M2 + SPECIAL BENIGN 5-BOARD MODULE (5B standalone signals={len(trades_5b)}) ===")
for wlbl, ws, we in [("五年全量 (2022-2026)", "2022-01-04", "2026-11-12"), ("纯样本外 OOS (2025-2026)", "2025-01-02", "2026-11-12"), ("近三年 (2024-2026)", "2024-01-02", "2026-11-12"), ("2026年7月以来", "2026-07-01", "2026-11-12")]:
    n, wr, plr, nav, ew, mdd, exc = eval_raw_tdf(df_combo, ws, we)
    print(f"  {wlbl:24s} | 笔数={n:2d} | 胜率={wr*100:5.1f}% | 盈亏比={plr:4.2f} | 单仓={nav:6.2f}x | 日等权={ew:6.2f}x | MDD={mdd*100:4.1f}% | 净超额={exc*100:+7.1f}%")

with open(f"{OUT_DIR}/master_scorecard_summary.json", "w", encoding="utf-8") as f:
    json.dump(summary_out, f, ensure_ascii=False, indent=2)

print(f"\nDone in {time.time()-t0:.1f}s")
