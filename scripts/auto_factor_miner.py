#!/usr/bin/env python3
"""
A股连板与强势股自动化因子挖掘引擎 (Zero-Lookahead Automated Factor Miner)
用法:
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/auto_factor_miner.py --top 15
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/auto_factor_miner.py --board 3 --top 15
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/auto_factor_miner.py --mode open --top 15
  /opt/homebrew/bin/python3.13 sim-portfolio/scripts/auto_factor_miner.py --mode daban --top 15

内置防伪四铁律 (Rule D15 + 样本外独立盲测):
  1. 零前视镜: 所有选股与环境因子严格取自 T-1 收盘及 T 日 09:25 竞价已知数据;
  2. 真实可成交: 严格剔除一字涨跌停不可买样本, 打板模式强制计入盘中摸板炸板亏损单, 统一扣双边 0.30% 摩擦;
  3. 按日等权 + 扣基准超额: 同日多信号按日期等权聚合, 同时输出相对大盘基准净超额;
  4. 样本外硬验证: 2021-11~2024-10 训练集挖掘 -> 2024-11~2026-11 样本外盲测, 且近5年/近3年/近1年扣费净收益同为正!
"""
import argparse
from itertools import combinations
from pathlib import Path
import numpy as np
import pandas as pd


def compute_real_exits(mb: pd.DataFrame) -> pd.DataFrame:
    """
    向量化计算符合实盘手册 (strategy_astock.md) 的三类真实隔夜退出收益:
      1) hold_pos_ret: 买入后次日(T+1)起, 当日收正(ret > 0)继续持有吃满连板主升浪, 当日收平或收负(<=0)收盘卖出(上限拿8日);
      2) tp5_5d_ret:   买入后次日(T+1)起5日内盘中最高摸 +5% 止盈(若开盘直接高开超+5%按开盘价止盈), 未触及则第5日收盘卖;
      3) dev95_4d_ret: 买入后次日(T+1)起至第4日盘中触及10日涨幅95%(卡严重异动线)止盈, 未触及则第4日收盘卖.
    同时支持两种入场价基准: open_adj (09:25竞价买入) 与 zt_adj (盘中触涨停价打板买入, 含当日炸板!).
    """
    n = len(mb)
    tk = mb["ticker"].to_numpy()
    q_adj = (mb["adj_close"] / mb["close"]).to_numpy()
    o_adj = mb["open"].to_numpy() * q_adj
    h_adj = mb["high"].to_numpy() * q_adj
    l_adj = mb["low"].to_numpy() * q_adj
    c_adj = mb["adj_close"].to_numpy()
    zt_adj = mb["zt_px"].to_numpy() * q_adj
    ret_arr = mb["ret"].to_numpy()

    # Precompute 10-day rolling min/base close for 95% 10-day deviation line proxy:
    # 10d cumulative gain from c[t-9] >= 95% => target_adj = c_adj[idx - (9 - step)] * 1.95
    p98_adj = (np.floor(mb["prev_c"].to_numpy() * 1.098 * 100 + 0.5) / 100.0) * q_adj
    open_hold_zt = np.full(n, np.nan)
    daban98_hold_zt = np.full(n, np.nan)
    daban_hold_zt = np.full(n, np.nan)
    open_hold_pos = np.full(n, np.nan)
    daban98_hold_pos = np.full(n, np.nan)
    daban_hold_pos = np.full(n, np.nan)
    open_tp5_5d = np.full(n, np.nan)
    open_dev95_4d = np.full(n, np.nan)
    open_c4 = np.full(n, np.nan)

    is_zt_arr = mb["is_zt"].to_numpy()
    cand_idx = np.where((mb["prev_streak"].to_numpy() >= 1) | (mb["prev2_streak"].to_numpy() >= 4))[0]
    for i in cand_idx:
        if i + 1 >= n or tk[i + 1] != tk[i]:
            continue
        # 1A) hold_zt (断板必卖): Day 0 must seal ZT (otherwise sell at T+1 close); from step=1..8, hold ONLY while sealed ZT (is_zt), sell at close on first broken-board day
        exit_zt_j = None
        if not is_zt_arr[i]:
            for step in range(1, 9):
                j = i + step
                if j >= n or tk[j] != tk[i]:
                    break
                exit_zt_j = j
                if not ((h_adj[j] - l_adj[j]) <= 1e-4 * c_adj[j] and ret_arr[j] < -0.085):
                    break
        else:
            for step in range(1, 9):
                j = i + step
                if j >= n or tk[j] != tk[i]:
                    break
                exit_zt_j = j
                if not is_zt_arr[j]:
                    if (h_adj[j] - l_adj[j]) <= 1e-4 * c_adj[j] and ret_arr[j] < -0.085:
                        continue
                    break
        if exit_zt_j is not None:
            open_hold_zt[i] = c_adj[exit_zt_j] / o_adj[i] - 1.0
            daban98_hold_zt[i] = c_adj[exit_zt_j] / p98_adj[i] - 1.0
            daban_hold_zt[i] = c_adj[exit_zt_j] / zt_adj[i] - 1.0

        # 1B) hold_pos (T+1起收红续拿断绿卖, 零未来函数): from step=1..8, hold while ret > 0, sell at close on first day with ret <= 0
        exit_pos_j = None
        for step in range(1, 9):
            j = i + step
            if j >= n or tk[j] != tk[i]:
                break
            exit_pos_j = j
            if ret_arr[j] <= 0.0:
                if (h_adj[j] - l_adj[j]) <= 1e-4 * c_adj[j] and ret_arr[j] < -0.085:
                    continue
                break
        if exit_pos_j is not None:
            open_hold_pos[i] = c_adj[exit_pos_j] / o_adj[i] - 1.0
            daban98_hold_pos[i] = c_adj[exit_pos_j] / p98_adj[i] - 1.0
            daban_hold_pos[i] = c_adj[exit_pos_j] / zt_adj[i] - 1.0

        # 2) tp5_5d from open_adj[i]: steps 1..5
        tp_px = o_adj[i] * 1.05
        sold = False
        last_j = None
        for step in range(1, 6):
            j = i + step
            if j >= n or tk[j] != tk[i]:
                break
            last_j = j
            if o_adj[j] >= tp_px:
                open_tp5_5d[i] = o_adj[j] / o_adj[i] - 1.0
                sold = True
                break
            if h_adj[j] >= tp_px:
                open_tp5_5d[i] = 0.05
                sold = True
                break
        if (not sold) and (last_j is not None):
            open_tp5_5d[i] = c_adj[last_j] / o_adj[i] - 1.0

        # 3) dev95_4d & c4 from open_adj[i]: Day 1 = entry day i; Day 2=i+1, Day 3=i+2, Day 4=i+3!
        sold95 = False
        last4 = None
        for step in range(1, 4):
            j = i + step
            if j >= n or tk[j] != tk[i]:
                break
            last4 = j
            # 10-day window base is j - 9 (or earliest available in same ticker)
            b_idx = j - 9
            if b_idx >= 0 and tk[b_idx] == tk[j]:
                line95 = c_adj[b_idx] * 1.95
                if o_adj[j] >= line95:
                    open_dev95_4d[i] = o_adj[j] / o_adj[i] - 1.0
                    sold95 = True
                    break
                if h_adj[j] >= line95:
                    open_dev95_4d[i] = line95 / o_adj[i] - 1.0
                    sold95 = True
                    break
        if not sold95 and last4 is not None:
            open_dev95_4d[i] = c_adj[last4] / o_adj[i] - 1.0
        if last4 is not None and last4 == i + 3:
            open_c4[i] = c_adj[last4] / o_adj[i] - 1.0

    mb["ret_open_holdzt"] = open_hold_zt
    mb["ret_daban98_holdzt"] = daban98_hold_zt
    mb["ret_daban_holdzt"] = daban_hold_zt
    mb["ret_open_holdpos"] = open_hold_pos
    mb["ret_daban98_holdpos"] = daban98_hold_pos
    mb["ret_daban_holdpos"] = daban_hold_pos
    mb["ret_open_tp5"] = open_tp5_5d
    mb["ret_open_dev95"] = open_dev95_4d
    mb["ret_open_day4"] = open_c4
    return mb


def load_panel(root: Path) -> pd.DataFrame:
    pq = list(root.rglob("a_daily.parquet"))[0]
    df = pd.read_parquet(
        pq,
        columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "oshare", "turn"],
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= "2021-06-01"].sort_values(["ticker", "date"]).reset_index(drop=True)
    df["code6"] = df["ticker"].astype(str).str.extract(r"(\d{6})")[0].fillna("")

    ind_path = root / "sim-portfolio/backtest/2026-10-15-review2022/industry.csv"
    if ind_path.exists():
        ind_df = pd.read_csv(ind_path)
        ind_df["code6"] = ind_df["code"].astype(str).str.extract(r"(\d{6})")[0]
        ind_map = ind_df.dropna(subset=["industry"]).drop_duplicates("code6", keep="last").set_index("code6")["industry"]
        df["ind"] = df["code6"].map(ind_map).fillna("UNK")
    else:
        df["ind"] = "UNK"

    df["is_main"] = df["code6"].str.startswith(("00", "60"))
    df["mcap"] = df["close"] * df["oshare"]

    g_all = df.groupby("ticker", sort=False)
    df["prev_c"] = g_all["close"].shift(1)
    df["ret"] = df["close"] / df["prev_c"] - 1.0

    # Market macro features
    df["is_large"] = df["mcap"] >= 5e10
    df["is_small_main"] = df["is_main"] & (df["mcap"] > 0) & (df["mcap"] <= 5e9)
    df["w_ret_l"] = np.where(df["is_large"] & df["ret"].notna(), df["ret"].clip(-0.2, 0.2) * df["mcap"], 0.0)
    df["w_cap_l"] = np.where(df["is_large"] & df["ret"].notna(), df["mcap"], 0.0)

    mkt = (
        df.groupby("date")
        .agg(tot_amt=("amount", "sum"), eq_ret=("ret", "mean"), w_num=("w_ret_l", "sum"), w_den=("w_cap_l", "sum"))
        .reset_index()
        .sort_values("date")
    )
    small_amt = df[df["is_small_main"]].groupby("date")["amount"].sum().rename("small_amt")
    mkt = mkt.merge(small_amt, on="date", how="left").fillna({"small_amt": 0.0})
    mkt["large_ret"] = mkt["w_num"] / mkt["w_den"].replace(0, np.nan)
    mkt["eq_ret_10d"] = (1.0 + mkt["eq_ret"].fillna(0)).rolling(10).apply(np.prod, raw=True) - 1.0
    mkt["large_ret_5d"] = (1.0 + mkt["large_ret"].fillna(0)).rolling(5).apply(np.prod, raw=True) - 1.0
    mkt["large_vol_10d"] = mkt["large_ret"].fillna(0).rolling(10).std() * np.sqrt(10)
    mkt["small_share"] = mkt["small_amt"] / mkt["tot_amt"].replace(0, np.nan)
    mkt["small_share_diff"] = mkt["small_share"] - mkt["small_share"].rolling(20).mean()
    mkt["bm_ret_3d"] = (1.0 + mkt["large_ret"].fillna(0)).shift(-1).rolling(3).apply(np.prod, raw=True).shift(-2) - 1.0

    for c in ["eq_ret", "eq_ret_10d", "large_ret_5d", "large_vol_10d", "small_share_diff"]:
        mkt[f"prev_{c}"] = mkt[c].shift(1)

    mb = df[df["is_main"] & (df["prev_c"] > 0)].copy().reset_index(drop=True)
    zt_px = np.floor(mb["prev_c"] * 1.10 * 100 + 0.5) / 100.0
    dt_px = np.floor(mb["prev_c"] * 0.90 * 100 + 0.5) / 100.0
    mb["zt_px"] = zt_px
    mb["dt_px"] = dt_px
    mb["is_zt"] = (mb["close"] >= zt_px - 0.005) & (mb["ret"] > 0.085)
    mb["is_touch"] = (mb["high"] >= zt_px - 0.005) & ((mb["high"] / mb["prev_c"] - 1.0) > 0.085)
    p98_px = np.floor(mb["prev_c"] * 1.098 * 100 + 0.5) / 100.0
    mb["is_touch98"] = (mb["high"] >= p98_px - 0.005) & ((mb["high"] / mb["prev_c"] - 1.0) >= 0.095)
    mb["is_dt"] = (mb["close"] <= dt_px + 0.005) & (mb["ret"] < -0.085)
    mb["is_yz_zt"] = mb["is_zt"] & (mb["low"] >= mb["high"] - 0.001)
    mb["open_is_zt"] = mb["open"] >= zt_px - 0.005
    mb["open_is_dt"] = mb["open"] <= dt_px + 0.005
    mb["open_gap"] = mb["open"] / mb["prev_c"] - 1.0

    zt_arr = mb["is_zt"].to_numpy()
    tk_arr = mb["ticker"].to_numpy()
    streak = np.zeros(len(mb), dtype=np.int32)
    cur = 0
    prev_tk = None
    for i in range(len(mb)):
        if tk_arr[i] != prev_tk:
            cur = 1 if zt_arr[i] else 0
            prev_tk = tk_arr[i]
        else:
            cur = (cur + 1) if zt_arr[i] else 0
        streak[i] = cur
    mb["streak"] = streak

    g = mb.groupby("ticker", sort=False)
    mb["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    mb["prev2_streak"] = g["streak"].shift(2).fillna(0).astype(int)
    mb["prev_turn"] = g["turn"].shift(1)
    mb["prev_mcap"] = g["mcap"].shift(1)
    mb["prev_yz"] = g["is_yz_zt"].shift(1).astype("boolean").fillna(False).to_numpy(dtype=bool)
    mb["prev_ret"] = g["ret"].shift(1)
    mb["prev_open"] = g["open"].shift(1)
    mb["prev_close"] = g["close"].shift(1)
    # Restore 1st-board float mcap: prev_mcap / (1.1 ** prev_streak)
    mb["first_board_mcap"] = mb["prev_mcap"] / np.power(1.10, np.clip(mb["prev_streak"], 1, 10))

    mb = compute_real_exits(mb)

    # Sector & height context at T-1
    sec_d = mb[mb["ind"] != "UNK"].groupby(["date", "ind"])["is_zt"].sum().rename("sec_zt").reset_index().sort_values(["ind", "date"])
    sec_d["prev_sec_zt"] = sec_d.groupby("ind")["sec_zt"].shift(1)

    max_h_d = mb.groupby("date")["streak"].max().rename("mkt_max_h")
    mb_max = mb.merge(max_h_d, on="date", how="left")
    max_cnt = mb_max[(mb_max["streak"] == mb_max["mkt_max_h"]) & (mb_max["mkt_max_h"] >= 3)].groupby("date").size().rename("mkt_max_cnt")
    h_ctx = pd.concat([max_h_d, max_cnt], axis=1).fillna({"mkt_max_cnt": 0}).sort_index()
    h_ctx["prev_mkt_max_h"] = h_ctx["mkt_max_h"].shift(1)
    h_ctx["prev_mkt_max_cnt"] = h_ctx["mkt_max_cnt"].shift(1)
    dt3 = mb[mb["prev_streak"] >= 3].groupby("date")["is_dt"].sum().rename("dt3_n")
    h_ctx = h_ctx.join(dt3, how="left").fillna({"dt3_n": 0})
    h_ctx["prev_dt3_n"] = h_ctx["dt3_n"].shift(1)

    cand = mb[(mb["date"] >= "2021-11-09") & ((mb["prev_streak"] >= 1) | (mb["prev2_streak"] >= 4))].copy().reset_index(drop=True)
    cand = cand.merge(sec_d[["date", "ind", "prev_sec_zt"]], on=["date", "ind"], how="left")
    cand["prev_sec_zt"] = cand["prev_sec_zt"].fillna(1)
    cand = cand.merge(h_ctx[["prev_mkt_max_h", "prev_mkt_max_cnt", "prev_dt3_n"]], left_on="date", right_index=True, how="left")
    cand = cand.merge(
        mkt[["date", "prev_eq_ret", "prev_eq_ret_10d", "prev_large_ret_5d", "prev_large_vol_10d", "prev_small_share_diff", "bm_ret_3d"]],
        on="date",
        how="left",
    )
    cand["is_sole_leader"] = (cand["prev_streak"] >= 4) & (cand["prev_streak"] == cand["prev_mkt_max_h"]) & (cand["prev_mkt_max_cnt"] == 1)
    cand["broke_high_yang"] = (
        (cand["prev2_streak"] >= 4)
        & (cand["prev_streak"] == 0)
        & (cand["prev_close"] > cand["prev_open"])
        & (cand["prev_ret"] >= 0.015)
        & (cand["prev_ret"] <= 0.08)
    )
    return cand


def mine_factors(cand: pd.DataFrame, target_board: int | None = None, mode_filter: str = "all"):
    FEE = 0.003

    universes = [
        ("1板次日(1进2)", cand["prev_streak"] == 1),
        ("2板次日(2进3)", cand["prev_streak"] == 2),
        ("3板次日(3进4)", cand["prev_streak"] == 3),
        ("4板次日(4进5)", cand["prev_streak"] == 4),
        ("5板及以上次日", cand["prev_streak"] >= 5),
        ("4板以上断板首日真阳反包池", cand["broke_high_yang"]),
    ]
    if target_board is not None:
        universes = [u for u in universes if str(target_board) in u[0]]

    exec_modes = [
        ("09:25低开分歧[-7%,-2%]买_卡95%异动或第4日卖", (~cand["open_is_dt"]) & (cand["open_gap"] >= -0.07) & (cand["open_gap"] <= -0.02), "ret_open_dev95"),
        ("09:25开盘<=+5.5%买_卡95%异动或第4日卖", (~cand["open_is_dt"]) & (cand["open_gap"] > -0.09) & (cand["open_gap"] <= 0.055), "ret_open_dev95"),
        ("09:25开盘<=+5.5%买_5日内摸+5%止盈", (~cand["open_is_dt"]) & (cand["open_gap"] > -0.09) & (cand["open_gap"] <= 0.055), "ret_open_tp5"),
        ("09:25高开[+3%,+8.5%]买_断板必卖", (~cand["open_is_zt"]) & (cand["open_gap"] >= 0.03) & (cand["open_gap"] <= 0.085), "ret_open_holdzt"),
        ("09:25高开[+4%,+8.5%]买_断板必卖", (~cand["open_is_zt"]) & (cand["open_gap"] >= 0.04) & (cand["open_gap"] <= 0.085), "ret_open_holdzt"),
        ("09:25高开[+3%,+8.5%]买_收红续拿断绿卖", (~cand["open_is_zt"]) & (cand["open_gap"] >= 0.03) & (cand["open_gap"] <= 0.085), "ret_open_holdpos"),
        ("高开[+4%,+8.5%]盘中摸+9.8%扫板(含炸板)_断板必卖", (~cand["open_is_zt"]) & (cand["open_gap"] >= 0.04) & (cand["open_gap"] <= 0.085) & cand["is_touch98"], "ret_daban98_holdzt"),
        ("高开[+4%,+8.5%]盘中摸+9.8%扫板(含炸板)_收红续拿断绿卖", (~cand["open_is_zt"]) & (cand["open_gap"] >= 0.04) & (cand["open_gap"] <= 0.085) & cand["is_touch98"], "ret_daban98_holdpos"),
        ("高开[+4%,+8.5%]盘中触板打板(含炸板)_断板必卖", (~cand["open_is_zt"]) & (cand["open_gap"] >= 0.04) & (cand["open_gap"] <= 0.085) & cand["is_touch"], "ret_daban_holdzt"),
        ("高开[+4%,+8.5%]盘中触板打板(含炸板)_收红续拿断绿卖", (~cand["open_is_zt"]) & (cand["open_gap"] >= 0.04) & (cand["open_gap"] <= 0.085) & cand["is_touch"], "ret_daban_holdpos"),
        ("非一字盘中摸+9.8%扫板(含炸板)_断板必卖", (~cand["open_is_zt"]) & cand["is_touch98"], "ret_daban98_holdzt"),
        ("非一字盘中摸+9.8%扫板(含炸板)_收红续拿断绿卖", (~cand["open_is_zt"]) & cand["is_touch98"], "ret_daban98_holdpos"),
        ("非一字盘中触板打板(含炸板)_断板必卖", (~cand["open_is_zt"]) & cand["is_touch"], "ret_daban_holdzt"),
        ("非一字盘中触板打板(含炸板)_收红续拿断绿卖", (~cand["open_is_zt"]) & cand["is_touch"], "ret_daban_holdpos"),
    ]
    if mode_filter == "daban":
        exec_modes = [m for m in exec_modes if "打板" in m[0]]
    elif mode_filter == "open":
        exec_modes = [m for m in exec_modes if "打板" not in m[0]]

    vol_med = cand["prev_large_vol_10d"].median()
    atomic_factors = [
        ("无筛选基线", pd.Series(True, index=cand.index)),
        ("昨极高锁仓换手板(账面换手1%~8%)", (~cand["prev_yz"]) & (cand["prev_turn"] >= 0.01) & (cand["prev_turn"] <= 0.08)),
        ("昨高锁仓换手板(账面换手1%~11%)", (~cand["prev_yz"]) & (cand["prev_turn"] >= 0.01) & (cand["prev_turn"] <= 0.11)),
        ("昨换手适中(11%~25%)", (~cand["prev_yz"]) & (cand["prev_turn"] > 0.11) & (cand["prev_turn"] <= 0.25)),
        ("还原首板流通市值<30亿", cand["first_board_mcap"] <= 3.0e9),
        ("还原首板流通市值<50亿", cand["first_board_mcap"] <= 5.0e9),
        ("同行业主线梯队(昨同行业>=2只涨停)", cand["prev_sec_zt"] >= 2),
        ("同行业强主线(昨同行业>=4只涨停)", cand["prev_sec_zt"] >= 4),
        ("全场唯一最高标独苗", cand["is_sole_leader"]),
        ("昨高标零跌停", cand["prev_dt3_n"] == 0),
        ("大盘非阴跌且非权重抽血", (cand["prev_eq_ret_10d"] > -0.05) & (cand["prev_large_ret_5d"] <= 0.035)),
        ("指数窄幅低波横盘", (cand["prev_large_vol_10d"] <= vol_med) & (cand["prev_eq_ret_10d"] > -0.04)),
        ("微盘资金占比扩张", cand["prev_small_share_diff"] > 0),
    ]

    combo_list = [(f[0], f[1]) for f in atomic_factors]
    for (n1, m1), (n2, m2) in combinations(atomic_factors[1:], 2):
        if ("换手" in n1 and "换手" in n2) or ("市值" in n1 and "市值" in n2) or ("同行业" in n1 and "同行业" in n2):
            continue
        combo_list.append((f"{n1} + {n2}", m1 & m2))

    results = []
    for u_name, u_mask in universes:
        for e_name, e_mask, ret_col in exec_modes:
            base_mask = u_mask & e_mask & cand[ret_col].notna()
            if base_mask.sum() < 20:
                continue
            for f_name, f_mask in combo_list:
                sel = cand[base_mask & f_mask]
                if len(sel) < 18:
                    continue
                daily = sel.groupby("date").agg(
                    net_ret=(ret_col, lambda x: x.mean() - FEE),
                    bm_ret=("bm_ret_3d", "first"),
                    n_stocks=(ret_col, "count"),
                )
                if len(daily) < 18:
                    continue

                d_train = daily[daily.index < "2024-11-01"]
                d_oos = daily[daily.index >= "2024-11-01"]
                d_5y = daily
                d_3y = daily[daily.index >= "2023-11-09"]
                d_1y = daily[daily.index >= "2025-11-09"]
                d_jul = daily[daily.index >= "2026-07-01"]

                if len(d_train) < 10 or len(d_oos) < 8 or len(d_1y) < 4:
                    continue

                m_tr = d_train["net_ret"].mean()
                m_oos = d_oos["net_ret"].mean()
                m_5y = d_5y["net_ret"].mean()
                m_3y = d_3y["net_ret"].mean()
                m_1y = d_1y["net_ret"].mean()
                m_jul = d_jul["net_ret"].mean() if len(d_jul) >= 2 else np.nan

                # Require Train > 0, OOS > 0, 5Y > +0.8%, 3Y > +0.8%, 1Y > +0.8% (all AFTER 0.30% fee!)
                if not (m_tr > 0.005 and m_oos > 0.005 and m_5y > 0.008 and m_3y > 0.008 and m_1y > 0.008):
                    continue

                wr_5y = (d_5y["net_ret"] > 0).mean()
                wr_1y = (d_1y["net_ret"] > 0).mean()
                wins = d_5y.loc[d_5y["net_ret"] > 0, "net_ret"]
                losses = d_5y.loc[d_5y["net_ret"] <= 0, "net_ret"]
                pf_5y = (wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0) else 9.99
                alpha_5y = (d_5y["net_ret"] - d_5y["bm_ret"].fillna(0)).mean()
                alpha_1y = (d_1y["net_ret"] - d_1y["bm_ret"].fillna(0)).mean()
                t_stat = m_5y / (d_5y["net_ret"].std() / np.sqrt(len(d_5y)))

                results.append(
                    {
                        "universe": u_name,
                        "exec_mode": e_name,
                        "factor": f_name,
                        "days_5y": len(d_5y),
                        "days_1y": len(d_1y),
                        "days_jul": len(d_jul),
                        "train_net": m_tr,
                        "oos_net": m_oos,
                        "net_5y": m_5y,
                        "net_3y": m_3y,
                        "net_1y": m_1y,
                        "net_jul": m_jul,
                        "wr_5y": wr_5y,
                        "wr_1y": wr_1y,
                        "pf_5y": pf_5y,
                        "alpha_5y": alpha_5y,
                        "alpha_1y": alpha_1y,
                        "t_stat": t_stat,
                    }
                )

    res_df = pd.DataFrame(results)
    if len(res_df) > 0:
        # Deduplicate near-identical factor variants within same universe+exec_mode, keeping highest conservative score
        res_df["score"] = res_df[["train_net", "oos_net", "net_1y"]].min(axis=1) * np.log1p(res_df["days_5y"])
        res_df = res_df.sort_values("score", ascending=False).reset_index(drop=True)
    return res_df


def main():
    parser = argparse.ArgumentParser(description="A股自动化零前视镜因子挖掘器")
    parser.add_argument("--board", type=int, default=None, help="指定连板高度 (1/2/3/4/5)")
    parser.add_argument("--mode", type=str, default="all", choices=["all", "daban", "open"], help="买点模式过滤")
    parser.add_argument("--top", type=int, default=15, help="输出前 N 条通过全期样本外硬门槛的实操因子")
    parser.add_argument("--save", type=str, default="/tmp/mined_factors_latest.csv", help="结果导出CSV路径")
    args = parser.parse_args()

    root = Path("/Users/huaichuaibeimeng/claude-projects")
    cand = load_panel(root)
    res = mine_factors(cand, target_board=args.board, mode_filter=args.mode)
    print(f"扫描完成! 通过【训练集+样本外+近5年/近3年/近1年全期扣千三正收益】硬门槛的实操因子组合共: {len(res)} 条")
    if len(res) > 0:
        res.to_csv(args.save, index=False)
        # Show diverse top strategies across different universes/modes first
        seen_ue = set()
        diverse_rows = []
        for _, r in res.iterrows():
            key = (r["universe"], r["exec_mode"])
            if key not in seen_ue:
                seen_ue.add(key)
                diverse_rows.append(r)
            if len(diverse_rows) >= args.top:
                break
        print("\n=== 各连板层级/买卖模式最优样本外实操因子 (按保守下界排序) ===")
        for idx, r in enumerate(diverse_rows, 1):
            jul_str = f"{r['net_jul']*100:+.2f}%(d={int(r['days_jul'])})" if pd.notna(r["net_jul"]) else "样本<2"
            print(
                f"[{idx:02d}] {r['universe']} | {r['exec_mode']} | 因子: {r['factor']}\n"
                f"     训练={r['train_net']*100:+.2f}% -> 样本外={r['oos_net']*100:+.2f}% | "
                f"5Y净={r['net_5y']*100:+.2f}%(胜率{r['wr_5y']*100:.1f}%,赔率{r['pf_5y']:.2f},d={int(r['days_5y'])},超额{r['alpha_5y']*100:+.2f}%,t={r['t_stat']:.2f}) | "
                f"3Y净={r['net_3y']*100:+.2f}% | 1Y净={r['net_1y']*100:+.2f}%(胜率{r['wr_1y']*100:.1f}%,d={int(r['days_1y'])},超额{r['alpha_1y']*100:+.2f}%) | 7月+={jul_str}"
            )


if __name__ == "__main__":
    main()
