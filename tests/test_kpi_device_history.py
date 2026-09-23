"""设备 ID 与历史索引刷新测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models.db import AuthSession, TaskRecord, init_db, session_factory
from app.models.schemas import (
    InspectionTask,
    RuleResult,
    RuleStatus,
    Summary,
    SystemInspection,
    TaskStats,
)
from app.services.store import save_task_meta
from app.services.tasks import task_service
from tests.baseline_helpers import setup_env


def _meta(task_id: str, status: str = "completed") -> InspectionTask:
    status_map = {
        "pending": ("pending", 0),
        "running": ("running", 0),
        "completed": ("completed", 1),
        "failed": ("failed", 1),
    }
    status_name, pass_count = status_map[status]
    rule = RuleResult(
        code="kpi.measurement_units",
        name="测量单元",
        category="kpi",
        priority=1,
        execution_order=1,
        status=RuleStatus.PASS if pass_count else RuleStatus.SKIP,
        severity="medium",
        skip_reason=None if pass_count else "测试跳过",
    )

    stats = TaskStats.model_validate(
        {"total": 1, "pass": pass_count, "warn": 0, "fail": 0, "error": 0, "skip": 1 - pass_count, "systems": 1}
    )
    return InspectionTask(
        task_id=task_id,
        name=task_id,
        mode="local",
        status=status_name,
        trigger="api",
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
        completed_at=datetime(2026, 9, 10, 12, tzinfo=UTC) if status_name == "completed" else None,
        stats=stats,
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            status="completed" if status_name == "completed" else "failed",
            summary=Summary.model_validate(
                {"total": 1, "pass": pass_count, "warn": 0, "fail": 0, "error": 0, "skip": 1 - pass_count}
            ),
            rules=[rule],
            customer={"device_id": "device-old"},
        ),
    )


def _task_with_meta(env, task_id: str, status: str = "completed") -> InspectionTask:
    save_task_meta(env.output, _meta(task_id, status))
    return _meta(task_id, status)


def test_reserve_trims_and_exposes_device_id(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    init_db()
    created = task_service.reserve("device.zip", None, None, None, None, device_id="  device-01  ")
    items, total = task_service.list_tasks(1, 10, None)
    assert total == 1
    assert items[0].device_id == "device-01"
    record = session_factory().get(TaskRecord, created.task_id)  # type: ignore[union-attr]
    assert record is not None and record.customer["device_id"] == "device-01"


def test_update_device_id_syncs_metadata_and_checks_auth(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    init_db()
    task_id = "task-device"
    meta = _task_with_meta(env, task_id)
    system_file = env.task_dir(task_id) / "system.json"
    system_file.write_text(json.dumps(meta.system.model_dump(by_alias=True)), encoding="utf-8")

    client = TestClient(app)
    response = client.patch(
        f"/api/v2/tasks/{task_id}/device-id",
        json={"device_id": "  device-new  "},
    )
    assert response.status_code == 200, response.text
    assert response.json()["device_id"] == "device-new"
    task_data = json.loads((env.task_dir(task_id) / "task.json").read_text())
    system_data = json.loads(system_file.read_text())
    assert task_data["system"]["customer"]["device_id"] == "device-new"
    assert system_data["customer"]["device_id"] == "device-new"

    from app.services.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: AuthSession(token="viewer", username="viewer", role="viewer")
    try:
        denied = TestClient(app).patch(f"/api/v2/tasks/{task_id}/device-id", json={"device_id": "other"})
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_update_device_id_rejects_running_and_missing(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    init_db()
    _task_with_meta(env, "task-running", status="running")
    client = TestClient(app)
    busy = client.patch("/api/v2/tasks/task-running/device-id", json={"device_id": "device-new"})
    assert busy.status_code == 409
    missing = client.patch("/api/v2/tasks/task-missing/device-id", json={"device_id": "device-new"})
    assert missing.status_code == 404


def test_device_id_change_immediately_changes_history_match(tmp_path, monkeypatch) -> None:
    from datetime import timedelta

    from app.services.kpi_history import get_history_trend, write_history_index

    env = setup_env(tmp_path, monkeypatch)
    init_db()
    task_id = "task-history-device"
    _task_with_meta(env, task_id)

    candidate_id = "task-history-old"
    candidate = _meta(candidate_id)
    candidate.completed_at = candidate.completed_at - timedelta(days=1)  # type: ignore[operator]
    save_task_meta(env.output, candidate)
    for owner in (candidate_id, task_id):
        write_history_index(
            owner,
            [
                {
                    "task_id": owner,
                    "measurement_unit_id": "MU",
                    "metric_resource_id": "ME",
                    "object_key": "pod-a",
                    "period_minutes": 15,
                    "measured_at": "2026-09-09T10:00:00+00:00",
                    "value": 10,
                    "source_file": "a.csv",
                    "line_number": 1,
                }
            ],
            output=env.output,
        )

    def query() -> str:
        trend = get_history_trend(
            task_id,
            rule_code="kpi.measurement_units",
            measurement_unit_id="MU",
            metric_resource_id="ME",
            object_key="pod-a",
            period_minutes=15,
            output=env.output,
        )
        return trend.match.status

    task_service.update_device_id(task_id, "")
    assert query() == "degraded"
    task_service.update_device_id(task_id, "device-b")
    assert query() == "no_history"


def test_delete_task_removes_output_uploads_and_index(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    init_db()
    task_id = "task-delete"
    _task_with_meta(env, task_id)
    index = env.task_dir(task_id) / "kpi" / "history" / "index.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text('{"task_id":"task-delete"}\n', encoding="utf-8")
    upload_file = env.uploads / task_id / "task-delete.zip"
    upload_file.parent.mkdir(parents=True, exist_ok=True)
    upload_file.write_bytes(b"zip")
    with session_factory() as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                name=task_id,
                mode="local",
                status="completed",
                trigger="api",
                package_file="task-delete.zip",
                customer={},
                stats={},
                created_at=datetime.now(UTC),
            )
        )
        session.commit()

    response = TestClient(app).delete(f"/api/v2/tasks/{task_id}")
    assert response.status_code == 204, response.text
    assert not env.task_dir(task_id).exists()
    assert not (env.uploads / task_id).exists()
    assert session_factory().get(TaskRecord, task_id) is None  # type: ignore[union-attr]
