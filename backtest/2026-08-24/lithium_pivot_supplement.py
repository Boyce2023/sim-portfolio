#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补充校验脚本(2026-08-24) —— 附加于 beta_lag_backtest.py 之后跑,专门回答:
  "今天(08-24)才往锂/资源切"这个具体动作,相对锂子主题自己的启动信号滞后多少?
  (beta_lag_backtest.py 把 资源_钨钼稀土锂 当一个篮子处理,07-02的ignition主要由
   钨/稀土(002378/000657)贡献,不代表锂矿子题自己的启动时点 —— 需要拆开验证)

数据源: ak.stock_zt_pool_em (全市场涨停池,东财push2ex,实测仅覆盖约08-04~08-24,
        早于08-04返回空,与beta_lag_backtest.py的实测记录一致,此处再次独立复核)
      + panel_资源_钨钼稀土锂.csv 里锂4只(002240/002466/002460/000155)的up_big历史
        (04-01~08-21,来自ak.stock_zh_a_daily新浪源,beta_lag_backtest.py已生成)
      + 腾讯 qt.gtimg.cn 实时行情(取08-24盘中价,因新浪日线尚无今天收盘数据)
"""
import json
import urllib.request
import pandas as pd
import akshare as ak

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"

# ---- 1. 独立复核 zt_pool_em 历史覆盖边界 + 08-04~08-24逐日金属/电池行业涨停家数 ----
dates = ["20260624","20260701","20260715","20260804","20260805","20260806","20260807",
         "20260810","20260811","20260812","20260813","20260814","20260817","20260818",
         "20260819","20260820","20260821","20260824"]
metal_industries = ["小金属","工业金属","金属新材","贵金属","非金属材","电池","能源金属","有色金属"]
lithium_codes = {"000155": "川能动力", "002240": "盛新锂能", "002466": "天齐锂业", "002460": "赣锋锂业"}

daily_rows = []
for d in dates:
    try:
        df = ak.stock_zt_pool_em(date=d)
    except Exception as e:
        daily_rows.append({"date": d, "error": str(e)})
        continue
    n = len(df) if df is not None else 0
    if n == 0:
        daily_rows.append({"date": d, "total_zt": 0, "metal_related": {}, "lithium_basket_zt": [],
                            "note": "空(验证:该接口早于约08-04无历史)"})
        continue
    codes6 = df["代码"].astype(str).str.zfill(6)
    ind_counts = df["所属行业"].value_counts()
    metal_related = {k: int(v) for k, v in ind_counts.items() if k in metal_industries}
    lith_hits = [lithium_codes[c] for c in codes6 if c in lithium_codes]
    battery_names = df.loc[df["所属行业"] == "电池", ["代码", "名称", "涨跌幅"]].to_dict("records")
    daily_rows.append({
        "date": d, "total_zt": n, "metal_related": metal_related,
        "lithium_basket_zt": lith_hits, "battery_industry_names": battery_names,
    })

# ---- 2. 锂4只自己的up_big历史(来自已有panel,04-01~08-21) ----
panel = pd.read_csv(f"{OUT_DIR}/panel_资源_钨钼稀土锂.csv", index_col=0, parse_dates=True)
lith_upbig = {}
for code in lithium_codes:
    col = f"upbig_{code}"
    if col in panel.columns:
        hits = panel.index[panel[col] == 1]
        lith_upbig[code] = [d.strftime("%Y-%m-%d") for d in hits]

# ---- 3. 今天(08-24)盘中实时价(新浪日线尚无今日收盘,用腾讯行情兜底) ----
codes_live = {
    "000155": "sz000155", "600549": "sh600549", "600111": "sh600111",
    "300408": "sz300408", "600183": "sh600183", "301018": "sz301018", "600312": "sh600312",
}
url = "http://qt.gtimg.cn/q=" + ",".join(codes_live.values())
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    raw = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="ignore")
except Exception as e:
    raw = ""
    print("tencent quote fetch failed:", e)

live_quotes = {}
for line in raw.strip().split(";"):
    line = line.strip()
    if not line:
        continue
    parts = line.split("~")
    if len(parts) < 5:
        continue
    name, price, prev_close = parts[1], parts[3], parts[4]
    try:
        pct = round((float(price) - float(prev_close)) / float(prev_close) * 100, 2)
    except Exception:
        pct = None
    live_quotes[name] = {"price": price, "prev_close": prev_close, "pct_chg_intraday_0824": pct}

out = {
    "purpose": "拆解锂子题自己的启动信号(不与钨/稀土混同),核对08-24实际动作的滞后",
    "zt_pool_em_coverage_check": daily_rows,
    "lithium_4tickers_upbig_history_0401_to_0821": lith_upbig,
    "live_quotes_0824_intraday": live_quotes,
    "caveat": "腾讯行情为08-24盘中快照(非收盘价,当天未走完);新浪日线FETCH_END=20260824时当日尚无收盘行情,"
              "故beta_lag_backtest.py的matched_trades.csv不含任何08-24当天的买入记录(非遗漏,是数据尚未生成)。",
}
with open(f"{OUT_DIR}/lithium_pivot_supplement.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(json.dumps(out, ensure_ascii=False, indent=2))
