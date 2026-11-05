"""为 KPI 日健康 E2E 准备固定、可重复的测量单元与任务现场。"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.inspectors.kpi.measurement import inspector
from app.models.db import (
    KpiMeasurementBinding,
    KpiMeasurementDerived,
    KpiMeasurementResource,
    KpiMetricMaintenanceConfig,
    init_db,
    session_factory,
)
from app.models.schemas import (
    InspectionTask,
    RuleResult,
    RuleStatus,
    Summary,
    SystemInspection,
    TaskStats,
)
from app.services import task_db
from app.services.executor import make_result
from app.services.kpi_daily_health import UTC8
from app.services.kpi_daily_health_snapshot import build_daily_health_snapshot
from app.services.store import save_rule_result, save_system, save_task_meta

TASK_ID = "task-kpi-daily-health"
LEGACY_TASK_ID = "task-kpi-daily-health-legacy"
RULE_CODE = "kpi.measurement_units"
RATE_ID = "ME_HEALTH_RATE_1"
RATE_UNIT = "MU_HEALTH_CALL"
DATA_DATE = datetime(2026, 11, 5, 10, 0, tzinfo=UTC8)
CREATED_AT = datetime(2026, 11, 5, 1, 50, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 11, 5, 2, 10, tzinfo=UTC)
CATALOG_TIME = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
DEVICE_ID = "kpi-health-device-e2e"

ENABLED_UNITS = [
    ("MU_CALL", "呼叫统计", "Call Statistics", "Call_Statistics"),
    ("MU_HEALTH_CALL", "健康呼叫统计", "Health Call Statistics", "Health_Call"),
    ("MU_HEALTH_SIGNAL", "健康信令统计", "Health Signal Statistics", "Health_Signal"),
    ("MU_HEALTH_MEDIA", "健康媒体统计", "Health Media Statistics", "Health_Media"),
]
DISABLED_UNITS = [
    ("MU_DISABLED_E2E", "停用测量单元 E2E", "Disabled E2E Unit", "Disabled_E2E"),
]

# metric_id, name_zh, name_en, direction, warning, critical, importance, values(day_offset, value)
BASE_METRICS = [
    ("MU_CALL", "ME_CALL", "呼叫请求次数", "Call Requests", "higher_better", 90.0, 80.0, "P1", [(0, 110), (1, 100)]),
    (
        "MU_CALL",
        "ME_MAX_USERS",
        "最大注册用户数",
        "Max Registered Users",
        "higher_better",
        2000.0,
        1500.0,
        "P1",
        [(0, 2048), (1, 2048)],
    ),
    (
        "MU_CALL",
        "ME_HEALTH_CALL_VOLUME",
        "呼叫业务量",
        "Call Volume",
        "neutral",
        None,
        None,
        "normal",
        [(0, 120), (1, 100)],
    ),
    (
        "MU_CALL",
        "ME_HEALTH_REGISTERED_USERS",
        "登记用户规模",
        "Registered User Scale",
        None,
        None,
        None,
        "normal",
        [(0, 1000), (1, 1000)],
    ),
    (
        "MU_CALL",
        "ME_HEALTH_RESOURCE_POOL",
        "资源池占用",
        "Resource Pool Usage",
        "lower_better",
        10.0,
        20.0,
        "normal",
        [(0, 9), (1, 10)],
    ),
    ("MU_CALL", "ME_HEALTH_ALARM_COUNT", "告警数量", "Alarm Count", "lower_better", 10.0, 20.0, "P2", []),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_LATENCY",
        "呼叫建立时延",
        "Call Setup Latency",
        "lower_better",
        60.0,
        80.0,
        "P1",
        [(0, 50), (1, 62)],
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_ERRORS",
        "呼叫错误次数",
        "Call Errors",
        "lower_better",
        10.0,
        20.0,
        "P1",
        [(0, 15), (1, 12)],
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_CONCURRENCY",
        "呼叫并发数",
        "Call Concurrency",
        "higher_better",
        85.0,
        75.0,
        "normal",
        [(0, 96), (1, 96)],
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_RECOVERY",
        "呼叫恢复次数",
        "Call Recoveries",
        "higher_better",
        85.0,
        75.0,
        "P2",
        [(0, 91), (1, 105)],
    ),
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_CALL_QUALITY",
        "呼叫质量样本",
        "Call Quality Samples",
        "higher_better",
        95.0,
        85.0,
        "normal",
        [(0, 0), (1, 0)],
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_SIGNAL_DROPS",
        "信令丢弃次数",
        "Signal Drops",
        "lower_better",
        10.0,
        20.0,
        "P1",
        [(0, 5), (1, 7)],
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_SIGNAL_LOAD",
        "信令负载",
        "Signal Load",
        "neutral",
        None,
        None,
        "normal",
        [(0, 80), (1, 70)],
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_SIGNAL_LATENCY",
        "信令处理时延",
        "Signal Processing Latency",
        "lower_better",
        30.0,
        50.0,
        "normal",
        [(0, 25), (1, 25)],
    ),
    (
        "MU_HEALTH_MEDIA",
        "ME_HEALTH_MEDIA_LATENCY",
        "媒体处理时延",
        "Media Processing Latency",
        "lower_better",
        30.0,
        50.0,
        "normal",
        [(0, 20), (1, 20)],
    ),
    (
        "MU_HEALTH_MEDIA",
        "ME_HEALTH_MEDIA_QUEUE",
        "媒体队列深度",
        "Media Queue Depth",
        "lower_better",
        100.0,
        200.0,
        "P2",
        [(0, 80), (1, 90)],
    ),
]

RATE_METRICS = [
    (
        "MU_HEALTH_CALL",
        "ME_HEALTH_RATE_1",
        "媒体资源创建成功率",
        "Media Resource Creation Success Rate",
        80.0,
        70.0,
        "P1",
    ),
    (
        "MU_HEALTH_SIGNAL",
        "ME_HEALTH_RATE_2",
        "媒体资源创建请求成功率",
        "Media Resource Request Success Rate",
        90.0,
        80.0,
        "P1",
    ),
    ("MU_HEALTH_MEDIA", "ME_HEALTH_RATE_3", "DC 资源更新成功率", "DC Resource Update Success Rate", 85.0, 75.0, "P1"),
    (
        "MU_HEALTH_MEDIA",
        "ME_HEALTH_RATE_4",
        "数据通道资源更新请求成功率",
        "Data Channel Update Request Success Rate",
        75.0,
        60.0,
        "P1",
    ),
]

RATE_DEPENDENCIES = {
    "ME_HEALTH_RATE_1": ("ME_HEALTH_RATE_1_NUMERATOR", "ME_HEALTH_RATE_1_DENOMINATOR"),
    "ME_HEALTH_RATE_2": ("ME_HEALTH_RATE_2_NUMERATOR", "ME_HEALTH_RATE_2_DENOMINATOR"),
    "ME_HEALTH_RATE_3": ("ME_HEALTH_RATE_3_NUMERATOR", "ME_HEALTH_RATE_3_DENOMINATOR"),
    "ME_HEALTH_RATE_4": ("ME_HEALTH_RATE_4_NUMERATOR", "ME_HEALTH_RATE_4_DENOMINATOR"),
}

RATE_DEPENDENCY_NAMES = {
    "ME_HEALTH_RATE_1_NUMERATOR": "媒体资源创建成功率分子",
    "ME_HEALTH_RATE_1_DENOMINATOR": "媒体资源创建成功率分母",
    "ME_HEALTH_RATE_2_NUMERATOR": "媒体资源创建请求成功率分子",
    "ME_HEALTH_RATE_2_DENOMINATOR": "媒体资源创建请求成功率分母",
    "ME_HEALTH_RATE_3_NUMERATOR": "DC 资源更新成功率分子",
    "ME_HEALTH_RATE_3_DENOMINATOR": "DC 资源更新成功率分母",
    "ME_HEALTH_RATE_4_NUMERATOR": "数据通道资源更新请求成功率分子",
    "ME_HEALTH_RATE_4_DENOMINATOR": "数据通道资源更新请求成功率分母",
}

RATE_VALUES = {
    # 7 日完整证据；今日固定为 129 / 200 = 64.5%，昨日为 150 / 200 = 75%。
    "ME_HEALTH_RATE_1": [
        (6, 122, 200, 61.0),
        (5, 132, 200, 66.0),
        (4, 140, 200, 70.0),
        (3, 128, 200, 64.0),
        (2, 145, 200, 72.5),
        (1, 150, 200, 75.0),
        (0, 129, 200, 64.5),
    ],
    "ME_HEALTH_RATE_2": [(0, 0, 0, 0.0), (1, 0, 0, 0.0)],
    "ME_HEALTH_RATE_3": [(0, 90, 100, 90.0), (1, 88, 100, 88.0)],
    "ME_HEALTH_RATE_4": [(0, 70, 100, 70.0), (1, 65, 100, 65.0)],
}


def _at(day_offset: int) -> datetime:
    return DATA_DATE - timedelta(days=day_offset)


def _source_file(unit_id: str) -> str:
    return f"ne333_{unit_id}_15_0_20261105100000.csv"


def _upsert_resource(
    session: Any,
    *,
    resource_id: str,
    kind: str,
    name_zh: str,
    name_en: str,
    enabled: bool,
    display_order: int,
    fragment: str | None = None,
    direction: str | None = None,
    warning_threshold: float | None = None,
    critical_threshold: float | None = None,
    importance: str | None = None,
) -> None:
    row = session.get(KpiMeasurementResource, resource_id)
    if row is None:
        row = KpiMeasurementResource(resource_id=resource_id, created_at=CATALOG_TIME, updated_at=CATALOG_TIME)
        session.add(row)
    row.kind = kind
    row.name_zh = name_zh
    row.name_en = name_en
    row.filename_fragment = fragment
    row.enabled = enabled
    row.display_order = display_order
    row.metric_group = "日健康 E2E"
    row.direction = direction
    row.importance = importance
    row.warning_threshold = warning_threshold
    row.critical_threshold = critical_threshold
    row.source = "preset"
    row.updated_at = CATALOG_TIME


def _upsert_binding(
    session: Any,
    unit_id: str,
    metric_id: str,
    *,
    source_file: str,
    raw_name: str | None = None,
) -> None:
    expected_raw_name = raw_name or metric_id
    bindings = (
        session.query(KpiMeasurementBinding)
        .filter_by(measurement_unit_id=unit_id, metric_resource_id=metric_id)
        .order_by(KpiMeasurementBinding.id)
        .all()
    )
    binding = next((row for row in bindings if row.raw_source_name == expected_raw_name), None)
    if binding is None and bindings:
        binding = bindings[0]
    if binding is None:
        binding = KpiMeasurementBinding(
            measurement_unit_id=unit_id,
            raw_source_name=expected_raw_name,
            created_at=CATALOG_TIME,
            updated_at=CATALOG_TIME,
        )
        session.add(binding)
        bindings = [binding]
    # 其他 E2E 种子可能先发现同一指标的中文列名；统一收敛到一条 confirmed 绑定，
    # 避免维护配置列表按绑定行重复展示同一个 metric_resource_id。
    for duplicate in bindings:
        if duplicate is binding:
            continue
        duplicate.status = "candidate"
        duplicate.enabled = False
        duplicate.updated_at = CATALOG_TIME
    binding.raw_source_name = expected_raw_name
    binding.metric_resource_id = metric_id
    binding.base_source_name = expected_raw_name
    binding.display_unit = "%" if metric_id in RATE_DEPENDENCIES else None
    binding.status = "confirmed"
    binding.enabled = True
    binding.task_id = TASK_ID
    binding.source_file = source_file
    binding.updated_at = CATALOG_TIME


def _upsert_derived(session: Any, unit_id: str, metric_id: str) -> None:
    row = (
        session.query(KpiMeasurementDerived)
        .filter_by(measurement_unit_id=unit_id, metric_resource_id=metric_id)
        .first()
    )
    numerator_id, denominator_id = RATE_DEPENDENCIES[metric_id]
    if row is None:
        row = KpiMeasurementDerived(
            measurement_unit_id=unit_id,
            metric_resource_id=metric_id,
            created_at=CATALOG_TIME,
            updated_at=CATALOG_TIME,
        )
        session.add(row)
    row.numerator_metric_id = numerator_id
    row.denominator_metric_id = denominator_id
    row.template = "success_rate"
    row.enabled = True
    row.updated_at = CATALOG_TIME


def _upsert_config(session: Any, unit_id: str, metric_id: str, *, derived: bool = False) -> None:
    row = (
        session.query(KpiMetricMaintenanceConfig)
        .filter_by(measurement_unit_id=unit_id, metric_resource_id=metric_id)
        .first()
    )
    if row is None:
        row = KpiMetricMaintenanceConfig(
            measurement_unit_id=unit_id,
            metric_resource_id=metric_id,
            created_at=CATALOG_TIME,
            updated_at=CATALOG_TIME,
        )
        session.add(row)
    row.role = "derived" if derived else "base"
    row.daily_aggregation = "sum" if derived else "latest"
    row.daily_change_threshold = 0.2 if derived else None
    row.daily_change_threshold_unit = "pp" if derived else "auto"
    row.is_percentage = derived
    row.zero_semantics = "unknown"
    row.consistency_tolerance = 0.2
    row.object_match_mode = "exact"
    row.updated_at = CATALOG_TIME


def _seed_catalog() -> None:
    with session_factory() as session:
        display_order = 1
        for unit_id, name_zh, name_en, fragment in ENABLED_UNITS:
            _upsert_resource(
                session,
                resource_id=unit_id,
                kind="mu",
                name_zh=name_zh,
                name_en=name_en,
                enabled=True,
                display_order=display_order,
                fragment=fragment,
            )
            display_order += 1
        for unit_id, name_zh, name_en, fragment in DISABLED_UNITS:
            _upsert_resource(
                session,
                resource_id=unit_id,
                kind="mu",
                name_zh=name_zh,
                name_en=name_en,
                enabled=False,
                display_order=display_order,
                fragment=fragment,
            )
            display_order += 1

        for unit_id, metric_id, name_zh, name_en, direction, warning, critical, importance, _ in BASE_METRICS:
            _upsert_resource(
                session,
                resource_id=metric_id,
                kind="me",
                name_zh=name_zh,
                name_en=name_en,
                enabled=True,
                display_order=display_order,
                direction=direction,
                warning_threshold=warning,
                critical_threshold=critical,
                importance=importance,
            )
            _upsert_binding(session, unit_id, metric_id, source_file=_source_file(unit_id))
            _upsert_config(session, unit_id, metric_id)
            display_order += 1

        for unit_id, metric_id, name_zh, name_en, warning, critical, importance in RATE_METRICS:
            _upsert_resource(
                session,
                resource_id=metric_id,
                kind="me",
                name_zh=name_zh,
                name_en=name_en,
                enabled=True,
                display_order=display_order,
                direction="higher_better",
                warning_threshold=warning,
                critical_threshold=critical,
                importance=importance,
            )
            _upsert_binding(session, unit_id, metric_id, source_file=_source_file(unit_id))
            _upsert_derived(session, unit_id, metric_id)
            _upsert_config(session, unit_id, metric_id, derived=True)
            for dependency_id in RATE_DEPENDENCIES[metric_id]:
                dependency_name = RATE_DEPENDENCY_NAMES[dependency_id]
                _upsert_resource(
                    session,
                    resource_id=dependency_id,
                    kind="me",
                    name_zh=dependency_name,
                    name_en=f"{name_en} Evidence",
                    enabled=True,
                    display_order=display_order,
                    direction="higher_better",
                    importance="normal",
                )
                _upsert_binding(
                    session,
                    unit_id,
                    dependency_id,
                    source_file=_source_file(unit_id),
                    raw_name=dependency_name,
                )
            display_order += 1

        for row in session.query(KpiMeasurementResource).filter(KpiMeasurementResource.kind == "mu").all():
            row.enabled = row.resource_id in {item[0] for item in ENABLED_UNITS}
            row.updated_at = CATALOG_TIME
        session.commit()


def _base_series() -> dict[tuple[str, str], list[dict[str, Any]]]:
    series: dict[tuple[str, str], list[dict[str, Any]]] = {}
    names = {metric_id: name_zh for _, metric_id, name_zh, *_ in BASE_METRICS}
    for unit_id, metric_id, _name_zh, _name_en, *_rest in BASE_METRICS:
        points = []
        for offset, value in _rest[-1]:
            points.append(
                {
                    "time": _at(int(offset)),
                    "object_key": "pod-health-a" if unit_id != "MU_CALL" else "pod-call-a",
                    "period_minutes": 15,
                    "value": value,
                }
            )
        series[(unit_id, metric_id)] = points
    del names
    return series


def _derived_series() -> dict[tuple[str, str], list[dict[str, Any]]]:
    unit_by_rate = {item[1]: item[0] for item in RATE_METRICS}
    series: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rate_id, rows in RATE_VALUES.items():
        unit_id = unit_by_rate[rate_id]
        numerator_id, denominator_id = RATE_DEPENDENCIES[rate_id]
        numerator_points: list[dict[str, Any]] = []
        denominator_points: list[dict[str, Any]] = []
        rate_points: list[dict[str, Any]] = []
        for offset, numerator, denominator, rate in rows:
            measured_at = _at(offset)
            base_point = {
                "time": measured_at,
                "object_key": "pod-health-a",
                "period_minutes": 15,
            }
            numerator_points.append({**base_point, "value": numerator})
            denominator_points.append({**base_point, "value": denominator})
            rate_points.append({**base_point, "value": rate})
        series[(unit_id, numerator_id)] = numerator_points
        series[(unit_id, denominator_id)] = denominator_points
        series[(unit_id, rate_id)] = rate_points
    return series


def _metric_results_for_unit(
    unit_id: str,
    series: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for (owner_unit, metric_id), points in series.items():
        if owner_unit != unit_id:
            continue
        results[metric_id] = {
            "metric_resource_id": metric_id,
            "source_files": [_source_file(unit_id)],
            "time_series": [
                {
                    **point,
                    "source_rows": [{"source_file": _source_file(unit_id), "line_number": index + 2}],
                }
                for index, point in enumerate(points)
            ],
        }
    return results


def _unit_results(series: dict[tuple[str, str], list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for unit_id, name_zh, name_en, _fragment in ENABLED_UNITS:
        metric_results = _metric_results_for_unit(unit_id, series)
        metric_ids = sorted(metric_results)
        results[unit_id] = {
            "measurement_unit_id": unit_id,
            "name_zh": name_zh,
            "name_en": name_en,
            "status": "pass",
            "reason": None,
            "file_count": 1,
            "object_count": 1,
            "metric_coverage": f"{len(metric_ids)}/{len(metric_ids)}",
            "metrics": metric_ids,
            "metric_results": metric_results,
            "object_results": {},
            "objects": {},
            "source_files": [_source_file(unit_id)],
        }
    return results


def _public_unit_results(unit_results: dict[str, dict[str, Any]], snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    metrics_by_unit: dict[str, list[dict[str, Any]]] = {}
    for metric in snapshot["metrics"]:
        metrics_by_unit.setdefault(str(metric["measurement_unit_id"]), []).append(
            {
                "metric_resource_id": metric["metric_resource_id"],
                "metric_resource_name_zh": metric["metric_resource_name_zh"],
                "base_source_name": metric["metric_resource_id"],
                "raw_source_name": metric["metric_resource_id"],
                "read_status": "readable" if metric["today_value"] is not None else "missing",
                "value_pattern": "all_zero" if metric["today_value"] == 0 else "normal",
                "business_status": metric["current_status"],
                "importance": metric["importance"],
                "display_unit": metric["display_unit"],
            }
        )
    output = []
    for unit_id, unit in unit_results.items():
        output.append(
            {
                "measurement_unit_id": unit_id,
                "name_zh": unit["name_zh"],
                "name_en": unit["name_en"],
                "status": "pass",
                "reason": None,
                "file_count": 1,
                "object_count": 1,
                "metric_coverage": f"{len(metrics_by_unit.get(unit_id, []))}/{len(metrics_by_unit.get(unit_id, []))}",
                "metrics": metrics_by_unit.get(unit_id, []),
                "objects": {},
                "source_files": unit["source_files"],
            }
        )
    return output


def _kpi_points(series: dict[tuple[str, str], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for (unit_id, metric_id), metric_points in series.items():
        for point in metric_points:
            points.append(
                {
                    "rule_code": RULE_CODE,
                    "measurement_unit_id": unit_id,
                    "metric_resource_id": metric_id,
                    "object_key": point["object_key"],
                    "period_minutes": point["period_minutes"],
                    "measured_at": point["time"],
                    "value": point["value"],
                    "source_file": _source_file(unit_id),
                    "line_number": 2,
                }
            )
    return points


def _rule_result(metadata: dict[str, Any], *, status: RuleStatus, summary: str) -> RuleResult:
    return make_result(
        inspector,
        status=status,
        summary=summary,
        metrics=[
            {"key": "matched_files", "label": "匹配文件数", "value": 4, "unit": "个"},
            {"key": "unmatched_files", "label": "未匹配文件数", "value": 0, "unit": "个"},
            {"key": "skipped_files", "label": "周期跳过文件数", "value": 0, "unit": "个"},
            {"key": "measurement_units", "label": "测量单元数", "value": 4, "unit": "个"},
        ],
        metadata=metadata,
    )


def _task(task_id: str, rule: RuleResult, *, status: RuleStatus) -> InspectionTask:
    summary = Summary(
        total=1,
        pass_=1 if status == RuleStatus.PASS else 0,
        warn=1 if status == RuleStatus.WARN else 0,
        fail=0,
        error=0,
        skip=0,
    )
    system = SystemInspection(
        package_file=f"{task_id}.zip",
        status="completed",
        summary=summary,
        rules=[rule.model_copy(update={"metadata": {}, "findings": [], "metrics": []})],
        version="V900R016C10SPC200",
        customer={"device_id": DEVICE_ID, "province": "江苏", "operator": "移动", "product": "UMF"},
    )
    return InspectionTask(
        task_id=task_id,
        name="KPI 当前判定与昨日趋势 E2E",
        mode="local",
        status="completed",
        trigger="api",
        created_at=CREATED_AT,
        completed_at=COMPLETED_AT,
        last_run_at=COMPLETED_AT,
        stats=TaskStats(
            total=1,
            pass_=summary.pass_,
            warn=summary.warn,
            fail=0,
            error=0,
            skip=0,
            systems=1,
        ),
        system=system,
    )


def _write_scene(task: InspectionTask, rule: RuleResult, kpi_points: list[dict[str, Any]]) -> None:
    task_dir = settings.output / task.task_id
    upload_dir = settings.uploads / task.task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / f"{task.task_id}.zip").write_bytes(b"e2e-kpi-daily-health")
    save_rule_result(settings.output, task.task_id, rule)
    if task.system is not None:
        save_system(settings.output, task.task_id, task.system)
    save_task_meta(settings.output, task)
    task_db.publish_snapshot(task, rule_results=[rule], kpi_points=kpi_points)


def _assert_scene(snapshot: dict[str, Any]) -> None:
    metrics = snapshot["metrics"]
    assert len(metrics) == 20, f"预计 20 个指标，实际 {len(metrics)}"
    assert snapshot["scope"]["expected_metric_count"] == 20
    assert snapshot["scope"]["confirmed_binding_metric_count"] == 20
    dependency_ids = {dependency_id for pair in RATE_DEPENDENCIES.values() for dependency_id in pair}
    assert dependency_ids.isdisjoint({metric["metric_resource_id"] for metric in metrics})
    assert snapshot["data_date"] == "2026-11-05", snapshot["data_date"]
    assert set(snapshot["current_counts"]) == {
        "normal",
        "warn",
        "fail",
        "pending_config",
        "unable_to_judge",
        "not_applicable",
    }
    assert all(snapshot["current_counts"][status] >= 1 for status in snapshot["current_counts"])
    assert all(snapshot["trend_counts"][status] >= 1 for status in snapshot["trend_counts"])
    rate_ids = {metric["metric_resource_id"] for metric in metrics if "成功率" in metric["metric_resource_name_zh"]}
    assert rate_ids == {item[1] for item in RATE_METRICS}, rate_ids
    for _unit, rate_id, name_zh, *_rest in RATE_METRICS:
        matches = [metric for metric in metrics if metric["metric_resource_id"] == rate_id]
        assert len(matches) == 1 and matches[0]["metric_resource_name_zh"] == name_zh
    rate_one = next(metric for metric in metrics if metric["metric_resource_id"] == RATE_ID)
    assert rate_one["measurement_unit_id"] == RATE_UNIT
    assert rate_one["trend_status"] == "worsened"
    today = rate_one["objects"][0]
    assert (today["numerator"], today["denominator"], today["today_value"]) == (129, 200, 64.5)


def main() -> None:
    init_db()
    _seed_catalog()
    series = {**_base_series(), **_derived_series()}
    unit_results = _unit_results(series)
    snapshot = build_daily_health_snapshot(
        TASK_ID,
        unit_results,
        [
            {
                "filename": _source_file(unit_id),
                "source_file": _source_file(unit_id),
                "status": "matched",
                "measurement_unit_id": unit_id,
            }
            for unit_id, *_rest in ENABLED_UNITS
        ]
        + [
            {
                "filename": "Disabled_E2E.csv",
                "source_file": "Disabled_E2E.csv",
                "status": "disabled",
                "measurement_unit_id": "MU_DISABLED_E2E",
            }
        ],
    )
    _assert_scene(snapshot)

    with session_factory() as session:
        enabled_units = [
            row.resource_id
            for row in session.query(KpiMeasurementResource)
            .filter(KpiMeasurementResource.kind == "mu", KpiMeasurementResource.enabled.is_(True))
            .order_by(KpiMeasurementResource.resource_id)
            .all()
        ]
    assert enabled_units == sorted(item[0] for item in ENABLED_UNITS), enabled_units

    public_units = _public_unit_results(unit_results, snapshot)
    status_counts = Counter(metric["current_status"] for metric in snapshot["metrics"])
    metadata = {
        "measurement_units": public_units,
        "files": [_source_file(item[0]) for item in ENABLED_UNITS],
        "unmatched_files": [],
        "skipped_files": [],
        "kpi_overview": {
            "unit_count": 4,
            "metric_count": 20,
            "business_fail_count": status_counts["fail"],
            "business_warn_count": status_counts["warn"],
            "data_error_count": status_counts["unable_to_judge"],
            "trend_worsened_count": snapshot["trend_counts"]["worsened"],
            "unconfigured_count": status_counts["pending_config"],
            "health_score": 72,
            "status_counts": {"pass": 4},
            "auto_registered_count": 18,
            "conflict_count": 0,
            "unmatched_file_count": 0,
        },
        "daily_health": snapshot,
    }
    rule = _rule_result(
        metadata,
        status=RuleStatus.WARN,
        summary="KPI 日健康 E2E：20 个指标，覆盖六种当前判定与五种昨日趋势",
    )
    task = _task(TASK_ID, rule, status=RuleStatus.WARN)
    _write_scene(task, rule, _kpi_points(series))

    legacy_metadata = {
        "measurement_units": [
            {
                "measurement_unit_id": "MU_CALL",
                "name_zh": "呼叫统计",
                "name_en": "Call Statistics",
                "status": "pass",
                "reason": None,
                "file_count": 1,
                "object_count": 1,
                "metric_coverage": "1/1",
                "metrics": [
                    {
                        "metric_resource_id": "ME_CALL",
                        "metric_resource_name_zh": "呼叫请求次数",
                        "base_source_name": "ME_CALL",
                        "raw_source_name": "ME_CALL",
                        "read_status": "readable",
                        "value_pattern": "normal",
                        "business_status": "normal",
                    }
                ],
                "objects": {},
                "source_files": ["legacy.csv"],
            }
        ],
        "files": ["legacy.csv"],
        "unmatched_files": [],
        "skipped_files": [],
    }
    legacy_rule = _rule_result(
        legacy_metadata,
        status=RuleStatus.PASS,
        summary="旧版 KPI 现场：没有日健康结论",
    )
    legacy_task = _task(LEGACY_TASK_ID, legacy_rule, status=RuleStatus.PASS)
    _write_scene(legacy_task, legacy_rule, [])


if __name__ == "__main__":
    main()
