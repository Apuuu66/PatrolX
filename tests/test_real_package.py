"""真实 App Problem Scene 样例包与分类/规则联动测试。"""

from __future__ import annotations

import csv
import io
import re
import shutil
import zipfile
from pathlib import Path

from app.core.archive import unpack
from app.core.checksum import sha256_file
from app.core.dicts import load_dicts
from app.inspectors.registry import registry
from app.services.extraction.classification import classify_main_evidence
from app.services.inventory.parser import parse_inventory
from tests.fixtures.make_real_package import BASE, FIXED_DATE, LST_ME_TXT, build_real_package

DEFAULT_FIXTURE_SHA256 = "c6fe260b70f9f80f4f3f82d2d510aba89803f0516e9e6b0d270a3493a5b12a94"


def _extract(tmp_path: Path, *, copy_base_only: bool = False):
    package_dir = tmp_path / "input"
    package = build_real_package(package_dir)
    data_dir = tmp_path / "task-333"
    unpack(package, data_dir / ".main")
    if copy_base_only:
        isolated = tmp_path / "isolated-base"
        shutil.copytree(data_dir / ".main" / BASE, isolated)
        shutil.rmtree(data_dir / ".main")
        shutil.copytree(isolated, data_dir / ".main" / BASE)
    run = classify_main_evidence(data_dir, product="UMF")
    return data_dir, run


def test_real_package_member_names_match_reference(tmp_path: Path) -> None:
    package = build_real_package(tmp_path)
    assert package.name == "ZZapp01BCN_app_Problem_scene_333.zip"


def test_alarm_subpackage_contains_only_multiple_alarm_csvs(tmp_path: Path) -> None:
    """告警子包是真实导出现场：只包含多个 CSV，不存在汇总 JSON。"""
    package = build_real_package(tmp_path)
    import io
    import zipfile

    with zipfile.ZipFile(package) as main_archive:
        alarm_name = next(name for name in main_archive.namelist() if "/Alarm Information/" in name)
        with zipfile.ZipFile(io.BytesIO(main_archive.read(alarm_name))) as alarm_archive:
            members = alarm_archive.namelist()

    assert len(members) > 1
    assert all(name.endswith(".csv") for name in members)
    assert not any(name.endswith(".json") for name in members)


def test_real_package_without_scene_anchor_uses_relative_other_fallback(tmp_path: Path) -> None:
    """旧语义文件名不能绕过目录路由；未命中场景锚点时按相对路径进入 other。"""
    data_dir, run = _extract(tmp_path, copy_base_only=True)

    non_alarm_entries = [entry for entry in run.entries if entry.route_id != "alarm.umf"]
    assert {entry.route_id for entry in non_alarm_entries} == {"umf.other"}
    assert {entry.category for entry in non_alarm_entries} == {"other"}
    assert not any(entry.target.startswith(("kpi/", "logs/", "basic/")) for entry in run.entries)
    assert {path.relative_to(data_dir).as_posix() for path in data_dir.rglob("*") if path.is_file()} >= {
        entry.target for entry in run.entries
    }


def test_real_non_kpi_files_are_preserved_without_active_rules(tmp_path: Path) -> None:
    """非 KPI 数据继续安全落盘，但已下线的业务规则不得重新进入活动目录。"""
    _data_dir, run = _extract(tmp_path, copy_base_only=True)
    registry.load_all()

    assert run.entries
    assert {entry.category for entry in run.entries} == {"alarm", "other"}
    active_codes = {rule.code for rule in registry.all()}
    assert active_codes == {"alarm.active_state", "alarm.recurrence", "kpi.measurement_units"}
    assert {"alarm.stat", "alarm.flapping", "resource.check"}.isdisjoint(active_codes)


def test_real_package_network_element_types_match_product_dict() -> None:
    """样例包的键值与表格式网元类型均能归一化到产品字典 code。"""
    product_codes = {item.code.upper() for item in load_dicts().product}
    assert product_codes == {"UMF", "CSP"}
    types_in_package = set()
    for line in LST_ME_TXT.splitlines():
        if line.startswith("网元类型: "):
            types_in_package.add(line.removeprefix("网元类型: ").strip())
            continue
        cells = re.split(r"\s{2,}", line.strip())
        if len(cells) >= 5 and cells[0] == "1":
            types_in_package.add(cells[4])
    assert {item.upper() for item in types_in_package} == product_codes


def test_real_package_lst_me_feeds_device_ledger(tmp_path: Path) -> None:
    """样例清单按上传网元类型筛选；每个任务只使用自己的 basic 来源。"""
    data_dir = tmp_path / "ledger"
    (data_dir / "basic").mkdir(parents=True)
    (data_dir / "basic" / "LST ME.txt").write_text(LST_ME_TXT, encoding="utf-8")
    csp = parse_inventory(data_dir, task_id="task-333", province="江苏", operator="移动", product="csp")
    assert csp["status"] == "archived"
    assert csp["execution_time"]["status"] == "ok"
    assert csp["execution_time"]["source"] == "lst_me"
    assert csp["execution_time"]["per_file"][0]["parsed_at"] == "2026-09-01T02:00:00+00:00"
    assert csp["network_element_type_filter"]["normalized"] == "CSP"
    assert [device["normalized_name"] for device in csp["devices"]] == [
        "CSP-SZ-01",
        "CSP-SZ-02",
        "TABLE-CSP-01",
    ]
    assert [record["normalized_name"] for record in csp["records"]] == [
        "CSP-SZ-01",
        "CSP-SZ-02",
        "TABLE-CSP-01",
    ]
    assert [device["version"]["status"] for device in csp["devices"]] == ["ok", "missing", "ok"]
    assert csp["devices"][-1]["version"]["raw_version"] == "27.0.0.13"
    assert csp["network_element_type_filter"]["matched_count"] == 3
    assert csp["network_element_type_filter"]["unmatched_count"] == 2

    umf = parse_inventory(data_dir, task_id="task-333", province="江苏", operator="移动", product="umf")
    assert umf["status"] == "archived"
    assert umf["network_element_type_filter"]["normalized"] == "UMF"
    assert [device["normalized_name"] for device in umf["devices"]] == ["UMF-SZ-01", "TABLE-UMF-01"]
    assert [record["normalized_name"] for record in umf["records"]] == ["UMF-SZ-01", "TABLE-UMF-01"]
    assert umf["devices"][-1]["version"]["raw_version"] == "27.0.0"
    assert umf["network_element_type_filter"]["matched_count"] == 2
    assert umf["network_element_type_filter"]["unmatched_count"] == 3

    mme = parse_inventory(data_dir, task_id="task-333", province="江苏", operator="移动", product="mme")
    assert mme["status"] == "not_archived"
    assert mme["not_archived_reason"] == "network_element_type_no_match"
    assert mme["network_element_type_filter"]["unmatched_count"] == 5


def test_real_package_fixture_variants_are_repeatable(tmp_path: Path) -> None:
    """默认样例字节保持稳定，KPI 缺失边界变体可重复生成。"""
    first = build_real_package(tmp_path / "first")
    second = build_real_package(tmp_path / "second")
    missing = build_real_package(tmp_path / "missing", include_kpi=False)

    assert sha256_file(first) == DEFAULT_FIXTURE_SHA256
    assert sha256_file(second) == DEFAULT_FIXTURE_SHA256
    assert missing.name.endswith("_without_kpi.zip")
    assert sha256_file(missing) != DEFAULT_FIXTURE_SHA256
    with zipfile.ZipFile(missing) as archive:
        assert not any(
            name.endswith("/Performance Measurement Results/PerfResult_20260918.zip") for name in archive.namelist()
        )


def test_umf_fixture_covers_real_directory_routes_and_archive_members(tmp_path: Path) -> None:
    """UMF 合成目录覆盖外层包装、大小写、73 KPI、14 MESH 和未命中文件。"""
    package = build_real_package(tmp_path / "first")
    repeated = build_real_package(tmp_path / "second")
    assert sha256_file(package) == sha256_file(repeated)

    base = "Outer Device/Problem 038/wrapper/UMF Problem Scene"
    expected_members = {
        f"{base}/Basic Information About the UMF/Nested/config.ini",
        f"{base}/debugging commands/Diagnostic.JSON",
        f"{base}/Equipment Status/equipment.csv",
        f"{base}/MESH Information (Problem)/mesh.txt",
        f"{base}/System Resources/resources.txt",
        f"{base}/operation logs/OPERATIONLOG_HISTORY_20260918.CSV",
        f"{base}/MML Configurations/EXP MML.txt",
        f"{base}/MML Configurations/EXPMML_20260918.zip",
        f"{base}/Performance Measurement Results/PerfResult_20260918.zip",
        f"{base}/MESH Application Metrics/CollectExport_20260918.zip",
        f"{base}/collectandcheck.ini",
        f"{base}/Unlisted/custom.dat",
        f"{base}/Unlisted/UnknownBundle.ZIP",
        "csp-device/0/Problems/Inventory/inventory.csv",
    }

    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert expected_members <= names
        assert all(info.date_time == FIXED_DATE for info in archive.infolist())

        kpi_name = f"{base}/Performance Measurement Results/PerfResult_20260918.zip"
        with zipfile.ZipFile(io.BytesIO(archive.read(kpi_name))) as kpi_archive:
            assert len(kpi_archive.infolist()) == 73
            assert all(info.date_time == FIXED_DATE for info in kpi_archive.infolist())

        mesh_name = f"{base}/MESH Application Metrics/CollectExport_20260918.zip"
        with zipfile.ZipFile(io.BytesIO(archive.read(mesh_name))) as mesh_archive:
            mesh_members = mesh_archive.infolist()
            assert len(mesh_members) == 14
            assert all(info.filename.endswith(".csv") for info in mesh_members)
            assert all(info.date_time == FIXED_DATE for info in mesh_members)

        for nested_name in (
            f"{base}/MML Configurations/EXPMML_20260918.zip",
            f"{base}/Unlisted/UnknownBundle.ZIP",
            "csp-device/0/Alarm Data/path-security/alarms.zip",
        ):
            with zipfile.ZipFile(io.BytesIO(archive.read(nested_name))) as nested_archive:
                assert nested_archive.infolist()
                assert all(info.date_time == FIXED_DATE for info in nested_archive.infolist())


def test_umf_fixture_classifies_into_rule_ready_catalog(tmp_path: Path) -> None:
    """合成 UMF 证据按真实目录落位，KPI/MESH 成员和未知 ZIP 均保持路线语义。"""
    from app.core.archive import unpack
    from app.services.extraction.classification import classify_main_evidence

    package = build_real_package(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)

    base = "Outer Device/Problem 038/wrapper/UMF Problem Scene"
    data_dir = tmp_path / "task"
    evidence_root = data_dir / ".main"
    shutil.copytree(extracted / base, evidence_root / base)
    inventory_source = "csp-device/0/Problems/Inventory/inventory.csv"
    inventory_target = evidence_root / inventory_source
    inventory_target.parent.mkdir(parents=True)
    shutil.copy2(extracted / inventory_source, inventory_target)

    run = classify_main_evidence(data_dir, product="UMF")
    entries = {entry.source_relative: entry for entry in run.entries}

    expected_routes = {
        f"{base}/Basic Information About the UMF/Nested/config.ini": (
            "umf.basic",
            "config",
            "basic/Nested/config.ini",
        ),
        f"{base}/debugging commands/Diagnostic.JSON": ("umf.debug", "status", "debug/Diagnostic.JSON"),
        f"{base}/Equipment Status/equipment.csv": (
            "umf.equipment-status",
            "status",
            "status/equipment.csv",
        ),
        f"{base}/MESH Information (Problem)/mesh.txt": ("umf.mesh-status", "status", "status/mesh.txt"),
        f"{base}/System Resources/resources.txt": (
            "umf.system-resources",
            "status",
            "status/resources.txt",
        ),
        f"{base}/operation logs/OPERATIONLOG_HISTORY_20260918.CSV": (
            "umf.operation-log",
            "operation",
            "operation-log/OPERATIONLOG_HISTORY_20260918.CSV",
        ),
        f"{base}/MML Configurations/EXP MML.txt": ("umf.mml-file", "config", "mml/EXP MML.txt"),
        f"{base}/collectandcheck.ini": ("umf.other", "other", "other/collectandcheck.ini"),
        f"{base}/Unlisted/custom.dat": ("umf.other", "other", "other/Unlisted/custom.dat"),
    }
    assert {
        source: (entry.route_id, entry.category, entry.target)
        for source, entry in entries.items()
        if source in expected_routes
    } == expected_routes
    assert all((data_dir / entry.target).is_file() for entry in run.entries)

    kpi_entries = [entry for entry in run.entries if entry.route_id == "umf.kpi"]
    assert len(kpi_entries) == 73
    assert all(entry.category == "kpi" and entry.target.startswith("kpi/") for entry in kpi_entries)
    assert len({entry.target for entry in kpi_entries}) == 73

    mml_entries = [entry for entry in run.entries if entry.route_id == "umf.mml-archive"]
    assert {entry.member_relative for entry in mml_entries} == {
        "Config/Fragment.txt",
        "Config/Parameters.cfg",
    }
    assert all(entry.category == "config" and entry.target.startswith("mml/") for entry in mml_entries)
    assert all((data_dir / entry.target).is_file() for entry in mml_entries)

    mesh_entries = [entry for entry in run.entries if entry.route_id == "umf.mesh-metrics"]
    assert len(mesh_entries) == 14
    assert all(
        entry.category == "other" and entry.target.startswith("other/MESH Application Metrics/CollectExport_20260918/")
        for entry in mesh_entries
    )

    unknown_source = f"{base}/Unlisted/UnknownBundle.ZIP"
    unknown_entry = entries[unknown_source]
    assert (unknown_entry.route_id, unknown_entry.category, unknown_entry.action) == (
        "umf.other",
        "other",
        "fallback",
    )
    assert (data_dir / unknown_entry.target).read_bytes() == (extracted / unknown_source).read_bytes()
    kpi_catalog_paths = {entry.path for entry in run.catalog if entry.path.startswith("kpi/")}
    assert kpi_catalog_paths == {entry.target for entry in kpi_entries}

    csp_data_dir = tmp_path / "csp-task"
    csp_source = csp_data_dir / ".main" / inventory_source
    csp_source.parent.mkdir(parents=True)
    shutil.copy2(extracted / inventory_source, csp_source)
    csp_run = classify_main_evidence(csp_data_dir, product="CSP")
    assert csp_run.entries == ()
    assert [(item.source_relative, item.route_id) for item in csp_run.ignored] == [(inventory_source, "ignore.zero")]


def test_us3_real_fixture_keeps_98_logs_three_chr_and_decompresses_host_logs(tmp_path: Path) -> None:
    """固定样例覆盖 98 个业务日志、85 个轮转 GZIP、3 个 CHR 和主机日志解压。"""
    from app.core.archive import unpack
    from app.services.extraction.classification import classify_main_evidence

    package = build_real_package(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)

    base = "Outer Device/Problem 038/wrapper/UMF Problem Scene"
    data_dir = tmp_path / "task"
    evidence_root = data_dir / ".main"
    shutil.copytree(extracted / base, evidence_root / base)

    run = classify_main_evidence(data_dir, product="UMF")
    service_source = f"{base}/Service Logs (Problem)/ServiceLogs_20260918.zip"
    service_entries = [entry for entry in run.entries if entry.route_id == "umf.service-logs"]
    assert len(service_entries) == 98
    assert all(entry.source_relative == service_source for entry in service_entries)
    assert all(entry.target.endswith(".log") for entry in service_entries)
    assert not any(entry.target.endswith(".log.gz") for entry in service_entries)
    assert len({entry.target for entry in service_entries}) == 98

    with zipfile.ZipFile(extracted / service_source) as archive:
        archived_members = archive.namelist()
    rotated_logs = [name for name in archived_members if name.endswith(".log.gz")]
    plain_originals = {name for name in archived_members if name.endswith(".log")}
    rotated_targets = {name.removesuffix(".gz") for name in rotated_logs}
    assert len(rotated_logs) == 85
    assert len(plain_originals) == 19

    selected_members = {entry.member_relative for entry in service_entries}
    assert rotated_targets <= selected_members
    assert len(selected_members & plain_originals) == 13
    assert selected_members - rotated_targets == selected_members & plain_originals
    assert not any(name.endswith(".log.gz") for name in selected_members)
    assert all((data_dir / entry.target).is_file() for entry in service_entries)

    service_ignored = {
        record.member_relative: record.reason for record in run.ignored if record.source_relative == service_source
    }
    expected_ignored = {
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
    assert service_ignored == expected_ignored
    assert not any(entry.member_relative in expected_ignored for entry in service_entries)

    chr_source = f"{base}/CHR Information/ServiceLogs_20260918.zip"
    chr_entries = [entry for entry in run.entries if entry.route_id == "umf.chr"]
    assert len(chr_entries) == 3
    assert {entry.target for entry in chr_entries} == {
        "chr/nodes/paas-01/health.bil",
        "chr/nodes/paas-02/health_2.bil",
        "chr/nodes/paas-03/health_3.bil",
    }
    assert all(entry.source_relative == chr_source and entry.category == "chr" for entry in chr_entries)
    assert all((data_dir / entry.target).is_file() for entry in chr_entries)
    chr_ignored = {
        record.member_relative: record.reason for record in run.ignored if record.source_relative == chr_source
    }
    assert chr_ignored == {
        "nodes/paas-01/LocalLogReport.csv": "report_not_log",
        "nodes/paas-01/notes.txt": "member_not_selected",
    }

    host_expectations = {
        "umf.host-debug": (
            f"{base}/Host Debugging Logs/DEBUG.tar.gz",
            "host-debug/nodes/paas-01/DEBUG.log",
        ),
        "umf.host-system": (
            f"{base}/Host System Logs/OS.tar.gz",
            "host-system/nodes/paas-01/OS.log",
        ),
    }
    for route_id, (source, target) in host_expectations.items():
        entries = [entry for entry in run.entries if entry.route_id == route_id]
        assert {entry.target for entry in entries} >= {target}
        assert all(entry.source_relative == source and entry.action == "expand" for entry in entries)
        assert not any(entry.target.endswith(".gz") for entry in entries)
        assert (data_dir / target).is_file()


def test_real_package_alarm_fixture_lands_two_alarm_files_and_ignores_non_alarm(tmp_path: Path) -> None:
    """US2 合成包只将 UMF/CSP 告警送入 catalog，非告警 0/ 与 CSP 文件不得落位。"""
    from app.core.archive import unpack
    from app.services.extraction.classification import classify_main_evidence

    package = build_real_package(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)

    umf_source = f"{BASE}/Alarm Information/boundary/umf_alarm_boundary.csv"
    csp_source = "csp-device/0/Problems/Alarm Data/current/csp_alarm_primary.csv"
    inventory_source = "csp-device/0/Problems/Inventory/runtime-inventory.csv"
    service_source = "csp-device/configuration/service.ini"

    for product in ("UMF", "CSP"):
        data_dir = tmp_path / f"alarm-{product.casefold()}"
        evidence_root = data_dir / ".main"
        for source in (umf_source, csp_source, inventory_source):
            target = evidence_root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(extracted / source, target)

        run = classify_main_evidence(data_dir, product=product)

        assert {entry.path for entry in run.catalog} == {
            "alarm/boundary/umf_alarm_boundary.csv",
            "alarm/current/csp_alarm_primary.csv",
        }
        assert {entry.category for entry in run.entries} == {"alarm"}
        assert not any(entry.path == inventory_source for entry in run.catalog)
        assert any(record.source_relative == inventory_source for record in run.ignored)
        for target in ("alarm/boundary/umf_alarm_boundary.csv", "alarm/current/csp_alarm_primary.csv"):
            with (data_dir / target).open(encoding="utf-8", newline="") as stream:
                assert list(csv.DictReader(stream))

    csp_data_dir = tmp_path / "csp-non-alarm"
    csp_service = csp_data_dir / ".main" / service_source
    csp_service.parent.mkdir(parents=True)
    shutil.copy2(extracted / service_source, csp_service)
    csp_run = classify_main_evidence(csp_data_dir, product="CSP")
    assert csp_run.catalog == ()
    assert [record.source_relative for record in csp_run.ignored] == [service_source]


def test_real_package_alarm_boundary_preserves_empty_files_and_rejects_unsafe_member(tmp_path: Path) -> None:
    """固定样例中的 0 字节、仅表头、零记录告警原样落位，路径穿越只产生局部失败。"""
    package = build_real_package(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)

    umf_alarm_dir = f"{BASE}/Alarm Information/boundary"
    umf_sources = [
        f"{umf_alarm_dir}/umf_alarm_empty.csv",
        f"{umf_alarm_dir}/umf_alarm_header_only.csv",
        f"{umf_alarm_dir}/umf_alarm_zero_records.csv",
        f"{umf_alarm_dir}/umf_alarm_boundary.csv",
    ]
    csp_source = "csp-device/0/Alarm Data/current/csp_alarm_without_problems.csv"
    unsafe_source = "csp-device/0/Alarm Data/path-security/alarms.zip"
    sources = [*umf_sources, csp_source, unsafe_source]

    for product in ("UMF", "CSP"):
        data_dir = tmp_path / f"alarm-boundary-{product.casefold()}"
        evidence_root = data_dir / ".main"
        for source in sources:
            target = evidence_root / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(extracted / source, target)

        run = classify_main_evidence(data_dir, product=product)
        entries = {entry.source_relative: entry for entry in run.entries}

        for source in umf_sources:
            entry = entries[source]
            assert (entry.route_id, entry.category) == ("alarm.umf", "alarm")
            assert entry.target == f"alarm/boundary/{Path(source).name}"
            assert (data_dir / entry.target).read_bytes() == (extracted / source).read_bytes()

        csp_entry = entries[csp_source]
        assert (csp_entry.route_id, csp_entry.category) == ("alarm.csp", "alarm")
        assert csp_entry.target == "alarm/current/csp_alarm_without_problems.csv"
        assert (data_dir / csp_entry.target).read_bytes() == (extracted / csp_source).read_bytes()

        assert unsafe_source not in entries
        failures = [failure for failure in run.failures if failure.source_relative == unsafe_source]
        assert len(failures) == 1
        assert failures[0].member_relative is None
        assert failures[0].error_code == "unsafe_path"
        assert "../escape.csv" in failures[0].reason
        assert not (data_dir.parent / "escape.csv").exists()


def test_real_package_corrupt_alarm_archive_keeps_valid_sibling(tmp_path: Path) -> None:
    """固定损坏归档产生可审计局部失败，同一归档的合法成员仍进入 catalog。"""
    package = build_real_package(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)

    source = "csp-device/0/Problems/Alarm Data/archive/alarm_corrupt_member.zip"
    data_dir = tmp_path / "corrupt-alarm"
    target_source = data_dir / ".main" / source
    target_source.parent.mkdir(parents=True)
    shutil.copy2(extracted / source, target_source)

    run = classify_main_evidence(data_dir, product="CSP")

    assert {entry.path for entry in run.catalog} == {"alarm/archive/valid_alarm.csv"}
    assert {(failure.member_relative, failure.error_code) for failure in run.failures} == {
        ("archive/corrupted_alarm.csv", "archive_corrupt")
    }
