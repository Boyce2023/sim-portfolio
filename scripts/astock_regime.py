#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.14", "pandas>=2.0"]
# ///
"""
astock_regime.py — A股专属5信号Regime检测

strategy_astock.md §8 的5信号实现:
  1. 全市场成交量 vs 20日均  (sh000001 volume proxy)
  2. 中证1000 vs 沪深300 月涨幅差
  3. 北向资金方向 (CSRC Aug-2024起停披露详细数据，跳过/标注)
  4. 两融余额 月环比 (SSE+SZSE margin balance)
  5. CSI300 vs 20周均线

规则:
  牛市 (BULL)   : ≥ 3个信号积极
  震荡 (NEUTRAL): 2个信号积极 (strategy文档叫"中性")
  熊市 (BEAR)   : ≤ 1个信号积极

输出:
  - 打印当前Regime + 各信号评分
  - 写入 ~/.claude/nexus/truth/macro/astock_regime.json

用法:
  uv run --script scripts/astock_regime.py
  uv run --script scripts/astock_regime.py --quiet   # 只打印Regime结论
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import pandas as pd
    import akshare as ak
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}", file=sys.stderr)
    sys.exit(1)

BJT = timezone(timedelta(hours=8))
NOW = datetime.now(BJT)
TODAY_STR = NOW.strftime("%Y-%m-%d")

NEXUS_DIR = Path.home() / ".claude" / "nexus"
OUTPUT_PATH = NEXUS_DIR / "truth" / "macro" / "astock_regime.json"


# ─── Helpers ────────────────────────────────────────────────────────────────

def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)


def pct_change(new_val: float, old_val: float) -> float | None:
    """Return percentage change, or None if old_val is zero."""
    if old_val == 0:
        return None
    return (new_val - old_val) / abs(old_val) * 100


# ─── Signal 1: 全市场成交量 vs 20日均 ───────────────────────────────────────
# Uses sh000001 (SSE Composite) volume as A-share total market proxy.
# The 20d MA comparison is direction-valid regardless of share-count vs yuan.

def signal_volume_vs_20dma() -> tuple[int, str, dict]:
    """
    Returns:
        score: +1 (bull) / 0 (neutral) / -1 (bear)
        note: human-readable description
        raw: raw data dict for audit
    """
    try:
        df = ak.stock_zh_index_daily(symbol="sh000001")
        df = df.sort_values("date").tail(60).reset_index(drop=True)

        if len(df) < 21:
            return 0, "数据不足(< 21天)", {"error": "insufficient_data"}

        vol_series = df["volume"].astype(float)
        latest_vol = float(vol_series.iloc[-1])
        ma20 = float(vol_series.iloc[-21:-1].mean())  # 前20日均量

        pct = pct_change(latest_vol, ma20)
        if pct is None:
            return 0, "均量为0，跳过", {"error": "zero_ma"}

        if pct > 30:
            score, label = +1, "bull"
        elif pct < -30:
            score, label = -1, "bear"
        else:
            score, label = 0, "neutral"

        note = f"今日量={latest_vol/1e8:.0f}亿 vs 20日均={ma20/1e8:.0f}亿 ({pct:+.1f}%) → {label}"
        raw = {
            "latest_volume": round(latest_vol, 0),
            "ma20_volume": round(ma20, 0),
            "pct_vs_ma20": round(pct, 2),
            "proxy": "sh000001 share volume",
        }
        return score, note, raw

    except Exception as e:
        return 0, f"获取失败: {e}", {"error": str(e)}


# ─── Signal 2: 中证1000 vs 沪深300 月涨幅差 ─────────────────────────────────
# CSI1000 outperform = small-cap leading = risk-on (bull)
# CSI300 outperform  = large-cap defensive = risk-off (bear)

def signal_csi1000_vs_csi300() -> tuple[int, str, dict]:
    try:
        df_300 = ak.stock_zh_index_daily(symbol="sh000300").sort_values("date").tail(35)
        df_1000 = ak.stock_zh_index_daily(symbol="sh000852").sort_values("date").tail(35)

        if len(df_300) < 22 or len(df_1000) < 22:
            return 0, "数据不足(< 22天)", {"error": "insufficient_data"}

        # 月涨幅 = (今日收盘 - 约21个交易日前收盘) / 约21个交易日前收盘
        def monthly_return(df: pd.DataFrame) -> float:
            close_now = float(df["close"].iloc[-1])
            close_month_ago = float(df["close"].iloc[-22])
            return pct_change(close_now, close_month_ago)

        ret_300 = monthly_return(df_300)
        ret_1000 = monthly_return(df_1000)

        if ret_300 is None or ret_1000 is None:
            return 0, "无法计算月涨幅", {"error": "calculation_failed"}

        diff = ret_1000 - ret_300  # 1000超额收益

        if diff > 5:
            score, label = +1, "bull (小票领涨)"
        elif diff < -5:
            score, label = -1, "bear (大票防御)"
        else:
            score, label = 0, "neutral"

        note = (
            f"CSI1000月涨幅={ret_1000:+.2f}% | 沪深300月涨幅={ret_300:+.2f}% "
            f"| 差值={diff:+.2f}% → {label}"
        )
        raw = {
            "csi1000_monthly_ret_pct": round(ret_1000, 3),
            "csi300_monthly_ret_pct": round(ret_300, 3),
            "diff_1000_minus_300": round(diff, 3),
        }
        return score, note, raw

    except Exception as e:
        return 0, f"获取失败: {e}", {"error": str(e)}


# ─── Signal 3: 北向资金方向 ──────────────────────────────────────────────────
# CSRC在2024年8月起停止披露北向每日净买入数据，导致akshare历史数据在该日期后全为NaN。
# 降级处理: 标注数据不可用，返回 0 (neutral)，不影响其他4个信号。

def signal_northbound() -> tuple[int, str, dict]:
    try:
        # 尝试获取最近14天数据 (2周)
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        df["日期"] = pd.to_datetime(df["日期"])
        df = df.sort_values("日期").tail(14)

        # 检查是否有有效的净买入数据
        valid = df["当日成交净买额"].dropna()
        if len(valid) < 10:
            note = (
                "⚠️ 北向数据不可用: CSRC 2024-08起停止披露北向每日净买入 "
                "(akshare历史数据2024-08-16后全为NaN)。跳过此信号 → neutral(0)"
            )
            raw = {
                "data_available": False,
                "reason": "CSRC stopped disclosing daily northbound flow since Aug-2024",
                "last_valid_date": None,
            }
            return 0, note, raw

        # 如果数据可用（未来API恢复时）
        recent_14d_sum = float(valid.sum())
        week1_sum = float(valid.tail(5).sum()) if len(valid) >= 5 else None
        week2_sum = float(valid.tail(10).head(5).sum()) if len(valid) >= 10 else None

        if week1_sum is not None and week2_sum is not None:
            both_inflow = week1_sum > 0 and week2_sum > 0
            both_outflow = week1_sum < 0 and week2_sum < 0
        else:
            both_inflow = both_outflow = False

        if both_inflow:
            score, label = +1, "bull (连续2周净流入)"
        elif both_outflow:
            score, label = -1, "bear (连续2周净流出)"
        else:
            score, label = 0, "neutral (方向不明)"

        note = f"北向近14日净买入={recent_14d_sum:.1f}亿 → {label}"
        raw = {
            "data_available": True,
            "14d_net_buy": round(recent_14d_sum, 2),
            "week1_sum": round(week1_sum, 2) if week1_sum else None,
            "week2_sum": round(week2_sum, 2) if week2_sum else None,
        }
        return score, note, raw

    except Exception as e:
        return 0, f"获取失败: {e}", {"error": str(e)}


# ─── Signal 4: 两融余额 月环比 ──────────────────────────────────────────────
# Uses SSE + SZSE 融资融券余额 combined.
# Rising margin = more leverage = risk-on sentiment.

def signal_margin_balance() -> tuple[int, str, dict]:
    try:
        # SSE margin data
        df_sh = ak.macro_china_market_margin_sh()
        df_sh["日期"] = pd.to_datetime(df_sh["日期"])
        df_sh = df_sh.sort_values("日期")

        # SZSE margin data
        df_sz = ak.macro_china_market_margin_sz()
        df_sz["日期"] = pd.to_datetime(df_sz["日期"])
        df_sz = df_sz.sort_values("日期")

        # Merge on date, use inner join for dates where both are available
        merged = pd.merge(
            df_sh[["日期", "融资融券余额"]].rename(columns={"融资融券余额": "sh_balance"}),
            df_sz[["日期", "融资融券余额"]].rename(columns={"融资融券余额": "sz_balance"}),
            on="日期",
            how="inner",
        ).sort_values("日期")

        if len(merged) < 22:
            return 0, "数据不足(< 22天)", {"error": "insufficient_data"}

        merged["total_balance"] = merged["sh_balance"] + merged["sz_balance"]
        latest_balance = float(merged["total_balance"].iloc[-1])
        month_ago_balance = float(merged["total_balance"].iloc[-22])

        pct = pct_change(latest_balance, month_ago_balance)
        if pct is None:
            return 0, "月前余额为0", {"error": "zero_base"}

        if pct > 5:
            score, label = +1, "bull (两融扩张)"
        elif pct < -5:
            score, label = -1, "bear (两融收缩)"
        else:
            score, label = 0, "neutral"

        note = (
            f"两融余额={latest_balance/1e12:.3f}万亿 | 月前={month_ago_balance/1e12:.3f}万亿 "
            f"| 月环比={pct:+.2f}% → {label}"
        )
        raw = {
            "latest_balance_cny": round(latest_balance, 0),
            "month_ago_balance_cny": round(month_ago_balance, 0),
            "monthly_pct_change": round(pct, 3),
            "latest_date": merged["日期"].iloc[-1].strftime("%Y-%m-%d"),
        }
        return score, note, raw

    except Exception as e:
        return 0, f"获取失败: {e}", {"error": str(e)}


# ─── Signal 5: CSI300 vs 20周均线 ───────────────────────────────────────────
# 20-week MA = 100 trading days (approx.)
# CSI300 above MA20w = trending bull; below = trending bear

def signal_csi300_vs_20w_ma() -> tuple[int, str, dict]:
    try:
        df = ak.stock_zh_index_daily(symbol="sh000300").sort_values("date").tail(160)

        if len(df) < 101:
            return 0, "数据不足(< 101天)", {"error": "insufficient_data"}

        close_series = df["close"].astype(float)
        latest_close = float(close_series.iloc[-1])
        ma20w = float(close_series.iloc[-101:-1].mean())  # 前100个交易日均值

        pct_vs_ma = pct_change(latest_close, ma20w)
        if pct_vs_ma is None:
            return 0, "MA20w为0", {"error": "zero_ma"}

        if pct_vs_ma > 2:
            score, label = +1, "bull (站上20周线)"
        elif pct_vs_ma < -2:
            score, label = -1, "bear (跌破20周线)"
        else:
            score, label = 0, "neutral (附近±2%)"

        note = (
            f"沪深300={latest_close:.2f} | 20周均线={ma20w:.2f} "
            f"| 偏离={pct_vs_ma:+.2f}% → {label}"
        )
        raw = {
            "csi300_close": round(latest_close, 2),
            "ma20w": round(ma20w, 2),
            "pct_vs_ma20w": round(pct_vs_ma, 3),
        }
        return score, note, raw

    except Exception as e:
        return 0, f"获取失败: {e}", {"error": str(e)}


# ─── Regime Aggregation ─────────────────────────────────────────────────────

SIGNAL_DEFS = [
    ("volume_vs_20dma",     "成交量vs20日均",          signal_volume_vs_20dma),
    ("csi1000_vs_csi300",   "中证1000/沪深300月涨幅差",  signal_csi1000_vs_csi300),
    ("northbound",          "北向资金方向",              signal_northbound),
    ("margin_balance",      "两融余额月环比",             signal_margin_balance),
    ("csi300_vs_20w_ma",    "CSI300 vs 20周均线",       signal_csi300_vs_20w_ma),
]


def run_all_signals(quiet: bool = False) -> dict:
    if not quiet:
        print(f"\n{'=' * 60}")
        print(f"A股 Regime Detection — {TODAY_STR}")
        print(f"{'=' * 60}")

    signals_out = []
    total_score = 0
    active_signal_count = 0  # count non-skipped signals

    for sig_id, sig_name, sig_func in SIGNAL_DEFS:
        score, note, raw = sig_func()
        total_score += score

        # A signal is "active" (contributes to count) unless it's a data-unavailable skip
        is_skipped = raw.get("data_available") is False
        if not is_skipped:
            active_signal_count += 1

        label_map = {+1: "🟢 +1", 0: "🟡  0", -1: "🔴 -1"}
        if not quiet:
            print(f"\n[{sig_id}] {sig_name}")
            print(f"  Score: {label_map.get(score, str(score))}")
            print(f"  Note : {note}")

        signals_out.append({
            "id": sig_id,
            "name": sig_name,
            "score": score,
            "note": note,
            "raw": raw,
            "skipped": is_skipped,
        })

    # Regime determination: based on total_score (signals §8)
    # Score range: [-5, +5]  (but signal 3 likely contributes 0 currently)
    # Rule: Σ ≥ +3 = bull | -2~+2 = sideways | ≤ -3 = bear
    if total_score >= 3:
        regime = "bull"
        regime_label = "🟢 牛市 (BULL)"
    elif total_score <= -3:
        regime = "bear"
        regime_label = "🔴 熊市 (BEAR)"
    else:
        regime = "sideways"
        regime_label = "🟡 震荡 (NEUTRAL)"

    # Confidence: lower if any signal was skipped
    skipped_count = sum(1 for s in signals_out if s["skipped"])
    base_confidence = 0.9 if skipped_count == 0 else 0.7 if skipped_count == 1 else 0.5

    # Regime definition for strategy params (from §8 Regime→参数切换)
    param_map = {
        "bull": {
            "atr_k_range": [2.0, 3.5],
            "hard_stop": "-15%",
            "max_single_position": "25-50%",
            "cash_floor": "无",
            "max_holdings": 8,
            "gamma_catalyst": "cap B级",
        },
        "sideways": {
            "atr_k_range": [1.5, 2.5],
            "hard_stop": "-12%",
            "max_single_position": "15-25%",
            "cash_floor": "≥20%",
            "max_holdings": 6,
            "gamma_catalyst": "cap C级",
        },
        "bear": {
            "atr_k_range": [1.0, 1.5],
            "hard_stop": "-8%~-10%",
            "max_single_position": "≤15%",
            "cash_floor": "≥40%",
            "max_holdings": 4,
            "gamma_catalyst": "禁止",
        },
    }

    if not quiet:
        print(f"\n{'─' * 60}")
        print(f"总分: {total_score:+d} (有效信号: {active_signal_count}/5)")
        print(f"Regime: {regime_label}")
        params = param_map[regime]
        print(f"\n策略参数切换 ({regime_label}):")
        print(f"  ATR K值    : {params['atr_k_range'][0]}-{params['atr_k_range'][1]}")
        print(f"  硬止损     : {params['hard_stop']}")
        print(f"  单只上限   : {params['max_single_position']}")
        print(f"  现金底线   : {params['cash_floor']}")
        print(f"  最大持仓数 : {params['max_holdings']}")
        print(f"  γ催化剂   : {params['gamma_catalyst']}")
        print(f"{'=' * 60}")

    result = {
        "metadata": {
            "description": "A股专属Regime Detection — strategy_astock.md §8 五信号评分法",
            "schema_version": "1.0",
            "last_updated": NOW.isoformat(),
            "update_source": "astock_regime.py",
            "signals_defined": 5,
            "signals_active": active_signal_count,
            "signals_skipped": skipped_count,
        },
        "current_regime": {
            "regime": regime,
            "regime_label": regime_label,
            "total_score": total_score,
            "confidence": base_confidence,
            "since_date": TODAY_STR,
            "source": "astock_regime.py v1.0 — A股专属5信号规则层",
            "reasoning": (
                f"总分={total_score:+d} "
                f"({'≥+3 牛市' if total_score >= 3 else '≤-3 熊市' if total_score <= -3 else '-2~+2 震荡'})"
            ),
        },
        "regime_params": param_map[regime],
        "regime_definition": {
            "bull":     {"condition": "Σ ≥ +3", "label": "牛市"},
            "sideways": {"condition": "-2 ≤ Σ ≤ +2", "label": "震荡"},
            "bear":     {"condition": "Σ ≤ -3", "label": "熊市"},
            "switch_rule": "牛→熊需2周连续≤-3 | 熊→牛需3周连续≥+3 (手动确认)",
        },
        "signals": signals_out,
        "stale_after_days": 7,  # weekly cadence per §8
    }

    return result


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="A股Regime检测 (strategy_astock.md §8)")
    parser.add_argument("--quiet", "-q", action="store_true", help="只输出Regime结论行")
    parser.add_argument("--no-write", action="store_true", help="不写入Truth Store")
    args = parser.parse_args()

    result = run_all_signals(quiet=args.quiet)

    if not args.no_write:
        atomic_write_json(OUTPUT_PATH, result)
        if not args.quiet:
            print(f"\n[OK] 已写入: {OUTPUT_PATH}")
        else:
            regime = result["current_regime"]["regime"]
            score = result["current_regime"]["total_score"]
            print(f"A股Regime: {result['current_regime']['regime_label']} (Σ={score:+d}) → {OUTPUT_PATH}")
    else:
        if args.quiet:
            regime_label = result["current_regime"]["regime_label"]
            score = result["current_regime"]["total_score"]
            print(f"A股Regime: {regime_label} (Σ={score:+d})")


if __name__ == "__main__":
    main()
