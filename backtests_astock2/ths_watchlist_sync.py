#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
ths_watchlist_sync.py
同花顺桌面端「置顶」自选股只读扫描与关注名单同步器
- 每小时自动只读解析同花顺本地云同步缓存中的「置顶」分组，把新置顶的 A 股自动并入 user_watchlist.json；
- 支持命令行手动增删改查，发现新票或盘中刷新时自动重出「今日题.html」并同步桌面。
"""
import os
import re
import sys
import glob
import json
import base64
import plistlib
import datetime
import argparse
import subprocess

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_5Y_DIR = os.path.join(CURR_DIR, "data_5y")
WATCHLIST_JSON = os.path.join(DATA_5Y_DIR, "user_watchlist.json")
THS_CLOUD_GLOB = os.path.expanduser(
    "~/Library/Containers/cn.com.10jqka.macstockPro/Data/Documents/cloud_store/blockstock_*/public/*.dat"
)
VALID_ASTOCK_RE = re.compile(r"^(?:00|30|60|68)\d{4}$")

DEFAULT_SEED_CODES = [
    "601929", "601595", "002419", "002148", "002187",
    "002205", "600715", "002425", "001201", "002242",
]


def read_ths_pinned_codes() -> list[str]:
    """只读扫描同花顺本地缓存中的『置顶』分组，按同花顺显示顺序返回6位A股代码列表"""
    for fp in sorted(glob.glob(THS_CLOUD_GLOB)):
        try:
            with open(fp, "rb") as f:
                pl = plistlib.load(f)
            for obj in pl.get("$objects", []):
                b = obj if isinstance(obj, bytes) else (obj.get("NS.data") if isinstance(obj, dict) else None)
                if not (isinstance(b, bytes) and b"|" in b):
                    continue
                i1 = b.find(b"\n")
                if i1 < 0 or i1 + 2 >= len(b):
                    continue
                ln1 = b[i1 + 1]
                g_b64 = b[i1 + 2: i1 + 2 + ln1]
                try:
                    g_name = base64.b64decode(g_b64).decode("gbk", errors="ignore")
                except Exception:
                    continue
                if g_name.strip() != "置顶":
                    continue
                s_tail = b[i1 + 2 + ln1:].decode("latin1", errors="ignore")
                m = re.search(r"([0-9A-Za-z]{6}(?:\|[0-9A-Za-z]{6})*)\|,([0-9]+(?:\|[0-9]+)*)\|", s_tail)
                if m:
                    raw_codes = m.group(1).split("|")
                    return [c for c in raw_codes if VALID_ASTOCK_RE.match(c)]
        except Exception:
            continue
    return []


def load_and_sync_watchlist() -> tuple[dict, list[str]]:
    """读取 user_watchlist.json 并把同花顺置顶中新出现的票并入关注列表（只增不误删）"""
    os.makedirs(DATA_5Y_DIR, exist_ok=True)
    now_s = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(WATCHLIST_JSON):
        try:
            state = json.load(open(WATCHLIST_JSON, "r", encoding="utf-8"))
        except Exception:
            state = {}
    else:
        state = {}

    codes = [c for c in state.get("codes", DEFAULT_SEED_CODES) if VALID_ASTOCK_RE.match(str(c))]
    if not codes:
        codes = list(DEFAULT_SEED_CODES)
    excluded = set(state.get("excluded_codes", []))
    added_meta = dict(state.get("added_meta", {}))

    ths_pinned = read_ths_pinned_codes()
    newly_added = []
    # 新置顶的票若不在当前关注名单且未被用户手工排除，按置顶顺序插入最前排醒目展示
    new_front = []
    for c in ths_pinned:
        if c not in codes and c not in excluded:
            new_front.append(c)
            newly_added.append(c)
            added_meta[c] = {"added_at": now_s, "source": "同花顺置顶自动同步"}

    if new_front:
        codes = new_front + codes

    new_state = {
        "updated_at": now_s,
        "last_ths_scan_at": now_s,
        "codes": codes,
        "ths_pinned_now": ths_pinned,
        "excluded_codes": sorted(excluded),
        "added_meta": added_meta,
    }
    if newly_added or (not os.path.exists(WATCHLIST_JSON)) or state.get("ths_pinned_now") != ths_pinned:
        tmp_p = WATCHLIST_JSON + ".tmp"
        with open(tmp_p, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_p, WATCHLIST_JSON)
    return new_state, newly_added


def main():
    ap = argparse.ArgumentParser(description="同花顺置顶每小时自动扫描与关注名单管理")
    ap.add_argument("--hourly", action="store_true", help="每小时定时扫描，有新票或盘中自动刷新今日题")
    ap.add_argument("--add", type=str, default="", help="手动添加股票代码，逗号分隔")
    ap.add_argument("--remove", type=str, default="", help="手动移除股票代码，逗号分隔")
    args = ap.parse_args()

    state, newly_added = load_and_sync_watchlist()
    changed = bool(newly_added)
    now = datetime.datetime.now()

    if args.add:
        for c in [x.strip()[:6] for x in args.add.split(",") if VALID_ASTOCK_RE.match(x.strip()[:6])]:
            if c not in state["codes"]:
                state["codes"].insert(0, c)
                changed = True
            if c in state["excluded_codes"]:
                state["excluded_codes"].remove(c)
                changed = True
    if args.remove:
        for c in [x.strip()[:6] for x in args.remove.split(",") if x.strip()]:
            if c in state["codes"]:
                state["codes"].remove(c)
                changed = True
            if c not in state["excluded_codes"]:
                state["excluded_codes"].append(c)
                changed = True
    if changed and (args.add or args.remove):
        state["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
        with open(WATCHLIST_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    in_mkt_hours = (now.weekday() < 5) and (9 <= now.hour <= 15)
    if changed or (args.hourly and in_mkt_hours):
        builder = os.path.join(CURR_DIR, "live_daily_question_builder.py")
        mode_flag = "--auction" if (now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 25))) else "--premarket"
        subprocess.run([sys.executable, builder, mode_flag], check=False, timeout=50)
    print(f"[ths-watchlist] codes={len(state['codes'])} ths_pinned={len(state['ths_pinned_now'])} newly_added={newly_added}")


if __name__ == "__main__":
    main()
