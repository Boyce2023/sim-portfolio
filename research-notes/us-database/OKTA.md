# OKTA 深判 (2026-09-03, Claude分析意见) · 现价 $163.15 (yf 9/2收) · 市值 $28.5B

## 读了什么
- 高盛model(0_Models/OKTA_model.xlsx, 7/29版, 模型价$99): IS/BS/CF/Drivers 四表, 季度列FY16→FY29E。
- Earnings call FY2027Q2(8/26)全文, FY2027Q1(5/28)与FY2026Q4(3/4)前半。
- 高盛行业报告 Revisiting Moats VI(security AI spend滞后)里的Okta段; 无个股研报。
- 价格: 52周低 $62.93(4/10) → Q1财报后+30%(5/29 $123) → Q2财报后+29%(8/27 $173) → 现 $163。半年2.6倍。

## 模型骨架(买方视角看GS怎么搭)
收入=订阅(99%)+专业服务(已转给GSI, 降到1%)。订阅由 ARR × NRR 驱动: Drivers页 ARR 1Q27A $3.0B, NRR 107%(FY24 117%→FY26 106%→模型FY27-29 flat 106-107%), 净新增ARR FY24 420 → FY26 308 → 模型FY27 312/FY28 377/FY29 403。
cRPO是先行指标: 1Q27 $2.50B, 模型FY27 +10%/FY28 +10%/FY29 +10%。
利润: 毛利82%, non-GAAP营业利润率 FY26 26.2% → FY27E 25.8% → FY29E 30.1%; SBC占收入 15%→11%; GAAP营业利润率 5%→18%。
现金: FCF FY26 $863M(29.6%) → FY27E $880M(27.5%) → FY29E $1.17B(30%); 回购 FY27E $548M。
关键单元经济: LTV:CAC 从 FY24 2.4 掉到 1Q27 1.7, 模型FY27 1.6。**这是模型里最诚实的一行: 每一块S&M换来的新ARR在变少。**
GS对FY28/29的再加速(9.5%→10.5%→10.7%)全部押在净新增ARR从312回到400, 而NRR不动——即靠新产品(OIG/AI agents)带来的新logo和扩张。

## 电话会里的事实(8/26)
- Q2非Q4季度历史最高bookings; cRPO增速加速约200bp(到约12%); >$1M ACV客户超600家(+20%+); 新产品占bookings 30%, 带来约40% ACV uplift; OIG是最大贡献。
- FY27指引上调: 收入+10~11%(原9~10%), non-GAAP OPM 26%, FCF 28~29%。Q3: 收入+10%, cRPO +11~12%。
- AI agents: "dozens of deals, several million-dollar-plus", 但CFO原话 "Still immaterial. Still very small... for FY2027 we do not think it is going to be material, but 2028 and beyond... real possibility". 定价=按用户数uplift, 消费制在铺路。
- 生态: Anthropic的enterprise-managed auth是第一个支持Cross App Access的agent; 26家SaaS支持资源端。Permiso收购(400条风险检测 vs 自家90)。联邦: IL5, DoD 2027零信任令; 公共部门<10%收入。
- 管理层对Microsoft: "copying us... hard to be neutral"。

## 判断
1. **生意质地**: 身份是系统级记录, 换成本高, 20,000客户/8,000集成是真护城河; 但不是物理约束型护城河, 最大结构风险是Microsoft Entra捆绑在E5里, 中小客户被白送。
2. **增长的真相**: 核心业务是一台10%机器(收入10~11%, cRPO 12%, NRR 107%), 再加速的证据只有"cRPO+200bp"和"bookings纪录", AI agent收入按公司自己的话FY27不可见。
3. **估值(G1口径)**: FY27E EPS $3.86(+10%) → P/E 42x, PEG≈4; FY28E $4.59(+19%) → 35.5x, PEG 1.9。EV≈$26B(现金$2.6B, 可转债6月已清), EV/FCF FY27E 29.6x, FCF yield 3.4%, EV/Sales 8x(4月时约3.5x)。yf的PEG 0.22是GAAP低基数假象, 不可用。
4. **股价在定价什么**: 半年2.6倍、两次财报各+30%, 而收入增速只从9%到10~11%。这是"AI agent身份=下一个大类"的叙事重估, 数字还没跟上。市场在提前买FY28再加速。
5. **现价我会新买吗: 不会。** 按我的框架: 供给侧约束可名状但不硬; PEG(G1)≥1.9不过关; 现金转化好(FCF>净利); 催化剂有日期(Oktane 9/21周, GS会9/9, Q3财报12月初)。四项过两项半。
6. **Bear case**: 若Q3/Q4 cRPO停在11~12%、AI收入到FY28仍"immaterial", 估值回到5~6x sales = $100~120, 下行30~40% → F9 T3/T4。参照: 2025-07 $98→2026-04 $63那段就是增速降到9%时的市场定价。
7. **什么条件下买**: ①cRPO增速打到14%以上(证明再加速是真的, 而非bookings口径的噪音), 或 ②价格回到$110~125(EV/FCF约20x)且thesis未破。两者其一即可考虑10%仓位; 都不满足不碰。
8. **回测里的Okta**: 2024-02-29(+22.9%)和2025-03-04(+24.3%)两次财报跳涨, 盲判agent都说"回吐", 都判对(21日 -3.6%/-2.7%, 1年 +0.9%/-26.5%)。这家公司的财报跳涨历史上是卖点不是买点——直到今年4月起的这轮不同, 因为这次跳涨伴随的是估值倍数从3.5x到8x的重估, 不是业绩驱动。这恰恰是我不追的理由。

## 反面(我可能错在哪)
- Agent身份真的可能成为最大的cyber类别(CEO原话), 若FY28 AI ARR做到$300M+级别, 10%机器变15%机器, 8x sales不贵。翻转条件: 连续两个季度cRPO≥14% 或 公司披露AI ARR并超$200M。
- 我对Microsoft捆绑风险的权重可能过高: 大企业(>$1M ACV +20%)恰恰是在选中立平台。
