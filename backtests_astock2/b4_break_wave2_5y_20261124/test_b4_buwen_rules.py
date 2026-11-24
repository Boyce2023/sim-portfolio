#!/opt/homebrew/bin/python3.13
"""PIT Backtest: 4-Board-Broken (4板断板无5板) Wave-2 Strategy under Buwen's 3 Rules.
Tests BOTH:
1. Exact Nov 2026 (2026-11-02 ~ 2026-11-23) 8-stock echelon cohort (single-slot rotation + collision sensitivity).
2. Full 5-Year (2021-11-24 ~ 2026-11-23) PIT out-of-sample verification (D15: single-slot, daily EW, 5Y/3Y/2026,
   limit-down exit deferral, 0.30% RT fee, net excess vs sh000300, theme-echelon & break-day red/green splits).
Strictly NO yfinance.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

SIM = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
FEE = 0.003  # 0.30% round-trip

# 1. Load 5Y A-share daily (non-ST 00/60) + KPL plates + HS300
st_set = set(json.load(open(SIM / "data/st_universe.json"))["codes"])
df = pd.read_parquet(
    SIM / "data/cn_hk_price_db/a_daily.parquet",
    columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "turn", "amount"],
    filters=[("date", ">=", pd.Timestamp("2021-10-01"))],
).sort_values(["ticker", "date"])
df["c6"] = df["ticker"].str[:6]
df = df[df["c6"].str.startswith(("00", "60")) & (~df["c6"].isin(st_set))].copy()

g = df.groupby("ticker", sort=False)
df["prev_c"] = g["adj_close"].shift(1)
ratio = df["adj_close"] / df["close"].replace(0, np.nan)
df["adj_high"] = df["high"] * ratio
df["adj_low"] = df["low"] * ratio
df["adj_open"] = df["open"] * ratio
df["pct"] = df["adj_close"] / df["prev_c"] - 1.0
df["hi_pct"] = df["adj_high"] / df["prev_c"] - 1.0
df["zt_px"] = (df["prev_c"] * 1.10 + 1e-9).round(2)
df["dt_px"] = (df["prev_c"] * 0.90 + 1e-9).round(2)
df["is_zt"] = (df["adj_close"] >= df["zt_px"] - 0.005) & (df["pct"] >= 0.094)
df["is_dt_lock"] = (df["adj_close"] <= df["dt_px"] + 0.005) & (df["pct"] <= -0.094)

def calc_streak(s):
    out, cur = np.zeros(len(s), dtype=int), 0
    for i, v in enumerate(s):
        cur = cur + 1 if v else 0
        out[i] = cur
    return out

df["streak"] = g["is_zt"].transform(calc_streak)
df["next_is_zt"] = g["is_zt"].shift(-1)

# Load KPL plate map: (date_str, c6) -> (plate, plate_size)
NON_THEME = {"其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"}
EVENT_KWS = ("实控人变更", "股权转让", "并购重组", "摘帽", "回购")
kpl_map = {}
with open(SIM / "data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
    for ln in f:
        if not ln.strip(): continue
        obj = json.loads(ln)
        dt = obj.get("date", "")
        if dt < "2021-10-01": continue
        for pl in obj.get("plates", []):
            pnm = pl.get("plate") or ""
            sts = pl.get("stocks", [])
            psz = len(sts)
            for st in sts:
                c6 = str(st[0])[:6]
                rsn = " ".join(str(x) for x in st[2:])
                kpl_map[(dt, c6)] = (pnm, psz, rsn)

# Load HS300 for benchmark parity
idx_js = json.load(open(SIM / "backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
hs = pd.Series({pd.Timestamp(dt): float(val["close"] if isinstance(val, dict) else val) for dt, val in idx_js["sh000300"].items()}).sort_index()

# Build per-ticker indexed arrays for fast trade simulation
by_tk = {tk: sub.reset_index(drop=True) for tk, sub in df.groupby("ticker", sort=False)}

# Simulate exact Buwen trade from break-day (idx_brk = idx4 + 1) close
# Rules:
#   - Buy at idx_brk close (if idx_brk closed locked limit-down? Still buyable on sell-1; flag it!)
#   - On day h >= 1 (idx = idx_brk + h):
#     (a) If intraday hi_pct >= +9.8% AND not is_zt -> SELL at close (Rule 3)
#     (b) If h == 2 AND cum_ret < min_rally_d2 (e.g. +5.0% or +8.0%) -> SELL at close (Rule 2)
#     (c) If h >= 3 AND not is_zt (wave-2 breaks / stops sealing, or h >= 6) -> SELL at close
#     (d) Physical limit-down deferral: if intended exit day closes at locked limit-down (is_dt_lock & open==close==low),
#         defer exit to next day open/close when openable!
def sim_trade(sub, idx_brk, min_rally_d2=0.08, max_hold=6, use_blow98=True, use_d2_cut=True):
    entry_dt = sub["date"].iloc[idx_brk]
    entry_px = float(sub["adj_close"].iloc[idx_brk])
    n = len(sub)
    exit_idx = None
    reason = ""
    for h in range(1, max_hold + 1):
        j = idx_brk + h
        if j >= n:
            exit_idx = n - 1
            reason = "未满(截止11.23)"
            break
        px = float(sub["adj_close"].iloc[j])
        hi_p = float(sub["hi_pct"].iloc[j])
        zt = bool(sub["is_zt"].iloc[j])
        cum = px / entry_px - 1.0
        # Rule 3: intraday >= 9.8% & unsealed -> sell at close
        if use_blow98 and hi_p >= 0.098 and not zt:
            exit_idx, reason = j, f"D{h}冲9.8%炸板卖"
            break
        # Rule 2: within 2 days no big rally -> sell at D2 close
        if use_d2_cut and h == 2 and cum < min_rally_d2:
            exit_idx, reason = j, f"D2未大涨(<+{min_rally_d2*100:.0f}%)止损"
            break
        # Natural wave-2 top exit: after D2 big rally, exit on first non-ZT day (h>=3)
        if h >= 3 and not zt:
            exit_idx, reason = j, f"D{h}二波断板止盈"
            break
    if exit_idx is None:
        exit_idx, reason = min(idx_brk + max_hold, n - 1), f"D{max_hold}满期止盈"
    # Physical limit-down sell deferral: if locked limit-down (low==high==close and pct<=-9.4%), defer to next openable day open
    ex_px = float(sub["adj_close"].iloc[exit_idx])
    deferred = False
    while exit_idx < n - 1 and bool(sub["is_dt_lock"].iloc[exit_idx]) and abs(sub["high"].iloc[exit_idx] - sub["low"].iloc[exit_idx]) < 1e-6:
        exit_idx += 1
        ex_px = float(sub["adj_open"].iloc[exit_idx])
        deferred = True
    if deferred:
        reason += "(一字跌停顺延)"
    net_ret = (ex_px * (1 - FEE / 2)) / (entry_px * (1 + FEE / 2)) - 1.0
    return {
        "entry_dt": entry_dt, "exit_dt": sub["date"].iloc[exit_idx],
        "hold_d": int(exit_idx - idx_brk), "entry_px": entry_px, "exit_px": ex_px,
        "net_ret": net_ret, "reason": reason,
    }

# Collect all 4-board-broken events from 2021-11-24 ~ 2026-11-20
events = []
for tk, sub in by_tk.items():
    idxs = np.where((sub["streak"].values == 4) & (sub["next_is_zt"].values == False))[0]
    for i4 in idxs:
        d4 = sub["date"].iloc[i4]
        if d4 < pd.Timestamp("2021-11-24") or i4 + 1 >= len(sub):
            continue
        i_brk = i4 + 1
        d4_s = d4.strftime("%Y-%m-%d")
        c6 = tk[:6]
        pnm, psz, rsn = kpl_map.get((d4_s, c6), ("其他", 1, ""))
        has_echelon = (pnm not in NON_THEME) and (psz >= 2) and (not any(ek in (pnm + rsn) for ek in EVENT_KWS))
        brk_pct = float(sub["pct"].iloc[i_brk])
        t_res = sim_trade(sub, i_brk, min_rally_d2=0.08)
        t_res5 = sim_trade(sub, i_brk, min_rally_d2=0.05)
        events.append({
            "d4": d4, "ticker": tk, "c6": c6, "plate": pnm, "psz": psz, "has_echelon": has_echelon,
            "brk_pct": brk_pct, "turn4": float(sub["turn"].iloc[i4]), "amt_brk": float(sub["amount"].iloc[i_brk]),
            "t8": t_res, "t5": t_res5,
        })
ev_df = pd.DataFrame(events).sort_values(["d4", "ticker"]).reset_index(drop=True)

# === PART 1: EXACT NOV 2026 (2026-11-02 ~ 2026-11-23) 8 ECHELON STOCKS (incl. 羊/东方 per Buwen) ===
nov_keep = {"002172", "002086", "600261", "002088", "603381", "603706", "002148", "002685"}
nms = {"002172":"澳洋健康","002086":"东方海洋","600261":"阳光照明","002088":"鲁阳节能","603381":"永臻股份","603706":"东方环宇","002148":"北纬科技","002685":"华东重机"}
nov = ev_df[(ev_df["d4"] >= pd.Timestamp("2026-11-02")) & (ev_df["c6"].isin(nov_keep))].copy()
print("=== PART 1: 11.02起 8只有梯队四板断板股（含羊/东方梯队）逐笔明细（扣0.30%费） ===")
for _, r in nov.iterrows():
    t = r["t8"]
    print(f"  入:{str(t['entry_dt'])[5:10]} 出:{str(t['exit_dt'])[5:10]} | {r['c6']} {nms[r['c6']]:4s} | 断板{r['brk_pct']*100:+5.1f}% | 持{t['hold_d']}天 | 净={t['net_ret']*100:+6.2f}% | {t['reason']}")

def run_single_slot(df_sub, key="t8", tie_mode="ew_day"):
    # Group by entry_dt (break day); single slot cannot enter new trade until prev exit_dt <= entry_dt
    # Note: A-share sell at close of exit_dt -> cash ready next day, OR can buy same day close? At 15:00 sell close & buy close same day is feasible (T+0 cash reuse after selling T+1 stock!); test BOTH strict exit_dt < entry_dt AND exit_dt <= entry_dt!
    nav = 1.0
    busy_until = pd.Timestamp("1900-01-01")
    taken = []
    for dt, grp in df_sub.groupby(df_sub[key].apply(lambda x: x["entry_dt"])):
        if dt <= busy_until:
            continue
        if tie_mode == "ew_day":
            rets = [x["net_ret"] for x in grp[key]]
            avg_r = float(np.mean(rets))
            max_ex = max(x["exit_dt"] for x in grp[key])
            nav *= (1.0 + avg_r)
            busy_until = max_ex
            taken.append((str(dt)[:10], str(max_ex)[:10], list(grp["c6"]), avg_r))
        elif tie_mode == "lowest_brk":
            row = grp.sort_values("brk_pct", ascending=True).iloc[0]
            x = row[key]
            nav *= (1.0 + x["net_ret"])
            busy_until = x["exit_dt"]
            taken.append((str(dt)[:10], str(x["exit_dt"])[:10], [row["c6"]], x["net_ret"]))
        elif tie_mode == "highest_amt":
            row = grp.sort_values("amt_brk", ascending=False).iloc[0]
            x = row[key]
            nav *= (1.0 + x["net_ret"])
            busy_until = x["exit_dt"]
            taken.append((str(dt)[:10], str(x["exit_dt"])[:10], [row["c6"]], x["net_ret"]))
    rets_arr = np.array([t[3] for t in taken])
    eq = np.cumprod(1.0 + rets_arr) if len(rets_arr) else np.array([1.0])
    mdd = float((eq / np.maximum.accumulate(np.insert(eq, 0, 1.0))[1:] - 1.0).min() * 100) if len(eq) else 0.0
    wr = float((rets_arr > 0).mean() * 100) if len(rets_arr) else 0.0
    avg = float(rets_arr.mean() * 100) if len(rets_arr) else 0.0
    return nav, mdd, len(taken), wr, avg, taken

print("\n=== PART 1B: 11月8股单仓满仓轮动（无后视镜同日冲突对照） ===")
for lbl, sub in [("8股全做(含收涨断板)", nov), ("仅做断板收跌(5股)", nov[nov["brk_pct"] < 0])]:
    for tm, tnm in [("ew_day", "同日等权"), ("lowest_brk", "同日选跌幅更深"), ("highest_amt", "同日选成交最大")]:
        nav, mdd, n_t, wr, avg, tkns = run_single_slot(sub, "t8", tm)
        print(f"  {lbl:16s} | {tnm:12s} | {n_t}笔 | 胜率{wr:4.0f}% | 单笔均{avg:+6.2f}% | 累计={(nav-1)*100:+6.2f}% | 回撤{mdd:5.1f}% | 路径={[(x[0][5:],x[2],round(x[3]*100,1)) for x in tkns]}")

# === PART 2: FULL 5-YEAR PIT VERIFICATION (2021-11-24 ~ 2026-11-23, D15) ===
print("\n=== PART 2: 全5年(2021.11~2026.11) 严格PIT防伪实证（检验是否11月小样本幻觉！） ===")
hs_5y = (hs.loc["2026-11-23"] / hs.loc["2021-11-24":].iloc[0] - 1.0) * 100
hs_3y = (hs.loc["2026-11-23"] / hs.loc["2023-11-24":].iloc[0] - 1.0) * 100
hs_26 = (hs.loc["2026-11-23"] / hs.loc["2026-01-01":].iloc[0] - 1.0) * 100
print(f"基准沪深300: 5Y={hs_5y:+.2f}% | 3Y={hs_3y:+.2f}% | 2026={hs_26:+.2f}%")

slices = [
    ("全市场4板断板(无过滤)", ev_df),
    ("有KPL梯队(非NON_THEME且>=2只)", ev_df[ev_df["has_echelon"]]),
    ("有KPL梯队 + 断板日收跌(<0%)", ev_df[ev_df["has_echelon"] & (ev_df["brk_pct"] < 0)]),
    ("有KPL梯队 + 断板日收涨(>=0%)", ev_df[ev_df["has_echelon"] & (ev_df["brk_pct"] >= 0)]),
    ("全市场4板断板 + 断板日收跌(<0%)", ev_df[ev_df["brk_pct"] < 0]),
]
for slbl, sdf in slices:
    for per_lbl, cut, bm in [("5Y", "2021-11-24", hs_5y), ("3Y", "2023-11-24", hs_3y), ("2026", "2026-01-01", hs_26)]:
        psub = sdf[sdf["d4"] >= pd.Timestamp(cut)]
        nav, mdd, n_t, wr, avg, _ = run_single_slot(psub, "t8", "ew_day")
        ew_all = psub["t8"].apply(lambda x: x["net_ret"])
        ew_wr = (ew_all > 0).mean() * 100 if len(ew_all) else 0
        ew_avg = ew_all.mean() * 100 if len(ew_all) else 0
        print(f"  {slbl:28s} | {per_lbl:4s} | 单仓:{n_t:3d}笔 胜{wr:4.1f}% 均{avg:+5.2f}% 累计{(nav-1)*100:+6.1f}%(超300 {(nav-1)*100-bm:+6.1f}%) 回撤{mdd:5.1f}% | 全样本等权(n={len(psub):3d}):胜{ew_wr:4.1f}% 均{ew_avg:+5.2f}%")
