#!/usr/bin/env bash
# =============================================================================
# daily_run.sh — sim-portfolio 每日自动触发入口
# 由 launchd 在 UTC 00:00（北京时间 08:00）调用
# =============================================================================

# ---------- 路径常量 ----------
REPO_DIR="/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
SCRIPTS_DIR="${REPO_DIR}/scripts"
LOGS_DIR="${REPO_DIR}/logs"
CALENDAR_FILE="${REPO_DIR}/market_calendar.json"

# ---------- 设置 PATH（launchd 环境极简，必须手动补全） ----------
export PATH="/Users/huaichuaibeimeng/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
# uv 绝对路径备用
UV_BIN="/Users/huaichuaibeimeng/.local/bin/uv"
GIT_BIN="/usr/bin/git"
# ⛔2026-09-21: 09-18 16:59 Homebrew 把 python3 升到 3.14.7, 新版本没有 yfinance/openpyxl/pyarrow,
#   本脚本 12 处裸 python3 调用在 09-21 早上全部 ModuleNotFoundError, 包括美股灾难线检查
#   (判不出交易日, 未做安全判定)。改用 09-18 前这些脚本一直在用的 3.13, 并在下方断言依赖齐全。
PY="/opt/homebrew/opt/python@3.13/bin/python3.13"

# ---------- 日志初始化 ----------
mkdir -p "${LOGS_DIR}"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="${LOGS_DIR}/${TODAY}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

log_err() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "${LOG_FILE}" >&2
}

log "===== daily_run.sh 启动 ====="
# ⛔解释器依赖断言: 3.13 若被 brew cleanup 删掉或缺包, 必须当场大声报错, 不许让十几个步骤各自悄悄崩掉
if ! "${PY}" -c "import yfinance, pandas, openpyxl, pyarrow" >/dev/null 2>&1; then
    log_err "⛔⛔ 解释器 ${PY} 缺依赖或不存在, 下面所有用它的步骤都会失败。修: 换一个装齐 yfinance/pandas/openpyxl/pyarrow 的 python"
    PY_BROKEN=1
fi

# ---------- 工作目录 ----------
cd "${REPO_DIR}" || {
    log_err "无法 cd 到 ${REPO_DIR}，退出"
    exit 1
}

# ---------- 市场日历检查（检查今天 NYSE 是否休市） ----------
# 读取 market_calendar.json 判断今天是否应该运行
# 规则：周末或在 nyse_closed 列表中 → 跳过
check_trading_day() {
    local dow
    dow=$(date +%u)   # 1=Mon … 7=Sun
    if [ "${dow}" -ge 6 ]; then
        log "今天是周末（周${dow}），跳过交易流程"
        return 1
    fi

    if [ ! -f "${CALENDAR_FILE}" ]; then
        log "未找到 market_calendar.json，跳过节假日检查，继续运行"
        return 0
    fi

    # 用 python3 读 JSON（比 jq 更可靠，避免依赖缺失）
    local is_holiday
    is_holiday=$(python3 - <<PYEOF
import json, sys
with open("${CALENDAR_FILE}") as f:
    cal = json.load(f)
closed = cal.get("trading_days_by_market", {}).get("us_closed_dates", [])
print("yes" if "${TODAY}" in closed else "no")
PYEOF
)

    if [ "${is_holiday}" = "yes" ]; then
        log "今天 ${TODAY} 是 NYSE 节假日，跳过交易流程"
        return 1
    fi

    return 0
}

if ! check_trading_day; then
    log "===== daily_run.sh 结束（非交易日，无操作） ====="
    exit 0
fi

log "今天 ${TODAY} 是交易日，开始执行流程"

# ---------- 通用步骤执行器 ----------
# run_step <步骤名> <命令...>
# 失败时记录错误但不 exit，让后续步骤继续
STEP_FAILED=0
[ "${PY_BROKEN:-0}" -eq 1 ] && STEP_FAILED=1

run_step() {
    local step_name="$1"
    shift
    log ">>> 步骤：${step_name}"
    if "$@" >> "${LOG_FILE}" 2>&1; then
        log "    ✓ ${step_name} 成功"
    else
        local rc=$?
        log_err "    ✗ ${step_name} 失败（exit ${rc}）"
        STEP_FAILED=1
    fi
}

# ---------- Step 1: git pull ----------
# ---------- Step 0: 外部数据源探活(2026-08-27维护新增, 坏了当天知道不等用户发现) ----------
if [ -f "${SCRIPTS_DIR}/health_check.py" ]; then
    run_step "health_check.py（外部源探活）" \
        "${PY}" "${SCRIPTS_DIR}/health_check.py"
fi

# ---------- Step 0.5: 网络门(2026-09-30, #59 与 us 09-30 报告同根) ----------
# ⛔ 09-30 08:00 机器休眠断网下整轮照跑, 取价全失败却无报警, 美股灾难线检查与 QQQ 挂单都没执行。
#   两个行情源都不通 = 本轮所有决策都建立在旧价上, 宁可整轮不跑也不能假装跑过。
net_ok() {
    local a b
    a=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://qt.gtimg.cn/q=sh000001" 2>/dev/null)
    b=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=1d" 2>/dev/null)
    log "    网络门: 腾讯=${a} 雅虎=${b}"
    # 任一源有 HTTP 响应(含 429 限流)即网络通; 两个都是 000 才是断网
    [ -n "${a}" ] && [ "${a}" != "000" ] || { [ -n "${b}" ] && [ "${b}" != "000" ]; }
}
_net_try=0
until net_ok; do
    _net_try=$((_net_try+1))
    if [ "${_net_try}" -ge 6 ]; then
        log_err "⛔ 网络门: 30 分钟内两个行情源始终不通, 判定本轮无效, 跳过全部后续步骤(不取价/不执行止损与挂单)"
        bash "${HOME}/.claude/session-remote/fs-reply.sh" "⛔[daily_run] ${TODAY} 08:00 这轮无效: 30 分钟内腾讯与雅虎行情都连不上(疑似机器休眠断网), 已跳过取价、止损检查与挂单执行, 两个市场都需要人工补跑" >/dev/null 2>&1 || true
        exit 2
    fi
    log "    网络门: 第 ${_net_try} 次不通, 300 秒后重试"
    sleep 300
done

run_step "git pull" \
    "${GIT_BIN}" pull --ff-only

# ---------- Step 2: 获取价格 ----------
_px_before=$(stat -f %m "${REPO_DIR}/latest_prices.json" 2>/dev/null || echo 0)
run_step "fetch_prices.py" \
    "${UV_BIN}" run "${SCRIPTS_DIR}/fetch_prices.py"
_px_after=$(stat -f %m "${REPO_DIR}/latest_prices.json" 2>/dev/null || echo 0)
if [ "${_px_after}" -le "${_px_before}" ]; then
    log_err "⛔ 取价结果门: latest_prices.json 未更新, 判定本轮无效, 跳过后续步骤"
    bash "${HOME}/.claude/session-remote/fs-reply.sh" "⛔[daily_run] ${TODAY} 这轮无效: fetch_prices 跑完但 latest_prices.json 没有更新, 已跳过止损检查与挂单执行, 两个市场都需要人工补跑" >/dev/null 2>&1 || true
    exit 3
fi

# ---------- Step 2b: 把价格回写 portfolio_state.json ----------
# update_prices.py exit 1 = validation errors（记录但不阻止后续）
# ⛔decision_engine 自 2026-09-09 起才真有 get_price 兜底(portfolio_state.current_price)。此前这里注释宣称"有 fallback"而代码无, 限流那天 16 条假卖出信号躺进正式 decisions.json。注释里的兜底不是兜底。
# update_prices.py exit 0 = 成功
# 2026-09-29(main 审计): 原来不带 --market 走 auto, 08:00/09:12 判成 A股时段只更新 cn, 美股持仓价格停在 09-17。
#   本步显式只管 A股, 美股由下面 Step 2b-us 自己更新。
run_step "update_prices.py(A股)" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/update_prices.py" --market cn

# ---------- Step 2b-us: 美股价格回写 (2026-09-29 us 加) ----------
# ⛔上一步不带 --market 时按时段 auto 判断, 08:00 被判成A股时段只更新 cn,
#   美股 13 只里 11 只 current_price 停在 09-17 共 12 天(main 09-29 实读发现)。
#   凡从 portfolio_state 算的杠杆/NAV/仓位占比/门禁全部偏。美股单独显式刷一次, 与A股那行各管各的。
run_step "update_prices.py --market us" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/update_prices.py" --market us

# ---------- Step 2c: 持久化催化剂日历数据 ----------
log ">>> 步骤：catalyst_calendar"
if "${UV_BIN}" run --script "${SCRIPTS_DIR}/catalyst_calendar.py" \
       --portfolio --json > "${REPO_DIR}/catalyst_upcoming.json" 2>/dev/null; then
    log "    ✓ catalyst_calendar 成功"
else
    log "    ⚠ catalyst_calendar 失败（非阻断，继续）"
fi

# ---------- Step 2c2: A股财报预约披露日历刷新（写入 catalyst_calendar，供X2/L11/T18⑤消费） ----------
run_step "astock_catalyst_calendar.py" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/astock_catalyst_calendar.py"

# ---------- Step 2d: Track B 盘后日评（TB持仓天数+CB追踪） ----------
if [ -f "${SCRIPTS_DIR}/tb_review.py" ]; then
    log ">>> 步骤：tb_review.py（Track B 盘后日评）"
    if "${UV_BIN}" run --script "${SCRIPTS_DIR}/tb_review.py" >> "${LOG_FILE}" 2>&1; then
        log "    ✓ tb_review.py 成功"
    else
        log "    ⚠ tb_review.py 失败（非阻断，继续）"
    fi
fi

# ---------- Step 3 (pre): Truth Store 维护（after update_prices, before decision_engine） ----------
run_step "maintain_truth.py" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/maintain_truth.py"
# 2026-09-02 main: regime=unknown是取数失败不是市场状态(09-02早上09:00 launchd跑出unknown, 10:48手跑即bull/VIX16.3);
# 09:00日志实证0/16全源失败=整段网络不通(08:00 health_check也连败4天), 10分钟后重试, 最多3次, 不让unknown过夜污染Truth Store
for _retry in 1 2 3; do
    if python3 -c "import json,sys;d=json.load(open('${HOME}/.claude/nexus/truth/macro/regime.json'));sys.exit(0 if d.get('current_regime',{}).get('regime','unknown')!='unknown' else 1)" 2>/dev/null; then
        break
    fi
    log "    ⚠ regime=unknown(取数失败), 600秒后重试 maintain_truth (${_retry}/3)"
    sleep 600
    run_step "maintain_truth.py(重试${_retry})" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/maintain_truth.py"
done
# 2026-09-29(main 审计): 三次重试用尽仍 unknown 时原来静默往下走, 补飞书报警
if ! python3 -c "import json,sys;d=json.load(open('${HOME}/.claude/nexus/truth/macro/regime.json'));sys.exit(0 if d.get('current_regime',{}).get('regime','unknown')!='unknown' else 1)" 2>/dev/null; then
    log "    ⛔ regime 三次重试后仍为 unknown, 已发飞书报警"
    bash "${HOME}/.claude/session-remote/fs-reply.sh" "[astock] ⛔ daily_run: regime 三次重试后仍 unknown(VIX或利差取不到), 下游按无regime处理, 需人工查取数" >/dev/null 2>&1 || true
fi

# ---------- Step 3a: 消费跨session信号（按需互知:自动读pending+持仓交叉+标consumed） ----------
# 2026-06-18: 接入signal_consumer闭环"按需互知"——美股/A股session确认脚本已存在,缺的是自动化
if [ -f "${SCRIPTS_DIR}/signal_consumer.py" ]; then
    run_step "signal_consumer.py" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/signal_consumer.py" --consume
fi

# ---------- Step 3b: A股 Regime Detection（宏观环境5信号） ----------
if [ -f "${SCRIPTS_DIR}/astock_regime.py" ]; then
    run_step "astock_regime.py" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/astock_regime.py"
fi

# ---------- Step 3b2: 灾难线自动止损检测（现价 vs avg_cost×0.88，只告警不下单，T0铁律） ----------
# ⛔ 2026-08-24新增：三环集团+生益科技双双破灾难线全靠人肉盯盘才发现，此步骤补漏。
# 破线时exit code非零 → run_step标"✗失败"，在日志汇总里显眼标红，人不可能错过。
if [ -f "${SCRIPTS_DIR}/auto_stop_check.py" ]; then
    run_step "auto_stop_check.py（灾难线检测）" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/auto_stop_check.py"
fi

# ---------- Step 3b2.5: 价格库口径门 + 成交与裁决对账（2026-09-17 新增） ----------
# ⛔为什么补这两步: 两个脚本 09-17 建好并双向验证通过, 但零调用方 —— 建了门没接进路径。
#   price_db_gate: 形状类断言(行数/末日/空值)挡不住"某段只剩三分之一"。实证 09-08 全库 5,207 只,
#     09-09 起每日只剩 1,792 只, 而"末日=09-15"照样绿; 任何读近一周做回测的动作都在用三分之一市场。
#   trade_ledger_diff: 有成交无裁决记录 / 到期的待执行动作无对应成交, 两类差集都无人发现。
# ⛔两者都必须非零退出码, 让 run_step 标红 —— 只打印不影响退出码等于没有门。
if [ -f "${SCRIPTS_DIR}/price_db_gate.py" ]; then
    run_step "price_db_gate.py（价格库口径门）" \
        "${PY}" "${SCRIPTS_DIR}/price_db_gate.py"
fi

if [ -f "${SCRIPTS_DIR}/trade_ledger_diff.py" ]; then
    run_step "trade_ledger_diff.py（成交与裁决对账）" \
        "${PY}" "${SCRIPTS_DIR}/trade_ledger_diff.py"
fi

# ---------- Step 3b3: 财报反应筛（财报当日跌+之后继续跌=双负预警） ----------
# ⛔ 2026-08-25新增，缘起8/24复盘：我16只持仓里唯二"双负"的HUBB/HWM，正是浮亏最大的两只
#    (-12.0K/-7.3K)，而这个信号在我8/14建HUBB仓的一个月前就已存在——规则不存在所以没人看见。
#    口径(2026-08-24 Buwen定)：只用价格，不用卖方consensus超预期。"涨了就是超预期"。
#    只告警不下单(T0铁律)；双负标的发nexus信号，进thesis三问复核队列。
if [ -f "${SCRIPTS_DIR}/earnings_reaction_screen.py" ]; then
    run_step "earnings_reaction_screen.py（财报双负预警）" \
        "${PY}" "${SCRIPTS_DIR}/earnings_reaction_screen.py" --signal
fi

# ---------- Step 3b3.5: 美股灾难线检查 (2026-09-08 接入) ----------
# ⛔为什么装在这里: 灾难线-12% 是 08-27 纠偏后美股唯一保留的价格规则
# (memory/feedback_us_value_only.md:32; 项目CLAUDE.md:123 有完整口径),
# 但此前只有 auto_stop_check.py 且它写死读 a_share, 美股16只一直靠人手算。
# ⛔规则写在纸上、机制不存在——与 .dxy_count.json 同族。今天补上。
# 退出码: 0=全查完无击穿 / 1=有击穿 / 2=无法判断 / 3=检查不完整(有漏检)
# ⛔漏检不返回0, 否则本脚本会把"没检查"当成"跑成功了"。
if [ -f "${SCRIPTS_DIR}/us_disaster_check.py" ]; then
    "${PY}" "${SCRIPTS_DIR}/us_disaster_check.py" --notify --enqueue   # 09-29: 击穿自动挂单, Step 4b2 执行
    DC_RC=$?
    case $DC_RC in
        0) echo "  [灾难线] ✅ 美股全部检查完毕, 无击穿" ;;
        1) echo "  [灾难线] 🚨 有持仓击穿-12%线 — 当日减半+thesis三问, 连续2日线下才清" ;;
        2) echo "  [灾难线] ⛔ 无法判断(state结构或取价失败) — 这不是'安全', 需人工检查" ;;
        3) echo "  [灾难线] ⛔ 检查不完整(有漏检) — 不构成全仓安全结论, 需人工确认" ;;
        *) echo "  [灾难线] ⛔ 未知退出码 $DC_RC" ;;
    esac
else
    echo "  [灾难线] ⛔ us_disaster_check.py 不存在 — 美股灾难线本轮未检查"
fi

# ---------- Step 3b3.6: 美股 thesis 复核提示 (2026-09-08 接入) ----------
# ⛔为什么装: 09-08诊断——已实现 -$64,724 而浮盈 +$67,951, 赚的全在没卖的仓位上。
# T18回测: 判断型卖出20日卖对率87% / 机械型36%, 而自动化全在机械型(灾难线/美元/金对簇)。
# ⛔本步不是新增扳机, 是把 thesis 三问从"靠自觉"变成"每天必然摆到眼前"。只提示不下单。
# 退出码: 0=全覆盖 / 2=配置缺失或损坏 / 3=有持仓没定义失效条件(新建仓忘了加)
if [ -f "${SCRIPTS_DIR}/us_thesis_review.py" ]; then
    "${PY}" "${SCRIPTS_DIR}/us_thesis_review.py"
    TR_RC=$?
    case $TR_RC in
        0) echo "  [thesis复核] ✅ 16只全部有失效条件, 已摆出今日该看的" ;;
        2) echo "  [thesis复核] ⛔ 配置缺失或损坏 — 无法复核, 这不是'没问题'" ;;
        3) echo "  [thesis复核] ⛔ 有持仓未定义失效条件 — 那几只的thesis无人看管" ;;
        *) echo "  [thesis复核] ⛔ 未知退出码 $TR_RC" ;;
    esac
else
    echo "  [thesis复核] ⛔ us_thesis_review.py 不存在 — 本轮未做thesis复核"
fi

# ---------- Step 3b3.7: 美股仓位体检 (2026-09-09 接入) ----------
# ⛔为什么装: 09-09 从792个git快照重建完整交易史, 发现峰值仓位落在 8%到15% 的38只
# 合计亏 $170,131 / 胜率21.1% / Kelly f*=-54.4%, 留一法去掉最亏3只仍亏 $111,311。
# 单笔的门(T19回本区间/T20仓位死区)已进 execute_trade.py, 但门只拦下一笔,
# 拦不住"已经躺在死区里的存量仓"。本步每天把存量摆出来。
# ⛔只报不动手: 调仓是judgment。退出码 0=无死区 / 1=有死区仓 / 2=数据不足无法判断
if [ -f "${SCRIPTS_DIR}/us_sizing_check.py" ]; then
    "${PY}" "${SCRIPTS_DIR}/us_sizing_check.py"
    SZ_RC=$?
    case $SZ_RC in
        0) echo "  [仓位体检] ✅ 无仓位落在 8%到15% 死区" ;;
        1) echo "  [仓位体检] ⛔ 有仓位落在死区 — 见上表, 需逐只判断是减到probe还是加到信念档" ;;
        2) echo "  [仓位体检] ⛔ 数据不足无法判断 — 这不是'没问题'" ;;
        *) echo "  [仓位体检] ⛔ 未知退出码 $SZ_RC" ;;
    esac
else
    echo "  [仓位体检] ⛔ us_sizing_check.py 不存在 — 本轮未做仓位体检"
fi

# ---------- Step 3b3.8: 美股价格库每日增量 (2026-09-09 接入) ----------
# ⛔为什么装: main 清点全系统数据时评 us_price_db 为维护最规范的数据集, 但"目前没有任何程序读它"。
# 不接进日常就是三个月后的另一个 kline_cache。本步让它每天收盘后自动追一天并重合并 all_daily。
# 退出码 0=干净 / 1=有失败ticker(见manifest.last_failed) / 3=整批失败熔断
if [ -f "${SCRIPTS_DIR}/us_price_db_pull.py" ]; then
    "${PY}" "${SCRIPTS_DIR}/us_price_db_pull.py" --incremental --merge > /tmp/us_price_db_daily.log 2>&1
    PDB_RC=$?
    # ⛔2026-09-16: 增量只更新 prices/ 不动 benchmarks/, 导致基准停在 09-08 而个股到 09-15。
    #   基准是一切对照与超额计算的分母, 落后会让"超额"静默失真, 当天我还拿它当交易日历数错了回看天数。
    "${PY}" "${SCRIPTS_DIR}/us_price_db_benchmarks.py" >> /tmp/us_price_db_daily.log 2>&1
    BM_RC=$?
    [ $BM_RC -ne 0 ] && echo "  [价格库] ⛔ 基准刷新失败(码 $BM_RC), 基准可能落后, 见 /tmp/us_price_db_daily.log"
    # ⛔2026-09-16: sectors/commodities/macro 三个子库从 09-09 建库起就没接过任何增量,
    #   体检时 sectors 停在 09-08、commodities 与 macro 停在 09-09, 落后五到六个交易日而无人知晓 ——
    #   因为从来没有一处会为此报错。板块对照与宏观读数都要用它们。退出码 4 = 新鲜度断言不过(按 freq 分档判)。
    "${PY}" "${SCRIPTS_DIR}/us_price_db_refresh_aux.py" >> /tmp/us_price_db_daily.log 2>&1
    AUX_RC=$?
    case $AUX_RC in
        0) ;;
        1) echo "  [价格库] ⛔ 辅助子库有序列失败, 见 /tmp/us_price_db_daily.log" ;;
        2) echo "  [价格库] ⛔⛔ 辅助子库整批失败熔断 — 数据源或凭据故障" ;;
        4) echo "  [价格库] ⛔ 辅助子库有序列超出新鲜度容忍, 见 /tmp/us_price_db_daily.log" ;;
        *) echo "  [价格库] ⛔ 辅助子库未知退出码 $AUX_RC" ;;
    esac
    # ⛔2026-09-17: 台账反向核对。所有治理机制管的都是**已经进了台账的条目**——字段校验、status
    #   合法性、新鲜度、needs_buwen 清账, 全都以"这条记录存在"为前提。一件事从未被记录时,
    #   所有校验都通过, 因为它根本不在名单上。实证: 09-11 两笔持仓被机械止损误清(合计 -27,273),
    #   六天里没有任何机制看见过它, 直到拿成交流水做反向核对才暴露。
    #   已双向测: 抽掉补记行报缺口(码1), 补记后放行(码0), 不是一道永远报错的门。
    "${PY}" "${SCRIPTS_DIR}/ledger_gap_check.py" --days 7 > /tmp/us_ledger_gap.log 2>&1
    GAP_RC=$?
    [ $GAP_RC -eq 1 ] && { echo "  [台账] ⛔⛔ 有成交未进台账, 见 /tmp/us_ledger_gap.log"; grep -A3 '差集非空' /tmp/us_ledger_gap.log | head -6; }
    [ $GAP_RC -gt 1 ] && echo "  [台账] ⛔ 反向核对异常退出码 $GAP_RC"

    case $PDB_RC in
        0) echo "  [价格库] ✅ 增量完成 $(grep -o '新增[0-9]*行' /tmp/us_price_db_daily.log | tail -1) | 基准 $([ $BM_RC -eq 0 ] && echo 已刷 || echo ⛔未刷)" ;;
        1) echo "  [价格库] ⛔ 有ticker失败, 见 manifest.last_failed" ;;
        3) echo "  [价格库] ⛔ 整批失败熔断 — 数据源或网络故障, 库停在昨天" ;;
        4) echo "  [价格库] ⛔⛔ 末日覆盖不足或有空收盘行 — 库被半截bar污染, 回测取价前必须先修(见日志)" ;;
        *) echo "  [价格库] ⛔ 未知退出码 $PDB_RC" ;;
    esac
else
    echo "  [价格库] ⛔ us_price_db_pull.py 不存在 — 库未更新"
fi

# ---------- Step 3b4: 美股盘后摘要自动推送(2026-08-27自动化普查落地) ----------
# 治"咋样了/持仓怎么样"30+次手动询问: 每天自动把NAV/最强最弱/T18门/宏观哨兵压成一条telegram。
if [ -f "${SCRIPTS_DIR}/us_eod_digest.py" ]; then
    run_step "us_eod_digest.py（美股盘后摘要→telegram）" \
        "${PY}" "${SCRIPTS_DIR}/us_eod_digest.py"
fi

# ---------- Step 3c: 退出信号检测（龙头崩+暴力拉升+催化剂临近） ----------
# 必须在 decision_engine 之前运行，使 decision_engine 能读到 nexus 退出信号
if [ -f "${SCRIPTS_DIR}/exit_signal_detector.py" ]; then
    run_step "exit_signal_detector.py" \
        "${UV_BIN}" run --script "${SCRIPTS_DIR}/exit_signal_detector.py"
fi

# ---------- Step 3: 更新持仓 ----------
# trading_engine.py 可能还不存在，条件执行
if [ -f "${SCRIPTS_DIR}/trading_engine.py" ]; then
    run_step "trading_engine.py" \
        "${UV_BIN}" run "${SCRIPTS_DIR}/trading_engine.py"
else
    log ">>> 步骤：trading_engine.py（文件不存在，跳过）"
fi

# ---------- Step 4: 生成决策（读取 exit_signal_detector 产生的 nexus 信号） ----------
if [ -f "${SCRIPTS_DIR}/decision_engine.py" ]; then
    run_step "decision_engine.py" \
        "${UV_BIN}" run "${SCRIPTS_DIR}/decision_engine.py"
else
    log ">>> 步骤：decision_engine.py（文件不存在，跳过）"
fi

# ---------- Step 4b: 自动执行止损（critical sell signals only） ----------
# 读 decisions.json，如有 priority=critical 的卖出信号，自动执行
if [ -f "${REPO_DIR}/decisions.json" ]; then
    log ">>> 步骤：auto-execute critical sells"
    python3 - <<'PYEOF'
import json, subprocess, sys

decisions_path = "decisions.json"
try:
    with open(decisions_path) as f:
        decisions = json.load(f)
except Exception:
    sys.exit(0)

sells = [s for s in decisions.get("sell_signals", []) if s.get("priority") == "critical"]
if not sells:
    print("无 critical 卖出信号")
    sys.exit(0)

import re, datetime, os
def _is_cn(s):
    # ⛔2026-09-15 (us 持笔, astock 测定): 信号原先不带 market 字段, 默认 "us", A股代码被发到 --account us,
    #   下单失败才没清仓(纯碰巧)。现在: 代码形态是A股(6位数字, 可带 sh/sz/bj 前缀或 .sh/.sz/.bj/.ss 后缀, 不分大小写)
    #   就一律按A股处理, 不看 market 字段(写错 market 是生成端 bug, 宁可不下单); 形态不像A股时才看 market。
    t = str(s.get("ticker", "")).strip()
    if re.fullmatch(r"(?i)(sh|sz|bj)?\d{6}(\.(sh|sz|bj|ss))?", t):
        return True
    return str(s.get("market") or "").lower() in ("cn", "a_share", "astock")

for s in sells:
    ticker = s["ticker"]
    if _is_cn(s):
        # A股机械退出归 astock 的 T18 流程(减半要按主beta或thesis写理由, 是判断动作), 通用脚本只记录不下单, 并唤醒 astock。
        print(f"[A股信号仅记录不下单] {ticker} reason={s.get('reason')} → 交 astock T18 复核")
        try:
            with open(os.path.expanduser("~/.claude/session-inbox/astock.jsonl"), "a") as _f:
                _f.write(json.dumps({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                                     "from": "daily_run-step4b", "kind": "task",
                                     "instruction": f"A股critical信号 {ticker} {s.get('reason')}, 按T18复核"},
                                    ensure_ascii=False) + "\n")
        except Exception as _e:
            print(f"  ⛔ 唤醒 astock 失败({type(_e).__name__}), 请 astock 自读 decisions.json")
        continue
    market = "us"
    account = "us"
    reason = s.get("reason", "auto stop-loss")
    cmd = [
        "/Users/huaichuaibeimeng/.local/bin/uv", "run", "--script",
        "scripts/execute_trade.py", "sell",
        "--account", account, "--ticker", ticker, "--all",
        "--reason", f"AUTO-STOPLOSS: {reason}"
    ]
    print(f"执行止损: {ticker} ({account})")
    subprocess.run(cmd, check=False)
PYEOF
    log "    ✓ auto-execute 检查完成"
fi

# ---------- Step 4b2: 自动执行 pending_orders（portfolio_state.json中的待处理订单） ----------
# trading_engine.py 会将session决策写入 pending_orders，但不执行。此步骤闭环。
log ">>> 步骤：auto-execute pending_orders"
python3 - <<'PYEOF'
import json, subprocess, sys
from pathlib import Path

state_path = Path("portfolio_state.json")
try:
    with open(state_path) as f:
        state = json.load(f)
except Exception as e:
    print(f"读取 portfolio_state.json 失败: {e}")
    sys.exit(0)

pending = state.get("pending_orders", [])
if not pending:
    print("无 pending_orders")
    sys.exit(0)

uv = "/Users/huaichuaibeimeng/.local/bin/uv"
executed = []

for order in pending:
    ticker = order.get("ticker", "")
    action = order.get("action", "").lower()  # "buy" or "sell"
    shares = order.get("shares")
    reason = order.get("reason", "auto-execute pending order")
    account_raw = order.get("account", "a_share")

    # normalize account name
    if account_raw in ("a_share", "cn", "astock"):
        account = "cn"
    else:
        account = "us"

    if action not in ("buy", "sell"):
        print(f"跳过未知操作: {ticker} {action}")
        continue

    cmd = [uv, "run", "--script", "scripts/execute_trade.py", action,
           "--account", account, "--ticker", ticker]

    if action == "buy" and shares:
        cmd += ["--shares", str(shares)]
    elif action == "sell":
        if shares:
            cmd += ["--shares", str(shares)]
        else:
            cmd += ["--all"]

    cmd += ["--reason", f"AUTO-PENDING: {reason}"]

    print(f"执行 pending_order: {action} {ticker} {shares or 'ALL'}股 ({account})")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"  ✓ {ticker} 成功")
        executed.append(ticker)
    else:
        print(f"  ✗ {ticker} 失败: {result.stderr[-200:] if result.stderr else 'unknown'}")

# 清除已执行的 pending_orders（通过 portfolio_io 确保同步链路完整）
if executed:
    with open(state_path) as f:
        state = json.load(f)
    remaining = [o for o in state.get("pending_orders", []) if o.get("ticker") not in executed]
    state["pending_orders"] = remaining
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from portfolio_io import save_portfolio
    save_portfolio(state, reason="daily auto: clear pending_orders", auto_sync=False)
    print(f"已清除 {len(executed)} 条 pending_orders，剩余 {len(remaining)} 条")

PYEOF
log "    ✓ pending_orders 检查完成"

# ---------- Step 4c: 同步 nexus-package dashboard ----------
run_step "sync_nexus.py" \
    "${UV_BIN}" run --script "${SCRIPTS_DIR}/sync_nexus.py"

# ---------- Step 5: git commit & push ----------
# 只在有文件变化时提交
log ">>> 步骤：git commit & push"
if "${GIT_BIN}" diff --quiet && "${GIT_BIN}" diff --cached --quiet; then
    log "    无文件变化，跳过 commit"
else
    COMMIT_MSG="daily: ${TODAY} auto-update"
    if "${GIT_BIN}" add -A >> "${LOG_FILE}" 2>&1 \
       && "${GIT_BIN}" commit -m "${COMMIT_MSG}" >> "${LOG_FILE}" 2>&1 \
       && "${GIT_BIN}" push >> "${LOG_FILE}" 2>&1; then
        log "    ✓ git commit & push 成功：${COMMIT_MSG}"
    else
        log_err "    ✗ git commit & push 失败（exit $?）"
        STEP_FAILED=1
    fi
fi

# ---------- 汇总 ----------
if [ "${STEP_FAILED}" -eq 1 ]; then
    log "===== daily_run.sh 结束（有步骤失败，请检查日志 ${LOG_FILE}） ====="
else
    log "===== daily_run.sh 结束（全部成功） ====="
fi

# ⛔2026-09-17: 原来这里无条件 `exit 0`, STEP_FAILED 只决定日志写哪一句话。
#   后果是脚本内部每一道门(灾难线检查、价格库三道、台账反向核对等)的非零退出码
#   全部在这一行被抹平, launchd 永远看到成功, 外部没有任何信号。
#   判据(来自 main 09-17): 一道门写完后必须回答"它失效时, 谁会在多久内知道"。
#   在此之前这些门的答案是"没有人, 除非有人主动翻日志"——那它们就还只是记录, 不是门。
#   ⛔已确认安全: com.claude.sim-portfolio.plist 无 KeepAlive(只有 StartCalendarInterval 8:00),
#     非零退出不会触发无限重启; launchctl 里 usage-bot 与 astock-refresh 长期带退出码 1 运行无异常。
exit "${STEP_FAILED}"
