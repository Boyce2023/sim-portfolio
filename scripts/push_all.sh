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

echo "═══════════════════════════════════════"
echo "  ✓ All repos synced"
echo "═══════════════════════════════════════"
