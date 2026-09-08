#!/opt/homebrew/bin/python3
"""断言门 — agent 的趋势类断言必须过价格数据核验才能进决策
⛔2026-09-07 建, 起因是当天扫描的实证:
   agent 对章源钨业的裁决写"09-07三件套企稳信号当日齐备, 属回踩买点触发日",
   实测近5日 -6.4% / 距7月高 -32.3% / 量比0.63 = 缩量阴跌, 与"企稳"完全相反。
   6个候选近5日全负, 而当天全市场大反弹(创业板+3.41%)它们几乎全跑输。
   信了那句就是又一次冲动追涨(冲动追涨=Buwen自述的80%亏损来源)。
⭐判据(main提炼): 不是agent不好用, 是它的断言与事实之间必须有一道门。
   好门是"错了会自己露馅"的——趋势断言有唯一正确答案(价格), 对不上就是错的。

用法:
  claim_gate.py <ticker> "<agent的裁决文本>"     单只核验
  claim_gate.py --batch <json文件>               批量, 文件格式 [{"ticker":..,"claim":..}]
退出码: 0=全部通过 1=有断言被驳回
"""
import sys,os,json,re,datetime
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))

# 断言词 → 该断言隐含的价格事实
CLAIMS={
 '企稳':   'steady', '止跌':'steady', '回踩':'steady', '买点':'steady', '三件套':'steady',
 '突破':   'breakout', '新高':'breakout', '创新高':'breakout',
 '主升':   'uptrend', '上升趋势':'uptrend', '强势':'uptrend',
}
def px(code, start, end):
    import ifind_data_layer as I
    c=code if '.' in code else code+('.SH' if code[0] in '56' else ('.BJ' if code[0] in '48' else '.SZ'))
    r=I.history(c,start,end,indicators='close,high,volume')
    if r.get('errorcode') not in (0,'0',None): raise RuntimeError(f"iFinD ec={r.get('errorcode')}")
    t=(r.get('tables') or [{}])[0]; tb=t.get('table') or {}
    return t.get('time') or [], tb.get('close') or [], tb.get('high') or [], tb.get('volume') or []

def check(code, claim, asof=None):
    asof=asof or datetime.date.today().isoformat()
    start=(datetime.date.fromisoformat(asof)-datetime.timedelta(days=95)).isoformat()
    tm,cl,hi,vo=px(code,start,asof)
    if len(cl)<25: return [('数据不足',f'只有{len(cl)}根K线','SKIP')]
    # ⛔断言末根bar日期(免费源盘后92%停在上一交易日, 静默给旧值)
    if tm[-1]!=asof:
        return [('数据陈旧',f'末根bar={tm[-1]} 期望{asof} → 拒绝在旧数据上判断','REJECT')]
    r5=(cl[-1]/cl[-6]-1)*100
    r20=(cl[-1]/cl[-21]-1)*100
    peak=max(hi); dist=(cl[-1]/peak-1)*100
    v5=sum(vo[-5:])/5; v20=sum(vo[-20:])/20; vr=v5/v20 if v20 else 0
    hi20=max(hi[-21:-1]) if len(hi)>21 else peak
    out=[]
    # ⛔否定式不是断言: "未现真企稳"/"尚未到买点"/"非主升" 是agent在说不好, 不该被当成它声称好
    #   (2026-09-07 首次回测本门时自己踩到: 三条明确写"未企稳"的裁决被标成REJECT, 输出失去区分度)
    NEG=('未','不','尚未','没有','非','难','无')
    kinds=set()
    for k in CLAIMS:
        i=claim.find(k)
        while i>=0:
            pre=claim[max(0,i-6):i]
            if not any(n in pre for n in NEG): kinds.add(CLAIMS[k]); break
            i=claim.find(k,i+1)
    if not kinds: return [('无趋势断言','该裁决未声称企稳/突破/主升, 不适用本门','SKIP')]
    for kind in sorted(kinds):
        if kind=='steady':
            bad=[]
            if r5<-3: bad.append(f'近5日{r5:+.1f}%(仍在跌)')
            if vr>1.5: bad.append(f'量比{vr:.2f}(放量下跌)')
            if dist<-25: bad.append(f'距区间高{dist:+.1f}%(深跌段)')
            out.append(('企稳断言', f'近5日{r5:+.1f}% 近20日{r20:+.1f}% 距高{dist:+.1f}% 量比{vr:.2f}',
                        'REJECT' if bad else 'PASS') if not bad else
                       ('企稳断言', f'⛔与事实矛盾: {" / ".join(bad)}', 'REJECT'))
        elif kind=='breakout':
            ok=cl[-1]>hi20
            out.append(('突破断言', f'现{cl[-1]:.2f} vs 前20日高{hi20:.2f}'+('' if ok else ' → 未创新高'),
                        'PASS' if ok else 'REJECT'))
        elif kind=='uptrend':
            ok=r20>0 and cl[-1]>sum(cl[-20:])/20
            out.append(('主升断言', f'近20日{r20:+.1f}% 现价{"高于" if cl[-1]>sum(cl[-20:])/20 else "低于"}20日均线',
                        'PASS' if ok else 'REJECT'))
    return out

def main():
    a=sys.argv[1:]
    if not a: print(__doc__); sys.exit(2)
    items=[]
    if a[0]=='--batch': items=json.load(open(a[1]))
    else: items=[{'ticker':a[0],'claim':' '.join(a[1:])}]
    bad=0
    for it in items:
        tk=str(it['ticker'])[-6:]
        try: res=check(tk,it.get('claim') or '')
        except Exception as e: print(f'{tk}  ⛔核验失败 {type(e).__name__} {str(e)[:60]}'); bad+=1; continue
        for name,detail,verdict in res:
            mark={'PASS':'✅','REJECT':'⛔','SKIP':'· '}[verdict]
            print(f'{mark} {tk} {name}: {detail}')
            if verdict=='REJECT': bad+=1
    print(f'\n{"="*60}\n{len(items)}条断言, 驳回 {bad} 处')
    sys.exit(1 if bad else 0)
if __name__=='__main__': main()
