#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A股短线量化红队五年全量无后视镜(PIT)回测：
假说：「高流动性大池子人气妖股暴跌后，次日竞价高开反核弱转强」
严守 D12 (禁yfinance) / D15 (防伪四必核) / Q8 (双门核查) / 物理截断校验。
"""
import json
import os
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
A_DAILY = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
ST_JSON = f"{DATA_DIR}/st_universe.json"
IND_CSV = f"{ROOT}/sim-portfolio/backtest/2026-10-15-review2022/industry.csv"
IDX_JSON = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
M5_PARQUET = f"{DATA_DIR}/all_strategies_5m_complete_pit.parquet"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/redteam_full_audit_20261123/partA_demon_reversal"

EPS = 1e-9

WINDOWS = [
    ("全五年", "2021-11-15", "2026-11-20"),
    ("IS_21_23", "2021-11-15", "2023-12-31"),
    ("OOS_24_26", "2024-01-01", "2026-11-20"),
    ("近三年", "2023-11-20", "2026-11-20"),
    ("2026全年", "2026-01-01", "2026-11-20"),
]

OPEN_WINDOWS = [
    ("W0_低开对照[-5,+1]", -0.05, 0.01),
    ("W1_平开微高[-1,+2]", -0.01, 0.02),
    ("W2_温和反核[+1,+5]", 0.01, 0.05),
    ("W3_中高开[+2,+7]", 0.02, 0.07),
    ("W4_高开强转[+4,+8.5]", 0.04, 0.085),
]

OPEN_BINS = [
    ("B0_深水[-10,-5)", -0.105, -0.05),
    ("B1_低开[-5,-1)", -0.05, -0.01),
    ("B2_平开[-1,+1)", -0.01, 0.01),
    ("B3_小高开[+1,+2)", 0.01, 0.02),
    ("B4_中高开[+2,+4)", 0.02, 0.04),
    ("B5_强高开[+4,+7)", 0.04, 0.07),
    ("B6_极高开[+7,+8.5]", 0.07, 0.085),
    ("B7_逼板(+8.5,zt)", 0.085, 0.11),
]


def round_half_up_01(arr: np.ndarray) -> np.ndarray:
    return np.floor(arr * 100.0 + 0.5 + 1e-9) / 100.0


def load_csi300() -> dict:
    with open(IDX_JSON, "r", encoding="utf-8") as f:
        return json.load(f)["sh000300"]


def csi_window_ret(csi_map: dict, s_dt: str, e_dt: str) -> float:
    dts = sorted(csi_map.keys())
    prev = [d for d in dts if d < s_dt]
    in_w = [d for d in dts if s_dt <= d <= e_dt]
    if not in_w:
        return 0.0
    base = prev[-1] if prev else in_w[0]
    end = in_w[-1]
    return float((csi_map[end] / csi_map[base] - 1.0) * 100.0)


def load_meta():
    with open(ST_JSON, "r", encoding="utf-8") as f:
        st_codes = set(json.load(f)["codes"])
    name_map = {}
    if os.path.exists(IND_CSV):
        ind = pd.read_csv(IND_CSV)
        name_map = dict(zip(ind["code"].astype(str).str.slice(-6), ind["code_name"].astype(str)))

    m1 = pd.read_parquet(A_DAILY, columns=["ticker", "date"])
    m2 = pd.read_parquet(A_DELISTED, columns=["ticker", "date"])
    meta = pd.concat([m1, m2], ignore_index=True)
    meta = meta[meta["ticker"].str.endswith((".SH", ".SZ")) & meta["ticker"].str.slice(0, 2).isin(["00", "60"])]
    first_dt_map = meta.groupby("ticker")["date"].min().to_dict()
    return st_codes, name_map, first_dt_map


def prepare_universe(st_codes: set, first_dt_map: dict, cutoff_date: str | None = None):
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn"]
    filters = [("date", ">=", pd.Timestamp("2021-09-01"))]
    if cutoff_date is not None:
        filters.append(("date", "<=", pd.Timestamp(cutoff_date)))

    d1 = pd.read_parquet(A_DAILY, columns=cols, filters=filters)
    d2 = pd.read_parquet(A_DELISTED, columns=cols, filters=filters)
    d1["is_delisted"] = 0
    d2["is_delisted"] = 1
    df = pd.concat([d1, d2], ignore_index=True)
    df["code"] = df["ticker"].str[:6]
    df = df[df["ticker"].str.endswith((".SH", ".SZ")) & df["code"].str.startswith(("00", "60"))].copy()
    df = df[~df["code"].isin(st_codes)].copy()
    df = df[(df["volume"] > 0) & (df["amount"] > 0) & (df["open"] > 0) & (df["close"] > 0)].copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    mkt_dates = np.sort(df["date"].unique())
    mkt_date_to_idx = {d: i for i, d in enumerate(mkt_dates)}
    df["mkt_idx"] = df["date"].map(mkt_date_to_idx).astype(np.int32)

    df["first_dt"] = df["ticker"].map(first_dt_map)
    df["nth_local"] = df.groupby("ticker", sort=False).cumcount()
    df["is_mature"] = np.where(df["first_dt"] >= pd.Timestamp("2021-09-01"), df["nth_local"] >= 15, df["nth_local"] >= 10)

    g = df.groupby("ticker", sort=False)
    df["adjf"] = df["adj_close"] / df["close"]
    df["prev_adj_close"] = g["adj_close"].shift(1)
    df["prevc"] = df["prev_adj_close"] / df["adjf"]
    df["zt_px"] = round_half_up_01(df["prevc"].to_numpy() * 1.10)
    df["dt_px"] = round_half_up_01(df["prevc"].to_numpy() * 0.90)
    df["ret"] = df["close"] / df["prevc"] - 1.0

    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.005) & (df["ret"] >= 0.095) & df["prevc"].notna()
    df["touched_zt"] = (df["high"] >= df["zt_px"] - 0.005) & ((df["high"] / df["prevc"] - 1.0) >= 0.095) & df["prevc"].notna()
    df["is_dt"] = (df["close"] <= df["dt_px"] + 0.005) & (df["ret"] <= -0.095) & df["prevc"].notna()
    df["touched_dt"] = (df["low"] <= df["dt_px"] + 0.005) & ((df["low"] / df["prevc"] - 1.0) <= -0.095) & df["prevc"].notna()

    s = df["is_zt"].astype(int)
    grp = (s != s.groupby(df["ticker"], sort=False).shift()).cumsum()
    df["streak"] = s.groupby([df["ticker"], grp], sort=False).cumsum() * s

    df["zt_10d"] = g["is_zt"].transform(lambda x: x.rolling(10, min_periods=1).sum())
    df["streak_10d"] = g["streak"].transform(lambda x: x.rolling(10, min_periods=1).max())
    df["ma5_amt_prev"] = g["amount"].transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
    df["adj_high"] = df["high"] * df["adjf"]
    df["max_adj_high_prev4"] = g["adj_high"].transform(lambda x: x.shift(1).rolling(4, min_periods=2).max())
    df["dd_from_4d_high"] = df["adj_close"] / df["max_adj_high_prev4"] - 1.0

    df["type1"] = df["is_dt"] | (df["touched_dt"] & (df["ret"] <= -0.07))
    df["type2a"] = (df["close"] < df["open"]) & ((df["close"] / df["high"] - 1.0) <= -0.10)
    df["type2b"] = (df["close"] < df["open"]) & (df["ret"] <= -0.07)
    df["type2c_15"] = (df["close"] < df["open"]) & df["touched_zt"] & (~df["is_zt"]) & (df["amount"] >= 1.5 * df["ma5_amt_prev"])
    df["type2c_20"] = (df["close"] < df["open"]) & df["touched_zt"] & (~df["is_zt"]) & (df["amount"] >= 2.0 * df["ma5_amt_prev"])
    df["type2"] = df["type2a"] | df["type2b"] | df["type2c_15"]
    df["type3"] = (df["dd_from_4d_high"] <= -0.15) & (df["ret"] <= -0.05)

    return df


def extract_all_signals_and_exits(df: pd.DataFrame, name_map: dict, max_date_str: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    base = (
        (df["date"] >= pd.Timestamp("2021-11-15")) &
        (df["date"] <= pd.Timestamp(max_date_str)) &
        df["is_mature"] &
        (df["prevc"] >= 2.0) &
        (df["close"] >= 2.0) &
        ((df["zt_10d"] >= 2) | (df["streak_10d"] >= 2)) &
        (df["amount"] >= 1e9) &
        (df["type1"] | df["type2"] | df["type3"])
    )
    cand_idx = np.flatnonzero(base.to_numpy())

    tickers = df["ticker"].to_numpy()
    codes = df["code"].to_numpy()
    dates = df["date"].dt.strftime("%Y-%m-%d").to_numpy()
    mkt_idx = df["mkt_idx"].to_numpy()
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    closes = df["close"].to_numpy()
    adjfs = df["adjf"].to_numpy()
    prevcs = df["prevc"].to_numpy()
    zt_pxs = df["zt_px"].to_numpy()
    dt_pxs = df["dt_px"].to_numpy()
    rets = df["ret"].to_numpy()
    amts = df["amount"].to_numpy()
    ma5_prev = df["ma5_amt_prev"].to_numpy()
    is_zt_arr = df["is_zt"].to_numpy()
    is_del_arr = df["is_delisted"].to_numpy()
    t1_arr = df["type1"].to_numpy()
    t2_arr = df["type2"].to_numpy()
    t2c20_arr = df["type2c_20"].to_numpy()
    t3_arr = df["type3"].to_numpy()
    zt10_arr = df["zt_10d"].to_numpy()
    str10_arr = df["streak_10d"].to_numpy()
    dd4_arr = df["dd_from_4d_high"].to_numpy()

    n_total = len(df)
    rows = []
    open_positions = []

    def find_unsealed_close_exit(tk: str, start_pos: int, check_zt: bool, strict_close_dt: bool = False):
        pos = start_pos
        zt_days = 0
        dt_defers = 0
        while pos < n_total and tickers[pos] == tk:
            if check_zt and is_zt_arr[pos]:
                zt_days += 1
                pos += 1
                continue
            blocked = (closes[pos] <= dt_pxs[pos] + 0.005) if strict_close_dt else (highs[pos] <= dt_pxs[pos] + 0.005)
            if blocked:
                dt_defers += 1
                pos += 1
                continue
            reason = "close_unsealed_zt" if zt_days > 0 else ("close_after_dt_defer" if dt_defers > 0 else "close_t1")
            return pos, float(closes[pos]), reason, zt_days, dt_defers
        return None, np.nan, "unclosed_past_end", zt_days, dt_defers

    def find_open_exit(tk: str, start_pos: int):
        pos = start_pos
        dt_defers = 0
        while pos < n_total and tickers[pos] == tk:
            if highs[pos] <= dt_pxs[pos] + 0.005:
                dt_defers += 1
                pos += 1
                continue
            if opens[pos] <= dt_pxs[pos] + 0.005:
                return pos, float(closes[pos]), "open_dt_unsealed_close", dt_defers
            reason = "open_after_dt_defer" if dt_defers > 0 else "open_t1"
            return pos, float(opens[pos]), reason, dt_defers
        return None, np.nan, "unclosed_past_end", dt_defers

    for i in cand_idx:
        b = i + 1
        if b >= n_total or tickers[b] != tickers[i]:
            continue
        if mkt_idx[b] != mkt_idx[i] + 1:
            continue
        if prevcs[b] < 2.0:
            continue
        if opens[b] >= zt_pxs[b] - 0.005:
            continue
        if (opens[b] <= dt_pxs[b] + 0.005) and (highs[b] <= dt_pxs[b] + 0.005):
            continue

        tk = tickers[i]
        buy_open_ret = opens[b] / prevcs[b] - 1.0
        buy_adj = opens[b] * adjfs[b]
        sealed_on_buy = bool(is_zt_arr[b])

        t1_pos = b + 1
        if t1_pos >= n_total or tickers[t1_pos] != tk:
            open_positions.append({
                "signal_date": dates[i],
                "buy_date": dates[b],
                "code": codes[i],
                "name": name_map.get(codes[i], codes[i]),
                "sig_amount_yi": round(amts[i] / 1e8, 2),
                "sig_ret_pct": round(rets[i] * 100.0, 2),
                "type1": bool(t1_arr[i]),
                "type2": bool(t2_arr[i]),
                "type3": bool(t3_arr[i]),
                "buy_open_ret_pct": round(buy_open_ret * 100.0, 2),
                "buy_day_close_vs_open_pct": round((closes[b] / opens[b] - 1.0) * 100.0, 2),
                "sealed_on_buy": sealed_on_buy,
            })
            continue

        e1_pos, e1_px, e1_rsn, e1_ztd, e1_dtd = find_unsealed_close_exit(tk, t1_pos, check_zt=sealed_on_buy, strict_close_dt=False)
        e1s_pos, e1s_px, _, _, _ = find_unsealed_close_exit(tk, t1_pos, check_zt=sealed_on_buy, strict_close_dt=True)

        if sealed_on_buy:
            e2_pos, e2_px, e2_rsn, e2_dtd = e1_pos, e1_px, e1_rsn, e1_dtd
        else:
            t1_open_ret = opens[t1_pos] / prevcs[t1_pos] - 1.0
            if t1_open_ret < 0.005:
                e2_pos, e2_px, e2_rsn, e2_dtd = find_open_exit(tk, t1_pos)
            else:
                e2_pos, e2_px, e2_rsn, _, e2_dtd = find_unsealed_close_exit(tk, t1_pos, check_zt=False)

        if sealed_on_buy:
            e3_pos, e3_px, e3_rsn, e3_dtd = e1_pos, e1_px, e1_rsn, e1_dtd
        else:
            e3_pos, e3_px, e3_rsn, e3_dtd = find_open_exit(tk, t1_pos)

        if e1_pos is None or e2_pos is None or e3_pos is None:
            open_positions.append({
                "signal_date": dates[i],
                "buy_date": dates[b],
                "code": codes[i],
                "name": name_map.get(codes[i], codes[i]),
                "sig_amount_yi": round(amts[i] / 1e8, 2),
                "sig_ret_pct": round(rets[i] * 100.0, 2),
                "type1": bool(t1_arr[i]),
                "type2": bool(t2_arr[i]),
                "type3": bool(t3_arr[i]),
                "buy_open_ret_pct": round(buy_open_ret * 100.0, 2),
                "buy_day_close_vs_open_pct": round((closes[b] / opens[b] - 1.0) * 100.0, 2),
                "sealed_on_buy": sealed_on_buy,
            })
            continue

        g1 = (e1_px * adjfs[e1_pos]) / buy_adj - 1.0
        g1_strict = (e1s_px * adjfs[e1s_pos]) / buy_adj - 1.0 if e1s_pos is not None else np.nan
        g2 = (e2_px * adjfs[e2_pos]) / buy_adj - 1.0
        g3 = (e3_px * adjfs[e3_pos]) / buy_adj - 1.0

        rows.append({
            "signal_date": dates[i],
            "buy_date": dates[b],
            "code": codes[i],
            "ticker": tk,
            "name": name_map.get(codes[i], codes[i]),
            "is_delisted": int(is_del_arr[i]),
            "sig_amount": float(amts[i]),
            "sig_amount_yi": float(amts[i] / 1e8),
            "sig_amt_ratio": float(amts[i] / ma5_prev[i]) if ma5_prev[i] > 0 else np.nan,
            "sig_ret": float(rets[i]),
            "sig_ch_dd": float(closes[i] / highs[i] - 1.0),
            "sig_dd4d": float(dd4_arr[i]),
            "zt_10d": int(zt10_arr[i]),
            "streak_10d": int(str10_arr[i]),
            "type1": bool(t1_arr[i]),
            "type2": bool(t2_arr[i]),
            "type2_strict2x": bool((closes[i] < opens[i]) and (((closes[i]/highs[i]-1) <= -0.10) or (rets[i] <= -0.07) or t2c20_arr[i])),
            "type3": bool(t3_arr[i]),
            "buy_open": float(opens[b]),
            "buy_close": float(closes[b]),
            "buy_open_ret": float(buy_open_ret),
            "sealed_on_buy": sealed_on_buy,
            "e1_exit_date": dates[e1_pos],
            "e1_gross_ret": float(g1),
            "e1_strict_gross_ret": float(g1_strict),
            "e1_reason": e1_rsn,
            "e1_dt_defers": int(e1_dtd),
            "e1_close_at_dt": int(closes[e1_pos] <= dt_pxs[e1_pos] + 0.005),
            "e2_exit_date": dates[e2_pos],
            "e2_gross_ret": float(g2),
            "e2_reason": e2_rsn,
            "e3_exit_date": dates[e3_pos],
            "e3_gross_ret": float(g3),
            "e3_reason": e3_rsn,
        })

    return pd.DataFrame(rows), pd.DataFrame(open_positions)


def eval_slice(df_sig: pd.DataFrame, exit_col: str, fee_bps: float, csi_map: dict, rank_mode: str = "amt") -> dict:
    fee = fee_bps / 10000.0
    out = {}
    if df_sig.empty:
        for wname, s_dt, e_dt in WINDOWS:
            csi_r = csi_window_ret(csi_map, s_dt, e_dt)
            out[wname] = {
                "raw_n": 0, "active_days": 0, "eq_nav": 1.0, "eq_ret_pct": 0.0, "eq_mdd_pct": 0.0, "eq_excess_pp": round(-csi_r, 2),
                "eq_trim5_ret_pct": 0.0,
                "raw_wr_pct": 0.0, "raw_mean_pct": 0.0, "raw_plr": 0.0,
                "slot_n": 0, "slot_wr_pct": 0.0, "slot_mean_pct": 0.0, "slot_plr": 0.0,
                "slot_nav": 1.0, "slot_ret_pct": 0.0, "slot_mdd_pct": 0.0, "slot_excess_pp": round(-csi_r, 2),
                "slot_trim5_nav": 1.0, "slot_trim5_ret_pct": 0.0,
                "csi300_pct": round(csi_r, 2),
            }
        return out

    prefix = exit_col
    work = df_sig.copy()
    work["net_ret"] = work[f"{prefix}_gross_ret"] - fee
    work["exit_date"] = work[f"{prefix}_exit_date"]

    if rank_mode == "amt":
        work = work.sort_values(["buy_date", "sig_amount", "code"], ascending=[True, False, True]).reset_index(drop=True)
    else:
        work = work.sort_values(["buy_date", "sig_ret", "sig_amount", "code"], ascending=[True, True, False, True]).reset_index(drop=True)

    for wname, s_dt, e_dt in WINDOWS:
        sub = work[(work["buy_date"] >= s_dt) & (work["buy_date"] <= e_dt)].copy()
        csi_r = csi_window_ret(csi_map, s_dt, e_dt)
        if sub.empty:
            out[wname] = {
                "raw_n": 0, "active_days": 0, "eq_nav": 1.0, "eq_ret_pct": 0.0, "eq_mdd_pct": 0.0, "eq_excess_pp": round(-csi_r, 2),
                "eq_trim5_ret_pct": 0.0,
                "raw_wr_pct": 0.0, "raw_mean_pct": 0.0, "raw_plr": 0.0,
                "slot_n": 0, "slot_wr_pct": 0.0, "slot_mean_pct": 0.0, "slot_plr": 0.0,
                "slot_nav": 1.0, "slot_ret_pct": 0.0, "slot_mdd_pct": 0.0, "slot_excess_pp": round(-csi_r, 2),
                "slot_trim5_nav": 1.0, "slot_trim5_ret_pct": 0.0,
                "csi300_pct": round(csi_r, 2),
            }
            continue

        day_rets = sub.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy()
        eq_curve = np.cumprod(1.0 + day_rets)
        eq_pk = np.maximum.accumulate(np.insert(eq_curve, 0, 1.0))[1:]
        eq_mdd = float(np.max((eq_pk - eq_curve) / eq_pk) * 100.0)
        eq_nav = float(eq_curve[-1])
        eq_ret_pct = (eq_nav - 1.0) * 100.0

        if len(sub) > 5:
            sub_drop5 = sub.drop(sub["net_ret"].nlargest(5).index)
            eq_trim5_nav = float(np.prod(1.0 + sub_drop5.groupby("buy_date")["net_ret"].mean().to_numpy()))
        else:
            eq_trim5_nav = 1.0
        eq_trim5_ret_pct = (eq_trim5_nav - 1.0) * 100.0

        r_all = sub["net_ret"].to_numpy()
        w_all = r_all[r_all > 0]
        l_all = r_all[r_all <= 0]
        raw_wr = float((r_all > 0).mean() * 100.0)
        raw_mean = float(r_all.mean() * 100.0)
        raw_plr = float(w_all.mean() / abs(l_all.mean())) if (len(w_all) > 0 and len(l_all) > 0 and l_all.mean() < 0) else (99.0 if len(w_all) > 0 else 0.0)

        picked_rets = []
        busy_until = ""
        for row in sub.itertuples(index=False):
            if not busy_until or row.buy_date > busy_until:
                picked_rets.append(float(row.net_ret))
                busy_until = str(row.exit_date)
        s_arr = np.array(picked_rets, dtype=float)
        s_curve = np.cumprod(1.0 + s_arr)
        s_pk = np.maximum.accumulate(np.insert(s_curve, 0, 1.0))[1:]
        s_mdd = float(np.max((s_pk - s_curve) / s_pk) * 100.0)
        s_nav = float(s_curve[-1])
        s_ret_pct = (s_nav - 1.0) * 100.0

        sw = s_arr[s_arr > 0]
        sl = s_arr[s_arr <= 0]
        s_wr = float((s_arr > 0).mean() * 100.0)
        s_mean = float(s_arr.mean() * 100.0)
        s_plr = float(sw.mean() / abs(sl.mean())) if (len(sw) > 0 and len(sl) > 0 and sl.mean() < 0) else (99.0 if len(sw) > 0 else 0.0)

        s_sorted = np.sort(s_arr)
        trim5_nav = float(np.prod(1.0 + s_sorted[:-5])) if len(s_sorted) > 5 else 1.0

        out[wname] = {
            "raw_n": int(len(sub)),
            "active_days": int(len(day_rets)),
            "eq_nav": round(eq_nav, 4),
            "eq_ret_pct": round(eq_ret_pct, 2),
            "eq_mdd_pct": round(eq_mdd, 2),
            "eq_excess_pp": round(eq_ret_pct - csi_r, 2),
            "eq_trim5_ret_pct": round(eq_trim5_ret_pct, 2),
            "raw_wr_pct": round(raw_wr, 2),
            "raw_mean_pct": round(raw_mean, 2),
            "raw_plr": round(raw_plr, 2),
            "slot_n": int(len(s_arr)),
            "slot_wr_pct": round(s_wr, 2),
            "slot_mean_pct": round(s_mean, 2),
            "slot_plr": round(s_plr, 2),
            "slot_nav": round(s_nav, 4),
            "slot_ret_pct": round(s_ret_pct, 2),
            "slot_mdd_pct": round(s_mdd, 2),
            "slot_excess_pp": round(s_ret_pct - csi_r, 2),
            "slot_trim5_nav": round(trim5_nav, 4),
            "slot_trim5_ret_pct": round((trim5_nav - 1.0) * 100.0, 2),
            "csi300_pct": round(csi_r, 2),
        }
    return out


def verify_5m_spot_check(df_trades: pd.DataFrame) -> dict:
    if not os.path.exists(M5_PARQUET) or df_trades.empty:
        return {"covered_buy_bars": 0}
    m5 = pd.read_parquet(M5_PARQUET, columns=["c6", "date", "hhmm_int", "open", "close"])
    m5_keys = set(zip(m5["c6"], m5["date"]))
    covered = df_trades[df_trades.apply(lambda r: (r["code"], r["buy_date"]) in m5_keys, axis=1)]
    if covered.empty:
        return {"covered_buy_bars": 0}
    m5_sub = m5.set_index(["c6", "date", "hhmm_int"])
    open_diffs = []
    for r in covered.head(50).itertuples():
        for hh in (930, 935):
            if (r.code, r.buy_date, hh) in m5_sub.index:
                px = float(m5_sub.loc[(r.code, r.buy_date, hh), "open"])
                open_diffs.append(abs(px - r.buy_open) / r.buy_open)
                break
    return {
        "covered_buy_bars": int(len(covered)),
        "checked_sample": int(len(open_diffs)),
        "max_open_rel_diff": round(float(max(open_diffs)) if open_diffs else 0.0, 6),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    csi_map = load_csi300()
    st_codes, name_map, first_dt_map = load_meta()

    print("[1/5] Preparing full 5Y PIT universe...")
    df_full = prepare_universe(st_codes, first_dt_map, cutoff_date=None)
    trades_all, open_pos = extract_all_signals_and_exits(df_full, name_map, "2026-11-19")
    trades_all.to_csv(f"{OUT_DIR}/all_crash_signals_ledger.csv", index=False)
    open_pos.to_csv(f"{OUT_DIR}/unclosed_20261120_signals.csv", index=False)

    print("[2/5] Running systematic matrix...")
    liq_cuts = [("amt>=10亿", 1e9), ("amt>=15亿", 1.5e9), ("amt>=20亿", 2.0e9)]
    type_masks = {
        "AllTypes": lambda d: pd.Series(True, index=d.index),
        "Type1_跌停大面": lambda d: d["type1"],
        "Type2_天地板巨量长阴": lambda d: d["type2"],
        "Type3_多日连杀急跌": lambda d: d["type3"],
    }

    matrix_rows = []
    for liq_name, liq_val in liq_cuts:
        d_liq = trades_all[trades_all["sig_amount"] >= liq_val]
        for t_name, t_fn in type_masks.items():
            d_type = d_liq[t_fn(d_liq)]
            for w_name, lo_o, hi_o in OPEN_WINDOWS:
                d_w = d_type[(d_type["buy_open_ret"] >= lo_o - EPS) & (d_type["buy_open_ret"] <= hi_o + EPS)]
                for ex_col in ("e1", "e2", "e3"):
                    res_30_amt = eval_slice(d_w, ex_col, 30.0, csi_map, rank_mode="amt")
                    res_50_amt = eval_slice(d_w, ex_col, 50.0, csi_map, rank_mode="amt")
                    res_30_dd = eval_slice(d_w, ex_col, 30.0, csi_map, rank_mode="crash")
                    row = {
                        "liq": liq_name,
                        "type": t_name,
                        "open_win": w_name,
                        "exit": ex_col.upper(),
                        "n_5y": res_30_amt["全五年"]["raw_n"],
                        "days_5y": res_30_amt["全五年"]["active_days"],
                        "wr_5y": res_30_amt["全五年"]["raw_wr_pct"],
                        "mean_5y": res_30_amt["全五年"]["raw_mean_pct"],
                        "plr_5y": res_30_amt["全五年"]["raw_plr"],
                        "eq_ret_5y": res_30_amt["全五年"]["eq_ret_pct"],
                        "eq_mdd_5y": res_30_amt["全五年"]["eq_mdd_pct"],
                        "eq_ex_5y": res_30_amt["全五年"]["eq_excess_pp"],
                        "eq_trim5_5y": res_30_amt["全五年"]["eq_trim5_ret_pct"],
                        "slot_amt_n_5y": res_30_amt["全五年"]["slot_n"],
                        "slot_amt_ret_5y": res_30_amt["全五年"]["slot_ret_pct"],
                        "slot_amt_mdd_5y": res_30_amt["全五年"]["slot_mdd_pct"],
                        "slot_amt_ex_5y": res_30_amt["全五年"]["slot_excess_pp"],
                        "slot_amt_trim5_5y": res_30_amt["全五年"]["slot_trim5_ret_pct"],
                        "slot_dd_ret_5y": res_30_dd["全五年"]["slot_ret_pct"],
                        "slot_dd_ex_5y": res_30_dd["全五年"]["slot_excess_pp"],
                        "eq_ret_5y_50bps": res_50_amt["全五年"]["eq_ret_pct"],
                        "slot_amt_ret_5y_50bps": res_50_amt["全五年"]["slot_ret_pct"],
                        "is_n": res_30_amt["IS_21_23"]["raw_n"],
                        "is_wr": res_30_amt["IS_21_23"]["raw_wr_pct"],
                        "is_mean": res_30_amt["IS_21_23"]["raw_mean_pct"],
                        "is_eq_ret": res_30_amt["IS_21_23"]["eq_ret_pct"],
                        "is_eq_ex": res_30_amt["IS_21_23"]["eq_excess_pp"],
                        "is_slot_ret": res_30_amt["IS_21_23"]["slot_ret_pct"],
                        "is_slot_ex": res_30_amt["IS_21_23"]["slot_excess_pp"],
                        "oos_n": res_30_amt["OOS_24_26"]["raw_n"],
                        "oos_wr": res_30_amt["OOS_24_26"]["raw_wr_pct"],
                        "oos_mean": res_30_amt["OOS_24_26"]["raw_mean_pct"],
                        "oos_eq_ret": res_30_amt["OOS_24_26"]["eq_ret_pct"],
                        "oos_eq_ex": res_30_amt["OOS_24_26"]["eq_excess_pp"],
                        "oos_slot_ret": res_30_amt["OOS_24_26"]["slot_ret_pct"],
                        "oos_slot_ex": res_30_amt["OOS_24_26"]["slot_excess_pp"],
                        "y3_n": res_30_amt["近三年"]["raw_n"],
                        "y3_eq_ret": res_30_amt["近三年"]["eq_ret_pct"],
                        "y3_eq_ex": res_30_amt["近三年"]["eq_excess_pp"],
                        "y3_slot_ret": res_30_amt["近三年"]["slot_ret_pct"],
                        "y3_slot_ex": res_30_amt["近三年"]["slot_excess_pp"],
                        "y26_n": res_30_amt["2026全年"]["raw_n"],
                        "y26_wr": res_30_amt["2026全年"]["raw_wr_pct"],
                        "y26_mean": res_30_amt["2026全年"]["raw_mean_pct"],
                        "y26_eq_ret": res_30_amt["2026全年"]["eq_ret_pct"],
                        "y26_eq_ex": res_30_amt["2026全年"]["eq_excess_pp"],
                        "y26_slot_ret": res_30_amt["2026全年"]["slot_ret_pct"],
                        "y26_slot_ex": res_30_amt["2026全年"]["slot_excess_pp"],
                    }
                    matrix_rows.append(row)

    df_matrix = pd.DataFrame(matrix_rows)
    df_matrix.to_csv(f"{OUT_DIR}/matrix_full_results.csv", index=False)

    print("[3/5] Running disjoint open-gap spectrum & strict-dt check...")
    spectrum_rows = []
    for liq_name, liq_val in [("amt>=10亿", 1e9), ("amt>=15亿", 1.5e9), ("amt>=20亿", 2.0e9)]:
        d_liq = trades_all[trades_all["sig_amount"] >= liq_val]
        for b_name, lo_o, hi_o in OPEN_BINS:
            d_b = d_liq[(d_liq["buy_open_ret"] >= lo_o - EPS) & (d_liq["buy_open_ret"] < hi_o - EPS)]
            for ex_col in ("e1", "e2", "e3"):
                r30 = eval_slice(d_b, ex_col, 30.0, csi_map, rank_mode="amt")
                spectrum_rows.append({
                    "liq": liq_name,
                    "open_bin": b_name,
                    "exit": ex_col.upper(),
                    "n_5y": r30["全五年"]["raw_n"],
                    "wr_5y": r30["全五年"]["raw_wr_pct"],
                    "mean_5y": r30["全五年"]["raw_mean_pct"],
                    "plr_5y": r30["全五年"]["raw_plr"],
                    "eq_ret_5y": r30["全五年"]["eq_ret_pct"],
                    "eq_trim5_5y": r30["全五年"]["eq_trim5_ret_pct"],
                    "slot_ret_5y": r30["全五年"]["slot_ret_pct"],
                    "is_eq_ret": r30["IS_21_23"]["eq_ret_pct"],
                    "oos_eq_ret": r30["OOS_24_26"]["eq_ret_pct"],
                    "y26_eq_ret": r30["2026全年"]["eq_ret_pct"],
                })
    pd.DataFrame(spectrum_rows).to_csv(f"{OUT_DIR}/open_gap_spectrum.csv", index=False)

    # Strict close-at-dt sensitivity on top slice (amt>=20亿, Type2, W2)
    s_top = trades_all[(trades_all["sig_amount"] >= 2e9) & trades_all["type2"] & (trades_all["buy_open_ret"] >= 0.01 - EPS) & (trades_all["buy_open_ret"] <= 0.05 + EPS)].copy()
    r_normal = eval_slice(s_top, "e1", 30.0, csi_map, rank_mode="amt")["全五年"]["eq_ret_pct"]
    s_top_strict = s_top.copy()
    s_top_strict["e1_gross_ret"] = s_top_strict["e1_strict_gross_ret"]
    r_strict = eval_slice(s_top_strict, "e1", 30.0, csi_map, rank_mode="amt")["全五年"]["eq_ret_pct"]

    print("[4/5] Running physical truncation test at 2024-12-31...")
    df_trunc = prepare_universe(st_codes, first_dt_map, cutoff_date="2024-12-31")
    trades_trunc, _ = extract_all_signals_and_exits(df_trunc, name_map, "2024-12-30")

    full_pre = trades_all[
        (trades_all["e1_exit_date"] <= "2024-12-31") &
        (trades_all["e2_exit_date"] <= "2024-12-31") &
        (trades_all["e3_exit_date"] <= "2024-12-31")
    ].sort_values(["buy_date", "code"]).reset_index(drop=True)
    trunc_pre = trades_trunc[
        (trades_trunc["e1_exit_date"] <= "2024-12-31") &
        (trades_trunc["e2_exit_date"] <= "2024-12-31") &
        (trades_trunc["e3_exit_date"] <= "2024-12-31")
    ].sort_values(["buy_date", "code"]).reset_index(drop=True)

    assert len(full_pre) == len(trunc_pre), f"Trunc len mismatch: {len(full_pre)} vs {len(trunc_pre)}"
    assert (full_pre["buy_date"] == trunc_pre["buy_date"]).all()
    assert (full_pre["code"] == trunc_pre["code"]).all()
    trunc_max_abs_diff = float(max(
        (full_pre["e1_gross_ret"] - trunc_pre["e1_gross_ret"]).abs().max(),
        (full_pre["e2_gross_ret"] - trunc_pre["e2_gross_ret"]).abs().max(),
        (full_pre["e3_gross_ret"] - trunc_pre["e3_gross_ret"]).abs().max(),
    ))

    # Specific check on strongest slice (amt>=20, Type2, W2[+1,+5])
    sl_f = full_pre[(full_pre["sig_amount"] >= 2e9) & full_pre["type2"] & (full_pre["buy_open_ret"] >= 0.01 - EPS) & (full_pre["buy_open_ret"] <= 0.05 + EPS)].reset_index(drop=True)
    sl_t = trunc_pre[(trunc_pre["sig_amount"] >= 2e9) & trunc_pre["type2"] & (trunc_pre["buy_open_ret"] >= 0.01 - EPS) & (trunc_pre["buy_open_ret"] <= 0.05 + EPS)].reset_index(drop=True)
    assert len(sl_f) == len(sl_t)
    slice_trunc_diff = float((sl_f["e1_gross_ret"] - sl_t["e1_gross_ret"]).abs().max()) if len(sl_f) else 0.0

    print("[5/5] Exporting summary...")
    m5_check = verify_5m_spot_check(trades_all)
    cand_m = df_matrix[df_matrix["n_5y"] >= 30].copy()
    best_eq = cand_m.sort_values("eq_ret_5y", ascending=False).head(10).to_dict("records")
    best_slot = cand_m.sort_values("slot_amt_ret_5y", ascending=False).head(10).to_dict("records")

    summary = {
        "csi300_benchmarks": {w[0]: round(csi_window_ret(csi_map, w[1], w[2]), 2) for w in WINDOWS},
        "total_signals_all_opens_10yi": int(len(trades_all)),
        "unclosed_20261120_count": int(len(open_pos)),
        "truncation_20241231_n_all": int(len(full_pre)),
        "truncation_max_abs_diff_all": trunc_max_abs_diff,
        "truncation_20241231_n_top_slice": int(len(sl_f)),
        "truncation_max_abs_diff_top_slice": slice_trunc_diff,
        "strict_dt_sensitivity_top_slice": {"normal_eq_5y": r_normal, "strict_close_dt_eq_5y": r_strict},
        "m5_spot_check": m5_check,
        "matrix_cells_n_ge_30": int(len(cand_m)),
        "cells_5y_eq_pos": int((cand_m["eq_ret_5y"] > 0).sum()),
        "cells_is_and_oos_eq_pos": int(((cand_m["is_eq_ret"] > 0) & (cand_m["oos_eq_ret"] > 0)).sum()),
        "cells_is_oos_y26_eq_pos": int(((cand_m["is_eq_ret"] > 0) & (cand_m["oos_eq_ret"] > 0) & (cand_m["y26_eq_ret"] > 0)).sum()),
        "best_10_by_eq_ret_5y": best_eq,
        "best_10_by_slot_amt_ret_5y": best_slot,
    }
    with open(f"{OUT_DIR}/summary_audit.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("DONE. trunc_all=", trunc_max_abs_diff, "trunc_slice=", slice_trunc_diff,
          "strict_dt=", (r_normal, r_strict))


if __name__ == "__main__":
    main()
