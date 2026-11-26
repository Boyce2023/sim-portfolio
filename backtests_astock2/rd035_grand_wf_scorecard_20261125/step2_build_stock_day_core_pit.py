#!/opt/homebrew/bin/python3.13
"""RD035 Wave 1-A Step 2: Build 5Y Full A-Share Stock-Day Core Features Library (strictly PIT).

Produces (under wave1_base/):
  - stock_day_core_features_pit.parquet (~7.02M rows, float32/int16/int8/cat, read RAM < 2 GB)
  - _audit_step2_stockday.json
Plus reusable PIT cache under _cache/:
  - lhb_stockday_5y_pit_{end_cutoff}.parquet
"""
import gc
import json
import os
import sqlite3
import sys
import time
import warnings
from collections import deque
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125")
OUT_DIR = os.path.join(BASE_DIR, "wave1_base")
CACHE_DIR = os.path.join(BASE_DIR, "_cache")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

sys.path.insert(0, os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd016_famous_youzi_seats_20261117"))
import step1_module1_seat_audit as rd16_m1
import step2_module2_leaderboard as rd16_m2
import step3a_is_factor_scan as rd16_m3


def _load_st_set():
    with open(os.path.join(ROOT, "sim-portfolio/data/st_universe.json")) as f:
        d = json.load(f)
    codes = d.get("codes", d) if isinstance(d, dict) else d
    return set(str(x)[-6:] for x in codes)


def _compute_stock_rolling_arrays(c6_arr, adj_close, amt, turn, ret1d, valid_prev):
    """Per-stock vectorized numpy causal calculations, returning unshifted arrays (shifted by 1 outside)."""
    n = len(c6_arr)
    # Stock slice boundaries
    brk = np.flatnonzero(c6_arr[1:] != c6_arr[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [n]))

    overhang = np.full(n, np.nan, dtype=np.float32)
    hr10 = np.full(n, np.nan, dtype=np.float32)
    hr30 = np.full(n, np.nan, dtype=np.float32)
    down_stk = np.zeros(n, dtype=np.int16)
    pos20 = np.full(n, np.nan, dtype=np.float32)
    pos60 = np.full(n, np.nan, dtype=np.float32)
    pos250 = np.full(n, np.nan, dtype=np.float32)
    dd20 = np.full(n, np.nan, dtype=np.float32)
    dd60 = np.full(n, np.nan, dtype=np.float32)
    amp20 = np.full(n, np.nan, dtype=np.float32)
    amp60 = np.full(n, np.nan, dtype=np.float32)
    bias10 = np.full(n, np.nan, dtype=np.float32)
    bias20 = np.full(n, np.nan, dtype=np.float32)
    ret5 = np.full(n, np.nan, dtype=np.float32)
    ret20 = np.full(n, np.nan, dtype=np.float32)
    ret60 = np.full(n, np.nan, dtype=np.float32)
    vr5 = np.full(n, np.nan, dtype=np.float32)
    t5_20 = np.full(n, np.nan, dtype=np.float32)

    for s, e in zip(starts, ends):
        m = e - s
        ac = adj_close[s:e]
        am = amt[s:e]
        tr = turn[s:e]
        r1 = ret1d[s:e]

        # Down streak
        ds = 0
        for i in range(m):
            if np.isfinite(r1[i]) and r1[i] < 0.0:
                ds += 1
            else:
                ds = 0
            down_stk[s + i] = ds

        if m > 5:
            ret5[s + 5 : e] = (ac[5:] / ac[:-5] - 1.0) * 100.0
        if m > 20:
            ret20[s + 20 : e] = (ac[20:] / ac[:-20] - 1.0) * 100.0
        if m > 60:
            ret60[s + 60 : e] = (ac[60:] / ac[:-60] - 1.0) * 100.0

        # Rolling via cumulative sums / pandas Series per stock? No: prefix sum for MA/turn, sliding window for min/max/overhang!
        csum_ac = np.concatenate(([0.0], np.cumsum(ac, dtype=np.float64)))
        csum_am = np.concatenate(([0.0], np.cumsum(np.nan_to_num(am, nan=0.0), dtype=np.float64)))
        csum_tr = np.concatenate(([0.0], np.cumsum(np.nan_to_num(tr, nan=0.0), dtype=np.float64)))

        if m >= 10:
            ma10 = (csum_ac[10:] - csum_ac[:-10]) / 10.0
            bias10[s + 9 : e] = (ac[9:] / ma10 - 1.0) * 100.0
        if m >= 20:
            ma20 = (csum_ac[20:] - csum_ac[:-20]) / 20.0
            bias20[s + 19 : e] = (ac[19:] / ma20 - 1.0) * 100.0

        # Vol ratio 5: amt[i] / mean(amt[i-5..i-1])
        if m >= 6:
            ma5_prev = (csum_am[5:-1] - csum_am[:-6]) / 5.0
            with np.errstate(divide="ignore", invalid="ignore"):
                vr5[s + 5 : e] = am[5:] / np.where(ma5_prev > 0, ma5_prev, np.nan)

        if m >= 20:
            tr5 = (csum_tr[20:] - csum_tr[15:-5]) / 5.0
            tr20 = (csum_tr[20:] - csum_tr[:-20]) / 20.0
            with np.errstate(divide="ignore", invalid="ignore"):
                t5_20[s + 19 : e] = tr5 / np.where(tr20 > 0, tr20, np.nan)

        # Rolling min/max/overhang/headroom
        # Use pandas Series rolling for 20/60 min-max (~0.5s total for 5500 stocks? Let's use numpy strided!)
        if m >= 5:
            # Causal 20d / 60d / 250d with min_periods=5/15/60
            # Fast numpy loops on small m (~1400) or strided full windows + prefix
            for win, min_p, out_p, out_d, out_a in [
                (20, 5, pos20, dd20, amp20),
                (60, 15, pos60, dd60, amp60),
            ]:
                if m >= win:
                    wview = np.lib.stride_tricks.sliding_window_view(ac, win)
                    wmin = wview.min(axis=1)
                    wmax = wview.max(axis=1)
                    rng = wmax - wmin
                    out_p[s + win - 1 : e] = np.where(rng > 0, (ac[win - 1 :] - wmin) / rng, 0.5)
                    out_d[s + win - 1 : e] = (ac[win - 1 :] / wmax - 1.0) * 100.0
                    out_a[s + win - 1 : e] = np.where(wmin > 0, rng / wmin * 100.0, np.nan)
                for i in range(min_p - 1, min(m, win - 1)):
                    sub = ac[: i + 1]
                    wmin, wmax = sub.min(), sub.max()
                    rng = wmax - wmin
                    out_p[s + i] = (ac[i] - wmin) / rng if rng > 0 else 0.5
                    out_d[s + i] = (ac[i] / wmax - 1.0) * 100.0
                    out_a[s + i] = rng / wmin * 100.0 if wmin > 0 else np.nan

            # 250d pos & overhang
            win250, min250 = 250, 60
            if m >= win250:
                wview = np.lib.stride_tricks.sliding_window_view(ac, win250)
                wmin = wview.min(axis=1)
                wmax = wview.max(axis=1)
                rng = wmax - wmin
                pos250[s + win250 - 1 : e] = np.where(rng > 0, (ac[win250 - 1 :] - wmin) / rng, 0.5)
                overhang[s + win250 - 1 : e] = (wview > ac[win250 - 1 :, None]).mean(axis=1)
            for i in range(min250 - 1, min(m, win250 - 1)):
                sub = ac[: i + 1]
                wmin, wmax = sub.min(), sub.max()
                rng = wmax - wmin
                pos250[s + i] = (ac[i] - wmin) / rng if rng > 0 else 0.5
                overhang[s + i] = float((sub > ac[i]).mean())

            # 10d100% headroom (min_{k=1..9} (2.0 * ac[t-k] / ac[t] - 1) * 100)
            if m >= 10:
                w10 = np.lib.stride_tricks.sliding_window_view(ac[:-1], 9)  # length m-9, corresponds to ac[9:]
                min_anchor10 = w10.min(axis=1)
                hr10[s + 9 : e] = (2.0 * min_anchor10 / ac[9:] - 1.0) * 100.0
            # 30d200% headroom (min_{k=1..29} (3.0 * ac[t-k] / ac[t] - 1) * 100)
            if m >= 30:
                w30 = np.lib.stride_tricks.sliding_window_view(ac[:-1], 29)
                min_anchor30 = w30.min(axis=1)
                hr30[s + 29 : e] = (3.0 * min_anchor30 / ac[29:] - 1.0) * 100.0

    return {
        "overhang": overhang,
        "hr10": hr10,
        "hr30": hr30,
        "down_stk": down_stk,
        "pos20": pos20,
        "pos60": pos60,
        "pos250": pos250,
        "dd20": dd20,
        "dd60": dd60,
        "amp20": amp20,
        "amp60": amp60,
        "bias10": bias10,
        "bias20": bias20,
        "ret5": ret5,
        "ret20": ret20,
        "ret60": ret60,
        "vr5": vr5,
        "t5_20": t5_20,
    }


def _build_lhb_5y_pit(bars_df: pd.DataFrame, cal_dates: np.ndarray, end_cutoff: str) -> pd.DataFrame:
    """Rebuild strictly causal 5Y LHB stock-day & rolling 250d Bayesian seat scores up to end_cutoff."""
    t0 = time.time()
    cl = rd16_m1.load_clean_lhb()
    cl["dt"] = pd.to_datetime(cl["TRADE_DATE"]).dt.strftime("%Y-%m-%d")
    cl["c6"] = cl["SECURITY_CODE"].astype(str).str.zfill(6)
    cl["dept_code"] = cl["OPERATEDEPT_CODE"].astype(str).str.strip()
    cl["dept_name"] = cl["OPERATEDEPT_NAME"].astype(str).str.strip()
    cl = cl[(cl["dt"] >= "2021-01-04") & (cl["dt"] <= end_cutoff)].copy()

    # Classify canonical seat groups (strictly fixed definitions from RD016)
    surf_codes = set(rd16_m2.SEAT_GROUPS["[组]开源西安西大街"]) | set(rd16_m2.SEAT_GROUPS["[组]开源西安太华路"]) | set(rd16_m2.SEAT_GROUPS["[组]上塘路(财通上塘)"])
    quant_codes = set(rd16_m2.SEAT_GROUPS["[组]量化打板(华鑫上海分)"]) | set(rd16_m2.SEAT_GROUPS["[组]量化基金(中金上海+华泰总部)"])
    good_yz_codes = (
        set(rd16_m3.IS_GOOD_CODES)
        | set(rd16_m2.SEAT_GROUPS["[组]陈小群(金马+黄河)"])
        | set(rd16_m2.SEAT_GROUPS["[组]六一中路/交易猿(福州六一+二纬)"])
        | set(rd16_m2.SEAT_GROUPS["[组]呼家楼/广渠门/北京总部"])
        | set(rd16_m2.SEAT_GROUPS["[组]消闲派(宜昌珍珠+沿江)"])
        | set(rd16_m2.SEAT_GROUPS["[组]章盟主核心席位"])
        | set(rd16_m2.SEAT_GROUPS["[组]作手新一(南京太平南)"])
        | set(rd16_m2.SEAT_GROUPS["[组]炒股养家(宛平+茅台+红宝石)"])
    )
    lhasa_codes = set(rd16_m2.SEAT_GROUPS["[组]西藏昌都+山南东财"])

    cl["is_inst"] = cl["dept_name"].str.contains("机构", na=False) | cl["dept_code"].isin(["0", "99999"])
    cl["is_lhasa"] = cl["dept_name"].str.contains("拉萨|山南|昌都", na=False) | cl["dept_code"].isin(lhasa_codes)
    cl["is_surf"] = cl["dept_code"].isin(surf_codes)
    cl["is_quant"] = cl["dept_code"].isin(quant_codes)
    cl["is_good_yz"] = cl["dept_code"].isin(good_yz_codes)

    # Deduplicate same (dt, c6, dept_code) across buy/sell appearances keeping max |NET| or sum
    cl_seat = (
        cl.sort_values(["dt", "c6", "dept_code"])
        .groupby(["dt", "c6", "dept_code"], as_index=False)
        .agg(
            BUY=("BUY", "max"),
            SELL=("SELL", "max"),
            NET=("NET", "mean"),
            is_inst=("is_inst", "max"),
            is_lhasa=("is_lhasa", "max"),
            is_surf=("is_surf", "max"),
            is_quant=("is_quant", "max"),
            is_good_yz=("is_good_yz", "max"),
        )
    )

    # Compute tradable T+1 open -> T+2 close / T+1 close return for LHB observations strictly <= end_cutoff
    sub_bars = bars_df[bars_df["dt"] >= "2021-01-04"][["c6", "dt", "open", "close", "adj_factor", "is_yizi_zt", "is_dt"]].copy()
    sub_bars = sub_bars.sort_values(["c6", "dt"]).reset_index(drop=True)
    dt_to_idx = {d: i for i, d in enumerate(cal_dates)}
    sub_bars["d_idx"] = sub_bars["dt"].map(dt_to_idx)
    sub_bars["adj_open"] = sub_bars["open"] * sub_bars["adj_factor"]
    sub_bars["adj_close"] = sub_bars["close"] * sub_bars["adj_factor"]

    # Map each (c6, dt) bar to next bar open (t+1), t+1 close, and first non-DT exit >= t+2
    # Build per-stock fast lookup dict for LHB trade settlement
    lhb_pairs = cl_seat[["dt", "c6"]].drop_duplicates()
    lhb_codes = set(lhb_pairs["c6"].unique())
    sub_bars = sub_bars[sub_bars["c6"].isin(lhb_codes)].copy()

    # For each stock in sub_bars, extract arrays
    stock_ev = {}
    for code_val, grp in sub_bars.groupby("c6", sort=False):
        stock_ev[code_val] = (
            grp["d_idx"].values,
            grp["adj_open"].values,
            grp["adj_close"].values,
            grp["is_yizi_zt"].values,
            grp["is_dt"].values,
        )

    # Evaluate settled excess return (ret_t2, ret_c) & settlement exit_idx for each unique (dt, c6)
    pair_list = []
    for dt_v, c6_v in lhb_pairs.itertuples(index=False, name=None):
        s_idx = dt_to_idx.get(dt_v, -1)
        tup = stock_ev.get(c6_v)
        if s_idx < 0 or tup is None:
            pair_list.append((dt_v, c6_v, -1, np.nan, np.nan))
            continue
        d_arr, ao_arr, ac_arr, yz_arr, dt_arr = tup
        pos = int(np.searchsorted(d_arr, s_idx))
        if pos >= len(d_arr) or d_arr[pos] != s_idx or pos + 2 >= len(d_arr):
            pair_list.append((dt_v, c6_v, -1, np.nan, np.nan))
            continue
        # Buy at next trading day pos+1 if sequential or next bar; check non-yizi buyable
        if yz_arr[pos + 1] or ao_arr[pos + 1] <= 0:
            pair_list.append((dt_v, c6_v, -1, np.nan, np.nan))
            continue
        # Exit close: first bar >= pos+2 not limit-down (up to pos+8)
        ex_pos = pos + 2
        while ex_pos < len(d_arr) - 1 and ex_pos < pos + 8 and dt_arr[ex_pos]:
            ex_pos += 1
        if dt_arr[ex_pos] or ac_arr[ex_pos] <= 0 or ac_arr[pos + 1] <= 0:
            pair_list.append((dt_v, c6_v, -1, np.nan, np.nan))
            continue
        ret_t2 = float(ac_arr[ex_pos] / ao_arr[pos + 1] - 1.0 - 0.003)
        ret_c = float(ac_arr[pos + 1] / ao_arr[pos + 1] - 1.0 - 0.003)
        ex_idx = int(d_arr[ex_pos])
        pair_list.append((dt_v, c6_v, ex_idx, ret_t2, ret_c))

    pair_df = pd.DataFrame(pair_list, columns=["dt", "c6", "exit_idx", "ret_t2", "ret_c"])
    cl_seat = cl_seat.merge(pair_df, on=["dt", "c6"], how="left")
    cl_seat["sig_idx"] = cl_seat["dt"].map(dt_to_idx).fillna(-1).astype(np.int32)

    # Chronological rolling 250-trading-day Bayesian shrinkage scoring strictly settling exit_idx <= cur_idx
    cl_seat = cl_seat.sort_values(["sig_idx", "c6", "dept_code"]).reset_index(drop=True)
    # Schedule settled updates keyed by exit_idx (only valid finite NET > 0 buys)
    buy_rows = cl_seat[(cl_seat["NET"] > 0) & (cl_seat["exit_idx"] >= 0) & cl_seat["ret_t2"].notna()].copy()
    pending_by_exit = {}
    for row in buy_rows[["exit_idx", "sig_idx", "dept_code", "ret_t2", "ret_c"]].itertuples(index=False, name=None):
        ex_i, sig_i, dc, rt2, rc = row
        pending_by_exit.setdefault(int(ex_i), []).append((sig_i, dc, float(rt2), float(rc)))

    seat_hist = {}  # dept_code -> deque of (sig_idx, rt2, rc)
    m_shrink = 15.0
    b_t2_arr = np.full(len(cl_seat), np.nan, dtype=np.float32)
    b_c_arr = np.full(len(cl_seat), np.nan, dtype=np.float32)

    # Group row indices by sig_idx
    sig_groups = cl_seat.groupby("sig_idx", sort=True).indices
    max_cal = len(cal_dates) - 1
    exit_ptr = 0
    for cur_idx in sorted(sig_groups.keys()):
        if cur_idx < 0 or cur_idx > max_cal:
            continue
        # Flush all settled trades whose exit_idx <= cur_idx (settled at cur_idx 15:00 before LHB ~17:30)
        while exit_ptr <= cur_idx:
            for sig_i, dc, rt2, rc in pending_by_exit.get(exit_ptr, ()):
                dq = seat_hist.setdefault(dc, deque())
                dq.append((sig_i, rt2, rc))
            exit_ptr += 1

        min_win = cur_idx - 250
        idxs = sig_groups[cur_idx]
        dcs = cl_seat["dept_code"].values[idxs]
        nets = cl_seat["NET"].values[idxs]
        is_non_lhasa = ~(cl_seat["is_lhasa"].values[idxs])
        is_non_inst = ~(cl_seat["is_inst"].values[idxs])

        for pos_i, dc, net_v, nl, ni in zip(idxs, dcs, nets, is_non_lhasa, is_non_inst):
            if net_v <= 0 or not nl or not ni:
                continue
            dq = seat_hist.get(dc)
            if not dq:
                continue
            while dq and dq[0][0] < min_win:
                dq.popleft()
            n_obs = len(dq)
            if n_obs >= 15:
                s_t2 = sum(x[1] for x in dq)
                s_c = sum(x[2] for x in dq)
                b_t2_arr[pos_i] = float(s_t2 / (n_obs + m_shrink) * 100.0)
                b_c_arr[pos_i] = float(s_c / (n_obs + m_shrink) * 100.0)

    cl_seat["b_t2"] = b_t2_arr
    cl_seat["b_c"] = b_c_arr

    # Aggregate to stock-day level (dt, c6)
    cl_seat["buy_pos"] = cl_seat["BUY"].clip(lower=0.0)
    cl_seat["lhasa_buy"] = np.where(cl_seat["is_lhasa"], cl_seat["buy_pos"], 0.0)
    cl_seat["inst_net"] = np.where(cl_seat["is_inst"], cl_seat["NET"], 0.0)
    cl_seat["good_buy"] = (cl_seat["is_good_yz"] & (cl_seat["NET"] > 0)).astype(np.int8)
    cl_seat["surf_buy"] = (cl_seat["is_surf"] & (cl_seat["NET"] > 0)).astype(np.int8)
    cl_seat["quant_buy"] = (cl_seat["is_quant"] & (cl_seat["NET"] > 0)).astype(np.int8)

    sd = cl_seat.groupby(["dt", "c6"], as_index=False).agg(
        lhb_inst_net_yi=("inst_net", lambda x: float(x.sum() / 1e8)),
        lhb_lhasa_buy=("lhasa_buy", "sum"),
        lhb_tot_buy=("buy_pos", "sum"),
        lhb_bayes_t2=("b_t2", "max"),
        lhb_bayes_c=("b_c", "max"),
        lhb_has_good_yz=("good_buy", "max"),
        lhb_has_surf_yz=("surf_buy", "max"),
        lhb_has_quant=("quant_buy", "max"),
        lhb_net_yi=("NET", lambda x: float(x.sum() / 1e8)),
        lhb_buy_yi=("buy_pos", lambda x: float(x.sum() / 1e8)),
    )
    sd["lhb_on"] = np.int8(1)
    sd["lhb_lhasa_share"] = np.where(sd["lhb_tot_buy"] > 0, sd["lhb_lhasa_buy"] / sd["lhb_tot_buy"], 0.0).astype(np.float32)
    sd["lhb_bayes_t2"] = sd["lhb_bayes_t2"].fillna(0.0).astype(np.float32)
    sd["lhb_bayes_c"] = sd["lhb_bayes_c"].fillna(0.0).astype(np.float32)
    sd = sd.drop(columns=["lhb_lhasa_buy", "lhb_tot_buy"])

    cache_p = os.path.join(CACHE_DIR, f"lhb_stockday_5y_pit_{end_cutoff.replace('-', '')}.parquet")
    sd.to_parquet(cache_p, index=False)
    print(f"[Step2] Rebuilt 5Y LHB PIT ({len(sd)} stock-days, {sd['dt'].min()}..{sd['dt'].max()}) in {time.time()-t0:.1f}s -> {cache_p}")
    return sd


def build_stock_day_core(end_cutoff: str = "2026-11-25", start_out: str = "2021-01-04"):
    t0 = time.time()
    print(f"[Step2] Building stock_day_core_features PIT up to {end_cutoff} ...")
    st_set = _load_st_set()

    # 1. Load bars >= 2019-10-01 <= end_cutoff
    cols_bar = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    df_a = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db/a_daily.parquet"), columns=cols_bar)
    df_d = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"), columns=cols_bar)
    bars = pd.concat([df_a, df_d], ignore_index=True)
    del df_a, df_d
    gc.collect()

    bars["dt"] = pd.to_datetime(bars["date"]).dt.strftime("%Y-%m-%d")
    bars = bars[(bars["dt"] >= "2019-10-01") & (bars["dt"] <= end_cutoff)].copy()
    bars["c6"] = bars["ticker"].astype(str).str[:6]
    suf = bars["ticker"].astype(str).str[-3:]
    valid_pref = bars["c6"].str.startswith(("00", "60", "30", "688", "689"))
    bars = bars[valid_pref & suf.isin([".SH", ".SZ"]) & (bars["close"] > 0) & (bars["adj_close"] > 0)].copy()
    bars = bars.sort_values(["c6", "dt"]).drop_duplicates(subset=["c6", "dt"], keep="first").reset_index(drop=True)

    cal_dates = np.array(sorted(bars.loc[bars["dt"] >= start_out, "dt"].unique()))
    full_cal = np.array(sorted(bars["dt"].unique()))
    cal_prev_map = {cal_dates[i]: (cal_dates[i - 1] if i > 0 else "2020-12-31") for i in range(len(cal_dates))}
    # Full prev map including 2020-12-31 for 2021-01-04
    full_prev_map = {full_cal[i]: (full_cal[i - 1] if i > 0 else "") for i in range(len(full_cal))}

    # Basic bar columns & causal shifts
    g = bars.groupby("c6", sort=False)
    prev_adj = g["adj_close"].shift(1)
    prev_close_raw = prev_adj * (bars["close"] / bars["adj_close"])
    prev_open_raw = g["open"].shift(1)
    prev_high_raw = g["high"].shift(1)
    prev_low_raw = g["low"].shift(1)
    prev_amt = g["amount"].shift(1)
    prev_oshare = g["oshare"].shift(1)
    prev_turn = g["turn"].shift(1)

    adj_fac = (bars["adj_close"] / bars["close"]).astype(np.float32)
    ret_1d = ((bars["adj_close"] / prev_adj - 1.0) * 100.0).astype(np.float32)
    open_pct = ((bars["open"] / prev_close_raw - 1.0) * 100.0).astype(np.float32)
    hl_rng = (bars["high"] - bars["low"]).values
    clv = np.where(hl_rng > 1e-6, (bars["close"].values - bars["low"].values) / hl_rng, 0.5).astype(np.float32)
    upper_shad = np.where(
        hl_rng > 1e-6,
        (bars["high"].values - np.maximum(bars["open"].values, bars["close"].values)) / hl_rng,
        0.0,
    ).astype(np.float32)

    is_20cm = bars["c6"].str.startswith(("30", "688", "689")).values
    is_st = bars["c6"].isin(st_set).values
    lim = np.where(is_20cm, 0.20, np.where(is_st & (bars["dt"].values < "2026-07-06"), 0.05, 0.10))
    zt_px = np.round(prev_close_raw.values * (1.0 + lim), 2)
    dt_px = np.round(prev_close_raw.values * (1.0 - lim), 2)
    vp = prev_close_raw.notna().values & (prev_close_raw.values > 0)
    non_st = ~is_st

    is_zt = (vp & non_st & (bars["close"].values >= zt_px - 1e-4) & (bars["close"].values >= bars["high"].values - 1e-4)).astype(np.int8)
    hit_zt = (vp & non_st & (bars["high"].values >= zt_px - 1e-4)).astype(np.int8)
    is_broken_zt = ((hit_zt == 1) & (is_zt == 0)).astype(np.int8)
    is_yizi_zt = ((is_zt == 1) & (bars["open"].values >= zt_px - 1e-4) & (bars["low"].values >= zt_px - 1e-4)).astype(np.int8)
    is_dt = (vp & non_st & (bars["close"].values <= dt_px + 1e-4) & (bars["close"].values <= bars["low"].values + 1e-4)).astype(np.int8)
    is_yizi_dt = ((is_dt == 1) & (bars["open"].values <= dt_px + 1e-4) & (bars["high"].values <= dt_px + 1e-4)).astype(np.int8)

    # Consecutive ZT streak
    c6_vals = bars["c6"].values
    streak = np.zeros(len(bars), dtype=np.int16)
    cur_s = 0
    prev_c = ""
    for idx in range(len(bars)):
        ck = c6_vals[idx]
        if ck != prev_c:
            cur_s = 0
            prev_c = ck
        cur_s = cur_s + 1 if is_zt[idx] == 1 else 0
        streak[idx] = cur_s

    bars["adj_factor"] = adj_fac
    bars["ret_1d"] = ret_1d
    bars["open_pct"] = open_pct
    bars["clv"] = clv
    bars["upper_shad"] = upper_shad
    bars["is_zt"] = is_zt
    bars["hit_zt"] = hit_zt
    bars["is_broken_zt"] = is_broken_zt
    bars["is_yizi_zt"] = is_yizi_zt
    bars["is_dt"] = is_dt
    bars["is_yizi_dt"] = is_yizi_dt
    bars["streak"] = np.clip(streak, 0, 127).astype(np.int8)
    bars["is_st_pit"] = is_st.astype(np.int8)
    bars["is_20cm"] = is_20cm.astype(np.int8)
    bars["prev_close_raw"] = prev_close_raw.astype(np.float32)

    # Rolling per-stock causal arrays (then shift by 1 within stock!)
    roll = _compute_stock_rolling_arrays(
        c6_vals,
        bars["adj_close"].values.astype(np.float64),
        bars["amount"].values.astype(np.float64),
        bars["turn"].values.astype(np.float64),
        bars["ret_1d"].values.astype(np.float64),
        vp,
    )
    bars["_tmp_overhang"] = roll["overhang"]
    bars["_tmp_hr10"] = roll["hr10"]
    bars["_tmp_hr30"] = roll["hr30"]
    bars["_tmp_down_stk"] = roll["down_stk"]
    bars["_tmp_pos20"] = roll["pos20"]
    bars["_tmp_pos60"] = roll["pos60"]
    bars["_tmp_pos250"] = roll["pos250"]
    bars["_tmp_dd20"] = roll["dd20"]
    bars["_tmp_amp20"] = roll["amp20"]
    bars["_tmp_amp60"] = roll["amp60"]
    bars["_tmp_bias10"] = roll["bias10"]
    bars["_tmp_bias20"] = roll["bias20"]
    bars["_tmp_ret5"] = roll["ret5"]
    bars["_tmp_ret20"] = roll["ret20"]
    bars["_tmp_vr5"] = roll["vr5"]
    bars["_tmp_t5_20"] = roll["t5_20"]
    del roll
    gc.collect()

    g2 = bars.groupby("c6", sort=False)
    bars["mcap_yi_t1"] = (prev_close_raw * prev_oshare / 1e8).astype(np.float32)
    bars["amount_yi_t1"] = (prev_amt / 1e8).astype(np.float32)
    bars["ret_1d_t1"] = g2["ret_1d"].shift(1).astype(np.float32)
    bars["d1_open_pct"] = g2["open_pct"].shift(1).astype(np.float32)
    bars["prev_clv"] = g2["clv"].shift(1).astype(np.float32)
    bars["prev_streak"] = g2["streak"].shift(1).fillna(0).clip(0, 127).astype(np.int8)
    bars["prev_is_broken_zt"] = g2["is_broken_zt"].shift(1).fillna(0).astype(np.int8)
    bars["prev_is_yizi_zt"] = g2["is_yizi_zt"].shift(1).fillna(0).astype(np.int8)

    shift_map = {
        "_tmp_overhang": ("overhang_pct_t1", np.float32),
        "_tmp_hr10": ("hr10d_space_t1", np.float32),
        "_tmp_hr30": ("hr30d_space_t1", np.float32),
        "_tmp_down_stk": ("down_streak_t1", np.int8),
        "_tmp_pos20": ("pos_20d_t1", np.float32),
        "_tmp_pos60": ("pos_60d_t1", np.float32),
        "_tmp_pos250": ("pos_250d_t1", np.float32),
        "_tmp_dd20": ("dd_20d_t1", np.float32),
        "_tmp_amp20": ("amp_20d_t1", np.float32),
        "_tmp_bias10": ("bias10_t1", np.float32),
        "_tmp_bias20": ("bias20_t1", np.float32),
        "_tmp_ret5": ("ret_5d_t1", np.float32),
        "_tmp_ret20": ("ret_20d_t1", np.float32),
        "_tmp_vr5": ("vol_ratio5_t1", np.float32),
        "_tmp_t5_20": ("turn_5_20_t1", np.float32),
    }
    for src_c, (dst_c, dt_t) in shift_map.items():
        s_val = g2[src_c].shift(1)
        if dt_t == np.int8:
            s_val = s_val.fillna(0).clip(-127, 127)
        bars[dst_c] = s_val.astype(dt_t)

    amp60_t1 = g2["_tmp_amp60"].shift(1)
    bars["amp_comp_20v60_t1"] = np.where(amp60_t1 > 0, bars["amp_20d_t1"] / amp60_t1, np.nan).astype(np.float32)

    # Drop temporary & warmup < 2021-01-04 (after computing LHB! Wait: LHB uses >= 2021-01-04)
    bars["amount_yi"] = (bars["amount"] / 1e8).astype(np.float32)
    bars["turn_pct"] = (bars["turn"] * 100.0).astype(np.float32)
    bars["open"] = bars["open"].astype(np.float32)
    bars["high"] = bars["high"].astype(np.float32)
    bars["low"] = bars["low"].astype(np.float32)
    bars["close"] = bars["close"].astype(np.float32)

    drop_tmp = [c for c in bars.columns if c.startswith("_tmp_")] + ["date", "ticker", "adj_close", "volume", "amount", "oshare", "turn", "upper_shad"]
    bars = bars.drop(columns=drop_tmp)
    bars = bars[bars["dt"] >= start_out].reset_index(drop=True)
    gc.collect()

    # 2. Rebuild 5Y LHB PIT & attach on T-1 (prev_dt)
    lhb_sd = _build_lhb_5y_pit(bars, cal_dates, end_cutoff)
    # Map lhb_sd dt -> next trading day on cal_dates? Actually use prev_dt join: bars["prev_dt"] = bars["dt"].map(full_prev_map)
    bars["prev_dt"] = bars["dt"].map(full_prev_map)
    lhb_join = lhb_sd.rename(
        columns={
            "dt": "prev_dt",
            "lhb_on": "lhb_on_t1",
            "lhb_bayes_t2": "lhb_bayes_t2_t1",
            "lhb_bayes_c": "lhb_bayes_c_t1",
            "lhb_inst_net_yi": "lhb_inst_net_yi_t1",
            "lhb_lhasa_share": "lhb_lhasa_share_t1",
            "lhb_has_good_yz": "lhb_has_good_yz_t1",
            "lhb_has_surf_yz": "lhb_has_surf_yz_t1",
            "lhb_has_quant": "lhb_has_quant_t1",
        }
    )
    bars = bars.merge(
        lhb_join[
            [
                "prev_dt",
                "c6",
                "lhb_on_t1",
                "lhb_bayes_t2_t1",
                "lhb_inst_net_yi_t1",
                "lhb_lhasa_share_t1",
                "lhb_has_good_yz_t1",
                "lhb_has_surf_yz_t1",
                "lhb_has_quant_t1",
            ]
        ],
        on=["prev_dt", "c6"],
        how="left",
    ).sort_values(["c6", "dt"]).reset_index(drop=True)
    for c in ["lhb_on_t1", "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1"]:
        bars[c] = bars[c].fillna(0).astype(np.int8)
    for c in ["lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1"]:
        bars[c] = bars[c].fillna(0.0).astype(np.float32)

    # 5-day trailing LHB appearance count strictly up to prev_dt (using full_cal mapping)
    lhb_dt_idx = {d: i for i, d in enumerate(full_cal)}
    lhb_sd["d_idx"] = lhb_sd["dt"].map(lhb_dt_idx).fillna(-1).astype(np.int32)
    lhb_pos = lhb_sd[lhb_sd["d_idx"] >= 0].sort_values(["c6", "d_idx"])
    lhb_c_map = {}
    for c6_v, grp in lhb_pos.groupby("c6", sort=False):
        lhb_c_map[c6_v] = grp["d_idx"].values
    cnt5_arr = np.zeros(len(bars), dtype=np.int8)
    pdt_idx_arr = bars["prev_dt"].map(lhb_dt_idx).fillna(-1).values.astype(np.int32)
    b_c6 = bars["c6"].values
    brk_b = np.flatnonzero(b_c6[1:] != b_c6[:-1]) + 1
    for s, e in zip(np.concatenate(([0], brk_b)), np.concatenate((brk_b, [len(bars)]))):
        arr_l = lhb_c_map.get(b_c6[s])
        if arr_l is None:
            continue
        p_sub = pdt_idx_arr[s:e]
        r_pos = np.searchsorted(arr_l, p_sub, side="right")
        l_pos = np.searchsorted(arr_l, p_sub - 4, side="left")
        cnt5_arr[s:e] = np.clip(r_pos - l_pos, 0, 127).astype(np.int8)
    bars["lhb_cnt_5d_t1"] = cnt5_arr
    del lhb_sd, lhb_join, lhb_pos, lhb_c_map
    gc.collect()

    # 3. PIT Top-10 Freeholders Lock (notice_date <= prev_dt & <= end_cutoff) -> free_mcap_yi_t1 & real_turn_pct_t1
    with open(os.path.join(ROOT, "sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json")) as f:
        t10_dict = json.load(f)
    lock_arr = np.full(len(bars), np.nan, dtype=np.float32)
    pdt_arr = bars["prev_dt"].values
    for s, e in zip(np.concatenate(([0], brk_b)), np.concatenate((brk_b, [len(bars)]))):
        recs = t10_dict.get(b_c6[s])
        if not recs:
            continue
        # recs: [[notice_date, end_date, free_lock_pct, ...], ...] sorted by notice_date
        valid_r = [(str(r[0])[:10], float(r[2])) for r in recs if r[2] is not None and str(r[0])[:10] <= end_cutoff]
        if not valid_r:
            continue
        valid_r.sort(key=lambda x: x[0])
        nd_arr = np.array([x[0] for x in valid_r])
        lv_arr = np.array([x[1] for x in valid_r], dtype=np.float32)
        pos = np.searchsorted(nd_arr, pdt_arr[s:e], side="right") - 1
        ok = pos >= 0
        lock_arr[s:e][ok] = lv_arr[pos[ok]]
    bars["lock_top10_pct_pre"] = lock_arr
    lock_eff = np.where(np.isfinite(lock_arr), np.clip(lock_arr, 0.0, 99.0), 0.0)
    bars["free_mcap_yi_t1"] = (bars["mcap_yi_t1"].values * (1.0 - lock_eff / 100.0)).astype(np.float32)
    bars["real_turn_pct_t1"] = np.clip(
        np.where(bars["free_mcap_yi_t1"].values > 0, bars["amount_yi_t1"].values / bars["free_mcap_yi_t1"].values * 100.0, np.nan),
        0.0,
        100.0,
    ).astype(np.float32)
    del t10_dict, lock_arr
    gc.collect()

    # 4. ZT Micro Tape T-1 (zt_micro_tape_5y_pit.db)
    con_zt = sqlite3.connect(f"file:{os.path.join(ROOT, 'sim-portfolio/data/zt_micro_tape_5y_pit.db')}?mode=ro", uri=True)
    zt_df = pd.read_sql_query(
        "SELECT trade_date AS prev_dt, sec_code AS c6, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date >= '2020-12-30' AND trade_date <= ?",
        con_zt,
        params=(end_cutoff,),
    )
    con_zt.close()
    zt_df["c6"] = zt_df["c6"].astype(str).str.zfill(6)
    zt_df = zt_df.drop_duplicates(subset=["prev_dt", "c6"], keep="first")
    # Convert HH:MM:SS -> int16 hhmm (e.g. 925, 1353)
    fst = zt_df["first_seal_time"].astype(str).str.replace(":", "", regex=False).str[:4]
    zt_df["d1_first_seal_hhmm_t1"] = pd.to_numeric(fst, errors="coerce").fillna(-1).astype(np.int16)
    zt_df["d1_open_board_cnt_t1"] = pd.to_numeric(zt_df["open_board_count"], errors="coerce").fillna(-1).clip(-127, 127).astype(np.int8)
    zt_df["_seal_yi"] = (pd.to_numeric(zt_df["seal_amount"], errors="coerce").fillna(0.0) / 1e8).astype(np.float32)
    bars = bars.merge(zt_df[["prev_dt", "c6", "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "_seal_yi"]], on=["prev_dt", "c6"], how="left")
    bars["d1_first_seal_hhmm_t1"] = bars["d1_first_seal_hhmm_t1"].fillna(-1).astype(np.int16)
    bars["d1_open_board_cnt_t1"] = bars["d1_open_board_cnt_t1"].fillna(-1).astype(np.int8)
    bars["d1_seal_ratio_t1"] = np.where(
        (bars["_seal_yi"].notna()) & (bars["amount_yi_t1"] > 0),
        bars["_seal_yi"] / bars["amount_yi_t1"],
        0.0,
    ).astype(np.float32)
    bars = bars.drop(columns=["_seal_yi"])
    del zt_df
    gc.collect()

    # Old-Hot 6-Dim 14 Key Features (strictly <= end_cutoff)
    oh_cols = [
        "c6",
        "dt",
        "list_age",
        "waves_3y_g15_t1",
        "zt_cnt_1y_t1",
        "max_streak_3y",
        "cum_turnover_1y",
        "trap_waves_3y",
        "dd_from_3y_high",
        "cool_days_since_last_zt",
        "cool_days_since_last_2b",
        "comm_posts_1y_pct",
        "xq_posts_1y_pct",
        "kpl_unique_plates_3y",
        "kpl_top_plate_share",
    ]
    oh = pd.read_parquet(
        os.path.join(ROOT, "sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125/old_hot_6dim_stock_day_pit.parquet"),
        columns=oh_cols,
        filters=[("dt", "<=", end_cutoff)],
    )
    bars = bars.merge(oh, on=["c6", "dt"], how="left").sort_values(["c6", "dt"]).reset_index(drop=True)
    for c in ["list_age", "zt_cnt_1y_t1", "cool_days_since_last_zt", "cool_days_since_last_2b", "kpl_unique_plates_3y"]:
        bars[c] = bars[c].fillna(-1).astype(np.int16)
    for c in ["waves_3y_g15_t1", "max_streak_3y", "trap_waves_3y"]:
        bars[c] = bars[c].fillna(-1).clip(-127, 127).astype(np.int8)
    for c in ["cum_turnover_1y", "dd_from_3y_high", "comm_posts_1y_pct", "xq_posts_1y_pct", "kpl_top_plate_share"]:
        bars[c] = bars[c].astype(np.float32)
    del oh
    gc.collect()

    # Re-anchor cached slice boundaries after merges
    b_c6 = bars["c6"].values
    b_dt = bars["dt"].values
    brk_b = np.flatnonzero(b_c6[1:] != b_c6[:-1]) + 1
    pdt_idx_arr = bars["prev_dt"].map(lhb_dt_idx).fillna(-1).values.astype(np.int32)

    # 6. Causal KPL Theme T-1 (from kpl_plates_2018_2026_merged.jsonl <= end_cutoff)
    zt_lookup = bars[bars["is_zt"] == 1][["dt", "c6", "streak"]].copy()
    zt_set_by_dt = {}
    for d_v, grp in zt_lookup.groupby("dt", sort=False):
        zt_set_by_dt[d_v] = dict(zip(grp["c6"].values, grp["streak"].values))
    del zt_lookup

    kpl_rows = []
    plate_streak = {}
    prev_day_plates = set()
    with open(os.path.join(ROOT, "sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl")) as f:
        for line in f:
            obj = json.loads(line)
            kdt = str(obj["date"])[:10]
            if kdt < "2020-11-01" or kdt > end_cutoff:
                continue
            zt_map = zt_set_by_dt.get(kdt, {})
            plates = obj.get("plates", [])
            # Rank plates by ZT stock count on kdt (falling back to stock count)
            p_scored = []
            cur_plates = set()
            for pl in plates:
                pname = str(pl.get("plate", ""))
                stks = [str(s[0])[-6:] for s in pl.get("stocks", []) if s]
                if not stks:
                    continue
                cur_plates.add(pname)
                n_zt = sum(1 for c in stks if c in zt_map)
                p_scored.append((pname, stks, n_zt, len(stks)))
            p_scored.sort(key=lambda x: (-x[2], -x[3], x[0]))
            new_streak = {}
            for rk, (pname, stks, n_zt, n_tot) in enumerate(p_scored, start=1):
                st_len = (plate_streak.get(pname, 0) + 1) if pname in prev_day_plates else 1
                new_streak[pname] = st_len
                # Record best plate per stock
                for c in stks:
                    kpl_rows.append((kdt, c, rk, n_zt, st_len))
            plate_streak = new_streak
            prev_day_plates = cur_plates

    kpl_df = pd.DataFrame(kpl_rows, columns=["prev_dt", "c6", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1"])
    kpl_df = kpl_df.sort_values(["prev_dt", "c6", "kpl_rank_t1"]).drop_duplicates(subset=["prev_dt", "c6"], keep="first")
    # 3-day ZT sum & 30d in-KPL days per stock
    kpl_cal_idx = {d: i for i, d in enumerate(full_cal)}
    kpl_df["d_idx"] = kpl_df["prev_dt"].map(kpl_cal_idx).fillna(-1).astype(np.int32)
    kpl_df_v = kpl_df[kpl_df["d_idx"] >= 0].sort_values(["c6", "d_idx"]).reset_index(drop=True)
    kpl_c_idx = {}
    for c6_v, grp in kpl_df_v.groupby("c6", sort=False):
        kpl_c_idx[c6_v] = (grp["d_idx"].values, grp["kpl_zt1_t1"].values)
    kpl_zt3 = np.zeros(len(bars), dtype=np.int16)
    kpl_d30 = np.zeros(len(bars), dtype=np.int8)
    for s, e in zip(np.concatenate(([0], brk_b)), np.concatenate((brk_b, [len(bars)]))):
        tup = kpl_c_idx.get(b_c6[s])
        if tup is None:
            continue
        kd_arr, kzt_arr = tup
        p_sub = pdt_idx_arr[s:e]
        r_pos = np.searchsorted(kd_arr, p_sub, side="right")
        l_3 = np.searchsorted(kd_arr, p_sub - 2, side="left")
        l_30 = np.searchsorted(kd_arr, p_sub - 29, side="left")
        kpl_d30[s:e] = np.clip(r_pos - l_30, 0, 127).astype(np.int8)
        csum_k = np.concatenate(([0], np.cumsum(kzt_arr, dtype=np.int32)))
        kpl_zt3[s:e] = (csum_k[r_pos] - csum_k[l_3]).astype(np.int16)

    kpl_df["kpl_in_t1"] = np.int8(1)
    bars["kpl_zt3_t1"] = kpl_zt3
    bars["kpl_days_30d_t1"] = kpl_d30
    bars = bars.merge(kpl_df[["prev_dt", "c6", "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1"]], on=["prev_dt", "c6"], how="left").sort_values(["c6", "dt"]).reset_index(drop=True)
    bars["kpl_in_t1"] = bars["kpl_in_t1"].fillna(0).astype(np.int8)
    bars["kpl_rank_t1"] = bars["kpl_rank_t1"].fillna(0).astype(np.int16)
    bars["kpl_zt1_t1"] = bars["kpl_zt1_t1"].fillna(0).astype(np.int16)
    bars["kpl_streak_t1"] = bars["kpl_streak_t1"].fillna(0).clip(0, 127).astype(np.int8)
    del kpl_rows, kpl_df, kpl_df_v, kpl_c_idx, zt_set_by_dt
    gc.collect()

    b_c6 = bars["c6"].values
    b_dt = bars["dt"].values
    brk_b = np.flatnonzero(b_c6[1:] != b_c6[:-1]) + 1

    # 7. Causal CSRC Industry Strength T-1 (start_date <= end_cutoff)
    ind_raw = pd.read_csv(os.path.join(ROOT, "sim-portfolio/data/csrc_industry_pit_clean.csv"))
    ind_raw["c6"] = ind_raw["code"].astype(str).str[-6:]
    ind_raw["start_dt"] = ind_raw["start_date"].astype(str).str[:10]
    ind_raw = ind_raw[ind_raw["start_dt"] <= end_cutoff].copy()
    ind_raw["industry"] = ind_raw["industry"].fillna("UNKNOWN").astype(str)
    all_inds = sorted(set(ind_raw["industry"].unique()) | {"UNKNOWN"})
    ind_to_id = {name: i for i, name in enumerate(all_inds)}
    ind_raw["csrc_ind_id"] = ind_raw["industry"].map(ind_to_id).astype(np.int16)
    ind_raw = ind_raw.sort_values(["c6", "start_dt"]).drop_duplicates(["c6", "start_dt"], keep="last")

    ind_map = {c: (g["start_dt"].values, g["csrc_ind_id"].values) for c, g in ind_raw.groupby("c6", sort=False)}
    ind_id_arr = np.full(len(bars), ind_to_id["UNKNOWN"], dtype=np.int16)
    for s, e in zip(np.concatenate(([0], brk_b)), np.concatenate((brk_b, [len(bars)]))):
        tup = ind_map.get(b_c6[s])
        if tup is None:
            continue
        sd_arr, id_arr = tup
        pos = np.searchsorted(sd_arr, b_dt[s:e], side="right") - 1
        ok = pos >= 0
        ind_id_arr[s:e][ok] = id_arr[pos[ok]]
    bars["csrc_ind_id"] = ind_id_arr

    mkt_day = bars.groupby("dt", as_index=False).agg(mkt_ret=("ret_1d", "mean"), mkt_zt=("is_zt", "sum"), mkt_amt=("amount_yi", "sum"))
    ind_day = bars.groupby(["dt", "csrc_ind_id"], as_index=False).agg(ind_ret=("ret_1d", "mean"), ind_zt=("is_zt", "sum"), ind_amt=("amount_yi", "sum"))
    ind_day = ind_day.merge(mkt_day, on="dt", how="left").sort_values(["csrc_ind_id", "dt"]).reset_index(drop=True)
    ind_day["ex_1d"] = ind_day["ind_ret"] - ind_day["mkt_ret"]
    ind_day["amt_share"] = ind_day["ind_amt"] / ind_day["mkt_amt"].replace(0, np.nan)

    gi = ind_day.groupby("csrc_ind_id", sort=False)
    ind_day["csrc_ind_ex5_t1"] = gi["ex_1d"].transform(lambda s: s.rolling(5, min_periods=2).sum().shift(1)).astype(np.float32)
    ind_day["csrc_ind_ex20_t1"] = gi["ex_1d"].transform(lambda s: s.rolling(20, min_periods=5).sum().shift(1)).astype(np.float32)
    ind_day["csrc_ind_zt_share5_t1"] = (
        gi["ind_zt"].transform(lambda s: s.rolling(5, min_periods=1).sum().shift(1))
        / gi["mkt_zt"].transform(lambda s: s.rolling(5, min_periods=1).sum().shift(1)).replace(0, np.nan)
    ).astype(np.float32)
    ind_day["csrc_ind_amt_pct250_t1"] = gi["amt_share"].transform(
        lambda s: s.rolling(250, min_periods=30).apply(lambda w: float(np.mean(w <= w[-1])), raw=True).shift(1)
    ).astype(np.float32)
    ind_day["csrc_ind_rank20_t1"] = ind_day.groupby("dt")["csrc_ind_ex20_t1"].rank(ascending=False, method="min").fillna(99).clip(1, 127).astype(np.int8)

    bars = bars.merge(
        ind_day[["dt", "csrc_ind_id", "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1", "csrc_ind_amt_pct250_t1"]],
        on=["dt", "csrc_ind_id"],
        how="left",
    ).sort_values(["c6", "dt"]).reset_index(drop=True)
    del ind_raw, ind_map, mkt_day, ind_day
    gc.collect()

    b_c6 = bars["c6"].values
    brk_b = np.flatnonzero(b_c6[1:] != b_c6[:-1]) + 1

    # 8. CNINFO Reg/Tox/Abn & IR Q&A (pre-open < T 09:25:00)
    def _effective_preopen_idx(pub_ts_series):
        pub_dt = pub_ts_series.astype(str).str[:10].values
        pub_hm = pub_ts_series.astype(str).str[11:19].values
        valid_p = pub_dt <= end_cutoff
        pos = np.searchsorted(full_cal, pub_dt[valid_p], side="left")
        on_same = (pos < len(full_cal)) & (full_cal[np.minimum(pos, len(full_cal) - 1)] == pub_dt[valid_p])
        after_0925 = pub_hm[valid_p] >= "09:25:00"
        eff = np.where(on_same & after_0925, pos + 1, pos)
        return valid_p, eff

    tox = pd.read_parquet(os.path.join(ROOT, "sim-portfolio/data/pit_reg_tox_notices_5y_complete.parquet"), columns=["sec_code", "pub_datetime_cst", "title"])
    # Extend > 2026-11-17 from cninfo_notices_5y_pit.db so latest week has 0 gap
    if end_cutoff > "2026-11-17":
        con_n = sqlite3.connect(f"file:{os.path.join(ROOT, 'sim-portfolio/data/cninfo_notices_5y_pit.db')}?mode=ro", uri=True)
        extra_n = pd.read_sql_query(
            "SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst > '2026-11-17 19:00:00' AND substr(pub_datetime_cst,1,10) <= ? AND (title LIKE '%立案%' OR title LIKE '%退市%' OR title LIKE '%监管%' OR title LIKE '%警示%' OR title LIKE '%风险提示%' OR title LIKE '%异常波动%')",
            con_n,
            params=(end_cutoff,),
        )
        con_n.close()
        if len(extra_n):
            tox = pd.concat([tox, extra_n], ignore_index=True)

    tox["c6"] = tox["sec_code"].astype(str).str.zfill(6)
    vp_t, eff_t = _effective_preopen_idx(tox["pub_datetime_cst"])
    tox = tox[vp_t].copy()
    tox["eff_idx"] = eff_t
    tox = tox[tox["eff_idx"] < len(full_cal)].copy()
    tox["is_abn"] = tox["title"].astype(str).str.contains("异常波动", regex=False)

    tox_reg_map = {}
    tox_abn_map = {}
    for c6_v, grp in tox.sort_values(["c6", "eff_idx"]).groupby("c6", sort=False):
        tox_reg_map[c6_v] = grp.loc[~grp["is_abn"], "eff_idx"].values
        tox_abn_map[c6_v] = grp.loc[grp["is_abn"], "eff_idx"].values

    con_ir = sqlite3.connect(f"file:{os.path.join(ROOT, 'sim-portfolio/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db')}?mode=ro", uri=True)
    ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa", con_ir)
    con_ir.close()
    ir_df["c6"] = ir_df["sec_code"].astype(str).str.zfill(6)
    vp_i, eff_i = _effective_preopen_idx(ir_df["pub_datetime_cst"])
    ir_df = ir_df[vp_i].copy()
    ir_df["eff_idx"] = eff_i
    ir_df = ir_df[ir_df["eff_idx"] < len(full_cal)].copy()
    ir_map = {c6_v: grp["eff_idx"].values for c6_v, grp in ir_df.sort_values(["c6", "eff_idx"]).groupby("c6", sort=False)}

    tox30 = np.zeros(len(bars), dtype=np.int8)
    abn30 = np.zeros(len(bars), dtype=np.int8)
    ir30 = np.zeros(len(bars), dtype=np.int16)
    dt_idx_arr = bars["dt"].map(kpl_cal_idx).values.astype(np.int32)
    for s, e in zip(np.concatenate(([0], brk_b)), np.concatenate((brk_b, [len(bars)]))):
        ck = b_c6[s]
        d_sub = dt_idx_arr[s:e]
        if ck in tox_reg_map and len(tox_reg_map[ck]):
            a = tox_reg_map[ck]
            tox30[s:e] = np.clip(np.searchsorted(a, d_sub, side="right") - np.searchsorted(a, d_sub - 29, side="left"), 0, 127).astype(np.int8)
        if ck in tox_abn_map and len(tox_abn_map[ck]):
            a = tox_abn_map[ck]
            abn30[s:e] = np.clip(np.searchsorted(a, d_sub, side="right") - np.searchsorted(a, d_sub - 29, side="left"), 0, 127).astype(np.int8)
        if ck in ir_map and len(ir_map[ck]):
            a = ir_map[ck]
            ir30[s:e] = (np.searchsorted(a, d_sub, side="right") - np.searchsorted(a, d_sub - 29, side="left")).astype(np.int16)

    bars["tox_reg_30d_pre"] = tox30
    bars["abn_notice_30d_pre"] = abn30
    bars["ir_cnt_30d_pre"] = ir30
    del tox, ir_df, tox_reg_map, tox_abn_map, ir_map
    gc.collect()

    # 9. Commodity 3-Ring Mapping & Driver Signal T-1 (< dt, < end_cutoff)
    with open(os.path.join(ROOT, "sim-portfolio/output/extreme_commodities_3ring_backtest_20261125/three_ring_mapping.json")) as f:
        tm = json.load(f)
    stock_ring = {}  # c6 -> (tier, driver_sym) priority ring1 > ring2 > ring3
    for _, item in tm["commodities"].items():
        drv = item.get("driver")
        for tier, key in [(1, "ring1"), (2, "ring2"), (3, "ring3")]:
            for tk in item.get(key, []):
                c6_t = str(tk)[:6]
                if c6_t not in stock_ring or tier < stock_ring[c6_t][0]:
                    stock_ring[c6_t] = (tier, drv)

    comm_dir = os.path.join(ROOT, "sim-portfolio/output/extreme_commodities_3ring_backtest_20261125/data_cache")
    cf = pd.read_parquet(os.path.join(comm_dir, "cn_futures_close.parquet"))
    gf = pd.read_parquet(os.path.join(comm_dir, "global_futures_close.parquet"))
    all_fut = pd.concat([cf, gf], axis=1).sort_index()
    all_fut.index = pd.to_datetime(all_fut.index).strftime("%Y-%m-%d")
    all_fut = all_fut[all_fut.index < end_cutoff]
    all_fut = all_fut[all_fut.index >= "2015-01-01"].copy()

    # For drivers used in stock_ring, compute 20d ret and 1260d causal pct, mapped strictly < dt
    used_drivers = sorted(set(v[1] for v in stock_ring.values() if v[1] in all_fut.columns))
    drv_df = pd.DataFrame({"dt": cal_dates})
    drv_df["dt_ts"] = pd.to_datetime(drv_df["dt"])
    fut_sub = all_fut[used_drivers].copy()
    fut_ret20 = fut_sub.pct_change(20) * 100.0
    # Causal 1260d percentile for used drivers
    fut_pct5y = pd.DataFrame(index=fut_sub.index, columns=used_drivers, dtype=np.float32)
    fut_idx = fut_sub.index.values
    mask_21 = fut_idx >= "2020-11-01"
    for col in used_drivers:
        v = fut_sub[col].values
        out_p = np.full(len(v), np.nan, dtype=np.float32)
        for r in np.where(mask_21)[0]:
            if not np.isfinite(v[r]):
                continue
            w = v[max(0, r - 1259) : r + 1]
            w = w[np.isfinite(w)]
            if len(w) >= 252:
                out_p[r] = float(np.mean(w <= v[r]))
        fut_pct5y[col] = out_p

    fut_ret20.index = pd.to_datetime(fut_ret20.index)
    fut_pct5y.index = pd.to_datetime(fut_pct5y.index)
    cal_ts_df = pd.DataFrame({"dt": cal_dates, "dt_ts": pd.to_datetime(cal_dates)}).sort_values("dt_ts")
    drv_r20_aligned = pd.merge_asof(cal_ts_df, fut_ret20.sort_index(), left_on="dt_ts", right_index=True, direction="backward", allow_exact_matches=False)
    drv_p5y_aligned = pd.merge_asof(cal_ts_df, fut_pct5y.sort_index(), left_on="dt_ts", right_index=True, direction="backward", allow_exact_matches=False)

    dt_pos_map = {d: i for i, d in enumerate(cal_dates)}
    cal_pos_arr = bars["dt"].map(dt_pos_map).values.astype(np.int32)
    ring_tier = np.zeros(len(bars), dtype=np.int8)
    drv_r20 = np.full(len(bars), np.nan, dtype=np.float32)
    drv_p5y = np.full(len(bars), np.nan, dtype=np.float32)
    r20_mat = {d: drv_r20_aligned[d].values.astype(np.float32) for d in used_drivers}
    p5y_mat = {d: drv_p5y_aligned[d].values.astype(np.float32) for d in used_drivers}
    for s, e in zip(np.concatenate(([0], brk_b)), np.concatenate((brk_b, [len(bars)]))):
        info = stock_ring.get(b_c6[s])
        if info is None:
            continue
        tr, dr = info
        ring_tier[s:e] = tr
        if dr in r20_mat:
            idx_sub = cal_pos_arr[s:e]
            drv_r20[s:e] = r20_mat[dr][idx_sub]
            drv_p5y[s:e] = p5y_mat[dr][idx_sub]
    bars["comm_ring_tier"] = ring_tier
    bars["comm_driver_ret20_t1"] = drv_r20
    bars["comm_driver_pct5y_t1"] = drv_p5y
    del all_fut, cf, gf, fut_sub, fut_ret20, fut_pct5y
    gc.collect()

    bars = bars.drop(columns=["prev_dt"])

    # Convert c6 and dt to compact Categories (dt ordered!) so single-process read RAM < 2 GB
    c6_cats = sorted(bars["c6"].unique())
    dt_cats = sorted(bars["dt"].unique())
    bars["c6"] = pd.Categorical(bars["c6"], categories=c6_cats, ordered=False)
    bars["dt"] = pd.Categorical(bars["dt"], categories=dt_cats, ordered=True)

    ram_gb = bars.memory_usage(deep=True).sum() / 1e9
    print(f"[Step2] Done {bars.shape} in {time.time()-t0:.1f}s | RAM={ram_gb:.3f} GB")
    return bars, ind_to_id


def main():
    # 1. Full build 2021-01-04 .. 2026-11-25
    df_full, ind_map = build_stock_day_core("2026-11-25")
    out_pq = os.path.join(OUT_DIR, "stock_day_core_features_pit.parquet")
    df_full.to_parquet(out_pq, index=False, compression="snappy")
    n_rows_full, n_cols_full = df_full.shape
    full_cols = list(df_full.columns)
    full_dt_min, full_dt_max = str(df_full["dt"].min()), str(df_full["dt"].max())
    miss_rates = {c: round(float(df_full[c].isna().mean()), 6) for c in full_cols if c not in ("c6", "dt")}
    del df_full
    gc.collect()

    # Check single-process read RAM of saved parquet
    df_read = pd.read_parquet(out_pq)
    read_ram_gb = round(float(df_read.memory_usage(deep=True).sum() / 1e9), 4)
    print(f"[Step2] Saved {out_pq} ({round(os.path.getsize(out_pq)/1e6, 1)} MB) | pd.read_parquet RAM = {read_ram_gb} GB")
    assert read_ram_gb < 2.0, f"Read RAM {read_ram_gb} GB >= 2.0 GB!"
    del df_read
    gc.collect()

    # 2. Physical truncation check at 2024-12-31
    df_trunc, _ = build_stock_day_core("2024-12-31")
    df_full_cut = pd.read_parquet(out_pq)
    df_full_cut = df_full_cut[df_full_cut["dt"] <= "2024-12-31"].copy()
    df_trunc["c6"] = df_trunc["c6"].astype(str)
    df_trunc["dt"] = df_trunc["dt"].astype(str)
    df_full_cut["c6"] = df_full_cut["c6"].astype(str)
    df_full_cut["dt"] = df_full_cut["dt"].astype(str)
    assert len(df_trunc) == len(df_full_cut), f"Row count mismatch: {len(df_trunc)} vs {len(df_full_cut)}"
    df_trunc = df_trunc.sort_values(["c6", "dt"]).reset_index(drop=True)
    df_full_cut = df_full_cut.sort_values(["c6", "dt"]).reset_index(drop=True)
    assert (df_trunc["c6"].values == df_full_cut["c6"].values).all()
    assert (df_trunc["dt"].values == df_full_cut["dt"].values).all()

    feat_cols = [c for c in full_cols if c not in ("c6", "dt")]
    max_diff = 0.0
    worst_col = None
    for c in feat_cols:
        a = df_trunc[c].values.astype(np.float64)
        b = df_full_cut[c].values.astype(np.float64)
        if not np.array_equal(np.isnan(a), np.isnan(b)):
            d = 999.0
        else:
            fin = np.isfinite(a) & np.isfinite(b)
            d = float(np.max(np.abs(a[fin] - b[fin]))) if fin.any() else 0.0
        if d > max_diff:
            max_diff = d
            worst_col = c
    print(f"[Step2] 2024-12-31 physical truncation check ({len(df_trunc)} rows): max_abs_diff={max_diff} (worst={worst_col})")
    assert max_diff == 0.0, f"Step2 truncation failed on {worst_col}: {max_diff}"

    audit = {
        "file": out_pq,
        "rows": int(n_rows_full),
        "cols": int(n_cols_full),
        "date_min": full_dt_min,
        "date_max": full_dt_max,
        "read_ram_gb": read_ram_gb,
        "size_mb": round(os.path.getsize(out_pq) / 1024 / 1024, 2),
        "truncation_2024_12_31_rows": int(len(df_trunc)),
        "truncation_2024_12_31_max_abs_diff": max_diff,
        "missing_rates": miss_rates,
        "csrc_ind_id_map": ind_map,
    }
    audit_path = os.path.join(OUT_DIR, "_audit_step2_stockday.json")
    with open(audit_path, "w") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    print(f"[Step2] Audit saved -> {audit_path}")


if __name__ == "__main__":
    main()
