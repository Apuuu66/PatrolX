"""把任务终态现场投影为可查询的 v6 KPI 结果与历史点。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import InspectionTask, Product
from app.services import store, task_db
from app.services.kpi_history import KPI_RULE_CODE, index_path, iter_history_index

logger = get_logger("patrolx.kpi_v6_terminal_publish")

_NO_ATTENTION_SPECIAL_STATES = {
    "not_applicable",
    "no_action",
    "no_baseline",
    "all_zero",
    "zero_denominator",
}
_SPECIAL_STATE_BY_REASON = {
    "no_current_data": "no_data",
    "dependency_missing": "no_data",
    "all_zero": "all_zero",
    "zero_denominator": "zero_denominator",
    "no_baseline": "no_baseline",
    "no_action": "no_action",
    "not_applicable": "not_applicable",
}


def _task_network_element_type(task: InspectionTask) -> str | None:
    """只从任务元数据 product 解析网元类型，未知值不猜测作用域。"""
    customer = task.system.customer if task.system is not None else {}
    value = customer.get("product")
    if not isinstance(value, str):
        return None
    try:
        return Product(value).value
    except ValueError:
        return None


def _daily_health_metrics(rule_result: object) -> list[dict[str, Any]]:
    metadata = getattr(rule_result, "metadata", None)
    if not isinstance(metadata, dict):
        return []
    daily_health = metadata.get("daily_health")
    if not isinstance(daily_health, dict):
        return []
    metrics = daily_health.get("metrics")
    if not isinstance(metrics, list):
        return []
    return [metric for metric in metrics if isinstance(metric, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = item.strip() if isinstance(item, str) else ""
        if text and text not in result:
            result.append(text)
    return result


def _source_files(metric: dict[str, Any]) -> list[str]:
    files: list[str] = []
    objects = metric.get("objects")
    if not isinstance(objects, list):
        return files
    for item in objects:
        if not isinstance(item, dict):
            continue
        for source_file in _string_list(item.get("source_files")):
            if source_file not in files:
                files.append(source_file)
    return files


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int) and value >= 0 else 0


def _special_state(current_status: str, current_reason: str) -> str | None:
    explicit = _SPECIAL_STATE_BY_REASON.get(current_reason)
    if explicit is not None:
        return explicit
    if current_status == "not_applicable":
        return "not_applicable"
    return None


def _decision(current_status: str) -> str:
    return {
        "normal": "pass",
        "warn": "warn",
        "fail": "fail",
        "unable_to_judge": "unjudgeable",
        "pending_config": "needs_config",
        "not_applicable": "not_applicable",
    }.get(current_status, "unjudgeable")


def _attention_group(
    *,
    current_status: str,
    trend_status: str,
    special_state: str | None,
) -> str | None:
    if special_state in _NO_ATTENTION_SPECIAL_STATES:
        return None
    if current_status == "fail":
        return "failure"
    if current_status == "warn":
        return "warning"
    if current_status == "normal" and trend_status == "worsened":
        return "trend_degraded"
    if current_status == "unable_to_judge":
        return "unjudgeable"
    if current_status == "pending_config":
        return "needs_config"
    return None


def _formula(role: str, config: dict[str, Any], metric: dict[str, Any]) -> str | None:
    if role != "derived":
        return None
    explicit = metric.get("formula") or config.get("formula")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    numerator = config.get("numerator_metric_id")
    denominator = config.get("denominator_metric_id")
    if isinstance(numerator, str) and isinstance(denominator, str):
        return f"{numerator} / {denominator} * 100"
    return None


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _metric_result(
    *,
    task: InspectionTask,
    network_element_type: str,
    scope_item: task_db.KpiScopeItemData,
    metric: dict[str, Any],
    published_at: datetime,
) -> task_db.KpiMetricResultData:
    config = scope_item.config_snapshot
    role = str(metric.get("role") or scope_item.metric_kind or "base")
    current_status = str(metric.get("current_status") or "unable_to_judge")
    current_reason = str(metric.get("current_reason") or "no_data")
    current_reason_text = str(metric.get("current_reason_text") or "缺少可判定数据")
    trend_status = str(metric.get("trend_status") or "no_baseline")
    special_state = _special_state(current_status, current_reason)
    decision = _decision(current_status)
    needs_attention_group = _attention_group(
        current_status=current_status,
        trend_status=trend_status,
        special_state=special_state,
    )
    today_value = _number(metric.get("today_value"))
    yesterday_value = _number(metric.get("yesterday_value"))
    change = _number(metric.get("delta"))
    unit_value = metric.get("display_unit") or config.get("display_unit")
    unit = str(unit_value) if isinstance(unit_value, str) and unit_value else None
    importance_value = metric.get("importance") or config.get("importance") or "normal"
    importance = str(importance_value)
    source_files = _source_files(metric)
    raw_source_names = _string_list(metric.get("raw_source_names")) or _string_list(config.get("raw_source_names"))
    objects = metric.get("objects")
    effective_point_count = sum(_integer(item.get("valid_count")) for item in objects or [] if isinstance(item, dict))
    result_payload = {
        "metric_role": role,
        "current_status": current_status,
        "current_reason": current_reason,
        "current_reason_text": current_reason_text,
        "trend_status": trend_status,
        "trend_reason": metric.get("trend_reason"),
        "evidence_available": bool(source_files),
        "raw_source_names": raw_source_names,
        "source_files": source_files,
        "formula": _formula(role, config, metric),
    }
    identity_payload = {
        "task_id": task.task_id,
        "network_element_type": network_element_type,
        "measurement_unit_id": scope_item.measurement_unit_id,
        "metric_resource_id": scope_item.metric_resource_id,
        "decision": decision,
        "special_state": special_state,
        "yesterday_trend": trend_status,
        "needs_attention_group": needs_attention_group,
        "today_value": today_value,
        "yesterday_value": yesterday_value,
        "change": change,
        "unit": unit,
        "importance": importance,
        "reason": current_reason_text,
        "effective_point_count": effective_point_count,
        "result_payload": result_payload,
    }
    return task_db.KpiMetricResultData(
        task_id=task.task_id,
        network_element_type=network_element_type,
        measurement_unit_id=scope_item.measurement_unit_id,
        metric_resource_id=scope_item.metric_resource_id,
        source_rule_code=KPI_RULE_CODE,
        decision=decision,
        special_state=special_state,
        yesterday_trend=trend_status,
        needs_attention_group=needs_attention_group,
        today_value=today_value,
        yesterday_value=yesterday_value,
        change=change,
        unit=unit,
        importance=importance,
        reason=current_reason_text,
        effective_point_count=effective_point_count,
        result_payload=result_payload,
        result_fingerprint=_fingerprint(identity_payload),
        published_at=published_at,
    )


def _missing_metric_result(
    *,
    task: InspectionTask,
    network_element_type: str,
    scope_item: task_db.KpiScopeItemData,
    published_at: datetime,
) -> task_db.KpiMetricResultData:
    config = scope_item.config_snapshot
    return _metric_result(
        task=task,
        network_element_type=network_element_type,
        scope_item=scope_item,
        metric={
            "role": scope_item.metric_kind,
            "current_status": "unable_to_judge",
            "current_reason": "no_current_data",
            "current_reason_text": "缺少可用的 KPI 现场数据",
            "trend_status": "no_baseline",
            "today_value": None,
            "yesterday_value": None,
            "delta": None,
            "display_unit": config.get("display_unit"),
            "importance": config.get("importance"),
            "objects": [],
        },
        published_at=published_at,
    )


def _scene_points(
    task_id: str,
    *,
    network_element_type: str,
    output: Path,
    scope_ids: set[tuple[str, str]],
) -> list[task_db.KpiPointData]:
    path = index_path(output, task_id)
    if not path.is_file():
        return []
    points: dict[str, task_db.KpiPointData] = {}
    for record in iter_history_index(task_id, output=output, source="scene"):
        identity = (record["measurement_unit_id"], record["metric_resource_id"])
        if identity not in scope_ids:
            continue
        measured_at = record["measured_at"]
        assert isinstance(measured_at, datetime)
        measured_at = measured_at.astimezone(UTC)
        fingerprint_payload = {
            "task_id": task_id,
            "measurement_unit_id": record["measurement_unit_id"],
            "metric_resource_id": record["metric_resource_id"],
            "object_key": record.get("object_key") or "__all__",
            "period_minutes": record.get("period_minutes"),
            "measured_at": measured_at.isoformat(),
            "value": float(record["value"]),
            "source_file": record.get("source_file"),
            "line_number": record.get("line_number"),
        }
        fingerprint = _fingerprint(fingerprint_payload)
        points[fingerprint] = task_db.KpiPointData(
            task_id=task_id,
            network_element_type=network_element_type,
            source_rule_code=KPI_RULE_CODE,
            measurement_unit_id=str(record["measurement_unit_id"]),
            metric_resource_id=str(record["metric_resource_id"]),
            object_key=str(record.get("object_key") or "__all__"),
            period_minutes=(int(record["period_minutes"]) if isinstance(record.get("period_minutes"), int) else None),
            measured_at=measured_at,
            value=float(record["value"]),
            source_file=(str(record["source_file"]) if isinstance(record.get("source_file"), str) else None),
            line_number=(int(record["line_number"]) if isinstance(record.get("line_number"), int) else None),
            point_fingerprint=fingerprint,
        )
    return list(points.values())


def publish_kpi_v6_from_scene(task: InspectionTask, *, output: Path | None = None) -> int:
    """读取当前现场并全量发布 v6 结果；没有任务 KPI 快照时安全 no-op。"""
    network_element_type = _task_network_element_type(task)
    if network_element_type is None:
        return 0
    snapshot = task_db.get_kpi_scope_snapshot(
        task.task_id,
        network_element_type=network_element_type,
    )
    if snapshot is None or not snapshot.items:
        return 0

    base = output or settings.output
    rule_result = store.load_rule_result(base, task.task_id, KPI_RULE_CODE)
    metrics_by_identity = {
        (str(metric.get("measurement_unit_id")), str(metric.get("metric_resource_id"))): metric
        for metric in _daily_health_metrics(rule_result)
    }
    published_at = datetime.now(UTC)
    results: list[task_db.KpiMetricResultData] = []
    for scope_item in snapshot.items:
        identity = (scope_item.measurement_unit_id, scope_item.metric_resource_id)
        metric = metrics_by_identity.get(identity)
        if metric is None:
            results.append(
                _missing_metric_result(
                    task=task,
                    network_element_type=network_element_type,
                    scope_item=scope_item,
                    published_at=published_at,
                )
            )
        else:
            results.append(
                _metric_result(
                    task=task,
                    network_element_type=network_element_type,
                    scope_item=scope_item,
                    metric=metric,
                    published_at=published_at,
                )
            )

    scope_ids = {(item.measurement_unit_id, item.metric_resource_id) for item in snapshot.items}
    points = _scene_points(
        task.task_id,
        network_element_type=network_element_type,
        output=base,
        scope_ids=scope_ids,
    )
    task_db.publish_kpi_v6_snapshot(
        task,
        metric_results=results,
        metric_points=points,
    )
    logger.info(
        "task_kpi_v6_published",
        task_id=task.task_id,
        network_element_type=network_element_type,
        metric_result_count=len(results),
        kpi_point_count=len(points),
    )
    return len(results)
