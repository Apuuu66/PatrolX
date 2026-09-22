"""真实 App Problem Scene 样例包与分类/规则联动测试。"""

from __future__ import annotations

from pathlib import Path

from app.core.checksum import sha256_file
from app.core.classify import classify_name
from app.inspectors.registry import registry
from app.models.schemas import RuleCategory, RuleStatus
from app.services.executor import RuleContext
from app.services.extraction import extract_main_site
from tests.fixtures.make_real_package import build_real_package


def _extract(tmp_path: Path):
    package_dir = tmp_path / "input"
    package = build_real_package(package_dir)
    data_dir = tmp_path / "task-333"
    manifest = extract_main_site(package, data_dir, sha256_file(package))
    return data_dir, manifest


def _ctx_with_task(tmp_path: Path, files: list[str]) -> RuleContext:
    data_dir = tmp_path / "task-333"
    logs: list[dict] = []

    def log(level: str, message: str, detail: dict | None = None) -> None:
        logs.append({"level": level, "message": message, **(detail or {})})

    ctx = RuleContext(task_id="task-333", data_dir=data_dir, log=log)
    ctx.files = [Path(item) for item in files]
    return ctx


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
        "config/system_info.ini",
        "config/version.ini",
        "kpi/ne333_Call_Session_API_Statistics_5_0_202609020000.csv",
        "kpi/ne333_Container_Metric_Unit_5_0_202609020000.csv",
        "logs/UmfService/logs/paas-192.168.2.2/UmfService.log",
        "logs/UmfService/logs/paas-192.168.2.2/UmfService_20260901011314.log",
        "logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc.log",
        "logs/UMFAcc/logs/paas-192.168.2.2/UMFAcc_20260901011314.log",
    }
    actual = {path.relative_to(data_dir).as_posix() for path in data_dir.rglob("*") if path.is_file()}
    missing = expected - actual
    assert not missing, f"解压现场缺少目标文件: {sorted(missing)}"
    locked_members = [item for item in manifest["files"] if "Container_Metric_Unit" in item["target"]]
    assert locked_members
    assert all(item["classification_reason"] == "archive:member" for item in locked_members)
    assert manifest["main"]["count"] == 5
    assert not manifest["rejected"]


def test_real_container_resource_and_alarm_rule_results(tmp_path: Path) -> None:
    data_dir, _ = _extract(tmp_path)
    registry.load_all()

    resource_ctx = _ctx_with_task(
        tmp_path,
        [
            "kpi/ne333_Container_Metric_Unit_5_0_202609020000.csv",
            "kpi/ne333_Container_Metric_Unit_15_0_202609020000.csv",
        ],
    )
    resource_result = registry.get("resource.check").run(resource_ctx)
    assert resource_result.status == RuleStatus.WARN
    assert resource_result.metrics[0].value >= 1
    assert resource_result.metrics[1].value >= 1

    alarm_ctx = _ctx_with_task(
        tmp_path,
        [
            "alarm/alarm_history_202609010101137101_001.csv",
            "alarm/alarm_history_202609010101137101_002.csv",
        ],
    )
    alarm_result = registry.get("alarm.stat").run(alarm_ctx)
    assert alarm_result.status == RuleStatus.FAIL
    assert alarm_result.metrics[0].value == 6
