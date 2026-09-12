"""契约模型可实例化与字段对齐测试。"""

from app.models.schemas import (
    InspectionTask,
    Metric,
    RuleResult,
    Summary,
    SystemInspection,
    TaskStats,
)


def test_summary_alias_pass() -> None:
    summary = Summary(total=3, pass_=1, warn=1, fail=0, error=0, skip=1)
    data = summary.model_dump(by_alias=True)
    assert data["pass"] == 1


def test_task_stats_inherits_summary() -> None:
    stats = TaskStats(total=1, pass_=1, warn=0, fail=0, error=0, skip=0, systems=1)
    assert stats.systems == 1


def test_rule_result_and_system_instance() -> None:
    rule = RuleResult(
        code="log.error_density",
        name="日志错误密度",
        category="log",
        priority=1,
        execution_order=3,
        status="warn",
        severity="medium",
        metrics=[Metric(key="error_count", label="错误条数", value=152, unit="条")],
    )
    system = SystemInspection(
        package_file="customer_a.tar.gz",
        status="completed",
        summary=Summary(total=1, pass_=0, warn=1, fail=0, error=0, skip=0),
        rules=[rule],
    )
    task = InspectionTask(
        task_id="task-001",
        name="示例任务",
        mode="local",
        status="completed",
        trigger="cli",
        created_at="2026-09-09T00:00:00Z",
        stats=TaskStats(total=1, pass_=0, warn=1, fail=0, error=0, skip=0, systems=1),
        system=system,
    )
    assert task.system is not None
    assert task.system.rules[0].code == "log.error_density"


def test_legacy_contract_fields_removed() -> None:
    assert "inputs" not in RuleResult.model_fields
    assert "artifacts" not in RuleResult.model_fields
    assert "system_id" not in SystemInspection.model_fields
    assert "system_name" not in SystemInspection.model_fields
