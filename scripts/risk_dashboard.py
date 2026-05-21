#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
risk_dashboard.py — 风险仪表盘数据生成器
生成供Railway前端消费的风险仪表盘JSON。
数据来源: portfolio_state.json

CLI:
    uv run --script scripts/risk_dashboard.py                          # stdout
    uv run --script scripts/risk_dashboard.py --output dashboard.json  # 文件
"""

import json
import sys
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ── 路径 ───────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "portfolio_state.json"
RISK_METRICS_FILE = REPO_ROOT / "scripts" / "risk_metrics_output.json"

# ── 风控限额 ────────────────────────────────────────────────────────────────────
LIMIT_SINGLE_POSITION = 0.15   # 单只 ≤ 15%
LIMIT_SECTOR          = 0.30   # 单板块 ≤ 30%
LIMIT_CASH_MIN        = 0.20   # 现金 ≥ 20%

# ── 板块 Beta 估算（无 yfinance，使用历史近似值）───────────────────────────────
SECTOR_BETA = {
    "AI芯片/半导体": 1.8,
    "AI芯片":        1.8,
    "消费科技/硬件": 1.2,
    "AI搜索/云计算": 1.4,
    "软件/SaaS":     1.3,
    "铀/核能":       1.6,
    "电力设备/燃气轮机": 1.1,
    "数据中心电气配电":  1.5,
    "电力设备":       1.0,
    "半导体封装":     1.6,
    "PCB/苹果链":    1.3,
    "机器人/精密齿轮": 1.7,
    "现金":           0.0,
}

DEFAULT_BETA = 1.2  # 找不到板块时的默认值


def load_state() -> dict:
    if not STATE_FILE.exists():
        print(f"[ERROR] portfolio_state.json not found at {STATE_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_risk_metrics() -> dict:
    """可选：读取 risk_metrics.py 的输出（如果存在）。"""
    if RISK_METRICS_FILE.exists():
        try:
            with open(RISK_METRICS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_beta(sector: str) -> float:
    return SECTOR_BETA.get(sector, DEFAULT_BETA)


def safe_stop_distance(position: dict) -> float | None:
    """
    止损距离 = (stop_loss - current_price) / current_price * 100
    返回负数（价格在止损上方为负，已触止损为正）。
    """
    current = position.get("current_price")
    stop = position.get("stop_loss")
    if current is None or stop is None or current == 0:
        return None
    return round((stop - current) / current * 100, 2)


def collect_all_positions(state: dict) -> list[dict]:
    """
    从 a_share + us 两个账户提取所有持仓，
    标准化为统一格式（权重用各自账户占比）。
    """
    positions = []

    for acct_id, acct in state.get("accounts", {}).items():
        total_assets = acct.get("total_assets", 1) or 1
        for pos in acct.get("positions", []):
            mv = pos.get("market_value", 0) or 0
            weight = mv / total_assets if total_assets else 0
            positions.append({
                "ticker":          pos.get("ticker", ""),
                "name":            pos.get("name", ""),
                "sector":          pos.get("sector", "未知"),
                "type":            pos.get("type", ""),
                "market_value":    mv,
                "weight":          weight,          # 在本账户内的权重
                "current_price":   pos.get("current_price"),
                "stop_loss":       pos.get("stop_loss"),
                "stop_loss_pct":   pos.get("stop_loss_pct"),
                "bear_case_downside": pos.get("bear_case_downside"),
                "unrealized_pnl_pct": pos.get("unrealized_pnl_pct", 0),
                "portfolio_pct":   pos.get("portfolio_pct"),  # 文件中已有
                "account":         acct_id,
                "currency":        acct.get("currency", ""),
            })
    return positions


def build_position_risks(positions: list[dict]) -> list[dict]:
    result = []
    for p in positions:
        ticker = p["ticker"]
        sector = p["sector"]
        weight_pct = round((p["portfolio_pct"] or p["weight"]) * 100, 2)
        beta = get_beta(sector)
        stop_dist = safe_stop_distance(p)
        bear_down = p.get("bear_case_downside")
        bear_pct = round(bear_down * 100, 1) if bear_down is not None else None

        risk_flags = []

        # 单仓超限
        if weight_pct > LIMIT_SINGLE_POSITION * 100:
            risk_flags.append(f"OVERWEIGHT: {weight_pct}% > {LIMIT_SINGLE_POSITION*100}%限额")

        # 止损距离 < 5%（接近止损线）
        if stop_dist is not None and stop_dist > -5:
            if stop_dist >= 0:
                risk_flags.append(f"STOP_TRIGGERED: 价格已穿越止损线")
            else:
                risk_flags.append(f"NEAR_STOP: 距止损仅 {abs(stop_dist):.1f}%")

        # bear case ≥ 20%（borderline）
        if bear_pct is not None and bear_pct <= -20:
            risk_flags.append(f"BEAR_CASE_LIMIT: bear case {bear_pct}%")

        result.append({
            "ticker":           ticker,
            "name":             p["name"],
            "sector":           sector,
            "account":          p["account"],
            "weight_pct":       weight_pct,
            "beta":             beta,
            "stop_distance_pct": stop_dist,
            "bear_case_pct":    bear_pct,
            "unrealized_pnl_pct": round(p.get("unrealized_pnl_pct") or 0, 2),
            "risk_flags":       risk_flags,
        })

    # 按 weight_pct 降序排列
    result.sort(key=lambda x: x["weight_pct"], reverse=True)
    return result


def build_sector_breakdown(positions: list[dict]) -> dict[str, float]:
    """板块合并权重（按各账户内 portfolio_pct 聚合）。"""
    breakdown: dict[str, float] = {}
    for p in positions:
        sector = p["sector"]
        weight = (p["portfolio_pct"] or p["weight"]) * 100
        breakdown[sector] = round(breakdown.get(sector, 0) + weight, 2)
    # 按权重降序
    return dict(sorted(breakdown.items(), key=lambda x: x[1], reverse=True))


def calc_hhi(weights_pct: list[float]) -> float:
    """HHI = Σ(wi²), wi 为小数。"""
    total = sum(weights_pct)
    if total == 0:
        return 0.0
    hhi = sum((w / 100) ** 2 for w in weights_pct)
    return round(hhi, 4)


def build_concentration(positions: list[dict], sector_breakdown: dict) -> dict:
    weights = [p["weight_pct"] for p in sorted(
        [{"weight_pct": (p["portfolio_pct"] or p["weight"]) * 100} for p in positions],
        key=lambda x: x["weight_pct"], reverse=True
    )]
    hhi = calc_hhi(weights)
    top3 = round(sum(sorted(weights, reverse=True)[:3]), 2)

    return {
        "hhi":             hhi,
        "hhi_interpretation": (
            "分散" if hhi < 0.15 else
            "适度集中" if hhi < 0.25 else
            "高度集中"
        ),
        "top3_pct":        top3,
        "sector_breakdown": sector_breakdown,
    }


def build_limit_checks(
    positions: list[dict],
    sector_breakdown: dict,
    cash_pct_us: float,
    cash_pct_cn: float,
) -> list[dict]:
    checks = []

    # ── 1. 单仓位 ≤ 15% ──────────────────────────────────────────────────────
    if positions:
        worst_pos = max(positions, key=lambda p: (p["portfolio_pct"] or p["weight"]))
        worst_pos_pct = round((worst_pos["portfolio_pct"] or worst_pos["weight"]) * 100, 2)
        worst_pos_label = f"{worst_pos['ticker']} {worst_pos_pct}%"
        single_fail = worst_pos_pct > LIMIT_SINGLE_POSITION * 100
    else:
        worst_pos_pct = 0.0
        worst_pos_label = "N/A (no positions)"
        single_fail = False
    checks.append({
        "rule":   "single_position_15pct",
        "desc":   "单只持仓 ≤ 15%",
        "status": "FAIL" if single_fail else "PASS",
        "worst":  worst_pos_label,
        "limit":  "15%",
        "value":  f"{worst_pos_pct}%",
    })

    # ── 2. 单板块 ≤ 30% ──────────────────────────────────────────────────────
    if sector_breakdown:
        worst_sector = max(sector_breakdown.items(), key=lambda x: x[1])
        worst_sector_label = f"{worst_sector[0]} {worst_sector[1]}%"
        sector_fail = worst_sector[1] > LIMIT_SECTOR * 100
    else:
        worst_sector_label = "N/A"
        sector_fail = False
    checks.append({
        "rule":   "sector_30pct",
        "desc":   "单板块集中度 ≤ 30%",
        "status": "FAIL" if sector_fail else "PASS",
        "worst":  worst_sector_label,
        "limit":  "30%",
        "value":  worst_sector_label.split(" ")[-1] if sector_breakdown else "0%",
    })

    # ── 3. 美股现金 ≥ 20% ────────────────────────────────────────────────────
    us_cash_fail = cash_pct_us < LIMIT_CASH_MIN
    checks.append({
        "rule":   "us_cash_20pct",
        "desc":   "美股账户现金 ≥ 20%",
        "status": "FAIL" if us_cash_fail else "PASS",
        "worst":  None,
        "limit":  "20%",
        "value":  f"{round(cash_pct_us * 100, 1)}%",
    })

    # ── 4. A股现金 ≥ 20% ─────────────────────────────────────────────────────
    cn_cash_fail = cash_pct_cn < LIMIT_CASH_MIN
    checks.append({
        "rule":   "cn_cash_20pct",
        "desc":   "A股账户现金 ≥ 20%",
        "status": "FAIL" if cn_cash_fail else "PASS",
        "worst":  None,
        "limit":  "20%",
        "value":  f"{round(cash_pct_cn * 100, 1)}%",
    })

    return checks


def build_portfolio_beta(positions: list[dict]) -> float:
    """加权平均 Beta。"""
    total_weight = 0.0
    weighted_beta = 0.0
    for p in positions:
        w = p["portfolio_pct"] or p["weight"]
        beta = get_beta(p["sector"])
        weighted_beta += w * beta
        total_weight += w
    if total_weight == 0:
        return 1.0
    return round(weighted_beta / total_weight, 3)


def build_alerts(
    position_risks: list[dict],
    limit_checks: list[dict],
    concentration: dict,
) -> list[dict]:
    alerts = []

    # 限额违规
    for chk in limit_checks:
        if chk["status"] == "FAIL":
            alerts.append({
                "level":   "critical",
                "type":    "limit_breach",
                "rule":    chk["rule"],
                "message": f"[{chk['rule'].upper()}] {chk['desc']} 违规: {chk['value']} > {chk['limit']}",
            })

    # 接近止损的持仓
    for pos in position_risks:
        for flag in pos["risk_flags"]:
            if "STOP_TRIGGERED" in flag or "NEAR_STOP" in flag:
                level = "critical" if "STOP_TRIGGERED" in flag else "warning"
                alerts.append({
                    "level":   level,
                    "type":    "stop_loss",
                    "ticker":  pos["ticker"],
                    "message": f"[{pos['ticker']}] {flag}",
                })
            elif "OVERWEIGHT" in flag:
                alerts.append({
                    "level":   "critical",
                    "type":    "position_limit",
                    "ticker":  pos["ticker"],
                    "message": f"[{pos['ticker']}] {flag}",
                })
            elif "BEAR_CASE_LIMIT" in flag:
                alerts.append({
                    "level":   "warning",
                    "type":    "bear_case",
                    "ticker":  pos["ticker"],
                    "message": f"[{pos['ticker']}] {flag}",
                })

    # HHI 过高
    if concentration["hhi"] > 0.25:
        alerts.append({
            "level":   "warning",
            "type":    "concentration",
            "message": f"[HHI] 组合集中度偏高: HHI={concentration['hhi']} ({concentration['hhi_interpretation']})",
        })

    return alerts


def score_risk(
    position_risks: list[dict],
    limit_checks: list[dict],
    concentration: dict,
    portfolio_beta: float,
) -> int:
    """
    风险评分 0-100（越高越险）。
    构成:
      - 集中度 (HHI)         权重 30 分
      - 止损距离              权重 25 分
      - 限额逼近程度          权重 25 分
      - Beta                  权重 20 分
    """
    score = 0.0

    # 1. 集中度 (HHI: 0 → 0分, 0.5+ → 30分)
    hhi = concentration["hhi"]
    score += min(hhi / 0.5, 1.0) * 30

    # 2. 止损距离（加权平均止损距离，越近越高分）
    stop_distances = [
        abs(p["stop_distance_pct"])
        for p in position_risks
        if p["stop_distance_pct"] is not None and p["stop_distance_pct"] < 0
    ]
    if stop_distances:
        avg_stop = sum(stop_distances) / len(stop_distances)
        # 距止损 2% → 25分; 20% → 0分
        stop_score = max(0, (20 - avg_stop) / 18) * 25
        score += stop_score

    # 3. 限额逼近程度
    fail_count = sum(1 for c in limit_checks if c["status"] == "FAIL")
    if limit_checks:
        score += min(fail_count / len(limit_checks), 1.0) * 25

    # 4. Beta（beta=1 → 0分, beta=2.5 → 20分）
    score += min((portfolio_beta - 0.5) / 2.0, 1.0) * 20

    return min(100, max(0, round(score)))


def risk_level(score: int, has_fail: bool) -> str:
    if has_fail:
        return "high"
    if score >= 70:
        return "high"
    if score >= 40:
        return "moderate"
    return "low"


def build_dashboard(state: dict, risk_metrics: dict) -> dict:
    accounts = state.get("accounts", {})
    us_acct = accounts.get("us", {})
    cn_acct = accounts.get("a_share", {})

    cash_pct_us = us_acct.get("cash_pct") or (
        us_acct.get("cash", 0) / us_acct.get("total_assets", 1)
        if us_acct.get("total_assets") else 0
    )
    cash_pct_cn = cn_acct.get("cash_pct") or (
        cn_acct.get("cash", 0) / cn_acct.get("total_assets", 1)
        if cn_acct.get("total_assets") else 0
    )

    positions = collect_all_positions(state)
    position_risks = build_position_risks(positions)
    sector_breakdown = build_sector_breakdown(positions)
    concentration = build_concentration(positions, sector_breakdown)
    limit_checks = build_limit_checks(positions, sector_breakdown, cash_pct_us, cash_pct_cn)
    portfolio_beta = build_portfolio_beta(positions)
    alerts = build_alerts(position_risks, limit_checks, concentration)

    has_fail = any(c["status"] == "FAIL" for c in limit_checks)
    p_score = score_risk(position_risks, limit_checks, concentration, portfolio_beta)
    r_level = risk_level(p_score, has_fail)

    # 合并 risk_metrics.py 外部数据（如存在）
    external_volatilities: dict = risk_metrics.get("volatilities", {})

    # 将波动率注入 position_risks（如果外部提供了）
    for pr in position_risks:
        vol = external_volatilities.get(pr["ticker"])
        if vol is not None:
            pr["volatility_30d"] = vol

    # ── 最终输出 ───────────────────────────────────────────────────────────────
    dashboard = {
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "source_file":         str(STATE_FILE),
        "portfolio_risk_score": p_score,
        "risk_level":          r_level,
        "portfolio_beta":      portfolio_beta,
        "accounts": {
            "us": {
                "total_assets_usd":  us_acct.get("total_assets"),
                "cash_usd":          us_acct.get("cash"),
                "cash_pct":          round(cash_pct_us * 100, 1),
                "invested_pct":      round((1 - cash_pct_us) * 100, 1),
            },
            "a_share": {
                "total_assets_cny":  cn_acct.get("total_assets"),
                "cash_cny":          cn_acct.get("cash"),
                "cash_pct":          round(cash_pct_cn * 100, 1),
                "invested_pct":      round((1 - cash_pct_cn) * 100, 1),
            },
        },
        "position_risks":      position_risks,
        "concentration":       concentration,
        "limit_checks":        limit_checks,
        "alerts":              alerts,
        "meta": {
            "positions_count": len(positions),
            "limits": {
                "single_position": f"{LIMIT_SINGLE_POSITION*100:.0f}%",
                "sector":          f"{LIMIT_SECTOR*100:.0f}%",
                "cash_min":        f"{LIMIT_CASH_MIN*100:.0f}%",
            },
            "risk_metrics_loaded": bool(risk_metrics),
        },
    }

    return dashboard


def main():
    parser = argparse.ArgumentParser(
        description="生成风险仪表盘 JSON。"
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="输出到文件（默认: stdout）",
    )
    args = parser.parse_args()

    state = load_state()
    risk_metrics = load_risk_metrics()
    dashboard = build_dashboard(state, risk_metrics)

    output_json = json.dumps(dashboard, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"[OK] 风险仪表盘已写入: {out_path.resolve()}", file=sys.stderr)
        # 同时打印摘要
        print(
            f"[摘要] score={dashboard['portfolio_risk_score']} "
            f"level={dashboard['risk_level']} "
            f"beta={dashboard['portfolio_beta']} "
            f"alerts={len(dashboard['alerts'])} "
            f"fails={sum(1 for c in dashboard['limit_checks'] if c['status']=='FAIL')}",
            file=sys.stderr,
        )
    else:
        print(output_json)


if __name__ == "__main__":
    main()
