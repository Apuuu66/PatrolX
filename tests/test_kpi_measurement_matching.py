"""测量单元任务文件匹配测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.db import init_db
from app.services.kpi_measurement_units import filename_fragment, match_measurement_files


@pytest.fixture(autouse=True)
def _database() -> None:
    init_db()


def test_filename_fragment_is_case_sensitive_shape() -> None:
    assert filename_fragment("Call Session API Statistics") == "Call_Session_API_Statistics"


def test_match_measurement_files_states(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import import_resource_csv, io

    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_MATCH,呼叫统计,Call Session API Statistics\n"
            "MU_LEFT,接口左,A B\n"
            "MU_RIGHT,接口右,B C\n"
        )
    )
    files = [
        ("ne333_Call_Session_API_Statistics_15_0_202609020000.csv", tmp_path / "matched.csv"),
        ("ne333_call_session_api_statistics_15_0_202609020000.csv", tmp_path / "lower.csv"),
        ("ne333_unknown_file_15_0_202609020000.csv", tmp_path / "unknown.csv"),
        ("ne333_A_B_C_15_0_202609020000.csv", tmp_path / "ambiguous.csv"),
    ]
    for _, path in files:
        path.write_text("a,b,c\n", encoding="utf-8")
    result = match_measurement_files(files)
    by_name = {item["filename"]: item for item in result["files"]}
    assert by_name["ne333_Call_Session_API_Statistics_15_0_202609020000.csv"]["status"] == "matched"
    assert by_name["ne333_call_session_api_statistics_15_0_202609020000.csv"]["status"] == "unmatched"
    assert by_name["ne333_unknown_file_15_0_202609020000.csv"]["status"] == "unmatched"
    assert by_name["ne333_A_B_C_15_0_202609020000.csv"]["status"] == "ambiguous"


def test_disabled_measurement_unit_file_is_visible_but_skipped(tmp_path: Path) -> None:
    from app.services.kpi_measurement_units import import_resource_csv, io, set_measurement_unit_enabled

    import_resource_csv(io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\n"))
    set_measurement_unit_enabled("MU_CALL", False)
    path = tmp_path / "disabled.csv"
    path.write_text("a,b,c\n", encoding="utf-8")
    result = match_measurement_files([("ne333_Call_Statistics_15_0_202609020000.csv", path)])
    assert result["files"][0]["status"] == "disabled"


def test_kpi_rule_consumes_only_classified_kpi_catalog_paths(tmp_path: Path) -> None:
    """分类只稳定 KPI 输入路径，既有规则版本、扫描模式和判定入口保持不变。"""
    import shutil

    from app.core.archive import unpack
    from app.inspectors.registry import registry
    from app.services.extraction.classification import classify_main_evidence
    from app.services.scanning import TaskFileCatalog
    from tests.fixtures.make_real_package import build_real_package

    package = build_real_package(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)

    base = "Outer Device/Problem 038/wrapper/UMF Problem Scene"
    data_dir = tmp_path / "task"
    shutil.copytree(extracted / base, data_dir / ".main" / base)
    run = classify_main_evidence(data_dir, product="UMF")

    kpi_paths = {Path(entry.path) for entry in run.catalog if entry.path.startswith("kpi/")}
    assert len(kpi_paths) == 73

    catalog_paths = TaskFileCatalog.build(data_dir).paths()
    assert any(path.parts[0] == "other" for path in catalog_paths)

    registry.load_all()
    kpi_rule = registry.get("kpi.measurement_units")
    assert kpi_rule.rule_version == "3.3.0"
    assert kpi_rule.source_patterns == [r"^kpi/.*\.csv$", r"^traffic/.*\.csv$"]
    assert set(TaskFileCatalog.build(data_dir).match(kpi_rule.source_patterns or [])) == kpi_paths
    assert all(path.parts[0] == "kpi" for path in kpi_paths)
