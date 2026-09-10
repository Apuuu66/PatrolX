#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[PatrolX] 未找到 python3，请先安装 Python 3.11+"
    exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
    echo "[PatrolX] 初始化离线运行环境..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e ".[dev]"
fi

echo "[PatrolX] 离线巡检开始..."
echo "[PatrolX] 输入目录：${PATROLX_PACKAGE_DIR:-uploads}"
echo "[PatrolX] 产物目录：output"
exec .venv/bin/python main.py "$@"
