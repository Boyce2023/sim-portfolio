#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""
A股灾难线自动止损检测器 — auto_stop_check.py

背景 (2026-08-24): 三环集团(300408)和生益科技(600183)双双跌破灾难线-12%,
全靠人肉盯盘才发现并手动清仓。daily_run.sh 里此前没有任何自动止损检测环节。

规则(2026-08-24 T18实证改版后的现行版本): **收盘价** vs avg_cost * 0.88。
  ⛔灾难线已从"执行器"降级为"强制复核触发器": 收盘在线下 = 触发thesis三问强制复核,
    连续2个交易日收盘仍在线下才处理余仓。依据C2(69笔卖出分类): 判断型卖出20日事后
    卖对率87%, 机械型(灾难线+破位)仅36%, 比抛硬币差。
  ⛔旧版表述"绝对地板/破线=无条件出/thesis与催化都不能override"已作废, 勿再引用。
  ⛔口径: 扳机一律收盘价判定(feedback_trigger_close_only)。本脚本取实时价, 因此
    在交易时段内**拒绝运行**(见 _in_trading_hours 与 run_check 入口断言)。

⛔⛔ 只告警,绝不自动下单。执行权永远归人(T0铁律)。本脚本唯一职责是让人
不可能错过 — 破线时打印醒目终端告警 + 写 nexus critical 信号。

价格来源: astock_data_layer.get_batch_prices()（东财主源+腾讯兜底），
⛔ 禁止对A股使用 yfinance（D12铁律）。

用法:
  uv run --script scripts/auto_stop_check.py
  uv run --script scripts/auto_stop_check.py --no-signal
  uv run --script scripts/auto_stop_check.py --verbose

退出码: 破线持仓数量（0 = 全部安全）。非零供 daily_run.sh 感知并在日志汇总中显眼标红。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import astock_data_layer as adl  # noqa: E402 — 唯一合法A股行情入口 + yfinance拦截器

# ── 路径 ─────────────────────────────────────────────────────────────────────
REPO          = Path(__file__).resolve().parent.parent
PORTFOLIO     = REPO / "portfolio_state.json"
NEXUS_SIGNALS = Path.home() / ".claude" / "nexus" / "signals" / "pending"

# ── 灾难线阈值 ─────────────────────────────────────────────────────────────────
DISASTER_LINE_RATIO = 0.88  # avg_cost * 0.88 = 灾难线 (跌破成本-12%)


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def get_a_positions(portfolio: dict) -> list[dict]:
    try:
        return portfolio["accounts"]["a_share"]["positions"]
    except (KeyError, TypeError):
        return []


# ── 信号 ─────────────────────────────────────────────────────────────────────

def _existing_signal_today(ticker: str, today_str: str) -> bool:
    """同一天已经为该ticker发过灾难线信号 → 不重复写，避免每次daily_run都刷屏。"""
    if not NEXUS_SIGNALS.exists():
        return False
    pattern = f"auto_stop_check-disaster-{ticker}"
    for f in NEXUS_SIGNALS.glob(f"sig-{today_str.replace('-', '')}-*"):
        if pattern in f.name:
            return True
    return False


def write_nexus_signal(ticker: str, name: str, price: float, disaster_line: float,
                        avg_cost: float, breach_pct: float) -> Path | None:
    if not NEXUS_SIGNALS.exists():
        try:
            NEXUS_SIGNALS.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    if _existing_signal_today(ticker, today_str):
        return None

    now_iso = now.astimezone(timezone.utc).isoformat()
    exp_iso = (now + timedelta(days=3)).astimezone(timezone.utc).isoformat()
    sig_id = f"sig-{now.strftime('%Y%m%d-%H%M%S')}-auto_stop_check-disaster-{ticker}"

    d = {
        "id": sig_id,
        "from": "auto_stop_check",
        "to": ["trading_astock"],
        "priority": "critical",
        "type": "position_change",
        "title": f"⚠️ 灾难线触发复核 | {name}({ticker}) | 收盘较成本 {breach_pct:+.2f}%",
        "content": (
            f"T18第②门(灾难线)触发: 收盘 ¥{price:.4f} 低于灾难线 ¥{disaster_line:.4f} "
            f"(=成本×{DISASTER_LINE_RATIO})\n"
            f"较成本价跌幅: {breach_pct:+.2f}%\n"
            f"⛔现行规则(2026-08-24 T18实证改版, 取代旧版'绝对地板/无条件出'): "
            f"灾难线**已从执行器降级为强制复核触发器**。触发=当日强制thesis三问复核+减半锁风险; "
            f"**连续2个交易日收盘仍在线下**才清余仓。依据C2(69笔卖出分类): 判断型卖出20日事后卖对率87%, "
            f"机械型(灾难线+破位)仅36%, 比抛硬币差。\n"
            f"⛔本信号只报'今日收盘在线下'这一个事实, 不代表应当卖出, 更不代表应当清仓。"
        ),
        "action_required": (
            f"⛔仅提醒,不自动下单,且**不建议直接清仓**。应做的是: "
            f"①核对该仓 type —— 若为 深研埋伏仓/core_position, 按T15只配基本面证伪止损, "
            f"禁技术扳机, 机械清仓路径不存在(实证: 金盘科技#34于09-15被T15门当场拦下); "
            f"②跑thesis三问(供给约束/主beta/催化剂时间线); "
            f"③三问未坏则持有, 仅在连续第2个交易日收盘仍在线下时才处理余仓; "
            f"④卖出时reason必须写thesis证伪, 写'止损/破位'会被T14/T15门拦。"
        ),
        "source_context": "auto-detect:disaster_line",
        "created_at": now_iso,
        "expires_at": exp_iso,
        "lifecycle": "pending",
        "read_by": [],
        "acted_on": False,
    }
    fname = NEXUS_SIGNALS / f"{sig_id}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    return fname


# ── 主检测逻辑 ──────────────────────────────────────────────────────────────────

def _in_trading_hours(now: datetime | None = None) -> bool:
    """当前是否处于A股交易时段(含09:15起的集合竞价)。"""
    n = now or datetime.now()
    if n.weekday() >= 5:
        return False
    hm = n.hour * 100 + n.minute
    return (915 <= hm <= 1130) or (1300 <= hm <= 1500)


def run_check(*, write_signal: bool = True, verbose: bool = False,
              allow_intraday: bool = False) -> list[dict]:
    # ⛔⛔ 入口硬断言(2026-09-17新增, 治一次险些造成真实损失的假警)
    #   本脚本取的是**实时价**(下方 adl.get_batch_prices), 而扳机一律以**收盘价**判定
    #   (feedback_trigger_close_only)。在交易时段跑 = 拿盘中读数去判一条只认收盘价的线。
    #   ⛔实证一(2026-09-17 09:15:34): daily_run 在集合竞价时段调用本脚本, 取到北方稀土的
    #     **竞价参考价 37.468**, 判定"击穿灾难线37.4725"并写出 critical 信号, 建议 `--all` 清仓。
    #     而 09-16 真实收盘是 37.49, 在线上 +0.047%, 连续线下计数根本没起算。
    #     该仓 6900 股, 若照信号执行就是在一个竞价参考价上清掉一个深研埋伏仓。
    #   ⛔实证二(2026-09-11 同一只): 14:55 读 37.45 在线下, 收盘 37.48 翻回线上,
    #     当时靠人工发现避开, 但**没有变成代码**, 于是六天后原样再来一次。
    #   ⛔所以拦在入口而不是只改取价函数: 取价函数有三级降级路径, 改一处会漏; 入口只有一个。
    #   ⛔⛔ 2026-09-17 二次修正: 第一版我写的是"交易时段直接拒跑", **那是错的修法**。
    #     daily_run 只看退出码, 拒跑会返回 [] 且退出码 0 —— 每日灾难线检查静默跳过,
    #     而输出看起来像"全部安全"。我一边在批"故障降级成语义合法的正常值", 一边自己造了一个。
    #     ⛔正确修法是**换口径不是不跑**: 灾难线只认收盘价, 那么在交易时段就用
    #     **上一交易日收盘价**(行情接口返回的 prev_close 恰好就是它)来判。
    #     门永远有效、口径永远正确; 只有连收盘价都拿不到时才拒跑, 且必须让上游看得见。
    use_prev_close = _in_trading_hours() and not allow_intraday
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    if use_prev_close:
        print(f"\n{'='*70}")
        print("  ⚠️ 当前处于A股交易时段(含集合竞价) — 自动切换为【上一交易日收盘价】口径")
        print(f"{'='*70}")
        print("  理由: 灾难线扳机一律以收盘价判定(feedback_trigger_close_only)。盘中实时价")
        print("        不是扳机口径, 用它判会在竞价参考价上发出清仓级告警。已实证两次:")
        print("        2026-09-11 北方稀土 14:55读37.45在线下/收盘37.48在线上(按盘中动手误杀6800股);")
        print("        2026-09-17 09:15:34 本脚本取竞价参考价37.468判'击穿', 而前一日收盘37.49在线上。")
        print("  ⛔本次判定用的是上一交易日收盘价, 不是今日盘中价, 也不是今日收盘价。")
    print(f"\n{'='*70}")
    print(f"  A股灾难线自动止损检测  |  {now_str}  |  阈值: avg_cost × {DISASTER_LINE_RATIO}")
    print(f"{'='*70}")

    portfolio = load_json(PORTFOLIO)
    positions = get_a_positions(portfolio)

    if not positions:
        print("  无A股持仓，退出。")
        return []

    tickers = [p.get("ticker", "") for p in positions if p.get("ticker")]
    print(f"\n持仓: {len(positions)} 只 | 正在拉取实时价格 (astock_data_layer/eastmoney+tencent)...")

    try:
        live_prices = adl.get_batch_prices(tickers)
    except Exception as e:
        print(f"  ⚠️ 批量取价失败: {e}，尝试逐只降级")
        live_prices = {}

    breaches: list[dict] = []
    rows: list[tuple] = []

    skipped = []          # 2026-09-08: 漏检的必须收集, 否则最后那行绿勾会把'没检查'说成'安全'
    for pos in positions:
        ticker   = pos.get("ticker", "")
        name     = pos.get("name", ticker)
        avg_cost = pos.get("avg_cost")

        if not avg_cost or avg_cost <= 0:
            print(f"  ⚠️ [{ticker}] {name}: 无avg_cost，跳过")
            skipped.append((ticker, name, "无avg_cost"))
            continue

        # ⛔取价口径由 use_prev_close 决定(见上方入口说明): 交易时段取上一交易日收盘价,
        #   非交易时段取 price(盘前=上一交易日收盘, 盘后=当日收盘, 两者都是合法的收盘口径)。
        _field = "prev_close" if use_prev_close else "price"
        live = live_prices.get(ticker, {})
        price = live.get(_field)

        # 降级: 批量接口没拿到就单独重试一次
        if price is None:
            try:
                single = adl.get_single_price(ticker)
                price = single.get(_field)
            except Exception:
                price = None

        # 再降级: 用portfolio_state.json里update_prices.py写入的缓存
        #   ⛔交易时段只认缓存里的 prev_close; 绝不用 current_price 兜底 ——
        #   那是盘中价, 用它兜底等于绕开了本次修正, 又回到在竞价参考价上判灾难线。
        if price is None:
            price = pos.get("prev_close") if use_prev_close else pos.get("current_price")
            if price and verbose:
                print(f"  [{ticker}] 实时取价失败，降级用portfolio_state.json缓存的{_field} ¥{price}")

        if price is None:
            print(f"  ⛔ [{ticker}] {name}: 无法获取{_field}(实时+缓存均失败)，无法判断灾难线，需人工检查！")
            skipped.append((ticker, name, f"取{_field}全部失败"))
            continue

        disaster_line = round(avg_cost * DISASTER_LINE_RATIO, 4)
        breach_pct = round((price - avg_cost) / avg_cost * 100, 2)
        dist_to_disaster_pct = round((price - disaster_line) / disaster_line * 100, 2)
        breached = price <= disaster_line

        rows.append((ticker, name, avg_cost, price, disaster_line, breach_pct, dist_to_disaster_pct, breached))

        if verbose:
            status = "🚨 破线" if breached else "  安全"
            print(f"  [{status}] {ticker} {name}: 现价¥{price:.2f} | 成本¥{avg_cost:.2f} "
                  f"| 灾难线¥{disaster_line:.2f} | 距灾难线{dist_to_disaster_pct:+.2f}%")

        if breached:
            breaches.append({
                "ticker": ticker, "name": name, "avg_cost": avg_cost,
                "price": price, "disaster_line": disaster_line, "breach_pct": breach_pct,
                # ⛔2026-09-17: 带上仓位性质。T15规定埋伏/深研/core仓只配基本面证伪止损、
                #   禁技术扳机, 对这类仓给"清仓"建议本身就是错的建议(实证: 金盘科技#34
                #   2026-09-15 09:30:05 的机械清仓单被T15门当场拦下)。告警必须据此分档措辞。
                "ptype": str(pos.get("type") or ""),
            })

    # ── 汇总表 ─────────────────────────────────────────────────────────────────
    print(f"\n{'─'*70}")
    print(f"  {'代码':<8}{'名称':<10}{'成本':>10}{'现价':>10}{'灾难线':>10}{'较成本%':>10}{'距灾难线%':>12}")
    print(f"{'─'*70}")
    for (ticker, name, avg_cost, price, disaster_line, breach_pct, dist_pct, breached) in rows:
        mark = " 🚨" if breached else ""
        print(f"  {ticker:<8}{name:<10}{avg_cost:>10.2f}{price:>10.2f}{disaster_line:>10.2f}"
              f"{breach_pct:>+9.2f}%{dist_pct:>+11.2f}%{mark}")
    print(f"{'─'*70}")

    # ── 醒目告警 ───────────────────────────────────────────────────────────────
    if breaches:
        print("\n")
        print("⚠️ " * 23)
        print("  灾难线触发【强制复核】— 不是清仓指令 (T18 2026-08-24实证改版)")
        print("")
        for b in breaches:
            # ⛔显示4位小数: 原来打印 :.2f, 于是灾难线37.4725与价格37.4683在屏幕上
            #   都显示成 37.47, 看起来像"相等却判跌破"。我2026-09-17就是被这一行误导,
            #   把真因误诊成"舍入伪影", 读码后才发现真因是取价口径(用了盘中竞价参考价)。
            print(f"  {b['ticker']} {b['name']}: 收盘¥{b['price']:.4f} < 灾难线¥{b['disaster_line']:.4f} "
                  f"(较成本{b['breach_pct']:+.2f}%)")
            if b.get("ptype") in ("深研埋伏仓", "core_position", "catalyst_position"):
                print(f"      ⛔该仓 type={b['ptype']}, 按T15只配基本面证伪止损、禁技术扳机。")
                print(f"        机械清仓路径对它不存在, 不要下机械止损单(会被T15门拦, 实证: 金盘科技#34)。")
        print("")
        print("  现行规则(取代旧版'绝对地板/无条件出'): 灾难线已从执行器降级为**强制复核触发器**。")
        print("    ①今日收盘在线下 = 触发thesis三问强制复核, 不等于卖出")
        print("    ②连续2个交易日收盘仍在线下, 才处理余仓")
        print("    ③依据C2(69笔卖出分类): 判断型卖出20日事后卖对率87%, 机械型仅36%, 比抛硬币差")
        print("  ⛔不要用 --all 清仓, 也不要在reason里写'止损/破位' —— 那会被T14/T15门拦下,")
        print("    且机械型卖出的事后正确率是全部卖出类型里最低的。卖出须写thesis证伪。")
        print("⚠️ " * 23)
        print("\n")

        if write_signal:
            written = []
            for b in breaches:
                fpath = write_nexus_signal(
                    b["ticker"], b["name"], b["price"], b["disaster_line"],
                    b["avg_cost"], b["breach_pct"],
                )
                if fpath:
                    written.append(fpath)
            if written:
                print(f"  [nexus] 已写入 {len(written)} 个critical信号:")
                for p in written:
                    print(f"    {p.name}")
            else:
                print(f"  [nexus] 今日已发过信号（或写入失败），未重复写入")
    elif skipped:
        # ⛔2026-09-08: 原实现无论漏检多少都打绿勾, len(rows)是"检查成功几只"不是"总共几只"。
        # 极端情况全部取价失败 → rows为空 → 打印"✅ 全部 0 个持仓安全"。
        # "0个持仓安全"与"没有持仓破线"在措辞上是同一个绿勾, 而这里判的是-12%灾难线(T18绝对地板)。
        print("\n" + "⛔" * 35)
        print(f"⛔  检查不完整: {len(positions)} 只持仓中 {len(skipped)} 只未能判定灾难线")
        for tk, nm, why in skipped:
            print(f"⛔    {tk} {nm} — {why}")
        print(f"⛔  已检查的 {len(rows)} 只中无击穿, 但这**不构成全仓安全结论**, 未检查的需人工确认")
        print("⛔" * 35)
    elif not rows:
        print("\n" + "⛔" * 35)
        print("⛔  零只持仓完成检查 — 这不是'安全', 是**检查根本没跑成*")
        print("⛔" * 35)
    else:
        print(f"\n✅  无灾难线击穿 — 全部 {len(rows)}/{len(positions)} 个持仓均已检查且安全")

    print(f"\n{'='*70}\n")
    return breaches


def main() -> None:
    parser = argparse.ArgumentParser(description="A股灾难线自动止损检测(avg_cost×0.88)")
    parser.add_argument("--no-signal", action="store_true", help="不写入 nexus signals/pending/")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示每只持仓详细检测过程")
    # ⛔2026-09-17 补注册: 本参数此前只出现在 run_check 的签名和一条打印提示里,
    #   argparse 从未注册它 —— 提示告诉用户"传 --allow-intraday", 实跑却报 unrecognized arguments。
    #   ⛔同一起事故 execute_trade.py 的注释里早就记过一次(--skip-aggression-gate 从未注册,
    #   是不存在的逃生舱)。记录存在而我没去取, 于是在写下来的坑上原样再踩。
    #   判据: **在错误提示里提到任何开关或绕过方式之前, 先实跑一次确认它存在。**
    #   错误提示是最少被测试的代码路径, 却恰好是人在慌乱时唯一会读的东西。
    parser.add_argument("--allow-intraday", action="store_true",
                        help="盘中改用实时价判定(默认在交易时段自动改用上一交易日收盘价, "
                             "因为灾难线扳机只认收盘价)。⛔仅供人工查看当前盘中位置, "
                             "不要据此下单: 盘中越线与收盘越线是两回事, 已实证两次。")
    args = parser.parse_args()

    breaches = run_check(write_signal=not args.no_signal, verbose=args.verbose,
                         allow_intraday=args.allow_intraday)
    sys.exit(len(breaches))


if __name__ == "__main__":
    main()
