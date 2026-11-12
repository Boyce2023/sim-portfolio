#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
构建「别人能直接用的」对外分享专版：经典八关一进二盘感挑战赛
单文件纯离线 HTML（无需服务器、无需压缩包，微信/飞书直接发一个文件即可点开玩）
"""
import os, re, json, base64, hashlib

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2"
SRC_5Y = "/tmp/astock2_5y_hierarchical.json"
OUT_Q1_JSON = "/tmp/astock2_q1_hierarchical.json"

with open(SRC_5Y, "r", encoding="utf-8") as f:
    cases_5y = json.load(f)

# 精选 8 道极具代表性的真实历史关卡：6 道各年份大肉真龙局（覆盖 A/B/C/D 且含人机分歧局）+ 2 道经典冰点空仓保命局（E）
picked = []
used_dates = set()

def pick_one(pred):
    for c in cases_5y:
        if c["date"] not in used_dates and pred(c):
            used_dates.add(c["date"])
            picked.append(c)
            return

# 1. 2022 熊市破冰真龙 (选项 A 或 B)
pick_one(lambda c: c["date"].startswith("2022") and c["type"] == "dragon" and c["market_best_ret"] >= 10.0 and c["market_ans"] == "A")
# 2. 2023 主线大肉真龙 (选项 B)
pick_one(lambda c: c["date"].startswith("2023") and c["type"] == "dragon" and c["market_best_ret"] >= 10.0 and c["market_ans"] == "B")
# 3. 2023 退潮核按钮空仓保命局 (选项 E)
pick_one(lambda c: c["date"].startswith("2023") and c["market_ans"] == "E" and c["sys_ret"] == 0.0)
# 4. 2024 连板主升大妖局 (选项 C)
pick_one(lambda c: c["date"].startswith("2024") and c["type"] == "dragon" and c["market_best_ret"] >= 12.0 and c["market_ans"] == "C")
# 5. 人机分歧高手局：量化空仓观望但盘感高手抓出大肉真龙 (选项 D)
pick_one(lambda c: c["type"] == "dragon" and c["market_best_ret"] >= 8.0 and c["sys_ret"] == 0.0 and c["market_ans"] == "D")
# 6. 2025 硬核主线起爆局
pick_one(lambda c: c["date"].startswith("2025") and c["type"] == "dragon" and c["market_best_ret"] >= 10.0)
# 7. 2025/2026 全场冲高炸板退潮空仓局 (选项 E)
pick_one(lambda c: c["date"] >= "2025-01-01" and c["market_ans"] == "E")
# 8. 2026 最新实战主线真龙局
pick_one(lambda c: c["date"].startswith("2026") and c["type"] == "dragon" and c["market_best_ret"] >= 8.0)

for c in cases_5y:
    if len(picked) >= 8:
        break
    if c["date"] not in used_dates and c["type"] == "dragon":
        used_dates.add(c["date"])
        picked.append(c)

picked.sort(key=lambda x: x["date"])
q8 = []
for i, c in enumerate(picked[:8]):
    cp = json.loads(json.dumps(c))
    cp["id"] = i + 1
    q8.append(cp)

with open(OUT_Q1_JSON, "w", encoding="utf-8") as f:
    json.dump(q8, f, ensure_ascii=False)

print("Selected 8 golden external cases:")
for c in q8:
    print(f"  #{c['id']} {c['date']} | ans={c['market_ans']} | {c['best_stock_name']} (+{c['market_best_ret']}%) | sys={c['sys_cand_name']} ({c['sys_ret']}%)")

# 读取前端模板并定制「对外友好的 8 关独立体验版」
import sys
sys.path.append("/tmp")
from astock2_trainer_css import CSS_FULL
with open("/tmp/astock2_unified_frontend.js", "r", encoding="utf-8") as f:
    fe_js = f.read()
with open("/tmp/astock2_unlocker_template.js", "r", encoding="utf-8") as f:
    unlock_js = f.read()
with open("/tmp/astock2_sh_series.js", "r", encoding="utf-8") as f:
    sh_js = f.read()
with open("/tmp/astock2_html_assembler.py", "r", encoding="utf-8") as f:
    asm_src = f.read()

# 提取 MAIN_CONTAINER_HTML
m = re.search(r'MAIN_CONTAINER_HTML\s*=\s*"""(.*?)"""', asm_src, re.S)
main_html = m.group(1)

# 1. 精简下拉菜单（去掉 8 关里用不到的单年份切片，防止外人点到空年份弹警告）
main_html = re.sub(r'\s*<option value="202[1-6]">.*?</option>', '', main_html)
main_html = main_html.replace('全量客观题库（2021-2026 全景）', '经典八关全量挑战（第 1~8 关）')
main_html = main_html.replace('实战决策实验室', 'A股短线实战挑战')
main_html = main_html.replace('A 股「一进二」盘感决策刷题机（Decision Trainer）', 'A 股「一进二」盘感挑战赛 · 经典八关体验版')

# 2. 顶部插入 30 秒新手玩法指南折叠卡 + 八关通关战报横幅容器
guide_banner = """
    <div id="external-guide-box" style="background:#fffbeb;border:1px solid #f59e0b;padding:10px 14px;margin-bottom:12px;font-size:12px;line-height:1.65;color:#1f2937;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-weight:800;color:#92400e;margin-bottom:4px;">
            <span>🎯 挑战规则（30 秒看懂怎么玩 · 共 8 关真实历史早盘切面）</span>
            <button class="toolbar-btn" onclick="var b=document.getElementById('guide-detail');b.style.display=b.style.display==='none'?'block':'none';" style="font-size:11px;padding:1px 8px;">展开 / 收起</button>
        </div>
        <div id="guide-detail">
            1. <strong>你的身份</strong>：站在真实历史交易日早盘 <strong>09:25 集合竞价刚结束那一秒</strong>，面对昨日涨停首板池，从 3 个热点题材中挑出<strong>唯一一只今日最有望晋级二连板的真龙头（A/B/C/D）</strong>；若判断全场退潮大面，果断选 <strong>E 空仓保命</strong>。<br/>
            2. <strong>真实撮合裁判</strong>：选中标的在 09:30 后突破盘前点火确认价即建仓（未触发则撤单记 0%）；买进后若当日未封死二板按 <strong>T+1 次日真实收盘价</strong> 结算，若封死二板则<strong>锁仓格局至断板日收盘价</strong>兑现大肉！<br/>
            3. <strong>辅助功能</strong>：点击顶部 <strong>「🔊 语音讲题」</strong> 可听普通话盘前解读与盘后复盘；做完全部 8 关将自动生成你的<strong>专属游资段位战报</strong>！
        </div>
    </div>
    <div id="final-8level-report" style="display:none;border:2px solid #111827;background:#fefce8;padding:14px 18px;margin-bottom:14px;"></div>
"""
main_html = main_html.replace('<!-- 关卡抬头横幅 -->', guide_banner + '\n    <!-- 关卡抬头横幅 -->')

# 3. 对外版独立存档 Key + 默认隐藏内部系统排名防剧透 + 八关通关战报生成与一键复制战绩
fe_ext = fe_js.replace("const STATS_KEY = 'astock2_trainer_stats_5y';", "const STATS_KEY = 'astock2_external_8level_v1';")
fe_ext = fe_ext.replace("window.showSysRank = true;", "window.showSysRank = false;")
main_html = main_html.replace('系统排名参考：已开启（点击隐藏）', '量化参考排名：已隐藏（点击查看）')

extra_report_js = """
function render8LevelFinalReport() {
    const box = document.getElementById('final-8level-report');
    if (!box) return;
    if (userStats.totalAnswered < allCases.length) {
        box.style.display = 'none';
        return;
    }
    const totRet = (userStats.cumNav - 1.0) * 100;
    const sysRet = (userStats.systemNav - 1.0) * 100;
    const acc = (userStats.correctCount / allCases.length * 100).toFixed(1);
    let rankTitle = '稳健实战派选手';
    if (totRet >= 25 && userStats.correctCount >= 5) rankTitle = '🏆 顶级主线点火游资';
    else if (totRet >= 10) rankTitle = '🔥 敏锐龙头猎手';
    else if (totRet >= 0) rankTitle = '🛡️ 严守纪律防守专家';
    else rankTitle = '🌱 潜力进阶打板选手';
    const shareTxt = `我在【A股一进二盘感挑战赛·经典8关】斩获「${rankTitle}」称号！8关累计净值收益 ${totRet>=0?'+':''}${totRet.toFixed(2)}%（同期量化基准 ${sysRet>=0?'+':''}${sysRet.toFixed(2)}%），抓中真龙/避险准确率 ${acc}%，击败量化 ${userStats.beatSystemCount} 次！`;
    window._lastShareTxt = shareTxt;
    box.style.display = 'block';
    box.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">
            <div>
                <div style="font-size:16px;font-weight:900;color:#111827;">🎉 恭喜完成全部 8 关实战挑战！你的段位：<span style="color:#b91c1c;">${rankTitle}</span></div>
                <div style="font-size:13px;color:#374151;margin-top:4px;">
                    8 关累计净收益：<strong style="color:${totRet>=0?'#dc2626':'#16a34a'};font-size:15px;">${totRet>=0?'+':''}${totRet.toFixed(2)}%</strong>
                    &nbsp;|&nbsp; 同期量化基准：<strong>${sysRet>=0?'+':''}${sysRet.toFixed(2)}%</strong>
                    &nbsp;|&nbsp; 最优解命中率：<strong>${userStats.correctCount}/${allCases.length} (${acc}%)</strong>
                    &nbsp;|&nbsp; 击败量化：<strong>${userStats.beatSystemCount} 次</strong>
                </div>
            </div>
            <div style="display:flex;gap:8px;">
                <button class="toolbar-btn primary" onclick="navigator.clipboard&&navigator.clipboard.writeText(window._lastShareTxt).then(()=>alert('战绩文案已复制，可直接粘贴发给好友！'))">📋 复制我的战绩</button>
                <button class="toolbar-btn" onclick="resetStats()" style="color:#dc2626;border-color:#fca5a5;">🔄 清空重新挑战</button>
            </div>
        </div>
    `;
}
const _origUpdateStatsUI = updateStatsUI;
updateStatsUI = function() {
    _origUpdateStatsUI();
    render8LevelFinalReport();
};
"""
fe_ext = fe_ext + "\n" + extra_report_js

data_str = json.dumps(q8, ensure_ascii=False)

# 构建免密即开对外版 & 口令保护对外版
def save_unlocked(paths):
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股「一进二」盘感挑战赛 · 经典八关体验版</title>
<style>{CSS_FULL}</style>
</head>
<body>
<div class="container">{main_html}</div>
<script>
const DATA_5Y = {data_str};
{sh_js}
{fe_ext}
window.addEventListener('DOMContentLoaded', () => {{ initTrainerApp(DATA_5Y); }});
</script>
</body>
</html>"""
    for p in paths:
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved unlocked external 8-level: {p} ({round(os.path.getsize(p)/1024, 1)} KB)")

def save_locked(paths, pwd="052101"):
    salt = "astock2_ext8_seed_29"
    kh = hashlib.sha256((pwd + salt).encode("utf-8")).hexdigest()
    raw = data_str.encode("utf-8")
    out = bytearray(len(raw))
    for blk, off in enumerate(range(0, len(raw), 32)):
        kb = hashlib.sha256((kh + f"_{blk}").encode("utf-8")).digest()
        ln = min(32, len(raw) - off)
        for j in range(ln):
            out[off + j] = raw[off + j] ^ kb[j]
    b64 = base64.b64encode(bytes(out)).decode("ascii")
    assert "0521" not in b64 and "0521" not in kh
    lock_dom = """
    <div id="lock-screen" class="lock-screen-wrapper">
        <div class="lock-card">
            <div class="lock-title"><span style="font-size:22px;">🎯</span><span>A股「一进二」盘感挑战赛</span></div>
            <div style="font-size:11px;font-weight:700;color:#111827;margin-bottom:12px;background:#fef3c7;padding:4px 8px;border:1px solid #f59e0b;">
                经典八关实战体验版（纯离线单文件 · 零外部依赖）
            </div>
            <div class="lock-desc">
                精选 2022 至 2026 年 8 道真实 A 股早盘 09:25 集合竞价历史切面。看看在没有后视镜的真实盘口前，你的盘感能否跑赢量化模型！
            </div>
            <div style="margin-bottom:6px;font-weight:700;font-size:12px;">请输入体验访问口令：</div>
            <input type="password" id="pwd-input" class="lock-input" placeholder="输入口令开始挑战" autofocus />
            <button class="lock-btn" onclick="attemptUnlock()">立即开启八关挑战</button>
            <div id="pwd-error" style="display:none;color:#dc2626;font-size:12px;margin-top:8px;font-weight:700;"></div>
            <div style="margin-top:16px;font-size:11px;color:#9ca3af;text-align:center;">
                提示：电脑双击或手机浏览器均可离线运行（口令请联系分享人获取）
            </div>
        </div>
    </div>"""
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股「一进二」盘感挑战赛 · 经典八关口令版</title>
<style>{CSS_FULL}</style>
</head>
<body>
{lock_dom}
<div id="main-app-container" class="container" style="display:none;">{main_html}</div>
<script>
const ENCRYPTED_PAYLOAD = "{b64}";
const EXPECTED_HASH = "{kh}";
const SALT = "{salt}";
{unlock_js}
{sh_js}
{fe_ext}
function attemptUnlock() {{
    const inputEl = document.getElementById('pwd-input');
    const errEl = document.getElementById('pwd-error');
    const pwd = inputEl ? inputEl.value.trim() : '';
    if (!pwd) {{ if (errEl) {{ errEl.textContent = '请输入访问口令！'; errEl.style.display = 'block'; }} return; }}
    const inputHash = sha256(pwd + SALT);
    if (inputHash !== EXPECTED_HASH) {{
        if (errEl) {{ errEl.textContent = '❌ 口令错误，请重新输入！'; errEl.style.display = 'block'; }}
        if (inputEl) inputEl.select();
        return;
    }}
    const data = JSON.parse(xor_decrypt_b64(ENCRYPTED_PAYLOAD, inputHash));
    document.getElementById('lock-screen').style.display = 'none';
    document.getElementById('main-app-container').style.display = 'block';
    try {{ sessionStorage.setItem('astock2_ext8_unlocked', pwd); }} catch(e) {{}}
    initTrainerApp(data);
}}
window.addEventListener('DOMContentLoaded', () => {{
    const inputEl = document.getElementById('pwd-input');
    if (inputEl) inputEl.addEventListener('keydown', (e) => {{ if (e.key === 'Enter') attemptUnlock(); }});
    try {{
        const sp = sessionStorage.getItem('astock2_ext8_unlocked');
        if (sp && sha256(sp + SALT) === EXPECTED_HASH) {{
            const data = JSON.parse(xor_decrypt_b64(ENCRYPTED_PAYLOAD, EXPECTED_HASH));
            document.getElementById('lock-screen').style.display = 'none';
            document.getElementById('main-app-container').style.display = 'block';
            initTrainerApp(data);
        }}
    }} catch(e) {{}}
}});
</script>
</body>
</html>"""
    for p in paths:
        with open(p, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"Saved locked external 8-level: {p} ({round(os.path.getsize(p)/1024, 1)} KB)")

save_unlocked([
    os.path.join(OUT_DIR, "1to2_trainer_q1.html"),
    os.path.join(OUT_DIR, "A股一进二盘感挑战赛_8关免密版.html"),
])
save_locked([
    os.path.join(OUT_DIR, "1to2_trainer_q1_locked.html"),
    os.path.join(OUT_DIR, "A股一进二盘感挑战赛_8关口令版.html"),
])
