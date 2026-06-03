#!/usr/bin/env python3
"""UASS v6.0 — D8 主线演进追踪: 连续天数 + 自动阶段判定 + 趋势方向"""

from __future__ import annotations
import json
from pathlib import Path

from uass_types import MAINLINE_HISTORY, STAGE_PRIORITY, mainline_sort_key


# ── 加载 / 保存历史 ──────────────────────────────────────────────────────────

def load_mainline_history() -> dict:
    """Load historical sector limit-up data (past 20 trading days)."""
    if MAINLINE_HISTORY.exists():
        with open(MAINLINE_HISTORY) as f:
            return json.load(f)
    return {"days": []}


def save_mainline_history(history: dict):
    """Persist mainline history, keep last 20 days."""
    history["days"] = history["days"][-20:]
    MAINLINE_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(MAINLINE_HISTORY, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


# ── 连板天数 + 阶段判定 ──────────────────────────────────────────────────────

def compute_mainline_streaks(history: dict, today_sectors: dict) -> dict[str, dict]:
    """
    Given sector data for today and historical days, compute hot streak
    (consecutive days with ≥2 limit-ups) and auto-stage.

    today_sectors values may be:
      - int: legacy format (just zt_count)
      - dict: new format with keys zt_count, avg_gain, leader, leader_gain

    Stage logic:
      Day 1: 启动(首日)
      Day 2-3: 主升早
      Day 4-5: 主升中
      Day 6+: 高潮/退潮风险

    Trend logic (today vs yesterday, for sectors with ≥2 days of history):
      今日涨停数 > 昨日 → "加速"
      今日涨停数 == 昨日 → "持平"
      今日涨停数 < 昨日 → "减速" (退潮信号)

    BUG FIX (P2 D8 repeat pollution):
      If the last entry in history["days"] already carries today's date (i.e. the
      scan is being re-run on the same trading day), that entry is excluded from
      the streak count so today's data is NOT double-counted as a prior day.
    """
    def _get_zt_count(val) -> int:
        """Extract zt_count whether val is int or new-format dict."""
        if isinstance(val, dict):
            return val.get("zt_count", 0)
        return int(val) if val else 0

    results = {}

    # Only look at days whose date differs from today — prevents double-counting
    # when the same date has already been appended during a prior run today.
    # Callers must pass the date_str they intend to use so we can filter correctly.
    # However, since compute_mainline_streaks does not receive date_str directly,
    # we rely on the contract enforced by update_mainline_history: this function is
    # called BEFORE today's entry is appended/updated, so history["days"] never
    # contains today's data at the time of this call.
    past_days = history.get("days", [])

    for sector, today_val in today_sectors.items():
        today_count = _get_zt_count(today_val)
        if today_count < 2:
            continue

        # Count consecutive prior days (walk backwards) with ≥2 limit-ups
        streak = 1  # today itself counts as day 1
        for day in reversed(past_days):
            day_sectors = day.get("sectors", {})
            past_val = day_sectors.get(sector, 0)
            if _get_zt_count(past_val) >= 2:
                streak += 1
            else:
                break

        if streak == 1:
            stage = "启动(首日)"
        elif streak <= 3:
            stage = "主升早"
        elif streak <= 5:
            stage = "主升中"
        else:
            stage = "高潮/退潮风险"

        # Trend: compare today vs yesterday (last entry in past_days)
        trend = "持平"
        if past_days:
            yesterday_val = past_days[-1].get("sectors", {}).get(sector, 0)
            yesterday_count = _get_zt_count(yesterday_val)
            if today_count > yesterday_count:
                trend = "加速"
            elif today_count < yesterday_count:
                trend = "减速"

        results[sector] = {
            "streak_days": streak,
            "today_count": today_count,
            "stage_auto": stage,
            "trend": trend,
            "actionability": STAGE_PRIORITY.get(stage, 99),
        }

    return results


# ── 主入口: 更新历史 + 返回条纹 ─────────────────────────────────────────────

def update_mainline_history(history: dict, date_str: str, scored: list) -> dict[str, dict]:
    """
    Count limit-ups per sector for today, enrich with avg_gain and leader info,
    append to history, compute streaks. Returns streak info per sector.

    Stored sector format (new):
      {"光通信": {"zt_count": 5, "avg_gain": 8.3, "leader": "002281", "leader_gain": 12.5}}

    BUG FIX (P2 D8 repeat pollution):
      Streaks are computed using the history state BEFORE today's entry is
      appended/updated.  The duplicate-date guard then either appends a fresh
      entry or replaces the existing same-date entry, ensuring idempotent
      re-runs do not accumulate duplicate rows.

    Execution order:
      1. Build sector_counts from scored (limit-up stocks only)
      2. Compute streaks against history BEFORE today is written
      3. Append or replace today's entry in history["days"]
      4. Save history (trimmed to last 20 days)
      5. Return streaks
    """
    # Step 1: Collect per-sector data from limit-up stocks
    sector_data: dict[str, dict] = {}
    for s in scored:
        if not s.get("涨停"):
            continue
        sec = s.get("行业", "")
        if not sec:
            continue
        if sec not in sector_data:
            sector_data[sec] = {
                "zt_count": 0,
                "gains": [],
                "leader": "",
                "leader_gain": -999.0,
            }
        sector_data[sec]["zt_count"] += 1
        chg = s.get("涨跌幅", 0.0)
        sector_data[sec]["gains"].append(chg)
        if chg > sector_data[sec]["leader_gain"]:
            sector_data[sec]["leader_gain"] = chg
            sector_data[sec]["leader"] = s.get("代码", "")

    # Build final sector dict with avg_gain, drop internal gains list
    sector_counts: dict[str, dict] = {}
    for sec, info in sector_data.items():
        gains = info["gains"]
        avg_gain = round(sum(gains) / len(gains), 1) if gains else 0.0
        sector_counts[sec] = {
            "zt_count": info["zt_count"],
            "avg_gain": avg_gain,
            "leader": info["leader"],
            "leader_gain": (
                round(info["leader_gain"], 1)
                if info["leader_gain"] != -999.0
                else 0.0
            ),
        }

    # Step 2: Compute streaks BEFORE today's data is written to history.
    # At this point history["days"] contains only prior trading days (or it
    # already has today's entry from a previous run — but the duplicate-date
    # guard below will replace it, and the streak was computed without it).
    #
    # Edge case: if the last entry IS today (re-run), we must temporarily
    # exclude it so the streak count uses only genuine prior days.
    days = history.get("days", [])
    if days and days[-1].get("date") == date_str:
        # Re-run scenario: compute streaks against history minus today's stale row
        history_for_streaks = {"days": days[:-1]}
    else:
        history_for_streaks = history

    streaks = compute_mainline_streaks(history_for_streaks, sector_counts)

    # Step 3: Append new entry or replace existing same-date entry (idempotent)
    if not history["days"] or history["days"][-1].get("date") != date_str:
        history["days"].append({"date": date_str, "sectors": sector_counts})
    else:
        history["days"][-1]["sectors"] = sector_counts

    # Step 4: Persist (trimmed to 20 days)
    save_mainline_history(history)

    # Step 5: Return streaks
    return streaks


# ── 便捷展示 (独立运行时) ────────────────────────────────────────────────────

def _display_streaks(streaks: dict[str, dict]):
    """Pretty-print streak info sorted by stage priority then count."""
    if not streaks:
        print("  (无热门板块，今日涨停数≥2的板块为空)")
        return

    sorted_items = sorted(streaks.items(), key=mainline_sort_key)
    header = f"{'板块':<14} {'阶段':<12} {'连续天':<6} {'今日涨停':<8} {'趋势'}"
    print(header)
    print("-" * len(header))
    for sec, info in sorted_items:
        trend_symbol = {"加速": "▲", "持平": "─", "减速": "▼"}.get(info["trend"], "?")
        print(
            f"{sec:<14} {info['stage_auto']:<12} "
            f"{info['streak_days']:<6} {info['today_count']:<8} "
            f"{trend_symbol} {info['trend']}"
        )


if __name__ == "__main__":
    import sys

    print("=== UASS v6.0 — D8 主线演进追踪 (独立运行) ===\n")
    history = load_mainline_history()
    days = history.get("days", [])
    print(f"历史记录: {len(days)} 个交易日")
    if days:
        print(f"最新日期: {days[-1].get('date', 'N/A')}")
        last_sectors = days[-1].get("sectors", {})
        hot = {k: v for k, v in last_sectors.items()
               if (v.get("zt_count", 0) if isinstance(v, dict) else int(v or 0)) >= 2}
        print(f"上次热门板块数: {len(hot)}\n")

        if hot:
            print("--- 基于最近历史的连板预估 ---")
            # Simulate: treat last day's sectors as "today" for display purposes
            preview_history = {"days": days[:-1]}
            preview_streaks = compute_mainline_streaks(preview_history, last_sectors)
            _display_streaks(preview_streaks)
    else:
        print("(暂无历史数据，请先运行 uass_scan.py 生成数据)")

    sys.exit(0)
