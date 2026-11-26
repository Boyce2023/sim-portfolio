#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-5 Track E: US Brainwave #3 — Low-Correlation Broad / Dividend / Gold ETF &
Large-Cap High-Dividend Low-Vol Forced-Selling Rebound on V20.0 Retreat / Empty-Streak Days.
Evaluates:
  - ETF Pool (0.05% RT fee): Broad + Dividend (510880/512890/512800) + Gold (518880)
  - Gold+Dividend Defensive Core ETF Pool (0.05% RT fee): 518880/510880/512890/512800/510050/510300
  - High-Dividend Low-Vol Large-Cap + Gold Stock Pool (0.30% RT fee)
  - Strict exit_date < t WF Scorecard Mode A, V20 Empty-Slot Patch (Fixed + YieldToV20),
    V20 daily return correlation (< 0.2 check), combined MDD compression, and 2024-12-31 truncation proof.
Zero yfinance (D12). Zero cap10m. Single-thread, RAM < 2 GB.
"""
import gc
import json
import os
import resource
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b5_common as wc

ETF_FEE_RT = 0.0005  # 0.05% round-trip for ETFs
STK_FEE_RT = 0.0030  # 0.30% round-trip for A-share stocks
STOCK_CORE_PQ = f"{wc.WAVE1_DIR}/stock_day_core_features_pit.parquet"
MKT_PIT_PQ = f"{wc.WAVE1_DIR}/market_daily_all_new_factors_pit.parquet"
FHPS_PQ = f"{wc.SIM}/backtests_astock2/china_policy_macro_rd027/raw_cache/stock_fhps_em_all.parquet"
GOLD_CORE = {"600547", "600489", "600988", "000975", "002155"}
BANK_BIG4 = {"601398", "601288", "601988", "601939"}


def _prepare_etf_candidates(etf_df: pd.DataFrame, mkt_df: pd.DataFrame, v20_ctx: dict) -> tuple[pd.DataFrame, dict]:
    """Compute strictly T-1 oversold, panic-then-shrink-stop, overnight anchor, and retreat context for ETFs."""
    # Exclude pure Treasury bond ETF 511010 from equity/gold rebound pool (keep 10 equity+gold ETFs)
    sub = etf_df[etf_df["code"] != "511010"].copy().sort_values(["code", "date"]).reset_index(drop=True)
    px_lu = {}
    for r in sub[["code", "date", "open", "close"]].itertuples(index=False, name=None):
        px_lu[(str(r[0]).zfill(6), str(r[1])[:10])] = (float(r[2]), float(r[3]))

    # Strictly causal prior V20 empty streak (from calendar <= t-1!)
    cal_ext = v20_ctx["calendar_ext"][["trade_date", "prior_empty_streak_len"]].copy()
    cal_ext = cal_ext.rename(columns={"trade_date": "date", "prior_empty_streak_len": "v20_prior_empty_streak"})

    feats = []
    for code, g in sub.groupby("code", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        c = g["close"].to_numpy(float)
        o = g["open"].to_numpy(float)
        h = g["high"].to_numpy(float)
        l = g["low"].to_numpy(float)
        v = g["volume"].to_numpy(float)
        n = len(g)

        r1 = pd.Series(c).pct_change().to_numpy(float)
        # Strictly T-1 values (at index i, we only know bars <= i-1 plus open[i]!)
        prev_c = np.roll(c, 1); prev_c[0] = np.nan
        open_pct = (o / prev_c - 1.0)

        down_stk = np.zeros(n, dtype=float)
        cur = 0
        for i in range(n):
            cur = (cur + 1) if (np.isfinite(r1[i]) and r1[i] < 0) else 0
            down_stk[i] = cur
        down_stk_t1 = np.roll(down_stk, 1); down_stk_t1[0] = 0.0

        s_c = pd.Series(c)
        s_r1 = pd.Series(r1)
        s_v = pd.Series(v)
        ret3_t1 = (s_c.shift(1) / s_c.shift(4) - 1.0).to_numpy(float) * 100.0
        ret5_t1 = (s_c.shift(1) / s_c.shift(6) - 1.0).to_numpy(float) * 100.0
        ret10_t1 = (s_c.shift(1) / s_c.shift(11) - 1.0).to_numpy(float) * 100.0
        ret20_t1 = (s_c.shift(1) / s_c.shift(21) - 1.0).to_numpy(float) * 100.0
        vol60_t1 = (s_r1.rolling(60, min_periods=20).std().shift(1)).to_numpy(float) * 100.0
        z_ret5_t1 = ret5_t1 / np.maximum(0.5, vol60_t1 * np.sqrt(5.0))

        hi20_t1 = s_c.rolling(20, min_periods=5).max().shift(1).to_numpy(float)
        dd20_t1 = (s_c.shift(1).to_numpy(float) / hi20_t1 - 1.0) * 100.0

        # Panic volume peak in [t-4..t-2] vs vol_ma20, and shrink on t-1
        v_med20_t2 = s_v.rolling(20, min_periods=10).median().shift(2).to_numpy(float)
        v_ratio_t1 = (s_v.shift(1) / s_v.rolling(20, min_periods=10).median().shift(2)).to_numpy(float)
        v_max_3d_prev = np.maximum.reduce([
            s_v.shift(2).fillna(0).to_numpy(float),
            s_v.shift(3).fillna(0).to_numpy(float),
            s_v.shift(4).fillna(0).to_numpy(float),
        ])
        panic_vol_peak_t1 = v_max_3d_prev / np.where(v_med20_t2 > 0, v_med20_t2, np.nan)
        vol_shrink_stop_t1 = s_v.shift(1).to_numpy(float) / np.where(v_max_3d_prev > 0, v_max_3d_prev, np.nan)

        # Candle stabilization at t-1 (CLV & lower shadow)
        rng_t1 = np.roll(h - l, 1); rng_t1[0] = np.nan
        clv_raw = np.where((h - l) > 1e-9, (2.0 * c - h - l) / (h - l), 0.5)
        clv_t1 = np.roll(clv_raw, 1); clv_t1[0] = 0.5
        lsh_raw = np.where(c > 0, (np.minimum(o, c) - l) / c * 100.0, 0.0)
        lsh_t1 = np.roll(lsh_raw, 1); lsh_t1[0] = 0.0
        r1_t1 = np.roll(r1, 1) * 100.0; r1_t1[0] = np.nan

        g["open_pct"] = open_pct
        g["down_streak_t1"] = down_stk_t1
        g["ret_3d_t1"] = ret3_t1
        g["ret_5d_t1"] = ret5_t1
        g["ret_10d_t1"] = ret10_t1
        g["ret_20d_t1"] = ret20_t1
        g["vol60_t1"] = vol60_t1
        g["z_ret5_t1"] = z_ret5_t1
        g["dd_20d_t1"] = dd20_t1
        g["panic_vol_peak_t1"] = panic_vol_peak_t1
        g["vol_shrink_stop_t1"] = vol_shrink_stop_t1
        g["vol_ratio_t1"] = v_ratio_t1
        g["clv_t1"] = clv_t1
        g["lower_shadow_t1"] = lsh_t1
        g["ret_1d_t1"] = r1_t1
        g["is_gold_etf"] = 1.0 if code == "518880" else 0.0
        g["is_div_etf"] = 1.0 if code in ("510880", "512890", "512800") else 0.0
        g["is_broad_def_etf"] = 1.0 if code in ("510050", "510300", "510500") else 0.0

        # Precompute 3d & 5d exit close prices (sell at pos + hold - 1 close)
        for h_td in (3, 5):
            ex_dts, epxs, grets = [], [], []
            step = h_td - 1
            dts_s = g["date"].to_numpy()
            for i in range(n):
                if i + step < n and dts_s[i] >= "2021-01-04":
                    ex_dts.append(str(dts_s[i + step]))
                    epxs.append(float(c[i + step]))
                    grets.append(float(c[i + step] / o[i] - 1.0) if o[i] > 0 else np.nan)
                else:
                    ex_dts.append("")
                    epxs.append(np.nan)
                    grets.append(np.nan)
            g[f"exdt_h{h_td}"] = ex_dts
            g[f"epx_h{h_td}"] = epxs
            g[f"gret_h{h_td}"] = grets
        feats.append(g)

    df_etf = pd.concat(feats, ignore_index=True)
    df_etf = df_etf[df_etf["date"] >= "2021-01-04"].copy()

    mkt_keep = [
        "trade_date", "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_ew_bias20_t1",
        "mkt_pct_above_ma20_t1", "mkt_0925_avg_gap_pct", "th_style_ice_point_sig_t1",
        "nt_v3_score_live_t1", "us_gspc_ret1d_on", "us_ixic_ret1d_on", "us_vix_level_on",
        "us_vix_chg1d_on", "us_tnx_chg5d_on", "us_dxy_ret5d_on", "comm_au_ret5d_t1",
    ]
    df_etf = df_etf.merge(mkt_df[mkt_keep], left_on="date", right_on="trade_date", how="left")
    df_etf = df_etf.merge(cal_ext, on="date", how="left")
    df_etf["v20_prior_empty_streak"] = df_etf["v20_prior_empty_streak"].fillna(0).astype(float)
    return df_etf, px_lu


def _prepare_highdiv_stock_candidates(mkt_df: pd.DataFrame, v20_ctx: dict) -> tuple[pd.DataFrame, dict]:
    """
    Build strictly PIT High-Dividend Low-Vol Large-Cap + Gold Core stock oversold rebound pool.
    Uses stock_fhps_em_all.parquet (最新公告日期 < dt, 股息率 >= 2.5%) + mcap_yi_t1 >= 150 + low 20d amp.
    """
    fhps = pd.read_parquet(FHPS_PQ, columns=["代码", "现金分红-股息率", "最新公告日期"])
    fhps["c6"] = fhps["代码"].astype(str).str.zfill(6)
    fhps["pub_dt"] = pd.to_datetime(fhps["最新公告日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    fhps["dy"] = pd.to_numeric(fhps["现金分红-股息率"], errors="coerce")
    fhps = fhps[fhps["pub_dt"].notna() & fhps["dy"].notna() & (fhps["dy"] >= 0.025)].copy()
    fhps = fhps.sort_values(["c6", "pub_dt"]).reset_index(drop=True)

    # Candidate universe: any code that EVER had dy >= 2.5% in 2020-2026 OR in GOLD_CORE/BANK_BIG4
    hd_codes = sorted(set(fhps.loc[fhps["pub_dt"] >= "2019-01-01", "c6"].unique()) | GOLD_CORE | BANK_BIG4)
    print(f"  [Track E Stocks] Scanning {len(hd_codes)} historical high-div / gold / big4 codes from core parquet...")

    pass1_cols = [
        "dt", "c6", "open", "close", "adj_factor",
        "is_st_pit", "is_yizi_zt", "is_yizi_dt", "is_dt",
        "mcap_yi_t1", "amount_yi_t1", "down_streak_t1", "amp_20d_t1", "ret_5d_t1",
    ]
    ds_core = ds.dataset(STOCK_CORE_PQ, format="parquet")
    st_df = ds_core.scanner(
        columns=pass1_cols,
        filter=ds.field("c6").isin(hd_codes) & (ds.field("dt") <= "2026-11-25"),
    ).to_table().to_pandas()
    st_df["dt"] = st_df["dt"].astype(str)
    st_df["c6"] = st_df["c6"].astype(str).str.zfill(6)
    st_df = st_df.sort_values(["c6", "dt"]).reset_index(drop=True)

    # Attach strictly PIT trailing dividend yield (pub_dt < dt within 420 calendar days)
    fhps_map = {}
    for c6, g in fhps.groupby("c6", sort=False):
        fhps_map[c6] = (g["pub_dt"].to_numpy(), g["dy"].to_numpy(float))

    dy_pit = np.zeros(len(st_df), dtype=np.float32)
    c6_arr = st_df["c6"].to_numpy()
    dt_arr = st_df["dt"].to_numpy()
    dt_ts_ns = pd.to_datetime(dt_arr).to_numpy("datetime64[s]").astype(np.int64)
    brk = np.flatnonzero(c6_arr[1:] != c6_arr[:-1]) + 1
    for s, e in zip(np.concatenate(([0], brk)), np.concatenate((brk, [len(st_df)]))):
        tup = fhps_map.get(c6_arr[s])
        if tup is None:
            continue
        p_dts, p_vals = tup
        p_sec = pd.to_datetime(p_dts).to_numpy("datetime64[s]").astype(np.int64)
        idx = np.searchsorted(p_dts, dt_arr[s:e], side="left") - 1
        ok = (idx >= 0) & ((dt_ts_ns[s:e] - p_sec[np.maximum(idx, 0)]) <= 420 * 86400)
        dy_pit[s:e][ok] = p_vals[idx[ok]]
    st_df["dy_pit_t1"] = dy_pit
    st_df["is_gold_stk"] = st_df["c6"].isin(GOLD_CORE).astype(np.int8)

    # Filter cleanly BEFORE loading extra feature columns or building forward MTM lookup (keeps RSS < 1.0 GB)
    st_df["ao"] = (st_df["open"].astype(float) * st_df["adj_factor"].astype(float)).astype(np.float32)
    st_df["ac"] = (st_df["close"].astype(float) * st_df["adj_factor"].astype(float)).astype(np.float32)
    g = st_df.groupby("c6", sort=False)
    st_df["ret_3d_t1"] = ((g["ac"].shift(1) / g["ac"].shift(4) - 1.0) * 100.0).astype(np.float32)
    amt_max3_t2 = g["amount_yi_t1"].transform(lambda s: s.rolling(3, min_periods=1).max().shift(1))
    st_df["vol_shrink_t1"] = (st_df["amount_yi_t1"] / amt_max3_t2.replace(0, np.nan)).astype(np.float32)

    # Must be PIT high-div (>=3%) & large cap (>=150亿) & low amp (<=5.0% for high-div), OR Gold core stock
    m_univ = (
        (st_df["is_st_pit"] == 0)
        & (st_df["is_yizi_zt"] == 0)
        & (st_df["is_yizi_dt"] == 0)
        & (
            ((st_df["dy_pit_t1"] >= 0.03) & (st_df["mcap_yi_t1"] >= 150.0) & (st_df["amp_20d_t1"] <= 5.0))
            | (st_df["is_gold_stk"] == 1)
        )
    )
    # Oversold setup: >= 2 down days and ret_5d_t1 <= -3.5%, OR ret_5d_t1 <= -5.0%
    m_oversold = ((st_df["down_streak_t1"] >= 2) & (st_df["ret_5d_t1"] <= -3.5)) | (st_df["ret_5d_t1"] <= -5.0)

    cands = st_df[m_univ & m_oversold].copy().reset_index(drop=True)
    cand_codes = sorted(cands["c6"].unique().tolist())
    st_sub = st_df[st_df["c6"].isin(cand_codes)][["c6", "dt", "ao", "ac", "is_yizi_dt", "is_dt"]].copy()
    del st_df
    gc.collect()

    # Pass 2: fetch remaining feature columns ONLY for cand_codes (~340 codes vs 1,557) & merge onto cands
    pass2_cols = [
        "dt", "c6", "open_pct", "ret_1d_t1", "prev_clv",
        "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1",
        "ret_20d_t1", "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1", "csrc_ind_ex5_t1",
    ]
    st_f2 = ds_core.scanner(
        columns=pass2_cols,
        filter=ds.field("c6").isin(cand_codes) & (ds.field("dt") <= "2026-11-25"),
    ).to_table().to_pandas()
    st_f2["dt"] = st_f2["dt"].astype(str)
    st_f2["c6"] = st_f2["c6"].astype(str).str.zfill(6)
    cands = cands.merge(st_f2, on=["c6", "dt"], how="left")
    del st_f2
    gc.collect()

    stk_arrays = {}
    px_lu = {}
    for c6, grp in st_sub.groupby("c6", sort=False):
        dts_s = grp["dt"].to_numpy()
        ao_s = grp["ao"].to_numpy(float)
        ac_s = grp["ac"].to_numpy(float)
        stk_arrays[c6] = (dts_s, {d: i for i, d in enumerate(dts_s)}, ao_s, ac_s, grp["is_yizi_dt"].to_numpy(bool), grp["is_dt"].to_numpy(bool))
    del st_sub
    gc.collect()

    # Populate px_lu ONLY for dates spanned by cands trades >= 2023-01-01 (eliminates huge dict RSS)
    cand_dts_arr = cands["dt"].to_numpy()
    cand_c6_arr = cands["c6"].to_numpy()
    for c6_v, dt_v in zip(cand_c6_arr, cand_dts_arr):
        tup = stk_arrays.get(c6_v)
        if tup is None:
            continue
        dts_s, d_map, ao_s, ac_s, _, _ = tup
        pos = d_map.get(dt_v)
        if pos is None:
            continue
        hi = min(len(dts_s), pos + 14)
        for j in range(pos, hi):
            dv = str(dts_s[j])
            if dv >= "2023-01-01":
                px_lu[(c6_v, dv)] = (float(ao_s[j]), float(ac_s[j]))

    for h_td in (3, 5):
        ex_dts, bpxs, epxs, grets = [], [], [], []
        step = h_td - 1
        for c6, dt_v in zip(cands["c6"], cands["dt"]):
            tup = stk_arrays.get(c6)
            if tup is None:
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan)
                continue
            dts_s, d_map, ao_s, ac_s, yz_dt_s, dt_s = tup
            pos = d_map.get(dt_v)
            if pos is None or pos + step >= len(dts_s):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan)
                continue
            b_px = ao_s[pos]
            ex_pos = pos + step
            while ex_pos < len(dts_s) - 1 and ex_pos < pos + step + 6 and (yz_dt_s[ex_pos] or dt_s[ex_pos]):
                ex_pos += 1
            e_px = ac_s[ex_pos]
            if not (np.isfinite(b_px) and b_px > 0 and np.isfinite(e_px) and e_px > 0):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan)
                continue
            ex_dts.append(str(dts_s[ex_pos]))
            bpxs.append(float(b_px))
            epxs.append(float(e_px))
            grets.append(float(e_px / b_px - 1.0))
        cands[f"exdt_h{h_td}"] = ex_dts
        cands[f"bpx_h{h_td}"] = bpxs
        cands[f"epx_h{h_td}"] = epxs
        cands[f"gret_h{h_td}"] = grets

    mkt_keep = [
        "trade_date", "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_ew_bias20_t1",
        "mkt_pct_above_ma20_t1", "mkt_0925_avg_gap_pct", "us_gspc_ret1d_on", "us_ixic_ret1d_on",
        "us_vix_level_on", "us_vix_chg1d_on", "comm_au_ret5d_t1",
    ]
    cands = cands.merge(mkt_df[mkt_keep], left_on="dt", right_on="trade_date", how="left")
    cal_ext = v20_ctx["calendar_ext"][["trade_date", "prior_empty_streak_len"]].rename(
        columns={"trade_date": "date", "prior_empty_streak_len": "v20_prior_empty_streak"}
    )
    cands = cands.merge(cal_ext, left_on="dt", right_on="date", how="left")
    cands["v20_prior_empty_streak"] = cands["v20_prior_empty_streak"].fillna(0).astype(float)
    return cands, px_lu


def _sim_etf_yield_to_v20(
    pass_df: pd.DataFrame,
    px_lu: dict[tuple[str, str], tuple[float, float]],
    v20_ctx: dict,
    wf_start_dt: str,
    end_dt: str = "2026-11-16",
    max_hold_td: int = 5,
    fee_rt: float = ETF_FEE_RT,
) -> dict:
    """
    Strictly causal day-by-day YieldToV20 simulation for Track E ETFs:
    Enter top-1 scored ETF on V20 empty days; exit when hold expires OR on first morning d >= T+1
    when V20 fires a signal (0 V20 trades skipped!), guaranteeing zero collision drag!
    """
    cal5 = v20_ctx["calendar_5y"]
    cal_win = cal5[cal5["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = cal_win["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    T = len(cal_dts)

    v20_led = v20_ctx["v20_ledger"]
    v20_win = v20_led[v20_led["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    v20_win["source"] = "v20"
    v20_by_buy = {d: g for d, g in v20_win.groupby("buy_date")}
    wait_dts = {w["buy_date"] for w in v20_ctx["v20_waits"] if w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)")}
    emp_strict = set(cal_win.loc[cal_win["v20_empty_strict_no_stier_wait"], "trade_date"])

    p_top1 = (
        pass_df[pass_df["buy_date"].between(wf_start_dt, end_dt)]
        .sort_values(["buy_date", "wf_score", "code"], ascending=[True, False, True])
        .groupby("buy_date", as_index=False)
        .first()
    )
    cand_by_dt = {str(r.buy_date): r for r in p_top1.itertuples(index=False)}

    in_etf = False
    etf_code = ""
    etf_buy_i = -1
    etf_bpx = 0.0
    etf_rem = 0
    in_v20_until = -1
    in_v20_eh = 0

    patch_trades = []
    comb_trades = []
    for i, d in enumerate(cal_dts):
        v20_today = v20_by_buy.get(d)
        is_st_wait = d in wait_dts
        v20_free_morning = in_v20_until < i

        if in_etf and v20_free_morning and (is_st_wait or v20_today is not None):
            px = px_lu.get((etf_code, d))
            if px and np.isfinite(px[0]) and px[0] > 0:
                epx = float(px[0])
                gr = epx / etf_bpx - 1.0
                nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
                tr = {
                    "buy_date": cal_dts[etf_buy_i], "exit_date": d,
                    "buy_hhmm": 925, "exit_hhmm": 924,
                    "code": etf_code, "strategy": "patch_yield",
                    "buy_px": etf_bpx, "exit_px": epx,
                    "gross_ret": gr, "net_ret": nr, "source": "patch", "mtm_pairs": [],
                }
                patch_trades.append(tr)
                comb_trades.append(tr)
                in_etf = False

        if v20_today is not None:
            for r in v20_today.itertuples(index=False):
                if (not in_etf) and ((in_v20_until < i) or (in_v20_until == i and int(r.buy_hhmm) > in_v20_eh)):
                    comb_trades.append({
                        "buy_date": r.buy_date, "exit_date": r.exit_date,
                        "buy_hhmm": int(r.buy_hhmm), "exit_hhmm": int(r.exit_hhmm),
                        "code": r.code, "strategy": r.strategy, "net_ret": float(r.net_ret),
                        "source": "v20", "mtm_pairs": r.mtm_pairs,
                    })
                    in_v20_until = dt_idx.get(r.exit_date, i)
                    in_v20_eh = int(r.exit_hhmm)
                    break

        if in_v20_until < i and is_st_wait and not in_etf:
            in_v20_until = max(in_v20_until, i)
            in_v20_eh = 1500

        if in_etf:
            etf_rem -= 1
            if etf_rem <= 0 or i == T - 1:
                px = px_lu.get((etf_code, d))
                if px and np.isfinite(px[1]) and px[1] > 0:
                    epx = float(px[1])
                    gr = epx / etf_bpx - 1.0
                    nr = (1.0 + gr) * (1.0 - fee_rt) - 1.0
                    tr = {
                        "buy_date": cal_dts[etf_buy_i], "exit_date": d,
                        "buy_hhmm": 925, "exit_hhmm": 1500,
                        "code": etf_code, "strategy": "patch_hold",
                        "buy_px": etf_bpx, "exit_px": epx,
                        "gross_ret": gr, "net_ret": nr, "source": "patch", "mtm_pairs": [],
                    }
                    patch_trades.append(tr)
                    comb_trades.append(tr)
                    in_etf = False
                    continue

        if (not in_etf) and (d in emp_strict) and (d in cand_by_dt) and i < T - 1:
            rc = cand_by_dt[d]
            px = px_lu.get((str(rc.code).zfill(6), d))
            if px and np.isfinite(px[0]) and px[0] > 0:
                in_etf = True
                etf_code = str(rc.code).zfill(6)
                etf_buy_i = i
                etf_bpx = float(px[0])
                etf_rem = max_hold_td - 1

    patch_df = pd.DataFrame(patch_trades)
    comb_df = pd.DataFrame(comb_trades)
    if not patch_df.empty:
        patch_df = wc.build_mtm_segs_for_df(patch_df, cal_dts, px_lu, fee_rt=fee_rt, end_cap_dt=end_dt)
    if not comb_df.empty:
        p_only = comb_df[comb_df["source"] == "patch"].copy()
        if not p_only.empty:
            p_only = wc.build_mtm_segs_for_df(p_only, cal_dts, px_lu, fee_rt=fee_rt, end_cap_dt=end_dt)
            comb_df["mtm_segs"] = [[] for _ in range(len(comb_df))]
            comb_df.loc[comb_df["source"] == "patch", "mtm_segs"] = p_only["mtm_segs"].values
        else:
            comb_df["mtm_segs"] = [[] for _ in range(len(comb_df))]

    csi_arr = cal_win["csi300_daily_ret"].to_numpy(float)
    ew_arr = cal_win["alla_ew_daily_ret"].to_numpy(float)
    dr_comb, _ = wc.wfp._build_combined_mtm(comb_df, cal_dts, patch_mtm_col="mtm_segs")
    dr_v20, _ = wc.wfp._build_combined_mtm(v20_win, cal_dts)
    dr_patch, _ = wc.wfm.build_daily_mtm_returns(patch_df, cal_dts, mtm_col="mtm_segs")

    wins = [("FULL_WF", wf_start_dt, end_dt), ("Y2025_2026", "2025-01-01", end_dt), ("Y2026", "2026-01-01", end_dt)]
    return {
        "patch_metrics": {wn: wc.wfm._calc_one_window(patch_df, None, dr_patch, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins},
        "comb_metrics": {wn: wc.wfm._calc_one_window(comb_df, None, dr_comb, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins},
        "v20_metrics": {wn: wc.wfm._calc_one_window(v20_win, None, dr_v20, cal_dts, dt_idx, csi_arr, ew_arr, s, e) for wn, s, e in wins},
        "corr_diag": wc.compute_corr_diagnostics(dr_patch, cal_dts, v20_ctx, wf_start_dt=wf_start_dt, end_dt=end_dt, dr_emp_standalone=dr_patch, dr_comb=dr_comb),
        "n_patch_added": int(len(patch_df)),
        "patch_trades": patch_df,
    }


def main():
    t0 = time.time()
    print("\n=== [Track E] US Brainwave #3: Low-Corr Broad / Dividend / Gold ETF & High-Div Low-Vol Rebound ===")
    v20_ctx = wc.wfp.load_v20_reference_context(wc.WAVE1_DIR)
    etf_df = wc.build_or_load_clean_etf_cache()
    mkt_df = pd.read_parquet(MKT_PIT_PQ)

    # Check raw underlying daily return correlation of Gold (518880) & Dividend (510880/512890) vs V20
    cal5_wf = v20_ctx["calendar_5y"][v20_ctx["calendar_5y"]["trade_date"].between("2023-01-03", "2026-11-16")].sort_values("trade_date").reset_index(drop=True)
    v20_dr = cal5_wf["v20_daily_ret"].to_numpy(float)
    v20_occ = cal5_wf["v20_occupied"].to_numpy(bool)
    raw_etf_corrs = {}
    for code in ("518880", "510880", "512890", "512800", "510050", "510300", "510500", "512100", "159915", "588000"):
        es = etf_df[etf_df["code"] == code].sort_values("date").copy()
        es["ret"] = es["close"].pct_change().fillna(0.0)
        em = cal5_wf[["trade_date"]].merge(es[["date", "ret"]], left_on="trade_date", right_on="date", how="left")
        er = em["ret"].fillna(0.0).to_numpy(float)
        raw_etf_corrs[code] = {
            "corr_all_days": round(float(np.corrcoef(er, v20_dr)[0, 1]), 4),
            "corr_v20_occupied_days": round(float(np.corrcoef(er[v20_occ], v20_dr[v20_occ])[0, 1]), 4),
        }
    print("  Underlying ETF raw daily corr vs V20:", raw_etf_corrs)

    df_etf, etf_px_lu = _prepare_etf_candidates(etf_df, mkt_df, v20_ctx)

    # ETF Oversold Trigger: >=2d down & ret5 <= -1.2%, OR z_ret5 <= -1.0, OR ret5 <= -2.5%
    m_os = ((df_etf["down_streak_t1"] >= 2) & (df_etf["ret_5d_t1"] <= -1.2)) | (df_etf["z_ret5_t1"] <= -1.0) | (df_etf["ret_5d_t1"] <= -2.5)
    m_retreat = (df_etf["L1_sent_phase_t1"].isin([1, 5])) | (df_etf["v20_prior_empty_streak"] >= 2) | (df_etf["mkt_pct_above_ma20_t1"] < 0.45)
    m_def_core = df_etf["code"].isin(["518880", "510880", "512890", "512800", "510050", "510300"])

    def _fmt_etf_pool(mask, hold_td):
        sub = df_etf[mask & df_etf[f"gret_h{hold_td}"].notna()].copy().reset_index(drop=True)
        sub["buy_date"] = sub["date"]
        sub["exit_date"] = sub[f"exdt_h{hold_td}"]
        sub["buy_px"] = sub["open"]
        sub["exit_px"] = sub[f"epx_h{hold_td}"]
        sub["gross_ret"] = sub[f"gret_h{hold_td}"]
        sub["buy_hhmm"] = 925
        sub["exit_hhmm"] = 1500
        sub["is_yizi"] = False
        sub["can_buy"] = True
        return sub[sub["exit_date"] > sub["buy_date"]].copy().reset_index(drop=True)

    etf_fcols = [
        "down_streak_t1", "ret_3d_t1", "ret_5d_t1", "ret_10d_t1", "ret_20d_t1", "vol60_t1", "z_ret5_t1",
        "dd_20d_t1", "panic_vol_peak_t1", "vol_shrink_stop_t1", "vol_ratio_t1", "clv_t1", "lower_shadow_t1",
        "ret_1d_t1", "open_pct", "is_gold_etf", "is_div_etf", "is_broad_def_etf",
        "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_ew_bias20_t1", "mkt_pct_above_ma20_t1",
        "mkt_0925_avg_gap_pct", "th_style_ice_point_sig_t1", "nt_v3_score_live_t1", "v20_prior_empty_streak",
        "us_gspc_ret1d_on", "us_ixic_ret1d_on", "us_vix_level_on", "us_vix_chg1d_on", "comm_au_ret5d_t1",
    ]

    e1_h3 = _fmt_etf_pool(m_os, 3)
    e1_h5 = _fmt_etf_pool(m_os, 5)
    e2_def_h5 = _fmt_etf_pool(m_os & m_def_core, 5)
    e3_retreat_h5 = _fmt_etf_pool(m_os & m_retreat, 5)
    print(f"  ETF Pool sizes: E1_H3={len(e1_h3)}, E1_H5={len(e1_h5)}, E2_GoldDivCore_H5={len(e2_def_h5)}, E3_RetreatOnly_H5={len(e3_retreat_h5)}")

    # Stock High-Div Low-Vol + Gold Pool
    cands_stk, stk_px_lu = _prepare_highdiv_stock_candidates(mkt_df, v20_ctx)

    def _fmt_stk_pool(hold_td):
        sub = cands_stk[cands_stk[f"gret_h{hold_td}"].notna()].copy().reset_index(drop=True)
        sub["buy_date"] = sub["dt"]
        sub["code"] = sub["c6"]
        sub["exit_date"] = sub[f"exdt_h{hold_td}"]
        sub["buy_px"] = sub[f"bpx_h{hold_td}"]
        sub["exit_px"] = sub[f"epx_h{hold_td}"]
        sub["gross_ret"] = sub[f"gret_h{hold_td}"]
        sub["buy_hhmm"] = 925
        sub["exit_hhmm"] = 1500
        sub["is_yizi"] = False
        sub["can_buy"] = True
        return sub[sub["exit_date"] > sub["buy_date"]].copy().reset_index(drop=True)

    e4_stk_h5 = _fmt_stk_pool(5)
    e4_stk_h3 = _fmt_stk_pool(3)
    e5_stk_retreat_h5 = e4_stk_h5[(e4_stk_h5["L1_sent_phase_t1"].isin([1, 5])) | (e4_stk_h5["v20_prior_empty_streak"] >= 2) | (e4_stk_h5["mkt_pct_above_ma20_t1"] < 0.45)].copy().reset_index(drop=True)
    print(f"  Stock High-Div+Gold Pool sizes: E4_Stk_H3={len(e4_stk_h3)}, E4_Stk_H5={len(e4_stk_h5)}, E5_Stk_Retreat_H5={len(e5_stk_retreat_h5)}")

    stk_fcols = [
        "dy_pit_t1", "is_gold_stk", "mcap_yi_t1", "amount_yi_t1", "open_pct", "ret_1d_t1", "prev_clv",
        "down_streak_t1", "ret_3d_t1", "ret_5d_t1", "ret_20d_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1",
        "dd_20d_t1", "amp_20d_t1", "vol_ratio5_t1", "vol_shrink_t1", "turn_5_20_t1", "real_turn_pct_t1",
        "csrc_ind_ex5_t1", "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_dt_cnt_t1", "L1_ew_bias20_t1",
        "mkt_pct_above_ma20_t1", "mkt_0925_avg_gap_pct", "v20_prior_empty_streak",
        "us_gspc_ret1d_on", "us_ixic_ret1d_on", "us_vix_level_on", "us_vix_chg1d_on", "comm_au_ret5d_t1",
    ]

    # Physical truncation 2024-12-31 test on ETF & Stock pools
    trunc_e_etf = wc.wfe.verify_truncation_zero_leakage(
        e1_h5, etf_fcols, mode="A", cutoff="2024-12-31", score_threshold="top20",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=80, min_warmup_trades_rare=50,
        min_warmup_months=18, recalc_freq="daily", top_k=10, min_k=4, fee_rt=ETF_FEE_RT, gross_ret_col="gross_ret",
    )
    trunc_e_stk = wc.wfe.verify_truncation_zero_leakage(
        e4_stk_h5, stk_fcols, mode="A", cutoff="2024-12-31", score_threshold="top10",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=100, min_warmup_trades_rare=60,
        min_warmup_months=18, recalc_freq="daily", top_k=10, min_k=4, fee_rt=STK_FEE_RT, gross_ret_col="gross_ret",
    )
    print(f"  [Track E] Truncation 2024-12-31 proof: ETF={trunc_e_etf['zero_leakage_pass']} ({trunc_e_etf['max_abs_score_diff']}), Stk={trunc_e_stk['zero_leakage_pass']} ({trunc_e_stk['max_abs_score_diff']})")

    variants = [
        ("E1_ETF_BroadDivGold_H3", "宽基+红利+黄金ETF超跌反抽 3天持仓(ETF扣0.05%)", e1_h3, etf_fcols, etf_px_lu, ETF_FEE_RT, trunc_e_etf["zero_leakage_pass"], 3, "daily"),
        ("E1_ETF_BroadDivGold_H5", "宽基+红利+黄金ETF超跌反抽 5天持仓(ETF扣0.05%)", e1_h5, etf_fcols, etf_px_lu, ETF_FEE_RT, trunc_e_etf["zero_leakage_pass"], 5, "daily"),
        ("E2_ETF_GoldDivCore_H5", "纯防御核心(黄金+红利+银行+上证50/300 ETF)超跌反抽 5天持仓(扣0.05%)", e2_def_h5, etf_fcols, etf_px_lu, ETF_FEE_RT, trunc_e_etf["zero_leakage_pass"], 5, "daily"),
        ("E3_ETF_RetreatEmpty_H5", "严格退潮/冰点/连空日 ETF超跌反抽 5天持仓(扣0.05%)", e3_retreat_h5, etf_fcols, etf_px_lu, ETF_FEE_RT, trunc_e_etf["zero_leakage_pass"], 5, "daily"),
        ("E4_Stk_HighDivGold_H3", "大盘高股息低波+黄金核心股超跌反抽 3天持仓(扣0.30%)", e4_stk_h3, stk_fcols, stk_px_lu, STK_FEE_RT, trunc_e_stk["zero_leakage_pass"], 3, "monthly"),
        ("E4_Stk_HighDivGold_H5", "大盘高股息低波+黄金核心股超跌反抽 5天持仓(扣0.30%)", e4_stk_h5, stk_fcols, stk_px_lu, STK_FEE_RT, trunc_e_stk["zero_leakage_pass"], 5, "daily"),
        ("E5_Stk_RetreatEmpty_H5", "严格退潮/冰点/连空日 高股息低波+黄金反抽 5天持仓(扣0.30%)", e5_stk_retreat_h5, stk_fcols, stk_px_lu, STK_FEE_RT, trunc_e_stk["zero_leakage_pass"], 5, "daily"),
    ]

    track_res = {}
    csv_rows = []
    for vid, desc, df_v, fcols, plu, fee_r, t_pass, h_td, rf in variants:
        res = wc.evaluate_scorecard_with_exact_mtm(
            df_v, fcols, plu, v20_ctx, fee_rt=fee_r, gross_ret_col="gross_ret",
            wf_start_date="2023-01-03", end_date="2026-11-16",
            min_warmup_trades=80, min_warmup_trades_rare=50, min_warmup_months=18,
            recalc_freq=rf, top_k=10, min_k=4, max_corr=0.65,
            thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
            perm_n=1000, seed=20261125,
        )
        print(f"  [{vid}] ({rf}) start={res['meta']['wf_actual_start']}, cands={len(df_v)}")
        print(res["summary_table"][["threshold", "n_trades", "wr_pct", "plr", "nav_wf", "ex5_wf", "mdd_pct", "sharpe", "nav_2526", "nav_y26", "perm_sd_p", "corr_v20"]].to_string(index=False))

        wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
        th_out = {}
        for tname, td in res["threshold_results"].items():
            vp = td["v20_empty_patch"]
            th_out[tname] = {
                "metrics": td["metrics"],
                "corr_diag": td["corr_diag"],
                "v20_empty_patch": {
                    "mode1_strict_combined_no_peek": {k: v for k, v in vp["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                    "mode2_empty_slot_standalone": vp["mode2_empty_slot_standalone"],
                } if vp else None,
            }
            if tname in ("all_cands", "top30", "top20", "top10", "abs_70"):
                csv_rows.append(wc.extract_track_row(
                    "TrackE_LowCorr_Rebound", vid, desc, tname, fee_r, wf_start,
                    td["metrics"], vp, td["corr_diag"], t_pass,
                ))

        # Evaluate YieldToV20 across ETF variants AND Stock variants (E4/E5) so V20 never collides out!
        yield_out = {}
        y_thresholds = ("all_cands", "top30", "top20", "top10", "abs_70") if fee_r == ETF_FEE_RT else ("top30", "top20", "top10", "abs_70")
        for tname in y_thresholds:
            pdf = res["threshold_results"][tname]["pass_df"]
            if not pdf.empty:
                yr = _sim_etf_yield_to_v20(pdf, plu, v20_ctx, wf_start_dt=wf_start, end_dt="2026-11-16", max_hold_td=h_td, fee_rt=fee_r)
                yield_out[tname] = {k: v for k, v in yr.items() if k != "patch_trades"}
                pm = yr["patch_metrics"]["FULL_WF"]
                cm = yr["comb_metrics"]["FULL_WF"]
                vm = yr["v20_metrics"]["FULL_WF"]
                pm25 = yr["patch_metrics"]["Y2025_2026"]
                cm25 = yr["comb_metrics"]["Y2025_2026"]
                vm25 = yr["v20_metrics"]["Y2025_2026"]
                pm26 = yr["patch_metrics"]["Y2026"]
                csv_rows.append({
                    "track": "TrackE_LowCorr_Rebound", "variant": f"{vid}_YieldToV20",
                    "desc": f"{desc} [让位V20]", "threshold": tname, "fee_rt_pct": round(fee_r * 100.0, 3),
                    "wf_actual_start": wf_start,
                    "n_trades_wf": pm["n"], "wr_wf_pct": pm["wr_pct"], "plr_wf": pm["plr"], "mean_wf_pct": pm["mean_pct"],
                    "nav_wf": pm["nav"], "ex3_wf": pm["ex_top3_nav"], "ex5_wf": pm["ex_top5_nav"],
                    "mdd_wf_pct": pm["daily_mdd_pct"], "sharpe_wf": pm["daily_sharpe"], "calmar_wf": pm["daily_calmar"],
                    "excess_csi300_wf_pp": pm["excess_csi300_pp"],
                    "nav_2526": pm25["nav"], "ex5_2526": pm25["ex_top5_nav"], "mdd_2526_pct": pm25["daily_mdd_pct"], "sharpe_2526": pm25["daily_sharpe"],
                    "excess_csi300_2526_pp": pm25["excess_csi300_pp"],
                    "nav_2026": pm26["nav"], "ex5_2026": pm26["ex_top5_nav"], "mdd_2026_pct": pm26["daily_mdd_pct"], "sharpe_2026": pm26["daily_sharpe"],
                    "perm_sd_p": None, "perm_any_p": None,
                    "corr_v20_all_days": yr["corr_diag"]["corr_standalone_vs_v20_all_days"],
                    "corr_v20_both_active": yr["corr_diag"]["corr_standalone_vs_v20_both_active"],
                    "corr_v20_empty_patch": yr["corr_diag"]["corr_empty_patch_standalone_vs_v20_all_days"],
                    "emp_trades_wf": pm["n"], "emp_wr_pct": pm["wr_pct"], "emp_nav_wf": pm["nav"], "emp_ex5_wf": pm["ex_top5_nav"],
                    "emp_mdd_wf_pct": pm["daily_mdd_pct"], "emp_sharpe_wf": pm["daily_sharpe"], "emp_calmar_wf": pm["daily_calmar"],
                    "emp_nav_2526": pm25["nav"],
                    "patch_n_added": yr["n_patch_added"], "patch_n_v20_skipped": 0,
                    "v20_base_nav_wf": vm["nav"], "v20_base_mdd_wf_pct": vm["daily_mdd_pct"], "v20_base_sharpe_wf": vm["daily_sharpe"], "v20_base_calmar_wf": vm["daily_calmar"],
                    "comb_nav_wf": cm["nav"], "comb_mdd_wf_pct": cm["daily_mdd_pct"], "comb_sharpe_wf": cm["daily_sharpe"], "comb_calmar_wf": cm["daily_calmar"],
                    "comb_delta_nav_ratio": round(cm["nav"] / max(1e-9, vm["nav"]), 4),
                    "comb_delta_mdd_pp": round(cm["daily_mdd_pct"] - vm["daily_mdd_pct"], 2),
                    "comb_delta_sharpe": round(cm["daily_sharpe"] - vm["daily_sharpe"], 4),
                    "comb_delta_calmar": round(cm["daily_calmar"] - vm["daily_calmar"], 3),
                    "comb_nav_2526": cm25["nav"], "v20_base_nav_2526": vm25["nav"],
                    "trunc_20241231_pass": t_pass,
                })
        if vid == "E5_Stk_RetreatEmpty_H5":
            p70 = res["threshold_results"]["abs_70"]["pass_df"]
            keep_cols = [c for c in ["buy_date", "exit_date", "code", "wf_score", "buy_px", "exit_px", "gross_ret"] if c in p70.columns]
            p70[keep_cols].to_parquet(f"{wc.CACHE_DIR}/track_e5_stk_abs70_pass.parquet", index=False)
        if vid == "E3_ETF_RetreatEmpty_H5":
            pe3 = res["threshold_results"]["all_cands"]["pass_df"]
            keep_cols = [c for c in ["buy_date", "exit_date", "code", "wf_score", "buy_px", "exit_px", "gross_ret"] if c in pe3.columns]
            pe3[keep_cols].to_parquet(f"{wc.CACHE_DIR}/track_e3_etf_allcands_pass.parquet", index=False)

        track_res[vid] = {
            "desc": desc,
            "n_total_cands": int(len(df_v)),
            "wf_actual_start": wf_start,
            "n_daily_rebuilds": res["meta"]["n_rebuilds"],
            "summary_table": res["summary_table"].to_dict("records"),
            "thresholds": th_out,
            "yield_to_v20": yield_out,
            "latest_scorecard_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr_pct": f["bin_wr_pct"], "bin_mean_pct": f["bin_mean_pct"]}
                for f in (res["meta"]["latest_scorecard"]["factors"] if res["meta"]["latest_scorecard"] else [])
            ],
            "best_slot_df": res["threshold_results"]["top20"]["slot_df"],
        }

    track_res["E2_ETF_GoldDivCore_H5"]["best_slot_df"].drop(columns=["mtm_segs"], errors="ignore").to_parquet(
        f"{wc.CACHE_DIR}/track_e_etf_best_slot.parquet", index=False
    )
    track_res["E4_Stk_HighDivGold_H5"]["best_slot_df"].drop(columns=["mtm_segs"], errors="ignore").to_parquet(
        f"{wc.CACHE_DIR}/track_e_stk_best_slot.parquet", index=False
    )
    for v in track_res.values():
        v.pop("best_slot_df", None)

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    out = wc.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "raw_underlying_etf_corr_vs_v20": raw_etf_corrs,
        "truncation_20241231_proofs": {"etf": trunc_e_etf, "stock": trunc_e_stk},
        "variants": track_res,
        "csv_rows": csv_rows,
    })
    with open(f"{wc.CACHE_DIR}/w2b5_track_e.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[Track E DONE in {time.time()-t0:.1f}s | RSS={rss_mb} MB]")


if __name__ == "__main__":
    main()
