#!/opt/homebrew/bin/python3
"""B策略次日候选短名单生成器 — 收盘调仓第④步产出, 供次日 09:27 的 b_board_alert 读取
⛔2026-09-07建: 此前 b_watch_YYYYMMDD.json 全靠手动生成(09-04是当天09:12手搓,
   09-05是前一晚21:35手搓), 没有任何脚本或定时负责 → 某天没人手搓, 盘中短名单就是空的,
   而旧版 shortlist() 对"文件没生成"和"今天真没候选"返回同一个值, 我看不出区别。
   本脚本把它变成收盘流程的固定产出。

四道门(全部来自当日涨停池, 无前视):
  ①首封 < 10:00   ②炸板次数 = 0   ③封板资金÷成交额 ≥ 3%   ④同行业当日涨停 ≥ 2只
市值门(三次修正定版): 首板需流通市值≥100亿; 2板及以上需≥50亿
排除: 一字板(开盘价即涨停价, 买不进)。⛔2026-10-20 Buwen 令"策略里可以加入北交和st", 原排除的 ST 与北交所改为可入
用法: b_watch_build.py [YYYYMMDD涨停池日期]   默认今天, 产出次一日的候选文件
"""
import json,os,sys,datetime,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def mkt(c): return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' or c.startswith('92') else 'sz')   # 92 开头是北交所新代码段, 2026-10-20 前误判为深市

def opens(codes):
    """取当日开盘价, 用于准确排一字板(只看封板时间会把'竞价快速封板'误判成一字)"""
    out={}
    for i in range(0,len(codes),400):
        q=','.join(mkt(c)+c for c in codes[i:i+400])
        try: raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=8).read().decode('gbk','ignore')
        except Exception as e: print('  取开盘价失败',type(e).__name__); continue
        for line in raw.split('\n'):
            p=line.split('~')
            if len(p)>6 and 'none_match' not in line:
                try: out[p[2]]={'open':float(p[5] or 0),'close':float(p[3] or 0),'prev':float(p[4] or 0)}
                except ValueError: pass
    return out


def first_board_cap(code,lb,mc_today,day,px_today=None):
    """首板当日流通市值(亿)。⛔2026-10-15 Buwen: 「30亿以下」说的是首板时的市值, 不是4到5板当天的市值
    (原话 0917「主看30亿市值以下首板」)。连板几天后市值自然涨了四到六成, 用当天市值卡30亿会把首板时
    合格的票挡掉(10-09/10-12 时代万恒首板时约24亿, 当天31到35亿, 被误剔)。
    做法: 流通股本不变, 首板日市值 = 今日流通市值 × 首板日收盘 / 今日收盘; 首板日 = 今日往前数 lb-1 个交易日。"""
    try:
        try:
            u=f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt(code)}{code},day,,,20,bfq'
            k=json.loads(urllib.request.urlopen(u,timeout=8).read())['data'][mkt(code)+code]
            bars=k.get('day') or k.get('bfqday') or []
        except Exception as e:
            # 2026-10-19: 腾讯日K 当天被 WAF 拦(HTTP 501), 改用新浪不复权日K, 字段排成同样的 [日期, 开, 收]
            print('  腾讯日K取不到, 改新浪',code,type(e).__name__)
            import re
            su=f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData?symbol={mkt(code)}{code}&scale=240&ma=no&datalen=20'
            raw=urllib.request.urlopen(urllib.request.Request(su,headers={'Referer':'https://finance.sina.com.cn','User-Agent':'Mozilla/5.0'}),timeout=8).read().decode()
            m=re.search(r'x=\((\[.*\])\)',raw,re.S)
            bars=[[b['day'],b['open'],b['close']] for b in json.loads(m.group(1))] if m else []
        d=f'{day[:4]}-{day[4:6]}-{day[6:]}'
        # 2026-10-16: 15:40 跑时腾讯日K常还没有当天这根(冰山冷热 4 板因此记成"取不到"), 用涨停池的最新价补上当天
        if bars and bars[-1][0]<d and px_today: bars=bars+[[d,None,str(px_today)]]
        idx=[i for i,b in enumerate(bars) if b[0]==d]
        if not idx: return None
        i=idx[0]; j=i-(lb-1)
        if j<0: return None
        return mc_today*float(bars[j][2])/float(bars[i][2])
    except Exception as e:
        print('  首板市值取数失败',code,type(e).__name__); return None

def get_lockup_pct(code):
    """获取前十大流通股东合计持股占总流通股本比例(lock10, %)，用于计算真实自由流通市值与真实自由换手率。
    优先读本地缓存 data/cn_hk_price_db/sh_lockup_cache.json，未命中则调 akshare 抓取并写回缓存。"""
    cache_p = f'{ROOT}/data/cn_hk_price_db/sh_lockup_cache.json'
    cache = {}
    if os.path.exists(cache_p):
        try: cache = json.load(open(cache_p))
        except Exception: cache = {}
    if code in cache and isinstance(cache[code], dict) and 'lock_top10' in cache[code]:
        return float(cache[code]['lock_top10'])
    # Try backtest cache as seed
    seed_p = f'{ROOT}/backtest/2026-10-20-selfreview/streak5_free_float/sh_lockup.json'
    if os.path.exists(seed_p):
        try:
            sd = json.load(open(seed_p))
            if code in sd:
                cache[code] = sd[code]
                json.dump(cache, open(cache_p, 'w'), ensure_ascii=False, indent=2)
                return float(sd[code]['lock_top10'])
        except Exception:
            pass
    try:
        import akshare as ak, pandas as pd
        sym = ('sh' if code.startswith('6') else 'sz') + code
        for rpt in ('20260630', '20260331', '20251231'):
            try:
                sdf = ak.stock_gdfx_free_top_10_em(symbol=sym, date=rpt)
                if sdf is not None and not sdf.empty:
                    col = '占总流通股本持股比例' if '占总流通股本持股比例' in sdf.columns else sdf.columns[4]
                    vals = pd.to_numeric(sdf[col], errors='coerce').fillna(0.0)
                    l10 = min(float(vals.sum()), 95.0)
                    l5 = min(float(vals[vals >= 5.0].sum()), 92.0)
                    cache[code] = {'lock_5pct': l5, 'lock_top10': l10}
                    json.dump(cache, open(cache_p, 'w'), ensure_ascii=False, indent=2)
                    return l10
            except Exception:
                continue
    except Exception:
        pass
    return 0.0


def main():
    day=sys.argv[1] if len(sys.argv)>1 else datetime.date.today().strftime('%Y%m%d')
    src=f'{ROOT}/data/zt_pool/{day}.json'
    if not os.path.exists(src): print(f'⛔涨停池 {day} 不存在: {src}'); sys.exit(1)
    zt=json.load(open(src))
    print(f'涨停池 {day}: {len(zt)} 只')
    ind_cnt={}
    for r in zt: ind_cnt[r.get('所属行业')]=ind_cnt.get(r.get('所属行业'),0)+1
    n_high4 = sum(1 for r in zt if int(r.get('连板数') or 1) >= 4)
    px=opens([str(r['代码']) for r in zt])
    print(f'开盘价取到 {len(px)} 只')
    # ⛔2026-10-21 按 Buwen 真实自由流通盘与五板回测升级:
    #   ① 市值门采用「首板真实自由流通市值 <= 30亿（或首板账面流通市值 <= 50亿）」，解决大股东高锁仓龙头(如九阳72.8%锁仓/大业股份)被假分母误杀问题
    #   ② 主线门支持「东财行业涨停 >= 2只 或 全场>=4板梯队 >= 2只且为本行业最高板」，解决跨行业题材(机器人/低空/传媒)被东财狭义二级行业切碎问题
    #   ③ 多股排序对齐 Buwen 实证：「前十股东锁仓 >= 50%(真锁仓) > 真实自由换手率适中偏低 > 账面大市值」
    #   ④ 同步输出 five_plus_t1_pool (五板/高标次日 T+1 开盘博弈池: 0%~+5% 或 <=-5% 开盘买, 盘中+8%/收盘+5%跟踪, 异动线卡线卖)
    cands=[]; five_plus_t1=[]; stat={'板数不符':0,'市值超标':0,'非主线':0,'非行业最高':0,'公告红旗':0}
    top={}
    for r in zt:
        ind=r.get('所属行业'); top[ind]=max(top.get(ind,0),int(r.get('连板数') or 1))
    screened=[]
    import subprocess
    for r in zt:
        c=str(r['代码']).zfill(6); nm=str(r.get('名称') or '')
        lb=int(r.get('连板数') or 1); mc=(r.get('流通市值') or 0)/1e8; ind=r.get('所属行业'); cc=ind_cnt.get(ind,0)
        if lb >= 4:
            lock10 = get_lockup_pct(c)
            free_ratio = max(0.05, 1.0 - lock10 / 100.0)
            free_mc = mc * free_ratio
            nom_turn = float(r.get('换手率') or 0)
            true_turn = nom_turn / free_ratio
            close_p = float(r.get('最新价') or 0)
            if lb >= 5:
                five_plus_t1.append({
                    'code': c, 'name': nm, 'lb': lb, 'ind': ind,
                    'mcap': round(mc, 1), 'free_mcap': round(free_mc, 1), 'lock10_pct': round(lock10, 1),
                    'nom_turn': round(nom_turn, 1), 'true_turn': round(true_turn, 1),
                    't1_buy_zone_high': [round(close_p * 1.00, 2), round(close_p * 1.05, 2)],
                    't1_buy_zone_dip': round(close_p * 0.95, 2),
                    'qualifies_lock50': lock10 >= 50.0,
                    'qualifies_turn_sweet': 15.0 <= true_turn <= 70.0
                })
        if lb not in (4,5): stat['板数不符']+=1; continue
        fmc=first_board_cap(c,lb,mc,day,r.get('最新价'))
        if fmc is None: stat.setdefault('首板市值取不到',0); stat['首板市值取不到']+=1; continue
        free_fmc = fmc * free_ratio
        if not (0 < free_fmc <= 30.0 or 0 < fmc <= 50.0): stat['市值超标']+=1; continue
        if cc < 2 and n_high4 < 2: stat['非主线']+=1; continue
        if lb<top.get(ind,0): stat['非行业最高']+=1; continue
        chk=subprocess.run(['/opt/homebrew/bin/python3.13',os.path.expanduser('~/claude-projects/news-dashboard/announce_lookup.py'),c,'1'],
                           capture_output=True,text=True,timeout=120).stdout
        if '🔴0' not in chk:
            stat['公告红旗']+=1; screened.append({'code':c,'name':nm,'理由':'近一月公告有红旗或查询失败, 需读原文'}); continue
        amt=r.get('成交额') or 0; seal=r.get('封板资金') or 0
        cands.append({'code':c,'name':nm,'lb':lb,'ind':ind,'gates':4,'ratio':round(seal/amt,3) if amt else 0,
                      't1':str(r.get('首次封板时间') or ''),'turn':round(nom_turn,1),'true_turn':round(true_turn,1),
                      'cc':cc,'mcap':round(mc,1),'free_mcap':round(free_mc,1),'lock10_pct':round(lock10,1),
                      '首板市值':round(fmc,1),'首板真实自由市值':round(free_fmc,1)})
    # 多股同台排序: 连板数高 -> 前十锁仓>=50%优先 -> 换手率更低 -> 账面市值更大 (对齐 Buwen: 五板当日低换手 > 大市值 + 真锁仓)
    cands.sort(key=lambda x:(-x['lb'], -(1 if x['lock10_pct']>=50 else 0), x['true_turn'], -x['mcap']))
    nxt=datetime.datetime.strptime(day,'%Y%m%d').date()+datetime.timedelta(days=1)
    while nxt.weekday()>=5: nxt+=datetime.timedelta(days=1)
    out={'date':nxt.isoformat(),'source':f'zt_pool/{day}.json ({len(zt)}只涨停)',
         '已过基本面筛':True,'已过基本面筛_说明':'策略二不看基本面, 只做公告红旗否决(近一月), 结果见 基本面筛除',
         '基本面筛除':screened,'chains':sorted({c['ind'] for c in cands}),
         '⛔硬门槛':'v14.0+真实自由流通盘升级: 今日4到5板/首板真实自由流通市值<=30亿(或首板账面<=50亿)/行业最高板/无公告红旗; 多股按[锁仓>=50% > 低真实换手 > 大市值]排序',
         '⛔判据已废_不得买入':False,
         '生成时间':datetime.datetime.now().isoformat(timespec='seconds'),'过滤统计':stat,'候选':cands,
         'five_plus_t1_pool':five_plus_t1}
    p=f'{ROOT}/data/b_watch_{nxt.strftime("%Y%m%d")}.json'
    # ⛔2026-09-18 加 DRY_RUN: 本脚本此前无法被无副作用验证(默认参数因涨停池未生成而退出,
    #   传历史日期又会覆盖掉已手工标注的既有名单), 而"改完总要测一下"是必然动作。
    #   先有开关再改逻辑, 顺序不能反。
    if os.environ.get('DRY_RUN')=='1':
        print('[DRY_RUN] 不写文件。out 顶层字段:'); print('   ', list(out.keys()))
        print(f'   判据已废_不得买入 = {out.get("⛔判据已废_不得买入")}   已过基本面筛 = {out.get("已过基本面筛")}')
        print(f'   本应写入 {os.path.basename(p)}, 候选 {len(cands)} 只')
        print('   过滤:',stat)
        for c in cands: print(f'   {c["code"]} {c["name"]} {c["lb"]}板 当日流通{c["mcap"]}亿 首板时{c["首板市值"]}亿 {c["ind"]}({c["cc"]}只)')
        return
    json.dump(out,open(p,'w'),ensure_ascii=False,indent=1)
    print('过滤:',stat)
    print(f'→ {len(cands)} 只候选写入 {os.path.basename(p)} (供 {nxt} 盘前使用)')
    for c in cands: print(f'   {c["code"]} {c["name"]:<8}{c["lb"]}板 {c["gates"]}/4门 封{c["ratio"]*100:.1f}% 首封{c["t1"]} 市值{c["mcap"]}亿 {c["ind"]}({c["cc"]}只)')
if __name__=='__main__': main()
