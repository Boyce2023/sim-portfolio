# -*- coding: utf-8 -*-
"""trainer_assembler_v18.py: V19 刷题机与 5 关挑战赛单文件 HTML 统一组装器"""
import os, sys, re, shutil
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTESTS_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BACKTESTS_DIR, "data_5y")
DELIVERY_DIR = os.path.join(BACKTESTS_DIR, "最新交付题库")
sys.path.append(SCRIPT_DIR)
from trainer_assembler_v16 import load_static_assets, MAIN_CONTAINER_HTML, build_unlocked_html_content

def customize_for_5level(main_html, fe_js, stats_key="astock2_v19_chal5", edition_name="V19第1辑5关"):
    res_html = re.sub(r'\s*<option value="202[1-6]">.*?</option>', "", main_html)
    res_html = res_html.replace("全量客观题库（2022-2026 全景）", "全量挑战（共 5 关）")
    res_html = res_html.replace("实战决策实验室", "A股短线实战盲测")
    res_html = res_html.replace("A 股「一进二」盘感决策刷题机（量化机械定式）", f"A 股「一进二」盘感挑战赛 · {edition_name}")
    guide_banner = """
    <div id="external-guide-box" style="background:#fffbeb;border:1px solid #f59e0b;padding:10px 14px;margin-bottom:12px;font-size:12px;line-height:1.65;color:#1f2937;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-weight:800;color:#92400e;margin-bottom:4px;">
            <span>作答规则（共 5 关真实历史早盘 09:25 切面）</span>
            <button class="toolbar-btn" onclick="var b=document.getElementById('guide-detail');b.style.display=b.style.display==='none'?'block':'none';" style="font-size:11px;padding:1px 8px;">展开 / 收起</button>
        </div>
        <div id="guide-detail">
            1. <strong>盲测视角</strong>：站在真实历史交易日早盘 <strong>09:25 集合竞价刚结束那一秒</strong>，从 3 个热点题材中选出唯一一只目标股（A/B/C/D），或选 <strong>E 空仓防守</strong>。<br/>
            2. <strong>撮合裁判（V19 定式）</strong>：09:26 按点火触发价预埋条件单（11:30 前未触及则撤单记 0.00%）；未封二板次日高开不足 +0.5% 竞价止损；封死二板次日 10:30 看均价线与涨停兑现，若次日开盘在 -6.5% 至 +2.5% 且雪球热帖不足 4 帖、二板封成比低于 25% 留至收盘清仓；主轨空仓时第 2 或第 3 主线低位暗牌硬催化头名可走候补轨。<br/>
            3. <strong>结果核算</strong>：全部答完后按累计净收益与相对量化基准超额给出实话实说的客观评估。
        </div>
    </div>
    """
    res_html = res_html.replace("<!-- 关卡抬头横幅 -->", guide_banner + "\n    <!-- 关卡抬头横幅 -->")
    res_html = res_html.replace("量化个股排名：已开启（点击隐藏）", "量化个股排名：已隐藏（点击查看）")
    res_fe = fe_js.replace("const STATS_KEY = 'astock2_trainer_stats_5y';", f"const STATS_KEY = '{stats_key}';")
    res_fe = res_fe.replace("window.showSysRank = true;", "window.showSysRank = false;")
    return res_html, res_fe

def clean_chinese_text(content):
    return content.replace("五板策略", "主线策略").replace("零未来函数", "严守先验").replace("——", "至").replace("—", "至")

def assemble_v18_deliverables(out_dir=DELIVERY_DIR):
    desk_dir = "/Users/huaichuaibeimeng/Desktop/短线/题目"
    os.makedirs(out_dir, exist_ok=True)
    fe_js, _, sh_js = load_static_assets()
    fe_js = clean_chinese_text(fe_js)
    tasks = [
        ("trainer_pack1_50_v19.json", "V19第1套50题", "astock2_trainer_stats_v19_pack1", os.path.join(out_dir, "一进二_50题.html"), False),
        ("trainer_chal5_v19.json", "V19第1辑5关", "astock2_trainer_stats_v19_chal5", os.path.join(out_dir, "一进二_5关.html"), True),
    ]
    for json_name, ed_name, skey, unlock_p, is_chal in tasks:
        data_str = open(os.path.join(DATA_DIR, json_name), encoding="utf-8").read()
        cur_html = MAIN_CONTAINER_HTML
        cur_fe = fe_js.replace("const STATS_KEY = 'astock2_trainer_stats_5y';", f"const STATS_KEY = '{skey}';")
        if is_chal:
            cur_html, cur_fe = customize_for_5level(MAIN_CONTAINER_HTML, fe_js, stats_key=skey, edition_name=ed_name)
        page_title = f"A股「一进二」盘感决策刷题机 · {ed_name}" if not is_chal else f"A股「一进二」盘感挑战赛 · {ed_name}"
        unlocked_content = clean_chinese_text(build_unlocked_html_content(data_str, cur_html, cur_fe, sh_js, page_title))
        open(unlock_p, "w", encoding="utf-8").write(unlocked_content)
        os.makedirs(desk_dir, exist_ok=True)
        shutil.copy2(unlock_p, os.path.join(desk_dir, os.path.basename(unlock_p)))
        print(f"已生成: {unlock_p} ({os.path.getsize(unlock_p)/1024:.1f} KB)")

if __name__ == "__main__":
    assemble_v18_deliverables()
