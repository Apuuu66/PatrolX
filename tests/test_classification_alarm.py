"""UMF/CSP 告警按真实目录统一展开的 US2 行为测试。"""

from __future__ import annotations

import gzip
import io
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.services.extraction.audit import LandedEntry
from app.services.extraction.classification import ClassificationRun, classify_main_evidence

ALARM_HEADER = (
    "告警流水号,应用ID,应用名称,告警ID,告警名称,告警级别,发生时间,清除时间,清除类型,事件类型,告警重复次数,定位信息\n"  # noqa: E501
)
ALARM_RECORD = "3001,9002,UMF核心服务,3001,合成告警,重要,2026-09-18 09:00:00,,,通信告警,1,pod-alarm-01\n"


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 18, 9, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def _tar_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mtime = 0
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def _tar_gz_bytes(members: dict[str, bytes]) -> bytes:
    return gzip.compress(_tar_bytes(members), mtime=0)


def _gzip_bytes(content: bytes) -> bytes:
    return gzip.compress(content, mtime=0)


def _corrupt_zip_member_crc(payload: bytes, member_name: str) -> bytes:
    """修改指定 ZIP 成员的中央目录 CRC，保留其他成员可读。"""
    corrupted = bytearray(payload)
    eocd_offset = payload.rfind(b"PK\x05\x06")
    assert eocd_offset >= 0
    entry_count = struct.unpack_from("<H", payload, eocd_offset + 10)[0]
    central_offset = struct.unpack_from("<I", payload, eocd_offset + 16)[0]
    target_name = member_name.encode()

    for _ in range(entry_count):
        assert payload[central_offset : central_offset + 4] == b"PK\x01\x02"
        name_length = struct.unpack_from("<H", payload, central_offset + 28)[0]
        extra_length = struct.unpack_from("<H", payload, central_offset + 30)[0]
        comment_length = struct.unpack_from("<H", payload, central_offset + 32)[0]
        name_start = central_offset + 46
        if payload[name_start : name_start + name_length] == target_name:
            crc = struct.unpack_from("<I", payload, central_offset + 16)[0]
            struct.pack_into("<I", corrupted, central_offset + 16, crc ^ 1)
            return bytes(corrupted)
        central_offset += 46 + name_length + extra_length + comment_length

    raise AssertionError(f"未找到 ZIP 成员: {member_name}")


def _classify(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    product: str,
) -> ClassificationRun:
    data_dir = tmp_path / "task"
    evidence_root = data_dir / ".main"
    evidence_root.mkdir(parents=True)
    for relative, content in files.items():
        _write(evidence_root / relative, content)
    return classify_main_evidence(data_dir, product=product)


def _entries_from(run: ClassificationRun, source: str) -> list[LandedEntry]:
    return [entry for entry in run.entries if entry.source_relative == source]


def _entry_from(run: ClassificationRun, source: str) -> LandedEntry:
    entries = _entries_from(run, source)
    assert len(entries) == 1, [entry.source_relative for entry in run.entries]
    return entries[0]


@pytest.mark.parametrize("product", ["UMF", "CSP"])
def test_alarm_information_matches_arbitrary_prefix_for_both_products(tmp_path: Path, product: str) -> None:
    """任意证据前缀下的完整 Alarm Information 段均按 UMF 告警路线落位。"""
    source = "vendor-a/Network/Problem 038/Wrapper/Alarm Information/export/history.csv"

    run = _classify(tmp_path, {source: b"alarm\n"}, product=product)

    entry = _entry_from(run, source)
    assert (entry.route_id, entry.category, entry.action) == ("alarm.umf", "alarm", "expand_recursive")
    assert entry.target == "alarm/export/history.csv"
    assert entry.member_relative is None


@pytest.mark.parametrize("product", ["UMF", "CSP"])
def test_alarm_data_under_zero_and_problems_matches_for_both_products(tmp_path: Path, product: str) -> None:
    """CSP 的 0/Problems/Alarm Data 路径在两种上传网元下均按告警处理。"""
    source = "csp-device/0/Problems/Alarm Data/current/alarms.csv"

    run = _classify(tmp_path, {source: b"alarm\n"}, product=product)

    entry = _entry_from(run, source)
    assert (entry.route_id, entry.category, entry.target) == (
        "alarm.csp",
        "alarm",
        "alarm/current/alarms.csv",
    )


def test_alarm_data_matches_when_problems_directory_is_missing(tmp_path: Path) -> None:
    """CSP 告警识别只依赖 Alarm Data 完整目录段，不依赖 Problems。"""
    source = "csp-device/0/Wrapper/Alarm Data/export/current.csv"

    run = _classify(tmp_path, {source: b"alarm\n"}, product="CSP")

    entry = _entry_from(run, source)
    assert (entry.route_id, entry.category, entry.target) == (
        "alarm.csp",
        "alarm",
        "alarm/export/current.csv",
    )


def test_alarm_directory_segments_are_case_insensitive_but_must_be_complete(tmp_path: Path) -> None:
    """告警目录段大小写不敏感，但相似目录名不能被当作完整告警目录段。"""
    information_source = "Outer/ALARM iNfOrMaTiOn/Export/upper.csv"
    data_source = "Wrapper/alarm dAtA/Export/lower.csv"
    similar_source = "Outer/Alarm Information Archive/not-alarm.csv"

    run = _classify(
        tmp_path,
        {
            information_source: b"information\n",
            data_source: b"data\n",
            similar_source: b"ordinary\n",
        },
        product="UMF",
    )

    information = _entry_from(run, information_source)
    data = _entry_from(run, data_source)
    similar = _entry_from(run, similar_source)
    assert (information.route_id, information.target) == ("alarm.umf", "alarm/Export/upper.csv")
    assert (data.route_id, data.target) == ("alarm.csp", "alarm/Export/lower.csv")
    assert similar.route_id == "umf.other"


def test_alarm_phase_wins_over_zero_ignore_and_nonalarm_zero_is_ignored(tmp_path: Path) -> None:
    """位于 0/ 的告警优先于 ignore，非告警 0/ 内容不进入 catalog。"""
    alarm_source = "device-a/0/Problems/Alarm Data/live/alarm.csv"
    ignored_sources = {
        "device-a/0/Problems/Inventory/inventory.csv",
        "device-a/0/Support/version.txt",
    }
    files = {alarm_source: ALARM_RECORD.encode(), **{source: b"ordinary\n" for source in ignored_sources}}

    run = _classify(tmp_path, files, product="UMF")

    alarm = _entry_from(run, alarm_source)
    assert (alarm.route_id, alarm.target) == ("alarm.csp", "alarm/live/alarm.csv")
    assert {entry.source_relative for entry in run.entries} == {alarm_source}
    assert {record.source_relative for record in run.ignored} == ignored_sources
    assert {record.route_id for record in run.ignored} == {"ignore.zero"}
    assert {entry.path for entry in run.catalog} == {"alarm/live/alarm.csv"}


def test_plain_alarm_files_preserve_empty_header_zero_record_and_populated_content(tmp_path: Path) -> None:
    """告警普通文件不按大小或记录数筛选，原始字节必须完整落位。"""
    contents = {
        "empty.csv": b"",
        "header-only.csv": ALARM_HEADER.encode(),
        "zero-records.csv": (ALARM_HEADER + "\n").encode(),
        "with-records.csv": (ALARM_HEADER + ALARM_RECORD).encode(),
    }
    files = {f"Outer/Alarm Information/Boundary/{name}": content for name, content in contents.items()}

    run = _classify(tmp_path, files, product="UMF")

    assert not run.failures
    for name, content in contents.items():
        source = f"Outer/Alarm Information/Boundary/{name}"
        entry = _entry_from(run, source)
        assert (entry.route_id, entry.category, entry.target) == (
            "alarm.umf",
            "alarm",
            f"alarm/Boundary/{name}",
        )
        assert entry.member_relative is None
        assert (run.data_dir / entry.target).read_bytes() == content


def test_alarm_zip_expands_members_without_archive_wrapper(tmp_path: Path) -> None:
    """ZIP 成员移除告警来源目录和归档外层后保留成员相对路径。"""
    source = "Outer/Alarm Information/export/alarms.zip"
    members = {
        "part-01.csv": ALARM_RECORD.encode(),
        "nested/part-02.csv": b"",
    }

    run = _classify(tmp_path, {source: _zip_bytes(members)}, product="UMF")

    entries = _entries_from(run, source)
    assert not run.failures
    assert {entry.member_relative for entry in entries} == set(members)
    assert {entry.target for entry in entries} == {"alarm/part-01.csv", "alarm/nested/part-02.csv"}
    assert all(
        (entry.route_id, entry.category, entry.action) == ("alarm.umf", "alarm", "expand_recursive")
        for entry in entries
    )


def test_alarm_nested_archive_combines_inner_member_paths(tmp_path: Path) -> None:
    """嵌套归档递归展开，archives 外层不进入目标但保留成员父目录。"""
    inner_archive = _tar_gz_bytes({"inner/alarm.csv": ALARM_RECORD.encode()})
    source = "Outer/Alarm Data/export/outer.zip"
    archive = _zip_bytes(
        {
            "top.csv": b"top\n",
            "nested/bundle.tar.gz": inner_archive,
        }
    )

    run = _classify(tmp_path, {source: archive}, product="CSP")

    entries = _entries_from(run, source)
    assert not run.failures
    assert {(entry.member_relative, entry.target) for entry in entries} == {
        ("nested/inner/alarm.csv", "alarm/nested/inner/alarm.csv"),
        ("top.csv", "alarm/top.csv"),
    }


def test_alarm_tar_and_tar_gz_expand_members(tmp_path: Path) -> None:
    """TAR 与 TAR.GZ 均按告警归档递归展开。"""
    tar_source = "Outer/Alarm Information/tar/alarms.tar"
    tar_gz_source = "Outer/Alarm Information/targz/alarms.tar.gz"

    run = _classify(
        tmp_path,
        {
            tar_source: _tar_bytes({"tar/from-tar.csv": b"tar\n"}),
            tar_gz_source: _tar_gz_bytes({"targz/from-targz.csv": b"targz\n"}),
        },
        product="UMF",
    )

    tar_entries = _entries_from(run, tar_source)
    tar_gz_entries = _entries_from(run, tar_gz_source)
    assert [(entry.member_relative, entry.target) for entry in tar_entries] == [
        ("tar/from-tar.csv", "alarm/tar/from-tar.csv")
    ]
    assert [(entry.member_relative, entry.target) for entry in tar_gz_entries] == [
        ("targz/from-targz.csv", "alarm/targz/from-targz.csv")
    ]
    assert not run.failures


def test_single_file_gzip_is_decompressed_inside_alarm_root(tmp_path: Path) -> None:
    """单文件 GZIP 去除一层 .gz 后缀，内容保存在 alarm/ 下。"""
    source = "Outer/Alarm Information/gzip/outages.csv.gz"
    content = (ALARM_HEADER + ALARM_RECORD).encode()

    run = _classify(tmp_path, {source: _gzip_bytes(content)}, product="UMF")

    entry = _entry_from(run, source)
    assert (entry.route_id, entry.category, entry.target) == (
        "alarm.umf",
        "alarm",
        "alarm/gzip/outages.csv",
    )
    assert entry.member_relative == "gzip/outages.csv"
    assert (run.data_dir / entry.target).read_bytes() == content


def test_corrupt_alarm_member_does_not_block_valid_siblings(tmp_path: Path) -> None:
    """损坏的告警成员只产生局部失败，同归档及相邻合法告警继续落位。"""
    source = "Outer/Alarm Data/corrupt/alarms.zip"
    sibling_source = "Outer/Alarm Data/plain-survivor.csv"
    corrupt_member = "nested/Corrupted.csv"
    archive = _corrupt_zip_member_crc(
        _zip_bytes(
            {
                "valid.csv": b"valid\n",
                corrupt_member: b"corrupt\n",
            }
        ),
        corrupt_member,
    )

    run = _classify(
        tmp_path,
        {
            source: archive,
            sibling_source: b"sibling\n",
        },
        product="CSP",
    )

    assert {entry.target for entry in run.entries} == {
        "alarm/plain-survivor.csv",
        "alarm/valid.csv",
    }
    assert {entry.path for entry in run.catalog} == {
        "alarm/plain-survivor.csv",
        "alarm/valid.csv",
    }
    failures = [failure for failure in run.failures if failure.source_relative == source]
    assert len(failures) == 1
    assert (failures[0].route_id, failures[0].member_relative, failures[0].error_code) == (
        "alarm.csp",
        corrupt_member,
        "archive_corrupt",
    )


def test_nested_corrupt_archive_records_prefixed_failure_and_keeps_sibling(tmp_path: Path) -> None:
    """嵌套归档整体损坏时只记录子归档路径，根归档中的合法成员继续落位。"""
    source = "Outer/Alarm Information/nested/alarms.zip"
    archive = _zip_bytes(
        {
            "valid.csv": b"valid\n",
            "nested/corrupt.zip": b"not a zip archive",
        }
    )

    run = _classify(tmp_path, {source: archive}, product="UMF")

    assert {entry.target for entry in run.entries} == {"alarm/valid.csv"}
    assert len(run.failures) == 1
    assert (run.failures[0].source_relative, run.failures[0].member_relative, run.failures[0].error_code) == (
        source,
        "nested/corrupt.zip",
        "archive_corrupt",
    )


def test_unsupported_alarm_archive_records_failure_and_keeps_plain_sibling(tmp_path: Path) -> None:
    """明确不支持的告警归档不得静默落位，其他合法告警文件仍继续处理。"""
    source = "Outer/Alarm Data/unsupported/alarms.7z"
    sibling_source = "Outer/Alarm Data/plain-survivor.csv"

    run = _classify(
        tmp_path,
        {
            source: b"unsupported archive",
            sibling_source: b"sibling\n",
        },
        product="CSP",
    )

    assert {entry.target for entry in run.entries} == {"alarm/plain-survivor.csv"}
    assert len(run.failures) == 1
    assert (run.failures[0].source_relative, run.failures[0].member_relative, run.failures[0].error_code) == (
        source,
        None,
        "archive_corrupt",
    )
