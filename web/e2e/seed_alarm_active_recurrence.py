"""为告警活动状态与反复上报详情准备固定合成现场。"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.db import init_db
from app.models.schemas import (
    InspectionTask,
    Priority,
    RuleCategory,
    RuleResult,
    RuleStatus,
    Severity,
    Summary,
    SystemInspection,
    TaskStats,
)
from app.services import task_db
from app.services.store import append_log, save_rule_result, save_system, save_task_meta

TASK_ID = "task-alarm-active-recurrence-e2e"
CREATED_AT = datetime(2026, 9, 18, 9, 2, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 9, 18, 9, 2, 1, tzinfo=UTC)
OBSERVATION_NOTE = "coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻"
SOURCE_FILE = "alarm/alarm_history_20260918090000000.csv"


def _metric(key: str, label: str, value: int | float | str, unit: str | None = None) -> dict[str, Any]:
    return {"key": key, "label": label, "value": value, "unit": unit}


def _active_result() -> RuleResult:
    metadata = {
        "schema_version": 1,
        "scope": {
            "source_patterns": ["^alarm/[^/]+\\.csv$"],
            "direct_alarm_csv_only": True,
            "operation_log_used": False,
            "cross_task_data_used": False,
        },
        "coverage": {
            "start_at": "2026-08-26T10:26:23+00:00",
            "end_at": "2026-09-18T09:01:00+00:00",
            "span_sec": 1965877,
            "end_basis": "max_valid_alarm_timestamp",
            "timezone_policy": "无时区时间按 UTC+8 解释后转 UTC",
            "observation_note": OBSERVATION_NOTE,
        },
        "totals": {
            "source_files": 1,
            "failed_files": 0,
            "raw_rows": 3,
            "valid_records": 3,
            "excluded_records": 0,
            "duplicate_records": 0,
            "active_records": 2,
            "active_groups": 2,
            "repeat_totals_complete": True,
            "estimated_report_totals_complete": True,
            "details_truncated": False,
            "findings_truncated": False,
        },
        "status_counts": {"Not Cleared": 2, "Normal Cleared": 1, "Reset Cleared": 0, "Unknown": 0},
        "active_severity_counts": {"CRITICAL": 1, "HIGH": 1, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0},
        "active_summary": {
            "highest_severity": "CRITICAL",
            "raw_repeat_times_total": 30,
            "max_single_repeat_times": 24,
            "estimated_report_total": 32,
            "estimated_total_is_estimate": True,
        },
        "groups": [
            {
                "group_key": "ntp-sync-pod-umf-9",
                "app_name": "UMF",
                "alarm_id": "NTP_SYNC_FAIL",
                "alarm_name": "NTP 同步失败",
                "object": "pod-umf-9",
                "severity": "CRITICAL",
                "first_raised_at": "2026-08-26T10:26:23+00:00",
                "last_raised_at": "2026-09-18T09:01:00+00:00",
                "duration_sec": 1965877,
                "lifecycle_count": 1,
                "raw_repeat_times_total": 24,
                "max_single_repeat_times": 24,
                "estimated_report_total": 25,
                "repeat_totals_complete": True,
                "source_refs": [{"source_file": SOURCE_FILE, "line_no": 2}],
            },
            {
                "group_key": "ibmc-connection-pod-csp-1",
                "app_name": "CSP",
                "alarm_id": "137611",
                "alarm_name": "iBMC 连接失败",
                "object": "pod-csp-1",
                "severity": "HIGH",
                "first_raised_at": "2026-09-18T08:30:00+00:00",
                "last_raised_at": "2026-09-18T08:50:00+00:00",
                "duration_sec": 1860,
                "lifecycle_count": 1,
                "raw_repeat_times_total": 6,
                "max_single_repeat_times": 6,
                "estimated_report_total": 7,
                "repeat_totals_complete": True,
                "source_refs": [{"source_file": SOURCE_FILE, "line_no": 3}],
            },
        ],
        "records": [
            {
                "app_name": "UMF",
                "alarm_id": "NTP_SYNC_FAIL",
                "alarm_name": "NTP 同步失败",
                "object": "pod-umf-9",
                "severity": "CRITICAL",
                "state": "Not Cleared",
                "raised_at": "2026-08-26T10:26:23+00:00",
                "cleared_at": None,
                "duration_sec": 1965877,
                "repeat_times": 24,
                "estimated_report_count": 25,
                "source_file": SOURCE_FILE,
                "line_no": 2,
            },
            {
                "app_name": "CSP",
                "alarm_id": "137611",
                "alarm_name": "iBMC 连接失败",
                "object": "pod-csp-1",
                "severity": "HIGH",
                "state": "Not Cleared",
                "raised_at": "2026-09-18T08:30:00+00:00",
                "cleared_at": None,
                "duration_sec": 1860,
                "repeat_times": 6,
                "estimated_report_count": 7,
                "source_file": SOURCE_FILE,
                "line_no": 3,
            },
        ],
        "quality": {
            "excluded_rows": 0,
            "invalid_raised_time_rows": 0,
            "invalid_cleared_time_rows": 0,
            "invalid_repeat_times_rows": 0,
            "unknown_status_rows": 0,
            "unknown_severity_rows": 0,
        },
        "files": [
            {
                "source_file": SOURCE_FILE,
                "status": "matched",
                "raw_rows": 3,
                "valid_rows": 3,
                "excluded_rows": 0,
                "duplicate_rows": 0,
                "error_code": None,
                "error_message": None,
            }
        ],
        "notes": [
            "活动状态唯一判据为 Whether Cleared=Not Cleared",
            "估算上报总数为 Σ(1 + Repeat Times)，不是精确事件总数",
            "Reset Cleared 不代表稳定恢复",
        ],
    }
    return RuleResult(
        code="alarm.active_state",
        name="未清除告警巡检",
        category=RuleCategory.ALARM,
        priority=Priority.P1,
        execution_order=0,
        status=RuleStatus.FAIL,
        severity=Severity.CRITICAL,
        summary="当前仍有 2 条未清除告警，其中 Critical 1 条，最高单条重复 24 次",
        executed_at=CREATED_AT,
        duration_ms=31,
        metrics=[
            _metric("active_records_total", "活动告警记录数", 2, "条"),
            _metric("active_groups_total", "活动告警分组数", 2, "个"),
            _metric("active_raw_repeat_times_total", "活动原始 Repeat Times", 30, "次"),
            _metric("active_estimated_reports_total", "活动估算上报总数", 32, "次"),
        ],
        findings=[
            {
                "finding_id": "alarm-active-ntp-pod-umf-9",
                "title": "未清除高危告警：NTP 同步失败",
                "severity": Severity.CRITICAL,
                "source_file": SOURCE_FILE,
                "evidence": "repeat_times=24; estimated_report_count=25; object=pod-umf-9",
                "details": "NTP 同步失败持续未清除，重复上报风险最高",
                "recommendation": "优先核查 NTP 连通性与时钟源，确认恢复前保留观察",
            }
        ],
        metadata={"alarm_active": metadata},
    )


def _recurrence_result() -> RuleResult:
    common_flags = {
        "multi_lifecycle": True,
        "repeat_reporting": True,
        "short_alarm": False,
        "rapid_recurrence": False,
        "reset_cleared": False,
    }
    reset_flags = {**common_flags, "rapid_recurrence": True, "reset_cleared": True}
    metadata = {
        "schema_version": 1,
        "parameters": {
            "short_alarm_sec": 300,
            "rapid_recurrence_window_sec": 3600,
            "rapid_recurrence_min_count": 3,
            "parameter_source": "default",
        },
        "coverage": {
            "start_at": "2026-08-26T10:26:23+00:00",
            "end_at": "2026-09-18T09:01:00+00:00",
            "span_sec": 1965877,
            "end_basis": "max_valid_alarm_timestamp",
            "timezone_policy": "无时区时间按 UTC+8 解释后转 UTC",
            "observation_note": OBSERVATION_NOTE,
        },
        "totals": {
            "source_files": 1,
            "failed_files": 0,
            "raw_rows": 6,
            "valid_records": 6,
            "excluded_records": 0,
            "duplicate_records": 0,
            "alarm_types": 2,
            "multi_lifecycle_types": 2,
            "repeat_reporting_types": 2,
            "short_alarm_types": 0,
            "rapid_recurrence_types": 1,
            "reset_cleared_records": 1,
            "repeat_positive_records": 4,
            "repeat_totals_complete": True,
            "estimated_report_totals_complete": True,
            "types_truncated": False,
            "details_truncated": False,
            "findings_truncated": False,
        },
        "status_counts": {"Not Cleared": 2, "Normal Cleared": 3, "Reset Cleared": 1, "Unknown": 0},
        "severity_counts": {"CRITICAL": 2, "HIGH": 2, "MEDIUM": 1, "LOW": 1, "UNKNOWN": 0},
        "types": [
            {
                "type_key": "ntp-sync-failure",
                "app_name": "UMF",
                "alarm_id": "NTP_SYNC_FAIL",
                "alarm_name": "NTP 同步失败",
                "object": "pod-umf-9",
                "object_count": 1,
                "lifecycle_count": 2,
                "not_cleared_count": 1,
                "raw_repeat_times_total": 30,
                "max_single_repeat_times": 24,
                "estimated_report_total": 32,
                "repeat_totals_complete": True,
                "first_raised_at": "2026-08-26T10:26:23+00:00",
                "last_raised_at": "2026-09-18T09:01:00+00:00",
                "max_duration_sec": 1965877,
                "min_adjacent_gap_sec": None,
                "status_counts": {"Not Cleared": 1, "Normal Cleared": 1, "Reset Cleared": 0, "Unknown": 0},
                "severity_counts": {"CRITICAL": 2, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0},
                "flags": common_flags,
                "objects": [
                    {
                        "object": "pod-umf-9",
                        "lifecycle_count": 2,
                        "not_cleared_count": 1,
                        "raw_repeat_times_total": 30,
                        "max_single_repeat_times": 24,
                        "estimated_report_total": 32,
                        "repeat_totals_complete": True,
                        "first_raised_at": "2026-08-26T10:26:23+00:00",
                        "last_raised_at": "2026-09-18T09:01:00+00:00",
                        "max_duration_sec": 1965877,
                        "min_adjacent_gap_sec": None,
                        "status_counts": {"Not Cleared": 1, "Normal Cleared": 1, "Reset Cleared": 0, "Unknown": 0},
                        "severity_counts": {"CRITICAL": 2, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0},
                        "flags": common_flags,
                    }
                ],
                "objects_truncated": False,
                "source_refs": [{"source_file": SOURCE_FILE, "line_no": 2}],
            },
            {
                "type_key": "ibmc-connection-failure",
                "app_name": "CSP",
                "alarm_id": "137611",
                "alarm_name": "iBMC 连接失败",
                "object": "pod-csp-1",
                "object_count": 1,
                "lifecycle_count": 4,
                "not_cleared_count": 1,
                "raw_repeat_times_total": 8,
                "max_single_repeat_times": 6,
                "estimated_report_total": 12,
                "repeat_totals_complete": True,
                "first_raised_at": "2026-09-18T08:00:00+00:00",
                "last_raised_at": "2026-09-18T08:50:00+00:00",
                "max_duration_sec": 1860,
                "min_adjacent_gap_sec": 600,
                "status_counts": {"Not Cleared": 1, "Normal Cleared": 2, "Reset Cleared": 1, "Unknown": 0},
                "severity_counts": {"CRITICAL": 0, "HIGH": 2, "MEDIUM": 1, "LOW": 1, "UNKNOWN": 0},
                "flags": reset_flags,
                "objects": [
                    {
                        "object": "pod-csp-1",
                        "lifecycle_count": 4,
                        "not_cleared_count": 1,
                        "raw_repeat_times_total": 8,
                        "max_single_repeat_times": 6,
                        "estimated_report_total": 12,
                        "repeat_totals_complete": True,
                        "first_raised_at": "2026-09-18T08:00:00+00:00",
                        "last_raised_at": "2026-09-18T08:50:00+00:00",
                        "max_duration_sec": 1860,
                        "min_adjacent_gap_sec": 600,
                        "status_counts": {"Not Cleared": 1, "Normal Cleared": 2, "Reset Cleared": 1, "Unknown": 0},
                        "severity_counts": {"CRITICAL": 0, "HIGH": 2, "MEDIUM": 1, "LOW": 1, "UNKNOWN": 0},
                        "flags": reset_flags,
                    }
                ],
                "objects_truncated": False,
                "source_refs": [{"source_file": SOURCE_FILE, "line_no": 3}],
            },
        ],
        "quality": {
            "excluded_rows": 0,
            "invalid_raised_time_rows": 0,
            "invalid_cleared_time_rows": 0,
            "invalid_repeat_times_rows": 0,
            "unknown_status_rows": 0,
            "unknown_severity_rows": 0,
        },
        "files": [
            {
                "source_file": SOURCE_FILE,
                "status": "matched",
                "raw_rows": 6,
                "valid_rows": 6,
                "excluded_rows": 0,
                "duplicate_rows": 0,
                "error_code": None,
                "error_message": None,
            }
        ],
        "notes": [
            "原始 Repeat Times 合计与估算上报总数是两个独立口径",
            "估算上报总数为 Σ(1 + Repeat Times)，不是精确事件总数",
            "快速复发只陈述告警文件中的时间事实，不判断操作时间或计划内外",
            "Reset Cleared 不代表稳定恢复",
            "未根据观察窗末端之后没有记录推断恢复",
        ],
    }
    return RuleResult(
        code="alarm.recurrence",
        name="告警反复上报巡检",
        category=RuleCategory.ALARM,
        priority=Priority.P1,
        execution_order=1,
        status=RuleStatus.FAIL,
        severity=Severity.HIGH,
        summary="识别 2 种告警类型，其中 1 种存在快速复发，原始 Repeat Times 合计 38 次",
        executed_at=CREATED_AT,
        duration_ms=47,
        metrics=[
            _metric("valid_lifecycles", "有效生命周期", 6, "条"),
            _metric("alarm_types", "告警类型数", 2, "种"),
            _metric("repeat_reporting_types", "重复上报类型数", 2, "种"),
            _metric("rapid_recurrence_types", "快速复发类型数", 1, "种"),
            _metric("reset_cleared_records", "Reset Cleared 记录数", 1, "条"),
            _metric("raw_repeat_times_total", "原始重复次数合计", 38, "次"),
            _metric("estimated_reports_total", "估算上报总数", 44, "次"),
        ],
        findings=[
            {
                "finding_id": "alarm-recurrence-ibmc-rapid",
                "title": "告警快速复发：iBMC 连接失败",
                "severity": Severity.HIGH,
                "source_file": SOURCE_FILE,
                "evidence": "lifecycle_count=4; raw_repeat_times_total=8; min_adjacent_gap_sec=600",
                "details": "60 分钟内多次发生，且存在 Reset Cleared 记录",
                "recommendation": "优先核查反复发生的根因，Reset Cleared 不等于稳定恢复",
            }
        ],
        metadata={"alarm_recurrence": metadata},
    )


def main() -> None:
    init_db()
    task_dir = settings.output / TASK_ID
    upload_dir = settings.uploads / TASK_ID
    shutil.rmtree(task_dir, ignore_errors=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "alarm-active-recurrence.zip").write_bytes(b"e2e-synthetic-alarm")

    rules = [_active_result(), _recurrence_result()]
    summary = Summary(total=2, pass_=0, warn=0, fail=2, error=0, skip=0)
    system = SystemInspection(
        package_file="alarm-active-recurrence.zip",
        package_checksum="1" * 64,
        version="V900R016C10SPC200",
        status="completed",
        summary=summary,
        rules=rules,
        customer={
            "province": "江苏",
            "operator": "移动",
            "product": "UMF",
            "device_id": "alarm-e2e-device-001",
        },
    )
    task = InspectionTask(
        task_id=TASK_ID,
        name="告警未清除与反复上报样例任务",
        mode="local",
        status="completed",
        trigger="api",
        created_at=CREATED_AT,
        completed_at=COMPLETED_AT,
        last_run_at=CREATED_AT,
        duration_ms=1_000,
        stats=TaskStats.model_validate(
            {"total": 2, "pass": 0, "warn": 0, "fail": 2, "error": 0, "skip": 0, "systems": 1}
        ),
        system=system,
    )
    for rule in rules:
        save_rule_result(settings.output, TASK_ID, rule)
    save_system(settings.output, TASK_ID, system)
    save_task_meta(settings.output, task)
    append_log(settings.output, TASK_ID, "info", "告警活动状态规则执行完成", rule_code="alarm.active_state")
    append_log(settings.output, TASK_ID, "info", "告警反复上报规则执行完成", rule_code="alarm.recurrence")
    task_db.publish_from_scene(task)
    print(f"seeded {TASK_ID}: rules=2 fail=2")


if __name__ == "__main__":
    main()
