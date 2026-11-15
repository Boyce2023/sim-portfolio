#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
p1_sim_engine.py: 冰点超跌撬板高仿真执行与评测底座 (P1 专属)
严格遵守 D12（零 yfinance）、D15（四必核）、零未来函数与反幸存者偏差铁律：
  1. 只要盘中触及买点成交，哪怕尾盘二次回封跌停，次日连续一字跌停锁死，也必须 100% 计入分母；
  2. 顺延到第一个非一字跌停且有成交量的开板日按开盘价割肉；
  3. 双边摩擦 0.20% (FEE_RATE = 0.0020)；
  4. 支持 B1~B6 六种买法与 E1~E6 六种卖法；
  5. D15 机构级核算：单仓轮动、双半仓轮动、按日等权、近5年/近3年/近期/IS/OOS、去Top3/Top5净值、沪深300净超额。
"""
import os
import sys
import json
import sqlite3
import numpy as np
import pandas as pd

FEE_RATE = 0.0020

# 沪深300基准字典
SANDBOX = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab"
with open(f"{SANDBOX}/index_klines_5y_cache.json", "r", encoding="utf-8") as _f:
    _IDX = json.load(_f)
CSI300_MAP = _IDX["sh000300"]
ALL_CSI_DTS = sorted(CSI300_MAP.keys())


def csi300_period_ret(start_dt: str, end_dt: str) -> float:
    dts = [d for d in ALL_CSI_DTS if start_dt <= d <= end_dt]
    if len(dts) < 2:
        return 0.0
    p0_idx = max(0, ALL_CSI_DTS.index(dts[0]) - 1)
    base_dt = ALL_CSI_DTS[p0_idx]
    return float(CSI300_MAP[dts[-1]] / CSI300_MAP[base_dt] - 1.0)


CSI_BENCHMARKS = {
    "full_5y": csi300_period_ret("2022-01-04", "2026-11-10"),      # -17.84%
    "recent_3y": csi300_period_ret("2023-11-10", "2026-11-10"),    # +12.35%
    "recent": csi300_period_ret("2026-07-01", "2026-11-10"),       # -18.48%
    "is": csi300_period_ret("2022-01-04", "2024-12-31"),           # -20.35%
    "oos": csi300_period_ret("2025-01-01", "2026-11-10"),          # +3.16%
}


def is_locked_limit_down_bar(op: float, hi: float, lo: float, cl: float, pc: float, is_yz_dt: bool) -> bool:
    """严格判定全天一字跌停锁死不可卖状态（包括10%主板与5%ST一字跌停）"""
    if is_yz_dt:
        return True
    if pc > 0 and (op == hi == lo == cl) and (cl / pc - 1.0 <= -0.044):
        return True
    return False


def is_close_limit_down(cl: float, pc: float, dt_px: float, is_dt: bool) -> bool:
    """判定15:00收盘是否封死跌停（尾盘封死不可在收盘卖出）"""
    if is_dt or (cl <= dt_px + 0.011):
        return True
    if pc > 0:
        st_dt = np.floor(pc * 0.95 * 100.0 + 0.5) / 100.0
        if abs(cl - st_dt) <= 0.011 and cl <= pc * 0.955:
            return True
    return False


def sim_single_exit(b: dict, pos: int, buy_px: float, exit_mode: str) -> tuple:
    """
    仿真单笔交易在指定卖法下的退出结果。
    返回: (exit_date, net_ret, hold_bars, exit_at_open)
    
    支持卖法:
      - E1_next_open: 次日开盘秒走 (若次日一字跌停不可卖，严格顺延至第一个开板日开盘割肉)
      - E2_tp5_h2: 冲 +5% 止盈，最长持有 2 天 (Day 2 收盘出局，若跌停顺延)
      - E3_tp7_h2: 冲 +7% 止盈，最长持有 2 天
      - E4_tp7_h3: 冲 +7% 止盈，最长持有 3 天
      - E5_tp7_h5: 冲 +7% 止盈，最长持有 5 天 (旧版对照)
      - E6_cut_reseal_tp7_h3: 断腕护城河卖法
          * Day 0 尾盘二次回封跌停或大阴 (close < buy_px * 0.985): 次日一旦开板在开盘价立即止损！绝不死扛5天！
          * Day 0 收红/长腿 (close >= buy_px):
              - 若 Day 0 地天板封涨停 (is_zt): 次日若继续连板一字涨停则持股，破板或触及止盈出局，最长持有 3 天
              - 普通收红/长腿: 冲 +7% 止盈，最长持有 3 天 (Day 3 收盘)
    """
    n = len(b["dts"])
    adj0 = b["adjf"][pos]
    buy_adj = buy_px * adj0
    dts = b["dts"]
    opens, highs, lows, closes = b["open"], b["high"], b["low"], b["close"]
    adjfs, pre_cs, dt_pxs, zt_pxs = b["adjf"], b["pre_c"], b["dt_px"], b["zt_px"]
    is_dts, is_yz_dts, is_zts = b["is_dt"], b["is_yizi_dt"], b["is_zt"]
    tos = b["to"]

    if pos >= n - 1:
        return dts[pos], -FEE_RATE, 0, False

    day0_cl = closes[pos]
    day0_is_zt = bool(is_zts[pos]) or (day0_cl >= zt_pxs[pos] - 0.011)
    day0_reseal_or_loss = (day0_cl < buy_px * 0.985) or (day0_cl <= dt_pxs[pos] + 0.011)

    # 确定此卖法的最大持仓天数与止盈阈值
    if exit_mode == "E1_next_open":
        tp_pct = 0.0
        max_hold = 1
        is_cut_fast = True
    elif exit_mode == "E2_tp5_h2":
        tp_pct = 0.05
        max_hold = 2
        is_cut_fast = False
    elif exit_mode == "E3_tp7_h2":
        tp_pct = 0.07
        max_hold = 2
        is_cut_fast = False
    elif exit_mode == "E4_tp7_h3":
        tp_pct = 0.07
        max_hold = 3
        is_cut_fast = False
    elif exit_mode == "E5_tp7_h5":
        tp_pct = 0.07
        max_hold = 5
        is_cut_fast = False
    elif exit_mode == "E6_cut_reseal_tp7_h3":
        if day0_reseal_or_loss:
            # 撬板失败，尾盘封回跌停或大阴：次日开盘立割
            tp_pct = 0.0
            max_hold = 1
            is_cut_fast = True
        else:
            # 撬板成功，日内红盘或长腿
            tp_pct = 0.07
            max_hold = 3
            is_cut_fast = False
    else:
        raise ValueError(f"Unknown exit mode: {exit_mode}")

    last_tradable_idx = -1
    tradable_step = 0

    for step in range(1, n - pos):
        idx = pos + step
        to_v = tos[idx]
        if to_v <= 0.0 or np.isnan(to_v):
            # 停牌棒：无法交易，等待复牌
            continue

        tradable_step += 1
        last_tradable_idx = idx
        op, hi, lo, cl, pc, dt_px, zt_px = opens[idx], highs[idx], lows[idx], closes[idx], pre_cs[idx], dt_pxs[idx], zt_pxs[idx]

        # 检查是否全天一字跌停锁死
        if is_locked_limit_down_bar(op, hi, lo, cl, pc, bool(is_yz_dts[idx])):
            # 锁死无法卖出，顺延到下一交易日
            continue

        adj_i = adjfs[idx]
        op_adj = op * adj_i
        hi_adj = hi * adj_i
        cl_adj = cl * adj_i

        # 1. 快速割肉 / E1 / 撬板失败断腕: 开盘秒走
        if is_cut_fast or (tradable_step > max_hold):
            return dts[idx], float(op_adj / buy_adj - 1.0 - FEE_RATE), step, True

        # 2. 地天板连板处理 (E6 且 Day 0 封涨停)
        if exit_mode == "E6_cut_reseal_tp7_h3" and day0_is_zt:
            # 如果次日是一字涨停，继续享受连板持有
            if op >= zt_px - 0.011 and (bool(is_zts[idx]) or cl >= zt_px - 0.011) and tradable_step < max_hold:
                continue

        # 3. 正常目标止盈判定 (tp_pct)
        if tp_pct > 0.0:
            tp_target = buy_adj * (1.0 + tp_pct)
            # 开盘直接高开达标 -> 开盘价止盈
            if op_adj >= tp_target:
                return dts[idx], float(op_adj / buy_adj - 1.0 - FEE_RATE), step, True
            # 盘中最高价触及止盈 -> 严格按 tp_pct 止盈
            if hi_adj >= tp_target:
                return dts[idx], float(tp_pct - FEE_RATE), step, False

        # 4. 到达最大持仓日 max_hold
        if tradable_step == max_hold:
            # 收盘出局，但需检查收盘是否封死跌停
            if is_close_limit_down(cl, pc, dt_px, bool(is_dts[idx])):
                # 收盘跌停锁死卖不掉，顺延至次日开盘
                continue
            return dts[idx], float(cl_adj / buy_adj - 1.0 - FEE_RATE), step, False

    # 兜底：若退市前停牌未再复牌，计入 -70% 真实退市清算损失
    if last_tradable_idx < 0 and dts[pos] < "2026-10-20":
        return dts[-1], float(-0.70 - FEE_RATE), n - 1 - pos, False
    end_i = last_tradable_idx if last_tradable_idx >= 0 else (n - 1)
    ret = float((closes[end_i] * adjfs[end_i]) / buy_adj - 1.0 - FEE_RATE)
    if dts[end_i] < "2026-10-20" and is_locked_limit_down_bar(
        opens[end_i], highs[end_i], lows[end_i], closes[end_i], pre_cs[end_i], bool(is_yz_dts[end_i])
    ):
        ret = min(ret, float(-0.70 - FEE_RATE))
    return dts[end_i], ret, max(1, end_i - pos), False


def precompute_all_entries_and_exits(df: pd.DataFrame, cb: dict) -> dict:
    """
    预计算 cand_pry_limitdown 中 6 种买法 (B1~B5) 与 6 种卖法 (E1~E6) 的全矩阵。
    """
    N = len(df)
    BUY_MODES = ["B1_auc_deep_open", "B2_pry_2tick", "B3_pry_lift_15pct", "B4_pry_lift_25pct", "B5_open_or_lift15"]
    EXIT_MODES = ["E1_next_open", "E2_tp5_h2", "E3_tp7_h2", "E4_tp7_h3", "E5_tp7_h5", "E6_cut_reseal_tp7_h3"]

    pre = {
        bm: {
            "valid": np.zeros(N, dtype=bool),
            "buy_at_open": np.zeros(N, dtype=bool),
            "buy_px": np.zeros(N, dtype=float),
            "day0_ret": np.zeros(N, dtype=float),
            "day0_reseal": np.zeros(N, dtype=bool),
            "day0_zt": np.zeros(N, dtype=bool),
            "exits": {
                em: {
                    "exit_date": np.empty(N, dtype=object),
                    "net_ret": np.zeros(N, dtype=float),
                    "hold_bars": np.zeros(N, dtype=int),
                    "exit_at_open": np.zeros(N, dtype=bool),
                }
                for em in EXIT_MODES
            },
        }
        for bm in BUY_MODES
    }

    codes = df["code"].values
    buy_dates = df["buy_date"].values
    open_pcts = df["open_pct"].values

    for i in range(N):
        c = codes[i]
        bd = buy_dates[i]
        b = cb[c]
        pos = b["date_to_pos"][bd]
        op = float(b["open"][pos])
        hi = float(b["high"][pos])
        cl = float(b["close"][pos])
        dt_px = float(b["dt_px"][pos])
        zt_px = float(b["zt_px"][pos])
        to_v = float(b["to"][pos])

        if to_v <= 0.0 or np.isnan(to_v):
            continue

        op_pct = open_pcts[i]

        # 判定买点触发
        # B1: 竞价深水未封死 -9.5% ~ -4.0%
        can_b1 = (-0.095 <= op_pct <= -0.040) and (op > dt_px + 0.011)
        # B2: 旧版跌停开盘且 high > dt_px + 0.02
        can_b2 = (op <= dt_px + 0.011) and (hi > dt_px + 0.02)
        # B3: 跌停开盘且向上拉起 1.5%
        trig15 = round(dt_px * 1.015, 2)
        if trig15 <= dt_px:
            trig15 = dt_px + 0.01
        can_b3 = (op <= dt_px + 0.011) and (hi >= trig15)
        # B4: 跌停开盘且向上拉起 2.5%
        trig25 = round(dt_px * 1.025, 2)
        if trig25 <= dt_px:
            trig25 = dt_px + 0.02
        can_b4 = (op <= dt_px + 0.011) and (hi >= trig25)
        # B5: B1 或 B3
        can_b5 = can_b1 or can_b3

        bm_specs = {}
        if can_b1:
            bm_specs["B1_auc_deep_open"] = (op, True)
        if can_b2:
            bm_specs["B2_pry_2tick"] = (round(dt_px + 0.02, 2), False)
        if can_b3:
            bm_specs["B3_pry_lift_15pct"] = (trig15, False)
        if can_b4:
            bm_specs["B4_pry_lift_25pct"] = (trig25, False)
        if can_b5:
            if can_b1:
                bm_specs["B5_open_or_lift15"] = (op, True)
            else:
                bm_specs["B5_open_or_lift15"] = (trig15, False)

        for bm, (buy_p, buy_at_op) in bm_specs.items():
            pre[bm]["valid"][i] = True
            pre[bm]["buy_at_open"][i] = buy_at_op
            pre[bm]["buy_px"][i] = buy_p
            pre[bm]["day0_ret"][i] = float(cl / buy_p - 1.0)
            pre[bm]["day0_reseal"][i] = bool(cl <= dt_px + 0.011 or cl < buy_p * 0.985)
            pre[bm]["day0_zt"][i] = bool(cl >= zt_px - 0.011)

            # 仿真 6 种卖法
            for em in EXIT_MODES:
                ed, nr, hb, eao = sim_single_exit(b, pos, buy_p, em)
                pre[bm]["exits"][em]["exit_date"][i] = ed
                pre[bm]["exits"][em]["net_ret"][i] = nr
                pre[bm]["exits"][em]["hold_bars"][i] = hb
                pre[bm]["exits"][em]["exit_at_open"][i] = eao

    return pre


def build_trades_dataframe(df: pd.DataFrame, pre: dict, mask: np.ndarray, buy_mode: str, exit_mode: str, priority_series: np.ndarray = None) -> pd.DataFrame:
    """构建标准交易流水表"""
    valid_mask = mask & pre[buy_mode]["valid"]
    if not np.any(valid_mask):
        return pd.DataFrame()

    sub_df = df[valid_mask].copy()
    sub_indices = np.where(valid_mask)[0]

    sub_df["buy_px"] = pre[buy_mode]["buy_px"][sub_indices]
    sub_df["buy_at_open"] = pre[buy_mode]["buy_at_open"][sub_indices]
    sub_df["day0_ret"] = pre[buy_mode]["day0_ret"][sub_indices]
    sub_df["day0_reseal"] = pre[buy_mode]["day0_reseal"][sub_indices]
    sub_df["day0_zt"] = pre[buy_mode]["day0_zt"][sub_indices]

    ex = pre[buy_mode]["exits"][exit_mode]
    sub_df["exit_date"] = ex["exit_date"][sub_indices]
    sub_df["net_ret"] = ex["net_ret"][sub_indices]
    sub_df["hold_bars"] = ex["hold_bars"][sub_indices]
    sub_df["exit_at_open"] = ex["exit_at_open"][sub_indices]

    if priority_series is not None:
        sub_df["priority_score"] = priority_series[sub_indices]
    else:
        sub_df["priority_score"] = 0.0

    return sub_df


def sim_single_slot(trades_df: pd.DataFrame) -> tuple:
    """单仓严格时序轮动模拟 (严禁资金瞬移)"""
    if trades_df.empty:
        return [], 1.0, 0.0, 0
    df = trades_df.copy()
    if "priority_score" not in df.columns:
        df["priority_score"] = 0.0
    srt = df.sort_values(["buy_date", "priority_score"], ascending=[True, False])
    taken = []
    free_after = ""
    exit_at_open_prev = True
    nav, pk, mdd = 1.0, 1.0, 0.0
    hold_days = 0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        can_buy = (free_after == "") or (bd > free_after) or (bd == free_after and exit_at_open_prev and (not getattr(r, "buy_at_open", True)))
        if not can_buy:
            continue
        taken.append(r)
        free_after = str(r.exit_date)[:10]
        exit_at_open_prev = bool(getattr(r, "exit_at_open", False))
        nav *= (1.0 + float(r.net_ret))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
        hold_days += max(1, int(getattr(r, "hold_bars", 1)))
    return taken, float(nav), float(mdd), int(hold_days)


def sim_two_half_slots(trades_df: pd.DataFrame) -> tuple:
    """双半仓严格轮动模拟 (每个半仓 0.5 起步)"""
    if trades_df.empty:
        return 1.0, 0.0, 0
    df = trades_df.copy()
    if "priority_score" not in df.columns:
        df["priority_score"] = 0.0
    srt = df.sort_values(["buy_date", "priority_score"], ascending=[True, False])
    slot_cap = [0.5, 0.5]
    slot_free = ["", ""]
    pk, mdd, cnt = 1.0, 0.0, 0
    used_day_codes = set()
    for r in srt.itertuples(index=False):
        c_val = getattr(r, "code", getattr(r, "c6", ""))
        bd, c = str(r.buy_date)[:10], str(c_val)
        if (bd, c) in used_day_codes:
            continue
        chosen = -1
        for s in (0, 1):
            if slot_free[s] == "" or bd > slot_free[s]:
                chosen = s
                break
        if chosen < 0:
            continue
        used_day_codes.add((bd, c))
        slot_free[chosen] = str(r.exit_date)[:10]
        slot_cap[chosen] *= (1.0 + float(r.net_ret))
        tot = slot_cap[0] + slot_cap[1]
        pk = max(pk, tot)
        mdd = max(mdd, (pk - tot) / pk)
        cnt += 1
    return float(slot_cap[0] + slot_cap[1]), float(mdd), int(cnt)


def sim_daily_eq(trades_df: pd.DataFrame) -> tuple:
    """按日等权 (消除救市日多只重叠放大幻觉)"""
    if trades_df.empty:
        return 1.0, 0.0
    by_d = trades_df.groupby("buy_date")["net_ret"].mean().sort_index()
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in by_d.values:
        nav *= (1.0 + float(r))
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
    return float(nav), float(mdd)


def eval_d15_period(trades_df: pd.DataFrame, start_dt: str, end_dt: str) -> dict:
    """评测特定时间切片内的 D15 详细指标"""
    bench = csi300_period_ret(start_dt, end_dt)
    if trades_df.empty:
        return {
            "raw_n": 0, "single_n": 0, "wr": 0.0, "payoff": 0.0, "mean_pct": 0.0,
            "single_nav": 1.0, "single_ret_pct": 0.0, "single_mdd_pct": 0.0,
            "eq_nav": 1.0, "eq_ret_pct": 0.0, "eq_mdd_pct": 0.0,
            "trimmed3_nav": 1.0, "trimmed5_nav": 1.0, "hold_days": 0,
            "csi300_pct": round(bench * 100.0, 2),
            "single_excess_pct": round(-bench * 100.0, 2),
            "eq_excess_pct": round(-bench * 100.0, 2),
        }
    sub = trades_df[(trades_df["buy_date"] >= start_dt) & (trades_df["buy_date"] <= end_dt)]
    if sub.empty:
        return {
            "raw_n": 0, "single_n": 0, "wr": 0.0, "payoff": 0.0, "mean_pct": 0.0,
            "single_nav": 1.0, "single_ret_pct": 0.0, "single_mdd_pct": 0.0,
            "eq_nav": 1.0, "eq_ret_pct": 0.0, "eq_mdd_pct": 0.0,
            "trimmed3_nav": 1.0, "trimmed5_nav": 1.0, "hold_days": 0,
            "csi300_pct": round(bench * 100.0, 2),
            "single_excess_pct": round(-bench * 100.0, 2),
            "eq_excess_pct": round(-bench * 100.0, 2),
        }

    taken, s_nav, s_mdd, h_days = sim_single_slot(sub)
    eq_nav, eq_mdd = sim_daily_eq(sub)
    rets = np.array([float(t.net_ret) for t in taken], dtype=float)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0) if len(rets) else 0.0
    po = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.0 if len(wins) > 0 else 0.0)
    mean_p = float(rets.mean() * 100.0) if len(rets) else 0.0

    # 去前3与去前5极值净值
    if len(rets) > 3:
        trim3 = float(np.prod(1.0 + np.sort(rets)[:-3]))
    else:
        trim3 = 1.0

    if len(rets) > 5:
        trim5 = float(np.prod(1.0 + np.sort(rets)[:-5]))
    else:
        trim5 = 1.0

    return {
        "raw_n": int(len(sub)),
        "single_n": int(len(rets)),
        "wr": round(wr, 2),
        "payoff": round(po, 2),
        "mean_pct": round(mean_p, 2),
        "single_nav": round(s_nav, 3),
        "single_ret_pct": round((s_nav - 1.0) * 100.0, 2),
        "single_mdd_pct": round(s_mdd * 100.0, 2),
        "eq_nav": round(eq_nav, 3),
        "eq_ret_pct": round((eq_nav - 1.0) * 100.0, 2),
        "eq_mdd_pct": round(eq_mdd * 100.0, 2),
        "trimmed3_nav": round(trim3, 3),
        "trimmed5_nav": round(trim5, 3),
        "hold_days": int(h_days),
        "csi300_pct": round(bench * 100.0, 2),
        "single_excess_pct": round(((s_nav - 1.0) - bench) * 100.0, 2),
        "eq_excess_pct": round(((eq_nav - 1.0) - bench) * 100.0, 2),
    }


def eval_d15_all(trades_df: pd.DataFrame) -> dict:
    """输出完整的 D15 四必核全指标字典"""
    if trades_df.empty:
        return {}

    sub_5y = trades_df[(trades_df["buy_date"] >= "2022-01-04") & (trades_df["buy_date"] <= "2026-11-10")]
    h_nav, h_mdd, h_n = sim_two_half_slots(sub_5y)

    res = {
        "full_5y": eval_d15_period(trades_df, "2022-01-04", "2026-11-10"),
        "recent_3y": eval_d15_period(trades_df, "2023-11-10", "2026-11-10"),
        "recent": eval_d15_period(trades_df, "2026-07-01", "2026-11-10"),
        "is_2022_2024": eval_d15_period(trades_df, "2022-01-04", "2024-12-31"),
        "oos_2025_2026": eval_d15_period(trades_df, "2025-01-01", "2026-11-10"),
        "half2_5y": {"nav": round(h_nav, 3), "mdd_pct": round(h_mdd * 100.0, 2), "n": int(h_n)},
        "annual": {},
    }

    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        s_d = f"{yr}-01-01"
        e_d = f"{yr}-12-31" if yr != "2026" else "2026-11-10"
        res["annual"][yr] = eval_d15_period(trades_df, s_d, e_d)

    return res
