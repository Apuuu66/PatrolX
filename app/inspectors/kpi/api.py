"""kpi.api（P1）：API KPI CSV 巡检。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.kpi.common import (
    KpiConfigError,
    build_kpi_metadata,
    finding_id,
    load_kpi_config,
    parse_all_files,
)
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

inspector = Inspector(
    code="kpi.api",
    name="API KPI 巡检",
    category=RuleCategory.KPI,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.2.0",
    description="解析 API KPI CSV 文件，完成识别、完整性检查和指标展示",
    recommendation="检查解析错误行和指标值是否正常",
    source_refs=["kpi_api"],
    outputs_metrics=[
        {"key": "file_count", "label": "文件数", "unit": "个"},
        {"key": "record_count", "label": "记录数", "unit": "条"},
        {"key": "metric_count", "label": "指标列数", "unit": "项"},
        {"key": "parse_error_count", "label": "解析错误数", "unit": "条"},
    ],
)


def _run(ctx: RuleContext) -> object:
    if not ctx.resolved_files():
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 API KPI 文件",
            skip_reason="未匹配到 kpi-api-*.csv 文件",
        )
    try:
        config = load_kpi_config()
    except KpiConfigError as exc:
        return make_result(
            inspector,
            status=RuleStatus.ERROR,
            summary="KPI 配置加载失败",
            metadata={"error": str(exc)},
        )

    files = parse_all_files(ctx.resolved_files(), ctx.data_dir, "api", config)
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 API KPI 文件",
            skip_reason="匹配文件不属于 kpi-api-*.csv",
        )
    file_count = len(files)
    record_count = sum(f.record_count for f in files)
    metric_count = sum(len(f.objects) for f in files)
    parse_error_count = sum(f.parse_error_count for f in files)
    findings: list[Finding] = []
    for file in files:
        for error in file.errors:
            findings.append(
                Finding(
                    finding_id=finding_id(
                        domain="api",
                        kind=f"error-{error.code}",
                        path=file.path,
                        line_number=error.line_number,
                    ),
                    title="API KPI 解析错误",
                    severity=Severity.MEDIUM,
                    source_file=file.path,
                    evidence=error.message,
                    recommendation=inspector.recommendation,
                )
            )
        for record in file.records:
            for error in record.errors:
                findings.append(
                    Finding(
                        finding_id=finding_id(
                            domain="api",
                            kind=f"error-{error.code}",
                            path=file.path,
                            line_number=record.line_number,
                        ),
                        title="API KPI 数据行错误",
                        severity=Severity.MEDIUM,
                        source_file=file.path,
                        evidence=f"行 {record.line_number}: {error.message}",
                        recommendation=inspector.recommendation,
                    )
                )

    has_error = parse_error_count > 0
    status = RuleStatus.FAIL if has_error else RuleStatus.PASS
    summary = f"API KPI 检查完成：{file_count} 文件，{record_count} 记录，{parse_error_count} 错误"

    return make_result(
        inspector,
        status=status,
        summary=summary,
        findings=findings,
        metrics=[
            {"key": "file_count", "label": "文件数", "value": file_count, "unit": "个"},
            {"key": "record_count", "label": "记录数", "value": record_count, "unit": "条"},
            {"key": "metric_count", "label": "指标列数", "value": metric_count, "unit": "项"},
            {"key": "parse_error_count", "label": "解析错误数", "value": parse_error_count, "unit": "条"},
        ],
        metadata=build_kpi_metadata("api", files, config),
    )


inspector.run = _run
registry.register(inspector)

if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
