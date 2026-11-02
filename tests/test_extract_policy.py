"""迁移保护：v5 生产链路不得读取旧 extract_policy.yaml。"""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_TEXT = (
    ".patrolx-extracted.json",
    "extract_policy.yaml",
    "load_extract_policy",
    "policy_manifest_snapshot",
    "evaluate_extract_policy",
)


def test_production_code_does_not_reference_legacy_extract_policy() -> None:
    """旧 skip/whitelist 策略不得重新进入生产分类或解压路径。"""
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        matched = [marker for marker in FORBIDDEN_TEXT if marker in text]
        if matched:
            violations.append(f"{path.relative_to(APP_ROOT)}: {', '.join(matched)}")

    assert violations == []
