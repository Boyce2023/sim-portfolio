#!/opt/homebrew/bin/python3
"""B策略次日候选短名单生成器 — 收盘调仓第④步产出, 供次日 09:27 的 b_board_alert 读取
⛔2026-09-07建: 此前 b_watch_YYYYMMDD.json 全靠手动生成(09-04是当天09:12手搓,
   09-05是前一晚21:35手搓), 没有任何脚本或定时负责 → 某天没人手搓, 盘中短名单就是空的,
   而旧版 shortlist() 对"文件没生成"和"今天真没候选"返回同一个值, 我看不出区别。
   本脚本把它变成收盘流程的固定产出。

四道门(全部来自当日涨停池, 无前视):
  ①首封 < 10:00   ②炸板次数 = 0   ③封板资金÷成交额 ≥ 3%   ④同行业当日涨停 ≥ 2只
市值门(三次修正定版): 首板需流通市值≥100亿; 2板及以上需≥50亿
排除: 一字板(开盘价即涨停价, 买不进) / ST / 北交所
用法: b_watch_build.py [YYYYMMDD涨停池日期]   默认今天, 产出次一日的候选文件
"""
import json,os,sys,datetime,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def mkt(c): return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' else 'sz')

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

def main():
    day=sys.argv[1] if len(sys.argv)>1 else datetime.date.today().strftime('%Y%m%d')
    src=f'{ROOT}/data/zt_pool/{day}.json'
    if not os.path.exists(src): print(f'⛔涨停池 {day} 不存在: {src}'); sys.exit(1)
    zt=json.load(open(src))
    print(f'涨停池 {day}: {len(zt)} 只')
    ind_cnt={}
    for r in zt: ind_cnt[r.get('所属行业')]=ind_cnt.get(r.get('所属行业'),0)+1
    px=opens([str(r['代码']) for r in zt])
    print(f'开盘价取到 {len(px)} 只')
    cands=[]; stat={'一字':0,'市值':0,'门<3':0,'ST/北交':0}
    for r in zt:
        c=str(r['代码']); nm=str(r.get('名称') or '')
        if nm.startswith(('ST','*ST')) or c[0] in '489': stat['ST/北交']+=1; continue
        o=px.get(c,{})
        if o.get('open') and o.get('close') and abs(o['open']-o['close'])<0.005:
            stat['一字']+=1; continue                      # 开盘即收盘且是涨停 = 一字板, 买不进
        lb=int(r.get('连板数') or 1); mc=(r.get('流通市值') or 0)/1e8
        # ⛔2026-09-10 市值硬门降级: 原 首板≥100亿 / 2板以上≥50亿, 挡掉 68% 涨停票。
        #   实证(2025 样本 13945 条, 用 oshare×close 复原当时流通市值): 各市值档 gap1 均值
        #   1.58%~1.94% 无单调性, 超额全在 ±0.22pp 内, 该门只把均值从 +1.84% 提到 +1.89%。
        #   现只挡"无市值数据"的异常行, 市值高低交由 b_score 的 fmv 维打分。
        if mc <= 0: stat['市值']+=1; continue
        amt=r.get('成交额') or 0; seal=r.get('封板资金') or 0
        ratio=seal/amt if amt else 0
        t1=str(r.get('首次封板时间') or '999999')
        ind=r.get('所属行业'); cc=ind_cnt.get(ind,0)
        g=sum([t1<'100000', (r.get('炸板次数') or 0)==0, ratio>=0.03, cc>=2])
        if g<3: stat['门<3']+=1; continue
        cands.append({'code':c,'name':nm,'lb':lb,'ind':ind,'gates':g,
                      'ratio':round(ratio,3),'t1':t1,'turn':round(r.get('换手率') or 0,1),
                      'cc':cc,'mcap':round(mc,1)})
    cands.sort(key=lambda x:(-x['gates'],-x['lb'],-x['ratio']))
    nxt=datetime.datetime.strptime(day,'%Y%m%d').date()+datetime.timedelta(days=1)
    while nxt.weekday()>=5: nxt+=datetime.timedelta(days=1)
    out={'date':nxt.isoformat(),'source':f'zt_pool/{day}.json ({len(zt)}只涨停)',
         # ⛔⛔ 默认不安全(2026-09-17新增)。Buwen 2026-09-15 定: "B名单改为先过基本面否决再买,
         #   名单保持暂停直到筛完"。此前这条规则只存在于 data/b_book.json 的一条文字记录里,
         #   本脚本(每天15:40由launchd生成次日名单)从来不知道它 → 每天产出的都是"未过门但可执行"的名单。
         #   09-15/09-16 靠我手动加 .paused 后缀挡住, 09-17 我没加, 而 b_auto_trade 盘中有13个
         #   买入触发点(09:30起), 距真实下单只差两分钟。**靠人记得的防线, 在人忙的那天就会失效。**
         #   ⛔为什么是加字段而不是改文件名: b_board_alert(09:27推送提醒)也读这个文件, 它只提醒不下单,
         #   不该被拦; 真正会花钱的是 b_auto_trade, 由它按本字段 fail-closed。
         #   默认值放在入口最窄的一端(本脚本每天只跑一次), 断言放在最宽的一端(消费端13个触发点)。
         '已过基本面筛':False,
         '已过基本面筛_说明':'筛完后置为 true 并在下方 基本面筛除 里写明否决了哪些、理由是什么; 未置 true 时 b_auto_trade 拒绝买入',
         '基本面筛除':[],
         'chains':sorted({c['ind'] for c in cands}),
         '⛔硬门槛':'四门过≥3; 排除一字板与ST与北交所与无市值数据。⛔市值门已于2026-09-10降级为打分维(原首板≥100亿/2板≥50亿挡掉68%样本却只提升5bp)',
         # ⛔2026-09-18 v14.0 大改革: 上面那四道封单门属旧体系判据, 已随 SABCT 一并废止。
         #   v14.0 策略二只做最高标 5 到 6 板、流通市值 30 亿以下, 买点在连板途中触板那一刻。
         #   本脚本尚未按新判据重写, 所以每天仍会产出一份按旧判据排序的名单。
         #   ⛔此前挡着它的只有 已过基本面筛=False 一道门, 而那道门拒绝的理由是"没筛基本面",
         #   不是"判据已废"。理由错了的拦截等于运气: 哪天基本面筛完置 true, 旧判据名单就放行。
         #   所以判据废止必须是**独立的一道门**, 由本脚本每天自动写入, 不靠人记得手动加后缀。
         #   (09-15/09-16 靠手加 .paused 挡住, 09-17 没加, 就是"靠人记得"失效的实例)
         '⛔判据已废_不得买入':True,
         '⛔判据已废_说明':'封单四门(首封<10:00 / 炸板=0 / 封板资金比≥3% / 同行业≥2只)属旧体系, '
                          '已随 2026-09-18 strategy_astock v14.0 废止。本名单仅供观察与复盘, '
                          '即使 已过基本面筛 置为 true 也不得据此买入。'
                          '按 v14.0 第四节(最高标5到6板、流通市值30亿以下、买点在连板途中)重写本脚本后, '
                          '才可将本字段置为 False。',
         '生成时间':datetime.datetime.now().isoformat(timespec='seconds'),
         '过滤统计':stat,'候选':cands}
    p=f'{ROOT}/data/b_watch_{nxt.strftime("%Y%m%d")}.json'
    # ⛔2026-09-18 加 DRY_RUN: 本脚本此前无法被无副作用验证(默认参数因涨停池未生成而退出,
    #   传历史日期又会覆盖掉已手工标注的既有名单), 而"改完总要测一下"是必然动作。
    #   先有开关再改逻辑, 顺序不能反。
    if os.environ.get('DRY_RUN')=='1':
        print('[DRY_RUN] 不写文件。out 顶层字段:'); print('   ', list(out.keys()))
        print(f'   判据已废_不得买入 = {out.get("⛔判据已废_不得买入")}   已过基本面筛 = {out.get("已过基本面筛")}')
        print(f'   本应写入 {os.path.basename(p)}, 候选 {len(cands)} 只')
        return
    json.dump(out,open(p,'w'),ensure_ascii=False,indent=1)
    print(f'过滤: 一字{stat["一字"]} 市值不足{stat["市值"]} 四门<3的{stat["门<3"]} ST/北交{stat["ST/北交"]}')
    print(f'→ {len(cands)} 只候选写入 {os.path.basename(p)} (供 {nxt} 盘前使用)')
    for c in cands: print(f'   {c["code"]} {c["name"]:<8}{c["lb"]}板 {c["gates"]}/4门 封{c["ratio"]*100:.1f}% 首封{c["t1"]} 市值{c["mcap"]}亿 {c["ind"]}({c["cc"]}只)')
if __name__=='__main__': main()
