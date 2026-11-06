"""可复用的 v6 KPI 合成任务与数据库现场。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True, slots=True)
class KpiV6TaskSeed:
    """一种网元类型的 v6 合成任务快照。"""

    task_id: str
    network_element_type: str
    package_path: Path
    measurement_unit_id: str
    metric_resource_ids: tuple[str, ...]
    team_focus_metric_resource_ids: tuple[str, ...]
    team_focus_revision: int
    stale_team_focus_revision: int
    config_fingerprint: str
    data_date: date


@dataclass(frozen=True, slots=True)
class KpiV6SeedState:
    """服务与 API 测试可直接复用的 v6 合成数据库状态。"""

    db_path: Path
    umf: KpiV6TaskSeed
    csp: KpiV6TaskSeed
    evidence_failure_metric_resource_id: str
    frozen_at: datetime


def _read_manifest(package: Path) -> dict[str, object]:
    from tests.fixtures import make_real_package as fixture_module

    with zipfile.ZipFile(package) as archive:
        payload = json.loads(archive.read(fixture_module.KPI_V6_WORKBENCH_MANIFEST_PATH))
    assert isinstance(payload, dict)
    return payload


def seed_kpi_v6_database(db_path: Path, *, seed_root: Path) -> KpiV6SeedState:
    from app.models.db import (
        KpiTeamFocusItem,
        KpiTeamFocusRevision,
        KpiV6MeasurementBinding,
        KpiV6MeasurementResource,
        KpiV6MeasurementUnit,
        KpiV6MetricMaintenanceConfig,
        TaskKpiMetricResultV6,
        TaskKpiPointV6,
        TaskKpiScopeItem,
        TaskKpiScopeSnapshot,
        TaskRecord,
        TaskRuleScopeItem,
        TaskRuleScopeSnapshot,
        session_factory,
    )
    from tests.fixtures import make_real_package as fixture_module

    frozen_at = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)
    data_date = date(2026, 11, 5)
    task_specs = (
        ("KPI-V6-UMF-TASK", "UMF", 4),
        ("KPI-V6-CSP-TASK", "CSP", 7),
    )
    task_seeds: dict[str, KpiV6TaskSeed] = {}
    manifests: dict[str, dict[str, object]] = {}

    for task_id, network_element_type, revision in task_specs:
        package_path = fixture_module.build_kpi_v6_workbench_fixture(
            seed_root / network_element_type.lower(),
            network_element_type=network_element_type,
        )
        manifest = _read_manifest(package_path)
        metrics = manifest["metrics"]
        assert isinstance(metrics, list)
        measurement_unit_id = str(metrics[0]["measurement_unit_id"])
        metric_ids = tuple(str(item["metric_resource_id"]) for item in metrics)
        focus_metric_ids = tuple(str(item["metric_resource_id"]) for item in metrics if bool(item.get("team_focus")))
        task_seeds[network_element_type] = KpiV6TaskSeed(
            task_id=task_id,
            network_element_type=network_element_type,
            package_path=package_path,
            measurement_unit_id=measurement_unit_id,
            metric_resource_ids=metric_ids,
            team_focus_metric_resource_ids=focus_metric_ids,
            team_focus_revision=revision,
            stale_team_focus_revision=revision - 1,
            config_fingerprint=hashlib.sha256(f"{network_element_type}:{','.join(metric_ids)}".encode()).hexdigest(),
            data_date=data_date,
        )
        manifests[network_element_type] = manifest

    umf_manifest = manifests["UMF"]
    umf_metrics = umf_manifest["metrics"]
    assert isinstance(umf_metrics, list)
    evidence_failure_metric_id = next(
        str(item["metric_resource_id"])
        for item in umf_metrics
        if item.get("team_focus") and item.get("expected_needs_attention_group") == "unjudgeable"
    )

    with session_factory() as session:
        for task_seed in task_seeds.values():
            manifest = manifests[task_seed.network_element_type]
            metrics = manifest["metrics"]
            assert isinstance(metrics, list)
            session.add(
                TaskRecord(
                    task_id=task_seed.task_id,
                    name=f"{task_seed.network_element_type} v6 合成任务",
                    mode="online",
                    status="completed",
                    trigger="api",
                    package_file=task_seed.package_path.name,
                    customer={"product": task_seed.network_element_type},
                    package_kind="inspection",
                    rule_network_element_type=task_seed.network_element_type,
                    version="V6",
                    stats={},
                    created_at=frozen_at - timedelta(minutes=30),
                    completed_at=frozen_at,
                    last_run_at=frozen_at,
                    package_checksum=hashlib.sha256(task_seed.package_path.read_bytes()).hexdigest(),
                )
            )
            focus_revision = session.get(KpiTeamFocusRevision, task_seed.network_element_type)
            if focus_revision is None:
                focus_revision = KpiTeamFocusRevision(
                    network_element_type=task_seed.network_element_type,
                    revision=task_seed.team_focus_revision,
                    updated_at=frozen_at,
                )
                session.add(focus_revision)
            else:
                focus_revision.revision = task_seed.team_focus_revision
                focus_revision.updated_at = frozen_at

            session.add(
                KpiV6MeasurementUnit(
                    network_element_type=task_seed.network_element_type,
                    measurement_unit_id=task_seed.measurement_unit_id,
                    name_zh="媒体与数据通道呼叫统计",
                    name_en="Media and Data Channel Call Statistics",
                    inspection_enabled=True,
                    revision=2,
                    config_fingerprint=task_seed.config_fingerprint,
                    source="preset",
                    origin_task_id=task_seed.task_id,
                    created_at=frozen_at,
                    updated_at=frozen_at,
                )
            )
            session.add(
                TaskKpiScopeSnapshot(
                    task_id=task_seed.task_id,
                    network_element_type=task_seed.network_element_type,
                    team_focus_revision=task_seed.team_focus_revision,
                    config_fingerprint=task_seed.config_fingerprint,
                    data_date=task_seed.data_date,
                    frozen_at=frozen_at,
                    snapshot_payload={
                        "enabled_measurement_unit_ids": [task_seed.measurement_unit_id],
                        "metric_count": 20,
                        "team_focus_count": 10,
                    },
                )
            )
            session.add(
                TaskRuleScopeSnapshot(
                    task_id=task_seed.task_id,
                    network_element_type=task_seed.network_element_type,
                    assignment_revision=11,
                    registry_fingerprint="f" * 64,
                    trigger="api",
                    source="task_service",
                    frozen_at=frozen_at,
                    snapshot_state="frozen",
                )
            )
            session.add(
                TaskRuleScopeItem(
                    task_id=task_seed.task_id,
                    rule_code="kpi.measurement_units",
                    rule_version="1.2.0",
                    category="kpi",
                    priority=1,
                    execution_order=20,
                    assignment_snapshot={"network_element_types": [task_seed.network_element_type]},
                )
            )

            focus_ids = set(task_seed.team_focus_metric_resource_ids)
            for display_order, metric in enumerate(metrics):
                metric_id = str(metric["metric_resource_id"])
                raw_source_names = tuple(str(name) for name in metric["raw_source_names"])
                is_percentage = bool(metric.get("is_percentage", False))
                is_team_focus = metric_id in focus_ids
                config_snapshot = {
                    "name_zh": metric["name_zh"],
                    "name_en": raw_source_names[0],
                    "role": "base",
                    "is_percentage": is_percentage,
                    "raw_source_names": list(raw_source_names),
                    "metric_group": metric.get("metric_group"),
                    "direction": metric.get("direction"),
                    "warning_threshold": metric.get("warning_threshold"),
                    "critical_threshold": metric.get("critical_threshold"),
                    "display_order": display_order,
                }
                session.add(
                    KpiV6MeasurementResource(
                        network_element_type=task_seed.network_element_type,
                        resource_id=metric_id,
                        kind="me",
                        name_zh=str(metric["name_zh"]),
                        name_en=raw_source_names[0],
                        display_order=display_order,
                        metric_group=str(metric.get("metric_group") or ""),
                        direction=metric.get("direction"),
                        importance="P1" if is_team_focus else "normal",
                        warning_threshold=metric.get("warning_threshold"),
                        critical_threshold=metric.get("critical_threshold"),
                        source="preset",
                        origin_task_id=task_seed.task_id,
                        legacy_source_key=f"{task_seed.network_element_type}:{metric_id}",
                        created_at=frozen_at,
                        updated_at=frozen_at,
                    )
                )
                session.add(
                    KpiV6MetricMaintenanceConfig(
                        network_element_type=task_seed.network_element_type,
                        measurement_unit_id=task_seed.measurement_unit_id,
                        metric_resource_id=metric_id,
                        role="base",
                        direction=metric.get("direction"),
                        warning_threshold=metric.get("warning_threshold"),
                        critical_threshold=metric.get("critical_threshold"),
                        daily_aggregation="latest",
                        is_percentage=is_percentage,
                        zero_semantics="unknown",
                        consistency_tolerance=0.2,
                        object_match_mode="exact",
                        legacy_source_key=f"{task_seed.network_element_type}:maintenance:{metric_id}",
                        created_at=frozen_at,
                        updated_at=frozen_at,
                    )
                )
                for raw_source_name in raw_source_names:
                    session.add(
                        KpiV6MeasurementBinding(
                            network_element_type=task_seed.network_element_type,
                            measurement_unit_id=task_seed.measurement_unit_id,
                            raw_source_name=raw_source_name,
                            base_source_name=raw_source_name,
                            metric_resource_id=metric_id,
                            display_unit="%" if is_percentage else "times",
                            binding_state="confirmed",
                            source_file="PerfResult_20261105000000.zip",
                            origin_task_id=task_seed.task_id,
                            revision=1,
                            legacy_source_key=(
                                f"{task_seed.network_element_type}:binding:{metric_id}:{raw_source_name}"
                            ),
                            created_at=frozen_at,
                            updated_at=frozen_at,
                        )
                    )
                if is_team_focus:
                    session.add(
                        KpiTeamFocusItem(
                            network_element_type=task_seed.network_element_type,
                            measurement_unit_id=task_seed.measurement_unit_id,
                            metric_resource_id=metric_id,
                            added_by="synthetic-fixture",
                            added_at=frozen_at,
                        )
                    )
                session.add(
                    TaskKpiScopeItem(
                        task_id=task_seed.task_id,
                        network_element_type=task_seed.network_element_type,
                        measurement_unit_id=task_seed.measurement_unit_id,
                        metric_resource_id=metric_id,
                        metric_kind="base",
                        config_snapshot=config_snapshot,
                        scope_status="ready",
                    )
                )

                attention_group = (
                    str(metric["expected_needs_attention_group"])
                    if is_team_focus and metric.get("expected_needs_attention_group")
                    else None
                )
                is_evidence_failure = (
                    task_seed.network_element_type == "UMF" and metric_id == evidence_failure_metric_id
                )
                decision, special_state, yesterday_trend = _metric_state(attention_group)
                today_value = _metric_value(metric, attention_group)
                yesterday_value = _metric_yesterday_value(metric, today_value)
                result_payload = {
                    "metric_role": "base",
                    "is_percentage": is_percentage,
                    "evidence_available": not is_evidence_failure,
                    "missing_reason": "合成证据不可读" if is_evidence_failure else None,
                    "raw_source_names": list(raw_source_names),
                    "source_file": "PerfResult_20261105000000.zip",
                    "threshold_source": "custom" if metric.get("warning_threshold") is not None else "missing",
                    "current_status": _current_status(attention_group),
                    "trend_status": _trend_status(attention_group),
                    "configuration_state": "incomplete" if attention_group == "needs_config" else "ready",
                }
                session.add(
                    TaskKpiMetricResultV6(
                        task_id=task_seed.task_id,
                        network_element_type=task_seed.network_element_type,
                        measurement_unit_id=task_seed.measurement_unit_id,
                        metric_resource_id=metric_id,
                        source_rule_code="kpi.measurement_units",
                        decision=decision,
                        special_state=special_state,
                        yesterday_trend=yesterday_trend,
                        needs_attention_group=attention_group,
                        today_value=None if is_evidence_failure else today_value,
                        yesterday_value=yesterday_value,
                        change=(
                            round(float(today_value) - float(yesterday_value), 6)
                            if today_value is not None and yesterday_value is not None and not is_evidence_failure
                            else None
                        ),
                        unit="%" if is_percentage else "times",
                        importance="P1" if is_team_focus else "normal",
                        reason=("合成证据不可读" if is_evidence_failure else _reason(attention_group)),
                        effective_point_count=0 if is_evidence_failure else 7,
                        result_payload=result_payload,
                        result_fingerprint=hashlib.sha256(f"{task_seed.task_id}:{metric_id}".encode()).hexdigest(),
                        published_at=frozen_at,
                    )
                )
                if is_evidence_failure:
                    continue
                for days_ago in range(6, -1, -1):
                    value = yesterday_value if days_ago == 1 else today_value
                    if value is not None and attention_group == "trend_degraded":
                        value = round(value - (6 - days_ago) * 2.5, 4)
                    if value is not None and attention_group == "warning":
                        value = round(value - (6 - days_ago) * 0.5, 4)
                    session.add(
                        TaskKpiPointV6(
                            task_id=task_seed.task_id,
                            network_element_type=task_seed.network_element_type,
                            source_rule_code="kpi.measurement_units",
                            measurement_unit_id=task_seed.measurement_unit_id,
                            metric_resource_id=metric_id,
                            object_key="__all__",
                            period_minutes=1440,
                            measured_at=datetime(2026, 11, 5, 8, tzinfo=UTC) - timedelta(days=days_ago),
                            value=value,
                            source_file="PerfResult_20261105000000.zip",
                            line_number=1,
                            point_fingerprint=hashlib.sha256(
                                f"{task_seed.task_id}:{metric_id}:{days_ago}".encode()
                            ).hexdigest(),
                        )
                    )
        session.commit()

    return KpiV6SeedState(
        db_path=db_path,
        umf=task_seeds["UMF"],
        csp=task_seeds["CSP"],
        evidence_failure_metric_resource_id=evidence_failure_metric_id,
        frozen_at=frozen_at,
    )


def _metric_state(group: str | None) -> tuple[str, str | None, str]:
    if group == "failure":
        return "fail", None, "worsened"
    if group == "warning":
        return "warn", None, "observe"
    if group == "trend_degraded":
        return "pass", None, "worsened"
    if group == "unjudgeable":
        return "error", "no_data", "no_baseline"
    if group == "needs_config":
        return "skip", None, "no_baseline"
    return "pass", None, "stable"


def _current_status(group: str | None) -> str:
    return {
        "failure": "fail",
        "warning": "warn",
        "trend_degraded": "normal",
        "unjudgeable": "unable_to_judge",
        "needs_config": "pending_config",
    }.get(group, "normal")


def _trend_status(group: str | None) -> str:
    return {
        "trend_degraded": "worsened",
        "warning": "observe",
        "unjudgeable": "no_baseline",
        "needs_config": "no_baseline",
    }.get(group, "stable")


def _reason(group: str | None) -> str:
    return {
        "failure": "超过严重阈值",
        "warning": "接近告警阈值",
        "trend_degraded": "较昨日恶化",
        "unjudgeable": "缺少可判定数据",
        "needs_config": "阈值尚未配置",
    }.get(group, "表现稳定")


def _metric_value(metric: dict[str, object], group: str | None) -> float | None:
    if group == "unjudgeable":
        return None
    if group == "needs_config":
        return 12.0
    if metric.get("metric_resource_id") == "ME_MEDIA_CREATION_SUCCESS_RATE":
        return 63.7
    warning = metric.get("warning_threshold")
    critical = metric.get("critical_threshold")
    if isinstance(critical, (int, float)):
        return float(critical)
    if isinstance(warning, (int, float)):
        return float(warning) - 1.0
    return 64.5


def _metric_yesterday_value(metric: dict[str, object], today_value: float | None) -> float | None:
    if metric.get("metric_resource_id") == "ME_MEDIA_CREATION_SUCCESS_RATE":
        return 75.0
    return today_value
