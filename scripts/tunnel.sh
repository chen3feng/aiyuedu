#!/usr/bin/env bash
# aiyuedu 本地服务 + Cloudflare Quick Tunnel 一键启动
#
#   ./scripts/tunnel.sh           启动服务（已在运行的跳过）和两条隧道，
#                                 打印公网链接并保持前台（Ctrl-C 只关隧道）
#   ./scripts/tunnel.sh -d        同上，打印后退出（隧道留在后台）
#   ./scripts/tunnel.sh stop      停止隧道（本地服务保持运行）
#   ./scripts/tunnel.sh status    查看服务和隧道状态
#
# 隧道：
#   api  → http://127.0.0.1:$API_PORT   学生端 API（/health 可直接探活）
#   h5   → http://127.0.0.1:5173        H5（/api 由 Vite 反代到 api）
#
# Quick Tunnel 不需要 Cloudflare 账号，每次启动 URL 都是随机的；进程退出即失效。
# 需要 cloudflared：brew install cloudflared
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.run"
LOG_DIR="$RUN_DIR/logs"
DEV="$ROOT/scripts/dev.sh"

# 与 dev.sh 保持同一套端口规则：显式 API_PORT > .run/api_port > 8000
if [ -z "${API_PORT:-}" ] && [ -f "$RUN_DIR/api_port" ]; then
  API_PORT="$(cat "$RUN_DIR/api_port" 2>/dev/null || echo 8000)"
fi
API_PORT="${API_PORT:-8000}"

# name target-port
TUNNELS=(
  "api $API_PORT"
  "h5 5173"
)

if [ -t 1 ]; then
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""; C_OFF=""
fi

info()  { printf '%s\n' "${C_GREEN}==>${C_OFF} $*"; }
warn()  { printf '%s\n' "${C_YELLOW}!!${C_OFF} $*"; }
error() { printf '%s\n' "${C_RED}xx${C_OFF} $*" >&2; }

pid_file()  { printf '%s/cf-%s.pid' "$RUN_DIR" "$1"; }
url_file()  { printf '%s/cf-%s.url' "$RUN_DIR" "$1"; }
log_file()  { printf '%s/cf-%s.log' "$LOG_DIR" "$1"; }

is_alive() {
  local pid
  pid="$(cat "$(pid_file "$1")" 2>/dev/null || true)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

port_in_use() { lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1; }

url_of() {
  local name="$1" url=""
  [ -f "$(url_file "$name")" ] && url="$(cat "$(url_file "$name")" 2>/dev/null || true)"
  if [ -z "$url" ] && [ -f "$(log_file "$name")" ]; then
    url="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$(log_file "$name")" 2>/dev/null | head -1 || true)"
  fi
  printf '%s' "$url"
}

wait_url() {
  local name="$1" tries="${2:-90}" url=""
  for _ in $(seq 1 "$tries"); do
    url="$(url_of "$name")"
    [ -n "$url" ] && { printf '%s' "$url"; return 0; }
    is_alive "$name" || return 1
    sleep 1
  done
  return 1
}

# 本机解析可能滞后（代理/缓存），只做尽力等待，不阻塞失败
wait_dns() {
  local host="$1" tries="${2:-20}"
  command -v dig >/dev/null 2>&1 || return 0
  for _ in $(seq 1 "$tries"); do
    [ -n "$(dig +short "$host" 2>/dev/null | head -1)" ] && return 0
    sleep 2
  done
  return 1
}

start_tunnel() {
  local name="$1" port="$2"

  if is_alive "$name"; then
    warn "$name 隧道已在运行 (pid $(cat "$(pid_file "$name")"))，复用"
    return 0
  fi
  rm -f "$(pid_file "$name")" "$(url_file "$name")"

  if pgrep -f "cloudflared tunnel --url http://127.0.0.1:${port}( |$)" >/dev/null 2>&1; then
    error "$name 端口 ${port} 已有未记录的 cloudflared 进程在跑；"
    error "先结束它再试：pkill -f 'cloudflared tunnel --url http://127.0.0.1:${port}'"
    return 1
  fi
  if ! port_in_use "$port"; then
    error "$name 本地端口 ${port} 没有监听，隧道无法建立"
    return 1
  fi

  info "建立 $name 隧道（127.0.0.1:${port}）…"
  nohup cloudflared tunnel --url "http://127.0.0.1:${port}" --no-autoupdate \
    >"$(log_file "$name")" 2>&1 &
  echo $! >"$(pid_file "$name")"

  local url
  if url="$(wait_url "$name" 90)"; then
    printf '%s\n' "$url" >"$(url_file "$name")"
    info "$name 隧道就绪 ${C_DIM}${url}${C_OFF}"
  else
    error "$name 隧道建立失败，最后 20 行日志："
    tail -20 "$(log_file "$name")" >&2 || true
    stop_tunnel "$name"
    return 1
  fi
}

stop_tunnel() {
  local name="$1" pid
  pid="$(cat "$(pid_file "$name")" 2>/dev/null || true)"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$(pid_file "$name")" "$(url_file "$name")"
    return 0
  fi
  info "关闭 $name 隧道 (pid $pid) …"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
  done
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$(pid_file "$name")" "$(url_file "$name")"
}

stop_all() {
  local t
  for t in "${TUNNELS[@]}"; do
    # shellcheck disable=SC2086
    stop_tunnel $t
  done
}

print_links() {
  local t
  printf '\n'
  printf '%-6s %-62s %s\n' "SERVICE" "PUBLIC URL" "LOCAL"
  for t in "${TUNNELS[@]}"; do
    set -- $t
    local name="$1" port="$2" url
    url="$(url_of "$name")"
    printf '%-6s %-62s %s\n' "$name" "${url:-（未启动）}" "http://127.0.0.1:$port"
  done
  printf '\n'
  local api_url h5_url
  api_url="$(url_of api)"; h5_url="$(url_of h5)"
  [ -n "$api_url" ] && printf '  接口探活: %s/health\n' "$api_url"
  [ -n "$h5_url" ]  && printf '  打开前端: %s\n' "$h5_url"
  printf '\n'
}

cmd_start() {
  local detach="${1:-0}"

  command -v cloudflared >/dev/null 2>&1 || {
    error "未安装 cloudflared：brew install cloudflared"
    exit 1
  }
  [ -x "$DEV" ] || { error "找不到 $DEV"; exit 1; }
  mkdir -p "$RUN_DIR" "$LOG_DIR"

  info "启动本地服务（已在运行的会跳过）…"
  "$DEV" start

  local t failed=0
  for t in "${TUNNELS[@]}"; do
    # shellcheck disable=SC2086
    start_tunnel $t || failed=1
  done
  if [ "$failed" -ne 0 ]; then
    error "有隧道建立失败，关闭已建立的隧道"
    stop_all
    exit 1
  fi

  info "等待 DNS 生效（本机解析可能因代理滞后）…"
  local host
  for t in "${TUNNELS[@]}"; do
    set -- $t
    host="$(url_of "$1" | sed -E 's#https://([^/]+).*#\1#')"
    if [ -n "$host" ] && wait_dns "$host"; then
      info "$host 已可解析"
    else
      warn "$host 本机暂时解析不到；外网/浏览器通常已可用，稍等片刻即可"
    fi
  done

  print_links

  if [ "$detach" -eq 1 ]; then
    info "隧道已转到后台（./scripts/tunnel.sh stop 可关闭）"
    return 0
  fi

  info "隧道保持运行，按 Ctrl-C 关闭隧道（本地服务继续运行）"
  # shellcheck disable=SC2064
  trap 'echo; info "关闭隧道…"; stop_all; exit 0' INT TERM
  wait
}

cmd_stop() {
  stop_all
  info "隧道已关闭；本地服务仍在运行（./scripts/dev.sh stop 可停止服务）"
}

cmd_status() {
  "$DEV" status
  printf '\n'
  local t
  printf '%-8s %-10s %-62s %s\n' "TUNNEL" "STATUS" "URL" "PID"
  for t in "${TUNNELS[@]}"; do
    set -- $t
    local name="$1" pid="-" url="-" status
    if is_alive "$name"; then
      pid="$(cat "$(pid_file "$name")")"
      url="$(url_of "$name")"
      status="${C_GREEN}RUNNING${C_OFF}"
    else
      status="${C_DIM}STOPPED${C_OFF}"
    fi
    printf '%-8s %-10s %-62s %s\n' "$name" "$status" "$url" "$pid"
  done
}

mkdir -p "$RUN_DIR" "$LOG_DIR"

case "${1:-start}" in
  start)  cmd_start 0 ;;
  -d|--detach) cmd_start 1 ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  *)
    error "未知命令：$1"
    echo "用法: $0 [start|-d|stop|status]" >&2
    exit 1
    ;;
esac
