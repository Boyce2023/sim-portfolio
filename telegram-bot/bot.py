#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["python-telegram-bot>=21.0", "httpx>=0.27"]
# ///
"""
bot.py — Telegram Alert Bot for Claude模拟盘
完整bot框架：长轮询 + 命令处理 + 定时任务

启动:
    export TELEGRAM_BOT_TOKEN=xxx
    export TELEGRAM_CHAT_ID=xxx
    uv run bot.py

守护进程:
    # 参见 README.md 的 launchd / systemd 配置
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
# Imports — python-telegram-bot v21+ (async)
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

# Local module — must be in same directory or on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))
from notifications import (
    TelegramNotifier,
    TradeAlert,
    RiskAlert,
    DailySummary,
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

# Suppress noisy upstream logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TZ_BEIJING = timezone(timedelta(hours=8))

def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

BOT_TOKEN = _get_env("TELEGRAM_BOT_TOKEN")
CHAT_ID = _get_env("TELEGRAM_CHAT_ID")

# Allowed command-senders (defaults to CHAT_ID if not set)
_allowed_raw = _get_env("TELEGRAM_ALLOWED_CHAT_IDS", CHAT_ID)
ALLOWED_CHAT_IDS: set[int] = {
    int(cid.strip()) for cid in _allowed_raw.split(",") if cid.strip().lstrip("-").isdigit()
}

# Config-driven settings
_notif_cfg = _CFG.get("notifications", {})
_DAILY_CFG = _notif_cfg.get("daily_summary", {})
_WEEKLY_CFG = _notif_cfg.get("weekly_summary", {})
_RISK_CFG = _notif_cfg.get("risk_alerts", {})

# UX
RATE_LIMIT_PER_MIN = _CFG.get("commands", {}).get("rate_limit_per_minute", 20)


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _authorized(update: Update) -> bool:
    """Only allow messages from whitelisted chat IDs."""
    if not ALLOWED_CHAT_IDS:
        return True  # No whitelist = allow all (development mode)
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in ALLOWED_CHAT_IDS


async def _reject(update: Update) -> None:
    if update.message:
        await update.message.reply_text("⛔ 未授权")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    text = (
        "🤖 <b>Claude模拟盘 Alert Bot</b>\n\n"
        "可用命令:\n"
        "  /status — 当前持仓和NAV\n"
        "  /risk — 风险指标（实时运行risk_monitor）\n"
        "  /trades — 最近5笔交易\n"
        "  /catalyst — 未来7天催化剂\n"
        "  /sync — 触发nexus数据同步\n"
        "  /help — 显示此帮助\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    await update.message.reply_text("⏳ 读取持仓中…", parse_mode=ParseMode.HTML)
    portfolio = load_portfolio()
    msg = format_status_message(portfolio)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    await update.message.reply_text("⏳ 运行风控检查（最多60秒）…", parse_mode=ParseMode.HTML)
    msg = await asyncio.get_event_loop().run_in_executor(None, format_risk_message)
    # Truncate for Telegram
    if len(msg) > 4000:
        msg = msg[:3900] + "\n…（截断，查看完整日志）"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    portfolio = load_portfolio()
    n = 5
    if context.args:
        try:
            n = int(context.args[0])
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


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        await _reject(update)
        return
    await update.message.reply_text("⏳ 触发 sync_nexus.py…")

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
        return result.returncode, result.stdout[-1000:] if result.stdout else result.stderr[-500:]

    try:
        rc, out = await asyncio.get_event_loop().run_in_executor(None, _run_sync)
        status = "✅ 同步成功" if rc == 0 else f"⚠️ 同步失败 (exit {rc})"
        await update.message.reply_text(f"{status}\n<pre>{out}</pre>", parse_mode=ParseMode.HTML)
    except asyncio.TimeoutError:
        await update.message.reply_text("⏱ 同步超时（>120s）")
    except Exception as exc:
        await update.message.reply_text(f"❌ 同步出错: {exc}")


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("❓ 未知命令，输入 /help 查看可用命令")


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

async def job_daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send daily summary at configured UTC time (default 01:30 UTC = 09:30 BJT)."""
    if not _DAILY_CFG.get("enabled", True):
        return

    portfolio = load_portfolio()
    if not portfolio:
        await context.bot.send_message(
            chat_id=CHAT_ID, text="⚠️ 日报: 无法读取portfolio_state.json",
            parse_mode=ParseMode.HTML
        )
        return

    a = portfolio.get("accounts", {}).get("a_share", {})
    u = portfolio.get("accounts", {}).get("us", {})

    def nav_return(acc: dict, init: float) -> float:
        return round((acc.get("total_assets", init) / init - 1) * 100, 2)

    today = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d")

    summary = DailySummary(
        date=today,
        cn_nav=a.get("total_assets", 0),
        cn_return_pct=nav_return(a, a.get("initial_capital", 1000000)),
        cn_benchmark_pct=None,   # TODO: fetch from yfinance 000300.SS if needed
        us_nav=u.get("total_assets", 0),
        us_return_pct=nav_return(u, u.get("initial_capital", 150000)),
        us_benchmark_pct=None,
        trade_count=a.get("trade_count", 0) + u.get("trade_count", 0),
        stop_loss_triggered=0,
        catalysts_upcoming=_read_upcoming_catalysts(portfolio),
    )

    try:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=summary.format(),
            parse_mode=ParseMode.HTML,
        )
        logger.info("Daily summary sent for %s", today)
    except TelegramError as exc:
        logger.error("Failed to send daily summary: %s", exc)


async def job_risk_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic risk check — sends alert only if thresholds breached."""
    if not _RISK_CFG.get("enabled", True):
        return

    portfolio = load_portfolio()
    if not portfolio:
        return

    a = portfolio.get("accounts", {}).get("a_share", {})
    u = portfolio.get("accounts", {}).get("us", {})

    alerts_to_send: list[RiskAlert] = []

    # Check drawdown for both accounts
    for acc, label, init, currency in [
        (a, "A股", a.get("initial_capital", 1000000), "CNY"),
        (u, "美股", u.get("initial_capital", 150000), "USD"),
    ]:
        nav = acc.get("total_assets", init)
        peak_nav = acc.get("peak_nav", nav)  # requires tracking in portfolio_state
        if peak_nav and peak_nav > 0:
            drawdown = (nav / peak_nav - 1) * 100
        else:
            drawdown = (nav / init - 1) * 100

        warn_dd = _RISK_CFG.get("drawdown_thresholds", {}).get("warn", -3.0)
        high_dd = _RISK_CFG.get("drawdown_thresholds", {}).get("high", -5.0)
        critical_dd = _RISK_CFG.get("drawdown_thresholds", {}).get("critical", -10.0)

        if drawdown <= critical_dd:
            level = "CRITICAL"
        elif drawdown <= high_dd:
            level = "HIGH"
        elif drawdown <= warn_dd:
            level = "WARNING"
        else:
            continue  # No alert needed

        details = [f"{label}回撤: {drawdown:+.2f}% (from peak)"]
        # Find positions near stop loss
        for p in acc.get("positions", []):
            stop = p.get("stop_loss")
            price = p.get("current_price")
            if stop and price and price > 0:
                stop_dist = (price - stop) / price * 100
                stop_prox = _RISK_CFG.get("stop_proximity_alert_pct", 5.0)
                if 0 < stop_dist < stop_prox:
                    details.append(
                        f"{p['ticker']} 距止损仅 {stop_dist:.1f}%"
                    )

        action_map = {
            "WARNING": "监控加强，暂缓新建仓",
            "HIGH": "暂停新建仓，检查止损设置",
            "CRITICAL": "立即检查，考虑减仓至现金≥50%",
        }
        alerts_to_send.append(RiskAlert(
            level=level,
            title=f"{label}组合需关注",
            details=details,
            drawdown_pct=drawdown,
            recommended_action=action_map.get(level),
        ))

    # Check cash levels
    for acc, label in [(a, "A股"), (u, "美股")]:
        total = acc.get("total_assets", 1)
        cash = acc.get("cash", 0)
        cash_pct = cash / total * 100 if total else 0
        min_cash = 20.0
        if cash_pct < min_cash:
            alerts_to_send.append(RiskAlert(
                level="WARNING",
                title=f"{label}现金比例偏低",
                details=[f"当前现金: {cash_pct:.1f}% (下限: {min_cash:.0f}%)"],
                recommended_action="避免新建仓",
            ))

    for alert in alerts_to_send:
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=alert.format(),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError as exc:
            logger.error("Failed to send risk alert: %s", exc)


def _read_upcoming_catalysts(portfolio: dict, days: int = 7) -> list[dict]:
    """Extract catalyst entries from portfolio positions."""
    results = []
    for account_key in ["a_share", "us"]:
        for p in portfolio.get("accounts", {}).get(account_key, {}).get("positions", []):
            cat = p.get("next_catalyst")
            if cat:
                results.append({
                    "date": "",
                    "ticker": p.get("ticker", ""),
                    "event": cat,
                })
    return results[:7]


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def build_application() -> Application:
    if not BOT_TOKEN:
        raise EnvironmentError(
            "TELEGRAM_BOT_TOKEN not set. Export it before starting the bot."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    # Register commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("trades", cmd_trades))
    app.add_handler(CommandHandler("catalyst", cmd_catalyst))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))

    # Schedule daily summary
    if _DAILY_CFG.get("enabled", True):
        send_time_utc = _DAILY_CFG.get("send_time_utc", "01:30")
        h, m = map(int, send_time_utc.split(":"))
        app.job_queue.run_daily(
            job_daily_summary,
            time=dtime(h, m, 0, tzinfo=timezone.utc),
            name="daily_summary",
        )
        logger.info("Daily summary scheduled at %s UTC", send_time_utc)

    # Risk check every 30 minutes during trading hours
    if _RISK_CFG.get("enabled", True):
        app.job_queue.run_repeating(
            job_risk_check,
            interval=1800,   # 30 minutes
            first=60,        # start after 60s
            name="risk_check",
        )
        logger.info("Risk check scheduled every 30 minutes")

    return app


async def post_init(application: Application) -> None:
    """Set bot command menu after startup."""
    commands = [
        BotCommand("status", "当前持仓和NAV"),
        BotCommand("risk", "实时风险指标"),
        BotCommand("trades", "最近5笔交易"),
        BotCommand("catalyst", "未来7天催化剂"),
        BotCommand("sync", "触发nexus数据同步"),
        BotCommand("help", "显示帮助"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot command menu updated")

    # Send startup notification
    try:
        now = datetime.now(TZ_BEIJING).strftime("%Y-%m-%d %H:%M BJT")
        await application.bot.send_message(
            chat_id=CHAT_ID,
            text=f"🟢 <b>Alert Bot 已启动</b>\n{now}\n输入 /help 查看命令",
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning("Could not send startup notification: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable not set.", file=sys.stderr)
        print("  export TELEGRAM_BOT_TOKEN=your_token_here", file=sys.stderr)
        sys.exit(1)

    if not CHAT_ID:
        print("WARNING: TELEGRAM_CHAT_ID not set — scheduled jobs won't know where to send.", file=sys.stderr)

    logger.info("Starting Claude Portfolio Alert Bot…")
    logger.info("Allowed chat IDs: %s", ALLOWED_CHAT_IDS or "ALL (dev mode)")

    app = build_application()
    app.post_init = post_init

    # Run with polling (no webhook needed for local/Mac deployment)
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,   # Don't process commands sent while bot was offline
        stop_signals=None,           # Let KeyboardInterrupt handle shutdown
    )


if __name__ == "__main__":
    main()
