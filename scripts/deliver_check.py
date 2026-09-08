#!/opt/homebrew/bin/python3
"""交付前扫描 — 省略号/截断/糊弄词。⛔2026-09-08 Buwen: "你做一堆省略号什么意思, 我是瞎子吗"
用法: deliver_check.py <文件或字符串>   退出码1=不合格"""
import sys,re
BAD=[(r'……|\.\.\.\.\.\.|⋯',' 省略号'),(r'前\s*\d+\s*[条只行]',' "前N条"截断'),
     (r'以下略|其余略|不再赘述|限于篇幅',' 主动省略'),(r'\(仅列|只列前',' 只列部分')]
def check(t):
    hits=[]
    for p,n in BAD:
        for m in re.finditer(p,t):
            hits.append((n.strip(), t[max(0,m.start()-40):m.end()+40].replace('\n',' ')))
    # ⛔已撤回结论回流检查(2026-09-08加): 我09-04撤回的数字, 09-08又当事实说了出来。
    #   撤回写在 backtest/CORRECTION.md, 被撤回的数字留在09-03任务台账 —— 两者不在同一路径,
    #   所以撤回拦不住引用。**撤回必须在路径上, 否则被撤回的数字会自己走回来。**
    import json,os
    rp=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data','retracted_claims.json')
    if os.path.exists(rp):
        for it in json.load(open(rp)).get('items',[]):
            for pat in it['claim_patterns']:
                for m in re.finditer(pat,t):
                    # ⛔2026-09-08 门自己误伤后加: 引用一个被撤回的数字**为了否定它**是合法的,
                    #   把它**当事实使用**才是问题。门只认模式不认上下文, 会把纠正文本也拦下来。
                    #   判据: 命中点前后60字内出现否定/撤回词 → 视为在纠正, 放行。
                    ctx=t[max(0,m.start()-60):m.end()+60]
                    if re.search(r'不是|已撤回|撤回于|错的|错了\d*倍|证伪|勿用|不得引用|作废|纠正|更正', ctx):
                        continue
                    hits.append((f"⛔已撤回结论 {it['id']}(撤于{it['retracted_on']})",
                                 f"...{t[max(0,m.start()-50):m.end()+50]}...  正确值: {it['correct_value'][:80]}"))
    return hits
if __name__=='__main__':
    import os
    a=' '.join(sys.argv[1:])
    t=open(a).read() if os.path.exists(a) else a
    h=check(t)
    if h:
        print(f'⛔交付不合格: {len(h)}处省略/截断')
        for n,c in h[:10]: print(f'  {n}: ...{c}...')
        print('  → 要完整列表就给完整, 不许"前8条……后4条"')
        sys.exit(1)
    print('✅ 无省略/截断')
