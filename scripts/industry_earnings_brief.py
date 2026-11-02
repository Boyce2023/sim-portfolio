#!/usr/bin/env python3
"""每日全市场行业业绩普遍情况扫描与播报 (2026-11-02 上线)
覆盖:
1) 最新财报季各行业营收与净利同比中位数强弱榜 (RPT_LICO_FN_CPD)
2) 近24小时/近5日新增定期报告与业绩预告按行业聚合 (RPT_PUBLIC_OP_NEWPREDICT)
输出: 返回结构化 dict 供 daily_brief_gen.py 写入晨报，支持 --push 推送飞书。
"""
import os
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import argparse, datetime, json, subprocess, sys
import requests
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0"}
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))
CAL_PATH = os.path.expanduser("~/claude-projects/sim-portfolio/trading_calendar.json")


def is_trading_day(d: datetime.date) -> bool:
    if d.weekday() >= 5:
        return False
    if os.path.exists(CAL_PATH):
        try:
            cal = json.load(open(CAL_PATH, encoding="utf-8"))
            if d.isoformat() in set(cal.get("trading_days_by_market", {}).get("cn_closed_dates", [])):
                return False
        except Exception:
            pass
    return True


def fetch_latest_season_summary(report_date: str = "2026-09-30") -> dict:
    s = requests.Session()
    s.trust_env = False
    rows = []
    for pg in range(1, 14):
        url = (
            "http://datacenter-web.eastmoney.com/api/data/v1/get?"
            "reportName=RPT_LICO_FN_CPD&columns=SECURITY_CODE,SECURITY_NAME_ABBR,PUBLISHNAME,"
            "REPORTDATE,UPDATE_DATE,TOTAL_OPERATE_INCOME,YSTZ,PARENT_NETPROFIT,SJLTZ"
            f"&filter=(REPORTDATE%3D'{report_date}')&pageNumber={pg}&pageSize=500"
        )
        r = s.get(url, headers=UA, timeout=6).json()
        chunk = (r.get("result") or {}).get("data") or []
        rows.extend(chunk)
        if len(chunk) < 500:
            break
    if not rows:
        return {"error": "empty_cpd"}

    df = pd.DataFrame(rows)
    df["YSTZ"] = pd.to_numeric(df["YSTZ"], errors="coerce")
    df["SJLTZ"] = pd.to_numeric(df["SJLTZ"], errors="coerce")
    df["upd"] = df["UPDATE_DATE"].astype(str).str[:10]

    g = df.dropna(subset=["PUBLISHNAME", "SJLTZ"]).groupby("PUBLISHNAME").agg(
        n=("SECURITY_CODE", "count"),
        med_rev=("YSTZ", "median"),
        med_np=("SJLTZ", "median"),
        pos_pct=("SJLTZ", lambda x: (x > 0).mean() * 100.0),
    )
    g = g[g["n"] >= 15].sort_values("med_np", ascending=False)

    def fmt_row(idx, r):
        mv = f"正{r['med_np']:.1f}%" if r["med_np"] >= 0 else f"负{abs(r['med_np']):.1f}%"
        rv = f"正{r['med_rev']:.1f}%" if r["med_rev"] >= 0 else f"负{abs(r['med_rev']):.1f}%"
        return f"{idx}（{int(r['n'])}家，净利中位{mv}，营收中位{rv}，正增占{r['pos_pct']:.0f}%）"

    top5 = [fmt_row(i, r) for i, r in g.head(5).iterrows()]
    bot5 = [fmt_row(i, r) for i, r in g.tail(5).sort_values("med_np").iterrows()]

    # Recent newly disclosed forecasts (last 5 days)
    cutoff = (datetime.datetime.now(TZ_CN).date() - datetime.timedelta(days=5)).isoformat()
    pred_summary = []
    try:
        purl = (
            "http://datacenter-web.eastmoney.com/api/data/v1/get?"
            "reportName=RPT_PUBLIC_OP_NEWPREDICT&columns=SECURITY_CODE,SECURITY_NAME_ABBR,"
            "PUBLISHNAME,REPORT_DATE,NOTICE_DATE,PREDICT_TYPE,ADD_AMP_LOWER,ADD_AMP_UPPER"
            f"&filter=(NOTICE_DATE%3E%3D'{cutoff}')&pageNumber=1&pageSize=500"
        )
        pr = s.get(purl, headers=UA, timeout=6).json()
        pchunk = (pr.get("result") or {}).get("data") or []
        if pchunk:
            pdf = pd.DataFrame(pchunk)
            pos_types = {"预增", "略增", "扭亏", "续盈"}
            pg_ind = pdf.dropna(subset=["PUBLISHNAME"]).groupby("PUBLISHNAME").agg(
                cnt=("SECURITY_CODE", "count"),
                good=("PREDICT_TYPE", lambda x: x.isin(pos_types).sum()),
            ).sort_values("cnt", ascending=False)
            for idx, r in pg_ind.head(5).iterrows():
                pred_summary.append(f"{idx}新增{int(r['cnt'])}家预告（预喜{int(r['good'])}家）")
    except Exception:
        pass

    return {
        "report_date": report_date,
        "total_companies": len(df),
        "top5_industries": top5,
        "bottom5_industries": bot5,
        "recent_forecasts_5d": pred_summary,
    }


def format_feishu_text(res: dict) -> str:
    today_s = datetime.datetime.now(TZ_CN).strftime("%Y年%m月%d日")
    lines = [
        f"【每日A股行业业绩普遍情况播报 · {today_s}】",
        f"最新财报季（{res.get('report_date','').replace('-','年',1).replace('-','月')+'日'}，共{res.get('total_companies',0)}家）：",
        "领跑前五行业：" + "；".join(res.get("top5_industries", [])),
        "垫底后五行业：" + "；".join(res.get("bottom5_industries", [])),
    ]
    if res.get("recent_forecasts_5d"):
        lines.append("近5日新增业绩预告集中行业：" + "；".join(res["recent_forecasts_5d"]))
    else:
        lines.append("近5日新增业绩预告：暂无行业集中披露。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    res = fetch_latest_season_summary()
    if "error" in res:
        print(f"ERROR: {res['error']}", file=sys.stderr)
        sys.exit(1)
    txt = format_feishu_text(res)
    print(txt)
    if args.push and is_trading_day(datetime.datetime.now(TZ_CN).date()):
        if args.dry_run:
            print("[DRY_RUN] 跳过飞书发送")
        else:
            sh = os.path.expanduser("~/.claude/session-remote/fs-reply.sh")
            subprocess.run(["bash", sh, txt], check=False, timeout=25)


if __name__ == "__main__":
    main()
