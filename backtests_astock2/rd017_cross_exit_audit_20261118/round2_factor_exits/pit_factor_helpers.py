#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
pit_factor_helpers.py — 第二轮动态因子查询与 D15 统一评测工具
严格遵守：所有时间戳查询使用 bisect < cutoff_ts，零未来函数！
"""
import bisect, json, re
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
IDX_PATH = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
IDX_CACHE = json.load(open(IDX_PATH, encoding="utf-8"))
SH300 = IDX_CACHE["sh000300"]
SH_MAP = IDX_CACHE["sh000002"]
SZ_MAP = IDX_CACHE["sz399107"]
CSI_DTS = sorted(SH300.keys())

TECH_RE = re.compile(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)")
NON_THEME = {"其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"}
EVENT_BASKET = {"并购重组", "股权转让", "资产注入", "国企改革", "央企改革", "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购", "增持", "次新股", "高送转", "参股新股"}
CSRC_OUTSIDER = {
    "A01", "A02", "A03", "A04", "A05", "D44", "D45", "D46", "E47", "E48", "E49", "E50",
    "F51", "F52", "G53", "G54", "G55", "G56", "G58", "G59", "H61", "H62", "K70",
    "L72", "N77", "N78", "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22",
}


def csi_ret_pct(s_dt: str, e_dt: str) -> float:
    prevs = [d for d in CSI_DTS if d < s_dt]
    posts = [d for d in CSI_DTS if d <= e_dt]
    p0 = SH300[prevs[-1]] if prevs else SH300[CSI_DTS[0]]
    p1 = SH300[posts[-1]]
    return round((p1 / p0 - 1.0) * 100.0, 2)


def has_ts_in_window(ts_map: dict, key: str, start_ts: str, end_ts: str) -> bool:
    arr = ts_map.get(key)
    if arr is None or len(arr) == 0:
        return False
    lo = int(np.searchsorted(arr, start_ts, side="left"))
    hi = int(np.searchsorted(arr, end_ts, side="left"))
    return hi > lo


def count_ts_in_window(ts_map: dict, key: str, start_ts: str, end_ts: str) -> int:
    arr = ts_map.get(key)
    if arr is None or len(arr) == 0:
        return 0
    lo = int(np.searchsorted(arr, start_ts, side="left"))
    hi = int(np.searchsorted(arr, end_ts, side="left"))
    return max(0, hi - lo)


def ex_reg_cnt_5d(env: dict, c6: str, prev_dt: str, cut_ts: str, days_back_dt: str) -> int:
    ex_k = "SH" if c6.startswith("60") else "SZ"
    evs = env["ex_reg_events"].get(ex_k, [])
    lo = bisect.bisect_left(evs, (f"{days_back_dt} 00:00:00", ""))
    hi = bisect.bisect_left(evs, (cut_ts, ""))
    stocks = {evs[i][1] for i in range(lo, hi)}
    return len(stocks)


def get_peers_0925(env: dict, c6: str, prev_dt: str, curr_dt: str) -> tuple[float, int, str]:
    """返回 (同题材队友在 curr_dt 09:25 竞价涨跌幅均值, 队友竞价/昨日跌停数, 主板板块名)"""
    sp = env["stock_plate_map"].get((prev_dt, c6))
    if not sp:
        return 0.0, 0, "其他"
    plate = sp[0]
    peers = [x for x in env["plate_stocks_map"].get((prev_dt, plate), []) if x != c6]
    if not peers:
        return 0.0, 0, plate
    ops = []
    dt_cnt = 0
    for p in peers:
        op = env["day_o_pct"].get((curr_dt, p))
        if op is not None:
            ops.append(op)
            if op <= -0.09:
                dt_cnt += 1
    avg_op = float(np.mean(ops)) if ops else 0.0
    return avg_op, dt_cnt, plate


def get_csrc_ind(env: dict, c6: str, dt: str) -> str:
    ivs = env["csrc_by_c6"].get(c6)
    if not ivs:
        return "UNK"
    for s0, e0, ind in ivs:
        if s0 <= dt <= e0:
            return ind
    return ivs[0][2] if dt < ivs[0][0] else ivs[-1][2]


def is_fake_theme_1to2(env: dict, c6: str, dt: str, has_notice_hard: bool = False) -> bool:
    sp = env["stock_plate_map"].get((dt, c6))
    if not sp:
        return True
    plate, _, _, r_sh = sp
    if plate in NON_THEME or plate in EVENT_BASKET:
        return True
    txt = f"{plate} {r_sh}"
    if TECH_RE.search(txt):
        cs = get_csrc_ind(env, c6, dt)
        if cs in CSRC_OUTSIDER and (not has_notice_hard):
            return True
    return False


def calc_arr_metrics(rr: np.ndarray, csi_pct: float) -> dict:
    n = len(rr)
    if n == 0:
        return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav": 1.0, "ret_pct": 0.0,
                "mdd_pct": 0.0, "trim3_nav": 1.0, "trim5_nav": 1.0, "csi300_pct": csi_pct, "excess_pp": round(-csi_pct, 2)}
    w, ls = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean() * 100.0)
    plr = float(w.mean() / abs(ls.mean())) if (len(w) and len(ls) and ls.mean() < 0) else (99.0 if len(w) else 0.0)
    nc = np.cumprod(1.0 + rr)
    pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
    mdd = float(np.max((pk - nc) / pk) * 100.0)
    sr = np.sort(rr)
    return {
        "n": int(n), "wr_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_pct": round(float(rr.mean() * 100.0), 2),
        "nav": round(float(nc[-1]), 4), "ret_pct": round((float(nc[-1]) - 1.0) * 100.0, 2),
        "mdd_pct": round(mdd, 2),
        "trim3_nav": round(float(np.prod(1.0 + sr[:-3])) if n > 3 else 1.0, 4),
        "trim5_nav": round(float(np.prod(1.0 + sr[:-5])) if n > 5 else 1.0, 4),
        "csi300_pct": csi_pct, "excess_pp": round((float(nc[-1]) - 1.0) * 100.0 - csi_pct, 2),
    }


def univariate_summary(df_is: pd.DataFrame, mask_col: str, base_ret_col: str, alt_ret_col: str) -> dict:
    sub = df_is[df_is[mask_col].astype(bool)]
    n_trig = int(len(sub))
    if n_trig == 0:
        return {"factor": mask_col, "n_trig": 0, "base_mean_pct": 0.0, "alt_mean_pct": 0.0, "delta_bps": 0.0, "win_improve_cnt": 0}
    b = sub[base_ret_col].to_numpy(dtype=float)
    a = sub[alt_ret_col].to_numpy(dtype=float)
    return {
        "factor": mask_col,
        "n_trig": n_trig,
        "base_mean_pct": round(float(b.mean() * 100.0), 2),
        "alt_mean_pct": round(float(a.mean() * 100.0), 2),
        "delta_bps": round(float((a.mean() - b.mean()) * 10000.0), 1),
        "improved_trades": int(np.sum(a > b + 1e-6)),
        "hurt_trades": int(np.sum(a < b - 1e-6)),
    }
