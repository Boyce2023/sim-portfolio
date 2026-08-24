#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["akshare>=1.12.0", "pandas"]
# ///
"""
A股财报预约披露日历刷新 — astock_catalyst_calendar.py

背景 (2026-08-24): portfolio_state.json 的 catalyst_calendar 是死的
(16只持仓只剩1条5月记录)，而 X2(催化剂过期T+5) / L11(催化剂前减仓) /
T18第⑤门(催化兑现) 三条规则全依赖它。本脚本用 akshare
`stock_report_disclosure` 拉持仓A股的半年报/季报预约披露日，写回
catalyst_calendar，供上述规则消费。

⚠️ akshare period 参数值是 "2026半年报"，不是 "2026年中报"（实测确认）。

写入方式: 只替换本脚本自己生成的条目（用 source 字段标记 tag=astock_catalyst_calendar），
手工维护的条目（如宏观事件/非A股持仓）保持不动，幂等可重复跑。

⛔ 不直接写 portfolio_state.json，走 portfolio_io.save_portfolio()。

用法:
  uv run --script scripts/astock_catalyst_calendar.py
  uv run --script scripts/astock_catalyst_calendar.py --dry-run   # 只打印不写入
  uv run --script scripts/astock_catalyst_calendar.py --period 2026三季度  # 手动指定period
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from portfolio_io import load_portfolio, save_portfolio  # noqa: E402

SIGNAL_SOURCE_TAG = "astock_catalyst_calendar"


# ── period自动推断 ─────────────────────────────────────────────────────────────
def infer_period(today: date) -> str:
    """
    按A股定期报告披露窗口推断当前应查询的period。
    窗口: 一季报(Q1)披露截止4/30 | 半年报披露截止8/31 | 三季报披露截止10/31 | 年报披露截止次年4/30
    简化映射(覆盖预约+实际披露的活跃查询窗口):
      1-4月  → 上一年年报  "{y-1}年报"
      5-8月  → 当年半年报  "{y}半年报"
      9-10月 → 当年三季度  "{y}三季度"
      11-12月→ 当年三季度  "{y}三季度" (10/31截止后仍是最新已知窗口,年报要等次年)
    """
    y, m = today.year, today.month
    if 1 <= m <= 4:
        return f"{y-1}年报"
    elif 5 <= m <= 8:
        return f"{y}半年报"
    else:
        return f"{y}三季度"


# ── 数据拉取 ───────────────────────────────────────────────────────────────────
def fetch_disclosure_dates(period: str) -> pd.DataFrame:
    df = ak.stock_report_disclosure(market="沪深京", period=period)
    return df


def best_date_for_ticker(row: pd.Series, today: date) -> tuple[date | None, str, bool]:
    """
    从一行记录里选出最可信的预约/实际披露日。
    返回 (date_or_None, label, is_already_disclosed)
    优先级: 三次变更 > 二次变更 > 初次变更 > 首次预约 (取"最新预测")
            若 实际披露 非空且 <= today → 视为已披露,不再作为未来催化剂
    """
    actual = row.get("实际披露")
    if pd.notna(actual):
        d = actual.date() if hasattr(actual, "date") else pd.Timestamp(actual).date()
        if d <= today:
            return d, "已披露", True
        # 实际披露日期在未来(理论上不该发生,但兜底)
        return d, "实际披露(未来)", False

    for col, label in (("三次变更", "三次变更预约"), ("二次变更", "二次变更预约"),
                        ("初次变更", "初次变更预约"), ("首次预约", "首次预约")):
        v = row.get(col)
        if pd.notna(v):
            d = v.date() if hasattr(v, "date") else pd.Timestamp(v).date()
            return d, label, False

    return None, "", False


# ── 主逻辑 ───────────────────────────────────────────────────────────────────
def build_entries(positions: list[dict], period: str, today: date) -> tuple[list[dict], list[str]]:
    """返回 (新催化剂条目列表, 跳过/警告日志)"""
    tickers = [p.get("ticker", "") for p in positions if p.get("ticker")]
    logs: list[str] = []

    try:
        df = fetch_disclosure_dates(period)
    except Exception as e:
        logs.append(f"⛔ akshare stock_report_disclosure(period={period}) 调用失败: {e}")
        return [], logs

    if df is None or df.empty:
        logs.append(f"⚠️ period={period} 返回空数据")
        return [], logs

    df_idx = df.set_index("股票代码")
    entries: list[dict] = []

    for pos in positions:
        ticker = pos.get("ticker", "")
        name = pos.get("name", ticker)
        if not ticker:
            continue

        if ticker not in df_idx.index:
            logs.append(f"⚠️ [{ticker}] {name}: period={period} 数据中未找到，跳过")
            continue

        row = df_idx.loc[ticker]
        # 同ticker可能多行(理论不该,但防御)
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        d, label, disclosed = best_date_for_ticker(row, today)

        if d is None:
            logs.append(f"⚠️ [{ticker}] {name}: 无任何可用披露日期，跳过")
            continue

        if disclosed:
            logs.append(f"ℹ️  [{ticker}] {name}: {period} 已于 {d.isoformat()} 披露，不计入未来催化剂日历")
            continue

        days_away = (d - today).days
        if days_away < 0:
            urgency = "CRITICAL"  # 预约日期已过但仍未标实际披露 = 逾期，异常值得关注
        elif days_away <= 5:
            urgency = "CRITICAL"
        elif days_away <= 14:
            urgency = "HIGH"
        else:
            urgency = "MEDIUM"

        entries.append({
            "date": d.isoformat(),
            "ticker": ticker,
            "event": f"{name} {period}预约披露({label})",
            "urgency": urgency,
            "precommitted_action": (
                f"{period}披露: 营收/扣非利润增速对照建仓thesis核对 → "
                f"兑现→按T18第⑤门评估兑现区间减仓; 不及预期/thesis证伪→按T18第③门评估卖出"
            ),
            "source": SIGNAL_SOURCE_TAG,
        })
        logs.append(f"✓ [{ticker}] {name}: {d.isoformat()} ({label}, {urgency})")

    return entries, logs


def refresh_catalyst_calendar(*, dry_run: bool = False, period_override: str | None = None) -> int:
    today = date.today()
    period = period_override or infer_period(today)

    print(f"\n{'='*70}")
    print(f"  A股财报预约披露日历刷新  |  {today.isoformat()}  |  period={period}")
    print(f"{'='*70}\n")

    state = load_portfolio()
    positions = state.get("accounts", {}).get("a_share", {}).get("positions", [])
    if not positions:
        print("  无A股持仓，退出。")
        return 0

    print(f"持仓: {len(positions)} 只\n")

    entries, logs = build_entries(positions, period, today)
    for line in logs:
        print(f"  {line}")

    if not entries:
        print("\n  无新增/更新的催化剂条目。")

    # ── 合并: 保留非本脚本生成的旧条目 + 替换本脚本生成的条目 ──────────────────────
    old_calendar = state.get("catalyst_calendar", [])
    if isinstance(old_calendar, dict):
        old_calendar = list(old_calendar.values())

    preserved = [e for e in old_calendar if e.get("source") != SIGNAL_SOURCE_TAG]
    new_calendar = preserved + entries
    new_calendar.sort(key=lambda e: e.get("date", "9999-99-99"))

    print(f"\n  日历条目: 保留{len(preserved)}条(非本脚本来源) + 新增/更新{len(entries)}条 = 共{len(new_calendar)}条")

    if dry_run:
        print("\n  [--dry-run] 不写入 portfolio_state.json")
        for e in entries:
            print(f"    {e['date']} | {e['ticker']} | {e['event']} | {e['urgency']}")
        print(f"\n{'='*70}\n")
        return len(entries)

    state["catalyst_calendar"] = new_calendar
    save_portfolio(state, reason="auto: A股财报预约披露日历刷新(astock_catalyst_calendar.py)", auto_sync=False)
    print(f"\n  ✓ catalyst_calendar 已更新并写入 portfolio_state.json (auto_sync=False, 交由daily_run.sh末尾统一commit)")
    print(f"\n{'='*70}\n")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description="A股财报预约披露日历刷新")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写入portfolio_state.json")
    parser.add_argument("--period", type=str, default=None,
                         help='手动指定akshare period(如"2026三季度")，默认按当前日期自动推断')
    args = parser.parse_args()

    count = refresh_catalyst_calendar(dry_run=args.dry_run, period_override=args.period)
    sys.exit(0)


if __name__ == "__main__":
    main()
