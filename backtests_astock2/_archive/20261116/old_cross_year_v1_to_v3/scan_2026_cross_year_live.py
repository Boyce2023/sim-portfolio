#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, re, json, glob, sqlite3, urllib.request
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA = f"{SIM}/data"

MA_PAT = re.compile(r"(重大资产重组|控制权变更|实控人变更|筹划控制权|借壳|要约收购|筹划重大资产|购买资产.*复牌|发行股份及支付现金购买资产预案|协议转让.*控制权)")
MA_EXC = re.compile(r"(解除限售|限售股上市|募集资金账户注销|业绩承诺补偿)")
BAD_KPL = ("并购重组", "股权转让", "实控人变更", "借壳", "壳资源", "ST板块", "摘帽")

def fetch_qq_quotes(q_codes):
    out = {}
    for i in range(0, len(q_codes), 65):
        u = "http://qt.gtimg.cn/q=" + ",".join(q_codes[i:i+65])
        try:
            raw = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=4).read().decode("gbk", "ignore")
            for ln in raw.splitlines():
                if '="' not in ln: continue
                lhs, rhs = ln.split('="', 1)
                sym = lhs.split("_")[-1].strip()
                f = rhs.split("~")
                if len(f) > 45:
                    c6, nm = f[2].strip(), f[1].strip()
                    key = sym if sym in ("sh000001", "sz399001", "sh000300") else c6
                    cur, pre, opn = float(f[3] or 0), float(f[4] or 0), float(f[5] or 0)
                    hi, lo = float(f[33] or 0), float(f[34] or 0)
                    vol_sh = float(f[36] or 0) * 100.0
                    amt = float(f[37] or 0) * 10000.0
                    cmv = float(f[44] or 0)
                    dt_raw = str(f[30])[:8]
                    dt_s = f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}" if len(dt_raw) == 8 else "2026-11-16"
                    if cur > 0 and pre > 0:
                        out[key] = {"dt": dt_s, "name": nm, "open": opn or cur, "high": hi or cur, "low": lo or cur,
                                    "close": cur, "pre": pre, "vol": vol_sh, "amt": amt, "cmv": cmv}
        except Exception:
            pass
    return out

def main():
    # 1. Load daily prices since 2026-08-01 + append live 2026-11-16 15:00 close!
    cols = ["date", "ticker", "open", "high", "low", "close", "amount", "volume", "turn", "oshare"]
    df = ds.dataset(f"{DATA}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2026-08-01"))
    ).to_table().to_pandas()
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")

    all_c6 = sorted(df["c6"].unique())
    q_list = ["sh000001", "sz399001", "sh000300"] + [("sh" if c.startswith("6") else "sz") + c for c in all_c6]
    live_q = fetch_qq_quotes(q_list)
    max_parq_dt = df["dt_str"].max()
    live_dt = live_q.get("sh000001", {}).get("dt", "2026-11-16")
    print(f"Parquet max_dt={max_parq_dt} | Live quote dt={live_dt} | Fetched={len(live_q)}")

    last_osh = df.sort_values("dt_str").groupby("c6")["oshare"].last().to_dict()
    if live_dt > max_parq_dt:
        add_rows = []
        for c6 in all_c6:
            q = live_q.get(c6)
            if not q or q["dt"] != live_dt: continue
            osh = last_osh.get(c6, 0.0)
            if osh <= 0 and q["cmv"] > 0 and q["close"] > 0:
                osh = q["cmv"] * 1e8 / q["close"]
            add_rows.append({
                "date": pd.Timestamp(live_dt), "ticker": f"{c6}.SH" if c6.startswith("6") else f"{c6}.SZ",
                "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                "amount": q["amt"], "volume": q["vol"], "turn": (q["vol"] / osh) if osh > 0 else 0.0,
                "oshare": osh, "c6": c6, "dt_str": live_dt
            })
        if add_rows:
            df = pd.concat([df, pd.DataFrame(add_rows)], ignore_index=True)

    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="last", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Index series for exact 10d100 & 30d200
    idx_data = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    sh_idx, sz_idx = dict(idx_data.get("sh000001", {})), dict(idx_data.get("sz399001", {}))
    if "sh000001" in live_q: sh_idx[live_q["sh000001"]["dt"]] = live_q["sh000001"]["close"]
    if "sz399001" in live_q: sz_idx[live_q["sz399001"]["dt"]] = live_q["sz399001"]["close"]

    g = df.groupby("c6", sort=False)
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["mcap"] = df["close"] * df["oshare"] / 1e8
    df["amt_yi"] = df["amount"] / 1e8
    df["zt_px"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.01) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_px"] - 0.01) & (df["low"] >= df["zt_px"] - 0.01)
    s_zt = df["is_zt"].astype(int)
    df["zt_streak"] = s_zt.groupby((~df["is_zt"]).cumsum()).cumsum()
    df["ma10"] = g["close"].transform(lambda s: s.rolling(10, min_periods=8).mean())
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=15).mean())
    df["zt_25d"] = g["is_zt"].transform(lambda s: s.rolling(25, min_periods=5).sum())
    df["yizi_5d"] = g["is_yizi"].transform(lambda s: s.rolling(5, min_periods=1).sum())

    # 2. Load KPL plates (2026-04 to 2026-11) + THS today
    date_plate = defaultdict(dict)
    stock_plates_20d = defaultdict(Counter)
    with open(f"{DATA}/kpl_plates_2018_2026_merged.jsonl", errors="ignore") as f:
        for ln in f:
            if '"2026-' not in ln: continue
            d = json.loads(ln)
            dt = d.get("date", "")
            for pl in d.get("plates", []):
                pn = pl.get("plate", "").strip()
                if pn and pn not in ("其他", "公告", "ST板块"):
                    stks = [str(s[0])[-6:] for s in pl.get("stocks", [])]
                    date_plate[dt][pn] = stks
                    if dt >= "2026-10-15":
                        for c6 in stks: stock_plates_20d[c6][pn] += 1
    for tf in sorted(glob.glob(f"{DATA}/ths_limit_up_daily/2026-11-*.json")):
        tj = json.load(open(tf))
        tdt = tj.get("date", "")
        for s in tj.get("stocks", []):
            c6 = str(s.get("code", ""))[:6]
            rt = str(s.get("reason_type", "")).split("+")[0].strip()
            if rt and rt not in ("其他", "公告"):
                date_plate[tdt].setdefault(rt, [])
                if c6 not in date_plate[tdt][rt]: date_plate[tdt][rt].append(c6)
                stock_plates_20d[c6][rt] += 1

    kpl_dts = sorted(date_plate.keys())
    recent10_plates = Counter()
    for d in kpl_dts[-10:]:
        for p, stks in date_plate[d].items():
            if not any(b in p for b in BAD_KPL):
                recent10_plates[p] += len(stks)
    print("Recent 10d Top 10 KPL Mainlines:", recent10_plates.most_common(10))
    top1_p = recent10_plates.most_common(1)[0][0] if recent10_plates else ""
    top2_ps = {p for p, _ in recent10_plates.most_common(2)}
    top4_ps = {p for p, _ in recent10_plates.most_common(4)}

    # Check 100yi midfielders per plate in recent 10d
    recent_sub = df[df["dt_str"] >= "2026-10-28"]
    big_movers = set(recent_sub[(recent_sub["mcap"] >= 100.0) & (recent_sub["amt_yi"] >= 18.0) & (recent_sub["pct"] >= 0.07)]["c6"].unique())
    plate_has_mid = {p for p in recent10_plates if any(c in big_movers for d in kpl_dts[-10:] for c in date_plate[d].get(p, []))}

    # 3. Load Notices, IR, Community, Flash Policy, Industry
    ind_df = pd.read_csv(f"{DATA}/industry.csv")
    csrc_map = dict(zip(ind_df["code"].str[3:], ind_df["industry"]))
    holders = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"))

    cn = sqlite3.connect(f"file:{DATA}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    notices_by_c6 = defaultdict(list)
    for dt, c6, ti, at in cn.execute("SELECT trade_date_avail, sec_code, title, ann_type FROM notices WHERE trade_date_avail >= '2026-07-15'"):
        notices_by_c6[str(c6)[-6:]].append((str(dt)[:10], f"{ti} {at}"))
    cn.close()

    # Flash news last 15 days policy counts
    fn = sqlite3.connect(f"file:{DATA}/flash_news_5y_pit.db?mode=ro", uri=True)
    fn_txts = [f"{r[0]} {r[1]}" for r in fn.execute("SELECT title, content FROM flash_news WHERE pub_datetime_cst >= '2026-10-28'")]
    fn.close()
    pol_min_re = re.compile(r"(国务院|政治局|发改委|工信部|国家航天局|国资委|设立.*司|三年行动计划|指导意见|重大突破|十五五)")
    pol_geo_re = re.compile(r"(台湾|海峡|福建|制裁|关税|自主可控|太空|卫星|机器人|具身智能|低空|固态电池)")

    # Screen active candidates on latest day (live_dt) with >=2 ZTs since 10-15 & mcap 20~350yi & above MA20*0.97
    latest_df = df[df["dt_str"] == df["dt_str"].max()].copy()
    w_oct = df[df["dt_str"] >= "2026-10-15"]
    oct_zts = w_oct.groupby("c6")["is_zt"].sum().to_dict()
    oct_hs_zts = w_oct.groupby("c6").apply(lambda x: int((x["is_zt"] & (~x["is_yizi"])).sum())).to_dict()

    cm_conn = sqlite3.connect(f"file:{DATA}/astock_community_5y_pit.db?mode=ro", uri=True)
    results = []
    for _, r in latest_df.iterrows():
        c6 = r["c6"]
        if oct_hs_zts.get(c6, 0) < 2 or not (20.0 <= r["mcap"] <= 350.0): continue
        nm = live_q.get(c6, {}).get("name", c6)
        if "ST" in nm or "退" in nm or r["yizi_5d"] >= 2: continue
        if pd.notna(r["ma20"]) and r["close"] < r["ma20"] * 0.96: continue

        # Exclude M&A
        nlist = notices_by_c6.get(c6, [])
        if any(MA_PAT.search(t) and not MA_EXC.search(t) for _, t in nlist): continue
        top_ps = stock_plates_20d.get(c6, Counter()).most_common(3)
        if not top_ps or any(b in top_ps[0][0] for b in BAD_KPL): continue
        main_p = top_ps[0][0]

        # Exact 10d100 & 30d200
        sub_b = df[df["c6"] == c6].tail(35)
        dts, cls = sub_b["dt_str"].tolist(), sub_b["close"].tolist()
        imap = sh_idx if c6.startswith("6") else sz_idx
        ic_now = imap.get(dts[-1], 3600.0)
        dev10, p100, dev30, p200 = 0.0, 99999.0, 0.0, 99999.0
        for w in range(1, min(10, len(cls) - 1) + 1):
            bi, bc = imap.get(dts[-1 - w]), cls[-1 - w]
            if bi and bc > 0:
                dev10 = max(dev10, (cls[-1] / bc - 1.0) - (ic_now / bi - 1.0))
                p100 = min(p100, bc * (2.0 + (ic_now / bi - 1.0)))
        for w in range(1, min(30, len(cls) - 1) + 1):
            bi, bc = imap.get(dts[-1 - w]), cls[-1 - w]
            if bi and bc > 0:
                dev30 = max(dev30, (cls[-1] / bc - 1.0) - (ic_now / bi - 1.0))
                p200 = min(p200, bc * (3.0 + (ic_now / bi - 1.0)))
        hr10 = p100 / cls[-1] - 1.0
        hr30 = p200 / cls[-1] - 1.0
        tight_hr = min(hr10, hr30)

        # Past 15d max dev10 for detour signature
        max_p15_d10 = 0.0
        for back in range(1, min(12, len(cls) - 11)):
            idx_e = -1 - back
            ie = imap.get(dts[idx_e], ic_now)
            for w in range(1, 11):
                bi, bc = imap.get(dts[idx_e - w]), cls[idx_e - w]
                if bi and bc > 0:
                    max_p15_d10 = max(max_p15_d10, (cls[idx_e] / bc - 1.0) - (ie / bi - 1.0))
        is_detour = int(0.62 <= max_p15_d10 <= 1.20 and dev10 <= 0.58 and hr30 >= 0.35)

        # Notices & Fundamentals
        has_contract = int(any(d >= "2026-09-25" and re.search(r"(中标|重大合同|日常经营重大合同|采购合同)", t) for d, t in nlist))
        has_coop = int(any(d >= "2026-09-25" and re.search(r"(战略合作|框架协议)", t) for d, t in nlist))
        has_newsub = int(any(d >= "2026-09-15" and re.search(r"(设立.*公司|合资|对外投资)", t) for d, t in nlist))
        q3_up = int(any(re.search(r"(预增|略增|续盈)", t) for _, t in nlist))
        q3_turn = int(any("扭亏" in t for _, t in nlist))
        q3_loss = int(any(re.search(r"(预亏|首亏|续亏|增亏)", t) for _, t in nlist))
        has_reg = int(any(d >= "2026-10-28" and re.search(r"(监管工作函|关注函|重点监控|严重异常波动)", t) and "回复" not in t for d, t in nlist))
        has_red = int(any(d >= "2026-09-15" and re.search(r"(减持计划|股东减持|预披露.*减持)", t) for d, t in nlist))
        has_clarify_deny = int(any(d >= "2026-10-20" and re.search(r"(无相关业务|未开展.*业务|占比极小|不存在.*业务)", t) for d, t in nlist))
        ir_90 = sum(1 for d, t in nlist if d >= "2026-08-15" and "投资者关系活动" in t)
        is_soe = int(bool(re.search(r"(中国|中航|航天|国|省|市|上海|北京|深圳|福建|平潭|四川|重庆|厦门|南京|广东|能建|电建|中化)", nm)))

        # Community posts
        p3 = cm_conn.execute("SELECT count(*) FROM community_posts WHERE symbol=? AND pub_datetime_cst >= '2026-11-11'", (c6,)).fetchone()[0]
        p30 = cm_conn.execute("SELECT count(*) FROM community_posts WHERE symbol=? AND pub_datetime_cst >= '2026-10-01' AND pub_datetime_cst < '2026-10-25'", (c6,)).fetchone()[0]
        stealth = int(p30 <= 8)

        # Policy burst matching main_p
        p_kw = main_p.replace("概念", "")[:2]
        pol_min = sum(1 for tx in fn_txts if p_kw in tx and pol_min_re.search(tx))
        pol_geo = sum(1 for tx in fn_txts if p_kw in tx and pol_geo_re.search(tx))

        in_top1 = int(main_p == top1_p)
        in_top2 = int(main_p in top2_ps)
        has_mid = int(main_p in plate_has_mid)
        name_match = int(p_kw in nm or bool(re.search(r"(智能|科技|机器人|航天|通信|光电|新材|发展|机电|传动|轴承)", nm)))
        csrc_ind = csrc_map.get(c6, "")
        outsider = int(main_p in ("芯片", "机器人概念", "人工智能", "算力") and bool(re.search(r"(农|牧|渔|纺织|服装|食品|家具|陶瓷|造纸|零售|餐饮|房地产)", csrc_ind)))

        # Compute exact V4.0 score
        sc = 50.0
        sc += min(max(tight_hr * 40.0, 0.0), 20.0)
        sc += 15.0 if is_detour else 0.0
        sc += 5.0 if r["pct"] > 0 else 0.0
        sc += min(pol_min * 3.0, 15.0)
        sc += min(pol_geo * 2.5, 10.0)
        sc += 12.0 if in_top1 else (6.0 if in_top2 else (3.0 if main_p in top4_ps else 0.0))
        sc += 8.0 if has_mid else 0.0
        sc += 5.0  # Q4 active mainline
        sc += 8.0 * has_contract + 6.0 * has_coop + 6.0 * has_newsub + 5.0 * q3_up + 8.0 * q3_turn + 5.0 * is_soe
        sc += 8.0 * stealth + (5.0 if ir_90 == 0 else 0.0) + (5.0 if r["close"] <= 15.0 else 0.0) + 5.0 * name_match
        sc -= 30.0 if tight_hr < 0.05 else 0.0
        sc -= 20.0 * has_reg + 15.0 * has_red + (15.0 if p3 >= 20 else 0.0) + 10.0 * q3_loss + 8.0 * outsider + 15.0 * has_clarify_deny
        if r["zt_streak"] >= 4: sc -= 15.0

        h_recs = [x for x in holders.get(c6, []) if isinstance(x, (list, tuple)) and len(x) > 2]
        lock = float(max(h_recs, key=lambda x: str(x[1]))[2]) if h_recs else 38.0

        results.append({
            "c6": c6, "name": nm, "theme": main_p, "close": round(float(r["close"]), 2),
            "pct_td": round(float(r["pct"]) * 100, 2), "mcap": round(float(r["mcap"]), 1),
            "amt_yi": round(float(r["amt_yi"]), 2), "lock": round(lock, 1),
            "oct_zts": oct_hs_zts.get(c6, 0), "streak": int(r["zt_streak"]),
            "dev10": round(dev10 * 100, 1), "hr10": round(hr10 * 100, 1),
            "dev30": round(dev30 * 100, 1), "hr30": round(hr30 * 100, 1),
            "detour": is_detour, "pol_min": pol_min, "has_mid": has_mid,
            "q3": "扭亏" if q3_turn else ("预增" if q3_up else ("预亏" if q3_loss else "常规")),
            "cat": f"合同{has_contract}/合资{has_newsub}/国资{is_soe}/调研{ir_90}",
            "pen": f"函{has_reg}/减{has_red}/热{p3}/外{outsider}",
            "v4_score": round(sc, 1)
        })
    cm_conn.close()

    res_df = pd.DataFrame(results).sort_values("v4_score", ascending=False)
    res_df.to_csv(f"{SIM}/backtests_astock2/rd011_v4_100factors_20261116/live_2026_11_16_candidates.csv", index=False, encoding="utf-8-sig")
    print("\n=== [A] 2026/27 跨年大票容量池 (45亿~350亿) Top 15 (截至 2026-11-16 收盘) ===")
    big_df = res_df[res_df["mcap"].between(45.0, 350.0)].head(15)
    print(big_df.to_string(index=False))
    print("\n=== [B] 20亿~45亿 小盘先锋对照池 Top 8 ===")
    sm_df = res_df[res_df["mcap"].between(20.0, 44.99)].head(8)
    print(sm_df.to_string(index=False))

if __name__ == "__main__":
    main()
