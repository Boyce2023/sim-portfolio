#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_five_board_today.py — Buwen 实盘专属《五板策略》每日全量并列播报与95%止盈线测算引擎

严格对齐 Buwen《五板策略》唯一口径（docs/90_内部_给Claude读/astock/五板策略明细/）：
  1. 范围：10cm 沪深主板非 ST（60xxxx / 00xxxx），真实连续 >= 5 连板（无日历断档重置）。
  2. 唯一强制硬门：连板次日 09:25 竞价开盘涨幅 <= +5.5%（-10% 至 +5.5% 全包，无下限挖洞）且非一字涨停。
     若次日一字买不到或高开 > +5.5% 未买但收盘续板，顺延至 6 板及以上等待本轮首个合格开盘。
  3. 重要成色项（绝非一票否决硬门）：前十大流通股东锁仓比（>=50% 优）、末板真实换手率（>=15% 较稳）、真实流通市值；
     100% 全量并列展示全市场每一只 >= 5 连板股，严禁私自预筛漏报。
  4. 天数与卖出：买入日为第 1 天；第 2 至第 4 天按前一日冻结指数计算的 10 日 100% 严重异动 95% 止盈线挂单止盈，否则第 4 天收盘卖。

⛔ 严禁 import yfinance（D12 铁律）。
"""
import datetime
import json
import math
import os
import sys
import urllib.request

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
FREE_CACHE = f"{SIM}/backtests_astock/sandbox_lab/pit_top10_freeholders_cache.json"
ALL_CACHE = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def _sym(c6: str) -> str:
    return ("sh" if c6.startswith("6") else "sz") + c6


def _get_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))


def _get_kline(sym: str, n: int = 25) -> list:
    u = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{n},qfq"
    d = _get_json(u)
    node = d["data"][sym]
    bars = node.get("qfqday") or node.get("day") or []
    return [(b[0], float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5])) for b in bars if float(b[5]) > 0]


def _get_quotes(codes: list) -> dict:
    if not codes:
        return {}
    u = "http://qt.gtimg.cn/q=" + ",".join(_sym(c) for c in codes)
    raw = urllib.request.urlopen(u, timeout=8).read().decode("gbk", "ignore")
    out = {}
    for line in raw.strip().split(";"):
        if "~" not in line:
            continue
        p = line.split("~")
        if len(p) > 46:
            c6 = p[2].zfill(6)
            pre = float(p[4] or 0)
            op = float(p[5] or 0)
            cur = float(p[3] or 0)
            zt = math.floor(pre * 1.10 * 100.0 + 0.5) / 100.0 if pre > 0 else 0.0
            q_dt_raw = p[30] if len(p) > 30 else ""
            q_dt = f"{q_dt_raw[:4]}-{q_dt_raw[4:6]}-{q_dt_raw[6:8]}" if len(q_dt_raw) >= 8 else ""
            out[c6] = {
                "name": p[1], "pre": pre, "open": op, "cur": cur, "zt": zt,
                "opct": (op / pre - 1.0) if (pre > 0 and op > 0) else 0.0,
                "cpct": float(p[32] or 0) / 100.0,
                "turn": float(p[38] or 0),
                "mcap": float(p[44] or 0),
                "q_dt": q_dt,
                "is_yizi": bool(op > 0 and zt > 0 and op >= zt - 0.005),
            }
    return out


def _get_lock_pct(c6: str, today_str: str, free_map: dict, all_map: dict):
    rows = free_map.get(c6)
    if rows:
        valid = [r for r in rows if str(r.get("NOTICE_DATE", ""))[:10] <= today_str and r.get("FREE_HOLDNUM_RATIO") is not None]
        if valid:
            latest_end = max(str(r.get("END_DATE", ""))[:10] for r in valid)
            s = sum(float(r["FREE_HOLDNUM_RATIO"]) for r in valid if str(r.get("END_DATE", ""))[:10] == latest_end)
            if 0 < s < 100:
                return round(s, 2), latest_end
    arows = all_map.get(c6)
    if arows:
        valid = [r for r in arows if str(r[0])[:10] <= today_str and r[2] is not None]
        if valid:
            valid.sort(key=lambda r: (str(r[1]), str(r[0])))
            return round(float(valid[-1][2]), 2), str(valid[-1][1])[:10]
    try:
        sc = f"{c6}.SH" if c6.startswith("6") else f"{c6}.SZ"
        u = (
            "https://datacenter.eastmoney.com/securities/api/data/v1/get?"
            f"reportName=RPT_F10_EH_FREEHOLDERS&columns=END_DATE,HOLD_NUM_RATIO,FREE_HOLDNUM_RATIO&"
            f"filter=(SECUCODE%3D%22{sc}%22)&pageNumber=1&pageSize=20&sortTypes=-1&sortColumns=END_DATE"
        )
        d = _get_json(u, timeout=6)
        data = (d.get("result") or {}).get("data") or []
        if data:
            latest_end = str(data[0].get("END_DATE", ""))[:10]
            s = sum(float(x.get("FREE_HOLDNUM_RATIO") or 0) for x in data if str(x.get("END_DATE", ""))[:10] == latest_end)
            if 0 < s < 100:
                return round(s, 2), latest_end
    except Exception:
        pass
    return None, ""


def _calc_streak(bars: list) -> int:
    if len(bars) < 2:
        return 0
    st = 0
    for i in range(len(bars) - 1, 0, -1):
        prev_c = bars[i - 1][2]
        cur_c = bars[i][2]
        zt = math.floor(prev_c * 1.10 * 100.0 + 0.5) / 100.0
        if cur_c >= zt - 0.005:
            st += 1
        else:
            break
    return st


def _calc_95_line(c6: str, bars: list, idx_map: dict, frozen_date: str):
    idx_prev = idx_map.get(frozen_date)
    if not idx_prev:
        return None, None
    cands = []
    for b in bars[-10:]:
        bd, _, bc, _, _, _ = b
        ib = idx_map.get(bd)
        if not ib:
            continue
        p95 = bc * (0.95 + idx_prev / ib)
        p100 = bc * (1.00 + idx_prev / ib)
        cands.append((p95, p100, bd))
    if not cands:
        return None, None
    cands.sort(key=lambda x: x[0])
    p95, p100, bd = cands[0]
    return math.ceil(p95 * 100.0 - 1e-8) / 100.0, round(p100, 2)


def _fetch_em_zt_date(d_compact: str) -> list:
    u = f"https://push2ex.eastmoney.com/getTopicZTPool?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt&Pageindex=0&pagesize=200&sort=lbc:desc&date={d_compact}"
    try:
        d = _get_json(u, timeout=8)
        return (d.get("data") or {}).get("pool") or []
    except Exception:
        return []


def print_five_board_section():
    print("\n=== [7] Buwen 实盘专属《五板策略》全量并列播报（唯一硬门：连板次日09:25开<=+5.5%非一字；锁仓比重要参考不硬删） ===")
    try:
        idx_sh = {b[0]: b[2] for b in _get_kline("sh000002", 30)}
        idx_sz = {b[0]: b[2] for b in _get_kline("sz399107", 30)}
        cal_dates = sorted(idx_sh.keys())
        if len(cal_dates) < 5:
            print("  [WARN] 指数日线不足，跳过五板策略检测")
            return
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        is_post_close = (now.hour > 15) or (now.hour == 15 and now.minute >= 0)
        # 盘前/盘中取上一已收盘日作为信号日；盘后(>=15:00)取今日作为明日信号日
        if today_str == cal_dates[-1] and not is_post_close:
            sig_date = cal_dates[-2]
            mode_tag = "今日09:25实盘窗口"
        else:
            sig_date = cal_dates[-1]
            mode_tag = "盘后备战明日09:25"

        free_map = json.load(open(FREE_CACHE, encoding="utf-8")) if os.path.exists(FREE_CACHE) else {}
        all_map = json.load(open(ALL_CACHE, encoding="utf-8")) if os.path.exists(ALL_CACHE) else {}

        # A. 扫描信号日全市场所有 >= 5 连板主板非 ST 股（100% 全量并列）
        pool_sig = _fetch_em_zt_date(sig_date.replace("-", ""))
        cand_codes = []
        for x in pool_sig:
            c6 = str(x.get("c", "")).zfill(6)
            nm = str(x.get("n", ""))
            if not (c6.startswith("00") or c6.startswith("60")):
                continue
            if "ST" in nm.upper():
                continue
            if int(x.get("lbc", 0)) >= 5:
                cand_codes.append((c6, nm, int(x.get("lbc", 0)), float(x.get("hs", 0))))

        quotes = _get_quotes([c[0] for c in cand_codes])
        print(f"  信号日={sig_date} | 阶段={mode_tag} | 全市场主板非ST连板>=5共 {len(cand_codes)} 只（100%全量并列）")
        if not cand_codes:
            print("  信号日全市场无 10cm 主板非 ST 连续 >= 5 连板股票")
        for c6, nm, em_lbc, em_turn in cand_codes:
            bars = _get_kline(_sym(c6), 25)
            bars_sig = [b for b in bars if b[0] <= sig_date]
            real_streak = _calc_streak(bars_sig)
            if real_streak < 5:
                continue
            sig_close = bars_sig[-1][2]
            cap55 = round(sig_close * 1.055, 2)
            lock_pct, lock_end = _get_lock_pct(c6, today_str, free_map, all_map)
            q = quotes.get(c6, {})
            mcap = q.get("mcap", 0.0)
            if lock_pct is not None and lock_pct < 99.0:
                true_turn = em_turn / (1.0 - lock_pct / 100.0)
                true_mcap = mcap * (1.0 - lock_pct / 100.0)
                lock_tag = f"锁仓{lock_pct:.1f}%({lock_end})({'高锁仓优' if lock_pct>=50 else '锁仓<50%留意'})|真换手{true_turn:.1f}%|真流值{true_mcap:.1f}亿"
            else:
                lock_tag = f"锁仓未知|账面换手{em_turn:.1f}%|账面流值{mcap:.1f}亿"

            is_live_next = (q.get("q_dt", "") > sig_date)
            if is_live_next:
                op = q.get("opct", 0.0)
                if q.get("is_yizi"):
                    status = "一字买不到(若今收续板则顺延)"
                elif op <= 0.055 + 1e-8:
                    status = f"【触发五板买点】今开{q['open']:.2f}({op*100:+.2f}%<=+5.5%)"
                else:
                    status = f"今开{q['open']:.2f}({op*100:+.2f}%>+5.5%跳过，若今收续板则顺延)"
            else:
                status = f"待明日09:25竞价(开盘<=+5.5%上限{cap55:.2f}元即触发)"

            idx_m = idx_sh if c6.startswith("6") else idx_sz
            p95, p100 = _calc_95_line(c6, bars_sig, idx_m, sig_date)
            line_s = f"参考95%线{p95:.2f}(100%={p100:.2f})" if p95 else ""
            print(f"  • {c6} {nm} | 真{real_streak}连板(收{sig_close:.2f}) | {status} | {lock_tag} | {line_s}")

        # B. 跟踪近 3 个交易日内已触发五板策略标的（第 2 至第 4 天 95% 止盈线跟踪）
        check_sig_dates = [d for d in cal_dates[-4:-1] if d < sig_date]
        tracked = []
        seen_c = set()
        for sd in reversed(check_sig_dates):
            pool_old = _fetch_em_zt_date(sd.replace("-", ""))
            for x in pool_old:
                c6 = str(x.get("c", "")).zfill(6)
                nm = str(x.get("n", ""))
                if c6 in seen_c or not (c6.startswith("00") or c6.startswith("60")) or "ST" in nm.upper():
                    continue
                if int(x.get("lbc", 0)) >= 5:
                    bars = _get_kline(_sym(c6), 25)
                    b_sd = [b for b in bars if b[0] <= sd]
                    if _calc_streak(b_sd) >= 5:
                        b_after = [b for b in bars if b[0] > sd]
                        if b_after:
                            ed, eo, ec = b_after[0][0], b_after[0][1], b_after[0][2]
                            prev_c = b_sd[-1][2]
                            zt_e = math.floor(prev_c * 1.10 * 100.0 + 0.5) / 100.0
                            gap = eo / prev_c - 1.0
                            if gap <= 0.055 + 1e-8 and eo < zt_e - 0.005:
                                seen_c.add(c6)
                                hold_day = len(b_after) + (1 if is_post_close else 0)
                                # 若盘后，展示次日(第 hold_day 天)的95%止盈线
                                idx_m = idx_sh if c6.startswith("6") else idx_sz
                                frozen_d = cal_dates[-1] if is_post_close else cal_dates[-2]
                                bars_frz = [b for b in bars if b[0] <= frozen_d]
                                p95, p100 = _calc_95_line(c6, bars_frz, idx_m, frozen_d)
                                cur_c = bars[-1][2]
                                pnl = (cur_c / eo - 1.0) * 100.0
                                if hold_day <= 4:
                                    tracked.append(
                                        f"  • {c6} {nm} | 信号{sd} -> 买日{ed}开{eo:.2f}({gap*100:+.2f}%) | "
                                        f"最新收{cur_c:.2f}(浮盈{pnl:+.2f}%) | {'明日' if is_post_close else '今日'}为第{hold_day}天 | "
                                        f"最紧95%止盈线={p95:.2f}元(100%异动={p100:.2f}元)"
                                    )
        if tracked:
            print("  【近3日已触发五板策略跟踪（第2至4天95%止盈线）】")
            for t in tracked:
                print(t)
    except Exception as e:
        print(f"  [WARN] 五板策略模块运行异常: {e}")


if __name__ == "__main__":
    print_five_board_section()
