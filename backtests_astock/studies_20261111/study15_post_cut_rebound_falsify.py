#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
study15_post_cut_rebound_falsify.py
================================================================================
专项回测 15：止损单后续反包打板初筛证伪回测
核心结论：
- 纠正收盘涨停幸存者偏差，盘中摸板打板100%计入炸板分母；
- 止损单后续触板买回13笔胜率46.2%笔均赚0.80%，全市场洗盘一两天触板811笔胜率36.4%笔均亏0.34%；
- 二波首板加8至12分挤仓使单仓复利净值从124.43倍暴跌至76.15至90.76倍；
- 判定：全面淘汰，严禁引入回马枪或二波首板机制。
================================================================================
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/tmp")
import fg_check_v15_base as vb

hist_fb = vb.hist_fb
all_dts = vb.all_dts
dt_to_idx = vb.dt_to_idx
price_lookup = vb.price_lookup
bars_5m_map = vb.bars_5m_map

# Static premarket score (known BEFORE D2 09:15!) & purifier_ok
seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
open_cnt = hist_fb["open_board_count"].fillna(0)
dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
clean_brk60 = hist_fb["clean_brk60"].values == 1
is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)
d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)

# Reconstruct static score (prior + static quant base)
# Note: s_quant_dual includes auction score; f_dd20/clean_brk60/mcap/tightness are static, or use s_prior_wk + static_q
static_purifier = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2))) & (~hist_fb["is_dying_pulse"]) & (~hist_fb["notice_bad"]) & (hist_fb["d1_seal_tightness"] >= 37.0) & (hist_fb["s_prior_wk"] >= 55.0)

# Simulate holding & exit from entry day `idx_buy` at `buy_px` using exact V15 5m 10:30 VWAP rules!
def sim_from_entry(c6, name, idx_buy, buy_px, fee=vb.FEE_RATE):
    if idx_buy < 0 or idx_buy >= len(all_dts) - 1: return None
    d_buy = all_dts[idx_buy]
    b_buy = price_lookup.get((c6, d_buy))
    if not b_buy: return None
    ob, hb, lb, cb, ztb, dtb, is_ztb, is_yz_dtb = b_buy
    prev_c = round(float(cb), 2)
    idx_next = idx_buy + 1
    b_next = price_lookup.get((c6, all_dts[idx_next]))
    if not b_next:
        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[idx_next], "exit_at_open": True, "sealed_buy": int(is_ztb), "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": prev_c}
    on, hn, ln, cn, ztn, dtn, is_ztn, is_yz_dtn = b_next

    # If entry day failed to close at limit-up (including摸板炸板!): next morning cut unless closed up & opens >=+0.5%
    if not is_ztb:
        curr = idx_next
        while curr < len(all_dts):
            b = price_lookup.get((c6, all_dts[curr]))
            if not b or not b[7]:
                px = round(float(b[0]), 2) if b else prev_c
                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_buy": 0, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
            curr += 1
        return None

    # Entry day sealed ZT! Ride multi-boards with exact 10:30 5m VWAP rule
    curr, boards_held, used_imm = idx_next, 2, False
    while curr < len(all_dts) and (curr - idx_buy <= 12):
        dc = all_dts[curr]
        b = price_lookup.get((c6, dc))
        if not b: break
        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b
        if iyzc: prev_c = round(float(cc), 2); curr += 1; continue
        arr = bars_5m_map.get((c6, dc))
        if arr is not None and len(arr) >= 12:
            idx_1030, cum_v, cum_a = -1, 0.0, 0.0
            for bi in range(len(arr)):
                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                if arr[bi, 0] == 1030: idx_1030 = bi; break
            if idx_1030 >= 0:
                bc_1030 = arr[idx_1030, 4]
                vwap = cum_a / cum_v if cum_v > 0 else bc_1030
                if bc_1030 >= ztc - 0.01:
                    for bi in range(idx_1030 + 1, len(arr) - 1):
                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                            px = round(float(arr[bi + 1, 1]), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": 1, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
                    if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    px = round(float(cc), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": 1, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
                elif bc_1030 < vwap:
                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": 1, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
                else:
                    if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                    if boards_held >= 3 and (not used_imm) and cc >= prev_c * 1.02 and (curr + 1 < len(all_dts)):
                        used_imm = True; prev_c = round(float(cc), 2); curr += 1; continue
                    px = round(float(cc), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": 1, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
        if iztc: prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
        px = round(float(cc), 2)
        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_buy": 1, "buy_date": d_buy, "c6": c6, "name": name, "buy_price": buy_px, "exit_price": px}
    return None

# Collect ALL 2022-2026 D3 (1-day rest) & D4 (2-day rest, like 东方海洋!) washout candidates from purified first boards!
df5y = hist_fb[(hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-05") & static_purifier].copy().reset_index(drop=True)
v15_traded_keys = {(t["c6"], t["buy_date"]) for t in vb.res_base["trades_list"]}

recs = []
for _, r in df5y.iterrows():
    c6, nm, d1_c, d2 = r["c6"], r["name"], float(r["close"]), r["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0 or idx2 + 3 >= len(all_dts): continue
    b2 = price_lookup.get((c6, d2))
    if not b2 or b2[6]: continue  # Only stocks that did NOT seal 2B on D2 ("断板或未板休息")!
    o2, h2, l2, c2, zt2, _, _, _ = b2
    was_v15_cut = (c6, d2) in v15_traded_keys
    s_prior = float(r["s_prior_wk"])
    s_tot_d2 = float(r["score_active"])

    # Check both k=1 (D3反包, rest 1 day) and k=2 (D4反包, rest 2 days like 东方海洋!)
    for rest_days in (1, 2):
        idx_e = idx2 + rest_days
        d_e = all_dts[idx_e]
        be = price_lookup.get((c6, d_e))
        if not be: continue
        oe, he, le, ce, zte, dte, izte, _ = be
        if oe <= 0 or oe >= zte - 0.005: continue  # exclude unbuyable yizi open!

        # Washout health check over rest period (strictly BEFORE d_e opens!):
        if rest_days == 1:
            wash_min_c = c2
            wash_max_h = h2
            prev_close = c2
            rest_no_zt = True
        else:
            b3 = price_lookup.get((c6, all_dts[idx2 + 1]))
            if not b3 or b3[6]: continue  # if D3 already ZT, it's not a 2-day washout!
            wash_min_c = min(c2, b3[3])
            wash_max_h = max(h2, b3[1])
            prev_close = b3[3]

        hold_above_d1c = wash_min_c >= d1_c * 0.995      # 洗盘收盘始终站稳首板收盘价 (强承接空中加油, 如东方海洋!)
        hold_above_96 = wash_min_c >= d1_c * 0.96        # 洗盘未跌破首板收盘-4%
        oe_pct = oe / prev_close - 1.0

        # Entry Trigger Type 1: Touch Limit-Up Hit-Board ("盘中触及涨停打反包板", 100% counting摸板炸板!)
        if he >= zte - 0.005 and 0.0 <= oe_pct <= 0.075:
            tr_zt = sim_from_entry(c6, nm, idx_e, zte)
            if tr_zt:
                recs.append({"rest": rest_days, "mode": "打反包涨停板(含炸板)", "was_v15": was_v15_cut, "s_prior": s_prior, "s_d2": s_tot_d2, "above_d1": hold_above_d1c, "above_96": hold_above_96, "oe_pct": oe_pct, **tr_zt})

        # Entry Trigger Type 2: Breakout washout high AND >= +6.5% ignition (< zt_p)
        trig_brk = round(max(wash_max_h + 0.01, prev_close * 1.065, oe * 1.012), 2)
        if 0.005 <= oe_pct <= 0.070 and trig_brk < zte - 0.005 and he >= trig_brk:
            tr_brk = sim_from_entry(c6, nm, idx_e, trig_brk)
            if tr_brk:
                recs.append({"rest": rest_days, "mode": "突破洗盘高点+6.5%点火", "was_v15": was_v15_cut, "s_prior": s_prior, "s_d2": s_tot_d2, "above_d1": hold_above_d1c, "above_96": hold_above_96, "oe_pct": oe_pct, **tr_brk})

rdf = pd.DataFrame(recs)
print(f"总反包候选触发记录: {len(rdf)}")
for md in ["打反包涨停板(含炸板)", "突破洗盘高点+6.5%点火"]:
    print(f"\n================ 买点模式: {md} ================")
    for label, mask in [
        ("A. 全部纯洁首板洗1~2天反包", rdf["mode"] == md),
        ("B. 洗盘收盘始终站稳首板收盘价 (above_d1)", (rdf["mode"] == md) & rdf["above_d1"]),
        ("C. 站稳首板收盘价 + 强主线题材(s_prior>=110)", (rdf["mode"] == md) & rdf["above_d1"] & (rdf["s_prior"] >= 110)),
        ("D. 站稳首板收盘价 + 原D2评分>=275 (高分漏买+止损池)", (rdf["mode"] == md) & rdf["above_d1"] & (rdf["s_d2"] >= 275)),
        ("E. 仅原V15买过止损的46笔回马枪 (was_v15)", (rdf["mode"] == md) & rdf["was_v15"]),
        ("F. 仅洗2天(D4东方海洋式) + 站稳首板收盘 + s_prior>=100", (rdf["mode"] == md) & (rdf["rest"] == 2) & rdf["above_d1"] & (rdf["s_prior"] >= 100)),
    ]:
        s = rdf[mask]
        if len(s) == 0: continue
        wr = (s["net_ret"] > 0).mean() * 100
        avg = s["net_ret"].mean() * 100
        seal_r = s["sealed_buy"].mean() * 100
        w_avg = s.loc[s["net_ret"] > 0, "net_ret"].mean()
        l_avg = abs(s.loc[s["net_ret"] <= 0, "net_ret"].mean()) if (s["net_ret"] <= 0).any() else 0.01
        pay = w_avg / l_avg if l_avg > 0 else 99
        print(f"  {label:<48s} | N={len(s):4d} | 当日封住率={seal_r:5.1f}% | 胜率={wr:5.1f}% | 盈亏比={pay:4.2f} | 均盈亏={avg:+6.2f}%")
