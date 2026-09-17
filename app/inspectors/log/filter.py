"""log.filter（P0）：扫描匹配日志并输出规范化过滤统计。"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.log.common import LEVELS, log_processed_files, read_records
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

MIN_LEVEL = 30  # 默认保留 WARN 及以上

inspector = Inspector(
    code="log.filter",
    name="日志过滤",
    category=RuleCategory.LOG,
    severity=Severity.LOW,
    priority=Priority.P0,
    rule_version="4.0.0",
    description="扫描 source_patterns 匹配的日志，统计服务、节点、保留级别与错误数量",
    recommendation="无日志类文件时跳过分析类规则",
    source_refs=["logs_all"],
    outputs_metrics=[
        {"key": "kept_lines", "label": "保留日志行", "unit": "行"},
        {"key": "total_lines", "label": "扫描日志行", "unit": "行"},
    ],
)


def _run(ctx: RuleContext) -> object:
    try:
        records = read_records(ctx)
    except (OSError, Exception) as exc:  # gzip/OSError 统一记录，不中断任务
        ctx.log("error", "日志文件读取失败", error=str(exc))
        return make_result(
            inspector,
            status=RuleStatus.ERROR,
            summary="日志文件读取失败",
            metadata={"error": str(exc)},
        )
    if not records:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现日志类文件",
            skip_reason="source_patterns 未发现可解析日志",
        )
    filtered = [
        record
        for record in records
        if record["level"] == "STACK" or (record["level"] in LEVELS and LEVELS[record["level"]] >= MIN_LEVEL)
    ]
    total_lines = len(records)
    kept_lines = len(filtered)
    counts = Counter(record["level"] for record in filtered)
    services = sorted({record["service"] for record in records})
    processed = sorted({record["source_file"] for record in records})
    log_processed_files(ctx, inspector.code, processed)
    ctx.log(
        "info",
        "日志过滤完成",
        files=processed,
        file_count=len(processed),
        kept=kept_lines,
        total=total_lines,
    )
    return make_result(
        inspector,
        status=RuleStatus.PASS,
        summary=f"日志过滤完成：{len(services)} 个服务，{len(processed)} 个文件，保留 {kept_lines}/{total_lines} 行",
        metrics=[
            {"key": "kept_lines", "label": "保留日志行", "value": kept_lines, "unit": "行"},
            {"key": "total_lines", "label": "扫描日志行", "value": total_lines, "unit": "行"},
        ],
        metadata={
            "files": len(processed),
            "service_count": len(services),
            "processed_files": processed,
            "levels": dict(counts),
            "error_count": counts["ERROR"] + counts["FATAL"] + counts["CRITICAL"],
            "warn_count": counts["WARN"] + counts["WARNING"],
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
