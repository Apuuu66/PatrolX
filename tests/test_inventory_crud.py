"""设备台账维护 API 集成测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.fixtures.inventory.builder import make_inventory_zip

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_inventory() -> None:
    from app.models.db import (
        InventoryChangeAudit,
        InventoryDevice,
        InventoryObservation,
        InventoryParseResult,
        session_factory,
    )

    with session_factory() as session:
        for model in (InventoryChangeAudit, InventoryObservation, InventoryParseResult, InventoryDevice):
            session.query(model).delete()
        session.commit()


def _create_device(**overrides: str) -> dict:
    payload = {
        "province": "江苏",
        "operator": "移动",
        "device_name": "NJ-MANUAL-001",
        "remark": "新装机",
    }
    payload.update(overrides)
    response = client.post("/api/v2/inventory/devices", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_manual_device() -> None:
    device = _create_device()
    assert device["device_name"] == "NJ-MANUAL-001"
    assert device["operator"] == "移动"
    assert device["current_version"] is None
    assert device["remark"] == "新装机"
    assert device["created_by"] == "integration-admin"

    detail = client.get(f"/api/v2/inventory/devices/{device['device_id']}")
    assert detail.status_code == 200
    assert detail.json()["device_id"] == device["device_id"]


def test_create_duplicate_device_returns_conflict() -> None:
    _create_device()
    response = client.post(
        "/api/v2/inventory/devices",
        json={
            "province": "江苏",
            "operator": "电信",
            "device_name": "NJ-MANUAL-001",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "device_already_exists"


def test_create_requires_admin() -> None:
    from app.models.db import AuthSession
    from app.services.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: AuthSession(token="viewer", username="viewer", role="viewer")
    try:
        response = client.post(
            "/api/v2/inventory/devices",
            json={"province": "江苏", "operator": "移动", "device_name": "NO-ACCESS"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: AuthSession(
            token="integration-test-token", username="integration-admin", role="admin"
        )


def test_update_remark_and_delete_removes_all_ledger_rows(tmp_path: Path) -> None:
    device = _create_device()
    updated = client.patch(f"/api/v2/inventory/devices/{device['device_id']}", json={"remark": "待复核"})
    assert updated.status_code == 200
    assert updated.json()["remark"] == "待复核"
    assert updated.json()["updated_by"] == "integration-admin"

    deleted = client.delete(f"/api/v2/inventory/devices/{device['device_id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v2/inventory/devices/{device['device_id']}").status_code == 404

    from app.models.db import InventoryChangeAudit, InventoryDevice, InventoryObservation, session_factory

    with session_factory() as session:
        assert session.query(InventoryDevice).count() == 0
        assert session.query(InventoryObservation).count() == 0
        assert session.query(InventoryChangeAudit).count() == 1
        assert session.query(InventoryChangeAudit).first().action == "delete"


def test_deleted_device_is_recreated_by_task(tmp_path: Path) -> None:
    device = _create_device()
    assert client.delete(f"/api/v2/inventory/devices/{device['device_id']}").status_code == 204

    package = tmp_path / "deleted-recreate.zip"
    make_inventory_zip(package)
    with package.open("rb") as fh:
        created = client.post(
            "/api/v3/tasks",
            files={"package_file": (package.name, fh, "application/zip")},
            data={
                "package_kind": "inspection",
                "province": "江苏",
                "operator": "移动",
                "product": "UMF2020",
            },
        )
    assert created.status_code == 202
    task_id = created.json()["task_id"]
    for _ in range(300):
        task = client.get(f"/api/v2/tasks/{task_id}")
        if task.status_code == 200 and task.json()["status"] in {"completed", "failed"}:
            break
        import time

        time.sleep(0.05)
    else:
        raise TimeoutError(task_id)
    assert client.get("/api/v2/inventory/devices").json()["total"] == 1
