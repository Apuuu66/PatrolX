"""HTML 报告的活动告警优先处置契约测试。"""

import html
import re
from pathlib import Path

from app.models.schemas import (
    Finding,
    Priority,
    RuleCategory,
    RuleResult,
    RuleStatus,
    Severity,
    Summary,
    SystemInspection,
    SystemStatus,
)
from app.services.report import render_report


def test_report_prioritizes_active_alarms_with_explicit_observation_scope(tmp_path: Path) -> None:
    recommendation = "核对活动告警对象现状并优先处置高严重级、重复上报量大的告警"
    active_rule = RuleResult(
        code="alarm.active_state",
        name="未清除告警巡检",
        category=RuleCategory.ALARM,
        priority=Priority.P1,
        execution_order=8,
        status=RuleStatus.FAIL,
        severity=Severity.HIGH,
        summary="发现高风险未清除告警：活动告警 3 条、2 组；最高严重级 CRITICAL",
        findings=[
            Finding(
                finding_id="alarm.active_state:group-1",
                title="未清除告警：数据库连接池耗尽",
                severity=Severity.CRITICAL,
                source_file="alarm/alarm_history_001.csv",
                evidence="alarm_id=1001; repeat_times=5",
                recommendation=recommendation,
            )
        ],
        metadata={
            "alarm_active": {
                "coverage": {
                    "start_at": "2026-09-01T02:00:01+00:00",
                    "end_at": "2026-09-01T02:31:05+00:00",
                    "observation_note": "coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻",
                },
                "totals": {"active_records": 3, "active_groups": 2},
                "active_summary": {
                    "highest_severity": "CRITICAL",
                    "raw_repeat_times_total": 7,
                    "estimated_report_total": 10,
                    "max_single_repeat_times": 5,
                },
                "groups": [
                    {
                        "alarm_id": "1001",
                        "alarm_name": "数据库连接池耗尽",
                        "app_name": "CSP核心服务",
                        "object": "paas-192.168.2.2",
                        "severity": "CRITICAL",
                        "duration_sec": 1864,
                        "raw_repeat_times_total": 5,
                        "estimated_report_total": 7,
                    },
                    {
                        "alarm_id": "1002",
                        "alarm_name": "NTP 同步失败",
                        "app_name": "CSP核心服务",
                        "object": "node-2",
                        "severity": "HIGH",
                        "duration_sec": 1564,
                        "raw_repeat_times_total": 2,
                        "estimated_report_total": 3,
                    },
                ],
                "notes": ["Reset Cleared 不代表稳定恢复"],
            }
        },
    )
    system = SystemInspection(
        package_file="synthetic-alarm.zip",
        status=SystemStatus.COMPLETED,
        summary=Summary(total=1, pass_=0, warn=0, fail=1, error=0, skip=0),
        rules=[active_rule],
    )

    report_path = render_report(tmp_path / "output", "task-alarm-report", system)
    report = report_path.read_text(encoding="utf-8")
    visible_text = html.unescape(re.sub(r"<[^>]+>", "", report))

    for text in (
        "告警优先处置",
        "活动告警 3 条",
        "最高严重级 紧急",
        "原始 Repeat Times 合计 7 次",
        "估算上报总数 10 次",
        "数据库连接池耗尽",
        recommendation,
        "Σ(1 + Repeat Times)",
        "不是任务执行时刻或真实恢复时刻",
        "2026-09-01T02:31:05+00:00",
        "Reset Cleared 不代表稳定恢复",
    ):
        assert text in visible_text, text
    assert "Reset Cleared 表示稳定恢复" not in visible_text
