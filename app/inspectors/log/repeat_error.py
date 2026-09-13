"""log.repeat_error（P1）：识别服务日志中的高频重复错误。"""

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

WARN_REPEAT = 5
FAIL_REPEAT = 20
NORMALIZE_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\d+",
    re.I,
)

inspector = Inspector(
    code="log.repeat_error",
    name="高频重复错误识别",
    category=RuleCategory.LOG,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="4.0.0",
    description="按服务归一化错误消息，识别连接池耗尽、认证失败、重试风暴等重复错误",
    recommendation="检查重复错误的触发频率、外部依赖可用性、重试与限流配置",
    source_patterns=[r"^logs/.*\.log$"],
    outputs_metrics=[
        {"key": "repeated_pattern_count", "label": "重复错误模式数", "unit": "个"},
        {"key": "max_repeat_count", "label": "最大重复次数", "unit": "次"},
    ],
)


def _normalized_message(message: str) -> str:
    return NORMALIZE_RE.sub("<var>", message).strip().lower()


def _run(ctx: RuleContext) -> object:
    records = read_records(ctx)
    if not records:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现匹配日志",
            skip_reason="source_patterns 未发现可解析日志",
        )

    counts: Counter[tuple[str, str]] = Counter()
    processed_files_list = log_processed_files(ctx, inspector.code, sorted({r["source_file"] for r in records}))

    groups: dict[tuple[str, str], dict] = {}

    for record in records:
        if record["level"] == "STACK":
            continue
        normalized = _normalized_message(record["message"])
        key = (record["service"], normalized)
        counts[key] += 1
        group = groups.setdefault(key, {"first": record, "evidence": []})
        if len(group["evidence"]) < 5:
            group["evidence"].append(record["message"])

    repeated = {key: count for key, count in counts.items() if count >= WARN_REPEAT}
    max_count = max(repeated.values(), default=0)
    status = RuleStatus.FAIL if max_count > FAIL_REPEAT else RuleStatus.WARN if repeated else RuleStatus.PASS

    findings = []
    for (service, normalized), count in sorted(repeated.items(), key=lambda item: (-item[1], item[0])):
        group = groups[(service, normalized)]
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-{service}-{len(findings) + 1:03d}".lower(),
                title=f"{service} 重复错误：{normalized[:120]}",
                severity=Severity.HIGH if count > FAIL_REPEAT else Severity.MEDIUM,
                source_file=group["first"]["source_file"],
                evidence="\n".join(group["evidence"])[:4096],
                recommendation=inspector.recommendation,
            )
        )

    summary = f"发现 {len(repeated)} 个高频重复错误，最大重复 {max_count} 次" if repeated else "未发现高频重复错误"
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "repeated_pattern_count", "label": "重复错误模式数", "value": len(repeated), "unit": "个"},
            {"key": "max_repeat_count", "label": "最大重复次数", "value": max_count, "unit": "次"},
        ],
        findings=findings,
        metadata={
            "thresholds": {"warn": WARN_REPEAT, "fail": FAIL_REPEAT},
            "top_patterns": {
                f"{service}:{normalized}": count
                for (service, normalized), count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
                if count >= WARN_REPEAT
            },
            "processed_files": processed_files_list,
        },
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
