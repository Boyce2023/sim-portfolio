# /// script
# requires-python = ">=3.11"
# ///
"""
sync_nexus.py — 将 portfolio_state.json 转换并同步到 nexus-package dashboard
每次交易后自动调用，也可手动运行: uv run --script scripts/sync_nexus.py
"""

import json, subprocess, sys, os, tempfile
from pathlib import Path
from datetime import datetime

REPO_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
NEXUS_DIR = Path("/Users/huaichuaibeimeng/claude-projects/nexus-package")
SOURCE = REPO_DIR / "portfolio_state.json"
TARGET = NEXUS_DIR / "output-buffer" / "sim-portfolio.json"
GIT = "/usr/bin/git"


def cn_ticker_suffix(ticker: str) -> str:
    return f"{ticker}.SS" if ticker.startswith("6") else f"{ticker}.SZ"


def _build_positions(acct, acct_key):
    """合并 positions + short_positions，空头用负shares表示。"""
    result = []
    for p in acct.get("positions", []):
        ticker = cn_ticker_suffix(p["ticker"]) if acct_key == "a_share" else p["ticker"]
        cp = p.get("current_price", p["avg_cost"])
        result.append({
            "ticker": ticker,
            "name": p.get("name", ""),
            "shares": p["shares"],
            "avg_cost": round(p["avg_cost"], 4),
            "current_price": round(cp, 4),
            "market_value": round(p["shares"] * cp, 2),
            "unrealized_pnl_pct": round((cp - p["avg_cost"]) / p["avg_cost"] * 100, 2) if p["avg_cost"] else 0,
            "portfolio_pct": p.get("portfolio_pct", 0),
            "entry_date": p.get("entry_date", ""),
            "type": p.get("type", ""),
            "sector": p.get("sector", ""),
        })
    for p in acct.get("short_positions", []):
        ticker = p["ticker"]
        entry_price = p.get("entry_price", p.get("avg_cost", 0))
        cp = p.get("current_price", entry_price)
        pnl_pct = round((entry_price - cp) / entry_price * 100, 2) if entry_price else 0
        result.append({
            "ticker": ticker,
            "name": p.get("name", ""),
            "shares": -p["shares"],
            "avg_cost": round(entry_price, 4),
            "current_price": round(cp, 4),
            "market_value": round(-(p["shares"] * cp), 2),
            "unrealized_pnl_pct": pnl_pct,
            "portfolio_pct": p.get("portfolio_pct", 0),
            "entry_date": p.get("entry_date", ""),
            "type": "short",
            "sector": p.get("sector", ""),
        })
    return result


def _calc_total(acct):
    """从原始数据重新计算total_assets，确保一致性。"""
    sys.path.insert(0, str(REPO_DIR / "scripts"))
    from nav_calc import calc_nav
    return calc_nav(acct)["total_assets"]


def transform(src: dict) -> dict:
    meta = src.get("_meta", {})
    a = src["accounts"]["a_share"]
    u = src["accounts"]["us"]

    a_total = _calc_total(a)
    u_total = _calc_total(u)
    a_initial = a.get("initial_capital", 1000000)
    u_initial = u.get("initial_capital", 150000)

    out = {
        "meta": {
            "type": "sim_portfolio",
            "description": "Claude AI模拟盘 — ¥1M A股 + $150K 美股",
            "start_date": meta.get("start_date", "2026-05-18"),
            "end_date": meta.get("end_date", "2026-06-18"),
            "last_updated": meta.get("last_updated", datetime.now().isoformat()),
            "benchmark": {"a_share": "CSI300", "us": "SPY"},
            "disclaimer": "模拟盘，非真实交易。仅供研究参考。",
        },
        "accounts": {
            "a_share": {
                "currency": "CNY",
                "initial_capital": a_initial,
                "total_assets": a_total,
                "cash": round(a.get("cash", 0), 2),
                "realized_pnl": round(a.get("realized_pnl", 0), 2),
                "return_pct": round((a_total / a_initial - 1) * 100, 2),
                "positions": _build_positions(a, "a_share"),
            },
            "us": {
                "currency": "USD",
                "initial_capital": u_initial,
                "total_assets": u_total,
                "cash": round(u.get("cash", 0), 2),
                "realized_pnl": round(u.get("realized_pnl", 0), 2),
                "return_pct": round((u_total / u_initial - 1) * 100, 2),
                "positions": _build_positions(u, "us"),
            },
        },
        "daily_snapshots": [],
        "trade_log": [],
    }

    # daily snapshots
    for snap in src.get("performance", {}).get("daily_snapshots", []):
        a_nav = snap.get("a_share_nav", 1000000)
        u_nav = snap.get("us_nav", 150000)
        a_ret = snap.get("a_share_return_pct", 0)
        u_ret = snap.get("us_return_pct", 0)
        combined = round(a_ret * 0.87 + u_ret * 0.13, 2)
        out["daily_snapshots"].append({
            "date": snap["date"],
            "a_share": {"total_assets": a_nav, "return_pct": a_ret},
            "us": {"total_assets": u_nav, "return_pct": u_ret},
            "combined_return_pct": combined,
        })

    # trade log
    for t in src.get("trade_log", []):
        date_str = t.get("date", t.get("timestamp", "")[:10])
        entry = {
            "date": date_str,
            "account": t.get("account", ""),
            "action": t.get("action", ""),
            "ticker": t.get("ticker", ""),
            "name": t.get("name", ""),
            "shares": t.get("shares", 0),
            "price": t.get("price", 0),
        }
        if t.get("realized_pnl") is not None:
            entry["realized_pnl"] = t["realized_pnl"]
        out["trade_log"].append(entry)

    return out


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

    out = transform(src)
    atomic_write(TARGET, out)

    a_nav = src["accounts"]["a_share"]["total_assets"]
    u_nav = src["accounts"]["us"]["total_assets"]
    a_pos = len(src["accounts"]["a_share"].get("positions", []))
    u_pos = len(src["accounts"]["us"].get("positions", []))
    trades = len(src.get("trade_log", []))
    snaps = len(out["daily_snapshots"])

    print(f"[sync] 已写入 {TARGET.name}: {a_pos}A股+{u_pos}美股持仓, {trades}笔交易, {snaps}天快照")

    git_push(a_nav, u_nav)


if __name__ == "__main__":
    main()
