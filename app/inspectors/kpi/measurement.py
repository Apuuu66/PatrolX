"""kpi.measurement_units（P1）：基于测量单元的 KPI 可读性检查。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.registry import registry
from app.models.schemas import Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result
from app.services.kpi_measurement_units import inspect_measurement_files

inspector = Inspector(
    code="kpi.measurement_units",
    name="KPI 测量单元检查",
    category=RuleCategory.KPI,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="3.3.0",
    description="自动入库测量单元指标，检查文件归属、数值可读性、业务阈值与任务内趋势",
    recommendation="处理未匹配文件与跨单元冲突，配置阈值，并修复空值、解析失败或趋势恶化的指标",
    source_refs=["kpi_all"],
    outputs_metrics=[
        {"key": "matched_files", "label": "匹配文件数", "unit": "个"},
        {"key": "unmatched_files", "label": "未匹配文件数", "unit": "个"},
        {"key": "skipped_files", "label": "周期跳过文件数", "unit": "个"},
        {"key": "measurement_units", "label": "测量单元数", "unit": "个"},
    ],
)


def _run(ctx: RuleContext) -> object:
    files = [
        (relative.as_posix(), absolute) for relative, absolute in zip(ctx.files, ctx.resolved_files(), strict=True)
    ]
    result = inspect_measurement_files(ctx.task_id, files)
    unit_results = result["measurement_units"]
    unmatched_count = len(result["unmatched_files"])
    skipped_count = len(result.get("skipped_files", []))
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现 KPI 测量单元 CSV",
            skip_reason="未发现 KPI 测量单元 CSV",
        )
    if not unit_results:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现可巡检的测量单元",
            skip_reason="KPI CSV 未匹配到任何已启用测量单元",
            metadata={
                "files": [item["filename"] for item in result["files"]],
                "unmatched_files": [item["filename"] for item in result["unmatched_files"]],
                "skipped_files": [item["filename"] for item in result.get("skipped_files", [])],
            },
        )
    if all(unit["status"] == "skip" for unit in unit_results):
        unconfirmed_count = sum(1 for unit in unit_results if unit["status"] == "skip")
        unconfirmed_ratio = f"{unconfirmed_count}/{len(unit_results)}"
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary=f"测量单元尚未确认指标绑定：{unconfirmed_ratio}",
            skip_reason=f"{unconfirmed_ratio} 个测量单元未确认指标绑定",
            metadata={"measurement_units": unit_results},
        )

    overview = result["kpi_overview"]
    failed = sum(1 for unit in unit_results if unit["status"] in {"fail", "error"})
    if failed:
        status = RuleStatus.FAIL
        summary = f"KPI 测量单元检查失败：{failed}/{len(unit_results)} 个测量单元异常"
    elif unmatched_count:
        status = RuleStatus.WARN
        summary = f"KPI 测量单元检查完成：{unmatched_count} 个文件未归属测量单元"
    else:
        status = RuleStatus.PASS
        summary = f"KPI 测量单元检查通过：{len(unit_results)} 个测量单元"
    diagnostic_parts = [
        f"阈值失败 {overview['business_fail_count']}",
        f"阈值预警 {overview['business_warn_count']}",
        f"数据异常 {overview['data_error_count']}",
        f"趋势恶化 {overview['trend_worsened_count']}",
    ]
    summary = f"{summary}；{'，'.join(diagnostic_parts)}"

    metrics = [
        {
            "key": "matched_files",
            "label": "匹配文件数",
            "value": sum(item["status"] == "matched" for item in result["files"]),
            "unit": "个",
        },
        {"key": "unmatched_files", "label": "未匹配文件数", "value": unmatched_count, "unit": "个"},
        {"key": "skipped_files", "label": "周期跳过文件数", "value": skipped_count, "unit": "个"},
        {"key": "measurement_units", "label": "测量单元数", "value": len(unit_results), "unit": "个"},
    ]
    metadata = {
        "measurement_units": unit_results,
        "files": [],
        "unmatched_files": [],
        "skipped_files": [],
    }

    # 保留展示字段，但结果契约中不携带任务现场绝对路径。
    for file_result in result["files"]:
        metadata["files"].append(file_result["filename"])
    for file_result in result["unmatched_files"]:
        metadata["unmatched_files"].append(file_result["filename"])
    for file_result in result.get("skipped_files", []):
        metadata["skipped_files"].append(file_result["filename"])

    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=metrics,
        metadata=metadata,
    )


inspector.run = _run
registry.register(inspector)


if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
