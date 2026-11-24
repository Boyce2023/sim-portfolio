#!/usr/bin/env python3
"""
astock_gto_mapper.py — A股五策略严格 GTO 6-Max 100bb 概率牌型映射器 (V19.1 物理校准真账锚定)

数学锚定 (2021-11 至 2026-11 五年 1215 交易日 · 228 笔单仓洁净真账):
- 日均入池频率 (Daily VPIP) = 228 / 1215 = 18.77%，精确对应 6-Max 100bb GTO LJ/UTG 开池范围 (~18.8%, 约 250 / 1326 combos)
- 各策略底池赔率盈亏平衡胜率 p_BE = |avg_loss| / (avg_win + |avg_loss|)
- 权益溢出 (Equity Edge) = 实际胜率 WR - p_BE
- 只作汇报与直觉翻译层，严禁修改任何策略打分、门槛与下单逻辑。
"""
from __future__ import annotations

GTO_CALIBRATION = {
    "s_3to4": {
        "name": "三进四V4.1",
        "thr": 90.0, "s_thr": 102.0,
        "p25": 94.0, "p50": 97.0, "p75": 103.5, "p90": 108.6, "max": 121.0,
        "wr": 65.3, "p_be": 33.9, "edge_pp": 31.4, "plr": 1.95, "ev": 9.08,
        "near_gap": 15.0, "mid_gap": 30.0,
    },
    "s_high": {
        "name": "高标首阴V5.1",
        "thr": 88.0, "s_thr": 96.0,
        "p25": 99.0, "p50": 109.0, "p75": 119.0, "p90": 128.7, "max": 141.0,
        "wr": 71.4, "p_be": 26.1, "edge_pp": 45.3, "plr": 2.83, "ev": 6.99,
        "near_gap": 15.0, "mid_gap": 30.0,
    },
    "s_pry": {
        "name": "超跌撬板V2.1",
        "thr": 165.0, "s_thr": 175.0,
        "p25": 170.0, "p50": 175.0, "p75": 187.5, "p90": 195.0, "max": 220.0,
        "wr": 87.5, "p_be": 57.1, "edge_pp": 30.4, "plr": 0.75, "ev": 6.19,
        "near_gap": 15.0, "mid_gap": 35.0,
    },
    "s_2to3": {
        "name": "二进三V2.1",
        "thr": 90.0, "s_thr": 96.0,
        "p25": 90.0, "p50": 92.0, "p75": 96.0, "p90": 100.6, "max": 107.0,
        "wr": 53.7, "p_be": 17.9, "edge_pp": 35.7, "plr": 4.57, "ev": 7.68,
        "near_gap": 15.0, "mid_gap": 30.0,
    },
    "s_1to2": {
        "name": "一进二V20",
        "thr": 304.8, "s_thr": 329.8,
        "p25": 322.0, "p50": 340.1, "p75": 358.4, "p90": 373.6, "max": 429.6,
        "wr": 68.0, "p_be": 25.8, "edge_pp": 42.3, "plr": 2.88, "ev": 7.24,
        "near_gap": 25.0, "mid_gap": 65.0,
    },
    "s_20cm_deepopen": {
        "name": "20cm深水错杀V1.1",
        "thr": 82.0, "s_thr": 82.0,
        "p25": 83.0, "p50": 86.0, "p75": 90.0, "p90": 92.0, "max": 95.0,
        "wr": 57.8, "p_be": 33.2, "edge_pp": 24.6, "plr": 2.01, "ev": 3.59,
        "near_gap": 6.0, "mid_gap": 15.0,
    },
}

RIO_TRAP_KEYWORDS = ("退潮脉冲", "假题材", "同板均值弱", "后排", "首板松散", "门禁", "换手", "低位", "雪球")
DEAD_KEYWORDS = ("一字", "毒丸", "监管", "熔断", "停牌", "ST")


def classify_gto_hand(
    strategy_id: str,
    score: float,
    is_passed: bool,
    veto_text: str = "",
    is_yizi: bool = False,
    thr_override: float | None = None,
) -> dict:
    """Deterministic GTO 6-Max 100bb hand & probability classification."""
    cal = GTO_CALIBRATION[strategy_id]
    thr = float(thr_override) if thr_override is not None else cal["thr"]
    sc = float(score)
    vt = str(veto_text or "")

    if is_passed:
        if sc >= cal["p90"]:
            hand, rng, act = "AA", "Top1.9%|过线前10%", "纯4Bet价值Open"
        elif sc >= cal["p75"]:
            hand, rng, act = "KK", "Top4.7%|过线前25%", "顶尖S档价值Open"
        elif sc >= cal["p50"]:
            hand, rng, act = "QQ/JJ", "Top9.4%|过线前50%", "核心中上牌Open"
        elif sc >= cal["p25"]:
            hand, rng, act = "TT/AQs", "Top14.1%|过线前75%", "标准价值Open"
        else:
            hand, rng, act = "99/AJs", "Top18.8%|范围底边", "压线底边Open"
        return {
            "hand": hand,
            "range_band": rng,
            "action": act,
            "short": f"GTO:{hand}[{act}]",
            "wr": cal["wr"],
            "p_be": cal["p_be"],
            "edge_pp": cal["edge_pp"],
            "ev": cal["ev"],
        }

    # Rejected hands: strictly classify by GTO failure mode
    if is_yizi or any(k in vt for k in DEAD_KEYWORDS):
        tag = "一字死牌" if (is_yizi or "一字" in vt) else "毒丸/熔断死牌"
        return {
            "hand": "Dead",
            "range_band": "不可玩死牌",
            "action": f"{tag}0%Fold",
            "short": f"GTO:Dead[{tag}]",
            "wr": 0.0, "p_be": cal["p_be"], "edge_pp": -cal["p_be"], "ev": 0.0,
        }

    gap = thr - sc
    has_rio = any(k in vt for k in RIO_TRAP_KEYWORDS)

    if sc >= thr:
        if has_rio:
            return {
                "hand": "KQo",
                "range_band": "RIO被压制陷阱",
                "action": "高分撞结构陷阱Fold",
                "short": "GTO:KQo[RIO陷阱Fold]",
                "wr": 0.0, "p_be": cal["p_be"], "edge_pp": 0.0, "ev": 0.0,
            }
        return {
            "hand": "AJo",
            "range_band": "Top19%-23%|0EV失位",
            "action": "够分但竞价失位Fold",
            "short": "GTO:AJo[0EV失位Fold]",
            "wr": 0.0, "p_be": cal["p_be"], "edge_pp": 0.0, "ev": 0.0,
        }

    if gap <= cal["near_gap"]:
        if has_rio:
            return {
                "hand": "QJo",
                "range_band": "Top24%-35%|RIO陷阱",
                "action": "差线且结构压制Fold",
                "short": "GTO:QJo[RIO陷阱Fold]",
                "wr": 0.0, "p_be": cal["p_be"], "edge_pp": 0.0, "ev": 0.0,
            }
        return {
            "hand": "ATo/KJo",
            "range_band": "Top19%-26%|0EV临界",
            "action": "范围底边外0%Fold",
            "short": "GTO:ATo/KJo[临界Fold]",
            "wr": 0.0, "p_be": cal["p_be"], "edge_pp": 0.0, "ev": 0.0,
        }

    if gap <= cal["mid_gap"]:
        return {
            "hand": "J8o/T7o",
            "range_band": "中下游弱杂牌",
            "action": "筹码不足纯Fold",
            "short": "GTO:J8o/T7o[弱牌Fold]",
            "wr": 0.0, "p_be": cal["p_be"], "edge_pp": 0.0, "ev": 0.0,
        }

    return {
        "hand": "72o",
        "range_band": "后55%|-EV纯弃",
        "action": "负期望垃圾纯Fold",
        "short": "GTO:72o[-EV纯Fold]",
        "wr": 0.0, "p_be": cal["p_be"], "edge_pp": 0.0, "ev": 0.0,
    }
