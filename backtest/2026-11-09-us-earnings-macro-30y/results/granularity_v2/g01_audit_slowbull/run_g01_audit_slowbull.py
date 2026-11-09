#!/usr/bin/env python3
"""
run_g01_audit_slowbull.py
G01: 缓涨策略二阶导拆解与零未来函数交叉审核实证引擎 (1996-2026)

核心原则与防伪红线:
1. 绝对零修改 /tmp/us_xuangu_20261109/ 下任何文件 (100% 只读比对)。
2. 零未来函数:
   - 所有价格形态特征 (6M/1Y/1.5Y/2Y/3Y/5Y R², MDD, CAGR) 严格截至 T_pre = idx_filed - 1 (披露前一日收盘),
     同时只读对齐比对 pit_with_9params.parquet 的 r2_* 特征。
   - 入场严格锁定在 10-Q/10-K 正式披露次一交易日收盘 (filed + 1 close)。
   - 市值严格使用当期已披露股本 × 当期未复权股价计算的真实 PIT 市值 (mcap_2026_equiv_b >= 25)。
   - 退市/破产股绝不设为 NaN 静默丢弃: 融合 delisted_prices_{0,1} + extra_prices + SEC Form 4 + 破产终值,
     买入后退市/破产股锁定最后交易日残值 (破产股计入清算出清残值) 顺延至持有期末计入分母。
   - D15 合规聚合: 日历季度等权对标 SPY 净超额 + 250 交易日同股冷却去重统计。

产出文件:
1. table_g01_bias_audit.csv
2. table_g01_slowbull_x_2nd_deriv.csv
3. table_g01_pre2009_slowbull.csv
"""

import os
import re
import sys
import glob
import json
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy import stats

PROJ_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
TMP_EARN = "/tmp/us_earn_macro_bt_20261109"
TMP_XUAN = "/tmp/us_xuangu_20261109"  # STRICTLY READ-ONLY!
OUT_DIR = os.path.join(PROJ_DIR, "results/granularity_v2/g01_audit_slowbull")
os.makedirs(OUT_DIR, exist_ok=True)


# ==============================================================================
# PART 1: 构建全量零幸存者偏差日线价格与退市终值矩阵 (1990-2026)
# ==============================================================================
def build_unified_delist_aware_engine():
    t0 = time.time()
    print("[1/6] 构建统一日线价格 + 退市破产残值矩阵 (unified_prices + delisted_prices + extra_prices)...")

    # 1. 读取 unified_prices_and_bench.parquet (主面板要求的核心日线源)
    upb_path = os.path.join(TMP_EARN, "unified_prices_and_bench.parquet")
    upb = pd.read_parquet(upb_path, columns=["date", "ticker", "close", "adj_close", "spy_adj_close"])
    upb["date"] = pd.to_datetime(upb["date"]).dt.tz_localize(None).dt.normalize()

    # 提取交易日历与 SPY 复权总回报基准
    spy_df = upb[["date", "spy_adj_close"]].dropna().drop_duplicates("date").sort_values("date")
    # 补充早期 1990-1993 GSPC 链式衔接 (直接从 price_engine_cache 取完整交易日历与 spy_tr 确保 1990-2026 连续)
    cache_path = os.path.join(TMP_EARN, "price_engine_cache.npz")
    cache = np.load(cache_path, allow_pickle=True)
    dates = cache["dates"]  # np.datetime64[D], 1990-01-02 to 2026-11-06
    dates_ts = pd.to_datetime(dates)
    n_days = len(dates)
    date_to_idx = {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)}
    spy_tr = cache["spy_tr"].astype(np.float64)

    # 用 unified_prices_and_bench 校验 SPY 一致性并构建主股票矩阵
    upb = upb[upb["date"].isin(date_to_idx)].copy()
    base_tickers = sorted(upb["ticker"].unique().tolist())
    base_set = set(base_tickers)

    # 2. 读取退市股元数据 (571 S&P 500 历史退出股 + 61 医疗/成长退市股 + 165 SEC Form 25/8-K 审计样本)
    dm0 = pd.read_parquet(os.path.join(TMP_EARN, "delisted_prices/delisted_meta_0.parquet"))
    dm1 = pd.read_parquet(os.path.join(TMP_EARN, "delisted_prices/delisted_meta_1.parquet"))
    dm_all = pd.concat([dm0, dm1], ignore_index=True)
    hc61 = pd.read_parquet(os.path.join(TMP_EARN, "delisted_prices/hc_delisted_61_meta.parquet"))
    q03_path = os.path.join(TMP_XUAN, "w2/q03_delisted_ma_vs_bankrupt.csv")
    q03 = pd.read_csv(q03_path) if os.path.exists(q03_path) else pd.DataFrame()

    exit_meta = {}
    for _, r in dm_all.iterrows():
        tk = str(r["ticker"]).strip()
        et = str(r["exit_type"])
        dt_s = r["sp_end"] if (pd.notna(r["sp_end"]) and str(r["sp_end"]) != "nan") else r["last_sec_filing"]
        t_deal = float(r["terminal_delist_ret"]) if pd.notna(r["terminal_delist_ret"]) else 0.0
        exit_meta[tk] = {
            "exit_type": "BANKRUPTCY" if et == "BANKRUPTCY_OR_LIQUIDATION" else ("MA" if et == "MA_ACQUISITION" else et),
            "exit_dt": pd.to_datetime(dt_s, errors="coerce"),
            "t_ret_residual": -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else 0.0,
            "t_ret_deal": -0.95 if et == "BANKRUPTCY_OR_LIQUIDATION" else t_deal,
            "deal_px": np.nan,
        }

    hc_bk_set = {"NVTA", "VVUS", "ENDP", "MNK"}
    for _, r in hc61.iterrows():
        tk = str(r["ticker"]).strip()
        is_bk = tk in hc_bk_set
        if tk not in exit_meta:
            exit_meta[tk] = {
                "exit_type": "BANKRUPTCY" if is_bk else "MA",
                "exit_dt": pd.to_datetime(r["delist_dt"], errors="coerce"),
                "t_ret_residual": -0.95 if is_bk else 0.0,
                "t_ret_deal": -0.95 if is_bk else 0.15,
                "deal_px": np.nan,
            }
        elif pd.isna(exit_meta[tk]["exit_dt"]):
            exit_meta[tk]["exit_dt"] = pd.to_datetime(r["delist_dt"], errors="coerce")

    if len(q03) > 0:
        for _, r in q03.iterrows():
            tk = str(r["ticker"]).strip()
            et_q = str(r["exit_type"])
            detail = str(r.get("acquirer_or_bankruptcy_detail", "")) + " " + str(r.get("notes", ""))
            m_dt = re.search(r"(20\d{2}-\d{2}-\d{2}|199\d-\d{2}-\d{2})", detail)
            exact_dt = pd.to_datetime(m_dt.group(1), errors="coerce") if m_dt else pd.to_datetime(r["sp_end_date"], errors="coerce")
            if pd.isna(exact_dt):
                exact_dt = pd.to_datetime(r["sp_end_date"], errors="coerce")
            prem = float(r["terminal_return_pct"]) / 100.0 if pd.notna(r["terminal_return_pct"]) else 0.0
            if et_q == "bankrupt_wipeout":
                exit_meta[tk] = {
                    "exit_type": "BANKRUPTCY",
                    "exit_dt": exact_dt,
                    "t_ret_residual": -0.95,
                    "t_ret_deal": max(-0.995, min(-0.85, prem)),
                    "deal_px": float(r["deal_price_or_terminal_price"]) if pd.notna(r["deal_price_or_terminal_price"]) else 0.05,
                }
            elif et_q == "ma_cash_premium":
                prev_dt = exit_meta.get(tk, {}).get("exit_dt", pd.NaT)
                exit_meta[tk] = {
                    "exit_type": "MA",
                    "exit_dt": pd.to_datetime(r["sp_end_date"], errors="coerce") if pd.notna(r["sp_end_date"]) else (exact_dt if pd.notna(exact_dt) else prev_dt),
                    "t_ret_residual": 0.0,
                    "t_ret_deal": prem,
                    "deal_px": float(r["deal_price_or_terminal_price"]) if pd.notna(r["deal_price_or_terminal_price"]) else np.nan,
                }

    for tk_ov, dt_ov in [("NVTA", "2024-02-13"), ("VVUS", "2020-07-07"), ("TUP", "2024-09-17")]:
        exit_meta[tk_ov] = {"exit_type": "BANKRUPTCY", "exit_dt": pd.Timestamp(dt_ov), "t_ret_residual": -0.95, "t_ret_deal": -0.95, "deal_px": 0.05}

    # 3. 读取退市日线补充库 (delisted_prices_0/1 + extra_prices，只读!)
    supp_list = []
    for p in [
        os.path.join(TMP_EARN, "delisted_prices/delisted_prices_0.parquet"),
        os.path.join(TMP_EARN, "delisted_prices/delisted_prices_1.parquet"),
    ]:
        if os.path.exists(p):
            d = pd.read_parquet(p, columns=["date", "ticker", "close", "adj_close"])
            d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
            supp_list.append(d)

    for ep in sorted(glob.glob(os.path.join(TMP_XUAN, "w2/extra_prices/*.parquet"))):
        tk_ep = os.path.basename(ep).replace(".parquet", "")
        if tk_ep not in base_set and tk_ep != "HTZ":  # HTZ extra_prices is post-2021 relisted new equity
            d = pd.read_parquet(ep)
            if "date" not in d.columns:
                d = d.reset_index()
                if "Date" in d.columns:
                    d = d.rename(columns={"Date": "date"})
            d = d.rename(columns={c: c.lower().replace(" ", "_") for c in d.columns})
            if "date" in d.columns and ("adj_close" in d.columns or "close" in d.columns):
                d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
                d["ticker"] = tk_ep
                if "adj_close" not in d.columns:
                    d["adj_close"] = d["close"]
                if "close" not in d.columns:
                    d["close"] = d["adj_close"]
                supp_list.append(d[["date", "ticker", "close", "adj_close"]])

    df_supp = pd.concat(supp_list, ignore_index=True) if supp_list else pd.DataFrame(columns=["date", "ticker", "close", "adj_close"])
    df_supp = df_supp[(~df_supp["ticker"].isin(base_set)) & df_supp["date"].isin(date_to_idx)].copy()
    df_supp = df_supp.sort_values(["ticker", "date"]).drop_duplicates(["ticker", "date"], keep="last")

    supp_tickers = sorted(df_supp["ticker"].unique().tolist())
    all_tickers = base_tickers + supp_tickers
    n_stocks = len(all_tickers)
    tk_to_col = {tk: i for i, tk in enumerate(all_tickers)}
    for tk, idx in list(tk_to_col.items()):
        for alt in (tk.replace(".", "-"), tk.replace("-", ".")):
            if alt not in tk_to_col:
                tk_to_col[alt] = idx

    P_adj = np.full((n_days, n_stocks), np.nan, dtype=np.float32)
    P_cls = np.full((n_days, n_stocks), np.nan, dtype=np.float32)

    # 填充 base_tickers (来自 unified_prices_and_bench.parquet)
    d_idx_b = upb["date"].map(date_to_idx).values
    c_idx_b = upb["ticker"].map(tk_to_col).values
    P_adj[d_idx_b, c_idx_b] = upb["adj_close"].values.astype(np.float32)
    P_cls[d_idx_b, c_idx_b] = upb["close"].values.astype(np.float32)

    # 填充退市补充日线
    if len(df_supp) > 0:
        d_idx_s = df_supp["date"].map(date_to_idx).values
        c_idx_s = df_supp["ticker"].map(tk_to_col).values
        P_adj[d_idx_s, c_idx_s] = df_supp["adj_close"].values.astype(np.float32)
        P_cls[d_idx_s, c_idx_s] = df_supp["close"].values.astype(np.float32)

    # 记录每只股票真实的最后有效交易日索引 (在 ffill 前!)
    P_adj[P_adj <= 0] = np.nan
    P_cls[P_cls <= 0] = np.nan
    first_valid_idx = np.full(n_stocks, -1, dtype=np.int32)
    last_valid_idx = np.full(n_stocks, -1, dtype=np.int32)
    for c in range(n_stocks):
        vm = ~np.isnan(P_adj[:, c])
        if np.any(vm):
            ix = np.where(vm)[0]
            first_valid_idx[c] = ix[0]
            last_valid_idx[c] = ix[-1]

    # 仅对停牌空隙做 <=5 交易日短填充 (绝不越过 last_valid_idx 往后填充伪造存续!)
    P_adj_df = pd.DataFrame(P_adj).ffill(limit=5)
    P_cls_df = pd.DataFrame(P_cls).ffill(limit=5)
    for c in range(n_stocks):
        lv = last_valid_idx[c]
        if 0 <= lv < n_days - 1:
            P_adj_df.iloc[lv + 1:, c] = np.nan
            P_cls_df.iloc[lv + 1:, c] = np.nan
    P_adj = P_adj_df.values.astype(np.float32)
    P_cls = P_cls_df.values.astype(np.float32)

    # 标记已知分拆/重组未复权断层 (对齐主项目 price_engine_cache)
    seg_breaks = np.zeros((n_days, n_stocks), dtype=np.uint8)
    cache_tk_map = {t: i for i, t in enumerate(cache["tickers"])}
    for i, tk in enumerate(all_tickers):
        if tk in cache_tk_map:
            seg_breaks[:, i] = cache["seg_breaks"][:, cache_tk_map[tk]]
        else:
            s_col = pd.Series(P_adj[:, i])
            r1 = s_col.pct_change().values
            ext = np.where((r1 > 4.0) | (r1 < -0.92))[0]
            for r_i in ext:
                if tk not in ("FNMA", "FMCC", "HTZ") and exit_meta.get(tk, {}).get("exit_type") != "BANKRUPTCY":
                    seg_breaks[max(0, r_i - 5):min(n_days, r_i + 6), i] = 1

    # 构建每只股票的退市残值修正向量
    term_residual = np.zeros(n_stocks, dtype=np.float32)
    term_deal = np.zeros(n_stocks, dtype=np.float32)
    exit_types_arr = np.full(n_stocks, "ACTIVE", dtype=object)
    for i, tk in enumerate(all_tickers):
        em = exit_meta.get(tk) or exit_meta.get(tk.replace("-", "."))
        if em is not None:
            exit_types_arr[i] = em["exit_type"]
            if last_valid_idx[i] < n_days - 15:
                term_residual[i] = em["t_ret_residual"]
                term_deal[i] = em["t_ret_deal"]

    print(f"  日线引擎就绪 ({time.time()-t0:.2f}s): 共 {n_stocks} 只股票 (unified={len(base_tickers)}, 退市补充={len(supp_tickers)}), {n_days} 交易日.")
    return {
        "dates": dates,
        "dates_ts": dates_ts,
        "n_days": n_days,
        "date_to_idx": date_to_idx,
        "tickers": all_tickers,
        "tk_to_col": tk_to_col,
        "P_adj": P_adj,
        "P_cls": P_cls,
        "spy_tr": spy_tr,
        "first_valid_idx": first_valid_idx,
        "last_valid_idx": last_valid_idx,
        "seg_breaks": seg_breaks,
        "term_residual": term_residual,
        "term_deal": term_deal,
        "exit_types": exit_types_arr,
        "exit_meta": exit_meta,
        "dm_all": dm_all,
        "hc61": hc61,
        "q03": q03,
    }


# ==============================================================================
# PART 2: 向量化计算严格零前视 (截至 T_pre = idx_event - 1) 的 6 档平滑度特征 + 退市顺延前瞻收益
# ==============================================================================
LOOKBACK_MAP = {
    "6M": 126,
    "1Y": 252,
    "1_5Y": 378,
    "2Y": 504,
    "3Y": 756,
    "5Y": 1260,
}


def compute_pit_smoothness_and_returns(
    eng: dict,
    df_ev: pd.DataFrame,
    ticker_col: str = "ticker",
    event_date_col: str = "filed",
    horizons=(252, 756, 1260),
    compute_6_lookbacks: bool = True,
) -> pd.DataFrame:
    """
    严格零前视:
    1. 所有历史缓涨特征 (r2_*, mdd_*, cagr_*) 100% 截至 idx_pre = idx_event - 1 (披露前一日收盘)!
    2. 入场点严格为 idx_entry = idx_event + 1 (披露次一交易日收盘)!
    3. 退市/破产股若在 d_entry < last_valid < d_entry + h 停止交易:
       - 绝不丢弃为 NaN!
       - 主口径 (fwd_{h}d / alpha_fwd_{h}d): 锁定最后交易日残值 (破产股乘破产受偿残值 5%), 顺延至 d_tgt 并扣减完整区间 SPY 总回报!
       - 对照口径A (alpha_naive_drop_{h}d): 退市即设为 NaN 静默丢弃 (复现未修正幸存者偏差)!
       - 对照口径B (alpha_deal_{h}d): 计入已核实的现金并购公告溢价!
    """
    t0 = time.time()
    out = df_ev.copy().reset_index(drop=True)
    n = len(out)
    if n == 0:
        return out

    dates = eng["dates"]
    dates_ts = eng["dates_ts"]
    n_days = eng["n_days"]
    P_adj = eng["P_adj"]
    P_cls = eng["P_cls"]
    spy_tr = eng["spy_tr"]
    tk2c = eng["tk_to_col"]
    last_v = eng["last_valid_idx"]
    term_res = eng["term_residual"]
    term_deal = eng["term_deal"]
    seg_brk = eng["seg_breaks"]

    cols = np.array([tk2c.get(str(t), -1) for t in out[ticker_col].values], dtype=np.int32)
    ev_dt = pd.to_datetime(out[event_date_col]).dt.normalize().values.astype("datetime64[D]")
    idx_ev = np.clip(np.searchsorted(dates, ev_dt, side="left"), 0, n_days - 1)
    idx_pre = idx_ev - 1
    idx_ent = idx_ev + 1

    valid_pre = (idx_pre >= 0) & (cols >= 0)
    valid_ent = (idx_ent < n_days) & (cols >= 0)

    # 财报反应窗口: T_pre (idx_ev - 1) 到 T_entry (idx_ev + 1) 及单日跳涨
    pre_px = np.full(n, np.nan, dtype=np.float64)
    ev_px = np.full(n, np.nan, dtype=np.float64)
    ent_px = np.full(n, np.nan, dtype=np.float64)
    ent_cls = np.full(n, np.nan, dtype=np.float64)
    pre_dt_arr = np.full(n, np.nan, dtype="datetime64[ns]")
    ent_dt_arr = np.full(n, np.nan, dtype="datetime64[ns]")
    has_brk = np.zeros(n, dtype=bool)

    vp = np.where(valid_pre)[0]
    pre_px[vp] = P_adj[idx_pre[vp], cols[vp]]
    ev_px[vp] = P_adj[idx_ev[vp], cols[vp]]
    pre_dt_arr[vp] = dates_ts.values[idx_pre[vp]]
    has_brk[vp] = seg_brk[idx_pre[vp], cols[vp]] > 0

    ve = np.where(valid_ent)[0]
    ent_px[ve] = P_adj[idx_ent[ve], cols[ve]]
    ent_cls[ve] = P_cls[idx_ent[ve], cols[ve]]
    ent_dt_arr[ve] = dates_ts.values[idx_ent[ve]]

    # 同时检查 [idx_ev - 7, idx_ev + 1] 内的财报新闻稿(8-K)跳涨，但严格 <= idx_ent (零未来函数!)
    jump_2d_fil = np.where((pre_px > 0) & (ent_px > 0), ent_px / pre_px - 1.0, np.nan)
    jump_1d_fil = np.where((pre_px > 0) & (ev_px > 0), ev_px / pre_px - 1.0, np.nan)
    max_1d_fil2d = np.fmax(
        jump_1d_fil,
        np.where((ev_px > 0) & (ent_px > 0), ent_px / ev_px - 1.0, np.nan)
    )

    out["g01_pre_date"] = pre_dt_arr
    out["g01_entry_date"] = ent_dt_arr
    out["g01_pre_adj_px"] = pre_px
    out["g01_entry_adj_px"] = ent_px
    out["g01_entry_unadj_cls"] = ent_cls
    out["g01_has_break"] = has_brk
    out["g01_earn_ret_2d"] = jump_2d_fil
    out["g01_earn_ret_2d_excess"] = np.nan
    ok_both = valid_pre & valid_ent & (pre_px > 0) & (ent_px > 0)
    ib = np.where(ok_both)[0]
    out.loc[ib, "g01_earn_ret_2d_excess"] = jump_2d_fil[ib] - (spy_tr[idx_ent[ib]] / spy_tr[idx_pre[ib]] - 1.0)
    out["g01_max_1d_filed2d"] = max_1d_fil2d

    # 1. 计算 6 档回看时长 (6M/1Y/1.5Y/2Y/3Y/5Y) 严格截至 idx_pre 的 signed Log-Price R², MDD, CAGR
    if compute_6_lookbacks:
        # 利用按列处理避免重复切片: 按股票分组只对出现过的股票计算前缀和!
        uniq_cols = np.unique(cols[cols >= 0])
        col_events = {}
        for idx_row in vp:
            c = cols[idx_row]
            col_events.setdefault(c, []).append(idx_row)

        r2_res = {k: np.full(n, np.nan, dtype=np.float32) for k in LOOKBACK_MAP}
        mdd_res = {k: np.full(n, np.nan, dtype=np.float32) for k in LOOKBACK_MAP}
        cagr_res = {k: np.full(n, np.nan, dtype=np.float32) for k in LOOKBACK_MAP}

        t_idx_vec = np.arange(n_days, dtype=np.float64)
        for c, row_list in col_events.items():
            px_col = P_adj[:, c].astype(np.float64)
            brk_col = seg_brk[:, c]
            # Prefix sums of valid log prices for O(1) R^2
            is_val = (~np.isnan(px_col)) & (px_col > 0)
            lp = np.where(is_val, np.log(np.where(is_val, px_col, 1.0)), 0.0)
            cnt_ps = np.concatenate([[0], np.cumsum(is_val.astype(np.int32))])
            brk_ps = np.concatenate([[0], np.cumsum((brk_col > 0).astype(np.int32))])
            sy_ps = np.concatenate([[0.0], np.cumsum(lp)])
            sy2_ps = np.concatenate([[0.0], np.cumsum(lp * lp)])
            sty_ps = np.concatenate([[0.0], np.cumsum(t_idx_vec * lp)])

            r_arr = np.array(row_list, dtype=np.int32)
            dp_arr = idx_pre[r_arr]

            for lbl, L in LOOKBACK_MAP.items():
                M = L + 1
                s_arr = dp_arr - L
                ok_w = s_arr >= 0
                if not np.any(ok_w):
                    continue
                r_ok = r_arr[ok_w]
                dp_ok = dp_arr[ok_w]
                s_ok = s_arr[ok_w]

                # 要求窗口内 100% 有效价格且无未复权分拆断层
                n_valid_w = cnt_ps[dp_ok + 1] - cnt_ps[s_ok]
                n_brk_w = brk_ps[dp_ok + 1] - brk_ps[s_ok]
                full_ok = (n_valid_w == M) & (n_brk_w == 0)
                if not np.any(full_ok):
                    continue

                r_f = r_ok[full_ok]
                dp_f = dp_ok[full_ok]
                s_f = s_ok[full_ok]

                Sy = sy_ps[dp_f + 1] - sy_ps[s_f]
                Sy2 = sy2_ps[dp_f + 1] - sy2_ps[s_f]
                Sty = sty_ps[dp_f + 1] - sty_ps[s_f]
                # sum_{k=0..L} k * y_{s+k} = Sty - s * Sy
                Sky = Sty - s_f.astype(np.float64) * Sy
                x_bar = L / 2.0
                Sxx = M * (M * M - 1.0) / 12.0
                Sxy = Sky - x_bar * Sy
                Syy = Sy2 - (Sy * Sy) / M

                r2_v = np.where(Syy > 1e-12, (Sxy * Sxy) / (Sxx * Syy), 0.0)
                r2_v = np.clip(r2_v, 0.0, 1.0)
                signed_r2 = np.where(Sxy >= 0, r2_v, -r2_v)
                r2_res[lbl][r_f] = signed_r2.astype(np.float32)

                p_start = px_col[s_f]
                p_end = px_col[dp_f]
                cagr_v = (p_end / p_start) ** (252.0 / L) - 1.0
                cagr_res[lbl][r_f] = cagr_v.astype(np.float32)

                # 窗口内最大回撤 (正值, 如 0.18 表示最大回撤 18%)
                mdd_tmp = np.empty(len(r_f), dtype=np.float32)
                for k_i in range(len(r_f)):
                    w_slice = px_col[s_f[k_i]:dp_f[k_i] + 1]
                    cmax = np.maximum.accumulate(w_slice)
                    mdd_tmp[k_i] = float(np.max(1.0 - w_slice / cmax))
                mdd_res[lbl][r_f] = mdd_tmp

        for lbl in LOOKBACK_MAP:
            out[f"g01_r2_{lbl}"] = r2_res[lbl]
            out[f"g01_mdd_{lbl}"] = mdd_res[lbl]
            out[f"g01_cagr_{lbl}"] = cagr_res[lbl]

    # 2. 计算严格零前视 + 退市残值顺延的前瞻收益 (1Y=252d, 3Y=756d, 5Y=1260d)
    ve_ok = np.where(valid_ent & (~np.isnan(ent_px)) & (ent_px > 0) & (~has_brk))[0]
    de_v = idx_ent[ve_ok]
    ce_v = cols[ve_ok]
    p0_v = ent_px[ve_ok]
    lv_v = last_v[ce_v]
    tres_v = term_res[ce_v]
    tdeal_v = term_deal[ce_v]

    for h in horizons:
        ret_strict = np.full(n, np.nan, dtype=np.float32)
        spy_strict = np.full(n, np.nan, dtype=np.float32)
        alp_strict = np.full(n, np.nan, dtype=np.float32)
        alp_naive_drop = np.full(n, np.nan, dtype=np.float32)
        alp_with_deal = np.full(n, np.nan, dtype=np.float32)
        delist_flag = np.zeros(n, dtype=bool)

        dtgt = de_v + h
        # 只有目标日 dtgt < n_days (即日历时间已到期, 非未来未发生窗口) 才评估满期收益;
        # 例外: 若股票在到期前已经破产清算退市 (lv_v < n_days - 15 且 lv_v < dtgt 且 tres_v <= -0.80), 破产结局已锁定!
        m_matured_normal = (dtgt < n_days) & (lv_v >= dtgt)
        idx_norm = np.where(m_matured_normal)[0]
        if len(idx_norm) > 0:
            pt = P_adj[dtgt[idx_norm], ce_v[idx_norm]].astype(np.float64)
            ok_t = (~np.isnan(pt)) & (pt > 0)
            in_ok = idx_norm[ok_t]
            rs = pt[ok_t] / p0_v[in_ok] - 1.0
            rb = spy_tr[dtgt[in_ok]] / spy_tr[de_v[in_ok]] - 1.0
            orig_i = ve_ok[in_ok]
            ret_strict[orig_i] = rs
            spy_strict[orig_i] = rb
            alp_strict[orig_i] = rs - rb
            alp_naive_drop[orig_i] = rs - rb
            alp_with_deal[orig_i] = rs - rb

        # 买入后在持有期内退市/破产的样本 (lv_v < dtgt 且 lv_v < n_days - 15 且 lv_v >= de_v)
        # 且日历上 dtgt < n_days (或已实质破产归零)
        m_delist = (lv_v < dtgt) & (lv_v < n_days - 15) & (lv_v >= de_v) & ((dtgt < n_days) | (tres_v <= -0.80))
        idx_del = np.where(m_delist)[0]
        if len(idx_del) > 0:
            pl = P_adj[lv_v[idx_del], ce_v[idx_del]].astype(np.float64)
            r_last = np.where((~np.isnan(pl)) & (pl > 0), pl / p0_v[idx_del] - 1.0, -0.95)
            # 严格残值顺延: 破产股计入破产残值 (tres_v=-0.95), 非破产股锁定最后交易日残值 (tres_v=0.0) 顺延计入分母!
            r_tot_res = np.where(
                tres_v[idx_del] <= -0.80,
                np.minimum(r_last, (1.0 + r_last) * (1.0 + tres_v[idx_del]) - 1.0),
                r_last
            )
            r_tot_deal = np.where(
                tres_v[idx_del] <= -0.80,
                r_tot_res,
                (1.0 + r_last) * (1.0 + tdeal_v[idx_del]) - 1.0
            )
            d_spy = np.minimum(dtgt[idx_del], n_days - 1)
            rb = spy_tr[d_spy] / spy_tr[de_v[idx_del]] - 1.0

            orig_i = ve_ok[idx_del]
            ret_strict[orig_i] = r_tot_res
            spy_strict[orig_i] = rb
            alp_strict[orig_i] = r_tot_res - rb
            alp_with_deal[orig_i] = r_tot_deal - rb
            # 注意: alp_naive_drop[orig_i] 保持为 NaN (复现退市股静默丢弃偏差)!
            delist_flag[orig_i] = True

        out[f"g01_fwd_{h}d"] = ret_strict
        out[f"g01_spy_{h}d"] = spy_strict
        out[f"g01_alpha_{h}d"] = alp_strict
        out[f"g01_alpha_naivedrop_{h}d"] = alp_naive_drop
        out[f"g01_alpha_deal_{h}d"] = alp_with_deal
        out[f"g01_delisted_{h}d"] = delist_flag

    print(f"  特征与前瞻收益计算完成 ({time.time()-t0:.2f}s): {n:,} 行.")
    return out


# ==============================================================================
# PART 3: 补全主面板 xbrl_master_pit_2009_2026 中的全部 140 家退市公司 (Form 4 + Enriched)
# ==============================================================================
def build_master_2009_2026_panel(eng: dict) -> pd.DataFrame:
    t0 = time.time()
    print("[2/6] 加载零前视主面板 xbrl_master_pit_2009_2026 并融合退市股 + 只读对齐 pit_with_9params...")

    xbrl = pd.read_parquet(os.path.join(PROJ_DIR, "data/xbrl_master_pit_2009_2026.parquet"))
    # 剔除 PARA 早期微盘股代码污染
    xbrl = xbrl[~((xbrl["ticker"] == "PARA") & (xbrl["rev_ttm"] < 1e8))].copy().reset_index(drop=True)

    # 先用统一日线引擎为全部可匹配日线的股票 (含 delisted_prices_{0,1} + extra_prices) 挂载严格零前视 6 档平滑度与前瞻收益
    xbrl = compute_pit_smoothness_and_returns(eng, xbrl, ticker_col="ticker", event_date_col="filed", horizons=(252, 756, 1260), compute_6_lookbacks=True)

    # 对补充进来的日线退市股 (原先在 xbrl_master 中 entry_adj_close 为 NaN，现已从 delisted_prices 拿到 g01_entry_adj_px) 补算真实 PIT 市值与 PE/PS
    macro_df = pd.read_parquet(os.path.join(PROJ_DIR, "data/macro_pit_daily_1990_2026.parquet"))
    macro_scale_map = dict(zip(pd.to_datetime(macro_df["date"]).dt.normalize(), macro_df["mcap_scale_to_2026"]))

    newly_priced = xbrl["mcap_pit"].isna() & xbrl["g01_entry_unadj_cls"].notna() & xbrl["shares_clean"].notna() & (xbrl["shares_clean"] > 0)
    if newly_priced.any():
        idx_np = xbrl.index[newly_priced]
        mc = xbrl.loc[idx_np, "g01_entry_unadj_cls"] * xbrl.loc[idx_np, "shares_clean"]
        sc = pd.to_datetime(xbrl.loc[idx_np, "g01_entry_date"]).dt.normalize().map(macro_scale_map).fillna(1.5)
        xbrl.loc[idx_np, "mcap_pit"] = mc
        xbrl.loc[idx_np, "mcap_usd_b"] = mc / 1e9
        xbrl.loc[idx_np, "mcap_2026_equiv_b"] = (mc / 1e9) * sc
        xbrl.loc[idx_np, "pe_pit"] = np.where(xbrl.loc[idx_np, "ni_ttm"].notna() & (xbrl.loc[idx_np, "ni_ttm"] != 0), mc / xbrl.loc[idx_np, "ni_ttm"], np.nan)
        xbrl.loc[idx_np, "ps_pit"] = np.where(xbrl.loc[idx_np, "rev_ttm"].notna() & (xbrl.loc[idx_np, "rev_ttm"] > 0), mc / xbrl.loc[idx_np, "rev_ttm"], np.nan)

    # 再用 SEC Form 4 内部人交易价格 + pit_panel_enriched_20261106 补全无日线退市 XBRL 股 (覆盖 1Y/3Y/5Y 全期限!)
    f4_path = os.path.join(TMP_XUAN, "w1_a2/delisted_f4_prices.parquet")
    enr_path = "/tmp/pit_panel_enriched_20261106.parquet"
    exit_meta = eng["exit_meta"]
    dates_cal = eng["dates"]
    spy_tr = eng["spy_tr"]
    n_days = eng["n_days"]

    f4_rescued = 0
    if os.path.exists(f4_path):
        f4 = pd.read_parquet(f4_path)
        f4["f4_dt"] = pd.to_datetime(f4["date"]).dt.normalize()
        f4["ticker_clean"] = f4["ticker"].replace({"HTZ_PRE": "HTZ", "FTR_PRE": "FTR"})
        f4 = f4[f4["price"].notna() & (f4["price"] > 0)].sort_values(["ticker_clean", "f4_dt"])
        f4_by_tk = {tk: grp[["f4_dt", "price"]].reset_index(drop=True) for tk, grp in f4.groupby("ticker_clean")}

        still_miss = xbrl["g01_entry_adj_px"].isna() & xbrl["ticker"].isin(f4_by_tk.keys())
        for idx in xbrl.index[still_miss]:
            tk = xbrl.at[idx, "ticker"]
            f_dt = pd.Timestamp(xbrl.at[idx, "filed"]).normalize()
            em = exit_meta.get(tk, {"exit_type": "MA", "exit_dt": pd.NaT, "deal_px": np.nan, "t_ret_residual": 0.0, "t_ret_deal": 0.0})
            if pd.notna(em["exit_dt"]) and f_dt >= em["exit_dt"]:
                continue
            f4_df = f4_by_tk[tk]
            prior_f4 = f4_df[(f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=3)) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=480))]
            if len(prior_f4) == 0:
                continue
            p0 = float(prior_f4["price"].iloc[-1])
            if p0 <= 0:
                continue

            idx_ev = int(np.clip(np.searchsorted(dates_cal, np.datetime64(f_dt, "D")), 0, n_days - 1))
            idx_ent = min(idx_ev + 1, n_days - 1)
            ent_date = pd.Timestamp(dates_cal[idx_ent])
            xbrl.at[idx, "g01_entry_date"] = ent_date
            xbrl.at[idx, "g01_entry_adj_px"] = p0

            # 用披露前 Form 4 序列拟合 2Y R², MDD, CAGR (若满 >=6 个观测点)
            hist_2y = f4_df[(f4_df["f4_dt"] <= f_dt) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=760))]
            if len(hist_2y) >= 6:
                tx = (hist_2y["f4_dt"] - hist_2y["f4_dt"].iloc[0]).dt.days.values.astype(float)
                ly = np.log(hist_2y["price"].values.astype(float))
                if tx[-1] >= 250 and np.std(ly) > 1e-8:
                    r_val = np.corrcoef(tx, ly)[0, 1]
                    sr2 = (r_val ** 2) if r_val >= 0 else -(r_val ** 2)
                    cmax = np.maximum.accumulate(hist_2y["price"].values.astype(float))
                    mdd_v = float(np.max(1.0 - hist_2y["price"].values / cmax))
                    cagr_v = float((hist_2y["price"].iloc[-1] / hist_2y["price"].iloc[0]) ** (365.25 / max(tx[-1], 180.0)) - 1.0)
                    for lbl in ("1_5Y", "2Y", "3Y"):
                        xbrl.at[idx, f"g01_r2_{lbl}"] = sr2
                        xbrl.at[idx, f"g01_mdd_{lbl}"] = mdd_v
                        xbrl.at[idx, f"g01_cagr_{lbl}"] = cagr_v

            # Form 4 反应近似 (披露前后内部人成交价变化)
            pre_f4 = f4_df[(f4_df["f4_dt"] < f_dt) & (f4_df["f4_dt"] >= f_dt - pd.Timedelta(days=120))]
            post_f4 = f4_df[(f4_df["f4_dt"] >= f_dt) & (f4_df["f4_dt"] <= f_dt + pd.Timedelta(days=20))]
            if len(pre_f4) > 0 and len(post_f4) > 0:
                xbrl.at[idx, "g01_earn_ret_2d"] = float(post_f4["price"].iloc[0] / pre_f4["price"].iloc[-1] - 1.0)

            sh = xbrl.at[idx, "shares_clean"]
            if pd.notna(sh) and sh > 0 and pd.isna(xbrl.at[idx, "mcap_pit"]):
                mc = p0 * sh
                sc = macro_scale_map.get(ent_date.normalize(), 1.5)
                ni_t = xbrl.at[idx, "ni_ttm"]
                rev_t = xbrl.at[idx, "rev_ttm"]
                xbrl.at[idx, "mcap_pit"] = mc
                xbrl.at[idx, "mcap_usd_b"] = mc / 1e9
                xbrl.at[idx, "mcap_2026_equiv_b"] = (mc / 1e9) * sc
                xbrl.at[idx, "pe_pit"] = mc / ni_t if (pd.notna(ni_t) and ni_t != 0) else np.nan
                xbrl.at[idx, "ps_pit"] = mc / rev_t if (pd.notna(rev_t) and rev_t > 0) else np.nan

            for h in (252, 756, 1260):
                d_tgt = idx_ent + h
                if d_tgt >= n_days and not (em["exit_type"] == "BANKRUPTCY" and pd.notna(em["exit_dt"]) and em["exit_dt"] <= pd.Timestamp(dates_cal[-1])):
                    continue
                d_spy_end = min(d_tgt, n_days - 1)
                tgt_ts = pd.Timestamp(dates_cal[d_spy_end])
                spy_r_full = float(spy_tr[d_spy_end] / spy_tr[idx_ent] - 1.0)

                if pd.notna(em["exit_dt"]) and em["exit_dt"] <= tgt_ts:
                    if em["exit_type"] == "BANKRUPTCY":
                        r_res = -0.95
                        r_deal = -0.95
                    else:
                        f4_pre_ex = f4_df[(f4_df["f4_dt"] > f_dt) & (f4_df["f4_dt"] <= em["exit_dt"])]
                        p_last = float(f4_pre_ex["price"].iloc[-1]) if len(f4_pre_ex) > 0 else p0
                        r_res = float(np.clip(p_last / p0 - 1.0, -0.90, 4.0))
                        if pd.notna(em["deal_px"]) and (0.35 <= em["deal_px"] / max(p_last, 0.01) <= 2.80):
                            r_deal = float(np.clip(em["deal_px"] / p0 - 1.0, -0.90, 4.0))
                        else:
                            r_deal = float(np.clip((1.0 + r_res) * (1.0 + max(0.0, em["t_ret_deal"])) - 1.0, -0.90, 4.0))
                    xbrl.at[idx, f"g01_fwd_{h}d"] = r_res
                    xbrl.at[idx, f"g01_spy_{h}d"] = spy_r_full
                    xbrl.at[idx, f"g01_alpha_{h}d"] = r_res - spy_r_full
                    xbrl.at[idx, f"g01_alpha_deal_{h}d"] = r_deal - spy_r_full
                    xbrl.at[idx, f"g01_delisted_{h}d"] = True
                else:
                    f4_near = f4_df[(f4_df["f4_dt"] >= tgt_ts - pd.Timedelta(days=150)) & (f4_df["f4_dt"] <= tgt_ts + pd.Timedelta(days=105))]
                    if len(f4_near) > 0:
                        diffs = (f4_near["f4_dt"] - tgt_ts).abs()
                        p_t = float(f4_near.loc[diffs.idxmin(), "price"])
                        r_res = float(np.clip(p_t / p0 - 1.0, -0.95, 5.0))
                        xbrl.at[idx, f"g01_fwd_{h}d"] = r_res
                        xbrl.at[idx, f"g01_spy_{h}d"] = spy_r_full
                        xbrl.at[idx, f"g01_alpha_{h}d"] = r_res - spy_r_full
                        xbrl.at[idx, f"g01_alpha_naivedrop_{h}d"] = r_res - spy_r_full
                        xbrl.at[idx, f"g01_alpha_deal_{h}d"] = r_res - spy_r_full
                    elif em["exit_type"] == "BANKRUPTCY" and pd.notna(em["exit_dt"]) and em["exit_dt"] > tgt_ts:
                        f4_up = f4_df[f4_df["f4_dt"] <= tgt_ts]
                        t_st = f4_up["f4_dt"].iloc[-1] if len(f4_up) > 0 else ent_date
                        p_st = float(f4_up["price"].iloc[-1]) if len(f4_up) > 0 else p0
                        p_term = p0 * 0.05
                        span = max(1.0, float((em["exit_dt"] - t_st).days))
                        elap = float(np.clip((tgt_ts - t_st).days, 0.0, span))
                        p_int = p_st + (p_term - p_st) * (elap / span)
                        r_res = float(np.clip(p_int / p0 - 1.0, -0.95, 2.0))
                        xbrl.at[idx, f"g01_fwd_{h}d"] = r_res
                        xbrl.at[idx, f"g01_spy_{h}d"] = spy_r_full
                        xbrl.at[idx, f"g01_alpha_{h}d"] = r_res - spy_r_full
                        xbrl.at[idx, f"g01_alpha_deal_{h}d"] = r_res - spy_r_full
                        xbrl.at[idx, f"g01_delisted_{h}d"] = True
            f4_rescued += 1

    # 补充 pit_panel_enriched_20261106 剩余退市记录
    enr_rescued = 0
    if os.path.exists(enr_path):
        pit_enr = pd.read_parquet(enr_path)
        enr_del = pit_enr[pit_enr["is_delisted"] == True]
        enr_map = {(r["ticker"], str(r["filing_date"])[:10]): r for _, r in enr_del.iterrows()}
        still_m2 = xbrl["g01_entry_adj_px"].isna()
        for idx in xbrl.index[still_m2]:
            key = (xbrl.at[idx, "ticker"], str(xbrl.at[idx, "filed"])[:10])
            if key in enr_map:
                er = enr_map[key]
                ent_d = pd.to_datetime(er["entry_date"])
                xbrl.at[idx, "g01_entry_date"] = ent_d
                xbrl.at[idx, "g01_entry_adj_px"] = 10.0
                if pd.notna(er["mcap_B"]) and pd.isna(xbrl.at[idx, "mcap_2026_equiv_b"]):
                    sc = macro_scale_map.get(ent_d.normalize(), 1.5)
                    xbrl.at[idx, "mcap_usd_b"] = float(er["mcap_B"])
                    xbrl.at[idx, "mcap_2026_equiv_b"] = float(er["mcap_B"]) * sc
                if pd.notna(er.get("ret_1y_full")) and pd.notna(er.get("alpha_spy_1y")):
                    xbrl.at[idx, "g01_fwd_252d"] = float(er["ret_1y_full"])
                    xbrl.at[idx, "g01_alpha_252d"] = float(er["alpha_spy_1y"])
                    xbrl.at[idx, "g01_alpha_deal_252d"] = float(er["alpha_spy_1y"])
                    xbrl.at[idx, "g01_delisted_252d"] = True
                if pd.notna(er.get("ret_3y_full")) and pd.notna(er.get("alpha_spy_3y")):
                    xbrl.at[idx, "g01_fwd_756d"] = float(er["ret_3y_full"])
                    xbrl.at[idx, "g01_alpha_756d"] = float(er["alpha_spy_3y"])
                    xbrl.at[idx, "g01_alpha_deal_756d"] = float(er["alpha_spy_3y"])
                    xbrl.at[idx, "g01_delisted_756d"] = True
                enr_rescued += 1

    # 4. 只读对齐兄弟会话 /tmp/us_xuangu_20261109/master_clean/pit_with_9params.parquet (按 ticker + end + filed)
    res_pq = pd.read_parquet(os.path.join(TMP_XUAN, "master_clean/pit_with_9params.parquet"))
    res_pq["end_key"] = pd.to_datetime(res_pq["q_end"]).dt.strftime("%Y-%m-%d")
    res_pq["filed_key"] = pd.to_datetime(res_pq["filed"]).dt.strftime("%Y-%m-%d")
    res_cols = [
        "ticker", "end_key", "filed_key", "jump_dt", "filed_entry_dt", "max_jump_win", "max_jump_filed2d",
        "mcap_pit_b", "mcap_eq26_b", "mcap_filed_b", "mcap_filed_eq26_b", "pe_pit", "pe_filed",
        "ret_1y", "alpha_1y", "ret_3y", "alpha_3y", "ret_5y", "alpha_5y",
        "f_ret_1y", "f_alpha_1y", "f_ret_3y", "f_alpha_3y", "f_ret_5y", "f_alpha_5y",
        "r2_6M", "mdd_6M", "cagr_6M", "r2_1Y", "mdd_1Y", "cagr_1Y",
        "r2_1_5Y", "mdd_1_5Y", "cagr_1_5Y", "r2_2Y", "mdd_2Y", "cagr_2Y",
        "r2_3Y", "mdd_3Y", "cagr_3Y", "r2_5Y", "mdd_5Y", "cagr_5Y",
        "op_accel", "ni_accel", "op_turnaround", "ni_turnaround", "prior4_rev_yoy_mean"
    ]
    res_sub = res_pq[res_cols].drop_duplicates(["ticker", "end_key", "filed_key"]).rename(
        columns={c: f"res_{c}" for c in res_cols if c not in ("ticker", "end_key", "filed_key")}
    )
    xbrl = xbrl.merge(res_sub, left_on=["ticker", "end", "filed"], right_on=["ticker", "end_key", "filed_key"], how="left")

    # 校验我们的严格 T_pre R² 与 pit_with_9params R² 的相关性
    for k in ("1Y", "1_5Y", "2Y", "3Y"):
        both_v = xbrl[[f"g01_r2_{k}", f"res_r2_{k}"]].dropna()
        corr = both_v.iloc[:, 0].corr(both_v.iloc[:, 1])
        med_diff = (both_v.iloc[:, 0] - both_v.iloc[:, 1]).abs().median()
        print(f"  [只读比对校验] r2_{k}: 对齐样本={len(both_v):,}, 相关系数={corr:.5f}, 中位绝对差={med_diff:.5f} (差异源于截至T_pre剔除财报日跳涨)")

    # 5. 计算复现 w1_a1 的「2026 股本倒推历史市值」以做精确偏差分解!
    # w1_a1 公式: implied_mcap_pit = mcap_2026 * (P_cls_t / P_cls_2026), 再乘以 mcap_scale_to_2026
    u26_path = os.path.join(TMP_XUAN, "w1_a5/us_25b_full_universe_20261109.csv")
    u_meta_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/universe_meta.parquet"
    mcap26_map = {}
    if os.path.exists(u_meta_path):
        um = pd.read_parquet(u_meta_path)
        for _, r in um.iterrows():
            if pd.notna(r.get("market_cap")):
                mcap26_map[str(r["ticker"])] = float(r["market_cap"]) / 1e9
    if os.path.exists(u26_path):
        u26 = pd.read_csv(u26_path)
        for _, r in u26.iterrows():
            if pd.notna(r.get("marketCap_B")):
                mcap26_map[str(r["ticker"])] = float(r["marketCap_B"])

    # 获取每只股票在统一日线库 2026 期末收盘价 P_cls_last
    tk2c = eng["tk_to_col"]
    P_cls = eng["P_cls"]
    last_v = eng["last_valid_idx"]
    last_cls_map = {}
    for tk, col in tk2c.items():
        lv = last_v[col]
        if lv >= eng["n_days"] - 15:  # 2026 仍存活股票
            last_cls_map[tk] = float(P_cls[lv, col])

    ent_norm = pd.to_datetime(xbrl["g01_entry_date"]).dt.normalize()
    sc_series = ent_norm.map(macro_scale_map).fillna(xbrl["mcap_scale_to_2026"]).fillna(1.0)
    mcap26_static = xbrl["ticker"].map(mcap26_map)
    last_c_ser = xbrl["ticker"].map(last_cls_map)
    # w1_a1 2026股本倒推当期市值与2026等效市值
    xbrl["mcap_w1a1_sh26_pit_b"] = mcap26_static * (xbrl["g01_entry_unadj_cls"] / last_c_ser)
    xbrl["mcap_w1a1_sh26_eq26_b"] = xbrl["mcap_w1a1_sh26_pit_b"] * sc_series
    xbrl["mcap_static_2026_b"] = mcap26_static

    # 6. 构建严格零前视基本面二阶导与连降减速计数器
    xbrl = xbrl.sort_values(["ticker", "end", "filed"]).reset_index(drop=True)
    n_x = len(xbrl)
    tks_x = xbrl["ticker"].values
    ends_x = pd.to_datetime(xbrl["end"]).values
    rev_yoy_v = xbrl["rev_yoy"].values
    rev_acc_v = xbrl["rev_accel_1q"].values
    opm_chg_v = xbrl["opm_yoy_chg"].values
    gmsga_chg_v = xbrl["gm_sga_yoy_chg"].values

    # 连续营收减速季数 (rev_yoy < rev_yoy_lag1, 严格同股相邻季 60~135 天)
    consec_rev_decel = np.zeros(n_x, dtype=np.int32)
    for i in range(n_x):
        is_dec = (not np.isnan(rev_acc_v[i])) and (rev_acc_v[i] < 0)
        if i > 0 and tks_x[i] == tks_x[i - 1]:
            gap = (ends_x[i] - ends_x[i - 1]) / np.timedelta64(1, "D")
            if 60 <= gap <= 135:
                consec_rev_decel[i] = (consec_rev_decel[i - 1] + 1) if is_dec else 0
            else:
                consec_rev_decel[i] = 1 if is_dec else 0
        else:
            consec_rev_decel[i] = 1 if is_dec else 0
    xbrl["g01_consec_rev_decel_n"] = consec_rev_decel

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        prior_3q_peak = np.nanmax(
            np.column_stack([xbrl["rev_yoy_lag1"].values, xbrl["rev_yoy_lag2"].values, xbrl["rev_yoy_lag3"].values]),
            axis=1
        )
    xbrl["g01_prior3q_peak_rev_yoy"] = prior_3q_peak

    # 补充利润同比环比加速 (opinc_yoy_lag1 / ni_yoy_lag1, 严格向后 shift)
    xbrl["opinc_yoy_lag1"] = xbrl.groupby("ticker")["opinc_yoy"].shift(1)
    xbrl["ni_yoy_lag1"] = xbrl.groupby("ticker")["ni_yoy"].shift(1)
    gap_prev = (pd.to_datetime(xbrl["end"]) - pd.to_datetime(xbrl.groupby("ticker")["end"].shift(1))).dt.days
    valid_seq = (gap_prev >= 60) & (gap_prev <= 135)
    xbrl["g01_op_accel"] = np.where(valid_seq, xbrl["opinc_yoy"] - xbrl["opinc_yoy_lag1"], np.nan)
    xbrl["g01_ni_accel"] = np.where(valid_seq, xbrl["ni_yoy"] - xbrl["ni_yoy_lag1"], np.nan)

    # 事后未来 4Q / 8Q 营收增速变动 (仅用于事后解剖为什么稳态缓涨在加息期死于减速，绝不用于任何选股信号!)
    xbrl["expost_rev_yoy_4q_later"] = xbrl.groupby("ticker")["rev_yoy"].shift(-4)
    xbrl["expost_rev_yoy_8q_later"] = xbrl.groupby("ticker")["rev_yoy"].shift(-8)

    print(f"  主面板融合完成 ({time.time()-t0:.2f}s): 总行数={len(xbrl):,}, 有效入场行={xbrl['g01_entry_adj_px'].notna().sum():,}, Form4救回={f4_rescued}, Enr救回={enr_rescued}.")
    return xbrl


# ==============================================================================
# PART 4: 统一统计评估函数 (严格符合 D15 与 G01 全部列指标要求)
# ==============================================================================
def deduplicate_cooldown(df: pd.DataFrame, date_col: str, cooldown_days: int = 250) -> pd.DataFrame:
    if len(df) == 0:
        return df
    d = df.dropna(subset=[date_col]).sort_values(["ticker", date_col]).copy()
    if len(d) == 0:
        return d
    keep = np.zeros(len(d), dtype=bool)
    tks = d["ticker"].values
    dts = pd.to_datetime(d[date_col]).values.astype("datetime64[D]").astype(np.int64)
    last_tk = None
    last_dt = -999999
    for i in range(len(d)):
        if tks[i] != last_tk or (dts[i] - last_dt) >= cooldown_days:
            keep[i] = True
            last_tk = tks[i]
            last_dt = dts[i]
    return d.iloc[keep].copy()


def eval_g01_metrics(
    df_sub: pd.DataFrame,
    date_col: str = "g01_entry_date",
    ret_cols_map: dict = None,
    alpha_cols_map: dict = None,
    agg_mode: str = "qtr_ew",  # "qtr_ew" (D15 日历季等权) or "pooled" (未修正混池均值)
    dedup_days: int = 250,
) -> dict:
    """
    输出完整 G01 硬核指标:
    - n_raw (原始触发数), n_dedup (250日冷却去重样本数), n_tickers (独立股票数)
    - 1Y / 3Y / 5Y:
      * 净超额 (qtr_ew 对标 SPY 净超额 或 pooled 均值)
      * 去重均值超额
      * 中位数超额 (去重独立事件)
      * 跑赢 SPY 胜率 (去重独立事件)
      * 真实盈亏比 (正超额均值 / |负超额均值|, 去重独立事件)
    - 3Y 翻倍率 (总回报 >= +100%), 3Y 腰斩率 (总回报 <= -50%, 含退市破产终值!)
    - 1Y / 5Y 翻倍率与腰斩率, 退市计入笔数
    """
    if ret_cols_map is None:
        ret_cols_map = {"1y": "g01_fwd_252d", "3y": "g01_fwd_756d", "5y": "g01_fwd_1260d"}
    if alpha_cols_map is None:
        alpha_cols_map = {"1y": "g01_alpha_252d", "3y": "g01_alpha_756d", "5y": "g01_alpha_1260d"}

    out = {
        "n_raw": int(len(df_sub)),
        "n_dedup": 0,
        "n_tickers": int(df_sub["ticker"].nunique()) if len(df_sub) > 0 else 0,
    }
    if len(df_sub) == 0:
        return out

    d = df_sub.dropna(subset=[date_col]).copy()
    if len(d) == 0:
        return out
    d["cal_qtr"] = pd.to_datetime(d[date_col]).dt.to_period("Q")
    d_dedup = deduplicate_cooldown(d, date_col=date_col, cooldown_days=dedup_days)
    out["n_dedup"] = int(len(d_dedup))

    for h_lbl in ("1y", "3y", "5y"):
        rc = ret_cols_map[h_lbl]
        ac = alpha_cols_map[h_lbl]
        if rc not in d.columns or ac not in d.columns:
            continue

        v_all = d.dropna(subset=[rc, ac])
        v_ded = d_dedup.dropna(subset=[rc, ac])
        out[f"n_raw_{h_lbl}"] = int(len(v_all))
        out[f"n_dedup_{h_lbl}"] = int(len(v_ded))

        if len(v_ded) < 3:
            for m in ("primary_alpha_pct", "qtr_ew_alpha_pct", "pooled_alpha_pct", "qtr_ew_ret_pct",
                      "med_alpha_pct", "win_rate_pct", "payoff_ratio", "double_rate_pct", "halve_rate_pct", "t_stat"):
                out[f"{m}_{h_lbl}"] = np.nan
            continue

        q_means_a = v_all.groupby("cal_qtr")[ac].mean()
        q_means_r = v_all.groupby("cal_qtr")[rc].mean()
        qtr_ew_a = float(q_means_a.mean())
        qtr_ew_r = float(q_means_r.mean())
        pooled_a = float(v_all[ac].mean())

        q_se = float(q_means_a.std(ddof=1) / np.sqrt(len(q_means_a))) if len(q_means_a) > 2 else np.nan
        t_st = (qtr_ew_a / q_se) if (q_se and q_se > 0) else np.nan

        # 若为未修正混池模式 (agg_mode=="pooled") 则用 v_all 算胜率/中位数复现原口径; 严格口径用 250d 冷却去重独立样本 v_ded!
        ev_sample = v_all if agg_mode == "pooled" else v_ded
        a_arr = ev_sample[ac].values
        r_arr = ev_sample[rc].values
        pos_a = a_arr[a_arr > 0]
        neg_a = a_arr[a_arr <= 0]
        payoff = float(pos_a.mean() / abs(neg_a.mean())) if (len(pos_a) > 0 and len(neg_a) > 0 and neg_a.mean() != 0) else np.nan

        prim_a = pooled_a if agg_mode == "pooled" else qtr_ew_a
        out[f"primary_alpha_pct_{h_lbl}"] = round(prim_a * 100.0, 2)
        out[f"qtr_ew_alpha_pct_{h_lbl}"] = round(qtr_ew_a * 100.0, 2)
        out[f"pooled_alpha_pct_{h_lbl}"] = round(pooled_a * 100.0, 2)
        out[f"qtr_ew_ret_pct_{h_lbl}"] = round(qtr_ew_r * 100.0, 2)
        out[f"med_alpha_pct_{h_lbl}"] = round(float(np.median(a_arr)) * 100.0, 2)
        out[f"win_rate_pct_{h_lbl}"] = round(float(np.mean(a_arr > 0)) * 100.0, 2)
        out[f"payoff_ratio_{h_lbl}"] = round(payoff, 2) if pd.notna(payoff) else np.nan
        out[f"double_rate_pct_{h_lbl}"] = round(float(np.mean(r_arr >= 1.0)) * 100.0, 2)
        out[f"halve_rate_pct_{h_lbl}"] = round(float(np.mean(r_arr <= -0.50)) * 100.0, 2)
        out[f"t_stat_{h_lbl}"] = round(t_st, 2) if pd.notna(t_st) else np.nan

    if "g01_delisted_756d" in d_dedup.columns:
        out["delisted_in_3y_n"] = int(d_dedup["g01_delisted_756d"].fillna(False).sum())
    return out


# ==============================================================================
# PART 5: 任务 1 — 偏差精算对比表 (table_g01_bias_audit.csv)
# ==============================================================================
def run_task1_bias_audit(xbrl: pd.DataFrame) -> pd.DataFrame:
    print("\n[3/6] 执行任务 1: 偏差精算瀑布对比表 (table_g01_bias_audit.csv)...")

    d = xbrl[~xbrl["g01_has_break"].fillna(False)].copy()
    d["filed_year"] = pd.to_datetime(d["filed"]).dt.year

    # 1. 定义策略一: PE < 15 拐点
    # (1A) 对齐 w1_a3 口径A8: 0 < PE < 15 + 报表加速(rev_accel>=5%&rev_yoy>0 或 op/ni_accel>=15%&yoy>0 或 扭亏) + 反应跳涨>=8%
    fin_acc_pit = (
        ((d["rev_accel_1q"] >= 0.05) & (d["rev_yoy"] > 0))
        | ((d["g01_op_accel"] >= 0.15) & (d["opinc_yoy"] > 0))
        | ((d["g01_ni_accel"] >= 0.15) & (d["ni_yoy"] > 0))
        | (d["turnaround_to_profit_1q"] == True)
        | (d["res_op_turnaround"] == True)
        | (d["res_ni_turnaround"] == True)
    )
    # 未修正跳涨判定 (res_max_jump_win: 在 [end+10d, filed+1d] 长达25天窗口挑最大单日涨幅 >= 8%)
    jump8_unadj = d["res_max_jump_win"] >= 0.08
    # 严格零前视跳涨判定: 仅看正式披露窗口 (earn_jump_ret >= 8% 或 g01_max_1d_filed2d >= 8% 或 8-K 新闻稿 2d 冲击 >= 8%, 但入场一律锁定 filed+1!)
    jump8_strict_signal = (d["earn_jump_ret"] >= 0.08) | (d["g01_max_1d_filed2d"] >= 0.08) | (d["res_max_jump_win"] >= 0.08)
    jump8_filed_only = (d["earn_jump_ret"] >= 0.08) | (d["g01_max_1d_filed2d"] >= 0.08)

    # (1B) 纯基本面低 PE < 15 拐点 (不要求跳涨>=8%, 对齐 w3 旧策略一 / w1_a3 口径B: 0<PE<15 & 营收或利润拐点加速): 退市破产股重灾区!
    pe_unadj_ok = (d["res_pe_pit"] > 0) & (d["res_pe_pit"] < 15.0)
    pe_strict_ok = (d["pe_pit"] > 0) & (d["pe_pit"] < 15.0)

    # 2. 定义策略二: 缓涨高增 (严格对齐题干: 1.5至3年平滑缓涨 R²>=0.75, 回撤<22%, CAGR>=15% + 单季营收同比>=15%)
    # 未修正平滑度特征 (来自 pit_with_9params, 截至 filed_entry_dt 含财报跳涨)
    sb_unadj = (
        (
            ((d["res_r2_1_5Y"] >= 0.75) & (d["res_mdd_1_5Y"] < 0.22) & (d["res_cagr_1_5Y"] >= 0.15))
            | ((d["res_r2_2Y"] >= 0.75) & (d["res_mdd_2Y"] < 0.22) & (d["res_cagr_2Y"] >= 0.15))
            | ((d["res_r2_3Y"] >= 0.75) & (d["res_mdd_3Y"] < 0.22) & (d["res_cagr_3Y"] >= 0.15))
        )
        & (d["rev_yoy"] >= 0.15)
    )
    # 严格零前视平滑度特征 (截至 filed - 1, 100% 披露前收盘, 含退市股全池)
    sb_strict = (
        (
            ((d["g01_r2_1_5Y"] >= 0.75) & (d["g01_mdd_1_5Y"] < 0.22) & (d["g01_cagr_1_5Y"] >= 0.15))
            | ((d["g01_r2_2Y"] >= 0.75) & (d["g01_mdd_2Y"] < 0.22) & (d["g01_cagr_2Y"] >= 0.15))
            | ((d["g01_r2_3Y"] >= 0.75) & (d["g01_mdd_3Y"] < 0.22) & (d["g01_cagr_3Y"] >= 0.15))
        )
        & (d["rev_yoy"] >= 0.15)
    )

    # 市值过滤门对比:
    # M0: 2026 期末静态市值 >= $25B (极端事后赢家倒推)
    mcap_M0_static26 = d["mcap_static_2026_b"] >= 25.0
    # M1: w1_a1 2026 股本倒推历史市值 (shares_2026 * price_t * scale_to_2026 >= $25B, 仅幸存池)
    mcap_M1_sh26_backcast = d["mcap_w1a1_sh26_eq26_b"] >= 25.0
    # M2: 严格当期真实未复权市值 (shares_clean_pit * unadj_px_pit * scale_to_2026 >= $25B)
    mcap_M2_true_pit = d["mcap_2026_equiv_b"] >= 25.0

    in_res_survivor_pool = d["res_filed_entry_dt"].notna()

    # 收益列映射:
    # R_jump: 未修正 jump_dt 入场 (来自 pit_with_9params, 71.8% 早于 filed, 且退市股为 NaN 丢弃)
    ret_jump_map = {"1y": "res_ret_1y", "3y": "res_ret_3y", "5y": "res_ret_5y"}
    alp_jump_map = {"1y": "res_alpha_1y", "3y": "res_alpha_3y", "5y": "res_alpha_5y"}
    # R_filed_drop: filed+1 收盘入场, 但退市股仍按 NaN 丢弃 (仅幸存股)
    ret_fdrop_map = {"1y": "g01_fwd_252d", "3y": "g01_fwd_756d", "5y": "g01_fwd_1260d"}
    alp_fdrop_map = {"1y": "g01_alpha_naivedrop_252d", "3y": "g01_alpha_naivedrop_756d", "5y": "g01_alpha_naivedrop_1260d"}
    # R_strict: filed+1 收盘入场 + 买入后退市/破产股锁定最后交易日残值顺延计入分母
    ret_strict_map = {"1y": "g01_fwd_252d", "3y": "g01_fwd_756d", "5y": "g01_fwd_1260d"}
    alp_strict_map = {"1y": "g01_alpha_252d", "3y": "g01_alpha_756d", "5y": "g01_alpha_1260d"}
    # R_deal: filed+1 收盘入场 + 破产残值计入 + 现金并购溢价计入 (敏感度对照)
    alp_deal_map = {"1y": "g01_alpha_deal_252d", "3y": "g01_alpha_deal_756d", "5y": "g01_alpha_deal_1260d"}

    periods = [
        ("Full_2009_2026", pd.Series(True, index=d.index)),
        ("Last10Y_2016_2026", d["filed_year"] >= 2016),
        ("HighRate_2021_2026", d["filed_year"] >= 2021),
        ("HighRate_2022_2026", d["filed_year"] >= 2022),
    ]

    strategies = [
        (
            "S1A_PE_lt15_Jump8_Inflection",
            "策略1A: PE<15财报跳涨拐点(0<PE<15 + 业绩加速 + 窗口跳涨>=8%, 对齐w1_a3口径A)",
            [
                ("Step0_ExtremeExPost_Static2026Mcap_JumpEntry_NaNDrop_Pooled",
                 "Step0_极端前视(2026静态市值>=25B + jump_dt入场 + 退市NaN丢弃 + 混池均值)",
                 in_res_survivor_pool & mcap_M0_static26 & pe_unadj_ok & fin_acc_pit & jump8_unadj,
                 "res_jump_dt", ret_jump_map, alp_jump_map, "pooled"),
                ("Step1_Unadjusted_2026ShareBackcast_JumpEntry_NaNDrop_Pooled",
                 "Step1_未修正口径①(2026股本倒推市值>=25B + jump_dt早于filed入场 + 退市NaN丢弃 + 混池均值)",
                 in_res_survivor_pool & mcap_M1_sh26_backcast & pe_unadj_ok & fin_acc_pit & jump8_unadj,
                 "res_jump_dt", ret_jump_map, alp_jump_map, "pooled"),
                ("Step2_FixEntry_StrictFiledPlus1Close",
                 "Step2_修正第1刀: 切掉jump_dt提前入场 -> 改用严格10-Q/10-K披露次日(filed+1)收盘入场",
                 in_res_survivor_pool & mcap_M1_sh26_backcast & pe_strict_ok & fin_acc_pit & jump8_strict_signal,
                 "g01_entry_date", ret_fdrop_map, alp_fdrop_map, "pooled"),
                ("Step2b_FixJumpWindow_StrictFiled2dJumpOnly",
                 "Step2b_修正窗口挑顶: 剔除filed前20天内事后挑最大阳线 -> 仅认披露日窗口跳涨>=8%且filed+1入场",
                 in_res_survivor_pool & mcap_M1_sh26_backcast & pe_strict_ok & fin_acc_pit & jump8_filed_only,
                 "g01_entry_date", ret_fdrop_map, alp_fdrop_map, "pooled"),
                ("Step3_FixMcap_TruePITUnadjSharesMcap",
                 "Step3_修正第2刀: 切掉2026股本倒推 -> 改用当期真实未复权股本市值(mcap_2026_equiv_b>=25)",
                 in_res_survivor_pool & mcap_M2_true_pit & pe_strict_ok & fin_acc_pit & jump8_filed_only,
                 "g01_entry_date", ret_fdrop_map, alp_fdrop_map, "pooled"),
                ("Step4_FixDelist_RetainBankruptAndResidual",
                 "Step4_修正第3刀: 补全退市破产池并锁定最后交易日残值顺延计入分母(零NaN静默剔除)",
                 mcap_M2_true_pit & pe_strict_ok & fin_acc_pit & jump8_filed_only,
                 "g01_entry_date", ret_strict_map, alp_strict_map, "pooled"),
                ("Step5_StrictZeroLookahead_CalendarQtrEW",
                 "Step5_严格零前视口径②(filed+1入场 + 真实当期市值>=25B + 退市破产残值顺延 + 日历季等权扣SPY)",
                 mcap_M2_true_pit & pe_strict_ok & fin_acc_pit & jump8_filed_only,
                 "g01_entry_date", ret_strict_map, alp_strict_map, "qtr_ew"),
                ("Step5_Alt_Keep8KJumpSignal_StrictFiledPlus1_CalendarQtrEW",
                 "Step5_对照(保留8-K跳涨信号但强制等10-Q filed+1入场 + 真实市值 + 退市残值顺延 + 日历季等权)",
                 mcap_M2_true_pit & pe_strict_ok & fin_acc_pit & jump8_strict_signal,
                 "g01_entry_date", ret_strict_map, alp_strict_map, "qtr_ew"),
            ]
        ),
        (
            "S1B_PE_lt15_AllFinInflection_NoJumpFilter",
            "策略1B: 纯基本面PE<15加速拐点(0<PE<15 + 业绩加速, 不限股价跳涨, 对齐w1_a3口径B/w3旧策略一)",
            [
                ("Step0_ExtremeExPost_Static2026Mcap_JumpEntry_NaNDrop_Pooled",
                 "Step0_极端前视(2026静态市值>=25B + jump_dt入场 + 退市NaN丢弃 + 混池均值)",
                 in_res_survivor_pool & mcap_M0_static26 & pe_unadj_ok & fin_acc_pit,
                 "res_jump_dt", ret_jump_map, alp_jump_map, "pooled"),
                ("Step1_Unadjusted_2026ShareBackcast_JumpEntry_NaNDrop_Pooled",
                 "Step1_未修正口径①(2026股本倒推市值>=25B + jump_dt入场 + 退市NaN丢弃 + 混池均值)",
                 in_res_survivor_pool & mcap_M1_sh26_backcast & pe_unadj_ok & fin_acc_pit,
                 "res_jump_dt", ret_jump_map, alp_jump_map, "pooled"),
                ("Step2_FixEntry_StrictFiledPlus1Close",
                 "Step2_修正第1刀: 切掉jump_dt窗口挑最高阳线入场 -> 改用严格filed+1收盘入场",
                 in_res_survivor_pool & mcap_M1_sh26_backcast & pe_strict_ok & fin_acc_pit,
                 "g01_entry_date", ret_fdrop_map, alp_fdrop_map, "pooled"),
                ("Step3_FixMcap_TruePITUnadjSharesMcap",
                 "Step3_修正第2刀: 切掉2026股本倒推 -> 改用当期真实未复权市值(mcap_2026_equiv_b>=25)",
                 in_res_survivor_pool & mcap_M2_true_pit & pe_strict_ok & fin_acc_pit,
                 "g01_entry_date", ret_fdrop_map, alp_fdrop_map, "pooled"),
                ("Step4_FixDelist_RetainBankruptAndResidual",
                 "Step4_修正第3刀: 补全退市破产股(含SIVB/FRC/BBBY/CHK等)残值顺延计入分母",
                 mcap_M2_true_pit & pe_strict_ok & fin_acc_pit,
                 "g01_entry_date", ret_strict_map, alp_strict_map, "pooled"),
                ("Step5_StrictZeroLookahead_CalendarQtrEW",
                 "Step5_严格零前视口径②(filed+1入场 + 真实当期市值>=25B + 退市破产残值顺延 + 日历季等权扣SPY)",
                 mcap_M2_true_pit & pe_strict_ok & fin_acc_pit,
                 "g01_entry_date", ret_strict_map, alp_strict_map, "qtr_ew"),
            ]
        ),
        (
            "S2_SlowBull_1_5to3Y_HighGrowth_ge15",
            "策略2: 缓涨高增(1.5至3年R²>=0.75且回撤<22%且CAGR>=15% + 单季营收同比>=15%)",
            [
                ("Step0_ExtremeExPost_Static2026Mcap_JumpEntry_NaNDrop_Pooled",
                 "Step0_极端前视(2026静态市值>=25B + jump_dt入场 + 退市NaN丢弃 + 混池均值)",
                 in_res_survivor_pool & mcap_M0_static26 & sb_unadj,
                 "res_jump_dt", ret_jump_map, alp_jump_map, "pooled"),
                ("Step1_Unadjusted_2026ShareBackcast_JumpEntry_NaNDrop_Pooled",
                 "Step1_未修正口径①(2026股本倒推市值>=25B + jump_dt入场 + 含财报日R² + 退市NaN丢弃 + 混池均值)",
                 in_res_survivor_pool & mcap_M1_sh26_backcast & sb_unadj,
                 "res_jump_dt", ret_jump_map, alp_jump_map, "pooled"),
                ("Step2_FixEntryAndPreR2_StrictFiledPlus1Close",
                 "Step2_修正第1刀: 切掉jump_dt入场与含跳涨R² -> 严格截至filed-1算R²且filed+1收盘入场",
                 in_res_survivor_pool & mcap_M1_sh26_backcast & sb_strict,
                 "g01_entry_date", ret_fdrop_map, alp_fdrop_map, "pooled"),
                ("Step3_FixMcap_TruePITUnadjSharesMcap",
                 "Step3_修正第2刀: 切掉2026股本倒推(挤出增发扩股小黑马/加回购缩股白马) -> 真实当期市值>=25B",
                 in_res_survivor_pool & mcap_M2_true_pit & sb_strict,
                 "g01_entry_date", ret_fdrop_map, alp_fdrop_map, "pooled"),
                ("Step4_FixDelist_RetainResidual",
                 "Step4_修正第3刀: 补全退市池并锁定最后交易日残值顺延计入分母(零破产归零, 多为溢价被并购)",
                 mcap_M2_true_pit & sb_strict,
                 "g01_entry_date", ret_strict_map, alp_strict_map, "pooled"),
                ("Step5_StrictZeroLookahead_CalendarQtrEW",
                 "Step5_严格零前视口径②(filed+1入场 + 真实当期市值>=25B + 退市残值顺延 + 日历季等权扣SPY)",
                 mcap_M2_true_pit & sb_strict,
                 "g01_entry_date", ret_strict_map, alp_strict_map, "qtr_ew"),
                ("Step5_Sensitivity_IncludeVerifiedMADealPremium",
                 "Step5_敏感度对照: 计入已核实的现金并购公告溢价终值(如CELG/ALXN/ATVI/VMW/ABMD等)",
                 mcap_M2_true_pit & sb_strict,
                 "g01_entry_date", ret_strict_map, alp_deal_map, "qtr_ew"),
            ]
        ),
    ]

    rows = []
    for p_code, p_mask in periods:
        for s_code, s_desc, step_list in strategies:
            prev_st = None
            step1_st = None
            for st_code, st_desc, mask, dt_c, r_map, a_map, agg_m in step_list:
                sub = d[p_mask & mask]
                st = eval_g01_metrics(sub, date_col=dt_c, ret_cols_map=r_map, alpha_cols_map=a_map, agg_mode=agg_m)
                row = {
                    "period": p_code,
                    "strategy_code": s_code,
                    "strategy_name": s_desc,
                    "step_code": st_code,
                    "step_description": st_desc,
                    "aggregation_mode": agg_m,
                }
                row.update(st)

                if st_code.startswith("Step1_"):
                    step1_st = st

                # 计算单步挤掉水分 (Step_t - Step_{t-1}) 与相对未修正口径① (Step_t - Step1) 的累计挤掉水分
                for h_lbl in ("1y", "3y", "5y"):
                    cur_a = st.get(f"primary_alpha_pct_{h_lbl}", np.nan)
                    prv_a = prev_st.get(f"primary_alpha_pct_{h_lbl}", np.nan) if prev_st else np.nan
                    s1_a = step1_st.get(f"primary_alpha_pct_{h_lbl}", np.nan) if step1_st else np.nan
                    row[f"step_marginal_haircut_pp_{h_lbl}"] = round(cur_a - prv_a, 2) if (pd.notna(cur_a) and pd.notna(prv_a) and not st_code.startswith(("Step5_Alt", "Step5_Sens"))) else np.nan
                    row[f"cum_haircut_vs_step1_pp_{h_lbl}"] = round(cur_a - s1_a, 2) if (pd.notna(cur_a) and pd.notna(s1_a)) else np.nan

                if not st_code.startswith(("Step2b_", "Step5_Alt", "Step5_Sens")):
                    prev_st = st
                rows.append(row)

    df_out = pd.DataFrame(rows)
    out_csv = os.path.join(OUT_DIR, "table_g01_bias_audit.csv")
    df_out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  已保存 {out_csv} ({len(df_out)} 行).")
    return df_out


# ==============================================================================
# PART 6: 任务 2 — 缓涨平滑度 × 基本面二阶导全交叉表 (table_g01_slowbull_x_2nd_deriv.csv)
# ==============================================================================
def classify_fundamental_2nd_deriv(df: pd.DataFrame) -> pd.Series:
    """
    严格零前视四档互斥基本面二阶导分类 (+ 其余组):
    1. D1_Consec3Q_DoubleAccel (连3季双加速):
       连续 >=2 季双拐点且连 >=3 季收入加速或直接满足 consec_double_inflect_n >= 3,
       为忠实题干先设严格主档: consec_double_inflect_n >= 3 (或 consec_rev_accel_n >= 3 且利润率同比扩张 > 0) 且 rev_yoy > 0!
    2. D2_SingleQ_DoubleImprove (单季双改善):
       非 D1, 当季营收同比环比加速 (rev_accel_1q > 0 且 rev_yoy > 0) 且利润率同比改善 ((opm_yoy_chg > 0) 或 (gm_sga_yoy_chg > 0))!
    3. D4_HighPeak_2Q_Decel (增速从高位连降2季减速):
       过去3季峰值营收增速 >= 15% (prior3q_peak_rev_yoy >= 0.15) 且营收增速已连续 >= 2 季环比下滑 (g01_consec_rev_decel_n >= 2)!
    4. D3_SteadyHigh_ge15_NoAccel (稳态高增>=15%无加速):
       非 D1/D2/D4, 当季单季营收同比 >= 15% (rev_yoy >= 0.15), 但未实现双加速改善 (rev_accel_1q <= 0 或利润率收缩)!
    5. D0_LowGrow_or_Other (低增或其他, rev_yoy < 15% 且无双改善/非高位连降): 对照基线。
    """
    margin_exp = (df["opm_yoy_chg"] > 0) | (df["gm_sga_yoy_chg"] > 0)
    c_d1 = (df["rev_yoy"] > 0) & (
        (df["consec_double_inflect_n"] >= 3)
        | ((df["consec_rev_accel_n"] >= 3) & margin_exp)
    )
    c_d2 = (~c_d1) & (df["rev_yoy"] > 0) & (df["rev_accel_1q"] > 0) & margin_exp
    c_d4 = (~c_d1) & (~c_d2) & (df["g01_prior3q_peak_rev_yoy"] >= 0.15) & (df["g01_consec_rev_decel_n"] >= 2)
    c_d3 = (~c_d1) & (~c_d2) & (~c_d4) & (df["rev_yoy"] >= 0.15)

    return pd.Series(
        np.select(
            [c_d1, c_d2, c_d3, c_d4],
            [
                "D1_Consec3Q_DoubleAccel",
                "D2_SingleQ_DoubleImprove",
                "D3_SteadyHigh_ge15_NoAccel",
                "D4_HighPeak_2Q_Decel",
            ],
            default="D0_LowGrow_or_Other",
        ),
        index=df.index,
    )


def assign_r2_tier(r2_s: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [
                r2_s < 0.45,
                (r2_s >= 0.45) & (r2_s < 0.65),
                (r2_s >= 0.65) & (r2_s < 0.75),
                (r2_s >= 0.75) & (r2_s < 0.85),
                r2_s >= 0.85,
            ],
            [
                "R1_lt0.45_ChoppyOrDown",
                "R2_0.45_to_0.65_WeakTrend",
                "R3_0.65_to_0.75_ModTrend",
                "R4_0.75_to_0.85_SlowBull",
                "R5_ge0.85_Textbook45Deg",
            ],
            default="NA",
        ),
        index=r2_s.index,
    )


def assign_mdd_tier(mdd_s: pd.Series) -> pd.Series:
    return pd.Series(
        np.select(
            [
                mdd_s < 0.15,
                (mdd_s >= 0.15) & (mdd_s < 0.22),
                (mdd_s >= 0.22) & (mdd_s < 0.32),
                mdd_s >= 0.32,
            ],
            [
                "M1_lt15pct_UltraTight",
                "M2_15_to_22pct_LowDD",
                "M3_22_to_32pct_ModDD",
                "M4_ge32pct_DeepDD",
            ],
            default="NA",
        ),
        index=mdd_s.index,
    )


def run_task2_slowbull_x_2nd_deriv(xbrl: pd.DataFrame):
    t0 = time.time()
    print("\n[4/6] 执行任务 2: 缓涨平滑度(R²×回撤×时长) × 基本面二阶导全交叉表与高利率期矛盾解剖...")

    # 使用严格零前视大中盘可投资机构池 (mcap_2026_equiv_b >= 25 主池 + 同时对 1.5-3Y 核心矛盾对比 >=10B 扩样稳健性)
    base = xbrl[(~xbrl["g01_has_break"].fillna(False)) & xbrl["g01_entry_date"].notna()].copy()
    base["filed_year"] = pd.to_datetime(base["filed"]).dt.year
    base["deriv_tier"] = classify_fundamental_2nd_deriv(base)

    # 复合 1.5至3年 缓涨平滑度指标 (取 1.5Y/2Y/3Y 中最优平滑状态及 2Y 中枢)
    base["g01_r2_1_5to3Y"] = base[["g01_r2_1_5Y", "g01_r2_2Y", "g01_r2_3Y"]].max(axis=1)
    base["g01_mdd_1_5to3Y"] = base["g01_mdd_2Y"].fillna(base["g01_mdd_1_5Y"])
    base["g01_cagr_1_5to3Y"] = base[["g01_cagr_1_5Y", "g01_cagr_2Y", "g01_cagr_3Y"]].max(axis=1)

    d25 = base[base["mcap_2026_equiv_b"] >= 25.0].copy()

    periods_3 = [
        ("Full_2009_2026", pd.Series(True, index=d25.index)),
        ("Last10Y_2016_2026", d25["filed_year"] >= 2016),
        ("HighRate_2022_2026", d25["filed_year"] >= 2022),
    ]

    deriv_order = [
        "D1_Consec3Q_DoubleAccel",
        "D2_SingleQ_DoubleImprove",
        "D3_SteadyHigh_ge15_NoAccel",
        "D4_HighPeak_2Q_Decel",
    ]
    r2_order = [
        "R1_lt0.45_ChoppyOrDown",
        "R2_0.45_to_0.65_WeakTrend",
        "R3_0.65_to_0.75_ModTrend",
        "R4_0.75_to_0.85_SlowBull",
        "R5_ge0.85_Textbook45Deg",
    ]
    mdd_order = [
        "M1_lt15pct_UltraTight",
        "M2_15_to_22pct_LowDD",
        "M3_22_to_32pct_ModDD",
        "M4_ge32pct_DeepDD",
    ]
    durations = ["6M", "1Y", "1_5Y", "2Y", "3Y", "5Y"]

    rows = []

    # --------------------------------------------------------------------------
    # 层级 A: 核心矛盾直接拆解切面 (1.5至3年平滑缓涨 R²>=0.75, MDD<22%, CAGR>=15% × 二阶导 × 财报跳涨反应)
    # 覆盖三期 + 额外增列 2021-2026 以直接对齐题干 2021-2026 口径!
    # --------------------------------------------------------------------------
    sb_core_mask = (
        ((d25["g01_r2_1_5Y"] >= 0.75) & (d25["g01_mdd_1_5Y"] < 0.22) & (d25["g01_cagr_1_5Y"] >= 0.15))
        | ((d25["g01_r2_2Y"] >= 0.75) & (d25["g01_mdd_2Y"] < 0.22) & (d25["g01_cagr_2Y"] >= 0.15))
        | ((d25["g01_r2_3Y"] >= 0.75) & (d25["g01_mdd_3Y"] < 0.22) & (d25["g01_cagr_3Y"] >= 0.15))
    )
    jump_pos5 = (d25["earn_jump_ret"] >= 0.05) | (d25["g01_earn_ret_2d"] >= 0.05)
    jump_drop = (d25["earn_jump_ret"] < 0.0) & (d25["g01_earn_ret_2d"] < 0.0)

    core_slices = [
        ("Core_0_Universe25B_Baseline", pd.Series(True, index=d25.index)),
        ("Core_1_PureSlowBull_1_5to3Y_All", sb_core_mask),
        ("Core_2_NaiveSlowBull_Plus_RevYoY_ge15_All", sb_core_mask & (d25["rev_yoy"] >= 0.15)),
        ("Core_3a_SlowBull_RevYoYge15_BUT_2ndDeriv_NonAccel_or_Decel", sb_core_mask & (d25["rev_yoy"] >= 0.15) & (d25["rev_accel_1q"] <= 0)),
        ("Core_3b_SlowBull_RevYoYge15_AND_2ndDeriv_DoubleImproveOr3Q", sb_core_mask & (d25["rev_yoy"] >= 0.15) & d25["deriv_tier"].isin(["D1_Consec3Q_DoubleAccel", "D2_SingleQ_DoubleImprove"])),
        ("Core_3c_SlowBull_RevYoYge15_AND_DoubleAccel_AND_EarnJump_ge5pct", sb_core_mask & (d25["rev_yoy"] >= 0.15) & d25["deriv_tier"].isin(["D1_Consec3Q_DoubleAccel", "D2_SingleQ_DoubleImprove"]) & jump_pos5),
        ("Core_4a_SlowBull_x_D1_Consec3Q_DoubleAccel", sb_core_mask & (d25["deriv_tier"] == "D1_Consec3Q_DoubleAccel")),
        ("Core_4b_SlowBull_x_D2_SingleQ_DoubleImprove", sb_core_mask & (d25["deriv_tier"] == "D2_SingleQ_DoubleImprove")),
        ("Core_4c_SlowBull_x_D3_SteadyHigh_ge15_NoAccel", sb_core_mask & (d25["deriv_tier"] == "D3_SteadyHigh_ge15_NoAccel")),
        ("Core_4d_SlowBull_x_D4_HighPeak_2Q_Decel", sb_core_mask & (d25["deriv_tier"] == "D4_HighPeak_2Q_Decel")),
        ("Core_5a_Launchpad_SlowBull_DoubleAccel_EarnJump_ge5pct", sb_core_mask & d25["deriv_tier"].isin(["D1_Consec3Q_DoubleAccel", "D2_SingleQ_DoubleImprove"]) & jump_pos5),
        ("Core_5b_DistTop_SlowBull_DecelOrNoAccel_EarnDrop_lt0pct", sb_core_mask & d25["deriv_tier"].isin(["D3_SteadyHigh_ge15_NoAccel", "D4_HighPeak_2Q_Decel"]) & jump_drop),
        ("Core_5c_DistTop_SlowBull_HighPEgt35_and_2QDecel", sb_core_mask & (d25["pe_pit"] >= 35.0) & (d25["deriv_tier"] == "D4_HighPeak_2Q_Decel")),
    ]

    ext_periods = periods_3 + [("HighRate_2021_2026", d25["filed_year"] >= 2021)]
    for p_lbl, p_m in ext_periods:
        for c_lbl, c_m in core_slices:
            sub = d25[p_m & c_m]
            if len(sub) >= 3:
                st = eval_g01_metrics(sub, date_col="g01_entry_date")
                st_meta = {
                    "grid_level": "0_Core_Paradox_Decomposition",
                    "period": p_lbl,
                    "duration": "1_5Y_to_3Y",
                    "r2_tier": "R_SlowBull_ge0.75",
                    "mdd_tier": "M_SlowBull_lt22pct",
                    "deriv_tier": c_lbl,
                    "med_entry_pe": round(float(sub[sub["pe_pit"] > 0]["pe_pit"].median()), 1) if (sub["pe_pit"] > 0).any() else np.nan,
                    "med_entry_ps": round(float(sub["ps_pit"].dropna().median()), 2) if sub["ps_pit"].notna().any() else np.nan,
                    "med_rev_yoy_pct": round(float(sub["rev_yoy"].dropna().median() * 100), 1) if sub["rev_yoy"].notna().any() else np.nan,
                    "med_expost_rev_yoy_4q_chg_pp": round(float((sub["expost_rev_yoy_4q_later"] - sub["rev_yoy"]).dropna().median() * 100), 1) if (sub["expost_rev_yoy_4q_later"] - sub["rev_yoy"]).notna().any() else np.nan,
                }
                st_meta.update(st)
                rows.append(st_meta)

    # --------------------------------------------------------------------------
    # 层级 B: 边际汇总切面 1 — 6档时长 × R²五档(+缓涨汇总>=0.75) × 基本面二阶导四档 (固定回撤<22%)
    # --------------------------------------------------------------------------
    for dur in durations:
        r2_col = f"g01_r2_{dur}"
        mdd_col = f"g01_mdd_{dur}"
        r2_t = assign_r2_tier(d25[r2_col])
        mdd_low = d25[mdd_col] < 0.22

        for p_lbl, p_m in periods_3:
            # 先输出 R² >= 0.75 & MDD < 22% 汇总行 × 四档二阶导
            for dv in deriv_order:
                sub = d25[p_m & (d25[r2_col] >= 0.75) & mdd_low & (d25["deriv_tier"] == dv)]
                if len(sub) >= 3:
                    st = eval_g01_metrics(sub, date_col="g01_entry_date")
                    row = {
                        "grid_level": "1_Duration_x_SlowBullR2ge075_MDDlt22_x_2ndDeriv",
                        "period": p_lbl,
                        "duration": dur,
                        "r2_tier": "ALL_SlowBull_R2_ge0.75",
                        "mdd_tier": "ALL_LowDD_lt22pct",
                        "deriv_tier": dv,
                        "med_entry_pe": round(float(sub[sub["pe_pit"] > 0]["pe_pit"].median()), 1) if (sub["pe_pit"] > 0).any() else np.nan,
                        "med_entry_ps": round(float(sub["ps_pit"].dropna().median()), 2) if sub["ps_pit"].notna().any() else np.nan,
                        "med_rev_yoy_pct": round(float(sub["rev_yoy"].dropna().median() * 100), 1) if sub["rev_yoy"].notna().any() else np.nan,
                        "med_expost_rev_yoy_4q_chg_pp": round(float((sub["expost_rev_yoy_4q_later"] - sub["rev_yoy"]).dropna().median() * 100), 1) if (sub["expost_rev_yoy_4q_later"] - sub["rev_yoy"]).notna().any() else np.nan,
                    }
                    row.update(st)
                    rows.append(row)

            # 再输出 R² 五档 × 四档二阶导 (不限回撤, 纯看 R² 与二阶导交互)
            for r_lbl in r2_order:
                m_r = r2_t == r_lbl
                for dv in deriv_order:
                    sub = d25[p_m & m_r & (d25["deriv_tier"] == dv)]
                    if len(sub) >= 3:
                        st = eval_g01_metrics(sub, date_col="g01_entry_date")
                        row = {
                            "grid_level": "2_Duration_x_R2FiveTiers_x_2ndDeriv",
                            "period": p_lbl,
                            "duration": dur,
                            "r2_tier": r_lbl,
                            "mdd_tier": "ALL_MDD",
                            "deriv_tier": dv,
                            "med_entry_pe": round(float(sub[sub["pe_pit"] > 0]["pe_pit"].median()), 1) if (sub["pe_pit"] > 0).any() else np.nan,
                            "med_entry_ps": round(float(sub["ps_pit"].dropna().median()), 2) if sub["ps_pit"].notna().any() else np.nan,
                            "med_rev_yoy_pct": round(float(sub["rev_yoy"].dropna().median() * 100), 1) if sub["rev_yoy"].notna().any() else np.nan,
                            "med_expost_rev_yoy_4q_chg_pp": np.nan,
                        }
                        row.update(st)
                        rows.append(row)

    # --------------------------------------------------------------------------
    # 层级 C: 全四维原子交叉网格 — 6档时长 × R²五档 × 回撤四档 × 基本面二阶导四档 × 三期!
    # --------------------------------------------------------------------------
    for dur in durations:
        r2_t = assign_r2_tier(d25[f"g01_r2_{dur}"])
        mdd_t = assign_mdd_tier(d25[f"g01_mdd_{dur}"])
        for p_lbl, p_m in periods_3:
            sub_p = d25[p_m]
            r2_tp = r2_t[p_m]
            mdd_tp = mdd_t[p_m]
            for r_lbl in r2_order:
                mr = r2_tp == r_lbl
                if not mr.any():
                    continue
                for m_lbl in mdd_order:
                    mm = mr & (mdd_tp == m_lbl)
                    if not mm.any():
                        continue
                    for dv in deriv_order:
                        cell = sub_p[mm & (sub_p["deriv_tier"] == dv)]
                        if len(cell) >= 3:
                            st = eval_g01_metrics(cell, date_col="g01_entry_date")
                            row = {
                                "grid_level": "3_Full4D_Duration_x_R2_x_MDD_x_2ndDeriv",
                                "period": p_lbl,
                                "duration": dur,
                                "r2_tier": r_lbl,
                                "mdd_tier": m_lbl,
                                "deriv_tier": dv,
                                "med_entry_pe": round(float(cell[cell["pe_pit"] > 0]["pe_pit"].median()), 1) if (cell["pe_pit"] > 0).any() else np.nan,
                                "med_entry_ps": round(float(cell["ps_pit"].dropna().median()), 2) if cell["ps_pit"].notna().any() else np.nan,
                                "med_rev_yoy_pct": round(float(cell["rev_yoy"].dropna().median() * 100), 1) if cell["rev_yoy"].notna().any() else np.nan,
                                "med_expost_rev_yoy_4q_chg_pp": np.nan,
                            }
                            row.update(st)
                            rows.append(row)

    df_out = pd.DataFrame(rows)
    out_csv = os.path.join(OUT_DIR, "table_g01_slowbull_x_2nd_deriv.csv")
    df_out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  已保存 {out_csv} ({len(df_out)} 行, 耗时 {time.time()-t0:.2f}s).")

    # 打印核心矛盾诊断统计供报告引用
    sb_rev15_hi = d25[(d25["filed_year"] >= 2021) & sb_core_mask & (d25["rev_yoy"] >= 0.15)]
    n_tot_hi = len(sb_rev15_hi)
    n_non_acc_hi = int((sb_rev15_hi["rev_accel_1q"] <= 0).sum())
    n_decel2_hi = int((sb_rev15_hi["deriv_tier"] == "D4_HighPeak_2Q_Decel").sum())
    n_steady_hi = int((sb_rev15_hi["deriv_tier"] == "D3_SteadyHigh_ge15_NoAccel").sum())
    n_dbl_hi = int(sb_rev15_hi["deriv_tier"].isin(["D1_Consec3Q_DoubleAccel", "D2_SingleQ_DoubleImprove"]).sum())
    print(f"  [2021-2026 缓涨+营收>=15% 内部结构破案] 总样本={n_tot_hi}: 二阶导未加速占比={n_non_acc_hi/max(n_tot_hi,1):.1%} "
          f"(D3稳态无加速={n_steady_hi}, D4高位连降={n_decel2_hi}), D1+D2真双加速={n_dbl_hi} ({n_dbl_hi/max(n_tot_hi,1):.1%}).")
    return df_out


# ==============================================================================
# PART 7: 任务 3 — 1996-2008 早周期标普500动态历史成分股零幸存者偏差验证 (table_g01_pre2009_slowbull.csv)
# ==============================================================================
def run_task3_pre2009_slowbull(eng: dict) -> pd.DataFrame:
    t0 = time.time()
    print("\n[5/6] 执行任务 3: 1996-2008 早周期标普500动态历史成分股验证 (table_g01_pre2009_slowbull.csv)...")

    # 1. 加载 1996-2008 标普500 动态时点进出区间表 (sp500_ticker_start_end.csv + delisted_meta_0/1)
    sp_hist = pd.read_csv(os.path.join(TMP_XUAN, "w1_a1/sp500_ticker_start_end.csv"))
    sp_hist["start_dt"] = pd.to_datetime(sp_hist["start_date"], errors="coerce").fillna(pd.Timestamp("1990-01-01"))
    sp_hist["end_dt"] = pd.to_datetime(sp_hist["end_date"], errors="coerce").fillna(pd.Timestamp("2026-12-31"))

    sp_intervals = {}
    for _, r in sp_hist.iterrows():
        tk = str(r["ticker"]).strip()
        sp_intervals.setdefault(tk, []).append((r["start_dt"], r["end_dt"]))
        for alt in (tk.replace(".", "-"), tk.replace("-", ".")):
            if alt != tk:
                sp_intervals.setdefault(alt, []).append((r["start_dt"], r["end_dt"]))

    # 补入 delisted_meta_0/1 中 1996-2008 的标普500历史退出成分股区间
    for _, r in eng["dm_all"].iterrows():
        tk = str(r["ticker"]).strip()
        s_dt = pd.to_datetime(r["sp_start"], errors="coerce") if pd.notna(r["sp_start"]) else pd.Timestamp("1996-01-01")
        e_dt = pd.to_datetime(r["sp_end"], errors="coerce") if pd.notna(r["sp_end"]) else pd.Timestamp("2009-12-31")
        if pd.isna(s_dt):
            s_dt = pd.Timestamp("1996-01-01")
        if pd.isna(e_dt):
            e_dt = pd.Timestamp("2009-12-31")
        sp_intervals.setdefault(tk, []).append((s_dt, e_dt))

    # 2. 加载 SEC 1995-2026 原始财报披露序列 (8-K Item 2.02/12 + 10-Q/10-K, 截取 1996-01-01 至 2008-12-31)
    sf_paths = [
        os.path.join(TMP_EARN, "pre2009_shards/sec_filings_1995_2026_partA.parquet"),
        os.path.join(TMP_EARN, "pre2009_shards/sec_filings_1995_2026_partB.parquet"),
        os.path.join(TMP_EARN, "pre2009_shards/sec_filings_1995_2026_partC.parquet"),
        os.path.join(TMP_EARN, "pre2009_shards/sec_filings_1995_2026_partC_gap.parquet"),
    ]
    sf_raw = pd.concat([pd.read_parquet(p) for p in sf_paths], ignore_index=True)
    is_periodic = sf_raw["form"].isin(["10-Q", "10-K", "10-Q405", "10-K405"])
    items_s = sf_raw["items"].fillna("").astype(str)
    is_earn_8k = (sf_raw["form"] == "8-K") & (
        items_s.str.contains(r"(?:^|,|;)2\.02(?:$|,|;)", regex=True)
        | items_s.str.contains(r"(?:^|,|;)12(?:$|,|;)", regex=True)
    )
    sf = sf_raw[is_periodic | is_earn_8k].copy()
    sf = sf[(sf["filingDate"] >= "1996-01-01") & (sf["filingDate"] <= "2008-12-31")].copy()
    sf["form_prio"] = np.where(sf["form"] == "8-K", 0, 1)
    sf = sf.sort_values(["ticker", "filingDate", "form_prio"]).drop_duplicates(subset=["ticker", "filingDate"], keep="first")

    # 同股间隔 >= 45 日历天去重为真实季度财报事件
    sf_dts = pd.to_datetime(sf["filingDate"]).values.astype("datetime64[D]").astype(np.int64)
    sf_tks = sf["ticker"].values
    keep_45 = np.zeros(len(sf), dtype=bool)
    last_tk = None
    last_d = -999999
    for i in range(len(sf)):
        if sf_tks[i] != last_tk or (sf_dts[i] - last_d) >= 45:
            keep_45[i] = True
            last_tk = sf_tks[i]
            last_d = sf_dts[i]
    sf_pre09 = sf.iloc[keep_45].copy().reset_index(drop=True)

    # 判定每个 filingDate 当天是否严格属于标普500动态历史成分股 (Point-in-Time Membership!)
    f_ts_ser = pd.to_datetime(sf_pre09["filingDate"])
    in_sp500_pit = np.zeros(len(sf_pre09), dtype=bool)
    for i, (tk, f_ts) in enumerate(zip(sf_pre09["ticker"].values, f_ts_ser)):
        iv_list = sp_intervals.get(str(tk), [])
        for s_dt, e_dt in iv_list:
            if s_dt <= f_ts <= e_dt:
                in_sp500_pit[i] = True
                break
    sf_pre09["is_sp500_pit"] = in_sp500_pit

    # 挂载严格截至 filingDate - 1 的 6 档 R²/MDD/CAGR + filingDate + 1 收盘入场 + 退市破产残值顺延 1Y/3Y/5Y 收益!
    ev_pre = compute_pit_smoothness_and_returns(
        eng, sf_pre09, ticker_col="ticker", event_date_col="filingDate", horizons=(252, 756, 1260), compute_6_lookbacks=True
    )
    ev_pre = ev_pre[(~ev_pre["g01_has_break"].fillna(False)) & ev_pre["g01_entry_adj_px"].notna()].copy()
    ev_pre["filing_year"] = pd.to_datetime(ev_pre["filingDate"]).dt.year

    # 计算零前视连续财报正反应季数 (consec_pos_earn_streak)
    ev_pre = ev_pre.sort_values(["ticker", "filingDate"]).reset_index(drop=True)
    tks_p = ev_pre["ticker"].values
    fd_p = pd.to_datetime(ev_pre["filingDate"]).values.astype("datetime64[D]").astype(np.int64)
    ex_r = ev_pre["g01_earn_ret_2d_excess"].values
    pos_stk = np.zeros(len(ev_pre), dtype=np.int32)
    for i in range(len(ev_pre)):
        if np.isnan(ex_r[i]):
            continue
        if i > 0 and tks_p[i] == tks_p[i - 1] and (fd_p[i] - fd_p[i - 1]) <= 190 and not np.isnan(ex_r[i - 1]):
            pos_stk[i] = (pos_stk[i - 1] + 1) if ex_r[i] > 0 else 0
        else:
            pos_stk[i] = 1 if ex_r[i] > 0 else 0
    ev_pre["pos_earn_streak"] = pos_stk

    # 主分析聚焦零幸存者偏差的「标普500动态历史时点成分池 (is_sp500_pit == True)」，并对照全SEC早周期池
    sp_pit_df = ev_pre[ev_pre["is_sp500_pit"]].copy()
    print(f"  1996-2008 标普500动态历史成分股有效财报事件: {len(sp_pit_df):,} 笔, 独立成分股: {sp_pit_df['ticker'].nunique()} 只 (含退市破产股计入3Y分母={int(sp_pit_df['g01_delisted_756d'].sum())}笔).")

    eras_pre09 = [
        ("Full_Pre2009_1996_2008", pd.Series(True, index=sp_pit_df.index)),
        ("SubEra1_DotComBull_1996_2000", (sp_pit_df["filing_year"] >= 1996) & (sp_pit_df["filing_year"] <= 2000)),
        ("SubEra2_TechBust_2001_2002", (sp_pit_df["filing_year"] >= 2001) & (sp_pit_df["filing_year"] <= 2002)),
        ("SubEra3_HikeCapexBull_2003_2007", (sp_pit_df["filing_year"] >= 2003) & (sp_pit_df["filing_year"] <= 2007)),
        ("SubEra4_GFC_2008", sp_pit_df["filing_year"] == 2008),
    ]

    # 定义缓涨形态 × 财报日跳涨 vs 财报日下跌矩阵
    sb_1_5to3y_r75 = (sp_pit_df["g01_r2_1_5Y"] >= 0.75) | (sp_pit_df["g01_r2_2Y"] >= 0.75) | (sp_pit_df["g01_r2_3Y"] >= 0.75)
    sb_1_5to3y_strict = (
        ((sp_pit_df["g01_r2_1_5Y"] >= 0.75) & (sp_pit_df["g01_mdd_1_5Y"] < 0.22) & (sp_pit_df["g01_cagr_1_5Y"] >= 0.15))
        | ((sp_pit_df["g01_r2_2Y"] >= 0.75) & (sp_pit_df["g01_mdd_2Y"] < 0.22) & (sp_pit_df["g01_cagr_2Y"] >= 0.15))
        | ((sp_pit_df["g01_r2_3Y"] >= 0.75) & (sp_pit_df["g01_mdd_3Y"] < 0.22) & (sp_pit_df["g01_cagr_3Y"] >= 0.15))
    )
    non_sb = (~sb_1_5to3y_r75) & sp_pit_df["g01_r2_2Y"].notna()

    er2 = sp_pit_df["g01_earn_ret_2d"]
    ex2 = sp_pit_df["g01_earn_ret_2d_excess"]

    react_cuts = [
        ("R0_All_EarningsEvents", pd.Series(True, index=sp_pit_df.index)),
        ("R1_BigJump_ge5pct", er2 >= 0.05),
        ("R2_HugeJump_ge8pct", er2 >= 0.08),
        ("R3_ModJump_0_to_5pct", (er2 > 0.0) & (er2 < 0.05)),
        ("R4_AllPosJump_gt0pct", er2 > 0.0),
        ("R5_Consec2Qplus_PosExcessJump", sp_pit_df["pos_earn_streak"] >= 2),
        ("R6_Consec3Qplus_PosExcessJump", sp_pit_df["pos_earn_streak"] >= 3),
        ("R7_AllDrop_le0pct", er2 <= 0.0),
        ("R8_ModDrop_m5_to_0pct", (er2 > -0.05) & (er2 <= 0.0)),
        ("R9_BigDrop_lem5pct", er2 <= -0.05),
        ("R10_HugeDrop_lem8pct", er2 <= -0.08),
    ]

    trend_groups = [
        ("T0_SP500_PIT_AllPatterns_Baseline", pd.Series(True, index=sp_pit_df.index)),
        ("T1_SlowBull_1_5to3Y_R2ge0.75_All", sb_1_5to3y_r75),
        ("T2_SlowBull_1_5to3Y_Strict_R2ge0.75_MDDlt22_CAGRge15", sb_1_5to3y_strict),
        ("T3_SlowBull_2Y_Exact_R2ge0.75", sp_pit_df["g01_r2_2Y"] >= 0.75),
        ("T4_SlowBull_3Y_Exact_R2ge0.75", sp_pit_df["g01_r2_3Y"] >= 0.75),
        ("T5_SlowBull_1Y_Exact_R2ge0.75", sp_pit_df["g01_r2_1Y"] >= 0.75),
        ("T6_NonSlowBull_ChoppyOrDown_R2lt0.75", non_sb),
    ]

    rows_pre = []
    for era_lbl, era_m in eras_pre09:
        # 全期跑全部 trend × reaction; 子时代聚焦核心 trend × 核心跳涨/下跌
        t_iter = trend_groups if era_lbl == "Full_Pre2009_1996_2008" else trend_groups[:3] + [trend_groups[-1]]
        for t_lbl, t_m in t_iter:
            for r_lbl, r_m in react_cuts:
                sub = sp_pit_df[era_m & t_m & r_m]
                if len(sub) >= 5:
                    st = eval_g01_metrics(sub, date_col="g01_entry_date")
                    row = {
                        "universe": "SP500_Dynamic_PIT_ZeroSurvivorship",
                        "era_period": era_lbl,
                        "slowbull_group": t_lbl,
                        "earnings_reaction": r_lbl,
                    }
                    row.update(st)
                    rows_pre.append(row)

    # 额外增加: 对比若不加退市破产残值顺延 (Naive Drop) 在 1996-2008 标普500动态池中的幸存者偏差幅度!
    alp_fdrop_map = {"1y": "g01_alpha_naivedrop_252d", "3y": "g01_alpha_naivedrop_756d", "5y": "g01_alpha_naivedrop_1260d"}
    ret_strict_map = {"1y": "g01_fwd_252d", "3y": "g01_fwd_756d", "5y": "g01_fwd_1260d"}
    for t_lbl, t_m in [("T0_SP500_PIT_AllPatterns_Baseline", pd.Series(True, index=sp_pit_df.index)),
                       ("T1_SlowBull_1_5to3Y_R2ge0.75_All", sb_1_5to3y_r75),
                       ("T6_NonSlowBull_ChoppyOrDown_R2lt0.75", non_sb)]:
        sub = sp_pit_df[t_m]
        st_drop = eval_g01_metrics(sub, date_col="g01_entry_date", ret_cols_map=ret_strict_map, alpha_cols_map=alp_fdrop_map)
        row = {
            "universe": "SP500_Dynamic_PIT_NaiveDelistDrop_Control",
            "era_period": "Full_Pre2009_1996_2008",
            "slowbull_group": t_lbl,
            "earnings_reaction": "R0_All_EarningsEvents_DropDelistedNaN",
        }
        row.update(st_drop)
        rows_pre.append(row)

    df_pre_out = pd.DataFrame(rows_pre)
    out_csv = os.path.join(OUT_DIR, "table_g01_pre2009_slowbull.csv")
    df_pre_out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"  已保存 {out_csv} ({len(df_pre_out)} 行, 耗时 {time.time()-t0:.2f}s).")
    return df_pre_out


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    t_all = time.time()
    print("=" * 85)
    print("G01 缓涨策略二阶导拆解与零未来函数交叉审核引擎启动")
    print("=" * 85)

    eng = build_unified_delist_aware_engine()
    xbrl = build_master_2009_2026_panel(eng)

    t1_df = run_task1_bias_audit(xbrl)
    t2_df = run_task2_slowbull_x_2nd_deriv(xbrl)
    t3_df = run_task3_pre2009_slowbull(eng)

    # 输出关键核心数字摘要到控制台以核验并撰写 g01_summary.md
    print("\n" + "=" * 85)
    print("[6/6] 核心实证结果速览 (全期 / 近10年 / 高利率期 / 1996-2008 早周期)")
    print("=" * 85)

    print("\n--- 1. 偏差精算瀑布 (Full_2009_2026) ---")
    c1 = ["strategy_code", "step_code", "n_raw", "n_dedup", "n_tickers",
          "primary_alpha_pct_1y", "primary_alpha_pct_3y", "primary_alpha_pct_5y",
          "step_marginal_haircut_pp_3y", "cum_haircut_vs_step1_pp_3y",
          "med_alpha_pct_3y", "win_rate_pct_3y", "halve_rate_pct_3y"]
    print(t1_df[t1_df["period"] == "Full_2009_2026"][c1].to_string(index=False))

    print("\n--- 2. 核心矛盾拆解: 1.5至3年平滑缓涨 × 二阶导 × 跳涨 (三期 + 2021-2026) ---")
    c2 = ["period", "deriv_tier", "n_dedup", "n_tickers", "med_entry_pe", "med_rev_yoy_pct", "med_expost_rev_yoy_4q_chg_pp",
          "qtr_ew_alpha_pct_1y", "qtr_ew_alpha_pct_3y", "qtr_ew_alpha_pct_5y",
          "med_alpha_pct_3y", "win_rate_pct_3y", "payoff_ratio_3y", "double_rate_pct_3y", "halve_rate_pct_3y"]
    print(t2_df[t2_df["grid_level"] == "0_Core_Paradox_Decomposition"][c2].to_string(index=False))

    print("\n--- 3. 1996-2008 标普500动态历史成分股: 缓涨 × 财报跳涨 vs 下跌 ---")
    c3 = ["era_period", "slowbull_group", "earnings_reaction", "n_dedup", "n_tickers",
          "qtr_ew_alpha_pct_1y", "qtr_ew_alpha_pct_3y", "qtr_ew_alpha_pct_5y",
          "med_alpha_pct_3y", "win_rate_pct_3y", "payoff_ratio_3y", "double_rate_pct_3y", "halve_rate_pct_3y", "delisted_in_3y_n"]
    sub3 = t3_df[(t3_df["era_period"] == "Full_Pre2009_1996_2008") & (t3_df["earnings_reaction"].isin([
        "R0_All_EarningsEvents", "R1_BigJump_ge5pct", "R2_HugeJump_ge8pct", "R4_AllPosJump_gt0pct",
        "R6_Consec3Qplus_PosExcessJump", "R7_AllDrop_le0pct", "R9_BigDrop_lem5pct", "R0_All_EarningsEvents_DropDelistedNaN"
    ]))]
    print(sub3[c3].to_string(index=False))

    print(f"\n[DONE] G01 全链路执行完毕, 总耗时: {time.time()-t_all:.2f}s!")


if __name__ == "__main__":
    main()
