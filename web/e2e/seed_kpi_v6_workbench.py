"""为 KPI v6 结果工作台 E2E 准备固定数据库与任务现场。"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import timedelta
from pathlib import Path

from app.core.config import settings
from app.models.db import (
    KpiLegacyRecoveryAudit,
    KpiRuleAssignmentGlobalState,
    KpiRuleAssignmentState,
    KpiRuleNetworkAssignment,
    KpiV6MeasurementBinding,
    TaskRecord,
    init_db,
    session_factory,
)
from app.models.schemas import InspectionTask, PackageKind, Summary, SystemInspection, TaskStats
from app.services.store import save_system, save_task_meta
from tests.fixtures.kpi_v6_seed import KpiV6TaskSeed, KpiV6SeedState, seed_kpi_v6_database
from tests.fixtures.make_real_package import build_kpi_v6_log_supplement_fixture

LEGACY_TASK_ID = "task-kpi-v6-legacy-rebuild"
LEGACY_PACKAGE_FILE = "KPI-V6-LEGACY-REBUILD.zip"
SCOPE_FUTURE_TASK_ID = "task-kpi-v6-scope-future"
SCOPE_FUTURE_PACKAGE_FILE = "KPI-V6-SCOPE-FUTURE.zip"
CANDIDATE_SOURCE_NAME = "待人工确认来源列"
RECOVERY_SOURCE_KEY_PREFIX = "e2e:recovery:umf:"


def _write_task_scene(state: KpiV6SeedState, task_seed: KpiV6TaskSeed) -> None:
    """重建任务文件现场；数据库行由 v6 种子负责，不在此处覆盖。"""
    task_dir = settings.output / task_seed.task_id
    upload_dir = settings.uploads / task_seed.task_id
    shutil.rmtree(task_dir, ignore_errors=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(task_seed.package_path, upload_dir / task_seed.package_path.name)

    summary = Summary(total=0, pass_=0, warn=0, fail=0, error=0, skip=0)
    system = SystemInspection(
        package_file=task_seed.package_path.name,
        status="completed",
        summary=summary,
        rules=[],
        version="V6",
        customer={"product": task_seed.network_element_type},
    )
    task = InspectionTask(
        task_id=task_seed.task_id,
        name=f"{task_seed.network_element_type} v6 合成任务",
        mode="online",
        status="completed",
        trigger="api",
        created_at=state.frozen_at - timedelta(minutes=30),
        completed_at=state.frozen_at,
        last_run_at=state.frozen_at,
        duration_ms=1_000,
        stats=TaskStats(total=0, pass_=0, warn=0, fail=0, error=0, skip=0, systems=1),
        system=system,
    )
    save_system(settings.output, task_seed.task_id, system)
    save_task_meta(settings.output, task, sync_db=False)
    log_lines = (
        {
            "ts": "2026-11-05T07:59:59Z",
            "level": "info",
            "message": "v6 KPI 合成任务完成",
            "task_id": task_seed.task_id,
        },
    )
    (task_dir / "execution.log").write_text(
        "".join(f"{json.dumps(line, ensure_ascii=False)}\n" for line in log_lines),
        encoding="utf-8",
    )


def _seed_rule_assignment(state: KpiV6SeedState) -> None:
    """给规则归属场景提供稳定初始归属与 revision。"""
    with session_factory() as session:
        global_state = session.get(KpiRuleAssignmentGlobalState, 1)
        if global_state is None:
            global_state = KpiRuleAssignmentGlobalState(id=1, revision=1, updated_at=state.frozen_at)
            session.add(global_state)
        else:
            global_state.revision = 1
            global_state.updated_at = state.frozen_at
        rule_state = session.get(KpiRuleAssignmentState, "kpi.measurement_units")
        if rule_state is None:
            rule_state = KpiRuleAssignmentState(
                rule_code="kpi.measurement_units",
                revision=1,
                assignment_state="assigned",
                updated_by="e2e-seed",
                updated_at=state.frozen_at,
            )
            session.add(rule_state)
        else:
            rule_state.revision = 1
            rule_state.assignment_state = "assigned"
            rule_state.updated_by = "e2e-seed"
            rule_state.updated_at = state.frozen_at
        session.query(KpiRuleNetworkAssignment).filter(
            KpiRuleNetworkAssignment.rule_code == "kpi.measurement_units"
        ).delete(synchronize_session=False)
        session.add(
            KpiRuleNetworkAssignment(
                rule_code="kpi.measurement_units",
                network_element_type="UMF",
                rule_revision=1,
                created_at=state.frozen_at,
                updated_at=state.frozen_at,
            )
        )
        session.commit()


def _seed_legacy_rebuild_task(state: KpiV6SeedState) -> None:
    """准备无 v6 范围快照、但保留可真实重建原始包的旧任务。"""
    task_dir = settings.output / LEGACY_TASK_ID
    upload_dir = settings.uploads / LEGACY_TASK_ID
    shutil.rmtree(task_dir, ignore_errors=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    package = upload_dir / LEGACY_PACKAGE_FILE
    shutil.copy2(state.umf.package_path, package)
    package_checksum = hashlib.sha256(package.read_bytes()).hexdigest()

    summary = Summary(total=0, pass_=0, warn=0, fail=0, error=0, skip=0)
    system = SystemInspection(
        package_file=LEGACY_PACKAGE_FILE,
        package_checksum=package_checksum,
        version="legacy",
        status="completed",
        summary=summary,
        rules=[],
        customer={"product": "UMF"},
    )
    task = InspectionTask(
        task_id=LEGACY_TASK_ID,
        name="待重建的 KPI 旧任务",
        mode="online",
        status="completed",
        trigger="api",
        created_at=state.frozen_at - timedelta(days=1),
        completed_at=state.frozen_at - timedelta(hours=23),
        last_run_at=state.frozen_at - timedelta(hours=23),
        duration_ms=1_000,
        stats=TaskStats(total=0, pass_=0, warn=0, fail=0, error=0, skip=0, systems=1),
        system=system,
        package_kind=PackageKind.INSPECTION,
    )
    save_system(settings.output, LEGACY_TASK_ID, system)
    save_task_meta(settings.output, task, sync_db=False)

    with session_factory() as session:
        existing = session.get(TaskRecord, LEGACY_TASK_ID)
        if existing is not None:
            session.delete(existing)
            session.flush()
        session.add(
            TaskRecord(
                task_id=LEGACY_TASK_ID,
                name=task.name,
                mode=task.mode.value,
                status=task.status.value,
                trigger=task.trigger.value,
                package_file=LEGACY_PACKAGE_FILE,
                customer={"product": "UMF"},
                package_kind=PackageKind.INSPECTION.value,
                rule_network_element_type="UMF",
                version="legacy",
                stats={},
                created_at=task.created_at,
                completed_at=task.completed_at,
                last_run_at=task.last_run_at,
                duration_ms=task.duration_ms,
                package_checksum=package_checksum,
            )
        )
        session.commit()

    (task_dir / "execution.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-04T09:00:00Z",
                "level": "info",
                "message": "旧版任务完成，无 v6 KPI 范围快照",
                "task_id": LEGACY_TASK_ID,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_scope_future_task(state: KpiV6SeedState) -> None:
    """准备独立旧任务，用于验证停用测量单元只影响后续巡检。"""
    task_dir = settings.output / SCOPE_FUTURE_TASK_ID
    upload_dir = settings.uploads / SCOPE_FUTURE_TASK_ID
    shutil.rmtree(task_dir, ignore_errors=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    package = upload_dir / SCOPE_FUTURE_PACKAGE_FILE
    shutil.copy2(state.umf.package_path, package)
    package_checksum = hashlib.sha256(package.read_bytes()).hexdigest()

    summary = Summary(total=0, pass_=0, warn=0, fail=0, error=0, skip=0)
    system = SystemInspection(
        package_file=SCOPE_FUTURE_PACKAGE_FILE,
        package_checksum=package_checksum,
        version="legacy",
        status="completed",
        summary=summary,
        rules=[],
        customer={"product": "UMF"},
    )
    task = InspectionTask(
        task_id=SCOPE_FUTURE_TASK_ID,
        name="待按当前范围重建的 UMF 任务",
        mode="online",
        status="completed",
        trigger="api",
        created_at=state.frozen_at - timedelta(days=2),
        completed_at=state.frozen_at - timedelta(days=2) + timedelta(minutes=1),
        last_run_at=state.frozen_at - timedelta(days=2) + timedelta(minutes=1),
        duration_ms=1_000,
        stats=TaskStats(total=0, pass_=0, warn=0, fail=0, error=0, skip=0, systems=1),
        system=system,
        package_kind=PackageKind.INSPECTION,
    )
    save_system(settings.output, SCOPE_FUTURE_TASK_ID, system)
    save_task_meta(settings.output, task, sync_db=False)

    with session_factory() as session:
        existing = session.get(TaskRecord, SCOPE_FUTURE_TASK_ID)
        if existing is not None:
            session.delete(existing)
            session.flush()
        session.add(
            TaskRecord(
                task_id=SCOPE_FUTURE_TASK_ID,
                name=task.name,
                mode=task.mode.value,
                status=task.status.value,
                trigger=task.trigger.value,
                package_file=SCOPE_FUTURE_PACKAGE_FILE,
                customer={"product": "UMF"},
                package_kind=PackageKind.INSPECTION.value,
                rule_network_element_type="UMF",
                version="legacy",
                stats={},
                created_at=task.created_at,
                completed_at=task.completed_at,
                last_run_at=task.last_run_at,
                duration_ms=task.duration_ms,
                package_checksum=package_checksum,
            )
        )
        session.commit()

    (task_dir / "execution.log").write_text(
        json.dumps(
            {
                "ts": "2026-11-03T09:00:00Z",
                "level": "info",
                "message": "旧版任务完成，等待验证后续巡检范围",
                "task_id": SCOPE_FUTURE_TASK_ID,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _seed_scope_maintenance(state: KpiV6SeedState) -> None:
    """播种一条历史恢复审计和一条候选绑定，供维护 E2E 使用。"""
    metric_id = state.umf.metric_resource_ids[0]
    recovery_source_key = f"{RECOVERY_SOURCE_KEY_PREFIX}{metric_id}"
    with session_factory() as session:
        session.query(KpiLegacyRecoveryAudit).filter(
            KpiLegacyRecoveryAudit.source_key == recovery_source_key
        ).delete(synchronize_session=False)
        session.query(KpiV6MeasurementBinding).filter_by(
            network_element_type="UMF",
            measurement_unit_id=state.umf.measurement_unit_id,
            raw_source_name=CANDIDATE_SOURCE_NAME,
        ).delete(synchronize_session=False)
        session.add_all(
            [
                KpiLegacyRecoveryAudit(
                    source_table="kpi_measurement_resources",
                    source_record_id=metric_id,
                    source_key=recovery_source_key,
                    network_element_type="UMF",
                    measurement_unit_id=state.umf.measurement_unit_id,
                    metric_resource_id=metric_id,
                    object_kind="metric",
                    before_snapshot={"enabled": False, "metric_resource_id": metric_id},
                    result="failed",
                    error_code="migration_row_error",
                    attempt_count=0,
                    actor=None,
                    source="migration",
                    created_at=state.frozen_at,
                    updated_at=state.frozen_at,
                ),
                KpiV6MeasurementBinding(
                    network_element_type="UMF",
                    measurement_unit_id=state.umf.measurement_unit_id,
                    raw_source_name=CANDIDATE_SOURCE_NAME,
                    base_source_name=CANDIDATE_SOURCE_NAME,
                    metric_resource_id=metric_id,
                    display_unit=None,
                    binding_state="candidate",
                    source_file="PerfResult_20261105000000.zip",
                    origin_task_id=state.umf.task_id,
                    revision=0,
                    legacy_source_key="e2e:candidate:umf:manual-confirm",
                    created_at=state.frozen_at,
                    updated_at=state.frozen_at,
                ),
            ]
        )
        session.commit()


def main() -> None:
    init_db()
    state = seed_kpi_v6_database(
        settings.resolved(settings.sqlite_path),
        seed_root=Path(__file__).resolve().parent / ".tmp" / "kpi-v6-workbench-fixtures",
    )
    _write_task_scene(state, state.umf)
    _write_task_scene(state, state.csp)
    _seed_rule_assignment(state)
    _seed_legacy_rebuild_task(state)
    _seed_scope_future_task(state)
    _seed_scope_maintenance(state)
    build_kpi_v6_log_supplement_fixture(Path(__file__).resolve().parent / ".tmp")


if __name__ == "__main__":
    main()
