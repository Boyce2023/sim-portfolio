#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专项回测: 主线(beta)启动日 vs 我方建仓日的滞后成本
窗口: 2026-06-24 ~ 2026-08-24 (数据抓取延伸到2026-04-01作为burst探测的基线buffer,
      但结论只对2026-06-24~2026-08-24窗口负责)

数据源变更说明(必须写清楚,不能假装按原计划跑通):
  原计划用 ak.stock_zt_pool_em 逐日取全市场涨停池(按行业聚合)。
  实测发现该接口(东财push2ex)只保留最近约2-3周历史(2026-08-24实测: 08-03当天
  返回0条,08-10返回99条,08-17返回106条,08-24返回41条) —— 无法覆盖06-24~08-04这段。
  东财另一域名(17.push2.eastmoney.com,行业板块列表接口)被本机代理挡(ProxyError),
  Tencent web.ifzq.gtimg.cn 返回501(WAF拦截)。
  按铁律4"失败立即换源不要重试": 改用 akshare.stock_zh_a_daily (新浪历史行情,
  全历史可得,已实测098条2026-04~08-21数据,0.4秒/只) 对预先圈定的4条产业链
  "篮子股"逐只取日线,自行判定涨停(主板/中小板±9.8%,创业板/科创板±19.5%)、
  逐日加总篮子内涨停家数,以此重建"主线热度时间序列",替代原计划的全市场
  涨停池聚合。

  这是方法论替代,不是原始需求的完整实现 —— 篮子股是人工圈定的产业链核心
  个股(非全市场普查),存在遗漏个股/概念边界主观的局限,必须明确披露。
"""

import json
import time
import datetime as dt
import akshare as ak
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
PORTFOLIO_STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"

WINDOW_START = "2026-06-24"
WINDOW_END = "2026-08-24"
FETCH_START = "20260401"   # buffer for burst baseline
FETCH_END = "20260824"

# ---- 人工圈定的4条产业链"篮子股"(核心个股,非全市场普查) ----
THEMES = {
    "AI算力_PCB光模块液冷": [
        ("600183", "生益科技"), ("002463", "沪电股份"), ("002916", "深南电路"),
        ("300476", "胜宏科技"), ("002938", "鹏鼎控股"), ("300502", "新易盛"),
        ("300308", "中际旭创"), ("300394", "天孚通信"), ("300408", "三环集团"),
        ("301018", "申菱环境"), ("002837", "英维克"),
    ],
    "资源_钨钼稀土锂": [
        ("600111", "北方稀土"), ("600549", "厦门钨业"), ("000657", "中钨高新"),
        ("002378", "章源钨业"), ("002842", "翔鹭钨业"), ("300748", "金力永磁"),
        ("000831", "中国稀土"), ("002240", "盛新锂能"), ("002466", "天齐锂业"),
        ("002460", "赣锋锂业"), ("000155", "川能动力"), ("603505", "金石资源"),
    ],
    "半导体设备材料": [
        ("002371", "北方华创"), ("688012", "中微公司"), ("688072", "拓荆科技"),
        ("688082", "盛美上海"), ("688019", "安集科技"), ("688206", "概伦电子"),
        ("688627", "精智达"),
    ],
    "氟化工制冷剂": [
        ("600160", "巨化股份"), ("605020", "永和股份"), ("603379", "三美股份"),
        ("600378", "昊华科技"),
    ],
}


def sina_symbol(code):
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh" + code
    return "sz" + code


def limit_threshold(code):
    if code.startswith(("300", "301", "688", "689")):
        return 19.5
    return 9.8


def fetch_ticker(code):
    sym = sina_symbol(code)
    for attempt in range(2):
        try:
            df = ak.stock_zh_a_daily(symbol=sym, start_date=FETCH_START, end_date=FETCH_END, adjust="qfq")
            if df is None or df.empty:
                return None
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            df["pct_chg"] = df["close"].pct_change() * 100
            return df
        except Exception as e:
            print(f"  [retry {attempt}] {code} err: {e}")
            time.sleep(1.5)
    return None


def build_theme_panel(theme_name, tickers):
    frames = {}
    for code, name in tickers:
        df = fetch_ticker(code)
        if df is None:
            print(f"  [WARN] {theme_name} {code} {name} 取数失败,跳过")
            continue
        thresh = limit_threshold(code)
        df["up_big"] = (df["pct_chg"] >= thresh).astype(int)
        frames[code] = df.set_index("date")
        # 存raw
        df.to_csv(f"{OUT_DIR}/raw_{code}_{name}.csv", index=False)
    if not frames:
        return None, {}
    all_dates = sorted(set().union(*[set(f.index) for f in frames.values()]))
    panel = pd.DataFrame(index=all_dates)
    for code, f in frames.items():
        panel[f"upbig_{code}"] = f["up_big"].reindex(all_dates)
        panel[f"pct_{code}"] = f["pct_chg"].reindex(all_dates)
    upbig_cols = [c for c in panel.columns if c.startswith("upbig_")]
    pct_cols = [c for c in panel.columns if c.startswith("pct_")]
    panel["theme_count"] = panel[upbig_cols].sum(axis=1, skipna=True)
    panel["theme_basket_ret_eq"] = panel[pct_cols].mean(axis=1, skipna=True)  # 篮子等权日均涨跌幅(近似)
    return panel, frames


def detect_ignition_and_fade(panel, window_start, window_end):
    """
    启动日(ignition)自动判据 —— 两套规则对比:
      规则A(严格突发): 某日起3日滚动涨停家数总和>=3, 且该日之前10日(不含当日)
                        滚动均值<1 (代表从"安静基线"突然放量)
      规则B(宽松阈值): 单日涨停家数首次>=3 (不看基线)
    退潮日(fade): 突破启动日之后,5日滚动涨停家数总和 从峰值回落到<=峰值的30%,
                  且随后2日不回升到>30%阈值以上(避免单日噪音)
    只在 [window_start, window_end] 区间内寻找ignition/fade候选日
    (基线用window前的数据计算,不受此限制)
    """
    s = panel["theme_count"].fillna(0)
    roll3 = s.rolling(3).sum()
    roll10_prior = s.shift(1).rolling(10).mean()
    roll5 = s.rolling(5).sum()

    mask_window = (panel.index >= pd.Timestamp(window_start)) & (panel.index <= pd.Timestamp(window_end))

    ignition_A = None
    ignition_B = None
    for d in panel.index[mask_window]:
        if ignition_B is None and s.loc[d] >= 3:
            ignition_B = d
        if ignition_A is None and roll3.loc[d] >= 3 and (pd.notna(roll10_prior.loc[d])) and roll10_prior.loc[d] < 1:
            ignition_A = d
        if ignition_A is not None and ignition_B is not None:
            break

    ignition = ignition_A if ignition_A is not None else ignition_B

    fade = None
    peak_val = None
    if ignition is not None:
        post = panel.index[(panel.index >= ignition)]
        post_roll5 = roll5.reindex(post)
        if post_roll5.notna().any():
            peak_val = post_roll5.max()
            peak_date = post_roll5.idxmax()
            after_peak = post_roll5.loc[post_roll5.index >= peak_date]
            thresh = peak_val * 0.30
            below = after_peak[after_peak <= thresh]
            for d in below.index:
                loc = list(after_peak.index).index(d)
                remaining = after_peak.iloc[loc:loc+3]
                if (remaining <= thresh * 1.0).sum() >= min(2, len(remaining)):
                    fade = d
                    break

    return {
        "ignition_strict(A)": ignition_A,
        "ignition_loose(B)": ignition_B,
        "ignition_used": ignition,
        "fade": fade,
        "peak_5d_sum": peak_val,
    }


def load_actual_buys():
    d = json.load(open(PORTFOLIO_STATE))
    tl = d["trade_log"]
    buys = [t for t in tl if t.get("account") == "a_share" and t.get("action") == "buy"]
    return buys


def trading_days_between(panel_index, d1, d2):
    """用面板里的真实交易日index算 d1->d2 之间隔了几个交易日(d2晚于d1为正)"""
    idx = list(panel_index)
    if d1 not in idx or d2 not in idx:
        return None
    return idx.index(d2) - idx.index(d1)


def main():
    results = {}
    lag_records = []

    for theme_name, tickers in THEMES.items():
        print(f"\n=== 拉取篮子: {theme_name} ({len(tickers)}只) ===")
        panel, frames = build_theme_panel(theme_name, tickers)
        if panel is None:
            print(f"  [FAIL] {theme_name} 全部取数失败,跳过该主线")
            continue
        panel.to_csv(f"{OUT_DIR}/panel_{theme_name}.csv")

        ig = detect_ignition_and_fade(panel, WINDOW_START, WINDOW_END)
        results[theme_name] = ig
        print(f"  ignition_strict(A)={ig['ignition_strict(A)']}  ignition_loose(B)={ig['ignition_loose(B)']}"
              f"  fade={ig['fade']}  peak_5d_sum={ig['peak_5d_sum']}")

    # ---- 匹配实际建仓记录 ----
    buys = load_actual_buys()
    theme_ticker_map = {}
    for tname, tickers in THEMES.items():
        for code, name in tickers:
            theme_ticker_map[code] = tname

    matched = []
    for b in buys:
        code = b["ticker"]
        bdate = b["date"]
        if code not in theme_ticker_map:
            continue
        if not (WINDOW_START <= bdate <= WINDOW_END):
            continue
        tname = theme_ticker_map[code]
        if tname not in results or results[tname]["ignition_used"] is None:
            continue
        panel = pd.read_csv(f"{OUT_DIR}/panel_{tname}.csv", index_col=0, parse_dates=True)
        ig_date = pd.Timestamp(results[tname]["ignition_used"])
        b_date_ts = pd.Timestamp(bdate)
        lag = trading_days_between(panel.index, ig_date, b_date_ts)
        if lag is None:
            # 建仓日不在篮子交易日index里(理论不该发生,兜底用最近日)
            continue
        # cost: 篮子等权收益 从ignition到buy_date(错过的), 从buy_date到最新(实际吃到的)
        ret_series = panel["theme_basket_ret_eq"].fillna(0) / 100.0
        cum = (1 + ret_series).cumprod()
        if ig_date in cum.index and b_date_ts in cum.index:
            missed_pct = (cum.loc[b_date_ts] / cum.loc[ig_date] - 1) * 100
        else:
            missed_pct = None
        last_date = cum.index.max()
        if b_date_ts in cum.index:
            captured_pct = (cum.loc[last_date] / cum.loc[b_date_ts] - 1) * 100
        else:
            captured_pct = None
        if ig_date in cum.index:
            total_run_pct = (cum.loc[last_date] / cum.loc[ig_date] - 1) * 100
        else:
            total_run_pct = None

        matched.append({
            "theme": tname,
            "ticker": code,
            "name": b.get("name"),
            "buy_date": bdate,
            "ignition_date": str(ig_date.date()),
            "lag_trading_days": lag,
            "missed_pct_ignition_to_buy": None if missed_pct is None else round(missed_pct, 2),
            "captured_pct_buy_to_now": None if captured_pct is None else round(captured_pct, 2),
            "total_run_pct_ignition_to_now": None if total_run_pct is None else round(total_run_pct, 2),
        })

    # ---- 汇总统计 ----
    df = pd.DataFrame(matched)
    summary = {}
    if not df.empty:
        # 按theme去重: 每条主线只取第一次建仓(最早buy_date)作为"建仓日"代表
        first_entries = df.sort_values("buy_date").groupby("theme").first().reset_index()
        summary["n_theme_first_entries"] = len(first_entries)
        summary["lag_trading_days_all_matched_trades_n"] = len(df)
        if len(df) > 0:
            lag_arr = df["lag_trading_days"].dropna()
            summary["lag_mean_all_trades"] = round(lag_arr.mean(), 1) if len(lag_arr) else None
            summary["lag_median_all_trades"] = round(lag_arr.median(), 1) if len(lag_arr) else None
            summary["lag_p5_p95_all_trades"] = [round(lag_arr.quantile(0.05), 1), round(lag_arr.quantile(0.95), 1)] if len(lag_arr) else None
        if len(first_entries) > 0:
            lag_fe = first_entries["lag_trading_days"].dropna()
            summary["lag_mean_theme_first_entry"] = round(lag_fe.mean(), 1) if len(lag_fe) else None
            summary["lag_median_theme_first_entry"] = round(lag_fe.median(), 1) if len(lag_fe) else None
            miss_fe = first_entries["missed_pct_ignition_to_buy"].dropna()
            summary["missed_pct_mean_theme_first_entry"] = round(miss_fe.mean(), 1) if len(miss_fe) else None

    out = {
        "window": [WINDOW_START, WINDOW_END],
        "ignition_fade_by_theme": {k: {kk: (str(vv) if vv is not None else None) for kk, vv in v.items()} for k, v in results.items()},
        "matched_trades": matched,
        "summary": summary,
        "sample_size_caveat": "主线数n=4(篮子人工圈定,非全市场普查); theme首次建仓样本n={}, 属方向性提示非稳健结论".format(summary.get("n_theme_first_entries", 0)),
    }
    with open(f"{OUT_DIR}/result_beta_lag.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)

    df.to_csv(f"{OUT_DIR}/matched_trades.csv", index=False, encoding="utf-8-sig")

    print("\n\n========== 结果 ==========")
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    print("\n--- matched trades ---")
    if not df.empty:
        print(df.to_string(index=False))
    else:
        print("(无匹配交易)")


if __name__ == "__main__":
    main()
