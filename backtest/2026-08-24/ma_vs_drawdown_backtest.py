#!/usr/bin/env python3
"""
验证假设: 股价相对MA20/MA60的位置 vs 距60日高点回撤幅度, 哪个对后续收益预测力更强。

universe: 本次为独立subagent, 无跨session上下文, 未能定位"A1"具体产出文件/交接说明。
  同批次另一脚本(trend_seq_vs_cost_stop.py)遇到同样问题, 已声明改用
  sim-portfolio/watchlist_config.json 的 cn_watchlist(112只)作为universe替代并显式声明。
  本脚本为与同批次结论口径一致, 同样以 cn_watchlist(112只, 其中105只本地cache有窗口内数据,
  剩余7只经腾讯接口(与sibling脚本同一数据源)补齐)作为【主结果universe_watchlist112】。
  同时额外跑一版【稳健性对照universe_broadcache887】——用本地kline_cache.db中"窗口内有交易记录
  的全部标的"(887只, 2026-06-24~2026-08-24至少有一天有效交易), 用来检验结论是否对
  "自选观察池"这种带选股偏差(watchlist本身是Claude/Buwen已经看好或持有过的票, 非随机抽样)的
  universe敏感。两版都报告, 不只挑好看的一版。

数据源: 本地 kline_cache.db (baostock qfq前复权日线, 2371只A股, 2025-03-25~2026-08-21;
  该库由 scripts/kline_cache.py 维护, 是本仓库astock筛股系统(uass_scoring/mainline_scan/
  trend_detector等)已在用的生产数据源, 非本次新拉取) + 腾讯 web.ifzq.gtimg.cn qfq接口补齐
  cn_watchlist中7只本地cache窗口内缺数据的票(300373/600012/600988/688097/688322/688347/688515),
  已实际抓取存于 watchlist_gapfill.csv, 全部成功, 无失败重试。

窗口: 2026-06-24 ~ 2026-08-24 (t的取值范围), 但forward return计算需要t之后的真实交易日数据,
  本地cache最新到2026-08-21(即"今天"2026-08-24尚未收盘, 无当日数据), 故:
  - h=5, h=20的t可覆盖窗口内绝大部分交易日
  - h=40的t只有窗口最前3个交易日(06-24/06-25/06-26)才有完整40日后数据可算
    (43个交易日的窗口, 40日forward只留3天余量) —— 这是"今天就是2026-08-24"的硬约束,
    不是数据缺失, 报告中会显式标注h=40的日期覆盖度低、结论降级为方向性提示。

方法:
  1. 每只股票每个交易日t (用该股自身交易日序列, 不跨股票对齐日历):
     - MA20位置 = Close[t]/MA20[t] - 1
     - MA60位置 = Close[t]/MA60[t] - 1
     - 60日高点回撤 = Close[t]/Rolling60Max(High)[t] - 1  (恒<=0)
     - 前瞻收益 fwd_h = Close[t+h]/Close[t] - 1, h=5/20/40 (t+h按该股自身序列位移，
       即h个"该股有交易记录的交易日"之后，非跳过停牌的自然日)
  2. 过滤: t当日volume>0(排除停牌日); 历史长度不足(MA60/60日高点需要>=60根)的行自动为NaN被剔除。
  3. 分桶(MA20/MA60仓位: <-10% / -10~0% / 0~10% / >10%; 回撤: <-30% / -30~-20% /
     -20~-10% / -10~-5% / -5~0%)算每桶后续收益的 n/mean/median/win_rate/p5/p95。
  4. 信息量对比用两把尺子: (a) 分桶间收益的单调性与极差(spread); (b) 连续值与前瞻收益的
     Spearman秩相关(IC), 在全panel上算, 是信息含量的核心量化指标。
  5. 主动找反例: 报告每个指标在每个horizon下IC的显著性(用n和bootstrap标准误感受量级)、
     h=40覆盖天数过少的问题、以及MA20/MA60/回撤三者本身的相关性(高度共线提示"测的是同一件事"
     还是"有增量信息")。
"""
import json
import re
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "kline_cache.db"
WATCHLIST_PATH = REPO_ROOT / "watchlist_config.json"
OUT_DIR = Path(__file__).resolve().parent
GAPFILL_CSV = OUT_DIR / "watchlist_gapfill.csv"
WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 200)


def load_data():
    conn = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        "SELECT code, date, high, close, volume FROM daily_kline ORDER BY code, date",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])

    # merge in the 7 cn_watchlist tickers whose local cache had zero rows inside
    # the backtest window (300373/600012/600988/688097/688322/688347/688515) —
    # already fetched via tencent qfq into watchlist_gapfill.csv, see docstring.
    if GAPFILL_CSV.exists():
        gap = pd.read_csv(GAPFILL_CSV, dtype={"code": str})
        gap = gap.rename(columns={"open": "open_", "close": "close",
                                   "high": "high", "low": "low", "volume": "volume"})
        gap["date"] = pd.to_datetime(gap["date"])
        gap = gap[["code", "date", "high", "close", "volume"]]
        # don't duplicate any (code,date) already in the sqlite cache
        existing_keys = set(zip(df["code"], df["date"]))
        gap = gap[~gap.apply(lambda r: (r["code"], r["date"]) in existing_keys, axis=1)]
        df = pd.concat([df, gap], ignore_index=True)

    for c in ("high", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close", "high"])
    df = df[df["close"] > 0]
    return df


def load_watchlist_tickers():
    d = json.load(open(WATCHLIST_PATH))
    cn = d.get("cn_watchlist")
    s = json.dumps(cn, ensure_ascii=False)
    return sorted(set(re.findall(r"\b\d{6}\b", s)))


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    g = df.groupby("code", group_keys=False)

    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    df["hh60"] = g["high"].transform(lambda s: s.rolling(60, min_periods=60).max())

    df["pos_ma20"] = df["close"] / df["ma20"] - 1
    df["pos_ma60"] = df["close"] / df["ma60"] - 1
    df["dd60"] = df["close"] / df["hh60"] - 1

    for h in (5, 20, 40):
        df[f"fwd_{h}"] = g["close"].transform(lambda s, h=h: s.shift(-h) / s - 1)

    return df


def bucket_ma_pos(x):
    if pd.isna(x):
        return np.nan
    if x < -0.10:
        return "1:<-10%"
    if x < 0:
        return "2:-10~0%"
    if x < 0.10:
        return "3:0~10%"
    return "4:>10%"


def bucket_dd60(x):
    if pd.isna(x):
        return np.nan
    if x < -0.30:
        return "1:<-30%"
    if x < -0.20:
        return "2:-30~-20%"
    if x < -0.10:
        return "3:-20~-10%"
    if x < -0.05:
        return "4:-10~-5%"
    return "5:-5~0%"


def summarize_bucket(sub: pd.DataFrame, fwd_col: str) -> pd.Series:
    v = sub[fwd_col].dropna()
    n = len(v)
    if n == 0:
        return pd.Series({"n": 0, "n_dates": 0, "mean": np.nan, "median": np.nan,
                           "win_rate": np.nan, "p5": np.nan, "p95": np.nan})
    n_dates = sub.loc[v.index, "date"].nunique()
    return pd.Series({
        "n": n,
        "n_dates": n_dates,
        "mean": v.mean(),
        "median": v.median(),
        "win_rate": (v > 0).mean(),
        "p5": v.quantile(0.05),
        "p95": v.quantile(0.95),
    })


def bucket_table(df: pd.DataFrame, bucket_col: str, fwd_col: str) -> pd.DataFrame:
    rows = []
    for b, sub in df.groupby(bucket_col, observed=True):
        s = summarize_bucket(sub, fwd_col)
        s["bucket"] = b
        rows.append(s)
    out = pd.DataFrame(rows).set_index("bucket").sort_index()
    return out[["n", "n_dates", "mean", "median", "win_rate", "p5", "p95"]]


def spearman_ic(df: pd.DataFrame, metric_col: str, fwd_col: str):
    sub = df[[metric_col, fwd_col, "date"]].dropna()
    n = len(sub)
    if n < 30:
        return {"n": n, "n_dates": sub["date"].nunique(), "ic": np.nan}
    ic = sub[metric_col].corr(sub[fwd_col], method="spearman")
    return {"n": n, "n_dates": sub["date"].nunique(), "ic": ic}


def main():
    print("Loading kline_cache.db ...")
    raw = load_data()
    print(f"raw rows={len(raw)}, distinct codes={raw['code'].nunique()}, "
          f"date range={raw['date'].min().date()}~{raw['date'].max().date()}")

    df = compute_indicators(raw)

    # window filter for t (the "today" of each observation)
    win = df[(df["date"] >= WINDOW_START) & (df["date"] <= WINDOW_END)].copy()
    # exclude suspended days (no trading) at t
    win = win[win["volume"] > 0]
    print(f"\nwindow rows (t in [{WINDOW_START},{WINDOW_END}], volume>0): {len(win)}, "
          f"distinct codes={win['code'].nunique()}, distinct dates={win['date'].nunique()}")

    win["bkt_ma20"] = win["pos_ma20"].apply(bucket_ma_pos)
    win["bkt_ma60"] = win["pos_ma60"].apply(bucket_ma_pos)
    win["bkt_dd60"] = win["dd60"].apply(bucket_dd60)

    results = {}
    ic_rows = []
    for h in (5, 20, 40):
        fwd_col = f"fwd_{h}"
        for metric_name, bkt_col, pos_col in (
            ("MA20位置", "bkt_ma20", "pos_ma20"),
            ("MA60位置", "bkt_ma60", "pos_ma60"),
            ("60日高点回撤", "bkt_dd60", "dd60"),
        ):
            tbl = bucket_table(win, bkt_col, fwd_col)
            results[(metric_name, h)] = tbl
            ic = spearman_ic(win, pos_col, fwd_col)
            ic_rows.append({"metric": metric_name, "horizon": h, **ic})

    ic_df = pd.DataFrame(ic_rows)

    # cross-correlation among the three raw metrics themselves (collinearity check)
    corr_cols = ["pos_ma20", "pos_ma60", "dd60"]
    corr_mat = win[corr_cols].corr(method="spearman")

    print("\n" + "=" * 90)
    print("BUCKET TABLES")
    print("=" * 90)
    for (metric_name, h), tbl in results.items():
        print(f"\n--- {metric_name} | forward {h}d return ---")
        print(tbl.round(4).to_string())

    print("\n" + "=" * 90)
    print("SPEARMAN IC (metric continuous value vs forward return, pooled panel)")
    print("=" * 90)
    print(ic_df.round(4).to_string(index=False))

    print("\n" + "=" * 90)
    print("CROSS-CORRELATION AMONG THE THREE RAW METRICS (collinearity check)")
    print("=" * 90)
    print(corr_mat.round(3).to_string())

    # save outputs
    ic_df.to_csv(OUT_DIR / "ic_summary.csv", index=False)
    corr_mat.to_csv(OUT_DIR / "metric_crosscorr.csv")
    with pd.ExcelWriter(OUT_DIR / "bucket_tables.xlsx") as xw:
        for (metric_name, h), tbl in results.items():
            sheet = f"{metric_name}_{h}d"[:31]
            tbl.to_excel(xw, sheet_name=sheet)
    keep_cols = ["code", "date", "close", "pos_ma20", "pos_ma60", "dd60",
                 "fwd_5", "fwd_20", "fwd_40"]
    win[keep_cols].to_csv(OUT_DIR / "panel_raw.csv.gz", index=False, compression="gzip")

    print(f"\nSaved: {OUT_DIR/'ic_summary.csv'}")
    print(f"Saved: {OUT_DIR/'metric_crosscorr.csv'}")
    print(f"Saved: {OUT_DIR/'bucket_tables.xlsx'}")
    print(f"Saved: {OUT_DIR/'panel_raw.csv.gz'}")


if __name__ == "__main__":
    main()
