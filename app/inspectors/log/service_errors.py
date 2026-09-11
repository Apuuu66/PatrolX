"""log.service_errors（P1）：按服务聚合错误，识别错误集中服务。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.log.common import filtered_path, log_processed_files, read_records
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

WARN_SERVICE_ERRORS = 5
FAIL_SERVICE_ERRORS = 20

inspector = Inspector(
    code="log.service_errors",
    name="服务日志错误集中度",
    category=RuleCategory.LOG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="按服务聚合 ERROR/FATAL/CRITICAL 日志，识别错误最集中的服务",
    recommendation="优先排查错误最集中的服务及其数据库、网络和下游依赖",
    inputs=["log.filter.artifacts.filtered_logs"],
    outputs_metrics=[
        {"key": "service_count", "label": "服务数量", "unit": "个"},
        {"key": "error_service_count", "label": "存在错误的服务数", "unit": "个"},
        {"key": "max_service_error_count", "label": "单服务最大错误数", "unit": "条"},
    ],
)


def _run(ctx: RuleContext) -> object:
    path = filtered_path(ctx)
    if path is None:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="依赖过滤产物缺失",
            skip_reason="依赖产物 log.filter.artifacts.filtered_logs 缺失或缺少 filtered.jsonl",
        )

    processed_files_list = log_processed_files(ctx, path, inspector.code)

    services: dict[str, dict] = {}
    for record in read_records(path):
        service = services.setdefault(record["service"], {"errors": 0, "levels": {}, "first": record})
        level = record["level"]
        service["levels"][level] = service["levels"].get(level, 0) + 1
        if level in ("ERROR", "FATAL", "CRITICAL"):
            service["errors"] += 1

    if not services:
        return make_result(
            inspector,
            status=RuleStatus.PASS,
            summary="无服务日志记录",
            metrics=[
                {"key": "service_count", "label": "服务数量", "value": 0, "unit": "个"},
                {"key": "error_service_count", "label": "存在错误的服务数", "value": 0, "unit": "个"},
                {"key": "max_service_error_count", "label": "单服务最大错误数", "value": 0, "unit": "条"},
            ],
            metadata={"processed_files": processed_files_list},
        )

    max_service = max(services, key=lambda name: (services[name]["errors"], name))
    max_count = services[max_service]["errors"]
    error_service_count = sum(item["errors"] > 0 for item in services.values())

    if max_count > FAIL_SERVICE_ERRORS:
        status, summary = RuleStatus.FAIL, f"服务错误严重集中：{max_service} {max_count} 条"
    elif max_count >= WARN_SERVICE_ERRORS:
        status, summary = RuleStatus.WARN, f"服务错误集中：{max_service} {max_count} 条"
    else:
        status, summary = RuleStatus.PASS, f"服务错误分布正常：共 {len(services)} 个服务"

    findings = []
    if status != RuleStatus.PASS:
        first = services[max_service]["first"]
        findings = [
            Finding(
                finding_id=f"{inspector.code}-f001",
                title=f"{max_service} 服务错误集中",
                severity=Severity.MEDIUM,
                source_file=first["source_file"],
                evidence=first["message"],
                recommendation=inspector.recommendation,
            )
        ]

    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "service_count", "label": "服务数量", "value": len(services), "unit": "个"},
            {"key": "error_service_count", "label": "存在错误的服务数", "value": error_service_count, "unit": "个"},
            {"key": "max_service_error_count", "label": "单服务最大错误数", "value": max_count, "unit": "条"},
        ],
        findings=findings,
        metadata={
            "service_error_counts": {name: item["errors"] for name, item in services.items()},
            "service_level_counts": {name: item["levels"] for name, item in services.items()},
            "hot_service": max_service,
            "processed_files": processed_files_list,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
