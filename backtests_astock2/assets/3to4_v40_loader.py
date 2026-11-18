# -*- coding: utf-8 -*-
"""三进四 V4.0 题库共享 PIT 数据与台账加载器（单进程单例缓存）"""
import os
import sys
import pandas as pd

CUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_DIR = os.path.dirname(CUR_DIR)
UPG_DIR = os.path.join(SIM_DIR, "backtests_astock", "clean_3strategies_mutual_upgrade_20261117")
LEDGER_V40_CSV = os.path.join(UPG_DIR, "ledger_upg_3to4_std.csv")

for _p in (CUR_DIR, UPG_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import upgrade_3to4_pit as u34

_CACHE = None


def get_v40_bundle() -> dict:
    """加载三进四 V4.0 完整 PIT 候选表、打分、10:30 5m 撮合与官方台账。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    res = u34.run_causal_pipeline("2026-11-16", verbose=False)
    cdf = res["cand_df"].copy()
    elig = cdf["is_10cm_non_st"] & cdf["buyable_open"] & (~cdf["prev_is_yizi"])
    elig_cnt = cdf.loc[elig].groupby("buy_date")["code"].count().to_dict()
    cdf["b3_rival_cnt"] = [max(1, int(elig_cnt.get(str(d), 1))) for d in cdf["buy_date"]]
    res["cand_df"] = cdf

    ledger_df = pd.read_csv(LEDGER_V40_CSV, dtype={"code": str})
    ledger_df["code"] = ledger_df["code"].astype(str).str.zfill(6)
    ledger_map = {
        (str(r.buy_date), str(r.code)): {
            "code": str(r.code),
            "name": str(r.name),
            "buy_date": str(r.buy_date),
            "buy_hhmm": int(r.buy_hhmm),
            "buy_price": round(float(r.buy_price), 2),
            "exit_date": str(r.exit_date),
            "exit_hhmm": int(r.exit_hhmm),
            "exit_price": round(float(r.exit_price), 2),
            "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
            "score": int(round(float(r.score))),
        }
        for r in ledger_df.itertuples(index=False)
    }
    res["ledger_df"] = ledger_df
    res["ledger_map"] = ledger_map
    _CACHE = res
    return _CACHE


def csi300_ret_v40(start_dt: str, end_dt: str) -> float:
    b = get_v40_bundle()
    return u34._csi300_ret(b["csi_map"], b["all_csi_dts"], start_dt, end_dt)
