#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""高标首阴反包百分制打分卡最终定版核验引擎（零未来函数 / PIT退市全含 / 2022-2024训练锁参 / 2025-2026盲测）"""
import os, re, json, glob, time, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import norm

t0 = time.time()
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
GFM_DIR = f"{SANDBOX}/grand_factor_matrix_20261112"
OUT_DIR = f"{SANDBOX}/high_dragon_scorecard_20261113"
FEE = 0.0020

IDX = json.load(open(f"{SANDBOX}/index_klines_5y_cache.json"))
CSI_MAP, SH_MAP, SZ_MAP = IDX["sh000300"], IDX["sh000002"], IDX["sz399107"]

cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "turn", "amount", "oshare"]
df = pd.concat([
    pd.read_parquet(f"{ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))]),
    pd.read_parquet(f"{ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))]),
], ignore_index=True)
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

g = df.groupby("c6")
df = df[g.cumcount() >= 10].copy().reset_index(drop=True)
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

s_zt, s_yz = df["is_zt"].astype(int), df["is_yizi"].astype(int)
df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
df["yz_streak"] = s_yz.groupby([df["c6"], (s_yz != g["is_yizi"].shift().fillna(False)).cumsum()]).cumsum() * s_yz
df["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
df["vol_ma5"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
df["seal_calc"] = (df["close"] == df["high"]).astype(int) * 30.0 + np.clip(df["l_pct"] * 100.0, -10.0, 10.0) * 1.5 + np.clip((df["close"] - df["open"]) / (df["pre_c"] + 1e-6) * 100.0, 0.0, 10.0) * 2.0 - np.where(df["amount"] / (df["vol_ma5"] + 1e-6) > 4.0, 15.0, 0.0)
df["d0_tight"] = g["seal_calc"].shift(1).fillna(25.0)
df["d1_vol_r"] = df["amount"] / (g["amount"].shift(1).fillna(1.0) + 1e-6)

all_dts = sorted(df["dt_str"].unique())
dt_to_idx = {d: i for i, d in enumerate(all_dts)}
for m in (CSI_MAP, SH_MAP, SZ_MAP):
    lv = None
    for d in all_dts:
        lv = m[d] if d in m else lv
        if lv is not None: m[d] = lv

code_bars = {c6: {"dts": s["dt_str"].values, "p": {d: i for i, d in enumerate(s["dt_str"].values)}, "open": s["open"].values, "high": s["high"].values, "low": s["low"].values, "close": s["close"].values, "adjf": s["adjf"].values, "pre_c": s["pre_c"].values, "zt_px": s["zt_px"].values, "dt_px": s["dt_px"].values, "is_zt": s["is_zt"].values, "is_yizi": s["is_yizi"].values, "is_yizi_dt": s["is_yizi_dt"].values, "o_pct": s["o_pct"].values} for c6, s in df.groupby("c6", sort=False)}

by_dt = {d: grp for d, grp in df.groupby("dt_str", sort=True)}
env_stats, brk_hist = {}, []
for d in all_dts:
    grp = by_dt[d]; zt_g = grp[grp["is_zt"]]
    ge4 = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
    brk_hist.append((int(ge4["is_dt"].sum()), int(len(ge4))))
    w10 = brk_hist[-10:]
    env_stats[d] = {"b3_dt": int((grp["prev_streak"] >= 3).mul(grp["is_dt"]).sum()), "brk_r10": sum(x[0] for x in w10) / max(1, sum(x[1] for x in w10)), "csi_r20": CSI_MAP[d] / CSI_MAP[all_dts[max(0, dt_to_idx[d] - 20)]] - 1.0, "csrc_zt": zt_g[zt_g["csrc_ind"] != ""].groupby("csrc_ind")["c6"].count().to_dict()}

holders = json.load(open(f"{GFM_DIR}/pit_top10_all_codes.json"))
get_lock = lambda c6, d: float(max([r for r in holders.get(c6, []) if r[0] < d], key=lambda x: x[1])[2]) if any(r[0] < d for r in holders.get(c6, [])) else 38.0

cand_pq = pd.read_parquet(f"{GFM_DIR}/cand_high_dragon.parquet")
t_lookup = {(r.buy_date, r.code): (bool(r.is_dominant_day), int(r.prior_mb_gap)) for r in cand_pq.itertuples()}

plate_zt, stock_pls = defaultdict(lambda: defaultdict(int)), defaultdict(list)
for line in open(f"{ROOT}/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"):
    if not line.strip(): continue
    o = json.loads(line); d, c = str(o.get("date", ""))[:10], str(o.get("code", ""))[:6]
    pls = [p for p in o.get("plates", []) if p and p not in ("ST板块", "昨日涨停", "昨日连板", "融资融券", "深股通", "沪股通")]
    if d and c and pls:
        stock_pls[(d, c)] = pls
        for p in pls: plate_zt[d][p] += 1

lhb = defaultdict(lambda: (0, 0.0, 0, 0))
Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
for (d, c), gl in lb[lb["dt"] >= "2021-10-01"].groupby(["dt", "c6"]):
    tb = float(gl["BUY"].sum()); ns = gl["OPERATEDEPT_NAME"].astype(str); lm = ns.str.contains("拉萨", na=False)
    lhb[(d, c)] = (int(lm.sum()), float(gl.loc[lm, "BUY"].sum()) / tb if tb > 0 else 0.0, int(ns.str.contains(Q_RE, na=False).sum()), int(ns.str.contains("机构专用", na=False).sum()))

stock_reg, ex_reg = defaultdict(list), {"SH": [], "SZ": []}
for r in pd.read_csv("/tmp/astock_5y_reg_events.csv").itertuples():
    c, d, t = str(r.code).zfill(6), str(r.ann_date)[:10], str(r.title)
    if str(r.event_type) in ("REG_LETTER", "HALT", "ZDJK") and not any(w in t for w in ["回复", "回函", "延期", "核查意见", "复牌"]):
        stock_reg[c].append(d)
        if c.startswith(("00", "60")) and "ST" not in str(r.name): ex_reg["SH" if c.startswith("60") else "SZ"].append((d, c))
for l in json.load(open("/tmp/astock_clean_reg_letters.json")):
    c, d, t = str(l["code"]).zfill(6), str(l["date"])[:10], l.get("title", "")
    if "ST" not in t and not any(w in t for w in ["回复", "回函", "延期", "核查意见", "复牌"]):
        stock_reg[c].append(d)
        if c.startswith(("00", "60")): ex_reg["SH" if c.startswith("60") else "SZ"].append((d, c))
for zf in glob.glob(f"{ROOT}/sim-portfolio/data/kpl/zdjk/*.json"):
    for it in json.load(open(zf)).get("List", []): stock_reg[str(it[0]).zfill(6)].append(str(it[2])[:10])
for ex in ("SH", "SZ"):
    ded, seen = [], {}
    for d, c in sorted(set(ex_reg[ex])):
        if c not in seen or (pd.Timestamp(d) - seen[c]).days > 7: seen[c] = pd.Timestamp(d); ded.append(d)
    ex_reg[ex] = sorted(ded)

TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险)")
tox_dates = defaultdict(list)
conn = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
for sc, pdt, ti in conn.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2021-10-01'"):
    if pdt and TOX_RE.search(str(ti or "")): tox_dates[str(sc)[:6].zfill(6)].append(str(pdt)[:10])
conn.close()

with open(f"{OUT_DIR}/part1_cache.pkl", "wb") as fp:
    import pickle
    plate_zt_d = {k: dict(v) for k, v in plate_zt.items()}
    pickle.dump((all_dts, dt_to_idx, by_dt, code_bars, env_stats, holders, t_lookup, plate_zt_d, dict(stock_pls), dict(lhb), dict(stock_reg), ex_reg, dict(tox_dates), CSI_MAP, SH_MAP, SZ_MAP), fp)
print(f"Part1 cache built in {time.time()-t0:.1f}s")
