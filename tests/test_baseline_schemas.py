"""基线契约模型校验测试。"""

import pytest
from pydantic import ValidationError

from app.models.schemas import Finding, InspectionTask, Metric, RuleResult, Summary, SystemInspection, TaskStats


def make_rule(**overrides: object) -> RuleResult:
    base = {
        "code": "log.error_density",
        "name": "日志错误密度",
        "category": "log",
        "priority": 1,
        "execution_order": 0,
        "status": "pass",
        "severity": "medium",
        "metrics": [{"key": "error_count", "label": "错误条数", "value": 0, "unit": "条"}],
    }
    base.update(overrides)
    return RuleResult.model_validate(base)


def make_task(rules: list[RuleResult], stats: TaskStats) -> InspectionTask:
    system = SystemInspection(
        package_file="sample.zip",
        status="completed",
        summary=Summary(
            total=stats.total,
            pass_=stats.pass_,
            warn=stats.warn,
            fail=stats.fail,
            error=stats.error,
            skip=stats.skip,
        ),
        rules=rules,
    )
    return InspectionTask(
        task_id="task-sample",
        name="示例",
        mode="local",
        status="completed",
        trigger="cli",
        created_at="2026-01-01T00:00:00Z",
        stats=stats,
        system=system,
    )


def test_skip_requires_non_empty_reason() -> None:
    with pytest.raises(ValidationError, match="skip_reason"):
        make_rule(status="skip")
    assert make_rule(status="skip", skip_reason="未发现日志文件").skip_reason == "未发现日志文件"


def test_finding_requires_traceability() -> None:
    with pytest.raises(ValidationError):
        Finding(finding_id="f1", title="问题", severity="high")
    with pytest.raises(ValidationError):
        Finding(finding_id="f1", title="问题", severity="high", source_file="a.log")
    with pytest.raises(ValidationError):
        Finding(finding_id="f1", title="问题", severity="high", evidence="ERROR")
    finding = Finding(
        finding_id="f1",
        title="问题",
        severity="high",
        source_file="logs/a.log",
        evidence="ERROR line",
    )
    assert finding.source_file and finding.evidence


def test_task_summary_must_match_rule_results() -> None:
    rule = make_rule(status="warn")
    with pytest.raises(ValidationError, match="summary"):
        make_task([rule], TaskStats(total=2, pass_=0, warn=1, fail=0, error=0, skip=0, systems=1))
    with pytest.raises(ValidationError, match="summary"):
        make_task([rule], TaskStats(total=1, pass_=1, warn=0, fail=0, error=0, skip=0, systems=1))
    task = make_task([rule], TaskStats(total=1, pass_=0, warn=1, fail=0, error=0, skip=0, systems=1))
    assert task.stats.total == 1


def test_metric_contract_is_simple_model() -> None:
    metric = Metric(key="error_count", label="错误条数", value=1, unit="条")
    assert metric.value == 1


def test_legacy_rule_fields_removed() -> None:
    assert "inputs" not in RuleResult.model_fields
    assert "artifacts" not in RuleResult.model_fields
    assert "system_id" not in SystemInspection.model_fields
