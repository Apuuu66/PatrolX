"""全量任务与台账生命周期测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.db import InventoryObservation, InventoryParseResult, session_factory
from app.models.schemas import PackageKind, TaskMode, TaskStatus, TaskTrigger
from tests.fixtures.inventory.builder import make_inventory_zip, make_log_supplement_zip


@pytest.fixture(autouse=True)
def _clean_inventory() -> None:
    from app.models.db import InventoryChangeAudit, InventoryDevice

    with session_factory() as session:
        for model in (InventoryChangeAudit, InventoryObservation, InventoryParseResult, InventoryDevice):
            session.query(model).delete()
        session.commit()


def test_full_run_archives_inventory(tmp_path: Path) -> None:
    from app.cli import run_task

    package = tmp_path / "inventory-package.zip"
    make_inventory_zip(package)
    task = run_task(
        package,
        name="台账任务",
        customer={"province": "江苏", "operator": "移动", "product": "UMF2020"},
        task_id="task-flow-ok",
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
        package_kind=PackageKind.INSPECTION,
    )
    assert task.status == TaskStatus.COMPLETED
    assert task.package_kind == PackageKind.INSPECTION
    assert task.inventory is not None
    assert task.inventory.status.value == "archived"
    with session_factory() as session:
        observation = session.query(InventoryObservation).filter(InventoryObservation.task_id == "task-flow-ok").one()
        assert observation.device_name == "NJ-AGG-001"


def test_log_supplement_does_not_archive(tmp_path: Path) -> None:
    from app.cli import run_task

    package = tmp_path / "logs-only.zip"
    make_log_supplement_zip(package, include_lst_me=True)
    task = run_task(
        package,
        name="日志补充包",
        task_id="task-flow-log",
        mode=TaskMode.LOCAL,
        trigger=TaskTrigger.CLI,
        package_kind=PackageKind.LOG_SUPPLEMENT,
    )
    assert task.status == TaskStatus.COMPLETED
    assert task.inventory is not None
    assert task.inventory.status.value == "not_applicable"
    with session_factory() as session:
        assert session.query(InventoryObservation).filter(InventoryObservation.task_id == "task-flow-log").count() == 0
