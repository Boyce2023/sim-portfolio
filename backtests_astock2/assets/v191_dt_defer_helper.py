# -*- coding: utf-8 -*-
"""
v191_dt_defer_helper.py: V19.1 红队物理真账共享校准工具（零 yfinance）
统一实现：
1. 15:00 精确封死跌停（is_dt_exact）顺延至次一非全天一字跌停交易日 09:25 开盘价卖出；
2. 含除权除息复权因子（adjf = adj_close / close）净收益计算。
"""
import os
import numpy as np
import pandas as pd

SIM_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
A_DAILY_PATH = os.path.join(SIM_DIR, "data", "cn_hk_price_db", "a_daily.parquet")
A_DELISTED_PATH = os.path.join(SIM_DIR, "data", "cn_hk_price_db", "a_delisted_daily.parquet")
PARTC_DIR = os.path.join(SIM_DIR, "backtests_astock", "redteam_full_audit_20261123", "partC_clean_ledgers_v191")

_DT_CACHE = None


def load_dt_defer_tables(start_date: str = "2021-09-01") -> dict:
    """加载 A 股真实日线复权因子、跌停价与精确封死跌停标记（单例缓存，严格零 yfinance）。"""
    global _DT_CACHE
    if _DT_CACHE is not None:
        return _DT_CACHE

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    da = pd.read_parquet(A_DAILY_PATH, columns=cols, filters=[("date", ">=", pd.Timestamp(start_date))])
    parts = [da]
    if os.path.exists(A_DELISTED_PATH):
        dd = pd.read_parquet(A_DELISTED_PATH, columns=cols, filters=[("date", ">=", pd.Timestamp(start_date))])
        parts.append(dd)
    df_d = pd.concat(parts, ignore_index=True)
    df_d["c6"] = df_d["ticker"].astype(str).str[:6]
    df_d = df_d[df_d["c6"].str.startswith(("00", "60")) & (~df_d["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_d["dt_s"] = df_d["date"].dt.strftime("%Y-%m-%d")
    df_d.sort_values(["c6", "dt_s"], inplace=True)
    df_d.drop_duplicates(["c6", "dt_s"], keep="first", inplace=True)
    df_d["adjf"] = np.where(df_d["close"] > 0, df_d["adj_close"] / df_d["close"], 1.0)

    g = df_d.groupby("c6")
    df_d["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
    df_d["dt_px"] = np.floor(df_d["prev_c_adj"] * 0.90 * 100.0 + 0.5) / 100.0
    df_d["is_dt_exact"] = (df_d["close"] <= df_d["dt_px"] + 0.005) & (df_d["prev_c_adj"] > 0)
    df_d["is_yizi_dt"] = (
        df_d["is_dt_exact"]
        & (df_d["open"] <= df_d["dt_px"] + 0.005)
        & (df_d["high"] <= df_d["dt_px"] + 0.005)
    )

    by_c = {c6: grp.reset_index(drop=True) for c6, grp in df_d.groupby("c6")}
    dmap = {(r.c6, r.dt_s): r for r in df_d.itertuples(index=False)}
    _DT_CACHE = {"dmap": dmap, "by_c": by_c}
    return _DT_CACHE


def calc_adj_net_ret(
    c6: str,
    buy_dt: str,
    buy_px: float,
    exit_dt: str,
    exit_px: float,
    tables: dict | None = None,
    fee: float = 0.0020,
) -> float | None:
    """按交易日真实 adjf 复权因子计算扣费净收益率。"""
    tb = tables or load_dt_defer_tables()
    dmap = tb["dmap"]
    bb = dmap.get((c6, buy_dt))
    eb = dmap.get((c6, exit_dt))
    if bb is None or eb is None or buy_px <= 0:
        return None
    return float((float(exit_px) * float(eb.adjf)) / (float(buy_px) * float(bb.adjf)) * (1.0 - fee) - 1.0)


def defer_eod_limit_down(
    c6: str,
    buy_dt: str,
    buy_px: float,
    exit_dt: str,
    exit_hhmm: int,
    exit_px: float,
    net_ret: float,
    tables: dict | None = None,
    fee: float = 0.0020,
) -> tuple[str, int, float, float, bool]:
    """若 15:00 卖点处于精确封死跌停状态，顺延至次一非一字跌停交易日 09:25 开盘价卖出。"""
    if int(exit_hhmm) < 1455:
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False
    tb = tables or load_dt_defer_tables()
    dmap, by_c = tb["dmap"], tb["by_c"]
    eb = dmap.get((c6, exit_dt))
    bb = dmap.get((c6, buy_dt))
    gc = by_c.get(c6)
    if eb is None or bb is None or gc is None or (not bool(eb.is_dt_exact)):
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False

    matches = gc.index[gc["dt_s"] == exit_dt]
    if len(matches) == 0:
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False
    pe = int(matches[0])
    if pe + 1 >= len(gc):
        return exit_dt, int(exit_hhmm), float(exit_px), float(net_ret), False

    k = pe + 1
    while k < len(gc) - 1 and bool(gc.loc[k, "is_yizi_dt"]):
        k += 1
    nb = gc.loc[k]
    nep = round(float(nb.open), 2)
    nret = float((float(nb.open) * float(nb.adjf)) / (float(buy_px) * float(bb.adjf)) * (1.0 - fee) - 1.0)
    return str(nb.dt_s), 925, nep, nret, True
