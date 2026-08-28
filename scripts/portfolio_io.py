#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Portfolio I/O 模块 — portfolio_state.json 的唯一写入入口

任何对 portfolio_state.json 的修改都必须通过 save_portfolio()。
save_portfolio() 自动执行:
  1. 写入 portfolio_state.json
  2. 刷新 session_view_*.json
  3. sync_nexus.py → Railway
  4. git add + commit + push

其他脚本 import 这个模块:
  from portfolio_io import load_portfolio, save_portfolio
"""

import fcntl
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = REPO / "portfolio_state.json"
_LOCK_PATH = REPO / ".portfolio.lock"
_LOCK_FH = None  # 进程级持有, 退出时OS自动释放


def _acquire_lock(timeout: int = 90):
    """⛔2026-08-27 并发写修复(Buwen批准): 2026-08-25 美股与A股session同时写
    portfolio_state.json 发生lost update(美股LEU卖出被覆盖, 交易ID撞号TRD-0457,
    audit有记录而state没变)。所有读-改-写入口都先经load_portfolio, 故在此上排他锁,
    进程存续期持有, 退出自动释放 → 跨session交易串行化。超时报错而非静默等待。"""
    global _LOCK_FH
    if _LOCK_FH is not None:
        return
    fh = open(_LOCK_PATH, "w")
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _LOCK_FH = fh
            return
        except (OSError, BlockingIOError):
            if time.time() > deadline:
                fh.close()
                raise TimeoutError(
                    f"[portfolio_io] ⛔ {timeout}s内未取得portfolio锁 — "
                    "另一session可能正在交易或持锁进程挂死, 请稍后重试或检查 .portfolio.lock 持有者")
            time.sleep(0.5)


def load_portfolio() -> dict:
    _acquire_lock()
    try:
        with open(PORTFOLIO_PATH) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"[portfolio_io] ⛔ portfolio_state.json is corrupted: {e}")
        raise


def _normalize_numeric_fields(state: dict) -> None:
    """⛔根因修复(06-17): position数值字段强制float,防字符串污染SSOT。
    历史事故: 中国船舶stop_loss被写成'31.5'(字符串)→risk_monitor第500行 str>int 崩,
    daily_run fail gracefully吞了几天没发现。在此拦截=字符串再也进不了SSOT,顺带清洗存量脏数据。"""
    NUM_FIELDS = ("avg_cost", "stop_loss", "target_1", "target_2", "shares",
                  "current_price", "market_value", "cost_basis", "unrealized_pnl",
                  "unrealized_pnl_pct", "portfolio_pct", "prev_close", "change_pct")
    fixed = []
    for acc in state.get("accounts", {}).values():
        for p in acc.get("positions", []):
            for fld in NUM_FIELDS:
                v = p.get(fld)
                if isinstance(v, str) and v.strip() not in ("", "None"):
                    try:
                        p[fld] = float(v)
                        fixed.append(f"{p.get('ticker')}.{fld}")
                    except ValueError:
                        pass
    if fixed:
        print(f"[portfolio_io] 🔧 normalized字符串数值→float: {fixed}")


def save_portfolio(state: dict, reason: str = "portfolio update", auto_sync: bool = True):
    """
    写入 portfolio_state.json 并自动触发全链路同步。

    Args:
        state: 完整的 portfolio state dict
        reason: 变更原因(用于git commit message)
        auto_sync: 是否自动sync+push (默认True, 测试时可关闭)
    """
    # 0. 强制数值字段类型(根因修复: 防字符串污染SSOT, 顺带清洗存量脏数据)
    _normalize_numeric_fields(state)

    # 1. Atomic write portfolio_state.json (tmpfile → rename)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=PORTFOLIO_PATH.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, PORTFOLIO_PATH)
    except:
        os.unlink(tmp_path)
        raise
    print(f"[portfolio_io] ✓ portfolio_state.json saved (atomic)")

    if not auto_sync:
        return

    # 2. Refresh session views
    try:
        _refresh_session_views(state)
    except Exception as e:
        print(f"[portfolio_io] ⚠️ session_view refresh failed: {e}")

    # 3. Sync to nexus (Railway)
    try:
        sync_script = REPO / "scripts" / "sync_nexus.py"
        if sync_script.exists():
            result = subprocess.run(
                ["uv", "run", "--script", str(sync_script)],
                capture_output=True, text=True, timeout=60, cwd=str(REPO)
            )
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    print(f"[portfolio_io] {line}")
    except Exception as e:
        print(f"[portfolio_io] ⚠️ nexus sync failed: {e}")

    # 4. Git add + commit + push
    try:
        files_to_add = [
            "portfolio_state.json",
            "session_view_cn.json",
            "session_view_us.json",
            "session_view_all.json",
        ]
        subprocess.run(["git", "add"] + files_to_add, cwd=str(REPO), capture_output=True)

        commit_msg = f"auto: {reason}\n\nCo-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=str(REPO), capture_output=True, text=True
        )
        if result.returncode == 0:
            # ⛔2026-08-27修: 原版不查push的returncode, 失败也打"✓done" →
            #   28个commit静默积压无人知(SSL_ERROR_SYSCALL)。改为: 查码+重试2次+最终失败发telegram。
            pushed = False
            for attempt in range(3):
                pr = subprocess.run(["git", "push"], cwd=str(REPO),
                                    capture_output=True, text=True, timeout=120)
                if pr.returncode == 0:
                    pushed = True
                    break
                time.sleep(3)
            if pushed:
                print(f"[portfolio_io] ✓ git commit+push done")
            else:
                err = (pr.stderr or "")[:120]
                print(f"[portfolio_io] ⛔ git push 3次全败: {err}")
                try:
                    behind = subprocess.run(["git", "rev-list", "--count", "origin/main..HEAD"],
                                            cwd=str(REPO), capture_output=True, text=True, timeout=10).stdout.strip()
                    subprocess.run(["bash", os.path.expanduser("~/.claude/session-remote/fs-reply.sh"),
                                    f"[sim-portfolio] ⛔git push连续失败({err[:80]}), 本地积压{behind}个commit未上远端, 需人工看一眼"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True, timeout=30)  # fire-and-forget: capture_output遇孙进程握管道会挂(interview实弹教训)
                except Exception:
                    pass
        else:
            if "nothing to commit" in result.stdout:
                print(f"[portfolio_io] (no changes to commit)")
            else:
                print(f"[portfolio_io] ⚠️ git commit failed: {result.stderr[:100]}")
    except Exception as e:
        print(f"[portfolio_io] ⚠️ git push failed: {e}")


def revert_trades(trade_ids: list[str], reason: str = ""):
    """
    撤回交易 — 原子操作，自动触发全链路同步。
    """
    state = load_portfolio()
    trade_log = state.get("trade_log", [])
    reverted = []

    for tid in trade_ids:
        trade = next((t for t in trade_log if t.get("id") == tid), None)
        if not trade:
            print(f"[revert] ⚠️ {tid} not found, skipping")
            continue

        account_key = "a_share" if trade.get("account", "") in ("cn", "a_share") else "us"
        account = state["accounts"][account_key]
        ticker = trade["ticker"]
        shares = trade["shares"]
        action = trade["action"]

        if action == "buy":
            pos = next((pp for pp in account["positions"] if pp["ticker"] == ticker), None)
            if pos:
                cost = shares * pos["avg_cost"]
                if pos["shares"] == shares:
                    account["positions"].remove(pos)
                else:
                    pos["shares"] -= shares
                account["cash"] += cost
                print(f"[revert] ✓ {tid}: 删除 BUY {ticker} {shares}股, 返还 ¥{cost:,.0f}")
                reverted.append(tid)
            else:
                print(f"[revert] ⚠️ {tid}: position {ticker} not found")
        elif action == "sell":
            cost = shares * trade.get("price", 0)
            account["cash"] -= cost
            pos = next((pp for pp in account["positions"] if pp["ticker"] == ticker), None)
            if pos:
                pos["shares"] += shares
            else:
                account["positions"].append({
                    "ticker": ticker,
                    "name": trade.get("name", ticker),
                    "shares": shares,
                    "avg_cost": trade.get("price", 0),
                    "current_price": trade.get("price", 0),
                })
            print(f"[revert] ✓ {tid}: 恢复 SELL {ticker} {shares}股")
            reverted.append(tid)

        state["trade_log"] = [t for t in state["trade_log"] if t.get("id") != tid]

    state["pending_orders"] = []

    reason_text = reason or f"撤回 {', '.join(reverted)}"
    save_portfolio(state, reason=reason_text)
    return reverted


def _refresh_session_views(state: dict):
    """Rebuild session_view JSON files."""
    try:
        from session_view import build_view, build_all_view
        for mkt in ("cn", "us"):
            v = build_view(state, mkt)
            (REPO / f"session_view_{mkt}.json").write_text(
                json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        av = build_all_view(state)
        (REPO / "session_view_all.json").write_text(
            json.dumps(av, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[portfolio_io] ✓ session_views refreshed")
    except ImportError:
        pass
    except Exception as e:
        print(f"[portfolio_io] ⚠️ session_view: {e}")
