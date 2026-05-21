#!/usr/bin/env python3
"""Generate Chinese architecture diagram as PNG with pixel-perfect CJK alignment."""
from PIL import Image, ImageDraw, ImageFont
import os

def is_wide(ch):
    c = ord(ch)
    if 0x4E00 <= c <= 0x9FFF: return True
    if 0x3400 <= c <= 0x4DBF: return True
    if 0xF900 <= c <= 0xFAFF: return True
    if 0xFF01 <= c <= 0xFF60: return True
    if 0x3000 <= c <= 0x303F: return True
    if 0x3040 <= c <= 0x30FF: return True
    if 0x2E80 <= c <= 0x2FDF: return True
    return False

def col_width(s):
    return sum(2 if is_wide(ch) else 1 for ch in s)

RAW = [
"┌─────────────────────────────────────────────────────────────────────────────────────┐",
"│                          NEXUS v10.1.0 系统全景架构                                  │",
"│                     6层多智能体协作操作系统 + AI模拟盘投资系统                            │",
"└─────────────────────────────────────────────────────────────────────────────────────┘",
"",
"╔═══════════════════════════════════════════════════════════════════════════════════════╗",
"║  6大工作流（每个会话自动识别身份，共享底层数据）                                          ║",
"║  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     ║",
"║  │  研究    │ │  交易    │ │  追踪    │ │  时事    │ │  面试    │ │  系统    │     ║",
"║  │  系统    │ │  系统    │ │  系统    │ │  选股    │ │  答辩    │ │  管理    │     ║",
"║  │          │ │          │ │          │ │          │ │          │ │          │     ║",
"║  │ 10步流程  │ │ 模拟盘   │ │ 仪表盘   │ │ 催化剂   │ │ 邮件求职 │ │ 审计升级  │     ║",
"║  │ 16框架   │ │ IBKR实盘 │ │ 云端部署 │ │ 市场脉搏  │ │ PM模拟  │ │ 6层维护   │     ║",
"║  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘     ║",
"║       └──────┬─────┴──────┬─────┴──────┬─────┴──────┬─────┴──────┬─────┘           ║",
"╚══════════════╪════════════╪════════════╪════════════╪════════════╪═══════════════════╝",
"               │            │            │            │            │",
"               ▼            ▼            ▼            ▼            ▼",
"┌─────────────────────────────────────────────────────────────────────────────────────┐",
"│                        ~/.claude/nexus/（Nexus 6层核心）                              │",
"│                                                                                     │",
"│  ┌─────────────────────────────────────────────────────────────────────────────┐    │",
"│  │ L5 元层 — 自修改协议 / 健康聚合 / 积分卡(基线51.5) / 反熵机制               │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L4 质量关卡 — 执法层（4级: 宪法5/法律18/法规32/建议~180）                    │    │",
"│  │   33个操作触发器（14原始 + 5监管 + 5技能 + 9风控v10.1）                      │    │",
"│  │   ┌─────────────┐ ┌──────────────┐ ┌─────────────┐ ┌──────────────┐       │    │",
"│  │   │ 熔断器      │ │ VIX暴露控制   │ │ 止损临界警报  │ │ 集中度风控    │       │    │",
"│  │   │ 5%/10%/15%  │ │ 20/25/35     │ │ <3%即警报   │ │ 同板块>3只   │       │    │",
"│  │   └─────────────┘ └──────────────┘ └─────────────┘ └──────────────┘       │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L3 编排层 — 任务队列 + 跨工作流任务派发（闲置中，建议简化）                   │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L2 信号总线 — 6条待处理 / 7条已处理 / 优先级: 紧急>高>中>低                 │    │",
"│  │   signals/pending/   ◄──── 5条同步 + 1条市场状态就绪                        │    │",
"│  │   signals/processed/ ◄──── 7条已处理（含3条v10过期清理）                     │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L1 状态层 — 6个工作流状态文件（全部同步至05-21）                              │    │",
"│  │   workstreams/{research,trading,tracking,events,interviews,nexus}.json      │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L0 真相库 — 337条事实 / 31个文件 / 23个公司文件                              │    │",
"│  │   ┌──────────────────────────────────────────────────────────────────┐     │    │",
"│  │   │ 公司数据 (23个)        │ 宏观指标               │ 持仓数据       │     │    │",
"│  │   │ NVDA AAPL GOOGL ADBE  │ indicators.json (16项) │ positions.json │     │    │",
"│  │   │ GEV LEU CCJ NXE SPUT  │ regime.json (横盘)     │ (IBKR待更新)  │     │    │",
"│  │   │ HSAI OKLO VST BWXT    │                        │                │     │    │",
"│  │   │ FPS CEG UEC 002028    │ ┌────────────────────┐ │                │     │    │",
"│  │   │ 002472 002938 603005  │ │ SPX    7,433       │ │                │     │    │",
"│  │   │ 600089 2525HK NOW     │ │ VIX    17.44       │ │                │     │    │",
"│  │   │                       │ │ 黄金   $4,549/盎司  │ │                │     │    │",
"│  │   │                       │ │ 比特币 $77,968     │ │                │     │    │",
"│  │   │                       │ │ 原油   $98.93/桶   │ │                │     │    │",
"│  │   │                       │ │ U3O8   $85/磅      │ │                │     │    │",
"│  │   │                       │ └────────────────────┘ │                │     │    │",
"│  │   └──────────────────────────────────────────────────────────────────┘     │    │",
"│  └─────────────────────────────────────────────────────────────────────────────┘    │",
"│                                                                                     │",
"│  sync/update-bulletin.json  ◄──── v10.1.0，跨会话同步协议（CLAUDE.md 第0步）        │",
"│  protocols/ ──── enforcement.md / handoff.md / output.md / internalization.md        │",
"│  architecture.yaml v9 / changelog.json v10.1.0                                      │",
"└──────────────────────────────────────────┬──────────────────────────────────────────┘",
"                                           │",
"                    ┌──────────────────────┼──────────────────────┐",
"                    │                      │ 唯一真相源            │",
"                    ▼                      ▼                      ▼",
"┌──────────────────────────────────────────────────────────────────────────────────────┐",
"│                    ~/claude-projects/sim-portfolio/                                    │",
"│                    Claude AI 模拟盘（第3天 | ¥1.03M + $148K）                          │",
"│                                                                                      │",
"│  ┌──────────────────────────────────────────────────────────────────────────────┐    │",
"│  │                    portfolio_state.json（唯一真相源）                          │    │",
"│  │  A股: 思源002028 / 晶方603005 / 鹏鼎002938 / 双环002472  | NAV ¥1,027,181    │    │",
"│  │  美股: NVDA / AAPL / GOOGL / ADBE / SRUUF / GEV / LEU / FPS | NAV $148,498  │    │",
"│  │  交易日志: 14笔 | 每日快照 | 现金计划                                         │    │",
"│  └───────────────────────────────────┬──────────────────────────────────────────┘    │",
"│                                      │                                               │",
"│  ┌───────────────────────────────────┼──────────────────────────────────────────┐    │",
"│  │                        scripts/（16个Python脚本）                             │    │",
"│  │                                                                               │    │",
"│  │  ┌─ 核心交易链 ──────────────────────────────────────────────────────┐        │    │",
"│  │  │ fetch_prices.py ──► risk_monitor.py ──► decision_engine.py       │        │    │",
"│  │  │       │                    │                     │               │        │    │",
"│  │  │       ▼                    ▼                     ▼               │        │    │",
"│  │  │  latest_prices.json   熔断器检查            decisions.json       │        │    │",
"│  │  │                       VIX缩放               决策链              │        │    │",
"│  │  │                       止损警报                    │              │        │    │",
"│  │  │                       (+343行 v10.1)             ▼              │        │    │",
"│  │  │                                         execute_trade.py       │        │    │",
"│  │  │                                          (+130行 审计追踪)     │        │    │",
"│  │  │                                              │                 │        │    │",
"│  │  │                                    ┌─────────┴──────────┐      │        │    │",
"│  │  │                                    ▼                    ▼      │        │    │",
"│  │  │                          portfolio_state.json    audit-trail/  │        │    │",
"│  │  │                              (更新)            (17笔 + 模式)   │        │    │",
"│  │  └────────────────────────────────────────────────────────────────┘        │    │",
"│  │                                                                            │    │",
"│  │  ┌─ 风险分析 ────────────────────────┐  ┌─ 归因与报告 ──────────────┐      │    │",
"│  │  │ risk_metrics.py   VaR/夏普/      │  │ attribution.py  归因分析  │      │    │",
"│  │  │   (528行)         索提诺/贝塔    │  │   (636行)       对比SPY  │      │    │",
"│  │  │ risk_dashboard.py 评分/限额      │  │ weekly_commentary.py     │      │    │",
"│  │  │   (500行)         集中度控制     │  │   (767行) md/推特/微博   │      │    │",
"│  │  │ kelly_sizing.py   凯利公式       │  │ performance.py 绩效计算   │      │    │",
"│  │  │   (319行)         基于交易       │  │ leaderboard_page.py 排行  │      │    │",
"│  │  └──────────────────────────────────┘  └──────────────────────────┘      │    │",
"│  │                                                                            │    │",
"│  │  ┌─ 市场感知 ────────────────────────┐  ┌─ 系统集成 ──────────────┐      │    │",
"│  │  │ regime_detection.py  4因子加权    │  │ sync_nexus.py  系统同步  │      │    │",
"│  │  │   VIX(35%)+MA(25%)+            │  │ system_check.py 健康检查  │      │    │",
"│  │  │   收益率(20%)+信用(20%)         │  │ trading_engine.py 执行层  │      │    │",
"│  │  │ news_scan.py  新闻扫描          │  │ leaderboard_api.py 路由   │      │    │",
"│  │  └──────────────────────────────────┘  └──────────────────────────┘      │    │",
"│  └───────────────────────────────────────────────────────────────────────────┘    │",
"│                                                                                   │",
"│  ┌─────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐     │",
"│  │ api/  (FastAPI)      │  │ alpha-factors/        │  │ telegram-bot/        │     │",
"│  │ ├ app.py (997行)     │  │ ├ factors.py (30因子)  │  │ ├ notifications.py   │     │",
"│  │ │  19个接口端点       │  │ │  基础因子框架        │  │ │  (630行, 零依赖推送)│     │",
"│  │ │  + 实时推送         │  │ │  动量/市盈/盈利实现  │  │ ├ bot.py (486行)     │     │",
"│  │ ├ models.py (383行)  │  │ ├ ic_tracker.py      │  │ │  命令处理           │     │",
"│  │ │  Pydantic v2       │  │ │  IC/IR/换手率       │  │ └ config/            │     │",
"│  │ ├ openapi.yaml       │  │ │  状态分类           │  │   电报配置           │     │",
"│  │ └ requirements.txt   │  │ └ factor_zoo.json    │  │   (仅环境变量)        │     │",
"│  │                      │  │   (30个因子定义)      │  │                      │     │",
"│  │  认证: 读公开/写需密钥│  │                      │  │  与JS版共存          │     │",
"│  └─────────────────────┘  └──────────────────────┘  └──────────────────────┘     │",
"│                                                                                   │",
"│  ┌─ 审计与报告 ──────────┐  ┌─ 研究资料 ──────────────────────────────────────┐   │",
"│  │ audit-trail/ (17+1)  │  │ research-notes/                                 │   │",
"│  │  每笔交易决策链       │  │  adversarial-debate-protocol.md (899行)         │   │",
"│  │  触发→论点→          │  │  regime-detection-design.md (669行, 二/三期)    │   │",
"│  │  风控→仓位→终决      │  │  backtesting-research.md (VectorBT推荐)         │   │",
"│  │ 周报/ (3份)          │  │                                                 │   │",
"│  │  md / 推特 / 微博    │  └──────────────────────────────────────────────────┘   │",
"│  └──────────────────────┘                                                         │",
"└──────────────┬───────────────────────────────────────────────────────────────────┘",
"               │",
"               │ git推送 / Railway部署",
"               ▼",
"┌──────────────────────────────────────────────────────────────────────────────────┐",
"│                          外部服务层                                                │",
"│                                                                                  │",
"│  ┌───────────────────────┐  ┌───────────────┐  ┌──────────────┐  ┌───────────┐  │",
"│  │ Railway               │  │ Telegram      │  │ 雅虎财经      │  │ GitHub    │  │",
"│  │ nexus-ai-portfolio    │  │ 告警机器人    │  │ yfinance接口  │  │ 远程仓库  │  │",
"│  │ .up.railway.app       │  │ 推送通知      │  │ 实时价格/指标 │  │ 版本控制   │  │",
"│  │                       │  │               │  │              │  │           │  │",
"│  │ 实时持仓/收益率图表    │  │ 交易成交通知  │  │ fetch_prices │  │ sim-port  │  │",
"│  │ 交易明细公开展示       │  │ 风控告警      │  │ risk_monitor │  │ 自动推送  │  │",
"│  │ 排行榜 (规划中)       │  │ 每日总结      │  │ regime_det   │  │           │  │",
"│  └───────────────────────┘  └───────────────┘  └──────────────┘  └───────────┘  │",
"└──────────────────────────────────────────────────────────────────────────────────┘",
"",
"┌──────────────────────────────────────────────────────────────────────────────────┐",
"│  ~/claude-projects/equity-frameworks/（独立Python库，MIT开源协议）                  │",
"│                                                                                  │",
"│  16个投资分析框架 — pip install equity-frameworks                                  │",
"│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐     │",
"│  │ 供给分析   │ │ 估值方法   │ │ 行业分析   │ │ 行为分析   │ │ 管理评估   │     │",
"│  │ F2 供给优先 │ │ F5 类比攻防 │ │ F1 铀弹性  │ │ F3 三次行情 │ │ F8 管理层  │     │",
"│  │ F13 可得性 │ │ F12 三层估值│ │ F4 度电成本│ │ F7 DeepSeek│ │  六维评分  │     │",
"│  │ F16 滞后  │ │ F15 共识反向│ │ F6 SMR分级 │ │ F14 历史类比│ │            │     │",
"│  │           │ │            │ │ F10 DC测算 │ │            │ │ 流程方法   │     │",
"│  │           │ │            │ │ F11 禾赛   │ │            │ │ F9 淘汰法  │     │",
"│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └────────────┘     │",
"│  15/15测试通过 | 零外部依赖 | 自动注册 | 20%熊市规则硬编码                          │",
"└──────────────────────────────────────────────────────────────────────────────────┘",
"",
"┌──────────────────────────────────────────────────────────────────────────────────┐",
"│  数据流向（唯一真相源层级）                                                        │",
"│                                                                                  │",
"│  持仓: portfolio_state.json ──► positions.json ──► watchlist.md                   │",
"│         (唯一真相源)              (真相库镜像)        (记忆库)                      │",
"│                                                                                  │",
"│  价格: yfinance ──► fetch_prices.py ──► portfolio_state.json                     │",
"│                                                                                  │",
"│  交易: 决策引擎 ──► 交易执行 ──► portfolio_state + 审计追踪                        │",
"│                                                                                  │",
"│  风控: 风险监控 ──► 熔断器/VIX/止损 ──► 信号总线 ──► 电报通知                      │",
"│                                                                                  │",
"│  同步: update-bulletin.json ──► CLAUDE.md 第0步 ──► 每个会话首条消息检查           │",
"└──────────────────────────────────────────────────────────────────────────────────┘",
]

# === NORMALIZER: fix column widths ===
def normalize(lines):
    right_border = set('│║┐┘┤╗╝╣')
    result = []
    single_target = None
    double_target = None
    for line in lines:
        if not line:
            result.append(line)
            continue
        first = line[0]
        if first == '┌':
            single_target = len(line)
        elif first == '╔':
            double_target = len(line)
        last = line[-1]
        if last not in right_border:
            result.append(line)
            continue
        target = None
        if first in '│┌└├┬┴':
            target = single_target
        elif first in '║╔╚╠╦╩':
            target = double_target
        if target is None:
            result.append(line)
            continue
        content = line[:-1].rstrip(' ')
        content_cols = col_width(content)
        spaces = target - content_cols - 1
        if spaces < 0:
            spaces = 0
        result.append(content + ' ' * spaces + last)
    return result

LINES = normalize(RAW)

print("=== Alignment check ===")
ok = True
single_t = None
double_t = None
for i, line in enumerate(LINES):
    if not line: continue
    first = line[0]
    if first == '┌': single_t = len(line)
    elif first == '╔': double_t = len(line)
    last = line[-1]
    if last in '│║┐┘┤╗╝╣':
        w = col_width(line)
        t = single_t if first in '│┌└├┬┴' else double_t if first in '║╔╚╠╦╩' else None
        if t and w != t:
            print(f"  !! L{i}: {w} cols (target {t}): {line[:60]}...")
            ok = False
if ok:
    print("  All lines aligned ✓")

# === RENDER ===
FONT_SIZE = 15
FONT_ASCII = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", FONT_SIZE, index=0)
FONT_CJK = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", FONT_SIZE, index=0)

CELL_W = FONT_ASCII.getlength("M")
CELL_H = int(FONT_SIZE * 1.55)
PAD_X = 28
PAD_Y = 22

max_cols = max(col_width(line) for line in LINES)
img_w = int(max_cols * CELL_W + PAD_X * 2)
img_h = int(len(LINES) * CELL_H + PAD_Y * 2)

img = Image.new("RGB", (img_w, img_h), "white")
draw = ImageDraw.Draw(img)

for row, line in enumerate(LINES):
    col = 0
    for ch in line:
        x = PAD_X + col * CELL_W
        y = PAD_Y + row * CELL_H
        wide = is_wide(ch)
        if wide:
            slot_w = CELL_W * 2
            glyph_w = FONT_CJK.getlength(ch)
            draw.text((x + (slot_w - glyph_w) / 2, y), ch, font=FONT_CJK, fill="black")
        else:
            draw.text((x, y), ch, font=FONT_ASCII, fill="black")
        col += 2 if wide else 1

out_path = os.path.expanduser("~/Desktop/nexus-architecture-v10.1-cn.png")
img.save(out_path, "PNG")
print(f"\nSaved: {out_path}")
print(f"Size: {img_w}x{img_h}px, {len(LINES)} lines, max {max_cols} cols")
