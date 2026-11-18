#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
factor_signals.py
Extract all 27 PIT holding-period dynamic exit factors (XF01..XF27) for every trade in s_pry sub (830 rows)
across D0..T+4, strictly guarding every timestamp before decision time (T+k 09:25 or T+k 14:55).
"""
import bisect, datetime
import numpy as np
import pandas as pd
from pit_env_comm_loaders import EVENT_BASKET_PLATES


def _count_ts_in(arr, lo_ts: str, hi_ts: str) -> int:
    if arr is None or len(arr) == 0:
        return 0
    return int(np.searchsorted(arr, hi_ts, side="left") - np.searchsorted(arr, lo_ts, side="left"))


def _latest_kpl_plates(hist_list, dt: str) -> list:
    if not hist_list:
        return []
    pos = bisect.bisect_right(hist_list, (dt, ["\uffff"])) - 1
    if pos >= 0:
        p_dt, pls = hist_list[pos]
        if (datetime.date.fromisoformat(dt) - datetime.date.fromisoformat(p_dt)).days <= 180:
            return pls
    return []


def compute_all_holding_factors(sub: pd.DataFrame, cb: dict, ctx: dict) -> list[dict]:
    """
    For each row in sub (830 rows), precompute exact PIT factor dictionary per holding step off=0..4:
      - off=0: D0 close (known at D0 15:00..23:59, usable starting T+1 09:25)
      - off=1..4: T+off 09:25 (pre-open/auction) and T+off 14:55 (intraday/close)
    """
    lhb_map = ctx["lhb_map"]
    stock_notices = ctx["stock_notices"]
    ex_reg = ctx["ex_reg"]
    xq_map = ctx["xq_map"]
    gb_map = ctx["gb_map"]
    ir_map = ctx["ir_map"]
    kpl_ds = ctx["kpl_ds"]
    kpl_dp = ctx["kpl_dp"]
    kpl_hist = ctx["kpl_hist"]
    tape_map = ctx["tape_map"]
    env_map = ctx["env_map"]
    rt_map = ctx["rt_map"]
    hd_rate_map = ctx["hd_rate_map"]
    csrc_zt_map = ctx["csrc_zt_map"]
    csrc_ind_map = ctx["csrc_ind_map"]

    feats = []
    for r in sub.itertuples(index=False):
        c6 = r.code
        d = cb[c6]
        p0 = int(r.p0)
        L = len(d["dts"])
        dt0 = str(d["dts"][p0])
        ex = "SH" if c6.startswith("60") else "SZ"
        ind = csrc_ind_map.get(c6, "")

        # Pre-entry guba 20d daily baseline (strictly < dt0 09:25)
        dt0_obj = datetime.date.fromisoformat(dt0)
        gb_arr = gb_map.get(c6)
        d30_str = (dt0_obj - datetime.timedelta(days=30)).isoformat()
        gb_base_cnt = _count_ts_in(gb_arr, f"{d30_str} 00:00:00", f"{dt0} 09:25:00")
        gb_daily_base = max(1.0, gb_base_cnt / 21.0)

        # D0 candle & turnover
        d0_o, d0_h, d0_l, d0_c = float(d["open"][p0]), float(d["high"][p0]), float(d["low"][p0]), float(d["close"][p0])
        d0_clv = (d0_c - d0_l) / (d0_h - d0_l + 1e-6)
        d0_true_yang = bool(d0_c > d0_o)
        d0_real_to = float(r.TAIL1457_day0_real_to)

        rec = {
            "d0_clv": d0_clv,
            "d0_true_yang": d0_true_yang,
            "d0_ugly_fade": bool((not d0_true_yang) and (d0_clv <= 0.30) and (d0_c > float(d["dt_px"][p0]) + 0.005)),
            "d0_strong_yang": bool(d0_true_yang and (d0_clv >= 0.70)),
            "d0_real_to": d0_real_to,
            "n_buyback90": bool(r.n_buyback90),
            "n_win90": bool(r.n_win90),
            "ir8": bool(r.ir8),
            "ir30_cnt": int(r.ir30_cnt),
            "steps": {},
        }

        # Cumulative LHB trackers from D0..T+k-1
        cum_lhasa_max_cnt = 0
        cum_lhasa_max_sh = 0.0
        cum_daysurf = False
        cum_inst_net = 0.0
        cum_inst_buy = 0.0
        cum_inst_sell = 0.0
        cum_yz_buy = False
        cum_yz_sell = False
        cum_quant_cnt = 0
        cum_big_net_sell = False
        cum_north_neg = False
        cum_bad_notice = False
        cum_hard_bad_notice = False
        cum_good_notice = bool(r.n_buyback90 or r.n_win90)
        cum_ir = bool(r.ir30_cnt > 0)

        for off in range(0, 5):
            pk = p0 + off
            if pk >= L:
                break
            dt_k = str(d["dts"][pk])
            dt_prev = str(d["dts"][pk - 1]) if pk >= 1 else dt_k

            # Compute day pk's seal tightness if ZT
            d_dip = (float(d["low"][pk]) - float(d["pre_c"][pk])) / (float(d["pre_c"][pk]) + 1e-6)
            d_ent = (float(d["close"][pk]) - float(d["open"][pk])) / (float(d["pre_c"][pk]) + 1e-6)
            to_ma5 = float(np.mean(d["to"][max(0, pk - 5):pk])) if pk > 0 else float(d["to"][pk])
            to_vr = float(d["to"][pk]) / (to_ma5 + 1e-6)
            seal_tight = (
                (30.0 if abs(float(d["close"][pk]) - float(d["high"][pk])) < 1e-6 else 0.0)
                + float(np.clip(d_dip * 100.0, -10.0, 10.0)) * 1.5
                + float(np.clip(d_ent * 100.0, 0.0, 10.0)) * 2.0
                - (15.0 if to_vr > 4.0 else 0.0)
            )
            tp = tape_map.get((dt_k, c6))
            obc = tp[2] if tp is not None else 0
            pls_k = kpl_ds.get((dt_k, c6), [])
            is_event_only = bool(pls_k) and all(p in EVENT_BASKET_PLATES for p in pls_k)
            lhb_k = lhb_map.get((dt_k, c6))
            lhasa_k = lhb_k["lhasa_buy_cnt"] if lhb_k else 0

            # Pre-open checks at off >= 1 (using info strictly < dt_k 09:25 and prior day close dt_prev)
            step_d = {
                "dt": dt_k,
                "to_vr": to_vr,
                "seal_tight": seal_tight,
                "open_board_cnt": obc,
                "is_event_only": is_event_only,
                "tight_good_zt": bool(d["is_zt"][pk] and seal_tight >= 37.0 and (not is_event_only) and lhasa_k == 0),
                "loose_bad_zt": bool(d["is_zt"][pk] and (seal_tight < 37.0 or is_event_only or lhasa_k >= 1)),
            }

            if off >= 1:
                # 1. Prior day (dt_prev) LHB -> update cum trackers for T+off 09:25
                lp = lhb_map.get((dt_prev, c6))
                if lp is not None:
                    cum_lhasa_max_cnt = max(cum_lhasa_max_cnt, lp["lhasa_buy_cnt"])
                    cum_lhasa_max_sh = max(cum_lhasa_max_sh, lp["lhasa_buy_sh"])
                    cum_daysurf |= lp["daysurf_buy"]
                    cum_inst_net += lp["inst_net"]
                    cum_inst_buy += lp["inst_buy"]
                    cum_inst_sell += lp["inst_sell"]
                    cum_yz_buy |= lp["top_yz_buy"]
                    cum_yz_sell |= lp["top_yz_sell"]
                    cum_quant_cnt = max(cum_quant_cnt, lp["quant_cnt"])
                    if lp["tot_sell"] > lp["tot_buy"] * 1.2:
                        cum_big_net_sell = True
                    if lp["north_net"] < 0:
                        cum_north_neg = True

                # 2. Notices strictly in [dt0 15:00:00, dt_k 09:25:00)
                nl = stock_notices.get(c6)
                if nl:
                    lo_n = bisect.bisect_left(nl, (f"{dt0} 15:00:00", False, False, False, ""))
                    for j in range(lo_n, len(nl)):
                        pdt, ib, ihb, ig, _ = nl[j]
                        if pdt >= f"{dt_k} 09:25:00":
                            break
                        cum_bad_notice |= ib
                        cum_hard_bad_notice |= ihb
                        cum_good_notice |= ig

                # 3. Exchange reg5 strictly <= dt_prev
                w5_lo = (datetime.date.fromisoformat(dt_prev) - datetime.timedelta(days=7)).isoformat()
                ex_cnt = len({c for d_r, c in ex_reg[ex] if w5_lo <= d_r <= dt_prev})

                # 4. Community strictly < dt_k 09:25:00
                xq_post_cnt = _count_ts_in(xq_map.get(c6), f"{dt0} 09:25:00", f"{dt_k} 09:25:00")
                gb_overnight = _count_ts_in(gb_arr, f"{dt_prev} 09:25:00", f"{dt_k} 09:25:00")
                gb_ratio = gb_overnight / gb_daily_base
                ir_post = _count_ts_in(ir_map.get(c6), f"{dt0} 09:25:00", f"{dt_k} 09:25:00")
                if ir_post > 0:
                    cum_ir = True

                # 5. Market 09:25 rt_env & prior close env
                rt_k = rt_map.get(dt_k, {})
                env_k = env_map.get(dt_k, {})
                env_p = env_map.get(dt_prev, {})
                hd_p = hd_rate_map.get(dt_prev, {})

                # 6. KPL / CSRC plate ZT mates on dt_prev
                my_pls = kpl_ds.get((dt_prev, c6)) or _latest_kpl_plates(kpl_hist.get(c6), dt_prev)
                kpl_mates = 0
                for pl in my_pls:
                    kpl_mates = max(kpl_mates, len(kpl_dp.get((dt_prev, pl), set()) - {c6}))
                csrc_mates = max(0, int(csrc_zt_map.get(dt_prev, {}).get(ind, 0)) - (1 if d["is_zt"][pk - 1] else 0)) if ind else 0

                # 7. Pre-market MA5 and MA10 in day pk scale
                af_k = float(d["adjf"][pk])
                lo5 = max(0, pk - 5)
                lo10 = max(0, pk - 10)
                ma5_k = float(np.mean(d["close"][lo5:pk] * (d["adjf"][lo5:pk] / af_k)))
                ma10_k = float(np.mean(d["close"][lo10:pk] * (d["adjf"][lo10:pk] / af_k)))
                o_gap = float(d["open"][pk]) / float(d["pre_c"][pk]) - 1.0
                o_vs_buy = (float(d["open"][pk]) * af_k / float(d["adjf"][p0])) / float(r.buy_px) - 1.0

                step_d.update({
                    # LHB (cumulative up to dt_prev, and D0 snapshot separately available in steps[1])
                    "lhasa_cnt": cum_lhasa_max_cnt,
                    "lhasa_sh": cum_lhasa_max_sh,
                    "lhasa_d0": lhb_map.get((dt0, c6), {}).get("lhasa_buy_cnt", 0),
                    "daysurf": cum_daysurf,
                    "inst_net": cum_inst_net,
                    "inst_buy": cum_inst_buy,
                    "inst_sell": cum_inst_sell,
                    "yz_buy": cum_yz_buy,
                    "yz_sell": cum_yz_sell,
                    "quant_cnt": cum_quant_cnt,
                    "big_net_sell": cum_big_net_sell,
                    "north_neg": cum_north_neg,
                    # Notices / Reg / Comm / IR
                    "bad_notice": cum_bad_notice,
                    "hard_bad_notice": cum_hard_bad_notice,
                    "good_notice": cum_good_notice,
                    "ex_reg5": ex_cnt,
                    "xq_cnt": xq_post_cnt,
                    "gb_overnight": gb_overnight,
                    "gb_ratio": gb_ratio,
                    "ir_active": cum_ir,
                    # Market 09:25 & prior close env
                    "mkt_open_zt": int(rt_k.get("mkt_open_zt_0925", 10)),
                    "mkt_open_dt": int(rt_k.get("mkt_open_dt_0925", 0)),
                    "mkt_open_avg": float(rt_k.get("mkt_open_avg_0925", 0.0)),
                    "fb_open_avg": float(env_k.get("fb_open_avg", 0.0)),
                    "prev_brk_dt_r": float(env_p.get("brk_dt_r", 0.0) if pd.notna(env_p.get("brk_dt_r")) else 0.0),
                    "prev_nuke_34": float(env_p.get("nuke_34", 0.0) if pd.notna(env_p.get("nuke_34")) else 0.0),
                    "prev_csi_pct": float(env_p.get("csi_pct", 0.0) if pd.notna(env_p.get("csi_pct")) else 0.0),
                    "prev_n_dt": int(env_p.get("n_dt", 10)),
                    "prev_n_zt": int(env_p.get("n_zt", 40)),
                    "prev_promo": float(env_p.get("promo_1to2", 0.20)),
                    "prev_promo_5d": float(env_p.get("mkt_promo_1to2_5d", 0.20)),
                    "hd_brk_r10": float(hd_p.get("brk_r10", 0.20)),
                    "hd_reb_zt_r10": float(hd_p.get("reb_zt_r10", 0.15)),
                    "hd_reb_pos_r10": float(hd_p.get("reb_pos_r10", 0.40)),
                    "kpl_mates": kpl_mates,
                    "csrc_mates": csrc_mates,
                    # Micro price / MA
                    "o_gap": o_gap,
                    "o_vs_buy": o_vs_buy,
                    "ma5_px": ma5_k,
                    "ma10_px": ma10_k,
                })
            rec["steps"][off] = step_d
        feats.append(rec)
    return feats
