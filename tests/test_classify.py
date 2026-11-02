"""迁移保护：生产代码不得恢复文件名、扩展名或内容嗅探分类。"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_MODULES = {
    "app.core.classify",
}
FORBIDDEN_NAMES = {
    "classify_content",
    "classify_member",
    "classify_name",
}


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_production_code_does_not_import_legacy_filename_or_content_classifier() -> None:
    """v5 生产链路只能按配置路线分类，不能导入旧分类模块或嗅探函数。"""
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = _imported_names(tree)
        legacy = sorted(
            name for name in names if name in FORBIDDEN_MODULES or name.rsplit(".", 1)[-1] in FORBIDDEN_NAMES
        )
        if legacy:
            violations.append(f"{path.relative_to(APP_ROOT)}: {', '.join(legacy)}")

    assert violations == []
