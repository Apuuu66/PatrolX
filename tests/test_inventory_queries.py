"""台账查询投影测试：版本历史按执行时间稳定呈现演进轨迹。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.db import (
    InventoryChangeAudit,
    InventoryDevice,
    InventoryObservation,
    InventoryParseResult,
    session_factory,
)
from app.services.inventory.ledger import archive_inventory
from app.services.inventory.parser import parse_inventory
from app.services.inventory.queries import get_version_history, list_observations
from tests.fixtures.inventory.builder import lst_me_content


@pytest.fixture()
def clean_inventory_db() -> None:
    with session_factory() as session:
        for model in (InventoryChangeAudit, InventoryObservation, InventoryParseResult, InventoryDevice):
            session.query(model).delete()
        session.commit()


def _archive_observation(
    task_dir: Path,
    *,
    task_id: str,
    header_time: str,
    version: str | None,
    completed_at: datetime,
) -> None:
    config_dir = task_dir / task_id / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "LST ME.txt").write_bytes(lst_me_content(version=version, header_time=header_time))
    evidence = parse_inventory(
        task_dir / task_id,
        task_id=task_id,
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    result = archive_inventory(
        evidence,
        task_id=task_id,
        package_kind="inspection",
        completed_at=completed_at,
    )
    assert result["status"] == "archived"


def test_version_history_uses_execution_time_and_marks_direction_and_gap(
    tmp_path: Path,
    clean_inventory_db: None,
) -> None:
    """乱序入库后仍按执行时间升序，方向与缺口不受上传顺序影响。"""
    completed_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    observations = [
        ("task-c", "2025-05-22  10:00:00", None),
        ("task-a", "2025-05-20  10:00:00", "V1"),
        ("task-e", "2025-05-24  10:00:00", "V1"),
        ("task-b", "2025-05-21  10:00:00", "V2"),
        ("task-d", "2025-05-23  10:00:00", "V2"),
    ]
    for task_id, header_time, version in observations:
        _archive_observation(
            tmp_path,
            task_id=task_id,
            header_time=header_time,
            version=version,
            completed_at=completed_at,
        )

    with session_factory() as session:
        device = session.query(InventoryDevice).one()
        points, total = get_version_history(session, device.device_id, page=1, page_size=10)
        listed, listed_total = list_observations(session, device.device_id, page=1, page_size=10, order="asc")

    assert total == 5
    assert [point.task_id for point in points] == ["task-a", "task-b", "task-c", "task-d", "task-e"]
    assert [point.direction for point in points] == [None, "upgrade", None, "unchanged", "downgrade"]
    assert [point.has_gap for point in points] == [False, False, True, True, False]
    assert [point.time_source for point in points] == ["lst_me"] * 5
    assert [point.observed_at.isoformat() for point in points] == [
        "2025-05-20T02:00:00+00:00",
        "2025-05-21T02:00:00+00:00",
        "2025-05-22T02:00:00+00:00",
        "2025-05-23T02:00:00+00:00",
        "2025-05-24T02:00:00+00:00",
    ]
    assert listed_total == 5
    assert [item.task_id for item in listed] == ["task-a", "task-b", "task-c", "task-d", "task-e"]
