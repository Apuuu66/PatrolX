#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "未找到 python3，请先安装 Python 3.11+"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "未找到 npm，请先安装 Node.js 18+"
    exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
    echo "[PatrolX] 创建虚拟环境并安装后端依赖..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e ".[dev]"
fi

if [[ ! -d "web/node_modules" ]]; then
    echo "[PatrolX] 安装前端依赖..."
    (cd web && npm install)
fi

echo "[PatrolX] 启动后端 API: http://127.0.0.1:8000"
.venv/bin/python -m uvicorn app.main:app --reload &
backend_pid=$!

cleanup() {
    kill "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT

echo "[PatrolX] 启动前端页面..."
cd web
npm run dev
