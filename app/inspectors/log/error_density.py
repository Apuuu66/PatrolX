"""log.error_density（P1）：直接统计源日志错误密度。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.log.common import log_processed_files, read_records
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

MAX_ERRORS = 100
ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL"}

inspector = Inspector(
    code="log.error_density",
    name="日志错误密度",
    category=RuleCategory.LOG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="4.0.0",
    description="统计 source_patterns 匹配日志中的 ERROR/FATAL/CRITICAL 条数，超过阈值告警",
    recommendation="检查异常来源模块，必要时查看完整日志上下文",
    source_patterns=[r"^logs/.*\.log$"],
    outputs_metrics=[{"key": "error_count", "label": "错误条数", "unit": "条"}],
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
    errors = [record for record in records if record["level"] in ERROR_LEVELS]
    error_count = len(errors)
    processed_files_list = log_processed_files(ctx, inspector.code, sorted({r["source_file"] for r in records}))
    if error_count > MAX_ERRORS * 2:
        status, summary = RuleStatus.FAIL, f"错误日志密度严重超限：{error_count} 条"
    elif error_count > MAX_ERRORS:
        status, summary = RuleStatus.WARN, f"错误日志密度超限：{error_count} 条"
    else:
        status, summary = RuleStatus.PASS, f"错误日志密度正常：{error_count} 条"
    findings = []
    if errors:
        first = errors[0]
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-f001",
                title=summary,
                severity=Severity.MEDIUM,
                source_file=first["source_file"],
                evidence=first["message"],
                recommendation=inspector.recommendation,
            )
        )
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[{"key": "error_count", "label": "错误条数", "value": error_count, "unit": "条"}],
        findings=findings,
        metadata={"processed_files": processed_files_list},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
