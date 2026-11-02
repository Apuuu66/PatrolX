"""US3 Service Logs、CHR 与主机日志的选择和解压行为测试。"""

from __future__ import annotations

import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.services.extraction.classification import ClassificationRun, classify_main_evidence
from app.services.extraction.config import load_classification_config

SCENE = "Outer Device/Problem 038/UMF Problem Scene"
SERVICE_ARCHIVE = f"{SCENE}/Service Logs (Problem)/ServiceLogs_20260918.zip"
CHR_ARCHIVE = f"{SCENE}/CHR Information/ServiceLogs_20260918.zip"
DEBUG_ARCHIVE = f"{SCENE}/Host Debugging Logs/DEBUG.tar.gz"
SYSTEM_ARCHIVE = f"{SCENE}/Host System Logs/OS.tar.gz"

SERVICE_INCLUDES = {
    "**/UMFAcc.log",
    "**/UMFAcc_*.log.gz",
    "**/UmfService.log",
    "**/UmfService_*.log.gz",
    "**/CacheService.log",
    "**/ResourceManageService.log",
}
SERVICE_EXCLUDES = {
    "**/RScheck/**",
    "**/rscheck*.gz",
    "**/dblog.tar.gz",
    "**/UFP_*.log",
    "**/UFP_MSS_2_0.zip",
    "**/monitor_detect.log",
    "**/UmfService_monitor.log",
    "**/start/**/*.log",
    "**/proxy/**/*.log",
    "**/bbox*.dat.txt",
    "**/LocalLogReport.csv",
}


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


def _tar_gz_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mtime = 0
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(content))
    return gzip.compress(buffer.getvalue(), mtime=0)


def _classify(tmp_path: Path, files: dict[str, bytes]) -> ClassificationRun:
    data_dir = tmp_path / "task"
    evidence_root = data_dir / ".main"
    for relative, content in files.items():
        _write(evidence_root / relative, content)
    return classify_main_evidence(data_dir, product="UMF")


def _entries_for(run: ClassificationRun, source: str) -> list:
    return [entry for entry in run.entries if entry.source_relative == source]


def test_service_log_routes_declare_all_include_and_exclude_patterns() -> None:
    config = load_classification_config()
    route = next(route for route in config.routes if route.id == "umf.service-logs")

    assert (route.phase, route.action, route.category) == ("precise", "select_and_decompress", "log")
    assert route.profiles == ("UMF",)
    assert route.source.directory == "Service Logs (Problem)"
    assert route.source.file == "ServiceLogs_*.zip"
    assert {item.pattern for item in route.selection.include} == SERVICE_INCLUDES
    assert {item.pattern for item in route.selection.exclude} == SERVICE_EXCLUDES
    assert route.target == "logs/{service}/{node_path}/{name_without_gz}"


def test_chr_and_host_routes_declare_expected_selection_and_member_decompress() -> None:
    config = load_classification_config()
    routes = {route.id: route for route in config.routes}

    chr = routes["umf.chr"]
    assert (chr.action, chr.category, chr.target) == ("select_and_decompress", "chr", "chr/{member}")
    assert {item.pattern for item in chr.selection.include} == {"**/*.bil.gz"}
    assert {(item.pattern, item.reason) for item in chr.selection.exclude} == {
        ("**/LocalLogReport.csv", "report_not_log")
    }

    debug = routes["umf.host-debug"]
    assert (debug.action, debug.category, debug.target) == ("expand", "log", "host-debug/{member}")
    assert debug.member_decompress == ("**/*.log.gz",)

    system = routes["umf.host-system"]
    assert (system.action, system.category, system.target) == ("expand", "log", "host-system/{member}")
    assert system.member_decompress == ("**/*.log.gz",)


def test_service_log_selection_excludes_before_include_and_landed_targets_are_service_scoped(tmp_path: Path) -> None:
    service_members = {
        "UMFAcc/logs/node-01/pod-01/UMFAcc.log": b"umf-acc\n",
        "UmfService/logs/node-02/pod-02/UmfService_20260918.log.gz": gzip.compress(b"umf-service\n", mtime=0),
        "CacheService/logs/node-03/CacheService.log": b"cache\n",
        "ResourceManageService/logs/node-04/ResourceManageService.log": b"resource\n",
        "UMFAcc/logs/node-01/proxy/UMFAcc.log": b"proxy\n",
        "UMFAcc/logs/node-01/RScheck/script.sh": b"script\n",
        "UMFAcc/logs/node-01/rscheck_20260918.gz": gzip.compress(b"rscheck\n", mtime=0),
        "UMFAcc/logs/node-01/dblog.tar.gz": b"not-an-archive\n",
        "UMFAcc/logs/node-01/UFP_other.log": b"ufp-log\n",
        "UMFAcc/logs/node-01/UFP_MSS_2_0.zip": b"ufp-archive\n",
        "UMFAcc/logs/node-01/monitor_detect.log": b"monitor\n",
        "UmfService/logs/node-02/UmfService_monitor.log": b"service-monitor\n",
        "UmfService/logs/node-02/start/boot.log": b"start\n",
        "UmfService/logs/node-02/proxy/request.log": b"proxy\n",
        "CacheService/logs/node-03/bbox.dat.txt": b"bbox\n",
        "LocalLogReport.csv": b"report\n",
        "Unmatched/notes.txt": b"notes\n",
    }

    run = _classify(tmp_path, {SERVICE_ARCHIVE: _zip_bytes(service_members)})
    entries = _entries_for(run, SERVICE_ARCHIVE)

    assert {entry.target for entry in entries} == {
        "logs/UMFACC/logs/node-01/pod-01/UMFAcc.log",
        "logs/UMFSERVICE/logs/node-02/pod-02/UmfService_20260918.log",
        "logs/CACHESERVICE/logs/node-03/CacheService.log",
        "logs/RESOURCEMANAGESERVICE/logs/node-04/ResourceManageService.log",
    }
    assert {entry.member_relative for entry in entries} == {
        "UMFAcc/logs/node-01/pod-01/UMFAcc.log",
        "UmfService/logs/node-02/pod-02/UmfService_20260918.log",
        "CacheService/logs/node-03/CacheService.log",
        "ResourceManageService/logs/node-04/ResourceManageService.log",
    }
    assert all(entry.route_id == "umf.service-logs" and entry.action == "select_and_decompress" for entry in entries)
    landed_service_log = run.data_dir / "logs/UMFSERVICE/logs/node-02/pod-02/UmfService_20260918.log"
    assert landed_service_log.read_bytes() == b"umf-service\n"

    ignored = {record.member_relative: record for record in run.ignored if record.source_relative == SERVICE_ARCHIVE}
    expected_reasons = {
        "UMFAcc/logs/node-01/proxy/UMFAcc.log": "proxy_log",
        "UMFAcc/logs/node-01/RScheck/script.sh": "service_check_script",
        "UMFAcc/logs/node-01/rscheck_20260918.gz": "service_check_script",
        "UMFAcc/logs/node-01/dblog.tar.gz": "runtime_database_archive",
        "UMFAcc/logs/node-01/UFP_other.log": "ufp_log",
        "UMFAcc/logs/node-01/UFP_MSS_2_0.zip": "ufp_archive",
        "UMFAcc/logs/node-01/monitor_detect.log": "monitor_log",
        "UmfService/logs/node-02/UmfService_monitor.log": "umf_service_monitor_log",
        "UmfService/logs/node-02/start/boot.log": "service_startup_log",
        "UmfService/logs/node-02/proxy/request.log": "proxy_log",
        "CacheService/logs/node-03/bbox.dat.txt": "bbox_data",
        "LocalLogReport.csv": "report_not_log",
        "Unmatched/notes.txt": "member_not_selected",
    }
    assert {member: record.reason for member, record in ignored.items()} == expected_reasons
    assert all(
        record.action == "select_and_decompress" and record.route_id == "umf.service-logs"
        for record in ignored.values()
    )
    assert not (run.data_dir / "logs/UMFACC/logs/node-01/proxy/UMFAcc.log").exists()


def test_service_log_unselected_members_never_enter_catalog(tmp_path: Path) -> None:
    members = {
        "UMFAcc/logs/node-01/UMFAcc.log": b"selected\n",
        "UMFAcc/logs/node-01/other.log.gz": gzip.compress(b"not selected\n", mtime=0),
    }

    run = _classify(tmp_path, {SERVICE_ARCHIVE: _zip_bytes(members)})

    assert [entry.path for entry in run.catalog] == ["logs/UMFACC/logs/node-01/UMFAcc.log"]
    records = [record for record in run.ignored if record.member_relative == "UMFAcc/logs/node-01/other.log.gz"]
    assert [record.reason for record in records] == ["member_not_selected"]
    assert not any(entry.target.endswith("other.log") for entry in run.entries)


def test_chr_selection_decompresses_bil_and_ignores_report_and_other_members(tmp_path: Path) -> None:
    members = {
        "nodes/paas-01/health.bil.gz": gzip.compress(b"bil-1\n", mtime=0),
        "nodes/paas-02/health_2.bil.gz": gzip.compress(b"bil-2\n", mtime=0),
        "nodes/paas-03/health_3.bil.gz": gzip.compress(b"bil-3\n", mtime=0),
        "nodes/paas-01/LocalLogReport.csv": b"report\n",
        "nodes/paas-01/notes.txt": b"notes\n",
    }

    run = _classify(tmp_path, {CHR_ARCHIVE: _zip_bytes(members)})
    entries = _entries_for(run, CHR_ARCHIVE)

    assert {entry.target for entry in entries} == {
        "chr/nodes/paas-01/health.bil",
        "chr/nodes/paas-02/health_2.bil",
        "chr/nodes/paas-03/health_3.bil",
    }
    assert {entry.member_relative for entry in entries} == {
        "nodes/paas-01/health.bil",
        "nodes/paas-02/health_2.bil",
        "nodes/paas-03/health_3.bil",
    }
    assert all(entry.route_id == "umf.chr" and entry.category == "chr" for entry in entries)
    assert all((run.data_dir / entry.target).read_bytes().startswith(b"bil-") for entry in entries)
    ignored = {record.member_relative: record.reason for record in run.ignored if record.source_relative == CHR_ARCHIVE}
    assert ignored == {
        "nodes/paas-01/LocalLogReport.csv": "report_not_log",
        "nodes/paas-01/notes.txt": "member_not_selected",
    }


@pytest.mark.parametrize(
    ("archive", "route_id", "root"),
    [
        (DEBUG_ARCHIVE, "umf.host-debug", "host-debug"),
        (SYSTEM_ARCHIVE, "umf.host-system", "host-system"),
    ],
)
def test_host_archives_decompress_member_log_gz(
    tmp_path: Path,
    archive: str,
    route_id: str,
    root: str,
) -> None:
    members = {
        "nodes/paas-01/DEBUG.log.gz": gzip.compress(b"debug\n", mtime=0),
        "nodes/paas-01/README.txt": b"readme\n",
        "nodes/paas-02/OS.log.gz": gzip.compress(b"system\n", mtime=0),
    }

    run = _classify(tmp_path, {archive: _tar_gz_bytes(members)})
    entries = _entries_for(run, archive)

    assert {entry.target for entry in entries} == {
        f"{root}/nodes/paas-01/DEBUG.log",
        f"{root}/nodes/paas-01/README.txt",
        f"{root}/nodes/paas-02/OS.log",
    }
    assert all(entry.route_id == route_id and entry.action == "expand" for entry in entries)
    assert (run.data_dir / f"{root}/nodes/paas-01/DEBUG.log").read_bytes() == b"debug\n"
    assert (run.data_dir / f"{root}/nodes/paas-02/OS.log").read_bytes() == b"system\n"


def test_selected_gzip_failure_is_local_and_keeps_other_logs(tmp_path: Path) -> None:
    members = {
        "UMFAcc/logs/node-01/UMFAcc.log": b"valid\n",
        "UMFAcc/logs/node-01/UMFAcc_bad.log.gz": b"not-a-gzip\n",
    }

    run = _classify(tmp_path, {SERVICE_ARCHIVE: _zip_bytes(members)})

    assert [entry.path for entry in run.catalog] == ["logs/UMFACC/logs/node-01/UMFAcc.log"]
    assert len(run.failures) == 1
    failure = run.failures[0]
    assert failure.source_relative == SERVICE_ARCHIVE
    assert failure.member_relative == "UMFAcc/logs/node-01/UMFAcc_bad.log.gz"
    assert failure.route_id == "umf.service-logs"
    assert failure.action == "select_and_decompress"
    assert failure.error_code == "archive_corrupt"
