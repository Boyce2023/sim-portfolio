#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Stage 2: Enrich stage1_cand_raw.parquet with Lockup, LHB Famous/Inst/North/Quant/Lhasa, Fine Notices, IR, Community, Themes, and Precompute All Entry x Exit Matrices."""
import os, sys, json, time, bisect, pickle, datetime
from collections import defaultdict
import numpy as np
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
GFM_DIR = f"{BASE}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{BASE}/backtests_astock2/p5_full_pry_universe"
for d in (GFM_DIR, OUT_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

from part2b_build_env_and_bars import pit_lock_lookup
from pit_aux_loaders import load_aux_pit_sources
from build_full_36k_pry_master import load_full_lhb_seats, load_fine_notices


def main():
    t0 = time.time()
    cand = pd.read_parquet(f"{OUT_DIR}/stage1_cand_raw.parquet")
    rt_env_map = json.load(open(f"{OUT_DIR}/rt_env_map.json"))
    env_df = pd.read_parquet(f"{GFM_DIR}/daily_env_5y.parquet")
    env_map = env_df.set_index("dt_str").to_dict(orient="index")
    holders_idx = json.load(open(f"{GFM_DIR}/pit_top10_all_codes.json"))
    idx_klines = json.load(open(f"{BASE}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    csi_map = idx_klines["sh000300"]

    target_codes = set(cand["c6"].unique())
    ind_map, name_map, _, _, _, ir_grp, comm_grp, _ = load_aux_pit_sources(target_codes)
    seat_map = load_full_lhb_seats()
    fine_notices = load_fine_notices(target_codes)

    # Load KPL plate counts per (date, code)
    kpl_map = {}
    plate_day_cnt = defaultdict(int)
    kp_path = f"{BASE}/data/kpl_plates_5y_2021_2026_complete.jsonl"
    if os.path.exists(kp_path):
        with open(kp_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                dt = str(obj.get("date") or obj.get("trade_date") or "")[:10]
                if dt < "2021-12-01":
                    continue
                for pl in obj.get("plates", []):
                    pname = str(pl.get("name") or pl.get("plate_name") or "其他")
                    stks = pl.get("stocks") or []
                    plate_day_cnt[(dt, pname)] = max(plate_day_cnt[(dt, pname)], len(stks))
                    for st in stks:
                        raw_sc = st[0] if isinstance(st, (list, tuple)) and len(st) > 0 else (st.get("code") or st.get("sec_code") or "" if isinstance(st, dict) else "")
                        sc = str(raw_sc)[-6:] if len(str(raw_sc)) >= 6 else ""
                        if sc and (dt, sc) not in kpl_map:
                            kpl_map[(dt, sc)] = pname

    cand["name"] = cand["c6"].map(name_map).fillna("")
    cand["csrc_ind"] = cand["c6"].map(ind_map).fillna("")
    cand["is_st_or_delist"] = cand["name"].str.contains("ST|退", na=False)

    # Vector/loop enrichment across ~52,000 rows (~4 seconds in Python)
    n = len(cand)
    lock10_a = np.zeros(n); lock5_a = np.zeros(n)
    ib_p = np.zeros(n); is_p = np.zeros(n); nb_p = np.zeros(n); yz_p = np.zeros(n, dtype=int); qt_p = np.zeros(n, dtype=int); lh_p = np.zeros(n, dtype=int); lhs_p = np.zeros(n)
    TAIL_ib_d0 = np.zeros(n); TAIL_yz_d0 = np.zeros(n, dtype=int)
    n_inv90 = np.zeros(n, dtype=bool); n_del90 = np.zeros(n, dtype=bool); n_los90 = np.zeros(n, dtype=bool); n_red90 = np.zeros(n, dtype=bool)
    n_buy90 = np.zeros(n, dtype=bool); n_win90 = np.zeros(n, dtype=bool); n_bad7 = np.zeros(n, dtype=bool); n_good7 = np.zeros(n, dtype=bool)
    ir8 = np.zeros(n, dtype=bool); ir30 = np.zeros(n, dtype=int); comm24 = np.zeros(n, dtype=int)
    plate_prev = []; p_sz_prev = np.zeros(n, dtype=int); TAIL_plate_d0 = []; TAIL_psz_d0 = np.zeros(n, dtype=int)

    c6_v = cand["c6"].values; dsig_v = cand["sig_date"].values; dbuy_v = cand["dt_str"].values
    for i in range(n):
        c6, ds_s, db_s = c6_v[i], dsig_v[i], dbuy_v[i]
        l10, l5 = pit_lock_lookup(holders_idx, c6, db_s)
        lock10_a[i], lock5_a[i] = l10, l5
        sp = seat_map.get((ds_s, c6), [0.0, 0.0, 0.0, 0, 0, 0, 0.0])
        ib_p[i], is_p[i], nb_p[i], yz_p[i], qt_p[i], lh_p[i], lhs_p[i] = sp
        sd0 = seat_map.get((db_s, c6), [0.0, 0.0, 0.0, 0, 0, 0, 0.0])
        TAIL_ib_d0[i], TAIL_yz_d0[i] = sd0[0], sd0[3]

        db_dt = datetime.date.fromisoformat(db_s)
        cut90 = (db_dt - datetime.timedelta(days=90)).isoformat()
        cut7 = (db_dt - datetime.timedelta(days=7)).isoformat()
        end_cut = f"{db_s} 09:25:00"
        nl = fine_notices.get(c6)
        if nl:
            lo = bisect.bisect_left(nl, (cut90, "", ()))
            for j in range(lo, len(nl)):
                pdt, adt, fl = nl[j]
                if pdt > end_cut:
                    break
                if adt and adt > db_s:
                    continue
                n_inv90[i] |= fl[0]; n_del90[i] |= fl[1]; n_los90[i] |= fl[2]; n_red90[i] |= fl[3]; n_buy90[i] |= fl[4]; n_win90[i] |= fl[5]
                if pdt >= cut7:
                    n_bad7[i] |= (fl[0] or fl[1] or fl[2] or fl[3])
                    n_good7[i] |= (fl[4] or fl[5])

        arr_ir = ir_grp.get(c6)
        if arr_ir is not None:
            p_hi = np.searchsorted(arr_ir, end_cut, side="left")
            p_lo30 = np.searchsorted(arr_ir, (db_dt - datetime.timedelta(days=30)).isoformat(), side="left")
            ir30[i] = int(max(0, p_hi - p_lo30))
            if p_hi > 0 and (db_dt - datetime.date.fromisoformat(arr_ir[p_hi - 1][:10])).days <= 8:
                ir8[i] = True

        arr_cm = comm_grp.get(c6)
        if arr_cm is not None:
            c_lo = np.searchsorted(arr_cm, f"{ds_s} 09:25:00", side="left")
            c_hi = np.searchsorted(arr_cm, end_cut, side="right")
            comm24[i] = int(max(0, c_hi - c_lo))

        pp = kpl_map.get((ds_s, c6), "其他")
        plate_prev.append(pp); p_sz_prev[i] = plate_day_cnt.get((ds_s, pp), 0)
        pd0 = kpl_map.get((db_s, c6), "其他")
        TAIL_plate_d0.append(pd0); TAIL_psz_d0[i] = plate_day_cnt.get((db_s, pd0), 0)

    cand["lock_top10"] = lock10_a; cand["lock_big5"] = lock5_a
    cand["real_free_mcap"] = cand["prev_mcap"].fillna(50.0) * np.maximum(0.05, 1.0 - lock10_a / 100.0)
    cand["prev_real_to"] = cand["prev_to"].fillna(5.0) / np.maximum(0.05, 1.0 - lock10_a / 100.0)
    cand["TAIL1457_day0_real_to"] = cand["to"].fillna(5.0) / np.maximum(0.05, 1.0 - lock10_a / 100.0)
    cand["inst_buy_prev"] = ib_p; cand["inst_sell_prev"] = is_p; cand["north_net_prev"] = nb_p
    cand["youzi_cnt_prev"] = yz_p; cand["quant_cnt_prev"] = qt_p; cand["lhasa_cnt_prev"] = lh_p; cand["lhasa_sh_prev"] = lhs_p
    cand["TAIL1457_inst_buy_d0"] = TAIL_ib_d0; cand["TAIL1457_youzi_d0"] = TAIL_yz_d0
    cand["n_inv90"] = n_inv90; cand["n_del90"] = n_del90; cand["n_los90"] = n_los90; cand["n_red90"] = n_red90
    cand["n_poison90"] = n_inv90 | n_del90 | n_los90 | n_red90
    cand["n_buyback90"] = n_buy90; cand["n_win90"] = n_win90; cand["n_bad7"] = n_bad7; cand["n_good7"] = n_good7
    cand["ir8"] = ir8; cand["ir30_cnt"] = ir30; cand["comm24"] = comm24
    cand["plate_prev"] = plate_prev; cand["p_sz_prev"] = p_sz_prev
    cand["TAIL1457_plate_d0"] = TAIL_plate_d0; cand["TAIL1457_psz_d0"] = TAIL_psz_d0

    # Merge Lagged Env & Real-time 0925/1457 Env
    cand = cand.merge(env_df.drop(columns=["n_zt", "n_dt", "seal_rate", "max_board", "top_cnt", "promo_1to2", "fb_open_avg", "ho_zt_r", "b3_dt_cnt", "brk_dt_r", "nuke_34"], errors="ignore"), on="dt_str", how="left")
    rt_df = pd.DataFrame.from_dict(rt_env_map, orient="index").reset_index().rename(columns={"index": "dt_str"})
    cand = cand.merge(rt_df, on="dt_str", how="left")

    # Day-0 14:57 candle geometry
    cand["TAIL1457_rebound_pct"] = (cand["close"] - cand["dt_price"]) / (cand["pre_c"] + 1e-6)
    cand["TAIL1457_is_true_yang"] = cand["close"] > cand["open"]
    cand["TAIL1457_clv"] = (cand["close"] - cand["low"]) / (cand["high"] - cand["low"] + 1e-6)
    dt_p = pd.to_datetime(cand["dt_str"])
    cand["month"] = dt_p.dt.month
    cand["weekday"] = dt_p.dt.weekday

    cand.to_parquet(f"{OUT_DIR}/full_pry_master_enriched.parquet", index=False)
    print(f"[+] Saved full_pry_master_enriched.parquet: shape={cand.shape} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
