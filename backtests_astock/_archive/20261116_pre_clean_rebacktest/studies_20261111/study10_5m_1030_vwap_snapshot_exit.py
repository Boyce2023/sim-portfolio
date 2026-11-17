#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, sys, time
import numpy as np
import pandas as pd
import baostock as bs

sys.path.insert(0, "/tmp")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
from master_5y_zero_lookahead_walkforward import evaluate_strategy_master, FEE_RATE, FEE_RATE_DISCOUNT
import astock_verify_wr_optimization_strict as M

hist_fb = M.hist_fb
price_lookup = M.price_lookup
all_dts = M.all_dts
dt_to_idx = M.dt_to_idx

_, _, tot_mask, sv_score = M.run_cfg("UPGRADE_MT37_HT5_IR5_NoRk4", min_tight=37.0, bon_turnover=5.0, bon_ir=5.0, block_rk4_usurp=True)
hist_fb["_sv_master"] = sv_score

CACHE_5M = "/tmp/cand_5m_bars_2022_2026.parquet"

# Collect all candidate stock-date windows in tot_mask (2022-2026)
cand_oos = hist_fb[tot_mask & (hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-09")].copy()
print(f"Total candidate rows in tot_mask (2022-2026): {len(cand_oos)}, unique days: {cand_oos['d2_dt'].nunique()}")

if not os.path.exists(CACHE_5M):
    t0 = time.time()
    lg = bs.login()
    all_chunks = []
    # Deduplicate (c6, d2_dt) windows
    wins = cand_oos[["c6", "d2_dt"]].drop_duplicates().values.tolist()
    for i, (c6, d2) in enumerate(wins):
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0:
            continue
        end_dt = all_dts[min(idx2 + 13, len(all_dts) - 1)]
        bs_code = ("sh." if c6.startswith("6") else "sz.") + c6
        if c6.startswith(("8", "4", "9")):
            continue
        rs = bs.query_history_k_data_plus(
            bs_code, "date,time,open,high,low,close,volume,amount",
            start_date=d2, end_date=end_dt, frequency="5", adjustflag="3"
        )
        rows = []
        while (rs.error_code == "0") & rs.next():
            rows.append(rs.get_row_data())
        if rows:
            dfc = pd.DataFrame(rows, columns=["date", "time", "open", "high", "low", "close", "volume", "amount"])
            dfc["c6"] = c6
            all_chunks.append(dfc)
    bs.logout()
    df_5m = pd.concat(all_chunks, ignore_index=True)
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df_5m[col] = pd.to_numeric(df_5m[col], errors="coerce").fillna(0.0)
    df_5m["hhmm"] = df_5m["time"].str.slice(8, 12)
    df_5m.to_parquet(CACHE_5M, index=False)
    print(f"Fetched & cached {len(df_5m)} 5m bars across {len(wins)} windows in {time.time()-t0:.1f}s")
else:
    df_5m = pd.read_parquet(CACHE_5M)
    print(f"Loaded cached {len(df_5m)} 5m bars")

# Build fast dict: (c6, dt) -> numpy array of shape (N_bars, 7): [hhmm_int, o, h, l, c, vol, amt]
df_5m["hhmm_int"] = df_5m["hhmm"].astype(int)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {}
for (c6, dt), grp in df_5m.groupby(["c6", "date"], sort=False):
    bars_5m_map[(c6, dt)] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy()

print(f"Indexed {len(bars_5m_map)} (stock, day) 5-minute intraday trajectories!")

def make_5m_exit_engine(
    # Baseline exact match flags:
    mode_name="baseline_exact",
    # 1) Failed 2B exit on D3:
    d3_fail_rebound_5m=False,    # Instead of dumping at 09:25 panic open, hold if >=VWAP or wait morning bounce (+1.5% above o3 or +0.5% above c2), cut if breaks below min(o3*0.985, vwap*0.988) or by 10:30!
    d3_fail_limit_pct=None,      # Or simple passive limit sell at c2*(1+pct)
    # 2) Multi-board lock_high_pct rule:
    lock50_min_board=2,          # 2 = lock 50% from D3+, 3 = only lock 50% from D4+, 99 = never lock 50% at open
    lock50_pct=0.05,
    # 3) Streak-break intraday 5-minute dynamic exit (THE MASTER SECRET!):
    intraday_surge_trail=False,  # If intraday hits >= +6.5% (or touches zt) and fails to stay sealed: exit at 5m close when drops >= trail_drop below intraday peak OR breaks VWAP!
    surge_arm_pct=0.065,
    trail_drop_pct=0.025,
    morning_weak_cut=False,      # On streak ride day (D3+), if by cut_hhmm (e.g. 1030) max high < +3.5% AND close < VWAP & close < prev_c * 1.005 -> exit weak board at 10:30 close instead of riding afternoon waterfall!
    weak_cut_hhmm=1030,
    weak_max_h=0.035,
    # 4) High-board (>=3B) strong first-yin N-shape hold:
    high_brk_hold=False,
    fee=FEE_RATE
):
    def sim_intraday_day(c6, dc, prev_c, zt, izt_eod):
        """Simulate real 5m bar-by-bar execution on day dc (strictly causal: decision at bar i close -> fill at bar i+1 open!)."""
        arr = bars_5m_map.get((c6, dc))
        if arr is None or len(arr) < 4:
            return None  # fallback to daily close
        cum_vol = 0.0
        cum_amt = 0.0
        peak_h = arr[0, 1]  # open of bar 0
        armed_surge = False
        n = len(arr)
        for i in range(n - 1):  # up to n-2 so fill happens strictly at bar i+1 OPEN (zero lookahead!)
            hhmm, bo, bh, bl, bc, bvol, bamt = arr[i]
            cum_vol += bvol
            cum_amt += bamt
            vwap = (cum_amt / cum_vol) if cum_vol > 0 else bc
            if bh > peak_h:
                peak_h = bh

            # If currently locked at limit-up at 5m close, NEVER sell!
            if bc >= zt - 0.01:
                armed_surge = True
                continue

            if peak_h >= prev_c * (1.0 + surge_arm_pct) or peak_h >= zt - 0.01:
                armed_surge = True

            # Rule 3A: Armed surge (touched ZT / blown board or surged >= +6.5%), failed to seal, and pulled back!
            if intraday_surge_trail and armed_surge and hhmm >= 940:
                if (bc <= peak_h * (1.0 - trail_drop_pct)) or (bc < vwap and bc < peak_h * 0.982):
                    next_open = round(float(arr[i + 1, 1]), 2)
                    return next_open

            # Rule 3B: Morning weak cutoff (by 10:30, never pushed >= +3.5%, sitting below VWAP and red/flat line -> afternoon waterfall risk!)
            if morning_weak_cut and hhmm >= weak_cut_hhmm and hhmm <= 1130:
                if (peak_h < prev_c * (1.0 + weak_max_h)) and (bc < vwap) and (bc < prev_c * 0.995):
                    next_open = round(float(arr[i + 1, 1]), 2)
                    return next_open

        return None  # held to EOD (either sealed ZT or normal 15:00 close)

    def sim_trade(row):
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        if do_direct:
            buy_px = round(float(o2), 2)
        else:
            trig_p = float(row["trig_p"])
            if trig_p >= zt2 - 0.005 or h2 < trig_p:
                return None
            buy_px = round(float(trig_p), 2)

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {"net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar

        # === CASE A: D2 UNSEALED ===
        if not is_zt2:
            if mode_name == "raw_b0":
                curr = idx3
                while curr < len(all_dts):
                    b = price_lookup.get((c6, all_dts[curr]))
                    if not b or not b[7]:
                        px = round(float(b[0]), 2) if b else prev_c
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}
                    curr += 1
                return None

            d2_closed_up = (c2 >= float(row["close"]))
            if d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                if is_zt3:
                    curr = idx3 + 1; prev_c = round(float(c3), 2)
                    while curr < len(all_dts) and (curr - idx2 <= 10):
                        dc = all_dts[curr]; b = price_lookup.get((c6, dc))
                        if not b: break
                        if b[7] or b[6]: prev_c = round(float(b[3]), 2); curr += 1; continue
                        px_5m = sim_intraday_day(c6, dc, prev_c, b[4], b[6]) if (intraday_surge_trail or morning_weak_cut) else None
                        px = px_5m if px_5m is not None else round(float(b[3]), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}
                    return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
                else:
                    px = round(float(c3), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}

            # Not N-shape hold:
            if d3_fail_limit_pct is not None and d2_closed_up and (not is_yz_dt3):
                lim_px = round(c2 * (1.0 + d3_fail_limit_pct), 2)
                if o3 >= lim_px:
                    px = round(float(o3), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}
                elif h3 >= lim_px + 0.02:
                    return {"net_ret": round((lim_px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": lim_px}
                else:
                    px = round(float(c3), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}

            if d3_fail_rebound_5m and d2_closed_up and (not is_yz_dt3):
                arr3 = bars_5m_map.get((c6, d3))
                if arr3 is not None and len(arr3) >= 12:
                    # Wait morning 09:35~10:30 for either +1.5% bounce over open / touch c2, OR cut if breaks first 5m low after 09:40 or at 10:30!
                    first_low = arr3[0, 3]
                    tgt_px = max(o3 * 1.018, c2 * 0.998)
                    ex_px = None
                    for i in range(len(arr3) - 1):
                        hhmm, bo, bh, bl, bc, bv, ba = arr3[i]
                        if bh >= tgt_px + 0.02:
                            ex_px = round(float(tgt_px), 2); break
                        if hhmm >= 945 and bc < first_low * 0.995:
                            ex_px = round(float(arr3[i + 1, 1]), 2); break
                        if hhmm >= 1030:
                            ex_px = round(float(arr3[i + 1, 1]), 2); break
                    if ex_px is None:
                        ex_px = round(float(c3), 2)
                    return {"net_ret": round((ex_px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": ex_px}

            curr = idx3
            while curr < len(all_dts):
                b = price_lookup.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}
                curr += 1
            return None

        # === CASE B: D2 SEALED 2-BOARD ===
        curr = idx3
        boards_held = 2
        while curr < len(all_dts) and (curr - idx2 <= 10):
            dc = all_dts[curr]
            bar = price_lookup.get((c6, dc))
            if not bar:
                return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar
            if iyz_dt:
                prev_c = round(float(c), 2); curr += 1; continue
            o_ret = o / prev_c - 1.0

            # High-open 50% lock at 09:25
            if (boards_held >= lock50_min_board) and (lock50_pct is not None) and (o_ret >= lock50_pct) and (o < zt - 0.005):
                p1 = round(float(o), 2)
                # Check if remaining 50% exits intraday via 5m rule or seals!
                px_5m = sim_intraday_day(c6, dc, prev_c, zt, izt) if (intraday_surge_trail or morning_weak_cut) else None
                if px_5m is not None:
                    p_avg = round(0.5 * p1 + 0.5 * px_5m, 4)
                    return {"net_ret": round((p_avg / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": p_avg}
                if not izt:
                    p2 = round(float(c), 2)
                    p_avg = round(0.5 * p1 + 0.5 * p2, 4)
                    return {"net_ret": round((p_avg / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": p_avg}
                else:
                    curr += 1; prev_c = round(float(c), 2); boards_held += 1; p2 = prev_c
                    while curr < len(all_dts) and (curr - idx2 <= 10):
                        dc2 = all_dts[curr]; b2 = price_lookup.get((c6, dc2))
                        if not b2: p2, dc = prev_c, dc2; break
                        if b2[7]: prev_c = round(float(b2[3]), 2); curr += 1; continue
                        px2_5m = sim_intraday_day(c6, dc2, prev_c, b2[4], b2[6]) if (intraday_surge_trail or morning_weak_cut) else None
                        if px2_5m is not None:
                            p2, dc = px2_5m, dc2; break
                        if b2[6]: prev_c = round(float(b2[3]), 2); curr += 1; continue
                        p2, dc = round(float(b2[3]), 2), dc2; break
                    p_avg = round(0.5 * p1 + 0.5 * p2, 4)
                    return {"net_ret": round((p_avg / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": p_avg}

            # Check intraday 5m exit BEFORE EOD (notice: if stock opens yizi and stays sealed, sim_intraday_day never sells because bc >= zt-0.01!)
            if intraday_surge_trail or morning_weak_cut:
                px_5m = sim_intraday_day(c6, dc, prev_c, zt, izt)
                if px_5m is not None:
                    return {"net_ret": round((px_5m / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px_5m}

            if izt:
                prev_c = round(float(c), 2); boards_held += 1; curr += 1; continue

            if high_brk_hold and (boards_held >= 3) and (c >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                curr += 1; prev_c = round(float(c), 2)
                while curr < len(all_dts) and (curr - idx2 <= 11):
                    dc2 = all_dts[curr]; b2 = price_lookup.get((c6, dc2))
                    if not b2: break
                    if b2[7] or b2[6]: prev_c = round(float(b2[3]), 2); curr += 1; continue
                    px2_5m = sim_intraday_day(c6, dc2, prev_c, b2[4], b2[6]) if (intraday_surge_trail or morning_weak_cut) else None
                    px = px2_5m if px2_5m is not None else round(float(b2[3]), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc2, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}

            px = round(float(c), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px}

        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c}
    return sim_trade

print("\n=== REAL 5-MINUTE BAR-BY-BAR MASTER EXIT BENCHMARK (EXACT 102.01x ENTRY SIGNALS) ===")
tests = [
    ("0_反面教材:未封次日开盘割+一律断板15点收盘卖", dict(mode_name="raw_b0", lock50_min_board=99, lock50_pct=None)),
    ("1_当前102倍基准(胜通N字+二进三起高开5%锁半+收盘卖)", dict()),
    ("2_二进三不早卖飞(三进四起才高开5%锁半)", dict(lock50_min_board=3, lock50_pct=0.05)),
    ("3_完全取消竞价卖半(满仓吃到断板收盘)", dict(lock50_min_board=99, lock50_pct=None)),
    ("4_5m盘中卖法A:摸板炸板/冲高6.5%回落破均线锁利", dict(intraday_surge_trail=True, surge_arm_pct=0.065, trail_drop_pct=0.025)),
    ("5_5m盘中卖法A+取消二进三竞价早卖半(满仓冲板炸板才走!)", dict(lock50_min_board=99, lock50_pct=None, intraday_surge_trail=True, surge_arm_pct=0.065, trail_drop_pct=0.025)),
    ("6_5m盘中卖法A+三进四锁半(二进三满仓+炸板回落走)", dict(lock50_min_board=3, lock50_pct=0.05, intraday_surge_trail=True, surge_arm_pct=0.065, trail_drop_pct=0.025)),
    ("7_5m盘中卖法B:10:30未冲3.5%破均线截断止损", dict(morning_weak_cut=True, weak_cut_hhmm=1030, weak_max_h=0.035)),
    ("8_5m盘中卖法A+B双剑合璧(炸板回落锁利+10:30弱势截断)", dict(lock50_min_board=3, lock50_pct=0.05, intraday_surge_trail=True, surge_arm_pct=0.065, trail_drop_pct=0.025, morning_weak_cut=True, weak_cut_hhmm=1030, weak_max_h=0.035)),
    ("9_卖法C:高标(>=3板)断板红盘>=2%多留一日吃龙回头", dict(high_brk_hold=True)),
    ("10_卖法D:未封板次日5m早盘反抽走(拒接09:25核按钮)", dict(d3_fail_rebound_5m=True)),
    ("11_大高手全套四分支卖点(5m炸板锁利+10:30截弱+三进四锁半+高标首阴)", dict(lock50_min_board=3, lock50_pct=0.05, intraday_surge_trail=True, surge_arm_pct=0.065, trail_drop_pct=0.025, morning_weak_cut=True, weak_cut_hhmm=1030, weak_max_h=0.035, high_brk_hold=True)),
    ("12_大高手全套+失败单5m早盘反抽离场", dict(d3_fail_rebound_5m=True, lock50_min_board=3, lock50_pct=0.05, intraday_surge_trail=True, surge_arm_pct=0.065, trail_drop_pct=0.025, morning_weak_cut=True, weak_cut_hhmm=1030, weak_max_h=0.035, high_brk_hold=True)),
]
for nm, kw in tests:
    fn = make_5m_exit_engine(**kw)
    r = evaluate_strategy_master(hist_fb, "_sv_master", tot_mask, fn, desc=nm)
    print(f"{nm:54s} | N={r['trades_5y']:3d} | WR={r['wr_5y']:5.1f}% | PF={r['payoff_5y']:4.2f} | 1S={r['nav_1s']:7.2f}x | 2S={r['nav_2s']:6.2f}x | EW={r['daily_eq']:5.2f}x | MDD={r['mdd_1s']:4.1f}%")
