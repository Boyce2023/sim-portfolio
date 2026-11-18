#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""rd_master_trading_data_sync.py — 五大主战策略全链路零延迟数据同步、缓存重算与 SLA 硬门禁总控"""
import os, sys, json, time, sqlite3, datetime, subprocess
import pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
SCRIPTS_DIR = f"{SIM_DIR}/scripts"
ND_DIR = f"{ROOT}/news-dashboard"
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from rd_incremental_sources import sync_index_klines_cache, sync_lhb_parquets, sync_ths_kpl_and_micro_tape

def _probe_tencent_sh_date() -> str:
    try:
        import urllib.request
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        raw = op.open(urllib.request.Request("http://qt.gtimg.cn/q=sh000001", headers={"User-Agent": "Mozilla/5.0"}), timeout=3).read().decode("gbk", "ignore")
        p = raw.split('="', 1)[1].split("~")
        ts = str(p[30])[:8]
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) == 8 and ts.isdigit() else ""
    except Exception:
        return ""

def _verify_cross_script_zero_drift() -> list[str]:
    errs = []
    try:
        bt2 = f"{SIM_DIR}/backtests_astock2"
        for p in (SCRIPTS_DIR, bt2, f"{bt2}/assets"):
            if p not in sys.path:
                sys.path.insert(0, p)
        from fast_1to2_today import evaluate_1to2_v19_df
        from live_daily_question_builder import score_auction_candidates
        from live_3to4_v40_engine import score_single_3to4_v40_row
        from score_3to4_v31_card import score_single_3to4_row

        c1 = json.load(open(f"{DATA_DIR}/1to2_premarket_cache.json", encoding="utf-8"))
        mock_q = {}
        for i, x in enumerate(c1.get("candidates", [])):
            pre = float(x["pre_c"])
            op = round(pre * (1.0 + 0.032 + (i % 5) * 0.008), 2)
            mock_q[x["c6"]] = {"name": x.get("name",""), "pre": pre, "open": op, "low": op, "high": op, "cur": op, "q_dt": c1.get("next_dt", "2099-01-01")}
        df_ssot, _ = evaluate_1to2_v19_df(c1, mock_q)
        sc_quiz, _ = score_auction_candidates(c1, mock_q)
        if not df_ssot.empty:
            m1 = {r["c6"]: (round(float(r["tot"]), 2), bool(r["ok"])) for _, r in df_ssot.iterrows()}
            m2 = {r["c6"]: (round(float(r["tot"]), 2), bool(r["ok"])) for r in sc_quiz}
            if m1 != m2:
                errs.append("drift_1to2_ssot_vs_quiz")

        c3 = json.load(open(f"{DATA_DIR}/3to4_premarket_cache.json", encoding="utf-8"))
        for r in c3.get("candidates", []):
            row = dict(r, **c3.get("env", {}), open_pct=0.055, buyable_open=True, is_top1_3b_open=True, plate_fb_ho_cnt=2, plate_fb_yz_cnt=0, plate_peers_open_avg=0.02)
            r_a = score_single_3to4_v40_row(row)
            r_b = score_single_3to4_row(row)
            if int(r_a["score"]) != int(r_b["score"]) or bool(r_a["passed_skeleton"]) != bool(r_b["passed_skeleton"]):
                errs.append(f"drift_3to4_v40_vs_card({r['code']})")
    except Exception as e:
        errs.append(f"drift_check_exception({e})")
    return errs

def _get_trade_dates() -> list[str]:
    tbl = ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
        columns=["date"], filter=(ds.field("date") >= ds.scalar(datetime.date(2026, 9, 1))) if hasattr(ds, "scalar") else None
    ).to_table()
    s = sorted(set(d.strftime("%Y-%m-%d") for d in tbl.column("date").to_pylist() if d))
    return s[-40:]

def _sync_ir_qa_recent():
    pit_db = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
    ir_db = f"{SIM_DIR}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
    if not (os.path.exists(pit_db) and os.path.exists(ir_db)): return ""
    cut = (datetime.date.today() - datetime.timedelta(days=15)).isoformat()
    c_src = sqlite3.connect(f"file:{pit_db}?mode=ro", uri=True)
    rows = c_src.execute(
        "SELECT ann_id, sec_code, sec_name, pub_datetime_cst, trade_date_avail, title FROM notices "
        "WHERE pub_datetime_cst >= ? AND (title LIKE '%活动记录%' OR title LIKE '%投资者关系%')", (cut,)
    ).fetchall()
    c_src.close()
    c_dst = sqlite3.connect(ir_db, timeout=30.0)
    if rows:
        now_s = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c_dst.executemany(
            "INSERT OR IGNORE INTO ir_qa (announcement_id, sec_code, sec_name, pub_datetime_cst, trade_date_avail, title, fetched_at, fetch_status) VALUES (?,?,?,?,?,?,?,'META_SYNC')",
            [(r[0], r[1], r[2], r[3], r[4], r[5], now_s) for r in rows]
        )
        c_dst.commit()
    mx = c_dst.execute("SELECT max(pub_datetime_cst) FROM ir_qa").fetchone()[0] or ""
    c_dst.close()
    return mx[:10]

def main():
    t0 = time.time()
    now = datetime.datetime.now()
    today_s = now.strftime("%Y-%m-%d")
    hm = now.hour * 100 + now.minute
    errors = []

    # Step 1: 若工作日 >=15:15 且日线未到今日，立刻跑日线入库与开盘啦盘后归档
    t_dates = _get_trade_dates()
    if now.weekday() < 5 and hm >= 1515 and (not t_dates or t_dates[-1] < today_s):
        subprocess.run([sys.executable, f"{SCRIPTS_DIR}/cn_price_db_update.py"], check=False, timeout=240)
        t_dates = _get_trade_dates()
        sh_dt = _probe_tencent_sh_date()
        if sh_dt and (not t_dates or sh_dt > t_dates[-1]):
            t_dates.append(sh_dt)
    latest_dt = t_dates[-1]
    prev_dt = t_dates[-2] if len(t_dates) >= 2 else latest_dt

    if hm >= 1515 and now.weekday() < 5:
        try: subprocess.run([sys.executable, f"{ND_DIR}/astock_concept_vocab.py", "--today"], check=False, timeout=90)
        except subprocess.TimeoutExpired: errors.append("kpl_vocab_timeout")
        try: subprocess.run([sys.executable, f"{SCRIPTS_DIR}/kpl_archive.py", "zdjk"], cwd=SIM_DIR, check=False, timeout=45)
        except subprocess.TimeoutExpired: errors.append("kpl_zdjk_timeout")
    try:
        subprocess.run([sys.executable, f"{ND_DIR}/astock_concepts.py", "--skip-extract", "--dry"], check=False, timeout=35)
    except subprocess.TimeoutExpired:
        print("[WARN] astock_concepts --dry timed out after 35s, continuing core sync", flush=True)

    # Step 2: 双公告库 (notices.db + cninfo_notices_5y_pit.db) 滚动全刷 (防晚间/周末/早盘漏单)
    r1 = subprocess.run([sys.executable, f"{SCRIPTS_DIR}/sync_notices_db.py", "--recent"], check=False, timeout=120)
    r2 = subprocess.run([sys.executable, f"{SCRIPTS_DIR}/backfill_cninfo_5y_pit.py", "--recent"], check=False, timeout=150)
    if r1.returncode != 0: errors.append(f"sync_notices_db rc={r1.returncode}")
    if r2.returncode != 0: errors.append(f"backfill_cninfo_5y_pit rc={r2.returncode}")
    ir_max = _sync_ir_qa_recent()

    # Step 3: 指数K线 + 龙虎榜买卖前五 + 同花顺涨停池 + KPL合并库 + 微观封单库
    idx_max = sync_index_klines_cache(latest_dt)
    lhb_max = sync_lhb_parquets(latest_dt)
    kpl_tape_max = sync_ths_kpl_and_micro_tape(t_dates)

    # Step 4: 全量重算实盘与研发策略盘前缓存 + 每日实战考题
    f_4to5 = f"{SIM_DIR}/backtests_astock2/fast_4to5_today.py" if os.path.exists(f"{SIM_DIR}/backtests_astock2/fast_4to5_today.py") else f"{SCRIPTS_DIR}/fast_4to5_today.py"
    cache_builders = [
        ("s5_1to2",        [sys.executable, f"{SCRIPTS_DIR}/fast_1to2_today.py", "--build-cache"],        f"{DATA_DIR}/1to2_premarket_cache.json"),
        ("s1_high_dragon", [sys.executable, f"{SCRIPTS_DIR}/fast_high_dragon_today.py", "--build-cache"], f"{DATA_DIR}/high_dragon_premarket_cache.json"),
        ("s2_3to4",        [sys.executable, f"{SCRIPTS_DIR}/fast_3to4_today.py", "--build-cache"],        f"{DATA_DIR}/3to4_premarket_cache.json"),
        ("s3_4to5",        [sys.executable, f_4to5, "--build-cache"],                                     f"{DATA_DIR}/4to5_premarket_cache.json"),
        ("s4_pry",         [sys.executable, f"{SCRIPTS_DIR}/fast_pry_today.py", "--build-cache"],         f"{DATA_DIR}/pry_premarket_cache.json"),
        ("s6_2to3",        [sys.executable, f"{SCRIPTS_DIR}/fast_2to3_today.py", "--build-cache"],        f"{DATA_DIR}/2to3_premarket_cache.json"),
    ]
    cache_status = {}
    for key, cmd, cpath in cache_builders:
        rc = subprocess.run(cmd, check=False, timeout=120).returncode
        if rc != 0 or not os.path.exists(cpath):
            if key == "s3_4to5":
                print(f"[WARN] optional R&D {key}_build_failed(rc={rc}), non-blocking", flush=True)
                cache_status[key] = {"ok": False, "optional_rd": True, "rc": rc}
            else:
                errors.append(f"{key}_build_failed(rc={rc})")
                cache_status[key] = {"ok": False}
            continue
        js = json.load(open(cpath, "r", encoding="utf-8"))
        c_dt = js.get("as_of_d1") or js.get("sig_date") or js.get("d3_date") or js.get("d1_date") or ""
        cands_arr = js.get("candidates") or []
        n_cands = len(cands_arr)
        ok = (c_dt >= latest_dt)
        if key == "s5_1to2" and js.get("used_ths_plate_fallback", False):
            ok = False
            errors.append("s5_1to2_used_ths_fallback_not_kpl")
        if key == "s2_3to4" and n_cands > 0:
            if any(("pos20_d0" not in x or "xq_cnt_2d" not in x) for x in cands_arr):
                ok = False
                errors.append("s2_3to4_missing_v40_fields")
        if not ok:
            if key == "s3_4to5":
                print(f"[WARN] optional R&D {key}_stale({c_dt}<{latest_dt}), non-blocking", flush=True)
            else:
                errors.append(f"{key}_stale({c_dt}<{latest_dt})")
        cache_status[key] = {"ok": ok, "signal_date": c_dt, "candidates": n_cands, "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(cpath)).strftime("%Y-%m-%d %H:%M:%S")}

    try:
        r_lq = subprocess.run([sys.executable, f"{SIM_DIR}/backtests_astock2/live_daily_question_builder.py", "--premarket"], check=False, timeout=90)
        if r_lq.returncode != 0:
            errors.append(f"live_daily_premarket_rc({r_lq.returncode})")
    except subprocess.TimeoutExpired:
        errors.append("live_daily_premarket_timeout")

    errors.extend(_verify_cross_script_zero_drift())

    # Step 5: 严格零延迟 SLA 门禁校验 (任何滞后立即吼叫报警，绝不静默降级)
    lhb_req_dt = prev_dt if (now.weekday() < 5 and 1500 <= hm < 1730 and latest_dt == today_s) else latest_dt
    for k in ("sh000002", "sz399107", "sh000300"):
        if idx_max.get(k, "") < latest_dt: errors.append(f"index_{k}_lag({idx_max.get(k)}<{latest_dt})")
    for sd in ("buy", "sell"):
        if lhb_max.get(sd, "") < lhb_req_dt: errors.append(f"lhb_{sd}_lag({lhb_max.get(sd)}<{lhb_req_dt})")
    if kpl_tape_max.get("kpl_merged_max", "") < latest_dt: errors.append(f"kpl_merged_lag({kpl_tape_max.get('kpl_merged_max')}<{latest_dt})")
    if kpl_tape_max.get("zt_micro_tape_max", "") < latest_dt: errors.append(f"zt_micro_tape_lag({kpl_tape_max.get('zt_micro_tape_max')}<{latest_dt})")

    c_pit = sqlite3.connect(f"file:{DATA_DIR}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    pit_max = (c_pit.execute("SELECT max(pub_datetime_cst) FROM notices").fetchone()[0] or "")[:19]
    c_pit.close()
    if pit_max[:10] < latest_dt: errors.append(f"cninfo_pit_lag({pit_max[:10]}<{latest_dt})")

    report = {
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "status": "GREEN_ZERO_LAG" if not errors else "CRITICAL_LAG_ALERT",
        "latest_trade_date": latest_dt,
        "sources": {"a_daily": latest_dt, "index_klines": idx_max, "lhb": lhb_max, **kpl_tape_max, "cninfo_pit_max": pit_max, "ir_qa_max": ir_max},
        "caches": cache_status,
        "errors": errors,
    }
    os.makedirs(f"{SIM_DIR}/signals/pending", exist_ok=True)
    json.dump(report, open(f"{DATA_DIR}/rd_data_health_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(report, open(f"{SIM_DIR}/signals/pending/rd_premarket_ready.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[RD_MASTER_SYNC] status={report['status']} | latest_dt={latest_dt} | elapsed={report['elapsed_sec']}s | errors={errors}", flush=True)
    urgent_p = f"{SIM_DIR}/signals/pending/URGENT_RD_DATA_ALERT.json"
    if errors:
        json.dump(report, open(urgent_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        sys.exit(2)
    elif os.path.exists(urgent_p):
        os.remove(urgent_p)

if __name__ == "__main__":
    main()
