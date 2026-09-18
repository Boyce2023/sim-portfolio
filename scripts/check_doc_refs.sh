#!/bin/bash
# 引用一致性检查: 改完 strategy_astock.md 必跑
#
# ⛔2026-09-18 建。起因: 24 小时内我在同一件事上栽了三次 ——
#   09-17 v13.0 重排章节号, DECISION_PROTOCOL 路由表整体失效;
#   09-18 v14.0 换成中文节号, 路由表再次整体失效;
#   同日修复时只改了第二层场景路由表, 漏掉第一层常驻15条(而它每次决策都在场)。
# ⛔昨天我为此在 DECISION_PROTOCOL 自我治理节写下过防范条款, 它没拦住我。
#   规则拦不住的事要靠能跑的东西。这就是那个能跑的东西。
set -u
cd "$(dirname "$0")/.." || exit 1
FAIL=0

echo "== strategy_astock.md 实际章节 =="
SECS=$(grep -o '^## 第[零一二三四五六七八九十]*节' strategy_astock.md | sed 's/^## //')
echo "$SECS" | sed 's/^/   /'

echo
echo "== 引用方里仍以 § 指向 strategy_astock 的活引用 =="
# ⛔首跑时 4 报 3 假: 全文查 § 会把"改版历史的叙述"、"描述废止的语境"、
#   以及 CLAUDE.md 自己的章节号(§11/§9/§6, 与 strategy_astock 无关)全部误报。
#   一个天天喊狼来了的门等于没有门, 所以判据收窄为:
#   只看同一行里既出现 strategy_astock 又出现 §编号, 且排除标注了废止/历史的行。
for f in DECISION_PROTOCOL.md CLAUDE.md; do
  HITS=$(grep -n '§[0-9]' "$f" 2>/dev/null \
         | grep -i 'strategy_astock' \
         | grep -v '已废\|废止\|已取消\|改版原因\|改版历史\|待重写\|原引用\|原注释' || true)
  if [ -n "$HITS" ]; then
    echo "   $f: 活引用未对齐"
    echo "$HITS" | cut -c1-110 | sed 's/^/      /'
    FAIL=1
  else
    echo "   $f: 无活引用残留"
  fi
done

echo
echo "== 判据段里残留的旧版本号(排除改版历史) =="
for f in DECISION_PROTOCOL.md CLAUDE.md; do
  HITS=$(grep -n 'v1[23]\.0' "$f" 2>/dev/null \
         | grep -v '改版\|作废\|已废\|历史\|整体失效\|改编号\|重排\|同步重写\|^\s*[0-9]*:\*v1\|随 \|重写：\|备份' || true)
  # ⛔2026-09-18: 原写 N=$(echo "$HITS" | grep -c . || echo 0), 管道失败时会拼出两行 0,
  #   导致 [ "$N" -gt 0 ] 报 "integer expression expected" —— 这道门自己带伤,
  #   而带伤的门比没有门更危险: 它会在真出问题那天悄悄退出。改用 printf 加 wc -l。
  N=$(printf '%s' "$HITS" | grep -c . 2>/dev/null); N=${N:-0}
  if [ "$N" -gt 0 ] 2>/dev/null; then
    echo "   $f: 判据段仍引用旧版本 $N 处"
    echo "$HITS" | cut -c1-110 | sed 's/^/      /'
    FAIL=1
  else
    echo "   $f: 判据段干净"
  fi
done

echo
echo "== 当前版本号一致性 =="
V=$(grep -m1 '^# Strategy v' strategy_astock.md | grep -o 'v[0-9]*\.[0-9]*')
echo "   strategy_astock.md 自称 $V"
for f in DECISION_PROTOCOL.md CLAUDE.md; do
  if grep -q "$V" "$f"; then echo "   $f 提到 $V: 是"; else echo "   $f 提到 $V: 否"; FAIL=1; fi
done

echo
[ "$FAIL" -eq 0 ] && echo "检查通过" || echo "有引用未对齐, 见上方"
exit $FAIL
