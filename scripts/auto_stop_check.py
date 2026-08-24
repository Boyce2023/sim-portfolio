#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""
A股灾难线自动止损检测器 — auto_stop_check.py

背景 (2026-08-24): 三环集团(300408)和生益科技(600183)双双跌破灾难线-12%,
全靠人肉盯盘才发现并手动清仓。daily_run.sh 里此前没有任何自动止损检测环节。

规则: 现价 vs avg_cost * 0.88 (灾难线, T18第②门绝对地板,破线=无条件出,
      thesis/信心/催化都不能override)。

⛔⛔ 只告警,绝不自动下单。执行权永远归人(T0铁律)。本脚本唯一职责是让人
不可能错过 — 破线时打印醒目终端告警 + 写 nexus critical 信号。

价格来源: astock_data_layer.get_batch_prices()（东财主源+腾讯兜底），
⛔ 禁止对A股使用 yfinance（D12铁律）。

用法:
  uv run --script scripts/auto_stop_check.py
  uv run --script scripts/auto_stop_check.py --no-signal
  uv run --script scripts/auto_stop_check.py --verbose

退出码: 破线持仓数量（0 = 全部安全）。非零供 daily_run.sh 感知并在日志汇总中显眼标红。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import astock_data_layer as adl  # noqa: E402 — 唯一合法A股行情入口 + yfinance拦截器

# ── 路径 ─────────────────────────────────────────────────────────────────────
REPO          = Path(__file__).resolve().parent.parent
PORTFOLIO     = REPO / "portfolio_state.json"
NEXUS_SIGNALS = Path.home() / ".claude" / "nexus" / "signals" / "pending"

# ── 灾难线阈值 ─────────────────────────────────────────────────────────────────
DISASTER_LINE_RATIO = 0.88  # avg_cost * 0.88 = 灾难线 (跌破成本-12%)


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def get_a_positions(portfolio: dict) -> list[dict]:
    try:
        return portfolio["accounts"]["a_share"]["positions"]
    except (KeyError, TypeError):
        return []


# ── 信号 ─────────────────────────────────────────────────────────────────────

def _existing_signal_today(ticker: str, today_str: str) -> bool:
    """同一天已经为该ticker发过灾难线信号 → 不重复写，避免每次daily_run都刷屏。"""
    if not NEXUS_SIGNALS.exists():
        return False
    pattern = f"auto_stop_check-disaster-{ticker}"
    for f in NEXUS_SIGNALS.glob(f"sig-{today_str.replace('-', '')}-*"):
        if pattern in f.name:
            return True
    return False


def write_nexus_signal(ticker: str, name: str, price: float, disaster_line: float,
                        avg_cost: float, breach_pct: float) -> Path | None:
    if not NEXUS_SIGNALS.exists():
        try:
            NEXUS_SIGNALS.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    if _existing_signal_today(ticker, today_str):
        return None

    now_iso = now.astimezone(timezone.utc).isoformat()
    exp_iso = (now + timedelta(days=3)).astimezone(timezone.utc).isoformat()
    sig_id = f"sig-{now.strftime('%Y%m%d-%H%M%S')}-auto_stop_check-disaster-{ticker}"

    d = {
        "id": sig_id,
        "from": "auto_stop_check",
        "to": ["trading_astock"],
        "priority": "critical",
        "type": "position_change",
        "title": f"🚨 灾难线击穿 | {name}({ticker}) | 现价较成本 {breach_pct:+.2f}%",
        "content": (
            f"T18第②门(灾难线)触发: 现价 ¥{price:.2f} 已跌破灾难线 ¥{disaster_line:.2f} "
            f"(=成本×{DISASTER_LINE_RATIO})\n"
            f"较成本价跌幅: {breach_pct:+.2f}%\n"
            f"规则: 灾难线是绝对地板, thesis/信心/催化都不能override, 无条件出。"
        ),
        "action_required": (
            f"⛔仅提醒,不自动下单。立即人工确认执行清仓: "
            f"uv run --script scripts/execute_trade.py sell --account cn "
            f"--ticker {ticker} --all --reason \"T18第②门灾难线-12%触发\""
        ),
        "source_context": "auto-detect:disaster_line",
        "created_at": now_iso,
        "expires_at": exp_iso,
        "lifecycle": "pending",
        "read_by": [],
        "acted_on": False,
    }
    fname = NEXUS_SIGNALS / f"{sig_id}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return fname


# ── 主检测逻辑 ──────────────────────────────────────────────────────────────────

def run_check(*, write_signal: bool = True, verbose: bool = False) -> list[dict]:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*70}")
    print(f"  A股灾难线自动止损检测  |  {now_str}  |  阈值: avg_cost × {DISASTER_LINE_RATIO}")
    print(f"{'='*70}")

    portfolio = load_json(PORTFOLIO)
    positions = get_a_positions(portfolio)

    if not positions:
        print("  无A股持仓，退出。")
        return []

    tickers = [p.get("ticker", "") for p in positions if p.get("ticker")]
    print(f"\n持仓: {len(positions)} 只 | 正在拉取实时价格 (astock_data_layer/eastmoney+tencent)...")

    try:
        live_prices = adl.get_batch_prices(tickers)
    except Exception as e:
        print(f"  ⚠️ 批量取价失败: {e}，尝试逐只降级")
        live_prices = {}

    breaches: list[dict] = []
    rows: list[tuple] = []

    for pos in positions:
        ticker   = pos.get("ticker", "")
        name     = pos.get("name", ticker)
        avg_cost = pos.get("avg_cost")

        if not avg_cost or avg_cost <= 0:
            print(f"  ⚠️ [{ticker}] {name}: 无avg_cost，跳过")
            continue

        live = live_prices.get(ticker, {})
        price = live.get("price")

        # 降级: 批量接口没拿到就单独重试一次
        if price is None:
            try:
                single = adl.get_single_price(ticker)
                price = single.get("price")
            except Exception:
                price = None

        # 再降级: 用portfolio_state.json里update_prices.py写入的current_price(daily_run中已在本脚本之前跑过)
        if price is None:
            price = pos.get("current_price")
            if price and verbose:
                print(f"  [{ticker}] 实时取价失败，降级用portfolio_state.json缓存价 ¥{price}")

        if price is None:
            print(f"  ⛔ [{ticker}] {name}: 无法获取任何价格(实时+缓存均失败)，无法判断灾难线，需人工检查！")
            continue

        disaster_line = round(avg_cost * DISASTER_LINE_RATIO, 4)
        breach_pct = round((price - avg_cost) / avg_cost * 100, 2)
        dist_to_disaster_pct = round((price - disaster_line) / disaster_line * 100, 2)
        breached = price <= disaster_line

        rows.append((ticker, name, avg_cost, price, disaster_line, breach_pct, dist_to_disaster_pct, breached))

        if verbose:
            status = "🚨 破线" if breached else "  安全"
            print(f"  [{status}] {ticker} {name}: 现价¥{price:.2f} | 成本¥{avg_cost:.2f} "
                  f"| 灾难线¥{disaster_line:.2f} | 距灾难线{dist_to_disaster_pct:+.2f}%")

        if breached:
            breaches.append({
                "ticker": ticker, "name": name, "avg_cost": avg_cost,
                "price": price, "disaster_line": disaster_line, "breach_pct": breach_pct,
            })

    # ── 汇总表 ─────────────────────────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print(f"  {'代码':<8}{'名称':<10}{'成本':>10}{'现价':>10}{'灾难线':>10}{'较成本%':>10}{'距灾难线%':>12}")
    print(f"{'─'*70}")
    for (ticker, name, avg_cost, price, disaster_line, breach_pct, dist_pct, breached) in rows:
        mark = " 🚨" if breached else ""
        print(f"  {ticker:<8}{name:<10}{avg_cost:>10.2f}{price:>10.2f}{disaster_line:>10.2f}"
              f"{breach_pct:>+9.2f}%{dist_pct:>+11.2f}%{mark}")
    print(f"{'─'*70}")

    # ── 醒目告警 ───────────────────────────────────────────────────────────────
    if breaches:
        print("\n")
        print("🚨" * 35)
        print("🚨" + " " * 66 + "🚨")
        print("🚨   灾难线击穿警报 — 立即人工评估执行清仓 (T18第②门,绝对地板)      🚨")
        print("🚨" + " " * 66 + "🚨")
        for b in breaches:
            line = (f"🚨   {b['ticker']} {b['name']}: 现价¥{b['price']:.2f} "
                     f"跌破灾难线¥{b['disaster_line']:.2f} (较成本{b['breach_pct']:+.2f}%)")
            print(line.ljust(70) + "🚨")
        print("🚨" + " " * 66 + "🚨")
        print("🚨   ⛔ 本脚本只告警不下单。执行:                                    🚨")
        print("🚨   uv run --script scripts/execute_trade.py sell --account cn      🚨")
        print("🚨   --ticker <代码> --all --reason \"T18第②门灾难线-12%触发\"          🚨")
        print("🚨" + " " * 66 + "🚨")
        print("🚨" * 35)
        print("\n")

        if write_signal:
            written = []
            for b in breaches:
                fpath = write_nexus_signal(
                    b["ticker"], b["name"], b["price"], b["disaster_line"],
                    b["avg_cost"], b["breach_pct"],
                )
                if fpath:
                    written.append(fpath)
            if written:
                print(f"  [nexus] 已写入 {len(written)} 个critical信号:")
                for p in written:
                    print(f"    {p.name}")
            else:
                print(f"  [nexus] 今日已发过信号（或写入失败），未重复写入")
    else:
        print(f"\n✅  无灾难线击穿 — 全部 {len(rows)} 个持仓安全")

    print(f"\n{'='*70}\n")
    return breaches


def main() -> None:
    parser = argparse.ArgumentParser(description="A股灾难线自动止损检测(avg_cost×0.88)")
    parser.add_argument("--no-signal", action="store_true", help="不写入 nexus signals/pending/")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示每只持仓详细检测过程")
    args = parser.parse_args()

    breaches = run_check(write_signal=not args.no_signal, verbose=args.verbose)
    sys.exit(len(breaches))


if __name__ == "__main__":
    main()
