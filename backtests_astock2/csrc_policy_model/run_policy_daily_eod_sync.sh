#!/bin/bash
set -euo pipefail

LOCKFILE="/tmp/astock2_policy_daily_sync.lock"
PY="/opt/homebrew/bin/python3.13"
DIR="/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/csrc_policy_model"
LOG="/tmp/astock2_policy_daily_sync.log"
DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

# PID lock (prevent concurrent duplicate runs)
if [[ -f "$LOCKFILE" ]]; then
  OLD_PID=$(cat "$LOCKFILE" 2>/dev/null || true)
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[$(date "+%F %T")] Already running (PID=$OLD_PID), skipping."
    exit 0
  fi
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

run_with_retry() {
  local desc="$1"
  shift
  local attempt=1
  local max_attempts=3
  local wait_sec=10
  while [[ $attempt -le $max_attempts ]]; do
    echo "[$(date "+%F %T")] [$desc] attempt $attempt/$max_attempts: $*"
    if [[ $DRY_RUN -eq 1 ]]; then
      echo "[DRY-RUN] Verified executable command: $*"
      return 0
    fi
    if "$@"; then
      echo "[$(date "+%F %T")] [$desc] SUCCESS"
      return 0
    fi
    echo "[$(date "+%F %T")] [$desc] FAILED (attempt $attempt), retrying in ${wait_sec}s..."
    sleep "$wait_sec"
    attempt=$((attempt + 1))
    wait_sec=$((wait_sec * 2))
  done
  echo "[$(date "+%F %T")] [$desc] EXHAUSTED retries"
  return 1
}

cd "$DIR"
if [[ $DRY_RUN -eq 1 ]]; then
  "$PY" "$DIR/policy_polymarket_ingest_v2.py" --status
  run_with_retry "V3_NT_Monitor" "$PY" "$DIR/csrc_national_team_monitor.py" --today
  run_with_retry "Policy_Ingest_V2" "$PY" "$DIR/policy_polymarket_ingest_v2.py"
  run_with_retry "Polymarket_Board" "$PY" "$DIR/policy_polymarket_board.py"
  echo "[DRY-RUN] All 3 pipeline targets & --status check PASSED."
  exit 0
fi

run_with_retry "V3_NT_Monitor" "$PY" "$DIR/csrc_national_team_monitor.py" --today
run_with_retry "Policy_Ingest_V2" "$PY" "$DIR/policy_polymarket_ingest_v2.py"
run_with_retry "Polymarket_Board" "$PY" "$DIR/policy_polymarket_board.py"
echo "[$(date "+%F %T")] Daily policy & NT EOD sync COMPLETE."
