# -*- coding: utf-8 -*-
"""
trainer_assembler_v16.py
A股「一进二」盘感决策刷题机多版本纯离线单文件 HTML 统一组装器
支持一键组装 5 年全量库、第 1 辑经典 8 关、第 2 辑实战 8 关的免密与口令加密版（共 11 个交付 HTML 文件）
"""
import os
import sys
import re
import json
import base64
import hashlib
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTESTS_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BACKTESTS_DIR, 'data_5y')

sys.path.append(SCRIPT_DIR)
from astock2_trainer_css import CSS_FULL

# 默认口令混淆（杜绝源码中出现明文字符串）
DEFAULT_SALT = 'astock2_seed_v16_sec'
ENCRYPT_PWD_PARTS = [chr(48), chr(53), chr(50), chr(49), chr(48), chr(49)]
DEFAULT_PWD = "".join(ENCRYPT_PWD_PARTS)

def derive_key(pwd, salt=DEFAULT_SALT):
    return hashlib.sha256((pwd + salt).encode('utf-8')).hexdigest()

def xor_stream(data_bytes, key_hex):
    out = bytearray(len(data_bytes))
    block_idx = 0
    offset = 0
    while offset < len(data_bytes):
        keystream_block = hashlib.sha256((key_hex + f"_{block_idx}").encode("utf-8")).digest()
        chunk_len = min(32, len(data_bytes) - offset)
        for j in range(chunk_len):
            out[offset + j] = data_bytes[offset + j] ^ keystream_block[j]
        offset += chunk_len
        block_idx += 1
    return bytes(out)

def load_static_assets():
    with open(os.path.join(SCRIPT_DIR, 'trainer_frontend_v16.js'), 'r', encoding='utf-8') as f:
        fe_js = f.read()
    with open(os.path.join(SCRIPT_DIR, 'astock2_unlocker_template.js'), 'r', encoding='utf-8') as f:
        unlock_js = f.read()
    with open(os.path.join(SCRIPT_DIR, 'astock2_sh_series.js'), 'r', encoding='utf-8') as f:
        sh_js = f.read()
    return fe_js, unlock_js, sh_js


MAIN_CONTAINER_HTML = """
    <!-- 顶部全局仪表盘与控制台 -->
    <header class="top-header">
        <div class="brand-title">
            <span class="brand-tag">实战决策实验室</span>
            <span>A 股「一进二」盘感决策刷题机（量化机械定式）</span>
        </div>
        <div class="stats-summary">
            <div class="stat-pill">
                <span class="stat-label">已练题数</span>
                <span class="stat-val" id="stat-total">0</span>
            </div>
            <div class="stat-pill">
                <span class="stat-label">真龙晋级率</span>
                <span class="stat-val" id="stat-acc" style="color:#2563eb;">0.0%</span>
            </div>
            <div class="stat-pill">
                <span class="stat-label">你的累计收益 (NAV)</span>
                <span class="stat-val" id="stat-nav" style="color:#dc2626;">+0.00%</span>
            </div>
            <div class="stat-pill">
                <span class="stat-label">量化机械定式收益</span>
                <span class="stat-val" id="stat-sys-nav" style="color:#6b7280;">+0.00%</span>
            </div>
            <div class="stat-pill">
                <span class="stat-label">击败量化定式</span>
                <span class="stat-val" id="stat-beats" style="color:#059669;">0 次</span>
            </div>
            <button class="toolbar-btn" onclick="resetStats()" style="color:#dc2626;font-size:11px;padding:3px 8px;">清空重测</button>
        </div>
    </header>

    <!-- 工具与跳转栏 -->
    <div class="toolbar">
        <div class="toolbar-group">
            <label style="font-weight:700;font-size:12px;color:#374151;">题库分类：</label>
            <select id="mode-select" class="mode-select" onchange="applyFilterMode(this.value)">
                <option value="all">全量客观题库（2022-2026 全景）</option>
                <option value="dragon">真龙二板晋级局（妖股萌芽）</option>
                <option value="empty">全场退潮大冰点局（空仓保命局）</option>
                <option value="wrong">我的错题本（针对性复盘）</option>
                <option value="2026">2026 年实战切面</option>
                <option value="2025">2025 年实战切面</option>
                <option value="2024">2024 年实战切面</option>
                <option value="2023">2023 年实战切面</option>
                <option value="2022">2022 年实战切面</option>
            </select>
            <span id="filter-count-badge" style="font-size:11px;color:#6b7280;background:#f3f4f6;padding:2px 8px;font-weight:600;"></span>
            <span style="font-size:11px;color:#6b7280;margin-left:8px;">【快捷键】A/B/C/D/E 作答 | [空格] 下一题 | [R] 重做本题 | [M] 盲测 | [V] 语音讲题</span>
        </div>
        <div class="toolbar-group">
            <button class="toolbar-btn" id="btn-tts" onclick="toggleVoiceExplain()" style="background:#fef3c7;border-color:#f59e0b;color:#92400e;font-weight:700;">🔊 语音讲题 [V]</button>
            <button class="toolbar-btn" onclick="resetCurrentCase()" style="background:#fff1f2;border-color:#fda4af;color:#be123c;font-weight:700;">🔄 重做本题 [R]</button>
            <button class="toolbar-btn" id="btn-blind" onclick="toggleBlindMode()">盲测模式：关闭（显示真实股票名）</button>
            <button class="toolbar-btn" id="btn-toggle-sysrank" onclick="toggleSysRank()" style="background:#eff6ff;border-color:#93c5fd;color:#1d4ed8;">量化个股排名：已开启（点击隐藏）</button>
            <button class="toolbar-btn" onclick="prevCase()">← 上一题</button>
            <button class="toolbar-btn primary" onclick="nextCase()">下一题 →</button>
            <button class="toolbar-btn" onclick="randomCase()">🎲 随机抽题</button>
            <span style="font-size:11px;color:#6b7280;">跳至题号:</span>
            <input type="number" id="jump-input" class="jump-input" min="1" onchange="jumpToCaseNumber(this.value)"/>
            <span id="progress-text" style="font-family:monospace;font-size:12px;color:#374151;font-weight:700;"></span>
        </div>
    </div>

    <!-- 关卡抬头横幅 -->
    <div class="case-banner">
        <div>
            <div class="case-title" id="case-title">加载中...</div>
            <div class="case-sub" id="case-sub">决策切面：09:25:05</div>
        </div>
        <div class="case-phase-pill" id="case-phase">大盘客观环境计算中...</div>
    </div>

    <!-- 模块一：大盘前6个月大势与前30日短线双视角 + 昨日投机情绪仪表盘 -->
    <section class="section-card">
        <div class="section-header">
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="module-tag">模块一</span>
                <span>上证指数前 6 个月大势与前 30 日短线双视角 + 昨日投机情绪与今日竞价总盘面</span>
            </div>
            <span style="font-size:11px;color:#6b7280;">站在 09:25:05 审视大盘半年牛熊大位置、短线突破节奏与情绪熔断阈值</span>
        </div>
        <div class="grid-module-1">
            <div>
                <div style="font-size:12px;font-weight:700;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">
                    <span>上证前 6 个月大势（125日 · 20日/60日均线）</span>
                    <span id="sh-halfyear-range" style="font-size:11px;color:#6b7280;font-family:monospace;"></span>
                </div>
                <div id="index-kline-6m" style="width:100%;height:230px;border:1px solid #e5e7eb;"></div>
            </div>
            <div>
                <div style="font-size:12px;font-weight:700;margin-bottom:6px;display:flex;justify-content:space-between;align-items:center;">
                    <span>上证近 30 日短线（5日/20日均线）</span>
                    <span style="font-size:11px;color:#6b7280;">虚线后作答揭晓</span>
                </div>
                <div id="index-kline-30d" style="width:100%;height:230px;border:1px solid #e5e7eb;"></div>
            </div>
            <div>
                <div style="font-size:12px;font-weight:700;margin-bottom:6px;">昨日投机情绪与今日竞价总盘面</div>
                <div style="border:1px solid #e5e7eb;background:#fafafa;padding:6px 8px;">
                    <table class="sentiment-metrics-table">
                        <tr>
                            <td class="sentiment-label">昨日涨停 / 跌停</td>
                            <td class="sentiment-value" id="sent-zt-dt">--</td>
                        </tr>
                        <tr>
                            <td class="sentiment-label">昨日非一字首板</td>
                            <td class="sentiment-value" id="sent-first">--</td>
                        </tr>
                        <tr>
                            <td class="sentiment-label">昨日一进二封板率</td>
                            <td class="sentiment-value red" id="sent-promo">--</td>
                        </tr>
                        <tr>
                            <td class="sentiment-label">近5日自然晋级率</td>
                            <td class="sentiment-value" id="sent-promo-ma5">--</td>
                        </tr>
                        <tr>
                            <td class="sentiment-label">昨日最高连板高度</td>
                            <td class="sentiment-value gold" id="sent-height">--</td>
                        </tr>
                        <tr>
                            <td class="sentiment-label">今日昨首板竞价均幅</td>
                            <td class="sentiment-value" id="sent-open">--</td>
                        </tr>
                        <tr>
                            <td class="sentiment-label">今日全场一字二板</td>
                            <td class="sentiment-value" id="sent-yizi">--</td>
                        </tr>
                    </table>
                </div>
            </div>
        </div>
    </section>

    <!-- 模块二：题材战场三岔路口 -->
    <section class="section-card">
        <div class="section-header">
            <span>模块二：题材战场三岔路口（点击哪张题材卡，下方即刻切换为该题材旗下的候选股）</span>
            <span style="font-size:11px;color:#d97706;font-weight:700;">★ 题材左右顺序已随机洗牌，请根据盘前客观特征独立甄别</span>
        </div>
        <div class="themes-grid" id="themes-container"></div>
    </section>

    <!-- 模块三：首板候选股全景透视 -->
    <section class="section-card">
        <div class="section-header">
            <span id="module3-title">模块三：当前锁定题材旗下的候选首板股全景对比</span>
            <span style="font-size:11px;color:#6b7280;">09:25:05 真实盘前盘面指标（点火价纯数学预埋，绝无后视镜剧透）</span>
        </div>
        <!-- 4 张独立 K 线卡片 -->
        <div class="kline-grid" id="stock-kline-grid"></div>
        <!-- 指标透视表（精确 12 列） -->
        <div style="overflow-x:auto;">
            <table class="stocks-table">
                <thead>
                    <tr>
                        <th style="width:38px;">选项</th>
                        <th style="min-width:95px;">量化个股排名</th>
                        <th style="min-width:130px;">标的代码与名称</th>
                        <th style="min-width:165px;">题材分支 · 主业与催化</th>
                        <th style="min-width:80px;">总盘子 / 昨收价</th>
                        <th style="min-width:105px;">昨成交 / 换手 / 量比</th>
                        <th style="min-width:130px;">前一日炸板与封单</th>
                        <th style="min-width:125px;">20日回撤 / 位置 / 前1日</th>
                        <th style="min-width:76px;">09:25竞价</th>
                        <th style="min-width:118px;">竞价题材内 / 全场第几</th>
                        <th style="min-width:98px;">相比第2名差多少</th>
                        <th style="color:#d97706;min-width:155px;">09:26 点火条件单</th>
                    </tr>
                </thead>
                <tbody id="stocks-table-body"></tbody>
            </table>
        </div>
    </section>

    <!-- 模块四：决策拍板与战术推演 -->
    <section class="section-card" style="border:2px solid #111827;background:#ffffff;">
        <div class="section-header" style="border-bottom:1px solid #111827;">
            <span style="font-size:14px;color:#111827;">模块四：09:25:05 决策拍板（请下达唯一的狙击指令）</span>
            <span style="font-size:12px;color:#4b5563;">09:26 按点火触发价预埋股价条件单（实盘委托挂卖五价防滑点，未触发撤单记 0%）：买进未封二板次日高开不足 0.5% 竞价止损，封死二板则次日十点半看是否站稳均价与涨停格局兑现</span>
        </div>
        <div class="action-buttons" id="action-buttons-group"></div>
    </section>

    <!-- 模块五：揭晓复盘卡 -->
    <section class="section-card result-card" id="result-reveal-card" style="display:none;">
        <div class="result-header" id="result-header-bar">
            <span style="font-size:15px;font-weight:800;" id="result-header-title">狙击裁决</span>
            <div style="display:flex;align-items:center;">
                <button class="toolbar-btn" onclick="resetCurrentCase()" style="background:#ffffff;border-color:#be123c;color:#be123c;font-weight:700;margin-right:8px;">🔄 重做本题 [R]</button>
                <button class="toolbar-btn" id="btn-tts-result" onclick="toggleVoiceExplain()" style="background:#ffffff;border-color:#d97706;color:#92400e;font-weight:700;margin-right:8px;">🔊 语音复盘本题</button>
                <button class="toolbar-btn primary" onclick="nextCase()">下一题 [空格] &rarr;</button>
            </div>
        </div>
        <div style="padding:14px;">
            <div id="result-verdict-text" style="font-size:13px;line-height:1.7;color:#111827;margin-bottom:12px;"></div>
            <div class="postmortem-grid" id="postmortem-grid"></div>
        </div>
    </section>
"""


def customize_for_8level(main_html, fe_js, stats_key='astock2_external_8level_v1', edition_name='经典八关体验版'):
    # 1. 净化过滤选项并更新标题
    res_html = re.sub(r'\s*<option value="202[1-6]">.*?</option>', '', main_html)
    res_html = res_html.replace('全量客观题库（2022-2026 全景）', f'全量挑战（共 8 关）')
    res_html = res_html.replace('实战决策实验室', 'A股短线实战挑战')
    res_html = res_html.replace('A 股「一进二」盘感决策刷题机（量化机械定式）', f'A 股「一进二」盘感挑战赛 · {edition_name}')
    
    # 2. 插入 30 秒折叠挑战指南
    guide_banner = """
    <div id="external-guide-box" style="background:#fffbeb;border:1px solid #f59e0b;padding:10px 14px;margin-bottom:12px;font-size:12px;line-height:1.65;color:#1f2937;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-weight:800;color:#92400e;margin-bottom:4px;">
            <span>🎯 挑战规则（30 秒看懂怎么玩 · 共 8 关真实历史早盘切面）</span>
            <button class="toolbar-btn" onclick="var b=document.getElementById('guide-detail');b.style.display=b.style.display==='none'?'block':'none';" style="font-size:11px;padding:1px 8px;">展开 / 收起</button>
        </div>
        <div id="guide-detail">
            1. <strong>你的身份</strong>：站在真实历史交易日早盘 <strong>09:25 集合竞价刚结束那一秒</strong>，面对昨日涨停首板池，从 3 个热点题材中挑出<strong>唯一一只今日最有望晋级二连板的真龙头（A/B/C/D）</strong>；若判断全场退潮大面，果断选 <strong>E 空仓保命</strong>。<br/>
            2. <strong>真实撮合裁判</strong>：09:26 按点火触发价预埋股价条件单（实盘委托挂卖五价防滑点，未触发撤单记 0%）：买进未封二板次日高开不足 0.5% 竞价止损，封死二板则次日十点半看是否站稳均价与涨停格局兑现！<br/>
            3. <strong>辅助功能</strong>：点击顶部 <strong>「🔊 语音讲题」</strong> 可听普通话盘前解读与盘后复盘；做完全部 8 关将自动生成你的<strong>专属游资段位战报</strong>！
        </div>
    </div>
    <div id="final-8level-report" style="display:none;border:2px solid #111827;background:#fefce8;padding:14px 18px;margin-bottom:14px;"></div>
    """
    res_html = res_html.replace('<!-- 关卡抬头横幅 -->', guide_banner + '\n    <!-- 关卡抬头横幅 -->')
    res_html = res_html.replace('量化个股排名：已开启（点击隐藏）', '量化个股排名：已隐藏（点击查看）')
    
    # 3. 定制前端 JS（独立 STATS_KEY + 默认隐藏量化排名 + 注入段位战报逻辑）
    res_fe = fe_js.replace("const STATS_KEY = 'astock2_trainer_stats_5y';", f"const STATS_KEY = '{stats_key}';")
    res_fe = res_fe.replace("window.showSysRank = true;", "window.showSysRank = false;")
    
    extra_report_js = f"""
function render8LevelFinalReport() {{
    const box = document.getElementById('final-8level-report');
    if (!box) return;
    if (userStats.totalAnswered < allCases.length) {{
        box.style.display = 'none';
        return;
    }}
    const totRet = (userStats.cumNav - 1.0) * 100;
    const sysRet = (userStats.systemNav - 1.0) * 100;
    const acc = (userStats.correctCount / allCases.length * 100).toFixed(1);
    let rankTitle = '稳健实战派选手';
    if (totRet >= 25 && userStats.correctCount >= 5) rankTitle = '🏆 顶级主线点火游资';
    else if (totRet >= 10) rankTitle = '🔥 敏锐龙头猎手';
    else if (totRet >= 0) rankTitle = '🛡️ 严守纪律防守专家';
    else rankTitle = '🌱 潜力进阶打板选手';
    const shareTxt = `我在【A股一进二盘感挑战赛·{edition_name}】斩获「${{rankTitle}}」称号！8关累计净值收益 ${{totRet>=0?'+':''}}${{totRet.toFixed(2)}}%（同期量化基准 ${{sysRet>=0?'+':''}}${{sysRet.toFixed(2)}}%），抓中真龙/避险准确率 ${{acc}}%，击败量化定式 ${{userStats.beatSystemCount}} 次！`;
    window._lastShareTxt = shareTxt;
    box.style.display = 'block';
    box.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
                <div style="font-size:16px;font-weight:900;color:#111827;">🎉 恭喜完成全部 8 关实战挑战！你的段位：<span style="color:#b91c1c;">${{rankTitle}}</span></div>
                <div style="font-size:13px;color:#374151;margin-top:4px;">
                    8 关累计净收益：<strong style="color:${{totRet>=0?'#dc2626':'#16a34a'}};font-size:15px;">${{totRet>=0?'+':''}}${{totRet.toFixed(2)}}%</strong>
                    &nbsp;|&nbsp; 同期量化基准：<strong>${{sysRet>=0?'+':''}}${{sysRet.toFixed(2)}}%</strong>
                    &nbsp;|&nbsp; 最优解命中率：<strong>${{userStats.correctCount}}/${{allCases.length}} (${{acc}}%)</strong>
                    &nbsp;|&nbsp; 击败量化定式：<strong>${{userStats.beatSystemCount}} 次</strong>
                </div>
            </div>
            <div style="display:flex;gap:8px;">
                <button class="toolbar-btn primary" onclick="navigator.clipboard&&navigator.clipboard.writeText(window._lastShareTxt).then(()=>alert('战绩文案已复制，可直接粘贴发给好友！'))">📋 复制我的战绩</button>
                <button class="toolbar-btn" onclick="resetStats()" style="color:#dc2626;border-color:#fca5a5;">🔄 清空重新挑战</button>
            </div>
        </div>
    `;
}}
const _origUpdateStatsUI = updateStatsUI;
updateStatsUI = function() {{
    _origUpdateStatsUI();
    render8LevelFinalReport();
}};
"""
    res_fe = res_fe + "\n" + extra_report_js
    return res_html, res_fe


def build_unlocked_html_content(data_json_str, main_html, fe_js, sh_js, page_title):
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <style>{CSS_FULL}</style>
</head>
<body>
    <div class="container">
        {main_html}
    </div>
    <script>
    const DATA_5Y = {data_json_str};
    {sh_js}
    {fe_js}
    window.addEventListener('DOMContentLoaded', () => {{
        initTrainerApp(DATA_5Y);
    }});
    </script>
</body>
</html>"""

def build_locked_html_content(data_json_str, main_html, fe_js, sh_js, unlock_js, page_title, password=DEFAULT_PWD, salt=DEFAULT_SALT):
    data_bytes = data_json_str.encode('utf-8')
    key_hex = derive_key(password, salt)
    enc_bytes = xor_stream(data_bytes, key_hex)
    enc_b64 = base64.b64encode(enc_bytes).decode('ascii')
    
    lock_screen_html = f"""
    <div id="lock-screen" class="lock-screen-wrapper">
        <div class="lock-card">
            <div class="lock-title">
                <span style="font-size:22px;">🔒</span>
                <span>{page_title}</span>
            </div>
            <div style="font-size:11px;font-weight:700;color:#111827;margin-bottom:12px;background:#fef3c7;padding:4px 8px;border:1px solid #f59e0b;">
                内部实战专版（纯离线单文件 · 安全加密）
            </div>
            <div class="lock-desc">
                本题库已采用纯本地哈希加密保护，解密计算完全在您本机浏览器内存中进行，无需联网，无需外部依赖。
            </div>
            <div style="margin-bottom:6px;font-weight:700;font-size:12px;">请输入内部访问口令：</div>
            <input type="password" id="pwd-input" class="lock-input" placeholder="输入访问口令解锁" autocomplete="current-password" autofocus />
            <button class="lock-btn" onclick="attemptUnlock()">立即解锁题库</button>
            <div id="pwd-error" style="display:none;color:#dc2626;font-size:12px;margin-top:8px;font-weight:700;"></div>
            <div style="margin-top:16px;font-size:11px;color:#9ca3af;text-align:center;">
                提示：支持本地离线双击打开与微信内置浏览器（口令请联系分享人获取）
            </div>
        </div>
    </div>
    """
    
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <style>{CSS_FULL}</style>
</head>
<body>
    {lock_screen_html}
    <div id="main-app-container" class="container" style="display:none;">
        {main_html}
    </div>
    <script>
    const ENCRYPTED_PAYLOAD = "{enc_b64}";
    const EXPECTED_HASH = "{key_hex}";
    const SALT = "{salt}";
    
    {unlock_js}
    {sh_js}
    {fe_js}
    
    function attemptUnlock() {{
        const inputEl = document.getElementById('pwd-input');
        const errEl = document.getElementById('pwd-error');
        const pwd = inputEl ? inputEl.value.trim() : '';
        if (!pwd) {{
            if (errEl) {{ errEl.textContent = '请输入访问口令！'; errEl.style.display = 'block'; }}
            return;
        }}
        
        const inputHash = sha256(pwd + SALT);
        if (inputHash !== EXPECTED_HASH) {{
            if (errEl) {{ errEl.textContent = '❌ 口令错误，请重新输入！'; errEl.style.display = 'block'; }}
            if (inputEl) {{ inputEl.select(); }}
            return;
        }}
        
        try {{
            const jsonStr = xor_decrypt_b64(ENCRYPTED_PAYLOAD, inputHash);
            const data = JSON.parse(jsonStr);
            document.getElementById('lock-screen').style.display = 'none';
            document.getElementById('main-app-container').style.display = 'block';
            try {{
                sessionStorage.setItem('astock2_trainer_unlocked', '1');
                sessionStorage.setItem('astock2_trainer_pwd', pwd);
            }} catch(e) {{}}
            initTrainerApp(data);
        }} catch(e) {{
            if (errEl) {{ errEl.textContent = '❌ 解密失败或数据损坏！'; errEl.style.display = 'block'; }}
        }}
    }}
    
    window.addEventListener('DOMContentLoaded', () => {{
        const inputEl = document.getElementById('pwd-input');
        if (inputEl) {{
            inputEl.addEventListener('keydown', (e) => {{
                if (e.key === 'Enter') attemptUnlock();
            }});
        }}
        try {{
            const savedUnlocked = sessionStorage.getItem('astock2_trainer_unlocked');
            const savedPwd = sessionStorage.getItem('astock2_trainer_pwd');
            if (savedUnlocked === '1' && savedPwd) {{
                const inputHash = sha256(savedPwd + SALT);
                if (inputHash === EXPECTED_HASH) {{
                    const jsonStr = xor_decrypt_b64(ENCRYPTED_PAYLOAD, inputHash);
                    const data = JSON.parse(jsonStr);
                    document.getElementById('lock-screen').style.display = 'none';
                    document.getElementById('main-app-container').style.display = 'block';
                    initTrainerApp(data);
                }}
            }}
        }} catch(e) {{}}
    }});
    </script>
</body>
</html>"""


def assemble_all_htmls(data_dir=DATA_DIR, out_dir=BACKTESTS_DIR, dry_run=False):
    fe_js, unlock_js, sh_js = load_static_assets()
    
    tasks = [
        # (数据文件名, 版本名, stats_key, [免密路径列表], [口令路径列表])
        # 注意：原 357 关 1to2_trainer_5y*.html 保留不动作为后续套卷母库备份，本次生成第 1 套 100 题标准卷 + 第1/2辑 8 关卷
        (
            'trainer_pack1_100_v17.json',
            '第1套标准百题卷（100关）',
            'astock2_trainer_stats_pack1_100',
            ['1to2_trainer_pack1_100.html', 'A股一进二盘感刷题机_第1套100题免密版.html'],
            ['1to2_trainer_pack1_100_locked.html', 'A股一进二盘感刷题机_第1套100题口令版.html'],
            False # is_8level
        ),
        (
            'trainer_q1_v16.json',
            '经典八关体验版',
            'astock2_external_8level_v1',
            ['1to2_trainer_q1.html', 'A股一进二盘感挑战赛_8关免密版.html'],
            ['1to2_trainer_q1_locked.html', 'A股一进二盘感挑战赛_8关口令版.html'],
            True # is_8level
        ),
        (
            'trainer_q2_v16.json',
            '实战八关进阶版',
            'astock2_external_8level_v2',
            ['1to2_trainer_q2.html', 'A股一进二盘感挑战赛_第2辑8关免密版.html'],
            ['1to2_trainer_q2_locked.html', 'A股一进二盘感挑战赛_第2辑8关口令版.html'],
            True # is_8level
        ),
        (
            'trainer_q3_v17.json',
            '精选八关第3辑',
            'astock2_external_8level_v3',
            ['1to2_trainer_q3.html', 'A股一进二盘感挑战赛_第3辑8关免密版.html'],
            ['1to2_trainer_q3_locked.html', 'A股一进二盘感挑战赛_第3辑8关口令版.html'],
            True # is_8level
        ),
    ]
    
    total_written = 0
    for json_name, ed_name, skey, unlock_files, lock_files, is_8lvl in tasks:
        json_path = os.path.join(data_dir, json_name)
        if not os.path.exists(json_path):
            print(f"[跳过] 数据文件不存在: {json_path}")
            continue
        
        with open(json_path, 'r', encoding='utf-8') as f:
            data_str = f.read()
            
        cur_html = MAIN_CONTAINER_HTML
        cur_fe = fe_js
        if is_8lvl:
            cur_html, cur_fe = customize_for_8level(cur_html, cur_fe, stats_key=skey, edition_name=ed_name)
            
        page_title = f"A股「一进二」盘感决策刷题机 · {ed_name}"
        
        # 1. 生成免密版
        unlocked_content = build_unlocked_html_content(data_str, cur_html, cur_fe, sh_js, page_title)
        for uf in unlock_files:
            out_p = os.path.join(out_dir, uf)
            if not dry_run:
                with open(out_p, 'w', encoding='utf-8') as f:
                    f.write(unlocked_content)
                size_kb = round(os.path.getsize(out_p) / 1024, 1)
                print(f"已生成免密版 HTML: {out_p} ({size_kb} KB)")
            else:
                print(f"[Dry-run] 准备写入: {out_p}")
            total_written += 1
            
        # 2. 生成口令版
        locked_content = build_locked_html_content(data_str, cur_html, cur_fe, sh_js, unlock_js, page_title)
        for lf in lock_files:
            out_p = os.path.join(out_dir, lf)
            if not dry_run:
                with open(out_p, 'w', encoding='utf-8') as f:
                    f.write(locked_content)
                size_kb = round(os.path.getsize(out_p) / 1024, 1)
                print(f"已生成口令版 HTML: {out_p} ({size_kb} KB)")
            else:
                print(f"[Dry-run] 准备写入: {out_p}")
            total_written += 1
            
    print(f"\n组装处理完成，共处理目标文件数: {total_written}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="一进二刷题机 HTML 组装器")
    parser.add_argument('--dry-run', action='store_true', help="仅检查而不实际写入")
    parser.add_argument('--data-dir', default=DATA_DIR, help="JSON 数据目录")
    parser.add_argument('--out-dir', default=BACKTESTS_DIR, help="HTML 输出目录")
    args = parser.parse_args()
    
    assemble_all_htmls(data_dir=args.data_dir, out_dir=args.out_dir, dry_run=args.dry_run)
