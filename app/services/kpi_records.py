"""KPI 原始记录查询投影服务。

历史 KPI 结果（metadata.version=1）不迁移，也不提供记录查询；
只有目录化结果（version >= 2）按请求投影为分页记录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.inspectors.kpi.catalog import normalize_metric_name
from app.models.schemas import (
    KpiDisplayStatus,
    KpiRecordItem,
    KpiRecordPage,
    RuleResult,
)
from app.services.store import load_rule_result


def _stable_record_values(
    source_values: dict[str, float],
    catalog: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """把真实列名中的“指标名 + 单位”按最长前缀归一到稳定 key。"""
    values: dict[str, float] = {}
    for source_name, value in source_values.items():
        normalized = normalize_metric_name(source_name)
        best_key: str | None = None
        best_length = 0
        for key, definition in catalog.items():
            for name in (definition.get("key"), definition.get("name_zh"), definition.get("name_en")):
                candidate = normalize_metric_name(str(name))
                if candidate and normalized.startswith(candidate) and len(candidate) > best_length:
                    best_key = key
                    best_length = len(candidate)
        if best_key is not None:
            values[best_key] = value
    return values


def _threshold_map(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(result.get("key")): result.get("threshold") or {} for result in results if result.get("key")}


def _record_status(
    record: dict[str, Any],
    value: float | None,
    threshold: dict[str, Any] | None,
) -> KpiDisplayStatus:
    if record.get("errors"):
        return KpiDisplayStatus.UNAVAILABLE
    if value is None:
        return KpiDisplayStatus.UNAVAILABLE
    if not threshold:
        return KpiDisplayStatus.NEUTRAL
    try:
        limit = float(threshold.get("periods", {}).get(str(record.get("period_minutes")), threshold.get("default")))
    except (TypeError, ValueError):
        return KpiDisplayStatus.UNAVAILABLE
    direction = threshold.get("direction")
    if direction == "min" and value < limit:
        return KpiDisplayStatus.FAIL
    if direction == "max" and value > limit:
        return KpiDisplayStatus.FAIL
    if direction not in {"min", "max"}:
        return KpiDisplayStatus.NEUTRAL
    # 当前契约只定义越限判定；warn 保留给未来阈值模型扩展。
    return KpiDisplayStatus.PASS


def _derived_value(
    formula: dict[str, Any] | None,
    values: dict[str, float],
) -> float | None:
    """按声明式 ratio 公式计算记录级值；不执行动态表达式。"""
    if not formula or formula.get("kind") != "ratio":
        return None
    try:
        numerator = values[formula["numerator"]]
        denominator = values.get(formula["denominator"])
        if denominator is None:
            fallback = formula.get("denominator_fallback")
            if not fallback or fallback.get("kind") != "sum":
                return None
            inputs = [values[input_key] for input_key in fallback.get("inputs", [])]
            if not inputs:
                return None
            denominator = sum(inputs)
        if denominator == 0:
            return None
        result = numerator / denominator
    except (KeyError, TypeError, ZeroDivisionError):
        return None
    scale = formula.get("scale", 1)
    try:
        result *= float(scale)
    except (TypeError, ValueError):
        return None
    return result


def _build_catalog(metadata: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    catalog: dict[str, dict[str, Any]] = {}
    definitions = metadata.get("metric_catalog", [])
    results = metadata.get("kpi_results", [])
    for definition in definitions if isinstance(definitions, list) else []:
        if not isinstance(definition, dict):
            continue
        key = str(definition.get("key", ""))
        if key:
            catalog[key] = definition
    thresholds = _threshold_map(results if isinstance(results, list) else [])
    return catalog, thresholds


def list_kpi_records(
    task_id: str,
    rule_code: str,
    *,
    metric_key: str | None = None,
    source_file: str | None = None,
    period_minutes: int | None = None,
    status: KpiDisplayStatus | None = None,
    page: int = 1,
    page_size: int = 50,
    output: Path | None = None,
) -> KpiRecordPage:
    """从规则结果 metadata 投影 KPI 记录分页。"""
    result = load_rule_result(output or settings.output, task_id, rule_code)
    if result is None:
        raise KeyError(rule_code)
    return project_kpi_records(
        result,
        metric_key=metric_key,
        source_file=source_file,
        period_minutes=period_minutes,
        status=status,
        page=page,
        page_size=page_size,
    )


def project_kpi_records(
    result: RuleResult,
    *,
    metric_key: str | None = None,
    source_file: str | None = None,
    period_minutes: int | None = None,
    status: KpiDisplayStatus | None = None,
    page: int = 1,
    page_size: int = 50,
) -> KpiRecordPage:
    """将目录化 KPI metadata 投影为记录分页。"""
    metadata = result.metadata
    try:
        metadata_version = int(metadata.get("version", 0)) if isinstance(metadata, dict) else 0
    except (TypeError, ValueError):
        metadata_version = 0
    if metadata_version < 2:
        return KpiRecordPage(total=0, page=page, page_size=page_size, items=[])

    catalog, thresholds = _build_catalog(metadata)
    items: list[KpiRecordItem] = []

    kpi_files = metadata.get("kpi_files", [])
    if not isinstance(kpi_files, list):
        kpi_files = []
    for kpi_file in kpi_files:
        if not isinstance(kpi_file, dict):
            continue
        file_path = str(kpi_file.get("path", ""))
        if source_file is not None and file_path != source_file:
            continue
        records = kpi_file.get("records", [])
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                record_period = int(record.get("period_minutes", kpi_file.get("period_minutes", 0)))
                line_number = int(record.get("line_number", 0))
            except (TypeError, ValueError):
                continue
            if period_minutes is not None and record_period != period_minutes:
                continue
            source_values: dict[str, float] = {}
            raw_values = record.get("values", {})
            if isinstance(raw_values, dict):
                for name, value in raw_values.items():
                    try:
                        source_values[str(name)] = float(value)
                    except (TypeError, ValueError):
                        continue
            stable_values = _stable_record_values(source_values, catalog)

            for key, definition in catalog.items():
                if metric_key is not None and key != metric_key:
                    continue
                formula = definition.get("formula") if definition.get("source_type") == "derived" else None
                value: float | None
                if formula:
                    value = _derived_value(formula, stable_values)
                else:
                    value = stable_values.get(key)
                display_status = _record_status(record, value, thresholds.get(key))
                if status is not None and display_status != status:
                    continue
                items.append(
                    KpiRecordItem(
                        metric_key=key,
                        metric_name_zh=str(definition.get("name_zh", key)),
                        source_file=file_path,
                        line_number=line_number,
                        period_minutes=record_period,
                        start_at=record.get("start_at"),
                        end_at=record.get("end_at"),
                        value=value,
                        status=display_status,
                        errors=record.get("errors", []) if isinstance(record.get("errors", []), list) else [],
                    )
                )

    items.sort(
        key=lambda item: (
            item.source_file,
            item.line_number,
            item.metric_key,
        )
    )
    total = len(items)
    start = (page - 1) * page_size
    return KpiRecordPage(
        total=total,
        page=page,
        page_size=page_size,
        items=items[start : start + page_size],
    )
