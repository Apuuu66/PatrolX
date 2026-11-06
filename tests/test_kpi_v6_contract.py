"""041 KPI 结果工作台 v6 契约守卫。"""

from functools import cache
from pathlib import Path

import yaml

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml"

_EXPECTED_V6_OPERATIONS = {
    ("/api/v6/kpi/tasks/{task_id}/summary", "get"),
    ("/api/v6/kpi/tasks/{task_id}/metrics", "get"),
    (
        "/api/v6/kpi/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/evidence",
        "get",
    ),
    (
        "/api/v6/kpi/tasks/{task_id}/metrics/{measurement_unit_id}/{metric_resource_id}/technical-analysis",
        "get",
    ),
    ("/api/v6/kpi/team-focus/{network_element_type}", "get"),
    ("/api/v6/kpi/team-focus/{network_element_type}", "patch"),
    ("/api/v6/kpi/measurement-units", "get"),
    ("/api/v6/kpi/measurement-units/{network_element_type}/{measurement_unit_id}", "get"),
    ("/api/v6/kpi/measurement-units/{network_element_type}/{measurement_unit_id}", "patch"),
    ("/api/v6/kpi/measurement-bindings", "get"),
    ("/api/v6/kpi/measurement-bindings/{network_element_type}/{binding_id}", "patch"),
    ("/api/v6/kpi/legacy-recovery-audits", "get"),
    ("/api/v6/kpi/legacy-recovery-audits/retry", "post"),
    ("/api/v6/kpi/pending-attributions", "get"),
    ("/api/v6/kpi/pending-attributions/{pending_id}/resolve", "post"),
    ("/api/v6/kpi/maintenance-operations/{operation_id}", "get"),
    ("/api/v6/kpi/rule-network-assignments", "get"),
    ("/api/v6/kpi/rule-network-assignments/batch", "post"),
    ("/api/v6/kpi/rule-network-assignments/audits", "get"),
    ("/api/v6/kpi/rule-network-assignments/{rule_code}", "patch"),
    ("/api/v3/tasks", "post"),
}


@cache
def _load_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _resolve(contract: dict, value: dict) -> dict:
    ref = value.get("$ref")
    if not isinstance(ref, str):
        return value
    current: object = contract
    for part in ref.removeprefix("#/").split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    assert isinstance(current, dict)
    return current


def _response_error_codes(contract: dict, operation: dict, status: str) -> set[str]:
    response = _resolve(contract, operation["responses"][status])
    content = response.get("content", {}).get("application/json", {})
    schema = _resolve(contract, content.get("schema", {}))
    assert schema.get("type") == "object", schema
    assert {"code", "message"} <= set(schema.get("properties", {})), schema
    assert set(schema.get("required", [])) == {"code", "message"}, schema
    return {
        example["value"]["code"]
        for example in content.get("examples", {}).values()
        if isinstance(example.get("value"), dict) and "code" in example["value"]
    }


def test_v6_contract_exposes_all_planned_v6_operations() -> None:
    contract = _load_contract()
    missing = sorted(
        f"{method.upper()} {path}"
        for path, method in _EXPECTED_V6_OPERATIONS
        if method not in contract.get("paths", {}).get(path, {})
    )
    assert missing == []


def test_v6_contract_has_governed_errors_pagination_and_created_responses() -> None:
    contract = _load_contract()
    error = contract["components"]["schemas"]["Error"]
    assert set(error["properties"]) == {"code", "message", "detail"}
    assert set(error["required"]) == {"code", "message"}

    for schema_name in (
        "KpiTeamFocusPageV6",
        "KpiMetricResultPageV6",
        "KpiMeasurementUnitPageV6",
        "KpiMeasurementBindingPageV6",
        "KpiRuleNetworkAssignmentPageV6",
    ):
        schema = contract["components"]["schemas"][schema_name]
        assert {"page", "page_size", "total"} <= set(schema["properties"]), schema_name
        assert {"page", "page_size", "total"} <= set(schema["required"]), schema_name

    for path in ("/api/v3/tasks", "/api/v2/tasks/{task_id}/rebuild"):
        operation = contract["paths"][path]["post"]
        assert "202" in operation["responses"]
        response = _resolve(contract, operation["responses"]["202"])
        assert "Location" in response.get("headers", {}), path


def test_kpi_evidence_source_preserves_all_raw_source_column_names() -> None:
    contract = _load_contract()
    sources = contract["components"]["schemas"]["KpiMetricEvidenceV6"]["properties"]["sources"]
    source_schema = _resolve(contract, sources["items"])

    assert "raw_source_names" in source_schema["properties"]
    assert source_schema["properties"]["raw_source_names"]["type"] == "array"
    assert source_schema["properties"]["raw_source_names"]["items"]["type"] == "string"
    assert {"file", "raw_source_names"} <= set(source_schema["required"])


def test_team_focus_patch_declares_both_atomic_conflicts() -> None:
    contract = _load_contract()
    operation = contract["paths"]["/api/v6/kpi/team-focus/{network_element_type}"]["patch"]
    response = _resolve(contract, operation["responses"]["409"])
    content = response["content"]["application/json"]
    examples = content.get("examples", {})
    codes = {item["value"]["code"] for item in examples.values()}
    assert codes == {"task_result_requires_rebuild", "team_focus_revision_conflict"}
    schema = _resolve(contract, content["schema"])
    assert {"code", "message"} <= set(schema["properties"])


def test_v5_contract_is_frozen_and_legacy_entries_are_deprecated() -> None:
    contract = _load_contract()
    schemas = contract["components"]["schemas"]

    request = schemas["KpiMeasurementBindingBatchConfirmRequest"]
    assert set(request["required"]) == {"binding_ids"}
    assert request["properties"]["binding_ids"]["type"] == "array"
    response = schemas["KpiMeasurementBindingBatchConfirmResponse"]
    assert set(response["required"]) == {"total", "succeeded", "failed", "items"}

    assert contract["paths"]["/api/v5/kpi/measurement-bindings/batch-confirm"]["post"]["deprecated"] is True
    for path in ("/api/v2/inspector-states", "/api/v2/inspector-states/{rule_code}/enabled"):
        operations = contract["paths"][path]
        assert all(
            operation.get("deprecated") is True
            for method, operation in operations.items()
            if method in {"get", "put", "post", "patch", "delete"}
        )
