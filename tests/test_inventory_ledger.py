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
from app.services.inventory.ledger import _recalculate_device, archive_inventory, load_evidence
from app.services.inventory.parser import parse_inventory
from app.services.inventory.queries import get_version_history
from tests.fixtures.inventory.builder import (
    HEADER_TIME_FUTURE,
    HEADER_TIME_INVALID,
    HEADER_TIME_SAMPLE,
    lst_me_content,
    multi_device_lst_me_content,
    tabular_lst_me_content,
)


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
    _write_source(task_dir, "NE name: Device-A\nME type: UMF2020\nSoftware version: V2\n")
    evidence = parse_inventory(task_dir, task_id="task-1", province="江苏", operator="移动", product="UMF2020")
    completed_at = datetime.now(UTC)
    archived = archive_inventory(evidence, task_id="task-1", package_kind="inspection", completed_at=completed_at)
    assert archived["status"] == "archived"
    assert load_evidence("task-1")["device"]["normalized_name"] == "Device-A"

    with session_factory() as session:
        observations = session.query(InventoryObservation).all()
        assert len(observations) == 1
        assert observations[0].version_status == "ok"
        assert observations[0].device_name == "Device-A"


def test_archive_tabular_lst_me_creates_observation_for_uploaded_product(task_dir: Path) -> None:
    _write_source(task_dir, tabular_lst_me_content().decode())
    evidence = parse_inventory(task_dir, task_id="task-tabular", province="江苏", operator="移动", product="csp")

    archived = archive_inventory(
        evidence,
        task_id="task-tabular",
        package_kind="inspection",
        completed_at=datetime.now(UTC),
    )

    assert archived["status"] == "archived"
    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        assert observation.device_name == "CSP-NE-001"
        assert observation.raw_version == "27.0.0.13"


def test_archive_rerun_overwrites_and_audits_once(task_dir: Path) -> None:
    first_time = datetime.now(UTC)
    _write_source(task_dir, "NE name: Device-A\nME type: UMF2020\nSoftware version: V2\n")
    evidence = parse_inventory(task_dir, task_id="task-1", province="江苏", operator="移动", product="UMF2020")
    archive_inventory(evidence, task_id="task-1", package_kind="inspection", completed_at=first_time)

    second_time = first_time + timedelta(hours=1)
    _write_source(task_dir, "NE name: Device-A\nME type: UMF2020\nSoftware version: V3\n")
    evidence = parse_inventory(task_dir, task_id="task-1", province="江苏", operator="移动", product="UMF2020")
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
    _write_source(task_dir, "NE name: Device-A\nME type: UMF2020\n")
    evidence = parse_inventory(task_dir, task_id="task-2", province=None, operator=None, product="UMF2020")
    result = archive_inventory(evidence, task_id="task-2", package_kind="inspection", completed_at=datetime.now(UTC))
    assert result["status"] == "not_archived"
    assert result["archived"] is False
    with session_factory() as session:
        assert session.query(InventoryObservation).count() == 0


def test_archive_rerun_with_multiple_devices_archives_each_device(task_dir: Path) -> None:
    base_time = datetime.now(UTC)
    _write_source(task_dir, "NE name: Device-A\nME type: UMF2020\nSoftware version: V1\n")
    evidence = parse_inventory(task_dir, task_id="task-3", province="江苏", operator="移动", product="UMF2020")
    archive_inventory(evidence, task_id="task-3", package_kind="inspection", completed_at=base_time)

    _write_source(
        task_dir,
        "NE name: Device-A\nME type: UMF2020\nSoftware version: V1\n"
        "NE name: Device-B\nME type: UMF2020\nSoftware version: V1\n",
    )
    evidence = parse_inventory(task_dir, task_id="task-3", province="江苏", operator="移动", product="UMF2020")
    result = archive_inventory(evidence, task_id="task-3", package_kind="inspection", completed_at=base_time)
    assert result["status"] == "archived"
    with session_factory() as session:
        observations = session.query(InventoryObservation).all()
        assert {item.device_name for item in observations} == {"Device-A", "Device-B"}


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


def test_archive_multiple_matching_devices(task_dir: Path) -> None:
    content = (
        b"NE name: Device-A\nME type: UMF2020\nSoftware version: V1\n"
        b"NE name: Device-B\nME type: UMF2020\nSoftware version: V2\n"
        b"NE name: Device-C\nME type: UMF2021\nSoftware version: V3\n"
    )
    _write_source(task_dir, content.decode())
    evidence = parse_inventory(task_dir, task_id="task-multi", province="江苏", operator="移动", product="UMF2020")
    result = archive_inventory(
        evidence,
        task_id="task-multi",
        package_kind="inspection",
        completed_at=datetime.now(UTC),
    )
    assert result["status"] == "archived"
    with session_factory() as session:
        observations = session.query(InventoryObservation).all()
        devices = session.query(InventoryDevice).all()
        assert {item.device_name for item in observations} == {"Device-A", "Device-B"}
        assert {item.current_device_name for item in devices} == {"Device-A", "Device-B"}
        assert {item.device_id for item in session.query(InventoryChangeAudit).all()} == {
            item.device_id for item in observations
        }


def test_archive_no_matching_filter_writes_evidence_but_not_ledger(task_dir: Path) -> None:
    _write_source(task_dir, "NE name: Device-A\nME type: UMF2021\nSoftware version: V1\n")
    evidence = parse_inventory(task_dir, task_id="task-filter", province="江苏", operator="移动", product="UMF2020")
    result = archive_inventory(
        evidence,
        task_id="task-filter",
        package_kind="inspection",
        completed_at=datetime.now(UTC),
    )
    assert result["status"] == "not_archived"
    assert result["archived"] is False
    with session_factory() as session:
        assert session.query(InventoryObservation).count() == 0


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _write_time_source(task_dir: Path, *, sub: str, header_time: str | None, version: str | None = "V1") -> None:
    directory = task_dir / "config" / sub
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "LST ME.txt").write_bytes(lst_me_content(version=version, header_time=header_time))


def _completed_at() -> datetime:
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def test_archive_uses_header_execution_time(task_dir: Path) -> None:
    _write_source(task_dir, lst_me_content(header_time=HEADER_TIME_SAMPLE).decode())
    completed_at = _completed_at()
    evidence = parse_inventory(
        task_dir,
        task_id="task-time",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    archive_inventory(evidence, task_id="task-time", package_kind="inspection", completed_at=completed_at)

    expected = datetime(2025, 5, 26, 6, 40, 36, tzinfo=UTC)
    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        device = session.query(InventoryDevice).one()
        assert _utc(observation.observed_at) == expected
        assert observation.time_source == "lst_me"
        assert observation.time_source_reason is None
        assert _utc(device.first_seen_at) == expected
        assert _utc(device.last_seen_at) == expected
        assert _utc(device.current_version_observed_at) == expected


def test_archive_falls_back_to_completed_at_with_reason(task_dir: Path) -> None:
    _write_source(task_dir, lst_me_content().decode())
    completed_at = _completed_at()
    evidence = parse_inventory(
        task_dir,
        task_id="task-time-fallback",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    archive_inventory(evidence, task_id="task-time-fallback", package_kind="inspection", completed_at=completed_at)

    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        assert _utc(observation.observed_at) == completed_at
        assert observation.time_source == "task"
        assert observation.time_source_reason == "header_time_missing"


@pytest.mark.parametrize(
    ("header_time", "expected_status", "expected_reason"),
    [
        (HEADER_TIME_INVALID, "invalid", "header_time_invalid"),
        (HEADER_TIME_FUTURE, "time_in_future", "time_in_future"),
    ],
)
def test_archive_untrusted_header_time_marks_reason(
    task_dir: Path,
    header_time: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    _write_source(task_dir, lst_me_content(header_time=header_time).decode())
    completed_at = _completed_at()
    evidence = parse_inventory(
        task_dir,
        task_id="task-time-untrusted",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    assert evidence["execution_time"]["per_file"][0]["status"] == expected_status
    archive_inventory(evidence, task_id="task-time-untrusted", package_kind="inspection", completed_at=completed_at)

    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        assert _utc(observation.observed_at) == completed_at
        assert observation.time_source == "task"
        assert observation.time_source_reason == expected_reason


def test_archive_multi_source_device_uses_recent_header_time(task_dir: Path) -> None:
    _write_time_source(task_dir, sub="site-a", header_time=HEADER_TIME_SAMPLE)
    _write_time_source(task_dir, sub="site-b", header_time="2025-05-27  09:00:00")
    completed_at = _completed_at()
    evidence = parse_inventory(
        task_dir,
        task_id="task-time-multi-source",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    archive_inventory(
        evidence,
        task_id="task-time-multi-source",
        package_kind="inspection",
        completed_at=completed_at,
    )

    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        assert _utc(observation.observed_at) == datetime(2025, 5, 27, 1, 0, 0, tzinfo=UTC)
        assert observation.time_source == "lst_me"


def test_archive_rerun_refreshes_time_fields(task_dir: Path) -> None:
    completed_at = _completed_at()
    _write_source(task_dir, lst_me_content(header_time=HEADER_TIME_SAMPLE).decode())
    evidence = parse_inventory(
        task_dir,
        task_id="task-time-rerun",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    archive_inventory(evidence, task_id="task-time-rerun", package_kind="inspection", completed_at=completed_at)

    _write_source(task_dir, lst_me_content().decode())
    evidence = parse_inventory(
        task_dir,
        task_id="task-time-rerun",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    archive_inventory(evidence, task_id="task-time-rerun", package_kind="inspection", completed_at=completed_at)

    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        assert _utc(observation.observed_at) == completed_at
        assert observation.time_source == "task"
        assert observation.time_source_reason == "header_time_missing"
        device = session.query(InventoryDevice).one()
        assert _utc(device.last_seen_at) == completed_at


def test_archive_legacy_evidence_without_execution_time_uses_completed_at(task_dir: Path) -> None:
    _write_source(task_dir, lst_me_content(header_time=HEADER_TIME_SAMPLE).decode())
    completed_at = _completed_at()
    evidence = parse_inventory(
        task_dir,
        task_id="task-time-legacy",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=completed_at,
    )
    evidence.pop("execution_time")
    archive_inventory(evidence, task_id="task-time-legacy", package_kind="inspection", completed_at=completed_at)

    with session_factory() as session:
        observation = session.query(InventoryObservation).one()
        assert _utc(observation.observed_at) == completed_at
        assert observation.time_source == "task"
        assert observation.time_source_reason is None


def test_archive_out_of_order_uploads_keep_latest_execution_version(task_dir: Path) -> None:
    late_execution = "2025-05-30  10:00:00"
    early_execution = "2025-05-20  10:00:00"
    late_observed = datetime(2025, 5, 30, 2, 0, 0, tzinfo=UTC)
    early_observed = datetime(2025, 5, 20, 2, 0, 0, tzinfo=UTC)

    _write_source(task_dir, lst_me_content(version="V2", header_time=late_execution).decode())
    late_evidence = parse_inventory(
        task_dir,
        task_id="task-late",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=datetime(2025, 5, 30, 3, 0, 0, tzinfo=UTC),
    )
    archive_inventory(
        late_evidence,
        task_id="task-late",
        package_kind="inspection",
        completed_at=datetime(2025, 5, 30, 3, 0, 0, tzinfo=UTC),
    )

    _write_source(task_dir, lst_me_content(version="V1", header_time=early_execution).decode())
    early_evidence = parse_inventory(
        task_dir,
        task_id="task-early",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=datetime(2025, 6, 5, 3, 0, 0, tzinfo=UTC),
    )
    archive_inventory(
        early_evidence,
        task_id="task-early",
        package_kind="inspection",
        completed_at=datetime(2025, 6, 5, 3, 0, 0, tzinfo=UTC),
    )

    with session_factory() as session:
        device = session.query(InventoryDevice).one()
        assert device.current_version_raw == "V2"
        assert device.current_version_task_id == "task-late"
        assert _utc(device.current_version_observed_at) == late_observed
        assert _utc(device.last_seen_at) == late_observed
        assert _utc(device.first_seen_at) == early_observed
        assert device.observation_count == 2

    with session_factory() as session:
        device_id = session.query(InventoryDevice).one().device_id
    history = get_version_history(device_id, page=1, page_size=10)[0]
    assert [point.raw_version for point in history] == ["V1", "V2"]
    assert [point.direction for point in history] == [None, "upgrade"]
    assert [point.time_source for point in history] == ["lst_me", "lst_me"]


def test_archive_same_execution_time_breaks_tie_by_task_id(task_dir: Path) -> None:
    header_time = "2025-05-26  14:40:36"
    for task_id, version in (("task-b", "V2"), ("task-a", "V1")):
        _write_source(task_dir, lst_me_content(version=version, header_time=header_time).decode())
        evidence = parse_inventory(
            task_dir,
            task_id=task_id,
            province="江苏",
            operator="移动",
            product="UMF2020",
            completed_at=_completed_at(),
        )
        archive_inventory(evidence, task_id=task_id, package_kind="inspection", completed_at=_completed_at())

    with session_factory() as session:
        device = session.query(InventoryDevice).one()
        assert device.current_version_raw == "V1"
        assert device.current_version_task_id == "task-a"

    with session_factory() as session:
        device = session.query(InventoryDevice).one()
        _recalculate_device(session, device, datetime.now(UTC))
        session.commit()
        assert device.current_version_task_id == "task-a"


def test_archive_newer_observation_without_version_keeps_current_version(task_dir: Path) -> None:
    _write_source(task_dir, lst_me_content(version="V1", header_time="2025-05-20  10:00:00").decode())
    evidence = parse_inventory(
        task_dir,
        task_id="task-with-version",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    archive_inventory(evidence, task_id="task-with-version", package_kind="inspection", completed_at=_completed_at())

    _write_source(task_dir, lst_me_content(version=None, header_time="2025-05-28  10:00:00").decode())
    evidence = parse_inventory(
        task_dir,
        task_id="task-without-version",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    archive_inventory(evidence, task_id="task-without-version", package_kind="inspection", completed_at=_completed_at())

    with session_factory() as session:
        device = session.query(InventoryDevice).one()
        assert device.current_version_raw == "V1"
        assert device.current_version_task_id == "task-with-version"
        assert _utc(device.last_seen_at) == datetime(2025, 5, 28, 2, 0, 0, tzinfo=UTC)
        assert device.observation_count == 2


def test_archive_version_conflict_does_not_change_current_version(task_dir: Path) -> None:
    _write_source(task_dir, lst_me_content(version="V1", header_time="2025-05-20  10:00:00").decode())
    evidence = parse_inventory(
        task_dir,
        task_id="task-baseline",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    archive_inventory(evidence, task_id="task-baseline", package_kind="inspection", completed_at=_completed_at())

    payload = multi_device_lst_me_content(
        [
            {"device_name": "NJ-AGG-001", "network_element_type": "UMF2020", "version": "V2"},
            {"device_name": "NJ-AGG-001", "network_element_type": "UMF2020", "version": "V3"},
        ],
        header_time="2025-05-28  10:00:00",
    )
    (task_dir / "config" / "LST ME.txt").write_bytes(payload)
    evidence = parse_inventory(
        task_dir,
        task_id="task-conflict",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    assert evidence["not_archived_reason"] == "matched_device_version_conflict"
    result = archive_inventory(
        evidence,
        task_id="task-conflict",
        package_kind="inspection",
        completed_at=_completed_at(),
    )
    assert result["archived"] is False

    with session_factory() as session:
        assert session.query(InventoryObservation).count() == 1
        device = session.query(InventoryDevice).one()
        assert device.current_version_raw == "V1"
        assert device.current_version_task_id == "task-baseline"
        assert device.observation_count == 1
