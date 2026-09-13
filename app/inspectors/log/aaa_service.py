"""log.aaa_service（P1）：AAAService 专属日志巡检。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.log.common import log_service_processed_files, service_records
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

SERVICE_NAME = "AAAService"
ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL"}
AUTH_FAIL_COUNT = 3

inspector = Inspector(
    code="log.aaa_service",
    name="AAAService 日志巡检",
    category=RuleCategory.LOG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="4.0.0",
    description="检查 AAAService 的认证失败和重试定时器超限",
    recommendation="检查认证服务可用性、账号锁定策略和重试定时器配置",
    source_patterns=[r"^logs/.*\.log$"],
    outputs_metrics=[
        {"key": "error_count", "label": "错误条数", "unit": "条"},
        {"key": "auth_failure_count", "label": "认证失败条数", "unit": "条"},
        {"key": "retry_timer_count", "label": "重试定时器超限条数", "unit": "条"},
    ],
)


def _run(ctx: RuleContext) -> object:
    records, source_files = service_records(ctx, SERVICE_NAME)
    if not records:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 AAAService 日志",
            skip_reason="未发现 AAAService 日志",
        )

    processed_files = log_service_processed_files(ctx, inspector.code, source_files)
    auth_records = [record for record in records if "auth failure" in record["message"].lower()]
    retry_records = [record for record in records if "retry timer exceeded" in record["message"].lower()]
    error_count = sum(record.get("level") in ERROR_LEVELS for record in records)

    findings: list[Finding] = []
    if auth_records:
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-auth-failure",
                title="AAAService 认证失败",
                severity=Severity.MEDIUM,
                source_file=auth_records[0]["source_file"],
                evidence=auth_records[0]["message"],
                details=f"命中 {len(auth_records)} 条认证失败日志",
                recommendation=inspector.recommendation,
            )
        )
    elif retry_records:
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-retry-timer",
                title="AAAService 重试定时器超限",
                severity=Severity.MEDIUM,
                source_file=retry_records[0]["source_file"],
                evidence=retry_records[0]["message"],
                details=f"命中 {len(retry_records)} 条重试定时器超限日志",
                recommendation=inspector.recommendation,
            )
        )

    if len(auth_records) >= AUTH_FAIL_COUNT or len(retry_records) >= AUTH_FAIL_COUNT:
        status = RuleStatus.FAIL
        summary = "AAAService 认证失败持续增加" if auth_records else "AAAService 重试定时器频繁超限"
    elif auth_records or retry_records:
        status = RuleStatus.WARN
        summary = "AAAService 存在认证失败" if auth_records else "AAAService 重试定时器超限"
    else:
        status = RuleStatus.PASS
        summary = "AAAService 日志正常"

    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "error_count", "label": "错误条数", "value": error_count, "unit": "条"},
            {"key": "auth_failure_count", "label": "认证失败条数", "value": len(auth_records), "unit": "条"},
            {"key": "retry_timer_count", "label": "重试定时器超限条数", "value": len(retry_records), "unit": "条"},
        ],
        findings=findings,
        metadata={"processed_files": processed_files},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
