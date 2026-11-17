# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.31", "pandas>=2.0"]
# ///

"""
A股历史价格数据下载脚本
下载 2024-01-01 至 2026-05-28 的 OHLCV 日线数据
同时计算 ATR / RS / 日均成交额指标

运行方式：
  uv run --script backtest/data/download_astock_data.py
"""

import json
import math
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

# ─── 配置 ────────────────────────────────────────────────────────────────────

START_DATE = "2024-01-01"
END_DATE   = "2026-05-28"

TICKERS = [
    # 半导体链
    "002028.SZ", "688019.SS", "300502.SZ", "002463.SZ", "688036.SS",
    "603501.SS", "002938.SZ", "300661.SZ", "688981.SS", "002371.SZ",
    # 新能源/光伏/储能
    "300274.SZ", "601012.SS", "002459.SZ", "300750.SZ", "600438.SS",
    # 医药
    "600276.SS", "300760.SZ", "688185.SS", "000858.SZ", "300347.SZ",
    # 消费/白酒
    "600519.SS", "000568.SZ", "002304.SZ",
    # 军工
    "600760.SS", "002179.SZ", "600893.SS",
    # 化工
    "600160.SS", "002648.SZ",
    # AI/软件
    "002230.SZ", "688111.SS",
    # 电力设备
    "601877.SS", "300014.SZ",
    # 汽车/智驾
    "002920.SZ", "601238.SS",
    # 金融
    "601318.SS", "600036.SS",
    # 指数
    "000300.SS",   # 沪深300
    "000852.SS",   # 中证1000
    "399006.SZ",   # 创业板指
]

# 绝对路径，避免 cwd 问题
_SCRIPT_DIR          = os.path.dirname(os.path.abspath(__file__))
PRICE_CACHE_PATH     = os.path.join(_SCRIPT_DIR, "astock_price_cache_2024_2026.json")
INDICATOR_CACHE_PATH = os.path.join(_SCRIPT_DIR, "astock_indicators_2024_2026.json")

# 缺失天数超过总交易日 20% 则发出 warning
MISSING_THRESHOLD = 0.20

# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def safe_float(v):
    """把 numpy/nan 转换成可 JSON 序列化的 Python float；NaN/Inf → None"""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except (TypeError, ValueError):
        return None


def to_list(series: pd.Series) -> list:
    return [safe_float(v) for v in series.tolist()]


def extract_ticker_df(raw, ticker: str) -> pd.DataFrame:
    """
    从 yfinance 批量下载结果中提取单只 ticker 的 OHLCV DataFrame。

    yfinance >= 0.2.x 批量下载 group_by='ticker' 时返回 MultiIndex columns:
      level-0 = Price字段 (Close/High/Low/Open/Volume)
      level-1 = Ticker

    单只 ticker 下载时同样返回 MultiIndex:
      level-0 = Price字段
      level-1 = Ticker (只有一个值)
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    if not isinstance(raw.columns, pd.MultiIndex):
        # 极旧版本 yfinance 平坦列
        return raw.copy()

    # 确认 ticker 存在于第二层
    tickers_in_data = raw.columns.get_level_values(1).unique().tolist()
    if ticker not in tickers_in_data:
        return pd.DataFrame()

    # xs 提取：返回 (Date × field) 的普通 DataFrame
    df = raw.xs(ticker, axis=1, level=1).copy()
    return df


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将列名统一为 Title-case（Open/High/Low/Close/Volume）"""
    rename = {}
    for col in df.columns:
        title = col.strip().title()
        rename[col] = title
    return df.rename(columns=rename)


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True Range → Wilder's smoothing ATR（EWM with span = 2*period - 1）"""
    high       = df["High"]
    low        = df["Low"]
    close      = df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=2 * period - 1, min_periods=period, adjust=False).mean()
    return atr


def calc_rs(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    相对强度 RS = 20日收益率 / 20日收益率标准差（年化波动率近似）
    正值 = 趋势向上且动量强；负值 = 下跌趋势。
    """
    ret      = df["Close"].pct_change()
    roll_ret = df["Close"].pct_change(period)
    roll_vol = ret.rolling(period).std()
    rs = roll_ret / roll_vol.replace(0.0, float("nan"))
    return rs


def calc_turnover(df: pd.DataFrame) -> pd.Series:
    """日成交额（元）= Close × Volume"""
    return df["Close"] * df["Volume"]


# ─── 主下载逻辑 ───────────────────────────────────────────────────────────────

def download_all() -> bool:
    failed_tickers  : list[str] = []
    warning_tickers : list[str] = []
    price_store     : dict = {}
    indicator_store : dict = {}

    print(f"[INFO] 开始下载 {len(TICKERS)} 个标的  {START_DATE} → {END_DATE}")
    print("=" * 60)

    # ── 批量下载 ────────────────────────────────────────────────────────────
    print("[INFO] 批量下载中（yfinance group_by='ticker'）...")
    try:
        raw = yf.download(
            tickers   = TICKERS,
            start     = START_DATE,
            end       = END_DATE,
            group_by  = "ticker",
            auto_adjust = True,
            threads   = True,
            progress  = True,
        )
        print(f"[INFO] 批量下载完成，raw.shape={raw.shape}, columns层数={raw.columns.nlevels}")
    except Exception as exc:
        print(f"[ERROR] 批量下载异常: {exc}")
        raw = None

    # ── 基准交易日（用第一个成功 ticker 的行数作为基准）──────────────────
    reference_days: int | None = None

    # ── 逐 ticker 解析 ──────────────────────────────────────────────────────
    for ticker in TICKERS:
        print(f"\n[{ticker}] 处理中...", end=" ", flush=True)

        # 1) 从批量结果中提取
        df = extract_ticker_df(raw, ticker)

        # 2) 如果批量结果为空，单独重下
        if df.empty:
            print("(批量提取为空，单独重下)", end=" ", flush=True)
            try:
                single_raw = yf.download(
                    tickers     = ticker,
                    start       = START_DATE,
                    end         = END_DATE,
                    auto_adjust = True,
                    progress    = False,
                )
                df = extract_ticker_df(single_raw, ticker)
                if df.empty and not single_raw.empty:
                    # 兼容极旧版本
                    df = single_raw.copy()
            except Exception as exc:
                print(f"→ 单独下载异常: {exc}")
                failed_tickers.append(ticker)
                continue

        if df is None or df.empty:
            print("→ 无数据，记录为失败")
            failed_tickers.append(ticker)
            continue

        # 3) 列名标准化
        df = normalize_columns(df)

        # 4) 必要列检查
        required = {"Open", "High", "Low", "Close", "Volume"}
        missing_cols = required - set(df.columns)
        if missing_cols:
            print(f"→ 列缺失 {missing_cols}，跳过")
            failed_tickers.append(ticker)
            continue

        # 5) 清洗
        df = df.dropna(subset=["Close"]).sort_index()
        n_days = len(df)

        if n_days == 0:
            print("→ 清洗后无行，跳过")
            failed_tickers.append(ticker)
            continue

        if reference_days is None:
            reference_days = n_days

        # 6) 缺失率检查
        if reference_days and reference_days > 0:
            missing_ratio = 1.0 - n_days / reference_days
            if missing_ratio > MISSING_THRESHOLD:
                msg = f"{ticker} (缺失 {missing_ratio:.1%}, 有 {n_days}/{reference_days} 天)"
                warning_tickers.append(msg)
                print(f"⚠ 缺失率 {missing_ratio:.1%}", end=" ", flush=True)

        print(f"→ {n_days} 个交易日", end=" ", flush=True)

        # 7) 日期序列
        dates = [d.strftime("%Y-%m-%d") for d in df.index]

        # 8) 价格缓存
        price_store[ticker] = {
            "dates":  dates,
            "open":   to_list(df["Open"]),
            "high":   to_list(df["High"]),
            "low":    to_list(df["Low"]),
            "close":  to_list(df["Close"]),
            "volume": to_list(df["Volume"]),
        }

        # 9) 指标计算
        atr      = calc_atr(df, period=14)
        rs       = calc_rs(df, period=20)
        turnover = calc_turnover(df)

        indicator_store[ticker] = {
            "dates":        dates,
            "atr_14":       to_list(atr),
            "rs_20":        to_list(rs),
            "turnover_cny": to_list(turnover),
        }

        print("✓", flush=True)

    # ── 写 Price Cache ──────────────────────────────────────────────────────
    trading_days = reference_days or 0
    generated_at = datetime.now().isoformat(timespec="seconds")

    price_output = {
        "_meta": {
            "generated":      generated_at,
            "period":         f"{START_DATE} to {END_DATE}",
            "tickers_count":  len(TICKERS),
            "trading_days":   trading_days,
            "failed_tickers": failed_tickers,
        },
        **price_store,
    }

    with open(PRICE_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(price_output, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n[OK] 价格缓存写入: {PRICE_CACHE_PATH}")

    # ── 写 Indicator Cache ───────────────────────────────────────────────────
    indicator_output = {
        "_meta": {
            "generated":      generated_at,
            "period":         f"{START_DATE} to {END_DATE}",
            "tickers_count":  len(TICKERS),
            "trading_days":   trading_days,
            "indicators":     ["atr_14", "rs_20", "turnover_cny"],
            "failed_tickers": failed_tickers,
        },
        **indicator_store,
    }

    with open(INDICATOR_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(indicator_output, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[OK] 指标缓存写入: {INDICATOR_CACHE_PATH}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("DOWNLOAD SUMMARY")
    print("=" * 60)
    print(f"  总标的数      : {len(TICKERS)}")
    print(f"  成功下载      : {len(price_store)}")
    print(f"  失败标的      : {len(failed_tickers)}")
    print(f"  Warning 标的  : {len(warning_tickers)}")
    print(f"  基准交易日数   : {trading_days}")
    print(f"  生成时间      : {generated_at}")
    print(f"  价格缓存路径  : {PRICE_CACHE_PATH}")
    print(f"  指标缓存路径  : {INDICATOR_CACHE_PATH}")

    if failed_tickers:
        print("\n[FAILED TICKERS]")
        for t in failed_tickers:
            print(f"  ✗ {t}")

    if warning_tickers:
        print("\n[WARNING — 数据不足]")
        for w in warning_tickers:
            print(f"  ⚠ {w}")

    print("=" * 60)
    return len(failed_tickers) == 0


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ok = download_all()
    sys.exit(0 if ok else 1)
