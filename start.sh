#!/usr/bin/env bash

set -uo pipefail

cd "$(dirname "$0")" || exit 1

BACKEND_PORT="${BACKEND_PORT:-8082}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
VENV_PYTHON="venv/bin/python"
BACKEND_PID=""
FRONTEND_PID=""

echo
echo "=================================================="
echo "  contract-review-assistant 合同智能审查助手"
echo "=================================================="
echo

fail() {
  echo "[错误] $1" >&2
  exit 1
}

find_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      return 0
    fi
  done
  return 1
}

terminate_tree() {
  local pid="${1:-}"
  local child
  [[ -z "$pid" ]] && return
  if command -v pgrep >/dev/null 2>&1; then
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
      terminate_tree "$child"
    done
  fi
  kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  trap - EXIT INT TERM
  echo
  echo "[关闭] 正在停止前端和后端进程..."
  terminate_tree "$FRONTEND_PID"
  terminate_tree "$BACKEND_PID"
  wait "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

find_python || fail "未找到 Python 3.10 或更高版本，请先安装并加入 PATH。"
command -v node >/dev/null 2>&1 || fail "未找到 Node.js，请安装 Node.js 后重新运行。"
command -v npm >/dev/null 2>&1 || fail "未找到 npm，请重新安装包含 npm 的 Node.js。"

echo "[环境] $($PYTHON_BIN --version 2>&1)"
echo "[环境] Node.js $(node --version)"

if [[ ! -f ".env" ]]; then
  [[ -f ".env.example" ]] || fail "根目录缺少 .env 和 .env.example，无法加载环境配置。"
  cp ".env.example" ".env" || fail "无法从 .env.example 创建 .env，请检查目录写入权限。"
  echo "[配置] 未找到 .env，已自动复制 .env.example。正式使用前请修改其中的密钥。"
else
  echo "[配置] 已读取根目录 .env。"
fi

set -a
# shellcheck disable=SC1091
source ".env"
set +a

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[准备] 未发现 ./venv，正在创建 Python 虚拟环境..."
  "$PYTHON_BIN" -m venv venv || fail "Python 虚拟环境创建失败，请检查 Python venv 组件和目录权限。"
fi

echo "[准备] 正在安装或校验后端依赖..."
"$VENV_PYTHON" -m pip install --timeout 120 --retries 5 -r requirements.txt || fail "后端依赖安装失败，请检查网络、代理和 requirements.txt。"

if [[ ! -x "frontend/node_modules/.bin/vite" ]]; then
  echo "[准备] 未发现前端依赖，正在执行 npm install..."
  npm --prefix frontend install --fetch-timeout=120000 --fetch-retries=5 || fail "前端依赖安装失败，请检查网络、npm 镜像和 frontend/package.json。"
else
  echo "[准备] 已发现前端依赖。"
fi

port_is_available() {
  "$VENV_PYTHON" - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])

def can_connect(family, address):
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        return sock.connect_ex(address) == 0
    finally:
        sock.close()

def can_bind(family, address):
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        # Windows otherwise permits a wildcard probe beside a loopback listener.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if family == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
            # Check IPv6-only listeners without colliding with the IPv4 probe.
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind(address)
        return True
    except OSError:
        return False
    finally:
        sock.close()

if can_connect(socket.AF_INET, ("127.0.0.1", port)):
    raise SystemExit(1)
if socket.has_ipv6 and can_connect(socket.AF_INET6, ("::1", port)):
    raise SystemExit(1)
if not can_bind(socket.AF_INET, ("0.0.0.0", port)):
    raise SystemExit(1)
try:
    ipv6_available = socket.has_ipv6
except AttributeError:
    ipv6_available = False
if ipv6_available and not can_bind(socket.AF_INET6, ("::", port)):
    raise SystemExit(1)
raise SystemExit(0)
PY
}

find_free_port() {
  local candidate="$1"
  local label="$2"
  local reserved="${3:-}"
  local previous

  if ! [[ "$candidate" =~ ^[0-9]+$ ]] || (( candidate < 1 || candidate > 65535 )); then
    echo "[错误] $label起始端口必须是 1 到 65535 之间的数字。" >&2
    return 1
  fi
  while [[ "$candidate" == "$reserved" ]] || ! port_is_available "$candidate"; do
    if (( candidate >= 65535 )); then
      echo "[错误] $label没有可用端口（已扫描到 65535）。" >&2
      return 1
    fi
    previous="$candidate"
    candidate=$((candidate + 1))
    echo "[端口] $label端口 $previous 已被占用，自动顺延至 $candidate。" >&2
  done
  printf '%s' "$candidate"
}

if ! BACKEND_PORT="$(find_free_port "$BACKEND_PORT" "后端")"; then
  fail "后端端口自动分配失败，请检查端口范围或手动释放端口。"
fi
if ! FRONTEND_PORT="$(find_free_port "$FRONTEND_PORT" "前端" "$BACKEND_PORT")"; then
  fail "前端端口自动分配失败，请检查端口范围或手动释放端口。"
fi

echo "[端口] 后端将使用 $BACKEND_PORT，前端开发服务将使用 $FRONTEND_PORT。"

echo
echo "[启动] 正在启动 FastAPI 后端..."
echo "[提示] 当前部分业务模块尚未编码完成，部分接口返回 404。"
"$VENV_PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!

backend_ready=false
for _ in $(seq 1 30); do
  kill -0 "$BACKEND_PID" 2>/dev/null || fail "后端进程提前退出，请检查上方错误信息。"
  if "$VENV_PYTHON" -c "import urllib.request; raise SystemExit(0 if urllib.request.urlopen('http://127.0.0.1:$BACKEND_PORT/api/health', timeout=1).status == 200 else 1)" >/dev/null 2>&1; then
    backend_ready=true
    break
  fi
  sleep 1
done
[[ "$backend_ready" == true ]] || fail "后端在 30 秒内未能就绪。"

sleep 2
echo "[启动] 正在启动 Vue 3 前端..."
(
  cd frontend || exit 1
  npm run dev -- --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

frontend_ready=false
for _ in $(seq 1 30); do
  kill -0 "$FRONTEND_PID" 2>/dev/null || fail "前端进程提前退出，请检查上方 npm 输出。"
  if ! port_is_available "$FRONTEND_PORT"; then
    frontend_ready=true
    break
  fi
  sleep 1
done
[[ "$frontend_ready" == true ]] || fail "前端在 30 秒内未能就绪。"

echo
echo "=================================================="
echo " 启动成功：http://localhost:$BACKEND_PORT"
echo " 前端开发服务：http://localhost:$FRONTEND_PORT"
echo " 当前部分业务模块尚未编码完成，部分接口返回 404。"
echo " 关闭所有前端页面后，前后端服务会自动退出。"
echo "=================================================="
echo

if [[ "${CONTRACT_REVIEW_NO_BROWSER:-0}" == "1" ]]; then
  echo "[测试] 已跳过自动打开浏览器。"
elif command -v open >/dev/null 2>&1; then
  open "http://localhost:$BACKEND_PORT" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:$BACKEND_PORT" >/dev/null 2>&1 || true
else
  echo "[提示] 未找到浏览器打开命令，请手动访问 http://localhost:$BACKEND_PORT"
fi

shutdown_requested=false
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  if "$VENV_PYTHON" -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:$BACKEND_PORT/api/runtime/status', timeout=1)); raise SystemExit(0 if data.get('client_seen') and data.get('shutdown_requested') else 1)" >/dev/null 2>&1; then
    echo "[关闭] 已检测到所有前端页面关闭。"
    shutdown_requested=true
    break
  fi
  sleep 1
done

if [[ "$shutdown_requested" == true ]]; then
  exit 0
fi

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  fail "后端服务意外退出。"
fi
fail "前端服务意外退出。"
