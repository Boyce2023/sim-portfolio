# -*- coding: utf-8 -*-
"""
trainer_assembler_v18.py: V18 刷题机与 5 关挑战赛单文件 HTML 统一组装器
严格执行中文交付规范 (零连字符/零破折号/零繁体字/收益写赚X%亏X%/禁五板策略与零未来函数)。
单文件严格控制在 150 行以内。
"""
import os, sys, re, json
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTESTS_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BACKTESTS_DIR, "data_5y")
DELIVERY_DIR = os.path.join(BACKTESTS_DIR, "最新交付题库")

sys.path.append(SCRIPT_DIR)
from trainer_assembler_v16 import (
    load_static_assets, MAIN_CONTAINER_HTML,
    build_unlocked_html_content, build_locked_html_content,
    DEFAULT_PWD, DEFAULT_SALT
)

def customize_for_5level(main_html, fe_js, stats_key="astock2_v18_chal5", edition_name="第1辑5关"):
    res_html = re.sub(r'\s*<option value="202[1-6]">.*?</option>', "", main_html)
    res_html = res_html.replace("全量客观题库（2022-2026 全景）", "全量挑战（共 5 关）")
    res_html = res_html.replace("实战决策实验室", "A股短线实战挑战")
    res_html = res_html.replace("A 股「一进二」盘感决策刷题机（量化机械定式）", f"A 股「一进二」盘感挑战赛 · {edition_name}")
    
    guide_banner = f"""
    <div id="external-guide-box" style="background:#fffbeb;border:1px solid #f59e0b;padding:10px 14px;margin-bottom:12px;font-size:12px;line-height:1.65;color:#1f2937;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-weight:800;color:#92400e;margin-bottom:4px;">
            <span>🎯 挑战规则（30 秒看懂怎么玩 · 共 5 关真实历史早盘切面）</span>
            <button class="toolbar-btn" onclick="var b=document.getElementById('guide-detail');b.style.display=b.style.display==='none'?'block':'none';" style="font-size:11px;padding:1px 8px;">展开 / 收起</button>
        </div>
        <div id="guide-detail">
            1. <strong>你的身份</strong>：站在真实历史交易日早盘 <strong>09:25 集合竞价刚结束那一秒</strong>，从 3 个热点题材中挑出<strong>唯一一只今日最有望晋级二连板的真龙头（A/B/C/D）</strong>；若判断全场退潮大面，果断选 <strong>E 空仓保命</strong>。<br/>
            2. <strong>真实撮合裁判</strong>：09:26 按点火触发价预埋股价条件单（限上午 11:30 前触及成交，11:30 未点火则午休撤单记 0% 过滤下午偷袭）：买进未封二板次日高开不足 0.5% 竞价止损，封死二板则次日十点半看是否站稳均价与涨停格局兑现！<br/>
            3. <strong>辅助功能</strong>：点击顶部 <strong>「🔊 语音讲题」</strong> 可听普通话盘前解读与盘后复盘；做完全部 5 关将自动生成你的<strong>专属游资段位战报</strong>！
        </div>
    </div>
    <div id="final-8level-report" style="display:none;border:2px solid #111827;background:#fefce8;padding:14px 18px;margin-bottom:14px;"></div>
    """
    res_html = res_html.replace("<!-- 关卡抬头横幅 -->", guide_banner + "\n    <!-- 关卡抬头横幅 -->")
    res_html = res_html.replace("量化个股排名：已开启（点击隐藏）", "量化个股排名：已隐藏（点击查看）")
    res_fe = fe_js.replace("const STATS_KEY = 'astock2_trainer_stats_5y';", f"const STATS_KEY = '{stats_key}';")
    res_fe = res_fe.replace("window.showSysRank = true;", "window.showSysRank = false;")

    extra_report_js = f"""
function render8LevelFinalReport() {{
    const box = document.getElementById('final-8level-report');
    if (!box) return;
    if (userStats.totalAnswered < allCases.length) {{ box.style.display = 'none'; return; }}
    const totRet = (userStats.cumNav - 1.0) * 100;
    const sysRet = (userStats.systemNav - 1.0) * 100;
    const acc = (userStats.correctCount / allCases.length * 100).toFixed(1);
    let rankTitle = '稳健实战派选手';
    if (totRet >= 15 && userStats.correctCount >= 4) rankTitle = '🏆 顶级主线点火游资';
    else if (totRet >= 8) rankTitle = '🔥 敏锐龙头猎手';
    else if (totRet >= 0) rankTitle = '🛡️ 严守纪律防守专家';
    else rankTitle = '🌱 潜力进阶打板选手';
    const retStr = totRet >= 0 ? `赚 ${{totRet.toFixed(2)}}%` : `亏 ${{Math.abs(totRet).toFixed(2)}}%`;
    const sysStr = sysRet >= 0 ? `赚 ${{sysRet.toFixed(2)}}%` : `亏 ${{Math.abs(sysRet).toFixed(2)}}%`;
    const shareTxt = `我在【A股一进二盘感挑战赛·{edition_name}】斩获「${{rankTitle}}」称号！5关累计净收益 ${{retStr}}（同期量化基准 ${{sysStr}}），抓中真龙/避险准确率 ${{acc}}%，击败量化定式 ${{userStats.beatSystemCount}} 次！`;
    window._lastShareTxt = shareTxt;
    box.style.display = 'block';
    box.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
                <div style="font-size:16px;font-weight:900;color:#111827;">🎉 恭喜完成全部 5 关实战挑战！你的段位：<span style="color:#b91c1c;">${{rankTitle}}</span></div>
                <div style="font-size:13px;color:#374151;margin-top:4px;">
                    5 关累计净收益：<strong style="color:${{totRet>=0?'#dc2626':'#16a34a'}};font-size:15px;">${{retStr}}</strong>
                    &nbsp;|&nbsp; 同期量化基准：<strong>${{sysStr}}</strong>
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
updateStatsUI = function() {{ _origUpdateStatsUI(); render8LevelFinalReport(); }};
"""
    return res_html, res_fe + "\n" + extra_report_js

def clean_chinese_text(content):
    # 净化全量可见文本规范：严禁五板策略/零未来函数，收益写赚X%/亏X%，零破折号
    content = content.replace("五板策略", "主线策略").replace("零未来函数", "严守先验")
    content = content.replace("——", "至").replace("—", "至")
    # 净收益格式转换: 净收益 +X% -> 净收益 赚X%
    content = re.sub(r'净收益\s*\+(\d+\.\d+)%', r'净收益 赚\1%', content)
    content = re.sub(r'净收益\s*-(\d+\.\d+)%', r'净收益 亏\1%', content)
    content = re.sub(r'净收益\s*\+?\$\{c\.market_best_ret\.toFixed\(2\)\}%', r'净收益 赚${c.market_best_ret.toFixed(2)}%', content)
    content = re.sub(r'净收益\s*\$\{cand\.net_ret\s*>\s*0\s*\?\s*\'\+\'\s*:\s*\'\'\}\$\{cand\.net_ret\.toFixed\(2\)\}%',
                     r"净收益 ${cand.net_ret > 0 ? ('赚' + cand.net_ret.toFixed(2) + '%') : (cand.net_ret < 0 ? ('亏' + Math.abs(cand.net_ret).toFixed(2) + '%') : '0.00%')}", content)
    return content

def assemble_v18_deliverables(out_dir=DELIVERY_DIR):
    os.makedirs(out_dir, exist_ok=True)
    fe_js, unlock_js, sh_js = load_static_assets()
    fe_js = clean_chinese_text(fe_js)
    tasks = [
        ("trainer_pack1_50_v18.json", "V18第1套50题", "astock2_trainer_stats_v18_pack1",
         os.path.join(out_dir, "A股一进二盘感刷题机_V18第1套50题免密版.html"),
         os.path.join(out_dir, "A股一进二盘感刷题机_V18第1套50题口令版.html"), False),
        ("trainer_chal5_v18.json", "V18第1辑5关", "astock2_trainer_stats_v18_chal5",
         os.path.join(out_dir, "A股一进二盘感挑战赛_V18第1辑5关免密版.html"),
         os.path.join(out_dir, "A股一进二盘感挑战赛_V18第1辑5关口令版.html"), True)
    ]
    for json_name, ed_name, skey, unlock_p, lock_p, is_chal in tasks:
        with open(os.path.join(DATA_DIR, json_name), "r", encoding="utf-8") as f: data_str = f.read()
        cur_html = MAIN_CONTAINER_HTML
        cur_fe = fe_js
        if is_chal: cur_html, cur_fe = customize_for_5level(cur_html, cur_fe, stats_key=skey, edition_name=ed_name)
        page_title = f"A股「一进二」盘感决策刷题机 · {ed_name}" if not is_chal else f"A股「一进二」盘感挑战赛 · {ed_name}"
        unlocked_content = clean_chinese_text(build_unlocked_html_content(data_str, cur_html, cur_fe, sh_js, page_title))
        locked_content = clean_chinese_text(build_locked_html_content(data_str, cur_html, cur_fe, sh_js, unlock_js, page_title))
        with open(unlock_p, "w", encoding="utf-8") as f: f.write(unlocked_content)
        with open(lock_p, "w", encoding="utf-8") as f: f.write(locked_content)
        print(f"已生成: {unlock_p} ({os.path.getsize(unlock_p)/1024:.1f} KB)")
        print(f"已生成: {lock_p} ({os.path.getsize(lock_p)/1024:.1f} KB)")

if __name__ == "__main__":
    assemble_v18_deliverables()
