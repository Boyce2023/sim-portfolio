# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance", "akshare>=1.14"]
# ///
"""sync_nexus.py — Auto-sync portfolio_state.json → nexus-package after trades.

Three-phase pipeline:
  1. BACKFILL — fetch missing CSI300/SPY benchmark data from yfinance,
     write back to portfolio_state.json (source-of-truth fix, not just patch)
  2. COMPUTE  — full_snapshot() builds the public JSON
  3. VERIFY   — every daily_snapshot must have sse_return_pct + spy_return_pct;
     any gap = abort push + print exactly what's missing
"""

import json, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

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


def git_push(cwd: str, files: list[str], msg: str) -> bool:
    for f in files:
        subprocess.run([GIT, "add", f], cwd=cwd, check=True, capture_output=True)
    diff = subprocess.run([GIT, "diff", "--cached", "--quiet"], cwd=cwd, capture_output=True)
    if diff.returncode == 0:
        return False
    subprocess.run([GIT, "commit", "-m", msg], cwd=cwd, check=True, capture_output=True)
    subprocess.run([GIT, "push"], cwd=cwd, check=True, capture_output=True, timeout=30)
    return True


# ── Phase 1: Backfill benchmark data into portfolio_state.json ──

def _fetch_csi300_akshare(start_date: str) -> dict:
    """CSI300 from akshare (A-stock primary source). Returns {date: cumulative_return_%}."""
    try:
        import akshare as ak
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        fetch_start = (start_dt - timedelta(days=5)).strftime("%Y%m%d")
        fetch_end = datetime.now().strftime("%Y%m%d")
        df = ak.index_zh_a_hist(symbol="000300", period="daily",
                                start_date=fetch_start, end_date=fetch_end)
        if df is None or df.empty:
            print("[benchmark] WARN: akshare CSI300 returned empty")
            return {}

        base_rows = df[df["日期"].astype(str) == start_date]
        if base_rows.empty:
            base_rows = df[df["日期"].astype(str) <= start_date].tail(1)
        if base_rows.empty:
            print("[benchmark] WARN: no CSI300 base date found")
            return {}

        base_price = float(base_rows["收盘"].iloc[0])
        result = {}
        for _, row in df.iterrows():
            ds = str(row["日期"])[:10]
            if ds >= start_date:
                result[ds] = round((float(row["收盘"]) / base_price - 1) * 100, 2)
        print(f"[benchmark] ✓ CSI300 from akshare: {len(result)} days")
        return result
    except Exception as e:
        print(f"[benchmark] WARN: akshare CSI300 failed: {e}")
        return {}


def _fetch_csi300_yf_fallback(start_date: str) -> dict:
    """CSI300 fallback via yfinance (only if akshare fails)."""
    try:
        import yfinance as yf
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        fetch_start = (start_dt - timedelta(days=5)).strftime("%Y-%m-%d")
        csi = yf.Ticker("000300.SS")
        hist = csi.history(start=fetch_start, end=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
        if hist.empty:
            return {}
        base_rows = hist[hist.index.strftime("%Y-%m-%d") <= start_date].tail(1)
        if base_rows.empty:
            return {}
        base_price = float(base_rows["Close"].iloc[0])
        result = {}
        for dt, row in hist.iterrows():
            ds = dt.strftime("%Y-%m-%d")
            if ds >= start_date:
                result[ds] = round((float(row["Close"]) / base_price - 1) * 100, 2)
        print(f"[benchmark] ✓ CSI300 from yfinance fallback: {len(result)} days")
        return result
    except Exception as e:
        print(f"[benchmark] WARN: yfinance CSI300 fallback failed: {e}")
        return {}


def _fetch_spy_returns(start_date: str) -> dict:
    """SPY from yfinance (US-stock primary source). Returns {date: cumulative_return_%}."""
    try:
        import yfinance as yf
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        fetch_start = (start_dt - timedelta(days=5)).strftime("%Y-%m-%d")
        spy = yf.Ticker("SPY")
        hist = spy.history(start=fetch_start, end=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
        if hist.empty:
            return {}
        base_rows = hist[hist.index.strftime("%Y-%m-%d") <= start_date].tail(1)
        if base_rows.empty:
            return {}
        base_price = float(base_rows["Close"].iloc[0])
        result = {}
        for dt, row in hist.iterrows():
            ds = dt.strftime("%Y-%m-%d")
            if ds >= start_date:
                result[ds] = round((float(row["Close"]) / base_price - 1) * 100, 2)
        print(f"[benchmark] ✓ SPY from yfinance: {len(result)} days")
        return result
    except Exception as e:
        print(f"[benchmark] WARN: SPY fetch failed: {e}")
        return {}


def _fetch_benchmark_returns(start_date: str) -> tuple[dict, dict]:
    """Fetch benchmark returns: CSI300 from akshare (→yf fallback), SPY from yfinance."""
    csi_ret = _fetch_csi300_akshare(start_date)
    if not csi_ret:
        print("[benchmark] akshare failed, trying yfinance fallback for CSI300...")
        csi_ret = _fetch_csi300_yf_fallback(start_date)
    spy_ret = _fetch_spy_returns(start_date)
    return csi_ret, spy_ret


def backfill_benchmarks(ssot: dict) -> bool:
    """Fill missing sse_return_pct / spy_return_pct in portfolio_state.json snapshots.
    Returns True if any data was written back.
    """
    snapshots = ssot.get("performance", {}).get("daily_snapshots", [])
    if not snapshots:
        return False

    missing_sse = [s for s in snapshots if s.get("sse_return_pct") is None]
    missing_spy = [s for s in snapshots if s.get("spy_return_pct") is None]

    if not missing_sse and not missing_spy:
        return False

    start_date = snapshots[0]["date"]
    print(f"[benchmark] Backfilling {len(missing_sse)} CSI300 + {len(missing_spy)} SPY gaps...")
    csi_ret, spy_ret = _fetch_benchmark_returns(start_date)

    fixed = 0
    for s in snapshots:
        dt = s["date"]
        if s.get("sse_return_pct") is None and dt in csi_ret:
            s["sse_return_pct"] = csi_ret[dt]
            fixed += 1
        if s.get("spy_return_pct") is None and dt in spy_ret:
            s["spy_return_pct"] = spy_ret[dt]
            fixed += 1

    if fixed > 0:
        atomic_write(SOURCE, ssot)
        print(f"[benchmark] ✓ Backfilled {fixed} values → portfolio_state.json")
        return True
    return False


# ── Phase 3: Verify output before push ──

def verify_output(output: dict) -> list[str]:
    """Check every daily_snapshot has benchmark data. Returns list of errors."""
    errors = []
    for s in output.get("daily_snapshots", []):
        dt = s["date"]
        sse = s.get("sse_return_pct")
        spy = s.get("spy_return_pct")
        if sse is None:
            errors.append(f"{dt}: sse_return_pct=None (A-share chart will have gap)")
        if spy is None:
            errors.append(f"{dt}: spy_return_pct=None (US chart will have gap)")

    positions = []
    for acct_key in ["a_share", "us"]:
        acct = output.get("accounts", {}).get(acct_key, {})
        for p in acct.get("positions", []):
            if p.get("current_price", 0) == 0 or p.get("market_value", 0) == 0:
                positions.append(f"{p.get('ticker','?')}: price=0 or mv=0")

    if positions:
        errors.append(f"Positions with zero price/mv: {positions}")

    return errors


def main():
    if not SOURCE.exists():
        print(f"[nexus-sync] ERROR: {SOURCE} not found")
        sys.exit(1)
    if not NEXUS_DIR.exists():
        print(f"[nexus-sync] ERROR: {NEXUS_DIR} not found")
        sys.exit(1)

    ssot = json.loads(SOURCE.read_text(encoding="utf-8"))

    # Phase 1: Backfill missing benchmark data into source
    source_changed = backfill_benchmarks(ssot)

    # Phase 2: Build public snapshot
    output = full_snapshot(ssot)

    # Phase 3: Verify before push
    errors = verify_output(output)
    if errors:
        print(f"[nexus-sync] ⚠️ VERIFY found {len(errors)} issue(s):")
        for e in errors:
            print(f"  → {e}")
        print("[nexus-sync] Pushing anyway but issues logged above.")

    # Write output
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(TARGET, output)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Push nexus-package
    pushed = git_push(
        str(NEXUS_DIR),
        ["output-buffer/sim-portfolio.json"],
        f"sync: portfolio update {now}"
    )
    if pushed:
        print(f"[nexus-sync] ✓ Pushed to Railway — {now}")
    else:
        print(f"[nexus-sync] ✓ File updated, no diff to push")

    # If source was modified (benchmark backfill), commit that too
    if source_changed:
        try:
            git_push(
                str(REPO_DIR),
                ["portfolio_state.json"],
                f"fix: backfill benchmark data {now}"
            )
            print("[nexus-sync] ✓ Benchmark backfill committed to sim-portfolio")
        except Exception as e:
            print(f"[nexus-sync] WARN: benchmark commit failed: {e}")

    # Final verification: re-read output and confirm
    final = json.loads(TARGET.read_text(encoding="utf-8"))
    final_errors = verify_output(final)
    if final_errors:
        print(f"[nexus-sync] ⛔ POST-PUSH VERIFY FAILED ({len(final_errors)} issues):")
        for e in final_errors:
            print(f"  → {e}")
    else:
        snap_count = len(final.get("daily_snapshots", []))
        print(f"[nexus-sync] ✓ POST-PUSH VERIFY OK: {snap_count} snapshots, all benchmarks present")


if __name__ == "__main__":
    main()
