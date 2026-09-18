#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
E2E_DIR="$ROOT_DIR/web/e2e/.tmp"
LEGACY_TASK_ID="task-legacy-e2e"
KPI_TASK_ID="task-kpi-e2e"

rm -rf "$E2E_DIR"
mkdir -p \
  "$E2E_DIR/output/$LEGACY_TASK_ID" \
  "$E2E_DIR/output/$KPI_TASK_ID/rules" \
  "$E2E_DIR/uploads/$LEGACY_TASK_ID" \
  "$E2E_DIR/uploads/$KPI_TASK_ID"
cp "$ROOT_DIR/web/e2e/fixtures/task.json" "$E2E_DIR/output/$LEGACY_TASK_ID/task.json"
touch "$E2E_DIR/uploads/$LEGACY_TASK_ID/legacy.zip"
cp "$ROOT_DIR/web/e2e/fixtures/kpi-task.json" "$E2E_DIR/output/$KPI_TASK_ID/task.json"
cp "$ROOT_DIR/web/e2e/fixtures/kpi.call.json" "$E2E_DIR/output/$KPI_TASK_ID/rules/kpi.call.json"
cp "$ROOT_DIR/web/e2e/fixtures/kpi-system.json" "$E2E_DIR/output/$KPI_TASK_ID/system.json"
touch "$E2E_DIR/uploads/$KPI_TASK_ID/kpi.zip"

export PATROLX_OUTPUT_DIR="$E2E_DIR/output"
export PATROLX_UPLOADS_DIR="$E2E_DIR/uploads"
export PATROLX_SQLITE_PATH="$E2E_DIR/patrolx.db"
export PATROLX_KPI_CATALOG_PATH="$ROOT_DIR/web/e2e/fixtures/kpi-catalog.json"

cd "$ROOT_DIR"
exec "$ROOT_DIR/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8010
