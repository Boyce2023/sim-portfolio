"""RD027 Wave 3 final report loader, V19.1/zh-delivery validator, and MD/HTML renderer."""
import html as htmllib
import json
import re
from pathlib import Path

ROOT = Path("/Users/huaichuaibeimeng/claude-projects")
OUT_BASE = ROOT / "output/china_policy_macro_rd027_20261125"

BANNED_WORDS = [
    "星辰大海", "皇冠明珠", "飞轮", "底座", "赋能", "闭环", "引擎", "跃迁",
    "重塑", "颠覆", "范式", "生态", "矩阵", "全景", "硬核", "标尺", "试金石",
    "胜负手", "王牌", "钩子", "年金", "天花板", "破局", "抓手", "撬动", "罕见",
    "极其", "绝不", "完美", "铁证", "铁律", "暗礁", "命门", "底牌", "法典",
    "死限", "拆穿", "十战十胜", "干干净净", "圣经", "贵族", "宪法", "绞肉机",
    "法医", "零未来函数", "D8", "D15", "SSOT",
]
LOAN11 = [
    "ablation", "daemon", "metadata", "telemetry", "guardrail",
    "handle", "endpoint", "idempotent", "Calmar", "PIT", "OOS",
]
BAD_PUNCT_RE = re.compile(r".{0,6}(?:-(?!\d)|—|–|！|!|→|\*\*).{0,6}")


def load_all_rd027_data() -> dict:
    """Load all verified Wave 1, Wave 2A, Wave 2B, and Wave 3 Critic JSONs."""
    files = {
        "p1": OUT_BASE / "data_pillars/pillar1_4_audit.json",
        "p2": OUT_BASE / "data_pillars/pillar2_top_meetings_audit.json",
        "p3": OUT_BASE / "data_pillars/pillar3_sector_traffic_lights_audit.json",
        "p5": OUT_BASE / "data_pillars/pillar5_25_inflections_casebook.json",
        "w2": OUT_BASE / "wave2_factors/wave2a_1000factor_audit.json",
        "t1": OUT_BASE / "wave2_practical/tool1_waterpool_regime_audit.json",
        "t2": OUT_BASE / "wave2_practical/tool2_sector_traffic_light_audit.json",
        "t3": OUT_BASE / "wave2_practical/tool3_polymarket_v2_audit.json",
        "lb": OUT_BASE / "wave2_practical/live_polymarket_board_v2_20261125.json",
        "c": OUT_BASE / "wave3_critic/rd027_critic_audit.json",
    }
    return {k: json.loads(p.read_text(encoding="utf-8")) for k, p in files.items()}


def validate_blocks(blocks: list[dict]) -> None:
    """Enforce V19.1, zh-delivery, cell<=40, and 11-loanword rules locally."""
    body_texts = []
    first_tbl_idx = next((i for i, b in enumerate(blocks) if b["t"] == "table"), len(blocks))
    if first_tbl_idx < 6:
        raise ValueError(f"Only {first_tbl_idx} blocks before first table (<6)")
    for b in blocks:
        t = b["t"]
        if t == "table":
            for r_idx, row in enumerate([b["headers"]] + b["rows"]):
                if len(row) != len(b["headers"]):
                    raise ValueError(f"Column mismatch at row {r_idx}: {row}")
                for c in row:
                    s = str(c)
                    if len(s) > 40:
                        raise ValueError(f"Cell >40 chars ({len(s)}): {s}")
                    body_texts.append(s)
        elif t == "ul":
            for it in b["items"]:
                body_texts.append(it)
        elif t != "h1":
            body_texts.append(b["text"])

    joined = "\n".join(body_texts)
    banned_hits = [w for w in BANNED_WORDS if w in joined]
    if banned_hits:
        raise ValueError(f"Banned words in body: {banned_hits}")
    bad_p = BAD_PUNCT_RE.findall(joined)
    if bad_p:
        raise ValueError(f"Bad punctuation found: {bad_p[:5]}")
    for w in LOAN11:
        hits = re.findall(rf"\b{w}\b(?!（)", joined)
        if hits:
            raise ValueError(f"Loanword '{w}' used without Chinese gloss: {hits}")
    if len(joined) < 2500:
        raise ValueError(f"Body visible chars too short: {len(joined)}")


def render_markdown(blocks: list[dict]) -> str:
    """Render validated blocks into clean GitHub Markdown."""
    out = []
    for b in blocks:
        t = b["t"]
        if t == "h1":
            out.append(f"# {b['text']}\n")
        elif t == "h2":
            out.append(f"\n## {b['text']}\n")
        elif t == "h3":
            out.append(f"\n### {b['text']}\n")
        elif t == "mark_p":
            out.append(f"\n`{b['text']}`\n")
        elif t == "p":
            out.append(f"{b['text']}\n")
        elif t == "ul":
            for it in b["items"]:
                out.append(f"* {it}")
            out.append("")
        elif t == "table":
            out.append("")
            out.append("| " + " | ".join(str(x) for x in b["headers"]) + " |")
            out.append("| " + " | ".join(["---"] * len(b["headers"])) + " |")
            for row in b["rows"]:
                out.append("| " + " | ".join(str(x) for x in row) + " |")
            out.append("")
    return "\n".join(out).strip() + "\n"


def render_html(blocks: list[dict]) -> str:
    """Render validated blocks into clean V19.1 Feishu HTML."""
    parts = ["<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'></head><body>"]
    for b in blocks:
        t = b["t"]
        esc = lambda s: htmllib.escape(str(s))
        if t == "h1":
            parts.append(f"<h1>{esc(b['text'])}</h1>")
        elif t == "h2":
            parts.append(f"<h2>{esc(b['text'])}</h2>")
        elif t == "h3":
            parts.append(f"<h3>{esc(b['text'])}</h3>")
        elif t == "mark_p":
            parts.append(f"<p><mark>{esc(b['text'])}</mark></p>")
        elif t == "p":
            parts.append(f"<p>{esc(b['text'])}</p>")
        elif t == "ul":
            lis = "".join(f"<li>{esc(it)}</li>" for it in b["items"])
            parts.append(f"<ul>{lis}</ul>")
        elif t == "table":
            ths = "".join(f"<th>{esc(h)}</th>" for h in b["headers"])
            trs = "".join(
                "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>"
                for r in b["rows"]
            )
            parts.append(f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>")
    parts.append("</body></html>")
    return "\n".join(parts)
