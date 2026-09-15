"""kpi.call（P1）：呼叫 KPI CSV 巡检（阈值 + 关联一致性 + 容量展示）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.inspectors.base import Inspector
from app.inspectors.kpi.common import (
    KpiConfigError,
    KpiRecord,
    KpiThreshold,
    build_kpi_metadata,
    finding_id,
    load_kpi_config,
    parse_all_files,
)
from app.inspectors.registry import registry
from app.models.schemas import Finding, Priority, RuleCategory, RuleStatus, Severity
from app.services.executor import RuleContext, make_result

inspector = Inspector(
    code="kpi.call",
    name="呼叫 KPI 巡检",
    category=RuleCategory.KPI,
    severity=Severity.MEDIUM,
    priority=Priority.P1,
    rule_version="1.2.0",
    description="解析呼叫 KPI CSV 文件，执行成功率/失败率阈值检查、请求关联一致性检查和容量指标展示",
    recommendation="检查阈值越限、数据自洽异常和容量趋势",
    source_patterns=[r"^kpi/(?:.*/)?kpi-call-(?:5|15|30|60)\.csv$"],
    outputs_metrics=[
        {"key": "file_count", "label": "文件数", "unit": "个"},
        {"key": "record_count", "label": "记录数", "unit": "条"},
        {"key": "parse_error_count", "label": "解析错误数", "unit": "条"},
        {"key": "consistency_error_count", "label": "自洽异常数", "unit": "条"},
        {"key": "success_rate_min", "label": "成功率最小值", "unit": "%"},
        {"key": "failure_rate_max", "label": "失败率最大值", "unit": "%"},
        {"key": "success_breach_count", "label": "成功率越限行数", "unit": "条"},
        {"key": "failure_breach_count", "label": "失败率越限行数", "unit": "条"},
        {"key": "capacity_metric_count", "label": "容量指标列数", "unit": "项"},
        {"key": "capacity_unknown_count", "label": "口径未知容量列数", "unit": "项"},
    ],
)

NA = "N/A"


def _derive_rates(record: KpiRecord, alias: dict[str, str]) -> None:
    """为单条记录计算派生成功率和失败率。"""
    derived: dict[str, float] = {}
    source_names: dict[str, str] = {}
    for source, stable in alias.items():
        source_names.setdefault(stable, source)
    attempts = record.values.get(source_names.get("call_attempts", ""), None)
    success = record.values.get(source_names.get("call_success_count", ""), None)
    failure = record.values.get(source_names.get("call_failure_count", ""), None)

    # 自洽检查
    if attempts is not None and success is not None and failure is not None:
        derived["call_count_difference"] = success + failure - attempts

    # 成功率
    explicit_sr = record.values.get(source_names.get("call_success_rate", ""), None)
    if explicit_sr is not None:
        derived["call_success_rate"] = explicit_sr
    elif attempts is not None and success is not None and attempts > 0:
        derived["call_success_rate"] = success / attempts * 100

    # 失败率
    explicit_fr = record.values.get(source_names.get("call_failure_rate", ""), None)
    if explicit_fr is not None:
        derived["call_failure_rate"] = explicit_fr
    elif attempts is not None and failure is not None and attempts > 0:
        derived["call_failure_rate"] = failure / attempts * 100

    record.derived = derived or None


def _resolve_threshold(
    threshold: KpiThreshold,
    period_minutes: int,
) -> float:
    """获取指定周期的阈值，缺失时使用 default。"""
    return threshold.periods.get(str(period_minutes), threshold.default)


def _run(ctx: RuleContext) -> object:
    if not ctx.resolved_files():
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现呼叫 KPI 文件",
            skip_reason="未匹配到 kpi-call-*.csv 文件",
        )
    try:
        config = load_kpi_config()
    except KpiConfigError as exc:
        return make_result(
            inspector,
            status=RuleStatus.ERROR,
            summary="KPI 配置加载失败",
            metadata={"error": str(exc)},
        )

    files = parse_all_files(ctx.resolved_files(), ctx.data_dir, "call", config)
    if not files:
        return make_result(
            inspector,
            status=RuleStatus.SKIP,
            summary="未发现呼叫 KPI 文件",
            skip_reason="匹配文件不属于 kpi-call-*.csv",
        )
    alias = config.aliases.get("call", {})
    sr_threshold = config.limits.get("call", {}).get("call_success_rate")
    fr_threshold = config.limits.get("call", {}).get("call_failure_rate")
    source_names = {stable: source for source, stable in alias.items()}

    file_count = len(files)
    record_count = sum(f.record_count for f in files)
    parse_error_count = sum(f.parse_error_count for f in files)
    consistency_error_count = 0
    success_breach_count = 0
    failure_breach_count = 0
    success_rates: list[float] = []
    failure_rates: list[float] = []
    capacity_metric_count = 0
    capacity_unknown_count = 0

    # 为每条记录派生比率
    for f in files:
        for r in f.records:
            _derive_rates(r, alias)
            if r.derived:
                diff = r.derived.get("call_count_difference")
                if diff is not None and diff != 0:
                    consistency_error_count += 1
                sr = r.derived.get("call_success_rate")
                fr = r.derived.get("call_failure_rate")

                # 阈值判定（仅无解析错误时）
                if not r.errors:
                    if sr is not None and sr_threshold is not None:
                        success_rates.append(sr)
                        limit = _resolve_threshold(sr_threshold, r.period_minutes)
                        if sr < limit:
                            success_breach_count += 1
                    if fr is not None and fr_threshold is not None:
                        failure_rates.append(fr)
                        limit = _resolve_threshold(fr_threshold, r.period_minutes)
                        if fr > limit:
                            failure_breach_count += 1

            if r.capacity_values:
                capacity_metric_count += len(r.capacity_values)
                capacity_unknown_count += sum(1 for c in r.capacity_values if c.status == "unknown")

    sr_min: int | float | str = min(success_rates) if success_rates else NA
    fr_max: int | float | str = max(failure_rates) if failure_rates else NA
    attempts_name = source_names.get("call_attempts", "")
    success_count_name = source_names.get("call_success_count", "")
    failure_count_name = source_names.get("call_failure_count", "")

    # 构建 findings
    findings: list[Finding] = []
    for f in files:
        for r in f.records:
            # 解析错误 finding
            for err in r.errors:
                findings.append(
                    Finding(
                        finding_id=finding_id(
                            domain="call", kind="parse-error", path=f.path, line_number=r.line_number
                        ),
                        title="KPI 数据解析错误",
                        severity=Severity.MEDIUM,
                        source_file=f.path,
                        evidence=f"行 {r.line_number}: {err.message}",
                        recommendation=inspector.recommendation,
                    )
                )
            # 自洽异常 finding
            if r.derived and r.derived.get("call_count_difference") is not None:
                diff = r.derived["call_count_difference"]
                if diff != 0:
                    findings.append(
                        Finding(
                            finding_id=finding_id(
                                domain="call", kind="consistency", path=f.path, line_number=r.line_number
                            ),
                            title="呼叫数量自洽异常",
                            severity=Severity.MEDIUM,
                            source_file=f.path,
                            evidence=(
                                f"行 {r.line_number}: 呼叫请求成功次数({r.values.get(success_count_name)}) "
                                f"+ 呼叫请求失败次数({r.values.get(failure_count_name)}) "
                                f"!= 呼叫请求次数({r.values.get(attempts_name)})，差值 {diff}"
                            ),
                            recommendation=inspector.recommendation,
                        )
                    )
            # 阈值越限 finding
            if not r.errors and r.derived:
                breaches: list[str] = []
                sr = r.derived.get("call_success_rate")
                fr = r.derived.get("call_failure_rate")
                if sr is not None and sr_threshold is not None:
                    limit = _resolve_threshold(sr_threshold, r.period_minutes)
                    if sr < limit:
                        breaches.append(f"成功率 {sr:.2f}% 低于阈值 {limit}% ({sr_threshold.direction})")
                if fr is not None and fr_threshold is not None:
                    limit = _resolve_threshold(fr_threshold, r.period_minutes)
                    if fr > limit:
                        breaches.append(f"失败率 {fr:.2f}% 高于阈值 {limit}% ({fr_threshold.direction})")
                if breaches:
                    findings.append(
                        Finding(
                            finding_id=finding_id(
                                domain="call", kind="threshold", path=f.path, line_number=r.line_number
                            ),
                            title="呼叫 KPI 阈值越限",
                            severity=Severity.MEDIUM,
                            source_file=f.path,
                            evidence=f"行 {r.line_number}: {'；'.join(breaches)}；来源: deploy/config/kpi_rules.yaml",
                            recommendation=inspector.recommendation,
                        )
                    )
            # 容量口径未知 finding
            for c in r.capacity_values or []:
                if c.status == "unknown":
                    findings.append(
                        Finding(
                            finding_id=finding_id(
                                domain="call", kind="capacity-unknown", path=f.path, line_number=r.line_number
                            ),
                            title="容量指标统计口径未知",
                            severity=Severity.LOW,
                            source_file=f.path,
                            evidence=f"行 {r.line_number}: {c.source_name} = {c.value}，统计口径未确认",
                            recommendation=inspector.recommendation,
                        )
                    )

    # 状态判定
    if parse_error_count > 0 or success_breach_count > 0 or failure_breach_count > 0:
        status = RuleStatus.FAIL
    elif consistency_error_count > 0:
        status = RuleStatus.WARN
    else:
        status = RuleStatus.PASS

    summary = (
        f"呼叫 KPI 检查完成：{file_count} 文件，{record_count} 记录，"
        f"{parse_error_count} 解析错误，{consistency_error_count} 自洽异常，"
        f"{success_breach_count} 成功率越限，{failure_breach_count} 失败率越限"
    )

    return make_result(
        inspector,
        status=status,
        summary=summary,
        findings=findings,
        metrics=[
            {"key": "file_count", "label": "文件数", "value": file_count, "unit": "个"},
            {"key": "record_count", "label": "记录数", "value": record_count, "unit": "条"},
            {"key": "parse_error_count", "label": "解析错误数", "value": parse_error_count, "unit": "条"},
            {"key": "consistency_error_count", "label": "自洽异常数", "value": consistency_error_count, "unit": "条"},
            {"key": "success_rate_min", "label": "成功率最小值", "value": sr_min, "unit": "%"},
            {"key": "failure_rate_max", "label": "失败率最大值", "value": fr_max, "unit": "%"},
            {"key": "success_breach_count", "label": "成功率越限行数", "value": success_breach_count, "unit": "条"},
            {"key": "failure_breach_count", "label": "失败率越限行数", "value": failure_breach_count, "unit": "条"},
            {"key": "capacity_metric_count", "label": "容量指标列数", "value": capacity_metric_count, "unit": "项"},
            {
                "key": "capacity_unknown_count",
                "label": "口径未知容量列数",
                "value": capacity_unknown_count,
                "unit": "项",
            },
        ],
        metadata=build_kpi_metadata("call", files, config),
    )


inspector.run = _run
registry.register(inspector)

if __name__ == "__main__":
    from app.cli import run_single_rule

    run_single_rule(inspector.code)
