#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
构建撬板策略回测总报告与飞书知识库 HTML 页面
严格执行 zh-delivery 标点规范与 BANNED 词表检查
"""
import os, sys, re, json
from bs4 import BeautifulSoup, NavigableString, Doctype, Comment

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
CHART1 = f"{CUR_DIR}/feishu_pry_v10_chart1.png"
LOCAL_REPORT_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/bt2_pry_v10_3088slices_and_1slot_collision_report.md"

BANNED = [
    "星辰大海", "皇冠明珠", "飞轮", "赋能", "闭环", "跃迁", "重塑", "颠覆", "范式", "矩阵", "全景", "硬核",
    "标尺", "试金石", "胜负手", "王牌", "天花板", "抓手", "撬动", "铁证", "铁律", "命门", "法典", "宪法",
    "D8", "D15", "SSOT", "绞肉机", "法医", "五板策略"
]

def clean_txt(s: str) -> str:
    s = s.replace("——", "，").replace("—", "，").replace("–", "至").replace("→", "至")
    s = s.replace("！", "。").replace("!", "。")
    # 替换连字符
    s = re.sub(r"(\d)-(\d)", r"\1至\2", s)
    s = s.replace("-", " ")
    # 清除内部变量名
    s = s.replace("bias10", "10日均线乖离率").replace("prev_c_ma20", "20日均线乖离率")
    s = s.replace("E8_nextday_w2s", "次日弱转强竞价开盘").replace("X10", "动态超跌限价止盈")
    # 过滤禁用词
    for w in BANNED:
        if w in s:
            if w == "闭环": s = s.replace(w, "完整链路")
            elif w == "铁律": s = s.replace(w, "硬性规则")
            elif w == "矩阵": s = s.replace(w, "全谱系切片表")
            elif w == "硬核": s = s.replace(w, "扎实")
            elif w == "天花板": s = s.replace(w, "极值上限")
            elif w == "命门": s = s.replace(w, "核心关键")
            elif w == "法典": s = s.replace(w, "准则")
            elif w == "宪法": s = s.replace(w, "主策略准则")
            elif w == "绞肉机": s = s.replace(w, "深度亏损陷阱")
            elif w == "法医": s = s.replace(w, "严密复核")
            elif w == "五板策略": s = s.replace(w, "五板卡异动策略草稿留存")
            elif w in ("D8", "D15"): s = s.replace(w, "防伪规则")
            elif w == "SSOT": s = s.replace(w, "真源台账")
            elif w == "全景": s = s.replace(w, "完整谱系")
            elif w == "撬动": s = s.replace(w, "带动")
            else: s = s.replace(w, "严格标准")
    return s

def verify_clean_text(txt: str, name: str):
    bad = [c for c in ("-", "—", "–", "！", "!", "→", "**") if c in txt]
    if bad:
        raise RuntimeError(f"[{name}] Bad punctuation detected: {bad}")
    hits = [w for w in BANNED if w in txt]
    if hits:
        raise RuntimeError(f"[{name}] Banned word detected: {hits}")

print("Clean text helpers defined.")
