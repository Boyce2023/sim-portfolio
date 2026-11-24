#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 3: 热点题材基本面大票中军策略原型实盘化压力测试、空仓补位验证与典型案例深挖
- Strictly local read-only. Zero yfinance (D12). Zero network calls.
- IS: 2021-11-16 ~ 2023-12-31 | OOS: 2024-01-01 ~ 2026-11-23 | 3Y: 2023-11-23+ | 2026: 2026-01-01+
"""
import os, sys, json, re, sqlite3, time, bisect, datetime
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA = f"{SIM}/data"
OUT_DIR = f"{SIM}/backtests_astock/hot_theme_largecap_audit_20261123/part3_stress"
os.makedirs(OUT_DIR, exist_ok=True)

FEE_BASE = 0.0020
FEE_SLIP05 = 0.0050
FEE_SLIP07 = 0.0070

NON_THEMATIC_PLATES = {
    "其他", "ST板块", "新股与次新股", "业绩增长", "一季报增长", "中报增长",
    "三季报增长", "年报增长", "并购重组", "股权转让", "回购", "增持",
    "国企改革", "央企改革", "地方国资改革", "高送转", "摘帽", "超跌", "定增", "参股新股"
}
NON_THEME_ELO = {"其他", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"}

MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
TECH_PAT_TIMELESS = re.compile(
    r"(芯片|半导体|光刻|集成电路|软件|信创|云计算|大数据|人工智能|AI|机器人|智能制造|自动化|"
    r"通信|5G|光通信|卫星|航天|军工|锂电|光伏|储能|风电|氢能|新材料|消费电子|智能驾驶|无人驾驶)"
)
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")

# Theme family classifiers for KPL plates
HARD_TECH_PLATE_RE = re.compile(
    r"(?:机器人|人形|减速器|工业母机|芯片|半导体|存储|光刻|算力|人工智能|AI|大模型|DeepSeek|"
    r"数字经济|软件|信创|云计算|通信|光通信|CPO|PCB|消费电子|华为|鸿蒙|自动驾驶|无人驾驶|智驾|"
    r"卫星|商业航天|低空|量子|液冷|传感器|机器视觉|电源)"
)
CORE_TECH_C_RE = re.compile(
    r"(?:机器人|人形|减速器|芯片|半导体|存储|光刻|人工智能|AI|大模型|DeepSeek|算力|CPO|光通信|液冷|数字经济)"
)
CONS_C_RE = re.compile(
    r"(?:家电|智能家居|食品|饮料|酿酒|白酒|乳业|预制菜|零售|百货|商超|商业|免税|服装|家纺|纺织|旅游|酒店|餐饮|美容|宠物)"
)
APPLIANCE_RE = re.compile(r"(?:家电|智能家居)")

FAMILY_RULES = [
    ("ROBOT", re.compile(r"(?:机器人|人形|减速器|工业母机|机器视觉)")),
    ("CHIP", re.compile(r"(?:芯片|半导体|存储|光刻|集成电路|第三代半导体)")),
    ("AI_COMP", re.compile(r"(?:人工智能|AI|大模型|DeepSeek|算力|CPO|光通信|液冷|数字经济|软件|信创|云计算)")),
    ("TECH_OTHER", re.compile(r"(?:消费电子|华为|鸿蒙|通信|5G|PCB|卫星|商业航天|低空|自动驾驶|无人驾驶|智驾|量子|传感器|电源)")),
    ("APPLIANCE", re.compile(r"(?:家电|智能家居)")),
    ("FOOD_BEV", re.compile(r"(?:食品|饮料|酿酒|白酒|乳业|预制菜)")),
    ("RETAIL", re.compile(r"(?:零售|百货|商超|免税|跨境电商)")),
    ("CONS_OTHER", re.compile(r"(?:服装|家纺|纺织|旅游|酒店|餐饮|美容|宠物|家居|家具)")),
]


def plate_families(pname: str) -> set[str]:
    if "消费电子" in pname or "商业航天" in pname:
        # Never misclassify 消费电子 or 商业航天 into consumer retail/food
        fams = {k for k, rx in FAMILY_RULES if k in ("ROBOT", "CHIP", "AI_COMP", "TECH_OTHER") and rx.search(pname)}
        return fams or {"TECH_OTHER"}
    return {k for k, rx in FAMILY_RULES if rx.search(pname)}


def split_terms(s: str) -> set:
    out = set()
    for part in re.split(r"[+、,，/；;]", s or ""):
        part = part.strip()
        if part:
            out.add(part)
            for x in re.split(r"[()（）]", part):
                x = x.strip()
                if x:
                    out.add(x)
    return {t for t in out if 2 <= len(t) <= 20 and t not in NON_THEME_ELO}


def load_daily_universe():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn"]
    f_cut = [("date", ">=", pd.Timestamp("2021-06-01"))]
    da = pd.read_parquet(f"{DATA}/cn_hk_price_db/a_daily.parquet", columns=cols, filters=f_cut)
    dd = pd.read_parquet(f"{DATA}/cn_hk_price_db/a_delisted_daily.parquet", columns=cols, filters=f_cut)
    df = pd.concat([da, dd], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[~df["ticker"].str.endswith(".BJ")].copy()
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt"], inplace=True)
    df.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["adj_open"] = df["open"] * df["adjf"]
    df["adj_high"] = df["high"] * df["adjf"]
    df["adj_low"] = df["low"] * df["adjf"]

    g = df.groupby("c6", sort=False)
    df["trade_num"] = g.cumcount()
    df["pre_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pre_adj_c"] = g["adj_close"].shift(1)
    df["pct"] = df["adj_close"] / df["pre_adj_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c_adj"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["pre_mcap"] = g["mcap"].shift(1)
    df["amt_yi"] = df["amount"] / 1e8

    is_20 = df["c6"].str.startswith(("300", "301", "688", "689"))
    df["lim_pct"] = np.where(is_20, 0.20, 0.10)
    df["zt_px"] = np.floor(df["pre_c_adj"] * (1.0 + df["lim_pct"]) * 100.0 + 0.5) / 100.0
    df["dt_px"] = np.floor(df["pre_c_adj"] * (1.0 - df["lim_pct"]) * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= df["lim_pct"] - 0.008) & (df["pre_c_adj"] > 0)
    df["is_dt_exact"] = (df["close"] <= df["dt_px"] + 0.005) & (df["pre_c_adj"] > 0)
    df["is_yizi_zt_open"] = (df["open"] >= df["zt_px"] - 0.005) & (df["pre_c_adj"] > 0)
    df["is_yizi_dt"] = df["is_dt_exact"] & (df["open"] <= df["dt_px"] + 0.005) & (df["high"] <= df["dt_px"] + 0.005)

    # Strictly pre-signal technicals (up to T-1) & MA10
    df["ret_pre10"] = g["adj_close"].shift(1) / (g["adj_close"].shift(11) + 1e-8) - 1.0
    min60 = g["adj_low"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).min())
    max60 = g["adj_high"].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df["pos60"] = (g["adj_close"].shift(1) - min60) / (max60 - min60 + 1e-8)
    df["ma10_adj"] = g["adj_close"].transform(lambda s: s.rolling(10, min_periods=10).mean())

    valid_dts = sorted(df["dt"].unique())
    print(f"[1/6] Loaded {len(df):,} rows ({df['c6'].nunique()} stocks, {len(valid_dts)} days) in {time.time()-t0:.1f}s")
    return df, valid_dts


def build_benchmarks(df: pd.DataFrame):
    idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    sh300 = idx_cache["sh000300"]

    b_df = pd.read_parquet(f"{SIM}/backtests_astock2/theory_backtest_15y_20261119/data_cache/broad_indices_15y.parquet")
    sh905 = {r.date.strftime("%Y-%m-%d"): float(r.close) for r in b_df[b_df["symbol"] == "sh000905"].itertuples(index=False)}

    # Build strict PIT CSI 1000 proxy (rank 801-1800 by prior-day mcap, cap-weighted)
    sub = df[df["dt"] >= "2021-11-01"][["dt", "c6", "pct", "pre_mcap"]].dropna()
    csi1000_lvl = 1000.0
    csi1000_map = {}
    for dt, grp in sub.groupby("dt", sort=True):
        if len(grp) >= 1800:
            s = grp.sort_values("pre_mcap", ascending=False).iloc[800:1800]
            w = np.clip(s["pre_mcap"].to_numpy(float), 1.0, None)
            r = np.clip(s["pct"].to_numpy(float), -0.25, 0.25)
            ret = float(np.average(r, weights=w))
        else:
            ret = 0.0
        csi1000_lvl *= (1.0 + ret)
        csi1000_map[dt] = csi1000_lvl

    # Validate proxy correlation against official 2026-06..08 sh000852 cache
    idx_off = json.load(open(f"{SIM}/backtest/2026-08-24/index_data.json"))["csi1000"]
    m_off = {x["date"]: x["close"] for x in idx_off}
    odts = sorted(m_off.keys())
    pr, orr = [], []
    for i in range(1, len(odts)):
        d0, d1 = odts[i - 1], odts[i]
        if d0 in csi1000_map and d1 in csi1000_map:
            pr.append(csi1000_map[d1] / csi1000_map[d0] - 1.0)
            orr.append(m_off[d1] / m_off[d0] - 1.0)
    corr = float(np.corrcoef(pr, orr)[0, 1]) if len(pr) > 5 else 0.0
    print(f"[*] CSI1000 proxy validated vs official sh000852 (n={len(pr)}d): r={corr:.4f}")
    return sh300, sh905, csi1000_map, corr


def load_csrc_and_notices_pit():
    t0 = time.time()
    csrc = pd.read_csv(f"{DATA}/csrc_industry_pit_clean.csv")
    csrc["c6"] = csrc["code"].astype(str).str[-6:].str.zfill(6)
    csrc_ind = dict(zip(csrc["c6"], csrc["industry"].fillna("")))
    csrc_name = dict(zip(csrc["c6"], csrc["code_name"].fillna("")))

    # Toxic notices: union of complete 5Y parquet + cninfo_notices_5y_pit.db
    re_tox = re.compile(r"立案|调查|违法|违规|处罚|退市|风险警示|\*ST|被实施|减持|问询函|监管函|警示函|预亏|亏损|违约|逾期|冻结|留置")
    re_earn = re.compile(r"预增|扭亏|大幅增长|略增|业绩快报")
    re_earn_neg = re.compile(r"预亏|亏损|下降|下修|首亏|增亏|减亏")
    re_ctr_buy = re.compile(r"中标|重大合同|日常经营|签订.*合同|订单|回购|增持")
    re_ctr_neg = re.compile(r"减持|终止|取消")
    re_app_title = re.compile(r"家用电器|家电|空调|冰箱|洗衣机|厨电|白电|小家电|电器")
    re_chip_title = re.compile(r"半导体|芯片|集成电路|晶圆|光刻|存储")

    tox_dates = defaultdict(list)
    df_tox = pd.read_parquet(f"{DATA}/pit_reg_tox_notices_5y_complete.parquet")
    for r in df_tox.itertuples(index=False):
        c6 = str(r.sec_code)[:6].zfill(6)
        pdt = str(r.pub_datetime_cst or "")[:19]
        if pdt >= "2021-08-01" and re_tox.search(str(r.title or "")):
            tox_dates[c6].append(pdt)

    earn_dates = defaultdict(list)
    ctr_buy_dates = defaultdict(list)
    app_title_first = {}
    chip_title_first = {}
    con = sqlite3.connect(f"file:{DATA}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for sc, pdt, tp, tit in con.execute(
        "SELECT sec_code, pub_datetime_cst, ann_type, title FROM notices WHERE pub_datetime_cst >= '2021-01-01'"
    ):
        c6 = str(sc)[:6].zfill(6)
        pdt_s = str(pdt or "")[:19]
        txt = f"{tp or ''} {tit or ''}"
        if re_tox.search(txt):
            tox_dates[c6].append(pdt_s)
        if re_earn.search(txt) and not re_earn_neg.search(txt):
            earn_dates[c6].append(pdt_s)
        if re_ctr_buy.search(txt) and not re_ctr_neg.search(txt):
            ctr_buy_dates[c6].append(pdt_s)
        if re_app_title.search(str(tit or "")):
            dt10 = pdt_s[:10]
            if c6 not in app_title_first or dt10 < app_title_first[c6]:
                app_title_first[c6] = dt10
        if re_chip_title.search(str(tit or "")):
            dt10 = pdt_s[:10]
            if c6 not in chip_title_first or dt10 < chip_title_first[c6]:
                chip_title_first[c6] = dt10
    con.close()

    # IR QA (complete 5Y uniform)
    ir_dates = defaultdict(list)
    con_ir = sqlite3.connect(f"file:{DATA}/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    for sc, pdt, tit in con_ir.execute(
        "SELECT sec_code, pub_datetime_cst, title FROM ir_qa WHERE pub_datetime_cst >= '2021-01-01'"
    ):
        c6 = str(sc)[:6].zfill(6)
        ir_dates[c6].append(str(pdt or "")[:19])
        if re_app_title.search(str(tit or "")):
            dt10 = str(pdt)[:10]
            if c6 not in app_title_first or dt10 < app_title_first[c6]:
                app_title_first[c6] = dt10
        if re_chip_title.search(str(tit or "")):
            dt10 = str(pdt)[:10]
            if c6 not in chip_title_first or dt10 < chip_title_first[c6]:
                chip_title_first[c6] = dt10
    con_ir.close()

    for m in (tox_dates, earn_dates, ctr_buy_dates, ir_dates):
        for k in m:
            m[k].sort()

    print(f"[2/6] Loaded PIT notices/tox/IR in {time.time()-t0:.1f}s")
    return csrc_ind, csrc_name, tox_dates, earn_dates, ctr_buy_dates, ir_dates, app_title_first, chip_title_first


def has_event_in_90d(ev_map, c6: str, sig_dt: str) -> bool:
    arr = ev_map.get(c6)
    if not arr:
        return False
    cut90 = (datetime.date.fromisoformat(sig_dt) - datetime.timedelta(days=90)).isoformat()
    end_cut = f"{sig_dt} 15:00:00"
    lo = bisect.bisect_left(arr, cut90)
    return lo < len(arr) and arr[lo] <= end_cut


def build_kpl_pit_engine(df: pd.DataFrame, valid_dts: list[str]):
    """Run 8Y preheated Dual-Layer Elo strictly on real A-share trading days."""
    t0 = time.time()
    valid_set = set(valid_dts)
    kpl_all = []
    with open(f"{DATA}/kpl_plates_2018_2026_merged.jsonl", "r", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            d = json.loads(ln)
            dt = d.get("date", "")
            # Filter post-2021-06 dates strictly to real trading days in a_daily
            if dt >= "2021-06-01" and dt not in valid_set:
                continue
            kpl_all.append(d)
    kpl_all.sort(key=lambda x: x["date"])

    # Build fast lookup for 2021-06+ days (earlier days just warm Elo with empty/minimal impact or basic stats)
    sub = df[df["dt"].isin({d["date"] for d in kpl_all if d["date"] >= "2021-06-01"})][
        ["dt", "c6", "is_zt", "is_yizi_zt_open", "pct", "mcap"]
    ]
    day_stock_map = {
        (r.dt, r.c6): (bool(r.is_zt), bool(r.is_zt), bool(r.is_yizi_zt_open), float(r.pct) if pd.notna(r.pct) else 0.0, float(r.mcap) if pd.notna(r.mcap) else 0.0)
        for r in sub.itertuples(index=False)
    }

    elo = defaultdict(lambda: 100.0)
    plate_recent_zts = defaultdict(list)
    plate_last_idx = {}
    prev_plate_stocks = {}
    term_seen_days = Counter()
    term_first_dt, term_last_idx = {}, {}

    # Strict PIT per-stock KPL theme history & ST history
    stock_kpl_fams_pit = defaultdict(set)  # cumulative up to current day
    stock_kpl_plates_pit = defaultdict(set)
    stock_st_last_dt = {}

    day_hot_plates = {}  # dt -> list of (pname, rk_c, sz, sc_clean, fams_set, today_c6_set)
    day_stock_fams_snapshot = {}  # only snapshot for days >= 2021-11-01? No, lookup on fly via first-seen dates!
    fam_first_seen = defaultdict(dict)  # c6 -> {fam: first_dt}
    plate_first_seen = defaultdict(dict)  # c6 -> {pname: first_dt}

    for day_idx, d_entry in enumerate(kpl_all):
        dt = d_entry["date"]
        cutoff_15d = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = d_entry.get("plates", [])

        # Update Elo from previous day
        for pname, c6_list in prev_plate_stocks.items():
            touches, seals, rets = 0, 0, []
            for c6 in c6_list:
                st = day_stock_map.get((dt, c6))
                if st is not None:
                    rets.append(st[3]); touches += int(st[1]); seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and np.mean(rets) > 0.025:
                elo[pname] += 6.0

        for p_k in list(elo.keys()):
            if day_idx - plate_last_idx.get(p_k, day_idx) > 3:
                elo[p_k] = 100.0 + (elo[p_k] - 100.0) * 0.85

        new_prev_p = {}
        plate_meta = {}
        day_terms_to_commit = {}

        for p in plates:
            pname = str(p.get("plate", "")).strip()
            stocks = p.get("stocks", [])
            if pname == "ST板块":
                for s in stocks:
                    stock_st_last_dt[str(s[0]).strip()[:6].zfill(6)] = dt
                continue
            if pname in NON_THEME_ELO or not stocks:
                continue
            sz = len(stocks)
            c6_list = []
            n_ma = n_tech_t = n_earn = n_big = n_yizi = n_new = 0
            spark_b = 0.0

            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                txt = f"{pname} {r_sh} {r_lg}"
                if MA_PAT.search(txt): n_ma += 1
                if TECH_PAT_TIMELESS.search(txt): n_tech_t += 1
                if EARN_PAT.search(txt): n_earn += 1

                for t in (split_terms(pname) | split_terms(r_sh)):
                    prev_cnt = term_seen_days[t]
                    prev_idx = term_last_idx.get(t, -9999)
                    f_dt = term_first_dt.get(t, dt)
                    if prev_cnt == 0 or f_dt >= cutoff_15d:
                        n_new += 1
                    elif 5 <= (day_idx - prev_idx) <= 45 and prev_cnt <= 5:
                        spark_b = max(spark_b, 6.0)
                    day_terms_to_commit[t] = dt

                st = day_stock_map.get((dt, c6))
                if st is not None:
                    if st[4] >= 150.0: n_big += 1
                    if st[2]: n_yizi += 1

                # Record cumulative PIT theme membership
                if pname not in NON_THEMATIC_PLATES:
                    if pname not in plate_first_seen[c6]:
                        plate_first_seen[c6][pname] = dt
                    for fm in plate_families(pname):
                        if fm not in fam_first_seen[c6]:
                            fam_first_seen[c6][fm] = dt

            new_prev_p[pname] = c6_list
            plate_last_idx[pname] = day_idx
            r5_zts = sum(cnt for idx_p, cnt in plate_recent_zts[pname] if day_idx - idx_p <= 5)
            plate_recent_zts[pname].append((day_idx, sz))

            sc_base = (
                elo[pname] + min(sz, 15) * 1.8 + min(r5_zts, 30) * 0.35
                + (8.0 if n_ma > 0 else 0.0) + (5.0 if n_new > 0 else 0.0)
                + spark_b + min(n_yizi * 4.0, 8.0) - (n_earn / sz) * 12.0 - (n_big / sz) * 10.0
            )
            sc_clean = sc_base + (6.0 if (TECH_PAT_TIMELESS.search(pname) or n_tech_t >= max(1, sz // 2)) else 0.0)
            plate_meta[pname] = (sc_clean, sz, set(c6_list))

        ranked = sorted(plate_meta.keys(), key=lambda k: plate_meta[k][0], reverse=True)
        if dt >= "2021-11-01":
            day_hot_plates[dt] = [
                (pn, rk, plate_meta[pn][1], round(plate_meta[pn][0], 2), plate_families(pn), plate_meta[pn][2])
                for rk, pn in enumerate(ranked, 1)
            ]

        for t, dt_v in day_terms_to_commit.items():
            term_seen_days[t] += 1
            if t not in term_first_dt:
                term_first_dt[t] = dt_v
            term_last_idx[t] = day_idx
        prev_plate_stocks = new_prev_p

    print(f"[3/6] Built 8Y KPL Elo engine ({len(day_hot_plates)} days >=2021-11) in {time.time()-t0:.1f}s")
    return day_hot_plates, fam_first_seen, plate_first_seen


def is_member_of_plate_pit(c6: str, sig_dt: str, pname: str, fams: set[str], today_c6s: set[str],
                           fam_first_seen, plate_first_seen, csrc_ind, csrc_name, app_title_first, chip_title_first) -> bool:
    if c6 in today_c6s:
        return True
    p_seen = plate_first_seen.get(c6, {})
    if pname in p_seen and p_seen[pname] <= sig_dt:
        return True
    f_seen = fam_first_seen.get(c6, {})
    for fm in fams:
        if fm in f_seen and f_seen[fm] <= sig_dt:
            return True
    # Narrow PIT CSRC bridge for mega-caps that rarely hit +10%
    ind = csrc_ind.get(c6, "")
    nm = csrc_name.get(c6, "")
    if "FOOD_BEV" in fams and ind.startswith(("C13", "C14", "C15")):
        return True
    if "RETAIL" in fams and ind.startswith("F52"):
        return True
    if "CONS_OTHER" in fams and ind.startswith(("C17", "C18", "C21")):
        return True
    if "APPLIANCE" in fams and ind.startswith("C38"):
        if (c6 in app_title_first and app_title_first[c6] <= sig_dt) or re.search(r"家电|电器|智家|美菱|小熊|厨电|制冷", nm):
            return True
    if "CHIP" in fams and ind.startswith("C39"):
        if (c6 in chip_title_first and chip_title_first[c6] <= sig_dt) or re.search(r"芯|微电子|半导体|晶圆|硅|光刻|存储|集成电路", nm):
            return True
    if "AI_COMP" in fams and ind.startswith(("I65", "C39")):
        if re.search(r"软件|信息|数据|智能|算力|光模块|服务器|云计算|人工智能|科技", nm):
            return True
    return False


def simulate_exit_and_ret(c_arr, buy_idx: int, exit_mode: str, fee: float):
    """
    c_arr dict of numpy arrays for stock c6: dts, open, close, high, dt_px, zt_px, adjf, is_dt_exact, is_yizi_dt, ma10_adj, adj_close
    Returns (exit_dt, exit_px, exit_hhmm, net_ret) or None
    """
    n = len(c_arr["dts"])
    if buy_idx >= n - 1:
        return None
    buy_px = float(c_arr["open"][buy_idx])
    buy_adjf = float(c_arr["adjf"][buy_idx])
    if buy_px <= 0 or bool(c_arr["is_yizi_zt_open"][buy_idx]) or bool(c_arr["is_yizi_dt"][buy_idx]):
        return None
    if float(c_arr["volume"][buy_idx]) <= 0:
        return None

    if exit_mode.startswith("hold_"):
        h = int(exit_mode.split("_")[1])
        target = buy_idx + h
        if target >= n:
            return None
        if not bool(c_arr["is_dt_exact"][target]):
            ex_idx = target
            ex_px = float(c_arr["close"][ex_idx])
            ex_hhmm = 1500
        else:
            # Defer limit-down to next non-yizi_dt 09:25 open
            k = target + 1
            while k < n - 1 and bool(c_arr["is_yizi_dt"][k]):
                k += 1
            if k >= n:
                return None
            ex_idx = k
            ex_px = float(c_arr["open"][ex_idx])
            ex_hhmm = 925
    elif exit_mode == "ma10":
        # T+1 compliant: check EOD adj_close < ma10_adj starting buy_idx + 1, cap 30d
        ex_idx = min(n - 1, buy_idx + 30)
        for k in range(buy_idx + 1, min(n, buy_idx + 31)):
            ma10 = c_arr["ma10_adj"][k]
            ac = c_arr["adj_close"][k]
            if not np.isnan(ma10) and ac < ma10:
                ex_idx = k
                break
        if not bool(c_arr["is_dt_exact"][ex_idx]):
            ex_px = float(c_arr["close"][ex_idx])
            ex_hhmm = 1500
        else:
            k = ex_idx + 1
            while k < n - 1 and bool(c_arr["is_yizi_dt"][k]):
                k += 1
            if k >= n:
                return None
            ex_idx = k
            ex_px = float(c_arr["open"][ex_idx])
            ex_hhmm = 925
    else:
        raise ValueError(exit_mode)

    ex_adjf = float(c_arr["adjf"][ex_idx])
    net_ret = (ex_px * ex_adjf) / (buy_px * buy_adjf) * (1.0 - fee) - 1.0
    return {
        "buy_date": c_arr["dts"][buy_idx],
        "buy_px": round(buy_px, 2),
        "exit_date": c_arr["dts"][ex_idx],
        "exit_px": round(ex_px, 2),
        "exit_hhmm": ex_hhmm,
        "net_ret": float(net_ret),
        "buy_idx_local": buy_idx,
        "exit_idx_local": ex_idx,
    }


def bench_period_ret(bmap: dict, s_dt: str, e_dt: str) -> float:
    keys = sorted(bmap.keys())
    sub = [k for k in keys if s_dt <= k <= e_dt]
    if not sub:
        return 0.0
    prevs = [k for k in keys if k < sub[0]]
    base_k = max(prevs) if prevs else sub[0]
    return float(bmap[sub[-1]] / bmap[base_k] - 1.0)


def eval_trade_ledger(trades_df: pd.DataFrame, sh300: dict, csi1000: dict, all_dts: list[str],
                      stock_arrays: dict, fee: float = FEE_BASE, run_perm: bool = True,
                      perm_pool_by_dt: dict = None, hold_for_perm: str = "hold_5") -> dict:
    """Compute D15 full evaluation: 1-slot + daily EW, 5 windows, ex-924, ex-Top5, perm p-value."""
    if trades_df is None or len(trades_df) == 0:
        return {"n_raw": 0, "1slot": {}, "ew_nav_5y": 1.0, "perm_p": None}

    # Build 1-slot strict chronological selection (sorted by buy_date asc, rk_c asc, amt_yi desc)
    s_ord = trades_df.sort_values(["buy_date", "rk_c", "amt_yi", "pct"], ascending=[True, True, False, False])
    ss_rows = []
    free_dt = ""
    for r in s_ord.itertuples(index=False):
        if free_dt == "" or r.buy_date > free_dt:
            ss_rows.append(r._asdict())
            free_dt = r.exit_date
    ss_df = pd.DataFrame(ss_rows)

    # Daily MTM equity curve across calendar trading days for 1-slot Sharpe/MDD/CAGR
    dt_to_i = {d: i for i, d in enumerate(all_dts)}
    dts_5y = [d for d in all_dts if "2021-11-16" <= d <= "2026-11-23"]
    d5_idx = {d: i for i, d in enumerate(dts_5y)}

    def calc_window_stats(sub_ss: pd.DataFrame, sub_raw: pd.DataFrame, s_dt: str, e_dt: str) -> dict:
        w_ss = sub_ss[(sub_ss["buy_date"] >= s_dt) & (sub_ss["buy_date"] <= e_dt)].copy()
        w_raw = sub_raw[(sub_raw["buy_date"] >= s_dt) & (sub_raw["buy_date"] <= e_dt)].copy()
        if len(w_ss) == 0:
            return {"n": 0, "n_raw": len(w_raw), "wr": 0.0, "payoff": 0.0, "nav": 1.0, "mdd": 0.0,
                    "ex300_pp": -bench_period_ret(sh300, s_dt, e_dt) * 100.0,
                    "ex1000_pp": -bench_period_ret(csi1000, s_dt, e_dt) * 100.0}
        rets = w_ss["net_ret"].to_numpy(float)
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        wr = float(len(wins) / len(rets))
        po = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (9.99 if len(wins) > 0 else 0.0)
        nav = float(np.prod(1.0 + rets))

        # Daily MTM across all calendar days in window
        w_dts = [d for d in all_dts if s_dt <= d <= e_dt]
        daily_r = np.zeros(len(w_dts), dtype=float)
        w_dt_i = {d: i for i, d in enumerate(w_dts)}
        for r in w_ss.itertuples(index=False):
            ca = stock_arrays[r.c6]
            b_i = ca["dt_to_pos"][r.buy_date]
            e_i = ca["dt_to_pos"][r.exit_date]
            n_d = e_i - b_i + 1
            # Mark-to-market daily log/simple decomposition matching exact trade net_ret
            cum_f = 1.0
            for k in range(b_i, e_i + 1):
                dk = ca["dts"][k]
                if dk not in w_dt_i:
                    continue
                if k == b_i:
                    if b_i == e_i:
                        dr = r.net_ret
                    else:
                        dr = (float(ca["close"][k]) / float(r.buy_px)) * (1.0 - fee / 2.0) - 1.0
                elif k == e_i:
                    # force exact product = 1 + net_ret
                    dr = (1.0 + r.net_ret) / cum_f - 1.0
                else:
                    dr = float(ca["adj_close"][k]) / float(ca["adj_close"][k - 1]) - 1.0
                cum_f *= (1.0 + dr)
                daily_r[w_dt_i[dk]] = dr

        eq = np.cumprod(1.0 + daily_r)
        pk = np.maximum.accumulate(np.insert(eq, 0, 1.0))[1:]
        mdd = float(np.max((pk - eq) / pk)) if len(eq) else 0.0
        yrs = max(0.05, len(w_dts) / 243.0)
        cagr = float(nav ** (1.0 / yrs) - 1.0)
        sharpe = float(np.mean(daily_r) / (np.std(daily_r) + 1e-12) * np.sqrt(243.0)) if np.std(daily_r) > 0 else 0.0
        calmar = float(cagr / mdd) if mdd > 1e-6 else 0.0

        b300 = bench_period_ret(sh300, s_dt, e_dt)
        b1000 = bench_period_ret(csi1000, s_dt, e_dt)

        # Equal weight per buy_date
        ew_d = w_raw.groupby("buy_date")["net_ret"].mean().to_numpy(float)
        ew_nav = float(np.prod(1.0 + ew_d)) if len(ew_d) else 1.0

        ex_top1_nav = float(np.prod(1.0 + np.sort(rets)[:-1])) if len(rets) > 1 else 1.0
        ex_top3_nav = float(np.prod(1.0 + np.sort(rets)[:-3])) if len(rets) > 3 else 1.0
        ex_top5_nav = float(np.prod(1.0 + np.sort(rets)[:-5])) if len(rets) > 5 else 1.0

        return {
            "n": int(len(w_ss)),
            "n_raw": int(len(w_raw)),
            "wr": round(wr * 100.0, 2),
            "payoff": round(po, 2),
            "avg_ret_pct": round(float(rets.mean()) * 100.0, 2),
            "nav": round(nav, 4),
            "ret_pct": round((nav - 1.0) * 100.0, 2),
            "cagr_pct": round(cagr * 100.0, 2),
            "mdd_pct": round(mdd * 100.0, 2),
            "sharpe": round(sharpe, 2),
            "calmar": round(calmar, 2),
            "csi300_pct": round(b300 * 100.0, 2),
            "ex300_pp": round(((nav - 1.0) - b300) * 100.0, 2),
            "csi1000_pct": round(b1000 * 100.0, 2),
            "ex1000_pp": round(((nav - 1.0) - b1000) * 100.0, 2),
            "ew_nav": round(ew_nav, 4),
            "ew_ex300_pp": round(((ew_nav - 1.0) - b300) * 100.0, 2),
            "ex_top1_nav": round(ex_top1_nav, 4),
            "ex_top3_nav": round(ex_top3_nav, 4),
            "ex_top5_nav": round(ex_top5_nav, 4),
        }

    # Window suite
    wins = {
        "5Y": calc_window_stats(ss_df, trades_df, "2021-11-16", "2026-11-23"),
        "IS": calc_window_stats(ss_df, trades_df, "2021-11-16", "2023-12-31"),
        "OOS": calc_window_stats(ss_df, trades_df, "2024-01-01", "2026-11-23"),
        "3Y": calc_window_stats(ss_df, trades_df, "2023-11-23", "2026-11-23"),
        "2026": calc_window_stats(ss_df, trades_df, "2026-01-01", "2026-11-23"),
    }

    # Ex-924 (exclude any trade overlapping 2024-09-24 ~ 2024-10-10)
    mask_924 = (trades_df["buy_date"] <= "2024-10-10") & (trades_df["exit_date"] >= "2024-09-24")
    raw_ex924 = trades_df[~mask_924]
    ss_ex924 = ss_df[~((ss_df["buy_date"] <= "2024-10-10") & (ss_df["exit_date"] >= "2024-09-24"))]
    wins["5Y_ex924"] = calc_window_stats(ss_ex924, raw_ex924, "2021-11-16", "2026-11-23")
    wins["OOS_ex924"] = calc_window_stats(ss_ex924, raw_ex924, "2024-01-01", "2026-11-23")

    # Permutation test (1000 Monte Carlo draws on same buy_dates from eligible large-cap pool)
    perm_p = None
    if run_perm and perm_pool_by_dt is not None and len(ss_df) >= 5:
        rng = np.random.default_rng(42)
        obs_nav = float(np.prod(1.0 + ss_df["net_ret"].to_numpy(float)))
        b_dates = ss_df["buy_date"].tolist()
        beats = 0
        n_sim = 1000
        for _ in range(n_sim):
            sim_r = []
            for bd in b_dates:
                arr = perm_pool_by_dt.get(bd)
                if arr is not None and len(arr) > 0:
                    sim_r.append(float(arr[rng.integers(0, len(arr))]))
            if sim_r and float(np.prod(1.0 + np.array(sim_r))) >= obs_nav:
                beats += 1
        perm_p = round(beats / n_sim, 4)

    return {"1slot": wins, "perm_p": perm_p, "ss_df": ss_df, "raw_df": trades_df}


def compute_cscv_pbo(variant_daily_rets: list[np.ndarray], n_blocks: int = 8) -> float:
    """Bailey CSCV Probability of Backtest Overfitting across S parameter variants."""
    if len(variant_daily_rets) < 2:
        return 0.0
    mat = np.column_stack(variant_daily_rets)  # T x S
    T, S = mat.shape
    blk_sz = T // n_blocks
    if blk_sz < 10:
        return 0.0
    mat = mat[:blk_sz * n_blocks]
    blocks = [mat[i * blk_sz:(i + 1) * blk_sz] for i in range(n_blocks)]

    from itertools import combinations
    half = n_blocks // 2
    all_idx = set(range(n_blocks))
    logits = []
    for is_idx in combinations(range(n_blocks), half):
        oos_idx = sorted(all_idx - set(is_idx))
        is_m = np.vstack([blocks[i] for i in is_idx])
        oos_m = np.vstack([blocks[i] for i in oos_idx])
        is_sh = np.mean(is_m, axis=0) / (np.std(is_m, axis=0) + 1e-12)
        oos_sh = np.mean(oos_m, axis=0) / (np.std(oos_m, axis=0) + 1e-12)
        best_s = int(np.argmax(is_sh))
        # Relative rank of best_s in OOS
        rk = float(np.sum(oos_sh <= oos_sh[best_s])) / (S + 1.0)
        rk = min(max(rk, 1e-4), 1.0 - 1e-4)
        logits.append(np.log(rk / (1.0 - rk)))
    return round(float(np.mean(np.array(logits) < 0.0)), 4)


def run_v191_overlay(v19_df: pd.DataFrame, backup_raw_df: pd.DataFrame, stock_arrays: dict,
                     all_dts: list[str], sh300: dict, csi1000: dict, kpl_hot_plates: dict,
                     mode: str, max_hold_d: int = 5, only_post_climax35: bool = False) -> dict:
    """
    Overlay Prototype A/B onto V19.1 single-slot clean ledger.
    modes:
      - 'V19_BASE': baseline V19.1 alone
      - 'D1_ideal': exit backup at D_v19 09:25 open (defer if yizi_dt), V19.1 enters
      - 'D1_strict': exit backup at D_v19 09:25 open; if v19.buy_hhmm == 925 skip that v19 trade (cash lock)
      - 'D2_lock': hold backup full max_hold_d; skip conflicting V19.1 trades
    """
    dts_5y = [d for d in all_dts if "2021-11-15" <= d <= "2026-11-23"]
    d_idx = {d: i for i, d in enumerate(dts_5y)}

    # Index V19.1 trades by buy_date
    v19 = v19_df.copy()
    v19["c6"] = v19["code"].astype(str).str.zfill(6)
    v19_by_bdt = {r.buy_date: r for r in v19.itertuples(index=False)}

    # Index backup candidates by buy_date (best candidate on each day)
    bk_best = {}
    if backup_raw_df is not None and len(backup_raw_df) > 0:
        b_ord = backup_raw_df.sort_values(["buy_date", "rk_c", "amt_yi", "pct"], ascending=[True, True, False, False])
        for bd, grp in b_ord.groupby("buy_date", sort=False):
            bk_best[bd] = grp.iloc[0]

    # Pre-check post-super-climax dates (prev_dt had any plate sz > 35)
    super_climax_buy_dts = set()
    for i in range(1, len(all_dts)):
        sig_dt, b_dt = all_dts[i - 1], all_dts[i]
        pls = kpl_hot_plates.get(sig_dt, [])
        if any(sz > 35 for _, _, sz, _, _, _ in pls):
            super_climax_buy_dts.add(b_dt)

    # Chronological single-slot event simulation day by day
    daily_r = np.zeros(len(dts_5y), dtype=float)
    cap_daily_r = np.zeros(len(dts_5y), dtype=float)
    cap_nav = 1.0
    pos_state = None
    bk_trades, v19_taken = [], []

    def step_cap(idx_k: int, dr_val: float, w_scale: float):
        nonlocal cap_nav
        cr = dr_val * w_scale
        cap_daily_r[idx_k] = (1.0 + cap_daily_r[idx_k]) * (1.0 + cr) - 1.0
        cap_nav *= (1.0 + cr)

    i = 0
    while i < len(dts_5y):
        dt = dts_5y[i]

        # 1. If holding a position, check exit on dt
        if pos_state is not None:
            if pos_state["type"] == "V19":
                vr = pos_state["v19_row"]
                w_v19 = pos_state["cap_w"]
                if dt < vr.exit_date:
                    ca = stock_arrays.get(vr.code_str)
                    if ca and dt in ca["dt_to_pos"]:
                        p = ca["dt_to_pos"][dt]
                        dr = float(ca["adj_close"][p]) / float(ca["adj_close"][p - 1]) - 1.0 if p > 0 else 0.0
                        pos_state["cum_f"] *= (1.0 + dr)
                        daily_r[i] = dr
                        # For exact trade-level cap scaling, apply trade return at exit or MTM scaled
                        pos_state["cap_cum_f"] *= (1.0 + dr * w_v19)
                        cap_daily_r[i] = dr * w_v19
                        cap_nav *= (1.0 + dr * w_v19)
                    i += 1
                    continue
                elif dt == vr.exit_date:
                    dr = (1.0 + float(vr.net_ret)) / pos_state["cum_f"] - 1.0
                    daily_r[i] = dr
                    target_cap_tot = 1.0 + float(vr.net_ret) * w_v19
                    cr = target_cap_tot / pos_state["cap_cum_f"] - 1.0
                    cap_daily_r[i] = cr
                    cap_nav *= (1.0 + cr)
                    pos_state = None
                    if vr.exit_hhmm == 925 and dt in v19_by_bdt and v19_by_bdt[dt].buy_hhmm >= 935:
                        pass
                    else:
                        i += 1
                        continue
            elif pos_state["type"] == "BK":
                c6 = pos_state["c6"]
                ca = stock_arrays[c6]
                p = ca["dt_to_pos"].get(dt)
                v19_today = v19_by_bdt.get(dt)
                want_yield = (mode in ("D1_ideal", "D1_strict")) and (v19_today is not None)
                planned_exit = (dt >= pos_state["exit_date_plan"])

                if (want_yield or planned_exit) and p is not None:
                    if want_yield:
                        if not bool(ca["is_yizi_dt"][p]):
                            ex_px = float(ca["open"][p])
                            ex_adjf = float(ca["adjf"][p])
                            tot_ret = (ex_px * ex_adjf) / (pos_state["buy_px"] * pos_state["buy_adjf"]) * (1.0 - FEE_BASE) - 1.0
                            dr = (1.0 + tot_ret) / pos_state["cum_f"] - 1.0
                            daily_r[i] += dr
                            step_cap(i, dr, 1.0)
                            bk_trades.append({"buy_date": pos_state["buy_date"], "exit_date": dt, "c6": c6, "net_ret": tot_ret, "yielded": True})
                            pos_state = None
                            if mode == "D1_strict" and int(v19_today.buy_hhmm) == 925:
                                i += 1
                                continue
                        else:
                            dr = float(ca["adj_close"][p]) / float(ca["adj_close"][p - 1]) - 1.0
                            pos_state["cum_f"] *= (1.0 + dr)
                            daily_r[i] = dr
                            step_cap(i, dr, 1.0)
                            i += 1
                            continue
                    elif planned_exit:
                        use_open = pos_state.get("deferred", False)
                        if use_open:
                            if not bool(ca["is_yizi_dt"][p]):
                                ex_px = float(ca["open"][p])
                                ex_adjf = float(ca["adjf"][p])
                                tot_ret = (ex_px * ex_adjf) / (pos_state["buy_px"] * pos_state["buy_adjf"]) * (1.0 - FEE_BASE) - 1.0
                                dr = (1.0 + tot_ret) / pos_state["cum_f"] - 1.0
                                daily_r[i] = dr
                                step_cap(i, dr, 1.0)
                                bk_trades.append({"buy_date": pos_state["buy_date"], "exit_date": dt, "c6": c6, "net_ret": tot_ret, "yielded": False})
                                pos_state = None
                                i += 1
                                continue
                            else:
                                dr = float(ca["adj_close"][p]) / float(ca["adj_close"][p - 1]) - 1.0
                                pos_state["cum_f"] *= (1.0 + dr)
                                daily_r[i] = dr
                                step_cap(i, dr, 1.0)
                                i += 1
                                continue
                        else:
                            if not bool(ca["is_dt_exact"][p]):
                                ex_px = float(ca["close"][p])
                                ex_adjf = float(ca["adjf"][p])
                                tot_ret = (ex_px * ex_adjf) / (pos_state["buy_px"] * pos_state["buy_adjf"]) * (1.0 - FEE_BASE) - 1.0
                                dr = (1.0 + tot_ret) / pos_state["cum_f"] - 1.0
                                daily_r[i] = dr
                                step_cap(i, dr, 1.0)
                                bk_trades.append({"buy_date": pos_state["buy_date"], "exit_date": dt, "c6": c6, "net_ret": tot_ret, "yielded": False})
                                pos_state = None
                                i += 1
                                continue
                            else:
                                pos_state["deferred"] = True
                                dr = float(ca["adj_close"][p]) / float(ca["adj_close"][p - 1]) - 1.0
                                pos_state["cum_f"] *= (1.0 + dr)
                                daily_r[i] = dr
                                step_cap(i, dr, 1.0)
                                i += 1
                                continue
                else:
                    if p is not None and p > 0:
                        dr = float(ca["adj_close"][p]) / float(ca["adj_close"][p - 1]) - 1.0
                        pos_state["cum_f"] *= (1.0 + dr)
                        daily_r[i] = dr
                        step_cap(i, dr, 1.0)
                    i += 1
                    continue

        # 2. If slot is free, check V19.1 entry first
        if dt in v19_by_bdt:
            vr = v19_by_bdt[dt]
            c6 = vr.c6
            v19_taken.append(vr.net_ret)
            w_v19 = min(1.0, 10.0 / max(cap_nav, 1e-9))
            if dt == vr.exit_date:
                daily_r[i] = (1.0 + daily_r[i]) * (1.0 + float(vr.net_ret)) - 1.0
                step_cap(i, float(vr.net_ret), w_v19)
                i += 1
                continue
            ca = stock_arrays.get(c6)
            first_dr = 0.0
            if ca and dt in ca["dt_to_pos"]:
                p = ca["dt_to_pos"][dt]
                first_dr = (float(ca["close"][p]) / float(vr.buy_price)) * (1.0 - FEE_BASE / 2.0) - 1.0
            daily_r[i] = (1.0 + daily_r[i]) * (1.0 + first_dr) - 1.0
            step_cap(i, first_dr, w_v19)
            pos_state = {
                "type": "V19",
                "v19_row": type("V", (), {
                    "code_str": c6, "buy_date": vr.buy_date, "exit_date": vr.exit_date,
                    "exit_hhmm": int(vr.exit_hhmm), "buy_price": float(vr.buy_price), "net_ret": float(vr.net_ret)
                })(),
                "cum_f": (1.0 + first_dr),
                "cap_w": w_v19,
                "cap_cum_f": (1.0 + first_dr * w_v19),
            }
            i += 1
            continue

        # 3. Otherwise completely idle day -> check backup large-cap entry (if not V19_BASE)
        if mode != "V19_BASE" and dt in bk_best:
            if (not only_post_climax35) or (dt in super_climax_buy_dts):
                row = bk_best[dt]
                c6 = row["c6"]
                ca = stock_arrays[c6]
                p = ca["dt_to_pos"].get(dt)
                if p is not None and p + max_hold_d < len(ca["dts"]):
                    plan_exit = ca["dts"][p + max_hold_d]
                    buy_px = float(ca["open"][p])
                    buy_adjf = float(ca["adjf"][p])
                    first_dr = (float(ca["close"][p]) / buy_px) * (1.0 - FEE_BASE / 2.0) - 1.0
                    daily_r[i] = first_dr
                    step_cap(i, first_dr, 1.0)
                    pos_state = {
                        "type": "BK", "c6": c6, "buy_date": dt, "buy_px": buy_px,
                        "buy_adjf": buy_adjf, "exit_date_plan": plan_exit,
                        "cum_f": 1.0 + first_dr, "deferred": False
                    }
        i += 1

    cap_r = cap_daily_r

    def win_perf_arr(arr, s_dt: str, e_dt: str) -> dict:
        idx_l = [d_idx[d] for d in dts_5y if s_dt <= d <= e_dt]
        sub_r = arr[idx_l]
        eq = np.cumprod(1.0 + sub_r)
        nav = float(eq[-1]) if len(eq) else 1.0
        pk = np.maximum.accumulate(np.insert(eq, 0, 1.0))[1:]
        mdd = float(np.max((pk - eq) / pk)) if len(eq) else 0.0
        yrs = max(0.05, len(sub_r) / 243.0)
        cagr = float(nav ** (1.0 / yrs) - 1.0)
        sh = float(np.mean(sub_r) / (np.std(sub_r) + 1e-12) * np.sqrt(243.0)) if np.std(sub_r) > 0 else 0.0
        cal = float(cagr / mdd) if mdd > 1e-6 else 0.0
        return {
            "nav": round(nav, 2), "cagr_pct": round(cagr * 100.0, 2),
            "mdd_pct": round(mdd * 100.0, 2), "sharpe": round(sh, 2), "calmar": round(cal, 2)
        }

    bk_rets = np.array([x["net_ret"] for x in bk_trades], dtype=float)
    bk_nav = float(np.prod(1.0 + bk_rets)) if len(bk_rets) else 1.0
    bk_wr = float((bk_rets > 0).mean() * 100.0) if len(bk_rets) else 0.0
    return {
        "mode": mode,
        "only_post_climax35": only_post_climax35,
        "v19_trades_taken": len(v19_taken),
        "bk_trades_taken": len(bk_trades),
        "bk_wr_pct": round(bk_wr, 2),
        "bk_solo_nav": round(bk_nav, 4),
        "5Y": win_perf_arr(daily_r, "2021-11-16", "2026-11-23"),
        "IS": win_perf_arr(daily_r, "2021-11-16", "2023-12-31"),
        "OOS": win_perf_arr(daily_r, "2024-01-01", "2026-11-23"),
        "2026": win_perf_arr(daily_r, "2026-01-01", "2026-11-23"),
        "5Y_cap10m_v19": win_perf_arr(cap_r, "2021-11-16", "2026-11-23"),
        "OOS_cap10m_v19": win_perf_arr(cap_r, "2024-01-01", "2026-11-23"),
    }


def main():
    t_start = time.time()
    df, all_dts = load_daily_universe()
    sh300, sh905, csi1000, csi1000_corr = build_benchmarks(df)
    csrc_ind, csrc_name, tox_dates, earn_dates, ctr_buy_dates, ir_dates, app_title_first, chip_title_first = load_csrc_and_notices_pit()
    day_hot_plates, fam_first_seen, plate_first_seen = build_kpl_pit_engine(df, all_dts)

    # Index per-stock numpy arrays for ultra-fast simulation
    t0 = time.time()
    stock_arrays = {}
    for c6, grp in df.groupby("c6", sort=False):
        dts_l = grp["dt"].tolist()
        stock_arrays[c6] = {
            "dts": dts_l,
            "dt_to_pos": {d: idx for idx, d in enumerate(dts_l)},
            "open": grp["open"].to_numpy(float),
            "high": grp["high"].to_numpy(float),
            "close": grp["close"].to_numpy(float),
            "adj_close": grp["adj_close"].to_numpy(float),
            "volume": grp["volume"].to_numpy(float),
            "dt_px": grp["dt_px"].to_numpy(float),
            "zt_px": grp["zt_px"].to_numpy(float),
            "adjf": grp["adjf"].to_numpy(float),
            "is_dt_exact": grp["is_dt_exact"].to_numpy(bool),
            "is_yizi_dt": grp["is_yizi_dt"].to_numpy(bool),
            "is_yizi_zt_open": grp["is_yizi_zt_open"].to_numpy(bool),
            "ma10_adj": grp["ma10_adj"].to_numpy(float),
            "o_pct": grp["o_pct"].to_numpy(float),
        }

    # Build day-by-day lookup table for fast signal scanning (>= 2021-11-01)
    df_sig = df[(df["dt"] >= "2021-11-01") & (df["trade_num"] >= 60) & (df["mcap"] >= 140.0) & (df["pct"] >= 0.025)].copy()
    sig_by_dt = {dt: grp for dt, grp in df_sig.groupby("dt", sort=True)}

    # Build permutation pool of large caps (>= 200亿) for hold_5 & ma10 Monte Carlo p-value
    df_perm200 = df[(df["dt"] >= "2021-11-15") & (df["trade_num"] >= 60) & (df["mcap"] >= 200.0) & (~df["is_yizi_zt_open"]) & (df["volume"] > 0)][["dt", "c6"]]
    perm_pool_5d = defaultdict(list)
    perm_pool_ma10 = defaultdict(list)
    for r in df_perm200.itertuples(index=False):
        ca = stock_arrays[r.c6]
        bi = ca["dt_to_pos"].get(r.dt)
        if bi is not None:
            res = simulate_exit_and_ret(ca, bi, "hold_5", FEE_BASE)
            if res is not None:
                perm_pool_5d[r.dt].append(res["net_ret"])
            res_m = simulate_exit_and_ret(ca, bi, "ma10", FEE_BASE)
            if res_m is not None:
                perm_pool_ma10[r.dt].append(res_m["net_ret"])
    perm_pool_5d = {k: np.array(v, dtype=float) for k, v in perm_pool_5d.items()}
    perm_pool_ma10 = {k: np.array(v, dtype=float) for k, v in perm_pool_ma10.items()}
    print(f"[4/6] Indexed stock arrays & perm pool in {time.time()-t0:.1f}s")

    # =========================================================================
    # Scan Signals for Prototypes A, B, C
    # =========================================================================
    t0 = time.time()
    all_cands_A = []
    all_cands_B = []
    all_cands_C = []

    sig_dts_sorted = [d for d in all_dts if "2021-11-12" <= d <= "2026-11-20"]
    dt_next_map = {all_dts[i]: all_dts[i + 1] for i in range(len(all_dts) - 1)}

    for sig_dt in sig_dts_sorted:
        buy_dt = dt_next_map.get(sig_dt)
        if not buy_dt:
            continue
        pls = day_hot_plates.get(sig_dt, [])
        if not pls:
            continue
        day_df = sig_by_dt.get(sig_dt)
        if day_df is None or len(day_df) == 0:
            continue

        # Iterate rk_c <= 2 plates (plus rk_c <= 5 for pure Appliance deep-dive)
        for pname, rk_c, sz, sc_clean, fams, today_c6s in pls:
            is_app_c = bool(APPLIANCE_RE.search(pname))
            if rk_c > 2 and not (is_app_c and rk_c <= 5):
                continue
            is_hard_tech = bool(HARD_TECH_PLATE_RE.search(pname))
            is_core_tech_c = bool(CORE_TECH_C_RE.search(pname))
            is_cons_c = bool(CONS_C_RE.search(pname)) and ("消费电子" not in pname) and ("商业航天" not in pname)

            if sz < 3:
                continue

            # Filter stocks belonging to this hot plate (strictly PIT)
            matched = []
            for r in day_df.itertuples(index=False):
                if is_member_of_plate_pit(r.c6, sig_dt, pname, fams, today_c6s,
                                          fam_first_seen, plate_first_seen, csrc_ind, csrc_name, app_title_first, chip_title_first):
                    matched.append(r)
            if not matched:
                continue
            mdf = pd.DataFrame(matched)
            mdf = mdf.sort_values("amt_yi", ascending=False).reset_index(drop=True)
            mdf["amt_rk_in_plate"] = np.arange(1, len(mdf) + 1)

            for row in mdf.itertuples(index=False):
                c6 = row.c6
                nm = csrc_name.get(c6, c6)
                if "ST" in nm.upper() or "退" in nm:
                    continue
                if has_event_in_90d(tox_dates, c6, sig_dt):
                    continue
                ca = stock_arrays[c6]
                bi = ca["dt_to_pos"].get(buy_dt)
                if bi is None:
                    continue
                if bool(ca["is_yizi_zt_open"][bi]) or bool(ca["is_yizi_dt"][bi]) or float(ca["volume"][bi]) <= 0:
                    continue

                o_pct_buy = float(ca["o_pct"][bi])
                ret_pre10 = float(row.ret_pre10) if pd.notna(row.ret_pre10) else 0.0
                pos60 = float(row.pos60) if pd.notna(row.pos60) else 0.5
                is_low_pos = (ret_pre10 <= 0.0) or (pos60 <= 0.60)

                base_info = {
                    "sig_date": sig_dt, "buy_date": buy_dt, "c6": c6, "name": nm,
                    "plate": pname, "rk_c": rk_c, "sz": sz,
                    "mcap": round(float(row.mcap), 1), "amt_yi": round(float(row.amt_yi), 2),
                    "pct": round(float(row.pct) * 100.0, 2), "is_zt": bool(row.is_zt),
                    "o_pct_buy": round(o_pct_buy * 100.0, 2),
                    "ret_pre10": round(ret_pre10 * 100.0, 2), "pos60": round(pos60, 3),
                    "amt_rk": int(row.amt_rk_in_plate),
                    "is_hard_tech": is_hard_tech, "is_core_tech_c": is_core_tech_c,
                    "is_cons_c": is_cons_c, "is_app_c": is_app_c,
                }

                # Prototype A: rk_c<=2, Hard Tech sz>=5, mcap>=200, amt>=8, amt_rk<=3, pct>=5%, low_pos
                if rk_c <= 2 and sz >= 5 and is_hard_tech and row.mcap >= 200.0 and row.amt_yi >= 8.0 and row.amt_rk_in_plate <= 3 and row.pct >= 0.05 and is_low_pos:
                    all_cands_A.append(base_info)

                # Prototype B: rk_c<=2, sz>=5, mcap>=150, pct>=3%, amt_rk<=2, earn/ctr_buy or IR>=1 in 90d
                if rk_c <= 2 and sz >= 5 and row.mcap >= 150.0 and row.amt_yi >= 3.0 and row.amt_rk_in_plate <= 2 and row.pct >= 0.03:
                    has_ir = has_event_in_90d(ir_dates, c6, sig_dt)
                    has_earn = has_event_in_90d(earn_dates, c6, sig_dt)
                    has_cb = has_event_in_90d(ctr_buy_dates, c6, sig_dt)
                    if has_ir or has_earn or has_cb:
                        b_info = dict(base_info)
                        b_info["has_ir"] = has_ir
                        b_info["has_earn"] = has_earn
                        b_info["has_cb"] = has_cb
                        b_info["uniform_5y"] = (has_ir or has_earn)
                        all_cands_B.append(b_info)

                # Prototype C: Direct contrast (Core Tech vs Consumer/Appliance) under same rule (mcap>=150, amt>=3, rk<=3, pct>=3%)
                if (is_core_tech_c or is_cons_c) and row.mcap >= 150.0 and row.amt_yi >= 3.0 and row.amt_rk_in_plate <= 3 and row.pct >= 0.03:
                    all_cands_C.append(base_info)

    dfA = pd.DataFrame(all_cands_A)
    dfB = pd.DataFrame(all_cands_B)
    dfC = pd.DataFrame(all_cands_C)
    print(f"[5/6] Generated candidates in {time.time()-t0:.1f}s -> A={len(dfA)}, B={len(dfB)}, C={len(dfC)}")

    def attach_sim(cdf: pd.DataFrame, exit_mode: str, fee: float) -> pd.DataFrame:
        if len(cdf) == 0:
            return cdf
        out_rows = []
        for r in cdf.to_dict("records"):
            ca = stock_arrays[r["c6"]]
            bi = ca["dt_to_pos"].get(r["buy_date"])
            if bi is None:
                continue
            res = simulate_exit_and_ret(ca, bi, exit_mode, fee)
            if res is None:
                continue
            rr = dict(r)
            rr.update(res)
            out_rows.append(rr)
        return pd.DataFrame(out_rows)

    # =========================================================================
    # Run Full Stress Matrix
    # =========================================================================
    summary = {
        "benchmarks": {
            "CSI300": {w: round(bench_period_ret(sh300, s, e) * 100.0, 2) for w, s, e in [
                ("5Y", "2021-11-16", "2026-11-23"), ("IS", "2021-11-16", "2023-12-31"),
                ("OOS", "2024-01-01", "2026-11-23"), ("3Y", "2023-11-23", "2026-11-23"),
                ("2026", "2026-01-01", "2026-11-23")
            ]},
            "CSI1000_proxy": {w: round(bench_period_ret(csi1000, s, e) * 100.0, 2) for w, s, e in [
                ("5Y", "2021-11-16", "2026-11-23"), ("IS", "2021-11-16", "2023-12-31"),
                ("OOS", "2024-01-01", "2026-11-23"), ("3Y", "2023-11-23", "2026-11-23"),
                ("2026", "2026-01-01", "2026-11-23")
            ]},
            "CSI1000_proxy_58d_corr": round(csi1000_corr, 4),
            "CSI500_to_1118": {w: round(bench_period_ret(sh905, s, e) * 100.0, 2) for w, s, e in [
                ("5Y", "2021-11-16", "2026-11-23"), ("IS", "2021-11-16", "2023-12-31"),
                ("OOS", "2024-01-01", "2026-11-23"), ("3Y", "2023-11-23", "2026-11-23"),
                ("2026", "2026-01-01", "2026-11-23")
            ]},
        },
        "archetypes": {},
        "overlays": {},
    }
    comp_rows = []
    all_case_trades = []

    def record_variant(arch_name: str, sub_df: pd.DataFrame, exit_mode: str, fee: float = FEE_BASE, run_perm: bool = True, custom_perm_pool: dict = None):
        sim_df = attach_sim(sub_df, exit_mode, fee)
        pp = custom_perm_pool if custom_perm_pool is not None else perm_pool_5d
        ev = eval_trade_ledger(sim_df, sh300, csi1000, all_dts, stock_arrays, fee=fee, run_perm=run_perm, perm_pool_by_dt=pp)
        s1 = ev["1slot"]
        rec = {
            "archetype": arch_name, "exit": exit_mode, "fee_bps": int(fee * 10000),
            "perm_p": ev["perm_p"], "1slot": s1,
        }
        summary["archetypes"][f"{arch_name}__{exit_mode}__f{int(fee*10000)}"] = rec
        if s1:
            w5, wis, woos, w3, w26, w924 = s1["5Y"], s1["IS"], s1["OOS"], s1["3Y"], s1["2026"], s1["5Y_ex924"]
            comp_rows.append({
                "variant": f"{arch_name} | {exit_mode} | fee={fee*100:.2f}%",
                "n_5y": w5["n"], "n_raw": w5["n_raw"], "wr_5y": w5["wr"], "payoff_5y": w5["payoff"],
                "nav_5y": w5["nav"], "cagr_5y": w5.get("cagr_pct", 0), "mdd_5y": w5["mdd_pct"],
                "sharpe_5y": w5.get("sharpe", 0), "calmar_5y": w5.get("calmar", 0),
                "ex300_5y_pp": w5["ex300_pp"], "ex1000_5y_pp": w5["ex1000_pp"],
                "ew_nav_5y": w5.get("ew_nav", 1.0),
                "ex_top1_nav": w5.get("ex_top1_nav", 1.0), "ex_top3_nav": w5.get("ex_top3_nav", 1.0), "ex_top5_nav": w5.get("ex_top5_nav", 1.0),
                "n_is": wis["n"], "nav_is": wis["nav"], "ex300_is_pp": wis["ex300_pp"],
                "n_oos": woos["n"], "nav_oos": woos["nav"], "wr_oos": woos["wr"], "ex300_oos_pp": woos["ex300_pp"], "ex1000_oos_pp": woos["ex1000_pp"],
                "n_3y": w3["n"], "nav_3y": w3["nav"], "ex300_3y_pp": w3["ex300_pp"],
                "n_26": w26["n"], "nav_26": w26["nav"], "ex300_26_pp": w26["ex300_pp"],
                "nav_5y_ex924": w924["nav"], "ex300_ex924_pp": w924["ex300_pp"],
                "perm_p": ev["perm_p"],
            })
        return ev

    # --- Prototype A Matrix & Slices ---
    for ex in ("hold_3", "hold_5", "hold_10", "ma10"):
        ev = record_variant("A_HardTech_All", dfA, ex, FEE_BASE, run_perm=(ex in ("hold_5", "ma10")), custom_perm_pool=(perm_pool_ma10 if ex == "ma10" else None))
        if ex == "hold_5" and "ss_df" in ev:
            all_case_trades.append(ev["ss_df"].assign(source="A_hold5"))
    # Harsh slippage 0.50% & 0.70%
    record_variant("A_HardTech_All", dfA, "hold_5", FEE_SLIP05, run_perm=False)
    record_variant("A_HardTech_All", dfA, "hold_5", FEE_SLIP07, run_perm=False)
    record_variant("A_HardTech_All", dfA, "ma10", FEE_SLIP05, run_perm=False)
    # Slices: sz>=15, sz>35, ZT vs Non-ZT大阳, Open caps
    record_variant("A_sz_ge15", dfA[dfA["sz"] >= 15], "hold_5", FEE_BASE)
    record_variant("A_sz_gt35_super", dfA[dfA["sz"] > 35], "hold_5", FEE_BASE)
    record_variant("A_ZT_sig", dfA[dfA["is_zt"]], "hold_5", FEE_BASE)
    record_variant("A_NonZT_BigYang", dfA[~dfA["is_zt"]], "hold_5", FEE_BASE)
    record_variant("A_Open_le2pct", dfA[dfA["o_pct_buy"] <= 2.0], "hold_5", FEE_BASE)
    record_variant("A_Open_le0pct", dfA[dfA["o_pct_buy"] <= 0.0], "hold_5", FEE_BASE)
    record_variant("A_Open_gt3pct", dfA[dfA["o_pct_buy"] > 3.0], "hold_5", FEE_BASE)

    # --- Prototype B Matrix & Slices ---
    for ex in ("hold_5", "hold_10", "hold_20"):
        evB = record_variant("B_InstFund_All", dfB, ex, FEE_BASE, run_perm=(ex == "hold_5"))
        if ex == "hold_5" and "ss_df" in evB:
            all_case_trades.append(evB["ss_df"].assign(source="B_hold5"))
    record_variant("B_InstFund_All", dfB, "hold_5", FEE_SLIP05, run_perm=False)
    record_variant("B_InstFund_Uniform5Y", dfB[dfB["uniform_5y"]], "hold_5", FEE_BASE)
    record_variant("B_InstFund_HardTech", dfB[dfB["is_hard_tech"]], "hold_5", FEE_BASE)

    # --- Prototype C Contrast (Appliance/Consumer vs Robot/Chip/AI) ---
    for ex in ("hold_3", "hold_5", "hold_10"):
        record_variant("C_CoreTech_rk2_sz5", dfC[dfC["is_core_tech_c"] & (dfC["rk_c"] <= 2) & (dfC["sz"] >= 5)], ex, FEE_BASE, run_perm=(ex == "hold_5"))
        evC_cons5 = record_variant("C_Consumer_rk2_sz5", dfC[dfC["is_cons_c"] & (dfC["rk_c"] <= 2) & (dfC["sz"] >= 5)], ex, FEE_BASE, run_perm=(ex == "hold_5"))
        record_variant("C_Consumer_rk2_sz3", dfC[dfC["is_cons_c"] & (dfC["rk_c"] <= 2) & (dfC["sz"] >= 3)], ex, FEE_BASE, run_perm=(ex == "hold_5"))
        if ex == "hold_5" and "ss_df" in evC_cons5:
            all_case_trades.append(evC_cons5["ss_df"].assign(source="C_Cons5_hold5"))
    evC_app = record_variant("C_Appliance_rk5_sz3", dfC[dfC["is_app_c"] & (dfC["sz"] >= 3)], "hold_5", FEE_BASE)
    record_variant("C_Appliance_rk5_sz3", dfC[dfC["is_app_c"] & (dfC["sz"] >= 3)], "hold_10", FEE_BASE, run_perm=False)
    if "ss_df" in evC_app:
        all_case_trades.append(evC_app["ss_df"].assign(source="C_App_hold5"))

    # --- CSCV PBO across A & B variants ---
    dts_5y = [d for d in all_dts if "2021-11-16" <= d <= "2026-11-23"]
    d5_i = {d: i for i, d in enumerate(dts_5y)}
    def build_var_vec(sub_df, ex):
        sim_df = attach_sim(sub_df, ex, FEE_BASE)
        ev = eval_trade_ledger(sim_df, sh300, csi1000, all_dts, stock_arrays, fee=FEE_BASE, run_perm=False)
        vec = np.zeros(len(dts_5y), dtype=float)
        if "ss_df" in ev:
            for r in ev["ss_df"].itertuples(index=False):
                if r.exit_date in d5_i:
                    vec[d5_i[r.exit_date]] = r.net_ret
        return vec
    pbo_A_vecs = [build_var_vec(sub, ex) for sub in [dfA, dfA[dfA["o_pct_buy"] <= 2.0], dfA[~dfA["is_zt"]], dfA[dfA["sz"] >= 15]] for ex in ("hold_3", "hold_5", "hold_10")]
    pbo_B_vecs = [build_var_vec(sub, ex) for sub in [dfB, dfB[dfB["uniform_5y"]], dfB[dfB["is_hard_tech"]], dfB[dfB["o_pct_buy"] <= 2.0]] for ex in ("hold_5", "hold_10", "hold_20")]
    summary["pbo_A_12variants"] = compute_cscv_pbo(pbo_A_vecs, n_blocks=8)
    summary["pbo_B_12variants"] = compute_cscv_pbo(pbo_B_vecs, n_blocks=8)

    # =========================================================================
    # Prototype D: V19.1 Empty-Day Overlay
    # =========================================================================
    print("[6/6] Running Prototype D V19.1 Idle-Day Overlays...")
    v19_path = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_combined_5strat_v191_slot1_clean.csv"
    v19_df = pd.read_csv(v19_path)
    summary["overlays"]["V19_BASE"] = run_v191_overlay(v19_df, None, stock_arrays, all_dts, sh300, csi1000, day_hot_plates, "V19_BASE")

    for bk_name, bk_df, h_d in [("ProtoA_3d", dfA, 3), ("ProtoA_5d", dfA, 5), ("ProtoB_5d", dfB, 5), ("ProtoA_NonZT_5d", dfA[~dfA["is_zt"]], 5)]:
        for md in ("D1_ideal", "D1_strict", "D2_lock"):
            key = f"{bk_name}__{md}"
            summary["overlays"][key] = run_v191_overlay(v19_df, bk_df, stock_arrays, all_dts, sh300, csi1000, day_hot_plates, md, max_hold_d=h_d, only_post_climax35=False)
        summary["overlays"][f"{bk_name}__D3_postClimax35_D1ideal"] = run_v191_overlay(
            v19_df, bk_df, stock_arrays, all_dts, sh300, csi1000, day_hot_plates, "D1_ideal", max_hold_d=h_d, only_post_climax35=True
        )

    # Save CSV & JSON & Case Studies (Top 10 winners + Top 10 losers across A/B/C)
    pd.DataFrame(comp_rows).to_csv(f"{OUT_DIR}/archetypes_comparison.csv", index=False, encoding="utf-8-sig")

    if all_case_trades:
        ct = pd.concat(all_case_trades, ignore_index=True).drop_duplicates(subset=["sig_date", "c6", "exit_date"])
        ct["net_ret_pct"] = (ct["net_ret"] * 100.0).round(2)
        top10 = ct.nlargest(10, "net_ret").assign(bucket="TOP10_WIN")
        bot10 = ct.nsmallest(10, "net_ret").assign(bucket="BOT10_LOSS")
        cases = pd.concat([top10, bot10], ignore_index=True)
        # Also attach iconic stocks check (拓普/三花/寒武纪/中芯/中际/新易盛/工业富联/美的/格力/海信)
        icon_codes = {"601689", "002050", "688256", "688981", "300308", "300502", "601138", "000333", "000651", "000921"}
        icons = ct[ct["c6"].isin(icon_codes)].sort_values("net_ret", ascending=False).head(15).assign(bucket="ICONIC_SAMPLE")
        pd.concat([cases, icons], ignore_index=True).to_csv(f"{OUT_DIR}/case_studies.csv", index=False, encoding="utf-8-sig")

    with open(f"{OUT_DIR}/summary_part3.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    print(f"DONE in {time.time()-t_start:.1f}s! Outputs saved in {OUT_DIR}")


if __name__ == "__main__":
    main()
