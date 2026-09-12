"""规则注册契约与执行器 metrics 校验测试。"""

import pytest

from app.inspectors.base import Inspector
from app.models.schemas import Priority, RuleCategory, Severity


def make_rule(**overrides: object) -> Inspector:
    kwargs = {
        "code": "log.sample",
        "name": "日志样例",
        "category": RuleCategory.LOG,
        "severity": Severity.MEDIUM,
        "priority": Priority.P1,
        "rule_version": "1.0.0",
        "description": "样例规则",
        "recommendation": "检查样例数据",
        "source_patterns": [r"logs/.*\.log"],
        "run": lambda ctx: None,
    }
    kwargs.update(overrides)
    return Inspector(**kwargs)


def test_normal_rule_requires_source_patterns() -> None:
    with pytest.raises(ValueError, match="source_patterns"):
        make_rule(source_patterns=None).validate()
    with pytest.raises(ValueError, match="source_patterns"):
        make_rule(source_patterns=[]).validate()


def test_source_patterns_must_be_safe_relative_regexes() -> None:
    make_rule().validate()
    with pytest.raises(ValueError, match="路径"):
        make_rule(source_patterns=[r"/logs/.*\.log"]).validate()
    with pytest.raises(ValueError, match="路径"):
        make_rule(source_patterns=[r"\.\./escape"]).validate()
    with pytest.raises(ValueError, match="正则"):
        make_rule(source_patterns=["logs/(.*"]).validate()


def test_registry_rejects_duplicate_metric_keys() -> None:
    from app.inspectors.registry import RuleRegistry

    registry = RuleRegistry()
    rule = make_rule(
        outputs_metrics=[
            {"key": "count", "label": "计数", "unit": "条"},
            {"key": "count", "label": "重复", "unit": "条"},
        ]
    )
    with pytest.raises(ValueError, match="metrics"):
        registry.register(rule)


def test_hidden_extract_rule_may_have_no_source_patterns() -> None:
    rule = make_rule(code="pkg.extract.log", hidden=True, source_patterns=None)
    rule.validate()


def test_inspector_metadata_has_source_patterns() -> None:
    from app.inspectors.base import Inspector

    rule = make_rule()
    assert rule.source_patterns == [r"logs/.*\.log"]
    assert "inputs" not in Inspector.__dataclass_fields__
    assert "outputs_artifacts" not in Inspector.__dataclass_fields__
