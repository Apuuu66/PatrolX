"""resource.check（P1）：Pod CPU/内存水位与业务资源检查。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

CPU_WARN_M = 800  # 800m
MEM_WARN_MB = 1024  # 1Gi

inspector = Inspector(
    code="resource.check",
    name="资源水位检查",
    category=RuleCategory.RESOURCE,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.0.0",
    description="检查 Pod CPU/内存水位与关键业务资源（控制块/定时器）使用情况",
    recommendation="高水位资源需扩容或排查泄漏",
    source_patterns=[r"^resource/.*$"],
    outputs_metrics=[
        {"key": "high_cpu", "label": "CPU 高水位实例", "unit": "个"},
        {"key": "high_mem", "label": "内存高水位实例", "unit": "个"},
    ],
    params=[
        {"key": "cpu_warn_m", "label": "CPU 告警水位(m)", "default": "800"},
        {"key": "mem_warn_mb", "label": "内存告警水位(MiB)", "default": "1024"},
    ],
)


def _parse_mem(value: str) -> int:
    value = value.strip().lower()
    multiplier = 1
    if value.endswith("gi"):
        multiplier, value = 1024, value[:-2]
    elif value.endswith("mi"):
        multiplier, value = 1, value[:-2]
    try:
        return int(float(value) * multiplier)
    except ValueError:
        return 0


def _parse_cpu(value: str) -> int:
    value = value.strip().lower()
    if value.endswith("m"):
        try:
            return int(value[:-1])
        except ValueError:
            return 0
    try:
        return int(float(value) * 1000)
    except ValueError:
        return 0


def _run(ctx: RuleContext) -> object:
    files = sorted(ctx.resolved_files())
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现资源类文件",
            skip_reason="未发现资源类文件",
        )
    findings: list[Finding] = []
    high_cpu = 0
    high_mem = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            name, cpu_m = parts[0], _parse_cpu(parts[2])
            mem_mb = _parse_mem(parts[4]) if len(parts) >= 5 else 0
            if cpu_m >= CPU_WARN_M:
                high_cpu += 1
                findings.append(
                    Finding(
                        finding_id=f"{inspector.code}-cpu-{name}",
                        title=f"{name} CPU 水位偏高",
                        severity=Severity.MEDIUM,
                        source_file=path.name,
                        evidence=f"cpu={cpu_m}m，告警水位 {CPU_WARN_M}m",
                        recommendation=inspector.recommendation,
                    )
                )
            if mem_mb >= MEM_WARN_MB:
                high_mem += 1
                findings.append(
                    Finding(
                        finding_id=f"{inspector.code}-mem-{name}",
                        title=f"{name} 内存水位偏高",
                        severity=Severity.MEDIUM,
                        source_file=path.name,
                        evidence=f"mem={mem_mb}MiB，告警水位 {MEM_WARN_MB}MiB",
                        recommendation=inspector.recommendation,
                    )
                )
    status = RuleStatus.WARN if findings else RuleStatus.PASS
    summary = f"资源检查完成：CPU 高水位 {high_cpu} 个，内存高水位 {high_mem} 个"
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "high_cpu", "label": "CPU 高水位实例", "value": high_cpu, "unit": "个"},
            {"key": "high_mem", "label": "内存高水位实例", "value": high_mem, "unit": "个"},
        ],
        findings=findings,
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
