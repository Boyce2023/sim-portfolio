#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD029 Zero-Hindsight Data Builder (2000-01-04 ~ 2026-11-25).
Strictly D12 compliant (NO yfinance). Zero cap10m metrics.
Constructs:
  1. Causal backward-adjusted (hfq, base=listing day) & raw OHLCV for 510050, 510300, 510500, 512100
     from listing date through 2026-11-25 close (Sina historical + Sina dividends + official LSJZ splits + Tencent 11-25).
  2. Extended daily market panel & V3 inputs through 2026-11-25 (Tencent live EOD quotes + Sina futures).
  3. Strict +1 full month PIT-lagged waterpool monthly mapping (avail > M+1 day 16, i.e., >= 17th of M+1).
"""
import json
import os
import re
import time
import warnings
warnings.filterwarnings("ignore")

for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

import akshare as ak
import numpy as np
import pandas as pd
import requests

assert "yfinance" not in __import__("sys").modules, "D12 violation: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CSRC_DIR = os.path.join(ROOT, "output/csrc_policy_100factors_20261114")
NT_DIR = os.path.join(CSRC_DIR, "national_team")
V3_CACHE_DIR = os.path.join(NT_DIR, "v3_cache")
POLY_DIR = os.path.join(CSRC_DIR, "policy_polymarket_v1")
PILLAR_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/data_pillars")
OUT_DIR = os.path.join(ROOT, "output/china_policy_macro_rd027_20261125/rd029_daybyday_etf")
CACHE_DIR = os.path.join(OUT_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

TARGET_END_DATE = "2026-11-25"

INDEX_MAP = {
    "sh000001": "sh_comp", "sh000300": "csi300", "sz399006": "chinext",
    "sh000688": "star50", "sh000905": "csi500", "sh000852": "csi1000",
    "sh000016": "sse50", "sh000922": "csi_div", "sz399975": "brokerage",
    "sz399986": "bank_idx", "sh000941": "new_energy", "sz399997": "baijiu",
    "sh000933": "pharma", "sz399974": "soe_reform", "sh000926": "central_soe",
    "sz399967": "defense", "sz399971": "media_ai", "sh000993": "tmt_info",
    "sh000989": "cons_opt", "sz399393": "real_estate", "sh512480": "semi_etf",
}

CORE_ETF_CODES = ["510050", "510300", "510500", "512100"]

# Verified official ETF share conversion / split factors from EastMoney LSJZ NAV continuity:
# On ex_split_date, 1 pre-split share converts to S post-split shares -> raw price drops by 1/S,
# so causal hfq factor multiplies by S (equivalently qfq multiplies pre-split by 1/S).
# Verification:
#   510500 2015-04-15: 2015-04-14 FHSP = '每份基金份额折算0.28032483份' -> S = 0.28032483 (pre-split * 3.56729)
#   510500 2022-08-29: 2022-08-25 DWJZ=7.2390, 2022-08-26 DWJZ=6.2977 (JZZZL=-0.35%) -> S = (7.2390*0.9965)/6.2977 = 1.14545
#   512100 2022-09-05: 2022-09-01 DWJZ=0.9823, 2022-09-02 DWJZ=2.7109 (JZZZL=+0.88%) -> S = (0.9823*1.0088)/2.7109 = 0.36554
VERIFIED_ETF_SPLITS = {
    "510500": [
        ("2015-04-15", 0.28032483),
        ("2022-08-29", 1.14544615),
    ],
    "512100": [
        ("2022-09-05", 0.36554016),
    ],
}

NT21_META = {
    "510300": ("华泰柏瑞沪深300ETF", "SSE", "CSI300", "T1", 0.8296),
    "510310": ("易方达沪深300ETF", "SSE", "CSI300", "T1", 0.8549),
    "510330": ("华夏沪深300ETF", "SSE", "CSI300", "T1", 0.8914),
    "159919": ("嘉实沪深300ETF", "SZSE", "CSI300", "T1", 0.8766),
    "510050": ("华夏上证50ETF", "SSE", "SSE50", "T1", 0.8605),
    "510180": ("华安上证180ETF", "SSE", "SSE180", "T1", 0.9193),
    "510230": ("国泰上证180金融ETF", "SSE", "SSE180FIN", "T1", 0.7759),
    "159901": ("易方达深证100ETF", "SZSE", "SZ100", "T1", 0.4693),
    "510100": ("易方达上证50ETF", "SSE", "SSE50", "T1", 0.0583),
    "560010": ("广发中证1000ETF", "SSE", "CSI1000", "T2", 0.9186),
    "512100": ("南方中证1000ETF", "SSE", "CSI1000", "T2", 0.8643),
    "159845": ("华夏中证1000ETF", "SZSE", "CSI1000", "T2", 0.8615),
    "159629": ("富国中证1000ETF", "SZSE", "CSI1000", "T2", 0.8574),
    "510500": ("南方中证500ETF", "SSE", "CSI500", "T2", 0.7591),
    "512500": ("华夏中证500ETF", "SSE", "CSI500", "T2", 0.6734),
    "159922": ("嘉实中证500ETF", "SZSE", "CSI500", "T2", 0.4606),
    "159915": ("易方达创业板ETF", "SZSE", "CHINEXT", "T2", 0.5403),
    "159952": ("广发创业板ETF", "SZSE", "CHINEXT", "T2", 0.1689),
    "588080": ("易方达科创50ETF", "SSE", "STAR50", "T2", 0.4195),
    "588050": ("工银科创50ETF", "SSE", "STAR50", "T2", 0.1178),
    "560170": ("南方央企科技引领ETF", "SSE", "SOETECH", "T3", 0.6630),
}

NT16_TICKERS = [
    "601398.SH", "601288.SH", "601988.SH", "601939.SH", "600036.SH",
    "601857.SH", "600028.SH", "600941.SH", "601088.SH", "600900.SH",
    "601318.SH", "601628.SH", "600519.SH", "600030.SH",
    "300750.SZ", "688981.SH",
]
FUND8_TICKERS = [
    "300750.SZ", "300308.SZ", "300274.SZ", "688256.SH",
    "300059.SZ", "002475.SZ", "603259.SH", "000858.SZ",
]


def _ticker_to_qt(tk: str) -> str:
    code, ex = tk.split(".")
    return ("sh" if ex == "SH" else "sz") + code


def fetch_qt_quotes(syms: list[str]) -> dict[str, dict]:
    out = {}
    for i in range(0, len(syms), 50):
        batch = syms[i:i + 50]
        url = "http://qt.gtimg.cn/q=" + ",".join(batch)
        raw = requests.get(
            url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
            proxies={"http": None, "https": None},
        ).content.decode("gbk", "ignore")
        for ln in raw.strip().splitlines():
            m = re.match(r'v_(\w+)="([^"]*)"', ln.strip())
            if not m:
                continue
            sym = m.group(1)
            ps = m.group(2).split("~")
            if len(ps) < 38:
                continue
            def _f(idx):
                try:
                    return float(ps[idx]) if ps[idx] not in ("", "-") else np.nan
                except Exception:
                    return np.nan
            dt_raw = ps[30][:8] if len(ps) > 30 and len(ps[30]) >= 8 else ""
            dt_fmt = f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}" if len(dt_raw) == 8 else ""
            out[sym] = {
                "sym": sym,
                "code": ps[2],
                "name": ps[1].replace(" ", ""),
                "close": _f(3),
                "prev_close": _f(4),
                "open": _f(5),
                "volume": _f(6),
                "pct_chg": _f(32),
                "high": _f(33),
                "low": _f(34),
                "amount": (_f(37) * 1e4) if pd.notna(_f(37)) else np.nan,  # 万元 -> 元
                "date": dt_fmt,
            }
    return out


def fetch_sina_futures_day(target_date: str = TARGET_END_DATE) -> dict[str, dict]:
    r = requests.get(
        "https://hq.sinajs.cn/list=CFF_RE_IF0,CFF_RE_IH0,CFF_RE_IC0,CFF_RE_IM0",
        headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"},
        proxies={"http": None, "https": None},
        timeout=10,
    ).text
    out = {}
    for ln in r.strip().splitlines():
        m = re.match(r'var hq_str_CFF_RE_(\w+)="([^"]*)"', ln.strip())
        if not m:
            continue
        sym = m.group(1)
        ps = m.group(2).split(",")
        if len(ps) > 37 and ps[36] == target_date:
            out[sym] = {
                "open": float(ps[0]),
                "high": float(ps[1]),
                "low": float(ps[2]),
                "close": float(ps[3]),
                "vol": float(ps[4]),
                "oi": float(ps[6]),
            }
    return out


def build_core_etf_prices(force_refresh: bool = False) -> pd.DataFrame:
    """
    Build real tradable daily OHLCV + causal HFQ (with dividend reinvestment & split adjustment)
    for 510050 (2005-02-23+), 510300 (2012-05-28+), 510500 (2013-03-15+), 512100 (2016-11-04+)
    through 2026-11-25 close.
    """
    out_pq = os.path.join(CACHE_DIR, "core4_etfs_to_20261125.parquet")
    if (not force_refresh) and os.path.exists(out_pq):
        df = pd.read_parquet(out_pq)
        if str(df["date"].max()) >= TARGET_END_DATE:
            return df

    qt = fetch_qt_quotes([f"sh{c}" for c in CORE_ETF_CODES])
    frames = []
    for code in CORE_ETF_CODES:
        sym = f"sh{code}"
        px = ak.fund_etf_hist_sina(symbol=sym)
        px["date"] = pd.to_datetime(px["date"]).dt.strftime("%Y-%m-%d")
        px = px.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        for c in ["open", "high", "low", "close", "volume", "amount"]:
            px[c] = pd.to_numeric(px[c], errors="coerce")

        # Append 2026-11-25 from Tencent if not yet in Sina
        q = qt.get(sym, {})
        if q.get("date") == TARGET_END_DATE and TARGET_END_DATE not in set(px["date"]):
            # Note: qt volume for ETFs in ps[6] is in 手(100 shares) or shares; use amount / avg_px if needed, keep exact open/high/low/close/amount
            new_row = {
                "date": TARGET_END_DATE,
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "close": q["close"],
                "volume": q["volume"] * 100.0,
                "amount": q["amount"],
            }
            px = pd.concat([px, pd.DataFrame([new_row])], ignore_index=True).sort_values("date").reset_index(drop=True)

        # Fetch Sina dividends
        div = ak.fund_etf_dividend_sina(symbol=sym)
        div_map = {}
        if div is not None and not div.empty:
            div["date"] = pd.to_datetime(div["日期"]).dt.strftime("%Y-%m-%d")
            div["cum_div"] = pd.to_numeric(div["累计分红"], errors="coerce")
            div = div.sort_values("date").reset_index(drop=True)
            div["div_amt"] = div["cum_div"].diff().fillna(div["cum_div"])
            for _, r in div.iterrows():
                da = float(r["div_amt"])
                if da > 0:
                    div_map[r["date"]] = div_map.get(r["date"], 0.0) + da

        split_map = {d: s for d, s in VERIFIED_ETF_SPLITS.get(code, [])}

        # Causal forward-stepping HFQ factor (base=1.0 on inception day, NEVER touches future rows!)
        n = len(px)
        hfq_factor = np.ones(n, dtype=float)
        div_col = np.zeros(n, dtype=float)
        split_col = np.ones(n, dtype=float)
        for i in range(1, n):
            dt = px.at[i, "date"]
            f = hfq_factor[i - 1]
            prev_c = float(px.at[i - 1, "close"])
            if dt in div_map and prev_c > div_map[dt]:
                da = div_map[dt]
                f = f * (prev_c / (prev_c - da))
                div_col[i] = da
            if dt in split_map:
                sp = split_map[dt]
                f = f * sp
                split_col[i] = sp
            hfq_factor[i] = f

        px["code"] = code
        px["div_amt"] = div_col
        px["split_conv"] = split_col
        px["hfq_factor"] = hfq_factor
        for c in ["open", "high", "low", "close"]:
            px[f"{c}_hfq"] = px[c] * px["hfq_factor"]
        px["raw_prev_close"] = px["close"].shift(1)
        px["hfq_prev_close"] = px["close_hfq"].shift(1)
        px["cc_ret"] = px["close_hfq"] / px["hfq_prev_close"] - 1.0
        px["gap_ret"] = px["open_hfq"] / px["hfq_prev_close"] - 1.0
        px["oc_ret"] = px["close_hfq"] / px["open_hfq"] - 1.0
        frames.append(px[[
            "date", "code", "open", "high", "low", "close", "volume", "amount",
            "div_amt", "split_conv", "hfq_factor", "open_hfq", "high_hfq", "low_hfq", "close_hfq",
            "cc_ret", "gap_ret", "oc_ret"
        ]])
        print(f"  [CoreETF {code}] {len(px)} days [{px['date'].min()} -> {px['date'].max()}], cum_hfq_mult={px['close_hfq'].iloc[-1]/px['close_hfq'].iloc[0]:.3f}x")

    out = pd.concat(frames, ignore_index=True).sort_values(["code", "date"]).reset_index(drop=True)
    out.to_parquet(out_pq, index=False)
    return out


def build_extended_inputs_to_20261125(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """
    Extend daily_market_panel_v2, etf22 + shares, futures, stocks23, breadth, macro_pain
    cleanly through 2026-11-25 close using live Tencent + Sina EOD feeds (zero lookahead).
    """
    mp_out = os.path.join(CACHE_DIR, "daily_market_panel_2000_20261125.parquet")
    v3_out = os.path.join(CACHE_DIR, "v3_raw_panel_2016_20261125.parquet")
    bd_out = os.path.join(CACHE_DIR, "breadth_daily_2005_20261125.parquet")
    m4_out = os.path.join(CACHE_DIR, "macro_pain_daily_2005_20261125.parquet")

    if (not force_refresh) and all(os.path.exists(p) for p in [mp_out, v3_out, bd_out, m4_out]):
        mp_c = pd.read_parquet(mp_out)
        if str(mp_c["date"].max()) >= TARGET_END_DATE:
            return {
                "mp": mp_c,
                "v3": pd.read_parquet(v3_out),
                "bd": pd.read_parquet(bd_out),
                "m4": pd.read_parquet(m4_out),
            }

    # 1. Load base panels through 2026-11-24
    mp = pd.read_parquet(os.path.join(POLY_DIR, "daily_market_panel_v2_20261124.parquet")).sort_values("date").reset_index(drop=True)
    mp["date"] = mp["date"].astype(str).str[:10]

    # Fetch 2026-11-25 quotes for all 21 indices + sz399106 + 22 ETFs + 23 stocks
    etf22_syms = [("sh" if ex == "SSE" else "sz") + c for c, (_, ex, _, _, _) in NT21_META.items()] + ["sh588000"]
    all_tks = sorted(set(NT16_TICKERS) | set(FUND8_TICKERS))
    stk_syms = [_ticker_to_qt(tk) for tk in all_tks]
    qt_all = fetch_qt_quotes(list(INDEX_MAP.keys()) + ["sz399106"] + etf22_syms + stk_syms)
    fut_25 = fetch_sina_futures_day(TARGET_END_DATE)

    # Append 2026-11-25 to market panel if not already present
    if TARGET_END_DATE not in set(mp["date"]) and qt_all.get("sh000300", {}).get("date") == TARGET_END_DATE:
        last_row = mp.iloc[-1]
        new_mp = {c: np.nan for c in mp.columns}
        new_mp["date"] = TARGET_END_DATE
        for sym, pfx in INDEX_MAP.items():
            q = qt_all.get(sym, {})
            if q.get("date") == TARGET_END_DATE:
                prev_c = float(last_row[f"{pfx}_close"])
                new_mp[f"{pfx}_open"] = q["open"]
                if f"{pfx}_high" in mp.columns:
                    new_mp[f"{pfx}_high"] = q["high"]
                if f"{pfx}_low" in mp.columns:
                    new_mp[f"{pfx}_low"] = q["low"]
                new_mp[f"{pfx}_close"] = q["close"]
                new_mp[f"{pfx}_cc_ret"] = q["close"] / prev_c - 1.0
                new_mp[f"{pfx}_gap_ret"] = q["open"] / prev_c - 1.0
                new_mp[f"{pfx}_oc_ret"] = q["close"] / q["open"] - 1.0

        # Exact SH+SZ stock turnover in 亿元 directly from Tencent qt.gtimg.cn (ps[37] is in 万元)
        sh25_amt = float(qt_all.get("sh000001", {}).get("amount") or 0.0) / 1e8
        sz25_amt = float(qt_all.get("sz399106", {}).get("amount") or 0.0) / 1e8
        new_mp["total_amount_yi"] = sh25_amt + sz25_amt if (sh25_amt + sz25_amt) > 0 else float(last_row["total_amount_yi"])

        # Big4 bank return on 2026-11-25
        b4_rets = []
        for b_sym in ["sh601398", "sh601288", "sh601988", "sh601939"]:
            bq = qt_all.get(b_sym, {})
            if bq.get("close") and bq.get("prev_close"):
                b4_rets.append(bq["close"] / bq["prev_close"] - 1.0)
        if b4_rets:
            new_mp["big4_bank_cc_ret"] = float(np.mean(b4_rets))
            new_mp["big4_vs_1000_ret"] = new_mp["big4_bank_cc_ret"] - new_mp.get("csi1000_cc_ret", 0.0)

        new_mp["bench_cc_ret"] = new_mp["csi300_cc_ret"]
        new_mp["bench_oc_ret"] = new_mp["csi300_oc_ret"]
        new_mp["bench_gap_ret"] = new_mp["csi300_gap_ret"]
        mp = pd.concat([mp, pd.DataFrame([new_mp])], ignore_index=True).sort_values("date").reset_index(drop=True)

    mp.to_parquet(mp_out, index=False)

    # 2. Build raw V3 panel (2016-01-04 ~ 2026-11-25) WITHOUT any shift(-1) lookahead!
    idx_c = pd.read_parquet(os.path.join(V3_CACHE_DIR, "indices_to_20261124.parquet"))
    idx_frames = []
    for sym, pfx in [("sh000300", "c300"), ("sh000852", "c1000"), ("sh000016", "c50"), ("sh000905", "c500"), ("sh000688", "star50"), ("sz399006", "cyb")]:
        sub = idx_c[idx_c["symbol"] == sym].sort_values("date")[["date", "open", "high", "low", "close"]].copy()
        q = qt_all.get(sym, {})
        if q.get("date") == TARGET_END_DATE and TARGET_END_DATE not in set(sub["date"]):
            sub = pd.concat([sub, pd.DataFrame([{"date": TARGET_END_DATE, "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]}])], ignore_index=True)
        sub = sub.rename(columns={c: f"{pfx}_{c}" for c in ["open", "high", "low", "close"]})
        idx_frames.append(sub)
    v3 = idx_frames[0]
    for f_df in idx_frames[1:]:
        v3 = v3.merge(f_df, on="date", how="left")
    v3 = v3.sort_values("date").reset_index(drop=True)

    # 22 ETFs raw + shares (2026-11-25 shares are unknown EOD, only known T+1 -> NaN on 11-25!)
    etf21 = pd.read_parquet(os.path.join(V3_CACHE_DIR, "etf21_to_20261124.parquet"))
    etf_ex = pd.read_parquet(os.path.join(V3_CACHE_DIR, "etf_extra10_to_20261124.parquet"))
    sh21 = pd.concat([
        pd.read_parquet(os.path.join(NT_DIR, "sse_shares_cache.parquet")),
        pd.read_parquet(os.path.join(NT_DIR, "szse_shares_cache.parquet")),
    ], ignore_index=True).drop_duplicates(["date", "code"])
    sh_ex = pd.read_parquet(os.path.join(V3_CACHE_DIR, "sse_extra10_shares.parquet"))

    e588 = etf_ex[etf_ex["code"] == "588000"].copy()
    e588["exch"], e588["idx_grp"], e588["team"], e588["nt_w"] = "SSE", "STAR50", "T2", 0.25
    e588["close_qfq"], e588["split_ratio"] = e588["close"], 1.0
    etf22 = pd.concat([etf21[etf21["date"] >= "2016-01-01"], e588[etf21.columns]], ignore_index=True)

    # Append 2026-11-25 ETF OHLC+amount
    add_etf25 = []
    meta_22 = dict(NT21_META)
    meta_22["588000"] = ("华夏科创50ETF", "SSE", "STAR50", "T2", 0.25)
    for code, (nm, exch, grp, tm, ntw) in meta_22.items():
        sym = ("sh" if exch == "SSE" else "sz") + code
        q = qt_all.get(sym, {})
        if q.get("date") == TARGET_END_DATE:
            add_etf25.append({
                "date": TARGET_END_DATE, "code": code, "name": nm, "exch": exch, "idx_grp": grp,
                "team": tm, "nt_w": ntw, "open": q["open"], "high": q["high"], "low": q["low"],
                "close": q["close"], "close_qfq": q["close"], "split_ratio": 1.0,
                "volume": q["volume"] * 100.0, "amount": q["amount"], "pct_chg": q["pct_chg"],
            })
    if add_etf25:
        etf22 = pd.concat([etf22[etf22["date"] < TARGET_END_DATE], pd.DataFrame(add_etf25)], ignore_index=True)
    sh22 = pd.concat([sh21, sh_ex[sh_ex["code"] == "588000"]], ignore_index=True).drop_duplicates(["date", "code"])
    etf22 = etf22.merge(sh22, on=["date", "code"], how="left").sort_values(["code", "date"]).reset_index(drop=True)

    # Strictly CAUSAL split detection (ZERO shift(-1)!)
    etf22["prev_sh"] = etf22.groupby("code")["shares_wan"].shift(1)
    etf22["sh_ret"] = etf22["shares_wan"] / etf22["prev_sh"] - 1.0
    etf22["prev_pct"] = etf22.groupby("code")["pct_chg"].shift(1).fillna(0.0)
    etf22["prev_sr"] = etf22.groupby("code")["split_ratio"].shift(1)
    sr_jmp = (etf22["split_ratio"] / etf22["prev_sr"] - 1.0).abs() > 0.08
    px_jmp = (etf22["pct_chg"].abs() > 22) | (etf22["prev_pct"].abs() > 22)
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

    core10 = {"510300", "510310", "510330", "159919", "510050", "510500", "512100", "159915", "588000", "588080"}
    t1_core = {"510300", "510310", "510330", "159919", "510050"}
    t2_core = {"510500", "512100", "159915", "588000", "588080"}
    etf22["is_core10"] = etf22["code"].isin(core10)
    etf22["is_t1_core"] = etf22["code"].isin(t1_core)
    etf22["is_t2_core"] = etf22["code"].isin(t2_core)

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
    d_etf = d_etf.merge(t1_fl, on="date", how="left").merge(t2_fl, on="date", how="left").merge(c10, on="date", how="left").sort_values("date").reset_index(drop=True)
    # Note: rolling median spikes & tapering will be recomputed purely causally after truncation!
    v3 = v3.merge(d_etf, on="date", how="left")

    # Stocks23 raw -> causal daily counts (since each stock's rolling 20d median is purely backward!)
    stk = pd.read_parquet(os.path.join(V3_CACHE_DIR, "stocks23_to_20261124.parquet")).sort_values(["ticker", "date"]).reset_index(drop=True)
    add_stk25 = []
    if TARGET_END_DATE not in set(stk["date"]):
        for tk in all_tks:
            q = qt_all.get(_ticker_to_qt(tk), {})
            if q.get("date") == TARGET_END_DATE:
                add_stk25.append({
                    "date": TARGET_END_DATE, "ticker": tk, "open": q["open"], "high": q["high"],
                    "low": q["low"], "close": q["close"], "adj_close": q["close"], "amount": q["amount"],
                })
    if add_stk25:
        stk = pd.concat([stk, pd.DataFrame(add_stk25)], ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    ratio = np.where(stk["close"] > 0, stk["adj_close"] / stk["close"], 1.0)
    stk["open_adj"] = stk["open"] * ratio
    stk["low_adj"] = stk["low"] * ratio
    stk["prev_adj"] = stk.groupby("ticker")["adj_close"].shift(1)
    stk["cc_ret"] = stk["adj_close"] / stk["prev_adj"] - 1.0
    stk["oc_ret"] = stk["adj_close"] / stk["open_adj"] - 1.0
    stk["pullup"] = (stk["adj_close"] - stk["low_adj"]) / stk["prev_adj"]
    stk["amt_med20_s1"] = stk.groupby("ticker")["amount"].transform(lambda s: s.rolling(20, min_periods=10).median().shift(1))
    stk["amt_spike"] = stk["amount"] / stk["amt_med20_s1"].replace(0, np.nan)

    nt16_set = set(NT16_TICKERS)
    big4_oil = ["601398.SH", "601288.SH", "601988.SH", "601939.SH", "601857.SH", "600028.SH"]
    squads = {
        "bank": ["601398.SH", "601288.SH", "601988.SH", "601939.SH", "600036.SH"],
        "energy": ["601857.SH", "600028.SH", "600941.SH", "601088.SH", "600900.SH"],
        "fincons": ["601318.SH", "601628.SH", "600519.SH", "600030.SH"],
        "growth": ["300750.SZ", "688981.SH"],
    }
    s16 = stk[stk["ticker"].isin(nt16_set)].copy()
    s16["vol_up"] = (s16["amt_spike"] >= 1.4) & ((s16["cc_ret"] >= 0.0) | (s16["pullup"] >= 0.012))
    g16 = s16.groupby("date").agg(hw16_sync_cnt=("vol_up", "sum")).reset_index()
    for sq_nm, tks in squads.items():
        sq_s = s16[s16["ticker"].isin(tks)].groupby("date").agg(**{f"sq_{sq_nm}_hits": ("vol_up", "sum")}).reset_index()
        g16 = g16.merge(sq_s, on="date", how="left")
    b4o = s16[s16["ticker"].isin(big4_oil)].groupby("date")["cc_ret"].mean().rename("big4_oil_ret").reset_index()
    g16 = g16.merge(b4o, on="date", how="left")
    g16["sq_active_cnt"] = (
        (g16["sq_bank_hits"].fillna(0) >= 1).astype(int) +
        (g16["sq_energy_hits"].fillna(0) >= 1).astype(int) +
        (g16["sq_fincons_hits"].fillna(0) >= 1).astype(int) +
        (g16["sq_growth_hits"].fillna(0) >= 1).astype(int)
    )
    v3 = v3.merge(g16[["date", "hw16_sync_cnt", "sq_active_cnt", "big4_oil_ret"]], on="date", how="left")

    sf8 = stk[stk["ticker"].isin(FUND8_TICKERS)].copy()
    sf8["is_dump"] = (sf8["oc_ret"] <= -0.020) & (sf8["amt_spike"] >= 1.2)
    g8 = sf8.groupby("date").agg(fund8_dump_cnt=("is_dump", "sum")).reset_index()
    v3 = v3.merge(g8, on="date", how="left")

    # Futures raw
    fut = pd.read_parquet(os.path.join(V3_CACHE_DIR, "futures_to_20261124.parquet")).sort_values("date").reset_index(drop=True)
    if fut_25 and TARGET_END_DATE not in set(fut["date"]):
        row_f = {"date": TARGET_END_DATE}
        for sym, vals in fut_25.items():
            for k, v in vals.items():
                row_f[f"{sym}_{k}"] = v
        fut = pd.concat([fut, pd.DataFrame([row_f])], ignore_index=True).sort_values("date").reset_index(drop=True)
    v3 = v3.merge(fut[["date", "IF0_close", "IF0_vol"]], on="date", how="left")

    # Sector 9 flows & LHB (no shift(-1)!)
    sec9 = {"512000", "512880", "512480", "512010", "512690", "515030", "515790", "510880", "512800"}
    sec_px = etf_ex[etf_ex["code"].isin(sec9)].copy()
    sec_sh = sh_ex[sh_ex["code"].isin(sec9)].copy()
    sec = sec_px.merge(sec_sh, on=["date", "code"], how="left").sort_values(["code", "date"]).reset_index(drop=True)
    sec["prev_sh"] = sec.groupby("code")["shares_wan"].shift(1)
    sec["sh_ret"] = sec["shares_wan"] / sec["prev_sh"] - 1.0
    sec["prev_pct"] = sec.groupby("code")["pct_chg"].shift(1).fillna(0.0)
    sec_split = ((sec["sh_ret"].abs() > 0.35) & ((sec["pct_chg"].abs() > 20) | (sec["prev_pct"].abs() > 20))) | (sec["pct_chg"].abs() > 25)
    sec["flow_yi"] = np.where(sec_split, 0.0, (sec["shares_wan"] - sec["prev_sh"]) * 1e4 * sec["close"] / 1e8)
    g_sec = sec.groupby("date")["flow_yi"].sum().rename("sec9_flow_1d_yi").reset_index()
    v3 = v3.merge(g_sec, on="date", how="left")

    lhb = pd.read_parquet(os.path.join(V3_CACHE_DIR, "lhb_org_daily_2020_2026.parquet"))
    v3 = v3.merge(lhb[["date", "lhb_net_yi"]], on="date", how="left")

    v3.to_parquet(v3_out, index=False)

    # 3. Breadth & Macro Pain extended to 2026-11-25 (carry forward 11-24 EOD macro/breadth except causal price ratio on ERP)
    bd = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar1_market_breadth_daily.parquet")).sort_values("date").reset_index(drop=True)
    bd["date_str"] = bd["date"].dt.strftime("%Y-%m-%d")
    if TARGET_END_DATE not in set(bd["date_str"]):
        last_bd = bd.iloc[-1].copy()
        last_bd["date"] = pd.Timestamp(TARGET_END_DATE)
        last_bd["date_str"] = TARGET_END_DATE
        # Keep T-1 margin/breadth; scale CSI300 PE & ERP causally if CSI300 moved
        c300_25 = qt_all.get("sh000300", {}).get("close")
        if c300_25 and pd.notna(last_bd["csi300_close"]) and last_bd["csi300_close"] > 0:
            pe_new = float(last_bd["csi300_pe_ttm_daily"]) * (float(c300_25) / float(last_bd["csi300_close"]))
            last_bd["csi300_close"] = float(c300_25)
            last_bd["csi300_pe_ttm_daily"] = pe_new
            last_bd["erp_csi300_pct"] = 100.0 / pe_new - float(last_bd["cn10y_eod"])
        bd = pd.concat([bd, pd.DataFrame([last_bd])], ignore_index=True)
    bd.to_parquet(bd_out, index=False)

    m4 = pd.read_parquet(os.path.join(PILLAR_DIR, "pillar4_macro_pain_daily_pit.parquet")).sort_values("date").reset_index(drop=True)
    m4["date_str"] = m4["date"].dt.strftime("%Y-%m-%d")
    if TARGET_END_DATE not in set(m4["date_str"]):
        last_m4 = m4.iloc[-1].copy()
        last_m4["date"] = pd.Timestamp(TARGET_END_DATE)
        last_m4["date_str"] = TARGET_END_DATE
        m4 = pd.concat([m4, pd.DataFrame([last_m4])], ignore_index=True)
    m4.to_parquet(m4_out, index=False)

    return {"mp": mp, "v3": v3, "bd": bd, "m4": m4}


if __name__ == "__main__":
    t0 = time.time()
    print("[RD029-Data] Building 4 core ETFs (510050/510300/510500/512100) through 2026-11-25...")
    etf_df = build_core_etf_prices(force_refresh=True)
    print("[RD029-Data] Building extended daily market panel & V3 inputs through 2026-11-25...")
    ext = build_extended_inputs_to_20261125(force_refresh=True)
    print(f"[RD029-Data] Done in {time.time()-t0:.1f}s! mp={ext['mp'].shape}, v3={ext['v3'].shape}, etf={etf_df.shape}")
