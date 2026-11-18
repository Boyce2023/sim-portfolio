#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
task1_pry_exit_audit.py — 超跌撬板 V1.0 (s_pry) 前视偏差审计与卖点重塑实证
严格遵循 D12 (禁 yfinance)、SQLite mode=ro、D15 四期双轨全口径、零日内未来函数。
"""
import os, json, pickle, sqlite3
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
P5_DIR = f"{SIM}/backtests_astock2/p5_full_pry_universe"
GFM_DIR = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118"
os.makedirs(OUT_DIR, exist_ok=True)

COST = 0.0020
IDX_PATH = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
SH300 = json.load(open(IDX_PATH, encoding="utf-8"))["sh000300"]
CSI_DTS = sorted(SH300.keys())


def csi_ret_pct(s_dt: str, e_dt: str) -> float:
    prevs = [d for d in CSI_DTS if d < s_dt]
    posts = [d for d in CSI_DTS if d <= e_dt]
    p0 = SH300[prevs[-1]] if prevs else SH300[CSI_DTS[0]]
    p1 = SH300[posts[-1]]
    return round((p1 / p0 - 1.0) * 100.0, 2)


WINDOWS = [
    ("full_5y", "2021-11-16", "2026-11-16", csi_ret_pct("2021-11-16", "2026-11-16")),
    ("is_21_23", "2021-11-16", "2023-12-31", csi_ret_pct("2021-11-16", "2023-12-31")),
    ("oos_24_26", "2024-01-01", "2026-11-16", csi_ret_pct("2024-01-01", "2026-11-16")),
    ("y2026_1y", "2026-01-01", "2026-11-16", csi_ret_pct("2026-01-01", "2026-11-16")),
]


def load_5m_coverage(df_sub: pd.DataFrame, cb: dict):
    p_all = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet", columns=["c6", "date"])
    s_all = set(zip(p_all["c6"].astype(str).str.zfill(6), p_all["date"].astype(str)))
    p_34 = pd.read_parquet(f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet", columns=["c6", "date"])
    s_34 = set(zip(p_34["c6"].astype(str).str.zfill(6), p_34["date"].astype(str)))
    with open(f"{SIM}/backtests_astock2/_archive/20261116/old_phase1_phase2_supersede/p4_pry_board/p2_5m_bars_cache.pkl", "rb") as f:
        s_p2 = set((str(k[0]).zfill(6), str(k[1])) for k in pickle.load(f).keys())
    con = sqlite3.connect(f"file:{SIM}/backtests_astock2/data_5y/firstboard_5m_5y_pit.db?mode=ro", uri=True)
    s_fb = set((str(r[0])[:6].zfill(6), str(r[1])) for r in con.execute("SELECT DISTINCT sec_code, trade_date FROM firstboard_5m_kline"))
    con.close()
    s_union = s_all | s_34 | s_p2 | s_fb

    def cov_stats(sub):
        n = len(sub)
        dc = {f"T+{k}": 0 for k in range(6)}
        any_h, all_h = 0, 0
        for r in sub.itertuples(index=False):
            d = cb[r.c6]
            p0 = d["date_to_pos"][r.buy_date]
            flags = []
            for k in range(6):
                if p0 + k < len(d["dts"]):
                    hit = (r.c6, str(d["dts"][p0 + k])) in s_union
                    dc[f"T+{k}"] += int(hit)
                    if 1 <= k <= 4:
                        flags.append(hit)
            any_h += int(any(flags))
            all_h += int(bool(flags) and all(flags))
        return {
            "n_rows": n,
            "day_counts": dc,
            "t1_cov_pct": round(dc["T+1"] / n * 100.0, 2) if n else 0.0,
            "any_t1_t4_cov_pct": round(any_h / n * 100.0, 2) if n else 0.0,
            "all_t1_t4_cov_pct": round(all_h / n * 100.0, 2) if n else 0.0,
        }

    top1 = df_sub.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date").first().reset_index()
    return {
        "union_5m_pairs": len(s_union),
        "full_435_pool": cov_stats(df_sub),
        "top1_25_days": cov_stats(top1),
        "conclusion": "本地全量5m库覆盖极低(435池T+1仅0.46%, 25头名T+1为0%), 严禁静默填补或凭日线猜分时高点先后",
    }


def first_sellable(d, p):
    L = len(d["dts"])
    while p < L - 1 and d["is_yizi_dt"][p]:
        p += 1
    return min(p, L - 1)


def hold_zt_relay(d, pk, buy_px, allow_yang_imm=False):
    L = len(d["dts"])
    o, c, dt_px, is_zt, is_yz_dt, dts = d["open"], d["close"], d["dt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"]
    imm = False
    cur = pk
    while cur < L - 1:
        nxt = cur + 1
        if is_yz_dt[nxt]:
            nxt2 = first_sellable(d, nxt)
            spx = o[nxt2] if o[nxt2] > dt_px[nxt2] + 0.005 else c[nxt2]
            return float(spx / buy_px * (1.0 - COST) - 1.0), str(dts[nxt2])
        if is_zt[nxt]:
            cur = nxt
            continue
        if allow_yang_imm and (not imm) and (c[nxt] > o[nxt]) and (c[nxt] >= c[cur] * 0.97):
            imm = True
            cur = nxt
            continue
        return float(c[nxt] / buy_px * (1.0 - COST) - 1.0), str(dts[nxt])
    return float(c[cur] / buy_px * (1.0 - COST) - 1.0), str(dts[cur])


def sim_pry_rule(d, p0, ret10, rule_type, **kw):
    L = len(d["dts"])
    o, h, l, c, dt_px, zt_px, is_zt, is_yz_dt, dts = (
        d["open"], d["high"], d["low"], d["close"], d["dt_px"], d["zt_px"], d["is_zt"], d["is_yizi_dt"], d["dts"]
    )
    buy_px = float(o[p0])
    use_approx_dt = kw.get("approx_dt", False)
    day0_dt = bool(d["is_dt"][p0]) if use_approx_dt else bool(c[p0] <= dt_px[p0] + 0.001)

    if day0_dt and rule_type != "cut_all_t1_open":
        ps = first_sellable(d, p0 + 1)
        spx = o[ps] if o[ps] > dt_px[ps] + 0.005 else c[ps]
        return float(spx / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if rule_type in ("buggy_x10", "strict_premarket", "strict_0925_zt_exempt", "strict_even_zt0"):
        coef = kw.get("coef", 0.45)
        floor = kw.get("floor", 0.06)
        cap = kw.get("cap", 0.16)
        max_h = kw.get("max_h", 4)
        tp_r = max(floor, coef * abs(ret10))
        if cap is not None:
            tp_r = min(tp_r, cap)
        tp_px = round(buy_px * (1.0 + tp_r), 2)

        if is_zt[p0] and rule_type != "strict_even_zt0":
            return hold_zt_relay(d, p0, buy_px)

        end_p = min(L - 1, p0 + max_h)
        for k in range(p0 + 1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if rule_type == "buggy_x10":
                if o[k] >= tp_px:
                    return hold_zt_relay(d, k, buy_px) if is_zt[k] else (float(o[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k]))
                if h[k] >= tp_px:
                    return hold_zt_relay(d, k, buy_px) if is_zt[k] else (float(tp_px / buy_px * (1.0 - COST) - 1.0), str(dts[k]))
            elif rule_type == "strict_0925_zt_exempt":
                if o[k] >= zt_px[k] - 0.005:
                    return hold_zt_relay(d, k, buy_px) if is_zt[k] else (float(c[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k]))
                if o[k] >= tp_px:
                    return float(o[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k])
                if h[k] >= tp_px:
                    return float(tp_px / buy_px * (1.0 - COST) - 1.0), str(dts[k])
            else:  # strict_premarket or strict_even_zt0
                # If uncapped tp_px exceeds today's limit-up zt_px, order cannot sit below zt_px
                if kw.get("skip_if_above_zt", False) and tp_px >= zt_px[k] - 0.005:
                    if is_zt[k]:
                        return hold_zt_relay(d, k, buy_px)
                    continue
                if o[k] >= tp_px:
                    return float(o[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k])
                if h[k] >= tp_px:
                    return float(tp_px / buy_px * (1.0 - COST) - 1.0), str(dts[k])
        ps = first_sellable(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if rule_type == "no_below_zt_limit":
        # Never place tp below ZT: hold ZT relay if ZT occurs, else exit at max_h close
        max_h = kw.get("max_h", 4)
        if is_zt[p0]:
            return hold_zt_relay(d, p0, buy_px, allow_yang_imm=kw.get("yang_imm", False))
        end_p = min(L - 1, p0 + max_h)
        for k in range(p0 + 1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if is_zt[k]:
                return hold_zt_relay(d, k, buy_px, allow_yang_imm=kw.get("yang_imm", False))
            if kw.get("t1_cut_lt") is not None and k == p0 + 1:
                if o[k] < c[p0] * (1.0 + kw["t1_cut_lt"]):
                    return float(o[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k])
        ps = first_sellable(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if rule_type == "daily_switch":
        # T+1 open < t1_open_cut cut at 09:25; ZT -> relay; non-ZT close at hold_days 15:00 (optional trailing)
        t1_cut = kw.get("t1_cut", -0.02)
        hold_days = kw.get("hold_days", 2)  # 1=T+1, 2=T+2, 3=T+3
        yang_imm = kw.get("yang_imm", False)
        if is_zt[p0]:
            return hold_zt_relay(d, p0, buy_px, allow_yang_imm=yang_imm)
        p1 = first_sellable(d, p0 + 1)
        if p1 > p0 + 1:
            spx = o[p1] if o[p1] > dt_px[p1] + 0.005 else c[p1]
            return float(spx / buy_px * (1.0 - COST) - 1.0), str(dts[p1])
        if t1_cut is not None and o[p1] < c[p0] * (1.0 + t1_cut):
            return float(o[p1] / buy_px * (1.0 - COST) - 1.0), str(dts[p1])
        end_p = min(L - 1, p0 + hold_days)
        for k in range(p1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if is_zt[k]:
                return hold_zt_relay(d, k, buy_px, allow_yang_imm=yang_imm)
            if kw.get("cut_weak_t1_red_only", False) and k == p1 and c[k] < c[p0]:
                return float(c[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k])
        ps = first_sellable(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    if rule_type == "daily_close_trail":
        # Strictly causal EOD close trailing stop (zero intraday lookahead)
        # If T+k closes up >= +6% (or peak close >= +6%), exit next close if close drops <= peak * (1 - 0.025)
        max_h = kw.get("max_h", 4)
        arm = kw.get("arm", 0.06)
        dd = kw.get("dd", 0.025)
        if is_zt[p0]:
            return hold_zt_relay(d, p0, buy_px)
        p1 = first_sellable(d, p0 + 1)
        if p1 == p0 + 1 and kw.get("t1_cut") is not None and o[p1] < c[p0] * (1.0 + kw["t1_cut"]):
            return float(o[p1] / buy_px * (1.0 - COST) - 1.0), str(dts[p1])
        pk_c = c[p0]
        armed = False
        end_p = min(L - 1, p0 + max_h)
        for k in range(p1, end_p + 1):
            if is_yz_dt[k]:
                continue
            if is_zt[k]:
                return hold_zt_relay(d, k, buy_px)
            if armed and c[k] <= pk_c * (1.0 - dd):
                return float(c[k] / buy_px * (1.0 - COST) - 1.0), str(dts[k])
            if c[k] > pk_c:
                pk_c = c[k]
            if pk_c >= buy_px * (1.0 + arm):
                armed = True
        ps = first_sellable(d, end_p)
        return float(c[ps] / buy_px * (1.0 - COST) - 1.0), str(dts[ps])

    raise ValueError(rule_type)


def calc_arr_stats(rr: np.ndarray, csi_pct: float) -> dict:
    n = len(rr)
    if n == 0:
        return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "nav": 1.0, "ret_pct": 0.0,
                "mdd_pct": 0.0, "trim3_nav": 1.0, "trim5_nav": 1.0, "csi300_pct": csi_pct, "excess_pp": round(-csi_pct, 2)}
    w, ls = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean() * 100.0)
    plr = float(w.mean() / abs(ls.mean())) if (len(w) and len(ls) and ls.mean() < 0) else (99.0 if len(w) else 0.0)
    nc = np.cumprod(1.0 + rr)
    pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
    mdd = float(np.max((pk - nc) / pk) * 100.0)
    sr = np.sort(rr)
    t3 = float(np.prod(1.0 + sr[:-3])) if n > 3 else 1.0
    t5 = float(np.prod(1.0 + sr[:-5])) if n > 5 else 1.0
    nav = float(nc[-1])
    return {
        "n": int(n), "wr_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_pct": round(float(rr.mean() * 100.0), 2),
        "nav": round(nav, 4), "ret_pct": round((nav - 1.0) * 100.0, 2),
        "mdd_pct": round(mdd, 2), "trim3_nav": round(t3, 4), "trim5_nav": round(t5, 4),
        "csi300_pct": csi_pct, "excess_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
    }


def eval_variant(df_base: pd.DataFrame, cb: dict, rule_type: str, **kw) -> dict:
    rets, eds = [], []
    for r in df_base.itertuples(index=False):
        rv, ed = sim_pry_rule(cb[r.c6], r.p0, r.prev_ret10, rule_type, **kw)
        rets.append(rv)
        eds.append(ed)
    df = df_base.copy()
    df["net_ret"] = rets
    df["exit_date"] = eds

    # Single slot rotation (sorted buy_date asc, score desc, bias10 asc; bd > free_after)
    srt = df.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
    taken, free_after = [], ""
    for r in srt.itertuples(index=False):
        if free_after == "" or r.buy_date > free_after:
            taken.append({"buy_date": r.buy_date, "exit_date": r.exit_date, "c6": r.c6, "net_ret": r.net_ret})
            free_after = r.exit_date
    df_1s = pd.DataFrame(taken)
    df_top1 = srt.groupby("buy_date").first().reset_index()
    df_eq_all = df.groupby("buy_date")["net_ret"].mean().sort_index()

    res = {}
    for wname, s_dt, e_dt, csi_p in WINDOWS:
        s1 = df_1s[(df_1s["buy_date"] >= s_dt) & (df_1s["buy_date"] <= e_dt)]["net_ret"].to_numpy(dtype=float)
        eq_a = df_eq_all[(df_eq_all.index >= s_dt) & (df_eq_all.index <= e_dt)].to_numpy(dtype=float)
        t1 = df_top1[(df_top1["buy_date"] >= s_dt) & (df_top1["buy_date"] <= e_dt)]["net_ret"].to_numpy(dtype=float)
        raw_cnt = int(((df["buy_date"] >= s_dt) & (df["buy_date"] <= e_dt)).sum())
        res[wname] = {
            "raw_signals": raw_cnt,
            "single_slot": calc_arr_stats(s1, csi_p),
            "daily_eq_all": calc_arr_stats(eq_a, csi_p),
            "daily_top1_eq": calc_arr_stats(t1, csi_p),
        }
    return res


def main():
    df_m = pd.read_parquet(f"{P5_DIR}/full_pry_master_enriched.parquet")
    with open(f"{GFM_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]
    v1 = pd.read_csv(f"{P5_DIR}/v1_oversold_pry_165_strict_ledger.csv")
    v1["c6"] = v1["code"].astype(str).str.zfill(6)
    m = v1.merge(df_m[["c6", "dt_str", "sig_date", "prev_ret10"]], left_on=["c6", "buy_date"], right_on=["c6", "dt_str"], how="left")
    m["p0"] = [cb[r.c6]["date_to_pos"][r.buy_date] for r in m.itertuples(index=False)]
    m["prev_ret10"] = m["prev_ret10"].fillna(-0.15).astype(float)

    cov_info = load_5m_coverage(m, cb)
    print("5m Coverage:", json.dumps(cov_info, ensure_ascii=False))

    # Verify exact reproduction of v1_oversold_pry_165_strict_ledger.csv & buggy s3_champion_ledger.csv
    s3 = pd.read_csv(f"{P5_DIR}/_archive/20261116_stage12_sweeps/s3_champion_ledger.csv")
    s3["c6"] = s3["code"].astype(str).str.zfill(6)
    m_s3 = m.merge(s3[["buy_date", "c6", "net_ret"]], on=["buy_date", "c6"], suffixes=("", "_s3"))

    buggy_rets = [sim_pry_rule(cb[r.c6], r.p0, r.prev_ret10, "buggy_x10", approx_dt=True)[0] for r in m_s3.itertuples(index=False)]
    strict_rets = [sim_pry_rule(cb[r.c6], r.p0, r.prev_ret10, "strict_premarket", approx_dt=False)[0] for r in m.itertuples(index=False)]
    max_diff_s3 = float(np.max(np.abs(np.array(buggy_rets) - m_s3["net_ret_s3"].to_numpy())))
    max_diff_v1 = float(np.max(np.abs(np.array(strict_rets) - m["net_ret"].to_numpy())))
    print(f"Repro check: max_diff vs s3_buggy={max_diff_s3:.8f}, max_diff vs v1_strict={max_diff_v1:.8f}")
    assert max_diff_s3 < 1e-5 and max_diff_v1 < 1e-5

    # Lookahead audit
    audit = {
        "repro_max_diff_s3_buggy": round(max_diff_s3, 8),
        "repro_max_diff_v1_strict": round(max_diff_v1, 8),
        "key_discovery": "precompute_return_matrix.py 第79-85行及旧s3_champion_ledger.csv存在偷看收盘is_zt续拿连板的前视偏差(435池中影响44笔: h>=tp且is_zt 40笔, o>=tp且is_zt 4笔), 加之0.01容差is_dt偏差7笔共51笔; 而现役真源 v1_oversold_pry_165_strict_ledger.csv (435笔) 及 ledger_aux_pry_v10.csv (25头名/16单仓) 实际已按 strict_premarket 盘前死挂精确止盈(仅is_zt0当天收盘已涨停的41/435与4/25续拿连板)修复!",
        "buggy_precompute_approx_dt": eval_variant(m, cb, "buggy_x10", approx_dt=True),
        "buggy_precompute_exact_dt": eval_variant(m, cb, "buggy_x10", approx_dt=False),
        "strict_premarket_v1_truth": eval_variant(m, cb, "strict_premarket", approx_dt=False),
        "strict_0925_zt_open_exempt": eval_variant(m, cb, "strict_0925_zt_exempt", approx_dt=False),
        "strict_even_zt0": eval_variant(m, cb, "strict_even_zt0", approx_dt=False),
    }

    # Task 1a: Pre-market limit sell parameter sweep (zero lookahead)
    variants = []
    for coef in [0.35, 0.45, 0.55, 0.65]:
        for floor in [0.05, 0.06, 0.08]:
            for cap_lbl, cap_val, skip_zt in [("cap12", 0.12, False), ("cap15", 0.15, False), ("uncap_skip_zt", None, True)]:
                for mh in [2, 3, 4, 5]:
                    name = f"1a_limit_c{int(coef*100)}_f{int(floor*100)}_{cap_lbl}_h{mh}"
                    variants.append({
                        "group": "1a_premarket_limit",
                        "name": name,
                        "params": {"coef": coef, "floor": floor, "cap": cap_val, "skip_if_above_zt": skip_zt, "max_h": mh},
                        "metrics": eval_variant(m, cb, "strict_premarket", coef=coef, floor=floor, cap=cap_val, skip_if_above_zt=skip_zt, max_h=mh),
                    })

    # Also test no_below_zt_limit (literally never hang tp < zt_px)
    for mh in [2, 3, 4, 5]:
        variants.append({
            "group": "1a_no_below_zt",
            "name": f"1a_no_below_zt_h{mh}",
            "params": {"max_h": mh},
            "metrics": eval_variant(m, cb, "no_below_zt_limit", max_h=mh),
        })

    # Task 1b: Causal daily close trail & T+1 cut + ZT relay (5m intraday trailing marked unbacktestable due to 0.46% 5m coverage)
    for t1_cut in [-0.02, -0.03, None]:
        for arm in [0.06, 0.08]:
            name = f"1b_eod_trail_t1cut{t1_cut}_arm{int(arm*100)}_dd25_h4"
            variants.append({
                "group": "1b_causal_eod_trail",
                "name": name,
                "params": {"t1_cut": t1_cut, "arm": arm, "dd": 0.025, "max_h": 4},
                "metrics": eval_variant(m, cb, "daily_close_trail", t1_cut=t1_cut, arm=arm, dd=0.025, max_h=4),
            })

    # Task 1c: Pure open/close switching rules
    for t1_cut in [None, -0.02, -0.03]:
        for hd in [1, 2, 3, 4]:
            for yang_imm in [False, True]:
                if t1_cut is not None and hd == 1 and yang_imm:
                    continue
                name = f"1c_switch_t1cut{t1_cut}_h{hd}_imm{int(yang_imm)}"
                variants.append({
                    "group": "1c_open_close_switch",
                    "name": name,
                    "params": {"t1_cut": t1_cut, "hold_days": hd, "yang_imm": yang_imm},
                    "metrics": eval_variant(m, cb, "daily_switch", t1_cut=t1_cut, hold_days=hd, yang_imm=yang_imm),
                })

    out = {"coverage_5m": cov_info, "lookahead_audit": audit, "variants": variants}
    with open(f"{OUT_DIR}/task1_pry_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Concise summary print
    def show(lbl, m_dict):
        f5, is_, oo, y26 = m_dict["full_5y"], m_dict["is_21_23"], m_dict["oos_24_26"], m_dict["y2026_1y"]
        print(f"  {lbl:38s} | 1S 5Y={f5['single_slot']['nav']:.3f}x(WR={f5['single_slot']['wr_pct']}%,PLR={f5['single_slot']['plr']},MDD={f5['single_slot']['mdd_pct']}%,T3={f5['single_slot']['trim3_nav']:.2f}x,Ex={f5['single_slot']['excess_pp']:+.1f}pp) "
              f"| IS={is_['single_slot']['nav']:.3f}x | OOS={oo['single_slot']['nav']:.3f}x | EQ_all 5Y={f5['daily_eq_all']['nav']:.3f}x(IS={is_['daily_eq_all']['nav']:.2f}x,OOS={oo['daily_eq_all']['nav']:.2f}x) | Top1_EQ={f5['daily_top1_eq']['nav']:.3f}x")

    print("\n--- Task 1 Lookahead Audit ---")
    show("buggy_precompute_approx_dt(s3_old)", audit["buggy_precompute_approx_dt"])
    show("buggy_precompute_exact_dt", audit["buggy_precompute_exact_dt"])
    show("strict_premarket(v1_truth)", audit["strict_premarket_v1_truth"])
    show("strict_0925_zt_open_exempt", audit["strict_0925_zt_open_exempt"])

    print("\n--- Top 12 Variants by 1S Full_5Y & OOS Balance ---")
    variants_srt = sorted(variants, key=lambda v: (v["metrics"]["full_5y"]["single_slot"]["nav"] * v["metrics"]["full_5y"]["daily_eq_all"]["nav"]), reverse=True)
    for v in variants_srt[:15]:
        show(v["name"], v["metrics"])
    print("\n--- Best 1c Open/Close Switch Variants ---")
    v1c = [v for v in variants if v["group"] == "1c_open_close_switch"]
    for v in sorted(v1c, key=lambda x: x["metrics"]["full_5y"]["single_slot"]["nav"], reverse=True)[:6]:
        show(v["name"], v["metrics"])


if __name__ == "__main__":
    main()
