#!/usr/bin/env python3
"""市场风格体检 (regime check) — 扫描/建仓前置体检

揭穿"指数失真",一跑就知道现在能不能做、钱在哪:
  ① 指数 vs 全市场市值中位数 背离  → 揭穿"指数牛、个股熊"的缩圈
  ② 赚钱效应趋势(涨家占比 3月→1月→1周) → 收窄=缩圈接近尾声
  ③ 今日板块强弱 → 钱当下抱团在哪

判读:
  指数涨但中位数股票跌 + 赚钱效应持续收窄 = 缩圈市
  → 钱抽到少数龙头,80%的票阴跌,该"少动/只跟核心龙头/高现金",别硬找标的
  普涨(中位数正+赚钱效应>55%) = 可放手做; 普跌(<40%) = 防守

固化自 2026-06-29: 当天科创50 3月+65% 但全市场中位数股票 -10%、赚钱效应22%,
典型"指数牛个股熊"缩圈市 —— 解释了用户"看不懂、不好炒"的体感。
用法: python3 scripts/regime_check.py  (慢接口建议加 2>/dev/null 静音进度条)
"""
import sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import statistics as st
sys.path.insert(0, '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts')
import akshare as ak
from astock_data_layer import get_full_market

def main():
    t0 = time.time()
    alls = get_full_market()
    cap_map = {s['code']: s['market_cap'] for s in alls if s.get('market_cap')}
    name_map = {s['code']: s['name'] for s in alls}
    codes = [s['code'] for s in alls if s.get('market_cap') and s['market_cap'] > 30 and s['code'][0] in '036']

    # 一、指数风格 (大小盘/成长)
    print("=" * 68); print("一、指数风格 (63日≈3月 / 21日≈1月 / 5日≈1周)"); print("=" * 68)
    IDX = {'000300': '沪深300(大盘)', '000905': '中证500(中盘)', '000852': '中证1000(小盘)',
           '399006': '创业板(成长)', '000688': '科创50(科技)', '000001': '上证综指'}
    for code, nm in IDX.items():
        try:
            df = ak.stock_zh_index_daily_em(symbol=('sh' if code[0] in '06' else 'sz') + code)
            c = df['close'].values.astype(float)
            print(f"  {nm:<16} 3月{(c[-1]/c[-63]-1)*100:+6.1f}%  1月{(c[-1]/c[-21]-1)*100:+6.1f}%  1周{(c[-1]/c[-5]-1)*100:+6.1f}%")
        except Exception:
            print(f"  {nm}: 取数失败")

    # 个股
    def fetch(code):
        try:
            df = ak.stock_zh_a_hist(symbol=code, period='daily', start_date='20260101', end_date='20260629', adjust='qfq')
            if df is None or len(df) < 65: return None
            return (code, df['收盘'].values.astype(float))
        except Exception:
            return None
    data = []
    with ThreadPoolExecutor(max_workers=25) as ex:
        for f in as_completed([ex.submit(fetch, c) for c in codes]):
            r = f.result()
            if r: data.append(r)
    print(f"\n(个股拉取{len(data)}只, {time.time()-t0:.0f}s)")

    # 二、市值风格
    rows = []
    for code, c in data:
        if len(c) < 63: continue
        rows.append((cap_map.get(code, 0), c[-1]/c[-63]-1, c[-1]/c[-21]-1, c[-1]/c[-5]-1))
    rows.sort()
    print("=" * 68); print("二、市值风格 (各层中位数收益%, 看大盘还是小盘强)"); print("=" * 68)
    L = len(rows)
    for lo, hi, nm in [(0, .2, '微盘20%'), (.2, .4, '小盘'), (.4, .6, '中盘'), (.6, .8, '大盘'), (.8, 1., '超大盘20%')]:
        seg = rows[int(lo*L):int(hi*L)]
        if not seg: continue
        m3 = st.median([x[1] for x in seg])*100; m1 = st.median([x[2] for x in seg])*100; mw = st.median([x[3] for x in seg])*100
        print(f"  {nm:<10}({seg[0][0]:.0f}-{seg[-1][0]:.0f}亿) 3月{m3:+6.1f}%  1月{m1:+6.1f}%  1周{mw:+6.1f}%")

    # 三、赚钱效应
    print("=" * 68); print("三、赚钱效应 (涨家占比 / 中位数收益) — 收窄=缩圈"); print("=" * 68)
    for w, nm in [(63, '3月'), (21, '1月'), (5, '1周')]:
        rets = [c[-1]/c[-w]-1 for _, c in data if len(c) > w]
        up = sum(1 for x in rets if x > 0); med = st.median(rets)*100
        tag = '赚钱效应好' if up/len(rets) > .55 else ('普跌' if up/len(rets) < .4 else '分化/难做')
        print(f"  {nm}: 上涨{up}/{len(rets)} ({up/len(rets)*100:.0f}%涨)  中位数{med:+.1f}%  {tag}")

    # 四、今日板块
    print("=" * 68); print("四、今日板块强弱 (资金当下在哪)"); print("=" * 68)
    try:
        bd = ak.stock_board_industry_name_em().sort_values('涨跌幅', ascending=False)
        print("  最强8:", '  '.join(f"{r['板块名称']}{r['涨跌幅']:+.1f}%" for _, r in bd.head(8).iterrows()))
        print("  最弱8:", '  '.join(f"{r['板块名称']}{r['涨跌幅']:+.1f}%" for _, r in bd.tail(8).iterrows()))
    except Exception:
        print("  板块取数失败")
    print(f"\n[体检完成 {time.time()-t0:.0f}s] 缩圈判读: 指数涨+中位数跌+赚钱效应收窄=缩圈→少动只跟核心龙头")

if __name__ == '__main__':
    main()
