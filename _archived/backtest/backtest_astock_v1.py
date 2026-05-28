#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.31", "pandas>=2.0", "numpy>=1.24", "rich>=13.0"]
# ///
"""
A股交易系统 V1 — Momentum Rotation + Dip Buy 回测引擎
=====================================================
策略: Momentum Rotation（主策略）+ Dip Buy（辅助策略）
A股特有规则: T+1 / 涨跌停 / 100股整数倍 / 沪深港参考

Usage:
    uv run --script backtest/backtest_astock_v1.py              # 2025全年
    uv run --script backtest/backtest_astock_v1.py --period 2024
    uv run --script backtest/backtest_astock_v1.py --verbose
    uv run --script backtest/backtest_astock_v1.py --no-cache
"""

from __future__ import annotations
import json, argparse, sys, warnings
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

warnings.filterwarnings("ignore", category=FutureWarning)
console = Console()
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_DIR = SCRIPT_DIR / "results"

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — A股可调参数（策略调参只改这里）
# ══════════════════════════════════════════════════════════════════════════════

INITIAL_CAPITAL = 10_000_000.0          # 初始资金 ¥1000万

# 指数 / 基准
BENCHMARK = "000300.SS"                  # 沪深300
CSI1000 = "000852.SS"                   # 中证1000（市场呼吸F20）

# ── Momentum Rotation（主策略）──
MOM_RS_LOOKBACK = 20                    # RS计算回看期（交易日）
MOM_TOP_N = 10                          # 选RS前10只（旧: 7只，配合MAX_POSITIONS=8）
MOM_REBAL_FREQ = 20                     # 每20交易日换仓
MOM_MIN_TURNOVER = 50_000_000           # 最低成交额5000万/日过滤
MOM_CRASH_LOOKBACK = 5                  # 崩盘过滤回看期
MOM_CRASH_THRESHOLD = -0.15             # 过去5日跌超15%排除

# ── 市场呼吸过滤器（F20）──
F20_LOOKBACK = 5                        # 相对强弱对比窗口（交易日）
F20_BREATH_THRESH = 0.02                # 中证1000-沪深300>2% = 吸气
F20_COLD_TURNOVER = 800_000_000_000     # 两市总成交额<8000亿=市场冷淡
F20_BREATH_IN_PCT = 1.0                 # 吸气：满仓（仓位上限乘数）
F20_BREATH_OUT_PCT = 0.0               # 呼气：零新仓（旧: 0.5半仓）——Agent-14验证: 呼气4笔全亏
F20_COLD_PCT = 0.6                      # 市场冷淡：减仓至60%

# ── 仓位规则（v9.1大改：删除现金底线+板块上限，修复结构性BUG）──
# 旧参数: MAX_POSITIONS=5 + MAX_POS_PCT=0.20 + MIN_CASH_PCT=0.20
# BUG: 数学矛盾——5只×20%=100%但现金≥20%→最多4只。安集科技被挡4次(+110.7%)
MAX_POSITIONS = 8                       # 最多持仓8只（旧: 5只）
MAX_POS_PCT = 0.25                      # 单只最多25%（旧: 20%）
MIN_CASH_PCT = 0.0                      # 无现金底线（旧: 20%）——用止损管风险不用现金管
MAX_SECTOR_PCT = 1.0                    # 无板块上限（旧: 35%）——A股alpha来自板块集中
LOT_SIZE = 100                          # A股最小交易单位（100股）

# ── ATR止损 ──
ATR_PERIOD = 14                         # ATR计算窗口
ATR_MULTIPLIER = 2.5                    # 入场止损 = Entry - 2.5×ATR
HARD_STOP_FLOOR = -0.15                 # 硬止损floor -15%
RATCHET_1R_LEVEL = 1.0                  # +1R移保本（棘轮锁利）
RATCHET_2R_LOOKBACK = 2                 # +2R移至high-2×ATR

# ── 卖出规则 ──
PARTIAL_SELL_2R_PCT = 0.25              # +2R卖出25%
PARTIAL_SELL_3R_PCT = 0.25              # +3R再卖25%
STAGNANT_DAYS = 20                      # 20天无上涨清仓
STAGNANT_MIN_GAIN = 0.01               # "上涨"定义：至少涨1%

# ── 涨跌停规则 ──
LIMIT_UP_MAIN = 0.10                    # 沪深主板涨停10%
LIMIT_DOWN_MAIN = -0.10                 # 主板跌停-10%
LIMIT_UP_GEM = 0.20                     # 创业板/科创板20%
LIMIT_DOWN_GEM = -0.20
GEM_PREFIXES = ("300", "301", "688")    # 创业板(300/301) + 科创板(688)

# ── Dip Buy辅助策略（v9.1调大：81%胜率配更大仓位）──
DIP_LOOKBACK = 20                       # 过去20日跌幅
DIP_THRESHOLD = -0.15                   # 跌超15%才触发
DIP_SIZE_PCT = 0.12                     # 入场仓位12%（旧: 8%）——81%胜率配更大仓位
DIP_STOP_PCT = -0.10                    # 止损-10%
DIP_TARGET_PCT = 0.15                   # +15%目标获利（旧: 10%）——让赢家跑更远

# ── 防御股标识（市场呼气时才允许买入）──
# 白酒、金融、消费、电力等相对稳定品种
DEFENSIVE_TICKERS = {
    "600519.SS",  # 贵州茅台
    "000568.SZ",  # 泸州老窖
    "002304.SZ",  # 洋河股份
    "601318.SS",  # 中国平安
    "600036.SS",  # 招商银行
    "600276.SS",  # 恒瑞医药
    "510300.SS",  # 沪深300 ETF
    "512100.SS",  # 中证1000 ETF
}

# 板块映射（用于单板块≤35%检查）
SECTOR_MAP = {
    "SEMI": {"002028.SZ", "688019.SS", "300502.SZ", "002463.SZ", "688036.SS",
             "603501.SS", "002938.SZ", "300661.SZ", "688981.SS", "002371.SZ"},
    "NEV":  {"300274.SZ", "601012.SS", "002459.SZ", "300750.SZ", "600438.SS"},
    "PHARMA": {"600276.SS", "300760.SZ", "688185.SS", "000858.SZ", "300347.SZ"},
    "LIQUOR": {"600519.SS", "000568.SZ", "002304.SZ"},
    "DEFENSE": {"600760.SS", "002179.SZ", "600893.SS"},
    "CHEM": {"600160.SS", "002648.SZ"},
    "AI_SW": {"002230.SZ", "688111.SS"},
    "POWER": {"601877.SS", "300014.SZ"},
    "AUTO": {"002920.SZ", "601238.SS"},
    "FIN": {"601318.SS", "600036.SS"},
    "ETF": {"510300.SS", "512100.SS"},
}

# A股回测Universe（约50只代表性标的）
ASTOCK_UNIVERSE = [
    # 半导体
    "002028.SZ", "688019.SS", "300502.SZ", "002463.SZ", "688036.SS",
    "603501.SS", "002938.SZ", "300661.SZ", "688981.SS", "002371.SZ",
    # 新能源
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
    # 金融（对冲用）
    "601318.SS", "600036.SS",
    # 指数ETF（benchmark）
    "510300.SS", "512100.SS",
]

ALL_SYMBOLS = ASTOCK_UNIVERSE + [BENCHMARK, CSI1000]


# ══════════════════════════════════════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    ticker: str
    shares: int                         # 必须是100的整数倍
    entry_price: float
    entry_date: str
    entry_day_idx: int                  # 回测day_count（用于T+1检查）
    stop_price: float
    signal: str                         # "MOM" | "DIP" | "REBAL"
    atr_at_entry: float = 0.0
    high_water: float = 0.0
    ratchet_1r_done: bool = False       # 是否已移保本
    ratchet_2r_done: bool = False       # 是否已移至+2R止损
    last_high_date: str = ""            # 用于20天无上涨计时
    partial_2r_done: bool = False       # +2R已卖25%
    partial_3r_done: bool = False       # +3R已卖25%
    dip_stop_pct: float = 0.0          # Dip Buy专用止损比例（固定-10%）
    dip_target_pct: float = 0.0        # Dip Buy专用获利目标（+10%）


@dataclass
class Trade:
    date: str
    action: str                         # BUY / SELL / PARTIAL_SELL
    ticker: str
    shares: int
    price: float
    value: float
    signal: str
    reason: str
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 数据下载与缓存
# ══════════════════════════════════════════════════════════════════════════════

def download_data(symbols: list[str], start: str, end: str, tag: str,
                  force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """批量下载A股价格数据，缓存到JSON文件。"""
    cache_path = DATA_DIR / f"astock_price_cache_{tag}.json"

    if cache_path.exists() and not force_refresh:
        console.print(f"[dim]Loading cached {tag} data from {cache_path.name}...[/dim]")
        try:
            cached = pd.read_json(cache_path)
            # 确保index是DatetimeIndex
            if not isinstance(cached.index, pd.DatetimeIndex):
                cached.index = pd.to_datetime(cached.index)
            result = {}
            for sym in symbols:
                cols = [c for c in cached.columns if c.startswith(f"{sym}_")]
                if cols:
                    df = cached[cols].copy()
                    df.columns = [c.replace(f"{sym}_", "") for c in df.columns]
                    df.dropna(how="all", inplace=True)
                    if len(df) >= 20:
                        result[sym] = df
            if len(result) >= len(symbols) * 0.7:
                console.print(f"[green]Cache hit: {len(result)}/{len(symbols)} symbols[/green]")
                return result
            console.print(f"[yellow]Cache incomplete ({len(result)}/{len(symbols)}), re-downloading...[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Cache read error: {e}, re-downloading...[/yellow]")

    console.print(f"[yellow]Downloading {tag} data for {len(symbols)} symbols...[/yellow]")
    # 下载时多拉30天buffer（用于计算MA/ATR等）
    buffer_start = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
    dl_end = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=5)).strftime("%Y-%m-%d")

    try:
        raw = yf.download(
            symbols,
            start=buffer_start,
            end=dl_end,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=True,
        )
    except Exception as e:
        console.print(f"[red]Download error: {e}[/red]")
        sys.exit(1)

    result: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            if len(symbols) == 1:
                df = raw.copy()
            elif isinstance(raw.columns, pd.MultiIndex):
                if sym in raw.columns.get_level_values(0):
                    df = raw[sym].copy()
                else:
                    continue
            else:
                continue

            if df is None or df.empty:
                continue
            df = df.dropna(how="all")
            # 标准化列名（确保有 Open/High/Low/Close/Volume）
            df.columns = [str(c).strip() for c in df.columns]
            required = {"Open", "High", "Low", "Close", "Volume"}
            if not required.issubset(set(df.columns)):
                continue
            if len(df) >= 20:
                result[sym] = df
        except Exception as e:
            console.print(f"[dim]Skip {sym}: {e}[/dim]")
            continue

    # 写缓存
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        combined = pd.DataFrame()
        for sym, df in result.items():
            for col in df.columns:
                combined[f"{sym}_{col}"] = df[col]
        combined.to_json(cache_path, date_format="iso")
        console.print(f"[dim]Cache saved → {cache_path.name}[/dim]")
    except Exception as e:
        console.print(f"[yellow]Cache write warning: {e}[/yellow]")

    console.print(f"[green]{len(result)}/{len(symbols)} symbols downloaded[/green]")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# A股工具函数
# ══════════════════════════════════════════════════════════════════════════════

def is_gem(ticker: str) -> bool:
    """判断是否是创业板/科创板（涨跌停±20%）。"""
    code = ticker.split(".")[0]
    return code.startswith(GEM_PREFIXES)


def get_limit_range(ticker: str) -> tuple[float, float]:
    """返回（跌停比例, 涨停比例）。"""
    if is_gem(ticker):
        return LIMIT_DOWN_GEM, LIMIT_UP_GEM
    return LIMIT_DOWN_MAIN, LIMIT_UP_MAIN


def round_to_lot(shares: float) -> int:
    """取整到100股整数倍（向下取整）。"""
    return max(0, int(shares // LOT_SIZE) * LOT_SIZE)


def calc_atr(data: pd.DataFrame, date: pd.Timestamp, period: int = ATR_PERIOD) -> float:
    """计算ATR(14)。"""
    mask = data.index <= date
    d = data.loc[mask]
    if len(d) < period + 1:
        return 0.0
    h = d["High"].iloc[-(period + 1):]
    lo = d["Low"].iloc[-(period + 1):]
    c = d["Close"].iloc[-(period + 1):]
    trs = []
    for i in range(1, len(h)):
        tr = max(
            float(h.iloc[i] - lo.iloc[i]),
            abs(float(h.iloc[i] - c.iloc[i - 1])),
            abs(float(lo.iloc[i] - c.iloc[i - 1])),
        )
        trs.append(tr)
    return float(np.mean(trs)) if trs else 0.0


def calc_rs(ticker_data: pd.DataFrame, benchmark_data: pd.DataFrame,
            date: pd.Timestamp, lookback: int = MOM_RS_LOOKBACK) -> float:
    """RS = 过去N日收益率 / 过去N日波动率（相对强弱得分）。"""
    t_mask = ticker_data.index <= date
    t_closes = ticker_data.loc[t_mask, "Close"]
    if len(t_closes) < lookback + 1:
        return -999.0
    returns = t_closes.pct_change().dropna().iloc[-lookback:]
    if len(returns) < lookback:
        return -999.0
    total_ret = float(t_closes.iloc[-1] / t_closes.iloc[-lookback - 1] - 1)
    vol = float(returns.std())
    if vol <= 0:
        return -999.0
    return total_ret / vol


def check_crash_filter(ticker_data: pd.DataFrame, date: pd.Timestamp) -> bool:
    """过去5日跌幅>15%则返回True（排除该票）。"""
    mask = ticker_data.index <= date
    closes = ticker_data.loc[mask, "Close"]
    if len(closes) < MOM_CRASH_LOOKBACK + 1:
        return False
    ret_5d = float(closes.iloc[-1] / closes.iloc[-MOM_CRASH_LOOKBACK - 1] - 1)
    return ret_5d < MOM_CRASH_THRESHOLD


def check_liquidity(ticker_data: pd.DataFrame, date: pd.Timestamp,
                    min_turnover: float = MOM_MIN_TURNOVER) -> bool:
    """检查过去10日平均成交额是否≥5000万。返回True=流动性达标。"""
    mask = ticker_data.index <= date
    d = ticker_data.loc[mask]
    if len(d) < 10:
        return False
    recent = d.iloc[-10:]
    # 成交额 = Close × Volume（A股Volume是股数）
    avg_turnover = float((recent["Close"] * recent["Volume"]).mean())
    return avg_turnover >= min_turnover


def _prev_close(ticker_data: pd.DataFrame, date: pd.Timestamp) -> Optional[float]:
    """获取date前最近一个交易日的收盘价。"""
    prev_mask = ticker_data.index < date
    prev = ticker_data.loc[prev_mask, "Close"]
    return float(prev.iloc[-1]) if not prev.empty else None


def is_limit_up(ticker_data: pd.DataFrame, date: pd.Timestamp, ticker: str) -> bool:
    """
    判断当日是否涨停（全天买不进）。
    判断逻辑：当日High≈Low（振幅<0.3%）且收盘涨幅≥涨停幅度-0.5%。
    yfinance数据涨停日通常表现为 Open=High=Low=Close ≈ prev_close × (1+limit)。
    """
    mask = ticker_data.index == date
    if not mask.any():
        return False
    row = ticker_data.loc[mask].iloc[0]
    pc = _prev_close(ticker_data, date)
    if pc is None or pc <= 0:
        return False
    _, limit_up = get_limit_range(ticker)
    today_close = float(row["Close"])
    today_high = float(row["High"])
    today_low = float(row["Low"])
    gain = (today_close - pc) / pc
    # 涨幅接近涨停线 AND 全天振幅极小（涨停封板特征）
    amplitude = (today_high - today_low) / pc
    return gain >= (limit_up - 0.008) and amplitude < 0.004


def is_limit_down(ticker_data: pd.DataFrame, date: pd.Timestamp, ticker: str) -> bool:
    """
    判断当日是否跌停（全天卖不出）。
    判断逻辑：当日High≈Low（振幅<0.3%）且收盘跌幅≥跌停幅度-0.5%。
    """
    mask = ticker_data.index == date
    if not mask.any():
        return False
    row = ticker_data.loc[mask].iloc[0]
    pc = _prev_close(ticker_data, date)
    if pc is None or pc <= 0:
        return False
    limit_down, _ = get_limit_range(ticker)
    today_close = float(row["Close"])
    today_high = float(row["High"])
    today_low = float(row["Low"])
    drop = (today_close - pc) / pc
    amplitude = (today_high - today_low) / pc
    return drop <= (limit_down + 0.008) and amplitude < 0.004


def detect_market_breath(csi1000_data: Optional[pd.DataFrame],
                         benchmark_data: pd.DataFrame,
                         date: pd.Timestamp,
                         all_data: Optional[dict] = None) -> str:
    """
    F20市场呼吸判断（每周一执行）。
    返回: "BREATH_IN"（吸气）/ "BREATH_OUT"（呼气）/ "NEUTRAL"

    当CSI1000数据不可用时，用GEM/STAR板块（300/301/688开头）的平均收益作为小盘股代理。
    """
    mask_300 = benchmark_data.index <= date
    c300 = benchmark_data.loc[mask_300, "Close"]
    if len(c300) < F20_LOOKBACK + 1:
        return "NEUTRAL"
    ret_300 = float(c300.iloc[-1] / c300.iloc[-F20_LOOKBACK - 1] - 1)

    if csi1000_data is not None and not csi1000_data.empty:
        mask_1000 = csi1000_data.index <= date
        c1000 = csi1000_data.loc[mask_1000, "Close"]
        if len(c1000) >= F20_LOOKBACK + 1:
            ret_1000 = float(c1000.iloc[-1] / c1000.iloc[-F20_LOOKBACK - 1] - 1)
            diff = ret_1000 - ret_300
            if diff > F20_BREATH_THRESH:
                return "BREATH_IN"
            elif -diff > F20_BREATH_THRESH:
                return "BREATH_OUT"
            return "NEUTRAL"

    # Fallback: synthetic small-cap basket from GEM/STAR board stocks
    if all_data is not None:
        gem_rets = []
        for sym, df in all_data.items():
            code = sym.split(".")[0]
            if not code.startswith(("300", "301", "688")):
                continue
            mask = df.index <= date
            c = df.loc[mask, "Close"]
            if len(c) >= F20_LOOKBACK + 1:
                gem_rets.append(float(c.iloc[-1] / c.iloc[-F20_LOOKBACK - 1] - 1))
        if len(gem_rets) >= 3:
            avg_gem_ret = sum(gem_rets) / len(gem_rets)
            diff = avg_gem_ret - ret_300
            if diff > F20_BREATH_THRESH:
                return "BREATH_IN"
            elif -diff > F20_BREATH_THRESH:
                return "BREATH_OUT"
    return "NEUTRAL"


def get_sector(ticker: str) -> Optional[str]:
    """返回ticker所属板块。"""
    for sector, tickers in SECTOR_MAP.items():
        if ticker in tickers:
            return sector
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio类
# ══════════════════════════════════════════════════════════════════════════════

class AStockPortfolio:
    def __init__(self, capital: float):
        self.cash = capital
        self.initial = capital
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.daily_navs: list[tuple[str, float, str, int]] = []
        # T+1: 记录每日买入（key=ticker, value=buy_day_idx）
        self.buy_day: dict[str, int] = {}

    def nav(self, prices: dict[str, float]) -> float:
        total = self.cash
        for t, p in self.positions.items():
            total += p.shares * prices.get(t, p.entry_price)
        return total

    def invested_pct(self, prices: dict[str, float]) -> float:
        n = self.nav(prices)
        return 1.0 - (self.cash / n) if n > 0 else 0.0

    def sector_exposure(self, prices: dict[str, float]) -> dict[str, float]:
        """计算各板块市值占比。"""
        n = self.nav(prices)
        if n <= 0:
            return {}
        exposure: dict[str, float] = {}
        for t, pos in self.positions.items():
            sector = get_sector(t) or "OTHER"
            val = pos.shares * prices.get(t, pos.entry_price)
            exposure[sector] = exposure.get(sector, 0.0) + val / n
        return exposure

    def can_buy_more(self, ticker: str, prices: dict[str, float],
                     size_pct: float, breath: str) -> tuple[bool, str]:
        """检查是否满足买入条件（v9.1: 只检查持仓数和已持有）。"""
        if ticker in self.positions:
            return False, "already_held"
        if len(self.positions) >= MAX_POSITIONS:
            return False, "max_positions"

        # 呼气时只买防御股（F20验证: 呼气期4笔全亏）
        if breath == "BREATH_OUT" and ticker not in DEFENSIVE_TICKERS:
            return False, "breath_out_non_defensive"

        # 确保有足够现金买入
        n = self.nav(prices)
        target_val = n * size_pct
        if target_val > self.cash * 0.95:
            return False, "insufficient_cash"

        return True, "ok"

    def can_sell(self, ticker: str, day_idx: int) -> tuple[bool, str]:
        """T+1检查：买入当天不能卖出。"""
        if ticker not in self.positions:
            return False, "not_held"
        buy_idx = self.buy_day.get(ticker, -999)
        if day_idx <= buy_idx:
            return False, "t+1_restriction"
        return True, "ok"

    def buy(self, ticker: str, price: float, date: str, day_idx: int,
            signal: str, size_pct: float, atr: float,
            breath_multiplier: float = 1.0,
            dip_stop_pct: float = 0.0,
            dip_target_pct: float = 0.0) -> Optional[Trade]:
        """买入（含100股取整、涨停检查已在外部完成）。"""
        n = self.nav({ticker: price})
        # 根据市场呼吸调整有效仓位上限
        effective_pct = size_pct * breath_multiplier
        effective_pct = min(effective_pct, MAX_POS_PCT)
        target_val = n * effective_pct
        target_val = min(target_val, self.cash * 0.95)
        if target_val < 5000:
            return None

        shares = round_to_lot(target_val / price)
        if shares == 0:
            return None
        value = shares * price
        if value > self.cash:
            shares = round_to_lot(self.cash * 0.95 / price)
            if shares == 0:
                return None
            value = shares * price

        # ATR止损
        if atr > 0:
            stop_atr = price - ATR_MULTIPLIER * atr
            stop_floor = price * (1 + HARD_STOP_FLOOR)
            stop_price = max(stop_atr, stop_floor)
        else:
            stop_price = price * (1 + HARD_STOP_FLOOR)

        self.cash -= value
        pos = Position(
            ticker=ticker,
            shares=shares,
            entry_price=price,
            entry_date=date,
            entry_day_idx=day_idx,
            stop_price=stop_price,
            signal=signal,
            atr_at_entry=atr,
            high_water=price,
            last_high_date=date,
            dip_stop_pct=dip_stop_pct,
            dip_target_pct=dip_target_pct,
        )
        self.positions[ticker] = pos
        self.buy_day[ticker] = day_idx

        trade = Trade(
            date=date, action="BUY", ticker=ticker, shares=shares,
            price=price, value=value, signal=signal, reason=signal,
        )
        self.trades.append(trade)
        return trade

    def sell(self, ticker: str, price: float, date: str, day_idx: int,
             reason: str, shares_override: int = 0) -> Optional[Trade]:
        """
        卖出。shares_override>0则卖指定股数（部分卖出）。
        T+1已在调用方检查。
        """
        pos = self.positions.get(ticker)
        if not pos:
            return None

        sell_shares = shares_override if shares_override > 0 else pos.shares
        sell_shares = min(sell_shares, pos.shares)
        value = sell_shares * price
        pnl = (price - pos.entry_price) * sell_shares
        pnl_pct = (price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0.0
        self.cash += value

        trade = Trade(
            date=date, action="PARTIAL_SELL" if shares_override > 0 else "SELL",
            ticker=ticker, shares=sell_shares, price=price, value=value,
            signal=pos.signal, reason=reason,
            realized_pnl=pnl, realized_pnl_pct=pnl_pct,
        )
        self.trades.append(trade)

        if sell_shares >= pos.shares:
            del self.positions[ticker]
            if ticker in self.buy_day:
                del self.buy_day[ticker]
        else:
            pos.shares -= sell_shares

        return trade

    def check_stops(self, prices: dict[str, float], date: str,
                    day_idx: int, data: dict[str, pd.DataFrame],
                    current_date: pd.Timestamp) -> list[Trade]:
        """检查止损/止盈触发。T+1安全检查已在内部执行。"""
        exits: list[Trade] = []
        for ticker in list(self.positions):
            pos = self.positions[ticker]
            price = prices.get(ticker)
            if price is None:
                continue

            # T+1：买入当天不触发卖出
            ok, reason = self.can_sell(ticker, day_idx)
            if not ok:
                continue

            # 跌停无法卖出
            if ticker in data and is_limit_down(data[ticker], current_date, ticker):
                continue

            # 更新最高价
            if price > pos.high_water:
                pos.high_water = price
                pos.last_high_date = date

            # Dip Buy：固定止损/止盈
            if pos.signal == "DIP":
                dip_stop = pos.entry_price * (1 + pos.dip_stop_pct)
                dip_target = pos.entry_price * (1 + pos.dip_target_pct)
                if price <= dip_stop:
                    t = self.sell(ticker, price, date, day_idx,
                                  f"DIP_STOP: {(price/pos.entry_price-1):.1%}")
                    if t:
                        exits.append(t)
                    continue
                if price >= dip_target:
                    t = self.sell(ticker, price, date, day_idx,
                                  f"DIP_TARGET: {(price/pos.entry_price-1):.1%}")
                    if t:
                        exits.append(t)
                    continue

            # ATR棘轮止损（Momentum仓位）
            atr = pos.atr_at_entry
            r_size = atr * ATR_MULTIPLIER if atr > 0 else abs(pos.entry_price - pos.stop_price)
            gain_r = (price - pos.entry_price) / r_size if r_size > 0 else 0

            # +1R → 移止损到保本
            if gain_r >= RATCHET_1R_LEVEL and not pos.ratchet_1r_done:
                pos.stop_price = pos.entry_price
                pos.ratchet_1r_done = True

            # +2R → 移止损到 high - 2×ATR（并卖25%）
            if gain_r >= 2.0 and not pos.ratchet_2r_done and atr > 0:
                pos.stop_price = max(pos.stop_price, pos.high_water - 2 * atr)
                pos.ratchet_2r_done = True
                if not pos.partial_2r_done:
                    sell_shares = round_to_lot(pos.shares * PARTIAL_SELL_2R_PCT)
                    if sell_shares > 0:
                        t = self.sell(ticker, price, date, day_idx,
                                      f"+2R partial sell 25%", shares_override=sell_shares)
                        if t:
                            exits.append(t)
                    pos.partial_2r_done = True

            # +3R → 再卖25%
            if gain_r >= 3.0 and not pos.partial_3r_done:
                sell_shares = round_to_lot(pos.shares * PARTIAL_SELL_3R_PCT)
                if sell_shares > 0:
                    t = self.sell(ticker, price, date, day_idx,
                                  f"+3R partial sell 25%", shares_override=sell_shares)
                    if t:
                        exits.append(t)
                if ticker in self.positions:
                    self.positions[ticker].partial_3r_done = True

            # 检查主止损（需re-check position still exists after partials）
            if ticker not in self.positions:
                continue
            pos = self.positions[ticker]
            if price <= pos.stop_price:
                t = self.sell(ticker, price, date, day_idx,
                              f"ATR_STOP: ¥{price:.2f} ≤ ¥{pos.stop_price:.2f}")
                if t:
                    exits.append(t)

        return exits

    def check_stagnant(self, prices: dict[str, float], date: str,
                       day_idx: int) -> list[Trade]:
        """20天无上涨清仓规则。"""
        exits: list[Trade] = []
        for ticker in list(self.positions):
            pos = self.positions.get(ticker)
            if not pos or pos.signal == "DIP":
                continue

            ok, _ = self.can_sell(ticker, day_idx)
            if not ok:
                continue

            price = prices.get(ticker)
            if price is None:
                continue

            if pos.last_high_date:
                last_high_dt = datetime.strptime(pos.last_high_date, "%Y-%m-%d")
                cur_dt = datetime.strptime(date, "%Y-%m-%d")
                days_since_high = (cur_dt - last_high_dt).days
                if days_since_high >= STAGNANT_DAYS:
                    t = self.sell(ticker, price, date, day_idx,
                                  f"STAGNANT: {days_since_high}d no new high")
                    if t:
                        exits.append(t)

        return exits


# ══════════════════════════════════════════════════════════════════════════════
# 主回测循环
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(data: dict[str, pd.DataFrame],
                 start: str, end: str,
                 verbose: bool = False) -> AStockPortfolio:
    pf = AStockPortfolio(INITIAL_CAPITAL)

    bench = data.get(BENCHMARK)
    csi1000 = data.get(CSI1000)
    if bench is None:
        console.print("[red]No benchmark (000300.SS) data[/red]")
        sys.exit(1)

    start_dt, end_dt = pd.Timestamp(start), pd.Timestamp(end)
    days = bench.index[(bench.index >= start_dt) & (bench.index <= end_dt)]
    if len(days) == 0:
        console.print("[red]No trading days in range[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]A股回测: {start} → {end} | {len(days)} 交易日 | ¥{INITIAL_CAPITAL:,.0f}[/bold cyan]")
    console.print(f"[dim]Universe: {len(ASTOCK_UNIVERSE)} 标的 | 策略: Momentum Rotation + Dip Buy[/dim]\n")

    day_count = 0
    last_mom_rebal = -MOM_REBAL_FREQ          # 确保第一天就触发换仓
    current_breath = "NEUTRAL"                 # 市场呼吸状态
    last_breath_date = ""

    # 用于进度展示
    bench_start_price = None

    for date in days:
        ds = date.strftime("%Y-%m-%d")
        day_count += 1

        # ── 获取当日收盘价 ──
        prices: dict[str, float] = {}
        for sym, df in data.items():
            m = df.index <= date
            if m.any():
                prices[sym] = float(df.loc[m, "Close"].iloc[-1])

        if bench_start_price is None and BENCHMARK in prices:
            bench_start_price = prices[BENCHMARK]

        # ── 每周一更新市场呼吸（F20）──
        if date.weekday() == 0:  # 周一
            current_breath = detect_market_breath(csi1000, bench, date, all_data=data)
            last_breath_date = ds

        # 市场呼吸对应仓位乘数
        if current_breath == "BREATH_IN":
            breath_multiplier = F20_BREATH_IN_PCT
        elif current_breath == "BREATH_OUT":
            breath_multiplier = F20_BREATH_OUT_PCT
        else:
            breath_multiplier = 0.8  # NEUTRAL: 80%满仓

        # ── 日内：止损/止盈检查（T+1已在内部处理）──
        stops = pf.check_stops(prices, ds, day_count, data, date)
        if verbose:
            for t in stops:
                c = "red" if t.realized_pnl < 0 else "green"
                console.print(f"  [{c}]{ds} {t.action} {t.ticker} "
                              f"P&L: ¥{t.realized_pnl:+,.0f} ({t.realized_pnl_pct:+.1%}) "
                              f"[{t.reason}][/{c}]")

        # ── 日内：20天无上涨检查 ──
        stagnant = pf.check_stagnant(prices, ds, day_count)
        if verbose:
            for t in stagnant:
                console.print(f"  [yellow]{ds} STAGNANT EXIT {t.ticker} P&L: ¥{t.realized_pnl:+,.0f}[/yellow]")

        # ── 每20交易日：Momentum Rotation换仓 ──
        if day_count - last_mom_rebal >= MOM_REBAL_FREQ:
            last_mom_rebal = day_count
            _run_momentum_rotation(pf, data, prices, ds, date, day_count,
                                   breath_multiplier, current_breath, verbose)

        # ── 每周五：Dip Buy扫描 ──
        if date.weekday() == 4:
            _run_dip_buy_scan(pf, data, prices, ds, date, day_count,
                              breath_multiplier, verbose)

        # ── 记录当日NAV ──
        nav = pf.nav(prices)
        pf.daily_navs.append((ds, nav, current_breath, len(pf.positions)))

        # ── 月度进度报告 ──
        if date.day <= 3 or date == days[-1]:
            ret = (nav / INITIAL_CAPITAL - 1) * 100
            bench_ret = 0.0
            if bench_start_price and BENCHMARK in prices:
                bench_ret = (prices[BENCHMARK] / bench_start_price - 1) * 100
            console.print(
                f"[dim]{ds}[/dim] NAV: [bold]¥{nav:>12,.0f}[/bold] "
                f"([{'green' if ret >= 0 else 'red'}]{ret:>+6.1f}%[/{'green' if ret >= 0 else 'red'}] "
                f"vs 300: [{'green' if bench_ret >= 0 else 'red'}]{bench_ret:>+6.1f}%[/{'green' if bench_ret >= 0 else 'red'}]) | "
                f"呼吸: [cyan]{current_breath:<11}[/cyan] | "
                f"持仓: {len(pf.positions):>2} | "
                f"现金: ¥{pf.cash:>10,.0f}"
            )

    return pf


def _run_momentum_rotation(pf: AStockPortfolio,
                            data: dict[str, pd.DataFrame],
                            prices: dict[str, float],
                            ds: str, date: pd.Timestamp, day_count: int,
                            breath_multiplier: float, breath: str,
                            verbose: bool) -> None:
    """执行Momentum Rotation换仓逻辑。"""
    if verbose:
        console.print(f"\n[bold blue]{ds} === Momentum Rotation ===[/bold blue]")

    # 1. 计算所有Universe标的的RS得分
    bench = data.get(BENCHMARK)
    rankings: list[tuple[str, float]] = []
    for ticker in ASTOCK_UNIVERSE:
        if ticker not in data or ticker not in prices:
            continue
        tdata = data[ticker]

        # 流动性过滤
        if not check_liquidity(tdata, date):
            continue

        # 崩盘过滤（过去5日跌>15%）
        if check_crash_filter(tdata, date):
            if verbose:
                console.print(f"  [dim]排除 {ticker}：崩盘过滤[/dim]")
            continue

        # 计算RS（收益率/波动率）
        rs = calc_rs(tdata, bench, date)
        if rs == -999.0:
            continue

        rankings.append((ticker, rs))

    rankings.sort(key=lambda x: x[1], reverse=True)
    top_n = [t for t, _ in rankings[:MOM_TOP_N]]
    top_set = set(top_n)

    if verbose:
        console.print(f"  RS前7: {top_n}")

    # 2. 卖出不在Top7的Momentum持仓
    for ticker in list(pf.positions):
        pos = pf.positions[ticker]
        if pos.signal not in ("MOM", "REBAL"):
            continue
        if ticker not in top_set:
            ok, reason = pf.can_sell(ticker, day_count)
            if not ok:
                if verbose:
                    console.print(f"  [dim]{ticker} RS出榜但 {reason}，推迟卖出[/dim]")
                continue
            # 检查跌停
            if ticker in data and is_limit_down(data[ticker], date, ticker):
                if verbose:
                    console.print(f"  [dim]{ticker} 跌停，无法卖出[/dim]")
                continue
            price = prices.get(ticker)
            if price:
                t = pf.sell(ticker, price, ds, day_count, "Rotation: RS out of top7")
                if t and verbose:
                    console.print(f"  [yellow]换出 {ticker} ¥{t.realized_pnl:+,.0f} ({t.realized_pnl_pct:+.1%})[/yellow]")

    # 3. 买入Top7中未持有的
    for ticker in top_n:
        if ticker in pf.positions:
            continue
        price = prices.get(ticker)
        if price is None:
            continue

        # 涨停无法买入
        if ticker in data and is_limit_up(data[ticker], date, ticker):
            if verbose:
                console.print(f"  [dim]{ticker} 涨停，无法买入[/dim]")
            continue

        ok, reason = pf.can_buy_more(ticker, prices, MAX_POS_PCT, breath)
        if not ok:
            if verbose:
                console.print(f"  [dim]跳过 {ticker}：{reason}[/dim]")
            continue

        atr = calc_atr(data[ticker], date) if ticker in data else 0.0
        trade = pf.buy(
            ticker=ticker, price=price, date=ds, day_idx=day_count,
            signal="MOM", size_pct=MAX_POS_PCT,
            atr=atr, breath_multiplier=breath_multiplier,
        )
        if trade and verbose:
            rs_val = next((r for t, r in rankings if t == ticker), 0)
            console.print(f"  [cyan]买入 {ticker} {trade.shares}股 @¥{trade.price:.2f} "
                          f"(RS={rs_val:.3f}, 止损=¥{pf.positions.get(ticker, type('', (), {'stop_price': 0})).stop_price:.2f})[/cyan]")


def _run_dip_buy_scan(pf: AStockPortfolio,
                      data: dict[str, pd.DataFrame],
                      prices: dict[str, float],
                      ds: str, date: pd.Timestamp, day_count: int,
                      breath_multiplier: float,
                      verbose: bool) -> None:
    """每周五Dip Buy扫描：过去20日跌>15%的标的。"""
    if verbose:
        console.print(f"\n[magenta]{ds} === Dip Buy Scan ===[/magenta]")

    # 呼气时不做Dip Buy（市场弱势不抄底）
    if breath_multiplier < 0.6:
        if verbose:
            console.print(f"  [dim]市场呼气，跳过Dip Buy[/dim]")
        return

    for ticker in ASTOCK_UNIVERSE:
        if ticker in pf.positions:
            continue
        if ticker not in data or ticker not in prices:
            continue

        tdata = data[ticker]
        mask = tdata.index <= date
        closes = tdata.loc[mask, "Close"]
        if len(closes) < DIP_LOOKBACK + 1:
            continue

        ret_20d = float(closes.iloc[-1] / closes.iloc[-DIP_LOOKBACK - 1] - 1)
        if ret_20d > DIP_THRESHOLD:
            continue

        # 流动性检查
        if not check_liquidity(tdata, date):
            continue

        price = prices[ticker]

        # 涨停无法买入
        if is_limit_up(tdata, date, ticker):
            continue

        ok, reason = pf.can_buy_more(ticker, prices, DIP_SIZE_PCT, "NEUTRAL")
        if not ok:
            if verbose:
                console.print(f"  [dim]Dip跳过 {ticker}：{reason}[/dim]")
            continue

        atr = calc_atr(tdata, date)
        trade = pf.buy(
            ticker=ticker, price=price, date=ds, day_idx=day_count,
            signal="DIP", size_pct=DIP_SIZE_PCT,
            atr=atr, breath_multiplier=1.0,  # Dip仓位不受呼吸缩放
            dip_stop_pct=DIP_STOP_PCT,
            dip_target_pct=DIP_TARGET_PCT,
        )
        if trade and verbose:
            console.print(f"  [magenta]Dip买入 {ticker} {trade.shares}股 @¥{trade.price:.2f} "
                          f"(20日跌幅={ret_20d:.1%})[/magenta]")


# ══════════════════════════════════════════════════════════════════════════════
# 绩效分析
# ══════════════════════════════════════════════════════════════════════════════

def analyze(pf: AStockPortfolio, data: dict[str, pd.DataFrame],
            start: str, end: str, tag: str) -> dict:
    trades = pf.trades
    closed = [t for t in trades if t.action in ("SELL", "PARTIAL_SELL")]

    if not closed:
        console.print("[yellow]没有已平仓交易[/yellow]")
        return {"error": "no_closed_trades"}

    wins = [t for t in closed if t.realized_pnl > 0]
    losses = [t for t in closed if t.realized_pnl <= 0]
    total_pnl = sum(t.realized_pnl for t in closed)
    win_rate = len(wins) / len(closed) * 100
    avg_win = float(np.mean([t.realized_pnl for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.realized_pnl for t in losses])) if losses else 0.0
    gross_profit = sum(t.realized_pnl for t in wins)
    gross_loss = abs(sum(t.realized_pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    navs = [n for _, n, _, _ in pf.daily_navs]
    final_nav = navs[-1] if navs else INITIAL_CAPITAL
    total_ret = (final_nav / INITIAL_CAPITAL - 1) * 100

    # Benchmark收益
    bench_data = data.get(BENCHMARK)
    bench_ret = 0.0
    if bench_data is not None:
        start_dt, end_dt = pd.Timestamp(start), pd.Timestamp(end)
        b_slice = bench_data.loc[(bench_data.index >= start_dt) & (bench_data.index <= end_dt), "Close"]
        if len(b_slice) >= 2:
            bench_ret = float(b_slice.iloc[-1] / b_slice.iloc[0] - 1) * 100

    # 最大回撤
    peak = navs[0] if navs else INITIAL_CAPITAL
    max_dd, max_dd_date = 0.0, ""
    for ds, n, _, _ in pf.daily_navs:
        if n > peak:
            peak = n
        dd = (n - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
            max_dd_date = ds

    # Sharpe（年化，无风险利率2.5%/年）
    daily_rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    rf_daily = 0.025 / 252
    sharpe = 0.0
    if len(daily_rets) > 1 and np.std(daily_rets) > 0:
        sharpe = (np.mean(daily_rets) - rf_daily) / np.std(daily_rets) * np.sqrt(252)

    # Calmar
    calmar = total_ret / abs(max_dd) if max_dd != 0 else float("inf")

    # 按信号分类统计
    sig_stats: dict[str, dict] = {}
    for t in closed:
        sig = t.signal.split("(")[0]
        if sig not in sig_stats:
            sig_stats[sig] = {"n": 0, "wins": 0, "pnl": 0.0}
        sig_stats[sig]["n"] += 1
        sig_stats[sig]["pnl"] += t.realized_pnl
        if t.realized_pnl > 0:
            sig_stats[sig]["wins"] += 1
    for s in sig_stats.values():
        s["wr"] = s["wins"] / s["n"] * 100 if s["n"] > 0 else 0.0

    # 月度收益
    monthly: dict[str, dict] = {}
    for i in range(1, len(pf.daily_navs)):
        m = pf.daily_navs[i][0][:7]
        if m not in monthly:
            monthly[m] = {"start": pf.daily_navs[i - 1][1]}
        monthly[m]["end"] = pf.daily_navs[i][1]
    for m in monthly:
        monthly[m]["ret"] = (monthly[m]["end"] / monthly[m]["start"] - 1) * 100

    # 市场呼吸状态分布
    breath_counts: dict[str, int] = {}
    for _, _, breath, _ in pf.daily_navs:
        breath_counts[breath] = breath_counts.get(breath, 0) + 1

    results = {
        "period": tag,
        "strategy": "A股 Momentum Rotation + Dip Buy V1",
        "universe_size": len(ASTOCK_UNIVERSE),
        "initial_capital": INITIAL_CAPITAL,
        "final_nav": round(final_nav, 2),
        "total_return_pct": round(total_ret, 2),
        "benchmark_return_pct": round(bench_ret, 2),
        "alpha_pct": round(total_ret - bench_ret, 2),
        "realized_pnl": round(total_pnl, 2),
        "sharpe": round(float(sharpe), 3),
        "calmar": round(float(calmar), 3),
        "max_dd_pct": round(max_dd, 2),
        "max_dd_date": max_dd_date,
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(float(profit_factor), 3),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "by_signal": sig_stats,
        "market_breath_distribution": breath_counts,
        "monthly_returns": {m: round(v["ret"], 2) for m, v in sorted(monthly.items())},
    }

    # ── 打印汇总 ──
    console.print(f"\n{'='*70}")
    console.print(Panel.fit(
        f"[bold]A股回测结果 — {tag}[/bold]",
        box=box.DOUBLE_EDGE
    ))

    tbl = Table(box=box.SIMPLE, show_header=False, min_width=55)
    tbl.add_column("", style="bold")
    tbl.add_column("", justify="right")

    ret_c = "green" if total_ret > 0 else "red"
    alpha_c = "green" if results["alpha_pct"] > 0 else "red"
    dd_c = "red"

    tbl.add_row("最终净值", f"¥{final_nav:,.0f}")
    tbl.add_row("总收益", f"[{ret_c}]{total_ret:+.2f}%[/{ret_c}]")
    tbl.add_row("沪深300", f"{bench_ret:+.2f}%")
    tbl.add_row("超额收益(Alpha)", f"[{alpha_c}]{results['alpha_pct']:+.2f}%[/{alpha_c}]")
    tbl.add_row("已实现P&L", f"¥{total_pnl:+,.0f}")
    tbl.add_row("Sharpe", f"{sharpe:.3f}")
    tbl.add_row("Calmar", f"{calmar:.3f}")
    tbl.add_row("最大回撤", f"[{dd_c}]{max_dd:.2f}%[/{dd_c}] ({max_dd_date})")
    tbl.add_row("", "")
    tbl.add_row("总交易次数", f"{len(trades)} (平仓: {len(closed)})")
    tbl.add_row("胜率", f"{win_rate:.1f}%")
    tbl.add_row("平均盈利", f"¥{avg_win:+,.0f}")
    tbl.add_row("平均亏损", f"¥{avg_loss:+,.0f}")
    tbl.add_row("Profit Factor", f"{profit_factor:.3f}")
    console.print(tbl)

    console.print("\n[bold]按策略分类:[/bold]")
    st = Table(box=box.SIMPLE_HEAVY)
    st.add_column("策略")
    st.add_column("交易数", justify="right")
    st.add_column("胜率", justify="right")
    st.add_column("P&L", justify="right")
    for sig in sorted(sig_stats):
        s = sig_stats[sig]
        pc = "green" if s["pnl"] > 0 else "red"
        st.add_row(sig, str(s["n"]), f"{s['wr']:.0f}%",
                   f"[{pc}]¥{s['pnl']:+,.0f}[/{pc}]")
    console.print(st)

    console.print("\n[bold]市场呼吸分布:[/bold]")
    total_days = sum(breath_counts.values())
    for state, cnt in sorted(breath_counts.items()):
        pct = cnt / total_days * 100 if total_days > 0 else 0
        console.print(f"  {state:<15} {cnt:>4}天 ({pct:.1f}%)")

    console.print("\n[bold]月度收益:[/bold]")
    for m, r in sorted(results["monthly_returns"].items()):
        c = "green" if r > 0 else "red"
        bar = "█" * int(abs(r) * 1.5)
        console.print(f"  {m}: [{c}]{r:>+7.2f}% {bar}[/{c}]")

    # ── 保存结果 ──
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stats_path = RESULTS_DIR / f"astock_v1_{tag}_stats.json"
    trades_path = RESULTS_DIR / f"astock_v1_{tag}_trades.json"

    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str, ensure_ascii=False)
    with open(trades_path, "w", encoding="utf-8") as f:
        json.dump([asdict(t) for t in pf.trades], f, indent=2,
                  default=str, ensure_ascii=False)

    console.print(f"\n[green]结果已保存:[/green]")
    console.print(f"  统计: {stats_path}")
    console.print(f"  交易: {trades_path}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="A股交易系统 V1 回测引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--period", default="2025",
        choices=["2024", "2025", "2026"],
        help="回测周期（默认2025全年）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细输出每笔交易",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="强制重新下载数据",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # 时间范围
    period_map = {
        "2024": ("2024-01-02", "2024-12-31", "2024"),
        "2025": ("2025-01-02", "2025-12-31", "2025"),
        "2026": ("2026-01-02", "2026-05-27", "2026_ytd"),
    }
    start, end, tag = period_map[args.period]

    # 下载数据
    data = download_data(
        ALL_SYMBOLS, start, end, tag,
        force_refresh=args.no_cache,
    )

    # 检查基准数据
    if BENCHMARK not in data:
        console.print(f"[red]基准数据缺失 ({BENCHMARK})，无法继续[/red]")
        sys.exit(1)

    # 过滤universe（仅保留有数据的）
    available = [t for t in ASTOCK_UNIVERSE if t in data]
    console.print(f"[dim]有效Universe: {len(available)}/{len(ASTOCK_UNIVERSE)} 只[/dim]")
    if len(available) < 5:
        console.print("[red]可用标的不足5只，退出[/red]")
        sys.exit(1)

    # 执行回测
    pf = run_backtest(data, start, end, verbose=args.verbose)

    # 分析结果
    analyze(pf, data, start, end, tag)


if __name__ == "__main__":
    main()
