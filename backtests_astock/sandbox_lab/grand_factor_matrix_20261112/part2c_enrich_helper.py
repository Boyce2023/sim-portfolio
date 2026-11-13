#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Part 2C: Enrich All 5 Strategy Candidate Universes (2022-01-04..2026-11-10) with All 32 1-to-2 V17 Factors."""
import os, sys, bisect, pickle, time, datetime
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from part2b_build_env_and_bars import pit_lock_lookup, OUT_DIR
from pit_aux_loaders import CSRC_PURE_OUTSIDER, HARD_TECH_RE


def enrich_candidates(cand_df, env_map, holders_idx, name_map, tape_map, lhasa_map, notice_by_c6, ir_grp, comm_grp, stock_theme_5y, csrc_zt_day_map, theme_day_meta, plate_open_peers_map):
    rows = []
    for r in cand_df.itertuples(index=False):
        c6, d_sig, d_buy = r.c6, r.sig_date, r.buy_date
        env = env_map.get(d_buy, {})
        lock10, lock5 = pit_lock_lookup(holders_idx, c6, d_buy)
        mcap = float(r.prev_mcap) if pd.notna(r.prev_mcap) else 50.0
        rf_mcap = mcap * max(0.05, 1.0 - lock10 / 100.0)
        prev_to = float(r.prev_to) if pd.notna(r.prev_to) else 8.0
        prev_real_to = prev_to / max(0.05, 1.0 - lock10 / 100.0)

        # Theme & Elo (looked up on d_sig = T-1!)
        ti = stock_theme_5y.get((d_sig, c6))
        if ti is None:
            plate, r_short, rk_c, t_sc_c, gap_c, p_elo, s_elo, p_sz, n_yz = "其他", "其他", 99, 95.0, 0.0, 100.0, 100.0, 1, 0
            has_new = own_new = is_ma_t = is_tech_c = is_earn_t = is_ev_bsk = is_broad = is_dying = False
            spark, sub_cnt = 0.0, 1
        else:
            plate, r_short = ti["plate"], ti["r_short"]
            rk_c, t_sc_c, gap_c = ti["rk_c"], ti["t_score_c"], ti["gap_c"]
            p_elo, s_elo, p_sz, n_yz = ti["p_elo"], ti["s_elo"], ti["p_sz"], ti["n_yizi"]
            has_new, own_new, spark = ti["has_new"], ti["own_new"], ti["spark"]
            is_ma_t, is_tech_c, is_earn_t = ti["is_ma"], ti["is_tech_c"], ti["is_earn"]
            is_ev_bsk, is_broad, sub_cnt, is_dying = ti["is_event_basket"], ti["is_broad_ind"], ti["sub_cluster_cnt"], ti["is_dying_pulse"]

        # PIT Notices (< d_buy 09:25:00)
        start_cut = (datetime.date.fromisoformat(d_sig) - datetime.timedelta(days=5)).isoformat()
        end_cut = f"{d_buy} 09:25:00"
        nh = n_ma = n_earn = n_bad = False
        nlist = notice_by_c6.get(c6)
        if nlist:
            lo = bisect.bisect_left(nlist, (start_cut, "", ()))
            for idx_n in range(lo, len(nlist)):
                pdt, adt, fl = nlist[idx_n]
                if pdt > end_cut:
                    break
                if adt and adt > d_buy:
                    continue
                nh |= fl[0]; n_ma |= fl[1]; n_earn |= fl[2]; n_bad |= fl[3]
        if n_bad:
            nh = False; n_ma = False

        # PIT IR Survey (past 8 days)
        has_ir = False
        arr_ir = ir_grp.get(c6)
        if arr_ir is not None:
            pos = np.searchsorted(arr_ir, end_cut, side="left")
            if pos > 0 and 0 <= (datetime.date.fromisoformat(d_buy) - datetime.date.fromisoformat(arr_ir[pos - 1][:10])).days <= 8:
                has_ir = True

        # PIT Community Heat (24h before d_buy 09:25:00)
        comm_24h = 0
        arr_cm = comm_grp.get(c6)
        if arr_cm is not None:
            c_lo = np.searchsorted(arr_cm, f"{d_sig} 09:25:00", side="left")
            c_hi = np.searchsorted(arr_cm, end_cut, side="right")
            comm_24h = int(max(0, c_hi - c_lo))

        # Tape & LHB on d_sig
        fst, seal_amt, opn_cnt = tape_map.get((d_sig, c6), ("99:99:99", 0.0, 0))
        lh_cnt, lh_sh = lhasa_map.get((d_sig, c6), (0, 0.0))

        # CSRC industry ZT count on d_sig & outsider check
        csrc = r.csrc_ind
        csrc_zt = int(csrc_zt_day_map.get(d_sig, {}).get(csrc, 0))
        csrc_sec = csrc[:3] if csrc else "UNK"
        is_ma_f = bool(is_ma_t or n_ma)
        is_outsider = bool(HARD_TECH_RE.search(str(plate)) and (csrc_sec in CSRC_PURE_OUTSIDER) and (not is_ma_f) and (not nh))

        is_gran = bool(has_new or own_new or (sub_cnt >= 2))
        s_prior = (
            (28 if rk_c == 1 else (16 if rk_c == 2 else (8 if rk_c == 3 else 0)))
            + (18 if p_sz >= 4 else (10 if p_sz >= 2 else -15))
            + (12 if has_new else 0) + (8 if own_new else 0) + (10 if spark > 0 else 0)
            + (18 if nh else 0) + (18 if is_ma_f else 0) + (12 if is_tech_c else 0)
            + (12 if gap_c >= 20.0 else 0)
            + float(np.clip((t_sc_c - 100.0) * 0.25, 0.0, 25.0))
            + float(np.clip((s_elo - 100.0) * 0.35, -10.0, 18.0))
            + (15.0 if is_gran else 0.0)
            + (10.0 if s_elo >= 105.0 else (-10.0 if s_elo <= 95.0 else 0.0))
            + (-20.0 if is_outsider else 0.0)
        )

        tmeta = theme_day_meta.get(d_sig, (0.0, False, False))
        p_open_avg, p_yz_open = plate_open_peers_map.get((d_buy, plate), (0.0, 0))

        rows.append({
            "code": c6, "name": name_map.get(c6, ""), "sig_date": d_sig, "buy_date": d_buy, "gap_days": int(r.gap_days),
            "prev_streak": int(r.prev_streak), "prev_dt_streak": int(r.prev_dt_streak), "prev_is_yizi": bool(r.prev_is_yizi),
            "open_pct": float(r.o_pct), "h_pct": float(r.h_pct), "l_pct": float(r.l_pct), "pct": float(r.pct),
            "buyable_open": bool(r.buyable_open), "is_yizi_open": bool(r.open >= r.zt_price - 0.011),
            "is_zt_today": bool(r.is_zt), "touch_zt_today": bool(r.touch_zt), "touch_dt_today": bool(r.touch_dt),
            # Macro / Regime (Group A)
            "mkt_fb_open_avg": float(env.get("fb_open_avg", 0.0)), "mkt_promo_1to2_5d": float(env.get("mkt_promo_1to2_5d", 0.20)),
            "mkt_seal_rate_prev": float(env.get("mkt_seal_rate_prev", 0.60)), "roll20_ho_zt": float(env.get("roll20_ho_zt", 0.45)),
            "mkt_max_board_prev": int(env.get("mkt_max_board_prev", 4)), "mkt_top_cnt_prev": int(env.get("mkt_top_cnt_prev", 1)),
            "prev_3b_dt_cnt": int(env.get("prev_3b_dt_cnt", 0)), "prev_break_dt_rate_10d": float(env.get("prev_break_dt_rate_10d", 0.20)),
            "prev_3to4_nuke_rate_20d": float(env.get("prev_3to4_nuke_rate_20d", 0.15)), "mkt_zt_prev": int(env.get("mkt_zt_prev", 50)),
            "mkt_dt_prev": int(env.get("mkt_dt_prev", 5)), "mkt_yizi_cnt": int(env.get("mkt_yizi_cnt", 0)),
            "csi300_ret5": float(env.get("csi300_ret5", 0.0)), "csi300_ret20": float(env.get("csi300_ret20", 0.0)), "csi300_amp20": float(env.get("csi300_amp20", 0.05)),
            # Theme & Competition (Group B)
            "plate": plate, "r_short": r_short, "rk_theme": int(rk_c), "p_elo": float(p_elo), "s_elo": float(s_elo), "p_sz": int(p_sz),
            "s_prior": round(s_prior, 2), "is_event_basket": bool(is_ev_bsk), "is_dying_pulse": bool(is_dying), "is_broad_ind": bool(is_broad),
            "sub_cluster_cnt": int(sub_cnt), "is_granularity": is_gran, "dom_gap": float(tmeta[0]), "is_dominant_day": bool(tmeta[1]),
            "is_melee_day": bool(tmeta[2]), "plate_peers_open_avg": float(p_open_avg), "plate_yizi_cnt": int(p_yz_open),
            "csrc_ind": csrc, "csrc_zt_cnt": csrc_zt, "is_pure_outsider": is_outsider,
            # Chip, Float, Micro-Tape & Notices (Group C)
            "mcap": round(mcap, 2), "lock_top10": round(lock10, 2), "lock_big5": round(lock5, 2), "real_free_mcap": round(rf_mcap, 2),
            "prev_to": round(prev_to, 2), "prev_real_to": round(prev_real_to, 2), "prev_amt": float(r.prev_amt), "prev_vol_ratio": float(r.prev_vr),
            "dd20": float(r.prev_dd20), "dd60": float(r.prev_dd60), "pos20": float(r.prev_pos20), "clean_brk60": bool(r.prev_brk60),
            "ret_pre10": float(r.prev_ret10), "zt_cnt_pre20": int(r.prev_zt20), "prior_mb_gap": int(r.prev_mb_gap),
            "first_seal_time": fst, "open_board_count": int(opn_cnt), "seal_amount": float(seal_amt), "seal_tightness": float(r.prev_tight),
            "is_hard_open_1030": bool(opn_cnt == 1 and fst <= "10:30:00"), "lhasa_seats_prev": int(lh_cnt), "lhasa_buy_share_prev": float(lh_sh),
            "has_ir_8d": has_ir, "notice_hard": nh, "notice_ma": is_ma_f, "notice_earn": bool(is_earn_t or n_earn), "notice_bad": n_bad,
            "comm_posts_24h": comm_24h,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        buy_o = np.where(out["buyable_open"], out["open_pct"], -9.99)
        out["_bo"] = buy_o
        out["true_buy_rk"] = out.groupby(["buy_date", "plate"])["_bo"].rank(ascending=False, method="min").astype(int)
        out["csrc_buy_rk"] = out.groupby(["buy_date", "csrc_ind"])["_bo"].rank(ascending=False, method="min").astype(int)
        out["mkt_open_rk"] = out.groupby("buy_date")["_bo"].rank(ascending=False, method="min").astype(int)
        out.drop(columns=["_bo"], inplace=True)
    return out
