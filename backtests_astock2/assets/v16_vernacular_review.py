# -*- coding: utf-8 -*-
"""
v16_vernacular_review.py: 大白话复盘与出场点评生成器
零内部变量名，零破折号，零正负百分比机械字眼，单句通俗人话。
"""
def generate_vernacular_review(sim_res, o2, h2, trig_p, zt2, is_zt2):
    if sim_res is None or not sim_res.get("executed", True):
        if sim_res and sim_res.get("tag") == "pm_cancel_1130":
            am_h = float(sim_res.get("am_high", o2))
            return {
                "exit_reason": f"上午11:30前最高仅 {am_h:.2f}元，未触及挂单价 {trig_p:.2f}元，午休撤单未成交",
                "pm_comment": "上午收盘前未触及点火价，按午休撤单铁律放弃下午盘偷袭诱多，全天未买进。"
            }
        if o2 >= zt2 - 0.005 or o2 <= 0:
            return {
                "exit_reason": f"集合竞价高开逼近涨停（{o2:.2f}元），缺乏安全买点跳过",
                "pm_comment": "开盘逼近涨停缺乏换手空间，未触发挂单买点。"
            }
        else:
            return {
                "exit_reason": f"盘中冲高最高仅 {h2:.2f}元，未触及挂单价 {trig_p:.2f}元 未成交",
                "pm_comment": f"开盘冲高最高仅 {h2:.2f}元，未达挂单门槛，全天未买进。"
            }

    tag = sim_res.get("tag", "eod_close")
    exit_px = sim_res.get("exit_price", 0.0)
    net_ret = sim_res.get("net_ret", 0.0) # float percentage e.g. 5.37
    final_height = sim_res.get("final_height", 1)

    if tag == "fail_open_cut":
        return {
            "exit_reason": f"买进当日未封二板，次日开盘承接转弱，集合竞价止损离场（卖出价 {exit_px:.2f}元）",
            "pm_comment": "买进当日炸板未能封死，次日集合竞价弱转强未成，果断止损控制回撤。"
        }
    elif tag == "nshape_d3_close":
        return {
            "exit_reason": f"买进当日未封二板但留溢价，次日反包冲高未封板，收盘平仓离场（卖出价 {exit_px:.2f}元）",
            "pm_comment": "炸板后次日尝试弱转强反包，尾盘未能封死涨停，按纪律收盘平仓兑现。"
        }
    elif tag == "5m_1030_weak_cut":
        return {
            "exit_reason": f"买进当日封死二板，次日十点半跌破分时均线平仓（卖出价 {exit_px:.2f}元）",
            "pm_comment": "晋级二板后次日盘中转弱，十点半跌破分时均线，执行右侧保利平仓。"
        }
    elif tag == "5m_1430_rush":
        return {
            "exit_reason": f"买进当日封死二板，连板锁仓至断板日午后两点半炸板抢跑兑现（卖出价 {exit_px:.2f}元）",
            "pm_comment": "连板主升格局锁仓，尾盘两点半封单松动开板，顺势抢跑锁定主升利润。"
        }
    elif tag == "eod_break":
        return {
            "exit_reason": f"买进当日封死二板，断板日早盘封死但盘中炸板，收盘平仓兑现（卖出价 {exit_px:.2f}元）",
            "pm_comment": "连板持仓遇高位分歧炸板，尾盘未能回封，收盘果断离场锁定溢价。"
        }
    else: # eod_close
        if final_height >= 3:
            return {
                "exit_reason": f"买进当日封死二板走出{final_height}连板，断板日收盘平仓兑现（卖出价 {exit_px:.2f}元）",
                "pm_comment": f"主线排头兵走出{final_height}连板主升浪，持有至断板日尾盘平仓吃满利润。"
            }
        else:
            return {
                "exit_reason": f"买进当日封死二板，次日维持均线上方但未封涨停，收盘兑现（卖出价 {exit_px:.2f}元）",
                "pm_comment": "二板晋级后次日全天维持强势，尾盘未能再次封涨停，收盘稳健兑现离场。"
            }
