# -*- coding: utf-8 -*-
"""三进四盘感刷题机单文件HTML组装器（支持免密版与口令加密版）"""
import os, sys, json, base64, hashlib, importlib
CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)
css_m = importlib.import_module("3to4_trainer_css")
CSS_3TO4 = css_m.CSS_3TO4

DEFAULT_SALT = 'astock2_3to4_sec'
DEFAULT_PWD = "".join([chr(48), chr(53), chr(50), chr(49), chr(48), chr(49)]) # 052101

def derive_key(pwd, salt=DEFAULT_SALT):
    return hashlib.sha256((pwd + salt).encode('utf-8')).hexdigest()

def xor_stream(data_bytes, key_hex):
    out = bytearray(len(data_bytes)); block_idx = 0; offset = 0
    while offset < len(data_bytes):
        keystream = hashlib.sha256((key_hex + f"_{block_idx}").encode("utf-8")).digest()
        chunk = min(32, len(data_bytes) - offset)
        for j in range(chunk): out[offset + j] = data_bytes[offset + j] ^ keystream[j]
        offset += chunk; block_idx += 1
    return bytes(out)

def load_assets():
    with open(os.path.join(CUR_DIR, '3to4_trainer_frontend.js'), 'r', encoding='utf-8') as f: fe_js = f.read()
    with open(os.path.join(CUR_DIR, '3to4_unlocker_template.js'), 'r', encoding='utf-8') as f: un_js = f.read()
    return fe_js, un_js

def build_unlocked_html(cases, page_title, stats_key):
    fe_js, _ = load_assets()
    data_str = json.dumps(cases, ensure_ascii=False)
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{page_title}</title>
<style>{CSS_3TO4}</style></head><body>
<div id="main-app-container" class="container"></div>
<script>
const DATA_CASES = {data_str};
const PAGE_TITLE = "{page_title}";
const STATS_KEY = "{stats_key}";
{fe_js}
if (document.readyState === 'loading') {{ window.addEventListener('DOMContentLoaded', () => initTrainerApp(DATA_CASES, PAGE_TITLE, STATS_KEY)); }}
else {{ initTrainerApp(DATA_CASES, PAGE_TITLE, STATS_KEY); }}
</script></body></html>"""

def build_locked_html(cases, page_title, stats_key, password=DEFAULT_PWD, salt=DEFAULT_SALT):
    fe_js, un_js = load_assets()
    data_str = json.dumps(cases, ensure_ascii=False)
    key_hex = derive_key(password, salt)
    enc_b64 = base64.b64encode(xor_stream(data_str.encode('utf-8'), key_hex)).decode('ascii')
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{page_title}</title>
<style>{CSS_3TO4}</style></head><body>
<div id="lock-screen" class="lock-screen-wrapper"><div class="lock-card">
<div class="lock-title"><span>🔒</span> <span>{page_title}</span></div>
<div style="font-size:11px;font-weight:700;color:#111827;margin-bottom:12px;background:#fef3c7;padding:4px 8px;border:1px solid #f59e0b;">内部实战专版（纯离线单文件 · 安全加密）</div>
<div class="lock-desc">本题库已采用纯本地哈希加密保护，解密计算完全在您本机浏览器内存中进行，无需联网，无需外部依赖。</div>
<div style="margin-bottom:6px;font-weight:700;font-size:12px;">请输入内部访问口令：</div>
<input type="password" id="pwd-input" class="lock-input" placeholder="输入访问口令解锁" autocomplete="current-password" autofocus />
<button class="lock-btn" onclick="attemptUnlock()">立即解锁题库</button>
<div id="pwd-error" style="display:none;color:#dc2626;font-size:12px;margin-top:8px;font-weight:700;"></div>
<div style="margin-top:16px;font-size:11px;color:#9ca3af;text-align:center;">提示：支持本地离线双击打开与微信内置浏览器（口令请联系分享人获取）</div>
</div></div>
<div id="main-app-container" class="container" style="display:none;"></div>
<script>
const ENCRYPTED_PAYLOAD = "{enc_b64}";
const EXPECTED_HASH = "{key_hex}";
const SALT = "{salt}";
const PAGE_TITLE = "{page_title}";
const STATS_KEY = "{stats_key}";
{un_js}
{fe_js}
function attemptUnlock() {{
    const inp = document.getElementById('pwd-input');
    const err = document.getElementById('pwd-error');
    const pwd = inp ? inp.value.trim() : '';
    if (!pwd) {{ if (err) {{ err.textContent = '请输入访问口令！'; err.style.display = 'block'; }} return; }}
    const inHash = sha256(pwd + SALT);
    if (inHash !== EXPECTED_HASH) {{
        if (err) {{ err.textContent = '❌ 口令错误，请重新输入！'; err.style.display = 'block'; }}
        if (inp) inp.select(); return;
    }}
    try {{
        const jsonStr = xor_decrypt_b64(ENCRYPTED_PAYLOAD, inHash);
        const data = JSON.parse(jsonStr);
        document.getElementById('lock-screen').style.display = 'none';
        document.getElementById('main-app-container').style.display = 'block';
        try {{ sessionStorage.setItem(STATS_KEY + '_unlocked', '1'); sessionStorage.setItem(STATS_KEY + '_pwd', pwd); }} catch(e) {{}}
        initTrainerApp(data, PAGE_TITLE, STATS_KEY);
    }} catch(e) {{ if (err) {{ err.textContent = '❌ 解密失败或数据损坏！'; err.style.display = 'block'; }} }}
}}
window.addEventListener('DOMContentLoaded', () => {{
    const inp = document.getElementById('pwd-input');
    if (inp) inp.addEventListener('keydown', e => {{ if (e.key === 'Enter') attemptUnlock(); }});
    try {{
        const u = sessionStorage.getItem(STATS_KEY + '_unlocked');
        const p = sessionStorage.getItem(STATS_KEY + '_pwd');
        if (u === '1' && p && sha256(p + SALT) === EXPECTED_HASH) {{
            const jsonStr = xor_decrypt_b64(ENCRYPTED_PAYLOAD, EXPECTED_HASH);
            const data = JSON.parse(jsonStr);
            document.getElementById('lock-screen').style.display = 'none';
            document.getElementById('main-app-container').style.display = 'block';
            initTrainerApp(data, PAGE_TITLE, STATS_KEY);
        }}
    }} catch(e) {{}}
}});
</script></body></html>"""
