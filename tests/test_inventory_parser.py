"""台账解析器契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

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

    evidence = parse_inventory(task_dir, task_id="task-ok", province="江苏 ", operator="移动")
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

    content = ("ME name: A B\nNE name: A B\nME name: A B\nSW version: V1\n软件版本: V1\n").encode()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(tmp_path, task_id="task-alias", province="江苏", operator="电信")
    assert evidence["status"] == "archived"
    assert evidence["device"]["normalized_name"] == "A B"
    assert evidence["version"]["raw_version"] == "V1"


def test_parse_gb18030_and_case_insensitive_path(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    (tmp_path / "config" / "nested").mkdir(parents=True)
    path = tmp_path / "config" / "nested" / "lst me.txt"
    path.write_bytes(lst_me_content(device_name="南京汇聚", version="V900R016", encoding="gb18030"))
    evidence = parse_inventory(tmp_path, task_id="task-gb", province="江苏", operator="联通")
    assert evidence["device"]["normalized_name"] == "南京汇聚"
    assert evidence["version"]["raw_version"] == "V900R016"


def test_parse_missing_version_archives_device(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(lst_me_content(version=None))
    evidence = parse_inventory(tmp_path, task_id="task-missing-version", province="江苏", operator="移动")
    assert evidence["status"] == "archived"
    assert evidence["version"]["status"] == "missing"
    assert evidence["archived"]["archived"] is True


def test_parse_version_conflict(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    content = b"NE name: Device-A\nSoftware version: V2\nSoftware version: V1\n"
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(tmp_path, task_id="task-version-conflict", province="江苏", operator="移动")
    assert evidence["status"] == "archived"
    assert evidence["version"]["status"] == "conflict"
    assert evidence["version"]["candidates"] == ["V2", "V1"]
    assert evidence["archived"]["archived"] is True


def test_parse_device_identity_conflict(tmp_path: Path) -> None:
    from app.services.inventory.parser import parse_inventory

    content = b"NE name: Device-A\nNE name: Device-B\nSoftware version: V1\n"
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / LST_ME_FILENAME).write_bytes(content)
    evidence = parse_inventory(tmp_path, task_id="task-device-conflict", province="江苏", operator="移动")
    assert evidence["status"] == "not_archived"
    assert evidence["device"]["status"] == "conflict"
    assert evidence["archived"] == {
        "archived": False,
        "device_id": None,
        "observation_id": None,
        "reason": "device_identity_conflict",
    }


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
    evidence = parse_inventory(tmp_path, task_id="task-decode", province="江苏", operator="移动")
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
