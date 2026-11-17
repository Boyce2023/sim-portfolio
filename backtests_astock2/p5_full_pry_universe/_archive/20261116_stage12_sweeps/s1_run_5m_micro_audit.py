#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
s1_run_5m_micro_audit.py - 5分钟K线微观撬板机制与竞价实测 (Task 2)
落盘 s1_5m_micro_audit.json
"""
import os, time, json, pickle, sqlite3
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p5_full_pry_universe"
PARQUET_FILE = f"{BASE_DIR}/full_pry_master_enriched.parquet"
RETURN_MATRIX_FILE = f"{BASE_DIR}/return_matrix_8x10.pkl"
CACHE_5M = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p4_pry_board/p2_5m_bars_cache.pkl"
AUCTION_DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/auction/auction.db"
OUT_JSON = f"{BASE_DIR}/s1_5m_micro_audit.json"

def main():
    t0 = time.time()
    print("Loading data for 5m micro audit...")
    df = pd.read_parquet(PARQUET_FILE)
    with open(RETURN_MATRIX_FILE, "rb") as f:
        rm = pickle.load(f)
    with open(CACHE_5M, "rb") as f:
        c2 = pickle.load(f)

    row_map = { (r.c6, r.dt_str): idx for idx, r in df.iterrows() }

    pry_events = []
    for (c6, dt_str), bars in c2.items():
        if (c6, dt_str) not in row_map:
            continue
        idx = row_map[(c6, dt_str)]
        row = df.iloc[idx]
        if row["is_st_or_delist"] or row["pre_c"] < 2.0 or not row["touch_dt"]:
            continue

        dt_px = row["dt_price"]
        prev_amt = row["prev_amt"]

        # find touch bar
        touch_idx = -1
        for k, b in enumerate(bars):
            if b[3] <= dt_px + 0.005:
                touch_idx = k
                break
        if touch_idx < 0:
            continue

        # find pry bar
        pry_idx = -1
        for k in range(touch_idx, len(bars)):
            if bars[k][2] > dt_px + 0.005:
                pry_idx = k
                break
        if pry_idx < 0:
            continue

        pb = bars[pry_idx]
        pb_time = int(pb[0])
        pb_amt = pb[6]
        pb_ratio = pb_amt / prev_amt if prev_amt > 0 else 0

        # Next bar confirmation
        next_confirm_low = False
        next_confirm_mid = False
        if pry_idx + 1 < len(bars):
            nb = bars[pry_idx + 1]
            pb_mid = (pb[2] + pb[3]) / 2.0
            next_confirm_low = bool(nb[4] >= pb[3])
            next_confirm_mid = bool(nb[4] >= pb_mid)

        # VWAP reclaim
        cum_v = np.cumsum(bars[:, 5])
        cum_a = np.cumsum(bars[:, 6])
        vwap = np.where(cum_v > 0, cum_a / cum_v, bars[:, 4])
        vwap_reclaim = False
        for k in range(pry_idx, len(bars)):
            if bars[k][4] > vwap[k]:
                vwap_reclaim = True
                break

        ename = "E1_opendt_lift15" if row["open_is_dt"] else "E4_intradive_dt"
        r_x1 = rm["ret"][ename]["X1"][idx]
        r_x4 = rm["ret"][ename]["X4"][idx]
        r_x7 = rm["ret"][ename]["X7"][idx]
        r_x9 = rm["ret"][ename]["X9"][idx]
        r_x10 = rm["ret"][ename]["X10"][idx]

        pry_events.append({
            "c6": c6, "dt_str": dt_str, "idx": idx, "ename": ename,
            "pry_time": pb_time, "pb_ratio": float(pb_ratio),
            "next_confirm_low": next_confirm_low, "next_confirm_mid": next_confirm_mid,
            "vwap_reclaim": vwap_reclaim, "resealed": bool(row["is_dt"]),
            "prev_dt_streak": int(row["prev_dt_streak"]) if pd.notnull(row["prev_dt_streak"]) else 0,
            "r_x1": float(r_x1) if pd.notnull(r_x1) else None,
            "r_x4": float(r_x4) if pd.notnull(r_x4) else None,
            "r_x7": float(r_x7) if pd.notnull(r_x7) else None,
            "r_x9": float(r_x9) if pd.notnull(r_x9) else None,
            "r_x10": float(r_x10) if pd.notnull(r_x10) else None,
        })

    pe = pd.DataFrame(pry_events)
    pe["daily_pry_rank"] = pe.groupby("dt_str")["pry_time"].rank(method="min")
    pe["is_pioneer"] = (pe["daily_pry_rank"] == 1)

    def stats_slice(sub, r_col="r_x7"):
        r = sub[r_col].dropna()
        n = len(sub)
        if len(r) == 0:
            return {"n": n, "reseal_rate": 0.0, "win_rate": 0.0, "mean_pct": 0.0, "plr": 0.0}
        w = float((r > 0).mean())
        m = float(r.mean() * 100)
        g = r[r > 0]
        l = r[r < 0]
        gain = float(g.mean()) if len(g) > 0 else 0.0
        loss = float(abs(l.mean())) if len(l) > 0 else 1.0
        plr = float(gain / loss) if loss > 1e-6 else 0.0
        reseal = float(sub["resealed"].mean())
        return {
            "n": n,
            "reseal_rate": round(reseal * 100, 2),
            "win_rate": round(w * 100, 2),
            "mean_pct": round(m, 2),
            "plr": round(plr, 2)
        }

    # 1. Mechanism 1: pb_ratio
    m1_results = {}
    for label, m in [
        ("lt_10pct", pe["pb_ratio"] < 0.10),
        ("10_to_20pct", (pe["pb_ratio"] >= 0.10) & (pe["pb_ratio"] < 0.20)),
        ("20_to_35pct", (pe["pb_ratio"] >= 0.20) & (pe["pb_ratio"] < 0.35)),
        ("ge_35pct", pe["pb_ratio"] >= 0.35),
    ]:
        m1_results[label] = {
            "X7": stats_slice(pe[m], "r_x7"),
            "X9": stats_slice(pe[m], "r_x9")
        }

    # 2. Mechanism 2: 2nd 5m confirmation
    m2_results = {
        "all": {"X7": stats_slice(pe, "r_x7"), "X9": stats_slice(pe, "r_x9")},
        "next_bar_broken_low": {"X7": stats_slice(pe[~pe["next_confirm_low"]], "r_x7"), "X9": stats_slice(pe[~pe["next_confirm_low"]], "r_x9")},
        "next_bar_held_low": {"X7": stats_slice(pe[pe["next_confirm_low"]], "r_x7"), "X9": stats_slice(pe[pe["next_confirm_low"]], "r_x9")},
        "next_bar_held_mid": {"X7": stats_slice(pe[pe["next_confirm_mid"]], "r_x7"), "X9": stats_slice(pe[pe["next_confirm_mid"]], "r_x9")},
    }

    # 3. Mechanism 3: VWAP Reclaim
    m3_results = {
        "vwap_not_reclaimed": {"X7": stats_slice(pe[~pe["vwap_reclaim"]], "r_x7"), "X9": stats_slice(pe[~pe["vwap_reclaim"]], "r_x9")},
        "vwap_reclaimed": {"X7": stats_slice(pe[pe["vwap_reclaim"]], "r_x7"), "X9": stats_slice(pe[pe["vwap_reclaim"]], "r_x9")},
    }

    # 4. Mechanism 4: Pioneer vs Follower
    m4_results = {
        "pioneer_rank1": {"X7": stats_slice(pe[pe["is_pioneer"]], "r_x7"), "X9": stats_slice(pe[pe["is_pioneer"]], "r_x9")},
        "follower_rank2_plus": {"X7": stats_slice(pe[~pe["is_pioneer"]], "r_x7"), "X9": stats_slice(pe[~pe["is_pioneer"]], "r_x9")},
    }

    # 5. Mechanism 5: Auction 09:18 -> 09:20 -> 09:25 audit
    conn = sqlite3.connect(f"file:{AUCTION_DB}?mode=ro", uri=True)
    q_18 = "SELECT date, code, price as p18, prevclose, asksz1 as a18, bidsz1 as b18 FROM snapf WHERE ts BETWEEN '09:17:30' AND '09:18:30' GROUP BY date, code"
    df_18 = pd.read_sql_query(q_18, conn).set_index(["date", "code"])
    q_20 = "SELECT date, code, price as p20, asksz1 as a20, bidsz1 as b20 FROM snapf WHERE ts BETWEEN '09:20:00' AND '09:20:30' GROUP BY date, code"
    df_20 = pd.read_sql_query(q_20, conn).set_index(["date", "code"])
    q_25 = "SELECT date, code, price as p25, asksz1 as a25, bidsz1 as b25 FROM snapf WHERE ts BETWEEN '09:24:30' AND '09:25:05' GROUP BY date, code"
    df_25 = pd.read_sql_query(q_25, conn).set_index(["date", "code"])
    conn.close()

    df_auc = df_18.join(df_20, how="inner").join(df_25, how="inner")
    df_auc["pct_18"] = df_auc["p18"] / df_auc["prevclose"] - 1.0
    df_auc["pct_20"] = df_auc["p20"] / df_auc["prevclose"] - 1.0
    df_auc["pct_25"] = df_auc["p25"] / df_auc["prevclose"] - 1.0

    dt_18 = df_auc[df_auc["pct_18"] <= -0.095].copy()
    dt_18["unsealed_at_0920"] = dt_18["pct_20"] > dt_18["pct_18"] + 0.005
    dt_18["unsealed_at_0925"] = dt_18["pct_25"] > dt_18["pct_18"] + 0.005

    dt_20 = df_auc[df_auc["pct_20"] <= -0.095].copy()
    dt_20["unsealed_by_0925"] = dt_20["pct_25"] > dt_20["pct_20"] + 0.005

    m5_results = {
        "n_limit_down_0918": len(dt_18),
        "unsealed_at_0920_fake_order_cancel_rate": round(float(dt_18["unsealed_at_0920"].mean()) * 100, 2),
        "unsealed_at_0925_open_rate": round(float(dt_18["unsealed_at_0925"].mean()) * 100, 2),
        "n_limit_down_locked_at_0920": len(dt_20),
        "genuine_absorbed_unsealed_by_0925_rate": round(float(dt_20["unsealed_by_0925"].mean()) * 100, 2),
        "still_locked_limit_down_at_open_rate": round(float(1.0 - dt_20["unsealed_by_0925"].mean()) * 100, 2)
    }

    final_payload = {
        "summary": "5m Intraday Micro Pry Mechanism & Auction Audit",
        "sample_counts": {
            "total_pry_events_with_5m": len(pe),
            "date_range": f"{pe['dt_str'].min()} to {pe['dt_str'].max()}"
        },
        "mechanism_1_volume_spike": m1_results,
        "mechanism_2_next_bar_confirmation": m2_results,
        "mechanism_3_vwap_reclaim": m3_results,
        "mechanism_4_pioneer_vs_follower": m4_results,
        "mechanism_5_auction_withdrawal_and_absorption": m5_results
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2, ensure_ascii=False)

    print(f"Audit completed in {time.time()-t0:.2f}s, saved to {OUT_JSON}")

if __name__ == "__main__":
    main()
