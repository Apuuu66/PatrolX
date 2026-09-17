"""traffic.stat（P1）：话务统计与接通率检查。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

ANSWER_RATE_MIN = 95.0

inspector = Inspector(
    code="traffic.stat",
    name="话务统计检查",
    category=RuleCategory.TRAFFIC,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="统计总话务量与应答率，应答率低于阈值告警",
    recommendation="应答率偏低时核查交换资源与拥塞配置",
    source_refs=["traffic_all"],
    outputs_metrics=[
        {"key": "total_calls", "label": "总话务量", "unit": "次"},
        {"key": "answer_rate", "label": "应答率", "unit": "%"},
    ],
    params=[{"key": "answer_rate_min", "label": "应答率下限", "default": "95"}],
)


def _read_traffic(files: list[Path]) -> dict[str, float]:
    values: dict[str, float] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.replace("=", " ").split()
            if len(parts) >= 2:
                try:
                    values[parts[0]] = float(parts[1])
                except ValueError:
                    continue
    return values


def _run(ctx: RuleContext) -> object:
    values = _read_traffic(sorted(ctx.resolved_files()))
    if not values:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现话统类文件",
            skip_reason="未发现话统类文件",
        )
    total = values.get("total_calls", 0)
    rate = values.get("answer_rate")
    findings: list[Finding] = []
    if rate is not None and rate < ANSWER_RATE_MIN:
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-answer_rate",
                title="应答率低于阈值",
                severity=Severity.MEDIUM,
                source_file=str(ctx.files[0]),
                evidence=f"answer_rate={rate}%，阈值下限 {ANSWER_RATE_MIN}%",
                recommendation=inspector.recommendation,
            )
        )
    status = RuleStatus.WARN if findings else RuleStatus.PASS
    summary = (
        f"话统检查完成：总话务 {total:.0f} 次，应答率 {rate}%"
        if rate is not None
        else f"话统检查完成：总话务 {total:.0f} 次（无应答率数据）"
    )
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "total_calls", "label": "总话务量", "value": int(total), "unit": "次"},
            {"key": "answer_rate", "label": "应答率", "value": rate if rate is not None else 0, "unit": "%"},
        ],
        findings=findings,
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
