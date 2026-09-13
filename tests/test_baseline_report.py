"""HTML 报告可审查性与契约一致性测试。"""

from pathlib import Path

from tests.baseline_helpers import SAMPLE, setup_env


def test_report_exposes_contract_results(tmp_path: Path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-sample")
    report = (tmp_path / "output" / "task-sample" / "report.html").read_text(encoding="utf-8")
    summary = task.system.summary

    for text in (
        f"总计 <b>{summary.total}</b>",
        f"通过 <b>{summary.pass_}</b>",
        f"告警 <b>{summary.warn}</b>",
        f"失败 <b>{summary.fail}</b>",
        f"异常 <b>{summary.error}</b>",
        f"跳过 <b>{summary.skip}</b>",
        "执行时间",
    ):
        assert text in report, text

    for rule in task.system.rules:
        assert rule.code in report
        if rule.status == "skip":
            assert rule.skip_reason and rule.skip_reason in report
        for finding in rule.findings:
            assert finding.title in report
            assert finding.source_file in report
            assert finding.evidence in report
            if finding.recommendation:
                assert finding.recommendation in report


def test_report_orders_findings_by_severity_then_rule_contract(tmp_path: Path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    from app.models.schemas import (
        Finding,
        Priority,
        RuleCategory,
        RuleResult,
        RuleStatus,
        Summary,
        SystemInspection,
        SystemStatus,
    )
    from app.services.report import render_report

    def make_finding(finding_id: str, title: str, severity: str) -> Finding:
        return Finding(
            finding_id=finding_id,
            title=title,
            severity=severity,
            source_file=f"logs/{finding_id}.log",
            evidence=f"evidence-{finding_id}",
            recommendation=f"action-{finding_id}",
        )

    def make_rule(code: str, priority: Priority, finding: Finding) -> RuleResult:
        return RuleResult(
            code=code,
            name=code,
            category=RuleCategory.OTHER,
            priority=priority,
            execution_order=0,
            status=RuleStatus.WARN,
            severity=finding.severity,
            summary=f"{code} 摘要",
            findings=[finding],
        )

    rules = [
        make_rule("z.medium", Priority.P2, make_finding("m1", "中风险", "medium")),
        make_rule("a.critical", Priority.P1, make_finding("c1", "严重风险", "critical")),
        make_rule("b.high", Priority.P0, make_finding("h1", "高风险", "high")),
        make_rule("a.low", Priority.P0, make_finding("l1", "低风险", "low")),
    ]
    system = SystemInspection(
        package_file="sample.zip",
        status=SystemStatus.COMPLETED,
        summary=Summary(total=4, pass_=0, warn=4, fail=0, error=0, skip=0),
        rules=rules,
    )
    render_report(tmp_path / "output", "task-sort", system)
    report = (tmp_path / "output" / "task-sort" / "report.html").read_text(encoding="utf-8")

    positions = [report.index(title) for title in ("严重风险", "高风险", "中风险", "低风险")]
    assert positions == sorted(positions)
    for value in ("logs/c1.log", "evidence-c1", "action-c1", "摘要"):
        assert value in report
