"""任务启动时的 KPI 有效范围解析与配置冻结。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.dicts import load_dicts
from app.models.db import (
    KpiTeamFocusItem,
    KpiTeamFocusRevision,
    KpiV6MeasurementBinding,
    KpiV6MeasurementDerived,
    KpiV6MeasurementResource,
    KpiV6MeasurementUnit,
    KpiV6MetricMaintenanceConfig,
    session_factory,
)
from app.services.task_db import KpiScopeItemData, KpiScopeSnapshotData

_PUBLIC_SCOPES = frozenset({"*", "COMMON", "PUBLIC", "GENERIC", ""})


class KpiScopeError(Exception):
    """KPI 范围冻结错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


def _sha256(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_network_type(network_element_type: str | None) -> str | None:
    if network_element_type is None:
        return None
    normalized = str(network_element_type).strip().upper()
    allowed = tuple(item.code.strip().upper() for item in load_dicts().product)
    if normalized in _PUBLIC_SCOPES or normalized not in allowed:
        raise KpiScopeError(
            "invalid_network_element_type",
            "网元类型不在运行时字典中",
            400,
            {"network_element_type": network_element_type, "allowed": list(allowed)},
        )
    return normalized


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _config_snapshot(
    *,
    unit: KpiV6MeasurementUnit,
    resource: KpiV6MeasurementResource,
    bindings: list[KpiV6MeasurementBinding],
    config: KpiV6MetricMaintenanceConfig | None,
) -> dict[str, Any]:
    raw_source_names = sorted({binding.raw_source_name for binding in bindings})
    payload: dict[str, Any] = {
        "name_zh": resource.name_zh,
        "name_en": resource.name_en,
        "role": "base",
        "is_percentage": bool(config.is_percentage) if config is not None else False,
        "raw_source_names": raw_source_names,
        "metric_group": resource.metric_group,
        "display_order": resource.display_order,
        "importance": resource.importance,
        "direction": config.direction if config is not None else resource.direction,
        "warning_threshold": (config.warning_threshold if config is not None else resource.warning_threshold),
        "critical_threshold": (config.critical_threshold if config is not None else resource.critical_threshold),
        "daily_aggregation": config.daily_aggregation if config is not None else "latest",
        "daily_change_threshold": config.daily_change_threshold if config is not None else None,
        "daily_change_threshold_unit": (config.daily_change_threshold_unit if config is not None else "auto"),
        "zero_semantics": config.zero_semantics if config is not None else "unknown",
        "consistency_tolerance": config.consistency_tolerance if config is not None else 0.2,
        "object_match_mode": config.object_match_mode if config is not None else "exact",
        "config_state": config.config_state if config is not None else "incomplete",
        "config_revision": config.revision if config is not None else None,
        "measurement_unit_name_zh": unit.name_zh,
        "measurement_unit_name_en": unit.name_en,
        "measurement_unit_revision": unit.revision,
        "source_files": sorted({binding.source_file for binding in bindings}),
        "display_units": sorted({binding.display_unit for binding in bindings if binding.display_unit is not None}),
        "binding_revisions": sorted({binding.revision for binding in bindings}),
    }
    payload["config_fingerprint"] = _sha256(payload)
    return payload


def _derived_config_snapshot(
    *,
    unit: KpiV6MeasurementUnit,
    resource: KpiV6MeasurementResource,
    derived: KpiV6MeasurementDerived,
    config: KpiV6MetricMaintenanceConfig | None,
    components: dict[str, KpiV6MeasurementResource],
) -> dict[str, Any]:
    numerator = components.get(derived.numerator_metric_id)
    denominator = components.get(derived.denominator_metric_id)
    is_percentage = bool(config.is_percentage) if config is not None else False
    formula_templates = {
        "success_rate": "numerator_sum / denominator_sum * 100",
        "reverse_success_rate": "100 - numerator_sum / denominator_sum * 100",
    }
    payload: dict[str, Any] = {
        "name_zh": resource.name_zh,
        "name_en": resource.name_en,
        "role": "derived",
        "is_percentage": is_percentage,
        "raw_source_names": [],
        "metric_group": resource.metric_group,
        "display_order": resource.display_order,
        "importance": resource.importance,
        "direction": config.direction if config is not None else resource.direction,
        "warning_threshold": (config.warning_threshold if config is not None else resource.warning_threshold),
        "critical_threshold": (config.critical_threshold if config is not None else resource.critical_threshold),
        "daily_aggregation": config.daily_aggregation if config is not None else "latest",
        "daily_change_threshold": config.daily_change_threshold if config is not None else None,
        "daily_change_threshold_unit": (config.daily_change_threshold_unit if config is not None else "auto"),
        "zero_semantics": config.zero_semantics if config is not None else "unknown",
        "consistency_tolerance": config.consistency_tolerance if config is not None else 0.2,
        "object_match_mode": config.object_match_mode if config is not None else "exact",
        "config_state": config.config_state if config is not None else "incomplete",
        "config_revision": config.revision if config is not None else None,
        "measurement_unit_name_zh": unit.name_zh,
        "measurement_unit_name_en": unit.name_en,
        "measurement_unit_revision": unit.revision,
        "numerator_metric_id": derived.numerator_metric_id,
        "denominator_metric_id": derived.denominator_metric_id,
        "numerator_metric_name": numerator.name_zh if numerator is not None else None,
        "denominator_metric_name": denominator.name_zh if denominator is not None else None,
        "template": derived.template,
        "formula": formula_templates.get(derived.template),
        "definition_revision": derived.revision,
        "display_units": ["%"] if is_percentage else [],
        "source_files": [],
        "binding_revisions": [],
    }
    payload["config_fingerprint"] = _sha256(payload)
    return payload


def _enabled_units(session: Session, network_element_type: str) -> list[KpiV6MeasurementUnit]:
    return (
        session.query(KpiV6MeasurementUnit)
        .filter(
            KpiV6MeasurementUnit.network_element_type == network_element_type,
            KpiV6MeasurementUnit.inspection_enabled.is_(True),
        )
        .order_by(KpiV6MeasurementUnit.name_zh, KpiV6MeasurementUnit.measurement_unit_id)
        .all()
    )


def _unit_base_items(
    session: Session,
    unit: KpiV6MeasurementUnit,
) -> list[KpiScopeItemData]:
    bindings = (
        session.query(KpiV6MeasurementBinding)
        .filter(
            KpiV6MeasurementBinding.network_element_type == unit.network_element_type,
            KpiV6MeasurementBinding.measurement_unit_id == unit.measurement_unit_id,
            KpiV6MeasurementBinding.binding_state == "confirmed",
            KpiV6MeasurementBinding.metric_resource_id.is_not(None),
        )
        .order_by(
            KpiV6MeasurementBinding.metric_resource_id,
            KpiV6MeasurementBinding.raw_source_name,
        )
        .all()
    )
    bindings_by_metric: dict[str, list[KpiV6MeasurementBinding]] = {}
    for binding in bindings:
        if binding.metric_resource_id:
            bindings_by_metric.setdefault(binding.metric_resource_id, []).append(binding)
    if not bindings_by_metric:
        return []

    metric_ids = sorted(bindings_by_metric)
    resources = {
        row.resource_id: row
        for row in session.query(KpiV6MeasurementResource)
        .filter(
            KpiV6MeasurementResource.network_element_type == unit.network_element_type,
            KpiV6MeasurementResource.resource_id.in_(metric_ids),
            KpiV6MeasurementResource.kind == "me",
        )
        .all()
    }
    configs = {
        row.metric_resource_id: row
        for row in session.query(KpiV6MetricMaintenanceConfig)
        .filter(
            KpiV6MetricMaintenanceConfig.network_element_type == unit.network_element_type,
            KpiV6MetricMaintenanceConfig.measurement_unit_id == unit.measurement_unit_id,
            KpiV6MetricMaintenanceConfig.metric_resource_id.in_(metric_ids),
        )
        .all()
    }
    items: list[KpiScopeItemData] = []
    for metric_id in metric_ids:
        resource = resources.get(metric_id)
        if resource is None:
            continue
        config_snapshot = _config_snapshot(
            unit=unit,
            resource=resource,
            bindings=bindings_by_metric[metric_id],
            config=configs.get(metric_id),
        )
        items.append(
            KpiScopeItemData(
                measurement_unit_id=unit.measurement_unit_id,
                metric_resource_id=metric_id,
                metric_kind="base",
                config_snapshot=config_snapshot,
                scope_status=("needs_config" if config_snapshot["config_state"] == "incomplete" else "ready"),
            )
        )
    return items


def _unit_derived_items(
    session: Session,
    unit: KpiV6MeasurementUnit,
) -> list[KpiScopeItemData]:
    derivations = (
        session.query(KpiV6MeasurementDerived)
        .filter(
            KpiV6MeasurementDerived.network_element_type == unit.network_element_type,
            KpiV6MeasurementDerived.measurement_unit_id == unit.measurement_unit_id,
            KpiV6MeasurementDerived.definition_state == "defined",
        )
        .order_by(KpiV6MeasurementDerived.metric_resource_id)
        .all()
    )
    if not derivations:
        return []
    metric_ids = sorted({row.metric_resource_id for row in derivations})
    component_ids = sorted(
        {metric_id for row in derivations for metric_id in (row.numerator_metric_id, row.denominator_metric_id)}
    )
    resources = {
        row.resource_id: row
        for row in session.query(KpiV6MeasurementResource)
        .filter(
            KpiV6MeasurementResource.network_element_type == unit.network_element_type,
            KpiV6MeasurementResource.resource_id.in_([*metric_ids, *component_ids]),
            KpiV6MeasurementResource.kind == "me",
        )
        .all()
    }
    configs = {
        row.metric_resource_id: row
        for row in session.query(KpiV6MetricMaintenanceConfig)
        .filter(
            KpiV6MetricMaintenanceConfig.network_element_type == unit.network_element_type,
            KpiV6MetricMaintenanceConfig.measurement_unit_id == unit.measurement_unit_id,
            KpiV6MetricMaintenanceConfig.metric_resource_id.in_(metric_ids),
        )
        .all()
    }
    items: list[KpiScopeItemData] = []
    for derived in derivations:
        resource = resources.get(derived.metric_resource_id)
        if resource is None:
            continue
        config_snapshot = _derived_config_snapshot(
            unit=unit,
            resource=resource,
            derived=derived,
            config=configs.get(derived.metric_resource_id),
            components=resources,
        )
        items.append(
            KpiScopeItemData(
                measurement_unit_id=unit.measurement_unit_id,
                metric_resource_id=derived.metric_resource_id,
                metric_kind="derived",
                config_snapshot=config_snapshot,
                scope_status=("needs_config" if config_snapshot["config_state"] == "incomplete" else "ready"),
            )
        )
    return items


class KpiScopeResolver:
    """按启用测量单元冻结任务执行所需的 KPI 指标与配置。"""

    def resolve(
        self,
        *,
        task_id: str,
        network_element_type: str | None,
        data_date: date | None = None,
        now: datetime | None = None,
    ) -> KpiScopeSnapshotData:
        normalized_type = _normalize_network_type(network_element_type)
        frozen_at = _utc(now)
        if normalized_type is None:
            return KpiScopeSnapshotData(
                task_id=task_id,
                network_element_type=None,
                team_focus_revision=0,
                config_fingerprint=_sha256(
                    {"network_element_type": None, "enabled_measurement_unit_ids": [], "items": []}
                ),
                data_date=data_date,
                frozen_at=frozen_at,
                snapshot_payload={
                    "enabled_measurement_unit_ids": [],
                    "metric_count": 0,
                    "base_metric_count": 0,
                    "derived_metric_count": 0,
                    "team_focus_count": 0,
                },
                items=(),
            )

        with session_factory() as session:
            units = _enabled_units(session, normalized_type)
            items_by_identity: dict[tuple[str, str], KpiScopeItemData] = {}
            for unit in units:
                for item in _unit_base_items(session, unit):
                    items_by_identity[(item.measurement_unit_id, item.metric_resource_id)] = item
                for item in _unit_derived_items(session, unit):
                    # 源包直出的确认绑定是身份权威；残留派生定义不得覆盖它。
                    items_by_identity.setdefault(
                        (item.measurement_unit_id, item.metric_resource_id),
                        item,
                    )
            items = list(items_by_identity.values())
            revision_row = session.get(KpiTeamFocusRevision, normalized_type)
            revision = revision_row.revision if revision_row is not None else 0
            scope_ids = {(item.measurement_unit_id, item.metric_resource_id) for item in items}
            focus_ids = {
                (row.measurement_unit_id, row.metric_resource_id)
                for row in session.query(KpiTeamFocusItem)
                .filter(KpiTeamFocusItem.network_element_type == normalized_type)
                .all()
            }

        ordered_items = tuple(sorted(items, key=lambda item: (item.measurement_unit_id, item.metric_resource_id)))
        enabled_unit_ids = [unit.measurement_unit_id for unit in units]
        base_count = sum(item.metric_kind == "base" for item in ordered_items)
        derived_count = sum(item.metric_kind == "derived" for item in ordered_items)
        config_fingerprint = _sha256(
            {
                "network_element_type": normalized_type,
                "enabled_measurement_unit_ids": enabled_unit_ids,
                "items": [
                    {
                        "measurement_unit_id": item.measurement_unit_id,
                        "metric_resource_id": item.metric_resource_id,
                        "metric_kind": item.metric_kind,
                        "config_snapshot": item.config_snapshot,
                    }
                    for item in ordered_items
                ],
            }
        )
        snapshot_payload = {
            "enabled_measurement_unit_ids": enabled_unit_ids,
            "metric_count": len(ordered_items),
            "base_metric_count": base_count,
            "derived_metric_count": derived_count,
            "team_focus_count": len(scope_ids & focus_ids),
        }
        return KpiScopeSnapshotData(
            task_id=task_id,
            network_element_type=normalized_type,
            team_focus_revision=revision,
            config_fingerprint=config_fingerprint,
            data_date=data_date,
            frozen_at=frozen_at,
            snapshot_payload=snapshot_payload,
            items=ordered_items,
        )
