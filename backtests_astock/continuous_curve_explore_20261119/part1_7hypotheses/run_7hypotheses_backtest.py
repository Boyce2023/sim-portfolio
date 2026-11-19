#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
7 组连续曲线假说 (C1~C7) 五年严格 PIT 探索回测 (2021-11-15 ~ 2026-11-18)
严格遵循:
- 主板 00/60 含退市母体, 剔除 st_universe.json 与 price < 2.0
- 零未来函数 (PIT): 信号日在 t 收盘确定, 仅允许在 t+1 (下一市场交易日) 09:25 开盘价撮合
- 剔除一字涨停 (open >= zt_px - 0.005) 与一字跌停 (open <= dt_px + 0.005), 扣双边 30bps
- 两组无未来离场: E1 固定 T+2 收盘(T+1/T+2 涨停顺延至断板收盘), E2 破 MA5 或 T+3 收盘(一字跌停顺延)
- 同时输出 Daily Equal-Weight 与 单仓 Top1 轮动 (严格 T+1 资金不重叠: next buy_date > prev exit_date)
"""

import json
import os
import time
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from numpy.lib.stride_tricks import sliding_window_view

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
A_DAILY_PATH = f"{BASE_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{BASE_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
ST_PATH = f"{BASE_DIR}/data/st_universe.json"
IDX_PATH = f"{BASE_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
OUT_DIR = f"{BASE_DIR}/backtests_astock/continuous_curve_explore_20261119/part1_7hypotheses"
os.makedirs(OUT_DIR, exist_ok=True)

FEE_RT = 0.0030  # 双边千三 (30bps)
START_LOAD = "2021-07-01"
BT_START = "2021-11-15"
BT_END = "2026-11-18"


def load_data():
    t0 = time.time()
    with open(ST_PATH, "r", encoding="utf-8") as f:
        st_codes = set(json.load(f)["codes"])
    with open(IDX_PATH, "r", encoding="utf-8") as f:
        idx_data = json.load(f)
    csi300 = idx_data["sh000300"]

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    f_expr = (ds.field("date") >= pd.Timestamp(START_LOAD)) & (ds.field("date") <= pd.Timestamp(BT_END))
    d1 = ds.dataset(A_DAILY_PATH, format="parquet").scanner(columns=cols, filter=f_expr).to_table().to_pandas()
    d2 = ds.dataset(A_DELISTED_PATH, format="parquet").scanner(columns=cols, filter=f_expr).to_table().to_pandas()
    d1["is_delisted_src"] = 0
    d2["is_delisted_src"] = 1
    df = pd.concat([d1, d2], ignore_index=True)

    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[
        df["c6"].str.startswith(("00", "60"))
        & df["ticker"].astype(str).str.endswith((".SH", ".SZ"))
        & (~df["c6"].isin(st_codes))
    ].copy()

    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 市场交易日映射 (用于判定下一交易日是否停牌)
    all_mkt_dts = sorted(df["dt_str"].unique())
    dt_to_mkt_idx = {d: i for i, d in enumerate(all_mkt_dts)}
    df["mkt_idx"] = df["dt_str"].map(dt_to_mkt_idx).astype(np.int32)

    # 精确前复权价格 & 交易所前收基准价
    df["adjf"] = df["adj_close"] / df["close"]
    df["a_open"] = df["open"] * df["adjf"]
    df["a_high"] = df["high"] * df["adjf"]
    df["a_low"] = df["low"] * df["adjf"]
    df["a_close"] = df["adj_close"]

    g = df.groupby("c6", sort=False)
    df["prev_a_close"] = g["a_close"].shift(1)
    df["prevc"] = df["prev_a_close"] / df["adjf"]
    df["ret"] = df["a_close"] / df["prev_a_close"] - 1.0
    df["open_gap"] = df["open"] / df["prevc"] - 1.0
    df["high_pct"] = df["high"] / df["prevc"] - 1.0
    df["amp"] = (df["high"] - df["low"]) / df["prevc"]

    df["zt_px"] = np.floor(df["prevc"] * 1.10 * 100.0 + 0.5 + 1e-9) / 100.0
    df["dt_px"] = np.floor(df["prevc"] * 0.90 * 100.0 + 0.5 + 1e-9) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.005) & (df["ret"] >= 0.095) & df["prevc"].notna()
    df["is_dt"] = (df["close"] <= df["dt_px"] + 0.005) & (df["ret"] <= -0.095) & df["prevc"].notna()
    df["touch_zt"] = (df["high"] >= df["zt_px"] - 0.005) & (df["high_pct"] >= 0.095) & df["prevc"].notna()
    df["is_yizi_dt"] = df["is_dt"] & (df["high"] <= df["dt_px"] + 0.005)

    df["mcap_yi"] = np.where(
        df["oshare"].notna() & (df["oshare"] > 0),
        df["close"] * df["oshare"] / 1e8,
        np.where(df["turn"] > 0, df["close"] * (df["volume"] / df["turn"]) / 1e8, np.nan),
    )

    # 市场每日情绪特征 (纯 PIT, 仅用到当日收盘)
    mkt_zt = df.groupby("dt_str")["is_zt"].sum().to_dict()
    mkt_dt = df.groupby("dt_str")["is_dt"].sum().to_dict()

    # CSI300 趋势 (当日是否 >= MA20)
    s300_dts = sorted(csi300.keys())
    s300_vals = np.array([csi300[d] for d in s300_dts], dtype=float)
    s300_ma20 = pd.Series(s300_vals).rolling(20).mean().to_numpy()
    csi_above_ma20 = {d: (s300_vals[i] >= s300_ma20[i]) if not np.isnan(s300_ma20[i]) else True for i, d in enumerate(s300_dts)}

    print(f"[load] rows={len(df):,}, stocks={df['c6'].nunique()}, elapsed={time.time()-t0:.1f}s")
    return df, all_mkt_dts, mkt_zt, mkt_dt, csi_above_ma20, csi300


def compute_features_and_signals(df: pd.DataFrame, mkt_zt: dict, mkt_dt: dict, csi_above_ma20: dict):
    """按个股分组向量化计算全部曲线特征并生成 C1~C7 信号索引。"""
    t0 = time.time()
    n = len(df)
    c6_arr = df["c6"].to_numpy()
    splits = np.flatnonzero(c6_arr[1:] != c6_arr[:-1]) + 1
    bounds = np.concatenate(([0], splits, [n]))

    # 预分配全局特征列以供后续排序/过滤
    ma5_all = np.full(n, np.nan)
    ma10_all = np.full(n, np.nan)
    ma20_all = np.full(n, np.nan)
    ret10_all = np.full(n, np.nan)
    ret10_prev_all = np.full(n, np.nan)
    er10_all = np.full(n, np.nan)
    er15_prev_all = np.full(n, np.nan)
    pos60_all = np.full(n, np.nan)
    max_streak10_prev_all = np.zeros(n, dtype=np.int32)
    streak_prev_all = np.zeros(n, dtype=np.int32)

    sig_masks = {f"C{i}": np.zeros(n, dtype=bool) for i in range(1, 8)}
    sig_strength = {f"C{i}": np.zeros(n, dtype=np.float64) for i in range(1, 8)}

    # 提取数组加速
    a_close = df["a_close"].to_numpy()
    a_high = df["a_high"].to_numpy()
    a_low = df["a_low"].to_numpy()
    close_u = df["close"].to_numpy()
    open_u = df["open"].to_numpy()
    high_u = df["high"].to_numpy()
    prevc = df["prevc"].to_numpy()
    ret = df["ret"].to_numpy()
    amp = df["amp"].to_numpy()
    vol = df["volume"].to_numpy()
    turn = df["turn"].to_numpy()
    is_zt = df["is_zt"].to_numpy()
    is_dt = df["is_dt"].to_numpy()
    touch_zt = df["touch_zt"].to_numpy()

    def roll_mean(x, w):
        bad = ~np.isfinite(x)
        x0 = np.where(bad, 0.0, x)
        cs = np.cumsum(np.insert(x0, 0, 0.0))
        bc = np.cumsum(np.insert(bad.astype(np.int32), 0, 0))
        out = np.full(len(x), np.nan, dtype=np.float64)
        valid_w = (bc[w:] - bc[:-w]) == 0
        out[w - 1:] = np.where(valid_w, (cs[w:] - cs[:-w]) / w, np.nan)
        return out

    def roll_sum(x, w):
        bad = ~np.isfinite(x)
        x0 = np.where(bad, 0.0, x)
        cs = np.cumsum(np.insert(x0, 0, 0.0))
        bc = np.cumsum(np.insert(bad.astype(np.int32), 0, 0))
        out = np.full(len(x), np.nan, dtype=np.float64)
        valid_w = (bc[w:] - bc[:-w]) == 0
        out[w - 1:] = np.where(valid_w, cs[w:] - cs[:-w], np.nan)
        return out

    for s_idx in range(len(bounds) - 1):
        a, b = bounds[s_idx], bounds[s_idx + 1]
        m = b - a
        if m < 65:
            continue

        ac = a_close[a:b]
        ah = a_high[a:b]
        al = a_low[a:b]
        cu = close_u[a:b]
        ou = open_u[a:b]
        hu = high_u[a:b]
        pc = prevc[a:b]
        r = ret[a:b]
        am = amp[a:b]
        v = vol[a:b]
        tu = turn[a:b]
        zt = is_zt[a:b]
        dt = is_dt[a:b]
        tzt = touch_zt[a:b]

        ma5 = roll_mean(ac, 5)
        ma10 = roll_mean(ac, 10)
        ma20 = roll_mean(ac, 20)
        ma5_all[a:b] = ma5
        ma10_all[a:b] = ma10
        ma20_all[a:b] = ma20

        # 涨停连板数 streak
        st = np.zeros(m, dtype=np.int32)
        cur = 0
        for i in range(m):
            if zt[i]:
                cur += 1
            else:
                cur = 0
            st[i] = cur
        st_prev = np.empty(m, dtype=np.int32); st_prev[0] = 0; st_prev[1:] = st[:-1]
        streak_prev_all[a:b] = st_prev

        # shift helpers
        ac_s1 = np.empty(m); ac_s1[0] = np.nan; ac_s1[1:] = ac[:-1]
        ac_s10 = np.empty(m); ac_s10[:10] = np.nan; ac_s10[10:] = ac[:-10]
        ac_s11 = np.empty(m); ac_s11[:11] = np.nan; ac_s11[11:] = ac[:-11]
        ac_s16 = np.empty(m); ac_s16[:16] = np.nan; ac_s16[16:] = ac[:-16]
        r_s1 = np.empty(m); r_s1[0] = np.nan; r_s1[1:] = r[:-1]
        zt_s1 = np.zeros(m, dtype=bool); zt_s1[1:] = zt[:-1]
        ma5_s1 = np.empty(m); ma5_s1[0] = np.nan; ma5_s1[1:] = ma5[:-1]
        ma10_s1 = np.empty(m); ma10_s1[0] = np.nan; ma10_s1[1:] = ma10[:-1]
        ma20_s1 = np.empty(m); ma20_s1[0] = np.nan; ma20_s1[1:] = ma20[:-1]

        ret10 = ac / ac_s10 - 1.0
        ret10_p = ac_s1 / ac_s11 - 1.0
        ret10_all[a:b] = ret10
        ret10_prev_all[a:b] = ret10_p

        abs_dc = np.abs(ac - ac_s1)
        abs_dc[0] = 0.0
        sum_dc10 = roll_sum(abs_dc, 10)
        er10 = np.abs(ac - ac_s10) / (sum_dc10 + 1e-12)
        er10_p = np.empty(m); er10_p[0] = np.nan; er10_p[1:] = er10[:-1]
        er10_all[a:b] = er10

        sum_dc15 = roll_sum(abs_dc, 15)
        er15 = np.abs(ac - np.concatenate((np.full(15, np.nan), ac[:-15]))) / (sum_dc15 + 1e-12)
        er15_p = np.empty(m); er15_p[0] = np.nan; er15_p[1:] = er15[:-1]
        er15_prev_all[a:b] = er15_p

        # vol_ma5_prev: mean of [t-5..t-1]
        v_ma5 = roll_mean(v, 5)
        v_ma5_p = np.empty(m); v_ma5_p[0] = np.nan; v_ma5_p[1:] = v_ma5[:-1]
        v_ma20 = roll_mean(v, 20)
        v_ma20_pre5 = np.empty(m); v_ma20_pre5[:6] = np.nan; v_ma20_pre5[6:] = v_ma20[:-6]
        v_ma3 = roll_mean(v, 3)
        v_ma3_p = np.empty(m); v_ma3_p[0] = np.nan; v_ma3_p[1:] = v_ma3[:-1]
        v_ma20_pre3 = np.empty(m); v_ma20_pre3[:4] = np.nan; v_ma20_pre3[4:] = v_ma20[:-4]

        am_ma5 = roll_mean(am, 5)
        am_ma5_p = np.empty(m); am_ma5_p[0] = np.nan; am_ma5_p[1:] = am_ma5[:-1]

        # sliding windows for exact lookbacks
        # 10d prev windows (ending at t-1, so shift 1)
        w10_r_p = np.full((m, 10), np.nan)
        w10_cu_p = np.full((m, 10), np.nan)
        w10_ou_p = np.full((m, 10), np.nan)
        w10_ac_p = np.full((m, 10), np.nan)
        w10_zt_p = np.zeros((m, 10), dtype=np.int32)
        w10_dt_p = np.zeros((m, 10), dtype=np.int32)
        w10_st_p = np.zeros((m, 10), dtype=np.int32)

        w10_r_p[10:] = sliding_window_view(r[:-1], 10)
        w10_cu_p[10:] = sliding_window_view(cu[:-1], 10)
        w10_ou_p[10:] = sliding_window_view(ou[:-1], 10)
        w10_ac_p[10:] = sliding_window_view(ac[:-1], 10)
        w10_zt_p[10:] = sliding_window_view(zt[:-1].astype(np.int32), 10)
        w10_dt_p[10:] = sliding_window_view(dt[:-1].astype(np.int32), 10)
        w10_st_p[10:] = sliding_window_view(st[:-1], 10)

        zt_cnt_10_p = w10_zt_p.sum(axis=1)
        dt_cnt_10_p = w10_dt_p.sum(axis=1)
        dt_cnt_10_inc = dt_cnt_10_p + dt.astype(np.int32)
        max_st10_p = w10_st_p.max(axis=1)
        max_streak10_prev_all[a:b] = max_st10_p
        min_r10_p = w10_r_p.min(axis=1)
        max_r10_p = w10_r_p.max(axis=1)
        max_ac10_p = w10_ac_p.max(axis=1)

        # 近 3 日是否有阴线回踩 (用于 "首次回踩")
        had_yin_3d = ((w10_r_p[:, -3:] <= -0.01) & (w10_cu_p[:, -3:] < w10_ou_p[:, -3:])).any(axis=1)

        # 60d prev high/low
        w60_ac_p = np.full((m, 60), np.nan)
        w60_ac_p[60:] = sliding_window_view(ac[:-1], 60)
        max_ac60_p = w60_ac_p.max(axis=1)
        min_ac60_p = w60_ac_p.min(axis=1)
        pos60 = (ac - min_ac60_p) / (max_ac60_p - min_ac60_p + 1e-12)
        pos60_all[a:b] = pos60

        # 5d prev check: all [t-5..t-1] ac >= ma20
        w5_ac_p = w10_ac_p[:, -5:]
        w5_ma20_p = np.full((m, 5), np.nan)
        w5_ma20_p[5:] = sliding_window_view(ma20[:-1], 5)
        hold_ma20_5d = (w5_ac_p >= w5_ma20_p).all(axis=1)

        # C5 wave_gain in [t-35..t-6] (30 days before the 5d tight base)
        wave_gain_35_6 = np.full(m, np.nan)
        max_ac_35_6 = np.full(m, np.nan)
        if m >= 36:
            w30 = sliding_window_view(ac[:-6], 30)  # len = m - 6 - 30 + 1 = m - 35
            run_min = np.minimum.accumulate(w30, axis=1)
            wg = np.max(w30 / run_min - 1.0, axis=1)
            wave_gain_35_6[35:] = wg
            max_ac_35_6[35:] = np.max(w30, axis=1)

        # C6 N-wave: in [t-30..t-1] peak and prior trough and pullback
        c6_wave_ok = np.zeros(m, dtype=bool)
        c6_wave_gain = np.zeros(m, dtype=np.float64)
        if m >= 36:
            w30_n = sliding_window_view(ac[:-1], 30)  # [t-30..t-1], starts at t=30
            w5_al_p = sliding_window_view(al[:-1], 5)  # starts at t=5
            for t_i in range(35, m):
                seg = ac[t_i - 30 : t_i]
                p_rel = int(np.argmax(seg))
                if p_rel < 3 or p_rel > 27:  # 峰距 t 至少 2 日回撤且峰前至少 3 日
                    continue
                p_abs = t_i - 30 + p_rel
                peak_px = ac[p_abs]
                trough_px = np.min(ac[t_i - 35 : p_abs])
                gain = peak_px / trough_px - 1.0
                if gain < 0.35:
                    continue
                min_after = np.min(ac[p_abs + 1 : t_i])
                dd_max = 1.0 - min_after / peak_px
                dd_yest = 1.0 - ac[t_i - 1] / peak_px
                if not (0.12 <= dd_max <= 0.28 and 0.10 <= dd_yest <= 0.28):
                    continue
                # 回踩 MA20 附近
                m20_y = ma20[t_i - 1]
                if np.isnan(m20_y) or np.min(al[t_i - 5 : t_i]) > m20_y * 1.04 or ac[t_i - 1] < m20_y * 0.93:
                    continue
                c6_wave_ok[t_i] = True
                c6_wave_gain[t_i] = gain

        valid = (np.arange(m) >= 60) & (cu >= 2.0) & (v > 0) & np.isfinite(pc) & np.isfinite(ma20)

        # ---- C1: 趋势加速首阴反包（跌阴）----
        # ret10_p in [28%, 75%] 且 ret10 <= 75%, ER10 >= 0.45, 首次回踩阴线(C<O, -8%~-1%, C>MA10)
        c1 = (
            valid
            & (ret10_p >= 0.28) & (ret10_p <= 0.75) & (ret10 <= 0.75)
            & (er10 >= 0.45) & (ac > ac_s10)
            & (cu < ou) & (r >= -0.08) & (r <= -0.01)
            & (ac > ma10)
            & (r_s1 > 0) & (~had_yin_3d)
        )
        sig_masks["C1"][a:b] = c1
        sig_strength["C1"][a:b] = ret10_p * 100.0 + er10 * 30.0

        # ---- C2: 趋势加速首阴真阳承接（剔除纯>=4连板）----
        c2 = (
            valid
            & (ret10_p >= 0.28) & (ret10_p <= 0.75) & (ret10 <= 0.75)
            & (zt_cnt_10_p >= 1) & (max_st10_p < 4) & (st_prev < 4)
            & (~zt) & (cu > ou) & (tu <= 0.35)
            & ((zt_s1 & (~zt)) | ((r < 0) & (r_s1 >= 0) & (~had_yin_3d)))
        )
        sig_masks["C2"][a:b] = c2
        sig_strength["C2"][a:b] = ret10_p * 100.0 + (cu / ou - 1.0) * 100.0

        # ---- C3: 趋势主升炸板/长上影分歧弱转强 ----
        c3 = (
            valid
            & (ac > ma5) & (ma5 > ma10) & (ma10 > ma20)
            & (ret10 >= 0.12) & (ret10 <= 0.45)
            & (((hu / pc - 1.0 >= 0.07) & ((hu - cu) / pc >= 0.03)) | (tzt & (~zt)))
        )
        sig_masks["C3"][a:b] = c3
        sig_strength["C3"][a:b] = ret10 * 100.0 + (hu - cu) / pc * 100.0

        # ---- C4: 趋势多头缩量洗盘阴线次日高开反包 ----
        c4 = (
            valid
            & (ma5 > ma10) & (ma10 > ma20)
            & (ret10_p >= 0.12) & (ret10_p <= 0.45)
            & (dt_cnt_10_inc == 0)
            & (v < 0.85 * v_ma5_p)
            & (cu < ou) & (r >= -0.07) & (r <= -0.02)
            & (ac >= ma10) & (r_s1 >= -0.01)
        )
        sig_masks["C4"][a:b] = c4
        sig_strength["C4"][a:b] = ret10_p * 100.0 + (1.0 - v / (v_ma5_p + 1e-9)) * 30.0

        # ---- C5: 高位 VCP 紧致压缩平台放量破局 ----
        c5 = (
            valid
            & (wave_gain_35_6 >= 0.30)
            & (ac_s1 >= 0.80 * max_ac_35_6)
            & (am_ma5_p < 0.05)
            & (v_ma5_p < 0.65 * v_ma20_pre5)
            & hold_ma20_5d
            & (r >= 0.05) & (cu >= ou)
            & (v >= 1.5 * v_ma5_p)
            & (ac > max_ac10_p)
        )
        sig_masks["C5"][a:b] = c5
        sig_strength["C5"][a:b] = wave_gain_35_6 * 50.0 + (v / (v_ma5_p + 1e-9)) * 10.0

        # ---- C6: N字二波回归（缩量深蹲回踩 MA20 后首阳反包）----
        c6_sig = (
            valid
            & c6_wave_ok
            & (v_ma3_p < 0.75 * v_ma20_pre3)
            & (r >= 0.05) & (cu > ou)
            & (v >= 1.3 * v_ma5_p)
            & (ac > ma5) & (ac_s1 <= ma5_s1)
        )
        sig_masks["C6"][a:b] = c6_sig
        sig_strength["C6"][a:b] = c6_wave_gain * 50.0 + (v / (v_ma5_p + 1e-9)) * 10.0

        # ---- C7: 平滑慢牛沿 MA5 陡峭加速（高效率低波趋势首突）----
        c7 = (
            valid
            & (er15_p >= 0.55) & (ac_s1 > ac_s16)
            & (ma5 > ma10) & (ma10 > ma20)
            & (dt_cnt_10_p == 0) & (min_r10_p > -0.04) & (max_r10_p < 0.07)
            & (r >= 0.07)
            & (v >= 1.3 * v_ma5_p)
            & (ac > max_ac60_p)
        )
        sig_masks["C7"][a:b] = c7
        sig_strength["C7"][a:b] = er15_p * 50.0 + (v / (v_ma5_p + 1e-9)) * 10.0

    df["ma5"] = ma5_all
    df["ma10"] = ma10_all
    df["ma20"] = ma20_all
    df["ret10"] = ret10_all
    df["ret10_prev"] = ret10_prev_all
    df["er10"] = er10_all
    df["er15_prev"] = er15_prev_all
    df["pos60"] = pos60_all
    df["max_st10_prev"] = max_streak10_prev_all
    df["st_prev"] = streak_prev_all
    df["mkt_zt"] = df["dt_str"].map(mkt_zt).fillna(0).astype(int)
    df["mkt_dt"] = df["dt_str"].map(mkt_dt).fillna(0).astype(int)
    df["csi_ok"] = df["dt_str"].map(csi_above_ma20).fillna(True).astype(bool)

    print(f"[features] elapsed={time.time()-t0:.1f}s")
    for k, msk in sig_masks.items():
        print(f"  raw signal_day count {k}: {int(msk.sum()):,}")
    return sig_masks, sig_strength


# 买入开盘区间定义 (min_gap, max_gap)
OPEN_BOUNDS = {
    "C1": (0.005, 0.050),
    "C2": (-0.045, 0.045),
    "C3": (0.015, 0.065),
    "C4": (0.010, 0.050),
    "C5": (0.010, 0.060),
    "C6": (0.010, 0.060),
    "C7": (0.015, 0.065),
}


def extract_trades(df: pd.DataFrame, sig_masks: dict, sig_strength: dict):
    """按严格 PIT 次日 09:25 撮合并模拟 E1/E2 两条无未来函数离场路径。"""
    t0 = time.time()
    c6 = df["c6"].to_numpy()
    dt_str = df["dt_str"].to_numpy()
    mkt_idx = df["mkt_idx"].to_numpy()
    open_u = df["open"].to_numpy()
    close_u = df["close"].to_numpy()
    high_u = df["high"].to_numpy()
    adjf = df["adjf"].to_numpy()
    a_close = df["a_close"].to_numpy()
    ma5 = df["ma5"].to_numpy()
    zt_px = df["zt_px"].to_numpy()
    dt_px = df["dt_px"].to_numpy()
    open_gap = df["open_gap"].to_numpy()
    vol = df["volume"].to_numpy()
    is_zt = df["is_zt"].to_numpy()
    is_yizi_dt = df["is_yizi_dt"].to_numpy()
    mcap_yi = df["mcap_yi"].to_numpy()
    turn = df["turn"].to_numpy()
    pos60 = df["pos60"].to_numpy()
    mkt_zt = df["mkt_zt"].to_numpy()
    mkt_dt = df["mkt_dt"].to_numpy()
    csi_ok = df["csi_ok"].to_numpy()
    max_st10 = df["max_st10_prev"].to_numpy()
    st_prev = df["st_prev"].to_numpy()
    is_del = df["is_delisted_src"].to_numpy()

    # 构建每只股票结束位置表，防止滑出个股边界
    n = len(df)
    splits = np.flatnonzero(c6[1:] != c6[:-1]) + 1
    stock_end = np.empty(n, dtype=np.int32)
    prev_s = 0
    for sp in np.append(splits, n):
        stock_end[prev_s:sp] = sp
        prev_s = sp

    all_ledgers = {}
    for hname, msk in sig_masks.items():
        lo_gap, hi_gap = OPEN_BOUNDS[hname]
        strength = sig_strength[hname]
        idxs = np.flatnonzero(msk)
        rows = []
        for idx in idxs:
            s_end = stock_end[idx]
            buy_idx = idx + 1
            if buy_idx >= s_end:
                continue
            # 必须为下一市场交易日 (停牌不可买), 且需有至少 T+1 交易日
            if mkt_idx[buy_idx] != mkt_idx[idx] + 1:
                continue
            b_dt = dt_str[buy_idx]
            if b_dt < BT_START or b_dt > "2026-11-17":
                continue
            if buy_idx + 1 >= s_end:
                continue
            # 价格 >= 2 元 & 成交量 > 0 & 非一字涨跌停
            if open_u[buy_idx] < 2.0 or vol[buy_idx] <= 0:
                continue
            if open_u[buy_idx] >= zt_px[buy_idx] - 0.005 or open_u[buy_idx] <= dt_px[buy_idx] + 0.005:
                continue
            g_open = open_gap[buy_idx]
            if not (lo_gap <= g_open <= hi_gap):
                continue

            buy_px_adj = open_u[buy_idx] * adjf[buy_idx]

            # --- 离场 E1: 固定 T+2 收盘 (k=2, 若 T+1 封涨停或 k>=2 封涨停则顺延至断板收盘; 一字跌停顺延) ---
            t1_idx = buy_idx + 1
            t1_zt = bool(is_zt[t1_idx]) if t1_idx < s_end else False
            e1_idx = None
            k = 2
            # 若 buy_idx + 2 超出样本 (如 2026-11-17 买, 2026-11-18 为 T+1), 用最后一个可行日
            if buy_idx + 2 >= s_end:
                # 若是 2026-11-17 买无法完整观测 T+2, 跳过以免截断缩短持仓期
                if dt_str[s_end - 1] >= "2026-11-18":
                    continue
                e1_idx = s_end - 1
            else:
                while buy_idx + k < s_end:
                    c_i = buy_idx + k
                    if vol[c_i] <= 0:
                        k += 1
                        continue
                    if is_yizi_dt[c_i]:
                        k += 1
                        continue
                    if is_zt[c_i]:
                        k += 1
                        continue
                    e1_idx = c_i
                    break
                if e1_idx is None:
                    e1_idx = s_end - 1

            ret_e1 = (close_u[e1_idx] * adjf[e1_idx]) / buy_px_adj - 1.0 - FEE_RT

            # --- 离场 E2: T+1 起收盘破 MA5 或 T+3 收盘止盈/止损 (一字跌停顺延) ---
            e2_idx = None
            k2 = 1
            while buy_idx + k2 < s_end:
                c_i = buy_idx + k2
                if vol[c_i] <= 0 or is_yizi_dt[c_i]:
                    k2 += 1
                    continue
                if a_close[c_i] < ma5[c_i] or (k2 >= 3 and not is_zt[c_i]):
                    e2_idx = c_i
                    break
                k2 += 1
            if e2_idx is None:
                e2_idx = s_end - 1

            ret_e2 = (close_u[e2_idx] * adjf[e2_idx]) / buy_px_adj - 1.0 - FEE_RT

            # 综合排名分 (纯信号日趋势强度 + 合理换手 + 60日低位加成, 零未来)
            rk_score = float(strength[idx]) - max(turn[idx] - 0.15, 0.0) * 100.0 - (pos60[idx] if np.isfinite(pos60[idx]) else 0.5) * 15.0

            rows.append({
                "sig_date": dt_str[idx],
                "buy_date": b_dt,
                "exit_date_e1": dt_str[e1_idx],
                "exit_date_e2": dt_str[e2_idx],
                "c6": c6[idx],
                "open_gap": round(float(g_open), 5),
                "ret_e1": float(ret_e1),
                "ret_e2": float(ret_e2),
                "hold_e1": int(e1_idx - buy_idx),
                "hold_e2": int(e2_idx - buy_idx),
                "rank_score": rk_score,
                "mcap_yi": float(mcap_yi[idx]) if np.isfinite(mcap_yi[idx]) else np.nan,
                "turn_sig": float(turn[idx]),
                "pos60": float(pos60[idx]) if np.isfinite(pos60[idx]) else 0.5,
                "mkt_zt": int(mkt_zt[idx]),
                "mkt_dt": int(mkt_dt[idx]),
                "csi_ok": bool(csi_ok[idx]),
                "had_zt_10": int(max_st10[idx] > 0 or is_zt[idx]),
                "max_st10": int(max(max_st10[idx], st_prev[idx] + (1 if is_zt[idx] else 0))),
                "is_delisted": int(is_del[idx]),
            })
        ldf = pd.DataFrame(rows)
        if not ldf.empty:
            ldf.sort_values(["buy_date", "rank_score"], ascending=[True, False], inplace=True)
            ldf.reset_index(drop=True, inplace=True)
        all_ledgers[hname] = ldf
        print(f"  [trades] {hname}: {len(ldf):,} filled trades")
    print(f"[extract_trades] elapsed={time.time()-t0:.1f}s")
    return all_ledgers


def run_1slot(df: pd.DataFrame, exit_col: str, ret_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    df_s = df.sort_values(["buy_date", "rank_score", "c6"], ascending=[True, False, True])
    picked = []
    cur_exit = ""
    for r in df_s.itertuples(index=False):
        if not cur_exit or r.buy_date > cur_exit:
            picked.append(r._asdict())
            cur_exit = getattr(r, exit_col)
    return pd.DataFrame(picked)


def csi_window_ret(csi300: dict, start_prev: str, end_dt: str) -> float:
    ks = sorted(csi300.keys())
    k0 = max(k for k in ks if k <= start_prev)
    k1 = max(k for k in ks if k <= end_dt)
    return (csi300[k1] / csi300[k0] - 1.0) * 100.0


def eval_window(df_all: pd.DataFrame, df_slot: pd.DataFrame, ret_col: str, d_lo: str, d_hi: str, csi_pct: float) -> dict:
    sub_a = df_all[(df_all["buy_date"] >= d_lo) & (df_all["buy_date"] <= d_hi)] if not df_all.empty else df_all
    sub_s = df_slot[(df_slot["buy_date"] >= d_lo) & (df_slot["buy_date"] <= d_hi)] if not df_slot.empty else df_slot

    # Daily Equal-Weight
    if len(sub_a) > 0:
        day_means = sub_a.groupby("buy_date")[ret_col].mean().sort_index().to_numpy()
        n_days = len(day_means)
        ew_avg_bps = float(np.mean(day_means) * 10000.0)
        ew_wr = float(np.mean(day_means > 0) * 100.0)
        ew_w = day_means[day_means > 0]
        ew_l = day_means[day_means <= 0]
        ew_plr = float(ew_w.mean() / abs(ew_l.mean())) if (len(ew_w) > 0 and len(ew_l) > 0 and ew_l.mean() < 0) else (9.99 if len(ew_w) > 0 else 0.0)
        ew_curve = np.cumprod(1.0 + day_means)
        ew_peaks = np.maximum.accumulate(np.insert(ew_curve, 0, 1.0))[1:]
        ew_mdd = float(np.max((ew_peaks - ew_curve) / ew_peaks) * 100.0)
        ew_nav = float(ew_curve[-1])
        ew_ret_pct = (ew_nav - 1.0) * 100.0
        ew_tstat = float(np.mean(day_means) / (np.std(day_means, ddof=1) / np.sqrt(n_days) + 1e-12)) if n_days > 1 else 0.0
    else:
        n_days = 0; ew_avg_bps = 0.0; ew_wr = 0.0; ew_plr = 0.0; ew_mdd = 0.0; ew_nav = 1.0; ew_ret_pct = 0.0; ew_tstat = 0.0

    # 1-Slot Top1 Rotation
    n_s = len(sub_s)
    if n_s > 0:
        sr = sub_s[ret_col].to_numpy()
        sw = sr[sr > 0]
        sl = sr[sr <= 0]
        s_avg_bps = float(np.mean(sr) * 10000.0)
        s_wr = float(len(sw) / n_s * 100.0)
        s_plr = float(sw.mean() / abs(sl.mean())) if (len(sw) > 0 and len(sl) > 0 and sl.mean() < 0) else (9.99 if len(sw) > 0 else 0.0)
        s_curve = np.cumprod(1.0 + sr)
        s_peaks = np.maximum.accumulate(np.insert(s_curve, 0, 1.0))[1:]
        s_mdd = float(np.max((s_peaks - s_curve) / s_peaks) * 100.0)
        s_nav = float(s_curve[-1])
        s_ret_pct = (s_nav - 1.0) * 100.0
    else:
        s_avg_bps = 0.0; s_wr = 0.0; s_plr = 0.0; s_mdd = 0.0; s_nav = 1.0; s_ret_pct = 0.0

    return {
        "n_all": int(len(sub_a)),
        "ew_days": int(n_days),
        "ew_bps": round(ew_avg_bps, 1),
        "ew_t": round(ew_tstat, 2),
        "ew_wr": round(ew_wr, 1),
        "ew_plr": round(ew_plr, 2),
        "ew_nav": round(ew_nav, 3),
        "ew_ret_pct": round(ew_ret_pct, 1),
        "ew_mdd": round(ew_mdd, 1),
        "ew_ex_pp": round(ew_ret_pct - csi_pct, 1),
        "n_slot": int(n_s),
        "slot_bps": round(s_avg_bps, 1),
        "slot_wr": round(s_wr, 1),
        "slot_plr": round(s_plr, 2),
        "slot_nav": round(s_nav, 3),
        "slot_ret_pct": round(s_ret_pct, 1),
        "slot_mdd": round(s_mdd, 1),
        "slot_ex_pp": round(s_ret_pct - csi_pct, 1),
        "csi300_pct": round(csi_pct, 2),
    }


def main():
    df, all_mkt_dts, mkt_zt, mkt_dt, csi_above_ma20, csi300 = load_data()
    sig_masks, sig_strength = compute_features_and_signals(df, mkt_zt, mkt_dt, csi_above_ma20)
    ledgers = extract_trades(df, sig_masks, sig_strength)

    windows = [
        ("5Y", "2021-11-15", "2026-11-18", csi_window_ret(csi300, "2021-11-15", "2026-11-18")),
        ("IS_21_23", "2021-11-15", "2023-12-29", csi_window_ret(csi300, "2021-11-15", "2023-12-29")),
        ("OOS_24_26", "2024-01-01", "2026-11-18", csi_window_ret(csi300, "2023-12-29", "2026-11-18")),
        ("3Y", "2023-11-16", "2026-11-18", csi_window_ret(csi300, "2023-11-15", "2026-11-18")),
        ("2026", "2026-01-01", "2026-11-18", csi_window_ret(csi300, "2025-12-31", "2026-11-18")),
    ]

    summary = {"windows_csi300": {w[0]: round(w[3], 2) for w in windows}, "results": {}}

    for hname, ldf in ledgers.items():
        ldf.to_csv(f"{OUT_DIR}/ledger_{hname}_raw.csv", index=False)
        res_h = {}
        for exit_tag, e_col, r_col in [("E1_T2", "exit_date_e1", "ret_e1"), ("E2_MA5_T3", "exit_date_e2", "ret_e2")]:
            slot_df = run_1slot(ldf, e_col, r_col)
            w_res = {}
            for wname, d0, d1, csi_pct in windows:
                w_res[wname] = eval_window(ldf, slot_df, r_col, d0, d1, csi_pct)
            # Yearly breakdown on EW and 1-slot
            yr_res = {}
            for yr in ["2022", "2023", "2024", "2025", "2026"]:
                yr_res[yr] = eval_window(ldf, slot_df, r_col, f"{yr}-01-01", f"{yr}-12-31", 0.0)
            res_h[exit_tag] = {"windows": w_res, "years": yr_res}
        summary["results"][hname] = res_h

    with open(f"{OUT_DIR}/summary_raw_7hypotheses.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # 打印精炼对比表 (<=3KB)
    print("\n=== CSI300 BENCHMARKS ===", summary["windows_csi300"])
    for exit_tag in ["E1_T2", "E2_MA5_T3"]:
        print(f"\n=== {exit_tag} RAW BASELINE (30bps RT) ===")
        hdr = f"{'Hyp':<4} {'nAll':>5} {'ew_5Y_bps':>9} {'ew_t':>5} {'IS_bps':>7} {'OOS_bps':>8} {'26_bps':>7} | {'s_5Y':>5} {'sWR':>5} {'sPLR':>5} {'sNAV':>6} {'sMDD':>5} {'s3Y_NAV':>7} {'s26_NAV':>7}"
        print(hdr)
        for hname in [f"C{i}" for i in range(1, 8)]:
            w = summary["results"][hname][exit_tag]["windows"]
            w5, wis, woos, w3, w26 = w["5Y"], w["IS_21_23"], w["OOS_24_26"], w["3Y"], w["2026"]
            print(
                f"{hname:<4} {w5['n_all']:>5} {w5['ew_bps']:>9.1f} {w5['ew_t']:>5.2f} "
                f"{wis['ew_bps']:>7.1f} {woos['ew_bps']:>8.1f} {w26['ew_bps']:>7.1f} | "
                f"{w5['n_slot']:>5} {w5['slot_wr']:>5.1f} {w5['slot_plr']:>5.2f} "
                f"{w5['slot_nav']:>6.2f} {w5['slot_mdd']:>5.1f} {w3['slot_nav']:>7.2f} {w26['slot_nav']:>7.2f}"
            )


if __name__ == "__main__":
    main()
