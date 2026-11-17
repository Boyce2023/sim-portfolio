# /// script
# requires-python = ">=3.11"
# ///
"""sync_nexus.py — Auto-sync portfolio_state.json → nexus-package after trades.
Uses core/compute.full_snapshot() — all computation in one place.

每次交易后自动调用，也可手动运行: uv run --script scripts/sync_nexus.py
"""

import json, subprocess, sys, os, tempfile
from pathlib import Path
from datetime import datetime

REPO_DIR = Path(__file__).parent.parent
NEXUS_DIR = Path("/Users/huaichuaibeimeng/claude-projects/nexus-package")
SOURCE = REPO_DIR / "portfolio_state.json"
TARGET = NEXUS_DIR / "output-buffer" / "sim-portfolio.json"
GIT = "/usr/bin/git"

sys.path.insert(0, str(REPO_DIR / "scripts"))
from core.compute import full_snapshot


def atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def git_push(a_nav, u_nav):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"sync: sim-portfolio {now} | A¥{a_nav:,.0f} | US${u_nav:,.2f}"
    try:
        subprocess.run([GIT, "add", "output-buffer/sim-portfolio.json"],
                       cwd=NEXUS_DIR, check=True, capture_output=True)
        result = subprocess.run([GIT, "diff", "--cached", "--quiet"],
                                cwd=NEXUS_DIR, capture_output=True)
        if result.returncode == 0:
            print("[sync] 无变化，跳过 git push")
            return
        subprocess.run([GIT, "commit", "-m", msg],
                       cwd=NEXUS_DIR, check=True, capture_output=True)
        subprocess.run([GIT, "push", "origin", "main"],
                       cwd=NEXUS_DIR, check=True, capture_output=True, timeout=30)
        print(f"[sync] git push 成功: {msg}")
    except subprocess.CalledProcessError as e:
        print(f"[sync] git push 失败: {e.stderr.decode()[:200]}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("[sync] git push 超时", file=sys.stderr)


def main():
    if not SOURCE.exists():
        print(f"[sync] {SOURCE} 不存在，跳过", file=sys.stderr)
        sys.exit(1)

    with open(SOURCE) as f:
        src = json.load(f)

    # ONE call replaces transform() + _build_positions() + _calc_total()
    out = full_snapshot(src)
    atomic_write(TARGET, out)

    # Use recalculated NAV values from full_snapshot output (Bug P10 fix)
    a_nav = out["accounts"]["a_share"]["total_assets"]
    u_nav = out["accounts"]["us"]["total_assets"]

    a_pos = len(out["accounts"]["a_share"]["positions"])
    u_pos = len(out["accounts"]["us"]["positions"])
    trades = len(out["trade_log"])
    snaps = len(out["daily_snapshots"])
    print(f"[sync] 已写入 {TARGET.name}: {a_pos}A股+{u_pos}美股持仓, {trades}笔交易, {snaps}天快照")

    git_push(a_nav, u_nav)


if __name__ == "__main__":
    main()
