"""台账 API 集成测试。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli import run_task
from app.main import app
from app.models.schemas import TaskMode, TaskTrigger
from tests.fixtures.inventory.builder import (
    lst_me_content,
    make_inventory_zip,
    make_log_supplement_zip,
)

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


def _wait(task_id: str) -> dict:
    for _ in range(300):
        response = client.get(f"/api/v2/tasks/{task_id}")
        if response.status_code == 200 and response.json()["status"] in {"completed", "failed"}:
            return response.json()
        time.sleep(0.05)
    raise TimeoutError(task_id)


def _create_v3(path: Path, **data: str) -> str:
    with path.open("rb") as fh:
        response = client.post(
            "/api/v3/tasks",
            files={"package_file": (path.name, fh, "application/zip")},
            data=data,
        )
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def test_v3_inspection_and_inventory_endpoints(tmp_path: Path) -> None:
    package = tmp_path / "inventory-api.zip"
    make_inventory_zip(package)
    task_id = _create_v3(
        package,
        package_kind="inspection",
        name="台账 API",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    task = _wait(task_id)
    assert task["status"] == "completed"
    assert task["package_kind"] == "inspection"
    assert task["inventory"]["status"] == "archived"

    devices = client.get("/api/v2/inventory/devices", params={"province": "江苏", "operator": "移动"}).json()
    assert devices["total"] == 1
    device = devices["items"][0]
    assert device["device_name"] == "NJ-AGG-001"
    assert device["current_version"] == "V900R016C10SPC200"
    assert device["site_key"] == "江苏:移动"

    detail = client.get(f"/api/v2/inventory/devices/{device['device_id']}").json()
    assert detail["device_id"] == device["device_id"]
    observations = client.get(f"/api/v2/inventory/devices/{device['device_id']}/observations").json()
    assert observations["total"] == 1
    history = client.get(f"/api/v2/inventory/devices/{device['device_id']}/version-history").json()
    assert history["items"][0]["direction"] is None


def test_v3_log_supplement_validation_and_not_applicable(tmp_path: Path) -> None:
    package = tmp_path / "log-api.zip"
    make_log_supplement_zip(package)
    with package.open("rb") as fh:
        rejected = client.post(
            "/api/v3/tasks",
            files={"package_file": ("bad-log.zip", fh, "application/zip")},
            data={"package_kind": "log_supplement", "province": "江苏", "operator": "移动"},
        )
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "metadata_not_applicable"

    task_id = _create_v3(package, package_kind="log_supplement", name="日志 API")
    task = _wait(task_id)
    assert task["inventory"]["status"] == "not_applicable"
    assert client.get("/api/v2/inventory/devices").json()["total"] == 0
    assert client.get("/api/v2/inventory/quality-issues").json()["total"] == 0


def test_cli_and_api_inventory_semantics_are_consistent(tmp_path: Path) -> None:
    cli_package = tmp_path / "inventory-cli-consistency.zip"
    make_inventory_zip(cli_package)
    cli_task = run_task(
        cli_package,
        name="CLI 台账一致性",
        customer={"province": "江苏", "operator": "移动", "product": "UMF2020"},
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
    )
    assert cli_task.inventory is not None
    assert cli_task.inventory.status == "archived"

    api_package = tmp_path / "inventory-api-consistency.zip"
    make_inventory_zip(api_package)
    task_id = _create_v3(
        api_package,
        package_kind="inspection",
        name="API 台账一致性",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    api_task = _wait(task_id)
    cli_inventory = cli_task.inventory
    api_inventory = api_task["inventory"]
    assert api_inventory["status"] == "archived"
    assert api_inventory["site"]["province"] == cli_inventory.site.province
    assert api_inventory["site"]["operator"] == cli_inventory.site.operator
    assert api_inventory["site"]["site_key"] == cli_inventory.site.site_key
    assert api_inventory["device"]["raw_names"] == cli_inventory.device.raw_names
    assert api_inventory["device"]["normalized_name"] == cli_inventory.device.normalized_name
    assert api_inventory["version"]["raw_version"] == cli_inventory.version.raw_version
    assert api_inventory["source_files"] == cli_inventory.source_files
    assert api_inventory["archived"]["archived"] == cli_inventory.archived.archived
    assert api_inventory["archived"]["device_id"] == cli_inventory.archived.device_id


def test_version_history_and_quality_issues(tmp_path: Path) -> None:
    package = tmp_path / "history.zip"
    make_inventory_zip(package)
    first = _create_v3(
        package,
        package_kind="inspection",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    _wait(first)

    second_package = tmp_path / "history-2.zip"
    make_inventory_zip(second_package, content=lst_me_content(version="V900R016C10SPC199"))
    second = _create_v3(
        second_package,
        package_kind="inspection",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    _wait(second)
    assert client.get("/api/v2/inventory/devices").json()["total"] == 1
    history = client.get("/api/v2/inventory/devices").json()["items"][0]["device_id"]
    points = client.get(f"/api/v2/inventory/devices/{history}/version-history").json()["items"]
    assert [point["direction"] for point in points] == [None, "downgrade"]

    missing_package = tmp_path / "missing-version.zip"
    make_inventory_zip(missing_package, content=lst_me_content(version=None))
    missing = _create_v3(
        missing_package,
        package_kind="inspection",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    _wait(missing)
    quality = client.get("/api/v2/inventory/quality-issues", params={"issue_type": "missing_version"}).json()
    assert quality["total"] == 1
    assert quality["items"][0]["task_id"] == missing
