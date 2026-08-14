## Case: D12 A股数据源(yfinance淘汰)

**情境(06-16数据源审计)**: A股价格/市值/PE/PB用yfinance取数，实测多次出严重错误——宏和科技、鼎泰高科市值少算10倍；生益科技PE报183，实际179。

**规则**: 主脑取A股数据一律用 `astock_data_layer.get_batch_prices`(EM被代理挡时自动tencent兜底)或本地`yf` CLI(已拦截重定向到正确源)。⛔禁止在代码里`import yfinance`直接取A股。派agent取A股数据时，prompt必须显式带这条约束——因为subagent进程不继承主脑的拦截器，会自己import yfinance踩坑。yfinance仅限美股/港股。

**VERIFY**: 数字来自astock_data_layer/tencent；market_cap==0/None时必须先重取再用，不允许在数据缺失时输出估值结论(违反底层"永不用残缺数据给结论"铁律)。
