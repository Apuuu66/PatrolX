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


def render_report(output: Path, task_id: str, system: SystemInspection, completed_at=None) -> Path:
    template_dir = Path(__file__).resolve().parents[1] / "reports" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=select_autoescape(["html"]))
    html = env.get_template("report.html.j2").render(
        task_id=task_id,
        system=system,
        findings=ordered_findings(system),
        completed_at=completed_at,
        alarm_active=active_alarm_report_context(system),
    )
    path = output / task_id / "report.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
