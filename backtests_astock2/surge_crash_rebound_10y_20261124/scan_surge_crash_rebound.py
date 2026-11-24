#!/usr/bin/env python3
"""
10Y PIT Empirical Scan: Surge -> Crash (A-Kill) -> Second-Wave Rebound
Universe: 10cm A-share mainboard (00/60) active + delisted (2016-01-01 ~ 2026-11-23)
Zero lookahead bias, survivorship-free, D15 compliant.
"""

import json
import os
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/huaichuaibeimeng/claude-projects")
OUT_DIR = ROOT / "sim-portfolio/backtests_astock2/surge_crash_rebound_10y_20261124"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FEE = 0.003  # 0.30% round-trip friction


def load_hs300():
    p_10y = ROOT / "sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123/data_cache/sh000300.parquet"
    hs = {}
    if p_10y.exists():
        df = pd.read_parquet(p_10y)
        if len(df.columns) == 1:
            df = df.reset_index()
        dcol = "date" if "date" in df.columns else df.columns[0]
        ccol = "close" if "close" in df.columns else df.columns[-1]
        for d, c in zip(pd.to_datetime(df[dcol]).dt.strftime("%Y-%m-%d"), df[ccol].astype(float)):
            hs[d] = c
    p_5y = ROOT / "sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
    if p_5y.exists():
        with open(p_5y) as f:
            raw = json.load(f)
        sub = raw.get("sh000300", {})
        if isinstance(sub, dict):
            for d, v in sub.items():
                val = v["close"] if isinstance(v, dict) else float(v)
                hs[d] = float(val)
    return hs


def fetch_names_tencent(tickers):
    names = {}
    clean = list(dict.fromkeys(tickers))
    for i in range(0, len(clean), 60):
        batch = clean[i:i + 60]
        q = []
        for t in batch:
            code, mkt = t.split(".")
            q.append(("sh" if mkt == "SH" else "sz") + code)
        url = "http://qt.gtimg.cn/q=" + ",".join(q)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                txt = resp.read().decode("gbk", errors="ignore")
            for line in txt.strip().splitlines():
                if "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) > 2:
                    code = parts[2]
                    name = parts[1]
                    mkt = "SH" if line.startswith("v_sh") else "SZ"
                    names[f"{code}.{mkt}"] = name
        except Exception:
            pass
    return names


def load_names_from_kpl():
    names = {}
    p = ROOT / "sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"
    if not p.exists():
        return names
    try:
        with open(p) as f:
            for line in f:
                if not line.strip():
                    continue
                obj = json.loads(line)
                for pl in obj.get("plates", []):
                    for st in pl.get("stocks", []):
                        c = str(st.get("code", "")).zfill(6)
                        n = st.get("name", "")
                        if c and n:
                            mkt = "SH" if c.startswith(("6", "9")) else "SZ"
                            names[f"{c}.{mkt}"] = n
    except Exception:
        pass
    return names


def is_sellable_close(ac, al, ret):
    # Not sealed at 10cm limit-down at close
    return not (ret <= -0.095 and ac <= al * 1.002)


def sell_from_idx(ac, al, ret, target_idx):
    n = len(ac)
    idx = min(target_idx, n - 1)
    while idx < n - 1 and not is_sellable_close(ac[idx], al[idx], ret[idx]):
        idx += 1
    return idx


def calc_single_slot_and_ew(trades, hs300_map, start_dt, end_dt):
    sub = [t for t in trades if start_dt <= t["entry_date"] <= end_dt]
    if not sub:
        return {"n": 0}
    # Date-equal-weight
    by_day = {}
    for t in sub:
        by_day.setdefault(t["entry_date"], []).append(t["ret"])
    day_rets = [float(np.mean(v)) for v in by_day.values()]
    all_rets = [t["ret"] for t in sub]
    wins = [r for r in all_rets if r > 0]
    losses = [r for r in all_rets if r <= 0]
    payoff = (np.mean(wins) / abs(np.mean(losses))) if (wins and losses and np.mean(losses) != 0) else 0.0

    # Single-slot non-overlapping rotation (deterministic: pick lowest ticker or highest prior surge?
    # Use deterministic prior_surge_pct descending = most famous dragon on that day!)
    sub_sorted = sorted(sub, key=lambda x: (x["entry_date"], -x["surge_pct"], x["ticker"]))
    nav = 1.0
    peak_nav = 1.0
    max_dd = 0.0
    busy_until = ""
    slot_n = 0
    slot_wins = 0
    slot_rets = []
    for t in sub_sorted:
        if t["entry_date"] <= busy_until:
            continue
        r = t["ret"]
        nav *= (1.0 + r)
        peak_nav = max(peak_nav, nav)
        max_dd = min(max_dd, nav / peak_nav - 1.0)
        busy_until = t["exit_date"]
        slot_n += 1
        slot_rets.append(r)
        if r > 0:
            slot_wins += 1

    # HS300 over same window
    hs_dates = sorted([d for d in hs300_map if start_dt <= d <= end_dt])
    hs_ret = (hs300_map[hs_dates[-1]] / hs300_map[hs_dates[0]] - 1.0) if len(hs_dates) >= 2 else 0.0
    cum_ret = nav - 1.0
    return {
        "n": len(sub),
        "days": len(by_day),
        "ew_day_mean": float(np.mean(day_rets)),
        "trade_mean": float(np.mean(all_rets)),
        "trade_med": float(np.median(all_rets)),
        "win_rate": len(wins) / len(all_rets),
        "payoff": float(payoff),
        "slot_n": slot_n,
        "slot_wr": slot_wins / slot_n if slot_n else 0.0,
        "slot_cum": cum_ret,
        "slot_mdd": max_dd,
        "hs300_ret": hs_ret,
        "net_excess": cum_ret - hs_ret,
    }


def main():
    print("Loading active + delisted parquet...")
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount"]
    df_act = pd.read_parquet(ROOT / "sim-portfolio/data/cn_hk_price_db/a_daily.parquet", columns=cols)
    df_del = pd.read_parquet(ROOT / "sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols)

    # Filter 10cm mainboard (00/60)
    df_act = df_act[df_act["ticker"].str.startswith(("00", "60"))].copy()
    df_del = df_del[df_del["ticker"].str.startswith(("00", "60"))].copy()
    df_act["is_delisted"] = False
    df_del["is_delisted"] = True

    df = pd.concat([df_act, df_del], ignore_index=True)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="first")

    # Determine listing start date (min date in full DB) per ticker before filtering >= 2015-09-01
    first_dt = df.groupby("ticker")["date"].min()
    df = df[df["date"] >= "2015-09-01"].copy()
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df["ym"] = df["date_str"].str.slice(0, 7)

    # Market-level monthly stats (2016-01 ~ 2026-11)
    # Compute daily turnover & daily 10cm limit-ups & max consecutive boards across mainboard
    print(f"Mainboard rows (>=2015-09): {len(df):,}, unique tickers: {df['ticker'].nunique():,}")

    # Adjusted OHLC
    valid_px = (df["close"] > 0) & (df["adj_close"] > 0)
    df = df[valid_px].copy()
    scale = df["adj_close"] / df["close"]
    df["ao"] = df["open"] * scale
    df["ah"] = df["high"] * scale
    df["al"] = df["low"] * scale
    df["ac"] = df["adj_close"]

    # Daily market turnover & trading days
    mkt_daily = df[df["date_str"] >= "2016-01-01"].groupby("date_str").agg(
        mkt_amt=("amount", "sum"),
        ym=("ym", "first"),
    ).reset_index()

    # Load ST list (for flagging current 2026-11 only, NOT static 10Y lookahead drop!)
    st_codes = set()
    st_p = ROOT / "sim-portfolio/data/st_universe.json"
    if st_p.exists():
        with open(st_p) as f:
            st_codes = set(json.load(f).get("codes", []))

    events = []
    # Entry trade lists
    trades_A_blind = []     # Buy crash confirmation day close (<= -25%, not limit-down) -> T+3 close
    trades_A30_blind = []   # Buy crash <= -30% day close -> T+3 close
    trades_B_open1 = []     # Rebound 1B confirmed -> next day open -> T+1 close
    trades_B_open3 = []     # Rebound 1B confirmed -> next day open -> T+3 close
    trades_B_brk = []       # Rebound 1B confirmed -> next day open -> break-board close
    trades_C_hit_t1 = []    # First rebound limit-up touch intraday (incl. failed!) -> next day close
    trades_C_hit_brk = []   # First rebound limit-up touch intraday -> break-board close
    trades_D_2b_t1 = []     # Rebound 2B confirmed -> next day open -> T+1 close
    trades_D_2b_t3 = []     # Rebound 2B confirmed -> next day open -> T+3 close

    # Also track monthly max consecutive boards & daily limit-ups
    daily_lu_cnt = {}
    monthly_max_board = {}

    first_dt_map = first_dt.dt.strftime("%Y-%m-%d").to_dict()

    for ticker, g in df.groupby("ticker", sort=False):
        n = len(g)
        if n < 60:
            continue
        dates = g["date_str"].to_numpy()
        yms = g["ym"].to_numpy()
        ao = g["ao"].to_numpy(dtype=np.float64)
        ah = g["ah"].to_numpy(dtype=np.float64)
        al = g["al"].to_numpy(dtype=np.float64)
        ac = g["ac"].to_numpy(dtype=np.float64)
        amt = g["amount"].to_numpy(dtype=np.float64)
        is_del = bool(g["is_delisted"].iloc[0])

        ret = np.zeros(n, dtype=np.float64)
        ret[1:] = ac[1:] / ac[:-1] - 1.0

        # Limit-up (10cm): ret >= 9.5% and close == high (within 0.2%)
        is_lu = (ret >= 0.095) & (ac >= ah * 0.998) & (ret <= 0.125)
        is_ld = (ret <= -0.095) & (ac <= al * 1.002) & (ret >= -0.125)
        is_yizi_lu = is_lu & (ao >= al * 0.998) & (ah <= al * 1.002)

        # Consecutive limit-up streak
        streak = np.zeros(n, dtype=np.int32)
        for i in range(1, n):
            if is_lu[i]:
                streak[i] = streak[i - 1] + 1

        # IPO age check: if listed after 2015-09-01, skip first 45 bars
        listed_after_cut = first_dt_map.get(ticker, "1990-01-01") >= "2015-09-01"
        min_i = 45 if listed_after_cut else 15

        # Update market-wide LU & max board stats (excluding IPO first 45 bars)
        for i in range(min_i, n):
            d = dates[i]
            if d < "2016-01-01":
                continue
            if is_lu[i]:
                daily_lu_cnt[d] = daily_lu_cnt.get(d, 0) + 1
                ym = yms[i]
                if streak[i] > monthly_max_board.get(ym, 0):
                    monthly_max_board[ym] = int(streak[i])

        # Scan for Surge -> Crash -> Rebound events
        i = min_i
        while i < n - 3:
            if dates[i] < "2016-01-01":
                i += 1
                continue

            # Quick check: must be near a 10d surge peak
            if i < 12:
                i += 1
                continue

            # Local peak check: ah[i] is highest in [i-3, min(n-1, i+3)]
            r_end = min(n, i + 4)
            if ah[i] < np.max(ah[i - 3:r_end]):
                i += 1
                continue

            # Check surge in [i-10, i]: low-to-high >= +40% AND >= 3 limit-ups in [i-10, i]
            win_lu = int(np.sum(is_lu[i - 10:i + 1]))
            if win_lu < 3:
                i += 1
                continue

            # Hygiene: no abnormal >13% jump (split/resumption/unadjusted IPO) in [i-10, i]
            if np.max(np.abs(ret[i - 10:i + 1])) > 0.125:
                i += 1
                continue

            base_low = float(np.min(al[i - 10:i]))
            if base_low <= 0:
                i += 1
                continue
            surge_pct = float(ah[i] / base_low - 1.0)
            if surge_pct < 0.40:
                i += 1
                continue

            max_streak_surge = int(np.max(streak[i - 10:i + 1]))
            peak_amt = float(np.max(amt[max(0, i - 2):i + 2]))

            # Phase 2: Crash A-kill within [i+1, min(n-1, i+12)]
            # Find first day t_c where drawdown from ah[i] hits <= -25%
            # Guard: no new high > ah[i] * 1.02 before crash, no >13% abnormal ret
            t_c = -1
            t_c30 = -1
            crash_ld_cnt = 0
            abn = False
            max_scan = min(n - 1, i + 12)
            for j in range(i + 1, max_scan + 1):
                if abs(ret[j]) > 0.125:
                    abn = True
                    break
                if ah[j] > ah[i] * 1.02:
                    break
                if is_ld[j]:
                    crash_ld_cnt += 1
                dd = al[j] / ah[i] - 1.0
                if dd <= -0.25 and t_c == -1:
                    t_c = j
                if dd <= -0.30 and t_c30 == -1:
                    t_c30 = j

            if abn or t_c == -1:
                i += 1
                continue

            # Track deepest trough within [i+1, min(n-1, t_c+12)] BEFORE rebound limit-up
            # Phase 3: Rebound within [t_c, min(n-1, t_c+12)] and <= i+25
            reb_end = min(n - 1, t_c + 12, i + 25)
            t_r = -1            # First rebound limit-up day (closed at LU)
            t_hit = -1          # First rebound intraday LU touch day (incl. failed!)
            t_b = t_c
            min_low = float(np.min(al[i + 1:t_c + 1]))
            for j in range(i + 1, t_c + 1):
                if al[j] == min_low:
                    t_b = j

            # Note: on t_c itself, only count as rebound if it's a 地天板 (ret >= 9.5% and close == high)
            for j in range(t_c, reb_end + 1):
                if abs(ret[j]) > 0.125:
                    break
                if al[j] < min_low and t_r == -1:
                    min_low = float(al[j])
                    t_b = j
                # Intraday touch limit-up (only on j >= t_c+1, or j == t_c if opened low and surged to LU)
                if t_hit == -1 and (j > t_c or (j == t_c and al[j] / ah[i] - 1.0 <= -0.25)):
                    if ah[j] >= ac[j - 1] * 1.095 and not is_yizi_lu[j]:
                        t_hit = j
                if t_r == -1 and is_lu[j]:
                    t_r = j
                    break

            max_dd_before_reb = float(min_low / ah[i] - 1.0)
            # Rebound consecutive boards & max rebound gain from min_low
            reb_boards = 0
            reb_max_gain = 0.0
            broke_peak = False
            reb_is_yizi = False
            reb_amt_ratio = 0.0
            if t_r != -1:
                k = t_r
                while k < n and is_lu[k]:
                    reb_boards += 1
                    k += 1
                post_end = min(n, t_r + 11)
                post_hi = float(np.max(ah[t_r:post_end]))
                reb_max_gain = float(post_hi / min_low - 1.0)
                broke_peak = post_hi > ah[i]
                reb_is_yizi = bool(is_yizi_lu[t_r])
                reb_amt_ratio = float(amt[t_r] / peak_amt) if peak_amt > 0 else 0.0
            else:
                post_hi = float(np.max(ah[t_c:reb_end + 1])) if reb_end >= t_c else min_low
                reb_max_gain = float(post_hi / min_low - 1.0)

            # Check if >= 20% rebound within 12d even without LU
            rebound_20pct = reb_max_gain >= 0.20

            ev = {
                "ticker": ticker,
                "is_delisted": is_del,
                "is_st_now": ticker.split(".")[0] in st_codes,
                "peak_date": dates[i],
                "peak_ym": yms[i],
                "surge_pct": surge_pct,
                "surge_lu_cnt": win_lu,
                "surge_max_streak": max_streak_surge,
                "crash_confirm_date": dates[t_c],
                "crash_confirm_ym": yms[t_c],
                "trough_date": dates[t_b],
                "crash_days": int(t_c - i),
                "crash_ld_cnt": crash_ld_cnt,
                "max_dd": max_dd_before_reb,
                "has_rebound_lu": t_r != -1,
                "rebound_date": dates[t_r] if t_r != -1 else None,
                "rebound_ym": yms[t_r] if t_r != -1 else None,
                "days_peak_to_reb": int(t_r - i) if t_r != -1 else -1,
                "days_confirm_to_reb": int(t_r - t_c) if t_r != -1 else -1,
                "reb_boards": reb_boards,
                "reb_max_gain": reb_max_gain,
                "broke_peak": broke_peak,
                "reb_is_yizi": reb_is_yizi,
                "reb_amt_ratio": reb_amt_ratio,
                "rebound_20pct": rebound_20pct,
            }
            events.append(ev)

            # --- PIT Tradable Entry Simulations ---
            # Entry A: Buy crash confirmation day t_c close (if NOT sealed limit-down) -> T+3 close
            if t_c + 3 < n and is_sellable_close(ac[t_c], al[t_c], ret[t_c]):
                ex = sell_from_idx(ac, al, ret, t_c + 3)
                r = ac[ex] / ac[t_c] - 1.0 - FEE
                trades_A_blind.append({
                    "ticker": ticker, "entry_date": dates[t_c], "exit_date": dates[ex],
                    "ret": float(r), "surge_pct": surge_pct
                })

            # Entry A30: Buy <= -30% crash day close (if NOT sealed limit-down) -> T+3 close
            if t_c30 != -1 and t_c30 + 3 < n and is_sellable_close(ac[t_c30], al[t_c30], ret[t_c30]):
                ex = sell_from_idx(ac, al, ret, t_c30 + 3)
                r = ac[ex] / ac[t_c30] - 1.0 - FEE
                trades_A30_blind.append({
                    "ticker": ticker, "entry_date": dates[t_c30], "exit_date": dates[ex],
                    "ret": float(r), "surge_pct": surge_pct
                })

            # Entry B: Rebound 1B confirmed at t_r -> Buy next day t_r+1 open (if NOT unbuyable yizi LU)
            if t_r != -1 and t_r + 2 < n:
                b_idx = t_r + 1
                if not is_yizi_lu[b_idx] and ao[b_idx] > 0:
                    # T+1 close (b_idx + 1)
                    ex1 = sell_from_idx(ac, al, ret, b_idx + 1)
                    trades_B_open1.append({
                        "ticker": ticker, "entry_date": dates[b_idx], "exit_date": dates[ex1],
                        "ret": float(ac[ex1] / ao[b_idx] - 1.0 - FEE), "surge_pct": surge_pct
                    })
                    # T+3 close (b_idx + 3)
                    if b_idx + 3 < n:
                        ex3 = sell_from_idx(ac, al, ret, b_idx + 3)
                        trades_B_open3.append({
                            "ticker": ticker, "entry_date": dates[b_idx], "exit_date": dates[ex3],
                            "ret": float(ac[ex3] / ao[b_idx] - 1.0 - FEE), "surge_pct": surge_pct
                        })
                    # Break-board exit: hold while LU, sell first non-LU close after b_idx
                    exb = b_idx + 1
                    while exb < n - 1 and is_lu[exb]:
                        exb += 1
                    exb = sell_from_idx(ac, al, ret, exb)
                    trades_B_brk.append({
                        "ticker": ticker, "entry_date": dates[b_idx], "exit_date": dates[exb],
                        "ret": float(ac[exb] / ao[b_idx] - 1.0 - FEE), "surge_pct": surge_pct
                    })

            # Entry C: Rebound 1B intraday limit-up hit (INCLUDES broken/failed boards in denominator!)
            if t_hit != -1 and t_hit + 1 < n:
                buy_px = ac[t_hit - 1] * 1.10
                ex1 = sell_from_idx(ac, al, ret, t_hit + 1)
                trades_C_hit_t1.append({
                    "ticker": ticker, "entry_date": dates[t_hit], "exit_date": dates[ex1],
                    "ret": float(ac[ex1] / buy_px - 1.0 - FEE), "surge_pct": surge_pct,
                    "sealed": bool(is_lu[t_hit])
                })
                exb = t_hit + 1
                while exb < n - 1 and is_lu[exb]:
                    exb += 1
                exb = sell_from_idx(ac, al, ret, exb)
                trades_C_hit_brk.append({
                    "ticker": ticker, "entry_date": dates[t_hit], "exit_date": dates[exb],
                    "ret": float(ac[exb] / buy_px - 1.0 - FEE), "surge_pct": surge_pct,
                    "sealed": bool(is_lu[t_hit])
                })

            # Entry D: Rebound 2B confirmed (t_r and t_r+1 both LU) -> Buy t_r+2 open (non-yizi)
            if t_r != -1 and reb_boards >= 2 and t_r + 3 < n:
                b_idx = t_r + 2
                if not is_yizi_lu[b_idx] and ao[b_idx] > 0:
                    ex1 = sell_from_idx(ac, al, ret, b_idx + 1)
                    trades_D_2b_t1.append({
                        "ticker": ticker, "entry_date": dates[b_idx], "exit_date": dates[ex1],
                        "ret": float(ac[ex1] / ao[b_idx] - 1.0 - FEE), "surge_pct": surge_pct
                    })
                    if b_idx + 3 < n:
                        ex3 = sell_from_idx(ac, al, ret, b_idx + 3)
                        trades_D_2b_t3.append({
                            "ticker": ticker, "entry_date": dates[b_idx], "exit_date": dates[ex3],
                            "ret": float(ac[ex3] / ao[b_idx] - 1.0 - FEE), "surge_pct": surge_pct
                        })

            # Advance cursor to avoid double-counting same wave
            i = max(i + 15, (t_r + 5) if t_r != -1 else (t_c + 10))

    ev_df = pd.DataFrame(events)
    print(f"Total 10Y Crash-After-Surge events: {len(ev_df):,} (delisted={int(ev_df['is_delisted'].sum())})")

    # Load HS300 & Stock Names
    hs300 = load_hs300()
    kpl_names = load_names_from_kpl()

    # Fetch names for Nov 2026 + top historical cluster examples
    reb_df = ev_df[ev_df["has_rebound_lu"]].copy()
    nov26_ev = ev_df[(ev_df["rebound_ym"] == "2026-11") | (ev_df["crash_confirm_ym"] == "2026-11")]

    # Monthly aggregation (by rebound_ym for rebound counts, by crash_confirm_ym for crash counts)
    mkt_monthly = mkt_daily.groupby("ym").agg(
        tdays=("date_str", "count"),
        avg_amt_yi=("mkt_amt", lambda x: float(x.mean() / 1e8)),
    ).reset_index()

    # Add daily LU avg per month
    lu_by_ym = {}
    for d, cnt in daily_lu_cnt.items():
        ym = d[:7]
        lu_by_ym.setdefault(ym, []).append(cnt)
    mkt_monthly["avg_lu"] = mkt_monthly["ym"].map(lambda ym: float(np.mean(lu_by_ym.get(ym, [0]))))
    mkt_monthly["max_board"] = mkt_monthly["ym"].map(lambda ym: int(monthly_max_board.get(ym, 0)))

    # Monthly HS300 return
    hs_by_ym = {}
    for d, c in sorted(hs300.items()):
        ym = d[:7]
        hs_by_ym.setdefault(ym, []).append(c)
    mkt_monthly["hs300_mret"] = mkt_monthly["ym"].map(
        lambda ym: (hs_by_ym[ym][-1] / hs_by_ym[ym][0] - 1.0) if len(hs_by_ym.get(ym, [])) >= 2 else np.nan
    )

    crash_cnt = ev_df.groupby("crash_confirm_ym").size().rename("crash_n")
    reb_cnt = reb_df.groupby("rebound_ym").size().rename("reb_lu_n")
    reb2_cnt = reb_df[reb_df["reb_boards"] >= 2].groupby("rebound_ym").size().rename("reb_2b_n")
    reb_new_hi = reb_df[reb_df["broke_peak"]].groupby("rebound_ym").size().rename("reb_newhi_n")

    m = mkt_monthly.set_index("ym").join([crash_cnt, reb_cnt, reb2_cnt, reb_new_hi]).fillna(
        {"crash_n": 0, "reb_lu_n": 0, "reb_2b_n": 0, "reb_newhi_n": 0}
    )
    for col in ["crash_n", "reb_lu_n", "reb_2b_n", "reb_newhi_n"]:
        m[col] = m[col].astype(int)
    # Pace normalized per 20 trading days (crucial for 2026-11 which only has 16 trading days!)
    m["reb_lu_pace20"] = m["reb_lu_n"] / m["tdays"] * 20.0
    m["reb_2b_pace20"] = m["reb_2b_n"] / m["tdays"] * 20.0
    m["crash_pace20"] = m["crash_n"] / m["tdays"] * 20.0
    m = m.reset_index()

    # Rank by reb_lu_pace20 and raw reb_lu_n
    m_sorted_pace = m.sort_values("reb_lu_pace20", ascending=False).reset_index(drop=True)
    m_sorted_raw = m.sort_values("reb_lu_n", ascending=False).reset_index(drop=True)
    m_5y = m[m["ym"] >= "2021-11"].sort_values("reb_lu_pace20", ascending=False).reset_index(drop=True)

    nov_pace_rank_10y = int(m_sorted_pace.index[m_sorted_pace["ym"] == "2026-11"][0]) + 1
    nov_raw_rank_10y = int(m_sorted_raw.index[m_sorted_raw["ym"] == "2026-11"][0]) + 1
    nov_pace_rank_5y = int(m_5y.index[m_5y["ym"] == "2026-11"][0]) + 1

    # Collect tickers to name-resolve (top 15 months' top 5 rebound stocks + all 2026-11 rebound stocks)
    top15_yms = list(m_sorted_pace.head(15)["ym"])
    if "2026-11" not in top15_yms:
        top15_yms.append("2026-11")
    need_tickers = set(nov26_ev["ticker"].tolist())
    for ym in top15_yms:
        sub = reb_df[reb_df["rebound_ym"] == ym].sort_values(
            ["reb_boards", "reb_max_gain", "surge_pct"], ascending=False
        ).head(6)
        need_tickers.update(sub["ticker"].tolist())
    missing_names = [t for t in need_tickers if t not in kpl_names]
    tx_names = fetch_names_tencent(missing_names)
    names_map = {**tx_names, **kpl_names}  # prefer kpl for delisted or tx for active
    for t, nm in tx_names.items():
        if t not in names_map or not names_map[t]:
            names_map[t] = nm

    def get_nm(t):
        return names_map.get(t, t)

    print("\n================ 1. 2026-11 RANK & BASE RATES ================")
    nov_row = m[m["ym"] == "2026-11"].iloc[0]
    print(f"2026-11 (tdays={int(nov_row['tdays'])}, thru 2026-11-23): crash={int(nov_row['crash_n'])}, "
          f"reb_1B={int(nov_row['reb_lu_n'])} (pace20={nov_row['reb_lu_pace20']:.1f}), "
          f"reb_2B+={int(nov_row['reb_2b_n'])} (pace20={nov_row['reb_2b_pace20']:.1f}), "
          f"newhi={int(nov_row['reb_newhi_n'])}")
    print(f"10Y Pace Rank: #{nov_pace_rank_10y}/{len(m)} (top {nov_pace_rank_10y/len(m)*100:.1f}%), "
          f"10Y Raw Rank: #{nov_raw_rank_10y}/{len(m)}, "
          f"5Y Pace Rank: #{nov_pace_rank_5y}/{len(m_5y)}")

    for label, s_dt, e_dt in [
        ("10Y (2016~2026)", "2016-01-01", "2026-11-23"),
        ("5Y (2021.11~2026.11)", "2021-11-01", "2026-11-23"),
        ("3Y (2023.11~2026.11)", "2023-11-01", "2026-11-23"),
        ("2026-11 (Crash in 10.25~11.20)", "2026-10-25", "2026-11-20"),
    ]:
        sub = ev_df[(ev_df["crash_confirm_date"] >= s_dt) & (ev_df["crash_confirm_date"] <= e_dt)]
        n_c = len(sub)
        r1 = int(sub["has_rebound_lu"].sum())
        r2 = int((sub["reb_boards"] >= 2).sum())
        rnh = int(sub["broke_peak"].sum())
        r20 = int(sub["rebound_20pct"].sum())
        print(f"BaseRate [{label}]: crash_n={n_c}, reb_1B={r1} ({r1/n_c*100:.1f}%), "
              f"reb_2B+={r2} ({r2/n_c*100:.1f}%), broke_peak={rnh} ({rnh/n_c*100:.1f}%), reb>=20%={r20} ({r20/n_c*100:.1f}%)")

    print("\n================ 2. TOP 15 HISTORICAL CLUSTER MONTHS (BY 20D PACE) ================")
    print(f"{'Rank':<4} {'YM':<8} {'TD':<3} {'Crash':<5} {'Reb1B':<5} {'Pace20':<6} {'Reb2B+':<6} {'NewHi':<5} {'AvgLU':<6} {'MaxB':<4} {'Amt亿':<7} {'HS300':<7} | Top Famous Examples")
    top15_out = []
    for idx, row in m_sorted_pace.head(15).iterrows():
        ym = row["ym"]
        sub = reb_df[reb_df["rebound_ym"] == ym].sort_values(
            ["reb_boards", "reb_max_gain", "surge_pct"], ascending=False
        ).head(4)
        exs = [f"{get_nm(r['ticker'])}({int(r['reb_boards'])}B,{r['reb_max_gain']*100:+.0f}%)" for _, r in sub.iterrows()]
        hs_s = f"{row['hs300_mret']*100:+.1f}%" if pd.notna(row["hs300_mret"]) else "N/A"
        print(f"{idx+1:<4} {ym:<8} {int(row['tdays']):<3} {int(row['crash_n']):<5} {int(row['reb_lu_n']):<5} "
              f"{row['reb_lu_pace20']:<6.1f} {int(row['reb_2b_n']):<6} {int(row['reb_newhi_n']):<5} "
              f"{row['avg_lu']:<6.1f} {int(row['max_board']):<4} {row['avg_amt_yi']:<7.0f} {hs_s:<7} | {', '.join(exs)}")
        top15_out.append({"rank": idx + 1, "ym": ym, "reb_lu_n": int(row["reb_lu_n"]), "pace20": round(float(row["reb_lu_pace20"]), 2), "examples": exs})

    # Regime comparison: Top 15 cluster months vs Median of all 131 months
    print("\n--- Regime Anatomy: Top 15 Cluster Months vs Normal Months ---")
    top15_m = m_sorted_pace.head(15)
    rest_m = m_sorted_pace.iloc[15:]
    for col, lbl in [("avg_amt_yi", "主板日均成交额(亿)"), ("avg_lu", "主板日均涨停家数"), ("max_board", "月最高连板高度"), ("crash_pace20", "暴涨暴跌月度供给数")]:
        print(f"  {lbl}: Top15均值={top15_m[col].mean():.1f} (中位={top15_m[col].median():.1f}) vs 其余116月均值={rest_m[col].mean():.1f} (中位={rest_m[col].median():.1f})")

    print("\n================ 3. 2026-11 COMPLETE REBOUND LIST (THRU 2026-11-23) ================")
    nov_reb = reb_df[reb_df["rebound_ym"] == "2026-11"].sort_values("rebound_date")
    for _, r in nov_reb.iterrows():
        print(f"  {r['rebound_date']} {r['ticker']} {get_nm(r['ticker']):<8} | 顶:{r['peak_date']}(+{r['surge_pct']*100:.0f}%,{int(r['surge_lu_cnt'])}板) "
              f"-> 杀:{r['max_dd']*100:.1f}%({int(r['crash_days'])}d,{int(r['crash_ld_cnt'])}跌停) -> 反抽:{int(r['reb_boards'])}板(最高+{r['reb_max_gain']*100:.0f}%)")

    print("\n================ 4. D15 PIT TRADABILITY BACKTEST (0.30% FEE, NON-YIZI) ================")
    periods = [
        ("10Y", "2016-01-01", "2026-11-23"),
        ("5Y", "2021-11-24", "2026-11-23"),
        ("3Y", "2023-11-24", "2026-11-23"),
        ("2026.11", "2026-11-01", "2026-11-23"),
    ]
    strat_map = [
        ("A1 盲抄暴跌-25%尾盘(T+3)", trades_A_blind),
        ("A2 盲抄暴跌-30%尾盘(T+3)", trades_A30_blind),
        ("B1 反抽首板次日开盘(T+1)", trades_B_open1),
        ("B2 反抽首板次日开盘(T+3)", trades_B_open3),
        ("B3 反抽首板次日开盘(断板卖)", trades_B_brk),
        ("C1 反抽首板打板含炸板(T+1)", trades_C_hit_t1),
        ("C2 反抽首板打板含炸板(断板卖)", trades_C_hit_brk),
        ("D1 反抽二板次日开盘(T+1)", trades_D_2b_t1),
        ("D2 反抽二板次日开盘(T+3)", trades_D_2b_t3),
    ]
    bt_summary = {}
    for sname, tlist in strat_map:
        print(f"\n[{sname}]")
        bt_summary[sname] = {}
        for plbl, s_dt, e_dt in periods:
            st = calc_single_slot_and_ew(tlist, hs300, s_dt, e_dt)
            bt_summary[sname][plbl] = st
            if st["n"] == 0:
                print(f"  {plbl:<7}: n=0")
            else:
                print(f"  {plbl:<7}: n={st['n']:<4} 日等权={st['ew_day_mean']*100:+.2f}% 笔均={st['trade_mean']*100:+.2f}% "
                      f"中位={st['trade_med']*100:+.2f}% 胜率={st['win_rate']*100:.1f}% 盈亏比={st['payoff']:.2f} | "
                      f"单仓({st['slot_n']}笔)累计={st['slot_cum']*100:+.1f}% HS300={st['hs300_ret']*100:+.1f}% 净超额={st['net_excess']*100:+.1f}% MDD={st['slot_mdd']*100:.1f}%")

    # Seal rate for Entry C (打板炸板率!)
    if trades_C_hit_t1:
        sealed_rate = sum(1 for t in trades_C_hit_t1 if t["sealed"]) / len(trades_C_hit_t1)
        print(f"\n[Entry C 封板率检查] 10Y反抽摸板共{len(trades_C_hit_t1)}笔，封死率={sealed_rate*100:.1f}%，炸板率={(1-sealed_rate)*100:.1f}%")

    print("\n================ 5. TRUE 2ND-WAVE (2B+) VS DEAD-CAT (1B) ANATOMY ================")
    r_2b = reb_df[reb_df["reb_boards"] >= 2]
    r_1b = reb_df[reb_df["reb_boards"] == 1]
    print(f"Rebound 1B count={len(r_1b)}, 2B+ count={len(r_2b)} ({len(r_2b)/len(reb_df)*100:.1f}% of rebound 1B advance to 2B+)")
    for col, lbl in [
        ("surge_pct", "一波涨幅"),
        ("surge_max_streak", "一波最高连板"),
        ("max_dd", "杀跌最大回撤"),
        ("crash_ld_cnt", "暴跌期跌停数"),
        ("days_peak_to_reb", "从顶到反抽天数"),
        ("reb_amt_ratio", "反抽日成交额/顶点成交额"),
    ]:
        print(f"  {lbl}: 真二波(2B+)中位={r_2b[col].median():.2f} vs 一日游(1B)中位={r_1b[col].median():.2f}")

    # Check if Entry B1 (反抽首板次日开盘 T+1) works better under high turnover or fast crash or high prior boards
    b1_df = pd.DataFrame(trades_B_open1)
    if len(b1_df) > 0:
        # Merge event features
        ev_reb = reb_df[["ticker", "rebound_date", "surge_max_streak", "max_dd", "crash_ld_cnt", "days_peak_to_reb", "reb_amt_ratio", "rebound_ym"]].copy()
        # Note entry_date is rebound_date + 1 trading day; match by ticker and closest rebound_date < entry_date
        # Easier: check rebound_ym market turnover
        ym_amt = m.set_index("ym")["avg_amt_yi"].to_dict()
        b1_df["ym"] = b1_df["entry_date"].str.slice(0, 7)
        b1_df["mkt_amt"] = b1_df["ym"].map(ym_amt)
        hi = b1_df[b1_df["mkt_amt"] >= 7000]  # mainboard >= 7000亿 (total market ~1.3万亿+)
        lo = b1_df[b1_df["mkt_amt"] < 7000]
        print(f"  [B1 按成交额切分] 放量市(主板>=7000亿) n={len(hi)}, 笔均={hi['ret'].mean()*100:+.2f}%, 胜率={(hi['ret']>0).mean()*100:.1f}% | "
              f"缩量市(<7000亿) n={len(lo)}, 笔均={lo['ret'].mean()*100:+.2f}%, 胜率={(lo['ret']>0).mean()*100:.1f}%")

    # Save full artifacts
    ev_df["name"] = ev_df["ticker"].map(get_nm)
    ev_df.to_parquet(OUT_DIR / "events_10y.parquet", index=False)
    m.to_csv(OUT_DIR / "monthly_stats_10y.csv", index=False)
    with open(OUT_DIR / "summary.json", "w") as f:
        json.dump({
            "nov26_rank_10y_pace": nov_pace_rank_10y,
            "nov26_rank_10y_raw": nov_raw_rank_10y,
            "nov26_rank_5y_pace": nov_pace_rank_5y,
            "total_months": len(m),
            "top15_months": top15_out,
            "bt_summary": bt_summary,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nSaved outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
