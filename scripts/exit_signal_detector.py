#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2"]
# ///
"""
A股退出信号自动检测器 — exit_signal_detector.py

检测三类退出信号:
  R6c  龙头崩: 板块龙头单日跌≥5% → 全板块出场
  T11  暴力拉升止盈: 持仓单日涨>8% 或 2-3日累计>15% → 建议减半锁利
  L11  催化剂临近: 持仓催化剂在T-5天以内 → 减仓提醒

用法:
  uv run --script scripts/exit_signal_detector.py
  uv run --script scripts/exit_signal_detector.py --no-signal  # 不写nexus信号文件
  uv run --script scripts/exit_signal_detector.py --verbose    # 显示所有检测步骤
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from typing import Optional

# ── 路径 ─────────────────────────────────────────────────────────────────────
REPO         = Path(__file__).resolve().parent.parent
PORTFOLIO    = REPO / "portfolio_state.json"
PRICES_FILE  = REPO / "latest_prices.json"
NEXUS_SIGNALS = Path.home() / ".claude" / "nexus" / "signals" / "pending"

# ── 板块龙头映射 (R6c) ────────────────────────────────────────────────────────
# 格式: sector关键词 -> [(ticker, name), ...]
# 覆盖最常见的A股板块，ticker为A股6位代码供baostock/akshare查询，
# 同时附yfinance后缀供实时备用查询
SECTOR_LEADERS: dict[str, list[tuple[str, str]]] = {
    "光模块": [("300502", "新易盛"), ("300308", "中际旭创"), ("688498", "天孚通信")],
    "AI物理层": [("300502", "新易盛"), ("300308", "中际旭创")],
    "电力设备": [("002028", "思源电气"), ("601877", "正泰电器"), ("300274", "阳光电源")],
    "变压器": [("002028", "思源电气"), ("600089", "特变电工")],
    "化工": [("600309", "万华化学"), ("600160", "巨化股份"), ("002500", "山推股份")],
    "制冷剂": [("600160", "巨化股份"), ("002429", "昊华科技")],
    "半导体": [("688981", "中芯国际"), ("603986", "兆易创新"), ("688012", "中微公司")],
    "AI算力": [("688041", "海光信息"), ("603501", "韦尔股份")],
    "医药": [("600276", "恒瑞医药"), ("000661", "长春高新")],
    "新能源车": [("002594", "比亚迪"), ("300750", "宁德时代")],
    "军工": [("600673", "东方航空"), ("600760", "中航沈飞")],
}

# 触发阈值
R6C_LEADER_DROP_PCT  = -5.0   # 龙头跌幅触发线
T11_SINGLE_DAY_PCT   =  8.0   # 单日涨幅止盈线
T11_MULTI_DAY_PCT    = 15.0   # 2-3日累计涨幅线
L11_CATALYST_DAYS    =  5     # 催化剂临近天数

# ── 数据加载 ─────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict | list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def get_a_positions(portfolio: dict) -> list[dict]:
    """从 portfolio_state.json 读取A股持仓列表。"""
    try:
        return portfolio["accounts"]["a_share"]["positions"]
    except (KeyError, TypeError):
        return []


def get_cached_cn_prices(prices_file: Path) -> dict[str, dict]:
    """从 latest_prices.json 读取CN价格缓存。"""
    data = load_json(prices_file)
    return data.get("cn", {}) if isinstance(data, dict) else {}


def fetch_price_yfinance(ticker: str) -> Optional[dict]:
    """
    用yfinance获取A股价格（ticker需加 .SS 或 .SZ 后缀）。
    返回 {"price": float, "prev_close": float, "change_pct": float} 或 None。
    """
    try:
        import yfinance as yf
        suffix = ".SS" if ticker.startswith(("6", "9")) else ".SZ"
        info = yf.Ticker(ticker + suffix).fast_info
        price = float(info.last_price or 0)
        prev  = float(info.previous_close or 0)
        if price and prev:
            return {"price": price, "prev_close": prev,
                    "change_pct": round((price - prev) / prev * 100, 2)}
    except Exception:
        pass
    return None


def get_price_change(ticker: str, cn_prices: dict[str, dict],
                     *, verbose: bool = False) -> Optional[float]:
    """
    获取当日涨跌幅(%)。优先用 latest_prices.json 缓存，不足则用 yfinance。
    """
    if ticker in cn_prices:
        pct = cn_prices[ticker].get("change_pct")
        if pct is not None:
            if verbose:
                print(f"  [{ticker}] 价格来自缓存: {pct:+.2f}%")
            return float(pct)

    if verbose:
        print(f"  [{ticker}] 缓存未命中，尝试yfinance...")
    result = fetch_price_yfinance(ticker)
    if result:
        if verbose:
            print(f"  [{ticker}] yfinance: {result['change_pct']:+.2f}%")
        return result["change_pct"]
    return None


def get_multi_day_change(ticker: str, days: int = 3) -> Optional[float]:
    """
    从kline_cache读取最近N日累计涨幅。
    如果cache不可用则返回None（降级到单日检测）。
    """
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from kline_cache import get_klines
        df = get_klines(ticker, days=days + 2)
        if df is None or len(df) < days:
            return None
        # 最新N日的起始close vs 最新close
        start_price = df["Close"].iloc[-(days + 1)]
        end_price   = df["Close"].iloc[-1]
        if start_price and start_price > 0:
            return round((end_price - start_price) / start_price * 100, 2)
    except Exception:
        pass
    return None


# ── 信号生成 ─────────────────────────────────────────────────────────────────

class Signal:
    def __init__(self, rule: str, priority: str, title: str,
                 detail: str, action: str, tickers: list[str]):
        self.rule     = rule
        self.priority = priority   # critical / high / medium
        self.title    = title
        self.detail   = detail
        self.action   = action
        self.tickers  = tickers
        self.ts       = datetime.now()

    def print_line(self) -> None:
        icon = {"critical": "🔴", "high": "🟡", "medium": "🔵"}.get(self.priority, "⚪")
        print(f"\n{icon} [{self.rule}] {self.title}")
        print(f"   {self.detail}")
        print(f"   → 操作: {self.action}")

    def to_nexus_dict(self) -> dict:
        now_iso = self.ts.astimezone(timezone.utc).isoformat()
        exp_iso = (self.ts + timedelta(days=3)).astimezone(timezone.utc).isoformat()
        slug    = self.rule.lower().replace(" ", "_")
        ticker_str = "_".join(self.tickers[:2]) if self.tickers else "portfolio"
        sig_id  = f"sig-{self.ts.strftime('%Y%m%d-%H%M%S')}-exit_detector-{slug}-{ticker_str}"
        return {
            "id": sig_id,
            "from": "exit_signal_detector",
            "to": ["trading_astock"],
            "priority": self.priority,
            "type": "position_change",
            "title": self.title,
            "content": self.detail,
            "action_required": self.action,
            "source_context": f"auto-detect:{self.rule}",
            "created_at": now_iso,
            "expires_at": exp_iso,
            "lifecycle": "pending",
            "read_by": [],
            "acted_on": False,
        }


def write_nexus_signal(sig: Signal) -> Path | None:
    """将信号写入 nexus/signals/pending/。仅写 critical 和 high 级别。"""
    if sig.priority not in ("critical", "high"):
        return None
    if not NEXUS_SIGNALS.exists():
        try:
            NEXUS_SIGNALS.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
    d = sig.to_nexus_dict()
    fname = NEXUS_SIGNALS / f"{d['id']}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return fname


# ── R6c 龙头崩检测 ───────────────────────────────────────────────────────────

def _sector_key(sector: str) -> str | None:
    """匹配持仓板块到SECTOR_LEADERS中的key。返回第一个匹配的key或None。"""
    for key in SECTOR_LEADERS:
        if key in sector:
            return key
    return None


def check_r6c(positions: list[dict], cn_prices: dict[str, dict],
              *, verbose: bool = False) -> list[Signal]:
    """
    R6c龙头崩检测:
    对每个A股持仓，找其板块龙头（排除自身），检查今日涨跌幅。
    任一龙头跌幅 ≥ R6C_LEADER_DROP_PCT → 生成出场信号。
    """
    signals: list[Signal] = []
    checked_sectors: set[str] = set()   # 同一板块只告警一次

    for pos in positions:
        ticker = pos.get("ticker", "")
        name   = pos.get("name", ticker)
        sector = pos.get("sector", "")

        skey = _sector_key(sector)
        if not skey:
            if verbose:
                print(f"  [{ticker}] 板块'{sector}'未在龙头映射中，跳过R6c")
            continue
        if skey in checked_sectors:
            continue

        leaders = SECTOR_LEADERS.get(skey, [])
        # 排除自身（已持有的股票当龙头时跳过）
        own_tickers = {p.get("ticker") for p in positions}
        external_leaders = [(t, n) for t, n in leaders if t not in own_tickers]

        if verbose:
            print(f"\n  [R6c] {name} 板块='{skey}' 外部龙头={[t for t,_ in external_leaders]}")

        crashed: list[tuple[str, str, float]] = []  # (ticker, name, change_pct)
        for lticker, lname in external_leaders:
            pct = get_price_change(lticker, cn_prices, verbose=verbose)
            if pct is not None and pct <= R6C_LEADER_DROP_PCT:
                crashed.append((lticker, lname, pct))

        if crashed:
            checked_sectors.add(skey)
            # 受波及的持仓（同板块）
            affected = [p["ticker"] for p in positions
                        if p.get("sector") and skey in p.get("sector", "")]

            crashed_str = ", ".join(f"{n}({t}) {pct:+.1f}%" for t, n, pct in crashed)
            signals.append(Signal(
                rule="R6c",
                priority="critical",
                title=f"⚠ 龙头崩 | {skey}板块 | {crashed_str}",
                detail=(f"板块龙头大幅下跌: {crashed_str}\n"
                        f"受影响持仓: {', '.join(affected)}\n"
                        f"触发条件: 龙头跌幅 ≥ {abs(R6C_LEADER_DROP_PCT):.0f}%"),
                action=f"执行R6c: 立即评估 {', '.join(affected)} 出场，板块信号失效",
                tickers=affected,
            ))

    return signals


# ── T11 暴力拉升止盈检测 ──────────────────────────────────────────────────────

def check_t11(positions: list[dict], cn_prices: dict[str, dict],
              *, verbose: bool = False) -> list[Signal]:
    """
    T11暴力拉升止盈:
    单日涨 > T11_SINGLE_DAY_PCT 或 3日累计 > T11_MULTI_DAY_PCT → 止盈信号。
    """
    signals: list[Signal] = []

    for pos in positions:
        ticker   = pos.get("ticker", "")
        name     = pos.get("name", ticker)
        cost     = pos.get("avg_cost", 0)
        shares   = pos.get("shares", 0)
        mv       = pos.get("market_value", 0)

        # 单日涨幅
        single_day = get_price_change(ticker, cn_prices, verbose=verbose)

        # 3日累计涨幅（kline_cache，可能None）
        multi_day = get_multi_day_change(ticker, days=3)

        if verbose:
            print(f"  [T11] {name}: 单日={single_day}, 3日累计={multi_day}")

        triggered = False
        reason_parts: list[str] = []

        if single_day is not None and single_day >= T11_SINGLE_DAY_PCT:
            triggered = True
            reason_parts.append(f"单日涨幅 {single_day:+.2f}% ≥ {T11_SINGLE_DAY_PCT:.0f}%")

        if multi_day is not None and multi_day >= T11_MULTI_DAY_PCT:
            triggered = True
            reason_parts.append(f"3日累计 {multi_day:+.2f}% ≥ {T11_MULTI_DAY_PCT:.0f}%")

        if triggered:
            reason = " | ".join(reason_parts)
            est_half_unlock = round(mv / 2) if mv else "?"
            signals.append(Signal(
                rule="T11",
                priority="high",
                title=f"止盈窗口 | {name}({ticker}) | {reason}",
                detail=(f"暴力拉升检测: {reason}\n"
                        f"当前市值约 ¥{mv:,.0f}，建议减半约 ¥{est_half_unlock:,.0f} 锁利\n"
                        f"成本价: ¥{cost:.2f}"),
                action="建议减半锁利（按T11规则），保留半仓等催化剂延续",
                tickers=[ticker],
            ))

    return signals


# ── L11 催化剂临近减仓检测 ────────────────────────────────────────────────────

def check_l11(positions: list[dict], catalyst_calendar: list[dict],
              *, verbose: bool = False) -> list[Signal]:
    """
    L11催化剂临近:
    持仓的催化剂事件在T-5天以内 → 提醒提前减仓备事件。
    同时读取持仓自身的 next_catalyst 字段作为补充。
    """
    signals: list[Signal] = []
    today = date.today()
    cutoff = today + timedelta(days=L11_CATALYST_DAYS)

    pos_tickers = {p.get("ticker"): p for p in positions}

    for entry in catalyst_calendar:
        cat_date_str = entry.get("date", "")
        cat_ticker   = entry.get("ticker", "")
        cat_event    = entry.get("event", "")
        precommit    = entry.get("precommitted_action", "")

        if cat_ticker not in pos_tickers:
            continue
        try:
            cat_date = date.fromisoformat(cat_date_str)
        except ValueError:
            continue

        days_to_event = (cat_date - today).days
        if 0 <= days_to_event <= L11_CATALYST_DAYS:
            pos = pos_tickers[cat_ticker]
            urgency = "critical" if days_to_event <= 1 else "high"
            signals.append(Signal(
                rule="L11",
                priority=urgency,
                title=f"催化剂T-{days_to_event}天 | {pos.get('name', cat_ticker)} | {cat_event[:40]}",
                detail=(f"持仓: {pos.get('name', cat_ticker)} ({cat_ticker})\n"
                        f"事件: {cat_event}\n"
                        f"日期: {cat_date_str} (还有 {days_to_event} 天)\n"
                        f"预承诺动作: {precommit}"),
                action=(f"T-{days_to_event}: 确认预承诺动作 → {precommit}" if precommit
                        else f"T-{days_to_event}: 确认持仓规模，决定是否加减仓"),
                tickers=[cat_ticker],
            ))

        if verbose and cat_ticker in pos_tickers:
            print(f"  [L11] {cat_ticker}: {cat_event[:30]} | 距今{days_to_event}天")

    # 同时检查持仓自身的 next_catalyst 字段（如无 catalyst_calendar 条目）
    already_alerted = {s.tickers[0] for s in signals if s.rule == "L11"}
    for pos in positions:
        ticker  = pos.get("ticker", "")
        if ticker in already_alerted:
            continue
        cat_str = pos.get("next_catalyst", "")
        if not cat_str:
            continue
        # 简单日期提取：如果 next_catalyst 含 "2026-" 格式日期
        import re
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", cat_str)
        if not date_match:
            continue
        try:
            cat_date = date.fromisoformat(date_match.group(1))
        except ValueError:
            continue
        days_to_event = (cat_date - today).days
        if 0 <= days_to_event <= L11_CATALYST_DAYS:
            signals.append(Signal(
                rule="L11",
                priority="high",
                title=f"催化剂T-{days_to_event}天 | {pos.get('name', ticker)} | {cat_str[:40]}",
                detail=(f"持仓: {pos.get('name', ticker)} ({ticker})\n"
                        f"来源: next_catalyst字段\n"
                        f"日期: {cat_date} (还有 {days_to_event} 天)"),
                action=f"确认 {pos.get('name', ticker)} 催化剂动作: {pos.get('catalyst_action', '请手动确认')}",
                tickers=[ticker],
            ))

    return signals


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def run_detection(*, write_signals: bool = True, verbose: bool = False) -> int:
    """执行全部检测，返回critical信号数量。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*60}")
    print(f"  A股退出信号检测  |  {now_str}")
    print(f"{'='*60}")

    # 加载数据
    portfolio = load_json(PORTFOLIO)
    cn_prices = get_cached_cn_prices(PRICES_FILE)
    positions = get_a_positions(portfolio)
    catalyst_calendar = (portfolio.get("catalyst_calendar") or [])
    if isinstance(catalyst_calendar, dict):
        catalyst_calendar = list(catalyst_calendar.values())

    print(f"\n持仓: {len(positions)} 只 | 价格缓存: {len(cn_prices)} 条")
    if not positions:
        print("  无A股持仓，退出。")
        return 0

    for p in positions:
        pct = p.get("change_pct")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        print(f"  {p.get('ticker')} {p.get('name')} | 今日: {pct_str} | "
              f"仓位: {p.get('portfolio_pct',0)*100:.1f}%")

    if verbose:
        print("\n[详细检测过程]")

    # 执行三项检测
    all_signals: list[Signal] = []
    all_signals += check_r6c(positions, cn_prices, verbose=verbose)
    all_signals += check_t11(positions, cn_prices, verbose=verbose)
    all_signals += check_l11(positions, catalyst_calendar, verbose=verbose)

    # 输出结果
    if not all_signals:
        print(f"\n✅  无退出信号 — 全部 {len(positions)} 个持仓正常")
    else:
        critical_count = sum(1 for s in all_signals if s.priority == "critical")
        high_count     = sum(1 for s in all_signals if s.priority == "high")
        print(f"\n{'─'*60}")
        print(f"  检测到 {len(all_signals)} 个信号 "
              f"(critical={critical_count}, high={high_count})")
        print(f"{'─'*60}")
        for sig in all_signals:
            sig.print_line()

        # 写入 nexus 信号
        if write_signals:
            written: list[Path] = []
            for sig in all_signals:
                fpath = write_nexus_signal(sig)
                if fpath:
                    written.append(fpath)
            if written:
                print(f"\n  [nexus] 已写入 {len(written)} 个信号文件:")
                for p in written:
                    print(f"    {p.name}")

    print(f"\n{'='*60}\n")

    critical_signals = [s for s in all_signals if s.priority == "critical"]
    return len(critical_signals)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A股退出信号自动检测 (R6c/T11/L11)"
    )
    parser.add_argument("--no-signal", action="store_true",
                        help="不写入 nexus signals/pending/ 目录")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="显示详细检测过程")
    args = parser.parse_args()

    critical_count = run_detection(
        write_signals=not args.no_signal,
        verbose=args.verbose,
    )

    # critical 信号时以非零退出码，便于 daily_run.sh 感知
    sys.exit(1 if critical_count > 0 else 0)


if __name__ == "__main__":
    main()
