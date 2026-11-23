# -*- coding: utf-8 -*-
"""
v19_data_adapter.py: V19.1 题库底层数据与撮合适配器
直接复用 upgrade_1to2_pit 唯一真源，并叠加 V19.1 红队物理真账校准（15:00跌停顺延 + 除权因子复权 + 对齐 ledger_1to2_v19_clean.csv）。
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from collections import defaultdict

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
CURR_DIR = os.path.dirname(ASSETS_DIR)
SIM_DIR = os.path.dirname(CURR_DIR)
UPG_DIR = os.path.join(SIM_DIR, "backtests_astock", "clean_3strategies_mutual_upgrade_20261117")
PARTC_DIR = os.path.join(SIM_DIR, "backtests_astock", "redteam_full_audit_20261123", "partC_clean_ledgers_v191")
for _p in (ASSETS_DIR, CURR_DIR, UPG_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import upgrade_1to2_pit as u12
from v191_dt_defer_helper import load_dt_defer_tables, defer_eod_limit_down, calc_adj_net_ret

CSRC_L2_CSV = os.path.join(SIM_DIR, "data", "csrc_industry_l2.csv")
KPL_5Y_PATH = os.path.join(SIM_DIR, "data", "kpl_plates_5y_2021_2026_complete.jsonl")
SH_PKL_PATH = os.path.join(ASSETS_DIR, "astock2_sh_daily.pkl")
CLEAN_1TO2_CSV = os.path.join(PARTC_DIR, "ledger_1to2_v19_clean.csv")


def _load_kpl_metadata():
    r_long_map = {}
    plate_daily_sz = defaultdict(dict)
    kpl_dates = []
    if os.path.exists(KPL_5Y_PATH):
        with open(KPL_5Y_PATH, "r", encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                d = json.loads(ln)
                dt = d["date"]
                kpl_dates.append(dt)
                for p in d.get("plates", []):
                    pname = p.get("plate", "")
                    stocks = p.get("stocks", [])
                    plate_daily_sz[dt][pname] = len(stocks)
                    for s in stocks:
                        c6 = str(s[0]).strip()[:6].zfill(6)
                        rl = str(s[3]).strip() if len(s) > 3 else ""
                        r_long_map[(dt, c6)] = rl
    return r_long_map, plate_daily_sz, kpl_dates


def _load_sh_index_series():
    df_sh = pd.read_pickle(SH_PKL_PATH)
    df_sh["date_str"] = df_sh["date"].dt.strftime("%Y-%m-%d")
    df_sh = df_sh.sort_values("date").reset_index(drop=True)
    sh_date_to_idx = {r.date_str: i for i, r in enumerate(df_sh.itertuples())}
    sh_rows = [[round(float(r.open), 2), round(float(r.high), 2), round(float(r.low), 2), round(float(r.close), 2), round(float(r.volume / 1e8), 2)] for r in df_sh.itertuples()]
    return df_sh, sh_date_to_idx, sh_rows


def load_v19_trainer_context():
    ctx = u12.build_signals_and_data_pit("2026-11-16")
    df_daily, _, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = u12.load_full_prices_pit("2026-11-16")
    all_dts = ctx["all_dts"]
    dt_to_idx = ctx["dt_to_idx"]
    bars_5m_map = ctx["bars_5m_map"]

    price_lookup_9 = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt, r.volume)
        for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt", "volume"]].itertuples(index=False)
    }
    is_new = (df_daily["c6"].values != np.roll(df_daily["c6"].values, 1))
    is_new[0] = True
    is_zt_arr = df_daily["is_zt"].values
    consec_arr = np.zeros(len(df_daily), dtype=np.int32)
    cur_consec = 0
    for i in range(len(df_daily)):
        cur_consec = int(is_zt_arr[i]) if (is_new[i] or not is_zt_arr[i]) else (cur_consec + 1)
        consec_arr[i] = cur_consec
    df_daily["consec_zt"] = consec_arr

    fb_valid = df_daily[df_daily["is_first_board"] & (~df_daily["is_yizi"])]
    fb_cnt_map = fb_valid.groupby("dt_str")["c6"].count().to_dict()
    d1_fb_open_map = fb_valid.groupby("dt_str")["d2_o_pct"].mean().to_dict()
    max_height_map = df_daily.groupby("dt_str")["consec_zt"].max().to_dict()
    stk_hist = defaultdict(list)
    for r in df_daily[["c6", "dt_str", "open", "high", "low", "close", "volume", "is_zt"]].itertuples(index=False):
        stk_hist[r.c6].append(r)

    r_long_map, plate_daily_sz, kpl_dates = _load_kpl_metadata()
    _, sh_date_to_idx, sh_rows = _load_sh_index_series()

    hf = ctx["hist_fb"].copy()
    ind_l2 = pd.read_csv(CSRC_L2_CSV)
    ind_l2["c6"] = ind_l2["code"].astype(str).str[-6:].str.zfill(6)
    name_map = dict(zip(ind_l2["c6"], ind_l2["code_name"].fillna("")))
    hf["name"] = [nm if nm else name_map.get(c6, c6) for nm, c6 in zip(hf["name"].astype(str), hf["c6"])]
    hf["r_long"] = [r_long_map.get((d1, c6), "") for d1, c6 in zip(hf["dt_str"], hf["c6"])]
    hf["is_st"] = hf["name"].astype(str).str.contains("ST|退", case=False, regex=True)
    hf["is_hard_turnover"] = (hf["open_board_count"].fillna(0) == 1) & (hf["first_seal_time"].fillna("99:99:99") <= "10:30:00") & (hf["d1_seal_tightness"] >= 38.0)

    csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hf["csrc_ind"]]
    ht_pat = r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)"
    is_ht = hf["plate"].astype(str).str.contains(ht_pat, regex=True).values
    hf["is_hard_tech"] = is_ht
    hf["is_outsider_pen"] = np.array([h and (cs in u12.CSRC_PURE_OUTSIDER) and (not hm) for h, cs, hm in zip(is_ht, csrc_sec, (hf["notice_hard"] | hf["is_ma"]).values)], dtype=bool)

    valid_plate = hf[(hf["plate"] != "其他") & (~hf["is_event_basket"])].copy()
    pg = valid_plate.groupby(["d2_dt", "plate"], as_index=False).agg(p_sz_max=("p_sz", "max"), p_theme_med=("s_prior_dual", "median"))
    pg_m = pg[pg["p_sz_max"] >= 2].copy()
    hf = hf.merge(pg_m[["d2_dt", "plate", "p_theme_med"]], on=["d2_dt", "plate"], how="left")

    daily_recs = []
    for d, grp in hf.groupby("d2_dt"):
        ho = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"]) & (grp["d2_o_pct"] >= 0.055)]
        daily_recs.append({"date": d, "r": (ho["d2_is_zt"].sum() / len(ho)) if len(ho) > 0 else np.nan})
    ds_s = pd.DataFrame(daily_recs).sort_values("date").reset_index(drop=True)
    ds_s["r20"] = ds_s["r"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    cold_map = {r.date: (r.r20 < 0.45) for r in ds_s.itertuples(index=False)}
    hf["weak_open_sensor_cold"] = hf["d2_dt"].map(cold_map).fillna(False)
    hf["is_melee_day"] = False
    hf["is_dom_no_dragon"] = False

    hf["sc_v"] = hf["score_active"]
    hf["v19_tot"] = ctx["mask_v19"]
    hf["v19_sv"] = hf["_sv_v19"]
    hf["v18_tot"] = ctx["mask_v19"]
    hf["v18_sv"] = hf["_sv_v19"]
    hf["v16_tot"] = ctx["mask_v19"]
    hf["v16_sv"] = hf["_sv_v19"]
    hf["is_fb_dom295"] = ctx["mask_v19"] & (~ctx["mask_v18"])

    wk = hf["gap_days"] >= 3
    pure_win = hf["is_buyable_open"] & ((wk & hf["d2_o_pct"].between(0.020, 0.088)) | ((~wk) & hf["d2_o_pct"].between(0.022, 0.078)))
    c_t1 = hf["v19_tot"]
    c_t2 = hf["gate_ok"] & pure_win & (~c_t1)
    c_t3 = hf["gate_ok"] & hf["is_buyable_open"] & (~pure_win) & (hf["d2_o_pct"] >= 0.0) & (~c_t1)
    hf["sys_rank_score"] = np.where(c_t1, 10000.0 + hf["v19_sv"], np.where(c_t2, 5000.0 + hf["sc_v"], np.where(c_t3, 2000.0 + hf["sc_v"], hf["sc_v"])))

    sim_raw = u12.make_trade_sim(ctx, use_m1_d3_exempt=True)
    dt_tables = load_dt_defer_tables()
    clean_df = pd.read_csv(CLEAN_1TO2_CSV, dtype={"code": str})
    clean_df["c6"] = clean_df["code"].astype(str).str.zfill(6)
    clean_map = {(str(r.buy_date), str(r.c6)): r for r in clean_df.itertuples(index=False)}

    def engine_fn(row_obj):
        row_d = row_obj._asdict() if hasattr(row_obj, "_asdict") else (row_obj.to_dict() if hasattr(row_obj, "to_dict") else dict(row_obj))
        res = sim_raw(row_d)
        c6, d2 = row_d["c6"], row_d["d2_dt"]
        if res is None:
            trig_p = float(row_d["trig_p"])
            arr2 = bars_5m_map.get((c6, d2))
            if arr2 is not None and len(arr2) > 0:
                ign, am_h = None, float(row_d.get("d2_open", 0.0))
                for bi in range(len(arr2)):
                    if int(arr2[bi, 0]) <= 1130 and float(arr2[bi, 2]) > am_h:
                        am_h = float(arr2[bi, 2])
                    if ign is None and float(arr2[bi, 2]) >= trig_p - 1e-4:
                        ign = int(arr2[bi, 0])
                if ign is not None and ign > 1130:
                    return {"executed": False, "tag": "pm_cancel_1130", "am_high": round(am_h, 2)}
            return None

        res = dict(res)
        tag = res.get("tag", "eod_close")
        ehh = int(res.get("exit_hhmm", 925 if res.get("exit_at_open") else 1500))
        if tag in ("eod_close", "eod_break", "nshape_d3_close"):
            ehh = 1500
        adj_nr = calc_adj_net_ret(c6, d2, float(res["buy_price"]), str(res["exit_date"]), float(res["exit_price"]), dt_tables, 0.0020)
        if adj_nr is not None:
            res["net_ret"] = round(adj_nr, 4)
        ned, neh, nep, nret, dt_def = defer_eod_limit_down(
            c6, d2, float(res["buy_price"]), str(res["exit_date"]), ehh, float(res["exit_price"]), float(res["net_ret"]), dt_tables, 0.0020
        )
        if dt_def:
            res["exit_date"] = ned
            res["exit_hhmm"] = neh
            res["exit_price"] = nep
            res["net_ret"] = round(nret, 4)
            res["exit_at_open"] = True
            res["tag"] = "eod_dt_defer_open"

        lt = clean_map.get((d2, c6))
        if lt is not None:
            res["exit_date"] = str(lt.exit_date)
            res["exit_hhmm"] = int(lt.exit_hhmm)
            res["exit_price"] = round(float(lt.exit_price), 2)
            res["net_ret"] = float(lt.net_ret)
            res["exit_at_open"] = bool(lt.exit_at_open)
            res["tag"] = str(lt.tag)

        idx2, idx_e = dt_to_idx[d2], dt_to_idx.get(res["exit_date"], dt_to_idx[d2] + 1)
        fh = 2 if res["sealed_2b"] else 1
        for k in range(idx2 + 1, idx_e):
            b = price_lookup_9.get((c6, all_dts[k]))
            if b and b[6]:
                fh += 1
        res["final_height"] = fh
        res["m1_exempt"] = False
        if res["sealed_2b"] == 1 and res["tag"] == "eod_close" and idx2 + 1 < len(all_dts):
            d3 = all_dts[idx2 + 1]
            arr3 = bars_5m_map.get((c6, d3))
            if arr3 is not None and len(arr3) >= 12:
                cv = ca = 0.0
                for row5 in arr3:
                    cv += row5[5]; ca += row5[6]
                    if int(row5[0]) == 1030:
                        vw = ca / cv if cv > 0 else row5[4]
                        if row5[4] < vw:
                            res["m1_exempt"] = True
                        break
        return res

    return {
        "hist_fb": hf, "engine_fn": engine_fn, "stk_hist": stk_hist,
        "all_dts": all_dts, "dt_to_idx": dt_to_idx, "price_lookup": price_lookup_9,
        "zt_cnt_map": zt_cnt_map, "dt_cnt_map": dt_cnt_map, "fb_cnt_map": fb_cnt_map,
        "seal_rate_map": seal_rate_map, "promo_ma5_map": promo_ma5_map,
        "max_height_map": max_height_map, "d1_fb_open_map": d1_fb_open_map,
        "sh_date_to_idx": sh_date_to_idx, "sh_rows": sh_rows,
        "plate_daily_sz": plate_daily_sz, "kpl_dates": kpl_dates,
    }
