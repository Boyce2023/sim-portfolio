#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part C: Official V19.1 Physical Clean Ledger Calibration, Archiving (S15) & Red-Team Re-Audit.
Fixes:
  1. 3to4 V4.1: defer 12 exact 15:00 locked limit-down exits (is_dt_exact) to next non-yizi_dt 09:25 open.
  2. High V5.1: rebuild from true V5.1 ruleset (v51_ledger_42: d1_to<=35%, lock>=45 or fmcap>=45 ±6)
     with S_hold_d3 (93% double-dev ONLY when buy-day sealed ZT or chained ZT) + defer 000968 15:00 limit-down exit.
  3. 2to3 V2.1: replace misplaced XF30_V22 (archived to _archive/20261123_pre_redteam_fix/) with official Opt_V21
     as ledger_v21_opt_std90.csv, fixing ex-div 002919 (2023-05-31 ZT -> 2023-06-01 15:00@38.75, +12.41%)
     and ex-div 600262 (-4.40%).
  4. 1to2 V19: defer 002361 (2025-12-30 15:00 limit-down -> 2025-12-31 09:25@12.61, +59.10%) and fix 002930 ex-div (-9.81%).
  5. Combined 5-strat V19.1: re-run strict single-slot chronology across the 5 clean pools.
Never touches any production .py script. Never imports yfinance (D12).
"""
import os, sys, json, math, shutil, pickle
import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
B2_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partB2_ledger_stress_audit"
PARTC_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
ARCH_DIR = f"{SIM}/backtests_astock/_archive/20261123_pre_redteam_fix"
os.makedirs(PARTC_DIR, exist_ok=True)
os.makedirs(ARCH_DIR, exist_ok=True)

sys.path.insert(0, B2_DIR)
import run_ledger_stress_audit as rta

OFFICIAL_PATHS = {
    "3to4": f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/ledger_3to4_xf30_std.csv",
    "high": f"{SIM}/backtests_astock/clean_rebacktest_20261116/partA_high_3to4/ledger_base_high_v51.csv",
    "2to3_misplaced": f"{SIM}/backtests_astock/exit_factors_v2_20261118/f2_2to3/ledger_xf30_t2_std90.csv",
    "2to3_official": f"{SIM}/backtests_astock/exit_factors_v2_20261118/f2_2to3/ledger_v21_opt_std90.csv",
    "2to3_opt_orig": f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/ledger_opt_t2_std90.csv",
    "1to2": f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_upg_1to2.csv",
    "comb": f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_combined_5strat_v191_slot1.csv",
}

# Step 1: S15 Archiving BEFORE overwriting
print("[1/6] Archiving pre-calibration ledgers to", ARCH_DIR)
for key, src_p in [
    ("3to4", OFFICIAL_PATHS["3to4"]),
    ("high", OFFICIAL_PATHS["high"]),
    ("2to3_opt_orig", OFFICIAL_PATHS["2to3_opt_orig"]),
    ("1to2", OFFICIAL_PATHS["1to2"]),
    ("comb", OFFICIAL_PATHS["comb"]),
]:
    dst_p = f"{ARCH_DIR}/{os.path.basename(src_p)}"
    if os.path.exists(src_p) and not os.path.exists(dst_p):
        shutil.copy2(src_p, dst_p)

misplaced_23 = OFFICIAL_PATHS["2to3_misplaced"]
arch_misplaced_23 = f"{ARCH_DIR}/ledger_xf30_t2_std90.csv"
if os.path.exists(misplaced_23):
    if not os.path.exists(arch_misplaced_23):
        shutil.copy2(misplaced_23, arch_misplaced_23)
    os.remove(misplaced_23)
    print("  Moved misplaced XF30_V22 ledger_xf30_t2_std90.csv -> archive")

# Load archived originals as Before baseline
d34_orig = pd.read_csv(f"{ARCH_DIR}/ledger_3to4_xf30_std.csv")
dhd_orig = pd.read_csv(f"{ARCH_DIR}/ledger_base_high_v51.csv")
d23_orig = pd.read_csv(f"{ARCH_DIR}/ledger_opt_t2_std90.csv")
d12_orig = pd.read_csv(f"{ARCH_DIR}/ledger_upg_1to2.csv")
comb_orig = pd.read_csv(f"{ARCH_DIR}/ledger_combined_5strat_v191_slot1.csv")

# Step 2: Load ground-truth daily & 5m data + CSI 300
print("[2/6] Loading ground-truth daily & 5m price data...")
idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
sh300 = idx_cache["sh000300"]
all_dts = sorted(sh300.keys())
csi_canon = json.load(open(f"{SIM}/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json", encoding="utf-8"))

cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
da = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))])
dd = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))])
df_d = pd.concat([da, dd], ignore_index=True)
df_d["c6"] = df_d["ticker"].str[:6]
df_d = df_d[df_d["c6"].str.startswith(("00", "60")) & (~df_d["ticker"].str.endswith(".BJ"))].copy()
df_d["dt_s"] = df_d["date"].dt.strftime("%Y-%m-%d")
df_d.sort_values(["c6", "dt_s"], inplace=True)
df_d.drop_duplicates(["c6", "dt_s"], keep="first", inplace=True)
df_d["adjf"] = np.where(df_d["close"] > 0, df_d["adj_close"] / df_d["close"], 1.0)
g = df_d.groupby("c6")
df_d["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
df_d["dt_px"] = np.floor(df_d["prev_c_adj"] * 0.90 * 100.0 + 0.5) / 100.0
df_d["zt_px"] = np.floor(df_d["prev_c_adj"] * 1.10 * 100.0 + 0.5) / 100.0
df_d["is_zt"] = (df_d["close"] >= df_d["zt_px"] - 0.011) & (df_d["close"] / df_d["prev_c_adj"] - 1.0 >= 0.095)
df_d["is_dt_exact"] = (df_d["close"] <= df_d["dt_px"] + 0.005) & (df_d["prev_c_adj"] > 0)
df_d["is_yizi_dt"] = df_d["is_dt_exact"] & (df_d["open"] <= df_d["dt_px"] + 0.005) & (df_d["high"] <= df_d["dt_px"] + 0.005)
by_c = {c6: grp.reset_index(drop=True) for c6, grp in df_d.groupby("c6")}
dmap = {(r.c6, r.dt_s): r for r in df_d.itertuples(index=False)}

df5 = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
df5["c6"] = df5["c6"].astype(str).str.zfill(6)
df5.sort_values(["c6", "date", "hhmm_int"], inplace=True)
pit_5m = {(c6, str(dt)): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
          for (c6, dt), grp in df5.groupby(["c6", "date"], sort=False)}
sub2_5m = pickle.load(open(f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl", "rb"))
idx_5m_sub2 = {(k[0], k[2]): v for k, v in sub2_5m.items()}

def get_bars_5m(c6, dt):
    arr = pit_5m.get((c6, dt))
    if arr is not None and len(arr) > 0:
        return arr
    v = idx_5m_sub2.get((c6, dt))
    if isinstance(v, pd.DataFrame) and not v.empty:
        sub = v[v["date"] == dt]
        if not sub.empty:
            hh = sub["hhmm"].str.replace(":", "").astype(int).values
            return np.column_stack([hh, sub["open"].values, sub["high"].values, sub["low"].values, sub["close"].values, sub["volume"].values, sub["amount"].values])
    return None

def defer_dt_trade(c6, exit_dt, buy_dt, buy_px):
    gc = by_c[c6]
    pe = gc.index[gc["dt_s"] == exit_dt][0]
    k = pe + 1
    while k < len(gc) - 1 and bool(gc.loc[k, "is_yizi_dt"]):
        k += 1
    nb = gc.loc[k]
    bb = dmap[(c6, buy_dt)]
    nr = (float(nb.open) * float(nb.adjf)) / (float(buy_px) * float(bb.adjf)) * 0.9980 - 1.0
    return str(nb.dt_s), 925, round(float(nb.open), 2), float(nr), bool(gc.loc[pe + 1, "is_yizi_dt"])

# Step 3: Calibrate all 5 ledgers + strict102 / m42 refs
print("[3/6] Calibrating ledgers...")
change_log = {"3to4": [], "high": [], "2to3": [], "1to2": []}

# 3.1 Three-to-Four V4.1
def fix_3to4(df_in, log_list=None):
    d = df_in.copy()
    d["code"] = d["code"].astype(str).str.zfill(6)
    for i, r in d.iterrows():
        c6 = r["code"]
        eb = dmap[(c6, str(r["exit_date"])[:10])]
        if int(r["exit_hhmm"]) >= 1455 and bool(eb.is_dt_exact):
            ned, neh, nep, nret, skipped_yizi = defer_dt_trade(c6, str(r["exit_date"])[:10], str(r["buy_date"])[:10], float(r["buy_price"]))
            if log_list is not None:
                log_list.append({
                    "code": c6, "name": r["name"], "buy_date": str(r["buy_date"])[:10],
                    "orig_exit": f"{r['exit_date']} {int(r['exit_hhmm'])}@{r['exit_price']}", "orig_ret_pct": round(float(r["net_ret"]) * 100, 2),
                    "new_exit": f"{ned} {neh}@{nep}", "new_ret_pct": round(nret * 100, 2), "skipped_t1_yizi_dt": skipped_yizi,
                })
            d.loc[i, "exit_date"] = ned
            d.loc[i, "exit_hhmm"] = neh
            d.loc[i, "exit_price"] = nep
            d.loc[i, "net_ret"] = round(nret, 6)
    return d

d34_clean = fix_3to4(d34_orig, change_log["3to4"])
d34_strict_orig = pd.read_csv(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/ledger_3to4_xf30_strict.csv")
d34_strict_clean = fix_3to4(d34_strict_orig)

# 3.2 High Dragon V5.1 (True V5.1 t42 + m42 ref)
(_, _, _, code_bars_hd, _, _, _, _, _, _, _, _, _, _, SH_MAP, SZ_MAP) = pickle.load(
    open(f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/part1_cache.pkl", "rb")
)

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

def build_high_clean(raw_path, log_list=None):
    df_raw = pd.read_csv(raw_path)
    rows = []
    for r in df_raw.itertuples():
        c6 = str(r.code).zfill(6)
        bars = code_bars_hd[c6]
        d2p = bars["p"][r.buy_date]
        ep = bars["p"][r.exit_date]
        b_op = float(bars["open"][d2p])
        imap = SH_MAP if c6.startswith("60") else SZ_MAP
        arr_b = get_bars_5m(c6, r.buy_date)
        arr_e = get_bars_5m(c6, r.exit_date)

        if r.b_open_h:
            b_hhmm, b_px = 925, b_op
        else:
            ipx = round(b_op * 1.015, 2)
            b_hhmm, b_px = 935, ipx
            if arr_b is not None and len(arr_b) > 0:
                for row in arr_b:
                    if int(row[0]) > 1130: break
                    if row[2] >= ipx:
                        b_hhmm = int(row[0]); b_px = float(max(row[1], ipx)); break

        sealed_b = bool(bars["is_zt"][d2p])
        chained_zt = (not sealed_b) and (ep > d2p + 1) and any(bool(bars["is_zt"][mid]) for mid in range(d2p + 1, ep))
        pl = get_double_dev_px(bars, ep, imap, 0.07) if (sealed_b or chained_zt) else 99999.0

        e_dt = str(r.exit_date)
        if r.eo:
            e_hhmm, e_px = 925, float(bars["open"][ep])
        else:
            hit_dev = False
            if pl < 99990.0 and arr_e is not None and len(arr_e) > 0:
                for row in arr_e:
                    if row[2] >= pl:
                        e_hhmm = int(row[0]); e_px = float(max(row[1], pl)); hit_dev = True; break
            if not hit_dev:
                if pl < 99990.0 and float(bars["high"][ep]) >= pl:
                    e_hhmm, e_px = 1030, float(pl)
                else:
                    e_hhmm, e_px = 1500, float(bars["close"][ep])

        eb = dmap[(c6, e_dt)]
        if e_hhmm >= 1455 and bool(eb.is_dt_exact):
            ned, neh, nep, nret, skipped_y = defer_dt_trade(c6, e_dt, r.buy_date, b_px)
            if log_list is not None:
                log_list.append({"code": c6, "name": r.name, "buy_date": r.buy_date, "fix": "eod_limit_down_defer",
                                 "orig_exit": f"{e_dt} {e_hhmm}@{e_px:.2f}", "new_exit": f"{ned} {neh}@{nep}", "new_ret_pct": round(nret*100,2)})
            e_dt, e_hhmm, e_px = ned, neh, nep
        else:
            bb = dmap[(c6, r.buy_date)]; eb2 = dmap[(c6, e_dt)]
            nret = (e_px * eb2.adjf) / (b_px * bb.adjf) * 0.9980 - 1.0

        rows.append({
            "code": c6, "name": str(r.name), "buy_date": str(r.buy_date),
            "buy_hhmm": int(b_hhmm), "buy_price": round(b_px, 2),
            "exit_date": str(e_dt), "exit_hhmm": int(e_hhmm), "exit_price": round(e_px, 2),
            "net_ret": round(float(nret), 6), "score": int(r.sc),
        })
    return pd.DataFrame(rows)

dhd_clean = build_high_clean(f"{SIM}/backtests_astock/trainer_high_v51/v51_ledger_42.csv", change_log["high"])
dhd_m42_ref = build_high_clean(f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_morn_42_ledger.csv")

# 3.3 Pry V2.1
d_pry_ss16, d_pry_top1 = rta.reconstruct_pry_v21()

# 3.4 Two-to-Three V2.1 (Opt_V21)
d23_clean = d23_orig.copy()
d23_clean["code"] = d23_clean["code"].astype(str).str.zfill(6)
for i, r in d23_clean.iterrows():
    c6 = r["code"]
    if c6 == "002919" and r["buy_date"] == "2023-05-30":
        bb, eb = dmap[(c6, r["buy_date"])], dmap[(c6, "2023-06-01")]
        nret = (38.75 / float(r["buy_price"])) * (bb.qfq_factor / eb.qfq_factor) * 0.9980 - 1.0
        change_log["2to3"].append({
            "code": c6, "name": r["name"], "buy_date": r["buy_date"],
            "fix": "ex_div_pre_c_fix_zt_hold_to_0601_1500",
            "orig_exit": f"{r['exit_date']} {r['exit_hhmm']}@{r['exit_price']}", "orig_ret_pct": round(float(r["net_ret"])*100,2),
            "new_exit": "2023-06-01 1500@38.75", "new_ret_pct": round(nret*100,2),
        })
        d23_clean.loc[i, "exit_date"] = "2023-06-01"
        d23_clean.loc[i, "exit_hhmm"] = 1500
        d23_clean.loc[i, "exit_price"] = 38.75
        d23_clean.loc[i, "net_ret"] = round(nret, 8)
    elif c6 == "600262" and r["buy_date"] == "2024-07-25":
        bb, eb = dmap[(c6, r["buy_date"])], dmap[(c6, r["exit_date"])]
        nret = (float(r["exit_price"]) / float(r["buy_price"])) * (bb.qfq_factor / eb.qfq_factor) * 0.9980 - 1.0
        change_log["2to3"].append({
            "code": c6, "name": r["name"], "buy_date": r["buy_date"],
            "fix": "ex_div_qfq_ret_fix",
            "orig_exit": f"{r['exit_date']} {r['exit_hhmm']}@{r['exit_price']}", "orig_ret_pct": round(float(r["net_ret"])*100,2),
            "new_exit": f"{r['exit_date']} {r['exit_hhmm']}@{r['exit_price']}", "new_ret_pct": round(nret*100,2),
        })
        d23_clean.loc[i, "net_ret"] = round(nret, 8)

# 3.5 One-to-Two V19
d12_clean = d12_orig.copy()
d12_clean["code"] = d12_clean["code"].astype(str).str.zfill(6)
for i, r in d12_clean.iterrows():
    c6 = r["code"]
    if c6 == "002930" and r["buy_date"] == "2025-06-23":
        bb, eb = dmap[(c6, r["buy_date"])], dmap[(c6, r["exit_date"])]
        nret = (float(r["exit_price"]) / float(r["buy_price"])) * (bb.qfq_factor / eb.qfq_factor) * 0.9980 - 1.0
        change_log["1to2"].append({
            "code": c6, "name": r["name"], "buy_date": r["buy_date"], "fix": "ex_div_qfq_ret_fix",
            "orig_ret_pct": round(float(r["net_ret"])*100,2), "new_ret_pct": round(nret*100,2),
        })
        d12_clean.loc[i, "net_ret"] = round(nret, 4)
    elif c6 == "002361" and r["buy_date"] == "2025-12-19":
        ned, neh, nep, nret, skipped_y = defer_dt_trade(c6, r["exit_date"], r["buy_date"], float(r["buy_price"]))
        change_log["1to2"].append({
            "code": c6, "name": r["name"], "buy_date": r["buy_date"], "fix": "eod_limit_down_defer",
            "orig_exit": f"{r['exit_date']} {r['exit_hhmm']}@{r['exit_price']}", "orig_ret_pct": round(float(r["net_ret"])*100,2),
            "new_exit": f"{ned} {neh}@{nep}", "new_ret_pct": round(nret*100,2),
        })
        d12_clean.loc[i, "exit_date"] = ned
        d12_clean.loc[i, "exit_hhmm"] = neh
        d12_clean.loc[i, "exit_price"] = nep
        d12_clean.loc[i, "net_ret"] = round(nret, 4)
        d12_clean.loc[i, "tag"] = "eod_dt_defer_open"
        d12_clean.loc[i, "exit_at_open"] = True

# 3.6 Combined 5-Strategy V19.1
cols_c = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "buy_price", "exit_price", "net_ret"]
pool_clean = pd.concat([
    d34_clean.assign(strategy="三进四V4.1", priority=1)[cols_c],
    dhd_clean.assign(strategy="高标首阴V5.1", priority=2)[cols_c],
    d_pry_top1.assign(strategy="超跌撬板V2.1", priority=3)[cols_c],
    d23_clean.assign(strategy="二进三V2.1", priority=4)[cols_c],
    d12_clean.assign(strategy="一进二V19", priority=5)[cols_c],
], ignore_index=True)
pool_clean["code"] = pool_clean["code"].astype(str).str.zfill(6)
comb_clean = rta.run_1slot_sim(pool_clean)
comb_clean["nav_all"] = np.round(np.cumprod(1.0 + comb_clean["net_ret"].to_numpy()), 4)

# Step 4: Write Part C copies AND overwrite 5 official CSV paths
print("[4/6] Writing clean CSVs to Part C & official production paths...")
d34_clean.to_csv(OFFICIAL_PATHS["3to4"], index=False, encoding="utf-8-sig")
dhd_clean.to_csv(OFFICIAL_PATHS["high"], index=False, encoding="utf-8-sig")
d23_clean.to_csv(OFFICIAL_PATHS["2to3_official"], index=False, encoding="utf-8-sig")
d12_clean.to_csv(OFFICIAL_PATHS["1to2"], index=False, encoding="utf-8-sig")
comb_clean.to_csv(OFFICIAL_PATHS["comb"], index=False, encoding="utf-8-sig")

d34_clean.to_csv(f"{PARTC_DIR}/ledger_3to4_v41_clean.csv", index=False, encoding="utf-8-sig")
d34_strict_clean.to_csv(f"{PARTC_DIR}/ledger_3to4_v41_strict102_clean_ref.csv", index=False, encoding="utf-8-sig")
dhd_clean.to_csv(f"{PARTC_DIR}/ledger_high_v51_clean.csv", index=False, encoding="utf-8-sig")
dhd_m42_ref.to_csv(f"{PARTC_DIR}/ledger_high_v51_m42_clean_ref.csv", index=False, encoding="utf-8-sig")
d_pry_ss16.to_csv(f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv", index=False, encoding="utf-8-sig")
d_pry_top1.to_csv(f"{PARTC_DIR}/ledger_pry_v21_top1_clean.csv", index=False, encoding="utf-8-sig")
d23_clean.to_csv(f"{PARTC_DIR}/ledger_2to3_v21_opt_std90_clean.csv", index=False, encoding="utf-8-sig")
d12_clean.to_csv(f"{PARTC_DIR}/ledger_1to2_v19_clean.csv", index=False, encoding="utf-8-sig")
comb_clean.to_csv(f"{PARTC_DIR}/ledger_combined_5strat_v191_slot1_clean.csv", index=False, encoding="utf-8-sig")

# Step 5: Compute complete stats (5Y, Near-3Y, 2026, 2026H2, IS, OOS + HLZ t, DSR M=150, EQ, High sub-tiers)
print("[5/6] Computing complete D15, HLZ/DSR & EQ benchmarks...")
WINS = [
    ("5Y", "2021-11-15", "2026-11-16", csi_canon["全五年(2021-11-16起)"][0]),
    ("3Y", "2023-11-16", "2026-11-16", csi_canon["近三年(2023-11-16起)"][0]),
    ("2026", "2026-01-01", "2026-11-16", csi_canon["2026全年"][0]),
    ("2026H2", "2026-07-01", "2026-11-16", csi_canon["2026年7月以来"][0]),
    ("IS", "2021-11-15", "2023-12-31", round(rta.get_csi_ret(sh300, "2021-11-15", "2023-12-31"), 2)),
    ("OOS", "2024-01-01", "2026-11-16", csi_canon["近三年(2024-01-01起)"][0]),
]

def hlz_dsr(df):
    d = rta.norm_ledger(df)
    n = len(d)
    def _b(bd, ed):
        prevs = [x for x in all_dts if x < bd]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dts[0]]
        p1s = [x for x in all_dts if x <= ed]
        return float(sh300[p1s[-1]] / p0 - 1.0)
    ex = np.array([float(r.net_ret) - _b(r.buy_date, r.exit_date) for r in d.itertuples()], dtype=float)
    sr = float(ex.mean() / ex.std(ddof=1)) if n > 1 else 0.0
    t_val = sr * math.sqrt(n)
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(ex, fisher=False, bias=False))) if n > 3 else 3.0
    gm = 0.5772156649
    sr0 = (1.0 / math.sqrt(max(n - 1, 1))) * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / 150) + gm * stats.norm.ppf(1.0 - 1.0 / (150 * math.e)))
    den = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2)))
    dsr150 = float(stats.norm.cdf((sr - sr0) * math.sqrt(max(n - 1, 1)) / den))
    return round(t_val, 2), round(dsr150, 4)

def full_stats(df):
    d = rta.norm_ledger(df)
    out = {}
    for wlbl, s_dt, e_dt, csi_p in WINS:
        sub = d[(d["buy_date"] >= s_dt) & (d["buy_date"] <= e_dt)]
        m = rta.calc_core_metrics(sub["net_ret"].to_numpy(), csi_p)
        sr = np.sort(sub["net_ret"].to_numpy())
        m["trim3"] = round(float(np.prod(1.0 + sr[:-3])), 4) if len(sr) > 3 else 1.0
        m["trim5"] = round(float(np.prod(1.0 + sr[:-5])), 4) if len(sr) > 5 else 1.0
        out[wlbl] = m
    t_val, dsr150 = hlz_dsr(d)
    out["hlz_t"] = t_val
    out["dsr_m150"] = dsr150
    return out

# Raw EQ for 3to4 (from raw 115 signals in pit_exit_cache_full) and 2to3 (from sub90 in exit_engine)
sys.path.insert(0, f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4")
import exit_factor_engine as efe34, step4_audit_trunc_and_report as s434
cache34 = pickle.load(open(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/pit_exit_cache_full.pkl", "rb"))
states34 = efe34.precompute_trade_day_states(cache34, min_score=90.0)
raw34_df = efe34.evaluate_rule(cache34, states34, lambda st, ctx: {"tight_1345_thr": 0.070 if s434.risk7_score(st) >= 1 else 0.050}, "v41", 90.0)["raw_df"].copy()
raw34_clean = fix_3to4(raw34_df)
eq_3to4_clean = round(float(np.prod(1.0 + raw34_clean.groupby("buy_date")["net_ret"].mean())), 2)
a90_101_3to4 = d34_clean[d34_clean["score"] <= 101]

# High V5.1 sub-tiers
dhd_s96 = dhd_clean[dhd_clean["score"] >= 96]
dhd_a88 = dhd_clean[dhd_clean["score"] <= 95]
dhd_2224 = dhd_clean[dhd_clean["buy_date"] <= "2024-12-31"]
dhd_2426 = dhd_clean[dhd_clean["buy_date"] >= "2024-01-01"]
dhd_yrs = {y: round(float(np.prod(1.0 + dhd_clean[dhd_clean["buy_date"].str.startswith(y)]["net_ret"])), 2) for y in ("2022", "2023", "2024", "2025", "2026")}

# 2to3 sub90 EQ with 002919 & 600262 fixed
c23 = pickle.load(open(f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
supp5m = pickle.load(open(f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "rb"))
b5m2_23 = {**c23["b5m_need"], **supp5m["supp_5m"]}
sub90_23 = c23["gated_all"][(c23["gated_all"]["score_v2"] >= 90) & (c23["gated_all"]["buy_date"] >= "2021-11-15")].copy()
sub90_23["c6_str"] = sub90_23["code"].astype(str).str.zfill(6)
sys.path.insert(0, f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit")
import exit_engine as ee23
plook23, stkh23 = ee23.build_lookups(c23["da_need"][c23["da_need"]["c6"].isin(set(sub90_23["c6_str"]))].copy())
dt_idx23 = {x: i for i, x in enumerate(c23["all_dts"])}
r23_raw, ed23_raw, eh23_raw, _ = ee23.sim_exit_all(sub90_23, plook23, stkh23, b5m2_23, c23["all_dts"], dt_idx23, idx_cache["sh000002"], idx_cache["sz399107"], ee23.ExitConfig("opt", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065))
sub90_23["net_ret"] = r23_raw
sub90_23["exit_date"] = ed23_raw
for idx_r, r in sub90_23.iterrows():
    c6 = r["c6_str"]
    if c6 == "002919" and r["buy_date"] == "2023-05-30":
        bb, eb = dmap[(c6, r["buy_date"])], dmap[(c6, "2023-06-01")]
        bpx = round(float(r["prev_close"]) * (1.0 + float(r["open_pct"])), 2)
        sub90_23.loc[idx_r, "net_ret"] = (38.75 / bpx) * (bb.qfq_factor / eb.qfq_factor) * 0.9980 - 1.0
    elif c6 == "600262" and r["buy_date"] == "2024-07-25":
        bb, eb = dmap[(c6, r["buy_date"])], dmap[(c6, r["exit_date"])]
        bpx = round(float(r["prev_close"]) * (1.0 + float(r["open_pct"])), 2)
        sub90_23.loc[idx_r, "net_ret"] = (float(eb.close) / bpx) * (bb.qfq_factor / eb.qfq_factor) * 0.9980 - 1.0
eq_2to3_clean = round(float(np.prod(1.0 + sub90_23.groupby("buy_date")["net_ret"].mean())), 2)

# 1to2 EQ: check summary_upg_1to2 old eq_nav 65.74 with 002930 & 002361 (002361 & 002930 check if other signals on those days)
eq_1to2_approx = round(65.74 * ((1 + d12_clean.loc[d12_clean.code=="002930","net_ret"].values[0]) / (1 - 0.1130)) * ((1 + d12_clean.loc[d12_clean.code=="002361","net_ret"].values[0]) / (1 + 0.6452)), 2)

# Step 6: Run independent red-team assertions on ALL 6 active + clean ledgers
print("[6/6] Running strict Red-Team assertions on all 6 CSVs...")
bar_map = {k: {
    "open": float(v.open), "high": float(v.high), "low": float(v.low), "close": float(v.close),
    "adj_close": float(v.adj_close), "qfq_factor": float(v.qfq_factor),
    "prev_close": float(v.prev_c_adj) if pd.notna(v.prev_c_adj) else np.nan, "prev_qfq": np.nan,
} for k, v in dmap.items()}

def assert_ledger(name, path, is_high=False, allow_overlap=False):
    df = pd.read_csv(path)
    d = rta.norm_ledger(df)
    a = rta.audit_physical_integrity(name, d, bar_map)
    dt_exact_1500 = sum(1 for r in d.itertuples() if int(r.exit_hhmm) >= 1455 and bool(dmap[(r.code, r.exit_date)].is_dt_exact))
    non_sealed_93 = 0
    if is_high:
        for r in d.itertuples():
            bb = dmap[(r.code, r.buy_date)]
            if (not bool(bb.is_zt)) and int(r.exit_hhmm) not in (925, 1500):
                gc = by_c[r.code]
                p0 = gc.index[gc["dt_s"] == r.buy_date][0]
                pe = gc.index[gc["dt_s"] == r.exit_date][0]
                if not any(bool(gc.loc[mid, "is_zt"]) for mid in range(p0 + 1, pe)):
                    non_sealed_93 += 1
    res = {
        "n": int(a["n"]),
        "t0_violations": int(a["t0_violations"]),
        "overlap_violations": int(a["overlap_strict_count"]),
        "yizi_zt_buy": int(a["yizi_zt_buy_count"]),
        "yizi_dt_exit": int(a["yizi_dt_exit_count"]),
        "dt_sealed_1500_sell": int(dt_exact_1500),
        "ex_div_unadjusted_err": int(a["ret_mismatch_gt50bps_count"]),
        "buy_oob": int(a["buy_oob_count"]),
        "exit_oob": int(a["exit_oob_count"]),
        "non_sealed_d0_misapplied_93pct": int(non_sealed_93),
        "open_dt_925_exit_count": int(a["open_dt_925_exit_count"]),
    }
    assert res["t0_violations"] == 0, (name, res)
    if not allow_overlap:
        assert res["overlap_violations"] == 0, (name, res)
    assert res["yizi_zt_buy"] == 0, (name, res)
    assert res["yizi_dt_exit"] == 0, (name, res)
    assert res["dt_sealed_1500_sell"] == 0, (name, res)
    assert res["ex_div_unadjusted_err"] == 0, (name, res)
    assert res["buy_oob"] == 0 and res["exit_oob"] == 0, (name, res)
    assert res["non_sealed_d0_misapplied_93pct"] == 0, (name, res)
    return res

assertions = {
    "3to4_v41": assert_ledger("3to4_v41", OFFICIAL_PATHS["3to4"]),
    "high_v51": assert_ledger("high_v51", OFFICIAL_PATHS["high"], is_high=True),
    "pry_v21_ss165": assert_ledger("pry_v21_ss165", f"{PARTC_DIR}/ledger_pry_v21_ss165_clean.csv"),
    "pry_v21_top1": assert_ledger("pry_v21_top1", f"{PARTC_DIR}/ledger_pry_v21_top1_clean.csv", allow_overlap=True),
    "2to3_v21": assert_ledger("2to3_v21", OFFICIAL_PATHS["2to3_official"]),
    "1to2_v19": assert_ledger("1to2_v19", OFFICIAL_PATHS["1to2"]),
    "comb_v191": assert_ledger("comb_v191", OFFICIAL_PATHS["comb"]),
    "3to4_strict102_ref": assert_ledger("3to4_strict102_ref", f"{PARTC_DIR}/ledger_3to4_v41_strict102_clean_ref.csv"),
}

summary_out = {
    "csi300_canonical": csi_canon,
    "assertions": assertions,
    "change_log": change_log,
    "before_after": {
        "3to4_v41": {"before": full_stats(d34_orig), "after": full_stats(d34_clean), "eq_5y_clean": eq_3to4_clean,
                     "a90_101_wr": round(float((a90_101_3to4.net_ret > 0).mean() * 100), 1),
                     "s102_before": full_stats(d34_strict_orig), "s102_after": full_stats(d34_strict_clean)},
        "high_v51": {"before_partA": full_stats(dhd_orig), "after_t42": full_stats(dhd_clean), "after_m42_ref": full_stats(dhd_m42_ref),
                     "s96_wr": round(float((dhd_s96.net_ret > 0).mean() * 100), 1),
                     "a88_95_wr": round(float((dhd_a88.net_ret > 0).mean() * 100), 1),
                     "bear_22_24": full_stats(dhd_2224)["5Y"], "recent_24_26": full_stats(dhd_2426)["5Y"], "yearly_nav": dhd_yrs},
        "pry_v21": {"before": full_stats(d_pry_ss16), "after": full_stats(d_pry_ss16)},
        "2to3_v21": {"before_opt": full_stats(d23_orig), "after_opt": full_stats(d23_clean), "eq_5y_clean_approx": eq_2to3_clean},
        "1to2_v19": {"before": full_stats(d12_orig), "after": full_stats(d12_clean), "eq_5y_clean_approx": eq_1to2_approx},
        "comb_v191": {"before": full_stats(comb_orig), "after": full_stats(comb_clean), "by_strat": comb_clean["strategy"].value_counts().to_dict()},
    },
}

with open(f"{PARTC_DIR}/calibration_audit_v191.json", "w", encoding="utf-8") as f:
    json.dump(summary_out, f, ensure_ascii=False, indent=2)

print("ALL ASSERTIONS PASSED 100%!")
for k, v in summary_out["before_after"].items():
    if k in ("3to4_v41", "high_v51", "pry_v21", "2to3_v21", "1to2_v19", "comb_v191"):
        bk = "before" if "before" in v else ("before_partA" if "before_partA" in v else "before_opt")
        ak = "after" if "after" in v else ("after_t42" if "after_t42" in v else "after_opt")
        b5, a5 = v[bk]["5Y"], v[ak]["5Y"]
        a3, a26 = v[ak]["3Y"], v[ak]["2026"]
        print(f"  {k:10s} | 5Y: {b5['nav']:>12,.2f}x -> {a5['nav']:>12,.2f}x (WR {b5['wr']}->{a5['wr']}%, PLR {b5['plr']}->{a5['plr']}, MDD {b5['mdd']}->{a5['mdd']}%, T5={a5['trim5']}x, Cap10M={a5['cap10m']}x, Ex={a5['excess_pp']:+,.1f}pp)")
        print(f"             | 3Y: n={a3['n']} WR={a3['wr']}% PLR={a3['plr']} MDD={a3['mdd']}% NAV={a3['nav']:,.2f}x Ex={a3['excess_pp']:+,.1f}pp | 2026: n={a26['n']} WR={a26['wr']}% PLR={a26['plr']} MDD={a26['mdd']}% NAV={a26['nav']:,.2f}x Ex={a26['excess_pp']:+,.1f}pp")
print("High extras:", summary_out["before_after"]["high_v51"]["s96_wr"], summary_out["before_after"]["high_v51"]["a88_95_wr"], summary_out["before_after"]["high_v51"]["bear_22_24"], summary_out["before_after"]["high_v51"]["recent_24_26"], summary_out["before_after"]["high_v51"]["yearly_nav"])
print("3to4 extras: HLZ=", summary_out["before_after"]["3to4_v41"]["after"]["hlz_t"], "DSR=", summary_out["before_after"]["3to4_v41"]["after"]["dsr_m150"], "EQ=", eq_3to4_clean, "A90_101_WR=", summary_out["before_after"]["3to4_v41"]["a90_101_wr"], "S102_after=", summary_out["before_after"]["3to4_v41"]["s102_after"]["5Y"])
print("2to3 extras: HLZ=", summary_out["before_after"]["2to3_v21"]["after_opt"]["hlz_t"], "DSR=", summary_out["before_after"]["2to3_v21"]["after_opt"]["dsr_m150"], "EQ=", eq_2to3_clean, "trim3=", summary_out["before_after"]["2to3_v21"]["after_opt"]["5Y"]["trim3"])
print("1to2 extras: HLZ=", summary_out["before_after"]["1to2_v19"]["after"]["hlz_t"], "DSR=", summary_out["before_after"]["1to2_v19"]["after"]["dsr_m150"], "EQ~=", eq_1to2_approx, "trim3=", summary_out["before_after"]["1to2_v19"]["after"]["5Y"]["trim3"])
