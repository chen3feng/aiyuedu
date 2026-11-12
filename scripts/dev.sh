#!/usr/bin/env bash
# aiyuedu 本地开发一键启停
#
#   ./scripts/dev.sh              启动全部服务（= start）
#   ./scripts/dev.sh start        启动全部服务（已在运行的跳过）
#   ./scripts/dev.sh stop         停止全部服务
#   ./scripts/dev.sh restart      重启全部服务
#   ./scripts/dev.sh status       查看运行状态
#   ./scripts/dev.sh logs [svc]   跟踪日志（svc = api|admin|h5，默认全部）
#
# API 端口默认 8000，可用 API_PORT 覆盖（如 API_PORT=8002 ./scripts/dev.sh start）；
# 未指定时会沿用 .run/api_port 里上次使用的端口。
#
# 服务：
#   api    FastAPI 学生端   http://127.0.0.1:8000   （可用 API_PORT 覆盖，如 8002）
#   admin  FastAPI 后台     http://127.0.0.1:8001
#   h5     uni-app H5       http://localhost:5173
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.run"
LOG_DIR="$RUN_DIR/logs"

# API 端口可用 API_PORT 覆盖（默认 8000）；H5 会通过 VITE_API_PORT 指向它。
# 未显式指定时，优先沿用上次 start 记录的端口，避免 status/stop 误判。
if [ -z "${API_PORT:-}" ] && [ -f "$RUN_DIR/api_port" ]; then
  API_PORT="$(cat "$RUN_DIR/api_port" 2>/dev/null || echo 8000)"
fi
API_PORT="${API_PORT:-8000}"

# name port probe-path
SERVICES=(
  "api $API_PORT /docs"
  "admin 8001 /docs"
  "h5 5173 /"
)

# --- 输出辅助 --------------------------------------------------------------

if [ -t 1 ]; then
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""; C_OFF=""
fi

info()  { printf '%s\n' "${C_GREEN}==>${C_OFF} $*"; }
warn()  { printf '%s\n' "${C_YELLOW}!!${C_OFF} $*"; }
error() { printf '%s\n' "${C_RED}xx${C_OFF} $*" >&2; }

# --- 工具函数 --------------------------------------------------------------

pid_file() { printf '%s/%s.pid' "$RUN_DIR" "$1"; }
log_file() { printf '%s/%s.log' "$LOG_DIR" "$1"; }

# 端口是否已有进程监听
port_in_use() { lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1; }

# 该服务（按记录的 pid）是否存活
is_alive() {
  local pid
  pid="$(cat "$(pid_file "$1")" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# 等待端口就绪并能通过 HTTP 探测；超时返回 1
wait_ready() {
  local name="$1" port="$2" path="$3" tries=60
  for _ in $(seq 1 "$tries"); do
    if curl -sf "http://127.0.0.1:${port}${path}" -o /dev/null 2>/dev/null; then
      return 0
    fi
    # 进程提前退出就不再等
    is_alive "$name" || return 1
    sleep 1
  done
  return 1
}

start_one() {
  local name="$1" port="$2" path="$3"
  local pid; pid="$(cat "$(pid_file "$name")" 2>/dev/null || true)"

  if is_alive "$name"; then
    warn "$name 已在运行 (pid $pid)，跳过"
    return 0
  fi
  if port_in_use "$port"; then
    error "$name 端口 $port 已被其他进程占用，跳过（可用 lsof -iTCP:$port 查看）"
    return 1
  fi

  info "启动 $name …"
  case "$name" in
    api)
      ( cd "$ROOT" && nohup uv run --directory apps/api uvicorn app.main:app --reload --port "$port" \
          >"$(log_file "$name")" 2>&1 & echo $! >"$(pid_file "$name")" )
      ;;
    admin)
      ( cd "$ROOT" && nohup uv run --directory apps/api uvicorn app.admin_app:admin_app --reload --port "$port" \
          >"$(log_file "$name")" 2>&1 & echo $! >"$(pid_file "$name")" )
      ;;
    h5)
      ( cd "$ROOT/apps/app" && VITE_API_PORT="$API_PORT" VITE_API_BASE="${VITE_API_BASE:-}" nohup npm run dev:h5 \
          >"$(log_file "$name")" 2>&1 & echo $! >"$(pid_file "$name")" )
      ;;
  esac

  if wait_ready "$name" "$port" "$path"; then
    info "$name 就绪 ${C_DIM}http://127.0.0.1:$port${C_OFF}"
  else
    error "$name 启动失败，最后 20 行日志："
    tail -20 "$(log_file "$name")" >&2 || true
    return 1
  fi
}

stop_one() {
  local name="$1" port="$2"
  local pid; pid="$(cat "$(pid_file "$name")" 2>/dev/null || true)"
  if [ -z "$pid" ] && ! port_in_use "$port"; then
    warn "$name 未在运行"
    rm -f "$(pid_file "$name")"
    return
  fi

  info "停止 $name …"
  [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do
    is_alive "$name" || port_in_use "$port" || break
    sleep 0.3
  done

  # 父进程被杀后可能留下占端口的子进程（uvicorn reload / npm→vite）
  if port_in_use "$port"; then
    local listeners; listeners="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ')"
    warn "$name 端口仍被占用 (pid $listeners)，结束监听进程"
    # shellcheck disable=SC2086
    kill -TERM $listeners 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -KILL $listeners 2>/dev/null || true
  fi
  [ -n "$pid" ] && is_alive "$name" && kill -KILL "$pid" 2>/dev/null || true
  rm -f "$(pid_file "$name")"
}

# --- 命令 ------------------------------------------------------------------

cmd_start() {
  mkdir -p "$RUN_DIR" "$LOG_DIR"
  printf '%s\n' "$API_PORT" >"$RUN_DIR/api_port"
  local failed=0
  for svc in "${SERVICES[@]}"; do
    # shellcheck disable=SC2086
    start_one $svc || failed=1
  done
  if [ "$failed" -eq 0 ]; then
    info "全部就绪，打开 ${C_GREEN}http://localhost:5173${C_OFF} 即可使用"
  else
    error "有服务启动失败，请查看上方日志"
    exit 1
  fi
}

cmd_stop() {
  for svc in "${SERVICES[@]}"; do
    # shellcheck disable=SC2086
    stop_one $svc
  done
}

cmd_status() {
  printf '%-8s %-8s %-10s %s\n' "SERVICE" "PORT" "STATUS" "PID"
  for svc in "${SERVICES[@]}"; do
    set -- $svc
    local name="$1" port="$2" path="$3" pid="-"
    if is_alive "$name"; then
      pid="$(cat "$(pid_file "$name")")"
      if curl -sf "http://127.0.0.1:${port}${path}" -o /dev/null 2>/dev/null; then
        printf '%-8s %-8s %s %s\n' "$name" "$port" "${C_GREEN}LISTENING${C_OFF}" "$pid"
      else
        printf '%-8s %-8s %s %s\n' "$name" "$port" "${C_YELLOW}STARTING?${C_OFF}" "$pid"
      fi
    else
      printf '%-8s %-8s %s %s\n' "$name" "$port" "${C_DIM}STOPPED${C_OFF}" "-"
    fi
  done
}

cmd_logs() {
  local target="${1:-}"
  if [ -z "$target" ]; then
    exec tail -F "$LOG_DIR"/*.log
  fi
  case "$target" in
    api|admin|h5) exec tail -F "$(log_file "$target")" ;;
    *) error "未知服务：$target（可选 api | admin | h5）"; exit 1 ;;
  esac
}

mkdir -p "$RUN_DIR" "$LOG_DIR"

case "${1:-start}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  logs)    shift; cmd_logs "${1:-}" ;;
  *) error "未知命令：$1"; echo "用法: $0 [start|stop|restart|status|logs [api|admin|h5]]" >&2; exit 1 ;;
esac
