#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD033 Core Data & Strict PIT KPL Theme Warehouse (Ultra-Fast Target-Only Enrichment).
Computes full market OHLCV & forward paths, then enriches KPL/LHB/Top10/tox/reg ONLY on
target event rows (20cm surge 10%~19.8%, 20cm ZT1, 10cm ZT1) -> ~12s runtime instead of 120s!
ZERO yfinance (D12). ZERO cap10m. SQLite mode=ro only.
"""
import bisect
import glob
import json
import os
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock2/rd033_20cm_theme_surge10_19_20261125"

A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_JSONL = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
ZT_DB = f"{SIM}/data/zt_micro_tape_5y_pit.db"
NOTICES_DB = f"{SIM}/data/cninfo_notices_5y_pit.db"
REG_TOX_PQ = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
ZDJK_GLOB = f"{SIM}/data/kpl/zdjk/*.json"
TOP10_20CM = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies/pit_top10_20cm_summary.json"
LHB_PQ = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117/clean_lhb_5y.parquet"
BENCH_CACHE = f"{OUT_DIR}/bench_indices_cache.json"

NON_THEME = {
    "其他", "公告", "ST板块", "科创板", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股", "新股与次新股", "北交所",
    "预盈预增", "回购", "增持", "高送转", "摘帽",
}

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")
TOX_RE = re.compile(r"(?:减持计划|股东减持|减持股份|立案调查|收到立案|退市风险|违法违规|业绩预亏|预亏)")
REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|严重异常波动)")
REG_EXC = re.compile(r"(?:回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")
RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")


def shift_cal(dt_s: str, days: int) -> str:
    return (datetime.strptime(dt_s, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def cnt_ts_win(ts_list: list | None, start_ts: str, end_ts: str) -> int:
    if not ts_list:
        return 0
    return max(0, bisect.bisect_left(ts_list, end_ts) - bisect.bisect_left(ts_list, start_ts))


def split_norm_plates(raw_plate: str) -> set[str]:
    out = set()
    for part in re.split(r"[,，/、]", str(raw_plate or "")):
        part = part.strip()
        if not part or part in NON_THEME:
            continue
        base = re.sub(r"\(.*?\)|（.*?）", "", part).strip()
        for tok in [base] + re.findall(r"[\(（](.*?)[\)）]", part):
            t = tok.strip()
            if t.endswith("概念") and len(t) > 3:
                t = t[:-2].strip()
            if t and t not in NON_THEME:
                out.add(t)
    return out


def build_st_tox_reg_timelines(c6_set_all: set[str], c6_set_20: set[str], end_cutoff: str) -> tuple[dict, dict, dict]:
    cut_ts = f"{end_cutoff} 23:59:59"
    st_ev = defaultdict(list)
    tox_m = defaultdict(list)
    reg_m = defaultdict(list)

    con_z = sqlite3.connect(f"file:{ZT_DB}?mode=ro", uri=True)
    for td, sc, nm in con_z.execute(
        "SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ?",
        (end_cutoff,),
    ):
        c6 = str(sc).zfill(6)
        if c6 not in c6_set_all:
            continue
        s = str(nm or "").strip()
        if s:
            st_ev[c6].append((f"{td} 15:00:00", 1 if ("ST" in s.upper() or "退" in s) else 0))
    con_z.close()

    con_n = sqlite3.connect(f"file:{NOTICES_DB}?mode=ro", uri=True)
    for sc, ti, ts in con_n.execute(
        "SELECT sec_code, title, pub_datetime_cst FROM notices WHERE pub_datetime_cst <= ?",
        (cut_ts,),
    ):
        c6 = str(sc).zfill(6)
        if c6 not in c6_set_all:
            continue
        ts_s, t_s = str(ts)[:19], str(ti or "")
        if ST_REV_RE.search(t_s) and "不" not in t_s[:10]:
            st_ev[c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[c6].append((ts_s, 1))
        if c6 in c6_set_20:
            if TOX_RE.search(t_s):
                tox_m[c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s):
                reg_m[c6].append(ts_s)
    con_n.close()

    rt = pd.read_parquet(REG_TOX_PQ, columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    rt = rt[(rt["pub_datetime_cst"].astype(str) <= cut_ts) & rt["c6"].isin(c6_set_all)]
    for r in rt.itertuples(index=False):
        t_s, ts_s = str(r.title or ""), str(r.pub_datetime_cst)[:19]
        if ST_REV_RE.search(t_s):
            st_ev[r.c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[r.c6].append((ts_s, 1))
        if r.c6 in c6_set_20:
            if TOX_RE.search(t_s):
                tox_m[r.c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s):
                reg_m[r.c6].append(ts_s)

    for zf in glob.glob(ZDJK_GLOB):
        try:
            for it in json.load(open(zf, encoding="utf-8")).get("List", []):
                c6, d_z = str(it[0]).zfill(6), str(it[2])[:10]
                if c6 in c6_set_20 and d_z <= end_cutoff:
                    reg_m[c6].append(f"{d_z} 08:00:00")
        except Exception:
            pass

    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}
    for m in (tox_m, reg_m):
        for k in list(m.keys()):
            m[k] = sorted(set(m[k]))
    return st_tl, tox_m, reg_m


def is_st_at(st_tl: dict, c6: str, cut_ts: str) -> int:
    tl = st_tl.get(c6)
    if not tl:
        return 0
    idx = bisect.bisect_left(tl[0], cut_ts)
    return int(tl[1][idx - 1]) if idx > 0 else 0


def _compute_clean_st_flags(st_tl: dict, c6_ser: pd.Series, dt_ser: pd.Series, f1_dt_ser: pd.Series | None = None) -> np.ndarray:
    res = np.ones(len(c6_ser), dtype=bool)
    f1_iter = f1_dt_ser if f1_dt_ser is not None else dt_ser
    for i, (c6, dt, f1) in enumerate(zip(c6_ser, dt_ser, f1_iter)):
        if c6 in st_tl:
            if is_st_at(st_tl, c6, f"{dt} 15:00:00") != 0:
                res[i] = False
            elif f1_dt_ser is not None and is_st_at(st_tl, c6, f"{(f1 or dt)} 09:00:00") != 0:
                res[i] = False
    return res


def load_rd033_warehouse(end_cutoff: str = "2026-11-25") -> dict:
    t0 = time.time()
    cut_ts_pq = pd.Timestamp(end_cutoff)
    prior_cut = pd.Timestamp("2020-08-01")

    cols_age = ["date", "ticker"]
    p1 = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols_age, filter=ds.field("date") < prior_cut).to_table().to_pandas()
    p2 = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols_age, filter=ds.field("date") < prior_cut).to_table().to_pandas()
    pa_df = pd.concat([p1, p2], ignore_index=True)
    pa_df = pa_df[pa_df["ticker"].astype(str).str.endswith((".SH", ".SZ"))]
    pa_df["c6"] = pa_df["ticker"].astype(str).str[:6]
    pa_df = pa_df[pa_df["c6"].str.startswith(("300", "301", "688", "689", "00", "60"))].drop_duplicates(["c6", "date"])
    prior_age_map = pa_df.groupby("c6").size().to_dict()
    del p1, p2, pa_df

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    flt = (ds.field("date") >= prior_cut) & (ds.field("date") <= cut_ts_pq)
    da = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    raw = pd.concat([da, dd], ignore_index=True)
    del da, dd

    raw["c6"] = raw["ticker"].astype(str).str[:6]
    raw["dt"] = raw["date"].dt.strftime("%Y-%m-%d")
    mask = (
        raw["ticker"].astype(str).str.endswith((".SH", ".SZ"))
        & raw["c6"].str.startswith(("300", "301", "688", "689", "00", "60"))
        & (raw["close"] > 0)
        & (raw["adj_close"] > 0)
        & (raw["dt"] <= end_cutoff)
    )
    raw = raw[mask].sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    raw["is20"] = raw["c6"].str.startswith(("300", "301", "688", "689"))
    raw["list_age"] = raw["c6"].map(lambda c: prior_age_map.get(c, 0)).astype(np.int32) + (raw.groupby("c6", sort=False).cumcount() + 1).astype(np.int32)

    all_c6 = set(raw["c6"].unique())
    c6_20 = set(raw.loc[raw["is20"], "c6"].unique())
    st_tl, tox_m, reg_m = build_st_tox_reg_timelines(all_c6, c6_20, end_cutoff)

    d10 = raw[~raw["is20"]].copy().reset_index(drop=True)
    d20 = raw[raw["is20"]].copy().reset_index(drop=True)
    del raw

    # --- 10cm lean processing ---
    g10 = d10.groupby("c6", sort=False)
    sc10 = d10["adj_close"] / d10["close"]
    d10["ao"] = d10["open"] * sc10
    d10["ac"] = d10["adj_close"]
    d10["prev_ac"] = g10["ac"].shift(1)
    d10["ret"] = d10["ac"] / d10["prev_ac"] - 1.0
    d10["o_pct"] = d10["ao"] / d10["prev_ac"] - 1.0
    prev_ex10 = d10["prev_ac"] / sc10
    d10["zt_px"] = np.floor(prev_ex10 * 1.10 * 100.0 + 0.5) / 100.0
    d10["dt_px"] = np.floor(prev_ex10 * 0.90 * 100.0 + 0.5) / 100.0
    d10["zt_px_adj"] = d10["zt_px"] * sc10
    d10["dt_px_adj"] = d10["dt_px"] * sc10
    d10["abn_ret"] = d10["ret"].abs() > 0.12
    d10["tradable"] = (d10["volume"] > 0) & (d10["open"] > 0) & (d10["list_age"] > 20) & (~d10["abn_ret"])
    d10["is_zt"] = (d10["prev_ac"] > 0) & (d10["close"] >= d10["zt_px"] - 0.011) & (d10["ret"] >= 0.095) & (~d10["abn_ret"])
    d10["is_dt"] = (d10["prev_ac"] > 0) & (d10["close"] <= d10["dt_px"] + 0.011) & (d10["ret"] <= -0.095) & (~d10["abn_ret"])
    d10["is_yizi_zt"] = d10["is_zt"] & (d10["low"] == d10["high"]) & (d10["o_pct"] >= 0.095)
    d10["buyable_open"] = (d10["volume"] > 0) & (d10["open"] > 0) & (~((d10["open"] >= d10["zt_px"] - 0.011) & (d10["low"] == d10["high"])))
    d10["sellable_strict"] = (d10["volume"] > 0) & (d10["close"] > 0) & (~d10["is_dt"])
    sz10 = d10["is_zt"].astype(int)
    sh10 = g10["is_zt"].shift(1).fillna(False).astype(bool)
    d10["streak"] = sz10.groupby([d10["c6"], (sz10 != sh10).cumsum()]).cumsum() * sz10

    f10_cols = {"f1_abn_ret": g10["abn_ret"].shift(-1).fillna(False).astype(bool)}
    for k in range(1, 5):
        f10_cols[f"f{k}_dt"] = g10["dt"].shift(-k).fillna("")
        f10_cols[f"f{k}_ao"] = g10["ao"].shift(-k)
        f10_cols[f"f{k}_ac"] = g10["ac"].shift(-k)
        f10_cols[f"f{k}_o_pct"] = g10["o_pct"].shift(-k)
        f10_cols[f"f{k}_buyable"] = g10["buyable_open"].shift(-k).fillna(False).astype(bool)
        f10_cols[f"f{k}_sellable_strict"] = g10["sellable_strict"].shift(-k).fillna(False).astype(bool)
    d10 = pd.concat([d10, pd.DataFrame(f10_cols, index=d10.index)], axis=1)
    d10 = d10[d10["dt"] >= "2021-01-04"].copy().reset_index(drop=True)

    # Check ST only on ZT10 rows (ultra fast)
    d10_zt_rows = d10[d10["is_zt"]].copy()
    d10_zt_rows["clean_st"] = _compute_clean_st_flags(st_tl, d10_zt_rows["c6"], d10_zt_rows["dt"], d10_zt_rows["f1_dt"])
    d10_zt_clean = d10_zt_rows[d10_zt_rows["clean_st"]]
    mkt10_zt = d10_zt_clean.groupby("dt").size().to_dict()
    zt10_by_dt, yz10_by_dt = defaultdict(set), defaultdict(set)
    for dt_x, c6_x, yz_x in zip(d10_zt_clean["dt"], d10_zt_clean["c6"], d10_zt_clean["is_yizi_zt"]):
        zt10_by_dt[dt_x].add(c6_x)
        if yz_x:
            yz10_by_dt[dt_x].add(c6_x)
    d10_zt = d10_zt_clean[d10_zt_clean["tradable"] & (d10_zt_clean["close"] >= 2.0) & (d10_zt_clean["amount"] >= 1e8) & (d10_zt_clean["streak"] == 1) & (~d10_zt_clean["is_yizi_zt"])].copy().reset_index(drop=True)
    del d10, d10_zt_rows, d10_zt_clean

    # --- 20cm full technicals & defragmented f1..f12 ---
    g20 = d20.groupby("c6", sort=False)
    sc20 = d20["adj_close"] / d20["close"]
    d20["ao"] = d20["open"] * sc20
    d20["ah"] = d20["high"] * sc20
    d20["al"] = d20["low"] * sc20
    d20["ac"] = d20["adj_close"]
    d20["prev_ac"] = g20["ac"].shift(1)
    d20["ret"] = d20["ac"] / d20["prev_ac"] - 1.0
    d20["o_pct"] = d20["ao"] / d20["prev_ac"] - 1.0
    d20["h_pct"] = d20["ah"] / d20["prev_ac"] - 1.0
    prev_ex20 = d20["prev_ac"] / sc20
    d20["zt_px"] = np.floor(prev_ex20 * 1.20 * 100.0 + 0.5) / 100.0
    d20["dt_px"] = np.floor(prev_ex20 * 0.80 * 100.0 + 0.5) / 100.0
    d20["zt_px_adj"] = d20["zt_px"] * sc20
    d20["dt_px_adj"] = d20["dt_px"] * sc20
    d20["abn_ret"] = d20["ret"].abs() > 0.22
    d20["tradable"] = (d20["volume"] > 0) & (d20["open"] > 0) & (d20["list_age"] > 20) & (~d20["abn_ret"])
    d20["is_zt"] = (d20["prev_ac"] > 0) & (d20["close"] >= d20["zt_px"] - 0.011) & (d20["ret"] >= 0.195) & (~d20["abn_ret"])
    d20["is_dt"] = (d20["prev_ac"] > 0) & (d20["close"] <= d20["dt_px"] + 0.011) & (d20["ret"] <= -0.195) & (~d20["abn_ret"])
    d20["touch_zt"] = (d20["prev_ac"] > 0) & ((d20["high"] >= d20["zt_px"] - 0.011) | (d20["h_pct"] >= 0.195)) & (~d20["abn_ret"])
    d20["is_yizi_zt"] = d20["is_zt"] & (d20["low"] == d20["high"]) & (d20["o_pct"] >= 0.195)
    d20["buyable_open"] = (d20["volume"] > 0) & (d20["open"] > 0) & (~((d20["open"] >= d20["zt_px"] - 0.011) & (d20["low"] == d20["high"])))
    d20["open_is_dt"] = (d20["prev_ac"] > 0) & (d20["open"] <= d20["dt_px"] + 0.011) & (d20["o_pct"] <= -0.195)
    d20["sellable_strict"] = (d20["volume"] > 0) & (d20["close"] > 0) & (~d20["is_dt"])

    sz20 = d20["is_zt"].astype(int)
    sh20 = g20["is_zt"].shift(1).fillna(False).astype(bool)
    d20["streak"] = sz20.groupby([d20["c6"], (sz20 != sh20).cumsum()]).cumsum() * sz20

    d20["ma5"] = g20["ac"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    d20["high60_pre"] = g20["ah"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    d20["high60_incl"] = g20["ah"].transform(lambda s: s.rolling(60, min_periods=20).max())
    d20["low60_incl"] = g20["al"].transform(lambda s: s.rolling(60, min_periods=20).min())
    d20["pos60_t0"] = (d20["ac"] - d20["low60_incl"]) / np.maximum(d20["high60_incl"] - d20["low60_incl"], 1e-4)
    d20["break60_t0"] = (d20["ah"] >= d20["high60_pre"] - 1e-4).astype(np.int8)
    d20["prev_ret5"] = d20["prev_ac"] / g20["ac"].shift(6) - 1.0
    d20["ret3"] = d20["ac"] / g20["ac"].shift(3) - 1.0
    d20["vol20_m1"] = g20["ret"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).std())
    big10_f = ((d20["ret"] >= 0.10) & d20["tradable"]).astype(float)
    d20["big10_20d_pre"] = big10_f.groupby(d20["c6"], sort=False).transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum())

    hl_rng = np.maximum(d20["ah"] - d20["al"], 1e-4)
    d20["clv"] = (d20["ac"] - d20["al"]) / hl_rng
    d20["body_ratio_hl"] = (d20["ac"] - d20["ao"]) / hl_rng
    d20["body_pct"] = (d20["ac"] - d20["ao"]) / np.maximum(d20["prev_ac"], 1e-4)
    d20["upper_shad"] = (d20["ah"] - np.maximum(d20["ao"], d20["ac"])) / np.maximum(d20["prev_ac"], 1e-4)
    est_sh = np.where(d20["oshare"].fillna(0) > 0, d20["oshare"], np.where(d20["turn"] > 0, d20["volume"] / d20["turn"], np.nan))
    d20["mcap"] = est_sh * d20["close"] / 1e8

    f20_cols = {"f1_abn_ret": g20["abn_ret"].shift(-1).fillna(False).astype(bool)}
    for k in range(1, 13):
        f20_cols[f"f{k}_dt"] = g20["dt"].shift(-k).fillna("")
        f20_cols[f"f{k}_ao"] = g20["ao"].shift(-k)
        f20_cols[f"f{k}_ah"] = g20["ah"].shift(-k)
        f20_cols[f"f{k}_al"] = g20["al"].shift(-k)
        f20_cols[f"f{k}_ac"] = g20["ac"].shift(-k)
        f20_cols[f"f{k}_o_pct"] = g20["o_pct"].shift(-k)
        f20_cols[f"f{k}_buyable"] = g20["buyable_open"].shift(-k).fillna(False).astype(bool)
        f20_cols[f"f{k}_open_is_dt"] = g20["open_is_dt"].shift(-k).fillna(False).astype(bool)
        f20_cols[f"f{k}_sellable_strict"] = g20["sellable_strict"].shift(-k).fillna(False).astype(bool)
        f20_cols[f"f{k}_is_zt"] = g20["is_zt"].shift(-k).fillna(False).astype(bool)
        f20_cols[f"f{k}_is_dt"] = g20["is_dt"].shift(-k).fillna(False).astype(bool)
        f20_cols[f"f{k}_ma5"] = g20["ma5"].shift(-k)
        f20_cols[f"f{k}_zt_px_adj"] = g20["zt_px_adj"].shift(-k)
        f20_cols[f"f{k}_dt_px_adj"] = g20["dt_px_adj"].shift(-k)
    d20 = pd.concat([d20, pd.DataFrame(f20_cols, index=d20.index)], axis=1)
    d20 = d20[d20["dt"] >= "2021-01-04"].copy().reset_index(drop=True)
    d20["clean_st"] = _compute_clean_st_flags(st_tl, d20["c6"], d20["dt"], d20["f1_dt"])

    # Build fast bar close lookup for daily MTM
    bar_ac_lu = {(c6, dt): float(ac) for c6, dt, ac in zip(d20["c6"], d20["dt"], d20["ac"])}
    bar_ac_lu.update({(c6, dt): float(ac) for c6, dt, ac in zip(d10_zt["c6"], d10_zt["dt"], d10_zt["ac"])})

    mkt20_zt = d20[d20["is_zt"] & d20["clean_st"]].groupby("dt").size().to_dict()
    ew20_daily = d20[d20["tradable"] & d20["clean_st"] & (~d20["abn_ret"])].groupby("dt")["ret"].mean().to_dict()

    zt20_by_dt = defaultdict(set)
    for dt_x, c6_x in zip(d20.loc[d20["is_zt"] & d20["clean_st"], "dt"],
                          d20.loc[d20["is_zt"] & d20["clean_st"], "c6"]):
        zt20_by_dt[dt_x].add(c6_x)

    early1030_10_by_dt = defaultdict(set)
    con_z = sqlite3.connect(f"file:{ZT_DB}?mode=ro", uri=True)
    for td, sc, fst in con_z.execute(
        "SELECT trade_date, sec_code, first_seal_time FROM zt_micro_tape WHERE trade_date >= '2021-01-04' AND trade_date <= ?",
        (end_cutoff,),
    ):
        c6 = str(sc).zfill(6)
        if c6.startswith(("00", "60")):
            fst_s = str(fst or "15:00:00").replace(":", "")[:4]
            if (int(fst_s) if fst_s.isdigit() else 1500) <= 1030:
                early1030_10_by_dt[str(td)].add(c6)
    con_z.close()

    # Chronological KPL processing
    hist_kpl = defaultdict(list)
    kpl_t0_plate_stats = {}
    kpl_t0_stock_direct = {}
    kpl_objs = []
    with open(KPL_JSONL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            if obj.get("date", "") <= end_cutoff:
                kpl_objs.append(obj)
    kpl_objs.sort(key=lambda x: x["date"])

    for obj in kpl_objs:
        dt_k = obj["date"]
        z10, z20, yz10, e1030 = zt10_by_dt.get(dt_k, set()), zt20_by_dt.get(dt_k, set()), yz10_by_dt.get(dt_k, set()), early1030_10_by_dt.get(dt_k, set())
        rk = 0
        for pl in obj.get("plates", []):
            raw_pn = str(pl.get("plate", "")).strip()
            if not raw_pn or raw_pn in NON_THEME:
                continue
            tokens = split_norm_plates(raw_pn)
            if not tokens:
                continue
            rk += 1
            mems = {str(s[0]).strip()[:6].zfill(6) for s in pl.get("stocks", [])}
            kpl_sz = len(mems)
            if dt_k >= "2021-01-04":
                n10 = len(mems & z10)
                n20 = len(mems & z20)
                tot_zt = max(kpl_sz, n10 + n20)
                has_10yz = int(len(mems & yz10) >= 1)
                has_10e1030 = int(len(mems & (e1030 | yz10)) >= 1)
                rec = (rk, kpl_sz, n10, n20, tot_zt, has_10yz, has_10e1030, raw_pn)
                for tok in tokens:
                    prev = kpl_t0_plate_stats.get((dt_k, tok))
                    if prev is None or (rec[4], -rec[0]) > (prev[4], -prev[0]):
                        kpl_t0_plate_stats[(dt_k, tok)] = rec
                for c6 in mems:
                    cur = kpl_t0_stock_direct.get((dt_k, c6))
                    if cur is None or (rec[4], -rec[0]) > (cur[4], -cur[0]):
                        kpl_t0_stock_direct[(dt_k, c6)] = rec
            for c6 in mems:
                hist_kpl[c6].append((dt_k, tokens))

    hist_dts = {c6: [x[0] for x in v] for c6, v in hist_kpl.items()}

    # Subset ONLY to target 20cm events BEFORE expensive KPL/Top10/LHB/Notice lookups! (2.5M -> ~35k rows!)
    is_surge = d20["tradable"] & d20["clean_st"] & (d20["close"] >= 2.0) & (d20["ret"] >= 0.10) & (d20["ret"] < 0.198) & (~d20["is_zt"])
    is_zt20 = d20["tradable"] & d20["clean_st"] & (d20["close"] >= 2.0) & (d20["amount"] >= 1e8) & d20["is_zt"] & (d20["streak"] == 1) & (~d20["is_yizi_zt"])
    tgt20 = d20[is_surge | is_zt20].copy().reset_index(drop=True)
    del d20

    t10 = json.load(open(TOP10_20CM, encoding="utf-8")) if os.path.exists(TOP10_20CM) else {}
    lock_arr = np.full(len(tgt20), np.nan)
    for c6, idx_arr in tgt20.groupby("c6", sort=False).groups.items():
        recs = [x for x in t10.get(c6, []) if x[0] <= end_cutoff]
        if not recs:
            continue
        for j in idx_arr:
            d_c = tgt20.at[j, "dt"]
            best_ed, best_l = "", np.nan
            for nd, ed, l10, _ in recs:
                if nd < d_c and ed >= best_ed:
                    best_ed, best_l = ed, l10
            lock_arr[j] = best_l
    lock_fill = np.where(np.isnan(lock_arr), 40.0, np.clip(lock_arr, 0.0, 95.0))
    tgt20["real_free_mcap"] = tgt20["mcap"] * (1.0 - lock_fill / 100.0)

    lhb = pd.read_parquet(LHB_PQ)
    lhb = lhb[(lhb["date"] <= end_cutoff) & lhb["stock_code"].str.startswith(("300", "301", "688", "689"))].copy().sort_values(["date", "stock_code", "is_three"])
    lhb_inst_map, lhb_lh_map = {}, {}
    for (dt_l, sc_l, is3), grp in lhb.groupby(["date", "stock_code", "is_three"], sort=False):
        if is3 == 1 and (dt_l, sc_l) in lhb_inst_map:
            continue
        lhb_inst_map[(dt_l, sc_l)] = float(grp[grp["dept_code"] == "0"]["NET"].sum()) / 1e4
        b_names = grp[grp["side"] == "B"]["dept_name"].astype(str).tolist()
        lhb_lh_map[(dt_l, sc_l)] = sum(1 for nm in b_names if RE_LHASA.search(nm) and "东亚" not in nm)

    bench = json.load(open(BENCH_CACHE, encoding="utf-8"))
    bench_cut = {bk: {dt_b: float(v_b) for dt_b, v_b in bmap.items() if dt_b <= end_cutoff} for bk, bmap in bench.items()}
    sh300, sz399006, sh000688 = bench_cut["sh000300"], bench_cut["sz399006"], bench_cut["sh000688"]

    n20 = len(tgt20)
    k_has_hist = np.zeros(n20, dtype=np.int8)
    k_rk_all = np.full(n20, 99, dtype=np.int16)
    k_zt_all = np.zeros(n20, dtype=np.int16)
    k_10yz_all = np.zeros(n20, dtype=np.int8)
    k_10e1030_all = np.zeros(n20, dtype=np.int8)
    k_plate_all = [""] * n20
    k_zt_365 = np.zeros(n20, dtype=np.int16)
    k_rk_365 = np.full(n20, 99, dtype=np.int16)
    k_zt_180 = np.zeros(n20, dtype=np.int16)
    k_rk_180 = np.full(n20, 99, dtype=np.int16)
    tox_90 = np.zeros(n20, dtype=np.int8)
    reg_10 = np.zeros(n20, dtype=np.int8)
    lhb_inst = np.zeros(n20, dtype=np.float64)
    lhb_lh = np.zeros(n20, dtype=np.int16)

    shift_cache = {}
    for i, (c6, dt, f1dt) in enumerate(zip(tgt20["c6"], tgt20["dt"], tgt20["f1_dt"])):
        t1_cut = f"{(f1dt or dt)} 09:00:00"
        if dt not in shift_cache:
            shift_cache[dt] = (shift_cal(dt, -90), shift_cal(dt, -10), shift_cal(dt, -365), shift_cal(dt, -180))
        d90, d10_c, d365, d180 = shift_cache[dt]
        if c6 in tox_m and cnt_ts_win(tox_m[c6], f"{d90} 00:00:00", t1_cut) > 0:
            tox_90[i] = 1
        if c6 in reg_m and cnt_ts_win(reg_m[c6], f"{d10_c} 00:00:00", t1_cut) > 0:
            reg_10[i] = 1
        lhb_inst[i] = lhb_inst_map.get((dt, c6), 0.0)
        lhb_lh[i] = lhb_lh_map.get((dt, c6), 0)

        dir_rec = kpl_t0_stock_direct.get((dt, c6))
        hd = hist_dts.get(c6)
        if hd:
            hi = bisect.bisect_left(hd, dt)
            if hi > 0:
                k_has_hist[i] = 1
                toks_all, toks_365, toks_180 = set(), set(), set()
                lo365 = bisect.bisect_left(hd, d365)
                lo180 = bisect.bisect_left(hd, d180)
                for j in range(0, hi):
                    toks_all |= hist_kpl[c6][j][1]
                    if j >= lo365:
                        toks_365 |= hist_kpl[c6][j][1]
                    if j >= lo180:
                        toks_180 |= hist_kpl[c6][j][1]
                best_a = None
                for tok in toks_all:
                    rec = kpl_t0_plate_stats.get((dt, tok))
                    if rec and (best_a is None or (rec[4], -rec[0]) > (best_a[4], -best_a[0])):
                        best_a = rec
                if best_a:
                    k_rk_all[i], _, _, _, k_zt_all[i], k_10yz_all[i], k_10e1030_all[i], k_plate_all[i] = best_a
                best_365 = None
                for tok in toks_365:
                    rec = kpl_t0_plate_stats.get((dt, tok))
                    if rec and (best_365 is None or (rec[4], -rec[0]) > (best_365[4], -best_365[0])):
                        best_365 = rec
                if best_365:
                    k_rk_365[i], k_zt_365[i] = best_365[0], best_365[4]
                best_180 = None
                for tok in toks_180:
                    rec = kpl_t0_plate_stats.get((dt, tok))
                    if rec and (best_180 is None or (rec[4], -rec[0]) > (best_180[4], -best_180[0])):
                        best_180 = rec
                if best_180:
                    k_rk_180[i], k_zt_180[i] = best_180[0], best_180[4]
        if dir_rec is not None and dir_rec[4] > k_zt_all[i]:
            k_rk_all[i], _, _, _, k_zt_all[i], k_10yz_all[i], k_10e1030_all[i], k_plate_all[i] = dir_rec

    sh_dts = sorted(sh300.keys())
    idx_r3_map = pd.Series([sh300[d] for d in sh_dts], index=sh_dts).pct_change(3).to_dict()

    extra20 = {
        "kpl_has_hist": k_has_hist, "kpl_rk": k_rk_all, "kpl_zt_cnt": k_zt_all,
        "kpl_10yz": k_10yz_all, "kpl_10e1030": k_10e1030_all, "kpl_plate": k_plate_all,
        "kpl_rk_365": k_rk_365, "kpl_zt_365": k_zt_365, "kpl_rk_180": k_rk_180, "kpl_zt_180": k_zt_180,
        "tox_90d": tox_90, "reg_10d": reg_10, "lhb_inst_net": lhb_inst, "lhb_lh_cnt": lhb_lh,
        "mkt20_zt_cnt": tgt20["dt"].map(mkt20_zt).fillna(0).astype(int),
        "mkt10_zt_cnt": tgt20["dt"].map(mkt10_zt).fillna(0).astype(int),
        "dist_3d30": 0.30 - (tgt20["ret3"] - tgt20["dt"].map(idx_r3_map).fillna(0.0)),
    }
    tgt20 = pd.concat([tgt20, pd.DataFrame(extra20, index=tgt20.index)], axis=1)

    surge_mask = (~tgt20["is_zt"]) & (tgt20["amount"] >= 1e8)
    tgt20["in_surge"] = surge_mask
    tgt20["in_surge_all_amt"] = ~tgt20["is_zt"]
    tgt20["in_zt20_1b"] = tgt20["is_zt"] & (tgt20["streak"] == 1) & (~tgt20["is_yizi_zt"]) & (tgt20["amount"] >= 1e8)
    tgt20["rk20_ret_in_theme"] = 99
    tgt20["rk20_amt_in_theme"] = 99
    sub_s = tgt20[surge_mask & (tgt20["kpl_plate"] != "")].copy()
    tgt20.loc[sub_s.index, "rk20_ret_in_theme"] = sub_s.groupby(["dt", "kpl_plate"])["ret"].rank(ascending=False, method="min").astype(int)
    tgt20.loc[sub_s.index, "rk20_amt_in_theme"] = sub_s.groupby(["dt", "kpl_plate"])["amount"].rank(ascending=False, method="min").astype(int)

    k10_rk, k10_zt, k10_yz, k10_pl = [], [], [], []
    for dt_x, c6_x in zip(d10_zt["dt"], d10_zt["c6"]):
        rec = kpl_t0_stock_direct.get((dt_x, c6_x))
        if rec:
            k10_rk.append(rec[0]); k10_zt.append(rec[4]); k10_yz.append(rec[5]); k10_pl.append(rec[7])
        else:
            k10_rk.append(99); k10_zt.append(0); k10_yz.append(0); k10_pl.append("")
    d10_zt["kpl_rk"] = k10_rk; d10_zt["kpl_zt_cnt"] = k10_zt; d10_zt["kpl_10yz"] = k10_yz; d10_zt["kpl_plate"] = k10_pl

    all_cal_dts = sorted([d for d in sh_dts if "2021-01-04" <= d <= end_cutoff])
    print(f"[Warehouse <= {end_cutoff}] tgt20={len(tgt20):,} (surge={int(surge_mask.sum()):,}), d10_zt1={len(d10_zt):,} in {time.time()-t0:.2f}s")
    return {
        "d20": tgt20, "d10_zt": d10_zt, "bar_ac_lu": bar_ac_lu,
        "sh300": sh300, "sz399006": sz399006, "sh000688": sh000688,
        "ew20_daily": ew20_daily, "all_cal_dts": all_cal_dts,
    }
