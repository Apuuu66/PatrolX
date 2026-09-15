"""契约文件与 FastAPI 实现的一致性测试。"""

from pathlib import Path

import yaml

from app.contract.export import CONTRACT_PATH, diff_contracts, generate_openapi


def _load_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_is_valid_openapi() -> None:
    contract = _load_contract()
    assert contract["openapi"].startswith("3.0")
    assert contract["info"]["title"] == "PatrolX API"
    assert "paths" in contract and contract["paths"]


def test_contract_matches_fastapi_impl() -> None:
    contract = _load_contract()
    generated = generate_openapi()
    issues = diff_contracts(generated, contract)
    assert issues == []


def test_core_schemas_present() -> None:
    schemas = _load_contract()["components"]["schemas"]
    for name in (
        "InspectionTask",
        "SystemInspection",
        "RuleResult",
        "Metric",
        "Finding",
        "Summary",
        "InspectorInfo",
        "DictsResponse",
        "Error",
        "TaskDeleteErrorV2",
        "TaskDeleteErrorDetailV2",
    ):
        assert name in schemas, f"缺少 schema: {name}"


def _parameter_name(spec: dict, parameter: dict) -> str:
    if "$ref" in parameter:
        return spec["components"]["parameters"][parameter["$ref"].split("/")[-1]]["name"]
    return parameter.get("name")


def test_openapi_contract_declares_kpi_record_query() -> None:
    spec = yaml.safe_load((Path(__file__).resolve().parents[1] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    rule_path = spec["paths"]["/api/v2/tasks/{task_id}/rules/{rule_code}"]["get"]
    parameter_names = {p.get("name") or p.get("$ref", "").split("/")[-1] for p in rule_path.get("parameters", [])}
    assert "exclude_records" in parameter_names

    records_path = spec["paths"]["/api/v2/tasks/{task_id}/rules/{rule_code}/kpi/records"]["get"]
    assert records_path["operationId"] == "listKpiRecordsV2"
    names = {_parameter_name(spec, p) for p in records_path.get("parameters", [])}
    assert {"metric_key", "source_file", "period_minutes", "status", "page", "page_size"} <= names

    schemas = spec["components"]["schemas"]
    assert {"KpiRecordPageV2", "KpiRecordItemV2"} <= set(schemas)
