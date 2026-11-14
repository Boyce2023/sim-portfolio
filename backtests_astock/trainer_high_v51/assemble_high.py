#!/opt/homebrew/bin/python3.13
# 高标刷题机 HTML 组装：免密版与口令版（口令与一进二题库相同，复用复制版组装器的加密外壳）
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import trainer_assembler_high as A
OUT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/最新交付题库"
fe = open(f"{HERE}/fe_high.js", encoding="utf-8").read()
unlock = open(f"{HERE}/unlocker_high.js", encoding="utf-8").read()
STYLE = """<style>
#high-app{max-width:980px;margin:0 auto;padding:12px;font-size:14px;color:#111827}
.hd-top{display:flex;flex-wrap:wrap;gap:14px;align-items:center;padding:10px;border:1px solid #e5e7eb;background:#f9fafb;margin-bottom:10px}
.hd-q h3{margin:6px 0}.hd-mk{color:#374151;margin:4px 0}.hd-tip{background:#fef3c7;border:1px solid #f59e0b;padding:6px 8px;margin:8px 0}
.hd-card{border:1px solid #d1d5db;padding:10px;margin:10px 0}.hd-name{font-weight:700;margin-bottom:6px}
.hd-k{width:100%;max-width:520px;height:150px;border:1px solid #f3f4f6}
.hd-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:4px 12px;margin-top:6px}
.hd-res{margin-top:8px;padding:6px 8px;border-left:4px solid #9ca3af;background:#f9fafb}
.hd-btns,.hd-nav{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.hd-ans{padding:10px;margin:10px 0;font-weight:600}.hd-ans.ok{background:#ecfdf5;border:1px solid #10b981}.hd-ans.bad{background:#fef2f2;border:1px solid #ef4444}
</style>"""
JOBS = [("high_pack50.json", "A股高标盘感刷题机_V5.1第1套50题", "高标首阴盘感刷题机 · V5.1 第1套50题", "high_v51_pack1"),
        ("high_chal5.json", "A股高标盘感挑战赛_V5.1第1辑5关", "高标首阴盘感挑战赛 · V5.1 第1辑5关", "high_v51_chal1")]
for fn, base, title, key in JOBS:
    data = json.load(open(f"{HERE}/{fn}", encoding="utf-8"))
    ds = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    js = f"window.HIGH_TITLE={json.dumps(title, ensure_ascii=False)};window.HIGH_STATS_KEY='{key}';\n" + fe
    main = STYLE + '<div id="high-app"></div>'
    for tag, content in [("免密版", A.build_unlocked_html_content(ds, main, js, "", title)),
                         ("口令版", A.build_locked_html_content(ds, main, js, "", unlock, title))]:
        p = f"{OUT}/{base}{tag}.html"
        open(p, "w", encoding="utf-8").write(content)
        print(p, os.path.getsize(p) // 1024, "KB", len(data), "题")
