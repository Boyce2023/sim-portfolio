# -*- coding: utf-8 -*-
"""三进四 V4.1 题库共享 PIT 数据与台账加载器（单进程单例缓存，全量对齐 XF30_7f_ge1 与 ledger_3to4_xf30_std.csv）"""
import os
import pickle
import sys
import pandas as pd

CUR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM_DIR = os.path.dirname(CUR_DIR)
UPG_DIR = os.path.join(SIM_DIR, "backtests_astock", "clean_3strategies_mutual_upgrade_20261117")
F1_DIR = os.path.join(SIM_DIR, "backtests_astock", "exit_factors_v2_20261118", "f1_3to4")

PIT_CACHE_PKL = os.path.join(F1_DIR, "pit_exit_cache_full.pkl")
LEDGER_V41_CSV = os.path.join(F1_DIR, "ledger_3to4_xf30_std.csv")
LEDGER_V40_OLD_CSV = os.path.join(UPG_DIR, "ledger_upg_3to4_std.csv")

for _p in (CUR_DIR, UPG_DIR, F1_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import upgrade_3to4_pit as u34
import exit_factor_engine as efe

F7_KEYS = ["xf21_135", "xf03_20m", "xf28_35", "xf02", "xf07_new", "xf22", "xf23_reb20"]
F7_LABELS = {
    "xf21_135": "主概念动态Elo>=135过热",
    "xf03_20m": "前一日机构卖出>2000万",
    "xf28_35": "前一日成交额>3.5倍均量爆量",
    "xf02": "前一日一日游席位买入",
    "xf07_new": "持仓期新增个股监管",
    "xf22": "沪深300大跌",
    "xf23_reb20": "近10日高标断板反包率<20%冷区",
}

_CACHE = None


def _risk7_score(st: dict) -> int:
    return sum(int(bool(st.get(k))) for k in F7_KEYS)


def _rule_v41(st: dict, ctx: dict) -> dict:
    return {"tight_1345_thr": 0.070 if _risk7_score(st) >= 1 else 0.050}


def _load_ledger_map(csv_path: str) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(csv_path, dtype={"code": str})
    df["code"] = df["code"].astype(str).str.zfill(6)
    mp = {
        (str(r.buy_date), str(r.code)): {
            "code": str(r.code),
            "name": str(r.name),
            "buy_date": str(r.buy_date),
            "buy_hhmm": int(r.buy_hhmm),
            "buy_price": round(float(r.buy_price), 2),
            "exit_date": str(r.exit_date),
            "exit_hhmm": int(r.exit_hhmm),
            "exit_price": round(float(r.exit_price), 2),
            "net_ret_raw": float(r.net_ret),
            "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
            "score": int(round(float(r.score))),
        }
        for r in df.itertuples(index=False)
    }
    return df, mp


def get_v40_bundle() -> dict:
    """加载三进四 V4.1 完整 PIT 候选表、打分、10:30 5m 撮合、XF30 卖点仿真与官方台账。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    with open(PIT_CACHE_PKL, "rb") as f:
        cache = pickle.load(f)

    cdf = cache["cand_df"].copy()
    elig = cdf["is_10cm_non_st"] & cdf["buyable_open"] & (~cdf["prev_is_yizi"])
    elig_cnt = cdf.loc[elig].groupby("buy_date")["code"].count().to_dict()
    cdf["b3_rival_cnt"] = [max(1, int(elig_cnt.get(str(d), 1))) for d in cdf["buy_date"]]

    # 为所有盘中可触及买单（含未过线/未过骨架的强行挂单参考题）预计算持仓期 7 项风险因子状态
    orig_entries = cache["buy_entries"]
    tmp_entries = []
    for e in orig_entries:
        ne = dict(e)
        if ne["buy_px"] is not None:
            ne["skel"] = True
            ne["sc_v40"] = 999.0
        tmp_entries.append(ne)
    cache["buy_entries"] = tmp_entries
    states_all = efe.precompute_trade_day_states(cache, min_score=0.0)
    cache["buy_entries"] = orig_entries

    ledger_df, ledger_map = _load_ledger_map(LEDGER_V41_CSV)
    _, old_ledger_map = _load_ledger_map(LEDGER_V40_OLD_CSV)

    code_bars = cache["code_bars_ext"]
    p_1030 = []
    for e in orig_entries:
        if e["buy_px"] is None:
            p_1030.append(None)
            continue
        idx = e["idx"]
        c6 = e["code"]
        bd = e["buy_date"]
        cb = code_bars[c6]
        pos = e["pos"]
        st_map = states_all.get(idx, {})

        ex0, spx0, adj0, _, shh0, _ = efe.sim_exit_with_rule(e, cache, st_map, None)
        ex1, spx1, adj1, hb1, shh1, rsn1 = efe.sim_exit_with_rule(e, cache, st_map, _rule_v41)
        nr0 = (spx0 * adj0) / (e["buy_px"] * float(cb["adjf"][pos])) * (1.0 - efe.FEE_RATE) - 1.0
        nr1 = (spx1 * adj1) / (e["buy_px"] * float(cb["adjf"][pos])) * (1.0 - efe.FEE_RATE) - 1.0

        # 命中官方 V4.1 台账的实盘买单做硬校验并 100% 精确对齐台账字段
        lt = ledger_map.get((bd, c6))
        if lt is not None:
            assert ex1 == lt["exit_date"] and int(shh1) == lt["exit_hhmm"], (
                f"V4.1 exit mismatch {bd} {c6}: {(ex1, shh1)} vs {(lt['exit_date'], lt['exit_hhmm'])}"
            )
            assert abs(round(spx1, 2) - lt["exit_price"]) <= 0.01 and abs(nr1 - lt["net_ret_raw"]) <= 1e-4
            nr1 = lt["net_ret_raw"]
            spx1 = lt["exit_price"]
            ex1 = lt["exit_date"]
            shh1 = lt["exit_hhmm"]

        ex_pos = cb["date_to_pos"].get(ex1, pos)
        st_ex = st_map.get(ex_pos, {})
        hits = [F7_LABELS[k] for k in F7_KEYS if st_ex.get(k)]
        lt_old = old_ledger_map.get((bd, c6))
        v40_ret = lt_old["net_ret_raw"] if lt_old is not None else nr0
        v40_ex_d = lt_old["exit_date"] if lt_old is not None else ex0
        v40_ex_h = lt_old["exit_hhmm"] if lt_old is not None else int(shh0)
        v40_ex_p = lt_old["exit_price"] if lt_old is not None else round(spx0, 2)
        v41_improved = bool(
            (rsn1 == "c_1345_guard")
            and (len(hits) > 0)
            and ((ex1 != v40_ex_d) or (int(shh1) != int(v40_ex_h)) or (abs(nr1 - v40_ret) > 1e-5))
        )

        p_1030.append({
            "code": c6,
            "name": e["name"],
            "buy_date": bd,
            "buy_hhmm": int(e["buy_hhmm"]),
            "buy_price": round(float(e["buy_px"]), 2),
            "exit_date": ex1,
            "exit_hhmm": int(shh1),
            "exit_price": round(float(spx1), 2),
            "hold_bars": int(hb1),
            "net_ret": float(nr1),
            "exit_reason": rsn1,
            "v41_tight_triggered": bool(rsn1 == "c_1345_guard" and len(hits) > 0),
            "v41_improved": v41_improved,
            "v41_risk_hits": hits,
            "v40_ret_pct": round(float(v40_ret) * 100.0, 2),
            "v40_exit_date": v40_ex_d,
            "v40_exit_hhmm": int(v40_ex_h),
            "v40_exit_price": v40_ex_p,
        })

    _CACHE = {
        "cand_df": cdf,
        "code_bars": code_bars,
        "p_1030": p_1030,
        "csi_map": cache["csi_map"],
        "all_csi_dts": cache["all_csi_dts"],
        "ledger_df": ledger_df,
        "ledger_map": ledger_map,
    }
    return _CACHE


def csi300_ret_v40(start_dt: str, end_dt: str) -> float:
    b = get_v40_bundle()
    return u34._csi300_ret(b["csi_map"], b["all_csi_dts"], start_dt, end_dt)
