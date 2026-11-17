#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
系统健康检查脚本 — 远程Agent执行前必须运行
快速验证portfolio_state.json完整性 + 风控规则 + 今日是否交易日

用法: uv run --script scripts/system_check.py
"""

import json
import sys
import os
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

# ── 路径 ────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent.parent
PORTFOLIO_FILE = REPO_ROOT / "portfolio_state.json"
CALENDAR_FILE  = REPO_ROOT / "market_calendar.json"

# ── 颜色输出 ─────────────────────────────────────────────────────────────────
PASS  = "\033[92m[PASS]\033[0m"
WARN  = "\033[93m[WARN]\033[0m"
FAIL  = "\033[91m[FAIL]\033[0m"
INFO  = "\033[94m[INFO]\033[0m"
BOLD  = "\033[1m"
RESET = "\033[0m"

results = []  # (level, message)

def record(level: str, msg: str):
    results.append((level, msg))
    icon = {"PASS": PASS, "WARN": WARN, "FAIL": FAIL, "INFO": INFO}.get(level, INFO)
    print(f"  {icon} {msg}")


# ── Check 1: 文件存在 ─────────────────────────────────────────────────────────
def check_files_exist():
    print(f"\n{BOLD}[1] 文件存在性{RESET}")
    ok = True
    for f in [PORTFOLIO_FILE, CALENDAR_FILE]:
        if f.exists() and f.stat().st_size > 0:
            record("PASS", f"{f.name} 存在且非空")
        else:
            record("FAIL", f"{f.name} 不存在或为空")
            ok = False
    return ok


# ── Check 2: JSON格式正确 ──────────────────────────────────────────────────────
def load_portfolio():
    print(f"\n{BOLD}[2] JSON格式验证{RESET}")
    try:
        data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        record("PASS", "portfolio_state.json JSON格式正确")
        return data
    except json.JSONDecodeError as e:
        record("FAIL", f"portfolio_state.json JSON解析错误: {e}")
        return None


def load_calendar():
    try:
        return json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Check 3: 完整性校验 Σ市值+现金=总资产 ─────────────────────────────────────
def check_integrity(data: dict):
    print(f"\n{BOLD}[3] 资产完整性校验{RESET}")

    for acct_key, acct in data.get("accounts", {}).items():
        positions = acct.get("positions", [])
        cash      = acct.get("cash", 0)
        reported  = acct.get("total_assets", 0)
        currency  = acct.get("currency", "?")

        market_val_sum = sum(p.get("market_value", 0) for p in positions)
        computed = market_val_sum + cash
        diff = abs(computed - reported)
        tol  = reported * 0.001  # 0.1% 容差（价格舍入）

        label = acct_key.upper()
        if diff <= tol:
            record("PASS", f"{label}: Σ市值+现金={computed:,.0f} {currency} ≈ total_assets={reported:,.0f} (diff={diff:.0f})")
        else:
            record("FAIL", f"{label}: 不平衡! Σ={computed:,.0f} vs reported={reported:,.0f}, diff={diff:,.0f} {currency}")


# ── Check 4: 所有持仓有stop_loss ─────────────────────────────────────────────
def check_stop_loss(data: dict):
    print(f"\n{BOLD}[4] 止损设置检查{RESET}")
    issues = []
    for acct_key, acct in data.get("accounts", {}).items():
        for p in acct.get("positions", []):
            ticker = p.get("ticker", "?")
            sl = p.get("stop_loss")
            if sl is None or sl <= 0:
                issues.append(f"{acct_key}.{ticker}: stop_loss缺失")
    if not issues:
        record("PASS", "所有持仓均设有止损价")
    else:
        for issue in issues:
            record("FAIL", issue)


# ── Check 5: 单只≤15%, 现金≥20% ────────────────────────────────────────────────
def check_position_limits(data: dict):
    print(f"\n{BOLD}[5] 仓位规则合规{RESET}")

    for acct_key, acct in data.get("accounts", {}).items():
        total_assets = acct.get("total_assets", 1)
        cash         = acct.get("cash", 0)
        currency     = acct.get("currency", "?")

        cash_pct = cash / total_assets if total_assets else 0
        if cash_pct >= 0.20:
            record("PASS", f"{acct_key.upper()}: 现金={cash_pct:.1%} ≥ 20%")
        else:
            record("WARN", f"{acct_key.upper()}: 现金={cash_pct:.1%} < 20% 最低要求")

        for p in acct.get("positions", []):
            ticker  = p.get("ticker", "?")
            mv      = p.get("market_value", 0)
            pct     = mv / total_assets if total_assets else 0
            pct_stored = p.get("portfolio_pct", pct)
            if pct_stored <= 0.15:
                record("PASS", f"  {ticker}: {pct_stored:.1%} ≤ 15%")
            else:
                record("FAIL", f"  {ticker}: {pct_stored:.1%} 超出15%单仓上限!")


# ── Check 6: 杠杆率 (美股账户) ───────────────────────────────────────────────
def check_leverage(data: dict):
    print(f"\n{BOLD}[6] 杠杆率检查{RESET}")
    us = data.get("accounts", {}).get("us", {})
    if not us:
        record("INFO", "未找到us账户，跳过杠杆检查")
        return

    total_invested = us.get("total_invested", 0)
    initial        = us.get("initial_capital", 150000)
    leverage_cap   = us.get("leverage_cap", 2.0)
    gross_exposure = us.get("max_gross_exposure", initial * leverage_cap)

    leverage_ratio = total_invested / initial if initial else 0
    if leverage_ratio <= leverage_cap:
        record("PASS", f"US杠杆率: {leverage_ratio:.2f}x ≤ cap {leverage_cap}x")
    else:
        record("FAIL", f"US杠杆率: {leverage_ratio:.2f}x 超出上限 {leverage_cap}x!")


# ── Check 7: 今天是否交易日 ──────────────────────────────────────────────────
def check_trading_day(cal):
    print(f"\n{BOLD}[7] 今日交易日状态{RESET}")

    today     = date.today()
    today_str = today.isoformat()
    weekday   = today.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:
        day_name = "周六" if weekday == 5 else "周日"
        record("INFO", f"今天是{day_name} ({today_str}) — 三市场均休市")
        return

    markets_closed_today = []
    if cal:
        closed = cal.get("trading_days_by_market", {})
        for mkt, dates in closed.items():
            mkt_label = mkt.replace("_closed_dates", "").upper()
            if today_str in dates:
                markets_closed_today.append(mkt_label)

    open_markets = []
    for mkt in ["CN", "HK", "US"]:
        if mkt not in markets_closed_today and f"{mkt.lower()}_closed_dates" not in [m.lower() for m in markets_closed_today]:
            open_markets.append(mkt)

    # Re-check with correct key names
    markets_closed_labels = []
    if cal:
        td = cal.get("trading_days_by_market", {})
        for key, dates in td.items():
            if today_str in dates:
                label = key.replace("_closed_dates", "").upper()
                markets_closed_labels.append(label)

    all_markets = {"CN", "HK", "US"}
    open_set = all_markets - set(markets_closed_labels)

    if markets_closed_labels:
        record("WARN", f"今日休市市场: {', '.join(markets_closed_labels)}")
    if open_set:
        record("PASS", f"今日开市市场: {', '.join(sorted(open_set))} ({today_str})")
    else:
        record("INFO", f"今日三市场均休市 ({today_str})")

    # 检查催化剂
    if cal:
        events = [e for e in cal.get("catalyst_calendar", []) if e.get("date") == today_str]
        for ev in events:
            urgency = ev.get("urgency", "INFO")
            record("WARN" if urgency in ("HIGH", "CRITICAL") else "INFO",
                   f"TODAY CATALYST: {ev.get('event', '?')} [{urgency}]")


# ── Check 8: 最近更新时间 ─────────────────────────────────────────────────────
def check_staleness(data: dict):
    print(f"\n{BOLD}[8] 数据新鲜度{RESET}")
    last_updated_str = data.get("_meta", {}).get("last_updated", "")
    if not last_updated_str:
        record("WARN", "portfolio_state.json 无 last_updated 字段")
        return

    try:
        # 解析时间（支持带时区偏移格式）
        last_updated_str_clean = last_updated_str.replace("+08:00", "+0800").replace("+00:00", "+0000")
        try:
            lu = datetime.fromisoformat(last_updated_str)
        except Exception:
            lu = datetime.strptime(last_updated_str_clean[:19], "%Y-%m-%dT%H:%M:%S")
            lu = lu.replace(tzinfo=timezone(timedelta(hours=8)))

        now_aware = datetime.now(tz=timezone(timedelta(hours=8)))
        if lu.tzinfo is None:
            lu = lu.replace(tzinfo=timezone(timedelta(hours=8)))

        hours_ago = (now_aware - lu).total_seconds() / 3600
        if hours_ago <= 24:
            record("PASS", f"最近更新: {last_updated_str} ({hours_ago:.1f}小时前)")
        elif hours_ago <= 48:
            record("WARN", f"数据偏旧: {last_updated_str} ({hours_ago:.1f}小时前，>24h)")
        else:
            record("FAIL", f"数据严重过期: {last_updated_str} ({hours_ago:.1f}小时前，>48h)")
    except Exception as e:
        record("WARN", f"无法解析 last_updated 时间: {last_updated_str} ({e})")


# ── 汇总 ──────────────────────────────────────────────────────────────────────
def summary():
    print(f"\n{BOLD}{'='*55}{RESET}")
    fails  = [m for lv, m in results if lv == "FAIL"]
    warns  = [m for lv, m in results if lv == "WARN"]
    passes = [m for lv, m in results if lv == "PASS"]

    total = len(fails) + len(warns) + len(passes)
    print(f"  PASS: {len(passes)}  WARN: {len(warns)}  FAIL: {len(fails)}")

    if fails:
        print(f"\n  {FAIL} 系统状态: {BOLD}FAIL{RESET} — 发现 {len(fails)} 个严重问题，请在交易前修复:")
        for m in fails:
            print(f"    • {m}")
        sys.exit(2)
    elif warns:
        print(f"\n  {WARN} 系统状态: {BOLD}WARN{RESET} — 有 {len(warns)} 个警告，可继续但请注意:")
        for m in warns:
            print(f"    • {m}")
        sys.exit(1)
    else:
        print(f"\n  {PASS} 系统状态: {BOLD}ALL CLEAR{RESET} — 可以开始今日交易")
        sys.exit(0)


# ── 主入口 ────────────────────────────────────────────────────────────────────
def main():
    print(f"{BOLD}{'='*55}")
    print(f"  Claude模拟盘 — 系统健康检查")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}{RESET}")

    # Check 1
    if not check_files_exist():
        print(f"\n  {FAIL} 关键文件缺失，无法继续检查")
        sys.exit(2)

    # Check 2
    data = load_portfolio()
    if data is None:
        sys.exit(2)

    cal = load_calendar()
    if cal is None:
        record("WARN", "market_calendar.json 加载失败，跳过日历检查")

    # Checks 3-8
    check_integrity(data)
    check_stop_loss(data)
    check_position_limits(data)
    check_leverage(data)
    check_trading_day(cal)
    check_staleness(data)

    summary()


if __name__ == "__main__":
    main()
