#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Final V1.1 Red-Team Audits: 8-test overfitting suite, kline/ex-div/DT-deferral integrity, & V19.1 empty-slot test."""
import itertools, math, pickle, sqlite3, sys
import numpy as np
import pandas as pd
import scipy.stats as stats

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
V191_PATH = f"{BASE}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_combined_5strat_v191_slot1_clean.csv"
sys.path.insert(0, PART2_DIR)
from backtest_utils import _sim_k_slots, bench_return, ew20_bench_return
from v11_core import V11_EXIT_CFG, sim_v11_exit


def calc_cap10m(rets: np.ndarray, init_w: float = 100.0, cap_w: float = 1000.0) -> float:
    cap = init_w
    for r in rets:
        cap += min(cap, cap_w) * float(r)
    return round(cap / init_w, 3)


def eval_window(tr_sub: pd.DataFrame, sh300: dict, ew20: dict, sdt: str, edt: str, ex924: bool = False) -> dict:
    sub = tr_sub[(tr_sub["buy_date"] >= sdt) & (tr_sub["buy_date"] <= edt)].copy() if not tr_sub.empty else pd.DataFrame()
    if ex924 and not sub.empty:
        sub = sub[~sub["sig_date"].between("2024-09-24", "2024-10-08")]
    if ex924:
        dts = sorted(d for d in sh300 if sdt <= d <= edt and not ("2024-09-24" <= d <= "2024-10-08"))
        hs_r = float(np.prod([sh300[d] / sh300[prev] for prev, d in zip(dts[:-1], dts[1:])]) - 1.0) if len(dts) > 1 else 0.0
        ew_r = float(np.prod([1.0 + ew20[d] for d in ew20 if sdt <= d <= edt and not ("2024-09-24" <= d <= "2024-10-08")]) - 1.0)
    else:
        hs_r = bench_return(sh300, sdt, edt)
        ew_r = ew20_bench_return(ew20, sdt, edt)
    if sub.empty:
        return {"raw_n": 0, "n_1s": 0, "nav_1s": 1.0, "cap10m_1s": 1.0, "hs300_ret": round(hs_r * 100, 2), "ew20_ret": round(ew_r * 100, 2)}
    t1, nav1, mdd1 = _sim_k_slots(sub, 1)
    t3, nav3, mdd3 = _sim_k_slots(sub, 3)
    ew_nav = float(np.prod(1.0 + sub.groupby("buy_date")["net_ret"].mean().to_numpy(dtype=float)))
    r1 = t1["net_ret_eval"].to_numpy(dtype=float)
    w1, l1 = r1[r1 > 0], r1[r1 <= 0]
    po1 = float(w1.mean() / abs(l1.mean())) if (len(w1) and len(l1) and l1.mean() < 0) else (99.0 if len(w1) else 0.0)
    ex5 = float(np.prod(1.0 + np.sort(r1)[:-5])) if len(r1) > 5 else 1.0
    ex10 = float(np.prod(1.0 + np.sort(r1)[:-10])) if len(r1) > 10 else 1.0
    return {
        "raw_n": int(len(sub)), "days": int(sub["buy_date"].nunique()),
        "n_1s": int(len(t1)), "wr_1s": round(float((r1 > 0).mean() * 100), 2), "po_1s": round(po1, 2),
        "mean_1s": round(float(r1.mean() * 100), 2), "nav_1s": round(nav1, 3), "mdd_1s": round(mdd1 * 100, 2),
        "cap10m_1s": calc_cap10m(r1), "ex5_1s": round(ex5, 3), "ex10_1s": round(ex10, 3),
        "n_3s": int(len(t3)), "wr_3s": round(float((t3["net_ret_eval"] > 0).mean() * 100), 2),
        "nav_3s": round(nav3, 3), "mdd_3s": round(mdd3 * 100, 2), "ew_nav": round(ew_nav, 3),
        "hs300_ret": round(hs_r * 100, 2), "ew20_ret": round(ew_r * 100, 2),
        "ex_hs300_1s": round((nav1 - 1.0 - hs_r) * 100, 2), "ex_ew20_1s": round((nav1 - 1.0 - ew_r) * 100, 2),
    }


def overfitting_suite_v11(label: str, pool: pd.DataFrame, fm: pd.DataFrame, thr: float, all_sig: pd.DataFrame, sh300: dict, all_dts: list[str]) -> dict:
    tr_raw = all_sig[all_sig["score"] >= thr].copy()
    t1, nav1, _ = _sim_k_slots(tr_raw, 1)
    n = len(t1)
    ex = np.array([float(r.net_ret_eval) - bench_return(sh300, str(r.buy_date), str(r.exit_date)) for r in t1.itertuples(index=False)], dtype=float)
    sr_tr = float(ex.mean() / ex.std(ddof=1)) if n > 1 else 0.0
    t_tr = float(sr_tr * np.sqrt(n))

    t_days = [d for d in sorted(all_dts) if "2021-01-04" <= d <= "2026-11-23"]
    day_idx = {d: i for i, d in enumerate(t_days)}

    def _build_d(led):
        arr = np.zeros(len(t_days), dtype=float)
        for r in led.itertuples(index=False):
            i = day_idx.get(str(r.exit_date))
            if i is not None: arr[i] += float(r.net_ret_eval)
        return arr

    d_arr = _build_d(t1)
    sr_d = float(d_arr.mean() / d_arr.std(ddof=1)) if d_arr.std(ddof=1) > 1e-12 else 0.0
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(ex, fisher=False, bias=False))) if n > 3 else 3.0
    gm = 0.5772156649
    dsr = {}
    for M in (30, 150, 200):
        sr0 = (1.0 / math.sqrt(max(n - 1, 1))) * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / M) + gm * stats.norm.ppf(1.0 - 1.0 / (M * math.e)))
        den = math.sqrt(max(1e-12, 1.0 - sk * sr_tr + ((ku - 1.0) / 4.0) * (sr_tr ** 2)))
        dsr[f"M{M}"] = round(float(stats.norm.cdf((sr_tr - sr0) * math.sqrt(max(n - 1, 1)) / den)), 4)

    rng = np.random.default_rng(20261124)
    bg_rets = all_sig["net_ret"].to_numpy(dtype=float)
    monkey_p = round((sum(1 for _ in range(5000) if np.prod(1.0 + rng.choice(bg_rets, size=n, replace=True)) >= nav1) + 1) / 5001, 5)

    def _cscv(R, ng):
        gs = len(t_days) // ng
        gidx = [list(range(i * gs, (i + 1) * gs if i < ng - 1 else len(t_days))) for i in range(ng)]
        omegas = []
        for te in itertools.combinations(range(ng), ng // 2):
            trg = [k for k in range(ng) if k not in te]
            tri = [x for k in trg for x in gidx[k]]; tei = [x for k in te for x in gidx[k]]
            rt, re_ = R[tri], R[tei]
            sd_t, sd_e = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sd_t, out=np.zeros_like(sd_t), where=sd_t > 1e-12)
            se = np.divide(re_.mean(0), sd_e, out=np.zeros_like(sd_e), where=sd_e > 1e-12)
            b = int(np.argmax(st))
            omegas.append(float(np.mean(se > se[b])))
        return {"pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2), "mean_rank_oos": round(float(np.mean(omegas)), 4)}

    R_w = np.column_stack([_build_d(_sim_k_slots(all_sig[all_sig["score"] >= t_i], 1)[0]) for t_i in [70, 72, 74, 76, 78, 80, 82]])
    R_l = np.column_stack([_build_d(_sim_k_slots(all_sig[all_sig["score"] >= t_i], 1)[0]) for t_i in [int(thr + d) for d in (-4, -2, 0, 2, 4)]])
    R_l1 = np.column_stack([_build_d(_sim_k_slots(all_sig[all_sig["score"] >= t_i], 1)[0]) for t_i in [int(thr + d) for d in range(-4, 5)]])
    sc_sub = all_sig[all_sig["score"] >= thr]["score"]
    R_q = np.column_stack([d_arr] + [_build_d(_sim_k_slots(all_sig[all_sig["score"] >= float(np.quantile(sc_sub, 0.05 + (v / 14.0) * 0.40))], 1)[0]) for v in range(1, 14)])

    fm_mat = all_sig[list(fm.columns)].to_numpy(dtype=float)
    mc_navs, mc_is, mc_oos = [], [], []
    for _ in range(200):
        scp = 70.0 + fm_mat @ rng.uniform(0.80, 1.20, size=fm_mat.shape[1])
        sp = all_sig[scp >= thr]
        mc_navs.append(_sim_k_slots(sp, 1)[1])
        mc_is.append(_sim_k_slots(sp[sp["buy_date"] <= "2024-08-31"], 1)[1])
        mc_oos.append(_sim_k_slots(sp[sp["buy_date"] >= "2024-09-01"], 1)[1])

    margin = max(5.0, thr - 70.0)
    th_pert = {}
    for d_lbl, th_v in [("-20%", round(70 + margin * 0.8)), ("-10%", round(70 + margin * 0.9)), ("base", thr), ("+10%", round(70 + margin * 1.1)), ("+20%", round(70 + margin * 1.2))]:
        s_th = all_sig[all_sig["score"] >= th_v]
        th_pert[d_lbl] = {"th": th_v, "full_1s": round(_sim_k_slots(s_th, 1)[1], 2), "is_1s": round(_sim_k_slots(s_th[s_th["buy_date"] <= "2024-08-31"], 1)[1], 2), "oos_1s": round(_sim_k_slots(s_th[s_th["buy_date"] >= "2024-09-01"], 1)[1], 2)}

    pool_sub = pool[pool["score"] >= thr].copy()
    pt2_tr = sim_v11_exit(pool_sub, {"b3_tp_mode": "none", "b2_mode": "d2_close", "zt_imm": False, "risk_mode": "none"}, fee=0.0030, tp_buf=0.0030)
    pt2_is = _sim_k_slots(pt2_tr[pt2_tr["buy_date"] <= "2024-08-31"], 1)[1]
    pt2_oos = _sim_k_slots(pt2_tr[pt2_tr["buy_date"] >= "2024-09-01"], 1)[1]
    ex_grid = [
        ("adapt_k=1.2(-20%)", {**V11_EXIT_CFG, "b3_adapt_k": 1.2}), ("adapt_k=1.8(+20%)", {**V11_EXIT_CFG, "b3_adapt_k": 1.8}),
        ("b2_tp=0.096(-20%)", {**V11_EXIT_CFG, "b2_tp": 0.096}), ("b2_tp=0.144(+20%)", {**V11_EXIT_CFG, "b2_tp": 0.144}),
        ("b2_body=0.048(-20%)", {**V11_EXIT_CFG, "b2_body": 0.048}), ("b2_body=0.072(+20%)", {**V11_EXIT_CFG, "b2_body": 0.072}),
        ("b2_clv=0.52(-20%)", {**V11_EXIT_CFG, "b2_clv": 0.52}), ("b2_clv=0.78(+20%)", {**V11_EXIT_CFG, "b2_clv": 0.78}),
    ]
    ex_plat, beat_both = [], 0
    for e_nm, e_cfg in ex_grid:
        etr = sim_v11_exit(pool_sub, e_cfg, fee=0.0030, tp_buf=0.0030)
        eis = _sim_k_slots(etr[etr["buy_date"] <= "2024-08-31"], 1)[1]
        eoo = _sim_k_slots(etr[etr["buy_date"] >= "2024-09-01"], 1)[1]
        efu = _sim_k_slots(etr, 1)[1]
        ok = (eis > pt2_is) and (eoo > pt2_oos)
        beat_both += int(ok)
        ex_plat.append({"param": e_nm, "is_1s": round(eis, 2), "oos_1s": round(eoo, 2), "full_1s": round(efu, 2), "beat_pure_t2_both": ok})

    return {
        "label": label, "hlz_t_trade": round(t_tr, 2), "hlz_t_daily": round(sr_d * math.sqrt(len(d_arr)), 2),
        "sr_annual_daily": round(sr_d * math.sqrt(242), 3), "dsr_M30": dsr["M30"], "dsr_M150": dsr["M150"], "dsr_M200": dsr["M200"],
        "monkey_p": monkey_p,
        "cscv_wide_S8": _cscv(R_w, 8), "cscv_wide_S10": _cscv(R_w, 10),
        "cscv_loc_step2_S8": _cscv(R_l, 8), "cscv_loc_step2_S10": _cscv(R_l, 10),
        "cscv_loc_step1_S8": _cscv(R_l1, 8), "cscv_loc_step1_S10": _cscv(R_l1, 10),
        "cscv_q14_S8": _cscv(R_q, 8), "cscv_q14_S10": _cscv(R_q, 10),
        "weight_mc_200": {
            "full_p10": round(float(np.percentile(mc_navs, 10)), 2), "full_med": round(float(np.median(mc_navs)), 2),
            "is_p10": round(float(np.percentile(mc_is, 10)), 2), "oos_p10": round(float(np.percentile(mc_oos, 10)), 2),
            "oos_med": round(float(np.median(mc_oos)), 2),
            "prob_oos_gt_2x_pct": round(float((np.array(mc_oos) > 2.0).mean() * 100.0), 1),
        },
        "threshold_pm20": th_pert,
        "exit_param_pm20_plateau": {"pass_rate_pct": round(beat_both / len(ex_grid) * 100.0, 1), "pure_t2_is": round(pt2_is, 2), "pure_t2_oos": round(pt2_oos, 2), "cases": ex_plat},
    }


def kline_exdiv_dt_audit(slot_A: pd.DataFrame, slot_S: pd.DataFrame, all_sig: pd.DataFrame) -> dict:
    con_k = sqlite3.connect(f"file:{BASE}/data/kline_cache.db?mode=ro", uri=True)
    k_df = pd.read_sql_query("SELECT code as c6, date as buy_date, open as k_open FROM daily_kline", con_k)
    con_k.close()
    da = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_daily.parquet", columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"])
    dd = pd.read_parquet(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"])
    da["c6"] = da["ticker"].str[:6]; dd["c6"] = dd["ticker"].str[:6]
    cset = set(all_sig["c6"].astype(str).str.zfill(6))
    dall = pd.concat([da[da["c6"].isin(cset)], dd[dd["c6"].isin(cset)]], ignore_index=True)
    dall["dt"] = dall["date"].dt.strftime("%Y-%m-%d")
    dall = dall.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    dall["prev_c_adj"] = dall.groupby("c6")["close"].shift(1) * dall["qfq_factor"] / dall.groupby("c6")["qfq_factor"].shift(1)
    q_levels = dall[dall["dt"] >= "2025-01-01"].groupby("c6")["qfq_factor"].unique().to_dict()
    bar_m = {(r.c6, r.dt): r for r in dall.itertuples(index=False)}

    m_k = all_sig.assign(c6=all_sig["c6"].astype(str).str.zfill(6)).merge(k_df, on=["c6", "buy_date"], how="inner")
    m_kA = slot_A.assign(c6=slot_A["c6"].astype(str).str.zfill(6)).merge(k_df, on=["c6", "buy_date"], how="inner")
    k_err_all, k_err_A = 0, 0
    for df_m, is_a in [(m_k, False), (m_kA, True)]:
        for r in df_m.itertuples(index=False):
            bb = bar_m.get((r.c6, r.buy_date))
            if bb is None: continue
            diffs = [abs(r.k_open - bb.open)] + [abs(r.k_open - bb.open * (float(qc) / bb.qfq_factor)) for qc in q_levels.get(r.c6, [1.0])]
            if min(diffs) > 0.02:
                if is_a: k_err_A += 1
                else: k_err_all += 1

    integ, exdiv_events, dt_def_events = {}, [], []
    for nm, led in [("A_76", slot_A), ("S_82", slot_S)]:
        d = led.copy(); d["c6"] = d["c6"].astype(str).str.zfill(6)
        t0_v = int((d["exit_date"] <= d["buy_date"]).sum())
        ov_v = sum(1 for i in range(1, len(d)) if d.iloc[i]["buy_date"] <= d.iloc[i-1]["exit_date"])
        yz_b, dt_e_close, yz_dt_e, oob_b, oob_e = 0, 0, 0, 0, 0
        for r in d.itertuples(index=False):
            bb, eb = bar_m[(r.c6, r.buy_date)], bar_m[(r.c6, r.exit_date)]
            b_zt = np.floor(bb.prev_c_adj * 1.20 * 100.0 + 0.5) / 100.0
            e_dt = np.floor(eb.prev_c_adj * 0.80 * 100.0 + 0.5) / 100.0
            if bb.open >= b_zt - 0.011 and bb.low == bb.high: yz_b += 1
            if eb.close <= e_dt + 0.011 and eb.low == eb.high: yz_dt_e += 1
            if r.exit_hhmm >= 1455 and eb.close <= e_dt + 0.011 and (eb.close / eb.prev_c_adj - 1.0) <= -0.195: dt_e_close += 1
            bp_raw, ep_raw = r.buy_px * (bb.close / bb.adj_close), r.exit_px * (eb.close / eb.adj_close)
            if bp_raw < bb.low - 0.02 or bp_raw > bb.high + 0.02: oob_b += 1
            if ep_raw < eb.low - 0.02 or ep_raw > eb.high + 0.02: oob_e += 1
            if nm == "A_76" and abs(bb.qfq_factor - eb.qfq_factor) > 1e-6:
                exdiv_events.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "c6": r.c6, "name": r.name, "qfq_buy": round(bb.qfq_factor, 4), "qfq_exit": round(eb.qfq_factor, 4), "net_ret": round(r.net_ret_eval, 4)})
            if nm == "A_76" and r.hold_bars > 1 and ("d2_close" in str(r.exit_reason) or "B4" in str(r.exit_reason) or "B3" in str(r.exit_reason)):
                dt_def_events.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "c6": r.c6, "name": r.name, "hold_bars": int(r.hold_bars), "exit_reason": r.exit_reason, "net_ret": round(r.net_ret_eval, 4)})
        assert t0_v == 0 and ov_v == 0 and yz_b == 0 and yz_dt_e == 0 and dt_e_close == 0 and oob_b == 0 and oob_e == 0
        integ[nm] = {"n": int(len(d)), "t0": t0_v, "overlap": ov_v, "yizi_zt_buy": yz_b, "yizi_dt_exit": yz_dt_e, "dt_sealed_1500_sell": dt_e_close, "buy_oob": oob_b, "exit_oob": oob_e}
    return {"kline_matched_all": int(len(m_k)), "kline_matched_A": int(len(m_kA)), "kline_err_all": k_err_all, "kline_err_A": k_err_A, "integrity": integ, "exdiv_hold_trades": exdiv_events, "dt_deferral_trades": dt_def_events}


def v191_empty_slot_v11(all_sig: pd.DataFrame, sh300: dict) -> dict:
    v191 = pd.read_csv(V191_PATH); v191["code"] = v191["code"].astype(str).str.zfill(6)
    s_dt, e_dt = "2021-11-15", "2026-11-16"
    hs_v = bench_return(sh300, s_dt, e_dt)

    def _stats(df_l):
        r = df_l["net_ret"].to_numpy(dtype=float); cum = np.cumprod(1.0 + r)
        pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
        w, l = r[r > 0], r[r <= 0]
        return {"n": int(len(r)), "wr": round(float((r > 0).mean() * 100), 2), "po": round(float(w.mean() / abs(l.mean())), 2), "nav": round(float(cum[-1]), 2), "cap10m": calc_cap10m(r), "mdd": round(float(np.max((pk - cum) / pk) * 100.0), 2), "ex_hs300_pp": round((float(cum[-1]) - 1.0 - hs_v) * 100, 1), "by_strat": df_l["strategy"].value_counts().to_dict()}

    out = {"v191_base": _stats(v191)}
    cols_k = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "net_ret"]
    occ_base = [((r.buy_date, int(r.buy_hhmm)), (r.exit_date, int(r.exit_hhmm))) for r in v191.itertuples(index=False)]
    for t_lbl, th in [("add_20cm_V11_A76", 76.0), ("add_20cm_V11_S82", 82.0)]:
        s20 = all_sig[(all_sig["score"] >= th) & (all_sig["buy_date"] >= s_dt) & (all_sig["buy_date"] <= e_dt)].copy()
        s20["code"] = s20["c6"].astype(str).str.zfill(6); s20["buy_hhmm"] = 925
        s20["exit_hhmm"] = np.where(s20["exit_reason"].str.contains("open|gap|tp"), 1030, 1500)
        s20["strategy"] = "20cm首板深水V1.1"; s20["priority"] = 6
        s20_ord = s20[cols_k].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).reset_index(drop=True)
        acc, occ = [], list(occ_base)
        for row in s20_ord.itertuples(index=False):
            st_i, en_i = (row.buy_date, int(row.buy_hhmm)), (row.exit_date, int(row.exit_hhmm))
            if all((en_i < os_) or (st_i > oe_) for os_, oe_ in occ):
                acc.append(row._asdict()); occ.append((st_i, en_i))
        cmb = pd.concat([v191[cols_k], pd.DataFrame(acc, columns=cols_k)], ignore_index=True).sort_values(["buy_date", "buy_hhmm", "exit_date"]).reset_index(drop=True)
        for idx_c in range(1, len(cmb)):
            p_r, c_r = cmb.iloc[idx_c - 1], cmb.iloc[idx_c]
            assert (c_r["buy_date"], int(c_r["buy_hhmm"])) > (p_r["exit_date"], int(p_r["exit_hhmm"]))
        st_c = _stats(cmb); r_add = np.array([x["net_ret"] for x in acc], dtype=float)
        st_c["v191_trades_preserved"] = f"{int((cmb['priority'] <= 5).sum())}/{len(v191)}"
        st_c["added_20cm_n"] = int(len(acc)); st_c["added_20cm_wr"] = round(float((r_add > 0).mean() * 100), 2) if len(r_add) else 0.0
        st_c["added_20cm_mean_pct"] = round(float(r_add.mean() * 100), 2) if len(r_add) else 0.0
        st_c["added_20cm_solo_nav"] = round(float(np.prod(1.0 + r_add)), 3) if len(r_add) else 1.0
        out[t_lbl] = st_c
    return out
