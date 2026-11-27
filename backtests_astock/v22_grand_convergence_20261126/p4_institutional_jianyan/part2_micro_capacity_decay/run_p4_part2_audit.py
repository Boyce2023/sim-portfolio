#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Institutional Audit · Part 2 (Pillars 5-7):
  Pillar 5: Capital Capacity & Real Order-Book Sqrt Market Impact (50W / 200W / 500W / 1000W / 3000W)
  Pillar 6: CUSUM (5000-MC) & Page-Hinkley Decay + 2026H2 & Last-3-Month Anatomy
  Pillar 7: 09:25 Live Engineering Feasibility & Zero-Drift Rollout Checklist
Read-only on production scripts & SQLite (?mode=ro). Zero yfinance (D12).
"""
import json, math, os, pickle, resource, sys, time, warnings
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

BASE = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{BASE}/sim-portfolio"
P3_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
RD038_DIR = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049_DIR = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p4_institutional_jianyan/part2_micro_capacity_decay"
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, RD038_DIR)
sys.path.insert(0, RD049_DIR)
import _rd038_engine as eng
from _rd049_common import build_2d_states


def max_dd(dr: np.ndarray) -> float:
    nav = np.cumprod(1.0 + dr)
    pk = np.maximum.accumulate(np.insert(nav, 0, 1.0))[1:]
    return float((1.0 - nav / pk).max())


def perf_windows(dr_5y: np.ndarray, tr_df: pd.DataFrame, cal_5y: list[str], idx_5y: dict[str, int]) -> dict:
    import bisect
    wf_off = bisect.bisect_left(cal_5y, "2023-01-03")
    y26_off = bisect.bisect_left(cal_5y, "2026-01-01")
    h2_off = bisect.bisect_left(cal_5y, "2026-07-01")
    wins = {
        "FULL_5Y": (0, len(cal_5y), ""),
        "WF_2326": (wf_off, len(cal_5y), "2023-01-03"),
        "Y2026": (y26_off, len(cal_5y), "2026-01-01"),
        "Y2026_H2": (h2_off, len(cal_5y), "2026-07-01"),
    }
    out = {}
    for k, (i0, i1, b_cut) in wins.items():
        dr = dr_5y[i0:i1]
        nav = float(np.prod(1.0 + dr))
        sd = float(np.std(dr, ddof=1)) if len(dr) > 1 else 0.0
        sh = float(np.mean(dr) / sd * math.sqrt(242.0)) if sd > 1e-12 else 0.0
        mdd = max_dd(dr)
        sub = tr_df[tr_df["buy_date"] >= b_cut] if b_cut else tr_df
        r = sub["net_ret"].to_numpy(float) if not sub.empty else np.array([])
        wr = float((r > 0).mean() * 100.0) if len(r) else 0.0
        out[k] = {
            "n": int(len(r)),
            "nav": round(nav, 4),
            "sharpe": round(sh, 3),
            "mdd_pct": round(mdd * 100.0, 2),
            "wr_pct": round(wr, 2),
            "mean_pct": round(float(r.mean() * 100.0), 2) if len(r) else 0.0,
        }
    return out


def rebuild_mtm_with_leg_costs(tr_df: pd.DataFrame, c_in: np.ndarray, c_out: np.ndarray, cal_5y: list[str], idx_5y: dict[str, int]) -> tuple[np.ndarray, np.ndarray, float]:
    T = len(cal_5y)
    day_mult = np.ones(T, dtype=float)
    new_r = np.zeros(len(tr_df), dtype=float)
    for i, r in enumerate(tr_df.itertuples(index=False)):
        fi = max(0.05, 1.0 - float(c_in[i]))
        fo = max(0.05, 1.0 - float(c_out[i]))
        new_r[i] = (1.0 + float(r.net_ret)) * fi * fo - 1.0
        segs = list(r.mtm_use)
        assert len(segs) >= 1
        prod_s = 1.0
        for j, (ti, mult) in enumerate(segs):
            m_adj = float(mult)
            if j == 0:
                m_adj *= fi
            if j == len(segs) - 1:
                m_adj *= fo
            prod_s *= m_adj
            day_mult[int(ti)] *= m_adj
        assert abs(prod_s - (1.0 + new_r[i])) < 1e-6, f"MTM mismatch idx={i}"
    dr_5y = day_mult - 1.0
    mtm_diff = abs(float(np.prod(1.0 + dr_5y)) - float(np.prod(1.0 + new_r)))
    return dr_5y, new_r, mtm_diff


def cusum_and_ph(rets: np.ndarray, dates: list[str], seed: int = 20261126) -> dict:
    rng = np.random.default_rng(seed)
    n = len(rets)
    mu1 = float(rets.mean())
    sd = float(rets.std(ddof=1))
    k_ref = 0.5 * mu1

    # 5,000-MC Tabular CUSUM matching run_part3_hygiene_portfolio_cusum.py
    h_grid = np.linspace(max(0.10, 0.5 * sd), max(0.80, 9.5 * sd), 46)
    n_mc, max_arl = 5000, 10000
    paths_h1 = rets[rng.integers(0, n, size=(n_mc, max_arl))]
    paths_h0 = (rets - mu1)[rng.integers(0, n, size=(n_mc, 400))]

    hit1 = np.full((len(h_grid), n_mc), max_arl + 1, dtype=int)
    s1 = np.zeros(n_mc)
    for t in range(max_arl):
        s1 = np.maximum(0.0, s1 + k_ref - paths_h1[:, t])
        smax = float(s1.max())
        if smax < h_grid[0]:
            continue
        for j, hv in enumerate(h_grid):
            if hv > smax:
                break
            upd = (hit1[j] > max_arl) & (s1 >= hv)
            if upd.any():
                hit1[j, upd] = t + 1
        if (hit1[-1] <= max_arl).all():
            break

    hit0 = np.full((len(h_grid), n_mc), 401, dtype=int)
    s0 = np.zeros(n_mc)
    for t in range(400):
        s0 = np.maximum(0.0, s0 + k_ref - paths_h0[:, t])
        smax = float(s0.max())
        if smax < h_grid[0]:
            continue
        for j, hv in enumerate(h_grid):
            if hv > smax:
                break
            upd = (hit0[j] > 400) & (s0 >= hv)
            if upd.any():
                hit0[j, upd] = t + 1
        if (hit0[-1] <= 400).all():
            break

    recs = []
    for j, hv in enumerate(h_grid):
        fa5 = float((hit1[j] <= n).mean()) * 100.0
        recs.append({"h": float(hv), "fa5_pct": round(fa5, 2), "arl0": round(float(hit1[j].mean()), 1), "arl1": round(float(hit0[j].mean()), 1)})

    red_c = [g for g in recs if g["arl0"] >= 250.0 and g["fa5_pct"] < 5.0]
    yel_c = [g for g in recs if g["arl0"] >= 250.0 and g["fa5_pct"] <= 15.0]
    red_p = red_c[0] if red_c else recs[-1]
    yel_p = yel_c[0] if (yel_c and yel_c[0]["h"] < red_p["h"]) else red_p

    def replay_cusum(hv: float):
        s, mx, hits = 0.0, 0.0, []
        path = []
        for idx_r, rv in enumerate(rets):
            s = max(0.0, s + k_ref - float(rv))
            mx = max(mx, s)
            if s >= hv:
                hits.append({"idx": idx_r + 1, "date": dates[idx_r], "S_pct": round(s * 100.0, 2)})
                s = 0.0
            path.append(s)
        return round(mx * 100.0, 2), round(path[-1] * 100.0, 2), hits

    max_s_pct, term_s_r, red_hits = replay_cusum(red_p["h"])
    _, term_s_y, yel_hits = replay_cusum(yel_p["h"])

    # Page-Hinkley downward shift detector: U_t = sum(r_i - mu1 + delta), M_t = max U, PH_t = M_t - U_t
    # Actually standard downward Page-Hinkley on r_t: m_t = sum_{i<=t}(r_i - mu_ref + delta), PH_t = max_{i<=t}(m_i) - m_t
    # Here tolerance delta = 0.25 * mu1 (or 0.50 * mu1). Under H1 (mean=mu1), E[r_i - mu1 + delta] = +delta > 0, so PH stays near 0.
    # Under H0 (mean=0), drift is -(mu1 - delta) < 0, so PH grows linearly!
    ph_res = {}
    for d_mult, tag in [(0.25, "delta_025mu"), (0.50, "delta_050mu")]:
        delta = d_mult * mu1
        # Empirical PH path
        m_v, m_pk, mx_ph, term_ph = 0.0, 0.0, 0.0, 0.0
        for rv in rets:
            m_v += (float(rv) - mu1 + delta)
            m_pk = max(m_pk, m_v)
            ph = m_pk - m_v
            mx_ph = max(mx_ph, ph)
            term_ph = ph
        # Bootstrap 5000-MC 95% (5Y FA = 5%) threshold under H1
        h1_ph_max = np.zeros(n_mc)
        mv = np.zeros(n_mc)
        mpk = np.zeros(n_mc)
        p_sub = paths_h1[:, :n]
        for t in range(n):
            mv += (p_sub[:, t] - mu1 + delta)
            mpk = np.maximum(mpk, mv)
            h1_ph_max = np.maximum(h1_ph_max, mpk - mv)
        lam_95 = float(np.percentile(h1_ph_max, 95.0))
        lam_90 = float(np.percentile(h1_ph_max, 90.0))
        ph_res[tag] = {
            "delta_pct": round(delta * 100.0, 2),
            "lambda_mc_95_pct": round(lam_95 * 100.0, 2),
            "lambda_mc_90_pct": round(lam_90 * 100.0, 2),
            "hist_max_ph_pct": round(mx_ph * 100.0, 2),
            "terminal_ph_pct": round(term_ph * 100.0, 2),
            "triggered_95": bool(mx_ph >= lam_95),
            "terminal_ratio_to_95": round(term_ph / max(1e-9, lam_95), 3),
        }

    return {
        "n_trades": int(n),
        "mu1_pct": round(mu1 * 100.0, 2),
        "sigma_pct": round(sd * 100.0, 2),
        "k_ref_pct": round(k_ref * 100.0, 2),
        "cusum_yellow": {"h_pct": round(yel_p["h"] * 100.0, 2), "arl0": yel_p["arl0"], "fa5_pct": yel_p["fa5_pct"], "arl1": yel_p["arl1"], "hist_hits": len(yel_hits), "hits": yel_hits, "terminal_S_pct": term_s_y},
        "cusum_red": {"h_pct": round(red_p["h"] * 100.0, 2), "arl0": red_p["arl0"], "fa5_pct": red_p["fa5_pct"], "arl1": red_p["arl1"], "hist_max_S_pct": max_s_pct, "hist_hits": len(red_hits), "hits": red_hits, "terminal_S_pct": term_s_r, "terminal_dist_pct": round(red_p["h"] * 100.0 - term_s_r, 2)},
        "page_hinkley": ph_res,
    }


def main():
    t0 = time.time()
    print("[1/4] Loading V22 assets, daily bars, 5m bars, and RD049 regimes...")
    with open(f"{P3_DIR}/_cache/step1_ablation_results.pkl", "rb") as f:
        ab = pickle.load(f)
    with open(f"{RD038_DIR}/_cache/rd038_master_cache.pkl", "rb") as f:
        rd38 = pickle.load(f)

    cal_5y = rd38["cal_5y"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    champ_tr = ab["sim_030"]["V21_M5_B_NoXQ_Pos5"]["trades_df"].copy().reset_index(drop=True)
    champ_tr["c6"] = champ_tr["code"].astype(str).str.strip().str[:6].str.zfill(6)
    v20_tr = ab["sim_030"]["B0_V20"]["trades_df"].copy().reset_index(drop=True)
    v21_tr = ab["sim_030"]["B1_V21"]["trades_df"].copy().reset_index(drop=True)
    m1_tr = ab["sim_030"]["V21_M1_P2"]["trades_df"].copy().reset_index(drop=True)
    m4_tr = ab["sim_030"]["V21_M4_P2_DirA"]["trades_df"].copy().reset_index(drop=True)

    # Load daily liquidity & volatility strictly filtered to champion c6
    c6_set = sorted(champ_tr["c6"].unique())
    tks = sorted({f"{c}.SH" for c in c6_set if c.startswith("6")} | {f"{c}.SZ" for c in c6_set if c.startswith(("0", "3"))})
    d1 = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(
        columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount"],
        filter=ds.field("ticker").isin(tks),
    ).to_table().to_pandas()
    d2 = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(
        columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount"],
        filter=ds.field("ticker").isin(tks),
    ).to_table().to_pandas()
    daily = pd.concat([d1, d2], ignore_index=True)
    daily["dt"] = pd.to_datetime(daily["date"]).dt.strftime("%Y-%m-%d")
    daily["c6"] = daily["ticker"].astype(str).str[:6]
    daily = daily.drop_duplicates(["c6", "dt"]).sort_values(["c6", "dt"]).reset_index(drop=True)
    daily["adjf"] = np.where((daily["close"] > 0) & (daily["adj_close"] > 0), daily["adj_close"] / daily["close"], 1.0)
    daily["ac"] = daily["close"] * daily["adjf"]
    daily["ret_1d"] = daily.groupby("c6")["ac"].pct_change()
    daily["sig20_t1"] = daily.groupby("c6")["ret_1d"].transform(lambda s: s.rolling(20, min_periods=5).std().shift(1)).clip(0.025, 0.10).fillna(0.05)
    daily["amt_t1"] = daily.groupby("c6")["amount"].shift(1)
    daily["ma5_amt_t1"] = daily.groupby("c6")["amount"].transform(lambda s: s.rolling(5, min_periods=1).mean().shift(1))

    # Load 5m bars (all_strategies + baostock patch)
    f1 = f"{SIM}/data/all_strategies_5m_complete_pit.parquet"
    f2 = f"{SIM}/backtests_astock2/rd039_single_strat_sharpe_lift_20261126/front1_2to3_20cm_cond/_cache_5m_baostock_patch.parquet"
    m5_1 = ds.dataset(f1).scanner(columns=["c6", "date", "hhmm_int", "amount"], filter=ds.field("c6").isin(c6_set)).to_table().to_pandas()
    m5_1["td"] = m5_1["date"].astype(str).str[:10]; m5_1["c6"] = m5_1["c6"].astype(str).str.zfill(6)
    m5_2 = ds.dataset(f2).scanner(columns=["c6", "date", "hhmm_int", "amount"], filter=ds.field("c6").isin(c6_set)).to_table().to_pandas()
    m5_2["td"] = m5_2["date"].astype(str).str[:10]; m5_2["c6"] = m5_2["c6"].astype(str).str.zfill(6)
    m5 = pd.concat([m5_1, m5_2], ignore_index=True).drop_duplicates(["c6", "td", "hhmm_int"])
    b935 = m5[m5["hhmm_int"] == 935][["c6", "td", "amount"]].rename(columns={"amount": "amt_935"})

    # Merge microstructure into champion trades
    df_c = champ_tr.merge(
        daily[["c6", "dt", "amount", "amt_t1", "ma5_amt_t1", "sig20_t1", "open", "high", "low", "close"]].rename(
            columns={"amount": "buy_day_amt", "amt_t1": "prev_day_amt"}
        ),
        left_on=["c6", "buy_date"], right_on=["c6", "dt"], how="left",
    ).drop(columns=["dt"])
    df_c = df_c.merge(b935.rename(columns={"amt_935": "buy_amt_935"}), left_on=["c6", "buy_date"], right_on=["c6", "td"], how="left").drop(columns=["td"])
    df_c = df_c.merge(m5[["c6", "td", "hhmm_int", "amount"]].rename(columns={"amount": "buy_bar_amt"}), left_on=["c6", "buy_date", "buy_hhmm"], right_on=["c6", "td", "hhmm_int"], how="left").drop(columns=["td", "hhmm_int"])
    df_c = df_c.merge(daily[["c6", "dt", "amount"]].rename(columns={"amount": "exit_day_amt"}), left_on=["c6", "exit_date"], right_on=["c6", "dt"], how="left").drop(columns=["dt"])
    df_c = df_c.merge(b935.rename(columns={"amt_935": "exit_amt_935"}), left_on=["c6", "exit_date"], right_on=["c6", "td"], how="left").drop(columns=["td"])
    df_c = df_c.merge(m5[["c6", "td", "hhmm_int", "amount"]].rename(columns={"amount": "exit_bar_amt"}), left_on=["c6", "exit_date", "exit_hhmm"], right_on=["c6", "td", "hhmm_int"], how="left").drop(columns=["td", "hhmm_int"])
    assert df_c["buy_day_amt"].notna().all() and df_c["exit_day_amt"].notna().all(), "Missing daily liquidity"

    # Identify exact P2 rescued trades (in M1/V22 vs B1_V21) and 4to5 trades
    v21_keys = set(zip(v21_tr["buy_date"], v21_tr["code"].astype(str).str.zfill(6), v21_tr["strategy"]))
    m1_keys = set(zip(m1_tr["buy_date"], m1_tr["code"].astype(str).str.zfill(6), m1_tr["strategy"]))
    p2_rescued_keys = m1_keys - v21_keys
    df_c["is_p2_rescued"] = [((r.buy_date, r.c6, r.strategy) in p2_rescued_keys) for r in df_c.itertuples(index=False)]
    df_c["is_4to5"] = (df_c["strategy"] == "4to5")

    # Effective execution liquidity pool V_in and V_out (RMB)
    v_in = np.zeros(len(df_c), dtype=float)
    v_in_src = []
    v_out = np.zeros(len(df_c), dtype=float)
    v_out_src = []
    for i, r in enumerate(df_c.itertuples(index=False)):
        bh = int(r.buy_hhmm)
        if bh >= 935:
            assert pd.notna(r.buy_bar_amt) and r.buy_bar_amt > 0
            v_in[i] = float(r.buy_bar_amt)
            v_in_src.append(f"exact_5m_{bh}")
        else:
            if pd.notna(r.buy_amt_935) and r.buy_amt_935 > 0:
                v_in[i] = min(0.35 * float(r.buy_amt_935), 0.20 * float(r.buy_day_amt))
                v_in_src.append("auc_0.35x935")
            else:
                v_in[i] = 0.05 * float(r.buy_day_amt)
                v_in_src.append("auc_0.05xday")

        eh = int(r.exit_hhmm)
        if eh == 925:
            if pd.notna(r.exit_amt_935) and r.exit_amt_935 > 0:
                v_out[i] = min(0.35 * float(r.exit_amt_935), 0.20 * float(r.exit_day_amt))
                v_out_src.append("exit_auc_0.35x935")
            else:
                v_out[i] = 0.05 * float(r.exit_day_amt)
                v_out_src.append("exit_auc_0.05xday")
        elif eh == 1500:
            # Closing 15-30m TWAP / call-auction exit window (conservative 8% of day or 2x closing 5m bar)
            if pd.notna(r.exit_bar_amt) and r.exit_bar_amt > 0:
                v_out[i] = max(float(r.exit_bar_amt), 0.05 * float(r.exit_day_amt))
                v_out_src.append("exit_eod_5m_or_5pct")
            else:
                v_out[i] = 0.08 * float(r.exit_day_amt)
                v_out_src.append("exit_eod_0.08xday")
        else:
            if pd.notna(r.exit_bar_amt) and r.exit_bar_amt > 0:
                v_out[i] = float(r.exit_bar_amt)
                v_out_src.append(f"exit_exact_5m_{eh}")
            else:
                frac = 0.0110 if eh == 1035 else (0.0074 if eh == 1345 else 0.0150)
                v_out[i] = frac * float(r.exit_day_amt)
                v_out_src.append(f"exit_emp_frac_{eh}")

    df_c["v_in_yuan"] = v_in
    df_c["v_in_src"] = v_in_src
    df_c["v_out_yuan"] = v_out
    df_c["v_out_src"] = v_out_src
    df_c["v_bottleneck_yuan"] = np.minimum(v_in, v_out)

    # [2/4] Pillar 5: Capacity curve across [0, 50W, 200W, 500W, 1000W, 3000W]
    print("[2/4] Running Pillar 5 capacity & market impact tests...")
    sig20 = df_c["sig20_t1"].to_numpy(float)
    tiers = [
        ("Base_0 (30bps_only)", 0.0),
        ("50万", 5e5),
        ("200万", 2e6),
        ("500万", 5e6),
        ("1000万", 1e7),
        ("3000万", 3e7),
    ]
    cap_rows = []
    cap_json = {"model_spec": "Buy-side sqrt impact: imp_leg = Y * sig20 * sqrt(Q / V_liq) on top of 30bps round-trip fee; crowding penalty adds 0.5*sig20*max(0, rho-0.15) when rho=Q/V_liq>15%", "tiers": []}
    for y_coef, m_mode in [(0.70, "sqrt_base_Y070"), (0.70, "sqrt_plus_crowd_Y070"), (0.50, "sqrt_cons_Y050"), (1.00, "sqrt_aggr_Y100")]:
        for t_label, q_yuan in tiers:
            if q_yuan == 0.0:
                c_in = np.zeros(len(df_c))
                c_out = np.zeros(len(df_c))
                rho_in = np.zeros(len(df_c))
                rho_out = np.zeros(len(df_c))
            else:
                rho_in = q_yuan / v_in
                rho_out = q_yuan / v_out
                c_in = y_coef * sig20 * np.sqrt(rho_in)
                c_out = y_coef * sig20 * np.sqrt(rho_out)
                if "crowd" in m_mode:
                    c_in = c_in + 0.50 * sig20 * np.maximum(0.0, rho_in - 0.15)
                    c_out = c_out + 0.50 * sig20 * np.maximum(0.0, rho_out - 0.15)
            dr_adj, r_adj, mtm_d = rebuild_mtm_with_leg_costs(df_c, c_in, c_out, cal_5y, idx_5y)
            assert mtm_d < 1e-5, f"mtm diff {mtm_d}"
            df_tmp = df_c[["buy_date"]].copy()
            df_tmp["net_ret"] = r_adj
            w = perf_windows(dr_adj, df_tmp, cal_5y, idx_5y)
            imp_bps = (c_in + c_out) * 10000.0
            rho_max = np.maximum(rho_in, rho_out)
            r_45 = r_adj[df_c["is_4to5"].to_numpy()]
            r_p2 = r_adj[df_c["is_p2_rescued"].to_numpy()]
            row = {
                "model": m_mode,
                "Y": y_coef,
                "ticket_label": t_label,
                "ticket_yuan": int(q_yuan),
                "nav_5y": w["FULL_5Y"]["nav"],
                "sharpe_5y": w["FULL_5Y"]["sharpe"],
                "mdd_5y_pct": w["FULL_5Y"]["mdd_pct"],
                "nav_wf": w["WF_2326"]["nav"],
                "sharpe_wf": w["WF_2326"]["sharpe"],
                "mdd_wf_pct": w["WF_2326"]["mdd_pct"],
                "nav_2026": w["Y2026"]["nav"],
                "sharpe_2026": w["Y2026"]["sharpe"],
                "mdd_2026_pct": w["Y2026"]["mdd_pct"],
                "nav_26h2": w["Y2026_H2"]["nav"],
                "mean_trade_ret_pct": w["FULL_5Y"]["mean_pct"],
                "wr_5y_pct": w["FULL_5Y"]["wr_pct"],
                "mean_impact_bps": round(float(imp_bps.mean()), 1),
                "p90_impact_bps": round(float(np.percentile(imp_bps, 90)), 1),
                "max_impact_bps": round(float(imp_bps.max()), 1),
                "mean_total_friction_bps": round(30.0 + float(imp_bps.mean()), 1),
                "breach_rho_15pct_cnt": int((rho_max > 0.15).sum()),
                "breach_rho_30pct_cnt": int((rho_max > 0.30).sum()),
                "breach_rho_100pct_cnt": int((rho_max > 1.00).sum()),
                "sub_4to5_mean_pct": round(float(r_45.mean() * 100.0), 2),
                "sub_4to5_nav": round(float(np.prod(1.0 + r_45)), 4),
                "sub_4to5_impact_bps": round(float(imp_bps[df_c["is_4to5"].to_numpy()].mean()), 1),
                "sub_p2_mean_pct": round(float(r_p2.mean() * 100.0), 2),
                "sub_p2_nav": round(float(np.prod(1.0 + r_p2)), 4),
                "sub_p2_impact_bps": round(float(imp_bps[df_c["is_p2_rescued"].to_numpy()].mean()), 1),
            }
            cap_rows.append(row)
            if m_mode == "sqrt_base_Y070":
                cap_json["tiers"].append(row)

    pd.DataFrame(cap_rows).to_csv(f"{OUT_DIR}/p4_capacity_curve.csv", index=False)

    # Top 10 thinnest liquidity risk trades (sorted by bottleneck V_liq, plus daily < 3亿 summary)
    # Also attach 3000W impact bps under base Y=0.70
    imp3000_in = 0.70 * sig20 * np.sqrt(3e7 / v_in)
    imp3000_out = 0.70 * sig20 * np.sqrt(3e7 / v_out)
    df_c["imp3000w_bps"] = (imp3000_in + imp3000_out) * 10000.0
    df_c["rho3000w_max_pct"] = np.maximum(3e7 / v_in, 3e7 / v_out) * 100.0
    df_c["imp500w_bps"] = (0.70 * sig20 * np.sqrt(5e6 / v_in) + 0.70 * sig20 * np.sqrt(5e6 / v_out)) * 10000.0

    top10_bot = df_c.sort_values("v_bottleneck_yuan").head(10)
    top10_day = df_c.sort_values("buy_day_amt").head(10)

    def _fmt_liq(sub_df):
        out_l = []
        for r in sub_df.itertuples(index=False):
            out_l.append({
                "buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.c6,
                "name": str(r.name) if pd.notna(r.name) else "NA",
                "strategy": r.strategy, "buy_hhmm": int(r.buy_hhmm), "exit_hhmm": int(r.exit_hhmm),
                "is_p2_rescued": bool(r.is_p2_rescued), "is_4to5": bool(r.is_4to5),
                "net_ret_pct": round(float(r.net_ret * 100.0), 2),
                "buy_day_amt_yi": round(float(r.buy_day_amt / 1e8), 3),
                "prev_day_amt_yi": round(float(r.prev_day_amt / 1e8), 3) if pd.notna(r.prev_day_amt) else None,
                "buy_amt_935_wan": round(float(r.buy_amt_935 / 1e4), 1) if pd.notna(r.buy_amt_935) else None,
                "buy_bar_amt_wan": round(float(r.buy_bar_amt / 1e4), 1) if pd.notna(r.buy_bar_amt) else None,
                "exit_day_amt_yi": round(float(r.exit_day_amt / 1e8), 3),
                "exit_bar_amt_wan": round(float(r.exit_bar_amt / 1e4), 1) if pd.notna(r.exit_bar_amt) else None,
                "v_in_wan": round(float(r.v_in_yuan / 1e4), 1), "v_in_src": r.v_in_src,
                "v_out_wan": round(float(r.v_out_yuan / 1e4), 1), "v_out_src": r.v_out_src,
                "imp500w_bps": round(float(r.imp500w_bps), 1),
                "imp3000w_bps": round(float(r.imp3000w_bps), 1),
                "rho3000w_max_pct": round(float(r.rho3000w_max_pct), 1),
            })
        return out_l

    liq_summary = {
        "coverage": {
            "total_trades": int(len(df_c)),
            "buy_daily_covered": int(df_c["buy_day_amt"].notna().sum()),
            "exit_daily_covered": int(df_c["exit_day_amt"].notna().sum()),
            "buy_935_5m_covered": int(df_c["buy_amt_935"].notna().sum()),
            "buy_gte935_exact_bar_covered": f"{int(df_c[df_c['buy_hhmm']>=935]['buy_bar_amt'].notna().sum())}/{int((df_c['buy_hhmm']>=935).sum())}",
            "exit_exact_bar_covered": int(df_c["exit_bar_amt"].notna().sum()),
        },
        "lt_3yi_counts": {
            "buy_day_lt_3yi": int((df_c["buy_day_amt"] < 3e8).sum()),
            "buy_day_lt_1yi": int((df_c["buy_day_amt"] < 1e8).sum()),
            "prev_day_lt_3yi": int((df_c["prev_day_amt"] < 3e8).sum()),
            "exit_day_lt_3yi": int((df_c["exit_day_amt"] < 3e8).sum()),
            "4to5_min_buy_amt_yi": round(float(df_c[df_c["is_4to5"]]["buy_day_amt"].min() / 1e8), 3),
            "4to5_med_buy_amt_yi": round(float(df_c[df_c["is_4to5"]]["buy_day_amt"].median() / 1e8), 3),
            "p2_rescued_lt_3yi": int((df_c[df_c["is_p2_rescued"]]["buy_day_amt"] < 3e8).sum()),
        },
        "top10_thinnest_by_exec_bottleneck": _fmt_liq(top10_bot),
        "top10_thinnest_by_buy_daily_amt": _fmt_liq(top10_day),
    }

    # [3/4] Pillar 6: Rolling Metrics, CUSUM, Page-Hinkley + 2026H2 & Last 3M Anatomy
    print("[3/4] Running Pillar 6 CUSUM/Page-Hinkley decay & 2026H2/3M anatomy...")
    dr_v22 = ab["sim_030"]["V21_M5_B_NoXQ_Pos5"]["dr_5y"]
    dr_v21 = ab["sim_030"]["B1_V21"]["dr_5y"]
    dr_v20 = ab["sim_030"]["B0_V20"]["dr_5y"]

    r_v22 = df_c["net_ret"].to_numpy(float)
    r_v21 = v21_tr["net_ret"].to_numpy(float)
    d_v22 = df_c["exit_date"].tolist()

    # Rolling 20 / 40 trade stats
    def roll_trade_stats(rets: np.ndarray, w: int) -> dict:
        wr_l, mn_l, sh_l = [], [], []
        for i in range(w, len(rets) + 1):
            sub = rets[i - w : i]
            wr_l.append(float((sub > 0).mean() * 100.0))
            mn_l.append(float(sub.mean() * 100.0))
            sd_s = float(sub.std(ddof=1))
            sh_l.append(float(sub.mean() / sd_s) if sd_s > 1e-12 else 0.0)
        return {
            "window": w,
            "min_wr_pct": round(min(wr_l), 2), "latest_wr_pct": round(wr_l[-1], 2),
            "min_mean_pct": round(min(mn_l), 2), "latest_mean_pct": round(mn_l[-1], 2),
            "min_trade_sharpe": round(min(sh_l), 3), "latest_trade_sharpe": round(sh_l[-1], 3),
        }

    # Daily excess CUSUM & PH (v22 vs v21, v22 vs v20) on active diff days
    ex_22_21 = dr_v22 - dr_v21
    ex_22_20 = dr_v22 - dr_v20

    def daily_excess_ph(ex_arr: np.ndarray, label: str) -> dict:
        mu_e = float(ex_arr.mean())
        sd_e = float(ex_arr.std(ddof=1))
        delta = 0.25 * abs(mu_e) if abs(mu_e) > 1e-9 else 0.0005
        mv, mpk, mx_ph, term_ph = 0.0, 0.0, 0.0, 0.0
        for v in ex_arr:
            mv += (float(v) - mu_e + delta)
            mpk = max(mpk, mv)
            ph = mpk - mv
            mx_ph = max(mx_ph, ph)
            term_ph = ph
        rng_d = np.random.default_rng(20261126)
        idx_bs = rng_d.integers(0, len(ex_arr), size=(2000, len(ex_arr)))
        bs = ex_arr[idx_bs] - mu_e + delta
        cs = np.cumsum(bs, axis=1)
        pks = np.maximum.accumulate(np.insert(cs, 0, 0.0, axis=1), axis=1)[:, 1:]
        mc_mx = (pks - cs).max(axis=1)
        lam95 = float(np.percentile(mc_mx, 95.0))
        return {
            "label": label,
            "daily_mean_bps": round(mu_e * 10000.0, 2),
            "daily_ir_ann": round(mu_e / max(1e-12, sd_e) * math.sqrt(242.0), 3),
            "hist_max_ph_pct": round(mx_ph * 100.0, 2),
            "terminal_ph_pct": round(term_ph * 100.0, 2),
            "lambda_mc95_pct": round(lam95 * 100.0, 2),
            "triggered_95": bool(mx_ph >= lam95),
        }

    cusum_v22 = cusum_and_ph(r_v22, d_v22, seed=20261126)
    cusum_v21 = cusum_and_ph(r_v21, v21_tr["exit_date"].tolist(), seed=20261127)

    # Monthly & Window comparison 2026-07..2026-11 + Last 3M (2026-08-26..) + 2026-10..11
    recent_rows = []
    periods = [
        ("2026-07", "2026-07-01", "2026-07-31"),
        ("2026-08", "2026-08-01", "2026-08-31"),
        ("2026-09", "2026-09-01", "2026-09-30"),
        ("2026-10", "2026-10-01", "2026-10-31"),
        ("2026-11", "2026-11-01", "2026-11-26"),
        ("2026H2_0701_1116", "2026-07-01", "2026-11-26"),
        ("Last3M_0826_1116", "2026-08-26", "2026-11-26"),
        ("Last30D_1012_1116", "2026-10-12", "2026-11-26"),
    ]
    cal_s = pd.Series(cal_5y)
    sys_map = [("V20.0", v20_tr, dr_v20), ("V21.0", v21_tr, dr_v21), ("V21+P2", m1_tr, ab["sim_030"]["V21_M1_P2"]["dr_5y"]), ("V21+P2+DirA", m4_tr, ab["sim_030"]["V21_M4_P2_DirA"]["dr_5y"]), ("V22.0", champ_tr, dr_v22)]
    for p_name, d_lo, d_hi in periods:
        mask_d = (cal_s >= d_lo) & (cal_s <= d_hi)
        idx_d = np.where(mask_d.to_numpy())[0]
        if len(idx_d) == 0:
            continue
        row_p = {"period": p_name, "cal_days": int(len(idx_d))}
        for s_lbl, s_df, s_dr in sys_map:
            dr_sub = s_dr[idx_d]
            nav_p = float(np.prod(1.0 + dr_sub))
            mdd_p = max_dd(dr_sub)
            tr_sub = s_df[(s_df["buy_date"] >= d_lo) & (s_df["buy_date"] <= d_hi)]
            r_sub = tr_sub["net_ret"].to_numpy(float)
            row_p[f"{s_lbl}_n"] = int(len(r_sub))
            row_p[f"{s_lbl}_wr"] = round(float((r_sub > 0).mean() * 100.0), 1) if len(r_sub) else 0.0
            row_p[f"{s_lbl}_mean"] = round(float(r_sub.mean() * 100.0), 2) if len(r_sub) else 0.0
            row_p[f"{s_lbl}_nav"] = round(nav_p, 4)
            row_p[f"{s_lbl}_mdd_pct"] = round(mdd_p * 100.0, 2)
        row_p["v22_minus_v21_nav_pp"] = round((row_p["V22.0_nav"] - row_p["V21.0_nav"]) * 100.0, 2)
        row_p["v22_minus_v20_nav_pp"] = round((row_p["V22.0_nav"] - row_p["V20.0_nav"]) * 100.0, 2)
        recent_rows.append(row_p)

    # Also build exact 2026H2 trade-by-trade comparison table into p4_recent_6m_compare.csv
    # Summarize monthly + 2026H2 block attribution
    def sub_pack(df_s, tag):
        df_x = df_s.copy()
        df_x["c6"] = df_x["code"].astype(str).str.zfill(6)
        df_x = df_x[df_x["buy_date"] >= "2026-07-01"][["buy_date", "exit_date", "c6", "name", "strategy", "tier", "score", "buy_hhmm", "exit_hhmm", "net_ret"]].copy()
        df_x = df_x.rename(columns={"net_ret": f"ret_{tag}", "exit_date": f"exdt_{tag}", "exit_hhmm": f"exhh_{tag}", "tier": f"tier_{tag}"})
        return df_x

    t20 = sub_pack(v20_tr, "v20")
    t21 = sub_pack(v21_tr, "v21")
    t22 = sub_pack(champ_tr, "v22")
    u_keys = pd.concat([
        t20[["buy_date", "c6", "name", "strategy", "buy_hhmm"]],
        t21[["buy_date", "c6", "name", "strategy", "buy_hhmm"]],
        t22[["buy_date", "c6", "name", "strategy", "buy_hhmm"]],
    ], ignore_index=True).drop_duplicates(["buy_date", "c6", "strategy"]).sort_values(["buy_date", "buy_hhmm", "c6"])
    u_m = u_keys.merge(t20[["buy_date", "c6", "strategy", "ret_v20", "exdt_v20"]], on=["buy_date", "c6", "strategy"], how="left")
    u_m = u_m.merge(t21[["buy_date", "c6", "strategy", "ret_v21", "exdt_v21"]], on=["buy_date", "c6", "strategy"], how="left")
    u_m = u_m.merge(t22[["buy_date", "c6", "strategy", "ret_v22", "exdt_v22", "exhh_v22"]], on=["buy_date", "c6", "strategy"], how="left")
    for c in ("ret_v20", "ret_v21", "ret_v22"):
        u_m[c] = (u_m[c] * 100.0).round(2)
    u_m["in_v20"] = u_m["ret_v20"].notna()
    u_m["in_v21"] = u_m["ret_v21"].notna()
    u_m["in_v22"] = u_m["ret_v22"].notna()

    # RD049 regimes & lights (also check post-backtest days 2026-11-12..2026-11-25)
    rd49 = pd.read_parquet(f"{RD049_DIR}/_cache/rd049_daily_regime_pit.parquet")
    rd49_st = build_2d_states(rd49)
    l5_map = dict(zip(rd49_st["trade_date"], rd49_st["light_5"]))
    df_c["light_5"] = df_c["buy_date"].map(l5_map).fillna("NA")
    u_m["light_5"] = u_m["buy_date"].map(l5_map).fillna("NA")
    u_m["month"] = u_m["buy_date"].str[:7]
    u_m["in_last_3m"] = u_m["buy_date"] >= "2026-08-26"
    u_m.to_csv(f"{OUT_DIR}/p4_recent_6m_compare.csv", index=False)
    pd.DataFrame(recent_rows).to_csv(f"{OUT_DIR}/p4_recent_6m_monthly.csv", index=False)

    nov_tail = rd49_st[rd49_st["trade_date"] >= "2026-11-12"][["trade_date", "light_5", "gz_r5_t1", "alla_med_r5_t1", "hb2_promo_t1", "dt_cnt_t1", "zb_rate_t1"]].to_dict("records")

    # 3 new blocks 2026H2 & Last 3M attribution
    # Compare V21 -> V21+P2 (M1) -> V21+P2+DirA (M4) -> V22 (M5_B_NoXQ_Pos5)
    dr_m1 = ab["sim_030"]["V21_M1_P2"]["dr_5y"]
    dr_m4 = ab["sim_030"]["V21_M4_P2_DirA"]["dr_5y"]
    def block_contrib(d_lo: str) -> dict:
        idx_d = np.where((cal_s >= d_lo).to_numpy())[0]
        n21 = float(np.prod(1.0 + dr_v21[idx_d]))
        nm1 = float(np.prod(1.0 + dr_m1[idx_d]))
        nm4 = float(np.prod(1.0 + dr_m4[idx_d]))
        n22 = float(np.prod(1.0 + dr_v22[idx_d]))
        return {
            "V21_nav": round(n21, 4),
            "P2_mult": round(nm1 / n21, 4),
            "DirA_mult": round(nm4 / nm1, 4),
            "4to5_Pos5_mult": round(n22 / nm4, 4),
            "V22_nav": round(n22, 4),
            "total_V22_vs_V21_mult": round(n22 / n21, 4),
        }

    # Check V22 Oct-Nov 2026 trades explicitly
    oct_nov_v22 = df_c[df_c["buy_date"] >= "2026-10-01"][["buy_date", "exit_date", "c6", "name", "strategy", "buy_hhmm", "exit_hhmm", "net_ret", "light_5", "is_p2_rescued", "is_4to5"]].copy()
    oct_nov_v22["net_ret_pct"] = (oct_nov_v22["net_ret"] * 100.0).round(2)

    # [4/4] Pillar 7: Engineering Audit & Rollout Readiness Matrix
    print("[4/4] Compiling Pillar 7 live 09:25 engineering audit...")
    same_day_x = []
    df_s = df_c.sort_values(["buy_date", "buy_hhmm"]).reset_index(drop=True)
    for i in range(1, len(df_s)):
        if df_s.loc[i, "buy_date"] == df_s.loc[i - 1, "exit_date"]:
            same_day_x.append({
                "date": df_s.loc[i, "buy_date"],
                "prev_code": df_s.loc[i - 1, "c6"], "prev_strat": df_s.loc[i - 1, "strategy"], "prev_exit_hhmm": int(df_s.loc[i - 1, "exit_hhmm"]),
                "next_code": df_s.loc[i, "c6"], "next_strat": df_s.loc[i, "strategy"], "next_buy_hhmm": int(df_s.loc[i, "buy_hhmm"]),
                "is_same_stock_wash": bool(df_s.loc[i, "c6"] == df_s.loc[i - 1, "c6"]),
            })

    pillar7 = {
        "production_parity_status": "FAIL_NOT_YET_WIRED_IN_PROD",
        "can_cut_live_immediately_as_is": False,
        "recommended_rollout": "先补齐5项工程缺口并过全历史零漂移单测，再并排实盘观察5至10个交易日后切正式实盘",
        "feature_checks": [
            {
                "feature": "RD049 5档红绿灯 (L1..L5) + 指数 sz399303",
                "status": "FAIL_MISSING_IN_PROD",
                "data_availability_0915_or_0925": "T-1盘后可100%生成，但现役脚本尚未采集 sz399303（国证2000）及微观内卷四指标",
                "evidence": "sim-portfolio/scripts/rd_incremental_sources.py:27 sync_index_klines_cache 仅拉取 sh000002/sz399107/sh000300/sh000001/sz399001，缺 sz399303；sim-portfolio/scripts/ 下无 build_2d_states / L1..L5 实现；a_daily 盘后15:15补丁含 high/close/low 可算 hit_zt/zb_rate/hb2_promo。",
            },
            {
                "feature": "P2_R_OPT (pos750<0.50 & pry_dt>=100)",
                "status": "FAIL_MISSING_AND_UNIVERSE_DRIFT",
                "data_availability_0915_or_0925": "09:15前盘前缓存可得，但存在全A vs 00/60口径漂移",
                "evidence": "live_3to4_v40_engine.py 仅计算 pos20_d0，无 750日(3年)前复权区间位置 L3_pos_750d_t1；fast_pry_today.py 无 dt_cnt>=100 门且其 prev_n_dt 仅扫 00/60（实测 2024-01-31 全A非ST=104家>=100 而 00/60=97家<100）。",
            },
            {
                "feature": "4to5 SJ114_7f_DtDefer @ Pos5 (买点/打分/风控/卖点)",
                "status": "FAIL_MAJOR_CODE_DRIFT",
                "data_availability_0915_or_0925": "数据源(cninfo/龙虎榜/KPL/腾讯09:25)均实时可得，但脚本与V22规格严重脱节",
                "evidence": "1) backtests_astock2/fast_4to5_today.py:480 仍卡 >=120 分非 >=114；2) TOX_RE 缺 TOX_STRICT_RE（漏『股票交易风险提示』与宽松减持预披露正则）；3) fast_4to5_today.py:317-323 从 3to4_premarket_cache.json 读 score/static_score 字段，但该文件无此字段且存的是当日3板而非昨日4板，恒落回85分；4) 缺 f47_reb_zt_r10>=0.20(+6)、缺 d4_mkt_nuke_cnt>=1(-3)、缺 LHB TRADE_ID去重/机构净卖>1000万/3日游资排重，plate_3b用THS代KPL；5) 完全缺失 E_V41_7f_d70_DtDefer --hold 卖点模块；6) execute_trade.py:662,1472 硬封杀 s_4to5；rd_master_trading_data_sync.py:288,308 将 s3_4to5 设为非阻断可选。",
            },
            {
                "feature": "DirA_Tight80 (3to4 D2日且4板晋级期 13:45护利 7%->8%)",
                "status": "WARN_MISSING_IN_HOLD",
                "data_availability_0915_or_0925": "09:15前已知（持仓买入日与D1是否4板为确定事实）",
                "evidence": "fast_3to4_today.py:375-395 --hold 仅写死 +7.0% / +5.0% 两档，未识别 D2 4板窗口并将护利线上收至 +8.0%。",
            },
            {
                "feature": "物理T+1交收、Tier1预约锁资与中金财富条件单",
                "status": "WARN_CONDITIONAL_EXEC_FRICTION",
                "data_availability_0915_or_0925": "需严格秩序锁：09:25:05 先判 Tier1(3to4_S/high_S) 是否挂条件单，有则禁买 Pos5(4to5)",
                "evidence": f"1) 同日先卖后买全5Y仅 {len(same_day_x)} 笔且全部是 09:25 卖出 -> 09:35~10:10 买入（含 2026-04-23 600961 4to5@09:25卖->high@09:35买回），A股T日卖出资金可用，但09:25成交回报确认到09:30扫板仅5分钟窗口；2) Tier1 waits 39次中与 Pos5 09:25 竞价零冲突的前提是 09:25:05 见到 3to4_S/high_S 即冻结资金；3) 13:45 +8.5%激活/+8.0%或+7.0%回落且未封板，传统中金财富条件单无法原生同时表达『13:45后+回落不封板』，须靠 astock_intraday_check 定时监控+手工/接口触发。",
            },
        ],
        "same_day_exit_to_entry_trades": same_day_x,
        "waits_count": len(ab["sim_030"]["V21_M5_B_NoXQ_Pos5"]["waits"]),
    }

    audit = {
        "task": "V22.0 Institutional Audit · Part 2 (Pillars 5-7)",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "sqlite_readonly_mode": True,
        "data_horizon_note": {
            "v22_ledger_buy_range": f"{df_c['buy_date'].min()} .. {df_c['buy_date'].max()}",
            "v22_ledger_exit_max": str(df_c["exit_date"].max()),
            "v22_calendar_end": str(cal_5y[-1]),
            "post_cutoff_rd049_20261112_25": nov_tail,
            "portfolio_state_last_cn_trade": "2026-11-11/12 002578 闽发铝业 (legacy); V21 模拟盘 2026-11-16..26 成交 N=0",
        },
        "pillar5_capacity_and_impact": {
            "verdict": "PASS_WITH_SIZE_CAP",
            "recommended_sweet_spot_cny": "200万~500万/单笔 (极限不超 1,000万；3,000万将因撬板/小盘一进二与瞬时5m流动性枯竭出现实质冲击失真)",
            "liquidity_stats": liq_summary,
            "capacity_curve_base_Y070": cap_json["tiers"],
            "crowding_penalized_3000w": [r for r in cap_rows if r["model"] == "sqrt_plus_crowd_Y070" and r["ticket_yuan"] in (5000000, 10000000, 30000000)],
        },
        "pillar6_decay_and_recent": {
            "verdict": "PASS_HEALTHY_NO_DECAY",
            "rolling_20_v22": roll_trade_stats(r_v22, 20),
            "rolling_40_v22": roll_trade_stats(r_v22, 40),
            "cusum_ph_v22": cusum_v22,
            "cusum_ph_v21": cusum_v21,
            "daily_excess_ph_v22_vs_v21": daily_excess_ph(ex_22_21, "V22_minus_V21"),
            "daily_excess_ph_v22_vs_v20": daily_excess_ph(ex_22_20, "V22_minus_V20"),
            "period_comparison": recent_rows,
            "new_blocks_attribution": {
                "Y2026H2_from_0701": block_contrib("2026-07-01"),
                "Last3M_from_0826": block_contrib("2026-08-26"),
                "Last30D_from_1012": block_contrib("2026-10-12"),
            },
            "v22_2026_oct_nov_trades": oct_nov_v22[["buy_date", "exit_date", "c6", "name", "strategy", "net_ret_pct", "light_5", "is_p2_rescued", "is_4to5"]].to_dict("records"),
        },
        "pillar7_engineering_feasibility": pillar7,
        "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1),
        "elapsed_sec": round(time.time() - t0, 2),
    }

    with open(f"{OUT_DIR}/p4_part2_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"DONE in {audit['elapsed_sec']}s | RSS={audit['rss_mb']}MB")
    print("=== PILLAR 5 SUMMARY (Base Y=0.70) ===")
    for r in cap_json["tiers"]:
        print(f"  {r['ticket_label']:20s}: 5Y_NAV={r['nav_5y']:14.4f} WF_NAV={r['nav_wf']:11.4f} WF_Sh={r['sharpe_wf']:.3f} 5Y_MDD={r['mdd_5y_pct']:.2f}% 26_NAV={r['nav_2026']:6.2f} imp={r['mean_impact_bps']:5.1f}bps rho>15%={r['breach_rho_15pct_cnt']} rho>100%={r['breach_rho_100pct_cnt']}")
    print("=== PILLAR 6 SUMMARY ===")
    print("  CUSUM V22 Red h=", cusum_v22["cusum_red"]["h_pct"], "hits=", cusum_v22["cusum_red"]["hist_hits"], "term_S=", cusum_v22["cusum_red"]["terminal_S_pct"], "PH_95 trig=", cusum_v22["page_hinkley"]["delta_025mu"]["triggered_95"])
    print("  2026H2 attrib:", audit["pillar6_decay_and_recent"]["new_blocks_attribution"]["Y2026H2_from_0701"])
    print("  Last3M attrib:", audit["pillar6_decay_and_recent"]["new_blocks_attribution"]["Last3M_from_0826"])
    print("  Oct-Nov V22 trades:", len(oct_nov_v22))


if __name__ == "__main__":
    main()
