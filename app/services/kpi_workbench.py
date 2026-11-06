"""KPI 巡检结果工作台的查询与投影服务。

服务层只使用任务冻结快照、共享团队关注和已发布最终判定。它不读取原始
KPI 点重新判定，也不从请求数/成功响应数等证据反算指标值。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, TypeVar

from app.models import kpi_v6 as schemas
from app.services.task_db import (
    KpiWorkbenchFocusItemData,
    KpiWorkbenchScopeItemData,
    KpiWorkbenchSourceData,
    get_kpi_workbench_source_data,
    get_task_summary,
    list_kpi_points_v6,
    list_previous_completed_task_ids,
)

_GROUP_ORDER: tuple[schemas.NeedsAttentionGroup, ...] = (
    schemas.NeedsAttentionGroup.FAILURE,
    schemas.NeedsAttentionGroup.WARNING,
    schemas.NeedsAttentionGroup.TREND_DEGRADED,
    schemas.NeedsAttentionGroup.UNJUDGEABLE,
    schemas.NeedsAttentionGroup.NEEDS_CONFIG,
)
_GROUP_RANK = {group: rank for rank, group in enumerate(_GROUP_ORDER, start=1)}
_NO_GROUP_RANK = len(_GROUP_ORDER) + 1
_FALLBACK_RANK = 2**31
_NOT_MATCHED_STATUS = object()

_EnumT = TypeVar("_EnumT", bound=StrEnum)


class KpiWorkbenchError(Exception):
    """工作台读取失败；由路由层映射为统一 API 错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        detail: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


class KpiWorkbenchTaskNotFound(KpiWorkbenchError):
    """任务不存在。"""

    def __init__(self, task_id: str) -> None:
        super().__init__("task_not_found", f"任务不存在: {task_id}", 404)


class KpiWorkbenchResultRequiresRebuild(KpiWorkbenchError):
    """旧任务没有 v6 KPI 快照。"""

    def __init__(self) -> None:
        super().__init__(
            "task_result_requires_rebuild",
            "旧任务没有 v6 KPI 快照，请按当前配置重建",
            409,
        )


class KpiWorkbenchMetricNotFound(KpiWorkbenchError):
    """指标不在任务的冻结 KPI 范围内。"""

    def __init__(
        self,
        task_id: str,
        measurement_unit_id: str,
        metric_resource_id: str,
    ) -> None:
        super().__init__(
            "kpi_metric_not_found",
            "指标不在当前任务的 KPI 快照中",
            404,
            {
                "task_id": task_id,
                "measurement_unit_id": measurement_unit_id,
                "metric_resource_id": metric_resource_id,
            },
        )


class KpiWorkbenchEvidenceUnavailable(KpiWorkbenchError):
    """单指标证据不可读；不牵连其他结果。"""

    def __init__(self, measurement_unit_id: str, metric_resource_id: str) -> None:
        super().__init__(
            "kpi_evidence_unavailable",
            "指标证据读取失败，请重试",
            424,
            {
                "retryable": True,
                "measurement_unit_id": measurement_unit_id,
                "metric_resource_id": metric_resource_id,
            },
        )


@dataclass(frozen=True, slots=True)
class _MetricIdentity:
    measurement_unit_id: str
    metric_resource_id: str


@dataclass(frozen=True, slots=True)
class _DerivedDefinition:
    numerator_metric_id: str
    denominator_metric_id: str
    numerator_name: str
    denominator_name: str
    formula: str | None


def _source_or_raise(task_id: str) -> KpiWorkbenchSourceData:
    source = get_kpi_workbench_source_data(task_id)
    if source is None:
        raise KpiWorkbenchTaskNotFound(task_id)
    if not source.snapshot_present:
        raise KpiWorkbenchResultRequiresRebuild()
    return source


def _enum_value(enum_type: type[_EnumT], value: object) -> _EnumT | object:
    if value is None:
        return _NOT_MATCHED_STATUS
    try:
        return enum_type(str(value))
    except ValueError:
        return _NOT_MATCHED_STATUS


def _optional_enum(enum_type: type[_EnumT], value: object) -> _EnumT | None:
    parsed = _enum_value(enum_type, value)
    return parsed if isinstance(parsed, enum_type) else None


def _optional_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    return None


def _iso_utc(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _display_order(item: KpiWorkbenchScopeItemData) -> int:
    for key in ("importance_rank", "display_order"):
        value = item.config_snapshot.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return _FALLBACK_RANK


def _importance_rank(
    item: KpiWorkbenchScopeItemData,
    result: dict[str, Any] | None,
) -> int:
    """优先使用最终结果的业务重要度；无显式等级时再回退冻结显示顺序。"""
    importance = _importance(item, result)
    return {
        schemas.Importance.P0: 0,
        schemas.Importance.P1: 1,
        schemas.Importance.P2: 2,
        schemas.Importance.NORMAL: 3,
    }[importance]


def _importance(item: KpiWorkbenchScopeItemData, result: dict[str, Any] | None) -> schemas.Importance:
    value = result.get("importance") if result is not None else None
    if value is None:
        value = item.config_snapshot.get("importance")
    parsed = _optional_enum(schemas.Importance, value)
    return parsed or schemas.Importance.NORMAL


def _role(item: KpiWorkbenchScopeItemData, result: dict[str, Any] | None) -> schemas.MetricRole:
    value: object = item.metric_kind
    if not isinstance(value, str) or value not in {"base", "derived"}:
        payload = result.get("result_payload", {}) if result is not None else {}
        value = payload.get("metric_role") if isinstance(payload, dict) else None
    parsed = _optional_enum(schemas.MetricRole, value)
    return parsed or schemas.MetricRole.BASE


def _current_status(result: dict[str, Any]) -> schemas.CurrentHealthStatus | None:
    payload = result.get("result_payload")
    payload_status = payload.get("current_status") if isinstance(payload, dict) else None
    parsed = _optional_enum(schemas.CurrentHealthStatus, payload_status)
    if parsed is not None:
        return parsed
    return {
        "fail": schemas.CurrentHealthStatus.FAIL,
        "warn": schemas.CurrentHealthStatus.WARN,
        "pass": schemas.CurrentHealthStatus.NORMAL,
        "error": schemas.CurrentHealthStatus.UNABLE_TO_JUDGE,
        "skip": schemas.CurrentHealthStatus.PENDING_CONFIG,
    }.get(str(result.get("decision")))


def _change_unit(item: KpiWorkbenchScopeItemData, result: dict[str, Any]) -> str | None:
    payload = result.get("result_payload")
    if isinstance(payload, dict):
        explicit = _optional_enum(
            schemas.ChangeUnit if hasattr(schemas, "ChangeUnit") else _ChangeUnit,
            payload.get("change_unit"),
        )
        if explicit is not None:
            return str(explicit)
    if _optional_number(result.get("change")) is None:
        return None
    if bool(item.config_snapshot.get("is_percentage", False)):
        return "pp"
    return "absolute"


class _ChangeUnit(StrEnum):
    PP = "pp"
    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    UNAVAILABLE = "unavailable"


def _evidence_available(result: dict[str, Any]) -> bool | None:
    payload = result.get("result_payload")
    value = payload.get("evidence_available") if isinstance(payload, dict) else None
    return value if isinstance(value, bool) else None


def _result_metric(
    source: KpiWorkbenchSourceData,
    item: KpiWorkbenchScopeItemData,
    result: dict[str, Any] | None,
    *,
    is_team_focus: bool,
) -> schemas.KpiMetricResultV6:
    group = (
        _optional_enum(schemas.NeedsAttentionGroup, result.get("needs_attention_group")) if result is not None else None
    )
    if result is None:
        group = schemas.NeedsAttentionGroup.UNJUDGEABLE if is_team_focus else None

    return schemas.KpiMetricResultV6(
        task_id=source.task_id,
        network_element_type=source.network_element_type or "",
        measurement_unit_id=item.measurement_unit_id,
        measurement_unit_name=item.measurement_unit_name,
        metric_resource_id=item.metric_resource_id,
        metric_name=item.metric_name,
        role=_role(item, result),
        importance=_importance(item, result),
        importance_rank=_importance_rank(item, result),
        availability=schemas.MetricAvailability.AVAILABLE,
        is_team_focus=is_team_focus,
        current_status=(_current_status(result) if result is not None else schemas.CurrentHealthStatus.UNABLE_TO_JUDGE),
        yesterday_trend=(
            _optional_enum(schemas.TrendHealthStatus, result.get("yesterday_trend"))
            if result is not None
            else schemas.TrendHealthStatus.NO_BASELINE
        ),
        needs_attention_group=group,
        special_state=(
            _optional_enum(schemas.MetricSpecialState, result.get("special_state"))
            if result is not None
            else schemas.MetricSpecialState.NO_DATA
        ),
        today_value=_optional_number(result.get("today_value")) if result is not None else None,
        yesterday_value=(_optional_number(result.get("yesterday_value")) if result is not None else None),
        change_value=_optional_number(result.get("change")) if result is not None else None,
        change_unit=_change_unit(item, result) if result is not None else None,
        reason=(str(result.get("reason") or "") if result is not None else "指标结果尚未生成"),
        evidence_available=(_evidence_available(result) if result is not None else False),
    )


def _unavailable_focus_metric(
    source: KpiWorkbenchSourceData,
    focus: KpiWorkbenchFocusItemData,
    *,
    reason: schemas.FocusAvailabilityReason,
) -> schemas.KpiMetricResultV6:
    return schemas.KpiMetricResultV6(
        task_id=source.task_id,
        network_element_type=source.network_element_type or "",
        measurement_unit_id=focus.measurement_unit_id,
        measurement_unit_name=focus.measurement_unit_name,
        metric_resource_id=focus.metric_resource_id,
        metric_name=focus.metric_name,
        role=schemas.MetricRole.BASE,
        importance=schemas.Importance.NORMAL,
        importance_rank=_FALLBACK_RANK,
        availability=schemas.MetricAvailability.UNAVAILABLE,
        availability_reason=reason,
        is_team_focus=True,
    )


def _all_metrics(source: KpiWorkbenchSourceData) -> list[schemas.KpiMetricResultV6]:
    result_map = {
        _MetricIdentity(
            measurement_unit_id=str(result["measurement_unit_id"]),
            metric_resource_id=str(result["metric_resource_id"]),
        ): result
        for result in source.metric_results
    }
    focus_ids = {
        _MetricIdentity(
            measurement_unit_id=item.measurement_unit_id,
            metric_resource_id=item.metric_resource_id,
        )
        for item in source.focus_items
    }
    return [
        _result_metric(
            source,
            item,
            result_map.get(
                _MetricIdentity(
                    measurement_unit_id=item.measurement_unit_id,
                    metric_resource_id=item.metric_resource_id,
                )
            ),
            is_team_focus=(
                _MetricIdentity(
                    measurement_unit_id=item.measurement_unit_id,
                    metric_resource_id=item.metric_resource_id,
                )
                in focus_ids
            ),
        )
        for item in source.scope_items
    ]


def _team_focus_metrics(
    source: KpiWorkbenchSourceData,
    all_metrics: list[schemas.KpiMetricResultV6],
) -> list[schemas.KpiMetricResultV6]:
    scope_map = {
        _MetricIdentity(
            measurement_unit_id=item.measurement_unit_id,
            metric_resource_id=item.metric_resource_id,
        ): item
        for item in source.scope_items
    }
    metric_map = {
        _MetricIdentity(
            measurement_unit_id=item.measurement_unit_id,
            metric_resource_id=item.metric_resource_id,
        ): item
        for item in all_metrics
    }
    result: list[schemas.KpiMetricResultV6] = []
    for focus in source.focus_items:
        identity = _MetricIdentity(focus.measurement_unit_id, focus.metric_resource_id)
        scope_item = scope_map.get(identity)
        if scope_item is None:
            result.append(
                _unavailable_focus_metric(
                    source,
                    focus,
                    reason=schemas.FocusAvailabilityReason.NOT_IN_TASK_SCOPE,
                )
            )
            continue
        metric = metric_map[identity]
        if not scope_item.measurement_unit_enabled:
            result.append(
                _unavailable_focus_metric(
                    source,
                    focus,
                    reason=schemas.FocusAvailabilityReason.MEASUREMENT_UNIT_DISABLED,
                )
            )
            continue
        result.append(metric)
    return result


def _view_metrics(
    source: KpiWorkbenchSourceData,
    view: schemas.KpiResultView,
) -> list[schemas.KpiMetricResultV6]:
    all_metrics = _all_metrics(source)
    if view is schemas.KpiResultView.ALL:
        return all_metrics
    focus_metrics = _team_focus_metrics(source, all_metrics)
    if view is schemas.KpiResultView.TEAM_FOCUS:
        return focus_metrics
    return [
        item
        for item in focus_metrics
        if item.availability is schemas.MetricAvailability.AVAILABLE and item.needs_attention_group is not None
    ]


def _sort_metrics(items: list[schemas.KpiMetricResultV6]) -> list[schemas.KpiMetricResultV6]:
    return sorted(
        items,
        key=lambda item: (
            _GROUP_RANK.get(item.needs_attention_group, _NO_GROUP_RANK),
            item.importance_rank,
            item.measurement_unit_id,
            item.metric_resource_id,
        ),
    )


def _matches_filters(
    item: schemas.KpiMetricResultV6,
    *,
    search: str | None,
    measurement_unit_id: str | None,
    current_status: schemas.CurrentHealthStatus | None,
    yesterday_trend: schemas.TrendHealthStatus | None,
    needs_attention_group: schemas.NeedsAttentionGroup | None,
) -> bool:
    if measurement_unit_id is not None and item.measurement_unit_id != measurement_unit_id:
        return False
    if current_status is not None and item.current_status is not current_status:
        return False
    if yesterday_trend is not None and item.yesterday_trend is not yesterday_trend:
        return False
    if needs_attention_group is not None and item.needs_attention_group is not needs_attention_group:
        return False
    if search:
        query = search.casefold().strip()
        haystack = " ".join(
            (
                item.measurement_unit_id,
                item.measurement_unit_name,
                item.metric_resource_id,
                item.metric_name,
            )
        ).casefold()
        if query not in haystack:
            return False
    return True


def _summary_group_counts(
    focus_metrics: list[schemas.KpiMetricResultV6],
) -> list[schemas.KpiNeedsAttentionGroupSummary]:
    counts = Counter(
        item.needs_attention_group
        for item in focus_metrics
        if item.availability is schemas.MetricAvailability.AVAILABLE and item.needs_attention_group is not None
    )
    return [
        schemas.KpiNeedsAttentionGroupSummary(
            group=group,
            order=order,
            count=counts[group],
        )
        for order, group in enumerate(_GROUP_ORDER, start=1)
    ]


def _enabled_measurement_unit_count(source: KpiWorkbenchSourceData) -> int:
    frozen_ids = source.snapshot_payload.get("enabled_measurement_unit_ids")
    if isinstance(frozen_ids, list):
        return len({str(value) for value in frozen_ids if str(value).strip()})
    return len({item.measurement_unit_id for item in source.scope_items if item.measurement_unit_enabled})


def get_kpi_task_summary(task_id: str) -> schemas.KpiTaskSummaryV6:
    """返回当前任务全局汇总；不受结果列表筛选影响。"""
    source = _source_or_raise(task_id)
    all_metrics = _all_metrics(source)
    focus_metrics = _team_focus_metrics(source, all_metrics)
    available_focus = [item for item in focus_metrics if item.availability is schemas.MetricAvailability.AVAILABLE]
    needs_attention_count = sum(item.needs_attention_group is not None for item in available_focus)
    no_action_count = len(available_focus) - needs_attention_count
    unavailable_focus_count = len(focus_metrics) - len(available_focus)
    previous_date: date | None = source.data_date - timedelta(days=1) if source.data_date is not None else None
    has_business_rules = source.business_rule_count > 0
    notice = None if has_business_rules else "当前网元类型未配置可执行业务规则"
    return schemas.KpiTaskSummaryV6(
        task_id=source.task_id,
        network_element_type=source.network_element_type,
        result_contract_version="v6",
        data_date=source.data_date.isoformat() if source.data_date is not None else None,
        previous_date=previous_date.isoformat() if previous_date is not None else None,
        latest_measured_at=_iso_utc(source.latest_measured_at),
        counts=schemas.KpiSummaryCountsV6(
            enabled_measurement_unit_count=_enabled_measurement_unit_count(source),
            all_metric_count=len(source.scope_items),
            team_focus_count=len(available_focus),
            needs_attention_count=needs_attention_count,
            no_action_count=no_action_count,
            unavailable_focus_count=unavailable_focus_count,
        ),
        needs_attention_groups=_summary_group_counts(focus_metrics),
        rule_scope=schemas.KpiRuleScopeStatusV6(
            business_rule_count=source.business_rule_count,
            has_executable_rules=has_business_rules,
            notice=notice,
        ),
        notices=[],
    )


def list_kpi_task_metrics(
    task_id: str,
    *,
    view: schemas.KpiResultView = schemas.KpiResultView.NEEDS_ATTENTION,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    measurement_unit_id: str | None = None,
    current_status: schemas.CurrentHealthStatus | None = None,
    yesterday_trend: schemas.TrendHealthStatus | None = None,
    needs_attention_group: schemas.NeedsAttentionGroup | None = None,
) -> schemas.KpiMetricResultPageV6:
    """查询三视图之一，并在服务端完成互斥分组、排序、筛选和分页。"""
    source = _source_or_raise(task_id)
    normalized_search = search.strip() if search is not None and search.strip() else None
    view_metrics = _sort_metrics(_view_metrics(source, view))
    view_total = len(view_metrics)
    filtered = [
        item
        for item in view_metrics
        if _matches_filters(
            item,
            search=normalized_search,
            measurement_unit_id=measurement_unit_id,
            current_status=current_status,
            yesterday_trend=yesterday_trend,
            needs_attention_group=needs_attention_group,
        )
    ]
    total = len(filtered)
    if not source.scope_items:
        empty_state = "no_task_metrics"
    elif view in {schemas.KpiResultView.NEEDS_ATTENTION, schemas.KpiResultView.TEAM_FOCUS} and not source.focus_items:
        empty_state = "team_focus_empty"
    elif total == 0:
        empty_state = "no_matching_metrics"
    else:
        empty_state = "none"
    offset = (page - 1) * page_size
    return schemas.KpiMetricResultPageV6(
        items=filtered[offset : offset + page_size],
        total=total,
        view_total=view_total,
        page=page,
        page_size=page_size,
        empty_state=empty_state,
        applied_filters=schemas.KpiAppliedFiltersV6(
            search=normalized_search,
            measurement_unit_id=measurement_unit_id,
            current_status=current_status,
            yesterday_trend=yesterday_trend,
            needs_attention_group=needs_attention_group,
        ),
    )


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("result_payload")
    return dict(payload) if isinstance(payload, dict) else {}


def _metric_context(
    source: KpiWorkbenchSourceData,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> tuple[KpiWorkbenchScopeItemData, dict[str, Any]]:
    """按冻结范围与已发布结果读取单指标，禁止跨测量单元或任务回退。"""
    scope_item = next(
        (
            item
            for item in source.scope_items
            if item.measurement_unit_id == measurement_unit_id and item.metric_resource_id == metric_resource_id
        ),
        None,
    )
    if scope_item is None:
        raise KpiWorkbenchMetricNotFound(source.task_id, measurement_unit_id, metric_resource_id)
    result = next(
        (
            item
            for item in source.metric_results
            if str(item.get("measurement_unit_id")) == measurement_unit_id
            and str(item.get("metric_resource_id")) == metric_resource_id
        ),
        None,
    )
    if result is None:
        raise KpiWorkbenchEvidenceUnavailable(measurement_unit_id, metric_resource_id)
    return scope_item, result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item not in result:
            result.append(item)
    return result


def _raw_source_names(
    scope_item: KpiWorkbenchScopeItemData,
    result: dict[str, Any],
) -> list[str]:
    names = _string_list(scope_item.config_snapshot.get("raw_source_names"))
    if not names:
        names = _string_list(_payload(result).get("raw_source_names"))
    if not names:
        fallback = scope_item.config_snapshot.get("name_en")
        if isinstance(fallback, str) and fallback.strip():
            names.append(fallback)
    return names


def _derived_definition(
    scope_item: KpiWorkbenchScopeItemData,
    payload: dict[str, Any],
) -> _DerivedDefinition | None:
    config = scope_item.config_snapshot
    numerator_metric_id = config.get("numerator_metric_id", payload.get("numerator_metric_id"))
    denominator_metric_id = config.get("denominator_metric_id", payload.get("denominator_metric_id"))
    if not isinstance(numerator_metric_id, str) or not numerator_metric_id.strip():
        return None
    if not isinstance(denominator_metric_id, str) or not denominator_metric_id.strip():
        return None
    numerator_name = config.get("numerator_metric_name", payload.get("numerator_metric_name"))
    denominator_name = config.get("denominator_metric_name", payload.get("denominator_metric_name"))
    numerator_label = (
        numerator_name.strip() if isinstance(numerator_name, str) and numerator_name.strip() else numerator_metric_id
    )
    denominator_label = (
        denominator_name.strip()
        if isinstance(denominator_name, str) and denominator_name.strip()
        else denominator_metric_id
    )
    explicit_formula = config.get("formula", payload.get("formula"))
    formula = explicit_formula.strip() if isinstance(explicit_formula, str) and explicit_formula.strip() else None
    if formula is None:
        template = config.get("template", payload.get("template"))
        if template == "success_rate":
            formula = f"{numerator_label} ÷ {denominator_label} × 100%"
        elif template == "reverse_success_rate":
            formula = f"(1 - {numerator_label} ÷ {denominator_label}) × 100%"
    return _DerivedDefinition(
        numerator_metric_id=numerator_metric_id,
        denominator_metric_id=denominator_metric_id,
        numerator_name=numerator_label,
        denominator_name=denominator_label,
        formula=formula,
    )


def _point_datetime(point: dict[str, Any]) -> datetime | None:
    value = point.get("measured_at")
    return value if isinstance(value, datetime) else None


def _point_date(point: dict[str, Any]) -> date | None:
    measured_at = _point_datetime(point)
    return measured_at.date() if measured_at is not None else None


def _overall_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overall = [point for point in points if str(point.get("object_key") or "__all__") == "__all__"]
    return overall or points


def _overall_period_minutes(points: list[dict[str, Any]]) -> int | None:
    periods = {
        period
        for point in _overall_points(points)
        if isinstance((period := point.get("period_minutes")), int) and period >= 1
    }
    return min(periods) if periods else None


def _group_points(
    points: list[dict[str, Any]],
    *,
    object_key: str,
    period_minutes: int | None,
) -> list[dict[str, Any]]:
    return [
        point
        for point in points
        if str(point.get("object_key") or "__all__") == object_key and point.get("period_minutes") == period_minutes
    ]


def _aggregate_points(
    points: list[dict[str, Any]],
    aggregation: Literal["latest", "mean", "sum", "max", "min"] = "latest",
) -> int | float | None:
    measured = [(point, value) for point in points if (value := _optional_number(point.get("value"))) is not None]
    if not measured:
        return None
    values = [value for _point, value in measured]
    if aggregation == "sum":
        return sum(values)
    if aggregation == "max":
        return max(values)
    if aggregation == "min":
        return min(values)
    if aggregation == "mean":
        return sum(values) / len(values)
    latest = max(
        measured,
        key=lambda item: _point_datetime(item[0]) or datetime.min.replace(tzinfo=UTC),
    )
    return latest[1]


def _group_daily_value(
    points: list[dict[str, Any]],
    *,
    bucket_date: date,
    object_key: str,
    period_minutes: int | None,
    aggregation: Literal["latest", "mean", "sum", "max", "min"],
) -> int | float | None:
    matching = _group_points(points, object_key=object_key, period_minutes=period_minutes)
    return _aggregate_points(
        [point for point in matching if _point_date(point) == bucket_date],
        aggregation,
    )


def _bucket_status(
    result: dict[str, Any],
    value: int | float | None,
    *,
    missing_status: Literal["no_data", "no_baseline"] = "no_data",
) -> Literal["ok", "no_data", "zero_denominator", "unreadable", "no_baseline"]:
    if value is None:
        special_state = _optional_enum(schemas.MetricSpecialState, result.get("special_state"))
        if special_state is schemas.MetricSpecialState.ZERO_DENOMINATOR:
            return "zero_denominator"
        if special_state is schemas.MetricSpecialState.UNAVAILABLE:
            return "unreadable"
        if special_state is schemas.MetricSpecialState.NO_BASELINE:
            return "no_baseline"
        return missing_status
    return "ok"


def _bucket(
    bucket_date: date,
    value: int | float | None,
    points: list[dict[str, Any]],
    *,
    result: dict[str, Any],
    missing_status: Literal["no_data", "no_baseline"] = "no_data",
    numerator: int | float | None = None,
    denominator: int | float | None = None,
) -> schemas.KpiDailyBucketV6:
    measured = [point for point in points if _point_date(point) == bucket_date]
    timestamps = [timestamp for point in measured if (timestamp := _point_datetime(point)) is not None]
    return schemas.KpiDailyBucketV6(
        date=bucket_date,
        value=value,
        numerator=numerator,
        denominator=denominator,
        valid_count=len(measured),
        first_measured_at=_iso_utc(min(timestamps, default=None)),
        last_measured_at=_iso_utc(max(timestamps, default=None)),
        status=_bucket_status(result, value, missing_status=missing_status),
    )


def _metric_daily_aggregation(scope_item: KpiWorkbenchScopeItemData) -> Literal["latest", "mean", "sum", "max", "min"]:
    value = scope_item.config_snapshot.get("daily_aggregation")
    if value in {"latest", "mean", "sum", "max", "min"}:
        return value
    return "latest"


def _threshold_source(value: object) -> Literal["custom", "default", "legacy_resource", "missing"]:
    if value in {"custom", "default", "legacy_resource", "missing"}:
        return value
    return "missing"


def _threshold_direction(value: object) -> Literal["higher_better", "lower_better", "neutral"]:
    if value in {"higher_better", "lower_better", "neutral"}:
        return value
    return "neutral"


def _evidence_sources(
    scope_item: KpiWorkbenchScopeItemData,
    result: dict[str, Any],
    points: list[dict[str, Any]],
    *,
    extra_points: list[dict[str, Any]] | None = None,
) -> list[schemas.KpiMetricSourceV6]:
    payload = _payload(result)
    files: list[str] = []
    explicit_file = payload.get("source_file")
    if isinstance(explicit_file, str) and explicit_file.strip():
        files.append(explicit_file)
    for point in [*points, *(extra_points or [])]:
        source_file = point.get("source_file")
        if isinstance(source_file, str) and source_file.strip() and source_file not in files:
            files.append(source_file)
    names = _raw_source_names(scope_item, result)
    return [
        schemas.KpiMetricSourceV6(
            file=source_file,
            record_group=None,
            raw_source_names=names,
        )
        for source_file in files
    ]


def _evidence_groups(
    points: list[dict[str, Any]],
    *,
    result: dict[str, Any],
    data_date: date,
    current_value: int | float | None,
    previous_value: int | float | None,
    current_status: schemas.CurrentHealthStatus,
    trend_status: schemas.TrendHealthStatus,
    daily_aggregation: Literal["latest", "mean", "sum", "max", "min"],
    derived_definition: _DerivedDefinition | None = None,
    numerator_points: list[dict[str, Any]] | None = None,
    denominator_points: list[dict[str, Any]] | None = None,
) -> list[schemas.KpiEvidenceGroupV6]:
    grouped: dict[tuple[str, int | None], list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        object_key = str(point.get("object_key") or "__all__")
        period_minutes = point.get("period_minutes")
        period = period_minutes if isinstance(period_minutes, int) and period_minutes >= 1 else None
        grouped[(object_key, period)].append(point)
    if not grouped:
        grouped[("__all__", 1440)] = []

    previous_date = data_date - timedelta(days=1)
    groups: list[schemas.KpiEvidenceGroupV6] = []
    for (object_key, period_minutes), group_points in sorted(
        grouped.items(),
        key=lambda item: (item[0][0], item[0][1] is None, item[0][1] or 0),
    ):
        today_points = [point for point in group_points if _point_date(point) == data_date]
        yesterday_points = [point for point in group_points if _point_date(point) == previous_date]
        is_overall = object_key == "__all__"
        today_value = current_value if is_overall else _aggregate_points(today_points, daily_aggregation)
        yesterday_value = previous_value if is_overall else _aggregate_points(yesterday_points, daily_aggregation)
        today_numerator = (
            _group_daily_value(
                numerator_points or [],
                bucket_date=data_date,
                object_key=object_key,
                period_minutes=period_minutes,
                aggregation=daily_aggregation,
            )
            if derived_definition is not None
            else None
        )
        today_denominator = (
            _group_daily_value(
                denominator_points or [],
                bucket_date=data_date,
                object_key=object_key,
                period_minutes=period_minutes,
                aggregation=daily_aggregation,
            )
            if derived_definition is not None
            else None
        )
        yesterday_numerator = (
            _group_daily_value(
                numerator_points or [],
                bucket_date=previous_date,
                object_key=object_key,
                period_minutes=period_minutes,
                aggregation=daily_aggregation,
            )
            if derived_definition is not None
            else None
        )
        yesterday_denominator = (
            _group_daily_value(
                denominator_points or [],
                bucket_date=previous_date,
                object_key=object_key,
                period_minutes=period_minutes,
                aggregation=daily_aggregation,
            )
            if derived_definition is not None
            else None
        )
        evidence_group_points = [
            *group_points,
            *_group_points(
                numerator_points or [],
                object_key=object_key,
                period_minutes=period_minutes,
            ),
            *_group_points(
                denominator_points or [],
                object_key=object_key,
                period_minutes=period_minutes,
            ),
        ]
        source_files = _string_list([point.get("source_file") for point in evidence_group_points])
        groups.append(
            schemas.KpiEvidenceGroupV6(
                object_key=object_key,
                period_minutes=period_minutes,
                today=_bucket(
                    data_date,
                    today_value,
                    today_points,
                    result=result,
                    numerator=today_numerator,
                    denominator=today_denominator,
                ),
                yesterday=(
                    _bucket(
                        previous_date,
                        yesterday_value,
                        yesterday_points,
                        result=result,
                        missing_status="no_baseline",
                        numerator=yesterday_numerator,
                        denominator=yesterday_denominator,
                    )
                    if yesterday_points or is_overall
                    else None
                ),
                current_status=current_status,
                trend_status=trend_status,
                reason=str(result.get("reason") or "") or None,
                source_files=source_files,
            )
        )
    return groups


def _seven_day_trend(
    points: list[dict[str, Any]],
    *,
    result: dict[str, Any],
    data_date: date,
    current_value: int | float | None,
    daily_aggregation: Literal["latest", "mean", "sum", "max", "min"],
    derived_definition: _DerivedDefinition | None = None,
    numerator_points: list[dict[str, Any]] | None = None,
    denominator_points: list[dict[str, Any]] | None = None,
) -> list[schemas.KpiDailyBucketV6]:
    candidates = _overall_points(points)
    period_minutes = _overall_period_minutes(points)
    trend: list[schemas.KpiDailyBucketV6] = []
    for days_ago in range(6, -1, -1):
        bucket_date = data_date - timedelta(days=days_ago)
        day_points = [point for point in candidates if _point_date(point) == bucket_date]
        value = current_value if bucket_date == data_date else _aggregate_points(day_points, daily_aggregation)
        numerator = (
            _group_daily_value(
                numerator_points or [],
                bucket_date=bucket_date,
                object_key="__all__",
                period_minutes=period_minutes,
                aggregation=daily_aggregation,
            )
            if derived_definition is not None
            else None
        )
        denominator = (
            _group_daily_value(
                denominator_points or [],
                bucket_date=bucket_date,
                object_key="__all__",
                period_minutes=period_minutes,
                aggregation=daily_aggregation,
            )
            if derived_definition is not None
            else None
        )
        trend.append(
            _bucket(
                bucket_date,
                value,
                day_points,
                result=result,
                missing_status="no_baseline",
                numerator=numerator,
                denominator=denominator,
            )
        )
    return trend


def get_kpi_metric_evidence(
    task_id: str,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> schemas.KpiMetricEvidenceV6:
    """组装单指标证据；base 指标只展示源包直出值，不生成计算语义。"""
    source = _source_or_raise(task_id)
    scope_item, result = _metric_context(source, measurement_unit_id, metric_resource_id)
    payload = _payload(result)
    if payload.get("evidence_available") is False:
        raise KpiWorkbenchEvidenceUnavailable(measurement_unit_id, metric_resource_id)

    points = list_kpi_points_v6(
        task_id,
        network_element_type=source.network_element_type or "",
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
    )
    data_date = source.data_date
    if data_date is None:
        point_dates = [point_date for point in points if (point_date := _point_date(point)) is not None]
        data_date = max(point_dates, default=datetime.now(UTC).date())

    current_status = _current_status(result) or schemas.CurrentHealthStatus.UNABLE_TO_JUDGE
    trend_status = (
        _optional_enum(schemas.TrendHealthStatus, result.get("yesterday_trend"))
        or _optional_enum(schemas.TrendHealthStatus, payload.get("trend_status"))
        or schemas.TrendHealthStatus.NO_BASELINE
    )
    current_value = _optional_number(result.get("today_value"))
    previous_value = _optional_number(result.get("yesterday_value"))
    role = _role(scope_item, result)
    daily_aggregation = _metric_daily_aggregation(scope_item)
    derived_definition = _derived_definition(scope_item, payload) if role is schemas.MetricRole.DERIVED else None
    numerator_points: list[dict[str, Any]] = []
    denominator_points: list[dict[str, Any]] = []
    if derived_definition is not None:
        numerator_points = list_kpi_points_v6(
            task_id,
            network_element_type=source.network_element_type or "",
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=derived_definition.numerator_metric_id,
        )
        denominator_points = list_kpi_points_v6(
            task_id,
            network_element_type=source.network_element_type or "",
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=derived_definition.denominator_metric_id,
        )
    previous_date = data_date - timedelta(days=1)
    overall_points = _overall_points(points)
    overall_period = _overall_period_minutes(points)
    current_numerator = (
        _group_daily_value(
            numerator_points,
            bucket_date=data_date,
            object_key="__all__",
            period_minutes=overall_period,
            aggregation=daily_aggregation,
        )
        if derived_definition is not None
        else None
    )
    current_denominator = (
        _group_daily_value(
            denominator_points,
            bucket_date=data_date,
            object_key="__all__",
            period_minutes=overall_period,
            aggregation=daily_aggregation,
        )
        if derived_definition is not None
        else None
    )
    previous_numerator = (
        _group_daily_value(
            numerator_points,
            bucket_date=previous_date,
            object_key="__all__",
            period_minutes=overall_period,
            aggregation=daily_aggregation,
        )
        if derived_definition is not None
        else None
    )
    previous_denominator = (
        _group_daily_value(
            denominator_points,
            bucket_date=previous_date,
            object_key="__all__",
            period_minutes=overall_period,
            aggregation=daily_aggregation,
        )
        if derived_definition is not None
        else None
    )
    if derived_definition is not None:
        components = [
            schemas.KpiEvidenceComponentV6(
                metric_resource_id=derived_definition.numerator_metric_id,
                name=derived_definition.numerator_name,
                role="numerator",
                value=current_numerator,
            ),
            schemas.KpiEvidenceComponentV6(
                metric_resource_id=derived_definition.denominator_metric_id,
                name=derived_definition.denominator_name,
                role="denominator",
                value=current_denominator,
            ),
        ]
        formula = derived_definition.formula
    else:
        formula = str(payload["formula"]) if role is schemas.MetricRole.DERIVED and payload.get("formula") else None
        raw_components = payload.get("components") if role is schemas.MetricRole.DERIVED else None
        components = (
            [schemas.KpiEvidenceComponentV6.model_validate(item) for item in raw_components if isinstance(item, dict)]
            if isinstance(raw_components, list)
            else []
        )
    reason_codes = _string_list(payload.get("reason_codes"))
    change_unit = _change_unit(scope_item, result)
    warning_threshold = _optional_number(scope_item.config_snapshot.get("warning_threshold"))
    critical_threshold = _optional_number(scope_item.config_snapshot.get("critical_threshold"))
    threshold = schemas.KpiThresholdEvidenceV6(
        direction=_threshold_direction(scope_item.config_snapshot.get("direction")),
        warning_threshold=warning_threshold,
        critical_threshold=critical_threshold,
        source=_threshold_source(payload.get("threshold_source") or scope_item.config_snapshot.get("threshold_source")),
    )
    config_revision = scope_item.config_snapshot.get("config_revision")
    config_fingerprint = scope_item.config_snapshot.get("config_fingerprint")

    return schemas.KpiMetricEvidenceV6(
        task_id=source.task_id,
        network_element_type=source.network_element_type or "",
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        metric=schemas.KpiMetricEvidenceMetricV6(
            name=scope_item.metric_name,
            role=role,
            is_percentage=bool(scope_item.config_snapshot.get("is_percentage", payload.get("is_percentage", False))),
            formula=formula,
            daily_aggregation=daily_aggregation,
            current_status=current_status,
            trend_status=trend_status,
        ),
        current=_bucket(
            data_date,
            current_value,
            [point for point in overall_points if _point_date(point) == data_date],
            result=result,
            numerator=current_numerator,
            denominator=current_denominator,
        ),
        previous=_bucket(
            previous_date,
            previous_value,
            [point for point in overall_points if _point_date(point) == previous_date],
            result=result,
            missing_status="no_baseline",
            numerator=previous_numerator,
            denominator=previous_denominator,
        ),
        change_value=_optional_number(result.get("change")),
        change_unit=change_unit,
        reason=str(result.get("reason") or "") or None,
        reason_codes=reason_codes,
        valid_count=int(result.get("effective_point_count") or 0),
        current_threshold=threshold,
        components=components,
        groups=_evidence_groups(
            points,
            result=result,
            data_date=data_date,
            current_value=current_value,
            previous_value=previous_value,
            current_status=current_status,
            trend_status=trend_status,
            daily_aggregation=daily_aggregation,
            derived_definition=derived_definition,
            numerator_points=numerator_points,
            denominator_points=denominator_points,
        ),
        seven_day_trend=_seven_day_trend(
            points,
            result=result,
            data_date=data_date,
            current_value=current_value,
            daily_aggregation=daily_aggregation,
            derived_definition=derived_definition,
            numerator_points=numerator_points,
            denominator_points=denominator_points,
        ),
        sources=_evidence_sources(
            scope_item,
            result,
            points,
            extra_points=[*numerator_points, *denominator_points],
        ),
        config_snapshot=schemas.KpiMetricConfigSnapshotV6(
            config_revision=config_revision if isinstance(config_revision, int) and config_revision >= 0 else None,
            config_fingerprint=config_fingerprint if isinstance(config_fingerprint, str) else None,
        ),
    )


def get_kpi_metric_technical_analysis(
    task_id: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    *,
    history_days: int = 90,
    version_limit: int = 10,
) -> schemas.KpiTechnicalAnalysisV6:
    """返回同设备已完成任务的指标历史；无设备身份时明确返回空集合。"""
    source = _source_or_raise(task_id)
    _metric_context(source, measurement_unit_id, metric_resource_id)
    task_summary = get_task_summary(task_id)
    generated_at = datetime.now(UTC).isoformat()
    if task_summary is None or not task_summary.device_id:
        return schemas.KpiTechnicalAnalysisV6(
            task_id=task_id,
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            generated_at=generated_at,
            cross_task_history=[],
            version_comparisons=[],
        )

    # 历史仍只按同一设备、网元类型、测量单元和指标身份读取；当前合成基线没有
    # device_id，因此保留空集合。具备真实设备身份时的版本接线由后续服务测试
    # 驱动，禁止退化为跨设备或跨测量单元聚合。
    history = _completed_metric_history(
        source,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        history_days=history_days,
        version_limit=version_limit,
        task_completed_before=task_summary.completed_at,
        device_id=task_summary.device_id,
        current_version=task_summary.customer_version,
    )
    return schemas.KpiTechnicalAnalysisV6(
        task_id=task_id,
        measurement_unit_id=measurement_unit_id,
        metric_resource_id=metric_resource_id,
        generated_at=generated_at,
        cross_task_history=history.cross_task_history,
        version_comparisons=history.version_comparisons,
    )


@dataclass(frozen=True, slots=True)
class _MetricHistory:
    cross_task_history: list[schemas.KpiHistoryPointV6]
    version_comparisons: list[schemas.KpiVersionComparisonV6]


def _completed_metric_history(
    source: KpiWorkbenchSourceData,
    *,
    measurement_unit_id: str,
    metric_resource_id: str,
    history_days: int,
    version_limit: int,
    task_completed_before: datetime | None,
    device_id: str,
    current_version: str | None,
) -> _MetricHistory:
    """读取同设备已完成任务的已发布点，按任务和系统版本生成稳定顺序。"""
    if task_completed_before is None:
        return _MetricHistory([], [])
    start_date = (source.data_date or task_completed_before.date()) - timedelta(days=history_days - 1)
    candidate_ids = list_previous_completed_task_ids(
        device_id,
        completed_before=task_completed_before,
        limit=max(history_days, version_limit * 5),
    )
    history: list[schemas.KpiHistoryPointV6] = []
    by_version: dict[str, list[schemas.KpiVersionComparisonV6]] = defaultdict(list)
    for candidate_id in candidate_ids:
        candidate_source = get_kpi_workbench_source_data(candidate_id)
        if candidate_source is None or not candidate_source.snapshot_present:
            continue
        if candidate_source.network_element_type != source.network_element_type:
            continue
        points = list_kpi_points_v6(
            candidate_id,
            network_element_type=candidate_source.network_element_type or "",
            measurement_unit_id=measurement_unit_id,
            metric_resource_id=metric_resource_id,
            start_at=datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
            end_at=task_completed_before,
        )
        if not points:
            continue
        latest_point = points[-1]
        measured_at = _point_datetime(latest_point)
        if measured_at is None:
            continue
        value = _optional_number(latest_point.get("value"))
        history.append(
            schemas.KpiHistoryPointV6(
                task_id=candidate_id,
                data_date=measured_at.date(),
                value=value,
                status="ok" if value is not None else "no_data",
            )
        )
        candidate_summary = get_task_summary(candidate_id)
        version = candidate_summary.customer_version if candidate_summary is not None else None
        if version and version != current_version:
            current_value = _optional_number(
                next(
                    (
                        item.get("today_value")
                        for item in candidate_source.metric_results
                        if str(item.get("measurement_unit_id")) == measurement_unit_id
                        and str(item.get("metric_resource_id")) == metric_resource_id
                    ),
                    None,
                )
            )
            by_version[version].append(
                schemas.KpiVersionComparisonV6(
                    task_id=candidate_id,
                    device_id=device_id,
                    version=version,
                    data_date=measured_at.date(),
                    current_value=current_value,
                    comparison_value=value,
                    change_value=(current_value - value if current_value is not None and value is not None else None),
                )
            )
    current_value = next(
        (
            _optional_number(item.get("today_value"))
            for item in source.metric_results
            if str(item.get("measurement_unit_id")) == measurement_unit_id
            and str(item.get("metric_resource_id")) == metric_resource_id
        ),
        None,
    )
    comparisons: list[schemas.KpiVersionComparisonV6] = []
    for _version, items in sorted(by_version.items(), key=lambda item: item[0]):
        candidate = sorted(items, key=lambda item: (item.data_date, item.task_id), reverse=True)[0]
        comparisons.append(
            candidate.model_copy(
                update={
                    "current_value": current_value,
                    "change_value": (
                        current_value - candidate.comparison_value
                        if current_value is not None and candidate.comparison_value is not None
                        else None
                    ),
                }
            )
        )
    history.sort(key=lambda item: (item.data_date, item.task_id))
    return _MetricHistory(history, comparisons[:version_limit])
