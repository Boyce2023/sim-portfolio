#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build unified 20cm PIT research panel & aux cache in part2_native_strategies/."""
import bisect, json, os, pickle, time
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from layer_prices_mkt import BASE, OUT_DIR, build_20cm_price_df, load_10cm_zt_map, load_benchmarks
from layer_events_pit import CSRC_TECH, load_community_notices_csrc, load_kpl_and_synergy, load_lhb_20cm, load_zt_tape_20cm


def cnt_ts_win(ts_list: list, start_ts: str, end_ts: str) -> int:
    if not ts_list:
        return 0
    lo = bisect.bisect_left(ts_list, start_ts)
    hi = bisect.bisect_left(ts_list, end_ts)
    return max(0, hi - lo)


def shift_cal(dt_s: str, days: int) -> str:
    return (datetime.strptime(dt_s, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def main():
    t0 = time.time()
    print("[1/5] Loading benchmarks & 10cm market stats...")
    sh300, sz399107 = load_benchmarks()
    mkt10, zt10_map = load_10cm_zt_map()

    print("[2/5] Building 20cm daily price panel (active + delisted + PIT top10 lockup)...")
    df = build_20cm_price_df()
    all_dts = sorted(df[df["dt"] >= "2020-09-01"]["dt"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}

    print("[3/5] Loading zt_micro_tape, KPL synergy, LHB/Youzi, Community, Cninfo, CSRC...")
    zt_tape, zt_st_first = load_zt_tape_20cm()
    stock_kpl, plate_stats, hist_themes = load_kpl_and_synergy(zt10_map, all_dts)
    lhb_map = load_lhb_20cm()
    ev = load_community_notices_csrc()

    # Slice to >= 2021-01-04 (keep pre-2021 shifted columns already computed!)
    # First attach prev/next trading date per row & next 10 trading bars for fast O(1) trade simulation
    g = df.groupby("c6", sort=False)
    df["prev_dt"] = g["dt"].shift(1).fillna("")
    df["zt_px_adj"] = df["zt_px"] * (df["ac"] / df["close"])
    for k in range(1, 12):
        df[f"f{k}_dt"] = g["dt"].shift(-k).fillna("")
        df[f"f{k}_ao"] = g["ao"].shift(-k)
        df[f"f{k}_ah"] = g["ah"].shift(-k)
        df[f"f{k}_al"] = g["al"].shift(-k)
        df[f"f{k}_ac"] = g["ac"].shift(-k)
        df[f"f{k}_o_pct"] = g["o_pct"].shift(-k)
        df[f"f{k}_ret"] = g["ret"].shift(-k)
        df[f"f{k}_ma5"] = g["ma5"].shift(-k)
        df[f"f{k}_buyable"] = g["buyable_open"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_sellable"] = g["sellable_close"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_zt"] = g["is_zt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_ty"] = g["is_true_yang"].shift(-k).fillna(False).astype(bool)

    df["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    df["prev_dt_streak"] = g["dt_streak"].shift(1).fillna(0).astype(int)
    df["prev_is_zt"] = g["is_zt"].shift(1).fillna(False).astype(bool)
    df["prev_is_dt"] = g["is_dt"].shift(1).fillna(False).astype(bool)
    df["prev_is_yizi_zt"] = g["is_yizi_zt"].shift(1).fillna(False).astype(bool)
    df["prev_is_yizi_dt"] = g["is_yizi_dt"].shift(1).fillna(False).astype(bool)
    df["prev_to"] = g["to"].shift(1)
    df["prev_ret"] = g["ret"].shift(1)
    df["prev_ret5"] = g["ret5"].shift(1)
    df["prev_ret10"] = g["ret10"].shift(1)
    df["prev_pos20"] = g["pos20"].shift(1)
    df["prev_pos60"] = g["pos60"].shift(1)
    df["prev_bias20"] = g["bias20"].shift(1)
    df["prev_mcap"] = g["mcap"].shift(1)
    df["prev_rf_mcap"] = g["real_free_mcap"].shift(1)
    df["prev_amt_ma5"] = g["amt_ma5_prev"].shift(1)
    df["prev_ma20"] = g["ma20"].shift(1)
    df["prev_high20"] = g["high20"].shift(1)
    df["prev_high60"] = g["high60"].shift(1)

    df = df[df["dt"] >= "2021-01-04"].copy().reset_index(drop=True)
    n = len(df)
    print(f"[4/5] Attaching PIT event features to {n:,} 20cm rows...")

    # Pre-load st_universe only as fallback for delisted names? No, use PIT first_st_dt from cninfo + zt_tape!
    st_first = dict(ev["st_first"])
    for c6, dt_s in zt_st_first.items():
        if c6 not in st_first or dt_s < st_first[c6]:
            st_first[c6] = dt_s

    c6_arr = df["c6"].values
    dt_arr = df["dt"].values
    f1dt_arr = df["f1_dt"].values
    pdt_arr = df["prev_dt"].values
    amt_arr = df["amount"].values

    # Compute PIT arrays
    is_st = np.zeros(n, dtype=np.int8)
    zt_hhmm = np.full(n, 9999, dtype=np.int32)
    zt_mins = np.full(n, 999, dtype=np.int32)
    zt_seal_amt = np.zeros(n, dtype=np.float32)
    zt_seal_ratio = np.zeros(n, dtype=np.float32)
    zt_obc = np.full(n, -1, dtype=np.int32)
    kpl_in = np.zeros(n, dtype=np.int8)
    kpl_sz = np.zeros(n, dtype=np.int16)
    kpl_10zt = np.zeros(n, dtype=np.int16)
    kpl_10yz = np.zeros(n, dtype=np.int16)
    kpl_20zt = np.zeros(n, dtype=np.int16)
    kpl_elo = np.full(n, 100.0, dtype=np.float32)
    kpl_plate_arr = [""] * n
    kpl_hist_10zt_max = np.zeros(n, dtype=np.int16)
    kpl_hist_10yz_max = np.zeros(n, dtype=np.int16)

    lhb_has = np.zeros(n, dtype=np.int8)
    lhb_inst_net = np.zeros(n, dtype=np.float32)
    lhb_inst_b = np.zeros(n, dtype=np.float32)
    lhb_net = np.zeros(n, dtype=np.float32)
    lhb_lh_cnt = np.zeros(n, dtype=np.int16)
    lhb_lh_share = np.zeros(n, dtype=np.float32)
    lhb_lh_net_pos = np.zeros(n, dtype=np.int8)
    lhb_good_yz = np.zeros(n, dtype=np.int8)
    lhb_surf = np.zeros(n, dtype=np.int8)
    lhb_quant = np.zeros(n, dtype=np.int16)
    lhb_north = np.zeros(n, dtype=np.float32)
    ths_cap_in = np.zeros(n, dtype=np.float32)
    bayes_c = np.zeros(n, dtype=np.float32)
    bayes_t2 = np.zeros(n, dtype=np.float32)

    xq_t0_pre = np.zeros(n, dtype=np.int16)
    xq_t1_pre = np.zeros(n, dtype=np.int16)
    xq_3d_t1 = np.zeros(n, dtype=np.int16)
    gb_cnt = np.zeros(n, dtype=np.int32)
    gb_read = np.zeros(n, dtype=np.float32)

    tox_90d = np.zeros(n, dtype=np.int8)
    reg_10d = np.zeros(n, dtype=np.int8)
    tox_t0_90d = np.zeros(n, dtype=np.int8)
    reg_t0_10d = np.zeros(n, dtype=np.int8)
    cat_earn_3d = np.zeros(n, dtype=np.int8)
    cat_cont_3d = np.zeros(n, dtype=np.int8)
    cat_ma_5d = np.zeros(n, dtype=np.int8)
    cat_bb_5d = np.zeros(n, dtype=np.int8)
    cat_earn_t0 = np.zeros(n, dtype=np.int8)
    cat_cont_t0 = np.zeros(n, dtype=np.int8)
    cat_ma_t0 = np.zeros(n, dtype=np.int8)
    cat_bb_t0 = np.zeros(n, dtype=np.int8)
    ir_10d = np.zeros(n, dtype=np.int16)
    ir_30d = np.zeros(n, dtype=np.int16)
    is_tech = np.zeros(n, dtype=np.int8)

    # Pre-index PIT rolling KPL themes per c6 -> sorted list of (dt, pname)
    hist_th_dts = {c6: [x[0] for x in v] for c6, v in hist_themes.items()}
    xq_m, gb_m = ev["xq"], ev["gb"]
    tox_m, reg_m = ev["tox"], ev["reg"]
    ce_m, cc_m, cm_m, cb_m, ir_m, csrc_m = ev["cat_earn"], ev["cat_cont"], ev["cat_ma"], ev["cat_bb"], ev["ir"], ev["csrc"]

    # Date shift cache for speed
    cal_cache = {}
    def get_cal(d):
        v = cal_cache.get(d)
        if v is None:
            v = (shift_cal(d, -2), shift_cal(d, -3), shift_cal(d, -5), shift_cal(d, -10), shift_cal(d, -30), shift_cal(d, -90))
            cal_cache[d] = v
        return v

    for i in range(n):
        c6 = c6_arr[i]
        dt = dt_arr[i]
        f1dt = f1dt_arr[i] or dt
        sf = st_first.get(c6)
        if sf and dt >= sf:
            is_st[i] = 1
        zt = zt_tape.get((dt, c6))
        if zt:
            zt_hhmm[i], zt_mins[i], zt_seal_amt[i], _, zt_obc[i], _, _ = zt
            if amt_arr[i] > 0:
                zt_seal_ratio[i] = zt[2] / amt_arr[i]

        kp = stock_kpl.get((dt, c6))
        if kp:
            kpl_in[i] = 1
            kpl_plate_arr[i] = kp[0]
            kpl_sz[i], kpl_10zt[i], kpl_10yz[i], kpl_20zt[i], kpl_elo[i] = kp[1], kp[2], kp[3], kp[4], kp[5]
        # PIT rolling 30d KPL peer check (strictly <= dt!)
        ht_dts = hist_th_dts.get(c6)
        if ht_dts:
            d30 = get_cal(dt)[4]
            lo = bisect.bisect_left(ht_dts, d30)
            hi = bisect.bisect_right(ht_dts, dt)
            if hi > lo:
                seen_p = {hist_themes[c6][j][1] for j in range(lo, hi)}
                m10, my10 = 0, 0
                for pn in seen_p:
                    ps = plate_stats.get((dt, pn))
                    if ps:
                        if ps[1] > m10: m10 = ps[1]
                        if ps[2] > my10: my10 = ps[2]
                kpl_hist_10zt_max[i] = m10
                kpl_hist_10yz_max[i] = my10

        lh = lhb_map.get((dt, c6))
        if lh:
            lhb_has[i] = 1
            lhb_inst_net[i] = lh["lhb_inst_net"] / 1e4
            lhb_inst_b[i] = lh["lhb_inst_b"] / 1e4
            lhb_net[i] = lh["lhb_net"] / 1e4
            lhb_lh_cnt[i] = lh["lhb_lh_cnt"]
            lhb_lh_share[i] = lh["lhb_lh_share"]
            lhb_lh_net_pos[i] = lh["lhb_lh_net_pos"]
            lhb_good_yz[i] = lh["lhb_good_yz"]
            lhb_surf[i] = lh["lhb_surf"]
            lhb_quant[i] = lh["lhb_quant_cnt"]
            lhb_north[i] = lh["lhb_north_net"] / 1e4
            ths_cap_in[i] = lh["ths_cap_in"] / 1e4
            bayes_c[i] = lh["bayes_c"]
            bayes_t2[i] = lh["bayes_t2"]

        d2, d3, d5, d10, d30, d90 = get_cal(dt)
        xl = xq_m.get(c6)
        if xl:
            xq_t0_pre[i] = cnt_ts_win(xl, f"{dt} 00:00:00", f"{dt} 14:55:00")
            xq_t1_pre[i] = cnt_ts_win(xl, f"{dt} 00:00:00", f"{f1dt} 09:25:00")
            xq_3d_t1[i] = cnt_ts_win(xl, f"{d2} 00:00:00", f"{f1dt} 09:25:00")
        gbv = gb_m.get((c6, dt))
        if gbv:
            gb_cnt[i], gb_read[i] = gbv[0], gbv[1]

        t1_cut = f"{f1dt} 09:25:00"
        t0_cut = f"{dt} 14:55:00"
        if cnt_ts_win(tox_m.get(c6), f"{d90} 00:00:00", t1_cut) > 0: tox_90d[i] = 1
        if cnt_ts_win(reg_m.get(c6), f"{d10} 00:00:00", t1_cut) > 0: reg_10d[i] = 1
        if cnt_ts_win(tox_m.get(c6), f"{d90} 00:00:00", t0_cut) > 0: tox_t0_90d[i] = 1
        if cnt_ts_win(reg_m.get(c6), f"{d10} 00:00:00", t0_cut) > 0: reg_t0_10d[i] = 1
        if cnt_ts_win(ce_m.get(c6), f"{d3} 00:00:00", t1_cut) > 0: cat_earn_3d[i] = 1
        if cnt_ts_win(cc_m.get(c6), f"{d3} 00:00:00", t1_cut) > 0: cat_cont_3d[i] = 1
        if cnt_ts_win(cm_m.get(c6), f"{d5} 00:00:00", t1_cut) > 0: cat_ma_5d[i] = 1
        if cnt_ts_win(cb_m.get(c6), f"{d5} 00:00:00", t1_cut) > 0: cat_bb_5d[i] = 1
        if cnt_ts_win(ce_m.get(c6), f"{d3} 00:00:00", t0_cut) > 0: cat_earn_t0[i] = 1
        if cnt_ts_win(cc_m.get(c6), f"{d3} 00:00:00", t0_cut) > 0: cat_cont_t0[i] = 1
        if cnt_ts_win(cm_m.get(c6), f"{d5} 00:00:00", t0_cut) > 0: cat_ma_t0[i] = 1
        if cnt_ts_win(cb_m.get(c6), f"{d5} 00:00:00", t0_cut) > 0: cat_bb_t0[i] = 1
        irl = ir_m.get(c6)
        if irl:
            ir_10d[i] = cnt_ts_win(irl, f"{d10} 00:00:00", t1_cut)
            ir_30d[i] = cnt_ts_win(irl, f"{d30} 00:00:00", t1_cut)
        for sd, ed, ind in csrc_m.get(c6, []):
            if sd <= dt <= ed and ind in CSRC_TECH:
                is_tech[i] = 1
                break

    df["is_st_pit"] = is_st
    df["zt_hhmm"] = zt_hhmm
    df["zt_mins"] = zt_mins
    df["zt_seal_amt"] = zt_seal_amt
    df["zt_seal_ratio"] = zt_seal_ratio
    df["zt_obc"] = zt_obc
    df["kpl_in"] = kpl_in
    df["kpl_plate"] = kpl_plate_arr
    df["kpl_sz"] = kpl_sz
    df["kpl_10zt"] = kpl_10zt
    df["kpl_10yz"] = kpl_10yz
    df["kpl_20zt"] = kpl_20zt
    df["kpl_elo"] = kpl_elo
    df["kpl_hist_10zt_max"] = kpl_hist_10zt_max
    df["kpl_hist_10yz_max"] = kpl_hist_10yz_max
    df["lhb_has"] = lhb_has
    df["lhb_inst_net"] = lhb_inst_net
    df["lhb_inst_b"] = lhb_inst_b
    df["lhb_net"] = lhb_net
    df["lhb_lh_cnt"] = lhb_lh_cnt
    df["lhb_lh_share"] = lhb_lh_share
    df["lhb_lh_net_pos"] = lhb_lh_net_pos
    df["lhb_good_yz"] = lhb_good_yz
    df["lhb_surf"] = lhb_surf
    df["lhb_quant"] = lhb_quant
    df["lhb_north"] = lhb_north
    df["ths_cap_in"] = ths_cap_in
    df["bayes_c"] = bayes_c
    df["bayes_t2"] = bayes_t2
    df["xq_t0_pre"] = xq_t0_pre
    df["xq_t1_pre"] = xq_t1_pre
    df["xq_3d_t1"] = xq_3d_t1
    df["gb_cnt"] = gb_cnt
    df["gb_read"] = gb_read
    df["tox_90d"] = tox_90d
    df["reg_10d"] = reg_10d
    df["tox_t0_90d"] = tox_t0_90d
    df["reg_t0_10d"] = reg_t0_10d
    df["cat_earn_3d"] = cat_earn_3d
    df["cat_cont_3d"] = cat_cont_3d
    df["cat_ma_5d"] = cat_ma_5d
    df["cat_bb_5d"] = cat_bb_5d
    df["cat_any"] = ((cat_earn_3d + cat_cont_3d + cat_ma_5d + cat_bb_5d) > 0).astype(np.int8)
    df["cat_any_t0"] = ((cat_earn_t0 + cat_cont_t0 + cat_ma_t0 + cat_bb_t0) > 0).astype(np.int8)
    df["ir_10d"] = ir_10d
    df["ir_30d"] = ir_30d
    df["is_tech"] = is_tech
    g_post = df.groupby("c6", sort=False)
    gb_ma10_prev = g_post["gb_cnt"].transform(lambda s: s.shift(1).rolling(10, min_periods=2).mean()).fillna(0.0)
    df["gb_surge"] = (df["gb_cnt"] + 1.0) / (gb_ma10_prev + 2.0)
    # KPL plate peers f1_open avg (known at T+1 09:25!)
    kpl_sub = df[df["kpl_in"] == 1]
    plate_f1o = kpl_sub.groupby(["dt", "kpl_plate"])["f1_o_pct"].mean().to_dict()
    df["kpl_peers_f1o"] = [plate_f1o.get((d, p), np.nan) if k == 1 else np.nan for d, p, k in zip(df["dt"], df["kpl_plate"], df["kpl_in"])]

    # Compute 20cm EW benchmark & cross-sectional 20cm market stats + severe deviation distances
    valid_bm = df["tradable"] & (df["is_st_pit"] == 0)
    ew20_daily = df[valid_bm].groupby("dt")["ret"].mean().to_dict()
    ew20_dts = sorted(ew20_daily.keys())
    ew20_nav = {}
    nv = 1.0
    for d in ew20_dts:
        nv *= (1.0 + ew20_daily[d])
        ew20_nav[d] = nv
    # Also compute 3d, 10d, 30d index returns from sz399107 (fallback sh300) for severe deviation
    idx_ref = {d: sz399107.get(d, sh300.get(d, np.nan)) for d in ew20_dts}
    idx_s = pd.Series([idx_ref[d] for d in ew20_dts], index=ew20_dts)
    idx_r3 = idx_s.pct_change(3).to_dict()
    idx_r10 = idx_s.pct_change(10).to_dict()
    idx_r30 = idx_s.pct_change(30).to_dict()
    csi_s = pd.Series([sh300.get(d, np.nan) for d in ew20_dts], index=ew20_dts)
    csi_1d = csi_s.pct_change(1).to_dict()
    csi_5d = csi_s.pct_change(5).to_dict()

    df["dist_3d30"] = 0.30 - (df["ret3"] - df["dt"].map(idx_r3).fillna(0.0))
    df["dist_10d100"] = 1.00 - (df["ret10"] - df["dt"].map(idx_r10).fillna(0.0))
    df["dist_30d200"] = 2.00 - (df["ret30"] - df["dt"].map(idx_r30).fillna(0.0))
    df["csi_1d"] = df["dt"].map(csi_1d).fillna(0.0)
    df["csi_5d"] = df["dt"].map(csi_5d).fillna(0.0)
    df["mkt20_zt_cnt"] = df["dt"].map(df[df["is_zt"] & (df["is_st_pit"] == 0)].groupby("dt").size()).fillna(0).astype(int)
    df["mkt20_dt_cnt"] = df["dt"].map(df[df["is_dt"] & (df["is_st_pit"] == 0)].groupby("dt").size()).fillna(0).astype(int)
    df["mkt20_ew_ret"] = df["dt"].map(ew20_daily).fillna(0.0)
    df["mkt10_zt_cnt"] = df["dt"].map({k: v["mkt10_zt_cnt"] for k, v in mkt10.items()}).fillna(0).astype(int)
    df["mkt10_yizi_cnt"] = df["dt"].map({k: v["mkt10_yizi_cnt"] for k, v in mkt10.items()}).fillna(0).astype(int)
    df["mkt10_max_board"] = df["dt"].map({k: v["mkt10_max_board"] for k, v in mkt10.items()}).fillna(0).astype(int)
    df["f1_mkt10_0925_zt"] = df["f1_dt"].map({k: v["mkt10_0925_zt_cnt"] for k, v in mkt10.items()}).fillna(0).astype(int)
    df["f1_mkt10_prev1b_open"] = df["f1_dt"].map({k: v["mkt10_prev_1b_open_avg"] for k, v in mkt10.items()}).fillna(0.0)

    out_pq = f"{OUT_DIR}/cache_20cm_panel.parquet"
    out_aux = f"{OUT_DIR}/cache_20cm_aux.pkl"
    df.to_parquet(out_pq, index=False)
    with open(out_aux, "wb") as f:
        pickle.dump({"sh300": sh300, "ew20_nav": ew20_nav, "ew20_daily": ew20_daily, "mkt10": mkt10, "plate_stats": plate_stats, "all_dts": ew20_dts}, f)
    print(f"[DONE] Saved {out_pq} ({len(df):,} rows, {df.shape[1]} cols) & aux in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
