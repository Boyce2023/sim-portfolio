# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance"]
# ///
"""sync_nexus.py — Auto-sync portfolio_state.json → nexus-package after trades.
Uses core/compute.full_snapshot() as the single computation source.

每次交易后自动调用，也可手动运行: uv run --script scripts/sync_nexus.py
"""

import json, subprocess, sys, os
from pathlib import Path
from datetime import datetime, timezone

REPO_DIR = Path(__file__).parent.parent
NEXUS_DIR = Path("/Users/huaichuaibeimeng/claude-projects/nexus-package")
SOURCE = REPO_DIR / "portfolio_state.json"
TARGET = NEXUS_DIR / "output-buffer" / "sim-portfolio.json"
GIT = "/usr/bin/git"

sys.path.insert(0, str(REPO_DIR / "scripts"))
from core.compute import full_snapshot


def atomic_write(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def git_push(msg: str):
    cwd = str(NEXUS_DIR)
    subprocess.run([GIT, "add", "output-buffer/sim-portfolio.json"], cwd=cwd, check=True, capture_output=True)
    diff = subprocess.run([GIT, "diff", "--cached", "--quiet"], cwd=cwd, capture_output=True)
    if diff.returncode == 0:
        print("[nexus-sync] No changes to push")
        return False
    subprocess.run([GIT, "commit", "-m", msg], cwd=cwd, check=True, capture_output=True)
    subprocess.run([GIT, "push"], cwd=cwd, check=True, capture_output=True, timeout=30)
    return True


def main():
    if not SOURCE.exists():
        print(f"[nexus-sync] ERROR: {SOURCE} not found")
        sys.exit(1)
    if not NEXUS_DIR.exists():
        print(f"[nexus-sync] ERROR: {NEXUS_DIR} not found")
        sys.exit(1)

    ssot = json.loads(SOURCE.read_text(encoding="utf-8"))
    output = full_snapshot(ssot)

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(TARGET, output)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pushed = git_push(f"sync: portfolio update {now}")
    if pushed:
        print(f"[nexus-sync] ✓ Pushed to Railway — {now}")
    else:
        print(f"[nexus-sync] ✓ File updated, no diff to push")


if __name__ == "__main__":
    main()
