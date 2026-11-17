#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_full_candidates_3main_5y.py
================================================================================
提取三大基础策略 5 年全周期全量近门槛候选池 (含真实 5m 撮合与触发状态)
落盘目标: scientific_seasonal_lab/full_candidates_3main_5y.pkl
================================================================================
"""
import os, sys, json, time, math, bisect, sqlite3, pickle, datetime
from collections import defaultdict
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
SIM = f"{ROOT}/sim-portfolio"
LAB_DIR = f"{CLEAN}/scientific_seasonal_lab"
os.makedirs(LAB_DIR, exist_ok=True)

FEE_RATE = 0.0020

# 1. 载入指数与日历
with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
    idx_cache = json.load(f)
CSI_MAP = idx_cache["sh000300"]
SH_MAP = idx_cache["sh000002"]
SZ_MAP = idx_cache["sz399107"]

# 2. 载入 100% 锁仓与 5m K 线库
TOP10_PATH = f"{SANDBOX}/grand_factor_matrix_20261112/pit_top10_all_codes.json"
with open(TOP10_PATH, "r", encoding="utf-8") as f:
    holders_pit = json.load(f)

def pit_lock_lookup(c6: str, dt_str: str) -> float:
    valid = [r for r in holders_pit.get(c6, []) if r[0] < dt_str]
    if not valid: return 38.0
    return float(max(valid, key=lambda x: x[1])[2])

print("[Step 1] Loading 5m bars pit map...")
df_5m_pit = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
df_5m_pit.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_pit_map = {
    (c6, d): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
    for (c6, d), g in df_5m_pit.groupby(["c6", "date"], sort=False)
}

high_sub2_path = f"{SANDBOX}/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"
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

# ==============================================================================
# 模块 A: 高标首阴 V5.1 全量候选池 (sc4 >= 80)
# ==============================================================================
print("\n[Step 2] Processing High Dragon V5.1 candidates (sc4 >= 80)...")
SRC_HIGH = f"{SANDBOX}/high_dragon_scorecard_20261113"
(all_dts_h, dt_to_idx_h, by_dt_h, code_bars_h, env_stats_h, _, t_lookup_h, _, _, _, stock_reg_h, ex_reg_h, tox_dates_h, _, _, _) = pickle.load(open(f"{SRC_HIGH}/part1_cache.pkl", "rb"))
dfr_h = pd.read_pickle(f"{SRC_HIGH}/v5_enriched_119.pkl")

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

high_cands_list = []
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
    
    # 模拟 morn_cond 触发状态
    triggered = False
    b_hhmm, b_px = 935, b_op
    is_auc = False
    
    if r.op2 >= 0.0:
        if r.op2 <= 0.045 and b_op < zt_px - 0.011:
            triggered = True
            b_px, is_auc, b_hhmm = b_op, True, 925
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

    high_cands_list.append({
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

print(f"High Dragon candidates (sc4 >= 80): {len(high_cands_list)} rows (triggered: {sum(c['triggered'] for c in high_cands_list)})")

# ==============================================================================
# 模块 B: 三进四 V3.4 全量候选池 (sc_v34 >= 82)
# ==============================================================================
print("\n[Step 3] Processing 3to4 V3.4 candidates (sc_v34 >= 82)...")
cache_3to4_path = f"{ROOT}/sim-portfolio/backtests_astock/special_26q4/3to4_26q4/cache_d_and_p.pkl"
with open(cache_3to4_path, "rb") as f:
    pkg_3to4 = pickle.load(f)

d_3to4 = pkg_3to4["df"]
p_3to4 = pkg_3to4["p_v32"]
sc_3to4 = pkg_3to4["sc_v34"]

three_to_four_cands_list = []
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

    three_to_four_cands_list.append({
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

print(f"3to4 candidates (sc >= 82): {len(three_to_four_cands_list)} rows (triggered: {sum(c['triggered'] for c in three_to_four_cands_list)})")

# ==============================================================================
# 模块 C: 一进二 V18 全量候选池 (sc_v >= thr_vec - 18.0)
# ==============================================================================
print("\n[Step 4] Processing 1to2 V18 candidates (sc_v >= thr_vec - 18.0)...")
BACKTEST_CLEAN_DIR = f"{SIM}/backtest/2026-11-11-1to2-clean"
BACKTEST_ASTOCK_DIR = f"{SIM}/backtests_astock"
if BACKTEST_CLEAN_DIR not in sys.path: sys.path.insert(0, BACKTEST_CLEAN_DIR)
if BACKTEST_ASTOCK_DIR not in sys.path: sys.path.insert(0, BACKTEST_ASTOCK_DIR)
if f"{BACKTEST_ASTOCK_DIR}/_archive/20261116_pre_clean_rebacktest" not in sys.path:
    sys.path.insert(0, f"{BACKTEST_ASTOCK_DIR}/_archive/20261116_pre_clean_rebacktest")

from clean_wf_1to2_v14_ironclad_master import (
    load_full_prices, BAD_NOTICE_PAT, NEG_NOTICE_PAT, HARD_NOTICE_PAT, HARD_NOTICE_ORIG_PAT,
    MA_NOTICE_PAT, EARN_NOTICE_PAT
)
from exp1_fake_theme_purifier import build_8y_purified_theme_metadata, compute_purifier_auction_scores

df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
price_lookup = {
    (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
    for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
}
stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)

fb = df_daily[df_daily["is_first_board"] & (~df_daily["is_yizi"]) & (df_daily["dt_str"] >= "2021-01-04")].copy()
c6_set = set(fb["c6"].unique())
notice_by_c6 = defaultdict(list)

DB_NOTICES_PATH = f"{SIM}/data/cninfo_notices_5y_pit.db"
if os.path.exists(DB_NOTICES_PATH):
    conn_notices = sqlite3.connect(f"file:{DB_NOTICES_PATH}?mode=ro", uri=True)
    for sec_code, pub_dt, avail_dt, title in conn_notices.execute(
        "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2020-12-25'"
    ):
        c6 = str(sec_code)[:6].zfill(6)
        if c6 not in c6_set or not pub_dt: continue
        ts = str(title or "")
        is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts))
        if is_neg:
            flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
        else:
            flags = (
                bool(HARD_NOTICE_ORIG_PAT.search(ts)),
                bool(HARD_NOTICE_PAT.search(ts)),
                bool(MA_NOTICE_PAT.search(ts)),
                bool(EARN_NOTICE_PAT.search(ts)),
                False,
            )
        if any(flags):
            notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), flags))
    conn_notices.close()

PARQUET_TOX_PATH = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
if os.path.exists(PARQUET_TOX_PATH):
    df_tox = pd.read_parquet(PARQUET_TOX_PATH)
    for sec_code, pub_dt, title in df_tox[["sec_code", "pub_datetime_cst", "title"]].itertuples(index=False):
        c6 = str(sec_code)[:6].zfill(6)
        if c6 not in c6_set or not pub_dt: continue
        ts = str(title or "")
        is_neg = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts)) or ("澄清" in ts)
        if is_neg:
            flags = (False, False, False, bool(EARN_NOTICE_PAT.search(ts)), True)
            notice_by_c6[c6].append((str(pub_dt), "", flags))

for c6 in notice_by_c6:
    notice_by_c6[c6].sort(key=lambda x: x[0])

rows_meta = []
cols_needed = [
    "c6", "dt_str", "d2_dt", "mcap", "amount", "f_dd20_d0", "f_dd60_d0", "f_pos20_d0",
    "f_d0_pct", "f_ret_pre10", "to", "f_d1_vol_ratio", "f_zt_cnt_pre20", "f_break60", "close", "d1_seal_tightness"
]
for r in fb[cols_needed].itertuples(index=False):
    c6, d1, d2 = r.c6, r.dt_str, (r.d2_dt if pd.notna(r.d2_dt) else "2026-11-16")
    ti = stock_theme_5y.get((d1, c6))
    if ti is None:
        ti = {
            "name": "", "plate": "其他", "r_short": "其他",
            "rk_o": 99, "t_score_o": 95.0, "gap_o": 0.0,
            "rk_c": 99, "t_score_c": 95.0, "gap_c": 0.0,
            "p_elo": 100.0, "s_elo": 100.0, "p_sz": 1, "n_yizi": 0,
            "has_new": False, "own_new": False, "spark": 0.0, "has_2b_lead": False,
            "is_ma": False, "is_tech_o": False, "is_tech_c": False, "is_earn": False,
            "is_event_basket": False, "is_broad_ind": False,
            "sub_cluster_cnt": 1, "is_dying_pulse": False,
        }

    start_cut = (datetime.date.fromisoformat(d1) - datetime.timedelta(days=4)).isoformat()
    end_cut = f"{d2} 09:25:00"
    nh_o = nh_c = n_ma = n_earn = n_bad = False
    nlist = notice_by_c6.get(c6)
    if nlist:
        lo = bisect.bisect_left(nlist, (start_cut, "", ()))
        for idx_n in range(lo, len(nlist)):
            pdt, adt, fl = nlist[idx_n]
            if pdt > end_cut: break
            if adt and adt > d2: continue
            nh_o |= fl[0]; nh_c |= fl[1]; n_ma |= fl[2]; n_earn |= fl[3]; n_bad |= fl[4]

    if n_bad: nh_c = False; nh_o = False; n_ma = False
    is_ma_f = bool(ti["is_ma"] or n_ma)

    rk_c, p_sz = ti["rk_c"], ti["p_sz"]
    s_prior_dual = (
        (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
        + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
        + (12 if ti["has_new"] else 0) + (8 if ti["own_new"] else 0) + (10 if ti["spark"] > 0 else 0)
        + (18 if nh_c else 0) + (18 if is_ma_f else 0) + (12 if ti["is_tech_c"] else 0)
        + (12 if ti["gap_c"] >= 20.0 else 0)
        + float(np.clip((ti["t_score_c"] - 100.0) * 0.25, 0.0, 25.0))
        + float(np.clip((ti["s_elo"] - 100.0) * 0.35, -10.0, 18.0))
    )

    mcap = float(r.mcap) if pd.notna(r.mcap) else 50.0
    amt = float(r.amount) if pd.notna(r.amount) else 2e8
    dd20 = float(r.f_dd20_d0) if pd.notna(r.f_dd20_d0) else 0.90
    dd60 = float(r.f_dd60_d0) if pd.notna(r.f_dd60_d0) else 0.85
    pos20 = float(r.f_pos20_d0) if pd.notna(r.f_pos20_d0) else 0.50
    d0_pct = float(r.f_d0_pct) if pd.notna(r.f_d0_pct) else 0.0
    ret10 = float(r.f_ret_pre10) if pd.notna(r.f_ret_pre10) else 0.0
    to = float(r.to) if pd.notna(r.to) else 8.0
    vr = float(r.f_d1_vol_ratio) if pd.notna(r.f_d1_vol_ratio) else 1.5
    zt20 = int(r.f_zt_cnt_pre20) if pd.notna(r.f_zt_cnt_pre20) else 0
    brk60 = int(r.f_break60)

    seal_r = seal_rate_map.get(d1, 0.55)
    dt_cnt = dt_cnt_map.get(d1, 5)
    zt_cnt = zt_cnt_map.get(d1, 50)
    promo5 = promo_ma5_map.get(d1, 0.20)

    sc_mcap = 28 if 60 <= mcap <= 155 else (10 if 40 <= mcap < 60 else (-20 if mcap < 35 else 0))
    sc_amt = 18 if 2.2e8 <= amt <= 15e8 else (-25 if amt < 1.8e8 else -10)
    sc_dd20 = 42 if dd20 <= 0.82 else (32 if dd20 <= 0.86 else (18 if dd20 <= 0.90 else (-40 if dd20 > 0.95 else 0)))
    sc_dd60 = 18 if dd60 <= 0.76 else (10 if dd60 <= 0.82 else (-15 if dd60 > 0.92 else 0))
    sc_pos = 18 if pos20 <= 0.40 else (-20 if pos20 > 0.85 else 0)
    sc_d0 = 12 if d0_pct <= 0.02 else (-15 if d0_pct > 0.06 else 0)
    sc_ret10 = 12 if ret10 <= 0.05 else (-15 if ret10 > 0.25 else 0)
    sc_to = 15 if 5.0 <= to <= 16.0 else (-20 if to > 28.0 else -10)
    sc_vr = 15 if 1.2 <= vr <= 4.0 else (-12 if vr > 8.0 else 0)
    sc_zt20 = 12 if zt20 >= 1 else 0
    sc_brk60 = 18 if brk60 == 1 else 0

    sc_seal = 15 if seal_r >= 0.70 else (-25 if seal_r < 0.45 else 0)
    sc_dt = 15 if dt_cnt <= 2 else (-30 if dt_cnt >= 12 else 0)
    sc_zt = 12 if zt_cnt >= 60 else (-15 if zt_cnt < 35 else 0)
    sc_p5 = 12 if promo5 >= 0.25 else (-15 if promo5 < 0.12 else 0)

    s_quant_dual = (
        sc_mcap + sc_amt + sc_dd20 + sc_dd60 + sc_pos + sc_d0 + sc_ret10 + sc_to + sc_vr + sc_zt20 + sc_brk60
        + sc_seal + sc_dt + sc_zt + sc_p5
    )

    rows_meta.append({
        "c6": c6, "dt_str": d1, "d2_dt": d2, "name": ti["name"], "plate": ti["plate"],
        "rk_theme": ti["rk_c"], "p_sz": ti["p_sz"], "s_prior_dual": s_prior_dual, "s_quant_dual": s_quant_dual,
        "score_dual": s_prior_dual + s_quant_dual,
        "notice_hard": bool(nh_c), "notice_bad": bool(n_bad), "is_ma": is_ma_f,
        "has_new_term": bool(ti["has_new"]), "own_new_term": bool(ti["own_new"]),
        "spark": float(ti["spark"]), "is_dying_pulse": bool(ti["is_dying_pulse"]),
        "is_event_basket": bool(ti["is_event_basket"]), "p_elo": float(ti["p_elo"]),
        "d1_seal_tightness": float(r.d1_seal_tightness) if pd.notna(r.d1_seal_tightness) else 50.0,
        "f_dd20_d0": dd20, "clean_brk60": brk60,
        "mkt_seal_rate": seal_r, "d1_zt_cnt": zt_cnt,
        "is_pioneer_word": bool(ti["has_new"] or ti["own_new"])
    })

hist_fb = pd.DataFrame(rows_meta)
print(f"Loaded {len(hist_fb)} hist_fb rows, computing auction scores...")
hist_fb = compute_purifier_auction_scores(hist_fb)

# 纯正 V18 基础打分与过滤规则 (100% 锁死不动)
bonus_spear = np.where(hist_fb["f_spear_auc"].fillna(False), 18.0, 0.0)
thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)
f3_bonus = np.where(hist_fb["notice_bad"], -35.0, 0.0)
wk_mask = hist_fb["gap_days"] >= 3
score_wk = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
s_prior_wk = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

name_sub20 = np.where(hist_fb["name"].str.contains("深|特|中|力", na=False), 5.0, 0.0)
y_v17 = hist_fb["f_rk_score_17"].fillna(0.0).values
bon_tape = np.where(hist_fb["tape_lead_ratio"].fillna(0.0) >= 0.025, 8.0, 0.0)
rk_fix_delta = np.where(hist_fb["rk_theme"] == 1, 10.0, np.where(hist_fb["rk_theme"] == 2, 5.0, 0.0))
d_ov = np.where(hist_fb["f_ov_score"].fillna(False), 12.0, 0.0)

sc_climax_pen = np.where(hist_fb["d1_zt_cnt"] >= 100, -15.0, np.where(hist_fb["d1_zt_cnt"] >= 95, -10.0, 0.0))
sc_seal_pen = np.where(hist_fb["mkt_seal_rate"] >= 0.80, -10.0, 0.0)
sc_cap_pen = np.where(hist_fb["f_cap_pen_cand"].fillna(False), -12.0, 0.0)

t3_med_map = hist_fb.groupby("d2_dt")["p_elo"].median().to_dict()
_t1m = hist_fb["p_elo"].values
_t3m = hist_fb["d2_dt"].map(t3_med_map).fillna(0.0).values
v18_dom_t3 = (_t1m >= 65.0) & (_t1m - _t3m >= 35.0) & (_t3m < 42.0)
sc_t3_pen = np.where(v18_dom_t3 & (hist_fb["rk_theme"].values >= 3), -15.0, 0.0)
v18_pen = sc_climax_pen + sc_seal_pen + sc_cap_pen + sc_t3_pen

sp_v = s_prior_wk + name_sub20 + y_v17 * 0.5
sq_v = hist_fb["s_quant_dual"].values + d_ov + bon_tape + rk_fix_delta + y_v17 * 0.5
sc_v = sp_v + sq_v + v18_pen
hist_fb["score_active"] = sc_v

common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_l1 = ~hist_fb["is_event_basket"]
pass_l2 = ~hist_fb["is_dying_pulse"]
pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | ((hist_fb["plate_peers_open_avg"] >= -0.010) & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2)))
pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
p_tight = (hist_fb["d1_seal_tightness"] >= 37.0).values
open_in_win = (
    (wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088))
    | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))
).values

# 放宽至近门槛池 (thr_vec - 18.0)
m_t1_broad = common_ok & open_in_win & (sp_v >= 40.0) & (sc_v >= thr_vec - 18.0)
pass_nd_true = ~(hist_fb["notice_bad"])

tot_cand_broad = m_t1_broad & pass_l1 & pass_l2 & pass_l3 & pass_nd_true & pass_ac & p_tight
sub_broad = hist_fb[tot_cand_broad & (hist_fb["d2_dt"] >= "2021-11-15") & (hist_fb["d2_dt"] <= "2026-11-16")].copy()
sub_broad.sort_values(["d2_dt", "score_active"], ascending=[True, False], inplace=True)

# 5m 真实交易引擎
from clean_rebacktest_v18_clean import make_clean_trade_engine
fn_clean_12 = make_clean_trade_engine(fee=FEE_RATE)

one_to_two_cands_list = []
for d2, grp in sub_broad.groupby("d2_dt", sort=True):
    # 保存该日头名候选
    top_r = grp.iloc[0]
    tr = fn_clean_12(top_r)
    triggered = bool(tr is not None)
    sc = float(top_r["score_active"])
    base_t = float(thr_vec[top_r.name]) if hasattr(top_r, "name") and top_r.name in thr_vec else 304.8
    
    op_pct = float(top_r.get("d2_o_pct", 0.0))
    if triggered:
        b_hhmm = int(tr.get("buy_hhmm", 925 if tr.get("b_open_h", False) else 935))
        b_px = float(tr.get("buy_price", top_r.get("open", 0.0)))
        ed = str(tr.get("exit_date", d2))
        e_hhmm = int(tr.get("exit_hhmm", 925 if tr.get("exit_at_open", False) else 1500))
        epx = float(tr.get("exit_price", b_px))
        r_net = float(tr.get("net_ret", 0.0))
    else:
        b_hhmm, b_px, ed, e_hhmm, epx, r_net = 935, 0.0, str(d2), 1500, 0.0, 0.0

    one_to_two_cands_list.append({
        "strategy": "一进二_V18",
        "code": str(top_r["c6"]).zfill(6),
        "name": str(top_r["name"]),
        "buy_date": str(d2),
        "score": round(sc, 1),
        "base_threshold": round(base_t, 1),
        "is_base_passed": bool(sc >= base_t),
        "triggered": triggered,
        "buy_hhmm": b_hhmm,
        "buy_price": round(b_px, 2),
        "exit_date": ed,
        "exit_hhmm": e_hhmm,
        "exit_price": round(epx, 2),
        "net_ret": round(r_net, 6),
        "open_pct": round(op_pct, 4)
    })

print(f"1to2 candidates (score >= thr-18): {len(one_to_two_cands_list)} rows (triggered: {sum(c['triggered'] for c in one_to_two_cands_list)})")

# ==============================================================================
# 模块 D: 打包落盘 full_candidates_3main_5y.pkl
# ==============================================================================
full_pool = {
    "generated_at": datetime.datetime.now().isoformat(),
    "high_dragon": high_cands_list,
    "3to4": three_to_four_cands_list,
    "1to2": one_to_two_cands_list
}
pkl_path = f"{LAB_DIR}/full_candidates_3main_5y.pkl"
with open(pkl_path, "wb") as f:
    pickle.dump(full_pool, f)

print(f"\n✅ 全量无遮蔽三大策略每日候选池打包完成: {pkl_path}")
print(f"  高标首阴 V5.1 (>=80分): {len(high_cands_list)} 条")
print(f"  三进四   V3.4 (>=82分): {len(three_to_four_cands_list)} 条")
print(f"  一进二   V18  (>=thr-18): {len(one_to_two_cands_list)} 条")
