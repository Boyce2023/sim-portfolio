#!/opt/homebrew/bin/python3.13
"""
补齐 2015 至 2026 年间 A 股已退市股票的历史日线数据。
数据输出路径: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet
列名与数据类型与 a_daily.parquet 完全对齐：
['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'amount', 'oshare', 'turn', 'qfq_factor']
"""

import os
import sys
import time
import datetime as dt
import pandas as pd
import numpy as np
import baostock as bs
import akshare as ak

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
DB_DIR = os.path.join(ROOT_DIR, "sim-portfolio/data/cn_hk_price_db")
A_DAILY_PATH = os.path.join(DB_DIR, "a_daily.parquet")
OUT_PATH = os.path.join(DB_DIR, "a_delisted_daily.parquet")


def get_current_tickers():
    print("[1/5] 读取现有在市股票代码池...", flush=True)
    df = pd.read_parquet(A_DAILY_PATH, columns=["ticker"])
    current_tickers = set(df["ticker"].unique())
    print(f"      现有在市股票总数: {len(current_tickers)} 只", flush=True)
    return current_tickers


def get_delisted_candidates(current_tickers):
    print("[2/5] 交叉检索历史全息快照与交易所退市名录...", flush=True)
    candidates = {}  # ticker: dict(name, bs_code)

    # 1. akshare 官方退市名录
    try:
        sh_delist = ak.stock_info_sh_delist()
        for _, row in sh_delist.iterrows():
            code = f"{int(row['公司代码']):06d}.SH"
            candidates[code] = {"name": str(row["公司简称"]), "bs_code": f"sh.{int(row['公司代码']):06d}"}
    except Exception as e:
        print(f"      akshare 上交所退市表拉取告警: {e}", flush=True)

    try:
        sz_delist = ak.stock_info_sz_delist()
        for _, row in sz_delist.iterrows():
            code = f"{int(row['证券代码']):06d}.SZ"
            candidates[code] = {"name": str(row["证券简称"]), "bs_code": f"sz.{int(row['证券代码']):06d}"}
    except Exception as e:
        print(f"      akshare 深交所退市表拉取告警: {e}", flush=True)

    # 2. baostock 历史全息快照求差集
    lg = bs.login()
    if lg.error_code != "0":
        print(f"      baostock 登录失败: {lg.error_msg}", flush=True)
    else:
        snapshot_dates = [
            "2015-01-05", "2016-01-05", "2017-01-05", "2018-01-05",
            "2019-01-07", "2020-01-06", "2021-01-05", "2022-01-05",
            "2023-01-05", "2024-01-05", "2025-01-06", "2026-01-05"
        ]
        for s_date in snapshot_dates:
            rs = bs.query_all_stock(day=s_date)
            while (rs.error_code == "0") and rs.next():
                row = rs.get_row_data()
                b_code = row[0]
                name = row[2]
                parts = b_code.split(".")
                if len(parts) == 2:
                    mkt, num = parts[0].upper(), parts[1]
                    if (mkt == "SH" and (num.startswith("60") or num.startswith("688"))) or \
                       (mkt == "SZ" and (num.startswith("00") or num.startswith("30"))):
                        ticker = f"{num}.{mkt}"
                        if ticker not in candidates:
                            candidates[ticker] = {"name": name, "bs_code": b_code}
        bs.logout()

    # 剔除在市股票
    missing_delisted = {t: info for t, info in candidates.items() if t not in current_tickers}
    print(f"      总计识别出不在存续库中的退市股票候选: {len(missing_delisted)} 只", flush=True)
    return missing_delisted


def fetch_delisted_daily(delisted_dict):
    print("[3/5] 开始并行/批量抓取退市股票 2015 至 2026 日线数据...", flush=True)
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")

    all_dfs = []
    success_count = 0
    empty_count = 0
    total = len(delisted_dict)

    fields = "date,code,open,high,low,close,volume,amount,turn"

    for idx, (ticker, info) in enumerate(delisted_dict.items(), 1):
        bs_code = info["bs_code"]
        name = info["name"]
        rs = bs.query_history_k_data_plus(
            bs_code,
            fields,
            start_date="2015-01-01",
            end_date="2026-11-10",
            frequency="d",
            adjustflag="3"
        )
        data = []
        while (rs.error_code == "0") and rs.next():
            data.append(rs.get_row_data())

        if data:
            df = pd.DataFrame(data, columns=rs.fields)
            # 过滤空值与非法行
            df = df[df["open"].str.strip() != ""]
            if not df.empty:
                df["ticker"] = ticker
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume", "amount"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                
                # turn baostock 为百分比，除以 100 对齐 a_daily 小数口径
                df["turn"] = pd.to_numeric(df["turn"], errors="coerce") / 100.0
                df["turn"] = df["turn"].fillna(0.0)
                
                # oshare 计算
                turn_safe = df["turn"].replace(0, np.nan)
                df["oshare"] = np.where(turn_safe.notna(), df["volume"] / turn_safe, np.nan)
                
                # 补充与 a_daily 一致的衍生列
                df["adj_close"] = df["close"]
                df["qfq_factor"] = 1.0

                df = df[[
                    "date", "ticker", "open", "high", "low", "close",
                    "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"
                ]]
                all_dfs.append(df)
                success_count += 1
            else:
                empty_count += 1
        else:
            empty_count += 1

        if idx % 50 == 0 or idx == total:
            print(f"      进度: {idx}/{total} (已获取有数据退市股: {success_count} 只, 无 2015 后交易记录: {empty_count} 只)", flush=True)

    bs.logout()

    if not all_dfs:
        print("      未拉取到任何有效日线数据！", flush=True)
        return pd.DataFrame()

    print("[4/5] 合并并排序日线数据表...", flush=True)
    full_df = pd.concat(all_dfs, ignore_index=True)
    full_df.sort_values(by=["ticker", "date"], inplace=True)
    full_df.reset_index(drop=True, inplace=True)
    return full_df


def save_and_verify(df):
    if df.empty:
        print("[5/5] 数据为空，跳过落盘。", flush=True)
        return

    print(f"[5/5] 落盘写入: {OUT_PATH} ...", flush=True)
    df.to_parquet(OUT_PATH, index=False, engine="pyarrow")
    
    file_size_mb = os.path.getsize(OUT_PATH) / (1024 * 1024)
    unique_tickers = df["ticker"].nunique()
    total_rows = len(df)
    min_date = df["date"].min().strftime("%Y-%m-%d")
    max_date = df["date"].max().strftime("%Y-%m-%d")

    print("\n" + "=" * 60)
    print("退市股票日线补齐完成！核验结果如下：")
    print(f"文件大小: {file_size_mb:.2f} MB")
    print(f"覆盖退市股票只数: {unique_tickers} 只")
    print(f"总日线 K 线行数: {total_rows} 行")
    print(f"起止日期跨度: {min_date} 至 {max_date}")
    print(f"数据列清单与类型:\n{df.dtypes}")
    print("前 3 行数据预览:\n", df.head(3))
    print("=" * 60 + "\n")


def main():
    start_t = time.time()
    current_tickers = get_current_tickers()
    delisted_dict = get_delisted_candidates(current_tickers)
    df = fetch_delisted_daily(delisted_dict)
    save_and_verify(df)
    print(f"总执行耗时: {time.time() - start_t:.1f} 秒", flush=True)


if __name__ == "__main__":
    main()
