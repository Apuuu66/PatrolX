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
