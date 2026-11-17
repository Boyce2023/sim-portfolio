#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
二进三 V2.0_cand（互学升级独立版）五年纯前视 PIT 完整回测与八项防过拟合审计引擎
================================================================================
严格遵循：
  1. 100% 独立单策略（所有信号、打分与出场仅依赖自身 PIT 数据，不依赖其他策略实盘状态）
  2. 参数与权重 100% 在 IS (2021-01-04 ~ 2023-12-31) 标定，OOS (2024-01-01 ~ 2026-11-16) 盲测
  3. 严禁 import yfinance (D12)；SQLite 一律 file:...?mode=ro 只读；严禁触碰现役生产文件
  4. 物理截断 >= 2025-01-01 全部原始数据源重算滚动 HHI q25、Elo、新词破冰、退潮脉冲与出场，
     硬断言与全量跑出 2021-2024 逐笔日期、代码、得分、收益率 max_abs_diff == 0.0
================================================================================
"""

import os
import sys
import re
import json
import math
import time
import sqlite3
import datetime
import itertools
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"
CLEAN_V10_DIR = f"{SIM}/backtests_astock/clean_2to3_v10_20261117"
CLEAN_16_DIR = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
OUT_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"

RAW_2TO3_PQ = f"{CLEAN_V10_DIR}/data_pit/clean_2to3_5y.parquet"
WAVE_A_PQ = f"{CLEAN_V10_DIR}/data_pit/factors_a.parquet"
WAVE_B_PQ = f"{CLEAN_V10_DIR}/data_pit/factors_b.parquet"
WAVE_C_PQ = f"{CLEAN_V10_DIR}/data_pit/factors_c.parquet"

A_DAILY_PQ = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PQ = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
BARS_5M_PQ = f"{DATA_DIR}/all_strategies_5m_complete_pit.parquet"
KPL_MERGED_JL = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
CSRC_PIT_CSV = f"{DATA_DIR}/csrc_industry_pit_clean.csv"
DB_ZT_TAPE = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
CSI_CANON_JSON = f"{CLEAN_16_DIR}/csi300_canonical_20261116.json"

FEE_ROUNDTRIP = 0.0020
CANON_5Y_START = "2021-11-16"
DATA_AS_OF_EXPECTED = "2026-11-16"

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}
HARD_TECH_RE = re.compile(
    r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)"
)
CSRC_PURE_OUTSIDER = {
    "A01", "A02", "A03", "A04", "A05",
    "D44", "D45", "D46",
    "E47", "E48", "E49", "E50",
    "F51", "F52",
    "G53", "G54", "G55", "G56", "G58", "G59",
    "H61", "H62",
    "K70", "L72", "N77", "N78",
    "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22",
}

FACTOR_NAMES_V2 = [
    "P1_1_HHI离散或单极集中(+6/-10)",
    "P1_2_晋级率低迷分歧(+8/+5)",
    "P1_3_市场高度<=3板压制(+6)",
    "P2_1_板块温热区或过热拥挤(+5/-10)",
    "P2_2_板块极寒Elo<=95破冰(+8)",
    "P2_4_同板块3板+老大哥压制(-8)",
    "P3_1_雪球暗牌零帖vs吹票(0/-10/-18)",
    "P3_2_近20日机构调研排雷(-10)",
    "P4_1_D2盘中深水洗盘<=-2%(+6)",
    "P4_2_D2开板弱封单vs死锁秒板(+6/-8/-16)",
    "P4_3_启动前20日箱体低位<=0.40(+6)",
    "P4_4_前十大锁仓>=50%&换手分段(+8/+5/-8)",
    "P5_1_D3竞价绿开承接<0%(+5)",
    "U1_传统行业跨界硬科技暗牌(+4)",
    "U2_自身细分概念15日新词破冰(+4)",
    "U3_退潮一日游脉冲排雷(-8)",
    "U4_D2尾盘14:30后烂板偷袭(-6)",
    "U5_D1首板一字透支(-6)",
]


def split_terms(s: str) -> set[str]:
    out = set()
    for part in re.split(r"[+、,，/；;]", s or ""):
        part = part.strip()
        if not part:
            continue
        out.add(part)
        for x in re.split(r"[()（）]", part):
            x = x.strip()
            if x:
                out.add(x)
    return {t for t in out if 2 <= len(t) <= 20 and t not in NON_THEME}


def _time_to_sec(tstr: str) -> float | None:
    if not tstr or len(tstr) < 5 or str(tstr).startswith("99"):
        return None
    parts = str(tstr).strip().split(":")
    try:
        hh, mm = int(parts[0]), int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
        if hh < 9 or (hh == 9 and mm < 30):
            return 0.0
        if hh < 12:
            return float((hh - 9) * 3600 + (mm - 30) * 60 + ss)
        return float(7200 + (hh - 13) * 3600 + mm * 60 + ss)
    except Exception:
        return None


def load_daily_and_5m(cutoff_date: str | None = None):
    """加载全量日线(在市+退市)与5m分钟K线；若指定cutoff_date则物理截断后续全部数据"""
    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "amount"]
    flt = ds.field("date") >= pd.Timestamp("2018-01-01")
    if cutoff_date:
        flt = flt & (ds.field("date") <= pd.Timestamp(cutoff_date))
    d_act = ds.dataset(A_DAILY_PQ, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d_del = ds.dataset(A_DELISTED_PQ, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da = pd.concat([d_act, d_del], ignore_index=True)
    da["c6"] = da["ticker"].astype(str).str[:6]
    da = da[da["c6"].str.startswith(("00", "60")) & (~da["ticker"].astype(str).str.endswith(".BJ"))].copy()
    da["dt"] = da["date"].dt.strftime("%Y-%m-%d")
    if cutoff_date:
        da = da[da["dt"] <= cutoff_date].copy()
    da.sort_values(["c6", "dt"], inplace=True)
    da.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    da.reset_index(drop=True, inplace=True)

    g_da = da.groupby("c6")
    da["pre_c"] = g_da["close"].shift(1)
    da["pct"] = da["close"] / da["pre_c"] - 1.0
    da["zt_px"] = np.floor(da["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    da["dt_px"] = np.floor(da["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    da["is_zt"] = (da["pre_c"] > 0) & (da["close"] >= da["zt_px"] - 0.01) & (da["pct"] >= 0.095)
    da["touch_zt"] = (da["pre_c"] > 0) & (da["high"] >= da["zt_px"] - 0.01)
    da["is_dt_exact"] = (da["pre_c"] > 0) & (da["close"] <= da["dt_px"] + 0.001) & (da["pct"] <= -0.095)
    da["is_yizi"] = da["is_zt"] & (da["open"] >= da["zt_px"] - 0.01) & (da["low"] >= da["zt_px"] - 0.01)
    da["is_yizi_dt"] = da["is_dt_exact"] & (da["open"] <= da["dt_px"] + 0.001) & (da["high"] <= da["dt_px"] + 0.001)
    s_zt = da["is_zt"].astype(int)
    s_shift = g_da["is_zt"].shift(1).fillna(False).infer_objects(copy=False).astype(bool)
    da["streak"] = s_zt.groupby([da["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt
    da["is_2b_plus"] = da["streak"] >= 2

    df_5m = pd.read_parquet(BARS_5M_PQ)
    if cutoff_date:
        df_5m = df_5m[df_5m["date"].astype(str) <= cutoff_date].copy()
    df_5m["c6"] = df_5m["c6"].astype(str).str.zfill(6)
    df_5m["hhmm_int"] = df_5m["hhmm_int"].astype(int)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    b5m = {
        (c6, str(dt)): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False)
    }
    return da, b5m


def compute_causal_raw_signals(da: pd.DataFrame, cutoff_date: str | None = None) -> dict:
    """从原始KPL JSONL、日线、CSRC与微盘库从头因果滚动计算HHI q25/Elo/新词破冰/退潮脉冲/D1一字/尾盘封单"""
    kpl_by_dt = {}
    with open(KPL_MERGED_JL, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                obj = json.loads(ln)
                dt_k = obj.get("date", "")
                if cutoff_date and dt_k > cutoff_date:
                    continue
                pls = obj.get("plates", [])
                if dt_k and sum(len(x.get("stocks", [])) for x in pls) > 0:
                    kpl_by_dt[dt_k] = pls

    kpl_dts = sorted(kpl_by_dt.keys())
    sub = da[da["dt"].isin(set(kpl_dts))][["dt", "c6", "pct", "is_zt", "touch_zt", "is_2b_plus"]]
    stat_map = {
        (r.dt, r.c6): (float(r.pct), bool(r.is_zt), bool(r.touch_zt), bool(r.is_2b_plus))
        for r in sub.itertuples(index=False) if pd.notna(r.pct)
    }

    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_last_idx, sub_last_idx = {}, {}
    prev_p, prev_sub = {}, {}
    plate_recent_zts = defaultdict(list)
    hist_hhi = []
    term_seen = Counter()
    term_first = {}

    rec_hhi, rec_elo_p, rec_elo_s, rec_dying, rec_own = {}, {}, {}, {}, {}
    for idx, dt in enumerate(kpl_dts):
        cut15 = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        for pn, c6l in prev_p.items():
            t = s = 0
            rs = []
            for c6 in c6l:
                st = stat_map.get((dt, c6))
                if st is not None:
                    rs.append(st[0]); s += int(st[1]); t += int(st[2])
            if t >= 2 and (s / t) < 0.50:
                elo[pn] -= 12.0 * ((t - s) / t)
            elif rs and float(np.mean(rs)) < -0.025:
                elo[pn] -= 10.0
            elif s >= 2 and (s / max(t, 1)) >= 0.70:
                elo[pn] += min(10.0, 5.0 + s * 1.2)
            elif rs and float(np.mean(rs)) > 0.025:
                elo[pn] += 6.0

        for sn, c6l in prev_sub.items():
            t = s = 0
            rs = []
            for c6 in c6l:
                st = stat_map.get((dt, c6))
                if st is not None:
                    rs.append(st[0]); s += int(st[1]); t += int(st[2])
            if t >= 2 and (s / t) < 0.50:
                sub_elo[sn] -= 10.0 * ((t - s) / t)
            elif rs and float(np.mean(rs)) < -0.025:
                sub_elo[sn] -= 8.0
            elif s >= 1 and (s / max(t, 1)) >= 0.70:
                sub_elo[sn] += min(9.0, 4.0 + s * 1.5)
            elif rs and float(np.mean(rs)) > 0.025:
                sub_elo[sn] += 5.0

        for pk in list(elo):
            if idx - plate_last_idx.get(pk, idx) > 3:
                elo[pk] = 100.0 + (elo[pk] - 100.0) * 0.85
        for sk in list(sub_elo):
            if idx - sub_last_idx.get(sk, idx) > 3:
                sub_elo[sk] = 100.0 + (sub_elo[sk] - 100.0) * 0.85

        np_p, np_s = {}, defaultdict(list)
        sz_all = []
        day_terms = set()
        for p in kpl_by_dt[dt]:
            pn = p.get("plate", "")
            stks = p.get("stocks", [])
            if not stks or pn in NON_THEME:
                continue
            sz = len(stks)
            sz_all.append(sz)
            plate_last_idx[pn] = idx
            c6l = []
            n2 = 0
            for s in stks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6l.append(c6)
                st = stat_map.get((dt, c6))
                if st is not None and st[3]:
                    n2 += 1
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                if r_sh and r_sh not in NON_THEME:
                    np_s[r_sh].append(c6)
                    sub_last_idx[r_sh] = idx
                for t in (split_terms(pn) | split_terms(r_sh)):
                    day_terms.add(t)
                if dt >= "2021-01-01":
                    se = float(sub_elo[r_sh]) if (r_sh and r_sh not in NON_THEME) else float(elo[pn])
                    if (dt, c6) not in rec_elo_p or sz > rec_elo_p[(dt, c6)][0]:
                        rec_elo_p[(dt, c6)] = (sz, float(elo[pn]))
                        rec_elo_s[(dt, c6)] = se
                    if (dt, c6) not in rec_own:
                        rec_own[(dt, c6)] = any(
                            (term_seen[t] == 0 or term_first.get(t, dt) >= cut15)
                            for t in split_terms(r_sh + "+" + r_lg)
                        )
            dyp = bool(any(z >= 5 for pi, z in plate_recent_zts[pn] if (idx - 8 <= pi <= idx - 3)) and n2 == 0)
            plate_recent_zts[pn].append((idx, sz))
            if dt >= "2021-01-01":
                for c6 in c6l:
                    if (dt, c6) not in rec_dying:
                        rec_dying[(dt, c6)] = dyp
            np_p[pn] = c6l

        tot_s = sum(sz_all)
        hhi = sum((x / tot_s) ** 2 for x in sz_all) if tot_s > 0 else 1.0
        if dt >= "2019-12-01":
            win = hist_hhi[-250:]
            hp = float(np.mean([1.0 if x <= hhi else 0.0 for x in win])) if len(win) >= 20 else 0.5
            hist_hhi.append(hhi)
            if dt >= "2021-01-01":
                rec_hhi[dt] = int(hp <= 0.25)
        for t in day_terms:
            term_seen[t] += 1
            if t not in term_first:
                term_first[t] = dt
        prev_p, prev_sub = np_p, np_s

    csrc_df = pd.read_csv(CSRC_PIT_CSV, dtype=str).fillna("")
    if cutoff_date:
        csrc_df = csrc_df[csrc_df["start_date"].str[:10] <= cutoff_date].copy()
    csrc_by_c6 = defaultdict(list)
    for r in csrc_df.itertuples(index=False):
        c6 = str(r.sec_code).strip()[:6].zfill(6)
        csrc_by_c6[c6].append((str(r.start_date)[:10], str(r.end_date)[:10], str(r.industry)[:3] if str(r.industry) else "UNK"))

    tape_sec = {}
    con = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
    try:
        q = "SELECT trade_date, sec_code, first_seal_time FROM zt_micro_tape"
        params = ()
        if cutoff_date:
            q += " WHERE trade_date <= ?"
            params = (cutoff_date,)
        for td, sc, fst in con.execute(q, params):
            sec_v = _time_to_sec(str(fst or ""))
            if sec_v is not None:
                tape_sec[(str(td), str(sc)[:6].zfill(6))] = sec_v
    finally:
        con.close()

    yizi_map = {
        (r.dt, r.c6): bool(r.is_yizi)
        for r in da[da["dt"] >= "2020-12-01"][["dt", "c6", "is_yizi"]].itertuples(index=False)
    }

    return {
        "rec_hhi": rec_hhi,
        "rec_elo_p": rec_elo_p,
        "rec_elo_s": rec_elo_s,
        "rec_dying": rec_dying,
        "rec_own": rec_own,
        "csrc_by_c6": csrc_by_c6,
        "tape_sec": tape_sec,
        "yizi_map": yizi_map,
    }


def sim_v2_exit_all(df: pd.DataFrame, da: pd.DataFrame, b5m: dict, cutoff_date: str | None = None) -> tuple[list, list, list]:
    """
    V2.0_cand 独立因果出场树:
      - 未封3板(~sealed_3b): 取消次日竞价地板斩仓，持仓过早盘抛压至D4 15:00清仓;
        若D4一字跌停顺延至首个非一字跌停日09:25; 若D4收盘精确跌停(dt_px)不可卖则顺延至次日09:25;
        若D4反包封死涨停则无缝切入连板骑乘链!
      - 封死3板(sealed_3b): D4极高开>9.2%且非一字板直接09:25兑现透支区;
        否则走13:45盘中冲高回落护利+1次真阳免死; 严格遵守一字跌停/收盘精确跌停不可卖顺延!
    """
    all_dts = sorted(da["dt"].unique())
    dt_idx = {d: i for i, d in enumerate(all_dts)}
    plook = {
        (r.c6, r.dt): (
            float(r.open), float(r.high), float(r.low), float(r.close),
            float(r.pre_c) if pd.notna(r.pre_c) else float(r.close),
            float(r.zt_px) if pd.notna(r.zt_px) else 9999.0,
            float(r.dt_px) if pd.notna(r.dt_px) else 0.0,
            bool(r.is_zt), bool(r.is_dt_exact), bool(r.is_yizi), bool(r.is_yizi_dt),
        )
        for r in da[da["dt"] >= "2020-12-25"][
            ["c6", "dt", "open", "high", "low", "close", "pre_c", "zt_px", "dt_px", "is_zt", "is_dt_exact", "is_yizi", "is_yizi_dt"]
        ].itertuples(index=False)
    }

    rets, eds, ehs = [], [], []
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        pos = dt_idx.get(bd, -1)
        if pos < 0 or pos >= len(all_dts) - 1:
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        b3 = plook.get((c6, bd))
        if not b3:
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        buy_px = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)

        def run_zt_hold(sp_idx: int):
            k = sp_idx + 1
            used_imm = False
            while k < len(all_dts) and (k - pos <= 18):
                dk = all_dts[k]
                bk = plook.get((c6, dk))
                if not bk:
                    k += 1; continue
                ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = bk
                if iyzdtk:
                    k += 1; continue
                if k > sp_idx + 1:
                    pb = plook.get((c6, all_dts[k - 1]))
                    if pb and (pb[10] or pb[8]):
                        return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925
                if k == pos + 1:
                    d4_op = ok / pck - 1.0 if pck > 0 else 0.0
                    if (d4_op > 0.092) and (ok < ztk - 0.005):
                        return (ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 925
                arr = b5m.get((c6, dk))
                if arr is not None and len(arr) > 0:
                    pk = ok
                    for row5 in arr:
                        hh, bo, bh, bl, bc = int(row5[0]), row5[1], row5[2], row5[3], row5[4]
                        if bh <= dtk + 0.005:
                            continue
                        if hh >= 1345 and pk >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                            px = min(bo, pck * 1.050)
                            if px > dtk + 0.005:
                                return (px / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, hh
                        if bh > pk:
                            pk = bh
                if iztk:
                    k += 1; continue
                if idtk:
                    k += 1; continue
                if (not used_imm) and (ck > ok) and (ck >= pck):
                    used_imm = True; k += 1; continue
                return (ck / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0, dk, 1500
            return float(r.ret_opn_cc), str(r.exit_dt_cc), int(r.exit_hh_cc)

        if b3[7]:
            rv, edv, ehv = run_zt_hold(pos)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
            continue

        k = pos + 1
        while k < len(all_dts):
            bk = plook.get((c6, all_dts[k]))
            if bk and not bk[10]:
                break
            k += 1
        if k >= len(all_dts):
            rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
            continue
        dk = all_dts[k]
        ok, hk, lk, ck, pck, ztk, dtk, iztk, idtk, iyzk, iyzdtk = plook[(c6, dk)]
        if k > pos + 1:
            rets.append((ok / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(925)
        elif iztk:
            rv, edv, ehv = run_zt_hold(k)
            rets.append(rv); eds.append(edv); ehs.append(ehv)
        elif idtk:
            m = k + 1
            sold = False
            while m < len(all_dts):
                bm = plook.get((c6, all_dts[m]))
                if bm and not bm[10]:
                    rets.append((bm[0] / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(all_dts[m]); ehs.append(925)
                    sold = True; break
                m += 1
            if not sold:
                rets.append(float(r.ret_opn_cc)); eds.append(str(r.exit_dt_cc)); ehs.append(int(r.exit_hh_cc))
        else:
            rets.append((ck / buy_px) * (1.0 - FEE_ROUNDTRIP) - 1.0); eds.append(dk); ehs.append(1500)

    # 零一字跌停/收盘跌停偷跑严格断言
    if cutoff_date is None:
        for idx_i, r in enumerate(df.itertuples(index=False)):
            ed, eh = eds[idx_i], ehs[idx_i]
            bk = plook.get((str(r.code).zfill(6), ed))
            if bk:
                assert not bk[10], f"Sold on yizi_dt violation: {r.code} {ed}"
                if eh == 1500 and ed < all_dts[-1]:
                    assert not bk[8], f"Sold at 15:00 on EOD exact limit-down violation: {r.code} {ed}"
    return rets, eds, ehs


def build_pit_dataset(cutoff_date: str | None = None):
    """构建完整或物理截断至cutoff_date的纯前视数据集并重算全部因果滚动信号"""
    raw_all = pd.read_parquet(RAW_2TO3_PQ)
    wa = pd.read_parquet(WAVE_A_PQ)
    wb = pd.read_parquet(WAVE_B_PQ)
    wc = pd.read_parquet(WAVE_C_PQ)

    if cutoff_date is None:
        assert len(raw_all) == 10848, f"Expected 10848 raw rows, got {len(raw_all)}"
        data_as_of_date = str(raw_all["exit_dt_cc"].max())
        assert data_as_of_date == DATA_AS_OF_EXPECTED, f"data_as_of_date mismatch: {data_as_of_date}"
    else:
        raw_all = raw_all[(raw_all["buy_date"] <= cutoff_date) & (raw_all["exit_dt_cc"] <= cutoff_date)].copy()
        data_as_of_date = str(raw_all["buy_date"].max())

    base = raw_all[raw_all["buyable_open"] & (~raw_all["prev_is_yizi"]) & (~raw_all["has_tox_90d"])].copy()
    wc_cols = [c for c in wc.columns if c not in ("code", "buy_date") and c not in base.columns]
    df = (
        base.merge(wa, on=["code", "buy_date"], how="inner")
        .merge(wb, on=["code", "buy_date"], how="inner")
        .merge(wc[["code", "buy_date"] + wc_cols], on=["code", "buy_date"], how="inner")
    )
    if cutoff_date is None:
        assert len(df) == 6070, f"Expected 6070 clean rows, got {len(df)}"

    # 三行硬代码校验: 单位除数 + 时间锚点 < buy_date 09:25:00 + 行列极值
    assert 5.0 < float(df["prev_close"].median()) < 50.0, "prev_close unit check failed"
    assert abs(float(df["ret_opn_cc"].median())) < 0.25, "ret_opn_cc decimal check failed"
    assert (df["sig_date"] < df["buy_date"]).all(), "Time anchor sig_date < buy_date 09:25:00 failed"
    assert 10.0 < float(df["d2_real_turn"].median()) < 40.0 and (df["d2_real_turn"].dropna().between(0.0, 2000.0)).all(), "d2_real_turn extreme check failed"

    da, b5m = load_daily_and_5m(cutoff_date)
    cs = compute_causal_raw_signals(da, cutoff_date)

    # 覆盖全部因果重算列，确保截断实验真实重算滚动HHI/Elo/新词/脉冲/CSRC/尾盘/D1一字
    df["b01_hhi_low_q25"] = [cs["rec_hhi"].get(sd, 0) for sd in df["sig_date"]]
    df["d2_own_new_term"] = [cs["rec_own"].get((sd, str(c6).zfill(6)), False) for sd, c6 in zip(df["sig_date"], df["code"])]
    df["d1_is_dying_pulse"] = [cs["rec_dying"].get((d1, str(c6).zfill(6)), False) for d1, c6 in zip(df["d1_date"], df["code"])]
    df["d1_is_yizi"] = [cs["yizi_map"].get((d1, str(c6).zfill(6)), False) for d1, c6 in zip(df["d1_date"], df["code"])]
    df["d2_seal_sec_causal"] = [cs["tape_sec"].get((sd, str(c6).zfill(6)), None) for sd, c6 in zip(df["sig_date"], df["code"])]

    csrc_by_c6 = cs["csrc_by_c6"]
    def _csrc(c6, sd):
        for s0, e0, ind in csrc_by_c6.get(c6, []):
            if s0 <= sd <= e0:
                return ind
        return "UNK"

    ht_mask = df["plate"].astype(str).str.contains(HARD_TECH_RE, regex=True).to_numpy()
    ma_mask = (df["notice_hard"].fillna(False) | df["d2_is_ma"].fillna(False)).to_numpy()
    df["is_pure_outsider_causal"] = [
        bool(h and (_csrc(str(c6).zfill(6), str(sd)) in CSRC_PURE_OUTSIDER) and (not m))
        for h, c6, sd, m in zip(ht_mask, df["code"], df["sig_date"], ma_mask)
    ]
    df["elo_ice_causal"] = [
        int(cs["rec_elo_p"].get((sd, str(c6).zfill(6)), (0, 100.0))[1] < 95.0 or cs["rec_elo_s"].get((sd, str(c6).zfill(6)), 100.0) <= 95.0)
        for sd, c6 in zip(df["sig_date"], df["code"])
    ]

    gated = df[
        df["buyable_open"] & (~df["prev_is_yizi"]) & (~df["has_tox_90d"]) & (~df["has_reg_10d"])
        & df["open_pct"].between(-0.065, 0.025) & (df["plate_sz"] < 15)
    ].copy().reset_index(drop=True)

    rv2, edv2, ehv2 = sim_v2_exit_all(gated, da, b5m, cutoff_date)
    gated["ret_v2"] = rv2
    gated["ed_v2"] = edv2
    gated["eh_v2"] = ehv2
    return raw_all, df, gated, data_as_of_date


def compute_v10_components(d: pd.DataFrame) -> np.ndarray:
    elo_ice = (d["a22_elo_ice_lt95"] == 1) | (d["d2_s_elo"] <= 95)
    w1_frag = ((d["c15_w1_day1_3"] == 1) | (d["c02_w1_fresh_20d_lt4_ge3"] == 1)) & (~elo_ice)
    w2_reb = (d["c21_w2_reb_20d_ge6"] == 1) | (d["c22_w2_reb_30d_ge6"] == 1)
    mid_warm = d["plate_rk_noev"].between(3, 7) | d["plate_sz"].between(2, 6)
    hot_crowd = ((d["plate_rk_noev"] <= 2) & (d["plate_sz"] >= 7)) | (d["plate_sz"] >= 12)
    both_low = (d["mkt_p12_prev"] < 0.18) & (d["mkt_p23_prev"] < 0.28)
    d2_weak_late = (d["d2_open_cnt_tape"] >= 1) & ((d["d2_seal_sec"].fillna(0) >= 1800) | (d["d2_seal_amt_ratio"].fillna(1) < 0.05))
    d2_fast_zero = (d["d2_open_cnt_tape"] == 0) & (d["d2_seal_sec"].fillna(99999) <= 300)

    comp = np.zeros((len(d), 14), dtype=float)
    comp[:, 0] = np.where(d["b01_hhi_low_q25"] == 1, 6.0, np.where(d["raw_top1_share"] >= 0.30, -10.0, 0.0))
    comp[:, 1] = np.where(both_low, 8.0, np.where(d["mkt_p23_prev"] < 0.28, 5.0, 0.0))
    comp[:, 2] = np.where(d["mkt_maxb_prev"] <= 3, 6.0, 0.0)
    comp[:, 3] = np.where(hot_crowd, -10.0, np.where(mid_warm, 5.0, 0.0))
    comp[:, 4] = np.where(elo_ice, 8.0, 0.0)
    comp[:, 5] = np.where(w1_frag, -16.0, np.where(w2_reb, 5.0, 0.0))
    comp[:, 6] = np.where(d["plate_3b_cnt_sd"] >= 1, -8.0, 0.0)
    comp[:, 7] = np.where(d["xq_cnt_tot"] == 0, 0.0, np.where(d["xq_cnt_tot"] >= 4, -18.0, -10.0))
    comp[:, 8] = np.where(d["ir_has_20d"] == 1, -10.0, 0.0)
    comp[:, 9] = np.where(d["d2_low_pct"] <= -0.02, 6.0, 0.0)
    comp[:, 10] = np.where(d["d2_seal_amt_ratio"].fillna(0) >= 0.25, -16.0, np.where(d2_fast_zero, -8.0, np.where(d2_weak_late, 6.0, 0.0)))
    comp[:, 11] = np.where(d["pos_20d_d0"].fillna(0.5) <= 0.40, 6.0, 0.0)
    comp[:, 12] = np.where(d["d2_real_turn"].fillna(30.0) < 15.0, -8.0, np.where((d["lock_top10"].fillna(0) >= 50.0) & d["d2_real_turn"].fillna(0).between(25.0, 65.0), 8.0, 0.0))
    comp[:, 13] = np.where(d["open_pct"] < 0.0, 5.0, 0.0)
    return comp


def compute_v20_components(d: pd.DataFrame) -> np.ndarray:
    """V2.0_cand 18项纯正交打分矩阵 (底分60, 标准>=90, 高严>=96)"""
    elo_ice = d["elo_ice_causal"].to_numpy() == 1
    mid_warm = d["plate_rk_noev"].between(3, 7) | d["plate_sz"].between(2, 6)
    hot_crowd = ((d["plate_rk_noev"] <= 2) & (d["plate_sz"] >= 7)) | (d["plate_sz"] >= 12)
    both_low = (d["mkt_p12_prev"] < 0.18) & (d["mkt_p23_prev"] < 0.28)
    d2_weak_late = (d["d2_open_cnt_tape"] >= 1) & ((d["d2_seal_sec"].fillna(0) >= 1800) | (d["d2_seal_amt_ratio"].fillna(1) < 0.05))
    d2_fast_zero = (d["d2_open_cnt_tape"] == 0) & (d["d2_seal_sec"].fillna(99999) <= 300)

    comp = np.zeros((len(d), 18), dtype=float)
    comp[:, 0] = np.where(d["b01_hhi_low_q25"] == 1, 6.0, np.where(d["raw_top1_share"] >= 0.30, -10.0, 0.0))
    comp[:, 1] = np.where(both_low, 8.0, np.where(d["mkt_p23_prev"] < 0.28, 5.0, 0.0))
    comp[:, 2] = np.where(d["mkt_maxb_prev"] <= 3, 6.0, 0.0)
    comp[:, 3] = np.where(hot_crowd, -10.0, np.where(mid_warm, 5.0, 0.0))
    comp[:, 4] = np.where(elo_ice, 8.0, 0.0)
    comp[:, 5] = np.where(d["plate_3b_cnt_sd"] >= 1, -8.0, 0.0)
    comp[:, 6] = np.where(d["xq_cnt_tot"] == 0, 0.0, np.where(d["xq_cnt_tot"] >= 4, -18.0, -10.0))
    comp[:, 7] = np.where(d["ir_has_20d"] == 1, -10.0, 0.0)
    comp[:, 8] = np.where(d["d2_low_pct"] <= -0.02, 6.0, 0.0)
    comp[:, 9] = np.where(d["d2_seal_amt_ratio"].fillna(0) >= 0.25, -16.0, np.where(d2_fast_zero, -8.0, np.where(d2_weak_late, 6.0, 0.0)))
    comp[:, 10] = np.where(d["pos_20d_d0"].fillna(0.5) <= 0.40, 6.0, 0.0)
    comp[:, 11] = np.where(
        d["d2_real_turn"].fillna(30.0) < 15.0, -8.0,
        np.where((d["lock_top10"].fillna(0) >= 50.0) & d["d2_real_turn"].fillna(0).between(25.0, 65.0), 8.0,
        np.where((d["lock_top10"].fillna(0) >= 50.0) & d["d2_real_turn"].fillna(0).between(15.0, 24.9999), 5.0, 0.0))
    )
    comp[:, 12] = np.where(d["open_pct"] < 0.0, 5.0, 0.0)
    # U1..U5 跨策略互学正交增量
    comp[:, 13] = np.where(d["is_pure_outsider_causal"].to_numpy(), 4.0, 0.0)
    comp[:, 14] = np.where(d["d2_own_new_term"].to_numpy(), 4.0, 0.0)
    comp[:, 15] = np.where(d["d1_is_dying_pulse"].to_numpy(), -8.0, 0.0)
    comp[:, 16] = np.where(d["d2_seal_sec_causal"].fillna(-1.0) >= 12600.0, -6.0, 0.0)
    comp[:, 17] = np.where(d["d1_is_yizi"].to_numpy(), -6.0, 0.0)
    return comp


def sim_single_slot(sub: pd.DataFrame, sc_col: str, rcol: str, ecol: str, hcol: str) -> pd.DataFrame:
    if sub.empty:
        return pd.DataFrame()
    srt = sub.sort_values(["buy_date", sc_col, "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True])
    taken, free_dt, free_hh = [], "", 0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)
        if (not free_dt) or (bd > free_dt) or (bd == free_dt and 925 > free_hh):
            assert bool(r.buyable_open) and (not bool(r.prev_is_yizi)), f"Yizi buy violation: {r.code} {bd}"
            bp = round(float(r.prev_close) * (1.0 + float(r.open_pct)), 2)
            nr = float(getattr(r, rcol))
            ep = round(bp * (1.0 + nr) / (1.0 - FEE_ROUNDTRIP), 2)
            ed, eh = str(getattr(r, ecol)), int(getattr(r, hcol))
            taken.append({
                "code": str(r.code).zfill(6), "name": str(r.name), "buy_date": bd, "buy_hhmm": 925,
                "buy_price": bp, "exit_date": ed, "exit_hhmm": eh, "exit_price": ep,
                "net_ret": nr, "score": int(round(float(getattr(r, sc_col)))),
                "open_pct": round(float(r.open_pct), 4), "sealed_3b": bool(r.sealed_3b),
                "plate": str(r.plate), "plate_sz": int(r.plate_sz),
            })
            free_dt, free_hh = ed, eh
    out = pd.DataFrame(taken)
    if not out.empty:
        assert (out["exit_date"] > out["buy_date"]).all(), "T+0 violation!"
        for i in range(1, len(out)):
            p, c = out.iloc[i - 1], out.iloc[i]
            assert (c["buy_date"] > p["exit_date"]) or (c["buy_date"] == p["exit_date"] and c["buy_hhmm"] > p["exit_hhmm"]), "Overlap violation!"
    return out


def sim_two_half_slots(sub: pd.DataFrame, sc_col: str = "score", rcol: str = "ret_v2", ecol: str = "ed_v2", hcol: str = "eh_v2") -> tuple:
    if sub.empty:
        return pd.DataFrame(), 1.0, 0.0
    sort_cols = ["buy_date"] + (["priority"] if "priority" in sub.columns else []) + (["buy_hhmm"] if "buy_hhmm" in sub.columns else []) + [sc_col, "open_pct", "plate_sz", "code"]
    asc = [True] * len(sort_cols)
    asc[sort_cols.index(sc_col)] = False
    srt = sub.sort_values(sort_cols, ascending=asc)
    cap, fdt, fhh, pk, mdd, taken, used = [0.5, 0.5], ["", ""], [0, 0], 1.0, 0.0, [], set()
    for r in srt.itertuples(index=False):
        bd, c6 = str(r.buy_date), str(r.code).zfill(6)
        bh = int(getattr(r, "buy_hhmm", 925))
        if (bd, c6) in used:
            continue
        chosen = 0 if (fdt[0] == "" or bd > fdt[0] or (bd == fdt[0] and bh > fhh[0])) else (1 if (fdt[1] == "" or bd > fdt[1] or (bd == fdt[1] and bh > fhh[1])) else -1)
        if chosen < 0:
            continue
        used.add((bd, c6))
        ret = float(getattr(r, rcol if hasattr(r, rcol) else "net_ret"))
        ed = str(getattr(r, ecol if hasattr(r, ecol) else "exit_date"))
        eh = int(getattr(r, hcol if hasattr(r, hcol) else "exit_hhmm"))
        fdt[chosen], fhh[chosen] = ed, eh
        cap[chosen] *= 1.0 + ret
        tot = cap[0] + cap[1]
        pk = max(pk, tot)
        mdd = max(mdd, (pk - tot) / pk)
        taken.append({"buy_date": bd, "exit_date": ed, "code": c6, "net_ret": ret})
    return pd.DataFrame(taken), float(cap[0] + cap[1]), float(mdd * 100.0)


def calc_nav_cap10m(rr: np.ndarray) -> dict:
    n = len(rr)
    if n == 0:
        return {"trades": 0, "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0, "nav": 1.0, "ret_pct": 0.0, "max_dd_pct": 0.0, "cap10m_mult": 1.0, "cap10m_ret_pct": 0.0}
    w, l = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nc = np.cumprod(1.0 + rr)
    pk = np.maximum.accumulate(np.insert(nc, 0, 1.0))[1:]
    mdd = float(np.max((pk - nc) / pk) * 100.0)
    cap = 1000.0
    for x in rr:
        cap += min(cap, 1000.0) * float(x)
    return {
        "trades": int(n), "win_rate_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_ret_pct": round(float(rr.mean() * 100.0), 2), "nav": round(float(nc[-1]), 2),
        "ret_pct": round((float(nc[-1]) - 1.0) * 100.0, 2), "max_dd_pct": round(mdd, 2),
        "cap10m_mult": round(cap / 1000.0, 2), "cap10m_ret_pct": round((cap / 1000.0 - 1.0) * 100.0, 2),
    }


def calc_window_metrics(sub_raw: pd.DataFrame, sub_slot: pd.DataFrame, csi_pct: float, rcol: str, ecol: str, hcol: str) -> dict:
    if sub_slot.empty:
        return {
            "raw_n": int(len(sub_raw)), "single_n": 0, "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0,
            "single_nav": 1.0, "half2_n": 0, "half2_nav": 1.0, "half2_mdd_pct": 0.0, "eq_nav": 1.0,
            "trim3_nav": 1.0, "trim5_nav": 1.0, "max_dd_pct": 0.0, "cap10m_simple_profit_wan": 0.0,
            "cap10m_capped_mult": 1.0, "csi300_pct": round(csi_pct, 2), "excess_slot_pp": round(-csi_pct, 2),
        }
    rr = sub_slot["net_ret"].to_numpy(dtype=float)
    m0 = calc_nav_cap10m(rr)
    ex3 = float(np.prod(1.0 + np.sort(rr)[:-3])) if len(rr) > 3 else 1.0
    ex5 = float(np.prod(1.0 + np.sort(rr)[:-5])) if len(rr) > 5 else 1.0
    ew = float(np.prod(1.0 + sub_raw.groupby("buy_date")[rcol].mean().sort_index().to_numpy())) if len(sub_raw) else 1.0
    h2_df, h2_nav, h2_mdd = sim_two_half_slots(sub_raw, "score", rcol, ecol, hcol)
    return {
        "raw_n": int(len(sub_raw)), "single_n": m0["trades"], "win_rate_pct": m0["win_rate_pct"], "plr": m0["plr"],
        "mean_ret_pct": m0["mean_ret_pct"], "single_nav": m0["nav"], "half2_n": int(len(h2_df)),
        "half2_nav": round(h2_nav, 2), "half2_mdd_pct": round(h2_mdd, 2), "eq_nav": round(ew, 2),
        "trim3_nav": round(ex3, 2), "trim5_nav": round(ex5, 2), "max_dd_pct": m0["max_dd_pct"],
        "cap10m_simple_profit_wan": round(float(rr.sum() * 1000.0), 1), "cap10m_capped_mult": m0["cap10m_mult"],
        "csi300_pct": round(csi_pct, 2), "excess_slot_pp": round((m0["nav"] - 1.0) * 100.0 - csi_pct, 2),
    }


def cscv_pbo_eval(R: np.ndarray, names: list, n_groups: int) -> dict:
    n_days = R.shape[0]
    gs = n_days // n_groups
    gidx = [list(range(i * gs, (i + 1) * gs if i < n_groups - 1 else n_days)) for i in range(n_groups)]
    combos = list(itertools.combinations(range(n_groups), n_groups // 2))
    omegas, logits = [], []
    for te in combos:
        tri = [x for k in range(n_groups) if k not in te for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = R[tri], R[tei]
        st = np.where(rt.std(0, ddof=1) > 1e-12, rt.mean(0) / rt.std(0, ddof=1), 0.0)
        se = np.where(re_.std(0, ddof=1) > 1e-12, re_.mean(0) / re_.std(0, ddof=1), 0.0)
        b = int(np.argmax(st))
        rk = float(np.mean(se > se[b]))
        omegas.append(rk)
        w = max(1e-4, min(1.0 - 1e-4, rk))
        logits.append(math.log(w / (1.0 - w)))
    return {"n_groups": n_groups, "n_combos": len(combos), "pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2), "mean_rank_oos": round(float(np.mean(omegas)), 4), "logits_mean": round(float(np.mean(logits)), 4)}


def run_8tests_audit(led_5y: pd.DataFrame, gated_5y: pd.DataFrame, comp_5y: np.ndarray, base_5y_pool: pd.DataFrame,
                       sh300: dict, t_days: list, sc_col: str, th_val: int, rcol: str, ecol: str, hcol: str,
                       base_pts: int, fac_names: list, run_lofo: bool = True) -> dict:
    all_dates = sorted(sh300.keys())
    day_idx = {d: i for i, d in enumerate(t_days)}

    def bench_ret(bd: str, ed: str) -> float:
        prevs = [d for d in all_dates if d < bd]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dates[0]]
        p1 = sh300.get(ed, sh300[all_dates[-1]])
        return float(p1 / p0 - 1.0)

    n = len(led_5y)
    rr = led_5y["net_ret"].to_numpy(dtype=float)
    ex = np.array([float(r.net_ret) - bench_ret(r.buy_date, r.exit_date) for r in led_5y.itertuples(index=False)])
    sr_tr = float(ex.mean() / ex.std(ddof=1)) if n > 1 else 0.0
    t_tr = float(sr_tr * np.sqrt(n))

    d_map = {d: 0.0 for d in t_days}
    for r in led_5y.itertuples(index=False):
        if r.exit_date in d_map:
            d_map[r.exit_date] += float(r.net_ret)
    d_arr = np.array([d_map[d] for d in t_days], dtype=float)
    sr_d = float(d_arr.mean() / d_arr.std(ddof=1))
    t_d = float(sr_d * np.sqrt(len(d_arr)))

    skew = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    kurt = float(stats.kurtosis(ex, fisher=False, bias=False)) if n > 3 else 3.0
    gamma = 0.5772156649
    dsr_out = {}
    for M in (30, 150):
        sr0 = (1.0 / np.sqrt(max(n - 1, 1))) * ((1.0 - gamma) * stats.norm.ppf(1.0 - 1.0 / M) + gamma * stats.norm.ppf(1.0 - 1.0 / (M * np.e)))
        denom = np.sqrt(max(1e-12, 1.0 - skew * sr_tr + ((kurt - 1.0) / 4.0) * (sr_tr ** 2)))
        dsr_out[f"M{M}"] = round(float(stats.norm.cdf((sr_tr - sr0) * np.sqrt(max(n - 1, 1)) / denom)), 4)

    # Test 2: Monkey 5000 on canonical 5Y buyable pool
    pool_by_dt = {str(dt_s): grp["ret_opn_cc"].to_numpy(dtype=float) for dt_s, grp in base_5y_pool.groupby("buy_date")}
    cands = [pool_by_dt.get(str(r.buy_date), np.array([float(r.net_ret)])) for r in led_5y.itertuples(index=False)]
    rng = np.random.default_rng(20261117)
    mat = np.zeros((n, 5000), dtype=float)
    for i, c_arr in enumerate(cands):
        mat[i, :] = c_arr[rng.integers(0, len(c_arr), size=5000)]
    sim_means = mat.mean(axis=0)
    monkey_p = float((np.sum(sim_means >= float(rr.mean())) + 1) / 5001)

    # Test 3: +-20% MC 200x, Neighborhood 86..98, and true LOFO
    mc_navs, mc_wrs, mc_ns, mc_ex3s = [], [], [], []
    for _ in range(200):
        mult = rng.uniform(0.80, 1.20, size=comp_5y.shape[1])
        scp = float(base_pts) + comp_5y @ mult
        subp = gated_5y[scp >= th_val].copy(); subp["score_tmp"] = scp[scp >= th_val]
        lp = sim_single_slot(subp, "score_tmp", rcol, ecol, hcol)
        pr = lp["net_ret"].to_numpy(dtype=float) if not lp.empty else np.array([])
        mc_ns.append(len(pr)); mc_navs.append(float(np.prod(1.0 + pr)) if len(pr) else 1.0)
        mc_wrs.append(float((pr > 0).mean() * 100.0) if len(pr) else 0.0)
        mc_ex3s.append(float(np.prod(1.0 + np.sort(pr)[:-3])) if len(pr) > 3 else 1.0)

    neigh = {}
    for th in [86, 88, 90, 92, 94, 96, 98]:
        sn = gated_5y[gated_5y[sc_col] >= th]
        ln = sim_single_slot(sn, sc_col, rcol, ecol, hcol)
        neigh[f"th_{th}"] = calc_nav_cap10m(ln["net_ret"].to_numpy(dtype=float) if not ln.empty else np.array([]))

    lofo = {}
    if run_lofo:
        for j, fn in enumerate(fac_names):
            sc_l = float(base_pts) + comp_5y.sum(axis=1) - comp_5y[:, j]
            sl_df = gated_5y[sc_l >= th_val].copy(); sl_df["score_tmp"] = sc_l[sc_l >= th_val]
            ll = sim_single_slot(sl_df, "score_tmp", rcol, ecol, hcol)
            lofo[fn] = calc_nav_cap10m(ll["net_ret"].to_numpy(dtype=float) if not ll.empty else np.array([]))

    # Test 4: CSCV PBO (S=8 & S=10)
    R_q = np.zeros((len(t_days), 14))
    for r in led_5y.itertuples(index=False):
        i = day_idx.get(r.exit_date)
        if i is not None: R_q[i, 0] += r.net_ret
    for v in range(1, 14):
        qv = float(np.quantile(led_5y["score"], 0.05 + (v / 14.0) * 0.40))
        ts = sim_single_slot(gated_5y[gated_5y[sc_col] >= qv], sc_col, rcol, ecol, hcol)
        for r in ts.itertuples(index=False):
            i = day_idx.get(r.exit_date)
            if i is not None: R_q[i, v] += r.net_ret
    lad_ths = [88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98]
    R_lad = np.zeros((len(t_days), len(lad_ths)))
    for j, th in enumerate(lad_ths):
        ts = sim_single_slot(gated_5y[gated_5y[sc_col] >= th], sc_col, rcol, ecol, hcol)
        for r in ts.itertuples(index=False):
            i = day_idx.get(r.exit_date)
            if i is not None: R_lad[i, j] += r.net_ret

    # Test 5: Outlier removal
    idx_sorted = np.argsort(rr)[::-1]
    n5p = max(1, math.ceil(0.05 * n))
    q_s = pd.to_datetime(led_5y["buy_date"]).dt.to_period("Q").astype(str)
    best_q = str(led_5y.groupby(q_s)["net_ret"].sum().idxmax())
    m_best_q = calc_nav_cap10m(led_5y[q_s != best_q]["net_ret"].to_numpy(dtype=float))

    # Test 6: N_eff, rho_1, N_weeks, 5000x Bootstrap 5% CI
    n_weeks = len(set((d.year, d.isocalendar()[1]) for d in pd.to_datetime(led_5y["buy_date"])))
    rho_1 = float(np.corrcoef(ex[:-1], ex[1:])[0, 1]) if n > 2 else 0.0
    if math.isnan(rho_1): rho_1 = 0.0
    n_eff = float(n * (1.0 - rho_1) / (1.0 + rho_1)) if rho_1 > 0 else float(n)
    b_means = np.array([ex[rng.integers(0, n, size=n)].mean() for _ in range(5000)])

    # Test 7: Yearly 2022-2026 vs CSI300
    yearly = {}
    for yr in (2022, 2023, 2024, 2025, 2026):
        sd_y, ed_y = f"{yr}-01-01", (f"{yr}-12-31" if yr < 2026 else DATA_AS_OF_EXPECTED)
        sub_y = led_5y[(led_5y["buy_date"] >= sd_y) & (led_5y["buy_date"] <= ed_y)]
        my = calc_nav_cap10m(sub_y["net_ret"].to_numpy(dtype=float) if not sub_y.empty else np.array([]))
        cy = bench_ret(sd_y, ed_y) * 100.0
        my["csi300_ret_pct"] = round(cy, 2)
        my["excess_slot_pp"] = round(my["ret_pct"] - cy, 2)
        my["excess_cap10m_pp"] = round(my["cap10m_ret_pct"] - cy, 2)
        yearly[str(yr)] = my

    # Test 8: 2x/3x friction (-30bps/-60bps + -20bps) & Adverse Selection 15% + Hell mode
    csi_5y_pct = bench_ret("2021-11-16", DATA_AS_OF_EXPECTED) * 100.0
    df_w = led_5y[led_5y["net_ret"] > 0].sort_values("open_pct", ascending=False)
    n_drop_w = max(1, math.ceil(0.15 * len(df_w))) if len(df_w) else 0
    df_adv = pd.concat([df_w.iloc[n_drop_w:], led_5y[led_5y["net_ret"] <= 0]]).sort_values("buy_date")
    rr_adv = df_adv["net_ret"].to_numpy(dtype=float)
    rr_hell = rr_adv - 0.0030
    n_drop_all = max(1, math.ceil(0.15 * n))

    return {
        "test1_hlz_dsr": {"trades_N": n, "hlz_t_trade": round(t_tr, 2), "hlz_t_daily": round(t_d, 2), "sr_annual_daily": round(sr_d * np.sqrt(242), 3), "dsr_trade_prob": dsr_out},
        "test2_monkey_5000": {"monkey_p": round(monkey_p, 5), "actual_mean_pct": round(float(rr.mean() * 100.0), 2), "pool_mean_pct": round(float(sim_means.mean() * 100.0), 2)},
        "test3_perturbation_lofo": {
            "mc_pm20pct_200runs": {"mean_trades": round(float(np.mean(mc_ns)), 1), "mean_wr_pct": round(float(np.mean(mc_wrs)), 2), "nav_p10": round(float(np.percentile(mc_navs, 10)), 2), "nav_median": round(float(np.median(mc_navs)), 2), "nav_p90": round(float(np.percentile(mc_navs, 90)), 2), "ex3_median": round(float(np.median(mc_ex3s)), 2), "prob_gt_1x_pct": round(float((np.array(mc_navs) > 1.0).mean() * 100.0), 1)},
            "threshold_neighborhood_86_98": neigh, "lofo": lofo,
        },
        "test4_cscv_pbo": {"quantile_S8": cscv_pbo_eval(R_q, [f"q{i}" for i in range(14)], 8), "quantile_S10": cscv_pbo_eval(R_q, [f"q{i}" for i in range(14)], 10), "ladder_S8": cscv_pbo_eval(R_lad, [f"t{t}" for t in lad_ths], 8), "ladder_S10": cscv_pbo_eval(R_lad, [f"t{t}" for t in lad_ths], 10)},
        "test5_outliers": {"trim3": calc_nav_cap10m(np.delete(rr, idx_sorted[:3]) if n > 3 else rr), "trim5": calc_nav_cap10m(np.delete(rr, idx_sorted[:5]) if n > 5 else rr), "drop_top5pct": calc_nav_cap10m(np.delete(rr, idx_sorted[:n5p]) if n > n5p else rr), "drop_best_quarter": {"best_quarter": best_q, **m_best_q}},
        "test6_neff_bootstrap": {"N": n, "independent_weeks": n_weeks, "rho_1": round(rho_1, 4), "N_eff": round(n_eff, 2), "boot_5pct_ci_excess_pct": round(float(np.percentile(b_means, 5) * 100.0), 2), "boot_50pct_ci_excess_pct": round(float(np.percentile(b_means, 50) * 100.0), 2), "boot_significant": bool(np.percentile(b_means, 5) > 0)},
        "test7_yearly_2022_2026": yearly,
        "test8_friction_hell": {
            "slip_extra_20bps_nav": round(float(np.prod(1.0 + (rr - 0.0020))), 2),
            "slip_2x_extra_30bps": calc_nav_cap10m(rr - 0.0030),
            "slip_3x_extra_60bps": calc_nav_cap10m(rr - 0.0060),
            "drop_top15pct_all_trades_nav": round(float(np.prod(1.0 + np.sort(rr)[:-n_drop_all])), 2) if n > n_drop_all else 1.0,
            "adverse_selection_drop_top15pct_open_wins": calc_nav_cap10m(rr_adv),
            "hell_mode_adverse_plus_30bps": {**calc_nav_cap10m(rr_hell), "excess_cap10m_pp": round(calc_nav_cap10m(rr_hell)["cap10m_ret_pct"] - csi_5y_pct, 2)},
        },
    }


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return 0.0 if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def eval_portfolio_synergy(gated_5y: pd.DataFrame, csi: dict) -> dict:
    sys.path.insert(0, CLEAN_16_DIR)
    from synthesize_master_clean_20261116 import standardize_ledger, run_1slot as port_1slot

    b_high = standardize_ledger(f"{CLEAN_16_DIR}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴_V51", 1)
    b_3to4 = standardize_ledger(f"{CLEAN_16_DIR}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四_V34", 2)
    aux_pry = standardize_ledger(f"{CLEAN_16_DIR}/partC_aux/ledger_aux_pry_v10.csv", "超跌撬板_V10", 3)
    b_1to2 = standardize_ledger(f"{CLEAN_16_DIR}/partB_1to2/ledger_base_1to2_v18.csv", "一进二_V18", 4)
    base4 = pd.concat([b_high, b_3to4, aux_pry, b_1to2], ignore_index=True)

    def to_p(sub, tag, sc_col, rc, ec, hc):
        return pd.DataFrame({
            "buy_date": sub["buy_date"].astype(str), "exit_date": sub[ec].astype(str),
            "code": sub["code"].astype(str).str.zfill(6), "name": sub["name"].astype(str),
            "net_ret": sub[rc].astype(float), "score": sub[sc_col].astype(float),
            "buy_hhmm": 925, "exit_hhmm": sub[hc].astype(int), "strategy": tag, "priority": 5,
        })

    out = {}
    pools = [
        ("Base4", base4),
        ("Base4_plus_2to3_V10_std90_5th", pd.concat([base4, to_p(gated_5y[gated_5y["score_v1"] >= 90], "二进三_V10", "score_v1", "ret_opn_cc", "exit_dt_cc", "exit_hh_cc")], ignore_index=True)),
        ("Base4_plus_2to3_V20_std90_5th", pd.concat([base4, to_p(gated_5y[gated_5y["score_v2"] >= 90], "二进三_V20", "score_v2", "ret_v2", "ed_v2", "eh_v2")], ignore_index=True)),
        ("Base4_plus_2to3_V20_strict96_5th", pd.concat([base4, to_p(gated_5y[gated_5y["score_v2"] >= 96], "二进三_V20_96", "score_v2", "ret_v2", "ed_v2", "eh_v2")], ignore_index=True)),
    ]
    for pname, pl in pools:
        sl = port_1slot(pl)
        win_res = {}
        for wname, sdt, csi_p in [("5Y", "2021-11-15", csi["全五年(2021-11-16起)"][0]), ("3Y", "2023-11-16", csi["近三年(2023-11-16起)"][0]), ("2026", "2026-01-01", csi["2026全年"][0])]:
            sw = sl[sl["buy_date"] >= sdt]
            rr = sw["net_ret"].to_numpy(dtype=float) if not sw.empty else np.array([])
            m = calc_nav_cap10m(rr)
            m["excess_slot_pp"] = round(m["ret_pct"] - csi_p, 2)
            m["strategy_counts"] = sw["strategy"].value_counts().to_dict() if not sw.empty else {}
            win_res[wname] = m
        out[pname] = win_res
    return out


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    csi = json.load(open(CSI_CANON_JSON, encoding="utf-8"))
    sh300 = json.load(open(IDX_JSON, encoding="utf-8"))["sh000300"]
    t_days = sorted([d for d in sh300.keys() if CANON_5Y_START <= d <= DATA_AS_OF_EXPECTED])

    # 1. 全量前视 PIT 流程
    raw_all, df_all, gated_all, data_as_of_date = build_pit_dataset(cutoff_date=None)
    comp_v1_all = compute_v10_components(gated_all)
    comp_v2_all = compute_v20_components(gated_all)
    gated_all["score_v1"] = 58.0 + comp_v1_all.sum(axis=1)
    gated_all["score_v2"] = 60.0 + comp_v2_all.sum(axis=1)
    gated_all["score"] = gated_all["score_v2"]

    mask_5y = (gated_all["buy_date"] >= CANON_5Y_START).to_numpy()
    gated_5y = gated_all[mask_5y].copy().reset_index(drop=True)
    comp_v1_5y = comp_v1_all[mask_5y]
    comp_v2_5y = comp_v2_all[mask_5y]
    base_5y = df_all[df_all["buy_date"] >= CANON_5Y_START].copy()

    # 2. 导出升级版标准档 (>=90) 与高严档 (>=96) 5年逐笔台账
    led_v2_std_5y = sim_single_slot(gated_5y[gated_5y["score_v2"] >= 90], "score_v2", "ret_v2", "ed_v2", "eh_v2")
    led_v2_str_5y = sim_single_slot(gated_5y[gated_5y["score_v2"] >= 96], "score_v2", "ret_v2", "ed_v2", "eh_v2")
    led_v2_std_5y.to_csv(f"{OUT_DIR}/ledger_upg_2to3_std.csv", index=False, encoding="utf-8-sig")
    led_v2_str_5y.to_csv(f"{OUT_DIR}/ledger_upg_2to3_strict.csv", index=False, encoding="utf-8-sig")

    led_v2_std_full = sim_single_slot(gated_all[gated_all["score_v2"] >= 90], "score_v2", "ret_v2", "ed_v2", "eh_v2")
    led_v2_str_full = sim_single_slot(gated_all[gated_all["score_v2"] >= 96], "score_v2", "ret_v2", "ed_v2", "eh_v2")
    led_v1_std_5y = sim_single_slot(gated_5y[gated_5y["score_v1"] >= 90], "score_v1", "ret_opn_cc", "exit_dt_cc", "exit_hh_cc")
    led_v1_str_5y = sim_single_slot(gated_5y[gated_5y["score_v1"] >= 96], "score_v1", "ret_opn_cc", "exit_dt_cc", "exit_hh_cc")
    led_v1_std_full = sim_single_slot(gated_all[gated_all["score_v1"] >= 90], "score_v1", "ret_opn_cc", "exit_dt_cc", "exit_hh_cc")
    led_v1_str_full = sim_single_slot(gated_all[gated_all["score_v1"] >= 96], "score_v1", "ret_opn_cc", "exit_dt_cc", "exit_hh_cc")

    # 3. 物理截断零未来函数硬测试 (删去 >= 2025-01-01 全部日线/5m/KPL/CSRC/微盘后从头重算)
    _, _, trunc_gated, _ = build_pit_dataset(cutoff_date="2024-12-31")
    trunc_gated["score_v2"] = 60.0 + compute_v20_components(trunc_gated).sum(axis=1)
    trunc_check = {}
    for tier, th, full_led in [("std90", 90, led_v2_std_full), ("strict96", 96, led_v2_str_full)]:
        f24 = full_led[full_led["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        t_led = sim_single_slot(trunc_gated[trunc_gated["score_v2"] >= th], "score_v2", "ret_v2", "ed_v2", "eh_v2")
        t24 = t_led[t_led["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        assert len(f24) == len(t24), f"Trunc len mismatch {tier}: {len(f24)} vs {len(t24)}"
        assert (f24["buy_date"] == t24["buy_date"]).all() and (f24["exit_date"] == t24["exit_date"]).all()
        assert (f24["code"] == t24["code"]).all()
        diff_sc = float(np.max(np.abs(f24["score"].to_numpy() - t24["score"].to_numpy())))
        diff_ret = float(np.max(np.abs(f24["net_ret"].to_numpy() - t24["net_ret"].to_numpy())))
        assert diff_sc == 0.0 and diff_ret == 0.0, f"Trunc diff != 0: score={diff_sc}, ret={diff_ret}"
        trunc_check[tier] = {"trades_2021_2024": int(len(t24)), "max_abs_diff_score": diff_sc, "max_abs_diff_ret": diff_ret}

    # 4. D15 多窗口对比 (V1.0 vs V2.0_cand, Std90 & Strict96)
    win_specs = [
        ("IS_21_23", "2021-01-01", "2023-12-31", -34.16, False),
        ("OOS_24_26", "2024-01-01", "2026-11-16", csi["近三年(2024-01-01起)"][0], False),
        ("全五年_20211116起", "2021-11-16", "2026-11-16", csi["全五年(2021-11-16起)"][0], True),
        ("近三年_20231116起", "2023-11-16", "2026-11-16", csi["近三年(2023-11-16起)"][0], True),
        ("2026全年", "2026-01-01", "2026-11-16", csi["2026全年"][0], True),
        ("2026年7月起", "2026-07-01", "2026-11-16", csi["2026年7月以来"][0], True),
        ("2026年10月起", "2026-10-01", "2026-11-16", csi["2026年10月以来"][0], True),
    ]
    windows_cmp, yearly_cmp = {}, {}
    specs = [
        ("V10_std90", "score_v1", 90, "ret_opn_cc", "exit_dt_cc", "exit_hh_cc", led_v1_std_5y, led_v1_std_full),
        ("V10_strict96", "score_v1", 96, "ret_opn_cc", "exit_dt_cc", "exit_hh_cc", led_v1_str_5y, led_v1_str_full),
        ("V20_std90", "score_v2", 90, "ret_v2", "ed_v2", "eh_v2", led_v2_std_5y, led_v2_std_full),
        ("V20_strict96", "score_v2", 96, "ret_v2", "ed_v2", "eh_v2", led_v2_str_5y, led_v2_str_full),
    ]
    for sname, scc, th, rc, ec, hc, l5, lf in specs:
        windows_cmp[sname] = {}
        for wn, sdt, edt, csip, u5 in win_specs:
            sa = gated_all[(gated_all[scc] >= th) & (gated_all["buy_date"] >= sdt) & (gated_all["buy_date"] <= edt)].copy()
            sa["score"] = sa[scc]
            ws = (l5 if u5 else lf)
            ws = ws[(ws["buy_date"] >= sdt) & (ws["buy_date"] <= edt)]
            windows_cmp[sname][wn] = calc_window_metrics(sa, ws, csip, rc, ec, hc)
        yearly_cmp[sname] = {}
        for y in range(2021, 2027):
            ys = str(y)
            ws = lf[lf["buy_date"].str.startswith(ys)]
            rr = ws["net_ret"].to_numpy(dtype=float) if not ws.empty else np.array([])
            yearly_cmp[sname][ys] = calc_nav_cap10m(rr)

    # 5. 八项防过拟合全维度体检 (V1.0 vs V2.0_cand)
    v1_names = [f"F{i}" for i in range(14)]
    audit_cmp = {
        "V10_std90": run_8tests_audit(led_v1_std_5y, gated_5y, comp_v1_5y, base_5y, sh300, t_days, "score_v1", 90, "ret_opn_cc", "exit_dt_cc", "exit_hh_cc", 58, v1_names, False),
        "V10_strict96": run_8tests_audit(led_v1_str_5y, gated_5y, comp_v1_5y, base_5y, sh300, t_days, "score_v1", 96, "ret_opn_cc", "exit_dt_cc", "exit_hh_cc", 58, v1_names, False),
        "V20_std90": run_8tests_audit(led_v2_std_5y, gated_5y, comp_v2_5y, base_5y, sh300, t_days, "score_v2", 90, "ret_v2", "ed_v2", "eh_v2", 60, FACTOR_NAMES_V2, True),
        "V20_strict96": run_8tests_audit(led_v2_str_5y, gated_5y, comp_v2_5y, base_5y, sh300, t_days, "score_v2", 96, "ret_v2", "ed_v2", "eh_v2", 60, FACTOR_NAMES_V2, False),
    }

    # 6. 新增盘活空仓日个股案例 (V1.0 处于空仓且V2.0_cand独立买到的新增交易)
    v1_keys = set(zip(led_v1_std_5y["buy_date"], led_v1_std_5y["code"]))
    v1_hold_intervals = list(zip(led_v1_std_5y["buy_date"], led_v1_std_5y["exit_date"], led_v1_std_5y["exit_hhmm"]))
    def _v1_was_cash(bd: str) -> bool:
        for vb, ve, vh in v1_hold_intervals:
            if vb <= bd < ve or (bd == ve and 925 <= vh):
                return False
        return True

    new_vs_v1 = led_v2_std_5y[[(bd, cd) not in v1_keys for bd, cd in zip(led_v2_std_5y["buy_date"], led_v2_std_5y["code"])]].copy()
    empty_day_unlocks = new_vs_v1[new_vs_v1["buy_date"].apply(_v1_was_cash)].copy()
    cols_ex = ["buy_date", "exit_date", "exit_hhmm", "code", "name", "score", "open_pct", "net_ret", "sealed_3b", "plate"]

    summary = sanitize_json({
        "meta": {
            "strategy_name": "二进三_V2.0_cand(互学升级独立版)",
            "baseline_name": "二进三_V1.0(原版)",
            "data_as_of_date": data_as_of_date,
            "canon_5y_window": f"{CANON_5Y_START} ~ {data_as_of_date}",
            "is_window": "2021-01-04 ~ 2023-12-31",
            "oos_window": f"2024-01-01 ~ {data_as_of_date}",
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "rule_and_scorecard_diff": {
            "base_points_v1_to_v2": [58, 60],
            "thresholds": {"std": 90, "strict": 96},
            "hard_gates_0925_unchanged": [
                "沪深主板10cm非ST真连续2天2板",
                "D2二板非一字且D3开盘非一字涨停",
                "D3 09:25开盘区间 [-6.5%, +2.5%]",
                "无近90日毒丸公告且无近10日监管风险公告",
                "主概念涨停家数 plate_sz < 15",
            ],
            "removed_factors": ["P2_3_一波脆弱vs二波回流(-16/+5): 2to3波段周期反转拖累且与龙头属性冲突"],
            "upgraded_factors": ["P4_4_前十大锁仓>=50%&换手分段: 新增[15%,25%)中温和锁仓换手(+5), 保留[25%,65%](+8)与<15%(-8)"],
            "added_positive_factors": [
                "U1_传统行业跨界硬科技暗牌(+4): 反向吸收1进2外行扣分项，2进3跨界带来增量博弈弹性",
                "U2_自身细分概念15日新词破冰(+4): 吸收1进2细分题材破冰因子",
            ],
            "added_poison_deductions": [
                "U3_退潮一日游脉冲排雷(-8): 吸收1进2 Layer2，板块近3~8日高潮但D1无连板龙头",
                "U4_D2尾盘14:30后烂板偷袭(-6): DF003尾盘偷袭弱承接扣分",
                "U5_D1首板一字透支(-6): D1一字板压缩D3接力空间",
            ],
            "exit_upgrade": "未封3板取消D4竞价<+0.5%割地板，持仓过早盘抛压至D4 15:00(若D4反包涨停则切入连板骑乘链，严格执行一字跌停/收盘精确跌停不可卖顺延); 封3板增加D4极高开>+9.2%非一字09:25止盈兑现，保留13:45护利与1次真阳免死",
        },
        "hard_asserts_and_truncation": {
            "yfinance_forbidden": True,
            "sqlite_readonly_uri": True,
            "unit_anchor_extreme_checks_passed": True,
            "t0_violations": 0,
            "overlap_violations": 0,
            "yizi_buy_violations": 0,
            "eod_dt_or_yizi_dt_sell_violations": 0,
            "truncation_cutoff_2024_12_31_zero_lookahead": trunc_check,
        },
        "windows_d15_comparison": windows_cmp,
        "yearly_comparison": yearly_cmp,
        "overfitting_8_tests_comparison": audit_cmp,
        "unlocked_empty_day_trades": {
            "total_new_trades_vs_v1_ledger": int(len(new_vs_v1)),
            "strict_empty_day_unlocks_n": int(len(empty_day_unlocks)),
            "empty_day_unlocks_wr_pct": round(float((empty_day_unlocks["net_ret"] > 0).mean() * 100.0), 2) if not empty_day_unlocks.empty else 0.0,
            "empty_day_unlocks_mean_pct": round(float(empty_day_unlocks["net_ret"].mean() * 100.0), 2) if not empty_day_unlocks.empty else 0.0,
            "empty_day_unlocks_comp_nav": round(float(np.prod(1.0 + empty_day_unlocks["net_ret"])), 2) if not empty_day_unlocks.empty else 1.0,
            "top8_empty_day_winners": empty_day_unlocks.sort_values("net_ret", ascending=False).head(8)[cols_ex].to_dict(orient="records"),
        },
        "portfolio_synergy_5th_priority": eval_portfolio_synergy(gated_5y, csi),
    })

    with open(f"{OUT_DIR}/summary_upg_2to3.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[PASS ALL HARD ASSERTS] Truncation 2021-2024 = {trunc_check} | elapsed={time.time()-t0:.1f}s")
    for k in ["V10_std90", "V20_std90", "V10_strict96", "V20_strict96"]:
        w5 = windows_cmp[k]["全五年_20211116起"]
        wi = windows_cmp[k]["IS_21_23"]
        wo = windows_cmp[k]["OOS_24_26"]
        t1 = audit_cmp[k]["test1_hlz_dsr"]
        print(f"  {k:13s} | IS:{wi['single_n']:2d}b/{wi['win_rate_pct']:4.1f}%/{wi['single_nav']:5.2f}x | OOS:{wo['single_n']:2d}b/{wo['win_rate_pct']:4.1f}%/{wo['single_nav']:5.2f}x | 5Y:{w5['single_n']:2d}b/{w5['win_rate_pct']:4.1f}%/1S={w5['single_nav']:6.2f}x/C10={w5['cap10m_capped_mult']:4.2f}x/T3={w5['trim3_nav']:5.2f}x/MDD={w5['max_dd_pct']:4.1f}%/t={t1['hlz_t_trade']}/DSR150={t1['dsr_trade_prob']['M150']}")


if __name__ == "__main__":
    main()
