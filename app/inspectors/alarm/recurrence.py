"""alarm.recurrence（P1）：汇总告警生命周期并识别反复上报风险。"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.alarm.common import (
    SEVERITY_ORDER,
    STATE_ORDER,
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
SHORT_ALARM_SEC = 300
RAPID_RECURRENCE_WINDOW_SEC = 3600
RAPID_RECURRENCE_MIN_COUNT = 3
_MAX_DETAILS = 100
_METRICS = (
    ("matched_files", "匹配告警文件数", "个"),
    ("valid_lifecycles", "有效告警生命周期数", "条"),
    ("alarm_types", "告警类型数", "种"),
    ("multi_lifecycle_types", "多次发生告警类型数", "种"),
    ("repeat_reporting_types", "重复上报告警类型数", "种"),
    ("short_alarm_types", "短告警类型数", "种"),
    ("rapid_recurrence_types", "快速复发告警类型数", "种"),
    ("reset_cleared_lifecycles", "重置清除生命周期数", "条"),
    ("repeat_positive_lifecycles", "Repeat Times 大于 0 生命周期数", "条"),
    ("raw_repeat_times_total", "原始重复次数合计", "次"),
    ("estimated_reports_total", "估算上报总数", "次"),
)

inspector = Inspector(
    code="alarm.recurrence",
    name="告警反复上报巡检",
    category=RuleCategory.ALARM,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="按应用与告警 ID 汇总生命周期，识别重复上报、短告警、快速复发和重置清除风险",
    recommendation="结合对象明细核查反复上报根因；原始重复次数与估算上报总数仅作为告警文件内的两个独立口径",
    source_refs=["alarm_all"],
    outputs_metrics=[{"key": key, "label": label, "unit": unit} for key, label, unit in _METRICS],
    params=[
        {"name": "short_alarm_sec", "value": str(SHORT_ALARM_SEC)},
        {"name": "rapid_recurrence_window_sec", "value": str(RAPID_RECURRENCE_WINDOW_SEC)},
        {"name": "rapid_recurrence_min_count", "value": str(RAPID_RECURRENCE_MIN_COUNT)},
    ],
)


@dataclass(slots=True)
class _Bucket:
    app_name: str
    alarm_id: str
    alarm_name: str
    records: list[AlarmRecord] = field(default_factory=list)

    def add(self, record: AlarmRecord) -> None:
        self.records.append(record)


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


def _duration(record: AlarmRecord, parsed: AlarmParseResult) -> int | None:
    if record.cleared_at is not None:
        return record.duration_sec
    if record.state == "Not Cleared" and parsed.coverage.end_at is not None:
        return max(0, int((parsed.coverage.end_at - record.raised_at).total_seconds()))
    return None


def _rapid_recurrence(records: list[AlarmRecord]) -> bool:
    timestamps = sorted(record.raised_at for record in records)
    if len(timestamps) < RAPID_RECURRENCE_MIN_COUNT:
        return False
    for index in range(len(timestamps) - RAPID_RECURRENCE_MIN_COUNT + 1):
        span = (timestamps[index + RAPID_RECURRENCE_MIN_COUNT - 1] - timestamps[index]).total_seconds()
        if span <= RAPID_RECURRENCE_WINDOW_SEC:
            return True
    return False


def _flags(records: list[AlarmRecord], parsed: AlarmParseResult) -> dict[str, bool]:
    valid_repeats = [record.repeat_times for record in records if record.repeat_times is not None]
    short_alarm = any(
        record.state != "Not Cleared"
        and (duration := _duration(record, parsed)) is not None
        and 0 <= duration <= SHORT_ALARM_SEC
        for record in records
    )
    return {
        "multi_lifecycle": len(records) > 1,
        "repeat_reporting": sum(valid_repeats) > 0,
        "short_alarm": short_alarm,
        "rapid_recurrence": _rapid_recurrence(records),
        "reset_cleared": any(record.state == "Reset Cleared" for record in records),
    }


def _min_adjacent_gap(records: list[AlarmRecord]) -> int | None:
    timestamps = sorted(record.raised_at for record in records)
    if len(timestamps) < 2:
        return None
    return min(
        int((later - earlier).total_seconds()) for earlier, later in zip(timestamps, timestamps[1:], strict=False)
    )


def _source_refs(records: list[AlarmRecord]) -> list[dict[str, str | int]]:
    refs = sorted({(record.source_file, record.line_no) for record in records}, key=lambda item: (item[0], item[1]))
    return [{"source_file": source_file, "line_no": line_no} for source_file, line_no in refs[:_MAX_DETAILS]]


def _summary_view(
    records: list[AlarmRecord],
    parsed: AlarmParseResult,
    *,
    app_name: str,
    alarm_id: str,
    alarm_name: str,
    include_objects: bool,
) -> dict[str, Any]:
    status_counts = Counter({state: 0 for state in STATE_ORDER})
    status_counts.update(record.state for record in records)
    severity_counts = Counter({severity: 0 for severity in SEVERITY_ORDER})
    severity_counts.update(record.severity for record in records)
    valid_repeats = [record.repeat_times for record in records if record.repeat_times is not None]
    durations = [duration for record in records if (duration := _duration(record, parsed)) is not None]
    flags = _flags(records, parsed)
    view: dict[str, Any] = {
        "type_key": stable_hash(app_name, alarm_id, prefix="alarm.recurrence:"),
        "app_name": app_name,
        "alarm_id": alarm_id,
        "alarm_name": alarm_name,
        "lifecycle_count": len(records),
        "not_cleared_count": status_counts["Not Cleared"],
        "raw_repeat_times_total": sum(valid_repeats),
        "max_single_repeat_times": max(valid_repeats, default=0),
        "estimated_report_total": sum(1 + value for value in valid_repeats),
        "repeat_totals_complete": len(valid_repeats) == len(records),
        "first_raised_at": iso_or_none(min(record.raised_at for record in records)),
        "last_raised_at": iso_or_none(max(record.raised_at for record in records)),
        "max_duration_sec": max(durations, default=None),
        "min_adjacent_gap_sec": _min_adjacent_gap(records),
        "status_counts": {state: status_counts[state] for state in STATE_ORDER},
        "severity_counts": {severity: severity_counts[severity] for severity in SEVERITY_ORDER},
        "flags": flags,
        "source_refs": _source_refs(records),
    }
    if include_objects:
        objects = _object_views(records, parsed, app_name, alarm_id)
        view["object_count"] = len(objects)
        view["objects"] = objects[:_MAX_DETAILS]
        view["objects_truncated"] = len(objects) > _MAX_DETAILS
    return view


def _object_views(
    records: list[AlarmRecord],
    parsed: AlarmParseResult,
    app_name: str,
    alarm_id: str,
) -> list[dict[str, Any]]:
    objects: dict[str, list[AlarmRecord]] = {}
    for record in records:
        objects.setdefault(record.object_key, []).append(record)
    views = [
        _summary_view(
            object_records,
            parsed,
            app_name=app_name,
            alarm_id=alarm_id,
            alarm_name=object_records[0].alarm_name,
            include_objects=False,
        )
        | {"object": object_key}
        for object_key, object_records in objects.items()
    ]
    for view in views:
        view.pop("type_key", None)
    views.sort(
        key=lambda item: (
            _SEVERITY_RANK[_highest_severity(item)],
            -item["raw_repeat_times_total"],
            -item["lifecycle_count"],
            item["object"],
        )
    )
    return views


def _bucket_views(parsed: AlarmParseResult) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], _Bucket] = {}
    for record in parsed.records:
        key = (record.app_name, record.alarm_id)
        bucket = buckets.setdefault(
            key,
            _Bucket(app_name=record.app_name, alarm_id=record.alarm_id, alarm_name=record.alarm_name),
        )
        bucket.add(record)
    views = [
        _summary_view(
            bucket.records,
            parsed,
            app_name=bucket.app_name,
            alarm_id=bucket.alarm_id,
            alarm_name=bucket.alarm_name,
            include_objects=True,
        )
        for bucket in buckets.values()
    ]
    views.sort(key=_type_sort_key)
    return views


def _highest_severity(view: dict[str, Any]) -> str:
    return min(
        (severity for severity, count in view["severity_counts"].items() if count),
        key=_SEVERITY_RANK.__getitem__,
        default="UNKNOWN",
    )


def _has_other_risk(flags: dict[str, bool]) -> bool:
    return any(
        flags[name]
        for name in ("multi_lifecycle", "repeat_reporting", "short_alarm", "rapid_recurrence", "reset_cleared")
    )


def _risk_rank(view: dict[str, Any]) -> int:
    flags = view["flags"]
    if view["not_cleared_count"] and (flags["repeat_reporting"] or flags["rapid_recurrence"]):
        return 0
    if view["not_cleared_count"] and _has_other_risk(flags):
        return 1
    if not view["not_cleared_count"] and any(
        flags[name] for name in ("multi_lifecycle", "repeat_reporting", "short_alarm", "rapid_recurrence")
    ):
        return 2
    if flags["reset_cleared"] or view["severity_counts"]["UNKNOWN"]:
        return 3
    return 4


def _type_sort_key(view: dict[str, Any]) -> tuple[int, int, int, int, str]:
    return (
        _risk_rank(view),
        _SEVERITY_RANK[_highest_severity(view)],
        -view["raw_repeat_times_total"],
        -view["lifecycle_count"],
        view["type_key"],
    )


def _is_risky(view: dict[str, Any]) -> bool:
    return _has_other_risk(view["flags"]) or view["severity_counts"]["UNKNOWN"] > 0


def _findings(types: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for type_view in types:
        if not _is_risky(type_view):
            continue
        source = type_view["source_refs"][0]
        findings.append(
            {
                "finding_id": type_view["type_key"],
                "title": f"告警反复风险：{type_view['alarm_name']}",
                "severity": _SEVERITY_TO_FINDING[_highest_severity(type_view)],
                "source_file": source["source_file"],
                "evidence": (
                    f"line_no={source['line_no']}; app_name={type_view['app_name']}; "
                    f"alarm_id={type_view['alarm_id']}; alarm_name={type_view['alarm_name']}; "
                    f"lifecycle_count={type_view['lifecycle_count']}; "
                    f"raw_repeat_times_total={type_view['raw_repeat_times_total']}; "
                    f"estimated_report_total={type_view['estimated_report_total']}; "
                    f"max_duration_sec={type_view['max_duration_sec']}; "
                    f"multi_lifecycle={str(type_view['flags']['multi_lifecycle']).lower()}; "
                    f"repeat_reporting={str(type_view['flags']['repeat_reporting']).lower()}; "
                    f"short_alarm={str(type_view['flags']['short_alarm']).lower()}; "
                    f"rapid_recurrence={str(type_view['flags']['rapid_recurrence']).lower()}; "
                    f"reset_cleared={str(type_view['flags']['reset_cleared']).lower()}"
                ),
                "recommendation": "结合对象与发生时间核查告警根因，确认反复上报和清除状态是否符合现场事实",
            }
        )
        if len(findings) == _MAX_DETAILS:
            break
    return findings


def _metrics(parsed: AlarmParseResult, types: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid_repeats = [record.repeat_times for record in parsed.records if record.repeat_times is not None]
    values = {
        "matched_files": sum(item.status == "matched" for item in parsed.files),
        "valid_lifecycles": parsed.valid_records,
        "alarm_types": len(types),
        "multi_lifecycle_types": sum(item["flags"]["multi_lifecycle"] for item in types),
        "repeat_reporting_types": sum(item["flags"]["repeat_reporting"] for item in types),
        "short_alarm_types": sum(item["flags"]["short_alarm"] for item in types),
        "rapid_recurrence_types": sum(item["flags"]["rapid_recurrence"] for item in types),
        "reset_cleared_lifecycles": sum(record.state == "Reset Cleared" for record in parsed.records),
        "repeat_positive_lifecycles": sum(value > 0 for value in valid_repeats),
        "raw_repeat_times_total": sum(valid_repeats),
        "estimated_reports_total": sum(1 + value for value in valid_repeats),
    }
    return [{"key": key, "label": label, "value": values[key], "unit": unit} for key, label, unit in _METRICS]


def _metadata(parsed: AlarmParseResult, types: list[dict[str, Any]]) -> dict[str, Any]:
    failed_files = sum(item.status != "matched" for item in parsed.files)
    risky_count = sum(_is_risky(item) for item in types)
    return {
        "schema_version": 1,
        "scope": {
            "source_patterns": _SOURCE_PATTERNS,
            "direct_alarm_csv_only": True,
            "operation_log_used": False,
            "cross_task_data_used": False,
            "stable_recovery_inferred": False,
        },
        "parameters": {
            "short_alarm_sec": SHORT_ALARM_SEC,
            "rapid_recurrence_window_sec": RAPID_RECURRENCE_WINDOW_SEC,
            "rapid_recurrence_min_count": RAPID_RECURRENCE_MIN_COUNT,
            "parameter_source": "default",
        },
        "coverage": parsed.coverage.as_dict(),
        "totals": {
            "source_files": len(parsed.files),
            "failed_files": failed_files,
            "raw_rows": parsed.raw_rows,
            "valid_records": parsed.valid_records,
            "excluded_records": parsed.quality.excluded_rows,
            "duplicate_records": parsed.duplicate_rows,
            "alarm_types": len(types),
            "multi_lifecycle_types": sum(item["flags"]["multi_lifecycle"] for item in types),
            "repeat_reporting_types": sum(item["flags"]["repeat_reporting"] for item in types),
            "short_alarm_types": sum(item["flags"]["short_alarm"] for item in types),
            "rapid_recurrence_types": sum(item["flags"]["rapid_recurrence"] for item in types),
            "reset_cleared_records": sum(record.state == "Reset Cleared" for record in parsed.records),
            "repeat_positive_records": sum(
                record.repeat_times is not None and record.repeat_times > 0 for record in parsed.records
            ),
            "repeat_totals_complete": parsed.quality.repeat_totals_complete,
            "estimated_report_totals_complete": parsed.quality.estimated_report_totals_complete,
            "types_truncated": len(types) > _MAX_DETAILS,
            "details_truncated": len(types) > _MAX_DETAILS
            or any(item["objects_truncated"] for item in types[:_MAX_DETAILS]),
            "findings_truncated": risky_count > _MAX_DETAILS,
        },
        "status_counts": dict(parsed.status_counts),
        "severity_counts": {
            severity: sum(item["severity_counts"][severity] for item in types) for severity in SEVERITY_ORDER
        },
        "types": types[:_MAX_DETAILS],
        "quality": parsed.quality.as_dict(),
        "files": [item.as_dict() for item in parsed.files],
        "notes": [
            "原始 Repeat Times 合计与估算上报总数是两个独立口径",
            "估算上报总数为 Σ(1 + Repeat Times)，不是精确事件总数",
            "快速复发只陈述告警文件中的时间事实，不判断操作时间或计划内外",
            "Reset Cleared 不代表稳定恢复",
            "未根据观察窗末端之后没有记录推断恢复",
        ],
    }


def _skip_metadata(parsed: AlarmParseResult | None) -> dict[str, Any]:
    if parsed is None:
        return {"alarm_recurrence": {"schema_version": 1, "files": [], "types": []}}
    return {
        "alarm_recurrence": {
            "schema_version": 1,
            "coverage": parsed.coverage.as_dict(),
            "quality": parsed.quality.as_dict(),
            "files": [item.as_dict() for item in parsed.files],
            "types": [],
        }
    }


def _run(ctx: RuleContext) -> object:
    if not ctx.files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 alarm/ 直属 CSV 告警文件",
            skip_reason="未发现 alarm/ 直属 CSV 告警文件",
            metadata=_skip_metadata(None),
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
            metadata=_skip_metadata(parsed),
        )

    types = _bucket_views(parsed)
    metrics = _metrics(parsed, types)
    has_active_repeat = any(
        item["not_cleared_count"] and (item["flags"]["repeat_reporting"] or item["flags"]["rapid_recurrence"])
        for item in types
    )
    has_risk = any(_is_risky(item) for item in types)
    quality_degraded = _quality_degraded(parsed)
    if has_active_repeat:
        status = RuleStatus.FAIL
    elif has_risk or quality_degraded:
        status = RuleStatus.WARN
    else:
        status = RuleStatus.PASS

    findings = _findings(types)
    metadata = _metadata(parsed, types)
    failed_files = metadata["totals"]["failed_files"]
    summary = (
        f"有效生命周期 {parsed.valid_records} 条、告警类型 {len(types)} 种；"
        f"反复上报类型 {metadata['totals']['repeat_reporting_types']} 种、"
        f"快速复发类型 {metadata['totals']['rapid_recurrence_types']} 种"
    )
    if has_active_repeat:
        summary = f"发现未清除反复上报风险：{summary}"
    elif has_risk:
        summary = f"发现告警反复或清除风险：{summary}"
    if failed_files:
        summary = f"{summary}；失败文件 {failed_files}"
    if quality_degraded and not has_active_repeat:
        summary = f"{summary}；数据质量或解析完整性降级"

    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=metrics,
        findings=findings,
        metadata={"alarm_recurrence": metadata},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
