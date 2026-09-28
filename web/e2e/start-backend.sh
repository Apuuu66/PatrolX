#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
E2E_DIR="$ROOT_DIR/web/e2e/.tmp"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$VENV_PYTHON" ]; then
  VENV_PYTHON="$(dirname "$(dirname "$ROOT_DIR")")/.venv/bin/python"
export PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}"
fi
LEGACY_TASK_ID="task-legacy-e2e"

rm -rf "$E2E_DIR"
mkdir -p \
  "$E2E_DIR/output/$LEGACY_TASK_ID" \
  "$E2E_DIR/uploads/$LEGACY_TASK_ID"
cp "$ROOT_DIR/web/e2e/fixtures/task.json" "$E2E_DIR/output/$LEGACY_TASK_ID/task.json"
touch "$E2E_DIR/uploads/$LEGACY_TASK_ID/legacy.zip"

cd "$ROOT_DIR"
"$VENV_PYTHON" - <<'PYCODE'
from tests.fixtures.inventory.builder import make_inventory_zip, make_log_supplement_zip
from pathlib import Path
base = Path("web/e2e/.tmp")
base.mkdir(parents=True, exist_ok=True)
make_inventory_zip(base / "inventory-e2e.zip")
make_log_supplement_zip(base / "log-supplement-e2e.zip")
PYCODE

export PATROLX_OUTPUT_DIR="$E2E_DIR/output"
export PATROLX_UPLOADS_DIR="$E2E_DIR/uploads"
export PATROLX_SQLITE_PATH="$E2E_DIR/patrolx.db"

cd "$ROOT_DIR"
"$VENV_PYTHON" "$ROOT_DIR/web/e2e/seed_kpi_measurement_history.py"
"$VENV_PYTHON" "$ROOT_DIR/web/e2e/seed_home_task.py"
exec "$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8010
