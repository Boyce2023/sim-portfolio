#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["python-telegram-bot>=21.0", "httpx>=0.27"]
# ///
"""
bot.py — Claude模拟盘 Telegram Bot v2.0

A股(¥10M) + 美股($1.5M) 双市场模拟盘的控制中心。
查询持仓/风控/交易记录 + Agent间异步通信 + 系统管理。

启动:
    export TELEGRAM_BOT_TOKEN=xxx
    export TELEGRAM_CHAT_ID=xxx
    uv run bot.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, time as dtime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
try:
    from telegram import Update, BotCommand
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    from telegram.constants import ParseMode
    from telegram.error import TelegramError
except ImportError:
    print(
        "python-telegram-bot not installed.\n"
        "Run: pip install 'python-telegram-bot>=21.0'",
        file=sys.stderr,
    )
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from notifications import (
    TelegramNotifier,
    TradeAlert,
    RiskAlert,
    DailySummary,
    NewsAlert,
    load_portfolio,
    format_status_message,
    format_trades_message,
    format_catalyst_message,
    format_risk_message,
    _CFG,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("telegram.bot")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TZ_BEIJING = timezone(timedelta(hours=8))
REPO_ROOT = Path(__file__).parent.parent

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_allowed_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", CHAT_ID)
ALLOWED_CHAT_IDS: set[int] = {
    int(cid.strip()) for cid in _allowed_raw.split(",") if cid.strip().lstrip("-").isdigit()
}

_notif_cfg = _CFG.get("notifications", {})
_DAILY_CFG = _notif_cfg.get("daily_summary", {})
_RISK_CFG = _notif_cfg.get("risk_alerts", {})

SESSION_ALIASES = {
    "astock": "trading_astock", "a股": "trading_astock", "cn": "trading_astock",
    "us": "trading_us", "美股": "trading_us",
    "nexus": "nexus_meta", "系统": "nexus_meta",
    "research": "research", "研究": "research",
    "all": "all", "全部": "all",
}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _authorized(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in ALLOWED_CHAT_IDS


async def _reject(update: Update) -> None:
    if update.message:
        await update.message.reply_text("⛔ 未授权")


def _load_agent_comms():
    """Lazy-import agent_comms module."""
    agent_comms_path = REPO_ROOT / "scripts" / "agent_comms.py"
    if not agent_comms_path.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent_comms", agent_comms_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    text = (
        "🤖 <b>Claude模拟盘</b>  A股¥10M + 美股$1.5M\n"
        "\n"
        "/s — 持仓+NAV\n"
        "/r — 风控\n"
        "/t [n] — 最近n笔交易\n"
        "/c — 催化剂日历\n"
        "/n — 新闻快讯\n"
        "/sync — 同步nexus\n"
        "/log — 系统变更\n"
        "/msg <代号> <内容> — 发消息\n"
        "/inbox — 消息板\n"
        "\n"
        "<code>astock</code> A股  <code>us</code> 美股  "
        "<code>nexus</code> 系统  <code>research</code> 研究  "
        "<code>all</code> 广播"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


# ── 查询 ──────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    portfolio = load_portfolio()
    msg = format_status_message(portfolio)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return

    def _run():
        scripts_dir = Path(_CFG.get("portfolio", {}).get("scripts_dir", ""))
        uv = _CFG.get("portfolio", {}).get("uv_path", "uv")
        risk_script = scripts_dir / "risk_monitor.py"
        if not risk_script.exists():
            return "❌ risk_monitor.py 未找到"
        try:
            result = subprocess.run(
                [uv, "run", "--script", str(risk_script), "--compact", "--no-save"],
                capture_output=True, text=True, timeout=60
            )
            text = result.stdout.strip() or result.stderr[:500]
            return text if text else "⚠️ 风控报告为空"
        except subprocess.TimeoutExpired:
            return "⏱ risk_monitor 超时"
        except Exception as exc:
            return f"❌ {exc}"

    msg = await asyncio.get_event_loop().run_in_executor(None, _run)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n…"
    await update.message.reply_text(f"<pre>{msg}</pre>", parse_mode=ParseMode.HTML)


async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    portfolio = load_portfolio()
    n = 5
    if context.args:
        try:
            n = min(int(context.args[0]), 20)
        except ValueError:
            pass
    msg = format_trades_message(portfolio, n=n)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_catalyst(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    portfolio = load_portfolio()
    msg = format_catalyst_message(portfolio)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return

    alerts_path = REPO_ROOT / "catalyst_alerts.json"
    if not alerts_path.exists():
        await update.message.reply_text("📰 无新闻记录")
        return

    try:
        raw = json.loads(alerts_path.read_text(encoding="utf-8"))
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")
        return

    all_alerts = raw.get("alerts", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])

    cutoff = datetime.now(TZ_BEIJING) - timedelta(hours=24)
    recent = []
    for entry in all_alerts:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ_BEIJING)
            if ts >= cutoff:
                recent.append(entry)
        except (ValueError, TypeError):
            recent.append(entry)

    recent.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    if not recent:
        await update.message.reply_text("📰 过去24小时无新闻")
        return

    urgency_icons = {"critical": "🔴", "breaking": "🔴", "important": "🟡"}
    lines = [f"📰 <b>新闻 ({len(recent)}条)</b>", ""]
    for entry in recent[:8]:
        icon = urgency_icons.get(entry.get("urgency", ""), "🟡")
        headline = entry.get("headline", "")
        matched = entry.get("matched_positions", [])
        match_str = f" → {', '.join(matched)}" if matched else ""
        lines.append(f"{icon} {headline}{match_str}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── 系统 ──────────────────────────────────────────────────────────────────

async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return

    scripts_dir = Path(_CFG.get("portfolio", {}).get("scripts_dir", ""))
    uv = _CFG.get("portfolio", {}).get("uv_path", "uv")
    sync_script = scripts_dir / "sync_nexus.py"

    if not sync_script.exists():
        await update.message.reply_text("❌ sync_nexus.py 未找到")
        return

    def _run_sync():
        result = subprocess.run(
            [uv, "run", "--script", str(sync_script)],
            capture_output=True, text=True, timeout=120
        )
        return result.returncode, result.stdout[-500:] if result.stdout else result.stderr[-300:]

    try:
        rc, out = await asyncio.get_event_loop().run_in_executor(None, _run_sync)
        status = "✅" if rc == 0 else f"⚠️ exit {rc}"
        await update.message.reply_text(f"{status}\n<pre>{out}</pre>", parse_mode=ParseMode.HTML)
    except asyncio.TimeoutError:
        await update.message.reply_text("⏱ 超时")
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")


async def cmd_changelog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return

    changelog_path = REPO_ROOT / "system_changelog.json"
    if not changelog_path.exists():
        await update.message.reply_text("📋 无变更记录")
        return

    try:
        data = json.loads(changelog_path.read_text(encoding="utf-8"))
    except Exception as exc:
        await update.message.reply_text(f"❌ {exc}")
        return

    entries = data.get("entries", [])
    if not entries:
        await update.message.reply_text("📋 无变更记录")
        return

    icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
    lines = [f"📋 <b>系统变更</b> (最近{min(len(entries), 5)}条)", ""]

    for e in entries[-5:]:
        icon = icons.get(e.get("priority", "medium"), "🔵")
        ack = e.get("ack", {})
        targets = e.get("target", [])
        pending = [t for t in targets if t not in ack and t != "all"]
        status = f"⏳{','.join(pending)}" if pending else "✅"

        lines.append(f"{icon} <b>{e.get('title', '?')}</b> {status}")
        lines.append(f"  {e.get('from', '?')} | {e.get('timestamp', '')[:16]}")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── Agent通信 ─────────────────────────────────────────────────────────────

async def cmd_msg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """发消息给Agent session。 /msg <代号> <内容>"""
    if not _authorized(update):
        await _reject(update)
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "/msg &lt;代号&gt; &lt;内容&gt;\n"
            "代号: astock | us | nexus | research | all",
            parse_mode=ParseMode.HTML,
        )
        return

    mod = _load_agent_comms()
    if not mod:
        await update.message.reply_text("❌ agent_comms.py 未找到")
        return

    raw_target = args[0].lower()
    to_session = SESSION_ALIASES.get(raw_target, raw_target)
    body = " ".join(args[1:])

    to_ids = [t.strip() for t in to_session.split(",")]
    msg_id = mod.cmd_send(
        from_id="user_telegram",
        to_ids=to_ids,
        subject=body[:50],
        body=body,
        no_telegram=True,
    )
    await update.message.reply_text(f"✅ → {to_session}\n🔖 {msg_id}")


async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/inbox [session] — 查看消息板"""
    if not _authorized(update):
        await _reject(update)
        return

    mod = _load_agent_comms()
    if not mod:
        await update.message.reply_text("❌ agent_comms.py 未找到")
        return

    data = mod._load()
    messages = data.get("messages", [])

    if not messages:
        await update.message.reply_text("📭 无消息")
        return

    # Optional filter by session
    filter_session = None
    if context.args:
        raw = context.args[0].lower()
        filter_session = SESSION_ALIASES.get(raw, raw)

    icons = {"critical": "🔴", "high": "🟡", "medium": "🔵", "low": "⚪"}
    shown = []
    for msg in messages[-10:]:
        if filter_session and filter_session not in msg.get("to", []) and msg.get("from") != filter_session:
            continue
        shown.append(msg)

    if not shown:
        await update.message.reply_text(f"📭 {filter_session or 'all'}: 无消息")
        return

    lines = [f"💬 <b>消息板</b> ({len(shown)}条)", ""]
    for msg in shown[-8:]:
        icon = icons.get(msg.get("priority", "medium"), "🔵")
        to_str = ",".join(msg.get("to", []))
        read_n = len(msg.get("read_by", {}))
        target_n = len(msg.get("to", []))
        replies = len(msg.get("replies", []))
        reply_tag = f" 💬{replies}" if replies else ""
        read_tag = f" ✅{read_n}/{target_n}" if target_n else ""

        lines.append(f"{icon} <b>{msg.get('subject', '?')}</b>{read_tag}{reply_tag}")
        lines.append(f"  {msg.get('from', '?')}→{to_str} {msg.get('timestamp', '')[:16]}")
        body_preview = msg.get("body", "")[:80]
        if body_preview:
            lines.append(f"  <i>{body_preview}</i>")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("❓ /help 查看命令")


# ═══════════════════════════════════════════════════════════════════════════
# Scheduled jobs
# ═══════════════════════════════════════════════════════════════════════════

async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _DAILY_CFG.get("enabled", True):
        return

    portfolio = load_portfolio()
    if not portfolio:
        await context.bot.send_message(chat_id=CHAT_ID, text="⚠️ 日报: 无法读取portfolio")
        return

    a = portfolio.get("accounts", {}).get("a_share", {})
    u = portfolio.get("accounts", {}).get("us", {})

    def nav_return(acc: dict) -> float:
        init = acc.get("initial_capital", 1)
        return round((acc.get("total_assets", init) / init - 1) * 100, 2)

    today = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d")
    catalysts = []
    for key in ["a_share", "us"]:
        for p in portfolio.get("accounts", {}).get(key, {}).get("positions", []):
            cat = p.get("next_catalyst")
            if cat:
                catalysts.append({"date": "", "ticker": p.get("ticker", ""), "event": cat})

    summary = DailySummary(
        date=today,
        cn_nav=a.get("total_assets", 0),
        cn_return_pct=nav_return(a),
        cn_benchmark_pct=None,
        us_nav=u.get("total_assets", 0),
        us_return_pct=nav_return(u),
        us_benchmark_pct=None,
        trade_count=a.get("trade_count", 0) + u.get("trade_count", 0),
        stop_loss_triggered=0,
        catalysts_upcoming=catalysts[:7],
    )

    try:
        await context.bot.send_message(
            chat_id=CHAT_ID, text=summary.format(), parse_mode=ParseMode.HTML,
        )
    except TelegramError as exc:
        logger.error("Daily summary failed: %s", exc)


async def job_risk_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _RISK_CFG.get("enabled", True):
        return

    portfolio = load_portfolio()
    if not portfolio:
        return

    a = portfolio.get("accounts", {}).get("a_share", {})
    u = portfolio.get("accounts", {}).get("us", {})
    alerts_to_send: list[RiskAlert] = []

    for acc, label in [(a, "A股"), (u, "美股")]:
        init = acc.get("initial_capital", 1)
        nav = acc.get("total_assets", init)
        peak = acc.get("peak_nav", nav)
        dd = (nav / peak - 1) * 100 if peak and peak > 0 else (nav / init - 1) * 100

        thresholds = _RISK_CFG.get("drawdown_thresholds", {})
        if dd <= thresholds.get("critical", -10.0):
            level = "CRITICAL"
        elif dd <= thresholds.get("high", -5.0):
            level = "HIGH"
        elif dd <= thresholds.get("warn", -3.0):
            level = "WARNING"
        else:
            continue

        details = [f"{label}回撤: {dd:+.2f}%"]
        for p in acc.get("positions", []):
            stop, price = p.get("stop_loss"), p.get("current_price")
            if stop and price and price > 0:
                dist = (price - stop) / price * 100
                if 0 < dist < _RISK_CFG.get("stop_proximity_alert_pct", 5.0):
                    details.append(f"{p['ticker']} 距止损{dist:.1f}%")

        action_map = {"WARNING": "暂缓新建仓", "HIGH": "暂停建仓", "CRITICAL": "考虑减仓"}
        alerts_to_send.append(RiskAlert(
            level=level, title=f"{label}需关注", details=details,
            drawdown_pct=dd, recommended_action=action_map.get(level),
        ))

    for acc, label in [(a, "A股"), (u, "美股")]:
        total = acc.get("total_assets", 1)
        cash_pct = acc.get("cash", 0) / total * 100 if total else 0
        if cash_pct < 20.0:
            alerts_to_send.append(RiskAlert(
                level="WARNING", title=f"{label}现金低",
                details=[f"现金{cash_pct:.1f}% (<20%)"],
                recommended_action="避免新建仓",
            ))

    for alert in alerts_to_send:
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID, text=alert.format(), parse_mode=ParseMode.HTML,
            )
        except TelegramError as exc:
            logger.error("Risk alert failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════
# Application
# ═══════════════════════════════════════════════════════════════════════════

def build_application() -> Application:
    if not BOT_TOKEN:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands — short aliases first, then full names
    handlers = {
        "start": cmd_start, "help": cmd_help,
        "s": cmd_status, "status": cmd_status,
        "r": cmd_risk, "risk": cmd_risk,
        "t": cmd_trades, "trades": cmd_trades,
        "c": cmd_catalyst, "catalyst": cmd_catalyst,
        "n": cmd_news, "news": cmd_news,
        "sync": cmd_sync,
        "log": cmd_changelog, "changelog": cmd_changelog,
        "msg": cmd_msg,
        "inbox": cmd_inbox,
    }
    for cmd, handler in handlers.items():
        app.add_handler(CommandHandler(cmd, handler))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))

    # Scheduled jobs
    if _DAILY_CFG.get("enabled", True):
        send_time = _DAILY_CFG.get("send_time_utc", "01:30")
        h, m = map(int, send_time.split(":"))
        app.job_queue.run_daily(
            job_daily_summary, time=dtime(h, m, 0, tzinfo=timezone.utc), name="daily",
        )

    if _RISK_CFG.get("enabled", True):
        app.job_queue.run_repeating(
            job_risk_check, interval=1800, first=60, name="risk",
        )

    return app


async def post_init(application: Application) -> None:
    commands = [
        BotCommand("s", "持仓+NAV"),
        BotCommand("r", "风控"),
        BotCommand("t", "最近交易"),
        BotCommand("c", "催化剂"),
        BotCommand("n", "新闻"),
        BotCommand("sync", "同步"),
        BotCommand("log", "系统变更"),
        BotCommand("msg", "发消息"),
        BotCommand("inbox", "消息板"),
    ]
    await application.bot.set_my_commands(commands)

    try:
        now = datetime.now(TZ_BEIJING).strftime("%m-%d %H:%M")
        await application.bot.send_message(
            chat_id=CHAT_ID,
            text=f"🟢 Bot启动 {now}  /help",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning("Startup notification failed: %s", exc)


def main() -> None:
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if not CHAT_ID:
        print("WARNING: TELEGRAM_CHAT_ID not set", file=sys.stderr)

    logger.info("Starting bot…")
    app = build_application()
    app.post_init = post_init
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        stop_signals=None,
    )


if __name__ == "__main__":
    main()
