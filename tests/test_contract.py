"""契约文件与 FastAPI 实现的一致性测试。"""

import yaml

from app.contract.export import CONTRACT_PATH, diff_contracts, generate_openapi


def _load_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_is_valid_openapi() -> None:
    contract = _load_contract()
    assert contract["openapi"].startswith("3.")
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
    ):
        assert name in schemas, f"缺少 schema: {name}"


def _parameter_name(spec: dict, parameter: dict) -> str:
    if "$ref" in parameter:
        return spec["components"]["parameters"][parameter["$ref"].split("/")[-1]]["name"]
    return parameter.get("name")
