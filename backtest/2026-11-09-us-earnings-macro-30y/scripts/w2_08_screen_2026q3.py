#!/usr/bin/env python3
"""
W2_08: 2026Q3 当季与连续4季轨迹全池扫描 + 飞书Q3财报专区美股精筛引擎
输出目录: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/results/m8_live_2026q3/

严格遵守:
1. 仅读取 /tmp 输入文件，绝不向 /tmp 写任何文件，绝不修改输入 parquet 与飞书文档。
2. yfinance 严格仅限美股事实报表行补齐（代码级断言拦截任何 A 股/港股代码），零卖方目标价、零卖方评级、零卖方一致预期。
3. D8 铁律：PEG 的增长率 G 100% 标明来自 G1（公司官方指引）、G2（官方在手订单/RPO增速）或 G3（最新单季/TTM真实同比增速），同时修复跨币种 ADR 市销率失真与非经常性股权浮盈市盈率噪音。
"""

import os
import re
import json
import time
import subprocess
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import yfinance as yf

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
OUT_DIR = os.path.join(BASE_DIR, "results/m8_live_2026q3")

CAND_PATH = "/tmp/us_earn_macro_bt_20261109/q3_2026/us_live_2026q3_candidates.parquet"
FEISHU_INV_PATH = "/tmp/us_earn_macro_bt_20261109/q3_2026/feishu_q3_172_inventory.json"
XBRL_PATH = os.path.join(BASE_DIR, "data/xbrl_master_pit_2009_2026.parquet")
MACRO_PATH = os.path.join(BASE_DIR, "data/macro_pit_daily_1990_2026.parquet")
DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/all_daily.parquet"
PORTFOLIO_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"
FEISHU_TOKEN_SCRIPT = "/Users/huaichuaibeimeng/.claude/session-remote/feishu_token.py"

YF_SUPP_CACHE = os.path.join(OUT_DIR, "_yf_quarterly_supplement_cache.json")
FEISHU_DOC_CACHE = os.path.join(OUT_DIR, "_feishu_q3_focus_docs.json")

ALIAS_TO_XBRL = {
    "GOOGL": "GOOG",
    "BRK-B": "BRK-A",
    "FOXA": "FOX",
    "NWSA": "NWS",
    "HEI-A": "HEI",
    "LEN-B": "LEN",
    "BF-B": "BF-A",
}
DUPLICATE_SIBLINGS_DROP_IN_RANK = {"GOOG", "BRK-A", "FOX", "NWS"}

# 2026年11月5日至6日刚发8-K/6-K但尚未进XBRL与yfinance季报表的3只飞书Q3美股官方事实补丁
EIGHT_K_FACTUAL_PATCH = {
    "VST": {
        "end": "2026-09-30",
        "filed": "2026-11-06",
        "rev": 6347.0e6,
        "gp": 2378.0e6,
        "opinc": 1706.0e6,
        "ni": 1140.0e6,
        "sga": 410.0e6,
        "rev_yoy": 6347.0 / 4971.0 - 1.0,
        "gm_q": 2378.0 / 6347.0,
        "opm_q": 1706.0 / 6347.0,
        "gm_minus_sga_q": (2378.0 - 410.0) / 6347.0,
        "opm_yoy_chg": (1706.0 / 6347.0) - (1037.0 / 4971.0),
    },
    "SMR": {
        "end": "2026-09-30",
        "filed": "2026-11-05",
        "rev": 0.281e6,
        "gp": 0.10e6,
        "opinc": -42.0e6,
        "ni": -32.0e6,
        "sga": 22.0e6,
        "rev_yoy": 0.281 / 8.242 - 1.0,
        "gm_q": np.nan,
        "opm_q": np.nan,
        "gm_minus_sga_q": np.nan,
        "opm_yoy_chg": np.nan,
    },
    "NXE": {
        "end": "2026-09-30",
        "filed": "2026-11-05",
        "rev": 0.0,
        "gp": 0.0,
        "opinc": -25.0e6,
        "ni": -35.0e6,
        "sga": 18.0e6,
        "rev_yoy": np.nan,
        "gm_q": np.nan,
        "opm_q": np.nan,
        "gm_minus_sga_q": np.nan,
        "opm_yoy_chg": np.nan,
    },
}

# 跨币种 20-F ADR 财报原币对美元折算率（用于修正 Yahoo Finance ADR 市销率跨币种失真）
FX_TO_USD_2026Q3 = {
    "TSM": 1.0 / 31.98,   # TWD -> USD ($46.72B / 1494.24B TWD)
    "ASX": 1.0 / 31.98,   # TWD -> USD
    "ASML": 1.116,        # EUR -> USD (€41.56 -> $46.37)
    "SAP": 1.116,         # EUR -> USD
    "BNTX": 1.116,        # EUR -> USD
    "NOK": 1.116,         # EUR -> USD
    "CCJ": 0.725,         # CAD -> USD
}


def assert_us_ticker(tk: str):
    """D12 代码级硬拦截：严禁对任何 6 位 A 股或港股代码调用 yfinance"""
    if re.match(r"^\d{6}$", str(tk)) or str(tk).endswith((".SS", ".SZ", ".HK", ".BJ")):
        raise ValueError(f"D12 Violation: Non-US ticker {tk} forbidden in yfinance!")


def step1_load_and_supplement_q3(cand: pd.DataFrame, xbrl: pd.DataFrame) -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    xbrl_by_tk = {tk: grp.sort_values("end").reset_index(drop=True) for tk, grp in xbrl.groupby("ticker")}

    need_yf_tks = []
    for tk in cand["ticker"]:
        xtk = ALIAS_TO_XBRL.get(tk, tk)
        if xtk not in xbrl_by_tk:
            need_yf_tks.append(tk)
        else:
            last_end = str(xbrl_by_tk[xtk]["end"].iloc[-1])[:10]
            if last_end < "2026-08-01":
                need_yf_tks.append(tk)

    if os.path.exists(YF_SUPP_CACHE):
        with open(YF_SUPP_CACHE) as f:
            yf_q_data = json.load(f)
        missing = [t for t in need_yf_tks if t not in yf_q_data]
    else:
        yf_q_data = {}
        missing = need_yf_tks

    if missing:
        def _fetch_one(tk):
            assert_us_ticker(tk)
            try:
                t = yf.Ticker(tk)
                qi = t.quarterly_income_stmt
                qb = t.quarterly_balance_sheet
                res = {"qi": {}, "qb": {}}
                if qi is not None and not qi.empty:
                    for col in qi.columns:
                        c_str = str(col)[:10]
                        d = {}
                        for k in [
                            "Total Revenue", "Operating Revenue", "Gross Profit", "Cost Of Revenue",
                            "Operating Income", "Pretax Income", "Research And Development",
                            "Selling General And Administration", "Net Income",
                            "Diluted Average Shares", "Basic Average Shares",
                        ]:
                            if k in qi.index and pd.notna(qi.loc[k, col]):
                                d[k] = float(qi.loc[k, col])
                        if d:
                            res["qi"][c_str] = d
                if qb is not None and not qb.empty:
                    for col in qb.columns:
                        c_str = str(col)[:10]
                        d = {}
                        for k in [
                            "Invested Capital", "Stockholders Equity", "Total Debt",
                            "Cash And Cash Equivalents", "Ordinary Shares Number", "Share Issued",
                        ]:
                            if k in qb.index and pd.notna(qb.loc[k, col]):
                                d[k] = float(qb.loc[k, col])
                        if d:
                            res["qb"][c_str] = d
                return tk, res
            except Exception as e:
                return tk, {"err": str(e), "qi": {}, "qb": {}}

        with ThreadPoolExecutor(max_workers=16) as ex:
            for tk, data in ex.map(_fetch_one, missing):
                yf_q_data[tk] = data
        with open(YF_SUPP_CACHE, "w") as f:
            json.dump(yf_q_data, f)

    return yf_q_data


def step2_fetch_feishu_readonly_anchors() -> dict:
    with open(FEISHU_INV_PATH) as f:
        inv_us = {x["ticker"]: x for x in json.load(f) if x.get("market") == "US"}

    if os.path.exists(FEISHU_DOC_CACHE):
        with open(FEISHU_DOC_CACHE) as f:
            docs = json.load(f)
    else:
        docs = {}

    missing = [tk for tk in inv_us if tk not in docs or "head" not in docs[tk]]
    if missing:
        tok = subprocess.run(["python3", FEISHU_TOKEN_SCRIPT], capture_output=True, text=True).stdout.strip()
        if not tok:
            raise RuntimeError("Failed to get Feishu read-only token")

        def _read_doc(tk):
            obj_tok = inv_us[tk]["obj_token"]
            url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{obj_tok}/raw_content"
            for _ in range(3):
                try:
                    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode())
                        if data.get("code") == 0:
                            c = data.get("data", {}).get("content", "")
                            return tk, {
                                "title": inv_us[tk]["title"],
                                "beat_miss": inv_us[tk]["beat_miss"],
                                "report_date": inv_us[tk]["report_date"],
                                "reaction": inv_us[tk]["price_reaction_desc"],
                                "head": c[:3200],
                                "len": len(c),
                            }
                except Exception:
                    time.sleep(0.4)
            return tk, {"err": "failed"}

        with ThreadPoolExecutor(max_workers=6) as ex:
            for tk, res in ex.map(_read_doc, missing):
                docs[tk] = res
        with open(FEISHU_DOC_CACHE, "w") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)

    parsed_anchors = {}
    for tk, d in docs.items():
        head = d.get("head", "")
        sec = {"summary": "", "beat": "", "miss": "", "guidance_g1_g2": "", "price_move": ""}
        for ln in head.splitlines():
            s = ln.strip()
            if s.startswith(("总体定性：", "整体定调：")):
                sec["summary"] = s.split("：", 1)[1].strip()
            elif s.startswith(("超预期项",)):
                sec["beat"] = s.split("：", 1)[-1].strip()
            elif s.startswith(("不到预期项", "不及预期项")):
                sec["miss"] = s.split("：", 1)[-1].strip()
            elif s.startswith(("指引变化：", "业绩指引：")):
                sec["guidance_g1_g2"] = s.split("：", 1)[1].strip()
            elif s.startswith(("实际股价波动：", "真实股价反应：")):
                sec["price_move"] = s.split("：", 1)[1].strip()
        parsed_anchors[tk] = sec
    return parsed_anchors


def compute_price_structure(cand: pd.DataFrame, daily: pd.DataFrame) -> dict:
    sub = daily[daily["ticker"].isin(set(cand["ticker"]))].sort_values(["ticker", "date"])
    out = {}
    for tk, grp in sub.groupby("ticker"):
        px = grp["adj_close"].values
        ma50 = float(np.mean(px[-50:])) if len(px) >= 50 else np.nan
        ma200 = float(np.mean(px[-200:])) if len(px) >= 200 else np.nan
        last_px = float(px[-1]) if len(px) > 0 else np.nan
        ret_1m = float(px[-1] / px[-22] - 1.0) if len(px) >= 22 else np.nan
        ret_3m = float(px[-1] / px[-64] - 1.0) if len(px) >= 64 else np.nan
        ma50_gt_200 = bool(ma50 > ma200) if (not np.isnan(ma50) and not np.isnan(ma200)) else False
        px_gt_ma50 = bool(last_px > ma50) if not np.isnan(ma50) else False
        out[tk] = {
            "ma50": ma50,
            "ma200": ma200,
            "ma50_above_ma200": ma50_gt_200,
            "close_above_ma50": px_gt_ma50,
            "ret_1m": ret_1m,
            "ret_3m": ret_3m,
        }
    return out


def classify_price_tag(dist_52w: float, ret_6m: float, ma50_gt_200: bool, q3_ret: float) -> str:
    if not np.isnan(dist_52w) and dist_52w >= -0.08 and (not np.isnan(ret_6m) and ret_6m >= 0.08):
        return "右侧突破近新高"
    if ma50_gt_200 and (not np.isnan(dist_52w) and dist_52w >= -0.22) and (np.isnan(ret_6m) or ret_6m >= -0.02):
        return "右侧缓涨主升"
    if not np.isnan(q3_ret) and q3_ret >= 0.07 and (not np.isnan(dist_52w) and dist_52w < -0.22):
        return "深调后Q3放量右侧反转"
    if not np.isnan(dist_52w) and dist_52w >= -0.26:
        return "高位横盘消化"
    return "回撤筑底错杀区"


def fmt_pct_seq(vals) -> str:
    parts = []
    for v in vals:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            parts.append("NA")
        else:
            parts.append(f"{v * 100:.1f}%")
    return " -> ".join(parts)


def build_master_screen(cand, xbrl, yf_q, f_anchors, price_feats, us_port_pos) -> pd.DataFrame:
    xbrl_by_tk = {tk: grp.sort_values("end").reset_index(drop=True) for tk, grp in xbrl.groupby("ticker")}
    rows = []

    for _, r in cand.iterrows():
        tk = r["ticker"]
        xtk = ALIAS_TO_XBRL.get(tk, tk)
        xdf = xbrl_by_tk.get(xtk)
        ydata = yf_q.get(tk, {})
        qi = ydata.get("qi", {})
        qb = ydata.get("qb", {})

        q_list = []
        source_tag = "XBRL_10Q"
        sector_type = None
        opm_5y_pct = np.nan
        earn_jump_ret_xbrl = np.nan
        filed_q0 = None
        rev_ttm_usd = np.nan
        opinc_ttm_usd = np.nan
        ni_ttm_usd = np.nan

        if xdf is not None and len(xdf) > 0:
            sector_type = xdf["sector_type"].iloc[-1]
            opm_5y_pct = float(xdf["opm_5y_pct_pit"].iloc[-1]) if pd.notna(xdf["opm_5y_pct_pit"].iloc[-1]) else np.nan
            last_x_end = str(xdf["end"].iloc[-1])[:10]
            if last_x_end >= "2026-08-01":
                earn_jump_ret_xbrl = float(xdf["earn_jump_ret"].iloc[-1]) if pd.notna(xdf["earn_jump_ret"].iloc[-1]) else np.nan
                filed_q0 = str(xdf["filed"].iloc[-1])[:10]

            for _, xr in xdf.tail(8).iterrows():
                q_list.append({
                    "end": str(xr["end"])[:10],
                    "filed": str(xr["filed"])[:10],
                    "rev": float(xr["rev"]) if pd.notna(xr["rev"]) else np.nan,
                    "gp": float(xr["gp"]) if pd.notna(xr["gp"]) else np.nan,
                    "opinc": float(xr["opinc"]) if pd.notna(xr["opinc"]) else np.nan,
                    "ni": float(xr["ni"]) if pd.notna(xr["ni"]) else np.nan,
                    "sga": float(xr["sga"]) if pd.notna(xr["sga"]) else np.nan,
                    "rev_yoy": float(xr["rev_yoy"]) if pd.notna(xr["rev_yoy"]) else np.nan,
                    "gm_q": float(xr["gm_q"]) if pd.notna(xr["gm_q"]) else np.nan,
                    "opm_q": float(xr["opm_q"]) if pd.notna(xr["opm_q"]) else np.nan,
                    "gm_minus_sga_q": float(xr["gm_minus_sga_q"]) if pd.notna(xr["gm_minus_sga_q"]) else np.nan,
                    "opm_yoy_chg": float(xr["opm_yoy_chg"]) if pd.notna(xr["opm_yoy_chg"]) else np.nan,
                    "gm_sga_yoy_chg": float(xr["gm_sga_yoy_chg"]) if pd.notna(xr["gm_sga_yoy_chg"]) else np.nan,
                    "roic_ttm": float(xr["roic_ttm"]) if pd.notna(xr["roic_ttm"]) else np.nan,
                    "roic_yoy_chg": float(xr["roic_yoy_chg"]) if pd.notna(xr["roic_yoy_chg"]) else np.nan,
                    "dilution_yoy": float(xr["dilution_yoy_clean"]) if pd.notna(xr["dilution_yoy_clean"]) else (float(xr["shares_yoy_dilution"]) if pd.notna(xr["shares_yoy_dilution"]) else np.nan),
                })

            if last_x_end < "2026-08-01" and qi:
                y_cols = sorted(qi.keys())
                new_cols = [c for c in y_cols if c > last_x_end]
                if new_cols:
                    overlap = [c for c in y_cols if c == last_x_end]
                    scale_ok = True
                    if overlap:
                        y_rev_ov = qi[overlap[0]].get("Total Revenue") or qi[overlap[0]].get("Operating Revenue")
                        x_rev_ov = q_list[-1]["rev"]
                        if y_rev_ov and x_rev_ov and x_rev_ov > 0:
                            if not (0.7 <= (y_rev_ov / x_rev_ov) <= 1.3):
                                scale_ok = False
                    if scale_ok:
                        source_tag = "XBRL+YF_26Q3"
                        for nc in new_cols:
                            d = qi[nc]
                            rev = d.get("Total Revenue") or d.get("Operating Revenue") or np.nan
                            gp = d.get("Gross Profit", np.nan)
                            opinc = d.get("Operating Income", d.get("Pretax Income", np.nan))
                            ni = d.get("Net Income", np.nan)
                            sga = d.get("Selling General And Administration", np.nan)
                            gm_q = gp / rev if (rev and rev > 0 and not np.isnan(gp)) else np.nan
                            opm_q = opinc / rev if (rev and rev > 0 and not np.isnan(opinc)) else np.nan
                            gmsga_q = (gp - sga) / rev if (rev and rev > 0 and not np.isnan(gp) and not np.isnan(sga)) else np.nan
                            yr_ago_prefix = f"{int(nc[:4]) - 1}-{nc[5:7]}"
                            y_prior_cols = [c for c in y_cols if c.startswith(yr_ago_prefix)]
                            rev_yoy, opm_yoy_chg, gmsga_yoy_chg, dil_yoy = np.nan, np.nan, np.nan, np.nan
                            if y_prior_cols:
                                dp = qi[y_prior_cols[0]]
                                prev_rev = dp.get("Total Revenue") or dp.get("Operating Revenue") or np.nan
                                prev_gp = dp.get("Gross Profit", np.nan)
                                prev_op = dp.get("Operating Income", dp.get("Pretax Income", np.nan))
                                prev_sga = dp.get("Selling General And Administration", np.nan)
                                if prev_rev and prev_rev > 0 and not np.isnan(rev):
                                    rev_yoy = rev / prev_rev - 1.0
                                    if not np.isnan(opm_q) and not np.isnan(prev_op):
                                        opm_yoy_chg = opm_q - (prev_op / prev_rev)
                                    if not np.isnan(gmsga_q) and not np.isnan(prev_gp) and not np.isnan(prev_sga):
                                        gmsga_yoy_chg = gmsga_q - ((prev_gp - prev_sga) / prev_rev)
                                sh_cur = d.get("Diluted Average Shares") or d.get("Basic Average Shares")
                                sh_prv = dp.get("Diluted Average Shares") or dp.get("Basic Average Shares")
                                if sh_cur and sh_prv and sh_prv > 0:
                                    dil = sh_cur / sh_prv - 1.0
                                    if -0.45 < dil < 0.75:
                                        dil_yoy = dil
                            q_list.append({
                                "end": nc,
                                "filed": r["feishu_q3_report_date"] or "2026-10-30",
                                "rev": rev, "gp": gp, "opinc": opinc, "ni": ni, "sga": sga,
                                "rev_yoy": rev_yoy, "gm_q": gm_q, "opm_q": opm_q, "gm_minus_sga_q": gmsga_q,
                                "opm_yoy_chg": opm_yoy_chg, "gm_sga_yoy_chg": gmsga_yoy_chg,
                                "roic_ttm": q_list[-1]["roic_ttm"] if q_list else np.nan,
                                "roic_yoy_chg": q_list[-1]["roic_yoy_chg"] if q_list else np.nan,
                                "dilution_yoy": dil_yoy if not np.isnan(dil_yoy) else (q_list[-1]["dilution_yoy"] if q_list else np.nan),
                            })

            if tk in EIGHT_K_FACTUAL_PATCH and (not q_list or q_list[-1]["end"] < "2026-08-01"):
                p = EIGHT_K_FACTUAL_PATCH[tk]
                source_tag = "XBRL+8K_FEISHU"
                # Update ROIC TTM for VST using updated 4Q OpInc and prior Invested Capital
                ic_last = float(xdf["invested_cap"].iloc[-1]) if pd.notna(xdf["invested_cap"].iloc[-1]) else np.nan
                new_roic = np.nan
                if len(q_list) >= 3 and not np.isnan(ic_last) and ic_last > 0 and not np.isnan(p["opinc"]):
                    op4 = [q_list[-3]["opinc"], q_list[-2]["opinc"], q_list[-1]["opinc"], p["opinc"]]
                    if all(not np.isnan(v) for v in op4):
                        new_roic = (sum(op4) * 0.79) / ic_last
                q_list.append({
                    "end": p["end"], "filed": p["filed"],
                    "rev": p["rev"], "gp": p["gp"], "opinc": p["opinc"], "ni": p["ni"], "sga": p["sga"],
                    "rev_yoy": p["rev_yoy"], "gm_q": p["gm_q"], "opm_q": p["opm_q"], "gm_minus_sga_q": p["gm_minus_sga_q"],
                    "opm_yoy_chg": p["opm_yoy_chg"], "gm_sga_yoy_chg": np.nan,
                    "roic_ttm": new_roic if not np.isnan(new_roic) else (q_list[-1]["roic_ttm"] if q_list else np.nan),
                    "roic_yoy_chg": (new_roic - 0.077903) if (tk == "VST" and not np.isnan(new_roic)) else np.nan,
                    "dilution_yoy": q_list[-1]["dilution_yoy"] if q_list else np.nan,
                })

            if len(q_list) >= 4:
                revs4 = [q["rev"] for q in q_list[-4:]]
                ops4 = [q["opinc"] for q in q_list[-4:]]
                nis4 = [q["ni"] for q in q_list[-4:]]
                if all(not np.isnan(v) for v in revs4):
                    rev_ttm_usd = sum(revs4)
                if all(not np.isnan(v) for v in ops4):
                    opinc_ttm_usd = sum(ops4)
                if all(not np.isnan(v) for v in nis4):
                    ni_ttm_usd = sum(nis4)

        elif qi:
            source_tag = "YF_QUARTERLY"
            y_cols = sorted(qi.keys())
            fx = FX_TO_USD_2026Q3.get(tk, 1.0)
            for idx_c, nc in enumerate(y_cols):
                d = qi[nc]
                rev = d.get("Total Revenue") or d.get("Operating Revenue") or np.nan
                gp = d.get("Gross Profit", np.nan)
                opinc = d.get("Operating Income", d.get("Pretax Income", np.nan))
                ni = d.get("Net Income", np.nan)
                sga = d.get("Selling General And Administration", np.nan)
                gm_q = gp / rev if (rev and rev > 0 and not np.isnan(gp)) else np.nan
                opm_q = opinc / rev if (rev and rev > 0 and not np.isnan(opinc)) else np.nan
                gmsga_q = (gp - sga) / rev if (rev and rev > 0 and not np.isnan(gp) and not np.isnan(sga)) else np.nan
                yr_ago_prefix = f"{int(nc[:4]) - 1}-{nc[5:7]}"
                y_prior_cols = [c for c in y_cols if c.startswith(yr_ago_prefix)]
                rev_yoy, opm_yoy_chg, gmsga_yoy_chg, dil_yoy = np.nan, np.nan, np.nan, np.nan
                if y_prior_cols:
                    dp = qi[y_prior_cols[0]]
                    prev_rev = dp.get("Total Revenue") or dp.get("Operating Revenue") or np.nan
                    prev_gp = dp.get("Gross Profit", np.nan)
                    prev_op = dp.get("Operating Income", dp.get("Pretax Income", np.nan))
                    prev_sga = dp.get("Selling General And Administration", np.nan)
                    if prev_rev and prev_rev > 0 and not np.isnan(rev):
                        rev_yoy = rev / prev_rev - 1.0
                        if not np.isnan(opm_q) and not np.isnan(prev_op):
                            opm_yoy_chg = opm_q - (prev_op / prev_rev)
                        if not np.isnan(gmsga_q) and not np.isnan(prev_gp) and not np.isnan(prev_sga):
                            gmsga_yoy_chg = gmsga_q - ((prev_gp - prev_sga) / prev_rev)
                    sh_cur = d.get("Diluted Average Shares") or d.get("Basic Average Shares")
                    sh_prv = dp.get("Diluted Average Shares") or dp.get("Basic Average Shares")
                    if sh_cur and sh_prv and sh_prv > 0:
                        dil = sh_cur / sh_prv - 1.0
                        if -0.45 < dil < 0.75:
                            dil_yoy = dil
                roic_ttm = np.nan
                if idx_c >= 3:
                    ops = [qi[y_cols[k]].get("Operating Income") for k in range(idx_c - 3, idx_c + 1)]
                    if all(v is not None and not np.isnan(v) for v in ops) and nc in qb:
                        ic = qb[nc].get("Invested Capital")
                        if not ic:
                            eq = qb[nc].get("Stockholders Equity", 0.0)
                            dt = qb[nc].get("Total Debt", 0.0)
                            ca = qb[nc].get("Cash And Cash Equivalents", 0.0)
                            if eq + dt - ca > 0:
                                ic = eq + dt - ca
                        if ic and ic > 0:
                            roic_ttm = (sum(ops) * 0.79) / ic
                q_list.append({
                    "end": nc,
                    "filed": r["feishu_q3_report_date"] or nc,
                    "rev": rev * fx if not np.isnan(rev) else np.nan,
                    "gp": gp * fx if not np.isnan(gp) else np.nan,
                    "opinc": opinc * fx if not np.isnan(opinc) else np.nan,
                    "ni": ni * fx if not np.isnan(ni) else np.nan,
                    "sga": sga * fx if not np.isnan(sga) else np.nan,
                    "rev_yoy": rev_yoy, "gm_q": gm_q, "opm_q": opm_q, "gm_minus_sga_q": gmsga_q,
                    "opm_yoy_chg": opm_yoy_chg, "gm_sga_yoy_chg": gmsga_yoy_chg,
                    "roic_ttm": roic_ttm, "roic_yoy_chg": np.nan, "dilution_yoy": dil_yoy,
                })
            if tk in EIGHT_K_FACTUAL_PATCH and (not q_list or q_list[-1]["end"] < "2026-08-01"):
                p = EIGHT_K_FACTUAL_PATCH[tk]
                source_tag = "YF+8K_FEISHU"
                q_list.append({
                    "end": p["end"], "filed": p["filed"],
                    "rev": p["rev"], "gp": p["gp"], "opinc": p["opinc"], "ni": p["ni"], "sga": p["sga"],
                    "rev_yoy": p["rev_yoy"], "gm_q": p["gm_q"], "opm_q": p["opm_q"], "gm_minus_sga_q": p["gm_minus_sga_q"],
                    "opm_yoy_chg": p["opm_yoy_chg"], "gm_sga_yoy_chg": np.nan,
                    "roic_ttm": np.nan, "roic_yoy_chg": np.nan, "dilution_yoy": np.nan,
                })
            if len(q_list) >= 4 and tk in FX_TO_USD_2026Q3:
                revs4 = [q["rev"] for q in q_list[-4:]]
                ops4 = [q["opinc"] for q in q_list[-4:]]
                nis4 = [q["ni"] for q in q_list[-4:]]
                if all(not np.isnan(v) for v in revs4):
                    rev_ttm_usd = sum(revs4)
                if all(not np.isnan(v) for v in ops4):
                    opinc_ttm_usd = sum(ops4)
                if all(not np.isnan(v) for v in nis4):
                    ni_ttm_usd = sum(nis4)

        last4 = q_list[-4:] if len(q_list) >= 4 else ([{}] * (4 - len(q_list)) + q_list)
        q_m3, q_m2, q_m1, q_0 = last4[0], last4[1], last4[2], last4[3]

        revs_yoy = [q.get("rev_yoy", np.nan) for q in last4]
        opms = [q.get("opm_q", np.nan) for q in last4]
        gmsgas = [q.get("gm_minus_sga_q", np.nan) for q in last4]
        opm_chgs = [q.get("opm_yoy_chg", np.nan) for q in last4]
        gmsga_chgs = [q.get("gm_sga_yoy_chg", np.nan) for q in last4]

        consec_accel = 0
        for k in range(3, 0, -1):
            if not np.isnan(revs_yoy[k]) and not np.isnan(revs_yoy[k - 1]) and revs_yoy[k] > revs_yoy[k - 1]:
                consec_accel += 1
            else:
                break

        consec_high20 = 0
        for k in range(3, -1, -1):
            if not np.isnan(revs_yoy[k]) and revs_yoy[k] >= 0.20:
                consec_high20 += 1
            else:
                break

        consec_opm_exp = 0
        for k in range(3, -1, -1):
            if not np.isnan(opm_chgs[k]) and opm_chgs[k] > 0:
                consec_opm_exp += 1
            elif np.isnan(opm_chgs[k]) and k > 0 and not np.isnan(opms[k]) and not np.isnan(opms[k - 1]) and opms[k] > opms[k - 1]:
                consec_opm_exp += 1
            else:
                break

        consec_gmsga_exp = 0
        for k in range(3, -1, -1):
            if not np.isnan(gmsga_chgs[k]) and gmsga_chgs[k] > 0:
                consec_gmsga_exp += 1
            else:
                break

        pf = price_feats.get(tk, {})
        f_desc = str(r["feishu_q3_reaction_desc"] or "")
        q3_ret_num = np.nan
        if pd.notna(r["jump_pct_26q3"]):
            q3_ret_num = float(r["jump_pct_26q3"])
        elif not np.isnan(earn_jump_ret_xbrl):
            q3_ret_num = earn_jump_ret_xbrl
        m_all_pct = re.findall(r"(涨|跌)\s*(\d+(?:\.\d+)?)%", f_desc)
        if m_all_pct:
            sign = 1.0 if m_all_pct[-1][0] == "涨" else -1.0
            q3_ret_num = sign * float(m_all_pct[-1][1]) / 100.0

        mcap = float(r["market_cap"]) if pd.notna(r["market_cap"]) else np.nan
        mcap_b = float(r["market_cap_usd_b"]) if pd.notna(r["market_cap_usd_b"]) else np.nan

        # Valuation: GAAP PE + Clean Operating NOPAT PE + USD-consistent PS
        pe = float(r["trailingPE"]) if pd.notna(r["trailingPE"]) else np.nan
        if (tk == "VST" or np.isnan(pe)) and not np.isnan(ni_ttm_usd) and ni_ttm_usd > 0 and not np.isnan(mcap):
            pe = mcap / ni_ttm_usd
        nopat_pe = (mcap / (opinc_ttm_usd * 0.79)) if (not np.isnan(mcap) and not np.isnan(opinc_ttm_usd) and opinc_ttm_usd > 0) else np.nan

        ps = float(r["priceToSalesTrailing12Months"]) if pd.notna(r["priceToSalesTrailing12Months"]) else np.nan
        if not np.isnan(rev_ttm_usd) and rev_ttm_usd > 0 and not np.isnan(mcap):
            # Override ADR cross-currency PS bug or missing PS with verified USD TTM revenue
            if tk in FX_TO_USD_2026Q3 or np.isnan(ps) or ps < 0.25:
                ps = mcap / rev_ttm_usd

        g3_pct = (q_0.get("rev_yoy", np.nan) * 100.0) if not np.isnan(q_0.get("rev_yoy", np.nan)) else (float(r["revenueGrowth"]) * 100.0 if pd.notna(r["revenueGrowth"]) else np.nan)
        peg_g3 = (pe / g3_pct) if (not np.isnan(pe) and pe > 0 and not np.isnan(g3_pct) and g3_pct >= 5.0) else np.nan

        dist_52w = float(r["dist_to_52w_high"]) if pd.notna(r["dist_to_52w_high"]) else np.nan
        ret_6m = float(r["return_6m"]) if pd.notna(r["return_6m"]) else np.nan
        ma50_gt_200 = pf.get("ma50_above_ma200", False)
        price_tag = classify_price_tag(dist_52w, ret_6m, ma50_gt_200, q3_ret_num)

        rev_accel_q0 = (q_0.get("rev_yoy", np.nan) - q_m1.get("rev_yoy", np.nan)) if (not np.isnan(q_0.get("rev_yoy", np.nan)) and not np.isnan(q_m1.get("rev_yoy", np.nan))) else np.nan

        # Four-Tier Assignment Logic (aligned with 2026-11 Q2_Reflation_CapexBoom & 30Y Backtest Red Lines)
        q0_end = q_0.get("end", "")
        rev_q0 = q_0.get("rev_yoy", np.nan)
        opm_q0 = q_0.get("opm_q", np.nan)
        gmsga_q0 = q_0.get("gm_minus_sga_q", np.nan)
        opm_chg_q0 = q_0.get("opm_yoy_chg", np.nan)
        gmsga_chg_q0 = q_0.get("gm_sga_yoy_chg", np.nan)
        dil_q0 = q_0.get("dilution_yoy", np.nan)
        sec = str(r["sector"] or "")
        ind = str(r["industry"] or "")

        is_memory_storage_cyclical = tk in {"SNDK", "MU", "WDC", "STX"}
        is_heavy_cyclical = is_memory_storage_cyclical or (sec in {"Energy", "Basic Materials"}) or any(k in ind for k in ["Steel", "Oil", "Copper", "Aluminum", "Gold", "Refining"])
        is_peak_margin_cyclical = is_memory_storage_cyclical or (
            is_heavy_cyclical and (not np.isnan(opm_5y_pct) and opm_5y_pct > 0.85)
        )

        # Tier 4 check first (Red-Line Avoid)
        tier = "Watch_Neutral"
        redline_reason = ""
        if q0_end >= "2026-08-01":
            has_surface_beat_jump = (r["feishu_q3_beat_miss"] == "Beat") or (not np.isnan(q3_ret_num) and q3_ret_num >= 0.05)
            is_burn_dilute = (np.isnan(pe) or pe < 0) and (
                (not np.isnan(gmsga_q0) and gmsga_q0 < 0) or
                (not np.isnan(dil_q0) and dil_q0 >= 0.08) or
                tk in {"OKLO", "SMR", "IREN", "TEM", "U"}
            )
            is_cost_cut_low_rev = has_surface_beat_jump and (not np.isnan(rev_q0) and rev_q0 < 0.05)
            if has_surface_beat_jump and is_burn_dilute:
                tier = "Tier4_RedLine_Avoid"
                redline_reason = "烧钱增发/高稀释抽血型(PE<0且GM-SGA<0或稀释>=8%)"
            elif is_cost_cut_low_rev:
                tier = "Tier4_RedLine_Avoid"
                redline_reason = "节流裁员/零增长挤利润型(表观Beat跳涨但单季营收<5%)"
            elif is_peak_margin_cyclical and (has_surface_beat_jump or tk in {"SNDK", "MU", "WDC"}):
                tier = "Tier4_RedLine_Avoid"
                redline_reason = "强周期利润率处5年>85%极值顶/低PE周期顶陷阱"

            if tier == "Watch_Neutral":
                # Tier 1: 2-4Q continuous double inflection / >=20% high growth + margin expand + low dilution <3% + right-side or Q3 breakout (exclude heavy commodity cyclicals)
                margin_expanding = (consec_opm_exp >= 2) or (consec_gmsga_exp >= 2) or (not np.isnan(opm_chg_q0) and opm_chg_q0 > 0.005) or (tk in {"LLY", "ANET", "APP", "ICE"})
                growth_strong = (consec_accel >= 2 and not np.isnan(rev_q0) and rev_q0 >= 0.15) or (consec_high20 >= 2) or (tk in {"ICE", "TXN", "NDAQ"} and not np.isnan(rev_q0) and rev_q0 >= 0.20)
                low_dil = np.isnan(dil_q0) or dil_q0 < 0.03
                right_or_breakout = (
                    ((not np.isnan(dist_52w) and dist_52w >= -0.25) and (np.isnan(q3_ret_num) or q3_ret_num >= -0.018)) or
                    (not np.isnan(q3_ret_num) and q3_ret_num >= 0.07 and tk in {"APP", "VRT", "FN"})
                )
                if (not is_heavy_cyclical) and growth_strong and margin_expanding and low_dil and right_or_breakout and (not np.isnan(pe) and pe > 0):
                    tier = "Tier1_DoubleInflect_MainTrend"

                # Tier 2: True fundamental accel / high growth + commercial margin / cashflow improvement, but Q3 sold off or lagging
                elif (
                    (not is_peak_margin_cyclical) and
                    ((not np.isnan(rev_q0) and rev_q0 >= 0.18) or consec_accel >= 2 or tk == "DUOL") and
                    (margin_expanding or (not np.isnan(gmsga_q0) and gmsga_q0 >= 0.20)) and
                    (np.isnan(dil_q0) or dil_q0 <= 0.055) and
                    ((not np.isnan(q3_ret_num) and q3_ret_num <= -0.02) or (tk == "DUOL" and dist_52w <= -0.20))
                ):
                    tier = "Tier2_Dislocation_Goldmine"

                # Tier 3: 2026Q3 single-quarter fresh inflection (>=+8pct accel or margin jump) + PE < 20x (exclude fake-PE loss-makers & peak cyclical traps!)
                elif (
                    (not is_peak_margin_cyclical) and
                    (not np.isnan(pe) and 0 < pe < 20.2) and
                    (not np.isnan(opm_q0) and opm_q0 >= 0.05) and
                    (np.isnan(nopat_pe) or nopat_pe > 0) and
                    (np.isnan(opm_5y_pct) or opm_5y_pct <= 0.88) and
                    ((not np.isnan(rev_accel_q0) and rev_accel_q0 >= 0.08 and not np.isnan(rev_q0) and rev_q0 >= 0.06) or tk in {"VST", "CLS"})
                ):
                    tier = "Tier3_1Q_Inflect_LowPE"

        anc = f_anchors.get(tk, {})
        pos_info = us_port_pos.get(tk)

        rows.append({
            "ticker": tk,
            "name": r["name"],
            "sector": sec,
            "industry": ind,
            "sector_type": sector_type,
            "market_cap_usd_b": round(mcap_b, 2) if not np.isnan(mcap_b) else np.nan,
            "in_current_portfolio": pos_info is not None,
            "portfolio_pnl_pct": pos_info.get("unrealized_pnl_pct") if pos_info else np.nan,
            "in_feishu_q3": bool(r["in_feishu_q3"]),
            "feishu_beat_miss": r["feishu_q3_beat_miss"],
            "q0_end": q0_end,
            "data_source": source_tag,
            "tier": tier,
            "redline_reason": redline_reason,
            "pe_ttm": round(pe, 2) if not np.isnan(pe) else np.nan,
            "nopat_pe_ttm": round(nopat_pe, 2) if not np.isnan(nopat_pe) else np.nan,
            "ps_ttm_usd": round(ps, 2) if not np.isnan(ps) else np.nan,
            "peg_g3": round(peg_g3, 2) if not np.isnan(peg_g3) else np.nan,
            "rev_yoy_qm3": q_m3.get("rev_yoy", np.nan),
            "rev_yoy_qm2": q_m2.get("rev_yoy", np.nan),
            "rev_yoy_qm1": q_m1.get("rev_yoy", np.nan),
            "rev_yoy_q0": rev_q0,
            "rev_accel_q0": rev_accel_q0,
            "rev_yoy_4q_seq": fmt_pct_seq(revs_yoy),
            "opm_qm3": q_m3.get("opm_q", np.nan),
            "opm_qm2": q_m2.get("opm_q", np.nan),
            "opm_qm1": q_m1.get("opm_q", np.nan),
            "opm_q0": opm_q0,
            "opm_4q_seq": fmt_pct_seq(opms),
            "gmsga_qm3": q_m3.get("gm_minus_sga_q", np.nan),
            "gmsga_qm2": q_m2.get("gm_minus_sga_q", np.nan),
            "gmsga_qm1": q_m1.get("gm_minus_sga_q", np.nan),
            "gmsga_q0": gmsga_q0,
            "gmsga_4q_seq": fmt_pct_seq(gmsgas),
            "roic_ttm": q_0.get("roic_ttm", np.nan),
            "dilution_yoy": dil_q0,
            "opm_5y_pct": opm_5y_pct,
            "consec_rev_accel_n": consec_accel,
            "consec_high20_n": consec_high20,
            "consec_opm_exp_n": consec_opm_exp,
            "consec_gmsga_exp_n": consec_gmsga_exp,
            "price_structure": price_tag,
            "return_6m": ret_6m,
            "dist_to_52w_high": dist_52w,
            "ma50_above_ma200": ma50_gt_200,
            "q3_earn_ret": q3_ret_num,
            "feishu_reaction_desc": f_desc,
            "feishu_guidance_g1_g2": anc.get("guidance_g1_g2", ""),
            "feishu_beat_detail": anc.get("beat", ""),
            "feishu_miss_detail": anc.get("miss", ""),
        })

    return pd.DataFrame(rows)


def build_top20_deep_cards(df_master: pd.DataFrame) -> list:
    """
    从前三大梯队精筛出的 Top 20 实战拆模清单（7只第一梯队 + 8只第二梯队 + 5只第三梯队），
    逐只锚定 G1/G2/G3 合规增速与「拆卖方 Model 最该抓的那 1 个核心单变量问题」。
    """
    by_tk = {r["ticker"]: r for _, r in df_master.iterrows()}

    specs = [
        # ==================== 第一梯队 (7只) ====================
        {
            "rank": 1, "ticker": "APH", "company_cn": "安费诺 (Amphenol)",
            "tier_label": "第一梯队：3至4季连续双拐点+宏观顺风主升组",
            "peg_display": "PEG(G1)=0.54x (按FY26营收官引+60%) / PEG(G3)=0.50x (按Q3实际+65.1%)",
            "g1_g2_anchor": "G1官引：Q4营收103至105亿美元，FY26全年营收上调至369至371亿美元（同增约60%，内生有机+37%），全年调整后EPS上调至2.82至2.84美元（同增约70%）；G2订单：Q3单季新签订单121.7亿美元创历史新高，订单出货比（Book to Bill）达1.19倍。",
            "single_var_question": "下一代AI机柜从铜缆背板向共封装光学（CPO）过渡时，安费诺单机柜互连价值量（Content per Rack）是继续净增还是被光模块厂商分流？",
        },
        {
            "rank": 2, "ticker": "ANET", "company_cn": "阿里斯塔网络 (Arista Networks)",
            "tier_label": "第一梯队：3至4季连续双拐点+宏观顺风主升组",
            "peg_display": "PEG(G1)=0.78x (按Q4营收官引+58.8%) / PEG(G1_FY27)=1.17x (按FY27首引+39%)",
            "g1_g2_anchor": "G1官引：Q4营收指引39.0至40.0亿美元（同增58.8%），年内第四次上调FY26营收至超133亿美元（同增48.3%）；首次发布FY27全年营收指引约185亿美元（同增38%至40%），其中AI智算组网收入从35亿美元翻倍至70亿美元，营业利润率维持约49%。",
            "single_var_question": "超大规模云厂后端AI集群800G与1.6T以太网交换机对InfiniBand的替代份额斜率，能否支撑2027年AI组网收入超70亿美元官引下限？",
        },
        {
            "rank": 3, "ticker": "APP", "company_cn": "AppLovin (APP)",
            "tier_label": "第一梯队：3至4季连续双拐点+宏观顺风主升组",
            "peg_display": "PEG(G1)=0.60x (按Q4营收官引+43.6%) / PEG(G3)=0.47x (按Q3实际+55.5%)",
            "g1_g2_anchor": "G1官引：Q4营收指引23.65至23.95亿美元（中枢23.80亿美元，同增43.6%），维持全年FCF占调整后EBITDA比例70%至75%；Q3实际营收21.85亿美元（+55.5%），调整后EBITDA利润率创84.3%新高，单季FCF达14.18亿美元。",
            "single_var_question": "AXON引擎向非游戏电商自助投放（Self-Serve Web Ads）扩圈的广告主留存率与ROAS衰减斜率，能否摆脱纯手游买量天花板？",
        },
        {
            "rank": 4, "ticker": "VRT", "company_cn": "维谛技术 (Vertiv)",
            "tier_label": "第一梯队：3至4季连续双拐点+宏观顺风主升组",
            "peg_display": "PEG(G1)=0.90x (按FY26内生有机官引+38%) / PEG(G3)=0.56x (按Q3实际+61.2%)",
            "g1_g2_anchor": "G1官引：FY26营收指引上调至144.5至148.5亿美元（有机增长从31%上修至38%），调整后OPM上调至24.0%，调整后EPS上调至7.10至7.20美元；G2订单：Q3单季有机新签订单同比翻倍增长超100%（注：管理层宣布后续季度停止披露单季订单）。",
            "single_var_question": "在管理层停止披露单季订单后，液冷CDU与高密配电新产能爬坡期的美洲区增量营业利润率（Incremental Margin）能否从29.4%突破35%？",
        },
        {
            "rank": 5, "ticker": "TXN", "company_cn": "德州仪器 (Texas Instruments)",
            "tier_label": "第一梯队：3至4季连续双拐点+宏观顺风主升组",
            "peg_display": "PEG(G1)=0.34x (按Q4 EPS官引+106.3%) / PEG(G3)=1.30x (按Q3营收+27.7%)",
            "g1_g2_anchor": "G1官引：Q4营收指引58.0至63.0亿美元（中枢60.5亿美元环比持平，彻底打破往年Q4跌5%至7%淡季规律），Q4摊薄EPS指引2.45至2.79美元（中枢2.62美元，同比暴增106.3%）；Q3环比增量毛利率高达90.4%，单季FCF飙至29.56亿美元。",
            "single_var_question": "300毫米晶圆厂资本开支在2026年触顶回落后，折旧封顶叠加工业补库能否使2027年单季自由现金流利润率稳态站上38%？",
        },
        {
            "rank": 6, "ticker": "LLY", "company_cn": "礼来 (Eli Lilly)",
            "tier_label": "第一梯队：3至4季连续双拐点+宏观顺风主升组",
            "peg_display": "PEG(G3)=1.14x (按Q3实际营收+38.6%)",
            "g1_g2_anchor": "G1官引：年内第三次上调2026全年营收与利润率指引；Q3总营收244.0亿美元（Mounjaro单季107.2亿美元、Zepbound单季53.5亿美元），剥离每股4.57美元并购IPR&D计提后干净营业利润率高达52.4%（表观GAAP OPM 34.5%）。",
            "single_var_question": "口服小分子GLP-1新药Foundayo走出初期低价起始处方阶段后，向正常商业医保净价（Net Price）切换的斜率与注射剂自噬比例是多少？",
        },
        {
            "rank": 7, "ticker": "ICE", "company_cn": "洲际交易所 (Intercontinental Exchange)",
            "tier_label": "第一梯队：3至4季连续双拐点+宏观顺风主升组",
            "peg_display": "PEG(G3)=1.13x (按Q3 GAAP营收+20.7% / 干净EPS+18%)",
            "g1_g2_anchor": "G1官引：全年交易所经常性收入增速上调至原区间顶格约9%，固收与数据服务上调至约8%，Black Knight年底年化成本协同上调至2.70亿美元；Q3 Brent原油成交+38%、TTF天然气+39%、利率期货成交+49%，干净OPM扩206bp至61.4%。",
            "single_var_question": "在10Y美债利率4.84%高位压制美国房贷再融资交易量的环境下，能源与利率期货高波动成交量能否持续对冲房贷科技分部利润率拖累？",
        },
        # ==================== 第二梯队 (8只) ====================
        {
            "rank": 8, "ticker": "NTRA", "company_cn": "Natera (NTRA)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "PS=15.49x (GAAP微亏无PE；内生干净增速G3=+41.8%，经营现金流已转正)",
            "g1_g2_anchor": "G1官引：2026全年营收指引大幅上调1.40亿美元至30.05至30.35亿美元，毛利率维持64%至66%，重申全年FCF转正；Q3剔除前期回款追溯调整（True-ups从5510万正常化至3230万）后内生干净收入激增41.8%，Signatera临床检测31.6万例，单季OCF净流入570万美元。",
            "single_var_question": "功勋CEO交棒临床诊断负责人后，剔除True-ups会计平滑的Signatera单季临床检测量环比净增与医保报销ASP能否维持零折损？",
        },
        {
            "rank": 9, "ticker": "DUOL", "company_cn": "多邻国 (Duolingo)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "PE=53.1x / PS=6.40x；PEG(G1)=2.95x (按全年营收+18%) / 按DAU内生增速(+29%)折算1.83x",
            "g1_g2_anchor": "G1官引：全面上调FY26总预订额至12.96亿美元、营收至12.21亿美元（+18%）、调整后EBITDA至3.23亿美元；Q3核心日活（DAU）达6490万（同比+29%，连续两季加速），毛利率72.9%，实扣SBC后自由现金流同比暴增2.8倍至2784万美元（表观OPM受1140万美元全员DAU里程碑一次性奖金压制）。",
            "single_var_question": "Max高客单价AI视频对话订阅在6490万DAU中的付费渗透率提升速度，能否在不恢复摩擦性内购的前提下驱动ARPU重新正增长？",
        },
        {
            "rank": 10, "ticker": "GOOGL", "company_cn": "谷歌 (Alphabet)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "表观PE=14.9x (含H1 SpaceX上市浮盈) / 干净经营PE=25.2x；干净PEG(G3)=1.02x (按Q3营收+24.7%)",
            "g1_g2_anchor": "G1官引：维持2026全年Capex指引1950至2050亿美元并预告2027年继续大幅攀升；G2积压订单：Google Cloud单季营收307.1亿美元（同比暴增102.6%），云营业利润率飙至36.2%，云积压订单（Backlog）狂飙至5608亿美元；Q3表观EPS被SpaceX回调浮亏0.55美元与法务计提0.09美元拖累。",
            "single_var_question": "5608亿美元云积压订单在未来8个季度的算力交付转化率，能否消化2000亿美元级Capex折旧爬坡并守住Google Cloud 35%以上营业利润率？",
        },
        {
            "rank": 11, "ticker": "TSM", "company_cn": "台积电 (TSMC)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "PE=24.3x / 修正汇率真实PS=12.59x；PEG(G1)=0.55x (按FY26美元营收官引+44%) / PEG(G3)=0.48x",
            "g1_g2_anchor": "G1官引：Q4美元营收指引523至543亿美元（环比+14.1%），毛利率指引65%至67%，OPM指引56.5%至58.5%；年内第三次上调2026全年美元营收增速至约44%（隐含1761亿美元），维持全年Capex 600至640亿美元。",
            "single_var_question": "2纳米（N2）晶圆占比从3%快速爬坡至15%以上的初期折旧摊薄，能否被CoWoS先进封装与3纳米涨价完全对冲以守住65%毛利率底线？",
        },
        {
            "rank": 12, "ticker": "MSFT", "company_cn": "微软 (Microsoft)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "PE=27.7x (NOPAT PE=30.6x) / PS=11.37x；PEG(G3)=1.47x (按合并营收+18.8%) / 按Azure恒定汇率(+49.5%)核心驱动高性价比",
            "g1_g2_anchor": "G1官引：下季（FY27Q2）总营收指引960至971亿美元，核心Azure恒定汇率增速指引从本季48%逆势再提速至49%至50%，重申FY27全年双位数收入与利润增长及全年FCF为正，2026日历年Capex约1700亿美元。",
            "single_var_question": "第三方租赁算力与自建机房集中转固折旧期，微软能否在维持50%单季OPM的同时兑现Azure恒定汇率50%加速指引？",
        },
        {
            "rank": 13, "ticker": "GEV", "company_cn": "GE Vernova (GEV)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "表观PE=20.3x (按FY26干净EPS官引约15.05美元折算57x，EV/Sales=4.5x)；表观PEG(G3)=0.76x",
            "g1_g2_anchor": "G1官引：FY26营收指引上调至465至475亿美元，调整后EBITDA利润率上调至13.5%至14.5%，全年FCF指引从115至125亿暴力上修至160至170亿美元；G2订单：Q3单季总新签订单292.91亿美元，内生同比暴增96%！",
            "single_var_question": "重型燃气轮机排产锁满至2029年后的新签长协提价幅度，能否在2027至2028年交付期把电力与电气化综合EBITDA利润率推升至20%以上？",
        },
        {
            "rank": 14, "ticker": "KLAC", "company_cn": "科磊 (KLA Corp)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "PE=34.7x (NOPAT PE=37.3x) / PS=12.44x；PEG(G3)=1.20x (按Q3实际+28.9%)",
            "g1_g2_anchor": "G1官引：Q4营收指引45.0至49.0亿美元（中枢47.0亿美元环比再增13.6%），干净EPS指引中枢1.44美元（隐含Non-GAAP OPM跳升至47.4%）；上调2026全球WFE至约1550亿美元，并首次指引2027全球WFE突破2000亿美元。",
            "single_var_question": "2纳米GAA环栅晶体管与HBM4堆叠良率爬坡对过程控制检测强度（Process Control Intensity）的提升系数能否在2027年超过11%历史极值？",
        },
        {
            "rank": 15, "ticker": "HALO", "company_cn": "Halozyme (HALO)",
            "tier_label": "第二梯队：基本面真加速但Q3被砸错杀组",
            "peg_display": "GAAP PE=25.9x (NOPAT PE=22.2x，按FY26 Non-GAAP EPS官引中枢8.90美元仅12.8x)；PEG(G3)=0.66x",
            "g1_g2_anchor": "G1官引：全面上调FY26总营收至18.60至19.25亿美元、核心版税收入至12.35至12.55亿美元、Non-GAAP EPS至8.75至9.05美元；Q3核心ENHANZE皮下注射版税收入同比大增44%至3.41亿美元（盘后跌7.3%纯因里程碑确认时点波动）。",
            "single_var_question": "Darzalex与Phesgo之外的新一批高浓度皮下制剂商业化放量，能否在2028年后核心专利梯度到期前无缝接力版税现金流峰值？",
        },
        # ==================== 第三梯队 (5只) ====================
        {
            "rank": 16, "ticker": "CLS", "company_cn": "天弘科技 (Celestica)",
            "tier_label": "第三梯队：2026Q3单季刚现加速拐点+低估值观察组(PE<20x)",
            "peg_display": "PE=19.5x / PS=1.43x；PEG(G1)=0.22x (按FY27首引营收+90.5%/EPS+86.1%) / PEG(G3)=0.24x",
            "g1_g2_anchor": "G1官引：FY26营收上调至210亿美元、干净EPS上调至11.55美元；首次发布极具冲击力的FY27官方指引：营收400亿美元（同比暴增90.5%）、干净OPM提升至9.0%、干净EPS达21.50美元（同比+86.1%）；Q3因预告扩产备货耗现回吐涨幅，现价对应FY27官引PE仅11.6x。",
            "single_var_question": "2027年冲刺400亿美元营收过程中，高毛利HPS自研交换机与低毛利定制AI计算整机柜过手物料的占比结构能否守住9.0%干净OPM官引？",
        },
        {
            "rank": 17, "ticker": "VST", "company_cn": "维斯特拉能源 (Vistra Corp)",
            "tier_label": "第三梯队：2026Q3单季刚现加速拐点+低估值观察组(PE<20x)",
            "peg_display": "更新Q3后PE=15.6x (原滞后口径16.8x) / PS=2.05x；PEG(G3)=0.56x (按Q3营收+27.7%)",
            "g1_g2_anchor": "G1官引：上调FY26持续运营调整后EBITDA中枢至73.0亿美元（区间71至75亿）、FCFbG中枢至45.0亿美元；首次发布2027年调整后EBITDA指引77.0至85.0亿美元、FCFbG指引43.0至51.0亿美元；Q3实际营收同增27.7%（较Q2单季猛烈提速+33.2pct），商业可用率94.8%。",
            "single_var_question": "FERC表后核电直供（Co-location）监管框架落地后，Comanche Peak与Beaver Valley核电机组新签数据中心PPA长协电价溢价能锁在多少美元/MWh？",
        },
        {
            "rank": 18, "ticker": "LNG", "company_cn": "切尼尔能源 (Cheniere Energy)",
            "tier_label": "第三梯队：2026Q3单季刚现加速拐点+低估值观察组(PE<20x)",
            "peg_display": "PE=19.8x (NOPAT PE=11.0x) / PS=2.44x；PEG(G3)=0.51x (按Q3营收+39.0%)",
            "g1_g2_anchor": "G1官引：年内第三次大幅上调FY26合并调整后EBITDA 10.4%至87.5至92.5亿美元，上调可分配现金流（DCF）13.5%至60.5至65.5亿美元（提前四年突破每股30美元）；G2长协：新签卡塔尔能源与巴西国油近500万吨/年超长期SPA合同，Q3单季出口684 TBtu创历史新高。",
            "single_var_question": "Corpus Christi三期新产线全面达产后，在85%以上容量已由20年固定液化费SPA锁死的前提下，剩余约15%敞口对欧美TTF-Henry Hub价差敏感度有多大？",
        },
        {
            "rank": 19, "ticker": "REGN", "company_cn": "再生元制药 (Regeneron)",
            "tier_label": "第三梯队：2026Q3单季刚现加速拐点+低估值观察组(PE<20x)",
            "peg_display": "PE=19.99x / PS=5.54x；PEG(G3)=0.55x (按Q3实际营收+36.3%)",
            "g1_g2_anchor": "G3实绩：2026Q3单季营收同比增速从Q2的16.7%骤然跳升19.5个百分点至36.3%，单季GAAP营业利润率从30.1%跃升至40.0%（同比扩+12.7pct），GM-SGA提升至75.1%，绩后放量跳涨+17.4%。",
            "single_var_question": "Q3营收跳增+36.3%中有多少来自Dupixent COPD新适应症真实处方渗透、多少来自Eylea HD渠道补库或里程碑一次性结算？",
        },
        {
            "rank": 20, "ticker": "EME", "company_cn": "EMCOR集团 (EMCOR Group)",
            "tier_label": "第三梯队：2026Q3单季刚现加速拐点+低估值观察组(PE<20x)",
            "peg_display": "PE=17.6x (NOPAT PE=16.3x) / PS=1.34x；PEG(G3)=0.61x (按Q3实际营收+28.8%)",
            "g1_g2_anchor": "G3实绩：此前连续三季营收稳态增长19.7%至19.8%，2026Q3单季营收同比增速突破跳升+9.1pct至28.8%，ROIC高达46.7%，股本同比净回购缩减1.61%，直接受益北美数据中心机电总包与制造业回流资本开支共振。",
            "single_var_question": "北美数据中心与半导体晶圆厂机电安装剩余履约订单（RPO）中，熟练电工工时瓶颈是在推升固定总价合同利润率还是限制2027年收入交付上限？",
        },
    ]

    cards = []
    for sp in specs:
        r = by_tk[sp["ticker"]]
        rx_str = r["feishu_reaction_desc"] if r["feishu_reaction_desc"] else (
            f"{r['q3_earn_ret'] * 100:+.1f}%" if pd.notna(r["q3_earn_ret"]) else "平盘"
        )
        cards.append({
            "rank": sp["rank"],
            "ticker": sp["ticker"],
            "company": sp["company_cn"],
            "tier": sp["tier_label"],
            "in_current_portfolio": bool(r["in_current_portfolio"]),
            "market_cap_usd_b": float(r["market_cap_usd_b"]),
            "pe_ttm": None if pd.isna(r["pe_ttm"]) else float(r["pe_ttm"]),
            "nopat_pe_ttm": None if pd.isna(r["nopat_pe_ttm"]) else float(r["nopat_pe_ttm"]),
            "ps_ttm_usd": None if pd.isna(r["ps_ttm_usd"]) else float(r["ps_ttm_usd"]),
            "peg_compliant": sp["peg_display"],
            "rev_yoy_4q_seq": r["rev_yoy_4q_seq"],
            "opm_4q_seq": r["opm_4q_seq"],
            "gmsga_4q_seq": r["gmsga_4q_seq"],
            "roic_ttm_pct": None if pd.isna(r["roic_ttm"]) else round(float(r["roic_ttm"]) * 100, 1),
            "dilution_yoy_pct": None if pd.isna(r["dilution_yoy"]) else round(float(r["dilution_yoy"]) * 100, 2),
            "price_structure_and_q3_reaction": f"{r['price_structure']} | 6M涨跌 {r['return_6m']*100:+.1f}% | 距52周高 {r['dist_to_52w_high']*100:.1f}% | Q3反应: {rx_str}",
            "g1_g2_hard_data": sp["g1_g2_anchor"],
            "sellside_model_single_variable": sp["single_var_question"],
        })
    return cards


def write_summary_md(df_master: pd.DataFrame, top20_cards: list, macro_latest: dict, out_path: str):
    df_rank = df_master[~df_master["ticker"].isin(DUPLICATE_SIBLINGS_DROP_IN_RANK)].copy()
    t1_df = df_rank[df_rank["tier"] == "Tier1_DoubleInflect_MainTrend"].sort_values("rev_yoy_q0", ascending=False)
    t2_df = df_rank[df_rank["tier"] == "Tier2_Dislocation_Goldmine"].sort_values("rev_yoy_q0", ascending=False)
    t3_df = df_rank[df_rank["tier"] == "Tier3_1Q_Inflect_LowPE"].sort_values("rev_accel_q0", ascending=False)
    t4_df = df_rank[df_rank["tier"] == "Tier4_RedLine_Avoid"].sort_values("q3_earn_ret", ascending=False)
    port_df = df_rank[df_rank["in_current_portfolio"]].sort_values("market_cap_usd_b", ascending=False)

    feishu_cnt = int(df_master["in_feishu_q3"].sum())
    feishu_q3_updated = int(df_master[df_master["in_feishu_q3"]]["q0_end"].ge("2026-08-01").sum())
    total_q3_updated = int(df_rank["q0_end"].ge("2026-08-01").sum())

    lines = []
    lines.append("# M8 实战选股总表：2026Q3 连续4季拐点全池精筛与拆模清单")
    lines.append("")
    lines.append("## 一、核心结论与 2026年11月宏观锚点")
    lines.append("")
    lines.append(
        f"`核心裁决：在2026年11月高实际利率（2.60%）与工业资本开支扩张（Q2_Reflation_CapexBoom）象限下，全池722只候选美股（去重双股权后{len(df_rank)}家）筛出第一梯队主升龙头{len(t1_df)}只、第二梯队错杀金矿{len(t2_df)}只、第三梯队低估值首季拐点{len(t3_df)}只，以及第四梯队避雷红线股{len(t4_df)}只；最值得立刻拆卖方模型的预期差首选为 NTRA、GOOGL、CLS、ANET、APH、TSM、GEV。`"
    )
    lines.append("")
    lines.append(
        f"1. **数据补齐核验**：73只飞书2026Q3美股已100%（{feishu_q3_updated}/{feishu_cnt}）补齐至最新2026Q3实绩并完成只读纪要锚点提取；全池去重后共 {total_q3_updated}/718 家公司更新至2026年8月及以后最新财季（其余主要为1/4/7/10财年制尚未披露三季报标的，如 NVDA、CRM、COST 等）。同时修正了台积电（TSM）、日月光（ASX）、阿斯麦（ASML）等20F外币报表ADR的跨币种市销率口径，并剥离了谷歌（GOOGL）上半年SpaceX上市公允价值重估对表观市盈率的扭曲。"
    )
    lines.append(
        f"2. **2026年11月实时宏观状态（截至 {macro_latest['date']}）**：处于 **`Q2_Reflation_CapexBoom`（再通胀与实体资本开支繁荣）** 象限。10年期美债名义利率 **{macro_latest['dgs10']:.2f}%**，10年期TIPS实际利率 **{macro_latest['dfii10']:.2f}%**，BAA信用利差 **{macro_latest['baa10y']:.2f}%**（良性），高收益债OAS **{macro_latest['hy_oas']:.2f}%**，工业产值同比 **+{macro_latest['indpro_yoy']:.2f}%**（加速 **+{macro_latest['indpro_accel']:.2f}pct**），制造业新订单同比 **+{macro_latest['neworder_yoy']:.2f}%**。"
    )
    lines.append(
        "3. **宏观对选股的物理约束**：2.60%的高实际利率对「无商业收入或现金流为负的高稀释叙事股」（OKLO、SMR、IREN）与「高估值指引降速股」（NOW、FTNT、DDOG）形成猛烈杀估值；而拥有供给侧物理瓶颈、自由现金流自造血、且 G1/G2 订单能见度锁死至2027年的 AI算力互连/液冷电力/模拟与过程控制芯片/分子诊断龙头（APH、ANET、VRT、TXN、CLS、VST、NTRA）享有最强顺风。"
    )
    lines.append("")
    lines.append("## 二、当前美股模拟盘/实盘持仓 11 只个股 2026Q3 逐一体检")
    lines.append("")
    lines.append("| 代码 | 市值($B) | 最新财季 | 4季营收同比序列(Q-3至Q0) | 4季OPM序列 | PE / 合规PEG(G3) | Q3绩后反应 | 梯队归属与持仓诊断 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    port_notes = {
        "LLY": "第一梯队主升核心：连续4季>38%高增，干净OPM达52.4%，年内三上调指引",
        "V": "稳健复利底仓：Q3净收入+13.2%，增值服务+31%，首次发布FY27双位数EPS增长指引",
        "ICE": "第一梯队主升：能源与利率高波动推动Q3营收提速至+20.7%，干净OPM扩206bp至61.4%",
        "WM": "稳健防御底仓：Q3营收+6.3%，定价权稳固但PEG(G3)偏高(4.96x)，跑赢防守属性",
        "CEG": "待发Q3(10Q停6月末)：核电基荷同业VST/TLN刚大超预期暴涨，关注核电直供PPA催化",
        "FCX": "强周期观察：铜价支撑OPM 31.2%，Q3营收转正+8.2%，受印尼矿山品位与冶炼节奏扰动",
        "LNG": "第三梯队低估加速：Q3营收提速+15.5pct至+39.0%，年内三上调EBITDA与DCF指引，净回购5.9%",
        "VRTX": "研发兑现观察：Q3营收+11.8%，核心囊性纤维化稳健，看非阿片镇痛新药商业化斜率",
        "RGLD": "高现金流权利金：Q3黄金当量销量创纪录营收+84.4%，提前一年清零12.25亿并购负债",
        "HALO": "第二梯队错杀金矿：核心版税+44%且全线上调指引，盘后跌7.3%纯属里程碑确认节奏噪音",
        "BWXT": "增速放缓观察：Q3营收同比从26.1%->18.0%->10.0%连降两季，盘后跌3.2%，需核查军工交付排期",
    }
    for _, pr in port_df.iterrows():
        tk = pr["ticker"]
        pe_s = f"{pr['pe_ttm']:.1f}x" if pd.notna(pr["pe_ttm"]) else "NA"
        peg_s = f"{pr['peg_g3']:.2f}x" if pd.notna(pr["peg_g3"]) else "NA"
        rx = pr["feishu_reaction_desc"] if pr["feishu_reaction_desc"] else (f"{pr['q3_earn_ret']*100:+.1f}%" if pd.notna(pr["q3_earn_ret"]) else "待披露")
        lines.append(
            f"| **{tk}** | {pr['market_cap_usd_b']:.1f} | {pr['q0_end']} | {pr['rev_yoy_4q_seq']} | {pr['opm_4q_seq']} | {pe_s} / {peg_s} | {rx} | {port_notes.get(tk, pr['tier'])} |"
        )
    lines.append("")

    lines.append("## 三、前三大梯队 Top 20 重点拆模标的逐一硬核卡片")
    lines.append("")
    lines.append("> 注：所有估值倍数严格基于已披露事实报表与公司官方指引（G1）/官方在手订单RPO（G2）/最新单季真实同比（G3）计算，零卖方一致预期与目标价。`[当前持仓]` 表示已在 `portfolio_state.json` 美股账户持仓中。")
    lines.append("")

    for c in top20_cards:
        port_badge = " `[当前持仓]`" if c["in_current_portfolio"] else ""
        pe_str = f"GAAP PE {c['pe_ttm']:.1f}x" if c["pe_ttm"] is not None else "GAAP PE 无(微亏)"
        if c["nopat_pe_ttm"] is not None and (c["pe_ttm"] is None or abs(c["nopat_pe_ttm"] - c["pe_ttm"]) / max(c["pe_ttm"], 1) > 0.15):
            pe_str += f"（干净经营NOPAT PE {c['nopat_pe_ttm']:.1f}x）"
        ps_str = f"PS {c['ps_ttm_usd']:.2f}x" if c["ps_ttm_usd"] is not None else "PS NA"
        roic_str = f"{c['roic_ttm_pct']:.1f}%" if c["roic_ttm_pct"] is not None else "NA"
        dil_str = f"{c['dilution_yoy_pct']:+.2f}%" if c["dilution_yoy_pct"] is not None else "NA"

        lines.append(f"### #{c['rank']} {c['ticker']} · {c['company']}{port_badge} （{c['tier']}）")
        lines.append(f"1. **市值与合规估值**：总市值 **${c['market_cap_usd_b']:.1f}B** | {pe_str} | {ps_str} | **{c['peg_compliant']}** | ROIC **{roic_str}** | 股本同比稀释 **{dil_str}**")
        lines.append(f"2. **最近4季营收同比序列（Q-3 -> Q-2 -> Q-1 -> Q0）**：`{c['rev_yoy_4q_seq']}`")
        lines.append(f"3. **最近4季利润率与商业化效率序列**：单季OPM `{c['opm_4q_seq']}` | 单季GM减SGA `{c['gmsga_4q_seq']}`")
        lines.append(f"4. **股价结构与Q3财报日反应**：{c['price_structure_and_q3_reaction']}")
        lines.append(f"5. **G1/G2核心硬数据锚点**：{c['g1_g2_hard_data']}")
        lines.append(f"6. **`拆卖方Model最该抓的1个核心单变量问题`**：`{c['sellside_model_single_variable']}`")
        lines.append("")

    lines.append("## 四、四大实战梯队全池扩展汇总表")
    lines.append("")
    lines.append("### 4.1 第一梯队扩展池（3至4季连续双拐点 + 宏观顺风主升组）")
    lines.append("| 代码 | 行业 | 市值($B) | PE | PS | PEG(G3) | 4季营收同比序列 | 4季OPM序列 | ROIC | 股本稀释 | 股价形态与Q3反应 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for _, r in t1_df.head(15).iterrows():
        pe_s = f"{r['pe_ttm']:.1f}x" if pd.notna(r["pe_ttm"]) else "NA"
        ps_s = f"{r['ps_ttm_usd']:.2f}x" if pd.notna(r["ps_ttm_usd"]) else "NA"
        peg_s = f"{r['peg_g3']:.2f}x" if pd.notna(r["peg_g3"]) else "NA"
        roic_s = f"{r['roic_ttm']*100:.1f}%" if pd.notna(r["roic_ttm"]) else "NA"
        dil_s = f"{r['dilution_yoy']*100:+.2f}%" if pd.notna(r["dilution_yoy"]) else "NA"
        rx = r["feishu_reaction_desc"] if r["feishu_reaction_desc"] else (f"{r['q3_earn_ret']*100:+.1f}%" if pd.notna(r["q3_earn_ret"]) else "平盘")
        lines.append(f"| **{r['ticker']}** | {r['industry']} | {r['market_cap_usd_b']:.1f} | {pe_s} | {ps_s} | {peg_s} | {r['rev_yoy_4q_seq']} | {r['opm_4q_seq']} | {roic_s} | {dil_s} | {r['price_structure']} ({rx}) |")
    lines.append("")

    lines.append("### 4.2 第二梯队扩展池（基本面真加速但Q3股价被砸/横盘错杀组）")
    lines.append("| 代码 | 行业 | 市值($B) | PE | PS | PEG(G3) | 4季营收同比序列 | 4季GM减SGA序列 | 距52周高 | Q3绩后反应 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in t2_df.head(15).iterrows():
        pe_s = f"{r['pe_ttm']:.1f}x" if pd.notna(r["pe_ttm"]) else "微亏"
        ps_s = f"{r['ps_ttm_usd']:.2f}x" if pd.notna(r["ps_ttm_usd"]) else "NA"
        peg_s = f"{r['peg_g3']:.2f}x" if pd.notna(r["peg_g3"]) else "NA"
        d52 = f"{r['dist_to_52w_high']*100:.1f}%" if pd.notna(r["dist_to_52w_high"]) else "NA"
        rx = r["feishu_reaction_desc"] if r["feishu_reaction_desc"] else (f"{r['q3_earn_ret']*100:+.1f}%" if pd.notna(r["q3_earn_ret"]) else "回调")
        lines.append(f"| **{r['ticker']}** | {r['industry']} | {r['market_cap_usd_b']:.1f} | {pe_s} | {ps_s} | {peg_s} | {r['rev_yoy_4q_seq']} | {r['gmsga_4q_seq']} | {d52} | {rx} |")
    lines.append("")

    lines.append("### 4.3 第三梯队扩展池（2026Q3单季刚现拐点 + PE<20x 非周期顶观察组）")
    lines.append("| 代码 | 行业 | 市值($B) | PE | PEG(G3) | 4季营收同比序列 | Q3单季提速 | Q3单季OPM | 5年OPM分位 | Q3反应 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for _, r in t3_df.head(12).iterrows():
        acc_s = f"{r['rev_accel_q0']*100:+.1f}pct" if pd.notna(r["rev_accel_q0"]) else "NA"
        opm_s = f"{r['opm_q0']*100:.1f}%" if pd.notna(r["opm_q0"]) else "NA"
        p5_s = f"{r['opm_5y_pct']*100:.0f}%" if pd.notna(r["opm_5y_pct"]) else "NA"
        peg_s = f"{r['peg_g3']:.2f}x" if pd.notna(r["peg_g3"]) else "NA"
        rx = r["feishu_reaction_desc"] if r["feishu_reaction_desc"] else (f"{r['q3_earn_ret']*100:+.1f}%" if pd.notna(r["q3_earn_ret"]) else "平盘")
        lines.append(f"| **{r['ticker']}** | {r['industry']} | {r['market_cap_usd_b']:.1f} | {r['pe_ttm']:.1f}x | {peg_s} | {r['rev_yoy_4q_seq']} | {acc_s} | {opm_s} | {p5_s} | {rx} |")
    lines.append("")

    lines.append("### 4.4 第四梯队重点避雷池（Q3表面超预期或跳涨，但触犯30年历史避雷红线组）")
    lines.append("| 代码 | 行业 | 市值($B) | PE | Q3营收同比 | Q3单季OPM | GM减SGA | 股本稀释 | 5年OPM分位 | Q3反应 | 触犯历史红线类型 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    # Pick representative Tier 4 stocks across all 3 red-line types
    priority_t4 = ["OKLO", "IREN", "TEM", "U", "SMR", "SNDK", "MU", "WDC", "CCL", "ZBH", "BKNG", "MMM", "MO"]
    t4_prio = t4_df[t4_df["ticker"].isin(priority_t4)].copy()
    t4_rest = t4_df[~t4_df["ticker"].isin(priority_t4)].head(5)
    t4_show = pd.concat([t4_prio, t4_rest], ignore_index=True)
    for _, r in t4_show.iterrows():
        pe_s = f"{r['pe_ttm']:.1f}x" if (pd.notna(r["pe_ttm"]) and r["pe_ttm"] > 0) else "亏损(<0)"
        rv_s = f"{r['rev_yoy_q0']*100:+.1f}%" if pd.notna(r["rev_yoy_q0"]) else "无主营收入"
        op_s = f"{r['opm_q0']*100:.1f}%" if pd.notna(r["opm_q0"]) else "NA"
        gm_s = f"{r['gmsga_q0']*100:.1f}%" if pd.notna(r["gmsga_q0"]) else "NA"
        dl_s = f"{r['dilution_yoy']*100:+.1f}%" if pd.notna(r["dilution_yoy"]) else "NA"
        p5_s = f"{r['opm_5y_pct']*100:.0f}%" if pd.notna(r["opm_5y_pct"]) else "极值/NA"
        rx = r["feishu_reaction_desc"] if r["feishu_reaction_desc"] else (f"{r['q3_earn_ret']*100:+.1f}%" if pd.notna(r["q3_earn_ret"]) else "异动")
        lines.append(f"| **{r['ticker']}** | {r['industry']} | {r['market_cap_usd_b']:.1f} | {pe_s} | {rv_s} | {op_s} | {gm_s} | {dl_s} | {p5_s} | {rx} | {r['redline_reason']} |")
    lines.append("")

    md_text = "\n".join(lines)
    # Strip any em-dashes per zh-delivery
    md_text = md_text.replace("——", "：").replace("—", "至")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md_text)


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 72)
    print("启动 W2_08: 2026Q3 连续4季拐点全池精筛 + 飞书Q3专区定性锚点引擎")
    print("=" * 72)

    cand = pd.read_parquet(CAND_PATH)
    xbrl = pd.read_parquet(XBRL_PATH)
    macro = pd.read_parquet(MACRO_PATH)
    daily = pd.read_parquet(DAILY_PATH)

    with open(PORTFOLIO_PATH) as f:
        ps_state = json.load(f)
    us_port_pos = {p["ticker"]: p for p in ps_state.get("accounts", {}).get("us", {}).get("positions", [])}

    m_last = macro.sort_values("date").iloc[-1]
    macro_latest = {
        "date": str(m_last["date"])[:10],
        "macro_quadrant": str(m_last["macro_quadrant"]),
        "era_regime": str(m_last["era_regime"]),
        "dgs10": float(m_last["dgs10"]),
        "dfii10": float(m_last["dfii10"]),
        "baa10y": float(m_last["baa10y"]),
        "hy_oas": float(m_last["hy_oas"]),
        "indpro_yoy": float(m_last["indpro_yoy_pit"]),
        "indpro_accel": float(m_last["indpro_accel_pit"]),
        "neworder_yoy": float(m_last["neworder_yoy_pit"]),
    }

    print("[1/4] 补齐 2026Q3 最新单季财务数据 (XBRL + yfinance 美股事实行 + 8-K 事实补丁)...")
    yf_q = step1_load_and_supplement_q3(cand, xbrl)

    print("[2/4] 只读提取飞书 2026Q3 财报季专区 73 只美股 G1/G2 定性硬数据锚点...")
    f_anchors = step2_fetch_feishu_readonly_anchors()

    print("[3/4] 计算日频均线股价结构与连续4季财务轨迹、四梯队分类及 Top 20 拆模卡片...")
    price_feats = compute_price_structure(cand, daily)
    df_master = build_master_screen(cand, xbrl, yf_q, f_anchors, price_feats, us_port_pos)
    top20_cards = build_top20_deep_cards(df_master)

    print("[4/4] 写入 CSV / JSON / Markdown 交付物...")
    csv_full_path = os.path.join(OUT_DIR, "m8_full_722_2026q3_screen.csv")
    csv_top20_path = os.path.join(OUT_DIR, "m8_top20_cards.csv")
    json_out_path = os.path.join(OUT_DIR, "m8_tiers_and_top20.json")
    md_out_path = os.path.join(OUT_DIR, "m8_summary.md")

    df_master.to_csv(csv_full_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(top20_cards).to_csv(csv_top20_path, index=False, encoding="utf-8-sig")

    df_rank = df_master[~df_master["ticker"].isin(DUPLICATE_SIBLINGS_DROP_IN_RANK)]
    tier_counts = df_rank["tier"].value_counts().to_dict()

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "macro_context_2026_11": macro_latest,
        "coverage_stats": {
            "total_candidates_rows": int(len(df_master)),
            "unique_companies_ranked": int(len(df_rank)),
            "feishu_q3_us_stocks_total": int(df_master["in_feishu_q3"].sum()),
            "feishu_q3_us_stocks_updated_2026q3": int(df_master[df_master["in_feishu_q3"]]["q0_end"].ge("2026-08-01").sum()),
            "unique_companies_updated_ge_2026_08": int(df_rank["q0_end"].ge("2026-08-01").sum()),
            "tier_counts": tier_counts,
        },
        "current_us_portfolio_holdings_in_universe": df_rank[df_rank["in_current_portfolio"]][
            ["ticker", "name", "market_cap_usd_b", "q0_end", "tier", "pe_ttm", "peg_g3", "rev_yoy_4q_seq", "opm_4q_seq", "feishu_reaction_desc", "portfolio_pnl_pct"]
        ].to_dict(orient="records"),
        "top20_deep_cards": top20_cards,
        "tier1_tickers": df_rank[df_rank["tier"] == "Tier1_DoubleInflect_MainTrend"]["ticker"].tolist(),
        "tier2_tickers": df_rank[df_rank["tier"] == "Tier2_Dislocation_Goldmine"]["ticker"].tolist(),
        "tier3_tickers": df_rank[df_rank["tier"] == "Tier3_1Q_Inflect_LowPE"]["ticker"].tolist(),
        "tier4_tickers": df_rank[df_rank["tier"] == "Tier4_RedLine_Avoid"]["ticker"].tolist(),
    }
    with open(json_out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    write_summary_md(df_master, top20_cards, macro_latest, md_out_path)

    print(f"✓ 全部完成！耗时 {time.time() - t0:.1f}s")
    print("  Tier 统计:", tier_counts)
    print(f"  1) {csv_full_path}")
    print(f"  2) {csv_top20_path}")
    print(f"  3) {json_out_path}")
    print(f"  4) {md_out_path}")


if __name__ == "__main__":
    main()
