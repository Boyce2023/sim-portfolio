# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""
notifications.py — Telegram通知发送模块
供 execute_trade.py / risk_monitor.py / daily_run.sh 等脚本 import 使用。

用法（直接import）:
    from notifications import TelegramNotifier, TradeAlert, RiskAlert, DailySummary

用法（独立测试）:
    uv run --script notifications.py --test
    uv run --script notifications.py --ping
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Literal

# httpx is the only runtime dependency — lightweight, supports async
try:
    import httpx
except ImportError:
    print("[notifications] httpx not found — run: pip install httpx", file=sys.stderr)
    httpx = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("telegram.notifications")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TZ_BEIJING = timezone(timedelta(hours=8))

CONFIG_PATH = Path(__file__).parent.parent / "config" / "telegram_config.json"
DEFAULT_PORTFOLIO_PATH = Path(__file__).parent.parent / "portfolio_state.json"

TELEGRAM_API = "https://api.telegram.org"


def _load_config() -> dict:
    """Load telegram_config.json; fall back to safe defaults."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


_CFG = _load_config()


def _get_bot_token() -> str:
    env_var = _CFG.get("bot", {}).get("token_env_var", "TELEGRAM_BOT_TOKEN")
    token = os.environ.get(env_var, "")
    if not token:
        raise EnvironmentError(
            f"Telegram bot token not set. Export ${env_var} before running."
        )
    return token


def _get_chat_id() -> str:
    env_var = _CFG.get("bot", {}).get("chat_id_env_var", "TELEGRAM_CHAT_ID")
    chat_id = os.environ.get(env_var, "")
    if not chat_id:
        raise EnvironmentError(
            f"Telegram chat ID not set. Export ${env_var} before running."
        )
    return chat_id


# ---------------------------------------------------------------------------
# Message data classes
# ---------------------------------------------------------------------------

@dataclass
class TradeAlert:
    """Populated by execute_trade.py after a successful trade."""
    account: Literal["us", "cn"]
    action: Literal["buy", "sell", "short", "cover"]
    ticker: str
    name: str
    shares: float
    price: float
    reason: str
    portfolio_pct: float = 0.0
    stop_loss: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    currency: str = "USD"
    timestamp: str = field(default_factory=lambda: datetime.now(TZ_BEIJING).isoformat(timespec="seconds"))

    def format(self) -> str:
        action_map = {
            "buy":   ("🔔", "买入"),
            "sell":  ("🔔", "卖出"),
            "short": ("🩳", "做空"),
            "cover": ("✅", "平空"),
        }
        emoji, action_cn = action_map.get(self.action, ("🔔", self.action.upper()))
        account_label = "模拟盘A股" if self.account == "cn" else "模拟盘美股"
        currency_sym = "¥" if self.currency == "CNY" else "$"

        lines = [
            f"{emoji} <b>{account_label}交易</b>",
            f"{action_cn} {self.name}({self.ticker}) {self.shares}股 @{currency_sym}{self.price:.2f}",
            f"仓位: {self.portfolio_pct:.1%} | 理由: {self.reason}",
        ]
        if self.stop_loss is not None and self.stop_loss_pct is not None:
            lines.append(
                f"止损: {currency_sym}{self.stop_loss:.2f} ({self.stop_loss_pct:+.1%})"
            )
        if self.target_1 is not None:
            t = f"目标1: {currency_sym}{self.target_1:.2f}"
            if self.target_2 is not None:
                t += f" | 目标2: {currency_sym}{self.target_2:.2f}"
            lines.append(t)
        lines.append(f"<i>{self.timestamp}</i>")
        return "\n".join(lines)


@dataclass
class RiskAlert:
    """Populated by risk_monitor.py when thresholds are breached."""
    level: Literal["INFO", "WARNING", "HIGH", "CRITICAL", "EMERGENCY"]
    title: str
    details: list[str]
    drawdown_pct: Optional[float] = None
    circuit_breaker_triggered: bool = False
    recommended_action: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(TZ_BEIJING).isoformat(timespec="seconds"))

    def format(self) -> str:
        level_emoji = {
            "INFO":      "ℹ️",
            "WARNING":   "⚠️",
            "HIGH":      "🔴",
            "CRITICAL":  "🚨",
            "EMERGENCY": "🆘",
        }.get(self.level, "⚠️")

        lines = [
            f"{level_emoji} <b>风险警报 [{self.level}]</b>",
            f"<b>{self.title}</b>",
        ]
        for d in self.details:
            lines.append(f"  • {d}")

        if self.drawdown_pct is not None:
            lines.append(f"回撤: {self.drawdown_pct:+.2f}% (from peak)")

        if self.circuit_breaker_triggered:
            lines.append("🛑 <b>Circuit Breaker 触发</b>")

        if self.recommended_action:
            lines.append(f"建议: {self.recommended_action}")

        lines.append(f"<i>{self.timestamp}</i>")
        return "\n".join(lines)


@dataclass
class DailySummary:
    """Built by the daily_run pipeline after price fetch + performance calc."""
    date: str
    cn_nav: float
    cn_return_pct: float
    cn_benchmark_pct: Optional[float]   # CSI300
    us_nav: float
    us_return_pct: float
    us_benchmark_pct: Optional[float]   # SPY
    trade_count: int = 0
    stop_loss_triggered: int = 0
    catalysts_upcoming: list[dict] = field(default_factory=list)  # [{date, ticker, event}]
    notes: Optional[str] = None

    def format(self) -> str:
        today = self.date or datetime.now(TZ_BEIJING).strftime("%Y-%m-%d")

        def pct_str(v: Optional[float]) -> str:
            if v is None:
                return "N/A"
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:.2f}%"

        def vs_bench(portfolio: float, bench: Optional[float]) -> str:
            if bench is None:
                return ""
            diff = portfolio - bench
            sign = "+" if diff >= 0 else ""
            return f" (vs 基准 {sign}{diff:.2f}%)"

        lines = [
            f"📊 <b>日报 | {today}</b>",
            "",
            f"🇨🇳 A股: ¥{self.cn_nav:,.0f} ({pct_str(self.cn_return_pct)}){vs_bench(self.cn_return_pct, self.cn_benchmark_pct)}",
            f"🇺🇸 美股: ${self.us_nav:,.0f} ({pct_str(self.us_return_pct)}){vs_bench(self.us_return_pct, self.us_benchmark_pct)}",
            f"交易: {self.trade_count}笔 | 止损触发: {self.stop_loss_triggered}",
        ]

        if self.catalysts_upcoming:
            lines.append("")
            lines.append("📅 <b>近期催化剂</b>")
            for cat in self.catalysts_upcoming[:5]:
                lines.append(f"  {cat['date']} {cat['ticker']}: {cat['event']}")

        if self.notes:
            lines.append("")
            lines.append(f"📝 {self.notes}")

        return "\n".join(lines)


@dataclass
class NewsAlert:
    """Populated by news_scan.py or external news pipeline when a relevant story is detected."""
    headline: str
    source: str           # bloomberg, cnbc, reuters, cls, eastmoney
    tickers: list[str]
    catalyst_type: str    # earnings, policy, upgrade, downgrade, m&a, macro, guidance, product
    urgency: str          # critical, breaking, important
    matched_positions: list[str]  # tickers that match current holdings
    recommended_action: str
    url: str
    timestamp: str = field(default_factory=lambda: datetime.now(TZ_BEIJING).isoformat(timespec="seconds"))

    def format(self) -> str:
        if self.urgency == "critical":
            urgency_emoji = "🔴"
            urgency_label = "BREAKING NEWS"
        elif self.urgency == "breaking":
            urgency_emoji = "🔴"
            urgency_label = "BREAKING NEWS"
        else:
            urgency_emoji = "🟡"
            urgency_label = "IMPORTANT"

        matched_str = ", ".join(self.matched_positions) if self.matched_positions else "无持仓匹配"

        lines = [
            f"{urgency_emoji} <b>{urgency_label}</b>",
            f"📰 {self.headline}",
            f"📊 Source: {self.source} | {self.timestamp}",
            f"🎯 持仓匹配: {matched_str}",
            f"💡 催化剂类型: {self.catalyst_type}",
            f"⚡ 建议: {self.recommended_action}",
            f"🔗 {self.url}",
        ]
        return "\n".join(lines)


@dataclass
class AgentMessage:
    """Agent-to-agent async message — pushed via Telegram as notification layer."""
    msg_id: str
    from_session: str
    to_sessions: list[str]
    subject: str
    body: str
    priority: str = "medium"
    reply_to: str = ""

    def format(self) -> str:
        icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
        icon = icons.get(self.priority, "🔵")
        to_str = ", ".join(self.to_sessions)
        lines = [
            f"💬 <b>Agent消息</b>",
            f"{icon} {self.subject}",
            f"👤 {self.from_session} → {to_str}",
            f"📝 {self.body[:500]}",
        ]
        if self.reply_to:
            lines.append(f"↩️ 回复: <code>{self.reply_to}</code>")
        lines.append(f"🔖 ID: <code>{self.msg_id}</code>")
        return "\n".join(lines)


@dataclass
class SystemChangeAlert:
    """Cross-session system change notification — pushed via Telegram for real-time delivery."""
    entry_id: str
    from_session: str
    target_sessions: list[str]
    title: str
    summary: str
    changes: list[str]
    priority: str = "medium"
    action_required: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(TZ_BEIJING).isoformat(timespec="seconds"))

    def format(self) -> str:
        icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
        icon = icons.get(self.priority, "🔵")
        targets = ", ".join(self.target_sessions)

        lines = [
            f"{icon} <b>系统变更通知</b>",
            f"📋 {self.title}",
            f"👤 来自: {self.from_session} → {targets}",
            f"📝 {self.summary}",
            "",
        ]
        for c in self.changes[:8]:
            lines.append(f"  • {c}")
        if len(self.changes) > 8:
            lines.append(f"  ... 共{len(self.changes)}项变更")
        if self.action_required:
            lines.append(f"\n⚡ <b>建议操作:</b> {self.action_required}")
        lines.append(f"\n🔖 ID: <code>{self.entry_id}</code>")
        lines.append("其他session启动时将自动确认此变更。")
        return "\n".join(lines)


@dataclass
class WeeklySummary:
    """Weekly commentary, simplified version of weekly_commentary.py output."""
    week_start: str
    week_end: str
    cn_return_pct: float
    us_return_pct: float
    total_trades: int
    top_performers: list[dict]   # [{ticker, name, return_pct}]
    worst_performers: list[dict]
    key_lessons: list[str]
    next_week_focus: list[str]

    def format(self) -> str:
        lines = [
            f"📈 <b>周报 | {self.week_start} ~ {self.week_end}</b>",
            "",
            f"A股周收益: {self.cn_return_pct:+.2f}%",
            f"美股周收益: {self.us_return_pct:+.2f}%",
            f"本周交易: {self.total_trades}笔",
        ]

        if self.top_performers:
            lines.append("")
            lines.append("🏆 <b>本周最佳</b>")
            for p in self.top_performers[:3]:
                lines.append(f"  {p['ticker']} {p['name']}: {p['return_pct']:+.1f}%")

        if self.worst_performers:
            lines.append("")
            lines.append("📉 <b>本周最弱</b>")
            for p in self.worst_performers[:3]:
                lines.append(f"  {p['ticker']} {p['name']}: {p['return_pct']:+.1f}%")

        if self.key_lessons:
            lines.append("")
            lines.append("💡 <b>本周复盘</b>")
            for lesson in self.key_lessons:
                lines.append(f"  • {lesson}")

        if self.next_week_focus:
            lines.append("")
            lines.append("🎯 <b>下周关注</b>")
            for item in self.next_week_focus:
                lines.append(f"  • {item}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core notifier
# ---------------------------------------------------------------------------

class TelegramNotifier:
    """
    Async-first notifier. Use `send_async` inside async contexts,
    or `send` (sync wrapper) for simple scripts.

    Usage:
        notifier = TelegramNotifier()
        notifier.send(TradeAlert(...))

        # Fire-and-forget from sync code:
        notifier.send_nowait(alert)
    """

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        parse_mode: str = "HTML",
        timeout: int = 10,
        retry_attempts: int = 3,
        retry_delay: float = 2.0,
        dry_run: bool = False,
    ):
        self._token = token or _get_bot_token()
        self._chat_id = chat_id or _get_chat_id()
        self._parse_mode = parse_mode
        self._timeout = timeout
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay
        self._dry_run = dry_run

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send(self, payload: "TradeAlert | RiskAlert | DailySummary | WeeklySummary | NewsAlert | str") -> bool:
        """Synchronous send. Returns True on success."""
        text = payload if isinstance(payload, str) else payload.format()
        return asyncio.run(self._send_with_retry(text))

    def send_nowait(self, payload: "TradeAlert | RiskAlert | DailySummary | WeeklySummary | NewsAlert | str") -> None:
        """
        Fire-and-forget: schedule send in background without blocking the caller.
        Safe to call from sync scripts where you don't care about the result.
        """
        text = payload if isinstance(payload, str) else payload.format()
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._send_with_retry(text))
            else:
                asyncio.run(self._send_with_retry(text))
        except Exception as exc:
            logger.warning("send_nowait failed to schedule: %s", exc)

    async def send_async(
        self,
        payload: "TradeAlert | RiskAlert | DailySummary | WeeklySummary | NewsAlert | str",
    ) -> bool:
        """Async send — use inside async contexts."""
        text = payload if isinstance(payload, str) else payload.format()
        return await self._send_with_retry(text)

    def send_news_alert(self, alert: "NewsAlert") -> bool:
        """Convenience wrapper for sending a NewsAlert synchronously."""
        return self.send(alert)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _send_with_retry(self, text: str) -> bool:
        if self._dry_run:
            logger.info("[DRY RUN] Would send:\n%s", text)
            return True

        if httpx is None:
            logger.error("httpx not installed — cannot send Telegram message")
            return False

        url = f"{TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text[:4096],   # Telegram hard limit
            "parse_mode": self._parse_mode,
            "disable_web_page_preview": True,
        }

        for attempt in range(1, self._retry_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("ok"):
                            logger.info("Telegram message sent (message_id=%s)", data["result"].get("message_id"))
                            return True
                        else:
                            logger.warning("Telegram API returned ok=false: %s", data)
                    elif resp.status_code == 429:
                        # Rate limited — respect Retry-After header
                        retry_after = float(resp.headers.get("Retry-After", self._retry_delay * attempt))
                        logger.warning("Rate limited — waiting %.1fs", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    else:
                        logger.warning("Telegram API HTTP %s: %s", resp.status_code, resp.text[:200])
            except httpx.TimeoutException:
                logger.warning("Attempt %d/%d timed out", attempt, self._retry_attempts)
            except Exception as exc:
                logger.warning("Attempt %d/%d failed: %s", attempt, self._retry_attempts, exc)

            if attempt < self._retry_attempts:
                await asyncio.sleep(self._retry_delay * attempt)

        logger.error("All %d send attempts failed", self._retry_attempts)
        return False


# ---------------------------------------------------------------------------
# Portfolio query helpers (used by bot.py command handlers)
# ---------------------------------------------------------------------------

def load_portfolio(path: Optional[Path] = None) -> dict:
    """Load portfolio_state.json. Returns empty dict on error."""
    fpath = path or Path(_CFG.get("portfolio", {}).get("state_file", str(DEFAULT_PORTFOLIO_PATH)))
    try:
        with open(fpath, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Cannot load portfolio: %s", exc)
        return {}


def format_status_message(portfolio: dict) -> str:
    """Format /status command response from portfolio_state.json."""
    if not portfolio:
        return "❌ 无法读取持仓数据"

    now = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d %H:%M BJT")
    a = portfolio.get("accounts", {}).get("a_share", {})
    u = portfolio.get("accounts", {}).get("us", {})

    def pct_str(v):
        if v is None:
            return "N/A"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    def nav_return(acc: dict, currency: str) -> str:
        nav = acc.get("total_assets", 0)
        init = acc.get("initial_capital", 1)
        ret = (nav / init - 1) * 100 if init else 0
        sym = "¥" if currency == "CNY" else "$"
        return f"{sym}{nav:,.0f} ({pct_str(ret)})"

    lines = [
        f"📊 <b>持仓状态 | {now}</b>",
        "",
        f"🇨🇳 A股 NAV: {nav_return(a, 'CNY')}",
        f"   现金: ¥{a.get('cash', 0):,.0f} | 持仓数: {len(a.get('positions', []))}",
        f"🇺🇸 美股 NAV: {nav_return(u, 'USD')}",
        f"   现金: ${u.get('cash', 0):,.0f} | 持仓数: {len(u.get('positions', []))}",
    ]

    # Top positions
    all_pos = []
    for p in a.get("positions", []):
        all_pos.append(("CN", p))
    for p in u.get("positions", []):
        all_pos.append(("US", p))

    if all_pos:
        lines.append("")
        lines.append("<b>主要持仓</b>")
        for market, p in sorted(all_pos, key=lambda x: abs(x[1].get("portfolio_pct", 0)), reverse=True)[:6]:
            name = p.get("name", p.get("ticker", ""))
            pct = p.get("portfolio_pct", 0)
            upnl = p.get("unrealized_pnl_pct", 0)
            lines.append(f"  {name}({p['ticker']}): {pct:.1%} | P&L {pct_str(upnl)}")

    return "\n".join(lines)


def format_trades_message(portfolio: dict, n: int = 5) -> str:
    """Format /trades command — last N trades from audit trail."""
    if not portfolio:
        return "❌ 无法读取交易记录"

    audit_dir = Path(_CFG.get("portfolio", {}).get("state_file", "")).parent.parent / "audit-trail"
    trades = []
    if audit_dir.exists():
        for f in sorted(audit_dir.glob("*.json"), reverse=True)[:20]:
            try:
                with open(f) as fp:
                    t = json.load(fp)
                trades.append(t)
            except Exception:
                continue

    if not trades:
        return "📋 暂无交易记录"

    lines = [f"📋 <b>最近 {min(n, len(trades))} 笔交易</b>", ""]
    for t in trades[:n]:
        action = t.get("action", "")
        ticker = t.get("ticker", "")
        shares = t.get("shares", 0)
        price = t.get("price", 0)
        account = t.get("account", "")
        ts = t.get("timestamp", "")[:10]
        sym = "¥" if account == "cn" else "$"
        action_map = {"buy": "买入", "sell": "卖出", "short": "做空", "cover": "平空"}
        lines.append(f"  {ts} {action_map.get(action, action)} {ticker} {shares}股 @{sym}{price:.2f}")

    return "\n".join(lines)


def format_catalyst_message(portfolio: dict, days: int = 7) -> str:
    """Format /catalyst command from watchlist_config.json catalysts."""
    wl_path = Path(_CFG.get("portfolio", {}).get("watchlist_file", ""))
    catalysts = []

    if wl_path.exists():
        try:
            with open(wl_path, encoding="utf-8") as f:
                wl = json.load(f)
            for section in ["us_watchlist", "cn_watchlist"]:
                for item in wl.get(section, []):
                    cat = item.get("next_catalyst")
                    cat_date = item.get("catalyst_date", "")
                    if cat and cat_date:
                        catalysts.append({
                            "date": cat_date,
                            "ticker": item.get("ticker", ""),
                            "event": cat,
                        })
        except Exception as exc:
            logger.warning("Cannot read watchlist: %s", exc)

    # Also read from portfolio positions
    for account_key in ["a_share", "us"]:
        for p in portfolio.get("accounts", {}).get(account_key, {}).get("positions", []):
            cat = p.get("next_catalyst")
            cat_date = ""
            # Parse date from catalyst text if embedded
            if cat:
                catalysts.append({
                    "date": cat_date or "TBD",
                    "ticker": p.get("ticker", ""),
                    "event": cat,
                })

    if not catalysts:
        return "📅 未来7天无已记录催化剂"

    # Sort by date, known dates first
    catalysts.sort(key=lambda x: x["date"] if x["date"] != "TBD" else "9999")

    lines = [f"📅 <b>催化剂日历 (未来{days}天)</b>", ""]
    for cat in catalysts[:10]:
        lines.append(f"  {cat['date']} {cat['ticker']}: {cat['event']}")

    return "\n".join(lines)


def format_risk_message() -> str:
    """Format /risk command — run risk_monitor and parse output."""
    import subprocess
    scripts_dir = Path(_CFG.get("portfolio", {}).get("scripts_dir", ""))
    uv = _CFG.get("portfolio", {}).get("uv_path", "uv")

    risk_script = scripts_dir / "risk_monitor.py"
    if not risk_script.exists():
        return "❌ risk_monitor.py 未找到"

    try:
        result = subprocess.run(
            [uv, "run", "--script", str(risk_script), "--no-save"],
            capture_output=True, text=True, timeout=60
        )
        # Strip ANSI codes and rich formatting for Telegram
        import re
        text = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        # Keep first 3000 chars
        text = text[:3000] if text else result.stderr[:1000]
        return f"<pre>{text}</pre>" if text else "⚠️ 风控报告为空"
    except subprocess.TimeoutExpired:
        return "⏱ risk_monitor.py 超时（>60s）"
    except Exception as exc:
        return f"❌ 运行风控脚本失败: {exc}"


# ---------------------------------------------------------------------------
# CLI entry point for testing
# ---------------------------------------------------------------------------

def _run_tests():
    """Quick smoke-test: print formatted messages without sending."""
    print("=== TradeAlert ===")
    alert = TradeAlert(
        account="us", action="buy", ticker="FPS", name="Federal Power Systems",
        shares=80, price=44.68, reason="DC电气配电IPO",
        portfolio_pct=0.024, stop_loss=37.98, stop_loss_pct=-0.15,
        target_1=55.0, currency="USD"
    )
    print(alert.format())

    print("\n=== RiskAlert ===")
    risk = RiskAlert(
        level="HIGH", title="美股组合回撤: -3.2% (from peak)",
        details=["NVDA距止损仅3.5%", "现金比例: 18.5% (低于20%下限)"],
        drawdown_pct=-3.2, recommended_action="暂停新建仓"
    )
    print(risk.format())

    print("\n=== DailySummary ===")
    summary = DailySummary(
        date="2026-05-21",
        cn_nav=1027181, cn_return_pct=2.72, cn_benchmark_pct=0.36,
        us_nav=148498, us_return_pct=-1.0, us_benchmark_pct=0.21,
        trade_count=0, stop_loss_triggered=0,
        catalysts_upcoming=[
            {"date": "2026-05-28", "ticker": "NVDA", "event": "Q1 FY2027财报 AMC盘后"},
            {"date": "2026-06-08", "ticker": "AAPL", "event": "WWDC 2026"},
        ]
    )
    print(summary.format())


def _run_ping():
    """Send a test ping to Telegram."""
    notifier = TelegramNotifier()
    ok = notifier.send("🟢 <b>Telegram Alert Bot 连接测试</b>\n通知模块运行正常。")
    print("Ping sent:", ok)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Telegram notifications module")
    parser.add_argument("--test", action="store_true", help="Print sample formatted messages")
    parser.add_argument("--ping", action="store_true", help="Send a test ping to Telegram")
    args = parser.parse_args()

    if args.test:
        _run_tests()
    elif args.ping:
        _run_ping()
    else:
        parser.print_help()
