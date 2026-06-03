#!/usr/bin/env bash
# =============================================================================
# daily_run.sh — sim-portfolio 每日自动触发入口
# 由 launchd 在 UTC 00:00（北京时间 08:00）调用
# =============================================================================

# ---------- 路径常量 ----------
REPO_DIR="/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
SCRIPTS_DIR="${REPO_DIR}/scripts"
LOGS_DIR="${REPO_DIR}/logs"
CALENDAR_FILE="${REPO_DIR}/market_calendar.json"

# ---------- 设置 PATH（launchd 环境极简，必须手动补全） ----------
export PATH="/Users/huaichuaibeimeng/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# uv 绝对路径备用
UV_BIN="/Users/huaichuaibeimeng/.local/bin/uv"
GIT_BIN="/usr/bin/git"

# ---------- 日志初始化 ----------
mkdir -p "${LOGS_DIR}"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="${LOGS_DIR}/${TODAY}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

log_err() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "${LOG_FILE}" >&2
}

log "===== daily_run.sh 启动 ====="

# ---------- 工作目录 ----------
cd "${REPO_DIR}" || {
    log_err "无法 cd 到 ${REPO_DIR}，退出"
    exit 1
}

# ---------- 市场日历检查（检查今天 NYSE 是否休市） ----------
# 读取 market_calendar.json 判断今天是否应该运行
# 规则：周末或在 nyse_closed 列表中 → 跳过
check_trading_day() {
    local dow
    dow=$(date +%u)   # 1=Mon … 7=Sun
    if [ "${dow}" -ge 6 ]; then
        log "今天是周末（周${dow}），跳过交易流程"
        return 1
    fi

    if [ ! -f "${CALENDAR_FILE}" ]; then
        log "未找到 market_calendar.json，跳过节假日检查，继续运行"
        return 0
    fi

    # 用 python3 读 JSON（比 jq 更可靠，避免依赖缺失）
    local is_holiday
    is_holiday=$(python3 - <<PYEOF
import json, sys
with open("${CALENDAR_FILE}") as f:
    cal = json.load(f)
closed = cal.get("trading_days_by_market", {}).get("us_closed_dates", [])
print("yes" if "${TODAY}" in closed else "no")
PYEOF
)

    if [ "${is_holiday}" = "yes" ]; then
        log "今天 ${TODAY} 是 NYSE 节假日，跳过交易流程"
        return 1
    fi

    return 0
}

if ! check_trading_day; then
    log "===== daily_run.sh 结束（非交易日，无操作） ====="
    exit 0
fi

log "今天 ${TODAY} 是交易日，开始执行流程"

# ---------- 通用步骤执行器 ----------
# run_step <步骤名> <命令...>
# 失败时记录错误但不 exit，让后续步骤继续
STEP_FAILED=0

run_step() {
    local step_name="$1"
    shift
    log ">>> 步骤：${step_name}"
    if "$@" >> "${LOG_FILE}" 2>&1; then
        log "    ✓ ${step_name} 成功"
    else
        local rc=$?
        log_err "    ✗ ${step_name} 失败（exit ${rc}）"
        STEP_FAILED=1
    fi
}

# ---------- Step 1: git pull ----------
run_step "git pull" \
    "${GIT_BIN}" pull --ff-only

# ---------- Step 2: 获取价格 ----------
run_step "fetch_prices.py" \
    "${UV_BIN}" run "${SCRIPTS_DIR}/fetch_prices.py"

# ---------- Step 2b: 把价格回写 portfolio_state.json ----------
# update_prices.py exit 1 = validation errors（记录但不阻止后续，decision_engine 有 fallback）
# update_prices.py exit 0 = 成功
run_step "update_prices.py" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/update_prices.py"

# ---------- Step 2c: 持久化催化剂日历数据 ----------
log ">>> 步骤：catalyst_calendar"
if "${UV_BIN}" run --script "${SCRIPTS_DIR}/catalyst_calendar.py" \
       --portfolio --json > "${REPO_DIR}/catalyst_upcoming.json" 2>/dev/null; then
    log "    ✓ catalyst_calendar 成功"
else
    log "    ⚠ catalyst_calendar 失败（非阻断，继续）"
fi

# ---------- Step 2d: Track B 盘后日评（TB持仓天数+CB追踪） ----------
if [ -f "${SCRIPTS_DIR}/tb_review.py" ]; then
    log ">>> 步骤：tb_review.py（Track B 盘后日评）"
    if "${UV_BIN}" run --script "${SCRIPTS_DIR}/tb_review.py" >> "${LOG_FILE}" 2>&1; then
        log "    ✓ tb_review.py 成功"
    else
        log "    ⚠ tb_review.py 失败（非阻断，继续）"
    fi
fi

# ---------- Step 3 (pre): Truth Store 维护（after update_prices, before decision_engine） ----------
run_step "maintain_truth.py" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/maintain_truth.py"

# ---------- Step 3b: A股 Regime Detection（宏观环境5信号） ----------
if [ -f "${SCRIPTS_DIR}/astock_regime.py" ]; then
    run_step "astock_regime.py" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/astock_regime.py"
fi

# ---------- Step 3c: 退出信号检测（龙头崩+暴力拉升+催化剂临近） ----------
# 必须在 decision_engine 之前运行，使 decision_engine 能读到 nexus 退出信号
if [ -f "${SCRIPTS_DIR}/exit_signal_detector.py" ]; then
    run_step "exit_signal_detector.py" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/exit_signal_detector.py"
fi

# ---------- Step 3: 更新持仓 ----------
# trading_engine.py 可能还不存在，条件执行
if [ -f "${SCRIPTS_DIR}/trading_engine.py" ]; then
    run_step "trading_engine.py" \
        "${UV_BIN}" run "${SCRIPTS_DIR}/trading_engine.py"
else
    log ">>> 步骤：trading_engine.py（文件不存在，跳过）"
fi

# ---------- Step 4: 生成决策（读取 exit_signal_detector 产生的 nexus 信号） ----------
if [ -f "${SCRIPTS_DIR}/decision_engine.py" ]; then
    run_step "decision_engine.py" \
        "${UV_BIN}" run "${SCRIPTS_DIR}/decision_engine.py"
else
    log ">>> 步骤：decision_engine.py（文件不存在，跳过）"
fi

# ---------- Step 4b: 自动执行止损（critical sell signals only） ----------
# 读 decisions.json，如有 priority=critical 的卖出信号，自动执行
if [ -f "${REPO_DIR}/decisions.json" ]; then
    log ">>> 步骤：auto-execute critical sells"
    python3 - <<'PYEOF'
import json, subprocess, sys

decisions_path = "decisions.json"
try:
    with open(decisions_path) as f:
        decisions = json.load(f)
except Exception:
    sys.exit(0)

sells = [s for s in decisions.get("sell_signals", []) if s.get("priority") == "critical"]
if not sells:
    print("无 critical 卖出信号")
    sys.exit(0)

for s in sells:
    ticker = s["ticker"]
    market = s.get("market", "us")
    account = "cn" if market == "cn" else "us"
    reason = s.get("reason", "auto stop-loss")
    cmd = [
        "/Users/huaichuaibeimeng/.local/bin/uv", "run", "--script",
        "scripts/execute_trade.py", "sell",
        "--account", account, "--ticker", ticker, "--all",
        "--reason", f"AUTO-STOPLOSS: {reason}"
    ]
    print(f"执行止损: {ticker} ({account})")
    subprocess.run(cmd, check=False)
PYEOF
    log "    ✓ auto-execute 检查完成"
fi

# ---------- Step 4b2: 自动执行 pending_orders（portfolio_state.json中的待处理订单） ----------
# trading_engine.py 会将session决策写入 pending_orders，但不执行。此步骤闭环。
log ">>> 步骤：auto-execute pending_orders"
python3 - <<'PYEOF'
import json, subprocess, sys
from pathlib import Path

state_path = Path("portfolio_state.json")
try:
    with open(state_path) as f:
        state = json.load(f)
except Exception as e:
    print(f"读取 portfolio_state.json 失败: {e}")
    sys.exit(0)

pending = state.get("pending_orders", [])
if not pending:
    print("无 pending_orders")
    sys.exit(0)

uv = "/Users/huaichuaibeimeng/.local/bin/uv"
executed = []

for order in pending:
    ticker = order.get("ticker", "")
    action = order.get("action", "").lower()  # "buy" or "sell"
    shares = order.get("shares")
    reason = order.get("reason", "auto-execute pending order")
    account_raw = order.get("account", "a_share")

    # normalize account name
    if account_raw in ("a_share", "cn", "astock"):
        account = "cn"
    else:
        account = "us"

    if action not in ("buy", "sell"):
        print(f"跳过未知操作: {ticker} {action}")
        continue

    cmd = [uv, "run", "--script", "scripts/execute_trade.py", action,
           "--account", account, "--ticker", ticker]

    if action == "buy" and shares:
        cmd += ["--shares", str(shares)]
    elif action == "sell":
        if shares:
            cmd += ["--shares", str(shares)]
        else:
            cmd += ["--all"]

    cmd += ["--reason", f"AUTO-PENDING: {reason}"]

    print(f"执行 pending_order: {action} {ticker} {shares or 'ALL'}股 ({account})")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"  ✓ {ticker} 成功")
        executed.append(ticker)
    else:
        print(f"  ✗ {ticker} 失败: {result.stderr[-200:] if result.stderr else 'unknown'}")

# 清除已执行的 pending_orders（通过 portfolio_io 确保同步链路完整）
if executed:
    with open(state_path) as f:
        state = json.load(f)
    remaining = [o for o in state.get("pending_orders", []) if o.get("ticker") not in executed]
    state["pending_orders"] = remaining
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from portfolio_io import save_portfolio
    save_portfolio(state, reason="daily auto: clear pending_orders", auto_sync=False)
    print(f"已清除 {len(executed)} 条 pending_orders，剩余 {len(remaining)} 条")

PYEOF
log "    ✓ pending_orders 检查完成"

# ---------- Step 4c: 同步 nexus-package dashboard ----------
run_step "sync_nexus.py" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/sync_nexus.py"

# ---------- Step 5: git commit & push ----------
# 只在有文件变化时提交
log ">>> 步骤：git commit & push"
if "${GIT_BIN}" diff --quiet && "${GIT_BIN}" diff --cached --quiet; then
    log "    无文件变化，跳过 commit"
else
    COMMIT_MSG="daily: ${TODAY} auto-update"
    if "${GIT_BIN}" add -A >> "${LOG_FILE}" 2>&1 \
       && "${GIT_BIN}" commit -m "${COMMIT_MSG}" >> "${LOG_FILE}" 2>&1 \
       && "${GIT_BIN}" push >> "${LOG_FILE}" 2>&1; then
        log "    ✓ git commit & push 成功：${COMMIT_MSG}"
    else
        log_err "    ✗ git commit & push 失败（exit $?）"
        STEP_FAILED=1
    fi
fi

# ---------- 汇总 ----------
if [ "${STEP_FAILED}" -eq 1 ]; then
    log "===== daily_run.sh 结束（有步骤失败，请检查日志 ${LOG_FILE}） ====="
else
    log "===== daily_run.sh 结束（全部成功） ====="
fi

exit 0
