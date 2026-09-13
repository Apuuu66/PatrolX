"""log.stacktrace（P1）：识别服务日志中的异常类型与堆栈。"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.log.common import log_processed_files, read_records
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

EXCEPTION_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Exception|Error))\b")

inspector = Inspector(
    code="log.stacktrace",
    name="日志堆栈异常识别",
    category=RuleCategory.LOG,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="4.0.0",
    description="从过滤后的日志中识别异常类型和堆栈，并按服务与异常类型聚合",
    recommendation="根据异常类型定位代码路径，优先处理出现最早且重复最多的异常",
    source_patterns=[r"^logs/.*\.log$"],
    outputs_metrics=[
        {"key": "stacktrace_count", "label": "堆栈/异常条数", "unit": "个"},
        {"key": "exception_type_count", "label": "异常类型数", "unit": "类"},
    ],
)


def _run(ctx: RuleContext) -> object:
    records = read_records(ctx)
    if not records:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现匹配日志",
            skip_reason="source_patterns 未发现可解析日志",
        )

    processed_files_list = log_processed_files(ctx, inspector.code, sorted({r["source_file"] for r in records}))

    service_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    groups: dict[tuple[str, str], dict] = {}
    stack_frame_count = 0

    for record in records:
        if record["level"] == "STACK":
            stack_frame_count += 1
        matches = EXCEPTION_RE.findall(record["message"])
        if not matches and record["level"] != "STACK":
            continue
        for exception_type in matches:
            key = (record["service"], exception_type)
            service_counts[record["service"]] += 1
            type_counts[exception_type] += 1
            group = groups.setdefault(key, {"records": []})
            if len(group["records"]) < 5:
                group["records"].append(record)

    if not type_counts:
        return make_result(
            inspector,
            status=RuleStatus.PASS,
            summary="未发现异常堆栈",
            metrics=[
                {"key": "stacktrace_count", "label": "堆栈/异常条数", "value": stack_frame_count, "unit": "个"},
                {"key": "exception_type_count", "label": "异常类型数", "value": 0, "unit": "类"},
            ],
            metadata={"processed_files": processed_files_list},
        )

    top_service = service_counts.most_common(1)[0][0]
    total_occurrences = sum(type_counts.values())
    status = RuleStatus.FAIL if total_occurrences > 5 else RuleStatus.WARN

    findings = []
    for (service, exception_type), group in sorted(groups.items()):
        first = group["records"][0]
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-{service}-{exception_type}".lower().replace("_", "-"),
                title=f"{service} 出现 {exception_type}",
                severity=Severity.HIGH if total_occurrences > 5 else Severity.MEDIUM,
                source_file=first["source_file"],
                evidence="\n".join(record["message"] for record in group["records"])[:4096],
                recommendation=inspector.recommendation,
            )
        )

    return make_result(
        inspector,
        status=status,
        summary=f"发现 {len(type_counts)} 类异常，共 {total_occurrences} 次；最集中服务为 {top_service}",
        metrics=[
            {"key": "stacktrace_count", "label": "堆栈/异常条数", "value": total_occurrences, "unit": "个"},
            {"key": "exception_type_count", "label": "异常类型数", "value": len(type_counts), "unit": "类"},
        ],
        findings=findings,
        metadata={
            "service_counts": dict(service_counts),
            "exception_type_counts": dict(type_counts),
            "stack_frame_count": stack_frame_count,
            "top_service": top_service,
            "processed_files": processed_files_list,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
