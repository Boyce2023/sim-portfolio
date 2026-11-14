#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三进四 V3.4 百分制打分卡（头名、锁仓、换手三项由否决改扣分，加三板早盘换手封板加分，含跨周末加分与1月5月扣分，自动输出总分、分档、突破触发价与明细）
用法：
  python3 score_3to4_v31_card.py --date 2026-10-27
  python3 score_3to4_v31_card.py --recent 10
"""
import os
import sys
import argparse
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)


import json
import bisect

_IDX_CACHE_PATH = os.path.abspath(os.path.join(CUR_DIR, "..", "backtests_astock", "sandbox_lab", "index_klines_5y_cache.json"))
_MKT_TDTS = sorted(json.load(open(_IDX_CACHE_PATH, "r"))["sh000300"].keys()) if os.path.exists(_IDX_CACHE_PATH) else []


def _is_post_holiday_or_monday(r: dict) -> bool:
    if "is_post_holiday_or_mon" in r and pd.notna(r["is_post_holiday_or_mon"]):
        return bool(r["is_post_holiday_or_mon"])
    bd = str(r.get("buy_date", ""))[:10]
    if len(bd) == 10 and _MKT_TDTS:
        pos = bisect.bisect_left(_MKT_TDTS, bd)
        if pos > 0:
            return (pd.Timestamp(bd) - pd.Timestamp(_MKT_TDTS[pos - 1])).days >= 3
    if len(bd) == 10:
        return pd.Timestamp(bd).weekday() == 0
    return False


def score_single_3to4_row(r: dict) -> dict:
    """对单只三进四候选股打分（V3.4 定版），返回 {passed_skeleton, score, tier, veto_reasons, breakdown_str}"""
    veto = []
    if not bool(r.get("is_10cm_non_st", True)):
        veto.append("非主板10厘米或ST")
    if bool(r.get("prev_is_yizi", False)):
        veto.append("三板一字缩量")
    if not bool(r.get("buyable_open", True)):
        veto.append("四板一字不可买")
    if bool(r.get("has_tox_notice", False)) or bool(r.get("has_stock_reg", False)):
        veto.append("真立案减持或个股监管函")
    if int(r.get("open_board_count", 0)) < 1:
        veto.append("三板未开板死封")
    to = float(r.get("prev_to", 0.0))
    op = float(r.get("open_pct", 0.0))
    if not (0.030 <= op <= 0.092):
        veto.append(f"四板竞价越界({op*100:.1f}%)")
    lock_ok = float(r.get("lock_top10", 0.0)) >= 45.0 or float(r.get("real_free_mcap", 0.0)) >= 45.0
    to_ok = 8.5 <= to <= 31.0
    top1_ok = bool(r.get("is_top1_3b_open", True))

    if veto:
        return {
            "passed_skeleton": False,
            "score": -999,
            "tier": "淘汰（未过硬骨架）",
            "veto_reasons": veto,
            "breakdown_str": "未过硬骨架：" + "、".join(veto),
        }

    sc = 78
    items = ["硬骨架底分78"]
    if not top1_ok:
        sc -= 12; items.append("非同日可买三板竞价头名扣12")
    if not lock_ok:
        sc -= 10; items.append("锁仓与自由流通盘双低扣10")
    if not to_ok:
        sc -= 10; items.append(f"三板换手越界({to:.1f}%)扣10")
    fs_raw = str(r.get("first_seal_time", "")).replace(":", "")[:4]
    fs = int(fs_raw) if fs_raw.isdigit() else 9999
    if 936 <= fs <= 1030:
        sc += 3; items.append("三板09:36至10:30换手后封板加3")
    px = float(r.get("px_d3", 25.0))
    if px <= 20.0:
        sc += 8; items.append("20元内低中价加8")
    elif px > 32.0:
        sc -= 5; items.append("超32元高价扣5")

    if int(r.get("mkt_max_board_prev", 5)) <= 4:
        sc += 8; items.append("最高板不超4板破局加8")

    if float(r.get("p_elo", 100.0)) >= 115.0:
        sc += 3; items.append("八年题材高热度加3")

    mzt = int(r.get("mkt_zt_prev", 50))
    if mzt >= 95:
        sc -= 10; items.append("前日百股涨停过热扣10")
    elif 35 <= mzt <= 85:
        sc += 5; items.append("涨停温热区加5")

    if bool(r.get("has_ex_reg", False)):
        sc -= 12; items.append("交易所重点监控期扣12")
    if bool(r.get("surf_yz_buy", False)):
        sc -= 12; items.append("三板一日游砸盘席位买入扣12")

    lh = int(r.get("lhb_lh_cnt", 0))
    if lh == 0:
        sc += 4; items.append("零拉萨席位加4")
    elif lh >= 3:
        sc -= 5; items.append("拉萨扎堆扣5")

    fb_ho = int(r.get("plate_fb_ho_cnt", 0))
    fb_yz = int(r.get("plate_fb_yz_cnt", 0))
    if fb_ho >= 2 and fb_yz == 0:
        sc += 4; items.append("同题材首板换手高开助攻加4")
    if fb_yz >= 1:
        sc -= 7; items.append("同题材首板顶一字兑现扣7")

    if float(r.get("plate_peers_open_avg", 0.0)) < -0.015:
        sc -= 10; items.append("同题材队友核按钮扣10")

    dt3 = int(r.get("prev_3b_dt_cnt", 0))
    if dt3 == 0:
        sc += 3; items.append("前日三板零跌停加3")
    elif dt3 >= 2:
        sc -= 4; items.append("前日三板多股跌停扣4")

    if float(r.get("csi_1d_prev", 0.0)) <= -0.020 or float(r.get("csi_5d_prev", 0.0)) <= -0.030:
        sc -= 8; items.append("前日沪深300急杀或5日破位扣8")

    if 9.5 <= to <= 28.0:
        sc += 3; items.append("换手黄金带加3")

    if _is_post_holiday_or_monday(r):
        sc += 2; items.append("周一或节后跨周末发酵加2")

    bd_str = str(r.get("buy_date", ""))
    b_mon = int(bd_str[5:7]) if len(bd_str) >= 7 and bd_str[5:7].isdigit() else 0
    if b_mon in (1, 5):
        sc -= 4; items.append("1月年报预告或5月退潮窗扣4")

    if sc >= 102:
        tier = "极严防守单（满102分）"
    elif sc >= 98:
        tier = "严格高确信单（98至101分）"
    elif sc >= 90:
        tier = "标准主力单（90至97分）"
    else:
        tier = "总分未达90分放弃"

    return {
        "passed_skeleton": True,
        "score": int(sc),
        "tier": tier,
        "veto_reasons": [],
        "breakdown_str": "，".join(items),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=str, default="")
    ap.add_argument("--recent", type=int, default=12)
    args = ap.parse_args()

    df = pd.read_parquet(f"{CUR_DIR}/data_5y/cand_3to4_enriched54.parquet")
    sub = df[df["buy_date"] == args.date] if args.date else df[df["buy_date"] >= sorted(df["buy_date"].unique())[-args.recent]]
    for _, row in sub.sort_values(["buy_date", "open_pct"], ascending=[True, False]).iterrows():
        res = score_single_3to4_row(row.to_dict())
        if args.date or res["score"] >= 90:
            trig_px = max(round(float(row["px_d3"]) * 1.065, 2), round(float(row["px_d3"]) * (1.0 + float(row["open_pct"])), 2))
            print(f"[{row['buy_date']}] {str(row['code']).zfill(6)} {row['name']:6s} | 总分={res['score']:4d} | 触发价={trig_px:6.2f} | {res['tier']} | {res['breakdown_str']}")


if __name__ == "__main__":
    main()
