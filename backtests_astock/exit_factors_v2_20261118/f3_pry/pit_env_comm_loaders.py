#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
pit_env_comm_loaders.py
Strict PIT loaders for Xueqiu/Guba community posts, IR QA, KPL plates, zt_micro_tape,
daily market env, 09:25 rt_env, CSI300 index, and high-board rebound rates.
"""
import os, json, sqlite3, datetime
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
EVENT_BASKET_PLATES = {
    "并购重组", "股权转让", "资产注入", "国企改革", "央企改革",
    "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购",
    "增持", "次新股", "高送转", "参股新股"
}
NON_THEME = {"其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"}


def load_community_and_ir_pit(target_codes: set) -> tuple[dict, dict, dict]:
    """Load strictly sorted timestamps for Xueqiu, Guba, and IR QA per stock."""
    xq_sets = defaultdict(set)
    gb_sets = defaultdict(set)
    ph = ",".join(["?"] * len(target_codes))
    codes_s = sorted(target_codes)

    con_xg = sqlite3.connect(f"file:{SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, ts in con_xg.execute(
        f"SELECT symbol, created_time_str FROM xueqiu_posts WHERE symbol IN ({ph}) AND created_time_str >= '2021-10-01'",
        codes_s,
    ):
        if ts:
            xq_sets[str(sym)[:6].zfill(6)].add(str(ts))
    for sym, ts in con_xg.execute(
        f"SELECT sec_code, pub_time FROM guba_posts WHERE sec_code IN ({ph}) AND pub_time >= '2021-10-01'",
        codes_s,
    ):
        if ts:
            gb_sets[str(sym)[:6].zfill(6)].add(str(ts))
    con_xg.close()

    con_cm = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for src, sym, ts in con_cm.execute(
        "SELECT source, symbol, pub_datetime_cst FROM community_posts WHERE pub_datetime_cst >= '2021-10-01'"
    ):
        c6 = str(sym)[-6:].zfill(6)
        if c6 not in target_codes or not ts:
            continue
        if "xueqiu" in str(src).lower():
            xq_sets[c6].add(str(ts))
        else:
            gb_sets[c6].add(str(ts))
    con_cm.close()

    xq_map = {k: np.array(sorted(v), dtype=object) for k, v in xq_sets.items()}
    gb_map = {k: np.array(sorted(v), dtype=object) for k, v in gb_sets.items()}

    ir_sets = defaultdict(set)
    ir_path = f"{SIM}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
    if os.path.exists(ir_path):
        con_ir = sqlite3.connect(f"file:{ir_path}?mode=ro", uri=True)
        for sc, pdt in con_ir.execute(
            f"SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code IN ({ph}) AND pub_datetime_cst >= '2021-10-01'",
            codes_s,
        ):
            if pdt:
                ir_sets[str(sc)[:6].zfill(6)].add(str(pdt))
        con_ir.close()
    ir_map = {k: np.array(sorted(v), dtype=object) for k, v in ir_sets.items()}
    return xq_map, gb_map, ir_map


def load_kpl_and_zt_tape(target_codes: set) -> tuple[dict, dict, dict, dict]:
    """
    Load KPL plate map & zt_micro_tape + full 1to2 d1_seal_tightness components.
    Returns:
      - kpl_day_stock_plates: {(dt, c6): [plate_names]}
      - kpl_day_plate_stocks: {(dt, plate): set(c6)}
      - kpl_stock_last_plates: {c6: sorted list of (dt, [plates])}
      - tape_map: {(dt, c6): (first_seal_time, seal_amount, open_board_count)}
    """
    kpl_day_stock_plates = defaultdict(list)
    kpl_day_plate_stocks = defaultdict(set)
    kpl_stock_hist = defaultdict(list)

    p_merged = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
    p_5y = f"{SIM}/data/kpl_plates_5y_2021_2026_complete.jsonl"
    raw_by_dt = {}
    for path, cond in [(p_merged, lambda dt: True), (p_5y, lambda dt: dt >= "2021-01-01")]:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                dt = str(obj.get("date") or "")[:10]
                if dt and cond(dt):
                    raw_by_dt[dt] = obj

    for dt in sorted(raw_by_dt.keys()):
        if dt < "2021-01-01":
            continue
        for pl in raw_by_dt[dt].get("plates", []):
            pname = str(pl.get("plate") or pl.get("name") or "")
            if not pname or pname in NON_THEME:
                continue
            for st in pl.get("stocks", []):
                c6 = str(st[0] if isinstance(st, (list, tuple)) else st.get("code", ""))[-6:].zfill(6)
                kpl_day_plate_stocks[(dt, pname)].add(c6)
                if c6 in target_codes:
                    kpl_day_stock_plates[(dt, c6)].append(pname)
        # Store compact history for target codes
        seen_c = {c6 for (d, c6) in kpl_day_stock_plates if d == dt}
        for c6 in seen_c:
            kpl_stock_hist[c6].append((dt, kpl_day_stock_plates[(dt, c6)]))

    con_t = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    tape_map = {}
    for td, sc, fst, sa, obc in con_t.execute(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date >= '2021-10-01'"
    ):
        c6 = str(sc)[:6].zfill(6)
        if c6 in target_codes:
            tape_map[(str(td)[:10], c6)] = (str(fst or "99:99:99"), float(sa or 0.0), int(obc or 0))
    con_t.close()

    return kpl_day_stock_plates, kpl_day_plate_stocks, kpl_stock_hist, tape_map


def load_market_env_maps(cb: dict) -> tuple[dict, dict, dict, dict]:
    """
    Build exact daily market environment maps:
      - env_map: daily_env_5y by dt_str (plus csi_pct, csi_ret5, high-dragon brk_r10, and true high-board rebound_r10)
      - rt_map: rt_env_map by dt_str (09:25 auction stats + 14:57 close stats)
      - csrc_zt_map: {(dt, csrc_ind): zt_count}
      - csrc_ind_map: {c6: csrc_ind}
    """
    env_df = pd.read_parquet(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/daily_env_5y.parquet")
    env_df = env_df.sort_values("dt_str").reset_index(drop=True)
    env_df["csi_pct"] = env_df["csi300"] / env_df["csi300"].shift(1) - 1.0
    env_map = env_df.set_index("dt_str").to_dict(orient="index")

    with open(f"{SIM}/backtests_astock2/p5_full_pry_universe/rt_env_map.json", "r", encoding="utf-8") as f:
        rt_map = json.load(f)

    # Also compute true high-dragon 10d rebound rate & brk_dt_r10 directly from a_daily + a_delisted
    ind_df = pd.read_csv(f"{SIM}/backtest/2026-10-15-review2022/industry.csv")
    ind_df["c6"] = ind_df["code"].astype(str).str[-6:].str.zfill(6)
    csrc_ind_map = dict(zip(ind_df["c6"], ind_df["industry"].fillna("")))

    cols = ["date", "ticker", "open", "close", "adj_close"]
    df_a = pd.concat([
        ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
            columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-10-01"))
        ).to_table().to_pandas(),
        ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", format="parquet").scanner(
            columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-10-01"))
        ).to_table().to_pandas(),
    ], ignore_index=True)
    df_a["c6"] = df_a["ticker"].astype(str).str[:6]
    df_a = df_a[df_a["c6"].str.startswith(("00", "60")) & (~df_a["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_a["dt_str"] = df_a["date"].dt.strftime("%Y-%m-%d")
    df_a = df_a.sort_values(["c6", "dt_str"]).drop_duplicates(["c6", "dt_str"]).reset_index(drop=True)

    g = df_a.groupby("c6")
    df_a["adjf"] = df_a["adj_close"] / df_a["close"]
    df_a["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df_a["adjf"]
    df_a["pct"] = df_a["close"] / df_a["pre_c"] - 1.0
    df_a["zt_px"] = np.floor(df_a["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df_a["dt_px"] = np.floor(df_a["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df_a["is_zt"] = (df_a["close"] >= df_a["zt_px"] - 0.011) & (df_a["pct"] >= 0.095) & (df_a["pre_c"] > 0)
    df_a["is_dt"] = (df_a["close"] <= df_a["dt_px"] + 0.011) & (df_a["pct"] <= -0.095) & (df_a["pre_c"] > 0)

    s_zt = df_a["is_zt"].astype(int)
    df_a["streak"] = s_zt.groupby([df_a["c6"], (s_zt != g["is_zt"].shift(1).eq(True)).cumsum()]).cumsum() * s_zt
    df_a["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    df_a["prev2_streak"] = g["streak"].shift(2).fillna(0).astype(int)
    df_a["prev_is_zt"] = g["is_zt"].shift(1).eq(True)
    df_a["prev_true_yang"] = (g["close"].shift(1) > g["open"].shift(1)).eq(True)
    df_a["csrc_ind"] = df_a["c6"].map(csrc_ind_map).fillna("")

    csrc_zt_map = {}
    brk_hist = []
    reb_hist = []
    hd_rate_map = {}
    for dt, grp in df_a.groupby("dt_str", sort=True):
        zt_g = grp[grp["is_zt"]]
        csrc_zt_map[dt] = zt_g[zt_g["csrc_ind"] != ""].groupby("csrc_ind")["c6"].count().to_dict()
        # High-dragon broken limit-down rate (matching build_pit_cache.py)
        ge4 = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
        brk_hist.append((int(ge4["is_dt"].sum()), int(len(ge4))))
        # True high-dragon rebound rate: stocks that were >=4 board 2 days ago, broke yesterday, and ZT today!
        reb_cand = grp[(grp["prev2_streak"] >= 4) & (~grp["prev_is_zt"])]
        reb_hist.append((int(reb_cand["is_zt"].sum()), int((reb_cand["pct"] > 0).sum()), int(len(reb_cand))))
        w10_b = brk_hist[-10:]
        w10_r = reb_hist[-10:]
        brk_r10 = sum(x[0] for x in w10_b) / max(1, sum(x[1] for x in w10_b))
        reb_zt_r10 = sum(x[0] for x in w10_r) / max(1, sum(x[2] for x in w10_r))
        reb_pos_r10 = sum(x[1] for x in w10_r) / max(1, sum(x[2] for x in w10_r))
        hd_rate_map[dt] = {"brk_r10": brk_r10, "reb_zt_r10": reb_zt_r10, "reb_pos_r10": reb_pos_r10}

    return env_map, rt_map, hd_rate_map, csrc_zt_map, csrc_ind_map
