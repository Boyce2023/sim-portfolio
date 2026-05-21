# Integration Guide — 如何接入现有脚本

## 1. execute_trade.py 接入（交易通知）

在 `execute_trade.py` 的 `main()` 函数内，找到交易执行成功后的日志输出处，追加以下代码。

### 定位点

搜索 `execute_trade.py` 中已有的成功打印逻辑（大约在 `log_trade()` 或 `print(f"成交")` 附近）：

```python
# 在文件顶部追加import（放在其他import之后）
import sys
import os
sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot"))
try:
    from notifications import TelegramNotifier, TradeAlert
    _tg = TelegramNotifier()
    _tg_enabled = True
except Exception:
    _tg_enabled = False   # 静默失败，不影响主流程
```

### 追加发送逻辑

在 `execute_trade.py` 内已有的成交确认之后：

```python
# ── Telegram通知（追加在现有成交日志之后） ──────────────────
if _tg_enabled:
    try:
        alert = TradeAlert(
            account=args.account,
            action=args.action,
            ticker=ticker,
            name=position.get("name", ticker),
            shares=executed_shares,
            price=execution_price,
            reason=args.reason,
            portfolio_pct=new_position_pct,
            stop_loss=stop_loss_price,
            stop_loss_pct=stop_loss_pct,
            target_1=target_1,
            currency="CNY" if args.account == "cn" else "USD",
        )
        _tg.send_nowait(alert)   # 非阻塞，不影响主流程
    except Exception as _tg_exc:
        logger.warning("Telegram通知失败: %s", _tg_exc)
```

**关键**: 使用 `send_nowait()` 而非 `send()`，确保网络问题不阻塞交易流程。

---

## 2. risk_monitor.py 接入（风险警报）

### 定位点

`risk_monitor.py` 在生成 alerts 后有一个 `print` / `console.print` 的汇总输出。在此之后追加：

```python
# 在文件顶部（imports之后）
sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot"))
try:
    from notifications import TelegramNotifier, RiskAlert as TgRiskAlert
    _tg = TelegramNotifier()
    _tg_enabled = True
except Exception:
    _tg_enabled = False
```

### 在主函数的 Critical/High alert 判断后追加：

```python
# ── Telegram推送（追加在现有输出之后） ──────────────────────
if _tg_enabled and overall_level in ("CRITICAL", "HIGH", "WARNING"):
    try:
        tg_alert = TgRiskAlert(
            level=overall_level,
            title=f"组合风险: {overall_level}",
            details=[a.message for a in alerts[:5]],   # alerts 是已有的alert列表
            drawdown_pct=portfolio_drawdown_pct,        # 已有变量
            circuit_breaker_triggered=(overall_level == "CRITICAL"),
            recommended_action=recommended_action_text,
        )
        _tg.send(tg_alert)   # 同步发送，risk_monitor本身已是独立进程
    except Exception as _exc:
        logger.warning("Telegram风控通知失败: %s", _exc)
```

### risk_monitor.py exit code 集成

`daily_run.sh` 已经检查 `risk_monitor.py` 的 exit code：

```bash
# daily_run.sh 现有逻辑（无需修改，risk_monitor已正确退出）
if ! uv run --script scripts/risk_monitor.py; then
    # CRITICAL: 发送系统警报
    python3 -c "
import sys; sys.path.insert(0, 'telegram-bot')
from notifications import TelegramNotifier, RiskAlert
TelegramNotifier().send(RiskAlert(
    level='CRITICAL',
    title='risk_monitor.py 退出码非0',
    details=['请检查 logs/ 目录'],
    recommended_action='手动检查持仓止损'
))
"
fi
```

---

## 3. daily_run.sh 接入（日报）

在 `daily_run.sh` 末尾（git push 之后）追加：

```bash
# ── Step 6: 发送日报 ──────────────────────────────────────
TELEGRAM_BOT_DIR="${REPO_DIR}/telegram-bot"
if [ -f "${TELEGRAM_BOT_DIR}/notifications.py" ]; then
    log ">>> 步骤：发送 Telegram 日报"
    python3 - <<'PYEOF'
import sys, json
from pathlib import Path
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/telegram-bot")

try:
    from notifications import TelegramNotifier, DailySummary, load_portfolio, _read_upcoming_catalysts
    portfolio = load_portfolio()
    a = portfolio.get("accounts", {}).get("a_share", {})
    u = portfolio.get("accounts", {}).get("us", {})

    def nav_return(acc, init):
        nav = acc.get("total_assets", init)
        return round((nav / init - 1) * 100, 2)

    from datetime import datetime, timezone, timedelta
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    summary = DailySummary(
        date=today,
        cn_nav=a.get("total_assets", 0),
        cn_return_pct=nav_return(a, a.get("initial_capital", 1000000)),
        cn_benchmark_pct=None,
        us_nav=u.get("total_assets", 0),
        us_return_pct=nav_return(u, u.get("initial_capital", 150000)),
        us_benchmark_pct=None,
        trade_count=a.get("trade_count", 0) + u.get("trade_count", 0),
        stop_loss_triggered=0,
        catalysts_upcoming=[
            {"date": "", "ticker": p.get("ticker", ""), "event": p.get("next_catalyst", "")}
            for acc_key in ["a_share", "us"]
            for p in portfolio.get("accounts", {}).get(acc_key, {}).get("positions", [])
            if p.get("next_catalyst")
        ][:7],
    )
    TelegramNotifier().send(summary)
    print("日报已发送")
except Exception as e:
    print(f"日报发送失败: {e}")
PYEOF
fi
```

---

## 4. 文件放置规范

```
sim-portfolio/
├── telegram-bot/           ← 新增目录（存放bot文件）
│   ├── bot.py
│   ├── notifications.py
│   └── INTEGRATION.md
├── config/
│   └── telegram_config.json   ← 从 config_template.json 复制
├── scripts/
│   ├── execute_trade.py   ← 追加3行import + send_nowait
│   ├── risk_monitor.py    ← 追加alert发送逻辑
│   └── daily_run.sh       ← 追加Step 6日报发送
└── ...
```

**注意**: `bot.py` 独立运行（长驻进程），`notifications.py` 是无状态模块（供其他脚本import）。两者可以共存在同一目录。

---

## 5. 环境变量传递

### 手动运行（测试）
```bash
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
uv run /Users/huaichuaibeimeng/claude-projects/sim-portfolio/telegram-bot/bot.py
```

### launchd（与现有 daily_run.sh 同级）

在 `install_launchd.sh` 中已有 launchd 安装逻辑，仿照添加 bot 的 plist：

```xml
<!-- ~/Library/LaunchAgents/com.claude.telegrambot.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude.telegrambot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/huaichuaibeimeng/.local/bin/uv</string>
        <string>run</string>
        <string>/Users/huaichuaibeimeng/claude-projects/sim-portfolio/telegram-bot/bot.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>YOUR_TOKEN_HERE</string>
        <key>TELEGRAM_CHAT_ID</key>
        <string>YOUR_CHAT_ID_HERE</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/huaichuaibeimeng/claude-projects/sim-portfolio/logs/telegram-bot.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/huaichuaibeimeng/claude-projects/sim-portfolio/logs/telegram-bot-err.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.claude.telegrambot.plist
launchctl start com.claude.telegrambot
```

---

## 6. 与现有 JS Bot 的共存

系统中已有 `.claude-tasks/telegram-claude-bot.js`（Claude Code任务管理bot）。Python bot 和 JS bot 使用相同的 BOT_TOKEN 是可以的 — Telegram允许同一bot多个消费者，但**不能**同时长轮询。

**推荐方案**: 两个bot使用同一TOKEN，但只有一个在同一时间长轮询。如果JS bot长期运行，Python bot改为**push-only模式**（不轮询，只发消息）：

```python
# push-only模式: 不启动Application，直接发消息
from notifications import TelegramNotifier, TradeAlert
notifier = TelegramNotifier()
notifier.send(alert)
```

这样 `notifications.py` 的发送功能完全独立，无需运行 `bot.py`。

---

## 7. 快速验证清单

```bash
# 1. 验证配置文件
ls -la /Users/huaichuaibeimeng/claude-projects/sim-portfolio/config/telegram_config.json

# 2. 验证通知模块格式化（无网络）
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio/telegram-bot
uv run notifications.py --test

# 3. 验证Telegram连接（需要真实token）
export TELEGRAM_BOT_TOKEN=xxx
export TELEGRAM_CHAT_ID=xxx
uv run notifications.py --ping

# 4. 启动bot（前台调试）
uv run bot.py

# 5. 在Telegram里发 /status 验证命令响应
```
