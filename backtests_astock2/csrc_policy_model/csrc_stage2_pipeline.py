#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stage-2 Automated Pipeline:
1. Waits cleanly until Wave 1 (54 Carbon shards) & Wave 2 (16 Carbon shards) finish.
2. Compiles full corpus & runs 144-factor backtest + 6 left-right perturbation grids.
3. Runs Wave 3 (12 Carbon Audit & Synthesis agents concurrently).
4. Applies any release_slot audit fixes from W3_01/W3_02 to shards and reruns backtest if needed.
5. Generates 4 high-DPI PNG charts, 4 Feishu HTML docs, and clean Markdown archive.
"""
import glob, json, os, subprocess, time

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
SHARD_DIR = os.path.join(BASE_DIR, "shards")
AUDIT_DIR = os.path.join(BASE_DIR, "audit")
LOG_F = os.path.join(BASE_DIR, "stage2_pipeline.log")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_F, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def runners_alive():
    r = subprocess.run(["pgrep", "-f", "csrc_wave[12]_runner.py"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def apply_audit_fixes():
    fixes = {}
    for wid in ("W3_01", "W3_02"):
        p = os.path.join(AUDIT_DIR, f"{wid}.json")
        if os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                for fx in d.get("fixes") or []:
                    if isinstance(fx, dict) and fx.get("event_date") and (fx.get("new_release_slot") or fx.get("release_slot")):
                        ns = str(fx.get("new_release_slot") or fx.get("release_slot")).upper().strip()
                        if ns in ("BMO", "INTRADAY", "AMC", "WEEKEND_HOLIDAY"):
                            fixes[str(fx["event_date"])[:10]] = ns
            except Exception as e:
                log(f"WARN reading {wid}: {e}")
    if not fixes:
        return 0
    changed = 0
    for sp in glob.glob(os.path.join(SHARD_DIR, "*.json")):
        try:
            sd = json.load(open(sp, encoding="utf-8"))
            mod = False
            for ev in sd.get("events", []):
                dt = str(ev.get("event_date", ""))[:10]
                if dt in fixes and ev.get("release_time_slot") != fixes[dt]:
                    ev["release_time_slot"] = fixes[dt]
                    mod = True
                    changed += 1
            if mod:
                json.dump(sd, open(sp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass
    return changed


def main():
    log("Waiting for Wave 1 (54 shards) & Wave 2 (16 shards) runners to finish...")
    while runners_alive():
        n_sh = len(glob.glob(os.path.join(SHARD_DIR, "*.json")))
        log(f"  still running... shards on disk = {n_sh}/70")
        time.sleep(15)

    n_sh = len(glob.glob(os.path.join(SHARD_DIR, "*.json")))
    log(f"Wave 1 & Wave 2 finished! Total shards on disk: {n_sh}/70. Running Pass-1 Backtest...")
    subprocess.run(["python3", "/tmp/csrc_run_all_backtests.py"], check=True)

    log("Launching Wave 3 (12 Carbon Audit & Synthesis Agents)...")
    subprocess.run(["python3", "/tmp/csrc_wave3_audit.py"], check=True)

    chg = apply_audit_fixes()
    if chg > 0:
        log(f"Applied {chg} timestamp/slot fixes from Wave 3 audit! Re-running Pass-2 Backtest...")
        subprocess.run(["python3", "/tmp/csrc_run_all_backtests.py"], check=True)
    else:
        log("Zero timestamp lookahead defects found by Wave 3 audit.")

    log("Building 4 High-DPI Charts + 4 Feishu HTML Docs + Markdown Archive...")
    subprocess.run(["python3", "/tmp/csrc_build_charts.py"], check=True)
    subprocess.run(["python3", "/tmp/csrc_gen_html_part1.py"], check=True)
    subprocess.run(["python3", "/tmp/csrc_gen_html_part2.py"], check=True)
    subprocess.run(["python3", "/tmp/csrc_gen_md_archive.py"], check=True)
    log("ALL STAGE-2 PIPELINE STEPS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
