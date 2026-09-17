"""Inspector source_refs 与注册表解析契约测试。"""

import pytest

from app.inspectors.base import Inspector
from app.inspectors.registry import RuleRegistry
from app.models.schemas import Priority, RuleCategory, Severity


def make_rule(**overrides: object) -> Inspector:
    kwargs = {
        "code": "alarm.sample",
        "name": "告警样例",
        "category": RuleCategory.ALARM,
        "severity": Severity.MEDIUM,
        "priority": Priority.P1,
        "rule_version": "1.0.0",
        "description": "样例规则",
        "recommendation": "检查样例数据",
        "run": lambda ctx: None,
    }
    kwargs.update(overrides)
    return Inspector(**kwargs)


def test_inspector_accepts_source_refs_instead_of_patterns() -> None:
    rule = make_rule(source_refs=["alarm_history"])
    rule.validate()


def test_inspector_rejects_both_source_forms_or_invalid_refs() -> None:
    with pytest.raises(ValueError, match="source_patterns/source_refs"):
        make_rule(
            source_patterns=[r"^alarm/.*$"],
            source_refs=["alarm_history"],
        ).validate()
    with pytest.raises(ValueError, match="source_refs"):
        make_rule(source_refs=["alarm/history"]).validate()
    with pytest.raises(ValueError, match="source_refs"):
        make_rule(source_refs=["alarm_history", "alarm_history"]).validate()


def test_registry_resolves_source_refs_to_runtime_patterns() -> None:
    registry = RuleRegistry()
    rule = make_rule(source_refs=["alarm_history"])
    registry.register(rule)
    registry.resolve_scan_refs({"alarm_history": [r"^alarm/(?:.*/)?alarm_history_\d+\.csv$"]})

    assert rule.source_patterns == [r"^alarm/(?:.*/)?alarm_history_\d+\.csv$"]
    assert rule.source_refs == ["alarm_history"]


def test_registry_resolves_multiple_refs_in_declared_order() -> None:
    registry = RuleRegistry()
    rule = make_rule(source_refs=["alarm_summary", "alarm_history"])
    registry.register(rule)
    registry.resolve_scan_refs(
        {
            "alarm_history": [r"^alarm/.*\.csv$"],
            "alarm_summary": [r"^alarm/.*\.json$"],
        }
    )

    assert rule.source_patterns == [r"^alarm/.*\.json$", r"^alarm/.*\.csv$"]


def test_registry_rejects_unknown_scan_ref() -> None:
    registry = RuleRegistry()
    registry.register(make_rule(source_refs=["missing"]))
    with pytest.raises(ValueError, match="未定义扫描组"):
        registry.resolve_scan_refs({})


def test_registry_requires_resolution_before_execution_plan() -> None:
    registry = RuleRegistry()
    registry.register(make_rule(source_refs=["alarm_history"]))
    with pytest.raises(ValueError, match="source_refs 未解析"):
        registry.inspect_plan()
