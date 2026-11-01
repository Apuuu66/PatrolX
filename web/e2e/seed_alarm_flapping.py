"""为已下线规则的只读详情准备固定历史现场。

规则实现删除后，历史结果仍必须可读。这里的任务、规则结果和台账全部由
静态固定数据构造，不调用活动规则执行器，也不依赖已删除的规则模块。
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.models.db import init_db
from app.models.schemas import (
    InspectionTask,
    Priority,
    RuleCategory,
    RuleResult,
    RuleStatus,
    Severity,
    Summary,
    SystemInspection,
    TaskStats,
)
from app.services import task_db
from app.services.store import save_rule_result, save_system, save_task_meta

TASK_ID = "task-alarm-flapping-e2e"
ALARM_FIXTURE = Path(__file__).parent / "fixtures" / "alarm_flapping_history.json"
CREATED_AT = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 10, 20, 8, 0, 1, tzinfo=UTC)


def _history_rules() -> list[RuleResult]:
    alarm = RuleResult.model_validate(json.loads(ALARM_FIXTURE.read_text(encoding="utf-8")))
    traffic = RuleResult(
        code="traffic.stat",
        name="话务统计检查",
        category=RuleCategory.TRAFFIC,
        priority=Priority.P1,
        execution_order=1,
        status=RuleStatus.SKIP,
        severity=Severity.MEDIUM,
        summary="未匹配到话务统计文件",
        skip_reason="source_patterns 未匹配到文件: ^traffic/.*$",
        executed_at=datetime(2026, 10, 20, 8, 0, 0, 500000, tzinfo=UTC),
        duration_ms=3,
    )
    umf_acc = RuleResult(
        code="log.umf_acc",
        name="UMFAcc 日志巡检",
        category=RuleCategory.LOG,
        priority=Priority.P1,
        execution_order=2,
        status=RuleStatus.WARN,
        severity=Severity.HIGH,
        summary="历史 UMFAcc 日志检查发现告警",
        executed_at=datetime(2026, 10, 20, 8, 0, 0, 800000, tzinfo=UTC),
        duration_ms=12,
    )
    return [alarm, traffic, umf_acc]


def main() -> None:
    init_db()
    task_dir = settings.output / TASK_ID
    upload_dir = settings.uploads / TASK_ID
    shutil.rmtree(task_dir, ignore_errors=True)
    shutil.rmtree(upload_dir, ignore_errors=True)
    task_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "alarm-flapping-history.zip").write_bytes(b"e2e-history")

    rules = _history_rules()
    summary = Summary(total=3, pass_=0, warn=1, fail=1, error=0, skip=1)
    system = SystemInspection(
        package_file="alarm-flapping-history.zip",
        package_checksum="0" * 64,
        version="V900R016C10SPC200",
        status="completed",
        summary=summary,
        rules=rules,
        customer={
            "province": "江苏",
            "operator": "移动",
            "product": "UMF",
            "device_id": "history-device-001",
        },
    )
    task = InspectionTask(
        task_id=TASK_ID,
        name="告警闪断历史样例任务",
        mode="local",
        status="completed",
        trigger="api",
        created_at=CREATED_AT,
        completed_at=COMPLETED_AT,
        last_run_at=CREATED_AT,
        duration_ms=1_000,
        stats=TaskStats.model_validate(
            {"total": 3, "pass": 0, "warn": 1, "fail": 1, "error": 0, "skip": 1, "systems": 1}
        ),
        system=system,
    )
    for rule in rules:
        save_rule_result(settings.output, TASK_ID, rule)
    save_system(settings.output, TASK_ID, system)
    save_task_meta(settings.output, task)
    task_db.publish_from_scene(task)
    print(f"seeded {TASK_ID}: rules=3 fail=1 warn=1 skip=1")


if __name__ == "__main__":
    main()
