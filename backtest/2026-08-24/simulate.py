#!/usr/bin/env python3
"""
Step 3: replay 4 exit rules on each closed episode (entry fixed = actual buy
schedule; only the EXIT is counterfactually replaced).

Rules:
  R1 disaster  : exit when close_t <= cost_basis_t * 0.88  (cost_basis updates
                 on each actual buy-leg date; matches T18 door2 / portfolio_trend_check.py)
  R2 ma20      : exit when close_t < SMA(close, 20) computed with the 20 most
                 recent closes INCLUDING today
  R3 low10     : exit when close_t < min(low of the 10 PRECEDING bars, excluding
                 today)  (matches EXIT_N=10 in portfolio_trend_check.py exactly)
  R4 hold      : never stops; marked to today's (2026-08-24) live price

Exit execution convention: fill at that trigger day's CLOSE (for R4: today's
live quote). This is a simplification (no intraday fill) applied uniformly
across all 4 rules so relative comparison stays fair.

Buy-side legs are replayed exactly as they actually happened (dates/prices/
shares) up to the point a rule fires; ACTUAL sell legs (profit-taking, T11b,
etc.) are ignored in the counterfactual -- each rule is tested as if it were
the SOLE exit discipline governing the whole position.
"""
import json, statistics as stats

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
TODAY = "2026-08-24"
FWD_N = 10   # false-kill lookforward window (trading days)

def load():
    with open(f"{BASE}/episodes_window.json") as f:
        eps = json.load(f)
    with open(f"{BASE}/klines.json") as f:
        kl = json.load(f)
    return eps, kl

def sma(closes, i, n):
    if i + 1 < n:
        return None
    window = closes[i - n + 1:i + 1]
    return sum(window) / n

def simulate_episode(ep, bars):
    """bars: sorted list of {'d','o','h','l','c'} for the ticker (full history incl. today)."""
    dates = [b["d"] for b in bars]
    closes = [b["c"] for b in bars]
    lows = [b["l"] for b in bars]

    entry_date = ep["entry_date"]
    if entry_date not in dates:
        # entry date not a trading-day bar we have (shouldn't happen); bail
        return None
    entry_idx = dates.index(entry_date)

    # buy legs schedule: (date, shares, price)
    buy_legs = sorted([(d, sh, px) for (d, act, sh, px) in ep["legs"] if act == "buy"],
                       key=lambda x: x[0])

    results = {}

    # ---- R1 disaster (-12% from evolving cost basis) ----
    shares = 0.0; cost_val = 0.0
    li = 0
    trig_idx = None
    for i in range(entry_idx, len(bars)):
        d = dates[i]
        while li < len(buy_legs) and buy_legs[li][0] <= d:
            _, sh, px = buy_legs[li]
            shares += sh; cost_val += sh * px
            li += 1
        if shares <= 0:
            continue
        cps = cost_val / shares
        g = closes[i] / cps - 1
        if g <= -0.12:
            trig_idx = i
            break
    if trig_idx is not None:
        exit_price = closes[trig_idx]
        cps_at_exit = cost_val / shares
        results["R1_disaster"] = dict(triggered=True, exit_date=dates[trig_idx],
                                       exit_price=exit_price, entry_cost=cps_at_exit,
                                       ret=exit_price / cps_at_exit - 1, exit_idx=trig_idx)
    else:
        cps_final = cost_val / shares if shares else ep["avg_entry_price"]
        results["R1_disaster"] = dict(triggered=False, exit_date=TODAY,
                                       exit_price=closes[-1], entry_cost=cps_final,
                                       ret=closes[-1] / cps_final - 1, exit_idx=len(bars) - 1)

    # ---- R2 20-day MA break (close < SMA20 incl. today) ----
    shares = 0.0; cost_val = 0.0; li = 0
    trig_idx = None
    for i in range(entry_idx, len(bars)):
        d = dates[i]
        while li < len(buy_legs) and buy_legs[li][0] <= d:
            _, sh, px = buy_legs[li]
            shares += sh; cost_val += sh * px
            li += 1
        ma20 = sma(closes, i, 20)
        if ma20 is not None and closes[i] < ma20:
            trig_idx = i
            break
    if trig_idx is not None:
        exit_price = closes[trig_idx]
        cps_at_exit = cost_val / shares if shares else ep["avg_entry_price"]
        results["R2_ma20"] = dict(triggered=True, exit_date=dates[trig_idx],
                                   exit_price=exit_price, entry_cost=cps_at_exit,
                                   ret=exit_price / cps_at_exit - 1, exit_idx=trig_idx)
    else:
        cps_final = cost_val / shares if shares else ep["avg_entry_price"]
        results["R2_ma20"] = dict(triggered=False, exit_date=TODAY,
                                   exit_price=closes[-1], entry_cost=cps_final,
                                   ret=closes[-1] / cps_final - 1, exit_idx=len(bars) - 1)

    # ---- R2b 20-day MA break, MA computed EXCLUDING today (avoids "already
    #      broken on day of purchase" lookahead artifact; requires >=1 day held) ----
    shares = 0.0; cost_val = 0.0; li = 0
    trig_idx = None
    for i in range(entry_idx, len(bars)):
        d = dates[i]
        while li < len(buy_legs) and buy_legs[li][0] <= d:
            _, sh, px = buy_legs[li]
            shares += sh; cost_val += sh * px
            li += 1
        if i == entry_idx:
            continue  # no exit allowed on the entry day itself
        ma20_prior = sma(closes, i - 1, 20)
        if ma20_prior is not None and closes[i] < ma20_prior:
            trig_idx = i
            break
    if trig_idx is not None:
        exit_price = closes[trig_idx]
        cps_at_exit = cost_val / shares if shares else ep["avg_entry_price"]
        results["R2b_ma20_excl_today"] = dict(triggered=True, exit_date=dates[trig_idx],
                                   exit_price=exit_price, entry_cost=cps_at_exit,
                                   ret=exit_price / cps_at_exit - 1, exit_idx=trig_idx)
    else:
        cps_final = cost_val / shares if shares else ep["avg_entry_price"]
        results["R2b_ma20_excl_today"] = dict(triggered=False, exit_date=TODAY,
                                   exit_price=closes[-1], entry_cost=cps_final,
                                   ret=closes[-1] / cps_final - 1, exit_idx=len(bars) - 1)

    # ---- R3 break prior-10-day low (close < min(low[t-10:t])) ----
    shares = 0.0; cost_val = 0.0; li = 0
    trig_idx = None
    for i in range(entry_idx, len(bars)):
        d = dates[i]
        while li < len(buy_legs) and buy_legs[li][0] <= d:
            _, sh, px = buy_legs[li]
            shares += sh; cost_val += sh * px
            li += 1
        if i - 10 < 0:
            continue
        low10 = min(lows[i - 10:i])
        if closes[i] < low10:
            trig_idx = i
            break
    if trig_idx is not None:
        exit_price = closes[trig_idx]
        cps_at_exit = cost_val / shares if shares else ep["avg_entry_price"]
        results["R3_low10"] = dict(triggered=True, exit_date=dates[trig_idx],
                                    exit_price=exit_price, entry_cost=cps_at_exit,
                                    ret=exit_price / cps_at_exit - 1, exit_idx=trig_idx)
    else:
        cps_final = cost_val / shares if shares else ep["avg_entry_price"]
        results["R3_low10"] = dict(triggered=False, exit_date=TODAY,
                                    exit_price=closes[-1], entry_cost=cps_final,
                                    ret=closes[-1] / cps_final - 1, exit_idx=len(bars) - 1)

    # ---- R4 hold to today, no stop ----
    shares = ep["shares"]; cost_val = ep["shares"] * ep["avg_entry_price"]
    cps_final = ep["avg_entry_price"]
    results["R4_hold"] = dict(triggered=False, exit_date=TODAY, exit_price=closes[-1],
                               entry_cost=cps_final, ret=closes[-1] / cps_final - 1,
                               exit_idx=len(bars) - 1)

    # ---- false-kill check: within FWD_N trading days after a TRIGGERED exit,
    #      did close ever go back above the exit price? ----
    for key in ["R1_disaster", "R2_ma20", "R2b_ma20_excl_today", "R3_low10"]:
        r = results[key]
        if r["triggered"]:
            i = r["exit_idx"]
            fwd = closes[i + 1:i + 1 + FWD_N]
            if not fwd:
                r["false_kill"] = None  # no forward data yet
            else:
                r["false_kill"] = any(c > r["exit_price"] for c in fwd)
                r["false_kill_fwd_days_available"] = len(fwd)
        else:
            r["false_kill"] = None

    return results

def main():
    eps, kl = load()
    out = []
    for ep in eps:
        bars = kl.get(ep["ticker"], [])
        if not bars:
            print(f"SKIP {ep['ticker']} (no bars)")
            continue
        sim = simulate_episode(ep, bars)
        if sim is None:
            print(f"SKIP {ep['ticker']} entry {ep['entry_date']} (entry date not in bars)")
            continue
        out.append({"episode": ep, "sim": sim})

    with open(f"{BASE}/simulation_results.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"simulated {len(out)} / {len(eps)} episodes")

if __name__ == "__main__":
    main()
