"""设备台账删除维护 API 集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime
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


def _seed_device(
    *,
    device_id: str = "js-nj-agg-001",
    device_name: str = "NJ-AGG-001",
    province: str = "江苏",
    operator: str = "移动",
) -> None:
    from app.models.db import InventoryDevice, session_factory

    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            InventoryDevice(
                device_id=device_id,
                device_key=device_name.lower(),
                province=province,
                current_device_name=device_name,
                current_site_key=f"{province}|{operator}",
                current_operator=operator,
                current_version_raw="V900R016C10SPC200",
                current_version_observed_at=now,
                current_version_task_id="task-current",
                first_seen_at=now,
                last_seen_at=now,
                latest_task_id="task-current",
                latest_status="archived",
                observation_count=1,
                site_change_count=0,
                has_site_conflict=False,
                remark="待复核",
                created_by="task",
                updated_by="task",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_manual_create_and_update_are_not_supported() -> None:
    _seed_device()
    created = client.post(
        "/api/v2/inventory/devices",
        json={"province": "江苏", "operator": "移动", "device_name": "NJ-MANUAL-001"},
    )
    updated = client.patch(f"/api/v2/inventory/devices/{'js-nj-agg-001'}", json={"remark": "新备注"})

    assert created.status_code == 405
    assert updated.status_code == 405
    assert client.get("/api/v2/inventory/devices").json()["total"] == 1


def test_delete_requires_admin() -> None:
    from app.models.db import AuthSession
    from app.services.auth import get_current_user

    _seed_device()
    app.dependency_overrides[get_current_user] = lambda: AuthSession(token="viewer", username="viewer", role="viewer")
    try:
        response = client.delete("/api/v2/inventory/devices/js-nj-agg-001")
        assert response.status_code == 403
    finally:
        app.dependency_overrides[get_current_user] = lambda: AuthSession(
            token="integration-test-token", username="integration-admin", role="admin"
        )


def test_delete_removes_all_ledger_rows(tmp_path: Path) -> None:
    _seed_device()
    deleted = client.delete("/api/v2/inventory/devices/js-nj-agg-001")
    assert deleted.status_code == 204
    assert client.get("/api/v2/inventory/devices/js-nj-agg-001").status_code == 404

    from app.models.db import InventoryChangeAudit, InventoryDevice, InventoryObservation, session_factory

    with session_factory() as session:
        assert session.query(InventoryDevice).count() == 0
        assert session.query(InventoryObservation).count() == 0
        assert session.query(InventoryChangeAudit).count() == 1
        assert session.query(InventoryChangeAudit).first().action == "delete"


def test_deleted_device_is_recreated_by_task(tmp_path: Path) -> None:
    _seed_device()
    assert client.delete("/api/v2/inventory/devices/js-nj-agg-001").status_code == 204

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
