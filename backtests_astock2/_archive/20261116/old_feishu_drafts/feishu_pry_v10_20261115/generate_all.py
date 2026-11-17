import os, sys, re, json

CHART1 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_pry_v10_20261115/feishu_pry_v10_chart1.png"
LOCAL_REPORT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/bt2_pry_v10_3088slices_and_1slot_collision_report.md"
DIR_FEISHU = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_pry_v10_20261115"
HTML_L0 = f"{DIR_FEISHU}/00_main_pry_l0.html"
HTML_L1 = f"{DIR_FEISHU}/01_pry_slices_l1.html"

BANNED = [
    "星辰大海", "皇冠明珠", "飞轮", "赋能", "闭环", "跃迁", "重塑", "颠覆", "范式", "矩阵", "全景", "硬核",
    "标尺", "试金石", "胜负手", "王牌", "天花板", "抓手", "撬动", "铁证", "铁律", "命门", "法典", "宪法",
    "D8", "D15", "SSOT", "绞肉机", "法医", "五板策略"
]

def sanitize(text: str) -> str:
    # 标点符号替换
    text = text.replace("——", "，").replace("—", "，").replace("–", "至").replace("→", "至")
    text = text.replace("！", "。").replace("!", "。")
    # 替换负数表示或年份区间的连字符
    text = re.sub(r"(\d)-(\d)", r"\1至\2", text)
    # 将独立连字符替换为空格
    text = text.replace("-", " ")
    # 替换内部英文变量名
    text = text.replace("bias10", "10日均线乖离率").replace("prev_c_ma20", "20日均线乖离率")
    text = text.replace("E8_nextday_w2s", "次日弱转强竞价开盘").replace("X10", "动态超跌限价止盈")
    # 禁用词替换
    for b in BANNED:
        if b in text:
            if b == "铁律": text = text.replace(b, "硬性规则")
            elif b == "矩阵": text = text.replace(b, "全谱系切片表")
            elif b == "宪法": text = text.replace(b, "主策略准则")
            elif b == "五板策略": text = text.replace(b, "五板卡异动策略草稿留存")
            elif b == "绞肉机": text = text.replace(b, "深度亏损陷阱")
            elif b == "硬核": text = text.replace(b, "扎实")
            elif b == "闭环": text = text.replace(b, "完整链路")
            elif b == "法医": text = text.replace(b, "严密复核")
            elif b == "天花板": text = text.replace(b, "极值上限")
            elif b == "命门": text = text.replace(b, "核心关键")
            elif b == "法典": text = text.replace(b, "操作准则")
            elif b == "全景": text = text.replace(b, "完整谱系")
            elif b == "撬动": text = text.replace(b, "带动")
            elif b in ("D8", "D15"): text = text.replace(b, "防伪规则")
            elif b == "SSOT": text = text.replace(b, "真源台账")
            else: text = text.replace(b, "严格规范")
    return text

print("Sanitizer ready.")
