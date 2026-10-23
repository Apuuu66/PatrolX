"""台账解析器契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.inventory.parser import parse_inventory
from tests.fixtures.inventory.builder import (
    HEADER_TIME_FUTURE,
    HEADER_TIME_INVALID,
    HEADER_TIME_SAMPLE,
    LST_ME_FILENAME,
    header_time_line,
    lst_me_content,
    make_inventory_zip,
    multi_device_lst_me_content,
)


@pytest.fixture()
def task_dir(tmp_path: Path) -> Path:
    package = tmp_path / "package.zip"
    make_inventory_zip(package)
    extracted = tmp_path / "data"
    extracted.mkdir()
    (extracted / "config").mkdir()
    (extracted / "config" / LST_ME_FILENAME).write_bytes(lst_me_content())
    return extracted


def test_parse_success_and_normalization(task_dir: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    evidence = parse_inventory(task_dir, task_id="task-ok", province="江苏 ", operator="移动", product="UMF2020")
    assert evidence["status"] == "archived"
    assert evidence["site"] == {
        "status": "ok",
        "source": "upload_metadata",
        "province": "江苏",
        "operator": "移动",
        "site_key": "江苏:移动",
    }
    assert evidence["device"]["status"] == "ok"
    assert evidence["device"]["normalized_name"] == "NJ-AGG-001"
    assert evidence["version"]["status"] == "ok"
    assert evidence["version"]["raw_version"] == "V900R016C10SPC200"
    assert evidence["source_files"] == [f"config/{LST_ME_FILENAME}"]


def test_parse_field_aliases_and_repeated_values(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    content = (
        "ME name: A B\nME type: UMF2020\nNE name: A B\nME type: UMF2020\n"
        "ME name: A B\nME type: UMF2020\nSW version: V1\n软件版本: V1\n"
    ).encode()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(tmp_path, task_id="task-alias", province="江苏", operator="电信", product="UMF2020")
    assert evidence["status"] == "archived"
    assert evidence["device"]["normalized_name"] == "A B"
    assert evidence["version"]["raw_version"] == "V1"


def test_parse_gb18030_and_case_insensitive_path(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    (tmp_path / "config" / "nested").mkdir(parents=True)
    path = tmp_path / "config" / "nested" / "lst me.txt"
    path.write_bytes(lst_me_content(device_name="南京汇聚", version="V900R016", encoding="gb18030"))
    evidence = parse_inventory(tmp_path, task_id="task-gb", province="江苏", operator="联通", product="UMF2020")
    assert evidence["device"]["normalized_name"] == "南京汇聚"
    assert evidence["version"]["raw_version"] == "V900R016"


def test_parse_missing_version_archives_device(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(lst_me_content(version=None))
    evidence = parse_inventory(
        tmp_path,
        task_id="task-missing-version",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["status"] == "archived"
    assert evidence["version"]["status"] == "missing"
    assert evidence["archived"]["archived"] is True


def test_parse_version_conflict(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    content = b"NE name: Device-A\nME type: UMF2020\nSoftware version: V2\nSoftware version: V1\n"
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(
        tmp_path,
        task_id="task-version-conflict",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["status"] == "not_archived"
    assert evidence["not_archived_reason"] == "matched_device_version_conflict"
    assert evidence["version"]["status"] == "conflict"
    assert evidence["version"]["candidates"] == ["V2", "V1"]


def test_parse_multiple_matching_devices_have_legacy_multiple_status(tmp_path: Path) -> None:
    content = (
        b"NE name: Device-A\nME type: UMF2020\nSoftware version: V1\n"
        b"NE name: Device-B\nME type: UMF2020\nSoftware version: V1\n"
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(
        tmp_path,
        task_id="task-multi-legacy",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["status"] == "archived"
    assert evidence["device"]["status"] == "matched_multiple"
    assert evidence["device"]["normalized_name"] is None
    assert evidence["archived"]["archived"] is True


def test_parse_missing_file_and_site(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    evidence = parse_inventory(tmp_path, task_id="task-missing-file", province=None, operator=None)
    assert evidence["status"] == "not_archived"
    assert evidence["site"]["status"] == "missing"
    assert evidence["device"]["status"] == "missing"
    assert evidence["device"]["reason_code"] == "source_file_missing"
    assert evidence["not_archived_reason"] == "missing_site"


def test_parse_decode_failure_is_structured(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(b"\xff\xfe\x00bad")
    evidence = parse_inventory(tmp_path, task_id="task-decode", province="江苏", operator="移动", product="UMF2020")
    assert evidence["status"] == "failed"
    assert evidence["device"]["status"] == "error"
    assert evidence["errors"]


def test_log_supplement_is_not_applicable(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    evidence = parse_inventory(
        tmp_path,
        task_id="task-log",
        province=None,
        operator=None,
        package_kind="log_supplement",
    )
    assert evidence["status"] == "not_applicable"
    assert evidence["site"]["status"] == "not_applicable"
    assert evidence["device"]["status"] == "not_applicable"
    assert evidence["version"]["status"] == "not_applicable"
    assert evidence["not_applicable_reason"] == "log_supplement_package"
    assert evidence["archived"]["reason"] == "not_applicable"


def _multi_content() -> bytes:
    from tests.fixtures.inventory.builder import multi_device_lst_me_content

    return multi_device_lst_me_content(
        [
            {"device_name": "NJ-AGG-001", "network_element_type": "UMF2020", "version": "V1"},
            {"device_name": "NJ-AGG-002", "network_element_type": "UMF2020", "version": "V2"},
            {"device_name": "NJ-AGG-003", "network_element_type": "UMF2021", "version": "V3"},
        ]
    )


def test_parse_multiple_devices_filters_by_network_element_type(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(_multi_content())
    evidence = parse_inventory(tmp_path, task_id="task-multi", province="江苏", operator="移动", product=" UMF2020 ")
    assert evidence["parser_version"] == "4"
    assert evidence["schema_version"] == 3
    assert evidence["status"] == "archived"
    assert evidence["network_element_type_filter"] == {
        "requested": "UMF2020",
        "normalized": "UMF2020",
        "status": "ok",
        "matched_count": 2,
        "unmatched_count": 1,
    }
    assert [item["normalized_name"] for item in evidence["devices"]] == ["NJ-AGG-001", "NJ-AGG-002"]
    # 只识别所选网元类型：不匹配的记录不进入任务证据明细，仅保留数量。
    assert [item["normalized_name"] for item in evidence["records"]] == ["NJ-AGG-001", "NJ-AGG-002"]
    assert [item["matched"] for item in evidence["records"]] == [True, True]
    assert len(evidence["archived"]["devices"]) == 2
    assert evidence["archived"]["device_id"] is None


def test_parse_missing_network_element_type_filter_does_not_archive(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(_multi_content())
    evidence = parse_inventory(tmp_path, task_id="task-no-filter", province="江苏", operator="移动")
    assert evidence["status"] == "not_archived"
    assert evidence["not_archived_reason"] == "network_element_type_filter_missing"
    assert evidence["devices"] == []
    assert evidence["records"] == []
    assert evidence["network_element_type_filter"]["status"] == "missing"


def test_parse_no_matching_network_element_type_does_not_archive(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(_multi_content())
    evidence = parse_inventory(tmp_path, task_id="task-no-match", province="江苏", operator="移动", product="UMF9999")
    assert evidence["status"] == "not_archived"
    assert evidence["not_archived_reason"] == "network_element_type_no_match"
    assert evidence["devices"] == []
    assert evidence["records"] == []
    assert evidence["network_element_type_filter"]["status"] == "no_match"
    assert evidence["network_element_type_filter"]["unmatched_count"] == 3


def test_parse_duplicate_same_device_with_same_version_is_deduplicated(tmp_path: Path) -> None:
    content = (
        b"NE name: Device-A\nME type: UMF2020\nSoftware version: V1\n"
        b"\nNE name: Device-A\nME type: UMF2020\nSoftware version: V1\n"
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(
        tmp_path,
        task_id="task-duplicate",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["status"] == "archived"
    assert len(evidence["records"]) == 2
    assert len(evidence["devices"]) == 1
    assert len(evidence["archived"]["devices"]) == 1


def test_parse_duplicate_same_device_with_conflicting_versions_is_not_ledger_archived(tmp_path: Path) -> None:
    content = (
        b"NE name: Device-A\nME type: UMF2020\nSoftware version: V1\n"
        b"\nNE name: Device-A\nME type: UMF2020\nSoftware version: V2\n"
    )
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(
        tmp_path,
        task_id="task-version-duplicate",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["status"] == "not_archived"
    assert evidence["not_archived_reason"] == "matched_device_version_conflict"
    assert len(evidence["devices"]) == 1
    assert evidence["devices"][0]["version"]["status"] == "conflict"
    assert evidence["version"]["status"] == "conflict"
    assert evidence["archived"]["archived"] is False


def test_parse_orphan_fields_do_not_stop_valid_records(tmp_path: Path) -> None:
    content = b"ME type: UMF2020\nSoftware version: V0\nNE name: Device-A\nME type: UMF2020\nSoftware version: V1\n"
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(
        tmp_path,
        task_id="task-orphan",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["status"] == "archived"
    assert evidence["devices"][0]["normalized_name"] == "Device-A"
    assert any(
        item.get("reason_code") == "orphan_record_field" and item.get("recoverable") for item in evidence["errors"]
    )


def _write_source(task_dir: Path, payload: bytes, *, name: str = LST_ME_FILENAME, sub: str = "config") -> None:
    directory = task_dir / sub
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(payload)


def _completed_at() -> datetime:
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def test_parse_header_time_is_converted_to_utc(tmp_path: Path) -> None:
    _write_source(tmp_path, lst_me_content(header_time=HEADER_TIME_SAMPLE))
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    execution = evidence["execution_time"]
    assert execution["status"] == "ok"
    assert execution["source"] == "lst_me"
    assert execution["per_file"] == [
        {
            "source_file": f"config/{LST_ME_FILENAME}",
            "raw_text": header_time_line(HEADER_TIME_SAMPLE),
            "line": 1,
            "parsed_at": "2025-05-26T06:40:36+00:00",
            "status": "ok",
            "reason": None,
        }
    ]
    assert evidence["schema_version"] == 3
    assert evidence["parser_version"] == "4"


def test_parse_header_time_after_noise_line_and_tabs(tmp_path: Path) -> None:
    payload = lst_me_content(
        header_lines=["%%LST ME:;%%", "RETCODE = 0  操作成功"],
        header_time="2025-05-26\t14:40:36",
    )
    _write_source(tmp_path, payload)
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-noise",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    entry = evidence["execution_time"]["per_file"][0]
    assert entry["line"] == 3
    assert entry["status"] == "ok"
    assert entry["parsed_at"] == "2025-05-26T06:40:36+00:00"
    assert evidence["device"]["status"] == "ok"


def test_parse_header_time_missing_falls_back(tmp_path: Path) -> None:
    _write_source(tmp_path, lst_me_content())
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-missing",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    execution = evidence["execution_time"]
    assert execution["status"] == "missing"
    assert execution["source"] == "task"
    assert execution["per_file"][0]["raw_text"] is None
    assert execution["per_file"][0]["line"] is None
    assert execution["per_file"][0]["parsed_at"] is None
    assert execution["per_file"][0]["status"] == "missing"
    assert execution["per_file"][0]["reason"] == "header_time_missing"
    assert evidence["status"] == "archived"


def test_parse_header_time_invalid_date_falls_back(tmp_path: Path) -> None:
    _write_source(tmp_path, lst_me_content(header_time=HEADER_TIME_INVALID))
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-invalid",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    entry = evidence["execution_time"]["per_file"][0]
    assert entry["status"] == "invalid"
    assert entry["reason"] == "header_time_invalid"
    assert entry["parsed_at"] is None
    assert entry["raw_text"] == header_time_line(HEADER_TIME_INVALID)
    assert evidence["status"] == "archived"


def test_parse_header_time_in_future_falls_back(tmp_path: Path) -> None:
    _write_source(tmp_path, lst_me_content(header_time=HEADER_TIME_FUTURE))
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-future",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    execution = evidence["execution_time"]
    assert execution["status"] == "missing"
    assert execution["source"] == "task"
    entry = execution["per_file"][0]
    assert entry["status"] == "time_in_future"
    assert entry["reason"] == "time_in_future"
    assert entry["parsed_at"] == "2098-12-31T16:00:00+00:00"


def test_parse_header_time_within_five_minutes_is_accepted(tmp_path: Path) -> None:
    _write_source(tmp_path, lst_me_content(header_time="2025-06-01  20:04:00"))
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-tolerance",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    entry = evidence["execution_time"]["per_file"][0]
    assert entry["status"] == "ok"
    assert entry["parsed_at"] == "2025-06-01T12:04:00+00:00"


def test_parse_multi_device_shares_header_time(tmp_path: Path) -> None:
    payload = multi_device_lst_me_content(
        [
            {"device_name": "Device-A", "network_element_type": "UMF2020", "version": "V1"},
            {"device_name": "Device-B", "network_element_type": "UMF2020", "version": "V2"},
        ],
        header_time=HEADER_TIME_SAMPLE,
    )
    _write_source(tmp_path, payload)
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-multi",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    assert len(evidence["execution_time"]["per_file"]) == 1
    assert [device["normalized_name"] for device in evidence["devices"]] == ["Device-A", "Device-B"]
    assert all(device["source_files"] == [f"config/{LST_ME_FILENAME}"] for device in evidence["devices"])


def test_parse_multiple_source_files_keep_own_times(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        lst_me_content(device_name="Device-A", header_time=HEADER_TIME_SAMPLE),
        name="LST ME.txt",
        sub="config/site-a",
    )
    _write_source(
        tmp_path,
        lst_me_content(device_name="Device-B", header_time="2025-05-27  09:00:00"),
        name="LST ME.txt",
        sub="config/site-b",
    )
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-sources",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    execution = evidence["execution_time"]
    assert execution["status"] == "ok"
    by_file = {entry["source_file"]: entry for entry in execution["per_file"]}
    assert by_file["config/site-a/LST ME.txt"]["parsed_at"] == "2025-05-26T06:40:36+00:00"
    assert by_file["config/site-b/LST ME.txt"]["parsed_at"] == "2025-05-27T01:00:00+00:00"


def test_parse_partial_header_times_marks_partial(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        lst_me_content(device_name="Device-A", header_time=HEADER_TIME_SAMPLE),
        name="LST ME.txt",
        sub="config/site-a",
    )
    _write_source(
        tmp_path,
        lst_me_content(device_name="Device-B"),
        name="LST ME.txt",
        sub="config/site-b",
    )
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-partial",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    assert evidence["execution_time"]["status"] == "partial"
    assert evidence["execution_time"]["source"] == "task"
    assert [entry["status"] for entry in evidence["execution_time"]["per_file"]] == ["ok", "missing"]


def test_parse_time_line_does_not_become_record_field(tmp_path: Path) -> None:
    _write_source(tmp_path, lst_me_content(header_time=HEADER_TIME_SAMPLE))
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-field",
        province="江苏",
        operator="移动",
        product="UMF2020",
        completed_at=_completed_at(),
    )
    assert evidence["errors"] == []
    assert evidence["records"][0]["name_source_lines"] == [2]
    assert evidence["records"][0]["version_source_lines"] == [4]


def test_parse_without_completed_at_keeps_header_time(tmp_path: Path) -> None:
    _write_source(tmp_path, lst_me_content(header_time=HEADER_TIME_FUTURE))
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-no-completed",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["execution_time"]["per_file"][0]["status"] == "ok"


def test_source_file_missing_evidence_has_empty_execution_time(tmp_path: Path) -> None:
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-nofile",
        province="江苏",
        operator="移动",
        product="UMF2020",
    )
    assert evidence["execution_time"] == {"status": "missing", "source": "task", "per_file": []}
    assert evidence["not_archived_reason"] == "source_file_missing"


def test_log_supplement_evidence_has_empty_execution_time(tmp_path: Path) -> None:
    evidence = parse_inventory(
        tmp_path,
        task_id="task-time-log",
        province=None,
        operator=None,
        package_kind="log_supplement",
    )
    assert evidence["execution_time"] == {"status": "missing", "source": "task", "per_file": []}
