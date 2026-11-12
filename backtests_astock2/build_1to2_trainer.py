#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_1to2_trainer.py
================================================================================
一进二盘感刷题机（Decision Trainer）自包含 HTML 生成器
严守铁律：
1. 严禁 import yfinance（D12），全部基于本地只读历史数据与 akshare 上证指数缓存
2. 审美铁律：白底高对比、零圆角（border-radius: 0）、表格无竖线（仅水平细线）
3. 通俗人话配少量专有名词，严禁代码变量名
================================================================================
"""
import os
import sys
import json
import subprocess

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
OUT_HTML = os.path.join(OUT_DIR, "1to2_trainer_q1.html")
DATA_JSON_PATH = "/tmp/astock2_trainer_dataset.json"

def load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def build_html():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # 1. 读取基础数据与模块
    with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
        cases_data = json.load(f)
    cases_json_str = json.dumps(cases_data, ensure_ascii=False)
    
    css_content = load_text("/tmp/astock2_trainer_css.py").split('CSS_CONTENT = """')[1].split('"""')[0]
    svg_renderer = load_text("/tmp/astock2_svg_renderer.js")
    stock_kline = load_text("/tmp/astock2_stock_kline.js")
    app_logic_1 = load_text("/tmp/astock2_app_logic.js")
    app_logic_2 = load_text("/tmp/astock2_app_logic_p2.js")
    app_logic_3 = load_text("/tmp/astock2_app_logic_p3.js")
    
    # 2. 组装下拉选项
    select_options = ""
    for idx, c in enumerate(cases_data):
        select_options += f'<option value="{idx}">第 {c["id"]} 关（{c["year"]}年）：{c["title"][:22]}...</option>\\n'
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>一进二盘感刷题机 | 2021-2026 真实历史逐日决策训练器</title>
    <style>
{css_content}
    </style>
</head>
<body>
<div class="container">
    <!-- 顶部全局控制台与战绩看板 -->
    <header class="top-header">
        <div class="brand-title">
            <span>一进二盘感刷题机</span>
            <span class="brand-tag">决策训练器</span>
            <span style="font-size:12px;color:#6b7280;font-weight:normal;">2021至2026 真实历史盘前逐日盲测</span>
        </div>
        <div class="stats-panel">
            <div class="stat-item">
                <span class="stat-label">已刷关卡</span>
                <span class="stat-val" id="stat-total">0</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">决策准确率</span>
                <span class="stat-val red" id="stat-acc">0.0%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">避坑成功率</span>
                <span class="stat-val green" id="stat-trap">0.0%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">模拟净值倍数</span>
                <span class="stat-val gold" id="stat-nav">1.000x</span>
            </div>
            <button class="btn" style="padding:4px 8px;font-size:11px;" onclick="resetStats()">重置战绩</button>
        </div>
        <div class="controls-panel">
            <button class="btn" onclick="prevCase()">上一题</button>
            <select class="select-input" id="case-select" onchange="onSelectCaseChange()">
                {select_options}
            </select>
            <button class="btn" onclick="nextCase()">下一题</button>
            <button class="btn" onclick="randomCase()">随机抽题</button>
            <button class="blind-toggle" id="btn-blind" onclick="toggleBlindMode()">盲测模式：开启（已隐去代码与名称）</button>
        </div>
    </header>

    <!-- 关卡横幅 -->
    <div class="case-banner">
        <div>
            <div class="case-title-text" id="case-title">关卡加载中...</div>
            <div class="case-sub-text" id="case-sub">决策切面：09:25:05 盘前视角</div>
        </div>
        <div class="case-phase-pill" id="case-phase">市场环境分析</div>
    </div>

    <!-- 模块一：大盘环境与昨日情绪仪表盘 -->
    <section class="section-card">
        <div class="section-header">
            <div class="section-header-title">
                <span style="background:#111827;color:#fff;padding:1px 5px;font-size:11px;">模块一</span>
                <span>大盘指数前 30 日走势与昨日连板情绪仪表盘</span>
            </div>
            <span style="font-size:11px;color:#6b7280;">站在 09:25:05 审视大盘趋势与投机周期水位</span>
        </div>
        <div class="section-body">
            <div class="grid-module-1">
                <div>
                    <div style="font-size:12px;font-weight:700;margin-bottom:6px;display:flex;justify-content:space-between;">
                        <span>上证指数真实日 K 线（含 5日、20日均线与成交量）</span>
                        <span style="font-size:11px;color:#6b7280;">虚线右侧为作答后揭晓之走势</span>
                    </div>
                    <div id="index-kline-box" style="width:100%;height:240px;border:1px solid #e5e7eb;"></div>
                </div>
                <div>
                    <div style="font-size:12px;font-weight:700;margin-bottom:6px;">昨日市场投机情绪仪表盘</div>
                    <div style="border:1px solid #e5e7eb;background:#fafafa;padding:10px;">
                        <table class="sentiment-metrics-table">
                            <tr>
                                <td class="sentiment-label">昨日全场涨停数</td>
                                <td class="sentiment-value red" id="sent-zt">--</td>
                            </tr>
                            <tr>
                                <td class="sentiment-label">昨日首板家数</td>
                                <td class="sentiment-value" id="sent-first">--</td>
                            </tr>
                            <tr>
                                <td class="sentiment-label">昨日全场跌停数</td>
                                <td class="sentiment-value green" id="sent-dt">--</td>
                            </tr>
                            <tr>
                                <td class="sentiment-label">昨日一进二晋级率</td>
                                <td class="sentiment-value red" id="sent-promo">--</td>
                            </tr>
                            <tr>
                                <td class="sentiment-label">全场最高连板高度</td>
                                <td class="sentiment-value gold" id="sent-height">--</td>
                            </tr>
                            <tr>
                                <td class="sentiment-label">今日首板平均高开</td>
                                <td class="sentiment-value" id="sent-open">--</td>
                            </tr>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- 模块二：今日前 3 大热点题材 PK 台 -->
    <section class="section-card">
        <div class="section-header">
            <div class="section-header-title">
                <span style="background:#111827;color:#fff;padding:1px 5px;font-size:11px;">模块二</span>
                <span>今日排名前 3 大热点题材 PK 台（先练选题材主线眼光）</span>
            </div>
            <span style="font-size:11px;color:#d97706;font-weight:600;">点击题材卡片可选中标记你看好的主线</span>
        </div>
        <div class="section-body">
            <div class="themes-grid" id="themes-container"></div>
        </div>
    </section>

    <!-- 模块三：A / B / C / D 四只候选股全景对比 -->
    <section class="section-card">
        <div class="section-header">
            <div class="section-header-title">
                <span style="background:#111827;color:#fff;padding:1px 5px;font-size:11px;">模块三</span>
                <span>首板候选池四强 K 线对比与 09:25 盘前全景对比表</span>
            </div>
            <span style="font-size:11px;color:#6b7280;">D1 收盘前 30 日真实 K 线形态 + 09:25 竞价抢筹排名</span>
        </div>
        <div class="section-body">
            <!-- 4 张独立 K 线图 -->
            <div class="kline-grid" id="stock-kline-grid"></div>
            
            <!-- 全景无竖线对比表 -->
            <div class="stocks-table-wrap">
                <table class="clean-table">
                    <thead>
                        <tr>
                            <th>选项</th>
                            <th>标的名称 / 代码</th>
                            <th>细分概念与血统</th>
                            <th>流通市值</th>
                            <th>首板成交额 / 换手</th>
                            <th>量比 / 封单干脆度</th>
                            <th>前20日回撤 / 涨停</th>
                            <th>前一日涨跌</th>
                            <th>今日 09:25 竞价</th>
                            <th>板块 / 全市场排名</th>
                            <th>领先第 2 名幅度</th>
                            <th>09:30 点火触发价</th>
                        </tr>
                    </thead>
                    <tbody id="stocks-table-body"></tbody>
                </table>
            </div>
        </div>
    </section>

    <!-- 模块四：一键拍板作答 -->
    <div class="action-box">
        <div class="action-header-text">
            <span>【一键拍板作答】现在是 09:25:05，竞价结果已出炉，请做出你的决策：</span>
            <span style="font-size:12px;color:#6b7280;font-weight:normal;">点击选项立即揭晓真实行情与深度死因复盘</span>
        </div>
        <div class="action-buttons-group">
            <button class="choice-btn" data-option="A" onclick="handleChoice('A')">【选择标的 A】</button>
            <button class="choice-btn" data-option="B" onclick="handleChoice('B')">【选择标的 B】</button>
            <button class="choice-btn" data-option="C" onclick="handleChoice('C')">【选择标的 C】</button>
            <button class="choice-btn" data-option="D" onclick="handleChoice('D')">【选择标的 D】</button>
            <button class="choice-btn btn-empty" data-option="E" onclick="handleChoice('E')">【选择标的 E 今日空仓放弃】</button>
        </div>
    </div>

    <!-- 揭晓复盘卡 -->
    <div class="result-reveal-card" id="result-reveal-card">
        <div class="result-header-bar" id="result-header-bar">
            <div id="result-header-title">作答结果判定</div>
            <button class="btn" style="background:#fff;color:#111;padding:4px 10px;font-size:11px;" onclick="nextCase()">下一题 &rarr;</button>
        </div>
        <div class="result-body">
            <div style="font-size:13px;line-height:1.7;color:#1f2937;margin-bottom:12px;" id="result-verdict-text"></div>
            <div style="font-size:13px;font-weight:700;margin-top:16px;border-top:1px solid #e5e7eb;padding-top:12px;">
                4 只候选标的真实日内表现与死因铁律深度复盘：
            </div>
            <div class="postmortem-grid" id="postmortem-grid"></div>
        </div>
    </div>
</div>

<script>
const TRAINER_DATA = {cases_json_str};

{svg_renderer}

{stock_kline}

{app_logic_1}

{app_logic_2}

{app_logic_3}

// 页面初始化
window.addEventListener('DOMContentLoaded', () => {{
    updateStatsUI();
    loadCase(0);
}});
</script>
</body>
</html>
"""
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    
    file_size_kb = round(os.path.getsize(OUT_HTML) / 1024, 2)
    print(f"HTML 生成成功: {OUT_HTML} (体积: {file_size_kb} KB)")
    return OUT_HTML

if __name__ == "__main__":
    out_file = build_html()
    try:
        subprocess.run(["open", "-a", "Google Chrome", out_file], check=True)
        print("已在 Google Chrome 中自动打开训练器 HTML")
    except Exception as e:
        print(f"打开 Chrome 失败: {e}")
