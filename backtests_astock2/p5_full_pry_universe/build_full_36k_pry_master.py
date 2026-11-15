#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Build Full 5Y (2022-2026) 36,000+ Limit-Down Touch & Pry Master Dataset with 140+ PIT Columns."""
import os, sys, re, json, time, bisect, sqlite3, datetime
from collections import defaultdict
import numpy as np
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
GFM_DIR = f"{BASE}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{BASE}/backtests_astock2/p5_full_pry_universe"
os.makedirs(OUT_DIR, exist_ok=True)
if GFM_DIR not in sys.path:
    sys.path.insert(0, GFM_DIR)

from part2a_daily_and_env import build_daily_panel_and_env
from part2b_build_env_and_bars import pit_lock_lookup
from pit_aux_loaders import load_aux_pit_sources


def load_full_lhb_seats():
    bp = f"{BASE}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
    sp = f"{BASE}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
    seat_map = defaultdict(lambda: [0.0, 0.0, 0.0, 0, 0, 0, 0.0])
    # [inst_buy, inst_sell, north_net, youzi_cnt, quant_cnt, lhasa_cnt, lhasa_sh]
    youzi_re = re.compile(r"(?:章建平|国泰君安.*江苏路|中信.*东阳|中信.*西安朱雀|华泰.*总部|国盛.*慈溪|中国银河.*大连金马路|联储.*宁波|六一中路|呼家楼|中信建投.*北京朝外|陈小群|东亚前海.*苏州留园)")
    quant_re = re.compile(r"(?:华鑫.*上海分公司|中金.*上海分公司|东亚前海.*上海分公司|瑞银证券.*上海花园石桥)")
    if os.path.exists(bp):
        b = pd.read_parquet(bp, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"])
        b["dt"] = b["TRADE_DATE"].astype(str).str[:10]
        b = b[b["dt"] >= "2021-10-01"].copy()
        b["c6"] = b["SECURITY_CODE"].astype(str).str[:6]
        nm = b["OPERATEDEPT_NAME"].astype(str)
        b["ib"] = np.where(nm.str.contains("机构专用", na=False), b["BUY"].fillna(0), 0.0)
        b["nb"] = np.where(nm.str.contains("股通专用", na=False), b["BUY"].fillna(0) - b["SELL"].fillna(0), 0.0)
        b["yz"] = nm.str.contains(youzi_re, na=False).astype(int)
        b["qt"] = nm.str.contains(quant_re, na=False).astype(int)
        b["lh"] = nm.str.contains("拉萨", na=False).astype(int)
        b["lhb_amt"] = np.where(b["lh"] == 1, b["BUY"].fillna(0), 0.0)
        g = b.groupby(["dt", "c6"], as_index=False).agg(
            ib=("ib", "sum"), nb=("nb", "sum"), yz=("yz", "sum"), qt=("qt", "sum"),
            lh=("lh", "sum"), lhb_amt=("lhb_amt", "sum"), tot_b=("BUY", "sum")
        )
        for r in g.itertuples(index=False):
            sh = float(r.lhb_amt / r.tot_b) if r.tot_b and r.tot_b > 0 else 0.0
            seat_map[(r.dt, r.c6)] = [float(r.ib)/1e4, 0.0, float(r.nb)/1e4, int(r.yz), int(r.qt), int(r.lh), round(sh, 4)]
    if os.path.exists(sp):
        s = pd.read_parquet(sp, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
        s["dt"] = s["TRADE_DATE"].astype(str).str[:10]
        s = s[(s["dt"] >= "2021-10-01") & s["OPERATEDEPT_NAME"].astype(str).str.contains("机构专用", na=False)]
        s["c6"] = s["SECURITY_CODE"].astype(str).str[:6]
        gs = s.groupby(["dt", "c6"], as_index=False)["SELL"].sum()
        for r in gs.itertuples(index=False):
            seat_map[(r.dt, r.c6)][1] = float(r.SELL) / 1e4
    return seat_map


def load_fine_notices(target_codes):
    out = defaultdict(list)
    conn = sqlite3.connect(f"file:{BASE}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    re_inv = re.compile(r"立案|调查|违法|违规|处罚|留置|逮捕|刑拘")
    re_del = re.compile(r"退市|终止上市|风险警示|\*ST|被实施")
    re_los = re.compile(r"预亏|亏损|大幅下降|下修|计提.*减值|逾期|违约|冻结|诉讼")
    re_red = re.compile(r"减持|清仓|平仓|被动减持")
    re_buy = re.compile(r"回购|增持|不减持")
    re_win = re.compile(r"预增|扭亏|大幅增长|中标|重大合同|重组|收购|控制权变更")
    for sc, pdt, adt, title in conn.execute("SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2021-09-01'"):
        c6 = str(sc)[:6].zfill(6)
        if c6 not in target_codes or not pdt:
            continue
        t = str(title or "")
        fl = (bool(re_inv.search(t)), bool(re_del.search(t)), bool(re_los.search(t)), bool(re_red.search(t)), bool(re_buy.search(t)), bool(re_win.search(t)))
        if any(fl):
            out[c6].append((str(pdt), str(adt or ""), fl))
    conn.close()
    for c6 in out:
        out[c6].sort(key=lambda x: x[0])
    return out


def main():
    t0 = time.time()
    df, _, _ = build_daily_panel_and_env()
    g = df.groupby("c6")
    s_yzdt = df["is_yizi_dt"].astype(int)
    df["yizi_dt_streak"] = s_yzdt.groupby([df["c6"], (s_yzdt != g["is_yizi_dt"].shift().fillna(False)).cumsum()]).cumsum() * s_yzdt
    df["ma5"] = g["close"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    df["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=20).mean())
    df["ret3"] = df["close"] / (g["close"].shift(3) + 1e-6) - 1.0
    df["ret60"] = df["close"] / (g["close"].shift(60) + 1e-6) - 1.0
    df["zt_cnt5"] = g["is_zt"].transform(lambda s: s.astype(int).rolling(5, min_periods=2).sum())
    df["zt_cnt60"] = g["is_zt"].transform(lambda s: s.astype(int).rolling(60, min_periods=10).sum())
    df["dt_cnt20"] = g["is_dt"].transform(lambda s: s.astype(int).rolling(20, min_periods=5).sum())
    df["up_d10"] = g["pct"].transform(lambda s: (s > 0).astype(int).rolling(10, min_periods=5).sum())
    df["vol20"] = g["pct"].transform(lambda s: s.rolling(20, min_periods=10).std())
    df["cum_to3"] = g["to"].transform(lambda s: s.rolling(3, min_periods=1).sum())

    sub = df[df["dt_str"] >= "2021-11-01"].copy()
    gs = sub.groupby("c6")
    for col, src in [
        ("sig_date", "dt_str"), ("prev_streak", "streak"), ("prev_dt_streak", "dt_streak"),
        ("prev_yizi_dt_streak", "yizi_dt_streak"), ("prev_mcap", "mcap"), ("prev_to", "to"),
        ("prev_amt", "amount"), ("prev_ret3", "ret3"), ("prev_ret5", "ret5"), ("prev_ret10", "ret10"),
        ("prev_ret20", "ret20"), ("prev_ret60", "ret60"), ("prev_zt5", "zt_cnt5"), ("prev_zt20", "zt_cnt20"),
        ("prev_zt60", "zt_cnt60"), ("prev_dt20", "dt_cnt20"), ("prev_up10", "up_d10"), ("prev_vol20", "vol20"),
        ("prev_cum_to3", "cum_to3"), ("prev_mb_gap", "prior_mb_gap"), ("prev_touch_dt", "touch_dt"),
        ("prev_is_dt", "is_dt"), ("prev_pct", "pct"), ("prev_o_pct", "o_pct"), ("prev_l_pct", "l_pct"),
    ]:
        sub[col] = gs[src].shift(1)
    sub["prev_dd20"] = (gs["close"].shift(1) / (gs["max20"].shift(1) + 1e-6)).fillna(0.9)
    sub["prev_dd60"] = (gs["close"].shift(1) / (gs["max60"].shift(1) + 1e-6)).fillna(0.85)
    sub["prev_pos20"] = ((gs["close"].shift(1) - gs["min20"].shift(1)) / (gs["max20"].shift(1) - gs["min20"].shift(1) + 1e-6)).fillna(0.5)
    sub["prev_c_ma5"] = (gs["close"].shift(1) / (gs["ma5"].shift(1) + 1e-6) - 1.0).fillna(0.0)
    sub["prev_c_ma20"] = (gs["close"].shift(1) / (gs["ma20"].shift(1) + 1e-6) - 1.0).fillna(0.0)
    sub["prev_c_ma60"] = (gs["close"].shift(1) / (gs["ma60"].shift(1) + 1e-6) - 1.0).fillna(0.0)
    sub["prev_ma20_up"] = (gs["ma20"].shift(1) > gs["ma20"].shift(6)).fillna(False)
    sub["prev_vr"] = (gs["amount"].shift(1) / (gs["vol_ma5"].shift(1) + 1e-6)).fillna(1.0)
    sub["day0_vr"] = (sub["amount"] / (sub["vol_ma5"] + 1e-6)).fillna(1.0)

    # Compute 09:25 Real-Time Auction Market Sensors & 14:57 Same-Day Market Sensors across ALL stocks!
    sub["open_is_dt"] = (sub["open"] <= sub["dt_price"] + 0.011) & (sub["pre_c"] > 0)
    sub["open_is_zt"] = (sub["open"] >= sub["zt_price"] - 0.011) & (sub["pre_c"] > 0)
    sub["pry_unsealed"] = sub["touch_dt"] & (~sub["is_dt"])
    d_agg = sub.groupby("dt_str", as_index=False).agg(
        mkt_open_dt_0925=("open_is_dt", "sum"),
        mkt_open_lt5_0925=("o_pct", lambda s: int((s <= -0.05).sum())),
        mkt_open_avg_0925=("o_pct", "mean"),
        mkt_open_zt_0925=("open_is_zt", "sum"),
        TAIL1457_mkt_dt_today=("is_dt", "sum"),
        TAIL1457_mkt_touch_dt_today=("touch_dt", "sum"),
        TAIL1457_mkt_pry_cnt_today=("pry_unsealed", "sum"),
        TAIL1457_mkt_zt_today=("is_zt", "sum"),
    )
    d_agg["TAIL1457_mkt_pry_rate_today"] = d_agg["TAIL1457_mkt_pry_cnt_today"] / d_agg["TAIL1457_mkt_touch_dt_today"].clip(lower=1)
    rt_env_map = d_agg.set_index("dt_str").to_dict(orient="index")

    # Save stage1 intermediate and call part2 enricher
    w5 = sub[(sub["dt_str"] >= "2022-01-04") & (sub["dt_str"] <= "2026-11-10") & (sub["pre_c"] >= 2.0) & sub["sig_date"].notna()].copy()
    # Keep ALL Day-0 touch_dt OR prev_dt_streak>=1 OR yesterday pry relay (prev_touch_dt & ~prev_is_dt)
    cand = w5[w5["touch_dt"] | (w5["prev_dt_streak"] >= 1) | (w5["prev_touch_dt"].fillna(False) & (~w5["prev_is_dt"].fillna(True)))].copy()
    cand.to_parquet(f"{OUT_DIR}/stage1_cand_raw.parquet", index=False)
    with open(f"{OUT_DIR}/rt_env_map.json", "w") as f:
        json.dump(rt_env_map, f)
    print(f"[+] Stage 1 ready: {len(cand):,} candidate rows (touch_dt={int(cand['touch_dt'].sum()):,}) in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
