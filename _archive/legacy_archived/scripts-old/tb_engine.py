#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Track B 信号聚合引擎 — 5维打分 + 仓位计算 + pending_order生成

用法:
  # 交互模式（逐步输入5维评分）
  uv run --script scripts/tb_engine.py score

  # 持仓评审（隐藏成本价，只看thesis/催化剂）
  uv run --script scripts/tb_engine.py review

  # 生成建仓pending_order
  uv run --script scripts/tb_engine.py order --ticker 002929 --name 润建股份 --grade B+ --type T2 --leader 002586 --shares 5000

输出:
  score: 5维打分表 + 等级判定 + 仓位建议
  review: TB持仓thesis检查（反处置效应）
  order: 写入portfolio_state.json的pending_orders
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATE_FILE = REPO / "rotation_state.json"
PORTFOLIO_FILE = REPO / "portfolio_state.json"
SCORECARD_FILE = REPO / "tb_scorecard.json"
PLAYBOOK_FILE = REPO / "tb_playbook.json"

# ── 评分表 ──────────────────────────────────────────────────────────────────

D1_SCORES = {
    "S": 30, "A": 22, "B": 14, "C": 6, "X": 0,
}
D1_DESC = {
    "S": "机构+游资+外资三方共振（各超1.5亿）",
    "A": "机构+游资共振 / 龙头T+1跟风（≥2板+≥60家涨停）",
    "B": "残差动量 / 均线能量Top 2",
    "C": "北向月度配置盘变化",
    "X": "无有效信号 — 一票否决",
}

D2_SCORES = {
    "T2": 25, "T4": 20, "T1": 15, "T3": 10, "T5": 5, "T1X": 0,
}
D2_DESC = {
    "T2": "产业催化型（有一手定量数字）",
    "T4": "政策方向性（政治局级催化）",
    "T1": "事件冲击型（核心受益方，业务可验证）",
    "T3": "情绪扩散型（龙头已涨20-50%，小票首板）",
    "T5": "游资坐庄型（游资席位集中拉升）",
    "T1X": "蹭热点 / 无业务关联 — 一票否决",
}

D3_SCORES = {
    "L1": 20, "L2": 16, "L3": 10, "L4": 6, "L5": 6,
    "L6X": 0, "L6I": 6, "TEMP": 4,
}
D3_DESC = {
    "L1": "主线先行层（板块龙头）",
    "L2": "价值量跟进层-高价值（PCB/BOM驱动）",
    "L3": "价值量跟进层-次级（覆铜板/散热）",
    "L4": "技术升级层",
    "L5": "材料层",
    "L6X": "L6末端扩散层（首次） — 一票否决",
    "L6I": "L6已成独立主线（有业务验证）",
    "TEMP": "临时子方向（不在L1-L6链）",
}

D4_SCORES = {
    "启动": 15, "主升早": 12, "主升中晚": 6, "高潮分歧": 2, "退潮": 0,
}

D5_SCORES = {
    "主板小盘": 10, "主板中盘": 10, "北交A": 8, "北交B": 4, "北交超小": 0,
}

# ── 等级映射 ────────────────────────────────────────────────────────────────

def score_to_grade(total: int) -> tuple[str, float, float, float]:
    """Return (grade, position_cap, atk_k, hard_stop)."""
    if total >= 75:
        return "B+", 0.15, 2.0, -0.12
    elif total >= 60:
        return "B", 0.12, 2.0, -0.10
    elif total >= 45:
        return "B-", 0.10, 1.5, -0.10
    else:
        return "C", 0.0, 0.0, 0.0


# ── I/O ─────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}

def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── 交互打分 ────────────────────────────────────────────────────────────────

def interactive_score():
    """Run interactive 5-dimension scoring."""
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║          Track B 5维评分器 — tb_engine.py score                 ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # Load market state for context
    state = load_json(STATE_FILE)
    f20 = state.get("market_breath", "未知")
    switch = state.get("market_switch", "未知")
    print(f"  当前市场: F20={f20} / switch={switch}")
    if switch == "CLOSED":
        print("  ⛔ 市场硬开关已关闭 — 评分仅供参考，不可建仓")
    print()

    # D1
    print("  ── D1 入场信号等级（30分）──")
    for k, desc in D1_DESC.items():
        print(f"    {k}: {desc} → {D1_SCORES[k]}分")
    d1_key = input("  选择 (S/A/B/C/X): ").strip().upper()
    if d1_key not in D1_SCORES:
        print("  无效输入，退出")
        return
    d1 = D1_SCORES[d1_key]
    if d1_key == "X":
        print("\n  ⛔ 一票否决：无有效入场信号。评级=C，不可入场。")
        return

    # D2
    print(f"\n  ── D2 轮动类型质量（25分）──")
    for k, desc in D2_DESC.items():
        print(f"    {k}: {desc} → {D2_SCORES[k]}分")
    d2_key = input("  选择 (T2/T4/T1/T3/T5/T1X): ").strip().upper()
    if d2_key not in D2_SCORES:
        print("  无效输入，退出")
        return
    d2 = D2_SCORES[d2_key]
    if d2_key == "T1X":
        print("\n  ⛔ 一票否决：蹭热点/无业务关联。评级=C，不可入场。")
        return

    # D3
    print(f"\n  ── D3 产业链传导位置（20分）──")
    for k, desc in D3_DESC.items():
        print(f"    {k}: {desc} → {D3_SCORES[k]}分")
    d3_key = input("  选择 (L1/L2/L3/L4/L5/L6X/L6I/TEMP): ").strip().upper()
    if d3_key not in D3_SCORES:
        print("  无效输入，退出")
        return
    d3 = D3_SCORES[d3_key]
    if d3_key == "L6X":
        print("\n  ⛔ 一票否决：L6末端扩散层首次出现。评级=C，不可入场。")
        return

    # D4
    print(f"\n  ── D4 时间位置/板块生命周期（15分）──")
    for k, score in D4_SCORES.items():
        print(f"    {k}: {score}分")
    d4_key = input("  选择 (启动/主升早/主升中晚/高潮分歧/退潮): ").strip()
    if d4_key not in D4_SCORES:
        print("  无效输入，退出")
        return
    d4 = D4_SCORES[d4_key]
    if d4_key == "退潮":
        print("\n  ⛔ 退潮期不入场。评级=C。")
        return

    # D5
    print(f"\n  ── D5 目标流动性（10分）──")
    for k, score in D5_SCORES.items():
        print(f"    {k}: {score}分")
    d5_key = input("  选择 (主板小盘/主板中盘/北交A/北交B/北交超小): ").strip()
    if d5_key not in D5_SCORES:
        print("  无效输入，退出")
        return
    d5 = D5_SCORES[d5_key]
    if d5_key == "北交超小":
        print("\n  ⛔ 一票否决：北交所超小盘(<15亿)流动性陷阱。评级=C。")
        return

    # 流动性萎缩检查
    liq_shrink = input("  当日成交额 < 5日均值50%？(y/n): ").strip().lower()
    if liq_shrink == "y":
        d5 = max(0, d5 - 5)
        print(f"    流动性萎缩 -5分 → D5={d5}分")

    # 总分
    total = d1 + d2 + d3 + d4 + d5
    grade, cap, atk_k, hard_stop = score_to_grade(total)

    # 强制降档
    force_notes = []
    is_youzi = input("\n  游资主导（无机构跟进）？(y/n): ").strip().lower()
    if is_youzi == "y":
        if grade in ("B+", "B"):
            grade = "B-"
            cap = 0.10
            force_notes.append("游资主导 → 压至B-（≤10%）")

    is_bse = d5_key.startswith("北交")
    if is_bse:
        cap = min(cap, 0.05)
        force_notes.append("北交所 → ≤5%硬约束")

    if d2_key == "T5":
        cap = min(cap, 0.10)
        force_notes.append("Type 5 → ≤10%")

    # PlayBook匹配
    playbook = load_json(PLAYBOOK_FILE)
    match_bonus = False

    # Signal-level sizing
    signal_mult = {"S": 1.0, "A": 0.75, "B": 0.50, "C": 0.50}.get(d1_key, 0.5)
    effective_size = cap * signal_mult

    # CB check
    scorecard = load_json(SCORECARD_FILE)
    cb = scorecard.get("cb_state", "GREEN")
    if cb == "RED":
        effective_size = 0
        force_notes.append("⛔ CB=RED — TB暂停，sizing=0")
    elif cb == "YELLOW":
        effective_size *= 0.5
        force_notes.append("⚠️ CB=YELLOW — sizing ×0.5")

    # Output
    divider = "─" * 64
    print(f"\n{divider}")
    print("  5维评分结果")
    print(divider)
    print(f"  D1 入场信号:  {d1_key} = {d1:>2}/30")
    print(f"  D2 轮动类型:  {d2_key} = {d2:>2}/25")
    print(f"  D3 传导位置:  {d3_key} = {d3:>2}/20")
    print(f"  D4 时间位置:  {d4_key} = {d4:>2}/15")
    print(f"  D5 流动性:    {d5_key} = {d5:>2}/10")
    print(divider)
    print(f"  总分: {total}/100 → 等级: {grade}")
    print(f"  仓位上限: {cap*100:.0f}%")
    print(f"  信号调节: {d1_key}级 ×{signal_mult:.0%} → 建议sizing: {effective_size*100:.1f}%")
    print(f"  ATR K值: {atk_k}")
    print(f"  硬止损: {hard_stop*100:.0f}%")

    if force_notes:
        print(f"\n  强制降档/调整:")
        for n in force_notes:
            print(f"    • {n}")

    print(divider)
    print()

    return {
        "d1": d1_key, "d2": d2_key, "d3": d3_key, "d4": d4_key, "d5": d5_key,
        "total": total, "grade": grade, "cap": cap,
        "effective_size": effective_size, "atk_k": atk_k, "hard_stop": hard_stop,
    }


# ── 持仓评审（反处置效应检查）────────────────────────────────────────────────

def review_holdings():
    """Show TB positions without cost price — forces thesis-based evaluation."""
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║       Track B 持仓评审（隐藏成本价）— tb_engine.py review      ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    portfolio = load_json(PORTFOLIO_FILE)
    state = load_json(STATE_FILE)
    today = datetime.now()

    tb_pos = []
    for acct in portfolio.get("accounts", {}).values():
        for pos in acct.get("positions", []):
            if pos.get("track") == "B":
                tb_pos.append(pos)

    if not tb_pos:
        print("  无TB持仓。")
        print()
        return

    for pos in tb_pos:
        name = pos.get("name", pos.get("ticker", "?"))
        ticker = pos.get("ticker", "?")
        tb_type = pos.get("tb_type", "?")
        tb_grade = pos.get("tb_grade", "?")
        leader = pos.get("tb_leader", "?")
        exit_preset = pos.get("tb_exit_preset", "未设置")
        thesis = pos.get("thesis", "无")
        catalyst = pos.get("next_catalyst", "无")

        entry_str = pos.get("tb_entry_date") or pos.get("entry_date", "")
        days = 0
        if entry_str:
            try:
                days = (today - datetime.strptime(entry_str[:10], "%Y-%m-%d")).days
            except ValueError:
                pass

        print(f"  ── {name} ({ticker}) ──")
        print(f"    等级: {tb_grade} | 类型: {tb_type} | 持有: {days}天")
        print(f"    龙头锚: {leader}")
        print(f"    退出预设: {exit_preset}")
        print(f"    Thesis: {thesis}")
        print(f"    催化剂: {catalyst}")
        print()
        print("    ❓ 反处置效应三问（不看成本价回答）:")
        print("       1. 现在这个价格，你会新买吗？")
        print("       2. 龙头还强吗？催化剂还在前面吗？")
        print("       3. 你在等什么？答不出=没理由持有。")
        print()


# ── 建仓order生成 ────────────────────────────────────────────────────────────

def create_order(args):
    """Generate a pending_order for a TB position."""
    portfolio = load_json(PORTFOLIO_FILE)

    order = {
        "ticker": args.ticker,
        "name": args.name,
        "action": "buy",
        "shares": args.shares,
        "account": "a_share",
        "reason": f"TB建仓: {args.grade}/{args.type}",
        "track": "B",
        "tb_grade": args.grade,
        "tb_type": args.type,
        "tb_leader": args.leader,
        "tb_entry_date": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
    }

    pending = portfolio.get("pending_orders", [])
    pending.append(order)
    portfolio["pending_orders"] = pending
    save_json(PORTFOLIO_FILE, portfolio)

    print()
    print(f"  ✅ TB pending_order 已写入:")
    print(f"     {args.ticker} {args.name} — {args.shares}股")
    print(f"     等级: {args.grade} / 类型: {args.type} / 龙头: {args.leader}")
    print(f"     ⚠️  需 daily_run.sh Step 4b2 自动执行，或手动执行 execute_trade.py")
    print()


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Track B 信号聚合引擎")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("score", help="交互式5维打分")
    sub.add_parser("review", help="持仓评审（隐藏成本价）")

    order_p = sub.add_parser("order", help="生成建仓pending_order")
    order_p.add_argument("--ticker", required=True)
    order_p.add_argument("--name", required=True)
    order_p.add_argument("--grade", required=True, choices=["B+", "B", "B-"])
    order_p.add_argument("--type", required=True, choices=["T1", "T2", "T3", "T4", "T5"])
    order_p.add_argument("--leader", required=True, help="龙头ticker")
    order_p.add_argument("--shares", required=True, type=int)

    args = p.parse_args()

    if args.command == "score":
        interactive_score()
    elif args.command == "review":
        review_holdings()
    elif args.command == "order":
        create_order(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
