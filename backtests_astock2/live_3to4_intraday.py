#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
live_3to4_intraday.py — 三进四 V3.4 盘前预演与 09:25:03 实时竞价极速算分引擎
秒读 3to4_premarket_cache.json，并发抓取腾讯实时竞价行情，调用 score_single_3to4_row 输出总分与触发价。
"""
import os, sys, json, time, urllib.request, datetime

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path: sys.path.insert(0, CUR_DIR)
from score_3to4_v31_card import score_single_3to4_row

CACHE_FILE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/3to4_premarket_cache.json"

def fetch_tencent_batch(codes: list[str]) -> dict[str, dict]:
    if not codes: return {}
    q_list = [f"{'sh' if c.startswith('60') else 'sz'}{c}" for c in set(codes)]
    url = f"http://qt.gtimg.cn/q={','.join(q_list)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = {}
    try:
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            content = resp.read().decode("gbk", errors="ignore")
            for line in content.strip().split(";"):
                if not line.strip() or "~" not in line: continue
                parts = line.split("~")
                if len(parts) > 30:
                    c6 = parts[2].strip()
                    px = float(parts[3]) if parts[3] else 0.0
                    pc = float(parts[4]) if parts[4] else 0.0
                    op = float(parts[5]) if parts[5] else 0.0
                    b1_v = float(parts[10]) if len(parts) > 10 and parts[10] else 0.0
                    s1_v = float(parts[20]) if len(parts) > 20 and parts[20] else 0.0
                    op_px = op if op > 0.0 else px
                    op_pct = (op_px / pc - 1.0) if pc > 0 else 0.0
                    is_yz = bool(op_pct >= 0.098 or (b1_v > 0 and s1_v == 0 and op_pct >= 0.090))
                    res[c6] = {"name": parts[1], "code": c6, "price": px, "pre_c": pc,
                               "open": op_px, "open_pct": op_pct, "is_yizi": is_yz}
    except Exception: pass
    return res

def run_premarket(cache: dict):
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    d3, bd = cache.get("d3_date", ""), cache.get("buy_date", "")
    print("=" * 86)
    print(f"【三进四主战策略 V3.4 盘前环境与推演面板】 信号日: {d3} -> 竞价日: {bd}")
    print(f"大盘情绪: 最高连板={env.get('mkt_max_board_prev')}板 | 全市场涨停={env.get('mkt_zt_prev')}家 | 三板跌停={env.get('prev_3b_dt_cnt')}家 | 沪深300 1日={env.get('csi_1d_prev', 0)*100:+.2f}%, 5日={env.get('csi_5d_prev', 0)*100:+.2f}%")
    print(f"跨周期加减分: 周一跨周末发酵+2分 | 11月非退潮月0分 | 最高板<=4板破局+8分 | 涨停35..85家温热+5分")
    print("=" * 86)

    for c in cands:
        c6, name = c["code"], c["name"]
        px3, to = c["px_d3"], c["prev_to"]
        lock, rfm = c["lock_top10"], c["real_free_mcap"]
        opn, fst = c["open_board_count"], c["first_seal_time"]
        base_r = dict(c, open_pct=0.055, buyable_open=True, is_top1_3b_open=True,
                      plate_fb_ho_cnt=0, plate_fb_yz_cnt=0, plate_peers_open_avg=0.01,
                      prev_3b_dt_cnt=env.get("prev_3b_dt_cnt", 0), csi_1d_prev=env.get("csi_1d_prev", 0.0),
                      csi_5d_prev=env.get("csi_5d_prev", 0.0), mkt_zt_prev=env.get("mkt_zt_prev", 50))
        res_base = score_single_3to4_row(base_r)
        trig = max(round(px3 * 1.065, 2), round(px3 * 1.055, 2))

        print(f"\n标的: {c6} {name} | 三板收盘: {px3:.2f}元 | 换手: {to:.2f}% | 锁仓: {lock:.1f}% | 自由流通盘: {rfm:.1f}亿 | 封板: {fst} (开板{opn}次)")
        if not res_base["passed_skeleton"]:
            print(f"  ❌ 硬骨架否决: {res_base['breakdown_str']}")
            continue
        print(f"  ✅ 静态基准预评分: {res_base['score']}分 ({res_base['tier']})")
        print(f"  📝 加分细目: {res_base['breakdown_str']}")
        print(f"  🎯 09:25 竞价过线推演:")
        print(f"     - 标准主力单 (>=90分): 竞价开盘涨幅在 +3.0% 至 +9.2% 之间且为可买三板头名即可达 {res_base['score']}分")
        print(f"     - 严格高确信单 (>=98分): 需同题材前日首板队友换手高开助攻 >=2 只 (+4分 -> {res_base['score']+4}分)")
        print(f"     - 极严防守单 (>=102分): 需同题材助攻达标且题材热度满115分 (+3分 -> {res_base['score']+7}分)")
        print(f"  ⚡ 09:26 突破条件单触发价公式: max(昨收*1.065, 今开价) = {trig:.2f}元 (卖五价扫入，11:30未触发撤单)")

def run_live_mode(cache: dict, mock_open_map: dict = None) -> list[dict]:
    t0 = time.time()
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    all_codes = set(c["code"] for c in cands)
    for c in cands:
        all_codes.update(c.get("plate_fb_codes", []))
        all_codes.update(c.get("plate_zt_codes", []))

    quotes = fetch_tencent_batch(list(all_codes))
    now = datetime.datetime.now()
    is_live = (now.weekday() < 5 and (now.hour == 9 and now.minute >= 25 or now.hour >= 10 and now.hour < 15))

    cand_inputs = []
    for c in cands:
        c6 = c["code"]
        q = quotes.get(c6, {})
        op_pct = 0.055
        if mock_open_map and c6 in mock_open_map: op_pct = float(mock_open_map[c6])
        elif q.get("open", 0) > 0 and q.get("pre_c", 0) > 0 and is_live: op_pct = float(q["open"] / q["pre_c"] - 1.0)
        buyable = bool(op_pct < 0.098 and (not is_live or not q.get("is_yizi", False)))
        cand_inputs.append({"c": c, "q": q, "op_pct": op_pct, "buyable": buyable})

    max_op = max([ci["op_pct"] for ci in cand_inputs if ci["buyable"]], default=-9.99)
    results = []

    print("=" * 86)
    print(f"【三进四主战策略 V3.4 极速决策引擎】 耗时: {time.time()-t0:.3f}s | 时段: {'实盘开盘竞价' if is_live else '盘前/盘后快照（默认基准场景）'}")
    print("=" * 86)

    for ci in cand_inputs:
        c = ci["c"]
        c6, name, px3 = c["code"], c["name"], c["px_d3"]
        op_pct, buyable = ci["op_pct"], ci["buyable"]
        is_top1 = bool(buyable and op_pct >= max_op - 1e-5)

        fb_ho, fb_yz, peer_ops = 0, 0, []
        for s6 in c.get("plate_fb_codes", []):
            sq = quotes.get(s6, {})
            if mock_open_map and s6 in mock_open_map:
                so_pct = float(mock_open_map[s6]); syz = bool(so_pct >= 0.098)
            elif is_live:
                so_pct = sq.get("open_pct", 0.0); syz = sq.get("is_yizi", False)
            else:
                so_pct, syz = 0.015, False
            if so_pct >= 0.03 and not syz: fb_ho += 1
            if syz: fb_yz += 1

        for z6 in c.get("plate_zt_codes", []):
            if mock_open_map and z6 in mock_open_map: peer_ops.append(float(mock_open_map[z6]))
            elif is_live and z6 in quotes and "open_pct" in quotes[z6]: peer_ops.append(quotes[z6]["open_pct"])
        peers_avg = float(sum(peer_ops) / len(peer_ops)) if peer_ops else 0.01

        row = dict(c, open_pct=op_pct, buyable_open=buyable, is_top1_3b_open=is_top1,
                   plate_fb_ho_cnt=fb_ho, plate_fb_yz_cnt=fb_yz, plate_peers_open_avg=peers_avg,
                   prev_3b_dt_cnt=env.get("prev_3b_dt_cnt", 0), csi_1d_prev=env.get("csi_1d_prev", 0.0),
                   csi_5d_prev=env.get("csi_5d_prev", 0.0), mkt_zt_prev=env.get("mkt_zt_prev", 50))
        sc_res = score_single_3to4_row(row)
        trig = max(round(px3 * 1.065, 2), round(px3 * (1.0 + op_pct), 2))
        res_item = {"code": c6, "name": name, "open_pct": op_pct, "score": sc_res["score"],
                    "tier": sc_res["tier"], "trig_px": trig, "breakdown": sc_res["breakdown_str"],
                    "passed": sc_res["passed_skeleton"]}
        results.append(res_item)

        status_tag = "🚀 [达标主力]" if sc_res["score"] >= 90 else "⛔ [未达标]"
        print(f"\n{status_tag} {c6} {name:6s} | 竞价: {op_pct*100:+.2f}% (头名={is_top1}) | 总分: {sc_res['score']:4d} | 分档: {sc_res['tier']}")
        print(f"  触发价: {trig:6.2f}元 (max(昨收*1.065, 今开)) | 执行: 09:26挂突破条件单，卖五价扫入，11:30未触撤单\n  细目: {sc_res['breakdown_str']}")
    return results

if __name__ == "__main__":
    c_data = json.load(open(CACHE_FILE)) if os.path.exists(CACHE_FILE) else {}
    run_live_mode(c_data)
