#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""三进四不稳定因子拆细：每个因子拆成多个子条件，只留双期同向且逐年留一5年全同向的子条件"""
import numpy as np, pandas as pd
import bt_3to4_expand_soft_skeleton as B

d = B.d.copy()
d["ret"] = [x["net_ret"] if x is not None else np.nan for x in B.p_v32]
d["yr"] = d.buy_date.str[:4].astype(int)
fst = pd.to_numeric(d.first_seal_time.astype(str).str.replace(":", "").str[:4], errors="coerce").fillna(9999)
pool = d[B.core & B.obc & B.op_ok & d.ret.notna()].copy()
fst = fst.loc[pool.index]
print(f"候选区底池（三项改扣分后的骨架）n={len(pool)} 笔均={pool.ret.mean()*100:+.2f}%")

def test(nm, m):
    m = m.fillna(False).astype(bool)
    if m.sum() < 10 or (~m).sum() < 10: return None
    dd = pool.ret[m].mean() - pool.ret[~m].mean()
    e, l = pool.yr < 2024, pool.yr >= 2024
    de = pool.ret[m & e].mean() - pool.ret[~m & e].mean()
    dl = pool.ret[m & l].mean() - pool.ret[~m & l].mean()
    lo = sum(int(np.sign(pool.ret[m & (pool.yr != y)].mean() - pool.ret[~m & (pool.yr != y)].mean()) == np.sign(dd)) for y in range(2022, 2027))
    ok = lo == 5 and np.sign(de) == np.sign(dl) == np.sign(dd) and abs(dd) >= 0.015 and m.sum() >= 10
    return (("入选" if ok else "    "), nm, int(m.sum()), (pool.ret[m] > 0).mean() * 100, dd * 100, de * 100, dl * 100, lo)

lsh, lcnt = pool.lhasa_buy_share_prev.fillna(0), pool.lhb_lh_cnt.fillna(0)
groups = {
    "拉萨买额占比": [("占比满10%", lsh >= 0.10), ("占比满20%", lsh >= 0.20), ("占比满30%", lsh >= 0.30),
                ("占比10%至20%", lsh.between(0.10, 0.20)), ("占比满20%且拉萨满2家", (lsh >= 0.20) & (lcnt >= 2)),
                ("占比满20%但仅1家", (lsh >= 0.20) & (lcnt == 1))],
    "首封时间": [("09:35前秒封且没开板", (fst <= 935) & (pool.open_board_count == 0)),
             ("09:35前秒封后开板回封", (fst <= 935) & (pool.open_board_count >= 1)),
             ("09:35至10:00封", fst.between(936, 1000)), ("10:00至10:30封", fst.between(1001, 1030)),
             ("10:30至14:00封", fst.between(1031, 1359)), ("14:00后尾盘封", fst >= 1400),
             ("开板满3次", pool.open_board_count >= 3)],
    "外行蹭科技": [("外行且无硬公告", pool.is_pure_outsider.astype(bool) & ~pool.notice_hard.astype(bool)),
              ("外行且题材热度满115", pool.is_pure_outsider.astype(bool) & (pool.p_elo >= 115)),
              ("外行且题材热度不足115", pool.is_pure_outsider.astype(bool) & (pool.p_elo < 115))],
    "公告": [("并购重组且换手超20%", pool.notice_ma.astype(bool) & (pool.prev_to > 20)),
           ("并购重组且换手不超20%", pool.notice_ma.astype(bool) & (pool.prev_to <= 20)),
           ("业绩公告且股价不超20元", pool.notice_earn.astype(bool) & (pool.px_d3 <= 20)),
           ("硬公告", pool.notice_hard.astype(bool))],
    "题材格局": [("断层主线日且是主线票", pool.is_dominant_day.astype(bool) & (pool.rk_theme == 1)),
             ("断层主线日但非主线票", pool.is_dominant_day.astype(bool) & (pool.rk_theme > 1)),
             ("混战日", pool.is_melee_day.astype(bool)), ("题材排名第1", pool.rk_theme == 1),
             ("同题材有321梯队", pool.has_321_plate.astype(bool)), ("三板竞争对手满3只", pool.b3_rival_cnt >= 3),
             ("三板竞争对手为0", pool.b3_rival_cnt == 0)],
    "周期温度": [("近20日三进四核按钮率满20%", pool.prev_3to4_nuke_rate_20d >= 0.20),
             ("近20日三进四核按钮率满40%", pool.prev_3to4_nuke_rate_20d >= 0.40),
             ("近5日一进二晋级率不足13%", pool.mkt_promo_1to2_5d < 0.13),
             ("近5日一进二晋级率满25%", pool.mkt_promo_1to2_5d >= 0.25),
             ("近20日高开封板率不足40%", pool.roll20_ho_zt < 0.40), ("近20日高开封板率满55%", pool.roll20_ho_zt >= 0.55),
             ("昨日封板率满75%", pool.mkt_seal_rate_prev >= 0.75), ("昨日首板今开均值为负", pool.mkt_fb_open_avg < 0)],
    "席位": [("机构上榜且零拉萨", (pool.lhb_inst_cnt >= 1) & (lcnt == 0)), ("机构上榜且有拉萨", (pool.lhb_inst_cnt >= 1) & (lcnt >= 1)),
           ("量化上榜且零拉萨", (pool.lhb_quant_cnt >= 1) & (lcnt == 0)), ("量化上榜且有拉萨", (pool.lhb_quant_cnt >= 1) & (lcnt >= 1))],
    "位置": [("60日平台首突", pool.clean_brk60.astype(bool)), ("前10日涨幅超50%", pool.ret_pre10 > 0.5),
           ("20日回撤超30%", pool.dd20 < -0.30), ("距百日高点空间满18%", pool.headroom_100 >= 0.18)],
}
for g, items in groups.items():
    print(f"--- {g} ---")
    for nm, m in items:
        r = test(nm, m)
        if r: print(f"{r[0]} {r[1]:24s} n={r[2]:3d} WR={r[3]:4.1f}% 差={r[4]:+6.2f}% | 22至23差={r[5]:+6.2f}% 24至26差={r[6]:+6.2f}% | 留一{r[7]}/5")
