# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.24"]
# ///
"""
风险指标计算引擎 — Claude模拟盘
读取 portfolio_state.json 的 daily_snapshots，计算完整风险指标。

计算指标:
  - VaR 95%/99%（参数法 + 历史法）
  - CVaR 95%（Expected Shortfall）
  - Rolling Sharpe Ratio（无风险利率: US 10Y ~4.5%）
  - Sortino Ratio（只惩罚下行波动）
  - Calmar Ratio（年化收益/最大回撤）
  - Max Drawdown + Current Drawdown
  - Beta to SPY
  - Information Ratio（超额收益/跟踪误差）

数据质量分级:
  - sufficient: ≥ 60 天
  - marginal:   20-59 天
  - insufficient: < 20 天（输出警告，仍计算有意义的指标）

用法:
  uv run --script scripts/risk_metrics.py
  uv run --script scripts/risk_metrics.py --output risk.json
  uv run --script scripts/risk_metrics.py --verbose
  python3 scripts/risk_metrics.py           # 从 sim-portfolio/ 目录运行
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio_state.json"

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────
RISK_FREE_ANNUAL = 0.045        # US 10Y 约 4.5%（2025-2026 区间）
TRADING_DAYS_PER_YEAR = 252
MIN_REQUIRED = 20               # 低于此值标注 insufficient
MARGINAL_THRESHOLD = 60         # 低于此值标注 marginal


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def annualize_return(daily_mean: float) -> float:
    """复利年化：(1 + daily_mean)^252 - 1"""
    return (1 + daily_mean) ** TRADING_DAYS_PER_YEAR - 1


def annualize_vol(daily_std: float) -> float:
    """年化波动率：daily_std * sqrt(252)"""
    return daily_std * math.sqrt(TRADING_DAYS_PER_YEAR)


def data_quality(n: int) -> str:
    if n >= MARGINAL_THRESHOLD:
        return "sufficient"
    elif n >= MIN_REQUIRED:
        return "marginal"
    else:
        return "insufficient"


def safe_divide(num: float, denom: float, fallback=None):
    if denom == 0 or (denom != denom):  # denom == 0 or NaN
        return fallback
    return num / denom


# ──────────────────────────────────────────────────────────────────────────────
# 核心计算
# ──────────────────────────────────────────────────────────────────────────────

def compute_var_parametric(returns: np.ndarray, confidence: float) -> float:
    """参数法 VaR（假设正态分布）。返回损失百分比（负值）。"""
    # z-score for one-tailed confidence level
    z_map = {0.95: 1.6449, 0.99: 2.3263}
    z = z_map.get(confidence, 1.6449)
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    return mu - z * sigma  # negative = loss


def compute_var_historical(returns: np.ndarray, confidence: float) -> float:
    """历史模拟法 VaR。返回损失百分比（负值）。"""
    return float(np.percentile(returns, (1 - confidence) * 100))


def compute_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    """CVaR / Expected Shortfall：VaR 以外尾部平均损失。"""
    cutoff = compute_var_historical(returns, confidence)
    tail = returns[returns <= cutoff]
    if len(tail) == 0:
        return cutoff
    return float(np.mean(tail))


def compute_max_drawdown(navs: np.ndarray) -> tuple[float, float]:
    """
    最大回撤 & 当前回撤（相对历史高点）。
    返回 (max_drawdown_pct, current_drawdown_pct)，均为负值或 0。
    """
    peak = np.maximum.accumulate(navs)
    drawdowns = (navs - peak) / peak * 100
    max_dd = float(np.min(drawdowns))
    current_dd = float(drawdowns[-1])
    return max_dd, current_dd


def compute_sharpe(returns: np.ndarray) -> float:
    """年化 Sharpe Ratio，无风险利率用 RISK_FREE_ANNUAL。"""
    rf_daily = (1 + RISK_FREE_ANNUAL) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - rf_daily
    mu_excess = float(np.mean(excess))
    sigma = float(np.std(returns, ddof=1))
    return safe_divide(
        mu_excess * TRADING_DAYS_PER_YEAR,
        sigma * math.sqrt(TRADING_DAYS_PER_YEAR),
        fallback=None
    )


def compute_sortino(returns: np.ndarray) -> Optional[float]:
    """Sortino Ratio：只惩罚下行波动（年化）。"""
    rf_daily = (1 + RISK_FREE_ANNUAL) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess = returns - rf_daily
    downside = excess[excess < 0]
    if len(downside) == 0:
        # 没有负超额收益 → 下行风险为 0 → Sortino = +inf（标注）
        return None  # 用 None 表示"完美"，不输出 inf
    downside_std = float(np.std(downside, ddof=1 if len(downside) > 1 else 0))
    downside_annual = downside_std * math.sqrt(TRADING_DAYS_PER_YEAR)
    annual_excess = float(np.mean(excess)) * TRADING_DAYS_PER_YEAR
    return safe_divide(annual_excess, downside_annual)


def compute_calmar(returns: np.ndarray, navs: np.ndarray) -> Optional[float]:
    """Calmar = 年化收益 / |最大回撤|。"""
    max_dd, _ = compute_max_drawdown(navs)
    if max_dd == 0:
        return None  # 无回撤，不计算
    annual_ret = annualize_return(float(np.mean(returns))) * 100  # in %
    return safe_divide(annual_ret, abs(max_dd))


def compute_beta(portfolio_returns: np.ndarray,
                 benchmark_returns: np.ndarray) -> Optional[float]:
    """
    Beta = Cov(port, bench) / Var(bench)。
    要求同等长度的配对数组（已过滤掉 NaN）。
    """
    if len(portfolio_returns) < 2 or len(benchmark_returns) < 2:
        return None
    cov_matrix = np.cov(portfolio_returns, benchmark_returns)
    var_bench = cov_matrix[1, 1]
    cov = cov_matrix[0, 1]
    return safe_divide(float(cov), float(var_bench))


def compute_information_ratio(portfolio_returns: np.ndarray,
                              benchmark_returns: np.ndarray) -> Optional[float]:
    """
    IR = 年化超额收益 / 年化跟踪误差。
    超额收益 = 组合日收益 - 基准日收益。
    """
    active = portfolio_returns - benchmark_returns
    mean_active = float(np.mean(active))
    te = float(np.std(active, ddof=1))
    if te == 0:
        return None
    return safe_divide(mean_active * TRADING_DAYS_PER_YEAR,
                       te * math.sqrt(TRADING_DAYS_PER_YEAR))


# ──────────────────────────────────────────────────────────────────────────────
# 数据提取
# ──────────────────────────────────────────────────────────────────────────────

def load_snapshots(verbose: bool = False) -> list[dict]:
    """读取并验证 daily_snapshots。"""
    if not PORTFOLIO_PATH.exists():
        print(f"[ERROR] portfolio_state.json not found at {PORTFOLIO_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        state = json.load(f)

    snapshots = state.get("performance", {}).get("daily_snapshots", [])
    if verbose:
        print(f"[INFO] Loaded {len(snapshots)} daily snapshots from {PORTFOLIO_PATH}")
    return snapshots


def extract_series(snapshots: list[dict], verbose: bool = False) -> dict:
    """
    从 snapshots 提取各时间序列（过滤掉 null 值）。
    返回字典，key 为序列名，value 为 numpy array。

    重要：portfolio/benchmark 配对序列（用于 Beta/IR）按日期对齐，
    不能简单地各自过滤后取尾部切片（不同日期的 null 会导致错位）。
    """
    us_navs, us_rets, a_navs, a_rets = [], [], [], []

    # 配对序列：只保留同日期两个字段都有值的行
    us_spy_paired: list[tuple[float, float]] = []   # (us_ret, spy_ret)
    a_sse_paired:  list[tuple[float, float]] = []   # (a_ret,  sse_ret)

    # 单列序列（NAV/return）：各自独立过滤
    for snap in snapshots:
        # 美股 NAV + 收益率
        us_nav = snap.get("us_nav")
        us_ret = snap.get("us_return_pct")
        if us_nav is not None and us_ret is not None:
            us_navs.append(us_nav)
            us_rets.append(us_ret / 100.0)

        # A股 NAV + 收益率
        a_nav = snap.get("a_share_nav")
        a_ret = snap.get("a_share_return_pct")
        if a_nav is not None and a_ret is not None:
            a_navs.append(a_nav)
            a_rets.append(a_ret / 100.0)

        # 配对：美股 vs SPY（同一天必须两者都有）
        spy_ret = snap.get("spy_return_pct")
        if us_ret is not None and spy_ret is not None:
            us_spy_paired.append((us_ret / 100.0, spy_ret / 100.0))

        # 配对：A股 vs SSE（同一天必须两者都有）
        sse_ret = snap.get("sse_return_pct")
        if a_ret is not None and sse_ret is not None:
            a_sse_paired.append((a_ret / 100.0, sse_ret / 100.0))

    # 解包配对序列
    if us_spy_paired:
        us_spy_port  = np.array([x[0] for x in us_spy_paired], dtype=float)
        us_spy_bench = np.array([x[1] for x in us_spy_paired], dtype=float)
    else:
        us_spy_port  = np.array([], dtype=float)
        us_spy_bench = np.array([], dtype=float)

    if a_sse_paired:
        a_sse_port  = np.array([x[0] for x in a_sse_paired], dtype=float)
        a_sse_bench = np.array([x[1] for x in a_sse_paired], dtype=float)
    else:
        a_sse_port  = np.array([], dtype=float)
        a_sse_bench = np.array([], dtype=float)

    if verbose:
        print(f"[INFO] US returns: {len(us_rets)} pts, "
              f"US/SPY paired: {len(us_spy_paired)} pts, "
              f"A-share returns: {len(a_rets)} pts, "
              f"A/SSE paired: {len(a_sse_paired)} pts")

    return {
        "us_navs":       np.array(us_navs, dtype=float),
        "us_rets":       np.array(us_rets, dtype=float),
        "a_navs":        np.array(a_navs,  dtype=float),
        "a_rets":        np.array(a_rets,  dtype=float),
        # Date-aligned paired series for Beta / IR
        "us_spy_port":   us_spy_port,
        "us_spy_bench":  us_spy_bench,
        "a_sse_port":    a_sse_port,
        "a_sse_bench":   a_sse_bench,
        # Legacy keys kept for backward compat (may be misaligned if dates differ)
        "spy_rets":      us_spy_bench,
        "sse_rets":      a_sse_bench,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 指标计算入口
# ──────────────────────────────────────────────────────────────────────────────

def compute_metrics_for(
    navs: np.ndarray,
    returns: np.ndarray,
    bench_returns: np.ndarray,
    label: str,
    verbose: bool = False,
    port_paired: Optional[np.ndarray] = None,
    bench_paired: Optional[np.ndarray] = None,
) -> dict:
    """
    计算单一账户（US 或 A股）的全套风险指标。

    bench_returns: 旧接口兼容，用于无配对数据时。
    port_paired / bench_paired: 日期对齐的配对收益率数组（Beta/IR 专用）。
                                 优先使用这两个参数计算 Beta 和 IR。
    """
    n = len(returns)
    quality = data_quality(n)

    if verbose:
        print(f"\n[{label}] n={n} ({quality})")
        if n > 0:
            print(f"  Returns: {[f'{r*100:.2f}%' for r in returns]}")
        if len(navs) > 0:
            print(f"  NAVs: {navs.tolist()}")

    result: dict = {
        "data_quality": quality,
        "n_obs": n,
    }

    # ── VaR / CVaR（最少 2 个数据点）──────────────────────────────────────────
    if n >= 2:
        var_95_hist = compute_var_historical(returns, 0.95)
        var_99_hist = compute_var_historical(returns, 0.99)
        var_95_param = compute_var_parametric(returns, 0.95)
        var_99_param = compute_var_parametric(returns, 0.99)
        cvar_95 = compute_cvar(returns, 0.95)

        result.update({
            "var_95_pct_hist": round(var_95_hist * 100, 4),
            "var_99_pct_hist": round(var_99_hist * 100, 4),
            "var_95_pct_param": round(var_95_param * 100, 4),
            "var_99_pct_param": round(var_99_param * 100, 4),
            "cvar_95_pct": round(cvar_95 * 100, 4),
        })

        if verbose:
            print(f"  VaR 95% hist={var_95_hist*100:.3f}%  param={var_95_param*100:.3f}%")
            print(f"  VaR 99% hist={var_99_hist*100:.3f}%  param={var_99_param*100:.3f}%")
            print(f"  CVaR 95%: {cvar_95*100:.3f}%")
    else:
        result.update({
            "var_95_pct_hist": None,
            "var_99_pct_hist": None,
            "var_95_pct_param": None,
            "var_99_pct_param": None,
            "cvar_95_pct": None,
            "_note_var": "insufficient data (<2 pts)",
        })

    # ── Sharpe / Sortino（最少 2 个数据点）────────────────────────────────────
    if n >= 2:
        sharpe = compute_sharpe(returns)
        sortino = compute_sortino(returns)

        result["sharpe_ratio"] = round(sharpe, 4) if sharpe is not None else None
        result["sortino_ratio"] = round(sortino, 4) if sortino is not None else "N/A (no negative excess returns)"

        if verbose:
            print(f"  Sharpe: {sharpe}")
            print(f"  Sortino: {sortino}")
    else:
        result["sharpe_ratio"] = None
        result["sortino_ratio"] = None
        result["_note_ratios"] = "insufficient data (<2 pts)"

    # ── Max Drawdown / Current Drawdown（最少 2 个 NAV 点）───────────────────
    if len(navs) >= 2:
        max_dd, cur_dd = compute_max_drawdown(navs)
        result["max_drawdown_pct"] = round(max_dd, 4)
        result["current_drawdown_pct"] = round(cur_dd, 4)

        if verbose:
            print(f"  Max Drawdown: {max_dd:.3f}%  Current: {cur_dd:.3f}%")
    else:
        result["max_drawdown_pct"] = None
        result["current_drawdown_pct"] = None
        result["_note_drawdown"] = "insufficient NAV data"

    # ── Calmar（最少 2 个数据点 + 有回撤）───────────────────────────────────
    if n >= 2 and len(navs) >= 2:
        calmar = compute_calmar(returns, navs)
        result["calmar_ratio"] = round(calmar, 4) if calmar is not None else "N/A (no drawdown)"

        if verbose:
            print(f"  Calmar: {calmar}")
    else:
        result["calmar_ratio"] = None
        result["_note_calmar"] = "insufficient data"

    # ── Beta to benchmark（需要日期对齐的配对数据）──────────────────────────
    # 优先使用日期对齐的 port_paired/bench_paired；
    # 如果未提供，回退到旧的尾部切片（可能不对齐，仅作兼容保留）。
    if port_paired is not None and bench_paired is not None:
        _port_r  = port_paired
        _bench_r = bench_paired
        n_paired = len(_port_r)
        _paired_note = "date-aligned pairs"
    else:
        # Legacy fallback — tail-slice may be misaligned when null dates differ
        n_paired = min(len(returns), len(bench_returns))
        _port_r  = returns[-n_paired:]      if n_paired > 0 else np.array([])
        _bench_r = bench_returns[-n_paired:] if n_paired > 0 else np.array([])
        _paired_note = "tail-slice (may be misaligned)"

    if n_paired >= 2:
        port_r  = _port_r
        bench_r = _bench_r
        beta = compute_beta(port_r, bench_r)
        result["beta_to_benchmark"] = round(beta, 4) if beta is not None else None

        if verbose:
            print(f"  Beta (n={n_paired} paired, {_paired_note}): {beta}")
    else:
        port_r  = np.array([])
        bench_r = np.array([])
        result["beta_to_benchmark"] = None
        result["_note_beta"] = f"insufficient paired data (need ≥2, got {n_paired})"

    # ── Information Ratio（需要配对数据）──────────────────────────────────────
    if n_paired >= 2:
        ir = compute_information_ratio(port_r, bench_r)
        result["information_ratio"] = round(ir, 4) if ir is not None else None

        if verbose:
            print(f"  Information Ratio: {ir}")
    else:
        result["information_ratio"] = None
        result["_note_ir"] = f"insufficient paired data (need ≥2, got {n_paired})"

    # ── 汇总统计（辅助信息）──────────────────────────────────────────────────
    if n >= 1:
        annualized_ret = annualize_return(float(np.mean(returns))) * 100
        annualized_vol_pct = annualize_vol(float(np.std(returns, ddof=1 if n > 1 else 0))) * 100 if n >= 2 else None
        result["annualized_return_pct"] = round(annualized_ret, 4)
        result["annualized_vol_pct"] = round(annualized_vol_pct, 4) if annualized_vol_pct is not None else None
        result["total_return_pct"] = round(float(np.prod(1 + returns) - 1) * 100, 4)
        result["daily_return_mean_pct"] = round(float(np.mean(returns)) * 100, 4)
        result["daily_return_std_pct"] = round(float(np.std(returns, ddof=1 if n > 1 else 0)) * 100, 4) if n >= 2 else None

    return result


# ──────────────────────────────────────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="风险指标计算引擎 — Claude模拟盘"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出 JSON 文件路径（默认: stdout）"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示详细计算过程"
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help="覆盖 portfolio_state.json 路径（默认: 项目根目录）"
    )
    args = parser.parse_args()

    # 允许覆盖路径（测试用）
    global PORTFOLIO_PATH
    if args.state:
        PORTFOLIO_PATH = Path(args.state).resolve()

    # ── 加载数据 ──────────────────────────────────────────────────────────────
    snapshots = load_snapshots(verbose=args.verbose)
    series = extract_series(snapshots, verbose=args.verbose)

    n_us = len(series["us_rets"])
    n_a = len(series["a_rets"])
    total_snapshots = len(snapshots)

    # ── 警告 ──────────────────────────────────────────────────────────────────
    warnings = []
    if total_snapshots < MIN_REQUIRED:
        msg = (f"WARNING: Only {total_snapshots} daily snapshots available. "
               f"Most risk metrics require ≥{MIN_REQUIRED} data points for statistical reliability. "
               f"Results shown are mathematically valid but not yet statistically robust.")
        warnings.append(msg)
        print(f"\n{'='*70}", file=sys.stderr)
        print(msg, file=sys.stderr)
        print(f"{'='*70}\n", file=sys.stderr)

    # ── 计算指标 ──────────────────────────────────────────────────────────────
    if args.verbose:
        print("\n" + "="*70)
        print("COMPUTING US PORTFOLIO METRICS")
        print("="*70)

    us_metrics = compute_metrics_for(
        navs=series["us_navs"],
        returns=series["us_rets"],
        bench_returns=series["spy_rets"],    # legacy compat
        port_paired=series["us_spy_port"],  # date-aligned for Beta/IR
        bench_paired=series["us_spy_bench"],
        label="US",
        verbose=args.verbose,
    )

    if args.verbose:
        print("\n" + "="*70)
        print("COMPUTING A-SHARE PORTFOLIO METRICS")
        print("="*70)

    a_metrics = compute_metrics_for(
        navs=series["a_navs"],
        returns=series["a_rets"],
        bench_returns=series["sse_rets"],   # legacy compat
        port_paired=series["a_sse_port"],  # date-aligned for Beta/IR
        bench_paired=series["a_sse_bench"],
        label="A-Share",
        verbose=args.verbose,
    )

    # ── 组装输出 ──────────────────────────────────────────────────────────────
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_points": total_snapshots,
        "minimum_required": MIN_REQUIRED,
        "marginal_threshold": MARGINAL_THRESHOLD,
        "risk_free_rate_annual_pct": RISK_FREE_ANNUAL * 100,
        "benchmark": {
            "us": "SPY",
            "a_share": "SSE Composite"
        },
        "warnings": warnings,
        "us": {
            "currency": "USD",
            "benchmark": "SPY",
            **us_metrics,
        },
        "a_share": {
            "currency": "CNY",
            "benchmark": "SSE Composite",
            **a_metrics,
        },
        "_methodology": {
            "var_parametric": "Assumes normal distribution. z=1.6449 for 95%, z=2.3263 for 99%.",
            "var_historical": "Non-parametric empirical percentile of observed daily returns.",
            "cvar": "Mean of returns below historical VaR cutoff (Expected Shortfall).",
            "sharpe": "Annualized: (E[r]-rf_daily)*252 / (std(r)*sqrt(252)). rf=US 10Y ~4.5%.",
            "sortino": "Annualized excess return / annualized downside deviation (negative excess returns only).",
            "calmar": "Annualized return (%) / |Max Drawdown (%)|.",
            "max_drawdown": "Peak-to-trough as % of peak NAV across entire observed history.",
            "beta": "OLS covariance estimate: Cov(port,bench) / Var(bench).",
            "information_ratio": "Annualized active return / annualized tracking error.",
        }
    }

    # ── 输出 ──────────────────────────────────────────────────────────────────
    json_str = json.dumps(output, indent=2, ensure_ascii=False)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        print(f"[OK] Risk metrics written to {out_path.resolve()}")
    else:
        print(json_str)

    # 退出码：数据不足时返回 2（警告级，非错误）
    if total_snapshots < MIN_REQUIRED:
        sys.exit(2)


if __name__ == "__main__":
    main()
