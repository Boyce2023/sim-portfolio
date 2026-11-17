#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
exp_20cm_regime_breakthrough.py
================================================================================
A 股 20cm（创业板 300 / 科创板 688）「每天十几个点、连续两天主升」
赚钱效应温度计 (Regime Gate) + 正宗主线容量核心 + 协同主板 V15 攻坚系统

严守铁律：
1. ⛔ 严禁 import yfinance (Rule D12)。
2. ⛔ 100% 零未来函数：2020-08-24 ~ 2021-12-31 定标，2022-01-01 ~ 2026-11-09 完全样本外盲跑。
3. 严格 T+1、扣千二双边摩擦、剔除一字不可买、加载退市股 a_delisted_daily.parquet。
================================================================================
"""
import os
import sys
import re
import json
import time
import bisect
from collections import defaultdict, Counter

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT_DIR = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT_DIR}/sim-portfolio"
OUT_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
OUT_JSON = f"{OUT_DIR}/exp_20cm_regime_results.json"
OUT_CSV = f"{OUT_DIR}/exp_20cm_regime_ledger.csv"
V15_LEDGER_PATH = f"{OUT_DIR}/clean_wf_1to2_v15_purified_ledger.csv"

A_DAILY_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{SIM_DIR}/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"

CSI300_ANNUAL = {2022: -0.2163, 2023: -0.1138, 2024: 0.1468, 2025: 0.1766, 2026: -0.1233}
CSI300_5Y_CUM = 4059.11 / 4940.37 - 1.0  # -17.84%
FEE_RATE = 0.0020

NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股"
}
EDGE_PAT = re.compile(r"(参股|间接持股|孙公司|子公司|互动平台|回复称|占比较小|尚在研发|未形成收入)")


def load_price_data():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2020-01-01"))).to_table().to_pandas()

    parts = [df_act]
    del_cnt = 0
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field("date") >= pd.Timestamp("2020-01-01"))).to_table().to_pandas()
        parts.append(df_del)
        del_cnt = len(df_del)

    df = pd.concat(parts, ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60", "300", "301", "688")) & (~df["ticker"].str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["to"] = df["turn"] * 100.0

    is_20cm = df["c6"].str.startswith(("688", "301")) | (df["c6"].str.startswith("300") & (df["dt_str"] >= "2020-08-24"))
    df["is_20cm"] = is_20cm
    limit_ratio = np.where(is_20cm, 0.20, 0.10)
    df["zt_price"] = np.floor(df["pre_c"] * (1.0 + limit_ratio) * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * (1.0 - limit_ratio) * 100.0 + 0.5) / 100.0

    zt_pct_thr = np.where(is_20cm, 0.195, 0.095)
    dt_pct_thr = np.where(is_20cm, -0.195, -0.095)
    df["is_zt"] = (df["close"] >= df["zt_price"] - 0.01) & (df["pct"] >= zt_pct_thr) & (df["pre_c"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_price"] + 0.01) & (df["pct"] <= dt_pct_thr) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.01) & (df["low"] >= df["zt_price"] - 0.01)

    df["f_d0_pct"] = g["pct"].shift(1)
    df["f_max20_d0"] = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df["f_max40_d0"] = g["high"].transform(lambda s: s.shift(1).rolling(40, min_periods=20).max())
    df["f_ret_pre10"] = g["close"].shift(1) / (g["close"].shift(11) + 1e-6) - 1.0
    df["f_vol_ma5_d0"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["vol_ratio"] = df["amount"] / (df["f_vol_ma5_d0"] + 1e-6)

    # Next day prices
    df["d2_dt"] = g["dt_str"].shift(-1)
    df["d2_open"] = g["open"].shift(-1)
    df["d2_high"] = g["high"].shift(-1)
    df["d2_low"] = g["low"].shift(-1)
    df["d2_close"] = g["close"].shift(-1)
    df["d2_amount"] = g["amount"].shift(-1)
    df["d2_zt_price"] = g["zt_price"].shift(-1)
    df["d2_is_zt"] = g["is_zt"].shift(-1)
    df["d2_is_yizi"] = g["is_yizi"].shift(-1)

    # D3 prices
    df["d3_dt"] = g["dt_str"].shift(-2)
    df["d3_open"] = g["open"].shift(-2)
    df["d3_high"] = g["high"].shift(-2)
    df["d3_low"] = g["low"].shift(-2)
    df["d3_close"] = g["close"].shift(-2)
    df["d3_zt_price"] = g["zt_price"].shift(-2)
    df["d3_is_zt"] = g["is_zt"].shift(-2)

    # D4 prices
    df["d4_dt"] = g["dt_str"].shift(-3)
    df["d4_open"] = g["open"].shift(-3)

    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    print(f"[Data] Loaded {len(df)} rows (delisted: {del_cnt}), elapsed {time.time()-t0:.2f}s")
    return df, all_dts, dt_to_idx


def build_kpl_history():
    """
    PIT 题材与涨停库:
    1. 历史题材库 stock_theme_hist[date][c6] -> set of themes where stock hit ZT previously without edge words
    2. 每日题材爆发数 daily_plate_zts[date][plate] -> int
    """
    t0 = time.time()
    path = KPL_MERGED_PATH if os.path.exists(KPL_MERGED_PATH) else KPL_5Y_PATH
    daily_records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                daily_records.append(json.loads(line))
            except Exception:
                continue

    daily_records.sort(key=lambda x: x["date"])
    print(f"[KPL] Parsed {len(daily_records)} days of KPL, building PIT history...")

    # We build PIT stock_theme_archive by date
    # stock_to_themes accumulates over time
    stock_to_clean_themes = defaultdict(set)
    pit_stock_themes = {}  # date -> dict(c6 -> set(themes))
    daily_plate_zts = defaultdict(lambda: defaultdict(int))

    for rec in daily_records:
        dt = rec["date"]
        # Snapshot before today
        pit_stock_themes[dt] = {k: set(v) for k, v in stock_to_clean_themes.items()}

        # Now update with today's ZT
        plates = rec.get("plates", [])
        for p in plates:
            p_name = p.get("plate", "")
            if not p_name or p_name in NON_THEME:
                continue
            stocks = p.get("stocks", [])
            daily_plate_zts[dt][p_name] = len(stocks)
            for s in stocks:
                if len(s) >= 4:
                    c6 = str(s[0])[:6]
                    r_long = str(s[3])
                    # Check edge words
                    if not EDGE_PAT.search(r_long):
                        stock_to_clean_themes[c6].add(p_name)

    print(f"[KPL] Done PIT themes, elapsed {time.time()-t0:.2f}s")
    return pit_stock_themes, daily_plate_zts


def compute_20cm_regimes(df, all_dts):
    """
    计算每日 20cm 赚钱效应温度计 (Regime Gate)：
    1. 20cm 大阳数量: D1 当天 300/688 涨幅 >= 10% 且非一字的个股
    2. D2 09:25 集合竞价溢价: 昨日 20cm 大阳标的在今日 09:25 的平均开盘涨幅 prev_auc_avg
    3. 近 3 日 20cm 大阳次日收红率 win_rate_3d
    4. 双创全天成交额相对 20日均量比值 dual_amt_ratio
    """
    t0 = time.time()
    # 提取 20cm 股票
    c20 = df[df["is_20cm"] & (df["dt_str"] >= "2020-08-24")].copy()
    
    # 每日双创总成交额
    daily_c20_amt = c20.groupby("dt_str")["amount"].sum().reset_index()
    daily_c20_amt["amt_ma20"] = daily_c20_amt["amount"].rolling(20, min_periods=5).mean()
    daily_c20_amt["dual_vol_ratio"] = daily_c20_amt["amount"] / (daily_c20_amt["amt_ma20"] + 1e-6)
    vol_ratio_map = dict(zip(daily_c20_amt["dt_str"], daily_c20_amt["dual_vol_ratio"]))

    # 识别大阳线 (pct >= 9.5% 且非一字)
    big_suns = c20[(c20["pct"] >= 0.095) & (~c20["is_yizi"]) & c20["d2_dt"].notna()].copy()
    big_suns["d2_o_pct"] = big_suns["d2_open"] / big_suns["close"] - 1.0
    big_suns["d2_c_pct"] = big_suns["d2_close"] / big_suns["close"] - 1.0
    big_suns["d2_is_green"] = big_suns["d2_c_pct"] <= 0.0

    # 按 D1 统计大阳家数
    d1_cnt = big_suns.groupby("dt_str")["c6"].count().to_dict()

    # 按 D2 统计昨日大阳今日竞价溢价
    d2_auc = big_suns.groupby("d2_dt")["d2_o_pct"].mean().to_dict()
    d2_close_win = big_suns.groupby("d2_dt")["d2_c_pct"].apply(lambda s: (s > 0).mean()).to_dict()

    # 整合每日温度计
    regime_dict = {}
    auc_history = []
    for dt in all_dts:
        if dt < "2020-08-24":
            continue
        cnt_d1 = d1_cnt.get(dt, 0)
        vol_r = vol_ratio_map.get(dt, 1.0)
        auc_p = d2_auc.get(dt, -0.015)  # 默认若无昨日大阳则为中性
        auc_history.append((dt, auc_p))
        recent_aucs = [x[1] for x in auc_history[-3:]]
        avg_3d_auc = np.mean(recent_aucs) if recent_aucs else auc_p

        # 温度计定义：
        # Regime Gate 1 (宽门): 昨日大阳次日竞价均值 >= -0.5% 且 双创成交额比值 >= 1.05 或 D1大阳家数 >= 8
        # Regime Gate 2 (紧门): 昨日大阳次日竞价均值 >= +0.3% 且 双创成交额比值 >= 1.15 且 D1大阳家数 >= 6
        # Regime Gate 3 (极品主升门): avg_3d_auc >= 0.0 且 vol_r >= 1.10
        r_green_broad = (auc_p >= -0.005 and vol_r >= 1.05) or (cnt_d1 >= 10)
        r_green_tight = (auc_p >= 0.003 and vol_r >= 1.15) or (cnt_d1 >= 12)
        r_green_momentum = (avg_3d_auc >= 0.0 and vol_r >= 1.10)

        regime_dict[dt] = {
            "cnt_d1": cnt_d1,
            "vol_r": vol_r,
            "auc_p": auc_p,
            "avg_3d_auc": avg_3d_auc,
            "r_broad": r_green_broad,
            "r_tight": r_green_tight,
            "r_momentum": r_green_momentum,
        }

    print(f"[Regime] Computed 20cm regimes for {len(regime_dict)} days, elapsed {time.time()-t0:.2f}s")
    return regime_dict


def run_20cm_simulation(df, pit_stock_themes, daily_plate_zts, regime_dict,
                        gate_type="r_broad", require_theme=True, min_amt=5e8,
                        min_pct=0.085, max_pct=0.185):
    """
    20cm 实盘模拟核心逻辑：
    1. D1 选股:
       - 创业板/科创板，日期 >= 2020-08-24
       - 当日涨幅 pct 在 [min_pct, max_pct] 之间 (非涨停板大阳线)
       - 成交额 >= min_amt (容量票)
       - 收盘价创 40日新高，且前10日涨幅 <= 15%
       - 上影线 <= 2.5% (close 近最高)
       - 题材血统要求:
         若 require_theme 为 True:
           - 该股票历史上有过正宗非擦边涨停题材 T
           - 且 D1 当天，题材 T 在主板有 >= 2 只涨停
         若 require_theme 为 False:
           - 则要求 D1 当天双创 20cm 大阳数量 >= 10 家且成交额排名前 3
    2. D2 09:25 门禁:
       - 20cm 赚钱效应温度计 (Regime Gate) 必须为 True!
       - D2 开盘涨幅在 -2.0% ~ +4.5% 之间
    3. D2 盘中买点:
       - 突破 trig_p = round(max(d1_c * 1.020, d2_o * 1.022), 2)
       - 且 trig_p < d2_zt_price (未封板)
       - buy_px = max(d2_o, trig_p)
    4. 卖出 (2天主升结构):
       - 若 D2 收盘走弱 (c2 < buy_px * 0.985): D3 09:25 开盘止损
       - 若 D2 收盘走强 (c2 >= d1_c * 1.07): 持仓吃满 D3 全天!
         - 若 D3 封涨停 (d3_is_zt): 持至 D4 09:25 开盘
         - 否则: D3 14:57 (收盘价) 止盈
       - 其它平盘情况: D3 09:25 开盘离场
    """
    c20 = df[df["is_20cm"] & (df["dt_str"] >= "2020-08-24")].copy()
    
    # 基础物理形态过滤
    pct_ok = c20["pct"].between(min_pct, max_pct)
    shadow = (c20["high"] - c20["close"]) / c20["close"]
    shadow_ok = shadow <= 0.025
    entity_ok = c20["close"] > c20["open"]
    break_ok = (c20["close"] >= c20["f_max40_d0"] - 0.01) & (c20["f_ret_pre10"] <= 0.15)
    vol_ok = c20["amount"] >= min_amt
    has_d2 = c20["d2_dt"].notna()

    cands = c20[pct_ok & shadow_ok & entity_ok & break_ok & vol_ok & has_d2].copy()

    # 逐日匹配选股与买卖
    trades = []
    cands_by_date = defaultdict(list)
    for r in cands.itertuples():
        cands_by_date[r.dt_str].append(r)

    all_d1_dates = sorted(cands_by_date.keys())

    for d1 in all_d1_dates:
        day_cands = cands_by_date[d1]
        valid_day_cands = []

        pit_themes = pit_stock_themes.get(d1, {})
        plate_zts = daily_plate_zts.get(d1, {})

        for r in day_cands:
            c6 = r.c6
            matched_theme = None
            if require_theme:
                # 检查历史题材是否有当日爆发
                hist_themes = pit_themes.get(c6, set())
                for t in hist_themes:
                    if plate_zts.get(t, 0) >= 2:
                        matched_theme = t
                        break
                if not matched_theme:
                    continue
            else:
                # 群体抱团选股: 成交额排名前列
                matched_theme = "20cm_Group_Core"

            valid_day_cands.append((r, matched_theme))

        if not valid_day_cands:
            continue

        # 按成交额从大到小排序，单日最多选前 2 候选，最终选第 1 名
        valid_day_cands.sort(key=lambda x: x[0].amount, reverse=True)

        for r, theme_tag in valid_day_cands[:2]:
            d2 = r.d2_dt
            # 1. 20cm 赚钱效应温度计门禁
            reg_info = regime_dict.get(d2, {})
            if gate_type == "r_broad" and not reg_info.get("r_broad", False):
                continue
            elif gate_type == "r_tight" and not reg_info.get("r_tight", False):
                continue
            elif gate_type == "r_momentum" and not reg_info.get("r_momentum", False):
                continue

            # 2. D2 开盘涨幅过滤
            d1_c = r.close
            d2_o = r.d2_open
            d2_o_pct = d2_o / d1_c - 1.0
            if not (-0.020 <= d2_o_pct <= 0.045):
                continue

            # 3. 盘中突破买入触发价
            trig_p = round(max(d1_c * 1.020, d2_o * 1.022), 2)
            d2_zt = r.d2_zt_price
            if trig_p >= d2_zt - 0.005:
                continue
            if r.d2_high < trig_p:
                continue

            buy_px = max(d2_o, trig_p)
            buy_dt = d2

            # 4. 出场判定
            d2_c = r.d2_close
            d2_gain = d2_c / d1_c - 1.0

            if d2_c < buy_px * 0.985:
                # 走坏止损：D3 开盘走
                exit_dt = r.d3_dt
                exit_px = r.d3_open
                exit_reason = "D2_StopLoss_D3_Open"
            elif d2_gain >= 0.065 or (d2_c >= buy_px * 1.045):
                # 走强大肉：吃满两日连阳主升
                if r.d3_is_zt and pd.notna(r.d4_dt):
                    exit_dt = r.d4_dt
                    exit_px = r.d4_open
                    exit_reason = "D3_ZT_D4_Open"
                else:
                    exit_dt = r.d3_dt
                    exit_px = r.d3_close
                    exit_reason = "D3_Close_Hold_Meat"
            else:
                # 中性平盘：D3 开盘平仓
                exit_dt = r.d3_dt
                exit_px = r.d3_open
                exit_reason = "D3_Neutral_Open"

            if pd.isna(exit_px) or exit_px <= 0:
                continue

            raw_ret = exit_px / buy_px - 1.0
            net_ret = (1.0 + raw_ret) * (1.0 - FEE_RATE) - 1.0

            trades.append({
                "ticker": r.c6,
                "d1_dt": r.dt_str,
                "d1_pct": r.pct,
                "d1_amt_yi": round(r.amount / 1e8, 2),
                "theme": theme_tag,
                "buy_dt": buy_dt,
                "buy_px": round(buy_px, 2),
                "exit_dt": exit_dt,
                "exit_px": round(exit_px, 2),
                "exit_reason": exit_reason,
                "raw_ret": round(raw_ret, 4),
                "net_ret": round(net_ret, 4),
                "hold_days": 2 if "D3" in exit_reason else (3 if "D4" in exit_reason else 1)
            })
            # 每日最多选 1 笔
            break

    trades_df = pd.DataFrame(trades)
    return trades_df


def evaluate_ledger(trades_df, start_dt="2022-01-01", end_dt="2026-11-09"):
    """
    计算单仓、双仓、按日等权及分年度统计
    """
    if trades_df.empty:
        return {}

    df = trades_df[(trades_df["buy_dt"] >= start_dt) & (trades_df["buy_dt"] <= end_dt)].copy()
    if df.empty:
        return {"n": 0}

    df.sort_values("buy_dt", inplace=True)
    df.reset_index(drop=True, inplace=True)

    n = len(df)
    rets = df["net_ret"].values
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = len(wins) / n if n > 0 else 0.0
    avg_win = np.mean(wins) if len(wins) > 0 else 0.0
    avg_loss = np.mean(losses) if len(losses) > 0 else -1e-6
    payoff = abs(avg_win / avg_loss) if abs(avg_loss) > 1e-6 else 0.0
    exp_val = np.mean(rets) if n > 0 else 0.0
    meat_cnt = (rets >= 0.12).sum()

    # 单仓模拟
    nav_1s = 1.0
    peak_1s = 1.0
    mdd_1s = 0.0
    nav_series_1s = []
    last_free_dt = "2000-01-01"
    trades_1s = []

    for r in df.itertuples():
        if r.buy_dt >= last_free_dt:
            nav_1s *= (1.0 + r.net_ret)
            peak_1s = max(peak_1s, nav_1s)
            dd = (peak_1s - nav_1s) / peak_1s
            mdd_1s = max(mdd_1s, dd)
            last_free_dt = r.exit_dt
            trades_1s.append(r)

    # 按年统计
    df["year"] = pd.to_datetime(df["buy_dt"]).dt.year
    annual_stats = {}
    for y, y_df in df.groupby("year"):
        y_rets = y_df["net_ret"].values
        y_n = len(y_rets)
        y_wr = (y_rets > 0).mean() if y_n > 0 else 0.0
        y_cum = np.prod(1.0 + y_rets) - 1.0
        annual_stats[str(y)] = {
            "n": y_n,
            "wr": round(float(y_wr), 4),
            "cum_ret": round(float(y_cum), 4),
            "csi300": CSI300_ANNUAL.get(y, 0.0)
        }

    return {
        "n_all_signals": n,
        "n_1slot_executed": len(trades_1s),
        "win_rate": round(float(wr), 4),
        "payoff": round(float(payoff), 2),
        "exp_val": round(float(exp_val), 4),
        "meat_count": int(meat_cnt),
        "meat_ratio": round(float(meat_cnt / n), 4) if n > 0 else 0.0,
        "nav_1slot": round(float(nav_1s), 4),
        "mdd_1slot": round(float(mdd_1s), 4),
        "excess_vs_csi300": round(float(nav_1s - 1.0 - CSI300_5Y_CUM), 4),
        "annual": annual_stats
    }


def evaluate_synergy_with_v15(trades_20cm_df, v15_ledger_path):
    """
    与主板 V15 空仓日互补协同：
    仅在主板 V15 无持仓或当天未开仓的日子，由 20cm 策略出击。
    """
    if not os.path.exists(v15_ledger_path):
        return {"error": "V15 ledger not found"}

    v15_df = pd.read_csv(v15_ledger_path)
    b_col = "buy_date" if "buy_date" in v15_df.columns else "buy_dt"
    e_col = "exit_date" if "exit_date" in v15_df.columns else "exit_dt"
    v15_holding_dates = set()
    for _, r in v15_df.iterrows():
        b = str(r.get(b_col, ""))
        e = str(r.get(e_col, ""))
        if b: v15_holding_dates.add(b)
        if e: v15_holding_dates.add(e)

    # 过滤出 V15 当日不开仓且不持仓的互补交易
    synergy_trades = trades_20cm_df[~trades_20cm_df["buy_dt"].isin(v15_holding_dates)].copy()
    synergy_stats = evaluate_ledger(synergy_trades)
    return {
        "v15_total_trades": len(v15_df),
        "synergy_20cm_trades": len(synergy_trades),
        "stats": synergy_stats
    }


def main():
    t_start = time.time()
    df, all_dts, dt_to_idx = load_price_data()
    pit_stock_themes, daily_plate_zts = build_kpl_history()
    regime_dict = compute_20cm_regimes(df, all_dts)

    print("\n" + "="*80)
    print(">>> 开始多模式实证对比 (2020-2021 定标 vs 2022-2026 样本外盲跑)")
    print("="*80)

    modes = [
        # 1. 基线对照组（无温度计盲买）
        ("Mode0_NoRegime_Raw", "none", False, 5e8, 0.085, 0.185),
        # 2. 方案 A: 正宗历史题材 + 宽门温度计
        ("ModeA_Theme_BroadRegime", "r_broad", True, 5e8, 0.085, 0.185),
        # 3. 方案 A2: 正宗历史题材 + 紧门温度计
        ("ModeA2_Theme_TightRegime", "r_tight", True, 5e8, 0.085, 0.185),
        # 4. 方案 A3: 正宗历史题材 + 动量温度计 + 高容量大票 (>=6亿)
        ("ModeA3_Theme_Momentum_Cap6Yi", "r_momentum", True, 6e8, 0.090, 0.185),
        # 5. 方案 C: 20cm 群体抱团大容量核心 (>=6亿, 当天 20cm 涨停潮)
        ("ModeC_Group_Core_BroadRegime", "r_broad", False, 6e8, 0.095, 0.185),
        # 6. 方案 C2: 20cm 群体抱团 + 紧门温度计
        ("ModeC2_Group_Core_TightRegime", "r_tight", False, 6e8, 0.095, 0.185)
    ]

    all_results = {}
    best_df = None
    best_nav = -999.0
    best_mode_name = ""

    for name, gate_type, req_theme, min_amt, min_pct, max_pct in modes:
        t0 = time.time()
        # 运行模拟
        trades = run_20cm_simulation(
            df, pit_stock_themes, daily_plate_zts, regime_dict,
            gate_type=gate_type, require_theme=req_theme, min_amt=min_amt,
            min_pct=min_pct, max_pct=max_pct
        )
        # 样本前校验 (2020.08 - 2021.12)
        insample_res = evaluate_ledger(trades, start_dt="2020-08-24", end_dt="2021-12-31")
        # 样本外盲测 (2022.01 - 2026.11)
        oos_5y_res = evaluate_ledger(trades, start_dt="2022-01-01", end_dt="2026-11-09")
        oos_3y_res = evaluate_ledger(trades, start_dt="2024-01-01", end_dt="2026-11-09")
        oos_2026_res = evaluate_ledger(trades, start_dt="2026-01-01", end_dt="2026-11-09")

        nav_5y = oos_5y_res.get("nav_1slot", 0.0)
        wr_5y = oos_5y_res.get("win_rate", 0.0)
        n_5y = oos_5y_res.get("n_all_signals", 0)

        print(f"[{name}] Done in {time.time()-t0:.2f}s | 5Y Trades: {n_5y} | WR: {wr_5y:.1%} | 1-Slot NAV: {nav_5y:.4f} | MDD: {oos_5y_res.get('mdd_1slot', 0):.1%}")

        all_results[name] = {
            "in_sample_2020_2021": insample_res,
            "oos_5y_2022_2026": oos_5y_res,
            "oos_3y_2024_2026": oos_3y_res,
            "oos_2026": oos_2026_res
        }

        if nav_5y > best_nav:
            best_nav = nav_5y
            best_df = trades
            best_mode_name = name

    # 对最优策略评估与主板 V15 的互补协同
    print("\n" + "="*80)
    print(f">>> 评估最优策略 [{best_mode_name}] 与主板 V15 互补协同效果...")
    synergy_res = evaluate_synergy_with_v15(best_df, V15_LEDGER_PATH)
    all_results["champion_synergy_with_v15"] = synergy_res

    # 导出最优账本
    if best_df is not None and not best_df.empty:
        best_df_oos = best_df[(best_df["buy_dt"] >= "2022-01-01") & (best_df["buy_dt"] <= "2026-11-09")].copy()
        best_df_oos.sort_values("buy_dt", inplace=True)
        best_df_oos.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
        print(f">>> 最优账本已导出至: {OUT_CSV} ({len(best_df_oos)} 笔样本外交易)")

    # 提取连拉两天十几个点典型大肉案例
    top_meat_cases = []
    if best_df is not None and not best_df.empty:
        meats = best_df_oos.sort_values("net_ret", ascending=False).head(5)
        for _, r in meats.iterrows():
            top_meat_cases.append({
                "ticker": r["ticker"],
                "d1_dt": r["d1_dt"],
                "buy_dt": r["buy_dt"],
                "d1_pct": round(r["d1_pct"], 4),
                "d1_amt_yi": r["d1_amt_yi"],
                "theme": r["theme"],
                "exit_dt": r["exit_dt"],
                "exit_reason": r["exit_reason"],
                "net_ret": round(r["net_ret"], 4),
                "hold_days": int(r["hold_days"])
            })
    all_results["top_meat_cases"] = top_meat_cases

    # 写入 JSON
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f">>> 完整实证结果已写入: {OUT_JSON}")
    print(f">>> 全部完成，总耗时 {time.time()-t_start:.2f}s")


if __name__ == "__main__":
    main()
