"""log.error_density（P1）：日志错误密度检查。"""

import sys
from pathlib import Path

# 支持 PyCharm 直接运行单规则文件
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import json

from app.inspectors.base import Inspector
from app.inspectors.log.common import log_processed_files
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

MAX_ERRORS = 100

inspector = Inspector(
    code="log.error_density",
    name="日志错误密度",
    category=RuleCategory.LOG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.1.0",
    description="统计日志中 ERROR/FATAL/CRITICAL 条数，超过阈值告警",
    recommendation="检查异常来源模块，必要时查看完整日志上下文",
    inputs=["log.filter.artifacts.filtered_logs"],
    outputs_metrics=[{"key": "error_count", "label": "错误条数", "unit": "条"}],
    params=[{"key": "max", "label": "错误条数阈值", "default": str(MAX_ERRORS)}],
)


def _run(ctx: RuleContext) -> object:
    artifact = ctx.inputs.get("log.filter.artifacts.filtered_logs")
    if artifact is None:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="依赖过滤产物缺失",
            skip_reason="依赖产物 log.filter.artifacts.filtered_logs 缺失",
        )
    root = Path(artifact.path)
    index_path = root / "index.json"
    if not index_path.exists():
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="过滤产物缺少索引",
            skip_reason="过滤产物缺少 index.json",
        )
    processed_files_list = log_processed_files(ctx, index_path, inspector.code)

    index = json.loads(index_path.read_text(encoding="utf-8"))
    error_count = int(index.get("error_count", 0))

    if error_count > MAX_ERRORS * 2:
        status, summary = RuleStatus.FAIL, f"错误日志密度严重超限：{error_count} 条"
    elif error_count > MAX_ERRORS:
        status, summary = RuleStatus.WARN, f"错误日志密度超限：{error_count} 条"
    else:
        status, summary = RuleStatus.PASS, f"错误日志密度正常：{error_count} 条"

    findings = []
    if status != RuleStatus.PASS:
        evidence = ""
        filtered = root / "filtered.log"
        if filtered.exists():
            evidence = "\n".join(filtered.read_text(encoding="utf-8", errors="replace").splitlines()[:3])[:2048]
        findings = [
            Finding(
                finding_id=f"{inspector.code}-f001",
                title=summary,
                severity=Severity.MEDIUM,
                source_file=index.get("files", [""])[0] if index.get("files") else None,
                evidence=evidence or None,
                recommendation=inspector.recommendation,
            )
        ]
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
