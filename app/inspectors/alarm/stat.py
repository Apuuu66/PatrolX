"""alarm.stat（P1）：告警量统计与未处理告警检查。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import csv
from collections import Counter

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

UNHANDLED_STATUS = {"未处理", "UNHANDLED", "OPEN"}


inspector = Inspector(
    code="alarm.stat",
    name="告警统计检查",
    category=RuleCategory.ALARM,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.1.0",
    description="统计告警总量、严重级分布与未处理/未清除告警；存在 CRITICAL 或未处理告警时告警",
    recommendation="优先处理 CRITICAL/HIGH 未处理告警，核查根因",
    source_refs=["alarm_all"],
    outputs_metrics=[
        {"key": "alarm_total", "label": "告警总量", "unit": "条"},
        {"key": "unhandled", "label": "未处理告警", "unit": "条"},
    ],
    params=[
        {"key": "unhandled_max", "label": "未处理告警上限", "default": "0"},
        {"key": "status_field", "label": "状态字段", "default": "status"},
        {"key": "cleared_time_field", "label": "清除时间字段", "default": "cleared_time"},
    ],
)


def _read_csv_alarm(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict] = []
        for raw in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            status = row.get("status", "")
            cleared = row.get("cleared_time", "")
            rows.append(
                {
                    "time": row.get("created_time") or row.get("first_occurrence_time") or "",
                    "code": row.get("alarm_code") or row.get("code") or "",
                    "severity": row.get("severity", "").upper(),
                    "status": status,
                    "object": row.get("object") or row.get("object_name") or "",
                    "cleared": bool(cleared),
                }
            )
        return rows


def _read_text_alarms(path: Path) -> list[dict]:
    rows: list[dict] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 7 or parts[0].upper() != "ALARM":
            continue
        rows.append(
            {
                "time": f"{parts[1]} {parts[2]}",
                "code": parts[3],
                "severity": parts[-2].upper(),
                "status": parts[-1],
                "object": "",
                "cleared": parts[-1].lower() not in {"unhandled", "open"},
            }
        )
    return rows


def _read_alarms(files: list[Path]) -> tuple[list[dict], Counter[str], int]:
    alarms: list[dict] = []
    severity_counts: Counter[str] = Counter()
    unhandled = 0
    for path in files:
        try:
            if path.suffix.lower() == ".csv":
                rows = _read_csv_alarm(path)
            else:
                rows = _read_text_alarms(path)
        except (OSError, csv.Error):
            continue
        alarms.extend(rows)
        for row in rows:
            severity = row["severity"]
            severity_counts[severity] += 1
            if not row["cleared"] or row["status"].upper() in UNHANDLED_STATUS or row["status"] == "未处理":
                unhandled += 1
    return alarms, severity_counts, unhandled


def _run(ctx: RuleContext) -> object:
    files = sorted(ctx.resolved_files())
    alarms, severity_counts, unhandled = _read_alarms(files)
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
                source_file=files[0].relative_to(ctx.data_dir).as_posix(),
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
