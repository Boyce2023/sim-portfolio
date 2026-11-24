#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD023 Step 0: Build 100% PIT-clean enriched 20cm research dataset + verify V1.1 baseline."""
import glob, json, os, pickle, re, sqlite3, sys, time
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
V1_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"
P2_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
V11_DIR = f"{BASE}/backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack"
PC_DIR = f"{BASE}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191"
OUT_DIR = f"{BASE}/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, V1_DIR); sys.path.insert(0, P2_DIR); sys.path.insert(0, V11_DIR)

from v11_core import V11_EXIT_CFG, compute_scorecard_v11, sim_v11_exit
from backtest_utils import _sim_k_slots

REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|严重异常波动)")
REG_EXC = re.compile(r"(?:回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")


def build_mkt_and_10cm_stats(all_dts: list[str], sh300: dict, sz399107: dict):
    """Build daily 10cm/all market stats (0925 ZT, EOD ZT/DT, seal rate, 4b+ rebound rate)."""
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close"]
    flt = ds.field("date") >= pd.Timestamp("2020-11-01")
    a1 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    a2 = ds.dataset(f"{BASE}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    a1["dl"], a2["dl"] = 0, 1
    df = pd.concat([a1, a2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & (df["close"] > 0) & (df["adj_close"] > 0)].copy()
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    # ST mask (conservative PIT from zt_micro_tape + st_universe)
    st_set = set()
    if os.path.exists(f"{BASE}/data/st_universe.json"):
        st_set = {str(x)[:6].zfill(6) for x in json.load(open(f"{BASE}/data/st_universe.json", encoding="utf-8")).get("codes", [])}

    g = df.groupby("c6", sort=False)
    sc = df["adj_close"] / df["close"]
    pac = g["adj_close"].shift(1)
    ret = df["adj_close"] / pac - 1.0
    h_pct = (df["high"] * sc) / pac - 1.0
    o_pct = (df["open"] * sc) / pac - 1.0
    is20 = df["c6"].str.startswith(("30", "688", "689"))
    lim = np.where(is20, 0.20, 0.10)
    r_th = np.where(is20, 0.195, 0.095)
    abn = ret.abs() > np.where(is20, 0.22, 0.12)
    pex = pac / sc
    zt_px = np.floor(pex * (1.0 + lim) * 100.0 + 0.5) / 100.0
    dt_px = np.floor(pex * (1.0 - lim) * 100.0 + 0.5) / 100.0

    df["ret"] = ret
    df["is20"] = is20
    df["is10"] = df["c6"].str.startswith(("00", "60"))
    df["non_st"] = ~df["c6"].isin(st_set)
    df["is_zt"] = (pac > 0) & (df["close"] >= zt_px - 0.011) & (ret >= r_th) & (~abn)
    df["touch_zt"] = (pac > 0) & (df["high"] >= zt_px - 0.011) & (h_pct >= r_th) & (~abn)
    df["is_dt"] = (pac > 0) & (df["close"] <= dt_px + 0.011) & (ret <= -r_th) & (~abn)
    df["open_zt"] = (pac > 0) & (df["open"] >= zt_px - 0.011) & (o_pct >= r_th)

    s10 = (df["is10"] & df["non_st"] & df["is_zt"]).astype(int)
    s10_sh = df.groupby("c6")["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak10"] = s10.groupby([df["c6"], (s10 != s10_sh).cumsum()]).cumsum() * s10
    df["prev_streak10"] = df.groupby("c6")["streak10"].shift(1).fillna(0).astype(int)

    # Daily stats & 4b+ rebound rate
    mkt_stats = {}
    prev_brk = set()
    reb_hist = []
    for dt, grp in df[df["dt"] >= "2020-12-01"].groupby("dt", sort=True):
        ns = grp[grp["non_st"]]
        ns10 = ns[ns["is10"]]
        zt10 = int(ns10["is_zt"].sum())
        tzt10 = int(ns10["touch_zt"].sum())
        zt_all = int(ns["is_zt"].sum())
        tzt_all = int(ns["touch_zt"].sum())
        if prev_brk:
            sr = ns10[ns10["c6"].isin(prev_brk)]
            reb_hist.append((int((sr["ret"] > 0).sum()), len(prev_brk)))
        else:
            reb_hist.append((0, 0))
        prev_brk = set(ns10[(ns10["prev_streak10"] >= 4) & (~ns10["is_zt"])]["c6"].tolist())
        w10 = reb_hist[-10:]
        reb10 = sum(x[0] for x in w10) / max(1, sum(x[1] for x in w10))
        mkt_stats[dt] = {
            "mkt10_nonst_zt": zt10, "mkt10_seal_rate": zt10 / tzt10 if tzt10 > 0 else 1.0,
            "mkt_all_nonst_zt": zt_all, "mkt_all_seal_rate": zt_all / tzt_all if tzt_all > 0 else 1.0,
            "mkt_all_nonst_dt": int(ns["is_dt"].sum()),
            "mkt10_nonst_0925_zt": int(ns10["open_zt"].sum()),
            "mkt_all_nonst_0925_zt": int(ns["open_zt"].sum()),
            "reb4_10d": reb10, "reb4_10d_den": sum(x[1] for x in w10),
        }

    # Build lookup for 10cm clean ledger T+1 09:25 open prices
    led_codes = set()
    for fn in ["ledger_3to4_v41_clean.csv", "ledger_high_v51_clean.csv", "ledger_pry_v21_top1_clean.csv",
               "ledger_2to3_v21_opt_std90_clean.csv", "ledger_1to2_v19_clean.csv"]:
        d_l = pd.read_csv(f"{PC_DIR}/{fn}")
        led_codes.update(d_l["code"].astype(str).str.zfill(6).unique())
    sub_l = df[df["c6"].isin(led_codes)].copy()
    sub_l["ao"] = sub_l["open"] * (sub_l["adj_close"] / sub_l["close"])
    sub_l["ac"] = sub_l["adj_close"]
    sub_l["next_dt"] = sub_l.groupby("c6")["dt"].shift(-1).fillna("")
    sub_l["next_ao"] = sub_l.groupby("c6")["ao"].shift(-1)
    bar_10 = {(r.c6, r.dt): (float(r.ao), float(r.ac), str(r.next_dt), float(r.next_ao) if pd.notna(r.next_ao) else np.nan, bool(r.is_zt))
              for r in sub_l.itertuples(index=False)}
    return mkt_stats, bar_10


def compute_holding_dev93_and_reg(pool: pd.DataFrame, sh300: dict, sz399107: dict) -> pd.DataFrame:
    """Compute exact PIT 10d100% & 30d200% 93%-cap prices for D2..D10 and holding-day reg_new."""
    c6_set = set(pool["c6"].unique())
    pan = pd.read_parquet(f"{P2_DIR}/cache_20cm_panel.parquet", columns=["c6", "dt", "ac", "adj_close", "close"])
    pan = pan[pan["c6"].isin(c6_set)].sort_values(["c6", "dt"]).reset_index(drop=True)
    dts_all = sorted(pan["dt"].unique())
    idx_ref = {d: sz399107.get(d, sh300.get(d, np.nan)) for d in dts_all}
    c_ac = {c: grp.set_index("dt")["ac"].to_dict() for c, grp in pan.groupby("c6")}
    dt_pos = {d: i for i, d in enumerate(dts_all)}

    # Load all reg notices
    reg_m = defaultdict(list)
    con_n = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, ti, ts in con_n.execute("SELECT sec_code, title, pub_datetime_cst FROM notices WHERE sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%'"):
        c6 = str(sc).zfill(6)
        if c6 in c6_set and REG_RE.search(str(ti or "")) and not REG_EXC.search(str(ti or "")):
            reg_m[c6].append(str(ts)[:19])
    con_n.close()
    rt = pd.read_parquet(f"{BASE}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    for r in rt[rt["c6"].isin(c6_set)].itertuples(index=False):
        if REG_RE.search(str(r.title or "")) and not REG_EXC.search(str(r.title or "")):
            reg_m[r.c6].append(str(r.pub_datetime_cst)[:19])
    for zf in glob.glob(f"{BASE}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6 = str(it[0]).zfill(6)
            if c6 in c6_set:
                reg_m[c6].append(str(it[2])[:10] + " 08:00:00")

    # Compute for each pool row, k=2..10: dev93_px (relative to ac at k-1 or raw adj), and reg_new in [f1_dt 09:00, f{k}_dt 09:00)
    out = pd.DataFrame(index=pool.index)
    for k in range(2, 11):
        caps = []
        regs = []
        for r in pool.itertuples(index=False):
            fk_dt = getattr(r, f"f{k}_dt", "")
            fkm_dt = getattr(r, f"f{k-1}_dt", "")
            if not fk_dt or not fkm_dt or fk_dt not in dt_pos or fkm_dt not in dt_pos:
                caps.append(np.nan); regs.append(0); continue
            # Regulatory check strictly before fk_dt 09:00
            tsl = reg_m.get(r.c6, [])
            regs.append(int(any(f"{r.f1_dt} 09:00:00" <= x < f"{fk_dt} 09:00:00" for x in tsl)))
            # 10d+100% (93%) and 30d+200% (186%) cap using index up to fkm_dt (causal before fk open)
            p_m = dt_pos[fkm_dt]
            ir_prev = idx_ref.get(fkm_dt, np.nan)
            acm = c_ac[r.c6]
            bp = 1e18
            if pd.notna(ir_prev) and ir_prev > 0:
                for win, thr in [(9, 0.93), (29, 1.86)]:
                    for back in range(0, win):
                        if p_m - back - 1 < 0: break
                        db = dts_all[p_m - back - 1]
                        pb, ib = acm.get(db, np.nan), idx_ref.get(db, np.nan)
                        if pd.notna(pb) and pb > 0 and pd.notna(ib) and ib > 0:
                            bp = min(bp, pb * (1.0 + thr + (ir_prev / ib - 1.0)))
            caps.append(bp if bp < 1e17 else np.nan)
        out[f"f{k}_dev93_px"] = caps
        out[f"f{k}_reg_new"] = regs
    return out


def main():
    t0 = time.time()
    aux = pickle.load(open(f"{P2_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, sz_idx, ew20, all_dts = aux["sh300"], {}, aux["ew20_daily"], aux["all_dts"]
    idx_json = json.load(open(f"{BASE}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))
    sz399107 = {k: float(v) for k, v in idx_json.get("sz399107", {}).items()}

    print("[1/4] Building daily 10cm/all market stats & 10cm clean ledger bars...")
    mkt_stats, bar_10 = build_mkt_and_10cm_stats(all_dts, sh300, sz399107)

    print("[2/4] Loading V1.1 pool & verifying exact baseline reproduction...")
    df = pd.read_parquet(f"{V1_DIR}/p1_clean_candidates.parquet")
    pool = df[df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    sc, fm = compute_scorecard_v11(pool)
    pool["score"] = sc.values
    tr_base = sim_v11_exit(pool[pool["score"] >= 76.0], V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    s1, nv, mdd = _sim_k_slots(tr_base, 1)
    print(f"  Baseline A76 verified: N={len(s1)}, FULL={nv:.3f}x, MDD={mdd*100:.2f}% (target: 285, 349.775x, 35.91%)")
    assert len(s1) == 285 and abs(nv - 349.775) < 0.01

    print("[3/4] Attaching trailing sensors, holding dev93/reg, and csi at f1_dt...")
    csi_s = pd.Series([sh300[d] for d in sorted(sh300)], index=sorted(sh300))
    c1d, c5d = csi_s.pct_change(1).to_dict(), csi_s.pct_change(5).to_dict()
    pool["f1_csi_1d"] = pool["f1_dt"].map(c1d).fillna(0.0)
    pool["f1_csi_5d"] = pool["f1_dt"].map(c5d).fillna(0.0)
    for col in ["mkt10_nonst_zt", "mkt10_seal_rate", "mkt_all_nonst_zt", "mkt_all_seal_rate", "mkt_all_nonst_dt", "mkt10_nonst_0925_zt", "mkt_all_nonst_0925_zt", "reb4_10d"]:
        pool[f"t0_{col}"] = pool["dt"].map({k: v[col] for k, v in mkt_stats.items()})
        pool[f"f1_{col}"] = pool["f1_dt"].map({k: v[col] for k, v in mkt_stats.items()})
        if col == "mkt_all_nonst_0925_zt":
            for k in range(2, 6):
                pool[f"f{k}_{col}"] = pool[f"f{k}_dt"].map({kk: vv[col] for kk, vv in mkt_stats.items()})

    # 100% causal trailing 20d deep-open 20cm recovery sensor (settled f2_dt <= dt!)
    # Use all_deep = p1 with f1_o_pct in [-10%, -3%] and mkt20_zt_cnt < 16 (or even unfiltered)
    p_deep = df[df["f1_o_pct"].between(-0.10, -0.030)].sort_values("f1_dt").copy()
    p_deep["d2_red"] = (p_deep["f2_ac"] > p_deep["f1_ao"]).astype(float)
    p_deep["d1_red"] = (p_deep["f1_ac"] > p_deep["f1_ao"]).astype(float)
    dt_idx = {d: i for i, d in enumerate(all_dts)}
    s20_red, s20_n, s20_d1, s10_red, s10_n = [], [], [], [], []
    # Pre-extract arrays for fast scan
    pd_f1_idx = np.array([dt_idx.get(d, -1) for d in p_deep["f1_dt"]])
    pd_f2_dt = p_deep["f2_dt"].to_numpy()
    pd_f1_dt = p_deep["f1_dt"].to_numpy()
    pd_d2r = p_deep["d2_red"].to_numpy()
    pd_d1r = p_deep["d1_red"].to_numpy()
    for r in pool.itertuples(index=False):
        t0_i = dt_idx.get(r.dt, -1)
        m20 = (pd_f1_idx >= t0_i - 20) & (pd_f1_idx < t0_i) & (pd_f2_dt != "") & (pd_f2_dt <= r.dt)
        m10 = (pd_f1_idx >= t0_i - 10) & (pd_f1_idx < t0_i) & (pd_f2_dt != "") & (pd_f2_dt <= r.dt)
        s20_n.append(int(m20.sum()))
        s20_red.append(float(np.nanmean(pd_d2r[m20])) if m20.sum() >= 5 else np.nan)
        m20_d1 = (pd_f1_idx >= t0_i - 20) & (pd_f1_idx <= t0_i) & (pd_f1_dt <= r.dt)
        s20_d1.append(float(np.nanmean(pd_d1r[m20_d1])) if m20_d1.sum() >= 5 else np.nan)
        s10_n.append(int(m10.sum()))
        s10_red.append(float(np.nanmean(pd_d2r[m10])) if m10.sum() >= 3 else np.nan)
    pool["sensor20_n"] = s20_n; pool["sensor20_d2_red"] = s20_red; pool["sensor20_d1_red"] = s20_d1
    pool["sensor10_n"] = s10_n; pool["sensor10_d2_red"] = s10_red

    dev_reg = compute_holding_dev93_and_reg(pool, sh300, sz399107)
    pool = pd.concat([pool, dev_reg], axis=1)

    print("[4/4] Saving enriched cache & bar_10...")
    pool.to_parquet(f"{OUT_DIR}/rd023_pool_enriched.parquet", index=False)
    pickle.dump({"mkt_stats": mkt_stats, "bar_10": bar_10}, open(f"{OUT_DIR}/rd023_aux.pkl", "wb"))
    print(f"[DONE in {time.time()-t0:.2f}s] Saved {len(pool)} rows x {pool.shape[1]} cols")


if __name__ == "__main__":
    main()
