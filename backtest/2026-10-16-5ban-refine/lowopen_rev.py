"""百洋 10-19 同型: 五板后第三天(T+2)低开<=-4.5%, 盘中碰跌停, 收盘翻红(高于前收). 从当天收盘算之后走势."""
exec(open('lowopen.py').read().split("for day in (2,3):")[0])
d=run(2)
d['touch_dt']=d.low2<=(d.prevc2*(1-d.lim2)).round(2)+0.011
d['red']=d.close2>d.prevc2
for h in (1,2,3): d[f'cc{h}']=d[f'close{2+h}']*d[f'adjf{2+h}']/(d.close2*d.adjf2)-1
def rr(x,lab):
    if len(x)==0: print(lab,0); return
    print(lab,f"n={len(x)}",' | '.join(f"收盘后{h}日 均{x[f'cc{h}'].mean()*100:+.1f}% 中位{x[f'cc{h}'].median()*100:+.1f}% 胜{(x[f'cc{h}']>0).mean()*100:.0f}%" for h in (1,2,3)))
lo=d[d.gap<=-0.045]
for per,m in [('2026全年',lo.date>='2026-01-01'),('2024起',lo.date>='2024-01-01')]:
    print(per); rr(lo[m&lo.touch_dt&lo.red],'  低开+碰跌停+收盘翻红'); rr(lo[m&lo.red],'  低开+收盘翻红(不管碰没碰跌停)'); rr(lo[m&~lo.red],'  低开+收盘没翻红')
print(lo[lo.touch_dt&lo.red][['date','code','gap','cc1','cc3']].assign(gap=lambda z:(z.gap*100).round(1),cc1=lambda z:(z.cc1*100).round(1),cc3=lambda z:(z.cc3*100).round(1)).to_string(index=False))
