"""resource.check（P1）：容器 CPU/内存水位检查。"""

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

CPU_WARN_PERCENT = 85.0
MEM_WARN_PERCENT = 90.0
REQUIRED_COLUMNS = {"测量开始时间", "测量结束时间", "周期(分钟)"}


inspector = Inspector(
    code="resource.check",
    name="资源水位检查",
    category=RuleCategory.RESOURCE,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="2.0.0",
    description="按列名识别容器 CPU/内存指标",
    recommendation="高水位资源需扩容或排查泄漏",
    source_refs=["resource_all"],
    outputs_metrics=[
        {"key": "high_cpu", "label": "CPU 高水位实例", "unit": "个"},
        {"key": "high_mem", "label": "内存高水位实例", "unit": "个"},
    ],
    params=[
        {"key": "cpu_warn_percent", "label": "CPU 告警水位(%)", "default": "85"},
        {"key": "mem_warn_percent", "label": "内存告警水位(%)", "default": "90"},
    ],
)


def _metric_kind(name: str) -> str:
    """根据列名语义识别 CPU/内存百分比指标，未知列不参与判定。"""
    normalized = name.strip().lower()
    is_rate = any(token in normalized for token in ("使用率", "util", "percent", "%"))
    if not is_rate:
        return ""
    if "cpu" in normalized or "处理器" in name:
        return "cpu"
    if "内存" in name or "memory" in normalized or "mem" in normalized:
        return "mem"
    return ""


def _identity(row: dict[str, str], fallback: str) -> str:
    service = (row.get("服务名") or "").strip()
    instance = (row.get("实例") or "").strip()
    if service and instance and service != instance:
        return f"{service}/{instance}"
    return service or instance or fallback


def _parse_csv(source_file: str, text: str) -> tuple[list[Finding], set[str], set[str]]:
    findings: list[Finding] = []
    high_cpu: set[str] = set()
    high_mem: set[str] = set()
    rows = list(csv.reader(io.StringIO(text)))
    header_index = next(
        (index for index, cells in enumerate(rows) if REQUIRED_COLUMNS.issubset({cell.strip() for cell in cells})),
        None,
    )
    if header_index is None:
        return findings, high_cpu, high_mem

    headers = [cell.strip() for cell in rows[header_index]]
    metric_headers = [(index, _metric_kind(name)) for index, name in enumerate(headers) if _metric_kind(name)]
    for row in rows[header_index + 1 :]:
        if len(row) < len(headers):
            continue
        values = dict(zip(headers, row, strict=False))
        identity = _identity(values, source_file)
        for kind, threshold in (("cpu", CPU_WARN_PERCENT), ("mem", MEM_WARN_PERCENT)):
            matched = [row[index] for index, metric_kind in metric_headers if metric_kind == kind]
            observed = [float(value) for value in matched if value.strip()]
            if not observed or max(observed) <= threshold:
                continue
            peak = max(observed)
            target = high_cpu if kind == "cpu" else high_mem
            target.add(identity)
            label = "CPU" if kind == "cpu" else "内存"
            findings.append(
                Finding(
                    finding_id=f"{inspector.code}-{kind}-{identity}",
                    title=f"{identity} {label}使用率偏高",
                    severity=Severity.MEDIUM,
                    source_file=source_file,
                    evidence=f"{label}使用率={peak:.2f}%，告警水位 {threshold:g}%",
                    recommendation=inspector.recommendation,
                )
            )
    return findings, high_cpu, high_mem


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
    high_cpu: set[str] = set()
    high_mem: set[str] = set()
    for path in files:
        source_file = path.relative_to(ctx.data_dir).as_posix() if path.is_relative_to(ctx.data_dir) else path.name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ctx.log(
                "warning",
                "资源文件读取失败",
                task_id=ctx.task_id,
                rule_code=inspector.code,
                source_file=source_file,
            )
            continue
        file_findings, file_cpu, file_mem = _parse_csv(source_file, text)
        findings.extend(file_findings)
        high_cpu.update(file_cpu)
        high_mem.update(file_mem)

    if not high_cpu and not high_mem and not findings:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现可解析的资源指标",
            skip_reason="未发现可解析的资源指标",
        )

    status = RuleStatus.WARN if findings else RuleStatus.PASS
    summary = f"资源检查完成：CPU 高水位 {len(high_cpu)} 个，内存高水位 {len(high_mem)} 个"
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "high_cpu", "label": "CPU 高水位实例", "value": len(high_cpu), "unit": "个"},
            {"key": "high_mem", "label": "内存高水位实例", "value": len(high_mem), "unit": "个"},
        ],
        findings=findings,
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
