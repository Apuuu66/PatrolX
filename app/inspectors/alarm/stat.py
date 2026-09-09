"""alarm.stat（P1）：告警量统计与未处理告警检查。"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

inspector = Inspector(
    code="alarm.stat",
    name="告警统计检查",
    category=RuleCategory.ALARM,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="统计告警总量与严重级分布，存在未处理告警或 CRITICAL 告警时告警",
    recommendation="优先处理 CRITICAL/HIGH 未处理告警，核查根因",
    outputs_metrics=[
        {"key": "alarm_total", "label": "告警总量", "unit": "条"},
        {"key": "unhandled", "label": "未处理告警", "unit": "条"},
    ],
    params=[{"key": "unhandled_max", "label": "未处理告警上限", "default": "0"}],
)


def _read_alarms(root: Path) -> tuple[list[dict], Counter[str], int]:
    alarms: list[dict] = []
    severity_counts: Counter[str] = Counter()
    unhandled = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 7 or parts[0].upper() != "ALARM":
                continue
            severity = parts[-2].upper()
            status = parts[-1]
            alarms.append({"time": f"{parts[1]} {parts[2]}", "code": parts[3], "severity": severity, "status": status})
            severity_counts[severity] += 1
            if status in {"未处理", "UNHANDLED", "OPEN"}:
                unhandled += 1
    return alarms, severity_counts, unhandled


def _run(ctx: RuleContext) -> object:
    root = ctx.data_dir / RuleCategory.ALARM.value
    alarms, severity_counts, unhandled = _read_alarms(root)
    if not alarms:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现告警类文件",
            skip_reason="未发现告警类文件",
        )
    critical = severity_counts.get("CRITICAL", 0)
    findings: list[Finding] = []
    if unhandled or critical:
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-unhandled",
                title="存在未处理/严重告警",
                severity=Severity.HIGH,
                source_file="告警导出数据",
                evidence=f"告警总量 {len(alarms)} 条，未处理 {unhandled} 条，CRITICAL {critical} 条",
                recommendation=inspector.recommendation,
            )
        )
    status = RuleStatus.FAIL if critical else RuleStatus.WARN if unhandled else RuleStatus.PASS
    summary = f"告警检查完成：{len(alarms)} 条（CRITICAL {critical}，未处理 {unhandled}）"
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "alarm_total", "label": "告警总量", "value": len(alarms), "unit": "条"},
            {"key": "unhandled", "label": "未处理告警", "value": unhandled, "unit": "条"},
        ],
        findings=findings,
        metadata={"severity_distribution": dict(severity_counts)},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
