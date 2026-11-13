# -*- coding: utf-8 -*-
"""
v16_trade_matcher.py: 5分钟 10:30 分时均线四分支撮合引擎与大白话复盘生成器
"""
def make_v16_trade_engine(price_lookup, all_dts, dt_to_idx, bars_5m_map, fee=0.0020):
    def sim_trade(row):
        if hasattr(row, "_asdict"):
            row = row._asdict()
        elif hasattr(row, "to_dict"):
            row = row.to_dict()
        c6, d2 = row["c6"], row["d2_dt"]
        idx2 = dt_to_idx.get(d2, -1)
        if idx2 < 0 or idx2 >= len(all_dts) - 1:
            return None
        d2_bar = price_lookup.get((c6, d2))
        if not d2_bar:
            return None
        o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar[:8]
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return None

        is_monday = row.get("gap_days", 1) >= 3
        cand_score = row.get("score_active", row.get("score_0", 0.0))
        cand_lead = row.get("buy_open_lead", 0.0)
        do_direct = is_monday and (cand_score >= 310.0) and (cand_lead >= 0.025)
        trig_p = float(row["trig_p"])
        buy_px = round(float(o2), 2) if do_direct else round(trig_p, 2)
        if not do_direct:
            if h2 < trig_p or trig_p >= zt2 - 0.005:
                return None
            # 2026-11-13 定版铁律：上午 11:30 前未触及点火价则午休撤单不买（过滤下午盘偷袭诱多）
            arr2 = bars_5m_map.get((c6, d2))
            if arr2 is not None and len(arr2) > 0:
                ign_hhmm = None
                am_high = float(o2)
                for bi in range(len(arr2)):
                    if int(arr2[bi, 0]) <= 1130 and float(arr2[bi, 2]) > am_high:
                        am_high = float(arr2[bi, 2])
                    if ign_hhmm is None and float(arr2[bi, 2]) >= trig_p - 1e-4:
                        ign_hhmm = int(arr2[bi, 0])
                if ign_hhmm is not None and ign_hhmm > 1130:
                    return {"executed": False, "tag": "pm_cancel_1130", "am_high": round(am_high, 2)}

        prev_c = round(float(c2), 2)
        idx3 = idx2 + 1
        d3 = all_dts[idx3]
        d3_bar = price_lookup.get((c6, d3))
        if not d3_bar:
            net = round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4)
            return {"net_ret": net, "exit_date": d3, "exit_at_open": True, "sealed_2b": int(is_zt2), "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c, "tag": "fail_open_cut", "final_height": 1}

        o3, h3, l3, c3, zt3, dt3, is_zt3, is_yz_dt3 = d3_bar[:8]
        if not is_zt2:
            d2_closed_up = (c2 >= float(row["close"]))
            if d2_closed_up and (o3 >= round(c2 * 1.005, 2)) and not is_yz_dt3:
                if is_zt3:
                    curr = idx3 + 1
                    boards_held = 3
                    used_immunity = False
                    prev_c = round(float(c3), 2)
                    while curr < len(all_dts) and (curr - idx2 <= 12):
                        dc = all_dts[curr]
                        b = price_lookup.get((c6, dc))
                        if not b: break
                        oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b[:8][:8]
                        if iyzc:
                            prev_c = round(float(cc), 2); curr += 1; continue
                        arr = bars_5m_map.get((c6, dc))
                        if arr is not None and len(arr) >= 12:
                            idx_1030 = -1
                            cum_v, cum_a = 0.0, 0.0
                            for bi in range(len(arr)):
                                cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                                if arr[bi, 0] == 1030:
                                    idx_1030 = bi; break
                            if idx_1030 >= 0:
                                bc_1030 = arr[idx_1030, 4]
                                vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                                if bc_1030 >= ztc - 0.01:
                                    for bi in range(idx_1030 + 1, len(arr) - 1):
                                        if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                            px = round(float(arr[bi + 1, 1]), 2)
                                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush", "final_height": boards_held}
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    else:
                                        px = round(float(cc), 2)
                                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break", "final_height": boards_held}
                                elif bc_1030 < vwap_1030:
                                    px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut", "final_height": boards_held}
                                else:
                                    if iztc:
                                        prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                                    if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                                        used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                                    px = round(float(cc), 2)
                                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close", "final_height": boards_held}
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close", "final_height": boards_held}
                    return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c, "tag": "eod_close", "final_height": boards_held}
                else:
                    px = round(float(c3), 2)
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": d3, "exit_at_open": False, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "nshape_d3_close", "final_height": 1}
            curr = idx3
            while curr < len(all_dts):
                b = price_lookup.get((c6, all_dts[curr]))
                if not b or not b[7]:
                    px = round(float(b[0]), 2) if b else prev_c
                    return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[curr], "exit_at_open": True, "sealed_2b": 0, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "fail_open_cut", "final_height": 1}
                curr += 1
            return None

        # 分支 2：买入日封死二板
        curr = idx3
        boards_held = 2
        used_immunity = False
        while curr < len(all_dts) and (curr - idx2 <= 12):
            dc = all_dts[curr]
            b = price_lookup.get((c6, dc))
            if not b: break
            oc, hc, lc, cc, ztc, dtc, iztc, iyzc = b[:8]
            if iyzc:
                prev_c = round(float(cc), 2); curr += 1; continue
            arr = bars_5m_map.get((c6, dc))
            if arr is not None and len(arr) >= 12:
                idx_1030 = -1
                cum_v, cum_a = 0.0, 0.0
                for bi in range(len(arr)):
                    cum_v += arr[bi, 5]; cum_a += arr[bi, 6]
                    if arr[bi, 0] == 1030:
                        idx_1030 = bi; break
                if idx_1030 >= 0:
                    bc_1030 = arr[idx_1030, 4]
                    vwap_1030 = cum_a / cum_v if cum_v > 0 else bc_1030
                    if bc_1030 >= ztc - 0.01:
                        for bi in range(idx_1030 + 1, len(arr) - 1):
                            if arr[bi, 0] >= 1430 and arr[bi, 4] < ztc - 0.01:
                                px = round(float(arr[bi + 1, 1]), 2)
                                return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1430_rush", "final_height": boards_held}
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        else:
                            px = round(float(cc), 2)
                            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_break", "final_height": boards_held}
                    elif bc_1030 < vwap_1030:
                        px = round(float(arr[idx_1030 + 1, 1]), 2) if idx_1030 + 1 < len(arr) else round(float(bc_1030), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "5m_1030_weak_cut", "final_height": boards_held}
                    else:
                        if iztc:
                            prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
                        if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                            used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
                        px = round(float(cc), 2)
                        return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close", "final_height": boards_held}
            if iztc:
                prev_c = round(float(cc), 2); boards_held += 1; curr += 1; continue
            if (boards_held >= 3) and (not used_immunity) and (cc >= prev_c * 1.02) and (curr + 1 < len(all_dts)):
                used_immunity = True; prev_c = round(float(cc), 2); curr += 1; continue
            px = round(float(cc), 2)
            return {"net_ret": round((px / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": dc, "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": px, "tag": "eod_close", "final_height": boards_held}
        return {"net_ret": round((prev_c / buy_px) * (1.0 - fee) - 1.0, 4), "exit_date": all_dts[min(curr, len(all_dts)-1)], "exit_at_open": False, "sealed_2b": 1, "buy_date": d2, "c6": c6, "name": row["name"], "buy_price": buy_px, "exit_price": prev_c, "tag": "eod_close", "final_height": boards_held}
    return sim_trade
