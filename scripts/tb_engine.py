#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Track B 纯筹码引擎 v3.0 — 6维: 5维当日快照 + D6历史筹码体检

Track B不看基本面、不看催化剂、不看产业链——那是Track A的事。
Track B只回答一个问题：钱在不在这里、筹码结构好不好、能不能涨。

6维: 资金信号 / 筹码形态 / 领涨地位 / 板块周期 / 弹性系数 / 历史筹码体检(D6)

v3.0: +D6历史筹码体检 — 三环集团教训(05-29): 30天翻倍+冲顶放量入场=接盘
D6自动拉历史行情，检查: 20日涨幅/量价背离/冲顶放量/获利盘密度
核心flag扣分，辅助flag叠加加重。

用法:
  uv run --script scripts/tb_engine.py score    # 交互评分
  uv run --script scripts/tb_engine.py review   # 持仓筹码审查
  uv run --script scripts/tb_engine.py order    # 生成建仓order
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

# ── D1 资金信号（45分）— 谁在买？多少钱？─────────────────────────────────────

D1_SCORES = {"S": 45, "A": 35, "B": 25, "C": 12, "X": 0}
D1_DESC = {
    "S": "龙虎榜净买≥5亿 + 机构席位确认 + 北向/外资同步买入",
    "A": "龙虎榜净买≥2亿 OR 机构+游资同向 OR 连续3日主力净流入",
    "B": "龙虎榜上榜(任何原因) OR 主力单日净流入>5000万 OR 融资连续3日增",
    "C": "仅散户推动 / 无龙虎榜 / 主力小额参与",
    "X": "龙虎榜净卖出 OR 主力净流出>1亿 — 一票否决",
}

# ── D2 筹码形态（30分）— 量能怎么样？筹码锁不锁？──────────────────────────────

D2_SCORES = {"S": 30, "A": 24, "B": 18, "C": 10, "D": 0}
D2_DESC = {
    "S": "涨停+封板资金>5亿+换手<10% OR 连板≥3（筹码高度锁定）",
    "A": "涨停+封板>1亿 OR 2连板 OR 量比>3+换手5-15%（放量突破+筹码良好）",
    "B": "放量上涨(量比>2)+5日均量持续放大 OR 首板涨停",
    "C": "温和放量(量比1-2) OR 缩量上涨（惜售但无增量）",
    "D": "放量下跌 OR 天量见天价（筹码松动/派发） — 一票否决",
}

# ── D3 领涨地位（25分）— 它在板块里是领涨还是跟风？──────────────────────────────

D3_SCORES = {"龙头": 25, "先手": 20, "跟涨": 12, "补涨": 6, "掉队": 0}
D3_DESC = {
    "龙头": "板块内率先涨停/创新高，辨识度最高，其他股跟它走",
    "先手": "板块前3个涨停，有独立涨停能力，仅次于龙头",
    "跟涨": "板块涨时跟涨但不领涨，走势被动",
    "补涨": "板块涨完后才动，明显滞后于龙头和先手",
    "掉队": "板块涨它不涨 / 跌幅领先板块 — 一票否决",
}

# ── D4 板块周期（20分）— 纯看价格行为判断阶段 ─────────────────────────────────

D4_SCORES = {"启动": 20, "主升早": 16, "主升中晚": 8, "高潮分歧": 3, "退潮": 0}
D4_DESC = {
    "启动": "板块首日放量突破 / 首批涨停出现 / 龙头首板",
    "主升早": "龙头2-3板，板块涨停数持续扩大，分歧极小",
    "主升中晚": "龙头5板+或涨幅>50%，跟风票补涨，换手率高企",
    "高潮分歧": "龙头出现大阴线/炸板，板块内分化明显",
    "退潮": "龙头连续下跌，板块涨停数骤减 / 跌停出现",
}

# ── D5 弹性系数（15分）— 市值决定弹性上限 ─────────────────────────────────────

D5_SCORES = {
    "科创创业小盘": 15, "主板小盘": 13, "主板中盘": 10, "大盘蓝筹": 8,
    "北交A": 10, "北交B": 6, "北交超小": 0,
}
D5_DESC = {
    "科创创业小盘": "科创板/创业板 市值<200亿（小票先飞加分）",
    "主板小盘": "主板 市值<300亿",
    "主板中盘": "主板 市值300-1000亿",
    "大盘蓝筹": "市值>1000亿（流动性好但弹性低）",
    "北交A": "北交所 有成交量支撑",
    "北交B": "北交所 早期/成交偏低",
    "北交超小": "北交所超小盘 — 流动性陷阱",
}

# ── D6 历史筹码体检（自动，由uass_scan.py chip_health_check执行）─────────────
# D6不是交互评分维度——它是自动拉历史行情后的惩罚分。
# 核心flag: EXTREME_RUN(20d>60%,-35) / HEAVY_RUN(20d>40%,-20) /
#           VOLUME_CLIMAX(近5日天量,-15) / PROFIT_TRAPPED(获利盘>25%,-10)
# 辅助flag: VOL_SHRINK / VOL_PRICE_DIV — 单独不扣分，叠加核心flag时各-5

# ── 等级映射 ────────────────────────────────────────────────────────────────

def score_to_grade(total: int) -> tuple[str, float, float, float]:
    """Return (grade, position_cap, atk_k, hard_stop). SABCT full spectrum (max 135)."""
    if total >= 120:
        return "S", 0.50, 3.5, -0.20
    elif total >= 108:
        return "A+", 0.35, 3.0, -0.18
    elif total >= 95:
        return "A", 0.25, 3.0, -0.15
    elif total >= 85:
        return "A-", 0.20, 2.5, -0.15
    elif total >= 75:
        return "B+", 0.15, 2.0, -0.12
    elif total >= 65:
        return "B", 0.12, 2.0, -0.10
    elif total >= 55:
        return "B-", 0.10, 1.5, -0.10
    elif total >= 40:
        return "C", 0.0, 0.0, 0.0
    else:
        return "D", 0.0, 0.0, 0.0


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
    """Run interactive 5-dimension scoring — pure chips/flow."""
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║     Track B 纯筹码引擎 v2.0 — tb_engine.py score               ║")
    print("║     只看资金/筹码/价格动量，不看基本面/催化剂/产业链            ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    state = load_json(STATE_FILE)
    f20 = state.get("market_breath", "未知")
    switch = state.get("market_switch", "未知")
    print(f"  当前市场: F20={f20} / switch={switch}")
    if switch == "CLOSED":
        print("  ⛔ 市场硬开关已关闭 — 评分仅供参考，不可建仓")
    print()

    # D1 资金信号
    print("  ── D1 资金信号（45分）— 谁在买？多少钱？──")
    for k, desc in D1_DESC.items():
        print(f"    {k}: {desc} → {D1_SCORES[k]}分")
    d1_key = input("  选择 (S/A/B/C/X): ").strip().upper()
    if d1_key not in D1_SCORES:
        print("  无效输入，退出")
        return
    d1 = D1_SCORES[d1_key]
    if d1_key == "X":
        print("\n  ⛔ 一票否决：主力净流出。评级=D，不入场。")
        return

    # D2 筹码形态
    print(f"\n  ── D2 筹码形态（30分）— 量能怎么样？筹码锁不锁？──")
    for k, desc in D2_DESC.items():
        print(f"    {k}: {desc} → {D2_SCORES[k]}分")
    d2_key = input("  选择 (S/A/B/C/D): ").strip().upper()
    if d2_key not in D2_SCORES:
        print("  无效输入，退出")
        return
    d2 = D2_SCORES[d2_key]
    if d2_key == "D":
        print("\n  ⛔ 一票否决：筹码松动/派发。评级=D，不入场。")
        return

    # D3 领涨地位
    print(f"\n  ── D3 领涨地位（25分）— 它在板块里领涨还是跟风？──")
    for k, desc in D3_DESC.items():
        print(f"    {k}: {desc} → {D3_SCORES[k]}分")
    d3_key = input("  选择 (龙头/先手/跟涨/补涨/掉队): ").strip()
    if d3_key not in D3_SCORES:
        print("  无效输入，退出")
        return
    d3 = D3_SCORES[d3_key]
    if d3_key == "掉队":
        print("\n  ⛔ 一票否决：板块涨它不涨=筹码有问题。评级=D，不入场。")
        return

    # D4 板块周期
    print(f"\n  ── D4 板块周期（20分）— 板块价格在什么阶段？──")
    for k, desc in D4_DESC.items():
        print(f"    {k}: {desc} → {D4_SCORES[k]}分")
    d4_key = input("  选择 (启动/主升早/主升中晚/高潮分歧/退潮): ").strip()
    if d4_key not in D4_SCORES:
        print("  无效输入，退出")
        return
    d4 = D4_SCORES[d4_key]
    if d4_key == "退潮":
        print("\n  ⛔ 退潮期不入场。评级=D。")
        return

    # D5 弹性系数
    print(f"\n  ── D5 弹性系数（15分）— 市值决定弹性上限 ──")
    for k, score in D5_SCORES.items():
        desc = D5_DESC.get(k, "")
        print(f"    {k}: {desc} → {score}分")
    d5_key = input("  选择 (科创创业小盘/主板小盘/主板中盘/大盘蓝筹/北交A/北交B/北交超小): ").strip()
    if d5_key not in D5_SCORES:
        print("  无效输入，退出")
        return
    d5 = D5_SCORES[d5_key]
    if d5_key == "北交超小":
        print("\n  ⛔ 一票否决：北交所超小盘流动性陷阱。评级=D。")
        return

    # 流动性萎缩检查
    liq_shrink = input("\n  当日成交额 < 5日均值50%？(y/n): ").strip().lower()
    if liq_shrink == "y":
        d5 = max(0, d5 - 5)
        print(f"    流动性萎缩 -5分 → D5={d5}分")

    # 总分
    total = d1 + d2 + d3 + d4 + d5
    grade, cap, atk_k, hard_stop = score_to_grade(total)

    # 强制降档
    force_notes = []

    # 游资主导检查
    is_youzi = input("\n  纯游资主导（无机构席位跟进）？(y/n): ").strip().lower()
    if is_youzi == "y":
        if grade in ("A", "A-", "B+", "B"):
            old_grade = grade
            grade = "B-"
            cap = 0.10
            force_notes.append(f"游资主导无机构 → {old_grade}压至B-（≤10%）")

    # 追高风险检查
    is_chasing = input("  追连板（当前已≥4板）？(y/n): ").strip().lower()
    if is_chasing == "y":
        cap *= 0.5
        force_notes.append(f"追4板+高位 → sizing ×0.5 = {cap*100:.1f}%")

    is_bse = d5_key.startswith("北交")
    if is_bse:
        cap = min(cap, 0.05)
        force_notes.append("北交所 → ≤5%硬约束")

    # Signal-level sizing
    signal_mult = {"S": 1.0, "A": 0.80, "B": 0.60, "C": 0.40}.get(d1_key, 0.5)
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
    print("  Track B 纯筹码评分结果")
    print(divider)
    print(f"  D1 资金信号:  {d1_key} = {d1:>2}/45  (谁在买)")
    print(f"  D2 筹码形态:  {d2_key} = {d2:>2}/30  (量能/锁筹)")
    print(f"  D3 领涨地位:  {d3_key} = {d3:>2}/25  (领涨vs跟风)")
    print(f"  D4 板块周期:  {d4_key} = {d4:>2}/20  (板块阶段)")
    print(f"  D5 弹性系数:  {d5_key} = {d5:>2}/15  (市值弹性)")
    print(divider)
    print(f"  总分: {total}/135 → 等级: {grade}")
    print(f"  仓位上限: {cap*100:.0f}%")
    print(f"  信号调节: D1={d1_key} ×{signal_mult:.0%} → 建议sizing: {effective_size*100:.1f}%")
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


# ── 持仓筹码审查 ──────────────────────────────────────────────────────────────

def review_holdings():
    """Show TB positions — pure chips/flow review, no cost price."""
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║     Track B 筹码审查 — tb_engine.py review                      ║")
    print("║     隐藏成本价，只问筹码/资金/领涨地位                          ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    portfolio = load_json(PORTFOLIO_FILE)
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
        tb_grade = pos.get("tb_grade", "?")
        leader = pos.get("tb_leader", "?")

        entry_str = pos.get("tb_entry_date") or pos.get("entry_date", "")
        days = 0
        if entry_str:
            try:
                days = (today - datetime.strptime(entry_str[:10], "%Y-%m-%d")).days
            except ValueError:
                pass

        print(f"  ── {name} ({ticker}) ──")
        print(f"    等级: {tb_grade} | 持有: {days}天 | 龙头锚: {leader}")
        print()
        print("    ❓ 筹码三问（不看成本价回答）:")
        print("       1. 龙头还在涨吗？它今天比昨天强还是弱？")
        print("       2. 成交量还在放大吗？还是开始萎缩？")
        print("       3. 板块还有新涨停吗？还是涨停数在减少？")
        print('       → 三个都答"是"=持有 | 任一答"否"=审查退出理由')
        print()


# ── 建仓order生成 ──────────────────────────────────────────────────────────────

def create_order(args):
    """Generate a pending_order for a TB position."""
    portfolio = load_json(PORTFOLIO_FILE)

    order = {
        "ticker": args.ticker,
        "name": args.name,
        "action": "buy",
        "shares": args.shares,
        "account": "a_share",
        "reason": f"TB建仓: {args.grade} | 龙头:{args.leader}",
        "track": "B",
        "tb_grade": args.grade,
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
    print(f"     等级: {args.grade} / 龙头锚: {args.leader}")
    print(f"     ⚠️  需手动执行 execute_trade.py")
    print()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Track B 纯筹码引擎 v2.0")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("score", help="交互式5维筹码评分")
    sub.add_parser("review", help="持仓筹码审查（隐藏成本价）")

    order_p = sub.add_parser("order", help="生成建仓pending_order")
    order_p.add_argument("--ticker", required=True)
    order_p.add_argument("--name", required=True)
    order_p.add_argument("--grade", required=True, choices=["S", "A+", "A", "A-", "B+", "B", "B-"])
    order_p.add_argument("--leader", required=True, help="板块龙头ticker（止损锚）")
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
