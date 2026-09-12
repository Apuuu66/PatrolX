"""log.fault_pattern（P1）：识别日志中的已知业务故障模式。"""

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

PATTERNS = [
    {
        "key": "db_connection_pool_exhausted",
        "name": "数据库连接池耗尽",
        "pattern": re.compile(r"db connection pool exhausted", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查数据库连接池配置、连接泄漏和数据库负载",
    },
    {
        "key": "auth_failure",
        "name": "认证失败",
        "pattern": re.compile(r"auth failure|authentication failed", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查认证服务、账号状态、证书/密码和限流策略",
    },
    {
        "key": "sctp_link_down",
        "name": "SCTP 链路中断",
        "pattern": re.compile(r"sctp link down", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查 SCTP 对端状态、网络连通性和链路配置",
    },
    {
        "key": "sctp_reconnect_failed",
        "name": "SCTP 重连失败",
        "pattern": re.compile(r"sctp reconnect failed", re.I),
        "severity": Severity.HIGH,
        "recommendation": "确认对端是否恢复，检查网络隔离、地址端口和重连参数",
    },
    {
        "key": "dependency_timeout",
        "name": "依赖连接超时",
        "pattern": re.compile(r"connection timeout|connect timed out|read timed out", re.I),
        "severity": Severity.MEDIUM,
        "recommendation": "检查下游服务时延、网络抖动、超时和重试配置",
    },
    {
        "key": "out_of_memory",
        "name": "内存耗尽",
        "pattern": re.compile(r"OutOfMemoryError|out of memory", re.I),
        "severity": Severity.HIGH,
        "recommendation": "检查内存水位、堆配置、业务内存增长和泄漏迹象",
    },
]

inspector = Inspector(
    code="log.fault_pattern",
    name="日志故障模式识别",
    category=RuleCategory.LOG,
    severity=Severity.HIGH,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="将日志消息匹配到数据库连接池、认证失败、SCTP 链路、依赖超时和内存耗尽等已知故障模式",
    recommendation="按命中的故障模式查看证据、受影响服务，并执行对应处置建议",
    source_patterns=[r"^logs/.*\.(log|log\.gz)$"],
    outputs_metrics=[
        {"key": "matched_pattern_count", "label": "命中故障模式数", "unit": "类"},
        {"key": "affected_service_count", "label": "受影响服务数", "unit": "个"},
        {"key": "max_pattern_hit_count", "label": "单模式最大命中数", "unit": "条"},
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

    groups: dict[tuple[str, str], dict] = {}
    pattern_counts: Counter[str] = Counter()
    service_counts: Counter[str] = Counter()

    for record in records:
        for pattern in PATTERNS:
            if not pattern["pattern"].search(record["message"]):
                continue
            key = (record["service"], pattern["key"])
            pattern_counts[pattern["key"]] += 1
            service_counts[record["service"]] += 1
            group = groups.setdefault(key, {"pattern": pattern, "records": []})
            if len(group["records"]) < 5:
                group["records"].append(record)

    high_pattern_count = sum(
        1 for pattern in PATTERNS if pattern["severity"] == Severity.HIGH and pattern_counts[pattern["key"]] > 0
    )
    max_count = max(pattern_counts.values(), default=0)

    if high_pattern_count >= 2 or max_count > 10:
        status = RuleStatus.FAIL
    elif pattern_counts:
        status = RuleStatus.WARN
    else:
        status = RuleStatus.PASS

    findings = []
    for (service, pattern_key), group in sorted(groups.items()):
        pattern = group["pattern"]
        first = group["records"][0]
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-{service}-{pattern_key}".lower(),
                title=f"{service} {pattern['name']}",
                severity=pattern["severity"],
                source_file=first["source_file"],
                evidence="\n".join(record["message"] for record in group["records"])[:4096],
                recommendation=pattern["recommendation"],
            )
        )

    summary = (
        "未命中已知故障模式"
        if not pattern_counts
        else f"命中 {len(pattern_counts)} 类故障模式，影响 {len(service_counts)} 个服务"
    )
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "matched_pattern_count", "label": "命中故障模式数", "value": len(pattern_counts), "unit": "类"},
            {"key": "affected_service_count", "label": "受影响服务数", "value": len(service_counts), "unit": "个"},
            {"key": "max_pattern_hit_count", "label": "单模式最大命中数", "value": max_count, "unit": "条"},
        ],
        findings=findings,
        metadata={
            "pattern_counts": dict(pattern_counts),
            "service_counts": dict(service_counts),
            "high_pattern_count": high_pattern_count,
            "processed_files": processed_files_list,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
