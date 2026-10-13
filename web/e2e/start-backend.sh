#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# 场景：default 使用 .tmp/8010 承载既有用例；retention 使用独立数据根、数据库与端口，
# 只播种 51 个留存任务，保证"仅留最近 50 个现场"与恢复现场断言不受其他用例清理影响。
SCENARIO="${PATROLX_E2E_SCENARIO:-default}"
if [ "$SCENARIO" = "retention" ]; then
  E2E_DIR="${PATROLX_E2E_DIR:-$ROOT_DIR/web/e2e/.tmp-retention}"
  PORT="${PATROLX_E2E_PORT:-8011}"
else
  E2E_DIR="${PATROLX_E2E_DIR:-$ROOT_DIR/web/e2e/.tmp}"
  PORT="${PATROLX_E2E_PORT:-8010}"
fi
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
  # 工作树内没有 .venv 时向上查找主仓库的 .venv（相对层级随 worktree 路径变化，不能写死）
  SEARCH_DIR="$(dirname "$ROOT_DIR")"
  while [ "$SEARCH_DIR" != "/" ] && [ ! -x "$SEARCH_DIR/.venv/bin/python" ]; do
    SEARCH_DIR="$(dirname "$SEARCH_DIR")"
  done
  VENV_PYTHON="$SEARCH_DIR/.venv/bin/python"
fi
if [ ! -x "$VENV_PYTHON" ]; then
  echo "未找到可用的 .venv/bin/python，请先在仓库根执行 python build.py install" >&2
  exit 1
fi
# 工作树运行时必须显式指定仓库根，避免 editable 安装把 app 解析到主工作区。
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
LEGACY_TASK_ID="task-legacy-e2e"

rm -rf "$E2E_DIR"
mkdir -p "$E2E_DIR"

export PATROLX_OUTPUT_DIR="$E2E_DIR/output"
export PATROLX_UPLOADS_DIR="$E2E_DIR/uploads"
export PATROLX_SQLITE_PATH="$E2E_DIR/patrolx.db"

cd "$ROOT_DIR"
"$VENV_PYTHON" -m app.cli create-default-admin --username e2e-admin --password e2e-admin-123

if [ "$SCENARIO" = "retention" ]; then
  # 51 个留存任务；种子内部按留存策略清理最旧的 1 个并写出 retention-report.json。
  "$VENV_PYTHON" "$ROOT_DIR/web/e2e/seed_retention.py"
else
  mkdir -p \
    "$E2E_DIR/output/$LEGACY_TASK_ID" \
    "$E2E_DIR/uploads/$LEGACY_TASK_ID"
  cp "$ROOT_DIR/web/e2e/fixtures/task.json" "$E2E_DIR/output/$LEGACY_TASK_ID/task.json"
  touch "$E2E_DIR/uploads/$LEGACY_TASK_ID/legacy.zip"

  "$VENV_PYTHON" - <<'PYCODE'
from tests.fixtures.inventory.builder import (
    make_inventory_zip,
    make_log_supplement_zip,
    multi_device_lst_me_content,
)
from pathlib import Path
base = Path("web/e2e/.tmp")
base.mkdir(parents=True, exist_ok=True)
make_inventory_zip(
    base / "inventory-e2e.zip",
    content=multi_device_lst_me_content(
        [
            {"device_name": "NJ-AGG-001", "network_element_type": "umf", "version": "V900R016C10SPC200"},
            {"device_name": "NJ-CSP-001", "network_element_type": "csp", "version": "V900R016C10SPC100"},
        ]
    ),
)
make_inventory_zip(
    base / "inventory-e2e-rerun.zip",
    content=multi_device_lst_me_content(
        [
            {"device_name": "NJ-AGG-001", "network_element_type": "umf", "version": "V900R016C10SPC200"},
            {"device_name": "NJ-CSP-001", "network_element_type": "csp", "version": "V900R016C10SPC100"},
        ]
    ),
)
# 设备 ID 台账校验用例使用独立包与独立设备，避免与其他用例的台账增删互相干扰。
make_inventory_zip(
    base / "device-check-e2e.zip",
    content=multi_device_lst_me_content(
        [
            {
                "device_name": "E2E-DEV-901",
                "network_element_type": "umf",
                "version": "V900R016C10SPC200",
            }
        ]
    ),
)
make_log_supplement_zip(base / "log-supplement-e2e.zip")
PYCODE

  "$VENV_PYTHON" "$ROOT_DIR/web/e2e/seed_kpi_measurement_history.py"
  "$VENV_PYTHON" "$ROOT_DIR/web/e2e/seed_home_task.py"
  "$VENV_PYTHON" "$ROOT_DIR/web/e2e/seed_alarm_flapping.py"
fi

exec "$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
