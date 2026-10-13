"""手动设备 ID 台账存在性校验（034 FR-010、SC-005、R9）。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.cli import generate_task_id
from app.core.config import settings
from app.main import app
from app.models.db import (
    InventoryDevice,
    InventoryObservation,
    InventoryParseResult,
    TaskRecord,
    init_db,
    session_factory,
)
from app.models.schemas import (
    InspectionTask,
    RuleResult,
    RuleStatus,
    Summary,
    SystemInspection,
    TaskStats,
)
from app.services.store import save_task_meta
from app.services.tasks import TaskDeviceIdError, task_service
from tests.baseline_helpers import setup_env

EXISTING_DEVICE = "js-nj-agg-001"


def _seed_device(device_id: str = EXISTING_DEVICE) -> None:
    """写入一台台账设备；设备 ID 由省份与规范化设备名确定性生成。"""
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            InventoryDevice(
                device_id=device_id,
                device_key=f"{device_id}-key",
                province="江苏",
                current_device_name=device_id,
                current_site_key="江苏|移动",
                current_operator="移动",
                current_version_raw="V900R016C10SPC200",
                current_version_observed_at=now,
                current_version_task_id="task-ledger",
                first_seen_at=now,
                last_seen_at=now,
                latest_task_id="task-ledger",
                latest_status="archived",
                observation_count=1,
                site_change_count=0,
                has_site_conflict=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


@pytest.fixture(autouse=True)
def _clean_inventory() -> None:
    init_db()
    with session_factory() as session:
        for model in (InventoryObservation, InventoryParseResult, InventoryDevice):
            session.query(model).delete()
        session.commit()
    yield
    with session_factory() as session:
        for model in (InventoryObservation, InventoryParseResult, InventoryDevice):
            session.query(model).delete()
        session.commit()


def _meta(task_id: str, device_id: str = "device-old") -> InspectionTask:
    rule = RuleResult(
        code="kpi.measurement_units",
        name="测量单元",
        category="kpi",
        priority=1,
        execution_order=1,
        status=RuleStatus.PASS,
        severity="medium",
    )
    return InspectionTask(
        task_id=task_id,
        name=task_id,
        mode="local",
        status="completed",
        trigger="api",
        created_at=datetime(2026, 9, 10, tzinfo=UTC),
        completed_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
        stats=TaskStats.model_validate(
            {"total": 1, "pass": 1, "warn": 0, "fail": 0, "error": 0, "skip": 0, "systems": 1}
        ),
        system=SystemInspection(
            package_file=f"{task_id}.zip",
            status="completed",
            summary=Summary.model_validate({"total": 1, "pass": 1, "warn": 0, "fail": 0, "error": 0, "skip": 0}),
            rules=[rule],
            customer={"province": "江苏", "operator": "移动", "device_id": device_id},
        ),
    )


def _task_with_meta(env, task_id: str, device_id: str = "device-old") -> InspectionTask:
    meta = _meta(task_id, device_id)
    save_task_meta(env.output, meta)
    (env.task_dir(task_id) / "system.json").write_text(
        json.dumps(meta.system.model_dump(by_alias=True)), encoding="utf-8"
    )
    return meta


def _customer_device(env, task_id: str) -> str | None:
    data = json.loads((env.task_dir(task_id) / "task.json").read_text(encoding="utf-8"))
    return data["system"]["customer"].get("device_id")


def test_update_device_id_requires_existing_inventory_device(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    _seed_device()
    task_id = "task-device-validate"
    _task_with_meta(env, task_id)
    client = TestClient(app)

    updated = client.patch(f"/api/v2/tasks/{task_id}/device-id", json={"device_id": EXISTING_DEVICE})
    assert updated.status_code == 200, updated.text
    assert updated.json()["device_id"] == EXISTING_DEVICE
    assert _customer_device(env, task_id) == EXISTING_DEVICE

    rejected = client.patch(f"/api/v2/tasks/{task_id}/device-id", json={"device_id": "NOT-EXIST"})
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["code"] == "device_not_found"
    assert "设备台账" in rejected.json()["message"]
    # 拒绝后任务记录保持拒绝前的值，不落库、不改现场。
    assert _customer_device(env, task_id) == EXISTING_DEVICE
    again = client.get(f"/api/v2/tasks/{task_id}")
    assert again.status_code == 200
    assert again.json()["system"]["customer"]["device_id"] == EXISTING_DEVICE


def test_device_removed_from_ledger_keeps_historical_task_value(tmp_path, monkeypatch) -> None:
    """边界：任务创建后设备从台账删除，历史任务保留已记录的值、读取不受影响。"""
    env = setup_env(tmp_path, monkeypatch)
    _seed_device()
    task_id = "task-device-stale"
    _task_with_meta(env, task_id, device_id=EXISTING_DEVICE)
    client = TestClient(app)

    with session_factory() as session:
        device = session.get(InventoryDevice, EXISTING_DEVICE)
        assert device is not None
        session.delete(device)
        session.commit()

    # 读取路径不查台账：历史任务仍返回已记录的值。
    detail = client.get(f"/api/v2/tasks/{task_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["system"]["customer"]["device_id"] == EXISTING_DEVICE
    assert _customer_device(env, task_id) == EXISTING_DEVICE

    # 手动再次指定已失效的 ID 仍按 FR-010 拒绝，任务既有值保持不变。
    rejected = client.patch(f"/api/v2/tasks/{task_id}/device-id", json={"device_id": EXISTING_DEVICE})
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["code"] == "device_not_found"
    assert _customer_device(env, task_id) == EXISTING_DEVICE


def test_update_device_id_empty_value_clears_without_inventory_check(tmp_path, monkeypatch) -> None:
    env = setup_env(tmp_path, monkeypatch)
    task_id = "task-device-clear"
    _task_with_meta(env, task_id, device_id=EXISTING_DEVICE)
    client = TestClient(app)

    cleared = client.patch(f"/api/v2/tasks/{task_id}/device-id", json={"device_id": "   "})
    assert cleared.status_code == 200, cleared.text
    assert not cleared.json()["device_id"]
    assert not _customer_device(env, task_id)


def test_reserve_rejects_unknown_device_id_without_creating_task(tmp_path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    _seed_device()

    with pytest.raises(TaskDeviceIdError) as excinfo:
        task_service.reserve("manual-device.zip", None, "江苏", "移动", None, device_id="NOT-EXIST")
    assert excinfo.value.code == "device_not_found"
    assert excinfo.value.status_code == 400

    task_id = generate_task_id("manual-device.zip")
    assert task_service.exists(task_id) is False
    assert not (settings.uploads / task_id).exists()
    assert not (settings.output / task_id).exists()
    with session_factory() as session:
        assert session.get(TaskRecord, task_id) is None

    created = task_service.reserve("manual-device.zip", None, "江苏", "移动", None, device_id=f"  {EXISTING_DEVICE}  ")
    with session_factory() as session:
        record = session.get(TaskRecord, created.task_id)
    assert record is not None
    assert record.customer["device_id"] == EXISTING_DEVICE
