#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 3: Velocity-Slippage (0% / +0.5% / +1.0%) Portfolio Priority & Stock-Selection Re-Audit.
Strict IS (<= 2024-06-30) fitting -> frozen blind OOS (>= 2024-07-04) & 2026 (>= 2026-01-01).
Zero yfinance (D12); zero cap10m; reuses tier_priority_engine.py & complete untriggered pool.
"""

import itertools
import json
import math
import os
import sys
import time
import warnings
from typing import Callable, Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

warnings.filterwarnings("ignore", category=FutureWarning)
sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
PARTC_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partC_fine_tier_priority"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
V11_DIR = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
OUT_DIR = f"{SIM}/output/slippage_velocity_audit_20261125/part3_priority_and_selection"

if PARTC_DIR not in sys.path:
    sys.path.insert(0, PARTC_DIR)
import tier_priority_engine as tpe

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported by dependency"

START_DT = "2021-11-16"
END_DT = "2026-11-16"
IS_END = "2024-06-30"
OOS_START = "2024-07-04"
Y26_START = "2026-01-01"
NEAR3Y_START = "2023-11-16"

STRATS = ["3to4", "high", "pry", "2to3", "1to2", "20cm"]
ALL_TIERS_12 = [
    "3to4_S(>=102)", "3to4_A(90-101)",
    "high_S(>=96)", "high_A(88-95)",
    "pry_S(>=175)", "pry_A(165-174)",
    "2to3_S(>=96)", "2to3_A(90-95)",
    "1to2_S(>=340)", "1to2_A(304.8-339.9)", "1to2_FB(295-304.7)",
    "20cm_S(>=82)",
]

S2C_MAP = {
    "3to4_S(>=102)": 1, "3to4_A(90-101)": 1,
    "high_S(>=96)": 2, "high_A(88-95)": 2,
    "pry_S(>=175)": 3, "pry_A(165-174)": 3,
    "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
    "1to2_S(>=340)": 5, "1to2_A(304.8-339.9)": 5, "1to2_FB(295-304.7)": 5,
    "20cm_S(>=82)": 6, "20cm_A(76-81)": 999,
}
S3B_MAP = {
    "3to4_S(>=102)": 1, "3to4_A(90-101)": 1,
    "high_S(>=96)": 2, "high_A(88-95)": 2,
    "pry_S(>=175)": 3, "pry_A(165-174)": 3,
    "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
    "20cm_S(>=82)": 5,
    "1to2_S(>=340)": 6, "1to2_A(304.8-339.9)": 6, "1to2_FB(295-304.7)": 6,
    "20cm_A(76-81)": 999,
}
S2C_SWAP_2TO3_PRY = {**S2C_MAP, "2to3_S(>=96)": 3, "2to3_A(90-95)": 3, "pry_S(>=175)": 4, "pry_A(165-174)": 4}
S2C_INC_20A = {**S2C_MAP, "20cm_A(76-81)": 7}
S3B_INC_20A = {**S3B_MAP, "20cm_A(76-81)": 7}
SG1_12SPLIT = {
    "3to4_S(>=102)": 1, "3to4_A(90-101)": 1,
    "high_S(>=96)": 2, "high_A(88-95)": 2,
    "pry_S(>=175)": 3, "pry_A(165-174)": 3,
    "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
    "1to2_S(>=340)": 5, "20cm_S(>=82)": 6,
    "1to2_A(304.8-339.9)": 7, "1to2_FB(295-304.7)": 8,
    "20cm_A(76-81)": 999,
}
DIRECT_TOP_MAP = {
    "2to3_S(>=96)": 1, "2to3_A(90-95)": 1,
    "pry_S(>=175)": 2, "pry_A(165-174)": 2,
    "20cm_S(>=82)": 3,
    "1to2_S(>=340)": 4, "1to2_A(304.8-339.9)": 4, "1to2_FB(295-304.7)": 4,
    "3to4_S(>=102)": 5, "3to4_A(90-101)": 5,
    "high_S(>=96)": 6, "high_A(88-95)": 6,
    "20cm_A(76-81)": 999,
}


def strat_order_to_tier_map(order: tuple[str, ...] | list[str], include_20cm_a: bool = False) -> dict[str, int]:
    pmap: dict[str, int] = {}
    for idx, st in enumerate(order, 1):
        if st == "3to4":
            pmap["3to4_S(>=102)"] = idx
            pmap["3to4_A(90-101)"] = idx
        elif st == "high":
            pmap["high_S(>=96)"] = idx
            pmap["high_A(88-95)"] = idx
        elif st == "pry":
            pmap["pry_S(>=175)"] = idx
            pmap["pry_A(165-174)"] = idx
        elif st == "2to3":
            pmap["2to3_S(>=96)"] = idx
            pmap["2to3_A(90-95)"] = idx
        elif st == "1to2":
            pmap["1to2_S(>=340)"] = idx
            pmap["1to2_A(304.8-339.9)"] = idx
            pmap["1to2_FB(295-304.7)"] = idx
        elif st == "20cm":
            pmap["20cm_S(>=82)"] = idx
            pmap["20cm_A(76-81)"] = 7 if include_20cm_a else 999
    return pmap


def load_5m_and_prev_close(codes: set[str]) -> tuple[dict, dict]:
    """Load 5m bars (plus sub2 fallback) & daily prev_close / zt_px for velocity slippage."""
    import pickle
    m5 = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    m5["c6"] = m5["c6"].astype(str).str.zfill(6)
    m5["dt"] = m5["date"].astype(str).str[:10]
    m5 = m5[m5["c6"].isin(codes)].drop_duplicates(["c6", "dt", "hhmm_int"], keep="first")
    m5_lu = {
        (r.c6, r.dt, int(r.hhmm_int)): (float(r.open), float(r.high), float(r.low), float(r.close))
        for r in m5.itertuples(index=False)
    }
    sub2_p = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"
    if os.path.exists(sub2_p):
        sub2 = pickle.load(open(sub2_p, "rb"))
        for k, v in sub2.items():
            c6, dt = str(k[0]).zfill(6), str(k[2])[:10]
            if c6 in codes and isinstance(v, pd.DataFrame) and not v.empty:
                sub = v[v["date"] == dt]
                for r in sub.itertuples(index=False):
                    hh = int(str(r.hhmm).replace(":", ""))
                    if (c6, dt, hh) not in m5_lu:
                        m5_lu[(c6, dt, hh)] = (float(r.open), float(r.high), float(r.low), float(r.close))

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2021-10-01")
    da = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    db = pd.concat([da, dd], ignore_index=True)
    db["c6"] = db["ticker"].astype(str).str[:6]
    db = db[db["c6"].isin(codes)].copy()
    db["dt"] = db["date"].dt.strftime("%Y-%m-%d")
    db.sort_values(["c6", "dt"], inplace=True)
    db.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    db["adjf"] = np.where((db["close"] > 0) & (db["adj_close"] > 0), db["adj_close"] / db["close"], 1.0)
    g = db.groupby("c6")
    db["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / db["adjf"]
    lim = np.where(db["c6"].str.startswith(("300", "301", "688", "689")), 0.20, 0.10)
    db["zt_px"] = np.floor(db["prev_c_adj"] * (1.0 + lim) * 100.0 + 0.5) / 100.0
    daily_zt_lu = {(r.c6, r.dt): (float(r.prev_c_adj), float(r.zt_px), float(r.adjf)) for r in db.itertuples(index=False)}
    return m5_lu, daily_zt_lu


def apply_velocity_slippage(pool_df: pd.DataFrame, m5_lu: dict, daily_zt_lu: dict, strict_5m: bool = True) -> tuple[pd.DataFrame, dict]:
    """Apply exact 3-tier velocity slippage model (0% / +0.5% / +1.0%, zt capped)."""
    df = pool_df.copy()
    vel_tiers, nom_slips, eff_slips, zt_caps = [], [], [], []
    new_rets, new_bpx = [], []
    old_rets = df["net_ret"].to_numpy(float)
    fallback_cnt = 0

    for r in df.itertuples(index=False):
        hh = int(r.buy_hhmm)
        old_r = float(r.net_ret)
        bp_val = float(r.buy_price_val) if pd.notna(r.buy_price_val) else np.nan
        if hh == 925:
            vel_tiers.append("direct_0925")
            nom_slips.append(0.0)
            eff_slips.append(0.0)
            zt_caps.append(False)
            new_rets.append(old_r)
            new_bpx.append(bp_val)
            continue

        assert not r.is_adj_px, f"Unexpected adj px for intraday trade {r.strategy} {r.code} {r.buy_date}"
        b5 = m5_lu.get((r.code, r.buy_date, hh))
        dz = daily_zt_lu.get((r.code, r.buy_date))
        assert dz is not None, f"Missing daily bar for {(r.code, r.buy_date, hh)}"
        pre_c, zt_px, _ = dz
        trig_p = bp_val
        assert pre_c > 0 and zt_px > 0 and trig_p > 0
        if b5 is None:
            assert not strict_5m, f"Missing 5m bar for {(r.code, r.buy_date, hh)}"
            fallback_cnt += 1
            vt, slip = "fallback_75bps", 0.0075
        else:
            open_5m, high_5m, _, _ = b5
            is_fast = (high_5m >= zt_px - 0.01) or ((high_5m - trig_p) / trig_p >= 0.025) or ((high_5m - open_5m) / pre_c >= 0.040)
            is_med = (not is_fast) and (((high_5m - trig_p) / trig_p >= 0.010) or ((high_5m - open_5m) / pre_c >= 0.020))
            if is_fast:
                vt, slip = "fast_100bps", 0.010
            elif is_med:
                vt, slip = "med_50bps", 0.005
            else:
                vt, slip = "slow_0bps", 0.000

        eff_buy = min(trig_p * (1.0 + slip), zt_px)
        new_r = (1.0 + old_r) * (trig_p / eff_buy) - 1.0
        vel_tiers.append(vt)
        nom_slips.append(slip)
        eff_slips.append(eff_buy / trig_p - 1.0)
        zt_caps.append(eff_buy < trig_p * (1.0 + slip) - 1e-7)
        new_rets.append(new_r)
        new_bpx.append(eff_buy)

    df["old_net_ret"] = old_rets
    df["net_ret"] = new_rets
    df["orig_buy_price_val"] = df["buy_price_val"]
    df["buy_price_val"] = new_bpx
    df["vel_tier"] = vel_tiers
    df["nom_slip"] = nom_slips
    df["eff_slip"] = eff_slips
    df["zt_capped"] = zt_caps

    intr = df[df["buy_hhmm"] > 925]
    stats = {
        "total_signals": int(len(df)),
        "direct_0925_signals": int((df["buy_hhmm"] == 925).sum()),
        "intraday_gt925_signals": int(len(intr)),
        "vel_tier_counts": intr["vel_tier"].value_counts().to_dict(),
        "by_strategy": {
            st: {
                "n_intraday": int(len(g)),
                "vel_counts": g["vel_tier"].value_counts().to_dict(),
                "avg_eff_slip_bps": round(float(g["eff_slip"].mean() * 10000.0), 2),
                "zt_capped_cnt": int(g["zt_capped"].sum()),
                "old_mean_pct": round(float(g["old_net_ret"].mean() * 100.0), 2),
                "new_mean_pct": round(float(g["net_ret"].mean() * 100.0), 2),
                "old_solo_nav": round(float(np.prod(1.0 + g["old_net_ret"].to_numpy(float))), 3),
                "new_solo_nav": round(float(np.prod(1.0 + g["net_ret"].to_numpy(float))), 3),
            }
            for st, g in intr.groupby("strategy")
        },
    }
    return df, stats


class FastSlotEngine:
    """High-speed exact replica of tier_priority_engine slot + MTM daily series builder."""

    def __init__(self, pool_df: pd.DataFrame, untrig_df: pd.DataFrame, cal_dts: list[str], dt_to_idx: dict, bar_lu: dict):
        self.cal_dts = cal_dts
        self.dt_to_idx = dt_to_idx
        self.T = len(cal_dts)
        comb = pd.concat([pool_df, untrig_df], ignore_index=True) if (untrig_df is not None and not untrig_df.empty) else pool_df.copy()
        comb = comb.reset_index(drop=True)
        self.df = comb
        self.n = len(comb)

        self.buy_dates = comb["buy_date"].tolist()
        self.buy_hhmms = comb["buy_hhmm"].astype(int).tolist()
        self.exit_dates = comb["exit_date"].tolist()
        self.exit_hhmms = comb["exit_hhmm"].astype(int).tolist()
        self.strategies = comb["strategy"].tolist()
        self.tiers = comb["tier"].tolist()
        self.scores = comb["score"].astype(float).tolist()
        self.codes = comb["code"].tolist()
        self.names = comb["name"].tolist()
        self.net_rets = comb["net_ret"].astype(float).tolist()
        self.is_untrigs = comb["is_untrig"].astype(bool).tolist()

        # Precompute MTM daily multiplier slice per triggered row (matches tpe.build_daily_mtm_series)
        self.mtm_slices: list[Optional[tuple[int, np.ndarray]]] = [None] * self.n
        for idx, r in enumerate(comb.itertuples(index=False)):
            if r.is_untrig:
                continue
            bi = dt_to_idx.get(r.buy_date)
            ei = dt_to_idx.get(r.exit_date)
            if bi is None:
                continue
            bb = bar_lu.get((r.code, r.buy_date))
            if r.is_adj_px and pd.notna(r.buy_price_val):
                b_adj = float(r.buy_price_val)
            elif (not r.is_adj_px) and pd.notna(r.buy_price_val) and bb is not None:
                b_adj = float(r.buy_price_val) * bb[4]
            elif bb is not None:
                b_adj = bb[1] * bb[4]
            else:
                b_adj = 1.0
            if b_adj <= 0:
                b_adj = 1.0
            prev_v, last_c = b_adj, b_adj
            end_loop = ei if (ei is not None and ei > bi) else self.T
            mults = []
            for t in range(bi, end_loop):
                bt = bar_lu.get((r.code, cal_dts[t]))
                cur_c = (bt[1] * bt[4]) if bt else last_c
                if cur_c <= 0:
                    cur_c = last_c
                mults.append(cur_c / prev_v)
                prev_v, last_c = cur_c, cur_c
            if ei is not None and ei > bi:
                mults.append((b_adj * (1.0 + float(r.net_ret))) / prev_v)
            self.mtm_slices[idx] = (bi, np.array(mults, dtype=float))

        # Static sort key tail: (-score, buy_hhmm, code)
        self.neg_scores = [-s for s in self.scores]

    def run(
        self,
        prio_fn: Callable[[pd.DataFrame], np.ndarray],
        timing_mode: str,
        end_dt_filter: Optional[str] = None,
        reserve_tiers: Optional[set[str]] = None,
    ) -> tuple[list[int], np.ndarray, list[dict]]:
        prios = prio_fn(self.df)
        if timing_mode == "naive":
            use_ut = False
            phases = np.zeros(self.n, dtype=int)
        elif timing_mode == "reserve_all":
            use_ut = True
            phases = np.zeros(self.n, dtype=int)
        elif timing_mode == "s_tier_reserve_only":
            use_ut = True
            res_set = {"3to4_S(>=102)", "high_S(>=96)"}
            phases = np.array([0 if (hh == 925 or tr in res_set) else 1 for hh, tr in zip(self.buy_hhmms, self.tiers)], dtype=int)
        elif timing_mode == "confirmed_0925_first":
            use_ut = False
            phases = np.array([0 if hh == 925 else 1 for hh in self.buy_hhmms], dtype=int)
        elif timing_mode == "zero_reserve_direct_first":
            use_ut = True
            phases = np.array([0 if hh == 925 else 1 for hh in self.buy_hhmms], dtype=int)
        elif timing_mode == "custom_phase":
            use_ut = True
            res_set = reserve_tiers or set()
            phases = np.array([0 if (hh == 925 or tr in res_set) else 1 for hh, tr in zip(self.buy_hhmms, self.tiers)], dtype=int)
        else:
            raise ValueError(f"Unknown timing_mode: {timing_mode}")

        cand_idx = [
            i for i in range(self.n)
            if prios[i] < 999
            and (use_ut or not self.is_untrigs[i])
            and (end_dt_filter is None or self.buy_dates[i] <= end_dt_filter)
        ]
        cand_idx.sort(
            key=lambda i: (
                self.buy_dates[i],
                int(phases[i]),
                int(prios[i]),
                self.neg_scores[i],
                self.buy_hhmms[i],
                self.codes[i],
            )
        )

        taken_idx: list[int] = []
        waits: list[dict] = []
        cur_ed, cur_eh = "", 0
        for i in cand_idx:
            bd, bh = self.buy_dates[i], self.buy_hhmms[i]
            if (not cur_ed) or (bd > cur_ed) or (bd == cur_ed and bh > cur_eh):
                if self.is_untrigs[i]:
                    waits.append({
                        "buy_date": bd,
                        "wait_strategy": self.strategies[i],
                        "wait_tier": self.tiers[i],
                        "wait_code": self.codes[i],
                        "wait_name": self.names[i],
                        "wait_score": round(self.scores[i], 1),
                        "cancel_hhmm": self.exit_hhmms[i],
                        "wait_phase": int(phases[i]),
                        "wait_prio": int(prios[i]),
                    })
                    cur_ed, cur_eh = self.exit_dates[i], self.exit_hhmms[i]
                else:
                    taken_idx.append(i)
                    cur_ed, cur_eh = self.exit_dates[i], self.exit_hhmms[i]

        if end_dt_filter is not None:
            T_len = sum(1 for d in self.cal_dts if d <= end_dt_filter)
        else:
            T_len = self.T
        day_mult = np.ones(T_len, dtype=float)
        for i in taken_idx:
            sl = self.mtm_slices[i]
            if sl is None:
                continue
            bi, mults = sl
            if bi >= T_len:
                continue
            hi = min(bi + len(mults), T_len)
            day_mult[bi:hi] *= mults[: hi - bi]
        return taken_idx, day_mult - 1.0, waits

    def subset_df(self, taken_idx: list[int]) -> pd.DataFrame:
        cols = [
            "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
            "strategy", "tier", "score", "net_ret", "buy_price_val", "is_adj_px", "is_untrig",
        ]
        if not taken_idx:
            return pd.DataFrame(columns=cols)
        return self.df.iloc[taken_idx][cols].reset_index(drop=True)


def fast_window_stats(rets: np.ndarray, daily_r: np.ndarray) -> dict:
    T = len(daily_r)
    mtm_nav = float(np.prod(1.0 + daily_r)) if T > 0 else 1.0
    cum_d = np.cumprod(1.0 + daily_r)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    daily_mdd = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    sd = float(np.std(daily_r, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(daily_r) / sd * math.sqrt(tpe.TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (tpe.TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0
    tr_nav = float(np.prod(1.0 + rets)) if len(rets) else 1.0
    return {
        "n": int(len(rets)),
        "nav": tr_nav,
        "mtm_nav": mtm_nav,
        "daily_mdd_pct": daily_mdd,
        "daily_sharpe": sharpe,
        "daily_calmar": calmar,
        "cagr_pct": cagr,
    }


def full_window_metrics(
    eng: FastSlotEngine,
    taken_idx: list[int],
    daily_r: np.ndarray,
    sh300: dict,
    all_sh_dts: list[str],
    windows: list[tuple[str, str, str]],
) -> dict:
    df_tr = eng.subset_df(taken_idx)
    out = {}
    for wlbl, sdt, edt in windows:
        m = tpe.calc_window_metrics(df_tr, daily_r, eng.cal_dts, eng.dt_to_idx, sh300, all_sh_dts, sdt, edt)
        sub = df_tr[(df_tr["buy_date"] >= sdt) & (df_tr["buy_date"] <= edt)] if not df_tr.empty else pd.DataFrame()
        win_idx = [eng.dt_to_idx[d] for d in eng.cal_dts if sdt <= d <= edt]
        dr = daily_r[win_idx] if win_idx else np.zeros(1)
        T = len(dr)
        mtm_nav = float(np.prod(1.0 + dr))
        cagr = (mtm_nav ** (tpe.TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
        ex3 = 1.0
        if not sub.empty and len(sub) > 3:
            ex3 = float(np.prod(1.0 + np.sort(sub["net_ret"].to_numpy(float))[:-3]))
        m["cagr_pct"] = round(cagr, 2)
        m["ex_top3_nav"] = round(ex3, 4)
        out[wlbl] = m
    return out


def sweep_720_perms(
    eng: FastSlotEngine,
    timing_mode: str,
    sh300: dict,
    all_sh_dts: list[str],
    windows: list[tuple[str, str, str]],
) -> dict:
    """Evaluate all 720 strategy permutations: select strictly on IS (<=IS_END), evaluate blind on OOS & Y2026."""
    is_idx_end = sum(1 for d in eng.cal_dts if d <= IS_END)
    oos_win = [eng.dt_to_idx[d] for d in eng.cal_dts if OOS_START <= d <= END_DT]
    y26_win = [eng.dt_to_idx[d] for d in eng.cal_dts if Y26_START <= d <= END_DT]
    n3y_win = [eng.dt_to_idx[d] for d in eng.cal_dts if NEAR3Y_START <= d <= END_DT]

    tier_arr = np.array(eng.tiers, dtype=object)
    records = []
    for perm in itertools.permutations(STRATS):
        pmap = strat_order_to_tier_map(perm, include_20cm_a=False)
        prio_vec = pd.Series(tier_arr).map(pmap).fillna(999).to_numpy(dtype=int)
        t_idx, dr_full, _ = eng.run(lambda _df, _p=prio_vec: _p, timing_mode=timing_mode)

        is_rets = np.array([eng.net_rets[i] for i in t_idx if eng.buy_dates[i] <= IS_END], dtype=float)
        oos_rets = np.array([eng.net_rets[i] for i in t_idx if eng.buy_dates[i] >= OOS_START], dtype=float)
        y26_rets = np.array([eng.net_rets[i] for i in t_idx if eng.buy_dates[i] >= Y26_START], dtype=float)
        n3y_rets = np.array([eng.net_rets[i] for i in t_idx if eng.buy_dates[i] >= NEAR3Y_START], dtype=float)
        full_rets = np.array([eng.net_rets[i] for i in t_idx], dtype=float)

        st_is = fast_window_stats(is_rets, dr_full[:is_idx_end])
        st_oos = fast_window_stats(oos_rets, dr_full[oos_win])
        st_y26 = fast_window_stats(y26_rets, dr_full[y26_win])
        st_n3y = fast_window_stats(n3y_rets, dr_full[n3y_win])
        st_full = fast_window_stats(full_rets, dr_full)

        records.append({
            "order": ">".join(perm),
            "perm": list(perm),
            "pos": {st: idx + 1 for idx, st in enumerate(perm)},
            "is_n": st_is["n"], "is_nav": round(st_is["nav"], 3), "is_sharpe": round(st_is["daily_sharpe"], 4),
            "is_calmar": round(st_is["daily_calmar"], 2), "is_mdd": round(st_is["daily_mdd_pct"], 2),
            "oos_n": st_oos["n"], "oos_nav": round(st_oos["nav"], 3), "oos_sharpe": round(st_oos["daily_sharpe"], 4),
            "oos_calmar": round(st_oos["daily_calmar"], 2), "oos_mdd": round(st_oos["daily_mdd_pct"], 2),
            "y26_n": st_y26["n"], "y26_nav": round(st_y26["nav"], 3), "y26_sharpe": round(st_y26["daily_sharpe"], 4),
            "n3y_nav": round(st_n3y["nav"], 3),
            "full_nav": round(st_full["nav"], 2), "full_sharpe": round(st_full["daily_sharpe"], 4), "full_calmar": round(st_full["daily_calmar"], 2),
        })

    df_r = pd.DataFrame(records)
    s2c_str = "3to4>high>pry>2to3>1to2>20cm"
    s3b_str = "3to4>high>pry>2to3>20cm>1to2"
    swap23_str = "3to4>high>2to3>pry>1to2>20cm"
    df_sr = df_r.sort_values(["is_sharpe", "is_nav"], ascending=False).reset_index(drop=True)
    df_nv = df_r.sort_values(["is_nav", "is_sharpe"], ascending=False).reset_index(drop=True)
    df_cm = df_r.sort_values(["is_calmar", "is_sharpe"], ascending=False).reset_index(drop=True)

    def _find_rank(df_sorted: pd.DataFrame, ord_s: str) -> dict:
        sub = df_sorted[df_sorted["order"] == ord_s]
        if sub.empty:
            return {}
        rk = int(sub.index[0]) + 1
        row = sub.iloc[0].to_dict()
        row.pop("pos", None)
        row["is_rank_out_of_720"] = rk
        return row

    pos_stats = {}
    for st in STRATS:
        p_col = df_r["pos"].apply(lambda d, _s=st: d[_s])
        # Mean IS Sharpe & IS NAV when strategy is at position 1..6, plus corr(rank_idx, is_sharpe)
        pos_stats[st] = {
            "corr_earlier_pos_vs_is_sharpe": round(float(np.corrcoef(-p_col, df_r["is_sharpe"])[0, 1]), 4),
            "corr_earlier_pos_vs_is_nav": round(float(np.corrcoef(-p_col, np.log(df_r["is_nav"]))[0, 1]), 4),
            "top20_is_sharpe_mean_pos": round(float(df_sr.head(20)["pos"].apply(lambda d, _s=st: d[_s]).mean()), 2),
            "top20_is_nav_mean_pos": round(float(df_nv.head(20)["pos"].apply(lambda d, _s=st: d[_s]).mean()), 2),
            "is_sharpe_by_pos_1to6": {
                str(k): round(float(df_r[p_col == k]["is_sharpe"].mean()), 4) for k in range(1, 7)
            },
        }

    # Check pairwise direct vs intraday order preference inside top-20 IS Sharpe & all 720
    pair_checks = {}
    for a, b in [("2to3", "3to4"), ("20cm", "1to2"), ("20cm", "3to4"), ("pry", "3to4"), ("2to3", "pry"), ("2to3", "1to2"), ("20cm", "2to3")]:
        a_before_b = df_r["pos"].apply(lambda d, _a=a, _b=b: d[_a] < d[_b])
        pair_checks[f"{a}_before_{b}"] = {
            "mean_is_sharpe_yes": round(float(df_r[a_before_b]["is_sharpe"].mean()), 4),
            "mean_is_sharpe_no": round(float(df_r[~a_before_b]["is_sharpe"].mean()), 4),
            "mean_is_nav_yes": round(float(df_r[a_before_b]["is_nav"].mean()), 2),
            "mean_is_nav_no": round(float(df_r[~a_before_b]["is_nav"].mean()), 2),
            "mean_oos_sharpe_yes": round(float(df_r[a_before_b]["oos_sharpe"].mean()), 4),
            "mean_oos_sharpe_no": round(float(df_r[~a_before_b]["oos_sharpe"].mean()), 4),
            "top20_is_sharpe_cnt": int(df_sr.head(20)["pos"].apply(lambda d, _a=a, _b=b: d[_a] < d[_b]).sum()),
        }

    def _clean_rows(d_sub: pd.DataFrame) -> list[dict]:
        out_l = []
        for idx, r in d_sub.iterrows():
            d = r.to_dict()
            d.pop("pos", None)
            d["is_rank"] = int(idx) + 1
            out_l.append(d)
        return out_l

    return {
        "timing_mode": timing_mode,
        "top5_by_is_sharpe": _clean_rows(df_sr.head(5)),
        "top5_by_is_nav": _clean_rows(df_nv.head(5)),
        "top5_by_is_calmar": _clean_rows(df_cm.head(5)),
        "benchmarks_rank_by_is_sharpe": {
            "S2C": _find_rank(df_sr, s2c_str),
            "S3B": _find_rank(df_sr, s3b_str),
            "Swap2to3Pry": _find_rank(df_sr, swap23_str),
        },
        "benchmarks_rank_by_is_nav": {
            "S2C": _find_rank(df_nv, s2c_str),
            "S3B": _find_rank(df_nv, s3b_str),
            "Swap2to3Pry": _find_rank(df_nv, swap23_str),
        },
        "strategy_position_effects": pos_stats,
        "pairwise_dominance": pair_checks,
        "best_is_sharpe_perm": df_sr.iloc[0]["perm"],
        "best_is_nav_perm": df_nv.iloc[0]["perm"],
        "best_is_calmar_perm": df_cm.iloc[0]["perm"],
    }


def fit_strict_is_models(eng: FastSlotEngine, pool_df: pd.DataFrame, dt_to_idx: dict) -> dict:
    """Fit EB rankings & Coordinate Ascent strictly on IS (<= 2024-06-30, exit_date <= 2024-06-30)."""
    is_df = pool_df[pool_df["buy_date"] <= IS_END].copy()
    assert (is_df["exit_date"] <= IS_END).all(), "IS trade exits after IS_END!"
    is_df["hold_td"] = np.maximum(1, is_df["exit_date"].map(dt_to_idx) - is_df["buy_date"].map(dt_to_idx))
    is_df["log_ret"] = np.log1p(is_df["net_ret"])

    grand_lr = float(is_df["log_ret"].mean())
    grand_ht = float(is_df["hold_td"].mean())
    strat_priors = {}
    for st, grp in is_df.groupby("strategy"):
        n_s = len(grp)
        strat_priors[st] = (
            float((grp["log_ret"].sum() + 5.0 * grand_lr) / (n_s + 5.0)),
            float((grp["hold_td"].sum() + 5.0 * grand_ht) / (n_s + 5.0)),
        )

    eb_table = {}
    for t, grp in is_df.groupby("tier"):
        st = grp["strategy"].iloc[0]
        p_lr, p_ht = strat_priors[st]
        n_t = len(grp)
        k_t = 10.0
        eb_lr = float((grp["log_ret"].sum() + k_t * p_lr) / (n_t + k_t))
        eb_ht = float((grp["hold_td"].sum() + k_t * p_ht) / (n_t + k_t))
        raw_mn = float(grp["net_ret"].mean())
        raw_ht = float(grp["hold_td"].mean())
        eb_table[t] = {
            "n_is": int(n_t),
            "wr_is_pct": round(float((grp["net_ret"] > 0).mean() * 100.0), 2),
            "raw_mean_pct": round(raw_mn * 100.0, 2),
            "raw_daily_eff_pct": round((raw_mn / raw_ht) * 100.0, 2),
            "eb_trade_log_ret_pct": round(eb_lr * 100.0, 2),
            "eb_daily_eff_pct": round((eb_lr / eb_ht) * 100.0, 2),
            "eb_lr_val": eb_lr,
            "eb_eff_val": eb_lr / eb_ht,
            "raw_mn_val": raw_mn,
            "raw_eff_val": raw_mn / raw_ht,
        }

    tier_ser = pd.Series(eng.tiers, dtype=object)

    def eval_is(ord_list: list[str], metric: str, tmode: str, res_set: Optional[set[str]] = None) -> float:
        pm = {t: i + 1 for i, t in enumerate(ord_list)}
        pvec = tier_ser.map(pm).fillna(999).to_numpy(dtype=int)
        t_idx, dr, _ = eng.run(lambda _d, _p=pvec: _p, timing_mode=tmode, end_dt_filter=IS_END, reserve_tiers=res_set)
        if not t_idx:
            return -999.0
        rets = np.array([eng.net_rets[i] for i in t_idx], dtype=float)
        st = fast_window_stats(rets, dr)
        if metric == "nav":
            return st["nav"]
        if metric == "sharpe":
            return st["daily_sharpe"]
        return st["daily_calmar"]

    def run_ca(start_ord: list[str], metric: str, tmode: str) -> tuple[list[str], float, list[list[str]]]:
        cur = list(start_ord)
        best_v = eval_is(cur, metric, tmode)
        hist = [list(cur)]
        for _ in range(15):
            best_cand = None
            for i in range(len(cur)):
                for j in range(i + 1, len(cur)):
                    cand = list(cur)
                    cand[i], cand[j] = cand[j], cand[i]
                    v = eval_is(cand, metric, tmode)
                    if v > best_v + 1e-6:
                        best_v = v
                        best_cand = cand
            if best_cand is None:
                break
            cur = best_cand
            hist.append(list(cur))
        return cur, best_v, hist

    def run_joint_ca(start_ord: list[str], start_res: set[str], metric: str) -> tuple[list[str], list[str], float]:
        cur_ord = list(start_ord)
        cur_res = set(start_res)
        best_v = eval_is(cur_ord, metric, "custom_phase", cur_res)
        toggle_tiers = ["3to4_S(>=102)", "high_S(>=96)", "1to2_S(>=340)", "3to4_A(90-101)", "high_A(88-95)"]
        for _ in range(15):
            best_step = None
            for t in toggle_tiers:
                cand_res = set(cur_res)
                if t in cand_res:
                    cand_res.remove(t)
                else:
                    cand_res.add(t)
                v = eval_is(cur_ord, metric, "custom_phase", cand_res)
                if v > best_v + 1e-6:
                    best_v = v
                    best_step = (cur_ord, cand_res)
            for i in range(len(cur_ord)):
                for j in range(i + 1, len(cur_ord)):
                    cand_ord = list(cur_ord)
                    cand_ord[i], cand_ord[j] = cand_ord[j], cand_ord[i]
                    v = eval_is(cand_ord, metric, "custom_phase", cur_res)
                    if v > best_v + 1e-6:
                        best_v = v
                        best_step = (cand_ord, cur_res)
            if best_step is None:
                break
            cur_ord, cur_res = best_step
        return cur_ord, sorted(cur_res), best_v

    init_ord = [t for t in ALL_TIERS_12 if t in eb_table]
    ca_nav_naive, _, _ = run_ca(init_ord, "nav", "naive")
    ca_sr_naive, _, _ = run_ca(init_ord, "sharpe", "naive")
    ca_nav_stier, _, _ = run_ca(init_ord, "nav", "s_tier_reserve_only")
    ca_sr_stier, _, _ = run_ca(init_ord, "sharpe", "s_tier_reserve_only")
    ca_cal_stier, _, _ = run_ca(init_ord, "calmar", "s_tier_reserve_only")
    ca_j_ord_nav, ca_j_res_nav, _ = run_joint_ca(init_ord, {"3to4_S(>=102)", "high_S(>=96)"}, "nav")
    ca_j_ord_sr, ca_j_res_sr, _ = run_joint_ca(init_ord, {"3to4_S(>=102)", "high_S(>=96)"}, "sharpe")

    no20a = {k: v for k, v in eb_table.items() if k != "20cm_A(76-81)"}
    return {
        "eb_table": eb_table,
        "rank_raw_eff": [t for t, _ in sorted(no20a.items(), key=lambda x: x[1]["raw_eff_val"], reverse=True)],
        "rank_raw_mean": [t for t, _ in sorted(no20a.items(), key=lambda x: x[1]["raw_mn_val"], reverse=True)],
        "rank_eb_eff": [t for t, _ in sorted(no20a.items(), key=lambda x: x[1]["eb_eff_val"], reverse=True)],
        "rank_eb_lr": [t for t, _ in sorted(no20a.items(), key=lambda x: x[1]["eb_lr_val"], reverse=True)],
        "ca_nav_naive": ca_nav_naive,
        "ca_sharpe_naive": ca_sr_naive,
        "ca_nav_stier": ca_nav_stier,
        "ca_sharpe_stier": ca_sr_stier,
        "ca_calmar_stier": ca_cal_stier,
        "ca_joint_nav": {"order": ca_j_ord_nav, "reserve_tiers": ca_j_res_nav},
        "ca_joint_sharpe": {"order": ca_j_ord_sr, "reserve_tiers": ca_j_res_sr},
    }


def compute_trade_diffs(base_df: pd.DataFrame, cand_df: pd.DataFrame) -> dict:
    """Compute exact trade-level differences between candidate ledger and baseline P3_S2C_STierReserveOnly."""
    def _key_map(d: pd.DataFrame) -> dict[tuple, dict]:
        out = {}
        for r in d.itertuples(index=False):
            out[(r.buy_date, r.code, r.strategy)] = {
                "buy_date": r.buy_date, "exit_date": r.exit_date, "buy_hhmm": int(r.buy_hhmm),
                "strategy": r.strategy, "tier": r.tier, "code": r.code, "name": r.name,
                "score": round(float(r.score), 1), "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
                "net_ret": float(r.net_ret),
            }
        return out

    bm = _key_map(base_df)
    cm = _key_map(cand_df)
    dropped = [bm[k] for k in sorted(set(bm) - set(cm))]
    added = [cm[k] for k in sorted(set(cm) - set(bm))]

    by_dt_b: dict[str, list] = {}
    by_dt_c: dict[str, list] = {}
    for x in dropped:
        by_dt_b.setdefault(x["buy_date"], []).append(x)
    for x in added:
        by_dt_c.setdefault(x["buy_date"], []).append(x)
    all_diff_dts = sorted(set(by_dt_b) | set(by_dt_c))
    paired = []
    for dt in all_diff_dts:
        paired.append({
            "buy_date": dt,
            "window": "IS" if dt <= IS_END else ("OOS_2026" if dt >= Y26_START else ("OOS_2425" if dt >= OOS_START else "EMBARGO")),
            "dropped_from_v20": by_dt_b.get(dt, []),
            "added_in_cand": by_dt_c.get(dt, []),
        })

    def _win_summary(lst_d: list[dict], lst_a: list[dict], filt_fn) -> dict:
        sd = [x["net_ret"] for x in lst_d if filt_fn(x["buy_date"])]
        sa = [x["net_ret"] for x in lst_a if filt_fn(x["buy_date"])]
        nav_d = float(np.prod(1.0 + np.array(sd))) if sd else 1.0
        nav_a = float(np.prod(1.0 + np.array(sa))) if sa else 1.0
        return {
            "dropped_cnt": len(sd), "added_cnt": len(sa),
            "dropped_nav_mult": round(nav_d, 4), "added_nav_mult": round(nav_a, 4),
            "net_ratio": round(nav_a / nav_d, 4) if nav_d > 0 else 1.0,
        }

    return {
        "base_n": int(len(base_df)), "cand_n": int(len(cand_df)),
        "dropped_count": len(dropped), "added_count": len(added),
        "window_impact": {
            "IS": _win_summary(dropped, added, lambda d: d <= IS_END),
            "OOS": _win_summary(dropped, added, lambda d: d >= OOS_START),
            "Y2026": _win_summary(dropped, added, lambda d: d >= Y26_START),
            "FULL": _win_summary(dropped, added, lambda d: True),
        },
        "paired_events": paired,
    }


def eval_cscv_and_purged_cv(
    eng: FastSlotEngine,
    pool_df: pd.DataFrame,
    untrig_df: pd.DataFrame,
    cal_dts: list[str],
    dt_to_idx: dict,
    bar_lu: dict,
    daily_r_map: dict[str, np.ndarray],
    scheme_specs_for_cv: list[tuple[str, dict, str]],
) -> dict:
    """CSCV PBO (S=8, 10) + Purged 5-Fold Embargoed CV on velocity-slipped pool."""
    # CSCV PBO comparing candidate architectures against P3_S2C_STierReserveOnly
    names = list(daily_r_map.keys())
    R = np.column_stack([daily_r_map[n] for n in names])
    i_v20 = names.index("P3_S2C_STierReserveOnly")
    cscv = {}
    for S in (8, 10):
        gs = len(R) // S
        gidx = [list(range(i * gs, (i + 1) * gs if i < S - 1 else len(R))) for i in range(S)]
        omegas, beat_v20 = [], []
        win_cnt = {nm: 0 for nm in names}
        for te in itertools.combinations(range(S), S // 2):
            trg = [k for k in range(S) if k not in te]
            rt = R[[x for k in trg for x in gidx[k]]]
            re_ = R[[x for k in te for x in gidx[k]]]
            sdt, sde = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sdt, out=np.zeros_like(sdt), where=sdt > 1e-12)
            se = np.divide(re_.mean(0), sde, out=np.zeros_like(sde), where=sde > 1e-12)
            b = int(np.argmax(st))
            win_cnt[names[b]] += 1
            omegas.append(float(np.mean(se > se[b])))
            beat_v20.append(bool(se[b] >= se[i_v20]))
        om_arr = np.array(omegas)
        cscv[f"S{S}"] = {
            "combinations": len(omegas),
            "pbo_pct": round(float(np.mean(om_arr > 0.50) * 100.0), 2),
            "mean_omega": round(float(np.mean(om_arr)), 4),
            "is_winner_beat_v20_oos_pct": round(float(np.mean(beat_v20) * 100.0), 2),
            "is_winners": {k: v for k, v in win_cnt.items() if v > 0},
        }

    # Purged 5-fold CV
    df = pool_df.copy()
    df["b_idx"] = df["buy_date"].map(dt_to_idx)
    df["e_idx"] = df["exit_date"].map(dt_to_idx)
    T = len(cal_dts)
    step = T // 5
    folds = [(k * step, (k + 1) * step - 1 if k < 4 else T - 1) for k in range(5)]

    res_by_m: dict[str, list] = {nm: [] for nm, _, _ in scheme_specs_for_cv}
    res_by_m["P2B_EB_TradeRet_Refit_STier"] = []

    for fi, (fs, fe) in enumerate(folds, 1):
        tr_mask = (df["e_idx"] < fs) | (df["b_idx"] > fe + tpe.EMBARGO_DAYS)
        te_mask = (df["b_idx"] >= fs) & (df["b_idx"] <= fe)
        tr_df = df[tr_mask].copy()
        te_df = df[te_mask].copy()
        ut_te = untrig_df[untrig_df["buy_date"].between(cal_dts[fs], cal_dts[fe])].copy() if not untrig_df.empty else pd.DataFrame()

        tr_df["hold_td"] = np.maximum(1, tr_df["e_idx"] - tr_df["b_idx"])
        tr_df["log_ret"] = np.log1p(tr_df["net_ret"])
        gl, gh = float(tr_df["log_ret"].mean()), float(tr_df["hold_td"].mean())
        sp_l = {st: (g["log_ret"].sum() + 5.0 * gl) / (len(g) + 5.0) for st, g in tr_df.groupby("strategy")}
        eb_l = {t: (g["log_ret"].sum() + 10.0 * sp_l[g["strategy"].iloc[0]]) / (len(g) + 10.0) for t, g in tr_df.groupby("tier")}
        pm_eb_lr = {t: i + 1 for i, (t, _) in enumerate(sorted(eb_l.items(), key=lambda x: x[1], reverse=True)) if t != "20cm_A(76-81)"}

        f_eng = FastSlotEngine(te_df, ut_te, cal_dts, dt_to_idx, bar_lu)
        fold_list = list(scheme_specs_for_cv) + [("P2B_EB_TradeRet_Refit_STier", pm_eb_lr, "s_tier_reserve_only")]
        for nm, pmap, tmode in fold_list:
            pvec = pd.Series(f_eng.tiers, dtype=object).map(pmap).fillna(999).to_numpy(dtype=int)
            t_idx, dr_full, _ = f_eng.run(lambda _d, _p=pvec: _p, timing_mode=tmode)
            dr_f = dr_full[fs: fe + 1]
            rets = np.array([f_eng.net_rets[i] for i in t_idx], dtype=float)
            nav_f = float(np.prod(1.0 + rets)) if len(rets) else 1.0
            sd_f = float(np.std(dr_f, ddof=1)) if len(dr_f) > 1 else 0.0
            sr_f = float(np.mean(dr_f) / sd_f * math.sqrt(tpe.TRD_DAYS_YEAR)) if sd_f > 1e-12 else 0.0
            res_by_m[nm].append({"fold": fi, "n": int(len(rets)), "nav": round(nav_f, 3), "sharpe": round(sr_f, 3)})

    purged_summary = {}
    for nm, flist in res_by_m.items():
        navs = [x["nav"] for x in flist]
        srs = [x["sharpe"] for x in flist]
        purged_summary[nm] = {
            "mean_fold_sharpe": round(float(np.mean(srs)), 3),
            "prod_5fold_nav": round(float(np.prod(navs)), 2),
            "min_fold_nav": round(float(min(navs)), 3),
            "folds": flist,
        }
    return {"cscv": cscv, "purged_5fold_cv": purged_summary}


def run_suite_for_pool(
    label: str,
    pool_df: pd.DataFrame,
    untrig_df: pd.DataFrame,
    cal_dts: list[str],
    dt_to_idx: dict,
    bar_lu: dict,
    sh300: dict,
    all_sh_dts: list[str],
    windows: list[tuple[str, str, str]],
    run_720: bool = True,
) -> dict:
    eng = FastSlotEngine(pool_df, untrig_df, cal_dts, dt_to_idx, bar_lu)

    # Assert exact parity with tier_priority_engine on P3_S2C_STierReserveOnly
    ref_tr, _ = tpe.run_single_slot(pool_df, lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode="s_tier_reserve_only")
    ref_dr, ref_diff = tpe.build_daily_mtm_series(ref_tr, cal_dts, dt_to_idx, bar_lu)
    fast_idx, fast_dr, _ = eng.run(lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), timing_mode="s_tier_reserve_only")
    fast_df = eng.subset_df(fast_idx)
    assert len(ref_tr) == len(fast_df), f"[{label}] Parity len mismatch {len(ref_tr)} vs {len(fast_df)}"
    assert (ref_tr["code"].to_numpy() == fast_df["code"].to_numpy()).all(), f"[{label}] Parity code mismatch"
    assert np.max(np.abs(ref_tr["net_ret"].to_numpy() - fast_df["net_ret"].to_numpy())) < 1e-12
    assert np.max(np.abs(ref_dr - fast_dr)) < 1e-10, f"[{label}] MTM daily parity diff={np.max(np.abs(ref_dr - fast_dr))}"
    assert ref_diff < 1e-3, f"[{label}] MTM nav reconciliation diff={ref_diff}"

    is_fit = fit_strict_is_models(eng, pool_df, dt_to_idx)

    perm_720 = {}
    if run_720:
        for tm in ("naive", "reserve_all", "s_tier_reserve_only"):
            perm_720[tm] = sweep_720_perms(eng, tm, sh300, all_sh_dts, windows)

    def _l2m(ord_list: list[str]) -> dict:
        return {t: i + 1 for i, t in enumerate(ord_list)}

    specs = [
        ("P3_S2C_STierReserveOnly", "现行V20.0：S2C + 仅3to4_S/high_S占位", S2C_MAP, "s_tier_reserve_only", None),
        ("P3_ZeroReserve_AllDirectFirst", "零预占：全09:25直买优于全部盘中单（含phase1未触发挡低顺位）", S2C_MAP, "zero_reserve_direct_first", None),
        ("P3_ZeroReserve_AllDirectFirst_NoUT", "零预占（tpe原版confirmed_0925_first无未触发池）", S2C_MAP, "confirmed_0925_first", None),
        ("P3_ZeroReserve_20cmAbove1to2", "零预占 + 20cm_S82压1to2", S3B_MAP, "zero_reserve_direct_first", None),
        ("P3_ZeroReserve_DirectOrder_2to3Top", "零预占 + 直买内2to3>pry>20cm_S82>1to2>3to4>high", DIRECT_TOP_MAP, "zero_reserve_direct_first", None),
        ("P3_Only3to4SReserve", "仅3to4_S占位，high_S让位09:25直买", S2C_MAP, "custom_phase", {"3to4_S(>=102)"}),
        ("P3_Swap_20cm_Above_1to2", "S3B：20cm_S82压1to2（含1to2周一09:25）+ S档占位", S3B_MAP, "s_tier_reserve_only", None),
        ("P3_Swap_2to3_Above_Pry", "S2C调顺位：2to3压pry + S档占位", S2C_SWAP_2TO3_PRY, "s_tier_reserve_only", None),
        ("P3_Include_20cmA76", "S2C + 加入20cm_A(76-81)垫底第7顺位 + S档占位", S2C_INC_20A, "s_tier_reserve_only", None),
        ("P3_ZeroReserve_Include_20cmA76", "零预占 + 加入20cm_A(76-81)第7顺位", S2C_INC_20A, "zero_reserve_direct_first", None),
        ("P3_Include_20cmA76_Above1to2", "S3B + 加入20cm_A(76-81)第7顺位 + S档占位", S3B_INC_20A, "s_tier_reserve_only", None),
        ("P3_1to2Split_STierRes", "1to2_S>=340 > 20cm_S82 > 1to2_A/FB + S档占位", SG1_12SPLIT, "s_tier_reserve_only", None),
        ("P3_S2C_ReserveAll", "S2C全盘中条件单占位（含A档未触发等待）", S2C_MAP, "reserve_all", None),
        ("P3_S3B_ReserveAll", "S3B全盘中条件单占位（20cm压1to2）", S3B_MAP, "reserve_all", None),
        ("C1_S2C_Naive", "粗排S2C（仅已触发信号）", S2C_MAP, "naive", None),
        ("C2_S3B_Naive", "粗排S3B（仅已触发信号）", S3B_MAP, "naive", None),
        ("IS_EB_DailyEff_STierRes", "IS拟合：经验贝叶斯日均效率 + S档占位", _l2m(is_fit["rank_eb_eff"]), "s_tier_reserve_only", None),
        ("IS_EB_TradeRet_STierRes", "IS拟合：经验贝叶斯单笔对数期望 + S档占位", _l2m(is_fit["rank_eb_lr"]), "s_tier_reserve_only", None),
        ("CA_IS_NAV_Naive", "IS坐标上升：Naive优化IS_NAV", _l2m(is_fit["ca_nav_naive"]), "naive", None),
        ("CA_IS_NAV_STierRes", "IS坐标上升：STierRes优化IS_NAV", _l2m(is_fit["ca_nav_stier"]), "s_tier_reserve_only", None),
        ("CA_IS_Sharpe_STierRes", "IS坐标上升：STierRes优化IS_Sharpe", _l2m(is_fit["ca_sharpe_stier"]), "s_tier_reserve_only", None),
        ("CA_IS_Calmar_STierRes", "IS坐标上升：STierRes优化IS_Calmar", _l2m(is_fit["ca_calmar_stier"]), "s_tier_reserve_only", None),
        ("CA_IS_JointPhase_NAV", "IS联合坐标上升：优化顺位+S档是否占位(NAV)", _l2m(is_fit["ca_joint_nav"]["order"]), "custom_phase", set(is_fit["ca_joint_nav"]["reserve_tiers"])),
        ("CA_IS_JointPhase_Sharpe", "IS联合坐标上升：优化顺位+S档是否占位(Sharpe)", _l2m(is_fit["ca_joint_sharpe"]["order"]), "custom_phase", set(is_fit["ca_joint_sharpe"]["reserve_tiers"])),
    ]
    if run_720:
        specs.extend([
            ("Perm720_IS_Sharpe_Best_STierRes", f"720粗排IS_Sharpe冠军(STierRes): {'>'.join(perm_720['s_tier_reserve_only']['best_is_sharpe_perm'])}", strat_order_to_tier_map(perm_720["s_tier_reserve_only"]["best_is_sharpe_perm"]), "s_tier_reserve_only", None),
            ("Perm720_IS_NAV_Best_STierRes", f"720粗排IS_NAV冠军(STierRes): {'>'.join(perm_720['s_tier_reserve_only']['best_is_nav_perm'])}", strat_order_to_tier_map(perm_720["s_tier_reserve_only"]["best_is_nav_perm"]), "s_tier_reserve_only", None),
            ("Perm720_IS_Sharpe_Best_ReserveAll", f"720粗排IS_Sharpe冠军(ReserveAll): {'>'.join(perm_720['reserve_all']['best_is_sharpe_perm'])}", strat_order_to_tier_map(perm_720["reserve_all"]["best_is_sharpe_perm"]), "reserve_all", None),
            ("Perm720_IS_Sharpe_Best_Naive", f"720粗排IS_Sharpe冠军(Naive): {'>'.join(perm_720['naive']['best_is_sharpe_perm'])}", strat_order_to_tier_map(perm_720["naive"]["best_is_sharpe_perm"]), "naive", None),
        ])

    tier_ser = pd.Series(eng.tiers, dtype=object)
    schemes_out = {}
    daily_r_map = {}
    ledgers_map = {}

    for sid, desc, pmap, tmode, res_set in specs:
        pvec = tier_ser.map(pmap).fillna(999).to_numpy(dtype=int)
        t_idx, dr_full, waits = eng.run(lambda _d, _p=pvec: _p, timing_mode=tmode, reserve_tiers=res_set)
        df_tr = eng.subset_df(t_idx)
        daily_r_map[sid] = dr_full
        ledgers_map[sid] = df_tr
        wm = full_window_metrics(eng, t_idx, dr_full, sh300, all_sh_dts, windows)
        strat_breakdown = {}
        for st, g in df_tr.groupby("strategy"):
            rets = g["net_ret"].to_numpy(float)
            strat_breakdown[st] = {
                "n": int(len(rets)),
                "wr_pct": round(float((rets > 0).mean() * 100.0), 2),
                "mean_pct": round(float(rets.mean() * 100.0), 2),
                "solo_nav": round(float(np.prod(1.0 + rets)), 3),
            }
        schemes_out[sid] = {
            "desc": desc,
            "timing_mode": tmode,
            "metrics": wm,
            "by_strategy": df_tr["strategy"].value_counts().to_dict(),
            "by_tier": df_tr["tier"].value_counts().to_dict(),
            "strategy_breakdown": strat_breakdown,
            "untrig_wait_count": len(waits),
        }

    base_df = ledgers_map["P3_S2C_STierReserveOnly"]
    diffs = {}
    for sid in [
        "P3_ZeroReserve_AllDirectFirst", "P3_ZeroReserve_AllDirectFirst_NoUT",
        "P3_Only3to4SReserve", "P3_Swap_20cm_Above_1to2", "P3_Swap_2to3_Above_Pry",
        "P3_Include_20cmA76", "P3_1to2Split_STierRes", "CA_IS_NAV_STierRes", "CA_IS_Sharpe_STierRes",
    ]:
        if sid in ledgers_map:
            diffs[sid] = compute_trade_diffs(base_df, ledgers_map[sid])
    if run_720:
        for sid in ["Perm720_IS_Sharpe_Best_STierRes", "Perm720_IS_NAV_Best_STierRes", "Perm720_IS_Sharpe_Best_ReserveAll"]:
            diffs[sid] = compute_trade_diffs(base_df, ledgers_map[sid])

    cv_keys = [
        "P3_S2C_STierReserveOnly", "P3_ZeroReserve_AllDirectFirst",
        "P3_Swap_20cm_Above_1to2", "P3_Swap_2to3_Above_Pry",
        "P3_Include_20cmA76", "CA_IS_NAV_STierRes", "CA_IS_Sharpe_STierRes",
    ]
    cv_specs = [
        ("P3_S2C_STierReserveOnly", S2C_MAP, "s_tier_reserve_only"),
        ("P3_ZeroReserve_AllDirectFirst", S2C_MAP, "zero_reserve_direct_first"),
        ("P3_Swap_20cm_Above_1to2", S3B_MAP, "s_tier_reserve_only"),
        ("P3_Swap_2to3_Above_Pry", S2C_SWAP_2TO3_PRY, "s_tier_reserve_only"),
        ("P3_Include_20cmA76", S2C_INC_20A, "s_tier_reserve_only"),
    ]
    cv_out = eval_cscv_and_purged_cv(
        eng, pool_df, untrig_df, cal_dts, dt_to_idx, bar_lu,
        {k: daily_r_map[k] for k in cv_keys},
        cv_specs,
    )

    return {
        "label": label,
        "is_fitted_models": is_fit,
        "perm_720": perm_720,
        "schemes": schemes_out,
        "trade_diffs_vs_v20": diffs,
        "overfitting_audits": cv_out,
    }


def build_tier_vel_profiles(pool_base: pd.DataFrame, pool_vs: pd.DataFrame) -> dict:
    """Compare solo tier performance (No-Slip vs Vel-Slip) across IS / OOS / Y2026 / FULL."""
    out = {}
    wins = [("IS", lambda d: d <= IS_END), ("OOS", lambda d: d >= OOS_START), ("Y2026", lambda d: d >= Y26_START), ("FULL", lambda d: True)]
    for t in sorted(pool_base["tier"].unique()):
        out[t] = {}
        sb = pool_base[pool_base["tier"] == t]
        sv = pool_vs[pool_vs["tier"] == t]
        for wlbl, fn in wins:
            mb = sb[sb["buy_date"].apply(fn)]
            mv = sv[sv["buy_date"].apply(fn)]
            rb = mb["net_ret"].to_numpy(float)
            rv = mv["net_ret"].to_numpy(float)
            if len(rb) == 0:
                out[t][wlbl] = {"n": 0}
                continue
            out[t][wlbl] = {
                "n": int(len(rb)),
                "base_wr_pct": round(float((rb > 0).mean() * 100.0), 2),
                "base_mean_pct": round(float(rb.mean() * 100.0), 2),
                "base_nav": round(float(np.prod(1.0 + rb)), 3),
                "vel_wr_pct": round(float((rv > 0).mean() * 100.0), 2),
                "vel_mean_pct": round(float(rv.mean() * 100.0), 2),
                "vel_nav": round(float(np.prod(1.0 + rv)), 3),
                "avg_eff_slip_bps": round(float(mv["eff_slip"].mean() * 10000.0), 1),
            }
    return out


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    windows = [
        ("FULL", START_DT, END_DT),
        ("Near3Y", NEAR3Y_START, END_DT),
        ("IS", START_DT, IS_END),
        ("OOS", OOS_START, END_DT),
        ("Y2026", Y26_START, END_DT),
    ]

    csv_v20 = dict(tpe.DEFAULT_CSVS)
    csv_v20["1to2"] = f"{PARTA_DIR}/ledger_1to2_v20_cand.csv"
    csv_s82 = dict(csv_v20)
    csv_s82["20cm"] = f"{V11_DIR}/final_v11_ledger_S82.csv"

    pool6_base = pd.concat([tpe.load_strategy_csv(st, p, START_DT, END_DT) for st, p in csv_v20.items()], ignore_index=True)
    pool_s82_base = pd.concat([tpe.load_strategy_csv(st, p, START_DT, END_DT) for st, p in csv_s82.items()], ignore_index=True)
    top1_base = tpe.load_full_top1_cross_check(START_DT, END_DT)
    untrig_df = tpe.build_untriggered_baseline_pool(pool6_base, START_DT, END_DT)

    all_codes = set(pool6_base["code"]) | set(pool_s82_base["code"]) | set(top1_base["code"])
    sh300, bar_lu, all_sh_dts = tpe.load_daily_bars(all_codes)
    cal_dts = [d for d in all_sh_dts if START_DT <= d <= END_DT]
    dt_to_idx = {d: i for i, d in enumerate(cal_dts)}
    m5_lu, daily_zt_lu = load_5m_and_prev_close(all_codes)

    pool6_vs, vel_stats_pool6 = apply_velocity_slippage(pool6_base, m5_lu, daily_zt_lu, strict_5m=True)
    pool_s82_vs, _ = apply_velocity_slippage(pool_s82_base, m5_lu, daily_zt_lu, strict_5m=True)
    top1_vs, vel_stats_top1 = apply_velocity_slippage(top1_base, m5_lu, daily_zt_lu, strict_5m=False)

    # Check V20.0 exact 69,134,091.1x parity on baseline
    b_tr, _ = tpe.run_single_slot(pool6_base, lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), untrig_df=untrig_df, timing_mode="s_tier_reserve_only")
    assert len(b_tr) == 278 and abs(float(np.prod(1.0 + b_tr["net_ret"])) - 69134091.1181) < 1.0, "Baseline V20 parity failed"

    tier_profiles = build_tier_vel_profiles(pool6_base, pool6_vs)
    res_base = run_suite_for_pool("baseline_no_extra_slip", pool6_base, untrig_df, cal_dts, dt_to_idx, bar_lu, sh300, all_sh_dts, windows, run_720=True)
    res_vs = run_suite_for_pool("velocity_slippage", pool6_vs, untrig_df, cal_dts, dt_to_idx, bar_lu, sh300, all_sh_dts, windows, run_720=True)
    res_s82_vs = run_suite_for_pool("pure_s82_vel_slip", pool_s82_vs, untrig_df, cal_dts, dt_to_idx, bar_lu, sh300, all_sh_dts, windows, run_720=False)
    untrig_top1 = tpe.build_untriggered_baseline_pool(top1_vs, START_DT, END_DT)
    res_top1_vs = run_suite_for_pool("top1_unfiltered_vel_slip", top1_vs, untrig_top1, cal_dts, dt_to_idx, bar_lu, sh300, all_sh_dts, windows, run_720=False)

    # Also compute V20 legacy window (IS <= 2024-08-31 / OOS >= 2024-09-01) for P3_S2C_STierReserveOnly comparison
    legacy_wins = [("IS_0831", START_DT, "2024-08-31"), ("OOS_0901", "2024-09-01", END_DT)]
    legacy_cmp = {}
    for lbl, p_in in [("baseline", pool6_base), ("velocity_slippage", pool6_vs)]:
        eng_tmp = FastSlotEngine(p_in, untrig_df, cal_dts, dt_to_idx, bar_lu)
        ti, dr, _ = eng_tmp.run(lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), timing_mode="s_tier_reserve_only")
        legacy_cmp[lbl] = full_window_metrics(eng_tmp, ti, dr, sh300, all_sh_dts, legacy_wins)

    # Check velocity-slip details inside executed V20 portfolio
    eng_vs = FastSlotEngine(pool6_vs, untrig_df, cal_dts, dt_to_idx, bar_lu)
    v20_ti, _, _ = eng_vs.run(lambda d: d["tier"].map(S2C_MAP).fillna(999).to_numpy(), timing_mode="s_tier_reserve_only")
    v20_exec = eng_vs.df.iloc[v20_ti]
    v20_exec_intr = v20_exec[v20_exec["buy_hhmm"] > 925]
    v20_vel_exec = {
        "n_total": int(len(v20_exec)),
        "n_direct_0925": int((v20_exec["buy_hhmm"] == 925).sum()),
        "n_intraday_gt925": int(len(v20_exec_intr)),
        "intraday_vel_counts": v20_exec_intr["vel_tier"].value_counts().to_dict(),
        "intraday_by_strategy": {
            st: {
                "n_intraday": int(len(g)),
                "vel_counts": g["vel_tier"].value_counts().to_dict(),
                "avg_eff_slip_bps": round(float(g["eff_slip"].mean() * 10000.0), 1),
                "old_mean_pct": round(float(g["old_net_ret"].mean() * 100.0), 2),
                "new_mean_pct": round(float(g["net_ret"].mean() * 100.0), 2),
            }
            for st, g in v20_exec_intr.groupby("strategy")
        },
    }

    out_obj = tpe.sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "windows": {w: f"{s}~{e}" for w, s, e in windows},
            "csi300_returns_pct": {w: round(tpe.get_csi_ret(sh300, all_sh_dts, s, e), 2) for w, s, e in windows},
            "input_csvs": csv_v20,
            "untriggered_counts": untrig_df["strategy"].value_counts().to_dict(),
        },
        "velocity_slippage_audit": {
            "pool6": vel_stats_pool6,
            "top1_pool": vel_stats_top1,
            "executed_v20_portfolio": v20_vel_exec,
        },
        "solo_tier_profiles_base_vs_vel": tier_profiles,
        "legacy_is0831_oos0901_p3_s2c": legacy_cmp,
        "baseline_no_extra_slip": res_base,
        "velocity_slippage": res_vs,
        "robustness_pure_s82_vel_slip": res_s82_vs,
        "robustness_top1_unfiltered_vel_slip": res_top1_vs,
    })

    out_json = f"{OUT_DIR}/part3_priority_summary.json"
    raw_txt = json.dumps(out_obj, ensure_ascii=False, indent=2)
    assert "yfinance" not in sys.modules, "D12 violation"
    assert "cap10m" not in raw_txt and "1000万" not in raw_txt, "Forbidden cap10m text"
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(raw_txt)

    print(f"[DONE in {time.time() - t0:.2f}s] Saved -> {out_json}")
    for tag, suite in [("BASE", res_base), ("VEL_SLIP", res_vs)]:
        print(f"\n=== {tag} KEY SCHEMES ===")
        for sid in [
            "P3_S2C_STierReserveOnly", "P3_ZeroReserve_AllDirectFirst", "P3_Only3to4SReserve",
            "P3_Swap_20cm_Above_1to2", "P3_Swap_2to3_Above_Pry", "P3_Include_20cmA76",
            "P3_1to2Split_STierRes", "CA_IS_NAV_STierRes", "CA_IS_Sharpe_STierRes",
            "CA_IS_JointPhase_Sharpe", "Perm720_IS_Sharpe_Best_STierRes", "Perm720_IS_NAV_Best_STierRes",
        ]:
            m = suite["schemes"][sid]["metrics"]
            print(f"  {sid:32s} | FULL={m['FULL']['nav']:10,.1f}x Ex5={m['FULL']['ex_top5_nav']:8,.1f}x SR={m['FULL']['daily_sharpe']:4.3f} | IS={m['IS']['nav']:7,.1f}x SR={m['IS']['daily_sharpe']:4.3f} | OOS={m['OOS']['nav']:6,.1f}x SR={m['OOS']['daily_sharpe']:4.3f} | Y26={m['Y2026']['nav']:5.2f}x")


if __name__ == "__main__":
    main()
