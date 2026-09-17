#!/usr/bin/env python3
"""活裁决条目的前提失效检测 — 查"记录写反了", 不是查"记录漏了"

⛔ 为什么需要它(2026-09-17, interview 提出第三档, astock 当日差点中招):
   治理失效有三档, 隐蔽度递增:
     一 没有记录        -> 治理看不见它(事件源反向核对管这个, 见 trade_ledger_diff.py)
     二 记录存在没去取  -> 制造"已学会"的假象
     三 **记录存在且写反了** -> 它带着治理体系的全部权威, **主动把人推向错误动作**
   前两档的失败方式是"什么都没发生"; 第三档的失败方式是"发生了一件错的事, 而且是系统指挥的"。

   ⛔本域实例(2026-09-17 当日): 裁决 #35 的条件文本写着"三日收盘在灾难线63.67下, 必须给出清仓议题",
   而 09-16 收盘 64.14 已经守住线, 连续计数前一天就断了。照条件文本执行 = 在一个不成立的前提上清仓。
   拦住它的是我前一天碰巧补在 intel_log 里的一句"前提已变", **不是任何机制**。

   ⛔同源(interview): 求职库标着某岗位"未投", 而投递确认邮件就在邮箱里, 差点导致对同一岗位重复投递。

**裁决条件文本的特性**: 写下的那一刻是对的, 之后每过一天都在悄悄失效, 而没有任何东西会重新验证它。
这与"status 字段最少被验证却唯一被拿来决定下一步"是同构的。

用法:
  python3 scripts/verdict_premise_check.py            # 全量扫活条目
  python3 scripts/verdict_premise_check.py --strict   # 有可疑项即退出码非零(供定时任务用)
"""
import argparse
import json
import os
import re
import sys

os.environ.setdefault("NO_PROXY", "*")  # ⛔必须在 import requests 之前
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# 条件文本里一旦出现这些词, 就说明它绑定了一个**当时成立、之后可能失效**的事实状态
STATE_WORDS = [
    "三日收盘", "连续2", "连续两", "连续第", "在灾难线下", "线下", "守住", "未破",
    "仍在", "已跌破", "尚未", "当前处于", "目前在",
]
# 价格形态: 两到三位整数带小数, 避免把百分比和年份抓进来
PRICE_RE = re.compile(r"(?<![\d.])(\d{1,4}\.\d{1,2})(?![\d])")
DRIFT_ALERT = 0.15   # 条件里的价位与现价偏离超过这个比例, 值得人看一眼


def load_items():
    p = os.path.join(ROOT, "data", "pending_verdicts.json")
    d = json.load(open(p, encoding="utf-8"))
    items = d["items"] if isinstance(d, dict) else d
    return [x for x in items if str(x.get("status")) == "open"]


def main():
    ap = argparse.ArgumentParser(description="活裁决条目的前提失效检测")
    ap.add_argument("--strict", action="store_true",
                    help="有可疑项即以非零退出码结束(供定时任务判失败)")
    args = ap.parse_args()

    items = load_items()
    codes = sorted({str(x.get("ticker") or x.get("code")) for x in items
                    if re.fullmatch(r"\d{6}", str(x.get("ticker") or x.get("code") or ""))})
    quotes = {}
    if codes:
        import astock_data_layer as adl
        quotes = adl.get_batch_prices(codes)

    st = json.load(open(os.path.join(ROOT, "portfolio_state.json"), encoding="utf-8"))
    held = {p["ticker"]: p for p in st["accounts"]["a_share"]["positions"]}

    flagged = []
    print(f"活条目 {len(items)} 条 · 检查条件文本里的前提是否仍成立\n")
    for it in sorted(items, key=lambda x: str(x.get("due"))):
        tk = str(it.get("ticker") or it.get("code"))
        cond = str(it.get("condition") or it.get("rule") or "")
        q = quotes.get(tk) or {}
        cur = q.get("price")
        reasons = []

        hit_words = [w for w in STATE_WORDS if w in cond]
        if hit_words:
            reasons.append(f"绑定了状态性前提 {hit_words}")

        if cur:
            prices = [float(n) for n in PRICE_RE.findall(cond)]
            # 只看与现价同量级的数字, 滤掉百分比和财务数字
            same_scale = [n for n in prices if 0.2 < n / cur < 5]
            drifted = [n for n in same_scale if abs(n / cur - 1) > DRIFT_ALERT]
            if drifted and len(drifted) == len(same_scale) and same_scale:
                reasons.append(f"条件里所有同量级价位 {same_scale} 都已偏离现价 {cur} 超过 {DRIFT_ALERT:.0%}")

        mark = "⚠️" if reasons else "  "
        pos = f"持{held[tk]['shares']}股" if tk in held else "未持仓"
        print(f"{mark} #{it.get('id')} {tk} due={it.get('due')} 现价={cur} {pos}")
        for r in reasons:
            print(f"     └ {r}")
        if reasons:
            flagged.append((it.get("id"), tk, reasons))

    # ⛔2026-09-17 增强(interview 判据): "不是查条目写得对不对, 是查条目依赖的那个前提今天是否仍成立 ——
    #   前者查文本一致性, 后者**必须重新取一次数**"。
    #   我第一版只做了前者, 并在这里写了"这一步不能自动化"。那个判断下早了:
    #   形如"N日收盘在X下/上"的前提**完全可以自动验证**, 取近N日收盘与X比即可。
    #   ⛔用一个成立的局部结论(有些前提不好解析)覆盖了没验证的整体(所以都不能自动化), 是同日第七次同形。
    resolved = _verify_parseable(flagged, items, quotes)

    print(f"\n需人工确认前提是否仍成立: {len(flagged)} 条")
    if resolved:
        print(f"其中 {len(resolved)} 条已自动取数判定:")
        for rid, verdict, detail in resolved:
            print(f"  #{rid} {verdict} — {detail}")
    if flagged:
        print("⛔ 未能自动判定的, 需读条件原文与今日事实对照。本工具负责的是'该看哪几条', ")
        print("   以及'其中哪几条我已经替你验过了'。")
    if args.strict and flagged:
        sys.exit(len(flagged))


def _verify_parseable(flagged, items, quotes):
    """对形如「N日收盘在X下/上」「收盘跌破X」的前提, 真去取近N日收盘做判定。
    ⛔只判它能判的; 判不了的照旧留给人, 绝不猜。"""
    import urllib.request
    byid = {str(x.get("id")): x for x in items}
    out = []
    pat = re.compile(r"(三|两|2|3|连续)日?收盘(?:仍)?在\s*([\d.]+)\s*(下|上|下方|上方)")
    for fid, tk, _ in flagged:
        it = byid.get(str(fid))
        if not it or not re.fullmatch(r"\d{6}", str(tk)):
            continue
        m = pat.search(str(it.get("condition") or ""))
        if not m:
            continue
        line = float(m.group(2))
        want_below = m.group(3).startswith("下")
        n = {"三": 3, "3": 3, "两": 2, "2": 2}.get(m.group(1), 3)
        try:
            mk = "sh" if tk[0] in "56" else ("bj" if tk[0] in "48" else "sz")
            u = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
                 f"param={mk}{tk},day,,,{n + 3},qfq")
            raw = json.load(urllib.request.urlopen(u, timeout=8))["data"][f"{mk}{tk}"]
            k = raw.get("qfqday") or raw.get("day")
            # ⛔⛔ 剔除当日未走完的那根 bar(2026-09-17 本函数首测即自曝):
            #   腾讯K线在交易时段返回的当日 bar 是**未完成的**, 它的"收盘价"其实是此刻的现价。
            #   首测对北方稀土给出"09-17=36.96", 而那是盘中价 —— 若照此判"今日收盘在线下",
            #   就是拿盘中读数去判一条只认收盘价的线。
            #   ⛔这是 feedback_trigger_close_only 今天第三次同形: 早上 auto_stop_check 拿竞价参考价
            #   判灾难线、上午我写的"拒跑"修法、现在是我为修前两者而新写的脚本自己又违反了它。
            #   **同一天为同一条规则建三道门, 第三道自己犯规。**
            import datetime as _dt
            _now = _dt.datetime.now()
            _today = _now.strftime("%Y-%m-%d")
            _hm = _now.hour * 100 + _now.minute
            _unfinished = (_now.weekday() < 5 and _hm < 1500)
            if _unfinished and k and str(k[-1][0])[:10] == _today:
                k = k[:-1]          # 今天还没收盘, 这根不算数
            closes = [(r[0], float(r[2])) for r in k[-n:]]
            if not closes:
                out.append((fid, "取数失败", "剔除未完成bar后无可用收盘, 仍需人工核"))
                continue
        except Exception as e:
            out.append((fid, "取数失败", f"{type(e).__name__}, 仍需人工核"))
            continue
        hits = [(d, c) for d, c in closes if (c < line) == want_below]
        side = "下" if want_below else "上"
        detail = f"近{n}日收盘 " + " / ".join(f"{d[-5:]}={c:.2f}" for d, c in closes)
        if len(hits) == n:
            out.append((fid, "✅前提仍成立", f"{detail}, 全部在 {line} {side}"))
        else:
            out.append((fid, "⛔前提已失效",
                        f"{detail}, 只有 {len(hits)}/{n} 日在 {line} {side} —— "
                        f"条件文本的前提不再成立, 照它执行会做错事"))
    return out


if __name__ == "__main__":
    main()
