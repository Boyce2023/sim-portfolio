#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四扩笔数第一步：在放宽后的大底池里，逐个检验未入模因子的双期同向与逐年留一稳定性"""
import numpy as np, pandas as pd
from verify_v33_calendar_upgrade import df, p_v32

df["ret"] = [x["net_ret"] if x is not None else np.nan for x in p_v32]
df["yr"] = df["buy_date"].str[:4].astype(int)
fst = df["first_seal_time"].astype(str).str.replace(":", "").str[:4]
df["fst"] = pd.to_numeric(fst, errors="coerce").fillna(9999)

wide = (df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"]
        & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
        & df["open_pct"].between(0.0, 0.095) & df["ret"].notna())
pool = df[wide].copy()
print(f"放宽大底池 n={len(pool)}，WR={(pool.ret>0).mean()*100:.1f}%，笔均={pool.ret.mean()*100:+.2f}%")

F = {
    "骨架_同日竞价头名": pool.is_top1_3b_open.astype(bool),
    "骨架_三板开板>=1": pool.open_board_count >= 1,
    "骨架_锁仓或容量达标": (pool.lock_top10 >= 45) | (pool.real_free_mcap >= 45),
    "骨架_换手8.5至31": pool.prev_to.between(8.5, 31),
    "骨架_高开3至9.2": pool.open_pct.between(0.03, 0.092),
    "高开2至3": pool.open_pct.between(0.02, 0.03),
    "10点30前换手回封": pool.is_hard_open_1030.astype(bool),
    "9点35前秒封": pool.fst <= 935,
    "14点后尾盘封板": pool.fst >= 1400,
    "硬公告催化": pool.notice_hard.astype(bool),
    "并购重组公告": pool.notice_ma.astype(bool),
    "业绩公告": pool.notice_earn.astype(bool),
    "拉萨买额占比满20%": pool.lhasa_buy_share_prev >= 0.20,
    "外行蹭硬科技": pool.is_pure_outsider.astype(bool),
    "事件大筐假抱团": pool.is_event_basket.astype(bool),
    "退潮脉冲": pool.is_dying_pulse.astype(bool),
    "断层主线日": pool.is_dominant_day.astype(bool),
    "题材混战日": pool.is_melee_day.astype(bool),
    "同题材有321梯队": pool.has_321_plate.astype(bool),
    "行业涨停满3家": pool.csrc_zt_cnt >= 3,
    "近20日三进四核按钮率>=30%": pool.prev_3to4_nuke_rate_20d >= 0.30,
    "近10日断板跌停率>=20%": pool.prev_break_dt_rate_10d >= 0.20,
    "近20日高开封板率<45%": pool.roll20_ho_zt < 0.45,
    "近5日一进二晋级率<13%": pool.mkt_promo_1to2_5d < 0.13,
    "机构席位上榜": pool.lhb_inst_cnt >= 1,
    "量化席位上榜": pool.lhb_quant_cnt >= 1,
    "60日平台首突": pool.clean_brk60.astype(bool),
    "近8日机构调研": pool.has_ir_8d.astype(bool),
    "竞争对手三板满2只": pool.b3_rival_cnt >= 2,
}
rows = []
for nm, m in F.items():
    m = m.fillna(False).astype(bool)
    if m.sum() < 8 or (~m).sum() < 8: continue
    d = pool.ret[m].mean() - pool.ret[~m].mean()
    e = pool[pool.yr < 2024]; l = pool[pool.yr >= 2024]
    me, ml = m.loc[e.index], m.loc[l.index]
    de = e.ret[me].mean() - e.ret[~me].mean() if me.sum() and (~me).sum() else np.nan
    dl = l.ret[ml].mean() - l.ret[~ml].mean() if ml.sum() and (~ml).sum() else np.nan
    lo = sum(int(np.sign(pool[pool.yr != y].ret[m[pool.yr != y]].mean() - pool[pool.yr != y].ret[~m[pool.yr != y]].mean()) == np.sign(d)) for y in range(2022, 2027))
    rows.append((nm, int(m.sum()), (pool.ret[m] > 0).mean() * 100, pool.ret[m].mean() * 100, d * 100, de * 100, dl * 100, lo))
for r in sorted(rows, key=lambda x: -abs(x[4])):
    ok = "稳" if (r[7] == 5 and np.sign(r[5]) == np.sign(r[6])) else "  "
    print(f"{ok} {r[0]:22s} n={r[1]:4d} WR={r[2]:4.1f}% 均={r[3]:+6.2f}% 差={r[4]:+6.2f}% | 22至23差={r[5]:+6.2f}% 24至26差={r[6]:+6.2f}% | 留一={r[7]}/5")
