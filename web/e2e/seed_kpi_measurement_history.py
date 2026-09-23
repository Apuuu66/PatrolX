"""为测量单元历史对比 E2E 准备真实巡检产物。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.inspectors.kpi.measurement import inspector
from app.models.db import init_db
from app.models.schemas import RuleStatus, Summary, SystemInspection, TaskStats
from app.services.executor import make_result
from app.services.kpi_measurement_units import (
    discover_measurement_bindings,
    import_resource_csv,
    inspect_measurement_files,
    io,
)
from app.services.store import save_rule_result, save_system, save_task_meta
from app.core.config import settings

CURRENT_TASK_ID = "task-kpi-history-current"
HISTORY_TASK_ID = "task-kpi-history-past"
RULE_CODE = "kpi.measurement_units"
HEADER = "container,测量开始时间,测量结束时间,周期(分钟),呼叫请求次数(次)\n"
FILE_NAME = "ne333_Call_Statistics_15_0_202609160000.csv"

CURRENT_CSV = (
    HEADER
    + "pod-a,2026-09-20 10:00:00,2026-09-20 10:15:00,15,108\n"
    + "pod-a,2026-09-20 10:15:00,2026-09-20 10:30:00,15,116\n"
)
HISTORY_CSV = (
    HEADER
    + "pod-a,2026-09-16 10:00:00,2026-09-16 10:15:00,15,101\n"
    + "pod-a,2026-09-17 10:00:00,2026-09-17 10:15:00,15,105\n"
    + "pod-a,2026-09-18 10:00:00,2026-09-18 10:15:00,15,103\n"
)


def _rule_result(task_id: str):
    task_dir = settings.output / task_id
    csv_path = task_dir / FILE_NAME
    files = [(FILE_NAME, csv_path)]
    discover_measurement_bindings(task_id, files)
    inspection = inspect_measurement_files(task_id, files)
    units = inspection["measurement_units"]
    overview = inspection["kpi_overview"]
    summary = f"KPI 测量单元检查通过：{len(units)} 个测量单元；阈值失败 {overview['business_fail_count']}，阈值预警 {overview['business_warn_count']}"
    return make_result(
        inspector,
        status=RuleStatus.PASS,
        summary=summary,
        metrics=[
            {"key": "matched_files", "label": "匹配文件数", "value": 1, "unit": "个"},
            {"key": "unmatched_files", "label": "未匹配文件数", "value": 0, "unit": "个"},
            {"key": "skipped_files", "label": "周期跳过文件数", "value": 0, "unit": "个"},
            {"key": "measurement_units", "label": "测量单元数", "value": len(units), "unit": "个"},
        ],
        metadata={
            "measurement_units": units,
            "files": [FILE_NAME],
            "unmatched_files": [],
            "skipped_files": [],
        },
    )


def _seed_task(task_id: str, csv_body: str, created_at: datetime, completed_at: datetime) -> None:
    task_dir = settings.output / task_id
    upload_dir = settings.uploads / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / FILE_NAME).write_text(csv_body, encoding="utf-8")
    (upload_dir / "kpi-history.zip").write_bytes(b"e2e")

    rule = _rule_result(task_id)
    summary = Summary(total=1, pass_=1, warn=0, fail=0, error=0, skip=0)
    system = SystemInspection(
        package_file="kpi-history.zip",
        status="completed",
        summary=summary,
        rules=[rule.model_copy(update={"metadata": {}, "findings": [], "metrics": []})],
        customer={"device_id": "demo-device-001"},
    )
    from app.models.schemas import InspectionTask

    save_rule_result(settings.output, task_id, rule)
    save_system(settings.output, task_id, system)
    save_task_meta(
        settings.output,
        InspectionTask(
            task_id=task_id,
            name=task_id,
            mode="local",
            status="completed",
            trigger="api",
            created_at=created_at,
            completed_at=completed_at,
            stats=TaskStats.model_validate({"total": 1, "pass": 1, "warn": 0, "fail": 0, "error": 0, "skip": 0, "systems": 1}),
            system=system,
        ),
    )


def main() -> None:
    init_db()
    import_resource_csv(
        io.StringIO("资源id,中文描述,英文描述\nMU_CALL,呼叫统计,Call Statistics\nME_CALL,呼叫请求次数,Call Requests\n")
    )
    _seed_task(
        CURRENT_TASK_ID,
        CURRENT_CSV,
        datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 20, 10, 30, tzinfo=UTC),
    )
    _seed_task(
        HISTORY_TASK_ID,
        HISTORY_CSV,
        datetime(2026, 9, 16, 9, 0, tzinfo=UTC),
        datetime(2026, 9, 18, 10, 30, tzinfo=UTC),
    )


if __name__ == "__main__":
    main()
