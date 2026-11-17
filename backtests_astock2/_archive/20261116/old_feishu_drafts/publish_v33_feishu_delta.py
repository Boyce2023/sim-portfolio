#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, subprocess
from publish_feishu_3to4_wiki import HTML_DIR, publish_one
from score_3to4_v31_card import score_single_3to4_row

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
subprocess.check_call(["/opt/homebrew/bin/python3.13", f"{CUR_DIR}/build_feishu_3to4_htmls.py"])
subprocess.check_call(["/opt/homebrew/bin/python3.13", f"{CUR_DIR}/build_feishu_3to4_sub_htmls.py"])

publish_one("main_3to4", "三进四", f"{HTML_DIR}/00_main_3to4.html", None)
publish_one("hub_3to4", "20261113 三进四专项小回测全集与近期有效度总检", f"{HTML_DIR}/00_hub_3to4_overview.html", "main_3to4")
publish_one("sub10", "10 三项否决改扣分与不稳定因子拆细回测", f"{HTML_DIR}/10_study.html", "hub_3to4")

# Verify Monday 2026-11-16 603396 金辰股份 exact V3.3 integer score across open conditions
base_jc = {
    "code": "603396", "name": "金辰股份", "sig_date": "2026-11-13", "buy_date": "2026-11-16",
    "is_10cm_non_st": True, "prev_is_yizi": False, "buyable_open": True,
    "has_tox_notice": False, "has_stock_reg": False, "open_board_count": 1,
    "lock_top10": 46.49, "real_free_mcap": 26.2, "prev_to": 14.29, "open_pct": 0.055,
    "is_top1_3b_open": True, "px_d3": 35.32, "mkt_max_board_prev": 7, "p_elo": 108.0,
    "mkt_zt_prev": 68, "has_ex_reg": False, "surf_yz_buy": False, "lhb_lh_cnt": 0,
    "plate_fb_ho_cnt": 0, "plate_fb_yz_cnt": 0, "plate_peers_open_avg": 0.01,
    "prev_3b_dt_cnt": 0, "csi_1d_prev": -0.005, "csi_5d_prev": 0.012,
}
print("Jinchen V3.3 Static Base:", score_single_3to4_row(base_jc))
jc_assist = dict(base_jc, plate_fb_ho_cnt=2)
print("Jinchen V3.3 +2 FB assist:", score_single_3to4_row(jc_assist))
jc_full = dict(base_jc, plate_fb_ho_cnt=2, p_elo=116.0)
print("Jinchen V3.3 +2 FB assist + Elo>=115:", score_single_3to4_row(jc_full))
