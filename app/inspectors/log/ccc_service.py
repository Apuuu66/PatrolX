"""log.ccc_service（P1）：CCC 服务节点启动状态巡检。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.log.common import log_service_processed_files, service_records
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

SERVICE_NAME = "CCC"
START_SUCCESS_TEXT = "start success"

inspector = Inspector(
    code="log.ccc_service",
    name="CCC 服务启动巡检",
    category=RuleCategory.LOG,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="检查 CCC 每个节点的启动是否成功",
    recommendation="检查未出现 start success 的节点启动流程和依赖状态",
    source_refs=["ccc_service_logs"],
    outputs_metrics=[
        {"key": "node_count", "label": "节点数", "unit": "个"},
        {"key": "startup_success_node_count", "label": "启动成功节点数", "unit": "个"},
        {"key": "startup_failure_node_count", "label": "启动异常节点数", "unit": "个"},
    ],
)


def _run(ctx: RuleContext) -> object:
    """按节点聚合 CCC 日志，并检查每个节点是否出现启动成功标记。"""
    records, source_files = service_records(ctx, SERVICE_NAME)
    if not records:
        skip_reason = "source_patterns 未匹配到文件" if not ctx.files else "未发现 CCC 日志"
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 CCC 日志" if ctx.files else "未发现匹配源文件",
            skip_reason=skip_reason,
        )

    processed_files = log_service_processed_files(ctx, inspector.code, source_files)
    node_records: dict[str, list[dict]] = {}
    for record in records:
        node = str(record.get("node") or "(unknown)")
        node_records.setdefault(node, []).append(record)

    success_nodes = {
        node
        for node, node_items in node_records.items()
        if any(START_SUCCESS_TEXT in str(item.get("message", "")).lower() for item in node_items)
    }
    failure_nodes = sorted(set(node_records) - success_nodes)

    findings = [
        Finding(
            finding_id=f"{inspector.code}-startup-{node}",
            title="CCC 节点启动异常",
            severity=Severity.HIGH,
            source_file=node_records[node][0]["source_file"],
            evidence=node_records[node][0]["message"],
            details=f"节点 {node} 未出现 {START_SUCCESS_TEXT}",
            recommendation=inspector.recommendation,
        )
        for node in failure_nodes
    ]

    return make_result(
        inspector,
        status=RuleStatus.FAIL if failure_nodes else RuleStatus.PASS,
        summary="CCC 存在节点启动异常" if failure_nodes else "CCC 所有节点启动正常",
        metrics=[
            {"key": "node_count", "label": "节点数", "value": len(node_records), "unit": "个"},
            {"key": "startup_success_node_count", "label": "启动成功节点数", "value": len(success_nodes), "unit": "个"},
            {"key": "startup_failure_node_count", "label": "启动异常节点数", "value": len(failure_nodes), "unit": "个"},
        ],
        findings=findings,
        metadata={"processed_files": processed_files},
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
