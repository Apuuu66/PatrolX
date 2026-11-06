"""任务长期数据（任务行 / 规则结果 / KPI 点）的 SQLite 读写唯一入口。

设计约束：

- 只有父进程（CLI 发布路径与 ``TaskService``）调用写入接口，worker 不写库。
- 界面展示读取全部走本模块；``output/`` 现场文件只作为执行期产物与启动回填输入。
- 规则结果与 KPI 点按任务整批替换，保持"最新为准、无版本历史"。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.db import (
    InventoryParseResult,
    KpiTeamFocusItem,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    TaskKpiMetricResultV6,
    TaskKpiPoint,
    TaskKpiPointV6,
    TaskKpiScopeItem,
    TaskKpiScopeSnapshot,
    TaskRecord,
    TaskRuleResult,
    TaskRuleScopeItem,
    TaskRuleScopeSnapshot,
    session_factory,
)
from app.models.schemas import (
    DataPreparation,
    InspectionTask,
    PackageKind,
    RuleResult,
    RuleStatus,
    Summary,
    SystemInspection,
    SystemStatus,
    TaskInventory,
    TaskMode,
    TaskStats,
    TaskStatus,
    TaskSummary,
    TaskTrigger,
)

logger = get_logger("patrolx.task_db")

_KPI_RULE_CODE = "kpi.measurement_units"
_KPI_INSERT_BATCH_SIZE = 1_000
_EMPTY_STATS = {"total": 0, "pass": 0, "warn": 0, "fail": 0, "error": 0, "skip": 0, "systems": 0}


@dataclass(frozen=True, slots=True)
class RuleScopeItemData:
    """任务规则快照中的单条业务规则。"""

    rule_code: str
    rule_version: str
    category: str
    priority: int
    execution_order: int
    assignment_snapshot: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RuleScopeSnapshotData:
    """任务启动时冻结的普通规则范围。"""

    task_id: str
    network_element_type: str | None
    assignment_revision: int
    registry_fingerprint: str
    trigger: str
    source: str
    frozen_at: datetime
    snapshot_state: str
    items: tuple[RuleScopeItemData, ...]

    @property
    def rule_codes(self) -> frozenset[str]:
        """冻结快照中的普通规则代码集合。"""
        return frozenset(item.rule_code for item in self.items)


@dataclass(frozen=True, slots=True)
class KpiScopeItemData:
    """任务 KPI 范围中的单个指标与配置快照。"""

    measurement_unit_id: str
    metric_resource_id: str
    metric_kind: str
    config_snapshot: dict[str, Any]
    scope_status: str


@dataclass(frozen=True, slots=True)
class KpiScopeSnapshotData:
    """任务启动时冻结的 KPI 配置范围摘要与指标集合。"""

    task_id: str
    network_element_type: str | None
    team_focus_revision: int
    config_fingerprint: str
    data_date: date | None
    frozen_at: datetime
    snapshot_payload: dict[str, Any]
    items: tuple[KpiScopeItemData, ...]


@dataclass(frozen=True, slots=True)
class KpiMetricResultData:
    """待原子发布的 v6 单指标最终判定。"""

    task_id: str
    network_element_type: str
    measurement_unit_id: str
    metric_resource_id: str
    source_rule_code: str | None
    decision: str
    special_state: str | None
    yesterday_trend: str | None
    needs_attention_group: str | None
    today_value: float | None
    yesterday_value: float | None
    change: float | None
    unit: str | None
    importance: str | None
    reason: str
    effective_point_count: int
    result_payload: dict[str, Any]
    result_fingerprint: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class KpiPointData:
    """待原子发布的 v6 复合作用域 KPI 点。"""

    task_id: str
    network_element_type: str
    source_rule_code: str | None
    measurement_unit_id: str
    metric_resource_id: str
    object_key: str
    period_minutes: int | None
    measured_at: datetime
    value: float | None
    source_file: str | None
    line_number: int | None
    point_fingerprint: str


@dataclass(frozen=True, slots=True)
class KpiWorkbenchScopeItemData:
    """结果工作台读取所需的任务指标范围与展示名称。"""

    measurement_unit_id: str
    measurement_unit_name: str
    measurement_unit_enabled: bool
    metric_resource_id: str
    metric_name: str
    metric_kind: str
    config_snapshot: dict[str, Any]
    scope_status: str


@dataclass(frozen=True, slots=True)
class KpiWorkbenchFocusItemData:
    """当前网元类型共享关注项及可用于不可用占位的展示信息。"""

    measurement_unit_id: str
    measurement_unit_name: str
    measurement_unit_enabled: bool
    metric_resource_id: str
    metric_name: str


@dataclass(frozen=True, slots=True)
class KpiWorkbenchSourceData:
    """任务工作台一次性读取的冻结范围、当前关注与最终结果。"""

    task_id: str
    network_element_type: str | None
    snapshot_present: bool
    team_focus_revision: int
    data_date: date | None
    frozen_at: datetime | None
    snapshot_payload: dict[str, Any]
    scope_items: tuple[KpiWorkbenchScopeItemData, ...]
    focus_items: tuple[KpiWorkbenchFocusItemData, ...]
    metric_results: tuple[dict[str, Any], ...]
    latest_measured_at: datetime | None
    business_rule_count: int


class KpiV6DataError(Exception):
    """v6 任务数据不满足冻结范围或可发布条件。"""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def elapsed_ms(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    """计算一次运行的毫秒耗时；任一端缺失时返回 None（从未运行 / 运行中）。

    时钟回拨等导致结束早于开始时收敛为 0，保证契约 ``duration_ms >= 0``。
    """
    if started_at is None or finished_at is None:
        return None
    start = _as_utc(started_at)
    end = _as_utc(finished_at)
    assert start is not None and end is not None
    return max(0, int((end - start).total_seconds() * 1000))


def _parse_iso_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _task_stats_payload(raw: object) -> TaskStats:
    """任务行 stats 兜底：缺失或非法时用零值，避免展示读取整体失败。"""
    if isinstance(raw, dict):
        try:
            return TaskStats.model_validate(raw)
        except Exception:  # noqa: BLE001 - 历史行可能缺 systems 或字段类型不符
            logger.warning("task_stats_invalid", payload_keys=sorted(raw))
    return TaskStats.model_validate(_EMPTY_STATS)


def _is_hidden_rule(code: str) -> bool:
    """隐藏规则不进入任务 system 摘要；规则缺失时按可见处理。"""
    from app.inspectors.registry import registry

    try:
        return bool(registry.get(code).hidden)
    except Exception:  # noqa: BLE001 - 规则已下线或注册表未加载时不影响读取
        return False


def _rule_row(task_id: str, result: RuleResult, *, updated_at: datetime | None = None) -> TaskRuleResult:
    payload = result.model_dump(by_alias=True, mode="json")
    return TaskRuleResult(
        task_id=task_id,
        rule_code=result.code,
        priority=result.priority.value if hasattr(result.priority, "value") else str(result.priority),
        execution_order=result.execution_order,
        status=result.status.value if hasattr(result.status, "value") else str(result.status),
        severity=result.severity.value if hasattr(result.severity, "value") else str(result.severity),
        executed_at=result.executed_at,
        finding_count=len(result.findings or []),
        result=payload,
        updated_at=updated_at or datetime.now(UTC),
    )


def _kpi_row_values(task_id: str, point: dict[str, Any]) -> dict[str, Any] | None:
    measured_at = point.get("measured_at")
    if isinstance(measured_at, str):
        measured_at = _parse_iso_time(measured_at)
    measured_at = _as_utc(measured_at if isinstance(measured_at, datetime) else None)
    if measured_at is None:
        return None
    value = point.get("value")
    period = point.get("period_minutes")
    line_number = point.get("line_number")
    return {
        "task_id": task_id,
        "rule_code": str(point.get("rule_code") or _KPI_RULE_CODE),
        "measurement_unit_id": point.get("measurement_unit_id"),
        "metric_resource_id": point.get("metric_resource_id"),
        "object_key": point.get("object_key") or "__all__",
        "period_minutes": period if isinstance(period, int) else None,
        "measured_at": measured_at,
        "value": float(value) if isinstance(value, (int, float)) else None,
        "source_file": point.get("source_file"),
        "line_number": line_number if isinstance(line_number, int) else None,
    }


def _kpi_insert_batches(points: Iterable[dict[str, Any]], task_id: str) -> Iterable[list[dict[str, Any]]]:
    """把 KPI 输入流切成固定大小批次，避免 ORM 身份映射保存全部行。"""
    batch: list[dict[str, Any]] = []
    for point in points:
        row = _kpi_row_values(task_id, point)
        if row is None:
            continue
        batch.append(row)
        if len(batch) >= _KPI_INSERT_BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def _apply_task_row(record: TaskRecord, task: InspectionTask) -> None:
    """把任务摘要写入任务行；运行字段（last_run_at/duration_ms）由发布快照显式带入。"""
    system = task.system
    record.name = task.name
    record.mode = task.mode.value
    record.status = task.status.value
    record.trigger = task.trigger.value
    record.package_kind = (task.package_kind or PackageKind.INSPECTION).value
    if system is not None:
        record.package_file = system.package_file
        record.customer = dict(system.customer)
        record.version = system.version
        if system.package_checksum:
            record.package_checksum = system.package_checksum
    record.stats = task.stats.model_dump(by_alias=True, mode="json")
    if task.completed_at is not None:
        record.completed_at = task.completed_at
    if task.last_run_at is not None:
        record.last_run_at = task.last_run_at
    if task.duration_ms is not None:
        record.duration_ms = task.duration_ms
    if task.preparation is not None:
        record.preparation = task.preparation.model_dump(by_alias=True, mode="json")


def _upsert_task_row(session: Session, task: InspectionTask) -> TaskRecord:
    record = session.get(TaskRecord, task.task_id)
    if record is None:
        record = TaskRecord(
            task_id=task.task_id,
            name=task.name,
            mode=task.mode.value,
            status=task.status.value,
            trigger=task.trigger.value,
            package_file=task.system.package_file if task.system is not None else "",
            customer={},
            stats={},
            package_kind=(task.package_kind or PackageKind.INSPECTION).value,
            created_at=task.created_at,
        )
        session.add(record)
        session.flush()
        record.created_at = task.created_at
    _apply_task_row(record, task)
    return record


def sync_task_row(task: InspectionTask) -> None:
    """父进程写 ``task.json`` 时同步任务行；不触碰规则结果与 KPI 点。"""
    with session_factory() as session:
        _upsert_task_row(session, task)
        session.commit()


def ensure_task_execution_row(
    *,
    task_id: str,
    name: str,
    mode: TaskMode,
    trigger: TaskTrigger,
    package_file: str,
    customer: dict[str, str],
    version: str | None,
    package_kind: PackageKind,
    rule_network_element_type: str | None,
    created_at: datetime,
) -> bool:
    """任务开始前确保任务行存在；已预留的在线任务保持原创建信息不变。

    任务范围快照通过外键依赖 ``tasks.task_id``。在线任务在排队时已有任务行，
    本地 CLI 任务则可能到执行阶段才首次落库；本函数只补齐缺失行，不覆盖已存在行。
    """
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is not None:
            return False
        session.add(
            TaskRecord(
                task_id=task_id,
                name=name,
                mode=mode.value,
                status=TaskStatus.RUNNING.value,
                trigger=trigger.value,
                package_file=package_file,
                customer=dict(customer),
                version=version,
                stats=dict(_EMPTY_STATS),
                package_kind=package_kind.value,
                rule_network_element_type=rule_network_element_type,
                created_at=created_at,
            )
        )
        session.commit()
        return True


def _validate_network_scope(network_element_type: str | None, *, allow_none: bool) -> None:
    if network_element_type is None:
        if allow_none:
            return
        raise KpiV6DataError("kpi_network_scope_required", "KPI 结果必须指定网元类型", 400)
    if not network_element_type or network_element_type in {"*", "COMMON", "PUBLIC"}:
        raise KpiV6DataError("invalid_network_element_type", "网元类型不能使用公共作用域", 400)


def save_task_scope_snapshots(
    *,
    rule_snapshot: RuleScopeSnapshotData,
    kpi_snapshot: KpiScopeSnapshotData,
) -> None:
    """在同一事务中替换任务规则与 KPI 范围快照。"""
    if rule_snapshot.task_id != kpi_snapshot.task_id:
        raise KpiV6DataError("task_scope_identity_mismatch", "规则与 KPI 快照任务不一致", 400)
    _validate_network_scope(rule_snapshot.network_element_type, allow_none=True)
    _validate_network_scope(kpi_snapshot.network_element_type, allow_none=not kpi_snapshot.items)

    with session_factory() as session:
        session.query(TaskRuleScopeItem).filter(TaskRuleScopeItem.task_id == rule_snapshot.task_id).delete()
        session.query(TaskRuleScopeSnapshot).filter(TaskRuleScopeSnapshot.task_id == rule_snapshot.task_id).delete()
        session.query(TaskKpiScopeItem).filter(TaskKpiScopeItem.task_id == kpi_snapshot.task_id).delete()
        session.query(TaskKpiScopeSnapshot).filter(TaskKpiScopeSnapshot.task_id == kpi_snapshot.task_id).delete()

        session.add(
            TaskRuleScopeSnapshot(
                task_id=rule_snapshot.task_id,
                network_element_type=rule_snapshot.network_element_type,
                assignment_revision=rule_snapshot.assignment_revision,
                registry_fingerprint=rule_snapshot.registry_fingerprint,
                trigger=rule_snapshot.trigger,
                source=rule_snapshot.source,
                frozen_at=rule_snapshot.frozen_at,
                snapshot_state=rule_snapshot.snapshot_state,
            )
        )
        for item in rule_snapshot.items:
            session.add(
                TaskRuleScopeItem(
                    task_id=rule_snapshot.task_id,
                    rule_code=item.rule_code,
                    rule_version=item.rule_version,
                    category=item.category,
                    priority=item.priority,
                    execution_order=item.execution_order,
                    assignment_snapshot=item.assignment_snapshot,
                )
            )

        session.add(
            TaskKpiScopeSnapshot(
                task_id=kpi_snapshot.task_id,
                network_element_type=kpi_snapshot.network_element_type,
                team_focus_revision=kpi_snapshot.team_focus_revision,
                config_fingerprint=kpi_snapshot.config_fingerprint,
                data_date=kpi_snapshot.data_date,
                frozen_at=kpi_snapshot.frozen_at,
                snapshot_payload=kpi_snapshot.snapshot_payload,
            )
        )
        for item in kpi_snapshot.items:
            if kpi_snapshot.network_element_type is None:
                raise KpiV6DataError("task_kpi_scope_network_missing", "KPI 快照有指标但缺少网元类型", 400)
            session.add(
                TaskKpiScopeItem(
                    task_id=kpi_snapshot.task_id,
                    network_element_type=kpi_snapshot.network_element_type,
                    measurement_unit_id=item.measurement_unit_id,
                    metric_resource_id=item.metric_resource_id,
                    metric_kind=item.metric_kind,
                    config_snapshot=item.config_snapshot,
                    scope_status=item.scope_status,
                )
            )
        session.flush()
        session.commit()


def get_rule_scope_snapshot(
    task_id: str,
    *,
    network_element_type: str | None,
) -> RuleScopeSnapshotData | None:
    """读取任务规则快照；任务或网元作用域不匹配时返回 None。"""
    _validate_network_scope(network_element_type, allow_none=True)
    with session_factory() as session:
        query = session.query(TaskRuleScopeSnapshot).filter(TaskRuleScopeSnapshot.task_id == task_id)
        if network_element_type is None:
            query = query.filter(TaskRuleScopeSnapshot.network_element_type.is_(None))
        else:
            query = query.filter(TaskRuleScopeSnapshot.network_element_type == network_element_type)
        row = query.one_or_none()
        if row is None:
            return None
        items = (
            session.query(TaskRuleScopeItem)
            .filter(TaskRuleScopeItem.task_id == task_id)
            .order_by(TaskRuleScopeItem.execution_order, TaskRuleScopeItem.rule_code)
            .all()
        )
        frozen_at = _as_utc(row.frozen_at)
        assert frozen_at is not None
        return RuleScopeSnapshotData(
            task_id=row.task_id,
            network_element_type=row.network_element_type,
            assignment_revision=row.assignment_revision,
            registry_fingerprint=row.registry_fingerprint,
            trigger=row.trigger,
            source=row.source,
            frozen_at=frozen_at,
            snapshot_state=row.snapshot_state,
            items=tuple(
                RuleScopeItemData(
                    rule_code=item.rule_code,
                    rule_version=item.rule_version,
                    category=item.category,
                    priority=item.priority,
                    execution_order=item.execution_order,
                    assignment_snapshot=dict(item.assignment_snapshot or {}),
                )
                for item in items
            ),
        )


def get_kpi_scope_snapshot(
    task_id: str,
    *,
    network_element_type: str | None,
) -> KpiScopeSnapshotData | None:
    """读取任务 KPI 快照；任务或网元作用域不匹配时返回 None。"""
    _validate_network_scope(network_element_type, allow_none=True)
    with session_factory() as session:
        query = session.query(TaskKpiScopeSnapshot).filter(TaskKpiScopeSnapshot.task_id == task_id)
        if network_element_type is None:
            query = query.filter(TaskKpiScopeSnapshot.network_element_type.is_(None))
        else:
            query = query.filter(TaskKpiScopeSnapshot.network_element_type == network_element_type)
        row = query.one_or_none()
        if row is None:
            return None
        items = (
            (
                session.query(TaskKpiScopeItem)
                .filter(
                    TaskKpiScopeItem.task_id == task_id,
                    TaskKpiScopeItem.network_element_type == network_element_type,
                )
                .order_by(TaskKpiScopeItem.measurement_unit_id, TaskKpiScopeItem.metric_resource_id)
                .all()
            )
            if network_element_type is not None
            else []
        )
        frozen_at = _as_utc(row.frozen_at)
        assert frozen_at is not None
        return KpiScopeSnapshotData(
            task_id=row.task_id,
            network_element_type=row.network_element_type,
            team_focus_revision=row.team_focus_revision,
            config_fingerprint=row.config_fingerprint,
            data_date=row.data_date,
            frozen_at=frozen_at,
            snapshot_payload=dict(row.snapshot_payload or {}),
            items=tuple(
                KpiScopeItemData(
                    measurement_unit_id=item.measurement_unit_id,
                    metric_resource_id=item.metric_resource_id,
                    metric_kind=item.metric_kind,
                    config_snapshot=dict(item.config_snapshot or {}),
                    scope_status=item.scope_status,
                )
                for item in items
            ),
        )


def _validate_result_scope(
    result: KpiMetricResultData,
    *,
    task_id: str,
    network_element_type: str,
    scope_ids: set[tuple[str, str]],
) -> None:
    identity = (result.measurement_unit_id, result.metric_resource_id)
    if result.task_id != task_id or result.network_element_type != network_element_type or identity not in scope_ids:
        raise KpiV6DataError(
            "kpi_result_scope_mismatch",
            "KPI 结果不属于任务冻结范围",
            409,
        )


def _validate_point_scope(
    point: KpiPointData,
    *,
    task_id: str,
    network_element_type: str,
    scope_ids: set[tuple[str, str]],
) -> None:
    identity = (point.measurement_unit_id, point.metric_resource_id)
    if point.task_id != task_id or point.network_element_type != network_element_type or identity not in scope_ids:
        raise KpiV6DataError(
            "kpi_point_scope_mismatch",
            "KPI 点不属于任务冻结范围",
            409,
        )


def publish_kpi_v6_snapshot(
    task: InspectionTask,
    *,
    metric_results: Iterable[KpiMetricResultData],
    metric_points: Iterable[KpiPointData],
    replace_source_rule_codes: set[str] | None = None,
) -> None:
    """单事务发布 v6 KPI 结果、点与任务摘要。

    ``replace_source_rule_codes`` 为 None 时全量替换；否则只替换给定来源规则的
    结果与点，用于单规则或增量重跑。
    """
    results = list(metric_results)
    points = list(metric_points)
    with session_factory() as session:
        snapshot = session.get(TaskKpiScopeSnapshot, task.task_id)
        if snapshot is None:
            raise KpiV6DataError(
                "task_result_requires_rebuild",
                "旧任务没有 v6 KPI 快照，请按当前配置重建",
                409,
            )
        network_element_type = snapshot.network_element_type
        if network_element_type is None:
            _validate_network_scope(network_element_type, allow_none=False)
        assert network_element_type is not None
        scope_rows = (
            session.query(TaskKpiScopeItem)
            .filter(
                TaskKpiScopeItem.task_id == task.task_id,
                TaskKpiScopeItem.network_element_type == network_element_type,
            )
            .all()
        )
        scope_ids = {(row.measurement_unit_id, row.metric_resource_id) for row in scope_rows}
        for result in results:
            _validate_result_scope(
                result,
                task_id=task.task_id,
                network_element_type=network_element_type,
                scope_ids=scope_ids,
            )
        for point in points:
            _validate_point_scope(
                point,
                task_id=task.task_id,
                network_element_type=network_element_type,
                scope_ids=scope_ids,
            )
        if replace_source_rule_codes is not None:
            allowed_codes = set(replace_source_rule_codes)
            if any(result.source_rule_code not in allowed_codes for result in results) or any(
                point.source_rule_code not in allowed_codes for point in points
            ):
                raise KpiV6DataError(
                    "kpi_incremental_publish_scope_mismatch",
                    "增量发布的行必须属于待替换来源规则",
                    409,
                )

        _upsert_task_row(session, task)
        result_delete = session.query(TaskKpiMetricResultV6).filter(TaskKpiMetricResultV6.task_id == task.task_id)
        point_delete = session.query(TaskKpiPointV6).filter(TaskKpiPointV6.task_id == task.task_id)
        if replace_source_rule_codes is None:
            result_delete.delete()
            point_delete.delete()
        elif replace_source_rule_codes:
            codes = sorted(replace_source_rule_codes)
            result_delete.filter(TaskKpiMetricResultV6.source_rule_code.in_(codes)).delete(synchronize_session=False)
            point_delete.filter(TaskKpiPointV6.source_rule_code.in_(codes)).delete(synchronize_session=False)

        for result in results:
            session.add(
                TaskKpiMetricResultV6(
                    task_id=result.task_id,
                    network_element_type=result.network_element_type,
                    measurement_unit_id=result.measurement_unit_id,
                    metric_resource_id=result.metric_resource_id,
                    source_rule_code=result.source_rule_code,
                    decision=result.decision,
                    special_state=result.special_state,
                    yesterday_trend=result.yesterday_trend,
                    needs_attention_group=result.needs_attention_group,
                    today_value=result.today_value,
                    yesterday_value=result.yesterday_value,
                    change=result.change,
                    unit=result.unit,
                    importance=result.importance,
                    reason=result.reason,
                    effective_point_count=result.effective_point_count,
                    result_payload=result.result_payload,
                    result_fingerprint=result.result_fingerprint,
                    published_at=result.published_at,
                )
            )
        for point in points:
            session.add(
                TaskKpiPointV6(
                    task_id=point.task_id,
                    network_element_type=point.network_element_type,
                    source_rule_code=point.source_rule_code,
                    measurement_unit_id=point.measurement_unit_id,
                    metric_resource_id=point.metric_resource_id,
                    object_key=point.object_key,
                    period_minutes=point.period_minutes,
                    measured_at=point.measured_at,
                    value=point.value,
                    source_file=point.source_file,
                    line_number=point.line_number,
                    point_fingerprint=point.point_fingerprint,
                )
            )
        session.flush()
        session.commit()


def _metric_result_payload(row: TaskKpiMetricResultV6) -> dict[str, Any]:
    return {
        "task_id": row.task_id,
        "network_element_type": row.network_element_type,
        "measurement_unit_id": row.measurement_unit_id,
        "metric_resource_id": row.metric_resource_id,
        "source_rule_code": row.source_rule_code,
        "decision": row.decision,
        "special_state": row.special_state,
        "yesterday_trend": row.yesterday_trend,
        "needs_attention_group": row.needs_attention_group,
        "today_value": row.today_value,
        "yesterday_value": row.yesterday_value,
        "change": row.change,
        "unit": row.unit,
        "importance": row.importance,
        "reason": row.reason,
        "effective_point_count": row.effective_point_count,
        "result_payload": dict(row.result_payload or {}),
        "result_fingerprint": row.result_fingerprint,
        "published_at": _as_utc(row.published_at),
    }


def list_kpi_metric_results_v6(
    task_id: str,
    *,
    network_element_type: str,
) -> list[dict[str, Any]]:
    """读取任务内指定网元类型的全部 v6 指标最终判定。"""
    _validate_network_scope(network_element_type, allow_none=False)
    with session_factory() as session:
        rows = (
            session.query(TaskKpiMetricResultV6)
            .filter(
                TaskKpiMetricResultV6.task_id == task_id,
                TaskKpiMetricResultV6.network_element_type == network_element_type,
            )
            .order_by(TaskKpiMetricResultV6.id)
            .all()
        )
        return [_metric_result_payload(row) for row in rows]


def get_kpi_metric_result_v6(
    task_id: str,
    *,
    network_element_type: str,
    measurement_unit_id: str,
    metric_resource_id: str,
) -> dict[str, Any] | None:
    """按完整复合身份读取单条 v6 指标最终判定。"""
    _validate_network_scope(network_element_type, allow_none=False)
    with session_factory() as session:
        row = (
            session.query(TaskKpiMetricResultV6)
            .filter(
                TaskKpiMetricResultV6.task_id == task_id,
                TaskKpiMetricResultV6.network_element_type == network_element_type,
                TaskKpiMetricResultV6.measurement_unit_id == measurement_unit_id,
                TaskKpiMetricResultV6.metric_resource_id == metric_resource_id,
            )
            .one_or_none()
        )
        return _metric_result_payload(row) if row is not None else None


def _kpi_point_v6_payload(row: TaskKpiPointV6) -> dict[str, Any]:
    return {
        "task_id": row.task_id,
        "network_element_type": row.network_element_type,
        "source_rule_code": row.source_rule_code,
        "measurement_unit_id": row.measurement_unit_id,
        "metric_resource_id": row.metric_resource_id,
        "object_key": row.object_key or "__all__",
        "period_minutes": row.period_minutes,
        "measured_at": _as_utc(row.measured_at),
        "value": row.value,
        "source_file": row.source_file,
        "line_number": row.line_number,
        "point_fingerprint": row.point_fingerprint,
    }


def list_kpi_points_v6(
    task_id: str,
    *,
    network_element_type: str,
    measurement_unit_id: str | None = None,
    metric_resource_id: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """读取指定任务与网元类型的 v6 KPI 点，可按复合身份和时间窗过滤。"""
    _validate_network_scope(network_element_type, allow_none=False)
    start = _as_utc(start_at)
    end = _as_utc(end_at)
    if start_at is not None and start is None:
        return []
    if end_at is not None and end is None:
        return []
    if start is not None and end is not None and start >= end:
        return []
    with session_factory() as session:
        query = session.query(TaskKpiPointV6).filter(
            TaskKpiPointV6.task_id == task_id,
            TaskKpiPointV6.network_element_type == network_element_type,
        )
        if measurement_unit_id is not None:
            query = query.filter(TaskKpiPointV6.measurement_unit_id == measurement_unit_id)
        if metric_resource_id is not None:
            query = query.filter(TaskKpiPointV6.metric_resource_id == metric_resource_id)
        if start is not None:
            query = query.filter(TaskKpiPointV6.measured_at >= start)
        if end is not None:
            query = query.filter(TaskKpiPointV6.measured_at < end)
        rows = query.order_by(TaskKpiPointV6.measured_at, TaskKpiPointV6.id).all()
        return [_kpi_point_v6_payload(row) for row in rows]


def _kpi_scope_metric_name(
    row: TaskKpiScopeItem,
    resource_map: dict[str, KpiV6MeasurementResource],
) -> str:
    """优先使用任务冻结名称，缺失时回退当前资源目录和稳定 ID。"""
    config_name = (row.config_snapshot or {}).get("name_zh")
    if isinstance(config_name, str) and config_name.strip():
        return config_name
    resource = resource_map.get(row.metric_resource_id)
    if resource is not None and resource.name_zh.strip():
        return resource.name_zh
    return row.metric_resource_id


def get_kpi_workbench_source_data(task_id: str) -> KpiWorkbenchSourceData | None:
    """读取工作台所需的冻结范围、共享关注、来源名称与最终判定。

    任务不存在返回 ``None``；任务存在但缺少 KPI 快照时以
    ``snapshot_present=False`` 返回，由服务层统一映射为重建提示。
    """
    with session_factory() as session:
        task = session.get(TaskRecord, task_id)
        if task is None:
            return None

        snapshot = session.get(TaskKpiScopeSnapshot, task_id)
        customer = task.customer if isinstance(task.customer, dict) else {}
        customer_type = customer.get("product")
        # KPI 作用域只由巡检包 product 决定；日志补充包的规则适用类型不得兜底为 KPI 类型。
        network_element_type = (
            snapshot.network_element_type
            if snapshot is not None
            else (str(customer_type).strip().upper() if customer_type else None)
        )

        business_rule_count = (
            session.query(func.count(TaskRuleScopeItem.id)).filter(TaskRuleScopeItem.task_id == task_id).scalar() or 0
        )
        if snapshot is None:
            return KpiWorkbenchSourceData(
                task_id=task_id,
                network_element_type=network_element_type,
                snapshot_present=False,
                team_focus_revision=0,
                data_date=None,
                frozen_at=None,
                snapshot_payload={},
                scope_items=(),
                focus_items=(),
                metric_results=(),
                latest_measured_at=None,
                business_rule_count=int(business_rule_count),
            )

        scope_query = session.query(TaskKpiScopeItem).filter(TaskKpiScopeItem.task_id == task_id)
        result_query = session.query(TaskKpiMetricResultV6).filter(TaskKpiMetricResultV6.task_id == task_id)
        point_query = session.query(func.max(TaskKpiPointV6.measured_at)).filter(TaskKpiPointV6.task_id == task_id)
        unit_map: dict[str, KpiV6MeasurementUnit] = {}
        resource_map: dict[str, KpiV6MeasurementResource] = {}
        focus_rows: list[KpiTeamFocusItem] = []
        if network_element_type is not None:
            scope_query = scope_query.filter(TaskKpiScopeItem.network_element_type == network_element_type)
            result_query = result_query.filter(TaskKpiMetricResultV6.network_element_type == network_element_type)
            point_query = point_query.filter(TaskKpiPointV6.network_element_type == network_element_type)
            unit_map = {
                row.measurement_unit_id: row
                for row in session.query(KpiV6MeasurementUnit)
                .filter(KpiV6MeasurementUnit.network_element_type == network_element_type)
                .all()
            }
            resource_map = {
                row.resource_id: row
                for row in session.query(KpiV6MeasurementResource)
                .filter(KpiV6MeasurementResource.network_element_type == network_element_type)
                .all()
            }
            focus_rows = (
                session.query(KpiTeamFocusItem)
                .filter(KpiTeamFocusItem.network_element_type == network_element_type)
                .order_by(
                    KpiTeamFocusItem.measurement_unit_id,
                    KpiTeamFocusItem.metric_resource_id,
                )
                .all()
            )

        scope_rows = scope_query.order_by(
            TaskKpiScopeItem.measurement_unit_id,
            TaskKpiScopeItem.metric_resource_id,
        ).all()
        snapshot_payload = dict(snapshot.snapshot_payload or {})
        frozen_enabled_unit_ids_raw = snapshot_payload.get("enabled_measurement_unit_ids")
        frozen_enabled_unit_ids = (
            {str(value) for value in frozen_enabled_unit_ids_raw if str(value).strip()}
            if isinstance(frozen_enabled_unit_ids_raw, list)
            else None
        )
        scope_items = tuple(
            KpiWorkbenchScopeItemData(
                measurement_unit_id=row.measurement_unit_id,
                measurement_unit_name=(
                    unit_map[row.measurement_unit_id].name_zh
                    if row.measurement_unit_id in unit_map
                    else row.measurement_unit_id
                ),
                # 历史工作台只认任务启动时冻结的启用测量单元，不读取当前启停状态。
                measurement_unit_enabled=(
                    row.measurement_unit_id in frozen_enabled_unit_ids if frozen_enabled_unit_ids is not None else True
                ),
                metric_resource_id=row.metric_resource_id,
                metric_name=_kpi_scope_metric_name(row, resource_map),
                metric_kind=row.metric_kind,
                config_snapshot=dict(row.config_snapshot or {}),
                scope_status=row.scope_status,
            )
            for row in scope_rows
        )
        focus_items = tuple(
            KpiWorkbenchFocusItemData(
                measurement_unit_id=row.measurement_unit_id,
                measurement_unit_name=(
                    unit_map[row.measurement_unit_id].name_zh
                    if row.measurement_unit_id in unit_map
                    else row.measurement_unit_id
                ),
                measurement_unit_enabled=(
                    unit_map[row.measurement_unit_id].inspection_enabled
                    if row.measurement_unit_id in unit_map
                    else False
                ),
                metric_resource_id=row.metric_resource_id,
                metric_name=(
                    resource_map[row.metric_resource_id].name_zh
                    if row.metric_resource_id in resource_map
                    else row.metric_resource_id
                ),
            )
            for row in focus_rows
        )
        frozen_at = _as_utc(snapshot.frozen_at)
        assert frozen_at is not None
        latest_measured_at = _as_utc(point_query.scalar())
        return KpiWorkbenchSourceData(
            task_id=task_id,
            network_element_type=network_element_type,
            snapshot_present=True,
            team_focus_revision=snapshot.team_focus_revision,
            data_date=snapshot.data_date,
            frozen_at=frozen_at,
            snapshot_payload=snapshot_payload,
            scope_items=scope_items,
            focus_items=focus_items,
            metric_results=tuple(_metric_result_payload(row) for row in result_query.all()),
            latest_measured_at=latest_measured_at,
            business_rule_count=int(business_rule_count),
        )


def publish_snapshot(
    task: InspectionTask,
    *,
    rule_results: Iterable[RuleResult],
    kpi_points: Iterable[dict[str, Any]],
) -> None:
    """单事务整批替换本任务的规则结果与 KPI 点，并同步任务行。"""
    results = list(rule_results)
    with session_factory() as session:
        _upsert_task_row(session, task)
        session.query(TaskRuleResult).filter(TaskRuleResult.task_id == task.task_id).delete()
        session.query(TaskKpiPoint).filter(TaskKpiPoint.task_id == task.task_id).delete()
        for result in results:
            session.add(_rule_row(task.task_id, result))
        for batch in _kpi_insert_batches(kpi_points, task.task_id):
            session.execute(insert(TaskKpiPoint), batch)
        session.commit()


def save_run_start(task_id: str, started_at: datetime) -> None:
    """任务运行开始：写 ``last_run_at`` 并清空 ``duration_ms``；任务行不存在时忽略。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return
        record.last_run_at = started_at
        record.duration_ms = None
        session.commit()


def save_run_end(
    task_id: str,
    *,
    status: TaskStatus,
    completed_at: datetime | None,
    duration_ms: int | None,
) -> None:
    """任务运行结束：写终态、结束时刻与耗时；任务行不存在时忽略。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return
        record.status = status.value
        record.completed_at = completed_at
        record.duration_ms = duration_ms
        session.commit()


def get_run_fields(task_id: str) -> tuple[datetime | None, int | None, str | None]:
    """返回任务行的 ``(last_run_at, duration_ms, package_checksum)``。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return None, None, None
        return _as_utc(record.last_run_at), record.duration_ms, record.package_checksum


def task_exists(task_id: str) -> bool:
    """任务行是否存在；用于区分「现场已清理」与「任务不存在」。"""
    with session_factory() as session:
        return session.get(TaskRecord, task_id) is not None


def get_package_file(task_id: str) -> str | None:
    """任务行记录的原始包文件名；恢复现场时按该名称写回。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None or not record.package_file:
            return None
        return record.package_file


@dataclass(frozen=True, slots=True)
class TaskIdentity:
    """同名任务恢复所需的任务首次创建身份。"""

    package_kind: PackageKind
    product: str | None
    rule_network_element_type: str | None


def get_task_identity(task_id: str) -> TaskIdentity | None:
    """返回兼容读取后的任务包类型与规范化网元类型，避免 API 直接访问持久化模型。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return None
        raw_kind = getattr(record, "package_kind", None) or PackageKind.INSPECTION.value
        try:
            package_kind = PackageKind(str(raw_kind))
        except ValueError:
            package_kind = PackageKind.INSPECTION
        customer = record.customer if isinstance(record.customer, dict) else {}
        raw_product = customer.get("product")
        if raw_product is None:
            product = None
        else:
            product = str(raw_product).strip().upper() or None
        raw_rule_type = getattr(record, "rule_network_element_type", None)
        rule_network_element_type = str(raw_rule_type).strip().upper() if raw_rule_type else None
        if package_kind == PackageKind.INSPECTION and rule_network_element_type is None:
            rule_network_element_type = product
        return TaskIdentity(
            package_kind=package_kind,
            product=product,
            rule_network_element_type=rule_network_element_type,
        )


def set_package_checksum(task_id: str, checksum: str) -> None:
    """写入首次接收的原始包校验和；已有值不覆盖。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None or record.package_checksum:
            return
        record.package_checksum = checksum
        session.commit()


def _system_status(status: TaskStatus) -> SystemStatus:
    return SystemStatus.FAILED if status == TaskStatus.FAILED else SystemStatus.COMPLETED


def _summary_from_stats(stats: TaskStats) -> Summary:
    return Summary(
        total=stats.total,
        pass_=stats.pass_,
        warn=stats.warn,
        fail=stats.fail,
        error=stats.error,
        skip=stats.skip,
    )


def _inventory_snapshot(session: Session, task_id: str) -> TaskInventory | None:
    result = session.get(InventoryParseResult, task_id)
    snapshot = result.snapshot if result is not None else None
    if not isinstance(snapshot, dict):
        return None
    try:
        return TaskInventory.model_validate(snapshot)
    except Exception:  # noqa: BLE001 - 坏快照只降级不阻断展示
        return None


def _visible_rules(session: Session, task_id: str) -> list[RuleResult]:
    rows = (
        session.query(TaskRuleResult)
        .filter(TaskRuleResult.task_id == task_id)
        .order_by(TaskRuleResult.execution_order.is_(None), TaskRuleResult.execution_order, TaskRuleResult.rule_code)
        .all()
    )
    results: list[RuleResult] = []
    for row in rows:
        if _is_hidden_rule(row.rule_code):
            continue
        try:
            results.append(RuleResult.model_validate(row.result))
        except Exception:  # noqa: BLE001 - 单条坏结果不阻断任务详情
            logger.warning("task_rule_result_invalid", task_id=task_id, rule_code=row.rule_code)
    return results


def _stats_match_rules(stats: TaskStats, rules: list[RuleResult]) -> bool:
    """任务行统计是否与规则行状态分布一致。"""
    if stats.total != len(rules):
        return False
    actual = {
        RuleStatus.PASS: stats.pass_,
        RuleStatus.WARN: stats.warn,
        RuleStatus.FAIL: stats.fail,
        RuleStatus.ERROR: stats.error,
        RuleStatus.SKIP: stats.skip,
    }
    if sum(actual.values()) != stats.total:
        return False
    return all(sum(rule.status == status for rule in rules) == count for status, count in actual.items())


def _stats_from_rules(rules: list[RuleResult], *, systems: int) -> TaskStats:
    """规则行是发布时整批替换的权威副本；统计不一致时按规则行重算。"""
    counts = {status.value: 0 for status in RuleStatus}
    for rule in rules:
        counts[rule.status.value] += 1
    return TaskStats(
        total=len(rules),
        pass_=counts["pass"],
        warn=counts["warn"],
        fail=counts["fail"],
        error=counts["error"],
        skip=counts["skip"],
        systems=systems,
    )


def _task_from_record(session: Session, record: TaskRecord, rules: list[RuleResult]) -> InspectionTask:
    stats = _task_stats_payload(record.stats)
    if rules and not _stats_match_rules(stats, rules):
        stats = _stats_from_rules(rules, systems=stats.systems)
    preparation = None
    if isinstance(record.preparation, dict):
        try:
            preparation = DataPreparation.model_validate(record.preparation)
        except Exception:  # noqa: BLE001 - 坏准备摘要只降级展示
            logger.warning("task_preparation_invalid", task_id=record.task_id)
    status = TaskStatus(record.status)
    # 记录声明有规则结果、库里却没有任何规则行：发布快照之前写入的历史任务行，
    # 只能按元数据降级（system=None），不得因统计不一致整体读取失败。
    system = (
        None
        if not rules and stats.total
        else SystemInspection(
            package_file=record.package_file or "",
            package_checksum=record.package_checksum,
            version=record.version,
            status=_system_status(status),
            summary=_summary_from_stats(stats),
            rules=rules,
            customer=dict(record.customer or {}),
        )
    )
    return InspectionTask(
        task_id=record.task_id,
        name=record.name,
        mode=TaskMode(record.mode),
        status=status,
        trigger=TaskTrigger(record.trigger),
        created_at=_as_utc(record.created_at),
        completed_at=_as_utc(record.completed_at),
        last_run_at=_as_utc(record.last_run_at),
        duration_ms=record.duration_ms,
        stats=stats,
        preparation=preparation,
        system=system,
        package_kind=PackageKind(getattr(record, "package_kind", None) or PackageKind.INSPECTION.value),
        inventory=_inventory_snapshot(session, record.task_id),
    )


def get_task(task_id: str) -> InspectionTask | None:
    """按任务行 + 规则结果 + 准备摘要组装任务详情。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return None
        return _task_from_record(session, record, _visible_rules(session, task_id))


def get_task_summary(task_id: str) -> TaskSummary | None:
    """返回列表用任务摘要（含运行字段与客户元数据）。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None:
            return None
        return _summary_from_record(session, record)


def _inventory_snapshots(session: Session, task_ids: list[str]) -> dict[str, TaskInventory]:
    """批量读取任务级台账证据快照，避免列表逐任务查询。"""
    if not task_ids:
        return {}
    rows = session.query(InventoryParseResult).filter(InventoryParseResult.task_id.in_(task_ids)).all()
    snapshots: dict[str, TaskInventory] = {}
    for row in rows:
        if not isinstance(row.snapshot, dict):
            continue
        try:
            snapshots[row.task_id] = TaskInventory.model_validate(row.snapshot)
        except Exception:  # noqa: BLE001 - 坏快照只降级不阻断列表
            continue
    return snapshots


def _summary_from_record(session: Session, record: TaskRecord, snapshot: TaskInventory | None = None) -> TaskSummary:
    stats = _task_stats_payload(record.stats)
    customer = dict(record.customer or {})
    preparation = None
    if isinstance(record.preparation, dict):
        try:
            preparation = DataPreparation.model_validate(record.preparation)
        except Exception:  # noqa: BLE001 - 坏准备摘要只降级展示
            preparation = None
    return TaskSummary(
        task_id=record.task_id,
        name=record.name,
        mode=TaskMode(record.mode),
        status=TaskStatus(record.status),
        trigger=TaskTrigger(record.trigger),
        created_at=_as_utc(record.created_at),
        completed_at=_as_utc(record.completed_at),
        last_run_at=_as_utc(record.last_run_at),
        duration_ms=record.duration_ms,
        stats=stats,
        preparation=preparation,
        system=None,
        package_kind=PackageKind(getattr(record, "package_kind", None) or PackageKind.INSPECTION.value),
        inventory=snapshot if snapshot is not None else _inventory_snapshot(session, record.task_id),
        device_id=customer.get("device_id"),
        customer_province=customer.get("province"),
        customer_operator=customer.get("operator"),
        customer_product=customer.get("product"),
        rule_network_element_type=(
            str(record.rule_network_element_type).strip().upper()
            if getattr(record, "rule_network_element_type", None)
            else None
        ),
        customer_version=record.version,
    )


def list_task_summaries(
    status: str | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[TaskSummary], int]:
    """返回按创建时间倒序的任务摘要与总数；排序、过滤与分页全部在 SQL 完成。"""
    with session_factory() as session:
        query = session.query(TaskRecord)
        if status:
            query = query.filter(TaskRecord.status == status)
        total = int(query.order_by(None).count())
        query = query.order_by(TaskRecord.created_at.desc(), TaskRecord.task_id.desc())
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        records = query.all()
        snapshots = _inventory_snapshots(session, [record.task_id for record in records])
        items = [_summary_from_record(session, record, snapshots.get(record.task_id)) for record in records]
    return items, total


def list_rule_results(task_id: str) -> list[RuleResult]:
    """按展示顺序返回任务全部规则结果（含隐藏规则）。"""
    with session_factory() as session:
        rows = (
            session.query(TaskRuleResult)
            .filter(TaskRuleResult.task_id == task_id)
            .order_by(
                TaskRuleResult.execution_order.is_(None),
                TaskRuleResult.execution_order,
                TaskRuleResult.rule_code,
            )
            .all()
        )
        results: list[RuleResult] = []
        for row in rows:
            try:
                results.append(RuleResult.model_validate(row.result))
            except Exception:  # noqa: BLE001 - 单条坏结果不阻断读取
                logger.warning("task_rule_result_invalid", task_id=task_id, rule_code=row.rule_code)
        return results


def get_rule_result(task_id: str, rule_code: str) -> RuleResult | None:
    """读取单条规则结果；不存在或损坏时返回 None。"""
    with session_factory() as session:
        row = (
            session.query(TaskRuleResult)
            .filter(TaskRuleResult.task_id == task_id, TaskRuleResult.rule_code == rule_code)
            .one_or_none()
        )
        if row is None:
            return None
        try:
            return RuleResult.model_validate(row.result)
        except Exception:  # noqa: BLE001 - 坏结果按不存在处理，调用方回退文件
            logger.warning("task_rule_result_invalid", task_id=task_id, rule_code=rule_code)
            return None


def list_kpi_points(task_id: str) -> list[dict[str, Any]]:
    """返回任务 KPI 历史点；字段与 ``kpi/history/index.jsonl`` 一一对应。"""
    with session_factory() as session:
        rows = (
            session.query(TaskKpiPoint)
            .filter(TaskKpiPoint.task_id == task_id)
            .order_by(TaskKpiPoint.measured_at, TaskKpiPoint.id)
            .all()
        )
        return [_kpi_point_payload(row) for row in rows if row.measured_at is not None]


def _kpi_point_payload(row: TaskKpiPoint) -> dict[str, Any]:
    """把持久化 KPI 点转换为展示层稳定字段。"""
    return {
        "task_id": row.task_id,
        "measurement_unit_id": row.measurement_unit_id,
        "metric_resource_id": row.metric_resource_id,
        "object_key": row.object_key or "__all__",
        "period_minutes": row.period_minutes,
        "measured_at": _as_utc(row.measured_at),
        "value": row.value,
        "source_file": row.source_file,
        "line_number": row.line_number,
    }


def list_kpi_points_for_metric(
    task_id: str,
    measurement_unit_id: str,
    metric_resource_id: str,
    *,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    """按任务、测量单元、指标和左闭右开时间窗读取 KPI 点。"""
    start = _as_utc(start_at)
    end = _as_utc(end_at)
    if start is None or end is None or start >= end:
        return []
    with session_factory() as session:
        rows = (
            session.query(TaskKpiPoint)
            .filter(
                TaskKpiPoint.task_id == task_id,
                TaskKpiPoint.measurement_unit_id == measurement_unit_id,
                TaskKpiPoint.metric_resource_id == metric_resource_id,
                TaskKpiPoint.measured_at >= start,
                TaskKpiPoint.measured_at < end,
            )
            .order_by(TaskKpiPoint.measured_at, TaskKpiPoint.id)
            .all()
        )
        return [_kpi_point_payload(row) for row in rows if row.measured_at is not None]


def list_previous_completed_task_ids(
    device_id: str,
    *,
    completed_before: datetime,
    limit: int = 20,
) -> list[str]:
    """返回同设备、指定时刻前最近完成的候选任务 ID。"""
    before = _as_utc(completed_before)
    if before is None or not device_id or limit <= 0:
        return []
    with session_factory() as session:
        records = (
            session.query(TaskRecord)
            .filter(
                TaskRecord.status == "completed",
                TaskRecord.completed_at.is_not(None),
                TaskRecord.completed_at < before,
            )
            .order_by(TaskRecord.completed_at.desc(), TaskRecord.task_id.desc())
            .all()
        )
    matched: list[str] = []
    for record in records:
        customer = record.customer if isinstance(record.customer, dict) else {}
        if str(customer.get("device_id") or "") != device_id:
            continue
        matched.append(record.task_id)
        if len(matched) >= limit:
            break
    return matched


@dataclass(slots=True)
class TaskRecordView:
    """列表/候选场景需要的轻量任务行视图。"""

    task_id: str
    name: str
    status: str
    created_at: datetime
    last_run_at: datetime | None
    completed_at: datetime | None
    version: str | None
    device_id: str | None


def list_task_records() -> list[TaskRecordView]:
    """返回全部任务行视图，供留存排序与 KPI 候选筛选使用。"""
    with session_factory() as session:
        records = session.query(TaskRecord).all()
        return [
            TaskRecordView(
                task_id=record.task_id,
                name=record.name,
                status=record.status,
                created_at=record.created_at,
                last_run_at=record.last_run_at,
                completed_at=record.completed_at,
                version=record.version,
                device_id=(record.customer or {}).get("device_id"),
            )
            for record in records
        ]


@dataclass(slots=True)
class OverviewCounts:
    """概览聚合结果。"""

    task_count: int
    rule_result_count: int
    finding_count: int
    status_counts: dict[str, int]


def _hidden_rule_codes() -> list[str]:
    """当前注册表中的隐藏规则代码；注册表不可用时不排除任何规则。"""
    from app.inspectors.registry import registry

    try:
        registry.load_all()
        return [rule.code for rule in registry.all(include_hidden=True) if rule.hidden]
    except Exception:  # noqa: BLE001 - 注册表加载失败不影响概览统计
        logger.warning("overview_hidden_rules_unavailable")
        return []


def overview_counts() -> OverviewCounts:
    """按任务行与规则结果行聚合概览统计，不扫描 output/。

    口径与既有概览一致：任务数与可见规则结果数（隐藏规则如 ``pkg.extract.*`` 不计入）。
    """
    hidden = _hidden_rule_codes()
    with session_factory() as session:
        task_count = session.query(func.count(TaskRecord.task_id)).scalar() or 0
        rules = session.query(TaskRuleResult)
        if hidden:
            rules = rules.filter(TaskRuleResult.rule_code.notin_(hidden))
        rule_result_count = rules.count()
        finding_count = rules.with_entities(func.coalesce(func.sum(TaskRuleResult.finding_count), 0)).scalar() or 0
        rows = (
            rules.with_entities(TaskRuleResult.status, func.count(TaskRuleResult.id))
            .group_by(TaskRuleResult.status)
            .all()
        )
    counts = {key: 0 for key in ("pass", "warn", "fail", "error", "skip")}
    for status, count in rows:
        if status in counts:
            counts[status] = int(count)
    return OverviewCounts(
        task_count=int(task_count),
        rule_result_count=int(rule_result_count),
        finding_count=int(finding_count),
        status_counts=counts,
    )


def delete_task_data(session: Session, task_id: str) -> None:
    """删除任务的规则结果、KPI 点与任务行；调用方负责先删文件现场。"""
    session.query(TaskRuleResult).filter(TaskRuleResult.task_id == task_id).delete()
    session.query(TaskKpiPoint).filter(TaskKpiPoint.task_id == task_id).delete()
    record = session.get(TaskRecord, task_id)
    if record is not None:
        session.delete(record)


# ---- 启动回填（幂等，必须先于任何留存清理） ----


def _read_json_file(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _read_kpi_index(task_dir: Path, task_id: str) -> Iterable[dict[str, Any]]:
    """逐行读取任务私有 KPI 索引；坏行跳过，不阻断回填。"""
    path = task_dir / "kpi" / "history" / "index.jsonl"
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict) or raw.get("task_id") != task_id:
                    continue
                yield raw
    except (OSError, UnicodeDecodeError):
        logger.warning("task_backfill_index_unreadable", task_id=task_id, path=str(path))


def _read_rule_results(task_dir: Path, task_id: str) -> list[RuleResult]:
    rules_dir = task_dir / "rules"
    if not rules_dir.is_dir():
        return []
    results: list[RuleResult] = []
    for path in sorted(rules_dir.glob("*.json")):
        payload = _read_json_file(path)
        if not isinstance(payload, dict):
            logger.warning("task_backfill_rule_broken", task_id=task_id, rule_file=path.name)
            continue
        try:
            results.append(RuleResult.model_validate(payload))
        except Exception:  # noqa: BLE001 - 单个坏规则文件跳过
            logger.warning("task_backfill_rule_invalid", task_id=task_id, rule_file=path.name)
    return results


def _read_scene_log_time(task_dir: Path, status: TaskStatus) -> datetime | None:
    """从执行日志 ``ts`` 字段读取终态时间；异常日志不阻断恢复。"""
    path = task_dir / "execution.log"
    last_time: datetime | None = None
    terminal_time: datetime | None = None
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                timestamp = _parse_iso_time(entry.get("ts"))
                if timestamp is None:
                    continue
                last_time = timestamp
                message = str(entry.get("message") or "")
                if status == TaskStatus.COMPLETED and "完成" in message:
                    terminal_time = timestamp
                elif status == TaskStatus.FAILED and "失败" in message:
                    terminal_time = timestamp
    except (OSError, UnicodeDecodeError):
        pass
    return terminal_time or last_time


def _recover_terminal_task_from_scene(task_id: str, task_dir: Path) -> InspectionTask | None:
    """用数据库任务行 + 终态 system.json + 规则结果恢复缺失 task.json 的任务。"""
    with session_factory() as session:
        record = session.get(TaskRecord, task_id)
        if record is None or record.status not in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
            return None
        record_values = {
            "name": record.name,
            "mode": record.mode,
            "trigger": record.trigger,
            "created_at": _as_utc(record.created_at),
            "last_run_at": _as_utc(record.last_run_at),
            "package_kind": record.package_kind,
            "stats": dict(record.stats or {}),
        }

    system_payload = _read_json_file(task_dir / "system.json")
    if not isinstance(system_payload, dict):
        return None
    try:
        system = SystemInspection.model_validate(system_payload)
    except Exception:  # noqa: BLE001 - 坏 system.json 不阻断其他任务恢复
        logger.warning("task_backfill_system_invalid", task_id=task_id)
        return None

    status = TaskStatus.COMPLETED if system.status == SystemStatus.COMPLETED else TaskStatus.FAILED
    completed_at = _read_scene_log_time(task_dir, status)
    if completed_at is None:
        try:
            completed_at = datetime.fromtimestamp((task_dir / "system.json").stat().st_mtime, tz=UTC)
        except OSError:
            completed_at = record_values["last_run_at"] or record_values["created_at"]
    last_run_at = record_values["last_run_at"] or record_values["created_at"]
    if last_run_at is None or completed_at is None:
        return None

    preparation = None
    from app.services import preparation as preparation_service

    try:
        preparation = preparation_service.load_preparation(task_dir)
    except Exception:  # noqa: BLE001 - 准备摘要重建失败不影响终态恢复
        logger.warning("task_backfill_preparation_failed", task_id=task_id)

    summary = system.summary
    systems = record_values["stats"].get("systems", 1)
    try:
        package_kind = PackageKind(str(record_values["package_kind"] or PackageKind.INSPECTION.value))
    except ValueError:
        package_kind = PackageKind.INSPECTION
    try:
        return InspectionTask(
            task_id=task_id,
            name=record_values["name"],
            mode=TaskMode(record_values["mode"]),
            status=status,
            trigger=TaskTrigger(record_values["trigger"]),
            created_at=record_values["created_at"],
            completed_at=completed_at,
            last_run_at=last_run_at,
            duration_ms=elapsed_ms(last_run_at, completed_at),
            stats=TaskStats(
                total=summary.total,
                pass_=summary.pass_,
                warn=summary.warn,
                fail=summary.fail,
                error=summary.error,
                skip=summary.skip,
                systems=int(systems) if isinstance(systems, int) else 1,
            ),
            preparation=preparation,
            system=system,
            package_kind=package_kind,
        )
    except Exception:  # noqa: BLE001 - 历史脏字段只跳过该任务
        logger.warning("task_backfill_terminal_scene_invalid", task_id=task_id)
        return None


def publish_from_scene(
    task: InspectionTask,
    *,
    output: Path | None = None,
    include_kpi: bool = True,
) -> None:
    """读取任务现场并整批发布到 SQLite；单个坏规则或 KPI 行跳过。

    准备摘要只在现场可计算时写入，避免覆盖既有值；``preparation`` 计算函数保持
    执行期语义不变，读取方一律以任务行中的快照为准。

    ``include_kpi=False`` 只发布任务行与规则结果，供终态先可见；KPI 随后通过
    :func:`publish_kpi_from_scene` 独立镜像，失败不回滚任务终态。
    """
    base = output or settings.output
    task_dir = base / task.task_id
    summary = task.preparation
    if summary is None:
        from app.services.preparation import load_preparation

        summary = load_preparation(task_dir)
    published = task if summary is None else task.model_copy(update={"preparation": summary})
    publish_snapshot(
        published,
        rule_results=_read_rule_results(task_dir, task.task_id),
        kpi_points=_read_kpi_index(task_dir, task.task_id) if include_kpi else (),
    )


def publish_kpi_from_scene(task_id: str, *, output: Path | None = None) -> int:
    """独立镜像现场 KPI 索引到 SQLite，失败由调用方记录且不改变任务终态。"""
    base = output or settings.output
    task_dir = base / task_id
    point_count = 0

    def counted_points() -> Iterable[dict[str, Any]]:
        nonlocal point_count
        for point in _read_kpi_index(task_dir, task_id):
            point_count += 1
            yield point

    with session_factory() as session:
        session.query(TaskKpiPoint).filter(TaskKpiPoint.task_id == task_id).delete()
        for batch in _kpi_insert_batches(counted_points(), task_id):
            session.execute(insert(TaskKpiPoint), batch)
        session.commit()
    logger.info("task_kpi_mirrored", task_id=task_id, kpi_point_count=point_count)
    return point_count


def _row_needs_snapshot(session: Session, task_id: str, rule_results: list[RuleResult]) -> bool:
    """任务行存在但没有任何规则行且现场有可导入规则时，需要按现场补齐快照。"""
    if not rule_results:
        return False
    return session.query(TaskRuleResult.id).filter(TaskRuleResult.task_id == task_id).first() is None


def import_task_from_output(task_id: str, *, output: Path | None = None, force: bool = False) -> bool:
    """从 ``output/<task_id>/`` 现场回填单个任务；已入库或现场不可读时返回 False。"""
    base = output or settings.output
    task_dir = base / task_id
    payload = _read_json_file(task_dir / "task.json")
    if not isinstance(payload, dict):
        recovered = _recover_terminal_task_from_scene(task_id, task_dir)
        if recovered is None:
            return False
        publish_from_scene(recovered, output=base, include_kpi=False)
        from app.services.store import save_task_meta

        save_task_meta(base, recovered)
        logger.info("task_backfilled_terminal_scene", task_id=task_id)
        return True
    try:
        task = InspectionTask.model_validate(payload)
    except Exception:  # noqa: BLE001 - 坏 task.json 跳过并记录
        logger.warning("task_backfill_task_invalid", task_id=task_id)
        return False

    rule_results = _read_rule_results(task_dir, task_id)
    if not rule_results and task.system is not None and task.system.rules:
        # 历史现场只有 task.json 内嵌的规则摘要（无 rules/*.json）时按摘要入库，
        # 保证现场被清理后规则详情仍可追溯；摘要之外的字段本就不在现场。
        rule_results = list(task.system.rules)

    if not force:
        with session_factory() as session:
            record = session.get(TaskRecord, task_id)
            if record is not None and not _row_needs_snapshot(session, task_id, rule_results):
                return False

    kpi_point_count = 0

    def counted_kpi_points() -> Iterable[dict[str, Any]]:
        nonlocal kpi_point_count
        for point in _read_kpi_index(task_dir, task_id):
            kpi_point_count += 1
            yield point

    preparation = task.preparation
    if preparation is None:
        from app.services import preparation as preparation_service

        try:
            preparation = preparation_service.load_preparation(task_dir)
        except Exception:  # noqa: BLE001 - 准备摘要重建失败不影响回填
            preparation = None
    package_checksum = task.system.package_checksum if task.system is not None else None
    run_fields = _read_run_fields_from_scene(task_dir)
    merged = task.model_copy(
        update={
            "preparation": preparation,
            "last_run_at": task.last_run_at or run_fields.get("last_run_at"),
            "duration_ms": task.duration_ms if task.duration_ms is not None else run_fields.get("duration_ms"),
            "system": (
                task.system.model_copy(update={"package_checksum": package_checksum})
                if task.system is not None
                else None
            ),
        }
    )
    publish_snapshot(merged, rule_results=rule_results, kpi_points=counted_kpi_points())
    logger.info(
        "task_backfilled",
        task_id=task_id,
        rule_count=len(rule_results),
        kpi_point_count=kpi_point_count,
    )
    return True


def _read_run_fields_from_scene(task_dir: Path) -> dict[str, Any]:
    """现场 ``system.json`` 兜底读取校验和；现场无记录时返回空。"""
    payload = _read_json_file(task_dir / "system.json")
    if not isinstance(payload, dict):
        return {}
    checksum = payload.get("package_checksum")
    return {"package_checksum": checksum if isinstance(checksum, str) else None}


_backfilled_output_dirs: set[Path] = set()


def ensure_backfilled(output: Path | None = None) -> int:
    """进程内至多扫描一次现场目录的启动回填入口（幂等）。"""
    base = output or settings.output
    if base in _backfilled_output_dirs:
        return 0
    imported = backfill_from_output(base)
    _backfilled_output_dirs.add(base)
    return imported


def backfill_from_output(output: Path | None = None) -> int:
    """启动幂等回填：扫描任务现场，导入未入库任务并恢复终态场景。"""
    base = output or settings.output
    if not base.is_dir():
        return 0
    imported = 0
    for task_dir in sorted(path for path in base.iterdir() if path.is_dir()):
        task_id = task_dir.name
        try:
            if import_task_from_output(task_id, output=base):
                imported += 1
        except Exception:  # noqa: BLE001 - 单个任务回填失败不阻断启动
            logger.exception("task_backfill_failed", task_id=task_id)
    if imported:
        logger.info("task_backfill_done", imported=imported)
    return imported
