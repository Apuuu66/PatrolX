"""KPI 日健康代表性样例包的固定内容与边界覆盖。"""

from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from pathlib import Path

from app.core.archive import unpack
from app.core.checksum import sha256_file
from app.services.extraction.classification import classify_main_evidence
from app.services.scanning import TaskFileCatalog
from tests.fixtures.make_real_package import (
    KPI_DAILY_HEALTH_PACKAGE_NAME,
    UMF_SCENE_ROOT,
    build_kpi_daily_health_fixture,
)
from tests.manifest_helpers import write_catalog_manifest

MANIFEST_PATH = "KPI/daily-health-fixture-manifest.json"


def _load_fixture(package: Path) -> tuple[dict[str, object], dict[str, list[dict[str, str]]]]:
    with zipfile.ZipFile(package) as outer:
        manifest = json.loads(outer.read(MANIFEST_PATH))
        perf_name = next(name for name in outer.namelist() if name.endswith("PerfResult_20261105000000.zip"))
        with zipfile.ZipFile(io.BytesIO(outer.read(perf_name))) as perf:
            files = {
                Path(name).name: list(csv.DictReader(io.StringIO(perf.read(name).decode("utf-8"))))
                for name in perf.namelist()
                if name.endswith(".csv")
            }
    return manifest, files


def test_kpi_daily_health_fixture_covers_metrics_units_and_boundaries(tmp_path: Path) -> None:
    package = build_kpi_daily_health_fixture(tmp_path)

    assert package.name == KPI_DAILY_HEALTH_PACKAGE_NAME
    manifest, files = _load_fixture(package)
    metrics = manifest["metrics"]
    assert isinstance(metrics, list)
    assert manifest["schema_version"] == 1
    assert manifest["data_date"] == "2026-11-05"
    assert manifest["metric_count"] == 20
    assert len(metrics) == len({item["metric_resource_id"] for item in metrics}) == 20
    assert {item["measurement_unit_id"] for item in metrics} == {
        "MU_CALL",
        "MU_HEALTH_CALL",
        "MU_HEALTH_SIGNAL",
        "MU_HEALTH_MEDIA",
    }

    current_counts = manifest["expected_current_counts"]
    trend_counts = manifest["expected_trend_counts"]
    assert set(current_counts) == {
        "normal",
        "warn",
        "fail",
        "pending_config",
        "unable_to_judge",
        "not_applicable",
    }
    assert set(trend_counts) == {"improved", "stable", "worsened", "observe", "no_baseline"}
    assert all(value > 0 for value in current_counts.values())
    assert all(value > 0 for value in trend_counts.values())
    assert sum(current_counts.values()) == sum(trend_counts.values()) == 20

    boundaries = manifest["boundaries"]
    assert boundaries["zero_denominator_metric_ids"] == ["ME_HEALTH_RATE_2"]
    assert set(boundaries["no_data_metric_ids"]) == {
        "ME_HEALTH_REGISTERED_USERS",
        "ME_HEALTH_ALARM_COUNT",
    }
    assert boundaries["all_zero_unknown_metric_ids"] == ["ME_HEALTH_CALL_QUALITY"]
    quality = next(item for item in metrics if item["metric_resource_id"] == "ME_HEALTH_CALL_QUALITY")
    assert quality["expected_current_status"] == "pending_config"
    assert boundaries["success_rate_evidence"] == {
        "metric_resource_id": "ME_HEALTH_RATE_1",
        "numerator": 129,
        "denominator": 200,
        "value": 64.5,
    }
    assert boundaries["disabled_measurement_unit_ids"] == ["MU_DISABLED_E2E"]
    assert boundaries["out_of_scope_files"] == ["ne333_Disabled_E2E_15_0_20261105000000.csv"]
    assert boundaries["legacy_task_without_daily_health"] is True

    raw_columns = {column for item in metrics for column in item["raw_columns"]}
    present_columns = {column for rows in files.values() for column in rows[0]}
    assert raw_columns <= present_columns
    assert {item["raw_columns"][0] for item in metrics if item["role"] == "derived"} <= present_columns
    rate_rows = files["ne333_Health_Call_15_0_20261105000000.csv"]
    latest = rate_rows[-1]
    assert (
        latest["媒体资源创建成功率分子"],
        latest["媒体资源创建成功率分母"],
        latest["媒体资源创建成功率"],
    ) == (
        "129",
        "200",
        "64.5",
    )
    assert len(files) == 5


def test_kpi_daily_health_fixture_uses_catalog_names_and_unique_rate_evidence_columns(tmp_path: Path) -> None:
    package = build_kpi_daily_health_fixture(tmp_path)
    manifest, files = _load_fixture(package)
    metrics = manifest["metrics"]
    assert isinstance(metrics, list)

    for metric in metrics:
        assert metric["name_zh"] in metric["raw_columns"]

    rate_metrics = [metric for metric in metrics if metric["role"] == "derived"]
    evidence_columns = [
        column for metric in rate_metrics for column in metric["raw_columns"] if column != metric["name_zh"]
    ]
    assert len(evidence_columns) == 8
    assert len(set(evidence_columns)) == 8

    rate_rows = files["ne333_Health_Call_15_0_20261105000000.csv"]
    assert "媒体资源创建成功率" in rate_rows[0]
    assert "媒体资源创建成功率分子" in rate_rows[0]
    assert "媒体资源创建成功率分母" in rate_rows[0]


def test_kpi_daily_health_fixture_is_byte_repeatable(tmp_path: Path) -> None:
    first = build_kpi_daily_health_fixture(tmp_path / "first")
    second = build_kpi_daily_health_fixture(tmp_path / "second")

    assert sha256_file(first) == sha256_file(second)


def test_kpi_daily_health_fixture_runs_through_real_classification(tmp_path: Path) -> None:
    """合成包必须按真实 UMF 场景结构进入 kpi/，不能依赖 E2E 种子绕过巡检链路。"""
    package = build_kpi_daily_health_fixture(tmp_path / "input")
    extracted = tmp_path / "extracted"
    unpack(package, extracted)
    data_dir = tmp_path / "task"
    shutil.copytree(extracted / UMF_SCENE_ROOT, data_dir / ".main" / UMF_SCENE_ROOT)

    run = classify_main_evidence(data_dir, product="UMF")
    write_catalog_manifest(data_dir, [entry.path for entry in run.catalog])
    kpi_paths = {Path(entry.path) for entry in run.catalog if entry.path.startswith("kpi/")}

    assert len(kpi_paths) == 5
    assert Path("kpi/ne333_Health_Call_15_0_20261105000000.csv") in kpi_paths
    assert Path("kpi/ne333_Disabled_E2E_15_0_20261105000000.csv") in kpi_paths
    catalog_paths = TaskFileCatalog.build(data_dir).paths()
    assert kpi_paths <= set(catalog_paths)
