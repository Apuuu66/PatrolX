"""真实 App Problem Scene 样例包与分类/规则联动测试。"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.checksum import sha256_file
from app.core.classify import classify_name
from app.core.dicts import load_dicts
from app.inspectors.registry import registry
from app.models.schemas import RuleCategory
from app.services.extraction import extract_main_site
from app.services.inventory.parser import parse_inventory
from tests.fixtures.make_real_package import LST_ME_TXT, build_real_package

DEFAULT_FIXTURE_SHA256 = "a2a8265f5971d66899951187e5ff2634081fc2bf82c25eb9a3b00ad94f69b7cb"


def _extract(tmp_path: Path):
    package_dir = tmp_path / "input"
    package = build_real_package(package_dir)
    data_dir = tmp_path / "task-333"
    manifest = extract_main_site(package, data_dir, sha256_file(package))
    return data_dir, manifest


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


def test_real_package_names_are_classified_by_semantics() -> None:
    assert classify_name("alarm_history_202609010101137101.zip") == RuleCategory.ALARM
    assert classify_name("PerfResult_202609010101137101.zip") == RuleCategory.KPI
    assert classify_name("ServiceLog_20260901011314.zip") == RuleCategory.LOG
    assert classify_name("ne333_Call_Session_API_Statistics_5_0_202609020000.csv") == RuleCategory.KPI
    assert classify_name("ne333_Container_Metric_Unit_5_0_202609020000.csv") == RuleCategory.RESOURCE


def test_real_package_extraction_places_files_by_semantic_category(tmp_path: Path) -> None:
    data_dir, manifest = _extract(tmp_path)

    expected = {
        "alarm/alarm_history_202609010101137101_001.csv",
        "alarm/alarm_history_202609010101137101_002.csv",
        "alarm/alarm_history_202609010101137101_003.csv",
        "config/LST ME.txt",
        "config/system_info.ini",
        "config/version.ini",
        "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv",
        "kpi/ne333_Container_Metric_Unit_5_0_202609020000.csv",
        "logs/CspService/logs/paas-192.168.2.2/CspService.log",
        "logs/CspService/logs/paas-192.168.2.2/CspService_20260901011314.log",
        "logs/CspService/logs/paas-192.168.2.3/CspService.log",
        "logs/UmfService/logs/paas-192.168.2.2/UmfService.log",
        "logs/UmfService/logs/paas-192.168.2.2/UmfService_20260901011314.log",
        "logs/UmfService/logs/paas-192.168.2.3/UmfService.log",
        "logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log",
        "logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc_20260901011314.log",
        "logs/UMFAcc/logs/paas-192.168.2.3/UMFAcc.log",
    }
    actual = {path.relative_to(data_dir).as_posix() for path in data_dir.rglob("*") if path.is_file()}
    missing = expected - actual
    assert not missing, f"解压现场缺少目标文件: {sorted(missing)}"
    locked_members = [item for item in manifest["files"] if "Container_Metric_Unit" in item["target"]]
    assert locked_members
    assert all(item["classification_reason"] == "archive:member" for item in locked_members)
    assert manifest["main"]["count"] == 6
    assert not manifest["rejected"]


def test_real_non_kpi_files_are_preserved_without_active_rules(tmp_path: Path) -> None:
    """非 KPI 数据继续安全落盘，但已下线的业务规则不得重新进入活动目录。"""
    data_dir, manifest = _extract(tmp_path)
    registry.load_all()

    targets = {item["target"] for item in manifest["files"]}
    for prefix in ("alarm/", "config/", "logs/"):
        assert any(target.startswith(prefix) for target in targets)
        assert any(
            path.relative_to(data_dir).as_posix().startswith(prefix) for path in data_dir.rglob("*") if path.is_file()
        )

    active_codes = {rule.code for rule in registry.all()}
    assert active_codes == {"kpi.measurement_units"}
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
    """样例包同时覆盖键值与表格式清单，并统一按上传网元类型筛选。"""
    data_dir, _ = _extract(tmp_path)
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
