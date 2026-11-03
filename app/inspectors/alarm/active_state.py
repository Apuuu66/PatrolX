"""alarm.active_state（P1）：只按 Whether Cleared=Not Cleared 识别当前活动告警。"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.alarm.common import (
    SEVERITY_ORDER,
    AlarmParseResult,
    AlarmRecord,
    iso_or_none,
    parse_alarm_files,
    stable_hash,
)
from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import make_result
from app.services.unit_runtime import RuleContext

_SOURCE_PATTERNS = [r"^alarm/[^/]+\.csv$"]
_SEVERITY_RANK = {value: index for index, value in enumerate(SEVERITY_ORDER)}
_SEVERITY_TO_FINDING = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
    "UNKNOWN": Severity.MEDIUM,
}
_METRICS = (
    ("active_alarm_records", "活动告警记录数", "个"),
    ("active_alarm_groups", "活动告警分组数", "个"),
    ("critical_active", "紧急活动告警数", "个"),
    ("high_active", "严重活动告警数", "个"),
    ("medium_active", "重要活动告警数", "个"),
    ("low_active", "次要活动告警数", "个"),
    ("unknown_active", "未知严重级活动告警数", "个"),
    ("active_repeat_times_total", "活动原始重复次数合计", "次"),
    ("max_single_repeat_times", "单条最大原始重复次数", "次"),
    ("active_estimated_reports_total", "活动估算上报总数", "次"),
)

inspector = Inspector(
    code="alarm.active_state",
    name="未清除告警巡检",
    category=RuleCategory.ALARM,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="仅依据告警文件的 Whether Cleared 状态识别当前未清除告警，并按严重级与重复上报量排序",
    recommendation="优先处置紧急和严重活动告警，核对对象当前状态；估算上报总数仅用于排序，不等同精确事件数",
    source_refs=["alarm_all"],
    outputs_metrics=[{"key": key, "label": label, "unit": unit} for key, label, unit in _METRICS],
)


def _quality_degraded(parsed: AlarmParseResult) -> bool:
    quality = parsed.quality
    return bool(
        parsed.budget_exceeded
        or any(item.status != "matched" for item in parsed.files)
        or quality.excluded_rows
        or quality.invalid_status_rows
        or quality.invalid_raised_time_rows
        or quality.invalid_cleared_time_rows
        or quality.missing_cleared_time_rows
        or quality.cleared_before_raised_rows
        or quality.invalid_repeat_times_rows
        or quality.missing_repeat_times_rows
        or quality.missing_app_name_rows
        or quality.missing_alarm_id_rows
        or quality.missing_alarm_name_rows
        or quality.missing_object_rows
        or quality.unknown_status_values
        or quality.unknown_severity_values
        or quality.unknown_headers
    )


def _active_duration(record: AlarmRecord, parsed: AlarmParseResult) -> int:
    if parsed.coverage.end_at is None:
        return 0
    return max(0, int((parsed.coverage.end_at - record.raised_at).total_seconds()))


def _record_view(record: AlarmRecord, parsed: AlarmParseResult) -> dict[str, Any]:
    return {
        "app_name": record.app_name,
        "alarm_id": record.alarm_id,
        "alarm_name": record.alarm_name,
        "object": record.object_key,
        "severity": record.severity,
        "state": record.state,
        "raised_at": iso_or_none(record.raised_at),
        "cleared_at": None,
        "duration_sec": _active_duration(record, parsed),
        "repeat_times": record.repeat_times,
        "estimated_report_count": record.estimated_report_count,
        "source_file": record.source_file,
        "line_no": record.line_no,
    }


def _group_views(active: list[AlarmRecord], parsed: AlarmParseResult) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], list[AlarmRecord]] = {}
    for record in active:
        buckets.setdefault((record.app_name, record.alarm_id, record.object_key), []).append(record)

    groups: list[dict[str, Any]] = []
    for (app_name, alarm_id, object_key), records in buckets.items():
        representative = min(records, key=lambda item: (_SEVERITY_RANK[item.severity], item.raised_at))
        valid_repeats = [item.repeat_times for item in records if item.repeat_times is not None]
        source_refs = sorted(
            {(item.source_file, item.line_no) for item in records},
            key=lambda item: (item[0], item[1]),
        )
        group_key = stable_hash(app_name, alarm_id, object_key, prefix="alarm.active_state:")
        groups.append(
            {
                "group_key": group_key,
                "app_name": app_name,
                "alarm_id": alarm_id,
                "alarm_name": representative.alarm_name,
                "object": object_key,
                "severity": min((item.severity for item in records), key=_SEVERITY_RANK.__getitem__),
                "first_raised_at": iso_or_none(min(item.raised_at for item in records)),
                "last_raised_at": iso_or_none(max(item.raised_at for item in records)),
                "duration_sec": max(_active_duration(item, parsed) for item in records),
                "lifecycle_count": len(records),
                "raw_repeat_times_total": sum(valid_repeats),
                "max_single_repeat_times": max(valid_repeats, default=0),
                "estimated_report_total": sum(1 + value for value in valid_repeats),
                "repeat_totals_complete": len(valid_repeats) == len(records),
                "source_refs": [
                    {"source_file": source_file, "line_no": line_no} for source_file, line_no in source_refs[:100]
                ],
            }
        )
    groups.sort(
        key=lambda item: (
            _SEVERITY_RANK[item["severity"]],
            -item["raw_repeat_times_total"],
            -item["duration_sec"],
            item["group_key"],
        )
    )
    return groups


def _metrics(active: list[AlarmRecord], groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    severity_counts = Counter(record.severity for record in active)
    valid_repeats = [record.repeat_times for record in active if record.repeat_times is not None]
    values = {
        "active_alarm_records": len(active),
        "active_alarm_groups": len(groups),
        "critical_active": severity_counts["CRITICAL"],
        "high_active": severity_counts["HIGH"],
        "medium_active": severity_counts["MEDIUM"],
        "low_active": severity_counts["LOW"],
        "unknown_active": severity_counts["UNKNOWN"],
        "active_repeat_times_total": sum(valid_repeats),
        "max_single_repeat_times": max(valid_repeats, default=0),
        "active_estimated_reports_total": sum(1 + value for value in valid_repeats),
    }
    return [{"key": key, "label": label, "value": values[key], "unit": unit} for key, label, unit in _METRICS]


def _findings(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for group in groups[:100]:
        source = group["source_refs"][0]
        findings.append(
            {
                "finding_id": stable_hash(group["group_key"], prefix="alarm.active_state:"),
                "title": f"未清除告警：{group['alarm_name']}",
                "severity": _SEVERITY_TO_FINDING[group["severity"]],
                "source_file": source["source_file"],
                "evidence": (
                    f"line_no={source['line_no']}; app_name={group['app_name']}; "
                    f"alarm_id={group['alarm_id']}; alarm_name={group['alarm_name']}; "
                    f"object={group['object']}; severity={group['severity']}; "
                    f"duration_sec={group['duration_sec']}; repeat_times={group['raw_repeat_times_total']}; "
                    f"estimated_report_count={group['estimated_report_total']}"
                ),
                "recommendation": "核对活动告警对象现状并优先处置高严重级、重复上报量大的告警",
            }
        )
    return findings


def _metadata(
    parsed: AlarmParseResult,
    active: list[AlarmRecord],
    groups: list[dict[str, Any]],
    active_records: list[dict[str, Any]],
) -> dict[str, Any]:
    failed_files = sum(item.status != "matched" for item in parsed.files)
    severity_counts = Counter(record.severity for record in active)
    valid_repeats = [record.repeat_times for record in active if record.repeat_times is not None]
    highest = min((record.severity for record in active), key=_SEVERITY_RANK.__getitem__, default="NONE")
    return {
        "schema_version": 1,
        "scope": {
            "source_patterns": _SOURCE_PATTERNS,
            "direct_alarm_csv_only": True,
            "operation_log_used": False,
            "cross_task_data_used": False,
        },
        "coverage": parsed.coverage.as_dict(),
        "totals": {
            "source_files": len(parsed.files),
            "failed_files": failed_files,
            "raw_rows": parsed.raw_rows,
            "valid_records": parsed.valid_records,
            "excluded_records": parsed.quality.excluded_rows,
            "duplicate_records": parsed.duplicate_rows,
            "active_records": len(active),
            "active_groups": len(groups),
            "repeat_totals_complete": parsed.quality.repeat_totals_complete,
            "estimated_report_totals_complete": parsed.quality.estimated_report_totals_complete,
            "details_truncated": len(groups) > 100 or len(active_records) > 100,
            "findings_truncated": len(groups) > 100,
        },
        "status_counts": dict(parsed.status_counts),
        "active_severity_counts": {severity: severity_counts[severity] for severity in SEVERITY_ORDER},
        "active_summary": {
            "highest_severity": highest,
            "raw_repeat_times_total": sum(valid_repeats),
            "max_single_repeat_times": max(valid_repeats, default=0),
            "estimated_report_total": sum(1 + value for value in valid_repeats),
            "estimated_total_is_estimate": True,
        },
        "groups": groups[:100],
        "records": active_records[:100],
        "quality": parsed.quality.as_dict(),
        "files": [item.as_dict() for item in parsed.files],
        "notes": [
            "活动状态唯一判据为 Whether Cleared=Not Cleared",
            "估算上报总数为 Σ(1 + Repeat Times)，不是精确事件总数",
            "Reset Cleared 不代表稳定恢复",
        ],
    }


def _run(ctx: RuleContext) -> object:
    if not ctx.files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 alarm/ 直属 CSV 告警文件",
            skip_reason="未发现 alarm/ 直属 CSV 告警文件",
            metadata={"alarm_active": {"schema_version": 1, "files": [], "groups": [], "records": []}},
        )

    parsed = parse_alarm_files(
        [(relative.as_posix(), absolute) for relative, absolute in zip(ctx.files, ctx.resolved_files(), strict=True)]
    )
    if not parsed.records:
        all_format_invalid = bool(parsed.files) and all(
            item.status == "failed" and item.error_code == "format_invalid" for item in parsed.files
        )
        skip_reason = "告警 CSV 格式不适用" if all_format_invalid else "告警 CSV 无可分析记录"
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary=skip_reason,
            skip_reason=skip_reason,
            metadata={
                "alarm_active": {
                    "schema_version": 1,
                    "coverage": parsed.coverage.as_dict(),
                    "quality": parsed.quality.as_dict(),
                    "files": [item.as_dict() for item in parsed.files],
                    "groups": [],
                    "records": [],
                }
            },
        )

    active = [record for record in parsed.records if record.state == "Not Cleared"]
    groups = _group_views(active, parsed)
    records = [_record_view(record, parsed) for record in active]
    records.sort(
        key=lambda item: (
            _SEVERITY_RANK[item["severity"]],
            -(item["repeat_times"] if item["repeat_times"] is not None else -1),
            -item["duration_sec"],
            item["source_file"],
            item["line_no"],
        )
    )
    metrics = _metrics(active, groups)
    quality_degraded = _quality_degraded(parsed)
    high_risk = any(record.severity in {"CRITICAL", "HIGH"} for record in active)
    if high_risk:
        status = RuleStatus.FAIL
    elif active or quality_degraded:
        status = RuleStatus.WARN
    else:
        status = RuleStatus.PASS

    failed_files = sum(item.status != "matched" for item in parsed.files)
    highest = min((record.severity for record in active), key=_SEVERITY_RANK.__getitem__, default="NONE")
    summary = f"活动告警 {len(active)} 条、{len(groups)} 组；最高严重级 {highest}"
    if high_risk:
        summary = f"发现高风险未清除告警：{summary}"
    elif not active:
        summary = "未发现未清除告警"
    if failed_files:
        summary = f"{summary}；失败文件 {failed_files}"
    if quality_degraded and not high_risk:
        summary = f"{summary}；数据质量或解析完整性降级"

    metadata = _metadata(parsed, active, groups, records)
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=metrics,
        findings=_findings(groups),
        metadata={"alarm_active": metadata},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
