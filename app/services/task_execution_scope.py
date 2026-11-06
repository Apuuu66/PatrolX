"""任务真正开始执行时的规则与 KPI 范围冻结。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.services import task_db
from app.services.kpi_scope import KpiScopeResolver
from app.services.rule_scope import RuleScopeResolver


@dataclass(frozen=True, slots=True)
class TaskExecutionScope:
    """一次任务执行只读取的规则与 KPI 冻结快照。"""

    rule_snapshot: task_db.RuleScopeSnapshotData
    kpi_snapshot: task_db.KpiScopeSnapshotData

    @property
    def rule_codes(self) -> frozenset[str]:
        return frozenset(item.rule_code for item in self.rule_snapshot.items)


def resolve_task_execution_scope(
    *,
    task_id: str,
    rule_network_element_type: str | None,
    kpi_network_element_type: str | None,
    trigger: str,
    source: str,
    data_date: date | None = None,
    now: datetime | None = None,
    registry_override: Any | None = None,
) -> TaskExecutionScope:
    """解析任务启动时的规则与 KPI 范围，但不持久化。"""
    frozen_at = now or datetime.now(UTC)
    rule_snapshot = RuleScopeResolver(registry_override).resolve(
        task_id=task_id,
        network_element_type=rule_network_element_type,
        trigger=trigger,
        source=source,
        now=frozen_at,
    )
    kpi_snapshot = KpiScopeResolver().resolve(
        task_id=task_id,
        network_element_type=kpi_network_element_type,
        data_date=data_date,
        now=frozen_at,
    )
    return TaskExecutionScope(rule_snapshot=rule_snapshot, kpi_snapshot=kpi_snapshot)


def publish_task_execution_scope(scope: TaskExecutionScope) -> None:
    """原子发布已冻结范围；调用方决定成功提交时点。"""
    task_db.save_task_scope_snapshots(
        rule_snapshot=scope.rule_snapshot,
        kpi_snapshot=scope.kpi_snapshot,
    )


def freeze_task_execution_scope(
    *,
    task_id: str,
    rule_network_element_type: str | None,
    kpi_network_element_type: str | None,
    trigger: str,
    source: str,
    data_date: date | None = None,
    now: datetime | None = None,
    registry_override: Any | None = None,
) -> TaskExecutionScope:
    """解析并原子持久化任务启动时范围；任何后续配置修改不得影响本次执行。"""
    scope = resolve_task_execution_scope(
        task_id=task_id,
        rule_network_element_type=rule_network_element_type,
        kpi_network_element_type=kpi_network_element_type,
        trigger=trigger,
        source=source,
        data_date=data_date,
        now=now,
        registry_override=registry_override,
    )
    publish_task_execution_scope(scope)
    return scope
