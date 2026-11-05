"""HTML 报告渲染（Jinja2 模板）。"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.schemas import RuleResult, Severity, SystemInspection

SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


def ordered_findings(system: SystemInspection) -> list[tuple[RuleResult, object]]:
    """报告展示顺序：严重度优先，同级按规则优先级和规则代码稳定排序。"""
    findings = [(rule, finding) for rule in system.rules for finding in rule.findings]
    return sorted(
        findings,
        key=lambda item: (
            SEVERITY_ORDER[item[1].severity],
            item[0].priority.value,
            item[0].code,
            item[1].finding_id,
        ),
    )


CURRENT_HEALTH_ORDER = (
    "fail",
    "warn",
    "unable_to_judge",
    "pending_config",
    "not_applicable",
    "normal",
)
CURRENT_HEALTH_LABELS = {
    "fail": "失败",
    "warn": "预警",
    "unable_to_judge": "无法判定",
    "pending_config": "待配置",
    "not_applicable": "不适用",
    "normal": "正常",
}
TREND_HEALTH_ORDER = ("worsened", "improved", "observe", "no_baseline", "stable")
TREND_HEALTH_LABELS = {
    "worsened": "恶化",
    "improved": "改善",
    "observe": "观察",
    "no_baseline": "无昨日基线",
    "stable": "稳定",
}
IMPORTANCE_ORDER = {"P0": 0, "P1": 1, "P2": 2, "normal": 3}
OUT_OF_SCOPE_REASON_LABELS = {
    "disabled_unit": "停用测量单元",
    "unconfirmed_binding": "未确认绑定",
}

SEVERITY_LABELS = {
    "CRITICAL": "紧急",
    "HIGH": "严重",
    "MEDIUM": "重要",
    "LOW": "次要",
    "UNKNOWN": "未知",
    "NONE": "无",
}


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _format_duration(seconds: Any) -> str:
    value = _as_int(seconds)
    if value < 60:
        return f"{value} 秒"
    if value < 3600:
        return f"{value} 秒（{round(value / 60)} 分钟）"
    return f"{value} 秒（{value / 3600:.1f} 小时）"


def active_alarm_report_context(system: SystemInspection) -> dict[str, Any] | None:
    """从活动告警规则自身 metadata 构建报告摘要，不推断恢复状态。"""
    rule = next((item for item in system.rules if item.code == "alarm.active_state"), None)
    if rule is None:
        return None
    metadata = rule.metadata.get("alarm_active")
    if not isinstance(metadata, dict):
        return None

    totals = metadata.get("totals") if isinstance(metadata.get("totals"), dict) else {}
    summary = metadata.get("active_summary") if isinstance(metadata.get("active_summary"), dict) else {}
    coverage = metadata.get("coverage") if isinstance(metadata.get("coverage"), dict) else {}
    groups = metadata.get("groups") if isinstance(metadata.get("groups"), list) else []
    highest = str(summary.get("highest_severity") or "NONE")
    recommendation = next(
        (finding.recommendation for finding in rule.findings if finding.recommendation),
        "优先处置紧急和严重活动告警，核对对象当前状态。",
    )
    top_groups = []
    for group in groups[:5]:
        if not isinstance(group, dict):
            continue
        severity = str(group.get("severity") or "UNKNOWN")
        top_groups.append(
            {
                "alarm_id": str(group.get("alarm_id") or ""),
                "alarm_name": str(group.get("alarm_name") or "未知告警"),
                "app_name": str(group.get("app_name") or ""),
                "object": str(group.get("object") or "对象未知"),
                "severity": SEVERITY_LABELS.get(severity, severity),
                "duration": _format_duration(group.get("duration_sec")),
                "raw_repeat_times_total": _as_int(group.get("raw_repeat_times_total")),
                "estimated_report_total": _as_int(group.get("estimated_report_total")),
            }
        )

    notes = [str(note) for note in metadata.get("notes", []) if note]
    return {
        "active_records": _as_int(totals.get("active_records")),
        "active_groups": _as_int(totals.get("active_groups")),
        "highest_severity": SEVERITY_LABELS.get(highest, highest),
        "raw_repeat_times_total": _as_int(summary.get("raw_repeat_times_total")),
        "max_single_repeat_times": _as_int(summary.get("max_single_repeat_times")),
        "estimated_report_total": _as_int(summary.get("estimated_report_total")),
        "coverage_end_at": str(coverage.get("end_at") or "—"),
        "observation_note": str(
            coverage.get("observation_note") or "coverage_end 是告警数据末刻，不是任务执行时刻或真实恢复时刻"
        ),
        "recommendation": recommendation,
        "groups": top_groups,
        "notes": notes,
    }


def _metric_display(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


def _metric_today_denominator(metric: dict[str, Any]) -> bool:
    objects = metric.get("objects")
    if not isinstance(objects, list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("denominator"), (int, float))
        and not isinstance(item.get("denominator"), bool)
        and float(item["denominator"]) == 0
        for item in objects
    )


def kpi_daily_health_report_context(system: SystemInspection) -> dict[str, Any] | None:
    """把 KPI 日健康 metadata 转成报告视图，不重新计算任何状态。"""
    rule = next((item for item in system.rules if item.code == "kpi.measurement_units"), None)
    if rule is None:
        return None
    metadata = rule.metadata.get("daily_health")
    if not isinstance(metadata, dict):
        return {
            "legacy": True,
            "message": "旧任务无日健康结论；既有指标和发现仍可查看。",
        }

    raw_current = metadata.get("current_counts") if isinstance(metadata.get("current_counts"), dict) else {}
    raw_trend = metadata.get("trend_counts") if isinstance(metadata.get("trend_counts"), dict) else {}
    current_distribution = [
        {
            "status": status,
            "label": CURRENT_HEALTH_LABELS[status],
            "count": _as_int(raw_current.get(status)),
        }
        for status in CURRENT_HEALTH_ORDER
    ]
    trend_distribution = [
        {
            "status": status,
            "label": TREND_HEALTH_LABELS[status],
            "count": _as_int(raw_trend.get(status)),
        }
        for status in TREND_HEALTH_ORDER
    ]

    metrics = (
        [item for item in metadata.get("metrics", []) if isinstance(item, dict)]
        if isinstance(metadata.get("metrics"), list)
        else []
    )
    focus_metrics = []
    for metric in metrics:
        current_status = str(metric.get("current_status") or "unable_to_judge")
        trend_status = str(metric.get("trend_status") or "no_baseline")
        if current_status == "normal" and trend_status not in {"worsened", "observe"}:
            continue
        focus_metrics.append(
            {
                **metric,
                "_current_rank": CURRENT_HEALTH_ORDER.index(current_status)
                if current_status in CURRENT_HEALTH_ORDER
                else len(CURRENT_HEALTH_ORDER),
                "_trend_rank": TREND_HEALTH_ORDER.index(trend_status)
                if trend_status in TREND_HEALTH_ORDER
                else len(TREND_HEALTH_ORDER),
            }
        )
    focus_metrics.sort(
        key=lambda item: (
            int(item["_current_rank"]),
            int(item["_trend_rank"]),
            IMPORTANCE_ORDER.get(str(item.get("importance") or "normal"), 4),
            str(item.get("measurement_unit_name_zh") or ""),
            str(item.get("metric_resource_name_zh") or item.get("metric_resource_id") or ""),
        )
    )
    focus_view = [
        {
            "measurement_unit_name_zh": str(item.get("measurement_unit_name_zh") or ""),
            "metric_resource_id": str(item.get("metric_resource_id") or ""),
            "metric_resource_name_zh": str(
                item.get("metric_resource_name_zh") or item.get("metric_resource_id") or "未命名指标"
            ),
            "current_status": str(item.get("current_status") or "unable_to_judge"),
            "current_status_label": CURRENT_HEALTH_LABELS.get(
                str(item.get("current_status") or "unable_to_judge"), "无法判定"
            ),
            "current_reason": str(item.get("current_reason_text") or item.get("current_reason") or ""),
            "today_display": _metric_display(item.get("today_display")),
            "yesterday_display": _metric_display(item.get("yesterday_display")),
            "delta_display": _metric_display(item.get("delta_display")),
            "trend_status": str(item.get("trend_status") or "no_baseline"),
            "trend_status_label": TREND_HEALTH_LABELS.get(str(item.get("trend_status") or "no_baseline"), "无昨日基线"),
            "trend_reason": str(item.get("trend_reason") or ""),
        }
        for item in focus_metrics[:12]
    ]

    zero_denominator_metrics = []
    for metric in metrics:
        if not _metric_today_denominator(metric):
            continue
        objects = metric.get("objects")
        assert isinstance(objects, list)
        for item in objects:
            if not isinstance(item, dict):
                continue
            denominator = item.get("denominator")
            if not isinstance(denominator, (int, float)) or isinstance(denominator, bool) or denominator != 0:
                continue
            object_key = str(item.get("object_key") or "未知对象")
            period = item.get("period_minutes")
            period_label = f"{period} 分钟" if isinstance(period, int) else "未分周期"
            zero_denominator_metrics.append(
                {
                    "metric_resource_id": str(metric.get("metric_resource_id") or ""),
                    "metric_resource_name_zh": str(
                        metric.get("metric_resource_name_zh") or metric.get("metric_resource_id") or "未命名指标"
                    ),
                    "object_label": f"{object_key} / {period_label}",
                    "numerator": _metric_display(item.get("numerator")),
                    "denominator": _metric_display(denominator),
                    "valid_count": _as_int(item.get("valid_count")),
                }
            )

    raw_scope = metadata.get("scope") if isinstance(metadata.get("scope"), dict) else {}
    raw_reasons = (
        raw_scope.get("out_of_scope_reason_counts")
        if isinstance(raw_scope.get("out_of_scope_reason_counts"), dict)
        else {}
    )
    scope = {
        "enabled_measurement_unit_count": _as_int(raw_scope.get("enabled_measurement_unit_count")),
        "confirmed_binding_metric_count": _as_int(raw_scope.get("confirmed_binding_metric_count")),
        "expected_metric_count": _as_int(raw_scope.get("expected_metric_count")),
        "out_of_scope_file_count": _as_int(raw_scope.get("out_of_scope_file_count")),
        "unconfirmed_binding_count": _as_int(raw_scope.get("unconfirmed_binding_count")),
        "reasons": [
            {
                "code": str(code),
                "label": OUT_OF_SCOPE_REASON_LABELS.get(str(code), str(code)),
                "count": _as_int(count),
            }
            for code, count in sorted(raw_reasons.items())
        ],
    }
    legacy = metadata.get("legacy_fallback")
    legacy_message = str(legacy.get("message")) if isinstance(legacy, dict) and legacy.get("message") else None
    return {
        "legacy": legacy_message is not None,
        "message": legacy_message or "旧任务无日健康结论；既有指标和发现仍可查看。",
        "data_date": str(metadata.get("data_date") or "—"),
        "previous_date": str(metadata.get("previous_date") or "—"),
        "timezone": str(metadata.get("timezone") or "Asia/Shanghai"),
        "latest_measured_at": _metric_display(metadata.get("latest_measured_at")),
        "current_distribution": current_distribution,
        "trend_distribution": trend_distribution,
        "current_total": sum(item["count"] for item in current_distribution),
        "trend_total": sum(item["count"] for item in trend_distribution),
        "focus_metrics": focus_view,
        "zero_denominator_metrics": zero_denominator_metrics,
        "scope": scope,
    }


def render_report(output: Path, task_id: str, system: SystemInspection, completed_at=None) -> Path:
    template_dir = Path(__file__).resolve().parents[1] / "reports" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html.j2").render(
        task_id=task_id,
        system=system,
        findings=ordered_findings(system),
        completed_at=completed_at,
        alarm_active=active_alarm_report_context(system),
        kpi_daily_health=kpi_daily_health_report_context(system),
    )
    path = output / task_id / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
