"""为磁盘留存治理 E2E 准备 51 个任务现场（034 US2 / T032）。

场景由代表性样例包生成器 `tests/fixtures/make_real_package.py` 派生：同一个真实包
以 51 个不同包名落到各自任务，运行时刻按序号递增，最旧的 1 个（序号 01）会被
`retention.cleanup` 清理。清理只针对本 seed 自己的记录，不触碰其他 E2E 种子任务的现场。

被清理任务额外带完整 KPI 产物（合成测量 CSV → v6 数据库快照），用于验证现场删除后
任务详情、规则结果、KPI 关注项与证据趋势仍可查（FR-002、SC-003）。
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.cli import generate_task_id
from app.core.config import settings
from app.models.db import init_db
from app.models.schemas import (
    InspectionTask,
    RuleResult,
    RuleStatus,
    Summary,
    SystemInspection,
    TaskStats,
)
from app.services import retention, task_db
from app.services.executor import make_result
from app.services.kpi_measurement_units import (
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
)
from app.services.store import save_rule_result, save_system, save_task_meta
from tests.fixtures.make_real_package import build_real_package

TASK_COUNT = 51
# 最旧任务：留存清理的唯一牺牲者，也是重传覆盖重建 E2E 的目标任务。
CLEANED_INDEX = 1
BASE_CREATED_AT = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
KPI_RULE_CODE = "kpi.measurement_units"
KPI_FILE_NAME = "ne333_Call_Statistics_15_0_202609160000.csv"
KPI_CSV = (
    "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"
    "pod-a,2026-09-16 10:00:00,2026-09-16 10:15:00,15,101\n"
    "pod-a,2026-09-17 10:00:00,2026-09-17 10:15:00,15,105\n"
)
DEVICE_ID = "retention-device-001"
KPI_NETWORK_ELEMENT_TYPE = "UMF"
KPI_MEASUREMENT_UNIT_ID = "MU_CALL"
KPI_METRIC_RESOURCE_ID = "ME_CALL"
KPI_DATA_DATE = date(2026, 9, 17)
KPI_CONFIG_FINGERPRINT = hashlib.sha256(
    f"{KPI_NETWORK_ELEMENT_TYPE}:{KPI_MEASUREMENT_UNIT_ID}:{KPI_METRIC_RESOURCE_ID}".encode()
).hexdigest()


def package_name(index: int) -> str:
    return f"retention-scene-{index:02d}.zip"


def task_id_for(index: int) -> str:
    return generate_task_id(package_name(index))


def _kpi_rule(task_id: str) -> RuleResult:
    task_dir = settings.output / task_id
    files = [(KPI_FILE_NAME, task_dir / KPI_FILE_NAME)]
    discover_measurement_bindings(task_id, files)
    inspection = inspect_measurement_files(task_id, files)
    units = inspection["measurement_units"]
    overview = inspection["kpi_overview"]
    return make_result(
        _kpi_inspector(),
        status=RuleStatus.PASS,
        summary=(
            f"KPI 测量单元检查通过：{len(units)} 个测量单元；"
            f"阈值失败 {overview['business_fail_count']}，阈值预警 {overview['business_warn_count']}"
        ),
        metrics=[
            {"key": "matched_files", "label": "匹配文件数", "value": 1, "unit": "个"},
            {"key": "unmatched_files", "label": "未匹配文件数", "value": 0, "unit": "个"},
            {"key": "skipped_files", "label": "周期跳过文件数", "value": 0, "unit": "个"},
            {"key": "measurement_units", "label": "测量单元数", "value": len(units), "unit": "个"},
        ],
        metadata={
            "measurement_units": units,
            "files": [KPI_FILE_NAME],
            "unmatched_files": [],
            "skipped_files": [],
        },
    )


def _kpi_inspector():
    from app.inspectors.kpi.measurement import inspector

    return inspector


def _simple_rule() -> RuleResult:
    return RuleResult(
        code="log.error_density",
        name="日志错误密度",
        category="log",
        priority=1,
        execution_order=0,
        status=RuleStatus.PASS,
        severity="medium",
        summary="日志错误密度正常",
        executed_at=BASE_CREATED_AT,
    )


def _seed_kpi_v6(task_id: str, frozen_at: datetime) -> None:
    """为被清理任务写入可独立留存查询的 v6 KPI 工作台快照。"""
    from app.models.db import (
        KpiTeamFocusItem,
        KpiTeamFocusRevision,
        KpiV6MeasurementResource,
        KpiV6MeasurementUnit,
        TaskKpiMetricResultV6,
        TaskKpiPointV6,
        TaskKpiScopeItem,
        TaskKpiScopeSnapshot,
        TaskRuleScopeItem,
        TaskRuleScopeSnapshot,
        session_factory,
    )

    raw_source_name = "呼叫请求次数(次)"
    config_snapshot = {
        "name_zh": "呼叫请求次数",
        "name_en": raw_source_name,
        "role": "base",
        "is_percentage": False,
        "raw_source_names": [raw_source_name],
        "direction": "lower_better",
        "daily_aggregation": "latest",
    }
    with session_factory() as session:
        focus_revision = session.get(KpiTeamFocusRevision, KPI_NETWORK_ELEMENT_TYPE)
        if focus_revision is None:
            session.add(
                KpiTeamFocusRevision(
                    network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                    revision=1,
                    updated_at=frozen_at,
                )
            )
        else:
            focus_revision.revision = 1
            focus_revision.updated_at = frozen_at
        session.add(
            KpiV6MeasurementUnit(
                network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                measurement_unit_id=KPI_MEASUREMENT_UNIT_ID,
                name_zh="呼叫统计",
                name_en="Call Statistics",
                inspection_enabled=True,
                revision=1,
                config_fingerprint=KPI_CONFIG_FINGERPRINT,
                source="preset",
                origin_task_id=task_id,
                created_at=frozen_at,
                updated_at=frozen_at,
            )
        )
        session.add(
            KpiV6MeasurementResource(
                network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                resource_id=KPI_METRIC_RESOURCE_ID,
                kind="me",
                name_zh="呼叫请求次数",
                name_en=raw_source_name,
                display_order=1,
                metric_group="呼叫",
                direction="lower_better",
                importance="P1",
                source="preset",
                origin_task_id=task_id,
                created_at=frozen_at,
                updated_at=frozen_at,
            )
        )
        session.add(
            KpiTeamFocusItem(
                network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                measurement_unit_id=KPI_MEASUREMENT_UNIT_ID,
                metric_resource_id=KPI_METRIC_RESOURCE_ID,
                added_by="e2e",
                added_at=frozen_at,
            )
        )
        session.add(
            TaskRuleScopeSnapshot(
                task_id=task_id,
                network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                assignment_revision=1,
                registry_fingerprint="f" * 64,
                trigger="api",
                source="task_service",
                frozen_at=frozen_at,
                snapshot_state="frozen",
            )
        )
        session.add(
            TaskRuleScopeItem(
                task_id=task_id,
                rule_code=KPI_RULE_CODE,
                rule_version="3.4.0",
                category="kpi",
                priority=1,
                execution_order=0,
                assignment_snapshot={
                    "network_element_types": [KPI_NETWORK_ELEMENT_TYPE],
                    "assignment_revision": 1,
                },
            )
        )
        session.add(
            TaskKpiScopeSnapshot(
                task_id=task_id,
                network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                team_focus_revision=1,
                config_fingerprint=KPI_CONFIG_FINGERPRINT,
                data_date=KPI_DATA_DATE,
                frozen_at=frozen_at,
                snapshot_payload={
                    "enabled_measurement_unit_ids": [KPI_MEASUREMENT_UNIT_ID],
                    "metric_count": 1,
                    "team_focus_count": 1,
                },
            )
        )
        session.add(
            TaskKpiScopeItem(
                task_id=task_id,
                network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                measurement_unit_id=KPI_MEASUREMENT_UNIT_ID,
                metric_resource_id=KPI_METRIC_RESOURCE_ID,
                metric_kind="base",
                config_snapshot=config_snapshot,
                scope_status="ready",
            )
        )
        session.add(
            TaskKpiMetricResultV6(
                task_id=task_id,
                network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                measurement_unit_id=KPI_MEASUREMENT_UNIT_ID,
                metric_resource_id=KPI_METRIC_RESOURCE_ID,
                source_rule_code=KPI_RULE_CODE,
                decision="pass",
                yesterday_trend="stable",
                today_value=105,
                yesterday_value=101,
                change=4,
                unit="times",
                importance="P1",
                reason="表现稳定",
                effective_point_count=2,
                result_payload={
                    "metric_role": "base",
                    "is_percentage": False,
                    "evidence_available": True,
                    "raw_source_names": [raw_source_name],
                    "source_file": KPI_FILE_NAME,
                    "current_status": "normal",
                    "trend_status": "stable",
                    "configuration_state": "ready",
                },
                result_fingerprint=hashlib.sha256(
                    f"{task_id}:{KPI_MEASUREMENT_UNIT_ID}:{KPI_METRIC_RESOURCE_ID}".encode()
                ).hexdigest(),
                published_at=frozen_at,
            )
        )
        for measured_at, value, line_number in (
            (datetime(2026, 9, 16, 10, 15, tzinfo=UTC), 101, 1),
            (datetime(2026, 9, 17, 10, 15, tzinfo=UTC), 105, 2),
        ):
            session.add(
                TaskKpiPointV6(
                    task_id=task_id,
                    network_element_type=KPI_NETWORK_ELEMENT_TYPE,
                    source_rule_code=KPI_RULE_CODE,
                    measurement_unit_id=KPI_MEASUREMENT_UNIT_ID,
                    metric_resource_id=KPI_METRIC_RESOURCE_ID,
                    object_key="__all__",
                    period_minutes=15,
                    measured_at=measured_at,
                    value=value,
                    source_file=KPI_FILE_NAME,
                    line_number=line_number,
                    point_fingerprint=hashlib.sha256(
                        f"{task_id}:{KPI_MEASUREMENT_UNIT_ID}:{KPI_METRIC_RESOURCE_ID}:{measured_at.isoformat()}".encode()
                    ).hexdigest(),
                )
            )
        session.commit()


def _seed_task(index: int, package_bytes: bytes, checksum: str) -> str:
    task_id = task_id_for(index)
    created_at = BASE_CREATED_AT + timedelta(minutes=index)
    package = package_name(index)
    task_dir = settings.output / task_id
    upload_dir = settings.uploads / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / package).write_bytes(package_bytes)

    if index == CLEANED_INDEX:
        (task_dir / KPI_FILE_NAME).write_text(KPI_CSV, encoding="utf-8")
        rule = _kpi_rule(task_id)
    else:
        rule = _simple_rule()

    stats = TaskStats.model_validate(
        {"total": 1, "pass": 1, "warn": 0, "fail": 0, "error": 0, "skip": 0, "systems": 1}
    )
    system = SystemInspection(
        package_file=package,
        package_checksum=checksum,
        status="completed",
        summary=Summary(total=1, pass_=1, warn=0, fail=0, error=0, skip=0),
        rules=[rule.model_copy(update={"metadata": {}, "findings": [], "metrics": []})],
        version="V1",
        customer={
            "device_id": DEVICE_ID,
            "province": "江苏",
            "operator": "移动",
            **({"product": KPI_NETWORK_ELEMENT_TYPE} if index == CLEANED_INDEX else {}),
        },
    )
    task = InspectionTask(
        task_id=task_id,
        name=f"留存场景 {index:02d}",
        mode="local",
        status="completed",
        trigger="api",
        created_at=created_at,
        completed_at=created_at + timedelta(seconds=30),
        last_run_at=created_at,
        duration_ms=30_000 + index,
        stats=stats,
        system=system,
    )
    save_rule_result(settings.output, task_id, rule)
    save_system(settings.output, task_id, system)
    save_task_meta(settings.output, task)
    task_db.publish_from_scene(task)
    if index == CLEANED_INDEX:
        _seed_kpi_v6(task_id, created_at)
    return task_id


def main() -> None:
    init_db()
    base = settings.output.parent
    build_dir = base / "retention-build"
    source_dir = base / "retention-source"
    shutil.rmtree(build_dir, ignore_errors=True)
    package_file = build_real_package(build_dir)
    package_bytes = package_file.read_bytes()
    checksum = hashlib.sha256(package_bytes).hexdigest()
    source_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package_file, source_dir / package_name(CLEANED_INDEX))

    import_resource_csv(
        io.StringIO(
            "资源id,中文描述,英文描述\n"
            "MU_CALL,呼叫统计,Call Statistics\n"
            "ME_CALL,呼叫请求次数,Call Requests\n"
        )
    )

    task_ids = [_seed_task(index, package_bytes, checksum) for index in range(1, TASK_COUNT + 1)]

    # 只按本 seed 的记录计算保留集合，避免清理其他 E2E 种子任务的现场（FR-004）。
    known_ids = set(task_ids)
    records = [record for record in task_db.list_task_records() if record.task_id in known_ids]
    result = retention.cleanup(records=records)

    report = {
        "package_file": package_name(CLEANED_INDEX),
        "package_checksum": checksum,
        "seeded_task_ids": task_ids,
        "cleaned_task_id": task_id_for(CLEANED_INDEX),
        "newest_task_id": task_id_for(TASK_COUNT),
        "retained_task_ids": sorted(result.retained),
        "removed_task_ids": [
            Path(path).name for path in result.removed_directories if Path(path).parent == settings.output
        ],
        "failed_paths": result.failed_paths,
    }
    (base / "retention-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
