"""KPI 日健康纯业务判定。

本模块只处理已解析的时间点和维护配置，不读取数据库或任务现场。巡检器、
详情 API 与报告通过同一组函数生成当前判定和昨日趋势，避免展示层重复算法。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

UTC8 = timezone(timedelta(hours=8), name="Asia/Shanghai")
DEFAULT_PERCENTAGE_TOLERANCE_PP = 0.2
DEFAULT_RELATIVE_TOLERANCE_PERCENT = 5.0

CURRENT_STATUS_PRIORITY = (
    "fail",
    "warn",
    "unable_to_judge",
    "pending_config",
    "not_applicable",
    "normal",
)
TREND_STATUS_PRIORITY = ("worsened", "improved", "observe", "no_baseline", "stable")

CurrentStatus = Literal["normal", "warn", "fail", "pending_config", "unable_to_judge", "not_applicable"]
TrendStatus = Literal["improved", "stable", "worsened", "observe", "no_baseline"]
Direction = Literal["higher_better", "lower_better", "neutral"]
Aggregation = Literal["latest", "mean", "sum", "max", "min"]
ThresholdUnit = Literal["pp", "relative", "auto"]
ZeroSemantics = Literal["unknown", "expected_zero", "business_not_triggered"]


@dataclass(frozen=True)
class DailyPoint:
    """单个指标在某个对象、周期和时间上的有效点。"""

    object_key: str
    measured_at: datetime
    period_minutes: int | None
    value: float | None
    numerator: float | None = None
    denominator: float | None = None
    raw_value: float | None = None
    source_file: str | None = None
    unreadable: bool = False


@dataclass(frozen=True)
class MetricDailyHealthConfig:
    """生成日健康所需的指标配置快照。"""

    measurement_unit_id: str
    metric_resource_id: str
    name_zh: str
    role: Literal["base", "derived"] = "base"
    direction: Direction | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None
    daily_aggregation: Aggregation = "latest"
    daily_change_threshold: float | None = None
    daily_change_threshold_unit: ThresholdUnit = "auto"
    is_percentage: bool = False
    zero_semantics: ZeroSemantics = "unknown"
    consistency_tolerance: float = DEFAULT_PERCENTAGE_TOLERANCE_PP
    numerator_metric_id: str | None = None
    denominator_metric_id: str | None = None
    template: Literal["success_rate", "reverse_success_rate"] = "success_rate"
    config_source: Literal["custom", "default", "legacy_resource", "missing"] = "legacy_resource"
    enabled: bool = True
    importance: str | None = None
    display_unit: str | None = None
    measurement_unit_name_zh: str | None = None
    metric_resource_enabled: bool = True
    measurement_unit_enabled: bool = True
    binding_confirmed: bool = True
    object_match_mode: Literal["exact"] = "exact"


def date_in_utc8(value: datetime) -> date:
    """把测量时间转换到 UTC+8 自然日；无时区输入按现场本地时间处理。"""
    aware = value.replace(tzinfo=UTC8) if value.tzinfo is None else value.astimezone(UTC8)
    return aware.date()


def _iso_utc8(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC8) if value.tzinfo is None else value.astimezone(UTC8)
    return aware.isoformat()


def _as_number(value: float | int | None) -> float | None:
    return None if value is None else float(value)


def _deduplicate_points(points: Iterable[DailyPoint]) -> list[DailyPoint]:
    """同一对象/周期/时间重复行取有效值均值，保留全部来源文件。"""
    grouped: dict[tuple[str, int | None, datetime], list[DailyPoint]] = defaultdict(list)
    for point in points:
        measured_at = point.measured_at.replace(tzinfo=UTC8) if point.measured_at.tzinfo is None else point.measured_at
        normalized = DailyPoint(
            object_key=point.object_key,
            measured_at=measured_at,
            period_minutes=point.period_minutes,
            value=point.value,
            numerator=point.numerator,
            denominator=point.denominator,
            raw_value=point.raw_value,
            source_file=point.source_file,
            unreadable=point.unreadable,
        )
        grouped[(normalized.object_key, normalized.period_minutes, normalized.measured_at)].append(normalized)

    result: list[DailyPoint] = []
    for (_object_key, _period, _time), duplicates in grouped.items():
        values = [item.value for item in duplicates if item.value is not None]
        numerators = [item.numerator for item in duplicates if item.numerator is not None]
        denominators = [item.denominator for item in duplicates if item.denominator is not None]
        raw_values = [item.raw_value for item in duplicates if item.raw_value is not None]
        base = duplicates[0]
        result.append(
            DailyPoint(
                object_key=base.object_key,
                measured_at=base.measured_at,
                period_minutes=base.period_minutes,
                value=sum(values) / len(values) if values else None,
                numerator=sum(numerators) if numerators else None,
                denominator=sum(denominators) if denominators else None,
                raw_value=sum(raw_values) / len(raw_values) if raw_values else None,
                source_file=next((item.source_file for item in duplicates if item.source_file), None),
                unreadable=all(item.unreadable for item in duplicates),
            )
        )
    return sorted(
        result,
        key=lambda item: (item.object_key, item.period_minutes is None, item.period_minutes or 0, item.measured_at),
    )


def _bucket(
    *,
    bucket_date: date,
    value: float | None,
    numerator: float | None = None,
    denominator: float | None = None,
    valid_count: int = 0,
    points: Sequence[DailyPoint] = (),
    status: Literal["ok", "no_data", "zero_denominator", "unreadable", "no_baseline"] = "ok",
) -> dict[str, object]:
    times = [item.measured_at for item in points]
    return {
        "date": bucket_date,
        "value": None if value is None else round(value, 6),
        "numerator": None if numerator is None else round(numerator, 6),
        "denominator": None if denominator is None else round(denominator, 6),
        "valid_count": valid_count,
        "first_measured_at": min(times).astimezone(UTC8) if times else None,
        "last_measured_at": max(times).astimezone(UTC8) if times else None,
        "status": status,
    }


def aggregate_daily_bucket(
    points: Iterable[DailyPoint],
    aggregation: Aggregation,
    *,
    bucket_date: date | None = None,
) -> dict[str, object]:
    """按维护配置把同一对象/周期的点聚合为一个自然日值。"""
    deduplicated = _deduplicate_points(points)
    resolved_date = bucket_date or next((date_in_utc8(item.measured_at) for item in deduplicated), date.min)
    valid = [item for item in deduplicated if item.value is not None]
    if not valid:
        has_unreadable = any(item.unreadable for item in deduplicated)
        return _bucket(
            bucket_date=resolved_date,
            value=None,
            points=deduplicated,
            status="unreadable" if has_unreadable else "no_data",
        )

    values = [float(item.value) for item in valid if item.value is not None]
    if aggregation == "latest":
        aggregate_value = values[-1]
    elif aggregation == "sum":
        aggregate_value = sum(values)
    elif aggregation == "max":
        aggregate_value = max(values)
    elif aggregation == "min":
        aggregate_value = min(values)
    else:
        aggregate_value = sum(values) / len(values)
    return _bucket(
        bucket_date=resolved_date,
        value=aggregate_value,
        valid_count=len(valid),
        points=valid,
        status="ok",
    )


def _pair_derived_points(
    numerator_points: Iterable[DailyPoint],
    denominator_points: Iterable[DailyPoint],
) -> list[tuple[DailyPoint, DailyPoint]]:
    numerator_by_key = {
        (item.object_key, item.period_minutes, item.measured_at): item
        for item in _deduplicate_points(numerator_points)
        if item.value is not None
    }
    denominator_by_key = {
        (item.object_key, item.period_minutes, item.measured_at): item
        for item in _deduplicate_points(denominator_points)
        if item.value is not None
    }
    pairs = []
    for key in sorted(
        set(numerator_by_key) & set(denominator_by_key),
        key=lambda item: (item[0], item[1] is None, item[1] or 0, item[2]),
    ):
        pairs.append((numerator_by_key[key], denominator_by_key[key]))
    return pairs


def _derived_bucket(
    pairs: Sequence[tuple[DailyPoint, DailyPoint]],
    *,
    bucket_date: date,
    template: Literal["success_rate", "reverse_success_rate"],
) -> dict[str, object]:
    usable = [
        (numerator, denominator)
        for numerator, denominator in pairs
        if numerator.value is not None and denominator.value is not None
    ]
    source_points = [item for pair in usable for item in pair]
    if not usable:
        return _bucket(bucket_date=bucket_date, value=None, points=source_points, status="no_data")

    numerator_sum = sum(float(numerator.value) for numerator, _ in usable if numerator.value is not None)
    denominator_sum = sum(float(denominator.value) for _, denominator in usable if denominator.value is not None)
    if denominator_sum == 0:
        return _bucket(
            bucket_date=bucket_date,
            value=None,
            numerator=numerator_sum,
            denominator=denominator_sum,
            valid_count=len(usable),
            points=source_points,
            status="zero_denominator",
        )
    value = numerator_sum / denominator_sum * 100
    if template == "reverse_success_rate":
        value = 100 - value
    return _bucket(
        bucket_date=bucket_date,
        value=value,
        numerator=numerator_sum,
        denominator=denominator_sum,
        valid_count=len(usable),
        points=source_points,
        status="ok",
    )


def _status_rank(status: str, priority: Sequence[str]) -> int:
    try:
        return priority.index(status)
    except ValueError:
        return len(priority)


def aggregate_current_statuses(statuses: Iterable[str]) -> CurrentStatus:
    """按 fail > warn > 无法判定 > 待配置 > 不适用 > normal 聚合。"""
    values = list(statuses)
    if not values:
        return "unable_to_judge"
    return min(values, key=lambda status: _status_rank(status, CURRENT_STATUS_PRIORITY))  # type: ignore[return-value]


def aggregate_trend_statuses(statuses: Iterable[str]) -> TrendStatus:
    """按恶化 > 改善 > 观察 > 无基线 > 稳定聚合。"""
    values = list(statuses)
    if not values:
        return "no_baseline"
    return min(values, key=lambda status: _status_rank(status, TREND_STATUS_PRIORITY))  # type: ignore[return-value]


def judge_current_status(
    value: float | None,
    *,
    direction: Direction | None,
    warning_threshold: float | None,
    critical_threshold: float | None,
    valid_count: int,
    denominator: float | None = None,
    all_zero: bool = False,
    zero_semantics: ZeroSemantics = "unknown",
    unreadable: bool = False,
) -> tuple[CurrentStatus, str]:
    """根据有效值、方向、阈值和零值语义生成当前判定。"""
    if denominator is not None and denominator == 0:
        return "not_applicable", "zero_denominator"
    if valid_count <= 0 or unreadable:
        return "unable_to_judge", "data_unreadable" if unreadable else "no_current_data"
    if value is None:
        return "unable_to_judge", "dependency_missing"
    if all_zero and zero_semantics == "unknown":
        return "pending_config", "all_zero_unconfirmed"
    if all_zero and zero_semantics == "business_not_triggered":
        return "not_applicable", "business_not_triggered"
    if direction not in {"higher_better", "lower_better"}:
        return "pending_config", "direction_missing"
    if warning_threshold is None and critical_threshold is None:
        return "pending_config", "threshold_missing"

    if direction == "higher_better":
        if critical_threshold is not None and value <= critical_threshold:
            return "fail", "critical_threshold"
        if warning_threshold is not None and value <= warning_threshold:
            return "warn", "warning_threshold"
    else:
        if critical_threshold is not None and value >= critical_threshold:
            return "fail", "critical_threshold"
        if warning_threshold is not None and value >= warning_threshold:
            return "warn", "warning_threshold"
    return "normal", "threshold_satisfied"


def classify_daily_trend(
    today_value: float | None,
    yesterday_value: float | None,
    *,
    direction: Direction | None,
    is_percentage: bool,
    change_threshold: float | None,
    change_threshold_unit: ThresholdUnit = "auto",
) -> dict[str, object]:
    """比较同对象、同周期的今日/昨日日值并应用方向和容差。"""
    if today_value is None or yesterday_value is None:
        return {
            "status": "no_baseline",
            "reason_code": "no_baseline",
            "delta": None,
            "delta_percent": None,
            "unit": "unavailable",
            "threshold": change_threshold,
            "threshold_source": "custom" if change_threshold is not None else "default",
            "reason": "无昨日同对象同周期有效基线",
        }

    if direction is None:
        return {
            "status": "no_baseline",
            "reason_code": "direction_missing",
            "delta": round(today_value - yesterday_value, 6),
            "delta_percent": None,
            "unit": "unavailable",
            "threshold": change_threshold,
            "threshold_source": "custom" if change_threshold is not None else "default",
            "reason": "指标缺少方向，无法判断趋势",
        }

    delta = today_value - yesterday_value
    resolved_unit: Literal["pp", "relative", "unavailable"]
    if change_threshold_unit == "auto":
        resolved_unit = "pp" if is_percentage else "relative"
    else:
        resolved_unit = change_threshold_unit
    configured_threshold = change_threshold
    if resolved_unit == "pp":
        tolerance = DEFAULT_PERCENTAGE_TOLERANCE_PP if configured_threshold is None else configured_threshold
        exceeds_tolerance = abs(delta) > tolerance
        threshold_source = "custom" if configured_threshold is not None else "default"
        delta_percent = None
        reason_unit = "pp"
    elif resolved_unit == "relative":
        tolerance = DEFAULT_RELATIVE_TOLERANCE_PERCENT if configured_threshold is None else configured_threshold
        if yesterday_value == 0:
            exceeds_tolerance = today_value != yesterday_value
            delta_percent = None
        else:
            delta_percent = delta / abs(yesterday_value) * 100
            exceeds_tolerance = abs(delta_percent) > tolerance
        threshold_source = "custom" if configured_threshold is not None else "default"
        reason_unit = "%"
    else:
        tolerance = configured_threshold
        exceeds_tolerance = delta != 0
        delta_percent = None
        threshold_source = "custom"
        reason_unit = "unavailable"

    if not exceeds_tolerance:
        status: TrendStatus = "stable"
        reason_code = "within_tolerance"
        reason = f"变化在容差内（{reason_unit}）"
    elif direction == "higher_better":
        status = "improved" if delta > 0 else "worsened"
        reason_code = status
        reason = f"高于昨日 {abs(delta):.6g}{reason_unit}" if delta > 0 else f"低于昨日 {abs(delta):.6g}{reason_unit}"
    elif direction == "lower_better":
        status = "improved" if delta < 0 else "worsened"
        reason_code = status
        reason = f"低于昨日 {abs(delta):.6g}{reason_unit}" if delta < 0 else f"高于昨日 {abs(delta):.6g}{reason_unit}"
    else:
        status = "observe"
        reason_code = "direction_neutral"
        reason = "方向中性且变化超过容差，仅提示观察"

    return {
        "status": status,
        "reason_code": reason_code,
        "delta": round(delta, 6),
        "delta_percent": None if delta_percent is None else round(delta_percent, 6),
        "unit": resolved_unit,
        "threshold": tolerance,
        "threshold_source": threshold_source,
        "reason": reason,
    }


def _change_threshold(
    config: MetricDailyHealthConfig,
) -> dict[str, object]:
    if config.daily_change_threshold_unit == "auto":
        unit = "pp" if config.is_percentage else "relative"
    else:
        unit = config.daily_change_threshold_unit
    value = config.daily_change_threshold
    if value is None:
        value = (
            DEFAULT_PERCENTAGE_TOLERANCE_PP
            if unit == "pp"
            else (DEFAULT_RELATIVE_TOLERANCE_PERCENT if unit == "relative" else None)
        )
    return {
        "value": value,
        "unit": unit,
        "source": "custom" if config.daily_change_threshold is not None else "default",
    }


def _threshold_evidence(config: MetricDailyHealthConfig) -> dict[str, object]:
    missing = config.direction is None and config.warning_threshold is None and config.critical_threshold is None
    return {
        "direction": config.direction,
        "warning_threshold": config.warning_threshold,
        "critical_threshold": config.critical_threshold,
        "source": "missing" if missing else config.config_source,
    }


def _consistency_evidence(
    config: MetricDailyHealthConfig,
    pairs: Sequence[tuple[DailyPoint, DailyPoint]],
    template: Literal["success_rate", "reverse_success_rate"],
) -> dict[str, object]:
    raw_pairs = [
        (numerator, denominator)
        for numerator, denominator in pairs
        if numerator.raw_value is not None
        and numerator.value is not None
        and denominator.value is not None
        and denominator.value > 0
    ]
    if config.role != "derived":
        return {
            "status": "not_checked",
            "tolerance_pp": config.consistency_tolerance,
            "difference_pp": None,
        }
    if not raw_pairs:
        return {
            "status": "unavailable",
            "tolerance_pp": config.consistency_tolerance,
            "difference_pp": None,
        }

    raw_weighted = sum(
        float(numerator.raw_value) * float(denominator.value)
        for numerator, denominator in raw_pairs
        if numerator.raw_value is not None and denominator.value is not None
    ) / sum(float(denominator.value) for _, denominator in raw_pairs if denominator.value is not None)
    numerator_sum = sum(float(numerator.value) for numerator, _ in raw_pairs if numerator.value is not None)
    denominator_sum = sum(float(denominator.value) for _, denominator in raw_pairs if denominator.value is not None)
    calculated = numerator_sum / denominator_sum * 100
    if template == "reverse_success_rate":
        calculated = 100 - calculated
    difference = abs(raw_weighted - calculated)
    return {
        "status": "within_tolerance" if difference <= config.consistency_tolerance else "exceeded",
        "tolerance_pp": config.consistency_tolerance,
        "difference_pp": round(difference, 6),
    }


def _group_key(point: DailyPoint) -> tuple[str, int | None]:
    return point.object_key, point.period_minutes


def _group_points(points: Iterable[DailyPoint]) -> dict[tuple[str, int | None], list[DailyPoint]]:
    grouped: dict[tuple[str, int | None], list[DailyPoint]] = defaultdict(list)
    for point in _deduplicate_points(points):
        grouped[_group_key(point)].append(point)
    return grouped


def _sorted_group_keys(keys: Iterable[tuple[str, int | None]]) -> list[tuple[str, int | None]]:
    return sorted(keys, key=lambda item: (item[0], item[1] is None, item[1] or 0))


def _source_files(points: Iterable[DailyPoint]) -> list[str]:
    return sorted({item.source_file for item in points if item.source_file})


def _latest_date(points: Iterable[DailyPoint]) -> date | None:
    valid = [item.measured_at for item in points if item.value is not None and not item.unreadable]
    return date_in_utc8(max(valid)) if valid else None


def _group_reason(
    today: dict[str, object],
    status: CurrentStatus,
    reason: str,
) -> str:
    if today["status"] == "zero_denominator":
        return "当日分母为 0，指标不适用"
    if today["status"] == "no_data":
        return "当对象/周期无有效数据"
    if today["status"] == "unreadable":
        return "当对象/周期数据不可读"
    if status == "normal":
        return "有效组满足阈值"
    if status == "pending_config":
        labels = {
            "all_zero_unconfirmed": "全零语义待确认",
            "direction_missing": "缺少指标方向",
            "threshold_missing": "缺少业务阈值",
            "aggregation_missing": "缺少日聚合方式",
            "consistency_exceeded": "原始成功率与重算值超出容差",
        }
        return labels.get(reason, "指标维护配置不完整")
    if status == "warn":
        return "触发预警阈值"
    if status == "fail":
        return "触发失败阈值"
    if status == "not_applicable":
        return "明确配置为业务未触发"
    return "缺少有效数据或依赖"


def _base_group_result(
    config: MetricDailyHealthConfig,
    points: Sequence[DailyPoint],
    *,
    data_date: date,
    previous_date: date,
) -> dict[str, object]:
    today_points = [item for item in points if date_in_utc8(item.measured_at) == data_date]
    yesterday_points = [item for item in points if date_in_utc8(item.measured_at) == previous_date]
    today = aggregate_daily_bucket(today_points, config.daily_aggregation, bucket_date=data_date)
    yesterday = (
        aggregate_daily_bucket(yesterday_points, config.daily_aggregation, bucket_date=previous_date)
        if yesterday_points
        else None
    )
    today_value = today["value"] if isinstance(today["value"], (int, float)) else None
    yesterday_value = (
        yesterday["value"] if yesterday is not None and isinstance(yesterday["value"], (int, float)) else None
    )
    valid_values = [float(item.value) for item in today_points if item.value is not None]
    all_zero = bool(valid_values) and all(value == 0 for value in valid_values)
    status, reason = judge_current_status(
        today_value,
        direction=config.direction,
        warning_threshold=config.warning_threshold,
        critical_threshold=config.critical_threshold,
        valid_count=int(today["valid_count"]),
        all_zero=all_zero,
        zero_semantics=config.zero_semantics,
        unreadable=today["status"] == "unreadable",
    )
    trend = classify_daily_trend(
        today_value,
        yesterday_value,
        direction=config.direction,
        is_percentage=config.is_percentage,
        change_threshold=config.daily_change_threshold,
        change_threshold_unit=config.daily_change_threshold_unit,
    )
    return {
        "object_key": next(iter(points)).object_key,
        "period_minutes": next(iter(points)).period_minutes,
        "today": today,
        "yesterday": yesterday,
        "current_status": status,
        "current_reason_code": reason,
        "trend_status": trend["status"],
        "trend_reason_code": trend["reason_code"],
        "trend_reason": trend["reason"],
        "reason": _group_reason(today, status, reason),
        "source_files": _source_files(points),
    }


def _derived_group_result(
    config: MetricDailyHealthConfig,
    pairs: Sequence[tuple[DailyPoint, DailyPoint]],
    *,
    data_date: date,
    previous_date: date,
) -> dict[str, object]:
    today_pairs = [pair for pair in pairs if date_in_utc8(pair[0].measured_at) == data_date]
    yesterday_pairs = [pair for pair in pairs if date_in_utc8(pair[0].measured_at) == previous_date]
    today = _derived_bucket(today_pairs, bucket_date=data_date, template=config.template)
    yesterday = (
        _derived_bucket(yesterday_pairs, bucket_date=previous_date, template=config.template)
        if yesterday_pairs
        else None
    )
    today_value = today["value"] if isinstance(today["value"], (int, float)) else None
    yesterday_value = (
        yesterday["value"] if yesterday is not None and isinstance(yesterday["value"], (int, float)) else None
    )
    all_zero = bool(today_pairs) and all(
        float(numerator.value or 0) == 0 and float(denominator.value or 0) == 0
        for numerator, denominator in today_pairs
    )
    missing_dependency = bool(
        (config.numerator_metric_id is None or config.denominator_metric_id is None)
        or (not pairs and (config.numerator_metric_id or config.denominator_metric_id))
    )
    if missing_dependency:
        status, reason = "unable_to_judge", "dependency_missing"
    else:
        status, reason = judge_current_status(
            today_value,
            direction=config.direction,
            warning_threshold=config.warning_threshold,
            critical_threshold=config.critical_threshold,
            valid_count=int(today["valid_count"]),
            denominator=(float(today["denominator"]) if isinstance(today["denominator"], (int, float)) else None),
            all_zero=all_zero,
            zero_semantics=config.zero_semantics,
            unreadable=today["status"] == "unreadable",
        )
    consistency = _consistency_evidence(config, today_pairs, config.template)
    if consistency["status"] == "exceeded" and status == "normal":
        status = "pending_config"
        reason = "consistency_exceeded"
    trend = classify_daily_trend(
        today_value,
        yesterday_value,
        direction=config.direction,
        is_percentage=config.is_percentage,
        change_threshold=config.daily_change_threshold,
        change_threshold_unit=config.daily_change_threshold_unit,
    )
    source_points = [item for pair in pairs for item in pair]
    first = pairs[0][0] if pairs else None
    return {
        "object_key": first.object_key if first else "unknown",
        "period_minutes": first.period_minutes if first else None,
        "today": today,
        "yesterday": yesterday,
        "current_status": status,
        "current_reason_code": reason,
        "trend_status": trend["status"],
        "trend_reason_code": trend["reason_code"],
        "trend_reason": trend["reason"],
        "reason": _group_reason(today, status, reason),
        "source_files": _source_files(source_points),
    }


def build_metric_daily_health(
    config: MetricDailyHealthConfig,
    points: Iterable[DailyPoint],
    *,
    numerator_points: Iterable[DailyPoint] | None = None,
    denominator_points: Iterable[DailyPoint] | None = None,
    raw_rate_points: Iterable[DailyPoint] | None = None,
    anchor_date: date | None = None,
) -> dict[str, object]:
    """生成单指标当前判定、对象/周期证据和最近 7 日聚合趋势。"""
    base_points = _deduplicate_points(points)
    numerator_values = _deduplicate_points(numerator_points or [])
    denominator_values = _deduplicate_points(denominator_points or [])
    raw_values = _deduplicate_points(raw_rate_points or [])

    if config.role == "derived":
        pairs = _pair_derived_points(numerator_values, denominator_values)
        if raw_values:
            raw_by_key = {(item.object_key, item.period_minutes, item.measured_at): item for item in raw_values}
            enriched_pairs: list[tuple[DailyPoint, DailyPoint]] = []
            for numerator, denominator in pairs:
                raw = raw_by_key.get((numerator.object_key, numerator.period_minutes, numerator.measured_at))
                if raw is not None:
                    numerator = DailyPoint(
                        object_key=numerator.object_key,
                        measured_at=numerator.measured_at,
                        period_minutes=numerator.period_minutes,
                        value=numerator.value,
                        numerator=numerator.numerator,
                        denominator=numerator.denominator,
                        raw_value=raw.value,
                        source_file=numerator.source_file,
                        unreadable=numerator.unreadable,
                    )
                enriched_pairs.append((numerator, denominator))
            pairs = enriched_pairs
        all_points = [item for pair in pairs for item in pair]
    else:
        pairs = []
        all_points = base_points

    resolved_date = anchor_date or _latest_date([*all_points, *numerator_values, *denominator_values, *raw_values])
    if resolved_date is None:
        raise ValueError("无法确定日健康数据日期：请提供锚点日期或至少一个有效测量时间")
    previous_date = resolved_date - timedelta(days=1)

    if config.role == "derived":
        pair_groups: dict[tuple[str, int | None], list[tuple[DailyPoint, DailyPoint]]] = defaultdict(list)
        for pair in pairs:
            pair_groups[_group_key(pair[0])].append(pair)
        groups = [
            _derived_group_result(config, pair_groups[key], data_date=resolved_date, previous_date=previous_date)
            for key in _sorted_group_keys(pair_groups)
        ]
        if not groups:
            group_key = "unknown"
            no_data_group = {
                "object_key": group_key,
                "period_minutes": None,
                "today": _bucket(bucket_date=resolved_date, value=None, status="no_data"),
                "yesterday": None,
                "current_status": "unable_to_judge",
                "current_reason_code": "dependency_missing",
                "trend_status": "no_baseline",
                "trend_reason_code": "no_baseline",
                "reason": "派生依赖无有效对象/周期数据",
                "source_files": [],
            }
            groups = [no_data_group]
        consistency = _consistency_evidence(config, pairs, config.template)
    else:
        point_groups = _group_points(base_points)
        groups = [
            _base_group_result(
                config,
                point_groups[key],
                data_date=resolved_date,
                previous_date=previous_date,
            )
            for key in _sorted_group_keys(point_groups)
        ]
        if not groups:
            groups = [
                {
                    "object_key": "unknown",
                    "period_minutes": None,
                    "today": _bucket(bucket_date=resolved_date, value=None, status="no_data"),
                    "yesterday": None,
                    "current_status": "unable_to_judge",
                    "current_reason_code": "no_current_data",
                    "trend_status": "no_baseline",
                    "trend_reason_code": "no_baseline",
                    "reason": "无有效对象/周期数据",
                    "source_files": [],
                }
            ]
        consistency = _consistency_evidence(config, [], config.template)

    metric_status = aggregate_current_statuses(str(group["current_status"]) for group in groups)
    metric_trend = aggregate_trend_statuses(str(group["trend_status"]) for group in groups)
    primary_current_group = next(
        (group for group in groups if group["current_status"] == metric_status),
        groups[0],
    )
    primary_trend_group = next(
        (group for group in groups if group["trend_status"] == metric_trend),
        groups[0],
    )
    change_threshold = _change_threshold(config)
    aggregation = "formula" if config.role == "derived" else config.daily_aggregation
    formula = (
        "numerator_sum / denominator_sum * 100"
        if config.role == "derived" and config.template == "success_rate"
        else "100 - numerator_sum / denominator_sum * 100"
        if config.role == "derived"
        else None
    )

    seven_day_trend = []
    for offset in range(6, -1, -1):
        day = resolved_date - timedelta(days=offset)
        if config.role == "derived":
            day_pairs = [pair for pair in pairs if date_in_utc8(pair[0].measured_at) == day]
            if day_pairs:
                bucket = _derived_bucket(day_pairs, bucket_date=day, template=config.template)
            else:
                bucket = _bucket(bucket_date=day, value=None, status="no_data")
        else:
            day_points = [item for item in base_points if date_in_utc8(item.measured_at) == day]
            bucket = aggregate_daily_bucket(day_points, config.daily_aggregation, bucket_date=day)
        seven_day_trend.append(bucket)

    return {
        "metric": {
            "name_zh": config.name_zh,
            "role": config.role,
            "is_percentage": config.is_percentage,
            "data_date": resolved_date,
            "previous_date": previous_date,
            "daily_aggregation": aggregation,
            "formula": formula,
            "current_status": metric_status,
            "current_reason_code": primary_current_group.get("current_reason_code"),
            "current_reason": primary_current_group.get("reason"),
            "trend_status": metric_trend,
            "trend_reason_code": primary_trend_group.get("trend_reason_code"),
            "trend_reason": primary_trend_group.get("trend_reason"),
            "current_threshold": _threshold_evidence(config),
            "change_threshold": change_threshold,
            "consistency": consistency,
        },
        "groups": groups,
        "seven_day_trend": seven_day_trend,
        "legacy_fallback": None,
    }


def current_counts(metrics: Iterable[dict[str, object]]) -> dict[str, int]:
    """统计指标级当前判定，供页面和报告直接展示。"""
    counts = {status: 0 for status in CURRENT_STATUS_PRIORITY}
    for metric in metrics:
        status = str(metric.get("current_status", "unable_to_judge"))
        counts[status if status in counts else "unable_to_judge"] += 1
    return counts


def trend_counts(metrics: Iterable[dict[str, object]]) -> dict[str, int]:
    """统计指标级昨日趋势，供页面和报告直接展示。"""
    counts = {status: 0 for status in TREND_STATUS_PRIORITY}
    for metric in metrics:
        status = str(metric.get("trend_status", "no_baseline"))
        counts[status if status in counts else "no_baseline"] += 1
    return counts
