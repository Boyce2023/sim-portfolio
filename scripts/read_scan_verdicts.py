#!/opt/homebrew/bin/python3
"""读扫描裁决的唯一入口 — 自动过断言门, 不给未核验的原始裁决
⛔2026-09-07 建。为什么不是"记得跑claim_gate":
   靠自觉的规则=零执行(纪律下沉铁律)。今天已踩两次同族: ①待裁决台账建好了但没人叫它,
   08-24的承诺逾期11天 ②agent说章源钨业"企稳三件套齐备属回踩买点", 我差点直接用。
   所以门不能是"我记得跑的一步", 必须是"我读裁决时绕不过去的那道"。
用法: read_scan_verdicts.py <workflow_journal路径或run目录>
"""
import sys,os,json,subprocess
HERE=os.path.dirname(os.path.abspath(__file__))
def load(p):
    if os.path.isdir(p): p=os.path.join(p,'journal.jsonl')
    out=[]
    for line in open(p):
        try: j=json.loads(line)
        except Exception: continue
        if j.get('type')!='result': continue
        v=j.get('result')
        if isinstance(v,dict) and 'decision' in v: out.append(v)
    return out
def main():
    if len(sys.argv)<2: print(__doc__); sys.exit(2)
    vs=load(sys.argv[1])
    if not vs: print('未找到任何含 decision 的裁决'); sys.exit(0)
    print(f'扫描裁决 {len(vs)} 条 — 全部先过断言门再显示\n')
    claims=[]
    for v in vs:
        tk=str(v.get('ticker') or v.get('code') or '').strip()
        txt=' '.join(str(v.get(k) or '') for k in ('sabct','trend','one_line','fundamental'))
        if tk: claims.append({'ticker':tk,'claim':txt,'_v':v})
        else:  claims.append({'ticker':'','claim':txt,'_v':v})
    # 无ticker的裁决先标出来——没有ticker就无法核验, 这本身是缺陷
    noid=[c for c in claims if not c['ticker']]
    if noid:
        print(f'⛔ {len(noid)} 条裁决没有 ticker 字段, 无法做价格核验。')
        print('   这不是"暂时没查到", 是这批裁决物理上不可核验——decision不带标的代码,')
        print('   任何趋势断言都无从对证。修 workflow schema 让 Step2 必须回填 ticker。\n')
    ok=[c for c in claims if c['ticker']]
    if ok:
        tmp='/tmp/gm_scan_claims.json'
        json.dump([{'ticker':c['ticker'],'claim':c['claim']} for c in ok],open(tmp,'w'),ensure_ascii=False)
        subprocess.run([sys.executable,os.path.join(HERE,'claim_gate.py'),'--batch',tmp])
    print('\n'+'='*64)
    print('决策分布:', {d: sum(1 for v in vs if v.get('decision')==d) for d in {x.get('decision') for x in vs}})
    print('⛔watch档检查(勿再误判): rule_conflicts_registry 冲突⑥已裁决——T18废除的是"裸watch/挂空等回调",')
    print('   workflow的watch=T16框架(强制watch_expiry三件套+到期强裁)是有闭环的, 不删不改判。')
    print('   我已因此误判3次(08-26/08-27/09-07)。要查的不是"有没有watch", 是"watch有没有填三件套":')
    for v in vs:
        if v.get('decision')=='watch':
            we=v.get('watch_expiry')
            print(f"     {v.get('ticker') or '?'} watch_expiry={'⛔未填→按纪律降级reject' if not we else we[:90]}")
if __name__=='__main__': main()
