"""HTML 报告可审查性与契约一致性测试。"""

from pathlib import Path

from tests.baseline_helpers import SAMPLE, setup_env


def test_report_exposes_contract_results(tmp_path: Path, monkeypatch) -> None:
    setup_env(tmp_path, monkeypatch)
    from app.cli import run_task

    task = run_task(SAMPLE, task_id="task-sample", customer={"product": "UMF"})
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


def _daily_health_rule(*, include_daily_health: bool = True):
    from app.models.schemas import RuleCategory, RuleResult, RuleStatus, Severity

    metadata = {
        "daily_health": {
            "schema_version": 1,
            "timezone": "Asia/Shanghai",
            "data_date": "2026-11-01",
            "previous_date": "2026-10-31",
            "latest_measured_at": "2026-11-01T23:45:00+08:00",
            "legacy_fallback": None,
            "current_counts": {
                "fail": 1,
                "warn": 1,
                "unable_to_judge": 1,
                "pending_config": 0,
                "not_applicable": 0,
                "normal": 1,
            },
            "trend_counts": {
                "worsened": 1,
                "improved": 0,
                "observe": 0,
                "no_baseline": 2,
                "stable": 1,
            },
            "scope": {
                "enabled_measurement_unit_count": 2,
                "confirmed_binding_metric_count": 4,
                "expected_metric_count": 4,
                "out_of_scope_file_count": 3,
                "unconfirmed_binding_count": 1,
                "out_of_scope_reason_counts": {"disabled_unit": 2, "unconfirmed_binding": 1},
            },
            "metrics": [
                {
                    "measurement_unit_id": "MU_CALL",
                    "measurement_unit_name_zh": "呼叫统计",
                    "metric_resource_id": "ME_RATE",
                    "metric_resource_name_zh": "呼叫成功率",
                    "role": "derived",
                    "importance": "P1",
                    "current_status": "fail",
                    "current_reason": "critical_threshold",
                    "current_reason_text": "低于失败阈值",
                    "today_value": 45.5,
                    "today_display": "45.5%",
                    "yesterday_value": 99.0,
                    "yesterday_display": "99.0%",
                    "delta": -53.5,
                    "delta_display": "-53.5pp",
                    "trend_status": "worsened",
                    "trend_reason": "成功率显著下降",
                    "objects": [
                        {
                            "object_key": "pod-a",
                            "period_minutes": 15,
                            "current_status": "not_applicable",
                            "numerator": 0,
                            "denominator": 0,
                            "valid_count": 2,
                        }
                    ],
                },
                {
                    "measurement_unit_id": "MU_CALL",
                    "measurement_unit_name_zh": "呼叫统计",
                    "metric_resource_id": "ME_DELAY",
                    "metric_resource_name_zh": "呼叫时延",
                    "role": "base",
                    "importance": "P2",
                    "current_status": "warn",
                    "current_reason": "warning_threshold",
                    "current_reason_text": "高于预警阈值",
                    "today_value": 120.0,
                    "today_display": "120ms",
                    "yesterday_value": 100.0,
                    "yesterday_display": "100ms",
                    "delta": 20.0,
                    "delta_display": "+20ms",
                    "trend_status": "worsened",
                    "trend_reason": "时延上升",
                    "objects": [],
                },
                {
                    "measurement_unit_id": "MU_CALL",
                    "measurement_unit_name_zh": "呼叫统计",
                    "metric_resource_id": "ME_NO_DATA",
                    "metric_resource_name_zh": "无数据指标",
                    "role": "base",
                    "importance": "normal",
                    "current_status": "unable_to_judge",
                    "current_reason": "no_current_data",
                    "current_reason_text": "无有效数据",
                    "today_display": "—",
                    "yesterday_display": "—",
                    "trend_status": "no_baseline",
                    "trend_reason": "无昨日基线",
                    "objects": [],
                },
                {
                    "measurement_unit_id": "MU_CALL",
                    "measurement_unit_name_zh": "呼叫统计",
                    "metric_resource_id": "ME_OK",
                    "metric_resource_name_zh": "正常指标",
                    "role": "base",
                    "importance": "normal",
                    "current_status": "normal",
                    "current_reason": "threshold_satisfied",
                    "current_reason_text": "满足阈值",
                    "today_value": 99.8,
                    "today_display": "99.8",
                    "yesterday_value": 99.7,
                    "yesterday_display": "99.7",
                    "delta": 0.1,
                    "delta_display": "+0.1",
                    "trend_status": "stable",
                    "trend_reason": "变化在容差内",
                    "objects": [],
                },
            ],
        }
    }
    if not include_daily_health:
        metadata = {}
    return RuleResult(
        code="kpi.measurement_units",
        name="KPI 测量单元巡检",
        category=RuleCategory.KPI,
        priority=1,
        execution_order=10,
        status=RuleStatus.FAIL,
        severity=Severity.HIGH,
        summary="KPI 日健康存在失败指标",
        metadata=metadata,
    )


def _system_with_kpi_rule(*, include_daily_health: bool = True):
    from app.models.schemas import Summary, SystemInspection, SystemStatus

    return SystemInspection(
        package_file="synthetic-kpi.zip",
        status=SystemStatus.COMPLETED,
        summary=Summary(total=1, pass_=0, warn=0, fail=1, error=0, skip=0),
        rules=[_daily_health_rule(include_daily_health=include_daily_health)],
    )


def test_report_renders_daily_health_distribution_focus_and_zero_denominator(tmp_path: Path) -> None:
    from app.services.report import render_report

    render_report(tmp_path / "output", "task-daily-health", _system_with_kpi_rule())
    report = (tmp_path / "output" / "task-daily-health" / "report.html").read_text(encoding="utf-8")

    for text in (
        "KPI 当前判定与昨日趋势",
        "数据日期 2026-11-01（Asia/Shanghai）",
        "当前判定分布",
        "当前合计 <b>4</b>",
        "较昨日分布",
        "趋势合计 <b>4</b>",
        "重点关注指标",
        "呼叫成功率",
        "呼叫时延",
        "零分母指标",
        "pod-a / 15 分钟",
        "范围说明",
        "范围外文件 <b>3</b>",
        "未确认绑定 <b>1</b>",
    ):
        assert text in report, text

    assert report.index("呼叫成功率") < report.index("呼叫时延")
    assert report.index("呼叫时延") < report.index("无数据指标")


def test_report_degrades_legacy_kpi_task_without_daily_health(tmp_path: Path) -> None:
    from app.services.report import render_report

    render_report(
        tmp_path / "output",
        "task-legacy-kpi",
        _system_with_kpi_rule(include_daily_health=False),
    )
    report = (tmp_path / "output" / "task-legacy-kpi" / "report.html").read_text(encoding="utf-8")

    assert "旧任务无日健康结论" in report
    assert "既有指标和发现仍可查看" in report
    assert "KPI 当前判定与昨日趋势" not in report
