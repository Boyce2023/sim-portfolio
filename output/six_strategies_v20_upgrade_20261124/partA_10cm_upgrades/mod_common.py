#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Shared PIT builders, metrics (NO cap10m), anti-overfitting tests & physical checks."""
import bisect, glob, itertools, json, math, os, re, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta
import numpy as np, pandas as pd, pyarrow.dataset as ds, scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
WINDOWS = [("FULL", "2021-11-16", "2026-11-16"), ("IS", "2021-11-16", "2024-08-31"),
           ("OOS", "2024-09-01", "2026-11-16"), ("2026", "2026-01-01", "2026-11-16")]

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")
TOX_RE = re.compile(r"(?:减持计划|股东减持|减持股份|立案调查|收到立案|退市风险|违法违规|业绩预亏|预亏)")
REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|严重异常波动)")
REG_EXC = re.compile(r"(?:回复|回函|延期|核查意见|复牌|募集资金|监事|独立董事|保荐)")

def _shift_cal(dt_s: str, days: int) -> str:
    return (datetime.strptime(dt_s, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")

def _cnt_ts(arr: list | None, lo: str, hi: str) -> int:
    return max(0, bisect.bisect_left(arr, hi) - bisect.bisect_left(arr, lo)) if arr else 0

def _is_st_at(st_tl: dict, c6: str, cut_ts: str) -> int:
    tl = st_tl.get(c6)
    if not tl: return 0
    idx = bisect.bisect_left(tl[0], cut_ts)
    return int(tl[1][idx - 1]) if idx > 0 else 0

def get_csi_ret(sh300: dict, all_dts: list, s_dt: str, e_dt: str) -> float:
    dts = [d for d in all_dts if s_dt <= d <= e_dt]
    if not dts: return 0.0
    prevs = [d for d in all_dts if d < dts[0]]
    p0 = sh300[prevs[-1]] if prevs else sh300[dts[0]]
    return float(sh300[dts[-1]] / p0 - 1.0)

def calc_window_metrics(tr1s: list, eq_daily: list, s_dt: str, e_dt: str, sh300: dict, all_dts: list) -> dict:
    csi_pct = get_csi_ret(sh300, all_dts, s_dt, e_dt) * 100.0
    st = [t for t in tr1s if s_dt <= str(t["buy_date"]) <= e_dt]
    se = [float(r) for d, r in eq_daily if s_dt <= str(d) <= e_dt]
    eq_nav, eq_pk, eq_mdd = 1.0, 1.0, 0.0
    for r in se:
        eq_nav *= (1.0 + r); eq_pk = max(eq_pk, eq_nav); eq_mdd = max(eq_mdd, (eq_pk - eq_nav) / eq_pk)
    n = len(st)
    if n == 0:
        return {"trades": 0, "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0, "nav_1s": 1.0,
                "trim3_nav": 1.0, "trim5_nav": 1.0, "mdd_1s_pct": 0.0, "eq_days": len(se),
                "eq_nav": round(eq_nav, 2), "mdd_eq_pct": round(eq_mdd * 100.0, 2),
                "csi300_pct": round(csi_pct, 2), "excess_1s_pp": round(-csi_pct, 2),
                "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - csi_pct, 2)}
    rets = np.array([float(t["net_ret"]) for t in st], dtype=float)
    wins, losses = rets[rets > 0], rets[rets < 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) and len(losses)) else (99.9 if len(wins) else 0.0)
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r in rets:
        nav *= (1.0 + float(r)); pk = max(pk, nav); mdd = max(mdd, (pk - nav) / pk)
    s_rets = np.sort(rets)
    t3 = float(np.prod(1.0 + s_rets[:-3])) if n > 3 else 1.0
    t5 = float(np.prod(1.0 + s_rets[:-5])) if n > 5 else 1.0
    return {
        "trades": int(n), "win_rate_pct": round(wr, 2), "plr": round(plr, 2),
        "mean_ret_pct": round(float(rets.mean() * 100.0), 2),
        "nav_1s": round(nav, 2), "trim3_nav": round(t3, 2), "trim5_nav": round(t5, 2),
        "mdd_1s_pct": round(mdd * 100.0, 2), "eq_days": len(se), "eq_nav": round(eq_nav, 2),
        "mdd_eq_pct": round(eq_mdd * 100.0, 2), "csi300_pct": round(csi_pct, 2),
        "excess_1s_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_eq_pp": round((eq_nav - 1.0) * 100.0 - csi_pct, 2),
    }

def all_windows_metrics(tr1s: list, eq_daily: list, sh300: dict, all_dts: list) -> dict:
    return {wn: calc_window_metrics(tr1s, eq_daily, sd, ed, sh300, all_dts) for wn, sd, ed in WINDOWS}

def hlz_and_dsr150(tr1s: list, sh300: dict, all_dts: list, m_trials: int = 150) -> tuple[float, float]:
    n = len(tr1s)
    if n < 5: return 0.0, 0.0
    def _b(bd, ed):
        prevs = [d for d in all_dts if d < bd]
        posts = [d for d in all_dts if d <= ed]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dts[0]]
        return float(sh300[posts[-1]] / p0 - 1.0)
    ex = np.array([float(t["net_ret"]) - _b(str(t["buy_date"]), str(t["exit_date"])) for t in tr1s], float)
    sr = float(ex.mean() / ex.std(ddof=1)) if ex.std(ddof=1) > 1e-12 else 0.0
    t_val = sr * math.sqrt(n)
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(ex, fisher=False, bias=False))) if n > 3 else 3.0
    gm = 0.5772156649
    sr0 = (1.0 / math.sqrt(n - 1)) * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / m_trials) + gm * stats.norm.ppf(1.0 - 1.0 / (m_trials * math.e)))
    den = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2)))
    return round(t_val, 2), round(float(stats.norm.cdf((sr - sr0) * math.sqrt(n - 1) / den)), 4)

def calc_cscv_pbo(tr_lists: list, all_dts: list, s_blocks: int = 10) -> float:
    t_days = [d for d in all_dts if "2021-11-15" <= d <= "2026-11-16"]
    didx = {d: i for i, d in enumerate(t_days)}
    cols = []
    for trs in tr_lists:
        v = np.zeros(len(t_days), float)
        for t in trs:
            i = didx.get(str(t["exit_date"]))
            if i is not None: v[i] += float(t["net_ret"])
        cols.append(v)
    R = np.column_stack(cols)
    t_len = len(t_days); gs = t_len // s_blocks
    gidx = [list(range(i * gs, (i + 1) * gs if i < s_blocks - 1 else t_len)) for i in range(s_blocks)]
    omegas = []
    for te in itertools.combinations(range(s_blocks), s_blocks // 2):
        tri = [x for k in range(s_blocks) if k not in te for x in gidx[k]]
        tei = [x for k in te for x in gidx[k]]
        rt, re_ = R[tri], R[tei]
        st = np.where(rt.std(0, ddof=1) > 1e-12, rt.mean(0) / rt.std(0, ddof=1), 0.0)
        se = np.where(re_.std(0, ddof=1) > 1e-12, re_.mean(0) / re_.std(0, ddof=1), 0.0)
        b = int(np.argmax(st))
        omegas.append(float(np.mean(se > se[b])))
    return round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2)

def build_fb20_cln_dates_pit(cutoff_dt: str) -> dict:
    """Strict PIT <= cutoff_dt builder matching p1_clean_candidates deep-open (<= -3%) breadth."""
    ts_cut, dt_ts = f"{cutoff_dt} 23:59:59", pd.Timestamp(cutoff_dt)
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount"]
    flt = ds.field("date") <= dt_ts
    a1 = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    a2 = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    a1["dl"], a2["dl"] = 0, 1
    df = pd.concat([a1, a2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[df["ticker"].str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("30", "688", "689")) & (df["close"] > 0) & (df["adj_close"] > 0)].copy()
    df = df.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    df["list_age"] = df.groupby("c6", sort=False).cumcount() + 1
    df = df[df["dt"] >= "2020-08-24"].copy().reset_index(drop=True)
    g = df.groupby("c6", sort=False); sc = df["adj_close"] / df["close"]
    df["ao"], df["ac"] = df["open"] * sc, df["adj_close"]
    df["prev_ac"] = g["ac"].shift(1); df["ret"] = df["ac"] / df["prev_ac"] - 1.0; df["o_pct"] = df["ao"] / df["prev_ac"] - 1.0
    df["abn_ret"] = df["ret"].abs() > 0.22
    df["tradable"] = (df["volume"] > 0) & (df["open"] > 0) & (df["list_age"] > 10) & (~df["abn_ret"])
    zt_px = np.floor((df["prev_ac"] / sc) * 1.20 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["prev_ac"] > 0) & (df["close"] >= zt_px - 0.011) & (df["ret"] >= 0.195) & (~df["abn_ret"])
    df["is_yizi_zt"] = df["is_zt"] & (df["low"] == df["high"]) & (df["o_pct"] >= 0.195)
    s_zt = df["is_zt"].astype(int); s_sh = g["is_zt"].shift(1).fillna(False).astype(bool)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    df["f1_dt"] = g["dt"].shift(-1).fillna(""); df["f1_o_pct"] = g["o_pct"].shift(-1)
    df["f1_open_gt0"] = (g["open"].shift(-1).fillna(0) > 0)
    df = df[df["dt"] >= "2021-01-04"].copy().reset_index(drop=True)
    all20 = set(df["c6"].unique())
    st_ev, tox_m, reg_m = defaultdict(list), defaultdict(list), defaultdict(list)
    con_z = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for td, sc6, nm in con_z.execute("SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')", (cutoff_dt,)):
        s = str(nm or "").strip()
        if s: st_ev[str(sc6).zfill(6)].append((f"{td} 15:00:00", 1 if ("ST" in s or "退" in s) else 0))
    con_z.close()
    cand = df[df["tradable"] & (df["close"] >= 2.0) & df["is_zt"] & (df["streak"] == 1) & (~df["is_yizi_zt"]) & (df["amount"] >= 1e8) & df["f1_open_gt0"] & df["f1_o_pct"].between(-0.15, -0.030)].copy().reset_index(drop=True)
    cset = set(cand["c6"].unique())
    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc6, ti, ts in con_n.execute("SELECT sec_code, title, pub_datetime_cst FROM notices WHERE pub_datetime_cst <= ? AND (sec_code LIKE '30%' OR sec_code LIKE '688%' OR sec_code LIKE '689%')", (ts_cut,)):
        c6, ts_s, t_s = str(sc6).zfill(6), str(ts)[:19], str(ti or "")
        if c6 in all20:
            if ST_REV_RE.search(t_s) and "不" not in t_s[:10]: st_ev[c6].append((ts_s, 0))
            elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s): st_ev[c6].append((ts_s, 1))
        if c6 in cset:
            if TOX_RE.search(t_s): tox_m[c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg_m[c6].append(ts_s)
    con_n.close()
    rt = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
    for r in rt[(rt["pub_datetime_cst"].astype(str) <= ts_cut) & rt["c6"].isin(all20)].itertuples(index=False):
        t_s, ts_s = str(r.title or ""), str(r.pub_datetime_cst)[:19]
        if ST_REV_RE.search(t_s): st_ev[r.c6].append((ts_s, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s): st_ev[r.c6].append((ts_s, 1))
        if r.c6 in cset:
            if TOX_RE.search(t_s): tox_m[r.c6].append(ts_s)
            if REG_RE.search(t_s) and not REG_EXC.search(t_s): reg_m[r.c6].append(ts_s)
    for zf in glob.glob(f"{SIM}/data/kpl/zdjk/*.json"):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6, d_z = str(it[0]).zfill(6), str(it[2])[:10]
            if c6 in cset and d_z <= cutoff_dt: reg_m[c6].append(f"{d_z} 08:00:00")
    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}
    for m in (tox_m, reg_m):
        for k in list(m.keys()): m[k] = sorted(set(m[k]))
    df_st = np.array([_is_st_at(st_tl, r.c6, f"{r.dt} 15:00:00") for r in df.itertuples(index=False)], dtype=int)
    mkt20_zt = df[df["is_zt"] & (df_st == 0)].groupby("dt").size().to_dict()
    cnt_by_f1 = defaultdict(int)
    for r in cand.itertuples(index=False):
        c6, dt, f1dt = r.c6, r.dt, r.f1_dt
        if not f1dt or f1dt > cutoff_dt: continue
        t1c = f"{f1dt} 09:00:00"
        if (_is_st_at(st_tl, c6, f"{dt} 15:00:00") == 0 and _is_st_at(st_tl, c6, t1c) == 0
                and _cnt_ts(tox_m.get(c6), f"{_shift_cal(dt, -90)} 00:00:00", t1c) == 0
                and _cnt_ts(reg_m.get(c6), f"{_shift_cal(dt, -10)} 00:00:00", t1c) == 0
                and mkt20_zt.get(dt, 0) < 16):
            cnt_by_f1[f1dt] += 1
    return dict(cnt_by_f1)
