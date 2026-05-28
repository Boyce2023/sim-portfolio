# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
周报自动生成系统 — Claude AI模拟盘
读取 portfolio_state.json + daily-reviews/ 目录，生成Markdown/Twitter/微博三种格式周报。

用法:
  uv run --script scripts/weekly_commentary.py                           # 本周
  uv run --script scripts/weekly_commentary.py --week 2026-05-18        # 指定周起始日
  uv run --script scripts/weekly_commentary.py --format twitter          # Twitter版
  uv run --script scripts/weekly_commentary.py --format weibo            # 微博版
  uv run --script scripts/weekly_commentary.py --output weekly-reports/  # 写文件
  uv run --script scripts/weekly_commentary.py --all-formats             # 生成全部格式
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio_state.json"
REVIEWS_DIR = PROJECT_ROOT / "daily-reviews"

# ──────────────────────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    """加载唯一真相源。"""
    if not PORTFOLIO_PATH.exists():
        sys.exit(f"[ERROR] 找不到 {PORTFOLIO_PATH}。请在 sim-portfolio/ 目录下运行。")
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_daily_review(d: date) -> Optional[str]:
    """读取某日复盘Markdown，不存在则返回None。"""
    path = REVIEWS_DIR / f"{d.isoformat()}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 周范围计算
# ──────────────────────────────────────────────────────────────────────────────

def compute_week_range(week_start_str: Optional[str]) -> tuple[date, date]:
    """
    返回 (week_start, week_end)。
    week_end = min(week_start + 6天, today)，避免引用未来数据。
    """
    if week_start_str:
        week_start = date.fromisoformat(week_start_str)
    else:
        today = date.today()
        # 回退到本周一（weekday 0=Monday）
        week_start = today - timedelta(days=today.weekday())

    week_end = min(week_start + timedelta(days=6), date.today())
    return week_start, week_end


def week_number(week_start: date, portfolio_start_str: str) -> int:
    """从模拟盘start_date算起，本周是第几周（从1开始）。"""
    portfolio_start = date.fromisoformat(portfolio_start_str)
    delta = (week_start - portfolio_start).days
    return max(1, delta // 7 + 1)


# ──────────────────────────────────────────────────────────────────────────────
# 数据提取辅助函数
# ──────────────────────────────────────────────────────────────────────────────

def snapshots_in_range(snapshots: list[dict], start: date, end: date) -> list[dict]:
    """过滤出date在[start, end]区间的日度快照。"""
    result = []
    for s in snapshots:
        try:
            d = date.fromisoformat(s["date"])
            if start <= d <= end:
                result.append(s)
        except (KeyError, ValueError):
            pass
    return sorted(result, key=lambda x: x["date"])


def trades_in_range(trade_log: list[dict], start: date, end: date) -> list[dict]:
    """过滤出timestamp在[start, end]区间的交易记录。"""
    result = []
    for t in trade_log:
        try:
            ts = datetime.fromisoformat(t["timestamp"])
            d = ts.date()
            if start <= d <= end:
                result.append(t)
        except (KeyError, ValueError):
            pass
    return sorted(result, key=lambda x: x["timestamp"])


def get_benchmark_return(snapshots: list[dict], field: str) -> Optional[float]:
    """
    从快照列表中取基准累计收益率（用最后一天的snapshot字段）。
    field: 'sse_return_pct' 或 'spy_return_pct'
    """
    # 用最后一天有值的快照
    for s in reversed(snapshots):
        val = s.get(field)
        if val is not None:
            return val
    return None


def nav_at(snapshots: list[dict], field: str, fallback: Optional[float] = None) -> Optional[float]:
    """取最后一天快照的指定字段。"""
    for s in reversed(snapshots):
        val = s.get(field)
        if val is not None:
            return val
    return fallback


# ──────────────────────────────────────────────────────────────────────────────
# 持仓变动分析
# ──────────────────────────────────────────────────────────────────────────────

def classify_trades(trades: list[dict]) -> dict[str, list[str]]:
    """
    分析本周交易，返回:
      new_positions: 新建仓
      add_positions: 加仓
      reduce_positions: 减仓/止损
    """
    buys: dict[str, int] = {}    # ticker -> total buy shares
    sells: dict[str, int] = {}   # ticker -> total sell shares

    for t in trades:
        ticker = t.get("ticker", "?")
        shares = t.get("shares", 0)
        action = t.get("action", "")
        if action in ("buy",):
            buys[ticker] = buys.get(ticker, 0) + shares
        elif action in ("sell", "short"):
            sells[ticker] = sells.get(ticker, 0) + shares

    new_positions = []
    add_positions = []
    reduce_positions = list(sells.keys())

    for ticker, _ in buys.items():
        if ticker not in sells:
            # 粗略判断：如果该ticker之前已有卖出记录，归加仓；否则看是否是新仓
            # 依据trade_log里第一条buy判断
            first_buy = next(
                (t for t in trades if t.get("ticker") == ticker and t.get("action") == "buy"),
                None,
            )
            if first_buy:
                reason = first_buy.get("reason", "")
                if "新建仓" in reason or "首次" in reason or first_buy == trades[0]:
                    new_positions.append(ticker)
                else:
                    add_positions.append(ticker)

    return {
        "new_positions": new_positions,
        "add_positions": add_positions,
        "reduce_positions": reduce_positions,
    }


def find_closest_to_stop(positions: list[dict]) -> Optional[tuple[str, float]]:
    """返回 (ticker, distance_pct)，distance = (current - stop_loss) / current。"""
    closest = None
    min_dist = float("inf")
    for p in positions:
        price = p.get("current_price") or p.get("avg_cost")
        stop = p.get("stop_loss")
        if price and stop:
            dist_pct = (price - stop) / price * 100
            if dist_pct < min_dist:
                min_dist = dist_pct
                closest = (p.get("ticker", "?"), dist_pct)
    return closest


def max_position(positions: list[dict]) -> Optional[tuple[str, float]]:
    """返回 (ticker, pct)，权重最大的持仓。"""
    best = None
    best_pct = 0.0
    for p in positions:
        pct = p.get("portfolio_pct", 0) or 0
        if pct > best_pct:
            best_pct = pct
            best = (p.get("ticker", "?"), pct * 100)
    return best


# ──────────────────────────────────────────────────────────────────────────────
# 周报生成：Markdown
# ──────────────────────────────────────────────────────────────────────────────

COMMENTARY_PLACEHOLDER = """\
[AI基金经理点评 — 由Claude在每周review时填写]

本周核心操作逻辑：（在此填写操作理由和市场判断）

市场观点：（在此填写对下周市场的看法和关键观察点）
"""


def build_markdown(
    state: dict,
    week_start: date,
    week_end: date,
    week_n: int,
    week_snapshots: list[dict],
    week_trades: list[dict],
) -> str:
    """生成完整Markdown周报。"""

    meta = state.get("_meta", {})
    accounts = state.get("accounts", {})
    a_acct = accounts.get("a_share", {})
    us_acct = accounts.get("us", {})
    perf = state.get("performance", {})
    catalyst_cal = state.get("catalyst_calendar_30d", [])

    # ── 日期范围 ──
    date_range = f"{week_start.strftime('%m/%d')}–{week_end.strftime('%m/%d/%Y')}"

    # ── A股绩效 ──
    a_snapshots = [
        s for s in week_snapshots if s.get("a_share_nav") is not None
    ]
    if a_snapshots:
        a_nav_end = a_snapshots[-1]["a_share_nav"]
        a_return = a_snapshots[-1].get("a_share_return_pct")
        sse_return = get_benchmark_return(a_snapshots, "sse_return_pct")
        a_alpha = (
            round(a_return - sse_return, 2)
            if a_return is not None and sse_return is not None
            else None
        )
    else:
        a_nav_end = a_acct.get("total_assets")
        a_return = perf.get("total_return_pct_cny")
        sse_return = None
        a_alpha = None

    # ── 美股绩效 ──
    us_snapshots = [
        s for s in week_snapshots if s.get("us_nav") is not None
    ]
    if us_snapshots:
        us_nav_end = us_snapshots[-1]["us_nav"]
        us_return = us_snapshots[-1].get("us_return_pct")
        spy_return = get_benchmark_return(us_snapshots, "spy_return_pct")
        us_alpha = (
            round(us_return - spy_return, 2)
            if us_return is not None and spy_return is not None
            else None
        )
    else:
        us_nav_end = us_acct.get("total_assets")
        us_return = perf.get("total_return_pct_usd")
        spy_return = None
        us_alpha = None

    # ── 综合收益（简单平均，权重相近时合理） ──
    combined_return = None
    if a_return is not None and us_return is not None:
        combined_return = round((a_return + us_return) / 2, 2)
    elif a_return is not None:
        combined_return = a_return
    elif us_return is not None:
        combined_return = us_return

    def fmt_pct(v: Optional[float], prefix: str = "") -> str:
        if v is None:
            return "N/A"
        sign = "+" if v >= 0 else ""
        return f"{prefix}{sign}{v:.2f}%"

    def fmt_nav_cny(v: Optional[float]) -> str:
        if v is None:
            return "N/A"
        return f"¥{v:,.0f}"

    def fmt_nav_usd(v: Optional[float]) -> str:
        if v is None:
            return "N/A"
        return f"${v:,.2f}"

    # ── 现金比例 ──
    a_cash_pct = a_acct.get("cash_pct", 0) * 100
    us_cash_plan = state.get("cash_plan", {})
    us_cash_pct_raw = us_cash_plan.get("cash_pct") or (
        us_acct.get("cash", 0) / us_acct.get("total_assets", 1) if us_acct.get("total_assets") else None
    )
    us_cash_pct = us_cash_pct_raw * 100 if us_cash_pct_raw else None

    # ── 最大单仓 ──
    a_positions = a_acct.get("positions", [])
    us_positions = us_acct.get("positions", [])
    all_positions = a_positions + us_positions
    max_pos = max_position(all_positions)

    # ── 距止损最近 ──
    closest_stop = find_closest_to_stop(all_positions)

    # ── 交易分类 ──
    trade_classify = classify_trades(week_trades)

    # ── 下周催化剂（30天内，仅展示week_end之后的） ──
    upcoming_catalysts = []
    for evt in catalyst_cal:
        try:
            evt_date = date.fromisoformat(evt["date"])
            if evt_date > week_end:
                upcoming_catalysts.append(evt)
        except (KeyError, ValueError):
            pass
    upcoming_catalysts = upcoming_catalysts[:5]  # 最多5条

    # ──────────────────────────────────────────────────────────────────────────
    # 拼装Markdown
    # ──────────────────────────────────────────────────────────────────────────

    lines = []
    lines.append(f"# AI模拟盘周报 | Week {week_n} ({date_range})")
    lines.append("")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 数据来源: portfolio_state.json v{meta.get('version', '?')}")
    lines.append("")

    # ── 本周表现 ──
    lines.append("## 本周表现")
    lines.append("")
    sse_str = fmt_pct(sse_return) if sse_return is not None else "N/A"
    spy_str = fmt_pct(spy_return) if spy_return is not None else "N/A"
    a_alpha_str = fmt_pct(a_alpha) if a_alpha is not None else "N/A"
    us_alpha_str = fmt_pct(us_alpha) if us_alpha is not None else "N/A"

    lines.append(
        f"- **A股**: {fmt_nav_cny(a_nav_end)} ({fmt_pct(a_return)})"
        f"  vs 上证{sse_str}  Alpha: {a_alpha_str}"
    )
    lines.append(
        f"- **美股**: {fmt_nav_usd(us_nav_end)} ({fmt_pct(us_return)})"
        f"  vs SPY {spy_str}  Alpha: {us_alpha_str}"
    )
    lines.append(f"- **综合**: {fmt_pct(combined_return)}")
    lines.append("")

    # 日度快照表（如有多天）
    if len(week_snapshots) > 1:
        lines.append("### 日度快照")
        lines.append("")
        lines.append("| 日期 | A股NAV | A股收益 | 美股NAV | 美股收益 |")
        lines.append("|------|--------|---------|---------|---------|")
        for s in week_snapshots:
            d_str = s.get("date", "?")
            a_nav_s = s.get("a_share_nav")
            a_ret_s = s.get("a_share_return_pct")
            us_nav_s = s.get("us_nav")
            us_ret_s = s.get("us_return_pct")
            lines.append(
                f"| {d_str} | {fmt_nav_cny(a_nav_s)} | {fmt_pct(a_ret_s)} "
                f"| {fmt_nav_usd(us_nav_s)} | {fmt_pct(us_ret_s)} |"
            )
        lines.append("")

    # 数据不足提示
    if len(week_snapshots) < 5:
        lines.append(
            f"> ⚠️ 数据说明: 本报告基于{len(week_snapshots)}个交易日快照"
            f"（模拟盘Day{(week_end - date.fromisoformat(meta.get('start_date', week_end.isoformat()))).days + 1}）。"
            " 数据量不足完整周，指标仅供参考。"
        )
        lines.append("")

    # ── 本周交易 ──
    lines.append(f"## 本周交易 ({len(week_trades)}笔)")
    lines.append("")
    if week_trades:
        lines.append("| 日期 | 标的 | 方向 | 价格 | 理由 |")
        lines.append("|------|------|------|------|------|")
        for t in week_trades:
            ts_str = t.get("timestamp", "?")[:10]
            ticker = t.get("ticker", "?")
            action_raw = t.get("action", "?")
            action_map = {"buy": "买入", "sell": "卖出", "short": "做空", "cover": "回补"}
            action_zh = action_map.get(action_raw, action_raw)
            price = t.get("price")
            price_str = f"¥{price:.2f}" if isinstance(price, (int, float)) else "?"
            # 根据账户调整货币符号
            if t.get("account") == "us":
                price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "?"
            reason = t.get("reason", "—")
            # 截断过长理由
            reason_short = reason[:40] + "…" if len(reason) > 40 else reason
            lines.append(f"| {ts_str} | {ticker} | {action_zh} | {price_str} | {reason_short} |")
    else:
        lines.append("_本周无交易记录_")
    lines.append("")

    # ── 持仓变动 ──
    lines.append("## 持仓变动")
    lines.append("")
    new_pos = trade_classify["new_positions"]
    add_pos = trade_classify["add_positions"]
    reduce_pos = trade_classify["reduce_positions"]
    lines.append(f"- **新建仓**: {', '.join(new_pos) if new_pos else '无'}")
    lines.append(f"- **加仓**: {', '.join(add_pos) if add_pos else '无'}")
    lines.append(f"- **减仓/止损**: {', '.join(reduce_pos) if reduce_pos else '无'}")
    lines.append("")

    # 当前持仓快照
    lines.append("### 当前持仓")
    lines.append("")
    if a_positions:
        lines.append("**A股**")
        lines.append("")
        lines.append("| 标的 | 持仓% | 累计盈亏 | 止损距离 |")
        lines.append("|------|-------|---------|---------|")
        for p in a_positions:
            name = p.get("name", p.get("ticker", "?"))
            pct_str = f"{p.get('portfolio_pct', 0) * 100:.1f}%"
            pnl_pct = p.get("unrealized_pnl_pct")
            pnl_str = fmt_pct(pnl_pct) if pnl_pct is not None else "N/A"
            price = p.get("current_price") or p.get("avg_cost", 0)
            stop = p.get("stop_loss", 0)
            stop_dist = (price - stop) / price * 100 if price else 0
            lines.append(f"| {name} | {pct_str} | {pnl_str} | {stop_dist:.1f}% |")
        lines.append("")

    if us_positions:
        lines.append("**美股**")
        lines.append("")
        lines.append("| 标的 | 持仓% | 累计盈亏 | 止损距离 |")
        lines.append("|------|-------|---------|---------|")
        for p in us_positions:
            name = p.get("ticker", "?")
            pct_str = f"{p.get('portfolio_pct', 0) * 100:.1f}%"
            pnl_pct = p.get("unrealized_pnl_pct")
            pnl_str = fmt_pct(pnl_pct) if pnl_pct is not None else "N/A"
            price = p.get("current_price") or p.get("avg_cost", 0)
            stop = p.get("stop_loss", 0)
            stop_dist = (price - stop) / price * 100 if price else 0
            lines.append(f"| {name} | {pct_str} | {pnl_str} | {stop_dist:.1f}% |")
        lines.append("")

    # ── 下周催化剂 ──
    lines.append("## 下周催化剂")
    lines.append("")
    if upcoming_catalysts:
        lines.append("| 日期 | 标的 | 事件 | 预案 |")
        lines.append("|------|------|------|------|")
        for evt in upcoming_catalysts:
            e_date = evt.get("date", "?")
            e_ticker = evt.get("ticker", "?")
            e_event = evt.get("event", "?")
            e_action = evt.get("precommitted_action", evt.get("urgency", "—"))
            # 截断
            e_event_s = e_event[:35] + "…" if len(e_event) > 35 else e_event
            e_action_s = e_action[:50] + "…" if len(e_action) > 50 else e_action
            lines.append(f"| {e_date} | {e_ticker} | {e_event_s} | {e_action_s} |")
    else:
        lines.append("_30天内无已登记催化剂_")
    lines.append("")

    # ── 风险状态 ──
    lines.append("## 风险状态")
    lines.append("")
    lines.append(
        f"- **现金比例**: A股 {a_cash_pct:.1f}% / 美股 {us_cash_pct:.1f}%"
        if us_cash_pct is not None
        else f"- **现金比例**: A股 {a_cash_pct:.1f}% / 美股 N/A"
    )
    if max_pos:
        lines.append(f"- **最大单仓**: {max_pos[0]} {max_pos[1]:.1f}%")
    else:
        lines.append("- **最大单仓**: N/A")
    if closest_stop:
        lines.append(f"- **距止损最近**: {closest_stop[0]} (距止损 {closest_stop[1]:.1f}%)")
    else:
        lines.append("- **距止损最近**: N/A")

    # 合规检查
    lines.append("")
    lines.append("### 合规检查")
    lines.append("")
    rule_comp = state.get("portfolio_summary", {}).get("rule_compliance", {})
    if rule_comp:
        for rule_name, result in rule_comp.items():
            result_str = str(result)
            if "note" in rule_name.lower():
                icon = "ℹ️"
            elif "PASS" in result_str:
                icon = "✅"
            elif "FAIL" in result_str or "WARN" in result_str:
                icon = "❌"
            else:
                icon = "ℹ️"
            lines.append(f"- {icon} **{rule_name}**: {result}")
    else:
        lines.append("_合规数据不可用_")
    lines.append("")

    # ── AI基金经理点评 ──
    lines.append("## AI基金经理点评")
    lines.append("")
    lines.append(COMMENTARY_PLACEHOLDER)

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 周报生成：Twitter版（≤280字符）
# ──────────────────────────────────────────────────────────────────────────────

def build_twitter(
    state: dict,
    week_start: date,
    week_end: date,
    week_n: int,
    week_snapshots: list[dict],
    week_trades: list[dict],
) -> str:
    """生成Twitter版周报，硬限制280字符。"""
    accounts = state.get("accounts", {})
    a_acct = accounts.get("a_share", {})
    us_acct = accounts.get("us", {})

    # 取最新快照
    a_snap = week_snapshots[-1] if week_snapshots else {}
    a_return = a_snap.get("a_share_return_pct")
    us_return = a_snap.get("us_return_pct")
    sse_r = a_snap.get("sse_return_pct")
    spy_r = a_snap.get("spy_return_pct")
    a_alpha = round(a_return - sse_r, 1) if (a_return is not None and sse_r is not None) else None
    us_alpha = round(us_return - spy_r, 1) if (us_return is not None and spy_r is not None) else None

    def sign(v: Optional[float]) -> str:
        if v is None:
            return "N/A"
        return f"{'+'if v>=0 else ''}{v:.1f}%"

    trade_count = len(week_trades)
    date_str = f"{week_start.strftime('%m/%d')}–{week_end.strftime('%m/%d')}"

    # 核心持仓（最强的2个）
    all_positions = a_acct.get("positions", []) + us_acct.get("positions", [])
    top2 = sorted(
        [p for p in all_positions if p.get("unrealized_pnl_pct") is not None],
        key=lambda p: p.get("unrealized_pnl_pct", 0),
        reverse=True,
    )[:2]
    top2_str = " | ".join(
        f"{p.get('ticker',p.get('name','?'))} {sign(p.get('unrealized_pnl_pct'))}"
        for p in top2
    )

    lines = [
        f"🤖 AI模拟盘 W{week_n} ({date_str})",
        f"🇨🇳 A股 {sign(a_return)} | Alpha {sign(a_alpha)} vs 上证",
        f"🇺🇸 美股 {sign(us_return)} | Alpha {sign(us_alpha)} vs SPY",
        f"📊 本周 {trade_count} 笔交易",
    ]
    if top2_str:
        lines.append(f"🏆 {top2_str}")
    lines.append("#AI投资 #模拟盘 #量化")

    text = "\n".join(lines)
    if len(text) > 280:
        # 截断到280字符
        text = text[:277] + "..."
    return text


# ──────────────────────────────────────────────────────────────────────────────
# 周报生成：微博版（≤140字中文）
# ──────────────────────────────────────────────────────────────────────────────

def build_weibo(
    state: dict,
    week_start: date,
    week_end: date,
    week_n: int,
    week_snapshots: list[dict],
    week_trades: list[dict],
) -> str:
    """生成微博版周报，硬限制140字。"""
    accounts = state.get("accounts", {})
    a_acct = accounts.get("a_share", {})
    us_acct = accounts.get("us", {})

    a_snap = week_snapshots[-1] if week_snapshots else {}
    a_return = a_snap.get("a_share_return_pct")
    us_return = a_snap.get("us_return_pct")
    sse_r = a_snap.get("sse_return_pct")
    spy_r = a_snap.get("spy_return_pct")
    a_alpha = round(a_return - sse_r, 1) if (a_return is not None and sse_r is not None) else None
    us_alpha = round(us_return - spy_r, 1) if (us_return is not None and spy_r is not None) else None

    def sign(v: Optional[float], unit: str = "%") -> str:
        if v is None:
            return "N/A"
        return f"{'+'if v>=0 else ''}{v:.1f}{unit}"

    trade_count = len(week_trades)
    date_str = f"{week_start.strftime('%m/%d')}~{week_end.strftime('%m/%d')}"

    # 最强持仓
    all_positions = a_acct.get("positions", []) + us_acct.get("positions", [])
    top1 = sorted(
        [p for p in all_positions if p.get("unrealized_pnl_pct") is not None],
        key=lambda p: p.get("unrealized_pnl_pct", 0),
        reverse=True,
    )[:1]
    top1_str = (
        f"最强{top1[0].get('ticker', top1[0].get('name','?'))} {sign(top1[0].get('unrealized_pnl_pct'))}"
        if top1
        else ""
    )

    text = (
        f"【AI模拟盘 第{week_n}周 {date_str}】"
        f"A股{sign(a_return)} vs上证Alpha{sign(a_alpha)}｜"
        f"美股{sign(us_return)} vs SPY Alpha{sign(us_alpha)}｜"
        f"本周{trade_count}笔交易"
    )
    if top1_str:
        text += f"｜{top1_str}"
    text += " #AI基金 #模拟投资"

    if len(text) > 140:
        text = text[:137] + "..."
    return text


# ──────────────────────────────────────────────────────────────────────────────
# 主程序
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI模拟盘周报自动生成",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              uv run --script scripts/weekly_commentary.py
              uv run --script scripts/weekly_commentary.py --week 2026-05-18
              uv run --script scripts/weekly_commentary.py --format twitter
              uv run --script scripts/weekly_commentary.py --format weibo
              uv run --script scripts/weekly_commentary.py --output weekly-reports/
              uv run --script scripts/weekly_commentary.py --all-formats
        """),
    )
    parser.add_argument(
        "--week",
        default=None,
        metavar="YYYY-MM-DD",
        help="周报起始日期（默认本周一）",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "twitter", "weibo"],
        default="markdown",
        help="输出格式（默认 markdown）",
    )
    parser.add_argument(
        "--all-formats",
        action="store_true",
        help="生成所有格式",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="DIR",
        help="写入目录（不指定则输出到stdout）",
    )
    args = parser.parse_args()

    # 加载数据
    state = load_portfolio()
    meta = state.get("_meta", {})
    portfolio_start = meta.get("start_date", "2026-05-18")

    # 周范围
    week_start, week_end = compute_week_range(args.week)
    week_n = week_number(week_start, portfolio_start)

    # 过滤本周数据
    all_snapshots = state.get("performance", {}).get("daily_snapshots", [])
    week_snapshots = snapshots_in_range(all_snapshots, week_start, week_end)
    all_trades = state.get("trade_log", [])
    week_trades = trades_in_range(all_trades, week_start, week_end)

    print(
        f"[Info] 周报范围: {week_start} ~ {week_end}  第{week_n}周  "
        f"快照:{len(week_snapshots)}天  交易:{len(week_trades)}笔",
        file=sys.stderr,
    )

    # 确定要生成的格式
    formats_to_gen: list[str]
    if args.all_formats:
        formats_to_gen = ["markdown", "twitter", "weibo"]
    else:
        formats_to_gen = [args.format]

    # 构建输出目录
    output_dir: Optional[Path] = None
    if args.output:
        output_dir = Path(args.output)
        if not output_dir.is_absolute():
            output_dir = PROJECT_ROOT / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

    # 生成并输出
    for fmt in formats_to_gen:
        if fmt == "markdown":
            content = build_markdown(
                state, week_start, week_end, week_n, week_snapshots, week_trades
            )
            ext = "md"
        elif fmt == "twitter":
            content = build_twitter(
                state, week_start, week_end, week_n, week_snapshots, week_trades
            )
            ext = "twitter.txt"
        else:  # weibo
            content = build_weibo(
                state, week_start, week_end, week_n, week_snapshots, week_trades
            )
            ext = "weibo.txt"

        if output_dir:
            filename = f"week{week_n:02d}-{week_start.isoformat()}.{ext}"
            out_path = output_dir / filename
            out_path.write_text(content, encoding="utf-8")
            print(f"[Output] {out_path}", file=sys.stderr)
        else:
            if len(formats_to_gen) > 1:
                sep = "=" * 60
                print(f"\n{sep}")
                print(f"  FORMAT: {fmt.upper()}")
                print(f"{sep}\n")
            print(content)


if __name__ == "__main__":
    main()
