#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
二进三 V2.0 全因子与连续截点左右波动高原寻优实验
严格隔离: 100% 只读现有生产与研究数据源; 严禁 yfinance (D12); SQLite 一律 mode=ro;
严格流程: 仅用 IS (2021-01-04 ~ 2023-12-31) 早晚双段+邻域高原筛选 -> OOS 盲测 -> D15 五期表 -> 8项审计(含M=300/500) -> 2024-12-31物理截断。
"""

import os
import sys
import json
import math
import time
from dataclasses import dataclass, replace, asdict

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
OUT_DIR = f"{SIM}/backtests_astock/factor_perturbation_2to3_20261117"

sys.path.insert(0, UPG_DIR)
import upgrade_2to3_pit as u  # noqa: E402

assert "yfinance" not in sys.modules, "D12 VIOLATION after import!"

IS_START = "2021-01-04"
IS_EARLY_END = "2022-06-30"
IS_LATE_START = "2022-07-01"
IS_END = "2023-12-31"
OOS_START = "2024-01-01"
DATA_AS_OF = u.DATA_AS_OF_EXPECTED


def round_half_away(val: float, mult: float) -> int:
    return int(math.copysign(math.floor(abs(val) * mult + 0.5), val))


@dataclass
class V20Config:
    base_pts: int = 60
    threshold: int = 90
    open_low: float = -0.065
    open_high: float = 0.025
    plate_sz_max: int = 15
    # Dim A factor weights
    w_p11_pos: int = 6
    w_p11_neg: int = -10
    w_p12_both: int = 8
    w_p12_p23: int = 5
    w_p13: int = 6
    w_p21_warm: int = 5
    w_p21_crowd: int = -10
    w_p22: int = 8
    w_p24: int = -8
    w_p31_mid: int = -10
    w_p31_hot: int = -18
    w_p32: int = -10
    w_p41: int = 6
    w_p42_weak: int = 6
    w_p42_fast: int = -8
    w_p42_huge: int = -16
    w_p43: int = 6
    w_p44_high: int = 8
    w_p44_mid: int = 5
    w_p44_low: int = -8
    w_p51: int = 5
    w_u1: int = 4
    w_u2: int = 4
    w_u3: int = -8
    w_u4: int = -6
    w_u5: int = -6
    # Dim B continuous cutoffs inside factors
    elo_cut: float = 95.0
    xq_zero_max: int = 0
    xq_hot_min: int = 4
    d2_low_cut: float = -0.02
    pos20_cut: float = 0.40
    lock_cut: float = 50.0
    turn_low: float = 15.0
    turn_mid: float = 25.0
    turn_high: float = 65.0
    p51_open_cut: float = 0.0
    u4_seal_sec: float = 12600.0
    # Dim B exit cutoffs
    d4_open_tp: float = 0.092
    guard_hhmm: int = 1345
    guard_act: float = 1.085
    guard_stop: float = 1.050


def build_pit_dataset_ext(cutoff_date: str | None = None):
    """100% 复用 upgrade_2to3_pit 底座加载逻辑，并额外保留因果 Elo 连续数值供截点扫描"""
    raw_all = pd.read_parquet(u.RAW_2TO3_PQ)
    wa = pd.read_parquet(u.WAVE_A_PQ)
    wb = pd.read_parquet(u.WAVE_B_PQ)
    wc = pd.read_parquet(u.WAVE_C_PQ)

    if cutoff_date is None:
        assert len(raw_all) == 10848, f"Expected 10848 raw rows, got {len(raw_all)}"
        data_as_of_date = str(raw_all["exit_dt_cc"].max())
        assert data_as_of_date == DATA_AS_OF, f"data_as_of_date mismatch: {data_as_of_date}"
    else:
        raw_all = raw_all[(raw_all["buy_date"] <= cutoff_date) & (raw_all["exit_dt_cc"] <= cutoff_date)].copy()
        data_as_of_date = str(raw_all["buy_date"].max())

    base = raw_all[raw_all["buyable_open"] & (~raw_all["prev_is_yizi"]) & (~raw_all["has_tox_90d"])].copy()
    wc_cols = [c for c in wc.columns if c not in ("code", "buy_date") and c not in base.columns]
    df = (
        base.merge(wa, on=["code", "buy_date"], how="inner")
        .merge(wb, on=["code", "buy_date"], how="inner")
        .merge(wc[["code", "buy_date"] + wc_cols], on=["code", "buy_date"], how="inner")
    )
    if cutoff_date is None:
        assert len(df) == 6070, f"Expected 6070 clean rows, got {len(df)}"

    # 三行硬代码校验: 单位除数 + 时间锚点 < buy_date 09:25:00 + 行列极值
    assert 5.0 < float(df["prev_close"].median()) < 50.0, "prev_close unit check failed"
    assert abs(float(df["ret_opn_cc"].median())) < 0.25, "ret_opn_cc decimal check failed"
    assert (df["sig_date"] < df["buy_date"]).all(), "Time anchor sig_date < buy_date 09:25:00 failed"
    assert 10.0 < float(df["d2_real_turn"].median()) < 40.0 and (df["d2_real_turn"].dropna().between(0.0, 2000.0)).all(), "d2_real_turn extreme check failed"

    da, b5m = u.load_daily_and_5m(cutoff_date)
    cs = u.compute_causal_raw_signals(da, cutoff_date)

    df["b01_hhi_low_q25"] = [cs["rec_hhi"].get(sd, 0) for sd in df["sig_date"]]
    df["d2_own_new_term"] = [cs["rec_own"].get((sd, str(c6).zfill(6)), False) for sd, c6 in zip(df["sig_date"], df["code"])]
    df["d1_is_dying_pulse"] = [cs["rec_dying"].get((d1, str(c6).zfill(6)), False) for d1, c6 in zip(df["d1_date"], df["code"])]
    df["d1_is_yizi"] = [cs["yizi_map"].get((d1, str(c6).zfill(6)), False) for d1, c6 in zip(df["d1_date"], df["code"])]
    df["d2_seal_sec_causal"] = [cs["tape_sec"].get((sd, str(c6).zfill(6)), None) for sd, c6 in zip(df["sig_date"], df["code"])]

    csrc_by_c6 = cs["csrc_by_c6"]

    def _csrc(c6, sd):
        for s0, e0, ind in csrc_by_c6.get(c6, []):
            if s0 <= sd <= e0:
                return ind
        return "UNK"

    ht_mask = df["plate"].astype(str).str.contains(u.HARD_TECH_RE, regex=True).to_numpy()
    ma_mask = (df["notice_hard"].fillna(False) | df["d2_is_ma"].fillna(False)).to_numpy()
    df["is_pure_outsider_causal"] = [
        bool(h and (_csrc(str(c6).zfill(6), str(sd)) in u.CSRC_PURE_OUTSIDER) and (not m))
        for h, c6, sd, m in zip(ht_mask, df["code"], df["sig_date"], ma_mask)
    ]
    df["elo_p_causal"] = [
        float(cs["rec_elo_p"].get((sd, str(c6).zfill(6)), (0, 100.0))[1])
        for sd, c6 in zip(df["sig_date"], df["code"])
    ]
    df["elo_s_causal"] = [
        float(cs["rec_elo_s"].get((sd, str(c6).zfill(6)), 100.0))
        for sd, c6 in zip(df["sig_date"], df["code"])
    ]
    df["elo_ice_causal"] = [
        int(ep < 95.0 or es <= 95.0)
        for ep, es in zip(df["elo_p_causal"], df["elo_s_causal"])
    ]
    return raw_all, df, da, b5m, data_as_of_date


def sim_v2_exit_param(
    df: pd.DataFrame, da: pd.DataFrame, b5m: dict,
    d4_open_tp: float = 0.092, guard_hhmm: int = 1345,
    guard_act: float = 1.085, guard_stop: float = 1.050,
    cutoff_date: str | None = None
) -> tuple[list, list, list]:
    """参数化版 V2.0 出场树 (与 upgrade_2to3_pit.sim_v2_exit_all 完全同构)"""
    all_dts = sorted(da["dt"].unique())
    dt_idx = {d: i for i, d in enumerate(all_dts)}
    plook = {
        (r.c6, r.dt): (
            float(r.open), float(r.high), float(r.low), float(r.close),
            float(r.pre_c) if pd.notna(r.pre_c) else float(r.close),
            float(r.zt_px) if pd.notna(r.zt_px) else 9999.0,
            float(r.dt_px) if pd.notna(r.dt_px) else 0.0,
            bool(r.is_zt), bool(r.is_dt_exact), bool(r.is_yizi), bool(r.is_yizi_dt),
        )
        for r in da[da["dt"] >= "2020-12-25"][
            ["c6", "dt", "open", "high", "low", "close", "pre_c", "zt_px", "dt_px", "is_zt", "is_dt_exact", "is_yizi", "is_yizi_dt"]
        ].itertuples(index=False)
    }

    rets, eds, ehs = [], [], []
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        pos = dt_idx.get(bd, -1)
        if pos < 0 or pos >= len(all_dts) - 1:
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        b3 = plook.get((c6, bd))
        if not b3:
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)

        def run_zt_hold(sp_idx: int):
            k = sp_idx + 1
            used_imm = False
            while k < len(all_dts) and (k - pos <= 18):
                dk = all_dts[k]
                bk = plook.get((c6, dk))
                if not bk:
                    k += 1; continue
                ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = bk
                if iyzdtk:
                    k += 1; continue
                if k > sp_idx + 1:
                    pb = plook.get((c6, all_dts[k - 1]))
                    if pb and (pb[10] or pb[8]):
                        return (ok / buy_px) * (1.0 - u.FEE_ROUNDTRIP) - 1.0, dk, 925
                if k == pos + 1:
                    d4_op = ok / pck - 1.0 if pck > 0 else 0.0
                    if (d4_op > d4_open_tp) and (ok < ztk - 0.005):
                        return (ok / buy_px) * (1.0 - u.FEE_ROUNDTRIP) - 1.0, dk, 925
                arr = b5m.get((c6, dk))
                if arr is not None and len(arr) > 0:
                    pk = ok
                    for row5 in arr:
                        hh, bo, bh, bl, bc = int(row5[0]), row5[1], row5[2], row5[3], row5[4]
                        if bh <= dtk + 0.005:
                            continue
                        if hh >= guard_hhmm and pk >= pck * guard_act and bl <= pck * guard_stop and bc < ztk - 0.01:
                            px = min(bo, pck * guard_stop)
                            if px > dtk + 0.005:
                                return (px / buy_px) * (1.0 - u.FEE_ROUNDTRIP) - 1.0, dk, hh
                        if bh > pk:
                            pk = bh
                if iztk:
                    k += 1; continue
                if idtk:
                    k += 1; continue
                if (not used_imm) and (ck > ok) and (ck >= pck):
                    used_imm = True; k += 1; continue
                return (ck / buy_px) * (1.0 - u.FEE_ROUNDTRIP) - 1.0, dk, 1500
            return float(r.ret_opn_cc), str(r.exit_dt_cc), int(r.exit_hh_cc)

        if b3[7]:
            rv, edv, ehv = run_zt_hold(pos)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
            continue

        k = pos + 1
        while k < len(all_dts):
            bk = plook.get((c6, all_dts[k]))
            if bk and not bk[10]:
                break
            k += 1
        if k >= len(all_dts):
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        dk = all_dts[k]
        ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = plook[(c6, dk)]
        if k > pos + 1:
            rets.append((ok / buy_px) * (1.0 - u.FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
        elif iztk:
            rv, edv, ehv = run_zt_hold(k)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
        elif idtk:
            m = k + 1
            sold = False
            while m < len(all_dts):
                bm = plook.get((c6, all_dts[m]))
                if bm and not bm[10]:
                    rets.append((bm[0] / buy_px) * (1.0 - u.FEE_ROUNDTRIP) - 1.0); eds.append(all_dts[m]); ehs.append(925)
                    sold = True; break
                m += 1
            if not sold:
                rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
        else:
            rets.append((ck / buy_px) * (1.0 - u.FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(1500)

    if cutoff_date is None:
        for idx_i, r in enumerate(df.itertuples(index=False)):
            ed, eh = eds[idx_i], ehs[idx_i]
            bk = plook.get((str(r.code).zfill(6), ed))
            if bk:
                assert not bk[10], f"Sold on yizi_dt violation: {r.code} {ed}"
                if eh == 1500 and ed < all_dts[-1]:
                    assert not bk[8], f"Sold at 15:00 on EOD exact limit-down violation: {r.code} {ed}"
    return rets, eds, ehs


def compute_components_param(d: pd.DataFrame, cfg: V20Config) -> np.ndarray:
    """参数化计算18项正交打分矩阵"""
    elo_ice = (d["elo_p_causal"].to_numpy() < cfg.elo_cut) | (d["elo_s_causal"].to_numpy() <= cfg.elo_cut)
    mid_warm = d["plate_rk_noev"].between(3, 7) | d["plate_sz"].between(2, 6)
    hot_crowd = ((d["plate_rk_noev"] <= 2) & (d["plate_sz"] >= 7)) | (d["plate_sz"] >= 12)
    both_low = (d["mkt_p12_prev"] < 0.18) & (d["mkt_p23_prev"] < 0.28)
    d2_weak_late = (d["d2_open_cnt_tape"] >= 1) & ((d["d2_seal_sec"].fillna(0) >= 1800) | (d["d2_seal_amt_ratio"].fillna(1) < 0.05))
    d2_fast_zero = (d["d2_open_cnt_tape"] == 0) & (d["d2_seal_sec"].fillna(99999) <= 300)

    comp = np.zeros((len(d), 18), dtype=float)
    comp[:, 0] = np.where(d["b01_hhi_low_q25"] == 1, float(cfg.w_p11_pos), np.where(d["raw_top1_share"] >= 0.30, float(cfg.w_p11_neg), 0.0))
    comp[:, 1] = np.where(both_low, float(cfg.w_p12_both), np.where(d["mkt_p23_prev"] < 0.28, float(cfg.w_p12_p23), 0.0))
    comp[:, 2] = np.where(d["mkt_maxb_prev"] <= 3, float(cfg.w_p13), 0.0)
    comp[:, 3] = np.where(hot_crowd, float(cfg.w_p21_crowd), np.where(mid_warm, float(cfg.w_p21_warm), 0.0))
    comp[:, 4] = np.where(elo_ice, float(cfg.w_p22), 0.0)
    comp[:, 5] = np.where(d["plate_3b_cnt_sd"] >= 1, float(cfg.w_p24), 0.0)

    xq = d["xq_cnt_tot"].to_numpy(dtype=float)
    comp[:, 6] = np.where(xq <= cfg.xq_zero_max, 0.0, np.where(xq >= cfg.xq_hot_min, float(cfg.w_p31_hot), float(cfg.w_p31_mid)))
    comp[:, 7] = np.where(d["ir_has_20d"] == 1, float(cfg.w_p32), 0.0)
    comp[:, 8] = np.where(d["d2_low_pct"] <= cfg.d2_low_cut, float(cfg.w_p41), 0.0)
    comp[:, 9] = np.where(
        d["d2_seal_amt_ratio"].fillna(0) >= 0.25, float(cfg.w_p42_huge),
        np.where(d2_fast_zero, float(cfg.w_p42_fast), np.where(d2_weak_late, float(cfg.w_p42_weak), 0.0))
    )
    comp[:, 10] = np.where(d["pos_20d_d0"].fillna(0.5) <= cfg.pos20_cut, float(cfg.w_p43), 0.0)

    turn = d["d2_real_turn"]
    lock_ok = d["lock_top10"].fillna(0) >= cfg.lock_cut
    turn_z = turn.fillna(0)
    comp[:, 11] = np.where(
        turn.fillna(30.0) < cfg.turn_low, float(cfg.w_p44_low),
        np.where(lock_ok & turn_z.between(cfg.turn_mid, cfg.turn_high), float(cfg.w_p44_high),
        np.where(lock_ok & turn_z.between(cfg.turn_low, cfg.turn_mid - 1e-4), float(cfg.w_p44_mid), 0.0))
    )
    comp[:, 12] = np.where(d["open_pct"] < cfg.p51_open_cut, float(cfg.w_p51), 0.0)
    comp[:, 13] = np.where(d["is_pure_outsider_causal"].to_numpy(), float(cfg.w_u1), 0.0)
    comp[:, 14] = np.where(d["d2_own_new_term"].to_numpy(), float(cfg.w_u2), 0.0)
    comp[:, 15] = np.where(d["d1_is_dying_pulse"].to_numpy(), float(cfg.w_u3), 0.0)
    comp[:, 16] = np.where(d["d2_seal_sec_causal"].fillna(-1.0) >= cfg.u4_seal_sec, float(cfg.w_u4), 0.0)
    comp[:, 17] = np.where(d["d1_is_yizi"].to_numpy(), float(cfg.w_u5), 0.0)
    return comp


def calc_quick_metrics(sub_raw: pd.DataFrame, sub_slot: pd.DataFrame, rcol: str) -> dict:
    if sub_slot.empty:
        return {
            "raw_n": int(len(sub_raw)), "single_n": 0, "wr": 0.0, "plr": 0.0,
            "mean": 0.0, "single_nav": 1.0, "eq_nav": 1.0, "mdd": 0.0,
        }
    rr = sub_slot["net_ret"].to_numpy(dtype=float)
    w, l = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nc = np.cumprod(1.0 + rr)
    pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
    mdd = float(np.max((pk - nc) / pk) * 100.0)
    ew = float(np.prod(1.0 + sub_raw.groupby("buy_date")[rcol].mean().sort_index().to_numpy())) if len(sub_raw) else 1.0
    return {
        "raw_n": int(len(sub_raw)),
        "single_n": int(len(rr)),
        "wr": round(wr, 2),
        "plr": round(plr, 2),
        "mean": round(float(rr.mean() * 100.0), 2),
        "single_nav": round(float(nc[-1]), 2),
        "eq_nav": round(ew, 2),
        "mdd": round(mdd, 2),
    }


def calc_d15_window_metrics(sub_raw: pd.DataFrame, sub_slot: pd.DataFrame, csi_pct: float, rcol: str, ecol: str, hcol: str) -> dict:
    """D15 全口径窗口指标: 含按日等权、单仓、100w->1000w封顶、1000w单利、1000w封顶、去前3/前5、同期沪深300净超额"""
    m = u.calc_window_metrics(sub_raw, sub_slot, csi_pct, rcol, ecol, hcol)
    if sub_slot.empty:
        m["cap_100w_to_1000w_mult"] = 1.0
        m["cap_100w_to_1000w_ret_pct"] = 0.0
        m["cap_100w_to_1000w_excess_pp"] = round(-csi_pct, 2)
        m["cap10m_simple_mult"] = 1.0
        m["cap10m_simple_ret_pct"] = 0.0
        m["cap10m_simple_excess_pp"] = round(-csi_pct, 2)
        return m
    rr = sub_slot["net_ret"].to_numpy(dtype=float)
    cap100 = 100.0
    for x in rr:
        cap100 += min(cap100, 1000.0) * float(x)
    c100_mult = cap100 / 100.0
    c100_ret = (c100_mult - 1.0) * 100.0
    simp_ret = float(rr.sum() * 100.0)
    m["cap_100w_to_1000w_mult"] = round(c100_mult, 2)
    m["cap_100w_to_1000w_ret_pct"] = round(c100_ret, 2)
    m["cap_100w_to_1000w_excess_pp"] = round(c100_ret - csi_pct, 2)
    m["cap10m_simple_mult"] = round(1.0 + float(rr.sum()), 2)
    m["cap10m_simple_ret_pct"] = round(simp_ret, 2)
    m["cap10m_simple_excess_pp"] = round(simp_ret - csi_pct, 2)
    return m


def run_8tests_audit_m300(
    led_5y: pd.DataFrame, gated_5y: pd.DataFrame, comp_5y: np.ndarray, base_5y_pool: pd.DataFrame,
    sh300: dict, t_days: list, sc_col: str, th_val: int, rcol: str, ecol: str, hcol: str,
    base_pts: int, fac_names: list, run_lofo: bool = True
) -> dict:
    """复用 upgrade_2to3_pit 8项审计，并将 DSR 严格扩展至 M=30, 150, 300, 500"""
    res = u.run_8tests_audit(
        led_5y, gated_5y, comp_5y, base_5y_pool,
        sh300, t_days, sc_col, th_val, rcol, ecol, hcol,
        base_pts, fac_names, run_lofo=run_lofo
    )
    all_dates = sorted(sh300.keys())

    def bench_ret(bd: str, ed: str) -> float:
        prevs = [d for d in all_dates if d < bd]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dates[0]]
        p1 = sh300.get(ed, sh300[all_dates[-1]])
        return float(p1 / p0 - 1.0)

    n = len(led_5y)
    ex = np.array([float(r.net_ret) - bench_ret(r.buy_date, r.exit_date) for r in led_5y.itertuples(index=False)])
    sr_tr = float(ex.mean() / ex.std(ddof=1)) if n > 1 else 0.0
    skew = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    kurt = float(stats.kurtosis(ex, fisher=False, bias=False)) if n > 3 else 3.0
    gamma = 0.5772156649
    dsr_out = {}
    for M in (30, 150, 300, 500):
        sr0 = (1.0 / np.sqrt(max(n - 1, 1))) * ((1.0 - gamma) * stats.norm.ppf(1.0 - 1.0 / M) + gamma * stats.norm.ppf(1.0 - 1.0 / (M * np.e)))
        denom = np.sqrt(max(1e-12, 1.0 - skew * sr_tr + ((kurt - 1.0) / 4.0) * (sr_tr ** 2)))
        dsr_out[f"M{M}"] = round(float(stats.norm.cdf((sr_tr - sr0) * np.sqrt(max(n - 1, 1)) / denom)), 4)
    res["test1_hlz_dsr"]["dsr_trade_prob"] = dsr_out
    return res


def build_grid_specs() -> list[dict]:
    """构造维度A (全部18因子分值左右波动) 与维度B (全部连续截点左右波动) 扫描清单"""
    base = V20Config()
    specs = []

    def add_group(dim: str, group: str, mech: str, items: list[tuple[str, bool, dict]]):
        for gidx, (label, is_b, patch) in enumerate(items):
            specs.append({
                "dim": dim,
                "group": group,
                "mech": mech,
                "grid_idx": gidx,
                "label": label,
                "is_baseline": is_b,
                "patch": patch,
                "cfg": replace(base, **patch),
            })

    # === 维度A: 12个单档因子 5档扫描 ===
    single_a = [
        ("A_P1_3", "P1_3", "w_p13", [2, 4, 6, 8, 10], 6),
        ("A_P2_2", "P2_2", "w_p22", [4, 6, 8, 10, 12], 8),
        ("A_P2_4", "P2_4", "w_p24", [-12, -10, -8, -6, -4], -8),
        ("A_P3_2", "P3_2", "w_p32", [-14, -12, -10, -8, -6], -10),
        ("A_P4_1", "P4_1", "w_p41", [2, 4, 6, 8, 10], 6),
        ("A_P4_3", "P4_3", "w_p43", [2, 4, 6, 8, 10], 6),
        ("A_P5_1", "P5_1", "w_p51", [1, 3, 5, 7, 9], 5),
        ("A_U1", "U1", "w_u1", [0, 2, 4, 6, 8], 4),
        ("A_U2", "U2", "w_u2", [0, 2, 4, 6, 8], 4),
        ("A_U3", "U3", "w_u3", [-12, -10, -8, -6, -4], -8),
        ("A_U4", "U4", "w_u4", [-10, -8, -6, -4, -2], -6),
        ("A_U5", "U5", "w_u5", [-10, -8, -6, -4, -2], -6),
    ]
    for grp, mech, field, vals, bval in single_a:
        add_group("DimA_weight", grp, mech, [
            (f"{v:+d}{'(base)' if v == bval else ''}", v == bval, {field: v})
            for v in vals
        ])

    # === 维度A: 6个多档复合因子 整体缩放 [0.5x, 0.75x, 1.0x, 1.25x, 1.5x] + 子档位独立微调 ===
    mults = [0.5, 0.75, 1.0, 1.25, 1.5]
    multi_scales = [
        ("A_P1_1_scale", "P1_1", {"w_p11_pos": 6, "w_p11_neg": -10}),
        ("A_P1_2_scale", "P1_2", {"w_p12_both": 8, "w_p12_p23": 5}),
        ("A_P2_1_scale", "P2_1", {"w_p21_warm": 5, "w_p21_crowd": -10}),
        ("A_P3_1_scale", "P3_1", {"w_p31_mid": -10, "w_p31_hot": -18}),
        ("A_P4_2_scale", "P4_2", {"w_p42_weak": 6, "w_p42_fast": -8, "w_p42_huge": -16}),
        ("A_P4_4_scale", "P4_4", {"w_p44_high": 8, "w_p44_mid": 5, "w_p44_low": -8}),
    ]
    for grp, mech, base_dict in multi_scales:
        items = []
        for m in mults:
            patch = {k: round_half_away(v, m) for k, v in base_dict.items()}
            desc = "/".join(f"{val:+d}" for val in patch.values())
            items.append((f"{m:.2f}x({desc}){'(base)' if m == 1.0 else ''}", m == 1.0, patch))
        add_group("DimA_weight", grp, mech, items)

    sub_tiers = [
        ("A_P1_1_pos", "P1_1", "w_p11_pos", [2, 4, 6, 8, 10], 6),
        ("A_P1_1_neg", "P1_1", "w_p11_neg", [-14, -12, -10, -8, -6], -10),
        ("A_P1_2_both", "P1_2", "w_p12_both", [4, 6, 8, 10, 12], 8),
        ("A_P1_2_p23", "P1_2", "w_p12_p23", [1, 3, 5, 7, 9], 5),
        ("A_P2_1_warm", "P2_1", "w_p21_warm", [1, 3, 5, 7, 9], 5),
        ("A_P2_1_crowd", "P2_1", "w_p21_crowd", [-14, -12, -10, -8, -6], -10),
        ("A_P3_1_mid", "P3_1", "w_p31_mid", [-14, -12, -10, -8, -6], -10),
        ("A_P3_1_hot", "P3_1", "w_p31_hot", [-22, -20, -18, -16, -14], -18),
        ("A_P4_2_weak", "P4_2", "w_p42_weak", [2, 4, 6, 8, 10], 6),
        ("A_P4_2_fast", "P4_2", "w_p42_fast", [-12, -10, -8, -6, -4], -8),
        ("A_P4_2_huge", "P4_2", "w_p42_huge", [-20, -18, -16, -14, -12], -16),
        ("A_P4_4_high", "P4_4", "w_p44_high", [4, 6, 8, 10, 12], 8),
        ("A_P4_4_mid", "P4_4", "w_p44_mid", [1, 3, 5, 7, 9], 5),
        ("A_P4_4_low", "P4_4", "w_p44_low", [-12, -10, -8, -6, -4], -8),
    ]
    for grp, mech, field, vals, bval in sub_tiers:
        add_group("DimA_weight", grp, mech, [
            (f"{v:+d}{'(base)' if v == bval else ''}", v == bval, {field: v})
            for v in vals
        ])

    # === 维度B: 全部连续物理截点 (硬门 + 因子截点 + 卖点截点 + 总分门槛) ===
    add_group("DimB_cutoff", "B01_open_low", "gate_open_low", [
        (f"{v*100:.1f}%{'(base)' if v == -0.065 else ''}", v == -0.065, {"open_low": v})
        for v in [-0.080, -0.070, -0.065, -0.055, -0.045]
    ])
    add_group("DimB_cutoff", "B02_open_high", "gate_open_high", [
        (f"+{v*100:.1f}%{'(base)' if v == 0.025 else ''}", v == 0.025, {"open_high": v})
        for v in [0.015, 0.020, 0.025, 0.030, 0.035]
    ])
    add_group("DimB_cutoff", "B03_plate_sz_max", "gate_plate_sz", [
        (f"<{v}{'(base)' if v == 15 else ''}", v == 15, {"plate_sz_max": v})
        for v in [10, 12, 15, 18, 22]
    ])
    add_group("DimB_cutoff", "B04_P2_2_elo", "P2_2_cut", [
        (f"<={v:.0f}{'(base)' if v == 95.0 else ''}", v == 95.0, {"elo_cut": v})
        for v in [90.0, 93.0, 95.0, 97.0, 99.0]
    ])
    add_group("DimB_cutoff", "B05_P3_1_xq_cut", "P3_1_cut", [
        ("(0, >=3)", False, {"xq_zero_max": 0, "xq_hot_min": 3}),
        ("(0, >=4)(base)", True, {"xq_zero_max": 0, "xq_hot_min": 4}),
        ("(<=1, >=4)", False, {"xq_zero_max": 1, "xq_hot_min": 4}),
        ("(<=1, >=5)", False, {"xq_zero_max": 1, "xq_hot_min": 5}),
    ])
    add_group("DimB_cutoff", "B06_P4_1_d2_low", "P4_1_cut", [
        (f"<={v*100:.1f}%{'(base)' if v == -0.02 else ''}", v == -0.02, {"d2_low_cut": v})
        for v in [-0.04, -0.03, -0.02, -0.01, 0.0]
    ])
    add_group("DimB_cutoff", "B07_P4_3_pos20", "P4_3_cut", [
        (f"<={v:.2f}{'(base)' if v == 0.40 else ''}", v == 0.40, {"pos20_cut": v})
        for v in [0.25, 0.33, 0.40, 0.50, 0.60]
    ])
    add_group("DimB_cutoff", "B08a_P4_4_lock", "P4_4_lock_cut", [
        (f">={v:.0f}%{'(base)' if v == 50.0 else ''}", v == 50.0, {"lock_cut": v})
        for v in [40.0, 45.0, 50.0, 55.0, 60.0]
    ])
    add_group("DimB_cutoff", "B08b_P4_4_turn_low", "P4_4_turn_low", [
        (f"{v:.0f}%{'(base)' if v == 15.0 else ''}", v == 15.0, {"turn_low": v})
        for v in [10.0, 12.0, 15.0, 18.0, 20.0]
    ])
    add_group("DimB_cutoff", "B08c_P4_4_turn_mid", "P4_4_turn_mid", [
        (f"{v:.0f}%{'(base)' if v == 25.0 else ''}", v == 25.0, {"turn_mid": v})
        for v in [19.0, 22.0, 25.0, 28.0, 31.0]
    ])
    add_group("DimB_cutoff", "B08d_P4_4_turn_high", "P4_4_turn_high", [
        (f"{v:.0f}%{'(base)' if v == 65.0 else ''}", v == 65.0, {"turn_high": v})
        for v in [45.0, 55.0, 65.0, 75.0, 85.0]
    ])
    add_group("DimB_cutoff", "B09_P5_1_open_cut", "P5_1_cut", [
        (f"<{v*100:+.1f}%{'(base)' if v == 0.0 else ''}", v == 0.0, {"p51_open_cut": v})
        for v in [-0.015, -0.005, 0.0, 0.005, 0.010]
    ])
    add_group("DimB_cutoff", "B10_U4_seal_time", "U4_cut", [
        (lbl, sec == 12600.0, {"u4_seal_sec": sec})
        for lbl, sec in [("14:00", 10800.0), ("14:15", 11700.0), ("14:30(base)", 12600.0), ("14:40", 13200.0), ("14:45", 13500.0)]
    ])
    add_group("DimB_cutoff", "B11a_exit_d4_open_tp", "exit_d4_tp", [
        (lbl, v == 0.092, {"d4_open_tp": v})
        for lbl, v in [("+8.0%", 0.080), ("+8.8%", 0.088), ("+9.2%(base)", 0.092), ("+9.6%", 0.096), ("不止盈", 9.99)]
    ])
    add_group("DimB_cutoff", "B11b_exit_1345_guard", "exit_guard", [
        ("+7.5%/+4.0%@13:45", False, {"guard_hhmm": 1345, "guard_act": 1.075, "guard_stop": 1.040}),
        ("+8.5%/+5.0%@13:45(base)", True, {"guard_hhmm": 1345, "guard_act": 1.085, "guard_stop": 1.050}),
        ("+9.0%/+5.5%@13:45", False, {"guard_hhmm": 1345, "guard_act": 1.090, "guard_stop": 1.055}),
        ("+8.5%/+5.0%@13:30", False, {"guard_hhmm": 1330, "guard_act": 1.085, "guard_stop": 1.050}),
        ("+8.5%/+5.0%@14:00", False, {"guard_hhmm": 1400, "guard_act": 1.085, "guard_stop": 1.050}),
    ])
    add_group("DimB_cutoff", "B12_threshold", "threshold", [
        (f">={v}{'(base)' if v == 90 else ''}", v == 90, {"threshold": v})
        for v in [88, 89, 90, 91, 92]
    ])
    return specs


def eval_one_cfg(pool_superset: pd.DataFrame, cfg: V20Config, exit_cache: dict) -> dict:
    """给定配置，在全量/IS/IS早晚/OOS/全五年上计算全口径单仓与等权指标"""
    ekey = (cfg.d4_open_tp, cfg.guard_hhmm, cfg.guard_act, cfg.guard_stop)
    rv, edv, ehv = exit_cache[ekey]

    mask_gate = (
        pool_superset["open_pct"].between(cfg.open_low, cfg.open_high).to_numpy()
        & (pool_superset["plate_sz"] < cfg.plate_sz_max).to_numpy()
    )
    sub = pool_superset[mask_gate].copy()
    sub["ret_c"] = np.asarray(rv, dtype=float)[mask_gate]
    sub["ed_c"] = np.asarray(edv, dtype=object)[mask_gate]
    sub["eh_c"] = np.asarray(ehv, dtype=int)[mask_gate]

    comp = compute_components_param(sub, cfg)
    sub["score"] = float(cfg.base_pts) + comp.sum(axis=1)
    cand_full = sub[sub["score"] >= cfg.threshold].copy()
    cand_5y = cand_full[cand_full["buy_date"] >= u.CANON_5Y_START].copy()

    led_full = u.sim_single_slot(cand_full, "score", "ret_c", "ed_c", "eh_c")
    led_5y = u.sim_single_slot(cand_5y, "score", "ret_c", "ed_c", "eh_c")

    def _slice(df_raw: pd.DataFrame, df_led: pd.DataFrame, sdt: str, edt: str):
        sr = df_raw[(df_raw["buy_date"] >= sdt) & (df_raw["buy_date"] <= edt)]
        sl = df_led[(df_led["buy_date"] >= sdt) & (df_led["buy_date"] <= edt)] if not df_led.empty else df_led
        return sr, sl

    sr_is, sl_is = _slice(cand_full, led_full, "2021-01-01", IS_END)
    sr_ise, sl_ise = _slice(cand_full, led_full, "2021-01-01", IS_EARLY_END)
    sr_isl, sl_isl = _slice(cand_full, led_full, IS_LATE_START, IS_END)
    sr_oos, sl_oos = _slice(cand_full, led_full, OOS_START, DATA_AS_OF)

    m_is = calc_quick_metrics(sr_is, sl_is, "ret_c")
    m_ise = calc_quick_metrics(sr_ise, sl_ise, "ret_c")
    m_isl = calc_quick_metrics(sr_isl, sl_isl, "ret_c")
    m_oos = calc_quick_metrics(sr_oos, sl_oos, "ret_c")
    m_5y = calc_quick_metrics(cand_5y, led_5y, "ret_c")

    return {
        "metrics": {
            "is_raw_n": m_is["raw_n"], "is_single_n": m_is["single_n"], "is_wr": m_is["wr"], "is_plr": m_is["plr"],
            "is_mean": m_is["mean"], "is_single_nav": m_is["single_nav"], "is_eq_nav": m_is["eq_nav"], "is_mdd": m_is["mdd"],
            "is_early_n": m_ise["single_n"], "is_early_wr": m_ise["wr"], "is_early_plr": m_ise["plr"], "is_early_mean": m_ise["mean"],
            "is_late_n": m_isl["single_n"], "is_late_wr": m_isl["wr"], "is_late_plr": m_isl["plr"], "is_late_mean": m_isl["mean"],
            "oos_raw_n": m_oos["raw_n"], "oos_single_n": m_oos["single_n"], "oos_wr": m_oos["wr"], "oos_plr": m_oos["plr"],
            "oos_mean": m_oos["mean"], "oos_single_nav": m_oos["single_nav"], "oos_eq_nav": m_oos["eq_nav"], "oos_mdd": m_oos["mdd"],
            "y5_raw_n": m_5y["raw_n"], "y5_single_n": m_5y["single_n"], "y5_wr": m_5y["wr"], "y5_plr": m_5y["plr"],
            "y5_mean": m_5y["mean"], "y5_single_nav": m_5y["single_nav"], "y5_eq_nav": m_5y["eq_nav"], "y5_mdd": m_5y["mdd"],
        },
        "cand_full": cand_full,
        "cand_5y": cand_5y,
        "led_full": led_full,
        "led_5y": led_5y,
    }


def select_is_plateau_candidates(is_only_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    严格防过拟合「高原双升筛选器」: 输入 DataFrame 物理剔除全部 oos_* 与 y5_* 列，仅凭 IS 与 IS早晚段做判断！
    """
    assert not any(c.startswith(("oos_", "y5_")) for c in is_only_df.columns), "LEAK GUARD: OOS/5Y column passed to IS selector!"

    base_row = is_only_df[is_only_df["is_baseline"]].iloc[0]
    b_n = float(base_row["is_single_n"])
    b_wr = float(base_row["is_wr"])
    b_plr = float(base_row["is_plr"])
    b_mean = float(base_row["is_mean"])
    b_e_mean = float(base_row["is_early_mean"])
    b_l_mean = float(base_row["is_late_mean"])
    min_n = math.ceil(0.85 * b_n)

    df = is_only_df.copy()
    df["pass_a"] = (
        (df["is_single_n"] >= min_n)
        & (df["is_wr"] >= b_wr - 1e-9)
        & (df["is_plr"] >= b_plr - 1e-9)
        & ((df["is_wr"] >= b_wr + 0.01) | (df["is_plr"] >= b_plr + 0.01))
    )
    df["pass_b"] = (
        (df["is_early_mean"] >= b_e_mean - 1e-9)
        & (df["is_late_mean"] >= b_l_mean - 1e-9)
    )

    pass_c_list = []
    for _, grp in df.groupby("group", sort=False):
        grp_s = grp.sort_values("grid_idx").reset_index()
        n_g = len(grp_s)
        for pos in range(n_g):
            row = grp_s.loc[pos]
            if row["is_baseline"]:
                pass_c_list.append((int(row["index"]), False))
                continue
            nbs = [grp_s.loc[j] for j in (pos - 1, pos + 1) if 0 <= j < n_g]
            no_cliff = all(
                (nb["is_single_n"] >= 0.75 * b_n)
                and (nb["is_wr"] >= b_wr - 4.0)
                and (nb["is_plr"] >= b_plr * 0.75)
                and (nb["is_mean"] >= b_mean * 0.75)
                for nb in nbs
            )
            non_base_nbs = [nb for nb in nbs if not nb["is_baseline"]]
            check_pool = non_base_nbs if non_base_nbs else nbs
            has_plateau_nb = any(
                (nb["is_single_n"] >= math.ceil(0.80 * b_n))
                and (nb["is_wr"] >= b_wr - 1.5)
                and (nb["is_plr"] >= b_plr * 0.90)
                and (nb["is_mean"] >= b_mean * 0.92)
                for nb in check_pool
            )
            pass_c_list.append((int(row["index"]), bool(no_cliff and has_plateau_nb)))

    pass_c_map = dict(pass_c_list)
    df["pass_c"] = [pass_c_map[i] for i in df.index]
    df["pass_abc"] = df["pass_a"] & df["pass_b"] & df["pass_c"]
    df["is_gain_score"] = (
        (df["is_wr"] - b_wr)
        + 10.0 * (df["is_plr"] - b_plr)
        + 2.0 * (df["is_mean"] - b_mean)
    )

    passing = df[df["pass_abc"]].sort_values("is_gain_score", ascending=False)
    ortho_selected = []
    seen_mechs = set()
    for r in passing.itertuples(index=False):
        if r.mech in seen_mechs:
            continue
        seen_mechs.add(r.mech)
        ortho_selected.append({
            "group": r.group, "mech": r.mech, "label": r.label,
            "patch": json.loads(r.patch_json),
            "is_single_n": int(r.is_single_n), "is_wr": float(r.is_wr), "is_plr": float(r.is_plr),
            "is_mean": float(r.is_mean), "is_early_mean": float(r.is_early_mean), "is_late_mean": float(r.is_late_mean),
            "is_gain_score": round(float(r.is_gain_score), 3),
        })

    info = {
        "base_is": {"single_n": int(b_n), "min_n_85pct": min_n, "wr": b_wr, "plr": b_plr, "mean": b_mean, "early_mean": b_e_mean, "late_mean": b_l_mean},
        "total_non_baseline_tested": int((~df["is_baseline"]).sum()),
        "count_pass_a": int(df["pass_a"].sum()),
        "count_pass_ab": int((df["pass_a"] & df["pass_b"]).sum()),
        "count_pass_abc": int(df["pass_abc"].sum()),
        "ortho_passing_candidates": ortho_selected,
        "runner_ups_ab_not_c": [
            {
                "group": r.group, "mech": r.mech, "label": r.label, "patch": json.loads(r.patch_json),
                "is_single_n": int(r.is_single_n), "is_wr": float(r.is_wr), "is_plr": float(r.is_plr),
                "is_mean": float(r.is_mean), "is_early_mean": float(r.is_early_mean), "is_late_mean": float(r.is_late_mean),
            }
            for r in df[df["pass_a"] & df["pass_b"] & (~df["pass_c"])].sort_values("is_gain_score", ascending=False).head(10).itertuples(index=False)
        ],
    }
    return df, info


def full_evaluation_bundle(
    name: str, cfg: V20Config, pool_superset: pd.DataFrame, exit_cache: dict,
    df_all: pd.DataFrame, csi: dict, sh300: dict, t_days: list
) -> dict:
    """产出 D15 七窗口对比、年度拆分、8项审计(含M=300/500) 与 组合协同"""
    ekey = (cfg.d4_open_tp, cfg.guard_hhmm, cfg.guard_act, cfg.guard_stop)
    rv, edv, ehv = exit_cache[ekey]
    mask_gate = (
        pool_superset["open_pct"].between(cfg.open_low, cfg.open_high).to_numpy()
        & (pool_superset["plate_sz"] < cfg.plate_sz_max).to_numpy()
    )
    sub = pool_superset[mask_gate].copy().reset_index(drop=True)
    sub["ret_c"] = np.asarray(rv, dtype=float)[mask_gate]
    sub["ed_c"] = np.asarray(edv, dtype=object)[mask_gate]
    sub["eh_c"] = np.asarray(ehv, dtype=int)[mask_gate]

    comp = compute_components_param(sub, cfg)
    sub["score"] = float(cfg.base_pts) + comp.sum(axis=1)

    mask_5y = (sub["buy_date"] >= u.CANON_5Y_START).to_numpy()
    sub_5y = sub[mask_5y].copy().reset_index(drop=True)
    comp_5y = comp[mask_5y]
    base_5y = df_all[df_all["buy_date"] >= u.CANON_5Y_START].copy()

    cand_full = sub[sub["score"] >= cfg.threshold].copy()
    cand_5y = sub_5y[sub_5y["score"] >= cfg.threshold].copy()
    led_full = u.sim_single_slot(cand_full, "score", "ret_c", "ed_c", "eh_c")
    led_5y = u.sim_single_slot(cand_5y, "score", "ret_c", "ed_c", "eh_c")

    win_specs = [
        ("IS_21_23", "2021-01-01", "2023-12-31", -34.16, False),
        ("OOS_24_26", "2024-01-01", DATA_AS_OF, csi["近三年(2024-01-01起)"][0], False),
        ("全五年_20211116起", "2021-11-16", DATA_AS_OF, csi["全五年(2021-11-16起)"][0], True),
        ("近三年_20231116起", "2023-11-16", DATA_AS_OF, csi["近三年(2023-11-16起)"][0], True),
        ("2026全年", "2026-01-01", DATA_AS_OF, csi["2026全年"][0], True),
        ("2026年7月起", "2026-07-01", DATA_AS_OF, csi["2026年7月以来"][0], True),
        ("2026年10月起", "2026-10-01", DATA_AS_OF, csi["2026年10月以来"][0], True),
    ]
    windows = {}
    for wn, sdt, edt, csip, u5 in win_specs:
        sa = cand_full[(cand_full["buy_date"] >= sdt) & (cand_full["buy_date"] <= edt)].copy()
        ws = led_5y if u5 else led_full
        ws = ws[(ws["buy_date"] >= sdt) & (ws["buy_date"] <= edt)]
        windows[wn] = calc_d15_window_metrics(sa, ws, csip, "ret_c", "ed_c", "eh_c")

    yearly = {}
    for y in range(2021, 2027):
        ys = str(y)
        ws = led_full[led_full["buy_date"].str.startswith(ys)]
        rr = ws["net_ret"].to_numpy(dtype=float) if not ws.empty else np.array([])
        yearly[ys] = u.calc_nav_cap10m(rr)

    audit8 = run_8tests_audit_m300(
        led_5y, sub_5y, comp_5y, base_5y, sh300, t_days,
        "score", cfg.threshold, "ret_c", "ed_c", "eh_c", cfg.base_pts, u.FACTOR_NAMES_V2, run_lofo=True
    )

    return {
        "name": name,
        "config": asdict(cfg),
        "windows_d15": windows,
        "yearly": yearly,
        "overfitting_8_tests_m300_m500": audit8,
        "led_full": led_full,
        "cand_5y": cand_5y,
    }


def run_truncation_check(cfg: V20Config, full_led: pd.DataFrame, da_trunc, b5m_trunc, df_trunc: pd.DataFrame) -> dict:
    """2024-12-31 物理截断零未来函数验证"""
    pool_t = df_trunc[
        (~df_trunc["has_reg_10d"])
        & df_trunc["open_pct"].between(cfg.open_low, cfg.open_high)
        & (df_trunc["plate_sz"] < cfg.plate_sz_max)
    ].copy().reset_index(drop=True)
    rv, edv, ehv = sim_v2_exit_param(
        pool_t, da_trunc, b5m_trunc,
        d4_open_tp=cfg.d4_open_tp, guard_hhmm=cfg.guard_hhmm,
        guard_act=cfg.guard_act, guard_stop=cfg.guard_stop,
        cutoff_date="2024-12-31"
    )
    pool_t["ret_c"], pool_t["ed_c"], pool_t["eh_c"] = rv, edv, ehv
    comp_t = compute_components_param(pool_t, cfg)
    pool_t["score"] = float(cfg.base_pts) + comp_t.sum(axis=1)
    t_led = u.sim_single_slot(pool_t[pool_t["score"] >= cfg.threshold], "score", "ret_c", "ed_c", "eh_c")

    f24 = full_led[full_led["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    t24 = t_led[t_led["exit_date"] <= "2024-12-31"].reset_index(drop=True)
    assert len(f24) == len(t24), f"Trunc len mismatch: {len(f24)} vs {len(t24)}"
    assert (f24["buy_date"] == t24["buy_date"]).all() and (f24["exit_date"] == t24["exit_date"]).all()
    assert (f24["code"] == t24["code"]).all()
    diff_sc = float(np.max(np.abs(f24["score"].to_numpy() - t24["score"].to_numpy())))
    diff_ret = float(np.max(np.abs(f24["net_ret"].to_numpy() - t24["net_ret"].to_numpy())))
    assert diff_sc == 0.0 and diff_ret == 0.0, f"Trunc diff != 0: score={diff_sc}, ret={diff_ret}"
    return {"trades_2021_2024": int(len(t24)), "max_abs_diff_score": diff_sc, "max_abs_diff_ret": diff_ret}


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    csi = json.load(open(u.CSI_CANON_JSON, encoding="utf-8"))
    sh300 = json.load(open(u.IDX_JSON, encoding="utf-8"))["sh000300"]
    t_days = sorted([d for d in sh300.keys() if u.CANON_5Y_START <= d <= DATA_AS_OF])

    raw_all, df_all, da, b5m, data_as_of_date = build_pit_dataset_ext(cutoff_date=None)

    # 超集信号池: 覆盖全部维度B硬门最大值 (open [-8.0%, +3.5%], plate_sz < 22)
    pool_superset = df_all[
        df_all["buyable_open"] & (~df_all["prev_is_yizi"]) & (~df_all["has_tox_90d"]) & (~df_all["has_reg_10d"])
        & df_all["open_pct"].between(-0.080, 0.035) & (df_all["plate_sz"] < 22)
    ].copy().reset_index(drop=True)

    # 校验基准与 upgrade_2to3_pit 100% 比特一致
    base_cfg = V20Config()
    gated_base = pool_superset[pool_superset["open_pct"].between(-0.065, 0.025) & (pool_superset["plate_sz"] < 15)].copy().reset_index(drop=True)
    assert np.array_equal(compute_components_param(gated_base, base_cfg), u.compute_v20_components(gated_base)), "Baseline component mismatch!"

    # 预计算全部唯一出场参数组合 (仅9组, 每组<0.4s)
    specs = build_grid_specs()
    exit_keys = sorted({(s["cfg"].d4_open_tp, s["cfg"].guard_hhmm, s["cfg"].guard_act, s["cfg"].guard_stop) for s in specs})
    exit_cache = {}
    for ek in exit_keys:
        exit_cache[ek] = sim_v2_exit_param(pool_superset, da, b5m, d4_open_tp=ek[0], guard_hhmm=ek[1], guard_act=ek[2], guard_stop=ek[3], cutoff_date=None)

    # 校验基准出场与 sim_v2_exit_all 100% 一致
    ref_rv, ref_ed, ref_eh = u.sim_v2_exit_all(gated_base, da, b5m, None)
    mask_b = (pool_superset["open_pct"].between(-0.065, 0.025) & (pool_superset["plate_sz"] < 15)).to_numpy()
    base_ek = (0.092, 1345, 1.085, 1.050)
    assert np.max(np.abs(np.asarray(exit_cache[base_ek][0])[mask_b] - np.asarray(ref_rv))) == 0.0, "Exit return mismatch vs sim_v2_exit_all!"
    assert list(np.asarray(exit_cache[base_ek][1])[mask_b]) == list(ref_ed), "Exit date mismatch!"
    assert list(np.asarray(exit_cache[base_ek][2])[mask_b]) == list(ref_eh), "Exit hhmm mismatch!"
    print(f"[VERIFIED] Baseline 100% bit-identical to upgrade_2to3_pit.py | superset={len(pool_superset)} | grid_specs={len(specs)}")

    # 1. 运行全量 Dim A + Dim B 左右波动扫描
    rows = []
    for sp in specs:
        res = eval_one_cfg(pool_superset, sp["cfg"], exit_cache)
        row = {
            "dim": sp["dim"],
            "group": sp["group"],
            "mech": sp["mech"],
            "grid_idx": sp["grid_idx"],
            "label": sp["label"],
            "is_baseline": sp["is_baseline"],
            "patch_json": json.dumps(sp["patch"], ensure_ascii=False),
            **res["metrics"],
        }
        rows.append(row)
    grid_df = pd.DataFrame(rows)

    # 2. 严格仅用 IS 列做「高原双升筛选」(物理剔除 oos_* 与 y5_* 列)
    is_only_cols = [c for c in grid_df.columns if not c.startswith(("oos_", "y5_"))]
    is_judged_df, is_sel_info = select_is_plateau_candidates(grid_df[is_only_cols])
    for col in ["pass_a", "pass_b", "pass_c", "pass_abc", "is_gain_score"]:
        grid_df[col] = is_judged_df[col]

    # 计算基准与各因子邻域高原度指标 (稳健带宽占比)
    base_is = is_sel_info["base_is"]
    plateau_diagnostics = {}
    for grp, gdf in grid_df.groupby("group", sort=False):
        gdf_s = gdf.sort_values("grid_idx")
        non_b = gdf_s[~gdf_s["is_baseline"]]
        # 稳健高原定义: 在IS内不出现断崖 (single_n >= 80% base, wr >= base-3pp, plr >= 0.85*base, mean >= 0.85*base)
        robust_cnt = int((
            (non_b["is_single_n"] >= 0.80 * base_is["single_n"])
            & (non_b["is_wr"] >= base_is["wr"] - 3.0)
            & (non_b["is_plr"] >= base_is["plr"] * 0.85)
            & (non_b["is_mean"] >= base_is["mean"] * 0.85)
        ).sum())
        is_wr_span = round(float(gdf_s["is_wr"].max() - gdf_s["is_wr"].min()), 2)
        is_plr_span = round(float(gdf_s["is_plr"].max() - gdf_s["is_plr"].min()), 2)
        is_mean_span = round(float(gdf_s["is_mean"].max() - gdf_s["is_mean"].min()), 2)
        plateau_diagnostics[grp] = {
            "dim": str(gdf_s["dim"].iloc[0]),
            "non_base_levels": int(len(non_b)),
            "is_robust_plateau_levels": robust_cnt,
            "is_wr_range_pp": is_wr_span,
            "is_plr_range": is_plr_span,
            "is_mean_range_pp": is_mean_span,
            "any_pass_abc": bool(gdf_s["pass_abc"].any()),
        }

    # 3.  Strictly in IS, assemble V2.1_plateau_cand (<= 4 orthogonal passing patches)
    ortho = is_sel_info["ortho_passing_candidates"]
    applied_patches = []
    cand_cfg = V20Config()
    if ortho:
        cur_is_wr, cur_is_plr, cur_is_n = base_is["wr"], base_is["plr"], base_is["single_n"]
        for cand_item in ortho:
            if len(applied_patches) >= 4:
                break
            trial_patch = {**cand_item["patch"]}
            # Check valid ordering for turn thresholds if combined
            test_cfg = replace(cand_cfg, **trial_patch)
            if not (test_cfg.turn_low < test_cfg.turn_mid < test_cfg.turn_high and test_cfg.open_low < test_cfg.open_high):
                continue
            tk = (test_cfg.d4_open_tp, test_cfg.guard_hhmm, test_cfg.guard_act, test_cfg.guard_stop)
            if tk not in exit_cache:
                exit_cache[tk] = sim_v2_exit_param(pool_superset, da, b5m, d4_open_tp=tk[0], guard_hhmm=tk[1], guard_act=tk[2], guard_stop=tk[3], cutoff_date=None)
            t_res = eval_one_cfg(pool_superset, test_cfg, exit_cache)["metrics"]
            # Must keep IS dual enhancement + early/late >= base + n >= 85% base
            keeps_dual = (
                t_res["is_single_n"] >= base_is["min_n_85pct"]
                and t_res["is_wr"] >= base_is["wr"] - 1e-9
                and t_res["is_plr"] >= base_is["plr"] - 1e-9
                and t_res["is_early_mean"] >= base_is["early_mean"] - 1e-9
                and t_res["is_late_mean"] >= base_is["late_mean"] - 1e-9
                and (
                    len(applied_patches) == 0
                    or (t_res["is_wr"] >= cur_is_wr - 0.5 and t_res["is_plr"] >= cur_is_plr - 0.05 and t_res["is_mean"] >= base_is["mean"])
                )
            )
            if keeps_dual:
                cand_cfg = test_cfg
                cur_is_wr, cur_is_plr, cur_is_n = t_res["is_wr"], t_res["is_plr"], t_res["is_single_n"]
                applied_patches.append(cand_item)

    has_v21 = len(applied_patches) > 0

    # 保存完整扫描矩阵 CSV (含 patch_json 与 pass_* 列)
    csv_path = f"{OUT_DIR}/perturbation_grid_all_factors.csv"
    grid_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # 4. 对 V2.0 与 V2.1_plateau_cand (若存在) 跑全套 D15 7窗口 + 8项审计(M=30/150/300/500) + 组合协同 + 2024-12-31 物理截断
    b_v20 = full_evaluation_bundle("V2.0_baseline", base_cfg, pool_superset, exit_cache, df_all, csi, sh300, t_days)

    _, df_trunc, da_trunc, b5m_trunc, _ = build_pit_dataset_ext(cutoff_date="2024-12-31")
    trunc_v20 = run_truncation_check(base_cfg, b_v20["led_full"], da_trunc, b5m_trunc, df_trunc)

    eval_bundles = {"V2.0_baseline": {k: v for k, v in b_v20.items() if k not in ("led_full", "cand_5y")}}
    trunc_results = {"V2.0_baseline": trunc_v20}

    oos_verdict = {}
    if has_v21:
        b_v21 = full_evaluation_bundle("V2.1_plateau_cand", cand_cfg, pool_superset, exit_cache, df_all, csi, sh300, t_days)
        trunc_v21 = run_truncation_check(cand_cfg, b_v21["led_full"], da_trunc, b5m_trunc, df_trunc)
        eval_bundles["V2.1_plateau_cand"] = {k: v for k, v in b_v21.items() if k not in ("led_full", "cand_5y")}
        trunc_results["V2.1_plateau_cand"] = trunc_v21

        v20_oos = b_v20["windows_d15"]["OOS_24_26"]
        v21_oos = b_v21["windows_d15"]["OOS_24_26"]
        v21_dsr300 = b_v21["overfitting_8_tests_m300_m500"]["test1_hlz_dsr"]["dsr_trade_prob"]["M300"]
        oos_dual_beat = (
            (v21_oos["win_rate_pct"] >= v20_oos["win_rate_pct"])
            and (v21_oos["plr"] >= v20_oos["plr"])
            and ((v21_oos["win_rate_pct"] > v20_oos["win_rate_pct"]) or (v21_oos["plr"] > v20_oos["plr"]))
            and (v21_oos["single_n"] >= math.ceil(0.85 * v20_oos["single_n"]))
        )
        oos_verdict = {
            "has_is_plateau_candidate": True,
            "applied_patches": applied_patches,
            "v20_oos": v20_oos,
            "v21_oos": v21_oos,
            "oos_dual_enhancement": bool(oos_dual_beat),
            "v21_dsr_M300": v21_dsr300,
            "v21_dsr_M300_ge_095": bool(v21_dsr300 >= 0.95),
            "honest_conclusion": (
                "V2.1_plateau_cand在OOS(2024~2026)实现了胜率与赔率真双升且DSR(M=300)>=0.95"
                if (oos_dual_beat and v21_dsr300 >= 0.95)
                else "虽然IS内选出了高原候选组合，但推入OOS(2024~2026)盲测未实现胜率与赔率真实双升(或DSR(M=300)<0.95)，维持V2.0为最优基准"
            ),
        }
    else:
        oos_verdict = {
            "has_is_plateau_candidate": False,
            "applied_patches": [],
            "honest_conclusion": "IS(2021~2023)严格早晚双段+邻域高原四条铁律下，无任何单变量改动实现真双升；V2.0当前参数已处于宽高原中心，维持V2.0最优",
        }

    # 如果还有 (a)+(b) 通过但未过 (c) 的边缘候选，也记录其单点对照仅供证伪说明 (绝不用于入选)
    summary = u.sanitize_json({
        "meta": {
            "experiment": "二进三 V2.0 全因子与连续截点左右波动高原寻优实验",
            "data_as_of_date": data_as_of_date,
            "is_window": "2021-01-04 ~ 2023-12-31",
            "is_early": "2021-01-04 ~ 2022-06-30",
            "is_late": "2022-07-01 ~ 2023-12-31",
            "oos_window": f"2024-01-01 ~ {data_as_of_date}",
            "canon_5y_window": f"{u.CANON_5Y_START} ~ {data_as_of_date}",
            "total_grid_rows": int(len(grid_df)),
            "total_groups": int(grid_df["group"].nunique()),
            "non_baseline_trials": int((~grid_df["is_baseline"]).sum()),
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "hard_guards": {
            "yfinance_forbidden": True,
            "sqlite_readonly_uri": True,
            "baseline_bit_identical_to_upgrade_2to3_pit": True,
            "truncation_2024_12_31_zero_lookahead": trunc_results,
        },
        "is_plateau_selection": is_sel_info,
        "plateau_stability_by_group": plateau_diagnostics,
        "oos_blind_verdict": oos_verdict,
        "strategies_d15_and_audit": eval_bundles,
    })

    json_path = f"{OUT_DIR}/summary_2to3_perturbation_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[DONE] grid_rows={len(grid_df)} | non_base={int((~grid_df['is_baseline']).sum())} | elapsed={time.time()-t0:.2f}s")
    print(f"IS selection: pass_a={is_sel_info['count_pass_a']}, pass_ab={is_sel_info['count_pass_ab']}, pass_abc={is_sel_info['count_pass_abc']}")
    print("Applied V2.1 patches:", [p["group"] + ":" + p["label"] for p in applied_patches])
    print("Verdict:", oos_verdict["honest_conclusion"])


if __name__ == "__main__":
    main()
