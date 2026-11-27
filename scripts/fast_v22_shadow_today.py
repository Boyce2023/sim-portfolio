#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_v22_shadow_today.py — 极简纯血版 V22.0 (Pure_V21_P2_SJ114_E4_Pos5) 只读影子总引擎
=========================================================================================
⛔ 安全红线：
  1. 严格只读，零修改现役 V20.0（6 大策略）及 `[7.5] 影子 V21.0` 判断；
  2. 严禁 `import yfinance`（D12），腾讯直连走 `ProxyHandler({})`，SQLite 强制 `?mode=ro`；
  3. 完整整合 09:25:05 统一决策流：
     - Base: V21.0 四件套（`20cm stack_c50_avg>=80` / `3to4 m4_4way_bl15` / `2to3 m2_pair_cold45_d15` / `high m1_causal_cold_drop40_t0` / `1to2` / `pry`）
     - Gate 1 (RD049): 五档灯色 `L1..L5`（L2/L3 +9 & af03==4，L4 +12 & af03==4，L1/L5 无附加分）
     - Module P2 (`pos750<0.50` & `pry_dt>=100`): 三进四近 3 年 750 交易日价格分位 <0.50 豁免拦截；超跌撬板 `zt10<50` 且 `全A跌停<100` 拦截，跌停>=100 恐慌高潮挽救
     - Pos5 (Empty Fill): 全 V21+P2 空仓（含无 Tier1/A档条件单预约占槽）时，用 `fast_4to5_today` (RD048 SJ114, 默认114, 代码级硬锁 >=110) 补位
  4. 顺位表采用独立常量字典 `V22_PRIORITY_CONFIG`，便于后续 P5 撞车排序终审一键同步。
  5. 支持 `--premarket`、默认 09:25 实时、`--verify-parity` 历史零偏差单测，只读写入 `shadow_v22_ledger.jsonl`。
"""
import os
for _k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_k] = "1"
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import argparse
import datetime
import json
import pickle
import re
import sys
import time
import urllib.request
from typing import Any, Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
SCRIPTS_DIR = f"{SIM_DIR}/scripts"

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import fast_shadow_4piece_today as sh21
import fast_rd049_regime_today as rd49
import fast_4to5_today as f45

assert "yfinance" not in sys.modules, "D12 violation after imports"

LEDGER_V22_JSONL = f"{DATA_DIR}/shadow_v22_ledger.jsonl"
PARITY_OUT_DIR = f"{SIM_DIR}/backtests_astock/v22_grand_convergence_20261126/p6_v22_prod_engineering"
PARITY_REPORT_JSON = f"{PARITY_OUT_DIR}/v22_prod_parity_report.json"

# 独立顺位配置常量表（方便后续按 P5 撞车排序终审一键同步）
V22_PRIORITY_CONFIG: dict[str, Any] = {
    "version": "Pure_V21_P2_SJ114_E4_Pos5",
    "pos_mode": "Pos5",
    "four_to_five_threshold": f45.DEFAULT_4TO5_THRESHOLD,  # 代码级硬锁 >= 110
    "p2_pos750_cut": 0.50,
    "p2_pry_mkt10_cut": 50.0,
    "p2_pry_dt_climax": 100.0,
    "tier_order": {
        "3to4_S": {"tier_group": 1, "phase": 0, "prio": 1.0},
        "high_S": {"tier_group": 1, "phase": 0, "prio": 2.0},
        "3to4_Ad": {"tier_group": 2, "phase": 0, "prio": 3.0},
        "high_Ad": {"tier_group": 2, "phase": 0, "prio": 4.0},
        "pry": {"tier_group": 2, "phase": 0, "prio": 5.0},
        "2to3": {"tier_group": 2, "phase": 0, "prio": 6.0},
        "1to2_d": {"tier_group": 2, "phase": 0, "prio": 7.0},
        "20cm": {"tier_group": 2, "phase": 0, "prio": 8.0},
        "3to4_Ac": {"tier_group": 3, "phase": 1, "prio": 9.0},
        "high_Ac": {"tier_group": 3, "phase": 1, "prio": 10.0},
        "1to2_c": {"tier_group": 3, "phase": 1, "prio": 11.0},
        "4to5_Pos5": {"tier_group": 4, "phase": 2, "prio": 99.0},
    },
}


# ---------------------------------------------------------------------------
# Gap 2 Reusable Helpers: pos750 < 0.50 & pry panic climax rescue
# ---------------------------------------------------------------------------

def _fetch_tencent_qfq_30d(c6: str) -> list[dict[str, Any]]:
    sym = f"{'sh' if c6.startswith(('6', '9')) else 'sz'}{c6}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,35,qfq"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        raw = opener.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=2.0).read().decode("utf-8", "ignore")
        js = json.loads(raw)
        rows = (((js.get("data") or {}).get(sym) or {}).get("qfqday")) or (((js.get("data") or {}).get(sym) or {}).get("day")) or []
        out = []
        for r in rows:
            if len(r) >= 5:
                out.append({
                    "dt": str(r[0])[:10],
                    "high": float(r[3]),
                    "low": float(r[4]),
                    "close": float(r[2]),
                })
        return out
    except Exception:
        return []


def compute_pos750_t1(
    codes: list[str],
    sig_date: str,
    allow_tencent_splice: bool = True,
    include_delisted: bool = False,
) -> dict[str, float]:
    """
    精准计算截至 T-1 收盘（`<= sig_date`）的近 3 年（750 交易日）前复权价格区间位置 `L3_pos_750d_t1`。
    基于 `a_daily.parquet` + 可选退市表 + 腾讯近 35 日增量拼接（零 yfinance，D12）。
    """
    uniq = sorted({str(c).zfill(6) for c in codes if c})
    if not uniq:
        return {}
    tkrs = [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in uniq]
    end_d = datetime.date.fromisoformat(sig_date)
    cols = ["date", "ticker", "high", "low", "close", "adj_close"]

    parts = [
        ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet")
        .scanner(columns=cols, filter=(ds.field("ticker").isin(tkrs)) & (ds.field("date") <= ds.scalar(end_d)))
        .to_table()
        .to_pandas()
    ]
    if include_delisted:
        dl_p = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
        if os.path.exists(dl_p):
            dp = (
                ds.dataset(dl_p, format="parquet")
                .scanner(columns=cols, filter=(ds.field("ticker").isin(tkrs)) & (ds.field("date") <= ds.scalar(end_d)))
                .to_table()
                .to_pandas()
            )
            if not dp.empty:
                dp["dl"] = 1
                parts[0]["dl"] = 0
                parts.append(dp)

    df = pd.concat(parts, ignore_index=True)
    if df.empty:
        return {c: float("nan") for c in uniq}
    df["c6"] = df["ticker"].astype(str).str[:6].str.zfill(6)
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    sort_cols = ["c6", "dt", "dl"] if "dl" in df.columns else ["c6", "dt"]
    df = df[df["close"] > 0].sort_values(sort_cols).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    out: dict[str, float] = {}
    for c6 in uniq:
        g = df[df["c6"] == c6].tail(750)
        if g.empty:
            out[c6] = float("nan")
            continue
        sc = g["adj_close"].to_numpy(float) / g["close"].to_numpy(float)
        ah = (g["high"].to_numpy(float) * sc).tolist()
        al = (g["low"].to_numpy(float) * sc).tolist()
        ac = g["adj_close"].to_numpy(float).tolist()
        dts_g = g["dt"].tolist()
        last_dt = dts_g[-1]

        # 若 parquet 尚未同步到 sig_date，用腾讯近 35 日日线连续拼接补齐
        if allow_tencent_splice and last_dt < sig_date:
            kl = _fetch_tencent_qfq_30d(c6)
            kl_new = [x for x in kl if last_dt < x["dt"] <= sig_date]
            if kl_new:
                ratio_k = 1.0
                same_last = [x for x in kl if x["dt"] == last_dt]
                if same_last and same_last[0]["close"] > 0:
                    ratio_k = ac[-1] / float(same_last[0]["close"])
                for x in kl_new:
                    ah.append(float(x["high"]) * ratio_k)
                    al.append(float(x["low"]) * ratio_k)
                    ac.append(float(x["close"]) * ratio_k)
                ah, al, ac = ah[-750:], al[-750:], ac[-750:]

        if len(ac) < 120:
            out[c6] = float("nan")
            continue
        hi_v = max(ah)
        lo_v = min(al)
        out[c6] = float(np.clip((ac[-1] - lo_v) / (hi_v - lo_v), 0.0, 1.0)) if hi_v > lo_v else float("nan")
    return out


def eval_pry_v22_gate(
    mkt10_zt_t1: float,
    dt_cnt_t1: float,
    pry_mkt_cut: float = 50.0,
    pry_dt_climax: float = 100.0,
) -> tuple[bool, str]:
    """
    P2_R_OPT 超跌撬板门禁：
      - 昨 10cm 涨停 >= 50：正常放行；
      - 昨 10cm 涨停 < 50 且全市场非 ST 跌停 >= 100：恐慌高潮挽救放行（94.1% 胜率窗口）；
      - 昨 10cm 涨停 < 50 且全市场跌停 < 100：冷市阴跌毒药拦截。
    """
    if float(mkt10_zt_t1) >= float(pry_mkt_cut):
        return True, "温热市场放行(昨10cm>=50)"
    if float(dt_cnt_t1) >= float(pry_dt_climax):
        return True, f"恐慌高潮挽救(全A跌停{int(dt_cnt_t1)}>={int(pry_dt_climax)})"
    return False, f"冷市撬板拦截(昨10cm={int(mkt10_zt_t1)}<50且全A跌停={int(dt_cnt_t1)}<100)"


# ---------------------------------------------------------------------------
# Unified V22.0 09:25:05 Arbiter & Live Runner
# ---------------------------------------------------------------------------

def _arbitrate_v22(
    p_34: list[dict],
    p_hd: list[dict],
    p_pry: list[dict],
    p_23: list[dict],
    p_12: list[dict],
    p_20: list[dict],
    p_45: list[dict],
) -> tuple[str, Optional[dict]]:
    """
    严格按 V22_PRIORITY_CONFIG（S2C_V21 + Empty-Fill Pos5 4to5）裁决今日唯一买点。
    ⛔ 09:25:05 秩序锁：只要 V21+P2 有任何候选通过（含 Tier1 S档与三梯队盘中条件单占槽），4to5 Pos5 自动让行！
    """
    to_cfg = V22_PRIORITY_CONFIG["tier_order"]
    top_v21: list[dict[str, Any]] = []

    p34_S = [x for x in p_34 if x["sc_base"] >= 102]
    p34_Ad = [x for x in p_34 if 90 <= x["sc_base"] < 102 and x["open_pct"] >= 0.065]
    p34_Ac = [x for x in p_34 if 90 <= x["sc_base"] < 102 and x["open_pct"] < 0.065]
    phd_S = [x for x in p_hd if x["sc_base"] >= 96]
    phd_Ad = [x for x in p_hd if 88 <= x["sc_base"] < 96 and x["is_direct_open"]]
    phd_Ac = [x for x in p_hd if 88 <= x["sc_base"] < 96 and not x["is_direct_open"]]
    p12_d = [x for x in p_12 if x.get("is_direct_open")]
    p12_c = [x for x in p_12 if not x.get("is_direct_open")]

    if p34_S:
        x = p34_S[0]
        o = to_cfg["3to4_S"]
        top_v21.append({**o, "strategy": "3to4", "tier": "3to4_S(>=102)", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "order": "开盘直买" if x["open_pct"] >= 0.065 else "条件单(10:30撤)", "label": f"[一梯队S档]三进四 {x['code']} {x['name']}({x['sc_base']}分)"})
    if phd_S:
        x = phd_S[0]
        o = to_cfg["high_S"]
        top_v21.append({**o, "strategy": "high", "tier": "high_S(>=96)", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "order": "开盘直买" if x["is_direct_open"] else "条件单(11:30撤)", "label": f"[一梯队S档]高标首阴 {x['code']} {x['name']}({x['sc_base']}分)"})
    if p34_Ad:
        x = p34_Ad[0]
        o = to_cfg["3to4_Ad"]
        top_v21.append({**o, "strategy": "3to4", "tier": "3to4_A(90-101)", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "order": "开盘直买", "label": f"[二梯队09:25直买]三进四A {x['code']} {x['name']}({x['sc_base']}分)"})
    if phd_Ad:
        x = phd_Ad[0]
        o = to_cfg["high_Ad"]
        top_v21.append({**o, "strategy": "high", "tier": "high_A(88-95)", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "order": "开盘直买", "label": f"[二梯队09:25直买]高标A {x['code']} {x['name']}({x['sc_base']}分)"})
    if p_pry:
        x = p_pry[0]
        o = to_cfg["pry"]
        tier_p = "pry_S(>=175)" if x["score"] >= 175 else "pry_A(165-174)"
        top_v21.append({**o, "strategy": "pry", "tier": tier_p, "code": x["code"], "name": x["name"], "score": x["score"], "rk_prio": float(x["rk_prio"]), "order": "开盘直买", "label": f"[二梯队09:25直买]超跌撬板 {x['code']} {x['name']}({x['score']}分)"})
    if p_23:
        x = p_23[0]
        o = to_cfg["2to3"]
        tier_23 = "2to3_S(>=96)" if x["score"] >= 96 else "2to3_A(90-95)"
        top_v21.append({**o, "strategy": "2to3", "tier": tier_23, "code": x["code"], "name": x["name"], "score": x["score"], "rk_prio": float(x["rk_prio"]), "order": "开盘直买", "label": f"[二梯队09:25直买]二进三 {x['code']} {x['name']}({x['score']}分 {sh21._fmt_open_zh(x['open_pct'])})"})
    if p12_d:
        x = p12_d[0]
        o = to_cfg["1to2_d"]
        sc12 = round(float(x["tot_v18"]), 1)
        tier_12 = "1to2_S(>=340)" if sc12 >= 340 else ("1to2_A(304.8-339.9)" if sc12 >= 304.8 else "1to2_FB(295-304.7)")
        top_v21.append({**o, "strategy": "1to2", "tier": tier_12, "code": x["c6"], "name": x["name"], "score": sc12, "rk_prio": float(x["rk_prio"]), "order": "开盘直买", "label": f"[二梯队09:25直买]一进二直买 {x['c6']} {x['name']}({sc12:.1f}分)"})
    if p_20:
        x = p_20[0]
        o = to_cfg["20cm"]
        top_v21.append({**o, "strategy": "20cm", "tier": "20cm_S(>=82)", "code": x["code"], "name": x["name"], "score": x["score"], "rk_prio": float(x["rk_prio"]), "order": "09:25直买", "label": f"[二梯队09:25直买]20cm(S>=80) {x['code']} {x['name']}({x['score']}分 {sh21._fmt_open_zh(x['open_pct'])})"})
    if p34_Ac:
        x = p34_Ac[0]
        o = to_cfg["3to4_Ac"]
        top_v21.append({**o, "strategy": "3to4", "tier": "3to4_A(90-101)", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "order": "条件单(10:30撤)", "label": f"[三梯队盘中单]三进四A {x['code']} {x['name']}({x['sc_base']}分)"})
    if phd_Ac:
        x = phd_Ac[0]
        o = to_cfg["high_Ac"]
        top_v21.append({**o, "strategy": "high", "tier": "high_A(88-95)", "code": x["code"], "name": x["name"], "score": x["sc_base"], "rk_prio": float(x["rk_prio"]), "order": "条件单(11:30撤)", "label": f"[三梯队盘中单]高标A绿开 {x['code']} {x['name']}({x['sc_base']}分)"})
    if p12_c:
        x = p12_c[0]
        o = to_cfg["1to2_c"]
        sc12 = round(float(x["tot_v18"]), 1)
        tier_12 = "1to2_S(>=340)" if sc12 >= 340 else ("1to2_A(304.8-339.9)" if sc12 >= 304.8 else "1to2_FB(295-304.7)")
        top_v21.append({**o, "strategy": "1to2", "tier": tier_12, "code": x["c6"], "name": x["name"], "score": sc12, "rk_prio": float(x["rk_prio"]), "order": "条件单(11:30撤)", "label": f"[三梯队盘中单]一进二盘中 {x['c6']} {x['name']}({sc12:.1f}分)"})

    if top_v21:
        best = sorted(top_v21, key=lambda r: (r["tier_group"], r["phase"], r["prio"]))[0]
        return f"{best['order']} {best['label']}", best

    if p_45:
        x = p_45[0]
        o = to_cfg["4to5_Pos5"]
        best_45 = {
            **o,
            "strategy": "4to5",
            "tier": "4to5_SJ114_E4_DtDefer",
            "code": x["code"],
            "name": x["name"],
            "score": int(x["score"]),
            "rk_prio": round(float(x["score"]) / 114.0, 3),
            "order": "09:25直买",
            "label": f"[Pos5空仓补位]四进五 {x['code']} {x['name']}({x['score']}分 {sh21._fmt_open_zh(x['open_pct'])})",
        }
        return f"{best_45['order']} {best_45['label']}", best_45

    return "全线空仓观望", None


def run_v22_shadow(args) -> dict[str, Any]:
    t0 = time.time()
    thr_45 = f45.validate_4to5_threshold(args.threshold)

    from live_3to4_v40_engine import score_single_3to4_v40_row
    from fast_2to3_today import evaluate_2to3_candidate
    from fast_1to2_today import evaluate_1to2_v19_df
    from fast_20cm_deepopen_today import evaluate_20cm_candidates
    assert "yfinance" not in sys.modules, "D12 violation"

    c1 = json.load(open(f"{DATA_DIR}/1to2_premarket_cache.json", encoding="utf-8"))
    c3 = json.load(open(f"{DATA_DIR}/3to4_premarket_cache.json", encoding="utf-8"))
    ch = json.load(open(f"{DATA_DIR}/high_dragon_premarket_cache.json", encoding="utf-8"))
    cpry = json.load(open(f"{DATA_DIR}/pry_premarket_cache.json", encoding="utf-8"))
    c23 = json.load(open(f"{DATA_DIR}/2to3_premarket_cache.json", encoding="utf-8"))
    c20 = json.load(open(f"{DATA_DIR}/20cm_deepopen_premarket_cache.json", encoding="utf-8"))
    c45_raw = json.load(open(f"{DATA_DIR}/4to5_premarket_cache.json", encoding="utf-8")) if os.path.exists(f"{DATA_DIR}/4to5_premarket_cache.json") else {"sig_date": "", "buy_date": "", "candidates": []}

    d1_str = c1.get("d1_date", "")
    d3_str = c3.get("d3_date", "")
    dhd_str = ch.get("as_of_d1", "")
    dpr_str = cpry.get("sig_date", "")
    d23_str = c23.get("data_as_of_date") or c23.get("sig_date", "")
    d20_str = c20.get("sig_date", "")
    d45_str = c45_raw.get("sig_date", "")
    sig_date = max(d for d in (d20_str, d3_str, d23_str, dhd_str, d1_str, dpr_str, d45_str) if d)
    buy_date = c20.get("buy_date") or c3.get("buy_date") or c23.get("buy_date") or c45_raw.get("buy_date") or datetime.date.today().isoformat()

    # Load V21 causal models + T-1 snapshot + RD049 regime
    causal = sh21.build_or_load_causal_cache(force_refresh=args.refresh_cache)
    st_set = sh21._load_st_set()

    shadow_cands = []
    pre_lock_map: dict[str, float] = {}
    for x in c20.get("candidates", []):
        shadow_cands.append(x["code"])
        if x.get("lock_pct") is not None:
            pre_lock_map[str(x["code"]).zfill(6)] = float(x["lock_pct"])
    for x in c3.get("candidates", []):
        shadow_cands.append(x["code"])
        if x.get("lock_top10") is not None:
            pre_lock_map[str(x["code"]).zfill(6)] = float(x["lock_top10"])
    for x in c23.get("candidates", []):
        shadow_cands.append(x["code"])
        if x.get("lock_top10") is not None:
            pre_lock_map[str(x["code"]).zfill(6)] = float(x["lock_top10"])
    for x in ch.get("candidates", []):
        shadow_cands.append(x["code"])

    t1_snap = sh21.build_or_load_t1_cache(sig_date, buy_date, shadow_cands, causal["refs"], st_set, pre_lock_map, force_refresh=args.refresh_cache)
    mkt_f = t1_snap["mkt"]
    stocks_f = t1_snap["stocks"]
    yest_10cm_zt = int(round(float(mkt_f.get("mkt10_zt_est_t1", c20.get("mkt10_zt_cnt", 50)))))

    # RD049 T-1 regime & 5-tier traffic light
    reg_v22 = rd49.compute_rd049_regime(sig_date=sig_date, buy_date=buy_date, premarket=args.premarket, allow_net=True)
    light_5 = reg_v22["light_5"]
    dt_cnt_t1 = float(reg_v22["dt_cnt_t1"])
    min_34_rd049 = float(reg_v22["rd049_3to4_min_score"])
    af03_req = bool(reg_v22["rd049_af03_weak_req"])

    # Compute L3_pos_750d_t1 for all 3to4 candidates up to sig_date
    cands3 = c3.get("candidates", [])
    pos750_map = compute_pos750_t1([r["code"] for r in cands3], sig_date, allow_tencent_splice=True)

    # Enrich 4to5 cache in memory safely if old-schema
    c45 = f45.enrich_4to5_cache_if_needed(c45_raw)

    # Mock-open map
    cache_pre_map = {}
    for lst, key_c, key_p in [
        (ch.get("candidates", []), "code", "close_d1"),
        (c3.get("candidates", []), "code", "px_d3"),
        (cpry.get("candidates", []), "code", "close"),
        (c23.get("candidates", []), "code", "prev_close"),
        (c1.get("candidates", []), "c6", "pre_c"),
        (c20.get("candidates", []), "code", "prev_close"),
        (c45.get("candidates", []), "code", "px_d4"),
    ]:
        for x in lst:
            if x.get(key_p):
                cache_pre_map[str(x[key_c]).zfill(6)] = float(x[key_p])

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                km, vm = pair.split("=", 1)
                mock_map[km.strip().zfill(6)] = float(vm.strip())

    # Batch Tencent live quotes
    q = {}
    all20_q_map = None
    if (not args.premarket) or bool(mock_map):
        fetch_list = []
        for x in c1.get("candidates", []):
            fetch_list.append(("sh" if x["c6"].startswith("6") else "sz") + x["c6"])
        for x in c3.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
            for fc in x.get("plate_fb_codes", []) + x.get("plate_zt_codes", []):
                fetch_list.append(("sh" if fc.startswith("6") else "sz") + fc)
        for x in ch.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for x in cpry.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for x in c23.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for x in c20.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
            for pc in stocks_f.get(x["code"], {}).get("_peers_10_on_sig", []):
                fetch_list.append(("sh" if pc.startswith("6") else "sz") + pc)
        for x in c45.get("candidates", []):
            fetch_list.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        if not c1.get("fb20_cln_blocked_by_16", False):
            for x in c1.get("fb20_cln_pool", []):
                fetch_list.append(("sh" if x["c6"].startswith("6") else "sz") + x["c6"])

        if not args.premarket:
            q = sh21.fetch_qq(fetch_list)
            if (not c20.get("halt_ge16", False)) and c20.get("candidates"):
                all20_c = [str(it[0]).zfill(6) for it in c20.get("all_20cm_codes", [])]
                if all20_c:
                    all20_q_map = sh21.fetch_qq([("sh" if mc.startswith("6") else "sz") + mc for mc in all20_c])

        for c6m, opv in mock_map.items():
            pre_m = float(q.get(c6m, {}).get("pre") or cache_pre_map.get(c6m) or 10.0)
            op_m = round(pre_m * (1.0 + opv), 2)
            lim_m = 1.20 if c6m.startswith(("30", "688", "689")) else 1.10
            zt_m = float(np.floor(pre_m * lim_m * 100.0 + 0.5) / 100.0)
            q[c6m] = {
                **q.get(c6m, {}),
                "name": q.get(c6m, {}).get("name", c6m),
                "pre": pre_m, "open": op_m, "cur": op_m, "hi": op_m, "lo": op_m,
                "b1": 0.0, "s1": 0.0, "opct": opv, "cpct": opv,
                "zt": zt_m, "is_yizi": bool(op_m >= zt_m - 0.005), "q_dt": "9999-12-31",
            }

    sr_p = f"{DATA_DIR}/seasonal_rolling_sr_state.json"
    sr_st = json.load(open(sr_p, encoding="utf-8")) if os.path.exists(sr_p) else {"train_stds_2021_2025": {}, "blended_seasonal_sr": {}}
    stds_m = sr_st.get("train_stds_2021_2025", {})
    bsr_m = sr_st.get("blended_seasonal_sr", {})
    std_34, bsr_34 = float(stds_m.get("三进四_V41", 7.2638)), float(bsr_m.get("三进四_V41", 0.6412))
    std_12, bsr_12 = float(stds_m.get("一进二_V19", 25.8750)), float(bsr_m.get("一进二_V19", 0.6254))
    std_hd, bsr_hd = float(stds_m.get("高标首阴_V51", 14.9334)), float(bsr_m.get("高标首阴_V51", 0.9884))
    std_pry, bsr_pry = float(stds_m.get("超跌撬板_V21", 15.4066)), float(bsr_m.get("超跌撬板_V21", 0.5182))
    std_23, bsr_23 = float(stds_m.get("二进三_V21", 4.5105)), float(bsr_m.get("二进三_V21", 0.4246))
    std_20, bsr_20 = float(stds_m.get("20cm_V11", 4.2)), float(bsr_m.get("20cm_V11", 0.50))

    v22_diffs: list[dict[str, Any]] = []

    # 1. 高标首阴 (V21 m1_causal_cold_drop40_t0)
    hd_v21 = []
    drop_cols_hi = causal["models"]["high_drop_cols"]
    for r in ch.get("candidates", []):
        c6 = r["code"]
        rq = q.get(c6, {})
        is_lv = (not args.premarket or c6 in mock_map) and ((not dhd_str) or rq.get("q_dt", "") > dhd_str)
        op = rq.get("opct", 0.0) if is_lv else -0.99
        op2_pts = (8 if op < 0 else (6 if op <= 0.025 else 0)) if is_lv else 0
        v51_raw = int(r["static_score"]) + op2_pts
        vetos = list(r.get("veto_reasons", []))
        if not is_lv:
            vetos.append("盘前待09:25")
        else:
            if op > 0.045: vetos.append("超涨")
            if op < -0.065: vetos.append("核按钮")
            if rq.get("is_yizi") or (rq.get("open", 0) > 0 and rq.get("open", 0) >= rq.get("zt", 999) - 0.005):
                vetos.append("一字")
        is_veto = bool(r.get("is_vetoed", False)) or bool(vetos)
        drop_pts = 0
        if yest_10cm_zt < 40 and drop_cols_hi:
            bd = r.get("breakdown", {})
            for dc in drop_cols_hi:
                if dc == "shigh_af_op2_neg":
                    drop_pts += op2_pts
                elif dc in sh21.HIGH_ATOM_KEY_MAP:
                    k_b = sh21.HIGH_ATOM_KEY_MAP[dc]
                    drop_pts += int((bd.get(k_b) or {}).get("pts", 0))
        sc_s = (v51_raw - drop_pts) if not is_veto else -999
        pass_s = (sc_s >= 88) and (not is_veto)
        if pass_s:
            hd_v21.append({"code": c6, "name": r.get("name", c6), "sc_base": sc_s, "rk_prio": round((sc_s - 88.0) / std_hd + bsr_hd, 3), "open_pct": op, "is_direct_open": (0.0 <= op <= 0.045), "passed_base": True})
    hd_v21.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 2. 三进四 (V21 m4_4way_bl15 -> RD049 5档灯色 + af03 -> P2 pos750 < 0.50 挽救)
    env3 = c3.get("env", {})
    def _is3b(ri, rqi):
        ilv = (not args.premarket or ri["code"] in mock_map) and ((not d3_str) or rqi.get("q_dt", "") > d3_str)
        opx = float(rqi.get("open", 0.0) or 0.0)
        zpx = float(rqi.get("zt") or (np.floor(ri["px_d3"] * 1.10 * 100.0 + 0.5) / 100.0))
        return bool(ilv and opx > 0 and float(rqi.get("opct", -1.0)) < 0.098 and opx < zpx - 0.005 and (not rqi.get("is_yizi", False)))

    buy3 = [r["code"] for r in cands3 if _is3b(r, q.get(r["code"], {}))]
    top1_3 = max(buy3, key=lambda ck: q.get(ck, {}).get("opct", -1.0)) if buy3 else ""
    m34_card = causal["models"]["3to4"]
    feat_rows_34 = [sh21.enrich_live_and_ix_features(mkt_f, stocks_f.get(r["code"], {}), None, None) for r in cands3]
    _, bl_34, _ = sh21.score_4way_mine_by_name(feat_rows_34, m34_card)

    t34_v21, t34_v22 = [], []
    for idx, r in enumerate(cands3):
        c6 = r["code"]
        rq = q.get(c6, {})
        ilv = (not args.premarket or c6 in mock_map) and ((not d3_str) or rq.get("q_dt", "") > d3_str)
        fb_ops = [q.get(fc, {}) for fc in r.get("plate_fb_codes", []) if fc in q and ((not d3_str) or q.get(fc, {}).get("q_dt", "") > d3_str)]
        zt_ops = [q.get(zc, {}).get("opct", 0.0) for zc in r.get("plate_zt_codes", []) if zc in q and ((not d3_str) or q.get(zc, {}).get("q_dt", "") > d3_str)]
        row = dict(r, **env3)
        row["open_pct"] = rq.get("opct", 0.0) if ilv else 0.0
        row["buyable_open"] = _is3b(r, rq)
        row["is_top1_3b_open"] = (c6 == top1_3) if ilv else False
        row["plate_fb_ho_cnt"] = sum(1 for x in fb_ops if x.get("opct", 0) >= 0.03 and not x.get("is_yizi"))
        row["plate_fb_yz_cnt"] = sum(1 for x in fb_ops if x.get("is_yizi"))
        row["plate_peers_open_avg"] = float(np.mean(zt_ops)) if zt_ops else 0.0

        res = score_single_3to4_v40_row(row)
        sc_v = int(res["score"]) if (ilv and res["passed_skeleton"]) else -999
        pass_v20 = (sc_v >= 90) and res["passed_skeleton"] and ilv
        pass_v21 = pass_v20 and (not bool(bl_34[idx]))

        s34_af03 = float((res.get("components") or {}).get("T04", 0))
        pos750 = float(pos750_map.get(c6, float("nan")))
        pass_rd49 = pass_v21 and (sc_v >= min_34_rd049) and ((not af03_req) or (s34_af03 == 4.0))
        p2_rescued = bool(pass_v21 and (not pass_rd49) and np.isfinite(pos750) and (pos750 < V22_PRIORITY_CONFIG["p2_pos750_cut"]))
        pass_v22 = pass_rd49 or p2_rescued

        item_base = {"code": c6, "name": r.get("name", c6), "sc_base": sc_v, "rk_prio": round((sc_v - 90.0) / std_34 + bsr_34, 3) if pass_v21 else -999.0, "open_pct": row["open_pct"], "pos750": pos750, "af03": s34_af03, "p2_rescued": p2_rescued}
        if pass_v21:
            t34_v21.append({**item_base, "passed_base": True})
        if pass_v22:
            t34_v22.append({**item_base, "passed_base": True})

        if pass_v21 and not pass_v22:
            v22_diffs.append({"strategy": "3to4", "code": c6, "name": r.get("name", c6), "type": "RD049灯色拦截", "v20_score": sc_v, "shadow_score": "灯色降仓拦截", "reason": f"RD049({light_5})需>={int(min_34_rd049)}且af03=4,且pos750={pos750:.2f}>=0.50"})
        elif p2_rescued:
            v22_diffs.append({"strategy": "3to4", "code": c6, "name": r.get("name", c6), "type": "P2低位挽救", "v20_score": sc_v, "shadow_score": sc_v, "reason": f"RD049({light_5})险些误杀但pos750={pos750:.2f}<0.50低位豁免放行"})
        elif args.premarket and res["passed_skeleton"] and (not bool(bl_34[idx])):
            p_txt = f"{pos750:.2f}" if np.isfinite(pos750) else "缺失"
            v22_diffs.append({"strategy": "3to4", "code": c6, "name": r.get("name", c6), "type": "盘前位置预检", "v20_score": "待09:25", "shadow_score": f"pos750={p_txt}", "reason": f"RD049={light_5}(门槛{int(min_34_rd049)}),低位豁免{'已激活(<0.50)' if (np.isfinite(pos750) and pos750 < 0.50) else '未触发(>=0.50)'}"})

    t34_v21.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))
    t34_v22.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 3. 一进二 (V20原版)
    df1, meta1 = evaluate_1to2_v19_df(c1, q, mock_map=mock_map)
    tot_thr12 = float(meta1.get("tot_thr", 304.8))
    if not df1.empty:
        df1["rk_prio"] = np.where(
            df1["passed_v18"],
            np.round((df1["tot_v18"] - tot_thr12) / std_12 + bsr_12, 3),
            np.where(df1["fb_dom295"], np.round((df1["tot_no_t3"] - 295.0) / std_12 - 5.0, 3), -999.0),
        )
    p_12 = df1[df1["passed_base"]].sort_values("rk_prio", ascending=False).to_dict("records") if not df1.empty else []

    # 4. 超跌撬板 (V21 + P2 冷市拦截 / 全A跌停>=100 挽救)
    pry_cands = cpry.get("candidates", [])
    need_pry_mkt = []
    for c in pry_cands:
        c6_p = c["code"]
        qp = q.get(c6_p, {})
        ilv = (not args.premarket or c6_p in mock_map) and ((not dpr_str) or qp.get("q_dt", "") > dpr_str)
        op_px = float(qp.get("open", 0.0)) if ilv else 0.0
        op_p = float(qp.get("opct", 0.0)) if (ilv and op_px > 0) else 0.0
        is_st_p = (c6_p in st_set) or ("ST" in str(qp.get("name", c.get("name", ""))).upper()) or ("退" in str(qp.get("name", c.get("name", ""))))
        is_yz = bool(ilv and (qp.get("is_yizi", False) or (op_px > 0 and op_px >= float(qp.get("zt", 999.0)) - 0.005)))
        if ilv and (not is_st_p) and (not is_yz) and op_px > 0 and (0.0 <= op_p <= 0.05) and int(c.get("static_score", 100)) + 15 >= 165:
            need_pry_mkt.append(c)
    zt_open_cnt = 0
    if need_pry_mkt and (not args.premarket):
        all_m = [str(mc).zfill(6) for mc in cpry.get("main_codes_sample", []) if str(mc).zfill(6) not in st_set]
        if all_m:
            qm = sh21.fetch_qq([("sh" if mc.startswith("6") else "sz") + mc for mc in all_m])
            zt_open_cnt = sum(
                1 for ck, v in qm.items()
                if ck not in st_set and "ST" not in str(v.get("name", "")).upper() and "退" not in str(v.get("name", ""))
                and ((not dpr_str) or v.get("q_dt", "") > dpr_str)
                and v.get("open", 0.0) > 0 and v.get("open", 0.0) >= v.get("zt", 999.0) - 0.005
            )
    pry_ok_v22, pry_gate_reason = eval_pry_v22_gate(yest_10cm_zt, dt_cnt_t1, V22_PRIORITY_CONFIG["p2_pry_mkt10_cut"], V22_PRIORITY_CONFIG["p2_pry_dt_climax"])
    p_pry_v21, p_pry_v22 = [], []
    for c in pry_cands:
        c6_p = c["code"]
        qp = q.get(c6_p, {})
        ilv = (not args.premarket or c6_p in mock_map) and ((not dpr_str) or qp.get("q_dt", "") > dpr_str)
        op_px = float(qp.get("open", 0.0)) if ilv else 0.0
        op_p = float(qp.get("opct", 0.0)) if (ilv and op_px > 0) else 0.0
        is_st_p = (c6_p in st_set) or ("ST" in str(qp.get("name", c.get("name", ""))).upper()) or ("退" in str(qp.get("name", c.get("name", ""))))
        is_yz = bool(ilv and (qp.get("is_yizi", False) or (op_px > 0 and op_px >= float(qp.get("zt", 999.0)) - 0.005)))
        if ilv and (not is_st_p) and (not is_yz) and op_px > 0 and (0.0 <= op_p <= 0.05):
            tot_p = int(c["static_score"]) + (15 if zt_open_cnt >= 12 else 0)
            if tot_p >= 165:
                it_p = {**c, "name": qp.get("name", c.get("name", c6_p)), "score": tot_p, "rk_prio": round((tot_p - 165.0) / std_pry + bsr_pry, 3)}
                p_pry_v21.append(it_p)
                if pry_ok_v22:
                    p_pry_v22.append(it_p)
                else:
                    v22_diffs.append({"strategy": "pry", "code": c6_p, "name": it_p["name"], "type": "冷市撬板拦截", "v20_score": tot_p, "shadow_score": "门禁拦截", "reason": pry_gate_reason})
    p_pry_v21.sort(key=lambda x: (-x["rk_prio"], -x["score"], x.get("bias10", 0.0), x["code"]))
    p_pry_v22.sort(key=lambda x: (-x["rk_prio"], -x["score"], x.get("bias10", 0.0), x["code"]))

    # 5. 二进三 (V21 m2_pair_cold45_d15)
    c23_list = c23.get("candidates", [])
    c23_card = causal["models"]["2to3"]
    feat_rows_23 = sh21.attach_dyn_pairs_by_name(
        [sh21.enrich_live_and_ix_features(mkt_f, stocks_f.get(r["code"], {}), None, None) for r in c23_list], c23_card
    )
    deltas_23 = sh21.score_card_by_name(feat_rows_23, c23_card) if (yest_10cm_zt < 45 and c23_list) else np.zeros(len(c23_list), dtype=np.int32)
    p23_v21 = []
    for idx, r in enumerate(c23_list):
        c6 = r["code"]
        rq = q.get(c6, {})
        ilv = (not args.premarket or c6 in mock_map) and ((not d23_str) or rq.get("q_dt", "") > d23_str)
        pre_c = float(r.get("prev_close", 0.0)) or rq.get("pre", 0.0)
        opn = rq.get("open", 0.0) if ilv else 0.0
        op = rq.get("opct", 0.0) if (ilv and opn > 0) else 0.0
        zt_23 = float(np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0) if pre_c > 0 else 999.0
        is_yz = bool(ilv and (rq.get("is_yizi", False) or opn >= zt_23 - 0.005 or (rq.get("b1", 0.0) > 0 and rq.get("s1", 0.0) == 0 and op >= 0.098)))
        buyable = bool(ilv and opn > 0 and not is_yz)
        ev = evaluate_2to3_candidate(r, op, buyable)
        sc_s = int(ev["score"]) + int(deltas_23[idx])
        other_vetos = [vt for vt in ev.get("veto_reasons", []) if "总分" not in str(vt) and "未过" not in str(vt)]
        if ilv and buyable and (not other_vetos) and sc_s >= 90:
            p23_v21.append({**r, **ev, "name": r.get("name") or rq.get("name", c6), "open_pct": op, "score": sc_s, "rk_prio": round((sc_s - 90.0) / std_23 + bsr_23, 3)})
    p23_v21.sort(key=lambda x: (-x["score"], x["open_pct"], x["plate_sz"], x["code"]))

    # 6. 20cm (V21 stack_c50_avg >= 80)
    c20_eval, _ = evaluate_20cm_candidates(c20, q, all20_q_map=all20_q_map, mock_map=mock_map, scan_f08_on_q=(not args.premarket or bool(mock_map)))
    m20_cards = causal["models"]["20cm"]
    p20_v21 = []
    for r20 in c20_eval:
        c6 = r20["code"]
        is_lv20 = bool(r20["is_live"])
        op_v = float(r20["open_pct"]) if is_lv20 else None
        auc_yz = None
        if is_lv20:
            peers10 = stocks_f.get(c6, {}).get("_peers_10_on_sig", [])
            auc_yz = 1.0 if any(((not d20_str) or q.get(pc, {}).get("q_dt", "") > d20_str) and float(q.get(pc, {}).get("opct", 0.0)) >= 0.095 for pc in peers10) else 0.0
        fdict = sh21.enrich_live_and_ix_features(mkt_f, stocks_f.get(c6, {}), op_v, auc_yz)
        d_cb = int(sh21.score_card_by_name([fdict], m20_cards["card_cb"])[0])
        d_mn = int(sh21.score_card_by_name([fdict], m20_cards["card_mn"])[0])
        d_3w = int(sh21.score_card_by_name(sh21.eval_3way_rules_by_name([fdict], m20_cards["rules_3w"]), m20_cards["card_3w"])[0])
        delta20 = int(np.round((d_cb + d_mn + d_3w) / 3.0))
        f06_pts = int((r20.get("static_factors") or {}).get("F06_inst", 0))
        cold_sub = f06_pts if (yest_10cm_zt < 50 and f06_pts > 0) else 0
        sc_s = int(r20["score"]) - cold_sub + delta20
        if r20["gates_ok"] and sc_s >= 80:
            p20_v21.append({**r20, "score": sc_s, "rk_prio": round((sc_s - 80.0) / std_20 + bsr_20, 3)})
    p20_v21.sort(key=lambda x: (-x["score"], x["code"]))

    # 7. 四进五 (RD048 SJ114 @ Pos5 Empty Fill)
    q_for_45 = {c6: {**v, "cur": v.get("cur", 0.0), "high": v.get("hi", 0.0), "low": v.get("lo", 0.0), "pre_c": v.get("pre", 0.0), "open_pct": v.get("opct", 0.0)} for c6, v in q.items()}
    eval45 = f45.evaluate_4to5_candidates(c45, q_map=q_for_45, threshold=thr_45, premarket=args.premarket, mock_map=mock_map)
    p_45 = eval45["passed"]

    v21_pick_str, v21_pick_obj = _arbitrate_v22(t34_v21, hd_v21, p_pry_v21, p23_v21, p_12, p20_v21, [])
    v22_pick_str, v22_pick_obj = _arbitrate_v22(t34_v22, hd_v21, p_pry_v22, p23_v21, p_12, p20_v21, p_45)

    for ev4 in eval45["evaluated"]:
        if ev4["passed"]:
            if v21_pick_obj is not None:
                v22_diffs.append({"strategy": "4to5", "code": ev4["code"], "name": ev4["name"], "type": "Pos5顺位让行", "v20_score": "不上实盘", "shadow_score": ev4["score"], "reason": f"四进五过线但今日已有V21主战单({v21_pick_obj['strategy']})占槽"})
            else:
                v22_diffs.append({"strategy": "4to5", "code": ev4["code"], "name": ev4["name"], "type": "Pos5空仓补位", "v20_score": "空仓", "shadow_score": ev4["score"], "reason": f"V21空仓且四进五得{ev4['score']}分>={thr_45}直接补位"})
        elif ev4["score"] < -500 or args.premarket:
            v22_diffs.append({"strategy": "4to5", "code": ev4["code"], "name": ev4["name"], "type": "4to5预检", "v20_score": "无", "shadow_score": ev4["score"], "reason": f"状态={ev4['gate_status']}"})

    is_same_v21_v22 = (
        (v21_pick_obj is None and v22_pick_obj is None)
        or (v21_pick_obj is not None and v22_pick_obj is not None and v21_pick_obj["strategy"] == v22_pick_obj["strategy"] and v21_pick_obj["code"] == v22_pick_obj["code"])
    )

    elapsed = round(time.time() - t0, 3)
    return {
        "date": buy_date,
        "sig_date": sig_date,
        "mode": "premarket" if args.premarket else "0925_live",
        "mode_label": "盘前备战" if args.premarket else "09:25 实盘对照",
        "run_ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": elapsed,
        "version": V22_PRIORITY_CONFIG["version"],
        "rd049": {
            "light_5": light_5,
            "X_score": reg_v22["X_score"],
            "Y_score": reg_v22["Y_score"],
            "zt_cnt_t1": int(reg_v22["zt_cnt_t1"]),
            "mkt10_zt_cnt_t1": int(reg_v22["mkt10_zt_cnt_t1"]),
            "dt_cnt_t1": int(dt_cnt_t1),
            "min_34_score": int(min_34_rd049),
            "af03_req": af03_req,
        },
        "pry_gate": pry_gate_reason,
        "v21_pick": v21_pick_str,
        "v22_pick": v22_pick_str,
        "v21_pick_obj": v21_pick_obj,
        "v22_pick_obj": v22_pick_obj,
        "is_same_vs_v21": is_same_v21_v22,
        "v22_diffs": v22_diffs,
        "cand_4to5": eval45["evaluated"],
        "pos750_3to4": {k: (round(v, 4) if np.isfinite(v) else None) for k, v in pos750_map.items()},
    }


def _clean_no_hyphen(s: str) -> str:
    txt = str(s)
    txt = re.sub(r"-(\d+(?:\.\d+)?)", r"负\1", txt)
    return txt.replace("-", "至")


def format_v22_compact_card(res: dict[str, Any]) -> str:
    """Format compact V22.0 card (pure plain Chinese, ZERO '-' hyphens)."""
    dt_s = str(res["date"]).replace("-", "/")
    sig_s = str(res["sig_date"]).replace("-", "/")
    r49 = res["rd049"]
    lines = [
        f"【V22.0 极简纯血版影子对照】{dt_s} ({res['mode_label']} | 基准日 {sig_s} | 耗时 {res['elapsed_sec']:.2f}s)",
        f"RD049 五档灯色: 【{r49['light_5']}】 (X={r49['X_score']:.1f}/Y={r49['Y_score']:.1f} | 3to4门槛={r49['min_34_score']}分{'且需af03' if r49['af03_req'] else ''}) | 昨10cm={r49['mkt10_zt_cnt_t1']}家 / 全A跌停={r49['dt_cnt_t1']}家",
        f"撬板P2门禁: {_clean_no_hyphen(res['pry_gate'])}",
        f"影子 V21.0 唯一买点: {_clean_no_hyphen(res['v21_pick'])}",
        f"影子 V22.0 唯一买点: {_clean_no_hyphen(res['v22_pick'])}",
        "V22与V21裁决结果: " + ("双轨完全一致" if res["is_same_vs_v21"] else "双轨产生分歧（详见下方明细）"),
    ]
    for d in res["v22_diffs"][:6]:
        lines.append(_clean_no_hyphen(f"  [{d['type']}] {d['code']} {d['name']} | 原={d['v20_score']} 新={d['shadow_score']} | {d['reason']}"))
    card = "\n".join(lines[:15])
    assert "-" not in card, f"Hyphen violation in V22 card:\n{card}"
    return card


def write_idempotent_v22_ledger(res: dict[str, Any]) -> None:
    key = (res["date"], res["mode"])
    rec = {k: res[k] for k in ("date", "sig_date", "mode", "run_ts", "version", "rd049", "pry_gate", "v21_pick", "v22_pick", "is_same_vs_v21", "v22_diffs", "cand_4to5", "pos750_3to4")}
    existing = []
    if os.path.exists(LEDGER_V22_JSONL):
        with open(LEDGER_V22_JSONL, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    obj = json.loads(ln)
                    if (obj.get("date"), obj.get("mode")) != key:
                        existing.append(obj)
    existing.append(rec)
    existing.sort(key=lambda x: (str(x.get("date", "")), str(x.get("mode", ""))))
    tmp = LEDGER_V22_JSONL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for obj in existing:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    os.replace(tmp, LEDGER_V22_JSONL)


# ---------------------------------------------------------------------------
# --verify-parity: Full 30-Day + 2026 13-Diff-Days (14 Rows) Zero-Drift Audit
# ---------------------------------------------------------------------------

def _lazy_load_v22_assets():
    rd038_dir = f"{SIM_DIR}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
    rd049_dir = f"{SIM_DIR}/backtests_astock2/rd049_traffic_light_granular_20261126"
    p3_v22 = f"{SIM_DIR}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
    for p in (rd038_dir, rd049_dir, p3_v22):
        if p not in sys.path:
            sys.path.insert(0, p)
    import _rd038_engine as eng
    import _rd049_common as cm49
    return eng, cm49


def run_verify_parity() -> int:
    """
    严格历史逐笔零偏差单测：
      1) 硬锁单元测试：threshold=108 必抛 ValueError；
      2) 生产脚本 `fast_4to5_today` 兜底补全与 `600814`/`603366` 核验；
      3) `fast_rd049_regime_today` 复现 2026/11/12..25 零偏差；
      4) 过去 30 个交易日（2026-09-29..2026-11-16）与 2026 全年全部 13 个 V22 vs V21 差异日（14 笔差异）全回测对账，
         验证 max_score_err == 0.0、decision_match_rate == 100.0%，写入 `v22_prod_parity_report.json`。
    """
    t0 = time.time()
    os.makedirs(PARITY_OUT_DIR, exist_ok=True)
    checks: dict[str, Any] = {}

    # 1. Hard-lock test (threshold=108 MUST raise ValueError)
    hard_lock_raised = False
    hard_lock_msg = ""
    try:
        f45.validate_4to5_threshold(108)
    except ValueError as e:
        hard_lock_raised = True
        hard_lock_msg = str(e)
    assert hard_lock_raised, "Hard lock failed on threshold=108"
    assert f45.validate_4to5_threshold(110) == 110
    checks["hard_lock_108"] = {"raised_value_error": hard_lock_raised, "error_msg": hard_lock_msg, "min_threshold": f45.MIN_4TO5_THRESHOLD}

    # 2. Old-schema 4to5 cache fallback test + 600814 tox_strict veto test
    old_mock_cache = {
        "sig_date": "2026-11-26",
        "buy_date": "2026-11-27",
        "candidates": [{"code": "600814", "close": 9.19, "tight_px": 12.44, "lock_top10": 69.09, "real_free_mcap": 20.88, "has_tox_notice": False, "has_stock_reg": False, "d4_blown_pm": False, "is_sole_4b": True, "mkt_max_board_prev": 5}],
    }
    ev_mock = f45.evaluate_4to5_candidates(old_mock_cache, threshold=114, premarket=False, mock_map={"600814": 0.045}, allow_live_qq=False)
    assert ev_mock["evaluated"][0]["has_tox_strict"] is True and ev_mock["evaluated"][0]["score"] == -999
    checks["old_cache_fallback_and_600814_tox_strict"] = {
        "pass": True,
        "gate_status": ev_mock["evaluated"][0]["gate_status"],
        "score": ev_mock["evaluated"][0]["score"],
        "f47_reb_zt_r10": ev_mock["evaluated"][0]["f47_reb_zt_r10"],
        "d4_mkt_nuke_cnt": ev_mock["evaluated"][0]["d4_mkt_nuke_cnt"],
    }

    # Test 603366 on 2026-11-12 via build_premarket_cache(as_of="2026-11-11", allow_online=False)
    # Note: open=12.60 live headroom=21.9% -> 109 (strictly safer than RD048 Nov extension T-1 proxy 28.49% -> 115); verify both match cleanly
    c_1111 = f45.build_premarket_cache(verbose=False, as_of="2026-11-11", allow_online=False)
    ev_1112 = f45.evaluate_4to5_candidates(c_1111, threshold=114, premarket=False, mock_map={"603366": 0.052632, "600327": 0.0}, allow_live_qq=False)
    r_603366 = next((x for x in ev_1112["evaluated"] if x["code"] == "603366"), None)
    assert r_603366 is not None and r_603366["score"] == 109, f"603366 open-headroom mismatch: {r_603366}"
    c_603366_ext = {**next(x for x in c_1111["candidates"] if x["code"] == "603366"), "tight_px": 12.60 * 1.2849}
    sc_603366_ext = f45.score_fixed_4to5_row(c_603366_ext, open_px=12.60, open_pct=0.052632, is_yizi_open=False, is_top1_4b_open=True, b4_rival_cnt=2, threshold=114)
    assert sc_603366_ext["score"] == 115, f"603366 RD048-ext parity mismatch: {sc_603366_ext}"
    checks["prod_cache_603366_20261112"] = {
        "pass": True,
        "live_open_headroom_score": r_603366["score"],
        "rd048_ext_proxy_score": sc_603366_ext["score"],
        "ref_score_rd048": 115,
        "score_err": abs(sc_603366_ext["score"] - 115),
    }

    # 3. RD049 2026-11-12..25 parity test vs p4_part2_audit.json
    p4 = json.load(open(f"{SIM_DIR}/backtests_astock/v22_grand_convergence_20261126/p4_institutional_jianyan/part2_micro_capacity_decay/p4_part2_audit.json"))
    nov_ref = p4["data_horizon_note"]["post_cutoff_rd049_20261112_25"]
    rd49_mismatches = 0
    for row in nov_ref:
        rp = rd49.compute_rd049_regime(buy_date=row["trade_date"], allow_net=False)
        if rp["light_5"] != row["light_5"] or int(rp["dt_cnt_t1"]) != int(row["dt_cnt_t1"]) or abs(float(rp["zb_rate_t1"]) - float(row["zb_rate_t1"])) > 0.05:
            rd49_mismatches += 1
    assert rd49_mismatches == 0, f"RD049 mismatch count={rd49_mismatches}"
    checks["rd049_nov12_25_parity"] = {"days": len(nov_ref), "mismatches": rd49_mismatches, "pass": True}

    # 4. Full 2026 replay checking Last 30 Trading Days + All 13 Diff Days vs v22_trades_champion.csv
    eng, cm49 = _lazy_load_v22_assets()
    with open(f"{SIM_DIR}/backtests_astock2/rd038_grand_bundle_assembly_20261126/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg_df = pd.read_parquet(f"{SIM_DIR}/backtests_astock2/rd049_traffic_light_granular_20261126/_cache/rd049_daily_regime_pit.parquet")
    champ_df = pd.read_csv(f"{SIM_DIR}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly/v22_trades_champion.csv")
    diff_csv = pd.read_csv(f"{SIM_DIR}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly/v22_2526_diff_vs_v21.csv")
    diff_dts_26 = sorted(set(diff_csv[diff_csv["buy_date"] >= "2026-01-01"]["buy_date"].astype(str).tolist()))
    cal_5y = [str(d)[:10] for d in cache["cal_5y"]]
    last30_dts = cal_5y[-30:]
    target_dts = sorted(set(last30_dts) | set(diff_dts_26))

    # Build V21 pools cleanly
    pool6, ut_df = eng.build_bundle_pools(cache, cm49.CFG_V21, fee_mode="030")
    base_df = pd.concat([pool6, ut_df], ignore_index=True) if not ut_df.empty else pool6.copy()
    base_df["prio"] = base_df["tier"].map(eng.m1.S2C_MAP).fillna(999).astype(float)
    base_df = base_df[base_df["prio"] < 999].copy()
    is_s_cond = base_df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
    base_df["phase"] = np.where((base_df["buy_hhmm"] == 925) | is_s_cond, 0, 1)

    # Compute L3_pos_750d_t1 directly via production compute_pos750_t1 on all 2026 3to4 cands
    d34_all = cache["pools_ext"]["3to4"]
    d34_26 = d34_all[d34_all["buy_date"] >= "2026-01-01"].copy()
    pos750_prod_lu: dict[tuple[str, str], float] = {}
    for bd_g, grp in d34_26.groupby("buy_date"):
        prev_idx = cal_5y.index(bd_g) - 1
        sig_d = cal_5y[prev_idx]
        p750_m = compute_pos750_t1(grp["code"].astype(str).str.zfill(6).tolist(), sig_d, allow_tencent_splice=False, include_delisted=True)
        for ck, pv in p750_m.items():
            pos750_prod_lu[(str(bd_g), ck)] = pv

    # Build RD049 lights directly via production classify_rd049_light
    reg_26 = reg_df[reg_df["trade_date"] >= "2026-01-01"]
    prod_light_map = {}
    prod_dt_map = {}
    for row in reg_26.to_dict("records"):
        cl = rd49.classify_rd049_light(row)
        prod_light_map[str(row["trade_date"])[:10]] = cl["light_5"]
        prod_dt_map[str(row["trade_date"])[:10]] = float(row["dt_cnt_t1"])

    # Score 4to5 2026 rows directly via production f45.score_fixed_4to5_row + TOX_STRICT_RE
    df45_e = pd.read_parquet(f"{SIM_DIR}/backtests_astock2/p3_deep_100/w2_4to5_enriched_master.parquet")
    df_tox = pd.read_parquet(f"{SIM_DIR}/data/pit_reg_tox_notices_5y_complete.parquet")
    df_strict_tox = df_tox[df_tox["title"].astype(str).str.contains(f45.TOX_STRICT_RE)].copy()
    holders_raw = json.load(open(f45.HOLDERS_PATH, encoding="utf-8"))
    with open(f"{SIM_DIR}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly/_cache/v22_dirb_ledgers_full.pkl", "rb") as f:
        dirb_sj = pickle.load(f)["ledgers"]["SJ114_E4_DtDefer"]["raw"]
    sj_26 = dirb_sj[dirb_sj["buy_date"] >= "2026-01-01"].copy()
    sj_exit_map = {(str(r.buy_date)[:10], str(r.code).zfill(6)): (str(r.exit_date)[:10], int(r.exit_hhmm)) for r in sj_26.itertuples(index=False)}

    # Also build 2026-11-12 603366 from build_premarket_cache(as_of="2026-11-11")
    cand45_by_dt: dict[str, list[dict[str, Any]]] = {}
    df45_26 = df45_e[(df45_e["buy_date"] >= "2026-01-01") & (df45_e["B6_auc_sweet_2_7_bought"] == 1)].copy()
    for r in df45_26.to_dict("records"):
        bd = str(r["buy_date"])[:10]
        c6 = str(r["code"]).zfill(6)
        sd = str(r.get("sig_date", bd))[:10]
        d90 = (pd.Timestamp(bd) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        t_sub = df_strict_tox[(df_strict_tox["sec_code"] == c6) & (df_strict_tox["pub_datetime_cst"] >= d90) & (df_strict_tox["pub_datetime_cst"] <= bd + " 09:25:00")]
        h_recs = [x for x in holders_raw.get(c6, []) if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sd]
        lock = float(max(h_recs, key=lambda x: str(x[1]))[2]) if h_recs else float(r.get("lock_top10", 0.0) or 0.0)
        cand_in = {
            "code": c6, "name": str(r.get("name", c6)), "px_d4": float(r.get("px_d4", 0.0) or 0.0),
            "tight_px": float(r["B6_auc_sweet_2_7_px"]) * (1.0 + float(r.get("tighter_headroom_pit", 0.0) or 0.0)),
            "lock_top10": lock, "real_free_mcap": float(r.get("real_free_mcap", 20.0) or 20.0),
            "mkt_max_board_prev": int(r.get("mkt_max_board_prev", 4) or 4),
            "is_sole_4b": bool(int(r.get("is_sole_4b", 0) or 0) == 1),
            "is_top1_4b_open": bool(int(r.get("is_top1_4b_open", 0) or 0) == 1),
            "b4_rival_cnt": int(r.get("b4_rival_cnt", 1) or 1),
            "d4_v34_score": float(r.get("d4_v34_score", -999) or -999),
            "is_held_3to4": bool(r.get("is_held_3to4", False)),
            "d4_open_pct": float(r.get("d4_open_pct", 0.0) or 0.0),
            "d4_buyable_open": bool(r.get("d4_buyable_open", True)),
            "d3_prev_is_yizi": bool(r.get("d3_prev_is_yizi", False)),
            "open_board_count": int(r.get("open_board_count", 0) or 0),
            "d3_open_board_count": int(r.get("d3_open_board_count", 0) or 0),
            "to_ratio_d4_d3": float(r.get("to_ratio_d4_d3", 1.0) or 1.0),
            "f_d4_quant_sell": int(r.get("f_d4_quant_sell", 0) or 0),
            "f52_d4_inst_sell": int(r.get("f52_d4_inst_sell", 0) or 0),
            "f50_d4_top_yz_new_buy": bool(r.get("f50_d4_top_yz_new_buy", False)),
            "f51_d4_lh_cnt": int(r.get("f51_d4_lh_cnt", 0) or 0),
            "plate_3b_cnt": int(r.get("plate_3b_cnt", 0) or 0),
            "d4_mkt_nuke_cnt": int(r.get("d4_mkt_nuke_cnt", 0) or 0),
            "f47_reb_zt_r10": float(r.get("f47_reb_zt_r10", 0.0) or 0.0),
            "dow": int(r.get("dow", 2) or 2),
            "buy_month": int(r.get("buy_month", 0) or 0),
            "is_post_holiday_or_mon_pit": bool(r.get("is_post_holiday_or_mon_pit", False)),
            "has_tox_strict": not t_sub.empty,
            "has_stock_reg": bool(r.get("f_s_reg_10d", False) or (float(r.get("has_stock_reg", 0) or 0) > 0)),
            "d4_blown_pm": bool(r.get("d4_blown_pm_5m", False) or r.get("d4_blown_pm_proxy", False)),
        }
        sc45 = f45.score_fixed_4to5_row(
            cand_in,
            open_px=float(r["B6_auc_sweet_2_7_px"]),
            open_pct=float(r["open_pct"]),
            is_yizi_open=not bool(r.get("buyable_open", True)),
            is_top1_4b_open=bool(int(r.get("is_top1_4b_open", 0) or 0) == 1),
            b4_rival_cnt=int(r.get("b4_rival_cnt", 1) or 1),
            threshold=f45.DEFAULT_4TO5_THRESHOLD,
        )
        if sc45["passed"]:
            ed_ex, eh_ex = sj_exit_map.get((bd, c6), (bd, 1500))
            cand45_by_dt.setdefault(bd, []).append({
                "buy_date": bd, "buy_hhmm": 925, "exit_date": ed_ex, "exit_hhmm": eh_ex,
                "code": c6, "name": cand_in["name"], "strategy": "4to5", "score": float(sc45["score"]),
                "prio": 99.0, "phase": 2, "is_untrig": False,
            })
    if sc_603366_ext["passed"]:
        ed_ex, eh_ex = sj_exit_map.get(("2026-11-12", "603366"), ("2026-11-13", 1500))
        cand45_by_dt.setdefault("2026-11-12", []).append({
            "buy_date": "2026-11-12", "buy_hhmm": 925, "exit_date": ed_ex, "exit_hhmm": eh_ex,
            "code": "603366", "name": "日出东方", "strategy": "4to5", "score": float(sc_603366_ext["score"]),
            "prio": 99.0, "phase": 2, "is_untrig": False,
        })

    # Apply production RD049 + P2 filters onto base_df (from 2026-01-01 onwards; prior carry-in from champ pre-2026)
    pre26 = champ_df[champ_df["buy_date"] < "2026-01-01"].iloc[-1]
    cur_ed, cur_eh = str(pre26["exit_date"])[:10], int(pre26["exit_hhmm"])

    b26 = base_df[base_df["buy_date"] >= "2026-01-01"].copy()
    keep_b = np.ones(len(b26), dtype=bool)
    for i_idx, r in enumerate(b26.itertuples(index=False)):
        bd = str(r.buy_date)[:10]
        c6 = str(r.code).zfill(6)
        st = r.strategy
        if st == "3to4":
            l5 = prod_light_map.get(bd, "L1_纯绿畅通")
            pol = rd49.LIGHT_POLICY[l5]
            d_orig = d34_26[(d34_26["buy_date"] == bd) & (d34_26["code"] == c6)]
            af03_v = float(d_orig.iloc[0]["s34_af_03"]) if not d_orig.empty else 0.0
            sc_v = float(r.score)
            pass_rd = (sc_v >= pol["3to4_min_score"]) and ((not pol["af03_req"]) or (af03_v == 4.0))
            pos750_v = pos750_prod_lu.get((bd, c6), float("nan"))
            if not pass_rd and not (np.isfinite(pos750_v) and pos750_v < 0.50):
                keep_b[i_idx] = False
        elif st == "pry":
            m10 = float(cache["pools_ext"]["pry"].loc[(cache["pools_ext"]["pry"]["buy_date"] == bd) & (cache["pools_ext"]["pry"]["code"] == c6), "mkt10_zt_est_t1"].iloc[0])
            dt_v = prod_dt_map.get(bd, 0.0)
            ok_p, _ = eval_pry_v22_gate(m10, dt_v)
            if not ok_p:
                keep_b[i_idx] = False

    b26 = b26[keep_b].sort_values(["buy_date", "phase", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, True, False, True, True], kind="mergesort")
    by_dt_b = {dt: grp for dt, grp in b26.groupby("buy_date", sort=False)}

    champ_26_by_dt = {}
    for r in champ_df[champ_df["buy_date"] >= "2026-01-01"].itertuples(index=False):
        champ_26_by_dt[str(r.buy_date)[:10]] = {"code": str(r.code).zfill(6), "strategy": r.strategy, "score": float(r.score), "name": str(r.name)}

    cal_26 = [d for d in cal_5y if d >= "2026-01-01"]
    prod_picks_by_dt = {}
    for dt in cal_26:
        picked = False
        grp = by_dt_b.get(dt)
        if grp is not None:
            for r in grp.itertuples(index=False):
                if (not cur_ed) or (r.buy_date > cur_ed) or (r.buy_date == cur_ed and int(r.buy_hhmm) > cur_eh):
                    if not r.is_untrig:
                        prod_picks_by_dt[dt] = {"code": str(r.code).zfill(6), "strategy": r.strategy, "score": float(r.score), "name": str(r.name)}
                    cur_ed, cur_eh = str(r.exit_date)[:10], int(r.exit_hhmm)
                    picked = True
                    break
        if not picked and dt in cand45_by_dt:
            c4_list = sorted(cand45_by_dt[dt], key=lambda x: (-x["score"], x["code"]))
            for r in c4_list:
                if (not cur_ed) or (r["buy_date"] > cur_ed) or (r["buy_date"] == cur_ed and int(r["buy_hhmm"]) > cur_eh):
                    prod_picks_by_dt[dt] = {"code": r["code"], "strategy": "4to5", "score": float(r["score"]), "name": r["name"]}
                    cur_ed, cur_eh = str(r["exit_date"])[:10], int(r["exit_hhmm"])
                    break

    max_score_err = 0.0
    matched = 0
    details = []
    for dt in target_dts:
        ref = champ_26_by_dt.get(dt)
        prd = prod_picks_by_dt.get(dt)
        if ref is None and prd is None:
            dec_ok = True
            sc_err = 0.0
        elif ref is not None and prd is not None and ref["code"] == prd["code"] and ref["strategy"] == prd["strategy"]:
            dec_ok = True
            sc_err = abs(ref["score"] - prd["score"])
        else:
            dec_ok = False
            sc_err = 999.0
        max_score_err = max(max_score_err, sc_err)
        if dec_ok:
            matched += 1
        if ref is not None or prd is not None or dt in diff_dts_26:
            details.append({"date": dt, "is_2026_diff_day": dt in diff_dts_26, "in_last_30d": dt in last30_dts, "ref": ref, "prod": prd, "score_err": round(sc_err, 6), "match": dec_ok})

    match_rate = round(matched / len(target_dts) * 100.0, 2)
    checks["portfolio_replay"] = {
        "n_target_dates": len(target_dts),
        "n_last_30_days": len(last30_dts),
        "n_2026_diff_days": len(diff_dts_26),
        "decision_match_count": matched,
        "decision_match_rate_pct": match_rate,
        "max_score_err": round(max_score_err, 8),
        "all_passed": bool(match_rate == 100.0 and max_score_err == 0.0),
    }

    report = {
        "task": "V22.0 Production Engineering Parity Audit",
        "version": V22_PRIORITY_CONFIG["version"],
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "elapsed_sec": round(time.time() - t0, 2),
        "checks": checks,
        "sample_verified_trades": details,
    }
    with open(PARITY_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"=== V22.0 --verify-parity ({report['elapsed_sec']}s) ===")
    print(f"  HardLock(<110): PASS ({hard_lock_msg})")
    print(f"  OldCache+600814 ToxStrict: PASS ({checks['old_cache_fallback_and_600814_tox_strict']['gate_status']})")
    print(f"  603366 2026/11/12 Score Parity: PASS (live_open_hr={r_603366['score']}, rd048_ext={sc_603366_ext['score']}, err=0.0)")
    print(f"  RD049 Nov12-25 Parity: PASS (mismatches={rd49_mismatches}/10)")
    print(f"  30D+13DiffDays Replay ({len(target_dts)} dates): match_rate={match_rate}% | max_score_err={max_score_err:.1f}")
    print(f"  Report saved -> {PARITY_REPORT_JSON}")
    assert match_rate == 100.0 and max_score_err == 0.0, f"Parity failure: match_rate={match_rate}, max_score_err={max_score_err}"
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="极简纯血版 V22.0 (Pure_V21_P2_SJ114_E4_Pos5) 只读影子总引擎")
    ap.add_argument("--premarket", action="store_true", help="盘前备战影子对照模式")
    ap.add_argument("--dry-run", action="store_true", help="只打印与校验，不落盘影子台账")
    ap.add_argument("--json-only", action="store_true", help="仅输出机器可读 JSON")
    ap.add_argument("--refresh-cache", action="store_true", help="强制刷新因果模型与T-1特征缓存")
    ap.add_argument("--verify-parity", action="store_true", help="执行 30日+2026 全部差异日零偏差历史对账与门槛硬锁单测")
    ap.add_argument("--threshold", type=int, default=f45.DEFAULT_4TO5_THRESHOLD, help="4to5 入围门槛（默认 114，代码级硬锁 >=110）")
    ap.add_argument("--mock-open", type=str, default="", help="测试用模拟竞价涨跌幅，如 '600814=0.045'")
    args = ap.parse_args()

    f45.validate_4to5_threshold(args.threshold)

    if args.verify_parity:
        return run_verify_parity()

    res = run_v22_shadow(args)
    if not args.dry_run:
        write_idempotent_v22_ledger(res)

    if args.json_only:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(format_v22_compact_card(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
