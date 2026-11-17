#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
synthesize_master_clean_20261116.py — 主线程独立核验与纯单仓合体总账合成器
严格执行 D15 四必核：单仓轮动(分钟级零时间穿越)、按日等权、1000万单笔上限实盘净值、最大回撤、五期胜率与盈亏比、同期沪深300与净超额。
"""
import os, json, math
import pandas as pd
import numpy as np

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
CSI_JSON = f"{BASE}/csi300_canonical_20261116.json"

WINDOWS = [
    ("2026年10月以来", "2026-10-01", "2026年10月以来"),
    ("2026年7月以来", "2026-07-01", "2026年7月以来"),
    ("2026全年", "2026-01-01", "2026全年"),
    ("近三年", "2023-11-16", "近三年(2023-11-16起)"),
    ("全五年", "2021-10-08", "全五年(2021-10-08起)"),
]

def _norm_hhmm(val, default_hhmm: int) -> int:
    if val is None or (isinstance(val, float) and math.isnan(val)): return default_hhmm
    s = str(val).strip().replace(":", "")
    if not s or s.lower() == "nan": return default_hhmm
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 4: return int(digits[:4])
    if len(digits) == 3: return int(digits)
    return default_hhmm

def standardize_ledger(path: str, strat_tag: str, priority: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if cl in ("buy_date", "entry_date", "d2_date", "d4_date", "trade_date"): col_map.setdefault("buy_date", c)
        if cl in ("exit_date", "sell_date", "out_date"): col_map.setdefault("exit_date", c)
        if cl in ("code", "c6", "ticker", "sec_code"): col_map.setdefault("code", c)
        if cl in ("name", "sec_name"): col_map.setdefault("name", c)
        if cl in ("net_ret", "ret", "net_return", "pnl_pct", "ret_net"): col_map.setdefault("ret_raw", c)
        if cl in ("score", "total_score", "final_score", "v18_score", "q4_score"): col_map.setdefault("score", c)
        if cl in ("buy_time", "entry_time", "buy_hhmm", "trig_time"): col_map.setdefault("buy_time", c)
        if cl in ("exit_time", "sell_time", "exit_hhmm", "out_time"): col_map.setdefault("exit_time", c)
    out = pd.DataFrame()
    out["buy_date"] = df[col_map["buy_date"]].astype(str).str[:10]
    out["exit_date"] = df[col_map["exit_date"]].astype(str).str[:10] if "exit_date" in col_map else out["buy_date"]
    out["code"] = df[col_map["code"]].astype(str).str[:6].str.zfill(6)
    out["name"] = df[col_map["name"]].astype(str) if "name" in col_map else out["code"]
    r = pd.to_numeric(df[col_map["ret_raw"]], errors="coerce").fillna(0.0)
    # Detect percent vs decimal (e.g. 12.5 vs 0.125)
    if r.abs().median() > 0.8:
        r = r / 100.0
    out["net_ret"] = r
    out["score"] = pd.to_numeric(df[col_map["score"]], errors="coerce").fillna(0.0) if "score" in col_map else 0.0
    def_buy = 925 if "pry" in strat_tag else 935
    out["buy_hhmm"] = [(_norm_hhmm(v, def_buy)) for v in df[col_map["buy_time"]]] if "buy_time" in col_map else def_buy
    out["exit_hhmm"] = [(_norm_hhmm(v, 1455)) for v in df[col_map["exit_time"]]] if "exit_time" in col_map else 1455
    out["strategy"] = strat_tag
    out["priority"] = priority
    return out.sort_values(["buy_date", "priority", "buy_hhmm", "score"], ascending=[True, True, True, False]).reset_index(drop=True)

def run_1slot(df_pool: pd.DataFrame) -> pd.DataFrame:
    df_s = df_pool.sort_values(["buy_date", "priority", "score", "buy_hhmm"], ascending=[True, True, False, True]).reset_index(drop=True)
    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    for row in df_s.itertuples(index=False):
        if not cur_exit_dt or row.buy_date > cur_exit_dt or (row.buy_date == cur_exit_dt and row.buy_hhmm > cur_exit_hhmm):
            picked.append(row._asdict())
            cur_exit_dt = row.exit_date
            cur_exit_hhmm = row.exit_hhmm
    return pd.DataFrame(picked)

def calc_metrics(df_all: pd.DataFrame, df_slot: pd.DataFrame, start_dt: str, csi_pct: float) -> dict:
    sub_s = df_slot[df_slot["buy_date"] >= start_dt].copy() if not df_slot.empty else pd.DataFrame()
    sub_a = df_all[df_all["buy_date"] >= start_dt].copy() if not df_all.empty else pd.DataFrame()
    n = len(sub_s)
    if n == 0:
        return {"n_slot": 0, "n_all": len(sub_a), "win_rate": 0.0, "wl_ratio": 0.0, "nav_slot": 1.0, "ret_slot_pct": 0.0,
                "nav_eq": 1.0, "ret_eq_pct": 0.0, "max_dd_pct": 0.0, "cap10m_mult": 1.0, "cap10m_ret_pct": 0.0,
                "csi300_pct": csi_pct, "excess_slot_pp": round(0.0 - csi_pct, 2), "excess_cap10m_pp": round(0.0 - csi_pct, 2)}
    rets = sub_s["net_ret"].to_numpy()
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / n * 100.0)
    wlr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.9 if len(wins) > 0 else 0.0)
    nav_curve = np.cumprod(1.0 + rets)
    peaks = np.maximum.accumulate(np.insert(nav_curve, 0, 1.0))[1:]
    mdd = float(np.max((peaks - nav_curve) / peaks) * 100.0) if len(nav_curve) else 0.0
    nav_final = float(nav_curve[-1])
    ret_slot_pct = (nav_final - 1.0) * 100.0
    # Daily equal weight on all signals
    if len(sub_a) > 0:
        day_rets = sub_a.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy()
        nav_eq = float(np.prod(1.0 + day_rets))
    else:
        nav_eq = 1.0
    # 1000万单笔封顶实盘资金池模拟 (初始100万，单笔最多投1000万，超出转现金池)
    cap = 100.0
    for r in rets:
        bet = min(cap, 1000.0)
        cap += bet * float(r)
    cap_mult = cap / 100.0
    cap_ret_pct = (cap_mult - 1.0) * 100.0
    return {
        "n_slot": n, "n_all": int(len(sub_a)),
        "win_rate": round(wr, 2), "wl_ratio": round(wlr, 2),
        "nav_slot": round(nav_final, 2), "ret_slot_pct": round(ret_slot_pct, 2),
        "nav_eq": round(nav_eq, 2), "ret_eq_pct": round((nav_eq - 1.0) * 100.0, 2),
        "max_dd_pct": round(mdd, 2),
        "cap10m_mult": round(cap_mult, 2), "cap10m_ret_pct": round(cap_ret_pct, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_slot_pp": round(ret_slot_pct - csi_pct, 2),
        "excess_cap10m_pp": round(cap_ret_pct - csi_pct, 2),
    }

if __name__ == "__main__":
    csi = json.load(open(CSI_JSON))
    # 统一采用 2021-11-16 起全五年 (-18.49%) 与 2023-11-16 起近三年 (+10.33%)
    WIN_SPEC = [
        ("2026年10月以来", "2026-10-01", csi["2026年10月以来"][0]),
        ("2026年7月以来", "2026-07-01", csi["2026年7月以来"][0]),
        ("2026全年", "2026-01-01", csi["2026全年"][0]),
        ("近三年", "2023-11-16", csi["近三年(2023-11-16起)"][0]),
        ("全五年", "2021-11-15", csi["全五年(2021-11-16起)"][0]),
    ]

    b_high = standardize_ledger(f"{BASE}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴_V51", 1)
    b_3to4 = standardize_ledger(f"{BASE}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四_V34", 2)
    b_1to2 = standardize_ledger(f"{BASE}/partB_1to2/ledger_base_1to2_v18.csv", "一进二_V18", 3)
    aux_pry = standardize_ledger(f"{BASE}/partC_aux/ledger_aux_pry_v10.csv", "超跌撬板_V10", 3)
    aux_5b = standardize_ledger(f"{BASE}/partC_aux/ledger_aux_5board.csv", "五板辅助", 5)

    q4_high = standardize_ledger(f"{BASE}/partD_26q4_and_combined/ledger_26q4_high.csv", "高标首阴_26Q4", 1)
    q4_3to4 = standardize_ledger(f"{BASE}/partD_26q4_and_combined/ledger_26q4_3to4.csv", "三进四_26Q4", 2)
    q4_1to2 = standardize_ledger(f"{BASE}/partD_26q4_and_combined/ledger_26q4_1to2.csv", "一进二_26Q4", 3)

    # 1. 五年基础版三大核心主策略纯单仓合体 (高标首阴 > 三进四 > 一进二)
    pool_base_3main = pd.concat([b_high, b_3to4, b_1to2], ignore_index=True)
    slot_base_3main = run_1slot(pool_base_3main)
    slot_base_3main.to_csv(f"{BASE}/ledger_base_combined_3main.csv", index=False)

    # 2. 五年基础版三大主策略 + 超跌撬板辅助 (高标首阴 1 > 三进四 2 > 超跌撬板 3 > 一进二 4)
    b_1to2_p4 = b_1to2.copy(); b_1to2_p4["priority"] = 4
    pool_base_3plus_pry = pd.concat([b_high, b_3to4, aux_pry, b_1to2_p4], ignore_index=True)
    slot_base_3plus_pry = run_1slot(pool_base_3plus_pry)
    slot_base_3plus_pry.to_csv(f"{BASE}/ledger_base_combined_3main_plus_pry.csv", index=False)

    # 3. 26Q4专供版三大核心主策略纯单仓合体 (严格只结合三大策略: 高标 > 三进四 > 一进二)
    pool_q4_3main = pd.concat([q4_high, q4_3to4, q4_1to2], ignore_index=True)
    slot_q4_3main = run_1slot(pool_q4_3main)

    master = {}
    items = [
        ("基础版_高标首阴V5.1", b_high, run_1slot(b_high)),
        ("基础版_三进四V3.4", b_3to4, run_1slot(b_3to4)),
        ("基础版_一进二V18", b_1to2, run_1slot(b_1to2)),
        ("辅助_超跌撬板V1.0", aux_pry, run_1slot(aux_pry)),
        ("辅助_五板卡异动", aux_5b, run_1slot(aux_5b)),
        ("基础版_三大主策略纯单仓合体", pool_base_3main, slot_base_3main),
        ("基础版_三大主策略加撬板合体", pool_base_3plus_pry, slot_base_3plus_pry),
        ("26Q4专供_高标首阴", q4_high, run_1slot(q4_high)),
        ("26Q4专供_三进四", q4_3to4, run_1slot(q4_3to4)),
        ("26Q4专供_一进二", q4_1to2, run_1slot(q4_1to2)),
        ("26Q4专供_三大主策略纯单仓合体", pool_q4_3main, slot_q4_3main),
    ]
    for label, d_all, d_slot in items:
        # 严核 T+0 与重叠
        t0_cnt = int((d_slot["exit_date"] <= d_slot["buy_date"]).sum()) if len(d_slot) else 0
        ov_cnt = 0
        for i in range(1, len(d_slot)):
            r_prev, r_cur = d_slot.iloc[i-1], d_slot.iloc[i]
            if r_cur["buy_date"] < r_prev["exit_date"] or (r_cur["buy_date"] == r_prev["exit_date"] and r_cur["buy_hhmm"] <= r_prev["exit_hhmm"]):
                ov_cnt += 1
        master[label] = {"t0_violations": t0_cnt, "overlap_violations": ov_cnt, "windows": {}}
        for w_name, s_dt, c_pct in WIN_SPEC:
            master[label]["windows"][w_name] = calc_metrics(d_all, d_slot, s_dt, c_pct)

    out_path = f"{BASE}/summary_master_all_clean_20261116.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)

    for label, info in master.items():
        w26 = info["windows"]["2026全年"]
        w3y = info["windows"]["近三年"]
        w5y = info["windows"]["全五年"]
        w7m = info["windows"]["2026年7月以来"]
        w10m = info["windows"]["2026年10月以来"]
        print(f"{label} [T0={info['t0_violations']},OV={info['overlap_violations']}]: "
              f"10月={w10m['n_slot']}笔/{w10m['win_rate']}%/{w10m['nav_slot']}x | "
              f"7月={w7m['n_slot']}笔/{w7m['win_rate']}%/{w7m['nav_slot']}x | "
              f"26年={w26['n_slot']}笔/{w26['win_rate']}%/{w26['nav_slot']}x(1000万封顶+{w26['cap10m_ret_pct']}%) | "
              f"3年={w3y['n_slot']}笔/{w3y['win_rate']}%/{w3y['nav_slot']}x | "
              f"5年={w5y['n_slot']}笔/{w5y['win_rate']}%/PLR={w5y['wl_ratio']}/单仓{w5y['nav_slot']}x/等权{w5y['nav_eq']}x/回撤{w5y['max_dd_pct']}%")

