"""契约文件与 FastAPI 实现的一致性测试。

含版本入口治理守卫 G-01/G-02/G-03（contracts/api-surface-delta.md）；
G-04（生成客户端零漂移）由 CI 门禁以 git diff 校验，不在 pytest 内。
"""

import re

import yaml
from fastapi import APIRouter

from app.api import router as router_module
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


_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})
_VERSION_PATH = re.compile(r"^/api/v(?P<version>\d+)/(?P<rest>.*)$")


def _iter_operations(contract: dict) -> list[tuple[str, str, dict]]:
    """遍历 路径 × 方法，产出 (路径, 方法, 操作对象)。"""
    operations: list[tuple[str, str, dict]] = []
    for path, item in contract.get("paths", {}).items():
        for method, operation in item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operations.append((path, method.upper(), operation))
    return operations


def _version_bucket(path: str) -> tuple[int, str] | None:
    """把 /api/v{N}/... 拆成 (版本号, 去版本前缀路径)；非版本路径返回 None。"""
    match = _VERSION_PATH.match(path)
    if match is None:
        return None
    return int(match.group("version")), match.group("rest")


def _operation_id_violations(contract: dict) -> list[str]:
    """G-01：operationId 必须唯一且非空，返回带方法/路径的违规说明。"""
    violations: list[str] = []
    sites: dict[str, list[str]] = {}
    for path, method, operation in _iter_operations(contract):
        operation_id = operation.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            violations.append(f"{method} {path} 缺少 operationId")
            continue
        sites.setdefault(operation_id, []).append(f"{method} {path}")
    for operation_id, locations in sites.items():
        if len(locations) > 1:
            violations.append(f"operationId 重复：{operation_id} 出现在 {'、'.join(locations)}")
    return violations


def _contract_version_prefixes(contract: dict) -> dict[str, list[str]]:
    """契约中 /api/v{N} 前缀 → 该前缀下的操作；空列表即空壳前缀。"""
    prefixes: dict[str, list[str]] = {}
    for path, item in contract.get("paths", {}).items():
        bucket = _version_bucket(path)
        if bucket is None:
            continue
        prefix = f"/api/v{bucket[0]}"
        operations = prefixes.setdefault(prefix, [])
        for method, operation in item.items():
            if method.lower() in _HTTP_METHODS and isinstance(operation, dict):
                operations.append(f"{method.upper()} {path}")
    return prefixes


def _registered_version_prefixes() -> set[str]:
    """从 app.api.router 枚举 APIRouter 实例的版本前缀（含 ``router`` 与 ``*_router``）。"""
    prefixes: set[str] = set()
    for value in vars(router_module).values():
        if isinstance(value, APIRouter) and _VERSION_PATH.match(f"{value.prefix}/"):
            prefixes.add(value.prefix)
    return prefixes


def _version_prefix_violations(contract: dict, registered_prefixes: set[str]) -> list[str]:
    """G-02：契约与代码注册的版本前缀必须一致，且每个前缀至少一个真实操作。"""
    contract_prefixes = _contract_version_prefixes(contract)
    violations: list[str] = []
    for prefix in sorted(set(contract_prefixes) | set(registered_prefixes)):
        operations = contract_prefixes.get(prefix)
        if operations is None:
            violations.append(f"代码注册但契约无操作：{prefix} 是空版本前缀，契约中没有任何对应操作")
        elif not operations:
            violations.append(f"契约空版本前缀：{prefix} 下没有任何操作")
        elif prefix not in registered_prefixes:
            violations.append(f"契约出现但代码未注册：{prefix} 出现在契约，但 app.api.router 未注册该版本前缀")
    return violations


def _capability_violations(contract: dict) -> list[str]:
    """G-03：同一能力（方法 + 去版本前缀路径）的旧入口须废弃并注明替代路径。"""
    groups: dict[tuple[str, str], list[tuple[int, str, dict]]] = {}
    for path, method, operation in _iter_operations(contract):
        bucket = _version_bucket(path)
        if bucket is None:
            continue
        groups.setdefault((method, bucket[1]), []).append((bucket[0], path, operation))

    violations: list[str] = []
    for (method, _rest), entries in groups.items():
        entries.sort(key=lambda item: item[0])
        if len(entries) == 1:
            _version, path, operation = entries[0]
            description = str(operation.get("description") or "")
            if operation.get("deprecated") and "不适用" not in description:
                violations.append(f"{method} {path} 已废弃但未注明替代入口：无更新版本入口时需说明替代入口或不适用")
            continue

        _current_version, current_path, current_operation = entries[-1]
        if current_operation.get("deprecated"):
            violations.append(f"{method} {current_path} 是最高版本入口却标记 deprecated，同一能力只允许一个当前入口")
        for _version, path, operation in entries[:-1]:
            if not operation.get("deprecated"):
                violations.append(f"{method} {path} 为旧入口但未标记 deprecated: true（当前入口 {current_path}）")
                continue
            description = str(operation.get("description") or "")
            if current_path not in description:
                violations.append(f"{method} {path} 标记 deprecated 但描述未注明替代入口 {current_path}")
    return violations


def _synthetic_contract(operations: list[tuple[str, str, dict[str, object]]]) -> dict:
    """按 (path, method, operation) 构造最小契约，供守卫合成用例使用。"""
    paths: dict[str, dict[str, object]] = {}
    for path, method, operation in operations:
        paths.setdefault(path, {})[method.lower()] = operation
    return {"openapi": "3.1.0", "info": {"title": "synthetic", "version": "0"}, "paths": paths}


def test_operation_ids_unique_and_non_empty() -> None:
    """G-01：operationId 必须唯一且非空，失败信息需指出重复项与涉及路径。"""
    duplicated = _synthetic_contract(
        [
            ("/api/v1/alpha", "GET", {"operationId": "getAlpha"}),
            ("/api/v2/alpha", "GET", {"operationId": "getAlpha"}),
        ]
    )
    violations = _operation_id_violations(duplicated)
    assert any("getAlpha" in item for item in violations), violations
    assert any("/api/v1/alpha" in item and "/api/v2/alpha" in item for item in violations), violations

    missing = _synthetic_contract([("/api/v1/beta", "POST", {})])
    violations = _operation_id_violations(missing)
    assert any("POST /api/v1/beta" in item for item in violations), violations

    assert _operation_id_violations(_load_contract()) == []


def test_no_empty_version_prefix() -> None:
    """G-02：代码注册的版本前缀与契约版本前缀必须一致，且每个前缀至少一个操作。"""
    contract = _synthetic_contract(
        [
            ("/api/v1/alpha", "GET", {"operationId": "getAlpha"}),
            ("/api/v2/alpha", "GET", {"operationId": "getAlphaV2"}),
        ]
    )
    hollow_router = _version_prefix_violations(contract, {"/api/v1", "/api/v2", "/api/v4"})
    assert any("/api/v4" in item and "空" in item for item in hollow_router), hollow_router

    orphan_contract = _version_prefix_violations(contract, {"/api/v1"})
    assert any("/api/v2" in item for item in orphan_contract), orphan_contract

    hollow_path = {
        "openapi": "3.1.0",
        "info": {"title": "synthetic", "version": "0"},
        "paths": {"/api/v4/alpha": {"parameters": []}},
    }
    hollow_path_violations = _version_prefix_violations(hollow_path, {"/api/v4"})
    assert any("/api/v4" in item and "空" in item for item in hollow_path_violations), hollow_path_violations

    assert _version_prefix_violations(_load_contract(), _registered_version_prefixes()) == []


def test_single_current_entry_per_capability() -> None:
    """G-03：同一能力的最高版本入口必须未废弃，其余入口须废弃并注明替代路径。"""
    stale = _synthetic_contract(
        [
            ("/api/v1/tasks", "POST", {"operationId": "createTaskV1", "description": "旧入口"}),
            (
                "/api/v2/tasks",
                "POST",
                {
                    "operationId": "createTaskV2",
                    "deprecated": True,
                    "description": "已被 /api/v3/tasks 取代",
                },
            ),
            ("/api/v3/tasks", "POST", {"operationId": "createTaskV3", "description": "当前入口"}),
        ]
    )
    violations = _capability_violations(stale)
    assert any("POST /api/v1/tasks" in item and "deprecated" in item for item in violations), violations
    assert len(violations) == 1, violations

    current_deprecated = _synthetic_contract(
        [
            (
                "/api/v1/tasks",
                "POST",
                {
                    "operationId": "createTaskV1",
                    "deprecated": True,
                    "description": "已被 /api/v2/tasks 取代",
                },
            ),
            ("/api/v2/tasks", "POST", {"operationId": "createTaskV2", "deprecated": True}),
        ]
    )
    violations = _capability_violations(current_deprecated)
    assert any("POST /api/v2/tasks" in item for item in violations), violations

    missing_replacement = _synthetic_contract(
        [
            ("/api/v1/tasks", "POST", {"operationId": "createTaskV1", "deprecated": True}),
            ("/api/v2/tasks", "POST", {"operationId": "createTaskV2", "description": "当前入口"}),
        ]
    )
    violations = _capability_violations(missing_replacement)
    assert any("/api/v1/tasks" in item and "/api/v2/tasks" in item for item in violations), violations

    no_successor = _synthetic_contract(
        [
            (
                "/api/v1/legacy",
                "GET",
                {"operationId": "getLegacy", "deprecated": True, "description": "无替代入口，不适用"},
            )
        ]
    )
    assert _capability_violations(no_successor) == []

    undocumented = _synthetic_contract(
        [("/api/v1/legacy", "GET", {"operationId": "getLegacy", "deprecated": True, "description": "旧接口"})]
    )
    assert any("/api/v1/legacy" in item for item in _capability_violations(undocumented))

    assert _capability_violations(_load_contract()) == []


def _is_nullable(prop: dict) -> bool:
    """判断属性 schema 是否允许 null（anyOf 含 null 分支）。"""
    return any(item.get("type") == "null" for item in prop.get("anyOf", []))


def _non_null_branch(prop: dict) -> dict:
    """取 anyOf 中的非 null 分支；无 anyOf 时返回原 schema。"""
    branches = prop.get("anyOf")
    if branches is None:
        return prop
    return next(item for item in branches if item.get("type") != "null")


def test_task_run_fields_nullable_in_contract() -> None:
    """FR-008/FR-009：last_run_at 与 duration_ms 可空，duration_ms >= 0，均非必填。"""
    schemas = _load_contract()["components"]["schemas"]
    for name in ("InspectionTask", "TaskSummary"):
        schema = schemas[name]
        properties = schema["properties"]
        last_run_at = properties["last_run_at"]
        assert _is_nullable(last_run_at), f"{name}.last_run_at 必须可空"
        branch = _non_null_branch(last_run_at)
        assert branch.get("type") == "string" and branch.get("format") == "date-time", name

        duration_ms = properties["duration_ms"]
        assert _is_nullable(duration_ms), f"{name}.duration_ms 必须可空"
        branch = _non_null_branch(duration_ms)
        assert branch.get("type") == "integer" and branch.get("minimum") == 0, name

        required = schema.get("required", [])
        assert "last_run_at" not in required, name
        assert "duration_ms" not in required, name


def test_scene_cleaned_returns_410_in_contract() -> None:
    """FR-011：报告、日志、重跑、重建在现场清理后返回 410 并说明留存语义。"""
    paths = _load_contract()["paths"]
    for path, method in (
        ("/api/v2/tasks/{task_id}/report", "get"),
        ("/api/v2/tasks/{task_id}/logs", "get"),
        ("/api/v2/tasks/{task_id}/rerun", "post"),
        ("/api/v2/tasks/{task_id}/rebuild", "post"),
    ):
        responses = paths[path][method]["responses"]
        assert "410" in responses, f"{method.upper()} {path} 缺少 410 响应"
        description = responses["410"]["description"]
        assert "留存策略" in description, f"{method.upper()} {path} 的 410 描述未说明留存语义"


def test_device_id_update_documents_device_not_found() -> None:
    """FR-013：手动指定设备 ID 必须已存在于设备台账，否则 400 device_not_found。"""
    responses = _load_contract()["paths"]["/api/v2/tasks/{task_id}/device-id"]["patch"]["responses"]
    assert "400" in responses, "PATCH /api/v2/tasks/{task_id}/device-id 缺少 400 响应"
    assert "device_not_found" in responses["400"]["description"]


def test_task_create_v3_documents_checksum_conflict() -> None:
    """FR-008：同名任务数据包校验和不一致时返回 409 package_checksum_conflict。"""
    responses = _load_contract()["paths"]["/api/v3/tasks"]["post"]["responses"]
    assert "409" in responses, "POST /api/v3/tasks 缺少 409 响应"
    assert "package_checksum_conflict" in responses["409"]["description"]
