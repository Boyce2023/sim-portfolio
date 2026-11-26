#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD042 Step 1: Track A — 近端次新股无套牢盘博弈 (A1 首板分歧承接 / A2 破位连跌缩量反抽 / A3 横盘突破新高次日承接)
Covers list_age 6..30 (core) and 6..60 (extended), strictly excluding days 1..5 no-limit noise.
Runs Blind Matrix (x6 exits x 30/50/80bps) + Expanding WF 0..100 Scorecards (exit_date < t)
+ Liquidity >=1亿/>=2亿 + 1000x Permutation + V20 Empty-Slot Patch + 2024-12-31 Truncation Proof.

Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 2.0 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import math
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd042_bse30cm_subnew_20261126"
for p in (BASE_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf  # noqa: E402
import _wf_sim_and_metrics as wfm  # noqa: E402
import _rd042_eval as rd_ev  # noqa: E402

STOCK_DAY_PQ = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
MKT_DAY_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"

EXITS = ["S1_hold1c", "S2_hold2c", "S3_hold3c", "S4_hold5c", "S5_zt_ride", "S6_ma5_stop"]
END_BAR_DATE = "2026-11-25"

STOCK_BASE_COLS = [
    "c6", "dt", "open", "high", "low", "close", "adj_factor", "ret_1d", "open_pct", "clv",
    "is_zt", "hit_zt", "is_broken_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "streak",
    "is_st_pit", "is_20cm", "prev_close_raw", "amount_yi", "turn_pct", "list_age",
]

STOCK_PIT_FEATS = [
    "mcap_yi_t1", "free_mcap_yi_t1", "amount_yi_t1", "real_turn_pct_t1",
    "ret_1d_t1", "d1_open_pct", "prev_clv", "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt",
    "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1", "down_streak_t1",
    "pos_20d_t1", "pos_60d_t1", "dd_20d_t1", "amp_20d_t1", "bias10_t1", "bias20_t1",
    "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1", "turn_5_20_t1",
    "lhb_on_t1", "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1",
    "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
    "lock_top10_pct_pre", "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
    "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1", "kpl_zt3_t1", "kpl_days_30d_t1",
    "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1",
    "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre",
]

MKT_PIT_FEATS = [
    "L1_zt_cnt_t1", "L1_nat_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zt_dt_logratio_t1",
    "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1", "L1_zt_prem_t1",
    "L1_lb_promo_t1", "L1_duanban_damian_t1", "L1_zt_mom3v20_t1", "L1_zt_pct60_t1",
    "L1_sent_phase_t1", "L1_smb_5d_t1", "L1_smb_20d_t1", "L1_amt_ratio20_t1",
    "L1_ew_bias20_t1", "L1_ew_pos60_t1", "L1_is_earn_win", "L1_is_month_end3", "L1_weekday",
    "mkt20_zt_cnt_t1", "mkt_amt_tril_t1", "mkt_0925_zt_cnt", "mkt_0925_avg_gap_pct",
    "th_style_ice_point_sig_t1", "us_ixic_ret1d_on", "us_vix_level_on",
    "pol_rescue_signal_10d", "pol_crackdown_signal_10d",
]


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def extract_subnew_events() -> pd.DataFrame:
    """Load list_age <= 85 sub-new rows strictly and extract A1, A2, A3 causal events."""
    t0 = time.time()
    all_cols = list(dict.fromkeys(STOCK_BASE_COLS + STOCK_PIT_FEATS))
    df = pd.read_parquet(STOCK_DAY_PQ, columns=all_cols, filters=[("list_age", "<=", 85)])
    df["c6"] = df["c6"].astype(str).str.zfill(6)
    df["dt"] = df["dt"].astype(str).str[:10]
    df = df.sort_values(["c6", "dt"]).reset_index(drop=True)
    print(f"[TrackA] Loaded sub-new bars (list_age<=85): {len(df):,} rows, {df['c6'].nunique()} stocks, RSS={peak_rss_mb()} MB", flush=True)

    # Merge market PIT features on dt
    mkt = pd.read_parquet(MKT_DAY_PQ, columns=["trade_date"] + MKT_PIT_FEATS)
    mkt["dt"] = mkt["trade_date"].astype(str).str[:10]
    mkt = mkt.drop(columns=["trade_date"]).drop_duplicates("dt")
    df = df.merge(mkt, on="dt", how="left").sort_values(["c6", "dt"]).reset_index(drop=True)

    events = []
    for c6, g in df.groupby("c6", sort=False):
        n = len(g)
        if n < 8:
            continue
        dts = g["dt"].to_numpy()
        op = g["open"].to_numpy(np.float64)
        hi = g["high"].to_numpy(np.float64)
        lo = g["low"].to_numpy(np.float64)
        cl = g["close"].to_numpy(np.float64)
        af = g["adj_factor"].to_numpy(np.float64)
        ac = cl * af
        ah = hi * af
        al = lo * af
        r1 = g["ret_1d"].to_numpy(np.float64)
        opct = g["open_pct"].to_numpy(np.float64)
        clv = g["clv"].to_numpy(np.float64)
        zt = g["is_zt"].to_numpy(np.int8)
        yzz = g["is_yizi_zt"].to_numpy(np.int8)
        dt_f = g["is_dt"].to_numpy(np.int8)
        yzd = g["is_yizi_dt"].to_numpy(np.int8)
        stk = g["streak"].to_numpy(np.int16)
        st = g["is_st_pit"].to_numpy(np.int8)
        i20 = g["is_20cm"].to_numpy(np.int8)
        pc_raw = g["prev_close_raw"].to_numpy(np.float64)
        amt = g["amount_yi"].to_numpy(np.float64)
        trn = g["turn_pct"].to_numpy(np.float64)
        age = g["list_age"].to_numpy(np.int16)
        dstk = g["down_streak_t1"].to_numpy(np.int16)

        ma5 = np.full(n, np.nan)
        for idx in range(4, n):
            ma5[idx] = np.mean(ac[idx - 4 : idx + 1]) / af[idx]

        # Extract feature matrix slice for quick row copy
        pit_dicts = g[STOCK_PIT_FEATS + MKT_PIT_FEATS].to_dict("records")

        # Track post-day-5 cumulative highs/lows causally
        for b in range(6, n - 1):
            sig = b - 1
            sig_age = int(age[sig])
            if sig_age < 6 or sig_age > 60:
                continue
            if st[b] == 1 or op[b] <= 0 or af[b] <= 0 or yzz[b] == 1 or yzd[b] == 1:
                continue
            if not np.isfinite(pc_raw[b]) or pc_raw[b] <= 0:
                continue
            lim = 20.0 if i20[b] == 1 else 10.0
            zt_px_b = round(pc_raw[b] * (1.0 + lim / 100.0), 2)
            # Exclude 09:25 limit-up auction open (unbuyable queue / adverse selection)
            if opct[b] >= lim - 0.25 or op[b] >= zt_px_b - 0.005:
                continue

            # Causal features up to sig (T-1)
            amt_prev3 = float(np.mean(amt[max(0, sig - 3) : sig])) if sig > 0 else amt[sig]
            vr3_sig = float(amt[sig] / max(1e-6, amt_prev3))
            amt_prev5_max = float(np.max(amt[max(0, sig - 5) : sig])) if sig > 0 else amt[sig]
            vol_shrink_pre = float(amt[sig - 1] / max(1e-6, amt_prev5_max)) if sig >= 2 else 1.0

            post5_mask = age[:sig] >= 6
            has_post5 = int(post5_mask.sum()) >= 1
            post5_hi_pre = float(np.max(ac[:sig][post5_mask])) if has_post5 else np.nan
            post5_lo_pre = float(np.min(al[:sig][post5_mask])) if has_post5 else np.nan
            all_hi_pre = float(np.max(ac[:sig]))
            day1_hi = float(np.max(ah[: sig + 1]))
            day5_idx = np.where(age[: sig + 1] == 5)[0]
            cum_ret_d5 = float((ac[sig] / ac[day5_idx[0]] - 1.0) * 100.0) if len(day5_idx) else np.nan
            cons_amp_5d = float((np.max(ah[max(0, sig - 5) : sig]) / max(1e-6, np.min(al[max(0, sig - 5) : sig])) - 1.0) * 100.0) if sig >= 5 else np.nan

            # Entry A1: Near-IPO limit-up next day
            is_a1 = (zt[sig] == 1)

            # Entry A2: Oversold / broke post5 low or down>=3d with shrink, followed by volume green rebound on sig
            broke_low_pre = bool(has_post5 and sig >= 2 and al[sig - 1] <= post5_lo_pre * 1.005 and (ac[sig - 1] / max(1e-6, np.max(ac[max(0, sig - 6) : sig])) - 1.0) <= -0.06)
            down3_pre = bool(dstk[sig] >= 3)  # note down_streak_t1[sig] == down streak up to sig-1!
            is_a2 = (
                (down3_pre or broke_low_pre)
                and (vol_shrink_pre <= 0.85)
                and (cl[sig] > op[sig])
                and (r1[sig] >= 3.0)
                and (vr3_sig >= 1.20)
                and (opct[b] <= 6.0)
            )

            # Entry A3: Consolidation breakout to new post-day-5 high (or all-time high) on volume ZT/big yang
            had_post5_pre2 = int((age[: sig - 1] >= 6).sum()) >= 3 if sig >= 2 else False
            post5_hi_pre2 = float(np.max(ac[: sig - 1][age[: sig - 1] >= 6])) if had_post5_pre2 else np.nan
            first_post5_brk = bool(
                sig_age >= 10
                and has_post5
                and had_post5_pre2
                and (ac[sig] > post5_hi_pre)
                and (ac[sig - 1] <= post5_hi_pre2)
            )
            first_all_brk = bool(first_post5_brk and (ac[sig] > all_hi_pre))
            is_a3 = (
                first_post5_brk
                and (cl[sig] > op[sig])
                and ((r1[sig] >= 5.0) or (zt[sig] == 1))
                and (vr3_sig >= 1.20)
                and (opct[b] <= 6.5)
            )

            if not (is_a1 or is_a2 or is_a3):
                continue

            ex_res = rd_ev.simulate_exits_generic(b, n, op, hi, lo, cl, af, ac, dts, zt, dt_f, yzd, ma5)
            if not ex_res:
                continue

            base_rec = {
                "code": c6,
                "sig_date": str(dts[sig]),
                "buy_date": str(dts[b]),
                "buy_hhmm": 925,
                "buy_px": round(float(op[b]), 3),
                "is_yizi": False,
                "is_20cm": int(i20[b]),
                "list_age": int(age[b]),
                "sn_sig_list_age": sig_age,
                "sn_age_bucket": "6_30" if sig_age <= 30 else "31_60",
                "sn_open_pct": round(float(opct[b]), 4),
                "sn_sig_ret1d": round(float(r1[sig]), 4),
                "sn_sig_clv": round(float(clv[sig]), 4),
                "sn_sig_amt_yi": round(float(amt[sig]), 4),
                "sn_sig_turn_pct": round(float(trn[sig]), 4),
                "sn_sig_vr3": round(vr3_sig, 4),
                "sn_vol_shrink_pre": round(vol_shrink_pre, 4),
                "sn_prev_is_yizi": int(yzz[sig]),
                "sn_prev_streak": int(stk[sig]),
                "sn_down_streak_pre": int(dstk[sig]),
                "sn_broke_low_pre": int(broke_low_pre),
                "sn_first_all_brk": int(first_all_brk),
                "sn_dist_day1_hi_pct": round(float((ac[sig] / day1_hi - 1.0) * 100.0), 3),
                "sn_cum_ret_d5_pct": round(cum_ret_d5, 3) if np.isfinite(cum_ret_d5) else np.nan,
                "sn_cons_amp_5d": round(cons_amp_5d, 3) if np.isfinite(cons_amp_5d) else np.nan,
                "open_pct": round(float(opct[b]), 4),
                "is_a1": int(is_a1),
                "is_a2": int(is_a2),
                "is_a3": int(is_a3),
            }
            base_rec.update(pit_dicts[b])

            for et_flag, et_name in ((is_a1, "A1"), (is_a2, "A2"), (is_a3, "A3")):
                if not et_flag:
                    continue
                rec = dict(base_rec)
                rec["entry_type"] = et_name
                for sname, sdict in ex_res.items():
                    rec[f"{sname}_exit_date"] = sdict["exit_date"]
                    rec[f"{sname}_exit_hhmm"] = sdict["exit_hhmm"]
                    rec[f"{sname}_gross_ret"] = sdict["gross_ret"]
                    rec[f"{sname}_reason"] = sdict["reason"]
                    rec[f"{sname}_mtm_json"] = json.dumps(sdict["mtm_gross"])
                events.append(rec)

    ev_df = pd.DataFrame(events).sort_values(["buy_date", "entry_type", "code"]).reset_index(drop=True)
    ev_pq = f"{OUT_DIR}/track_a_subnew_events_pit.parquet"
    ev_df.to_parquet(ev_pq, index=False, compression="snappy")
    print(f"[TrackA] Extracted {len(ev_df):,} events in {time.time()-t0:.1f}s | A1={int((ev_df['entry_type']=='A1').sum())}, A2={int((ev_df['entry_type']=='A2').sum())}, A3={int((ev_df['entry_type']=='A3').sum())} | RSS={peak_rss_mb()} MB", flush=True)
    del df
    gc.collect()
    return ev_df


def get_track_a_features(df_view: pd.DataFrame) -> list[str]:
    """Strictly causal non-degenerate features for Track A."""
    sn_cols = [
        "is_20cm", "list_age", "sn_sig_list_age", "sn_open_pct", "sn_sig_ret1d", "sn_sig_clv",
        "sn_sig_amt_yi", "sn_sig_turn_pct", "sn_sig_vr3", "sn_vol_shrink_pre",
        "sn_prev_is_yizi", "sn_prev_streak", "sn_down_streak_pre", "sn_broke_low_pre",
        "sn_first_all_brk", "sn_dist_day1_hi_pct", "sn_cum_ret_d5_pct", "sn_cons_amp_5d",
    ]
    cands = list(dict.fromkeys(sn_cols + STOCK_PIT_FEATS + MKT_PIT_FEATS))
    w = df_view[df_view["buy_date"] <= "2022-12-31"]
    clean = []
    for c in cands:
        if c not in df_view.columns or not pd.api.types.is_numeric_dtype(df_view[c]):
            continue
        s = w[c].dropna()
        if len(s) < 25:
            continue
        vc = s.value_counts()
        if len(vc) <= 1:
            continue
        if len(vc) <= 3 and int(vc.min()) < 8:
            continue
        clean.append(c)
    return clean


def main():
    t0 = time.time()
    ev_df = extract_subnew_events()
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    bench_df = v20_ctx["bench"]

    windows_5y = [
        ("FULL_5Y", "2021-01-04", END_BAR_DATE),
        ("WF_2326", "2023-01-03", END_BAR_DATE),
        ("Y2025_2026", "2025-01-01", END_BAR_DATE),
        ("Y2026", "2026-01-01", END_BAR_DATE),
        ("Y2026_H2", "2026-07-01", END_BAR_DATE),
    ]

    # 1. Blind Matrix across A1 / A2 / A3 (6..30 Core + 6..60 Extended + Liquidity + Divergence Open)
    age30 = (ev_df["sn_age_bucket"] == "6_30").to_numpy()
    age60 = np.ones(len(ev_df), dtype=bool)
    div_open = ev_df["sn_open_pct"].between(-8.0, 2.5).to_numpy()
    a1_fb_nyz = (ev_df["sn_prev_streak"] == 1).to_numpy() & (ev_df["sn_prev_is_yizi"] == 0).to_numpy()
    is_10 = (ev_df["is_20cm"] == 0).to_numpy()
    is_20 = (ev_df["is_20cm"] == 1).to_numpy()
    liq1 = (ev_df["sn_sig_amt_yi"] >= 1.0).to_numpy()
    liq2 = (ev_df["sn_sig_amt_yi"] >= 2.0).to_numpy()
    a3_allh = (ev_df["sn_first_all_brk"] == 1).to_numpy()

    blind_slices = [
        ("A1_30d_all", "A1", age30),
        ("A1_30d_div", "A1", age30 & div_open),
        ("A1_30d_fb_nyz_div", "A1", age30 & a1_fb_nyz & div_open),
        ("A1_30d_10cm_div", "A1", age30 & is_10 & div_open),
        ("A1_30d_20cm_div", "A1", age30 & is_20 & div_open),
        ("A1_30d_div_liq2yi", "A1", age30 & div_open & liq2),
        ("A1_60d_all", "A1", age60),
        ("A1_60d_div", "A1", age60 & div_open),
        ("A2_30d_rebound", "A2", age30),
        ("A2_30d_liq2yi", "A2", age30 & liq2),
        ("A2_60d_rebound", "A2", age60),
        ("A2_60d_liq2yi", "A2", age60 & liq2),
        ("A3_30d_post5brk", "A3", age30),
        ("A3_30d_post5brk_div", "A3", age30 & ev_df["sn_open_pct"].between(-5.0, 3.5).to_numpy()),
        ("A3_30d_allhighbrk", "A3", age30 & a3_allh),
        ("A3_30d_liq2yi", "A3", age30 & liq2),
        ("A3_60d_post5brk", "A3", age60),
        ("A3_60d_allhighbrk", "A3", age60 & a3_allh),
    ]

    blind_rows = []
    for s_name, ent, msk in blind_slices:
        for ex in EXITS:
            view = rd_ev.make_clean_view(ev_df, ent, ex, extra_mask=msk, fee_rt=0.0030)
            if len(view) < 10:
                continue
            _, slot = wfm.select_single_slot_trades(view.assign(wf_score=100.0), score_col="wf_score", threshold=None, wf_only=False)
            ev30 = rd_ev.eval_windows_exact(slot, view, view, bench_df, "mtm_json_use", 0.0030, "2021-01-04", END_BAR_DATE, windows_5y, perm_n=100)
            ev50 = rd_ev.eval_windows_exact(
                slot.assign(net_ret=(1.0 + slot["gross_ret"]) * (1.0 - 0.0050) - 1.0),
                view.assign(net_ret=(1.0 + view["gross_ret"]) * (1.0 - 0.0050) - 1.0),
                view, bench_df, "mtm_json_use", 0.0050, "2021-01-04", END_BAR_DATE, windows_5y[:2], perm_n=20,
            )
            ev80 = rd_ev.eval_windows_exact(
                slot.assign(net_ret=(1.0 + slot["gross_ret"]) * (1.0 - 0.0080) - 1.0),
                view.assign(net_ret=(1.0 + view["gross_ret"]) * (1.0 - 0.0080) - 1.0),
                view, bench_df, "mtm_json_use", 0.0080, "2021-01-04", END_BAR_DATE, windows_5y[:2], perm_n=20,
            )
            f5 = ev30["windows"].get("FULL_5Y", {})
            wf23 = ev30["windows"].get("WF_2326", {})
            y2526 = ev30["windows"].get("Y2025_2026", {})
            y26 = ev30["windows"].get("Y2026", {})
            y26h2 = ev30["windows"].get("Y2026_H2", {})
            blind_rows.append({
                "section": "BLIND_A", "track": s_name, "exit_rule": ex,
                "n_cands": int(len(view)), "raw_wr_pct": round(float((view["net_ret"] > 0).mean() * 100), 2),
                "raw_mean_pct": round(float(view["net_ret"].mean() * 100), 2),
                "n_trades": f5.get("n", 0), "wr_pct": f5.get("wr_pct", 0.0), "plr": f5.get("plr", 0.0),
                "mean_pct": f5.get("mean_pct", 0.0),
                "nav_30": f5.get("nav", 1.0), "ex5_30": f5.get("ex_top5_nav", 1.0),
                "mdd_pct": f5.get("daily_mdd_pct", 0.0), "sharpe": f5.get("daily_sharpe", 0.0), "calmar": f5.get("daily_calmar", 0.0),
                "mtm_diff": ev30["mtm_reconciliation_diff"],
                "excess_csi300_pp": f5.get("excess_csi300_pp", 0.0),
                "nav_50": ev50["windows"].get("FULL_5Y", {}).get("nav", 1.0),
                "nav_80": ev80["windows"].get("FULL_5Y", {}).get("nav", 1.0),
                "n_wf": wf23.get("n", 0), "nav_wf": wf23.get("nav", 1.0), "ex5_wf": wf23.get("ex_top5_nav", 1.0),
                "sharpe_wf": wf23.get("daily_sharpe", 0.0),
                "nav_2526": y2526.get("nav", 1.0), "nav_y26": y26.get("nav", 1.0), "nav_26h2": y26h2.get("nav", 1.0),
            })
    blind_df = pd.DataFrame(blind_rows)
    blind_df.to_csv(f"{OUT_DIR}/rd042_track_a_blind.csv", index=False, encoding="utf-8-sig")
    print(f"[TrackA] Blind matrix saved ({len(blind_df)} rows). Top 5 by nav_30:")
    print(blind_df.sort_values("nav_30", ascending=False)[["track", "exit_rule", "n_trades", "wr_pct", "nav_30", "ex5_30", "nav_wf", "nav_y26"]].head(6).to_string())

    # 2. Expanding Walk-Forward 0..100 Scorecards on key Track A tracks
    wf_specs = [
        ("WF_A1_30d_all_S1", "A1", "S1_hold1c", age30, True),
        ("WF_A1_30d_all_S2", "A1", "S2_hold2c", age30, False),
        ("WF_A1_30d_all_S5zt", "A1", "S5_zt_ride", age30, True),
        ("WF_A1_30d_div_S1", "A1", "S1_hold1c", age30 & div_open, False),
        ("WF_A1_30d_div_S5zt", "A1", "S5_zt_ride", age30 & div_open, False),
        ("WF_A1_60d_all_S1", "A1", "S1_hold1c", age60, False),
        ("WF_A1_60d_div_S1", "A1", "S1_hold1c", age60 & div_open, False),
        ("WF_A2_30d_S1", "A2", "S1_hold1c", age30, False),
        ("WF_A2_30d_S2", "A2", "S2_hold2c", age30, False),
        ("WF_A2_60d_S1", "A2", "S1_hold1c", age60, True),
        ("WF_A2_60d_S2", "A2", "S2_hold2c", age60, False),
        ("WF_A3_30d_S1", "A3", "S1_hold1c", age30, True),
        ("WF_A3_30d_S2", "A3", "S2_hold2c", age30, False),
        ("WF_A3_30d_S5zt", "A3", "S5_zt_ride", age30, False),
        ("WF_A3_60d_S1", "A3", "S1_hold1c", age60, False),
        ("WF_A3_60d_S5zt", "A3", "S5_zt_ride", age60, False),
    ]
    wf_rows, wf_audits = [], {}
    for tid, ent, ex, msk, run_tr in wf_specs:
        view = rd_ev.make_clean_view(ev_df, ent, ex, extra_mask=msk, fee_rt=0.0030)
        if len(view) < 60:
            print(f"  [Skip {tid}] len={len(view)}")
            continue
        fcols = get_track_a_features(view)
        au, rows, _ = rd_ev.evaluate_wf_track(
            tid, view, fcols, v20_ctx, liq_col="sn_sig_amt_yi", liq_thresholds=(1.0, 2.0),
            wf_start_req="2023-01-03", end_dt=END_BAR_DATE,
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
            run_trunc=run_tr, min_warmup_trades=50, min_warmup_trades_rare=35, min_warmup_months=12, perm_n=1000,
        )
        wf_audits[tid] = au
        wf_rows.extend(rows)
        t20 = [r for r in rows if r["threshold"] == "top20"][0]
        print(f"  -> {tid}: n={t20['n_trades']}, wr={t20['wr_pct']}%, nav30={t20['nav_30']}, ex5={t20['ex5_30']}, nav2526={t20['nav_2526']}, nav26={t20['nav_y26']}, liq2yi={t20['liq_2.0_nav']}, trunc={t20['trunc_pass']} ({au['elapsed_sec']}s)", flush=True)

    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(f"{OUT_DIR}/rd042_track_a_wf.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/rd042_track_a_audit.json", "w", encoding="utf-8") as f:
        json.dump({"elapsed_sec": round(time.time() - t0, 2), "peak_rss_mb": peak_rss_mb(), "audits": wf_audits}, f, ensure_ascii=False, indent=2)
    print(f"[TrackA] Complete in {time.time()-t0:.1f}s | peak RSS={peak_rss_mb()} MB")


if __name__ == "__main__":
    main()
