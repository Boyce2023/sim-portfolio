# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
信念评分卡 + Victory Protocol — Claude模拟盘
Pain系统(Circuit Breaker + Pain Memory) + Reward系统(Conviction Amplifier + Victory Memory + PlayBook)

用法:
    uv run --script scripts/conviction_check.py                    # 显示完整scorecard (美股)
    uv run --script scripts/conviction_check.py --market cn        # A股模式
    uv run --script scripts/conviction_check.py --update           # 重算所有状态
    uv run --script scripts/conviction_check.py --post-mortem --ticker NVDA --loss-pct 8.5 --grade A --pod A
    uv run --script scripts/conviction_check.py --win --ticker CEG --gain-pct 12.0 --grade A+
    uv run --script scripts/conviction_check.py --victory --ticker MU --gain-pct 15.0 --r-multiple 2.5 --grade A+ --strategy MOM_ROTATION --mfe-capture 72
    uv run --script scripts/conviction_check.py --grade-trade --ticker MU --process-grade A --reason "followed MOM rebalance rule exactly"
    uv run --script scripts/conviction_check.py --hold-review      # 反处置效应: 持仓Review (美股)
    uv run --script scripts/conviction_check.py --hold-review --market cn  # 反处置效应: 持仓Review (A股)
    uv run --script scripts/conviction_check.py --playbook         # 显示赢家模式库 (美股)
    uv run --script scripts/conviction_check.py --playbook --market cn     # A股赢家模式库
"""

from __future__ import annotations

import json
import sys
import argparse
from datetime import date, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 路径配置
# ──────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SCORECARD_PATH_US = PROJECT_ROOT / "conviction_scorecard.json"
SCORECARD_PATH_CN = PROJECT_ROOT / "conviction_scorecard_cn.json"
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio_state.json"
PAIN_MEMORY_PATH = PROJECT_ROOT / "pain_memory.md"
VICTORY_MEMORY_PATH = PROJECT_ROOT / "victory_memory.md"
PLAYBOOK_PATH = PROJECT_ROOT / "playbook.json"
PLAYBOOK_ASTOCK_PATH = PROJECT_ROOT / "playbook_astock.json"

# ── A股 SABCD 评级参数 ──
CN_ATR_K = {
    "S": 3.5, "A+": 3.0, "A": 3.0, "A-": 2.5,
    "B+": 2.0, "B": 2.0, "B-": 1.5,
}
CN_MAX_STOP = {
    "S": -0.20, "A+": -0.18, "A": -0.15, "A-": -0.15,
    "B+": -0.12, "B": -0.10, "B-": -0.10,
}

# ── Pain System: Circuit Breaker 阈值 ──
CB_RED_DRAWDOWN = 5.0
CB_YELLOW_DRAWDOWN = 3.0
CB_RED_LOSSES = 3
CB_YELLOW_LOSSES = 2
CB_RECOVERY_WEEKS = 2
RESTRICTION_DAYS = 30
RESTRICTION_LIFT_WINS = 3

# ── Reward System: Conviction Amplifier 阈值 ──
CA_ELEVATED_A_RATE = 0.60     # A-grade率≥60% → ELEVATED
CA_ELEVATED_EXPECTANCY = 0.5  # R期望值>0.5 → ELEVATED
CA_PEAK_A_RATE = 0.75         # A-grade率≥75% → PEAK
CA_PEAK_EXPECTANCY = 1.0      # R期望值>1.0 → PEAK
CA_PEAK_A_STREAK = 5          # 连续A-grade≥5 → PEAK
CA_ELEVATED_MULTIPLIER = 1.25 # ELEVATED sizing ×1.25
CA_PEAK_MULTIPLIER = 1.50     # PEAK sizing ×1.5
VICTORY_MEMORY_MAX = 5        # rolling window
R_MULTIPLE_ROLLING = 20       # rolling 20 trades for expectancy
MFE_WARNING_THRESHOLD = 0.40  # MFE capture <40% = systematic early exits


# ──────────────────────────────────────────────────────────────────────────────
# 数据加载 / 保存
# ──────────────────────────────────────────────────────────────────────────────
def _scorecard_path(market: str = "us") -> Path:
    return SCORECARD_PATH_CN if market == "cn" else SCORECARD_PATH_US


def load_scorecard(market: str = "us") -> dict:
    path = _scorecard_path(market)
    if not path.exists():
        print(f"ERROR: scorecard not found at {path}", file=sys.stderr)
        sys.exit(2)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_scorecard(data: dict, market: str = "us") -> None:
    data["last_updated"] = date.today().isoformat()
    path = _scorecard_path(market)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_portfolio() -> dict:
    if not PORTFOLIO_PATH.exists():
        return {}
    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_pain_memory_raw() -> str:
    if not PAIN_MEMORY_PATH.exists():
        return ""
    return PAIN_MEMORY_PATH.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Pain Memory 解析
# ──────────────────────────────────────────────────────────────────────────────
def _strip_html_comments(text: str) -> str:
    """Remove HTML comment blocks (<!-- ... -->) from text."""
    import re
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def parse_pain_memory(raw: str) -> tuple[int, dict | None]:
    """
    Returns (post_mortem_count, latest_pm_dict).
    latest_pm_dict keys: ticker, date, loss_pct, summary
    """
    raw = _strip_html_comments(raw)
    lines = raw.splitlines()
    pm_blocks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("### PM-"):
            if current:
                pm_blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        pm_blocks.append(current)

    count = len(pm_blocks)
    if count == 0:
        return 0, None

    # Parse the first (most recent) block
    first = pm_blocks[0]
    header = first[0]  # "### PM-1 | NVDA | 2026-05-20 | -8.5%"
    parts = [p.strip() for p in header.lstrip("#").strip().split("|")]
    ticker = parts[1] if len(parts) > 1 else "?"
    pm_date = parts[2] if len(parts) > 2 else "?"
    loss_raw = parts[3] if len(parts) > 3 else "?"

    # Build 1-line summary from first question answer
    summary_line = ""
    in_q1 = False
    for line in first[1:]:
        if "1. 哪里判断错了" in line or "**1." in line:
            in_q1 = True
            continue
        if in_q1 and line.strip() and not line.startswith("**2.") and not line.startswith("**Pattern"):
            summary_line = line.strip()
            break
        if "**2." in line:
            break

    return count, {
        "ticker": ticker,
        "date": pm_date,
        "loss_pct": loss_raw,
        "summary": summary_line or "（无详情）",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio — recent trade history (for context only)
# ──────────────────────────────────────────────────────────────────────────────
def get_us_positions(portfolio: dict) -> list[dict]:
    return (
        portfolio.get("accounts", {})
        .get("us", {})
        .get("positions", [])
    )


def get_cn_positions(portfolio: dict) -> list[dict]:
    return (
        portfolio.get("accounts", {})
        .get("a_share", {})
        .get("positions", [])
    )


# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker 计算
# ──────────────────────────────────────────────────────────────────────────────
def compute_cb_state(cb: dict) -> str:
    """
    Returns "RED" | "YELLOW" | "GREEN" based on current cb fields.
    Does not apply recovery upgrade — that's done in update_cb.
    """
    weekly_dd = float(cb.get("weekly_drawdown_pct", 0.0))
    consec = int(cb.get("consecutive_losses", 0))

    if weekly_dd > CB_RED_DRAWDOWN or consec >= CB_RED_LOSSES:
        return "RED"
    if weekly_dd > CB_YELLOW_DRAWDOWN or consec >= CB_YELLOW_LOSSES:
        return "YELLOW"
    return "GREEN"


def update_cb_state(scorecard: dict) -> str:
    """
    Recalculate circuit breaker state:
    1. Base state from thresholds
    2. Apply recovery upgrade if applicable
    3. Write back to scorecard
    Returns new state string.
    """
    cb = scorecard["circuit_breaker"]
    base_state = compute_cb_state(cb)

    # Recovery upgrade
    recovery_weeks = int(cb.get("recovery_weeks_clean", 0))
    current_state = cb.get("state", "GREEN")

    new_state = base_state
    if base_state in ("YELLOW", "RED") and recovery_weeks >= CB_RECOVERY_WEEKS:
        # Upgrade one level: RED → YELLOW → GREEN
        if base_state == "RED":
            new_state = "YELLOW"
        elif base_state == "YELLOW":
            new_state = "GREEN"

    cb["state"] = new_state
    return new_state


# ──────────────────────────────────────────────────────────────────────────────
# Grade 精度跟踪（rolling 10笔近似）
# ──────────────────────────────────────────────────────────────────────────────
def get_grade_tier(grade: str) -> str:
    """Returns 'A+_A' for A+ or A grades, 'B+_B' for B+ or B."""
    g = grade.strip().upper()
    if g in ("A+", "A", "A-"):
        return "A+_A"
    return "B+_B"


def accuracy_str(wins: int, losses: int) -> str:
    total = wins + losses
    if total == 0:
        return "0/0 = N/A"
    pct = wins / total * 100
    return f"{wins}/{total} = {pct:.0f}%"


# ──────────────────────────────────────────────────────────────────────────────
# 输出 Scorecard
# ──────────────────────────────────────────────────────────────────────────────
CB_ICONS = {"GREEN": "🟢 GREEN", "YELLOW": "🟡 YELLOW", "RED": "🔴 RED"}


def print_scorecard(scorecard: dict, pain_count: int, latest_pm: dict | None, market: str = "us") -> None:
    cb = scorecard["circuit_breaker"]
    restrictions = scorecard["grade_restrictions"]
    ga = scorecard["grade_accuracy"]
    ob = scorecard["override_budget"]

    state = cb.get("state", "GREEN")
    consec_losses = int(cb.get("consecutive_losses", 0))
    weekly_dd = float(cb.get("weekly_drawdown_pct", 0.0))

    ap_allowed = restrictions.get("A+_allowed", True)
    a_allowed = restrictions.get("A_allowed", True)
    global_downgrade = restrictions.get("global_downgrade", False)

    # Grade accuracy
    aa = ga.get("A+_A", {})
    bb = ga.get("B+_B", {})
    aa_wins = int(aa.get("wins", 0))
    aa_losses = int(aa.get("losses", 0))
    bb_wins = int(bb.get("wins", 0))
    bb_losses = int(bb.get("losses", 0))

    or_wins = int(ob.get("override_record", {}).get("wins", 0))
    or_losses = int(ob.get("override_record", {}).get("losses", 0))
    or_total = or_wins + or_losses
    or_pct_str = f"{or_wins / or_total * 100:.0f}%" if or_total > 0 else "N/A"
    override_budget_used = int(ob.get("used_this_week", 0))
    override_budget_total = int(ob.get("per_week", 1))

    market_label = "A股 [cn]" if market == "cn" else "美股 [us]"
    print()
    print(f"=== CONVICTION SCORECARD ({market_label}) ===")
    print(f"Circuit Breaker: {CB_ICONS.get(state, state)}")
    print(f"连续止损次数: {consec_losses}  |  本周drawdown: {weekly_dd:.1f}%")
    print(
        f"评级权限: A+ [{'✓' if ap_allowed else '✗'}] | "
        f"A [{'✓' if a_allowed else '✗'}] | "
        f"全线降级 [{'Y' if global_downgrade else 'N'}]"
    )
    if not ap_allowed or not a_allowed:
        expires = restrictions.get("restriction_expires")
        reason = restrictions.get("restriction_reason", "")
        if expires:
            print(f"  ⚠ 限制原因: {reason}  |  解除日期: {expires}")

    print()
    print("── Pain System ──")
    print("最近止损 (pain_memory):")
    if latest_pm:
        summary = latest_pm["summary"]
        if len(summary) > 60:
            summary = summary[:57] + "..."
        print(
            f"  {latest_pm['ticker']} | {latest_pm['date']} | "
            f"{latest_pm['loss_pct']} | {summary}"
        )
    else:
        print("  无止损记录")

    # ── Victory Protocol Section ──
    print()
    print("── Victory Protocol ──")

    # Conviction Amplifier
    ca = scorecard.get("conviction_amplifier", {})
    ca_state = ca.get("state", "NORMAL")
    ca_icon = CA_ICONS.get(ca_state, ca_state)
    multiplier = ca.get("sizing_multiplier", 1.0)
    consec_wins = int(ca.get("consecutive_wins", 0))
    print(f"Conviction Amplifier: {ca_icon} (sizing ×{multiplier:.2f})")
    print(f"连续胜利: {consec_wins}  |  A-grade连续: {ca.get('consecutive_a_grades', 0)}")

    # Victory Memory
    vm_raw = load_victory_memory_raw()
    vm_count, latest_vm = parse_victory_memory(vm_raw)
    print(f"\n最近胜利 (victory_memory): {vm_count}条")
    if latest_vm:
        print(f"  {latest_vm['ticker']} | {latest_vm['date']} | {latest_vm['gain_pct']} | {latest_vm['r_multiple']}")
    else:
        print("  无胜利记录")

    # R-Multiple Dashboard (filtered by market)
    rm_all = scorecard.get("r_multiple_log", {}).get("trades", [])
    mkt_key = "cn" if market == "cn" else "us"
    rm_filtered = [t for t in rm_all if t.get("market", "us") == mkt_key]
    rm_recent = rm_filtered[-R_MULTIPLE_ROLLING:]
    if rm_recent:
        rs = [t["r_multiple"] for t in rm_recent]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]
        wr = len(wins) / len(rs) if rs else 0
        aw = sum(wins) / len(wins) if wins else 0
        al = sum(losses) / len(losses) if losses else 0
        exp = (wr * aw) + ((1 - wr) * al)
        print(f"\nR-Multiple (rolling {len(rm_recent)}笔):")
        print(f"  胜率: {wr:.1%} | 均赢: +{aw:.1f}R | 均亏: {al:.1f}R | 期望值: {exp:+.3f}R")
        best_r_trade = max(rm_recent, key=lambda t: t["r_multiple"])
        if best_r_trade["r_multiple"] > 0:
            print(f"\n🏆 最佳单笔: +{best_r_trade['r_multiple']:.1f}R ({best_r_trade['ticker']})")
    else:
        print(f"\nR-Multiple: 无{market_label}交易记录")

    # MFE (filtered by market)
    mfe_vals = [t["mfe_capture_pct"] for t in rm_filtered if t.get("mfe_capture_pct") is not None]
    if mfe_vals:
        avg_mfe = sum(mfe_vals) / len(mfe_vals)
        mfe_flag = " ⚠ 过早卖出!" if avg_mfe < 40 else ""
        print(f"MFE Capture: {avg_mfe:.0f}%{mfe_flag}")

    # Trade Process Grades
    tg = scorecard.get("trade_grades", {})
    r10 = tg.get("rolling_10", {})
    if sum(r10.get(g, 0) for g in ("A", "B", "C")) > 0:
        a_pct = float(r10.get("a_grade_pct", 0))
        print(f"\nProcess Grade (rolling 10笔): A={r10.get('A',0)} B={r10.get('B',0)} C={r10.get('C',0)} → A-rate={a_pct:.0%}")

    # Streaks
    streaks = tg.get("streaks", {})
    cur_a = int(streaks.get("current_a_streak", 0))
    best_a = int(streaks.get("longest_a_streak", 0))
    if best_a > 0:
        print(f"A-grade连续: 当前{cur_a} | 最长{best_a}")

    # PlayBook summary
    pb = load_playbook(market)
    validated = [p for p in pb.get("patterns", []) if p.get("status") == "validated"]
    if validated:
        print(f"\n📖 PlayBook: {len(validated)}个验证模式")
        for p in validated:
            print(f"  {p['id']}: {p['name']} (胜率{p.get('win_rate_backtest',0):.0%}, 均R +{p.get('avg_r_multiple',0):.1f})")

    print()
    print("── 综合 ──")
    print("Grade准确率 (rolling 10笔):")
    print(f"  A+/A: {accuracy_str(aa_wins, aa_losses)}")
    print(f"  B+/B: {accuracy_str(bb_wins, bb_losses)}")

    print()
    or_record_str = f"{or_wins}W / {or_losses}L = {or_pct_str}"
    print(f"Discovery Override战绩: {or_record_str}")
    print(f"Override预算: {override_budget_used}次/周 (上限{override_budget_total}次)")
    print()


# ──────────────────────────────────────────────────────────────────────────────
# --update 逻辑
# ──────────────────────────────────────────────────────────────────────────────
def handle_update(scorecard: dict, market: str = "us") -> None:
    new_state = update_cb_state(scorecard)
    save_scorecard(scorecard, market)
    icon = CB_ICONS.get(new_state, new_state)
    print(f"[update] Circuit Breaker → {icon}")
    print(f"  consecutive_losses={scorecard['circuit_breaker']['consecutive_losses']}  "
          f"weekly_drawdown={scorecard['circuit_breaker']['weekly_drawdown_pct']:.1f}%  "
          f"recovery_weeks_clean={scorecard['circuit_breaker']['recovery_weeks_clean']}")


# ──────────────────────────────────────────────────────────────────────────────
# --post-mortem 逻辑
# ──────────────────────────────────────────────────────────────────────────────
def handle_post_mortem(scorecard: dict, ticker: str, loss_pct: float, grade: str, pod: str, market: str = "us") -> None:
    cb = scorecard["circuit_breaker"]
    restrictions = scorecard["grade_restrictions"]
    ga = scorecard["grade_accuracy"]

    # 1. Increment consecutive_losses
    cb["consecutive_losses"] = int(cb.get("consecutive_losses", 0)) + 1
    cb["recovery_weeks_clean"] = 0  # Reset recovery on any loss
    cb["last_triggered"] = date.today().isoformat()

    # 2. Update grade_accuracy — add a loss for the tier
    tier = get_grade_tier(grade)
    if tier == "A+_A":
        ga["A+_A"]["losses"] = int(ga["A+_A"].get("losses", 0)) + 1
    else:
        ga["B+_B"]["losses"] = int(ga["B+_B"].get("losses", 0)) + 1
    ga["overall"]["losses"] = int(ga["overall"].get("losses", 0)) + 1

    # 3. If grade was A+ or A: restrict A+
    g_upper = grade.strip().upper()
    if g_upper in ("A+", "A"):
        restrictions["A+_allowed"] = False
        restrictions["restriction_reason"] = f"A级止损({ticker} -{loss_pct:.1f}%)"
        restrictions["restriction_expires"] = (date.today() + timedelta(days=RESTRICTION_DAYS)).isoformat()

    # 4. Recalculate circuit breaker
    update_cb_state(scorecard)

    # 5. Increment pain_memory_count
    scorecard["pain_memory_count"] = int(scorecard.get("pain_memory_count", 0)) + 1

    save_scorecard(scorecard, market)

    state = scorecard["circuit_breaker"]["state"]
    icon = CB_ICONS.get(state, state)
    print(f"[post-mortem] {ticker} | Grade={grade} | Pod={pod} | Loss=-{loss_pct:.1f}%")
    print(f"  Circuit Breaker → {icon}  |  连续止损: {cb['consecutive_losses']}")
    if not restrictions.get("A+_allowed", True):
        print(f"  A+ 权限已锁定至 {restrictions['restriction_expires']}")
    print()
    print("⚠️  请在 pain_memory.md 中写入post-mortem (3个问题)")


# ──────────────────────────────────────────────────────────────────────────────
# Victory Memory 解析 (mirrors Pain Memory)
# ──────────────────────────────────────────────────────────────────────────────
def load_victory_memory_raw() -> str:
    if not VICTORY_MEMORY_PATH.exists():
        return ""
    return VICTORY_MEMORY_PATH.read_text(encoding="utf-8")


def parse_victory_memory(raw: str) -> tuple[int, dict | None]:
    raw = _strip_html_comments(raw)
    lines = raw.splitlines()
    vm_blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("### VM-"):
            if current:
                vm_blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        vm_blocks.append(current)
    count = len(vm_blocks)
    if count == 0:
        return 0, None
    first = vm_blocks[0]
    header = first[0]
    parts = [p.strip() for p in header.lstrip("#").strip().split("|")]
    ticker = parts[1] if len(parts) > 1 else "?"
    vm_date = parts[2] if len(parts) > 2 else "?"
    gain_raw = parts[3] if len(parts) > 3 else "?"
    r_raw = parts[4] if len(parts) > 4 else "?"
    summary_line = ""
    for line in first[1:]:
        if "1. 哪个信号我读对了" in line or "**1." in line:
            continue
        if line.strip() and not line.startswith("**") and not line.startswith("##"):
            summary_line = line.strip()
            break
    return count, {
        "ticker": ticker, "date": vm_date,
        "gain_pct": gain_raw, "r_multiple": r_raw,
        "summary": summary_line or "(无详情)",
    }


def load_playbook(market: str = "us") -> dict:
    path = PLAYBOOK_ASTOCK_PATH if market == "cn" else PLAYBOOK_PATH
    if not path.exists():
        return {"patterns": [], "observation_pool": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────────────────────
# Conviction Amplifier 状态机 (mirrors Circuit Breaker)
# ──────────────────────────────────────────────────────────────────────────────
CA_ICONS = {"NORMAL": "⚪ NORMAL", "ELEVATED": "🔵 ELEVATED", "PEAK": "🟣 PEAK"}


def compute_ca_state(ca: dict) -> str:
    a_rate = float(ca.get("a_grade_rate_rolling10", 0.0))
    expectancy = float(ca.get("expectancy_rolling20", 0.0))
    a_streak = int(ca.get("consecutive_a_grades", 0))
    if a_rate >= CA_PEAK_A_RATE and expectancy > CA_PEAK_EXPECTANCY and a_streak >= CA_PEAK_A_STREAK:
        return "PEAK"
    if a_rate >= CA_ELEVATED_A_RATE and expectancy > CA_ELEVATED_EXPECTANCY:
        return "ELEVATED"
    return "NORMAL"


def update_ca_state(scorecard: dict) -> str:
    ca = scorecard.get("conviction_amplifier", {})
    tg = scorecard.get("trade_grades", {})
    rm = scorecard.get("r_multiple_log", {})
    rolling10 = tg.get("rolling_10", {})
    rolling20 = rm.get("rolling_20", {})
    ca["a_grade_rate_rolling10"] = float(rolling10.get("a_grade_pct", 0.0))
    ca["expectancy_rolling20"] = float(rolling20.get("expectancy", 0.0))
    new_state = compute_ca_state(ca)
    if new_state == "PEAK":
        ca["sizing_multiplier"] = CA_PEAK_MULTIPLIER
        ca["last_peak"] = date.today().isoformat()
    elif new_state == "ELEVATED":
        ca["sizing_multiplier"] = CA_ELEVATED_MULTIPLIER
        ca["last_elevated"] = date.today().isoformat()
    else:
        ca["sizing_multiplier"] = 1.0
    ca["state"] = new_state
    scorecard["conviction_amplifier"] = ca
    return new_state


# ──────────────────────────────────────────────────────────────────────────────
# R-Multiple + MFE 追踪
# ──────────────────────────────────────────────────────────────────────────────
def log_r_multiple(scorecard: dict, ticker: str, r_mult: float, mfe_capture: float | None, market: str = "us") -> None:
    rm = scorecard.setdefault("r_multiple_log", {"trades": [], "rolling_20": {}, "mfe_stats": {}})
    entry = {
        "date": date.today().isoformat(),
        "ticker": ticker,
        "r_multiple": r_mult,
        "mfe_capture_pct": mfe_capture,
        "market": market,
    }
    rm["trades"].append(entry)
    recalc_rolling_r(rm, market)
    if mfe_capture is not None:
        recalc_mfe(rm, market)


def recalc_rolling_r(rm: dict, market: str | None = None) -> None:
    trades = rm.get("trades", [])
    if market:
        trades = [t for t in trades if t.get("market", "us") == market]
    recent = trades[-R_MULTIPLE_ROLLING:]
    if not recent:
        return
    rs = [t["r_multiple"] for t in recent]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    win_rate = len(wins) / len(rs) if rs else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    rm["rolling_20"] = {
        "count": len(recent),
        "win_rate": round(win_rate, 3),
        "avg_win_r": round(avg_win, 2),
        "avg_loss_r": round(avg_loss, 2),
        "expectancy": round(expectancy, 3),
        "best_r": round(max(rs), 2),
        "worst_r": round(min(rs), 2),
    }


def recalc_mfe(rm: dict, market: str | None = None) -> None:
    trades = rm.get("trades", [])
    if market:
        trades = [t for t in trades if t.get("market", "us") == market]
    mfe_vals = [t["mfe_capture_pct"] for t in trades if t.get("mfe_capture_pct") is not None]
    if not mfe_vals:
        return
    rm["mfe_stats"] = {
        "avg_capture_pct": round(sum(mfe_vals) / len(mfe_vals), 1),
        "trades_with_mfe": len(mfe_vals),
        "note": "MFE capture = exit_pnl / max_unrealized_gain. <40% = systematic early exits.",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Trade Grading (A/B/C Process Quality)
# ──────────────────────────────────────────────────────────────────────────────
def log_trade_grade(scorecard: dict, ticker: str, process_grade: str, reason: str) -> None:
    tg = scorecard.setdefault("trade_grades", {"log": [], "rolling_10": {}, "streaks": {}})
    g = process_grade.upper()
    if g not in ("A", "B", "C"):
        print(f"ERROR: process-grade must be A, B, or C (got '{process_grade}')", file=sys.stderr)
        sys.exit(1)
    tg["log"].append({
        "date": date.today().isoformat(),
        "ticker": ticker, "grade": g, "reason": reason,
    })
    recalc_trade_grades(tg)
    streaks = tg.setdefault("streaks", {})
    if g == "A":
        streaks["current_a_streak"] = int(streaks.get("current_a_streak", 0)) + 1
        if streaks["current_a_streak"] > int(streaks.get("longest_a_streak", 0)):
            streaks["longest_a_streak"] = streaks["current_a_streak"]
    else:
        streaks["current_a_streak"] = 0


def recalc_trade_grades(tg: dict) -> None:
    log = tg.get("log", [])
    recent = log[-10:]
    counts = {"A": 0, "B": 0, "C": 0}
    for entry in recent:
        g = entry.get("grade", "B")
        counts[g] = counts.get(g, 0) + 1
    total = sum(counts.values())
    tg["rolling_10"] = {
        "A": counts["A"], "B": counts["B"], "C": counts["C"],
        "a_grade_pct": round(counts["A"] / total, 3) if total > 0 else 0.0,
    }


# ──────────────────────────────────────────────────────────────────────────────
# --victory 逻辑 (mirrors --post-mortem)
# ──────────────────────────────────────────────────────────────────────────────
def handle_victory(scorecard: dict, ticker: str, gain_pct: float, r_mult: float,
                   grade: str, strategy: str, mfe_capture: float | None, market: str = "us") -> None:
    log_r_multiple(scorecard, ticker, r_mult, mfe_capture, market=market)
    log_trade_grade(scorecard, ticker, "A", f"Victory: {strategy} +{gain_pct:.1f}% +{r_mult:.1f}R")

    ca = scorecard.setdefault("conviction_amplifier", {})
    ca["consecutive_wins"] = int(ca.get("consecutive_wins", 0)) + 1
    streaks = scorecard.get("trade_grades", {}).get("streaks", {})
    win_streak = int(ca["consecutive_wins"])
    if win_streak > int(streaks.get("longest_win_streak", 0)):
        streaks["longest_win_streak"] = win_streak

    rewards = scorecard.setdefault("reward_milestones", {})
    rewards["total_victories_logged"] = int(rewards.get("total_victories_logged", 0)) + 1
    if r_mult > float(rewards.get("best_single_r", 0)):
        rewards["best_single_r"] = round(r_mult, 2)
        rewards["best_single_ticker"] = ticker

    scorecard["victory_memory_count"] = int(scorecard.get("victory_memory_count", 0)) + 1

    update_ca_state(scorecard)
    save_scorecard(scorecard, market)

    ca_state = ca.get("state", "NORMAL")
    ca_icon = CA_ICONS.get(ca_state, ca_state)
    multiplier = ca.get("sizing_multiplier", 1.0)

    print(f"\n{'='*60}")
    print(f"  VICTORY LOGGED")
    print(f"{'='*60}")
    print(f"  {ticker} | +{gain_pct:.1f}% | +{r_mult:.1f}R | Strategy: {strategy} | Grade: {grade}")
    if mfe_capture is not None:
        mfe_flag = " ⚠ 过早卖出!" if mfe_capture < MFE_WARNING_THRESHOLD * 100 else ""
        print(f"  MFE Capture: {mfe_capture:.0f}%{mfe_flag}")
    print(f"  Conviction Amplifier → {ca_icon} | Sizing: ×{multiplier:.2f}")
    print(f"  连续胜利: {win_streak} | 累计Victory: {rewards['total_victories_logged']}")
    if r_mult >= 3.0:
        print(f"  🏆 大胜! +{r_mult:.1f}R — 请在victory_memory.md中写入完整模式分析")
    elif r_mult >= 1.5:
        print(f"  ✅ 优质交易 — 5分钟内完成VM模板")
    print(f"  📖 检查playbook.json: 是否匹配已知赢家模式?")
    r20 = scorecard.get("r_multiple_log", {}).get("rolling_20", {})
    if r20.get("count", 0) >= 5:
        print(f"\n  R-Multiple Dashboard (rolling {r20['count']}笔):")
        print(f"    胜率: {r20['win_rate']:.1%} | 均赢: +{r20['avg_win_r']:.1f}R | 均亏: {r20['avg_loss_r']:.1f}R")
        print(f"    期望值: {r20['expectancy']:+.3f}R | 最佳: +{r20['best_r']:.1f}R | 最差: {r20['worst_r']:.1f}R")
    print(f"{'='*60}")
    print(f"\n  ⚠️  请在 victory_memory.md 中写入VM模板 (5分钟, 3个问题)")


# ──────────────────────────────────────────────────────────────────────────────
# --hold-review 逻辑 (Anti-Disposition Effect)
# ──────────────────────────────────────────────────────────────────────────────
def handle_hold_review(scorecard: dict, market: str = "us") -> None:
    portfolio = load_portfolio()
    if market == "cn":
        positions = get_cn_positions(portfolio)
        market_label = "A股"
        no_pos_msg = "无A股持仓"
    else:
        positions = get_us_positions(portfolio)
        market_label = "美股"
        no_pos_msg = "无美股持仓"

    if not positions:
        print(no_pos_msg)
        return
    vm_raw = load_victory_memory_raw()
    _, latest_vm = parse_victory_memory(vm_raw)
    playbook = load_playbook(market)
    patterns = playbook.get("patterns", [])
    mfe_stats = scorecard.get("r_multiple_log", {}).get("mfe_stats", {})
    avg_mfe = float(mfe_stats.get("avg_capture_pct", 0))

    print(f"\n{'='*60}")
    print(f"  HOLD REVIEW — 反处置效应检查 ({market_label})")
    print(f"{'='*60}")
    print(f"  ⚠ 以下只显示前瞻信息。成本价已隐藏(anti-disposition)。\n")

    for p in positions:
        ticker = p.get("ticker", "?")
        name = p.get("name", "")
        display_ticker = f"{ticker} {name}" if name else ticker
        thesis = p.get("thesis", "无thesis")
        catalyst = p.get("next_catalyst", "无催化剂")
        stop = p.get("stop_loss", "未设")
        grade = p.get("confidence_grade", p.get("conviction_level", "?"))
        unrealized_pct = p.get("unrealized_pnl_pct", 0)

        # For A-stock: show ATR K and max stop for the grade
        grade_info = ""
        if market == "cn" and grade in CN_ATR_K:
            k = CN_ATR_K[grade]
            max_stop = CN_MAX_STOP[grade]
            grade_info = f" | ATR K={k} | 最大止损{max_stop:.0%}"

        # Pattern match vs playbook
        matching_patterns = []
        for pat in patterns:
            if any(inst.get("ticker") == ticker for inst in pat.get("instances", [])):
                matching_patterns.append(pat["name"])
        # Also check observation_pool
        for obs in playbook.get("observation_pool", []):
            if any(inst.get("ticker") == ticker for inst in obs.get("instances", [])):
                matching_patterns.append(f"[观察中] {obs['name']}")

        status_icon = "🟢" if unrealized_pct > 0 else "🔴"
        print(f"  {status_icon} {display_ticker} [{grade}]{grade_info}")
        thesis_display = thesis if len(thesis) <= 80 else thesis[:77] + "..."
        print(f"    Thesis: {thesis_display}")
        print(f"    催化剂: {catalyst}")
        print(f"    止损线: {stop}")
        if matching_patterns:
            print(f"    📖 匹配赢家模式: {', '.join(matching_patterns)}")
        if unrealized_pct > 5:
            print(f"    ⏳ 主动持有声明: \"我选择继续持有{ticker}因为催化剂{catalyst}尚未兑现\"")
        print()

    if avg_mfe > 0:
        print(f"  历史MFE capture: {avg_mfe:.0f}%", end="")
        if avg_mfe < 40:
            print(" ⚠ 过低! 系统性过早卖出。考虑放宽trailing stop。")
        elif avg_mfe < 60:
            print(" — 有改善空间。")
        else:
            print(" — 良好。")
        print()

    print(f"  💡 提醒: '已涨了不少'不是卖出理由(L11)。")
    print(f"     减仓需提供'与催化剂无关'的理由: 止损/资金需求/A级替代机会。")
    if market == "cn":
        print(f"     A股: 板块龙头跌>5%当天=板块结束→同板块启动出场。")
    print(f"{'='*60}")


# ──────────────────────────────────────────────────────────────────────────────
# --playbook 逻辑
# ──────────────────────────────────────────────────────────────────────────────
def handle_playbook(market: str = "us") -> None:
    pb = load_playbook(market)
    patterns = pb.get("patterns", [])
    obs = pb.get("observation_pool", [])
    market_label = "A股 [cn]" if market == "cn" else "美股 [us]"

    print(f"\n{'='*60}")
    print(f"  WINNER'S PLAYBOOK — 赢家模式库 ({market_label})")
    print(f"{'='*60}")

    if not patterns:
        print("  (空 — 首个验证模式将在2+实例后生成)")
    else:
        for p in patterns:
            status = p.get("status", "?")
            icon = "✅" if status == "validated" else "👀"
            instances = p.get("instances", [])
            avg_r = p.get("avg_r_multiple", 0)
            wr = p.get("win_rate_backtest", 0)
            print(f"\n  {icon} {p['id']}: {p['name']}")
            print(f"     {p.get('description', '')}")
            if wr > 0:
                print(f"     胜率: {wr:.0%} | 均R: +{avg_r:.1f} | 实例: {len(instances)}笔")
            else:
                print(f"     实例: {len(instances)}笔")
            if_then = p.get("if_then", "N/A")
            print(f"     IF-THEN: {if_then[:100]}{'...' if len(if_then) > 100 else ''}")
            edge = p.get("edge_source", "")
            if edge:
                print(f"     Edge: {edge}")

    if obs:
        print(f"\n  --- 观察池 (需更多实例验证) ---")
        for o in obs:
            # Support both US playbook format (instances_needed/current_instances)
            # and A-stock format (instances list)
            if "instances_needed" in o:
                progress = f"{o.get('current_instances', 0)}/{o.get('instances_needed', 2)}"
            else:
                progress = f"{len(o.get('instances', []))}/2"
            print(f"  👀 {o['id']}: {o['name']} ({progress})")
            desc = o.get("description", "")
            if desc:
                print(f"       {desc[:80]}")
            if_then = o.get("if_then", "")
            if if_then:
                print(f"       IF-THEN: {if_then[:100]}{'...' if len(if_then) > 100 else ''}")

    print(f"\n{'='*60}")


# ──────────────────────────────────────────────────────────────────────────────
# --win 逻辑 (original, kept for backward compat)
# ──────────────────────────────────────────────────────────────────────────────
def handle_win(scorecard: dict, ticker: str, gain_pct: float, grade: str, market: str = "us") -> None:
    cb = scorecard["circuit_breaker"]
    restrictions = scorecard["grade_restrictions"]
    ga = scorecard["grade_accuracy"]
    rewards = scorecard.get("reward_milestones", {})

    # 1. Reset consecutive_losses
    cb["consecutive_losses"] = 0

    # Increment recovery_weeks_clean (approximate: +1 per win)
    cb["recovery_weeks_clean"] = int(cb.get("recovery_weeks_clean", 0)) + 1

    # 2. Update grade_accuracy — add a win
    tier = get_grade_tier(grade)
    if tier == "A+_A":
        ga["A+_A"]["wins"] = int(ga["A+_A"].get("wins", 0)) + 1
    else:
        ga["B+_B"]["wins"] = int(ga["B+_B"].get("wins", 0)) + 1
    ga["overall"]["wins"] = int(ga["overall"].get("wins", 0)) + 1

    # 3. Check if grade restriction can be lifted
    restriction_lifted = False
    if not restrictions.get("A+_allowed", True):
        # Check 3 consecutive wins at restricted level (A+/A)
        aa = ga.get("A+_A", {})
        aa_wins = int(aa.get("wins", 0))
        # Simple heuristic: if total wins at A+_A >= 3 since restriction
        if aa_wins >= RESTRICTION_LIFT_WINS:
            restrictions["A+_allowed"] = True
            restrictions["restriction_reason"] = None
            restrictions["restriction_expires"] = None
            restriction_lifted = True

    # 4. Check reward milestones (simple: every 5 wins overall = pod_c_bonus)
    overall_wins = int(ga["overall"].get("wins", 0))
    pod_c_bonus = int(rewards.get("pod_c_bonus", 0))
    new_bonus = overall_wins // 5
    if new_bonus > pod_c_bonus:
        rewards["pod_c_bonus"] = new_bonus
        scorecard["reward_milestones"] = rewards
        print(f"  🎉 里程碑: Pod III奖励 x{new_bonus} (累计{overall_wins}次胜利)")

    # 5. Recalculate circuit breaker
    update_cb_state(scorecard)

    save_scorecard(scorecard, market)

    state = scorecard["circuit_breaker"]["state"]
    icon = CB_ICONS.get(state, state)
    print(f"[win] {ticker} | Grade={grade} | Gain=+{gain_pct:.1f}%")
    print(f"  Circuit Breaker → {icon}  |  连续止损重置为0  |  累计胜利: {overall_wins}")
    if restriction_lifted:
        print("  ✅ A+ 权限已恢复 (连续3次A级获胜)")


# ──────────────────────────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Claude模拟盘 — 信念评分卡 + Victory Protocol")

    # Market selector
    parser.add_argument("--market", type=str, default="us", choices=["us", "cn"],
                        help="市场: us=美股(默认) | cn=A股")

    # Pain System
    parser.add_argument("--update", action="store_true", help="重算所有状态(CB + CA)")
    parser.add_argument("--post-mortem", action="store_true", help="记录止损post-mortem")
    parser.add_argument("--win", action="store_true", help="记录盈利(简易模式)")

    # Victory Protocol
    parser.add_argument("--victory", action="store_true", help="记录胜利(完整Victory Protocol)")
    parser.add_argument("--grade-trade", action="store_true", help="记录交易过程评分(A/B/C)")
    parser.add_argument("--hold-review", action="store_true", help="反处置效应: 持仓Review(隐藏成本价)")
    parser.add_argument("--playbook", action="store_true", help="显示赢家模式库")

    # Shared params
    parser.add_argument("--ticker", type=str, help="标的代码")
    parser.add_argument("--loss-pct", type=float, help="止损幅度 %%")
    parser.add_argument("--gain-pct", type=float, help="盈利幅度 %%")
    parser.add_argument("--grade", type=str, help="建仓等级 (S/A+/A/A-/B+/B/B-)")
    parser.add_argument("--pod", type=str, help="Pod分类 (美股用)")
    parser.add_argument("--r-multiple", type=float, help="R倍数 (盈亏÷初始风险)")
    parser.add_argument("--strategy", type=str, help="策略标签 (MOM_ROTATION/DIP_BUY/PEAD_ADD/PROBE_THEN_PRESS/CATALYST_PRECISION/SECTOR_LEADER)")
    parser.add_argument("--mfe-capture", type=float, help="MFE capture %% (exit_pnl÷max_unrealized×100)")
    parser.add_argument("--process-grade", type=str, help="交易过程评分 (A/B/C)")
    parser.add_argument("--reason", type=str, default="", help="评分理由")
    args = parser.parse_args()

    market = args.market
    scorecard = load_scorecard(market)

    # ── Pain System ──
    if args.post_mortem:
        missing = [f for f, v in [("--ticker", args.ticker), ("--loss-pct", args.loss_pct),
                                   ("--grade", args.grade), ("--pod", args.pod)] if v is None]
        # --pod is US-specific; for cn market it's optional
        if market == "cn":
            missing = [f for f, v in [("--ticker", args.ticker), ("--loss-pct", args.loss_pct),
                                       ("--grade", args.grade)] if v is None]
        if missing:
            print(f"ERROR: --post-mortem 需要: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        handle_post_mortem(scorecard, args.ticker, args.loss_pct, args.grade, args.pod or "cn", market=market)
        return

    if args.win:
        missing = [f for f, v in [("--ticker", args.ticker), ("--gain-pct", args.gain_pct),
                                   ("--grade", args.grade)] if v is None]
        if missing:
            print(f"ERROR: --win 需要: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        handle_win(scorecard, args.ticker, args.gain_pct, args.grade, market=market)
        return

    # ── Victory Protocol ──
    if args.victory:
        missing = [f for f, v in [("--ticker", args.ticker), ("--gain-pct", args.gain_pct),
                                   ("--r-multiple", args.r_multiple), ("--grade", args.grade),
                                   ("--strategy", args.strategy)] if v is None]
        if missing:
            print(f"ERROR: --victory 需要: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        handle_victory(scorecard, args.ticker, args.gain_pct, args.r_multiple,
                       args.grade, args.strategy, args.mfe_capture, market=market)
        return

    if args.grade_trade:
        missing = [f for f, v in [("--ticker", args.ticker), ("--process-grade", args.process_grade)] if v is None]
        if missing:
            print(f"ERROR: --grade-trade 需要: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        log_trade_grade(scorecard, args.ticker, args.process_grade, args.reason)
        update_ca_state(scorecard)
        save_scorecard(scorecard, market)
        r10 = scorecard.get("trade_grades", {}).get("rolling_10", {})
        ca = scorecard.get("conviction_amplifier", {})
        print(f"[grade] {args.ticker} = {args.process_grade}-grade | A-rate: {r10.get('a_grade_pct',0):.0%} | "
              f"CA: {ca.get('state', 'NORMAL')} (×{ca.get('sizing_multiplier',1):.2f})")
        return

    if args.hold_review:
        handle_hold_review(scorecard, market)
        return

    if args.playbook:
        handle_playbook(market)
        return

    if args.update:
        handle_update(scorecard, market)
        update_ca_state(scorecard)
        save_scorecard(scorecard, market)
        ca = scorecard.get("conviction_amplifier", {})
        ca_icon = CA_ICONS.get(ca.get("state", "NORMAL"), "NORMAL")
        print(f"[update] Conviction Amplifier → {ca_icon} (×{ca.get('sizing_multiplier',1):.2f})")

    # Default: print full scorecard
    portfolio = load_portfolio()
    pain_raw = load_pain_memory_raw()
    pain_count, latest_pm = parse_pain_memory(pain_raw)
    scorecard["pain_memory_count"] = pain_count
    print_scorecard(scorecard, pain_count, latest_pm, market)


if __name__ == "__main__":
    main()
