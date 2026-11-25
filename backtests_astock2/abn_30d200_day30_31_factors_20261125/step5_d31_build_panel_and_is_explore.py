#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 5: Enrich 30d-200% Hold Events with D31 09:25 Features, D30 Post-Close LHB/KPL/Notices,
Forward D31..D50 Daily Bars, Conservative Intraday Breakout Buy Points (BP2a/BP2b),
and Run STRICT IS-ONLY (2021-2023) Exploration for Scorecards & 7 Exit Trees.
"""

import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

P = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/abn_30d200_day30_31_factors_20261125")
sys.path.insert(0, str(P))

from step1_extract_events_and_returns import A_DAILY, A_DELISTED, CNINFO_DB, KPL_JSONL, SIM, load_indices
from step2_build_pit_factors import NON_THEME, load_lhb_clean

FEE_30 = 0.0030
TP_BUF = 0.0030


def load_full_daily_for_d31():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-09-01")
    d1 = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d2 = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "60", "300", "301", "688", "689"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    g = df.groupby("c6")
    df["pre_adj"] = g["adj_close"].shift(1)
    df["pre_raw"] = g["close"].shift(1)
    df["pre_qfq"] = g["qfq_factor"].shift(1)
    df["pct"] = df["adj_close"] / df["pre_adj"] - 1.0
    df["o_pct"] = (df["open"] * (df["adj_close"] / df["close"])) / df["pre_adj"] - 1.0
    df["is_20"] = df["c6"].str.startswith(("300", "301", "688", "689"))

    lim_ex = np.where(df["is_20"], 0.20, 0.10)
    lim_thr = np.where(df["is_20"], 0.194, 0.094)
    no_xd = np.abs(df["qfq_factor"] / np.where(df["pre_qfq"] > 0, df["pre_qfq"], np.nan) - 1.0) < 1e-6
    ratio = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    ref_c = np.where(no_xd, df["pre_raw"], df["pre_adj"] / np.where(ratio > 0, ratio, 1.0))

    df["zt_px_raw"] = np.floor(ref_c * (1.0 + lim_ex) * 100.0 + 0.5) / 100.0
    df["dt_px_raw"] = np.floor(ref_c * (1.0 - lim_ex) * 100.0 + 0.5) / 100.0
    df["zt_px_adj"] = df["zt_px_raw"] * ratio
    df["dt_px_adj"] = df["dt_px_raw"] * ratio
    df["ao"] = df["open"] * ratio
    df["ah"] = df["high"] * ratio
    df["al"] = df["low"] * ratio
    df["ac"] = df["adj_close"]
    df["ma5"] = g["adj_close"].transform(lambda s: s.rolling(5, min_periods=3).mean())

    df["is_zt"] = (df["close"] >= df["zt_px_raw"] - 0.011) & (df["pct"] >= lim_thr) & (df["pre_adj"] > 0)
    df["is_dt"] = (df["close"] <= df["dt_px_raw"] + 0.011) & (df["pct"] <= -lim_thr) & (df["pre_adj"] > 0)
    df["is_yizi_zt"] = df["is_zt"] & (df["open"] >= df["zt_px_raw"] - 0.011) & (df["low"] >= df["zt_px_raw"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_px_raw"] + 0.011) & (df["high"] <= df["dt_px_raw"] + 0.011)
    df["open_is_dt"] = (df["open"] <= df["dt_px_raw"] + 0.011) & (df["o_pct"] <= -lim_thr) & (df["pre_adj"] > 0)
    df["open_is_zt"] = (df["open"] >= df["zt_px_raw"] - 0.011) & (df["o_pct"] >= lim_thr) & (df["pre_adj"] > 0)

    # Market-wide 09:25 open auction breadth & daily median mcap/amount for causal rolling normalization
    df["mcap_yi"] = df["close"] * df["oshare"] / 1e8
    dg = df.groupby("dt_str")
    mkt_open_zt10 = df[~df["is_20"]].groupby("dt_str")["open_is_zt"].sum().to_dict()
    mkt_open_zt20 = df[df["is_20"]].groupby("dt_str")["open_is_zt"].sum().to_dict()
    mkt_med_mcap = dg["mcap_yi"].median().sort_index()
    mkt_amt_tril = (dg["amount"].sum() / 1e12).sort_index()
    mkt_amt_ma250 = mkt_amt_tril.rolling(250, min_periods=60).mean().shift(1).to_dict()
    mkt_mcap_ma250 = mkt_med_mcap.rolling(250, min_periods=60).mean().shift(1).to_dict()

    print(f"[FullDaily] Built in {time.time()-t0:.1f}s")
    return df, mkt_open_zt10, mkt_open_zt20, mkt_amt_ma250, mkt_mcap_ma250


def load_kpl_d30_ext():
    """Extract D30 KPL membership and same-day low-assist / zt count (known post-close D30, PIT for D31 09:25)."""
    plate_stocks = defaultdict(lambda: defaultdict(set))
    stock_plates = defaultdict(lambda: defaultdict(list))
    with open(KPL_JSONL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt = obj.get("date", "")
            if dt < "2020-09-01" or dt > "2026-11-24":
                continue
            for pl in obj.get("plates", []):
                pname = str(pl.get("plate", "")).strip()
                if not pname or pname in NON_THEME:
                    continue
                for st in pl.get("stocks", []):
                    c6 = str(st.get("code", ""))[:6].zfill(6) if isinstance(st, dict) else (str(st[0])[:6].zfill(6) if isinstance(st, list) and st else "")
                    if c6:
                        plate_stocks[dt][pname].add(c6)
                        stock_plates[c6][dt].append(pname)
    return plate_stocks, stock_plates


def load_notices_until_d31_0925(target_codes: set):
    conn = sqlite3.connect(f"file:{CNINFO_DB}?mode=ro", uri=True)
    ph = ",".join("?" for _ in target_codes)
    q = f"""
    SELECT sec_code, pub_datetime_cst, trade_date_avail, title
    FROM notices
    WHERE sec_code IN ({ph})
      AND (title LIKE '%异常波动%' OR title LIKE '%停牌核查%' OR title LIKE '%风险提示%'
           OR title LIKE '%问询函%' OR title LIKE '%关注函%' OR title LIKE '%监管函%' OR title LIKE '%立案%')
    """
    out = defaultdict(list)
    for c6, pub_dt, avail_dt, title in conn.execute(q, list(target_codes)):
        c6 = str(c6)[:6].zfill(6)
        t = str(title or "")
        # Available at D31 09:25 if pub_datetime_cst <= D31 09:25:00
        out[c6].append((str(pub_dt), str(avail_dt), t))
    conn.close()
    return out


def sim_exit_tree(df_ev: pd.DataFrame, exit_mode: str, cfg: dict = None, fee: float = FEE_30, tp_buf: float = TP_BUF,
                  entry_mode: str = "d31_open") -> pd.DataFrame:
    """
    Simulate 7+ physical exit strategies from D31 entry (D31 open or BP2a/BP2b intraday breakout).
    k=1 is D31, k=2 is D32, ..., k=20 is D50.
    All limit-TP exits include +tp_buf (+0.30%) penetration requirement; limit-down deferrals go to next sellable open/close.
    """
    cfg = cfg or {}
    rows = []
    for r in df_ev.itertuples(index=False):
        if entry_mode == "d31_open":
            b_px = float(r.f1_ao)
            if not r.d31_buyable or not (b_px > 0):
                continue
        elif entry_mode == "bp2a_red":
            # D31 low open (<0%) + intraday cross >= D30_close * 1.005 (+0.30% buf)
            if not r.d31_buyable or not r.bp2a_hit:
                continue
            b_px = float(r.bp2a_px_adj)
        elif entry_mode == "bp2b_open2":
            # D31 low open (<0%) + intraday cross >= D31_open * 1.02 (+0.30% buf)
            if not r.d31_buyable or not r.bp2b_hit:
                continue
            b_px = float(r.bp2b_px_adj)
        else:
            continue

        f1_ac = float(r.f1_ac)
        f1_ao = float(r.f1_ao)
        f1_zt = bool(r.f1_zt)
        f1_body = float(r.f1_body)
        f1_clv = float(r.f1_clv)
        gap_abs = abs(float(r.d31_gap)) / 100.0
        max_k = int(r.avail_k)

        if max_k < 2:
            continue

        sell_k = 2
        s_px = np.nan
        sell_at_open = False
        reason = exit_mode

        def try_tp(k, tp_r, ref_px):
            if k > max_k:
                return False, np.nan, ""
            ao = float(getattr(r, f"f{k}_ao"))
            ah = float(getattr(r, f"f{k}_ah"))
            sellable = bool(getattr(r, f"f{k}_sellable"))
            open_dt = bool(getattr(r, f"f{k}_open_dt"))
            zt_adj = float(getattr(r, f"f{k}_zt_adj"))
            if not sellable or np.isnan(ao) or np.isnan(ah):
                return False, np.nan, ""
            tp_px = ref_px * (1.0 + tp_r)
            if ao >= tp_px and not open_dt:
                return True, ao, "gap_tp"
            need_ah = min(tp_px * (1.0 + tp_buf), zt_adj - 1e-4)
            if ah >= need_ah:
                return True, tp_px, "intra_tp"
            return False, np.nan, ""

        def defer_close(k_target):
            k = min(k_target, max_k)
            while k < max_k and bool(getattr(r, f"f{k}_yz_dt")):
                k += 1
            if bool(getattr(r, f"f{k}_yz_dt")):
                return k, float(getattr(r, f"f{k}_ac"))
            if bool(getattr(r, f"f{k}_is_dt")) and k < max_k:
                k2 = k + 1
                while k2 < max_k and bool(getattr(r, f"f{k2}_yz_dt")):
                    k2 += 1
                px = float(getattr(r, f"f{k2}_ao")) if not bool(getattr(r, f"f{k2}_yz_dt")) else float(getattr(r, f"f{k2}_ac"))
                return k2, px
            return k, float(getattr(r, f"f{k}_ac"))

        def defer_open(k_target):
            k = min(k_target, max_k)
            while k < max_k and bool(getattr(r, f"f{k}_yz_dt")):
                k += 1
            px = float(getattr(r, f"f{k}_ao")) if not bool(getattr(r, f"f{k}_yz_dt")) else float(getattr(r, f"f{k}_ac"))
            return k, px

        # ---- 7 EXIT MODES ----
        if exit_mode == "E0_Fixed_D32c":
            sell_k, s_px = defer_close(2)
        elif exit_mode == "E0_Fixed_D35c":
            sell_k, s_px = defer_close(min(5, max_k))
        elif exit_mode.startswith("E1_D32_TP"):
            tp_r = float(cfg.get("tp", 0.08))
            hit, px_h, r_h = try_tp(2, tp_r, f1_ac)
            if hit:
                sell_k, s_px, reason = 2, px_h, f"E1_{r_h}"
            else:
                sell_k, s_px = defer_close(2)
                reason = "E1_d32_close"
        elif exit_mode == "E2_ZT_Ride_Break":
            if f1_zt:
                k = 2
                while k < max_k and bool(getattr(r, f"f{k}_zt")):
                    k += 1
                sell_k, s_px = defer_close(k)
                reason = "E2_zt_break"
            else:
                sell_k, s_px = defer_close(2)
                reason = "E2_nonzt_d32c"
        elif exit_mode == "E3_ZT_Ride_YangImm":
            tp_r = float(cfg.get("tp", 0.08))
            if f1_zt:
                k = 2
                while k < max_k and bool(getattr(r, f"f{k}_zt")):
                    k += 1
                # First non-ZT day k: if true yang (ac > ao and ac > pre_ac), immune 1 extra day to k+1 close
                if k < max_k and float(getattr(r, f"f{k}_ac")) > float(getattr(r, f"f{k}_ao")) and float(getattr(r, f"f{k}_ac")) > float(getattr(r, f"f{k-1}_ac")):
                    sell_k, s_px = defer_close(k + 1)
                    reason = "E3_yang_imm"
                else:
                    sell_k, s_px = defer_close(k)
                    reason = "E3_zt_break"
            elif f1_body <= -0.02 or f1_ac < f1_ao:
                # D31 closed weak/yin -> exit D32 open immediately!
                sell_k, s_px = defer_open(2)
                reason = "E3_yin_d32o"
            else:
                hit, px_h, r_h = try_tp(2, tp_r, f1_ac)
                if hit:
                    sell_k, s_px, reason = 2, px_h, f"E3_{r_h}"
                else:
                    sell_k, s_px = defer_close(2)
                    reason = "E3_yang_d32c"
        elif exit_mode == "E4_4Branch_Tree":
            b2_body = float(cfg.get("b2_body", 0.05))
            b2_clv = float(cfg.get("b2_clv", 0.65))
            b2_tp = float(cfg.get("b2_tp", 0.10))
            b3_k = float(cfg.get("b3_k", 1.5))
            b4_body = float(cfg.get("b4_body", -0.04))
            if f1_zt:
                k = 2
                while k < max_k and bool(getattr(r, f"f{k}_zt")):
                    k += 1
                sell_k, s_px = defer_close(k)
                reason = "E4_B1_zt"
            elif f1_body <= b4_body or bool(r.f1_is_dt):
                sell_k, s_px = defer_close(2)
                reason = "E4_B4_d32c"
            elif f1_body >= b2_body and f1_clv >= b2_clv:
                hit, px_h, r_h = try_tp(2, b2_tp, f1_ac)
                if hit:
                    sell_k, s_px, reason = 2, px_h, f"E4_B2_{r_h}"
                elif max_k >= 3:
                    if bool(getattr(r, "f2_zt")):
                        k = 3
                        while k < max_k and bool(getattr(r, f"f{k}_zt")):
                            k += 1
                        sell_k, s_px = defer_close(k)
                        reason = "E4_B2_d32zt"
                    else:
                        hit3, px3, r3 = try_tp(3, b2_tp, float(getattr(r, "f2_ac")))
                        if hit3:
                            sell_k, s_px, reason = 3, px3, f"E4_B2_d33_{r3}"
                        else:
                            sell_k, s_px = defer_close(3)
                            reason = "E4_B2_d33c"
                else:
                    sell_k, s_px = defer_close(2)
            else:
                tp3 = max(0.06, min(0.14, gap_abs * b3_k))
                hit, px_h, r_h = try_tp(2, tp3, f1_ac)
                if hit:
                    sell_k, s_px, reason = 2, px_h, f"E4_B3_{r_h}"
                else:
                    sell_k, s_px = defer_close(2)
                    reason = "E4_B3_d32c"
        elif exit_mode == "E5_Trail_MA5_or_DD8":
            dd_lim = float(cfg.get("dd_lim", 0.08))
            max_h = min(int(cfg.get("max_h", 15)), max_k)
            peak_c = f1_ac
            triggered = False
            for k in range(2, max_h + 1):
                c_k = float(getattr(r, f"f{k}_ac"))
                ma5_k = float(getattr(r, f"f{k}_ma5"))
                peak_c = max(peak_c, float(getattr(r, f"f{k}_ah")))
                if c_k < ma5_k or (c_k / peak_c - 1.0 <= -dd_lim):
                    # Next day open sell (or close if k == max_k)
                    if k < max_k:
                        sell_k, s_px = defer_open(k + 1)
                        reason = "E5_trail_next_open"
                    else:
                        sell_k, s_px = defer_close(k)
                        reason = "E5_trail_last_close"
                    triggered = True
                    break
            if not triggered:
                sell_k, s_px = defer_close(max_h)
                reason = "E5_max_hold"
        elif exit_mode == "E6_Adaptive_TP_3D":
            tp2 = float(cfg.get("tp2", 0.10))
            tp3 = float(cfg.get("tp3", 0.06))
            tp4 = float(cfg.get("tp4", 0.03))
            # Profit target relative to actual buy price b_px: +10% on D32, +6% on D33, +3% on D34 else D34 close
            hit2, px2, _ = try_tp(2, tp2, b_px)
            if hit2:
                sell_k, s_px, reason = 2, px2, "E6_d32_tp"
            elif max_k >= 3:
                hit3, px3, _ = try_tp(3, tp3, b_px)
                if hit3:
                    sell_k, s_px, reason = 3, px3, "E6_d33_tp"
                elif max_k >= 4:
                    hit4, px4, _ = try_tp(4, tp4, b_px)
                    if hit4:
                        sell_k, s_px, reason = 4, px4, "E6_d34_tp"
                    else:
                        sell_k, s_px = defer_close(4)
                        reason = "E6_d34_close"
                else:
                    sell_k, s_px = defer_close(3)
            else:
                sell_k, s_px = defer_close(2)

        if np.isnan(s_px) or s_px <= 0:
            continue
        exit_dt = getattr(r, f"f{sell_k}_date")
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({
            "c6": r.c6, "name": r.name, "is_20": bool(r.is_20),
            "in_peak_pool": bool(r.in_peak_pool), "in_end_pool": bool(r.in_end_pool),
            "d30_date": r.d30_date, "buy_date": r.d31_date, "exit_date": exit_dt,
            "yr": int(r.d31_yr), "end_dev30": float(r.end_dev30), "d31_gap": float(r.d31_gap),
            "buy_px": b_px, "exit_px": s_px, "gross_ret": gross, "net_ret": net,
            "hold_bars": sell_k, "exit_reason": reason,
        })
    return pd.DataFrame(rows)


def main():
    t_start = time.time()
    eh = pd.read_parquet(P / "events_hold_48factors.parquet")
    df_all, mkt_op10, mkt_op20, mkt_amt_ma250, mkt_mcap_ma250 = load_full_daily_for_d31()
    plate_stocks, stock_plates = load_kpl_d30_ext()
    notices_map = load_notices_until_d31_0925(set(eh["c6"].unique()))
    lhb_map = load_lhb_clean()

    stock_panels = {c6: grp.reset_index(drop=True) for c6, grp in df_all[df_all["c6"].isin(set(eh["c6"]))].groupby("c6", sort=False)}
    del df_all

    # Enrich each event with D31..D50 forward bars + D31 09:25 PIT features + BP2a/BP2b triggers
    ext_rows = []
    for r in eh.itertuples(index=False):
        c6 = r.c6
        sp = stock_panels[c6]
        i = int(r.d30_idx)
        n = len(sp)
        d30_dt = r.d30_date
        d31_dt = r.d31_date

        # D30 candle features
        ao30, ah30, al30, ac30 = float(sp["ao"].iloc[i]), float(sp["ah"].iloc[i]), float(sp["al"].iloc[i]), float(sp["ac"].iloc[i])
        pre30 = float(sp["pre_adj"].iloc[i])
        d30_clv = (2.0 * ac30 - ah30 - al30) / (ah30 - al30) if (ah30 - al30) > 1e-9 else 0.5
        d30_body = (ac30 - ao30) / pre30 * 100.0 if pre30 > 0 else 0.0

        # D30 evening -> D31 09:25 notice check
        reg_abn_d31_0925 = 0
        reg_inq_d31_0925 = 0
        for pub_dt, avail_dt, title in notices_map.get(c6, []):
            if avail_dt <= d31_dt and pub_dt <= f"{d31_dt} 09:25:00":
                if any(w in title for w in ("异常波动", "停牌核查", "严重异常波动", "交易风险提示")):
                    reg_abn_d31_0925 += 1
                if any(w in title for w in ("问询函", "关注函", "监管函", "立案")) and "回复" not in title:
                    reg_inq_d31_0925 = 1

        # D30 LHB (PIT for D31 09:25!)
        rec_l30 = lhb_map.get(c6, {}).get(d30_dt)
        d30_lhb_yz_net = float(rec_l30.yz_net) if rec_l30 is not None else 0.0

        # D30 KPL low assist (PIT for D31 09:25!)
        d30_plates = stock_plates.get(c6, {}).get(d30_dt, [])
        d30_kpl_zt_cnt = max((len(plate_stocks[d30_dt].get(p, set())) for p in d30_plates), default=0)

        # Causal rolling normalized mcap & mkt turnover (vs trailing 250d mean)
        amt_ma = mkt_amt_ma250.get(d30_dt, np.nan)
        mcap_ma = mkt_mcap_ma250.get(d30_dt, np.nan)
        mkt_amt_rel250 = float(r.mkt_amt_tril_d30 / amt_ma) if (amt_ma and amt_ma > 0) else np.nan
        mcap_rel250 = float(r.mcap_yi / mcap_ma) if (mcap_ma and mcap_ma > 0 and pd.notna(r.mcap_yi)) else np.nan

        # D31 09:25 auction features
        d31_ao = float(sp["ao"].iloc[i + 1])
        d31_ah = float(sp["ah"].iloc[i + 1])
        d31_al = float(sp["al"].iloc[i + 1])
        d31_ac = float(sp["ac"].iloc[i + 1])
        d31_zt_adj = float(sp["zt_px_adj"].iloc[i + 1])
        d31_dt_adj = float(sp["dt_px_adj"].iloc[i + 1])
        d31_pre_ac = float(sp["pre_adj"].iloc[i + 1])
        d31_body = (d31_ac - d31_ao) / d31_pre_ac if d31_pre_ac > 0 else 0.0
        d31_clv = (2.0 * d31_ac - d31_ah - d31_al) / (d31_ah - d31_al) if (d31_ah - d31_al) > 1e-9 else 0.5
        d31_open_dt = bool(sp["open_is_dt"].iloc[i + 1])
        d31_mkt10_opzt = int(mkt_op10.get(d31_dt, 0))
        d31_mkt20_opzt = int(mkt_op20.get(d31_dt, 0))
        d31_weekday = int(pd.Timestamp(d31_dt).weekday())

        # BP2a & BP2b conservative +0.30% penetration intraday breakout triggers
        # BP2a: D31 open < D30 close AND D31 high >= D30 close * 1.005 * 1.003 (and entry <= zt_px)
        ref_2a = d31_pre_ac * 1.005
        px_2a = ref_2a * (1.0 + TP_BUF)
        bp2a_hit = bool((r.d31_gap < 0.0) and (d31_ah >= px_2a) and (px_2a <= d31_zt_adj - 1e-4))
        # BP2b: D31 open < D30 close AND D31 high >= D31 open * 1.02 * 1.003
        ref_2b = d31_ao * 1.020
        px_2b = ref_2b * (1.0 + TP_BUF)
        bp2b_hit = bool((r.d31_gap < 0.0) and (d31_ah >= px_2b) and (px_2b <= d31_zt_adj - 1e-4))

        d_out = {
            "d30_clv": round(d30_clv, 3), "d30_body": round(d30_body, 2),
            "reg_abn_d31_0925": reg_abn_d31_0925, "reg_inq_d31_0925": reg_inq_d31_0925,
            "d30_lhb_yz_net": round(d30_lhb_yz_net, 1), "d30_kpl_zt_cnt": d30_kpl_zt_cnt,
            "mkt_amt_rel250": round(mkt_amt_rel250, 3) if pd.notna(mkt_amt_rel250) else np.nan,
            "mcap_rel250": round(mcap_rel250, 3) if pd.notna(mcap_rel250) else np.nan,
            "d31_mkt10_opzt": d31_mkt10_opzt, "d31_mkt20_opzt": d31_mkt20_opzt,
            "d31_weekday": d31_weekday, "d31_open_dt": d31_open_dt,
            "f1_body": round(d31_body, 4), "f1_clv": round(d31_clv, 4),
            "bp2a_hit": bp2a_hit, "bp2a_px_adj": round(px_2a, 4),
            "bp2b_hit": bp2b_hit, "bp2b_px_adj": round(px_2b, 4),
        }

        avail_k = min(20, n - 1 - i)
        d_out["avail_k"] = int(avail_k)
        for k in range(1, 21):
            idx_k = i + k
            if idx_k < n:
                d_out[f"f{k}_date"] = str(sp["dt_str"].iloc[idx_k])
                d_out[f"f{k}_ao"] = float(sp["ao"].iloc[idx_k])
                d_out[f"f{k}_ah"] = float(sp["ah"].iloc[idx_k])
                d_out[f"f{k}_al"] = float(sp["al"].iloc[idx_k])
                d_out[f"f{k}_ac"] = float(sp["ac"].iloc[idx_k])
                d_out[f"f{k}_ma5"] = float(sp["ma5"].iloc[idx_k])
                d_out[f"f{k}_zt_adj"] = float(sp["zt_px_adj"].iloc[idx_k])
                d_out[f"f{k}_zt"] = bool(sp["is_zt"].iloc[idx_k])
                d_out[f"f{k}_is_dt"] = bool(sp["is_dt"].iloc[idx_k])
                d_out[f"f{k}_yz_dt"] = bool(sp["is_yizi_dt"].iloc[idx_k])
                d_out[f"f{k}_open_dt"] = bool(sp["open_is_dt"].iloc[idx_k])
                d_out[f"f{k}_sellable"] = not bool(sp["is_yizi_dt"].iloc[idx_k])
            else:
                d_out[f"f{k}_date"] = ""
                for col_f in ("ao", "ah", "al", "ac", "ma5", "zt_adj"):
                    d_out[f"f{k}_{col_f}"] = np.nan
                for col_b in ("zt", "is_dt", "yz_dt", "open_dt", "sellable"):
                    d_out[f"f{k}_{col_b}"] = False
        ext_rows.append(d_out)

    ext_df = pd.DataFrame(ext_rows)
    full = pd.concat([eh.reset_index(drop=True), ext_df], axis=1)
    full.to_parquet(P / "events_hold_d31_enriched.parquet", index=False)
    print(f"[Enriched] Saved events_hold_d31_enriched.parquet shape={full.shape} in {time.time()-t_start:.1f}s")

    # ============================================================
    # STRICT IS-ONLY (2021-2023) EXPLORATION (ZERO OOS PEEKING!)
    # ============================================================
    is_pool = full[(full["d31_date"] <= "2023-12-31") & full["d31_buyable"]].copy()
    print(f"\n=== STRICT IS-ONLY (2021-2023) D31 BUYABLE POOL: Total={len(is_pool)} | 10cm={(~is_pool['is_20']).sum()} | 20cm={is_pool['is_20'].sum()} ===")

    # 1. Check BP2a / BP2b vs D31 open inside IS ONLY
    print("\n--- IS-ONLY Buy Point 1 (D31 Open) vs Buy Point 2 (Intraday Breakout +0.30% buf) -> D32c & D35c ---")
    for trk_nm, msk in [
        ("TrackA_10cm_peak", (~is_pool["is_20"]) & is_pool["in_peak_pool"]),
        ("TrackA_10cm_end165", (~is_pool["is_20"]) & is_pool["in_end_pool"]),
        ("TrackB_20cm_peak", is_pool["is_20"] & is_pool["in_peak_pool"]),
        ("TrackC_All_peak", is_pool["in_peak_pool"]),
    ]:
        sub = is_pool[msk]
        for bp_nm, em in [("BP1_D31_Open", "d31_open"), ("BP2a_GapNeg_CrossRed05", "bp2a_red"), ("BP2b_GapNeg_OpenPlus2", "bp2b_open2")]:
            t_d32 = sim_exit_tree(sub, "E0_Fixed_D32c", entry_mode=em)
            t_d35 = sim_exit_tree(sub, "E0_Fixed_D35c", entry_mode=em)
            if len(t_d32) == 0:
                continue
            print(f"  {trk_nm:20s} | {bp_nm:22s} | n={len(t_d32):2d} | D32c wr={(t_d32['net_ret']>0).mean()*100:4.1f}% mean={t_d32['net_ret'].mean()*100:+6.2f}% | D35c mean={t_d35['net_ret'].mean()*100:+6.2f}%")

    # 2. Check 7 Exit Trees inside IS ONLY across Track A / Track B / Track C
    print("\n--- IS-ONLY 7 Exit Trees Comparison (D31 Open Buy) ---")
    exit_tests = [
        ("E0_Fixed_D32c", {}),
        ("E0_Fixed_D35c", {}),
        ("E1_D32_TP6", {"tp": 0.06}),
        ("E1_D32_TP8", {"tp": 0.08}),
        ("E1_D32_TP10", {"tp": 0.10}),
        ("E2_ZT_Ride_Break", {}),
        ("E3_ZT_Ride_YangImm", {"tp": 0.08}),
        ("E4_4Branch_Tree", {"b2_body": 0.05, "b2_clv": 0.65, "b2_tp": 0.10, "b3_k": 1.5, "b4_body": -0.04}),
        ("E5_Trail_MA5_or_DD8", {"dd_lim": 0.08, "max_h": 15}),
        ("E6_Adaptive_TP_3D", {"tp2": 0.10, "tp3": 0.06, "tp4": 0.03}),
    ]
    for trk_nm, msk in [
        ("TrackA_10cm_peak", (~is_pool["is_20"]) & is_pool["in_peak_pool"]),
        ("TrackA_10cm_end165", (~is_pool["is_20"]) & is_pool["in_end_pool"]),
        ("TrackB_20cm_peak", is_pool["is_20"] & is_pool["in_peak_pool"]),
        ("TrackC_All_peak", is_pool["in_peak_pool"]),
    ]:
        sub = is_pool[msk]
        print(f"  -- {trk_nm} (IS n={len(sub)}) --")
        for emode, cfg in exit_tests:
            e_tag = emode if not emode.startswith("E1_D32_TP") else emode
            tr = sim_exit_tree(sub, e_tag, cfg=cfg)
            r = tr["net_ret"].to_numpy()
            w, l = r[r > 0], r[r <= 0]
            po = w.mean() / abs(l.mean()) if len(w) and len(l) else np.nan
            ew = tr.groupby("buy_date")["net_ret"].mean()
            ew_cum = (np.prod(1 + ew) - 1) * 100
            print(f"    {emode:22s}: n={len(r):2d} wr={(r>0).mean()*100:5.1f}% po={po:4.2f} mean={r.mean()*100:+6.2f}% ew_cum={ew_cum:+7.1f}% avg_hold={tr['hold_bars'].mean():.1f}d")

    # 3. Single-factor IS-ONLY scan (including new D31 09:25 & D30 post-close factors!)
    print("\n--- IS-ONLY Top Factors on D31 Open -> D32c / E4_4Branch (Track A / Track B / Track C) ---")
    for trk_nm, msk in [
        ("TrackA_10cm_peak", (~is_pool["is_20"]) & is_pool["in_peak_pool"]),
        ("TrackB_20cm_peak", is_pool["is_20"] & is_pool["in_peak_pool"]),
        ("TrackC_All_peak", is_pool["in_peak_pool"]),
    ]:
        sub = is_pool[msk].copy()
        tr_e4 = sim_exit_tree(sub, "E4_4Branch_Tree", {"b2_body": 0.05, "b2_clv": 0.65, "b2_tp": 0.10, "b3_k": 1.5, "b4_body": -0.04})
        sub = sub.merge(tr_e4[["c6", "d30_date", "net_ret"]].rename(columns={"net_ret": "ret_e4"}), on=["c6", "d30_date"], how="left")
        sub["ret_d32c"] = sub["r31o_d32c_f30"]

        cands = {
            "d31_gap_lt0": sub["d31_gap"] < 0.0,
            "d31_gap_lt_m2": sub["d31_gap"] < -2.0,
            "d31_gap_ge0": sub["d31_gap"] >= 0.0,
            "d31_gap_ge3_bad": sub["d31_gap"] >= 3.0,
            "d31_gap_sweet_20cm": sub["d31_gap"].between(-1.0, 5.0),
            "d31_mon_or_fri_fri": sub["d31_weekday"] == 4,
            "d31_mon_pen": sub["d31_weekday"] == 0,
            "d30_gap_lt0_and_neg": sub["d30_pct"] < 0.0,
            "d30_body_lt_m2": sub["d30_body"] < -2.0,
            "d30_body_ge0": sub["d30_body"] >= 0.0,
            "d30_clv_ge06": sub["d30_clv"] >= 0.6,
            "d30_kpl_in": sub["kpl_in_d30"],
            "d30_kpl_zt_ge2": sub["kpl_theme_zt_d30"] >= 2,
            "d29_kpl_5d": sub["kpl_in_5d_d29"],
            "d29_kpl_10d": sub["kpl_in_10d_d29"],
            "d29_theme_zt_ge2": sub["theme_zt_d29"] >= 2,
            "d29_theme_trend_up": sub["theme_trend_up_d29"],
            "d29_theme_leader": sub["is_theme_leader_d29"],
            "d30_live_assist": sub["theme_zt_d30_live"] >= 1,
            "relief_1d_ge10": sub["relief_1d_pp"] >= 10.0,
            "relief_1d_lt10": sub["relief_1d_pp"] < 10.0,
            "end_dev_ge170": sub["end_dev30"] >= 170.0,
            "dd30_lt5": sub["dd_at_d30"] >= -5.0,
            "dd30_pullback_5_20": sub["dd_at_d30"].between(-20.0, -5.0),
            "vol_shrink_lt08": sub["vol_shrink_5_20"] < 0.8,
            "above_ma5": sub["above_ma5"],
            "streak_ge3_demon": sub["max_streak_30d"] >= 3,
            "mcap_lt50": sub["mcap_yi"] < 50.0,
            "mcap_rel250_lt1": sub["mcap_rel250"] < 1.0,
            "no_reg_inq_d31": sub["reg_inq_d31_0925"] == 0,
            "no_reg_abn_d31": sub["reg_abn_d31_0925"] == 0,
            "lhb_d29_inst_pos": sub["lhb_inst_net_5d_d29"] > 0.0,
            "lhb_d30_inst_pos": sub["lhb_d30_inst_net"].fillna(0.0) > 0.0,
            "lhb_any_inst_pos": (sub["lhb_inst_net_5d_d29"] > 0.0) | (sub["lhb_d30_inst_net"].fillna(0.0) > 0.0),
            "lhb_no_lasa_d30": sub["lhb_d30_lasa_ratio"].fillna(0.0) < 0.20,
            "mkt_zt_d30_ge50": sub["mkt_zt_cnt_d30"] >= 50,
            "mkt_dt_d30_le10": sub["mkt_dt_cnt_d30"] <= 10,
            "mkt_amt_rel_ge1": sub["mkt_amt_rel250"] >= 1.0,
            "hs300_20d_pos": sub["hs300_ret20_d30"] > 0.0,
        }
        print(f"  -- {trk_nm} Top IS Factors (n={len(sub)}) --")
        res_f = []
        for fn, cond in cands.items():
            cond = cond.fillna(False)
            nt, nf = int(cond.sum()), int((~cond).sum())
            if nt < 5 or nf < 5:
                continue
            sp_32 = (sub.loc[cond, "ret_d32c"].mean() - sub.loc[~cond, "ret_d32c"].mean()) * 100
            sp_e4 = (sub.loc[cond, "ret_e4"].mean() - sub.loc[~cond, "ret_e4"].mean()) * 100
            m_t32 = sub.loc[cond, "ret_d32c"].mean() * 100
            m_te4 = sub.loc[cond, "ret_e4"].mean() * 100
            res_f.append((abs(sp_e4), fn, nt, nf, round(m_t32, 2), round(sp_32, 2), round(m_te4, 2), round(sp_e4, 2)))
        res_f.sort(reverse=True)
        for _, fn, nt, nf, m32, s32, me4, se4 in res_f[:18]:
            print(f"    {fn:22s}: T={nt:2d}/F={nf:2d} | D32c m={m32:+5.2f}%(sp={s32:+5.2f}) | E4 m={me4:+5.2f}%(sp={se4:+5.2f})")


if __name__ == "__main__":
    main()
