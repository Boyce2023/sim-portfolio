# 宏观Tracker注册表 — Phase 2 (2026-06-16)

> 系统每日开盘前自动跑"第一判断"的数据蓝图。yf+FRED双源。


# Master注册表 + Dashboard规格(CURATE)

这是一个纯架构设计任务,我已有全部9类扫描输入,不需要再拉数据或调工具。直接合成交付。

---

# Master Tracker 注册表 + 每日 Macro Dashboard 蓝图

宏观第一判断层。设计原则:真触发优先、可自动化优先、yf能拉的进日级、FRED日频靠`fred_macro.py`、月频官方数据做确认不做择时。

---

## 1. Master Tracker 注册表(分层)

### 日级 — 每天开盘前必拉(自动化)

**A. yf 可直接拉(实时/盘中,morning check 首选)**

| # | Tracker | 命令 | 什么值=什么信号 | 权重 |
|---|---------|------|----------------|------|
| 1 | HYG/LQD 盘中比值 | `yf quote HYG LQD JNK` | 比值下行+HYG放量暴跌=信用 risk-off 实时前哨(领先 FRED OAS 一天) | ★★★前哨 |
| 2 | 10Y 名义 | `yf price ^TNX` | 看速度:单周>30bp=利率冲击 | ★★ |
| 3 | 曲线代理 10Y-3M | `yf price ^TNX` − `^IRX` | 转负=衰退预警;倒挂后转正(^IRX暴跌)=危机临近 | ★★★ |
| 4 | 短端 2Y 路径 | `yf price ^IRX`(13wk代理) | 单月跌>50bp=市场抢跑降息/危机 | ★★ |
| 5 | VIX 期限结构 | `yf price ^VIX9D ^VIX ^VIX3M` → 算 VIX9D/VIX、VIX/VIX3M | 比率>1=backwardation=真实压力(领先信用利差);<1=calm | ★★★本类最强 |
| 6 | VIX 现货 | `yf price ^VIX` | 默认降权(噪音);>50=反向买点触发器 | 噪音/触发 |
| 7 | VVIX / SKEW / MOVE | `yf price ^VVIX ^SKEW ^MOVE` | VVIX>110 或 VIX低VVIX高背离=尾部保护抢购;MOVE>120=债市应激(领先股VIX) | ★★ |
| 8 | 铜金比 | `yf price HG=F GC=F` → 相除+5日Δ | 快速下行=增长塌方/避险(领先股市拐点,验证信用方向) | ★★★ |
| 9 | USDJPY | `yf price JPY=X` | 3日内升>3-4%=carry unwind/全球去杠杆(尾部触发器) | ★★★尾部 |
| 10 | DXY/油/金 面板 | `yf macro` | 背景读数:DXY急升=美元流动性收紧;油持续突破=通胀链 | ★辅助 |
| 11 | RSP/SPY 广度 | `yf history RSP SPY 1y` → Close相除 | 比值创新低+SPY新高=广度背离(熊前兆);跌破200dma=黄灯 | ★★ |

**B. FRED 日频(`fred_macro.py`,收盘后 T+1,非 yf)**

| # | Tracker | FRED 代码 | 什么值=什么信号 | 权重 |
|---|---------|-----------|----------------|------|
| 12 | **HY OAS** | `BAMLH0A0HYM2` | <300平静/300-500警戒/500-1000降仓/**>1000=极端真触发**。日变>+50bp=管道转向 | ★★★#1领先 |
| 13 | IG OAS | `BAMLC0A0CM` | <100正常/>200=信用周期转向(盘子大,系统意义>HY) | ★★ |
| 14 | HY-IG 质量利差 | 12−13 自算 | 急速走阔=质量逃离(早于HY水平突破) | ★★ |
| 15 | CCC OAS | `BAMLH0A3HYC` | >1500bp=违约潮预期(HY领先确认) | ★★ |
| 16 | **10Y 实际利率** | `DFII10` | <0资产友好/>2%警戒/**1月升>50bp=真触发**(杀高久期/SOXL) | ★★★最高 |
| 17 | 10Y Breakeven | `T10YIE` | 1.8-2.5锚定/>2.8上行=通胀预期失锚 | ★★ |
| 18 | 5Y5Y 长期锚 | `T5YIFR` | 破2.5%=真失锚(Fed最看重) | ★★ |
| 19 | **SOFR-EFFR / SOFR-IORB** | `SOFR`/`EFFR`/`IORB` | SOFR持续>IORB+20bp 或 SOFR-EFFR>10bp 连3日=回购冻结(真触发,FX管道最早尖叫) | ★★★真触发 |
| 20 | TGA 余额 | `WTREGEN` | 激增=财政抽水(隐性紧缩) | ★ |
| 21 | ON RRP 余额 | `RRPONTSYD` | 耗尽至~0=缓冲垫没了,QT真正抽准备金(领先WRESBAL承压) | ★★ |

### 周级 — 每周固定拉

| # | Tracker | 源 | 节奏 | 什么值=什么信号 | 权重 |
|---|---------|----|----|----------------|------|
| 22 | **初请失业金 ICSA(MA4)** | FRED `ICSA`+`CCSA` | 周四08:30 | MA4>300k且加速上行=衰退裂缝(最早硬数据) | ★★★周频最优 |
| 23 | **准备金余额 WRESBAL** | FRED `WRESBAL` | 周四H.4.1 | 跌破~3.0万亿=准备金稀缺区(当前~3.08万亿,贴警戒) | ★★★硬约束 |
| 24 | Fed 总资产 WALCL | FRED `WALCL` | 周四H.4.1 | 连续两周转正且非临时工具=QT结束/政策逆转 | ★★ |
| 25 | NFCI / ANFCI | FRED `NFCI`/`ANFCI` | 周三 | 穿0并加速上行=系统性收紧确认(滞后,做确认) | ★确认 |
| 26 | **AAII Bear%** | aaii.com | 周四 | **>50%=反向买点(配VIX>50)** | ★★★反向 |
| 27 | CBOE Put/Call | cboe.com $CPC/$CPCE | 日(周扫) | Total>1.0-1.2=极度恐慌(反向);<0.7=自满 | ★★反向 |
| 28 | BofA FMS 现金水平 | WebSearch 月报 | 月中(周扫转引) | >5%=机构防御极致(反向买);<4%=自满sell | ★★机构定位 |
| 29 | 盈利修正广度 NERI | FactSet/Yardeni | 周 | 由正转负+加速=下修潮启动(D8:仅预期定位,不进估值链) | ★★盈利侧 |
| 30 | Breadth Thrust(Zweig) | Stockcharts $NYAD | 日扫 | 10日adv占比<0.40→>0.615=罕见强多确认(零假信号) | ★★★稀有正向 |

### 月级 — 官方数据(确认,不择时)

| # | Tracker | 源 | 什么值=什么信号 | 权重 |
|---|---------|----|----------------|------|
| 31 | **Core PCE YoY** | FRED `PCEPILFE` | Fed反应函数唯一真输入。>3%上行=鹰派/估值杀;趋2%=鸽派。看二阶导 | ★★★最该盯通胀 |
| 32 | Sticky CPI | FRED `STICKCPIM157SFRBATL` | 上行=结构性通胀(比headline难逆转) | ★★ |
| 33 | **Sahm Rule** | FRED `SAHMREALTIME` | **≥0.50=衰退触发(历史100%准)** | ★★★ |
| 34 | **ISM New Orders**(+S&P Flash) | ISM官方/WebSearch | New Orders−Inventories 掉头跌破50=盈利拐点(领先6-12月)。Flash早一周 | ★★★最强领先 |
| 35 | GDPNow | atlantafed xlsx | 季末读+2%骤降转负=失速实时确认(季初噪音大别当真) | ★★ |
| 36 | EBP 超额债券溢价 | Fed FEDS Notes | +1σ以上=信用收缩真信号(月度滞后,做确认) | ★★ |
| 37 | 两融余额+涨跌停炸板率 | akshare | A股散户杠杆/情绪极端=全球risk-on见顶交叉佐证(二阶,低权重) | 低/二阶 |

---

## 2. 每日 Macro Dashboard 规格(Phase3 脚本蓝图)

**执行流程(开盘前 cron):**

```
Step 1  yf 批量拉(实时):  ^TNX ^IRX ^VIX ^VIX9D ^VIX3M ^VVIX ^SKEW ^MOVE
        HG=F GC=F JPY=X HYG LQD JNK   +  yf macro
Step 2  fred_macro.py(收盘后T+1,日频缓存):
        BAMLH0A0HYM2 BAMLC0A0CM BAMLH0A3HYC DFII10 T10YIE T5YIFR
        SOFR EFFR IORB RRPONTSYD WTREGEN
Step 3  算衍生:  VIX9D/VIX, VIX/VIX3M, 铜金比+5日Δ, 10Y-3M, HY-IG质差,
        SOFR-IORB, HYG/LQD, RSP/SPY vs 200dma
Step 4  每周四叠加: ICSA(MA4) WRESBAL WALCL ; 每周三 NFCI
Step 5  Regime 引擎: 给方向(risk-on/neutral/risk-off) + 程度 + 距硬触发距离
Step 6  写 truth/macro/daily_regime.json + 一屏输出
```

**Regime 引擎逻辑(5 域投票):**

| 域 | 读数 | risk-on | neutral | risk-off |
|----|------|---------|---------|----------|
| 信用 | HY OAS | <400 | 400-600 | >600/日变>50bp |
| 实际利率 | DFII10 水平+1月Δ | <1.5%稳 | 1.5-2% | >2% 或 月升>50bp |
| 融资管道 | SOFR-IORB | <0 | 0-10bp | >20bp连3日 |
| 增长 | 铜金比5日Δ + 曲线 | 上行+曲线正 | 持平 | 急跌/倒挂转正 |
| 波动结构 | VIX/VIX3M | <0.95 | 0.95-1.0 | >1.0 backwardation |

方向=多数票;程度=触发域数(0平静/1-2警觉/3+收紧/4-5系统性);另列**反向买点闸**:VIX>50 且 AAII Bear>50 → 独立绿灯。

**一屏输出样板:**

```
═══ MACRO REGIME  2026-06-15 08:15 ET ═══
方向: RISK-ON (4/5域绿)  程度: 平静  反向闸: 未触发

信用     HY OAS 271bp ↓     [<300绿] 距硬触发1000bp = -729bp
实际利率 DFII10 2.05% →     [警戒] 距>2%已破, 月Δ+8bp未加速
管道     SOFR-IORB +2bp     [绿] 距触发20bp = -18bp
增长     铜金比 ↑1.2% / 曲线+正  [绿]
波动     VIX 17.7 / VIX9D÷VIX 0.96 contango  [绿]
─────────────────────────────────────
硬触发距离: 全部安全, 最近的是 DFII10(已在警戒水位, 盯月升速)
持仓含义: 信用绿灯+曲线正, growth/SOXL 无估值杀压力, 维持攻击仓位
周频待更: ICSA MA4 / WRESBAL(贴3.0万亿警戒) — 周四看
```

---

## 3. 硬触发监控清单(百年校准真触发)

| 真触发 | Tracker | 当前值(扫描期) | 触发阈值 | 触发后动作 |
|--------|---------|---------------|----------|-----------|
| **信用利差极端** | HY OAS `BAMLH0A0HYM2` | 271bp | >1000bp(或日变>+50bp预警) | 系统性事件确认→防御/清杠杆;500-1000先降仓 |
| **融资管道冻结** | SOFR-IORB / SOFR-EFFR | SOFR 3.65% 贴EFFR | SOFR>IORB+20bp 连3日 / SOFR-EFFR>10bp | 2019回购危机翻版→立即降risk |
| **政策真逆转+通胀失锚** | Core PCE YoY `PCEPILFE` + 5Y5Y `T5YIFR` | (月频) | Core PCE连3月加速>4%年化 且 T5YIFR破2.5% | 估值杀确认→减高久期 |
| **实际利率转正加速** | DFII10 | ~2.05% | >2% 且 1月升>50bp | 杀growth引擎启动→减SOXL/科技/长久期 |
| **曲线倒挂(中期)** | T10Y3M / 2Y速度 | (盯) | 倒挂后转正 + 2Y单月跌>50bp | 衰退临近→降risk+备VIX>50反向买点 |
| **衰退确认(双印证)** | Sahm `SAHMREALTIME` + ICSA MA4 | (月/周) | Sahm≥0.50 或 ICSA MA4>300k加速 | 满仓→防御 |
| **尾部去杠杆** | USDJPY | (盯) | 3日内日元升>3-4% | carry unwind→全球去杠杆,降beta |
| **反向买点(攻)** | VIX + AAII Bear | VIX 17.7 | VIX>50 且 AAII Bear>50% | 独立绿灯→加仓 |

每项 dashboard 输出"当前值 + 距阈值距离",让系统每天量化"离悬崖多远"。

---

## 4. 精选取舍(纳入/不纳入,no silent cap)

**不纳入或降为背景的(附理由):**

- **CPI headline / NFP / 零售当日 surprise** → 市场秒级 price in,属噪音。只盯趋势(Core PCE 二阶导)和 nowcast,不盯单月头条。
- **官方 GDP(GDPC1)** → 滞后确认无 alpha,GDPNow 已替代领先功能。
- **名义利率水平(^TNX/^TYX 绝对值)** → 校准明确:水平是噪音,只看速度。降为辅助。
- **VIX 现货当主指标** → 最有名但默认降权,只在>50升级为反向触发器。期限结构信号强10x。
- **高盛 GS FCI** → 无免费API,NFCI 高度相关免费替代,不为它建专有源。
- **NY Fed ACM 期限溢价** → 需爬xlsx自建parser,B级辅助,周度手动够,不进日级自动管道。
- **CME FedWatch 概率** → 无官方概率API,周度WebSearch+FOMC/CPI当天补,不进日级。
- **%above-200dma / NH-NL / AD线原生值** → Stockcharts专有symbol,yf全FAIL(实测),信号与RSP/SPY同族。RSP/SPY自动化替代,其余周级人工背景核对。
- **SLOOS 信贷标准** → 季频太慢,仅背景确认。
- **II 投顾 / EPFR 资金流** → 付费,二手引用即可。
- **雪球/股吧词频/李大霄** → 需自建NLP无现成API,不入系统;李大霄当情绪极值彩蛋。
- **白银/天然气/VXN/OVX/GVZ** → 分板块辅助,随 yf macro 顺手,不单独盯。

**关键架构结论:** yf **无法**拉任何 FRED/BLS/BEA 官方序列(只有市场行情)。真触发核心数据(HY OAS、DFII10、SOFR、ICSA)全在 FRED → 必须建独立 `fred_macro.py`(免费API key,稳定无限流)+ `gdpnow_fetch.py`(curl xlsx),与 yf 市场proxy层并行。这是 Phase3 两条独立管道,不要试图塞进 yf。

---

## 5. 中文/散户情绪源定位

**用法:逆向,二阶/间接,默认低权重,不进美股建仓主链。**

- **因果链弱**:A股散户情绪 → 中国 risk appetite → 仅外溢到中概/港股/挂华美股(KWEB/BABA/PDD),对纯美股标的无直接因果。
- **校准归类**:属"情绪/估值/单日波动"噪音家族,非"信用/融资/实际利率"真触发家族。
- **正确用法**:当两融余额+新增开户**同时极端亢奋**(如2026年1月开户环比+89%、两融2.58万亿同比+41%)→ 作为"全球散户 risk-on 见顶"的**交叉佐证之一**,配合美股自身 VIX/AAII 使用;**单独出现不构成美股动作**。
- **天天盯(仅A股session/中概相关时)**:两融融资余额(akshare日,中国版margin debt)+ 涨跌停炸板率/连板高度(akshare日,游资情绪最高频,顶部退潮先于指数)。
- **权重**:dashboard 中列为单独"二阶情绪"栏,不参与5域 regime 投票,只在中概持仓时升权。
- 李大霄式定性 → 情绪极值彩蛋,永不入系统输入。

---

**交付小结:** 注册表共37项分日/周/月三层(日级19项,其中yf自动11+FRED日频10,周级9,月级7+1二阶);Dashboard 5域投票引擎给方向+程度+距硬触发距离;8项硬触发量化监控;Phase3 需建 `fred_macro.py`+`gdpnow_fetch.py` 两条独立管道(yf拉不到官方数据是硬约束)。所有"当前值"来自各扫描线程的实测读数,标注为扫描期(2026-06-12~16),实盘部署时主session需跑一次 yf+FRED 校准格式。


---

# 9类数据源广扫明细


## 官方美国数据 (FRED / BLS / BEA / Fed)
**trackers**: 核心原则: 官方数据本身是"已发布的滞后事实", 真正的alpha不在数字本身(市场秒级price in), 而在①数字vs预期的surprise ②趋势的二阶导(加速/减速) ③GDPNow这类实时nowcast领先官方GDP。按百年校准映射, 这一类里真正高权重的是"通胀失锚"和"实际利率转正", 其余多为noise-prone。

=== A. 通胀 (最高权重, 连"政策真逆转+通胀失锚"触发) ===

1) CPI 总体 | FRED: CPIAUCSL (SA, index) / CPIAUCNS (NSA) | 月度, BLS每月约第10-13个交易日 08:30 ET发布 | 来源: https://fred.stlouisfed.org/series/CPIAUCSL ; 日历 https://www.bls.gov/schedule/news_release/cpi.htm
2) Core CPI (ex food&energy) | FRED: CPILFESL | 月度 | 同上。信号映射: Core CPI MoM年化>4%且连续3月加速 = 通胀失锚预警(真触发); 0.2-0.3% MoM = 正常; 减速 = 降息窗口打开
3) PCE 总体 | FRED: PCEPI | 月度, BEA月底约第4周 08:30 ET | https://fred.stlouisfed.org/series/PCEPI
4) Core PCE (美联储2%锚定目标) | FRED: PCEPILFE | 月度 | https://fred.stlouisfed.org/series/PCEPILFE ; 日历 https://www.bea.gov/news/schedule。信号: Core PCE YoY = Fed反应函数的真正输入。>3%且上行=鹰派/估值杀; 趋向2%=鸽派窗口。这是最该盯的单一通胀读数
5) CPI细分(粘性): Sticky Price CPI | FRED: STICKCPIM157SFRBATL (亚特兰大联储) | 月度 | 信号: 粘性通胀=趋势核心, 比headline更难逆转, 上行=结构性通胀(真信号)

=== B. 就业 (NFP, 中权重, surprise驱动短期波动) ===

6) NFP 非农就业 | FRED: PAYEMS (level) | 月度, BLS每月第一个周五 08:30 ET | https://fred.stlouisfed.org/series/PAYEMS ; 日历 https://www.bls.gov/schedule/news_release/empsit.htm。信号: 看MoM变化(净增就业)。<+50k或负=衰退信号(配合曲线倒挂=真触发); 月度surprise vs consensus驱动当日波动(noise除非极端)
7) 失业率 | FRED: UNRATE | 月度 | https://fred.stlouisfed.org/series/UNRATE。信号: Sahm Rule(三月均值较前12月低点+0.5pp=衰退已开始)是高权重领先信号
8) Sahm Rule实时值 | FRED: SAHMREALTIME | 月度 | https://fred.stlouisfed.org/series/SAHMREALTIME。≥0.50 = 衰退触发(历史100%准确, 真信号, 直接连"该不该满仓")
9) 初请失业金 (周频领先) | FRED: ICSA | 周度, 每周四 08:30 ET | https://fred.stlouisfed.org/series/ICSA。信号: 4周均值>375k且上行=劳动市场转弱(领先NFP), 周频高刷新率使其成为最快的就业领先指标
10) 平均时薪 (薪资通胀) | FRED: CES0500000003 | 月度(随NFP) | YoY>4%=薪资-通胀螺旋风险

=== C. 增长 (GDP滞后, GDPNow领先=本类最高alpha) ===

11) GDPNow (亚特兰大联储实时nowcast) | 来源: https://www.atlantafed.org/cqer/research/gdpnow (有CSV/JSON下载, 非FRED) | 每周多次更新 | ★本类最该盯: 在官方GDP发布前6-8周就给实时季度GDP估计。信号: GDPNow从+2%骤降转负=衰退实时预警(领先官方季度GDP一个季度)
12) 官方实际GDP | FRED: GDPC1 (chained 2017$) | 季度, BEA, 三次估计(advance/second/third) | https://fred.stlouisfed.org/series/GDPC1。连续两季环比负=技术性衰退(滞后确认, 非领先)
13) 纽约联储 Nowcast / Weekly Economic Index | FRED: WEI | 周度 | https://fred.stlouisfed.org/series/WEI。周频GDP代理, 实时增长温度计

=== D. 消费/生产 (中低权重, 趋势确认用) ===

14) 零售销售 | FRED: RSAFS (total) / RSXFS (ex-auto) | 月度, Census约月中 08:30 ET | https://fred.stlouisfed.org/series/RSAFS。Control group MoM转负且连续=消费走弱
15) 工业产出 | FRED: INDPRO | 月度, Fed | https://fred.stlouisfed.org/series/INDPRO。制造业产出, 配合ISM读周期位置
16) 产能利用率 | FRED: TCU | 月度 | 通胀供给侧压力代理
17) 个人收入&支出 | FRED: PI / PCE | 月度(随PCE物价同发) | 实际支出趋势

=== E. 政策利率/实际利率 (高权重, 连"实际利率转正加速"真触发) ===

18) 联邦基金有效利率 | FRED: DFF | 日度 | https://fred.stlouisfed.org/series/DFF
19) ★ 10年期TIPS实际利率 | FRED: DFII10 | 日度 | https://fred.stlouisfed.org/series/DFII10。★高权重真触发: 实际利率从负转正且加速上行 = 估值压缩引擎启动(2022年杀growth的元凶)。>2%且上行=对长久期/高估值股最大压力
20) 5y5y远期通胀预期 | FRED: T5YIFR | 日度 | https://fred.stlouisfed.org/series/T5YIFR。市场对通胀失锚的实时定价, >2.5%且上行=通胀预期脱锚(真信号)

注: B-就业的NFP当日surprise、D-消费的单月波动多属noise(默认降权), 除非触及极端阈值(Sahm触发/初请破375k趋势)。真正连"满仓vs防御"决策的是A-Core PCE趋势、C-GDPNow拐点、E-实际利率方向、就业的Sahm Rule。

**可自动拉**: ⛔ 关键结论: yf(Yahoo Finance)无法直接拉任何FRED/BLS/BEA官方series — yf只覆盖Yahoo的市场行情(价格/PE/VIX/UST收益率/商品)。官方宏观数据全部不在yf范围内。

可自动化路径(推荐建独立FRED拉取器, 不依赖yf):
- ★最优: FRED API (https://api.stlouisfed.org/fred/series/observations?series_id=CPILFESL&api_key=KEY&file_type=json) — 免费key, 覆盖上述所有FRED代码(CPIAUCSL/CPILFESL/PCEPILFE/PAYEMS/UNRATE/SAHMREALTIME/ICSA/GDPC1/WEI/DFII10/T5YIFR/INDPRO/RSAFS等)。Python: pip install fredapi, Fred(api_key).get_series('PCEPILFE')。这是本类唯一靠谱的自动化方案
- GDPNow: 亚特兰大联储有CSV端点 https://www.atlantafed.org/-/media/documents/cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx — 可自动下载解析
- 发布日历(判断"upcoming vs released"): BLS schedule页 + BEA schedule页, 需自己维护或抓 https://www.bls.gov/schedule/ 。⚠️ Trigger Q7时区铁律: 全部08:30 ET发布, session用CST时换算确认是否已release

必须WebSearch/手动的部分:
- "数字vs consensus surprise" — FRED只给actual值, 不给市场预期。consensus预期(Bloomberg/Investing.com economic calendar)必须WebSearch或第三方API, 这是短期市场反应的真正驱动, FRED拉不到
- 当日发布的即时解读/市场反应 — WebSearch补

建议: 这一类不要塞进yf, 单独建 fred_macro.py(FRED API) + gdpnow_fetch.py, 用cron按发布日历定时拉。yf留给市场proxy层(实际利率DFII10可yf拉TIP/TLT做代理, 但精确值用FRED)。

**精选**: 天天/逢发布必盯的精选(2个):

1) ★ Core PCE YoY (FRED: PCEPILFE) — 这是美联储反应函数的唯一真正输入, 直接决定"加息/降息/维持"=决定growth股估值的折现率。盯它不是为了知道通胀, 是为了预判Fed下一步。月度发布, 趋势二阶导(加速/减速)比绝对值更重要。连百年校准"政策真逆转+通胀失锚"高权重触发。

2) ★ GDPNow (亚特兰大联储, 非FRED) — 本类唯一的真·领先指标。官方GDP(GDPC1)是滞后确认无alpha, 但GDPNow在季度GDP发布前6-8周就实时给估计, 每周多次更新。拐点(如+2.5%骤降转负)=衰退实时预警, 直接连"满仓vs防御"的仓位决策。配合Sahm Rule(SAHMREALTIME≥0.5)双确认衰退, 是这一类里最该天天扫的两个读数。

排除理由: NFP/CPI headline/零售当日surprise虽热闹但多属noise(市场秒级price in), 除非触及极端阈值(Sahm触发/初请破375k趋势/Core PCE连3月加速)。盯趋势和nowcast, 不盯单月头条。


## 利率与实际利率 (Rates & Real Rates)
**trackers**: 广扫后的最优tracker清单, 按"百年校准真触发"权重排序:

【A级 — 真触发信号 (高权重)】

1. 10Y实际利率 (DFII10, 10Y TIPS yield) ★最高权重★
- 来源: FRED代码 DFII10 (https://fred.stlouisfed.org/series/DFII10)
- 刷新: 日 (收盘后~下午更新), 盘中可用yf代理 ^TNX-T10YIE推算
- 信号映射: 这是校准里"实际利率从负转正加速"的核心读数。<0%=金融抑制/资产友好; 0~1%=中性; >2%且1个月内升幅>50bp=★真触发, 杀估值(尤其高久期成长股/SOXL类). 2022年DFII10从-1%冲到+1.7%=纳指-33%的根因. 当前(06-16)约2.0-2.1%区间.
- 注意: 不是名义利率涨就杀估值, 是实际利率涨才杀. 名义涨+breakeven涨(通胀预期)对成长股伤害小.

2. 10Y Breakeven通胀预期 (T10YIE)
- 来源: FRED代码 T10YIE (=DGS10 - DFII10), 也有5Y的 T5YIE / 5Y5Y的 T5YIFR
- 刷新: 日
- 信号映射: 校准里"通胀失锚"的市场读数. 稳定区间1.8-2.5%=锚定良好. >2.8%且上行=通胀预期失锚警告(配合政策逆转=真触发). <1.5%=通缩/衰退预期. 5Y5Y(T5YIFR)是美联储最看重的长期锚, 它破2.5%才算真失锚.

3. 收益率曲线 10Y-2Y / 10Y-3M (倒挂)
- 来源: FRED T10Y2Y (10Y-2Y) 和 T10Y3M (10Y-3M, NY Fed衰退模型用这个); yf可代理: ^TNX减^IRX(近似10Y-3M)
- 刷新: 日 (yf代理实时)
- 信号映射: 校准里"曲线倒挂(中期信号)". T10Y3M转负=未来12-18月衰退概率显著上升(命中率最高的单一指标). 关键: 倒挂本身是中期预警不是卖点; "倒挂后转正(bull steepening, 短端暴跌)"才是衰退临近的真触发. 2022-2023深度倒挂, 2024转正.

4. 短端政策利率代理 (^IRX 13周T-bill / FRED DGS2 2Y)
- 来源: yf ^IRX (已验证, 当前3.618%); FRED DGS2(2Y国债)
- 刷新: ^IRX实时(日内), DGS2日
- 信号映射: 2Y是市场对未来2年Fed路径的定价. 2Y快速下行(>50bp/月)=市场抢跑降息=衰退/危机临近(校准"政策真逆转"前兆). 2Y/^IRX见顶回落=加息周期结束信号.

【B级 — 期限溢价/结构 (中权重, 辅助判断)】

5. NY Fed ACM Term Premium (10Y期限溢价)
- 来源: NY Fed网站 (https://www.newyorkfed.org/research/data_indicators/term-premia-tabs), 下载ACMTP10. 注意: 无FRED单独代码, 需爬NY Fed的xlsx/csv
- 刷新: 日 (NY Fed每日更新, 但需手动/脚本拉)
- 信号映射: 期限溢价从负转正且加速=债券供给/财政担忧驱动的"坏的利率上行"(2023 Q4 10Y冲5%即此). 正且快升=对风险资产更危险, 因为不是增长驱动. 长期为负=养老/海外配置压制, 利率上行可控.

6. 名义10Y/5Y/30Y (^TNX/^FVX/^TYX)
- 来源: yf ^TNX(4.469%)/^FVX(4.188%)/^TYX(4.971%) — 全部已验证
- 刷新: 实时(日内)
- 信号映射: 主要看"速度"不是"水平". 10Y单周升幅>30bp=利率冲击, 历史上常伴随股市回调. ^TYX(30Y)>5%且上行=长端财政/期限溢价警报. 水平本身不构成真触发(校准: 利率水平是噪音, 实际利率加速+曲线结构才是触发).

【C级 — 政策路径预期 (中权重, 拐点用)】

7. CME FedWatch 降息概率
- 来源: https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html (网页, 基于Fed Funds期货). 数据底层=ZQ期货, yf无直接概率字段
- 刷新: 实时(随期货跳动)
- 信号映射: 校准"政策真逆转"的前瞻定价. 市场从"加息/不变"快速转向"年内3+次降息"=抢跑衰退. 关键拐点: 概率分布在1-2周内剧烈左移=危机模式(2019.7, 2024.9降息预期). 单纯1次降息预期波动=噪音.

8. SOFR / SOFR-OIS spread (融资管道, 跨类但利率端可监控)
- 来源: FRED SOFR; 紧张度看 SOFR vs EFFR(FRED EFFR)利差
- 刷新: 日
- 信号映射: 这条本属"融资管道"类(LIBOR-OIS/回购), 但短端利率session里可顺手监控. SOFR突然跳升/SOFR-EFFR走阔=回购市场流动性紧张(2019.9回购危机翻版)=★真触发. 平时贴合EFFR=正常.

**可自动拉**: 【能yf自动拉 — 已全部验证】
- 名义收益率: `yf price ^TNX` (10Y=4.469%) / `yf price ^FVX` (5Y) / `yf price ^TYX` (30Y) / `yf price ^IRX` (13周bill=3.618%) — 实时, 直接读percent
- `yf macro` 一条命令含UST yields总览 (morning check首选)
- 曲线代理: `yf price ^TNX` 减 `yf price ^IRX` ≈ 10Y-3M倒挂; ^TNX减2Y需另取2Y(yf无干净2Y ticker, ^FVX是5Y不是2Y)
- 历史/速度判断: `yf history ^TNX 1mo --json` 算月度升幅(>30-50bp=冲击)

【必须FRED拉 (脚本可自动化, 非yf) — 核心真触发数据在这里】
- DFII10 (10Y实际利率) ★最重要★, T10YIE (breakeven), T5YIFR (5Y5Y长期锚), T10Y2Y/T10Y3M (曲线), DGS2 (2Y), SOFR/EFFR
- 自动化方式: FRED有免费API (fredapi/pandas-datareader), 建议写个fred_pull.py按代码批量拉, 日频缓存. 不能用yf但完全可自动化, 优先级应高于很多yf项因为DFII10是这一类最高权重读数.

【必须手动/爬网 (无干净API)】
- NY Fed ACM Term Premium (ACMTP10): 爬 newyorkfed.org 的csv, 每日更新, 可脚本化但需自建parser
- CME FedWatch降息概率: 网页工具, 无官方概率API. 自动化路径=拉ZQ(Fed Funds)期货自己算隐含概率, 或WebSearch读当前概率. 建议每周WebSearch一次+重大事件(FOMC/CPI)当天补.

**精选**: 天天盯的精选1-2个:

【第1 — DFII10 (10Y实际利率)】这一类唯一最该天天盯的. 理由: 百年校准里"实际利率从负转正加速"是少数几个真触发之一, 且它是杀美股估值(尤其高久期成长股/科技/SOXL类持仓)最直接的传导变量. 2022年纳指-33%、2018 Q4回调根因都是实际利率冲击, 不是名义利率也不是VIX. 盯法: 看水平(>2%进入警戒)+速度(1个月升>50bp=减高久期仓). 必须FRED拉, 盘中可用 ^TNX - T10YIE 代理.

【第2 — 曲线 T10Y3M + 短端2Y速度】理由: 曲线是命中率最高的衰退领先指标, 而"倒挂后bull steepening(2Y暴跌、曲线快速转正)"是衰退/降息周期真正启动的信号, 比FedWatch更早更硬. 盯法: T10Y3M转正过程+2Y单月跌幅>50bp=危机模式预警, 触发降risk+找VIX>50反向买点.

其余 (名义^TNX/^TYX/期限溢价/FedWatch) 周度看即可, 水平本身是噪音, 只在"速度异常"或FOMC/CPI事件日升级为实时盯.


## 信用利差 (Credit Spreads) — 宏观第一判断层 #1领先指标
**trackers**: 广扫后确定的最优tracker清单(分3组: 利差水平/超额溢价/融资管道压力)。所有FRED代码+ETF proxy均已实测验证(2026-06-16)。

【组1: 利差水平 — 核心日度引擎】
1. HY OAS — ICE BofA US High Yield Index OAS ★★★最高权重
   • 来源: FRED `BAMLH0A0HYM2`
   • CSV直拉(无需API key): https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2
   • 刷新: 日更(收盘后, T+1早晨)。实测当前值 2.71%(271bp, 截至06-12), 即极度宽松/risk-on
   • 信号映射(百年校准): <300bp=平静 / 300-500bp=警戒 / 500-1000bp=承压(降仓) / ⛔>1000bp(>10%)=极端真触发, 历史每次>1000bp都对应衰退/系统性事件(08年GFC~2000bp, 20年3月~1100bp, 22年最高~600bp)。日变动>+50bp单日=管道转向预警

2. IG OAS — ICE BofA US Corporate Index OAS
   • 来源: FRED `BAMLC0A0CM`。实测 0.74%(74bp, 06-12)
   • 刷新: 日更。信号: <100bp正常 / 100-150bp警戒 / >200bp=信用周期转向(IG动比HY动更具系统意义, 因IG盘子大、被动持有多)

3. HY-IG质量利差(衍生, 自算) = BAMLH0A0HYM2 − BAMLC0A0CM ≈ 当前197bp
   • 刷新: 日更(两序列相减)。信号: 急速走阔=risk-off向低质量蔓延, 比单看HY更早识别"质量逃离"

4. CCC OAS(尾部最敏感) — FRED `BAMLH0A3HYC`
   • 刷新: 日更。CCC是HY里最脆弱层, 先于HY整体走阔。>1500bp=违约潮预期。作为HY的领先确认

【组2: EBP超额债券溢价 — 去掉违约预期后的"纯风险偏好"】
5. EBP(Gilchrist-Zakrajšek Excess Bond Premium) ★高权重、学术金标准
   • 来源: 美联储理事会(Federal Reserve Board)发布, 月度Excel/CSV: https://www.federalreserve.gov/econresdata/notes/feds-notes/2016/ (Favara et al. updated series) — ⛔非FRED, 需手动/WebFetch下载
   • 刷新: 月更(滞后约2-3周)
   • 信号: EBP是"剥离了基本面违约风险后的债券溢价", >0且上升=投资者风险厌恶上升(纯情绪/信用收缩前兆), 是衰退最好的单一预测变量之一(GZ论文)。+1个标准差以上=信用收缩真信号。⚠️月度+滞后, 做确认不做实时

【组3: 融资管道压力 — 是否"冻结"(真触发, 最高权重档)】
6. SOFR利差 / 回购压力 — LIBOR已退役, 现用 SOFR vs EFFR 或 SOFR-IORB
   • 来源: FRED `SOFR`(实测 3.65%, 06-12) + `EFFR` + `IORB`。NY Fed也发SOFR百分位
   • 刷新: 日更(NY Fed每早8am ET发前一日)。信号: SOFR持续>IORB或SOFR 99th百分位飙升=回购市场缺准备金(类19年9月回购危机)。SOFR-EFFR走阔=短端融资紧张
7. 隔夜逆回购/准备金 — FRED `RPONTSYD`(逆回购用量) + `WRESBAL`(准备金余额)
   • 刷新: 日/周。信号: 准备金快速枯竭→回购利率易尖峰, 提前预警管道脆弱
8. (传统对照)TED/LIBOR-OIS已废弃: LIBOR 2023年6月停发, 不再可用; 历史回测用 FRED `TEDRATE`(已停更)

【ETF实时proxy — yf唯一能自动拉的, 用于盘中抢先于FRED日更】
9. HYG(iShares HY, 实测$80.04) / JNK(SPDR HY) / LQD(iShares IG) / 衍生 HYG/LQD比值
   • 来源: yf quote HYG/JNK/LQD。刷新: 实时(交易时段)
   • 信号: HYG盘中暴跌+成交量放大=信用risk-off的实时前哨, 领先FRED OAS一天。HYG/LQD比值下行=HY相对IG走弱(质量逃离)。⚠️ETF含久期+流动性噪音, 只做方向预警, 水平判断仍以FRED OAS为准

**可自动拉**: 【yf能自动拉(实时, 实测通过)】仅ETF proxy: `yf quote HYG`/`yf quote JNK`/`yf quote LQD`。yf macro覆盖Treasury/VIX/2-10利差, 但⛔不含任何OAS信用利差序列。

【yf不能拉, 但可全自动化(curl FRED CSV, 无需API key, 实测通过)】所有OAS核心序列:
 • curl -s "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2" (HY OAS)
 • 同法换id: BAMLC0A0CM(IG) / BAMLH0A3HYC(CCC) / SOFR / EFFR / IORB
 • ⚠️注意: 短时间内连发多个请求会触发FRED bot防护(返回JS而非CSV), 实测EFFR/RPONTSYD被限流。建议每请求间隔2-3秒, 或申请免费FRED API key走 api.stlouisfed.org/fred/series/observations 更稳。建议封装成 credit_spread.py 脚本日更入Truth Store(truth/macro/credit_spreads.json)

【必须手动/WebFetch】EBP超额债券溢价: 美联储FEDS Notes月度Excel, 非FRED, 需WebFetch federalreserve.gov下载。月度+滞后, 做月度确认即可

**精选**: 天天盯1-2个:
① HY OAS (FRED BAMLH0A0HYM2) — 这是整个宏观判断层的#1领先指标, 单一最高权重。理由: 百年校准里"信用利差极端>1000bp"是唯一被反复验证的危机真触发, 且日更、客观、不受头条噪音污染。它走阔领先股市见顶通常数周。当前271bp=极度宽松, 离任何警戒线都远, 说明信用端给risk-on开绿灯。配套盯HY-IG质量利差(自算)抓"质量逃离"早于水平突破。

② HYG/LQD盘中比值 (yf, 实时) — 作为HY OAS的实时前哨, 在FRED日更出来前一天就能从ETF盘中看到信用risk-off方向。两者配对: 平时看ETF抢方向, 定水平/定触发用FRED OAS。

执行建议: 写 credit_spread.py 每日收盘后curl FRED 5个序列(HY/IG/CCC/SOFR/质量利差)写入Truth Store, 盘中用yf HYG/LQD/JNK补实时方向。EBP每月手动拉一次做确认。


## 流动性与金融条件 (Liquidity & Financial Conditions)
**trackers**: 真触发权重排序的最优tracker清单（按"百年校准"权重高→低）。所有刷新节奏按FRED实际更新滞后标注。

【T1 真触发 — 融资管道冻结（最高权重，1天领先即灾难）】
1. SOFR-EFFR spread / SOFR本身 — 来源FRED代码 SOFR(担保隔夜) + EFFR(联邦基金有效利率) + OBFR(隔夜银行融资)。刷新:日(T+1,纽约联储早8:00ET发布前一交易日)。信号:SOFR持续>IORB(准备金利率)20bp+ 或 SOFR-EFFR >10bp = 回购市场缺钱/准备金稀缺(2019-09重演)。SOFR单日尖峰(月末/季末)是技术性,连续3日抬升才是真信号。这是LIBOR-OIS的现代替代品(LIBOR已停用)。
2. 准备金余额 WRESBAL — FRED代码 WRESBAL。刷新:周(每周四H.4.1)。信号:绝对水平跌破~3.0万亿(占GDP~10%)=进入"准备金稀缺区",QT撞墙信号。当前实测6/10读数=3,080,723(百万)即3.08万亿,贴近警戒线——这是当前最该盯的硬约束。

【T1 真触发 — 政策真逆转 / QT-QE状态】
3. Fed总资产 WALCL — FRED代码 WALCL(全名Assets:Total Assets)。刷新:周(每周四下午H.4.1)。信号:周环比方向=QT(缩)/QE(扩)的SSOT。连续两周转正且非临时流动性工具驱动 = QT结束/政策逆转(真触发)。实测6/3→6/10由6,711,495升至6,725,397(百万),近期有回升迹象需盯。
4. 财政部TGA余额 WTREGEN — FRED代码 WTREGEN(Treasury General Account)。刷新:日(T+1)。信号:TGA激增=财政部从市场抽水(发债补账户),与准备金此消彼长;债务上限解决后TGA重建是隐性流动性紧缩,常被忽视的真触发。
5. ON RRP余额 RRPONTSYD — FRED代码 RRPONTSYD(Overnight Reverse Repo)。刷新:日(T+1)。信号:这是流动性"缓冲垫"。RRP从~2万亿耗尽至接近0 = QT开始真正抽干准备金(缓冲耗尽后下一个承压的就是WRESBAL)。RRP见底 = 流动性紧缩进入第二阶段的领先指标。

【T2 综合金融条件指数（聚合读数，确认而非领先）】
6. 芝加哥联储 NFCI — FRED代码 NFCI(National Financial Conditions Index)。刷新:周(每周三,数据截至上周五)。信号:0=历史均值;正值=金融条件偏紧;负值=偏松。实测最新6/5=-0.506(宽松)。穿越0并加速上行 = 系统性收紧确认。子项还有 NFCILEVERAGE / NFCICREDIT / NFCIRISK 可拆杠杆/信用/风险三维。
7. 芝加哥联储 ANFCI(调整后) — FRED代码 ANFCI。刷新:周。信号:剥离经济周期影响后的"纯金融"条件,>0=比经济基本面所暗示的更紧(异常收紧,比NFCI更敏感于纯流动性冲击)。
8. 高盛GS FCI(US Financial Conditions Index) — 来源:无免费API,Bloomberg代码 .GSUSFCI 或高盛GIR报告/财经媒体引用。刷新:日。信号:权重含股价/利率/汇率/信用利差,GS自家口径,市场最常引用。⚠️ 不可yf/FRED自动拉,需WebSearch或Bloomberg。可用FRED的NFCI作为免费高度相关替代。

【辅助 — 银行体系信贷紧缩】
9. SLOOS银行信贷标准 DRTSCILM — FRED代码(C&I贷款收紧净百分比)。刷新:季(每季度SLOOS调查)。信号:净收紧%飙升=信贷渠道关闭的领先指标,但季频太慢,仅作背景确认。

**可自动拉**: 【可FRED自动拉(免费,无需API key)】— 核心机制:FRED的 fredgraph.csv 端点无需key即可拉全历史。确切命令:
  curl -sL "https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>"
返回CSV(date,value)。已实测成功:WALCL / WRESBAL / NFCI 均返回干净数据。
适用全部FRED系列:WALCL, WRESBAL, RRPONTSYD, WTREGEN, SOFR, OBFR, NFCI, ANFCI, NFCILEVERAGE, DRTSCILM。
⚠️ 限流注意(实测发现):FRED对快速连续CSV请求会触发bot挑战并返回空body。必须节流——每series间隔3-5秒,或单次请求/天。建议:写一个daily cron脚本顺序拉(带sleep),而非并发。加 -A "Mozilla/5.0" UA头更稳。
推荐:用官方FRED API + 免费key(api.stlouisfed.org/fred/series/observations?series_id=X&api_key=KEY&file_type=json)更稳定无限流,key免费申请。

【yf可拉的相关项】yahoo-finance脚本路径 /Users/huaichuaibeimeng/.claude/skills/yahoo-finance/scripts/yf。`yf macro` 给VIX/10Y/2Y/2-10利差/DXY/S&P(实测可用),但这些是市场行情非流动性内部管道。yf无法拉Fed资产负债表/RRP/准备金/NFCI(Yahoo无FRED系列)。

【必须WebSearch/手动】高盛GS FCI(.GSUSFCI)——专有指数,无免费API,WebSearch高盛GIR或Bloomberg终端。可用免费NFCI替代。

**精选**: 天天盯1-2个精选:
①【WRESBAL 准备金余额(周四更新)】— 这是当前最硬的、最接近触发点的约束。实测3.08万亿已贴近~3.0万亿的"准备金稀缺"警戒线。流动性危机的物理本质就是"系统里钱够不够",准备金是这个问题的SSOT。它跌破警戒线 = 2019回购危机式事件的物理前提成立。
②【SOFR-IORB利差(日更)】— WRESBAL是"水位",SOFR是"水压表"。准备金稀缺会先在SOFR上以隔夜利率尖峰的形式爆发(领先于任何指数)。SOFR持续>IORB是融资管道冻结的最早、最真实的尖叫,是T1真触发里"领先性"最强的单点。
两者配对:WRESBAL告诉你"离悬崖多远"(慢变量/水位),SOFR告诉你"是否已经踩空"(快变量/水压)。NFCI/GS-FCI是聚合确认指标,滞后,降权作为背景读数即可,不必天天盯。


## 波动率与情绪 (Volatility & Sentiment)
**trackers**: 已实测验证(2026-06-16, yfinance 1.4.1全部拉通)。分两组:可yf自动拉(硬数据,定价类)和必须外部源(调查/资金流类)。

═══ A组: yf自动拉(波动率结构, 实时盘中) ═══

1. **VIX现货 ^VIX** — 来源yf `^VIX`。节奏:实时(15min delay)/日收。信号映射(校准过的"真触发vs噪音"——VIX单点飙升是噪音降权,只有>50才是反向买点):
   - <15 = 自满区(噪音,不动)
   - 20-30 = 警觉但非触发
   - >50 = ⛔反向买点(百年校准:与AAII空>50%叠加=强买入信号)
   实测last=17.68(平静)。

2. **VIX期限结构(核心,比VIX现货信号强10x)** — yf组合拉 `^VIX9D`/`^VIX`/`^VIX3M`/`^VIX6M`,脚本算两个比率:
   - **VIX9D/VIX** 和 **VIX/VIX3M**。节奏:日(盘中可实时)。
   - 比率<1 = contango(正常,市场calm,VIX远月高于近月)
   - 比率>1 = backwardation(倒挂=近月恐慌定价高于远月=真实压力,这是融资/流动性应激的早期读数,非头条噪音)
   - 实测VIX9D/VIX=0.962, VIX/VIX3M=0.837 → 双双contango=无压力。**这是本类最该自动化的领先指标**:VIX3M倒挂领先信用利差走阔。

3. **VVIX(波动率的波动率) ^VVIX** — yf `^VVIX`。节奏:日。VVIX>100-110 = 对冲需求激增/尾部恐慌定价上升(实测87.58=平静)。VVIX与VIX背离(VIX低但VVIX高)= 市场在悄悄买尾部保护=领先警告。

4. **SKEW ^SKEW** — yf `^SKEW`。节奏:日。衡量OTM put相对定价(黑天鹅对冲成本)。>145 = 尾部对冲需求高(实测142.60=偏高但未极端)。单独是噪音,与VVIX同向上升才当信号。

5. **MOVE债券波动率 ^MOVE** — yf `^MOVE`(实测可拉,last=69.36)。节奏:日。**跨资产价值高**:MOVE飙升常领先股票VIX(利率不确定→风险资产),且直连"融资管道/政策逆转"真触发。>120-150 = 债市应激。

6. **VXN纳指波动率 ^VXN** / **OVX原油 ^OVX** / **GVZ黄金 ^GVZ** — 均yf可拉。节奏:日。辅助/分板块,非核心。OVX(实测54.10偏高)用于能源beta判断。

═══ B组: 必须外部源(调查/资金流, 不可yf) ═══

7. **CBOE Put/Call Ratio** — ⛔yf拉不到(^CPC/^PCALL实测EMPTY)。来源:CBOE官网 https://www.cboe.com/us/options/market_statistics/ (Total/Equity/Index PC ratio) 或 StockCharts $CPC/$CPCE。节奏:日(收盘后)。信号:总PC>1.0-1.2 = 极度恐慌(反向偏多),<0.7 = 自满。Equity-only PC更纯。**反向情绪指标,与VIX>50叠加用**。

8. **AAII散户调查(Bull/Bear)** — ⛔不可yf。来源:https://www.aaii.com/sentimentsurvey 周四发布。节奏:周。**这是百年校准的明确反向买点之一**:Bear%>50% = 强反向买入信号(配合VIX>50)。Bull-Bear spread极负(<-20)= 散户投降。免费但需手动/WebSearch抓。

9. **Investors Intelligence(II)投顾调查** — ⛔不可yf,付费。来源:Investors Intelligence(II) Advisors Sentiment,周二发布。节奏:周。Bull%>60 = 机构自满(熊方),<25 = 投顾恐慌(反向多)。II比AAII信号更"聪明钱",但需付费/二手引用。

10. **BofA Global Fund Manager Survey(FMS)** — ⛔不可yf,月度卖方报告。来源:BofA研究(媒体广泛转引,WebSearch可得关键读数)。节奏:月(月中)。最有用读数:**现金水平**(>5%=机构防御到极致=反向买点;<4%=自满sell signal,BofA自己的Cash Rule)、全球增长预期、最拥挤交易。这是"机构定位"的最优单一来源。

11. **资金流** — 部分yf可代理:
   - ETF资金流:yf可拉ETF的价格/成交量,但**净流入需专门源**(ICI周度共同基金流 https://www.ici.org/research/stats, 或EPFR付费, 或Lipper)。节奏:周。
   - 代理方案(可自动化):yf拉 HYG/LQD/TLT/SPY 的成交量+价格动量做risk-on/off代理。
   - **真信号在B组:股票基金大幅赎回(ICI周流极负)+ AAII投降 = 反向买点确认**。

**可自动拉**: 【yf自动拉,已实测全部通过】单条命令即可,无需WebSearch:
- VIX全家族: `yf price ^VIX` / `^VIX9D` / `^VIX3M` / `^VIX6M` / `^VVIX` / `^SKEW` / `^MOVE` / `^VXN` / `^OVX` / `^GVZ` (yfinance 1.4.1全部返回数据)
- 期限结构比率: 脚本拉^VIX9D/^VIX/^VIX3M三个close,算 VIX9D÷VIX 和 VIX÷VIX3M (>1=倒挂=真压力)。这是本类最该建成cron日更脚本的项。
- 资金流代理: `yf history HYG/LQD/TLT/SPY` 取量价做risk-on/off(代理,非真净流入)。

【必须WebSearch/手动/付费,yf拉不到——实测^CPC/^PCALL/^TRIN全EMPTY】:
- CBOE Put/Call: CBOE官网或StockCharts $CPC/$CPCE (日, WebSearch/抓取)
- AAII散户调查: aaii.com (周, 免费但需手动/WebSearch)
- II投顾调查: Investors Intelligence (周, 付费/二手)
- BofA FMS: BofA月报 (月, WebSearch转引关键读数如现金水平)
- 真实基金净流入: ICI周度 ici.org (周) 或 EPFR(付费)

**精选**: **天天盯第一名: VIX期限结构倒挂(VIX9D/VIX 和 VIX/VIX3M, 全yf可拉日更)。** 理由:符合百年校准的"真触发"逻辑——它不是头条噪音(单日VIX飙升被明确降权),而是市场对近期流动性/融资压力的真实定价。近月恐慌定价超过远月(比率>1=backwardation)是信用利差走阔和融资管道冻结的早期同步/领先读数,比VIX现货绝对水平信号强得多。可100%自动化成cron脚本,零人工。

**第二名(反向买点用,周更): AAII Bear% + CBOE Put/Call。** 理由:百年校准已明确把"VIX>50 + AAII空>50%"列为反向买入信号——这是本类唯一被授权当"买点触发器"而非"降权噪音"的组合。但二者都不可yf,需建周度WebSearch/抓取任务(AAII周四、PC日更)。建议:VIX现货由yf自动监控,一旦>40-50自动触发去抓AAII/PC做反向确认。

注:VIX现货本身按校准规则默认降权(噪音),只在>50时升级为信号——不要因为它最有名就天天当主指标盯。


## 商品与汇率 (Commodities & FX)
**trackers**: 注: 本thread内yf不在PATH(command not found), tickers基于Yahoo Finance标准符号约定+FRED标准代码给出。建议主session用`yf macro`/`yf price <ticker>`实拉一次校准格式。FRED代码可100%确认有效。

最优tracker清单(按宏观判断层信号价值排序):

=== A. 增长/避险情绪核心 (最高价值) ===

1. **铜金比 (Copper/Gold Ratio)** — 增长vs避险的最干净读数
   - 来源: 计算式 = HG=F(铜) / GC=F(金), 两者均yf可拉。无单一ticker, 需脚本相除。FRED替代: 无直接, 但可用PCOPPUSDM/不便, 直接用期货。
   - 刷新: 日(实时盘中可)
   - 信号: 比值上升=增长预期回暖/risk-on(利好周期/工业股)。比值快速下跌=增长预期塌方/避险, 与10Y收益率高度同步——铜金比领先于股市拐点。极端低位+加速下行=衰退pricing, 配合信用利差走阔=真触发预警。
   - 校准映射: 单独不是"真触发", 是增长动能确认器, 辅助验证信用利差信号的方向。

2. **铜 HG=F (COMEX Copper)** — Dr.Copper, 实物需求领先指标(供给侧优先)
   - 来源: yf `yf price HG=F`。FRED现货: PCOPPUSDM(月,滞后)。
   - 刷新: 日/实时
   - 信号: 持续走弱=全球工业需求/中国地产塌方信号(供给侧物理需求)。突破性上行常领先于通胀回升。单日波动=噪音, 看周线趋势。

3. **黄金 GC=F (COMEX Gold)** — 避险+实际利率+去美元化复合读数
   - 来源: yf `yf price GC=F`。FRED伦敦定盘: GOLDAMGBD228NLBM(日)。
   - 刷新: 日/实时
   - 信号: 黄金与实际利率(10Y TIPS)负相关。黄金在实际利率上行时仍涨=结构性去美元化/央行购金(背离传统模型, 注意)。极端避险冲刺常伴危机, 但单独是噪音, 需配合信用利差。

=== B. 美元/流动性 (carry & 全球流动性) ===

4. **DXY DX-Y.NYB (US Dollar Index)** — 全球美元流动性总闸门
   - 来源: yf `yf price DX-Y.NYB`。FRED贸易加权: DTWEXBGS(日, 更全面但滞后1日)。
   - 刷新: 日/实时(yf) ; DTWEXBGS日更
   - 信号: DXY急升=全球美元流动性收紧/risk-off/新兴市场承压(海外营收美股压力)。DXY破位下行=risk-on/利好商品+EM。是商品(以美元计价)的反向压制因子。

5. **USDJPY JPY=X** — carry trade unwind尾部风险监测(2024.8 yen-carry闪崩的核心)
   - 来源: yf `yf price JPY=X`。FRED: DEXJPUS(日)。
   - 刷新: 实时/日
   - 信号: ⛔尾部触发器。USDJPY**快速下跌**(日元急升)=carry unwind启动=全球去杠杆抛售连锁(2024-08-05闪崩原型)。关注3日内>3-4%的日元升值幅度=真触发预警。缓慢移动=噪音。这是"融资管道"类信号在FX侧的体现, 高权重。

=== C. 通胀/能源供给侧 (辅助) ===

6. **原油 CL=F (WTI)** — 通胀+地缘+需求复合
   - 来源: yf `yf price CL=F`。Brent: BZ=F。FRED WTI现货: DCOILWTICO(日)。
   - 刷新: 日/实时
   - 信号: 油价飙升=通胀压力回升(连回"通胀失锚"真触发链)+消费税效应。地缘头条驱动的单日跳涨=默认噪音(校准规则), 看是否持续突破。需求侧塌方(油铜同跌)=衰退确认。

7. **白银 SI=F / 天然气 NG=F** — 次级确认(可选, 不必天天盯)
   - 来源: yf `yf price SI=F` / `yf price NG=F`
   - 刷新: 日
   - 信号: 白银=黄金的高beta版(工业+避险双重), 银金比辅助。天然气=能源供给/地缘(欧洲), 波动大噪音多, 仅事件期看。

**可自动拉**: 能yf自动拉(单ticker, 已知Yahoo标准符号, 优先自动化):
- `yf price CL=F` (WTI原油)
- `yf price HG=F` (铜)
- `yf price GC=F` (金)
- `yf price DX-Y.NYB` (DXY)
- `yf price JPY=X` (USDJPY)
- `yf price SI=F` (白银) / `yf price NG=F` (天然气)
- `yf macro` 一条命令含VIX/DXY/油/金/BTC等宏观面板(最省事的日常一拉, 建议每日跑)

需脚本计算(yf拉两腿后相除, 不能单命令):
- 铜金比 = HG=F / GC=F → 建议写进macro监控脚本, 输出比值+5日变化%
- 银金比 = SI=F / GC=F (可选)

FRED自动拉备份(免WebSearch, 代码确认有效, 用fredapi或https://fred.stlouisfed.org/graph/fredgraph.csv?id=<CODE>):
- DTWEXBGS (贸易加权美元, 日)
- DEXJPUS (USDJPY, 日)
- DCOILWTICO (WTI现货, 日)
- GOLDAMGBD228NLBM (伦敦金, 日)
- PCOPPUSDM (铜现货, 月)

无需WebSearch/手动: 本类全部可自动化。WebSearch仅用于"为什么动"(地缘/OPEC/BOJ政策定性), 数字一律yf/FRED。

⚠️校准提示: 本thread yf不在PATH, 上述ticker符号为Yahoo标准约定, 主session首次部署时跑一次`yf macro`+逐个`yf price`验证返回格式, 再固化进监控脚本。

**精选**: 天天盯1-2个:
1. **铜金比 (HG=F / GC=F)** — 全类最高信号价值。它是增长vs避险的单一最干净读数, 领先股市拐点, 且与10Y收益率/信用利差方向高度同步——是验证"真触发"(信用利差极端)方向的最佳交叉确认器。一个比值同时压缩了周期需求(铜)和避险(金)两条线, 信息密度最高。

2. **USDJPY (JPY=X)** — 唯一的FX侧尾部触发器。carry unwind是2024-08闪崩的物理机制(融资管道类真触发在FX的体现), 平时安静但一旦3日内日元急升>3-4%即全球去杠杆连锁。属于"低频但致命", 必须常驻监控阈值告警, 而非天天看绝对值。

理由: 这两个一个管"方向"(铜金比=增长动能)、一个管"尾部"(USDJPY=去杠杆崩盘), 覆盖了商品/汇率类对选股系统最有用的两个维度。DXY/油/金作为辅助读数随`yf macro`每日一拉即可, 不需单独盯。


## 市场内部 / Breadth (家数广度)
**trackers**: 广度类tracker分两条物理通道，决定能否自动化：(A) 可由价格序列重算的"合成广度"——yf能拉的ETF/指数，自己算比值；(B) 交易所原生breadth内部数——只在Stockcharts/Barchart的特殊symbol下存在，yfinance/yf一律拉不到(已实测全FAIL)。

按"领先性×可自动化×信号清晰度"排序：

==1) RSP/SPY 比值 (等权/市值权) — 最优广度代理，强烈推荐==
含义: 比值上行=广度健康(钱进中小盘成分)，比值下行=只有少数大票拉指数(集中度风险，但属噪音侧，仅作背景)。
来源: yf history RSP + yf history SPY，自己除。两个ETF都实测可拉(RSP=212.88, SPY=754.83, OHLC齐全)。
刷新: 日级(收盘后算)。盘中想要可拉15m但无必要。
信号映射: 比值创6-12月新低且SPY同时新高=典型"广度背离"，熊市前兆之一(2021末、2007、2000均出现)。比值跌破200dma=广度转弱黄灯。比值随指数同创新高=广度确认，绿灯。
能yf自动: 是。100%可脚本化。

==2) %above 200dma / %above 50dma (S&P成分股站上均线占比) — 信号最干净，但拉不到原生值==
含义: 这是百年校准里最值钱的breadth读数。<20%=极度超卖(常见反向买点配合VIX>50)，>80%=超买/晚周期。
来源(原生): Stockcharts symbol $SPXA200R(200日) / $SPXA50R(50日) — 网页/付费API，yf无法拉(实测SPXEW/^MAJ200N全FAIL)。
来源(自建): 可用yf批量拉SP500全成分(yf history 每只)，本地算各自200dma，统计占比。可行但重(500次拉取)。
刷新: 日级。
信号映射: %>200dma 从>80%回落跌穿50%=动能见顶。<15%且持续=洗盘见底区(配AAII空>50%/VIX>50才是反向买点，单独不够)。
能yf自动: 原生否；自建是(批量重算，建议每日后台跑一次)。

==3) Breadth Thrust (Zweig / 10日adv占比) — 罕见但极高权重的"全清"买入信号==
含义: 10日(adv家数/(adv+dec))的EMA从<0.40拉到>0.615=Zweig Breadth Thrust，历史上每次出现后6-12月几乎全部上涨(1962年至今十余次零假信号)。这是少有的"breadth真触发"。
来源(原生): 需NYSE每日advancing/declining家数。Stockcharts $NYADV/$NYDEC、$NYAD(adv-dec net)。yf实测^ADD/^ADVN/^DECN全FAIL。
来源(备): WSJ/Barchart市场内部页、Norgate数据。
刷新: 日级。
信号映射: Zweig thrust触发=罕见强多头确认(高权重真触发，归入正向)。普通adv/dec线持续走低背离=广度恶化背景(降权噪音侧)。
能yf自动: 否(需adv/dec家数，yfinance不提供)。须WebSearch/Stockcharts/付费数据。

==4) New Highs - New Lows (NH-NL 净新高新低) — 广度背离确认器==
含义: 净新高转负且指数仍高=隐性走弱。NH-NL是%above-200dma的同源信号，二选一即可。
来源(原生): Stockcharts $NYHL / $NAHL(纳指) / $NHNL，或WSJ Market Data。yf实测^NYHL/^NHNL FAIL。
刷新: 日级。
信号映射: 指数新高但净新高<前高的50%=背离黄灯。净新高深度转负持续=熊确认。
能yf自动: 否。

==5) 涨跌家数 / Advance-Decline Line (AD线) — 经典但最难自动化==
含义: 累计adv-dec，AD线先于指数见顶是经典背离。与#3#4同族。
来源: Stockcharts $NYAD/$NYADV/$NYDEC，yf FAIL。
刷新: 日级。
能yf自动: 否。

实测结论: yf(yfinance后端)只认可交易的证券(ETF+主要指数如^GSPC/^NYA/^VIX/^TNX可拉)，所有交易所breadth内部symbol(^ADD/^NYHL/^TRIN等)一律返回空=拉不到。

**可自动拉**: 【yf直接自动拉，今天就能脚本化】
- RSP/SPY比值: `yf history RSP <period>` + `yf history SPY <period>`，取Close相除。实测两只OHLC齐全可拉。日级后台跑。
- 辅助代理ratio同法可拉: IWM/SPY(小盘广度,IWM=294.64实测OK)、^NYA(NYSE综合,23673实测OK)对比^GSPC。

【yf自建可拉(重，500次批量)】
- %above 200dma / 50dma: 脚本 `yf history` 遍历SP500成分→本地算均线→统计占比。每日后台一次。建议作为对#2原生值的免费替代。

【yf拉不到，必须WebSearch/Stockcharts/Barchart/付费】
- %above-200dma原生值: Stockcharts $SPXA200R / $SPXA50R
- Breadth Thrust / adv-dec家数: $NYAD / $NYADV / $NYDEC (WSJ Market Data页或Barchart)
- NH-NL净新高: $NYHL / $NHNL
- AD线: 同adv-dec家数
原因(实测): yfinance只返回可交易证券，交易所breadth内部index symbol全部返回空。这些是Stockcharts/付费数据商专有。

**精选**: 天天盯1个: RSP/SPY比值(广度背离的早期雷达，唯一100%可yf自动化的高价值广度信号，日级后台算，跌破200dma或与SPY新高背离=黄灯)。
天天盯第2个(条件性): Breadth Thrust(Zweig 10日adv占比)——平时不动，但它是breadth里极少数的"真触发高权重正向信号"(历史零假信号)，值得每日WebSearch扫一眼Stockcharts $NYAD是否触发0.615阈值。它拉不到yf，但稀有度+权重高到必须人工/WebSearch监控。
理由: RSP/SPY管"广度恶化(熊前兆)"且能自动化；Zweig thrust管"广度全清(强多确认)"且权重极高。两者一守一攻，覆盖breadth域的双向极端，其余(%above200dma/NH-NL/AD线)信号同族且全要付费源，做背景周级人工核对即可，不必天天盯。


## 增长nowcast与盈利 (Growth Nowcast & Earnings)
**trackers**: 广扫这一类，按"领先性+信号清洁度"排序的最优tracker清单。⚠️关键约束: 本类几乎全是宏观/经济统计序列(GDPNow/ISM/初请/盈利修正)，yf=Yahoo Finance只有市场行情，无法拉这些。真值来源是FRED+官方+数据商。

【1★ 初请失业金 Initial Jobless Claims — 本类最优, 唯一周频高频硬数据】
- 来源: FRED代码 ICSA(initial, 季调) + CCSA(continuing, 续请)。原始发布: 美国劳工部DOL ETA, https://www.dol.gov/ui/data.pdf
- 刷新: 周(每周四08:30 ET发布上一周数据)。本类唯一兼具"高频+硬数据+领先"的指标。
- 信号映射(关注4周移动均值MA4抗噪): ICSA MA4 < 230k = 劳动市场强/扩张; 250-300k = 中性走软; ⛔ >300k且环比加速上行 = 衰退临近, 经典领先信号(历史上claims在NBER衰退前数月转头向上)。续请CCSA持续抬升=再就业困难=后周期恶化确认。
- 信号权重: 中高。趋势反转(底背离/MA4连续4-6周上行)>单周绝对值。单周噪音大(罢工/天气/季调), 必看MA4。
- 自动拉: ❌yf不可。✅FRED API可自动(见auto_pullable字段)。

【2★ ISM制造业PMI(及服务业) — 本类最强领先指标, 月频】
- 来源: ISM官方 https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/ (PMI数字需付费/媒体转载)。FRED有衍生序列: NAPM(老ISM mfg, 已停更)→现用 MANEMP相关需另找; 实务上ISM PMI头条值FRED不直接免费提供, 靠官方发布日抓+WebSearch补。S&P Global Flash PMI(月中预览)是更早的领先读数。
- 刷新: 月(制造业每月第1个工作日10:00 ET; 服务业第3个工作日; S&P Global Flash约每月23-24日, 比ISM早一周)。
- 信号映射: 50=荣枯线。⛔ <48且连续2月下行+新订单分项(New Orders)领先掉头 = 制造业收缩, 6-12月领先企业盈利下行。>52扩张。最值钱的是子分项: New Orders(领先整体PMI)、New Orders减Inventories差(领先性最强, 库存周期信号)、Prices Paid(领先核心商品通胀)。
- 信号权重: 高(领先性公认强)。但=软数据(调查)，需与初请等硬数据交叉。
- 自动拉: ❌yf不可。部分FRED可(如服务业); 制造业头条值靠官方发布+WebSearch。

【3 Atlanta Fed GDPNow — 实时GDP nowcast, 本类"当下增速"读数】
- 来源: 亚特兰大联储 https://www.atlantafed.org/cqer/research/gdpnow 。官方提供机读数据: https://www.atlantafed.org/-/media/documents/cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx (xlsx, 可程序化抓)。对照: NY Fed Nowcast、StL Fed News Index。
- 刷新: 不定期(每有新经济数据发布即更新, 约每周2-3次), 季度滚动。
- 信号映射: 实时拼出的当季GDP年化%。⛔ 关注"水平+轨迹": 读数从+2%快速下修向0或转负=增长失速实时确认; 与market consensus/blue chip差距大=预期重定价风险。注意: 季初波动极大(样本少), 季末才可信。
- 信号权重: 中(确认型, 非领先; 是"现在多快"不是"未来转向")。早期读数噪音大别当真。
- 自动拉: ❌yf不可。✅可程序化(直接抓官方xlsx URL, 见auto_pullable)。

【4 盈利修正广度 Earnings Revision Breadth — 本类盈利侧最优领先信号】
- 来源: 无免费API。机构源: FactSet Earnings Insight(免费PDF周报 https://insight.factset.com/, 含S&P500 EPS修正/beat率)、Refinitiv/LSEG I/B/E/S、Yardeni Research(免费图 https://yardeni.com/ "Revisions"系列, 含NERI净修正指数)、Bloomberg(BEst)。代理: 个股层面yf ratings(分析师上下调)可拼粗略广度。
- 刷新: 周(FactSet周五PDF; Yardeni周更)。
- 信号映射: NERI(Net Earnings Revision Index)=(上调-下调)/总数。⛔ NERI由正转负且加速下行 = 盈利预期下修潮启动, 领先实际EPS和股价。前瞻4周修正方向比绝对水平重要。Breadth(修正股票占比)恶化领先指数级EPS下修。
- 信号权重: 中高(盈利侧领先性好)。但=卖方consensus衍生, 按D8仅作"预期定位读数", 不进估值链。
- 自动拉: ❌yf不可拉breadth。✅yf ratings可拉个股升降级(粗代理, 需自己聚合)。Yardeni/FactSet靠WebFetch抓页/PDF。

【5 前瞻EPS Forward EPS / Fwd P/E — 估值定位读数, 非领先】
- 来源: yardeni "Stock Market Briefing: Forward P/Es" 免费、FactSet、yf quote(个股forwardPE/forwardEps字段, 指数靠成分聚合或用SPY代理)。
- 刷新: 周/月。
- 信号映射: 这是"市场预期了多少"的水平读数, 本身不领先。用法: ①Fwd EPS的修正方向(=上面的revision breadth, 才是信号) ②Fwd P/E极端高=高估值=按百年校准属"噪音/默认降权"(不单独触发)。⛔ 真正有用的是Fwd EPS掉头, 不是P/E高低。
- 信号权重: 低(单独看=被降权的高估值噪音)。仅作背景定位。
- 自动拉: △yf quote可拉个股forwardEps/forwardPE; 指数级需聚合成分或抓Yardeni。

【补充市场内生代理(yf可直接自动拉, 增长预期实时读数, 补宏观滞后)】
- 铜金比 Copper/Gold: yf price HG=F 与 GC=F 相除 → 增长预期实时代理, 比比率掉头领先PMI。实时, ✅yf可拉。
- 周期/防御比: yf compare 用 XLI(工业)/XLU(公用)、XLY/XLP → 比率走弱=增长预期降温。✅yf可拉。
- 运输股 IYT/小盘 IWM 相对SPY: 经济敏感, 走弱领先。✅yf可拉。
这些不是"官方nowcast", 但实时、免费、yf可自动, 适合作为GDPNow/ISM月频数据之间的高频补盲。

**可自动拉**: 分两类清楚区分:

❌ yf无法拉(本类核心硬数据全在此列, yf=Yahoo只有行情):
- 初请失业金、ISM PMI头条值、GDPNow、盈利修正广度、指数级Fwd EPS — 这些是FRED/官方/数据商序列, Yahoo Finance不carry。

✅ 可自动化(非yf, 但能脚本化, 建议建管道):
1. FRED API(免费, 最优自动源, 覆盖初请最全)。需先申请api_key(已验证当前环境无key, 报错"api_key is not set")。命令样例:
   curl "https://api.stlouisfed.org/fred/series/observations?series_id=ICSA&api_key=KEY&file_type=json&sort_order=desc&limit=8"
   续请用 CCSA。建议: 申请免费FRED key存入环境变量, 写个 fred 拉取脚本(类比yf)。
2. GDPNow: 直接curl官方xlsx, 无需key:
   curl -sL "https://www.atlantafed.org/-/media/documents/cqer/researchcq/gdpnow/GDPTrackingModelDataAndForecasts.xlsx" -o gdpnow.xlsx
3. 盈利修正/Yardeni/FactSet: 靠WebFetch抓页面/PDF(半自动, 无干净API)。

△ yf可拉(仅代理/个股, 非头条宏观值):
- yf ratings TICKER → 个股分析师升降级(聚合成粗revision breadth)
- yf quote TICKER → forwardEps/forwardPE(个股)
- yf price HG=F / GC=F → 铜金比(增长代理, 实时)
- yf compare XLI,XLU,XLY,XLP → 周期/防御比(增长代理)

⚠️ 当前环境yf不在默认PATH, 实路径: /Users/huaichuaibeimeng/.agents/skills/yahoo-finance/scripts/yf (或用yahoo-finance skill调用)。

**精选**: 天天盯精选(本类2个):

①【初请失业金 ICSA(看MA4)】— 本类唯一"周频+硬数据+领先"三合一, 信号最清洁。理由: GDPNow/Fwd EPS是滞后/定位读数, ISM是月频且软数据, 盈利修正是卖方衍生; 只有初请既高频又是政府硬数据, 且历史上在衰退前数月转头(claims MA4连续上行=最早的劳动市场裂缝)。与百年校准的"真触发"逻辑一致——它捕捉的是基本面恶化的早期实物证据, 不是估值/情绪噪音。盯法: 每周四看ICSA MA4趋势(>300k且加速上行=红灯)+CCSA续请抬升确认。

②【ISM制造业New Orders子分项(及S&P Global Flash PMI月中预览)】— 本类公认领先性最强的转向信号。理由: 整体PMI已被广泛跟踪, 但New Orders分项、尤其"New Orders减Inventories"领先整体PMI和企业盈利6-12个月, 是判断库存周期/盈利拐点的最优单一读数; S&P Global Flash比ISM早约一周, 抢跑窗口。盯法: 每月看New Orders是否跌破50且环比掉头, 配合Flash PMI月中预览, 与初请(硬数据)交叉确认软硬一致。

(GDPNow只在季末读、盈利修正广度每周扫一眼方向即可, 不必天天盯; Fwd P/E按校准属降权噪音, 不单独触发。)


## 中文/散户情绪源 (Chinese / Retail Sentiment Sources)
**trackers**: 用途定性: 这一整类是【逆向情绪读数】, 不是基本面。映射逻辑统一为"散户极度亢奋=topping风险/降权追多, 散户极度恐慌=反向买点候选"。但对美股选股系统的价值是【间接/二阶】: A股散户情绪→中国risk appetite→外溢到中概/与中国挂钩的美股(KWEB/BABA/PDD/港股)+全球risk-on/off温度计, 不能直接驱动美股建仓。按可靠性+可自动化排序:

═══ TIER 1 (硬数据, 可自动化, 优先) ═══

1. 两融余额/融资余额 (margin balance) — 最优硬指标
   • 来源: akshare `stock_margin_account_info`(东财, 全市场两融账户/余额) + `stock_margin_detail_sse`/`stock_margin_detail_szse`(沪深交易所明细)
   • 刷新: 日(T+1, 交易所收盘后晚间披露)
   • 信号映射: 融资余额=散户/游资杠杆。绝对水位+斜率双看。2026/1余额2.58万亿(同比+40.9%, 来源stcn.com/sina), 这种加速上冲=亢奋顶部风险, 对应Phase1"高估值/杠杆"噪音类但作情绪计有效;余额单周骤降>5%=去杠杆/恐慌, 配合暴跌=潜在反向买点。最干净的"中国版margin debt"。
   • 来源URL: https://finance.sina.com.cn/stock/marketresearch/2026-01-12/doc-inhfzcnx6954464.shtml

2. 新增投资者开户数 (new A-share accounts) — 最纯的散户FOMO计
   • 来源: akshare `stock_account_statistics_em`(东财, 月度新增投资者) ; 原始口径=中证登月报
   • 刷新: 月(中证登月中披露上月)
   • 信号映射: 散户入市狂热度。2026/1新开491.58万户(环比+89%, 同比+213%), 这种翻倍式井喷=典型情绪顶部前兆(散户在最高位入场), 强逆向看空信号。低迷+收缩=底部酝酿。滞后性强(月频), 做趋势确认而非择时。
   • 来源URL: https://finance.sina.com.cn/roll/2026-04-17/doc-inhuuccn6641084.shtml

3. 全市场涨跌停/连板/封板率/赚钱效应 (breadth+游资情绪)
   • 来源: akshare涨跌停板池接口(`stock_zt_pool_em`涨停池/`stock_zt_pool_dtgc_em`跌停/炸板) → 自算炸板率=炸板数/(涨停数+炸板数)、最高连板高度、封板率
   • 刷新: 日(实时盘中可拉, 收盘定格)
   • 信号映射: 炸板率>30%+连板高度坍塌=接力情绪退潮(顶部);封板率>85%+涨停近百家=亢奋(如2026/4/30封板率85%、5/19涨停122家);跌停潮(>50家)=恐慌。这是A股游资情绪最高频读数。

═══ TIER 2 (情绪指数/合成, 半自动) ═══

4. 沪深300股债性价比/ERP (股权风险溢价) — 不是散户情绪但是A股估值温度计
   • 来源: akshare债券收益率+指数PE自算 ERP = 1/PE(300) − 10Y国债收益率; 或东财/中证现成"股债性价比"
   • 刷新: 日
   • 信号: ERP处于历史+1σ以上=股票极便宜(底部, 与散户恐慌共振时=反向买点强信号);−1σ=股票贵(顶部)。比纯情绪客观, 建议作"情绪×估值"双重确认。

5. 东财"A股情绪雷达"合成指标 (散户追涨指数/主力散户背离度/赚钱效应指数)
   • 来源: 东方财富财富号"A股情绪雷达"(每日, 如2026/5/20散户追涨85/100=极度危险、主力散户背离90/100)
   • 刷新: 日 | 来源URL: https://caifuhao.eastmoney.com/news/20260520185420844463360
   • 信号: 散户追涨>80=危险/降权;主力散户背离>85=主力出货散户接盘=顶部。⚠️黑箱算法, 不可复现, 只能WebFetch读, 当辅助交叉。

═══ TIER 3 (社媒情绪, 难自动化/低可靠, 默认降权) ═══

6. 雪球情绪指数 — 学术上是大盘领先指标(CSDN/知乎回测), 但无公开稳定API, 雪球接口稳定性差。需自建爬虫+情绪模型, 维护成本高。
7. 东方财富股吧发帖量/情绪词频("牛市""割肉") — 研究显示东财股民情绪波动最剧烈(与行情吻合), 雪球/集思录用户更理性。同样需自建NLP, 无现成接口。
8. 李大霄抖音/微博 (用户提到的"散户情绪表") — 纯定性反向风向标(标志性喊话=情绪极值信号), 无法量化自动拉, 只能人工/WebSearch偶查, 当彩蛋不当系统输入。

**可自动拉**: 【可yf自动拉】无——yf(yahoo-finance)不覆盖A股散户情绪/两融/开户数, 这一类yf完全不适用。

【可akshare自动拉, 推荐建脚本】(akshare已是项目A股主源):
• 两融余额: `ak.stock_margin_account_info()` / `ak.stock_margin_detail_sse()` / `ak.stock_margin_detail_szse()` — 日频
• 新增开户: `ak.stock_account_statistics_em()` — 月频(注: 接口名需在当前akshare版本core确认, 我未实测;若失效用东财月报URL兜底)
• 涨跌停/炸板/连板: `ak.stock_zt_pool_em(date=...)` + `ak.stock_zt_pool_dtgc_em(date=...)` — 日频, 自算炸板率/封板率/连板高度
• ERP/股债性价比: akshare国债收益率 + 指数PE 自算, 日频
建议: 写一个 china_sentiment.py 包进现有A股数据栈(feedback_data_sources.md里akshare主源), 输出日度情绪面板。⚠️所有akshare接口名/参数需先实测(我基于文档+搜索, 未在本环境跑akshare验证, 标"接口名待core确认")。

【必须WebSearch/WebFetch或人工, 不可自动化】:
• 东财"A股情绪雷达"合成指数 — WebFetch读财富号
• 雪球情绪指数/股吧词频 — 需自建爬虫+NLP, 不建议短期上
• 李大霄抖音 — 人工偶查, 反向彩蛋

**精选**: 天天盯1-2个: ①【两融融资余额】(akshare日拉) — 这一类里唯一兼具高频+客观+可自动化的硬指标, 是"中国版margin debt", 斜率+绝对水位直接读散户杠杆亢奋度, 与百年校准"杠杆/融资管道"逻辑同源。②【涨跌停炸板率+连板高度】(akshare日拉) — A股游资情绪最高频读数, 顶部退潮先于指数下跌, 做情绪拐点预警。

⚠️给系统的诚实定位(关键): 整个"中文/散户情绪源"类对美股选股系统是【二阶/间接信号, 默认低权重】, 不进入美股建仓主链。理由: (1)A股散户情绪→中国risk appetite→只对中概/港股/与华挂钩美股有外溢, 对纯美股标的无直接因果;(2)属Phase1校准里的"情绪/估值/单日波动"噪音家族, 而非"信用利差/融资冻结/实际利率"真触发家族。正确用法: 当A股两融+开户数同时极端亢奋(如2026年1月井喷)→作为"全球散户risk-on见顶"的交叉佐证之一, 配合美股自身VIX/AAII读数使用;单独出现不构成美股动作。李大霄式定性信号只当情绪极值彩蛋, 永不入系统输入。
