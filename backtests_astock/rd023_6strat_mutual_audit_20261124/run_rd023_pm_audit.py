#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD023 PM Audit: 20cm cross-board/counterparty signals -> 5x 10cm V19.1 clean ledgers + Drift Audit."""
import json, os, sqlite3, sys
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules
SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
OUT = f"{SIM}/backtests_astock/rd023_6strat_mutual_audit_20261124"
os.makedirs(OUT, exist_ok=True)
P_LED = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
P_20 = f"{SIM}/backtests_astock2/rd022_20cm_strategy_suite_20261124"

# 1. Build 100% PIT daily 20cm cross-board panel
p20 = pd.read_parquet(
    f"{P_20}/part2_native_strategies/cache_20cm_panel.parquet",
    columns=["dt", "prev_dt", "c6", "open", "zt_px", "o_pct", "is_st_pit", "prev_is_zt", "prev_streak", "mkt20_zt_cnt", "mkt20_dt_cnt", "mkt20_ew_ret"],
)
p20 = p20[p20["is_st_pit"].fillna(0) == 0].copy()
p20["open_is_zt"] = (p20["open"] >= p20["zt_px"] - 0.01) & (p20["zt_px"] > 0)
p20["prev_1b"] = (p20["prev_is_zt"].fillna(0) == 1) & (p20["prev_streak"].fillna(0) == 1)
p20["prev_1b_deep"] = p20["prev_1b"] & (p20["o_pct"] <= -0.03)

d20 = p20.groupby("dt", as_index=False).agg(
    mkt20_0925_zt=("open_is_zt", "sum"),
    mkt20_zt=("mkt20_zt_cnt", "first"),
    mkt20_dt=("mkt20_dt_cnt", "first"),
    mkt20_ew=("mkt20_ew_ret", "first"),
    p1b_cnt=("prev_1b", "sum"),
    p1b_deep_cnt=("prev_1b_deep", "sum"),
).sort_values("dt").reset_index(drop=True)
p1b_o = p20[p20["prev_1b"]].groupby("dt")["o_pct"].mean().rename("p1b_open_avg")
d20 = d20.merge(p1b_o, on="dt", how="left")
d20["prev_mkt20_zt"] = d20["mkt20_zt"].shift(1)
d20["prev_mkt20_dt"] = d20["mkt20_dt"].shift(1)
d20["next_mkt20_0925_zt"] = d20["mkt20_0925_zt"].shift(-1)
d20["prev_dt_10"] = d20["dt"].shift(1)

# 20cm V1.1 daily signal flags (A76 & S82)
v11 = pd.read_csv(f"{P_20}/v11_unified_redteam_attack/final_v11_ledger.csv")
v11_by_d = v11.groupby("buy_date", as_index=False).agg(v11_a76_cnt=("score", "count"), v11_max_sc=("score", "max"))
d20 = d20.merge(v11_by_d, left_on="dt", right_on="buy_date", how="left").drop(columns=["buy_date"])
d20["v11_a76_cnt"] = d20["v11_a76_cnt"].fillna(0).astype(int)
d20["v11_max_sc"] = d20["v11_max_sc"].fillna(0.0)

# 2. Load 10cm daily OHLC/amount/mcap + zt_micro_tape seal_amount
cols_d = ["date", "ticker", "open", "close", "amount", "oshare"]
da = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", columns=cols_d, filters=[("date", ">=", pd.Timestamp("2021-01-01"))])
dd = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols_d, filters=[("date", ">=", pd.Timestamp("2021-01-01"))])
d10 = pd.concat([da, dd], ignore_index=True)
d10["c6"] = d10["ticker"].astype(str).str[:6]
d10 = d10[d10["c6"].str.startswith(("00", "60")) & (~d10["ticker"].astype(str).str.endswith(".BJ"))].copy()
d10["dt"] = pd.to_datetime(d10["date"]).dt.strftime("%Y-%m-%d")
d10 = d10.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="first")
d10["prev_c"] = d10.groupby("c6")["close"].shift(1)
d10["o_pct"] = d10["open"] / d10["prev_c"] - 1.0
d10["mcap_yi"] = d10["close"] * d10["oshare"] / 1e8  # check oshare unit below
# Detect amount & oshare unit
med_amt = d10["amount"].median()
amt_mult = 1000.0 if med_amt < 1e7 else 1.0
d10["amt_yuan"] = d10["amount"] * amt_mult
med_os = d10["oshare"].dropna().median()
os_mult = 1e4 if med_os < 1e7 else 1.0
d10["mcap_yi"] = d10["close"] * d10["oshare"] * os_mult / 1e8

con_zt = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
zt = pd.read_sql_query("SELECT trade_date AS dt, sec_code AS c6, seal_amount, open_board_count, board_count FROM zt_micro_tape WHERE trade_date >= '2021-01-01'", con_zt)
con_zt.close()
zt["c6"] = zt["c6"].astype(str).str.zfill(6)
zt = zt.merge(d10[["c6", "dt", "amt_yuan", "mcap_yi"]], on=["c6", "dt"], how="left")
zt["seal_ratio"] = np.where(zt["amt_yuan"] > 0, zt["seal_amount"] / zt["amt_yuan"], np.nan)
zt_map = zt.set_index(["c6", "dt"])[["seal_ratio", "seal_amount", "open_board_count", "mcap_yi"]]

# 3. Helper to split IS (<=2024-08-31), OOS (>=2024-09-01), 2026 (>=2026-01-01)
def stat_split(df_s, cond_col):
    out = {}
    for p_name, m in [("ALL", df_s["buy_date"] >= "2021-01-01"), ("IS", df_s["buy_date"] <= "2024-08-31"),
                      ("OOS", df_s["buy_date"] >= "2024-09-01"), ("2026", df_s["buy_date"] >= "2026-01-01")]:
        sub = df_s[m]
        h = sub[sub[cond_col] == True]["net_ret"].to_numpy()
        nh = sub[sub[cond_col] == False]["net_ret"].to_numpy()
        out[p_name] = {
            "hit_n": int(len(h)), "hit_wr": round(float((h > 0).mean() * 100), 1) if len(h) else None,
            "hit_avg": round(float(h.mean() * 100), 2) if len(h) else None,
            "base_n": int(len(nh)), "base_wr": round(float((nh > 0).mean() * 100), 1) if len(nh) else None,
            "base_avg": round(float(nh.mean() * 100), 2) if len(nh) else None,
            "delta": round(float((h.mean() - nh.mean()) * 100), 2) if (len(h) and len(nh)) else None,
        }
    return out

ledgers = {
    "3to4_V41": f"{P_LED}/ledger_3to4_v41_clean.csv",
    "high_V51": f"{P_LED}/ledger_high_v51_clean.csv",
    "pry_ss165": f"{P_LED}/ledger_pry_v21_ss165_clean.csv",
    "pry_top1": f"{P_LED}/ledger_pry_v21_top1_clean.csv",
    "2to3_V21": f"{P_LED}/ledger_2to3_v21_opt_std90_clean.csv",
    "1to2_V19": f"{P_LED}/ledger_1to2_v19_clean.csv",
    "combined_5S": f"{P_LED}/ledger_combined_5strat_v191_slot1_clean.csv",
}

d10_idx = d10.set_index(["c6", "dt"])[["o_pct", "mcap_yi"]]
results = {}
for sname, fp in ledgers.items():
    df = pd.read_csv(fp, dtype={"code": str})
    df["c6"] = df["code"].astype(str).str.zfill(6)
    df = df.merge(d20, left_on="buy_date", right_on="dt", how="left")
    # Attach buy_date o_pct & prev_dt seal_ratio + mcap_yi
    df["buy_op"] = [d10_idx.loc[(c, d), "o_pct"] if (c, d) in d10_idx.index else np.nan for c, d in zip(df["c6"], df["buy_date"])]
    df["t0_seal_r"] = [zt_map.loc[(c, pdt), "seal_ratio"] if (c, pdt) in zt_map.index else np.nan for c, pdt in zip(df["c6"], df["prev_dt_10"])]
    df["t0_mcap"] = [d10_idx.loc[(c, pdt), "mcap_yi"] if (c, pdt) in d10_idx.index else np.nan for c, pdt in zip(df["c6"], df["prev_dt_10"])]
    df["sig_yizi20"] = df["mkt20_0925_zt"].fillna(0) >= 1
    df["sig_prev20zt16"] = df["prev_mkt20_zt"].fillna(0) >= 16
    df["sig_prev20dt3"] = df["prev_mkt20_dt"].fillna(0) >= 3
    df["sig_hold_d1_20dt3"] = df["mkt20_dt"].fillna(0) >= 3
    df["sig_hold_d2_yizi20"] = df["next_mkt20_0925_zt"].fillna(0) >= 1
    df["sig_seal10_neg"] = (df["t0_seal_r"].fillna(-1) >= 0.10) & (df["buy_op"].fillna(0) < 0)
    df["sig_seal10_all"] = df["t0_seal_r"].fillna(-1) >= 0.10
    df["sig_v11_a76"] = df["v11_a76_cnt"] >= 1
    df["sig_v11_s82"] = df["v11_max_sc"] >= 82.0
    df["sig_20p1b_deep2"] = df["p1b_deep_cnt"].fillna(0) >= 2
    df["sig_20p1b_avgneg2"] = df["p1b_open_avg"].fillna(0) <= -0.02

    sres = {"n": int(len(df)), "mcap_by_yr": {str(y): round(float(g["t0_mcap"].median()), 1) for y, g in df.groupby(df["buy_date"].str[:4]) if g["t0_mcap"].notna().any()}}
    for col in ["sig_yizi20", "sig_prev20zt16", "sig_prev20dt3", "sig_hold_d1_20dt3", "sig_hold_d2_yizi20",
                "sig_seal10_neg", "sig_seal10_all", "sig_v11_a76", "sig_v11_s82", "sig_20p1b_deep2", "sig_20p1b_avgneg2"]:
        sres[col] = stat_split(df, col)
    results[sname] = sres

# 4. Task A-5 Drift Audit (Xueqiu coverage by year, KPL plate_sz by year, 10cm ZT mcap median by year)
con_cm = sqlite3.connect(f"file:{SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
xq_yr = pd.read_sql_query("SELECT substr(pub_datetime_cst,1,4) AS yr, source, COUNT(*) AS posts, COUNT(DISTINCT symbol) AS syms FROM community_posts WHERE pub_datetime_cst >= '2021-01-01' GROUP BY 1,2 ORDER BY 1,2", con_cm)
con_cm.close()

zt_mcap_yr = zt[zt["mcap_yi"].notna()].groupby(zt["dt"].str[:4])["mcap_yi"].agg(["count", "median", lambda s: s.quantile(0.75), lambda s: (s > 90).mean() * 100])
zt_mcap_yr.columns = ["zt_cnt", "mcap_med_yi", "mcap_p75_yi", "pct_gt90yi"]

kpl_rows = []
with open(f"{SIM}/data/kpl_plates_5y_2021_2026_complete.jsonl", encoding="utf-8") as f:
    for line in f:
        o = json.loads(line)
        dt = str(o.get("date") or o.get("trade_date") or "")[:10]
        pls = o.get("plates") or o.get("data") or []
        if dt >= "2021-01-01" and isinstance(pls, list) and pls:
            szs = [int(p.get("sz") or p.get("count") or len(p.get("stocks", []))) for p in pls if isinstance(p, dict)]
            if szs: kpl_rows.append((dt[:4], len(szs), max(szs), int(max(szs) > 35)))
kpl_df = pd.DataFrame(kpl_rows, columns=["yr", "n_plates", "max_sz", "gt35"])
kpl_yr = kpl_df.groupby("yr").agg(days=("n_plates", "count"), avg_plates=("n_plates", "mean"), avg_max_sz=("max_sz", "mean"), pct_gt35=("gt35", lambda s: s.mean() * 100)).round(2)

out_obj = {"signals": results, "xq_by_yr": xq_yr.to_dict("records"), "zt_mcap_yr": zt_mcap_yr.round(2).to_dict("index"), "kpl_yr": kpl_yr.to_dict("index")}
with open(f"{OUT}/summary_rd023_pm.json", "w", encoding="utf-8") as f:
    json.dump(out_obj, f, ensure_ascii=False, indent=2)

# Print compact high-signal summary (<=3KB)
print("=== COMPACT RD023 PM AUDIT SUMMARY ===")
for sname in ["3to4_V41", "high_V51", "pry_ss165", "2to3_V21", "1to2_V19", "combined_5S"]:
    sr = results[sname]
    print(f"\n[{sname} N={sr['n']}] mcap_med_yr={sr['mcap_by_yr']}")
    for sig in ["sig_yizi20", "sig_prev20zt16", "sig_prev20dt3", "sig_hold_d1_20dt3", "sig_hold_d2_yizi20", "sig_seal10_neg", "sig_seal10_all", "sig_v11_a76", "sig_20p1b_deep2"]:
        d_is, d_oos, d_26 = sr[sig]["IS"], sr[sig]["OOS"], sr[sig]["2026"]
        if (d_is["hit_n"] + d_oos["hit_n"]) == 0: continue
        # Print only signals with >=3 total hits
        if (d_is["hit_n"] + d_oos["hit_n"]) < 3: continue
        print(f"  {sig:18s} | IS: n={d_is['hit_n']:2d} d={str(d_is['delta']):>6s}% (WR {d_is['hit_wr']} vs {d_is['base_wr']}) | OOS: n={d_oos['hit_n']:2d} d={str(d_oos['delta']):>6s}% (WR {d_oos['hit_wr']} vs {d_oos['base_wr']}) | 26: n={d_26['hit_n']:2d} d={str(d_26['delta']):>6s}%")
print("\n=== DRIFT: XQ BY YEAR ===")
print(xq_yr.to_string(index=False))
print("\n=== DRIFT: 10CM ZT MCAP BY YEAR ===")
print(zt_mcap_yr.round(2).to_string())
print("\n=== DRIFT: KPL BY YEAR ===")
print(kpl_yr.to_string())
