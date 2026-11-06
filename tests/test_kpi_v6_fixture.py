"""KPI v6 代表性合成夹具的成功率语义与作用域隔离测试。"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

from app.core.checksum import sha256_file
from tests.fixtures import make_real_package as fixture_module

MANIFEST_PATH = "KPI/v6-workbench-fixture-manifest.json"


def _build(directory: Path, network_element_type: str = "UMF") -> Path:
    builder = getattr(fixture_module, "build_kpi_v6_workbench_fixture", None)
    assert callable(builder), "缺少 v6 代表性合成夹具生成器"
    return builder(directory, network_element_type=network_element_type)


def _load_manifest(package: Path) -> dict[str, object]:
    with zipfile.ZipFile(package) as outer:
        return json.loads(outer.read(MANIFEST_PATH))


def _load_rows(package: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(package) as outer:
        performance_name = next(name for name in outer.namelist() if name.endswith("PerfResult_20261105000000.zip"))
        with zipfile.ZipFile(io.BytesIO(outer.read(performance_name))) as performance:
            csv_name = next(name for name in performance.namelist() if name.endswith(".csv"))
            return list(csv.DictReader(io.StringIO(performance.read(csv_name).decode("utf-8-sig").split("\n", 2)[2])))


def _build_log_supplement(directory: Path) -> Path:
    builder = getattr(fixture_module, "build_kpi_v6_log_supplement_fixture", None)
    assert callable(builder), "缺少 v6 日志补充包合成夹具生成器"
    return builder(directory)


def test_kpi_v6_fixture_is_repeatable_and_contains_20_base_metrics_with_10_focus_items(tmp_path: Path) -> None:
    first = _build(tmp_path / "first", "UMF")
    second = _build(tmp_path / "second", "UMF")

    assert sha256_file(first) == sha256_file(second)
    manifest = _load_manifest(first)
    metrics = manifest["metrics"]
    assert isinstance(metrics, list)
    assert manifest["schema_version"] == 1
    assert manifest["package_kind"] == "kpi_v6_workbench"
    assert manifest["network_element_type"] == "UMF"
    assert manifest["metric_count"] == 20
    assert len(metrics) == 20
    assert len({item["metric_resource_id"] for item in metrics}) == 20
    assert {item["role"] for item in metrics} == {"base"}
    assert all("formula" not in item or item["formula"] is None for item in metrics)

    focus_ids = set(manifest["team_focus_metric_resource_ids"])
    assert len(focus_ids) == manifest["team_focus_count"] == 10
    assert {item["metric_resource_id"] for item in metrics if item["team_focus"]} == focus_ids
    assert {item["metric_group"] for item in metrics if item["team_focus"]} == {
        "media_resource_creation",
        "media_resource_modification",
        "media_resource_deletion",
    }
    assert {item["expected_needs_attention_group"] for item in metrics if item["team_focus"]} >= {
        "failure",
        "warning",
        "trend_degraded",
        "unjudgeable",
        "needs_config",
    }
    assert {item["expected_needs_attention_group"] for item in metrics if item["team_focus"]} == {
        "failure",
        "warning",
        "trend_degraded",
        "unjudgeable",
        "needs_config",
    }
    assert manifest["same_metric_ids_across_network_types"] is True
    assert manifest["team_focus_scope"] == {
        "network_element_type": "UMF",
        "shared_across_tasks": True,
        "contains_device_dimension": False,
    }

    historical_recovery = manifest["historical_recovery"]
    assert isinstance(historical_recovery, list)
    assert {item["object_kind"] for item in historical_recovery} == {"metric", "binding", "derived"}
    assert all(item["legacy_enabled"] is False for item in historical_recovery)
    assert all(item["expects_recovery_audit"] is True for item in historical_recovery)
    assert all(item["inspection_effect"] == "none" for item in historical_recovery)

    rule_assignments = manifest["rule_assignments"]
    assert rule_assignments == [
        {
            "rule_code": "kpi.media.call_quality",
            "network_element_types": ["CSP", "UMF"],
        },
        {
            "rule_code": "kpi.media.umf_only",
            "network_element_types": ["UMF"],
        },
        {
            "rule_code": "kpi.media.unassigned",
            "network_element_types": [],
        },
    ]


def test_kpi_v6_fixture_merges_success_rate_aliases_and_keeps_missing_source_value_missing(tmp_path: Path) -> None:
    umf_manifest = _load_manifest(_build(tmp_path / "umf", "UMF"))
    csp_manifest = _load_manifest(_build(tmp_path / "csp", "CSP"))

    alias_groups = csp_manifest["success_rate_alias_groups"]
    assert isinstance(alias_groups, dict)
    creation_names = alias_groups["ME_MEDIA_CREATION_SUCCESS_RATE"]
    data_channel_names = alias_groups["ME_DATA_CHANNEL_UPDATE_SUCCESS_RATE"]
    assert creation_names == [
        "Media Resource Creation Success Rate(%)",
        "Media Resource Creation Requests Success Rate(%)",
    ]
    assert data_channel_names == [
        "DC Resource Update Success Rate(%)",
        "Data Channel Resource Update Requests Success Rate(%)",
    ]

    metrics = csp_manifest["metrics"]
    assert isinstance(metrics, list)
    by_id = {item["metric_resource_id"]: item for item in metrics}
    for metric_id, names in alias_groups.items():
        assert by_id[metric_id]["role"] == "base"
        assert by_id[metric_id]["raw_source_names"] == names
        assert len([item for item in metrics if item["metric_resource_id"] == metric_id]) == 1

    umf_rows = _load_rows(_build(tmp_path / "umf-rows", "UMF"))
    csp_rows = _load_rows(_build(tmp_path / "csp-rows", "CSP"))
    creation_name = creation_names[0]
    assert umf_rows[-2][creation_name] == "75.0"
    # 成功率是源包直出值，故意不等于 129 / 200 的可计算结果，防止被重算。
    assert umf_rows[-1][creation_name] == "63.7"
    assert round(129 / 200 * 100, 1) == 64.5
    assert csp_rows[-1][creation_name] == ""
    assert csp_rows[-1]["Number of Media Resource Creation Requests(times)"] == "200"
    assert csp_rows[-1]["Number of Success Responses to Media Resource Creation Requests(times)"] == "129"
    assert csp_rows[-1]["Number of Failure Responses to Media Resource Creation Requests(times)"] == "71"
    assert csp_manifest["missing_success_rate_source"] == {
        "metric_resource_id": "ME_MEDIA_CREATION_SUCCESS_RATE",
        "raw_source_name": creation_name,
        "expected_value": None,
        "related_evidence_is_non_calculation_input": True,
    }
    assert "missing_success_rate_source" not in umf_manifest
    csp_by_id = {item["metric_resource_id"]: item for item in metrics}
    assert csp_by_id["ME_MEDIA_CREATION_SUCCESS_RATE"]["expected_needs_attention_group"] == "unjudgeable"

    umf_metrics = umf_manifest["metrics"]
    assert isinstance(umf_metrics, list)
    umf_by_id = {item["metric_resource_id"]: item for item in umf_metrics}
    assert umf_by_id["ME_MEDIA_CREATION_SUCCESS_RATE"]["expected_needs_attention_group"] == "failure"
    assert {item["measurement_unit_id"] for item in umf_metrics} == {item["measurement_unit_id"] for item in metrics}
    assert {item["metric_resource_id"] for item in umf_metrics} == set(by_id)


def test_kpi_v6_log_supplement_fixture_is_repeatable_and_requires_one_network_type(tmp_path: Path) -> None:
    first = _build_log_supplement(tmp_path / "first")
    second = _build_log_supplement(tmp_path / "second")

    assert sha256_file(first) == sha256_file(second)
    manifest = _load_manifest(first)
    assert manifest["package_kind"] == "log_supplement"
    assert manifest["package_name"] == first.name
    assert manifest["rule_network_element_type"] is None
    assert manifest["allowed_rule_network_element_types"] == ["UMF", "CSP"]
    assert manifest["log_source_files"] == ["CspService/logs/paas-192.168.2.2/CspService.log"]
