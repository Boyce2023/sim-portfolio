#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Final V1.1 Core Scorecard, Strict +0.30% Penetration Exit Engine, and Truncation Rebuild."""
import bisect, glob, json, os, re, sqlite3, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

sys.dont_write_bytecode = True
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
PART2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
sys.path.insert(0, V1_DIR); sys.path.insert(0, PART2_DIR)

from backtest_utils import _sim_k_slots
from step2_is_exit_tree_opt import defer_to_sellable_close
from step0_build_clean_p1_pool import ST_ON_RE, ST_EXC_RE, ST_REV_RE, TOX_RE, REG_RE, REG_EXC, shift_cal, cnt_ts_win, is_st_at

V11_EXIT_CFG = {
    "zt_imm": False,
    "b2_body": 0.06,
    "b2_clv": 0.65,
    "b2_mode": "d3_hold",
    "b2_tp": 0.12,
    "b3_tp_mode": "adaptive",
    "b3_adapt_k": 1.5,
    "b4_body": -0.05,
    "b4_mode": "d2_close",
    "risk_mode": "inst_dt",
}

V11_FACTOR_META = [
    ("F01_open_gap", "D2_量价微观", "T+1开盘甜区[-7.0%,-3.0%](+4) / 核按钮<-8.0%(-10)", "+4 / -10", "温和深水错杀反抽赔率高，跌破-8%多为真崩盘"),
    ("F02_rfm_le20", "D1_筹码流通", "真实自由流值 <= 20亿 (+4，已剔除>40亿静态惩罚)", "+4", "轻量小流通盘弹性更足，且不误杀2025-2026高流动性中大票"),
    ("F03_dist3d30_ge10", "D2_监管空间", "距3日30%严重异动余量 >= 10%", "+4", "反抽空间充裕不卡监管异动红线"),
    ("F04_zt60d_ge2", "D2_股性记忆", "近60日涨停次数 >= 2 (含当日)", "+5", "具活跃股性记忆，游资承接辨识度高"),
    ("F05_seal_ratio_ge10_pen", "D2_诱多陷阱", "T0封单金额/成交额 >= 10% 却次日深低开", "-5", "大封单假一致次日却深低开说明隔夜资金集中撤退"),
    ("F06_inst_net_pos", "D3_机构背书", "T0龙虎榜机构专用净买入 > 0", "+5", "机构真金白银背书，次日错杀有底盘承接"),
    ("F07_mkt10_zt_gt55", "D4_情绪外溢", "T0全市场10cm涨停 > 70 (+7) / > 55 (+4)", "+7 / +4", "主板高风险偏好资金外溢至错杀20cm首板"),
    ("F08_yizi20_siphon_pen", "D4_同场虹吸", "T+1 09:25 全场出现 >= 1只20cm一字涨停", "-5", "20cm一字新龙吸干同场接力流动性"),
    ("F09_monday_pen", "D6_日历承压", "T+1买入日为周一", "-8", "周末消息消化后周一深开情绪承压胜率骤降"),
]


def compute_scorecard_v11(d: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    f = pd.DataFrame(index=d.index)
    f["F01_open_gap"] = np.where(d["f1_o_pct"] < -0.080, -10, np.where(d["f1_o_pct"].between(-0.070, -0.030), 4, 0))
    f["F02_rfm_le20"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    f["F03_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    f["F04_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    f["F05_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -5, 0)
    f["F06_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 5, 0)
    f["F07_mkt10_zt_gt55"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 7, np.where(d["mkt10_zt_cnt"].fillna(0) > 55, 4, 0))
    f["F08_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
    f["F09_monday_pen"] = np.where(d["f1_weekday"] == 0, -8, 0)
    sc = pd.Series(70.0 + f.sum(axis=1).to_numpy(), index=d.index)
    return sc, f


def sim_v11_exit(df: pd.DataFrame, cfg: dict, fee: float = 0.0030, tp_buf: float = 0.0030) -> pd.DataFrame:
    rows = []
    for r in df.itertuples(index=False):
        b_px = float(r.f1_ao)
        if np.isnan(b_px) or b_px <= 0:
            continue
        rm = cfg.get("risk_mode", "none")
        risk_hit = ((r.f1_lhb_inst_net < -2000.0) or (r.f1_mkt20_dt_cnt >= 3) or (r.f1_mkt10_dt_cnt >= 20)) if rm == "inst_dt" else False
        sell_k, s_px, reason = 2, np.nan, "d2_close"

        def try_tp(k, tp_r, ref_px):
            ao = float(getattr(r, f"f{k}_ao", np.nan))
            ah = float(getattr(r, f"f{k}_ah", np.nan))
            if np.isnan(ao) or np.isnan(ah) or (not getattr(r, f"f{k}_sellable", False)):
                return False, np.nan, ""
            open_dt = bool(getattr(r, f"f{k}_open_is_dt", False))
            tp_px = ref_px * (1.0 + tp_r)
            if ao >= tp_px and not open_dt:
                return True, ao, "gap_tp"
            zt_px_k = float(getattr(r, f"f{k}_zt_px_adj", 1e18) or 1e18)
            need_ah = min(tp_px * (1.0 + tp_buf), zt_px_k - 1e-4)
            if ah >= need_ah:
                return True, tp_px, "intraday_tp"
            return False, np.nan, ""

        if r.f1_zt:
            k = 2
            while k < 10:
                if np.isnan(float(getattr(r, f"f{k}_ac", np.nan))):
                    k = max(2, k - 1); break
                if getattr(r, f"f{k}_zt", False):
                    k += 1; continue
                sell_k, reason = k, "B1_zt_break"; break
            else:
                sell_k, reason = 10, "B1_zt_max10"
        else:
            f1_ac, f1_body, f1_clv = float(r.f1_ac), float(r.f1_body or 0.0), float(r.f1_clv or 0.5)
            is_b4 = (f1_body <= cfg.get("b4_body", -0.05) or r.f1_is_dt)
            is_b2 = (not is_b4) and (f1_body >= cfg.get("b2_body", 0.06)) and (f1_clv >= cfg.get("b2_clv", 0.65))
            if is_b4:
                sell_k, reason = 2, "B4_d2_close"
            elif is_b2:
                tp2 = min(cfg.get("b2_tp", 0.12), 0.07) if (risk_hit and cfg.get("b2_tp")) else cfg.get("b2_tp", None)
                if cfg.get("b2_mode") in ("d2_tp", "d3_hold") and tp2 is not None:
                    hit, px_h, r_h = try_tp(2, tp2, f1_ac)
                    if hit: s_px, sell_k, reason = px_h, 2, f"B2_{r_h}"
                if np.isnan(s_px):
                    if cfg.get("b2_mode") == "d3_hold" and (not risk_hit) and not np.isnan(r.f3_ac):
                        if r.f2_zt:
                            k = 3
                            while k < 10 and getattr(r, f"f{k}_zt", False): k += 1
                            sell_k, reason = k, "B2_d2zt_ride"
                        else:
                            if tp2 is not None:
                                hit3, px3, r3 = try_tp(3, tp2, float(r.f2_ac))
                                if hit3: s_px, sell_k, reason = px3, 3, f"B2_d3_{r3}"
                            if np.isnan(s_px): sell_k, reason = 3, "B2_d3_close"
                    else:
                        sell_k, reason = 2, "B2_d2_close"
            else:
                tp3 = max(0.06, min(0.15, abs(float(r.f1_o_pct)) * cfg.get("b3_adapt_k", 1.5))) if cfg.get("b3_tp_mode") == "adaptive" else cfg.get("b3_tp", None)
                if risk_hit and tp3 is not None: tp3 = min(tp3, 0.07)
                if tp3 is not None:
                    hit, px_h, r_h = try_tp(2, tp3, f1_ac)
                    if hit: s_px, sell_k, reason = px_h, 2, f"B3_{r_h}"
                if np.isnan(s_px): sell_k, reason = 2, "B3_d2_close"

        if np.isnan(s_px):
            sell_k, s_px = defer_to_sellable_close(r, sell_k)
            if sell_k < 2: continue
        s_dt = getattr(r, f"f{sell_k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0: continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({
            "sig_date": r.dt, "buy_date": r.f1_dt, "exit_date": s_dt,
            "c6": r.c6, "name": r.name, "dl": int(r.dl), "amount": float(r.amount),
            "score": float(getattr(r, "score", 0.0)), "open_pct": round(float(r.f1_o_pct) * 100.0, 2),
            "buy_px": b_px, "exit_px": s_px, "gross_ret": gross, "net_ret": net,
            "hold_bars": sell_k - 1, "exit_reason": reason, "risk_hit": int(risk_hit),
        })
    return pd.DataFrame(rows)


def truncation_20250101_v11(slot_A_full: pd.DataFrame, slot_S_full: pd.DataFrame) -> dict:
    t0 = time.time()
    CUT_DT, CUT_TS = "2024-12-31", "2024-12-31 23:59:59"
    ts_cut = pd.Timestamp(CUT_DT)
    cols_p = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    flt = ds.field("date") <= ts_cut
    a1 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols_p, filter=flt).to_table().to_pandas()
    a2 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols_p, filter=flt).to_table().to_pandas()
    a1["dl"], a2["dl"] = 0, 1
    raw_all = pd.concat([a1, a2], ignore_index=True)
    raw_all["c6"] = raw_all["ticker"].astype(str).str[:6]
    raw_all["dt"] = pd.to_datetime(raw_all["date"]).dt.strftime("%Y-%m-%d")
    raw_all = raw_all[raw_all["ticker"].str.endswith((".SH", ".SZ")) & (raw_all["close"] > 0) & (raw_all["adj_close"] > 0)].copy()
    raw_all = raw_all.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    d10 = raw_all[raw_all["c6"].str.startswith(("00", "60")) & (raw_all["dt"] >= "2020-12-01")].copy()
    g10 = d10.groupby("c6", sort=False); s10 = d10["adj_close"] / d10["close"]; pac10 = g10["adj_close"].shift(1); r10 = d10["adj_close"] / pac10 - 1.0
    ztp10 = np.floor((pac10 / s10) * 1.10 * 100.0 + 0.5) / 100.0; dtp10 = np.floor((pac10 / s10) * 0.90 * 100.0 + 0.5) / 100.0
    abn10 = r10.abs() > 0.12
    d10["is_zt"] = (pac10 > 0) & (d10["close"] >= ztp10 - 0.011) & (r10 >= 0.095) & (~abn10)
    d10["is_dt"] = (pac10 > 0) & (d10["close"] <= dtp10 + 0.011) & (r10 <= -0.095) & (~abn10)
    mkt10_zt = d10[d10["dt"] >= "2021-01-01"].groupby("dt")["is_zt"].sum().to_dict()
    mkt10_dt = d10[d10["dt"] >= "2021-01-01"].groupby("dt")["is_dt"].sum().to_dict()

    df = raw_all[raw_all["c6"].str.startswith(("30", "688", "689"))].copy().reset_index(drop=True)
    df["list_age"] = df.groupby("c6", sort=False).cumcount() + 1
    df = df[df["dt"] >= "2020-08-24"].copy().reset_index(drop=True)
    g = df.groupby("c6", sort=False); sc_ratio = df["adj_close"] / df["close"]
    df["ao"], df["ah"], df["al"], df["ac"] = df["open"] * sc_ratio, df["high"] * sc_ratio, df["low"] * sc_ratio, df["adj_close"]
    df["prev_ac"] = g["ac"].shift(1); df["ret"] = df["ac"] / df["prev_ac"] - 1.0; df["o_pct"] = df["ao"] / df["prev_ac"] - 1.0
    df["abn_ret"] = df["ret"].abs() > 0.22
    df["tradable"] = (df["volume"] > 0) & (df["open"] > 0) & (df["list_age"] > 10) & (~df["abn_ret"])
    prev_ex = df["prev_ac"] / sc_ratio
    df["zt_px"] = np.floor(prev_ex * 1.20 * 100.0 + 0.5) / 100.0; df["dt_px"] = np.floor(prev_ex * 0.80 * 100.0 + 0.5) / 100.0
    df["zt_px_adj"] = df["zt_px"] * sc_ratio; df["dt_px_adj"] = df["dt_px"] * sc_ratio
    df["is_zt"] = (df["prev_ac"] > 0) & (df["close"] >= df["zt_px"] - 0.011) & (df["ret"] >= 0.195) & (~df["abn_ret"])
    df["is_dt"] = (df["prev_ac"] > 0) & (df["close"] <= df["dt_px"] + 0.011) & (df["ret"] <= -0.195) & (~df["abn_ret"])
    df["is_yizi_zt"] = df["is_zt"] & (df["low"] == df["high"]) & (df["o_pct"] >= 0.195)
    df["buyable_open"] = (df["volume"] > 0) & (df["open"] > 0) & (~((df["o_pct"] >= 0.195) & (df["low"] == df["high"])))
    df["sellable_close"] = (df["volume"] > 0) & (df["close"] > 0) & (~((df["ret"] <= -0.195) & (df["low"] == df["high"])))
    df["open_is_dt"] = (df["prev_ac"] > 0) & (df["open"] <= df["dt_px"] + 0.011) & (df["o_pct"] <= -0.195)
    df["open_is_zt"] = (df["prev_ac"] > 0) & (df["open"] >= df["zt_px"] - 0.011) & (df["o_pct"] >= 0.195)
    df["sellable_strict"] = df["sellable_close"] & (~df["is_dt"])
    df["clv"] = np.where(df["ah"] > df["al"], (df["ac"] - df["al"]) / (df["ah"] - df["al"]), 0.5)
    s_zt = df["is_zt"].astype(int); s_sh = g["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    df["ret3"] = df["ac"] / g["ac"].shift(3) - 1.0
    est_sh = np.where(df["oshare"].fillna(0) > 0, df["oshare"], np.where(df["turn"] > 0, df["volume"] / df["turn"], np.nan))
    df["mcap"] = est_sh * df["close"] / 1e8
    df["zt_cnt_60d"] = g["is_zt"].transform(lambda s: s.rolling(60, min_periods=1).sum())

    t10 = json.load(open(f"{PART2_DIR}/pit_top10_20cm_summary.json", encoding="utf-8"))
    lock_arr = np.full(len(df), np.nan)
    for c6, idx_arr in g.groups.items():
        recs = [x for x in t10.get(c6, []) if x[0] <= CUT_DT]
        if not recs: continue
        dts = df.loc[idx_arr, "dt"].values; l_vals = np.full(len(dts), np.nan)
        for j, d in enumerate(dts):
            best_ed, best_l = "", np.nan
            for nd, ed, l10, _ in recs:
                if nd < d and ed >= best_ed: best_ed, best_l = ed, l10
            l_vals[j] = best_l
        lock_arr[idx_arr] = l_vals
    lock_fill = np.where(np.isnan(lock_arr), 40.0, np.clip(lock_arr, 0.0, 95.0))
    df["real_free_mcap"] = df["mcap"] * (1.0 - lock_fill / 100.0)

    idx_json = json.load(open(f"{BASE}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sh300_t = {k: float(v) for k, v in idx_json.get("sh000300", {}).items() if k <= CUT_DT}
    sz_t = {k: float(v) for k, v in idx_json.get("sz399107", {}).items() if k <= CUT_DT}

    con_z = sqlite3.connect(f"file:{BASE}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    zt_tape, st_events = {}, defaultdict(list)
    for td, sc, nm, sa in con_z.execute(
        "SELECT trade_date, sec_code, sec_name, seal_amount FROM zt_micro_tape WHERE trade_date <= ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')", (CUT_DT,)
    ):
        c6 = str(sc).zfill(6); zt_tape[(str(td), c6)] = float(sa or 0.0); s = str(nm or "").strip()
        if s: st_events[c6].append((f"{td} 15:00:00", 1 if ("ST" in s or "退" in s) else 0))
    con_z.close()

    lhb = pd.read_parquet(f"{BASE}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet")
    lhb = lhb[(lhb["date"] <= CUT_DT) & lhb["stock_code"].str.startswith(("30", "688", "689"))].copy().sort_values(["date", "stock_code", "is_three"])
    lhb_map = {}
    for (dt, sc, is3), grp in lhb.groupby(["date", "stock_code", "is_three"], sort=False):
        if is3 == 1 and (dt, sc) in lhb_map: continue
        lhb_map[(dt, sc)] = float(grp[grp["dept_code"] == "0"]["NET"].sum()) / 1e4

    for k in range(1, 12):
        df[f"f{k}_dt"] = g["dt"].shift(-k).fillna("")
        df[f"f{k}_ao"] = g["ao"].shift(-k); df[f"f{k}_ah"] = g["ah"].shift(-k)
        df[f"f{k}_al"] = g["al"].shift(-k); df[f"f{k}_ac"] = g["ac"].shift(-k)
        df[f"f{k}_o_pct"] = g["o_pct"].shift(-k)
        df[f"f{k}_buyable"] = g["buyable_open"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_sellable"] = g["sellable_close"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_sellable_strict"] = g["sellable_strict"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_is_dt"] = g["is_dt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_open_is_dt"] = g["open_is_dt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_zt"] = g["is_zt"].shift(-k).fillna(False).astype(bool)
        df[f"f{k}_zt_px_adj"] = g["zt_px_adj"].shift(-k)
    df["f1_abn_ret"] = g["abn_ret"].shift(-1).fillna(False).astype(bool)
    df["f1_clv"] = g["clv"].shift(-1)
    df["f1_body"] = np.where(df["f1_ao"] > 0, df["f1_ac"] / df["f1_ao"] - 1.0, np.nan)

    df = df[df["dt"] >= "2021-01-04"].copy().reset_index(drop=True)
    ew20_dts = sorted(df["dt"].unique())
    idx_s = pd.Series([sz_t.get(d, sh300_t.get(d, np.nan)) for d in ew20_dts], index=ew20_dts)
    df["dist_3d30"] = 0.30 - (df["ret3"] - df["dt"].map(idx_s.pct_change(3).to_dict()).fillna(0.0))
    df["mkt10_zt_cnt"] = df["dt"].map(mkt10_zt).fillna(0).astype(int)
    df["f1_mkt10_dt_cnt"] = df["f1_dt"].map(mkt10_dt).fillna(0).astype(int)
    mkt20_ozt = df.groupby("dt")["open_is_zt"].sum().to_dict()
    df["f1_mkt20_0925_zt"] = df["f1_dt"].map(mkt20_ozt).fillna(0).astype(int)

    all_20_set = set(df["c6"].unique())
    cand = df[df["tradable"] & (df["close"] >= 2.0) & df["is_zt"] & (df["streak"] == 1) & (~df["is_yizi_zt"])
              & (df["amount"] >= 1e8) & df["f1_buyable"] & (~df["f1_abn_ret"]) & df["f1_o_pct"].between(-0.10, -0.030)].copy().reset_index(drop=True)
    c6_set = set(cand["c6"].unique())
    tox_m, reg_m = defaultdict(list), defaultdict(list)
    con_n = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, ti, ts in con_n.execute("SELECT sec_code, title, pub_datetime_cst FROM notices WHERE pub_datetime_cst <= ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')", (CUT_TS,)):
        c6, ts_s, t_s = str(sc).zfill(6), str(ts)[:19], str(ti or "")
        if c6 in all_20_set:
            if ST_REV_RE.search(t_s) and "不" not in t_s[:10]: st_events[c6].append((ts_s, 0))
            elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s): st_events[c6].append((ts_s, 1))
        if c6 in c6_set:
            if TOX_RE.search(t_s): tox_m[c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg_m[c6].append(ts_s)
    con_n.close()
    rt = pd.read_parquet(f"{BASE}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    for r in rt[(rt["pub_datetime_cst"].astype(str) <= CUT_TS) & rt["c6"].isin(all_20_set)].itertuples(index=False):
        t_s, ts_s = str(r.title or ""), str(r.pub_datetime_cst)[:19]
        if ST_REV_RE.search(t_s): st_events[r.c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s): st_events[r.c6].append((ts_s, 1))
        if r.c6 in c6_set:
            if TOX_RE.search(t_s): tox_m[r.c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg_m[r.c6].append(ts_s)
    for zf in glob.glob(f"{BASE}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6, d_z = str(it[0]).zfill(6), str(it[2])[:10]
            if c6 in c6_set and d_z <= CUT_DT: reg_m[c6].append(d_z + " 08:00:00")
    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_events.items()}
    df_st_mask = np.array([is_st_at(st_tl, r.c6, f"{r.dt} 15:00:00") for r in df.itertuples(index=False)], dtype=int)
    mkt20_zt_clean = df[df["is_zt"] & (df_st_mask == 0)].groupby("dt").size().to_dict()
    mkt20_dt_clean = df[df["is_dt"] & (df_st_mask == 0)].groupby("dt").size().to_dict()
    cand["mkt20_zt_cnt"] = cand["dt"].map(mkt20_zt_clean).fillna(0).astype(int)
    cand["f1_mkt20_dt_cnt"] = cand["f1_dt"].map(mkt20_dt_clean).fillna(0).astype(int)
    for m in (tox_m, reg_m):
        for k in list(m.keys()): m[k] = sorted(set(m[k]))

    keep, zt_sr, inst_n, f1_inst_a = np.zeros(len(cand), dtype=bool), [], [], []
    for i, r in enumerate(cand.itertuples(index=False)):
        c6, dt, f1dt = r.c6, r.dt, r.f1_dt or r.dt
        if f1dt > CUT_DT or r.f2_dt == "" or r.f2_dt > CUT_DT:
            zt_sr.append(0.0); inst_n.append(0.0); f1_inst_a.append(0.0); continue
        t1c = f"{f1dt} 09:00:00"
        keep[i] = (is_st_at(st_tl, c6, f"{dt} 15:00:00") == 0 and is_st_at(st_tl, c6, t1c) == 0
                   and cnt_ts_win(tox_m.get(c6), f"{shift_cal(dt,-90)} 00:00:00", t1c) == 0
                   and cnt_ts_win(reg_m.get(c6), f"{shift_cal(dt,-10)} 00:00:00", t1c) == 0 and r.mkt20_zt_cnt < 16)
        zt_sr.append(zt_tape.get((dt, c6), 0.0) / r.amount if r.amount > 0 else 0.0)
        inst_n.append(lhb_map.get((dt, c6), 0.0)); f1_inst_a.append(lhb_map.get((f1dt, c6), 0.0))

    cand["zt_seal_ratio"] = zt_sr; cand["lhb_inst_net"] = inst_n; cand["f1_lhb_inst_net"] = f1_inst_a
    cand["f1_weekday"] = pd.to_datetime(cand["f1_dt"]).dt.dayofweek.fillna(-1).astype(int)
    cand["name"] = cand["c6"]
    sub_tr = cand[keep].copy().reset_index(drop=True)
    sub_tr["score"] = compute_scorecard_v11(sub_tr)[0].values

    res = {}
    for tier_lbl, th, full_df in [("A_76", 76.0, slot_A_full), ("S_82", 82.0, slot_S_full)]:
        tr_t = sim_v11_exit(sub_tr[sub_tr["score"] >= th], V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
        s1_t, _, _ = _sim_k_slots(tr_t, 1)
        t24 = s1_t[s1_t["exit_date"] <= CUT_DT].sort_values(["buy_date", "c6"]).reset_index(drop=True)
        f24 = full_df[full_df["exit_date"] <= CUT_DT].sort_values(["buy_date", "c6"]).reset_index(drop=True)
        assert len(t24) == len(f24) and (t24["buy_date"] == f24["buy_date"]).all() and (t24["exit_date"] == f24["exit_date"]).all()
        max_sc_diff = float(np.max(np.abs(t24["score"].to_numpy() - f24["score"].to_numpy())))
        max_ret_diff = float(np.max(np.abs(t24["net_ret_eval"].to_numpy() - f24["net_ret_eval"].to_numpy())))
        assert max_sc_diff == 0.0 and max_ret_diff < 1e-12
        res[tier_lbl] = {"trades_2021_2024": int(len(t24)), "max_score_diff": max_sc_diff, "max_ret_diff": round(max_ret_diff, 15)}
    res["elapsed_sec"] = round(time.time() - t0, 2)
    return res
