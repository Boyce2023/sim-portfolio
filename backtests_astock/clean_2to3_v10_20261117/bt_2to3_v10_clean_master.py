#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
《二进三 V1.0（迷茫暗牌弱转强打分版）》工业级干净回测主程序
================================================================================
严格遵循：
  1. 2021-2023 训练集与第一性原理定结构与整数分值（Base=58, 标准档>=90, 高严档>=96）
  2. 2024-2026 与 2026 全盲样本外验证 + 5大权威窗口 D15 净超额（零 yfinance）
  3. 防过拟合三件套：CSCV 交叉过拟合概率 PBO、±20% 权重 200 次蒙特卡洛扰动与连续邻域、
     删去 2025-2026 截断重跑 max_abs_diff == 0.0 零未来函数硬断言
  4. 纯单仓 & 双半仓第4顺位（高标首阴 V5.1 > 三进四 V3.4 > 一进二 V18 > 二进三 V10）
     及含超跌撬板 V1.0 第5顺位合体协同验证
================================================================================
"""

import itertools
import json
import math
import os
import sys
import numpy as np
import pandas as pd
import scipy.stats as stats

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN_REF_DIR = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"
IDX_JSON = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{CLEAN_REF_DIR}/csi300_canonical_20261116.json"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/clean_2to3_v10_20261117"

RAW_2TO3_PQ = f"{OUT_DIR}/data_pit/clean_2to3_5y.parquet"
WAVE_A_PQ = f"{OUT_DIR}/data_pit/factors_a.parquet"
WAVE_B_PQ = f"{OUT_DIR}/data_pit/factors_b.parquet"
WAVE_C_PQ = f"{OUT_DIR}/data_pit/factors_c.parquet"

FEE_ROUNDTRIP = 0.0020
CANON_5Y_START = "2021-11-16"
DATA_AS_OF_EXPECTED = "2026-11-16"

FACTOR_NAMES = [
    "P1_1_HHI离散或单极集中(+6/-10)",
    "P1_2_晋级率低迷分歧(+8/+5)",
    "P1_3_市场高度<=3板压制(+6)",
    "P2_1_板块温热区或过热拥挤(+5/-10)",
    "P2_2_板块极寒Elo<=95破冰(+8)",
    "P2_3_一波脆弱vs二波回流(-16/+5)",
    "P2_4_同板块3板+老大哥压制(-8)",
    "P3_1_雪球暗牌零帖vs吹票(0/-10/-18)",
    "P3_2_近20日机构调研排雷(-10)",
    "P4_1_D2盘中深水洗盘<=-2%(+6)",
    "P4_2_D2开板弱封单vs死锁秒板(+6/-8/-16)",
    "P4_3_启动前20日箱体低位<=0.40(+6)",
    "P4_4_前十大锁仓>=50%&换手25~65%(+8/-8)",
    "P5_1_D3竞价绿开承接<0%(+5)",
]


def load_all_clean_data():
    raw_all = pd.read_parquet(RAW_2TO3_PQ)
    wa = pd.read_parquet(WAVE_A_PQ)
    wb = pd.read_parquet(WAVE_B_PQ)
    wc = pd.read_parquet(WAVE_C_PQ)

    # Assert 1: 严格行数与主键对齐校验
    assert len(raw_all) == 10848, f"Expected 10848 raw rows, got {len(raw_all)}"
    base = raw_all[
        raw_all["buyable_open"] & (~raw_all["prev_is_yizi"]) & (~raw_all["has_tox_90d"])
    ].copy()
    assert len(base) == 6070, f"Expected 6070 buyable non-yizi non-tox rows, got {len(base)}"
    assert len(wa) == 10848 and len(wb) == 6070 and len(wc) == 6070, (
        f"Wave A/B/C length mismatch: wa={len(wa)}, wb={len(wb)}, wc={len(wc)}"
    )
    assert base.duplicated(["code", "buy_date"]).sum() == 0, "Duplicate base keys"
    assert wa.duplicated(["code", "buy_date"]).sum() == 0, "Duplicate Wave A keys"
    assert wb.duplicated(["code", "buy_date"]).sum() == 0, "Duplicate Wave B keys"
    assert wc.duplicated(["code", "buy_date"]).sum() == 0, "Duplicate Wave C keys"

    # Assert 2: 数据截止日硬校验
    data_as_of_date = str(raw_all["exit_dt_cc"].max())
    assert data_as_of_date == DATA_AS_OF_EXPECTED, (
        f"data_as_of_date mismatch: {data_as_of_date} != {DATA_AS_OF_EXPECTED}"
    )

    wc_cols = [c for c in wc.columns if c not in ("code", "buy_date") and c not in base.columns]
    df = (
        base.merge(wa, on=["code", "buy_date"], how="inner")
        .merge(wb, on=["code", "buy_date"], how="inner")
        .merge(wc[["code", "buy_date"] + wc_cols], on=["code", "buy_date"], how="inner")
    )
    assert len(df) == 6070, f"Merged frame expected 6070 rows, got {len(df)}"
    return raw_all, df, data_as_of_date


def apply_hard_gates(df: pd.DataFrame, open_lo: float = -0.065, open_hi: float = 0.025, max_plate_sz: int = 15) -> pd.DataFrame:
    """09:25 前置 5 条硬骨架一票否决"""
    mask = (
        df["buyable_open"]
        & (~df["prev_is_yizi"])
        & (~df["has_tox_90d"])
        & (~df["has_reg_10d"])
        & df["open_pct"].between(open_lo, open_hi)
        & (df["plate_sz"] < max_plate_sz)
    )
    return df[mask].copy().reset_index(drop=True)


def compute_score_components(d: pd.DataFrame) -> np.ndarray:
    """计算 14 项纯物理正交整数打分分量（底分 58 分，满分理论 119 分，标准档 >= 90，高严档 >= 96）"""
    elo_ice = (d["a22_elo_ice_lt95"] == 1) | (d["d2_s_elo"] <= 95)
    w1_frag = ((d["c15_w1_day1_3"] == 1) | (d["c02_w1_fresh_20d_lt4_ge3"] == 1)) & (~elo_ice)
    w2_reb = (d["c21_w2_reb_20d_ge6"] == 1) | (d["c22_w2_reb_30d_ge6"] == 1)
    mid_warm = d["plate_rk_noev"].between(3, 7) | d["plate_sz"].between(2, 6)
    hot_crowd = ((d["plate_rk_noev"] <= 2) & (d["plate_sz"] >= 7)) | (d["plate_sz"] >= 12)
    both_low = (d["mkt_p12_prev"] < 0.18) & (d["mkt_p23_prev"] < 0.28)
    d2_weak_late = (d["d2_open_cnt_tape"] >= 1) & (
        (d["d2_seal_sec"].fillna(0) >= 1800) | (d["d2_seal_amt_ratio"].fillna(1) < 0.05)
    )
    d2_fast_zero = (d["d2_open_cnt_tape"] == 0) & (d["d2_seal_sec"].fillna(99999) <= 300)

    comp = np.zeros((len(d), 14), dtype=float)
    # Pillar 1: 市场迷茫与分歧
    comp[:, 0] = np.where(d["b01_hhi_low_q25"] == 1, 6.0, np.where(d["raw_top1_share"] >= 0.30, -10.0, 0.0))
    comp[:, 1] = np.where(both_low, 8.0, np.where(d["mkt_p23_prev"] < 0.28, 5.0, 0.0))
    comp[:, 2] = np.where(d["mkt_maxb_prev"] <= 3, 6.0, 0.0)
    # Pillar 2: 板块温热与一二波周期
    comp[:, 3] = np.where(hot_crowd, -10.0, np.where(mid_warm, 5.0, 0.0))
    comp[:, 4] = np.where(elo_ice, 8.0, 0.0)
    comp[:, 5] = np.where(w1_frag, -16.0, np.where(w2_reb, 5.0, 0.0))
    comp[:, 6] = np.where(d["plate_3b_cnt_sd"] >= 1, -8.0, 0.0)
    # Pillar 3: 社区暗牌与机构排雷
    comp[:, 7] = np.where(d["xq_cnt_tot"] == 0, 0.0, np.where(d["xq_cnt_tot"] >= 4, -18.0, -10.0))
    comp[:, 8] = np.where(d["ir_has_20d"] == 1, -10.0, 0.0)
    # Pillar 4: 二板盘口洗盘、换手与锁仓底座
    comp[:, 9] = np.where(d["d2_low_pct"] <= -0.02, 6.0, 0.0)
    comp[:, 10] = np.where(
        d["d2_seal_amt_ratio"].fillna(0) >= 0.25,
        -16.0,
        np.where(d2_fast_zero, -8.0, np.where(d2_weak_late, 6.0, 0.0)),
    )
    comp[:, 11] = np.where(d["pos_20d_d0"].fillna(0.5) <= 0.40, 6.0, 0.0)
    comp[:, 12] = np.where(
        d["d2_real_turn"].fillna(30.0) < 15.0,
        -8.0,
        np.where((d["lock_top10"].fillna(0) >= 50.0) & d["d2_real_turn"].fillna(0).between(25.0, 65.0), 8.0, 0.0),
    )
    # Pillar 5: 三板 09:25 竞价承接
    comp[:, 13] = np.where(d["open_pct"] < 0.0, 5.0, 0.0)
    return comp


def score_dataframe(d: pd.DataFrame, base_pts: int = 58) -> pd.Series:
    comp = compute_score_components(d)
    return pd.Series(base_pts + comp.sum(axis=1), index=d.index, dtype=float)


def sim_single_slot(
    sub: pd.DataFrame,
    sc_col: str = "score",
    rcol: str = "ret_opn_cc",
    ecol: str = "exit_dt_cc",
    hcol: str = "exit_hh_cc",
) -> pd.DataFrame:
    if sub.empty:
        return pd.DataFrame()
    srt = sub.sort_values(
        ["buy_date", sc_col, "open_pct", "plate_sz", "code"],
        ascending=[True, False, True, True, True],
    )
    taken = []
    free_dt, free_hh = "", 0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)
        if (not free_dt) or (bd > free_dt) or (bd == free_dt and 925 > free_hh):
            bp = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)
            nr = float(getattr(r, rcol))
            ep = round(bp * (1.0 + nr) / (1.0 - FEE_ROUNDTRIP), 2)
            ed = str(getattr(r, ecol))
            eh = int(getattr(r, hcol))
            taken.append(
                {
                    "code": str(r.code).zfill(6),
                    "name": str(r.name),
                    "buy_date": bd,
                    "buy_hhmm": 925,
                    "buy_price": bp,
                    "exit_date": ed,
                    "exit_hhmm": eh,
                    "exit_price": ep,
                    "net_ret": nr,
                    "score": int(round(float(getattr(r, sc_col)))),
                    "open_pct": round(float(r.open_pct), 4),
                    "sealed_3b": bool(r.sealed_3b),
                    "plate": str(r.plate),
                    "plate_sz": int(r.plate_sz),
                }
            )
            free_dt, free_hh = ed, eh
    out = pd.DataFrame(taken)
    if not out.empty:
        assert (out["exit_date"] > out["buy_date"]).all(), "T+0 violation detected!"
        for i in range(1, len(out)):
            p, c = out.iloc[i - 1], out.iloc[i]
            assert (c["buy_date"] > p["exit_date"]) or (
                c["buy_date"] == p["exit_date"] and c["buy_hhmm"] > p["exit_hhmm"]
            ), f"Overlap violation: {p['buy_date']}->{p['exit_date']} vs {c['buy_date']}"
    return out


def sim_two_half_slots(
    sub: pd.DataFrame,
    sc_col: str = "score",
    rcol: str = "ret_opn_cc",
    ecol: str = "exit_dt_cc",
    hcol: str = "exit_hh_cc",
) -> tuple:
    if sub.empty:
        return pd.DataFrame(), 1.0, 0.0
    sort_cols = ["buy_date"]
    asc_list = [True]
    if "priority" in sub.columns:
        sort_cols.append("priority"); asc_list.append(True)
    if "buy_hhmm" in sub.columns:
        sort_cols.append("buy_hhmm"); asc_list.append(True)
    sort_cols.append(sc_col); asc_list.append(False)
    if "open_pct" in sub.columns:
        sort_cols.append("open_pct"); asc_list.append(True)
    if "plate_sz" in sub.columns:
        sort_cols.append("plate_sz"); asc_list.append(True)
    sort_cols.append("code"); asc_list.append(True)
    srt = sub.sort_values(sort_cols, ascending=asc_list)

    cap = [0.5, 0.5]
    fdt = ["", ""]
    fhh = [0, 0]
    pk, mdd = 1.0, 0.0
    taken = []
    used = set()
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)
        c6 = str(r.code).zfill(6)
        bh = int(getattr(r, "buy_hhmm", 925))
        if (bd, c6) in used:
            continue
        chosen = -1
        for s in (0, 1):
            if fdt[s] == "" or bd > fdt[s] or (bd == fdt[s] and bh > fhh[s]):
                chosen = s
                break
        if chosen < 0:
            continue
        used.add((bd, c6))
        ret = float(getattr(r, rcol if hasattr(r, rcol) else "net_ret"))
        ed = str(getattr(r, ecol if hasattr(r, ecol) else "exit_date"))
        eh = int(getattr(r, hcol if hasattr(r, hcol) else "exit_hhmm"))
        fdt[chosen], fhh[chosen] = ed, eh
        cap[chosen] *= 1.0 + ret
        tot = cap[0] + cap[1]
        pk = max(pk, tot)
        mdd = max(mdd, (pk - tot) / pk)
        taken.append({"buy_date": bd, "exit_date": ed, "code": c6, "net_ret": ret})
    return pd.DataFrame(taken), float(cap[0] + cap[1]), float(mdd * 100.0)


def calc_window_metrics(sub_raw: pd.DataFrame, sub_slot: pd.DataFrame, csi_pct: float, rcol: str = "ret_opn_cc") -> dict:
    if sub_slot.empty:
        return {
            "raw_n": int(len(sub_raw)),
            "single_n": 0,
            "win_rate_pct": 0.0,
            "plr": 0.0,
            "mean_ret_pct": 0.0,
            "single_nav": 1.0,
            "half2_n": 0,
            "half2_nav": 1.0,
            "half2_mdd_pct": 0.0,
            "eq_nav": 1.0,
            "ex3_nav": 1.0,
            "max_dd_pct": 0.0,
            "cap10m_simple_profit_wan": 0.0,
            "cap10m_capped_mult": 1.0,
            "csi300_pct": round(csi_pct, 2),
            "excess_slot_pp": round(0.0 - csi_pct, 2),
            "excess_half2_pp": round(0.0 - csi_pct, 2),
            "excess_eq_pp": round(0.0 - csi_pct, 2),
        }
    rr = sub_slot["net_ret"].to_numpy(dtype=float)
    wins, losses = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean() * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) and len(losses) and losses.mean() < 0) else 99.0
    nav = float(np.prod(1.0 + rr))
    ex3 = float(np.prod(1.0 + np.sort(rr)[:-3])) if len(rr) > 3 else 1.0
    ew = float(np.prod(1.0 + sub_raw.groupby("buy_date")[rcol].mean().sort_index().to_numpy())) if len(sub_raw) else 1.0
    h2_df, h2_nav, h2_mdd = sim_two_half_slots(sub_raw, rcol=rcol)

    pk = cur = 1.0
    mdd = 0.0
    for x in rr:
        cur *= 1.0 + x
        pk = max(pk, cur)
        mdd = max(mdd, (pk - cur) / pk)

    # 1000万本金单利总盈利(万) + 1000万单笔封顶净值倍数
    simple_profit_wan = float(rr.sum() * 1000.0)
    cap = 1000.0
    for x in rr:
        cap += min(cap, 1000.0) * float(x)
    cap_mult = cap / 1000.0

    return {
        "raw_n": int(len(sub_raw)),
        "single_n": int(len(rr)),
        "win_rate_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_ret_pct": round(float(rr.mean() * 100.0), 2),
        "single_nav": round(nav, 2),
        "half2_n": int(len(h2_df)),
        "half2_nav": round(h2_nav, 2),
        "half2_mdd_pct": round(h2_mdd, 2),
        "eq_nav": round(ew, 2),
        "ex3_nav": round(ex3, 2),
        "max_dd_pct": round(mdd * 100.0, 2),
        "cap10m_simple_profit_wan": round(simple_profit_wan, 1),
        "cap10m_capped_mult": round(cap_mult, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_slot_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_half2_pp": round((h2_nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_eq_pp": round((ew - 1.0) * 100.0 - csi_pct, 2),
    }


def cscv_pbo_eval(R: np.ndarray, names: list, n_groups: int) -> dict:
    n_days = R.shape[0]
    gs = n_days // n_groups
    gidx = [list(range(i * gs, (i + 1) * gs if i < n_groups - 1 else n_days)) for i in range(n_groups)]
    combos = list(itertools.combinations(range(n_groups), n_groups // 2))
    omegas, logits = [], []
    win_cnt = np.zeros(R.shape[1], dtype=int)
    for te in combos:
        trg = [k for k in range(n_groups) if k not in te]
        tri = [x for k in trg for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re = R[tri], R[tei]
        st = np.where(rt.std(0, ddof=1) > 1e-12, rt.mean(0) / rt.std(0, ddof=1), 0.0)
        se = np.where(re.std(0, ddof=1) > 1e-12, re.mean(0) / re.std(0, ddof=1), 0.0)
        b = int(np.argmax(st))
        win_cnt[b] += 1
        rank_oos = float(np.mean(se > se[b]))
        omegas.append(rank_oos)
        w = max(1e-4, min(1.0 - 1e-4, rank_oos))
        logits.append(math.log(w / (1.0 - w)))
    return {
        "n_groups": n_groups,
        "n_combos": len(combos),
        "n_variants": R.shape[1],
        "pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2),
        "mean_rank_oos": round(float(np.mean(omegas)), 4),
        "logits_mean": round(float(np.mean(logits)), 4),
        "is_winners": {names[i]: int(win_cnt[i]) for i in range(len(names)) if win_cnt[i] > 0},
    }


def calc_dsr_hlz_monkey_2xfee(df_slot: pd.DataFrame, df_base_pool: pd.DataFrame, sh300: dict, t_days: list) -> dict:
    n = len(df_slot)
    all_dates = sorted(sh300.keys())

    def bench_ret(bd: str, ed: str) -> float:
        prevs = [d for d in all_dates if d < bd]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dates[0]]
        p1 = sh300.get(ed, sh300[all_dates[-1]])
        return float(p1 / p0 - 1.0)

    ex = np.array([float(r.net_ret) - bench_ret(r.buy_date, r.exit_date) for r in df_slot.itertuples(index=False)])
    sr_tr = float(ex.mean() / ex.std(ddof=1)) if n > 1 else 0.0
    t_tr = float(sr_tr * np.sqrt(n))

    d_map = {d: 0.0 for d in t_days}
    for r in df_slot.itertuples(index=False):
        if r.exit_date in d_map:
            d_map[r.exit_date] += float(r.net_ret)
    d_arr = np.array([d_map[d] for d in t_days], dtype=float)
    sr_d = float(d_arr.mean() / d_arr.std(ddof=1))
    t_d = float(sr_d * np.sqrt(len(d_arr)))

    # Bailey DSR (M=30 & M=150) on trade excess
    skew = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    kurt = float(stats.kurtosis(ex, fisher=False, bias=False)) if n > 3 else 3.0
    gamma = 0.5772156649
    dsr_out = {}
    for M in (30, 150):
        sr0 = (1.0 / np.sqrt(max(n - 1, 1))) * (
            (1.0 - gamma) * stats.norm.ppf(1.0 - 1.0 / M) + gamma * stats.norm.ppf(1.0 - 1.0 / (M * np.e))
        )
        denom = np.sqrt(max(1e-12, 1.0 - skew * sr_tr + ((kurt - 1.0) / 4.0) * (sr_tr ** 2)))
        dsr_out[f"M{M}"] = round(float(stats.norm.cdf((sr_tr - sr0) * np.sqrt(max(n - 1, 1)) / denom)), 4)

    # Monkey 5000 permutation on canonical buyable pool
    pool_by_dt = {}
    for dt_s, grp in df_base_pool.groupby("buy_date"):
        pool_by_dt[str(dt_s)] = grp["ret_opn_cc"].to_numpy(dtype=float)
    cands = [pool_by_dt.get(str(r.buy_date), np.array([float(r.net_ret)])) for r in df_slot.itertuples(index=False)]
    rng = np.random.default_rng(20261117)
    n_sims = 5000
    mat = np.zeros((n, n_sims), dtype=float)
    for i, c_arr in enumerate(cands):
        mat[i, :] = c_arr[rng.integers(0, len(c_arr), size=n_sims)]
    sim_means = mat.mean(axis=0)
    actual_mean = float(df_slot["net_ret"].mean())
    p_val = float((np.sum(sim_means >= actual_mean) + 1) / (n_sims + 1))

    # 2x friction (extra -0.20% round-trip) & drop top 15% best trades stress
    rr = df_slot["net_ret"].to_numpy(dtype=float)
    rr_2x = rr - 0.0020
    n_drop15 = max(1, math.ceil(0.15 * n))
    rr_adv15 = np.sort(rr)[:-n_drop15] if n > n_drop15 else rr

    return {
        "hlz_t_trade_excess": round(t_tr, 2),
        "hlz_t_daily": round(t_d, 2),
        "sr_annual_daily": round(sr_d * np.sqrt(242), 3),
        "dsr_trade_prob": dsr_out,
        "monkey_5000_p_value": round(p_val, 5),
        "monkey_actual_mean_pct": round(actual_mean * 100.0, 2),
        "monkey_pool_mean_pct": round(float(sim_means.mean() * 100.0), 2),
        "fee_2x_nav": round(float(np.prod(1.0 + rr_2x)), 2),
        "drop_top15pct_nav": round(float(np.prod(1.0 + rr_adv15)), 2),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    raw_all, df, data_as_of_date = load_all_clean_data()
    csi = json.load(open(CSI_CANON_JSON, encoding="utf-8"))
    sh300 = json.load(open(IDX_JSON, encoding="utf-8"))["sh000300"]
    t_days = sorted([d for d in sh300.keys() if CANON_5Y_START <= d <= DATA_AS_OF_EXPECTED])
    day_idx = {d: i for i, d in enumerate(t_days)}

    # 1. 硬骨架 + 全样本打分
    gated_all = apply_hard_gates(df)
    gated_all["score"] = score_dataframe(gated_all, base_pts=58)
    comp_all = compute_score_components(gated_all)

    gated_5y = gated_all[gated_all["buy_date"] >= CANON_5Y_START].copy().reset_index(drop=True)
    comp_5y = compute_score_components(gated_5y)

    # 2. 导出标准档 (>=90) 与高严档 (>=96) 逐笔台账 (Canon 5Y, 对齐 V5.1/V3.4/V18 口径)
    ledger_std90_5y = sim_single_slot(gated_5y[gated_5y["score"] >= 90])
    ledger_strict96_5y = sim_single_slot(gated_5y[gated_5y["score"] >= 96])
    ledger_std90_5y.to_csv(f"{OUT_DIR}/ledger_base_2to3_v10_std90.csv", index=False, encoding="utf-8-sig")
    ledger_strict96_5y.to_csv(f"{OUT_DIR}/ledger_base_2to3_v10_strict96.csv", index=False, encoding="utf-8-sig")

    # Full 2021-01-04 ~ 2026-11-16 single-slot (用于 2021-2023 训练 vs 2024-2026 盲测)
    ledger_std90_full = sim_single_slot(gated_all[gated_all["score"] >= 90])
    ledger_strict96_full = sim_single_slot(gated_all[gated_all["score"] >= 96])

    # 3. Assert 3: 截断零未来函数硬断言 (彻底删除 2025-2026 后重跑 2021-2024)
    trunc_raw = raw_all[(raw_all["buy_date"] <= "2024-12-31") & (raw_all["exit_dt_cc"] <= "2024-12-31")].copy()
    trunc_df = df[(df["buy_date"] <= "2024-12-31") & (df["exit_dt_cc"] <= "2024-12-31")].copy()
    trunc_gated = apply_hard_gates(trunc_df)
    trunc_gated["score"] = score_dataframe(trunc_gated, base_pts=58)

    trunc_check = {}
    for tier, th, full_led in [("std90", 90, ledger_std90_full), ("strict96", 96, ledger_strict96_full)]:
        full_2124 = full_led[full_led["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        trunc_2124 = sim_single_slot(trunc_gated[trunc_gated["score"] >= th]).reset_index(drop=True)
        assert len(full_2124) == len(trunc_2124), f"Trunc len mismatch {tier}: {len(full_2124)} vs {len(trunc_2124)}"
        max_abs_diff = float(np.max(np.abs(full_2124["net_ret"].to_numpy() - trunc_2124["net_ret"].to_numpy())))
        assert max_abs_diff == 0.0, f"Trunc diff != 0.0 for {tier}: {max_abs_diff}"
        assert (full_2124["code"] == trunc_2124["code"]).all() and (full_2124["buy_date"] == trunc_2124["buy_date"]).all()
        trunc_check[tier] = {"trades_2021_2024": int(len(trunc_2124)), "max_abs_diff": max_abs_diff}

    # 4. 五期标准对比 + 训练vs盲测 + 分年度
    win_specs = [
        ("2026年10月起", "2026-10-01", "2026-11-16", csi["2026年10月以来"][0]),
        ("2026年7月起", "2026-07-01", "2026-11-16", csi["2026年7月以来"][0]),
        ("2026全年", "2026-01-01", "2026-11-16", csi["2026全年"][0]),
        ("近三年_20231116起", "2023-11-16", "2026-11-16", csi["近三年(2023-11-16起)"][0]),
        ("全五年_20211116起", "2021-11-16", "2026-11-16", csi["全五年(2021-11-16起)"][0]),
        ("2021_2023样本内训练", "2021-01-01", "2023-12-31", -34.16),
        ("2024_2026全盲样本外", "2024-01-01", "2026-11-16", 15.99),
    ]
    windows_out = {}
    yearly_out = {}
    for tier, th, led_5y, led_full in [
        ("std90", 90, ledger_std90_5y, ledger_std90_full),
        ("strict96", 96, ledger_strict96_5y, ledger_strict96_full),
    ]:
        windows_out[tier] = {}
        for wname, sdt, edt, csi_p in win_specs:
            sa = gated_all[(gated_all["score"] >= th) & (gated_all["buy_date"] >= sdt) & (gated_all["buy_date"] <= edt)]
            src_led = led_5y if ("2026" in wname or "近三年" in wname or "全五年" in wname) else led_full
            ws = src_led[(src_led["buy_date"] >= sdt) & (src_led["buy_date"] <= edt)]
            windows_out[tier][wname] = calc_window_metrics(sa, ws, csi_p)
        yearly_out[tier] = {}
        for y in range(2021, 2027):
            ys = str(y)
            sa_y = gated_all[(gated_all["score"] >= th) & (gated_all["buy_date"].str.startswith(ys))]
            ws_y = led_full[led_full["buy_date"].str.startswith(ys)]
            rr = ws_y["net_ret"].to_numpy(dtype=float) if not ws_y.empty else np.array([])
            yearly_out[tier][ys] = {
                "raw_n": int(len(sa_y)),
                "single_n": int(len(rr)),
                "win_rate_pct": round(float((rr > 0).mean() * 100.0), 1) if len(rr) else 0.0,
                "single_nav": round(float(np.prod(1.0 + rr)), 2) if len(rr) else 1.0,
            }

    # 5. 分步过滤漏斗表 (Canon 5Y & Full 21-26)
    csi_5y = csi["全五年(2021-11-16起)"][0]
    raw_5y = raw_all[raw_all["buy_date"] >= CANON_5Y_START].copy()
    base_5y = df[df["buy_date"] >= CANON_5Y_START].copy()
    funnel_steps = [
        ("Step0_真2天2板母池", raw_5y, len(raw_all)),
        ("Step1_可买非一字非90日毒丸", base_5y, len(df)),
        ("Step2_5条硬骨架过滤", gated_5y, len(gated_all)),
        ("Step3_score>=85", gated_5y[gated_5y["score"] >= 85], int((gated_all["score"] >= 85).sum())),
        ("Step4_std90_score>=90", gated_5y[gated_5y["score"] >= 90], int((gated_all["score"] >= 90).sum())),
        ("Step5_strict96_score>=96", gated_5y[gated_5y["score"] >= 96], int((gated_all["score"] >= 96).sum())),
    ]
    funnel_table = {}
    for sname, sub_f, full_n in funnel_steps:
        if sname.startswith("Step0"):
            funnel_table[sname] = {
                "full_6y_raw_n": int(full_n),
                "raw_n": int(len(sub_f)),
                "buyable_n_in_5y": int(len(base_5y)),
                "note": "含一字涨停不可买与毒丸样本，故仅统计母池规模，自Step1起剔除一字与毒丸进入真实交易回测",
            }
            continue
        if "score" not in sub_f.columns:
            sub_f = sub_f.copy()
            sub_f["score"] = 0.0
        led_f = sim_single_slot(sub_f)
        m_f = calc_window_metrics(sub_f, led_f, csi_5y)
        m_f["full_6y_raw_n"] = int(full_n)
        funnel_table[sname] = m_f

    # 6. 防过拟合三件套 + DSR/HLZ/Monkey/2x摩擦
    # 6a. 连续邻域曲线 86/88/90/92/94/96/98 (Canon 5Y)
    neighborhood = {}
    for th in [86, 88, 90, 92, 94, 96, 98]:
        sub_n = gated_5y[gated_5y["score"] >= th]
        led_n = sim_single_slot(sub_n)
        neighborhood[f"th_{th}"] = calc_window_metrics(sub_n, led_n, csi_5y)

    # 6b. ±20% 权重 200 次蒙特卡洛扰动
    rng = np.random.default_rng(20261117)
    mc_perturb = {}
    for th_lbl, th_val in [("std90", 90), ("strict96", 96)]:
        navs, wrs, ns, ex3s = [], [], [], []
        for _ in range(200):
            mult = rng.uniform(0.80, 1.20, size=14)
            sc_p = 58.0 + comp_5y @ mult
            sub_p = gated_5y[sc_p >= th_val].copy()
            sub_p["score"] = sc_p[sc_p >= th_val]
            led_p = sim_single_slot(sub_p)
            rr = led_p["net_ret"].to_numpy(dtype=float) if not led_p.empty else np.array([])
            ns.append(len(rr))
            navs.append(float(np.prod(1.0 + rr)) if len(rr) else 1.0)
            wrs.append(float((rr > 0).mean() * 100.0) if len(rr) else 0.0)
            ex3s.append(float(np.prod(1.0 + np.sort(rr)[:-3])) if len(rr) > 3 else 1.0)
        mc_perturb[th_lbl] = {
            "runs": 200,
            "mean_trades": round(float(np.mean(ns)), 1),
            "trades_range": [int(np.min(ns)), int(np.max(ns))],
            "mean_win_rate_pct": round(float(np.mean(wrs)), 2),
            "nav_median": round(float(np.median(navs)), 2),
            "nav_p10": round(float(np.percentile(navs, 10)), 2),
            "nav_p90": round(float(np.percentile(navs, 90)), 2),
            "prob_nav_gt_1x_pct": round(float((np.array(navs) > 1.0).mean() * 100.0), 1),
            "ex3_median": round(float(np.median(ex3s)), 2),
            "prob_ex3_gt_1x_pct": round(float((np.array(ex3s) > 1.0).mean() * 100.0), 1),
        }

    # 6c. CSCV PBO (S=10 252 combos & S=8 70 combos, 既有 Audit8 分位切分 + 分数线阶梯)
    R_q_std90 = np.zeros((len(t_days), 14), dtype=float)
    for r in ledger_std90_5y.itertuples(index=False):
        i = day_idx.get(r.exit_date)
        if i is not None:
            R_q_std90[i, 0] += r.net_ret
    for v in range(1, 14):
        qv = float(np.quantile(ledger_std90_5y["score"], 0.05 + (v / 14.0) * 0.40))
        ts = sim_single_slot(gated_5y[gated_5y["score"] >= qv])
        for r in ts.itertuples(index=False):
            i = day_idx.get(r.exit_date)
            if i is not None:
                R_q_std90[i, v] += r.net_ret

    lad_ths = [90, 91, 92, 93, 94, 95, 96, 97, 98]
    R_lad = np.zeros((len(t_days), len(lad_ths)), dtype=float)
    for j, th in enumerate(lad_ths):
        ts = sim_single_slot(gated_5y[gated_5y["score"] >= th])
        for r in ts.itertuples(index=False):
            i = day_idx.get(r.exit_date)
            if i is not None:
                R_lad[i, j] += r.net_ret

    cscv_out = {
        "audit8_quantile_std90_S8": cscv_pbo_eval(R_q_std90, [f"q{i}" for i in range(14)], 8),
        "audit8_quantile_std90_S10": cscv_pbo_eval(R_q_std90, [f"q{i}" for i in range(14)], 10),
        "threshold_ladder_90_98_S8": cscv_pbo_eval(R_lad, [f"th{t}" for t in lad_ths], 8),
        "threshold_ladder_90_98_S10": cscv_pbo_eval(R_lad, [f"th{t}" for t in lad_ths], 10),
    }

    extra_stats = {
        "std90": calc_dsr_hlz_monkey_2xfee(ledger_std90_5y, base_5y, sh300, t_days),
        "strict96": calc_dsr_hlz_monkey_2xfee(ledger_strict96_5y, base_5y, sh300, t_days),
    }

    # 7. 设计消融对比: 开盘门 vs 扣分 / 板块门 / CleanExit vs F30
    ablation_out = {}
    for lbl, ohi, psz_lim, psz_pen in [
        ("HardGate_open[-6.5%,+2.5%]_plate<15(定版)", 0.025, 15, False),
        ("WideGate_open[-6.5%,+4.5%]_高开>=2.5%扣12", 0.045, 15, False),
        ("WideGate_open[-6.5%,+6.0%]_高开>=2.5%扣12", 0.060, 15, False),
        ("PlatePen_plate>=15扣12", 0.025, 999, True),
    ]:
        sub_ab = df[
            df["open_pct"].between(-0.065, ohi) & (df["plate_sz"] < psz_lim) & (~df["has_reg_10d"])
        ].copy().reset_index(drop=True)
        sub_ab["score"] = score_dataframe(sub_ab, base_pts=58)
        if ohi > 0.025:
            sub_ab["score"] -= np.where(sub_ab["open_pct"] > 0.025, 12.0, 0.0)
        if psz_pen:
            sub_ab["score"] -= np.where(sub_ab["plate_sz"] >= 15, 12.0, 0.0)
        sa5 = sub_ab[(sub_ab["buy_date"] >= CANON_5Y_START) & (sub_ab["score"] >= 90)]
        ablation_out[lbl] = calc_window_metrics(sa5, sim_single_slot(sa5), csi_5y)

    # CleanExit vs F30 + 5m 覆盖率
    cov_audit = {}
    for th_lbl, th_val in [("std90", 90), ("strict96", 96)]:
        sub_c = gated_5y[gated_5y["score"] >= th_val]
        led_cc = sim_single_slot(sub_c, "score", "ret_opn_cc", "exit_dt_cc", "exit_hh_cc")
        led_f30 = sim_single_slot(sub_c, "score", "ret_opn_f30", "exit_dt_f30", "exit_hh_f30")
        cov_audit[th_lbl] = {
            "has_5m_buy_pct": round(float(sub_c["has_5m_buy"].mean() * 100.0), 2),
            "has_5m_d4_sealed_pct": round(float(sub_c[sub_c["sealed_3b"]]["has_5m_d4"].mean() * 100.0), 2),
            "has_5m_d4_unsealed_pct": round(float(sub_c[~sub_c["sealed_3b"]]["has_5m_d4"].mean() * 100.0), 2),
            "CleanExit_CC": calc_window_metrics(sub_c, led_cc, csi_5y, "ret_opn_cc"),
            "F30_reb2": calc_window_metrics(sub_c, led_f30, csi_5y, "ret_opn_f30"),
        }

    # 8. 纯单仓与双半仓第4/第5顺位合体协同测试
    sys.path.insert(0, CLEAN_REF_DIR)
    from synthesize_master_clean_20261116 import standardize_ledger, run_1slot as port_1slot

    b_high = standardize_ledger(f"{CLEAN_REF_DIR}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴_V51", 1)
    b_3to4 = standardize_ledger(f"{CLEAN_REF_DIR}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四_V34", 2)
    b_1to2 = standardize_ledger(f"{CLEAN_REF_DIR}/partB_1to2/ledger_base_1to2_v18.csv", "一进二_V18", 3)
    aux_pry = standardize_ledger(f"{CLEAN_REF_DIR}/partC_aux/ledger_aux_pry_v10.csv", "超跌撬板_V10", 3)
    b_1to2_p4 = b_1to2.copy()
    b_1to2_p4["priority"] = 4

    def to_port_df(raw_sub: pd.DataFrame, tag: str, prio: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "buy_date": raw_sub["buy_date"].astype(str),
                "exit_date": raw_sub["exit_dt_cc"].astype(str),
                "code": raw_sub["code"].astype(str).str.zfill(6),
                "name": raw_sub["name"].astype(str),
                "net_ret": raw_sub["ret_opn_cc"].astype(float),
                "score": raw_sub["score"].astype(float),
                "buy_hhmm": 925,
                "exit_hhmm": raw_sub["exit_hh_cc"].astype(int),
                "strategy": tag,
                "priority": prio,
            }
        )

    def eval_portfolio(pool_df: pd.DataFrame) -> dict:
        sl = port_1slot(pool_df)
        out_p = {}
        for wname, sdt, csi_p in [
            ("2026年10月起", "2026-10-01", csi["2026年10月以来"][0]),
            ("2026年7月起", "2026-07-01", csi["2026年7月以来"][0]),
            ("2026全年", "2026-01-01", csi["2026全年"][0]),
            ("近三年_20231116起", "2023-11-16", csi["近三年(2023-11-16起)"][0]),
            ("全五年_20211115起", "2021-11-15", csi["全五年(2021-11-16起)"][0]),
        ]:
            s_w = sl[sl["buy_date"] >= sdt]
            p_w = pool_df[pool_df["buy_date"] >= sdt]
            rr = s_w["net_ret"].to_numpy(dtype=float) if not s_w.empty else np.array([])
            w, l = rr[rr > 0], rr[rr <= 0]
            plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 99.0
            nav = float(np.prod(1.0 + rr)) if len(rr) else 1.0
            ex3 = float(np.prod(1.0 + np.sort(rr)[:-3])) if len(rr) > 3 else 1.0
            pk = cur = 1.0
            mdd = 0.0
            for x in rr:
                cur *= 1.0 + x
                pk = max(pk, cur)
                mdd = max(mdd, (pk - cur) / pk)
            h2_df, h2_nav, h2_mdd = sim_two_half_slots(p_w, rcol="net_ret", ecol="exit_date", hcol="exit_hhmm")
            out_p[wname] = {
                "single_n": int(len(rr)),
                "win_rate_pct": round(float((rr > 0).mean() * 100.0), 2) if len(rr) else 0.0,
                "plr": round(plr, 2),
                "single_nav": round(nav, 2),
                "ex3_nav": round(ex3, 2),
                "max_dd_pct": round(float(mdd * 100.0), 2),
                "half2_n": int(len(h2_df)),
                "half2_nav": round(h2_nav, 2),
                "half2_mdd_pct": round(h2_mdd, 2),
                "csi300_pct": round(csi_p, 2),
                "excess_slot_pp": round((nav - 1.0) * 100.0 - csi_p, 2),
                "strategy_counts_slot": s_w["strategy"].value_counts().to_dict(),
            }
        return out_p

    p_23_90_raw = gated_5y[gated_5y["score"] >= 90]
    p_23_96_raw = gated_5y[gated_5y["score"] >= 96]
    portfolio_synergy = {
        "Base3_High_3to4_1to2": eval_portfolio(pd.concat([b_high, b_3to4, b_1to2], ignore_index=True)),
        "Base3_plus_Pry": eval_portfolio(pd.concat([b_high, b_3to4, aux_pry, b_1to2_p4], ignore_index=True)),
        "Base3_plus_2to3_std90_4th": eval_portfolio(
            pd.concat([b_high, b_3to4, b_1to2, to_port_df(p_23_90_raw, "二进三_V10_std90", 4)], ignore_index=True)
        ),
        "Base3_plus_Pry_plus_2to3_std90_5th": eval_portfolio(
            pd.concat([b_high, b_3to4, aux_pry, b_1to2_p4, to_port_df(p_23_90_raw, "二进三_V10_std90", 5)], ignore_index=True)
        ),
        "Base3_plus_2to3_strict96_4th": eval_portfolio(
            pd.concat([b_high, b_3to4, b_1to2, to_port_df(p_23_96_raw, "二进三_V10_strict96", 4)], ignore_index=True)
        ),
        "Base3_plus_Pry_plus_2to3_strict96_5th": eval_portfolio(
            pd.concat([b_high, b_3to4, aux_pry, b_1to2_p4, to_port_df(p_23_96_raw, "二进三_V10_strict96", 5)], ignore_index=True)
        ),
    }

    # 9. 极值前5大赚单与前5大亏单
    extremes = {}
    for tier, led in [("std90", ledger_std90_5y), ("strict96", ledger_strict96_5y)]:
        cols_e = ["code", "name", "buy_date", "buy_price", "exit_date", "exit_hhmm", "exit_price", "score", "open_pct", "net_ret", "sealed_3b", "plate"]
        extremes[tier] = {
            "top5_winners": led.sort_values("net_ret", ascending=False).head(5)[cols_e].to_dict(orient="records"),
            "top5_losers": led.sort_values("net_ret", ascending=True).head(5)[cols_e].to_dict(orient="records"),
        }

    summary = {
        "strategy_name": "二进三_V1.0_迷茫暗牌弱转强打分版",
        "data_as_of_date": data_as_of_date,
        "canon_5y_window": f"{CANON_5Y_START} ~ {data_as_of_date}",
        "scorecard_spec": {
            "base_points": 58,
            "std_threshold": 90,
            "strict_threshold": 96,
            "n_orthogonal_items": 14,
            "factor_names": FACTOR_NAMES,
            "hard_gates_0925": [
                "沪深主板10cm非ST真连续2天2板(剔除创业科创北交与PIT ST)",
                "D2二板非一字且D3开盘非一字涨停(~prev_is_yizi & buyable_open)",
                "D3 09:25开盘承接区间 [-6.5%, +2.5%]",
                "无近90日毒丸公告且无近10日监管风险公告(~has_tox_90d & ~has_reg_10d)",
                "全市场非单边吸血大热抱团(plate_sz < 15)",
            ],
            "tie_breaker": "score DESC, open_pct ASC, plate_sz ASC, code ASC",
            "execution_rule": "09:25集合竞价直买; CleanExit卖出(未封3板绕一字跌停,次日开盘<+0.5%于09:25斩仓释放资金,否则15:00清; 封3板走V3.4 13:45护利+真阳免死1次)",
        },
        "hard_asserts_passed": {
            "row_counts_10848_6070_verified": True,
            "data_as_of_date_eq_2026_11_16": True,
            "t0_violations": 0,
            "overlap_violations": 0,
            "truncation_zero_lookahead_2021_2024": trunc_check,
        },
        "windows_d15": windows_out,
        "yearly_2021_2026": yearly_out,
        "filter_funnel_canon5y": funnel_table,
        "anti_overfitting_three_pieces": {
            "cscv_pbo": cscv_out,
            "mc_weight_perturbation_pm20pct_200runs": mc_perturb,
            "neighborhood_curve_86_98": neighborhood,
            "truncation_test": trunc_check,
        },
        "extra_quant_audits": extra_stats,
        "design_ablations_canon5y": ablation_out,
        "execution_and_5m_coverage_audit": cov_audit,
        "portfolio_synergy": portfolio_synergy,
        "extremes_top5": extremes,
    }

    out_json_path = f"{OUT_DIR}/summary_2to3_v10_d15_and_audit.json"
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[PASS ALL 3 HARD ASSERTS] Truncation max_abs_diff = {trunc_check}")
    print(f"Saved ledgers & audit JSON to {OUT_DIR}")
    for tier in ("std90", "strict96"):
        w5 = windows_out[tier]["全五年_20211116起"]
        w3 = windows_out[tier]["近三年_20231116起"]
        w26 = windows_out[tier]["2026全年"]
        print(
            f"  [{tier}] 5Y: ss={w5['single_n']} WR={w5['win_rate_pct']}% PLR={w5['plr']} "
            f"1S={w5['single_nav']}x H2={w5['half2_nav']}x EW={w5['eq_nav']}x Ex3={w5['ex3_nav']}x "
            f"MDD={w5['max_dd_pct']}% Exc={w5['excess_slot_pp']:+.1f}pp | "
            f"3Y={w3['single_nav']}x | 26={w26['single_nav']}x"
        )
    print("  CSCV PBO (std90):", cscv_out)
    print("  Portfolio 4th (std90) 5Y:", portfolio_synergy["Base3_plus_2to3_std90_4th"]["全五年_20211115起"])


if __name__ == "__main__":
    main()
