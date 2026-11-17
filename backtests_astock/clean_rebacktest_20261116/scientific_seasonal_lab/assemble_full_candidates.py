#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import pickle, json, os, datetime
import pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
LAB_DIR = f"{CLEAN}/scientific_seasonal_lab"

FEE_RATE = 0.0020

# 1. 载入 1to2 宽候选
with open("/tmp/cands_1to2_broad.pkl", "rb") as f:
    cands_12 = pickle.load(f)

# 2. 载入 3to4 宽候选
cache_3to4_path = f"{ROOT}/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl"
with open(cache_3to4_path, "rb") as f:
    pkg_3to4 = pickle.load(f)

d_3to4 = pkg_3to4["df"]
p_3to4 = pkg_3to4["p_v32"]
sc_3to4 = pkg_3to4["sc_v34"]

cands_34 = []
for i in range(len(d_3to4)):
    sc = float(sc_3to4[i])
    if sc < 82.0: continue
    row = d_3to4.iloc[i]
    c6 = str(row["code"]).zfill(6)
    tr = p_3to4[i]
    triggered = bool(tr is not None and isinstance(tr, dict) and "net_ret" in tr)
    op_pct = float(row["open_pct"]) if hasattr(row, "open_pct") and pd.notna(row["open_pct"]) else 0.0
    
    if triggered:
        b_hhmm = int(tr.get("buy_hhmm", 935))
        b_px = float(tr.get("buy_price", row.get("open", 0.0)))
        ed = str(tr.get("exit_date", row["buy_date"]))
        e_hhmm = int(tr.get("exit_hhmm", 1500))
        epx = float(tr.get("exit_price", b_px))
        r_net = float(tr.get("net_ret", 0.0))
    else:
        b_hhmm, b_px, ed, e_hhmm, epx, r_net = 935, 0.0, str(row["buy_date"]), 1500, 0.0, 0.0

    cands_34.append({
        "strategy": "三进四_V34",
        "code": c6,
        "name": str(row["name"]),
        "buy_date": str(row["buy_date"]),
        "score": sc,
        "base_threshold": 90.0,
        "is_base_passed": bool(sc >= 90.0),
        "triggered": triggered,
        "buy_hhmm": b_hhmm,
        "buy_price": round(b_px, 2),
        "exit_date": ed,
        "exit_hhmm": e_hhmm,
        "exit_price": round(epx, 2),
        "net_ret": round(r_net, 6),
        "open_pct": round(op_pct, 4)
    })

# 3. 载入 High Dragon 宽候选
SRC_HIGH = f"{SANDBOX}/high_dragon_scorecard_20261113"
(all_dts_h, dt_to_idx_h, by_dt_h, code_bars_h, env_stats_h, _, t_lookup_h, _, _, _, stock_reg_h, ex_reg_h, tox_dates_h, CSI_MAP, SH_MAP, SZ_MAP) = pickle.load(open(f"{SRC_HIGH}/part1_cache.pkl", "rb"))
dfr_h = pd.read_pickle(f"{SRC_HIGH}/v5_enriched_119.pkl")

# Pit top 10
with open(f"{SANDBOX}/grand_factor_matrix_20261112/pit_top10_all_codes.json") as f:
    holders_pit = json.load(f)

def pit_lock_lookup(c6: str, dt_str: str) -> float:
    valid = [r for r in holders_pit.get(c6, []) if r[0] < dt_str]
    if not valid: return 38.0
    return float(max(valid, key=lambda x: x[1])[2])

for idx, r in dfr_h.iterrows():
    c6 = str(r["code"]).zfill(6)
    dfr_h.at[idx, "lock"] = pit_lock_lookup(c6, r["buy_date"])

# 5m bars
df_5m_pit = pd.read_parquet(f"{ROOT}/sim-portfolio/data/all_strategies_5m_complete_pit.parquet")
df_5m_pit.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_pit_map = {
    (c6, d): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
    for (c6, d), g in df_5m_pit.groupby(["c6", "date"], sort=False)
}

high_sub2_path = f"{SRC_HIGH}/sub2_5m_bars_cache.pkl"
bars_5m_sub2 = pickle.load(open(high_sub2_path, "rb")) if os.path.exists(high_sub2_path) else {}
idx_5m_sub2 = {(k[0], k[2]): v for k, v in bars_5m_sub2.items()}

def get_bars_5m(c6: str, dt: str) -> np.ndarray | None:
    arr = bars_5m_pit_map.get((c6, dt))
    if arr is not None and len(arr) > 0: return arr
    v = idx_5m_sub2.get((c6, dt))
    if isinstance(v, pd.DataFrame) and not v.empty:
        sub = v[v["date"] == dt]
        if not sub.empty:
            hh = sub["hhmm"].str.replace(":", "").astype(int).values
            return np.column_stack([hh, sub["open"].values, sub["high"].values, sub["low"].values, sub["close"].values, sub["volume"].values, sub["amount"].values])
    return None

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

cands_hd = []
for r in dfr_h.itertuples():
    if r.sc4 < 80: continue
    c6 = str(r.code).zfill(6)
    if c6 not in code_bars_h or r.buy_date not in code_bars_h[c6]["p"]: continue
    bars = code_bars_h[c6]
    d2p = bars["p"][r.buy_date]
    b_op = float(bars["open"][d2p])
    zt_px = float(bars["zt_px"][d2p])
    ex = "SH" if c6.startswith("60") else "SZ"
    imap = SH_MAP if ex == "SH" else SZ_MAP
    arr_b = get_bars_5m(c6, r.buy_date)
    
    triggered = False
    b_hhmm, b_px = 935, b_op
    
    if r.op2 >= 0.0:
        if r.op2 <= 0.045 and b_op < zt_px - 0.011:
            triggered = True
            b_px, b_hhmm = b_op, 925
    else:
        ipx = round(b_op * 1.015, 2)
        if ipx < zt_px - 0.011 and arr_b is not None and len(arr_b) > 0:
            for row in arr_b:
                if int(row[0]) > 1130: break
                if row[2] >= ipx:
                    b_hhmm, b_px = int(row[0]), float(max(row[1], ipx))
                    triggered = True
                    break

    net_ret, ep, epx, exit_hhmm, ed = 0.0, d2p, b_op, 1500, r.buy_date
    if triggered:
        n = len(bars["dts"])
        ep, epx, eo, exit_hhmm = None, None, False, 1500
        def run_zt_loop(start_p):
            imm = False
            for step in range(1, 8):
                p = start_p + step
                if p >= n: break
                pl = get_double_dev_px(bars, p, imap, 0.07)
                if bars["open"][p] >= pl: return p, float(bars["open"][p]), True, 925
                if bars["high"][p] >= pl: return p, float(pl), False, 1030
                if not bars["is_zt"][p]:
                    if (not imm) and (bars["close"][p] > bars["open"][p]):
                        imm = True; continue
                    while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                    return p, float(bars["close"][p]), False, 1500
            p_end = min(start_p + 5, n - 1)
            return p_end, float(bars["close"][p_end]), False, 1500

        if bars["is_zt"][d2p]:
            ep, epx, eo, exit_hhmm = run_zt_loop(d2p)
        else:
            p = min(d2p + 1, n - 1)
            while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
            if bars["is_zt"][p]: ep, epx, eo, exit_hhmm = run_zt_loop(p)
            else: ep, epx, eo, exit_hhmm = p, float(bars["close"][p]), False, 1500

        ed = bars["dts"][ep]
        arr_e = get_bars_5m(c6, ed)
        pl = get_double_dev_px(bars, ep, imap, 0.07)
        e_op, e_cl = float(bars["open"][ep]), float(bars["close"][ep])

        if eo:
            exit_hhmm, epx = 925, e_op
        else:
            hit_dev = False
            if arr_e is not None and len(arr_e) > 0:
                for row in arr_e:
                    if row[2] >= pl:
                        exit_hhmm, epx, hit_dev = int(row[0]), float(max(row[1], pl)), True
                        break
            if not hit_dev:
                if float(bars["high"][ep]) >= pl: exit_hhmm, epx = 1030, pl
                else: exit_hhmm, epx = 1500, e_cl

        net_ret = (epx * bars["adjf"][ep]) / (b_px * bars["adjf"][d2p]) * (1.0 - FEE_RATE) - 1.0

    cands_hd.append({
        "strategy": "高标首阴_V51",
        "code": c6,
        "name": r.name,
        "buy_date": r.buy_date,
        "score": float(r.sc4),
        "base_threshold": 88.0,
        "is_base_passed": bool(r.sc4 >= 88),
        "triggered": bool(triggered),
        "buy_hhmm": int(b_hhmm),
        "buy_price": round(float(b_px), 2),
        "exit_date": str(ed),
        "exit_hhmm": int(exit_hhmm),
        "exit_price": round(float(epx), 2),
        "net_ret": round(float(net_ret), 6),
        "open_pct": round(float(r.op2), 4)
    })

# 4. 打包输出
full_candidates = {
    "generated_at": datetime.datetime.now().isoformat(),
    "high_dragon": cands_hd,
    "3to4": cands_34,
    "1to2": cands_12
}

out_pkl = f"{LAB_DIR}/full_candidates_3main_5y.pkl"
with open(out_pkl, "wb") as f:
    pickle.dump(full_candidates, f)

print(f"\n✅ 5 年三大策略全量无遮蔽候选池生成完毕: {out_pkl}")
print(f"  高标首阴 V5.1 (>=80分): {len(cands_hd)} 条 (triggered={sum(c['triggered'] for c in cands_hd)})")
print(f"  三进四   V3.4 (>=82分): {len(cands_34)} 条 (triggered={sum(c['triggered'] for c in cands_34)})")
print(f"  一进二   V18  (>=thr-18): {len(cands_12)} 条 (triggered={sum(c['triggered'] for c in cands_12)})")
