#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V3.0 National Team Rescue & Institutional Hedge 5-Dimension Pure-Integer Scorecard Calibration.
Period: 2021-01-04 ~ 2026-11-24 (1,427 trading days, IS=2021~2023, OOS=2024~2026) + 2017~2026 10Y robustness check.
Strict PIT: features observed on day T (Live Intraday vs Settled EOD), entry at T+1 open -> T+5 / T+20 close.
Strictly NO yfinance (D12 compliant). Zero cap10m metrics.
Output: output/csrc_policy_100factors_20261114/national_team/v3_scorecard_backtest_audit.json
"""
import os, sys, json, warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team"
CACHE_DIR = os.path.join(NT_DIR, "v3_cache")
AUDIT_OUT = os.path.join(NT_DIR, "v3_scorecard_backtest_audit.json")

CORE10 = {"510300", "510310", "510330", "159919", "510050", "510500", "512100", "159915", "588000", "588080"}
T1_CORE = {"510300", "510310", "510330", "159919", "510050"}
T2_CORE = {"510500", "512100", "159915", "588000", "588080"}
SEC9 = {"512000", "512880", "512480", "512010", "512690", "515030", "515790", "510880", "512800"}

NT16 = [
    "601398.SH","601288.SH","601988.SH","601939.SH","600036.SH",
    "601857.SH","600028.SH","600941.SH","601088.SH","600900.SH",
    "601318.SH","601628.SH","600519.SH","600030.SH",
    "300750.SZ","688981.SH",
]
BIG4_OIL = ["601398.SH","601288.SH","601988.SH","601939.SH","601857.SH","600028.SH"]
SQUADS = {
    "bank": ["601398.SH","601288.SH","601988.SH","601939.SH","600036.SH"],
    "energy": ["601857.SH","600028.SH","600941.SH","601088.SH","600900.SH"],
    "fincons": ["601318.SH","601628.SH","600519.SH","600030.SH"],
    "growth": ["300750.SZ","688981.SH"],
}
FUND8 = ["300750.SZ","300308.SZ","300274.SZ","688256.SH","300059.SZ","002475.SZ","603259.SH","000858.SZ"]

COST_ROUND_TRIP = 0.0030  # 0.15% one-way -> 0.30% round-trip


# ==============================================================================
# V3.0 PURE INTEGER SCORING RULES (0-100, BASE=20)
# ==============================================================================
V3_SCORECARD_SPEC = {
    "base_score": 20,
    "range": [0, 100],
    "tiers": [
        {"tier": "<40", "label": "无救市/观望", "min": 0, "max": 39},
        {"tier": "40~59", "label": "脉冲维稳", "min": 40, "max": 59},
        {"tier": "60~74", "label": "准救市试探", "min": 60, "max": 74},
        {"tier": ">=75", "label": "真底重手救市", "min": 75, "max": 100},
    ],
    "rules": {
        "D1_宽基ETF主战池(10核心+22全池)": [
            {"id": "D1_amt_spike_ge20", "mode": "both", "pts_live": 16, "pts_eod": 12, "desc": "10核心/22全池成交量比>=2.0x"},
            {"id": "D1_amt_spike_15_20", "mode": "both", "pts_live": 10, "pts_eod": 7, "desc": "10核心/22全池成交量比1.5x~2.0x"},
            {"id": "D1_amt_spike_12_pulse", "mode": "both", "pts_live": 4, "pts_eod": 3, "desc": "量比1.2x~1.5x叠加300下影/拉起>=0.8%"},
            {"id": "D1_pullup_confirm", "mode": "both", "pts_live": 4, "pts_eod": 3, "desc": "放量>=1.5x叠加沪深300自低点拉起>=0.8%"},
            {"id": "D1_live_t1t2_sync", "mode": "live", "pts_live": 8, "pts_eod": 0, "desc": "盘中一队>=2只且二队>=2只同步放量>=1.6x(或5m同窗共振)"},
            {"id": "D1_live_broad5", "mode": "live", "pts_live": 6, "pts_eod": 0, "desc": "10核心ETF>=5只放量>=1.6x"},
            {"id": "D1_live_t1_skew", "mode": "live", "pts_live": -4, "pts_eod": 0, "desc": "一队>=2只放量但二队0只(抽血小盘预警)"},
            {"id": "D1_live_lag5d_inflow", "mode": "live", "pts_live": 4, "pts_eod": 0, "desc": "截至昨日5日纯净累计净申购>=150亿"},
            {"id": "D1_eod_wflow_heavy", "mode": "eod", "pts_live": 0, "pts_eod": 12, "desc": "盘后官宣单日纯净净申购>=90亿或占AUM>=1.5%"},
            {"id": "D1_eod_wflow_mid", "mode": "eod", "pts_live": 0, "pts_eod": 7, "desc": "盘后官宣单日纯净净申购40~90亿或占AUM>=0.7%"},
            {"id": "D1_eod_wflow_5d", "mode": "eod", "pts_live": 0, "pts_eod": 4, "desc": "盘后近5日纯净累计净申购>=150亿"},
            {"id": "D1_eod_F152_sync", "mode": "eod", "pts_live": 0, "pts_eod": 6, "desc": "F152一二队共振(一队>=50亿且二队>=25亿)"},
            {"id": "D1_eod_F151_skew", "mode": "eod", "pts_live": 0, "pts_eod": -5, "desc": "F151一队偏心(一队>=75亿且二队<15亿)"},
        ],
        "D2_16核心权重个股(4大方阵)": [
            {"id": "D2_hw_sync_4", "mode": "both", "pts_live": 10, "pts_eod": 10, "desc": "16只国家队权重>=4只放量止跌/拉升+宽基ETF>=1.5x"},
            {"id": "D2_hw_sync_8_sq3", "mode": "both", "pts_live": 4, "pts_eod": 4, "desc": "同步权重>=8只且横跨>=3大方阵(额外加分)"},
            {"id": "D2_fake_support", "mode": "both", "pts_live": -10, "pts_eod": -10, "desc": "假护盘抽血(银行石油-中证1000>=2.0%或>=0.8%且千跌<=-0.8%, ETF<1.3x)"},
        ],
        "D3_股指期货期现联动(IF/IH/IC/IM)": [
            {"id": "D3_rd019_trap", "mode": "both", "pts_live": -10, "pts_eod": -10, "desc": "RD019期现双爆量恐慌陷阱(ETF>=1.8x且IF0>=1.5x非交割日)"},
            {"id": "D3_clean_spot", "mode": "both", "pts_live": 6, "pts_eod": 6, "desc": "纯净现货护盘(ETF>=1.8x且IF0<1.5x非交割日)"},
            {"id": "D3_deep_discount", "mode": "both", "pts_live": 5, "pts_eod": 5, "desc": "现货放量>=1.5x叠加IF0深贴水<=-0.5%"},
            {"id": "D3_basis_narrow", "mode": "both", "pts_live": 3, "pts_eod": 3, "desc": "现货放量>=1.5x且贴水状态下基差单日走强>=+0.25%"},
            {"id": "D3_basis_premium_warn", "mode": "both", "pts_live": -5, "pts_eod": -5, "desc": "弱势下IF0升水/零贴水(>=0%)或任何状态下升水>=+0.3%"},
        ],
        "D4_机构与市场赎回对冲压力": [
            {"id": "D4_fund8_dump", "mode": "both", "pts_live": -6, "pts_eod": -6, "desc": "公募8大重仓>=3只日内放量砸盘(oc<=-2%/14点后<=-1.5%, 量>=1.2x)"},
            {"id": "D4_iopv_disc", "mode": "live_only", "pts_live": -5, "pts_eod": 0, "desc": "实盘14只ETF深折价(<=-0.25%)>=3家(盘中实盘专属扣分)"},
            {"id": "D4_live_lag_inst_out", "mode": "live", "pts_live": -4, "pts_eod": 0, "desc": "截至昨日上交所9行业ETF 5日<=-35亿或龙虎榜机构5日<=-40亿"},
            {"id": "D4_eod_sec9_out", "mode": "eod", "pts_live": 0, "pts_eod": -4, "desc": "盘后上交所9行业ETF 5日净赎回<=-35亿"},
            {"id": "D4_eod_lhb_out", "mode": "eod", "pts_live": 0, "pts_eod": -4, "desc": "盘后龙虎榜机构专用5日净卖出<=-40亿"},
            {"id": "D4_eod_F154_exit", "mode": "eod", "pts_live": 0, "pts_eod": -12, "desc": "F154单日纯净净赎回<=-80亿"},
            {"id": "D4_eod_F153_stop", "mode": "eod", "pts_live": 0, "pts_eod": -5, "desc": "F153连买>=3日且5日>=220亿后转净流出(未达-80亿)"},
            {"id": "D4_eod_F156_wave", "mode": "eod", "pts_live": 0, "pts_eod": -8, "desc": "F156近5日纯净累计净赎回<=-250亿"},
        ],
        "D5_弱势背景与官方政策表态": [
            {"id": "D5_weak_ma20", "mode": "both", "pts_live": 6, "pts_eod": 6, "desc": "弱势护盘背景(沪深300<MA20或60日回撤<=-6%)"},
            {"id": "D5_deep_dd60", "mode": "both", "pts_live": 4, "pts_eod": 4, "desc": "深跌加速区间(60日回撤<=-8%)"},
            {"id": "D5_high_overheat", "mode": "both", "pts_live": -18, "pts_eod": -18, "desc": "高位过热(MA20之上且20日涨>=5%, 放量非救市)"},
            {"id": "D5_extreme_bubble", "mode": "both", "pts_live": -6, "pts_eod": -6, "desc": "极度狂热(MA20之上且20日涨>=15%)"},
            {"id": "D5_official_nt_5d", "mode": "both", "pts_live": 12, "pts_eod": 12, "desc": "近5日汇金/国新/诚通/互换便利官宣增持或启动(严格PIT)"},
        ],
    }
}


def load_master_panel() -> pd.DataFrame:
    idx = pd.read_parquet(f"{CACHE_DIR}/indices_to_20261124.parquet")
    piv = {}
    for sym, pfx in [("sh000300", "c300"), ("sh000852", "c1000"), ("sh000016", "c50"), ("sh000905", "c500"), ("sh000688", "star50"), ("sz399006", "cyb")]:
        sub = idx[idx["symbol"] == sym].sort_values("date").copy()
        sub[f"{pfx}_prev_close"] = sub["close"].shift(1)
        sub[f"{pfx}_ret"] = sub["close"] / sub[f"{pfx}_prev_close"] - 1.0
        sub[f"{pfx}_oc"] = sub["close"] / sub["open"] - 1.0
        sub[f"{pfx}_pullup"] = (sub["close"] - sub["low"]) / sub[f"{pfx}_prev_close"]
        piv[pfx] = sub[["date", "open", "high", "low", "close", f"{pfx}_prev_close", f"{pfx}_ret", f"{pfx}_oc", f"{pfx}_pullup"]].rename(
            columns={"open": f"{pfx}_open", "high": f"{pfx}_high", "low": f"{pfx}_low", "close": f"{pfx}_close"}
        )

    p = piv["c300"].copy()
    for pfx in ["c1000", "c50", "c500", "star50", "cyb"]:
        p = p.merge(piv[pfx], on="date", how="left")
    p = p.sort_values("date").reset_index(drop=True)

    p["c300_ma20"] = p["c300_close"].rolling(20, min_periods=20).mean()
    p["c300_dd60"] = p["c300_close"] / p["c300_close"].rolling(60, min_periods=10).max() - 1.0
    p["c300_ret20"] = p["c300_close"] / p["c300_close"].shift(20) - 1.0

    for pfx in ["c300", "c1000"]:
        o = p[f"{pfx}_open"].to_numpy(float)
        c = p[f"{pfx}_close"].to_numpy(float)
        l = p[f"{pfx}_low"].to_numpy(float)
        n = len(p)
        for h in [5, 20]:
            fwd = np.full(n, np.nan)
            fwd[:n-h] = c[h:] / o[1:n-h+1] - 1.0
            p[f"{pfx}_open_fwd_{h}d"] = fwd
            fwd_t = np.full(n, np.nan)
            fwd_t[:n-h] = c[h:] / c[:n-h] - 1.0
            p[f"{pfx}_tail_fwd_{h}d"] = fwd_t
        mae = np.full(n, np.nan)
        for i in range(n - 20):
            mae[i] = np.min(l[i+1:i+21]) / o[i+1] - 1.0
        p[f"{pfx}_open_mae20"] = mae

    # Dim 1: 21 NT ETFs + 588000
    etf21 = pd.read_parquet(f"{CACHE_DIR}/etf21_to_20261124.parquet")
    etf_ex = pd.read_parquet(f"{CACHE_DIR}/etf_extra10_to_20261124.parquet")
    sh21 = pd.concat([
        pd.read_parquet(f"{NT_DIR}/sse_shares_cache.parquet"),
        pd.read_parquet(f"{NT_DIR}/szse_shares_cache.parquet"),
    ], ignore_index=True).drop_duplicates(["date", "code"])
    sh_ex = pd.read_parquet(f"{CACHE_DIR}/sse_extra10_shares.parquet")

    e588 = etf_ex[etf_ex["code"] == "588000"].copy()
    e588["exch"], e588["idx_grp"], e588["team"], e588["nt_w"] = "SSE", "STAR50", "T2", 0.25
    e588["close_qfq"], e588["split_ratio"] = e588["close"], 1.0
    etf22 = pd.concat([etf21[etf21["date"] >= "2016-01-01"], e588[etf21.columns]], ignore_index=True)
    sh22 = pd.concat([sh21, sh_ex[sh_ex["code"] == "588000"]], ignore_index=True).drop_duplicates(["date", "code"])
    etf22 = etf22.merge(sh22, on=["date", "code"], how="left").sort_values(["code", "date"]).reset_index(drop=True)

    etf22["prev_sh"] = etf22.groupby("code")["shares_wan"].shift(1)
    etf22["sh_ret"] = etf22["shares_wan"] / etf22["prev_sh"] - 1.0
    etf22["next_pct"] = etf22.groupby("code")["pct_chg"].shift(-1).fillna(0.0)
    etf22["prev_pct"] = etf22.groupby("code")["pct_chg"].shift(1).fillna(0.0)
    etf22["prev_sr"] = etf22.groupby("code")["split_ratio"].shift(1)
    etf22["next_sr"] = etf22.groupby("code")["split_ratio"].shift(-1)
    sr_jmp = ((etf22["split_ratio"] / etf22["prev_sr"] - 1.0).abs() > 0.08) | ((etf22["next_sr"] / etf22["split_ratio"] - 1.0).abs() > 0.08)
    px_jmp = (etf22["pct_chg"].abs() > 22) | (etf22["next_pct"].abs() > 22) | (etf22["prev_pct"].abs() > 22)
    explicit_splits = (
        ((etf22["code"] == "510310") & (etf22["date"].isin(["2024-09-20", "2024-09-23"]))) |
        ((etf22["code"] == "512100") & (etf22["date"].isin(["2022-09-02", "2022-09-05"]))) |
        ((etf22["code"] == "159845") & (etf22["date"].isin(["2022-08-01", "2022-08-02"]))) |
        ((etf22["code"] == "510230") & (etf22["date"].isin(["2020-08-14", "2020-08-17"]))) |
        ((etf22["code"] == "560010") & (etf22["date"].isin(["2022-09-13", "2022-09-14"]))) |
        ((etf22["code"] == "159922") & (etf22["date"].isin(["2024-11-29", "2024-12-02"]))) |
        ((etf22["code"] == "159919") & (etf22["date"].isin(["2019-01-11", "2019-01-14"]))) |
        ((etf22["code"] == "159901") & (etf22["date"].isin(["2021-04-09", "2021-04-12"]))) |
        ((etf22["code"] == "159629") & (etf22["date"].isin(["2022-11-11", "2022-11-14"]))) |
        ((etf22["code"] == "510100") & (etf22["date"].isin(["2025-03-07", "2025-03-10"])))
    )
    is_split = explicit_splits | (sr_jmp & (etf22["sh_ret"].abs() > 0.10)) | ((etf22["sh_ret"].abs() > 0.35) & px_jmp) | (etf22["pct_chg"].abs() > 25)
    etf22["net_flow_yi"] = np.where(is_split, 0.0, (etf22["shares_wan"] - etf22["prev_sh"]) * 1e4 * etf22["close"] / 1e8)
    etf22["nt_w_flow_yi"] = etf22["net_flow_yi"] * etf22["nt_w"].astype(float)
    etf22["aum_yi"] = etf22["shares_wan"] * 1e4 * etf22["close"] / 1e8
    etf22["amt_med20_s1"] = etf22.groupby("code")["amount"].transform(lambda s: s.rolling(20, min_periods=5).median().shift(1))
    etf22["ind_spike"] = etf22["amount"] / etf22["amt_med20_s1"].replace(0, np.nan)
    etf22["is_core10"] = etf22["code"].isin(CORE10)
    etf22["is_t1_core"] = etf22["code"].isin(T1_CORE)
    etf22["is_t2_core"] = etf22["code"].isin(T2_CORE)

    g = etf22.groupby("date")
    d_etf = pd.DataFrame({
        "etf22_amt_yi": g["amount"].sum() / 1e8,
        "etf22_flow_yi": g["net_flow_yi"].sum(),
        "etf22_wflow_yi": g["nt_w_flow_yi"].sum(),
        "etf22_aum_yi": g["aum_yi"].sum(),
        "etf22_n_sh": g["shares_wan"].apply(lambda s: int(s.notna().sum())),
    }).reset_index()

    t1_fl = etf22[etf22["team"] == "T1"].groupby("date")["net_flow_yi"].sum().rename("t1_flow_yi")
    t2_fl = etf22[etf22["team"] == "T2"].groupby("date")["net_flow_yi"].sum().rename("t2_flow_yi")
    c10 = etf22[etf22["is_core10"]].groupby("date").agg(
        core10_amt_yi=("amount", lambda s: s.sum() / 1e8),
        core10_t1_cnt16=("ind_spike", lambda s: int(((s >= 1.6) & (etf22.loc[s.index, "is_t1_core"])).sum())),
        core10_t2_cnt16=("ind_spike", lambda s: int(((s >= 1.6) & (etf22.loc[s.index, "is_t2_core"])).sum())),
    )
    d_etf = d_etf.merge(t1_fl, on="date", how="left").merge(t2_fl, on="date", how="left").merge(c10, on="date", how="left")
    d_etf = d_etf.sort_values("date").reset_index(drop=True)
    d_etf["etf22_amt_spike"] = d_etf["etf22_amt_yi"] / d_etf["etf22_amt_yi"].rolling(20, min_periods=10).median().shift(1)
    d_etf["core10_amt_spike"] = d_etf["core10_amt_yi"] / d_etf["core10_amt_yi"].rolling(20, min_periods=10).median().shift(1)
    d_etf["etf22_wflow_5d"] = d_etf["etf22_wflow_yi"].rolling(5, min_periods=1).sum()
    d_etf["wflow_pct_aum"] = d_etf["etf22_wflow_yi"] / d_etf["etf22_aum_yi"].shift(1).replace(0, np.nan) * 100.0

    consec, c = [], 0
    for v, nsh in zip(d_etf["etf22_wflow_yi"].fillna(0), d_etf["etf22_n_sh"].fillna(0)):
        c = c + 1 if (nsh > 0 and v >= 30.0) else 0
        consec.append(c)
    d_etf["nt_tapering_stop"] = ((pd.Series(consec).shift(1).fillna(0) >= 3) & (d_etf["etf22_wflow_5d"].shift(1).fillna(0) >= 220.0) & (d_etf["etf22_wflow_yi"] <= 0.0)).astype(int)
    p = p.merge(d_etf, on="date", how="left")

    # Dim 2 & 4: 16 NT Heavyweights + 8 Fund Heavyweights
    stk = pd.read_parquet(f"{CACHE_DIR}/stocks23_to_20261124.parquet").sort_values(["ticker", "date"]).reset_index(drop=True)
    ratio = np.where(stk["close"] > 0, stk["adj_close"] / stk["close"], 1.0)
    stk["open_adj"] = stk["open"] * ratio
    stk["low_adj"] = stk["low"] * ratio
    stk["prev_adj"] = stk.groupby("ticker")["adj_close"].shift(1)
    stk["cc_ret"] = stk["adj_close"] / stk["prev_adj"] - 1.0
    stk["oc_ret"] = stk["adj_close"] / stk["open_adj"] - 1.0
    stk["pullup"] = (stk["adj_close"] - stk["low_adj"]) / stk["prev_adj"]
    stk["amt_med20_s1"] = stk.groupby("ticker")["amount"].transform(lambda s: s.rolling(20, min_periods=10).median().shift(1))
    stk["amt_spike"] = stk["amount"] / stk["amt_med20_s1"].replace(0, np.nan)

    s16 = stk[stk["ticker"].isin(NT16)].copy()
    s16["vol_up"] = (s16["amt_spike"] >= 1.4) & ((s16["cc_ret"] >= 0.0) | (s16["pullup"] >= 0.012))
    g16 = s16.groupby("date").agg(hw16_sync_cnt=("vol_up", "sum")).reset_index()
    for sq_name, tks in SQUADS.items():
        sq_sub = s16[s16["ticker"].isin(tks)].groupby("date").agg(**{f"sq_{sq_name}_hits": ("vol_up", "sum")}).reset_index()
        g16 = g16.merge(sq_sub, on="date", how="left")
    big4o = s16[s16["ticker"].isin(BIG4_OIL)].groupby("date")["cc_ret"].mean().rename("big4_oil_ret").reset_index()
    g16 = g16.merge(big4o, on="date", how="left")
    g16["sq_active_cnt"] = (
        (g16["sq_bank_hits"].fillna(0) >= 1).astype(int) +
        (g16["sq_energy_hits"].fillna(0) >= 1).astype(int) +
        (g16["sq_fincons_hits"].fillna(0) >= 1).astype(int) +
        (g16["sq_growth_hits"].fillna(0) >= 1).astype(int)
    )
    p = p.merge(g16, on="date", how="left")

    sf8 = stk[stk["ticker"].isin(FUND8)].copy()
    sf8["is_dump"] = (sf8["oc_ret"] <= -0.020) & (sf8["amt_spike"] >= 1.2)
    g8 = sf8.groupby("date").agg(fund8_dump_cnt=("is_dump", "sum")).reset_index()
    p = p.merge(g8, on="date", how="left")

    # Dim 3: Futures
    fut = pd.read_parquet(f"{CACHE_DIR}/futures_to_20261124.parquet").sort_values("date").reset_index(drop=True)
    fut["if0_spike"] = fut["IF0_vol"] / fut["IF0_vol"].rolling(20, min_periods=10).median().shift(1)
    p = p.merge(fut, on="date", how="left")
    p["if0_basis_pct"] = (p["IF0_close"] / p["c300_close"] - 1.0) * 100.0
    p["if0_basis_chg1"] = p["if0_basis_pct"] - p["if0_basis_pct"].shift(1)

    dt_s = pd.to_datetime(p["date"])
    p["ym"] = dt_s.dt.strftime("%Y-%m")
    deliv_dates = set()
    for ym_val, grp in p.groupby("ym"):
        y, m = map(int, ym_val.split("-"))
        fd = pd.Timestamp(year=y, month=m, day=1)
        ff = 1 + (4 - fd.weekday()) % 7
        tf = pd.Timestamp(year=y, month=m, day=ff + 14)
        cand = grp[pd.to_datetime(grp["date"]) >= tf]
        if len(cand):
            deliv_dates.add(cand["date"].iloc[0])
    p["is_deliv"] = p["date"].isin(deliv_dates)

    # Dim 4: Sector 9 ETFs + LHB
    sec_px = etf_ex[etf_ex["code"].isin(SEC9)].copy()
    sec_sh = sh_ex[sh_ex["code"].isin(SEC9)].copy()
    sec = sec_px.merge(sec_sh, on=["date", "code"], how="left").sort_values(["code", "date"]).reset_index(drop=True)
    sec["prev_sh"] = sec.groupby("code")["shares_wan"].shift(1)
    sec["sh_ret"] = sec["shares_wan"] / sec["prev_sh"] - 1.0
    sec["next_pct"] = sec.groupby("code")["pct_chg"].shift(-1).fillna(0.0)
    sec["prev_pct"] = sec.groupby("code")["pct_chg"].shift(1).fillna(0.0)
    sec_split = ((sec["sh_ret"].abs() > 0.35) & ((sec["pct_chg"].abs() > 20) | (sec["next_pct"].abs() > 20) | (sec["prev_pct"].abs() > 20))) | (sec["pct_chg"].abs() > 25)
    sec["flow_yi"] = np.where(sec_split, 0.0, (sec["shares_wan"] - sec["prev_sh"]) * 1e4 * sec["close"] / 1e8)
    g_sec = sec.groupby("date")["flow_yi"].sum().rename("sec9_flow_1d_yi").reset_index().sort_values("date")
    g_sec["sec9_flow_5d_yi"] = g_sec["sec9_flow_1d_yi"].rolling(5, min_periods=1).sum()
    p = p.merge(g_sec, on="date", how="left")

    lhb = pd.read_parquet(f"{CACHE_DIR}/lhb_org_daily_2020_2026.parquet")
    p = p.merge(lhb[["date", "lhb_net_yi"]], on="date", how="left")
    p["lhb_net_yi"] = p["lhb_net_yi"].fillna(0.0)
    p["lhb_5d_net_yi"] = p["lhb_net_yi"].rolling(5, min_periods=1).sum()

    # Dim 5: Official NT Events
    ev = pd.read_json(f"{NT_DIR}/nt_official_events.json")
    ev_entry = ev[ev["cat"] == "NT_OFFICIAL_ENTRY"].copy()
    dates_list = p["date"].tolist()
    d2i = {d: i for i, d in enumerate(dates_list)}
    off_eod = np.zeros(len(p), dtype=int)
    off_int = np.zeros(len(p), dtype=int)
    for _, r in ev_entry.iterrows():
        dt_e, sl = str(r["event_date"]), str(r["slot"]).upper()
        if dt_e in d2i:
            idx_e = d2i[dt_e]
            for k in range(idx_e, min(len(p), idx_e + 5)):
                off_eod[k] = 1
                if k > idx_e or sl in ("BMO", "INTRADAY"):
                    off_int[k] = 1
        else:
            later = [k for k, d in enumerate(dates_list) if d > dt_e]
            if later:
                idx_e = later[0]
                for k in range(idx_e, min(len(p), idx_e + 5)):
                    off_eod[k] = 1
                    off_int[k] = 1
    p["official_nt_5d_eod"] = off_eod
    p["official_nt_5d_intra"] = off_int
    return p


def score_panel(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy().reset_index(drop=True)
    d["lag1_wflow_5d"] = d["etf22_wflow_5d"].shift(1)
    d["lag1_sec9_5d"] = d["sec9_flow_5d_yi"].shift(1)
    d["lag1_lhb_5d"] = d["lhb_5d_net_yi"].shift(1)

    live_scores, eod_scores = [], []
    for _, r in d.iterrows():
        s_live = 20
        s_eod = 20

        # Dim 5: Context & Policy
        is_weak = (pd.notna(r["c300_ma20"]) and r["c300_close"] < r["c300_ma20"]) or (pd.notna(r["c300_dd60"]) and r["c300_dd60"] <= -0.06)
        is_deep = pd.notna(r["c300_dd60"]) and r["c300_dd60"] <= -0.08
        is_high = (pd.notna(r["c300_ma20"]) and r["c300_close"] > r["c300_ma20"]) and (pd.notna(r["c300_ret20"]) and r["c300_ret20"] >= 0.05)
        is_bubble = (pd.notna(r["c300_ma20"]) and r["c300_close"] > r["c300_ma20"]) and (pd.notna(r["c300_ret20"]) and r["c300_ret20"] >= 0.15)

        if is_high:
            s_live -= 18
            s_eod -= 18
            if is_bubble:
                s_live -= 6
                s_eod -= 6
        else:
            if is_weak:
                s_live += 6
                s_eod += 6
            if is_deep:
                s_live += 4
                s_eod += 4

        if int(r["official_nt_5d_intra"] or 0) == 1:
            s_live += 12
        if int(r["official_nt_5d_eod"] or 0) == 1:
            s_eod += 12

        # Dim 1: Broad ETF Pool
        c10_spk = float(r["core10_amt_spike"] or 0.0) if pd.notna(r["core10_amt_spike"]) else 0.0
        e22_spk = float(r["etf22_amt_spike"] or 0.0) if pd.notna(r["etf22_amt_spike"]) else 0.0
        spk = max(c10_spk, e22_spk)
        pullup = float(r["c300_pullup"] or 0.0) if pd.notna(r["c300_pullup"]) else 0.0
        t1_c = int(r["core10_t1_cnt16"] or 0) if pd.notna(r["core10_t1_cnt16"]) else 0
        t2_c = int(r["core10_t2_cnt16"] or 0) if pd.notna(r["core10_t2_cnt16"]) else 0

        if spk >= 2.0:
            s_live += 16
            s_eod += 12
        elif spk >= 1.5:
            s_live += 10
            s_eod += 7
        elif spk >= 1.2 and pullup >= 0.008:
            s_live += 4
            s_eod += 3

        if spk >= 1.5 and pullup >= 0.008:
            s_live += 4
            s_eod += 3

        if t1_c >= 2 and t2_c >= 2:
            s_live += 8
        elif (t1_c + t2_c) >= 5:
            s_live += 6
        elif t1_c >= 2 and t2_c == 0:
            s_live -= 4

        l5 = float(r["lag1_wflow_5d"] or 0.0) if pd.notna(r["lag1_wflow_5d"]) else 0.0
        if l5 >= 150.0:
            s_live += 4

        wf = float(r["etf22_wflow_yi"] or 0.0) if pd.notna(r["etf22_wflow_yi"]) else 0.0
        wpct = float(r["wflow_pct_aum"] or 0.0) if pd.notna(r["wflow_pct_aum"]) else 0.0
        wf5 = float(r["etf22_wflow_5d"] or 0.0) if pd.notna(r["etf22_wflow_5d"]) else 0.0
        t1f = float(r["t1_flow_yi"] or 0.0) if pd.notna(r["t1_flow_yi"]) else 0.0
        t2f = float(r["t2_flow_yi"] or 0.0) if pd.notna(r["t2_flow_yi"]) else 0.0

        if wf >= 90.0 or wpct >= 1.5:
            s_eod += 12
        elif wf >= 40.0 or wpct >= 0.7:
            s_eod += 7

        if wf5 >= 150.0:
            s_eod += 4
        if t1f >= 50.0 and t2f >= 25.0:
            s_eod += 6
        elif t1f >= 75.0 and t2f < 15.0:
            s_eod -= 5

        # Dim 2: 16 NT Heavyweights
        hw_cnt = int(r["hw16_sync_cnt"] or 0) if pd.notna(r["hw16_sync_cnt"]) else 0
        sq_cnt = int(r["sq_active_cnt"] or 0) if pd.notna(r["sq_active_cnt"]) else 0
        b4o = float(r["big4_oil_ret"] or 0.0) if pd.notna(r["big4_oil_ret"]) else 0.0
        c1k = float(r["c1000_ret"] or 0.0) if pd.notna(r["c1000_ret"]) else 0.0

        if spk >= 1.5 and hw_cnt >= 4:
            pts_hw = 10 + (4 if (hw_cnt >= 8 and sq_cnt >= 3) else 0)
            s_live += pts_hw
            s_eod += pts_hw
        elif spk < 1.3 and (((b4o - c1k) >= 0.020) or (b4o >= 0.008 and c1k <= -0.008)):
            s_live -= 10
            s_eod -= 10

        # Dim 3: Index Futures Linkage
        if_spk = float(r["if0_spike"] or 0.0) if pd.notna(r["if0_spike"]) else 0.0
        if_bas = float(r["if0_basis_pct"] or 0.0) if pd.notna(r["if0_basis_pct"]) else 0.0
        bas_c1 = float(r["if0_basis_chg1"] or 0.0) if pd.notna(r["if0_basis_chg1"]) else 0.0
        is_del = bool(r["is_deliv"])

        if spk >= 1.8 and if_spk >= 1.5 and (not is_del):
            s_live -= 10
            s_eod -= 10
        elif spk >= 1.8 and if_spk < 1.5 and (not is_del):
            s_live += 6
            s_eod += 6

        if spk >= 1.5 and if_bas <= -0.5:
            s_live += 5
            s_eod += 5
        if spk >= 1.5 and if_bas <= -0.1 and bas_c1 >= 0.25:
            s_live += 3
            s_eod += 3
        if (is_weak and if_bas >= 0.0) or (if_bas >= 0.30):
            s_live -= 5
            s_eod -= 5

        # Dim 4: Institutional & Redemption Pressure
        f8_dump = int(r["fund8_dump_cnt"] or 0) if pd.notna(r["fund8_dump_cnt"]) else 0
        if f8_dump >= 3:
            s_live -= 6
            s_eod -= 6

        s9_lag = float(r["lag1_sec9_5d"] or 0.0) if pd.notna(r["lag1_sec9_5d"]) else 0.0
        lhb_lag = float(r["lag1_lhb_5d"] or 0.0) if pd.notna(r["lag1_lhb_5d"]) else 0.0
        if s9_lag <= -35.0 or lhb_lag <= -40.0:
            s_live -= 4

        s9_cur = float(r["sec9_flow_5d_yi"] or 0.0) if pd.notna(r["sec9_flow_5d_yi"]) else 0.0
        lhb_cur = float(r["lhb_5d_net_yi"] or 0.0) if pd.notna(r["lhb_5d_net_yi"]) else 0.0
        if s9_cur <= -35.0:
            s_eod -= 4
        if lhb_cur <= -40.0:
            s_eod -= 4

        if wf <= -80.0:
            s_eod -= 12
        elif int(r["nt_tapering_stop"] or 0) == 1:
            s_eod -= 5
        if wf5 <= -250.0:
            s_eod -= 8

        live_scores.append(int(np.clip(s_live, 0, 100)))
        eod_scores.append(int(np.clip(s_eod, 0, 100)))

    d["score_live"] = live_scores
    d["score_eod"] = eod_scores
    return d


def single_slot_eval(df_sub: pd.DataFrame, mask: pd.Series):
    idxs = df_sub.index[mask].tolist()
    taken = []
    nf = -1
    for i in idxs:
        if i >= nf and i + 20 < len(df_sub):
            r20 = df_sub.at[i, "c300_open_fwd_20d"]
            if pd.notna(r20):
                taken.append((i, float(r20)))
                nf = i + 20
    if not taken:
        return {"n_trades": 0, "compound_ret_pct": None, "bench_same_window_pct": None, "excess_vs_300_pct": None, "win_rate_pct": None, "mdd_pct": None}
    rets = np.array([x[1] - COST_ROUND_TRIP for x in taken])
    nav = np.cumprod(1.0 + rets)
    peak = np.maximum.accumulate(np.insert(nav, 0, 1.0))[1:]
    mdd = float(np.min(nav / peak - 1.0)) * 100.0
    comp = (nav[-1] - 1.0) * 100.0
    # Full window CSI300 buy-and-hold
    bh = (df_sub["c300_close"].iloc[-1] / df_sub["c300_close"].iloc[0] - 1.0) * 100.0
    return {
        "n_trades": int(len(taken)),
        "compound_ret_pct": round(comp, 2),
        "bench_300_bh_pct": round(bh, 2),
        "excess_vs_bh_pct": round(comp - bh, 2),
        "win_rate_pct": round(float((rets > 0).mean() * 100.0), 1),
        "mdd_pct": round(mdd, 2),
    }


def summarize_tier_table(df: pd.DataFrame, score_col: str) -> dict:
    tiers = [(0, 39, "<40 无救市/观望"), (40, 59, "40~59 脉冲维稳"), (60, 74, "60~74 准救市试探"), (75, 100, ">=75 真底重手救市")]
    windows = [
        ("IS_2021_2023", df[(df["date"] >= "2021-01-04") & (df["date"] <= "2023-12-31")]),
        ("OOS_2024_2026", df[df["date"] >= "2024-01-01"]),
        ("ALL_2021_2026", df[df["date"] >= "2021-01-04"]),
        ("EXT_2017_2026", df[df["date"] >= "2017-01-17"]),
    ]
    out = {}
    for w_name, df_w in windows:
        df_w = df_w.reset_index(drop=True)
        bh_300 = round(float((df_w["c300_close"].iloc[-1] / df_w["c300_close"].iloc[0] - 1.0) * 100.0), 2)
        bh_1000 = round(float((df_w["c1000_close"].iloc[-1] / df_w["c1000_close"].iloc[0] - 1.0) * 100.0), 2)
        rows = []
        for lo, hi, lbl in tiers:
            m = (df_w[score_col] >= lo) & (df_w[score_col] <= hi)
            s = df_w[m]
            r5 = s["c300_open_fwd_5d"].dropna() * 100.0
            r20 = s["c300_open_fwd_20d"].dropna() * 100.0
            k5 = s["c1000_open_fwd_5d"].dropna() * 100.0
            k20 = s["c1000_open_fwd_20d"].dropna() * 100.0
            w20, l20 = r20[r20 > 0], -r20[r20 < 0]
            pl20 = float(w20.mean() / l20.mean()) if (len(w20) and len(l20)) else (9.99 if len(w20) else None)
            w5, l5 = r5[r5 > 0], -r5[r5 < 0]
            pl5 = float(w5.mean() / l5.mean()) if (len(w5) and len(l5)) else (9.99 if len(w5) else None)
            sl = single_slot_eval(df_w, m)
            rows.append({
                "tier": lbl, "n_days": int(len(s)),
                "c300_t5_mean_pct": round(float(r5.mean()), 2) if len(r5) else None,
                "c300_t5_win_pct": round(float((r5 > 0).mean() * 100), 1) if len(r5) else None,
                "c300_t5_payoff": round(pl5, 2) if pl5 is not None else None,
                "c300_t20_mean_pct": round(float(r20.mean()), 2) if len(r20) else None,
                "c300_t20_win_pct": round(float((r20 > 0).mean() * 100), 1) if len(r20) else None,
                "c300_t20_payoff": round(pl20, 2) if pl20 is not None else None,
                "c1000_t5_mean_pct": round(float(k5.mean()), 2) if len(k5) else None,
                "c1000_t20_mean_pct": round(float(k20.mean()), 2) if len(k20) else None,
                "c1000_t20_win_pct": round(float((k20 > 0).mean() * 100), 1) if len(k20) else None,
                "slot_20d": sl,
            })
        out[w_name] = {"csi300_bh_pct": bh_300, "csi1000_bh_pct": bh_1000, "tiers": rows}
    return out


def univariate_dimension_audit(d21: pd.DataFrame) -> list:
    weak = (d21["c300_close"] < d21["c300_ma20"]) | (d21["c300_dd60"] <= -0.06)
    high = (d21["c300_close"] > d21["c300_ma20"]) & (d21["c300_ret20"] >= 0.05)
    checks = [
        ("BASE_无条件基准", pd.Series(True, index=d21.index)),
        ("D1_Core10量比>=1.5x(弱势)", weak & (d21["core10_amt_spike"] >= 1.5)),
        ("D1_Core10量比>=2.0x(弱势)", weak & (d21["core10_amt_spike"] >= 2.0)),
        ("D1_一二队盘中同步>=2&>=2(弱势)", weak & (d21["core10_t1_cnt16"] >= 2) & (d21["core10_t2_cnt16"] >= 2)),
        ("D1_一队偏心抽血T1>=2&T2=0(弱势)", weak & (d21["core10_t1_cnt16"] >= 2) & (d21["core10_t2_cnt16"] == 0)),
        ("D1_盘后纯净净申购>=90亿或>=1.5%AUM(弱势)", weak & ((d21["etf22_wflow_yi"] >= 90.0) | (d21["wflow_pct_aum"] >= 1.5))),
        ("D1_F152一二队共振(T1>=50&T2>=25)", (d21["t1_flow_yi"] >= 50.0) & (d21["t2_flow_yi"] >= 25.0)),
        ("D1_F151一队偏心(T1>=75&T2<15)", (d21["t1_flow_yi"] >= 75.0) & (d21["t2_flow_yi"] < 15.0)),
        ("D2_16权重同步>=4+ETF>=1.5x(弱势)", weak & (d21["hw16_sync_cnt"] >= 4) & (d21["core10_amt_spike"] >= 1.5)),
        ("D2_假护盘抽血(银行石油-1000>=2%,ETF<1.3x)", ((d21["big4_oil_ret"] - d21["c1000_ret"]) >= 0.020) & (d21["core10_amt_spike"] < 1.3)),
        ("D3_RD019期现双爆量陷阱(ETF>=1.8&IF0>=1.5非交割)", weak & (d21["core10_amt_spike"] >= 1.8) & (d21["if0_spike"] >= 1.5) & (~d21["is_deliv"])),
        ("D3_纯净现货护盘(ETF>=1.8&IF0<1.5非交割)", weak & (d21["core10_amt_spike"] >= 1.8) & (d21["if0_spike"] < 1.5) & (~d21["is_deliv"])),
        ("D3_弱势IF0升水/零贴水(>=0%)", weak & (d21["if0_basis_pct"] >= 0.0)),
        ("D3_深贴水护盘(IF0<=-0.5%&ETF>=1.5x)", weak & (d21["if0_basis_pct"] <= -0.5) & (d21["core10_amt_spike"] >= 1.5)),
        ("D4_F154单日纯净赎回<=-80亿", d21["etf22_wflow_yi"] <= -80.0),
        ("D4_F156五日纯净赎回<=-250亿", d21["etf22_wflow_5d"] <= -250.0),
        ("D4_公募8重仓放量砸盘>=3只(无ETF护盘)", weak & (d21["fund8_dump_cnt"] >= 3) & (d21["core10_amt_spike"] < 1.3)),
        ("D5_弱势深跌背景(dd60<=-8%)", d21["c300_dd60"] <= -0.08),
        ("D5_高位过热(MA20上+20日>=5%)", high),
        ("D5_官方明牌增持公告(5日PIT)", d21["official_nt_5d_eod"] == 1),
    ]
    rows = []
    for nm, m in checks:
        s = d21[m]
        r5 = s["c300_open_fwd_5d"].dropna() * 100.0
        r20 = s["c300_open_fwd_20d"].dropna() * 100.0
        k20 = s["c1000_open_fwd_20d"].dropna() * 100.0
        rows.append({
            "factor": nm, "n": int(len(s)),
            "c300_5d_pct": round(float(r5.mean()), 2) if len(r5) else None,
            "c300_w5_pct": round(float((r5 > 0).mean() * 100), 1) if len(r5) else None,
            "c300_20d_pct": round(float(r20.mean()), 2) if len(r20) else None,
            "c300_w20_pct": round(float((r20 > 0).mean() * 100), 1) if len(r20) else None,
            "c1000_20d_pct": round(float(k20.mean()), 2) if len(k20) else None,
            "c1000_w20_pct": round(float((k20 > 0).mean() * 100), 1) if len(k20) else None,
        })
    return rows


def main():
    p = load_master_panel()
    scored = score_panel(p)
    d21 = scored[scored["date"] >= "2021-01-04"].copy().reset_index(drop=True)

    live_res = summarize_tier_table(scored, "score_live")
    eod_res = summarize_tier_table(scored, "score_eod")
    uni = univariate_dimension_audit(d21)

    for tag, res in [("LIVE INTRADAY SCORE (盘中实时版)", live_res), ("SETTLED EOD SCORE (盘后实锤版)", eod_res)]:
        print(f"\n==================== {tag} ====================")
        for w in ["IS_2021_2023", "OOS_2024_2026", "ALL_2021_2026", "EXT_2017_2026"]:
            wb = res[w]
            print(f"[{w}] CSI300 B&H={wb['csi300_bh_pct']:+.2f}% | CSI1000 B&H={wb['csi1000_bh_pct']:+.2f}%")
            for r in wb["tiers"]:
                sl = r["slot_20d"]
                print(f"  {r['tier']:18s} | n={r['n_days']:4d} | T+5={str(r['c300_t5_mean_pct']):>6s}% (w={str(r['c300_t5_win_pct']):>5s}%, PL={str(r['c300_t5_payoff']):>4s}) | T+20={str(r['c300_t20_mean_pct']):>6s}% (w={str(r['c300_t20_win_pct']):>5s}%, PL={str(r['c300_t20_payoff']):>4s}) | 1000_20d={str(r['c1000_t20_mean_pct']):>6s}% | 20d单仓(n={sl['n_trades']}):复利={str(sl['compound_ret_pct']):>6s}%,DD={str(sl['mdd_pct']):>6s}%")

    lms = ["2021-07-28","2022-04-26","2022-04-27","2022-11-01","2023-08-28","2023-10-23","2023-12-28","2024-01-22","2024-02-05","2024-02-06","2024-07-19","2024-09-24","2024-09-30","2024-10-08","2024-10-09","2025-04-07","2025-04-08","2026-07-20","2026-11-02","2026-11-19","2026-11-20","2026-11-23","2026-11-24"]
    lm_rows = scored[scored["date"].isin(lms)][["date","c300_ret","core10_amt_spike","etf22_wflow_yi","hw16_sync_cnt","if0_basis_pct","score_live","score_eod","c300_open_fwd_5d","c300_open_fwd_20d"]].copy()
    for c in ["c300_ret", "c300_open_fwd_5d", "c300_open_fwd_20d"]:
        lm_rows[c] = (lm_rows[c] * 100.0).round(2)
    print("\n=== LANDMARK VERIFICATION ===")
    print(lm_rows.round(2).to_string(index=False))

    audit = {
        "meta": {
            "model": "CSRC National Team Rescue & Institutional Hedge Scorecard V3.0",
            "primary_window": "2021-01-04 ~ 2026-11-24",
            "n_days_primary": int(len(d21)),
            "is_window": "2021-01-04 ~ 2023-12-31",
            "oos_window": "2024-01-01 ~ 2026-11-24",
            "ext_10y_window": "2017-01-17 ~ 2026-11-24",
            "pit_rule": "Signal observed at T (Intraday vs Settled EOD), executed strictly at T+1 open, 0.30% round-trip cost.",
            "data_as_of_date": str(scored["date"].max()),
        },
        "scorecard_spec": V3_SCORECARD_SPEC,
        "univariate_5dim_audit_2021_2026": uni,
        "live_intraday_calibration": live_res,
        "settled_eod_calibration": eod_res,
        "landmark_dates": lm_rows.round(3).to_dict(orient="records"),
    }
    with open(AUDIT_OUT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"\nSaved audit JSON -> {AUDIT_OUT}")


if __name__ == "__main__":
    main()
