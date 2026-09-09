#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "未找到 python3，请先安装 Python 3.11+"
    exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
    echo "[PatrolX] 创建虚拟环境并安装依赖..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e ".[dev]"
fi

echo "[PatrolX] 开始本地巡检..."
exec .venv/bin/python main.py
