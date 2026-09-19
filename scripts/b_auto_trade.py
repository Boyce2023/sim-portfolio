#!/opt/homebrew/bin/python3
"""B策略全自动执行器 — 选股即推送 / 最早可交易时点即执行 / 执行即报告
⛔2026-09-08 Buwen当面质问后建: "如果你真的会忘为什么不代码化, 为什么呢?"
   我没有正当理由。模拟盘我有自主决策+执行+事后报告的授权(07-09定, 08-26/27/09-08共复发4次),
   每次都靠"记得"——靠记得就等于没有。三个环节全部代码化, 不留人工判断:

   ① 15:40 收盘选股完成 → **立即推飞书**(不埋在报告里)
   ② 09:25 竞价 / 09:30 开盘 → **自动执行**, 不等任何人确认
   ③ 成交 → **立即推飞书**报告代码/股数/价格/金额

⛔实操性铁律(2026-09-08 血的教训, 龙版传媒无效成交):
   B的买点是**当日盘中回落后再触及涨停价的那一瞬间**。封板一小时后再挂单, 前面压着巨额封单,
   真实市场排不进去——模拟盘的即时成交模型会给出假成交, 污染策略实证。
   所以: 昨日选出的候选, **必须在今日最早可交易时点执行**, 过了就作废不补。
   一字板同理不买(开盘价==最低价==涨停价, 全天没打开过, 买不进)。

用法: b_auto_trade.py notify      选股完成后推送名单(15:40 挂 b_watch_build 之后)
      b_auto_trade.py execute     最早可交易时点执行(09:30 挂)
      b_auto_trade.py sell        次日开盘卖出昨仓(09:30 挂, 先于 execute)
"""
import json,os,sys,datetime,subprocess,urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def fs(msg):
    r=subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),msg],
                     capture_output=True,timeout=20)
    if r.returncode!=0:
        print(f'⛔飞书失败 rc={r.returncode} {r.stderr.decode("utf-8","ignore")[:120]}',flush=True)
        print(f'   未送达: {msg[:200]}',flush=True)
    return r.returncode==0
def mkt(c): return 'sh' if c[0] in '56' else ('bj' if c[0] in '48' else 'sz')
def quote(codes):
    out={}
    for i in range(0,len(codes),400):
        q=','.join(mkt(c)+c for c in codes[i:i+400])
        try: raw=urllib.request.urlopen(f'http://qt.gtimg.cn/q={q}',timeout=8).read().decode('gbk','ignore')
        except Exception as e: print('⛔行情失败',type(e).__name__); continue
        for line in raw.split('\n'):
            p=line.split('~')
            if len(p)>44 and 'none_match' not in line:
                try: out[p[2]]={'n':p[1],'now':float(p[3]),'pc':float(p[4]),'open':float(p[5]),
                                'high':float(p[33]),'low':float(p[34]),'turn':float(p[38] or 0),
                                'flow':float(p[44]),'chg':float(p[32]),
                                'amount':float(p[37] or 0)*1e4,'name':p[1]}
                except ValueError: pass
    return out
def gain20(code):
    """板前20日涨幅(%): 用腾讯日线, 取涨停日(=前一交易日)收盘 vs 再往前20个交易日收盘。拿不到返回 None(打分strict会因此弃权)。"""
    try:
        pre='sh' if code[0]=='6' else ('bj' if code[0] in '489' else 'sz')
        u=f'https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={pre}{code},day,,,40,qfq'
        d=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=8).read().decode())
        k=(d['data'].get(pre+code) or {}); bars=k.get('qfqday') or k.get('day') or []
        if len(bars)<22: return None
        last=float(bars[-1][2]); ref=float(bars[-22][2])
        return round((last/ref-1)*100,2) if ref>0 else None
    except Exception as e:
        print(f'  {code} gain20取数失败: {type(e).__name__}',flush=True); return None

def watch_file(day=None):
    d=day or datetime.date.today().strftime('%Y%m%d')
    return f'{ROOT}/data/b_watch_{d}.json'

def notify():
    """① 选股完成立即推送 —— 不埋在长报告里"""
    p=watch_file()
    if not os.path.exists(p):
        fs(f'[B策略·选股] ⛔{datetime.date.today()} 短名单文件未生成({os.path.basename(p)}), 上游可能没跑 — 这不等于今天没候选'); return
    w=json.load(open(p)); c=w.get('候选',[])
    if not c:
        fs(f'[B策略·选股] {w.get("date")} 四门筛后**零候选**(文件正常, 确实没有过门的票)'); return
    lines=[f"{x['code']} {x['name']} {x['lb']}板 {x['gates']}/4门 {'满档' if x['gates']>=4 else '半档'} 市值{x.get('mcap','?')}亿 {x['ind']}" for x in c]
    # ⛔⛔2026-09-18: 推送文案必须反映执行端的真实状态, 否则是在对一个关死的门空转。
    #   execute() 有两道独立的门(已过基本面筛 / ⛔判据已废_不得买入), 任一不满足就一单不下。
    #   而原文案写死"明早最早可交易时点自动执行""我会自动下单并立刻报你, 不需要你确认",
    #   在两道门都关着的日子里等于每天承诺一件不会发生的事, 读的人还以为名单会被执行。
    #   ⛔这正是 #63 记的"B策略临板通道在对一个关死的执行端空转"。
    #   ⛔改成读门的状态而不是写死: 门以后重新打开时文案自动恢复, 不需要再改一次代码。
    _dead = w.get('⛔判据已废_不得买入') is True
    _unscreened = w.get('已过基本面筛') is not True
    if _dead or _unscreened:
        _why=[]
        if _dead: _why.append("判据已废(封单四门随 v14.0 废止, b_watch_build 尚未按新判据重写)")
        if _unscreened: _why.append("未过基本面筛(Buwen 09-15 定: B名单先过基本面否决再买)")
        head=f"[B策略·选股 {w.get('date')}] {len(c)}只候选, ⛔**不会下单**, 仅供观察与复盘:"
        tail=(f"\n⛔执行端当前关闭: {' 且 '.join(_why)}。"
              f"\nexecute() 的门会在明早每个买入触发点拒绝并落日志。**本条不是操作指令。**")
    else:
        head=f"[B策略·选股 {w.get('date')}] {len(c)}只候选, 明早最早可交易时点自动执行:"
        tail=(f"\n⛔买点=盘中回落后再触板那一瞬间; 一字板不买; 过了时点作废不补。"
              f"我会自动下单并立刻报你, 不需要你确认。")
    msg=head+"\n"+'\n'.join(lines)+tail
    print(msg); fs(msg)

def market_state():
    """全市场炸板率 + 各行业当日最高连板高度。
    ⛔取数失败返回 None(不返回0/不返回安全默认值) —— 故障不得降级成合法正常值。"""
    try:
        import akshare as ak
        day=datetime.date.today().strftime('%Y%m%d')
        zt=ak.stock_zt_pool_em(date=day)
        try: zb=ak.stock_zt_pool_zbgc_em(date=day)
        except Exception: zb=None
        nzt=0 if zt is None else len(zt); nzb=0 if zb is None else len(zb)
        if nzt+nzb==0: return None
        lead={}
        if nzt:
            for _,r in zt.iterrows():
                ind=str(r.get('所属行业') or '').strip()
                try: lb=int(r.get('连板数') or 1)
                except Exception: lb=1
                if ind: lead[ind]=max(lead.get(ind,0),lb)
        return {'bomb':nzb/(nzt+nzb),'nzt':nzt,'nzb':nzb,'lead':lead}
    except Exception as e:
        print(f'  ⛔全市场状态取数失败: {type(e).__name__}: {e}',flush=True)
        return None

def leader_streak(lead,ind):
    """行业名两边可能截断(watch写'农产品加', 涨停池写'农产品加工'), 用前缀互含匹配"""
    ind=(ind or '').strip()
    if not ind: return 0
    return max([v for k,v in (lead or {}).items() if k==ind or k.startswith(ind) or ind.startswith(k)] or [0])


def execute():
    """② 最早可交易时点自动执行 —— 不等任何人确认"""
    # ⛔取用链打在执行日志里, 每次都留痕(Buwen 09-08: 学了不调用等于没学)
    import subprocess as _sp
    print(_sp.run(['/opt/homebrew/bin/python3',f'{ROOT}/scripts/preflight.py','buy'],
                  capture_output=True,text=True).stdout)
    p=watch_file()
    if not os.path.exists(p): print(f'⛔无今日短名单 {p}'); return
    w=json.load(open(p)); cands=w.get('候选',[])
    if not cands: print('今日零候选'); return
    # ⛔⛔ 消费端兜底断言(2026-09-17新增, 治"规则只写在文档里、执行路径不认识它")
    #   Buwen 2026-09-15 定: "B名单改为先过基本面否决再买, 名单保持暂停直到筛完"。
    #   这条规则此前只存在于 data/b_book.json 的一条文字记录里, b_watch_build 生成名单时不知道它,
    #   于是每天自动生成的名单都处于"未过门但可执行"状态; 09-15/09-16 是我手动加 .paused 后缀挡住的,
    #   09-17 我没加, 而本函数在盘中有13个触发时点(09:30起), 距离真实下单只差两分钟。
    #   ⛔判据写成"缺标记就拒"而不是"有paused才拒": 后者会放行所有存量旧名单文件(它们都没有标记)。
    #   ⛔类型收紧: 判据写 `is not True` 而不是 `not w.get(...)` —— 隔离单测发现字符串 "false"
    #   是 truthy, 用后者会放行一个明写着未筛的名单。只有布尔 True 才算筛过。
    if w.get('已过基本面筛') is not True:
        msg=(f"[B策略⛔门] {os.path.basename(p)} 缺少'已过基本面筛'标记, 本轮拒绝买入(fail-closed)。"
             f"Buwen 09-15定: B名单先过基本面否决再买。未筛的名单不得进入执行路径。"
             f"筛完后把该字段置为 true(或写明筛除清单)再放行。")
        print(msg); fs(msg); return
    # ⛔⛔ 2026-09-18 第二道独立的门: 判据本身已废
    #   上一道门管的是"这份名单筛没筛基本面", 本道门管的是"这份名单的判据还算不算数"。
    #   ⛔两者必须分开: v14.0 废掉了封单四门, 而上一道门只要被置 true 就放行,
    #   拦截理由错了等于运气。哪天基本面筛完置 true, 一份按已废判据排序的名单就进了执行路径。
    #   写成 `is True` 而非 truthy 判断, 同 124 行的类型收紧理由(字符串 "false" 是 truthy)。
    if w.get('⛔判据已废_不得买入') is True:
        msg=(f"[B策略⛔判据门] {os.path.basename(p)} 标记为'判据已废', 本轮拒绝买入。"
             f"封单四门(首封<10:00/炸板=0/封板资金比≥3%/同行业≥2只)已随 2026-09-18 "
             f"strategy_astock v14.0 废止。按 v14.0 第四节(最高标5到6板、流通市值30亿以下、"
             f"买点在连板途中触板那一刻)重写 b_watch_build 后方可放行。")
        print(msg); fs(msg); return
    book=json.load(open(f'{ROOT}/data/b_book.json'))
    held={str(x.get('ticker'))[-6:] for x in (book.get('positions') or [])}
    room=3-len(held)
    if room<=0: print('⛔已持满3只'); return
    # ⛔2026-09-11 市场级硬门(回测下沉, 反直觉所以写清依据):
    #   全A 2017-2026 买当日首板次开进持有, 全市场炸板率>50% 当天: 5日超额-1.99%/胜率34.6%,
    #   20日-4.60%, n=2217, 是全表最强的单条排除规则。不加条件的首板基准是 5日+0.47%。
    ms=market_state()
    if ms is None:
        print('⛔全市场炸板率无法测量 → 本轮拒绝买入(fail-closed)')
        fs('[B策略⛔风控门] 全市场炸板率取数失败, 本轮拒绝买入。⛔这是fail-closed不是bug: 测不出市场是否安全就不下单。')
        return
    if ms['bomb']>0.50:
        print(f"⛔全市场炸板率 {ms['bomb']*100:.1f}% (涨停{ms['nzt']}/炸板{ms['nzb']}) >50% → 今日禁止打板")
        fs(f"[B策略·风控门触发] 全市场炸板率 {ms['bomb']*100:.1f}% (涨停{ms['nzt']} 炸板{ms['nzb']}) 超50%, 今日零买入。"
           f"回测依据: 该状态下买首板5日超额-1.99%/20日-4.60%/胜率34.6%(n=2217)。")
        return
    print(f"  市场炸板率 {ms['bomb']*100:.1f}% (涨停{ms['nzt']}/炸板{ms['nzb']}) ✅通过")
    q=quote([c['code'] for c in cands])
    done=[]
    for c in sorted(cands,key=lambda z:(-z['gates'],z.get('turn',99))):
        if room<=0: break
        code=c['code']; d=q.get(code)
        if not d or code in held: continue
        lim=round(d['pc']*(1.2 if code[:2] in ('30','68') else 1.1),2)
        # 逐条核对回测参数(PARAMS_B2权威)
        if abs(d['open']-lim)<0.02 and abs(d['low']-lim)<0.02: print(f'  {code} ⛔一字板不买'); continue
        # ⛔2026-09-11 板块龙头门(回测下沉): 板块已有≥3板龙头时买该板块"跟风首板",
        #   5日超额+0.05%/20日-2.03%, 劣于首板基准(+0.47%/-1.09%); 而板块一个连板都没有时
        #   +0.63%/-0.91% 最好。龙头是这一轮已被定价的证据, 不是入场证据。
        #   只管首板; 候选自己就是连板(lb>=2)时本门不适用。
        if (c.get('lb') or 1)==1:
            _hs=leader_streak(ms['lead'],c.get('ind'))
            if _hs>=3:
                print(f"  {code} ⛔板块龙头门: {c.get('ind')} 已有{_hs}板龙头, 首板跟风不买"); continue
        # ⛔2026-09-10 删除换手硬门: 换手已作为打分的一维(0~3%:+0.61pp 递减到 >25%:-1.65pp),
        #   硬门与打分并存会让打分永远跑不到(实测今日6只全被硬门拒, 打分代码一次没执行)。
        #   极端换手仍被拒: 换手40%即使其他维度全优, 总分+0.63 < FLOOR 1.36 → 不买(已反向注入验证)。
        if abs(d['now']-lim)>0.02: print(f'  {code} · 未触板(现{d["now"]} 涨停{lim}), 等触板'); continue
        # ⛔2026-09-10 删除市值硬门(原: 首板≥100亿 / 2板以上≥50亿)。
        #   实证(cn_hk_price_db 的 oshare×close 复原当时流通市值, 2025 样本 13945 条匹配率 100%):
        #   各市值档 gap1 均值 1.58% 到 1.94% 无单调性, 超额全在 ±0.22pp 内; 而该门挡掉 68% 样本
        #   只把均值从 +1.84% 提到 +1.89%。已降级为打分的 fmv 维, 不再一票否决。
        # ⛔2026-09-10 改: 二元门(gates>=4满档/否则半档) → 概率打分定档(Buwen令"所有规则按概率给")
        #   六维缺一即弃权(strict), 防"数据故障被当成合法正常值"。
        import b_score
        g20=gain20(code)
        sc,det=b_score.score(turn=d.get('turn'),amount=d.get('amount'),streak=c.get('lb') or 1,
                             gain20=g20,board=0.2 if code[:2] in ('30','68') else 0.1,
                             is_st=1 if 'ST' in (d.get('name') or '') else 0, fmv=d.get('flow'))
        frac,tier=b_score.sizing(sc)
        print(f"  {code} {b_score.explain(turn=d.get('turn'),amount=d.get('amount'),streak=c.get('lb') or 1,gain20=g20,board=0.2 if code[:2] in ('30','68') else 0.1,is_st=1 if 'ST' in (d.get('name') or '') else 0,fmv=d.get('flow'))}",flush=True)
        if frac<=0:
            continue
        size=book['pool_size']*frac
        sh=int(size/lim/100)*100
        if sh<100: continue
        r=subprocess.run(['/opt/homebrew/bin/python3',f'{ROOT}/scripts/execute_trade.py','buy',
            '--account','cn','--book','b','--ticker',code,'--shares',str(sh),'--at-price',str(lim),
            '--reason',f"B策略专户自动执行·概率打分{sc:+.2f}分→{tier}(四门{c['gates']}/4仅作参考不再定档)。触板即买, 涨停价{lim}成交。"
                        f"参数核对: 非一字板/换手{d['turn']}%<10/市值{d['flow']:.0f}亿≥{need}/前日涨>3%/{c['lb']}板。"
                        f"次日开盘价卖不留第二天。⛔自动执行不等确认(Buwen授权, 09-08代码化)"],
            capture_output=True,text=True,cwd=ROOT)
        ok='[OK]' in r.stdout
        print(f"  {code} {'✅成交' if ok else '⛔失败'} {sh}股@{lim}")
        if ok: done.append(f"{code} {d['n']} {sh}股@{lim} ={sh*lim:,.0f}元 打分{sc:+.2f}{tier}"); room-=1
        else:
            # ⛔2026-09-10 修: 原写法 stdout 非空就不打 stderr, 而 BLOCKED 消息走的正是 stderr,
            #   导致 09-08 起 13 笔失败全部无声。现在两股都打, 且 stderr 优先。
            if r.stderr: print('    ⛔stderr:', r.stderr.strip()[-300:])
            if r.stdout: print('    stdout:', r.stdout.strip()[-200:])
            fs(f"[B策略⛔执行失败] {code} {sh}股@{lim} 未成交。原因: {(r.stderr or r.stdout).strip()[-200:]}")
    # ③ 执行即报告
    if done:
        fs(f"[B策略·已成交 {datetime.date.today()}] 自动执行{len(done)}笔:\n"+'\n'.join(done)+"\n次日开盘卖出, 不留第二天。")
    else:
        fs(f"[B策略·未成交 {datetime.date.today()}] {len(cands)}只候选无一触板或全被参数门挡下, 今日零成交。")

def sell():
    """次日卖出昨仓。B无thesis只有溢价。

    ⛔⛔2026-09-18 规则已改, 本函数是旧实现, 入口已加 fail-closed 门。
      新规则(strategy_astock 4.5): **次日若再度封涨停, 持有到当日收盘再卖; 未封涨停, 开盘即卖。**
      本函数实现的是旧的"次日开盘无条件卖", 与规则不一致。
      依据(5板以上三种卖法同批样本对照, 超额已减同期全市场同口径中位):
        甲 次日开盘无条件卖   A段严口径 n=35 均值+1.01% t=1.05 不显著
        乙 封涨停则持到收盘   +3.27% t=2.90 胜率66% (放宽 n=142 时 t=5.27; B段 n=31 时 t=2.73)
        丙 次日收盘无条件卖   +0.76% t=0.53 不显著
      机制: 次日仍封板仅 29% 到 37%, 输时按最快方式认输、赢时让它跑满十个点, 不对称即收益。
      丙证明无条件持有不行, 必须是"封板才持"这个条件分支。

    ⛔为什么是拒绝执行而不是硬着头皮按旧规则卖: 旧规则会在封板那 29% 到 37% 的情况下
      把利润砍在开盘价, 而那正是全部超额的来源。**按已证伪的规则执行, 比不执行更贵。**
      当前不会被触发(策略二前置门二关闭、买入已被判据门拦死、B账本空仓), 但门要先在,
      因为"靠人记得"的防线在人忙的那天就会失效(09-15/09-16 手加.paused、09-17 没加)。

    ⛔以下旧实现保留, 重写时以它为基础, 集合竞价那部分是对的:
      2026-09-08修时点: 原挂09:30执行, 但开盘价是09:25:00集合竞价撮合产生的,
      09:30下单成交的是连续竞价实时价, 不是开盘价, 规则和实现对不上。
      现改挂 09:16/09:19/09:22 三次, 全在 9:15-9:25 申报窗口内。
      集合竞价只能限价单(沪3.3.6/深3.3.5, 市价单一律被拒);
      9:20-9:25 不可撤单但仍可新报; 9:25-9:30 交易所完全不接受申报。
      报价用跌停价挂卖(保证以集合竞价成交价即开盘价成交), 而非用昨收猜开盘价。
      ⛔重写要点: 需在 09:16-09:22 窗口判断"次日是否封涨停"。该判断在开盘那刻不可得,
      所以新规则的实现形态应是: 开盘先不卖, 盘中监测是否封板, 未封则立即卖、已封则等到收盘。
      这与现在"竞价窗口内一次性卖完"是两种结构, 不是改几行参数的事。"""
    book=json.load(open(f'{ROOT}/data/b_book.json'))
    ps=book.get('positions') or []
    if not ps: print('B账本空仓, 无需卖出'); return
    # ⛔⛔fail-closed 卖出门(2026-09-18): 有仓且规则与实现不一致 -> 拒绝执行并告警。
    _msg=("[B策略⛔卖出门] 本函数是旧的'次日开盘无条件卖'实现, 而 strategy_astock 4.5 已于 "
          "2026-09-18 改为'次日封涨停则持到当日收盘, 未封则开盘即卖'。规则与实现不一致, "
          "本轮拒绝自动卖出。⛔按已证伪的规则执行比不执行更贵: 旧规则会把封板那 29% 到 37% "
          "情况下的利润砍在开盘价, 而那正是全部超额的来源(开盘无条件卖 t=1.05 不显著, "
          "封板则持到收盘 t=2.90 到 5.27 胜率 65% 到 71%)。"
          f"⛔当前 B 账本有 {len(ps)} 只持仓需人工处置。重写本函数后删除本门。")
    print(_msg); fs(_msg); return
    q=quote([str(x['ticker'])[-6:] for x in ps]); done=[]
    for x in ps:
        code=str(x['ticker'])[-6:]; d=q.get(code)
        if not d: continue
        # 以开盘价记账(集合竞价成交价==开盘价); 现实中挂单价应用跌停价确保成交
        r=subprocess.run(['/opt/homebrew/bin/python3',f'{ROOT}/scripts/execute_trade.py','sell',
            '--account','cn','--ticker',code,'--all','--at-price',str(d['open'] or d['now']),
            '--reason',f"B策略规则卖出: 次日开盘价{d['open']}卖出, 不留第二天。B没有thesis只有溢价, 不设持有逻辑。"],
            capture_output=True,text=True,cwd=ROOT)
        if '[OK]' in r.stdout:
            pnl=(d['open']-x.get('avg_cost',d['open']))*x['shares']
            done.append(f"{code} {d['n']} {x['shares']}股@{d['open']} 盈亏{pnl:+,.0f}")
    if done: fs(f"[B策略·开盘卖出 {datetime.date.today()}]\n"+'\n'.join(done))

if __name__=='__main__':
    {'notify':notify,'execute':execute,'sell':sell}[(sys.argv[1:] or ['execute'])[0]]()
