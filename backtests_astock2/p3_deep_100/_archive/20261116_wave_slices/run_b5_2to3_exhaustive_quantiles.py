#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_b5_2to3_exhaustive_quantiles.py — 二进三全维度无死角分箱与「题材×筹码×情绪」交互普查师 B5

职责：
1. 加载 cand_2to3_enriched.parquet（清洁 10cm 主板非 ST 非一字可买池 5,930 笔）+ code_bars_5y.pkl + 全部本地 5m 库。
2. 使用 B4 验证的二进三最优出场【混合F30】：
   - Day3 未封三板：按 reb2 规则出（次日高开>=+2%竞价走，否则盘中冲>=+2%走，否则收盘走）
   - Day3 封死三板：Day4 起 100% 无缝切《三进四 V3.4》（13:45 峰值>=+8.5%回落<=+5.0%护利 + 真阳免死1次）
   分别计算两套买法下的真实净收益：
   - ret_auc_f30：09:25 竞价买 + 混合F30出场
   - ret_ign_f30：max(open*1.012, pre_c*1.065) 11:30前点火买 + 混合F30出场
3. 任务A：对表中全部 92 个严格 09:25 PIT 特征列（严禁包含 h_pct/l_pct/pct/is_zt_today/touch_zt_today/
   touch_dt_today/net_ret/exit_dt/sealed_3b 等未来列）做五分位 Q1-Q5 与布尔单变量扫描，输出 Q1-Q5 均值、
   Q5-Q1 差、2022-2023 多空差、2024-2026 多空差、双期是否同向、5 年逐年同向数。
4. 任务B：32 组「选真龙」核心物理交互项扫描，调用 eval_factor_slice 输出全套指标。

铁律：
- 零 yfinance (D12)；
- 所有 SQLite 使用 file:...?mode=ro (uri=True)；
- 严禁修改 portfolio_state.json；
- 只写专属输出文件。
"""
import os
import sys
import json
import time
import pickle
import sqlite3
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
AST2 = f"{SIM_DIR}/backtests_astock2"
MAT_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
P23_DIR = f"{AST2}/p2_2to3"
OUT_DIR = f"{AST2}/p3_deep_100"

for p in (AST2, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from common_eval_harness import eval_factor_slice, CSI_BENCH, FEE
from core_3to4_5m_engine import sim_exit_5m

OUT_QUANTILES_CSV = f"{OUT_DIR}/b5_2to3_all_cols_quantiles.csv"
OUT_INTERACT_CSV = f"{OUT_DIR}/b5_2to3_dragon_interactions.csv"
OUT_SUMMARY_JSON = f"{OUT_DIR}/b5_summary.json"

EXCLUDE_FUTURE_COLS = {
    "h_pct", "l_pct", "pct",
    "is_zt_today", "touch_zt_today", "touch_dt_today",
    "net_ret", "exit_dt", "sealed_3b",
}
EXCLUDE_META_COLS = {
    "code", "name", "sig_date", "buy_date", "year",
    "plate", "r_short", "csrc_ind",
}


def load_all_local_5m(needed_codes: set) -> dict:
    """加载全部本地 5 分钟 K 线缓存（3 个 parquet + 2 个只读 SQLite db）。"""
    bars = {}
    for pq in [
        f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet",
        f"{AST2}/data_5y/cand_3to4_5m_bars.parquet",
        f"{AST2}/p2_4to5/cand_4to5_5m_bars.parquet",
    ]:
        if not os.path.exists(pq):
            continue
        d5 = pd.read_parquet(
            pq, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]
        )
        d5["c6"] = d5["c6"].astype(str).str.zfill(6)
        d5 = d5[d5["c6"].isin(needed_codes)].sort_values(["c6", "date", "hhmm_int"])
        for (c, dt_s), g in d5.groupby(["c6", "date"], sort=False):
            key = (c, str(dt_s)[:10])
            if key not in bars:
                bars[key] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    db_pit = f"{AST2}/data_5y/firstboard_5m_5y_pit.db"
    if os.path.exists(db_pit):
        con = sqlite3.connect(f"file:{db_pit}?mode=ro", uri=True)
        q_codes = sorted(needed_codes)
        for i in range(0, len(q_codes), 400):
            sub_c = q_codes[i:i + 400]
            qm = ",".join(["?"] * len(sub_c))
            sql = (
                "SELECT sec_code, trade_date, "
                "CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INT) AS hhmm_int, "
                "open, high, low, close, volume, amount "
                f"FROM firstboard_5m_kline WHERE sec_code IN ({qm})"
            )
            dfb = pd.read_sql_query(sql, con, params=sub_c)
            if not dfb.empty:
                dfb["c6"] = dfb["sec_code"].astype(str).str.zfill(6)
                dfb["dt"] = dfb["trade_date"].astype(str).str[:10]
                dfb.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
                for (c, dt_s), g in dfb.groupby(["c6", "dt"], sort=False):
                    if (c, dt_s) not in bars:
                        bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        con.close()

    db_old = f"{SIM_DIR}/data/firstboard_5m_5y_pit.db"
    if os.path.exists(db_old):
        con = sqlite3.connect(f"file:{db_old}?mode=ro", uri=True)
        q_codes = sorted(needed_codes)
        for i in range(0, len(q_codes), 400):
            sub_c = q_codes[i:i + 400]
            qm = ",".join(["?"] * len(sub_c))
            sql = (
                "SELECT sec_code, substr(bar_time,1,10) AS dt, "
                "CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INT) AS hhmm_int, "
                "open, high, low, close, volume, amount "
                f"FROM firstboard_5m_bars WHERE sec_code IN ({qm})"
            )
            dfb = pd.read_sql_query(sql, con, params=sub_c)
            if not dfb.empty:
                dfb["c6"] = dfb["sec_code"].astype(str).str.zfill(6)
                dfb.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
                for (c, dt_s), g in dfb.groupby(["c6", "dt"], sort=False):
                    if (c, dt_s) not in bars:
                        bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        con.close()
    return bars


def sim_buy_dyn65_12_1130(c6: str, bd: str, cb: dict, pos: int, bars_5m_map: dict):
    """max(open*1.012, pre_c*1.065) 11:30前点火买（5m优先，缺5m按日线兜底）。"""
    op = float(cb["open"][pos])
    pc = float(cb["pre_c"][pos])
    hi = float(cb["high"][pos])
    zt = float(cb["zt_px"][pos])
    if op >= zt - 0.005:
        return None, None
    trig = max(pc * 1.065, op * 1.012)
    if trig >= zt - 0.005:
        return None, None
    if op >= trig:
        return op, 925
    arr = bars_5m_map.get((c6, bd))
    if arr is not None and len(arr) > 0:
        for row in arr:
            hhmm = int(row[0])
            if hhmm > 1130:
                break
            bo, bh, bl = float(row[1]), float(row[2]), float(row[3])
            if bl >= zt - 0.005:
                continue
            if bh >= trig:
                fill_px = max(bo, trig)
                if fill_px < zt - 0.005:
                    return float(fill_px), hhmm
        return None, None
    if hi >= trig:
        return float(max(op, trig)), 1000
    return None, None


def simulate_hybrid_f30_returns(pool: pd.DataFrame, cb_map: dict, bars_5m: dict) -> pd.DataFrame:
    """
    在清洁可买池上精确计算：
    - ret_auc_f30 / exit_auc_f30: 09:25 open + 混合F30
    - ret_ign_f30 / exit_ign_f30: max(open*1.012, pre_c*1.065) 11:30前 + 混合F30
    注：同一股票同一天买法相同与否，出场轨迹仅取决于 Day3 是否封板及 Day4+ 5m 走势，只需模拟一次 sim_exit_5m。
    """
    ret_auc, ex_auc = [], []
    ret_ign, ex_ign = [], []
    sealed_3b_sim = []

    for r in pool.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None:
            ret_auc.append(np.nan); ex_auc.append("")
            ret_ign.append(np.nan); ex_ign.append("")
            sealed_3b_sim.append(False)
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1:
            ret_auc.append(np.nan); ex_auc.append("")
            ret_ign.append(np.nan); ex_ign.append("")
            sealed_3b_sim.append(False)
            continue

        # 混合F30出场：Day3未封用reb2，Day3封死三板则Day4起100%切《三进四V3.4》pm1345+真阳免死1次
        ex_dt, spx, adjs, _, _ = sim_exit_5m(
            c6, cb, pos, bars_5m, exit_mode="pm1345_5m", day5_unsealed_mode="reb2", use_yang_imm=True
        )
        adj_buy = float(cb["adjf"][pos])
        op = float(cb["open"][pos])
        zt = float(cb["zt_px"][pos])
        sealed_3b_sim.append(bool(cb["is_zt"][pos]))

        if op >= zt - 0.005:
            ret_auc.append(np.nan); ex_auc.append("")
        else:
            nr_a = (spx * adjs) / (op * adj_buy) * (1.0 - FEE) - 1.0
            ret_auc.append(float(nr_a))
            ex_auc.append(str(ex_dt))

        bpx_i, _ = sim_buy_dyn65_12_1130(c6, bd, cb, pos, bars_5m)
        if bpx_i is None:
            ret_ign.append(np.nan); ex_ign.append("")
        else:
            nr_i = (spx * adjs) / (bpx_i * adj_buy) * (1.0 - FEE) - 1.0
            ret_ign.append(float(nr_i))
            ex_ign.append(str(ex_dt))

    out = pool.copy()
    out["ret_auc_f30"] = ret_auc
    out["exit_auc_f30"] = ex_auc
    out["ret_ign_f30"] = ret_ign
    out["exit_ign_f30"] = ex_ign
    out["sealed_3b_sim"] = sealed_3b_sim
    return out


def parse_seal_time_to_min(series: pd.Series) -> pd.Series:
    """将 HH:MM:SS 转为距 09:30 的分钟数（09:25 -> -5.0, 99:99:99 -> NaN）。"""
    vals = []
    for v in series:
        if not isinstance(v, str) or v == "99:99:99" or ":" not in v:
            vals.append(np.nan)
        else:
            try:
                hh, mm, ss = map(int, v.split(":"))
                vals.append((hh * 60 + mm + ss / 60.0) - (9 * 60 + 30))
            except Exception:
                vals.append(np.nan)
    return pd.Series(vals, index=series.index, dtype=float)


def assign_q1_to_q5(s: pd.Series):
    """
    严格无随机拆平的五分位/二值映射，返回 (bin_series_1_to_5, bin_type, q1_desc, q5_desc)。
    """
    valid = s.dropna()
    nu = int(valid.nunique())
    if nu <= 1:
        return pd.Series(np.nan, index=s.index), "constant", "const", "const"

    if s.dtype == bool or nu == 2:
        uvals = sorted(valid.unique())
        lo, hi = uvals[0], uvals[-1]
        out = pd.Series(np.nan, index=s.index, dtype=float)
        out[s == lo] = 1.0
        out[s == hi] = 5.0
        return out, "bool_or_binary", str(lo), str(hi)

    # Numeric with >= 3 unique values
    s_num = pd.to_numeric(s, errors="coerce")
    q_res = pd.qcut(s_num.dropna(), 5, duplicates="drop")
    cats = q_res.cat.categories
    nb = len(cats)
    if nb == 5:
        codes = q_res.cat.codes + 1
        out = pd.Series(np.nan, index=s.index, dtype=float)
        out.loc[codes.index] = codes.astype(float)
        return out, "quintile_5", f"[{cats[0].left:.4g},{cats[0].right:.4g}]", f"({cats[4].left:.4g},{cats[4].right:.4g}]"
    elif nb in (2, 3, 4):
        slot_map = {2: [1, 5], 3: [1, 3, 5], 4: [1, 2, 4, 5]}[nb]
        mapped = q_res.cat.codes.map(lambda c: float(slot_map[c]) if c >= 0 else np.nan)
        out = pd.Series(np.nan, index=s.index, dtype=float)
        out.loc[mapped.index] = mapped
        return out, f"quantile_{nb}", f"[{cats[0].left:.4g},{cats[0].right:.4g}]", f"({cats[-1].left:.4g},{cats[-1].right:.4g}]"
    else:
        # >80% concentrated at mode (e.g. 0 or 1): split mode vs tail
        mode_val = float(s_num.dropna().mode().iloc[0])
        out = pd.Series(np.nan, index=s.index, dtype=float)
        if mode_val <= float(s_num.min()) + 1e-12:
            out[s_num <= mode_val + 1e-12] = 1.0
            out[s_num > mode_val + 1e-12] = 5.0
            return out, "mode_vs_tail", f"<={mode_val:.4g}", f">{mode_val:.4g}"
        else:
            out[s_num < mode_val - 1e-12] = 1.0
            out[s_num > mode_val + 1e-12] = 5.0
            return out, "below_vs_above_mode", f"<{mode_val:.4g}", f">{mode_val:.4g}"


def eval_single_col_quantiles(df: pd.DataFrame, col_name: str, bin_s: pd.Series, ret_col: str, prefix: str) -> dict:
    """对单列按 bin_s (1..5) 计算 Q1..Q5 均值、Q5-Q1 差、双期同向、5年逐年同向数与单调度。"""
    sub = df[[ret_col, "buy_date"]].copy()
    sub["_bin"] = bin_s
    sub = sub[sub[ret_col].notna() & sub["_bin"].notna()].copy()
    sub["_yr"] = sub["buy_date"].astype(str).str[:4]

    out = {f"{prefix}_n_valid": int(len(sub))}
    q_means = {}
    for q in (1, 2, 3, 4, 5):
        m = sub.loc[sub["_bin"] == q, ret_col]
        out[f"{prefix}_q{q}_n"] = int(len(m))
        if len(m) > 0:
            val = float(m.mean() * 100.0)
            out[f"{prefix}_q{q}_pct"] = round(val, 2)
            q_means[q] = val
        else:
            out[f"{prefix}_q{q}_pct"] = np.nan

    if 1 in q_means and 5 in q_means:
        diff_all = q_means[5] - q_means[1]
        out[f"{prefix}_q5_q1_diff_pct"] = round(diff_all, 2)
    else:
        diff_all = np.nan
        out[f"{prefix}_q5_q1_diff_pct"] = np.nan

    # Early 2022-2023 vs Recent 2024-2026 long-short diff (Q5 - Q1)
    e_sub = sub[sub["buy_date"] < "2024-01-01"]
    r_sub = sub[sub["buy_date"] >= "2024-01-01"]

    def _ls_diff(d):
        g1 = d.loc[d["_bin"] == 1, ret_col]
        g5 = d.loc[d["_bin"] == 5, ret_col]
        if len(g1) >= 3 and len(g5) >= 3:
            return float((g5.mean() - g1.mean()) * 100.0)
        return np.nan

    d_early = _ls_diff(e_sub)
    d_recent = _ls_diff(r_sub)
    out[f"{prefix}_early_22_23_diff_pct"] = round(d_early, 2) if pd.notna(d_early) else np.nan
    out[f"{prefix}_recent_24_26_diff_pct"] = round(d_recent, 2) if pd.notna(d_recent) else np.nan
    out[f"{prefix}_dual_same_sign"] = bool(
        pd.notna(d_early) and pd.notna(d_recent) and (d_early * d_recent > 0)
    )

    # 5-year annual same-sign count (vs overall Q5-Q1 sign)
    yr_same = 0
    yr_tested = 0
    if pd.notna(diff_all) and abs(diff_all) > 1e-9:
        for yr in ("2022", "2023", "2024", "2025", "2026"):
            yd = sub[sub["_yr"] == yr]
            g1 = yd.loc[yd["_bin"] == 1, ret_col]
            g5 = yd.loc[yd["_bin"] == 5, ret_col]
            if len(g1) >= 1 and len(g5) >= 1:
                yr_tested += 1
                dy = float((g5.mean() - g1.mean()) * 100.0)
                if dy * diff_all > 0:
                    yr_same += 1
    out[f"{prefix}_yr_same_sign_cnt"] = int(yr_same)
    out[f"{prefix}_yr_tested_cnt"] = int(yr_tested)

    # Monotonicity check across populated bins
    pts = [(q, q_means[q]) for q in (1, 2, 3, 4, 5) if q in q_means]
    if len(pts) >= 3:
        qs = np.array([p[0] for p in pts], dtype=float)
        vs = np.array([p[1] for p in pts], dtype=float)
        corr = float(pd.Series(vs).corr(pd.Series(qs), method="spearman"))
        diffs = np.diff(vs)
        strict_mono = bool(np.all(diffs > 0) or np.all(diffs < 0))
        out[f"{prefix}_mono_spearman"] = round(corr, 3) if pd.notna(corr) else np.nan
        out[f"{prefix}_strict_mono"] = strict_mono
    else:
        out[f"{prefix}_mono_spearman"] = np.nan
        out[f"{prefix}_strict_mono"] = False

    return out


def build_cross_board_features(df_clean: pd.DataFrame, cb_map: dict) -> pd.DataFrame:
    """
    在全量 10cm 主板非 ST 原始表（cand_2to3, cand_0to1_firstboard, cand_3to4, cand_high_dragon）
    上精确构造无未来函数的同题材排位、一字阶梯、最高身位大哥压制与筹码比例特征，并映射到 df_clean。
    """
    df = df_clean.copy()

    def _is_10cm_nonst(d: pd.DataFrame) -> pd.Series:
        c = d["code"].astype(str).str.zfill(6)
        return c.str.startswith(("00", "60")) & (~d["name"].astype(str).str.upper().str.contains("ST"))

    # 1. 全量 10cm 二板（含一字不可买），算板块二板一字数与总数
    d23_raw = pd.read_parquet(
        f"{MAT_DIR}/cand_2to3.parquet",
        columns=["code", "name", "sig_date", "buy_date", "gap_days", "open_pct", "is_yizi_open", "plate"],
    )
    d23_10 = d23_raw[_is_10cm_nonst(d23_raw)].copy()
    d23_named = d23_10[d23_10["plate"].notna() & (d23_10["plate"] != "") & (d23_10["plate"] != "其他")]
    p_2b_yz_map = d23_named[d23_named["is_yizi_open"]].groupby(["buy_date", "plate"]).size().to_dict()
    p_2b_tot_map = d23_named.groupby(["buy_date", "plate"]).size().to_dict()

    df["plate_2b_yizi_cnt"] = [
        p_2b_yz_map.get((b, p), 0) if (p and p != "其他") else 0
        for b, p in zip(df["buy_date"], df["plate"])
    ]
    df["plate_2b_tot_cnt"] = [
        p_2b_tot_map.get((b, p), 1) if (p and p != "其他") else 1
        for b, p in zip(df["buy_date"], df["plate"])
    ]

    # 2. 同题材可买二板竞价排位（"其他"不互组）
    named_mask = df["plate"].notna() & (df["plate"] != "") & (df["plate"] != "其他")
    df["plate_2b_cnt"] = 1
    df["2b_plate_buy_rk"] = 1
    grp_named = df[named_mask].groupby(["buy_date", "plate"])
    df.loc[named_mask, "plate_2b_cnt"] = grp_named["code"].transform("count").astype(int)
    df.loc[named_mask, "2b_plate_buy_rk"] = grp_named["open_pct"].rank(ascending=False, method="min").astype(int)
    df["mkt_2b_open_rk"] = df.groupby("buy_date")["open_pct"].rank(ascending=False, method="min").astype(int)

    # 精确断层领先第2名幅度
    p_sorted = {}
    for (bd, pl), g in df[named_mask].groupby(["buy_date", "plate"], sort=False):
        p_sorted[(bd, pl)] = sorted(g["open_pct"].tolist(), reverse=True)
    lead_vals = []
    for bd, pl, pcnt, rk in zip(df["buy_date"], df["plate"], df["plate_2b_cnt"], df["2b_plate_buy_rk"]):
        if pl != "其他" and pcnt >= 2 and rk == 1:
            ops = p_sorted.get((bd, pl), [])
            lead_vals.append(float(ops[0] - ops[1]) if len(ops) >= 2 else 0.0)
        else:
            lead_vals.append(0.0)
    df["open_lead_plate_rk2_clean"] = lead_vals

    # 3. Day2 (sig_date) 同题材是否有 >=3板高标大哥压制
    dhd = pd.read_parquet(f"{MAT_DIR}/cand_high_dragon.parquet", columns=["code", "name", "sig_date", "prev_streak", "plate"])
    d34 = pd.read_parquet(f"{MAT_DIR}/cand_3to4.parquet", columns=["code", "name", "sig_date", "prev_streak", "plate"])
    d_ge3 = pd.concat([dhd, d34], ignore_index=True)
    d_ge3 = d_ge3[_is_10cm_nonst(d_ge3) & (d_ge3["prev_streak"] >= 3)]
    d_ge3_named = d_ge3[d_ge3["plate"].notna() & (d_ge3["plate"] != "") & (d_ge3["plate"] != "其他")]
    big_bro_pairs = set(zip(d_ge3_named["sig_date"], d_ge3_named["plate"]))
    df["has_plate_3b_plus_big_bro"] = [
        ((s, p) in big_bro_pairs) if (p and p != "其他") else False
        for s, p in zip(df["sig_date"], df["plate"])
    ]
    df["is_plate_highest_dragon"] = ~df["has_plate_3b_plus_big_bro"]

    # 4. 派生筹码与盘口因子
    df["chip_dual45"] = (df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0)
    df["seal_amt_ratio"] = np.where(df["prev_amt"] > 0, df["seal_amount"] / df["prev_amt"], 0.0)
    b_ts = pd.to_datetime(df["buy_date"])
    df["buy_month"] = b_ts.dt.month
    df["is_jan_may_blackout"] = df["buy_month"].isin([1, 5])
    return df


def define_32_dragon_interactions(df: pd.DataFrame) -> list:
    """定义 32 组「选真龙」题材×筹码×情绪×位置×量能多因子物理交互项。"""
    named = df["plate"].notna() & (df["plate"] != "") & (df["plate"] != "其他")
    hi_dragon = df["is_plate_highest_dragon"]
    hi_dragon_named = named & hi_dragon
    uniq_2b_named = named & (df["plate_2b_cnt"] == 1)
    uniq_2b_all = df["plate_2b_cnt"] == 1
    rk1 = df["2b_plate_buy_rk"] == 1
    chip45 = df["chip_dual45"]
    mild_open = df["open_pct"].between(0.0, 0.055)
    pit_gold = (df["dd20"] <= 0.85) | (df["pos20"] <= 0.45)

    specs = [
        # I. 最高身位无压制 × 超跌黄金坑 / N型龙回头
        ("G01_无3板压制最高身位二板 × 超跌黄金坑(dd20<=0.85|pos20<=0.45)", hi_dragon & pit_gold),
        ("G02_有名题材无3板压制最高身位二板 × 超跌黄金坑(dd20<=0.85|pos20<=0.45)", hi_dragon_named & pit_gold),
        ("G03_无3板压制最高身位二板 × 深回撤(dd20<=0.85)", hi_dragon & (df["dd20"] <= 0.85)),
        ("G04_无3板压制最高身位二板 × 20日低位箱体(pos20<=0.45)", hi_dragon & (df["pos20"] <= 0.45)),
        ("G05_板块最高身位二板 × N型龙回头(zt_cnt_pre20>=1&dd20<=0.86)", hi_dragon & (df["zt_cnt_pre20"] >= 1) & (df["dd20"] <= 0.86)),
        ("G06_板块最高身位二板 × 真前妖N型回头(zt_cnt_pre20>=3&dd20<=0.86)", hi_dragon & (df["zt_cnt_pre20"] >= 3) & (df["dd20"] <= 0.86)),

        # II. 板块唯一二板活口 × 爆量分歧换手 / 空间破局窗 / 双45筹码门
        ("G07_板块唯一二板活口(去其他) × 二板爆量分歧换手(to_ratio>2.0)", uniq_2b_named & (df["to_ratio_d2_d1"] > 2.0)),
        ("G08_板块唯一二板(含其他) × 二板爆量分歧换手(to_ratio>2.0)", uniq_2b_all & (df["to_ratio_d2_d1"] > 2.0)),
        ("G09_双45筹码门 × 空间破局窗(3~4板) × 板块唯一二板(去其他)", chip45 & df["mkt_max_board_prev"].between(3, 4) & uniq_2b_named),
        ("G10_双45筹码门 × 空间破局窗(3~4板) × 板块唯一二板(去其他) × 温和竞价(0~5.5%)", chip45 & df["mkt_max_board_prev"].between(3, 4) & uniq_2b_named & mild_open),

        # III. 5日晋级率冰点破局真龙
        ("G11_5日晋级率冰点(<0.13) × 同题材二板第1名", (df["mkt_promo_1to2_5d"] < 0.13) & rk1),
        ("G12_5日晋级率冰点(<0.13) × 有名题材第1名 × 无3板压制最高身位", (df["mkt_promo_1to2_5d"] < 0.13) & named & rk1 & hi_dragon),
        ("G13_5日晋级率冰点(<0.13) × 同题材二板第1名 × 双45筹码门", (df["mkt_promo_1to2_5d"] < 0.13) & rk1 & chip45),

        # IV. 第一主线题材 × 同题材第1 × 温和竞价
        ("G14_第一主线(rk_theme==1&s_elo>=102) × 同题材二板第1 × 温和竞价(0~5.5%)", (df["rk_theme"] == 1) & (df["s_elo"] >= 102) & rk1 & mild_open),
        ("G15_第一主线(rk_theme==1&s_elo>=102) × 同题材二板第1 × 无3板压制", (df["rk_theme"] == 1) & (df["s_elo"] >= 102) & rk1 & hi_dragon),
        ("G16_第一主线(rk_theme==1&s_elo>=102) × 板块唯一二板 × 温和竞价(0~5.5%)", (df["rk_theme"] == 1) & (df["s_elo"] >= 102) & uniq_2b_named & mild_open),
        ("G17_主线前2(rk_theme<=2&s_elo>=102) × 同题材第1 × 断层领先>=1.5%", (df["rk_theme"] <= 2) & (df["s_elo"] >= 102) & rk1 & (df["open_lead_plate_rk2_clean"] >= 0.015)),

        # V. 伴生一字锁筹阶梯 × 排位 × 市值/筹码
        ("G18_同题材1只二板一字 × 本股换手第1 × 双45筹码门", (df["plate_2b_yizi_cnt"] == 1) & rk1 & chip45),
        ("G19_同题材1只二板一字 × 本股换手第1 × 温和竞价(0~5.5%)", (df["plate_2b_yizi_cnt"] == 1) & rk1 & mild_open),
        ("G20_90亿以上中大盘(mcap>90) × 同题材二板一字>=1 × 同题材第1", (df["mcap"] > 90.0) & (df["plate_2b_yizi_cnt"] >= 1) & rk1),
        ("G21_小盘甜点(15~45亿) × 板块唯一二板(去其他) × 双45筹码门", df["mcap"].between(15.0, 45.0) & uniq_2b_named & chip45),

        # VI. 60日干净突破第2通道 × 筹码 × 情绪/位置
        ("G22_60日干净突破(clean_brk60) × 双45筹码门 × 同题材二板第1", (df["clean_brk60"] == True) & chip45 & rk1),
        ("G23_60日干净突破(clean_brk60) × 无3板压制最高身位 × 温和竞价(0~5.5%)", (df["clean_brk60"] == True) & hi_dragon & mild_open),
        ("G24_60日深坑超跌(dd60<=0.82) × 板块唯一二板(去其他)", (df["dd60"] <= 0.82) & uniq_2b_named),

        # VII. 微观盘口封单强度 × 换手分歧 × 情绪周期
        ("G25_早盘换手回封(hard1030) × 紧度>=37 × 双45筹码门 × 温和竞价(0~5.5%)", (df["is_hard_open_1030"] == True) & (df["seal_tightness"] >= 37.0) & chip45 & mild_open),
        ("G26_封成比>=0.08 × 同题材二板第1 × 无3板压制最高身位", (df["seal_amt_ratio"] >= 0.08) & rk1 & hi_dragon),
        ("G27_爆量分歧(to_ratio>2.0) × 20日回撤(dd20<=0.86) × 同题材第1", (df["to_ratio_d2_d1"] > 2.0) & (df["dd20"] <= 0.86) & rk1),
        ("G28_温和放量(to_ratio 0.8~1.6) × 双45筹码门 × 主线前2(rk_theme<=2)", df["to_ratio_d2_d1"].between(0.8, 1.6) & chip45 & (df["rk_theme"] <= 2)),

        # VIII. 情绪周期与日历过滤叠加真龙
        ("G29_非1/5退潮月 × 舒适情绪(zt35~85&seal<=0.75) × 最高身位第1", (~df["is_jan_may_blackout"]) & df["mkt_zt_prev"].between(35, 85) & (df["mkt_seal_rate_prev"] <= 0.75) & hi_dragon_named & rk1),
        ("G30_低跌停安全窗(dt<=6) × 同题材首板高开>=2只 × 同题材第1", (df["mkt_dt_prev"] <= 6) & (df["plate_fb_ho_cnt"] >= 2) & rk1),
        ("G31_冰点恐慌环境(dt>=15|promo<0.13) × 最高身位唯一二板(去其他)", ((df["mkt_dt_prev"] >= 15) | (df["mkt_promo_1to2_5d"] < 0.13)) & hi_dragon_named & uniq_2b_named),
        ("G32_周一节后窗口(gap>=3) × 同题材二板第1 × 断层领先>=2.0%", (df["gap_days"] >= 3) & rk1 & (df["open_lead_plate_rk2_clean"] >= 0.020)),
    ]
    return specs


def main():
    t0 = time.time()
    print("[B5] Loading cand_2to3_enriched.parquet + code_bars_5y.pkl + 5m bars...")
    df_all = pd.read_parquet(f"{P23_DIR}/cand_2to3_enriched.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    # Clean 10cm non-ST non-yizi buyable pool (~5,930 rows)
    pool_raw = df_all[(~df_all["prev_is_yizi"]) & (df_all["buyable_open"])].copy().reset_index(drop=True)
    needed_codes = set(pool_raw["code"].astype(str).str.zfill(6))
    bars_5m = load_all_local_5m(needed_codes)
    print(f"[B5] Clean pool n={len(pool_raw)}, loaded {len(bars_5m):,} 5m blocks in {time.time()-t0:.1f}s")

    # Simulate ret_auc_f30 & ret_ign_f30 with Hybrid F30 exit
    t1 = time.time()
    pool = simulate_hybrid_f30_returns(pool_raw, cb_map, bars_5m)
    auc_valid = pool[pool["ret_auc_f30"].notna()].copy()
    ign_valid = pool[pool["ret_ign_f30"].notna()].copy()
    base_auc_mean = float(auc_valid["ret_auc_f30"].mean())
    base_ign_mean = float(ign_valid["ret_ign_f30"].mean())
    print(
        f"[B5] Hybrid F30 sim done in {time.time()-t1:.1f}s | "
        f"ret_auc_f30: n={len(auc_valid)}, avg={base_auc_mean*100:+.2f}% | "
        f"ret_ign_f30: n={len(ign_valid)}, avg={base_ign_mean*100:+.2f}%"
    )

    # =========================================================================
    # 任务A：全部 92 个严格 09:25 PIT 特征列五分位 Q1-Q5 与布尔单变量扫描
    # =========================================================================
    pit_cols = [c for c in df_all.columns if c not in EXCLUDE_FUTURE_COLS and c not in EXCLUDE_META_COLS]
    assert len(pit_cols) == 92, f"Expected 92 PIT cols, got {len(pit_cols)}"
    assert not (set(pit_cols) & EXCLUDE_FUTURE_COLS), "Future column leaked!"

    pool_q = pool.copy()
    pool_q["first_seal_time"] = parse_seal_time_to_min(pool_q["first_seal_time"])

    q_rows = []
    for col in pit_cols:
        bin_s, bin_type, q1_desc, q5_desc = assign_q1_to_q5(pool_q[col])
        rec = {
            "feature": col,
            "raw_dtype": str(df_all[col].dtype),
            "bin_type": bin_type,
            "n_unique": int(pool_q[col].nunique(dropna=True)),
            "q1_range": q1_desc,
            "q5_range": q5_desc,
        }
        rec.update(eval_single_col_quantiles(pool_q, col, bin_s, "ret_auc_f30", "auc"))
        rec.update(eval_single_col_quantiles(pool_q, col, bin_s, "ret_ign_f30", "ign"))
        q_rows.append(rec)

    q_df = pd.DataFrame(q_rows)
    q_df.to_csv(OUT_QUANTILES_CSV, index=False, encoding="utf-8-sig")
    print(f"[B5] Task A saved ({len(q_df)} cols) -> {OUT_QUANTILES_CSV}")

    # =========================================================================
    # 任务B：32 组「选真龙」核心物理交互项扫描
    # =========================================================================
    pool_b = build_cross_board_features(pool, cb_map)
    specs = define_32_dragon_interactions(pool_b)

    base_auc_eval = eval_factor_slice(auc_valid, ret_col="ret_auc_f30", exit_col="exit_auc_f30", rank_col="open_pct", base_mean=base_auc_mean)
    base_ign_eval = eval_factor_slice(ign_valid, ret_col="ret_ign_f30", exit_col="exit_ign_f30", rank_col="open_pct", base_mean=base_ign_mean)

    inter_rows = []
    for name, cond in specs:
        cond_s = pd.Series(cond, index=pool_b.index).fillna(False).astype(bool)
        sub_auc = pool_b[cond_s & pool_b["ret_auc_f30"].notna()]
        sub_ign = pool_b[cond_s & pool_b["ret_ign_f30"].notna()]

        ev_auc = eval_factor_slice(sub_auc, ret_col="ret_auc_f30", exit_col="exit_auc_f30", rank_col="open_pct", base_mean=base_auc_mean)
        ev_ign = eval_factor_slice(sub_ign, ret_col="ret_ign_f30", exit_col="exit_ign_f30", rank_col="open_pct", base_mean=base_ign_mean)

        rec = {
            "interaction_name": name,
            "hit_pool_n": int(cond_s.sum()),
            "hit_pool_pct": round(float(cond_s.mean() * 100.0), 2),
            "auc_dual_abs_pos": bool(ev_auc["early_22_23_avg"] > 0 and ev_auc["recent_24_26_avg"] > 0),
            "ign_dual_abs_pos": bool(ev_ign["early_22_23_avg"] > 0 and ev_ign["recent_24_26_avg"] > 0),
        }
        for k, v in ev_auc.items():
            rec[f"auc_{k}"] = v
        for k, v in ev_ign.items():
            rec[f"ign_{k}"] = v
        inter_rows.append(rec)

    inter_df = pd.DataFrame(inter_rows)
    inter_df.to_csv(OUT_INTERACT_CSV, index=False, encoding="utf-8-sig")
    print(f"[B5] Task B saved ({len(inter_df)} interactions) -> {OUT_INTERACT_CSV}")

    # =========================================================================
    # Summary JSON & Core Findings Printout
    # =========================================================================
    q_valid = q_df[q_df["bin_type"] != "constant"].copy()
    q_valid["auc_abs_diff"] = q_valid["auc_q5_q1_diff_pct"].abs()
    q_valid["ign_abs_diff"] = q_valid["ign_q5_q1_diff_pct"].abs()

    top_auc_q = q_valid[q_valid["auc_dual_same_sign"]].sort_values("auc_abs_diff", ascending=False).head(20)
    top_ign_q = q_valid[q_valid["ign_dual_same_sign"]].sort_values("ign_abs_diff", ascending=False).head(20)
    top_mono_5y = q_valid[
        (q_valid["auc_dual_same_sign"]) & (q_valid["auc_yr_same_sign_cnt"] >= 4)
    ].sort_values(["auc_yr_same_sign_cnt", "auc_abs_diff"], ascending=[False, False]).head(25)

    top_inter_auc = inter_df[inter_df["auc_n_raw"] >= 15].sort_values("auc_delta_vs_base", ascending=False).head(15)
    top_inter_ign = inter_df[inter_df["ign_n_raw"] >= 10].sort_values("ign_delta_vs_base", ascending=False).head(15)

    def _clean_records(df_in, cols):
        recs = []
        for _, row in df_in[cols].iterrows():
            d = {}
            for k, v in row.items():
                if pd.isna(v):
                    d[k] = None
                elif isinstance(v, (np.bool_, bool)):
                    d[k] = bool(v)
                elif isinstance(v, (np.integer, int)):
                    d[k] = int(v)
                elif isinstance(v, (np.floating, float)):
                    d[k] = float(v)
                else:
                    d[k] = str(v)
            recs.append(d)
        return recs

    q_cols_brief = [
        "feature", "bin_type", "q1_range", "q5_range",
        "auc_q1_pct", "auc_q2_pct", "auc_q3_pct", "auc_q4_pct", "auc_q5_pct",
        "auc_q5_q1_diff_pct", "auc_early_22_23_diff_pct", "auc_recent_24_26_diff_pct",
        "auc_dual_same_sign", "auc_yr_same_sign_cnt", "auc_mono_spearman",
        "ign_q1_pct", "ign_q5_pct", "ign_q5_q1_diff_pct", "ign_dual_same_sign", "ign_yr_same_sign_cnt",
    ]
    inter_cols_brief = [
        "interaction_name", "hit_pool_n", "auc_n_raw", "auc_wr_raw", "auc_payoff_raw",
        "auc_avg_ret", "auc_delta_vs_base", "auc_early_22_23_avg", "auc_recent_24_26_avg",
        "auc_dual_same_sign", "auc_dual_abs_pos", "auc_ss_n", "auc_ss_nav", "auc_ss_mdd",
        "auc_ss_ex_top3_nav", "auc_ss_net_excess_5y", "auc_eq_nav", "auc_ss_pos_years",
        "ign_n_raw", "ign_wr_raw", "ign_avg_ret", "ign_delta_vs_base", "ign_dual_same_sign",
        "ign_ss_n", "ign_ss_nav", "ign_ss_net_excess_5y", "ign_eq_nav", "ign_ss_pos_years",
    ]

    summary = {
        "meta": {
            "pool_total_n": int(len(pool)),
            "auc_valid_n": int(len(auc_valid)),
            "ign_valid_n": int(len(ign_valid)),
            "pit_feature_count": int(len(pit_cols)),
            "excluded_future_cols": sorted(EXCLUDE_FUTURE_COLS),
            "constant_cols": q_df[q_df["bin_type"] == "constant"]["feature"].tolist(),
            "pit_note": "headroom_100 in cand_2to3_enriched.parquet uses Day3 index close ratio (imap[bd]/imap[bd-k]) per builder_2to3_dataset.py; flagged for transparency.",
            "csi300_bench_pct": {k: round(v * 100, 2) for k, v in CSI_BENCH.items()},
            "exit_rule": "Hybrid F30 (Day3 unsealed -> reb2; Day3 sealed 3B -> Day4+ 3to4 V3.4 pm1345 + true-yang immunity x1)",
        },
        "baselines": {
            "ret_auc_f30": base_auc_eval,
            "ret_ign_f30": base_ign_eval,
        },
        "task_a_summary": {
            "total_cols_scanned": int(len(q_df)),
            "constant_cols_n": int((q_df["bin_type"] == "constant").sum()),
            "auc_dual_same_sign_n": int(q_valid["auc_dual_same_sign"].sum()),
            "ign_dual_same_sign_n": int(q_valid["ign_dual_same_sign"].sum()),
            "auc_dual_and_4plus_years_n": int(((q_valid["auc_dual_same_sign"]) & (q_valid["auc_yr_same_sign_cnt"] >= 4)).sum()),
            "top_auc_dual_same_sign": _clean_records(top_auc_q, q_cols_brief),
            "top_ign_dual_same_sign": _clean_records(top_ign_q, q_cols_brief),
            "robust_4plus_years_same_sign": _clean_records(top_mono_5y, q_cols_brief),
        },
        "task_b_summary": {
            "total_interactions": int(len(inter_df)),
            "top_auc_interactions": _clean_records(top_inter_auc, inter_cols_brief),
            "top_ign_interactions": _clean_records(top_inter_ign, inter_cols_brief),
            "all_interactions": _clean_records(inter_df, inter_cols_brief),
        },
    }

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[B5] Summary JSON saved -> {OUT_SUMMARY_JSON}")

    print("\n=== [Baseline Pools (Hybrid F30)] ===")
    print(f"  AUC 09:25 + F30 : n={base_auc_eval['n_raw']} WR={base_auc_eval['wr_raw']}% PO={base_auc_eval['payoff_raw']} avg={base_auc_eval['avg_ret']:+.2f}% (22-23:{base_auc_eval['early_22_23_avg']:+.2f}% / 24-26:{base_auc_eval['recent_24_26_avg']:+.2f}%)")
    print(f"  IGN 11:30 + F30 : n={base_ign_eval['n_raw']} WR={base_ign_eval['wr_raw']}% PO={base_ign_eval['payoff_raw']} avg={base_ign_eval['avg_ret']:+.2f}% (22-23:{base_ign_eval['early_22_23_avg']:+.2f}% / 24-26:{base_ign_eval['recent_24_26_avg']:+.2f}%)")

    print("\n=== [Task A Top 15 Robust Dual-Same-Sign & >=4/5 Years (ret_auc_f30)] ===")
    for r in summary["task_a_summary"]["robust_4plus_years_same_sign"][:15]:
        print(
            f"  {r['feature']:26s} [{r['bin_type']:12s}] | Q1={r['auc_q1_pct']:+5.2f}% -> Q5={r['auc_q5_pct']:+5.2f}% "
            f"| Q5-Q1={r['auc_q5_q1_diff_pct']:+5.2f}% (22-23:{r['auc_early_22_23_diff_pct']:+5.2f}% / 24-26:{r['auc_recent_24_26_diff_pct']:+5.2f}%) "
            f"| {r['auc_yr_same_sign_cnt']}/5yr | sp={r['auc_mono_spearman']}"
        )

    print("\n=== [Task B Top 15 Dragon Interactions (ret_auc_f30)] ===")
    for r in summary["task_b_summary"]["top_auc_interactions"]:
        print(
            f"  {r['interaction_name']:54s} | n={r['auc_n_raw']:3d} WR={r['auc_wr_raw']:4.1f}% PO={r['auc_payoff_raw']:4.2f} "
            f"avg={r['auc_avg_ret']:+5.2f}% d={r['auc_delta_vs_base']:+5.2f}% (22-23:{r['auc_early_22_23_avg']:+5.2f}%/24-26:{r['auc_recent_24_26_avg']:+5.2f}%) "
            f"| ss={r['auc_ss_n']:3d} NAV={r['auc_ss_nav']:5.2f}x ex3={r['auc_ss_ex_top3_nav']:4.2f}x exCSI={r['auc_ss_net_excess_5y']:+6.1f}% eq={r['auc_eq_nav']:5.2f}x {r['auc_ss_pos_years']}/5yr"
        )

    print("\n=== [Task B Top 10 Dragon Interactions (ret_ign_f30)] ===")
    for r in summary["task_b_summary"]["top_ign_interactions"][:10]:
        print(
            f"  {r['interaction_name']:54s} | n={r['ign_n_raw']:3d} WR={r['ign_wr_raw']:4.1f}% "
            f"avg={r['ign_avg_ret']:+5.2f}% d={r['ign_delta_vs_base']:+5.2f}% "
            f"| ss={r['ign_ss_n']:3d} NAV={r['ign_ss_nav']:5.2f}x exCSI={r['ign_ss_net_excess_5y']:+6.1f}% eq={r['ign_eq_nav']:5.2f}x {r['ign_ss_pos_years']}/5yr"
        )

    print(f"\n[B5 DONE] Total elapsed: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
