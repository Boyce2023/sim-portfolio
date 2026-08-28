#!/usr/bin/env python3
"""delay参数全年验证(2026-08-26承诺的欠账): delay=0/1/2 在2025全年+2026Q1逐月"""
import sys;sys.path.insert(0,'/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban')
from engine import load, signals
from engine_delay import run_delay
print('%-12s %8s %8s %8s'%('区间','delay0','delay1','delay2'),flush=True)
import os
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
for db,m0,m1,lab in [('univ2025.db','2025-01-01','2025-12-31','2025全年'),
                     ('univ2025.db','2025-01-01','2025-06-30','2025H1'),
                     ('univ2025.db','2025-07-01','2025-12-31','2025H2'),
                     ('univ202601.db','2026-01-01','2026-01-31','2026-01'),
                     ('univ202602.db','2026-02-01','2026-02-28','2026-02'),
                     ('univ202603.db','2026-03-01','2026-03-31','2026-03')]:
    by=load(B+db);TD=sorted({b[1] for bars in by.values() for b in bars if m0<=b[1]<=m1})
    sig=signals(by,m0,m1)
    navs=[]
    for d in (0,1,2):
        nav,tr,log=run_delay(by,sig,TD,TD[-1],delay=d)
        navs.append(nav)
    print('%-12s %8.4f %8.4f %8.4f'%(lab,*navs),flush=True)
print('DONE',flush=True)
