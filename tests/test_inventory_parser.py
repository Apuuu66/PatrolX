"""台账解析器契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.inventory.parser import parse_inventory
from tests.fixtures.inventory.builder import LST_ME_FILENAME, lst_me_content, make_inventory_zip


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
    assert evidence["parser_version"] == "2"
    assert evidence["schema_version"] == 2
    assert evidence["status"] == "archived"
    assert evidence["network_element_type_filter"] == {
        "requested": "UMF2020",
        "normalized": "UMF2020",
        "status": "ok",
        "matched_count": 2,
        "unmatched_count": 1,
    }
    assert [item["normalized_name"] for item in evidence["devices"]] == ["NJ-AGG-001", "NJ-AGG-002"]
    assert [item["matched"] for item in evidence["records"]] == [True, True, False]
    assert len(evidence["archived"]["devices"]) == 2
    assert evidence["archived"]["device_id"] is None


def test_parse_missing_network_element_type_filter_does_not_archive(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(_multi_content())
    evidence = parse_inventory(tmp_path, task_id="task-no-filter", province="江苏", operator="移动")
    assert evidence["status"] == "not_archived"
    assert evidence["not_archived_reason"] == "network_element_type_filter_missing"
    assert evidence["devices"] == []
    assert evidence["network_element_type_filter"]["status"] == "missing"


def test_parse_no_matching_network_element_type_does_not_archive(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(_multi_content())
    evidence = parse_inventory(tmp_path, task_id="task-no-match", province="江苏", operator="移动", product="UMF9999")
    assert evidence["status"] == "not_archived"
    assert evidence["not_archived_reason"] == "network_element_type_no_match"
    assert evidence["devices"] == []
    assert evidence["network_element_type_filter"]["status"] == "no_match"


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
