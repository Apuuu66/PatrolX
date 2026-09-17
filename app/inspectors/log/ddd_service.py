"""log.ddd_service（P1）：DDD 服务网络连通性巡检。"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.log.common import log_service_processed_files, service_records
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

SERVICE_NAME = "DDD"
PING_FAILURE_RE = re.compile(r"\bping\b.*\b(?:fail(?:ed|ure)?|error)\b|ping\s*失败", re.IGNORECASE)

inspector = Inspector(
    code="log.ddd_service",
    name="DDD 服务 ping 巡检",
    category=RuleCategory.LOG,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="检查 DDD 日志中是否存在 ping 失败",
    recommendation="检查失败节点网络连通性、目标地址可达性和防火墙配置",
    source_refs=["ddd_service_logs"],
    outputs_metrics=[
        {"key": "ping_failure_count", "label": "ping 失败条数", "unit": "条"},
        {"key": "affected_node_count", "label": "受影响节点数", "unit": "个"},
    ],
)


def _run(ctx: RuleContext) -> object:
    """检查 DDD 日志中的 ping 失败记录。"""
    records, source_files = service_records(ctx, SERVICE_NAME)
    if not records:
        skip_reason = "source_patterns 未匹配到文件" if not ctx.files else "未发现 DDD 日志"
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 DDD 日志" if ctx.files else "未发现匹配源文件",
            skip_reason=skip_reason,
        )

    processed_files = log_service_processed_files(ctx, inspector.code, source_files)
    ping_records = [record for record in records if PING_FAILURE_RE.search(str(record.get("message", "")))]
    node_records: dict[str, list[dict]] = {}
    for record in ping_records:
        node = str(record.get("node") or "(unknown)")
        node_records.setdefault(node, []).append(record)

    findings = [
        Finding(
            finding_id=f"{inspector.code}-ping-{node}",
            title="DDD 节点 ping 失败",
            severity=Severity.HIGH,
            source_file=node_records[node][0]["source_file"],
            evidence=node_records[node][0]["message"],
            details=f"节点 {node} 命中 {len(node_records[node])} 条 ping 失败日志",
            recommendation=inspector.recommendation,
        )
        for node in sorted(node_records)
    ]

    return make_result(
        inspector,
        status=RuleStatus.FAIL if ping_records else RuleStatus.PASS,
        summary="DDD 存在 ping 失败" if ping_records else "DDD 未发现 ping 失败",
        metrics=[
            {"key": "ping_failure_count", "label": "ping 失败条数", "value": len(ping_records), "unit": "条"},
            {"key": "affected_node_count", "label": "受影响节点数", "value": len(node_records), "unit": "个"},
        ],
        findings=findings,
        metadata={"processed_files": processed_files},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
