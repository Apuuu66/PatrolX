"""台账持久化服务测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models.db import (
    InventoryChangeAudit,
    InventoryDevice,
    InventoryObservation,
    InventoryParseResult,
    session_factory,
)
from app.services.inventory.ledger import archive_inventory, load_evidence
from app.services.inventory.parser import parse_inventory


@pytest.fixture()
def task_dir(tmp_path: Path) -> Path:
    with session_factory() as session:
        for model in (InventoryChangeAudit, InventoryObservation, InventoryParseResult, InventoryDevice):
            session.query(model).delete()
        session.commit()
    (tmp_path / "config").mkdir()
    return tmp_path


def _write_source(task_dir: Path, content: str) -> None:
    (task_dir / "config" / "LST ME.txt").write_text(content, encoding="utf-8")


def test_archive_creates_unique_observation_and_device(task_dir: Path) -> None:
    _write_source(task_dir, "NE name: Device-A\nSoftware version: V2\n")
    evidence = parse_inventory(task_dir, task_id="task-1", province="江苏", operator="移动")
    completed_at = datetime.now(UTC)
    archived = archive_inventory(evidence, task_id="task-1", package_kind="inspection", completed_at=completed_at)
    assert archived["status"] == "archived"
    assert load_evidence("task-1")["device"]["normalized_name"] == "Device-A"

    with session_factory() as session:
        observations = session.query(InventoryObservation).all()
        assert len(observations) == 1
        assert observations[0].version_status == "ok"
        assert observations[0].device_name == "Device-A"


def test_archive_rerun_overwrites_and_audits_once(task_dir: Path) -> None:
    first_time = datetime.now(UTC)
    _write_source(task_dir, "NE name: Device-A\nSoftware version: V2\n")
    evidence = parse_inventory(task_dir, task_id="task-1", province="江苏", operator="移动")
    archive_inventory(evidence, task_id="task-1", package_kind="inspection", completed_at=first_time)

    second_time = first_time + timedelta(hours=1)
    _write_source(task_dir, "NE name: Device-A\nSoftware version: V3\n")
    evidence = parse_inventory(task_dir, task_id="task-1", province="江苏", operator="移动")
    first = archive_inventory(evidence, task_id="task-1", package_kind="inspection", completed_at=second_time)
    assert first["status"] == "archived"
    assert first["audits"] == ["update"]
    repeat = archive_inventory(evidence, task_id="task-1", package_kind="inspection", completed_at=second_time)
    assert repeat["audits"] == []

    with session_factory() as session:
        observations = session.query(InventoryObservation).all()
        assert len(observations) == 1
        assert observations[0].raw_version == "V3"


def test_archive_missing_site_does_not_archive(task_dir: Path) -> None:
    _write_source(task_dir, "NE name: Device-A\n")
    evidence = parse_inventory(task_dir, task_id="task-2", province=None, operator=None)
    result = archive_inventory(evidence, task_id="task-2", package_kind="inspection", completed_at=datetime.now(UTC))
    assert result["status"] == "not_archived"
    assert result["archived"] is False
    with session_factory() as session:
        assert session.query(InventoryObservation).count() == 0


def test_archive_device_conflict_retires_existing_observation(task_dir: Path) -> None:
    base_time = datetime.now(UTC)
    _write_source(task_dir, "NE name: Device-A\nSoftware version: V1\n")
    evidence = parse_inventory(task_dir, task_id="task-3", province="江苏", operator="移动")
    archive_inventory(evidence, task_id="task-3", package_kind="inspection", completed_at=base_time)

    _write_source(task_dir, "NE name: Device-A\nNE name: Device-B\n")
    evidence = parse_inventory(task_dir, task_id="task-3", province="江苏", operator="移动")
    result = archive_inventory(evidence, task_id="task-3", package_kind="inspection", completed_at=base_time)
    assert result["status"] == "not_archived"
    assert result["audits"] == ["retire"]
    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        assert observation.status == "retired"


def test_log_supplement_does_not_touch_ledger(task_dir: Path) -> None:
    evidence = parse_inventory(
        task_dir,
        task_id="task-log",
        province=None,
        operator=None,
        package_kind="log_supplement",
    )
    result = archive_inventory(
        evidence,
        task_id="task-log",
        package_kind="log_supplement",
        completed_at=datetime.now(UTC),
    )
    assert result["status"] == "not_applicable"
    with session_factory() as session:
        assert session.query(InventoryObservation).count() == 0
