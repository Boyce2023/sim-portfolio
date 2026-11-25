#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Module 1 (RD026): policy_polymarket_ingest_v2.py
Incremental PIT Policy Corpus & Market Panel Upgrader (D12 compliant, Tencent akshare + local DB only).

Features:
1. Reads read-only SSOT:
   - output/csrc_policy_100factors_20261114/backtest/master_events_pit.parquet
   - output/csrc_policy_100factors_20261114/backtest/daily_market_panel.parquet
   - output/csrc_policy_100factors_20261114/national_team/v3_cache/*
   - sim-portfolio/data/cn_hk_price_db/a_daily.parquet
   - sim-portfolio/backtest/2026-08-24-daban/notices.db
2. Strips same-day (lead=0) policy leaks from non-HARD_ACTION_NOW rows (M0525, M0628).
3. Ingests verified live events from 2026-11-15 to 2026-11-25 (and optional --add-event-json).
4. Extends daily_market_panel cleanly to 2026-11-24 using Tencent index API (akshare),
   local survivorship-free a_daily.parquet, V3 national team ETF pool, and notices.db.
5. Saves outputs to output/csrc_policy_100factors_20261114/policy_polymarket_v1/:
   - master_events_v2_20261125.parquet
   - daily_market_panel_v2_20261124.parquet
   - ingest_v2_audit.json

CLI:
  python3 policy_polymarket_ingest_v2.py
  python3 policy_polymarket_ingest_v2.py --add-event-json path/to/new_events.json
  python3 policy_polymarket_ingest_v2.py --status
"""
import argparse
import json
import os
import sqlite3
import sys
import warnings
warnings.filterwarnings("ignore")
os.environ["NO_PROXY"] = "*"

import akshare as ak
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import csrc_v3_backtest_calibrate as v3_cal

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_OUT = os.path.join(ROOT, "output/csrc_policy_100factors_20261114")
POLY_DIR = os.path.join(BASE_OUT, "policy_polymarket_v1")
os.makedirs(POLY_DIR, exist_ok=True)

ORIG_EV_PQ = os.path.join(BASE_OUT, "backtest/master_events_pit.parquet")
ORIG_MP_PQ = os.path.join(BASE_OUT, "backtest/daily_market_panel.parquet")
A_DAILY_PQ = os.path.join(ROOT, "sim-portfolio/data/cn_hk_price_db/a_daily.parquet")
NOTICES_DB = os.path.join(ROOT, "sim-portfolio/backtest/2026-08-24-daban/notices.db")

V2_EV_PQ = os.path.join(POLY_DIR, "master_events_v2_20261125.parquet")
V2_MP_PQ = os.path.join(POLY_DIR, "daily_market_panel_v2_20261124.parquet")
AUDIT_JSON = os.path.join(POLY_DIR, "ingest_v2_audit.json")

INDEX_MAP = {
    "sh000001": "sh_comp",
    "sh000300": "csi300",
    "sz399006": "chinext",
    "sh000688": "star50",
    "sh000905": "csi500",
    "sh000852": "csi1000",
    "sh000016": "sse50",
    "sh000922": "csi_div",
    "sz399975": "brokerage",
    "sz399986": "bank_idx",
    "sh000941": "new_energy",
    "sz399997": "baijiu",
    "sh000933": "pharma",
    "sz399974": "soe_reform",
    "sh000926": "central_soe",
    "sz399967": "defense",
    "sz399971": "media_ai",
    "sh000993": "tmt_info",
    "sh000989": "cons_opt",
    "sz399393": "real_estate",
    "sh512480": "semi_etf",
}

LIVE_VERIFIED_EVENTS = [
    {
        "master_id": "V2_20261115_IAC",
        "shard_src": "live_v2_20261125",
        "event_date": "2026-11-15",
        "release_slot": "WEEKEND_HOLIDAY",
        "authority_level": "CSRC_CHAIR",
        "is_joint_ministry": 0,
        "venue_type": "SYMPOSIUM",
        "action_verb_stage": "RESEARCH_EVALUATE",
        "speaker_or_body": "中国证监会主席吴清及国际顾问委员会",
        "title_or_occasion": "证监会国际顾问委员会第23次会议（上海，主题面向2030的中国资本市场：构建包容环境、增强市场韧性、完善全球治理）",
        "quotes_joined": "面向2030的中国资本市场：构建包容环境、增强市场韧性、完善全球治理；深化高水平制度型开放与中长期资金入市。",
        "named_sectors_joined": "硬科技,中长期资金蓝筹,沪深港通标的",
        "hard_levers_joined": "",
        "market_rescue_signal": 1,
        "liquidity_long_term_capital": 1,
        "ipo_supply_tightening": 0,
        "share_reduction_crackdown": 0,
        "quant_short_selling_tightening": 0,
        "speculation_fraud_crackdown": 0,
        "tech_innovation_support": 1,
        "ma_restructuring_support": 0,
        "dividend_buyback_push": 0,
        "brokerage_investment_bank": 1,
        "source": "live_v2_ingest",
        "resolves_master_ids": [],
    },
    {
        "master_id": "V2_20261118_MOF",
        "shard_src": "live_v2_20261125",
        "event_date": "2026-11-18",
        "release_slot": "AMC",
        "authority_level": "FISCAL_SASAC",
        "is_joint_ministry": 0,
        "venue_type": "OFFICIAL_QA_RULE",
        "action_verb_stage": "HARD_ACTION_NOW",
        "speaker_or_body": "财政部",
        "title_or_occasion": "财政部开展11月国债做市支持操作并推进1500亿元中央金融机构注资特别国债发行",
        "quotes_joined": "财政部完成11月国债做市支持操作，并推进1500亿元中央金融机构注资特别国债发行落地，夯实大型国有金融机构资本补充。",
        "named_sectors_joined": "国有大型银行,非银金融,大金融权重",
        "hard_levers_joined": "FISCAL_CAPITAL_INJECT",
        "market_rescue_signal": 1,
        "liquidity_long_term_capital": 1,
        "ipo_supply_tightening": 0,
        "share_reduction_crackdown": 0,
        "quant_short_selling_tightening": 0,
        "speculation_fraud_crackdown": 0,
        "tech_innovation_support": 0,
        "ma_restructuring_support": 0,
        "dividend_buyback_push": 0,
        "brokerage_investment_bank": 0,
        "source": "live_v2_ingest",
        "resolves_master_ids": [],
    },
    {
        "master_id": "V2_20261122_MARGIN",
        "shard_src": "live_v2_20261125",
        "event_date": "2026-11-22",
        "release_slot": "WEEKEND_HOLIDAY",
        "authority_level": "JOINT_MINISTRY_SCIO",
        "is_joint_ministry": 1,
        "venue_type": "OFFICIAL_QA_RULE",
        "action_verb_stage": "HARD_ACTION_NOW",
        "speaker_or_body": "中国证监会统筹/沪深北交易所",
        "title_or_occasion": "证监会统筹沪深北交易所将投资者融资买入最低保证金比例由100%调低至80%（2026年11月30日起施行，新老合约适用，附异常交易差异化从严管控）",
        "quotes_joined": "经中国证监会批准，沪深北交易所将投资者融资买入证券最低保证金比例由100%调整为80%，2026年11月30日起施行，新老合约适用；同步对异常交易及高杠杆炒作实施差异化从严管控。",
        "named_sectors_joined": "头部券商,两融标的,宽基权重",
        "hard_levers_joined": "MARGIN_BROKERAGE",
        "market_rescue_signal": 2,
        "liquidity_long_term_capital": 1,
        "ipo_supply_tightening": 0,
        "share_reduction_crackdown": 0,
        "quant_short_selling_tightening": 0,
        "speculation_fraud_crackdown": 1,
        "tech_innovation_support": 0,
        "ma_restructuring_support": 0,
        "dividend_buyback_push": 0,
        "brokerage_investment_bank": 2,
        "source": "live_v2_ingest",
        # Explicitly resolves 2026-11-06 State Council Exec meeting (M0652) on 16d lead!
        "resolves_master_ids": ["M0652"],
    },
    {
        "master_id": "V2_20261122_FEE",
        "shard_src": "live_v2_20261125",
        "event_date": "2026-11-22",
        "release_slot": "WEEKEND_HOLIDAY",
        "authority_level": "CSRC_OFFICIAL",
        "is_joint_ministry": 1,
        "venue_type": "OFFICIAL_QA_RULE",
        "action_verb_stage": "HARD_ACTION_NOW",
        "speaker_or_body": "沪深交易所与中国结算",
        "title_or_occasion": "沪深交易所与中国结算发布新一轮降费让利通知（免收2026年交易单元使用费，上市费与债券经手费减免延至2028年底，两市新增让利约27.6亿元）",
        "quotes_joined": "免收2026年交易单元使用费，上市费与债券经手费减免措施延续至2028年底，两市合计新增降费让利约27.6亿元，切实降低市场交易成本。",
        "named_sectors_joined": "头部券商,交易所核心资产,债券市场",
        "hard_levers_joined": "MARGIN_BROKERAGE",
        "market_rescue_signal": 1,
        "liquidity_long_term_capital": 0,
        "ipo_supply_tightening": 0,
        "share_reduction_crackdown": 0,
        "quant_short_selling_tightening": 0,
        "speculation_fraud_crackdown": 0,
        "tech_innovation_support": 0,
        "ma_restructuring_support": 0,
        "dividend_buyback_push": 0,
        "brokerage_investment_bank": 2,
        "source": "live_v2_ingest",
        "resolves_master_ids": ["M0652"],
    },
    {
        "master_id": "V2_20261122_CHINEXT_MM",
        "shard_src": "live_v2_20261125",
        "event_date": "2026-11-22",
        "release_slot": "WEEKEND_HOLIDAY",
        "authority_level": "EXCHANGE_SURVEILLANCE",
        "is_joint_ministry": 0,
        "venue_type": "EXCHANGE_NOTICE",
        "action_verb_stage": "DRAFT_CONSULT",
        "speaker_or_body": "深圳证券交易所",
        "title_or_occasion": "深交所就《深圳证券交易所创业板股票做市交易业务细则（征求意见稿）》公开征求意见",
        "quotes_joined": "深交所起草《深圳证券交易所创业板股票做市交易业务细则（征求意见稿）》并向社会公开征求意见，完善创业板做市商制度、提升流动性与定价效率。",
        "named_sectors_joined": "创业板,头部券商做市商,硬科技成长",
        "hard_levers_joined": "TECH_BOARD_REFORM",
        "market_rescue_signal": 1,
        "liquidity_long_term_capital": 0,
        "ipo_supply_tightening": 0,
        "share_reduction_crackdown": 0,
        "quant_short_selling_tightening": 0,
        "speculation_fraud_crackdown": 0,
        "tech_innovation_support": 2,
        "ma_restructuring_support": 0,
        "dividend_buyback_push": 0,
        "brokerage_investment_bank": 1,
        "source": "live_v2_ingest",
        "resolves_master_ids": [],
    },
    {
        "master_id": "V2_20261123_BUYBACK",
        "shard_src": "live_v2_20261125",
        "event_date": "2026-11-23",
        "release_slot": "AMC",
        "authority_level": "CSRC_OFFICIAL",
        "is_joint_ministry": 0,
        "venue_type": "SYMPOSIUM",
        "action_verb_stage": "ROUTINE_SLOGAN",
        "speaker_or_body": "深圳等多地证监局",
        "title_or_occasion": "深圳等多地证监局密集召开上市公司座谈会鼓励依法合规开展回购增持与市值管理",
        "quotes_joined": "用好用足股票回购增持再贷款政策工具，鼓励辖区优质上市公司依法合规开展回购增持与一年多次分红。",
        "named_sectors_joined": "高股息红利,央企国企,回购增持龙头",
        "hard_levers_joined": "DIVIDEND_BUYBACK",
        "market_rescue_signal": 1,
        "liquidity_long_term_capital": 0,
        "ipo_supply_tightening": 0,
        "share_reduction_crackdown": 0,
        "quant_short_selling_tightening": 0,
        "speculation_fraud_crackdown": 0,
        "tech_innovation_support": 0,
        "ma_restructuring_support": 0,
        "dividend_buyback_push": 2,
        "brokerage_investment_bank": 0,
        "source": "live_v2_ingest",
        "resolves_master_ids": [],
    },
]


def _calc_streak(s: pd.Series) -> np.ndarray:
    arr = s.to_numpy(dtype=np.int8)
    out = np.zeros(len(arr), dtype=np.int16)
    c = 0
    for i, v in enumerate(arr):
        c = c + 1 if v else 0
        out[i] = c
    return out


def build_extended_market_panel(target_end_date: str = "2026-11-24", refresh_panel: bool = False) -> pd.DataFrame:
    if not refresh_panel and os.path.exists(V2_MP_PQ):
        mp_cached = pd.read_parquet(V2_MP_PQ)
        if str(mp_cached["date"].max()) >= target_end_date:
            print(f"[Panel] Reusing cached {V2_MP_PQ}: {len(mp_cached)} days [-> {mp_cached['date'].max()}]")
            return mp_cached
    mp = pd.read_parquet(ORIG_MP_PQ)
    mp = mp.sort_values("date").reset_index(drop=True)
    orig_max = str(mp["date"].max())
    print(f"[Panel] Loaded base daily_market_panel: {len(mp)} rows [{mp['date'].min()} -> {orig_max}]")

    # 1. Fetch fresh index closes/opens/highs/lows via Tencent akshare (D12 compliant)
    idx_tail_frames = {}
    all_new_dates = set()
    for sym, pfx in INDEX_MAP.items():
        df = ak.stock_zh_index_daily_tx(symbol=sym)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.sort_values("date").drop_duplicates("date")
        df = df[(df["date"] >= "2026-09-01") & (df["date"] <= target_end_date)].copy()
        for c in ["open", "high", "low", "close"]:
            df[f"{pfx}_{c}"] = df[c].astype(float)
        df[f"{pfx}_prev_close"] = df[f"{pfx}_close"].shift(1)
        df[f"{pfx}_cc_ret"] = df[f"{pfx}_close"] / df[f"{pfx}_prev_close"] - 1.0
        df[f"{pfx}_gap_ret"] = df[f"{pfx}_open"] / df[f"{pfx}_prev_close"] - 1.0
        df[f"{pfx}_oc_ret"] = df[f"{pfx}_close"] / df[f"{pfx}_open"] - 1.0
        sub = df[df["date"] > orig_max][[
            "date", f"{pfx}_open", f"{pfx}_high", f"{pfx}_low", f"{pfx}_close",
            f"{pfx}_cc_ret", f"{pfx}_gap_ret", f"{pfx}_oc_ret"
        ]].copy()
        # Handle sector indices missing high/low in orig panel cleanly
        for col in list(sub.columns):
            if col not in mp.columns:
                sub = sub.drop(columns=[col])
        idx_tail_frames[pfx] = sub
        all_new_dates.update(sub["date"].tolist())

    new_dates = sorted(d for d in all_new_dates if d > orig_max)
    print(f"[Panel] Extending with {len(new_dates)} new trading days: {new_dates}")
    if new_dates:
        ext = pd.DataFrame({"date": new_dates})
        for pfx, sub in idx_tail_frames.items():
            ext = ext.merge(sub, on="date", how="left")

        # 2. Compute exact A-share cross-sectional microstructure from a_daily.parquet
        t = pq.read_table(
            A_DAILY_PQ,
            columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "oshare"],
            filters=[("date", ">=", pd.Timestamp("2026-09-01")), ("date", "<=", pd.Timestamp(target_end_date))],
        )
        stk = t.to_pandas()
        stk["date"] = pd.to_datetime(stk["date"]).dt.strftime("%Y-%m-%d")
        stk = stk.drop_duplicates(["date", "ticker"]).sort_values(["ticker", "date"]).reset_index(drop=True)
        ratio = np.where(stk["close"] > 0, stk["adj_close"] / stk["close"], 1.0)
        stk["open_adj"] = stk["open"] * ratio
        stk["high_adj"] = stk["high"] * ratio
        stk["low_adj"] = stk["low"] * ratio
        stk["prev_adj_close"] = stk.groupby("ticker")["adj_close"].shift(1)
        valid = (stk["prev_adj_close"] > 0) & (stk["open_adj"] > 0) & (stk["adj_close"] > 0) & (stk["amount"] > 0)
        stk = stk[valid].copy()
        stk["cc_ret"] = stk["adj_close"] / stk["prev_adj_close"] - 1.0
        stk["gap_ret"] = stk["open_adj"] / stk["prev_adj_close"] - 1.0
        stk["oc_ret"] = stk["adj_close"] / stk["open_adj"] - 1.0
        stk["high_ret"] = stk["high_adj"] / stk["prev_adj_close"] - 1.0
        stk["mkt_cap"] = stk["close"] * stk["oshare"]

        tk = stk["ticker"].astype(str)
        is_20pct = tk.str.startswith("688") | tk.str.startswith("300") | tk.str.startswith("301")
        is_bj = tk.str.startswith("8") | tk.str.startswith("4") | tk.str.startswith("92")
        zt_thresh = np.where(is_bj, 0.292, np.where(is_20pct, 0.195, 0.0975))
        dt_thresh = np.where(is_bj, -0.292, np.where(is_20pct, -0.195, -0.0975))
        stk["is_zt"] = (stk["cc_ret"] >= zt_thresh) & (stk["cc_ret"] <= 0.35)
        stk["is_dt"] = (stk["cc_ret"] <= dt_thresh) & (stk["cc_ret"] >= -0.35)
        stk["touched_zt"] = (stk["high_ret"] >= zt_thresh) & (stk["high_ret"] <= 0.35)
        stk["is_broken_zt"] = stk["touched_zt"] & (~stk["is_zt"])
        stk["zt_streak"] = stk.groupby("ticker", sort=False)["is_zt"].transform(_calc_streak)
        stk["prev_zt_streak"] = stk.groupby("ticker", sort=False)["zt_streak"].shift(1).fillna(0)
        stk["is_tech_board"] = tk.str.startswith("688") | tk.str.startswith("300") | tk.str.startswith("301")
        stk["cap_pct"] = stk.groupby("date")["mkt_cap"].rank(pct=True)
        stk["is_micro30"] = stk["cap_pct"] <= 0.30
        stk["is_large10"] = stk["cap_pct"] >= 0.90
        stk["cc_clean"] = stk["cc_ret"].clip(-0.30, 0.30)
        stk["oc_clean"] = stk["oc_ret"].clip(-0.25, 0.25)
        stk["gap_clean"] = stk["gap_ret"].clip(-0.20, 0.20)
        big4_set = {"601398.SH", "601288.SH", "601988.SH", "601939.SH"}
        stk["is_big4"] = stk["ticker"].isin(big4_set)

        stk_new = stk[stk["date"].isin(new_dates)].copy()
        g = stk_new.groupby("date")
        daily_new = pd.DataFrame({
            "n_stocks": g["ticker"].count(),
            "total_amount_yi": g["amount"].sum() / 1e8,
            "ew_cc_ret": g["cc_clean"].mean(),
            "ew_oc_ret": g["oc_clean"].mean(),
            "ew_gap_ret": g["gap_clean"].mean(),
            "up_ratio": g["cc_ret"].apply(lambda s: (s > 0).mean()),
            "zt_cnt": g["is_zt"].sum(),
            "dt_cnt": g["is_dt"].sum(),
            "touched_zt_cnt": g["touched_zt"].sum(),
            "broken_zt_cnt": g["is_broken_zt"].sum(),
            "max_zt_streak": g["zt_streak"].max(),
            "b3plus_cnt": g["zt_streak"].apply(lambda s: (s >= 3).sum()),
        }).reset_index()
        daily_new["broken_rate"] = np.where(
            daily_new["touched_zt_cnt"] > 0,
            daily_new["broken_zt_cnt"] / daily_new["touched_zt_cnt"],
            np.nan,
        )
        for label, mask in [
            ("micro30", stk_new["is_micro30"]),
            ("large10", stk_new["is_large10"]),
            ("tech_board", stk_new["is_tech_board"]),
            ("high_relay", stk_new["prev_zt_streak"] >= 3),
            ("big4_bank", stk_new["is_big4"]),
        ]:
            sub = stk_new[mask].groupby("date").agg(**{
                f"{label}_cc_ret": ("cc_clean", "mean"),
                f"{label}_oc_ret": ("oc_clean", "mean"),
                f"{label}_gap_ret": ("gap_clean", "mean"),
            }).reset_index()
            daily_new = daily_new.merge(sub, on="date", how="left")

        ext = ext.merge(daily_new, on="date", how="left")

        # Append to full panel and recompute rolling state variables across splice boundary
        for c in mp.columns:
            if c not in ext.columns:
                ext[c] = np.nan
        mp_ext = pd.concat([mp, ext[mp.columns]], ignore_index=True).sort_values("date").reset_index(drop=True)
    else:
        mp_ext = mp.copy()

    # Recompute rolling benchmark & microstructure columns seamlessly on full panel
    mp_ext["bench_cc_ret"] = mp_ext["csi300_cc_ret"].fillna(mp_ext["large10_cc_ret"]).fillna(mp_ext["sh_comp_cc_ret"])
    mp_ext["bench_oc_ret"] = mp_ext["csi300_oc_ret"].fillna(mp_ext["large10_oc_ret"]).fillna(mp_ext["sh_comp_oc_ret"])
    mp_ext["bench_gap_ret"] = mp_ext["csi300_gap_ret"].fillna(mp_ext["large10_gap_ret"]).fillna(mp_ext["sh_comp_gap_ret"])
    mp_ext["bench_level"] = (1.0 + mp_ext["bench_cc_ret"].fillna(0.0)).cumprod()
    mp_ext["bench_ret_5d"] = mp_ext["bench_level"] / mp_ext["bench_level"].shift(5) - 1.0
    mp_ext["bench_ret_20d"] = mp_ext["bench_level"] / mp_ext["bench_level"].shift(20) - 1.0
    mp_ext["bench_ret_60d"] = mp_ext["bench_level"] / mp_ext["bench_level"].shift(60) - 1.0
    mp_ext["bench_dd_60d"] = mp_ext["bench_level"] / mp_ext["bench_level"].rolling(60, min_periods=10).max() - 1.0
    mp_ext["bench_dd_250d"] = mp_ext["bench_level"] / mp_ext["bench_level"].rolling(250, min_periods=30).max() - 1.0
    mp_ext["bench_vol_20d"] = mp_ext["bench_cc_ret"].rolling(20, min_periods=10).std() * np.sqrt(242)
    mp_ext["amount_pct_250d"] = mp_ext["total_amount_yi"].rolling(250, min_periods=30).rank(pct=True)
    mp_ext["amount_ratio_20d"] = mp_ext["total_amount_yi"] / mp_ext["total_amount_yi"].rolling(20, min_periods=5).mean()
    mp_ext["big4_vs_1000_ret"] = mp_ext["big4_bank_cc_ret"] - mp_ext["csi1000_cc_ret"]
    mp_ext["csi300_lower_shadow"] = (
        np.minimum(mp_ext["csi300_open"], mp_ext["csi300_close"]) - mp_ext["csi300_low"]
    ) / mp_ext["csi300_close"].shift(1)

    # 3. Merge V3.0 National Team daily panel & scores (2016-2026-11-24)
    v3_p = v3_cal.score_panel(v3_cal.load_master_panel())
    v3_cols = v3_p[[
        "date", "etf22_amt_yi", "etf22_flow_yi", "etf22_wflow_yi", "etf22_aum_yi",
        "t1_flow_yi", "t2_flow_yi", "etf22_amt_spike", "core10_amt_spike",
        "etf22_wflow_5d", "nt_tapering_stop", "score_live", "score_eod"
    ]].rename(columns={"score_live": "v3_score_live", "score_eod": "v3_score_eod"})
    mp_ext = mp_ext.merge(v3_cols, on="date", how="left")
    # Fill extended ETF cols on 2026-11-18 ~ 2026-11-24 where orig mp ended at 11-17
    tail_mask = mp_ext["date"] > orig_max
    if tail_mask.any():
        mp_ext.loc[tail_mask, "etf_tot_amt_yi"] = mp_ext.loc[tail_mask, "etf22_amt_yi"]
        mp_ext.loc[tail_mask, "etf_net_flow_yi"] = mp_ext.loc[tail_mask, "etf22_flow_yi"]
        mp_ext.loc[tail_mask, "etf_nt_weighted_flow_yi"] = mp_ext.loc[tail_mask, "etf22_wflow_yi"]
        mp_ext.loc[tail_mask, "etf_tot_aum_yi"] = mp_ext.loc[tail_mask, "etf22_aum_yi"]
        mp_ext.loc[tail_mask, "etf_t1_flow_yi"] = mp_ext.loc[tail_mask, "t1_flow_yi"]
        mp_ext.loc[tail_mask, "etf_t2_flow_yi"] = mp_ext.loc[tail_mask, "t2_flow_yi"]
        mp_ext.loc[tail_mask, "etf_amt_spike_20d"] = mp_ext.loc[tail_mask, "etf22_amt_spike"]
        mp_ext.loc[tail_mask, "etf_nt_weighted_flow_5d_yi"] = mp_ext.loc[tail_mask, "etf22_wflow_5d"]
        mp_ext.loc[tail_mask, "etf_data_avail"] = 1.0

    # 4. Merge notices.db dense exchange halt-check & severe abnormal notices (2025-01-02 ~ 2026-11-25)
    if os.path.exists(NOTICES_DB):
        conn = sqlite3.connect(NOTICES_DB)
        q = """
        SELECT ndate AS date,
          SUM(CASE WHEN title LIKE '%停牌核查%' AND title NOT LIKE '%复牌%' AND title NOT LIKE '%核查结果%' THEN 1 ELSE 0 END) AS notices_halt_check_cnt,
          SUM(CASE WHEN title LIKE '%重点监控%' THEN 1 ELSE 0 END) AS notices_monitor_cnt,
          SUM(CASE WHEN title LIKE '%严重异常波动%' THEN 1 ELSE 0 END) AS notices_sev_abn_cnt,
          SUM(CASE WHEN ntype LIKE '%关注函%' OR ntype LIKE '%监管函%' OR title LIKE '%监管工作函%' THEN 1 ELSE 0 END) AS notices_reg_letter_cnt
        FROM notice
        GROUP BY ndate
        """
        ndf = pd.read_sql(q, conn)
        conn.close()
        # Map weekend/holiday notices to next trading day <= 2026-11-24 or keep exact date aggregation mapped cleanly
        trade_dates = mp_ext["date"].tolist()
        t_arr = np.array(trade_dates)
        mapped = []
        for _, r in ndf.iterrows():
            d = str(r["date"])[:10]
            pos = np.searchsorted(t_arr, d, side="left")
            if pos < len(t_arr):
                td = t_arr[pos]
                # Only aggregate notices up to 2026-11-24 onto trading calendar; 2026-11-25 kept in status
                mapped.append((td, r["notices_halt_check_cnt"], r["notices_monitor_cnt"], r["notices_sev_abn_cnt"], r["notices_reg_letter_cnt"]))
        mdf = pd.DataFrame(mapped, columns=["date", "notices_halt_check_cnt", "notices_monitor_cnt", "notices_sev_abn_cnt", "notices_reg_letter_cnt"])
        mdf = mdf.groupby("date", as_index=False).sum()
        mp_ext = mp_ext.merge(mdf, on="date", how="left")
        m_2025 = mp_ext["date"] >= "2025-01-02"
        for col in ["notices_halt_check_cnt", "notices_monitor_cnt", "notices_sev_abn_cnt", "notices_reg_letter_cnt"]:
            mp_ext.loc[m_2025, col] = mp_ext.loc[m_2025, col].fillna(0)
        mp_ext["notices_sev_abn_5d"] = mp_ext["notices_sev_abn_cnt"].rolling(5, min_periods=1).sum()
        mp_ext["notices_reg_letter_5d"] = mp_ext["notices_reg_letter_cnt"].rolling(5, min_periods=1).sum()

    # Fill ex_cnt5 gap cleanly after 2026-11-12 using last known or notices proxy
    if "ex_cnt5" in mp_ext.columns:
        mp_ext["ex_cnt5"] = mp_ext["ex_cnt5"].ffill()

    mp_ext.to_parquet(V2_MP_PQ, index=False)
    print(f"[Panel] Saved {V2_MP_PQ}: {len(mp_ext)} days [{mp_ext['date'].min()} -> {mp_ext['date'].max()}], {len(mp_ext.columns)} cols")
    return mp_ext


def _align_event_row(ev: dict, mp_ext: pd.DataFrame, date_to_idx: dict, dates: list) -> dict:
    dt = str(ev["event_date"])[:10]
    slot = str(ev.get("release_slot", "AMC")).upper()
    if dt in date_to_idx:
        i_dt = date_to_idx[dt]
        if slot == "BMO":
            t_entry, t_prior = i_dt, i_dt - 1
        elif slot == "INTRADAY":
            t_entry, t_prior = i_dt + 1, i_dt - 1
        else:
            t_entry, t_prior = i_dt + 1, i_dt
    else:
        later = [i for i, d in enumerate(dates) if d > dt]
        t_entry = later[0] if later else len(dates)
        t_prior = (t_entry - 1) if t_entry > 0 else len(dates) - 1

    rec = dict(ev)
    rec.pop("resolves_master_ids", None)
    rec["event_date"] = dt
    rec["release_slot"] = slot
    rec["tradable_date"] = dates[t_entry] if t_entry < len(dates) else "PENDING_NEXT_OPEN"
    rec["t_entry_idx"] = int(t_entry) if t_entry < len(dates) else -1
    rec["chairman_era"] = rec.get("chairman_era", "吴清")
    rec["days_in_office"] = int((pd.Timestamp(dt) - pd.Timestamp("2024-02-07")).days)
    rec["weekday"] = int(pd.Timestamp(dt).dayofweek)
    rec["month"] = int(pd.Timestamp(dt).month)
    rec["n_subseq_policies"] = int(rec.get("n_subseq_policies", 0))
    rec["min_policy_lead_days"] = int(rec.get("min_policy_lead_days", -1))
    rec["has_policy_within_15d"] = int(rec.get("has_policy_within_15d", 0))
    rec["has_policy_within_30d"] = int(rec.get("has_policy_within_30d", 0))
    rec["has_policy_within_60d"] = int(rec.get("has_policy_within_60d", 0))
    rec["has_policy_within_90d"] = int(rec.get("has_policy_within_90d", 0))

    t_pr = min(max(0, t_prior), len(mp_ext) - 1)
    pr = mp_ext.iloc[t_pr]
    rec["prior_dd_60d"] = float(pr["bench_dd_60d"]) if pd.notna(pr["bench_dd_60d"]) else np.nan
    rec["prior_dd_250d"] = float(pr["bench_dd_250d"]) if pd.notna(pr["bench_dd_250d"]) else np.nan
    rec["prior_ret_20d"] = float(pr["bench_ret_20d"]) if pd.notna(pr["bench_ret_20d"]) else np.nan
    rec["prior_ret_5d"] = float(pr["bench_ret_5d"]) if pd.notna(pr["bench_ret_5d"]) else np.nan
    rec["prior_vol_20d"] = float(pr["bench_vol_20d"]) if pd.notna(pr["bench_vol_20d"]) else np.nan
    rec["prior_amt_pct_250d"] = float(pr["amount_pct_250d"]) if pd.notna(pr["amount_pct_250d"]) else np.nan
    rec["prior_amt_yi"] = float(pr["total_amount_yi"]) if pd.notna(pr["total_amount_yi"]) else np.nan
    rec["prior_zt_cnt"] = float(pr["zt_cnt"]) if pd.notna(pr["zt_cnt"]) else np.nan
    rec["prior_dt_cnt"] = float(pr["dt_cnt"]) if pd.notna(pr["dt_cnt"]) else np.nan
    rec["prior_max_streak"] = float(pr["max_zt_streak"]) if pd.notna(pr["max_zt_streak"]) else np.nan
    rec["prior_broken_rate"] = float(pr["broken_rate"]) if pd.notna(pr["broken_rate"]) else np.nan
    return rec


def build_v2_events(mp_ext: pd.DataFrame, extra_json_path: str = None) -> pd.DataFrame:
    ev_orig = pd.read_parquet(ORIG_EV_PQ).copy()
    ev_orig["source"] = "historical_pit_v1"

    # Strictly remove same-day (lead=0) leaks on non-HARD_ACTION_NOW events
    # Per shard audit:
    # - M0525 (2024-06-19 DRAFT_CONSULT): lead_days=[0, 97] -> strict lead>=1 is 97d
    # - M0628 (2026-07-03 DRAFT_CONSULT): lead_days=[0] -> strict lead>=1 is none (-1)
    leak_fixes = []
    for mid, new_lead in [("M0525", 97), ("M0628", -1)]:
        m = (ev_orig["master_id"] == mid) & (ev_orig["action_verb_stage"] != "HARD_ACTION_NOW")
        if m.any():
            ev_orig.loc[m, "min_policy_lead_days"] = new_lead
            for h in [15, 30, 60, 90]:
                ev_orig.loc[m, f"has_policy_within_{h}d"] = int(1 <= new_lead <= h)
            leak_fixes.append({"master_id": mid, "new_min_lead": new_lead})

    # Also align pending M0652-M0659 entry indices where panel now extends to 2026-11-24
    dates = mp_ext["date"].tolist()
    date_to_idx = {d: i for i, d in enumerate(dates)}

    extra_events = list(LIVE_VERIFIED_EVENTS)
    if extra_json_path:
        raw = json.load(open(extra_json_path, "r", encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("events", [raw])
        for item in raw:
            item.setdefault("source", "cli_added_json")
            extra_events.append(item)

    existing_keys = set(zip(ev_orig["master_id"], ev_orig["event_date"]))
    new_rows = []
    resolved_links = []
    for raw_ev in extra_events:
        res_ids = raw_ev.get("resolves_master_ids") or []
        dt_new = str(raw_ev["event_date"])[:10]
        for rm_id in res_ids:
            m = ev_orig["master_id"] == rm_id
            if m.any():
                dt_src = str(ev_orig.loc[m, "event_date"].iloc[0])[:10]
                ld = (pd.Timestamp(dt_new) - pd.Timestamp(dt_src)).days
                if ld >= 1:
                    cur_ld = int(ev_orig.loc[m, "min_policy_lead_days"].iloc[0])
                    best_ld = ld if cur_ld < 1 else min(cur_ld, ld)
                    ev_orig.loc[m, "min_policy_lead_days"] = best_ld
                    for h in [15, 30, 60, 90]:
                        if 1 <= best_ld <= h:
                            ev_orig.loc[m, f"has_policy_within_{h}d"] = 1
                    ev_orig.loc[m, "n_subseq_policies"] = ev_orig.loc[m, "n_subseq_policies"].astype(int) + 1
                    lv = str(raw_ev.get("hard_levers_joined", ""))
                    if lv:
                        prev_lv = str(ev_orig.loc[m, "hard_levers_joined"].iloc[0] or "")
                        joined = ",".join(dict.fromkeys([x for x in (prev_lv + "," + lv).split(",") if x]))
                        ev_orig.loc[m, "hard_levers_joined"] = joined
                    resolved_links.append({"from_master_id": rm_id, "to_master_id": raw_ev["master_id"], "lead_days": ld})

        k = (raw_ev.get("master_id", ""), dt_new)
        if k in existing_keys:
            continue
        existing_keys.add(k)
        new_rows.append(_align_event_row(raw_ev, mp_ext, date_to_idx, dates))

    df_new = pd.DataFrame(new_rows)
    for col in ev_orig.columns:
        if col not in df_new.columns:
            df_new[col] = np.nan if ev_orig[col].dtype.kind in "fc" else (0 if ev_orig[col].dtype.kind in "iu" else "")
    df_all = pd.concat([ev_orig, df_new[ev_orig.columns]], ignore_index=True)
    df_all = df_all.sort_values(["event_date", "master_id"]).reset_index(drop=True)

    # Recompute tradable_date / t_entry_idx for recent or previously pending rows
    for idx in df_all.index:
        dt = str(df_all.at[idx, "event_date"])[:10]
        slot = str(df_all.at[idx, "release_slot"]).upper()
        if dt >= "2026-11-14" or str(df_all.at[idx, "tradable_date"]) == "PENDING_NEXT_OPEN":
            if dt in date_to_idx:
                i_dt = date_to_idx[dt]
                t_en = i_dt if slot == "BMO" else i_dt + 1
            else:
                later = [i for i, d in enumerate(dates) if d > dt]
                t_en = later[0] if later else len(dates)
            df_all.at[idx, "t_entry_idx"] = int(t_en) if t_en < len(dates) else -1
            df_all.at[idx, "tradable_date"] = dates[t_en] if t_en < len(dates) else "PENDING_NEXT_OPEN"

    # Recompute pos_cluster_10d strictly PIT across full sorted table
    pos_mask = (df_all["market_rescue_signal"].fillna(0) + df_all["liquidity_long_term_capital"].fillna(0)) >= 2
    # Map each event date to trading-day index on mp_ext for cluster counting even when t_entry_idx == -1
    t_arr = np.array(dates)
    ev_tidx = [int(np.searchsorted(t_arr, str(d)[:10], side="left")) for d in df_all["event_date"]]
    pos_tidx = np.array([ev_tidx[i] for i in range(len(df_all)) if pos_mask.iloc[i]])
    df_all["pos_cluster_10d"] = [
        int(np.sum((pos_tidx >= tidx - 10) & (pos_tidx <= tidx)))
        for tidx in ev_tidx
    ]

    df_all.to_parquet(V2_EV_PQ, index=False)

    audit = {
        "as_of_date": "2026-11-25",
        "panel_max_date": str(mp_ext["date"].max()),
        "panel_rows": int(len(mp_ext)),
        "panel_cols": int(len(mp_ext.columns)),
        "events_total": int(len(df_all)),
        "events_historical": int((df_all["source"] == "historical_pit_v1").sum()),
        "events_live_v2": int((df_all["source"] == "live_v2_ingest").sum()),
        "non_hard_total": int((df_all["action_verb_stage"] != "HARD_ACTION_NOW").sum()),
        "non_hard_lead0_remaining": int(((df_all["action_verb_stage"] != "HARD_ACTION_NOW") & (df_all["min_policy_lead_days"] == 0)).sum()),
        "leak_fixes_applied": leak_fixes,
        "resolved_links": resolved_links,
        "live_events_added": [
            {"master_id": r["master_id"], "event_date": r["event_date"], "authority_level": r["authority_level"], "action_verb_stage": r["action_verb_stage"], "title": r["title_or_occasion"]}
            for r in new_rows
        ],
    }
    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"[Events] Saved {V2_EV_PQ}: {len(df_all)} events (live_v2={audit['events_live_v2']}, lead0_rem={audit['non_hard_lead0_remaining']})")
    return df_all


def show_status():
    if os.path.exists(AUDIT_JSON):
        print(json.dumps(json.load(open(AUDIT_JSON, encoding="utf-8")), ensure_ascii=False, indent=2))
    else:
        print("ingest_v2_audit.json not generated yet.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add-event-json", default=None, help="Optional JSON file with new events to append")
    ap.add_argument("--refresh-panel", action="store_true", help="Force re-fetch of index & market panel")
    ap.add_argument("--status", action="store_true", help="Print current ingest v2 status and exit")
    args = ap.parse_args()

    if args.status and os.path.exists(V2_EV_PQ) and os.path.exists(V2_MP_PQ):
        show_status()
        return

    mp_ext = build_extended_market_panel("2026-11-24", refresh_panel=args.refresh_panel)
    build_v2_events(mp_ext, extra_json_path=args.add_event_json)
    show_status()


if __name__ == "__main__":
    main()
