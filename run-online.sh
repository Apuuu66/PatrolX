#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[PatrolX] 未找到 python3，请先安装 Python 3.11+"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "[PatrolX] 未找到 npm，请先安装 Node.js 18+"
    exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
    echo "[PatrolX] 初始化在线运行环境..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e ".[dev]"
fi

if [[ ! -d "web/node_modules" ]]; then
    echo "[PatrolX] 安装前端依赖..."
    (cd web && npm install)
fi

cleanup() {
    if [[ -n "${backend_pid:-}" ]]; then
        kill "$backend_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "[PatrolX] 在线预览启动中..."
echo "[PatrolX] 后端 API：http://127.0.0.1:8000"
echo "[PatrolX] 前端页面：http://127.0.0.1:5173"
echo "[PatrolX] 停止服务：按 Ctrl+C"
.venv/bin/python -m uvicorn app.main:app --reload &
backend_pid=$!

(cd web && npm run dev)
