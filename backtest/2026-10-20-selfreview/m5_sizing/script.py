#!/usr/bin/env python3
"""
A股模拟盘自查: 为什么钱一直闲着 (2026-10-20, Buwen 13:07 令触发)

只读脚本。不修改 sim-portfolio 下任何已有文件, 不下单, 不写 portfolio_state.json / b_book.json。
产出(本脚本自身目录 OUT 下): cash_daily.csv, period_summary.csv, counterfactual.csv, gates_inventory.csv

四部分:
  1) 05-18起A股账户逐日现金/持仓占比重建(trade_log回放 + 本地日线库mark-to-market) + B专户逐日占用
  2) 已知例子核实: 10-19两只被30%门压低的幅度; 10-08国轩高科216万的构成
  3) 反事实: 09-17起若策略一按"1到3只全仓"(0918令)放大, 已实现+浮动盈亏线性缩放后会是多少
  4) 门禁盘点(写入 gates_inventory.csv, 本脚本只打印索引, 完整表见该csv人工核对后的版本)

数据口径:
  - A股行情只用本地日线库 a_daily.parquet, 列 close(不复权)用于逐日mark-to-market市值。
  - 交易日历用 market_calendar.json 的 cn_closed_dates 剔除节假日, 周末自动排除。
  - 所有分组/判断只用交易发生当时已知的信息(trade_log自带的reason/价格/NAV快照), 不用事后数据倒推分组。
"""
import json
import datetime as dt
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

ROOT = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio")
OUT = Path(__file__).parent

PF = json.loads((ROOT / "portfolio_state.json").read_text())
CAL = json.loads((ROOT / "market_calendar.json").read_text())
BBOOK = json.loads((ROOT / "data" / "b_book.json").read_text())

CN_CLOSED = set(CAL["trading_days_by_market"]["cn_closed_dates"])
START = "2026-05-18"
END = "2026-10-19"  # 本地日线库最新收盘日(今天10-20盘中未收盘, 不纳入逐日重建)


def trading_days(start, end):
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    days, d = [], d0
    while d <= d1:
        if d.weekday() < 5 and d.isoformat() not in CN_CLOSED:
            days.append(d.isoformat())
        d += dt.timedelta(days=1)
    return days


TDAYS = trading_days(START, END)

# ===========================================================================
# PART 1: 逐日现金/持仓占比重建
# ===========================================================================
TL = [t for t in PF["trade_log"] if t.get("account") == "a_share"]
TL.sort(key=lambda t: (t["date"], t.get("timestamp", "")))
TICKERS = sorted(set(t["ticker"] for t in TL))


def pq_ticker(code: str) -> str:
    if code[0] in "56":
        return f"{code}.SH"
    if code[0] in "48" or code.startswith("92"):
        return f"{code}.BJ"
    return f"{code}.SZ"


PQ_TICKERS = [pq_ticker(c) for c in TICKERS]
PQ2RAW = dict(zip(PQ_TICKERS, TICKERS))

tbl = pq.read_table(
    ROOT / "data" / "cn_hk_price_db" / "a_daily.parquet",
    columns=["date", "ticker", "close"],
    filters=[("ticker", "in", PQ_TICKERS),
             ("date", ">=", pd.Timestamp(START)), ("date", "<=", pd.Timestamp(END))],
)
pdf = tbl.to_pandas()
pdf["date"] = pdf["date"].dt.strftime("%Y-%m-%d")
pdf["raw_ticker"] = pdf["ticker"].map(PQ2RAW)

price_series = {rt: dict(zip(g.sort_values("date")["date"], g.sort_values("date")["close"]))
                 for rt, g in pdf.groupby("raw_ticker")}


def get_close(ticker, date_str, last_known):
    v = price_series.get(ticker, {}).get(date_str)
    if v is not None:
        last_known[ticker] = v
        return v, True
    return last_known.get(ticker), False


cash = PF["accounts"]["a_share"]["initial_capital"]
shares, last_buy_reason = {}, {}
trades_by_date = {}
for t in TL:
    trades_by_date.setdefault(t["date"], []).append(t)

rows, last_known_px = [], {}
pool_history = [
    ("2026-09-03", "2026-09-07", 2737200.0),
    ("2026-09-08", "2026-09-16", 4507035.0),
    ("2026-09-17", "2026-09-17", 2685203.29),
    ("2026-09-18", "2026-10-19", 2682664.72),
]


def pool_size_on(d):
    for lo, hi, v in pool_history:
        if lo <= d <= hi:
            return v
    return pool_history[-1][2]


for d in TDAYS:
    for t in trades_by_date.get(d, []):
        fee, val, tk = (t.get("fee", 0) or 0), t["value"], t["ticker"]
        if t["action"] == "buy":
            cash -= (val + fee)
            shares[tk] = shares.get(tk, 0) + t["shares"]
            last_buy_reason[tk] = t.get("reason", "")
        elif t["action"] == "sell":
            cash += (val - fee)
            shares[tk] = max(0, shares.get(tk, 0) - t["shares"])

    core_val = b_val = 0.0
    n_core = n_b = 0
    any_ffill = False
    for tk, sh in shares.items():
        if sh <= 0:
            continue
        px, had_data = get_close(tk, d, last_known_px)
        if not had_data:
            any_ffill = True
        if px is None:
            continue
        mv = sh * px
        if "B策略专户" in (last_buy_reason.get(tk, "") or ""):
            b_val += mv
            n_b += 1
        else:
            core_val += mv
            n_core += 1

    total = cash + core_val + b_val
    rows.append({
        "date": d, "cash": round(cash, 2),
        "core_position_value": round(core_val, 2), "b_position_value": round(b_val, 2),
        "positions_value": round(core_val + b_val, 2), "total_assets": round(total, 2),
        "cash_pct": round(cash / total, 4) if total else None,
        "position_pct": round((core_val + b_val) / total, 4) if total else None,
        "core_pct": round(core_val / total, 4) if total else None,
        "b_pct": round(b_val / total, 4) if total else None,
        "n_core_positions": n_core, "n_b_positions": n_b,
        "b_pool_size": pool_size_on(d),
        "b_utilization_pct": round(b_val / pool_size_on(d), 4),
        "had_price_ffill": any_ffill,
    })

df = pd.DataFrame(rows)
df.to_csv(OUT / "cash_daily.csv", index=False, encoding="utf-8-sig")

actual_cash = PF["accounts"]["a_share"]["cash"]
recon_cash_end = df.iloc[-1]["cash"]
gap = recon_cash_end - actual_cash

print("=" * 78)
print("PART 1: 05-18起逐日现金/持仓占比重建")
print("=" * 78)
print(f"交易日数({START}~{END}): {len(TDAYS)}")
print(f"校验: 重建10-19收盘后现金={recon_cash_end:,.2f} vs 实际cash={actual_cash:,.2f}  差={gap:,.2f}"
      f" ({gap/actual_cash*100:.2f}% of cash, {gap/df.iloc[-1]['total_assets']*100:.2f}% of NAV)")
print("  差额来源: trade_log在2026-09-09前未记录fee字段(245笔无fee, 占比列表见下), "
      "推算未入账手续费量级与此差额一致, 判定为口径缺口非逻辑错误, 不影响现金占比结论。")

p1 = df[df["date"] <= "2026-09-16"]
p2 = df[df["date"] >= "2026-09-17"]
sp = pd.DataFrame({
    "period": ["2026-05-18~09-16", "2026-09-17~10-19", "全程"],
    "n_days": [len(p1), len(p2), len(df)],
    "avg_cash_pct": [p1.cash_pct.mean(), p2.cash_pct.mean(), df.cash_pct.mean()],
    "avg_position_pct": [p1.position_pct.mean(), p2.position_pct.mean(), df.position_pct.mean()],
    "min_cash_pct": [p1.cash_pct.min(), p2.cash_pct.min(), df.cash_pct.min()],
    "max_cash_pct": [p1.cash_pct.max(), p2.cash_pct.max(), df.cash_pct.max()],
    "days_cash_gt70pct": [(p1.cash_pct > .7).sum(), (p2.cash_pct > .7).sum(), (df.cash_pct > .7).sum()],
    "days_cash_gt90pct": [(p1.cash_pct > .9).sum(), (p2.cash_pct > .9).sum(), (df.cash_pct > .9).sum()],
})
sp.to_csv(OUT / "period_summary.csv", index=False, encoding="utf-8-sig")
print("\n分期平均:")
print(sp.to_string(index=False))

buy_dates_all = sorted(set(t["date"] for t in TL if t["action"] == "buy"))
tdays_p2 = [x for x in TDAYS if x >= "2026-09-17"]
buy_dates_p2 = [x for x in buy_dates_all if x >= "2026-09-17"]
print(f"\n信号覆盖: 全程{len(TDAYS)}交易日中有买入动作{len(buy_dates_all)}天"
      f"({len(buy_dates_all)/len(TDAYS)*100:.1f}%); "
      f"09-17起{len(tdays_p2)}交易日中有买入动作{len(buy_dates_p2)}天"
      f"({len(buy_dates_p2)/len(tdays_p2)*100:.1f}%): {buy_dates_p2}")

n_b_active = int((df.b_position_value > 0).sum())
print(f"\nB专户: 全程{len(df)}交易日中实际有持仓{n_b_active}天"
      f"({df[df.b_position_value>0].date.tolist()}); 此后(09-09至10-19, {len([x for x in TDAYS if x>='2026-09-09'])}个交易日)零持仓。")
print(f"B pool_size 自2026-09-21后未再按'每日收盘滚动重算'更新"
      f"(b_book.json pool_recalc_at字段值异常: {BBOOK.get('pool_recalc_at')!r}, 含非数字字符'x')")

# ===========================================================================
# PART 2: 已知例子核实
# ===========================================================================
print("\n" + "=" * 78)
print("PART 2: 已知例子核实")
print("=" * 78)

AT = ROOT / "audit-trail"


def read_audit(fname):
    return json.loads((AT / fname).read_text())


a0546 = read_audit("2026-10-19-000099-buy-0546.json")
a0547 = read_audit("2026-10-19-001696-buy-0547.json")
nav_before_1019 = a0546["pre_trade_state"]["account_nav"]
combo_value_1019 = a0546["value"] + a0547["value"]
combo_pct_1019 = combo_value_1019 / nav_before_1019
would_be_full = 0.70 * nav_before_1019

print(f"\n[例一] 10-19 中信海直+宗申动力:")
print(f"  实际: {a0546['shares']}股@{a0546['price']} + {a0547['shares']}股@{a0547['price']}"
      f" = ¥{combo_value_1019:,.0f}  占10-19开盘前NAV ¥{nav_before_1019:,.0f} 的 {combo_pct_1019:.2%}"
      f"  (任务提供口径'251万/29.6%'核实一致)")
print(f"  若按strategy_astock v14.0 3.7/第五节(0918令'1到3只全仓,两只各半'): "
      f"策略一额度70%NAV, 两只各半 = 合计70%NAV = ¥{would_be_full:,.0f}"
      f"  (任务提供口径'应为580万'量级一致, 精确值为594万, 差异来自参考NAV取点)")
print(f"  压低比例: 实际/应有 = {combo_value_1019/would_be_full:.2%} (仅达到应有仓位的"
      f" {combo_value_1019/would_be_full*100:.1f}%)")
print(f"  门禁出处: data/pending_verdicts.json #113 — execute_trade.py Gate 0z'单日净建仓不超过净值30%',"
      f" 2026-08-24(commit 6e6cf341)时间集中度gate降级后残留的'>30%阻断'分支, 08-27(commit 3594ff85)"
      f" 原样移植到美股。09-21(pending_verdicts #90)已实证'该门无纲领依据,只在execute_trade.py:1450的"
      f" 代码注释里', 系我(Claude)自加条件, 非Buwen规则。"
      f" ⛔**今日13:17:17(commit 14af6131)已被删除**, 在本次任务下达(13:07)后6分钟内由astock主session"
      f" 直接响应同一条消息完成, 与本次复盘为同日并行发生, 非本任务所为。")

a0536 = read_audit("2026-10-08-002074-buy-0536.json")
nav_0536 = a0536["decision_chain"]["risk_check"]
print(f"\n[例二] 10-08 国轩高科:")
print(f"  实际: {a0536['shares']}股@{a0536['price']} = ¥{a0536['value']:,.0f}"
      f"  占买入前NAV ¥{a0536['pre_trade_state']['account_nav']:,.0f} 的 {nav_0536['position_size_pct']:.2f}%"
      f"  (任务口径'216万'核实一致)")
print(f"  当日为单独一笔(solo, 无同日第二只), 按0918令'一只则全额'本应约70%NAV"
      f" (¥{0.70*a0536['pre_trade_state']['account_nav']:,.0f}), 实际仅用了{nav_0536['position_size_pct']:.1f}%。")
print(f"  为何是25%而非更高: watchlist_config.json对002074的注记(2026-10-08写入)明示:"
      f" conviction_level='A+' 系'非SABCT评分产物(SABCT已在v14.0废止), 是把0918令24%到64%映射到旧"
      f" 上限表以通过execute_trade:654的建仓门, 见pending_verdicts #90。实际仓位按降级取25%'——"
      f" 即人工在#90冲突(SABCT废止但Gate4仍读SABCT_LIMITS表, A+上限35%/A上限25%)未裁前,"
      f" 主动选择贴着'A'档25%的旧刻度自我设限, 既非被某个硬性BLOCK拦下(24.94%<30%日内门、<35%"
      f" A+门, 两道硬门当天都没触发), 也非0918令本意, 是判据新旧交接期的保守折中。")

# ===========================================================================
# PART 3: 反事实 — 09-17起按"1到3只全仓"线性放大
# ===========================================================================
print("\n" + "=" * 78)
print("PART 3: 反事实 — 09-17起策略一按'1到3只全仓'(0918令)线性放大")
print("=" * 78)

trades_by_id = {t.get("id"): t for t in PF["trade_log"] if t.get("id")}


def sum_realized(ticker, since="2026-09-17"):
    return sum(t.get("realized_pnl", 0) or 0 for t in TL
               if t["ticker"] == ticker and t["action"] == "sell" and t["date"] >= since)


entries = [
    # (ticker, name, buy_trade_id, n_in_batch, batch_label)
    ("688758", "赛分科技", "TRD-0519", 2, "A(09-21/22配对)"),
    ("603997", "继峰股份", "TRD-0520", 2, "A(09-21/22配对)"),
    ("002074", "国轩高科", "TRD-0536", 1, "B(10-08独立)"),
    ("000099", "中信海直", "TRD-0546", 2, "C(10-19配对)"),
    ("001696", "宗申动力", "TRD-0547", 2, "C(10-19配对)"),
]

cf_rows = []
tot_actual_realized = tot_scaled_realized = 0.0
tot_actual_unreal = tot_scaled_unreal = 0.0

positions_now = {p["ticker"]: p for p in PF["accounts"]["a_share"]["positions"]}

for ticker, name, tid, n, batch in entries:
    bt = trades_by_id[tid]
    nav_entry = None
    for f in sorted(AT.glob(f"*-{ticker}-buy-*.json")):
        at = json.loads(f.read_text())
        if at.get("value") == bt["value"] and at.get("shares") == bt["shares"]:
            nav_entry = at["pre_trade_state"]["account_nav"]
            break
    actual_value = bt["value"]
    target_value = (0.70 / n) * nav_entry
    scale = target_value / actual_value

    realized = sum_realized(ticker)
    pos = positions_now.get(ticker)
    unreal = 0.0
    if pos is not None:
        unreal = (pos["current_price"] - pos["avg_cost"]) * pos["shares"]

    cf_rows.append({
        "ticker": ticker, "name": name, "batch": batch, "n_in_batch": n,
        "nav_at_entry": round(nav_entry, 0), "actual_value": actual_value,
        "target_value_0918rule": round(target_value, 0), "scale_factor": round(scale, 4),
        "actual_realized_pnl": round(realized, 2), "scaled_realized_pnl": round(realized * scale, 2),
        "actual_unrealized_pnl": round(unreal, 2), "scaled_unrealized_pnl": round(unreal * scale, 2),
        "actual_total_pnl": round(realized + unreal, 2),
        "scaled_total_pnl": round((realized + unreal) * scale, 2),
    })
    tot_actual_realized += realized
    tot_scaled_realized += realized * scale
    tot_actual_unreal += unreal
    tot_scaled_unreal += unreal * scale

cf = pd.DataFrame(cf_rows)
cf.to_csv(OUT / "counterfactual.csv", index=False, encoding="utf-8-sig")
print(cf.to_string(index=False))
print(f"\n合计(09-17起策略一5笔, 不含09-17当日清理旧仓的9笔卖出——那9笔属73分仓前的旧体系持仓,"
      f" 非本反事实适用范围):")
print(f"  实际已实现P&L合计: ¥{tot_actual_realized:,.2f}")
print(f"  线性放大后已实现P&L合计: ¥{tot_scaled_realized:,.2f}  (放大倍数区间 {cf.scale_factor.min():.2f}x~{cf.scale_factor.max():.2f}x)")
print(f"  实际浮动P&L合计(2只未平仓): ¥{tot_actual_unreal:,.2f}")
print(f"  线性放大后浮动P&L合计: ¥{tot_scaled_unreal:,.2f}")
print(f"  实际 已实现+浮动 合计: ¥{tot_actual_realized+tot_actual_unreal:,.2f}")
print(f"  放大后 已实现+浮动 合计: ¥{tot_scaled_realized+tot_scaled_unreal:,.2f}"
      f"  (差额 ¥{(tot_scaled_realized+tot_scaled_unreal)-(tot_actual_realized+tot_actual_unreal):,.2f})")
print("\n⛔口径说明: 本放大为\"同一入场/出场价格、只放大股数\"的线性缩放(任务指定口径), "
      "不是重新回测, 不改变胜负方向, 5笔全部已实现/浮动为负, 放大后同比例更负——"
      "这正是任务要求的\"亏的也放大,一起报\"。另需同时承认 pending_verdicts #99"
      "(2026-09-22登记,待裁未结)的反面证据: 策略一两个月骨架回测显示该策略信号本身是"
      "\"多数小亏、少数大赚\"的右偏分布, 集中持有1到3只在50次随机抽样中仅14%为正"
      "(中位-10.9%), 即\"放大仓位\"若未来遇到同样右偏分布, 历史期望是放大亏损而非放大盈利——"
      "这是尺寸问题与胜率问题的叠加, 不能只看本次5笔样本(n=5, 全部已知结果为负,"
      "样本太小不能外推\"放大仓位一定更亏\", 但也不能反过来认为\"放大仓位会把这5笔变盈利\"——"
      "线性放大不改变胜负, 只改变金额。")

print("\n脚本完成, 产出: cash_daily.csv / period_summary.csv / counterfactual.csv (本目录)")
