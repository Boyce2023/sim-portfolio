# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
A股 Session 统一仪表盘 — 单次加载、单次输出

替代串行执行 session_view + risk_monitor + tb_scan + tb_review + tb_monitor。
所有数据文件只读一次，输出一个紧凑的仪表盘。

用法:
  uv run --script scripts/astock_session.py                    # 默认仪表盘
  uv run --script scripts/astock_session.py --quick             # 仅持仓+关键警报
  uv run --script scripts/astock_session.py --scan --limit-up 75 --board-break 22 --turnover 11500  # 含F20扫描
  uv run --script scripts/astock_session.py --json              # JSON输出（供agent读取）

原始脚本仍可独立使用:
  tb_engine.py score   — 交互式5维评分（不合并）
  tb_engine.py review  — 持仓评审（不合并）
  tb_engine.py order   — 建仓order生成（不合并）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# ── 文件路径 ──────────────────────────────────────────────────────────────────

PORTFOLIO_FILE = REPO / "portfolio_state.json"
PRICES_FILE = REPO / "latest_prices.json"
ROTATION_FILE = REPO / "rotation_state.json"
SCORECARD_FILE = REPO / "tb_scorecard.json"
WATCHLIST_FILE = REPO / "watchlist_config.json"

# ── 常量 ──────────────────────────────────────────────────────────────────────

try:
    from core.config import (
        ASTOCK_POSITION_LIMITS, ASTOCK_ATR_K, ASTOCK_HARD_STOP_PCT,
        ASTOCK_MAX_POSITIONS, ASTOCK_SINGLE_POSITION_CAP,
    )
except ImportError:
    ASTOCK_POSITION_LIMITS = {
        "S": 0.50, "A+": 0.35, "A": 0.25, "A-": 0.20,
        "B+": 0.15, "B": 0.12, "B-": 0.10,
    }
    ASTOCK_MAX_POSITIONS = 99  # v9.2(06-23): 持仓数不约束
    ASTOCK_SINGLE_POSITION_CAP = 0.50

TYPE_HOLDING_LIMITS = {"T1": 5, "T2": 45, "T3": 5, "T4": 15, "T5": 12, "BSE": 7}

F20_TB_CAP = {"强吸气": 0.40, "吸气": 0.30, "中性": 0.15, "呼气": 0.00, "深度呼气": 0.00}

# ═══════════════════════════════════════════════════════════════════════════════
# ═══  数据加载（全局单次）  ═══════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class SessionData:
    """Single load of all data files."""
    __slots__ = ("portfolio", "prices", "rotation", "scorecard",
                 "account", "positions", "trade_log", "cash", "total_assets")

    def __init__(self):
        self.portfolio = load_json(PORTFOLIO_FILE)
        self.prices = load_json(PRICES_FILE)
        self.rotation = load_json(ROTATION_FILE)
        self.scorecard = load_json(SCORECARD_FILE)

        self.account = self.portfolio.get("accounts", {}).get("a_share", {})
        self.positions = self.account.get("positions", [])
        self.trade_log = self.portfolio.get("trade_log", [])
        self.cash = float(self.account.get("cash", 0))

        self.total_assets = self.cash
        cn_prices = self.prices.get("cn", {})
        for pos in self.positions:
            ticker = pos.get("ticker", "")
            shares = pos.get("shares", 0)
            price = cn_prices.get(ticker, {}).get("price") or pos.get("current_price") or pos.get("avg_cost", 0)
            self.total_assets += float(price) * shares


# ═══════════════════════════════════════════════════════════════════════════════
# ═══  Section 1: 持仓概览  ═══════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

def render_portfolio(d: SessionData) -> list[str]:
    lines: list[str] = []
    w = lines.append

    cash_pct = (d.cash / d.total_assets * 100) if d.total_assets > 0 else 0
    ta_count = sum(1 for p in d.positions if p.get("track", "A") != "B")
    tb_count = sum(1 for p in d.positions if p.get("track") == "B")
    total_count = len(d.positions)

    w("═══ 持仓概览 ═══")
    w(f"  总资产: ¥{d.total_assets:,.0f} | 现金: ¥{d.cash:,.0f} ({cash_pct:.1f}%)")
    track_str = f"Track A: {ta_count}"
    if tb_count > 0:
        track_str += f" | Track B: {tb_count}"
    w(f"  持仓: {total_count}只 (上限{ASTOCK_MAX_POSITIONS}) | {track_str}")
    w("")

    if not d.positions:
        w("  (空仓)")
        w("")
        return lines

    # Table header
    w(f"  {'名称':<10} {'评级':<4} {'仓位%':>6} {'浮盈%':>7} {'止损距%':>7} {'催化剂':<16}")
    w(f"  {'─'*60}")

    cn_prices = d.prices.get("cn", {})
    sorted_pos = sorted(d.positions, key=lambda p: p.get("portfolio_pct", 0), reverse=True)

    for pos in sorted_pos:
        name = (pos.get("name", "?"))[:10]
        grade = pos.get("conviction_level", pos.get("confidence", pos.get("tb_grade", "?")))
        track = pos.get("track", "A")
        if track == "B":
            grade = f"TB:{pos.get('tb_grade', '?')}"

        ticker = pos.get("ticker", "")
        shares = pos.get("shares", 0)
        avg_cost = float(pos.get("avg_cost", 0))
        price = cn_prices.get(ticker, {}).get("price") or pos.get("current_price") or avg_cost
        price = float(price)

        mkt_val = price * shares
        pct = (mkt_val / d.total_assets * 100) if d.total_assets > 0 else 0
        pnl_pct = ((price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0

        stop = pos.get("stop_loss")
        stop_dist = ""
        if stop and price > 0:
            dist = (price - float(stop)) / price * 100
            stop_dist = f"{dist:.1f}"

        catalyst = (pos.get("next_catalyst") or "—")[:16]

        w(f"  {name:<10} {grade:<4} {pct:>6.1f} {pnl_pct:>+7.1f} {stop_dist:>7} {catalyst:<16}")

    w(f"  {'─'*60}")
    w("")
    return lines


# ═══════════════════════════════════════════════════════════════════════════════
# ═══  Section 2: 风控摘要  ═══════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

def render_risk(d: SessionData) -> list[str]:
    lines: list[str] = []
    w = lines.append
    w("═══ 风控摘要 ═══")

    alerts: list[str] = []
    cn_prices = d.prices.get("cn", {})

    # 1. Single position check
    max_pct = 0.0
    max_name = ""
    max_grade = ""
    for pos in d.positions:
        ticker = pos.get("ticker", "")
        shares = pos.get("shares", 0)
        price = cn_prices.get(ticker, {}).get("price") or pos.get("current_price") or pos.get("avg_cost", 0)
        mkt_val = float(price) * shares
        pct = (mkt_val / d.total_assets) if d.total_assets > 0 else 0
        if pct > max_pct:
            max_pct = pct
            max_name = pos.get("name", ticker)
            max_grade = pos.get("conviction_level", pos.get("confidence", "B"))
    grade_limit = ASTOCK_POSITION_LIMITS.get(max_grade, 0.25)
    if max_pct > grade_limit:
        alerts.append(f"  !! 单只超限: {max_name} {max_pct:.1%} > {max_grade}上限{grade_limit:.0%}")
    else:
        w(f"  OK 单只上限: 通过 (最大{max_name} {max_pct:.1%} <= {max_grade}上限{grade_limit:.0%})")

    # 2. Position count
    count = len(d.positions)
    if count > ASTOCK_MAX_POSITIONS:
        alerts.append(f"  !! 持仓超限: {count}/{ASTOCK_MAX_POSITIONS}")
    else:
        w(f"  OK 持仓数量: {count}/{ASTOCK_MAX_POSITIONS}")

    # 3. Stop-loss proximity
    near_stop = []
    for pos in d.positions:
        ticker = pos.get("ticker", "")
        stop = pos.get("stop_loss")
        if not stop:
            continue
        price = cn_prices.get(ticker, {}).get("price") or pos.get("current_price") or pos.get("avg_cost", 0)
        price = float(price)
        stop = float(stop)
        if price > 0:
            dist = (price - stop) / price * 100
            if dist < 3.0:
                near_stop.append((pos.get("name", ticker), dist))
            elif dist < 5.0:
                near_stop.append((pos.get("name", ticker), dist))

    if near_stop:
        for name, dist in near_stop:
            level = "!!" if dist < 3.0 else "~~"
            alerts.append(f"  {level} 止损距离: {name} {dist:.1f}%")
    else:
        w("  OK 止损距离: 全部安全")

    # 4. Sector concentration
    sector_map: dict[str, float] = {}
    for pos in d.positions:
        sector = pos.get("sector", "未知")
        ticker = pos.get("ticker", "")
        shares = pos.get("shares", 0)
        price = cn_prices.get(ticker, {}).get("price") or pos.get("current_price") or pos.get("avg_cost", 0)
        mkt_val = float(price) * shares
        pct = (mkt_val / d.total_assets) if d.total_assets > 0 else 0
        sector_map[sector] = sector_map.get(sector, 0) + pct

    same_sector_3 = [(s, p) for s, p in sector_map.items() if p > 0.30]
    if same_sector_3:
        for s, p in same_sector_3:
            alerts.append(f"  ~~ 板块集中: {s} {p:.1%} (关注，非硬约束)")
    else:
        w("  OK 板块集中: 通过")

    if alerts:
        w("")
        for a in alerts:
            w(a)

    w("")
    return lines


# ═══════════════════════════════════════════════════════════════════════════════
# ═══  Section 3: F20 市场呼吸  ═══════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

# ── F20 判定逻辑（from tb_scan.py，完全不改）────────────────────────────────

def determine_f20(limit_up: int, board_break: float, turnover: float,
                  northbound: float | None, limit_down: int,
                  prev_state: dict) -> tuple[str, str]:
    if limit_down > 50:
        return "深度呼气", f"跌停{limit_down}家>50 — 崩溃期"
    if limit_up < 30 and turnover < 5000:
        return "深度呼气", f"涨停{limit_up}<30 + 成交{turnover:.0f}亿<5000亿"
    consec = prev_state.get("market_context", {}).get("consecutive_low_days", 0)
    if limit_up < 30:
        new_consec = consec + 1 if consec >= 0 else 1
        if new_consec >= 3:
            return "呼气", f"涨停{limit_up}<30 连续{new_consec}日 — 强制覆盖为呼气"
        return "中性", f"涨停{limit_up}<30（连续{new_consec}日，<3日暂定中性）"
    if board_break > 50:
        return "呼气", f"炸板率{board_break:.0f}%>50%"
    if limit_up >= 80 and board_break < 20:
        return "强吸气", f"涨停{limit_up}>=80 + 炸板率{board_break:.0f}%<20%"
    if limit_up >= 60 and board_break < 30:
        extra = ""
        if northbound is not None and northbound > 0:
            extra = f" + 北向净流入{northbound:.0f}亿"
        return "吸气", f"涨停{limit_up}家 + 炸板率{board_break:.0f}%{extra}"
    return "中性", f"涨停{limit_up}家 / 炸板率{board_break:.0f}%（模糊区间）"


def check_hard_switch(limit_up: int, board_break: float, limit_down: int,
                      index_chg: float | None, f20: str) -> list[dict]:
    signals = []
    if index_chg is not None and index_chg <= -1.5:
        signals.append({"rule": f"大盘跌{index_chg:+.2f}%", "action": "NO-GO"})
    if limit_down > 50:
        signals.append({"rule": f"跌停{limit_down}家>50", "action": "NO-GO + TB清仓审查"})
    if f20 in ("呼气", "深度呼气"):
        signals.append({"rule": f"F20={f20}", "action": "零新仓" if f20 == "呼气" else "TB归零"})
    if board_break > 60:
        signals.append({"rule": f"炸板率{board_break:.0f}%>60%", "action": "当日全出TB仓位"})
    return signals


def do_f20_scan(d: SessionData, args) -> list[str]:
    """Run full F20 scan with market data, update rotation_state.json."""
    lines: list[str] = []
    w = lines.append

    f20, reason = determine_f20(
        args.limit_up, args.board_break, args.turnover,
        args.northbound, args.limit_down, d.rotation,
    )
    tb_cap = F20_TB_CAP.get(f20, 0.15)

    switches = check_hard_switch(
        args.limit_up, args.board_break, args.limit_down,
        args.index_chg, f20,
    )

    icon = {"强吸气": "++", "吸气": "+ ", "中性": "= ", "呼气": "- ", "深度呼气": "--"}.get(f20, "??")
    w(f"═══ F20 市场呼吸 [{icon}] ═══")
    w(f"  状态: {f20} | TB仓位上限: {tb_cap*100:.0f}%")
    w(f"  依据: {reason}")

    if switches:
        w(f"  硬开关: !! 触发！")
        for s in switches:
            w(f"    !! {s['rule']} -> {s['action']}")
    else:
        w(f"  硬开关: OK 全部通过")

    # Update rotation_state.json
    consec = d.rotation.get("market_context", {}).get("consecutive_low_days", 0)
    new_consec = (consec + 1 if consec >= 0 else 1) if args.limit_up < 30 else 0

    market_switch = "OPEN"
    if switches:
        for s in switches:
            if "清仓" in s.get("action", "") or "归零" in s.get("action", ""):
                market_switch = "EMERGENCY_CLOSE"
                break
        if market_switch != "EMERGENCY_CLOSE":
            market_switch = "CLOSED"
    if f20 in ("呼气", "深度呼气"):
        market_switch = "CLOSED"

    today = datetime.now().strftime("%Y-%m-%d")
    d.rotation.update({
        "market_switch": market_switch,
        "market_breath": f20,
        "f20_last_updated": today,
        "market_context": {
            "limit_up_count": args.limit_up,
            "limit_down_count": args.limit_down,
            "turnover_billion": args.turnover,
            "board_break_rate": args.board_break,
            "northbound_net": args.northbound,
            "index_change_pct": args.index_chg,
            "consecutive_low_days": new_consec,
        },
        "last_scan": today,
    })

    for key in ("active_themes", "watch_pool", "pending_signals"):
        if key not in d.rotation:
            d.rotation[key] = []
    if "restart_confirmation" not in d.rotation:
        d.rotation["restart_confirmation"] = {"days_normal": 0, "restart_ready": False}

    restart = d.rotation["restart_confirmation"]
    if market_switch == "OPEN":
        restart["days_normal"] = restart.get("days_normal", 0) + 1
        if restart["days_normal"] >= 3:
            restart["restart_ready"] = True
    else:
        restart["days_normal"] = 0
        restart["restart_ready"] = False

    save_json(ROTATION_FILE, d.rotation)
    w(f"  [写入] rotation_state.json: switch={market_switch}")

    # GO/NO-GO
    tb_pct = sum(p.get("portfolio_pct", 0) for p in d.positions if p.get("track") == "B")
    tb_count = sum(1 for p in d.positions if p.get("track") == "B")
    has_block = len(switches) > 0 or f20 in ("呼气", "深度呼气")
    if has_block:
        w(f"  GO/NO-GO: !! NO-GO | TB={tb_count}只/{tb_pct*100:.1f}%")
    else:
        w(f"  GO/NO-GO: OK GO | TB={tb_count}只/{tb_pct*100:.1f}%")

    w("")
    return lines


def render_f20_readonly(d: SessionData) -> list[str]:
    """Read-only F20 status from rotation_state.json (no scan)."""
    lines: list[str] = []
    w = lines.append

    f20 = d.rotation.get("market_breath", "未知")
    switch = d.rotation.get("market_switch", "未知")
    updated = d.rotation.get("f20_last_updated", "未知")
    tb_cap = F20_TB_CAP.get(f20, 0.15)

    icon = {"强吸气": "++", "吸气": "+ ", "中性": "= ", "呼气": "- ", "深度呼气": "--"}.get(f20, "??")
    w(f"═══ F20 市场呼吸 [{icon}] ═══")
    w(f"  状态: {f20} | switch={switch} | 更新: {updated}")
    w(f"  TB仓位上限: {tb_cap*100:.0f}%")

    ctx = d.rotation.get("market_context", {})
    if ctx.get("limit_up_count") is not None:
        w(f"  上次数据: 涨停{ctx['limit_up_count']}家 / 炸板率{ctx.get('board_break_rate', 0):.0f}% / 成交{ctx.get('turnover_billion', 0):.0f}亿")

    today = datetime.now().strftime("%Y-%m-%d")
    if updated != "未知" and updated < today:
        w(f"  ~~ F20数据非今日 — 建议: --scan 更新")

    w("")
    return lines


# ═══════════════════════════════════════════════════════════════════════════════
# ═══  Section 4: Track B 状态  ═══════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

# ── CB/CA 逻辑（from tb_review.py，不改）──────────────────────────────────────

def update_cb_state(trade_log: list, scorecard: dict) -> dict:
    today = datetime.now()
    cutoff = today - timedelta(days=7)
    count = 0
    for t in trade_log:
        if t.get("track") != "B":
            continue
        if t.get("realized_pnl", 0) >= 0:
            continue
        if not t.get("rule_violation", False):
            continue
        exit_str = t.get("exit_date") or t.get("date", "")
        if not exit_str:
            continue
        try:
            exit_date = datetime.strptime(exit_str[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if exit_date >= cutoff:
            count += 1

    scorecard["cb_state"] = "RED" if count >= 3 else ("YELLOW" if count >= 2 else "GREEN")
    scorecard["cb_violation_count_7d"] = count
    scorecard["cb_last_updated"] = today.strftime("%Y-%m-%d")
    return scorecard


def update_ca_state(trade_log: list, scorecard: dict) -> dict:
    tb_trades = sorted(
        [t for t in trade_log if t.get("track") == "B" and t.get("exit_date")],
        key=lambda t: t.get("exit_date", ""), reverse=True,
    )
    consec = 0
    for t in tb_trades[:10]:
        if t.get("realized_pnl", 0) > 0:
            consec += 1
        else:
            break
    scorecard["ca_consecutive_wins"] = consec
    scorecard["ca_state"] = "AMPLIFIED" if consec >= 5 else ("WARMING" if consec >= 3 else "NORMAL")
    return scorecard


# ── 持仓天数 + 降级 + 双轨约束（from tb_review + tb_monitor）────────────────

def check_tb_alerts(positions: list, rotation: dict, scorecard: dict) -> list[str]:
    """Consolidated TB alerts: time stops, downgrades, CB, dual-track limits."""
    alerts: list[str] = []
    today = datetime.now()

    tb_pos = [p for p in positions if p.get("track") == "B"]
    tb_count = len(tb_pos)
    ta_count = len(positions) - tb_count
    tb_pct = sum(p.get("portfolio_pct", 0) for p in tb_pos)

    # Time stops
    for pos in tb_pos:
        name = pos.get("name", pos.get("ticker", "?"))
        tb_type = pos.get("tb_type", "T1")
        entry_str = pos.get("tb_entry_date") or pos.get("entry_date", "")
        if not entry_str:
            continue
        try:
            entry_date = datetime.strptime(entry_str[:10], "%Y-%m-%d")
        except ValueError:
            continue
        days = (today - entry_date).days
        limit = TYPE_HOLDING_LIMITS.get(tb_type, 10)
        if days >= limit:
            alerts.append(f"  !! {name}: 持有{days}天 >= {tb_type}上限{limit}天 — 应出场")
        elif days >= limit - 1:
            alerts.append(f"  ~~ {name}: 持有{days}天，明日达上限")

    # Downgrade check (board break)
    board_break = rotation.get("market_context", {}).get("board_break_rate", 0)
    if board_break > 60 and tb_pos:
        alerts.append(f"  !! 炸板率{board_break:.0f}%>60% — 全TB出场")
    elif board_break > 50 and tb_pos:
        alerts.append(f"  ~~ 炸板率{board_break:.0f}%>50% — 全TB降1档+减仓")

    # CB
    cb = scorecard.get("cb_state", "GREEN")
    if cb == "RED":
        alerts.append(f"  !! CB=RED — TB暂停，不可新建仓")
    elif cb == "YELLOW":
        alerts.append(f"  ~~ CB=YELLOW — TB sizing x0.5")

    # Dual-track limits
    if tb_count > 3:
        alerts.append(f"  !! TB持仓{tb_count}>3只上限")
    total = ta_count + tb_count
    if total > 10:
        alerts.append(f"  !! 总持仓{total}>10只上限")

    f20 = rotation.get("market_breath", "中性")
    tb_cap = F20_TB_CAP.get(f20, 0.15)
    if tb_pct > tb_cap and tb_cap > 0:
        alerts.append(f"  !! TB仓位{tb_pct*100:.1f}% > F20={f20}上限{tb_cap*100:.0f}%")

    return alerts


def render_tb_status(d: SessionData) -> list[str]:
    lines: list[str] = []
    w = lines.append

    # Update CB/CA
    d.scorecard = update_cb_state(d.trade_log, d.scorecard)
    d.scorecard = update_ca_state(d.trade_log, d.scorecard)

    tb_pos = [p for p in d.positions if p.get("track") == "B"]
    tb_pct = sum(p.get("portfolio_pct", 0) for p in tb_pos)

    cb = d.scorecard.get("cb_state", "GREEN")
    ca = d.scorecard.get("ca_state", "NORMAL")
    ca_wins = d.scorecard.get("ca_consecutive_wins", 0)
    cb_icon = {"GREEN": "OK", "YELLOW": "~~", "RED": "!!"}.get(cb, "??")
    ca_icon = {"NORMAL": "  ", "WARMING": "* ", "AMPLIFIED": "**"}.get(ca, "  ")

    w("═══ Track B 状态 ═══")
    w(f"  TB持仓: {len(tb_pos)}只 / {tb_pct*100:.1f}%")
    w(f"  CB: [{cb_icon}] {cb} (7日违规{d.scorecard.get('cb_violation_count_7d', 0)}笔) | CA: [{ca_icon}] {ca} ({ca_wins}连胜)")

    # TB position table (if any)
    if tb_pos:
        w(f"  {'─'*50}")
        w(f"  {'名称':<10} {'等级':<4} {'类型':<4} {'天数':>4} {'上限':>4} {'龙头':<8}")
        w(f"  {'─'*50}")
        for p in tb_pos:
            name = (p.get("name", "?"))[:10]
            grade = p.get("tb_grade", "?")
            tb_type = p.get("tb_type", "?")
            leader = (p.get("tb_leader", "?"))[:8]
            entry_str = p.get("tb_entry_date") or p.get("entry_date", "")
            days = 0
            if entry_str:
                try:
                    days = (datetime.now() - datetime.strptime(entry_str[:10], "%Y-%m-%d")).days
                except ValueError:
                    pass
            limit = TYPE_HOLDING_LIMITS.get(tb_type, 10)
            w(f"  {name:<10} {grade:<4} {tb_type:<4} {days:>4} {limit:>4}  {leader:<8}")
        w(f"  {'─'*50}")

    # Type suspensions
    suspensions = d.scorecard.get("type_suspensions", {})
    today_str = datetime.now().strftime("%Y-%m-%d")
    for type_id, info in suspensions.items():
        expires = info.get("expires", "")
        if expires and expires > today_str:
            w(f"  !! {type_id} 暂停至 {expires}: {info.get('reason', '')}")

    # Alerts
    alerts = check_tb_alerts(d.positions, d.rotation, d.scorecard)
    if alerts:
        for a in alerts:
            w(a)
    else:
        w("  OK 无TB警报")

    # Save scorecard
    save_json(SCORECARD_FILE, d.scorecard)

    w("")
    return lines


# ═══════════════════════════════════════════════════════════════════════════════
# ═══  Section 5: 催化剂日历  ═══════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

def render_catalysts(d: SessionData) -> list[str]:
    lines: list[str] = []
    w = lines.append

    today = datetime.now()
    upcoming = []

    for pos in d.positions:
        catalyst = pos.get("next_catalyst")
        catalyst_date = pos.get("catalyst_date", "")
        if not catalyst:
            continue
        name = pos.get("name", pos.get("ticker", "?"))

        days_away = None
        if catalyst_date:
            try:
                cat_dt = datetime.strptime(catalyst_date[:10], "%Y-%m-%d")
                days_away = (cat_dt - today).days
            except ValueError:
                pass

        upcoming.append((days_away if days_away is not None else 999, name, catalyst, catalyst_date))

    # Also check catalyst_calendar_30d
    for evt in d.portfolio.get("catalyst_calendar_30d", []):
        ticker = evt.get("ticker", "")
        # Only include A-stock tickers
        if not (ticker.isdigit() or (len(ticker) == 6 and ticker[:1] in ("0", "3", "6"))):
            continue
        evt_date = evt.get("date", "")
        days_away = None
        if evt_date:
            try:
                days_away = (datetime.strptime(evt_date[:10], "%Y-%m-%d") - today).days
            except ValueError:
                pass
        desc = evt.get("event", evt.get("description", "?"))
        upcoming.append((days_away if days_away is not None else 999, ticker, desc, evt_date))

    if not upcoming:
        return lines

    upcoming.sort(key=lambda x: x[0])
    # Only show within 14 days
    upcoming = [u for u in upcoming if u[0] is not None and u[0] <= 14]

    if not upcoming:
        return lines

    w("═══ 催化剂日历 (14天内) ═══")
    for days, name, catalyst, date_str in upcoming:
        if days is not None and days <= 2:
            urgency = "!!"
        elif days is not None and days <= 7:
            urgency = "~~"
        else:
            urgency = "  "
        date_display = date_str[:10] if date_str else "?"
        w(f"  {urgency} {date_display} [{name}] {catalyst}")
    w("")
    return lines


# ═══════════════════════════════════════════════════════════════════════════════
# ═══  主入口  ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="A股 Session 统一仪表盘")
    p.add_argument("--quick", action="store_true", help="仅持仓+关键警报")
    p.add_argument("--json", action="store_true", help="JSON输出")

    # F20 scan args (optional — only needed with --scan)
    p.add_argument("--scan", action="store_true", help="执行F20扫描（需market data）")
    p.add_argument("--limit-up", type=int, help="涨停家数")
    p.add_argument("--limit-down", type=int, default=0, help="跌停家数")
    p.add_argument("--board-break", type=float, help="炸板率(%%)")
    p.add_argument("--turnover", type=float, default=8000, help="成交额(亿)")
    p.add_argument("--northbound", type=float, default=None, help="北向净流入(亿)")
    p.add_argument("--index-chg", type=float, default=None, help="大盘涨跌幅(%%)")

    return p.parse_args()


def main():
    args = parse_args()

    # Validate scan args
    if args.scan and (args.limit_up is None or args.board_break is None):
        print("ERROR: --scan 需要 --limit-up 和 --board-break", file=sys.stderr)
        sys.exit(1)

    # Single data load
    d = SessionData()

    if args.json:
        # JSON mode: structured output for agent consumption
        result = {
            "total_assets": d.total_assets,
            "cash": d.cash,
            "cash_pct": d.cash / d.total_assets if d.total_assets > 0 else 0,
            "position_count": len(d.positions),
            "positions": [],
            "f20": d.rotation.get("market_breath", "未知"),
            "market_switch": d.rotation.get("market_switch", "未知"),
            "cb_state": d.scorecard.get("cb_state", "GREEN"),
            "ca_state": d.scorecard.get("ca_state", "NORMAL"),
        }
        cn_prices = d.prices.get("cn", {})
        for pos in d.positions:
            ticker = pos.get("ticker", "")
            shares = pos.get("shares", 0)
            avg_cost = float(pos.get("avg_cost", 0))
            price = cn_prices.get(ticker, {}).get("price") or pos.get("current_price") or avg_cost
            price = float(price)
            result["positions"].append({
                "ticker": ticker,
                "name": pos.get("name"),
                "grade": pos.get("conviction_level", pos.get("confidence")),
                "track": pos.get("track", "A"),
                "pct": round((price * shares / d.total_assets) * 100, 1) if d.total_assets > 0 else 0,
                "pnl_pct": round(((price - avg_cost) / avg_cost) * 100, 1) if avg_cost > 0 else 0,
                "stop_loss": pos.get("stop_loss"),
                "catalyst": pos.get("next_catalyst"),
            })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Render dashboard
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    output: list[str] = []
    output.append("")
    output.append(f"  A股 Session Dashboard | {now}")
    output.append(f"  {'='*50}")
    output.append("")

    # Section 1: Portfolio
    output.extend(render_portfolio(d))

    if args.quick:
        # Quick mode: only critical alerts
        alerts = check_tb_alerts(d.positions, d.rotation, d.scorecard)
        critical = [a for a in alerts if "!!" in a]
        if critical:
            output.append("═══ 关键警报 ═══")
            output.extend(critical)
            output.append("")
        print("\n".join(output))
        return

    # Section 2: Risk
    output.extend(render_risk(d))

    # Section 3: F20
    if args.scan:
        output.extend(do_f20_scan(d, args))
    else:
        output.extend(render_f20_readonly(d))

    # Section 4: TB Status
    output.extend(render_tb_status(d))

    # Section 5: Catalysts
    output.extend(render_catalysts(d))

    print("\n".join(output))


if __name__ == "__main__":
    main()
