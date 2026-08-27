#!/usr/bin/env bash
# push_all.sh — 一键push sim-portfolio + nexus-package
# 用法: bash scripts/push_all.sh ["commit message"]
set -euo pipefail

SIM_DIR="$(cd "$(dirname "$0")/.." && pwd)"
NEXUS_DIR="$HOME/claude-projects/nexus-package"
MSG="${1:-auto: push_all}"

echo "═══════════════════════════════════════"
echo "  push_all: sim-portfolio + nexus"
echo "═══════════════════════════════════════"

# ── 0. 刷新价格（防止盘中push带陈旧价格，2026-06-12事故修复）──
cd "$SIM_DIR"
if [ -f scripts/update_prices.py ]; then
    uv run --script scripts/update_prices.py 2>/dev/null | tail -2 || echo "[prices] ⚠️ update_prices失败，继续push（价格可能非最新）"
fi

# ── 1. sim-portfolio ──
cd "$SIM_DIR"
if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -m "$MSG

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>" || true
fi

AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "0")
if [ "$AHEAD" -gt 0 ]; then
    git push
    echo "[sim-portfolio] ✓ pushed ($AHEAD commits)"
else
    echo "[sim-portfolio] ✓ already up to date"
fi

# ── 2. sync_nexus → nexus-package ──
cd "$SIM_DIR"
if [ -f scripts/sync_nexus.py ]; then
    uv run --script scripts/sync_nexus.py
else
    echo "[nexus] ⚠️ sync_nexus.py not found, skipping"
fi

# ── 3. nexus-package (catch any unsync'd changes) ──
if [ -d "$NEXUS_DIR/.git" ]; then
    cd "$NEXUS_DIR"
    if [ -n "$(git status --porcelain)" ]; then
        git add -A
        git commit -m "sync: manual push_all $(date -u '+%Y-%m-%d %H:%M UTC')" || true
    fi
    AHEAD=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "0")
    if [ "$AHEAD" -gt 0 ]; then
        git push
        echo "[nexus-package] ✓ pushed ($AHEAD commits)"
    else
        echo "[nexus-package] ✓ already up to date"
    fi
else
    echo "[nexus-package] ⚠️ $NEXUS_DIR not found"
fi

# ⛔2026-08-27维护加装: push健康探针——"push真成功了吗"必须验证,不能跑完就算成功。
#   (教训: 回测大文件把push堵死两天+29个commit,每次"timed out"都没人查,靠维护体检才发现)
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio
BEHIND=$(git rev-list --count @{u}..HEAD 2>/dev/null || echo "?")
FAILFLAG=/tmp/push_all_failcount
if [ "$BEHIND" != "0" ]; then
    N=$(($(cat $FAILFLAG 2>/dev/null || echo 0)+1)); echo $N > $FAILFLAG
    echo "⛔ push探针: 本地仍领先 $BEHIND commits = push未成功 (连续第${N}次)"
    if [ "$N" -ge 2 ]; then
        SIG=~/.claude/nexus/signals/pending/sig-$(date +%Y%m%d-%H%M%S)-push_health-blocked.json
        printf '{"priority":"high","from":"push_health_probe","title":"sim-portfolio push连续%s次失败,本地领先%s commits","detail":"跑 git push 看完整报错;常见根因=大文件超GitHub限制(见feedback_system_ops §9)","expires":"%s"}
' "$N" "$BEHIND" "$(date -v+7d +%Y-%m-%d)" > "$SIG"
        echo "  → 已发signal: $SIG"
    fi
else
    rm -f $FAILFLAG
    echo "✓ push探针: 本地与远端一致"
fi

echo "═══════════════════════════════════════"
echo "  ✓ All repos synced"
echo "═══════════════════════════════════════"
