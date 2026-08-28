#!/bin/bash
# 后台任务标准件 (2026-08-27维护建立, 依据feedback_progress_reporting+case_background_task_blind_spot)
# 用法: source bg_task_lib.sh 后使用以下函数
#
# bg_launch <name> <logfile> <cmd...>   起后台任务+写pid文件
# bg_health <name> <output_file> <max_stale_min>  验活: 进程在+产出新鲜,否则退出码非0并打印诊断
#
# ⛔三条铁律内建:
#  1. 心跳按"产出文件mtime"判断,不按"进程存在"(zombie进程会骗过ps)
#  2. 验活失败输出诊断而非静默
#  3. 调用方必须对失败态有处置(20分钟规则)
bg_launch() {
  local name=$1 log=$2; shift 2
  nohup "$@" > "$log" 2>&1 &
  echo $! > "/tmp/bgtask_${name}.pid"
  echo "[bg_launch] $name PID=$(cat /tmp/bgtask_${name}.pid) log=$log"
}
bg_health() {
  local name=$1 out=$2 max_min=${3:-20}
  local pid=$(cat "/tmp/bgtask_${name}.pid" 2>/dev/null)
  local alive=0; [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && alive=1
  local fresh=0
  if [ -e "$out" ]; then
    local age=$(( ($(date +%s) - $(stat -f %m "$out")) / 60 ))
    [ "$age" -le "$max_min" ] && fresh=1 || true
  fi
  if [ "$alive" -eq 1 ] && [ "$fresh" -eq 1 ]; then echo "[bg_health] $name OK (pid=$pid, 产出${age:-?}分钟前)"; return 0
  elif [ "$alive" -eq 1 ]; then echo "[bg_health] ⛔ $name 进程在但产出停滞${age:-∞}分钟>$max_min = 疑似卡死(zombie型)"; return 2
  else echo "[bg_health] ⛔ $name 进程已死 (产出$([ -e "$out" ] && echo ${age}分钟前 || echo 不存在))"; return 1; fi
}
