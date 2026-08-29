#!/usr/bin/env python3
"""进程级超时守护: SIGALRM杀不死baostock的C阻塞(08-28验尸确认),子进程+kill -9才行。
用法: python3 run_guarded.py <总超时秒> <重试次数> <脚本> """
import sys,subprocess,time,os,signal
tmo,retries,script=int(sys.argv[1]),int(sys.argv[2]),sys.argv[3]
for att in range(1,retries+1):
    print(f'[guard] 第{att}次启动 {script} (超时{tmo}s)',flush=True)
    p=subprocess.Popen(['python3',script],stdout=sys.stdout,stderr=sys.stderr,preexec_fn=os.setsid)
    t0=time.time()
    while p.poll() is None:
        time.sleep(15)
        if time.time()-t0>tmo:
            print(f'[guard] ⛔超时{tmo}s,kill -9 进程组',flush=True)
            os.killpg(os.getpgid(p.pid),signal.SIGKILL)
            time.sleep(3)
            break
    if p.poll()==0:
        print(f'[guard] ✓ {script} 完成',flush=True); sys.exit(0)
    print(f'[guard] 第{att}次失败(exit={p.poll()}),{"重试" if att<retries else "放弃"}',flush=True)
    time.sleep(30)
sys.exit(1)
