#!/usr/bin/env bash
# =============================================================================
# install_launchd.sh — 安装 / 卸载 sim-portfolio 每日自动触发的 launchd 服务
#
# 用法：
#   ./scripts/install_launchd.sh              # 安装
#   ./scripts/install_launchd.sh --uninstall  # 卸载
# =============================================================================

LABEL="com.claude.sim-portfolio"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"

REPO_DIR="/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
DAILY_RUN="${REPO_DIR}/scripts/daily_run.sh"
LOGS_DIR="${REPO_DIR}/logs"

# ---------- 卸载流程 ----------
uninstall() {
    echo "[install_launchd] 卸载 ${LABEL} ..."

    # 停止并移除（忽略未加载时的报错）
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null \
        || launchctl unload "${PLIST_PATH}" 2>/dev/null \
        || true

    if [ -f "${PLIST_PATH}" ]; then
        rm -f "${PLIST_PATH}"
        echo "[install_launchd] 已删除 plist: ${PLIST_PATH}"
    else
        echo "[install_launchd] plist 不存在，无需删除"
    fi

    echo "[install_launchd] 卸载完成"
}

# ---------- 参数解析 ----------
if [ "$1" = "--uninstall" ]; then
    uninstall
    exit 0
fi

# ---------- 安装前检查 ----------
if [ ! -f "${DAILY_RUN}" ]; then
    echo "[install_launchd] 错误：找不到 ${DAILY_RUN}"
    echo "请确保 daily_run.sh 已存在再安装"
    exit 1
fi

if [ ! -x "${DAILY_RUN}" ]; then
    echo "[install_launchd] daily_run.sh 不可执行，自动 chmod +x ..."
    chmod +x "${DAILY_RUN}"
fi

# ---------- 创建目录 ----------
mkdir -p "${PLIST_DIR}"
mkdir -p "${LOGS_DIR}"

# ---------- 写入 plist ----------
# StartCalendarInterval: Hour=0, Minute=0 UTC = 北京时间 08:00
cat > "${PLIST_PATH}" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

    <!-- 服务标识 -->
    <key>Label</key>
    <string>${LABEL}</string>

    <!-- 执行程序：绝对路径 -->
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${DAILY_RUN}</string>
    </array>

    <!-- 工作目录 -->
    <key>WorkingDirectory</key>
    <string>${REPO_DIR}</string>

    <!-- 触发时间：UTC 00:00 = 北京时间 08:00 -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>0</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <!-- 日志输出 -->
    <key>StandardOutPath</key>
    <string>${LOGS_DIR}/launchd_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${LOGS_DIR}/launchd_stderr.log</string>

    <!-- 启动时不立即运行 -->
    <key>RunAtLoad</key>
    <false/>

    <!-- 环境变量（launchd 不继承 shell PATH） -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Users/huaichuaibeimeng/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>/Users/huaichuaibeimeng</string>
    </dict>

</dict>
</plist>
PLIST

echo "[install_launchd] plist 已写入: ${PLIST_PATH}"

# ---------- 先卸载旧版本（如果存在） ----------
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null \
    || launchctl unload "${PLIST_PATH}" 2>/dev/null \
    || true

# ---------- 加载新 plist ----------
# macOS 13+ 推荐 bootstrap，旧版本回退到 load
if launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}" 2>/dev/null; then
    echo "[install_launchd] launchctl bootstrap 成功"
elif launchctl load "${PLIST_PATH}" 2>/dev/null; then
    echo "[install_launchd] launchctl load 成功（旧版兼容模式）"
else
    echo "[install_launchd] 警告：launchctl 加载失败，请手动运行："
    echo "  launchctl load ${PLIST_PATH}"
fi

# ---------- 验证 ----------
echo ""
echo "[install_launchd] 验证服务状态："
launchctl list | grep "${LABEL}" && echo "  ✓ 服务已注册" || echo "  ⚠ 服务未出现在列表中，请检查"

echo ""
echo "[install_launchd] ===== 安装完成 ====="
echo "  服务标识: ${LABEL}"
echo "  plist:    ${PLIST_PATH}"
echo "  触发时间: 每天 UTC 00:00（北京时间 08:00）"
echo "  入口脚本: ${DAILY_RUN}"
echo "  标准输出: ${LOGS_DIR}/launchd_stdout.log"
echo "  标准错误: ${LOGS_DIR}/launchd_stderr.log"
echo "  每日日志: ${LOGS_DIR}/YYYY-MM-DD.log"
echo ""
echo "  手动测试: launchctl start ${LABEL}"
echo "  手动停止: launchctl stop ${LABEL}"
echo "  查看状态: launchctl list ${LABEL}"
echo "  卸载:     ./scripts/install_launchd.sh --uninstall"
