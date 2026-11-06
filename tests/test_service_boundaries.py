"""静态模块边界保护测试。"""

import ast
from pathlib import Path

import pytest

APP_ROOT = Path("app")
INSPECTOR_ROOT = APP_ROOT / "inspectors"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


@pytest.mark.parametrize(
    ("root", "forbidden_prefix"),
    [
        (APP_ROOT / "services" / "extraction", "app.services.scanning"),
        (APP_ROOT / "services" / "extraction", "app.services.prepare"),
        (APP_ROOT / "services" / "scanning", "app.services.prepare"),
        (APP_ROOT / "services" / "prepare", "app.services.scanning"),
        (APP_ROOT / "services" / "prepare", "app.services.extraction"),
    ],
)
def test_service_packages_do_not_cross_responsibility_boundaries(root: Path, forbidden_prefix: str) -> None:
    violations = {
        f"{path.relative_to(APP_ROOT)} -> {name}"
        for path in _python_files(root)
        for name in _imports(path)
        if name == forbidden_prefix or name.startswith(forbidden_prefix + ".")
    }

    assert not violations, f"发现跨职责依赖: {sorted(violations)}"


def test_ordinary_inspector_files_do_not_import_other_rule_implementations() -> None:
    shared_modules = {"app.inspectors.base", "app.inspectors.registry"}
    violations: set[str] = set()

    for path in _python_files(INSPECTOR_ROOT):
        relative = path.relative_to(INSPECTOR_ROOT)
        parts = relative.with_suffix("").parts
        if parts[-1] in {"base", "registry", "common"} or len(parts) == 1:
            continue
        own_prefix = ".".join(("app", "inspectors", *parts[:-1]))
        for name in _imports(path):
            if not name.startswith("app.inspectors."):
                continue
            if name in shared_modules or name == own_prefix or name.startswith(own_prefix + "."):
                continue
            violations.add(f"{path.relative_to(APP_ROOT)} -> {name}")

    assert not violations, f"普通规则导入了其他规则实现: {sorted(violations)}"


def test_kpi_v6_routes_do_not_access_persistence_or_calculate_groups() -> None:
    route_path = APP_ROOT / "api" / "kpi_v6.py"
    assert route_path.is_file(), "缺少 v6 KPI 路由模块"

    tree = ast.parse(route_path.read_text(encoding="utf-8"))
    imports = _imports(route_path)
    assert not any(name == "app.models.db" or name.startswith("app.models.db.") for name in imports)
    assert not any(name == "sqlalchemy.orm" or name.startswith("sqlalchemy.orm.") for name in imports)

    forbidden_calls = {
        "group_by",
        "having",
        "count",
        "sum",
    }
    calculated_calls = {
        ast.unparse(node.func).rsplit(".", 1)[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calculated_calls.isdisjoint(forbidden_calls), (
        f"路由层不得计算 KPI 分组: {sorted(calculated_calls & forbidden_calls)}"
    )


def test_api_routes_do_not_access_database_layer() -> None:
    """路由层只做协议适配，持久化必须留在服务层。"""
    forbidden_import_prefixes = ("app.models.db", "sqlalchemy")
    violations: set[str] = set()
    for path in _python_files(APP_ROOT / "api"):
        relative = path.relative_to(APP_ROOT / "api")
        imports = _imports(path)
        for name in imports:
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_import_prefixes):
                violations.add(f"{relative} -> {name}")

        tree = ast.parse(path.read_text(encoding="utf-8"))
        direct_db_calls = {
            ast.unparse(node.func).rsplit(".", 1)[-1]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        } & {"session_factory", "Session", "select", "text"}
        if direct_db_calls:
            violations.add(f"{relative} -> calls {sorted(direct_db_calls)}")

    assert not violations, f"路由层直连数据库: {sorted(violations)}"


def test_unassigned_rules_do_not_enter_execution_plan(isolated_db) -> None:
    """零归属业务规则不进入 prepare/inspect 计划，也不执行产生结果。"""
    from app.inspectors.base import Inspector
    from app.inspectors.registry import RuleRegistry
    from app.models.schemas import Priority, RuleCategory, Severity
    from app.services.executor import Executor
    from app.services.rule_scope import RuleScopeResolver

    registry = RuleRegistry()
    registry.register(
        Inspector(
            code="kpi.unassigned",
            name="未归属规则",
            category=RuleCategory.KPI,
            severity=Severity.MEDIUM,
            priority=Priority.P1,
            rule_version="1.0.0",
            description="未归属边界测试",
            recommendation="配置网元归属",
            source_patterns=[r"kpi/.+\.csv"],
            run=lambda _context: None,
        )
    )

    snapshot = RuleScopeResolver(registry).resolve(
        task_id="task-unassigned-boundary",
        network_element_type="UMF",
        trigger="api",
        source="api",
    )
    executor = Executor(registry, frozen_rule_codes={item.rule_code for item in snapshot.items})

    assert snapshot.items == ()
    assert executor.prepare_plan() == []
    assert executor.inspect_plan() == []
