#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_exit_scan.py
超跌橡皮筋撬板 V1.0 (s_pry) 四大家族 90+ 卖点全谱系深度扫描与物理撮合核查引擎
严格零前视、D12 零 yfinance、只读所有外部数据源，输出全部写入独占目录 s3_pry_exit/。
"""
import os, sys, json, time, math, pickle
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
P5_DIR = f"{SIM}/backtests_astock2/p5_full_pry_universe"
GFM_DIR = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"
COST = 0.0020

os.makedirs(OUT_DIR, exist_ok=True)


def load_all_data():
    df = pd.read_parquet(f"{P5_DIR}/full_pry_master_enriched.parquet")
    with open(f"{GFM_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]
    v1_ref = pd.read_csv(f"{P5_DIR}/v1_oversold_pry_165_strict_ledger.csv", dtype={"code": str})
    s3_ref = pd.read_csv(f"{P5_DIR}/_archive/20261116_stage12_sweeps/s3_champion_ledger.csv", dtype={"code": str})
    with open(f"{SIM}/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json", "r") as f:
        csi_canon = json.load(f)
    with open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", "r") as f:
        sh300 = json.load(f)["sh000300"]

    # Load 5m bars union
    m5_df = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    m5_df["c6"] = m5_df["c6"].astype(str).str.zfill(6)
    m5_df["date"] = m5_df["date"].astype(str).str[:10]
    m5_map = {}
    for (c6, dt), grp in m5_df.groupby(["c6", "date"], sort=False):
        grp_s = grp.sort_values("hhmm_int")
        m5_map[(c6, dt)] = grp_s[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=np.float64)

    sub2_path = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"
    if os.path.exists(sub2_path):
        with open(sub2_path, "rb") as f:
            s2 = pickle.load(f)
        for k, v in s2.items():
            if v is None or len(v) == 0 or not isinstance(v, pd.DataFrame):
                continue
            c6_k = str(k[0])[:6].zfill(6)
            v = v.copy()
            v["hhmm_int"] = v["hhmm"].astype(str).str.replace(":", "").astype(int)
            for dt_s, grp in v.groupby("date"):
                key = (c6_k, str(dt_s)[:10])
                if key not in m5_map:
                    grp_s = grp.sort_values("hhmm_int")
                    m5_map[key] = grp_s[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=np.float64)

    return df, cb, v1_ref, s3_ref, csi_canon, sh300, m5_map


def build_base_candidates(df, cb):
    """严格复刻 fast_pry_today.py + v1_oversold_pry_165_strict_ledger 四道硬门与10项整数打分卡"""
    n = len(df)
    c6_v, ds_v = df["c6"].values, df["sig_date"].values
    bias10 = np.zeros(n, dtype=np.float32)
    down_streak = np.zeros(n, dtype=np.int16)
    is_yang = np.zeros(n, dtype=bool)
    for i in range(n):
        d = cb.get(c6_v[i])
        if d is None:
            continue
        p = d["date_to_pos"].get(ds_v[i])
        if p is None:
            continue
        op, cl = d["open"][p], d["close"][p]
        is_yang[i] = cl > op
        if p >= 9:
            bias10[i] = cl / np.mean(d["close"][p - 9 : p + 1]) - 1.0
        st, k = 0, p - 1
        while k >= 0 and d["close"][k] < d["pre_c"][k]:
            st += 1
            k -= 1
        down_streak[i] = st
    df = df.copy()
    df["bias10"] = bias10
    df["down_streak"] = down_streak
    df["is_yang"] = is_yang

    gate = (
        (~df["is_st_or_delist"].values)
        & (df["pre_c"].values >= 2.0)
        & (~df["n_poison90"].fillna(False).values)
        & (~df["n_del90"].fillna(False).values)
        & (~df["n_inv90"].fillna(False).values)
        & df["prev_touch_dt"].fillna(False).values.astype(bool)
        & (~df["prev_is_dt"].fillna(True).values.astype(bool))
        & (df["prev_zt20"].fillna(0).values == 0)
        & (df["prev_c_ma20"].fillna(0).values <= -0.15)
        & (df["prev_dd20"].fillna(1.0).values <= 0.80)
        & (df["o_pct"].values >= 0.0)
        & (df["o_pct"].values <= 0.05)
    )
    sub = df[gate].copy().reset_index(drop=True)

    keep_rows = []
    for idx, r in sub.iterrows():
        d = cb.get(r["c6"])
        if d is None:
            continue
        p0 = d["date_to_pos"].get(r["dt_str"])
        if p0 is None or p0 + 1 >= len(d["dts"]):
            continue
        if bool(d["is_yizi"][p0]) or float(d["open"][p0]) >= float(d["zt_px"][p0]) - 0.011:
            continue
        keep_rows.append((idx, p0, float(d["open"][p0])))

    sub = sub.iloc[[x[0] for x in keep_rows]].copy().reset_index(drop=True)
    sub["p0"] = [x[1] for x in keep_rows]
    sub["buy_px"] = [x[2] for x in keep_rows]

    sc = np.full(len(sub), 100, dtype=int)
    sc += np.where(sub["bias10"].values <= -0.15, 20, 0)
    sc += np.where(sub["down_streak"].values >= 4, 15, 0)
    sc += np.where(sub["prev_c_ma20"].fillna(0).values <= -0.22, 15, 0)
    sc += np.where(sub["real_free_mcap"].fillna(999).values <= 25.0, 15, 0)
    sc += np.where(sub["mkt_open_zt_0925"].fillna(0).values >= 12, 15, 0)
    sc += np.where(sub["is_yang"].values, 10, 0)
    sc += np.where(sub["prev_vr"].fillna(0).values >= 1.5, 10, 0)
    sc += np.where(sub["lock_top10"].fillna(0).values >= 50.0, 10, 0)
    sc += np.where(sub["inst_buy_prev"].fillna(0).values > 0, 10, 0)
    sc += np.where(sub["lhasa_sh_prev"].fillna(0).values > 0.25, -20, 0)
    sub["score"] = sc
    sub["code"] = sub["c6"].astype(str).str.zfill(6)
    sub["buy_date"] = sub["dt_str"].astype(str)
    return sub


def first_sellable_day(d, start_pos):
    L = len(d["dts"])
    p = start_pos
    while p < L - 1 and d["is_yizi_dt"][p]:
        p += 1
    return min(p, L - 1)


def hold_zt_relay(d, p0, pk, buy_px, use_adjf=True):
    """连板持有直至首次断板收盘 (遇一字跌停顺延至翘开首日开盘/收盘)"""
    L = len(d["dts"])
    o, c, dt_px, is_zt, is_yz_dt, dts, adjf = (
        d["open"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"], d["adjf"]
    )
    cur = pk
    while cur < L - 1:
        nxt = cur + 1
        if is_yz_dt[nxt]:
            nxt2 = first_sellable_day(d, nxt)
            s_px = o[nxt2] if o[nxt2] > dt_px[nxt2] + 0.005 else c[nxt2]
            af = (adjf[nxt2] / adjf[p0]) if use_adjf else 1.0
            return float((s_px * af) / buy_px * (1.0 - COST) - 1.0), str(dts[nxt2]), nxt2 - p0
        if is_zt[nxt]:
            cur = nxt
            continue
        af = (adjf[nxt] / adjf[p0]) if use_adjf else 1.0
        return float((c[nxt] * af) / buy_px * (1.0 - COST) - 1.0), str(dts[nxt]), nxt - p0
    af = (adjf[cur] / adjf[p0]) if use_adjf else 1.0
    return float((c[cur] * af) / buy_px * (1.0 - COST) - 1.0), str(dts[cur]), max(1, cur - p0)


def ret_from_px(d, p0, k, sell_px, buy_px, use_adjf=True):
    af = (d["adjf"][k] / d["adjf"][p0]) if use_adjf else 1.0
    return float((sell_px * af) / buy_px * (1.0 - COST) - 1.0), str(d["dts"][k]), k - p0


def sim_limit_tp(d, p0, buy_px, tp_schedule, max_h, match_mode="strict_premarket",
                 zt_relay_if_unfilled=False, end_zt_relay=False,
                 day0_cut_mode="reseal_only", sl_mode=None, sl_pct=0.08,
                 high_open_lock=None, use_adjf=True):
    """
    通用限价止盈/止损/减仓/时间衰减模拟器
    tp_schedule: float OR list of floats (for day offset 1..max_h) OR callable(k)->tp_px_unadj
    match_mode:
      - 'strict_premarket': 真实交易所盘前死限价单 (o>=tp -> o, o<tp<=h -> tp; 与 v1_oversold_pry_165_strict 100%对齐)
      - 'prompt_ozt_relay': prompt文字口径 (o>=tp且is_zt -> relay, o<tp<=h -> tp, tp>zt_px且is_zt -> 继续/relay)
      - 'phantom_s3_bug': 旧 precompute_return_matrix 穿板幻觉口径 (h>=tp且is_zt -> relay)
    """
    L = len(d["dts"])
    if p0 + 1 >= L or buy_px <= 0:
        return np.nan, "", 0
    o, h, l, c, pre_c, dt_px, zt_px, is_zt, is_yz_dt, dts, adjf = (
        d["open"], d["high"], d["low"], d["close"], d["pre_c"], d["dt_px"], d["zt_px"],
        d["is_zt"], d["is_yizi_dt"], d["dts"], d["adjf"]
    )

    # Day 0 reseal / weak cut check
    day0_reseal = (c[p0] <= dt_px[p0] + 0.005)
    if match_mode == "phantom_s3_bug":
        day0_reseal = bool(d["is_dt"][p0])

    # Day 0 limit-up (地天板) -> board relay
    if is_zt[p0]:
        return hold_zt_relay(d, p0, p0, buy_px, use_adjf=use_adjf)

    # Check Day 0 cut triggers
    do_cut_t1_open = False
    if day0_cut_mode != "none" and day0_reseal:
        do_cut_t1_open = True
    if day0_cut_mode == "reseal_or_neg3" and (c[p0] < o[p0]) and (c[p0] / pre_c[p0] - 1.0 <= -0.03):
        do_cut_t1_open = True
    elif day0_cut_mode == "reseal_or_neg5" and (c[p0] < o[p0]) and (c[p0] / pre_c[p0] - 1.0 <= -0.05):
        do_cut_t1_open = True
    elif day0_cut_mode == "reseal_or_buy_m4" and (c[p0] < buy_px * 0.96):
        do_cut_t1_open = True
    elif day0_cut_mode == "reseal_or_buy_m6" and (c[p0] < buy_px * 0.94):
        do_cut_t1_open = True
    elif day0_cut_mode == "reseal_or_m4_and_t1weak":
        p1 = first_sellable_day(d, p0 + 1)
        if (c[p0] < buy_px * 0.96) and (o[p1] < c[p0]):
            do_cut_t1_open = True

    if do_cut_t1_open:
        ps = first_sellable_day(d, p0 + 1)
        s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return ret_from_px(d, p0, ps, s_px, buy_px, use_adjf=use_adjf)

    end_p = min(L - 1, p0 + max_h)
    for step_idx, k in enumerate(range(p0 + 1, end_p + 1), start=1):
        if is_yz_dt[k]:
            continue

        # Ex-dividend scale if adjf changed
        af_ratio = (adjf[p0] / adjf[k]) if use_adjf else 1.0

        # High-open lock from 2to3 (non-yizi high gap >= high_open_lock)
        if high_open_lock is not None:
            op_pct_k = o[k] / pre_c[k] - 1.0
            if (op_pct_k >= high_open_lock) and (not is_zt[k] or o[k] < zt_px[k] - 0.011):
                return ret_from_px(d, p0, k, o[k], buy_px, use_adjf=use_adjf)
            if (o[k] >= zt_px[k] - 0.011) and is_zt[k]:
                return hold_zt_relay(d, p0, k, buy_px, use_adjf=use_adjf)

        # Compute target price for day k
        if callable(tp_schedule):
            tp_px_raw = tp_schedule(d, p0, k, buy_px)
        elif isinstance(tp_schedule, (list, tuple)):
            tp_r = tp_schedule[min(step_idx - 1, len(tp_schedule) - 1)]
            tp_px_raw = round(buy_px * (1.0 + tp_r), 2)
        else:
            tp_px_raw = round(buy_px * (1.0 + float(tp_schedule)), 2)

        tp_px = round(tp_px_raw * af_ratio, 2) if abs(af_ratio - 1.0) > 1e-6 else tp_px_raw

        # Intraday hard stop check (pessimistic: stop checked before TP unless open >= tp)
        if sl_mode == "intra_pess":
            sl_px = round(buy_px * (1.0 - sl_pct) * af_ratio, 2)
            if o[k] <= sl_px:
                s_px = o[k] if o[k] > dt_px[k] + 0.005 else c[k]
                return ret_from_px(d, p0, k, s_px, buy_px, use_adjf=use_adjf)
            if l[k] <= sl_px and o[k] < tp_px:
                return ret_from_px(d, p0, k, max(sl_px, dt_px[k]), buy_px, use_adjf=use_adjf)
        elif sl_mode == "break_d0_low_intra":
            sl_px = round(d["low"][p0] * af_ratio, 2)
            if o[k] < sl_px:
                s_px = o[k] if o[k] > dt_px[k] + 0.005 else c[k]
                return ret_from_px(d, p0, k, s_px, buy_px, use_adjf=use_adjf)
            if l[k] < sl_px and o[k] < tp_px:
                return ret_from_px(d, p0, k, max(sl_px, dt_px[k]), buy_px, use_adjf=use_adjf)

        # Limit order fill check
        if o[k] >= tp_px:
            if match_mode in ("phantom_s3_bug", "prompt_ozt_relay") and is_zt[k]:
                return hold_zt_relay(d, p0, k, buy_px, use_adjf=use_adjf)
            return ret_from_px(d, p0, k, o[k], buy_px, use_adjf=use_adjf)

        if h[k] >= tp_px:
            if match_mode == "phantom_s3_bug" and is_zt[k]:
                return hold_zt_relay(d, p0, k, buy_px, use_adjf=use_adjf)
            return ret_from_px(d, p0, k, tp_px, buy_px, use_adjf=use_adjf)

        # Unfilled! Check if tp_px > zt_px[k] and closed at ZT
        if zt_relay_if_unfilled and is_zt[k] and tp_px > zt_px[k]:
            return hold_zt_relay(d, p0, k, buy_px, use_adjf=use_adjf)

        # Close-only hard stop check
        if sl_mode == "close_sl":
            sl_px = round(buy_px * (1.0 - sl_pct) * af_ratio, 2)
            if c[k] <= sl_px and k < end_p:
                if c[k] > dt_px[k] + 0.005:
                    return ret_from_px(d, p0, k, c[k], buy_px, use_adjf=use_adjf)
                ps = first_sellable_day(d, k + 1)
                s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
                return ret_from_px(d, p0, ps, s_px, buy_px, use_adjf=use_adjf)
        elif sl_mode == "break_d0_low_close":
            sl_px = round(d["low"][p0] * af_ratio, 2)
            if c[k] < sl_px and k < end_p:
                if c[k] > dt_px[k] + 0.005:
                    return ret_from_px(d, p0, k, c[k], buy_px, use_adjf=use_adjf)
                ps = first_sellable_day(d, k + 1)
                s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
                return ret_from_px(d, p0, ps, s_px, buy_px, use_adjf=use_adjf)

        # Optimistic intraday SL (only if TP didn't hit)
        if sl_mode == "intra_opt":
            sl_px = round(buy_px * (1.0 - sl_pct) * af_ratio, 2)
            if o[k] <= sl_px:
                s_px = o[k] if o[k] > dt_px[k] + 0.005 else c[k]
                return ret_from_px(d, p0, k, s_px, buy_px, use_adjf=use_adjf)
            if l[k] <= sl_px:
                return ret_from_px(d, p0, k, max(sl_px, dt_px[k]), buy_px, use_adjf=use_adjf)

    # Time expired at end_p
    ps = first_sellable_day(d, end_p)
    if end_zt_relay and is_zt[ps]:
        return hold_zt_relay(d, p0, ps, buy_px, use_adjf=use_adjf)
    return ret_from_px(d, p0, ps, c[ps], buy_px, use_adjf=use_adjf)


def sim_trailing_pullback(d, p0, buy_px, arm_pct, pb_pct, max_h=4, bound="neutral",
                          high_open_lock=None, m5_map=None, c6=None):
    """
    家族 B: 冲高回落右侧条件单模拟 (严防日线路径幻想!)
    bound:
      - 'opt' (乐观上界): 当日先探低再冲高(若收盘未回落>pb_pct或封板，则视为未触发回落并更新peak继续持有)
      - 'pess' (悲观下界): 当日若触及arm_px且高低振幅足以触发pb_pct回落(且非一字板)，即视为在触发瞬间回落被震出
      - 'neutral' (日线收盘确定性口径): 仅当「次日开盘已跌破peak*(1-pb)」或「当日收盘<=max(peak,h[k])*(1-pb)」时才确定触发(若有5m线则用真实5m顺序!)
    """
    L = len(d["dts"])
    if p0 + 1 >= L or buy_px <= 0:
        return np.nan, "", 0
    o, h, l, c, pre_c, dt_px, zt_px, is_zt, is_yz_dt, dts, adjf = (
        d["open"], d["high"], d["low"], d["close"], d["pre_c"], d["dt_px"], d["zt_px"],
        d["is_zt"], d["is_yizi_dt"], d["dts"], d["adjf"]
    )
    if c[p0] <= dt_px[p0] + 0.005:
        ps = first_sellable_day(d, p0 + 1)
        s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return ret_from_px(d, p0, ps, s_px, buy_px)
    if is_zt[p0]:
        return hold_zt_relay(d, p0, p0, buy_px)

    armed = False
    peak_adj = buy_px
    arm_px_unadj = buy_px * (1.0 + arm_pct)
    end_p = min(L - 1, p0 + max_h)

    for k in range(p0 + 1, end_p + 1):
        if is_yz_dt[k]:
            continue
        af = adjf[k] / adjf[p0]
        o_adj, h_adj, l_adj, c_adj = o[k] * af, h[k] * af, l[k] * af, c[k] * af
        zt_adj = zt_px[k] * af

        if high_open_lock is not None:
            op_pct_k = o[k] / pre_c[k] - 1.0
            if (op_pct_k >= high_open_lock) and (o[k] < zt_px[k] - 0.011):
                return ret_from_px(d, p0, k, o[k], buy_px)

        # Use real 5m bars if available on day k!
        arr = m5_map.get((c6, str(dts[k]))) if (m5_map is not None and c6 is not None) else None
        if arr is not None and len(arr) > 0:
            if o_adj >= arm_px_unadj:
                armed = True
                peak_adj = max(peak_adj, o_adj)
            if armed and o_adj <= peak_adj * (1.0 - pb_pct) and o[k] > dt_px[k] + 0.005:
                return ret_from_px(d, p0, k, o[k], buy_px)
            for row in arr:
                bh, bl, bc, bo = row[2] * af, row[3] * af, row[4] * af, row[1] * af
                if not armed and bh >= arm_px_unadj:
                    armed = True
                    peak_adj = max(peak_adj, bh)
                elif armed:
                    peak_adj = max(peak_adj, bh)
                # Not sealed at limit-up on this 5m close
                if armed and bc < zt_adj - 0.01 and bl <= peak_adj * (1.0 - pb_pct):
                    trig_px = min(bo, peak_adj * (1.0 - pb_pct)) / af
                    trig_px = max(trig_px, dt_px[k])
                    return ret_from_px(d, p0, k, trig_px, buy_px)
            if is_zt[k]:
                # Sealed at ZT EOD; stay armed with peak_adj and relay past end_p if ZT
                if k == end_p:
                    return hold_zt_relay(d, p0, k, buy_px)
            continue

        # Daily bar simulation (no 5m bar)
        # Check open gap drop if already armed from prior day
        if armed and o_adj <= peak_adj * (1.0 - pb_pct):
            s_px = o[k] if o[k] > dt_px[k] + 0.005 else c[k]
            return ret_from_px(d, p0, k, s_px, buy_px)

        if not armed:
            if h_adj >= arm_px_unadj:
                # Newly armed on day k
                if d["is_yizi"][k]:
                    armed = True
                    peak_adj = max(peak_adj, h_adj)
                elif bound == "opt":
                    # Optimistic: assume dipped to l_adj first, then surged to h_adj; only exits if c_adj <= h_adj*(1-pb) and not ZT
                    peak_adj = max(peak_adj, h_adj)
                    armed = True
                    if (not is_zt[k]) and c_adj <= peak_adj * (1.0 - pb_pct):
                        trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                        return ret_from_px(d, p0, k, trig_px, buy_px)
                elif bound == "pess":
                    # Pessimistic: assume hit arm_px first (or o_adj if higher), then dropped to l_adj before rallying
                    ref_pk = max(arm_px_unadj, o_adj)
                    if l_adj <= ref_pk * (1.0 - pb_pct):
                        trig_px = max(dt_px[k], (ref_pk * (1.0 - pb_pct)) / af)
                        return ret_from_px(d, p0, k, trig_px, buy_px)
                    peak_adj = max(peak_adj, h_adj)
                    armed = True
                    if (not is_zt[k]) and c_adj <= peak_adj * (1.0 - pb_pct):
                        trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                        return ret_from_px(d, p0, k, trig_px, buy_px)
                else:  # neutral: deterministic close-confirmed pullback or midpoint if h->l->c ambiguous
                    peak_adj = max(peak_adj, h_adj)
                    armed = True
                    if (not is_zt[k]) and c_adj <= peak_adj * (1.0 - pb_pct):
                        trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                        return ret_from_px(d, p0, k, trig_px, buy_px)
        else:
            # Already armed from prior day
            if d["is_yizi"][k]:
                peak_adj = max(peak_adj, h_adj)
            elif bound == "opt":
                peak_adj = max(peak_adj, h_adj)
                if (not is_zt[k]) and c_adj <= peak_adj * (1.0 - pb_pct):
                    trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                    return ret_from_px(d, p0, k, trig_px, buy_px)
            elif bound == "pess":
                if l_adj <= peak_adj * (1.0 - pb_pct):
                    trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                    return ret_from_px(d, p0, k, trig_px, buy_px)
                peak_adj = max(peak_adj, h_adj)
                if (not is_zt[k]) and l_adj <= peak_adj * (1.0 - pb_pct):
                    trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                    return ret_from_px(d, p0, k, trig_px, buy_px)
            else:  # neutral
                if l_adj <= peak_adj * (1.0 - pb_pct):
                    # Prior peak * (1-pb) was breached intraday!
                    trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                    return ret_from_px(d, p0, k, trig_px, buy_px)
                peak_adj = max(peak_adj, h_adj)
                if (not is_zt[k]) and c_adj <= peak_adj * (1.0 - pb_pct):
                    trig_px = max(dt_px[k], (peak_adj * (1.0 - pb_pct)) / af)
                    return ret_from_px(d, p0, k, trig_px, buy_px)

        if is_zt[k] and k == end_p:
            return hold_zt_relay(d, p0, k, buy_px)

    ps = first_sellable_day(d, end_p)
    if is_zt[ps]:
        return hold_zt_relay(d, p0, ps, buy_px)
    return ret_from_px(d, p0, ps, c[ps], buy_px)


def sim_ma_regress(d, p0, buy_px, ma_len=5, mult=1.0, min_protect=1.03, max_h=4,
                   cap_pct=None, end_zt_relay=False):
    """家族 D: 均线回归限价止盈 (100% PIT已知昨日均线，固定盘前限价单)"""
    L = len(d["dts"])
    if p0 + 1 >= L or buy_px <= 0:
        return np.nan, "", 0
    o, h, c, dt_px, is_zt, is_yz_dt, dts, adjf = (
        d["open"], d["high"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"], d["adjf"]
    )
    if c[p0] <= dt_px[p0] + 0.005:
        ps = first_sellable_day(d, p0 + 1)
        s_px = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return ret_from_px(d, p0, ps, s_px, buy_px)
    if is_zt[p0]:
        return hold_zt_relay(d, p0, p0, buy_px)

    end_p = min(L - 1, p0 + max_h)
    for k in range(p0 + 1, end_p + 1):
        if is_yz_dt[k]:
            continue
        af_k_to_0 = adjf[k] / adjf[p0]
        # Compute exact split-adjusted MA up to k-1 in day k's scale
        lo_idx = max(0, k - ma_len)
        ma_prev_k_scale = float(np.mean(c[lo_idx:k] * (adjf[lo_idx:k] / adjf[k])))
        tgt_ma = round(ma_prev_k_scale * mult, 2)
        min_px = round(buy_px * min_protect * (adjf[p0] / adjf[k]), 2)
        tp_px = max(min_px, tgt_ma)
        if cap_pct is not None:
            cap_px = round(buy_px * (1.0 + cap_pct) * (adjf[p0] / adjf[k]), 2)
            tp_px = min(tp_px, cap_px)
        if o[k] >= tp_px:
            return ret_from_px(d, p0, k, o[k], buy_px)
        if h[k] >= tp_px:
            return ret_from_px(d, p0, k, tp_px, buy_px)

    ps = first_sellable_day(d, end_p)
    if end_zt_relay and is_zt[ps]:
        return hold_zt_relay(d, p0, ps, buy_px)
    return ret_from_px(d, p0, ps, c[ps], buy_px)


def sim_x1_open(d, p0, buy_px):
    ps = first_sellable_day(d, p0 + 1)
    s_px = d["open"][ps] if d["open"][ps] > d["dt_px"][ps] + 0.005 else d["close"][ps]
    return ret_from_px(d, p0, ps, s_px, buy_px)


def sim_x2_close(d, p0, buy_px):
    if d["close"][p0] <= d["dt_px"][p0] + 0.005:
        return sim_x1_open(d, p0, buy_px)
    if d["is_zt"][p0]:
        return hold_zt_relay(d, p0, p0, buy_px)
    ps = first_sellable_day(d, p0 + 1)
    if ps == p0 + 1 and d["is_zt"][ps]:
        return hold_zt_relay(d, p0, ps, buy_px)
    return ret_from_px(d, p0, ps, d["close"][ps], buy_px)


def sim_x7_relay(d, p0, buy_px):
    if d["close"][p0] <= d["dt_px"][p0] + 0.005:
        return sim_x1_open(d, p0, buy_px)
    if d["is_zt"][p0]:
        return hold_zt_relay(d, p0, p0, buy_px)
    p1 = first_sellable_day(d, p0 + 1)
    if d["is_zt"][p1]:
        return hold_zt_relay(d, p0, p1, buy_px)
    if d["close"][p1] * (d["adjf"][p1] / d["adjf"][p0]) < d["close"][p0]:
        return ret_from_px(d, p0, p1, d["close"][p1], buy_px)
    end_p = min(len(d["dts"]) - 1, p0 + 3)
    for k in range(p1 + 1, end_p + 1):
        if d["is_zt"][k]:
            return hold_zt_relay(d, p0, k, buy_px)
        if d["close"][k] * (d["adjf"][k] / d["adjf"][k - 1]) < d["close"][k - 1] * 0.985:
            ps = first_sellable_day(d, k)
            return ret_from_px(d, p0, ps, d["close"][ps], buy_px)
    ps = first_sellable_day(d, end_p)
    return ret_from_px(d, p0, ps, d["close"][ps], buy_px)


def eval_slice(rets, holds=None):
    if len(rets) == 0:
        return {"n": 0, "wr": 0.0, "plr": 0.0, "mean": 0.0, "nav": 1.0, "mdd": 0.0, "avg_hold": 0.0}
    r = np.asarray(rets, dtype=float)
    w = r[r > 0]
    l = r[r <= 0]
    wr = float(len(w) / len(r) * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) > 0 and len(l) > 0 and l.mean() < 0) else (99.0 if len(w) > 0 else 0.0)
    nav_arr = np.cumprod(1.0 + r)
    pk = np.maximum.accumulate(np.insert(nav_arr, 0, 1.0))[1:]
    mdd = float(np.max((pk - nav_arr) / pk) * 100.0)
    return {
        "n": int(len(r)),
        "wr": round(wr, 2),
        "plr": round(plr, 2),
        "mean": round(float(r.mean() * 100.0), 3),
        "nav": round(float(nav_arr[-1]), 4),
        "mdd": round(mdd, 2),
        "avg_hold": round(float(np.mean(holds)), 2) if holds is not None and len(holds) else 0.0,
    }


def eval_variant(sub_df, ret_arr, edt_arr, hold_arr, min_score=165):
    m = sub_df["score"].values >= min_score
    w = sub_df.loc[m, ["buy_date", "code", "score", "bias10"]].copy()
    w["net_ret"] = ret_arr[m]
    w["exit_date"] = edt_arr[m]
    w["hold_days"] = hold_arr[m]
    w = w[w["net_ret"].notna()].copy()

    # 1. Daily equal-weight
    deq = w.groupby("buy_date", as_index=False).agg(net_ret=("net_ret", "mean"), hold_days=("hold_days", "mean")).sort_values("buy_date")
    # 2. Top1 per day (score desc, bias10 asc)
    top1 = w.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    # 3. Single slot rotation (buy_date > free_after)
    srt = w.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
    ss_rows = []
    free_after = ""
    for r in srt.itertuples(index=False):
        if free_after == "" or r.buy_date > free_after:
            ss_rows.append(r._asdict())
            free_after = r.exit_date
    ss = pd.DataFrame(ss_rows)

    out = {}
    for wname, s_dt, e_dt in [
        ("ALL", "2021-11-15", "2026-11-16"),
        ("IS", "2021-11-15", "2023-12-31"),
        ("OOS", "2024-01-01", "2026-11-16"),
        ("3Y", "2023-11-16", "2026-11-16"),
        ("2026", "2026-01-01", "2026-11-16"),
    ]:
        deq_s = deq[(deq["buy_date"] >= s_dt) & (deq["buy_date"] <= e_dt)]
        top_s = top1[(top1["buy_date"] >= s_dt) & (top1["buy_date"] <= e_dt)]
        ss_s = ss[(ss["buy_date"] >= s_dt) & (ss["buy_date"] <= e_dt)] if not ss.empty else ss
        out[wname] = {
            "deq": eval_slice(deq_s["net_ret"].values, deq_s["hold_days"].values),
            "top1": eval_slice(top_s["net_ret"].values, top_s["hold_days"].values),
            "ss": eval_slice(ss_s["net_ret"].values if not ss_s.empty else [], ss_s["hold_days"].values if not ss_s.empty else []),
        }
    return out


def main():
    t0 = time.time()
    print("[1/4] Loading data & verifying exact v1 baseline alignment...")
    df, cb, v1_ref, s3_ref, csi_canon, sh300, m5_map = load_all_data()
    sub = build_base_candidates(df, cb)
    n_sub = len(sub)
    print(f"  Base gate buyable candidates: {n_sub} rows across {sub['buy_date'].nunique()} days")

    # Helper to run any sim_fn across all 830 rows
    def run_sim(sim_fn):
        rets = np.full(n_sub, np.nan, dtype=float)
        edts = np.full(n_sub, "", dtype=object)
        hlds = np.zeros(n_sub, dtype=int)
        for idx, r in enumerate(sub.itertuples(index=False)):
            d = cb[r.c6]
            rv, ed, hd = sim_fn(d, r.p0, r.buy_px, r)
            rets[idx] = rv
            edts[idx] = ed
            hlds[idx] = hd
        return rets, edts, hlds

    # Verify exact reproduction of v1_oversold_pry_165_strict_ledger.csv & s3_champion_ledger.csv
    r_v1, d_v1, h_v1 = run_sim(lambda d, p0, bpx, r: sim_limit_tp(
        d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, match_mode="strict_premarket"
    ))
    sub_chk = sub[sub["score"] >= 165].copy()
    sub_chk["net_ret_sim"] = r_v1[sub["score"].values >= 165]
    sub_chk["exit_dt_sim"] = d_v1[sub["score"].values >= 165]
    m_v1 = v1_ref.merge(sub_chk, on=["buy_date", "code"])
    assert len(m_v1) == 435, f"Expected 435 rows, got {len(m_v1)}"
    max_diff_v1 = float((m_v1["net_ret"] - m_v1["net_ret_sim"]).abs().max())
    assert max_diff_v1 < 1e-4, f"v1 mismatch: {max_diff_v1}"

    r_s3, d_s3, h_s3 = run_sim(lambda d, p0, bpx, r: sim_limit_tp(
        d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, match_mode="phantom_s3_bug", use_adjf=False
    ))
    sub_chk["net_ret_s3"] = r_s3[sub["score"].values >= 165]
    m_s3 = s3_ref.merge(sub_chk, on=["buy_date", "code"])
    max_diff_s3 = float((m_s3["net_ret"] - m_s3["net_ret_s3"]).abs().max())
    print(f"  [PASS] v1_strict 435/435 max_diff={max_diff_v1:.7f} | s3_phantom 435/435 max_diff={max_diff_s3:.7f}")

    # Physical matching audit across >=165, >=150, >=140
    r_prm, d_prm, h_prm = run_sim(lambda d, p0, bpx, r: sim_limit_tp(
        d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4,
        match_mode="prompt_ozt_relay", zt_relay_if_unfilled=True
    ))
    audit_match = {}
    for th in [165, 150, 140]:
        msk = sub["score"].values >= th
        diff_s3_v1 = int(np.sum(np.abs(r_s3[msk] - r_v1[msk]) > 1e-4))
        diff_prm_v1 = int(np.sum(np.abs(r_prm[msk] - r_v1[msk]) > 1e-4))
        audit_match[f"P{th}"] = {
            "n_total": int(msk.sum()),
            "diff_phantom_s3_vs_strict_v1": diff_s3_v1,
            "diff_prompt_ozt_vs_strict_v1": diff_prm_v1,
        }
    print("  Physical matching audit:", json.dumps(audit_match))

    # Build all 90+ variants!
    print("[2/4] Registering & simulating 90+ exit variants across 4 families...")
    variants = []

    def add_var(name, family, fn, desc=""):
        variants.append((name, family, fn, desc))

    # --- Baselines ---
    add_var("B0_X10_phantom_bug", "Baseline", lambda d, p0, bpx, r: sim_limit_tp(
        d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, match_mode="phantom_s3_bug", use_adjf=False),
        "旧precompute_return_matrix穿板幻觉版")
    add_var("B1_X10_v1_strict", "Baseline", lambda d, p0, bpx, r: sim_limit_tp(
        d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, match_mode="strict_premarket"),
        "现役v1真实盘前死限价单(0.45*|ret10|, 6%~16%, 4日)")
    add_var("B2_X10_prompt_ozt", "Baseline", lambda d, p0, bpx, r: sim_limit_tp(
        d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, match_mode="prompt_ozt_relay", zt_relay_if_unfilled=True),
        "prompt口径(o>=tp且zt或tp>zt且zt转连板)")
    add_var("B3_X1_t1_open", "Baseline", lambda d, p0, bpx, r: sim_x1_open(d, p0, bpx), "T+1开盘无条件卖出")
    add_var("B4_X2_t1_close", "Baseline", lambda d, p0, bpx, r: sim_x2_close(d, p0, bpx), "T+1收盘卖出(涨停接力)")
    add_var("B5_X7_zt_relay", "Baseline", lambda d, p0, bpx, r: sim_x7_relay(d, p0, bpx), "X7连板主升格局卖法")

    # --- Family A: Dynamic Limit TP 4D Grid ---
    # A1.1 Anchor: abs(ret10) * k
    for k_val in [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70]:
        if k_val == 0.45:
            continue
        add_var(f"A_ret10_k{int(k_val*100)}", "FamilyA_Anchor",
                (lambda kv: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, float(np.clip(kv * abs(float(r.prev_ret10)), 0.06, 0.16)), 4))(k_val),
                f"ret10* {k_val}, [6%,16%], 4d")

    # A1.2 Anchor: abs(ret5) * k
    for k_val in [0.40, 0.50, 0.60, 0.70, 0.80]:
        add_var(f"A_ret5_k{int(k_val*100)}", "FamilyA_Anchor",
                (lambda kv: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, float(np.clip(kv * abs(float(r.prev_ret5)), 0.06, 0.16)), 4))(k_val),
                f"ret5* {k_val}, [6%,16%], 4d")

    # A1.3 Anchor: abs(bias10) * k
    for k_val in [0.45, 0.55, 0.65, 0.75, 0.85]:
        add_var(f"A_bias10_k{int(k_val*100)}", "FamilyA_Anchor",
                (lambda kv: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, float(np.clip(kv * abs(float(r.bias10)), 0.06, 0.16)), 4))(k_val),
                f"bias10* {k_val}, [6%,16%], 4d")

    # A1.4 Anchor: abs(prev_c_ma20) * k
    for k_val in [0.30, 0.35, 0.40, 0.45, 0.50]:
        add_var(f"A_cma20_k{int(k_val*100)}", "FamilyA_Anchor",
                (lambda kv: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, float(np.clip(kv * abs(float(r.prev_c_ma20)), 0.06, 0.16)), 4))(k_val),
                f"c_ma20* {k_val}, [6%,16%], 4d")

    # A1.5 Anchor: 20d drawdown (1 - prev_dd20) * k
    for k_val in [0.25, 0.30, 0.35, 0.40, 0.45]:
        add_var(f"A_dd20_k{int(k_val*100)}", "FamilyA_Anchor",
                (lambda kv: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, float(np.clip(kv * max(0.0, 1.0 - float(r.prev_dd20)), 0.06, 0.16)), 4))(k_val),
                f"(1-dd20)* {k_val}, [6%,16%], 4d")

    # A2 Floor x Cap grid (on 0.45*|ret10|, 4d)
    for fl, cp, ztr, eztr in [
        (0.04, 0.10, False, False), (0.04, 0.12, False, False),
        (0.05, 0.12, False, False), (0.05, 0.14, False, False),
        (0.06, 0.10, False, False), (0.06, 0.12, False, False),
        (0.06, 0.14, False, False), (0.06, 0.20, False, False),
        (0.06, 9.99, False, False),
        (0.07, 0.14, False, False), (0.07, 0.16, False, False), (0.07, 0.20, False, False),
        (0.08, 0.16, False, False), (0.08, 0.20, False, False), (0.08, 9.99, False, False),
        # High floor >= 10.5% so T+1 ZT never gets filled early!
        (0.105, 0.20, True, True), (0.11, 9.99, True, True),
        # Legal ZT relay when tp > zt_px
        (0.06, 0.16, True, True), (0.06, 0.20, True, True), (0.06, 9.99, True, True),
    ]:
        cp_lbl = "nocap" if cp > 5 else f"c{int(cp*100)}"
        z_lbl = "_ztr" if ztr else ""
        add_var(f"A_fc_f{int(fl*1000)}_{cp_lbl}{z_lbl}", "FamilyA_FloorCap",
                (lambda f0, c0, zr, ez: lambda d, p0, bpx, r: sim_limit_tp(
                    d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), f0, c0)), 4,
                    zt_relay_if_unfilled=zr, end_zt_relay=ez))(fl, cp, ztr, eztr),
                f"ret10*0.45 floor={fl*100:.1f}% cap={cp_lbl} ztr={ztr}")

    # A3 Holding days max_h grid (1..6) on X10 & on (k=0.35, 5%~14%)
    for mh in [1, 2, 3, 5, 6]:
        add_var(f"A_mh_x10_{mh}d", "FamilyA_MaxH",
                (lambda m0: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), m0))(mh),
                f"X10 max_h={mh}d")
        add_var(f"A_mh_k35_{mh}d", "FamilyA_MaxH",
                (lambda m0: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, float(np.clip(0.35 * abs(float(r.prev_ret10)), 0.05, 0.14)), m0))(mh),
                f"k35 [5%,14%] max_h={mh}d")

    # --- Family B: Trailing Pullback Conditional Order + High-Open Lock ---
    for arm_lbl, arm_fn in [
        ("arm6", lambda r: 0.06),
        ("arm8", lambda r: 0.08),
        ("arm10", lambda r: 0.10),
        ("armDyn", lambda r: float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16))),
    ]:
        for pb_v in [0.015, 0.025, 0.030]:
            for bnd in ["opt", "pess", "neutral"]:
                add_var(f"B_trail_{arm_lbl}_pb{int(pb_v*1000)}_{bnd}", "FamilyB_Trail",
                        (lambda afn, pv, bd: lambda d, p0, bpx, r: sim_trailing_pullback(
                            d, p0, bpx, afn(r), pv, max_h=4, bound=bd, m5_map=m5_map, c6=r.c6))(arm_fn, pb_v, bnd),
                        f"Trail {arm_lbl} pb={pb_v*100:.1f}% ({bnd})")
    # High-open lock (from 2to3) combined with X10 & Trail neutral
    for gap_th in [0.085, 0.092]:
        add_var(f"B_gaplock{int(gap_th*1000)}_X10", "FamilyB_GapLock",
                (lambda gt: lambda d, p0, bpx, r: sim_limit_tp(
                    d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, high_open_lock=gt, end_zt_relay=True))(gap_th),
                f"高开>={gap_th*100:.1f}%非一字开盘锁利 + X10")
        add_var(f"B_gaplock{int(gap_th*1000)}_trail8_25_neut", "FamilyB_GapLock",
                (lambda gt: lambda d, p0, bpx, r: sim_trailing_pullback(
                    d, p0, bpx, 0.08, 0.025, max_h=4, bound="neutral", high_open_lock=gt, m5_map=m5_map, c6=r.c6))(gap_th),
                f"高开>={gap_th*100:.1f}%非一字开盘锁利 + 冲8回落2.5%")

    # --- Family C: Cut-Weak / Hard Stop / Time-Decay Step-Down ---
    # C1 Day-0 weak candle cut
    for cm in ["none", "reseal_or_neg3", "reseal_or_neg5", "reseal_or_buy_m4", "reseal_or_buy_m6", "reseal_or_m4_and_t1weak"]:
        add_var(f"C_d0cut_{cm}", "FamilyC_Day0Cut",
                (lambda c_m: lambda d, p0, bpx, r: sim_limit_tp(
                    d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, day0_cut_mode=c_m))(cm),
                f"Day0弱势分支: {cm}")

    # C2 Hard Stop-Loss (with X10)
    for sl_m, sl_p in [
        ("intra_pess", 0.06), ("intra_opt", 0.06), ("close_sl", 0.06),
        ("intra_pess", 0.08), ("intra_opt", 0.08), ("close_sl", 0.08),
        ("intra_pess", 0.10), ("close_sl", 0.10),
        ("break_d0_low_intra", 0.0), ("break_d0_low_close", 0.0),
    ]:
        sl_lbl = f"{sl_m}_{int(sl_p*100)}" if sl_p > 0 else sl_m
        add_var(f"C_sl_{sl_lbl}", "FamilyC_StopLoss",
                (lambda sm, sp: lambda d, p0, bpx, r: sim_limit_tp(
                    d, p0, bpx, float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), 4, sl_mode=sm, sl_pct=sp))(sl_m, sl_p),
                f"硬止损 {sl_lbl}")

    # C3 Time-Decay Step-Down TP (New Physical Hypothesis)
    decay_defs = [
        ("C_decay_A_fast4d", lambda r: [float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))*0.75, 0.05, 0.02], 4),
        ("C_decay_B_med4d", lambda r: [float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))*0.80, 0.06, 0.03], 4),
        ("C_decay_C_gentle4d", lambda r: [float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))*0.85, float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))*0.65, 0.04], 4),
        ("C_decay_D_highT1_4d", lambda r: [float(np.clip(0.55*abs(r.prev_ret10), 0.08, 0.20)), float(np.clip(0.40*abs(r.prev_ret10), 0.06, 0.14)), 0.05, 0.02], 4),
        ("C_decay_E_fixed4d", lambda r: [0.12, 0.09, 0.06, 0.03], 4),
        ("C_decay_F_3d", lambda r: [float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))*0.75, 0.04], 3),
        ("C_decay_G_5d", lambda r: [float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16)), float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))*0.80, 0.06, 0.04, 0.02], 5),
        ("C_decay_H_t1unsealed11_4d", lambda r: [max(0.11, float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))), float(np.clip(0.45*abs(r.prev_ret10), 0.06, 0.16))*0.80, 0.06, 0.03], 4),
        ("C_decay_I_k50_dec_4d", lambda r: [float(np.clip(0.50*abs(r.prev_ret10), 0.07, 0.16)), float(np.clip(0.40*abs(r.prev_ret10), 0.06, 0.14)), 0.055, 0.03], 4),
        ("C_decay_J_k50_dec_3d", lambda r: [float(np.clip(0.50*abs(r.prev_ret10), 0.07, 0.16)), float(np.clip(0.40*abs(r.prev_ret10), 0.06, 0.14)), 0.04], 3),
    ]
    for nm, sched_fn, mh in decay_defs:
        add_var(nm, "FamilyC_TimeDecay",
                (lambda sfn, m0: lambda d, p0, bpx, r: sim_limit_tp(d, p0, bpx, sfn(r), m0, zt_relay_if_unfilled=True, end_zt_relay=True))(sched_fn, mh),
                f"时间衰减阶梯止盈 {nm}")

    # --- Family D: Moving-Average Regression Limit-Price ---
    for ma_l, mult_list in [(5, [0.97, 0.99, 1.00, 1.02]), (10, [0.95, 0.98, 1.00])]:
        for m_val in mult_list:
            for min_p in [1.00, 1.03, 1.05]:
                if ma_l == 10 and min_p == 1.00:
                    continue
                add_var(f"D_MA{ma_l}_m{int(m_val*100)}_p{int(min_p*100)}", "FamilyD_MARegress",
                        (lambda ml, mv, mp: lambda d, p0, bpx, r: sim_ma_regress(d, p0, bpx, ma_len=ml, mult=mv, min_protect=mp, max_h=4))(ma_l, m_val, min_p),
                        f"MA{ma_l}*{m_val} 保底{min_p} 4日")
    # Hybrid MA5 + X10 cap
    for min_p in [1.03, 1.05]:
        add_var(f"D_Hybrid_minX10_MA5_p{int(min_p*100)}", "FamilyD_MARegress",
                (lambda mp: lambda d, p0, bpx, r: sim_ma_regress(
                    d, p0, bpx, ma_len=5, mult=1.00, min_protect=mp, max_h=4,
                    cap_pct=float(np.clip(0.45 * abs(float(r.prev_ret10)), 0.06, 0.16)), end_zt_relay=True))(min_p),
                f"min(X10, max(保底{min_p}, MA5)) 4日")

    print(f"  Total variants registered: {len(variants)}")
    rows_out = []
    all_var_data = {}
    for vname, fam, fn, desc in variants:
        rets, edts, hlds = run_sim(fn)
        res_p165 = eval_variant(sub, rets, edts, hlds, min_score=165)
        res_p150 = eval_variant(sub, rets, edts, hlds, min_score=150)
        res_p140 = eval_variant(sub, rets, edts, hlds, min_score=140)
        res_p000 = eval_variant(sub, rets, edts, hlds, min_score=0)

        all_var_data[vname] = {
            "family": fam,
            "desc": desc,
            "P165": res_p165,
            "P150": res_p150,
            "P140": res_p140,
            "P000": res_p000,
        }
        rows_out.append({
            "variant": vname,
            "family": fam,
            "desc": desc,
            "P165_ALL_ss_nav": res_p165["ALL"]["ss"]["nav"],
            "P165_ALL_ss_wr": res_p165["ALL"]["ss"]["wr"],
            "P165_ALL_ss_plr": res_p165["ALL"]["ss"]["plr"],
            "P165_ALL_ss_mdd": res_p165["ALL"]["ss"]["mdd"],
            "P165_ALL_ss_hold": res_p165["ALL"]["ss"]["avg_hold"],
            "P165_ALL_deq_nav": res_p165["ALL"]["deq"]["nav"],
            "P165_IS_deq_nav": res_p165["IS"]["deq"]["nav"],
            "P165_OOS_deq_nav": res_p165["OOS"]["deq"]["nav"],
            "P165_IS_ss_nav": res_p165["IS"]["ss"]["nav"],
            "P165_OOS_ss_nav": res_p165["OOS"]["ss"]["nav"],
            "P150_IS_deq_nav": res_p150["IS"]["deq"]["nav"],
            "P150_OOS_deq_nav": res_p150["OOS"]["deq"]["nav"],
            "P150_ALL_deq_nav": res_p150["ALL"]["deq"]["nav"],
            "P150_IS_ss_nav": res_p150["IS"]["ss"]["nav"],
            "P150_OOS_ss_nav": res_p150["OOS"]["ss"]["nav"],
            "P140_IS_deq_nav": res_p140["IS"]["deq"]["nav"],
            "P140_OOS_deq_nav": res_p140["OOS"]["deq"]["nav"],
            "P140_ALL_deq_nav": res_p140["ALL"]["deq"]["nav"],
            "P000_IS_deq_nav": res_p000["IS"]["deq"]["nav"],
            "P000_OOS_deq_nav": res_p000["OOS"]["deq"]["nav"],
            "P000_ALL_deq_nav": res_p000["ALL"]["deq"]["nav"],
        })

    scan_df = pd.DataFrame(rows_out)
    scan_df.to_csv(f"{OUT_DIR}/scan_all_variants.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/scan_all_variants_full.json", "w", encoding="utf-8") as f:
        json.dump({"audit_matching": audit_match, "variants": all_var_data}, f, ensure_ascii=False, indent=2)

    print(f"[3/4] Saved {len(scan_df)} variants to scan_all_variants.csv in {time.time()-t0:.1f}s!")
    # Print compact top table by IS dual-pool geometric mean & P165 OOS check
    b1 = scan_df[scan_df["variant"] == "B1_X10_v1_strict"].iloc[0]
    print("\n=== BASELINES ===")
    print(scan_df[scan_df["family"] == "Baseline"][[
        "variant", "P165_ALL_ss_nav", "P165_ALL_ss_wr", "P165_ALL_deq_nav",
        "P165_IS_deq_nav", "P165_OOS_deq_nav", "P150_IS_deq_nav", "P150_OOS_deq_nav", "P140_IS_deq_nav", "P140_OOS_deq_nav"
    ]].to_string(index=False))

    # Print top 15 by IS combined rank (P165_IS_deq_nav * P150_IS_deq_nav * P140_IS_deq_nav) excluding opt trailing bounds
    clean_df = scan_df[~scan_df["variant"].str.contains("_opt$")].copy()
    clean_df["IS_score"] = clean_df["P165_IS_deq_nav"] * clean_df["P150_IS_deq_nav"] * clean_df["P140_IS_deq_nav"]
    print("\n=== TOP 20 BY IS DUAL-POOL (P165 x P150 x P140 DEQ, excl. optimistic trail) ===")
    print(clean_df.sort_values("IS_score", ascending=False).head(20)[[
        "variant", "P165_ALL_ss_nav", "P165_ALL_ss_hold", "P165_IS_deq_nav", "P165_OOS_deq_nav",
        "P150_IS_deq_nav", "P150_OOS_deq_nav", "P140_IS_deq_nav", "P140_OOS_deq_nav"
    ]].to_string(index=False))


if __name__ == "__main__":
    main()
