"""kpi.threshold（P1）：KPI 关键指标阈值检查。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import csv
import json

from app.inspectors.base import Inspector, PrepareSpec
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result
from app.services.prepare import prepared_dir

THRESHOLDS = {
    "call_success_rate": (98.0, "呼叫成功率", "%"),
    "attach_success_rate": (97.0, "附着成功率", "%"),
    "setup_success_rate": (97.0, "建立成功率", "%"),
}

inspector = Inspector(
    code="kpi.threshold",
    name="KPI 阈值检查",
    category=RuleCategory.KPI,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.1.0",
    description="检查关键 KPI（呼叫/附着/建立成功率）是否低于阈值",
    recommendation="低于阈值时核查对应网元与链路质量",
    source_patterns=[r"^kpi/.*$"],
    outputs_metrics=[
        {"key": "checked", "label": "检查指标数", "unit": "项"},
        {"key": "below", "label": "低于阈值数", "unit": "项"},
    ],
    params=[{"key": "thresholds", "label": "阈值配置", "default": "见代码内定义"}],
)


def _read_kpi(files: list[Path]) -> dict[str, float]:
    values: dict[str, float] = {}
    for path in files:
        if path.suffix.lower() not in {".csv", ".txt"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.suffix.lower() == ".csv":
            rows = list(csv.reader(text.splitlines()))
            if not rows:
                continue
            header = rows[0]
            idx = {h.strip().lower(): i for i, h in enumerate(header)}
            for row in rows[1:]:
                if len(row) < 2:
                    continue
                name = row[idx.get("metric", 0)].strip()
                try:
                    values[name] = float(row[idx.get("value", 1)].strip())
                except (ValueError, IndexError):
                    continue
        else:
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        values[parts[0]] = float(parts[1])
                    except ValueError:
                        continue
    return values


def _prepare(ctx: RuleContext) -> object:
    """解析原始 KPI 文件并写入规则私有 prepared 数据。"""
    values = _read_kpi(sorted(ctx.resolved_files()))
    path = prepared_dir(ctx, inspector.code) / "kpi_values.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return None


def _run(ctx: RuleContext) -> object:
    path = prepared_dir(ctx, inspector.code) / "kpi_values.json"
    if not path.exists():
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="预处理数据未就绪",
            skip_reason="KPI prepared 数据不存在",
        )
    values = {key: float(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}
    if not values:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 KPI 类文件",
            skip_reason="未发现 KPI 类文件",
        )
    findings: list[Finding] = []
    below = 0
    for key, (limit, label, unit) in THRESHOLDS.items():
        value = values.get(key)
        if value is None or value >= limit:
            continue
        below += 1
        findings.append(
            Finding(
                finding_id=f"{inspector.code}-{key}",
                title=f"{label}低于阈值",
                severity=Severity.MEDIUM,
                source_file=", ".join(ctx_file.as_posix() for ctx_file in ctx.files),
                evidence=f"{key}={value}{unit}，阈值下限 {limit}{unit}",
                recommendation=inspector.recommendation,
            )
        )
    status = RuleStatus.FAIL if below >= 2 else RuleStatus.WARN if below else RuleStatus.PASS
    summary = (
        f"KPI 检查完成：{len(values)} 项，{below} 项低于阈值" if below else f"KPI 检查完成：{len(values)} 项均正常"
    )
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "checked", "label": "检查指标数", "value": len(values), "unit": "项"},
            {"key": "below", "label": "低于阈值数", "value": below, "unit": "项"},
        ],
        findings=findings,
    )


inspector.run = _run
inspector.prepare = PrepareSpec(code="prepare.kpi.threshold", owner_code=inspector.code, run=_prepare)
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
