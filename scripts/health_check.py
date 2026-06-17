# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.28", "akshare>=1.14", "baostock>=0.8", "rich>=13", "yfinance>=0.2"]
# ///
"""扫描前数据链体检 — 只测连通+返回结构+不报错,不跑选股。
用法: uv run --script scripts/health_check.py
每次大扫描前跑一次,确认数据源/接口/脚本全绿再开扫,免得拿脏数据写报告。"""
import sys, json
from datetime import datetime

sys.path.insert(0, "scripts")
R = []
def chk(name, fn):
    try:
        R.append(("PASS", name, fn()))
    except Exception as e:
        R.append(("FAIL", name, f"{type(e).__name__}: {str(e)[:140]}"))

# ===== A. astock_data_layer 核心数据层（D12指定源）=====
def a1():
    from astock_data_layer import get_batch_prices
    r = get_batch_prices(["600519", "000001", "300308", "688019"])  # 沪/深/创/科
    ok = {k: v for k, v in r.items() if v.get("price") and v.get("market_cap")}
    assert len(ok) >= 3, f"仅{len(ok)}/4完整"
    s = r.get("600519", {})
    return f"{len(ok)}/4完整 | 茅台¥{s.get('price')}/PE{s.get('pe')}/市值{s.get('market_cap')}亿/源{s.get('source')}"
chk("A1 get_batch_prices(EM主源·沪深创科4板块)", a1)

def a2():
    from astock_data_layer import _fallback_tencent
    r = _fallback_tencent("600519", datetime.now().isoformat())
    assert r.get("price"), "tencent无price"
    return f"兜底OK | 茅台¥{r['price']}/市值{r.get('market_cap')}亿"
chk("A2 tencent兜底(_fallback_tencent)", a2)

def a3():
    from astock_data_layer import get_limit_up_stocks
    r = get_limit_up_stocks()
    n = sum(len(v) for v in r.values()) if isinstance(r, dict) else len(r)
    return f"涨停池返回{n}只"
chk("A3 涨停池(get_limit_up_stocks)", a3)

def a4():
    from astock_data_layer import get_strong_movers
    r = get_strong_movers()
    return f"强势股返回{len(r)}只"
chk("A4 强势股(get_strong_movers)", a4)

# ===== B. UASS扫描数据源（Step1依赖）=====
def b1():
    from uass_pipeline import fetch_all
    d = datetime.now().strftime("%Y%m%d")
    r = fetch_all(d)
    return (f"涨停{len(r.get('zt_pool',[]))} / 强势{len(r.get('strong_movers',[]))} / "
            f"龙虎榜{len(r.get('lhb',[]))} / 板块{len(r.get('sector_flow',[]))} / "
            f"北向{r.get('northbound',{}).get('净买额_亿','N/A')}亿 / errors={r.get('errors')}")
chk("B1 uass全量(fetch_all:涨停+强势+龙虎榜+板块+北向)", b1)

# ===== C. 评分/风控/视图脚本（含今天修的3个）=====
def c1():
    import tb_engine
    g = tb_engine.score_to_grade(80)
    return f"import+score_to_grade(80)={g[0]} (351行引号语法修复验证)"
chk("C1 tb_engine(今修:语法)", c1)

def c2():
    import risk_monitor
    rep = risk_monitor.run_risk_check(fetch_live=False, market="cn")
    crit = len([a for a in rep.alerts if a.level == "critical"])
    return f"run(market=cn,no-fetch)OK | A股NAV¥{rep.cn_total_assets:,.0f} | CRITICAL={crit}(应0,假告警已修)"
chk("C2 risk_monitor(今修:类型+market隔离)", c2)

def c3():
    import astock_pipeline as ap, inspect
    src = inspect.getsource(ap.step_uass_scan)
    assert "subprocess" in src and "batch_chip_health" not in src, "pipeline未修复"
    return "step_uass_scan=subprocess调uass_scan,不再引用已删函数(今修)"
chk("C3 astock_pipeline(今修:subprocess)", c3)

def c4():
    import session_view
    assert hasattr(session_view, "main")
    return "import OK,main()存在"
chk("C4 session_view", c4)

def c5():
    import update_prices
    return "import OK"
chk("C5 update_prices", c5)

# ===== D. SSOT =====
def d1():
    s = json.load(open("portfolio_state.json"))
    acc = s["accounts"]["a_share"]
    return f"结构完整 | A股{len(acc['positions'])}持仓/现金¥{acc['cash']:,.0f}"
chk("D1 portfolio_state.json(SSOT)", d1)

# ===== E. 外部API直连 =====
def e1():
    from astock_data_layer import get_single_price
    r = get_single_price("600519")
    assert r.get("price"), "单股查询无price"
    return f"单股生产接口OK(EM挂自动兜底tencent) | 茅台¥{r['price']}/源{r.get('source')}"
chk("E1 单股查询容错(get_single_price)", e1)

# ===== 输出 =====
print("=" * 64)
print(f"A股扫描数据链体检 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 64)
for st, name, msg in R:
    print(f"{'✅' if st=='PASS' else '❌'} {name}\n     → {msg}")
print("=" * 64)
p = sum(1 for s, _, _ in R if s == "PASS")
print(f"结果: {p} PASS / {len(R)-p} FAIL / 共{len(R)}项")
if p < len(R):
    print("⚠️ 有FAIL项,扫描前必须修复(否则拿脏数据/卡agent)")
else:
    print("✅ 全绿,数据链可用,可开扫")
