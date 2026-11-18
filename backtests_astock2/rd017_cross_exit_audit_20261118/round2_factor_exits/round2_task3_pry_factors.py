#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
round2_task3_pry_factors.py — 第二轮任务三: 超跌撬板 V1.0 (s_pry) 持仓动态因子实证
同时在 435严池 / 25头名(16单仓) / 830宽池(92天) 上:
  1) IS (2022~2023) 逐项检验 T+0/持仓龙虎榜、盘后突发利空公告、09:25市场情绪背离、反弹首板一进二V19裁判;
  2) 锁定极简动态卖点规则在 OOS (2024~2026) 与 2026 做全盲验证并汇报完整 D15 双轨指标。
"""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD2_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118/round2_factor_exits"
P5_DIR = f"{SIM}/backtests_astock2/p5_full_pry_universe"
GFM_DIR = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
sys.path.insert(0, RD2_DIR)
import pit_factor_helpers as pfh

COST = 0.0020
WINDOWS = [
    ("full_5y", "2021-11-16", "2026-11-16", pfh.csi_ret_pct("2021-11-16", "2026-11-16")),
    ("is_22_23", "2022-01-04", "2023-12-31", pfh.csi_ret_pct("2022-01-04", "2023-12-31")),
    ("oos_24_26", "2024-01-01", "2026-11-16", pfh.csi_ret_pct("2024-01-01", "2026-11-16")),
    ("y2026_1y", "2026-01-01", "2026-11-16", pfh.csi_ret_pct("2026-01-01", "2026-11-16")),
]


def first_sellable(d, p):
    L = len(d["dts"])
    while p < L - 1 and d["is_yizi_dt"][p]:
        p += 1
    return min(p, L - 1)


def is_zt_strong_1to2(c6: str, d: dict, pk: int, k_next: int, env: dict) -> tuple[bool, dict]:
    """用一进二 V19 严苛标准评判反弹首板 (pk) 在次日 09:25 (k_next) 是否值得锁仓博二板"""
    dt_pk = str(d["dts"][pk])
    dt_nx = str(d["dts"][k_next])
    o, h, l, c, pc = float(d["open"][pk]), float(d["high"][pk]), float(d["low"][pk]), float(d["close"][pk]), float(d["pre_c"][pk])
    dip = (l - pc) / (pc + 1e-6)
    ent = (c - o) / (pc + 1e-6)
    to_info = env["day_to_map"].get((dt_pk, c6))
    amt_pk = env["day_amt"].get((dt_pk, c6), 0.0)
    amt_ma5 = to_info[6] if to_info else 0.0
    vr = (amt_pk / amt_ma5) if amt_ma5 > 0 else 1.5
    tight = (30.0 if c >= h - 0.001 else 0.0) + np.clip(dip * 100.0, -10.0, 10.0) * 1.5 + np.clip(ent * 100.0, 0.0, 10.0) * 2.0 - (15.0 if vr > 4.0 else 0.0)

    tp = env["tape_map"].get((dt_pk, c6))
    fst, obc, _ = tp if tp else ("09:30:00", 0, np.nan)
    fake_theme = pfh.is_fake_theme_1to2(env, c6, dt_pk)

    nx_op = (float(d["open"][k_next]) / c - 1.0) if c > 0 else 0.0
    is_yizi_nx = bool(d["open"][k_next] >= d["zt_px"][k_next] - 0.005)

    meta = {"tight": tight, "fst": fst, "obc": obc, "fake_theme": fake_theme, "nx_op": nx_op, "vr": vr}
    # Strong promotion: not rotten (tight>=37 & fst<"14:00:00" & obc<=1), real theme, and next open >= +2.2% (or yizi!)
    strong = is_yizi_nx or ((tight >= 37.0) and (fst < "14:00:00") and (obc <= 1) and (not fake_theme) and (nx_op >= 0.022))
    return strong, meta


def sim_pry_dynamic(
    c6: str, d: dict, p0: int, env: dict,
    base_hold: int = 3,
    t1_cut: float | None = -0.02,
    yang_imm: bool = True,
    use_lhb_bad_cut: bool = False,
    use_lhb_good_extend: bool = False,
    use_night_notice_cut: bool = False,
    use_mkt_freeze_cut: bool = False,
    use_diverge_rule: bool = False,
    zt_referee: str = "hold_all",  # hold_all | cut_all_nx_open | cut_nx_lt20 | cut_1to2_weak
) -> tuple[float, str]:
    L = len(d["dts"])
    o, c, dt_px, zt_px, is_zt, is_yz_dt, dts = d["open"], d["close"], d["dt_px"], d["zt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"]
    buy_px = float(o[p0])

    # Day 0 exact limit-down reseal -> T+1 open cut
    if bool(c[p0] <= dt_px[p0] + 0.001):
        ps = first_sellable(d, p0 + 1)
        spx = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return float(spx / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    def hold_zt_relay(pk: int):
        # First check zt_referee at k_next = pk + 1
        kn = first_sellable(d, pk + 1)
        if kn > pk + 1:
            spx = o[kn] if o[kn] > dt_px[kn] + 0.005 else c[kn]
            return float(spx / buy_px * (1.0 - COST) - 1.0), str(dts[kn])

        if zt_referee != "hold_all" and pk < L - 1:
            strong, meta = is_zt_strong_1to2(c6, d, pk, kn, env)
            is_yz_nx = bool(o[kn] >= zt_px[kn] - 0.005)
            if zt_referee == "cut_all_nx_open" and (not is_yz_nx):
                return float(o[kn] / buy_px * (1.0 - COST) - 1.0), str(dts[kn])
            if zt_referee == "cut_nx_lt20" and (not is_yz_nx) and (meta["nx_op"] < 0.020):
                return float(o[kn] / buy_px * (1.0 - COST) - 1.0), str(dts[kn])
            if zt_referee == "cut_1to2_weak" and (not strong):
                return float(o[kn] / buy_px * (1.0 - COST) - 1.0), str(dts[kn])

        imm = False
        cur = pk
        while cur < L - 1:
            nxt = cur + 1
            if is_yz_dt[nxt]:
                nx2 = first_sellable(d, nxt)
                spx = o[nx2] if o[nx2] > dt_px[nx2] + 0.005 else c[nx2]
                return float(spx / buy_px * (1.0 - COST) - 1.0), str(dts[nx2])
            if is_zt[nxt]:
                cur = nxt; continue
            if yang_imm and (not imm) and (c[nxt] > o[nxt]) and (c[nxt] >= c[cur] * 0.97):
                imm = True; cur = nxt; continue
            return float(c[nxt] / buy_px * (1.0 - COST) - 1.0), str(dts[nxt])
        return float(c[cur] / buy_px * (1.0 - COST) - 1.0), str(dts[cur])

    if is_zt[p0]:
        return hold_zt_relay(p0)

    # Check if T+0 LHB had inst/top_yz net buy -> optional extend
    dt0 = str(dts[p0])
    lb0 = env["lhb_buy_info"].get((dt0, c6), {})
    ls0 = env["lhb_sell_info"].get((dt0, c6), {})
    max_h = base_hold
    if use_lhb_good_extend:
        if (lb0.get("inst_buy", 0.0) > ls0.get("inst_sell", 0.0)) or len(lb0.get("top_yz", [])) > 0:
            max_h = max(base_hold, 4)

    end_p = min(L - 1, p0 + max_h)
    k = p0 + 1
    while k <= end_p:
        if is_yz_dt[k]:
            k += 1; continue
        dk = str(dts[k]); prev_dk = str(dts[k - 1])
        ok = float(o[k])

        # Nightly LHB bad
        lb_p = env["lhb_buy_info"].get((prev_dk, c6), {})
        if use_lhb_bad_cut:
            if lb_p.get("lh_cnt", 0) >= 3 or (lb_p.get("tot_buy", 0) > 0 and lb_p.get("lh_ratio", 0) >= 0.25) or lb_p.get("surf_yz", False):
                return float(ok / buy_px * (1.0 - COST) - 1.0), dk

        # Nightly notice bad (tox or reg)
        if use_night_notice_cut:
            bad_nt = pfh.has_ts_in_window(env["tox_ts_map"], c6, f"{prev_dk} 15:00:00", f"{dk} 09:25:00") or pfh.has_ts_in_window(env["reg_ts_map"], c6, f"{prev_dk} 15:00:00", f"{dk} 09:25:00")
            if bad_nt:
                return float(ok / buy_px * (1.0 - COST) - 1.0), dk

        # Market sentiment & divergence at k 09:25
        ms = env["mkt_stats"].get(dk, {})
        zt_open_cnt = int(ms.get("mkt_0925_zt_cnt", 10))
        mkt_p1b = float(ms.get("mkt_prev_1b_open_avg", 0.0))
        op_k = (ok / float(c[k - 1]) - 1.0) if c[k - 1] > 0 else 0.0

        if use_mkt_freeze_cut and zt_open_cnt < 5 and mkt_p1b < -0.010:
            return float(ok / buy_px * (1.0 - COST) - 1.0), dk

        if k == p0 + 1:
            if use_diverge_rule:
                if mkt_p1b >= 0.0 and op_k < -0.015:
                    return float(ok / buy_px * (1.0 - COST) - 1.0), dk
                if mkt_p1b < -0.010 and op_k >= 0.010:
                    end_p = min(L - 1, p0 + 4)  # strong divergence extends hold
            if t1_cut is not None and op_k < t1_cut:
                return float(ok / buy_px * (1.0 - COST) - 1.0), dk

        if is_zt[k]:
            return hold_zt_relay(k)
        k += 1

    ps = first_sellable(d, end_p)
    return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])


def eval_pry_pool(df_base: pd.DataFrame, cb: dict, env: dict, **kw) -> dict:
    rets, eds = [], []
    for r in df_base.itertuples(index=False):
        rv, ed = sim_pry_dynamic(r.c6, cb[r.c6], r.p0, env, **kw)
        rets.append(rv); eds.append(ed)
    df = df_base.copy()
    df["net_ret"] = rets; df["exit_date"] = eds

    srt = df.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
    taken, free_after = [], ""
    for r in srt.itertuples(index=False):
        if free_after == "" or r.buy_date > free_after:
            taken.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "net_ret": r.net_ret})
            free_after = r.exit_date
    df_1s = pd.DataFrame(taken)
    df_top1 = srt.groupby("buy_date").first().reset_index()
    df_eq_all = df.groupby("buy_date")["net_ret"].mean().sort_index()

    res = {}
    for wn, sdt, edt, csip in WINDOWS:
        s1 = df_1s[(df_1s["buy_date"] >= sdt) & (df_1s["buy_date"] <= edt)]["net_ret"].to_numpy(dtype=float) if not df_1s.empty else np.array([], dtype=float)
        eq_a = df_eq_all[(df_eq_all.index >= sdt) & (df_eq_all.index <= edt)].to_numpy(dtype=float)
        t1 = df_top1[(df_top1["buy_date"] >= sdt) & (df_top1["buy_date"] <= edt)]["net_ret"].to_numpy(dtype=float)
        res[wn] = {
            "single_slot": pfh.calc_arr_metrics(s1, csip),
            "daily_eq_all": pfh.calc_arr_metrics(eq_a, csip),
            "daily_top1_eq": pfh.calc_arr_metrics(t1, csip),
        }
    return res


def main():
    t0 = time.time()
    with open(f"{RD2_DIR}/pit_exit_env.pkl", "rb") as f:
        env = pickle.load(f)
    with open(f"{GFM_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    df_m = pd.read_parquet(f"{P5_DIR}/full_pry_master_enriched.parquet")
    v1 = pd.read_csv(f"{P5_DIR}/v1_oversold_pry_165_strict_ledger.csv")
    v1["c6"] = v1["code"].astype(str).str.zfill(6)
    m435 = v1.merge(df_m[["c6", "dt_str", "prev_ret10"]], left_on=["c6", "buy_date"], right_on=["c6", "dt_str"], how="left")
    m435["p0"] = [cb[r.c6]["date_to_pos"][r.buy_date] for r in m435.itertuples(index=False)]

    # 830 broad pool
    non_st = (~df_m["is_st_or_delist"].values) & (df_m["pre_c"].values >= 2.0)
    no_poison = (~df_m["n_poison90"].fillna(False).values) & (~df_m["n_del90"].fillna(False).values) & (~df_m["n_inv90"].fillna(False).values)
    ptdt = df_m["prev_touch_dt"].fillna(False).values.astype(bool)
    pisdt = df_m["prev_is_dt"].fillna(True).values.astype(bool)
    pure_oversold = (df_m["prev_zt20"].fillna(0).values == 0) & (df_m["prev_c_ma20"].fillna(0).values <= -0.15) & (df_m["prev_dd20"].fillna(1.0).values <= 0.80)
    w2s_open_conf = (df_m["o_pct"].values >= 0.0) & (df_m["o_pct"].values <= 0.05)
    m830 = df_m[non_st & no_poison & ptdt & (~pisdt) & pure_oversold & w2s_open_conf].copy()
    m830["buy_date"] = m830["dt_str"].astype(str)
    m830["score"] = 100
    m830["bias10"] = m830["prev_c_ma20"].fillna(0)
    p0s, keep = [], []
    for r in m830.itertuples(index=False):
        d = cb.get(r.c6)
        p = d["date_to_pos"].get(r.buy_date) if d else None
        if p is not None and p + 1 < len(d["dts"]):
            p0s.append(p); keep.append(True)
        else:
            keep.append(False)
    m830 = m830[keep].copy(); m830["p0"] = p0s

    # 1. Univariate IS factor audit on BOTH m435 IS (15 rows) and m830 IS (to ensure statistical power!)
    def build_is_uni(df_sub):
        sub_is = df_sub[df_sub["buy_date"] <= "2023-12-31"].copy()
        rows = []
        for r in sub_is.itertuples(index=False):
            d = cb[r.c6]; p0 = r.p0; dt0 = str(d["dts"][p0])
            rb, _ = sim_pry_dynamic(r.c6, d, p0, env, base_hold=3, t1_cut=-0.02, yang_imm=True)
            # Check factors at T+1 09:25 (for non-dt0, non-zt0)
            p1 = first_sellable(d, p0 + 1)
            dt1 = str(d["dts"][p1])
            op_1 = (float(d["open"][p1]) / float(d["close"][p0]) - 1.0) if d["close"][p0] > 0 else 0.0
            r_t1_open = (float(d["open"][p1]) / float(d["open"][p0]) * (1.0 - COST) - 1.0)
            lb0 = env["lhb_buy_info"].get((dt0, r.c6), {})
            ls0 = env["lhb_sell_info"].get((dt0, r.c6), {})
            bad_nt = pfh.has_ts_in_window(env["tox_ts_map"], r.c6, f"{dt0} 15:00:00", f"{dt1} 09:25:00") or pfh.has_ts_in_window(env["reg_ts_map"], r.c6, f"{dt0} 15:00:00", f"{dt1} 09:25:00")
            ms1 = env["mkt_stats"].get(dt1, {})
            zt_c1 = int(ms1.get("mkt_0925_zt_cnt", 10))
            p1b1 = float(ms1.get("mkt_prev_1b_open_avg", 0.0))

            # First ZT board check (if ZT occurs in T+0..T+3)
            zt_pk = None
            for k in range(p0, min(len(d["dts"]), p0 + 4)):
                if d["is_zt"][k]:
                    zt_pk = k; break
            zt_weak_1to2 = zt_nx_lt2 = False
            r_zt_nx_open = rb
            if zt_pk is not None and zt_pk + 1 < len(d["dts"]):
                kn = first_sellable(d, zt_pk + 1)
                r_zt_nx_open = float(d["open"][kn] / float(d["open"][p0]) * (1.0 - COST) - 1.0)
                strong, meta = is_zt_strong_1to2(r.c6, d, zt_pk, kn, env)
                zt_weak_1to2 = (not strong)
                zt_nx_lt2 = (meta["nx_op"] < 0.020)

            rows.append({
                "base_ret": rb, "t1_open_ret": r_t1_open, "zt_nx_open_ret": r_zt_nx_open,
                "f_lhb_bad_t0": bool(lb0.get("lh_cnt", 0) >= 3 or (lb0.get("tot_buy", 0) > 0 and lb0.get("lh_ratio", 0) >= 0.25) or lb0.get("surf_yz", False)),
                "f_lhb_good_t0": bool((lb0.get("inst_buy", 0.0) > ls0.get("inst_sell", 0.0)) or len(lb0.get("top_yz", [])) > 0),
                "f_night_bad_t1": bad_nt,
                "f_mkt_freeze_t1": bool(zt_c1 < 5 and p1b1 < -0.010),
                "f_weak_diverge_t1": bool(p1b1 >= 0.0 and op_1 < -0.015),
                "f_zt_weak_1to2": zt_weak_1to2,
                "f_zt_nx_lt2": zt_nx_lt2,
                "f_has_zt": zt_pk is not None,
            })
        return pd.DataFrame(rows)

    u435 = build_is_uni(m435)
    u830 = build_is_uni(m830)
    uni_res = []
    for fc, alt_col in [
        ("f_lhb_bad_t0", "t1_open_ret"),
        ("f_night_bad_t1", "t1_open_ret"),
        ("f_mkt_freeze_t1", "t1_open_ret"),
        ("f_weak_diverge_t1", "t1_open_ret"),
        ("f_has_zt", "zt_nx_open_ret"),
        ("f_zt_weak_1to2", "zt_nx_open_ret"),
        ("f_zt_nx_lt2", "zt_nx_open_ret"),
    ]:
        uni_res.append({
            "factor": fc,
            "is_435_pool": pfh.univariate_summary(u435, fc, "base_ret", alt_col),
            "is_830_pool": pfh.univariate_summary(u830, fc, "base_ret", alt_col),
        })

    print("=== Task 3 Univariate IS ===")
    for x in uni_res:
        a, b = x["is_435_pool"], x["is_830_pool"]
        print(f"  {x['factor']:20s} | 435_IS(N={len(u435)}): n={a['n_trig']:2d} {a['base_mean_pct']:+5.2f}%->{a['alt_mean_pct']:+5.2f}% ({a['delta_bps']:+6.0f}bps) | 830_IS(N={len(u830)}): n={b['n_trig']:3d} {b['base_mean_pct']:+5.2f}%->{b['alt_mean_pct']:+5.2f}% ({b['delta_bps']:+6.0f}bps)")

    # 2. Composite comparison across 435 strict & 830 broad pools
    configs = [
        ("r1_h3_t1m2_imm1", dict(base_hold=3, t1_cut=-0.02, yang_imm=True)),
        ("r1_h2_t1m2_imm0", dict(base_hold=2, t1_cut=-0.02, yang_imm=False)),
        ("r2_h3_lhb_bad_cut", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, use_lhb_bad_cut=True)),
        ("r2_h3_lhb_good_ext", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, use_lhb_good_extend=True)),
        ("r2_h3_night_notice_cut", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, use_night_notice_cut=True)),
        ("r2_h3_mkt_freeze_cut", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, use_mkt_freeze_cut=True)),
        ("r2_h3_diverge_rule", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, use_diverge_rule=True)),
        ("r2_h3_zt_cut_all_nxopen", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, zt_referee="cut_all_nx_open")),
        ("r2_h3_zt_cut_nx_lt20", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, zt_referee="cut_nx_lt20")),
        ("r2_h3_zt_cut_1to2_weak", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, zt_referee="cut_1to2_weak")),
        ("r2_h2_zt_cut_1to2_weak", dict(base_hold=2, t1_cut=-0.02, yang_imm=False, zt_referee="cut_1to2_weak")),
        ("r2_h3_full_dynamic_combo", dict(base_hold=3, t1_cut=-0.02, yang_imm=True, use_lhb_bad_cut=True, use_lhb_good_extend=True, use_night_notice_cut=True, use_diverge_rule=True, zt_referee="cut_1to2_weak")),
        ("r2_h2_full_dynamic_combo", dict(base_hold=2, t1_cut=-0.02, yang_imm=False, use_lhb_bad_cut=True, use_night_notice_cut=True, use_diverge_rule=True, zt_referee="cut_1to2_weak")),
    ]

    comp_res = []
    for name, kw in configs:
        comp_res.append({
            "name": name,
            "pool_435_and_16_1s": eval_pry_pool(m435, cb, env, **kw),
            "pool_830_broad": eval_pry_pool(m830, cb, env, **kw),
        })

    out = {"univariate_is_tests": uni_res, "is_oos_full_comparison": comp_res}
    with open(f"{RD2_DIR}/round2_task3_pry.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n=== Task 3 Composite Comparison (done in {time.time()-t0:.1f}s) ===")
    for e in comp_res:
        p4, p8 = e["pool_435_and_16_1s"], e["pool_830_broad"]
        f5, is_, oo, y26 = p4["full_5y"]["single_slot"], p4["is_22_23"]["single_slot"], p4["oos_24_26"]["single_slot"], p4["y2026_1y"]["single_slot"]
        eq4 = p4["full_5y"]["daily_eq_all"]; tp1 = p4["full_5y"]["daily_top1_eq"]
        eq8 = p8["full_5y"]["daily_eq_all"]
        print(f"  {e['name']:26s} | 435_1S: 5Y={f5['nav']:5.3f}(WR={f5['wr_pct']:4.1f}%,IS={is_['nav']:5.3f},OOS={oo['nav']:5.3f},26={y26['nav']:5.3f}) EQ435={eq4['nav']:5.3f} Top1={tp1['nav']:5.3f} | 830_EQ={eq8['nav']:5.3f}(IS={p8['is_22_23']['daily_eq_all']['nav']:4.2f},OOS={p8['oos_24_26']['daily_eq_all']['nav']:4.2f})")


if __name__ == "__main__":
    main()
