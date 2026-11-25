#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
audit_live_trades_mtd.py — A股实盘/模拟盘近一月成交流水与基准净超额自动核验工具（A2 根治漏报深物业A）

功能：
  1. 同时读取 sim-portfolio/portfolio_state.json (trade_log, cn) 与 sim-portfolio/data/real_broker_trades_cn.json (实盘核对底表)；
  2. 强制核验 data_as_of_date 是否等于最新沪深300收盘日（防拿过期回测台账漏报近期实盘单）；
  3. 精确计算当月/近一月已平仓净收益、在持浮盈亏、胜率与同期沪深300净超额（D15 四必核）。
⛔ 严禁 import yfinance（D12 铁律）。
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
PS_PATH = f"{ROOT}/sim-portfolio/portfolio_state.json"
REAL_PATH = f"{ROOT}/sim-portfolio/data/real_broker_trades_cn.json"


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_HDR = {"User-Agent": "Mozilla/5.0"}


def _csi300_kline(n: int = 40) -> list:
    cache_p = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
    out = []
    if os.path.exists(cache_p):
        raw = json.load(open(cache_p, encoding="utf-8")).get("sh000300") or {}
        if isinstance(raw, dict):
            out = sorted((str(k)[:10], float(v)) for k, v in raw.items())[-n:]
    # Overlay latest live Tencent quote for sh000300
    try:
        req = urllib.request.Request("http://qt.gtimg.cn/q=sh000300", headers=_HDR)
        p_arr = _OPENER.open(req, timeout=6).read().decode("gbk", "ignore").split("~")
        if len(p_arr) > 31 and p_arr[3]:
            dt_raw = str(p_arr[30])[:8]
            if len(dt_raw) == 8 and dt_raw.isdigit():
                dt_s = f"{dt_raw[:4]}-{dt_raw[4:6]}-{dt_raw[6:8]}"
                val = float(p_arr[3])
                if not out or dt_s > out[-1][0]:
                    out.append((dt_s, val))
                elif dt_s == out[-1][0]:
                    out[-1] = (dt_s, val)
    except Exception:
        pass
    return out


def _live_close(c6: str) -> float:
    sym = ("sh" if c6.startswith("6") else "sz") + c6
    req = urllib.request.Request(f"http://qt.gtimg.cn/q={sym}", headers=_HDR)
    raw = _OPENER.open(req, timeout=6).read().decode("gbk", "ignore")
    p = raw.split("~")
    return float(p[3]) if len(p) > 3 and p[3] else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=datetime.datetime.now().strftime("%Y-%m"), help="YYYY-MM")
    args = ap.parse_args()

    csi = _csi300_kline(45)
    latest_mkt_dt = csi[-1][0]
    m_bars = [b for b in csi if b[0].startswith(args.month)]
    prev_bars = [b for b in csi if b[0] < (m_bars[0][0] if m_bars else args.month + "-01")]
    csi_mtd = ((m_bars[-1][1] / prev_bars[-1][1]) - 1.0) * 100.0 if (m_bars and prev_bars) else 0.0

    ps = json.load(open(PS_PATH, encoding="utf-8"))
    sim_cn = [t for t in (ps.get("trade_log") or []) if str(t.get("account", "")).lower() in ("cn", "a_share")]
    real_doc = json.load(open(REAL_PATH, encoding="utf-8")) if os.path.exists(REAL_PATH) else {"as_of_date": "", "trades": []}
    real_trades = real_doc.get("trades") or []

    real_as_of = str(real_doc.get("as_of_date", ""))
    stale_warn = (real_as_of < latest_mkt_dt)
    print(f"=== [A股实盘/模拟盘成交流水自动核验 · {args.month}] ===")
    print(f"  最新沪深300收盘日={latest_mkt_dt} | 实盘台账截止日={real_as_of or '缺失'} | 状态={'⚠️滞后需补录' if stale_warn else '✅零滞后同步'}")
    print(f"  同期沪深300({args.month} MTD)={csi_mtd:+.2f}% | 模拟盘cn累计流水={len(sim_cn)}笔 | 实盘台账本月={len([t for t in real_trades if str(t.get('buy_date','')).startswith(args.month)])}笔")

    m_real = [t for t in real_trades if str(t.get("buy_date", "")).startswith(args.month) or str(t.get("sell_date", "")).startswith(args.month)]
    nav = 1.0
    closed_n = 0
    wins = 0
    for t in m_real:
        st = t.get("status", "closed")
        if st == "closed":
            ret = float(t["net_ret_pct"])
            nav *= (1.0 + ret / 100.0)
            closed_n += 1
            if ret > 0:
                wins += 1
            print(f"  [已平] {t['buy_date']}->{t['sell_date']} | {t['code']} {t['name']} ({t.get('strategy','')}) | 买{t['buy_px']} 卖{t['sell_px']} | 净收益{ret:+.2f}%")
        else:
            cur = _live_close(t["code"])
            u_ret = (cur / float(t["buy_px"]) - 1.0) * 100.0 if cur > 0 else 0.0
            print(f"  [在持] {t['buy_date']}起 | {t['code']} {t['name']} ({t.get('strategy','')}) | 买{t['buy_px']} 现{cur:.2f} | 浮盈亏{u_ret:+.2f}%")

    mtd_pct = (nav - 1.0) * 100.0
    excess = mtd_pct - csi_mtd
    wr = (wins / closed_n * 100.0) if closed_n else 0.0
    print(f"  【{args.month} 实盘已平汇总】{closed_n}笔 | 胜率{wr:.1f}% | 复利净收益{mtd_pct:+.2f}% | 相对沪深300净超额{excess:+.2f}个百分点")
    if stale_warn:
        sys.exit(2)


if __name__ == "__main__":
    main()
